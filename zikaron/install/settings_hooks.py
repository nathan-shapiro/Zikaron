"""How a Claude Code install merges its hook groups into `.claude/settings.local.json`.

`design/harness.md` §"The installer's two targets" and `design/guards.md` §5 are normative. Every
group on a trigger this install writes is one of three kinds, and each is treated by itself:

- **a user's own** — none of its commands runs a Zikaron script — stays where it is and is never
  compared;
- **the other selection's** — a Zikaron group running only scripts this install does not write on
  that trigger, as the guards' re-read nudge is beside a memory install's search reminder — is
  copied verbatim too, whatever its path, as a trigger this install does not write is: an install
  touches only its own selection;
- **this selection's** — one running a script this install writes there — is this install's when
  every command in it runs a program this install writes there, at this install's path, whatever
  their number and their `if`s. It is replaced, and reported when it differed. One carrying a
  command of the user's own, or a Zikaron program at another install's path, is refused, and
  replaced under `--force`.

**Ownership is the program, not the whole group** — the predicate `MCP_OWNERSHIP_FIELDS` states for
`.mcp.json`, and for the same reason: a changed timeout, an added field or a changed set of `if`
filters is an upgrade, and comparing groups whole would make every existing install refuse its own
the first time one moved.
"""

import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from zikaron.hook.components import Components
from zikaron.install.entries import CLAUDE_START_TRIGGERS, Commands, claude_hooks_value
from zikaron.install.harness import InstallError
from zikaron.install.ownership import ANOTHER_INSTALL
from zikaron.install.writer import Plan


@dataclass(frozen=True, slots=True)
class MergedHooks:
    """The settings file's `hooks` value after this install, and what is to be said about it."""

    hooks: dict[str, list[object]]
    notes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Slot:
    """What this install writes on one trigger: the Zikaron scripts, by file name, and the
    programs, by path."""

    scripts: frozenset[str]
    programs: frozenset[str]
    commands: Commands

    @classmethod
    def of(cls, groups: list[dict[str, object]], commands: Commands) -> Self:
        programs = frozenset(
            program for group in groups for program in _programs_in(group, commands)
        )
        return cls(frozenset(Path(program).name for program in programs), programs, commands)

    def holds(self, group: object) -> bool:
        """Whether `group` is this selection's: a command in it runs a script written here."""
        return any(
            _zikaron_script(command, self.commands) in self.scripts
            for command in _commands_in(group)
        )

    def owns(self, group: object) -> bool:
        """Whether `group` is this install's: every command in it runs a program written here."""
        programs = _programs_in(group, self.commands)
        return bool(programs) and set(programs) <= self.programs


def merge(by_trigger: dict[str, list[object]], *, plan: Plan, path: Path) -> MergedHooks:
    """This selection's hook groups merged into `by_trigger`, the file's groups per trigger.

    Raises:
        InstallError: a group of this selection's is not this install's, and `--force` was not
            passed.
    """
    ours = claude_hooks_value(
        plan.commands, plan.components, start=start_selection(by_trigger, plan)
    )
    slots = {trigger: _Slot.of(groups, plan.commands) for trigger, groups in ours.items()}
    _refuse_foreign(by_trigger, ours, slots, plan=plan, path=path)
    hooks = {
        **{key: value for key, value in by_trigger.items() if key not in ours},
        **{
            trigger: _spliced(by_trigger.get(trigger, []), groups, slots[trigger])
            for trigger, groups in ours.items()
        },
    }
    return MergedHooks(hooks=hooks, notes=tuple(_notes(by_trigger, ours, slots, plan=plan)))


def _spliced(existing: list[object], ours: list[dict[str, object]], slot: _Slot) -> list[object]:
    """`existing` with this selection's groups replaced by `ours`, where the first of them stood,
    or after the rest when none did — so installing one selection over both leaves the trigger's
    order, and so the file, as it was."""
    spliced: list[object] = []
    placed = False
    for group in existing:
        if not slot.holds(group):
            spliced.append(group)
        elif not placed:
            spliced.extend(ours)
            placed = True
    return spliced if placed else [*spliced, *ours]


def start_selection(by_trigger: dict[str, list[object]], plan: Plan) -> Components:
    """What the start entries carry after this install: the union of the selection being
    installed and every selection a Zikaron start entry already names.

    So guards over a memory install write `--components both`, and a memory install over guards or
    both keeps `both` — neither install ever drops the other's start text.
    """
    selection = plan.components
    for trigger in CLAUDE_START_TRIGGERS:
        for group in by_trigger.get(trigger, []):
            for command in _commands_in(group):
                if _zikaron_script(command, plan.commands) == plan.commands.hook.name:
                    selection = selection.union(Components.from_arguments(_words(command)[1:]))
    return selection


def _commands_in(group: object) -> list[str]:
    """Every `command` string inside one settings hook group, defensively.

    Shared by the ownership tests and the diagnostics so the two cannot disagree about what an
    entry *is* — and typed against `object` throughout because one side of every comparison is a
    document the user wrote.

    **An entry with no `command` string is invisible to ownership and to the notes**, so a group
    carrying one beside ours compares as ours, is rewritten, and that entry goes with only the
    rewrite's note to show for it.
    """
    if not isinstance(group, dict):
        return []
    entries = group.get("hooks")
    if not isinstance(entries, list):
        return []
    return [
        str(entry["command"])
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("command"), str)
    ]


def _words(command: str) -> list[str]:
    """A hook command split as the shell splits it — the field is a shell command line
    (`research/claude-code-hook-command-shell-probe.md`) — or whole, where it does not split."""
    try:
        return shlex.split(command)
    except ValueError:
        return [command]


def _program(command: str, commands: Commands) -> str:
    """What a hook command's ownership is decided by: a Zikaron command's program path, its first
    shell word — the arguments are the selection, not the owner — and any other command whole.

    A command naming an unquoted path with a space in it, as an install wrote before commands were
    shell-quoted, does not split to a Zikaron program and is taken whole, so it still matches the
    quoted path that replaces it.
    """
    words = _words(command)
    first = words[0] if words else ""
    return first if Path(first).name in (commands.hook.name, commands.guard.name) else command


def _zikaron_script(command: str, commands: Commands) -> str | None:
    """Which Zikaron script a hook command runs — `zikaron-hook` or `zikaron-guard` — or `None`.

    By the script's **file name**, not its full path, and that is deliberate: a command naming
    `/somewhere-else/venv/bin/zikaron-hook` belongs to a *different* Zikaron install, and
    recognising it is what lets this install refuse it, or replace it under `--force`, rather than
    leave two hooks firing into the same store from two interpreters.
    """
    name = Path(_program(command, commands)).name
    return name if name in (commands.hook.name, commands.guard.name) else None


def _programs_in(group: object, commands: Commands) -> list[str]:
    return [_program(command, commands) for command in _commands_in(group)]


def _refuse_foreign(
    by_trigger: dict[str, list[object]],
    ours: dict[str, list[dict[str, object]]],
    slots: dict[str, _Slot],
    *,
    plan: Plan,
    path: Path,
) -> None:
    """Refuse when a group of this selection's is not this install's.

    A group whose program differs means another install owns it, whose absolute path may point at
    a venv that no longer has Zikaron in it; replacing it silently would hide that the user has two
    installs, so the refusal names the trigger and the command that is there. A group carrying our
    command beside one of the user's is refused too, and that is the right answer rather than an
    oversight: this installer replaces a group wholesale and does not merge *inside* one, so
    rewriting would drop their entry silently and refusing is the only way not to. The refusal
    prints both command lists so they can see which entry is theirs.

    Raises:
        InstallError: such a group is there and `--force` was not passed.
    """
    if plan.force:
        return
    differing = sorted(
        f"{trigger}: {_describe_group_difference(group, ours[trigger])}"
        for trigger, slot in slots.items()
        for group in by_trigger.get(trigger, [])
        if slot.holds(group) and not slot.owns(group)
    )
    if not differing:
        return
    raise InstallError(
        f"{path} already carries Zikaron hook entries that differ from what this install would "
        f"write ({'; '.join(differing)}). {ANOTHER_INSTALL}"
    )


def _without_arguments(group: object, commands: Commands) -> object:
    """A group with each Zikaron command reduced to its program, for telling an edit that matters
    from a change of selection or of quoting."""
    if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
        return group  # pragma: no cover — only recognised groups reach here, and they are both
    entries = [
        {**entry, "command": _program(entry["command"], commands)}
        if isinstance(entry, dict) and isinstance(entry.get("command"), str)
        else entry
        for entry in group["hooks"]
    ]
    return {**group, "hooks": entries}


def _notes(
    by_trigger: dict[str, list[object]],
    ours: dict[str, list[dict[str, object]]],
    slots: dict[str, _Slot],
    *,
    plan: Plan,
) -> list[str]:
    """What replacing a group of this selection's cost, on whichever path got there.

    **Without `--force`: a group of ours that was replaced by a different one.** Its programs
    matched, so this install owns the group — but the rest of it did not, and the two readings of
    that are indistinguishable from the file: a new `HOOK_TIMEOUT_SECONDS` upgrading itself, or a
    user's hand-edited `timeout` being reverted. Refusing would block the first to protect the
    second. Reporting serves the second without blocking the first, the same trade
    `ownership.merged_server` makes for a server entry.

    **Ownership is re-checked here rather than assumed from the refusal**, which `--force` skips
    entirely — without it, taking over another install's hook would advise re-applying a hand-edit
    that never existed.

    **`--force` adds a second note rather than replacing this one.** It overrides the refusal, so a
    group carrying our command beside a hook of the user's own is replaced wholesale and their hook
    goes with it. That is reported; a *takeover* is not. Another install's hook at a path of its
    own leaves the user nothing to re-apply or recover, and replacing it is what `--force` is for.
    **What gets said is what they did not ask for.** Both notes can fire on one run, for different
    groups, so neither returns early.
    """
    replaced = [
        (trigger, group)
        for trigger, slot in slots.items()
        for group in by_trigger.get(trigger, [])
        if slot.holds(group) and group not in ours[trigger]
    ]
    notes: list[str] = []
    if plan.force:
        losses = sorted(
            (trigger, theirs)
            for trigger, group in replaced
            if (theirs := _user_commands_in(group, plan.commands))
        )
        if losses:
            where = "; and ".join(
                f"on {trigger}, dropping {', '.join(theirs)}" for trigger, theirs in losses
            )
            noun = "group" if len(losses) == 1 else "groups"
            one = sum(len(theirs) for _, theirs in losses) == 1
            notes.append(
                f"--force replaced Zikaron's hook {noun} {where}. "
                f"{'That command was' if one else 'Those commands were'} inside the {noun} it "
                f"replaced and {'is' if one else 'are'} no longer there. Check the .bak beside the "
                f"file for {'it' if one else 'them'}."
            )
    rewritten = sorted(
        {
            trigger
            for trigger, group in replaced
            if slots[trigger].owns(group)
            and _without_arguments(group, plan.commands)
            not in [_without_arguments(one, plan.commands) for one in ours[trigger]]
        }
    )
    if rewritten:
        notes.append(
            f"Zikaron's own hook on {', '.join(rewritten)} differed from what this install writes "
            "and was replaced — if you had hand-edited a timeout or matcher there, re-apply it."
        )
    return notes


def _user_commands_in(group: object, commands: Commands) -> list[str]:
    """Commands inside a group of this selection's that are **the user's**.

    A command running a Zikaron script belongs to some Zikaron install — this one or another —
    and `--force` replacing it is the flag doing its job. Anything else is a hook the user put
    there, which `--force` discards as a side effect of replacing the group around it. Only the
    second is worth a note, and partitioning them here keeps that judgement in one place.
    """
    return [
        command for command in _commands_in(group) if _zikaron_script(command, commands) is None
    ]


def _describe_group_difference(group: object, expected: list[dict[str, object]]) -> str:
    """Which command the other install wrote, not merely that a group differs.

    Naming only the location would leave a user unable to tell another install from their own
    edit, and therefore unable to decide whether `--force` is the right answer.

    Only the command is described, because only a differing command reaches here — anything else is
    an upgrade this install performs and reports through `_notes`.
    """
    commanded = _commands_in(group)
    wanted = [command for one in expected for command in _commands_in(one)]
    return f"command is {commanded or 'absent'}, this install writes {wanted}"
