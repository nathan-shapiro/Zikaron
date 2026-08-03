"""`zikaron.hook.envelope`: subagent suppression, the harness session id, and the `client` envelope.

`architecture.md` §"Subagent sessions" and §"The request envelope" are normative.
"""

import os

import pytest

from zikaron.hook.envelope import build_envelope, harness_session_id, is_subagent_session


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


class TestHarnessSessionId:
    def test_returns_the_environment_value_when_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("KIRO_SESSION_ID", "a-real-harness-id")
        assert harness_session_id() == "a-real-harness-id"

    def test_returns_none_when_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("KIRO_SESSION_ID", raising=False)
        assert harness_session_id() is None

    def test_a_zk_prefixed_value_is_treated_as_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`architecture.md`'s client contract: "a client that finds a `zk-`-prefixed value in
        `KIRO_SESSION_ID` must treat it as absent" — mirrors `zikaron.mcp.connection`'s identical
        rule so both clients honour the reserved namespace the same way."""
        monkeypatch.setenv("KIRO_SESSION_ID", "zk-00000000-0000-0000-0000-000000000000")
        assert harness_session_id() is None

    def test_a_value_merely_containing_zk_but_not_prefixed_by_it_is_not_treated_as_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("KIRO_SESSION_ID", "not-zk-but-contains-it")
        assert harness_session_id() == "not-zk-but-contains-it"


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
