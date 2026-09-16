"""`python -m zikaron.knowledge` — the knowledge-base verbs, for a person at a shell.

Flow, argument parsing and printing live here; every decision lives in `zikaron.core.knowledge`,
which the agent-facing tools will call through the same functions. This module deliberately holds
no rule of its own, so the two surfaces cannot diverge on what a verb means.

**Nothing here waits for a build.** `add` and `refresh` start one and return, because a build is
minutes of work over a whole directory tree and holding a shell for it would make the two verbs that
create a corpus the two slowest things this command does. The build is its own command with its own
entry point, which is both what gets spawned and what an operator runs by hand when they want to
watch one.
"""

import argparse
import shlex
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

import aiosqlite

from zikaron.core.config.resolution import EffectiveConfig
from zikaron.core.knowledge import lifecycle, lock, meta, reporting
from zikaron.knowledge import scope
from zikaron.knowledge.indexer import detach

_UNSET = "—"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m zikaron.knowledge",
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
    adding.add_argument("--path", type=Path, required=True, help="the directory to index")
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
        type=meta.GitMode,
        choices=tuple(meta.GitMode),
        default=meta.GitMode.TRACKED,
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
    refreshing.add_argument("name")
    refreshing.add_argument(
        "--full",
        action="store_true",
        help="reindex every file rather than only what changed. For when the thing that moved is "
        "not the files: a changed chunk budget, or content the index was handed through a filter "
        "that has changed since.",
    )
    refreshing.add_argument(
        "--force-unlock",
        action="store_true",
        help="clear a build lock nothing will clear on its own — one recorded by another machine, "
        "which this one cannot probe. Refuses while a process on this host still answers to the "
        "recorded pid.",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one verb, printing an account of what happened. Returns a process exit status.

    Returns rather than calling `sys.exit`, so a test drives the whole command in-process and
    reads both the status and the output. `__main__` is the only place a status becomes an exit.
    """
    args = _parser().parse_args(sys.argv[1:] if argv is None else argv)
    return scope.execute(lambda: _run(args), printer=lambda line: print(line, file=sys.stderr))


async def _run(args: argparse.Namespace) -> int:
    """Open the store once, run the verb, and close it however it ends."""
    async with scope.open_store(args.project) as store:
        return await _dispatch(args, store)


async def _dispatch(args: argparse.Namespace, store: scope.OpenStore) -> int:
    store_dir, db, config = store.directory, store.connection, store.config
    if args.verb == "list":
        _print_listing(await reporting.list_bases(store_dir, db, config), detailed=False)
        return 0
    if args.verb == "status":
        _print_listing(await reporting.status(store_dir, db, config, name=args.name), detailed=True)
        return 0
    if args.verb == "add":
        return await _add(args, store)
    if args.verb == "rename":
        renamed = await lifecycle.rename(
            store_dir, db, config, name=args.name, new_name=args.new_name
        )
        print(f"renamed to {renamed.summary.name!r}")
        return 0
    if args.verb == "remove":
        return await _remove(args, store_dir, db, config)
    if args.verb == "refresh":
        return await _refresh(args, store)
    # Unreachable through the command, which refuses an unknown verb before dispatch. Loud rather
    # than a trailing `return`, because the branch a fall-through would land in is the destructive
    # one — a verb added to the parser and forgotten here must fail, not remove a knowledge base.
    raise NotImplementedError(f"no handler for the verb {args.verb!r}")


async def _add(args: argparse.Namespace, store: scope.OpenStore) -> int:
    created = await lifecycle.add(
        store.directory,
        store.connection,
        store.config,
        lifecycle.AddRequest(
            name=args.name,
            root=args.path,
            description=args.description,
            include_globs=tuple(args.include),
            exclude_globs=tuple(args.exclude),
            git_mode=args.git_mode,
            max_file_bytes=args.max_file_bytes,
        ),
    )
    print(f"added     {created.knowledge_base.name!r}")
    print(f"database  {created.database_path}")
    # The state a corpus is created in, before its first build has committed anything. It is the
    # honest answer rather than a placeholder: the database exists and its settings are sound, and
    # nothing has been indexed into it yet.
    print(f"state     {created.status.summary.state.value}")
    if created.git_mode_effective is not created.git_mode:
        print(
            f"\ngit-mode {created.git_mode.value!r} will not take effect: {args.path} is not "
            f"inside a git work tree, so this corpus is built as "
            f"{created.git_mode_effective.value!r}."
        )
    _start_build(created.knowledge_base.name, store, full=False)
    return 0


async def _refresh(args: argparse.Namespace, store: scope.OpenStore) -> int:
    """Clear a lock if asked to, check what can be checked, and start a build in the background."""
    if args.force_unlock:
        _report_unlock(await lifecycle.unlock(store.directory, store.connection, name=args.name))
    # Everything decidable without reading a file is decided here, in front of whoever ran this:
    # the build itself detaches, and a refusal it raised would go to a discarded stream.
    registered = await lifecycle.prepare_build(store.directory, store.connection, name=args.name)
    _start_build(registered.name, store, full=args.full)
    return 0


def _report_unlock(cleared: lock.LockHolder | None) -> None:
    if cleared is None:
        print("unlocked  no lock was recorded; nothing to clear")
        return
    print(f"unlocked  cleared the lock held by {cleared.describe()}")


def _start_build(name: str, store: scope.OpenStore, *, full: bool) -> None:
    """Spawn the build and say how to follow it, and how to see it fail.

    The foreground command is printed in full rather than described, because it is the only way to
    recover the *reason* a detached build failed: its own output goes nowhere, so what is left is
    to run the identical command where its output can be seen. It is the argv the spawn reports
    rather than a second construction of it, so the two cannot differ.
    """
    argv = detach.spawn(name, project=store.project, full=full)
    print(f"building  {name!r} in the background")
    # Quoted, because a name is free-form and two-word ones are ordinary — an unquoted one pasted
    # back is a command that fails to parse, which is worse than useless in a line offered as the
    # way to follow a build.
    print(f"follow    python -m zikaron.knowledge status {shlex.quote(name)}")
    print("\nThat build's output is discarded. To watch one, or to see why one failed:")
    print(f"  {shlex.join(argv)}")


async def _remove(
    args: argparse.Namespace,
    store_dir: Path,
    db: aiosqlite.Connection,
    config: EffectiveConfig,
) -> int:
    if not args.yes:
        listing = await reporting.status(store_dir, db, config, name=args.name)
        (found,) = listing.knowledge_bases
        indexed = found.details.chunks if found.details is not None else 0
        print(
            f"would destroy {found.summary.name!r}: "
            f"{found.summary.files_indexed} files, {indexed} chunks, and its database."
        )
        print("Pass --yes to actually do it.")
        return 1
    removed = await lifecycle.remove(store_dir, db, config, name=args.name)
    print(f"removed   {removed.knowledge_base.name!r}")
    for path in removed.files_unlinked:
        print(f"unlinked  {path}")
    return 0


def _print_listing(listing: reporting.Listing, *, detailed: bool) -> None:
    if not listing.knowledge_bases:
        print("no knowledge bases in this project")
    for report in listing.knowledge_bases:
        _print_summary(report.summary)
        if detailed:
            _print_details(report.details)
    _print_orphans(listing.orphans)


def _print_summary(summary: reporting.Summary) -> None:
    remaining = _UNSET if summary.files_remaining is None else str(summary.files_remaining)
    print(f"\n{summary.name}")
    print(f"  {summary.description}")
    print(f"  state {summary.state.value}  files {summary.files_indexed}  remaining {remaining}")


def _joined(values: Sequence[str]) -> str:
    """Patterns as a caller would type them, or a marker when there are none."""
    return ", ".join(values) if values else _UNSET


def _by_reason(counts: Mapping[str, int]) -> str:
    """Every skip reason with a count, or a marker when nothing was skipped.

    Reasons that fired are listed rather than the whole nine every time, because the question this
    answers is *why is a file missing from the corpus* and a wall of zeroes buries the one that is
    not. The all-zero case says so explicitly instead of printing an empty line, since "nothing was
    skipped" and "this was not measured" are different answers.
    """
    fired = [f"{reason} {count}" for reason, count in sorted(counts.items()) if count]
    return ", ".join(fired) if fired else "none"


def _print_details(details: reporting.Details | None) -> None:
    if details is None:
        print("  (no database to read — nothing has been built here yet)")
        return
    effective = _UNSET if details.git_mode_effective is None else details.git_mode_effective.value
    print(f"  root      {details.root_path}")
    print(f"  git-mode  {details.git_mode.value} (last build used {effective})")
    print(f"  include   {_joined(details.include_globs)}")
    print(f"  exclude   {_joined(details.exclude_globs)}")
    print(f"  chunks    {details.chunks}  bytes {details.bytes_indexed}")
    print(f"  max-file  {details.max_file_bytes} bytes")
    print(f"  seen      {details.files_seen}  skipped {details.files_skipped}")
    print(f"  skipped   {_by_reason(details.skipped)}")
    print(
        f"  searches  {details.searches} ({details.searches_empty} empty), "
        f"results {details.results_returned} ({details.results_stale} stale)"
    )
    print(
        f"  last scan {details.last_scan_started_at or _UNSET} .. "
        f"{details.last_scan_completed_at or _UNSET}"
    )
    if details.lock is not None:
        print(f"  build     {_lock_line(details.lock)}")


def _age(seconds: float) -> str:
    """A duration a person can read at a glance, coarse on purpose.

    The question a lock's age answers is *has this been sitting here* — minutes or days — so a
    second-exact figure would be precision nobody acts on, over a number large enough to have to be
    counted digit by digit.
    """
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            return f"{int(seconds // size)}{unit}"
    return f"{int(seconds)}s"


def _lock_line(report: reporting.LockReport) -> str:
    """Who is building this corpus, and what this machine can say about whether they still are.

    The live case says *a process answers to that pid* rather than *the build is running*, because
    that is all a pid probe establishes: after a crash the number is free, and a reused one looks
    exactly like the indexer that recorded it.
    """
    who = "an unreadable pid" if report.pid is None else f"pid {report.pid}"
    age = _UNSET if report.age_seconds is None else _age(report.age_seconds)
    if report.live is True:
        standing = "a process on this host still answers to that pid"
    elif report.live is False:
        standing = "no longer running; the next build takes the lock over"
    else:
        standing = (
            "not something this machine can check; if you are sure it is gone, clear it with "
            "`refresh --force-unlock`"
        )
    return f"held {age} by {who} on {report.host or _UNSET} — {standing}"


def _print_orphans(orphans: Sequence[reporting.Orphan]) -> None:
    if not orphans:
        return
    print(f"\n{len(orphans)} orphaned database(s) — no knowledge base refers to these:")
    for orphan in orphans:
        name = orphan.breadcrumb_name or "<unreadable>"
        print(f"  {orphan.path}  was {name!r}  {orphan.size_bytes} bytes")
    print("Nothing will open or delete them. Remove them by hand when you are sure.")
