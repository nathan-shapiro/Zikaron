"""`zikaron knowledge` — the knowledge-base verbs, for a person at a shell.

**Every verb is an RPC call.** Flow, argument parsing and printing live here; every decision lives
in the service, behind the same methods the agent-facing tools call, so the two surfaces cannot
diverge on what a verb means. This command opens no store **of its own** — the one open it makes is
`ServiceConnection`'s read-only identity read, and `client.py` says on what terms. `zikaron doctor`
is the one command exempted from the thin-client rule — it may open the store directly — because it
reports on an installation that may be broken in the way that stops the service starting.

**Nothing here waits for a build unless asked to.** `add` and `refresh` start one and return,
because a build is minutes of work over a whole directory tree and holding a shell for it would
make the two verbs that create a corpus the two slowest things this command does.
`refresh --wait` is the exception, for a step that must not end with an indexer still running — its
own builds and any it found already under way alike. Even then the build still detaches, so a
command killed mid-wait leaves it running exactly as an agent ending its session after an MCP
refresh does.
"""

import argparse
import asyncio
import shlex
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

from zikaron.core.errors import ErrorCode, ZikaronError
from zikaron.knowledge.client import (
    KnowledgeClient,
    ServiceRefusalError,
    connected,
    relative_to_shell,
)
from zikaron.project.report import execute, render, stderr
from zikaron.project.resolve import CONSOLE_INITIALIZE, MODULE_INITIALIZE, refusal, resolve

_UNSET = "—"

_MODULE_INVOCATION: Final = "python -m zikaron.knowledge"

#: How long `--wait` gives a build to show itself before calling it never started. Bounds only the
#: spawn window — see `_await_builds` on why what follows it is not bounded here.
_APPEARANCE_DEADLINE_SECONDS: Final = 30.0

_POLL_SECONDS: Final = 1.0

#: What each build `outcome` other than `started` means to somebody at a shell, and whether it
#: fails the command. `already_indexing` is neither a refusal nor a failure: the corpus is being
#: built, which is what was asked for, so a loop of refreshes against a running build must not read
#: as a loop of failures. An unreadable database is a *failure* — the driver's own error, which
#: nothing the caller sends differently fixes — where the rest are refusals this system understood.
_OUTCOMES: Final[Mapping[str, tuple[str, bool]]] = {
    "already_indexing": ("building", False),
    "unreadable": ("failed", True),
    "no_database": ("refused", True),
    "root_missing": ("refused", True),
}


def _parser(prog: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Manage this project's knowledge bases: named, indexed corpora of text files.",
    )
    parser.add_argument(
        "--project",
        type=Path,
        default=None,
        help="the project whose store to act on. The default is the harness's own project "
        "directory where it names one, else the current directory.",
    )
    verbs = parser.add_subparsers(dest="verb", required=True)

    verbs.add_parser("list", help="every knowledge base, and whether each one is usable")

    adding = verbs.add_parser("add", help="register a corpus and create its database")
    adding.add_argument("name", help="what to call it. Free-form; lower-cased when stored")
    adding.add_argument(
        "--path",
        type=Path,
        required=True,
        help="the directory to index. A relative path is taken from this shell's working "
        "directory, as any other command's would be — the agent-facing tool takes one from the "
        "project root instead, since it has no shell to be relative to.",
    )
    adding.add_argument(
        "--description",
        required=True,
        help="what this corpus holds. Required: it is what lets a later caller choose between "
        "corpora without searching every one of them.",
    )
    adding.add_argument(
        "--include",
        action="append",
        default=[],
        metavar="GLOB",
        help="repeatable. Matched against the path relative to --path, where '*' crosses '/' — so "
        "'*.md' reaches every markdown file and 'docs/*' means the whole tree under docs.",
    )
    adding.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="GLOB",
        help="repeatable, and applied before --include. Same matching as --include.",
    )
    adding.add_argument(
        "--git-mode",
        choices=("tracked", "all", "off"),
        default="tracked",
        help="how much git is consulted. Degrades to 'off' outside a work tree, and says so.",
    )
    adding.add_argument(
        "--max-file-bytes",
        type=int,
        default=None,
        help="this corpus's own size cap (default: from configuration). Over-cap files are "
        "skipped and counted, never truncated.",
    )

    removing = verbs.add_parser("remove", help="destroy a knowledge base and its database")
    removing.add_argument("name")
    removing.add_argument(
        "--yes",
        action="store_true",
        help="actually do it. Without this the call reports what would be destroyed and stops.",
    )

    renaming = verbs.add_parser("rename", help="change a knowledge base's name")
    renaming.add_argument("name")
    renaming.add_argument("new_name", metavar="new-name")

    reporting_parser = verbs.add_parser("status", help="the detail behind a knowledge base's state")
    reporting_parser.add_argument("name", nargs="?", default=None)

    refreshing = verbs.add_parser("refresh", help="build a knowledge base's index")
    refreshing.add_argument(
        "name",
        nargs="?",
        default=None,
        help="which knowledge base to build. Omit it to reach every one, each checked on its own.",
    )
    refreshing.add_argument(
        "--full",
        action="store_true",
        help="reindex every file rather than only what changed. For when the thing that moved is "
        "not the files: a changed chunk budget, or content the index was handed through a filter "
        "that has changed since.",
    )
    refreshing.add_argument(
        "--wait",
        action="store_true",
        help="do not return while an indexer is running against a named corpus — the builds this "
        "call starts, and any it finds already under way — and exit on what they leave behind. "
        "For a script or a CI step that must not end with a build still going.",
    )
    refreshing.add_argument(
        "--force-unlock",
        action="store_true",
        help="clear a build lock nothing will clear on its own — one recorded by another machine, "
        "which this one cannot probe. Refuses while a process on this host still answers to the "
        "recorded pid.",
    )

    return parser


def main(argv: Sequence[str] | None = None, *, prog: str = _MODULE_INVOCATION) -> int:
    """Run one verb, printing an account of what happened. Returns a process exit status.

    Returns rather than calling `sys.exit`, so a test drives the whole command in-process and
    reads both the status and the output. `__main__` is the only place a status becomes an exit.
    """
    args = _parser(prog).parse_args(sys.argv[1:] if argv is None else argv)
    args.invocation = prog
    try:
        args.project_scope = resolve(args.project)
    except ZikaronError as error:
        render(error)
        return 1
    if not args.project_scope.has_store:
        # Before the connection rather than after a failure from it, because the service creates a
        # store wherever it is pointed: reaching it at all is what makes the second store.
        stderr(refusal(args.project_scope, initialize=_initialize_command(prog)))
        return 1
    return execute(lambda: _run(args))


def _initialize_command(prog: str) -> str:
    """How this reader reaches `init`, given how they reached this command.

    A console script is on `PATH` only when one was installed; `uv tool install` provides it and a
    source tree run through `python -m` does not. Naming the wrong one is a command that fails for
    somebody already stuck.
    """
    return MODULE_INITIALIZE if prog.startswith("python -m") else CONSOLE_INITIALIZE


async def _run(args: argparse.Namespace) -> int:
    async with connected(args.project_scope.directory) as client:
        return await _dispatch(args, client)


async def _dispatch(args: argparse.Namespace, client: KnowledgeClient) -> int:
    if args.verb == "list":
        _print_listing(
            await client.call("knowledge_list", {}), detailed=False, project=client.project
        )
        return 0
    if args.verb == "status":
        payload = await client.call("knowledge_status", {"knowledge_base": args.name})
        _print_listing(payload, detailed=True, project=client.project)
        return 0
    if args.verb == "add":
        return await _add(args, client)
    if args.verb == "rename":
        payload = await client.call(
            "knowledge_rename", {"name": args.name, "new_name": args.new_name}
        )
        (renamed,) = _entries(payload)
        print(f"renamed to {renamed['name']!r}")
        return 0
    if args.verb == "remove":
        return await _remove(args, client)
    if args.verb == "refresh":
        return await _refresh(args, client)
    # Unreachable through the command, which refuses an unknown verb before dispatch. Loud rather
    # than a trailing `return`, because the branch a fall-through would land in is the destructive
    # one — a verb added to the parser and forgotten here must fail, not remove a knowledge base.
    raise NotImplementedError(f"no handler for the verb {args.verb!r}")


def _entries(payload: Mapping[str, object]) -> list[dict[str, object]]:
    """A response's `knowledge_bases`, checked rather than assumed.

    A service answering a shape this build does not expect is a defect in one of the two, and a
    `TypeError` naming it is a better report than a `KeyError` three frames later.
    """
    bases = payload.get("knowledge_bases")
    if not isinstance(bases, list):
        raise TypeError(f"response carries no knowledge_bases list: {payload!r}")
    entries: list[dict[str, object]] = []
    for entry in bases:
        if not isinstance(entry, dict):
            raise TypeError(f"knowledge_bases holds {type(entry).__name__}, not objects")
        entries.append(entry)
    return entries


def _text(value: object) -> str:
    return _UNSET if value is None else str(value)


async def _add(args: argparse.Namespace, client: KnowledgeClient) -> int:
    root = relative_to_shell(args.path)
    payload = await client.call(
        "knowledge_add",
        {
            "name": args.name,
            "path": root,
            "description": args.description,
            "include": list(args.include),
            "exclude": list(args.exclude),
            "git_mode": args.git_mode,
            "max_file_bytes": args.max_file_bytes,
        },
    )
    (entry,) = _entries(payload)
    print(f"added     {entry['name']!r}")
    print(f"database  {_text(payload.get('database_path'))}")
    # The state a corpus is created in, before its first build has committed anything. It is the
    # honest answer rather than a placeholder: the database exists and its settings are sound, and
    # nothing has been indexed into it yet.
    print(f"state     {_text(entry.get('state'))}")
    requested = payload.get("requested_git_mode")
    effective = payload.get("effective_git_mode")
    if requested != effective:
        # `root`, not what was typed: the probe ran against the path this command sent, and a
        # relative one names a different directory to whoever reads it back.
        print(
            f"\ngit-mode {requested!r} will not take effect: {root} is not inside a git "
            f"work tree, so this corpus is built as {effective!r}."
        )
    started = _report_build(entry, prog=args.invocation)
    if started:
        _explain_detachment()
    return 0


async def _refresh(args: argparse.Namespace, client: KnowledgeClient) -> int:
    """Clear a lock if asked to, then start a build for every corpus nothing stops.

    Returns non-zero when any named corpus could not be built, so a shell sees a refusal as a
    failure — but, without `--wait`, never for `already_indexing`, which is the idempotent case.

    **Under `--wait`, `already_indexing` is waited for rather than passed over.** What the option
    promises is a call that does not return while an indexer is running against a named corpus, and
    a build somebody else started is one of those. Returning 0 there would end a CI step with that
    indexer alive — and the documented provisioning sequence reaches it, since `add` starts a build
    and has no `--wait` of its own, so a `refresh --wait` arriving after that build took its lock
    sees exactly this outcome.
    """
    if args.force_unlock:
        if args.name is None:
            stderr("refused: --force-unlock clears one knowledge base's lock, so name one")
            return 1
        _report_unlock(await client.call("knowledge_unlock", {"knowledge_base": args.name}))

    before = await _scan_marks(client, name=args.name) if args.wait else {}

    params: dict[str, object] = {"full": args.full}
    if args.name is not None:
        params["name"] = args.name
    payload = await client.call("knowledge_refresh", params)

    entries = _entries(payload)
    if not entries:
        print(f"no knowledge bases in {client.project}")
    building: list[str] = []
    running: list[str] = []
    failed = False
    for entry in entries:
        name = str(entry.get("name"))
        if _report_build(entry, prog=args.invocation, waiting=args.wait, full=args.full):
            building.append(name)
        elif str(entry.get("outcome")) == "already_indexing" and args.wait:
            running.append(name)
        elif _OUTCOMES.get(str(entry.get("outcome")), ("refused", True))[1]:
            failed = True
    if not args.wait:
        if building:
            _explain_detachment()
        return 1 if failed else 0
    if not building and not running:
        return 1 if failed else 0
    failed_waits = await _await_builds(
        client, building, running=running, before=before, only=args.name
    )
    if failed_waits & set(building):
        # The one moment the foreground command is most wanted: a build **this call started** has
        # ended badly and its own output went nowhere. Intersected rather than merely non-empty,
        # because the note points at a line `_report_build` prints for `started` alone — a corpus
        # that was already being built has none, and pointing at it would send a reader looking.
        _explain_detachment()
    return 1 if failed_waits or failed else 0


async def _scan_marks(client: KnowledgeClient, *, name: str | None) -> dict[str, str | None]:
    """Each corpus's `last_scan_started_at` before a build is asked for.

    The baseline half of the wait's predicate. A corpus with no database has none, and `None` is
    the honest value: any timestamp at all is an advance on it.

    Narrowed to `name` when one was given, because `reporting.status` opens every registered
    corpus's database per call: a sweep needs all of them and a named refresh needs one, and the
    difference is the whole registry opened once a second for the minutes a build takes.
    """
    payload = await client.call("knowledge_status", {"knowledge_base": name})
    marks: dict[str, str | None] = {}
    for entry in _entries(payload):
        mark = entry.get("last_scan_started_at")
        marks[str(entry.get("name"))] = None if mark is None else str(mark)
    return marks


def _still_building(entry: Mapping[str, object], *, mark: str | None) -> bool:
    """Whether this corpus's build is still to finish, given where its last scan started.

    **Not "is the state `indexing`".** `state.PRECEDENCE` puts `reindex_required` ahead of
    `indexing`, so a corpus rebuilt after an encoder mismatch reports the former for the whole
    build and a wait keyed on `indexing` would return before it began.

    The build is over when its lock is gone — absent, or recorded against a process this host can
    see is dead. That alone is not enough: a lock is taken shortly *after* the spawn, so a fast
    first poll sees none and would call a build that never began finished. `last_scan_started_at`
    closes that window, since the indexer writes it as it starts.
    """
    if entry.get("last_scan_started_at") == mark:
        return True
    return _lock_says_running(_lock_of(entry))


def _lock_of(entry: Mapping[str, object]) -> Mapping[str, object] | None:
    """This corpus's recorded build lock, or `None` where `status` reports none."""
    held = entry.get("lock")
    return held if isinstance(held, dict) else None


def _lock_says_running(held: Mapping[str, object] | None) -> bool:
    """Whether a recorded lock is evidence of a build still going.

    **A lock outlives the process that took it.** Nothing releases one on a kill — the rows survive
    deliberately, so the next build can take them over — so a holder this host has probed and found
    gone (`live: false`) is a build that ended, not one running. One helper because both predicates
    need exactly this reading, and two copies of it is how one of them comes to hang on a dead
    holder while the other does not.
    """
    return held is not None and held.get("live") is not False


async def _await_builds(
    client: KnowledgeClient,
    names: Sequence[str],
    *,
    running: Sequence[str],
    before: Mapping[str, str | None],
    only: str | None = None,
) -> set[str]:
    """Block until every named build is over. Returns every corpus the wait failed on.

    Three kinds reach that set and all three fail the command: a build that ran and left the corpus
    unusable, one that never started, and one held by a lock this host cannot probe.

    `names` are the builds this call started; `running` are those a call found already under way.
    **The two need different predicates.** A started build is over when its lock is gone *and* its
    scan mark has advanced past the baseline — the mark is what closes the window between the spawn
    and the lock. A build already running took its lock before this call read that baseline, so its
    mark will never advance past it and the same test would say *not begun* forever; its lock alone
    — present and not provably dead — is the evidence, and the lock is already there.

    **Unbounded once a build is demonstrably running, bounded while one is only expected.** A
    build is minutes of work over a whole tree and inventing a deadline for it would be inventing a
    number to tune; the step or shell that asked to wait already has its own. What is bounded is
    the window before a build shows itself at all, because a spawn that died before taking its
    lock leaves nothing that will ever change.

    **Appearance is tracked per corpus**, against one deadline for the whole call. A sweep starts
    one build each, and a single appearance flag would let a corpus whose build *did* start
    suppress the only escape for one whose spawn died — leaving the call waiting forever on a build
    that will never exist, which is the hang this option removes from a CI step.

    **A corpus that never appeared is given up on; the rest are still waited for.** Returning at
    that moment would end the call with the builds that *did* start still running — the one thing
    `--wait` promises not to do — and would skip the report on any that had already finished. So a
    dead spawn is recorded, reported, and dropped from what is watched; the call fails at the end
    **because** of it rather than instead of the rest of its work.

    `only` narrows each poll to one corpus, for the same reason `_scan_marks` takes a name: a status
    call opens every registered corpus's database, and a named refresh watches one.
    """
    shown: dict[str, str] = {}
    lock_only = set(running)
    watched = [*names, *running]
    appeared: set[str] = set(running)
    dead: set[str] = set()
    deadline = time.monotonic() + _APPEARANCE_DEADLINE_SECONDS
    while True:
        payload = await client.call("knowledge_status", {"knowledge_base": only})
        reports = {str(entry.get("name")): entry for entry in _entries(payload)}
        pending = []
        for name in watched:
            entry = reports.get(name)
            if name in dead or entry is None:
                continue
            held = _lock_of(entry)
            if name in lock_only:
                if held is not None and held.get("live") is None:
                    # A holder this host cannot probe. Nothing here can see it released — the
                    # same judgement `lock.probe` declines to make — so waiting on it is waiting
                    # forever, and the exit is the one an operator already has.
                    stderr(
                        f"failed    {name}: its build lock is held by a process this machine "
                        f"cannot probe — another host, or an unreadable pid — so this wait can "
                        f"never see it released; clear it with "
                        f"`refresh {shlex.quote(name)} --force-unlock`"
                    )
                    dead.add(name)
                    continue
                if _lock_says_running(held):
                    pending.append(name)
                    _show_progress(name, entry, shown)
                continue
            if entry.get("last_scan_started_at") != before.get(name):
                appeared.add(name)
            if _still_building(entry, mark=before.get(name)):
                pending.append(name)
                _show_progress(name, entry, shown)
        if not pending:
            surviving = [name for name in watched if name not in dead]
            return _report_terminal_states(reports, surviving) | dead
        absent = [name for name in pending if name not in appeared]
        if absent and time.monotonic() > deadline:
            for name in absent:
                stderr(f"failed    {name}: no build started within {_APPEARANCE_DEADLINE_SECONDS}s")
                dead.add(name)
            continue
        await asyncio.sleep(_POLL_SECONDS)


def _progress_line(entry: Mapping[str, object]) -> str:
    """How far a running build has got, in the two shapes the numbers actually come in.

    `files_remaining` is a number only once the walk has finished — `reporting.files_remaining`
    withholds one until then, because "the walk is still running" and "the walk finished and
    nothing changed" are otherwise the same empty table. So a line claiming `0 remaining` during a
    walk would be inventing the one number nobody can yet have.
    """
    indexed = entry.get("files_indexed")
    remaining = entry.get("files_remaining")
    if remaining is None:
        return f"{indexed} files indexed; still finding what changed"
    return f"{indexed} files indexed, {remaining} to go"


def _show_progress(name: str, entry: Mapping[str, object], shown: dict[str, str]) -> None:
    """Report one corpus's progress, but only when it has actually moved.

    **Printed on change rather than on a clock, and with no carriage-return redrawing.** A wait is
    minutes long and polls every second, so a line per poll is hundreds of identical lines in a CI
    log; a redrawn line is worse, since it needs a terminal and this is written for the case where
    there is not one. On change, both readers get what they need: a person sees it move, and a log
    keeps one line per real advance.

    Standard error, so a caller may still pipe this command's output somewhere.
    """
    line = _progress_line(entry)
    if shown.get(name) == line:
        return
    shown[name] = line
    stderr(f"building  {name}: {line}")


def _report_terminal_states(
    reports: Mapping[str, Mapping[str, object]], names: Sequence[str]
) -> set[str]:
    """Say how each waited-for corpus ended, and return the ones that ended unusable.

    The names rather than a count, because the caller's next decision is about *which*: the note
    pointing at a foreground command is worth printing only for a corpus this call started one for.
    """
    unusable: set[str] = set()
    for name in names:
        state = str(reports[name].get("state")) if name in reports else "gone"
        if state == "ok":
            print(f"built     {name!r} is {state}")
            continue
        unusable.add(name)
        stderr(f"failed    {name}: the build left it {state}")
    return unusable


def _report_unlock(payload: Mapping[str, object]) -> None:
    """Say what was cleared, rendering the holder here rather than reading a sentence off the wire.

    The three recorded fields travel; the wording is this command's, which is why the service does
    not carry one — see `knowledge-index.md` §8.4.
    """
    cleared = payload.get("cleared")
    if cleared is None:
        print("unlocked  no lock was recorded; nothing to clear")
        return
    if not isinstance(cleared, dict):
        raise TypeError(f"cleared is {type(cleared).__name__}, not an object or null")
    pid = cleared.get("pid")
    who = "an unreadable pid" if pid is None else f"pid {pid}"
    host = cleared.get("host") or "an unnamed host"
    started_at = cleared.get("started_at") or "unknown"
    print(f"unlocked  cleared the lock held by {who} on {host}, since {started_at}")


def _report_build(
    entry: Mapping[str, object], *, prog: str, waiting: bool = False, full: bool = False
) -> bool:
    """Say what happened to one corpus, and whether **this call** started a build against it.

    The return value answers that narrower question rather than *is a build running*, because a
    corpus already being built has one running and none started here; `_refresh` reads the outcome
    itself to decide what a wait should cover.

    A started build prints the command that reproduces it in the foreground, because a detached
    build's output is discarded and running the identical command is the only way to recover why
    one failed. That command is the argv the service's own spawn reported, carried on the wire
    rather than rebuilt here, so the two cannot differ.
    """
    name = str(entry.get("name"))
    outcome = str(entry.get("outcome"))
    if outcome == "started":
        print(f"building  {name!r} in the background")
        # Quoted, because a name is free-form and two-word ones are ordinary — an unquoted one
        # pasted back is a command that fails to parse.
        # `prog` rather than a literal: under `uv tool install` no interpreter is on `PATH`, so a
        # hard-coded `python -m` line is a command that fails with `No module named zikaron`.
        print(f"follow    {prog} status {shlex.quote(name)}")
        command = entry.get("foreground_command")
        if isinstance(command, list):
            print(f"foreground {shlex.join(str(part) for part in command)}")
        return True
    prefix, _fails = _OUTCOMES.get(outcome, ("refused", True))
    if prefix == "building":
        # Under `--wait` the wait's own lines say what happens next, and one of them may be a
        # refusal to wait at all — a lock this machine cannot probe. Saying *waiting for it* here
        # would be promising one poll ahead of finding out.
        queued = "this call queued nothing" if waiting else "nothing was queued"
        # Nothing on the wire says whether the build already running is a full one — a lock
        # records pid, host and start — so this says what *this call* did, which is the half that
        # would otherwise go unsaid.
        missed = " — the --full rebuild asked for here did not start" if full else ""
        print(f"building  {name!r} is already being built; {queued}{missed}")
        return False
    stderr(f"{prefix:<9} {name}: {entry.get('reason') or outcome}")
    return False


def _explain_detachment() -> None:
    """The one note every started build shares, printed after them rather than once per build."""
    print("\nA detached build's output is discarded. To watch one, or to see why one failed, run")
    print("the foreground command printed beside it.")


async def _remove(args: argparse.Namespace, client: KnowledgeClient) -> int:
    """Destroy a corpus, or report what destroying it would cost.

    The preview arrives as a **refusal** — `knowledge_confirm_required`, carrying what would be
    destroyed — rather than as a result, because the call genuinely did not happen. It is caught
    here rather than left to `_execute` so the account reads as a preview instead of an error.
    """
    if not args.yes:
        try:
            await client.call("knowledge_remove", {"name": args.name, "confirm": False})
        except ServiceRefusalError as refusal:
            if refusal.code != ErrorCode.KNOWLEDGE_CONFIRM_REQUIRED:
                raise
            print(f"would destroy {refusal.data.get('name')!r}: {_what_goes(refusal.data)}.")
            print("Pass --yes to actually do it.")
            return 1
        raise TypeError("knowledge_remove without confirm answered instead of refusing")
    payload = await client.call("knowledge_remove", {"name": args.name, "confirm": True})
    (entry,) = _entries(payload)
    print(f"removed   {entry['name']!r}")
    unlinked = payload.get("files_unlinked")
    if isinstance(unlinked, list):
        for path in unlinked:
            print(f"unlinked  {path}")
    return 0


def _what_goes(data: Mapping[str, object]) -> str:
    """How much a removal would destroy, or that nobody can say.

    A corpus whose database is present and will not open may hold a fully built index, so counting
    it as empty is a confident number nothing backs, on the one verb nothing undoes.
    """
    if data.get("chunks") is None:
        return "an unknown amount — its database cannot be read"
    return f"{data.get('files_indexed')} files, {data.get('chunks')} chunks, and its database"


def _print_listing(payload: Mapping[str, object], *, detailed: bool, project: Path) -> None:
    entries = _entries(payload)
    if not entries:
        print(f"no knowledge bases in {project}")
    for entry in entries:
        _print_summary(entry)
        if detailed:
            _print_details(entry)
    _print_orphans(payload.get("orphans"))


def _print_summary(entry: Mapping[str, object]) -> None:
    print(f"\n{entry.get('name')}")
    print(f"  {entry.get('description')}")
    print(
        f"  state {entry.get('state')}  files {entry.get('files_indexed')}  "
        f"remaining {_text(entry.get('files_remaining'))}"
    )


def _joined(value: object) -> str:
    """Patterns as a caller would type them, or a marker when there are none."""
    if not isinstance(value, list) or not value:
        return _UNSET
    return ", ".join(str(one) for one in value)


def _by_reason(counts: object) -> str:
    """Every skip reason with a count, or a marker when nothing was skipped.

    Reasons that fired are listed rather than the whole set every time, because the question this
    answers is *why is a file missing from the corpus* and a wall of zeroes buries the one that is
    not. The all-zero case says so explicitly, since "nothing was skipped" and "this was not
    measured" are different answers.
    """
    if not isinstance(counts, dict):
        return "none"
    fired = [f"{reason} {count}" for reason, count in sorted(counts.items()) if count]
    return ", ".join(fired) if fired else "none"


def _print_details(entry: Mapping[str, object]) -> None:
    """The diagnostic half, or why there is none.

    A corpus with nothing to report is in one of two conditions calling for opposite reassurances.
    A database that is **absent** has genuinely never been built. A database that is **present and
    will not open** may hold a completely built corpus, so telling a reader nothing has been built
    here is a confident claim about something nobody can measure. The state line above names which
    of the two it is; this line is what a reader takes the meaning from.
    """
    if "root_path" not in entry:
        if entry.get("state") == "error":
            print("  (its database is present and cannot be read — what it holds is unknown)")
        else:
            print("  (no database to read — nothing has been built here yet)")
        return
    print(f"  root      {entry.get('root_path')}")
    effective = _text(entry.get("git_mode_effective"))
    print(f"  git-mode  {entry.get('git_mode')} (last build used {effective})")
    print(f"  include   {_joined(entry.get('include'))}")
    print(f"  exclude   {_joined(entry.get('exclude'))}")
    print(f"  chunks    {entry.get('chunks')}  bytes {entry.get('bytes_indexed')}")
    print(f"  max-file  {entry.get('max_file_bytes')} bytes")
    print(f"  seen      {entry.get('files_seen')}  skipped {entry.get('files_skipped')}")
    print(f"  skipped   {_by_reason(entry.get('skipped'))}")
    print(
        f"  searches  {entry.get('searches')} ({entry.get('searches_empty')} empty), "
        f"results {entry.get('results_returned')} ({entry.get('results_stale')} stale)"
    )
    print(
        f"  last scan {_text(entry.get('last_scan_started_at'))} .. "
        f"{_text(entry.get('last_scan_completed_at'))}"
    )
    held = entry.get("lock")
    if isinstance(held, dict):
        print(f"  build     {_lock_line(held, name=str(entry.get('name')))}")


def _age(seconds: float) -> str:
    """A duration a person can read at a glance, coarse on purpose.

    The question a lock's age answers is *has this been sitting here* — minutes or days — so a
    second-exact figure would be precision nobody acts on.
    """
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            return f"{int(seconds // size)}{unit}"
    return f"{int(seconds)}s"


def _lock_line(held: Mapping[str, object], *, name: str) -> str:
    """Who is building this corpus, and what this machine can say about whether they still are.

    The live case says *a process answers to that pid* rather than *the build is running*, because
    that is all a pid probe establishes: after a crash the number is free, and a reused one looks
    exactly like the indexer that recorded it.
    """
    pid = held.get("pid")
    who = "an unreadable pid" if pid is None else f"pid {pid}"
    seconds = held.get("age_seconds")
    age = _age(float(seconds)) if isinstance(seconds, (int, float)) else _UNSET
    live = held.get("live")
    if live is True:
        standing = "a process on this host still answers to that pid"
    elif live is False:
        standing = "no longer running; the next build takes the lock over"
    else:
        standing = (
            "not something this machine can check; if you are sure it is gone, clear it with "
            f"`refresh {shlex.quote(name)} --force-unlock`"
        )
    return f"held {age} by {who} on {_text(held.get('host'))} — {standing}"


def _print_orphans(orphans: object) -> None:
    if not isinstance(orphans, list) or not orphans:
        return
    print(f"\n{len(orphans)} orphaned database(s) — no knowledge base refers to these:")
    for orphan in orphans:
        if not isinstance(orphan, dict):
            continue
        name = orphan.get("name") or "<unreadable>"
        print(f"  {orphan.get('path')}  was {name!r}  {orphan.get('size_bytes')} bytes")
    print("Nothing will open or delete them. Remove them by hand when you are sure.")
