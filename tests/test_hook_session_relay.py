"""`zikaron.hook.session_relay`: the hook leaving its session's label for the MCP client that shares
its parent.

`design/harness.md` §"The session relay" is normative. kiro's session variable reaches hooks and no
MCP server, so the hook writes the payload's `session_id` to a file named for its own parent, and
the MCP client — a child of the same agent server — reads it there.
"""

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from zikaron.harness import detect
from zikaron.harness.spec import CLAUDE_CODE, KIRO
from zikaron.hook import main as main_module
from zikaron.hook import push, session_relay, spawn_warm
from zikaron.hook.components import Components


def _relay_file() -> Path:
    return detect.relay_file(session_relay.relay_dir(), os.getppid())


def _dead_pid() -> int:
    """A pid that existed a moment ago and does not now."""
    child = subprocess.Popen([sys.executable, "-c", ""])
    child.wait()
    return child.pid


def _run(payload: dict[str, object], monkeypatch: pytest.MonkeyPatch) -> str:
    """`main._run` against `payload`, returning what it wrote to stdout."""
    written = io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    monkeypatch.setattr(sys, "stdout", written)
    main_module._run(Components.MEMORY)
    return written.getvalue()


class TestWhatIsWritten:
    def test_the_payloads_session_id_is_left_for_the_parent(self) -> None:
        session_relay.record(KIRO, "sess_one", sweep=False)
        assert _relay_file().read_text(encoding="utf-8") == "sess_one"

    def test_the_last_writer_wins(self) -> None:
        session_relay.record(KIRO, "sess_one", sweep=False)
        session_relay.record(KIRO, "sess_two", sweep=False)
        assert _relay_file().read_text(encoding="utf-8") == "sess_two"

    def test_nothing_is_written_under_a_harness_whose_variable_reaches_both(self) -> None:
        session_relay.record(CLAUDE_CODE, "sess_one", sweep=True)
        assert not session_relay.relay_dir().exists()

    @pytest.mark.parametrize("malformed", [None, "", 42, ["sess_one"]])
    def test_a_malformed_session_id_leaves_the_previous_label(self, malformed: object) -> None:
        """The payload is untrusted JSON, so only a non-empty string replaces a label."""
        session_relay.record(KIRO, "sess_one", sweep=False)
        session_relay.record(KIRO, malformed, sweep=False)
        assert _relay_file().read_text(encoding="utf-8") == "sess_one"

    def test_the_directory_and_the_file_are_private(self) -> None:
        session_relay.record(KIRO, "sess_one", sweep=False)
        assert session_relay.relay_dir().stat().st_mode & 0o777 == 0o700
        assert _relay_file().stat().st_mode & 0o777 == 0o600


class TestItIsAtomicAndBestEffort:
    def test_a_write_that_fails_halfway_leaves_the_old_label_whole(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session_relay.record(KIRO, "sess_the-old-label", sweep=False)
        real_write = os.write

        def write_one_byte_then_fail(descriptor: int, data: bytes | memoryview) -> int:
            real_write(descriptor, bytes(data[:1]))
            raise OSError("the disk filled")

        monkeypatch.setattr(os, "write", write_one_byte_then_fail)
        session_relay.record(KIRO, "sess_the-new-label", sweep=False)
        monkeypatch.undo()
        assert _relay_file().read_text(encoding="utf-8") == "sess_the-old-label"
        assert sorted(entry.name for entry in session_relay.relay_dir().iterdir()) == [
            _relay_file().name
        ]

    def test_a_killed_hooks_temporary_under_this_name_does_not_block_the_write(self) -> None:
        """A hook killed mid-write leaves its temporary, named for its own pid; a later hook that
        draws the same pid before a sweep must still write."""
        session_relay.record(KIRO, "sess_the-old-label", sweep=False)
        stale = _relay_file().with_name(f"{_relay_file().name}.{os.getpid()}.tmp")
        stale.write_text("sess_half")
        session_relay.record(KIRO, "sess_the-new-label", sweep=False)
        assert _relay_file().read_text(encoding="utf-8") == "sess_the-new-label"
        assert not stale.exists()

    def test_a_write_that_makes_no_progress_is_abandoned_rather_than_retried(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session_relay.record(KIRO, "sess_the-old-label", sweep=False)
        monkeypatch.setattr(os, "write", lambda _descriptor, _data: 0)
        session_relay.record(KIRO, "sess_the-new-label", sweep=False)
        monkeypatch.undo()
        assert _relay_file().read_text(encoding="utf-8") == "sess_the-old-label"
        assert [entry.name for entry in session_relay.relay_dir().iterdir()] == [_relay_file().name]

    def test_a_refused_runtime_directory_costs_the_relay_and_nothing_else(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """`security.ensure_runtime_dir` raises on a directory it will not trust, and the relay is
        written before the policy is printed, so an unguarded write would cost the policy."""
        hostile = tmp_path / "runtime"
        (hostile / "zikaron").mkdir(parents=True, mode=0o755)
        (hostile / "zikaron").chmod(0o755)
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(hostile))
        monkeypatch.setattr(spawn_warm, "run", lambda **_kwargs: "the write policy")
        printed = _run(
            {"hook_event_name": KIRO.spawn_trigger, "cwd": str(tmp_path), "session_id": "sess_a"},
            monkeypatch,
        )
        assert printed == "the write policy"
        assert not session_relay.relay_dir().exists()


class TestItIsWrittenFirst:
    def test_it_is_written_when_the_push_cannot_reach_a_service(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A cold-start push can spend its whole deadline waiting on a starting service and be
        killed at the harness's timeout, so a relay written after the request would be lost on the
        very session whose label is measured."""
        monkeypatch.setattr(push, "run", lambda **_kwargs: "the memory hook failed")
        _run(
            {
                "hook_event_name": KIRO.prompt_trigger,
                "cwd": str(tmp_path),
                "session_id": "sess_cold",
                "prompt": "anything",
            },
            monkeypatch,
        )
        assert _relay_file().read_text(encoding="utf-8") == "sess_cold"

    def test_it_is_written_when_the_push_is_suppressed(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv(KIRO.session_variable, "sess_an-enclosing-session")
        printed = _run(
            {
                "hook_event_name": KIRO.prompt_trigger,
                "cwd": str(tmp_path),
                "session_id": "sess_this-session",
                "prompt": "anything",
            },
            monkeypatch,
        )
        assert printed == ""
        assert _relay_file().read_text(encoding="utf-8") == "sess_this-session"


class TestTheSweep:
    def test_a_session_start_removes_the_files_of_processes_that_are_gone(self) -> None:
        directory = session_relay.relay_dir()
        session_relay.record(KIRO, "sess_live", sweep=False)
        dead = _dead_pid()
        detect.relay_file(directory, dead).write_text("sess_dead")
        (directory / f"{os.getppid()}.{dead}.tmp").write_text("sess_half")
        session_relay.record(KIRO, "sess_live", sweep=True)
        assert sorted(entry.name for entry in directory.iterdir()) == [_relay_file().name]

    def test_a_prompt_removes_nothing(self) -> None:
        directory = session_relay.relay_dir()
        session_relay.record(KIRO, "sess_live", sweep=False)
        dead = _dead_pid()
        detect.relay_file(directory, dead).write_text("sess_dead")
        session_relay.record(KIRO, "sess_live", sweep=False)
        assert detect.relay_file(directory, dead).exists()

    def test_a_file_whose_name_is_no_pid_is_left_alone(self) -> None:
        directory = session_relay.relay_dir()
        session_relay.record(KIRO, "sess_live", sweep=False)
        (directory / "notes").write_text("not ours to judge")
        session_relay.record(KIRO, "sess_live", sweep=True)
        assert (directory / "notes").exists()

    def test_a_process_this_user_cannot_signal_counts_as_alive(self) -> None:
        """`PermissionError` from `os.kill(pid, 0)` means the process exists and is someone
        else's; pid 1 is always such a process for an unprivileged user, and alive for root."""
        directory = session_relay.relay_dir()
        session_relay.record(KIRO, "sess_live", sweep=False)
        detect.relay_file(directory, 1).write_text("sess_init")
        session_relay.record(KIRO, "sess_live", sweep=True)
        assert detect.relay_file(directory, 1).exists()
