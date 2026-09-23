"""Build one knowledge base's index, and say what the build did.

The whole of the command is here; `__main__` only turns its status into an exit. The management
command **spawns this module** rather than calling `build`, so a build means one thing however it
was asked for — and `detach.command` is the argv it spawns, which is also what it prints for
anybody who has to run the same build where its output can be seen.
"""

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

import aiosqlite

from zikaron.core.config.resolution import EffectiveConfig
from zikaron.core.indexing.encoder import FastEmbedEncoder
from zikaron.core.knowledge import builds, disposal, lifecycle, scan
from zikaron.core.knowledge.counters import SkipReason
from zikaron.core.knowledge.meta import GitMode
from zikaron.knowledge import scope


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        # Derived rather than written out, so the usage text stays true through a rename — this is
        # the same module path the spawn builds its argv from, and two spellings of it would drift.
        prog=f"python -m {__package__}",
        description="Build one knowledge base's index: walk its root, detect what changed, and "
        "record it.",
    )
    parser.add_argument(
        "name", help="which knowledge base to build, as `zikaron knowledge list` names it"
    )
    parser.add_argument(
        "--project",
        type=Path,
        default=None,
        help="the project whose store to act on. The default is the harness's own project "
        "directory where it names one, else the current directory.",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="reindex every file rather than only what changed.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Build the named knowledge base. Returns a process exit status."""
    args = _parser().parse_args(sys.argv[1:] if argv is None else argv)
    return scope.execute(lambda: _run(args), printer=lambda line: print(line, file=sys.stderr))


async def _run(args: argparse.Namespace) -> int:
    async with scope.open_store(args.project) as store:
        return await build(
            store.directory, store.connection, store.config, name=args.name, full=args.full
        )


async def build(
    store_dir: Path,
    db: aiosqlite.Connection,
    config: EffectiveConfig,
    *,
    name: str,
    full: bool = False,
) -> int:
    """Run one build and print an account of it. Returns a process exit status.

    **The refusals are decided before the model is loaded**, which is a second of CPU and the most
    expensive thing this command does. It is wasted either way when a build is refused — in the
    foreground it is the operator's second, and detached it is spent on a refusal nobody will ever
    see. The build itself re-establishes each refusal, since the check and the build are not one
    transaction.

    Args:
        store_dir: the `.zikaron` directory this store lives in.
        db: an open connection to `memory.db`, which carries the registry.
        config: the effective configuration: which encoder to load, how many chunks to embed per
            pass, and what to compare the built corpus's identity against afterwards.
        name: which knowledge base to build.
        full: reindex every admitted file rather than only what changed.
    """
    await builds.prepare(store_dir, db, config, name=name)
    refreshed = await lifecycle.refresh(
        store_dir, db, config, name=name, build=await build_settings(config, full=full)
    )
    _print_report(refreshed)
    return 0


async def build_settings(config: EffectiveConfig, *, full: bool = False) -> disposal.BuildSettings:
    """Load the configured encoder and read the batch size, for one build.

    The load costs roughly a second and runs on a worker thread, which keeps it off the event loop
    rather than making it cheaper — a build is a batch job with no interactive path to protect, so
    paying it up front and once is the right trade. A corpus whose recorded identity disagrees with
    what this loads is not refused: it is rebuilt at the new identity, which is the only repair
    available once the width of a stored vector has stopped matching what the model emits.
    """
    return disposal.BuildSettings(
        encoder=await asyncio.to_thread(FastEmbedEncoder.load, config.get_str("embed_model")),
        embed_batch=config.get_int("knowledge_embed_batch"),
        full=full,
    )


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
    _print_rebuild(result)


def _print_rebuild(result: scan.ScanResult) -> None:
    """Say when a build was a rebuild, because nothing in its numbers would show it.

    A rebuild reindexes every file and deletes none, which is what a corpus's first build looks
    like too — and what changed is not in the corpus at all but in what embedded it.

    The wording names the outcome rather than the cause, because there are two and the numbers
    distinguish neither: the model may have moved under the index, or the vector table may have
    been found declared at a width the corpus's own record does not name, which nothing this
    program does can produce and a restored or hand-edited database can.
    """
    rebuilt = result.rebuilt_identity
    if rebuilt is None:
        return
    print(
        f"\nThis corpus's stored vectors did not match the model it records, so its index was "
        f"discarded and made again with {rebuilt.embed_model!r} at {rebuilt.embed_dim} dimensions."
    )


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
