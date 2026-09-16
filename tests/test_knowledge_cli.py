"""The command a person runs, driven in-process so both its exit status and its output are read.

`main` returns a status rather than exiting for exactly this reason. What is checked here is the
command's own job — parsing, dispatch, exit statuses and what it prints — since every decision it
reports belongs to `zikaron.core.knowledge` and is tested there.
"""

import argparse
import asyncio
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import aiosqlite
import pytest

from tests.knowledge_fixtures import config_for, corpus_root
from zikaron.core.knowledge import lock, registry, reporting
from zikaron.core.knowledge.database import KnowledgeDatabase
from zikaron.core.knowledge.errors import RegistryUnavailableError
from zikaron.core.store.embedder import FakeEmbedder
from zikaron.core.store.store import Store
from zikaron.core.store.transactions import in_one_transaction, propagate
from zikaron.knowledge import scope
from zikaron.knowledge.indexer import detach
from zikaron.knowledge.main import _age, _dispatch, main

#: A pid no process can have, so *not running* is a fact rather than a race with the scheduler.
_DEAD_PID: Final = 2**22 + 7


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A project directory with a created memory store and a corpus to point at.

    Synchronous, like every test in this file: `main` owns its own event loop, so a test running
    inside one could not call it at all. That is the command's real shape rather than a
    concession — a person runs it, and it runs to completion.
    """
    config = config_for(tmp_path)
    embedder = FakeEmbedder(config.get_str("embed_model"), config.get_int("embed_dim"))

    async def _create() -> None:
        async with await Store.create(tmp_path / ".zikaron", config, embedder):
            pass

    asyncio.run(_create())
    corpus_root(tmp_path)
    return tmp_path


@dataclass(frozen=True, slots=True)
class _Started:
    """One build this command asked for, as the arguments it asked with."""

    name: str
    project: Path
    full: bool


@pytest.fixture(autouse=True)
def started(monkeypatch: pytest.MonkeyPatch) -> list[_Started]:
    """Every build the command under test starts, recorded instead of run.

    Autouse rather than opt-in: `add` and `refresh` both start one, so a test that forgot this
    would spawn a real build of a real corpus — minutes of work in a test process, outliving the
    test that caused it. What the spawn itself does is checked where it lives.
    """
    asked: list[_Started] = []

    def _record(name: str, *, project: Path, full: bool = False) -> list[str]:
        asked.append(_Started(name=name, project=project, full=full))
        return detach.command(name, project=project, full=full)

    monkeypatch.setattr(detach, "spawn", _record)
    return asked


def _run(project_dir: Path, *argv: str) -> int:
    return main(["--project", str(project_dir), *argv])


def _hold_the_lock(project_dir: Path, *, pid: int, host: str) -> None:
    """Record a build lock against the `docs` corpus, as a real indexer would when it starts.

    Written straight into the knowledge base's own `meta` rather than by starting a build, because
    what these tests are about is what the command does when it *finds* one — including the two
    holders no build of this test's own could produce: one on another machine, and one whose
    process has died.
    """

    async def _go() -> None:
        store_dir = project_dir / ".zikaron"
        config = config_for(project_dir)
        async with await Store.open(store_dir, config) as store:
            registered = await registry.require(store.connection, "docs")
            async with await KnowledgeDatabase.open(store_dir, registered.id) as opened:

                async def _work(connection: aiosqlite.Connection) -> None:
                    await lock.acquire(
                        connection, pid=pid, host=host, started_at="2026-01-01T00:00:00+00:00"
                    )

                await in_one_transaction(opened.connection, _work, failure=propagate)

    asyncio.run(_go())


class TestTheVerbs:
    def test_add_then_list_then_rename_then_remove(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert (
            _run(
                project,
                "add",
                "Design Docs",
                "--path",
                str(project / "docs"),
                "--description",
                "architecture records",
            )
            == 0
        )
        added = capsys.readouterr().out
        assert "design docs" in added
        assert "reindex_required" in added

        assert _run(project, "list") == 0
        listed = capsys.readouterr().out
        assert "design docs" in listed
        assert "architecture records" in listed

        assert _run(project, "rename", "design docs", "Design Records") == 0
        assert "design records" in capsys.readouterr().out

        assert _run(project, "status", "design records") == 0
        detailed = capsys.readouterr().out
        assert str(project / "docs") in detailed
        assert "git-mode" in detailed

        assert _run(project, "remove", "design records", "--yes") == 0
        assert "removed" in capsys.readouterr().out

        assert _run(project, "list") == 0
        assert "no knowledge bases" in capsys.readouterr().out

    def test_remove_without_yes_reports_and_refuses(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Destroying a corpus on an unconfirmed call is the one mistake that cannot be undone, so
        the unconfirmed form reports what would go and exits non-zero."""
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        capsys.readouterr()

        assert _run(project, "remove", "docs") == 1
        printed = capsys.readouterr().out
        assert "would destroy" in printed
        assert "--yes" in printed

        assert _run(project, "list") == 0
        assert "docs" in capsys.readouterr().out

    def test_status_without_a_name_reports_every_knowledge_base(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        for name in ("one", "two"):
            _run(project, "add", name, "--path", str(project / "docs"), "--description", name)
        capsys.readouterr()

        assert _run(project, "status") == 0
        printed = capsys.readouterr().out
        assert "one" in printed
        assert "two" in printed

    def test_add_persists_the_options_it_was_given(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A setting accepted and not persisted would be silently undone by the next build, which
        would re-walk under the global default and change the corpus the caller defined."""
        assert (
            _run(
                project,
                "add",
                "docs",
                "--path",
                str(project / "docs"),
                "--description",
                "d",
                "--include",
                "*.md",
                "--include",
                "*.txt",
                "--exclude",
                "draft/*",
                "--git-mode",
                "off",
                "--max-file-bytes",
                "4096",
            )
            == 0
        )
        capsys.readouterr()

        assert _run(project, "status", "docs") == 0
        printed = capsys.readouterr().out
        assert "include   *.md, *.txt" in printed
        assert "exclude   draft/*" in printed
        assert "git-mode  off" in printed
        assert "4096 bytes" in printed


class TestRefusalsReachTheExitStatus:
    def test_an_unknown_name_exits_non_zero_and_says_so(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run(project, "status", "absent") == 1
        assert "refused" in capsys.readouterr().err

    def test_a_duplicate_name_exits_non_zero(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        assert (
            _run(project, "add", "DOCS", "--path", str(project / "docs"), "--description", "e") == 1
        )
        assert "already exists" in capsys.readouterr().err

    def test_a_bad_root_exits_non_zero(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert (
            _run(project, "add", "docs", "--path", str(project / "nope"), "--description", "d") == 1
        )
        assert "does not exist" in capsys.readouterr().err

    def test_an_out_of_range_size_cap_exits_non_zero(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert (
            _run(
                project,
                "add",
                "docs",
                "--path",
                str(project / "docs"),
                "--description",
                "d",
                "--max-file-bytes",
                "0",
            )
            == 1
        )
        assert "refused" in capsys.readouterr().err

    def test_a_project_with_no_store_exits_non_zero_rather_than_creating_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The command opens the memory store through the ordinary path, so it inherits every
        check that path runs — and a project Zikaron was never installed into is refused rather
        than quietly given a store by a knowledge-base command."""
        assert _run(tmp_path, "list") == 1
        assert "refused" in capsys.readouterr().err
        assert not (tmp_path / ".zikaron" / "memory.db").exists()

    def test_an_orphan_is_reported_by_both_list_and_status(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        capsys.readouterr()
        stray = project / ".zikaron" / "knowledge" / "00000000-0000-4000-8000-000000000000.db"
        stray.write_bytes(b"")

        assert _run(project, "list") == 0
        printed = capsys.readouterr().out
        assert "orphaned database" in printed
        assert stray.name in printed


class TestTheDocumentedInvocation:
    """`python -m zikaron.knowledge` has to work, because it is what the design tells a person to
    run. Only a real subprocess exercises the `__main__` module that makes a package executable."""

    @pytest.mark.integration
    def test_the_module_is_executable_and_prints_its_usage(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "zikaron.knowledge", "--help"],
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
        )
        assert "python -m zikaron.knowledge" in result.stdout
        for verb in ("add", "list", "remove", "rename", "status"):
            assert verb in result.stdout

    @pytest.mark.integration
    def test_the_module_exits_non_zero_on_a_refusal(self, project: Path) -> None:
        """The status has to survive the trip through `__main__`, which is the one line of it that
        can be wrong — and a command that reported success on a refusal would be worse than one
        that failed to run at all."""
        argv = [
            sys.executable,
            "-m",
            "zikaron.knowledge",
            "--project",
            str(project),
            "status",
            "no",
        ]
        result = subprocess.run(  # noqa: S603 — a fixed, test-constructed interpreter path.
            argv,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        assert result.returncode == 1
        assert "refused" in result.stderr


class TestWhatTheOutputSays:
    def test_a_corpus_with_no_skips_says_none_rather_than_nine_zeroes(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The question the breakdown answers is *why is a file missing from the corpus*, and a
        wall of zeroes buries the one reason that fired. "Nothing was skipped" and "this was not
        measured" are different answers, so the empty case says so rather than printing nothing."""
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        capsys.readouterr()

        assert _run(project, "status", "docs") == 0
        assert "skipped   none" in capsys.readouterr().out

    def test_a_corpus_with_no_globs_says_so_rather_than_printing_an_empty_list(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        capsys.readouterr()

        assert _run(project, "status", "docs") == 0
        printed = capsys.readouterr().out
        assert "include   \u2014" in printed
        assert "exclude   \u2014" in printed

    def test_a_verb_the_dispatch_does_not_handle_fails_loudly(self, project: Path) -> None:
        """Unreachable through the command, which refuses an unknown verb before dispatch. Asserted
        because the branch a silent fall-through would land in is the destructive one: a verb added
        to the parser and forgotten here must fail rather than remove a knowledge base."""

        async def _go() -> None:
            async with await Store.open(project / ".zikaron", config_for(project)) as store:
                await _dispatch(
                    argparse.Namespace(verb="invent"),
                    scope.OpenStore(
                        project=project,
                        directory=project / ".zikaron",
                        connection=store.connection,
                        config=config_for(project),
                    ),
                )

        with pytest.raises(NotImplementedError, match="invent"):
            asyncio.run(_go())


class TestWhereTheCommandActs:
    def test_without_a_project_it_uses_the_same_scope_rule_both_clients_use(
        self, project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Resolved through the harness seam rather than by reading the working directory here, so
        this command and the agent's own tools address one store rather than two."""
        monkeypatch.chdir(project)
        assert main(["list"]) == 0
        assert "no knowledge bases" in capsys.readouterr().out

    def test_a_knowledge_base_with_no_database_prints_that_rather_than_zeroes(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A corpus that has never been built has no diagnostics to show, and printing zeroes for
        them would read as measurements of an empty corpus rather than as their absence."""
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        for path in (project / ".zikaron" / "knowledge").iterdir():
            path.unlink()
        capsys.readouterr()

        assert _run(project, "status", "docs") == 0
        printed = capsys.readouterr().out
        assert "no database to read" in printed
        assert "reindex_required" in printed

    def test_a_failure_that_is_not_a_refusal_is_reported_rather_than_traced(
        self, project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Every predictable refusal is raised as one. This is the remainder — a full disk, a
        revoked permission — which tells whoever ran the command nothing they can act on if it
        arrives as a traceback."""

        async def _fail(*_args: object, **_kwargs: object) -> None:
            raise OSError("the disk is full")

        monkeypatch.setattr(reporting, "list_bases", _fail)
        assert _run(project, "list") == 1
        assert "failed: the disk is full" in capsys.readouterr().err


class TestStartingABuild:
    """`add` and `refresh` both start one and return. Nothing waits: a build is minutes of work
    over a whole tree, and the two verbs that create a corpus would otherwise be the two slowest
    things this command does."""

    def test_add_starts_a_build_of_the_corpus_it_just_created(
        self, project: Path, started: list[_Started], capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert (
            _run(project, "add", "Docs", "--path", str(project / "docs"), "--description", "d") == 0
        )
        assert started == [_Started(name="docs", project=project, full=False)]
        printed = capsys.readouterr().out
        assert "building" in printed
        assert "status docs" in printed

    def test_refresh_starts_one_for_a_corpus_that_already_exists(
        self, project: Path, started: list[_Started]
    ) -> None:
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        started.clear()

        assert _run(project, "refresh", "docs") == 0
        assert started == [_Started(name="docs", project=project, full=False)]

    def test_a_full_build_is_asked_for_by_name(
        self, project: Path, started: list[_Started]
    ) -> None:
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        started.clear()

        assert _run(project, "refresh", "docs", "--full") == 0
        assert started == [_Started(name="docs", project=project, full=True)]

    def test_the_command_that_reproduces_a_failed_build_is_printed(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A detached build's output goes nowhere, so the one way back to *why* it failed is to run
        the identical command where its output can be seen."""
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        capsys.readouterr()

        assert _run(project, "refresh", "docs", "--full") == 0
        printed = capsys.readouterr().out
        assert "zikaron.knowledge.indexer" in printed
        assert "--full" in printed
        assert str(project) in printed

    def test_an_unknown_name_refuses_in_the_foreground_and_starts_nothing(
        self, project: Path, started: list[_Started], capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The build detaches with its output discarded, so a refusal it raised would reach nobody.
        Everything decidable without reading a file is decided here instead."""
        assert _run(project, "refresh", "absent") == 1
        assert started == []
        assert "refused" in capsys.readouterr().err

    def test_a_knowledge_base_with_no_database_refuses_rather_than_starting_a_build(
        self, project: Path, started: list[_Started], capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Everything that says what a corpus indexes lives in the file that is missing, so there
        is nothing for a walk to walk."""
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        for path in (project / ".zikaron" / "knowledge").iterdir():
            path.unlink()
        started.clear()
        capsys.readouterr()

        assert _run(project, "refresh", "docs") == 1
        assert started == []
        assert "remove it and add it again" in capsys.readouterr().err

    def test_a_root_that_has_gone_refuses_in_the_foreground_and_starts_nothing(
        self, project: Path, started: list[_Started], capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The refusal a detached build leaves no trace of at all: it happens before the lock is
        taken, so there is not even a dead holder to find afterwards."""
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        for path in (project / "docs").iterdir():
            path.unlink()
        (project / "docs").rmdir()
        started.clear()
        capsys.readouterr()

        assert _run(project, "refresh", "docs") == 1
        assert started == []
        assert "kept as it is" in capsys.readouterr().err

    def test_a_build_that_cannot_be_shown_dead_refuses_the_next_one(
        self, project: Path, started: list[_Started], capsys: pytest.CaptureFixture[str]
    ) -> None:
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        _hold_the_lock(project, pid=os.getpid(), host=lock.this_host())
        started.clear()
        capsys.readouterr()

        assert _run(project, "refresh", "docs") == 1
        assert started == []
        assert "already running" in capsys.readouterr().err

    def test_a_lock_a_crashed_build_left_stops_nothing(
        self, project: Path, started: list[_Started]
    ) -> None:
        """Those rows survive on purpose, and the next build reclaims them. Refusing on them would
        make one dead process a permanent refusal."""
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        _hold_the_lock(project, pid=_DEAD_PID, host=lock.this_host())
        started.clear()

        assert _run(project, "refresh", "docs") == 0
        assert started == [_Started(name="docs", project=project, full=False)]


class TestClearingALockFromTheCommandLine:
    def test_a_foreign_lock_is_cleared_and_the_build_goes_ahead(
        self, project: Path, started: list[_Started], capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Nothing reclaims a foreign lock on its own, so without this the corpus is one nothing
        can build, remove or wait out."""
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        _hold_the_lock(project, pid=_DEAD_PID, host="another-machine")
        started.clear()
        capsys.readouterr()

        assert _run(project, "refresh", "docs", "--force-unlock") == 0
        printed = capsys.readouterr().out
        assert "cleared the lock" in printed
        assert started == [_Started(name="docs", project=project, full=False)]

    def test_a_running_local_build_is_refused_and_nothing_is_started(
        self, project: Path, started: list[_Started], capsys: pytest.CaptureFixture[str]
    ) -> None:
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        _hold_the_lock(project, pid=os.getpid(), host=lock.this_host())
        started.clear()
        capsys.readouterr()

        assert _run(project, "refresh", "docs", "--force-unlock") == 1
        assert started == []
        assert "still answers to the lock" in capsys.readouterr().err

    def test_no_lock_at_all_is_reported_and_the_build_still_starts(
        self, project: Path, started: list[_Started], capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Somebody reaching for this cannot see whether a lock is still there, which is why they
        are reaching for it — and the flag is on `refresh`, so finding nothing to clear leaves the
        verb they actually asked for to go ahead."""
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        started.clear()
        capsys.readouterr()

        assert _run(project, "refresh", "docs", "--force-unlock") == 0
        assert "nothing to clear" in capsys.readouterr().out
        assert started == [_Started(name="docs", project=project, full=False)]


class TestWhatStatusSaysAboutABuild:
    def test_a_running_build_on_this_host_is_reported_as_running(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        _hold_the_lock(project, pid=os.getpid(), host=lock.this_host())
        capsys.readouterr()

        assert _run(project, "status", "docs") == 0
        printed = capsys.readouterr().out
        assert "still answers to that pid" in printed
        assert f"pid {os.getpid()}" in printed

    def test_a_build_whose_process_is_gone_says_so(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The only evidence a detached build died: its output went nowhere, and every counter it
        left behind looks exactly like one still climbing."""
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        _hold_the_lock(project, pid=_DEAD_PID, host=lock.this_host())
        capsys.readouterr()

        assert _run(project, "status", "docs") == 0
        assert "no longer running" in capsys.readouterr().out

    def test_a_foreign_lock_points_at_the_way_to_clear_it(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        _hold_the_lock(project, pid=_DEAD_PID, host="another-machine")
        capsys.readouterr()

        assert _run(project, "status", "docs") == 0
        printed = capsys.readouterr().out
        assert "another-machine" in printed
        assert "--force-unlock" in printed

    def test_a_corpus_nobody_is_building_reports_no_lock_at_all(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        capsys.readouterr()

        assert _run(project, "status", "docs") == 0
        assert "build     " not in capsys.readouterr().out


class TestAStoreThatCannotBeRead:
    def test_it_says_the_registry_is_unavailable_rather_than_that_there_are_none(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The list of knowledge bases lives in the memory store, so a store that will not open
        makes every corpus undiscoverable — and *no knowledge bases* is a real answer for a project
        that has none, which a caller would read as the corpora being gone."""
        (project / ".zikaron" / "memory.db").write_bytes(b"not a database at all")

        assert _run(project, "list") == 1
        printed = capsys.readouterr()
        assert "could not be read" in printed.err
        assert "no knowledge bases" not in printed.out

    def test_the_refusal_is_the_one_a_caller_can_branch_on(self, project: Path) -> None:
        """Pinned as a **type**, not as the words it prints. These classes are separate so that a
        surface mapping refusals onto wire codes can do it on the class rather than by matching
        prose — and a message reworded later must not silently change which branch a caller takes.
        A test that read only the printed text would pass for any refusal at all."""
        (project / ".zikaron" / "memory.db").write_bytes(b"not a database at all")

        async def _go() -> None:
            async with scope.open_store(project):
                pass

        with pytest.raises(RegistryUnavailableError):
            asyncio.run(_go())


class TestHowALocksAgeIsPrinted:
    """Coarse on purpose: the question is *has this been sitting here*, so a second-exact figure
    would be precision nobody acts on over a number large enough to have to be counted digit by
    digit. Each unit is checked at its own boundary, because an off-by-one there reports days as
    hours."""

    @pytest.mark.parametrize(
        ("seconds", "printed"),
        [
            (0.0, "0s"),
            (59.9, "59s"),
            (60.0, "1m"),
            (3599.0, "59m"),
            (3600.0, "1h"),
            (86399.0, "23h"),
            (86400.0, "1d"),
            (200000.0, "2d"),
        ],
    )
    def test_each_unit_takes_over_at_its_own_boundary(self, seconds: float, printed: str) -> None:
        assert _age(seconds) == printed


class TestWhatTheFollowLineSays:
    def test_a_two_word_name_is_quoted_so_the_line_can_be_pasted_back(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Names are free-form and two-word ones are ordinary. Unquoted, the line offered as the way
        to follow a build is a command that fails to parse."""
        assert (
            _run(
                project,
                "add",
                "Design Docs",
                "--path",
                str(project / "docs"),
                "--description",
                "d",
            )
            == 0
        )
        printed = capsys.readouterr().out
        assert "status 'design docs'" in printed
