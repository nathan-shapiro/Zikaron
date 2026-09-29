"""`zikaron.service.envelope` — the resolution preamble: shape, the label ladder, `label_source`."""

import pytest

from zikaron.core.errors import ErrorCode, ZikaronError
from zikaron.core.events import REQUEST_CLIENT_KINDS, ClientKind
from zikaron.service.envelope import ClientEnvelope, label_source, parse_envelope, resolve


def _raw(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {"session_id": "kiro-session-1", "kind": "mcp", "pid": 123}
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# parse_envelope — rung 1, shape only
# ---------------------------------------------------------------------------


def test_parses_a_well_formed_resolved_envelope() -> None:
    envelope = parse_envelope(_raw())
    assert envelope == ClientEnvelope(session_id="kiro-session-1", kind="mcp", pid=123, op_id=None)


def test_parses_a_well_formed_bootstrap_envelope() -> None:
    envelope = parse_envelope(_raw(session_id=None))
    assert envelope.session_id is None


def test_parses_a_supplied_op_id() -> None:
    envelope = parse_envelope(_raw(op_id="caller-supplied-1"))
    assert envelope.op_id == "caller-supplied-1"


@pytest.mark.parametrize("kind", sorted(REQUEST_CLIENT_KINDS))
def test_accepts_every_known_client_kind(kind: ClientKind) -> None:
    """Parametrized over the set the boundary reads, so the name stays true as members are added.

    A hand-written list of kinds is what made this test silently cover three of them once `cli`
    landed, and the same list would have gone on passing when `indexer` arrived — the one member no
    request may carry, which `test_rejects_the_indexer_kind_and_does_not_advertise_it` pins from the
    other side.
    """
    assert parse_envelope(_raw(kind=kind)).kind == kind


def test_rejects_a_non_object_client() -> None:
    with pytest.raises(ZikaronError) as excinfo:
        parse_envelope("not an object")
    assert excinfo.value.code is ErrorCode.BOUNDS
    assert excinfo.value.data["field"] == "client"


def test_rejects_a_session_id_that_is_neither_string_nor_null() -> None:
    with pytest.raises(ZikaronError) as excinfo:
        parse_envelope(_raw(session_id=42))
    assert excinfo.value.code is ErrorCode.BOUNDS
    assert excinfo.value.data["field"] == "client.session_id"


def test_rejects_a_missing_kind() -> None:
    raw = _raw()
    del raw["kind"]
    with pytest.raises(ZikaronError) as excinfo:
        parse_envelope(raw)
    assert excinfo.value.data["field"] == "client.kind"


def test_rejects_an_unknown_kind() -> None:
    with pytest.raises(ZikaronError) as excinfo:
        parse_envelope(_raw(kind="primary-agent"))
    assert excinfo.value.data["field"] == "client.kind"


def test_rejects_the_indexer_kind_and_does_not_advertise_it() -> None:
    """The store's `CHECK` admits one member more than the wire does, and this is that gap.

    `client_kind = 'indexer'` exists for a spawned build, which is no client call at all. Deriving
    the accepted set from `ClientKind` would accept it here and file a client's writes under the
    kind reserved for a build — excluded from the drop-rate query, ignored by linkage, advertised in
    this very payload's `limit` as a value to send. So the `limit` is asserted too: a refusal that
    names the value it just refused is an invitation to retry with it.
    """
    with pytest.raises(ZikaronError) as excinfo:
        parse_envelope(_raw(kind=ClientKind.INDEXER.value))
    assert excinfo.value.code is ErrorCode.BOUNDS
    assert excinfo.value.data["field"] == "client.kind"
    offered = excinfo.value.data["limit"]
    assert isinstance(offered, list)
    assert ClientKind.INDEXER.value not in offered
    # The four a client may send are still offered, so this is a narrowing rather than a break.
    assert sorted(str(kind) for kind in REQUEST_CLIENT_KINDS) == offered


def test_rejects_a_missing_pid() -> None:
    raw = _raw()
    del raw["pid"]
    with pytest.raises(ZikaronError) as excinfo:
        parse_envelope(raw)
    assert excinfo.value.code is ErrorCode.BOUNDS
    assert excinfo.value.data["field"] == "client.pid"


def test_rejects_a_zero_pid() -> None:
    with pytest.raises(ZikaronError) as excinfo:
        parse_envelope(_raw(pid=0))
    assert excinfo.value.data["field"] == "client.pid"


def test_accepts_the_smallest_legal_pid() -> None:
    """`pid=1` is the boundary a `< 1` check and an `<= 1` check disagree on — pid 1 is a real,
    legal process id (traditionally `init`), and `architecture.md` says only that `pid` must be
    positive, not that it must exceed 1."""
    assert parse_envelope(_raw(pid=1)).pid == 1


def test_rejects_a_negative_pid() -> None:
    with pytest.raises(ZikaronError) as excinfo:
        parse_envelope(_raw(pid=-5))
    assert excinfo.value.data["field"] == "client.pid"


def test_rejects_a_non_integer_pid() -> None:
    with pytest.raises(ZikaronError) as excinfo:
        parse_envelope(_raw(pid="123"))
    assert excinfo.value.data["field"] == "client.pid"


def test_rejects_a_boolean_pid_even_though_bool_is_an_int_subclass() -> None:
    """A request sending `true` for `pid` must not silently become pid 1 — the exact exactness
    `config.keys.ConfigKey.accepts` enforces for a configured value, applied to a wire value."""
    with pytest.raises(ZikaronError) as excinfo:
        parse_envelope(_raw(pid=True))
    assert excinfo.value.data["field"] == "client.pid"


def test_rejects_a_non_string_op_id() -> None:
    with pytest.raises(ZikaronError) as excinfo:
        parse_envelope(_raw(op_id=42))
    assert excinfo.value.data["field"] == "client.op_id"


# ---------------------------------------------------------------------------
# resolve — rung 2, the label ladder
# ---------------------------------------------------------------------------


def test_a_conforming_session_id_passes_through_unchanged() -> None:
    envelope = ClientEnvelope(session_id="kiro-session-1", kind="mcp", pid=1, op_id=None)
    resolved = resolve(envelope)
    assert resolved.session_id == "kiro-session-1"


def test_a_null_session_id_is_minted_in_the_reserved_namespace() -> None:
    envelope = ClientEnvelope(session_id=None, kind="mcp", pid=1, op_id=None)
    resolved = resolve(envelope)
    assert resolved.session_id.startswith("zk-")


def test_two_bootstrap_calls_mint_two_distinct_labels() -> None:
    envelope = ClientEnvelope(session_id=None, kind="mcp", pid=1, op_id=None)
    first = resolve(envelope)
    second = resolve(envelope)
    assert first.session_id != second.session_id


def test_an_empty_session_id_is_treated_as_malformed_and_minted() -> None:
    """`architecture.md`: "a malformed label carries no information" — refused nowhere, minted."""
    envelope = ClientEnvelope(session_id="", kind="mcp", pid=1, op_id=None)
    resolved = resolve(envelope)
    assert resolved.session_id.startswith("zk-")


def test_a_too_long_session_id_is_treated_as_malformed_and_minted() -> None:
    envelope = ClientEnvelope(session_id="x" * 129, kind="mcp", pid=1, op_id=None)
    resolved = resolve(envelope)
    assert resolved.session_id.startswith("zk-")


def test_a_session_id_of_exactly_128_chars_conforms() -> None:
    label = "x" * 128
    envelope = ClientEnvelope(session_id=label, kind="mcp", pid=1, op_id=None)
    resolved = resolve(envelope)
    assert resolved.session_id == label


def test_a_session_id_containing_a_control_character_is_treated_as_malformed_and_minted() -> None:
    envelope = ClientEnvelope(session_id="kiro\x00session", kind="mcp", pid=1, op_id=None)
    resolved = resolve(envelope)
    assert resolved.session_id.startswith("zk-")


def test_a_session_id_containing_del_is_treated_as_malformed_and_minted() -> None:
    envelope = ClientEnvelope(session_id="kiro\x7fsession", kind="mcp", pid=1, op_id=None)
    resolved = resolve(envelope)
    assert resolved.session_id.startswith("zk-")


def test_a_supplied_op_id_is_kept() -> None:
    envelope = ClientEnvelope(session_id="s1", kind="mcp", pid=1, op_id="caller-1")
    resolved = resolve(envelope)
    assert resolved.op_id == "caller-1"


def test_an_absent_op_id_is_minted() -> None:
    envelope = ClientEnvelope(session_id="s1", kind="mcp", pid=1, op_id=None)
    resolved = resolve(envelope)
    assert resolved.op_id != ""


def test_pid_and_kind_pass_through_resolution_unchanged() -> None:
    envelope = ClientEnvelope(session_id="s1", kind="consolidator", pid=999, op_id=None)
    resolved = resolve(envelope)
    assert resolved.pid == 999
    assert resolved.kind == "consolidator"


# ---------------------------------------------------------------------------
# label_source — a pure function of the label alone
# ---------------------------------------------------------------------------


def test_label_source_is_minted_for_the_reserved_prefix() -> None:
    assert label_source("zk-11111111-1111-1111-1111-111111111111") == "minted"


def test_label_source_is_harness_for_anything_else() -> None:
    assert label_source("kiro-session-1") == "harness"


def test_label_source_requires_the_prefix_at_the_start_not_merely_somewhere_in_the_label() -> None:
    """A harness id that happens to *contain* `zk-` — a project or branch name embedding it, for
    instance — must not be misclassified `minted`. The prefix is reserved as a *prefix*
    (`architecture.md`: the service recognizes its own label coming back), not as a substring the
    label may contain anywhere."""
    assert label_source("my-project-zk-thing") == "harness"


def test_label_source_agrees_with_what_resolve_actually_produces() -> None:
    """The two must never disagree: `label_source` exists so a stored label can be classified
    later, and it has to classify the exact labels `resolve` mints, not merely the reserved
    prefix in the abstract."""
    minted = resolve(ClientEnvelope(session_id=None, kind="mcp", pid=1, op_id=None))
    assert label_source(minted.session_id) == "minted"

    harness = resolve(ClientEnvelope(session_id="kiro-1", kind="mcp", pid=1, op_id=None))
    assert label_source(harness.session_id) == "harness"
