"""`zikaron.service.params` — reading raw JSON `params` into typed values, uniformly across both
dispatch modules."""

import pytest

from zikaron.core.errors import ErrorCode, ZikaronError
from zikaron.service.envelope import ResolvedEnvelope
from zikaron.service.params import (
    call_params,
    optional_str,
    require_bool,
    require_int,
    require_object,
    require_str,
    require_uuid_list,
)


def test_call_params_carries_the_resolved_envelope_and_the_supplied_max_depth() -> None:
    envelope = ResolvedEnvelope(session_id="s1", kind="mcp", pid=1, op_id="op1")
    params = call_params(envelope, max_depth=32)
    assert params.session_id == "s1"
    assert params.client_kind == "mcp"
    assert params.op_id == "op1"
    assert params.max_depth == 32


def test_require_str_accepts_a_string() -> None:
    assert require_str({"gist": "hello"}, "gist") == "hello"


def test_require_str_rejects_a_missing_field() -> None:
    with pytest.raises(ZikaronError) as excinfo:
        require_str({}, "gist")
    assert excinfo.value.code is ErrorCode.BOUNDS
    assert excinfo.value.data["field"] == "gist"


def test_require_str_rejects_a_non_string() -> None:
    with pytest.raises(ZikaronError):
        require_str({"gist": 42}, "gist")


def test_optional_str_accepts_a_string() -> None:
    assert optional_str({"superseded_by": "u1"}, "superseded_by") == "u1"


def test_optional_str_accepts_absence_as_none() -> None:
    assert optional_str({}, "superseded_by") is None


def test_optional_str_accepts_explicit_null_as_none() -> None:
    assert optional_str({"superseded_by": None}, "superseded_by") is None


def test_optional_str_rejects_a_non_string_non_null_value() -> None:
    with pytest.raises(ZikaronError):
        optional_str({"superseded_by": 42}, "superseded_by")


def test_require_int_accepts_an_integer() -> None:
    assert require_int({"version": 3}, "version") == 3


def test_require_int_rejects_a_missing_field_with_no_default() -> None:
    with pytest.raises(ZikaronError):
        require_int({}, "version")


def test_require_int_falls_back_to_a_default_when_absent() -> None:
    assert require_int({}, "limit", default=5) == 5


def test_require_int_rejects_a_boolean_even_though_bool_is_an_int_subclass() -> None:
    with pytest.raises(ZikaronError):
        require_int({"version": True}, "version")


def test_require_int_rejects_a_string() -> None:
    with pytest.raises(ZikaronError):
        require_int({"version": "3"}, "version")


def test_require_bool_accepts_a_boolean() -> None:
    assert require_bool({"include_retired": True}, "include_retired", default=False) is True


def test_require_bool_falls_back_to_the_default_when_absent() -> None:
    assert require_bool({}, "include_retired", default=False) is False


def test_require_bool_rejects_a_non_boolean() -> None:
    with pytest.raises(ZikaronError):
        require_bool({"include_retired": "yes"}, "include_retired", default=False)


def test_require_uuid_list_accepts_a_list_of_strings() -> None:
    assert require_uuid_list({"uuids": ["a", "b"]}, "uuids") == ["a", "b"]


def test_require_uuid_list_accepts_an_empty_list() -> None:
    assert require_uuid_list({"uuids": []}, "uuids") == []


def test_require_uuid_list_rejects_a_non_list() -> None:
    with pytest.raises(ZikaronError):
        require_uuid_list({"uuids": "a"}, "uuids")


def test_require_uuid_list_rejects_a_list_with_a_non_string_element() -> None:
    with pytest.raises(ZikaronError):
        require_uuid_list({"uuids": ["a", 42]}, "uuids")


def test_require_object_accepts_a_dict() -> None:
    assert require_object({"target": {"uuid": "u1"}}, "target") == {"uuid": "u1"}


def test_require_object_rejects_a_non_dict() -> None:
    with pytest.raises(ZikaronError):
        require_object({"target": "not-an-object"}, "target")


def test_require_object_rejects_absence() -> None:
    with pytest.raises(ZikaronError):
        require_object({}, "target")
