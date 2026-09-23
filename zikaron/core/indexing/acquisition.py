"""Fetching the pinned embedding artefact, and proving the bytes that arrive are the pinned ones.

**Digests are checked whenever bytes come off the network through this path, and never on a warm
start.** (Through *this* path: a `$FASTEMBED_CACHE_PATH` shared with another fastembed consumer that
fetched the same repository can present a snapshot Zikaron never hashed. Same source and same
revision, so the threat is unchanged.) A warm start
checks only that the five files are *present*, which costs a `stat` each. The reason is measured:
hashing them costs 331-396 ms under load — not the 185 ms an unloaded in-process timing suggests,
because the walk is CPU-bound — and `push.py` gives the whole cold-start sequence 2.0 s before the
hook degrades and the user's first message loses its memories. A/B at M17's load cell, four
alternating arms: with the walk, 0 to 1 runs in 5 finished inside that budget; without it, 5/5
(`research/m30-verify-cost.md`). Verifying on every start bought nothing the acquisition-time check
does not, and cost the guarantee M17 exists to hold.

**What that trades away, stated rather than implied.** Corruption *after* acquisition — disk rot, a
file replaced on disk — is no longer caught at startup. `zikaron doctor` verifies the full digest
set on demand and is the channel for it. What remains covered is the threat the pin was built for: a
source handing over bytes that are not the pinned ones, checked at the moment it does so.

**The warm call passes `local_files_only=True` together with the 40-hex revision, and that pair is
what makes "no network on a warm start" hold by construction rather than by cache state.** With a
commit hash, `snapshot_download` skips `repo_info`; but on the *online* path the file listing still
comes from the on-disk tree cache and, when `trees/<sha>.json` is absent, from one `list_repo_tree`
call — whose presence is an artefact of whichever `huggingface_hub` populated the cache.
`local_files_only=True` removes that last door: `_raise_if_incomplete_snapshot` returns without
touching an API object when the tree cache is missing. So the sequence is warm, then online only if
the warm call says the files are not all here.

**The one re-fetch is `force_download=True`, and nothing here deletes a file in order to replace
it.** The cache stores content at `blobs/<etag>` with `snapshots/<sha>/<file>` as a symlink to it,
and when the blob exists and the pointer does not, `snapshot_download` re-links without downloading.
So deleting the file and calling it again deletes the symlink, re-links the same corrupt blob,
mismatches again, and reports *upstream differs* to a user whose disk is bad — the two diagnoses
swapped. Only `force_download` replaces an existing destination. *(`_discard` does delete, and is
the one exception: it discards a snapshot already proved not to be the artefact and fetches nothing,
which is the opposite of deleting in order to repair. Its own docstring has the argument, and the
invariant it holds.)*

**A second mismatch is a failure, never another *forced* fetch.** After the discard a second call in
one process finds no snapshot, so the warm call falls through to one plain online call, which
re-links the existing blobs and transfers no bytes before the refusal is raised. The bound is **one
re-fetch per process per artefact**, so a lazily reconstructed encoder is not a fresh licence to
download. It is not
durable across processes: a source serving the wrong bytes costs one extra 64 MB *per service
start*, and the service is respawned by any client that finds the socket absent. That is the
accepted cost of a bound that needs no state on disk, and it ends when an upgrade carries a new pin.
"""

import contextlib
import hashlib
import shutil
from pathlib import Path
from typing import Final, NamedTuple

from zikaron.core.errors import BadConfigSource, ErrorCode, ZikaronError
from zikaron.core.indexing.model_pin import PinnedArtifact

#: Read in 1 MiB blocks: the largest pinned file is 64 MB, and hashing it through one `read_bytes`
#: would hold the whole artefact in memory on the cold-start path M17 fought for.
_HASH_BLOCK_BYTES: Final = 1024 * 1024

#: Artefacts already re-fetched in this process, as `<repo_id>@<revision>`. Module state because the
#: bound the design states is per process, and an `Encoder` may be constructed more than once in
#: one — a lazy reload must not be a second licence to download.
_REFETCHED: set[str] = set()


def _digest(path: Path) -> str:
    """The file's SHA256, following the symlink into the blob it points at."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(_HASH_BLOCK_BYTES):
            digest.update(block)
    return digest.hexdigest()


class Verification(NamedTuple):
    """Which pinned files are not there, and which are there with the wrong bytes.

    **Kept apart because the two faults have different remedies, and `doctor` is what states them.**
    Absent files a start will fetch; a present file with wrong bytes it will not touch, because a
    warm start checks presence only — so the advice for one is "start the service" and for the other
    "remove the snapshot first" (`doctor/checks.py`). *The split is no longer what chooses between
    filling and forcing: `missing_files` does that, before any hashing happens.*
    """

    absent: tuple[str, ...]
    wrong: tuple[str, ...]

    def complete(self) -> bool:
        return not self.absent and not self.wrong

    def all_files(self) -> tuple[str, ...]:
        return tuple(sorted(self.absent + self.wrong))


def missing_files(pin: PinnedArtifact, directory: Path) -> tuple[str, ...]:
    """Which pinned files are absent — a `stat` each, no reading.

    The whole warm-start check. It exists to catch an interrupted fetch, which leaves a snapshot
    directory the warm call returns rather than refuses; handing that to fastembed fails obscurely.
    It deliberately says nothing about the *contents* of the files that are present.
    """
    return tuple(name for name in sorted(pin.digests) if not (directory / name).is_file())


def verify(pin: PinnedArtifact, directory: Path) -> Verification:
    """Check a snapshot directory against the pin. Public because `doctor` reports the same walk.

    Two implementations of one predicate is two answers to "are these the pinned bytes" that can
    disagree the day one of them changes.

    **Called on the fetch paths and by `doctor`, never on a warm start** — the module docstring has
    the measurement that decided it.
    """
    absent = []
    wrong = []
    for name, expected in sorted(pin.digests.items()):
        path = directory / name
        if not path.is_file():
            absent.append(name)
        elif _digest(path) != expected:
            wrong.append(name)
    return Verification(absent=tuple(absent), wrong=tuple(wrong))


def _mismatch_failure(
    pin: PinnedArtifact, mismatched: Verification, *, stranded: Path | None = None
) -> ZikaronError:
    """`bad_config` naming the configured model, as every other artefact refusal here does.

    No bespoke error type, following M29's withdrawal: the wire table is a fixed set and the thing
    that is wrong is still which artefact the configuration resolved to. The remedy is in
    `expected`, because that is the field a reader is shown.

    Args:
        stranded: the snapshot directory `_discard` could not remove, if it could not. Named in the
            remedy because the next warm start will otherwise trust it: refusing here while leaving
            bytes this process proved wrong in the place a warm start looks is the one outcome worth
            more than a sentence.
    """
    remedy = (
        f"{pin.repo_id} at revision {pin.revision} matching this release's pinned digests; "
        f"{', '.join(mismatched.all_files())} did not, after one re-fetch. "
        "Upgrade zikaron, which is what carries a new pin"
    )
    if stranded is not None:
        remedy += (
            f". Delete {stranded} by hand first — it could not be removed, and a later start "
            "would use it"
        )
    return ZikaronError(
        ErrorCode.BAD_CONFIG,
        source=BadConfigSource.FILE,
        file="<embedding artifact>",
        key="embedding.embed_model",
        value=pin.model_name,
        expected=remedy,
    )


def _discard(directory: Path) -> bool:
    """Remove a snapshot this process has proved wrong. True if it is gone afterwards.

    **The invariant it serves: at no instant does a complete snapshot this process knows to be wrong
    exist on disk.** A warm start checks presence, not contents, so any moment where all five
    pointers resolve to bytes already proved wrong is a moment a concurrent or subsequent process
    loads them. There are two such moments and both are closed by calling this before them — after a
    failed verification, and **before the forced re-fetch**, which is the longer window by far:
    `snapshot_download` creates a pointer only `if not os.path.exists(pointer_path)`
    (`file_download.py`), so under `force_download` every existing pointer stays aimed at the old
    blob for the whole download, until the replacement blob's atomic move lands. Interrupt there and
    the wrong bytes are what the next start finds.

    Discarding first also removes a second defect of that same line: when the server's etag differs
    from the on-disk blob's, the download lands at a *new* blob and the surviving pointer is never
    re-aimed, so the re-fetch cannot succeed at all.

    **This is not the delete the module docstring rules out.** That one deletes a file in order to
    *repair* it, which re-links the same blob and reports the wrong diagnosis. This discards
    symlinks already proved not to be the artefact, and fetches nothing.
    """
    with contextlib.suppress(OSError):
        shutil.rmtree(directory)
    return not directory.exists()


def _snapshot(
    pin: PinnedArtifact, *, cache_dir: Path, local_files_only: bool, force_download: bool = False
) -> Path:
    from huggingface_hub import snapshot_download  # noqa: PLC0415

    return Path(
        snapshot_download(
            repo_id=pin.repo_id,
            revision=pin.revision,
            cache_dir=str(cache_dir),
            allow_patterns=list(pin.filenames),
            local_files_only=local_files_only,
            force_download=force_download,
        )
    )


def artifact_directory(pin: PinnedArtifact, *, cache_dir: Path) -> Path:
    """The directory holding the pinned artefact's files, fetched if absent and verified if fetched.

    Args:
        pin: which artefact, at which revision, hashing to what.
        cache_dir: the durable per-user cache `model_cache` resolves.

    Returns:
        The snapshot directory, suitable for fastembed's `specific_model_path`.

    Raises:
        ZikaronError: `BAD_CONFIG` naming `embedding.embed_model`, when the files still do not
            match the pin after the one permitted re-fetch.
    """
    from huggingface_hub.errors import (  # noqa: PLC0415
        IncompleteSnapshotError,
        LocalEntryNotFoundError,
    )

    try:
        directory = _snapshot(pin, cache_dir=cache_dir, local_files_only=True)
    except (LocalEntryNotFoundError, IncompleteSnapshotError):
        directory = _snapshot(pin, cache_dir=cache_dir, local_files_only=False)
    else:
        # The warm path, and the only one that does not hash: every pinned file is already here, so
        # nothing arrived from the network to check. An interrupted fetch is what `missing_files`
        # catches — the warm call *returns* a partial snapshot rather than refusing one, and a plain
        # online call fills only the gaps where `force_download` would pay for all five again.
        if not missing_files(pin, directory):
            return directory
        directory = _snapshot(pin, cache_dir=cache_dir, local_files_only=False)

    # Reached only when bytes have just come off the network, which is what is being checked.
    checked = verify(pin, directory)
    if checked.complete():
        return directory

    # Discarded *before* the re-fetch as well as after it, which is the longer of the two windows
    # where a complete-but-wrong snapshot would sit where a warm start looks. `_discard` has the
    # mechanism; the ordering is the whole point, so it does not move.
    gone = _discard(directory)
    claim = f"{pin.repo_id}@{pin.revision}"
    if claim in _REFETCHED:
        raise _mismatch_failure(pin, checked, stranded=None if gone else directory)
    _REFETCHED.add(claim)
    directory = _snapshot(pin, cache_dir=cache_dir, local_files_only=False, force_download=True)
    checked = verify(pin, directory)
    if not checked.complete():
        gone = _discard(directory)
        raise _mismatch_failure(pin, checked, stranded=None if gone else directory)
    return directory
