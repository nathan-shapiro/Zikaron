"""Searching one knowledge base: fuse both arms, cap what one file may fill, and answer honestly.

The read path inside a corpus is the store's own benchmarked one — dense and lexical fused by
reciprocal rank at the corpus's own `rrf_k` — over chunks instead of memories. What is different
here is everything downstream of the ranking, and each difference answers a question a file corpus
raises and a memory store does not:

- **A result is a fragment with an address**, so it carries the line range its snippet covers and a
  reader can widen it. The snippet is verbatim file content: no ellipses, no match markers, no
  normalization, and no path prefix — so reading those lines back returns the same bytes.
- **One file may not fill an answer.** A large document chunks into many pieces that all resemble
  each other, and without a per-file cap the best few of them crowd out every other file.
- **A result says whether it may be out of date**, because the file on disk is the authority and
  the index is a copy of it. `false` there means *no evidence of change* rather than a guarantee,
  and the two known gaps are stated rather than hidden.
"""

import asyncio
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import accumulate
from pathlib import Path

import aiosqlite

from zikaron.core.knowledge import arms, chunking
from zikaron.core.knowledge.meta import KnowledgeMeta
from zikaron.core.retrieval.arms import cosine_from_distance
from zikaron.core.retrieval.query import PreparedQuery
from zikaron.core.retrieval.ranking import rrf_score


@dataclass(frozen=True, slots=True)
class SearchSettings:
    """The three bounds one search answers under, all already resolved and checked.

    `limit_per_kb` arrives clamped rather than validated: a caller asking for more results than the
    cap allows is asking for as many as it can have, and refusing the call would hand back nothing
    over a number the caller does not care about.
    """

    limit_per_kb: int
    max_chunks_per_file: int
    snippet_max_chars: int


@dataclass(frozen=True, slots=True)
class Result:
    """One fragment, with everything a reader needs in order to act on it or to distrust it."""

    path: str
    start_line: int
    end_line: int
    snippet: str
    truncated: bool
    score: float
    stale: bool


@dataclass(frozen=True, slots=True)
class _Fused:
    """One chunk that at least one arm returned, with what the arms said about it."""

    chunk_id: int
    fused_score: float
    best_rank: int
    distance: float | None


@dataclass(frozen=True, slots=True)
class _StoredChunk:
    """A chunk as the index holds it, before it is cut to a snippet."""

    path: str
    start_line: int
    text: str


def _fuse(
    dense: Sequence[arms.ArmRow], lexical: Sequence[arms.ArmRow], *, rrf_k: int
) -> tuple[_Fused, ...]:
    """Both arms' rows as one ordered pool, best first.

    Reciprocal rank fusion over the arms that returned each chunk — an arm that did not return it
    contributes nothing, rather than a term at a notional worst rank. The order is then made total:
    the fused score, then the best rank any arm gave it (a chunk one arm put first is a better bet
    than one both arms put tenth), then the chunk id, which is arbitrary and is the point, since it
    is what makes one corpus and one query always produce the same list.
    """
    by_id: dict[int, list[arms.ArmRow]] = {}
    for row in [*dense, *lexical]:
        by_id.setdefault(row.chunk_id, []).append(row)
    fused = [
        _Fused(
            chunk_id=chunk_id,
            fused_score=rrf_score((row.rank for row in rows), rrf_k=rrf_k),
            best_rank=min(row.rank for row in rows),
            distance=next((row.distance for row in rows if row.distance is not None), None),
        )
        for chunk_id, rows in by_id.items()
    ]
    return tuple(sorted(fused, key=lambda one: (-one.fused_score, one.best_rank, one.chunk_id)))


def _capped(
    pool: Iterable[_Fused], stored: Mapping[int, _StoredChunk], *, settings: SearchSettings
) -> tuple[_Fused, ...]:
    """The best chunks in order, with at most `max_chunks_per_file` from any one file.

    Applied before the output limit rather than after it, so a document that chunks into fifty
    near-identical pieces spends two slots and leaves the rest of the answer to other files. The
    best-scoring chunks of that file are the ones that survive, since the pool is already ordered.
    """
    kept: list[_Fused] = []
    per_file: dict[str, int] = {}
    for one in pool:
        chunk = stored.get(one.chunk_id)
        if chunk is None:
            # A chunk id an arm returned and the chunk table does not have. The full-text index is
            # external-content, so a maintenance bug can leave postings for rows that are gone —
            # and this is the one place that can notice quietly, because a `MATCH` answers a rowid
            # normally and raises only when a column is projected.
            continue
        seen = per_file.get(chunk.path, 0)
        if seen >= settings.max_chunks_per_file:
            continue
        per_file[chunk.path] = seen + 1
        kept.append(one)
        if len(kept) >= settings.limit_per_kb:
            break
    return tuple(kept)


async def _stored_chunks(
    db: aiosqlite.Connection, chunk_ids: Sequence[int]
) -> dict[int, _StoredChunk]:
    """The rows behind a pool of chunk ids, in one statement rather than one per id."""
    if not chunk_ids:
        return {}
    placeholders = ", ".join("?" for _ in chunk_ids)
    rows = await db.execute_fetchall(
        "SELECT id, path, start_line, text FROM chunks "  # noqa: S608 — placeholders only; every id is a bound parameter.
        f"WHERE id IN ({placeholders})",
        tuple(chunk_ids),
    )
    return {
        int(chunk_id): _StoredChunk(path=str(path), start_line=int(start_line), text=str(text))
        for chunk_id, path, start_line, text in rows
    }


async def _missing_cosines(
    db: aiosqlite.Connection, chunk_ids: Sequence[int], *, vector: bytes
) -> dict[int, float]:
    """The cosine for each of `chunk_ids`, for chunks the dense arm never scored.

    A chunk the lexical arm alone surfaced has no distance in hand, and it needs one twice over: it
    is what the result reports as its score, and a group whose hits are *all* lexical would
    otherwise have no ordering key at all. One statement for all of them, bounded by the output
    limit rather than by the corpus.

    The arithmetic is the extension's own `vec_distance_L2`, the same function the nearest-neighbour
    path evaluates — decoding the coordinates and re-summing them here would round differently, and
    a chunk sitting on a threshold would then clear it under one path and not the other.
    """
    if not chunk_ids:
        return {}
    placeholders = ", ".join("?" for _ in chunk_ids)
    rows = await db.execute_fetchall(
        "SELECT chunk_id, vec_distance_L2(embedding, ?) FROM chunks_vec "  # noqa: S608 — placeholders only; every id is a bound parameter.
        f"WHERE chunk_id IN ({placeholders})",
        (vector, *chunk_ids),
    )
    return {int(chunk_id): cosine_from_distance(float(distance)) for chunk_id, distance in rows}


def cut_to_snippet(text: str, *, start_line: int, max_chars: int) -> tuple[str, int, bool]:
    """A chunk's text as a snippet, with the last line it covers and whether it was cut.

    The governing property is that the snippet is byte-identical to lines `start_line` through the
    returned line of the file, so a caller can read that range and get the same bytes, quote a
    command out of it, or widen it for context. A cut therefore removes **whole lines from the
    end** — the result is fewer lines of the file, never a doctored version of more.

    **The one exception is when not even the chunk's first line fits.** There is then no whole-line
    prefix to return, so the cut lands *inside* that line: the snippet is a prefix of it, `end_line`
    names it, and any further lines of the chunk are outside the snippet entirely — `truncated` is
    all that says so. The alternative is an unbounded string in a bounded response, and nothing
    useful can be done about a forty-kilobyte minified line the text detection admitted.

    Note that this does **not** require the chunk to be one line: a chunk of six lines whose first
    is longer than the cap takes the same path.

    Args:
        text: the chunk's stored text, verbatim. A chunk always holds at least one line.
        start_line: the file line `text` begins at.
        max_chars: `knowledge_snippet_max_chars`, counted in Unicode code points.

    Returns:
        The snippet, the file line it ends at, and whether anything was left out.
    """
    lines = chunking.split_lines(text)
    if len(text) <= max_chars:
        return text, start_line + len(lines) - 1, False
    # How many whole lines fit, counted from the running total rather than by accumulating and
    # breaking: the totals only increase, so counting the ones within the cap *is* the greedy
    # answer — and it has no loop exit that the arithmetic above has already made unreachable.
    fitting = sum(1 for total in accumulate(len(line) for line in lines) if total <= max_chars)
    if fitting == 0:
        return text[:max_chars], start_line, True
    return "".join(lines[:fitting]), start_line + fitting - 1, True


async def _pending_paths(db: aiosqlite.Connection, paths: Sequence[str]) -> set[str]:
    """Which of `paths` the walk phase has flagged as changed and not yet disposed of."""
    if not paths:
        return set()
    placeholders = ", ".join("?" for _ in paths)
    rows = await db.execute_fetchall(
        f"SELECT path FROM pending WHERE path IN ({placeholders})",  # noqa: S608 — placeholders only; every path is a bound parameter.
        tuple(paths),
    )
    return {str(path) for (path,) in rows}


def _size_disagrees(absolute: Path, indexed_size: int) -> bool:
    """Whether a live look at the file contradicts what the index recorded, or cannot be taken.

    **A failed `stat` is the strongest staleness evidence available**, not an edge case to fall
    through: it usually means the file is gone, so the range this result points at cannot be read
    at all. It is neither a size difference nor a pending row, so it has to be named here or it
    falls through both.

    Size is a cheap discriminator rather than a complete one — an edit that keeps a file's length
    is invisible to it — which is why the flag means *no evidence of change* rather than *no
    change*.
    """
    try:
        return absolute.stat().st_size != indexed_size
    except OSError:
        return True


#: The recorded size of a path the `files` table has no row for. No real size can equal it, so such
#: a path always reads as stale — which is the honest answer: the index holds a fragment it has no
#: record of having indexed, and cannot say what it was taken from.
_NO_RECORDED_SIZE = -1


async def _indexed_sizes(db: aiosqlite.Connection, paths: Sequence[str]) -> dict[str, int]:
    if not paths:
        return {}
    placeholders = ", ".join("?" for _ in paths)
    rows = await db.execute_fetchall(
        f"SELECT path, size FROM files WHERE path IN ({placeholders})",  # noqa: S608 — placeholders only; every path is a bound parameter.
        tuple(paths),
    )
    return {str(path): int(size) for path, size in rows}


async def _stale_paths(db: aiosqlite.Connection, paths: Sequence[str], *, root: Path) -> set[str]:
    """Every path among `paths` with evidence of having changed since it was indexed.

    Two disjuncts, and both are needed: the walk phase may have noticed a change the index phase has
    not reached yet, and a file may have changed since any scan looked at it. No hashing happens
    here — the latency belongs to the query, and a hash of every result's file would spend it on
    certainty nobody asked for.
    """
    pending = await _pending_paths(db, paths)
    sizes = await _indexed_sizes(db, paths)
    checked = await asyncio.to_thread(
        lambda: {
            path
            for path in paths
            if _size_disagrees(root / path, sizes.get(path, _NO_RECORDED_SIZE))
        }
    )
    return pending | checked


async def search_one(
    db: aiosqlite.Connection,
    *,
    query: PreparedQuery,
    corpus: KnowledgeMeta,
    settings: SearchSettings,
) -> tuple[Result, ...]:
    """Search one knowledge base and return its results, best first.

    Args:
        db: an open connection to this knowledge base.
        query: the prepared query, whose vector is unit length so that a distance read back off it
            is a cosine.
        corpus: this knowledge base's own `meta` — its `rrf_k`, its `fusion_depth`, and the root its
            paths are relative to.
        settings: the output limit, the per-file cap and the snippet cap.

    Returns:
        At most `limit_per_kb` results, ordered by fused rank. **`score` is deliberately not
        monotone down that list**, because it is a cosine and the order is a fusion of two arms.
    """
    dense_rows = await arms.dense(db, vector=query.vector, fusion_depth=corpus.fusion_depth)
    lexical_rows: tuple[arms.ArmRow, ...] = ()
    if query.lexical.expression is not None:
        lexical_rows = await arms.lexical(
            db, expression=query.lexical.expression, fusion_depth=corpus.fusion_depth
        )
    pool = _fuse(dense_rows, lexical_rows, rrf_k=corpus.rrf_k)
    stored = await _stored_chunks(db, [one.chunk_id for one in pool])
    kept = _capped(pool, stored, settings=settings)
    cosines = await _missing_cosines(
        db, [one.chunk_id for one in kept if one.distance is None], vector=query.vector
    )
    # Distinct, because the per-file cap lets one file hold several of these and a repeated path
    # would mean two `stat` calls and a longer `IN` list for one answer.
    paths = sorted({stored[one.chunk_id].path for one in kept})
    stale = await _stale_paths(db, paths, root=Path(corpus.root_path))
    results: list[Result] = []
    for one in kept:
        chunk = stored[one.chunk_id]
        score = (
            cosine_from_distance(one.distance)
            if one.distance is not None
            else cosines.get(one.chunk_id)
        )
        if score is None:
            # A chunk with no vector, which every build makes impossible: the two are written and
            # deleted in one transaction. Reaching it means the index disagrees with itself, and
            # omitting the chunk is the honest answer where inventing a score would put a number
            # nothing produced beside numbers that mean something.
            continue
        snippet, end_line, truncated = cut_to_snippet(
            chunk.text, start_line=chunk.start_line, max_chars=settings.snippet_max_chars
        )
        results.append(
            Result(
                path=chunk.path,
                start_line=chunk.start_line,
                end_line=end_line,
                snippet=snippet,
                truncated=truncated,
                score=score,
                stale=chunk.path in stale,
            )
        )
    return tuple(results)
