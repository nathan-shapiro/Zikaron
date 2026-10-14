"""Every process Zikaron spawns runs this install's code, whatever its working directory holds.

A child inherits its parent's working directory, and `python -m` puts that directory first on
`sys.path`, so a `zikaron/` package there — another checkout's — would be imported in place of this
install's. Each spawn passes `-P` to prevent it; this runs each one's own interpreter options from
such a directory and asks which `zikaron` it imports.
"""

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

import zikaron
from zikaron.hook import connect, spawn_warm
from zikaron.knowledge.indexer import detach
from zikaron.service import lifecycle


def _service(tmp_path: Path, _monkeypatch: pytest.MonkeyPatch) -> list[str]:
    return lifecycle.default_server_command(tmp_path / "s.sock", tmp_path / "store")


def _service_from_the_hook(tmp_path: Path, _monkeypatch: pytest.MonkeyPatch) -> list[str]:
    return connect.default_server_command(tmp_path / "s.sock", tmp_path / "store")


def _build(tmp_path: Path, _monkeypatch: pytest.MonkeyPatch) -> list[str]:
    return detach.command("docs", project=tmp_path, full=False)


def _warm_helper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    monkeypatch.delenv("KIRO_SESSION_ID", raising=False)
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    spawned: list[list[str]] = []

    class _FakePopen:
        def __init__(self, command: list[str], **_kwargs: object) -> None:
            spawned.append(command)

    with monkeypatch.context() as patched:
        patched.setattr(subprocess, "Popen", _FakePopen)
        spawn_warm.run(scope_dir=tmp_path, payload_session_id=None)
    (command,) = spawned
    return command


@pytest.mark.parametrize(
    "argv_of", [_service, _service_from_the_hook, _build, _warm_helper], ids=lambda f: f.__name__
)
def test_a_checkout_in_the_working_directory_does_not_shadow_this_install(
    argv_of: Callable[[Path, pytest.MonkeyPatch], list[str]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    argv = argv_of(tmp_path, monkeypatch)
    interpreter_and_options = argv[: argv.index("-m")]
    checkout = tmp_path / "checkout"
    (checkout / "zikaron").mkdir(parents=True)
    (checkout / "zikaron" / "__init__.py").write_text("")
    finished = subprocess.run(  # noqa: S603 — this process's own interpreter, a fixed program.
        [*interpreter_and_options, "-c", "import zikaron; print(zikaron.__file__)"],
        cwd=checkout,
        capture_output=True,
        text=True,
        check=True,
    )
    assert interpreter_and_options[0] == sys.executable
    assert finished.stdout.strip() == zikaron.__file__
