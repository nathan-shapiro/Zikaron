"""A clean install on a fresh directory does push, pull, write and a consolidation run.

Integration tier, and deliberately the least mocked test in the repository: every step below runs
the **installed console scripts as subprocesses**, driven by the exact command strings the installer
wrote into an agent config. That is the property this test exists for — every other test in the
suite calls Python functions, so none of them would notice a `command` pointing at the wrong
interpreter, a `--mode` argument spelled wrong, or an entry point that was never installed.

What it cannot do is drive kiro. So it exercises the same two things kiro does with what was
installed — run the hook command with a JSON payload on stdin, and speak MCP over stdio to the
server command — and the claim that kiro itself reads these files is checked by using them, not
here.
"""

import json
import os
import signal
import socket
import subprocess
import time
from collections.abc import Iterator
from contextlib import suppress
from pathlib import Path
from typing import Any, Final

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

from zikaron.install import main as install_main
from zikaron.install.entries import MCP_SERVER_NAME
from zikaron.install.writer import Targets
from zikaron.service import paths

pytestmark = pytest.mark.integration

_SESSION_ID: Final = "e2e-top-level-session"

#: Cold, this waits out a real `fastembed` load in a freshly spawned service.
_SERVICE_READY_DEADLINE: Final = 60.0

_MEMORIES: Final = (
    (
        "integration tests hang unless PGHOST is exported",
        "The integration suite blocks on connect with no error when PGHOST is unset; export "
        "PGHOST=localhost before running it.",
    ),
    (
        "integration tests also need PGPORT on this machine",
        "PGPORT defaults to 5432 in the library but the local cluster listens on 5433, so the "
        "integration suite fails to connect until PGPORT is exported too.",
    ),
    (
        "the protobuf codegen step fails silently when protoc is stale",
        "make gen exits 0 with an empty _pb2.py when protoc is older than 3.20; check protoc "
        "--version before trusting a regenerated stub.",
    ),
)


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "a-fresh-project"
    project.mkdir()
    return project


def _install(project: Path) -> dict[str, Any]:
    """Install into `project` and hand back the agent config the installer merged into."""
    agent = project / ".kiro" / "agents" / "mine.json"
    agent.parent.mkdir(parents=True)
    agent.write_text(
        json.dumps({"name": "mine", "description": "a user's own agent", "tools": ["subagent"]})
    )
    status = install_main.main(["--project", str(project), "--agent", str(agent)])
    assert status == 0, "the install refused on a machine where the real harness is present"
    document = json.loads(agent.read_text())
    assert isinstance(document, dict)
    return document


def _hook_command(agent_config: dict[str, Any]) -> str:
    """The `userPromptSubmit` command string, read back out of what was installed."""
    entries = agent_config["hooks"]["userPromptSubmit"]
    assert len(entries) == 1
    command = entries[0]["command"]
    assert isinstance(command, str)
    return command


def _mcp_command(agent_config: dict[str, Any]) -> str:
    command = agent_config["mcpServers"][MCP_SERVER_NAME]["command"]
    assert isinstance(command, str)
    return command


def _hook_env(session_id: str) -> dict[str, str]:
    """The environment kiro gives a hook: its own session id, and nothing Zikaron-specific.

    Taken from the payload the caller is about to send rather than from a module constant, because
    the two being *equal* is what makes this a top-level session — when they differ the hook
    correctly treats the invocation as a subagent one and suppresses everything, warm spawn
    included. An earlier version of this helper read a constant, and a second test file passing its
    own session id got silently suppressed: the service never started and the failure surfaced as a
    timeout waiting for it.
    """
    return {**os.environ, "KIRO_SESSION_ID": session_id}


def _run_hook(
    command: str, project: Path, payload: dict[str, object]
) -> subprocess.CompletedProcess[str]:
    """Run an installed hook `command` the way the harness runs it: through a shell.

    `shell=True` is fidelity rather than convenience, and it was a real gap. The harness executes
    this
    field through `/bin/bash -c` — measured, along with the failure that follows from it: an
    unquoted
    path containing a space produced `/bin/bash: line 1: /home/me/My: No such file or directory` and
    exit 127. Passing `[command]` to `subprocess.run` instead treats the whole string as one
    executable pathname, which is a *different* execution model and cannot see that class of defect
    at
    all.
    """
    session_id = payload.get("session_id")
    assert isinstance(session_id, str), "a kiro hook payload always carries its session id"
    return subprocess.run(  # noqa: S602 — a shell is the point: see this function's docstring.
        command,
        shell=True,
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=project,
        env=_hook_env(session_id),
        timeout=30,
        check=False,
    )


def _service_pid(project: Path) -> int | None:
    """This project's service pid from a real `health()` call, or `None` if nothing answers."""
    store_dir = paths.store_dir(project)
    if not store_dir.is_dir():
        return None
    runtime = paths.runtime_dir(xdg_runtime_dir=os.environ.get("XDG_RUNTIME_DIR"), uid=os.getuid())
    sock_path = paths.socket_path(runtime, store_dir.resolve())
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(5.0)
    try:
        sock.connect(str(sock_path))
        sock.sendall(b'{"jsonrpc": "2.0", "id": 1, "method": "health", "params": {}}\n')
        buffer = b""
        while not buffer.endswith(b"\n"):
            chunk = sock.recv(4096)
            if not chunk:
                return None
            buffer += chunk
    except OSError:
        return None
    finally:
        sock.close()
    pid = json.loads(buffer.decode("utf-8"))["result"]["pid"]
    assert isinstance(pid, int)
    return pid


def _await_service(project: Path) -> int:
    deadline = time.monotonic() + _SERVICE_READY_DEADLINE
    while time.monotonic() < deadline:
        pid = _service_pid(project)
        if pid is not None:
            return pid
        time.sleep(0.1)
    raise TimeoutError("no service answered health() for this project")


@pytest.fixture
def reaped(tmp_path: Path) -> Iterator[Path]:
    """A fresh project, with whatever service it started stopped again afterwards.

    Every test that can plausibly leave a service running gets checked this way, after one that did
    was found only by running `pgrep` by hand: a leaked service holds an open store and a live
    socket, and the next test's start-if-absent would find it instead of starting its own.
    """
    project = _project(tmp_path)
    try:
        yield project
    finally:
        _stop_service(project)


def _stop_service(project: Path) -> None:
    """SIGTERM whatever service answers for this project, and wait for it to actually go.

    Waiting matters rather than only signalling: an idle service that has unlinked its socket but
    not yet exited still holds the store open, and this project's directory is about to be removed
    underneath it.
    """
    pid = _service_pid(project)
    if pid is None:
        return
    with suppress(ProcessLookupError):
        os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.05)
    raise TimeoutError(f"service pid {pid} did not exit")


def _stdio(command: str, mode: str, project: Path) -> StdioTransport:
    """A real `zikaron-mcp` subprocess in `project`, exactly as kiro spawns one.

    `cwd` is the load-bearing argument: the client scopes its store to its own working directory,
    and kiro was measured to spawn an MCP server in the workspace directory — so a test spawning it
    anywhere else would be testing a different store than the hooks use.
    """
    return StdioTransport(
        command=command,
        args=["--mode", mode],
        cwd=str(project),
        env={**os.environ, "KIRO_SESSION_ID": _SESSION_ID},
    )


async def _call(client: Client[Any], tool: str, args: dict[str, Any] | None = None) -> Any:  # noqa: ANN401 — a tool's result shape is the wire's, deliberately not narrowed here.
    """One tool call, returning whatever the wire returned.

    Untyped on purpose: these are the JSON shapes the design states, and asserting against them is
    the test's job — a typed wrapper here would be a second, test-local model of the tool surface
    that could agree with itself while disagreeing with the server.
    """
    result = await client.call_tool(tool, args or {})
    return result.data


async def test_a_clean_install_does_write_pull_push_and_a_consolidation_run(reaped: Path) -> None:
    project = reaped
    agent_config = _install(project)
    hook_command = _hook_command(agent_config)
    mcp_command = _mcp_command(agent_config)

    # 1. `agentSpawn`: the write policy reaches stdout, and the detached warm helper starts a
    #    service for a store that does not exist yet.
    spawned = _run_hook(
        hook_command,
        project,
        {"hook_event_name": "agentSpawn", "cwd": str(project), "session_id": _SESSION_ID},
    )
    assert spawned.returncode == 0
    assert spawned.stderr == ""
    assert "## Project memory (Zikaron)" in spawned.stdout
    assert "Never record a secret" in spawned.stdout
    _await_service(project)

    # 2. Write: three memories through the real primary MCP server.
    written: list[str] = []
    async with Client(_stdio(mcp_command, "primary", project)) as client:
        tools = {tool.name for tool in await client.list_tools()}
        assert tools == {
            "zikaron_search",
            "zikaron_fetch",
            "zikaron_remember",
            "zikaron_amend",
            "zikaron_retire",
        }
        for gist, content in _MEMORIES:
            remembered = await _call(client, "zikaron_remember", {"gist": gist, "content": content})
            written.append(remembered["uuid"])

        # 3. Pull: the store answers a query with the memory that matches it.
        found = await _call(client, "zikaron_search", {"query": "integration tests hang"})
        assert any(row["uuid"] == written[0] for row in found)

    # 4. Push: the same store, reached by the hook, prints an injected block naming that memory.
    pushed = _run_hook(
        hook_command,
        project,
        {
            "hook_event_name": "userPromptSubmit",
            "cwd": str(project),
            "session_id": _SESSION_ID,
            "prompt": "why do the integration tests hang on connect?",
        },
    )
    assert pushed.returncode == 0
    assert pushed.stderr == ""
    assert "## Project memory — reference only" in pushed.stdout
    assert _MEMORIES[0][0] in pushed.stdout
    assert written[0] in pushed.stdout, "the block prints whole uuids so a fetch takes one call"

    # 5. Consolidate: a real consolidator client, which plans the run on its first served group.
    promoted: list[str] = []
    async with Client(_stdio(mcp_command, "consolidator", project)) as client:
        assert {tool.name for tool in await client.list_tools()} == {
            "zikaron_next_group",
            "zikaron_merge",
            "zikaron_promote",
            "zikaron_discard",
        }
        for _ in range(len(_MEMORIES) + 1):
            group = await _call(client, "zikaron_next_group")
            if group.get("done"):
                break
            assert not group.get("busy"), f"the takeover bridge did not claim the run: {group}"
            absorb = [
                {"uuid": entry["uuid"], "expected_version": entry["expected_version"]}
                for entry in group["journal_entries"]
            ]
            outcome = await _call(
                client,
                "zikaron_promote",
                {
                    "group_id": group["group_id"],
                    "gist": group["journal_entries"][0]["gist"],
                    "content": group["journal_entries"][0]["content"],
                    "absorb": absorb,
                },
            )
            assert outcome["group_complete"] is True
            assert outcome["remaining_uuids"] == []
            promoted.append(outcome["uuid"])
        else:
            pytest.fail("the consolidator never reached {done: true}")
    assert promoted, "the run served no groups at all"

    # 6. The journal is consolidated: every promoted record is long-term, and nothing was lost.
    async with Client(_stdio(mcp_command, "primary", project)) as client:
        fetched = await _call(client, "zikaron_fetch", {"uuids": [*promoted, *written]})
        assert fetched["missing"] == [], "consolidation must never delete a row, only retire it"
        by_uuid = {record["uuid"]: record for record in fetched["records"]}
        assert {by_uuid[uuid]["tier"] for uuid in promoted} == {"long_term"}
        # Every original journal row is either the promoted record itself — an in-place promotion
        # flips the row rather than copying it — or retired against one.
        for uuid in written:
            record = by_uuid[uuid]
            assert record["tier"] == "long_term" or record["superseded_by"] in promoted


async def test_the_installed_skill_and_consolidator_config_are_where_kiro_looks(
    tmp_path: Path,
) -> None:
    """No subprocess: the two artefacts have to sit at the paths kiro discovers agents and skills
    at, and nothing else in this file would fail if they moved."""
    project = _project(tmp_path)
    _install(project)
    targets = Targets(project=project)
    assert targets.consolidator_config == project / ".kiro/agents/zikaron-consolidator.json"
    assert targets.skill_file == project / ".kiro/skills/zikaron-consolidate/SKILL.md"
    assert json.loads(targets.consolidator_config.read_text())["name"] == "zikaron-consolidator"
    assert targets.skill_file.read_text().startswith("---\nname: zikaron-consolidate\n")
