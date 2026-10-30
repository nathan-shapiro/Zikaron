"""The guards in a real kiro session (`design/build-plan.md` §M41-2 item 9).

The twin of `test_guard_claude_live.py`. One headless turn, given exact commands so that neither
the edit nor the override is the model's choice: a `sed -i` the guard must deny, the same form with
a valid override, a `sed -i` on a scratch target, and a `pgrep -f` matching its own shell. Each is
asserted from the evidence kiro leaves:

- both start texts arrived whole, from the session's `messages.jsonl`, whose
  `session_start_<id>_<agent>` record holds the hooks' output (`research/kiro-v3-probe.md` §45,
  §49);
- the denied `sed` left the file unchanged, and the overridden and scratch ones changed theirs;
- the self-matching `pgrep` did not run, since the file it would have touched is absent;
- each deny reached the model, from the model's own quote of its opening clause in the transcript:
  neither the session record nor `kiro.log` keeps a hook's stderr (§33), so nothing else shows it.

**The project lives under `~/.cache/zikaron-live-tests/`, never `tmp_path`**: under `/tmp` every
target would be scratch. The session's profile carries `shell` and a `shell` allow rule, without
which headless kiro refuses every shell call itself, for a reason that is not the guard's.

    .venv/bin/pytest -m integration_kiro tests/test_guard_kiro_live.py
"""

import json
import shutil
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest

from tests.kiro_live import chat, require_kiro, session_messages
from zikaron.guard import messages
from zikaron.guard.start_text import guard_start_text
from zikaron.harness.spec import KIRO
from zikaron.hook.write_policy import WRITE_POLICY_PROMPT
from zikaron.install import main as install_main

pytestmark = pytest.mark.integration_kiro

_SESSION_MODEL: Final = "claude-haiku-5.5"
_PRIMARY_NAME: Final = "zikaron-live-guards"

_PRIMARY: Final[dict[str, object]] = {
    "name": _PRIMARY_NAME,
    "description": "A test agent for Zikaron's live guard check.",
    "prompt": "You are a test agent. Do exactly what the user asks, and nothing else.",
    "tools": ["read", "shell"],
    "permissions": {
        "rules": [
            {"capability": "shell", "effect": "allow"},
            {"capability": "fs_read", "effect": "allow"},
        ]
    },
}

_DENIED: Final = "sed -i 's/beta/BETA/' target.txt"
_OVERRIDDEN: Final = "sed -i 's/gamma/GAMMA/' target.txt #ZIKARON-FORCE #Reason: live guard test"
#: A pattern no process carries but the command running it, so only the shell can match it.
_NONCE: Final = f"zikaron_live_selfmatch_{uuid.uuid4().hex[:12]}"
_RAN: Final = f"ran-{_NONCE[-12:]}"
_SELF_MATCHING: Final = f"pgrep -f {_NONCE}; touch {_RAN}"
_FIND_REPLACE_OPENING: Final = messages.DENY_TEMPLATE.split(":", 1)[0]
_SELF_MATCH_OPENING: Final = messages.SELF_MATCH_TEMPLATE.split(":", 1)[0]


@pytest.fixture
def project() -> Iterator[Path]:
    root = Path.home() / ".cache" / "zikaron-live-tests" / uuid.uuid4().hex
    root.mkdir(parents=True)
    (root / "target.txt").write_text("alpha beta gamma\n", encoding="utf-8")
    try:
        yield root
    finally:
        shutil.rmtree(root)


def _install(project: Path) -> None:
    agents = project / ".kiro" / "agents"
    agents.mkdir(parents=True)
    profile = agents / f"{_PRIMARY_NAME}.json"
    profile.write_text(json.dumps(_PRIMARY, indent=2) + "\n", encoding="utf-8")
    argv = ["--project", str(project), "--harness", "kiro", "--agent", str(profile)]
    assert install_main.main([*argv, "--components", "both"]) == 0


def _strings(value: object) -> Iterator[str]:
    """Every string anywhere in a parsed JSON value."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def test_the_guards_deny_override_and_spare_scratch_in_a_real_session(
    project: Path, tmp_path: Path
) -> None:
    require_kiro()
    _install(project)
    scratch = tmp_path / "scratch.txt"
    scratch.write_text("delta\n", encoding="utf-8")
    prompt = (
        "This is a test of hooks installed in this throwaway project; every command is harmless. "
        "Do these steps in order, each exactly as written, character for character, including any "
        "trailing # comment, and carry on to the next even if one is refused. "
        f"Step 1: run this shell command: `{_DENIED}`. "
        f"Step 2: run this shell command: `{_OVERRIDDEN}`. "
        f"Step 3: run this shell command: `sed -i 's/delta/DELTA/' {scratch}`. "
        f"Step 4: run this shell command: `{_SELF_MATCHING}`. "
        "Then, for each step a hook refused, quote verbatim the first sentence of the message the "
        "hook gave you, and reply with nothing else."
    )
    turn = chat(project, _PRIMARY_NAME, prompt, model=_SESSION_MODEL)
    assert turn.of_type("runError") == [], turn.diagnosis()

    text = (project / "target.txt").read_text(encoding="utf-8")
    assert "BETA" not in text, "the denied sed ran"
    assert "GAMMA" in text, f"the overridden sed did not run. {turn.diagnosis()}"
    assert "DELTA" in scratch.read_text(encoding="utf-8"), "the scratch target was not spared"
    assert not (project / _RAN).exists(), "the self-matching pgrep ran"

    transcript = session_messages(turn.session_id)
    strings = [string for line in transcript.splitlines() for string in _strings(json.loads(line))]
    for start_text in (WRITE_POLICY_PROMPT, guard_start_text(KIRO)):
        assert any(start_text in string for string in strings), start_text[:80]
    assert any(_FIND_REPLACE_OPENING in string for string in strings), "no find-replace deny quoted"
    assert any(_SELF_MATCH_OPENING in string for string in strings), "no self-match deny quoted"
