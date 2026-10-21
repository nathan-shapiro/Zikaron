"""Starting a build that outlives whoever asked for it.

Two claims, checked separately because only one of them can be checked without a second process.
**The argv** is a pure function and is checked as one — in particular the `--` before the knowledge
base's name, since a name is free-form and one beginning with a dash would otherwise be read as an
option by the very command it names. **The detachment** is a property of a real process tree, so it
is checked by running the real command and watching a build finish after the command that asked for
it has already exited.
"""

import asyncio
import os
import sqlite3
import stat
import subprocess
import sys
import threading
import time
from collections.abc import Sequence
from contextlib import closing
from pathlib import Path
from typing import Final

import pytest

from tests.knowledge_fixtures import config_for
from zikaron.core.store.embedder import FakeEmbedder
from zikaron.core.store.store import Store
from zikaron.knowledge.indexer import detach

_MODULE: Final = "zikaron.knowledge.indexer"

#: How often the detached build is checked for. Short, because the window between the child taking
#: the lock and finishing a small corpus is measured in seconds.
_POLL_SECONDS: Final = 0.05


class _FakePopen:
    """Stands in for a spawned child, recording how it was asked for and whether it was waited on.

    `wait` blocks until released, so the test can observe that the wait happens somewhere that is
    not the calling thread — which is the whole of what the reaping thread is for.
    """

    started: Sequence[str] | None = None
    keywords: dict[str, object] = {}  # noqa: RUF012 — class-level, read back by the test.
    waited = threading.Event()
    release = threading.Event()

    def __init__(self, argv: Sequence[str], **keywords: object) -> None:
        type(self).started = list(argv)
        type(self).keywords = keywords

    def wait(self) -> int:
        type(self).release.wait(timeout=5)
        type(self).waited.set()
        return 0

    @classmethod
    def reset(cls) -> None:
        cls.started = None
        cls.keywords = {}
        cls.waited = threading.Event()
        cls.release = threading.Event()


class TestTheCommandAChildIsGiven:
    def test_it_runs_this_interpreter_and_the_indexer_module(self) -> None:
        argv = detach.command("docs", project=Path("/projects/one"), full=False)
        assert argv[:4] == [sys.executable, "-P", "-m", _MODULE]

    def test_the_project_is_passed_rather_than_left_to_be_resolved_again(self) -> None:
        """The parent has already decided which store it means, and a child re-deriving it could
        answer differently — a different project, a different registry, a different corpus."""
        argv = detach.command("docs", project=Path("/projects/one"), full=False)
        assert argv[argv.index("--project") + 1] == "/projects/one"

    def test_the_name_comes_last_behind_a_separator(self) -> None:
        """Names are free-form, so one beginning with a dash is possible — and without the
        separator the build would die parsing its own arguments before opening anything."""
        argv = detach.command("-weird", project=Path("/projects/one"), full=False)
        assert argv[-2:] == ["--", "-weird"]

    def test_a_full_build_is_asked_for_explicitly(self) -> None:
        assert "--full" in detach.command("docs", project=Path("/p"), full=True)

    def test_an_incremental_build_asks_for_nothing_extra(self) -> None:
        assert "--full" not in detach.command("docs", project=Path("/p"), full=False)

    def test_the_name_is_an_argument_rather_than_anything_a_shell_reads(self) -> None:
        """Nothing here goes through a shell, so a name full of shell metacharacters is one
        argument and not a command."""
        hostile = "docs; rm -rf /"
        assert detach.command(hostile, project=Path("/p"), full=False)[-1] == hostile


class TestHowTheChildIsStarted:
    @pytest.fixture(autouse=True)
    def _fake_popen(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _FakePopen.reset()
        monkeypatch.setattr(subprocess, "Popen", _FakePopen)

    @pytest.fixture
    def log(self, tmp_path: Path) -> Path:
        return tmp_path / "build.log"

    def test_it_gets_its_own_session_and_nothing_to_read(self, log: Path) -> None:
        """Its own session so it has no controlling terminal and is not signalled with the caller's
        process group; no stdin because there is nobody left to type into it."""
        detach.spawn("docs", project=Path("/p"), log=log)
        assert _FakePopen.keywords["start_new_session"] is True
        assert _FakePopen.keywords["stdin"] is subprocess.DEVNULL

    def test_both_streams_go_to_one_descriptor(self, log: Path) -> None:
        detach.spawn("docs", project=Path("/p"), log=log)
        assert isinstance(_FakePopen.keywords["stdout"], int)
        assert _FakePopen.keywords["stderr"] == _FakePopen.keywords["stdout"]

    def test_it_is_started_with_the_argv_this_module_builds(self, log: Path) -> None:
        detach.spawn("docs", project=Path("/p"), log=log, full=True)
        assert _FakePopen.started == detach.command("docs", project=Path("/p"), full=True)

    def test_it_hands_back_the_childs_own_handle(self, log: Path) -> None:
        """The handle, not the pid, is what says whether the child still runs: a recycled number
        answers a probe, and a handle to an exited child does not."""
        assert isinstance(detach.spawn("docs", project=Path("/p"), log=log), _FakePopen)

    def test_the_caller_is_not_the_one_that_waits(self, log: Path) -> None:
        """A long-lived caller that never waited would accumulate a zombie per build, and a caller
        that waited here would not have detached at all. The wait happens on a thread of its own."""
        detach.spawn("docs", project=Path("/p"), log=log)
        assert not _FakePopen.waited.is_set()
        _FakePopen.release.set()
        assert _FakePopen.waited.wait(timeout=5)

    def test_a_child_that_cannot_be_started_is_reported(
        self, monkeypatch: pytest.MonkeyPatch, log: Path
    ) -> None:
        """The caller has just told somebody a build is running. Nothing else would ever correct
        that, so a failed spawn is the one thing here that must not be swallowed."""

        def _refuse(*_args: object, **_keywords: object) -> None:
            raise OSError("no such interpreter")

        monkeypatch.setattr(subprocess, "Popen", _refuse)
        with pytest.raises(OSError, match="no such interpreter"):
            detach.spawn("docs", project=Path("/p"), log=log)

    def test_a_failed_start_leaves_no_descriptor_open(
        self, monkeypatch: pytest.MonkeyPatch, log: Path
    ) -> None:
        """The spawner is a long-lived service, so a descriptor leaked per failed start is one
        fewer for every build after it."""

        def _refuse(*_args: object, **_keywords: object) -> None:
            raise OSError("no such interpreter")

        monkeypatch.setattr(subprocess, "Popen", _refuse)
        before = _open_descriptors()
        with pytest.raises(OSError, match="no such interpreter"):
            detach.spawn("docs", project=Path("/p"), log=log)
        assert _open_descriptors() == before

    def test_a_log_that_cannot_be_opened_starts_no_build(self, tmp_path: Path) -> None:
        """A build whose output had nowhere to go would fail detached with nobody told why, which
        is the condition the log exists to end — so the call that asked for it fails instead."""
        with pytest.raises(FileNotFoundError):
            detach.spawn("docs", project=Path("/p"), log=tmp_path / "absent" / "build.log")
        assert _FakePopen.started is None


class TestTheLogItIsGiven:
    """What the spawner does to the file before the child writes to it."""

    @pytest.fixture(autouse=True)
    def _fake_popen(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _FakePopen.reset()
        monkeypatch.setattr(subprocess, "Popen", _FakePopen)

    def test_it_is_private_even_when_found_wider(self, tmp_path: Path) -> None:
        """A build's output names the paths it indexed; the store's files are `0600`, and a log a
        person or an older build left at `0644` is tightened rather than kept."""
        log = tmp_path / "build.log"
        log.write_text("from before\n", encoding="utf-8")
        log.chmod(0o644)
        detach.spawn("docs", project=Path("/p"), log=log)
        assert stat.S_IMODE(log.stat().st_mode) == 0o600

    def test_it_is_created_private(self, tmp_path: Path) -> None:
        log = tmp_path / "build.log"
        detach.spawn("docs", project=Path("/p"), log=log)
        assert stat.S_IMODE(log.stat().st_mode) == 0o600

    def test_it_holds_the_latest_build_alone(self, tmp_path: Path) -> None:
        """Emptied at each spawn, which is why it needs no retention."""
        log = tmp_path / "build.log"
        log.write_text("the build before\n", encoding="utf-8")
        detach.spawn("docs", project=Path("/p"), log=log)
        assert log.read_text(encoding="utf-8") == ""

    def test_two_writers_at_once_both_land(self, tmp_path: Path) -> None:
        """A previous child still printing as the next spawn empties the log, or a restarted
        service spawning beside a child it does not know of: appended, their lines follow one
        another, where positioned writes would overwrite the first's from offset 0."""
        log = tmp_path / "build.log"
        first = detach.open_log(log)
        second = detach.open_log(log)
        try:
            os.write(first, b"first\n")
            os.write(second, b"second\n")
        finally:
            os.close(first)
            os.close(second)
        assert log.read_text(encoding="utf-8") == "first\nsecond\n"


@pytest.mark.integration
class TestWhatAChildWritesReachesTheLog:
    """A real child, so what is checked is the descriptor it inherits rather than the arguments a
    stub was handed. Its command is replaced, because what is under test is the plumbing and a real
    build's output is the integration file's business."""

    def _run(self, monkeypatch: pytest.MonkeyPatch, log: Path, program: str) -> str:
        monkeypatch.setattr(
            detach, "command", lambda *_args, **_keywords: [sys.executable, "-c", program]
        )
        process = detach.spawn("docs", project=Path("/p"), log=log)
        deadline = time.monotonic() + 30
        while process.poll() is None and time.monotonic() < deadline:
            time.sleep(_POLL_SECONDS)
        assert process.poll() is not None, "the child did not exit"
        return log.read_text(encoding="utf-8")

    def test_both_streams_reach_it(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        written = self._run(
            monkeypatch,
            tmp_path / "build.log",
            "import sys; print('to stdout'); print('to stderr', file=sys.stderr)",
        )
        assert "to stdout" in written
        assert "to stderr" in written

    def test_lines_land_in_the_order_they_were_printed(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Stripped from this process first, so a shell that exports it cannot make the test pass
        for a spawner that does not set it."""
        monkeypatch.delenv("PYTHONUNBUFFERED", raising=False)
        written = self._run(
            monkeypatch,
            tmp_path / "build.log",
            "import sys; print('one'); print('two', file=sys.stderr); print('three')",
        )
        assert written.splitlines() == ["one", "two", "three"]

    def test_a_child_that_dies_of_an_exception_leaves_its_traceback(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The case the log is for: a build that failed with nobody watching."""
        written = self._run(
            monkeypatch, tmp_path / "build.log", "raise RuntimeError('the reason it died')"
        )
        assert "Traceback (most recent call last)" in written
        assert "RuntimeError: the reason it died" in written


def _open_descriptors() -> list[str]:
    """This process's open descriptors, by number. `/dev/fd` is where both supported systems list
    them; the listing's own descriptor is in every count alike."""
    return sorted(entry.name for entry in Path("/dev/fd").iterdir())


@pytest.mark.integration
class TestABuildOutlivesTheCommandThatAskedForIt:
    """The claim a stub cannot make: a real child, in a real process tree, working after the process
    that started it has exited. Run through the shipped command rather than through `spawn`, because
    what is checked is that the whole path detaches."""

    def test_the_build_runs_in_another_session_after_the_command_has_returned(
        self, tmp_path: Path
    ) -> None:
        """**Not vacuous for a build that never detached**, and it is worth saying why, since the
        obvious version of this test is. A synchronous `add` would finish its build *before*
        returning, so no lock would ever be visible afterwards and the wait below would time out.
        Seeing one at all is therefore the evidence: the build had not started when the command
        exited, and it ran anyway."""
        project = _project_with_a_corpus(tmp_path, files=300)
        assert _cli(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")

        pid = _wait_for_builder(project)
        assert pid is not None, _cli_output(project, "status", "docs")
        # A session of its own: no controlling terminal, and out of reach of a signal sent to the
        # process group of whoever asked for the build.
        assert os.getsid(pid) != os.getsid(os.getpid())

        assert _wait_for_state(project, "ok"), _cli_output(project, "status", "docs")


def _project_with_a_corpus(tmp_path: Path, *, files: int) -> Path:
    """A project holding a real store and a directory with `files` files in it to index."""
    corpus = tmp_path / "docs"
    corpus.mkdir()
    for index in range(files):
        (corpus / f"file{index}.md").write_text(f"prose number {index}\n" * 20, encoding="utf-8")
    config = config_for(tmp_path)
    embedder = FakeEmbedder(config.get_str("embed_model"), config.get_int("embed_dim"))

    async def _create() -> None:
        async with await Store.create(tmp_path / ".zikaron", config, embedder):
            pass

    asyncio.run(_create())
    return tmp_path


def _cli(project: Path, *argv: str) -> bool:
    return _run_cli(project, *argv).returncode == 0


def _cli_output(project: Path, *argv: str) -> str:
    finished = _run_cli(project, *argv)
    return finished.stdout + finished.stderr


def _run_cli(project: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 — a fixed argv this test constructed.
        [sys.executable, "-m", "zikaron.knowledge", "--project", str(project), *argv],
        capture_output=True,
        text=True,
        check=False,
    )


def _wait_for_builder(project: Path, *, timeout: float = 120.0) -> int | None:
    """The pid of the process holding the build lock, once one holds it.

    Read straight out of the knowledge base rather than through `status`, because the window this
    has to catch is short and a command that spawns an interpreter to answer is slower than the
    thing it is watching. The child pays an interpreter start and a real model load before it takes
    the lock at all, which is why this polls rather than looking once.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        recorded = _recorded_lock_pid(project)
        if recorded is not None:
            return recorded
        time.sleep(_POLL_SECONDS)
    return None


def _recorded_lock_pid(project: Path) -> int | None:
    """The recorded `lock_pid`, or `None` while no lock is held or the database is not there yet."""
    found = sorted((project / ".zikaron" / "knowledge").glob("*.db"))
    if not found:
        return None
    try:
        # `closing`, not a bare `with`: `sqlite3.Connection.__exit__` ends the transaction and
        # leaves the connection open, which from 3.13 raises `ResourceWarning: unclosed database`.
        with closing(sqlite3.connect(f"file:{found[0]}?mode=ro", uri=True)) as connection:
            rows = connection.execute("SELECT value FROM meta WHERE key = 'lock_pid'").fetchall()
    except sqlite3.Error:
        return None
    return int(rows[0][0]) if rows else None


def _wait_for_state(project: Path, state: str, *, timeout: float = 300.0) -> bool:
    """Poll `status` until the corpus reaches `state`, which is what a person would do."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if f"state {state}" in _cli_output(project, "status", "docs"):
            return True
        time.sleep(0.5)
    return False
