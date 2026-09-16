"""The knowledge index against the real artifact: `fastembed`'s own model, and a real corpus.

The unit tier proves the rules with a tokenizer whose counts a test can compute by hand. This tier
proves the two things that cannot be faked. One is a property of the deployed model rather than of
our code — that a chunk's vector does not depend on what else was in its batch — and it is a
premise guard by design: batching is a throughput decision this package is free to change, and the
day it stops being free is the day this test fails. The other is that the whole path works end to
end when nothing about it is a stand-in.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Final

import pytest

from tests.knowledge_fixtures import (
    Corpus,
    add_request,
    config_for,
    open_corpus,
    open_index,
    write_tree,
)
from zikaron.core.indexing.encoder import FastEmbedEncoder
from zikaron.core.knowledge import disposal, groups, lifecycle, vectors
from zikaron.core.knowledge.chunking import FileChunkPlan, plan_file_chunks
from zikaron.core.knowledge.groups import Group, SearchRequest
from zikaron.core.knowledge.meta import GitMode

pytestmark = pytest.mark.integration

MODEL: Final = "BAAI/bge-small-en-v1.5"

#: Enough chunks to cross the default batch boundary of 32 with room on both sides of it.
_PARAGRAPHS: Final = 40


@pytest.fixture(scope="module")
def encoder() -> FastEmbedEncoder:
    """One loaded model for the whole module: the load is the expensive part, not the inference."""
    return FastEmbedEncoder.load(MODEL)


def _wide_plan(encoder: FastEmbedEncoder) -> FileChunkPlan:
    """A plan with more chunks than the default batch holds, so a batch boundary falls inside it.

    The budget is small enough that each paragraph becomes its own chunk: what this tier is for is
    the model's behaviour across a batch boundary, and a plan that fits in one pass would assert
    agreement between two identical calls.
    """
    text = "".join(
        f"paragraph {index} about the protobuf codegen step and why it fails\n\n"
        for index in range(_PARAGRAPHS)
    )
    plan = plan_file_chunks(path="docs/a.md", text=text, encoder=encoder, chunk_max_tokens=16)
    assert plan.n_chunks > 32
    return plan


async def _embedded(
    plan: FileChunkPlan, *, encoder: FastEmbedEncoder, batch_size: int
) -> tuple[bytes, ...]:
    return await vectors.embed_chunks(
        plan, encoder=encoder, embed_dim=encoder.dim, batch_size=batch_size
    )


async def test_a_chunk_embeds_identically_alone_and_in_a_wide_batch(
    encoder: FastEmbedEncoder,
) -> None:
    """The defect this rules out is one a neighbouring product ships: pooling that ignores the
    attention mask makes a document's embedding depend on the longest text that happened to share
    its batch, and it is suppressed there only because every batch is size one. Enabling batching
    would activate it, silently — every vector still stores, and every search still answers.
    """
    plan = _wide_plan(encoder)
    alone = await _embedded(plan, encoder=encoder, batch_size=1)
    batched = await _embedded(plan, encoder=encoder, batch_size=32)
    assert alone == batched


async def test_the_batch_size_changes_nothing_at_any_width(encoder: FastEmbedEncoder) -> None:
    """Three widths rather than two, because a pooling bug that happened to cancel at one batch
    size would look like agreement."""
    plan = _wide_plan(encoder)
    widths = [await _embedded(plan, encoder=encoder, batch_size=size) for size in (1, 7, 32)]
    assert widths[0] == widths[1] == widths[2]


@asynccontextmanager
async def _built(tmp_path: Path, encoder: FastEmbedEncoder) -> AsyncIterator[Corpus]:
    root = write_tree(
        tmp_path / "corpus",
        {
            "design/retrieval.md": (
                b"# Retrieval\n\nThe dense arm probes the vector index and the lexical arm runs "
                b"BM25.\n\nBoth are fused by reciprocal rank.\n"
            ),
            "runbooks/deploy.md": (
                b"# Deploying\n\nRun `make release` and then wait for the health check.\n"
            ),
        },
    )
    async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
        config = config_for(tmp_path)
        await lifecycle.refresh(
            corpus.store_dir,
            corpus.db,
            config,
            name=corpus.name,
            build=disposal.BuildSettings(
                encoder=encoder, embed_batch=config.get_int("knowledge_embed_batch")
            ),
        )
        yield corpus


async def test_a_real_corpus_answers_a_real_query(
    tmp_path: Path, encoder: FastEmbedEncoder
) -> None:
    """End to end with nothing standing in: the real tokenizer decides the chunk boundaries, the
    real model fills the vector index, and the query goes through the same preflight a tool call
    would."""
    async with _built(tmp_path, encoder) as corpus:
        response = await groups.search_all(
            corpus.store_dir,
            corpus.db,
            config_for(tmp_path),
            SearchRequest(text="how do the two retrieval arms combine", limit_per_kb=5),
            encoder=encoder,
        )
    (group,) = response.groups
    assert isinstance(group, Group)
    assert group.results
    best = group.results[0]
    assert best.path == "design/retrieval.md"
    assert "reciprocal rank" in best.snippet or "dense arm" in best.snippet
    assert -1.0 <= best.score <= 1.0
    assert best.stale is False


async def test_a_real_snippet_reads_back_off_the_file(
    tmp_path: Path, encoder: FastEmbedEncoder
) -> None:
    async with _built(tmp_path, encoder) as corpus:
        response = await groups.search_all(
            corpus.store_dir,
            corpus.db,
            config_for(tmp_path),
            SearchRequest(text="make release health check", limit_per_kb=5),
            encoder=encoder,
        )
        (group,) = response.groups
        assert isinstance(group, Group)
        for result in group.results:
            text = (corpus.root / result.path).read_bytes().decode("utf-8")
            lines = text.split("\n")
            kept = [f"{line}\n" for line in lines[:-1]]
            if lines[-1]:
                kept.append(lines[-1])
            assert result.snippet == "".join(kept[result.start_line - 1 : result.end_line])


async def test_the_real_tokenizer_keeps_every_sequence_under_the_models_cap(
    tmp_path: Path, encoder: FastEmbedEncoder
) -> None:
    """What the budget exists for: the assembled sequence — path, separator, body and special
    tokens — is under the cap the model would otherwise truncate at without saying so."""
    async with _built(tmp_path, encoder) as corpus, open_index(corpus) as opened:
        rows = await opened.connection.execute_fetchall("SELECT path, text FROM chunks")
        assert list(rows)
        for path, text in rows:
            assembled = encoder.count_tokens(f"{path}\n{text}") + encoder.n_special_tokens
            assert assembled <= encoder.max_sequence_tokens
