"""Fetching the pinned artefact: which calls are made, and that the two mismatch causes differ.

**The defect this file exists to prevent is a suite that exercises only the corrupt-local branch.**
Both branches end in "the digests did not match", and an executor who implements the re-fetch as a
delete passes the source-is-wrong branch while failing the corrupt-local one — then "fixes" it by
relaxing the test. So every case below asserts the *call sequence* as well as the outcome.

`snapshot_download` is stubbed rather than the wrapper around it, so the arguments the wrapper
builds — the revision, `allow_patterns`, and which of `local_files_only`/`force_download` is set on
which attempt — are themselves under test.
"""

import hashlib
import shutil
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final

import pytest
from huggingface_hub.errors import LocalEntryNotFoundError

from zikaron.core.errors import ErrorCode, ZikaronError
from zikaron.core.indexing import acquisition
from zikaron.core.indexing.model_pin import PINNED_ARTIFACTS, PinnedArtifact, pin_for

_SERVED: Final = {
    "config.json": b'{"served": true}',
    "model_optimized.onnx": b"onnx weights, notionally",
    "special_tokens_map.json": b"{}",
    "tokenizer.json": b'{"tokenizer": true}',
    "tokenizer_config.json": b'{"config": true}',
}

_PIN: Final = PinnedArtifact(
    model_name="fake/model",
    repo_id="fake/model-onnx-q",
    revision="0" * 39 + "a",
    digests=MappingProxyType(
        {name: hashlib.sha256(content).hexdigest() for name, content in _SERVED.items()}
    ),
)


@dataclass
class _Call:
    local_files_only: bool
    force_download: bool
    revision: str
    allow_patterns: list[str]


class _Hub:
    """A `snapshot_download` stand-in over one directory, recording what it was asked for.

    `serving` is what the *source* hands back, which a test sets independently of what is already
    on disk — that separation is the whole point, since the two mismatch branches differ only in
    whether the source is good.
    """

    def __init__(self, snapshot: Path) -> None:
        self.snapshot = snapshot
        self.serving: dict[str, bytes] = dict(_SERVED)
        self.calls: list[_Call] = []
        #: Models a damaged transfer rather than a bad source: the first download lands wrong and
        #: the re-fetch lands right, which is what separates the two mismatch causes.
        self.on_second_fetch_serve_correctly = False
        #: Raised from inside the forced re-fetch, before it writes. Models a process killed
        #: mid-download — the window in which pointers to bytes already proved wrong would survive.
        self.raise_on_forced_fetch: BaseException | None = None
        self._fetches = 0

    # Every argument spelled out, rather than swallowed by `**kwargs`: the call shape is part of
    # what is under test, so a wrapper that stopped passing one should fail here.
    def __call__(  # noqa: PLR0913
        self,
        *,
        repo_id: str,  # noqa: ARG002
        revision: str,
        cache_dir: str,  # noqa: ARG002
        allow_patterns: list[str],
        local_files_only: bool,
        force_download: bool,
    ) -> str:
        self.calls.append(_Call(local_files_only, force_download, revision, allow_patterns))
        complete = self.snapshot.is_dir() and all(
            (self.snapshot / name).is_file() for name in _SERVED
        )
        if local_files_only:
            # **A partial snapshot is returned, not refused, and that is the real behaviour.** With
            # a commit hash and no `trees/<sha>.json`, `_raise_if_incomplete_snapshot` returns
            # without checking, so an interrupted first fetch comes back as a directory missing
            # files. A stub that raised here would be stricter than the library and would hide the
            # case the caller has a branch for.
            if not self.snapshot.is_dir():
                raise LocalEntryNotFoundError("nothing cached")
            return str(self.snapshot)
        if complete and not force_download:
            return str(self.snapshot)
        if force_download and self.raise_on_forced_fetch is not None:
            raise self.raise_on_forced_fetch
        self._fetches += 1
        serving = (
            dict(_SERVED)
            if self.on_second_fetch_serve_correctly and self._fetches > 1
            else self.serving
        )
        self.snapshot.mkdir(parents=True, exist_ok=True)
        for name, content in serving.items():
            (self.snapshot / name).write_bytes(content)
        return str(self.snapshot)

    def write_on_disk(self, content: dict[str, bytes]) -> None:
        self.snapshot.mkdir(parents=True, exist_ok=True)
        for name, body in content.items():
            (self.snapshot / name).write_bytes(body)


@pytest.fixture(autouse=True)
def _forget_refetches() -> Iterator[None]:
    """The re-fetch bound is per process, and a test process runs many installs' worth."""
    acquisition._REFETCHED.clear()
    yield
    acquisition._REFETCHED.clear()


@pytest.fixture
def hub(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _Hub:
    stub = _Hub(tmp_path / "cache" / "snapshots" / _PIN.revision)
    monkeypatch.setattr("huggingface_hub.snapshot_download", stub)
    return stub


def _fetch(hub: _Hub, tmp_path: Path) -> Path:  # noqa: ARG001
    return acquisition.artifact_directory(_PIN, cache_dir=tmp_path / "cache")


class TestTheWarmPath:
    def test_a_complete_cache_is_used_without_an_online_call(
        self, hub: _Hub, tmp_path: Path
    ) -> None:
        hub.write_on_disk(_SERVED)
        assert _fetch(hub, tmp_path) == hub.snapshot
        assert [call.local_files_only for call in hub.calls] == [True]

    def test_the_warm_call_carries_the_full_length_revision(
        self, hub: _Hub, tmp_path: Path
    ) -> None:
        """Only a revision matching `REGEX_COMMIT_HASH` skips `repo_info`; a tag or a short form
        costs an HTTPS round-trip on every service start."""
        hub.write_on_disk(_SERVED)
        _fetch(hub, tmp_path)
        assert hub.calls[0].revision == _PIN.revision
        assert len(hub.calls[0].revision) == 40

    def test_only_the_pinned_filenames_are_asked_for(self, hub: _Hub, tmp_path: Path) -> None:
        hub.write_on_disk(_SERVED)
        _fetch(hub, tmp_path)
        assert hub.calls[0].allow_patterns == sorted(_SERVED)


class TestTheColdPath:
    def test_an_absent_cache_falls_through_to_one_online_call(
        self, hub: _Hub, tmp_path: Path
    ) -> None:
        assert _fetch(hub, tmp_path) == hub.snapshot
        assert [(c.local_files_only, c.force_download) for c in hub.calls] == [
            (True, False),
            (False, False),
        ]


class TestAWarmStartDoesNotHash:
    """**The measured decision**: hashing on every start costs 331-396 ms under load and pushes the
    cold-start sequence past `push._DEADLINE_SECONDS`, losing the user's first message
    (`research/m30-verify-cost.md`). Nothing arrives from the network on a warm start, so nothing is
    checked — and the trade is that on-disk corruption is `zikaron doctor`'s to find, not startup's.
    """

    def test_a_complete_but_corrupt_cache_is_used_without_a_refetch(
        self, hub: _Hub, tmp_path: Path
    ) -> None:
        hub.write_on_disk({**_SERVED, "tokenizer.json": b"corrupted on this disk"})
        assert _fetch(hub, tmp_path) == hub.snapshot
        assert [call.local_files_only for call in hub.calls] == [True], (
            "a warm start must make no online call, and must not hash to discover it need not"
        )
        assert (hub.snapshot / "tokenizer.json").read_bytes() == b"corrupted on this disk"

    def test_the_full_walk_doctor_runs_still_finds_it(self, hub: _Hub, tmp_path: Path) -> None:
        """The guarantee did not disappear, it moved — asserted rather than left to prose.

        This calls `verify` directly, which is the function `doctor` runs; `check_model_cache`
        resolves its own `models--<org>--<name>/snapshots/<rev>` layout that this stub does not
        build, and `test_doctor.py` covers that surface.
        """
        hub.write_on_disk({**_SERVED, "tokenizer.json": b"corrupted on this disk"})
        _fetch(hub, tmp_path)
        assert acquisition.verify(_PIN, hub.snapshot).wrong == ("tokenizer.json",)


class TestBytesOffTheNetworkAreAlwaysChecked:
    """Same symptom, opposite remedies: one is a damaged download, the other is the source."""

    def test_a_download_that_lands_wrong_triggers_exactly_one_forced_refetch(
        self, hub: _Hub, tmp_path: Path
    ) -> None:
        """Cold cache, and the first fetch lands one bad file — a damaged transfer rather than a
        bad source, since the second attempt serves the pinned bytes."""
        hub.serving["tokenizer.json"] = b"damaged in transit"
        hub.on_second_fetch_serve_correctly = True
        assert _fetch(hub, tmp_path) == hub.snapshot
        assert [(c.local_files_only, c.force_download) for c in hub.calls] == [
            (True, False),
            (False, False),
            (False, True),
        ]
        assert (hub.snapshot / "tokenizer.json").read_bytes() == _SERVED["tokenizer.json"]

    def test_a_source_serving_wrong_bytes_fails_once_and_downloads_nothing_further(
        self, hub: _Hub, tmp_path: Path
    ) -> None:
        hub.serving["tokenizer.json"] = b"still wrong"
        with pytest.raises(ZikaronError) as raised:
            _fetch(hub, tmp_path)
        assert raised.value.code is ErrorCode.BAD_CONFIG
        assert len(hub.calls) == 3, "a fourth attempt is the forever-loop this bound exists against"

    def test_the_failure_names_the_file_the_revision_and_the_remedy(
        self, hub: _Hub, tmp_path: Path
    ) -> None:
        hub.serving["tokenizer.json"] = b"still wrong"
        with pytest.raises(ZikaronError) as raised:
            _fetch(hub, tmp_path)
        expected = str(raised.value.data["expected"])
        assert "tokenizer.json" in expected
        assert _PIN.revision in expected
        assert "Upgrade zikaron" in expected

    def test_a_file_the_source_never_sends_counts_as_missing_rather_than_crashing(
        self, hub: _Hub, tmp_path: Path
    ) -> None:
        """The digest walk must not raise `OSError` from opening a file that is not there."""
        hub.serving.pop("config.json")
        with pytest.raises(ZikaronError) as raised:
            _fetch(hub, tmp_path)
        assert "config.json" in str(raised.value.data["expected"])


class TestAnInterruptedFirstFetch:
    """A snapshot with some files linked and the rest missing, which is what Ctrl-C leaves.

    **The warm call returns that directory rather than raising**, so the repair path is chosen by
    what `verify` found — and an absent file must not cost a forced re-download of all five.
    """

    def test_missing_files_are_filled_without_forcing(self, hub: _Hub, tmp_path: Path) -> None:
        partial = {name: body for name, body in _SERVED.items() if name != "model_optimized.onnx"}
        hub.write_on_disk(partial)
        assert _fetch(hub, tmp_path) == hub.snapshot
        assert [(c.local_files_only, c.force_download) for c in hub.calls] == [
            (True, False),
            (False, False),
        ]
        assert not acquisition._REFETCHED, "filling a gap must not spend the re-fetch budget"

    def test_the_fill_is_verified_because_those_bytes_did_arrive(
        self, hub: _Hub, tmp_path: Path
    ) -> None:
        """A partial snapshot is the one warm case that still hashes — the fill fetched something,
        and what a fetch delivers is always checked. Here the source is bad, so it must fail."""
        partial = {name: body for name, body in _SERVED.items() if name != "config.json"}
        hub.write_on_disk(partial)
        hub.serving["config.json"] = b"wrong bytes from the source"
        with pytest.raises(ZikaronError):
            _fetch(hub, tmp_path)
        assert [c.force_download for c in hub.calls] == [False, False, True]


class TestTheRefetchBoundIsPerProcess:
    def test_a_second_call_in_one_process_forces_nothing_further(
        self, hub: _Hub, tmp_path: Path
    ) -> None:
        """A lazily reconstructed encoder must not be a fresh licence to fetch 64 MB."""
        hub.serving["tokenizer.json"] = b"still wrong"
        with pytest.raises(ZikaronError):
            _fetch(hub, tmp_path)
        before = len(hub.calls)
        with pytest.raises(ZikaronError):
            _fetch(hub, tmp_path)
        assert [(c.local_files_only, c.force_download) for c in hub.calls[before:]] == [
            (True, False),
            (False, False),
        ], (
            "the budget is spent, so no forced fetch — but the discard leaves no snapshot, so the "
            "warm call falls through to one plain online call that re-links and transfers nothing"
        )


class TestAFailedAcquisitionLeavesNothingToTrust:
    """**The hole the warm-start decision opens, closed where it opens.** Presence is all a warm
    start checks, so a snapshot left behind by a failed acquisition would be complete, unverified
    and used by the next process — known-bad bytes passing silently.
    """

    def test_the_snapshot_is_gone_after_a_source_serves_wrong_bytes(
        self, hub: _Hub, tmp_path: Path
    ) -> None:
        hub.serving["tokenizer.json"] = b"still wrong"
        with pytest.raises(ZikaronError):
            _fetch(hub, tmp_path)
        assert not hub.snapshot.exists(), (
            "a proven-wrong snapshot left on disk is what the next warm start would trust"
        )

    def test_a_kill_during_the_forced_refetch_leaves_nothing_complete(
        self, hub: _Hub, tmp_path: Path
    ) -> None:
        """**The longer of the two windows, and the one `_discard`'s ordering exists for.**
        `snapshot_download` creates a pointer only when one does not already exist, so under
        `force_download` every existing pointer keeps resolving to the old blob for the whole
        download. A process killed there would leave five files present — and a warm start checks
        presence — so the bytes this process proved wrong become what the next one loads.
        """
        hub.serving["tokenizer.json"] = b"damaged"
        hub.raise_on_forced_fetch = KeyboardInterrupt()
        with pytest.raises(KeyboardInterrupt):
            _fetch(hub, tmp_path)
        assert acquisition.missing_files(_PIN, hub.snapshot), (
            "a warm start would find every file present and load bytes already proved wrong"
        )

    def test_a_snapshot_that_cannot_be_removed_is_named_in_the_refusal(
        self, hub: _Hub, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """**Refusing while leaving those bytes where a warm start looks is the case the remedy is
        for**, so the remedy has to name the directory — and the second assertion is why: the next
        call trusts exactly what could not be removed.
        """

        real_rmtree = shutil.rmtree

        def _refuse(path: object, *args: object, **kwargs: object) -> None:  # noqa: ARG001
            raise OSError("read-only filesystem")

        hub.serving["tokenizer.json"] = b"still wrong"
        monkeypatch.setattr(shutil, "rmtree", _refuse)
        with pytest.raises(ZikaronError) as raised:
            _fetch(hub, tmp_path)
        expected = str(raised.value.data["expected"])
        assert str(hub.snapshot) in expected
        assert "by hand" in expected

        # Restored by name rather than with `monkeypatch.undo()`, which would also revert the
        # `hub` fixture's patch of `snapshot_download` and send the next call to the real network.
        monkeypatch.setattr(shutil, "rmtree", real_rmtree)
        before = len(hub.calls)
        assert _fetch(hub, tmp_path) == hub.snapshot
        assert [call.local_files_only for call in hub.calls[before:]] == [True]
        assert (hub.snapshot / "tokenizer.json").read_bytes() == b"still wrong", (
            "the hazard the remedy exists for: a later call warm-starts into the bytes that could "
            "not be removed and uses them"
        )

    def test_the_spent_budget_site_also_names_a_stranded_snapshot(
        self, hub: _Hub, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The *other* raise site — the one reached once the re-fetch budget is already spent.

        Its `stranded` argument is unreached by the test above, so replacing it with `None` would
        redden nothing; this is the sequence that reaches it.
        """

        def _refuse(path: object, *args: object, **kwargs: object) -> None:  # noqa: ARG001
            raise OSError("read-only filesystem")

        hub.serving["tokenizer.json"] = b"still wrong"
        with pytest.raises(ZikaronError):
            _fetch(hub, tmp_path)  # spends the budget, discards succeed
        monkeypatch.setattr(shutil, "rmtree", _refuse)
        with pytest.raises(ZikaronError) as raised:
            _fetch(hub, tmp_path)  # re-lands the wrong bytes; the pre-re-fetch discard now fails
        assert str(hub.snapshot) in str(raised.value.data["expected"])

    def test_the_next_process_therefore_acquires_again(self, hub: _Hub, tmp_path: Path) -> None:
        """Modelled by clearing the per-process budget, which is what a new process starts with."""
        hub.serving["tokenizer.json"] = b"still wrong"
        with pytest.raises(ZikaronError):
            _fetch(hub, tmp_path)
        acquisition._REFETCHED.clear()
        hub.serving = dict(_SERVED)
        assert _fetch(hub, tmp_path) == hub.snapshot
        assert hub.calls[-1].local_files_only is False, "it fetched rather than trusting the ruins"


class TestThePinItself:
    def test_every_revision_is_a_full_length_commit_hash(self) -> None:
        for pin in PINNED_ARTIFACTS.values():
            assert len(pin.revision) == 40
            assert set(pin.revision) <= set("0123456789abcdef")

    def test_every_digest_is_a_sha256(self) -> None:
        for pin in PINNED_ARTIFACTS.values():
            for name, digest in pin.digests.items():
                assert len(digest) == 64, name
                assert set(digest) <= set("0123456789abcdef"), name

    def test_the_shipped_default_model_is_pinned(self) -> None:
        """The config default and the pin table are two statements of one artefact."""
        from zikaron.core.config.keys import CONFIG_KEYS  # noqa: PLC0415

        default = next(
            key.default
            for key in CONFIG_KEYS
            if (key.section.value, key.name)
            == (
                "embedding",
                "embed_model",
            )
        )
        assert pin_for(str(default)) is not None

    def test_an_unpinned_model_is_reported_rather_than_refused(self) -> None:
        """D20 keeps the model a config key, so a model this table does not name falls through to
        fastembed's own acquisition — the behaviour every install had before the pin existed."""
        assert pin_for("some/other-model") is None
