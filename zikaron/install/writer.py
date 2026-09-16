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
  file the user owns that differs from what this install would write is a *refusal*, because that
  means another install owns it.
- **A merge is backed up first, and the first backup wins.** `<config>.bak` is written only when
  nothing is there — not even a dangling symlink — because overwriting it on every run would replace
  the pristine original with the copy the first install had already modified.
"""

import errno
import json
import os
import shlex
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Final, NamedTuple

from zikaron.install.assets import SKILL_NAME
from zikaron.install.entries import (
    CONSOLIDATOR_AGENT_NAME,
    MCP_SERVER_NAME,
    TOOL_SELECTOR,
    Commands,
    HookFormat,
    hooks_array,
    hooks_object,
    mcp_servers_value,
)
from zikaron.install.harness import InstallError

_JSON_INDENT = 2

#: How a skill is named in `resources`. Skills are progressively loaded, unlike `file://` entries.
_SKILL_SCHEME: Final = "skill://"

#: Said in two places — after a merge and beside a printed fragment — because it is the one way an
#: array-format install differs from an object-format one in what it can promise.
ARRAY_FORMAT_OUTPUT_CAP_NOTE: Final = (
    "The array hook format documents no `max_output_size` field, so those entries inherit the "
    "harness default of 10240 bytes rather than the 65536 an object-format entry states."
)


@dataclass(frozen=True, slots=True)
class Targets:
    """Where **kiro's** shipped artefacts go for one project directory.

    Kiro-specific, and named so rather than generalised: Claude Code's four artefacts live at
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


class ShippedFile(NamedTuple):
    """One artefact this install owns outright: its path and the exact bytes that belong there.

    The unit both harnesses' writers agree on. Kiro ships two, Claude Code ships two — and the
    *merged* files are not among them on either harness, because a merge target belongs to the user
    and a shipped file does not.
    """

    path: Path
    content: str


@dataclass(frozen=True, slots=True)
class Plan:
    """One install, as parsed from the command line: where, with what, and how forcefully.

    A value rather than six parameters threaded through every function here. The grouping is not an
    invention to satisfy an argument-count rule: these are exactly what one invocation decided, they
    travel together to every writer below, and bundling them means a new option is added in one
    place instead of in four signatures.

    `hook_format` is kiro's and is ignored by the Claude Code target, which has one hook shape. It
    stays on the shared value rather than being pushed into a kiro-only bag because the alternative
    — a per-harness options type — would make `main.py` build its arguments differently depending on
    a flag it has not resolved yet.
    """

    project: Path
    commands: Commands
    model: str
    hook_format: HookFormat
    force: bool
    trust_tools: bool


@dataclass(slots=True)
class Report:
    """What an install did, for `main.py` to print and for a test to assert on."""

    created: list[Path] = field(default_factory=list)
    replaced: list[Path] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)
    merged: list[Path] = field(default_factory=list)
    backed_up: list[Path] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class MergePlan:
    """A merge that has been checked and not yet performed.

    `document` is the finished JSON to write. Holding it as a value is what lets the caller order
    the
    whole install "check everything, then write everything" — the checks live in the `plan_*`
    functions, which read and refuse, and every write is in `commit_merge`.
    """

    path: Path
    document: dict[str, object]
    notes: tuple[str, ...]


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
        # **`--force` backs up too**, which it did not until a review caught it. The
        # content-comparison trade rests on "nothing is replaced without `<name>.bak` existing
        # first", and this path made that false exactly where it matters most: `--force` is the
        # flag the merge-conflict refusals *instruct* people to pass, so it arrives alongside an
        # unrelated conflict rather than only when someone means "discard my edits". Best-effort:
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
    a
    truncated config the harness then refuses to load, and the `.bak` beside it is a worse remedy
    than never having broken it.

    The scratch file is created **exclusively, under a name nothing can predict**. A fixed
    `<target>.tmp` would be *followed* if it happened to be a symlink — the same hole the check on
    the
    final target closes one component along, and a destination check that leaves its own scratch
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
    to
    a regular file may legally return short — the documented case being a partial write when the
    space
    for the rest is not there — and ignoring the return value would let a truncated file be renamed
    over a user's config while the install reported success. That is the exact failure the atomic
    rewrite was introduced to close, reintroduced one layer down.

    `fsync` before the caller publishes, because the rename is atomic against other *processes* and
    says nothing about a crash: without it, a machine that loses power moments later can come back
    with
    the rename applied and the contents not.

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
    neither
    is atomic across devices, and `os.replace` raises. Created through `mkstemp`, which opens with
    `O_CREAT | O_EXCL` under an unpredictable name, so no pre-existing name can redirect it.

    **The descriptor stays open until the publication.** Closing it and reopening the path by name
    would reintroduce exactly the hole the exclusive creation closes: between the close and the
    reopen, anything able to write in that directory could unlink the name and leave a symlink in
    its
    place, and the reopen would follow it. Writing through the descriptor means the bytes go to the
    inode this function created, whatever happens to the name.
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


def plan_kiro_merge(path: Path, plan: Plan, targets: Targets) -> MergePlan:
    """Check a user's agent config and build the document a merge would write. Writes nothing.

    The file's own format decides how hooks are written — object stays object, array stays array —
    because the harness rewrites a config in whichever format it read, and a file carrying both
    shapes
    has no defined meaning. `plan.hook_format` applies only when the file has no `hooks` key at all.

    Raises:
        InstallError: the file is missing, not a JSON object, carries `hooks`/`mcpServers` in a
        shape
            this cannot merge into, or already carries a Zikaron entry that differs from what this
            install would write. The last is the one worth refusing loudly: it means a previous
            install from a *different* interpreter, whose paths may point at a venv that no longer
            has
            Zikaron in it. Replacing is almost always right, and doing it silently would hide that
            the
            user has two installs.
    """
    document = _load_agent_config(path)
    hook_format = _detect_format(document, path=path, requested=plan.hook_format)
    _guard_mergeable_shapes(document, path=path)
    _guard_existing_entries(document, plan.commands, path=path, force=plan.force)
    guard_backup_path(path)

    merged = dict(document)
    merged["hooks"] = _merged_hooks(document, plan.commands, hook_format)
    merged["mcpServers"] = _merged_servers(document, plan.commands)
    merged["tools"] = _selecting(document, "tools")
    if plan.trust_tools:
        merged["allowedTools"] = _selecting(document, "allowedTools")
    settings, crew_notes = _merged_tools_settings(document)
    if settings is not None:
        merged["toolsSettings"] = settings
    resources, resource_notes = _merged_resources(document, targets)
    if resources is not None:
        merged["resources"] = resources

    notes = [ARRAY_FORMAT_OUTPUT_CAP_NOTE] if hook_format is HookFormat.ARRAY else []
    notes.extend(crew_notes)
    notes.extend(resource_notes)
    if TOOL_SELECTOR not in _string_list(document.get("tools")):
        notes.append(
            f"Added `{TOOL_SELECTOR}` to {path.name}'s `tools` — without it the memory tools are "
            "simply absent, since `mcpServers` configures the server and `tools` selects from it."
        )
    if not plan.trust_tools and TOOL_SELECTOR not in _string_list(document.get("allowedTools")):
        notes.append(
            f"`{TOOL_SELECTOR}` is **not** in {path.name}'s `allowedTools` (--no-trust-tools), so "
            "every memory write will ask your permission. Remove that flag, or add it by hand, to "
            "let the agent record without interrupting you."
        )
    if "subagent" not in _string_list(document.get("tools")):
        notes.append(
            f"{path.name} does not list the `subagent` tool. The zikaron-consolidate skill spawns "
            "the consolidator through it, so add it to `tools` to be able to consolidate. Granting "
            "a built-in tool is your decision, so this install does not do it for you."
        )
    return MergePlan(path=path, document=merged, notes=tuple(notes))


def commit_merge(merge: MergePlan, report: Report) -> None:
    """Back the config up if nothing is backed up yet, then write the planned document.

    **A file that does not exist yet is not backed up**, and that is not merely an optimisation: a
    backup is a copy of the user's own prior state, and there is none. Kiro never reaches this
    branch — `--agent` must name an existing file and `main.py` refuses otherwise — but Claude
    Code's two merge targets are fixed project paths that a fresh project simply does not have, and
    attempting a copy there would refuse the whole install over the absence of a file we are about
    to create.
    """
    if merge.path.exists() or merge.path.is_symlink():
        _back_up_once(merge.path, report=report)
    _replace(merge.path, json.dumps(merge.document, indent=_JSON_INDENT) + "\n")
    report.merged.append(merge.path)
    report.notes.extend(merge.notes)


def _load_agent_config(path: Path) -> dict[str, object]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InstallError(f"could not read {path}: {exc}") from exc
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InstallError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise InstallError(f"{path} is not a JSON object")
    return document


def _detect_format(document: dict[str, object], *, path: Path, requested: HookFormat) -> HookFormat:
    """Which format this file's hooks are in, refusing a shape that is neither.

    A present-but-unmergeable `hooks` value is refused rather than replaced: it is data the user put
    there, this code cannot tell what they meant by it, and silently dropping it to install our own
    two entries would destroy something to make room for something.
    """
    hooks = document.get("hooks")
    if isinstance(hooks, dict):
        return HookFormat.OBJECT
    if isinstance(hooks, list):
        return HookFormat.ARRAY
    if "hooks" in document:
        raise InstallError(
            f"{path} has a `hooks` value that is neither an object nor an array "
            f"({type(hooks).__name__}). Fix or remove it before installing; this refuses rather "
            "than replace it."
        )
    return requested


def _guard_mergeable_shapes(document: dict[str, object], *, path: Path) -> None:
    """Refuse any `hooks`/`tools` shape the merge below would silently drop.

    The merge is written defensively — it filters a hook-map value that is not a list, and treats a
    non-list `tools` as absent — and defensive filtering on a *write* path is data loss with a
    reassuring shape. A trigger whose value is an object, or a `tools` value that is a string, is
    something the user put there; this cannot know what they meant by it, and installing over it
    would
    destroy something to make room for something.
    """
    hooks = document.get("hooks")
    if isinstance(hooks, dict):
        for trigger, value in hooks.items():
            if not isinstance(value, list):
                raise InstallError(
                    f"{path} has `hooks.{trigger}` as {type(value).__name__} rather than an array. "
                    "Fix or remove it before installing; this refuses rather than drop it."
                )
    for key in ("tools", "allowedTools"):
        value = document.get(key)
        if key in document and not isinstance(value, list):
            raise InstallError(
                f"{path} has a `{key}` value that is not an array ({type(value).__name__}). Fix or "
                "remove it before installing; this refuses rather than replace it."
            )
    if "resources" in document and not isinstance(document.get("resources"), list):
        raise InstallError(
            f"{path} has a `resources` value that is not an array "
            f"({type(document.get('resources')).__name__}). Fix or remove it before installing."
        )
    _guard_crew_shape(document, path=path)


def _guard_crew_shape(document: dict[str, object], *, path: Path) -> None:
    """Refuse a `toolsSettings.crew` this cannot merge into rather than replacing it.

    Same rule as every other shape guard here, one level deeper: the crew block gates which agents
    may
    be spawned, so quietly rebuilding a malformed one could hand the user a config that spawns more
    —
    or less — than they had written down.
    """
    settings = document.get("toolsSettings")
    if "toolsSettings" in document and not isinstance(settings, dict):
        raise InstallError(
            f"{path} has a `toolsSettings` value that is not an object "
            f"({type(settings).__name__}). Fix or remove it before installing."
        )
    if not isinstance(settings, dict):
        return
    present = [key for key in _CREW_KEYS if key in settings]
    if len(present) > 1:
        raise InstallError(
            f"{path} has both `toolsSettings.crew` and `toolsSettings.agent_crew`. The harness "
            "documents them as aliases for one block and gives no meaning to carrying both, so "
            "this refuses rather than guess which one it reads. Keep one and re-run."
        )
    for crew_key in present:
        crew = settings[crew_key]
        if not isinstance(crew, dict):
            raise InstallError(
                f"{path} has a `toolsSettings.{crew_key}` value that is not an object "
                f"({type(crew).__name__}). Fix or remove it before installing."
            )
        for list_key in ("availableAgents", "trustedAgents"):
            if list_key in crew and not isinstance(crew[list_key], list):
                raise InstallError(
                    f"{path} has `toolsSettings.{crew_key}.{list_key}` as "
                    f"{type(crew[list_key]).__name__} rather than an array. Fix or remove it "
                    "before installing."
                )


def _guard_existing_entries(
    document: dict[str, object], commands: Commands, *, path: Path, force: bool
) -> None:
    """Refuse a config already wired to a *different* Zikaron install, unless forced.

    Both halves are checked, and the hook half was the gap: an earlier version guarded only the
    `mcpServers` entry, so a config carrying a stale hook command and no server entry had that
    command
    silently replaced. The two are installed together and must be refused together.
    """
    servers = document.get("mcpServers")
    if "mcpServers" in document and not isinstance(servers, dict):
        raise InstallError(
            f"{path} has an `mcpServers` value that is not an object "
            f"({type(servers).__name__}). Fix or remove it before installing."
        )
    if force:
        return
    has_server = isinstance(servers, dict) and MCP_SERVER_NAME in servers
    existing_server = servers.get(MCP_SERVER_NAME) if isinstance(servers, dict) else None
    expected_server = mcp_servers_value(commands, mode="primary")[MCP_SERVER_NAME]
    if has_server and existing_server != expected_server:
        raise InstallError(
            f"{path} already has an `mcpServers.{MCP_SERVER_NAME}` entry pointing somewhere else "
            f"({existing_server!r}). That is a previous install from a different interpreter. "
            "Re-run with --force to replace it."
        )
    differing = _differing_zikaron_hooks(document, commands)
    if differing:
        raise InstallError(
            f"{path} already has Zikaron hook entries that differ from what this install would "
            f"write ({'; '.join(differing)}). That is either a previous install from a different "
            "interpreter or an entry you edited. Re-run with --force to adopt this install's "
            "entries."
        )


def _differing_zikaron_hooks(document: dict[str, object], commands: Commands) -> list[str]:
    """Every existing Zikaron hook entry that is not **exactly** what this install would write.

    The contract's word is *differs*, and equality of one field is not equality of an entry: an
    entry
    carrying the current command with `timeout_ms: 1`, or the reserved name with a changed
    `trigger`,
    is something a person chose, and the merge below would replace it. So the comparison is
    structural, against the generated entry for that entry's own trigger.

    Recognition uses **both** identities the merge uses — an object-format entry by its command's
    file
    name, an array-format entry by its reserved `name` — because guarding one while replacing on
    either is how an entry comes to be rewritten silently.

    Returned as descriptions rather than a boolean so the refusal can say *what* differs. That is
    the
    only way a user can tell their own edit from a Zikaron version change, and therefore whether
    `--force` is the right answer.
    """
    hooks = document.get("hooks")
    if isinstance(hooks, dict):
        expected_by_trigger = {
            trigger: entries[0] for trigger, entries in hooks_object(commands).items()
        }
        described = [
            _describe_difference(entry, expected_by_trigger.get(trigger), where=trigger)
            for trigger, entries in hooks.items()
            if isinstance(entries, list)
            for entry in entries
            if _is_our_command(entry, commands)
        ]
        return [description for description in described if description is not None]
    if not isinstance(hooks, list):
        return []
    expected_by_name = {entry["name"]: entry for entry in hooks_array(commands)}
    descriptions: list[str] = []
    for entry in hooks:
        name = entry.get("name") if isinstance(entry, dict) else None
        named = isinstance(name, str) and name in expected_by_name
        if not (named or _is_our_command(entry, commands)):
            continue
        expected = expected_by_name.get(name) if isinstance(name, str) else None
        description = _describe_difference(entry, expected, where=str(name or "an unnamed entry"))
        if description is not None:
            descriptions.append(description)
    return descriptions


def _describe_difference(entry: object, expected: object, *, where: str) -> str | None:
    """`None` if `entry` is exactly `expected`, else a short account of how the two differ."""
    if entry == expected:
        return None
    if expected is None:
        return f"{where}: not an entry this install writes"
    if not isinstance(entry, dict) or not isinstance(expected, dict):
        return f"{where}: {entry!r}"
    differing = [
        key for key in sorted(set(entry) | set(expected)) if entry.get(key) != expected.get(key)
    ]
    return f"{where}: {', '.join(differing)}"


def _entry_command(entry: object) -> str | None:
    """The executable an entry runs, in either format's spelling, **unquoted**.

    Unquoted because the stored string is shell source: what we write is `shlex.quote`'d, so the raw
    value of a Zikaron entry is `'/path/to/zikaron-hook'` and a caller comparing `Path(...).name`
    against `zikaron-hook` would be comparing against `zikaron-hook'`. A single-token command is
    reported as that token; anything else — a pipeline, several words, unbalanced quotes — is
    reported
    verbatim, since it is not a bare executable path and no caller should treat it as one.
    """
    if not isinstance(entry, dict):
        return None
    direct = entry.get("command")
    if not isinstance(direct, str):
        action = entry.get("action")
        nested = action.get("command") if isinstance(action, dict) else None
        direct = nested if isinstance(nested, str) else None
    if direct is None:
        return None
    try:
        words = shlex.split(direct)
    except ValueError:
        # Unbalanced quotes: not something to reinterpret, and the caller compares it as-is.
        return direct
    return words[0] if len(words) == 1 else direct


def guard_backup_path(path: Path) -> None:
    """Refuse now if this file could not be backed up later. Creates nothing.

    Split out of `_back_up_once` and called from `plan_merge` because the backup is the **last**
    thing
    a merge does and the shipped files are written before it: leaving this check where it happens
    would mean a blocked backup path was discovered only after two files had landed, which is the
    half-install the plan/commit split exists to prevent. The same condition is re-tested at commit,
    because a check and a use are two moments and this one is cheap.

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


def _merged_hooks(
    document: dict[str, object], commands: Commands, hook_format: HookFormat
) -> object:
    """This install's hook entries, folded into whatever the config already had.

    Replacement is keyed on identity rather than appended blindly: an object-format entry is
    identified by its `command`'s file name, an array-format entry by its `name`. Appending instead
    would give a twice-installed project two hooks per trigger, and therefore two injected blocks
    per
    user message.
    """
    if hook_format is HookFormat.OBJECT:
        return _merged_hooks_object(document, commands)
    return _merged_hooks_array(document, commands)


def _merged_hooks_object(
    document: dict[str, object], commands: Commands
) -> dict[str, list[object]]:
    existing = document.get("hooks")
    merged: dict[str, list[object]] = (
        {key: list(value) for key, value in existing.items() if isinstance(value, list)}
        if isinstance(existing, dict)
        else {}
    )
    for trigger, entries in hooks_object(commands).items():
        kept = [entry for entry in merged.get(trigger, []) if not _is_our_command(entry, commands)]
        merged[trigger] = [*kept, *entries]
    return merged


def _merged_hooks_array(document: dict[str, object], commands: Commands) -> list[object]:
    ours = hooks_array(commands)
    our_names = {entry["name"] for entry in ours}
    existing = document.get("hooks")
    kept = [
        entry
        for entry in (existing if isinstance(existing, list) else [])
        if not (isinstance(entry, dict) and entry.get("name") in our_names)
        and not _is_our_command(entry, commands)
    ]
    return [*kept, *ours]


def _merged_servers(document: dict[str, object], commands: Commands) -> dict[str, object]:
    servers = document.get("mcpServers")
    merged: dict[str, object] = dict(servers) if isinstance(servers, dict) else {}
    merged.update(mcp_servers_value(commands, mode="primary"))
    return merged


def _merged_resources(
    document: dict[str, object], targets: Targets
) -> tuple[list[object] | None, list[str]]:
    """The agent's `resources` with the skill declared, when declaring it is what makes it load.

    Skills reach an agent through `resources`, and by default they *also* arrive without one: the
    harness appends inherited resources (workspace skills among them) to whatever a config declares,
    and only the `chat.disableInheritingDefaultResources` setting turns that off.

    **The entry is written whenever nothing already covers the skill, including when `resources` is
    absent.** An earlier version only left a note in that case, reasoning that inheritance covers
    it — which leaves a *deterministically broken* install for the one documented configuration
    where it does not, and a warning is not a delivered skill. Declaring resources does not disable
    inheritance (the harness appends to what a config declares), so the entry is purely additive and
    cannot narrow anything; the only cost is a redundant declaration in the common case, against a
    skill that silently fails to load in the uncommon one.

    A `skill://.kiro/skills/**/SKILL.md` glob already covers it, so a config carrying one gains
    nothing.

    Coverage is tested with `fnmatch`, whose `*` spans separators and so treats the `**` glob above
    as matching. Both directions of error are benign: over-matching leaves the entry off a config
    that inherits it anyway, and under-matching adds one that is redundant.
    """
    declared = document.get("resources")
    listed: list[object] = list(declared) if isinstance(declared, list) else []
    target = str(targets.skill_file.relative_to(targets.project))
    covered = any(
        isinstance(entry, str)
        and entry.startswith(_SKILL_SCHEME)
        and fnmatch(target, entry.removeprefix(_SKILL_SCHEME))
        for entry in listed
    )
    if covered:
        return None, []
    return [*listed, _skill_resource(targets)], [
        f"Added `{_skill_resource(targets)}` to `resources`, so the consolidation skill is "
        "reachable whether or not inherited resources are switched on."
    ]


def _skill_resource(targets: Targets) -> str:
    """The `skill://` URI for the shipped skill, relative to the project."""
    return _SKILL_SCHEME + str(targets.skill_file.relative_to(targets.project))


#: `toolsSettings.crew` gates which agents the `subagent` tool may spawn. `agent_crew` is a
#: documented
#: alias for the same block, so a config using it must be *updated in place* rather than given a
#: second
#: block whose relationship to the first is undefined.
_CREW_KEYS: Final = ("crew", "agent_crew")


def _merged_tools_settings(
    document: dict[str, object],
) -> tuple[dict[str, object] | None, list[str]]:
    """The agent's `toolsSettings` with the consolidator added to its crew, and what to report.

    **Without this the consolidation skill cannot run at all**, which is how the omission was found
    —
    in real use, not in review. The skill spawns `zikaron-consolidator` through the `subagent` tool,
    and `toolsSettings.crew.availableAgents` gates which agents that tool may spawn: a config
    listing
    three of its own agents and not ours answers "Agents not available for crew stages".

    **The two lists are not symmetric, and treating them alike would break working configs.**
    `availableAgents` is a *restriction*: the harness documents that an absent or empty list means
    every agent is available. So adding our name to an empty one would *narrow* the config from "any
    agent" to "only the consolidator" and silently break every other subagent the user has. It is
    therefore extended only when it already lists something. `trustedAgents` is a *grant* — empty
    grants nothing — so adding to it can only widen, and it is created if absent.

    Returns `(None, notes)` when there is nothing to change, so an install does not add an empty
    `toolsSettings` block to a config that had none.
    """
    settings = document.get("toolsSettings")
    if settings is None:
        settings = {}
    if not isinstance(settings, dict):
        return None, []
    crew_key = next((key for key in _CREW_KEYS if key in settings), "crew")
    crew = settings.get(crew_key)
    crew_dict: dict[str, object] = dict(crew) if isinstance(crew, dict) else {}

    notes: list[str] = []
    changed = False

    available = crew_dict.get("availableAgents")
    if isinstance(available, list) and available:
        if CONSOLIDATOR_AGENT_NAME not in _string_list(available):
            crew_dict["availableAgents"] = [*available, CONSOLIDATOR_AGENT_NAME]
            changed = True
            notes.append(
                f"Added `{CONSOLIDATOR_AGENT_NAME}` to "
                f"`toolsSettings.{crew_key}.availableAgents` — the consolidation skill spawns it "
                "through the `subagent` tool, and that list gates which agents may be spawned."
            )
    else:
        notes.append(
            f"`toolsSettings.{crew_key}.availableAgents` is unset, which the harness reads as "
            "*every* agent being available, so it was left alone rather than narrowed to one entry."
        )

    if CONSOLIDATOR_AGENT_NAME not in _string_list(crew_dict.get("trustedAgents")):
        notes.append(
            f"Starting a consolidation will ask your permission once, because "
            f"`{CONSOLIDATOR_AGENT_NAME}` is not in `toolsSettings.{crew_key}.trustedAgents`. Add "
            "it there if you would rather it did not — that grants a subagent spawn, which is a "
            "wider thing than the memory tools and so is left to you."
        )

    if not changed:
        return None, notes
    merged_settings = dict(settings)
    merged_settings[crew_key] = crew_dict
    return merged_settings, notes


def _selecting(document: dict[str, object], key: str) -> list[object]:
    """The agent's `tools` or `allowedTools`, with `@zikaron` added if it is not already there.

    **`tools` is not optional, and that was measured rather than assumed.** An agent carrying the
    `mcpServers` entry and a `tools` list that did not name the server reported its own tools as
    `code, dummy, execute_bash, fs_read, fs_write, glob, grep, todo_list, use_subagent` — every
    memory
    tool absent, no warning anywhere. `mcpServers` configures a server; `tools` selects from it.

    **`allowedTools` is added too, by default, and the reason is the write policy rather than
    convenience.** Without it, every `remember`, `amend` and `retire` interrupts the user for
    approval,
    and the design's whole write posture is "err toward recording" — the prior art's own measured
    failure was an agent that recorded too *little*. Per-write friction pushes directly against the
    one
    behaviour the store depends on, and it trains a user to click through prompts, which is worse
    than
    not asking at all.

    What is being trusted is narrow, and worth stating precisely rather than generously: tools that
    read and write rows in SQLite files under the project, with no network and no effect outside
    it. A mistaken write is **recoverable, not undoable** — `retire` withdraws a row from
    ordinary retrieval and leaves it auditable, while an `amend` overwrites prose that nothing
    restores. That is a weaker guarantee than "reversible", which is the word this used first and
    which overstated it. `--no-trust-tools` leaves the entry out for anyone who wants the prompts,
    and the install reports which it did either way.
    """
    existing = document.get(key)
    listed: list[object] = list(existing) if isinstance(existing, list) else []
    if TOOL_SELECTOR in _string_list(existing):
        return listed
    return [*listed, TOOL_SELECTOR]


def _is_our_command(entry: object, commands: Commands) -> bool:
    """Whether an existing entry is a Zikaron hook, in either format's spelling.

    Matches on the command's **file name**, not the whole path, so a previous install from another
    venv is replaced rather than left beside this one — two `zikaron-hook` entries on one trigger
    would inject two blocks per message, and the stale one would point at an interpreter that may no
    longer have Zikaron installed.
    """
    command = _entry_command(entry)
    return command is not None and Path(command).name == commands.hook.name


def _string_list(value: object) -> frozenset[str]:
    if not isinstance(value, list):
        return frozenset()
    return frozenset(item for item in value if isinstance(item, str))
