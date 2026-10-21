"""The search reminder's hook path (`design/code-knowledge.md` §6): which tool events it asks
about, the connect that never starts a service, the request it sends, and silence on failure.

The service is a fake bound on a real socket in this process, so the hook's actual socket code runs
(`coding-standards.md` §4).
"""

import json
import socket
import threading
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from zikaron.core.errors import ErrorCode
from zikaron.harness.spec import CLAUDE_CODE, KIRO
from zikaron.hook import connect, reminder, rpc
from zikaron.install.code_knowledge import DOCUMENTER_AGENT_NAME, ORCHESTRATOR_AGENT_NAME
from zikaron.service.params import PATHS_MAX

_LINE = "Zikaron hook: a reminder."
_SESSION = "the-session"


class _FakeService:
    """A UDS server that answers `health()` as this store's and every other request with
    `answer`, recording each request it read."""

    def __init__(self, sock_path: Path, *, store_db_path: Path, answer: dict[str, object]) -> None:
        self._store_db_path = store_db_path
        self._answer = answer
        self.requests: list[dict[str, object]] = []
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(str(sock_path))
        self._server.listen(4)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        self._server.settimeout(0.05)
        while not self._stop.is_set():
            try:
                connection, _ = self._server.accept()
            except TimeoutError:
                continue
            with connection, connection.makefile("rb") as lines:
                for raw in lines:
                    request = json.loads(raw)
                    self.requests.append(request)
                    if request["method"] == "health":
                        body: dict[str, object] = {
                            "result": {
                                "ready": True,
                                "store_path": str(self._store_db_path),
                                "store_id": "an-id",
                            }
                        }
                    else:
                        body = self._answer
                    response = {"jsonrpc": "2.0", "id": request.get("id", 1), **body}
                    connection.sendall((json.dumps(response) + "\n").encode("utf-8"))

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)
        self._server.close()

    @property
    def remind_params(self) -> dict[str, object]:
        (request,) = [one for one in self.requests if one["method"] == "knowledge_remind"]
        params = request["params"]
        assert isinstance(params, dict)
        return params


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A project with one knowledge base's database present, and a session label to send."""
    knowledge = tmp_path / ".zikaron" / "knowledge"
    knowledge.mkdir(parents=True)
    (knowledge / "00000000-0000-0000-0000-000000000000.db").touch()
    monkeypatch.setenv(CLAUDE_CODE.session_variable, _SESSION)
    return tmp_path


@pytest.fixture
def serve(
    project: Path, socket_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Callable[[dict[str, object]], _FakeService]]:
    sock_path = socket_dir / "s.sock"
    monkeypatch.setattr(connect, "resolve_sock_path", lambda _store_dir: sock_path)
    started: list[_FakeService] = []

    def _start(answer: dict[str, object]) -> _FakeService:
        service = _FakeService(
            sock_path, store_db_path=project / ".zikaron" / "memory.db", answer=answer
        )
        started.append(service)
        return service

    yield _start
    for service in started:
        service.close()


@pytest.fixture
def no_service(socket_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A socket path nothing listens on."""
    sock_path = socket_dir / "absent.sock"
    monkeypatch.setattr(connect, "resolve_sock_path", lambda _store_dir: sock_path)
    return sock_path


def _grep(path: str | None = None, **extra: object) -> dict[str, object]:
    tool_input: dict[str, object] = {"pattern": "needle"}
    if path is not None:
        tool_input["path"] = path
    return {"tool_name": "Grep", "tool_input": tool_input, **extra}


def _run(payload: dict[str, object], project: Path, *, spec: object = CLAUDE_CODE) -> str | None:
    return reminder.run(
        {"cwd": str(project), **payload},
        scope_dir=project,
        spec=spec,  # type: ignore[arg-type]
        pid=7,
    )


def _hook_log(project: Path) -> str:
    path = project / ".zikaron" / "hook.log"
    return path.read_text(encoding="utf-8") if path.exists() else ""


class TestWhatIsAsked:
    def test_a_grep_is_answered_with_the_service_s_line(
        self, project: Path, serve: Callable[[dict[str, object]], _FakeService]
    ) -> None:
        service = serve({"result": {"text": _LINE}})
        assert _run(_grep("src"), project) == _LINE
        params = service.remind_params
        assert params["paths"] == [str(project / "src")]
        assert "agent_id" not in params
        assert isinstance(params["deadline_at_ms"], int)
        client = params["client"]
        assert isinstance(client, dict)
        assert client["session_id"] == _SESSION

    def test_no_reminder_due_is_silence(
        self, project: Path, serve: Callable[[dict[str, object]], _FakeService]
    ) -> None:
        serve({"result": {"text": None}})
        assert _run(_grep("src"), project) is None
        assert _hook_log(project) == ""

    @pytest.mark.parametrize(
        "payload",
        [
            _grep("src", tool_response={"numFiles": 0, "filenames": []}),
            {
                "tool_name": "Bash",
                "tool_input": {"command": "grep -rn needle src"},
                "tool_response": {
                    "stdout": "",
                    "stderr": "",
                    "interrupted": False,
                    "returnCodeInterpretation": "No matches found",
                },
            },
        ],
        ids=["a Grep that found nothing", "a grep that found nothing"],
    )
    def test_the_result_is_not_read(
        self,
        project: Path,
        serve: Callable[[dict[str, object]], _FakeService],
        payload: dict[str, object],
    ) -> None:
        """A search that found nothing is reminded as one that found something: the miss is when
        the documents help most. The two results are the shapes the probes recorded."""
        serve({"result": {"text": _LINE}})
        assert _run(payload, project) == _LINE

    def test_a_grep_with_no_path_searched_the_working_directory(
        self, project: Path, serve: Callable[[dict[str, object]], _FakeService]
    ) -> None:
        service = serve({"result": {"text": _LINE}})
        _run(_grep(), project)
        assert service.remind_params["paths"] == [str(project)]

    def test_a_glob_s_path_is_what_it_searched(
        self, project: Path, serve: Callable[[dict[str, object]], _FakeService]
    ) -> None:
        service = serve({"result": {"text": _LINE}})
        _run({"tool_name": "Glob", "tool_input": {"pattern": "*.rs", "path": "lib"}}, project)
        assert service.remind_params["paths"] == [str(project / "lib")]

    def test_a_shell_search_s_paths_are_read_from_its_command(
        self, project: Path, serve: Callable[[dict[str, object]], _FakeService]
    ) -> None:
        service = serve({"result": {"text": _LINE}})
        command: dict[str, object] = {
            "tool_name": "Bash",
            "tool_input": {"command": "grep -rn needle a b"},
        }
        assert _run(command, project) == _LINE
        assert service.remind_params["paths"] == [str(project / "a"), str(project / "b")]

    def test_a_subagent_s_id_is_sent_beside_its_type(
        self, project: Path, serve: Callable[[dict[str, object]], _FakeService]
    ) -> None:
        service = serve({"result": {"text": _LINE}})
        _run(_grep(agent_type="Explore", agent_id="a1"), project)
        assert service.remind_params["agent_id"] == "a1"

    def test_an_id_with_no_type_is_not_sent(
        self, project: Path, serve: Callable[[dict[str, object]], _FakeService]
    ) -> None:
        """The main session's key never carries one, or `memory_surface` could not clear it."""
        service = serve({"result": {"text": _LINE}})
        _run(_grep(agent_id="a1"), project)
        assert "agent_id" not in service.remind_params

    def test_a_main_session_run_as_a_named_agent_is_keyed_as_the_session(
        self, project: Path, serve: Callable[[dict[str, object]], _FakeService]
    ) -> None:
        """`claude --agent <name>` gives the main session's tool events an `agent_type` and no
        `agent_id` (`research/m40-4-hook-probes.md`), so the per-prompt clear still reaches it."""
        service = serve({"result": {"text": _LINE}})
        assert _run(_grep(agent_type="leiba-engineer"), project) == _LINE
        assert "agent_id" not in service.remind_params

    def test_a_payload_session_id_differing_from_the_label_is_asked_under_the_label(
        self, project: Path, serve: Callable[[dict[str, object]], _FakeService]
    ) -> None:
        """This path compares no session ids: nothing is suppressed, and nothing is logged."""
        service = serve({"result": {"text": _LINE}})
        assert _run(_grep(session_id="not-the-label"), project) == _LINE
        client = service.remind_params["client"]
        assert isinstance(client, dict)
        assert client["session_id"] == _SESSION
        assert _hook_log(project) == ""

    def test_past_the_bound_the_first_paths_are_sent(
        self, project: Path, serve: Callable[[dict[str, object]], _FakeService]
    ) -> None:
        service = serve({"result": {"text": _LINE}})
        files = " ".join(f"f{n}" for n in range(reminder.PATHS_AT_MOST + 5))
        _run({"tool_name": "Bash", "tool_input": {"command": f"grep x {files}"}}, project)
        sent = service.remind_params["paths"]
        assert isinstance(sent, list)
        assert sent == [str(project / f"f{n}") for n in range(reminder.PATHS_AT_MOST)]


class TestWhatIsNotAsked:
    @pytest.mark.parametrize("agent_type", [DOCUMENTER_AGENT_NAME, ORCHESTRATOR_AGENT_NAME])
    def test_never_for_the_documenter_or_the_orchestrator(
        self, project: Path, serve: Callable[[dict[str, object]], _FakeService], agent_type: str
    ) -> None:
        service = serve({"result": {"text": _LINE}})
        assert _run(_grep(agent_type=agent_type, agent_id="a1"), project) is None
        assert service.requests == []

    def test_never_under_a_harness_with_no_reminder(
        self, project: Path, serve: Callable[[dict[str, object]], _FakeService]
    ) -> None:
        service = serve({"result": {"text": _LINE}})
        assert _run(_grep(), project, spec=KIRO) is None
        assert service.requests == []

    @pytest.mark.parametrize(
        "payload",
        [
            {"tool_name": "Read", "tool_input": {"file_path": "/a"}},
            {"tool_name": "Bash", "tool_input": {"command": "ls src"}},
            {"tool_name": "Bash", "tool_input": {"command": 7}},
            {"tool_name": "Grep", "tool_input": "not an object"},
            {"tool_input": {"pattern": "x"}},
        ],
        ids=["another tool", "no search", "command not a string", "input not an object", "no tool"],
    )
    def test_a_payload_that_reports_no_search_asks_nothing(
        self,
        project: Path,
        serve: Callable[[dict[str, object]], _FakeService],
        payload: dict[str, object],
    ) -> None:
        service = serve({"result": {"text": _LINE}})
        assert _run(payload, project) is None
        assert service.requests == []

    def test_a_store_with_no_corpus_makes_no_connection(
        self,
        project: Path,
        serve: Callable[[dict[str, object]], _FakeService],
    ) -> None:
        (project / ".zikaron" / "knowledge" / "00000000-0000-0000-0000-000000000000.db").unlink()
        service = serve({"result": {"text": _LINE}})
        assert _run(_grep(), project) is None
        assert service.requests == []

    def test_no_session_label_asks_nothing(
        self,
        project: Path,
        serve: Callable[[dict[str, object]], _FakeService],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv(CLAUDE_CODE.session_variable)
        service = serve({"result": {"text": _LINE}})
        assert _run(_grep(), project) is None
        assert service.requests == []

    def test_with_no_service_serving_it_is_silent_and_starts_nothing(
        self, project: Path, no_service: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _no_start(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("a start was attempted")

        monkeypatch.setattr(connect, "_start_under_lock", _no_start)
        assert _run(_grep(), project) is None
        assert _hook_log(project) == ""
        assert not no_service.exists()


class TestFailure:
    """A serving service's error, or a failure once connecting began, is one `hook.log` line
    carrying the reminder's word, and silence."""

    def test_an_error_answer_is_logged_by_its_kind_and_told_from_a_push_s(
        self, project: Path, serve: Callable[[dict[str, object]], _FakeService]
    ) -> None:
        code = int(ErrorCode.STORE_BUSY)
        serve({"error": {"code": code, "message": "busy"}})
        assert _run(_grep(), project) is None
        (line,) = _hook_log(project).splitlines()
        assert line.split()[1:] == ["store_busy", reminder.LOG_DETAIL, str(code)]

    def test_an_unnamed_code_is_still_identifiable(
        self, project: Path, serve: Callable[[dict[str, object]], _FakeService]
    ) -> None:
        serve({"error": {"code": int(ErrorCode.BOUNDS), "message": "bounds"}})
        _run(_grep(), project)
        (line,) = _hook_log(project).splitlines()
        assert line.split()[1:3] == [f"rejected_{int(ErrorCode.BOUNDS)}", reminder.LOG_DETAIL]

    def test_a_malformed_answer_is_transport(
        self, project: Path, serve: Callable[[dict[str, object]], _FakeService]
    ) -> None:
        serve({"result": {"no text": True}})
        assert _run(_grep(), project) is None
        (line,) = _hook_log(project).splitlines()
        assert line.split()[1:] == ["transport", reminder.LOG_DETAIL]

    def test_an_unanswered_request_is_unanswered(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _hangs(*_args: object, **_kwargs: object) -> None:
            raise TimeoutError

        monkeypatch.setattr(connect, "connect_if_serving", _fake_connection)
        monkeypatch.setattr(rpc, "remind_once", _hangs)
        _run(_grep(), project)
        (line,) = _hook_log(project).splitlines()
        assert line.split()[1:] == ["unanswered", reminder.LOG_DETAIL]

    def test_a_request_never_sent_is_deadline_exceeded(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _late(*_args: object, **_kwargs: object) -> None:
            raise rpc.NotSentError

        monkeypatch.setattr(connect, "connect_if_serving", _fake_connection)
        monkeypatch.setattr(rpc, "remind_once", _late)
        _run(_grep(), project)
        (line,) = _hook_log(project).splitlines()
        assert line.split()[1:] == ["deadline_exceeded", reminder.LOG_DETAIL]

    def test_another_store_s_service_is_store_identity(
        self, project: Path, serve: Callable[[dict[str, object]], _FakeService], tmp_path: Path
    ) -> None:
        service = serve({"result": {"text": _LINE}})
        service._store_db_path = tmp_path / "elsewhere.db"
        assert _run(_grep(), project) is None
        (line,) = _hook_log(project).splitlines()
        assert line.split()[1:3] == ["store_identity", reminder.LOG_DETAIL]

    def test_an_unanticipated_exception_is_transport(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _breaks(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("unanticipated")

        monkeypatch.setattr(connect, "connect_if_serving", _breaks)
        assert _run(_grep(), project) is None
        (line,) = _hook_log(project).splitlines()
        assert line.split()[1:] == ["transport", reminder.LOG_DETAIL]

    def test_an_unreadable_knowledge_directory_is_no_corpus(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _unreadable(_store_dir: Path) -> tuple[Path, ...]:
            raise PermissionError

        monkeypatch.setattr(reminder, "orphan_candidates", _unreadable)
        assert _run(_grep(), project) is None
        assert _hook_log(project) == ""


def _fake_connection(*_args: object, **_kwargs: object) -> connect.Connection:
    near, far = socket.socketpair()
    far.close()
    return connect.Connection(
        sock=near, cold_start=False, health=connect.Health(store_path="/x", store_id="y")
    )


def test_the_tools_it_reads_are_the_spec_field_s(
    project: Path, serve: Callable[[dict[str, object]], _FakeService]
) -> None:
    """No tool name is spelled downstream of the seam: widening a matcher widens what is read."""
    assert CLAUDE_CODE.search_reminder is not None
    files = CLAUDE_CODE.search_reminder.files._replace(matcher="Grep|Glob|LS")
    widened = CLAUDE_CODE._replace(
        search_reminder=CLAUDE_CODE.search_reminder._replace(files=files)
    )
    service = serve({"result": {"text": _LINE}})
    listing: dict[str, object] = {"tool_name": "LS", "tool_input": {"path": "lib"}}
    assert _run(listing, project) is None
    assert _run(listing, project, spec=widened) == _LINE
    assert service.remind_params["paths"] == [str(project / "lib")]


def test_the_silent_agent_types_are_the_installer_s_names() -> None:
    assert reminder.DOCUMENTER_AGENT_TYPE == DOCUMENTER_AGENT_NAME
    assert reminder.ORCHESTRATOR_AGENT_TYPE == ORCHESTRATOR_AGENT_NAME


def test_the_hook_s_bound_is_the_service_s() -> None:
    assert reminder.PATHS_AT_MOST == PATHS_MAX
