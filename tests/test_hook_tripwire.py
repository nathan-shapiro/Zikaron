"""`zikaron.hook.tripwire`: the one signal that this process misdetected its harness.

`design/harness.md` §"The nesting limit, stated rather than engineered around" is normative. The
scoping is the whole content of these tests: the predicate is identical to the ordinary subagent
check, so an unscoped tripwire would fire on every subagent turn under the harness that fires its
hooks for subagent sessions, drowning the signal it exists to raise.
"""

from pathlib import Path

import pytest

from zikaron.harness.spec import CLAUDE_CODE, KIRO, SPECS, HarnessSpec
from zikaron.hook import tripwire
from zikaron.service import paths


def _hook_log(scope_dir: Path) -> Path:
    return paths.hook_log_path(paths.store_dir(scope_dir))


class TestScoping:
    def test_a_harness_that_fires_hooks_for_subagent_sessions_writes_nothing(
        self, tmp_path: Path
    ) -> None:
        """The routine case, not an anomaly: under this harness a payload whose session id differs
        from the environment's *is* the subagent case, several times per session. A line here would
        be noise in a log whose value is a closed vocabulary of genuine failures.
        """
        tripwire.record_if_misdetected(spec=KIRO, scope_dir=tmp_path)
        assert not _hook_log(tmp_path).exists()

    def test_a_harness_where_the_ids_are_invariant_writes_exactly_one_line(
        self, tmp_path: Path
    ) -> None:
        tripwire.record_if_misdetected(spec=CLAUDE_CODE, scope_dir=tmp_path)
        lines = _hook_log(tmp_path).read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        assert lines[0].endswith(tripwire.SESSION_ENV_MISMATCH)

    def test_the_scoping_reads_the_table_rather_than_naming_a_harness(self) -> None:
        """The condition is a field on the spec, so adding a third harness cannot silently inherit
        either behaviour — it has to state which one it is.
        """
        for spec in SPECS.values():
            assert isinstance(spec.fires_hooks_for_subagent_sessions, bool)
        assert KIRO.fires_hooks_for_subagent_sessions
        assert not CLAUDE_CODE.fires_hooks_for_subagent_sessions


class TestTheLineItself:
    def test_the_kind_is_the_only_content_besides_a_timestamp(self, tmp_path: Path) -> None:
        """`hook.log` carries a fixed failure kind and an optional wire error code, never prompt or
        memory content — a rule that only holds if every writer honours it. This one has no error
        code, so the line is a timestamp and a label.
        """
        tripwire.record_if_misdetected(spec=CLAUDE_CODE, scope_dir=tmp_path)
        line = _hook_log(tmp_path).read_text(encoding="utf-8").strip()
        timestamp, kind = line.split(" ")
        assert kind == tripwire.SESSION_ENV_MISMATCH
        assert timestamp.endswith("Z")

    def test_repeated_invocations_append_rather_than_replace(self, tmp_path: Path) -> None:
        """Each hook invocation is its own process, so two misdetected turns are two lines. A
        writer that truncated would leave an operator seeing only the most recent one.
        """
        tripwire.record_if_misdetected(spec=CLAUDE_CODE, scope_dir=tmp_path)
        tripwire.record_if_misdetected(spec=CLAUDE_CODE, scope_dir=tmp_path)
        assert len(_hook_log(tmp_path).read_text(encoding="utf-8").splitlines()) == 2


class TestItNeverRaises:
    """Called on a path that has already decided to print nothing and exit 0. A tripwire that turned
    a silent suppression into a crash would cost more than the signal it buys.
    """

    def test_an_unwritable_store_directory_is_absorbed(self, tmp_path: Path) -> None:
        store = tmp_path / ".zikaron"
        store.mkdir(mode=0o500)
        try:
            tripwire.record_if_misdetected(spec=CLAUDE_CODE, scope_dir=tmp_path)
        finally:
            store.chmod(0o700)

    def test_a_store_path_that_is_a_file_is_absorbed(self, tmp_path: Path) -> None:
        (tmp_path / ".zikaron").write_text("not a directory")
        tripwire.record_if_misdetected(spec=CLAUDE_CODE, scope_dir=tmp_path)

    @pytest.mark.parametrize("spec", [KIRO, CLAUDE_CODE], ids=lambda spec: spec.harness.value)
    def test_a_nonexistent_working_directory_is_absorbed(
        self, tmp_path: Path, spec: HarnessSpec
    ) -> None:
        tripwire.record_if_misdetected(spec=spec, scope_dir=tmp_path / "nowhere" / "deeper")
