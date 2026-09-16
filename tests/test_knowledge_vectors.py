"""`zikaron.core.knowledge.vectors` — batched embedding, and what it refuses to store.

The batch size is a throughput decision and must not be able to change an answer, so the tests
about batching assert *what was handed to the model* as well as what came back.
"""

import struct
from typing import Final

import pytest

from tests.fake_encoder import FakeEncoder
from zikaron.core.errors import ErrorCode, IndexStage, ZikaronError
from zikaron.core.indexing.encoder import index_identity_disagrees
from zikaron.core.knowledge import vectors
from zikaron.core.knowledge.chunking import FileChunkPlan, plan_file_chunks

_PATH: Final = "docs/a.md"

#: Five paragraphs, so a plan of five chunks at a one-token budget — enough to see a batch boundary
#: fall somewhere other than the end.
_TEXT: Final = "alpha\n\nbeta\n\ngamma\n\ndelta\n\nepsilon\n"


def _plan(encoder: FakeEncoder, text: str = _TEXT) -> FileChunkPlan:
    return plan_file_chunks(path=_PATH, text=text, encoder=encoder, chunk_max_tokens=1)


async def _embed(
    encoder: FakeEncoder, *, batch_size: int, plan: FileChunkPlan | None = None
) -> tuple[bytes, ...]:
    return await vectors.embed_chunks(
        plan if plan is not None else _plan(encoder),
        encoder=encoder,
        embed_dim=encoder.dim,
        batch_size=batch_size,
    )


async def test_the_chunks_are_embedded_in_passes_of_the_batch_size() -> None:
    encoder = FakeEncoder()
    await _embed(encoder, batch_size=2)
    assert [len(pass_) for pass_ in encoder.embedded] == [2, 2, 1]


async def test_a_batch_larger_than_the_file_is_one_pass() -> None:
    encoder = FakeEncoder()
    await _embed(encoder, batch_size=32)
    assert [len(pass_) for pass_ in encoder.embedded] == [5]


async def test_a_batch_size_of_one_is_a_pass_per_chunk() -> None:
    encoder = FakeEncoder()
    await _embed(encoder, batch_size=1)
    assert [len(pass_) for pass_ in encoder.embedded] == [1, 1, 1, 1, 1]


async def test_every_chunk_is_embedded_once_in_order_whatever_the_batch_size() -> None:
    """The batch boundary is where an implementation that re-slices its own input loses or repeats
    a chunk, and the loss would be silent: the count still matches, and the vectors still store."""
    wide = FakeEncoder()
    narrow = FakeEncoder()
    await _embed(wide, batch_size=32)
    await _embed(narrow, batch_size=2)
    assert [text for pass_ in wide.embedded for text in pass_] == [
        text for pass_ in narrow.embedded for text in pass_
    ]


async def test_what_is_embedded_is_the_path_prefixed_sequence() -> None:
    encoder = FakeEncoder()
    plan = _plan(encoder, "alpha\n")
    await _embed(encoder, batch_size=32, plan=plan)
    assert encoder.embedded == [(plan.chunks[0].embedded_text(_PATH),)]


async def test_a_file_with_no_chunks_embeds_nothing() -> None:
    encoder = FakeEncoder()
    assert await _embed(encoder, batch_size=32, plan=_plan(encoder, "")) == ()
    assert encoder.embedded == []


async def test_the_stored_vectors_are_unit_length() -> None:
    """Every cosine this store reads back is `1 - d^2/2` over a `vec0` L2 distance, which is exact
    only for unit vectors — so the normalization is the thing that makes a threshold mean what it
    says, not a tidying step."""
    encoder = FakeEncoder()
    stored = await _embed(encoder, batch_size=2)
    for packed in stored:
        unpacked = struct.unpack(f"<{len(packed) // 4}f", packed)
        assert len(unpacked) == encoder.dim
        assert sum(value * value for value in unpacked) == pytest.approx(1.0)


async def test_an_embedder_that_raises_is_an_index_failure() -> None:
    encoder = FakeEncoder(embed_error=RuntimeError("the model is not loadable"))
    with pytest.raises(ZikaronError) as excinfo:
        await _embed(encoder, batch_size=2)
    assert excinfo.value.code is ErrorCode.INDEX_FAILED
    assert excinfo.value.data["stage"] == IndexStage.EMBED


async def test_a_store_error_from_the_embedder_keeps_its_own_code() -> None:
    """The case this is really about: a deferred model load that failed latches its failure and
    re-raises it on every use. That is a configuration problem naming the model, and rewriting it
    as an indexing failure would send whoever reads it to look at the file being indexed."""
    latched = index_identity_disagrees(
        reported_model="other", reported_dim=7, recorded_model="expected", recorded_dim=384
    )
    encoder = FakeEncoder(embed_error=latched)
    with pytest.raises(ZikaronError) as excinfo:
        await _embed(encoder, batch_size=2)
    assert excinfo.value is latched


async def test_an_embedder_returning_too_few_vectors_is_an_index_failure() -> None:
    """A pass that answers with a different number of vectors than it was given texts has lost the
    correspondence between chunk and vector, and storing them anyway would label a chunk with
    another chunk's meaning."""
    encoder = FakeEncoder(vector_count_delta=1)
    with pytest.raises(ZikaronError) as excinfo:
        await _embed(encoder, batch_size=32)
    assert excinfo.value.code is ErrorCode.INDEX_FAILED
    assert excinfo.value.data["stage"] == IndexStage.EMBED


async def test_an_embedder_returning_the_wrong_width_is_an_index_failure() -> None:
    encoder = FakeEncoder(vector_width=7)
    with pytest.raises(ZikaronError) as excinfo:
        await _embed(encoder, batch_size=32)
    assert excinfo.value.code is ErrorCode.INDEX_FAILED
    assert excinfo.value.data["stage"] == IndexStage.EMBED
