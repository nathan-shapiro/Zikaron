"""The instruction gate as the shell runs it (`design/harness.md` §"Agent teams").

The gate is what keeps a hook on every tool call from costing a Python start on every tool call,
so what it decides is pinned against `sh` itself: it starts `zikaron-hook` exactly when a marker
of this session's is pending, with the payload on its stdin, and otherwise exits 0.
"""

import os
import subprocess
from pathlib import Path

import pytest

from zikaron.harness.spec import CLAUDE_CODE, KIRO
from zikaron.install.entries import instruction_gate_command
from zikaron.service import paths

SESSION = "6ce78ba4-beb9-485f-b46d-fd39b8ed5073"


@pytest.fixture
def hook(tmp_path: Path) -> Path:
    """A stand-in `zikaron-hook` that records the payload it was given, in a directory with a
    space in its name, as a quoted install must survive."""
    scripts = tmp_path / "venv bin"
    scripts.mkdir()
    script = scripts / "zikaron-hook"
    script.write_text(f'#!/bin/sh\ncat > "{tmp_path / "ran"}"\n', encoding="utf-8")
    script.chmod(0o755)
    return script


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    paths.instruction_pending_dir(paths.store_dir(root)).mkdir(parents=True)
    return root


def _gate(hook: Path, project: Path, *, session: str | None = SESSION) -> int:
    assert CLAUDE_CODE.project_dir_variable is not None
    env = {"PATH": os.environ["PATH"], CLAUDE_CODE.project_dir_variable: str(project)}
    if session is not None:
        env[CLAUDE_CODE.session_variable] = session
    completed = subprocess.run(  # noqa: S603 — the installer's own command, run as Claude Code runs it.
        ["/bin/sh", "-c", instruction_gate_command(hook, CLAUDE_CODE)],
        input=b'{"payload": true}',
        env=env,
        cwd=project,
        check=False,
        timeout=10,
    )
    return completed.returncode


def _marker(project: Path, name: str) -> None:
    (paths.instruction_pending_dir(paths.store_dir(project)) / name).touch()


def test_no_marker_starts_nothing_and_exits_0(hook: Path, project: Path, tmp_path: Path) -> None:
    _marker(project, "another-session")
    assert _gate(hook, project) == 0
    assert not (tmp_path / "ran").exists()


@pytest.mark.parametrize("names", [[SESSION], [f"{SESSION}.a1", f"{SESSION}.a2"]])
def test_a_marker_of_this_sessions_starts_the_hook_with_the_payload(
    hook: Path, project: Path, tmp_path: Path, names: list[str]
) -> None:
    for name in names:
        _marker(project, name)
    assert _gate(hook, project) == 0
    assert (tmp_path / "ran").read_bytes() == b'{"payload": true}'


def test_an_unset_session_variable_starts_it_where_any_marker_is_pending(
    hook: Path, project: Path, tmp_path: Path
) -> None:
    assert _gate(hook, project, session=None) == 0
    assert not (tmp_path / "ran").exists()
    _marker(project, "another-session")
    assert _gate(hook, project, session=None) == 0
    assert (tmp_path / "ran").exists()


def test_a_project_with_no_store_exits_0(hook: Path, tmp_path: Path) -> None:
    bare = tmp_path / "bare"
    bare.mkdir()
    assert _gate(hook, bare) == 0
    assert not (tmp_path / "ran").exists()


def test_a_harness_naming_no_project_directory_has_no_gate(hook: Path) -> None:
    """The gate finds the store as every hook does, by the project variable; a harness exporting
    none has nothing to find it by, and is refused rather than given a gate that can never open."""
    with pytest.raises(ValueError, match="no project directory"):
        instruction_gate_command(hook, KIRO)
