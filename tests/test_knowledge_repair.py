"""Rebuilding a corpus at a new embedding width, and reindexing one whose files never moved.

Two ways a build reindexes a file the comparison would have cleared, tested together because they
compose and are easy to conflate. **A full build** is asked for: change detection is bypassed and
nothing else differs. **A rebuild** is forced: the encoder in hand is not the one that made the
stored vectors, so the derived tables are dropped and made again at the new width, which leaves
every file changed without anybody declaring it so.

The interesting property is what an *interrupted* rebuild leaves, since there is no checkpoint. The
drop records the model it is rebuilding to, so after a kill `meta` names the model the dead run was
writing, and what happens next turns on what configuration says. **Seen through** — configuration
still naming the new model — nothing compared disagrees, and what reports the corpus as unbuilt is
the completion instant the drop withdrew along with the rows it vouched for; the next scan resumes,
keeping rows that model made. **Reverted**, the abandoned identity is an ordinary encoder mismatch,
and the next scan drops and redoes the corpus whole. A width the recorded identity does not name is
neither of these: nothing here can produce it, and it is read so that a database assembled from two
builds elsewhere is declared back rather than dying on its first insert.
"""

import dataclasses
from collections.abc import Sequence
from pathlib import Path
from typing import Final
from uuid import uuid4

import aiosqlite
import pytest

from tests.fake_encoder import FakeEncoder
from tests.knowledge_fixtures import (
    Corpus,
    add_request,
    build_index,
    build_settings,
    config_for,
    open_corpus,
    open_index,
    write_config,
    write_tree,
)
from zikaron.core.config.keys import CONFIG_KEYS_BY_NAME, IntBounds
from zikaron.core.errors import ZikaronError
from zikaron.core.knowledge import (
    database,
    ddl,
    disposal,
    files,
    groups,
    lock,
    meta,
    pending,
    registry,
    repair,
    reporting,
    scan,
)
from zikaron.core.knowledge.database import KnowledgeDatabase
from zikaron.core.knowledge.meta import GitMode, KnowledgeMeta
from zikaron.core.knowledge.state import KnowledgeState
from zikaron.core.store.transactions import in_one_transaction, propagate

#: A width no corpus here is created at, so a rebuild to it is visible in the stored blobs and in
#: the vector table's own declaration rather than only in `meta`.
_OTHER_DIM: Final = 16

#: A second model at the *default* width, which is the shape that leaves no physical trace: the
#: shipped `bge-small-en-v1.5` and `all-MiniLM-L6-v2` are both 384, so swapping one for the other
#: changes nothing a table declaration or a stored blob could show.
_SAME_WIDTH_MODEL: Final = "another-model-of-the-same-width"

_FLOAT32_BYTES: Final = 4

_NOTICED_AT: Final = "2026-01-01T00:00:00+00:00"

_LAYOUT: Final[dict[str, bytes]] = {
    "a.md": b"alpha prose\n",
    "b.md": b"beta prose\n",
    "nested/c.md": b"gamma prose\n",
}


def _chunk_budget_range() -> tuple[int, int]:
    """The declared ends of `chunk_max_tokens`, read from the schema rather than restated here.

    A test that turns on the budget changing needs two values the resolver accepts, and writing
    them out would let a narrowed range turn this into a configuration error wearing the costume of
    a chunking failure.
    """
    bounds = CONFIG_KEYS_BY_NAME["chunk_max_tokens"].bounds
    if not isinstance(bounds, IntBounds) or bounds.maximum is None:
        raise TypeError("chunk_max_tokens is expected to declare both ends of an integer range")
    return bounds.minimum, bounds.maximum


_SMALLEST_TOKENS, _LARGEST_TOKENS = _chunk_budget_range()
_SMALLEST_BUDGET: Final = f"[indexing]\nchunk_max_tokens = {_SMALLEST_TOKENS}\n"
_LARGEST_BUDGET: Final = str(_LARGEST_TOKENS)

#: Long enough that the smallest budget cuts it into several chunks and the largest into one, with
#: the deterministic encoder counting one token per whitespace-delimited run.
_LONG_FILE: Final[dict[str, bytes]] = {"long.md": b"one two three four five six\n" * 60}


def _identity(*, model: str = "BAAI/bge-small-en-v1.5", dim: int = 384) -> KnowledgeMeta:
    """A corpus's recorded identity, for the tests that need no database to decide a question."""
    return KnowledgeMeta(
        schema_version=1,
        id=uuid4(),
        name_breadcrumb="docs",
        root_path="/corpora/docs",
        include_globs=(),
        exclude_globs=(),
        git_mode=GitMode.OFF,
        embed_model=model,
        embed_dim=dim,
        chunk_max_tokens=450,
        rrf_k=60,
        fusion_depth=50,
        max_file_bytes=1_048_576,
    )


async def _chunk_rows(db: aiosqlite.Connection) -> list[tuple[str, int]]:
    rows = await db.execute_fetchall(
        "SELECT path, part_index FROM chunks ORDER BY path, part_index"
    )
    return [(str(path), int(part)) for path, part in rows]


async def _vector_widths(db: aiosqlite.Connection) -> set[int]:
    rows = await db.execute_fetchall("SELECT embedding FROM chunks_vec")
    return {len(bytes(blob)) // _FLOAT32_BYTES for (blob,) in rows}


async def _indexed_at(db: aiosqlite.Connection) -> dict[str, str]:
    return {path: row.indexed_at for path, row in (await files.load_all(db)).items()}


async def _reported_state(corpus: Corpus) -> KnowledgeState:
    """The state `status` reports for this corpus, through the path a caller actually reaches."""
    listing = await reporting.status(corpus.store_dir, corpus.db, corpus.config, name=corpus.name)
    (report,) = listing.knowledge_bases
    return report.summary.state


async def _served_results(corpus: Corpus) -> list[object]:
    """What a search over this one corpus actually returns, through the path an agent reaches.

    The state is what `status` reports; this is what the state *does*, and the two are worth
    asserting apart — a corpus reported as unusable that is nonetheless searched would answer
    emptiness as though it were an answer.
    """
    response = await groups.search_all(
        corpus.store_dir,
        corpus.db,
        corpus.config,
        groups.SearchRequest(text="alpha prose", limit_per_kb=5),
        encoder=FakeEncoder(),
    )
    (group,) = response.groups
    assert isinstance(group, groups.Group)
    return list(group.results)


async def _write_meta(corpus: Corpus, rows: dict[str, str]) -> None:
    """Change one corpus's stored `meta`, the way a reconfiguration would.

    Written into the knowledge base's own database rather than into configuration, because that is
    where a built corpus reads these from: configuration seeds them at creation and is not
    consulted again.
    """
    registered = await registry.require(corpus.db, corpus.name)
    async with await KnowledgeDatabase.open(corpus.store_dir, registered.id) as opened:

        async def _work(connection: aiosqlite.Connection) -> None:
            await database.write_meta(connection, rows)

        await in_one_transaction(opened.connection, _work, failure=propagate)


class TestTheStatementsARebuildIssues:
    """The rebuild creates its tables from the same statements a fresh knowledge base is built
    from. One definition for both paths is what stops a rebuilt table drifting from a created one,
    which is a difference nobody would see except by comparing two databases."""

    def test_every_derived_table_is_dropped_and_created_again(self) -> None:
        statements = ddl.rebuild_derived_statements(_OTHER_DIM)
        dropped = [one for one in statements if one.startswith("DROP TABLE")]
        assert dropped == ["DROP TABLE chunks_fts", "DROP TABLE chunks_vec", "DROP TABLE chunks"]

    def test_the_creates_are_the_ones_a_fresh_knowledge_base_uses(self) -> None:
        statements = ddl.rebuild_derived_statements(_OTHER_DIM)
        assert statements[3:] == (*ddl.DERIVED_STATEMENTS, ddl.chunks_vec_statement(_OTHER_DIM))
        assert all(one in ddl.FIXED_STATEMENTS for one in ddl.DERIVED_STATEMENTS)

    def test_the_full_text_table_is_dropped_before_the_table_it_indexes(self) -> None:
        """It is external-content over `chunks`, so it is the one statement here with an opinion
        about another table still existing."""
        statements = list(ddl.rebuild_derived_statements(_OTHER_DIM))
        assert statements.index("DROP TABLE chunks_fts") < statements.index("DROP TABLE chunks")

    def test_nothing_drops_the_chunk_index_because_dropping_its_table_takes_it(self) -> None:
        """It is created again with the rest — what no statement does is drop it, because SQLite
        has already removed it with the table it indexes."""
        statements = ddl.rebuild_derived_statements(_OTHER_DIM)
        assert not any(one.startswith("DROP INDEX") for one in statements)
        assert any("CREATE INDEX chunks_path" in one for one in statements)


class TestWhenARebuildIsDue:
    """Two disagreements ask for the same work: the encoder in hand against the recorded identity,
    and the stored table's width against that same identity. The first is what every ordinary
    rebuild answers to, including the one a reverted configuration asks for. The second is a
    backstop — the drop writes the declaration and the identity in one transaction, so nothing here
    separates them, and a database whose `meta` and tables came from different builds is what it
    exists to declare back."""

    def test_an_agreeing_encoder_over_a_matching_table_asks_for_nothing(self) -> None:
        corpus = _identity()
        encoder = FakeEncoder(model_name=corpus.embed_model, dim=corpus.embed_dim)
        assert repair.rebuilt_identity(corpus, encoder, stored_width=corpus.embed_dim) is None

    def test_a_different_model_at_the_same_width_still_asks_for_a_rebuild(self) -> None:
        """The width is checkable against the stored table and the model is not, so a model that
        changed under an index is exactly the divergence nothing later could detect."""
        corpus = _identity()
        rebuilt = repair.rebuilt_identity(
            corpus,
            FakeEncoder(model_name="other", dim=corpus.embed_dim),
            stored_width=corpus.embed_dim,
        )
        assert rebuilt is not None
        assert (rebuilt.embed_model, rebuilt.embed_dim) == ("other", corpus.embed_dim)

    def test_a_different_width_asks_for_a_rebuild(self) -> None:
        corpus = _identity()
        rebuilt = repair.rebuilt_identity(
            corpus,
            FakeEncoder(model_name=corpus.embed_model, dim=_OTHER_DIM),
            stored_width=corpus.embed_dim,
        )
        assert rebuilt is not None
        assert rebuilt.embed_dim == _OTHER_DIM

    def test_a_table_left_at_another_width_asks_for_one_even_with_nothing_else_wrong(self) -> None:
        """The tamper case, which is the only way this state is reached: a database whose `meta` and
        tables came from different builds — restored from a backup, or edited by hand. The encoder
        agrees with `meta`, and the table is the only thing that does not."""
        corpus = _identity()
        rebuilt = repair.rebuilt_identity(
            corpus,
            FakeEncoder(model_name=corpus.embed_model, dim=corpus.embed_dim),
            stored_width=_OTHER_DIM,
        )
        assert rebuilt == corpus, "the rebuild is back to the identity the corpus still claims"

    def test_when_both_disagree_the_rebuild_is_at_the_width_the_encoder_emits(self) -> None:
        """The branch order is load-bearing rather than incidental. The table has to be declared at
        the width the encoder about to fill it produces; declared at the recorded one instead, the
        rebuild would finish the drop and then die on its first insert."""
        corpus = _identity()
        rebuilt = repair.rebuilt_identity(
            corpus,
            FakeEncoder(model_name="other", dim=_OTHER_DIM),
            stored_width=_OTHER_DIM + 1,
        )
        assert rebuilt is not None
        assert rebuilt.embed_dim == _OTHER_DIM, "the encoder's width wins over the recorded one"

    def test_nothing_but_the_identity_moves(self) -> None:
        """A rebuild changes which model filled the corpus, not what the corpus is."""
        corpus = _identity()
        rebuilt = repair.rebuilt_identity(
            corpus,
            FakeEncoder(model_name="other", dim=_OTHER_DIM),
            stored_width=corpus.embed_dim,
        )
        assert rebuilt is not None
        assert (
            dataclasses.replace(rebuilt, embed_model=corpus.embed_model, embed_dim=corpus.embed_dim)
            == corpus
        )

    def test_the_rows_the_drop_records_are_the_two_identity_keys(self) -> None:
        rebuilt = _identity(model="other", dim=_OTHER_DIM)
        assert repair.identity_rows(rebuilt) == {
            meta.EMBED_MODEL_KEY: "other",
            meta.EMBED_DIM_KEY: str(_OTHER_DIM),
        }


class TestDroppingWhatABuildDerived:
    async def test_the_vector_table_comes_back_at_the_new_width(self, tmp_path: Path) -> None:
        root = write_tree(tmp_path / "corpus", _LAYOUT)
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await build_index(corpus)
            async with open_index(corpus) as opened:
                await repair.drop_derived(
                    opened.connection, identity=_identity(model="other", dim=_OTHER_DIM)
                )
                await opened.connection.execute(
                    "INSERT INTO chunks_vec (chunk_id, embedding) VALUES (?, ?)",
                    (1, bytes(_OTHER_DIM * _FLOAT32_BYTES)),
                )
                assert await _vector_widths(opened.connection) == {_OTHER_DIM}

    async def test_the_files_rows_go_with_the_chunks_they_account_for(self, tmp_path: Path) -> None:
        """A row claiming a hash and a chunk count for content that is no longer stored would clear
        the very file the rebuild has to read again."""
        root = write_tree(tmp_path / "corpus", _LAYOUT)
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await build_index(corpus)
            async with open_index(corpus) as opened:
                assert await files.load_all(opened.connection) != {}
                await repair.drop_derived(
                    opened.connection, identity=_identity(model="other", dim=_OTHER_DIM)
                )
                assert await files.load_all(opened.connection) == {}
                assert await _chunk_rows(opened.connection) == []

    async def test_the_identity_is_recorded_as_the_tables_are_emptied(self, tmp_path: Path) -> None:
        """`meta` names the model whose vectors are in the table, so the statement that empties the
        table has to be the statement that renames it — otherwise there is a window, as long as a
        build, in which the rows being committed are labelled by a model that did not make them."""
        root = write_tree(tmp_path / "corpus", _LAYOUT)
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await build_index(corpus)
            async with open_index(corpus) as opened:
                await repair.drop_derived(
                    opened.connection, identity=_identity(model="other", dim=_OTHER_DIM)
                )
                raw = await database.read_meta(opened.connection)
            assert raw[meta.EMBED_MODEL_KEY] == "other"
            assert int(raw[meta.EMBED_DIM_KEY]) == _OTHER_DIM
            assert meta.LAST_SCAN_COMPLETED_AT_KEY not in raw, "and the instant went with the rows"

    async def test_the_pending_list_is_left_exactly_as_it_was(self, tmp_path: Path) -> None:
        """`pending` names what a walk found changed, and the next walk replaces it wholesale.
        Emptying it here would delete a staleness signal on an occasion nothing accounts for."""
        root = write_tree(tmp_path / "corpus", _LAYOUT)
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await build_index(corpus)
            async with open_index(corpus) as opened:

                async def _plant(connection: aiosqlite.Connection) -> None:
                    await pending.replace_all(connection, ["a.md"], noticed_at=_NOTICED_AT)

                await in_one_transaction(opened.connection, _plant, failure=propagate)
                await repair.drop_derived(
                    opened.connection, identity=_identity(model="other", dim=_OTHER_DIM)
                )
                assert await pending.paths(opened.connection) == ["a.md"]

    async def test_a_failure_part_way_through_leaves_the_old_index_whole(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The whole reason the rebuild is one explicit transaction. A `DROP TABLE` issued with no
        transaction open runs in autocommit, and a later rollback would not restore it — which
        would turn one failed rebuild into a corpus with no chunks and no way back."""
        root = write_tree(tmp_path / "corpus", _LAYOUT)
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await build_index(corpus)
            async with open_index(corpus) as opened:
                before = await _chunk_rows(opened.connection)
                widths = await _vector_widths(opened.connection)

                real = ddl.rebuild_derived_statements

                def _with_a_failing_tail(embed_dim: int) -> Sequence[str]:
                    return (*real(embed_dim), "SELECT no_such_column")

                monkeypatch.setattr(ddl, "rebuild_derived_statements", _with_a_failing_tail)
                with pytest.raises(aiosqlite.Error):
                    await repair.drop_derived(opened.connection, identity=_identity(dim=_OTHER_DIM))

                assert await _chunk_rows(opened.connection) == before
                assert await _vector_widths(opened.connection) == widths
                assert await files.load_all(opened.connection) != {}
                assert opened.meta.embed_dim != _OTHER_DIM, "the identity did not move either"

    async def test_a_failure_after_the_tables_rolls_back_the_meta_rows_with_them(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The other end of the same transaction, and the end the statement list cannot reach.

        The test above fails while issuing DDL, so the `meta` writes never run and would be intact
        whether or not a transaction held them. Failing *after* `files.forget_all` is what puts the
        identity write and the cleared completion instant inside the window under test: neither may
        survive a rebuild that did not happen.
        """
        root = write_tree(tmp_path / "corpus", _LAYOUT)
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await build_index(corpus)
            async with open_index(corpus) as opened:
                before = await _chunk_rows(opened.connection)
                recorded = (opened.meta.embed_model, opened.meta.embed_dim)

                async def _fail(_: aiosqlite.Connection) -> None:
                    raise RuntimeError("the indexer died mid-drop")

                monkeypatch.setattr(files, "forget_all", _fail)
                with pytest.raises(RuntimeError, match="mid-drop"):
                    await repair.drop_derived(
                        opened.connection, identity=_identity(model="other", dim=_OTHER_DIM)
                    )

                assert await _chunk_rows(opened.connection) == before
                raw = await database.read_meta(opened.connection)
                assert (raw[meta.EMBED_MODEL_KEY], int(raw[meta.EMBED_DIM_KEY])) == recorded
                assert meta.LAST_SCAN_COMPLETED_AT_KEY in raw, "the instant survived with the rows"


class TestARebuildEndToEnd:
    async def test_a_new_model_rebuilds_the_corpus_and_records_what_filled_it(
        self, tmp_path: Path
    ) -> None:
        root = write_tree(tmp_path / "corpus", _LAYOUT)
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await build_index(corpus)
            async with open_index(corpus) as opened:
                before = await _chunk_rows(opened.connection)

            refreshed = await build_index(
                corpus, encoder=FakeEncoder(model_name="other", dim=_OTHER_DIM)
            )

            assert refreshed.result.rebuilt_identity is not None
            assert refreshed.result.rebuilt_identity.embed_model == "other"
            async with open_index(corpus) as opened:
                assert (opened.meta.embed_model, opened.meta.embed_dim) == ("other", _OTHER_DIM)
                assert await _chunk_rows(opened.connection) == before
                assert await _vector_widths(opened.connection) == {_OTHER_DIM}

    async def test_an_ordinary_build_reports_no_rebuild(self, tmp_path: Path) -> None:
        root = write_tree(tmp_path / "corpus", _LAYOUT)
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            refreshed = await build_index(corpus)
            assert refreshed.result.rebuilt_identity is None

    async def test_an_interrupted_rebuild_still_refuses_and_the_next_build_completes_it(
        self, tmp_path: Path
    ) -> None:
        """There is no rebuild checkpoint, and none is needed: the drop left two facts behind, and
        between them the knowledge base goes on refusing and the next build is the repair, however
        it was invoked.

        Configuration is left at the default, so `status` reports what a revert would — the
        withdrawn instant and an encoder mismatch both — while the build that completes it loads the
        **abandoned** model and so takes no drop: it resumes over the emptied tables. State answers
        to configuration and the repair to the encoder in hand (§8.4), and the two disagreeing here
        is why the corpus goes on reporting `reindex_required` after that build completes.
        """
        root = write_tree(tmp_path / "corpus", _LAYOUT)
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await build_index(corpus)
            async with open_index(corpus) as opened:
                recorded = (opened.meta.embed_model, opened.meta.embed_dim)

            with pytest.raises(ZikaronError):
                await build_index(corpus, encoder=_an_unavailable_model())

            async with open_index(corpus) as opened:
                assert (opened.meta.embed_model, opened.meta.embed_dim) != recorded, (
                    "the drop recorded the identity it was rebuilding to"
                )
                assert opened.meta.embed_dim == opened.vector_width, (
                    "the width it declared and the identity naming that width move together"
                )
                assert await _chunk_rows(opened.connection) == []
                assert opened.vector_width == _OTHER_DIM, "the drop widened the table"
                raw = await database.read_meta(opened.connection)
                # The drop withdrew the earlier build's completion instant along with the rows it
                # vouched for, so the corpus reports that nothing a completed build made is stored.
                assert meta.LAST_SCAN_COMPLETED_AT_KEY not in raw
            assert await _reported_state(corpus) is KnowledgeState.REINDEX_REQUIRED

            refreshed = await build_index(
                corpus, encoder=FakeEncoder(model_name="other", dim=_OTHER_DIM)
            )

            assert refreshed.result.rebuilt_identity is None, (
                "the same model resumed; no second drop"
            )
            async with open_index(corpus) as opened:
                assert (opened.meta.embed_model, opened.meta.embed_dim) == ("other", _OTHER_DIM)
                assert await _chunk_rows(opened.connection) != []
            # Built, and still refusing: the corpus is whole under the model that filled it, and
            # that model is not the configured one. Correcting configuration is the exit, not
            # another build.
            assert refreshed.status.summary.state is KnowledgeState.REINDEX_REQUIRED

    async def test_an_interrupted_rebuild_is_repaired_even_if_the_model_is_put_back(
        self, tmp_path: Path
    ) -> None:
        """An operator tries a model, the rebuild is interrupted after it widened the table, and the
        operator reverts. `meta` names the abandoned model, because the drop recorded it, so the
        reverted encoder is an ordinary **encoder mismatch** — the same comparison that started the
        rebuild, now pointing the other way.

        What this asserts is the *repair* rather than the refusal: the build that follows the revert
        has to rebuild, narrowing the table back, and a build that treated this as an ordinary
        indexing job would die inserting a vector of the reverted model's width into a table
        declared for the abandoned one — one rejected insert per file."""
        root = write_tree(tmp_path / "corpus", _LAYOUT)
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await build_index(corpus)
            async with open_index(corpus) as opened:
                recorded = (opened.meta.embed_model, opened.meta.embed_dim)

            with pytest.raises(ZikaronError):
                await build_index(corpus, encoder=_an_unavailable_model())

            # The revert: back to the default encoder, which `meta` no longer names.
            assert await _reported_state(corpus) is KnowledgeState.REINDEX_REQUIRED

            refreshed = await build_index(corpus)

            assert refreshed.result.rebuilt_identity is not None, (
                "the table still had to be rebuilt"
            )
            async with open_index(corpus) as opened:
                assert (opened.meta.embed_model, opened.meta.embed_dim) == recorded
                assert opened.vector_width == recorded[1]
                assert await _chunk_rows(opened.connection) != []
                assert await _vector_widths(opened.connection) == {recorded[1]}
            assert await _reported_state(corpus) is KnowledgeState.OK

    async def test_an_interrupted_rebuild_refuses_where_nothing_compared_disagrees(
        self, tmp_path: Path
    ) -> None:
        """The state in which the completion instant is the only thing refusing, and the one where
        leaving it would be silent.

        Swap a model for another of the same width — `bge-small-en-v1.5` and `all-MiniLM-L6-v2` are
        both 384 — interrupt the rebuild after its drop, and leave the configuration naming the new
        model, as an operator who means to finish the swap would. `meta` names it too, because the
        drop recorded it; the table never changed shape. So the encoder agrees, the width agrees,
        and **nothing compared disagrees** — over an index the drop emptied. Without the withdrawn
        completion instant this corpus would report `ok` and answer every search as *searched, found
        nothing*, for as long as nobody happened to run a build.
        """
        root = write_tree(tmp_path / "corpus", _LAYOUT)
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await build_index(corpus)
            async with open_index(corpus) as opened:
                width = opened.meta.embed_dim

            same_width = FakeEncoder(
                model_name=_SAME_WIDTH_MODEL,
                dim=width,
                embed_error=RuntimeError("the model is unavailable"),
            )
            with pytest.raises(ZikaronError):
                await build_index(corpus, encoder=same_width)

            # Configuration catches up with the swap, which is what leaves nothing to compare.
            write_config(tmp_path, f'[embedding]\nembed_model = "{_SAME_WIDTH_MODEL}"\n')
            settled = dataclasses.replace(corpus, config=config_for(tmp_path))
            async with open_index(settled) as opened:
                assert opened.meta.embed_model == _SAME_WIDTH_MODEL, "recorded by the drop"
                assert opened.vector_width == width == opened.meta.embed_dim
                assert await _chunk_rows(opened.connection) == []

            assert await _reported_state(settled) is KnowledgeState.REINDEX_REQUIRED
            assert await _served_results(settled) == [], "and it is not searched while it says so"

            await build_index(settled, encoder=FakeEncoder(model_name=_SAME_WIDTH_MODEL, dim=width))

            async with open_index(settled) as opened:
                assert await _chunk_rows(opened.connection) != []
            assert await _reported_state(settled) is KnowledgeState.OK

    async def test_a_rebuild_that_committed_files_before_dying_leaves_no_vector_it_does_not_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The case a resume gets wrong unless the drop records what is refilling the corpus.

        A rebuild commits file by file, so one killed part-way has written the *new* model's vectors
        under `files` rows whose hashes say they are current. Had `meta` been left naming the old
        model until the scan completed, reverting to one of the same width would have left nothing
        compared disagreeing — and the scan that followed would have been an ordinary one, clearing
        those files as unchanged and ending `ok` over two models' vectors with nothing able to say
        so.

        Because the drop records what is refilling the corpus, the revert instead makes the
        abandoned identity an ordinary encoder mismatch, so the repair is a redo and every file is
        embedded again. The oracle is which texts the reverted encoder was
        *asked* to embed, not the vectors stored: `FakeEncoder` derives a vector from the text
        alone, so two models produce identical bytes for one chunk and comparing values would pass
        whatever happened.
        """
        root = write_tree(tmp_path / "corpus", _LAYOUT)
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await build_index(corpus)
            async with open_index(corpus) as opened:
                recorded = (opened.meta.embed_model, opened.meta.embed_dim)

            other = FakeEncoder(model_name=_SAME_WIDTH_MODEL, dim=recorded[1])
            real = disposal.dispose

            async def _die_on_the_second(*args: object, **kwargs: object) -> None:
                if _committed:
                    raise RuntimeError("the indexer died")
                _committed.append(True)
                await real(*args, **kwargs)  # type: ignore[arg-type]

            _committed: list[bool] = []
            monkeypatch.setattr(disposal, "dispose", _die_on_the_second)
            with pytest.raises(RuntimeError, match="the indexer died"):
                await build_index(corpus, encoder=other)
            monkeypatch.undo()

            async with open_index(corpus) as opened:
                committed = set(await files.load_all(opened.connection))
                assert len(committed) == 1, "one file was committed by the abandoned model"
                assert (opened.meta.embed_model, opened.meta.embed_dim) == (
                    other.model_name,
                    other.dim,
                ), "the drop recorded what was refilling the corpus"
            assert await _reported_state(corpus) is KnowledgeState.REINDEX_REQUIRED

            # The revert: back to the encoder the corpus was originally built with.
            reverted = FakeEncoder()
            await build_index(corpus, encoder=reverted)

            asked = {text for batch in reverted.embedded for text in batch}
            (stranded,) = committed
            assert any(stranded in text for text in asked), (
                f"{stranded} carried the other model's vectors and was never embedded again"
            )
            async with open_index(corpus) as opened:
                assert (opened.meta.embed_model, opened.meta.embed_dim) == recorded
            assert await _reported_state(corpus) is KnowledgeState.OK

    async def test_a_rebuild_that_was_not_reverted_resumes_rather_than_starting_over(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The other half, and the reason recording the identity at the drop costs nothing: where
        the swap is seen through rather than reverted, the rows the dead rebuild committed were made
        by the model `meta` now names, so the scan that follows keeps them and indexes only what is
        left. Recorded at the scan's far end instead, this scan would have had to redo the corpus
        from nothing to be correct."""
        root = write_tree(tmp_path / "corpus", _LAYOUT)
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await build_index(corpus)

            async with open_index(corpus) as opened:
                width = opened.meta.embed_dim

            def _other() -> FakeEncoder:
                return FakeEncoder(model_name=_SAME_WIDTH_MODEL, dim=width)

            real = disposal.dispose

            async def _die_on_the_second(*args: object, **kwargs: object) -> None:
                if _committed:
                    raise RuntimeError("the indexer died")
                _committed.append(True)
                await real(*args, **kwargs)  # type: ignore[arg-type]

            _committed: list[bool] = []
            monkeypatch.setattr(disposal, "dispose", _die_on_the_second)
            with pytest.raises(RuntimeError, match="the indexer died"):
                await build_index(corpus, encoder=_other())
            monkeypatch.undo()

            async with open_index(corpus) as opened:
                kept = set(await files.load_all(opened.connection))
            assert len(kept) == 1, "one file was committed before the kill"

            # Configuration sees the swap through, so nothing asks for a second drop.
            write_config(tmp_path, f'[embedding]\nembed_model = "{_SAME_WIDTH_MODEL}"\n')
            settled = dataclasses.replace(corpus, config=config_for(tmp_path))
            resuming = _other()
            refreshed = await build_index(settled, encoder=resuming)

            assert refreshed.result.rebuilt_identity is None, "no second drop was owed"
            asked = {text for batch in resuming.embedded for text in batch}
            (committed_path,) = kept
            assert not any(committed_path in text for text in asked), (
                "the file the dead rebuild committed was kept rather than embedded again"
            )
            assert await _reported_state(settled) is KnowledgeState.OK

    async def test_a_build_decides_what_to_rebuild_on_state_it_read_under_its_own_lock(
        self, tmp_path: Path
    ) -> None:
        """Two builds overlap by a directory check and a git subprocess, which is ordinary for two
        spawns inside one model-load window. If the rebuild decision were taken on what the database
        said when it was *opened*, the one that took the lock second would act on a snapshot the
        first had already overtaken — and at equal widths every insert still fits, so it would index
        with its own encoder into a corpus the winner had relabelled, silently.

        The overlap is forced here rather than raced: a handle is opened, a whole build runs to
        completion through another, and only then does the first handle's build begin.
        """
        root = write_tree(tmp_path / "corpus", _LAYOUT)
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await build_index(corpus)
            async with open_index(corpus) as opened:
                first_seen = opened.meta.embed_model

                # The overtaking build, through its own handle, start to finish.
                await build_index(corpus, encoder=FakeEncoder(model_name=_SAME_WIDTH_MODEL))
                (root / "a.md").write_bytes(b"alpha, edited\n")

                await scan.run(opened, build_settings(corpus.config))

            async with open_index(corpus) as reopened:
                assert reopened.meta.embed_model == first_seen, (
                    "the second build rebuilt to its own encoder rather than adding to the other's"
                )
                assert await _vector_widths(reopened.connection) == {reopened.meta.embed_dim}

    async def test_a_table_the_recorded_identity_cannot_fill_is_refused_on_its_own(
        self, tmp_path: Path
    ) -> None:
        """The width is a backstop, and this is the only way to reach it on its own.

        Every route this package has to a table `meta` cannot fill is the rebuild's drop, and the
        drop withdraws the completion instant in the same transaction — so wherever the width
        disagrees the corpus is already saying it holds no completed build, which is why the two
        cases above cannot tell the width check from nothing. What is left for it to catch is a
        `meta` and a table separated by something outside this system: a file restored from a
        backup of another build, or a row edited by hand. Reproduced by redeclaring the table under
        a corpus that completed, since nothing in this package will do that.
        """
        root = write_tree(tmp_path / "corpus", _LAYOUT)
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await build_index(corpus)
            assert await _reported_state(corpus) is KnowledgeState.OK

            async with open_index(corpus) as opened:
                recorded = opened.meta.embed_dim
                await opened.connection.execute("DROP TABLE chunks_vec")
                await opened.connection.execute(ddl.chunks_vec_statement(_OTHER_DIM))
                await opened.connection.commit()
                raw = await database.read_meta(opened.connection)
            assert meta.LAST_SCAN_COMPLETED_AT_KEY in raw, "the completion instant is untouched"

            assert await _reported_state(corpus) is KnowledgeState.REINDEX_REQUIRED
            assert await _served_results(corpus) == [], "and it is not searched while it says so"

            await build_index(corpus)

            async with open_index(corpus) as opened:
                assert opened.vector_width == recorded, "the repair declared it back"
                assert await _vector_widths(opened.connection) == {recorded}
            assert await _reported_state(corpus) is KnowledgeState.OK

    async def test_the_lock_is_given_back_even_when_the_rebuild_fails(self, tmp_path: Path) -> None:
        root = write_tree(tmp_path / "corpus", _LAYOUT)
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await build_index(corpus)
            with pytest.raises(ZikaronError):
                await build_index(corpus, encoder=_an_unavailable_model())
            async with open_index(corpus) as opened:
                raw = await database.read_meta(opened.connection)
            assert not any(key in raw for key in lock.LOCK_KEYS)

    async def test_a_rebuild_starts_from_the_files_the_corpus_has_now(self, tmp_path: Path) -> None:
        """A build that *takes the drop* rebuilds from what the root holds now, so a file deleted
        while the corpus was unbuildable is simply not in the corpus that build leaves behind. (The
        scan following an interrupted rebuild takes no drop and resumes where the swap was seen
        through, and takes this drop where it was reverted — both covered above.)"""
        root = write_tree(tmp_path / "corpus", _LAYOUT)
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await build_index(corpus)
            (root / "b.md").unlink()

            await build_index(corpus, encoder=FakeEncoder(model_name="other", dim=_OTHER_DIM))

            async with open_index(corpus) as opened:
                assert "b.md" not in await files.load_all(opened.connection)


def _an_unavailable_model() -> FakeEncoder:
    """An encoder of a different identity that fails on its first forward pass.

    The drop has already happened by then — it recorded this identity and cleared the completion
    instant, which has not been written again — and that is exactly the window an interrupted
    rebuild leaves behind.
    """
    return FakeEncoder(
        model_name="other",
        dim=_OTHER_DIM,
        embed_error=RuntimeError("the model is unavailable"),
    )


class TestAFullBuild:
    async def test_every_file_is_reindexed_though_none_of_them_changed(
        self, tmp_path: Path
    ) -> None:
        root = write_tree(tmp_path / "corpus", _LAYOUT)
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await build_index(corpus)
            async with open_index(corpus) as opened:
                first = await _indexed_at(opened.connection)

            refreshed = await build_index(corpus, full=True)

            assert refreshed.result.counters.files_indexed == len(_LAYOUT)
            assert refreshed.result.files_deleted == 0
            async with open_index(corpus) as opened:
                second = await _indexed_at(opened.connection)
            assert set(second) == set(first)
            assert all(second[path] >= first[path] for path in first)

    async def test_an_ordinary_build_over_the_same_files_rewrites_nothing(
        self, tmp_path: Path
    ) -> None:
        """The contrast that makes the test above mean something: without the bypass, a second
        build over unchanged files touches no row at all."""
        root = write_tree(tmp_path / "corpus", _LAYOUT)
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await build_index(corpus)
            async with open_index(corpus) as opened:
                first = await _indexed_at(opened.connection)

            await build_index(corpus)

            async with open_index(corpus) as opened:
                assert await _indexed_at(opened.connection) == first

    async def test_a_full_build_is_not_a_discard_and_rebuild(self, tmp_path: Path) -> None:
        """Each file's own transaction replaces its own rows, so the corpus is never empty and the
        recorded identity survives — which is the whole difference from a rebuild."""
        root = write_tree(tmp_path / "corpus", _LAYOUT)
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await build_index(corpus)
            async with open_index(corpus) as opened:
                identity = (opened.meta.embed_model, opened.meta.embed_dim)
                chunks = await _chunk_rows(opened.connection)

            refreshed = await build_index(corpus, full=True)

            assert refreshed.result.rebuilt_identity is None
            async with open_index(corpus) as opened:
                assert (opened.meta.embed_model, opened.meta.embed_dim) == identity
                assert await _chunk_rows(opened.connection) == chunks

    async def test_a_full_build_picks_up_a_changed_chunk_budget(self, tmp_path: Path) -> None:
        """The case the bypass exists for: nothing about the files moved, and the corpus is
        nonetheless out of date because the rule that cut it into chunks did."""
        write_config(tmp_path, _SMALLEST_BUDGET)
        root = write_tree(tmp_path / "corpus", _LONG_FILE)
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await build_index(corpus)
            async with open_index(corpus) as opened:
                many = len(await _chunk_rows(opened.connection))
            assert many > 1

            await _write_meta(corpus, {meta.CHUNK_MAX_TOKENS_KEY: _LARGEST_BUDGET})
            await build_index(corpus, full=True)

            async with open_index(corpus) as opened:
                assert len(await _chunk_rows(opened.connection)) < many

    async def test_a_build_that_is_not_full_leaves_a_changed_budget_unapplied(
        self, tmp_path: Path
    ) -> None:
        """Which is why the bypass has to exist at all: the files are byte-identical, so change
        detection clears every one of them and the old chunking stands."""
        write_config(tmp_path, _SMALLEST_BUDGET)
        root = write_tree(tmp_path / "corpus", _LONG_FILE)
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await build_index(corpus)
            async with open_index(corpus) as opened:
                many = len(await _chunk_rows(opened.connection))

            await _write_meta(corpus, {meta.CHUNK_MAX_TOKENS_KEY: _LARGEST_BUDGET})
            await build_index(corpus)

            async with open_index(corpus) as opened:
                assert len(await _chunk_rows(opened.connection)) == many


class TestReadingAStoredWidthBack:
    """`vec0` reports nothing about its own column — measured: `PRAGMA table_info` gives it an empty
    type — so the recorded `CREATE` is the only place the width can be read from. Reading it is what
    lets a `meta` and a table joined from different builds — restored, or edited by hand — be
    reported and declared back rather than dying on the first insert; nothing this package does
    separates them (§8.4)."""

    def test_the_width_comes_back_out_of_the_statement_that_fixed_it(self) -> None:
        assert ddl.declared_vector_width(ddl.chunks_vec_statement(_OTHER_DIM)) == _OTHER_DIM

    @pytest.mark.parametrize("declaration", ["float[16]", "FLOAT[16]", "float [16]"])
    def test_every_spelling_the_extension_accepts_is_read(self, declaration: str) -> None:
        """`vec0` takes all three — measured — and `sqlite_master` keeps whichever was written. A
        pattern matching only the spelling this module emits would call a working table unreadable,
        and the question being asked is what the table accepts rather than who wrote it."""
        statement = f"CREATE VIRTUAL TABLE chunks_vec USING vec0 (embedding {declaration})"
        assert ddl.declared_vector_width(statement) == 16

    def test_a_declaration_with_no_width_is_fatal_rather_than_defaulted(self) -> None:
        """The statement is one this project wrote, so a declaration without a width means a
        database that is not the one it claims to be. Absorbed into a default it would read as
        agreeing with whatever `meta` said, which is the reading that hides the defect."""
        with pytest.raises(ValueError, match="no vector width"):
            ddl.declared_vector_width("CREATE VIRTUAL TABLE chunks_vec USING vec0 (embedding)")

    async def test_it_is_read_at_open_so_a_corpus_carries_it(self, tmp_path: Path) -> None:
        root = write_tree(tmp_path / "corpus", _LAYOUT)
        async with (
            open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus,
            open_index(corpus) as opened,
        ):
            assert opened.vector_width == opened.meta.embed_dim
