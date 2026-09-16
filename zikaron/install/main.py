"""`python -m zikaron.install` — write Zikaron's artefacts into a project, for either harness.

`architecture.md` §"The install contract" is normative for every refusal here; `harness.md`
§"The installer's two targets" for what varies between the two. The order of operations is the
contract's own: **validate before writing anything**, because a half-installed project whose
consolidator names a model the harness will silently substitute is the one outcome that makes two
consolidation runs incomparable while both look healthy.

**This module is written once.** Which files exist and how each is merged lives behind
`HarnessTarget`; flow, preflight order, collision policy and backup discipline are here and are
shared. If a harness name appears below outside `_resolve_harness`, the seam has sprung a leak.

Not a console script. `zikaron-hook` and `zikaron-mcp` are entry points because a config file has to
name them by absolute path; this command is run by a person, once, and `python -m zikaron.install`
already says which interpreter's Zikaron is being installed — which is the single most important
fact about an install and the one an ambient `zikaron-install` on `PATH` would obscure.
"""

import argparse
import os
import sys
from pathlib import Path
from typing import Final

from zikaron.harness.spec import CLAUDE_CODE, Harness
from zikaron.install.entries import Commands, HookFormat
from zikaron.install.harness import InstallError
from zikaron.install.targets import HarnessTarget, target_for
from zikaron.install.writer import (
    Plan,
    Report,
    ShippedFile,
    commit_merge,
    guard_shipped_targets,
    write_shipped_files,
)

#: `--harness auto`, the default. Resolved by evidence, and refused when there is none — see
#: `_resolve_harness`.
_AUTO = "auto"

#: The marker variable Claude Code exports into every process it spawns, **read from the seam**
#: rather than spelled again here — a review caught the literal, and it is intent 1's own defect
#: class.
#:
#: What is deliberately *not* reused is `harness.detect.current_harness`, and the difference is the
#: whole point: that function answers "which harness am I running under", falling back to kiro when
#: the marker is absent because kiro exports none. The installer is asking a **different question**
#: — "which harness is this project set up for" — where that same fallback would silently write
#: kiro artefacts into a Claude Code project from a plain terminal and exit 0. So the *value* comes
#: from the seam and the *policy* does not.
_CLAUDE_MARKER: Final = CLAUDE_CODE.marker_variable


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m zikaron.install",
        description="Install Zikaron's consolidator, consolidation skill, hook and MCP entries.",
    )
    parser.add_argument(
        "--project",
        type=Path,
        default=Path.cwd(),
        help="the project to install into (default: the current directory). At runtime the "
        "store is keyed by the harness's own project directory where it names one, else the "
        "working directory (D17)",
    )
    parser.add_argument(
        "--harness",
        choices=(_AUTO, *(harness.value for harness in Harness)),
        default=_AUTO,
        help="which harness to install for. The default resolves it from the project and the "
        "environment, and refuses rather than guessing when neither says.",
    )
    parser.add_argument(
        "--agent",
        type=Path,
        default=None,
        help="kiro only: an existing agent config to merge the hook and MCP entries into. Backed "
        "up to <config>.bak first.",
    )
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="print the entries instead of merging them, and write no shipped files either. Use "
        "to see exactly what an install would add before letting it.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="the consolidator's model (default: this harness's own, which kiro validates against "
        "its model list and Claude Code refuses at spawn if unknown)",
    )
    parser.add_argument(
        "--format",
        dest="hook_format",
        type=HookFormat,
        choices=tuple(HookFormat),
        default=HookFormat.OBJECT,
        help="kiro only: which hook format to write when the target config has none yet. A config "
        "that already has hooks keeps its own format regardless.",
    )
    parser.add_argument(
        "--no-trust-tools",
        dest="trust_tools",
        action="store_false",
        help="do not pre-approve Zikaron's own tools, so every memory write asks permission. The "
        "default trusts them: per-write prompts push against the write policy the whole store "
        "depends on.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite files this would otherwise refuse to touch",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Install, printing an account of what happened. Returns a process exit status.

    Returns rather than calling `sys.exit`, so a test drives the whole command in-process and reads
    both the status and the output — the `__main__` block below is the only place a status becomes
    an exit.
    """
    args = _parser().parse_args(sys.argv[1:] if argv is None else argv)
    try:
        report = _install(agent=args.agent, options=args)
    except InstallError as exc:
        print(f"install refused: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        # Every *predictable* path-shape problem is refused in the preflight above. This is the
        # remainder — a full disk, a revoked permission, a filesystem that went read-only mid-run —
        # reported as a failed install rather than as a traceback, which tells a user nothing they
        # can act on.
        print(f"install failed: {exc}", file=sys.stderr)
        return 1
    _print_report(report)
    return 0


def _install(*, agent: Path | None, options: argparse.Namespace) -> Report:
    """The whole install, in the contract's order: check everything, then write everything.

    The ordering is load-bearing rather than tidy. `plan_merges` parses the files it would touch and
    runs every refusal against them **before** the shipped files are written, so a malformed config
    or a conflicting entry leaves the project exactly as it was. An earlier arrangement wrote the
    shipped files first and found the problem afterwards, which is the half-install this order
    prevents.

    Raises:
        InstallError: any refusal. Nothing has been written when one is raised.
    """
    project: Path = options.project
    harness_choice, harness_notes = _resolve_harness(options.harness, project)
    target = target_for(harness_choice)
    commands = Commands.from_this_interpreter()
    _refuse_missing_commands(commands)
    _refuse_unusable_agent_flag(agent, target)
    if not project.is_dir():
        raise InstallError(f"{project} is not a directory")
    if agent is not None and not agent.is_file():
        raise InstallError(f"{agent} does not exist — --agent takes a path to an existing config")
    if agent is not None and agent.is_symlink():
        # Refused rather than followed, because publishing an atomic rewrite means replacing the
        # directory entry — which would silently sever a config managed as a link into a dotfile
        # repository, leaving a new local file and the real one untouched and disconnected. This is
        # the opposite case from a symlinked *directory*, which a write through preserves.
        raise InstallError(
            f"{agent} is a symlink. Point --agent at the file it resolves to "
            f"({agent.resolve()}), so this does not replace the link itself."
        )

    plan = Plan(
        project=project,
        commands=commands,
        # `is None`, not `or`: an explicit `--model ""` is a mistake worth reporting, and truthiness
        # would silently substitute this harness's default for it. Found by the test written for the
        # shape check rather than by the shape check itself, which never saw the value.
        model=(target.spec.consolidator_model if options.model is None else options.model),
        hook_format=options.hook_format,
        force=options.force,
        trust_tools=options.trust_tools,
    )
    report = Report()
    report.notes.extend(harness_notes)
    if options.print_only:
        # **A preview refuses nothing it does not have to.** The model check asks a *remote* harness
        # whether an id exists, and the fragment below neither contains the model nor mentions it —
        # so on a machine whose harness cannot be reached, a hard refusal here would block a preview
        # in order to validate something the preview does not show. Downgraded to a note; a real
        # install still refuses.
        try:
            target.refuse_absent_harness()
            target.refuse_unknown_model(plan.model)
        except InstallError as exc:
            # "refused", not "could not be validated": the two reachable causes read very
            # differently to whoever ran this. Kiro's is a genuinely unreachable harness; the shape
            # check is local and deterministic, so the model *was* checked and failed. The
            # exception's own text distinguishes them, so it is quoted rather than paraphrased.
            report.notes.append(
                f"a real install would refuse here ({exc}) — this preview does not, because its "
                "whole job is to show you what would be written."
            )
        shipped = target.shipped_files(plan)
        report.notes.append(target.fragment(plan))
        report.notes.append(
            "An install would also write, in full:\n"
            + "\n".join(f"- {path}" for path, _content in shipped)
        )
        report.notes.extend(target.notes(plan))
        return report

    target.refuse_absent_harness()
    target.refuse_unknown_model(plan.model)
    shipped = target.shipped_files(plan)
    _refuse_agent_aliasing_a_shipped_target(agent, shipped)

    guard_shipped_targets(shipped, project)
    merges = target.plan_merges(plan, agent)

    write_shipped_files(shipped, plan, report)
    for merge in merges:
        commit_merge(merge, report)
    if not merges:
        # Kiro with no `--agent`: the shipped files land and the entries are printed for the user to
        # paste, which is what M12 did and what a user re-running to refresh the consolidator still
        # expects. Expressed as "nothing was merged" rather than as "kiro without --agent" so it
        # stays a fact about this install rather than a harness name leaking into shared flow.
        report.notes.append(target.fragment(plan))
    report.notes.extend(target.notes(plan))
    report.notes.extend(
        target.complaints_about([*report.created, *report.replaced, *report.merged])
    )
    return report


def _resolve_harness(requested: str, project: Path) -> tuple[Harness, list[str]]:
    """Which harness to install for, refusing rather than guessing, plus anything worth saying.

    Explicit wins. `auto` then reads **the project first**, because that is what the install is
    *for*: a `.claude/` or a `.kiro/` directory says which harness this project is already set up
    with, and it says so more specifically than whatever terminal the installer happens to be run
    from. Only when the project says nothing does the environment marker get a vote.

    **Both present, or neither and no marker, is a refusal.** The alternative is the failure this
    corpus has already paid for once, in an agent whose `mcpServers` was configured and whose
    `tools` did not select it: a working-looking install, exit 0, and no memory tools anywhere. A
    wrong-harness install has exactly that shape, and it is worse than an install that did not
    happen.

    **When the two sources *contradict*, the install says so.** Project evidence still wins, but a
    lone `.kiro/` in a project opened from a Claude Code session is a real configuration — this
    corpus's own migration advice is to *keep* `.kiro/` — and installing for kiro there produces the
    working-looking-inert result for the session the user is actually in. Reported rather than
    enforced: the evidence genuinely is ambiguous, and a note costs nothing while a refusal would
    block the common case of installing for kiro from a Claude Code terminal.

    Raises:
        InstallError: `auto` found no evidence, or found both.
    """
    if requested != _AUTO:
        return Harness(requested), []
    has_claude = (project / ".claude").is_dir()
    has_kiro = (project / ".kiro").is_dir()
    marker_set = _CLAUDE_MARKER is not None and bool(os.environ.get(_CLAUDE_MARKER))
    if has_claude and not has_kiro:
        return Harness.CLAUDE_CODE, []
    if has_kiro and not has_claude:
        contradiction = (
            [
                f"{_CLAUDE_MARKER} is set, but {project} has only .kiro/ — installed for "
                f"{Harness.KIRO.value}. Pass --harness {Harness.CLAUDE_CODE.value} if this project "
                "is meant to use the session you are in."
            ]
            if marker_set
            else []
        )
        return Harness.KIRO, contradiction
    if has_claude and has_kiro:
        evidence = "it has both .kiro/ and .claude/"
    elif marker_set:
        return Harness.CLAUDE_CODE, []
    else:
        evidence = f"it has neither .kiro/ nor .claude/, and {_CLAUDE_MARKER} is not set"
    raise InstallError(
        f"could not tell which harness {project} is for — {evidence}. Pass "
        f"--harness {Harness.KIRO.value} or --harness {Harness.CLAUDE_CODE.value}. Guessing here "
        "would install artefacts the harness never reads, which exits 0 and leaves no memory tools "
        "at all."
    )


def _refuse_unusable_agent_flag(agent: Path | None, target: HarnessTarget) -> None:
    """Refuse `--agent` on a harness that has no user-named config to merge into.

    Refused rather than ignored: the flag is the one instruction the user gave about where their
    configuration lives, and silently discarding it would install into two fixed project files
    while they believed they had chosen otherwise.
    """
    if agent is None or target.accepts_agent_flag:
        return
    raise InstallError(
        f"--agent has no meaning under --harness {target.name}: its hook and MCP entries go into "
        "fixed project files (.claude/settings.local.json and .mcp.json), not into an agent config "
        "you name. Drop the flag, or pass --print-only to see exactly what would be written."
    )


def _refuse_agent_aliasing_a_shipped_target(
    agent: Path | None, shipped: tuple[ShippedFile, ...]
) -> None:
    """Refuse an `--agent` that names one of the files this install writes itself.

    `.kiro/agents/zikaron-consolidator.json` is a plausible thing to pick out of an agents
    directory, and picking it used to produce a working-looking install that had broken
    consolidation: the merge turned the consolidator's own config into a *primary* agent —
    `--mode primary`, primary hooks — while keeping its identity and prompt, so the very first
    `zikaron_memory_next_group` the prompt instructs has no tool behind it. Exit 0, and
    consolidation
    silently gone.

    Compared by resolved path rather than by string, because the two can be the same file under
    different spellings, and `--project .` makes that likely rather than exotic.
    """
    if agent is None:
        return
    resolved = agent.resolve()
    for path, _content in shipped:
        if resolved == path.resolve():
            raise InstallError(
                f"--agent names {path.name}, which this install writes itself. Point --agent at "
                "the config for the agent you work in, not at one of Zikaron's own."
            )


def _refuse_missing_commands(commands: Commands) -> None:
    missing = commands.missing()
    if not missing:
        return
    listed = ", ".join(str(path) for path in missing)
    raise InstallError(
        f"the shipped commands are not installed for this interpreter ({listed}). Run "
        "`pip install -e .` (or `pip install zikaron`) into the environment you are installing "
        "from — a hook whose command does not exist fails silently, because the harness does not "
        "surface a hook's stderr."
    )


def _print_report(report: Report) -> None:
    for path in report.created:
        print(f"wrote     {path}")
    for path in report.replaced:
        print(f"replaced  {path}")
    for path in report.merged:
        print(f"merged    {path}")
    for path in report.backed_up:
        print(f"backed up {path}")
    for path in report.skipped:
        print(f"kept      {path} (already there — pass --force to replace it)")
    for note in report.notes:
        print(f"\n{note}")
