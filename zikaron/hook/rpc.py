"""Framing and sending exactly one `surface` request, and reading its one response line.

`architecture.md` §RPC: newline-delimited JSON-RPC 2.0. This module is deliberately not a copy of
`zikaron.service.rpc`'s own framing helpers — that module is stdlib-only too and reuse would be
free, but its whole surface (`parse_request`, `encode_result`, `encode_error`) is written from the
*server's* side of one exchange, parsing an incoming request and encoding an outgoing response;
this client only ever constructs one outgoing request and parses one incoming response, the
opposite pair, so there is nothing in that module this side would actually call. Mirrors the
identical hand-rolled shape `zikaron.service.lifecycle`'s own internal `_send_request` uses for
`health()`, restated here for `surface` rather than imported for the reason `connect.py`'s module
docstring gives.
"""

import json
import socket
import time
from dataclasses import dataclass
from typing import Self

from zikaron.hook.envelope import HookEnvelope

_MS_PER_SECOND = 1000


class SurfaceRejectionError(Exception):
    """The service answered with a JSON-RPC `error` object rather than a result.

    Carries the wire fields verbatim so `push.py`'s failure-logging path can name the code
    `architecture.md`'s error table gives — `store_busy`, `bad_config`, `reindexing`,
    `schema_incompatible`, or anything else the service returns — without this module needing to
    know what any of them mean.
    """

    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class NotSentError(TimeoutError):
    """The deadline passed before the request was sent, so the service never received it."""


@dataclass(frozen=True, slots=True)
class PushDeadline:
    """This process's one deadline for a push, read on two clocks.

    `at_ms` is sent as `deadline_at_ms`, so the service answers `deadline_passed` rather than
    committing a push nobody will read; it is wall-clock because the service shares only this
    machine's realtime clock, and a monotonic reading means nothing in another process. `by` is
    the same instant on this process's monotonic clock, which bounds its own socket waits.
    """

    at_ms: int
    by: float

    @classmethod
    def after(cls, seconds: float, *, now: float) -> Self:
        """`seconds` after `now`, a `time.monotonic()` reading; the wall clock is read beside it."""
        return cls(at_ms=int((time.time() + seconds) * _MS_PER_SECOND), by=now + seconds)


def surface_once(
    sock: socket.socket, *, prompt: str, limit: int, envelope: HookEnvelope, deadline: PushDeadline
) -> str:
    """Send one `memory_surface(prompt, limit, deadline_at_ms)` request and return its text.

    `deadline` bounds the whole exchange. A socket timeout bounds one call, so it is re-armed from
    `deadline.by` before the send and before every read, and an answer arriving in pieces cannot
    outrun it.

    A single `sendall`/`recv`-until-newline round trip — this client makes exactly one request per
    process, so there is no held connection for a partial-send ambiguity to matter against: unlike
    `zikaron.mcp.connection`'s own client, which must distinguish "nothing was sent" from "some of
    it was" because it might otherwise wrongly retry a request the service already ran, this
    process is about to exit either way and never retries anything, so `sendall`'s own
    documented inability to report partial progress carries no risk here that a second attempt
    could get wrong.

    Raises:
        NotSentError: the deadline had passed before the request could be sent.
        TimeoutError: the deadline passed before the whole answer arrived.
        OSError: the socket failed during send or receive.
        ConnectionError: the connection closed before a full line arrived, or the response was
            not a well-formed JSON-RPC envelope.
        SurfaceRejectionError: the service answered with an `error` object.
    """
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "memory_surface",
        "params": {
            "prompt": prompt,
            "limit": limit,
            "deadline_at_ms": deadline.at_ms,
            "client": envelope.as_client_object(),
        },
    }
    try:
        time_out_at(sock, deadline.by)
    except TimeoutError:
        raise NotSentError("the deadline passed before the request was sent") from None
    sock.sendall((json.dumps(request) + "\n").encode("utf-8"))
    buffer = b""
    while not buffer.endswith(b"\n"):
        time_out_at(sock, deadline.by)
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("connection closed before a full response was read")
        buffer += chunk
    parsed = json.loads(buffer.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ConnectionError(f"response was not a JSON object: {parsed!r}")
    if "result" in parsed:
        result = parsed["result"]
        text = result.get("text") if isinstance(result, dict) else None
        if not isinstance(text, str):
            raise ConnectionError(f"surface() did not return {{text}}: {result!r}")
        return text
    error = parsed.get("error")
    if not isinstance(error, dict):
        raise ConnectionError(f"response has neither a result nor an error object: {parsed!r}")
    code = error.get("code")
    message = error.get("message")
    if not isinstance(code, int) or not isinstance(message, str):
        raise ConnectionError(f"error object is missing code/message: {error!r}")
    raise SurfaceRejectionError(code, message)


def time_out_at(sock: socket.socket, instant: float) -> None:
    """Set `sock`'s timeout to what is left until `instant`, a `time.monotonic()` reading.

    A socket timeout bounds one call, so an exchange of several calls re-arms it before each one
    to bound the whole exchange.

    Raises:
        TimeoutError: `instant` has already passed.
    """
    remaining = instant - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("the deadline passed before the answer was complete")
    sock.settimeout(remaining)
