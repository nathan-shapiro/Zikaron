"""The code-knowledge skill run end to end by a real `claude`, from an install to `up_to_date`.

Every hermetic test of D39 checks what the installer writes and what the planner decides. What none
of them can check is the harness doing its half (`design/code-knowledge.md` §5.2): that the
installed skill has the session spawn the orchestrator, that the orchestrator can spawn the
installed documenter and wait for it, that a documenter's write lands where the planner looks, and
that a headless `-p` session stays alive until the orchestrator's run has finished. A rename
upstream of any of those leaves every install writing nothing, or the invoking session doing the
work itself. So this asserts only what the harness recorded and the run left behind — the
session's spawn and the orchestrator's documenter spawns, the planner's own verdict, each
document's K14 front matter as the planner reads it, and the corpus's registration — never what a
model says. The skill is invoked with no argument, so the run documents the whole project.

**Out of the default run**, as `integration_claude` is (`design/coding-standards.md` §4): it needs
a working `claude` and live model calls, a few documenters' worth.

    .venv/bin/pytest -m integration_claude tests/test_code_knowledge_claude_live.py
"""

import json
import os
import sqlite3
import subprocess
from pathlib import Path
from typing import Final

import pytest

from zikaron.code_knowledge import main as planner
from zikaron.core.knowledge.links import SourceLink, read_link
from zikaron.harness.spec import CLAUDE_CODE
from zikaron.install import harness
from zikaron.install import main as install_main
from zikaron.project import initialize
from zikaron.service import paths

pytestmark = pytest.mark.integration_claude

#: Four documents — the two sources, the install's `.mcp.json` and the README — each a
#: documenter's whole turn, behind the orchestrator.
_RUN_TIMEOUT: Final = 1500.0

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


def _require_claude() -> None:
    """Fail — never skip — when the binary is absent, as `test_install_claude_live.py` does."""
    name = CLAUDE_CODE.harness_binary
    assert harness.binary_is_available(name), (
        f"{name!r} is not on PATH: do not run `-m integration_claude` on this machine."
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


def _plan(project: Path, capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    capsys.readouterr()
    status = planner.main(["plan", "--project", str(project), "--module", "."])
    captured = capsys.readouterr()
    assert status == 0, captured.err
    plan = json.loads(captured.out)
    assert isinstance(plan, dict)
    return plan


def _spawns(records: list[dict[str, object]]) -> list[tuple[str, str]]:
    """The call id and `subagent_type` of every spawn the given messages made."""
    spawns = []
    for record in records:
        message = record.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        for block in content if isinstance(content, list) else []:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                arguments = block.get("input")
                if isinstance(arguments, dict) and "subagent_type" in arguments:
                    spawns.append((str(block.get("id")), str(arguments["subagent_type"])))
    return spawns


def _children(records: list[dict[str, object]], call: str) -> list[dict[str, object]]:
    """The messages of the subagent the spawn `call` started, which `-p` streams under its id."""
    return [r for r in records if r.get("parent_tool_use_id") == call]


def _corpora(project: Path) -> list[str]:
    db_path = paths.store_db_path(paths.store_dir(project))
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        # The registry is created by a store's first `knowledge_add`, so a run that never got there
        # has no table.
        registry = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'knowledge_bases'"
        ).fetchone()
        if registry is None:
            return []
        return sorted(str(row[0]) for row in connection.execute("SELECT name FROM knowledge_bases"))
    finally:
        connection.close()


def test_the_skill_documents_the_whole_project_to_up_to_date(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The planner's verdict before and after one headless invocation of the installed skill.

    `-p` waits for the background orchestrator, but by default for ten minutes at most, dropping
    what is unfinished; `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0` lifts the cap
    (`research/claude-code-background-subagents.md`, row 4), as the toy run did. The session's own
    model is `haiku`, since it only spawns the orchestrator — the orchestrator and the documenters
    run on the models the install wrote.
    """
    _require_claude()
    project = _project(tmp_path)
    status = install_main.main(["--project", str(project), "--harness", "claude-code"])
    assert status == 0, "the install refused a directory it had just been given"
    assert initialize.main(["--project", str(project)]) == 0, (
        "`zikaron init` could not create the store — see .zikaron/service.log"
    )
    before = _plan(project, capsys)
    assert before["up_to_date"] is False, "a project with no documents was reported up to date"

    try:
        result = subprocess.run(  # noqa: S603 — the argv is this file's own constant.
            [
                CLAUDE_CODE.harness_binary,
                "-p",
                "--model",
                "haiku",
                "--permission-mode",
                "bypassPermissions",
                "--output-format",
                "stream-json",
                "--verbose",
                "/zikaron-document-code",
            ],
            cwd=project,
            env={**os.environ, "CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS": "0"},
            capture_output=True,
            text=True,
            timeout=_RUN_TIMEOUT,
            check=False,
            stdin=subprocess.DEVNULL,
        )
        stdout, exited = result.stdout, str(result.returncode)
    except subprocess.TimeoutExpired as expired:
        # Killed with its orchestrator: what the planner says now is the diagnosis.
        stdout = (expired.stdout or b"").decode("utf-8", "replace")  # bytes even in text mode
        exited = f"never (killed at {_RUN_TIMEOUT:.0f} s)"
    records = []
    for line in stdout.splitlines():
        try:
            records.append(json.loads(line))
        except ValueError:
            continue
    report = next((str(r.get("result")) for r in records if r.get("type") == "result"), "")

    after = _plan(project, capsys)
    assert after["up_to_date"] is True, (
        f"the run left work undone: {after.get('work')}. claude exited {exited}; "
        f"its report: {report[-1500:]!r}"
    )
    session = [r for r in records if not r.get("parent_tool_use_id")]
    orchestrators = [call for call, kind in _spawns(session) if kind == "zikaron-code-orchestrator"]
    assert orchestrators, "the session spawned no zikaron-code-orchestrator"
    assert any(
        kind == "zikaron-documenter"
        for call in orchestrators
        for _, kind in _spawns(_children(records, call))
    ), "the orchestrator spawned no zikaron-documenter"
    documents = project / "code-knowledge"
    for relative in _SOURCES:
        document = documents / f"{relative}.md"
        assert document.is_file(), f"no document for {relative}"
        link = read_link(document.read_text(encoding="utf-8"))
        assert isinstance(link, SourceLink), f"{document} declares no well-formed K14 link: {link}"
        assert link.path == relative
        assert link.blob == _git(project, "hash-object", relative).strip()
    assert (documents / "README.md").is_file(), "the project's README was never written"
    assert _corpora(project) == ["code-knowledge"], (
        "the run's last step did not register the whole project's corpus"
    )
