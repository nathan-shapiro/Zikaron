"""Putting the shipped artefacts on disk, including the one operation that touches a file the user
owns.

`architecture.md` §"The install contract" is normative. Three rules run through everything here:

- **Everything is checked before anything is written.** A `plan_*` function parses and guards the
  file it would touch and produces the document it *would* write, touching nothing; `commit_merge`
  writes it. An earlier arrangement wrote the shipped files first and discovered a malformed config
  afterwards, which left a project half-installed — the exact outcome the contract's own ordering
  exists to prevent.
- **Refuse rather than overwrite; keep rather than clobber.** A shipped file whose bytes are already
  what this install ships is kept and reported; one that differs is backed up and refreshed, which
  is what makes a re-run after an *upgrade* correct rather than merely safe. A Zikaron entry in a
  file the user owns whose **ownership** differs from what this install would write is a *refusal*,
  because that means another install owns it — the interpreter path and the mode for a server
  entry, the command for a hook entry (under Claude Code, a hook group's command list). A
  difference outside those is an upgrade that is merged and reported (`ownership.py`, and
  `design/architecture.md` §"The install contract").
- **A merge is backed up first, and the first backup wins.** `<config>.bak` is written only when
  nothing is there — not even a dangling symlink — because overwriting it on every run would replace
  the pristine original with the copy the first install had already modified. **A merge that
  changes nothing writes nothing**, backup included, so a re-run leaves the file as it was.
"""

import errno
import json
import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

from zikaron.hook.components import Components
from zikaron.install.assets import SKILL_NAME
from zikaron.install.code_knowledge import DOCUMENT_SKILL_NAME, DOCUMENTER_AGENT_NAME
from zikaron.install.entries import CONSOLIDATOR_AGENT_NAME, Commands
from zikaron.install.harness import InstallError

_JSON_INDENT = 2


@dataclass(frozen=True, slots=True)
class Targets:
    """Where **kiro's** shipped artefacts go for one project directory.

    Kiro-specific, and named so rather than generalised: Claude Code's artefacts live at
    different paths under a different dotdir and are computed by `ClaudeCodeTarget`. A single
    `Targets` covering both would be a union type whose fields are half-null on either harness,
    which is the shape `coding-standards.md` §2 asks us not to build.
    """

    project: Path

    @property
    def agents_dir(self) -> Path:
        return self.project / ".kiro" / "agents"

    @property
    def consolidator_config(self) -> Path:
        return self.agents_dir / f"{CONSOLIDATOR_AGENT_NAME}.json"

    @property
    def skill_file(self) -> Path:
        return self.project / ".kiro" / "skills" / SKILL_NAME / "SKILL.md"

    @property
    def documenter_config(self) -> Path:
        return self.agents_dir / f"{DOCUMENTER_AGENT_NAME}.json"

    @property
    def document_skill_file(self) -> Path:
        return self.project / ".kiro" / "skills" / DOCUMENT_SKILL_NAME / "SKILL.md"


class ShippedFile(NamedTuple):
    """One artefact this install owns outright: its path and the exact bytes that belong there.

    The unit both harnesses' writers agree on — and the *merged* files are not among them on either
    harness, because a merge target belongs to the user and a shipped file does not.
    """

    path: Path
    content: str


@dataclass(frozen=True, slots=True)
class Plan:
    """One install, as parsed from the command line: where, with what, and how forcefully.

    A value rather than a parameter list threaded through every function here. The grouping is not
    an invention to satisfy an argument-count rule: these are exactly what one invocation decided,
    they travel together to every writer below, and bundling them means a new option is added in one
    place instead of in four signatures.

    `orchestrator_model` is Claude Code's, kiro shipping no orchestrator, and only that target reads
    it. It stays on the shared value rather than being pushed into a per-harness bag because the
    alternative — a per-harness options type — would make `main.py` build its arguments differently
    depending on a flag it has not resolved yet.
    """

    project: Path
    commands: Commands
    consolidator_model: str
    documenter_model: str
    orchestrator_model: str
    force: bool
    trust_tools: bool
    #: What is being installed: the memory store, the guards, or both.
    components: Components = Components.MEMORY


@dataclass(slots=True)
class Report:
    """What an install did, for `main.py` to print and for a test to assert on."""

    created: list[Path] = field(default_factory=list)
    replaced: list[Path] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)
    #: The subset of `skipped` left alone because its backup failed, not because it was already
    #: correct. Recorded rather than re-derived: the other two reasons are still readable from the
    #: file, this one is not.
    kept_unbacked: list[Path] = field(default_factory=list)
    merged: list[Path] = field(default_factory=list)
    #: Merge targets that already carried every entry, and so were neither backed up nor written.
    current: list[Path] = field(default_factory=list)
    backed_up: list[Path] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class MergePlan:
    """A merge that has been checked and not yet performed.

    `document` is the finished JSON to write. Holding it as a value is what lets the caller order
    the whole install "check everything, then write everything" — the checks live in the `plan_*`
    functions, which read and refuse, and every write is in `commit_merge`. `unchanged` says the
    document equals the one on disk as parsed, so a file formatted by hand is kept as it is.
    """

    path: Path
    document: dict[str, object]
    notes: tuple[str, ...]
    unchanged: bool


def guard_shipped_targets(files: tuple[ShippedFile, ...], project: Path) -> None:
    """Refuse any shipped path whose existing shape would make writing it fail or lie. Writes
    nothing.

    Two failures this closes, both reachable on an ordinary project and neither previously checked:

    - A **directory** at `SKILL.md` was treated as an ordinary collision and reported as "kept", so
      the install exited 0 while no loadable skill existed at all.
    - A **regular file** where `.kiro/skills` or the skill's own directory belongs made the later
      `mkdir(parents=True)` raise `NotADirectoryError` — *after* the consolidator config had been
      written. A traceback and a half-install, from a path shape rather than a crash.

    Raises:
        InstallError: a final target exists and is not a regular file, or an ancestor that must be a
            directory is not one.
    """
    for shipped in files:
        target = shipped.path
        if _occupied(target) and not target.is_file():
            raise InstallError(
                f"{target} is not a regular file, so it cannot be installed. Move it aside and "
                "re-run."
            )
        for ancestor in _ancestors_within(target, project):
            if _occupied(ancestor) and not ancestor.is_dir():
                raise InstallError(
                    f"{ancestor} is not a directory, so {target.name} cannot be installed under "
                    "it. Move it aside and re-run."
                )


def _occupied(path: Path) -> bool:
    """Whether something is at `path` — a **dangling symlink included**.

    `Path.exists()` alone is false for a dangling symlink, which is how a dangling `SKILL.md` link
    previously passed the preflight, was reported as "kept", and let the install exit 0 with no
    loadable skill anywhere. The pair of checks below then reads "occupied, and not the kind it must
    be", which is true of a link to the wrong kind of thing as well as of a wrong thing.
    """
    return path.exists() or path.is_symlink()


def _ancestors_within(target: Path, project: Path) -> list[Path]:
    """`target`'s parent directories, outermost first, stopping at `project`.

    Bounded at the project, because everything above it belongs to the user's filesystem rather than
    to this install: a check that walked to `/` would refuse on any unusual mount above a perfectly
    ordinary project.
    """
    ancestors: list[Path] = []
    current = target.parent
    while current not in (project, current.parent):
        ancestors.append(current)
        current = current.parent
    return list(reversed(ancestors))


def write_shipped_files(files: tuple[ShippedFile, ...], plan: Plan, report: Report) -> None:
    """Write every shipped artefact, recording each outcome in `report`."""
    for shipped in files:
        _write_shipped(shipped, plan=plan, report=report)


def _write_shipped(shipped: ShippedFile, *, plan: Plan, report: Report) -> None:
    """Create the file, refresh it if what is there is not what we ship, or keep and report it.

    **Staleness is a content comparison**, and that is a fix rather than a simplification. The
    predicate used to ask one narrow question — does this config name a *different install's*
    interpreter — which caught a cloned repository and missed the case it was most likely to meet:
    *same install, older version*. Upgrading Zikaron and re-running the installer left the previous
    version's consolidator prompt in place, reported cheerfully as "already there", unless someone
    thought to pass `--force`. A prompt that no longer matches the tools it describes is exactly the
    confidently-stale artefact this project exists to prevent, and it was being produced by the
    installer's own success path.

    Comparing the bytes subsumes the old question — a different interpreter yields different content
    — and extends it to every shipped file rather than only the JSON one, which is why kiro's skill
    could previously never be refreshed at all (its staleness predicate was the constant `False`).
    It also catches a hand-edited artefact, which is the one behaviour change: such a file is now
    backed up and rewritten rather than silently kept. That is the right trade for a file the
    installer owns, and it is safe because nothing is replaced without `<name>.bak` existing first.

    A symlink at the target is treated as an existing file rather than followed, so neither the
    stale path nor `--force` can be talked into writing through a link into somewhere else entirely.
    """
    path, content = shipped
    exists = path.exists() or path.is_symlink()
    if exists and plan.force and not path.is_symlink() and _read_or_empty(path) != content:
        # **`--force` backs up too.** The content-comparison trade rests on "nothing is replaced
        # without `<name>.bak` existing first", and this path made that false exactly where it
        # matters most: `--force` is the flag the merge-conflict refusals *instruct* people to pass,
        # so it arrives alongside an unrelated conflict rather than only when someone means
        # "discard my edits". Best-effort:
        # a backup that cannot be written must not block an override the user asked for
        # explicitly, so it degrades to a note rather than a refusal.
        try:
            _back_up_once(path, report=report)
        except InstallError as exc:
            report.notes.append(
                f"{path.name} could not be backed up before --force replaced it ({exc})."
            )
    if exists and not plan.force:
        if path.is_symlink() or _read_or_empty(path) == content:
            report.skipped.append(path)
            return
        try:
            _back_up_once(path, report=report)
        except InstallError as exc:
            # A stale artefact is worth correcting, but not at the cost of losing what is there with
            # no copy of it. Keeping a broken consolidator config is recoverable; replacing it
            # unbacked is not, so this reports and leaves it.
            report.skipped.append(path)
            report.kept_unbacked.append(path)
            report.notes.append(
                f"{path.name} differs from what this install ships but could not be backed up "
                f"({exc}), so it was left alone. Move it aside and re-run to get a correct one."
            )
            return
        _replace(path, content)
        report.replaced.append(path)
        report.notes.append(
            f"{path.name} differed from what this install ships and was rewritten — an older "
            f"Zikaron, another install, or a local edit. The original is at {path.name}.bak."
        )
        return
    if path.is_symlink():
        path.unlink()
    _replace(path, content)
    (report.replaced if exists else report.created).append(path)


def _read_or_empty(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _replace(path: Path, content: str) -> None:
    """Write `content` to `path` atomically, creating parents as needed.

    Through a temporary file in the same directory and one rename, because for the agent config this
    is a file the user owns: a crash or a full disk part-way through a plain write leaves them with
    a truncated config the harness then refuses to load, and the `.bak` beside it is a worse remedy
    than never having broken it.

    The scratch file is created **exclusively, under a name nothing can predict**. A fixed
    `<target>.tmp` would be *followed* if it happened to be a symlink — the same hole the check on
    the final target closes one component along, and a destination check that leaves its own scratch
    file
    open to redirection has closed nothing.

    An existing file's permission bits are carried over, because a rename replaces the inode and its
    mode with it: a config that was `0644` must not come back `0600` as a side effect of how it was
    written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.is_file() and not path.is_symlink() else None
    with _exclusive_temporary(path) as scratch:
        _write_all(scratch.descriptor, content.encode("utf-8"))
        if mode is not None:
            os.fchmod(scratch.descriptor, mode)
        scratch.path.replace(path)


def _write_all(descriptor: int, payload: bytes) -> None:
    """Write every byte of `payload` to `descriptor`, then flush it to the device.

    A single `os.write` is **not** enough, and that is the point of this function existing: a write
    to a regular file may legally return short — the documented case being a partial write when the
    space for the rest is not there — and ignoring the return value would let a truncated file be
    renamed over a user's config while the install reported success. That is the exact failure the
    atomic rewrite was introduced to close, reintroduced one layer down.

    `fsync` before the caller publishes, because the rename is atomic against other *processes* and
    says nothing about a crash: without it, a machine that loses power moments later can come back
    with the rename applied and the contents not.

    Raises:
        OSError: any part of the write or the flush failed. Nothing is published, because the caller
            publishes after this returns.
    """
    written = 0
    while written < len(payload):
        just_written = os.write(descriptor, payload[written:])
        if just_written == 0:
            raise OSError(errno.ENOSPC, "wrote no bytes and none were rejected", None)
        written += just_written
    os.fsync(descriptor)


class _Scratch(NamedTuple):
    """An open descriptor and the path it was created at, held together.

    Both, because the writing goes through the **descriptor** while the publication is by path: the
    descriptor is what makes the write immune to the name being swapped underneath it, and the path
    is
    what `replace`/`link` needs.
    """

    descriptor: int
    path: Path


@contextmanager
def _exclusive_temporary(destination: Path) -> Iterator[_Scratch]:
    """A freshly created scratch file beside `destination`, held open, removed on any failure.

    Beside it rather than under `/tmp`, so the final rename or link stays on one filesystem —
    neither is atomic across devices, and `os.replace` raises. Created through `mkstemp`, which
    opens with `O_CREAT | O_EXCL` under an unpredictable name, so no pre-existing name can
    redirect it.

    **The descriptor stays open until the publication.** Closing it and reopening the path by name
    would reintroduce exactly the hole the exclusive creation closes: between the close and the
    reopen, anything able to write in that directory could unlink the name and leave a symlink in
    its place, and the reopen would follow it. Writing through the descriptor means the bytes go
    to the inode this function created, whatever happens to the name.
    """
    descriptor, raw = tempfile.mkstemp(
        dir=destination.parent, prefix=f".{destination.name}.", suffix=".tmp"
    )
    scratch = _Scratch(descriptor=descriptor, path=Path(raw))
    try:
        yield scratch
    finally:
        os.close(descriptor)
        scratch.path.unlink(missing_ok=True)


def commit_merge(merge: MergePlan, report: Report) -> None:
    """Back the config up if nothing is backed up yet, then write the planned document — or, when
    the file already carries it, touch nothing.

    **A file that does not exist yet is not backed up**, and that is not merely an optimisation: a
    backup is a copy of the user's own prior state, and there is none. Kiro never reaches this
    branch — `--agent` must name an existing file and `main.py` refuses otherwise — but Claude
    Code's two merge targets are fixed project paths that a fresh project simply does not have, and
    attempting a copy there would refuse the whole install over the absence of a file we are about
    to create.
    """
    if merge.unchanged:
        report.current.append(merge.path)
        report.notes.extend(merge.notes)
        return
    if merge.path.exists() or merge.path.is_symlink():
        _back_up_once(merge.path, report=report)
    _replace(merge.path, json.dumps(merge.document, indent=_JSON_INDENT) + "\n")
    report.merged.append(merge.path)
    report.notes.extend(merge.notes)


def guard_backup_path(path: Path) -> None:
    """Refuse now if this file could not be backed up later. Creates nothing.

    Split out of `_back_up_once` and called from `plan_merge` because the backup is the **last**
    thing a merge does and the shipped files are written before it: leaving this check where it
    happens would mean a blocked backup path was discovered only after two files had landed, which
    is the half-install the plan/commit split exists to prevent. The same condition is re-tested
    at commit, because a check and a use are two moments and this one is cheap.

    Raises:
        InstallError: something is at `<path>.bak` and it is not a regular file.
    """
    backup = path.with_name(path.name + ".bak")
    if backup.is_file() and not backup.is_symlink():
        return
    if backup.exists() or backup.is_symlink():
        raise InstallError(
            f"{backup} exists and is not a regular file, so {path.name} cannot be backed up. "
            "Move it aside and re-run."
        )


def _back_up_once(path: Path, *, report: Report) -> None:
    """Copy `path` to `<path>.bak`, unless something is already there.

    The check is `is_file() and not is_symlink()`, not `exists()`, and both halves earn their keep.
    `exists()` is **false** for a dangling symlink while `shutil.copy2` happily follows one, which
    would write this config's contents to whatever the link names, outside the project entirely. And
    anything at that path which is *not* a regular file — a directory, a fifo — is not a backup, so
    treating its presence as "already backed up" would let a merge proceed with no recoverable copy.

    Raises:
        InstallError: the copy failed. A merge that cannot be backed up is refused rather than
            performed, because an edit to a file the user owns with no recoverable copy of it is the
            one outcome this whole function exists to prevent.
    """
    backup = path.with_name(path.name + ".bak")
    if backup.is_file() and not backup.is_symlink():
        report.notes.append(f"{backup.name} already existed and was left as it was.")
        return
    guard_backup_path(path)
    try:
        _copy_atomically(path, backup)
    except FileExistsError:
        # Another process published the first backup between the check above and this link. That
        # copy wins, exactly as an already-present one would have.
        report.notes.append(f"{backup.name} appeared while backing up and was left as it was.")
        return
    except OSError as exc:
        raise InstallError(f"could not back {path} up to {backup.name}: {exc}") from exc
    report.backed_up.append(backup)


def _copy_atomically(source: Path, destination: Path) -> None:
    """Copy `source` to `destination` through an exclusively created temporary file.

    Not `shutil.copy2` straight to the destination: that writes the final `.bak` in place, so a copy
    interrupted part-way — a full disk, a killed process — leaves a *partial regular file* that the
    next run would accept as the pristine first backup. A rename either happened or did not.
    """
    with _exclusive_temporary(destination) as scratch:
        _write_all(scratch.descriptor, source.read_bytes())
        shutil.copystat(source, scratch.path)
        # `os.link`, not `replace`: a rename would overwrite a backup another process created
        # between `_guard_backup_path` and here, and "the first backup wins" is the whole rule. A
        # hard link fails with `EEXIST` instead, and the temporary is removed either way.
        os.link(scratch.path, destination)
