"""`zikaron.hook.spawn_warm.run`: `agentSpawn`'s print-the-policy-and-warm sequence.

`architecture.md` §"Warming" and §"Subagent sessions" are normative.
"""

import subprocess
from pathlib import Path

import pytest

from zikaron.hook import connect, failure, spawn_warm, write_policy
from zikaron.hook.limits import MAX_OUTPUT_SIZE
from zikaron.hook.write_policy import OVERRIDE_REFUSED, WRITE_POLICY_PROMPT


def test_returns_the_write_policy_prompt_on_a_top_level_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`spawn_warm.run` always calls `_spawn_warm_helper_best_effort` as a side effect on a
    top-level session, regardless of what the caller is asserting about the returned prompt —
    `subprocess.Popen` must be mocked here too, or this test genuinely spawns the real detached
    warm helper (which then genuinely spawns a real `zikaron.service.main` for `tmp_path`),
    leaking both processes on every run. An earlier version of this test omitted the mock on the
    reasoning that it was checking an unrelated return value, and the leak went unnoticed because
    nothing in the test's own assertions depended on the spawn *not* happening.
    """
    monkeypatch.delenv("KIRO_SESSION_ID", raising=False)
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: None)
    output = spawn_warm.run(cwd=tmp_path, payload_session_id="anything")
    assert output == WRITE_POLICY_PROMPT


def test_returns_none_in_a_subagent_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KIRO_SESSION_ID", "top-level-session")
    output = spawn_warm.run(cwd=tmp_path, payload_session_id="a-different-subagent-session")
    assert output is None


def test_a_subagent_session_never_spawns_the_warm_helper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`architecture.md` §"Subagent sessions": suppression is unconditional, ahead of the RPC and
    ahead of the degraded chain — the warm helper's own spawn is the `agentSpawn` equivalent of
    the RPC a `userPromptSubmit` would otherwise make, so it must not run either."""
    monkeypatch.setenv("KIRO_SESSION_ID", "top-level-session")
    spawned: list[list[str]] = []

    def _fail_if_called(command: list[str], **_kwargs: object) -> None:
        spawned.append(command)

    monkeypatch.setattr(subprocess, "Popen", _fail_if_called)
    spawn_warm.run(cwd=tmp_path, payload_session_id="a-different-subagent-session")
    assert spawned == []


def test_a_top_level_session_spawns_the_warm_helper_with_this_stores_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("KIRO_SESSION_ID", raising=False)
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    spawned: list[list[str]] = []

    class _FakePopen:
        def __init__(self, command: list[str], **_kwargs: object) -> None:
            spawned.append(command)

    monkeypatch.setattr(subprocess, "Popen", _FakePopen)
    spawn_warm.run(cwd=tmp_path, payload_session_id=None)
    assert len(spawned) == 1
    command = spawned[0]
    assert command[1:3] == ["-m", "zikaron.hook.warm_helper"]
    assert str(tmp_path / ".zikaron") == command[4]


def test_a_spawn_failure_does_not_change_what_is_printed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`spawn_warm.py`'s own docstring: the spawn is deliberately best-effort, with no observable
    effect on this hook's own output either way."""
    monkeypatch.delenv("KIRO_SESSION_ID", raising=False)

    def _raise_oserror(*_args: object, **_kwargs: object) -> None:
        raise OSError("no such interpreter")

    monkeypatch.setattr(subprocess, "Popen", _raise_oserror)
    output = spawn_warm.run(cwd=tmp_path, payload_session_id=None)
    assert output == WRITE_POLICY_PROMPT


def test_a_non_oserror_failure_in_path_derivation_does_not_suppress_the_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The gap an earlier version of this module had: only `Popen` itself was wrapped in
    `contextlib.suppress(OSError)`, leaving path derivation (`connect.resolve_sock_path`, which
    calls `Path.resolve()` and can raise on a symlink loop) unguarded — a failure there would
    have propagated past this module entirely and reached `main.py`'s own outermost catch-all,
    which for `agentSpawn` would then suppress the **write-policy print itself**. Forced by
    monkeypatching `connect.resolve_sock_path` to raise `RuntimeError`, a type `OSError` alone
    would not have caught, so this proves the fix catches the whole operation rather than only
    widening the type list around the one call site already covered.
    """
    monkeypatch.delenv("KIRO_SESSION_ID", raising=False)

    def _raise_runtime_error(_store_dir: Path) -> Path:
        raise RuntimeError("a symlink loop, or any other non-OSError failure")

    monkeypatch.setattr(connect, "resolve_sock_path", _raise_runtime_error)
    output = spawn_warm.run(cwd=tmp_path, payload_session_id=None)
    assert output == WRITE_POLICY_PROMPT


class TestTheOverrideReachesStdoutAndItsLabelReachesHookLog:
    """`architecture.md` §"The install contract": the override is what gets printed, and a read that
    was not simply "no override there" leaves one fixed label in `hook.log`.

    `subprocess.Popen` is mocked in every case here for the reason the first test in this file
    documents: `run()` spawns the real detached warm helper on any top-level session, whatever the
    test is actually asserting.
    """

    @staticmethod
    def _top_level(monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("KIRO_SESSION_ID", raising=False)
        monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: None)

    def test_a_clean_override_is_printed_instead_of_the_constant(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._top_level(monkeypatch)
        store = tmp_path / ".zikaron"
        store.mkdir(mode=0o700)
        store.chmod(0o700)
        (store / "write-policy.md").write_text("## Operator policy\n")
        assert spawn_warm.run(cwd=tmp_path, payload_session_id=None) == "## Operator policy\n"
        assert not (store / "hook.log").exists()

    def test_a_refused_override_prints_the_constant_and_logs_one_line(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._top_level(monkeypatch)
        store = tmp_path / ".zikaron"
        store.mkdir(mode=0o700)
        store.chmod(0o700)
        (store / "write-policy.md").mkdir()
        assert spawn_warm.run(cwd=tmp_path, payload_session_id=None) == WRITE_POLICY_PROMPT
        logged = (store / "hook.log").read_text().splitlines()
        assert len(logged) == 1
        assert logged[0].endswith(OVERRIDE_REFUSED)

    def test_a_failure_inside_the_reader_still_prints_the_constant(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The whole-body guard, forced: `read_policy` raising something none of its own six
        conditions anticipated must not cost this hook the one thing `architecture.md` promises it
        always does. `RuntimeError` specifically, so a guard narrowed to `OSError` would not pass.
        """
        self._top_level(monkeypatch)

        def _raise(_store_dir: Path) -> object:
            raise RuntimeError("an unanticipated reader failure")

        monkeypatch.setattr(write_policy, "read_policy", _raise)
        assert spawn_warm.run(cwd=tmp_path, payload_session_id=None) == WRITE_POLICY_PROMPT

    def test_a_failure_while_logging_the_label_still_prints_the_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`record_failure` is itself best-effort, but this asserts the *caller's* guarantee rather
        than trusting that one: even if logging raised, the text this function resolved is what gets
        printed. Otherwise a full disk would silently downgrade an operator's policy.
        """
        self._top_level(monkeypatch)
        store = tmp_path / ".zikaron"
        store.mkdir(mode=0o700)
        oversize = "y" * (MAX_OUTPUT_SIZE + 1)
        (store / "write-policy.md").write_text(oversize)

        def _raise(*_args: object, **_kwargs: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(failure, "record_failure", _raise)
        assert spawn_warm.run(cwd=tmp_path, payload_session_id=None) == oversize
