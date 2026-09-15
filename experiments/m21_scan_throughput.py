#!/usr/bin/env python
"""Three numbers M21's brief says cannot be taken later without re-walking a real repository.

1. **Throughput** — wall time and peak RSS for one full build over a real tree, to size the
   separate-process argument against the ~124 s the design models for the embedding component
   alone. This milestone embeds nothing, so what is measured here is the *floor*: walking,
   reading, hashing and one transaction per file.
2. **The binary-with-unknown-extension fraction**, which decides whether a remembered-skip memo is
   worth building. Such a file is read in full on every scan forever, because the change-detection
   fast path can never clear a file that was never indexed. If it is a rounding error, the memo
   never gets built.
3. **The fraction of a real repository under a `.gitignore`d directory the fixed prune list does
   not already name**, which decides whether the walk should test directory nodes against
   `check-ignore` as it descends instead of discarding their files one at a time afterwards.

Run:  .venv/bin/python experiments/m21_scan_throughput.py <repository> [<repository> ...]

Each repository is measured in a throwaway store under a temporary directory, which is removed
afterwards. Nothing is written to the repository itself.
"""

from __future__ import annotations

import asyncio
import json
import os
import resource
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from zikaron.core.config.resolution import resolve  # noqa: E402
from zikaron.core.knowledge import git, lifecycle, walk  # noqa: E402
from zikaron.core.knowledge.counters import ScanCounters  # noqa: E402
from zikaron.core.knowledge.meta import GitMode  # noqa: E402
from zikaron.core.store.embedder import FakeEmbedder  # noqa: E402
from zikaron.core.store.store import Store  # noqa: E402

_KIB_PER_MIB = 1024


def _peak_rss_mib() -> float:
    """This process's high-water mark, which on Linux `getrusage` reports in KiB."""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / _KIB_PER_MIB


async def _measure_build(root: Path, mode: GitMode) -> dict[str, object]:
    """One full build over `root` in a throwaway store, timed."""
    workspace = Path(tempfile.mkdtemp(prefix="zikaron-m21-"))
    try:
        config = resolve(workspace / "system.toml", workspace / "project.toml")
        store_dir = workspace / ".zikaron"
        embedder = FakeEmbedder(config.get_str("embed_model"), config.get_int("embed_dim"))
        async with await Store.create(store_dir, config, embedder) as store:
            await lifecycle.add(
                store_dir,
                store.connection,
                config,
                lifecycle.AddRequest(
                    name="corpus",
                    root=root,
                    description="throughput measurement",
                    git_mode=mode,
                    home=workspace / "not-the-home-directory",
                ),
            )
            started = time.monotonic()
            first = await lifecycle.refresh(
                store_dir, store.connection, config, name="corpus"
            )
            cold = time.monotonic() - started

            started = time.monotonic()
            second = await lifecycle.refresh(
                store_dir, store.connection, config, name="corpus"
            )
            warm = time.monotonic() - started
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

    counters = first.result.counters
    return {
        # Recorded rather than asserted in the write-up. An earlier note claimed "an otherwise
        # idle machine" as boilerplate, from a template rather than from observation, and it was
        # false: every timing it carried was an upper bound and nothing in the file said so.
        "load_average_1m": round(os.getloadavg()[0], 2),
        "cpu_count": os.cpu_count(),
        "git_mode": mode.value,
        "git_mode_effective": first.result.git_mode_effective.value,
        "cold_seconds": round(cold, 3),
        "warm_seconds": round(warm, 3),
        "peak_rss_mib": round(_peak_rss_mib(), 1),
        "files_seen": counters.files_seen,
        "files_indexed": counters.files_indexed,
        "bytes_indexed": counters.bytes_indexed,
        "pruned_directories": counters.pruned_directories,
        "skipped": {reason.value: count for reason, count in sorted(counters.skipped.items())},
        "warm_files_indexed": second.result.counters.files_indexed,
    }


def _walked(root: Path) -> tuple[list[walk.Candidate], ScanCounters]:
    counters = ScanCounters()
    return list(walk.entries(root, counters)), counters


def _ancestors(path: str) -> list[str]:
    """Every directory above one relative path, nearest last."""
    parts = path.split("/")[:-1]
    return ["/".join(parts[: index + 1]) for index in range(len(parts))]


async def _measure_ignored_directories(root: Path) -> dict[str, object]:
    """How much of this repository sits under an ignored directory the prune list does not name.

    Every ancestor directory of every walked file is asked about in one batch. A file whose
    ancestor is ignored was walked, statted and then discarded one at a time — testing the
    directory node instead would have pruned the whole subtree.
    """
    candidates, _ = _walked(root)
    directories = sorted({ancestor for candidate in candidates for ancestor in _ancestors(candidate.path)})
    try:
        ignored = await git.ignored_paths(root, directories)
    except git.GitUnavailableError as error:
        return {"error": str(error)}
    under_ignored = [
        candidate
        for candidate in candidates
        if any(ancestor in ignored for ancestor in _ancestors(candidate.path))
    ]
    return {
        "walked_files": len(candidates),
        "directories_tested": len(directories),
        "ignored_directories": len(ignored),
        "files_under_an_ignored_directory": len(under_ignored),
        "fraction": round(len(under_ignored) / len(candidates), 4) if candidates else 0.0,
    }


def _repository_facts(root: Path) -> dict[str, object]:
    completed = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    return {
        "root": str(root),
        "head": completed.stdout.strip() or "not a repository",
    }


async def _main(root: Path, mode: GitMode) -> int:
    """One repository, one mode, one process.

    One build per invocation deliberately: peak RSS is a *process* high-water mark, so measuring
    several builds in one process would report the largest of them against every one.
    """
    facts = _repository_facts(root)
    facts["build"] = await _measure_build(root, mode)
    facts["ignored_directories"] = await _measure_ignored_directories(root)
    print(json.dumps(facts, indent=2))
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:  # noqa: PLR2004
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(
        asyncio.run(_main(Path(sys.argv[1]).resolve(), GitMode(sys.argv[2])))
    )
