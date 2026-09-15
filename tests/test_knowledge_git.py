"""Everything this package asks git, against real repositories.

Real `git` rather than a fake, because every assertion here is about what git actually answers —
which exit status means *nothing is ignored*, how a rename is spelled in a `-z` stream, what an
attribute's value looks like. A fake would assert this suite's beliefs back to itself, and those
beliefs are exactly what has been wrong before.

These stay in the default tier: `git` is a tool the suite already requires, every repository is
built under `tmp_path`, and nothing leaves the machine.
"""

import subprocess
from pathlib import Path

import pytest

from zikaron.core.knowledge import git, text
from zikaron.core.knowledge.git import (
    GitUnavailableError,
    _nul_records,
    _parse_attributes,
    _parse_listing,
    _parse_status,
)


def _git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 — a fixed argv built from this file's own literals.
        ["git", *arguments],  # noqa: S607
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    """An initialised repository with an identity, so commits are possible without one on the
    machine running the suite."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "suite@example.invalid")
    _git(root, "config", "user.name", "Suite")
    return root


def _write(root: Path, relative: str, content: str) -> Path:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


class TestTheWorkTreeProbe:
    async def test_a_repository_answers_yes(self, repository: Path) -> None:
        assert await git.inside_work_tree(repository)

    async def test_an_ordinary_directory_answers_no(self, tmp_path: Path) -> None:
        assert not await git.inside_work_tree(tmp_path)


class TestTheTrackedListing:
    async def test_it_gives_the_blob_hash_of_every_tracked_regular_file(
        self, repository: Path
    ) -> None:
        _write(repository, "a.md", "alpha\n")
        _write(repository, "docs/b.md", "beta\n")
        _write(repository, "untracked.md", "gamma\n")
        _git(repository, "add", "a.md", "docs/b.md")
        listed = await git.list_files(repository)
        assert set(listed) == {"a.md", "docs/b.md"}
        assert listed["a.md"] == _git(repository, "hash-object", "a.md").stdout.strip()

    async def test_an_executable_file_is_a_regular_file(self, repository: Path) -> None:
        script = _write(repository, "run.sh", "#!/bin/sh\n")
        script.chmod(0o755)
        _git(repository, "add", "run.sh")
        assert "run.sh" in await git.list_files(repository)

    async def test_a_tracked_symlink_is_not_listed(self, repository: Path) -> None:
        """Symlinks are refused by the walk on their own account; excluding them here keeps the
        intersection from re-admitting one the walk already declined to follow."""
        _write(repository, "real.md", "x\n")
        (repository / "link.md").symlink_to("real.md")
        _git(repository, "add", "real.md", "link.md")
        assert set(await git.list_files(repository)) == {"real.md"}

    async def test_a_path_containing_a_newline_keeps_its_own_spelling(
        self, repository: Path
    ) -> None:
        """Without `-z` git quotes and escapes such a path, and this listing is the join key
        against the walk — a mangled key drops the file out of the corpus rather than merely
        missing a fast path."""
        awkward = "weird\nname.md"
        _write(repository, awkward, "x\n")
        _git(repository, "add", "-A")
        assert awkward in await git.list_files(repository)

    async def test_outside_a_work_tree_it_refuses_rather_than_answering_empty(
        self, tmp_path: Path
    ) -> None:
        with pytest.raises(GitUnavailableError):
            await git.list_files(tmp_path)

    def test_a_gitlink_and_a_symlink_are_excluded_by_mode(self) -> None:
        """The modes are an allowlist rather than a list to reject, so a mode nobody anticipated
        is excluded rather than admitted. A gitlink's hash is a *commit* and its path is a
        directory on disk, so admitting one would put a commit id in a column documented as a
        content hash."""
        payload = (
            b"100644 1111111111111111111111111111111111111111 0\tkept.md\0"
            b"160000 2222222222222222222222222222222222222222 0\tsub\0"
            b"120000 3333333333333333333333333333333333333333 0\tlink.md\0"
            b"100755 4444444444444444444444444444444444444444 0\trun.sh\0"
        )
        assert set(_parse_listing(payload)) == {"kept.md", "run.sh"}


class TestParsingAStreamThatIsNotWhatWasExpected:
    """The parsers, against payloads git would not normally produce.

    Every one of these is a shape that returns a plausible answer rather than an error if it is
    mishandled, which is the failure this whole seam is written against: a record misaligned by
    one field answers about a path nobody asked about.
    """

    def test_a_stream_with_no_trailing_terminator_keeps_its_last_record(self) -> None:
        assert _nul_records(b"a\0b") == ["a", "b"]

    def test_exactly_one_trailing_terminator_is_dropped_and_inner_blanks_are_kept(self) -> None:
        """Some `-z` forms emit empty fields as real values, so a split that discards every empty
        string misaligns every record after the first one."""
        assert _nul_records(b"a\0\0b\0") == ["a", "", "b"]

    def test_an_empty_stream_is_no_records_rather_than_one_blank(self) -> None:
        assert _nul_records(b"") == []

    def test_a_listing_record_with_no_tab_is_ignored(self) -> None:
        # `\x00` rather than `\0` throughout: in a bytes literal `\0` followed by a digit is read
        # as one octal escape, so `\0100644` is a backspace and this payload would be a different
        # stream from the one it appears to be.
        payload = (
            b"garbage-with-no-tab\x00100644 1111111111111111111111111111111111111111 0\ta.md\x00"
        )
        assert set(_parse_listing(payload)) == {"a.md"}

    def test_a_status_field_too_short_to_carry_a_path_is_ignored(self) -> None:
        assert _parse_status(b"XY\0 M a.md\0", "") == {"a.md"}

    def test_a_prefix_is_stripped_from_every_path_including_a_renames_bare_one(self) -> None:
        """Both halves of a rename need it: the old path arrives with no status letters, so a
        parser that reconciled only the prefixed field would leave one repository-relative path
        among corpus-relative ones."""
        payload = b"R  docs/new.md\0docs/old.md\0 M docs/edited.md\0"
        assert _parse_status(payload, "docs/") == {"new.md", "old.md", "edited.md"}

    def test_a_path_above_the_prefix_is_dropped_rather_than_shortened(self) -> None:
        """A sibling of the corpus root could otherwise be shortened into a name that collides
        with one inside it — reporting a change to a file the corpus does not contain.

        **The non-colliding `notes.md` is what makes this test able to fail.** With only the
        colliding pair, an implementation that stripped where it could and dropped nothing would
        produce the same set, because the sibling's shortened name is already in it — so the
        assertion would hold whether or not anything was dropped."""
        payload = b" M notes.md\0 M guide.md\0 M docs/guide.md\0"
        assert _parse_status(payload, "docs/") == {"guide.md"}

    def test_an_attribute_record_for_something_nobody_asked_about_is_dropped(self) -> None:
        payload = b"a.md\0text\0set\0a.md\0diff\0unset\0"
        assert _parse_attributes(payload, ["text"]) == {"a.md": {"text": "set"}}


class TestTheStatusReport:
    async def test_an_edited_tracked_file_is_reported(self, repository: Path) -> None:
        _write(repository, "a.md", "alpha\n")
        _git(repository, "add", "-A")
        _git(repository, "commit", "-qm", "first")
        _write(repository, "a.md", "changed\n")
        assert "a.md" in await git.changed_paths(repository)

    async def test_a_file_inside_an_untracked_directory_is_named(self, repository: Path) -> None:
        """The default collapses an untracked directory into a single entry naming the directory,
        so an edited file inside one would go unreported."""
        _write(repository, "new/deep/a.md", "x\n")
        reported = await git.changed_paths(repository)
        assert "new/deep/a.md" in reported

    async def test_a_deleted_file_is_reported(self, repository: Path) -> None:
        _write(repository, "a.md", "alpha\n")
        _git(repository, "add", "-A")
        _git(repository, "commit", "-qm", "first")
        (repository / "a.md").unlink()
        assert "a.md" in await git.changed_paths(repository)

    async def test_a_rename_contributes_both_of_its_paths(self, repository: Path) -> None:
        """The stream carries the status letters and the **new** path, then the old path as a
        bare field with no status prefix at all — a parser expecting every field to begin with two
        status characters reads that old path as a malformed status line."""
        _write(repository, "old.md", "alpha\n")
        _git(repository, "add", "-A")
        _git(repository, "commit", "-qm", "first")
        _git(repository, "mv", "old.md", "new.md")
        reported = await git.changed_paths(repository)
        assert {"old.md", "new.md"} <= reported

    async def test_outside_a_work_tree_it_refuses(self, tmp_path: Path) -> None:
        with pytest.raises(GitUnavailableError):
            await git.changed_paths(tmp_path)


class TestTheIgnoreQuestion:
    async def test_ignored_paths_come_back_and_others_do_not(self, repository: Path) -> None:
        _write(repository, ".gitignore", "build/\n*.log\n")
        assert await git.ignored_paths(
            repository, ["build/out.txt", "notes.md", "run.log"]
        ) == frozenset({"build/out.txt", "run.log"})

    async def test_nothing_ignored_is_an_answer_rather_than_a_failure(
        self, repository: Path
    ) -> None:
        """It exits 1 to say so, which is the common case for a documentation tree — and a
        `returncode != 0` test would degrade every scan of one and record a degradation that did
        not happen as the explanation for a corpus it did not shape."""
        _write(repository, ".gitignore", "build/\n")
        assert await git.ignored_paths(repository, ["notes.md", "a/b.md"]) == frozenset()

    async def test_a_tracked_file_is_never_reported_ignored(self, repository: Path) -> None:
        """Git's own rule, implemented by git: ignore patterns do not affect tracked files. It
        holds only because the index is consulted, which is the default and must not be switched
        off."""
        _write(repository, ".gitignore", "*.log\n")
        _write(repository, "kept.log", "x\n")
        _git(repository, "add", "-f", "kept.log")
        assert await git.ignored_paths(repository, ["kept.log"]) == frozenset()

    async def test_a_path_containing_a_newline_is_answered_about_itself(
        self, repository: Path
    ) -> None:
        """Fed on a line-separated stdin, git splits such a path and answers about a *different*
        one — with exit 0 and a plausible-looking result."""
        _write(repository, ".gitignore", "*.log\n")
        assert await git.ignored_paths(repository, ["bad\nname.log"]) == frozenset(
            {"bad\nname.log"}
        )

    async def test_outside_a_work_tree_it_refuses(self, tmp_path: Path) -> None:
        with pytest.raises(GitUnavailableError):
            await git.ignored_paths(tmp_path, ["a.md"])

    async def test_no_paths_is_answered_without_asking_git(self, tmp_path: Path) -> None:
        """An empty question needs no subprocess, and answering it here is what makes the call
        safe to make unconditionally — including outside a work tree, where it would otherwise
        refuse."""
        assert await git.ignored_paths(tmp_path, []) == frozenset()


class TestTheAttributeQuestion:
    @pytest.mark.parametrize(
        ("rule", "name", "expected"),
        [
            ("*.bin binary", "x.bin", {"binary": "set", "text": "unset"}),
            ("*.dat -text", "x.dat", {"binary": "unspecified", "text": "unset"}),
            ("*.auto text=auto", "x.auto", {"binary": "unspecified", "text": "auto"}),
            ("*.md text", "x.md", {"binary": "unspecified", "text": "set"}),
            ("# nothing", "x.txt", {"binary": "unspecified", "text": "unspecified"}),
        ],
    )
    async def test_the_value_is_not_a_boolean(
        self, repository: Path, rule: str, name: str, expected: dict[str, str]
    ) -> None:
        _write(repository, ".gitattributes", f"{rule}\n")
        answers = await git.attributes(repository, [name], text.ATTRIBUTES)
        assert answers[name] == expected

    async def test_it_reads_the_working_tree_rather_than_the_commit(self, repository: Path) -> None:
        """So an uncommitted edit to `.gitattributes` changes which files a corpus admits, with no
        commit and no change to any indexed file to notice it by."""
        _write(repository, ".gitattributes", "*.dat text\n")
        _git(repository, "add", "-A")
        _git(repository, "commit", "-qm", "first")
        _write(repository, ".gitattributes", "*.dat -text\n")
        answers = await git.attributes(repository, ["x.dat"], text.ATTRIBUTES)
        assert text.excluded_by_attributes(answers["x.dat"])

    async def test_a_path_that_does_not_exist_is_answered_rather_than_refused(
        self, repository: Path
    ) -> None:
        answers = await git.attributes(repository, ["absent.md"], text.ATTRIBUTES)
        assert answers["absent.md"] == {"binary": "unspecified", "text": "unspecified"}

    async def test_outside_a_work_tree_it_refuses(self, tmp_path: Path) -> None:
        with pytest.raises(GitUnavailableError):
            await git.attributes(tmp_path, ["a.md"], text.ATTRIBUTES)

    async def test_no_paths_or_no_attributes_needs_no_subprocess(self, tmp_path: Path) -> None:
        assert await git.attributes(tmp_path, [], text.ATTRIBUTES) == {}
        assert await git.attributes(tmp_path, ["a.md"], []) == {}
