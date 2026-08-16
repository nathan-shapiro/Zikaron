"""`zikaron.hook.envelope`: subagent suppression and the `client` envelope.

`architecture.md` §"Subagent sessions" and §"The request envelope" are normative. Resolving the
session label itself is the harness seam's job, not this module's — those tests live in
`test_harness_detect.py`, with the variable names they read.
"""

import dataclasses
import os

from zikaron.core.events import ClientKind
from zikaron.hook.envelope import (
    CLIENT_KIND,
    HookEnvelope,
    build_envelope,
    is_subagent_session,
)
from zikaron.service.envelope import ClientEnvelope, parse_envelope


class TestIsSubagentSession:
    def test_matching_ids_is_not_a_subagent_session(self) -> None:
        assert not is_subagent_session(env_session_id="abc", payload_session_id="abc")

    def test_differing_ids_is_a_subagent_session(self) -> None:
        """The exact case the probe measured: a subagent's payload carries its own session id
        while `KIRO_SESSION_ID` still holds the top-level one."""
        assert is_subagent_session(env_session_id="top-level", payload_session_id="subagent-own")

    def test_env_absent_is_never_a_subagent_session_regardless_of_payload(self) -> None:
        """`architecture.md`: "when `KIRO_SESSION_ID` is absent entirely, it proceeds normally" —
        unconditional on the payload's own value, including a payload that happens to carry some
        session id that would differ from anything."""
        assert not is_subagent_session(env_session_id=None, payload_session_id="anything")
        assert not is_subagent_session(env_session_id=None, payload_session_id=None)

    def test_a_non_string_payload_session_id_never_matches_a_present_env_value(self) -> None:
        """A malformed payload (a payload session id that is not a string, or entirely absent —
        modelled here as `None`, the value `dict.get` returns for a missing key) differs from any
        real string `env_session_id`, so this reports a subagent session — the conservative
        direction, since suppressing a push costs a convenience recoverable by asking, per
        `architecture.md`'s own stated asymmetry."""
        assert is_subagent_session(env_session_id="top-level", payload_session_id=None)
        assert is_subagent_session(env_session_id="top-level", payload_session_id=42)

    def test_env_present_and_payload_absent_is_a_subagent_session(self) -> None:
        assert is_subagent_session(env_session_id="top-level", payload_session_id=None)


class TestBuildEnvelope:
    def test_carries_the_given_session_id_kind_hook_and_pid(self) -> None:
        envelope = build_envelope(session_id="a-session", pid=4242)
        assert envelope.session_id == "a-session"
        assert envelope.kind == "hook"
        assert envelope.pid == 4242
        assert envelope.op_id is None

    def test_a_null_session_id_is_the_bootstrap_form(self) -> None:
        envelope = build_envelope(session_id=None, pid=1)
        assert envelope.session_id is None

    def test_pid_is_this_processs_own_when_given_its_own_pid(self) -> None:
        envelope = build_envelope(session_id="s", pid=os.getpid())
        assert envelope.pid == os.getpid()


class TestEnvelopeContractDoesNotDrift:
    """The hook states the `client` envelope's four fields and its `kind` literal locally rather
    than importing `zikaron.service.envelope.ClientEnvelope` and `zikaron.core.events.ClientKind`,
    because importing either costs ~30 ms of a ~48 ms per-user-message process
    (`zikaron/hook/envelope.py` module docstring). These are the guards that make the copy safe.

    This test file pays the import cost the hook refuses to; that asymmetry is the whole point.
    """

    def test_kind_literal_equals_the_client_kind_enums_own_value(self) -> None:
        assert ClientKind.HOOK.value == CLIENT_KIND

    def test_field_names_and_order_match_the_service_side_dataclass(self) -> None:
        service_side = tuple(f.name for f in dataclasses.fields(ClientEnvelope))
        assert HookEnvelope._fields == service_side

    def test_the_wire_object_carries_exactly_those_names(self) -> None:
        """`as_client_object()` is the one place the wire spelling is written, so a field renamed on
        the service side without renaming it here has to fail somewhere — here.
        """
        wire = build_envelope(session_id="s", pid=1).as_client_object()
        assert set(wire) == {f.name for f in dataclasses.fields(ClientEnvelope)}

    def test_the_wire_object_round_trips_through_the_services_own_parser(self) -> None:
        """Shape agreement is not the same claim as acceptance: this asserts the service's own
        envelope parser accepts what the hook actually sends, so the two sides agree about types
        and optionality as well as about names.
        """
        parsed = parse_envelope(build_envelope(session_id="a-session", pid=4242).as_client_object())
        assert parsed.session_id == "a-session"
        assert parsed.kind == CLIENT_KIND
        assert parsed.pid == 4242
        assert parsed.op_id is None
