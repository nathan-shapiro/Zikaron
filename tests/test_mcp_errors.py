"""`zikaron.mcp.errors.response_to_tool_result` — a conflict shape is a success, never an error."""

import pytest

from zikaron.mcp.errors import ServiceRejectionError, response_to_tool_result


def test_a_plain_success_result_is_returned_unchanged() -> None:
    response: dict[str, object] = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"uuid": "u1", "version": 1},
    }
    assert response_to_tool_result(response) == {"uuid": "u1", "version": 1}


def test_a_bare_list_result_is_returned_unchanged() -> None:
    """`zikaron_search`'s own documented shape is a bare list, per `architecture.md` — this must
    not be mistaken for a malformed response merely because it is not a `dict`."""
    response: dict[str, object] = {"jsonrpc": "2.0", "id": 1, "result": [{"uuid": "u1"}]}
    assert response_to_tool_result(response) == [{"uuid": "u1"}]


def test_a_conflict_shape_is_returned_as_a_success_not_raised() -> None:
    """The key fact this module exists to encode: `{conflict: true, current: {...}}` is a
    JSON-RPC **result**, not an **error** — `core.write.tools.Amended | Conflict` never raises for
    a conflict, so this function must return it exactly like any other successful shape rather
    than treating the word "conflict" in the payload as a signal to raise.
    """
    conflict_payload = {"conflict": True, "current": {"uuid": "u1", "version": 3}}
    response: dict[str, object] = {"jsonrpc": "2.0", "id": 1, "result": conflict_payload}
    assert response_to_tool_result(response) == conflict_payload


def test_an_error_object_raises_service_rejection_error_carrying_code_and_data() -> None:
    response: dict[str, object] = {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {"code": -32020, "message": "store busy", "data": {"verb": "remember"}},
    }
    with pytest.raises(ServiceRejectionError) as excinfo:
        response_to_tool_result(response)
    assert excinfo.value.code == -32020
    assert excinfo.value.data == {"verb": "remember"}


def test_an_error_object_with_no_data_field_raises_with_data_none() -> None:
    """`data` is optional on the wire (`rpc.encode_error`'s own `data: dict | None = None`), so
    an error with no payload beyond code/message must not be treated as malformed."""
    response: dict[str, object] = {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {"code": -32000, "message": "no memory with that uuid"},
    }
    with pytest.raises(ServiceRejectionError) as excinfo:
        response_to_tool_result(response)
    assert excinfo.value.code == -32000
    assert excinfo.value.data is None


@pytest.mark.parametrize(
    "response",
    [
        {"jsonrpc": "2.0", "id": 1},
        {"jsonrpc": "2.0", "id": 1, "error": "not an object"},
        {"jsonrpc": "2.0", "id": 1, "error": {"message": "no code"}},
        {"jsonrpc": "2.0", "id": 1, "error": {"code": -32000}},
        {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32000, "message": "x", "data": "not a dict"},
        },
    ],
)
def test_a_malformed_response_raises_type_error(response: dict[str, object]) -> None:
    with pytest.raises(TypeError):
        response_to_tool_result(response)
