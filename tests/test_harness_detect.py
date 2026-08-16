"""`zikaron.harness.detect`: which harness this process is under, and what its session label is.

`design/harness.md` §"Detection, session identity, and the nesting limit" is normative. These tests
were previously part of `test_hook_envelope.py`, when the hook owned a hard-coded variable name;
they moved with the rule.
"""

from pathlib import Path

import pytest

from zikaron.harness import detect
from zikaron.harness.spec import CLAUDE_CODE, KIRO, SPECS, Harness, HarnessSpec
from zikaron.mcp.connection import ServiceConnection
from zikaron.service import envelope as service_envelope

#: Built from the service's own prefix rather than spelled out, so this fixture cannot drift into
#: agreeing with a stale copy in the seam while both disagree with the service.
_MINTED = f"{service_envelope._MINTED_PREFIX}00000000-0000-0000-0000-000000000000"


class TestDetection:
    def test_no_marker_means_the_unmarked_harness(self) -> None:
        assert detect.current_harness() is Harness.KIRO
        assert detect.current_spec() is KIRO

    def test_a_present_marker_selects_its_harness(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CLAUDECODE", "1")
        assert detect.current_harness() is Harness.CLAUDE_CODE
        assert detect.current_spec() is CLAUDE_CODE

    def test_an_empty_marker_does_not_count_as_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A marker answers a yes/no question, and an empty value is no evidence that the harness
        spawned anything. Detection is the decision every other harness-varying value hangs off, so
        it takes the conservative reading rather than treating "set to nothing" as "set".
        """
        monkeypatch.setenv("CLAUDECODE", "")
        assert detect.current_harness() is Harness.KIRO

    def test_the_fallback_is_derived_from_the_table_rather_than_named(self) -> None:
        """Exactly one spec may be unmarked. Two would make detection ambiguous when no marker is
        set, and none would make it undefined — so the fallback is computed from the table and this
        asserts the table still supports it.
        """
        unmarked = [spec.harness for spec in SPECS.values() if spec.marker_variable is None]
        assert unmarked == [detect.FALLBACK]

    def test_a_marker_is_never_confused_with_a_session_variable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Setting only the session variable of a marked harness must not detect that harness: the
        session variable is inherited by ordinary child processes for legitimate reasons, and
        detection deliberately consults one designated marker rather than any evidence it can find.
        """
        monkeypatch.setenv(CLAUDE_CODE.session_variable, "some-session")
        assert detect.current_harness() is Harness.KIRO


class TestSessionLabel:
    @pytest.mark.parametrize("spec", [KIRO, CLAUDE_CODE], ids=lambda spec: spec.harness.value)
    def test_returns_the_value_of_this_harnesss_own_variable(
        self, monkeypatch: pytest.MonkeyPatch, spec: HarnessSpec
    ) -> None:
        monkeypatch.setenv(spec.session_variable, "a-real-harness-id")
        assert detect.session_label(spec) == "a-real-harness-id"

    @pytest.mark.parametrize("spec", [KIRO, CLAUDE_CODE], ids=lambda spec: spec.harness.value)
    def test_returns_none_when_absent(self, spec: HarnessSpec) -> None:
        assert detect.session_label(spec) is None

    @pytest.mark.parametrize("spec", [KIRO, CLAUDE_CODE], ids=lambda spec: spec.harness.value)
    def test_a_minted_value_is_treated_as_absent(
        self, monkeypatch: pytest.MonkeyPatch, spec: HarnessSpec
    ) -> None:
        """The reserved namespace check applies to whichever variable wins, so no harness can claim
        a service-minted label under either name.
        """
        monkeypatch.setenv(spec.session_variable, _MINTED)
        assert detect.session_label(spec) is None

    def test_the_seams_minted_prefix_is_the_services_own(self) -> None:
        """A guarded copy, like every other cross-boundary copy here. The prefix is how the service
        tells its own minted labels from a harness's, and if it ever moved, an unguarded seam would
        go on forwarding service-minted labels as harness ones — the exact case the check exists to
        refuse — while agreeing perfectly with its own tests.
        """
        assert detect._MINTED_PREFIX == service_envelope._MINTED_PREFIX

    @pytest.mark.parametrize("spec", [KIRO, CLAUDE_CODE], ids=lambda spec: spec.harness.value)
    def test_an_empty_value_is_absence_not_a_label(
        self, monkeypatch: pytest.MonkeyPatch, spec: HarnessSpec
    ) -> None:
        """An exported-but-empty variable is what a wrapper script leaves behind, and it must mean
        the same thing here as it does at the service, which treats a zero-length label as no label.

        The consequence of disagreeing is not a rejected request — it never reaches one. The
        suppression check compares this value to the payload's session id, so a forwarded `""`
        differs from every real id and silently suppresses every top-level push.
        """
        monkeypatch.setenv(spec.session_variable, "")
        assert detect.session_label(spec) is None

    @pytest.mark.parametrize("spec", [KIRO, CLAUDE_CODE], ids=lambda spec: spec.harness.value)
    def test_a_value_merely_containing_the_prefix_is_not_treated_as_absent(
        self, monkeypatch: pytest.MonkeyPatch, spec: HarnessSpec
    ) -> None:
        monkeypatch.setenv(spec.session_variable, "not-zk-but-contains-it")
        assert detect.session_label(spec) == "not-zk-but-contains-it"

    def test_each_harness_reads_only_its_own_variable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The rename is the whole port. A harness reading the other's variable would resolve a
        label that looks valid and belongs to a different session entirely.
        """
        monkeypatch.setenv(KIRO.session_variable, "kiro-session")
        monkeypatch.setenv(CLAUDE_CODE.session_variable, "claude-session")
        assert detect.session_label(KIRO) == "kiro-session"
        assert detect.session_label(CLAUDE_CODE) == "claude-session"

    def test_the_other_harnesss_variable_alone_resolves_to_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(KIRO.session_variable, "kiro-session")
        assert detect.session_label(CLAUDE_CODE) is None


class TestBothClientsResolveTheSameLabel:
    """The property the seam exists to guarantee, asserted across the two clients rather than
    within one.

    Before the seam, each client carried its own copy of the ladder and its own hard-coded variable
    name. A rename applied to one and not the other would leave a hook and an MCP server in the same
    session speaking under different labels — which silently breaks linked sessions, both
    cross-client signals, and the per-session recall instrument, none of which fail loudly.
    """

    @pytest.mark.parametrize("spec", [KIRO, CLAUDE_CODE], ids=lambda spec: spec.harness.value)
    def test_the_mcp_client_adopts_exactly_what_the_seam_resolves(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, spec: HarnessSpec
    ) -> None:
        if spec.marker_variable is not None:
            monkeypatch.setenv(spec.marker_variable, "1")
        monkeypatch.setenv(spec.session_variable, "shared-session-label")
        connection = ServiceConnection(tmp_path)
        assert connection.envelope(kind="mcp").session_id == "shared-session-label"
        assert connection.envelope(kind="mcp").session_id == detect.session_label(
            detect.current_spec()
        )

    @pytest.mark.parametrize("spec", [KIRO, CLAUDE_CODE], ids=lambda spec: spec.harness.value)
    def test_both_fall_to_the_bootstrap_form_when_no_session_variable_is_present(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, spec: HarnessSpec
    ) -> None:
        """`None` here means the bootstrap form — send null, adopt the label the service mints —
        and both clients must reach it together, since one bootstrapping while the other forwards a
        real id is exactly the split this guards.
        """
        if spec.marker_variable is not None:
            monkeypatch.setenv(spec.marker_variable, "1")
        assert detect.session_label(detect.current_spec()) is None
        assert ServiceConnection(tmp_path).envelope(kind="mcp").session_id is None
