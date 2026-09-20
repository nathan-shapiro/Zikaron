"""Alternative chunkers for the lever experiment, producing what the real indexer consumes.

The shipped chunker packs whole paragraphs greedily into a token budget and never overlaps, so a
passage straddling a boundary is cleanly inside neither chunk, and a section shorter than the
budget shares its chunk with whatever preceded it. Both variants here change only *where the cuts
fall*; everything downstream — the per-file transaction, both index arms, the snippet contract —
is the product's own.

Each variant returns a `FileChunkPlan`, so `disposal.py`'s call site consumes it unchanged and the
measurement compares chunking rather than two different pipelines.

**The stored text stays whole lines and the embedded body is head-cut to the budget**, exactly as
the product does it, because the invariant that a snippet is byte-identical to its line range is
what the whole retrieval contract rests on and a harness that breaks it measures something else.
"""

from collections.abc import Sequence

from zikaron.core.indexing.encoder import Encoder, assembled_tokens, token_head
from zikaron.core.knowledge.chunking import (
    PREFIX_SEPARATOR,
    FileChunk,
    FileChunkPlan,
    split_lines,
)

#: Markdown heading levels a section may start at. `#` is excluded: a single top-level title per
#: file would make the whole file one section and measure nothing.
_SECTION_LEVELS = (2, 3, 4)

#: How much of the previous chunk the overlap variant repeats, as a share of the budget.
OVERLAP_FRACTION = 0.25


def _heading_level(line: str) -> int | None:
    stripped = line.lstrip()
    if not stripped.startswith("#"):
        return None
    level = len(stripped) - len(stripped.lstrip("#"))
    return level if level in _SECTION_LEVELS else None


def _prefix_and_budget(path: str, encoder: Encoder, chunk_max_tokens: int) -> tuple[str, int]:
    """The path as it will be prepended, and the token budget left for content beside it."""
    spare = encoder.max_sequence_tokens - encoder.n_special_tokens - 2
    prefix = path
    if encoder.count_tokens(prefix) > spare - 1:
        prefix = token_head(prefix, tokens=spare - 1, encoder=encoder)
    return prefix, min(chunk_max_tokens, spare - encoder.count_tokens(prefix))


def _emit(
    lines: Sequence[str],
    start_index: int,
    end_index: int,
    *,
    part_index: int,
    prefix: str,
    budget: int,
    encoder: Encoder,
) -> FileChunk:
    """One chunk over `lines[start_index:end_index]`, with its embedded body cut to the budget."""
    text = "".join(lines[start_index:end_index])
    body = text
    if assembled_tokens(f"{prefix}{PREFIX_SEPARATOR}", body, encoder=encoder) > encoder.max_sequence_tokens:
        body = token_head(body, tokens=budget, encoder=encoder)
    return FileChunk(
        part_index=part_index,
        start_line=start_index + 1,
        end_line=end_index,
        text=text,
        embedded_body=body,
    )


def _packed_ranges(
    lines: Sequence[str], *, budget: int, encoder: Encoder, overlap: int = 0
) -> list[tuple[int, int]]:
    """Line index ranges packed greedily to `budget` tokens, each starting `overlap` tokens back.

    The step back is measured in tokens and converted to whole lines, since a chunk is whole lines
    and a partial one could not satisfy the snippet contract. A step that would not advance is
    clamped, so a file always terminates however the budget and the overlap interact.
    """
    counts = [encoder.count_tokens(line) for line in lines]
    ranges: list[tuple[int, int]] = []
    start = 0
    while start < len(lines):
        total = 0
        end = start
        while end < len(lines) and (total + counts[end] <= budget or end == start):
            total += counts[end]
            end += 1
        ranges.append((start, end))
        if end >= len(lines):
            break
        if overlap <= 0:
            start = end
            continue
        back = 0
        step = end
        while step > start + 1 and back + counts[step - 1] <= overlap:
            step -= 1
            back += counts[step]
        start = max(step, start + 1)
    return ranges


def _plan_packed(
    *, path: str, text: str, encoder: Encoder, chunk_max_tokens: int, overlap_fraction: float
) -> FileChunkPlan:
    prefix, budget = _prefix_and_budget(path, encoder, chunk_max_tokens)
    lines = split_lines(text)
    chunks = [
        _emit(lines, start, end, part_index=i, prefix=prefix, budget=budget, encoder=encoder)
        for i, (start, end) in enumerate(
            _packed_ranges(
                lines, budget=budget, encoder=encoder, overlap=int(budget * overlap_fraction)
            )
        )
    ]
    return FileChunkPlan(prefix=prefix, effective_budget=budget, chunks=tuple(chunks))


def plan_without_overlap(
    *, path: str, text: str, encoder: Encoder, chunk_max_tokens: int
) -> FileChunkPlan:
    """Line-greedy packing with no overlap — the control for `plan_with_overlap`.

    The shipped chunker packs whole *paragraphs*; these variants pack *lines*. Comparing an
    overlapping line-greedy index directly against the shipped one would confound the overlap with
    the change of packing unit, so this arm holds the packing and removes only the overlap.
    """
    return _plan_packed(
        path=path,
        text=text,
        encoder=encoder,
        chunk_max_tokens=chunk_max_tokens,
        overlap_fraction=0.0,
    )


def plan_with_overlap(
    *, path: str, text: str, encoder: Encoder, chunk_max_tokens: int
) -> FileChunkPlan:
    """Line-greedy packing where each chunk repeats the tail of the one before it."""
    return _plan_packed(
        path=path,
        text=text,
        encoder=encoder,
        chunk_max_tokens=chunk_max_tokens,
        overlap_fraction=OVERLAP_FRACTION,
    )


def plan_with_breadcrumb(
    *, path: str, text: str, encoder: Encoder, chunk_max_tokens: int
) -> FileChunkPlan:
    """The shipped cuts, with each chunk embedded under the headings it sits beneath.

    The shipped prefix is the file path, which says what the *document* is about. A chunk of prose
    partway down a long document is frequently about a narrower subject that its own words never
    restate, because the heading two screens above already said it — and that heading is exactly
    what a reader uses to know what they are looking at. Prepending the enclosing headings gives
    the embedder the same cue.

    **Only the embedded sequence changes.** `text` remains the file's bytes for its line range, so
    a snippet still round-trips against the file, and the breadcrumb is charged against the same
    budget as any other prefix rather than being added on top of a sequence already proved to fit.
    """
    prefix, budget = _prefix_and_budget(path, encoder, chunk_max_tokens)
    lines = split_lines(text)
    trail = _heading_trail(lines)
    chunks: list[FileChunk] = []
    for part_index, (start, end) in enumerate(
        _packed_ranges(lines, budget=budget, encoder=encoder)
    ):
        crumb = trail[start]
        body = "".join(lines[start:end])
        embedded = f"{crumb}\n{body}" if crumb else body
        if (
            assembled_tokens(f"{prefix}{PREFIX_SEPARATOR}", embedded, encoder=encoder)
            > encoder.max_sequence_tokens
        ):
            embedded = token_head(embedded, tokens=budget, encoder=encoder)
        chunks.append(
            FileChunk(
                part_index=part_index,
                start_line=start + 1,
                end_line=end,
                text=body,
                embedded_body=embedded,
            )
        )
    return FileChunkPlan(prefix=prefix, effective_budget=budget, chunks=tuple(chunks))


def _heading_trail(lines: Sequence[str]) -> list[str]:
    """For each line, the breadcrumb of headings enclosing it."""
    stack: dict[int, str] = {}
    trail: list[str] = []
    for line in lines:
        level = _heading_level(line)
        if level is not None:
            stack = {lv: title for lv, title in stack.items() if lv < level}
            stack[level] = line.lstrip().lstrip("#").strip()
        trail.append(" > ".join(stack[lv] for lv in sorted(stack)))
    return trail


def _plan_sectioned(
    *,
    path: str,
    text: str,
    encoder: Encoder,
    chunk_max_tokens: int,
    overlap_fraction: float,
    breadcrumb: bool,
) -> FileChunkPlan:
    prefix, budget = _prefix_and_budget(path, encoder, chunk_max_tokens)
    lines = split_lines(text)
    trail = _heading_trail(lines)
    boundaries = [i for i, line in enumerate(lines) if _heading_level(line) is not None]
    starts = sorted({0, *boundaries})
    sections = [
        (start, starts[position + 1] if position + 1 < len(starts) else len(lines))
        for position, start in enumerate(starts)
    ]
    overlap = int(budget * overlap_fraction)
    chunks: list[FileChunk] = []
    for start, end in sections:
        if start >= end:
            continue
        for span in _packed_ranges(
            lines[start:end], budget=budget, encoder=encoder, overlap=overlap
        ):
            first, last = start + span[0], start + span[1]
            body = "".join(lines[first:last])
            crumb = trail[first] if breadcrumb else ""
            embedded = f"{crumb}\n{body}" if crumb else body
            if (
                assembled_tokens(f"{prefix}{PREFIX_SEPARATOR}", embedded, encoder=encoder)
                > encoder.max_sequence_tokens
            ):
                embedded = token_head(embedded, tokens=budget, encoder=encoder)
            chunks.append(
                FileChunk(
                    part_index=len(chunks),
                    start_line=first + 1,
                    end_line=last,
                    text=body,
                    embedded_body=embedded,
                )
            )
    return FileChunkPlan(prefix=prefix, effective_budget=budget, chunks=tuple(chunks))


def plan_by_section(
    *, path: str, text: str, encoder: Encoder, chunk_max_tokens: int
) -> FileChunkPlan:
    """Cut at markdown headings first, then pack within a section.

    A section shorter than the budget becomes exactly one chunk, so a heading and the prose that
    answers it stay together rather than being split by wherever the running token count happened
    to land. A section longer than the budget is packed greedily inside its own boundaries and
    never merges with the next one.
    """
    return _plan_sectioned(
        path=path,
        text=text,
        encoder=encoder,
        chunk_max_tokens=chunk_max_tokens,
        overlap_fraction=0.0,
        breadcrumb=False,
    )


def plan_section_overlap(
    *, path: str, text: str, encoder: Encoder, chunk_max_tokens: int
) -> FileChunkPlan:
    """Section cuts, with overlap between the chunks *inside* a long section.

    Section boundaries fix where an answer begins; overlap fixes an answer straddling a cut made
    inside a section too long to hold in one chunk. The two address different halves of the same
    failure, so this arm exists to say whether the halves add.
    """
    return _plan_sectioned(
        path=path,
        text=text,
        encoder=encoder,
        chunk_max_tokens=chunk_max_tokens,
        overlap_fraction=OVERLAP_FRACTION,
        breadcrumb=False,
    )


def plan_section_overlap_breadcrumb(
    *, path: str, text: str, encoder: Encoder, chunk_max_tokens: int
) -> FileChunkPlan:
    """Section cuts, overlap inside a section, and the enclosing headings on what is embedded."""
    return _plan_sectioned(
        path=path,
        text=text,
        encoder=encoder,
        chunk_max_tokens=chunk_max_tokens,
        overlap_fraction=OVERLAP_FRACTION,
        breadcrumb=True,
    )
