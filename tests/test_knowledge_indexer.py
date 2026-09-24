"""The build command: its own entry point, driven in-process and as a real process.

A build is its own command rather than a mode of the management one, because it is minutes of
saturated CPU where every other verb is a small transaction. What is checked here is that
command's own job — parsing, exit statuses, what it prints, and that it survives being killed —
since every decision it reports belongs to `zikaron.core.knowledge` and is tested there.
"""

import asyncio
import signal
import sqlite3
import subprocess
import sys
import time
from collections.abc import Callable, Coroutine
from contextlib import closing
from pathlib import Path

import pytest

from tests.knowledge_fixtures import config_for, corpus_root
from zikaron.core.knowledge import candidates, git, lifecycle, lock
from zikaron.core.knowledge.errors import UnknownKnowledgeBaseError
from zikaron.core.knowledge.meta import GitMode
from zikaron.core.store.embedder import FakeEmbedder
from zikaron.core.store.store import Store
from zikaron.knowledge import scope
from zikaron.knowledge.indexer import detach
from zikaron.knowledge.indexer import main as indexer_main
from zikaron.knowledge.indexer.main import main

_READY_TIMEOUT_SECONDS = 30.0
_POLL_SECONDS = 0.05

#: Every test here drives the real command, and the real command loads the real encoder before it
#: indexes anything — which is exactly what the `integration` tier is for. The decisions the command
#: reports are tested against the deterministic encoder in `zikaron.core.knowledge`'s own tests, so
#: nothing is covered only here.
pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _no_detached_builds(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the management command from starting a build of its own.

    `add` starts one, and every project here is made with `add`. Left alone, each test would leave
    a real detached build running over a real corpus — outliving the test, competing for the lock
    the test then takes, and reaching the machine long after the suite had moved on. The one test
    that wants the command it *would* have started replaces this with a recorder.
    """
    monkeypatch.setattr(detach, "spawn", lambda *_args, **_keywords: [])


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A project with a created store and a corpus registered over a real directory.

    Synchronous, like the command itself: `main` owns its own event loop, so a test running inside
    one could not call it at all.
    """
    return _make_project(tmp_path, git_mode="off")


class TestTheCommand:
    def test_it_builds_and_reports_what_it_did(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["--project", str(project), "docs"]) == 0
        printed = capsys.readouterr().out
        assert "built     'docs'" in printed
        assert "1 in the index" in printed
        assert "state     ok" in printed

    def test_it_says_when_nothing_was_skipped(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """ "Nothing was skipped" and "this was not measured" are different answers, so the
        all-zero case says so rather than printing an empty line."""
        main(["--project", str(project), "docs"])
        assert "skipped   none" in capsys.readouterr().out

    def test_it_reports_why_files_are_missing_when_some_are(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (project / "docs" / "logo.png").write_bytes(b"\x89PNG")
        main(["--project", str(project), "docs"])
        assert "skipped   denied_extension 1" in capsys.readouterr().out

    def test_an_unknown_knowledge_base_is_a_refusal_rather_than_a_traceback(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["--project", str(project), "nothing-by-that-name"]) == 1
        assert "refused:" in capsys.readouterr().err

    def test_a_missing_root_is_refused_and_says_the_index_is_kept(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        main(["--project", str(project), "docs"])
        (project / "docs" / "a.md").unlink()
        (project / "docs").rmdir()
        assert main(["--project", str(project), "docs"]) == 1
        assert "kept as it is" in capsys.readouterr().err


class TestTheCaveatsItPrints:
    """Each of these is a corpus shaped by something other than its own configuration, so a build
    that stayed silent would leave the difference to be discovered as files that are missing."""

    def test_a_git_mode_that_did_not_take_effect_is_said_out_loud(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The default is `tracked` while indexing a documentation tree outside any repository is
        an endorsed use, so this is ordinary rather than exotic — and the message has to say so.
        This fixture *is* that ordinary case, so a message naming only a git failure would be
        wrong here specifically, which is why the first clause is pinned rather than just the
        headline."""
        _make_project(tmp_path, git_mode="tracked")
        assert main(["--project", str(tmp_path), "docs"]) == 0
        printed = capsys.readouterr().out
        assert "did not take effect" in printed
        assert "not inside a git work tree" in printed

    def test_attributes_that_could_not_be_read_are_said_out_loud(
        self, project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        async def _refuse(*_args: object, **_kwargs: object) -> None:
            raise git.GitUnavailableError("attributes unavailable")

        monkeypatch.setattr(git, "attributes", _refuse)
        monkeypatch.setattr(
            candidates, "gather", _pretend_git_answered(candidates.GitAnswers(GitMode.ALL))
        )
        assert main(["--project", str(project), "docs"]) == 0
        assert ".gitattributes could not be read" in capsys.readouterr().out

    def test_files_left_pending_are_said_out_loud(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (project / "docs" / "a.md").chmod(0o000)
        try:
            assert main(["--project", str(project), "docs"]) == 0
        finally:
            (project / "docs" / "a.md").chmod(0o600)
        assert "still pending" in capsys.readouterr().out


def _pretend_git_answered(
    answers: candidates.GitAnswers,
) -> Callable[..., Coroutine[object, object, candidates.GitAnswers]]:
    """Stand in for the git enumeration, so a corpus outside a repository still reaches the
    attribute call — which is the only way to exercise that call failing on its own."""

    async def _gather(*_args: object, **_kwargs: object) -> candidates.GitAnswers:
        return answers

    return _gather


def _make_project(tmp_path: Path, *, git_mode: str) -> Path:
    """A store with one corpus registered over a real directory, built without the CLI.

    **Registered through `core.knowledge.lifecycle` rather than through `zikaron knowledge add`.**
    What these tests need is a registered corpus; reaching it through the management command would
    now start a real service, which would spawn a real build of its own — competing for the lock
    the test is about to take, and outliving the test. Nothing about the indexer depends on which
    surface registered the corpus.
    """
    config = config_for(tmp_path)
    embedder = FakeEmbedder(config.get_str("embed_model"), config.get_int("embed_dim"))
    corpus_root(tmp_path)

    async def _create() -> None:
        async with await Store.create(tmp_path / ".zikaron", config, embedder) as store:
            await lifecycle.add(
                tmp_path / ".zikaron",
                store.connection,
                config,
                lifecycle.AddRequest(
                    name="docs",
                    root=tmp_path / "docs",
                    description="architecture records",
                    git_mode=GitMode(git_mode),
                ),
            )

    asyncio.run(_create())
    return tmp_path


class TestAsARealProcess:
    def test_the_documented_invocation_runs(self, project: Path) -> None:
        """The only way to exercise an entry point is to be one, so this spawns it."""
        completed = subprocess.run(  # noqa: S603 — this interpreter, on a path built here.
            [sys.executable, "-m", "zikaron.knowledge.indexer", "--project", str(project), "docs"],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        assert "built     'docs'" in completed.stdout

    def test_killing_a_build_leaves_pending_rows_and_the_next_build_finishes(
        self, project: Path
    ) -> None:
        """A build that dies leaves its committed files intact and its pending rows naming what it
        never reached — which is what a later scan and a search both rely on. Killed with a signal
        no handler can catch, because that is the case no in-process cleanup can rescue."""
        many = project / "docs"
        for index in range(400):
            (many / f"file{index:04d}.md").write_text(f"body {index}\n", encoding="utf-8")
        process = subprocess.Popen(  # noqa: S603
            [sys.executable, "-m", "zikaron.knowledge.indexer", "--project", str(project), "docs"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            _wait_for_rows(project, at_least=1)
            process.send_signal(signal.SIGKILL)
        finally:
            process.wait(timeout=30)

        left = _pending_count(project)
        assert left > 0

        # The lock the killed build took is still recorded — nothing released it, because nothing
        # ran — and it names a process this host can now see is gone, which is what lets the next
        # build take it over rather than refusing forever.
        holder = _recorded_lock(project)
        assert holder is not None
        assert lock.is_reclaimable(holder, host=lock.this_host())

        completed = subprocess.run(  # noqa: S603 — this interpreter, on a path built here.
            [sys.executable, "-m", "zikaron.knowledge.indexer", "--project", str(project), "docs"],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        assert _pending_count(project) == 0
        assert _file_rows(project) == 401
        assert _recorded_lock(project) is None, "a completed build gives its lock back"


def _knowledge_database(project: Path) -> Path:
    (found,) = sorted((project / ".zikaron" / "knowledge").glob("*.db"))
    return found


def _count(project: Path, query: str) -> int:
    """Read one count out of the knowledge base, from outside the process that is writing it.

    A plain read-only `sqlite3` connection rather than the package's own opener: this is standing
    where a separate process stands, and the opener would apply pragmas to a database another
    process holds.
    """
    # `closing`, not a bare `with`: `sqlite3.Connection.__exit__` commits or rolls back the
    # transaction and leaves the connection **open**. From Python 3.13 that surfaces as a
    # `ResourceWarning: unclosed database`; on 3.12 it was silent, which is how these helpers
    # accumulated dozens of open handles per run without anything saying so.
    with closing(
        sqlite3.connect(f"file:{_knowledge_database(project)}?mode=ro", uri=True)
    ) as connection:
        ((found,),) = connection.execute(query)
    return int(found)


def _pending_count(project: Path) -> int:
    return _count(project, "SELECT count(*) FROM pending")


def _recorded_lock(project: Path) -> lock.LockHolder | None:
    """The build lock as another process finds it, read the same read-only way as the counts."""
    with closing(
        sqlite3.connect(f"file:{_knowledge_database(project)}?mode=ro", uri=True)
    ) as connection:
        rows = connection.execute("SELECT key, value FROM meta").fetchall()
    return lock.read({str(key): str(value) for key, value in rows})


def _file_rows(project: Path) -> int:
    return _count(project, "SELECT count(*) FROM files")


def _wait_for_rows(project: Path, *, at_least: int) -> None:
    """Block until the build has committed some files, so the kill lands mid-scan.

    Polled rather than timed, because how long a walk takes depends on the machine — and a kill
    that arrived before the first commit would test a build that had not started.
    """
    deadline = time.monotonic() + _READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            if _file_rows(project) >= at_least:
                return
        except sqlite3.Error:
            # The build is writing this database from another process; a read landing mid-write
            # is an ordinary outcome of watching it rather than a failure to report.
            pass
        time.sleep(_POLL_SECONDS)
    pytest.fail(f"no build progress within {_READY_TIMEOUT_SECONDS}s")


class TestWhenABuildIsARebuild:
    def test_it_says_the_index_was_made_again_by_a_different_model(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A rebuild reindexes every file and deletes none, which is what a first build looks like
        too — and the thing that changed is not in the corpus at all but in what embedded it. So it
        is said out loud rather than left to be inferred from numbers that cannot show it."""
        assert main(["--project", str(project), "docs"]) == 0
        capsys.readouterr()
        _record_a_different_model(project)

        assert main(["--project", str(project), "docs"]) == 0

        printed = capsys.readouterr().out
        assert "did not match the model it records" in printed
        assert "made again with" in printed


def _record_a_different_model(project: Path) -> None:
    """Rewrite the corpus's recorded encoder identity, so the next build disagrees with it.

    The cheap half of the divergence: the model this corpus claims moves, rather than the model the
    machine has. Loading a second real artifact to produce the same disagreement would cost a
    download and prove nothing extra.
    """
    with closing(sqlite3.connect(_knowledge_database(project))) as connection:
        connection.execute("UPDATE meta SET value = 'some-other-model' WHERE key = 'embed_model'")
        connection.commit()


class TestWhatIsDecidedBeforeTheModelLoads:
    def test_a_refusal_is_reached_without_loading_the_encoder(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Loading the model is a second of CPU and the most expensive thing this command does. It
        is wasted on any build that will be refused — in the foreground it is the operator's second,
        and detached it is spent on a refusal nobody will ever see."""

        async def _must_not_load(*_args: object, **_keywords: object) -> None:
            raise AssertionError("the encoder was loaded before the refusal was decided")

        monkeypatch.setattr(indexer_main, "build_settings", _must_not_load)

        async def _go() -> None:
            async with scope.open_store(project) as store:
                await indexer_main.build(
                    store.directory, store.connection, store.config, name="nothing-by-that-name"
                )

        with pytest.raises(UnknownKnowledgeBaseError):
            asyncio.run(_go())
