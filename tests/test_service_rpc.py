"""`zikaron.service.rpc` — newline-delimited JSON-RPC 2.0 framing and its own protocol error
range."""

import json

import pytest

from zikaron.core.errors import APPLICATION_CODE_MAX, APPLICATION_CODE_MIN
from zikaron.service.rpc import (
    ProtocolErrorCode,
    RequestParseError,
    RpcRequest,
    encode_error,
    encode_result,
    parse_request,
)


def test_parses_a_well_formed_request() -> None:
    line = json.dumps({"jsonrpc": "2.0", "id": 7, "method": "health", "params": {}})
    request = parse_request(line)
    assert request == RpcRequest(method="health", params={}, request_id=7, has_id=True)


def test_params_defaults_to_an_empty_object_when_absent() -> None:
    line = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "health"})
    request = parse_request(line)
    assert request.params == {}


def test_request_id_may_be_a_string() -> None:
    line = json.dumps({"jsonrpc": "2.0", "id": "abc", "method": "health", "params": {}})
    request = parse_request(line)
    assert request.request_id == "abc"


def test_a_notification_has_no_id_and_has_id_is_false() -> None:
    """A JSON-RPC *notification*: the `id` key is absent entirely, and gets no response at all —
    distinct from a request whose `id` is explicitly `null`, which still gets a response."""
    line = json.dumps({"jsonrpc": "2.0", "method": "health", "params": {}})
    request = parse_request(line)
    assert request.request_id is None
    assert request.has_id is False


def test_an_explicit_null_id_is_a_real_request_not_a_notification() -> None:
    """`dict.get("id")` returns `None` for both an absent key and an explicit `null` value —
    `has_id` is what tells the two apart, since only the first is a notification."""
    line = json.dumps({"jsonrpc": "2.0", "id": None, "method": "health", "params": {}})
    request = parse_request(line)
    assert request.request_id is None
    assert request.has_id is True


def test_rejects_a_line_that_is_not_valid_json() -> None:
    with pytest.raises(RequestParseError) as excinfo:
        parse_request("not json at all {{{")
    assert excinfo.value.code is ProtocolErrorCode.PARSE_ERROR
    assert excinfo.value.request_id is None


def test_rejects_a_top_level_value_that_is_not_an_object() -> None:
    with pytest.raises(RequestParseError) as excinfo:
        parse_request(json.dumps([1, 2, 3]))
    assert excinfo.value.code is ProtocolErrorCode.INVALID_REQUEST


def test_rejects_the_wrong_jsonrpc_version() -> None:
    line = json.dumps({"jsonrpc": "1.0", "id": 1, "method": "health"})
    with pytest.raises(RequestParseError) as excinfo:
        parse_request(line)
    assert excinfo.value.code is ProtocolErrorCode.INVALID_REQUEST
    assert excinfo.value.request_id == 1


def test_rejects_a_missing_method() -> None:
    line = json.dumps({"jsonrpc": "2.0", "id": 1})
    with pytest.raises(RequestParseError) as excinfo:
        parse_request(line)
    assert excinfo.value.code is ProtocolErrorCode.INVALID_REQUEST


def test_rejects_an_empty_method() -> None:
    line = json.dumps({"jsonrpc": "2.0", "id": 1, "method": ""})
    with pytest.raises(RequestParseError) as excinfo:
        parse_request(line)
    assert excinfo.value.code is ProtocolErrorCode.INVALID_REQUEST


def test_rejects_params_that_is_not_an_object() -> None:
    line = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "health", "params": [1, 2]})
    with pytest.raises(RequestParseError) as excinfo:
        parse_request(line)
    assert excinfo.value.code is ProtocolErrorCode.INVALID_PARAMS
    assert excinfo.value.request_id == 1
    assert excinfo.value.has_id is True


def test_a_notification_whose_params_fail_shape_validation_still_carries_has_id_false() -> None:
    """`RequestParseError` itself must know whether the request that failed had an `id` key —
    not only `RpcRequest`'s own success path — since `has_id` is knowable by the time the
    `params` check runs and a notification's shape failure must be suppressible exactly as a
    later, method-level rejection of the same notification would be."""
    line = json.dumps({"jsonrpc": "2.0", "method": "remember", "params": "not-an-object"})
    with pytest.raises(RequestParseError) as excinfo:
        parse_request(line)
    assert excinfo.value.code is ProtocolErrorCode.INVALID_PARAMS
    assert excinfo.value.has_id is False


def test_a_parse_error_before_has_id_is_knowable_defaults_to_true() -> None:
    """Invalid JSON, or a top level that is not even an object, happens before any `id` key is
    knowable at all — `has_id` defaults to `True` for those two cases, meaning "there is a
    response to give," since a truly unparseable line has no notification identity to suppress a
    response for."""
    with pytest.raises(RequestParseError) as excinfo:
        parse_request("not json {{{")
    assert excinfo.value.has_id is True

    with pytest.raises(RequestParseError) as excinfo:
        parse_request(json.dumps([1, 2, 3]))
    assert excinfo.value.has_id is True


def test_encode_result_is_a_single_newline_terminated_json_line() -> None:
    line = encode_result(7, {"ok": True})
    assert line.endswith("\n")
    assert line.count("\n") == 1
    parsed = json.loads(line)
    assert parsed == {"jsonrpc": "2.0", "id": 7, "result": {"ok": True}}


def test_encode_result_with_a_session_id_attaches_it_as_a_sibling_of_result() -> None:
    """`session_id` is never merged into `result` — a **sibling** `client: {session_id}` field,
    which is what lets a bare-list `result` (`search`'s documented shape) still carry the label."""
    line = encode_result(7, {"ok": True}, session_id="s1")
    parsed = json.loads(line)
    assert parsed == {
        "jsonrpc": "2.0",
        "id": 7,
        "result": {"ok": True},
        "client": {"session_id": "s1"},
    }


def test_encode_result_with_a_bare_list_result_still_attaches_the_session_id() -> None:
    """The case a merged-into-`result` approach could never represent: `zikaron_search`'s own
    documented shape is a bare list, which has no key to add `session_id` to."""
    line = encode_result(7, [{"uuid": "u1"}], session_id="s1")
    parsed = json.loads(line)
    assert parsed["result"] == [{"uuid": "u1"}]
    assert parsed["client"] == {"session_id": "s1"}


def test_encode_result_without_a_session_id_carries_no_client_field() -> None:
    """`health()` resolves no label at all — the parameter's default omits the field entirely
    rather than writing `"client": null`, which would claim a resolution that never happened."""
    line = encode_result(7, {"ready": True})
    parsed = json.loads(line)
    assert "client" not in parsed


def test_encode_error_without_data() -> None:
    line = encode_error(7, -32000, "no memory with that uuid")
    parsed = json.loads(line)
    assert parsed == {
        "jsonrpc": "2.0",
        "id": 7,
        "error": {"code": -32000, "message": "no memory with that uuid"},
    }


def test_encode_error_with_data() -> None:
    line = encode_error(7, -32000, "no memory with that uuid", {"uuid": "abc"})
    parsed = json.loads(line)
    assert parsed["error"]["data"] == {"uuid": "abc"}


def test_encode_error_with_a_session_id_attaches_it_as_a_sibling_of_error_not_inside_data() -> None:
    """`architecture.md`: "Returns `client.session_id` in the response envelope — on success and
    on every error alike," naming the response *envelope* — the same top-level `client` sibling
    `encode_result` uses, not a field spliced into the error's own declared `data` shape. Every
    application error's `data` is a fixed, documented shape (`not_found` is `{uuid}`; nothing in
    the error table names `session_id` as one of its own fields), so this asserts `data` comes
    back exactly as given, unmodified, alongside the label rather than polluted by it."""
    line = encode_error(7, -32000, "no memory with that uuid", {"uuid": "abc"}, session_id="s1")
    parsed = json.loads(line)
    assert parsed["client"] == {"session_id": "s1"}
    assert parsed["error"]["data"] == {"uuid": "abc"}


def test_encode_error_with_no_session_id_attaches_no_client_field_at_all() -> None:
    """Mirrors `encode_result`'s own symmetric behaviour: a resolution that never produced a
    label (a shape failure in `parse_envelope` itself, before `resolve()` ever ran) has nothing
    to echo, and `architecture.md`'s own "no exceptions" claim is scoped to errors occurring
    *after* resolution — this is the one case genuinely before it."""
    line = encode_error(7, -32000, "no memory with that uuid", {"uuid": "abc"})
    parsed = json.loads(line)
    assert "client" not in parsed


def test_encode_error_accepts_a_protocol_code_and_a_zikaron_code_alike() -> None:
    """Both error families frame through the same function — the distinction is the number,
    not a second code path."""
    protocol_line = json.loads(encode_error(1, ProtocolErrorCode.METHOD_NOT_FOUND, "nope"))
    app_line = json.loads(encode_error(1, -32020, "store busy"))
    assert protocol_line["error"]["code"] == -32601
    assert app_line["error"]["code"] == -32020


def test_the_two_error_ranges_never_overlap() -> None:
    """JSON-RPC 2.0 reserves -32768..-32000 for the protocol; Zikaron's own `ErrorCode` claims
    only -32099..-32000 of that band, per `zikaron.core.errors`."""
    for code in ProtocolErrorCode:
        assert not (APPLICATION_CODE_MIN <= code <= APPLICATION_CODE_MAX), (
            f"{code} collides with the application range"
        )
