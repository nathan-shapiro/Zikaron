"""The encoder contract's failure paths, and the guards that fire when an artifact misbehaves.

No model is loaded here. `FastEmbedEncoder.load`'s happy path belongs to the integration tier, the
only place a real artifact's facts can be checked. This file covers the opposite:
the paths taken when the artifact cannot supply a fact the preflight has to budget against, and the
guard that refuses tokenizer offsets which do not index the text as passed.

Each of these is a `bad_config` rather than an `index_failed`, and that distinction is deliberate:
the model that was configured is the thing that is wrong, and `embedding.embed_model` is the key an
operator would change.
"""

from typing import Any, Final, cast

import pytest
from fastembed import TextEmbedding
from tokenizers import Tokenizer, models

from tests.fake_encoder import FakeEncoder
from zikaron.core.errors import ErrorCode, ZikaronError
from zikaron.core.indexing.encoder import ArtifactFacts, Encoder, FastEmbedEncoder

MODEL: Final = "BAAI/bge-small-en-v1.5"


class _StubEncoding:
    """A `tokenizers.Encoding` stand-in whose offsets are whatever a test needs them to be."""

    def __init__(self, ids: list[int], offsets: list[tuple[int, int]]) -> None:
        self.ids = ids
        self.offsets = offsets


class _StubTokenizer:
    """A tokenizer that reports offsets a test chooses, to exercise the offset guard."""

    def __init__(self, offsets: list[tuple[int, int]]) -> None:
        self._offsets = offsets

    def encode(self, text: str, add_special_tokens: bool = True) -> _StubEncoding:  # noqa: ARG002
        return _StubEncoding(ids=[1] * len(self._offsets), offsets=self._offsets)


class _StubModel:
    """A `TextEmbedding` stand-in exposing whatever `.model.tokenizer` a test wants it to."""

    def __init__(self, tokenizer: object) -> None:
        self.model = type("Inner", (), {"tokenizer": tokenizer})()

    def embed(self, documents: Any) -> Any:  # noqa: ANN401, ARG002
        return [[0.0]]


def _encoder_with(tokenizer: object) -> FastEmbedEncoder:
    """A `FastEmbedEncoder` around a stub, bypassing `load` since no artifact is involved.

    The `cast`s are the price of testing this class without a model: the constructor's parameters
    are annotated with the concrete `fastembed`/`tokenizers` types because those are what production
    passes, and structural stand-ins are the only way to reach the guards without loading 64 MiB of
    ONNX weights for one assertion.
    """
    return FastEmbedEncoder(
        model=cast("TextEmbedding", _StubModel(tokenizer)),
        tokenizer=cast("Tokenizer", tokenizer),
        facts=ArtifactFacts(model_name=MODEL, dim=384, n_special_tokens=2, max_sequence_tokens=512),
    )


def test_the_fake_encoder_satisfies_the_protocol_the_write_path_depends_on() -> None:
    """The unit tier's double has to be substitutable for the real one, or its tests prove nothing
    about production. `Encoder` extends the store's `Embedder`, so this also asserts the double is
    accepted by `Store.create`."""
    fake: Encoder = FakeEncoder()
    assert isinstance(fake, Encoder)
    assert (fake.model_name, fake.dim) == ("BAAI/bge-small-en-v1.5", 384)
    assert (fake.n_special_tokens, fake.max_sequence_tokens) == (2, 512)


def test_a_model_that_exposes_no_tokenizer_is_refused_naming_the_model_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("fastembed.TextEmbedding", lambda model_name: _StubModel(None))  # noqa: ARG005
    with pytest.raises(ZikaronError) as raised:
        FastEmbedEncoder.load(MODEL)
    assert raised.value.code is ErrorCode.BAD_CONFIG
    assert raised.value.data["key"] == "embedding.embed_model"
    assert raised.value.data["value"] == MODEL


def test_a_tokenizer_declaring_no_sequence_cap_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """The preflight budgets against the cap, so an artifact that states none cannot be budgeted
    against at all — better to refuse than to substitute a number from another model's card."""
    # A tokenizer with no truncation rule configured at all, which is what an artifact that states
    # no sequence cap looks like. `unk_token` is a vocabulary entry, not a credential.
    bare = Tokenizer(models.WordLevel(vocab={"probe": 0}, unk_token="probe"))  # noqa: S106
    assert bare.truncation is None
    monkeypatch.setattr("fastembed.TextEmbedding", lambda model_name: _StubModel(bare))  # noqa: ARG005
    with pytest.raises(ZikaronError) as raised:
        FastEmbedEncoder.load(MODEL)
    assert raised.value.code is ErrorCode.BAD_CONFIG
    assert "max_length" in str(raised.value.data["expected"])


@pytest.mark.parametrize(
    ("offsets", "why"),
    [
        ([(0, 99)], "an end past the text's length"),
        ([(-1, 2)], "a negative start"),
        ([(3, 1)], "an end before its own start"),
    ],
)
def test_offsets_that_do_not_index_the_text_as_passed_are_refused(
    offsets: list[tuple[int, int]], why: str
) -> None:
    """A tokenizer whose normalization rewrote the text would report offsets into the *rewritten*
    form. Slicing the original by those cuts in the wrong places and still yields text, so the
    failure would be silent — which is the one thing chunking exists to prevent."""
    encoder = _encoder_with(_StubTokenizer(offsets))
    with pytest.raises(ZikaronError) as raised:
        encoder.token_char_spans("abc")
    assert raised.value.code is ErrorCode.BAD_CONFIG, why


@pytest.mark.parametrize(
    ("offsets", "why"),
    [
        ([(2, 3), (0, 1)], "spans running backwards"),
        ([(0, 2), (1, 3)], "spans overlapping"),
    ],
)
def test_offsets_out_of_token_order_or_overlapping_are_refused(
    offsets: list[tuple[int, int]], why: str
) -> None:
    """A hard split slices from a window's first start to its last end, so out-of-order or
    overlapping spans would reorder or duplicate the prose inside a chunk — again, silently, since
    the result is still text."""
    encoder = _encoder_with(_StubTokenizer(offsets))
    with pytest.raises(ZikaronError) as raised:
        encoder.token_char_spans("abcd")
    assert raised.value.code is ErrorCode.BAD_CONFIG, why
    assert "token order" in str(raised.value.data["expected"])


def test_well_formed_offsets_pass_through_unchanged() -> None:
    encoder = _encoder_with(_StubTokenizer([(0, 1), (2, 3)]))
    assert encoder.token_char_spans("a b") == ((0, 1), (2, 3))
    assert encoder.count_tokens("a b") == 2
    assert (encoder.model_name, encoder.dim) == (MODEL, 384)
    assert (encoder.n_special_tokens, encoder.max_sequence_tokens) == (2, 512)
