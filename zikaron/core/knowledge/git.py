"""Everything this package asks git, as six invocations and nothing else.

Git is never asked **which files exist** — the filesystem walk is the sole authority on that. It is
asked only *did this file, which the walk found, change since we indexed it*, and *does this
repository consider this file text*. Taking the file set from git instead fails on two ordinary
shapes: a submodule is listed as a gitlink whose path is a directory on disk and whose hash is a
commit rather than content, and a sparse checkout lists a hash for a path that is **absent** from
disk while reporting nothing about it as changed — which would serve chunks forever for a file
nobody can open.

**Every invocation here is batched and takes its paths on stdin under `-z`.** Two properties come
with `-z` and neither is optional. It bounds the **input** as well as the output: a path containing
a newline, fed on a line-separated stdin, is split and answered about as two different paths — with
a plausible answer and a success exit. And it turns off `core.quotePath`, which would otherwise
render such a path in escaped form on output, where it silently fails to match the walk's own
spelling of it.

**Paths cross this boundary as bytes, decoded the way the filesystem decodes them.** A path is the
join key between what the walk found and what git says about it, so the two must produce the same
string for the same bytes; `os.fsdecode`/`os.fsencode` are what `os.scandir` itself uses, including
the surrogate escapes an undecodable byte becomes.

**Paths are not all relative to the same thing, and exactly one call has to be corrected for it.**
`ls-files` reports relative to the working directory and `check-ignore`/`check-attr` echo back the
paths they were given, so all three already agree with the walk. **`status --porcelain` is
relative to the repository root whatever the working directory is**, so for a corpus rooted below
its repository it is reconciled against `rev-parse --show-prefix` before anything joins on it.

**Which invocations *determine* the corpus, and which merely filter it.** `rev-parse` — both the
work-tree probe and the prefix — together with `ls-files`, `status` and `check-ignore` decide what
is a candidate at all, so a failure of any of them means the scan cannot honour the `git_mode` it
was asked for and must fall back to consulting git not at all. `check-attr` runs after the
candidate set is settled and only removes from it, so its failure means *attributes unavailable,
the sniff governs* — flipping the mode there would retroactively invalidate a candidate set
already computed under another one. This module reports "did not answer" for both and leaves the
consequence to its caller, which is the layer that knows which question it was asking.
"""

import asyncio
import os
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

#: How long the one-shot probe may take. Generous against a sub-millisecond call, and present at
#: all because a hung `git` on a network filesystem would otherwise hang whoever is waiting.
_PROBE_TIMEOUT_SECONDS: Final = 5.0

#: How long a batched call over a whole repository's paths may take. Large, because the input can
#: be tens of thousands of paths on a cold filesystem cache, and bounded for the same reason the
#: probe is: a scan that hangs reports nothing, where one that gives up degrades and says so.
_BATCH_TIMEOUT_SECONDS: Final = 120.0

#: The `ls-files -s` modes that name a regular file. An allowlist rather than a list of modes to
#: reject, so a mode nobody anticipated is excluded rather than admitted: `160000` is a submodule
#: gitlink whose hash is a commit and whose path is a directory, and `120000` is a symlink, which
#: the walk refuses on its own account.
_REGULAR_FILE_MODES: Final = frozenset({"100644", "100755"})

#: The status codes that carry a **second** path in the `-z` stream: the new path follows the
#: status letters, and the old path arrives as a bare field with no status prefix at all. A parser
#: expecting every field to begin with two status characters reads that old path as a status line.
_TWO_PATH_CODES: Final = frozenset({"R", "C"})

#: `check-ignore` exits 1 to mean *none of these paths is ignored*, which is an answer and the
#: common one for a documentation tree. Stated as the set of exits that **are** answers rather than
#: as a list of failures, because the outcomes nobody enumerates — death on a signal, an exit 2 on
#: a bad flag — would otherwise be classified as answers, and this command's answer for "nothing
#: ignored" is an empty stdout. That misclassification is indistinguishable from a real answer and
#: silently stops `.gitignore` being applied at all.
_CHECK_IGNORE_ANSWER_EXITS: Final = frozenset({0, 1})

#: One attribute record: the path, the attribute, and its value.
_ATTRIBUTE_RECORD_FIELDS: Final = 3

#: What precedes the tab in one `ls-files -s` record: the mode, the object id and the stage.
_LISTING_HEAD_FIELDS: Final = 3

#: The two status letters and the space after them, which every status entry begins with.
_STATUS_PREFIX_LENGTH: Final = 3


class GitUnavailableError(Exception):
    """A git invocation did not answer.

    One class for every cause — git absent from `PATH`, a directory that is not a work tree, a
    `safe.directory` refusal inside a container, a timeout, a signal — because the caller's
    question is *did this answer*, and an enumeration of causes is precisely how the cause nobody
    listed comes to be treated as an answer. The dubious-ownership refusal is the common modern
    case and is none of the first two.
    """


def _nul_records(payload: bytes) -> list[str]:
    """Split a `-z` stream into its records, decoded as the filesystem decodes paths.

    Exactly one trailing terminator is dropped, and empty records in the middle are kept: some
    `-z` forms emit empty fields as real values, and a split that discards every empty string
    misaligns every record after the first one.
    """
    fields = os.fsdecode(payload).split("\0")
    if fields and fields[-1] == "":
        fields.pop()
    return fields


def _stdin_records(paths: Sequence[str]) -> bytes:
    """Paths as a `-z` stdin stream, every record terminated rather than separated."""
    return b"".join(os.fsencode(path) + b"\0" for path in paths)


def _run(
    arguments: Sequence[str], *, root: Path, stdin: bytes | None, timeout: float
) -> subprocess.CompletedProcess[bytes]:
    """Run one git command in `root`, in binary mode, raising if it could not be run at all.

    `cwd=root` is what makes a relative path mean what the walk means by it: git resolves the paths
    it is given against the **process** working directory rather than against the repository root,
    so a scan of a subdirectory of a repository would otherwise ask about paths that do not exist.

    Raises:
        GitUnavailableError: the command could not be started, or did not finish in time.
    """
    try:
        # A fixed argument vector with no shell in it; `git` is resolved from `PATH`, which is what
        # makes this the same git the operator's own commands use.
        return subprocess.run(  # noqa: S603
            ["git", *arguments],  # noqa: S607
            cwd=root,
            input=stdin,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise GitUnavailableError(f"git {arguments[0]} could not be run in {root}") from error


def _answered(
    completed: subprocess.CompletedProcess[bytes], *, accept: frozenset[int] = frozenset({0})
) -> bytes:
    """This invocation's stdout, or a refusal if its exit status was not one of the answers.

    Raises:
        GitUnavailableError: the exit status is outside `accept`. A negative status means the
            process was killed by a signal, which is covered by the same test rather than by a
            case of its own.
    """
    if completed.returncode not in accept:
        raise GitUnavailableError(
            f"git exited {completed.returncode}: "
            f"{os.fsdecode(completed.stderr).strip() or 'no diagnostic'}"
        )
    return completed.stdout


def _inside_work_tree(root: Path) -> bool:
    completed = _run(
        ["rev-parse", "--is-inside-work-tree"],
        root=root,
        stdin=None,
        timeout=_PROBE_TIMEOUT_SECONDS,
    )
    return completed.returncode == 0 and os.fsdecode(completed.stdout).strip() == "true"


async def inside_work_tree(root: Path) -> bool:
    """Whether git reports `root` as inside a work tree.

    Every failure is the one answer *no*, rather than an enumeration of causes: git missing from
    `PATH`, a directory that is not a repository, and a `safe.directory` refusal inside a container
    all return different things, and the last is the common modern case an enumeration of the first
    two would classify wrongly.
    """
    try:
        return await asyncio.to_thread(_inside_work_tree, root)
    except GitUnavailableError:
        return False


def _parse_listing(payload: bytes) -> dict[str, str]:
    listed: dict[str, str] = {}
    for record in _nul_records(payload):
        head, separator, path = record.partition("\t")
        if not separator:
            continue
        fields = head.split()
        if len(fields) < _LISTING_HEAD_FIELDS or fields[0] not in _REGULAR_FILE_MODES:
            continue
        listed[path] = fields[1]
    return listed


async def list_files(root: Path) -> Mapping[str, str]:
    """Every regular file git tracks under `root`, as path to blob hash.

    The hash is git's own precomputed one, which is what makes change detection cost a subprocess
    rather than a read of every file. It is **not** a hash of the file's bytes — git hashes a header
    plus the content, and applies clean filters on the way — so it is only ever compared against its
    own prior value, never against a content hash.

    Raises:
        GitUnavailableError: git did not answer. The caller must treat the whole scan as
            consulting git not at all, because a candidate set intersected with a failed
            subprocess is an empty corpus wearing the shape of an answer.
    """

    def _listing() -> Mapping[str, str]:
        completed = _run(
            ["ls-files", "-s", "-z"], root=root, stdin=None, timeout=_BATCH_TIMEOUT_SECONDS
        )
        return _parse_listing(_answered(completed))

    return await asyncio.to_thread(_listing)


def _parse_status(payload: bytes, prefix: str) -> set[str]:
    """Every path this status stream reports, as the corpus spells them.

    `prefix` is where the corpus root sits inside its repository, with a trailing separator, or
    empty when the two are the same directory. Paths above the prefix belong to the repository but
    not to this corpus, and are dropped rather than shortened — a sibling of the corpus root could
    otherwise be stripped into a name that collides with one inside it.

    **Dropping them is a cost guard rather than a correctness one, and the difference is worth
    knowing before anyone weakens it.** A path that leaked through could only add a spurious
    member to the changed set, which vetoes the fast path for one file: it is then read and
    hashed, its content compared, and an unchanged file keeps the row it already had. So the harm
    is a wasted read, never a wrong answer — unlike the prefix *stripping* above it, where a
    failure to join is silent staleness.
    """
    reported: set[str] = set()
    records = _nul_records(payload)
    index = 0
    while index < len(records):
        entry = records[index]
        index += 1
        if len(entry) < _STATUS_PREFIX_LENGTH:
            continue
        codes, path = entry[:2], entry[_STATUS_PREFIX_LENGTH:]
        reported.add(path)
        if _TWO_PATH_CODES.intersection(codes) and index < len(records):
            # A rename or copy carries the **new** path here and the **old** one in the next
            # field, bare: no status letters, nothing marking it as a continuation. Consuming it
            # explicitly is what stops the old path being read as a malformed status entry.
            reported.add(records[index])
            index += 1
    return {path.removeprefix(prefix) for path in reported if path.startswith(prefix)}


def _prefix_inside_repository(root: Path) -> str:
    """Where `root` sits inside its repository, with a trailing separator, or empty at the top.

    Raises:
        GitUnavailableError: git did not answer. This decides how the status stream joins, so a
            failure here leaves the whole scan unable to honour its git mode.
    """
    completed = _run(
        ["rev-parse", "--show-prefix"], root=root, stdin=None, timeout=_PROBE_TIMEOUT_SECONDS
    )
    # Only the trailing newline: a directory name may legitimately begin with a space, and this
    # command has no `-z` form to separate the value from its terminator.
    return os.fsdecode(_answered(completed)).rstrip("\n")


async def changed_paths(root: Path) -> frozenset[str]:
    """Every path under the corpus root that git reports as differing from `HEAD` or from the
    index, in either column, spelled relative to that root.

    **Reported relative to the corpus root, which takes an extra call to arrange.** Porcelain
    output is relative to the *repository* root whatever the working directory — unlike
    `ls-files`, which reports relative to it — so for a corpus rooted below its repository the two
    would not join, and the guard would silently match nothing. Measured: from `repo/docs`,
    `ls-files` answers `guide.md` where `status` answers `docs/guide.md`. Left unreconciled, an
    uncommitted edit to a tracked file is cleared as unchanged on every scan until it is
    committed, which is the confidently-stale failure the walk-first design exists to rule out.

    `-uall` rather than the default, which collapses an untracked directory into a single entry
    for the directory and never names the files inside it — so an edited file in one would go
    unreported. A rename contributes both of its paths: the old one is a deletion and the new one
    is a candidate, since this design does not inherit git's rename detection.

    One reported path is not a file: a dirty submodule appears under the directory it lives in.
    That matches no indexed file, so nothing downstream breaks, but it is the one shape in this
    stream that a caller must not assume is a file.

    Raises:
        GitUnavailableError: git did not answer, to either of the two calls this makes.
    """

    def _status() -> frozenset[str]:
        prefix = _prefix_inside_repository(root)
        completed = _run(
            ["status", "--porcelain", "-z", "-uall"],
            root=root,
            stdin=None,
            timeout=_BATCH_TIMEOUT_SECONDS,
        )
        return frozenset(_parse_status(_answered(completed), prefix))

    return await asyncio.to_thread(_status)


async def ignored_paths(root: Path, paths: Sequence[str]) -> frozenset[str]:
    """Which of `paths` `.gitignore` excludes, in one call.

    Asked of git rather than answered by parsing `.gitignore` in process, because doing it
    ourselves means reimplementing nested ignore files, negation re-inclusion, `$GIT_DIR/info/
    exclude` and `core.excludesFile` — a semantics surface wide enough that a divergence would show
    up as files missing from a corpus rather than as an error.

    **`--no-index` is deliberately not passed.** The default consults the index and therefore
    reports a *tracked* ignored file as not ignored, which is git's own rule that ignore patterns
    never affect tracked files. Switching it off reads like a harmless optimisation and inverts
    that rule, dropping tracked-but-ignored files out of the corpus.

    Raises:
        GitUnavailableError: git neither reported ignored paths nor reported that none were ignored.
    """
    if not paths:
        return frozenset()

    def _ignored() -> frozenset[str]:
        return frozenset(
            _nul_records(
                _answered(
                    _run(
                        ["check-ignore", "--stdin", "-z"],
                        root=root,
                        stdin=_stdin_records(paths),
                        timeout=_BATCH_TIMEOUT_SECONDS,
                    ),
                    accept=_CHECK_IGNORE_ANSWER_EXITS,
                )
            )
        )

    return await asyncio.to_thread(_ignored)


def _parse_attributes(payload: bytes, names: Sequence[str]) -> dict[str, dict[str, str]]:
    answers: dict[str, dict[str, str]] = {}
    fields = _nul_records(payload)
    for start in range(0, len(fields) - (_ATTRIBUTE_RECORD_FIELDS - 1), _ATTRIBUTE_RECORD_FIELDS):
        path, attribute, value = fields[start : start + _ATTRIBUTE_RECORD_FIELDS]
        if attribute in names:
            answers.setdefault(path, {})[attribute] = value
    return answers


async def attributes(
    root: Path, paths: Sequence[str], names: Sequence[str]
) -> Mapping[str, Mapping[str, str]]:
    """What `.gitattributes` says about each of `paths`, for each attribute in `names`.

    The answer comes from the **working-tree** `.gitattributes` rather than the committed one, so
    an uncommitted edit to it changes which files a corpus admits with no commit and no change to
    any indexed file — which is why this has to be asked about every candidate on every scan, not
    only about the ones being read.

    A value is not a boolean: git answers `set`, `unset`, `unspecified`, or an arbitrary string.
    Interpreting them is not this module's job.

    Raises:
        GitUnavailableError: git did not answer. Unlike the calls above, this one does not decide
            what is a candidate, so a caller may proceed without it.
    """
    if not paths or not names:
        return {}

    def _attributes() -> Mapping[str, Mapping[str, str]]:
        return _parse_attributes(
            _answered(
                _run(
                    ["check-attr", "--stdin", "-z", *names],
                    root=root,
                    stdin=_stdin_records(paths),
                    timeout=_BATCH_TIMEOUT_SECONDS,
                )
            ),
            names,
        )

    return await asyncio.to_thread(_attributes)
