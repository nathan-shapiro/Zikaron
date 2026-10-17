"""What the planner reads: a module's sources as the corpus walk admits them, their hashes, and the
documents already under the module's documents directory.

The walk and admission are `zikaron.core.knowledge`'s own, under `git_mode = all`
(`design/code-knowledge.md` §3.2), and the hash is K14's (§3.3), so the producer and a search agree
on what a file is and what it hashes to.
"""

import asyncio
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from zikaron.core.code_knowledge.layout import DOCUMENT_SUFFIX, Layout, path_order
from zikaron.core.knowledge import candidates, git, walk
from zikaron.core.knowledge.counters import ScanCounters
from zikaron.core.knowledge.meta import GitMode
from zikaron.core.knowledge.source_hash import HashBudget, Hashed, Source, hash_sources

#: A hashing batch closes once its sources' absolute paths total this many bytes. `hash_sources`
#: passes a batch to git as arguments, and a vector past `ARG_MAX` — 1 MiB on macOS — fails to
#: start git, which `hash_sources` answers with the in-process form, filters unapplied.
HASH_BATCH_PATH_BYTES: Final = 128 * 1024

#: The width the in-process form computes. It is reached only when git cannot be started, and then
#: the repository's object format cannot be asked either.
_IN_PROCESS_WIDTH: Final = 40

_BYTE_ORDER_MARK: Final = chr(0xFEFF)


@dataclass(frozen=True, slots=True)
class ModuleSources:
    """The module's sources, root-relative and in path order, with how git was consulted and what
    the walk refused."""

    paths: tuple[str, ...]
    effective: GitMode
    counters: ScanCounters


def _walked(module_dir: Path, layout: Layout, counters: ScanCounters) -> list[walk.Candidate]:
    return [
        candidate
        for candidate in walk.entries(module_dir, counters)
        if not layout.holds_documents(layout.source(candidate.path))
    ]


async def _ignore_answers(module_dir: Path, found: list[walk.Candidate]) -> candidates.GitAnswers:
    """What `.gitignore` excludes of `found`, or that git could not be consulted.

    Only `check-ignore`, where `candidates.gather` also lists and diffs the repository for a scan's
    change detection — answers the planner never reads, and `git status` alone grows with the whole
    repository rather than the module. Its failure degrades to `off` as `gather`'s does, since
    candidacy rests on it.
    """
    if not await git.inside_work_tree(module_dir):
        return candidates.GitAnswers(effective=GitMode.OFF)
    try:
        ignored = await git.ignored_paths(module_dir, [candidate.path for candidate in found])
    except git.GitUnavailableError:
        return candidates.GitAnswers(effective=GitMode.OFF)
    return candidates.GitAnswers(effective=GitMode.ALL, ignored=ignored)


async def module_sources(root: Path, layout: Layout, rules: walk.WalkRules) -> ModuleSources:
    """The module's files as the corpus walk admits them with `.gitignore` applied, and the globs
    `rules` carries over each one's path relative to the module."""
    module_dir = root / layout.module
    counters = ScanCounters()
    found = await asyncio.to_thread(_walked, module_dir, layout, counters)
    answers = await _ignore_answers(module_dir, found)
    admitted = walk.admitted(found, ignored=answers.ignored, rules=rules, counters=counters)
    admitted = await candidates.narrow(module_dir, admitted, answers, counters)
    return ModuleSources(
        paths=tuple(sorted((layout.source(c.path) for c in admitted), key=path_order)),
        effective=answers.effective,
        counters=counters,
    )


def hash_batches(root: Path, sources: Sequence[str]) -> list[list[str]]:
    """`sources`, in order, cut into batches whose absolute paths total at most
    `HASH_BATCH_PATH_BYTES`, each path's terminating NUL counted.

    A walked source's absolute path is its real path: the root is resolved and the walk follows no
    symlink, so this is the length `hash_sources` passes to git.
    """
    batches: list[list[str]] = []
    batch: list[str] = []
    size = 0
    for source in sources:
        cost = len(os.fsencode(root / source)) + 1
        if batch and size + cost > HASH_BATCH_PATH_BYTES:
            batches.append(batch)
            batch, size = [], 0
        batch.append(source)
        size += cost
    if batch:
        batches.append(batch)
    return batches


async def hashes(root: Path, sources: Sequence[str]) -> dict[str, Hashed]:
    """Every source's hash, or the state that answered for it, each batch under a budget of its
    own rather than one search's."""
    answered: dict[str, Hashed] = {}
    for batch in hash_batches(root, sources):
        found = await hash_sources(
            root,
            [Source(path=path, width=_IN_PROCESS_WIDTH) for path in batch],
            budget=HashBudget(),
        )
        answered.update({source.path: hashed for source, hashed in found.items()})
    return answered


@dataclass(frozen=True, slots=True)
class ModuleDocuments:
    """Every document under the module's documents directory, the README apart.

    A text is `None` for a file that could not be read as UTF-8 text — a symlink, anything that is
    not a regular file, an unreadable or undecodable one — which the planner judges foreign.
    """

    texts: Mapping[str, str | None]
    readme: str | None
    readme_present: bool


def _text(entry: os.DirEntry[str]) -> str | None:
    try:
        if not entry.is_file(follow_symlinks=False):
            return None
        return Path(entry.path).read_bytes().decode("utf-8").removeprefix(_BYTE_ORDER_MARK)
    except (OSError, UnicodeDecodeError):
        return None


def _entries(directory: Path) -> list[os.DirEntry[str]]:
    try:
        with os.scandir(directory) as scanning:
            return list(scanning)
    except OSError:
        return []


def module_documents(root: Path, layout: Layout) -> ModuleDocuments:
    """Every `.md` file under the module's documents directory, pruning the directory names the
    corpus walk prunes, since a document there could not be indexed."""
    texts: dict[str, str | None] = {}
    readme: str | None = None
    readme_present = False
    stack = [(root / layout.module_documents, layout.module_documents)]
    while stack:
        directory, prefix = stack.pop()
        for entry in _entries(directory):
            path = f"{prefix}/{entry.name}"
            if entry.is_dir(follow_symlinks=False):
                if not walk.is_pruned_directory(entry.name):
                    stack.append((Path(entry.path), path))
            elif path == layout.readme:
                readme, readme_present = _text(entry), True
            elif entry.name.endswith(DOCUMENT_SUFFIX):
                texts[path] = _text(entry)
    return ModuleDocuments(texts=texts, readme=readme, readme_present=readme_present)
