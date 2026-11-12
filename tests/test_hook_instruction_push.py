"""`zikaron.hook.instruction_push`: push on an agent's first tool call after an instruction.

`design/harness.md` §"Agent teams" is normative, `architecture.md` §"Degraded modes" for the chain.
The service is stubbed at `connect` and `rpc`, as the reminder's tests stub it; what is pinned here
is who is pushed, on what, at most once, and what a lost push leaves in `hook.log`.
"""

import json
import os
import socket
import threading
import time
from pathlib import Path

import pytest

from tests import transcript_records as records
from zikaron.harness.spec import CLAUDE_CODE, KIRO, HookEvent, InstructionPush
from zikaron.hook import connect, instruction_markers, instruction_push, rpc, spawn_warm
from zikaron.hook import main as main_module
from zikaron.install.code_knowledge import DOCUMENTER_AGENT_NAME, ORCHESTRATOR_AGENT_NAME
from zikaron.install.entries import CONSOLIDATOR_AGENT_NAME
from zikaron.service import paths

SESSION = "6ce78ba4-beb9-485f-b46d-fd39b8ed5073"
AGENT = "amate-1-d82c396dc9f48005"
OTHER = "amate-2-0000000000000000"


@pytest.fixture
def push_spec() -> InstructionPush:
    assert CLAUDE_CODE.instruction_push is not None
    return CLAUDE_CODE.instruction_push


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / ".zikaron").mkdir(mode=0o700)
    assert CLAUDE_CODE.marker_variable is not None
    monkeypatch.setenv(CLAUDE_CODE.marker_variable, "1")
    monkeypatch.setenv(CLAUDE_CODE.session_variable, SESSION)
    return tmp_path


@pytest.fixture
def session_transcript(tmp_path: Path) -> Path:
    return tmp_path / "transcripts" / f"{SESSION}.jsonl"


@pytest.fixture
def surfaced(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    """Every `memory_surface` the path makes, answered with a block naming its prompt."""
    calls: list[dict[str, object]] = []

    def _connection(*_args: object, **_kwargs: object) -> connect.Connection:
        near, far = socket.socketpair()
        far.close()
        return connect.Connection(
            sock=near, cold_start=False, health=connect.Health(store_path="/x", store_id="y")
        )

    def _surface(_sock: socket.socket, **kwargs: object) -> str:
        calls.append(kwargs)
        return f"BLOCK for {kwargs['prompt']}"

    monkeypatch.setattr(connect, "connect_if_serving", _connection)
    monkeypatch.setattr(rpc, "surface_once", _surface)
    return calls


def _agent(
    push_spec: InstructionPush,
    session_transcript: Path,
    agent_id: str,
    *,
    definition: str = "general-purpose",
    transcript: list[dict[str, object]] | None = None,
) -> None:
    record_path = push_spec.agent_file(session_transcript, agent_id, push_spec.record_suffix)
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(json.dumps({"agentType": definition}), encoding="utf-8")
    records.write(
        push_spec.agent_file(session_transcript, agent_id, push_spec.transcript_suffix),
        transcript if transcript is not None else records.at_first_call(f"Task for {agent_id}."),
    )


@pytest.fixture
def pending_agent(project: Path, session_transcript: Path, push_spec: InstructionPush) -> None:
    """An ordinary subagent with its task in its transcript and its marker set."""
    _agent(push_spec, session_transcript, AGENT)
    _mark(project, AGENT)


def _mark(project: Path, agent_id: str | None) -> None:
    payload: dict[str, object] = {"session_id": SESSION, "agent_id": agent_id, "source": "startup"}
    event = HookEvent.SUBAGENT_START if agent_id else HookEvent.SPAWN
    instruction_push.mark(event, payload, scope_dir=project, spec=CLAUDE_CODE)


def _call(
    project: Path,
    session_transcript: Path,
    agent_id: str | None,
    *,
    agent_type: str | None = "x",
) -> str | None:
    payload: dict[str, object] = {
        "session_id": SESSION,
        "transcript_path": str(session_transcript),
        "tool_name": "Bash",
    }
    if agent_id is not None:
        payload["agent_id"] = agent_id
    if agent_type is not None:
        payload["agent_type"] = agent_type
    return instruction_push.run(payload, scope_dir=project, spec=CLAUDE_CODE, pid=1)


def _hook_log(project: Path) -> str:
    path = paths.hook_log_path(project / ".zikaron")
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _pending(project: Path) -> set[str]:
    directory = paths.instruction_pending_dir(project / ".zikaron")
    return {entry.name for entry in directory.iterdir()} if directory.exists() else set()


class TestMarkers:
    @pytest.mark.parametrize(
        ("event", "payload", "expected"),
        [
            (HookEvent.SUBAGENT_START, {"agent_id": AGENT}, {f"{SESSION}.{AGENT}"}),
            (HookEvent.SUBAGENT_START, {}, set()),
            (HookEvent.SPAWN, {"source": "startup"}, {SESSION}),
            (HookEvent.SPAWN, {"source": "resume"}, set()),
            (HookEvent.SPAWN, {"source": "compact"}, set()),
            (HookEvent.TEAMMATE_IDLE, {}, {SESSION}),
            (HookEvent.TEAMMATE_IDLE, {"agent_id": AGENT}, set()),
        ],
    )
    def test_each_setter_writes_its_key(
        self,
        project: Path,
        event: HookEvent,
        payload: dict[str, object],
        expected: set[str],
    ) -> None:
        instruction_push.mark(
            event, {"session_id": SESSION, **payload}, scope_dir=project, spec=CLAUDE_CODE
        )
        assert _pending(project) == expected

    def test_subagent_stop_clears_its_agents_marker_and_no_other(self, project: Path) -> None:
        _mark(project, AGENT)
        _mark(project, OTHER)
        instruction_push.mark(
            HookEvent.SUBAGENT_STOP,
            {"session_id": SESSION, "agent_id": AGENT},
            scope_dir=project,
            spec=CLAUDE_CODE,
        )
        assert _pending(project) == {f"{SESSION}.{OTHER}"}

    def test_a_subagent_stop_without_its_id_leaves_the_sessions_own_marker(
        self, project: Path
    ) -> None:
        """The session's own marker is a tmux teammate's waiting message."""
        _mark(project, None)
        instruction_push.mark(
            HookEvent.SUBAGENT_STOP, {"session_id": SESSION}, scope_dir=project, spec=CLAUDE_CODE
        )
        assert _pending(project) == {SESSION}

    def test_a_session_start_removes_a_marker_past_its_limit(self, project: Path) -> None:
        """An install from before the gate has no tool-call hook to sweep, so the start does."""
        _mark(project, AGENT)
        stale = paths.instruction_pending_dir(project / ".zikaron") / f"{SESSION}.{AGENT}"
        old = time.time() - instruction_markers.PENDING_TTL_SECONDS - 60
        os.utime(stale, (old, old))
        _mark(project, None)
        assert _pending(project) == {SESSION}

    def test_an_id_that_cannot_name_a_file_marks_nothing(self, project: Path) -> None:
        instruction_push.mark(
            HookEvent.SUBAGENT_START,
            {"session_id": "../escape", "agent_id": AGENT},
            scope_dir=project,
            spec=CLAUDE_CODE,
        )
        assert _pending(project) == set()

    def test_a_harness_without_the_push_marks_nothing(self, project: Path) -> None:
        instruction_push.mark(
            HookEvent.SPAWN,
            {"session_id": SESSION, "source": "startup"},
            scope_dir=project,
            spec=KIRO,
        )
        assert _pending(project) == set()


class TestWhoIsPushed:
    def test_an_ordinary_subagent_is_pushed_its_prompt_once(
        self,
        project: Path,
        session_transcript: Path,
        push_spec: InstructionPush,
        surfaced: list[dict[str, object]],
    ) -> None:
        _agent(push_spec, session_transcript, AGENT)
        _mark(project, AGENT)
        assert _call(project, session_transcript, AGENT) == f"BLOCK for Task for {AGENT}."
        assert _call(project, session_transcript, AGENT) is None
        assert len(surfaced) == 1
        assert surfaced[0]["occasion"] == instruction_push.OCCASION
        assert _pending(project) == set()

    @pytest.mark.usefixtures("pending_agent")
    def test_a_harness_without_the_push_pushes_nothing(
        self, project: Path, surfaced: list[dict[str, object]]
    ) -> None:
        payload: dict[str, object] = {"session_id": SESSION, "agent_id": AGENT}
        assert instruction_push.run(payload, scope_dir=project, spec=KIRO, pid=1) is None
        unsafe: dict[str, object] = {**payload, "session_id": "../escape"}
        assert instruction_push.run(unsafe, scope_dir=project, spec=CLAUDE_CODE, pid=1) is None
        assert surfaced == []

    def test_no_marker_makes_no_request(
        self,
        project: Path,
        session_transcript: Path,
        push_spec: InstructionPush,
        surfaced: list[dict[str, object]],
    ) -> None:
        _agent(push_spec, session_transcript, AGENT)
        assert _call(project, session_transcript, AGENT) is None
        assert surfaced == []

    @pytest.mark.usefixtures("surfaced")
    def test_several_agents_are_each_pushed_their_own_instruction(
        self, project: Path, session_transcript: Path, push_spec: InstructionPush
    ) -> None:
        for agent in (AGENT, OTHER):
            _agent(push_spec, session_transcript, agent)
            _mark(project, agent)
        assert _call(project, session_transcript, OTHER) == f"BLOCK for Task for {OTHER}."
        assert _pending(project) == {f"{SESSION}.{AGENT}"}
        assert _call(project, session_transcript, AGENT) == f"BLOCK for Task for {AGENT}."

    def test_a_parallel_batch_pushes_once(
        self,
        project: Path,
        session_transcript: Path,
        push_spec: InstructionPush,
        surfaced: list[dict[str, object]],
    ) -> None:
        _agent(push_spec, session_transcript, AGENT)
        _mark(project, AGENT)
        barrier = threading.Barrier(6)
        results: list[str | None] = []

        def call() -> None:
            barrier.wait()
            results.append(_call(project, session_transcript, AGENT))

        threads = [threading.Thread(target=call) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert len(surfaced) == 1
        assert sum(result is not None for result in results) == 1

    @pytest.mark.parametrize(
        "definition", [CONSOLIDATOR_AGENT_NAME, DOCUMENTER_AGENT_NAME, ORCHESTRATOR_AGENT_NAME]
    )
    def test_an_excluded_definition_is_never_pushed_whatever_its_type_says(
        self,
        project: Path,
        session_transcript: Path,
        push_spec: InstructionPush,
        surfaced: list[dict[str, object]],
        definition: str,
    ) -> None:
        """A teammate's `agent_type` is its name; its record names what it is."""
        _agent(push_spec, session_transcript, AGENT, definition=definition)
        _mark(project, AGENT)
        assert _call(project, session_transcript, AGENT, agent_type="chosen-name") is None
        assert surfaced == []

    def test_an_agent_with_no_readable_record_is_not_pushed_and_says_so(
        self, project: Path, session_transcript: Path, surfaced: list[dict[str, object]]
    ) -> None:
        _mark(project, AGENT)
        assert _call(project, session_transcript, AGENT) is None
        assert surfaced == []
        assert f"{instruction_push.INSTRUCTION_UNREAD} {instruction_push.LOG_DETAIL}" in (
            _hook_log(project)
        )

    def test_a_main_session_is_never_pushed_and_logs_nothing(
        self, project: Path, session_transcript: Path, surfaced: list[dict[str, object]]
    ) -> None:
        records.write(
            session_transcript,
            [records.user("A typed prompt."), records.assistant(records.tool_use())],
        )
        _mark(project, None)
        assert _call(project, session_transcript, None, agent_type=None) is None
        assert _call(project, session_transcript, None, agent_type="memory-researcher") is None
        assert surfaced == []
        assert _hook_log(project) == ""

    @pytest.mark.usefixtures("surfaced")
    @pytest.mark.parametrize("agent_type", ["probe-mate", None], ids=["typed", "untyped"])
    def test_a_tmux_teammate_is_pushed_its_message(
        self, project: Path, session_transcript: Path, agent_type: str | None
    ) -> None:
        """Typed or not: one spawned with no type runs no `--agent`, and may carry none."""
        records.write(
            session_transcript,
            [
                records.user(records.message("Run the probe.")),
                records.assistant(records.tool_use()),
            ],
        )
        _mark(project, None)
        assert _call(project, session_transcript, None, agent_type=agent_type) == (
            "BLOCK for Run the probe."
        )

    @pytest.mark.usefixtures("surfaced")
    def test_a_tmux_teammates_marker_past_its_limit_is_still_its_own_to_claim(
        self, project: Path, session_transcript: Path
    ) -> None:
        """Its last idle set it, and its next message may come a day later; the sweep its own
        call runs must not take it first."""
        records.write(
            session_transcript,
            [records.user(records.message("Run the probe.")), records.api_request()],
        )
        _mark(project, None)
        marker = paths.instruction_pending_dir(project / ".zikaron") / SESSION
        old = time.time() - instruction_markers.PENDING_SESSION_TTL_SECONDS - 60
        os.utime(marker, (old, old))
        assert _call(project, session_transcript, None) == "BLOCK for Run the probe."
        assert _pending(project) == set()

    @pytest.mark.parametrize(
        "definition", [CONSOLIDATOR_AGENT_NAME, DOCUMENTER_AGENT_NAME, ORCHESTRATOR_AGENT_NAME]
    )
    def test_an_excluded_tmux_teammate_is_never_pushed_and_logs_nothing(
        self,
        project: Path,
        session_transcript: Path,
        surfaced: list[dict[str, object]],
        definition: str,
    ) -> None:
        """A session of its own, named by its `agent_type` alone: the cell that would hand a
        consolidator spawned by name under tmux the search D7 withholds."""
        records.write(
            session_transcript,
            [
                records.user(records.message("Consolidate the journal.")),
                records.assistant(records.tool_use()),
            ],
        )
        _mark(project, None)
        assert _call(project, session_transcript, None, agent_type=definition) is None
        assert surfaced == []
        assert _hook_log(project) == ""
        assert _pending(project) == set()

    def test_an_instruction_of_an_unmeasured_shape_is_logged_not_pushed(
        self,
        project: Path,
        session_transcript: Path,
        push_spec: InstructionPush,
        surfaced: list[dict[str, object]],
    ) -> None:
        _agent(
            push_spec,
            session_transcript,
            AGENT,
            transcript=[
                records.user("The task."),
                records.assistant(records.tool_use()),
                records.user([records.tool_result()]),
                records.assistant(records.tool_use()),
            ],
        )
        _mark(project, AGENT)
        assert _call(project, session_transcript, AGENT) is None
        assert surfaced == []
        assert instruction_push.INSTRUCTION_UNREAD in _hook_log(project)


class TestALostPushLeavesATrace:
    def test_no_service_listening_writes_a_line(
        self,
        project: Path,
        session_transcript: Path,
        push_spec: InstructionPush,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(connect, "connect_if_serving", lambda *_a, **_k: None)
        _agent(push_spec, session_transcript, AGENT)
        _mark(project, AGENT)
        assert _call(project, session_transcript, AGENT) is None
        assert f"{instruction_push.NOT_SERVING} {instruction_push.LOG_DETAIL}" in (
            _hook_log(project)
        )

    def test_a_service_still_loading_writes_a_line(
        self,
        project: Path,
        session_transcript: Path,
        push_spec: InstructionPush,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def _loading(*_args: object, **_kwargs: object) -> connect.Connection:
            near, far = socket.socketpair()
            far.close()
            health = connect.Health(store_path="/x", store_id="y", model_loaded=False)
            return connect.Connection(sock=near, cold_start=False, health=health)

        monkeypatch.setattr(connect, "connect_if_serving", _loading)
        _agent(push_spec, session_transcript, AGENT)
        _mark(project, AGENT)
        assert _call(project, session_transcript, AGENT) is None
        assert f"starting {instruction_push.LOG_DETAIL}" in _hook_log(project)

    @pytest.mark.parametrize(
        ("raised", "kind"),
        [(rpc.NotSentError(), "deadline_exceeded"), (TimeoutError(), "unanswered")],
    )
    @pytest.mark.usefixtures("surfaced", "pending_agent")
    def test_a_late_push_writes_its_kind(
        self,
        project: Path,
        session_transcript: Path,
        monkeypatch: pytest.MonkeyPatch,
        raised: Exception,
        kind: str,
    ) -> None:
        def _late(_sock: socket.socket, **_kwargs: object) -> str:
            raise raised

        monkeypatch.setattr(rpc, "surface_once", _late)
        assert _call(project, session_transcript, AGENT) is None
        assert f"{kind} {instruction_push.LOG_DETAIL}" in _hook_log(project)

    @pytest.mark.usefixtures("surfaced")
    def test_any_other_failure_is_transport(
        self,
        project: Path,
        session_transcript: Path,
        push_spec: InstructionPush,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def _breaks(_sock: socket.socket, **_kwargs: object) -> str:
            raise ValueError("a malformed answer")

        monkeypatch.setattr(rpc, "surface_once", _breaks)
        _agent(push_spec, session_transcript, AGENT)
        _mark(project, AGENT)
        assert _call(project, session_transcript, AGENT) is None
        assert f"transport {instruction_push.LOG_DETAIL}" in _hook_log(project)

    @pytest.mark.usefixtures("pending_agent")
    def test_a_block_over_the_budget_is_pushed_whole_and_logged(
        self, project: Path, session_transcript: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        oversize = "x" * (CLAUDE_CODE.injection_budget + 1)

        def _connection(*_args: object, **_kwargs: object) -> connect.Connection:
            near, far = socket.socketpair()
            far.close()
            health = connect.Health(store_path="/x", store_id="y")
            return connect.Connection(sock=near, cold_start=False, health=health)

        monkeypatch.setattr(connect, "connect_if_serving", _connection)
        monkeypatch.setattr(rpc, "surface_once", lambda _sock, **_kwargs: oversize)
        assert _call(project, session_transcript, AGENT) == oversize
        assert f"push_oversize {instruction_push.LOG_DETAIL}" in _hook_log(project)

    @pytest.mark.usefixtures("pending_agent", "surfaced")
    def test_nothing_eligible_emits_nothing(
        self, project: Path, session_transcript: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An empty block is the prompt path's "prints nothing"; on the structured channel it
        would still be an envelope."""
        monkeypatch.setattr(rpc, "surface_once", lambda _sock, **_kwargs: "")
        assert _call(project, session_transcript, AGENT) is None
        assert _hook_log(project) == ""

    @pytest.mark.usefixtures("pending_agent", "surfaced")
    def test_a_refusal_writes_its_kind_and_code(
        self, project: Path, session_transcript: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _refused(_sock: socket.socket, **_kwargs: object) -> str:
            raise rpc.ServiceRejectionError(code=-32020, message="busy")

        monkeypatch.setattr(rpc, "surface_once", _refused)
        assert _call(project, session_transcript, AGENT) is None
        assert f"store_busy {instruction_push.LOG_DETAIL} -32020" in _hook_log(project)

    def test_a_diverging_session_is_the_tripwires(
        self,
        project: Path,
        session_transcript: Path,
        push_spec: InstructionPush,
        surfaced: list[dict[str, object]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv(CLAUDE_CODE.session_variable, "another-session")
        _agent(push_spec, session_transcript, AGENT)
        _mark(project, AGENT)
        assert _call(project, session_transcript, AGENT) is None
        assert surfaced == []
        assert "session_env_mismatch" in _hook_log(project)


class TestDispatch:
    def _run(self, payload: dict[str, object], monkeypatch: pytest.MonkeyPatch) -> str:
        output: list[str] = []
        monkeypatch.setattr("sys.stdin", __import__("io").StringIO(json.dumps(payload)))
        monkeypatch.setattr("sys.stdout.write", output.append)
        main_module._run()
        return "".join(output)

    @pytest.mark.usefixtures("surfaced")
    def test_a_tool_call_reaches_the_push_on_its_structured_channel(
        self,
        project: Path,
        session_transcript: Path,
        push_spec: InstructionPush,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _agent(push_spec, session_transcript, AGENT)
        _mark(project, AGENT)
        emitted = self._run(
            {
                "hook_event_name": push_spec.tool_trigger,
                "cwd": str(project),
                "session_id": SESSION,
                "agent_id": AGENT,
                "agent_type": "x",
                "transcript_path": str(session_transcript),
            },
            monkeypatch,
        )
        context = json.loads(emitted)["hookSpecificOutput"]
        assert context == {
            "hookEventName": push_spec.tool_trigger,
            "additionalContext": f"BLOCK for Task for {AGENT}.",
        }

    @pytest.mark.parametrize(
        ("fields", "expected"),
        [
            ({"hook_event_name": "SessionStart", "source": "startup"}, {SESSION}),
            ({"hook_event_name": "SubagentStart", "agent_id": AGENT}, {f"{SESSION}.{AGENT}"}),
            ({"hook_event_name": "TeammateIdle", "agent_type": "m43-mate"}, {SESSION}),
            ({"hook_event_name": "SubagentStop", "agent_id": AGENT}, set()),
        ],
    )
    def test_each_marking_trigger_sets_or_clears_its_marker(
        self,
        project: Path,
        monkeypatch: pytest.MonkeyPatch,
        fields: dict[str, object],
        expected: set[str],
    ) -> None:
        """Through the dispatcher, so an event dropped from its wiring is seen: without
        `TeammateIdle` no tmux teammate's later message is ever pushed."""
        monkeypatch.setattr(spawn_warm, "run", lambda **_kwargs: None)
        if fields["hook_event_name"] == "SubagentStop":
            _mark(project, AGENT)
        payload = {"cwd": str(project), "session_id": SESSION}
        self._run({**payload, **fields}, monkeypatch)
        assert _pending(project) == expected
