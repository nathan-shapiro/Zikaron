"""Build one knowledge base's index, and say what the build did.

The whole of the command is here; `__main__` only turns its status into an exit. The management
command **spawns this module** rather than calling `build`, so a build means one thing however it
was asked for — and `detach.command` is the argv it spawns, which is also what it prints for
anybody who has to run the same build where its output can be seen.
"""

import argparse
import asyncio
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from zikaron.core.config.resolution import EffectiveConfig
from zikaron.core.indexing.encoder import FastEmbedEncoder
from zikaron.core.knowledge import builds, disposal, lifecycle, registry, scan
from zikaron.core.knowledge.counters import SkipReason
from zikaron.core.knowledge.meta import GitMode
from zikaron.knowledge import scope
from zikaron.knowledge.indexer import build_log


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
        return await build(store, name=args.name, full=args.full)


async def build(store: scope.OpenStore, *, name: str, full: bool = False) -> int:
    """Run one build, print an account of it, and record what it cost. Returns an exit status.

    **The refusals are decided before the model is loaded**, which is a second of CPU and the most
    expensive thing this command does. It is wasted either way when a build is refused — in the
    foreground it is the operator's second, and detached it is spent on a refusal nobody will ever
    see. The build itself re-establishes each refusal, since the check and the build are not one
    transaction.

    **The corpus is resolved here, before `prepare`, and the rule for which failures get a row is
    positional rather than by class.** `prepare` returns the corpus only on success and none of the
    refusals it raises carries an `id`, so a catch site has nothing to key a row by unless this
    function already holds one. `registry.lookup` therefore runs **outside** the `try`: nothing
    raised before it returns writes a row, and everything raised after it is written under the id it
    bound, whatever its class. So `lookup`'s own two refusals write none, while the same
    `UnknownKnowledgeBaseError` raised later — by the refresh's own resolution, after a `remove`
    landed between the reads — *is* written, because by then an id is in hand. A rule by class could
    not express that difference.

    `registry.ensure` ahead of it creates the registry table if no `knowledge_add` has: this is one
    of the two writers that may, so a store no knowledge verb has touched still resolves the name
    rather than failing with *no such table*.

    **Exactly one row per build, written before the corpus lock is released wherever the lock was
    taken**, so `refresh --wait`, which watches the lock, returns after the row has landed or been
    dropped. `scan.run` calls `BuildLog.settle` for every outcome reached with the lock held; the
    failure catch here writes only for a refusal before it, and is a no-op otherwise. A failure
    after the release — the corpus handle's close, the report's own reads — exits 1 over the
    `ok=true` row the scan earned: the row describes the scan, which committed.

    `except Exception` and deliberately not `BaseException`: a `KeyboardInterrupt` or a
    `CancelledError` must not be made to wait out a lock so that its own death can be recorded.
    Such a build writes no row.

    Args:
        store: the open store to build against — its directory, its connection, its effective
            configuration, and the `schema_version` that decides whether an event row is attempted
            at all, since a direct run never migrates one.
        name: which knowledge base to build.
        full: reindex every admitted file rather than only what changed.
    """
    started = time.perf_counter()
    db = store.connection
    await registry.ensure(db)
    registered = await registry.lookup(db, name)
    log = build_log.BuildLog.opened(
        db,
        knowledge_base_id=registered.id,
        full=full,
        schema_version=store.schema_version,
        started=started,
    )
    try:
        await builds.prepare(store.directory, db, store.config, name=name)
        refreshed = await lifecycle.refresh(
            store.directory,
            db,
            store.config,
            name=name,
            build=await build_settings(store.config, full=full),
            on_completion=log.settle,
        )
    except Exception as error:
        await log.failed(error)
        raise
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
