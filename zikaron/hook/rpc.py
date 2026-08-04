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

from zikaron.hook.envelope import HookEnvelope


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


def surface_once(sock: socket.socket, *, prompt: str, limit: int, envelope: HookEnvelope) -> str:
    """Send one `surface(prompt, limit)` request and return the text it answered with.

    A single `sendall`/`recv`-until-newline round trip — this client makes exactly one request per
    process, so there is no held connection for a partial-send ambiguity to matter against: unlike
    `zikaron.mcp.connection`'s own client, which must distinguish "nothing was sent" from "some of
    it was" because it might otherwise wrongly retry a request the service already ran, this
    process is about to exit either way and never retries anything, so `sendall`'s own
    documented inability to report partial progress carries no risk here that a second attempt
    could get wrong.

    Raises:
        OSError: the socket failed during send or receive.
        ConnectionError: the connection closed before a full line arrived, or the response was
            not a well-formed JSON-RPC envelope.
        SurfaceRejection: the service answered with an `error` object.
    """
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "surface",
        "params": {
            "prompt": prompt,
            "limit": limit,
            "client": envelope.as_client_object(),
        },
    }
    sock.sendall((json.dumps(request) + "\n").encode("utf-8"))
    buffer = b""
    while not buffer.endswith(b"\n"):
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
