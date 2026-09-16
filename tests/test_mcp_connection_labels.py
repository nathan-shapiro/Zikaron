"""`zikaron.mcp.connection.ServiceConnection` — session-label adoption, and the reserved `zk-`
namespace a client must honour on the way in.

`architecture.md`'s resolution ladder step 5, exactly: "The client adopts the returned label and
reuses it for its process lifetime." No socket is opened by any test here — each one monkeypatches
`ServiceConnection._connected_socket` to hand back an already-"connected" placeholder, since this
module's own behaviour under test is what it does with the label a *response* carries, never how
it gets a socket in the first place (`test_mcp_connection_integration.py` already covers that).
"""

from pathlib import Path

import pytest

from zikaron.mcp.connection import ServiceConnection


@pytest.fixture
def connection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ServiceConnection:
    """A `ServiceConnection` whose socket-establishing seam is stubbed out entirely — every test
    in this file is about label bookkeeping around `_send`, never about the connection sequence
    itself, so `_connected_socket` is replaced with a stub that hands back an object `_send` is
    also monkeypatched not to look at.

    `KIRO_SESSION_ID` is cleared **before** constructing `ServiceConnection`, in this fixture
    rather than in each test body: the constructor reads it once, at `__init__` time, so a test
    that called `monkeypatch.delenv` in its own body — after this fixture has already run — would
    be clearing the variable too late to affect a connection this fixture already built. Any test
    that needs a *present* harness value constructs its own `ServiceConnection` directly instead
    of using this fixture, for the identical reason in reverse.
    """
    monkeypatch.delenv("KIRO_SESSION_ID", raising=False)
    conn = ServiceConnection(tmp_path)

    async def fake_connected_socket(_self: ServiceConnection) -> object:
        return object()

    monkeypatch.setattr(ServiceConnection, "_connected_socket", fake_connected_socket)
    return conn


def _script_responses(monkeypatch: pytest.MonkeyPatch, responses: list[dict[str, object]]) -> None:
    """Replace module-level `_send_request`/`_read_response` so `ServiceConnection.request`
    "sends" nothing for real and "reads" each of `responses` in order — the two seams that
    replaced one combined `_send` when the send and receive halves of one round trip were split
    apart, so a caller could tell "never sent" from "sent, response lost" (`connection.py`'s own
    docstring on `request`).
    """
    queue = list(responses)

    def fake_send_request(
        _sock: object,
        _method: str,
        _params: dict[str, object],
        *,
        envelope: object,  # noqa: ARG001 — keyword-only name must match `_send_request`'s own.
    ) -> None:
        return None

    def fake_read_response(_sock: object) -> dict[str, object]:
        if not queue:
            raise AssertionError("no scripted response left")
        return queue.pop(0)

    monkeypatch.setattr("zikaron.mcp.connection._send_request", fake_send_request)
    monkeypatch.setattr("zikaron.mcp.connection._read_response", fake_read_response)


async def test_with_no_harness_session_id_the_first_response_label_is_adopted_for_the_next_call(
    connection: ServiceConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exact failure mode this fix exists to close: with no `KIRO_SESSION_ID`, a client that
    re-bootstraps on every call sends `session_id: null` forever, and the service mints a **new**
    `zk-<uuid4>` each time — so a `fetch` and the `amend` that follows it would carry different
    labels despite being one session's own two calls. This test proves the second call's envelope
    carries what the first response actually returned, not a fresh bootstrap.
    """
    _script_responses(
        monkeypatch,
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"uuid": "u1"},
                "client": {"session_id": "zk-first-minted-label"},
            },
        ],
    )

    first_envelope = connection.envelope(kind="mcp")
    assert first_envelope.session_id is None, "the very first call has nothing to adopt yet"
    await connection.request("memory_fetch", {}, envelope=first_envelope)

    second_envelope = connection.envelope(kind="mcp")
    assert second_envelope.session_id == "zk-first-minted-label"


async def test_a_label_is_adopted_from_an_application_error_response_too(
    connection: ServiceConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`architecture.md` step 4: `client.session_id` is returned "on success and on every error
    alike." A client that only adopted from a successful `result` would re-bootstrap after every
    rejected first call — precisely the case a consolidator's first `plan_groups` answering
    `store_busy` must not fall into, since the retry that follows depends on the same label.
    """
    _script_responses(
        monkeypatch,
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "error": {"code": -32020, "message": "store busy"},
                "client": {"session_id": "zk-minted-even-on-error"},
            },
        ],
    )

    envelope = connection.envelope(kind="consolidator")
    response = await connection.request("memory_plan_groups", {}, envelope=envelope)
    assert "error" in response

    next_envelope = connection.envelope(kind="consolidator")
    assert next_envelope.session_id == "zk-minted-even-on-error"


async def test_a_zk_prefixed_harness_value_is_treated_as_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`architecture.md`'s client contract, stated for exactly this case: "a client that finds a
    `zk-`-prefixed value in `KIRO_SESSION_ID` must treat it as absent." The `zk-` prefix is how the
    service tells its own minted labels apart from a harness's; forwarding one unchanged would let
    a harness masquerade as the service's own reserved namespace, breaking the one thing
    `label_source` is derived from.
    """
    monkeypatch.setenv("KIRO_SESSION_ID", "zk-a-harness-should-not-be-allowed-to-claim-this")

    conn = ServiceConnection(tmp_path)
    envelope = conn.envelope(kind="mcp")
    assert envelope.session_id is None


async def test_an_ordinary_harness_value_is_forwarded_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KIRO_SESSION_ID", "a-genuine-kiro-session-id")

    conn = ServiceConnection(tmp_path)
    envelope = conn.envelope(kind="mcp")
    assert envelope.session_id == "a-genuine-kiro-session-id"


async def test_an_already_adopted_label_is_not_overwritten_by_a_later_harness_read(
    connection: ServiceConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`envelope()` must read the connection's own held `_session_id`, never `os.environ` again
    after construction — this guards against a regression back toward re-reading the environment
    on every call, which is the exact defect this whole module was fixed to remove.
    """
    _script_responses(
        monkeypatch,
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {},
                "client": {"session_id": "zk-adopted-once"},
            },
        ],
    )
    await connection.request("memory_search", {}, envelope=connection.envelope(kind="mcp"))

    # Simulate the environment changing mid-process — this must have no effect on what the
    # connection has already adopted, unlike a design that re-read `os.environ` per call.
    monkeypatch.setenv("KIRO_SESSION_ID", "a-different-value-that-appeared-later")
    assert connection.envelope(kind="mcp").session_id == "zk-adopted-once"
