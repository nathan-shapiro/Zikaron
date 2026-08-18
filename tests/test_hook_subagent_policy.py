"""`zikaron.hook.subagent_policy`: the write policy delivered to a subagent, and the one exclusion.

`design/harness.md` §Subagents is normative. The spawn trigger fires once per session, so without
this path a subagent inherits the memory tools having never seen the write policy — and the
exclusion is exact here rather than a blanket suppression, because this payload carries the agent
identity the other harness's cannot express.
"""

from pathlib import Path

import pytest

from zikaron.hook import subagent_policy
from zikaron.hook.write_policy import (
    OVERRIDE_EMPTY,
    WRITE_POLICY_PROMPT,
)
from zikaron.install.entries import CONSOLIDATOR_AGENT_NAME
from zikaron.service import paths


class TestTheConsolidatorIsExcluded:
    def test_the_consolidator_receives_nothing(self, tmp_path: Path) -> None:
        """Its policy is its own system prompt. Handing it the primary agent's write instructions
        on top would be a second, conflicting set of directions for the same turn.
        """
        assert subagent_policy.run(scope_dir=tmp_path, agent_type=CONSOLIDATOR_AGENT_NAME) is None

    def test_every_other_agent_type_receives_the_policy(self, tmp_path: Path) -> None:
        assert subagent_policy.run(scope_dir=tmp_path, agent_type="some-other-agent") is not None

    def test_the_guarded_copy_of_the_agent_type_matches_the_installers_own_declaration(
        self,
    ) -> None:
        """The canonical name lives with the installer that writes the agent config; the hook keeps
        a copy because importing the installer would pull it onto a path measured in milliseconds.
        Two copies of one name is the drift this corpus keeps finding, so the copy is guarded — this
        test pays the import cost, the hook does not.
        """
        assert subagent_policy.CONSOLIDATOR_AGENT_TYPE == CONSOLIDATOR_AGENT_NAME


class TestAnUnrecognisableAgentTypeStillReceivesThePolicy:
    """The payload is untrusted JSON, and the safe direction to be wrong in is delivering a policy
    that was not needed rather than withholding one that was: an agent holding the memory tools and
    never told the write policy is the exact failure this path exists to prevent.
    """

    @pytest.mark.parametrize("agent_type", [None, 42, [], {}, "", "unknown-future-agent"])
    def test_anything_that_is_not_exactly_the_consolidator_gets_the_policy(
        self, tmp_path: Path, agent_type: object
    ) -> None:
        assert subagent_policy.run(scope_dir=tmp_path, agent_type=agent_type) == WRITE_POLICY_PROMPT

    def test_a_near_miss_on_the_consolidators_name_is_not_the_consolidator(
        self, tmp_path: Path
    ) -> None:
        """An exact comparison, not a prefix or a substring: an agent named for the consolidator
        without being it must not silently lose its policy.
        """
        near = f"{CONSOLIDATOR_AGENT_NAME}-experimental"
        assert subagent_policy.run(scope_dir=tmp_path, agent_type=near) == WRITE_POLICY_PROMPT


class TestTheOverrideIsHonouredHereToo:
    """An operator experimenting with the policy text should see it in both places it is injected.
    A subagent path that silently served the shipped constant would make the override look
    inconsistent for reasons nothing reports.
    """

    def test_a_readable_override_is_used(self, tmp_path: Path) -> None:
        store = tmp_path / ".zikaron"
        store.mkdir(mode=0o700)
        store.chmod(0o700)
        (store / "write-policy.md").write_text("## Mine\n\nRecord less.\n", encoding="utf-8")
        assert subagent_policy.run(scope_dir=tmp_path, agent_type="some-agent") == (
            "## Mine\n\nRecord less.\n"
        )

    def test_a_blank_override_falls_back_and_is_logged(self, tmp_path: Path) -> None:
        store = tmp_path / ".zikaron"
        store.mkdir(mode=0o700)
        store.chmod(0o700)
        (store / "write-policy.md").write_text("   \n", encoding="utf-8")
        assert (
            subagent_policy.run(scope_dir=tmp_path, agent_type="some-agent") == WRITE_POLICY_PROMPT
        )
        log = paths.hook_log_path(store).read_text(encoding="utf-8")
        assert OVERRIDE_EMPTY in log


class TestItNeverRaises:
    def test_a_nonexistent_working_directory_still_yields_the_shipped_policy(
        self, tmp_path: Path
    ) -> None:
        """The caller's contract is to emit a policy; no failure beneath may cost it that."""
        missing = tmp_path / "nowhere" / "deeper"
        assert (
            subagent_policy.run(scope_dir=missing, agent_type="some-agent") == WRITE_POLICY_PROMPT
        )

    def test_a_store_path_that_is_a_file_still_yields_the_shipped_policy(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / ".zikaron").write_text("not a directory")
        assert (
            subagent_policy.run(scope_dir=tmp_path, agent_type="some-agent") == WRITE_POLICY_PROMPT
        )
