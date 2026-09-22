"""Indexing against the real artifact: `fastembed`'s own `bge-small-en-v1.5` and real `sqlite-vec`.

The unit tier proves the packing *rules* with a tokenizer whose counts a test can compute by hand.
This tier proves the thing that cannot be faked: that the numbers the preflight budgets against are
the numbers the deployed model actually uses, and that every sequence it hands to that model fits
under the cap it claims to fit under.

One test here is a premise guard rather than a check on our own code —
`test_fastembeds_own_tokenizer_is_still_the_truncating_one` — and it is deliberate. The whole reason
this package builds a second tokenizer is a measured property of a third-party artifact, so if that
property ever changes, a failing test is exactly how this design note should come up for review.
"""

import struct
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Final

import pytest
from fastembed import TextEmbedding
from tokenizers import Tokenizer

from zikaron.core.config.resolution import EffectiveConfig, resolve
from zikaron.core.indexing import writes
from zikaron.core.indexing.chunking import SEPARATOR_TOKENS, plan_chunks
from zikaron.core.indexing.encoder import FastEmbedEncoder
from zikaron.core.indexing.writes import IndexedCall, IndexingContext
from zikaron.core.records.memory import CallParams, Rewrite
from zikaron.core.store.store import Store

pytestmark = pytest.mark.integration

MODEL: Final = "BAAI/bge-small-en-v1.5"
_GIST: Final = "protobuf codegen fails silently on the staging cluster"
_MAX_DEPTH: Final = 32

#: Comfortably past the 512-token cap under any tokenization, so a counter that saturated at the
#: cap would be caught rather than merely suspected.
_LONG_PARAGRAPH: Final = ("alpha beta gamma delta " * 400).strip()


@pytest.fixture(scope="module")
def encoder() -> FastEmbedEncoder:
    """One loaded model for the whole module: the load is the expensive part, not the inference."""
    return FastEmbedEncoder.load(MODEL)


def _config(tmp_path: Path) -> EffectiveConfig:
    return resolve(tmp_path / "system.toml", tmp_path / "project.toml")


def _ctx() -> CallParams:
    return CallParams(session_id="s1", client_kind="mcp", op_id="op1", max_depth=_MAX_DEPTH)


@asynccontextmanager
async def _open(
    tmp_path: Path, encoder: FastEmbedEncoder
) -> AsyncIterator[tuple[Store, IndexedCall]]:
    """A store and the call that writes into it, closed however the test ends.

    A context manager rather than a plain factory because the pair cannot be bound by a single
    `async with ... as`, and the store still has to be closed on the failure path: its connection
    runs on a non-daemon thread, so a leak hangs the session at interpreter exit rather than
    reporting.
    """
    async with await Store.create(tmp_path / ".zikaron", _config(tmp_path), encoder) as store:
        index = IndexingContext.for_store(store, _config(tmp_path), encoder)
        yield store, IndexedCall(ctx=_ctx(), index=index)


# ---------------------------------------------------------------------------
# What the artifact reports, and what it must not be asked
# ---------------------------------------------------------------------------


def test_every_tokenizer_fact_is_measured_from_the_loaded_model(
    encoder: FastEmbedEncoder,
) -> None:
    assert encoder.model_name == MODEL
    assert encoder.dim == 384
    assert encoder.n_special_tokens == 2, "BGE wraps a sequence in [CLS] and [SEP]"
    assert encoder.max_sequence_tokens == 512


def test_the_counting_tokenizer_does_not_truncate(encoder: FastEmbedEncoder) -> None:
    """The measured finding this package's tokenizer copy exists for.

    A counter that truncated would report exactly `max_sequence_tokens` here, the preflight would
    conclude the paragraph sits at the cap, no hard split would fire, `truncated` would stay false,
    and fastembed would silently drop the tail — every recorded number looking healthy.
    """
    counted = encoder.count_tokens(_LONG_PARAGRAPH)
    assert counted > encoder.max_sequence_tokens
    assert counted > 1000, "a 1600-word paragraph must count in the thousands, not the hundreds"


def test_fastembeds_own_tokenizer_is_still_the_truncating_one(encoder: FastEmbedEncoder) -> None:
    """A premise guard, not a check on our code: the hazard above is a property of the artifact.

    If fastembed ever stops configuring truncation, this fails — and the right response is to
    re-read `indexing.md`'s note about it rather than to delete this assertion.
    """
    deployed = getattr(TextEmbedding(model_name=MODEL).model, "tokenizer", None)
    assert isinstance(deployed, Tokenizer), "fastembed no longer exposes its tokenizer"
    assert deployed.truncation is not None, "fastembed no longer truncates; revisit indexing.md"
    assert deployed.truncation["max_length"] == encoder.max_sequence_tokens


def test_token_char_spans_land_on_boundaries_that_slice_the_text_back(
    encoder: FastEmbedEncoder,
) -> None:
    """What makes a hard split land on a token boundary: the offsets index the text as passed."""
    text = "the protobuf codegen step fails on prod-eu, not on staging"
    spans = encoder.token_char_spans(text)
    assert spans, "prose must produce tokens"
    assert all(0 <= start <= end <= len(text) for start, end in spans)
    assert [end for _, end in spans] == sorted(end for _, end in spans)
    sliced = "".join(text[start:end] for start, end in spans)
    assert "".join(sliced.split()) == "".join(text.split()), (
        "the spans must cover every non-whitespace character, or a hard split would drop prose"
    )


def test_a_whitespace_separator_costs_no_tokens_which_is_why_the_budget_charges_for_one(
    encoder: FastEmbedEncoder,
) -> None:
    """`indexing.md`: `separator_tokens` is 1 by contract and measures 0 on this model."""
    assert encoder.count_tokens("\n") == 0
    assert SEPARATOR_TOKENS == 1


# ---------------------------------------------------------------------------
# The preflight against the real tokenizer
# ---------------------------------------------------------------------------


def test_every_assembled_sequence_fits_the_models_cap(encoder: FastEmbedEncoder) -> None:
    """The guarantee the whole package exists for, checked by counting what will be embedded."""
    content = "\n\n".join([_LONG_PARAGRAPH, "a short closing note", _LONG_PARAGRAPH])
    plan = plan_chunks(
        gist=_GIST, content=content, encoder=encoder, chunk_max_tokens=450, gist_max_tokens=64
    )
    assert plan.n_chunks > 1
    for text in plan.embedded_texts(_GIST):
        assert encoder.count_tokens(text) + encoder.n_special_tokens <= 512


def test_an_oversized_paragraph_trips_the_truncated_canary(encoder: FastEmbedEncoder) -> None:
    plan = plan_chunks(
        gist=_GIST,
        content=_LONG_PARAGRAPH,
        encoder=encoder,
        chunk_max_tokens=450,
        gist_max_tokens=64,
    )
    assert plan.truncated is True
    assert all(chunk.truncated for chunk in plan.chunks)
    assert all(chunk.token_count <= plan.effective_budget for chunk in plan.chunks)


def test_a_real_short_memory_is_one_chunk_and_the_canary_stays_down(
    encoder: FastEmbedEncoder,
) -> None:
    plan = plan_chunks(
        gist=_GIST,
        content="the proto compiler version drifts from the one pinned in requirements.txt",
        encoder=encoder,
        chunk_max_tokens=450,
        gist_max_tokens=64,
    )
    assert plan.n_chunks == 1
    assert plan.truncated is False


def test_chunk_boundaries_are_deterministic_across_runs(encoder: FastEmbedEncoder) -> None:
    content = "\n\n".join([_LONG_PARAGRAPH, "closing note", "another paragraph entirely"])
    first = plan_chunks(
        gist=_GIST, content=content, encoder=encoder, chunk_max_tokens=120, gist_max_tokens=64
    )
    second = plan_chunks(
        gist=_GIST, content=content, encoder=encoder, chunk_max_tokens=120, gist_max_tokens=64
    )
    assert first == second


# ---------------------------------------------------------------------------
# End to end, with real vectors in a real vec0 table
# ---------------------------------------------------------------------------


async def test_a_real_write_stores_unit_vectors_that_a_knn_query_finds(
    tmp_path: Path, encoder: FastEmbedEncoder
) -> None:
    """One KNN probe, as a check on the *write*: invariant 1's join is the only thing tying a
    vector to its memory, so a write that produced an unqueryable index would look healthy in every
    other assertion here. The read path itself has its own tests."""
    async with _open(tmp_path, encoder) as (store, call):
        content = "\n\n".join([_LONG_PARAGRAPH, "run make clean first or the stale objects link"])
        written = await writes.remember(
            store.connection, rewrite=Rewrite(gist=_GIST, content=content), call=call
        )
        rows = await store.connection.execute_fetchall(
            "SELECT c.part_index, v.embedding FROM memory_chunk c "
            "JOIN memory_vec v ON v.rowid = c.chunk_id WHERE c.memory_uuid = ? "
            "ORDER BY c.part_index",
            (written.memory.uuid,),
        )
        stored = [tuple(row) for row in rows]
        assert len(stored) == written.plan.n_chunks > 1
        for _part_index, blob in stored:
            values = struct.unpack("<384f", bytes(blob))
            assert sum(value * value for value in values) == pytest.approx(1.0, abs=1e-5)

        (query,) = encoder.embed(["why does make fail with stale objects"])
        probe = struct.pack("<384f", *query)
        hits = await store.connection.execute_fetchall(
            "SELECT c.memory_uuid, v.distance FROM memory_vec v "
            "JOIN memory_chunk c ON c.chunk_id = v.rowid "
            "WHERE v.embedding MATCH ? AND k = 3 ORDER BY v.distance",
            (probe,),
        )
        found = [str(row[0]) for row in hits]
        assert written.memory.uuid in found


async def test_a_real_amend_replaces_the_index_and_leaves_no_stale_term(
    tmp_path: Path, encoder: FastEmbedEncoder
) -> None:
    async with _open(tmp_path, encoder) as (store, call):
        written = await writes.remember(
            store.connection,
            rewrite=Rewrite(gist=_GIST, content="the protobuf step fails on staging only"),
            call=call,
        )
        await writes.amend(
            store.connection,
            uuid=written.memory.uuid,
            version=1,
            rewrite=Rewrite(gist="protobuf codegen fails on prod-eu", content="pin the compiler"),
            call=call,
        )
        stale = await store.connection.execute_fetchall(
            "SELECT COUNT(*) FROM memory_fts WHERE memory_fts MATCH '\"staging\"'"
        )
        assert int(next(iter(stale))[0]) == 0
        fresh = await store.connection.execute_fetchall(
            "SELECT COUNT(*) FROM memory_fts WHERE memory_fts MATCH '\"prod-eu\"'"
        )
        assert int(next(iter(fresh))[0]) == 1
        chunk_count = await store.connection.execute_fetchall(
            "SELECT COUNT(*) FROM memory_chunk WHERE memory_uuid = ?", (written.memory.uuid,)
        )
        vec_count = await store.connection.execute_fetchall("SELECT COUNT(*) FROM memory_vec")
        assert int(next(iter(chunk_count))[0]) == int(next(iter(vec_count))[0]) == 1


async def test_a_real_store_writes_identical_bytes_for_identical_prose(
    tmp_path: Path, encoder: FastEmbedEncoder
) -> None:
    """Byte-identical output for one input, through the real model — what makes a reindex or a
    cross-machine comparison meaningful rather than approximately meaningful."""
    blobs: list[list[bytes]] = []
    for name in ("first", "second"):
        root = tmp_path / name
        root.mkdir()
        async with _open(root, encoder) as (store, call):
            await writes.remember(
                store.connection,
                rewrite=Rewrite(gist=_GIST, content="pin the proto compiler to 3.21.12"),
                call=call,
            )
            rows = await store.connection.execute_fetchall(
                "SELECT embedding FROM memory_vec ORDER BY rowid"
            )
            blobs.append([bytes(row[0]) for row in rows])
    assert blobs[0] == blobs[1]
