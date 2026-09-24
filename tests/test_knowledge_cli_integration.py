"""`zikaron knowledge` against a **real service it starts itself**, in a project with no store.

Everything else about this command is driven in `test_knowledge_cli.py` with the transport stubbed
out, which is where its parsing, dispatch, statuses and output belong. What cannot be checked there
is the claim this milestone exists for: **`zikaron init` bootstraps a project that has never had a
store**, because the service creates one on its first start and `Store.open` cannot, after which
every verb works against it. That claim rests on the socket, the spawn and the model load, so it is
paid for once, here.

Real in every part the claim depends on: no server is pre-spawned, no store is pre-created, and the
encoder is the shipped one — `ServiceContext.assemble` loads it, which is the second or two this
file costs.
"""

import json
import os
import shlex
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import suppress
from pathlib import Path
from typing import Final

import pytest

from zikaron.knowledge.main import main
from zikaron.project.initialize import main as initialize
from zikaron.service import paths

_REAP_DEADLINE_SECONDS: Final = 10.0


def _service_pid(store_dir: Path) -> int | None:
    """The pid of whatever is listening for this store, asked over its own socket.

    Asked rather than read from a file, for the reason `test_service_lifecycle_integration.py`
    gives: after a respawn a remembered pid names a process that no longer exists.
    """
    sock_path = paths.socket_path(
        paths.runtime_dir(xdg_runtime_dir=os.environ.get("XDG_RUNTIME_DIR"), uid=os.getuid()),
        store_dir.resolve(),
        platform=sys.platform,
    )
    if not sock_path.exists():
        return None
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(2.0)
    try:
        sock.connect(str(sock_path))
        sock.sendall(
            b'{"jsonrpc":"2.0","id":1,"method":"health","params":{},'
            b'"client":{"session_id":"reaper","kind":"cli","pid":0}}\n'
        )
        line = sock.makefile("rb").readline()
    except OSError:
        return None
    finally:
        sock.close()
    answered = json.loads(line)
    result = answered.get("result")
    return int(result["pid"]) if isinstance(result, dict) and "pid" in result else None


@pytest.fixture
def reaped(tmp_path: Path) -> Iterator[Path]:
    """A project directory, with whatever service the command started killed afterwards.

    A service outlives the command that started it — by design, until `idle_timeout` — so a test
    that walked away would leave one holding a store under a directory pytest is about to delete.
    """
    yield tmp_path
    pid = _service_pid(tmp_path / ".zikaron")
    if pid is None:
        return
    with suppress(ProcessLookupError):
        os.kill(pid, signal.SIGKILL)
    deadline = time.monotonic() + _REAP_DEADLINE_SECONDS
    while time.monotonic() < deadline:
        with suppress(ChildProcessError):
            if os.waitpid(pid, os.WNOHANG) != (0, 0):
                return
        time.sleep(0.05)


@pytest.fixture
def initialized(reaped: Path, capsys: pytest.CaptureFixture[str]) -> Path:
    """`reaped`, after `zikaron init` has created its store.

    Every verb refuses a project with none, so this is what the rest of this file needs before it
    can put one in front of a socket. It is the real command against the real service, which is
    also what makes the store here the one the service built rather than one a test assembled.
    """
    assert initialize(["--project", str(reaped)]) == 0, capsys.readouterr().err
    capsys.readouterr()
    return reaped


def test_init_bootstraps_a_project_that_has_never_had_a_store(
    reaped: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The case no direct open could serve, and the reason the service is what creates a store.

    `Store.open` is `existing_only` and `Store.create` needs the embedding artifact, which no
    command-line process holds. The service holds it — so `init` is a command that asks for a
    store and a service that makes one, and the assertion below is that nothing else on this path
    could have.
    """
    assert not (reaped / ".zikaron" / "memory.db").exists()

    assert initialize(["--project", str(reaped)]) == 0, capsys.readouterr().err

    assert (reaped / ".zikaron" / "memory.db").exists(), (
        "the service creates the store on its first start; nothing else in this path can"
    )
    assert "initialized" in capsys.readouterr().out


def test_a_verb_refuses_before_init_and_leaves_nothing_behind(
    reaped: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The refusal against a real socket path rather than a stub, because what it must not do is
    reach the service at all: reaching it is what creates a store, so a check that ran after the
    connection would refuse and bootstrap in the same breath.
    """
    assert main(["--project", str(reaped), "list"]) == 1
    assert "refused: no Zikaron store in" in capsys.readouterr().err
    assert not (reaped / ".zikaron").exists()
    assert _service_pid(reaped / ".zikaron") is None


def test_add_reaches_the_service_once_the_project_is_initialized(
    initialized: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    corpus = initialized / "docs"
    corpus.mkdir()
    (corpus / "a.md").write_text("the protobuf step fails silently\n", encoding="utf-8")

    status = main(
        [
            "--project",
            str(initialized),
            "add",
            "docs",
            "--path",
            str(corpus),
            "--description",
            "the docs corpus",
        ]
    )

    assert status == 0, capsys.readouterr().err
    assert "added     'docs'" in capsys.readouterr().out


def test_list_reaches_the_same_service_a_second_time(
    initialized: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A second command finds the service the first one started rather than starting another.

    Asserted on the corpus being visible rather than on a pid, because what a person needs is that
    two commands address one store — which is the failure a second service would produce.
    """
    corpus = initialized / "docs"
    corpus.mkdir()
    (corpus / "a.md").write_text("x\n", encoding="utf-8")
    assert (
        main(
            [
                "--project",
                str(initialized),
                "add",
                "docs",
                "--path",
                str(corpus),
                "--description",
                "the docs corpus",
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert main(["--project", str(initialized), "list"]) == 0
    assert "docs" in capsys.readouterr().out


def test_the_module_exits_non_zero_on_a_refusal(initialized: Path) -> None:
    """The status has to survive the trip through `__main__`, which is the one line of it that can
    be wrong — a command reporting success on a refusal is worse than one that fails to run.

    A subprocess, because only one exercises the `__main__` module that makes a package executable
    — and therefore a real service, which is why it belongs in this file and takes the reaper.

    **The project is initialized first, and that is what keeps this test about what it says.**
    Against a storeless project the same command refuses without reaching the service at all, so
    the status would survive a trip this test never took.
    """
    result = subprocess.run(  # noqa: S603 — a fixed, test-constructed interpreter path.
        [
            sys.executable,
            "-m",
            "zikaron.knowledge",
            "--project",
            str(initialized),
            "status",
            "no-such-corpus",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 1
    assert "refused" in result.stderr


def test_the_foreground_command_the_verb_prints_actually_builds_the_corpus(
    initialized: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """One implementation reached two ways, so a build means the same thing however it was asked.

    The management verb does not run a build — it asks the service to start one detached — so the
    parity claim is about the **command it prints**, which is the argv that spawn reported. A
    detached build's output goes nowhere, so that line is the only way to recover why one failed;
    a line that did not reproduce the build would be worse than no line at all.

    **`--wait` is what makes the *run* deterministic rather than a race.** `add` starts a detached
    build, so running the printed command straight afterwards puts two builds on one corpus and the
    second is refused for the lock the first holds — not a defect in either, but an accurate account
    of what such a test asked for. Waiting first exercises the argv against a corpus nothing is
    building. It does **not** make which lines get printed deterministic: whether the `refresh`
    starts a build of its own or finds `add`'s already under way depends on that same window, which
    is why the argv is taken from `add`.
    """
    corpus = initialized / "docs"
    corpus.mkdir()
    (corpus / "a.md").write_text("architecture records\n", encoding="utf-8")
    assert (
        main(
            [
                "--project",
                str(initialized),
                "add",
                "docs",
                "--path",
                str(corpus),
                "--description",
                "architecture records",
            ]
        )
        == 0
    )
    # **Taken from `add`, not from the `refresh`.** A fresh corpus always answers `started`, so
    # `add` always prints this line; the `refresh` prints one only if it started a build of its
    # own, and when `add`'s indexer has already taken the lock it answers `already_indexing` and
    # prints none. That outcome is correct — and waited for — but it would leave nothing here to
    # unpack.
    added = capsys.readouterr().out

    assert main(["--project", str(initialized), "refresh", "docs", "--wait"]) == 0
    printed = capsys.readouterr().out
    assert "built     'docs' is ok" in printed, "the wait outlasts the build it started or found"

    (line,) = [one for one in added.splitlines() if one.startswith("foreground ")]
    argv = shlex.split(line.removeprefix("foreground "))
    completed = subprocess.run(  # noqa: S603 — the argv the command under test printed.
        argv, capture_output=True, text=True, timeout=300, check=False
    )
    assert completed.returncode == 0, completed.stderr
    assert "built     'docs'" in completed.stdout


def test_rename_and_remove_reach_a_real_service(
    initialized: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The two verbs the tests above never put in front of a socket.

    Chained rather than given a project each, because what is under test is that each reaches the
    service at all — and a corpus that was renamed and then removed by name proves both did.

    **The `refresh --wait` between them is not incidental.** `add` starts a detached build, and
    `lifecycle.remove` refuses while a lock is held by a holder this host cannot show is dead — a
    live local indexer is one — so without the wait this test races that build and fails whenever it
    loses. It costs the build `add` was going to run anyway.
    """
    corpus = initialized / "docs"
    corpus.mkdir()
    (corpus / "a.md").write_text("x\n", encoding="utf-8")
    assert (
        main(
            [
                "--project",
                str(initialized),
                "add",
                "docs",
                "--path",
                str(corpus),
                "--description",
                "architecture records",
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert main(["--project", str(initialized), "refresh", "docs", "--wait"]) == 0
    capsys.readouterr()

    assert main(["--project", str(initialized), "rename", "docs", "design records"]) == 0
    assert "design records" in capsys.readouterr().out

    assert main(["--project", str(initialized), "remove", "design records", "--yes"]) == 0
    assert "removed" in capsys.readouterr().out

    assert main(["--project", str(initialized), "list"]) == 0
    assert f"no knowledge bases in {initialized}" in capsys.readouterr().out
