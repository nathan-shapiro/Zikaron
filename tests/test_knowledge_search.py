"""Searching one knowledge base: what comes back, what it points at, and when it says so.

The property every test here leans on is the one an agent acts on: a result's snippet is exactly
lines `start_line` to `end_line` of the file it names. It is asserted by reading those lines back
off the real file rather than by comparing the snippet against the row it came from, because the
row and the file are precisely the two things that can drift apart.
"""

from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Final

import pytest

from tests.fake_encoder import FakeEncoder, unit_at
from tests.knowledge_fixtures import (
    Corpus,
    add_request,
    build_index,
    config_for,
    open_corpus,
    open_index,
    write_config,
    write_tree,
)
from zikaron.core.knowledge import arms, pending, search
from zikaron.core.knowledge.chunking import plan_file_chunks
from zikaron.core.knowledge.meta import GitMode
from zikaron.core.knowledge.search import Result, SearchSettings, cut_to_snippet

_DEFAULT_SETTINGS: Final = SearchSettings(
    limit_per_kb=5, max_chunks_per_file=2, snippet_max_chars=1200
)


def read_lines(path: Path, start_line: int, end_line: int) -> str:
    """Lines `start_line` to `end_line` of `path`, inclusive and 1-based, exactly as they are.

    Written out here so the round-trip is asserted against the file rather than against the
    database row the snippet came from.

    **Decoded from bytes rather than read as text**, which is not fussiness: Python's text mode
    applies universal-newline translation, so it hands back `\\n` where a CRLF file holds `\\r\\n`
    — and a comparison made through it would pass for a snippet that had quietly lost a byte per
    line. The claim under test is about bytes, so the test reads bytes.
    """
    text = path.read_bytes().decode("utf-8")
    lines = text.split("\n")
    kept = [f"{line}\n" for line in lines[:-1]]
    if lines[-1]:
        kept.append(lines[-1])
    return "".join(kept[start_line - 1 : end_line])


async def _search(
    corpus: Corpus,
    query: str,
    *,
    encoder: FakeEncoder | None = None,
    settings_used: SearchSettings = _DEFAULT_SETTINGS,
) -> tuple[Result, ...]:
    """Run one query against one built corpus, the way the service does."""
    using = encoder if encoder is not None else FakeEncoder()
    config = config_for(corpus.store_dir.parent)
    prepared = arms.unit_query(
        query,
        encoder=using,
        prefix=config.get_str("embed_prefix_query"),
        max_terms=config.get_int("fts_query_max_terms"),
    ).prepared
    async with open_index(corpus) as opened:
        return await search.search_one(
            opened.connection, query=prepared, corpus=opened.meta, settings=settings_used
        )


#: Files whose shape a chunker that normalizes anything would get wrong, each by a different
#: mechanism. Shared by the round-trip test and available to any other that needs a corpus with
#: something other than tidy prose in it.
AWKWARD_CORPUS: Final[dict[str, bytes]] = {
    "trailing.md": b"protobuf step   \n\n\n   \nsecond protobuf paragraph\t\n",
    "indented.py": b"def step():\n    # indented protobuf comment\n        deeper = True\n",
    "unterminated.sh": b"set -euo pipefail\nmake protobuf step",
    "carriage.md": b"carriage step one\r\ncarriage step two\r\n",
    "minified.txt": ("minified " + "x" * 400 + "\nprotobuf after it\n").encode("utf-8"),
    "blank.md": b"\n\n\n",
}


def _corpus(tmp_path: Path, layout: dict[str, bytes]) -> AbstractAsyncContextManager[Corpus]:
    """A corpus over `layout`, with git left out of it so the machine's own repository cannot
    change what these assert."""
    root = write_tree(tmp_path / "corpus", layout)
    return open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF))


class TestWhatAResultPointsAt:
    async def test_the_matching_file_ranks_first_and_names_the_lines_it_came_from(
        self, tmp_path: Path
    ) -> None:
        """First rather than alone: neither arm applies a relevance floor, so a small corpus
        returns everything it has and what a query decides is the *order*."""
        async with _corpus(
            tmp_path, {"a.md": b"nothing here\n", "b.md": b"the protobuf step fails silently\n"}
        ) as corpus:
            await build_index(corpus)
            results = await _search(corpus, "protobuf")
            assert results[0].path == "b.md"
            assert (results[0].start_line, results[0].end_line) == (1, 1)

    async def test_the_snippet_is_the_file_bytes_for_the_range_it_reports(
        self, tmp_path: Path
    ) -> None:
        layout = {
            "notes.md": b"# Heading\n\nthe protobuf step fails silently\n\nsecond paragraph\n"
        }
        async with _corpus(tmp_path, layout) as corpus:
            await build_index(corpus)
            (result,) = await _search(corpus, "protobuf")
            on_disk = read_lines(corpus.root / result.path, result.start_line, result.end_line)
            assert result.snippet == on_disk

    async def test_a_file_with_no_final_newline_round_trips_too(self, tmp_path: Path) -> None:
        """The shape a chunker that appends a terminator would get wrong by exactly one byte, and
        the one most likely to be quoted back into a shell."""
        async with _corpus(tmp_path, {"run.sh": b"set -euo pipefail\nmake protobuf"}) as corpus:
            await build_index(corpus)
            (result,) = await _search(corpus, "protobuf")
            assert result.snippet.endswith("make protobuf")
            assert result.snippet == read_lines(
                corpus.root / result.path, result.start_line, result.end_line
            )

    async def test_the_snippet_carries_no_path_prefix(self, tmp_path: Path) -> None:
        async with _corpus(tmp_path, {"docs/protobuf.md": b"alpha\n"}) as corpus:
            await build_index(corpus)
            (result,) = await _search(corpus, "protobuf")
            assert result.snippet == "alpha\n"


class TestTheRoundTripProperty:
    async def test_every_result_over_an_awkward_corpus_reads_back_identically(
        self, tmp_path: Path
    ) -> None:
        """The corpus is the point: every file here is a shape that breaks a chunker which
        normalizes anything — trailing whitespace, indentation, blank runs, a missing final
        newline, CRLF endings, and a line long enough to be cut.

        The property allows exactly one inequality: when a chunk's **first line** alone exceeds the
        cap there is no whole-line prefix to return, so the cut lands inside that line and the
        snippet is a **prefix** of the range rather than all of it, flagged by `truncated`. Every
        other result, truncated or not, is byte-identical to the lines it reports — a whole-lines
        cut lowers `end_line` along with it.
        """
        async with _corpus(tmp_path, AWKWARD_CORPUS) as corpus:
            await build_index(corpus)
            mid_line_cuts = 0
            for query in ("protobuf", "step", "indented", "carriage", "minified"):
                results = await _search(
                    corpus,
                    query,
                    settings_used=SearchSettings(
                        limit_per_kb=20, max_chunks_per_file=20, snippet_max_chars=120
                    ),
                )
                assert results
                for result in results:
                    on_disk = read_lines(
                        corpus.root / result.path, result.start_line, result.end_line
                    )
                    if result.snippet == on_disk:
                        continue
                    mid_line_cuts += 1
                    assert result.truncated is True
                    assert result.start_line == result.end_line
                    assert on_disk.startswith(result.snippet)
            assert mid_line_cuts, "the corpus no longer exercises the one allowed inequality"


class TestTheSnippetCap:
    async def test_a_chunk_over_the_cap_is_cut_at_a_line_boundary(self, tmp_path: Path) -> None:
        body = "".join(f"protobuf line {index}\n" for index in range(40))
        async with _corpus(tmp_path, {"long.md": body.encode("utf-8")}) as corpus:
            await build_index(corpus)
            (result,) = await _search(
                corpus,
                "protobuf",
                settings_used=SearchSettings(
                    limit_per_kb=5, max_chunks_per_file=2, snippet_max_chars=60
                ),
            )
            assert result.truncated is True
            assert result.snippet.endswith("\n")
            assert result.snippet == read_lines(
                corpus.root / result.path, result.start_line, result.end_line
            )

    def test_a_snippet_within_the_cap_is_not_flagged(self) -> None:
        snippet, end_line, truncated = cut_to_snippet("one\ntwo\n", start_line=4, max_chars=100)
        assert (snippet, end_line, truncated) == ("one\ntwo\n", 5, False)

    def test_a_single_line_over_the_cap_is_cut_mid_line_and_flagged(self) -> None:
        """The one case that breaks the whole-lines rule, and it is stated rather than hidden:
        nothing useful can be done about a minified line, and the alternative is an unbounded
        string in a bounded response."""
        snippet, end_line, truncated = cut_to_snippet("x" * 50 + "\n", start_line=9, max_chars=10)
        assert (snippet, end_line, truncated) == ("x" * 10, 9, True)

    def test_a_multi_line_chunk_whose_first_line_is_over_the_cap_is_cut_inside_it(self) -> None:
        """It does not take a one-line chunk to reach that case, and saying "a single line longer
        than the cap" hides which condition actually fires. What decides it is whether the *first*
        line fits: when it does not there is no whole-line prefix to return, and the chunk's later
        lines fall outside the snippet with only `truncated` to say so."""
        snippet, end_line, truncated = cut_to_snippet(
            "x" * 50 + "\nsecond line\nthird line\n", start_line=9, max_chars=10
        )
        assert (snippet, end_line, truncated) == ("x" * 10, 9, True)


class TestWhatOneFileMayFill:
    async def test_one_file_contributes_at_most_the_per_file_cap(self, tmp_path: Path) -> None:
        """A large document chunks into pieces that all resemble each other, and without the cap
        the best few crowd out every other file.

        The corpus is built at the smallest chunk budget configuration allows, because at the
        default one every paragraph here would land in a single chunk and the cap would never be
        reached — an assertion that passes because the condition it names cannot arise is worth
        nothing.
        """
        write_config(tmp_path, "[indexing]\nchunk_max_tokens = 64\n")
        crowded = "".join(f"protobuf paragraph {index} " * 30 + "\n\n" for index in range(10))
        layout = {"big.md": crowded.encode("utf-8"), "small.md": b"protobuf once\n"}
        async with _corpus(tmp_path, layout) as corpus:
            async with open_index(corpus) as opened:
                assert opened.meta.chunk_max_tokens == 64
            await build_index(corpus)
            async with open_index(corpus) as opened:
                rows = await opened.connection.execute_fetchall(
                    "SELECT count(*) FROM chunks WHERE path = 'big.md'"
                )
                ((chunks_in_the_big_file,),) = list(rows)
            assert int(chunks_in_the_big_file) > 2
            results = await _search(
                corpus,
                "protobuf",
                settings_used=SearchSettings(
                    limit_per_kb=5, max_chunks_per_file=2, snippet_max_chars=1200
                ),
            )
            assert sum(1 for result in results if result.path == "big.md") == 2
            assert "small.md" in {result.path for result in results}

    async def test_the_output_limit_bounds_the_results(self, tmp_path: Path) -> None:
        layout = {f"f{index}.md": b"protobuf\n" for index in range(8)}
        async with _corpus(tmp_path, layout) as corpus:
            await build_index(corpus)
            results = await _search(
                corpus,
                "protobuf",
                settings_used=SearchSettings(
                    limit_per_kb=3, max_chunks_per_file=2, snippet_max_chars=1200
                ),
            )
            assert len(results) == 3


class TestScoring:
    async def test_a_chunk_only_the_lexical_arm_found_still_has_a_cosine(
        self, tmp_path: Path
    ) -> None:
        """Without the explicit vector lookup a lexical-only hit has no score to report, and a
        group whose hits are all lexical would have no ordering key at all.

        Reaching that case takes a corpus deeper than the arm: at the shipped depth a small corpus
        is returned whole by the dense arm, so every hit has a distance already and the lookup this
        is about never runs. `fusion_depth = 1` makes the two arms disagree by construction.
        """
        write_config(tmp_path, "[retrieval]\nfusion_depth = 1\n")
        encoder = FakeEncoder()
        prefix = config_for(tmp_path).get_str("embed_prefix_query")
        target = b"zzqqidentifier here\n"
        plan = plan_file_chunks(
            path="target.md", text=target.decode(), encoder=encoder, chunk_max_tokens=450
        )
        # Planted as far from the query as a unit vector can be, so the dense arm at depth one
        # returns some other chunk and this one is reached by the lexical arm alone — and its
        # cosine is then known exactly rather than being whatever a hash produced.
        encoder.planned[plan.chunks[0].embedded_text("target.md")] = unit_at(180.0, encoder.dim)
        encoder.planned[f"{prefix}zzqqidentifier"] = unit_at(0.0, encoder.dim)
        layout: dict[str, bytes] = {
            f"f{index}.md": f"filler {index}\n".encode() for index in range(6)
        }
        layout["target.md"] = target
        async with _corpus(tmp_path, layout) as corpus:
            await build_index(corpus, encoder=encoder)
            results = await _search(corpus, "zzqqidentifier", encoder=encoder)
            lexical_only = next(result for result in results if result.path == "target.md")
            assert lexical_only.score == pytest.approx(-1.0, abs=1e-5)

    async def test_a_planted_pair_scores_as_its_angle_says(self, tmp_path: Path) -> None:
        """A cosine rather than a fused rank, asserted against a vector planted at a known angle —
        the two differ by an order of magnitude, so a reader comparing groups would be misled by
        the wrong one."""
        encoder = FakeEncoder()
        config = config_for(tmp_path)
        prefix = config.get_str("embed_prefix_query")
        plan = plan_file_chunks(
            path="a.md", text="alpha beta\n", encoder=encoder, chunk_max_tokens=450
        )
        encoder.planned[plan.chunks[0].embedded_text("a.md")] = unit_at(0.0, encoder.dim)
        encoder.planned[f"{prefix}alpha"] = unit_at(60.0, encoder.dim)
        async with _corpus(tmp_path, {"a.md": b"alpha beta\n"}) as corpus:
            await build_index(corpus, encoder=encoder)
            (result,) = await _search(corpus, "alpha", encoder=encoder)
            assert result.score == pytest.approx(0.5, abs=1e-5)

    async def test_an_embedder_returning_a_long_query_vector_still_scores_a_cosine(
        self, tmp_path: Path
    ) -> None:
        """A score is a cosine, and `1 - d^2/2` over a stored distance is a cosine only when both
        vectors are unit length. The corpus is normalized at write time; the query is normalized
        before it is bound, and this is what says so — the planted query points the same way as the
        one above and is three times as long, so an implementation that skipped it would report a
        number outside the range a cosine even has.
        """
        encoder = FakeEncoder()
        config = config_for(tmp_path)
        prefix = config.get_str("embed_prefix_query")
        plan = plan_file_chunks(
            path="a.md", text="alpha beta\n", encoder=encoder, chunk_max_tokens=450
        )
        encoder.planned[plan.chunks[0].embedded_text("a.md")] = unit_at(0.0, encoder.dim)
        encoder.planned[f"{prefix}alpha"] = tuple(
            3.0 * value for value in unit_at(60.0, encoder.dim)
        )
        async with _corpus(tmp_path, {"a.md": b"alpha beta\n"}) as corpus:
            await build_index(corpus, encoder=encoder)
            (result,) = await _search(corpus, "alpha", encoder=encoder)
            assert result.score == pytest.approx(0.5, abs=1e-5)

    async def test_a_query_of_pure_punctuation_still_answers(self, tmp_path: Path) -> None:
        """No term survives the lexical constructor, so that arm is skipped rather than raising or
        matching everything — and the dense arm still runs."""
        async with _corpus(tmp_path, {"a.md": b"alpha\n"}) as corpus:
            await build_index(corpus)
            assert await _search(corpus, "?!...")


class TestStaleness:
    async def test_an_untouched_file_is_not_stale(self, tmp_path: Path) -> None:
        async with _corpus(tmp_path, {"a.md": b"protobuf\n"}) as corpus:
            await build_index(corpus)
            (result,) = await _search(corpus, "protobuf")
            assert result.stale is False

    async def test_a_file_whose_size_moved_is_stale(self, tmp_path: Path) -> None:
        async with _corpus(tmp_path, {"a.md": b"protobuf\n"}) as corpus:
            await build_index(corpus)
            (corpus.root / "a.md").write_bytes(b"protobuf and more besides\n")
            (result,) = await _search(corpus, "protobuf")
            assert result.stale is True

    async def test_a_file_that_is_gone_is_stale(self, tmp_path: Path) -> None:
        """The strongest staleness evidence there is: the range this result points at cannot be
        read at all, and a failed look is neither a size difference nor a pending row."""
        async with _corpus(tmp_path, {"a.md": b"protobuf\n"}) as corpus:
            await build_index(corpus)
            (corpus.root / "a.md").unlink()
            (result,) = await _search(corpus, "protobuf")
            assert result.stale is True

    async def test_a_file_the_walk_flagged_is_stale_before_the_index_phase_reaches_it(
        self, tmp_path: Path
    ) -> None:
        """The disjunct the pending table exists for: a change the walk noticed and the index
        phase has not yet disposed of, which no live look at the file would reveal if the edit
        happened to keep its size."""
        async with _corpus(tmp_path, {"a.md": b"protobuf\n"}) as corpus:
            await build_index(corpus)
            async with open_index(corpus) as opened:
                await pending.replace_all(
                    opened.connection, ["a.md"], noticed_at="2026-01-01T00:00:00+00:00"
                )
                await opened.connection.commit()
            (result,) = await _search(corpus, "protobuf")
            assert result.stale is True


class TestACorpusWithNothingInIt:
    async def test_a_corpus_of_nothing_indexable_returns_no_results(self, tmp_path: Path) -> None:
        """Every path below here is written for a pool with something in it; this is the one where
        there is nothing to fetch rows for, nothing to score, and nothing to look up on disk."""
        async with _corpus(tmp_path, {"logo.png": b"\x89PNG\x00\x01"}) as corpus:
            await build_index(corpus)
            assert await _search(corpus, "anything") == ()


class TestWhenTheIndexDisagreesWithItself:
    """Neither of these can happen through a build — chunks, postings and vectors move in one
    transaction — so both are planted. They are here because the failure they guard against is
    silent: a fabricated score and a fragment with no text behind it both read as ordinary
    results."""

    async def test_a_posting_whose_chunk_row_is_gone_is_left_out(self, tmp_path: Path) -> None:
        async with _corpus(
            tmp_path, {"a.md": b"protobuf here\n", "b.md": b"protobuf there\n"}
        ) as corpus:
            await build_index(corpus)
            async with open_index(corpus) as opened:
                await opened.connection.execute("DELETE FROM chunks WHERE path = 'a.md'")
                await opened.connection.commit()
            results = await _search(corpus, "protobuf")
            assert [result.path for result in results] == ["b.md"]

    async def test_a_chunk_whose_vector_is_gone_is_left_out(self, tmp_path: Path) -> None:
        async with _corpus(
            tmp_path, {"a.md": b"protobuf here\n", "b.md": b"protobuf there\n"}
        ) as corpus:
            await build_index(corpus)
            async with open_index(corpus) as opened:
                await opened.connection.execute(
                    "DELETE FROM chunks_vec WHERE chunk_id IN "
                    "(SELECT id FROM chunks WHERE path = 'a.md')"
                )
                await opened.connection.commit()
            results = await _search(corpus, "protobuf")
            assert [result.path for result in results] == ["b.md"]


class TestAResultsPathIsSafeToJoin:
    """A result's `path` is relative to the corpus root and holds no parent segment, so a caller
    joining it onto that root cannot be sent outside the corpus by anything the index contains."""

    async def test_no_result_path_is_absolute_or_climbs_out_of_the_corpus(
        self, tmp_path: Path
    ) -> None:
        layout = {
            "a.md": b"protobuf at the top\n",
            "nested/b.md": b"protobuf one level down\n",
            "nested/deeper/c.md": b"protobuf two levels down\n",
        }
        async with _corpus(tmp_path, layout) as corpus:
            await build_index(corpus)
            results = await _search(corpus, "protobuf")
            assert len(results) == len(layout)
            for result in results:
                assert not Path(result.path).is_absolute()
                assert ".." not in Path(result.path).parts
                assert (corpus.root / result.path).is_file()


class TestDeterminism:
    async def test_one_query_twice_returns_the_identical_list(self, tmp_path: Path) -> None:
        layout = {f"f{index}.md": b"protobuf step\n" for index in range(6)}
        async with _corpus(tmp_path, layout) as corpus:
            await build_index(corpus)
            first = await _search(corpus, "protobuf step")
            second = await _search(corpus, "protobuf step")
            assert first == second
