"""kiro's V3 engine loads what we installed, driven by a real `kiro-cli chat` and a real model.

The twin of `test_install_claude_live.py`. Every other kiro test checks that we *wrote* the right
files, and `kiro-cli agent validate` accepts a profile V3 then refuses (`research/kiro-v3-probe.md`
§23), so only a real turn shows that V3 loads the profile, fires the hooks, serves the tools, and
grants what the rules say where every question is refused, as it is headless.

    .venv/bin/pytest -m integration_kiro tests/test_install_kiro_live.py

**Out of the default run**, for `integration_kiro`'s reason and a second one: each turn is a live
model call, costing money and minutes, whose output is not deterministic. One installed session is
driven through one turn and asserted on several ways, so a failure names its half without a second
call. The turns ask a model to call tools, and a model may decline, so these are the places a
model's choice can turn this tier red.

The test writes its own primary profile, in V3's shape, with `subagent` granted, which the install
leaves to the user. `--require-mcp-startup` is passed because kiro starts the first turn without
waiting for MCP servers (`research/kiro-v3-probe.md` §8).
"""

import asyncio
import json
import sqlite3
import subprocess
from pathlib import Path
from typing import Final, NamedTuple

import pytest
from fastmcp import Client

from tests.kiro_live import TURN_TIMEOUT, Turn, chat, events, launch_log, require_kiro
from zikaron.core.code_knowledge.document import front_matter
from zikaron.harness.spec import KIRO
from zikaron.install import main as install_main
from zikaron.install.kiro_merge import DOCUMENTS_DIRECTORY
from zikaron.mcp.server import build_server
from zikaron.service import paths

pytestmark = pytest.mark.integration_kiro

#: The cheapest model `--list-models` offers, for every agent the test runs.
_MODEL: Final = "claude-haiku-5.5"

_PRIMARY_NAME: Final = "zikaron-live"

#: `fs_read` is what every measured consolidation run's primary carried; `subagent` is the grant
#: the install leaves to the user.
_PRIMARY_RULES: Final[tuple[dict[str, object], ...]] = (
    {"capability": "fs_read", "effect": "allow"},
    {"capability": "subagent", "effect": "allow"},
)

#: The user's own profile, in V3's shape.
_PRIMARY: Final[dict[str, object]] = {
    "name": _PRIMARY_NAME,
    "description": "A test agent for Zikaron's live install check.",
    "prompt": "You are a test agent. Do exactly what the user asks, and nothing else.",
    "tools": ["read", "subagent"],
    "permissions": {"rules": list(_PRIMARY_RULES)},
}

_GIST: Final = "zikaron live kiro check: the installed server is reachable from a real V3 turn"

_CONSOLIDATE: Final = (
    "Consolidate this project's memory: load the zikaron-consolidate skill and follow it. Then "
    "reply with the single word: done."
)


def _install(project: Path, primary: dict[str, object] = _PRIMARY) -> None:
    agents = project / ".kiro" / "agents"
    agents.mkdir(parents=True)
    profile = agents / f"{_PRIMARY_NAME}.json"
    profile.write_text(json.dumps(primary, indent=2) + "\n", encoding="utf-8")
    argv = ["--project", str(project), "--harness", "kiro", "--agent", str(profile)]
    status = install_main.main([*argv, "--model", _MODEL])
    assert status == 0, "the install refused on a profile it had just been given"


def _chat(project: Path, agent: str, prompt: str) -> Turn:
    return chat(project, agent, prompt, model=_MODEL)


def _events(project: Path) -> list[tuple[str, str, str]]:
    """`(session_id, client_kind, kind)` for every event in the project's store, read-only."""
    db_path = paths.store_db_path(paths.store_dir(project))
    assert db_path.is_file(), (
        "no store was created: the start hook did not run, or could not reach the service — "
        f"check {paths.hook_log_path(paths.store_dir(project))}"
    )
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return [
            (str(row[0]), str(row[1]), str(row[2]))
            for row in connection.execute("SELECT session_id, client_kind, kind FROM event")
        ]
    finally:
        connection.close()


class _Session(NamedTuple):
    project: Path
    turn: Turn
    events: list[tuple[str, str, str]]


@pytest.fixture(scope="class")
def session(tmp_path_factory: pytest.TempPathFactory) -> _Session:
    """One installed project, driven through one turn that writes a memory and consolidates it."""
    require_kiro()
    project = tmp_path_factory.mktemp("kiro-live")
    _install(project)
    turn = _chat(
        project,
        _PRIMARY_NAME,
        "First call the Zikaron tool zikaron_memory_remember exactly once, with gist "
        f"{_GIST!r} and content 'Written by the Zikaron live kiro test.' Then consolidate this "
        "project's memory: load the zikaron-consolidate skill and follow it. Then reply with the "
        "single word: done.",
    )
    return _Session(project=project, turn=turn, events=_events(project))


class TestAnInstalledV3Session:
    def test_the_installed_profile_loads_on_the_v3_engine(self, session: _Session) -> None:
        """V3 refuses a profile in V2's shape at `init`, as a `runError`, and runs the default
        agent instead (`research/kiro-v3-probe.md` §1)."""
        (started,) = session.turn.of_type("runStarted")
        data = started.get("data")
        assert isinstance(data, dict)
        assert data.get("engine") == "v3", session.turn.diagnosis()
        assert session.turn.of_type("runError") == [], session.turn.diagnosis()
        assert len(session.turn.of_type("runFinished")) == 1, session.turn.diagnosis()

    def test_the_prompt_hook_reaches_the_service(self, session: _Session) -> None:
        """Emitted by the service, on a request the hook made, on a trigger kiro fired, from an
        entry the installer wrote, and whatever the model chose to do."""
        kinds = {kind for _, client, kind in session.events if client == "hook"}
        assert "surface_call" in kinds, (
            "the prompt hook never reached the service; read "
            f"{paths.hook_log_path(paths.store_dir(session.project))}. {session.turn.diagnosis()}"
        )

    def test_an_mcp_tool_is_callable(self, session: _Session) -> None:
        kinds = {(client, kind) for _, client, kind in session.events}
        assert ("mcp", "remember") in kinds, session.turn.diagnosis()

    def test_every_client_resolves_the_harness_session_label(self, session: _Session) -> None:
        """The hook reads kiro's variable and the MCP clients read what it relayed, the
        consolidator's included, so every row carries the session kiro names
        (`design/harness.md` §"The session relay")."""
        by_client: dict[str, set[str]] = {}
        for session_id, client, _ in session.events:
            by_client.setdefault(client, set()).add(session_id)
        assert set(by_client) >= {"hook", "mcp", "consolidator"}, by_client
        expected = {str(session.turn.session_id)}
        assert all(labels == expected for labels in by_client.values()), (
            f"the clients resolved different labels: {by_client}; kiro named {expected}"
        )

    def test_consolidation_runs_end_to_end_through_the_skill(self, session: _Session) -> None:
        """The skill loads under the install's `skill` rule, the consolidator spawns under the
        test's `subagent` rule, and it disposes of the one journal entry."""
        consolidator = {kind for _, client, kind in session.events if client == "consolidator"}
        assert consolidator & {"promote", "merge", "discard"}, (
            f"the consolidator disposed of nothing; it logged {sorted(consolidator)}. "
            f"{session.turn.diagnosis()}"
        )


def test_the_upgrader_classifies_the_shipped_profiles_as_v3_ones(tmp_path: Path) -> None:
    """No shipped profile "would upgrade" or is "out of sync", the class the TUI answers by
    rebuilding a profile: the consolidator and the orchestrator are `v3-only` — their `tools` hold
    no `grep` or `glob`, and the consolidator's deny carries `exclude` — and the documenter `already
    universal`, as they were measured to run (`research/kiro-v3-probe.md` §17, §26, §53). No model
    is called."""
    require_kiro()
    project = tmp_path / "project"
    project.mkdir()
    _install(project)
    completed = subprocess.run(  # noqa: S603 — the argv is this file's own constants.
        [KIRO.harness_binary, "agent", "upgrade", "--dry-run", str(project / ".kiro" / "agents")],
        capture_output=True,
        text=True,
        timeout=TURN_TIMEOUT,
        check=False,
    )
    # The upgrader writes its table to stderr.
    report = completed.stdout + completed.stderr
    lines = report.splitlines()
    for profile, classification in (
        ("zikaron-consolidator.json", "v3-only"),
        ("zikaron-documenter.json", "already universal"),
        ("zikaron-code-orchestrator.json", "v3-only"),
    ):
        (line,) = [line for line in lines if profile in line]
        assert line.rstrip().endswith(classification), report


def _one_source(project: Path) -> tuple[Path, str]:
    """A git project holding one source file, and that file's blob hash."""
    project.mkdir()
    subprocess.run(["git", "init", "-q", str(project)], check=True)  # noqa: S603, S607 — fixed.
    source = project / "calc.py"
    source.write_text('def double(x: int) -> int:\n    """Twice x."""\n    return 2 * x\n')
    blob = subprocess.run(  # noqa: S603 — a fixed argv.
        ["git", "hash-object", str(source)],  # noqa: S607 — git on PATH, as every git test uses.
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return source, blob


def _documenter_prompt(project: Path, source: Path, blob: str, document: Path) -> str:
    return (
        f"Root: {project}\nSource: {source}\nDocument: {document}\nFront matter:\n"
        f"{front_matter('calc.py', blob)}"
    )


def test_the_documenter_reads_one_file_and_writes_another_unasked(tmp_path: Path) -> None:
    """Run directly as its own agent, headless, where any question is refused: so a document on
    disk is the documenter's rules measured, not a prompt answered."""
    require_kiro()
    project = tmp_path / "project"
    source, blob = _one_source(project)
    _install(project)
    document = project / "docs" / "calc.md"
    turn = _chat(project, "zikaron-documenter", _documenter_prompt(project, source, blob, document))
    assert turn.of_type("runError") == [], turn.diagnosis()
    assert document.is_file(), f"no document was written. {turn.diagnosis()}"
    assert document.read_text(encoding="utf-8").startswith(front_matter("calc.py", blob))


def test_a_spawned_documenter_writes_under_the_sessions_scoped_write_rule(tmp_path: Path) -> None:
    """A spawned agent may do what the session's rules allow, its own allow rules adding nothing:
    under a session with no write rule the documenter's write asks, and headless that refuses it
    (`research/kiro-v3-probe.md` §28, §54). The rule the install's note names is what lets it
    write."""
    require_kiro()
    project = tmp_path / "project"
    source, blob = _one_source(project)
    write: dict[str, object] = {
        "capability": "fs_write",
        "match": [f"./{DOCUMENTS_DIRECTORY}/**"],
        "effect": "allow",
    }
    primary = {**_PRIMARY, "permissions": {"rules": [*_PRIMARY_RULES, write]}}
    _install(project, primary)
    document = project / DOCUMENTS_DIRECTORY / "calc.py.md"
    turn = _chat(
        project,
        _PRIMARY_NAME,
        "Spawn the zikaron-documenter subagent exactly once, giving it exactly this text as its "
        "prompt, and nothing else:\n"
        f"{_documenter_prompt(project, source, blob, document)}\n"
        "Then reply with the single word: done.",
    )
    assert turn.of_type("runError") == [], turn.diagnosis()
    assert document.is_file(), f"no document was written. {turn.diagnosis()}"
    assert document.read_text(encoding="utf-8").startswith(front_matter("calc.py", blob))


#: The smallest threshold the configuration admits, so a group of a few short records spills.
_SPILL_THRESHOLD: Final = 4096


async def _remember(project: Path, records: list[tuple[str, str]]) -> None:
    """Write `records` through the primary MCP server in-process, which starts the project's
    service as an agent's would."""
    async with Client(build_server("primary", scope_dir=project)) as client:
        for gist, content in records:
            await client.call_tool("zikaron_memory_remember", {"gist": gist, "content": content})


def test_a_spilled_group_is_read_from_the_stores_spill_directory(tmp_path: Path) -> None:
    """A group over the threshold is written to `.zikaron/spill/`, which the consolidator's rules
    let it read and nothing else, and the consolidator reads it and decides the group
    (`design/architecture.md` §"A result too large to deliver — the client spills it to a file").
    The read is asserted from `kiro.log`'s `acp.policy-eval.complete` line for it, so a read asked
    and refused is told apart from one never tried."""
    require_kiro()
    project = tmp_path / "project"
    project.mkdir()
    _install(project)
    store = paths.store_dir(project)
    store.mkdir(mode=0o700)
    paths.project_config_path(store).write_text(
        f"[consolidation]\nspill_threshold = {_SPILL_THRESHOLD}\n", encoding="utf-8"
    )
    # Each record alone is over the threshold, so a group spills however the records are grouped.
    detail = "The flaky integration test reconnects to the broker after a dropped socket. " * 80
    asyncio.run(
        _remember(
            project,
            [
                (f"integration test {n} reconnects to the broker after a dropped socket", detail)
                for n in range(3)
            ],
        )
    )
    turn = _chat(project, _PRIMARY_NAME, _CONSOLIDATE)
    assert turn.of_type("runError") == [], turn.diagnosis()
    assert paths.spill_dir(store).is_dir(), f"no group was spilled. {turn.diagnosis()}"
    reads = [
        evaluation
        for evaluation in events(launch_log(turn.session_id), "acp.policy-eval.complete")
        if evaluation.get("toolId") == "read_file"
    ]
    assert {"toolId": "read_file", "effect": "allow", "capability": "fs_read"} in reads, reads
    consolidator = {kind for _, client, kind in _events(project) if client == "consolidator"}
    assert consolidator & {"promote", "merge", "discard"}, (
        f"the consolidator decided nothing; it logged {sorted(consolidator)}. {turn.diagnosis()}"
    )
