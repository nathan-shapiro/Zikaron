"""`BackgroundLoadedEncoder` — what answers before the artifact exists, and what waits for it.

Every test here drives the load through a `threading.Event` the test itself controls rather than
through timing, so the two states that matter — *loading* and *loaded* — are reached on purpose
instead of being raced for. A test that slept and hoped would pass on a fast machine for the wrong
reason, and this class exists precisely because the real load takes about a second.

The one property worth naming, because it looks like an omission: the loader checks the artifact's
**width** and not its **name**. `FastEmbedEncoder.load` reports back the name it was handed, so a
name comparison here would compare a string with itself. A disagreeing name is caught where it can
be — at `Store.open`, against the store's own recorded metadata, before anything ever consults this
class and before the service has bound a socket.
"""

import threading
from collections.abc import Sequence

import pytest

from tests.fake_encoder import FakeEncoder
from zikaron.core.errors import BadConfigSource, ErrorCode, ZikaronError
from zikaron.core.indexing.encoder import BackgroundLoadedEncoder, Encoder


class _GatedLoad:
    """A loader that blocks until the test releases it, and records what it was asked for."""

    def __init__(self, artifact: Encoder | None = None, error: BaseException | None = None) -> None:
        self.released = threading.Event()
        self.entered = threading.Event()
        self.finished = threading.Event()
        self.asked_for: list[str] = []
        self._artifact = artifact if artifact is not None else FakeEncoder()
        self._error = error

    def __call__(self, model_name: str) -> Encoder:
        self.asked_for.append(model_name)
        self.entered.set()
        # Bounded, so a regression fails the suite rather than hanging it. `finished` exists
        # because of what that timeout makes possible: a test asserting only that `released` is
        # still unset is satisfied by the timeout expiring, which is the caller having waited the
        # full five seconds — the exact opposite of what such a test means to prove. Assert
        # against `finished` to mean "the load has not completed".
        self.released.wait(timeout=5.0)
        try:
            if self._error is not None:
                raise self._error
            return self._artifact
        finally:
            self.finished.set()


def _loading(
    load: _GatedLoad, *, model_name: str = FakeEncoder().model_name
) -> BackgroundLoadedEncoder:
    encoder = BackgroundLoadedEncoder(model_name=model_name, load=load)
    assert load.entered.wait(timeout=5.0), "the loader thread never started"
    return encoder


def test_declared_identity_answers_while_the_artifact_is_still_loading() -> None:
    """The property the whole class exists for: a consistency check against the store's recorded
    identity runs to completion with no model in memory.

    Both reads happen while the loader is provably still inside `load`, and the proof is that the
    load has not *finished* — not that it has not been released. Those are different claims, and
    only the first one fails when a declared property starts waiting for the artifact: the gate
    has a timeout, so a blocking read is released by that timeout expiring, leaving `released`
    unset and every value correct. Asserting on `released` here certified the property whether or
    not the code had it."""
    load = _GatedLoad()
    encoder = _loading(load)
    encoder.declare_dim(384)

    assert encoder.model_name == "BAAI/bge-small-en-v1.5"
    assert encoder.dim == 384
    assert not load.finished.is_set(), "a declared property waited for the artifact"

    load.released.set()


def test_dim_refuses_before_a_width_has_been_declared() -> None:
    """Using this as an `Encoder` before the store it belongs to was opened is a mistake with no
    safe answer: there is nothing to report and nothing to check against, so it says so rather
    than inventing a width or blocking on a load that would not settle the question either."""
    load = _GatedLoad()
    encoder = _loading(load)

    with pytest.raises(ZikaronError) as raised:
        _ = encoder.dim
    assert raised.value.code is ErrorCode.BAD_CONFIG

    encoder.release()
    load.released.set()


def test_artifact_members_wait_for_the_load_and_then_report_the_artifact() -> None:
    load = _GatedLoad(FakeEncoder(n_special_tokens=7, max_sequence_tokens=99))
    encoder = _loading(load)
    encoder.declare_dim(384)

    load.released.set()

    assert encoder.n_special_tokens == 7
    assert encoder.max_sequence_tokens == 99
    assert encoder.count_tokens("one two three") == 3
    assert encoder.token_char_spans("ab cd") == ((0, 2), (3, 5))
    assert len(encoder.embed(["x"])[0]) == 384


def test_a_width_disagreeing_with_the_store_is_refused_by_every_artifact_member() -> None:
    """The guard, asserted by breaking it: an artifact whose measured width is not the one the
    store recorded must never be usable for a read or a write, because every vector it produced
    would be stored labelled with an index it does not fit.

    Asserted through the members a caller actually reaches rather than through the comparison
    itself, since a check that fired but let the encoder be used anyway would satisfy an internal
    assertion and none of the contract."""
    load = _GatedLoad(FakeEncoder(dim=384))
    encoder = _loading(load)
    encoder.declare_dim(768)
    load.released.set()

    for reach_for_the_artifact in (
        lambda: encoder.n_special_tokens,
        lambda: encoder.max_sequence_tokens,
        lambda: encoder.count_tokens("x"),
        lambda: encoder.token_char_spans("x"),
        lambda: encoder.embed(["x"]),
    ):
        with pytest.raises(ZikaronError) as raised:
            reach_for_the_artifact()
        assert raised.value.code is ErrorCode.BAD_CONFIG


def test_the_width_refusal_names_the_store_as_the_authority_and_reports_both_widths() -> None:
    """The payload is the contract — a reader has to be able to see what the model reports and
    what the store recorded, or the error says only that something disagreed."""
    load = _GatedLoad(FakeEncoder(dim=384))
    encoder = _loading(load)
    encoder.declare_dim(768)
    load.released.set()

    with pytest.raises(ZikaronError) as raised:
        encoder.embed(["x"])

    payload = raised.value.data
    assert payload["source"] == BadConfigSource.META.value
    assert payload["key"] == "embed_model/embed_dim"
    assert "384" in str(payload["value"])
    assert "768" in str(payload["expected"])


def test_a_disagreeing_model_name_is_not_checked_here() -> None:
    """Stated as a test because its absence looks like a bug. The real loader echoes back the name
    it was given, so comparing them proves nothing; the width is the only fact the artifact
    independently supplies. A name that disagrees with the store is refused at `Store.open`, against
    the store's own metadata, before anything ever consults this class."""
    load = _GatedLoad(FakeEncoder(model_name="some/other-model", dim=384))
    encoder = _loading(load)
    encoder.declare_dim(384)
    load.released.set()

    assert encoder.count_tokens("one two") == 2
    assert encoder.model_name == "BAAI/bge-small-en-v1.5"


def test_a_load_that_raises_is_latched_and_re_raised_unchanged() -> None:
    """A load failure has nowhere else to go: it happens on a thread with no caller, after the
    point where it could have been raised from construction. Re-raising the original — rather than
    a wrapper naming it — keeps whatever diagnosis it carried."""
    original = RuntimeError("the artifact could not be downloaded")
    load = _GatedLoad(error=original)
    encoder = _loading(load)
    encoder.declare_dim(384)
    load.released.set()

    with pytest.raises(RuntimeError) as first:
        encoder.embed(["x"])
    with pytest.raises(RuntimeError) as second:
        encoder.count_tokens("x")

    assert first.value is original
    assert second.value is original


def test_the_load_is_attempted_once_however_many_callers_reach_for_it() -> None:
    """A retry per access would turn one bad configuration into an unbounded stream of model
    loads, each blocking whoever asked."""
    load = _GatedLoad(error=RuntimeError("no"))
    encoder = _loading(load)
    encoder.declare_dim(384)
    load.released.set()

    for _ in range(3):
        with pytest.raises(RuntimeError):
            encoder.count_tokens("x")

    assert load.asked_for == ["BAAI/bge-small-en-v1.5"]


def test_failure_reports_rather_than_raises_and_is_none_on_success() -> None:
    """For a holder whose job is to react to the failure — catching what you are watching for
    reads as an accident rather than as the point."""
    failing = _GatedLoad(error=RuntimeError("no"))
    encoder = _loading(failing)
    encoder.declare_dim(384)
    failing.released.set()
    assert isinstance(encoder.failure(), RuntimeError)

    working = _GatedLoad()
    fine = _loading(working)
    fine.declare_dim(384)
    working.released.set()
    assert fine.failure() is None


def test_artifact_returns_the_loaded_encoder_with_no_width_to_check() -> None:
    """The create path's shape: the store's width is about to be derived from this model, so there
    is nothing yet to check it against and the caller needs the artifact itself."""
    artifact = FakeEncoder(dim=384)
    load = _GatedLoad(artifact)
    encoder = _loading(load)
    load.released.set()

    assert encoder.artifact() is artifact


def test_artifact_re_raises_a_load_failure() -> None:
    original = RuntimeError("no artifact")
    load = _GatedLoad(error=original)
    encoder = _loading(load)
    load.released.set()

    with pytest.raises(RuntimeError) as raised:
        encoder.artifact()
    assert raised.value is original


def test_release_lets_the_loader_finish_with_nothing_declared() -> None:
    """A caller that abandons the store it was going to check against must still let the loader
    run to completion, or it leaves a thread blocked on a declaration that will never arrive."""
    load = _GatedLoad()
    encoder = _loading(load)

    encoder.release()
    load.released.set()

    assert encoder.failure() is None


def test_every_encoder_member_is_implemented() -> None:
    """`Encoder` is a protocol, so a member added to it and forgotten here would fail at the first
    call rather than at construction. `runtime_checkable` only checks presence, which is exactly
    what would be missed."""
    encoder = BackgroundLoadedEncoder(model_name="m", load=lambda _name: FakeEncoder())
    encoder.declare_dim(384)
    assert isinstance(encoder, Encoder)

    members: Sequence[str] = (
        "model_name",
        "dim",
        "n_special_tokens",
        "max_sequence_tokens",
        "count_tokens",
        "token_char_spans",
        "embed",
    )
    assert all(hasattr(encoder, name) for name in members)


def test_a_blocking_member_refuses_rather_than_hanging_when_nothing_was_declared() -> None:
    """The misuse `dim` already refuses, answered the same way by the members that block.

    Left alone this deadlocks in a way nothing can recover: the caller waits for a load that is
    itself waiting for the declaration that is never coming, with neither wait bounded. Two
    untimed waits pointed at each other is the worst shape a mistake can take here, and it costs
    one comparison to make it a refusal instead.

    The call is made on a thread this test joins with a deadline, rather than made directly. That
    is not ceremony: a direct call hangs forever if the guard is removed, and a test that hangs is
    one that never reports at all — strictly worse than one that fails. Verified by removing the
    guard, which hung the direct version and fails this one."""
    load = _GatedLoad()
    encoder = _loading(load)

    outcome: list[BaseException | None] = []

    def _reach_for_a_blocking_member() -> None:
        try:
            encoder.count_tokens("x")
        except BaseException as error:
            outcome.append(error)
        else:
            outcome.append(None)

    caller = threading.Thread(target=_reach_for_a_blocking_member, daemon=True)
    caller.start()
    caller.join(timeout=2.0)

    assert outcome, "the call hung waiting for a load that was waiting for the declaration"
    refusal = outcome[0]
    assert isinstance(refusal, ZikaronError)
    assert refusal.code is ErrorCode.BAD_CONFIG

    encoder.release()
    load.released.set()
