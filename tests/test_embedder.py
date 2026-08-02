"""The `Embedder` protocol — the only thing this milestone needs from "embedding"."""

from zikaron.core.store.embedder import Embedder, FakeEmbedder


def test_fake_embedder_satisfies_the_protocol() -> None:
    fake: Embedder = FakeEmbedder(model_name="BAAI/bge-small-en-v1.5", dim=384)
    assert isinstance(fake, Embedder)
    assert fake.model_name == "BAAI/bge-small-en-v1.5"
    assert fake.dim == 384


def test_fake_embedder_is_frozen() -> None:
    fake = FakeEmbedder(model_name="m", dim=1)
    try:
        fake.dim = 2  # type: ignore[misc]
    except AttributeError:
        pass
    else:
        raise AssertionError("FakeEmbedder must be immutable")
