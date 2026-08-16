"""`zikaron.hook.main`: stdin JSON dispatch and the outermost catch-all — always exit 0.

`_run()` is exercised directly for the dispatch logic, since it is a plain function with no
return value. `TestMainAsARealSubprocess` covers what only a real process boundary can assert:
the actual exit code, and that nothing unexpected reaches real stdout/stderr.
"""

import contextlib
import io
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Final

import pytest

from zikaron.harness.spec import CLAUDE_CODE, KIRO
from zikaron.hook import main as main_module
from zikaron.hook import push, spawn_warm, subagent_policy
from zikaron.hook.write_policy import WRITE_POLICY_PROMPT
from zikaron.service import paths

_TIMEOUT_SECONDS: Final = 15.0


class _FakeSurfaceServiceForMain:
    """A real UDS server, bound at the exact path `connect.resolve_sock_path` derives for a real
    `store_dir` under a real, dedicated `XDG_RUNTIME_DIR` — unlike `test_hook_push.py`'s own fake
    service, which monkeypatches `resolve_sock_path` directly, this one has to work against a
    genuine **subprocess**, where in-process monkeypatching has no effect at all: the environment
    variable is the only lever a real child process shares with this test.
    """

    def __init__(self, store_dir: Path, *, respond_text: str) -> None:
        # A short, top-level `/tmp` directory rather than nesting under `store_dir` — pytest's
        # own `tmp_path` is already several directory levels deep, and the socket path this class
        # binds is `runtime_dir/zikaron/<32-hex-char-hash>.sock`; combined with a deeply-nested
        # `tmp_path` as the runtime directory, the total length exceeds the ~108-byte kernel
        # `sun_path` limit — measured directly rather than assumed, since an earlier version of
        # this fixture nested under `store_dir` and failed with exactly that `OSError`.
        self.runtime_dir = Path(tempfile.mkdtemp(prefix="zikaron-test-runtime-"))
        store_subdir = store_dir / ".zikaron"
        store_subdir.mkdir()
        self._store_db_path = store_subdir / "memory.db"
        sock_path = resolve_sock_path_under(store_subdir, xdg_runtime_dir=self.runtime_dir)
        self._respond_text = respond_text
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(str(sock_path))
        self._server.listen(4)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve_forever, daemon=True)
        self._thread.start()

    def _serve_forever(self) -> None:
        self._server.settimeout(0.05)
        while not self._stop.is_set():
            try:
                connection, _ = self._server.accept()
            except TimeoutError:
                continue
            with connection:
                while True:
                    request = self._read_one_request(connection)
                    if request is None:
                        break
                    self._answer(connection, request)

    def _read_one_request(self, connection: socket.socket) -> dict[str, object] | None:
        buffer = b""
        while not buffer.endswith(b"\n"):
            chunk = connection.recv(4096)
            if not chunk:
                return None
            buffer += chunk
        parsed = json.loads(buffer.decode("utf-8"))
        assert isinstance(parsed, dict)
        return parsed

    def _answer(self, connection: socket.socket, request: dict[str, object]) -> None:
        method = request.get("method")
        response: dict[str, object]
        if method == "health":
            response = {
                "jsonrpc": "2.0",
                "id": request.get("id", 1),
                "result": {
                    "ready": True,
                    "store_path": str(self._store_db_path),
                    "store_id": "test-store-id",
                },
            }
        else:
            response = {
                "jsonrpc": "2.0",
                "id": request.get("id", 1),
                "result": {"text": self._respond_text},
            }
        connection.sendall((json.dumps(response) + "\n").encode("utf-8"))

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)
        self._server.close()
        shutil.rmtree(self.runtime_dir, ignore_errors=True)


def resolve_sock_path_under(store_subdir: Path, *, xdg_runtime_dir: Path) -> Path:
    """`connect.resolve_sock_path`'s own derivation, computed with an explicit
    `XDG_RUNTIME_DIR` rather than reading it from `os.environ` — a test-only variant so this
    fixture can bind a socket at the identical path a real subprocess given that same environment
    variable will itself derive, without mutating this test process's own environment first.

    Also creates the derived runtime directory (`XDG_RUNTIME_DIR/zikaron`) if it does not exist,
    mirroring what `connect.connect_once`'s own call to `security.ensure_runtime_dir` does in
    production — this test fixture binds a socket directly rather than going through
    `connect_once` at all, so nothing else would create that directory on its behalf.
    """
    resolved_store_dir = store_subdir.resolve()
    runtime_dir = paths.runtime_dir(xdg_runtime_dir=str(xdg_runtime_dir), uid=os.getuid())
    runtime_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    return paths.socket_path(runtime_dir, resolved_store_dir)


def _pid_from_health(sock_path: Path) -> int | None:
    """Connect to `sock_path` and ask its `health()` for the serving process's pid — `None` if
    nothing answers, which is the ordinary case for every test that never causes a real service
    to be spawned at all.
    """
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(1.0)
        sock.connect(str(sock_path))
    except OSError:
        return None
    try:
        sock.sendall(b'{"jsonrpc": "2.0", "id": 1, "method": "health", "params": {}}\n')
        buffer = b""
        while not buffer.endswith(b"\n"):
            chunk = sock.recv(4096)
            if not chunk:
                return None
            buffer += chunk
        parsed = json.loads(buffer.decode("utf-8"))
        pid = parsed["result"]["pid"]
        assert isinstance(pid, int)
        return pid
    except (OSError, KeyError, ValueError):
        return None
    finally:
        sock.close()


def _reap_any_service_spawned_for(store_dir: Path) -> None:
    """Wait for, then kill, whatever real `zikaron.service.main` process a top-level `agentSpawn`
    test's own detached warm helper may have caused to exist for `store_dir` — and fail loudly if
    it cannot be confirmed gone, rather than silently returning either way.

    The whole chain is genuinely asynchronous and detached by design (`architecture.md`
    §"Warming": "the hook process makes no RPC; its detached child does the start-if-absent
    work, on a path no user message waits for") — `main.py`'s own subprocess has already exited
    by the time this cleanup runs, and the warm helper it spawned may still be mid-flight. This
    polls for the service to actually become reachable through the warm helper's own full
    `_HEALTH_POLL_DEADLINE_SECONDS` (10 s) plus margin — round 2 review
    (`reviews/m11-hook-client-review.md`, finding 6) found an earlier version of this function
    used a 5 s deadline here, half the helper's own, so a slower machine could have the helper
    finish starting a service *after* this function had already given up looking for one to
    clean up — before attempting to terminate it; a warm helper that never starts anything leaves
    nothing here to find, which is the ordinary, non-leaking case for every *other* test in this
    class that does not touch `agentSpawn` at all.

    The service found this way is a **grandchild** of this test process (this process's own
    child, `main.py`'s subprocess, has already exited; the warm helper it spawned is itself
    detached and its own child is the service) — `os.waitpid` cannot reap a process that is not
    this process's own direct child, and the same round-2 finding caught an earlier version of
    this function treating `os.waitpid`'s resulting `ChildProcessError` as confirmation the
    process was gone, when it only confirms this process was never entitled to reap it in the
    first place and says nothing about whether SIGTERM actually took effect. Liveness is
    therefore checked with `os.kill(pid, 0)` (works correctly against a non-child, unlike
    `waitpid`, and raises `ProcessLookupError` once the process is genuinely gone), with SIGKILL
    escalation if SIGTERM alone has not worked by the same deadline, and an assertion that the
    process is confirmed gone before this function returns — a leaked, still-running service is a
    real test-suite hygiene defect this cleanup exists to catch, not something to fail past
    silently.
    """
    sock_path = resolve_sock_path_under(
        store_dir / ".zikaron",
        xdg_runtime_dir=Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")),  # noqa: S108 — a
        # fallback only, matching `_FakeSurfaceServiceForMain`'s own dedicated runtime directory
        # in every test that actually sets `XDG_RUNTIME_DIR`, which every caller of this function
        # does; this branch exists only so the function has a defined value if that were ever
        # not true.
    )
    find_deadline = time.monotonic() + 12.0  # the helper's own 10 s deadline, plus margin.
    pid: int | None = None
    while time.monotonic() < find_deadline:
        pid = _pid_from_health(sock_path)
        if pid is not None:
            break
        time.sleep(0.1)
    if pid is None:
        return

    def _is_alive(candidate_pid: int) -> bool:
        try:
            os.kill(candidate_pid, 0)
        except ProcessLookupError:
            return False
        else:
            return True

    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGTERM)
    term_deadline = time.monotonic() + 5.0
    while time.monotonic() < term_deadline and _is_alive(pid):
        time.sleep(0.05)
    if _is_alive(pid):
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)
        kill_deadline = time.monotonic() + 5.0
        while time.monotonic() < kill_deadline and _is_alive(pid):
            time.sleep(0.05)
    assert not _is_alive(pid), (
        f"leaked zikaron.service.main process pid={pid} for {store_dir} survived SIGTERM and "
        "SIGKILL"
    )


def _invoke_main(payload: object) -> subprocess.CompletedProcess[str]:
    """Run the real `python -m zikaron.hook.main` process, at **this repository's own** working
    directory — production kiro spawns the hook command from wherever kiro itself runs, and it is
    the JSON payload's `cwd` field, not the OS-level subprocess working directory, that tells the
    hook which project it is operating on.
    """
    return subprocess.run(
        [sys.executable, "-m", "zikaron.hook.main"],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
        check=False,
    )


def _run_with_payload(payload: object, monkeypatch: pytest.MonkeyPatch) -> None:
    """Feed `payload` to `_run()` as though it had been read from stdin — cheaper than a real
    subprocess for cases that want in-process monkeypatching of `push.run`/`spawn_warm.run` to
    take effect, which a real subprocess would not see.
    """
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    main_module._run()


class TestRunDispatchesOnHookEventName:
    def test_agent_spawn_calls_spawn_warm(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        called: list[object] = []

        def _fake_run(**kwargs: object) -> str:
            called.append(kwargs)
            return "text"

        monkeypatch.setattr(spawn_warm, "run", _fake_run)
        _run_with_payload({"hook_event_name": "agentSpawn", "cwd": str(tmp_path)}, monkeypatch)
        assert len(called) == 1

    def test_user_prompt_submit_calls_push(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        called: list[object] = []

        def _fake_run(**kwargs: object) -> None:
            called.append(kwargs)

        monkeypatch.setattr(push, "run", _fake_run)
        _run_with_payload(
            {"hook_event_name": "userPromptSubmit", "cwd": str(tmp_path), "prompt": "what failed"},
            monkeypatch,
        )
        assert len(called) == 1

    def test_an_unrecognized_hook_event_name_calls_neither(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        push_called: list[object] = []
        spawn_called: list[object] = []
        monkeypatch.setattr(push, "run", lambda **kwargs: push_called.append(kwargs))
        monkeypatch.setattr(spawn_warm, "run", lambda **kwargs: spawn_called.append(kwargs))
        _run_with_payload({"hook_event_name": "postToolUse", "cwd": str(tmp_path)}, monkeypatch)
        assert push_called == []
        assert spawn_called == []

    def test_user_prompt_submit_with_a_non_string_prompt_never_calls_push(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        called: list[object] = []
        monkeypatch.setattr(push, "run", lambda **kwargs: called.append(kwargs))
        _run_with_payload(
            {"hook_event_name": "userPromptSubmit", "cwd": str(tmp_path), "prompt": 42},
            monkeypatch,
        )
        assert called == []

    def test_a_non_dict_payload_never_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _run_with_payload([1, 2, 3], monkeypatch)  # must not raise

    def test_a_missing_cwd_key_defaults_to_the_current_directory(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`payload.get("cwd", ".")` is the fallback — worth pinning, since a hook payload always
        carries `cwd` per the documented shape, but this function must not raise a `KeyError` if
        a future kiro version ever omitted it."""
        monkeypatch.setattr(spawn_warm, "run", lambda **_kwargs: None)
        _run_with_payload({"hook_event_name": "agentSpawn"}, monkeypatch)  # must not raise


def _run_capturing_stdout(payload: object, monkeypatch: pytest.MonkeyPatch) -> str:
    """`_run()` against a payload, returning exactly what it wrote to stdout."""
    written = io.StringIO()
    monkeypatch.setattr(sys, "stdout", written)
    _run_with_payload(payload, monkeypatch)
    return written.getvalue()


class TestTriggerNamesNormalizeAcrossBothHarnesses:
    """One implementation serves both harnesses, so each harness's own trigger names must reach the
    same module. A ladder of string comparisons per harness is exactly what this replaces.
    """

    @pytest.mark.parametrize("trigger", [KIRO.spawn_trigger, CLAUDE_CODE.spawn_trigger])
    def test_either_harnesss_spawn_trigger_calls_spawn_warm(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, trigger: str
    ) -> None:
        called: list[object] = []
        monkeypatch.setattr(spawn_warm, "run", lambda **kwargs: called.append(kwargs))
        _run_with_payload({"hook_event_name": trigger, "cwd": str(tmp_path)}, monkeypatch)
        assert len(called) == 1

    @pytest.mark.parametrize("trigger", [KIRO.prompt_trigger, CLAUDE_CODE.prompt_trigger])
    def test_either_harnesss_prompt_trigger_calls_push(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, trigger: str
    ) -> None:
        called: list[object] = []
        monkeypatch.setattr(push, "run", lambda **kwargs: called.append(kwargs))
        _run_with_payload(
            {"hook_event_name": trigger, "cwd": str(tmp_path), "prompt": "what failed"},
            monkeypatch,
        )
        assert len(called) == 1

    def test_the_subagent_trigger_calls_only_the_policy_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Policy-only: no warm helper spawn, no push. A second warm spawn per subagent would be
        pure cost, and no retrieval belongs in a subagent's context by this route.
        """
        policy_called: list[object] = []
        spawn_called: list[object] = []
        push_called: list[object] = []
        monkeypatch.setattr(subagent_policy, "run", lambda **kwargs: policy_called.append(kwargs))
        monkeypatch.setattr(spawn_warm, "run", lambda **kwargs: spawn_called.append(kwargs))
        monkeypatch.setattr(push, "run", lambda **kwargs: push_called.append(kwargs))
        _run_with_payload(
            {
                "hook_event_name": CLAUDE_CODE.subagent_start_trigger,
                "cwd": str(tmp_path),
                "agent_type": "some-agent",
            },
            monkeypatch,
        )
        assert len(policy_called) == 1
        assert spawn_called == []
        assert push_called == []

    def test_subagent_stop_reaches_nothing_at_all(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A real trigger one harness sends and this hook has no work for. The hook having no write
        path at all depends on it staying unrecognised rather than merely unhandled downstream.
        """
        called: list[object] = []
        for module in (spawn_warm, push, subagent_policy):
            monkeypatch.setattr(module, "run", lambda **kwargs: called.append(kwargs))
        _run_with_payload(
            {"hook_event_name": "SubagentStop", "cwd": str(tmp_path)},
            monkeypatch,
        )
        assert called == []


class TestOutputGoesOutOnTheEventsOwnChannel:
    """Plain stdout from the subagent trigger reaches nobody — not the subagent, not the parent —
    while the same text under `hookSpecificOutput.additionalContext` reaches the subagent verbatim.
    So the channel is a property of the event, and writing stdout unconditionally silently delivers
    nothing for one of the three.
    """

    @pytest.mark.parametrize(
        "trigger", [KIRO.spawn_trigger, CLAUDE_CODE.spawn_trigger, KIRO.prompt_trigger]
    )
    def test_spawn_and_prompt_write_the_returned_text_verbatim(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, trigger: str
    ) -> None:
        monkeypatch.setattr(spawn_warm, "run", lambda **_kwargs: "policy text")
        monkeypatch.setattr(push, "run", lambda **_kwargs: "policy text")
        written = _run_capturing_stdout(
            {"hook_event_name": trigger, "cwd": str(tmp_path), "prompt": "p"}, monkeypatch
        )
        assert written == "policy text"

    def test_the_subagent_trigger_wraps_its_text_in_the_structured_channel(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(subagent_policy, "run", lambda **_kwargs: "policy text")
        trigger = CLAUDE_CODE.subagent_start_trigger
        written = _run_capturing_stdout(
            {"hook_event_name": trigger, "cwd": str(tmp_path), "agent_type": "some-agent"},
            monkeypatch,
        )
        assert json.loads(written) == {
            "hookSpecificOutput": {
                "hookEventName": trigger,
                "additionalContext": "policy text",
            }
        }

    def test_the_subagent_trigger_never_writes_bare_text(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The regression this whole class exists for: bare text here is delivered to nobody, and
        it fails silently rather than erroring, so only an assertion on the shape catches it.
        """
        monkeypatch.setattr(subagent_policy, "run", lambda **_kwargs: "policy text")
        written = _run_capturing_stdout(
            {
                "hook_event_name": CLAUDE_CODE.subagent_start_trigger,
                "cwd": str(tmp_path),
                "agent_type": "some-agent",
            },
            monkeypatch,
        )
        assert written != "policy text"
        assert written.startswith("{")

    def test_nothing_is_written_at_all_when_a_path_returns_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`None` means print nothing — not an empty structured envelope, which for the subagent
        trigger would still deliver an empty context block rather than staying silent.
        """
        monkeypatch.setattr(subagent_policy, "run", lambda **_kwargs: None)
        written = _run_capturing_stdout(
            {
                "hook_event_name": CLAUDE_CODE.subagent_start_trigger,
                "cwd": str(tmp_path),
                "agent_type": subagent_policy.CONSOLIDATOR_AGENT_TYPE,
            },
            monkeypatch,
        )
        assert written == ""


class TestMainAsARealSubprocess:
    """The observables `_run()` alone cannot assert: the real process's own exit code (always 0,
    per the measurement recorded in `push.py`'s own module docstring), and that nothing
    unexpected reaches stdout or stderr on the ordinary paths.

    These tests exercise `main()` and the `if __name__ == "__main__":` guard *behaviourally* —
    every one of them spawns a real subprocess and observes its real exit code — but `coverage.py`
    cannot attribute a subprocess's own execution back to this test process's coverage data
    without subprocess coverage instrumentation, which nothing else in this codebase adopts
    either: `zikaron/service/main.py`, built and reviewed at M9, carries the identical class of
    uncovered lines (its own thin `run()` wrapper and `__main__` guard) for the same reason.
    """

    def test_malformed_json_on_stdin_exits_zero_with_no_output(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "zikaron.hook.main"],
            input="not valid json{{{",
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )
        assert result.returncode == 0
        assert result.stdout == ""
        assert result.stderr == ""

    def test_an_unrecognized_hook_event_exits_zero_with_no_output(self, tmp_path: Path) -> None:
        result = _invoke_main({"hook_event_name": "stop", "cwd": str(tmp_path)})
        assert result.returncode == 0
        assert result.stdout == ""
        assert result.stderr == ""

    def test_a_subagent_user_prompt_submit_exits_zero_with_no_output(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("KIRO_SESSION_ID", "top-level-session")
        result = _invoke_main(
            {
                "hook_event_name": "userPromptSubmit",
                "cwd": str(tmp_path),
                "session_id": "a-subagent-session",
                "prompt": "irrelevant",
            }
        )
        assert result.returncode == 0
        assert result.stdout == ""
        assert result.stderr == ""

    def test_an_agent_spawn_in_a_subagent_session_exits_zero_with_no_output(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("KIRO_SESSION_ID", "top-level-session")
        result = _invoke_main(
            {
                "hook_event_name": "agentSpawn",
                "cwd": str(tmp_path),
                "session_id": "a-subagent-session",
            }
        )
        assert result.returncode == 0
        assert result.stdout == ""
        assert result.stderr == ""

    def test_a_top_level_agent_spawn_prints_the_write_policy_and_exits_zero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A real, top-level `agentSpawn` genuinely spawns the detached warm helper as a fire-
        and-forget side effect, which in turn genuinely spawns a real `zikaron.service.main` for
        `tmp_path` — this is the intended production behaviour, not a test artefact, so it cannot
        be mocked away without also no longer testing the real end-to-end entry point. `_reap_
        any_service_spawned_for` waits for and cleans up whatever service this test's own
        `agentSpawn` caused to exist, rather than leaving it running for the rest of the suite.
        """
        monkeypatch.delenv("KIRO_SESSION_ID", raising=False)
        result = _invoke_main({"hook_event_name": "agentSpawn", "cwd": str(tmp_path)})
        try:
            assert result.returncode == 0
            assert "Project memory (Zikaron)" in result.stdout
            assert result.stderr == ""
        finally:
            _reap_any_service_spawned_for(tmp_path)

    def test_the_write_policy_reaches_stdout_byte_for_byte_with_no_extra_trailing_newline(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`print(output)` would append a `\\n` `spawn_warm.run` never included in
        `WRITE_POLICY_PROMPT` — this pins the exact end-to-end output rather than only checking
        that a substring is present, which the earlier substring-only test above cannot catch.

        Leaks a real detached warm helper and a real spawned service for the identical reason
        the test above does — see its own docstring — cleaned up the same way.
        """
        monkeypatch.delenv("KIRO_SESSION_ID", raising=False)
        result = _invoke_main({"hook_event_name": "agentSpawn", "cwd": str(tmp_path)})
        try:
            assert result.returncode == 0
            assert result.stdout == WRITE_POLICY_PROMPT
        finally:
            _reap_any_service_spawned_for(tmp_path)

    def test_a_successful_surface_result_reaches_stdout_byte_for_byte(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The same byte-exact guarantee on the `userPromptSubmit` success path: `push.run`'s own
        returned text must reach stdout with no extra trailing newline `print` would have added.
        """
        monkeypatch.setenv("KIRO_SESSION_ID", "s1")
        service = _FakeSurfaceServiceForMain(tmp_path, respond_text="- exact gist one\n- gist two")
        try:
            result = subprocess.run(
                [sys.executable, "-m", "zikaron.hook.main"],
                input=json.dumps(
                    {
                        "hook_event_name": "userPromptSubmit",
                        "cwd": str(tmp_path),
                        "session_id": "s1",
                        "prompt": "p",
                    }
                ),
                capture_output=True,
                text=True,
                timeout=_TIMEOUT_SECONDS,
                env={**os.environ, "XDG_RUNTIME_DIR": str(service.runtime_dir)},
                check=False,
            )
            assert result.returncode == 0
            assert result.stdout == "- exact gist one\n- gist two"
            assert result.stderr == ""
        finally:
            service.close()

    def test_an_empty_surface_result_produces_genuinely_empty_stdout(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`architecture.md` §"Errors": an empty store's `surface` "prints nothing at all" —
        `print("")` would still emit a bare `\\n`, which is a different observable from nothing.
        """
        monkeypatch.setenv("KIRO_SESSION_ID", "s1")
        service = _FakeSurfaceServiceForMain(tmp_path, respond_text="")
        try:
            result = subprocess.run(
                [sys.executable, "-m", "zikaron.hook.main"],
                input=json.dumps(
                    {
                        "hook_event_name": "userPromptSubmit",
                        "cwd": str(tmp_path),
                        "session_id": "s1",
                        "prompt": "p",
                    }
                ),
                capture_output=True,
                text=True,
                timeout=_TIMEOUT_SECONDS,
                env={**os.environ, "XDG_RUNTIME_DIR": str(service.runtime_dir)},
                check=False,
            )
            assert result.returncode == 0
            assert result.stdout == ""
            assert result.stderr == ""
        finally:
            service.close()

    def test_a_degraded_user_prompt_submit_still_exits_zero_and_relays_on_stdout(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The measured result this whole design rests on: even a genuine failure must exit 0 and
        put its relay text on stdout, never stderr — the exact opposite of an earlier revision
        that this spike overturned.

        Forced deterministically rather than by pointing at an empty `tmp_path` and hoping no
        service ever answers: `connect_once`'s own start-if-absent sequence would otherwise
        genuinely **succeed** in starting a real service (which is exactly what it is designed to
        do), turning the intended failure case into an ordinary success once the spawn completes
        — measured directly while building this test, not assumed. `XDG_RUNTIME_DIR` is pointed
        at a plain file rather than a directory, which raises before any connect or spawn
        attempt, guaranteeing the failure path fires regardless of how fast or reliable the real
        service's own startup is — the exact exception class this particular construction raises
        (`NotADirectoryError`, from the OS itself, rather than `security.ensure_runtime_dir`'s own
        `ZikaronError`, which needs a subtly different construction) is not what this test is
        pinning; `test_hook_push.py::test_a_hostile_runtime_directory_is_logged_and_relayed_
        rather_than_propagating` is the one that pins the `ZikaronError` path specifically. This
        test only needs *some* real, deterministic pre-connect failure to observe the real
        process's own exit code and channel behaviour end to end.
        """
        monkeypatch.delenv("KIRO_SESSION_ID", raising=False)
        bogus_runtime_dir = tmp_path / "not-a-directory"
        bogus_runtime_dir.write_text("this is a file, not a directory", encoding="utf-8")
        store_dir = tmp_path / "project"
        store_dir.mkdir()
        env = dict(os.environ)
        env.pop("KIRO_SESSION_ID", None)
        env["XDG_RUNTIME_DIR"] = str(bogus_runtime_dir)
        result = subprocess.run(
            [sys.executable, "-m", "zikaron.hook.main"],
            input=json.dumps(
                {"hook_event_name": "userPromptSubmit", "cwd": str(store_dir), "prompt": "p"}
            ),
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            env=env,
            check=False,
        )
        assert result.returncode == 0
        assert "operator" in result.stdout
        assert "hook.log" in result.stdout
        assert result.stderr == ""
