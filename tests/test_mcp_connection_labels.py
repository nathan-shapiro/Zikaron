"""`zikaron.mcp.connection.ServiceConnection` — session-label adoption, and the reserved `zk-`
namespace a client must honour on the way in.

`architecture.md`'s resolution ladder step 5, exactly: "The client adopts the returned label and
reuses it for its process lifetime." No socket is opened by any test here — each one monkeypatches
`ServiceConnection._connected_socket` to hand back an already-"connected" placeholder, since this
module's own behaviour under test is what it does with the label a *response* carries, never how
it gets a socket in the first place (`test_mcp_connection_integration.py` already covers that).
"""

import os
from pathlib import Path

import pytest

from zikaron.core.errors import ErrorCode, ZikaronError
from zikaron.harness import detect
from zikaron.mcp.connection import ServiceConnection
from zikaron.service import paths
from zikaron.service.envelope import ClientEnvelope


@pytest.fixture
def connection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ServiceConnection:
    """A `ServiceConnection` whose socket-establishing seam is stubbed out entirely — every test
    in this file is about label bookkeeping around `_send`, never about the connection sequence
    itself, so `_connected_socket` is replaced with a stub that hands back an object `_send` is
    also monkeypatched not to look at. The harness's variables are already absent (`conftest`).
    """
    conn = ServiceConnection(tmp_path)

    class _FakeSocket:
        def settimeout(self, _timeout: float) -> None:
            pass

    async def fake_connected_socket(_self: ServiceConnection) -> object:
        return _FakeSocket()

    monkeypatch.setattr(ServiceConnection, "_connected_socket", fake_connected_socket)
    return conn


def _script_responses(
    monkeypatch: pytest.MonkeyPatch, responses: list[dict[str, object]]
) -> list[ClientEnvelope]:
    """Replace module-level `_send_request`/`_read_response` so `ServiceConnection.request`
    "sends" nothing for real and "reads" each of `responses` in order — the two seams that
    replaced one combined `_send` when the send and receive halves of one round trip were split
    apart, so a caller could tell "never sent" from "sent, response lost" (`connection.py`'s own
    docstring on `request`). Returns the envelopes "sent", in order.
    """
    queue = list(responses)
    sent: list[ClientEnvelope] = []

    def fake_send_request(
        _sock: object,
        _method: str,
        _params: dict[str, object],
        *,
        envelope: ClientEnvelope,
    ) -> None:
        sent.append(envelope)

    def fake_read_response(_sock: object) -> dict[str, object]:
        if not queue:
            raise AssertionError("no scripted response left")
        return queue.pop(0)

    monkeypatch.setattr("zikaron.mcp.connection._send_request", fake_send_request)
    monkeypatch.setattr("zikaron.mcp.connection._read_response", fake_read_response)
    return sent


_ANSWER: dict[str, object] = {"jsonrpc": "2.0", "id": 1, "result": {}}


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
    connection: ServiceConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`architecture.md`'s client contract, stated for exactly this case: "a client that finds a
    `zk-`-prefixed value in `KIRO_SESSION_ID` must treat it as absent." The `zk-` prefix is how the
    service tells its own minted labels apart from a harness's; forwarding one unchanged would let
    a harness masquerade as the service's own reserved namespace, breaking the one thing
    `label_source` is derived from.
    """
    sent = _script_responses(monkeypatch, [_ANSWER])
    monkeypatch.setenv("KIRO_SESSION_ID", "zk-a-harness-should-not-be-allowed-to-claim-this")
    await connection.request("memory_search", {}, envelope=connection.envelope(kind="mcp"))
    assert sent[0].session_id is None


async def test_an_ordinary_harness_value_is_forwarded_unchanged(
    connection: ServiceConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent = _script_responses(monkeypatch, [_ANSWER])
    monkeypatch.setenv("KIRO_SESSION_ID", "a-genuine-kiro-session-id")
    await connection.request("memory_search", {}, envelope=connection.envelope(kind="mcp"))
    assert sent[0].session_id == "a-genuine-kiro-session-id"


async def test_the_label_is_resolved_at_the_first_request_not_at_construction(
    connection: ServiceConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A kiro MCP server starts in the same second as the session's start hook, whose relay is
    what the seam reads under kiro: a label resolved when the server was built would be the minted
    one the relay was meant to replace."""
    sent = _script_responses(monkeypatch, [_ANSWER])
    relay_dir = paths.session_relay_dir(connection.location.runtime_dir)
    relay_dir.mkdir(parents=True)
    detect.relay_file(relay_dir, os.getppid()).write_text("sess_written-after-the-server-started")
    await connection.request("memory_search", {}, envelope=connection.envelope(kind="mcp"))
    assert sent[0].session_id == "sess_written-after-the-server-started"


async def test_the_resolved_label_does_not_change_after_the_first_request(
    connection: ServiceConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent = _script_responses(monkeypatch, [_ANSWER, _ANSWER])
    monkeypatch.setenv("KIRO_SESSION_ID", "the-first-label")
    await connection.request("memory_search", {}, envelope=connection.envelope(kind="mcp"))
    monkeypatch.setenv("KIRO_SESSION_ID", "a-later-label")
    await connection.request("memory_search", {}, envelope=connection.envelope(kind="mcp"))
    assert [envelope.session_id for envelope in sent] == ["the-first-label", "the-first-label"]


async def test_an_already_adopted_label_is_not_overwritten_by_a_later_harness_read(
    connection: ServiceConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`envelope()` must read the connection's own held `_session_id`, never `os.environ` again
    after the first request — this guards against a regression back toward re-reading the
    environment on every call, which would split one process's writes across labels.
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


def test_constructing_a_connection_refuses_an_unusable_runtime_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`StoreLocation.resolve` runs in `__init__`, so `paths.socket_path`'s refusal surfaces when
    this client is constructed — before a tool is registered, let alone called.
    `tests/test_mcp_main.py` covers what the process then prints.

    Pure: nothing is connected and nothing touches the filesystem. It pins the wiring, which the
    boundary tests in `test_service_paths.py` cannot see.
    """
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/" + "x" * 110)
    with pytest.raises(ZikaronError) as raised:
        ServiceConnection(tmp_path)
    assert raised.value.code is ErrorCode.BAD_CONFIG
