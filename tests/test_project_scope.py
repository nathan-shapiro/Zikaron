"""Which project a typed command acts on, and what it does when that project has no store.

**The defect these pin is one a green suite had.** Routing `zikaron knowledge` through the service
made the service's store creation reachable from any directory, so a command typed outside the
project built a second store and answered from it — correctly, and about nothing. Every case here
is a directory a person plausibly types in.
"""

import errno
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Final

import pytest

from zikaron.core.errors import BadConfigSource, ErrorCode, ZikaronError
from zikaron.harness.spec import CLAUDE_CODE, KIRO
from zikaron.knowledge.main import _initialize_command
from zikaron.knowledge.main import main as knowledge
from zikaron.project import initialize as initialize_module
from zikaron.project.initialize import main as initialize
from zikaron.project.resolve import (
    CONSOLE_INITIALIZE,
    EXPLICIT_PROJECT,
    MODULE_INITIALIZE,
    WORKING_DIRECTORY,
    Project,
    nearest_store_above,
    refusal,
    resolve,
)
from zikaron.service import paths


class _AnsweringClient:
    """Stands in for `KnowledgeClient` where the call's *result* is irrelevant: `init` sends one
    `health` only so that reaching the service creates the store."""

    async def call(self, _method: str, _params: dict[str, object]) -> dict[str, object]:
        return {}


_STORE: Final = ".zikaron"
_DATABASE: Final = "memory.db"


@pytest.fixture
def initialized(tmp_path: Path) -> Path:
    """A project whose `memory.db` is present. **The file is empty, and that is not a working
    store** — it is the artefact a create that failed after connecting leaves behind. Nothing in
    this file opens one, so the distinction is invisible here and load-bearing everywhere else:
    `has_store` answers *is there a file*, and only the service's own open answers *is it sound*.
    """
    (tmp_path / _STORE).mkdir()
    (tmp_path / _STORE / _DATABASE).touch()
    return tmp_path


@pytest.fixture
def half_started(tmp_path: Path) -> Path:
    """What a first start that failed or was interrupted leaves behind: the directory and no
    database.

    The service creates `.zikaron/` for its log before `ServiceContext.assemble` runs, so this is
    reachable from a cold cache with no network, a bad `.zikaron/config.toml`, or a client that
    gave up at its poll deadline. It is the state that makes *the directory exists* the wrong
    question to ask.
    """
    (tmp_path / _STORE).mkdir()
    (tmp_path / _STORE / "service.log").touch()
    return tmp_path


def test_only_one_harness_even_declares_a_project_directory() -> None:
    """**This reads the declarations, which is all a hermetic test can reach.** Whether a live
    harness *exports* the variable to a shell is not assertable here; it was measured separately
    (`research/claude-project-dir-reaches-hooks-not-shells.md`: Claude Code exports it to hooks and
    not to the agent's shell, so a typed command resolves through the fallback rung in practice).
    What this pins is that kiro declares none at all, so an inherited `CLAUDE_PROJECT_DIR` can
    never rescope a command under it.
    """
    assert KIRO.project_dir_variable is None
    assert CLAUDE_CODE.project_dir_variable == "CLAUDE_PROJECT_DIR"


class TestWhichRungAnswered:
    def test_an_explicit_project_is_resolved_and_says_so(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Absolute at minimum, because the service outlives this shell and stringifies the value
        into the foreground command a build result prints — which would act on a different project
        when pasted from elsewhere. The tests below pin the stronger property."""
        monkeypatch.chdir(tmp_path)
        resolved = resolve(Path())
        assert resolved.directory.is_absolute()
        assert resolved.origin == "--project"

    def test_a_relative_explicit_project_is_resolved_not_merely_absolute(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """**`absolute()` keeps `..` and `resolve()` does not, and identity is compared on
        spellings.** The socket is keyed on the resolved path while `health.store_path` reports
        what the service was started with, so an unresolved `--project` starts a service the
        agent's MCP server and hook refuse on every call. `Path.cwd()` is already physical, which
        is what makes every other rung agree by construction.
        """
        (tmp_path / "sub").mkdir()
        monkeypatch.chdir(tmp_path / "sub")
        assert resolve(Path("..")).directory == tmp_path.resolve()

    def test_a_symlinked_explicit_project_is_resolved(self, tmp_path: Path) -> None:
        """The same defect by the route a provisioning script is likeliest to take: a checkout
        reached through a symlinked parent, or `--project "$PWD"`, where the shell's logical path
        disagrees with the physical one every other client computes."""
        real = tmp_path / "real"
        real.mkdir()
        link = tmp_path / "link"
        link.symlink_to(real)
        assert resolve(link).directory == real.resolve()

    def test_a_symlink_loop_is_refused_on_every_supported_version(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """**The outcome is one refusal; the branch it comes through is not the same everywhere.**
        Measured: 3.12's `Path.resolve()` raises `RuntimeError` and this is caught; 3.13 and 3.14
        return the unresolved path and the `is_dir()` check refuses it instead. This asserts what a
        reader gets, which is the part that must not vary.
        """
        loop = tmp_path / "loop"
        loop.symlink_to(tmp_path / "loop2")
        (tmp_path / "loop2").symlink_to(loop)
        assert initialize(["--project", str(loop)]) == 1
        assert "refused:" in capsys.readouterr().err

    def test_a_resolution_failure_is_refused_rather_than_raised(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The `except` itself, reached the same way on every version, since the test above only
        enters it on 3.12. An `OSError` out of `resolve()` must reach the reader as a refusal
        naming the path, never as a traceback."""

        def _raising(_self: Path, *_args: object, **_keywords: object) -> Path:
            raise OSError(errno.ELOOP, "Too many levels of symbolic links")

        monkeypatch.setattr(Path, "resolve", _raising)
        assert initialize(["--project", str(tmp_path)]) == 1
        printed = capsys.readouterr().err
        assert "refused:" in printed
        assert str(tmp_path) in printed

    def test_a_knowledge_verb_refuses_a_resolution_failure_too(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """**Both callers of `resolve`, not just the one the guard was written for.** `init` and the
        verbs each catch this before any connection exists, and a guard covered on one caller of a
        shared helper is the class that looks tested and is not: uncaught here, a `--project` this
        machine cannot resolve reaches the reader as a traceback.
        """

        def _raising(_self: Path, *_args: object, **_keywords: object) -> Path:
            raise OSError(errno.ELOOP, "Too many levels of symbolic links")

        monkeypatch.setattr(Path, "resolve", _raising)
        assert knowledge(["--project", str(tmp_path), "list"]) == 1
        printed = capsys.readouterr().err
        assert "refused:" in printed
        assert str(tmp_path) in printed

    def test_the_harness_variable_is_honoured_and_named(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The case that makes a subdirectory harmless: the variable answers and the cwd never
        enters. The marker is set too, because the variable is read through the harness that
        declares it — under kiro, which declares none, `CLAUDE_PROJECT_DIR` is correctly ignored.
        """
        deep = tmp_path / "src" / "deep"
        deep.mkdir(parents=True)
        monkeypatch.setenv(str(CLAUDE_CODE.marker_variable), "1")
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        monkeypatch.chdir(deep)
        resolved = resolve(None)
        assert resolved.directory == tmp_path
        assert resolved.origin == "$CLAUDE_PROJECT_DIR"

    def test_a_variable_naming_the_working_directory_is_still_reported_as_the_variable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """**The cell the rung fix was made for.** Deriving the rung by comparing the resolved
        directory against the cwd reports *the working directory* here, and the refusal then
        advises a `cd` that resolves to the same place and refuses again. Reading whether the
        variable answered cannot be wrong that way.
        """
        deep = tmp_path / "src" / "deep"
        deep.mkdir(parents=True)
        monkeypatch.setenv(str(CLAUDE_CODE.marker_variable), "1")
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(deep))
        monkeypatch.chdir(deep)
        assert resolve(None).origin == "$CLAUDE_PROJECT_DIR"

    def test_the_other_harnesss_variable_is_not_read(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A variable is read through the harness that declares it, never by name alone. Under
        kiro, which declares none, an inherited `CLAUDE_PROJECT_DIR` — a real possibility in a
        nested session — must not silently rescope the command.
        """
        deep = tmp_path / "src" / "deep"
        deep.mkdir(parents=True)
        monkeypatch.delenv(str(CLAUDE_CODE.marker_variable), raising=False)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        monkeypatch.chdir(deep)
        assert resolve(None).directory == deep

    def test_without_a_usable_variable_it_is_the_working_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
        monkeypatch.chdir(tmp_path)
        resolved = resolve(None)
        assert resolved.directory == tmp_path
        # The literal, not `WORKING_DIRECTORY`: this is the pin on what a reader is shown, and
        # asserting the constant against itself would hold for any wording it was changed to.
        assert resolved.origin == "the working directory"


class TestWhetherThereIsAStore:
    def test_a_project_with_no_store_directory_has_none(self, tmp_path: Path) -> None:
        assert not Project(tmp_path, WORKING_DIRECTORY).has_store

    def test_a_store_directory_without_a_database_is_not_a_store(self, half_started: Path) -> None:
        """**The blocker this predicate was changed for.** The service creates `.zikaron/` for its
        log before it creates the store, so keying on the directory would report a failed first
        start as initialized and let every verb past the check — leaving the service to create the
        store behind whichever verb ran first, which is the defect the refusal removes.
        """
        project = Project(half_started, WORKING_DIRECTORY)
        assert project.store_dir_exists
        assert not project.has_store

    def test_a_database_makes_it_a_store(self, initialized: Path) -> None:
        project = Project(initialized, WORKING_DIRECTORY)
        assert project.has_store
        assert project.store_dir == initialized / _STORE


class TestTheAncestorSearchBindsNothing:
    def test_it_finds_the_nearest_ancestor(self, initialized: Path) -> None:
        deep = initialized / "src" / "deep"
        deep.mkdir(parents=True)
        assert nearest_store_above(deep) == initialized / _STORE

    def test_it_never_returns_the_directory_itself(self, initialized: Path) -> None:
        """The caller already knows this directory has none; returning it would make a refusal
        advise running the command where it was just run."""
        assert nearest_store_above(initialized) is None

    def test_a_sibling_package_store_is_not_reachable(self, tmp_path: Path) -> None:
        """The monorepo shape, and the reason nothing here *binds* what it finds. `packages/b` has
        its own store; a command run under `packages/a` must not be told about it, and must never
        be silently bound to it."""
        (tmp_path / "packages" / "a").mkdir(parents=True)
        (tmp_path / "packages" / "b" / _STORE).mkdir(parents=True)
        (tmp_path / "packages" / "b" / _STORE / _DATABASE).touch()
        assert nearest_store_above(tmp_path / "packages" / "a") is None

    def test_an_ancestor_with_no_database_is_not_offered(self, half_started: Path) -> None:
        """Naming a directory a failed first start left behind would send the reader somewhere
        that refuses too, which is a loop with extra steps."""
        deep = half_started / "src" / "deep"
        deep.mkdir(parents=True)
        assert nearest_store_above(deep) is None


class TestTheRefusal:
    def test_it_names_the_directory_and_the_rung(self, tmp_path: Path) -> None:
        """The rung, because the remedy differs: a wrong `CLAUDE_PROJECT_DIR` is not repaired by
        changing directory, and a mistyped `--project` is not repaired by exporting one."""
        printed = refusal(Project(tmp_path, "$CLAUDE_PROJECT_DIR"), initialize=CONSOLE_INITIALIZE)
        assert str(tmp_path) in printed
        assert "resolved from $CLAUDE_PROJECT_DIR" in printed
        assert CONSOLE_INITIALIZE in printed

    def test_it_names_a_store_it_found_above(self, initialized: Path) -> None:
        deep = initialized / "src" / "deep"
        deep.mkdir(parents=True)
        printed = refusal(Project(deep, WORKING_DIRECTORY), initialize=CONSOLE_INITIALIZE)
        assert f"a store exists at {initialized / _STORE}" in printed
        assert f"--project {initialized}" in printed
        assert f"run this from {initialized}" in printed

    def test_with_nothing_above_it_advises_naming_the_project(self, tmp_path: Path) -> None:
        printed = refusal(Project(tmp_path, WORKING_DIRECTORY), initialize=MODULE_INITIALIZE)
        assert "a store exists at" not in printed
        assert "pass --project to name the project" in printed

    def test_moving_is_not_offered_when_the_directory_did_not_come_from_the_shell(
        self, initialized: Path
    ) -> None:
        """**The message must not contradict its own diagnosis.** It has just said the directory
        came from `$CLAUDE_PROJECT_DIR`; under that rung `cd` resolves to the same place and
        refuses again, so `--project` — the top rung — is the only move offered.
        """
        deep = initialized / "src" / "deep"
        deep.mkdir(parents=True)
        printed = refusal(Project(deep, "$CLAUDE_PROJECT_DIR"), initialize=CONSOLE_INITIALIZE)
        assert f"--project {initialized}" in printed
        assert "run this from" not in printed

    def test_a_reader_who_passed_project_is_not_told_to_pass_project(self, tmp_path: Path) -> None:
        """The same loop as the one above, one rung up: answering a mistyped `--project` with
        *pass --project* repeats back what the reader already did."""
        printed = refusal(Project(tmp_path, EXPLICIT_PROJECT), initialize=CONSOLE_INITIALIZE)
        assert "check the path given to --project" in printed
        assert "pass --project" not in printed
        assert "run this from" not in printed

    @pytest.mark.parametrize("origin", [WORKING_DIRECTORY, EXPLICIT_PROJECT, "$CLAUDE_PROJECT_DIR"])
    def test_a_half_started_store_directory_gets_only_the_repair(
        self, half_started: Path, origin: str
    ) -> None:
        """**Diagnosing one reader and advising another is the defect here.** This reader is in the
        right project with an interrupted first start in it, so an ancestor to move to or a
        `--project` to correct is wrong advice under every rung — the `.zikaron/` is right there.
        """
        printed = refusal(Project(half_started, origin), initialize=CONSOLE_INITIALIZE)
        assert f"{half_started / _STORE} exists but holds no store" in printed
        assert CONSOLE_INITIALIZE in printed
        assert "pass --project" not in printed
        assert "check the path" not in printed
        assert "run this from" not in printed


class TestWhichInitializeCommandIsSuggested:
    """Naming a command the reader cannot run is a refusal that fails twice.

    `uv tool install` puts the console script on `PATH` and no interpreter; a source tree driven
    through `python -m` has the interpreter and may have no console script.
    """

    def test_the_console_form_is_suggested_to_a_console_caller(self) -> None:
        assert _initialize_command("zikaron knowledge") == CONSOLE_INITIALIZE

    def test_the_module_form_is_suggested_to_a_module_caller(self) -> None:
        assert _initialize_command("python -m zikaron.knowledge") == MODULE_INITIALIZE


class TestTheCommandsThemselves:
    def test_a_verb_in_a_storeless_project_refuses_and_creates_nothing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """**The assertion that matters is the second one.** Refusing while still leaving a store
        behind would be the same defect with a better message, and the store is created by
        *reaching* the service — so the check has to happen before the connection, not after a
        failure from it.
        """
        assert knowledge(["--project", str(tmp_path), "list"]) == 1
        assert "refused: no Zikaron store in" in capsys.readouterr().err
        assert not (tmp_path / _STORE).exists()

    def test_initialize_reaches_the_service_even_when_a_store_is_there_and_says_so(
        self, initialized: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A second `init` reports rather than refusing — exit 0, safe in a script that runs twice.

        **It still connects.** A `memory.db` the service cannot open is a file, so stopping at
        *there is a file* would report a permanently broken project as ready; the connection puts
        the identity read in front of it, which refuses by disposition exactly as a verb would.
        """
        reached: list[Path] = []

        @asynccontextmanager
        async def _recording(project: Path) -> AsyncIterator[object]:
            reached.append(project)
            yield _AnsweringClient()

        monkeypatch.setattr(initialize_module, "connected", _recording)
        assert initialize(["--project", str(initialized)]) == 0
        printed = capsys.readouterr().out
        assert "already initialized" in printed
        assert str(initialized / _STORE) in printed
        assert reached == [initialized]

    def test_initialize_still_reaches_the_service_when_only_the_directory_exists(
        self,
        half_started: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """**The blocker's other half.** Reporting *already initialized* here would leave a
        provisioning script proceeding against a project with no store; `init` must go on and ask
        for one. Patched rather than run for real, so this stays a unit test — what is under test
        is that the branch was taken at all.
        """
        reached: list[Path] = []

        @asynccontextmanager
        async def _recording(project: Path) -> AsyncIterator[object]:
            reached.append(project)
            paths.store_db_path(paths.store_dir(project)).touch()
            yield _AnsweringClient()

        monkeypatch.setattr(initialize_module, "connected", _recording)
        assert initialize(["--project", str(half_started)]) == 0
        assert reached == [half_started]
        assert "already initialized" not in capsys.readouterr().out

    def test_initialize_fails_when_the_service_answers_but_no_store_appears(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A service answering `health` is not the same fact as a store existing, and the second
        is what every later command tests. Reporting success on the first would hand a
        provisioning script a project its next step refuses."""

        @asynccontextmanager
        async def _creating_nothing(_project: Path) -> AsyncIterator[object]:
            yield _AnsweringClient()

        monkeypatch.setattr(initialize_module, "connected", _creating_nothing)
        assert initialize(["--project", str(tmp_path)]) == 1
        assert "no store is at" in capsys.readouterr().err

    def test_a_refused_start_is_rendered_by_its_codes_disposition(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The shared ladder in `report.execute`, reached from `init` rather than from a verb: a
        `ZikaronError` raised while establishing the connection prints by the code's own declared
        disposition, so this command and `zikaron-mcp` cannot disagree about whether the caller has
        a move."""

        def _refusing(_project: Path) -> object:
            raise ZikaronError(
                ErrorCode.BAD_CONFIG,
                source=BadConfigSource.DERIVED,
                key="runtime_dir",
                value="/x",
                expected="something else",
            )

        monkeypatch.setattr(initialize_module, "connected", _refusing)
        assert initialize(["--project", str(tmp_path)]) == 1
        assert "refused:" in capsys.readouterr().err

    def test_initialize_under_an_existing_store_says_it_is_creating_a_second(
        self, initialized: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """**The one command that reaches the second-store defect by design.** The README sends a
        reader to `init` first, and a reader who runs it one directory too deep gets exactly what
        the verbs' refusal exists to prevent. A monorepo makes it legitimate, so this notes rather
        than refuses — and binds nothing.
        """
        nested = initialized / "src"
        nested.mkdir()

        @asynccontextmanager
        async def _creating(project: Path) -> AsyncIterator[object]:
            paths.store_db_path(paths.store_dir(project)).parent.mkdir(exist_ok=True)
            paths.store_db_path(paths.store_dir(project)).touch()
            yield _AnsweringClient()

        monkeypatch.setattr(initialize_module, "connected", _creating)
        assert initialize(["--project", str(nested)]) == 0
        printed = capsys.readouterr()
        assert f"a store already exists at {initialized / _STORE}" in printed.err
        assert "initialized" in printed.out

    def test_initialize_with_nothing_above_says_nothing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The note must not fire for the ordinary case, or it stops meaning anything."""

        @asynccontextmanager
        async def _creating(project: Path) -> AsyncIterator[object]:
            paths.store_dir(project).mkdir(exist_ok=True)
            paths.store_db_path(paths.store_dir(project)).touch()
            yield _AnsweringClient()

        monkeypatch.setattr(initialize_module, "connected", _creating)
        assert initialize(["--project", str(tmp_path)]) == 0
        assert "already exists at" not in capsys.readouterr().err

    def test_initialize_refuses_a_project_that_is_not_a_directory(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`ensure_store_dir` is `mkdir(parents=True)`, so without this check a mistyped
        `--project` builds the tree and a store in it — reached from the verbs' own refusal, which
        ends by offering this command."""
        missing = tmp_path / "tpyo" / "deeper"
        assert initialize(["--project", str(missing)]) == 1
        assert "is not a directory" in capsys.readouterr().err
        assert not missing.exists()

    def test_a_connect_deadline_miss_says_to_run_it_again(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The failure this command owns alone looks permanent from here and usually is not: the
        client gives up while the service goes on starting."""

        def _refusing(_project: Path) -> object:
            # `connected` raising stands in for the `call` that would: `connected` only computes
            # the location, and the socket is reached inside `call`. Both sit in `_create`'s `try`.
            raise ConnectionError("no server became reachable at /x.sock before the deadline")

        monkeypatch.setattr(initialize_module, "connected", _refusing)
        assert initialize(["--project", str(tmp_path)]) == 1
        printed = capsys.readouterr().err
        assert "never reached its own logging" in printed
        assert "look in" not in printed
        assert MODULE_INITIALIZE in printed

    def test_a_deadline_miss_with_a_service_log_points_at_it(
        self,
        half_started: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """**The two causes of a timeout are a slow start and a dead one, and the advice differs.**
        A retry alone loops forever when the service died inside its first start — offline with a
        cold cache, an unreadable config, an extension that will not load. The log is on disk by
        the ordering §"First run" chose for exactly this, so the message names it.

        **The negative assertion is what makes this discriminate**: the log path appears in the
        absent-log wording too, so asserting it alone would hold under either branch.
        """

        def _refusing(_project: Path) -> object:
            raise ConnectionError("no server became reachable at /x.sock before the deadline")

        monkeypatch.setattr(initialize_module, "connected", _refusing)
        assert initialize(["--project", str(half_started)]) == 1
        printed = capsys.readouterr().err
        assert str(paths.service_log_path(half_started / _STORE)) in printed
        assert "look in" in printed
        assert "never reached its own logging" not in printed
        # A first start, so the artifact fetch is live and worth naming.
        assert "embedding artifact" in printed
        assert MODULE_INITIALIZE in printed

    def test_a_deadline_miss_against_an_existing_store_does_not_blame_the_fetch(
        self,
        initialized: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """**On this path the artifact cannot be what missed the deadline.** A store already here
        means the service takes the *open* path, where the encoder loads on a background thread
        behind a socket that is already bound; only the create path waits for it. Naming a network
        fetch there reads as a flake and buys a re-run that fails identically — the loop this
        message exists to cut, on the path a script that runs twice takes every time but the first.
        """
        (initialized / _STORE / "service.log").touch()

        def _refusing(_project: Path) -> object:
            raise ConnectionError("no server became reachable at /x.sock before the deadline")

        monkeypatch.setattr(initialize_module, "connected", _refusing)
        assert initialize(["--project", str(initialized)]) == 1
        printed = capsys.readouterr().err
        assert "embedding artifact" not in printed
        assert str(paths.service_log_path(initialized / _STORE)) in printed
        assert MODULE_INITIALIZE in printed
