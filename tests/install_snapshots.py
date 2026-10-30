"""Every file an install ships, for each harness, rendered as an install writes it — and the
snapshot of them tracked under `tests/fixtures/installed/`.

A change to what an install ships then changes a tracked file, so it is seen in a diff and not only
in the code that produces it; `tests/test_install_snapshots.py` fails until the snapshot agrees. The
snapshot is rendered, never hand-edited. After a deliberate change, re-render it with

    .venv/bin/python -m tests.install_snapshots

**The paths drop each harness's own dot-directory** — `claude-code/agents/zikaron-documenter.md`,
not `.claude/agents/…` — so neither harness finds a snapshot in this repository as an agent or a
skill of its own. The commands and the project are fixed, so nothing machine-specific is in them.
"""

from pathlib import Path
from typing import Final

from zikaron.install.entries import Commands
from zikaron.install.targets import ClaudeCodeTarget, HarnessTarget, KiroTarget
from zikaron.install.writer import Plan

SNAPSHOT_ROOT: Final = Path(__file__).resolve().parent / "fixtures" / "installed"

_COMMANDS: Final = Commands(hook=Path("/venv/bin/zikaron-hook"), mcp=Path("/venv/bin/zikaron-mcp"))
_PROJECT: Final = Path("/project")
_TARGETS: Final[tuple[HarnessTarget, ...]] = (KiroTarget(), ClaudeCodeTarget())


def rendered() -> dict[str, str]:
    """Each harness's shipped files at its default model, keyed `<harness>/<path under its
    dot-directory>`."""
    files: dict[str, str] = {}
    for target in _TARGETS:
        plan = Plan(
            project=_PROJECT,
            commands=_COMMANDS,
            consolidator_model=target.spec.consolidator_model,
            documenter_model=target.spec.documenter_model,
            orchestrator_model=target.spec.orchestrator_model,
            force=False,
            trust_tools=True,
        )
        for shipped in target.shipped_files(plan):
            under_dotdir = shipped.path.relative_to(_PROJECT).parts[1:]
            files["/".join((target.name, *under_dotdir))] = shipped.content
    return files


def tracked() -> dict[str, str]:
    """The snapshot as it stands on disk, keyed as `rendered` keys it."""
    return {
        path.relative_to(SNAPSHOT_ROOT).as_posix(): path.read_bytes().decode("utf-8")
        for path in sorted(SNAPSHOT_ROOT.rglob("*"))
        if path.is_file()
    }


def write() -> None:
    """Replace the snapshot with what an install ships now, removing any file it no longer does."""
    files = rendered()
    for stale in set(tracked()) - set(files):
        (SNAPSHOT_ROOT / stale).unlink()
    for relative, content in files.items():
        path = SNAPSHOT_ROOT / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8"))


if __name__ == "__main__":
    write()
