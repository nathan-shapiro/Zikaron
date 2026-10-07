"""The edit guards in a real Claude Code session (`design/build-plan.md` §M37, "A live test").

One headless session under `--permission-mode bypassPermissions` is given exact commands, so that
neither the edit nor the override is the model's choice: a `sed -i` the guard must deny, the same
form with a valid override, and an `Edit`. What is asserted is what the harness recorded, never what
the model says:

- the deny is the `sed -i` call's `tool_result` in the `stream-json` output, and the file is
  unchanged by it — under `bypassPermissions`, which is itself one of §2's rows;
- the override's command ran (the file changed), and its acknowledgement reached the model, which is
  recorded only in the session's transcript, as an attachment;
- the `Edit` was followed by the nudge, also an attachment.

**The project lives under `~/.cache/zikaron-live-tests/`, never `tmp_path`**: pytest's temporary
directories lie under `/tmp` or `$TMPDIR`, where the guard exempts the commands and suppresses the
nudge, so a project there would test nothing. **The override's withdrawing rather than granting is
not observable here** — under `bypassPermissions` no decision and `allow` look the same — so the
hermetic `tests/test_guard_main.py` holds it, on the hook's JSON.

    .venv/bin/pytest -m integration_claude tests/test_guard_claude_live.py
"""

import json
import os
import shutil
import subprocess
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Final

import pytest

from zikaron.harness.spec import CLAUDE_CODE
from zikaron.install import harness
from zikaron.install import main as install_main

pytestmark = pytest.mark.integration_claude

_TURN_TIMEOUT: Final = 300.0
_DENIED: Final = "sed -i 's/beta/BETA/' target.txt"
_OVERRIDDEN: Final = "sed -i 's/gamma/GAMMA/' target.txt #ZIKARON-FORCE #Reason: live guard test"
#: The model is told to keep the trailing comment because, measured, a small model otherwise drops
#: it as noise — and the override is then the model's choice, which this test must not depend on.
_PROMPT: Final = (
    "Do these three steps in order, each exactly as written, and carry on to the next even if one "
    f"fails. Step 1: run this Bash command, character for character: `{_DENIED}`. Step 2: run this "
    f"Bash command, character for character, including its trailing # comment: `{_OVERRIDDEN}`. "
    "Step 3: use the Edit tool to replace the word alpha with ALPHA in target.txt. Then reply with "
    "the single word: done."
)


@pytest.fixture
def project() -> Iterator[Path]:
    root = Path.home() / ".cache" / "zikaron-live-tests" / uuid.uuid4().hex
    root.mkdir(parents=True)
    (root / "target.txt").write_text("alpha beta gamma\n", encoding="utf-8")
    try:
        yield root
    finally:
        shutil.rmtree(root)


def _session(project: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """One headless turn: the `stream-json` records, and the session transcript's records."""
    assert harness.binary_is_available(CLAUDE_CODE.harness_binary), (
        f"{CLAUDE_CODE.harness_binary!r} is not on PATH: do not run -m integration_claude here, "
        "or `HarnessSpec.harness_binary` names the wrong binary."
    )
    result = subprocess.run(  # noqa: S603 — the argv is this file's own constants.
        [
            CLAUDE_CODE.harness_binary,
            "-p",
            _PROMPT,
            "--model",
            "haiku",
            "--permission-mode",
            "bypassPermissions",
            "--output-format",
            "stream-json",
            "--verbose",
        ],
        cwd=project,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=_TURN_TIMEOUT,
        check=False,
        stdin=subprocess.DEVNULL,
    )
    stream = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
    sessions = {record["session_id"] for record in stream if "session_id" in record}
    assert len(sessions) == 1, f"no session in the stream; stderr: {result.stderr[-800:]!r}"
    (session,) = sessions
    (transcript,) = (Path.home() / ".claude" / "projects").glob(f"*/{session}.jsonl")
    lines = transcript.read_text(encoding="utf-8").splitlines()
    return stream, [json.loads(line) for line in lines if line.strip()]


def _tool_results(stream: list[dict[str, Any]]) -> list[str]:
    results = []
    for record in stream:
        for block in (record.get("message") or {}).get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                content = block.get("content")
                results.append(content if isinstance(content, str) else json.dumps(content))
    return results


def test_the_guards_deny_acknowledge_and_nudge_in_a_real_session(project: Path) -> None:
    status = install_main.main(
        ["--project", str(project), "--harness", "claude-code", "--components", "guards"]
    )
    assert status == 0
    stream, transcript = _session(project)
    text = (project / "target.txt").read_text(encoding="utf-8")

    denials = [r for r in _tool_results(stream) if "PreToolUse:Bash hook error" in r]
    assert any("Zikaron's find-replace guard refused this command" in r for r in denials), denials
    assert "BETA" not in text, "the denied sed ran"
    assert "GAMMA" in text, "the overridden sed did not run"
    assert "ALPHA" in text, "the Edit did not happen, so no nudge could follow it"

    recorded = "\n".join(json.dumps(record) for record in transcript)
    assert "#ZIKARON-FORCE accepted by Zikaron's find-replace guard" in recorded
    assert "PostToolUse:Edit hook additional context" in recorded
    assert "target.txt` was edited" in recorded
