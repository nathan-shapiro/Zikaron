"""Validating a corpus root, and finding out whether the requested git mode will take effect.

The root is the one caller-supplied string in this system with any path semantics at all, so this
is the only place a supplied string is checked as a path — and the check is deliberately narrow: a
corpus outside the project directory is a legitimate use, so only degenerate roots are refused.
"""

import subprocess
from pathlib import Path

import pytest

from zikaron.core.knowledge.errors import InvalidRootError
from zikaron.core.knowledge.meta import GitMode
from zikaron.core.knowledge.roots import effective_git_mode, validate_root


class TestValidatingARoot:
    def test_an_ordinary_directory_is_accepted_and_returned_resolved(self, tmp_path: Path) -> None:
        root = tmp_path / "docs"
        root.mkdir()
        assert validate_root(root, home=tmp_path / "home") == root.resolve()

    def test_a_relative_path_is_resolved(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Stored resolved because the value outlives the call: a relative path would name
        different directories from different working directories."""
        root = tmp_path / "docs"
        root.mkdir()
        monkeypatch.chdir(tmp_path)
        assert validate_root(Path("docs"), home=tmp_path / "home") == root.resolve()

    def test_an_absent_path_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(InvalidRootError, match="does not exist"):
            validate_root(tmp_path / "nothing", home=tmp_path / "home")

    def test_a_tilde_naming_no_known_user_is_refused_rather_than_raising(
        self, tmp_path: Path
    ) -> None:
        """`~someone` for a user this machine has no record of. Expansion hands the string back
        unchanged and `Path` then refuses to say what it means — a `RuntimeError`, which is the
        wrong shape for what is a caller's mistake: it carries no field a surface can report and
        reaches a caller that typed a path as an internal failure. Refused in the same terms as
        any other root naming nothing, and `path` is the value as supplied, since expansion is
        where it stopped and there is no resolved form to report."""
        supplied = Path("~no-such-user-zikaron/docs")
        with pytest.raises(InvalidRootError, match="does not exist") as caught:
            validate_root(supplied, home=tmp_path / "home")
        assert caught.value.path == supplied

    def test_a_file_is_refused(self, tmp_path: Path) -> None:
        target = tmp_path / "a.md"
        target.write_text("x", encoding="utf-8")
        with pytest.raises(InvalidRootError, match="not a directory"):
            validate_root(target, home=tmp_path / "home")

    def test_the_filesystem_root_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(InvalidRootError, match="filesystem root"):
            validate_root(Path("/"), home=tmp_path / "home")

    def test_the_home_directory_itself_is_refused(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        home.mkdir()
        with pytest.raises(InvalidRootError, match="home directory"):
            validate_root(home, home=home)

    def test_a_directory_inside_the_home_directory_is_accepted(self, tmp_path: Path) -> None:
        """The check rejects degenerate roots, not distant ones — indexing a docs tree under the
        home directory is the ordinary case, not an edge one."""
        home = tmp_path / "home"
        inside = home / "notes"
        inside.mkdir(parents=True)
        assert validate_root(inside, home=home) == inside.resolve()

    def test_a_symlink_to_a_degenerate_root_is_refused(self, tmp_path: Path) -> None:
        """Resolution happens before the degenerate test, so a link pointing at `/` is refused
        rather than admitted under its own innocuous name."""
        link = tmp_path / "looks-fine"
        link.symlink_to("/")
        with pytest.raises(InvalidRootError, match="filesystem root"):
            validate_root(link, home=tmp_path / "home")


class TestWhetherGitWillTakeEffect:
    async def test_off_is_reported_without_consulting_git_at_all(self, tmp_path: Path) -> None:
        assert await effective_git_mode(tmp_path, GitMode.OFF) is GitMode.OFF

    @pytest.mark.parametrize("requested", [GitMode.TRACKED, GitMode.ALL])
    async def test_a_directory_outside_a_work_tree_degrades_to_off(
        self, tmp_path: Path, requested: GitMode
    ) -> None:
        """Ordinary rather than exotic: the default is `tracked` while indexing a docs tree
        outside any repository is an endorsed use, so a caller that was not told would discover it
        as a silently different corpus."""
        outside = tmp_path / "not-a-repo"
        outside.mkdir()
        assert await effective_git_mode(outside, requested) is GitMode.OFF

    @pytest.mark.integration
    @pytest.mark.parametrize("requested", [GitMode.TRACKED, GitMode.ALL])
    async def test_a_work_tree_keeps_the_mode_that_was_asked_for(
        self, tmp_path: Path, requested: GitMode
    ) -> None:
        """Against a real repository, because what is under test is what `git` actually answers —
        a stub would assert this suite's belief about `rev-parse` back to itself."""
        repository = tmp_path / "repo"
        repository.mkdir()
        subprocess.run(
            ["git", "init", "-q"],  # noqa: S607
            cwd=repository,
            check=True,
            capture_output=True,
            timeout=30,
        )
        assert await effective_git_mode(repository, requested) is requested

    async def test_every_way_the_probe_can_fail_is_the_same_answer(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Stated over the complement rather than over a list of causes, and that matters: `git`
        missing from `PATH`, a non-zero exit and a timeout are three different outcomes, and a rule
        naming only some of them would classify the rest as *yes, git is available here*.

        A timeout is included because it is the one that cannot be produced by a directory: it
        needs a `git` that hangs, which a network filesystem supplies and a test has to stage.
        """
        failures: list[BaseException] = [
            FileNotFoundError("no git on PATH"),
            PermissionError("not executable"),
            subprocess.TimeoutExpired(cmd="git", timeout=5.0),
            subprocess.SubprocessError("something else entirely"),
        ]
        for failure in failures:

            def _raise(
                *_args: object, _failure: BaseException = failure, **_kwargs: object
            ) -> None:
                raise _failure

            monkeypatch.setattr(subprocess, "run", _raise)
            assert await effective_git_mode(tmp_path, GitMode.TRACKED) is GitMode.OFF

    async def test_an_answer_that_is_not_the_word_true_is_not_an_answer(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Exit 0 alone is not enough: a `git` that succeeded while saying `false` is answering
        *no*, and reading only the status would take that for a yes."""

        class _Completed:
            returncode = 0
            stdout = "false\n"

        monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: _Completed())
        assert await effective_git_mode(tmp_path, GitMode.TRACKED) is GitMode.OFF
