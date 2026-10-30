"""The code-knowledge skill run end to end by a real `kiro-cli chat`, from an install to
`up_to_date`, and again after a source moves.

The twin of `test_code_knowledge_claude_live.py`. What no hermetic test can check is kiro doing its
half (`design/code-knowledge.md` §5.2): that the installed skill has the session spawn the
orchestrator and wait for it, that the orchestrator spawns the installed documenter, that each runs
on the model and at the effort its profile names, and that the session's rules — not the spawned
agents' own — let the planner run and the documents be written. So this asserts what kiro logged
and what the run left behind: the spawns and each one's model and effort, from the launch's
`kiro.log`; the planner's verdict, each document's K14 front matter, and the module's knowledge
base, registered and answering a search.

The session's profile holds `read` and `subagent` beside the install's `@zikaron`, with allow rules
for `subagent`, `shell`, `fs_read` and `fs_write` over `./code-knowledge/**` beside the `mcp` and
`skill` rules the install writes. `shell` is the one selector left out, which measures that a
subagent's call needs the session's rule and not the session's tool. The agents run on the shipped
models, an Opus orchestrator at `high` effort being this test's cost, which the two-source module
bounds; the session runs on `claude-haiku-5.5`.

    .venv/bin/pytest -m integration_kiro tests/test_code_knowledge_kiro_live.py
"""

import asyncio
import json
import sqlite3
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Final

import pytest
from fastmcp import Client

from tests.kiro_live import Turn, chat, events, launch_log, require_kiro
from zikaron.code_knowledge import main as planner
from zikaron.core.knowledge.links import SourceLink, read_link
from zikaron.harness.spec import KIRO
from zikaron.install import main as install_main
from zikaron.install.code_knowledge import (
    DOCUMENTER_AGENT_NAME,
    DOCUMENTER_EFFORT,
    ORCHESTRATOR_AGENT_NAME,
    ORCHESTRATOR_EFFORT,
)
from zikaron.install.kiro_merge import DOCUMENTS_DIRECTORY
from zikaron.mcp.server import build_server
from zikaron.project import initialize
from zikaron.service import paths

pytestmark = pytest.mark.integration_kiro

_MODULE: Final = "pkg"
_CORPUS: Final = f"code-knowledge/{_MODULE}"
_SESSION_MODEL: Final = "claude-haiku-5.5"
_PRIMARY_NAME: Final = "zikaron-live-docs"

_SOURCES: Final = {
    "pkg/ledger.py": (
        '"""An append-only ledger of signed amounts."""\n\n'
        "from pkg.money import cents\n\n\n"
        "class Ledger:\n"
        "    def __init__(self) -> None:\n"
        "        self._entries: list[int] = []\n\n"
        "    def post(self, amount: str) -> None:\n"
        '        """Record an amount; a negative one is a refund."""\n'
        "        self._entries.append(cents(amount))\n\n"
        "    def balance(self) -> int:\n"
        "        return sum(self._entries)\n"
    ),
    "pkg/money.py": (
        '"""Parsing of decimal amounts into integer cents."""\n\n\n'
        "def cents(amount: str) -> int:\n"
        '    """`"12.34"` is 1234; a third decimal place is refused, never rounded."""\n'
        '    whole, _, fraction = amount.partition(".")\n'
        "    if len(fraction) > 2:\n"
        '        raise ValueError(f"{amount!r} has more than two decimal places")\n'
        '    return int(whole) * 100 + int(fraction.ljust(2, "0"))\n'
    ),
}

_MOVED: Final = (
    "\n\ndef dollars(cents: int) -> str:\n"
    '    """`1234` is `"12.34"`; the inverse of `cents`."""\n'
    '    return f"{cents // 100}.{cents % 100:02d}"\n'
)

_PRIMARY: Final[dict[str, object]] = {
    "name": _PRIMARY_NAME,
    "description": "A test agent for Zikaron's live code-knowledge check.",
    "prompt": "You are a test agent. Do exactly what the user asks, and nothing else.",
    "tools": ["read", "subagent"],
    "permissions": {
        "rules": [
            {"capability": "subagent", "effect": "allow"},
            {"capability": "shell", "effect": "allow"},
            {"capability": "fs_read", "effect": "allow"},
            {
                "capability": "fs_write",
                "match": [f"./{DOCUMENTS_DIRECTORY}/**"],
                "effect": "allow",
            },
        ]
    },
}

_PROMPT: Final = (
    "Document the module pkg of this project's code: load the zikaron-document-code skill and "
    "follow it, the module pkg being the only argument. Then reply with the run's report."
)


def _git(project: Path, *args: str) -> str:
    return subprocess.run(  # noqa: S603 — git with this file's own arguments.
        ["git", "-C", str(project), *args],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _project(root: Path) -> Path:
    project = root / "project"
    for relative, text in _SOURCES.items():
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    _git(project, "init", "--quiet")
    _git(project, "add", ".")
    _git(
        project,
        "-c",
        "user.name=live test",
        "-c",
        "user.email=live@test.invalid",
        "commit",
        "--quiet",
        "-m",
        "a package to document",
    )
    return project


def _install(project: Path) -> None:
    agents = project / ".kiro" / "agents"
    agents.mkdir(parents=True)
    profile = agents / f"{_PRIMARY_NAME}.json"
    profile.write_text(json.dumps(_PRIMARY, indent=2) + "\n", encoding="utf-8")
    argv = ["--project", str(project), "--harness", "kiro", "--agent", str(profile)]
    assert install_main.main(argv) == 0, "the install refused a profile it had just been given"
    assert initialize.main(["--project", str(project)]) == 0, (
        "`zikaron init` could not create the store — see .zikaron/service.log"
    )


def _plan(project: Path, capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    capsys.readouterr()
    status = planner.main(["plan", "--project", str(project), "--module", _MODULE])
    captured = capsys.readouterr()
    assert status == 0, captured.err
    plan = json.loads(captured.out)
    assert isinstance(plan, dict)
    return plan


def _corpora(project: Path) -> list[str]:
    db_path = paths.store_db_path(paths.store_dir(project))
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        registry = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'knowledge_bases'"
        ).fetchone()
        if registry is None:
            return []
        return sorted(str(row[0]) for row in connection.execute("SELECT name FROM knowledge_bases"))
    finally:
        connection.close()


async def _search_once_built(project: Path, query: str) -> str:
    """The module's knowledge base searched for `query` once its build reports `ok`."""
    async with Client(build_server("primary", scope_dir=project)) as client:
        for _ in range(120):
            status = await client.call_tool("zikaron_knowledge_status", {"knowledge_base": _CORPUS})
            if '"state": "ok"' in json.dumps(status.structured_content):
                break
            await asyncio.sleep(1)
        found = await client.call_tool(
            "zikaron_knowledge_search", {"query": query, "knowledge_bases": [_CORPUS]}
        )
        return json.dumps(found.structured_content)


def _starts(turn: Turn, agent: str) -> list[dict[str, object]]:
    return [
        start
        for start in events(launch_log(turn.session_id), "invoke_subagent.starting")
        if start.get("subagentId") == agent
    ]


def _assert_document(project: Path, relative: str) -> Path:
    document = project / DOCUMENTS_DIRECTORY / f"{relative}.md"
    assert document.is_file(), f"no document for {relative}"
    link = read_link(document.read_text(encoding="utf-8"))
    assert isinstance(link, SourceLink), f"{document} declares no well-formed K14 link: {link}"
    assert link.path == relative
    assert link.blob == _git(project, "hash-object", relative).strip()
    return document


def test_the_skill_documents_a_module_through_the_orchestrator_and_again_once_it_moves(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    record_property: Callable[[str, object], None],
) -> None:
    require_kiro()
    project = _project(tmp_path)
    _install(project)
    assert _plan(project, capsys)["up_to_date"] is False

    first = chat(project, _PRIMARY_NAME, _PROMPT, model=_SESSION_MODEL)
    assert first.of_type("runError") == [], first.diagnosis()
    plan = _plan(project, capsys)
    assert plan["up_to_date"] is True, f"the run left work undone: {plan}. {first.diagnosis()}"

    orchestrators = _starts(first, ORCHESTRATOR_AGENT_NAME)
    documenters = _starts(first, DOCUMENTER_AGENT_NAME)
    assert orchestrators, "the session spawned no zikaron-code-orchestrator"
    assert len(documenters) >= len(_SOURCES), f"too few documenters were spawned: {documenters}"
    for start, model, effort in (
        *((start, KIRO.orchestrator_model, ORCHESTRATOR_EFFORT) for start in orchestrators),
        *((start, KIRO.documenter_model, DOCUMENTER_EFFORT) for start in documenters),
    ):
        assert (start.get("modelId"), start.get("effortLevel"), start.get("effortOverride")) == (
            model,
            effort,
            True,
        ), start

    for relative in _SOURCES:
        _assert_document(project, relative)
    assert (project / DOCUMENTS_DIRECTORY / _MODULE / "README.md").is_file()
    assert _corpora(project) == [_CORPUS]
    assert "money.py" in asyncio.run(_search_once_built(project, "integer cents decimal places"))

    moved = project / "pkg" / "money.py"
    before = _assert_document(project, "pkg/money.py").stat().st_ino
    moved.write_text(_SOURCES["pkg/money.py"] + _MOVED, encoding="utf-8")
    second = chat(project, _PRIMARY_NAME, _PROMPT, model=_SESSION_MODEL)
    assert second.of_type("runError") == [], second.diagnosis()
    assert _plan(project, capsys)["up_to_date"] is True, second.diagnosis()
    after = _assert_document(project, "pkg/money.py")
    assert after.stat().st_ino != before, "the moved source's document was not written anew"

    by_conversation: dict[str, list[str]] = {}
    for record in launch_log(second.session_id):
        message = record.get("message")
        conversation = record.get("conversationId")
        if not isinstance(message, str) or conversation == second.session_id:
            continue
        for evaluation in events([record], "acp.policy-eval.complete"):
            by_conversation.setdefault(str(conversation), []).append(str(evaluation.get("toolId")))
    record_property("subagent_tool_ids", json.dumps(by_conversation))
    print(f"subagent tool ids on the second run: {by_conversation}")
