"""Zikaron's own Claude Code spawns pass no `name` (`design/build-plan.md` §M43 item 13).

With agent teams on, a named spawn becomes a teammate every time, and a teammate idles when its work
is done instead of ending — wrong for the consolidator, the orchestrator and the documenters, each
meant to run once and end. The model names a spawn unprompted: every orchestrator spawn in the
transcripts measured carried one. So each shipped instruction says not to, read here from the
install snapshots, which `test_install_snapshots.py` holds equal to what the installer writes.
"""

from pathlib import Path

import pytest

_SNAPSHOT = Path(__file__).parent / "fixtures" / "installed" / "claude-code"


@pytest.mark.parametrize(
    "shipped",
    [
        "skills/zikaron-consolidate/SKILL.md",
        "skills/zikaron-document-code/SKILL.md",
        "agents/zikaron-code-orchestrator.md",
    ],
)
def test_each_spawn_instruction_says_to_pass_no_name(shipped: str) -> None:
    text = " ".join((_SNAPSHOT / shipped).read_text(encoding="utf-8").split())
    assert "and no `name`, since a named spawn becomes a teammate" in text
