"""One indexed file's text in, the exact chunks that will be stored and embedded out.

Every function here is **pure** — no store, no connection, no clock — which is what lets a plan be
built before any transaction opens and lets its determinism be asserted by running it twice.

Three properties shape all of it, and each of them is a promise something else depends on:

- **A chunk holds whole lines, verbatim.** Terminators, trailing whitespace and blank lines are
  preserved exactly, so the stored text is byte-identical to the lines its range names and a caller
  can read that range back and get the same bytes. Anything else — stripping, rejoining, collapsing
  — makes a fragment that *looks* like the file and is not.
- **The chunks of one file partition its lines**, contiguously, with no gap and no overlap. So
  nothing is indexed twice and nothing is silently dropped, and the two facts are checkable by
  concatenation rather than by trusting the packer.
- **What is embedded fits the model**, counted on the assembled sequence — prefix, separator, body
  and special tokens — rather than on the body alone, because the sum of two counts is not the count
  of their concatenation and the failure it hides is a sequence the model truncates in silence.

Paragraphs are what packing *prefers* rather than what it is made of: a break falls after a blank
line wherever the budget allows, and at an ordinary line boundary where it does not.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final

from zikaron.core.errors import ErrorCode, IndexStage, ZikaronError
from zikaron.core.indexing.chunking import PREFIX_SEPARATOR, SEPARATOR_TOKENS
from zikaron.core.indexing.encoder import Encoder, assembled_tokens, token_head

#: The one character that ends a line. Deliberately **not** `str.splitlines`, which also breaks on
#: `\v`, `\f`, a lone `\r`, `\x1c` to `\x1e`, `\x85` and the two Unicode separators U+2028/U+2029 —
#: nine characters no editor, no `git` and no file-reading tool counts as a line break. A form feed
#: inside a source file would otherwise shift every line number after it, and a range that names the
#: wrong lines is worse than no range at all because it reads as precise. A `\r\n` file needs no
#: special case: the `\r` is part of that line's text and is preserved with it.
LINE_END: Final = "\n"

#: The least content a chunk may carry, which is what the prefix must leave room for. One token, so
#: that a path long enough to crowd out the content yields rather than making the file unindexable.
_MINIMUM_CONTENT_TOKENS: Final = 1


@dataclass(frozen=True, slots=True)
class FileChunk:
    """One chunk of one file, as it will be stored and as it will be embedded.

    `text` is stored and is verbatim. `embedded_body` is what actually reaches the model, and the
    two differ in exactly one case: a single line too long to fit the budget is stored whole and
    embedded from its head, because the alternative is either a stored fragment that no longer
    matches the file or a sequence the model truncates without saying so.

    Line numbers are 1-based and inclusive, and describe `text`.
    """

    part_index: int
    start_line: int
    end_line: int
    text: str
    embedded_body: str

    @property
    def head_only(self) -> bool:
        """Whether only the head of this chunk's text was embedded.

        True only for a single line longer than the budget. The stored text is unaffected, so this
        says something about dense reach rather than about what a reader will be shown: the tail is
        still indexed lexically, and still returned in a snippet.
        """
        return self.embedded_body != self.text

    def embedded_text(self, path: str) -> str:
        """The sequence actually embedded: the file's path, one separator, then this chunk's body.

        Prefixing with the path is what keeps a chunk from being an orphan — a paragraph of
        instructions with nothing saying what they concern — and it is why the budget is computed
        against the assembled sequence rather than against the body alone.
        """
        return f"{path}{PREFIX_SEPARATOR}{self.embedded_body}"


@dataclass(frozen=True, slots=True)
class FileChunkPlan:
    """Every chunk one file produces, in `part_index` order, plus what they were cut to fit.

    **`prefix` is carried here rather than taken from the caller at embed time**, and that is what
    makes the budget honest: it is the exact string every chunk's sequence was measured against, so
    the sequence that reaches the model is the one this plan proved fits. It is the file's path,
    shortened only where a path long enough to crowd out the content forced it.

    A file with no lines at all produces no chunks, which is the truth about an empty file rather
    than a case to reject: it has nothing to index and its `files` row records a chunk count of
    zero.
    """

    prefix: str
    effective_budget: int
    chunks: tuple[FileChunk, ...]

    @property
    def n_chunks(self) -> int:
        """How many chunks this plan holds."""
        return len(self.chunks)

    @property
    def head_only_chunks(self) -> int:
        """How many chunks were embedded from a head rather than whole."""
        return sum(1 for chunk in self.chunks if chunk.head_only)

    def embedded_texts(self) -> tuple[str, ...]:
        """Every chunk's assembled sequence, in `part_index` order — the embedder's input.

        Takes no prefix: it uses this plan's own, so the text that reaches the model cannot be
        assembled against a different string from the one the budget was proved against.
        """
        return tuple(chunk.embedded_text(self.prefix) for chunk in self.chunks)


@dataclass(frozen=True, slots=True)
class _Unit:
    """A run of lines the packer moves as one: a paragraph with its trailing blank lines, or,
    where a paragraph will not fit, a single line."""

    start_line: int
    lines: tuple[str, ...]
    tokens: int

    @property
    def text(self) -> str:
        return "".join(self.lines)

    @property
    def end_line(self) -> int:
        return self.start_line + len(self.lines) - 1


def _index_failed(stage: IndexStage) -> ZikaronError:
    return ZikaronError(ErrorCode.INDEX_FAILED, stage=stage)


def split_lines(text: str) -> tuple[str, ...]:
    """`text` as its lines, each carrying its own terminator, in order.

    The last line has no terminator when the file does not end in one, which is what makes the
    stored text a byte-exact copy of the range it names — a chunker that appended a newline the file
    never had would produce a snippet that disagrees with the file by one byte, on the one file
    shape most likely to be quoted.
    """
    if not text:
        return ()
    parts = text.split(LINE_END)
    lines = [f"{part}{LINE_END}" for part in parts[:-1]]
    if parts[-1]:
        lines.append(parts[-1])
    return tuple(lines)


def _is_blank(line: str) -> bool:
    return not line.strip()


def _paragraph_units(lines: Sequence[str], *, encoder: Encoder) -> tuple[_Unit, ...]:
    """The file's lines grouped into paragraphs, each carrying the blank lines that follow it.

    A group ends exactly where a non-blank line follows a blank one, which is the blank-line
    paragraph boundary stated in terms of the lines themselves. Blank lines stay attached to the
    paragraph above rather than starting a group of their own, so that a chunk break lands *after*
    the blank run — where a reader would put it — and every line still belongs to exactly one group.
    """
    units: list[_Unit] = []
    current: list[str] = []
    start_line = 1
    for offset, line in enumerate(lines, start=1):
        if current and not _is_blank(line) and _is_blank(current[-1]):
            units.append(_unit(start_line, current, encoder=encoder))
            current = []
            start_line = offset
        current.append(line)
    if current:
        units.append(_unit(start_line, current, encoder=encoder))
    return tuple(units)


def _unit(start_line: int, lines: Sequence[str], *, encoder: Encoder) -> _Unit:
    kept = tuple(lines)
    return _Unit(start_line=start_line, lines=kept, tokens=encoder.count_tokens("".join(kept)))


def _single_lines(unit: _Unit, *, encoder: Encoder) -> Iterable[_Unit]:
    """One unit per line of `unit`, for a paragraph that will not fit a chunk on its own."""
    return (
        _unit(unit.start_line + offset, [line], encoder=encoder)
        for offset, line in enumerate(unit.lines)
    )


class _Packer:
    """Greedy, forward-only accumulation of units into chunks of at most `budget` tokens.

    **The running token count is a sum of the units' own counts, and that is exact here rather than
    an approximation.** Units are joined at a line terminator, and the tokenizer's pre-tokenizer
    splits on whitespace, so no token ever spans the join — measured on the deployed artifact. It is
    a sum rather than a recount of the accumulated text because recounting is quadratic in the
    number of units: at the measured tokenizer throughput, a megabyte of single-token lines would
    cost minutes of tokenization for one file. **Nothing rests on the assumption**: every emitted
    chunk's text is recounted afterwards, and a chunk that overran its budget is refused there.
    """

    __slots__ = ("_budget", "_chunks", "_encoder", "_pending", "_tokens")

    def __init__(self, *, budget: int, encoder: Encoder) -> None:
        self._budget = budget
        self._encoder = encoder
        self._chunks: list[FileChunk] = []
        self._pending: list[_Unit] = []
        self._tokens = 0

    def fits(self, unit: _Unit) -> bool:
        """Whether `unit` can join what is pending without exceeding the budget."""
        return self._tokens + unit.tokens <= self._budget

    def add(self, unit: _Unit) -> None:
        """Accumulate `unit` into the chunk being built."""
        self._pending.append(unit)
        self._tokens += unit.tokens

    def flush(self) -> None:
        """Emit what is pending as one chunk, if there is anything pending."""
        if not self._pending:
            return
        text = "".join(unit.text for unit in self._pending)
        self._emit(
            start_line=self._pending[0].start_line,
            end_line=self._pending[-1].end_line,
            text=text,
            embedded_body=text,
        )
        self._pending = []
        self._tokens = 0

    def emit_head_of(self, unit: _Unit) -> None:
        """Emit one over-long line as its own chunk, stored whole and embedded from its head.

        Called only with a single line that does not fit an empty chunk, which is the one place the
        whole-lines rule and the model's input cap cannot both be satisfied. Storing the line whole
        keeps the range honest; embedding its head keeps the truncation ours and deliberate rather
        than the model's and silent.
        """
        self._emit(
            start_line=unit.start_line,
            end_line=unit.end_line,
            text=unit.text,
            embedded_body=token_head(unit.text, tokens=self._budget, encoder=self._encoder),
        )

    def chunks(self) -> tuple[FileChunk, ...]:
        """Every chunk emitted so far, in `part_index` order."""
        return tuple(self._chunks)

    def _emit(self, *, start_line: int, end_line: int, text: str, embedded_body: str) -> None:
        self._chunks.append(
            FileChunk(
                part_index=len(self._chunks),
                start_line=start_line,
                end_line=end_line,
                text=text,
                embedded_body=embedded_body,
            )
        )


def _pack(units: Sequence[_Unit], *, budget: int, encoder: Encoder) -> tuple[FileChunk, ...]:
    """Fill chunks with whole paragraphs where they fit, and with whole lines where they do not."""
    packer = _Packer(budget=budget, encoder=encoder)
    for unit in units:
        if packer.fits(unit):
            packer.add(unit)
            continue
        packer.flush()
        if packer.fits(unit):
            packer.add(unit)
            continue
        for line in _single_lines(unit, encoder=encoder):
            if packer.fits(line):
                packer.add(line)
                continue
            packer.flush()
            if packer.fits(line):
                packer.add(line)
                continue
            packer.emit_head_of(line)
    packer.flush()
    return packer.chunks()


def plan_file_chunks(
    *, path: str, text: str, encoder: Encoder, chunk_max_tokens: int
) -> FileChunkPlan:
    """Cut one file's text into the chunks that will be stored and embedded for it.

    Pure: the same arguments produce byte-identical chunks on every call and in every process, which
    is what every claim about deterministic chunk boundaries rests on.

    **A path long enough to crowd out the content is shortened, not refused.** The prefix is an
    address rather than content: it earns its place by giving a chunk something to be *about*, and a
    head of it still does that. Refusing instead would make a single deep path an unindexable file —
    deterministically, on every build, with nothing in any report explaining which file or why — and
    the remedy would be for somebody to guess at an exclude glob. Since a path of that length is
    already pathological, the prefix yields to the content rather than the other way round.

    Args:
        path: this file's path relative to the corpus root, prepended to every chunk at embed time
            and never stored in a chunk's text.
        text: the file's decoded content.
        encoder: the deployed artifact — its tokenizer does the counting, and its special-token
            count and sequence cap set the budget alongside `chunk_max_tokens`.
        chunk_max_tokens: this corpus's own per-chunk budget, which binds unless the path is long
            enough that the model's cap binds first.

    Returns:
        A plan whose chunks partition `text`'s lines in order, and the prefix they are assembled
        with — which is `path` unless it had to be shortened. A file with no lines produces no
        chunks.

    Raises:
        ZikaronError: `INDEX_FAILED` at stage `budget` if the model's own cap leaves no room for one
            token of content beside the special tokens and the separator, which is a configured
            model too small to embed anything rather than anything about this file; or at stage
            `assembly` if the chunks the packing produced do not in fact satisfy their own budget or
            the model's cap, which is a defect here rather than anything about the file.
    """
    spare = encoder.max_sequence_tokens - encoder.n_special_tokens - SEPARATOR_TOKENS
    if spare < _MINIMUM_CONTENT_TOKENS:
        raise _index_failed(IndexStage.BUDGET)
    prefix = path
    if encoder.count_tokens(prefix) > spare - _MINIMUM_CONTENT_TOKENS:
        prefix = token_head(prefix, tokens=spare - _MINIMUM_CONTENT_TOKENS, encoder=encoder)
    budget = min(chunk_max_tokens, spare - encoder.count_tokens(prefix))
    lines = split_lines(text)
    plan = FileChunkPlan(
        prefix=prefix,
        effective_budget=budget,
        chunks=_pack(_paragraph_units(lines, encoder=encoder), budget=budget, encoder=encoder),
    )
    _assert_plan_is_within_its_budgets(plan, encoder=encoder)
    return plan


def _assert_plan_is_within_its_budgets(plan: FileChunkPlan, *, encoder: Encoder) -> None:
    """Refuse a plan the packing did not actually satisfy, on either of its two bounds.

    Both are checked by **recounting** what was emitted rather than by trusting the counts that
    drove the packing, which is what makes this a post-condition instead of a restatement — and what
    makes the packer's running sum safe to use: if joining units ever did merge tokens across a line
    terminator, the chunk it produced would be refused here rather than handed to a model that
    truncates it in silence.

    A failure is `index_failed` at the `assembly` stage: not a truncation, and not something a
    caller can fix, so the file's transaction rolls back rather than writing a chunk whose vector
    describes less text than its row claims.
    """
    for chunk in plan.chunks:
        if encoder.count_tokens(chunk.embedded_body) > plan.effective_budget:
            raise _index_failed(IndexStage.ASSEMBLY)
        # The separator rides with the prefix rather than being charged as a constant, so what is
        # counted here is byte-for-byte the string `embedded_texts` emits. Counting
        # `prefix + body` instead would leave the sequence that actually reaches the model counted
        # nowhere: the budget derivation charges the separator as a fixed token over pieces counted
        # apart, and this recount is the only place the whole thing is measured as one string.
        if (
            assembled_tokens(
                f"{plan.prefix}{PREFIX_SEPARATOR}", chunk.embedded_body, encoder=encoder
            )
            > encoder.max_sequence_tokens
        ):
            raise _index_failed(IndexStage.ASSEMBLY)
