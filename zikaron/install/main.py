"""`python -m zikaron.install` — write Zikaron's kiro artefacts into a project.

`architecture.md` §"The install contract" is normative for every refusal here. The order of
operations is the contract's own: **validate before writing anything**, because a half-installed
project whose consolidator names a model the harness will silently substitute is the one outcome
that
makes two consolidation runs incomparable while both look healthy.

Not a console script. `zikaron-hook` and `zikaron-mcp` are entry points because a config file has to
name them by absolute path; this command is run by a person, once, and `python -m zikaron.install`
already says which interpreter's Zikaron is being installed — which is the single most important
fact
about an install and the one an ambient `zikaron-install` on `PATH` would obscure.
"""

import argparse
import json
import sys
from pathlib import Path

from zikaron.install import harness
from zikaron.install.assets import SKILL_MARKDOWN
from zikaron.install.entries import (
    TOOL_SELECTOR,
    Commands,
    HookFormat,
    hooks_value,
    mcp_servers_value,
)
from zikaron.install.harness import InstallError
from zikaron.install.writer import (
    ARRAY_FORMAT_OUTPUT_CAP_NOTE,
    Plan,
    Report,
    Targets,
    commit_merge,
    guard_shipped_targets,
    plan_merge,
    shipped_targets,
    write_shipped_files,
)

#: `architecture.md`'s distribution table. Overridable on the command line so the model comparison
#: `consolidation.md` §"Consolidator identity and model" asks for costs no code change — and stated
#: here rather than defaulted inside the config builder, so `--model` and the shipped default are
#: the
#: same one value read from one place.
DEFAULT_MODEL = "claude-sonnet-5"

_JSON_INDENT = 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m zikaron.install",
        description="Install Zikaron's kiro agent config, consolidation skill and hook entries.",
    )
    parser.add_argument(
        "--project",
        type=Path,
        default=Path.cwd(),
        help="the project to install into (default: the current directory, which is also the "
        "directory Zikaron scopes its store to)",
    )
    parser.add_argument(
        "--agent",
        type=Path,
        default=None,
        help="an existing agent config to merge the hook and MCP entries into. Backed up to "
        "<config>.bak first. Omit to have the entries printed for you to paste.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"the consolidator's model, validated against this harness (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--format",
        dest="hook_format",
        type=HookFormat,
        choices=tuple(HookFormat),
        default=HookFormat.OBJECT,
        help="which hook format to write when the target config has none yet. A config that "
        "already has hooks keeps its own format regardless.",
    )
    parser.add_argument(
        "--no-trust-tools",
        dest="trust_tools",
        action="store_false",
        help="leave `@zikaron` out of the target agent's `allowedTools`, so every memory write "
        "asks permission. The default adds it: per-write prompts push against the write policy "
        "the whole store depends on.",
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
    an
    exit.
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

    The ordering is load-bearing rather than tidy. `plan_merge` parses the user's own config and
    runs
    every refusal against it **before** the shipped files are written, so a malformed config or a
    conflicting entry leaves the project exactly as it was. An earlier arrangement wrote the shipped
    files first and found the problem afterwards, which is the half-install this order prevents.

    Raises:
        InstallError: any refusal. Nothing has been written when one is raised.
    """
    project: Path = options.project
    commands = Commands.from_this_interpreter()
    _refuse_missing_commands(commands)
    _refuse_unknown_model(options.model)
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
        targets=Targets(project=project),
        commands=commands,
        model=options.model,
        hook_format=options.hook_format,
        force=options.force,
        trust_tools=options.trust_tools,
    )
    _refuse_agent_aliasing_a_shipped_target(agent, plan)
    guard_shipped_targets(plan)
    merge = plan_merge(agent, plan) if agent is not None else None

    report = Report()
    write_shipped_files(plan, SKILL_MARKDOWN, report)
    if merge is None:
        report.notes.append(_fragment_note(commands, options.hook_format))
    else:
        commit_merge(merge, report)
    _validate_written_configs(report, agent)
    return report


def _refuse_agent_aliasing_a_shipped_target(agent: Path | None, plan: Plan) -> None:
    """Refuse an `--agent` that names one of the files this install writes itself.

    `.kiro/agents/zikaron-consolidator.json` is a plausible thing to pick out of an agents
    directory,
    and picking it used to produce a working-looking install that had broken consolidation: the
    merge
    turned the consolidator's own config into a *primary* agent — `--mode primary`, primary hooks —
    while keeping its identity and prompt, so the very first `zikaron_next_group` the prompt
    instructs
    has no tool behind it. Exit 0, and consolidation silently gone.

    Compared by resolved path rather than by string, because the two can be the same file under
    different spellings, and `--project .` makes that likely rather than exotic.
    """
    if agent is None:
        return
    resolved = agent.resolve()
    for target in shipped_targets(plan.targets):
        if resolved == target.resolve():
            raise InstallError(
                f"--agent names {target.name}, which this install writes itself. Point --agent at "
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


def _refuse_unknown_model(model: str) -> None:
    """`architecture.md`'s no-silent-fallback rule, enforced where a config is about to be written.

    The check is *membership*, not a regex or a prefix: the harness answers with an exact set, and
    accepting anything outside it would install a config whose model the harness silently replaces
    with its own default — leaving two consolidation runs incomparable while both look healthy.
    """
    available = harness.available_model_ids()
    if model in available:
        return
    raise InstallError(
        f"{model!r} is not a model this harness offers. `kiro-cli agent validate` would accept it "
        "silently and the harness would fall back to its default, so it is refused here instead. "
        f"Available: {', '.join(sorted(available))}"
    )


def _fragment_note(commands: Commands, hook_format: HookFormat) -> str:
    """The entries to paste, when no `--agent` was given."""
    fragment = json.dumps(
        {
            "hooks": hooks_value(commands, hook_format),
            "mcpServers": mcp_servers_value(commands, mode="primary"),
        },
        indent=_JSON_INDENT,
    )
    caveats = [
        f"`{TOOL_SELECTOR}` must be in that agent's `tools`, or the memory tools are simply absent "
        "— `mcpServers` configures the server and `tools` selects from it. Put it in "
        "`allowedTools` as well, or every memory write will interrupt you for approval.",
        "The agent also needs `subagent` among its `tools` for the zikaron-consolidate skill to "
        "spawn the consolidator.",
    ]
    if hook_format is HookFormat.ARRAY:
        caveats.append(ARRAY_FORMAT_OUTPUT_CAP_NOTE)
    return (
        "Add these to the agent config you actually use (or re-run with --agent <path> to have "
        "them merged in, with a backup):\n\n"
        + fragment
        + "\n\n"
        + "\n".join(f"- {caveat}" for caveat in caveats)
    )


def _validate_written_configs(report: Report, agent: Path | None) -> None:
    """Report `kiro-cli agent validate`'s own complaint about anything we wrote, if it has one.

    After writing rather than before, because it validates a *file*: this is the check on our own
    JSON, and it is a report rather than a refusal — the install has already happened by here, and
    telling the user what the harness dislikes is more useful than an exception that leaves them
    guessing which of the two files it meant.
    """
    candidates = [*report.created, *report.merged] if agent is None else [*report.created, agent]
    for path in candidates:
        if path.suffix != ".json":
            continue
        complaint = harness.validate_agent_config(path)
        if complaint is not None:
            report.notes.append(f"{path}: `kiro-cli agent validate` says: {complaint}")


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
