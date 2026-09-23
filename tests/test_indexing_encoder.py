"""The encoder contract's failure paths, and the guards that fire when an artifact misbehaves.

No model is loaded here. `FastEmbedEncoder.load`'s happy path belongs to the integration tier, the
only place a real artifact's facts can be checked. This file covers the opposite:
the paths taken when the artifact cannot supply a fact the preflight has to budget against, and the
guard that refuses tokenizer offsets which do not index the text as passed.

Each of these is a `bad_config` rather than an `index_failed`, and that distinction is deliberate:
the model that was configured is the thing that is wrong, and `embedding.embed_model` is the key an
operator would change.
"""

import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, cast

import pytest
from fastembed import TextEmbedding
from fastembed.common.utils import define_cache_dir
from tokenizers import Tokenizer, models

from tests.fake_encoder import FakeEncoder
from zikaron.core.errors import ErrorCode, ZikaronError
from zikaron.core.indexing.encoder import ArtifactFacts, Encoder, FastEmbedEncoder, token_head
from zikaron.core.indexing.model_cache import FASTEMBED_CACHE_VARIABLE, model_cache_dir

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


@pytest.fixture(autouse=True)
def pinned_artifact_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """`MODEL` is the pinned artefact, so `load` would otherwise reach the Hub for every test here.

    Autouse and unconditional: this file's subject is the guards `load` runs *after* it has a
    model, and a test that silently acquired 64 MB would be testing the network.
    """
    directory = tmp_path / "pinned-artifact"
    directory.mkdir()
    monkeypatch.setattr(
        "zikaron.core.indexing.acquisition.artifact_directory",
        lambda pin, *, cache_dir: directory,  # noqa: ARG005
    )
    return directory


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


class TestTheCacheDirectoryTheLoadPathHandsFastembed:
    """That `load` passes one, and that passing it is what keeps the tempdir empty.

    **The side effect under test is `define_cache_dir`'s `mkdir`**, which runs in
    `OnnxTextEmbedding.__init__` before the download and creates
    `tempfile.gettempdir()/fastembed_cache` whenever its argument is `None`. The stub below calls
    the library's real `define_cache_dir` so that the effect is fastembed's own rather than a
    re-implementation of it; nothing else about a model is needed to observe it.

    A relocated `tempfile.tempdir` rather than the machine's own, because `/tmp/fastembed_cache`
    already exists on any machine that has ever run this suite, so asserting against the real one
    would pass for a reason unrelated to the code.
    """

    @staticmethod
    @pytest.fixture
    def relocated_tempdir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
        elsewhere = tmp_path / "tempdir"
        elsewhere.mkdir()
        monkeypatch.setattr(tempfile, "tempdir", str(elsewhere))
        return elsewhere

    @staticmethod
    def _stub_calling_the_real_define_cache_dir(
        monkeypatch: pytest.MonkeyPatch, seen: dict[str, str | None]
    ) -> None:
        def _construct(
            model_name: str,  # noqa: ARG001
            cache_dir: str | None,
            specific_model_path: str | None,  # noqa: ARG001
        ) -> _StubModel:
            seen["cache_dir"] = cache_dir
            define_cache_dir(cache_dir)
            return _StubModel(None)

        monkeypatch.setattr("fastembed.TextEmbedding", _construct)

    def test_nothing_is_created_under_the_tempdir(
        self, monkeypatch: pytest.MonkeyPatch, relocated_tempdir: Path, tmp_path: Path
    ) -> None:
        """The mutation this is written against is the resolver returning `define_cache_dir(None)`.
        The `FASTEMBED_CACHE_PATH` override is set so the assertion does not depend on the home
        directory of whoever runs it — and under that mutation `define_cache_dir(None)` would read
        the same variable, so the variable is *unset* and a home is supplied instead.
        """
        monkeypatch.delenv(FASTEMBED_CACHE_VARIABLE, raising=False)
        monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
        monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path / "home"))
        seen: dict[str, str | None] = {}
        self._stub_calling_the_real_define_cache_dir(monkeypatch, seen)

        with pytest.raises(ZikaronError):
            FastEmbedEncoder.load(MODEL)

        assert list(relocated_tempdir.iterdir()) == []
        # **Compared against the pure resolver rather than a spelled-out path.** Spelling one bakes
        # in a platform: an earlier form asserted `~/.cache/zikaron/models` and was red on macOS,
        # where the correct answer is `~/Library/Caches/…`. What this call is for is the *wiring* —
        # that `load` hands fastembed what the resolver returns — and `test_indexing_model_cache.py`
        # is where each platform's own answer is pinned.
        assert seen["cache_dir"] == str(
            model_cache_dir(environ={}, platform=sys.platform, home=tmp_path / "home")
        )

    def test_the_directory_it_names_is_the_one_that_gets_made(
        self, monkeypatch: pytest.MonkeyPatch, relocated_tempdir: Path, tmp_path: Path
    ) -> None:
        """`define_cache_dir` creates whatever it is handed, so the stray `mkdir` lands in the
        durable directory instead of being merely avoided."""
        durable = tmp_path / "durable-cache"
        monkeypatch.setenv(FASTEMBED_CACHE_VARIABLE, str(durable))
        self._stub_calling_the_real_define_cache_dir(monkeypatch, {})

        with pytest.raises(ZikaronError):
            FastEmbedEncoder.load(MODEL)

        assert durable.is_dir()
        assert list(relocated_tempdir.iterdir()) == []


def _raising_construction(**_kwargs: object) -> None:
    raise RuntimeError("onnxruntime: cannot load shared library")


class TestAPinnedArtefactThatWillNotConstruct:
    """**The refusal has to say which of two things is wrong, because nothing else will.**

    `server.py` logs a traceback for a non-`ZikaronError` and returns only `data` for a
    `ZikaronError`, and nothing in the package renders `__cause__`. So converting a construction
    failure without carrying its text would report a broken `onnxruntime` as a config fault, point
    the user at a `doctor` that passes, and leave the real message on no channel — worse than the
    raw traceback it replaced.
    """

    def test_it_names_both_doctor_and_the_underlying_cause(
        self, monkeypatch: pytest.MonkeyPatch, pinned_artifact_dir: Path
    ) -> None:
        monkeypatch.setattr("fastembed.TextEmbedding", _raising_construction)
        with pytest.raises(ZikaronError) as raised:
            FastEmbedEncoder.load(MODEL)
        expected = str(raised.value.data["expected"])
        assert raised.value.code is ErrorCode.BAD_CONFIG
        assert "zikaron doctor" in expected
        assert str(pinned_artifact_dir) in expected
        assert "onnxruntime: cannot load shared library" in expected
        assert isinstance(raised.value.__cause__, RuntimeError)

    def test_an_unpinned_model_raises_unchanged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Nothing was acquired and nothing is pinned, so there is no pin to point a reader at and
        the original exception is the most informative thing available."""
        monkeypatch.setattr("zikaron.core.indexing.model_pin.pin_for", lambda _name: None)
        monkeypatch.setattr("fastembed.TextEmbedding", _raising_construction)
        with pytest.raises(RuntimeError):
            FastEmbedEncoder.load(MODEL)


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
    monkeypatch.setattr(
        "fastembed.TextEmbedding",
        lambda model_name, cache_dir, specific_model_path: _StubModel(None),  # noqa: ARG005
    )
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
    monkeypatch.setattr(
        "fastembed.TextEmbedding",
        lambda model_name, cache_dir, specific_model_path: _StubModel(bare),  # noqa: ARG005
    )
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


def test_a_head_is_sliced_on_token_boundaries() -> None:
    assert token_head("alpha beta gamma", tokens=2, encoder=FakeEncoder()) == "alpha beta"


def test_a_head_of_a_text_with_no_tokens_is_empty_rather_than_an_error() -> None:
    """Total rather than precondition-guarded: both callers only ask for a head of text they have
    already counted tokens in, so this answers a question nothing in the store asks — and answering
    it with the empty string, which is what a head of nothing is, is cheaper than a precondition
    every later caller has to remember."""
    assert token_head("   ", tokens=5, encoder=FakeEncoder()) == ""


@dataclass
class _ShortSpanEncoder(FakeEncoder):
    """An encoder whose spans cover fewer tokens than it says the text has.

    Well-formed but short is the dangerous shape: every span is ordered and in range, so the guards
    that check *those* properties pass, and the head that results silently keeps less text than the
    count it was derived from promised.
    """

    def token_char_spans(self, text: str) -> tuple[tuple[int, int], ...]:
        return super().token_char_spans(text)[:1]


def test_a_head_is_refused_when_the_artifacts_count_and_spans_disagree() -> None:
    with pytest.raises(ZikaronError) as excinfo:
        token_head("alpha beta gamma", tokens=2, encoder=_ShortSpanEncoder())
    assert excinfo.value.code is ErrorCode.BAD_CONFIG
    assert excinfo.value.data["key"] == "embedding.embed_model"
