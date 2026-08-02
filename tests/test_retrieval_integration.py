"""Retrieval against the real artifact: `fastembed`'s `bge-small-en-v1.5` and real `sqlite-vec`.

The unit tier proves the *rules* — the term constructor, the budget arithmetic, the fusion order —
against a tokenizer whose counts a test can compute by hand. This tier proves the two things that
cannot be faked.

**That the query-side budget is measured against the numbers the deployed model actually uses.** The
write side already has this guard; the read side needs its own, because the failure it prevents is
the same one and it is silent: `retrieval.md` permits truncation here and forbids it being
unrecorded, so a preflight counting through the model's *own* saturating tokenizer would report
every long prompt as sitting exactly at the cap and set `query_truncated` never.

**That both arms retrieve a real memory from real prose.** Everything in the unit tier is a claim
about ranks and events; this is the only tier where the question is whether the pipeline finds
anything at all.
"""

import struct
from pathlib import Path
from typing import Final

import pytest

from zikaron.core.config.resolution import EffectiveConfig, resolve
from zikaron.core.indexing import writes
from zikaron.core.indexing.encoder import FastEmbedEncoder
from zikaron.core.indexing.writes import IndexedCall, IndexingContext
from zikaron.core.records.memory import CallParams, Rewrite
from zikaron.core.retrieval import block, query, reads
from zikaron.core.retrieval.reads import ReadCall
from zikaron.core.retrieval.retrieve import RetrievalSettings
from zikaron.core.store.store import Store

pytestmark = pytest.mark.integration

MODEL: Final = "BAAI/bge-small-en-v1.5"
_MAX_DEPTH: Final = 32

#: The literal D20 keeps as a config default, quoted from the model card. Passed on the query side
#: only, per BGE's asymmetric convention.
_PREFIX: Final = "Represent this sentence for searching relevant passages: "

#: Comfortably past the 512-token cap under any tokenization, so a counter that saturated at the cap
#: would be caught rather than merely suspected.
_LONG_PROMPT: Final = ("alpha beta gamma delta " * 400).strip()

_MEMORIES: Final = (
    (
        "integration tests flake on CI unless PGHOST is set",
        "The suite assumes a local postgres. On CI the host differs, so PGHOST must be exported "
        "before pytest runs or every database test fails with a connection refused.",
    ),
    (
        "make proto exits 0 but emits nothing when protoc is older than 3.21",
        "The generator silently produces no files on older protoc. Check the version first; the "
        "exit status is not evidence that codegen happened.",
    ),
    (
        "the release build needs Java 17, not 21",
        "Gradle's toolchain resolution picks the newest installed JDK and the shadow plugin then "
        "fails on a class file version it cannot read.",
    ),
)


@pytest.fixture(scope="module")
def encoder() -> FastEmbedEncoder:
    """One loaded model for the whole module: the load is the expensive part, not the inference."""
    return FastEmbedEncoder.load(MODEL)


def _config(tmp_path: Path) -> EffectiveConfig:
    return resolve(tmp_path / "system.toml", tmp_path / "project.toml")


def _ctx() -> CallParams:
    return CallParams(session_id="s1", client_kind="mcp", op_id="op1", max_depth=_MAX_DEPTH)


def _read_call(effective: EffectiveConfig, encoder: FastEmbedEncoder) -> ReadCall:
    return ReadCall(ctx=_ctx(), settings=RetrievalSettings.from_config(effective), encoder=encoder)


async def _store_with_memories(tmp_path: Path, encoder: FastEmbedEncoder) -> Store:
    effective = _config(tmp_path)
    store = await Store.create(tmp_path / ".zikaron", effective, encoder)
    index = IndexingContext.for_store(store, effective, encoder)
    for gist, content in _MEMORIES:
        await writes.remember(
            store.connection,
            rewrite=Rewrite(gist=gist, content=content),
            call=IndexedCall(ctx=_ctx(), index=index),
        )
    return store


def test_the_query_budget_is_computed_from_the_deployed_artifacts_own_numbers(
    encoder: FastEmbedEncoder,
) -> None:
    """The prefix is charged against the model's real cap, so a real store's real budget is what a
    long prompt is measured against — not a constant transcribed from a model card."""
    external = query.external_query(_LONG_PROMPT, encoder=encoder, prefix=_PREFIX, max_terms=64)
    budget = encoder.max_sequence_tokens - encoder.n_special_tokens - encoder.count_tokens(_PREFIX)
    assert external.query_truncated
    assert external.query_tokens == encoder.count_tokens(_LONG_PROMPT)
    assert external.query_tokens > budget
    assert encoder.count_tokens(_PREFIX + _LONG_PROMPT[: len(_LONG_PROMPT)]) > budget


def test_the_truncated_query_actually_fits_the_model_it_is_sent_to(
    encoder: FastEmbedEncoder,
) -> None:
    """The whole point of the preflight: what reaches the model, prefix and special tokens included,
    is under the cap — so the model has nothing left to truncate silently."""
    budget = encoder.max_sequence_tokens - encoder.n_special_tokens - encoder.count_tokens(_PREFIX)
    kept = query._head(_LONG_PROMPT, tokens=budget, encoder=encoder)
    assembled = encoder.count_tokens(_PREFIX + kept) + encoder.n_special_tokens
    assert assembled <= encoder.max_sequence_tokens


def test_a_prompt_under_the_budget_is_embedded_whole_and_reports_no_truncation(
    encoder: FastEmbedEncoder,
) -> None:
    text = "why do the integration tests fail on CI"
    external = query.external_query(text, encoder=encoder, prefix=_PREFIX, max_terms=64)
    assert not external.query_truncated
    assert external.query_tokens == encoder.count_tokens(text)


def test_the_bge_query_prefix_reaches_the_model(encoder: FastEmbedEncoder) -> None:
    """D20's one convention, checked where it can actually be observed: the vector the dense arm
    will search with is the embedding of *prefix + text*, not of the text alone. It costs 1.19 ms
    and is reversible, and getting it wrong would silently invalidate every figure in
    `retrieval.md`."""
    text = "why do the integration tests fail on CI"
    external = query.external_query(text, encoder=encoder, prefix=_PREFIX, max_terms=64)
    (with_prefix,) = encoder.embed([_PREFIX + text])
    (without,) = encoder.embed([text])
    assert external.prepared.vector == struct.pack(f"<{len(with_prefix)}f", *with_prefix)
    assert external.prepared.vector != struct.pack(f"<{len(without)}f", *without)


async def test_a_paraphrase_retrieves_the_memory_it_paraphrases(
    tmp_path: Path, encoder: FastEmbedEncoder
) -> None:
    """The one question no unit test asks: with a real model and real prose, does the pipeline find
    the right memory? A paraphrase sharing almost no vocabulary with the record is the case
    `retrieval.md` says needs both arms — 0.667 for either arm alone against 0.800 fused."""
    async with await _store_with_memories(tmp_path, encoder) as store:
        printed = await reads.surface(
            store.connection,
            prompt="the database tests keep failing when I run them on the build server",
            call=_read_call(_config(tmp_path), encoder),
            limit=1,
        )
        assert "PGHOST" in printed
        assert printed.startswith(block.HEADER)


async def test_an_exact_error_string_retrieves_its_memory(
    tmp_path: Path, encoder: FastEmbedEncoder
) -> None:
    """The other measured category: on error strings each arm scores 0.967 and the hybrid 1.000. The
    identifier here — `protoc` — is exactly the shape the lexical arm exists to catch."""
    async with await _store_with_memories(tmp_path, encoder) as store:
        hits = await reads.search(
            store.connection,
            text="protoc 3.21",
            call=_read_call(_config(tmp_path), encoder),
            limit=1,
        )
        assert [hit.gist for hit in hits] == [_MEMORIES[1][0]]


async def test_the_whole_read_path_is_deterministic_against_the_real_model(
    tmp_path: Path, encoder: FastEmbedEncoder
) -> None:
    """Determinism through the real embedder as well as the real indexes: the same store and the
    same prompt produce the same block, byte for byte."""
    async with await _store_with_memories(tmp_path, encoder) as store:
        call = _read_call(_config(tmp_path), encoder)
        prompt = "which JDK does the release build want"
        first = await reads.surface(store.connection, prompt=prompt, call=call)
        second = await reads.surface(store.connection, prompt=prompt, call=call)
        assert first == second
        assert "Java 17" in first


async def test_an_internal_query_reuses_a_real_stored_vector_without_embedding_again(
    tmp_path: Path, encoder: FastEmbedEncoder
) -> None:
    """The internal path's whole claim, against the real artifact: the vector already exists, so
    planning costs no inference and is a pure function of the store."""
    async with await _store_with_memories(tmp_path, encoder) as store:
        rows = await store.connection.execute_fetchall("SELECT uuid FROM memory ORDER BY uuid")
        uuid = str(next(iter(rows))[0])

        internal = await query.internal_query(store.connection, memory_uuid=uuid, max_terms=64)

        stored = await store.connection.execute_fetchall(
            "SELECT v.embedding FROM memory_chunk c JOIN memory_vec v ON v.rowid = c.chunk_id "
            "WHERE c.memory_uuid = ? AND c.part_index = 0",
            (uuid,),
        )
        assert internal.vector == bytes(next(iter(stored))[0])
        assert internal.lexical.expression is not None
