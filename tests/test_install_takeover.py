"""Invoking consolidation again takes over a stuck run, through the real client path.

Integration tier. This is the other half of what a clean install has to demonstrate, and it earns
its own file because the mechanism spans three processes that normally never meet: a worker holding
a lease, the service that granted it, and a fresh consolidator client whose own bridge is the only
thing that can displace it.

The reasoning behind the mechanism, restated because it is what makes an unconditional takeover
safe rather than reckless: nothing inside the store can tell a stopped worker from a slow one — a
lease is a timer, and a pid check answers whether a process exists, not whether it will progress.
The
one piece of real liveness evidence is outside the store: a human invoking the skill again. So an
explicit `memory_plan_groups` takes the run over, and the displaced run is closed `taken_over`
rather than
`abandoned`, because a user retrying in one kiro session presents the same `session_id` and only a
different pid.
"""

import json
import os
import socket
import sqlite3
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Final

import pytest
from fastmcp import Client

from tests.test_install_e2e import (
    _await_service,
    _call,
    _hook_command,
    _install,
    _mcp_command,
    _run_hook,
    _stdio,
    _stop_service,
)
from zikaron.core.errors import ErrorCode
from zikaron.service import paths

#: Same reasoning as `test_install_e2e.py`: everything real here is Zikaron's own, and the harness
#: binary is answered for. One assignment — a second `pytestmark` would replace this, not add to it.
pytestmark = [
    pytest.mark.integration,
    pytest.mark.usefixtures("stub_harness_binaries"),
]

_SESSION_ID: Final = "takeover-top-level-session"
_STRANDED_PID: Final = 999_999

_JOURNAL: Final = (
    ("the vendored parser rejects tabs in headers", "Indent with spaces; tabs raise KeyError."),
    ("the vendored parser also rejects trailing commas", "Strip them before parsing."),
)


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Path]:
    directory = tmp_path / "a-project-with-a-stuck-run"
    directory.mkdir()
    try:
        yield directory
    finally:
        _stop_service(directory)


def _rpc(project: Path, method: str, params: dict[str, Any]) -> dict[str, Any]:
    """One raw JSON-RPC call to this project's service, as a client that is not us would make it.

    Raw rather than through `zikaron.mcp.connection`, because the whole point is to stand in for a
    *stranger*: a worker with its own `(session_id, pid)` that this test never runs as a process.
    Reusing our own client would tie the fake holder's identity to this test's own pid.
    """
    runtime = paths.runtime_dir(xdg_runtime_dir=os.environ.get("XDG_RUNTIME_DIR"), uid=os.getuid())
    sock_path = paths.socket_path(runtime, paths.store_dir(project).resolve())
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(30.0)
    try:
        sock.connect(str(sock_path))
        request = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        sock.sendall((json.dumps(request) + "\n").encode("utf-8"))
        buffer = b""
        while not buffer.endswith(b"\n"):
            chunk = sock.recv(4096)
            if not chunk:
                raise AssertionError("the service closed the connection mid-response")
            buffer += chunk
    finally:
        sock.close()
    parsed = json.loads(buffer.decode("utf-8"))
    assert isinstance(parsed, dict)
    return parsed


def _result(project: Path, method: str, params: dict[str, Any]) -> dict[str, Any]:
    """The `result` of a raw call that must succeed."""
    parsed = _rpc(project, method, params)
    assert "error" not in parsed, parsed
    result = parsed["result"]
    assert isinstance(result, dict)
    return result


def _error(project: Path, method: str, params: dict[str, Any]) -> dict[str, Any]:
    """The `error` of a raw call that must be refused."""
    parsed = _rpc(project, method, params)
    assert "result" not in parsed, parsed
    error = parsed["error"]
    assert isinstance(error, dict)
    return error


def _runs(project: Path) -> list[dict[str, Any]]:
    """Every consolidation run, oldest first, read straight out of the store.

    The only way to observe the assertion this test exists for: `taken_over` is a stored status, and
    no RPC reports the status of a run the caller does not own. Read-only, and the service keeps the
    database open in WAL mode, so this neither blocks it nor sees an uncommitted state.
    """
    db_path = paths.store_db_path(paths.store_dir(project))
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT run_id, session_id, pid, status, expires_at FROM consolidation_run "
            "ORDER BY started_at, run_id"
        ).fetchall()
    finally:
        connection.close()
    return [dict(row) for row in rows]


async def _seed_journal(project: Path, mcp_command: str) -> list[str]:
    written: list[str] = []
    async with Client(_stdio(mcp_command, "primary", project)) as client:
        for gist, content in _JOURNAL:
            result = await _call(
                client, "zikaron_memory_remember", {"gist": gist, "content": content}
            )
            written.append(result["uuid"])
    return written


async def test_reinvoking_consolidation_takes_over_a_stranded_run(project: Path) -> None:
    agent_config = _install(project)
    hook_command = _hook_command(agent_config)
    mcp_command = _mcp_command(agent_config)

    _run_hook(
        hook_command,
        project,
        {"hook_event_name": "agentSpawn", "cwd": str(project), "session_id": _SESSION_ID},
    )
    _await_service(project)
    written = await _seed_journal(project, mcp_command)

    # A worker plans a run and then stops existing, holding an unexpired lease. `run_lease` defaults
    # to 1800 s, so nothing about this run expires during the test: only a takeover can displace it.
    stranded = _result(
        project,
        "memory_plan_groups",
        {
            "client": {
                "session_id": "a-worker-that-stopped",
                "kind": "consolidator",
                "pid": _STRANDED_PID,
            }
        },
    )
    assert stranded["status"] == "active"
    before = _runs(project)
    assert [run["status"] for run in before] == ["active"]
    assert before[0]["pid"] == _STRANDED_PID
    assert time.strftime("%Y-%m-%dT%H:%M:%S") < before[0]["expires_at"], (
        "the stranded lease must still be live, or expiry rather than takeover would explain the "
        "result"
    )

    # A stranger cannot simply serve itself the work: that is what makes the explicit takeover the
    # only path, and therefore what makes a human's second invocation the evidence it rests on.
    busy = _result(
        project,
        "memory_next_group",
        {"client": {"session_id": "somebody-else", "kind": "consolidator", "pid": 999_998}},
    )
    assert busy["busy"] is True
    assert busy["holder_pid"] == _STRANDED_PID

    # The skill's own path: a fresh consolidator client, whose bridge calls `memory_plan_groups`
    # lazily before the first `memory_next_group` it forwards.
    async with Client(_stdio(mcp_command, "consolidator", project)) as client:
        group = await _call(client, "zikaron_memory_next_group")
        assert not group.get("busy"), f"the takeover did not happen: {group}"
        assert not group.get("done"), "the replanned run served nothing, so the journal was lost"
        served = {entry["uuid"] for entry in group["journal_entries"]}
        assert served <= set(written)

        after = _runs(project)
        assert [run["status"] for run in after] == ["taken_over", "active"], after
        assert after[0]["run_id"] == before[0]["run_id"]
        assert after[0]["pid"] == _STRANDED_PID
        assert after[1]["pid"] != _STRANDED_PID
        assert group["run_id"] == after[1]["run_id"]

        # The displaced worker can commit nothing after the takeover instant: every write verb
        # requires its group's run to be owned by the caller *and* effectively active. Asserted as
        # the wire error rather than a status field, because that rung answers with `group_expired`
        # (-32011) — the displaced holder is told its own run is gone, which is exactly what it is.
        refused = _error(
            project,
            "memory_apply_discard",
            {
                "client": {
                    "session_id": "a-worker-that-stopped",
                    "kind": "consolidator",
                    "pid": _STRANDED_PID,
                },
                "group_id": group["group_id"],
                "absorb": [
                    {"uuid": row["uuid"], "expected_version": row["expected_version"]}
                    for row in group["journal_entries"][:1]
                ],
                "reason": "a write from the run that was taken over",
            },
        )
        assert refused["code"] == ErrorCode.GROUP_EXPIRED
