"""Reading one method's raw JSON `params` into the typed value its handler needs.

Shared by `dispatch.py` and `dispatch_consolidation.py` so a malformed request produces the
identical `bounds` shape regardless of which dispatch module handles the method — a second,
independently-written set of these checks is how one dispatch module comes to accept a value the
other refuses for the same field name.

Every function raises `ZikaronError(BOUNDS, ...)` rather than a bare `TypeError`/`KeyError`: an
RPC parameter that fails these checks is exactly `architecture.md`'s rung-1 `bounds` rejection —
"cheapest, and independent of store state" — for the same reason a limit outside 1-50 is, so a
malformed request gets the same wire error a well-shaped one that violates a range does, rather
than a protocol-level failure that would suggest the transport itself misbehaved.
"""

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import aiosqlite

from zikaron.core.errors import ErrorCode, ZikaronError
from zikaron.core.records.memory import CallParams
from zikaron.service.envelope import ResolvedEnvelope
from zikaron.service.serialize import RpcResult

if TYPE_CHECKING:
    from zikaron.service.context import ServiceContext

#: One RPC method's handler: a connection, the assembled service state, the resolved envelope,
#: and the raw params, in to a typed `RpcResult` out. Shared here rather than declared separately
#: in `dispatch.py` and `dispatch_consolidation.py` so `server.py` can hold both modules' method
#: tables in one `Mapping` of one type.
type Handler = Callable[
    ["aiosqlite.Connection", "ServiceContext", ResolvedEnvelope, dict[str, object]],
    Awaitable[RpcResult],
]


def call_params(envelope: ResolvedEnvelope, *, max_depth: int) -> CallParams:
    """The resolved envelope, as the `CallParams` every `core` mutation and read takes."""
    return CallParams(
        session_id=envelope.session_id,
        client_kind=envelope.kind,
        op_id=envelope.op_id,
        max_depth=max_depth,
    )


def require_str(params: dict[str, object], name: str) -> str:
    """`params[name]` if it is a string, else `bounds`."""
    value = params.get(name)
    if not isinstance(value, str):
        raise ZikaronError(ErrorCode.BOUNDS, field=name, limit="a string", actual=value)
    return value


def optional_str(params: dict[str, object], name: str) -> str | None:
    """`params[name]` if present and a string, `None` if absent or explicitly `null`, else
    `bounds`."""
    value = params.get(name)
    if value is not None and not isinstance(value, str):
        raise ZikaronError(ErrorCode.BOUNDS, field=name, limit="a string or absent", actual=value)
    return value


def require_int(params: dict[str, object], name: str, *, default: int | None = None) -> int:
    """`params[name]` if it is an integer, `default` if absent and one was given, else `bounds`.

    `bool` is excluded even though it is an `int` subclass: a request sending `true` for a version
    or a limit must not silently become `1`, the same exactness `ConfigKey.accepts` enforces for a
    configured value.
    """
    if name not in params:
        if default is not None:
            return default
        raise ZikaronError(ErrorCode.BOUNDS, field=name, limit="an integer", actual=None)
    value = params[name]
    if not isinstance(value, int) or isinstance(value, bool):
        raise ZikaronError(ErrorCode.BOUNDS, field=name, limit="an integer", actual=value)
    return value


def require_bool(params: dict[str, object], name: str, *, default: bool) -> bool:
    """`params[name]` if it is a boolean, `default` if absent, else `bounds`."""
    value = params.get(name, default)
    if not isinstance(value, bool):
        raise ZikaronError(ErrorCode.BOUNDS, field=name, limit="a boolean", actual=value)
    return value


def require_uuid_list(params: dict[str, object], name: str) -> list[str]:
    """`params[name]` if it is a list of strings, else `bounds`."""
    value = params.get(name)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ZikaronError(ErrorCode.BOUNDS, field=name, limit="a list of strings", actual=value)
    return value


def require_object(params: dict[str, object], name: str) -> dict[str, object]:
    """`params[name]` if it is a JSON object, else `bounds`."""
    value = params.get(name)
    if not isinstance(value, dict):
        raise ZikaronError(ErrorCode.BOUNDS, field=name, limit="an object", actual=value)
    return value
