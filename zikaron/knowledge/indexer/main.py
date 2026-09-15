"""Build one knowledge base's index, and say what the build did.

The whole of the command is here; `__main__` only turns its status into an exit. The management
command's `refresh` verb calls `build` directly rather than reimplementing it, so a build means
one thing however it was asked for.
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

import aiosqlite

from zikaron.core.config.resolution import EffectiveConfig
from zikaron.core.knowledge import lifecycle, scan
from zikaron.core.knowledge.counters import SkipReason
from zikaron.core.knowledge.meta import GitMode
from zikaron.knowledge import scope


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m zikaron.knowledge.indexer",
        description="Build one knowledge base's index: walk its root, detect what changed, and "
        "record it.",
    )
    parser.add_argument(
        "name", help="which knowledge base to build, as `python -m zikaron.knowledge list` names it"
    )
    parser.add_argument(
        "--project",
        type=Path,
        default=None,
        help="the project whose store to act on. The default is the harness's own project "
        "directory where it names one, else the current directory.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Build the named knowledge base. Returns a process exit status."""
    args = _parser().parse_args(sys.argv[1:] if argv is None else argv)
    return scope.execute(lambda: _run(args), printer=lambda line: print(line, file=sys.stderr))


async def _run(args: argparse.Namespace) -> int:
    async with scope.open_store(args.project) as store:
        return await build(store.directory, store.connection, store.config, name=args.name)


async def build(
    store_dir: Path, db: aiosqlite.Connection, config: EffectiveConfig, *, name: str
) -> int:
    """Run one build and print an account of it. Returns a process exit status.

    Args:
        store_dir: the `.zikaron` directory this store lives in.
        db: an open connection to `memory.db`, which carries the registry.
        config: the effective configuration, for reporting the corpus's state afterwards.
        name: which knowledge base to build.
    """
    refreshed = await lifecycle.refresh(store_dir, db, config, name=name)
    _print_report(refreshed)
    return 0


def _print_report(refreshed: lifecycle.Refreshed) -> None:
    result = refreshed.result
    counters = result.counters
    print(f"built     {refreshed.knowledge_base.name!r}")
    # "in the index" rather than "indexed", because the count describes the corpus this build
    # leaves behind rather than the work it did: a build that found nothing changed still reports
    # every file it confirmed is there.
    print(
        f"files     {counters.files_indexed} in the index, {result.files_deleted} deleted, "
        f"{counters.files_skipped} skipped, {counters.files_seen} seen"
    )
    print(f"bytes     {counters.bytes_indexed}")
    print(f"skipped   {_by_reason(counters.skipped)}")
    print(f"pruned    {counters.pruned_directories} directories")
    print(f"state     {refreshed.status.summary.state.value}")
    _print_caveats(result)


def _by_reason(counts: dict[SkipReason, int]) -> str:
    """Every reason that fired, with its count, or a marker when nothing was skipped.

    Only the reasons that fired, because the question this answers is *why is a file missing from
    the corpus* and a wall of zeroes buries the one that is not. The all-zero case says so
    explicitly, since "nothing was skipped" and "this was not measured" are different answers.
    """
    fired = [f"{reason.value} {count}" for reason, count in sorted(counts.items()) if count]
    return ", ".join(fired) if fired else "none"


def _print_caveats(result: scan.ScanResult) -> None:
    """Whatever made this build weaker than it was asked to be, or nothing at all.

    Each of these is a corpus shaped by something other than its own configuration, and a build
    that did not say so would leave the difference to be discovered as missing files.
    """
    if result.git_mode_effective is not result.git_mode:
        # Both causes are named because the code cannot tell them apart here — the work-tree probe
        # collapses every failure to "no" — and because the *ordinary* one is first: indexing a
        # documentation tree outside any repository is an endorsed use, and a message naming only
        # a git failure would send that operator to debug `PATH` on every build.
        print(
            f"\ngit-mode {result.git_mode.value!r} did not take effect: this root is not inside a "
            f"git work tree, or git could not answer for it, so the build ran as "
            f"{GitMode.OFF.value!r} and no git rule was applied."
        )
    if not result.attributes_available:
        print(
            "\n.gitattributes could not be read, so files this repository marks as binary were "
            "judged by their content alone."
        )
    if result.files_remaining:
        print(
            f"\n{result.files_remaining} file(s) could not be read and are still pending; they "
            "are reported as stale until a later build reaches them."
        )
