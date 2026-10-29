"""`zikaron.hook.tripwire`: the one signal that this process misdetected its harness.

`design/harness.md` §"The nesting limit, stated rather than engineered around" is normative. Neither
harness fires a spawn or prompt hook for a subagent session, so a payload whose session id differs
from the environment's is a misdetection under either, and the tripwire records it under either.
"""

from pathlib import Path

import pytest

from zikaron.harness.spec import CLAUDE_CODE, KIRO, HarnessSpec
from zikaron.hook import push, spawn_warm, tripwire
from zikaron.service import paths


def _hook_log(scope_dir: Path) -> Path:
    return paths.hook_log_path(paths.store_dir(scope_dir))


class TestItFiresUnderEitherHarness:
    @pytest.mark.parametrize("spec", [KIRO, CLAUDE_CODE], ids=lambda spec: spec.harness.value)
    def test_a_divergent_push_writes_exactly_one_line(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, spec: HarnessSpec
    ) -> None:
        """Driven through the push path, so a harness-scoped early return anywhere on the way to
        the tripwire is seen."""
        if spec.marker_variable is not None:
            monkeypatch.setenv(spec.marker_variable, "1")
        monkeypatch.setenv(spec.session_variable, "the-enclosing-session")
        printed = push.run(
            scope_dir=tmp_path, payload_session_id="this-session", prompt="anything", pid=1
        )
        assert printed is None
        lines = _hook_log(tmp_path).read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        assert lines[0].endswith(tripwire.SESSION_ENV_MISMATCH)

    @pytest.mark.parametrize("spec", [KIRO, CLAUDE_CODE], ids=lambda spec: spec.harness.value)
    def test_a_divergent_start_writes_exactly_one_line(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, spec: HarnessSpec
    ) -> None:
        if spec.marker_variable is not None:
            monkeypatch.setenv(spec.marker_variable, "1")
        monkeypatch.setenv(spec.session_variable, "the-enclosing-session")
        printed = spawn_warm.run(scope_dir=tmp_path, payload_session_id="this-session")
        assert printed is None
        lines = _hook_log(tmp_path).read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        assert lines[0].endswith(tripwire.SESSION_ENV_MISMATCH)


class TestTheLineItself:
    def test_the_kind_is_the_only_content_besides_a_timestamp(self, tmp_path: Path) -> None:
        """`hook.log` carries a fixed failure kind and an optional wire error code, never prompt or
        memory content — a rule that only holds if every writer honors it. This one has no error
        code, so the line is a timestamp and a label.
        """
        tripwire.record_misdetection(scope_dir=tmp_path)
        line = _hook_log(tmp_path).read_text(encoding="utf-8").strip()
        timestamp, kind = line.split(" ")
        assert kind == tripwire.SESSION_ENV_MISMATCH
        assert timestamp.endswith("Z")

    def test_repeated_invocations_append_rather_than_replace(self, tmp_path: Path) -> None:
        """Each hook invocation is its own process, so two misdetected turns are two lines. A
        writer that truncated would leave an operator seeing only the most recent one.
        """
        tripwire.record_misdetection(scope_dir=tmp_path)
        tripwire.record_misdetection(scope_dir=tmp_path)
        assert len(_hook_log(tmp_path).read_text(encoding="utf-8").splitlines()) == 2


class TestItNeverRaises:
    """Called on a path that has already decided to print nothing and exit 0. A tripwire that turned
    a silent suppression into a crash would cost more than the signal it buys.
    """

    def test_an_unwritable_store_directory_is_absorbed(self, tmp_path: Path) -> None:
        store = tmp_path / ".zikaron"
        store.mkdir(mode=0o500)
        try:
            tripwire.record_misdetection(scope_dir=tmp_path)
        finally:
            store.chmod(0o700)

    def test_a_store_path_that_is_a_file_is_absorbed(self, tmp_path: Path) -> None:
        (tmp_path / ".zikaron").write_text("not a directory")
        tripwire.record_misdetection(scope_dir=tmp_path)

    def test_a_nonexistent_working_directory_is_absorbed(self, tmp_path: Path) -> None:
        tripwire.record_misdetection(scope_dir=tmp_path / "nowhere" / "deeper")
