"""The filesystem walk: what it descends into, what it refuses, and what it counts on the way.

Every test builds a real tree on `tmp_path` and walks it. The walk's whole job is to describe a
filesystem, so a fake one would assert this suite's beliefs about `scandir` rather than the
behaviour anything downstream depends on.
"""

import os
from pathlib import Path

import pytest

from zikaron.core.knowledge import walk
from zikaron.core.knowledge.counters import ScanCounters, SkipReason

_ROOMY = 1_000_000


def _tree(root: Path, layout: dict[str, str]) -> Path:
    """Write one tree, creating parent directories as needed."""
    for relative, content in layout.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return root


def _walked(root: Path, counters: ScanCounters | None = None) -> list[str]:
    return [candidate.path for candidate in walk.entries(root, counters or ScanCounters())]


def _admitted(
    root: Path,
    counters: ScanCounters,
    *,
    rules: walk.WalkRules,
    ignored: frozenset[str] = frozenset(),
) -> list[str]:
    found = list(walk.entries(root, counters))
    return [
        candidate.path
        for candidate in walk.admitted(found, ignored=ignored, rules=rules, counters=counters)
    ]


class TestWhatItFinds:
    def test_paths_are_relative_to_the_root_in_posix_form(self, tmp_path: Path) -> None:
        _tree(tmp_path, {"a.md": "a", "docs/deep/b.md": "b"})
        assert _walked(tmp_path) == ["a.md", "docs/deep/b.md"]

    def test_files_in_one_directory_come_back_in_ascending_name_order(self, tmp_path: Path) -> None:
        """The order is observable: it fixes which files a partly-completed scan has committed.

        Asserted against the order itself rather than against a second walk — comparing a walk
        with itself cannot see an order that is stable and *wrong*, which is exactly what a walk
        that sorted the other way would be."""
        _tree(tmp_path, {"c.md": "x", "a.md": "x", "b.md": "x"})
        assert _walked(tmp_path) == ["a.md", "b.md", "c.md"]

    def test_the_order_is_the_same_on_every_walk_of_one_tree(self, tmp_path: Path) -> None:
        """And stable across runs, which is the half a single expected list cannot show."""
        _tree(tmp_path, {f"f{index}.md": "x" for index in range(20)} | {"z/y/x.md": "x"})
        assert _walked(tmp_path) == _walked(tmp_path)

    def test_a_dot_file_is_admitted(self, tmp_path: Path) -> None:
        """Only the dot *directory* rule prunes; an ordinary dot-file is corpus content."""
        _tree(tmp_path, {".editorconfig": "root = true"})
        assert _walked(tmp_path) == [".editorconfig"]

    def test_the_size_it_reports_is_the_file_on_disk(self, tmp_path: Path) -> None:
        _tree(tmp_path, {"a.md": "12345"})
        ((candidate,)) = list(walk.entries(tmp_path, ScanCounters()))
        assert candidate.size == 5
        assert candidate.absolute == tmp_path / "a.md"


class TestPruning:
    @pytest.mark.parametrize("name", sorted(walk.PRUNED_DIRECTORY_NAMES))
    def test_every_named_directory_is_never_descended(self, tmp_path: Path, name: str) -> None:
        _tree(tmp_path, {f"{name}/buried.md": "x", "kept.md": "y"})
        counters = ScanCounters()
        assert _walked(tmp_path, counters) == ["kept.md"]
        assert counters.pruned_directories == 1

    def test_any_dot_directory_is_pruned_even_when_unnamed(self, tmp_path: Path) -> None:
        _tree(tmp_path, {".cache/x.md": "x", "kept.md": "y"})
        counters = ScanCounters()
        assert _walked(tmp_path, counters) == ["kept.md"]
        assert counters.pruned_directories == 1

    def test_a_git_pointer_file_is_pruned_and_is_not_counted_as_a_directory(
        self, tmp_path: Path
    ) -> None:
        """A linked worktree's and a submodule's `.git` are files, and the prune rule matches the
        name in either shape. The count is of directories, so the file shape stays out of it."""
        _tree(tmp_path, {".git": "gitdir: /elsewhere/.git/worktrees/wt", "kept.md": "y"})
        counters = ScanCounters()
        assert _walked(tmp_path, counters) == ["kept.md"]
        assert counters.pruned_directories == 0
        assert counters.files_seen == 1

    def test_a_pruned_directory_is_neither_seen_nor_skipped(self, tmp_path: Path) -> None:
        """Pruning happens before candidacy, so the files inside were never evaluated — counting
        them as skipped would claim a knowledge the walk never had."""
        _tree(tmp_path, {"build/a.md": "x", "build/b.md": "y"})
        counters = ScanCounters()
        assert _walked(tmp_path, counters) == []
        assert (counters.files_seen, counters.files_skipped) == (0, 0)


class TestSymlinksAndOddEntries:
    def test_a_file_symlink_is_refused_and_counted(self, tmp_path: Path) -> None:
        _tree(tmp_path, {"real.md": "x"})
        (tmp_path / "link.md").symlink_to(tmp_path / "real.md")
        counters = ScanCounters()
        assert _walked(tmp_path, counters) == ["real.md"]
        assert counters.skipped == {SkipReason.SYMLINK: 1}
        assert counters.files_seen == 2

    def test_a_directory_symlink_is_refused_rather_than_descended(self, tmp_path: Path) -> None:
        """Counted as a symlink rather than as a pruned directory: not following it is exactly
        declining to find out what it points at."""
        _tree(tmp_path, {"real/inside.md": "x"})
        (tmp_path / "link").symlink_to(tmp_path / "real", target_is_directory=True)
        counters = ScanCounters()
        assert _walked(tmp_path, counters) == ["real/inside.md"]
        assert counters.skipped == {SkipReason.SYMLINK: 1}

    def test_a_symlink_cycle_cannot_hang_the_walk(self, tmp_path: Path) -> None:
        _tree(tmp_path, {"a/b.md": "x"})
        (tmp_path / "a" / "loop").symlink_to(tmp_path, target_is_directory=True)
        assert _walked(tmp_path) == ["a/b.md"]

    def test_a_dangling_symlink_is_a_symlink_rather_than_unreadable(self, tmp_path: Path) -> None:
        (tmp_path / "gone.md").symlink_to(tmp_path / "does-not-exist")
        counters = ScanCounters()
        assert _walked(tmp_path, counters) == []
        assert counters.skipped == {SkipReason.SYMLINK: 1}

    def test_a_pipe_is_refused_as_unreadable(self, tmp_path: Path) -> None:
        """Opening one would block the scan for as long as nothing writes to it, so it is refused
        by type rather than by trying."""
        os.mkfifo(tmp_path / "pipe")
        counters = ScanCounters()
        assert _walked(tmp_path, counters) == []
        assert counters.skipped == {SkipReason.UNREADABLE: 1}

    def test_a_directory_that_cannot_be_listed_is_one_refusal_rather_than_silence(
        self, tmp_path: Path
    ) -> None:
        """The walk cannot know how many files it did not see, so it records the one refusal it
        can — the alternative is a subtree vanishing with nothing to explain it."""
        _tree(tmp_path, {"closed/inside.md": "x", "open.md": "y"})
        (tmp_path / "closed").chmod(0o000)
        counters = ScanCounters()
        try:
            assert _walked(tmp_path, counters) == ["open.md"]
        finally:
            (tmp_path / "closed").chmod(0o700)
        assert counters.skipped == {SkipReason.UNREADABLE: 1}


class _UndeterminableEntry:
    """A directory entry whose type cannot be established, standing in for one that vanished.

    Between `scandir` listing a directory and the walk asking about each entry, a file can be
    deleted or a filesystem can go away — and each of the three questions the walk asks then
    raises rather than answering. Staged rather than raced, because a race is not reproducible and
    what matters is that every one of the three is refused under a reason a report can name.
    """

    def __init__(self, name: str, path: str) -> None:
        self.name = name
        self.path = path

    def is_symlink(self) -> bool:
        raise OSError("the entry went away")

    def is_dir(self, *, follow_symlinks: bool = True) -> bool:  # noqa: ARG002 — `DirEntry`'s own
        # signature: the walk passes this argument, so a stand-in that omitted it would be
        # answering a different call from the one the code makes.
        raise OSError("the entry went away")

    def is_file(self, *, follow_symlinks: bool = True) -> bool:  # noqa: ARG002
        raise OSError("the entry went away")

    def stat(self, *, follow_symlinks: bool = True) -> os.stat_result:  # noqa: ARG002
        raise OSError("the entry went away")


class TestAnEntryThatCannotBeClassified:
    def test_it_is_refused_as_unreadable_and_counted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unreadable is the more accurate of the two words for an entry whose type could not be
        determined, and counting it is what keeps it from vanishing without an explanation."""
        _tree(tmp_path, {"kept.md": "x"})

        class _Listing:
            def __enter__(self) -> list[object]:
                return [_UndeterminableEntry("gone.md", str(tmp_path / "gone.md"))]

            def __exit__(self, *_exception: object) -> None:
                return None

        monkeypatch.setattr(os, "scandir", lambda _path: _Listing())
        counters = ScanCounters()
        assert _walked(tmp_path, counters) == []
        assert counters.skipped == {SkipReason.UNREADABLE: 1}
        assert counters.files_seen == 1


class TestTheFilterLadder:
    def test_an_ignored_path_is_refused_first(self, tmp_path: Path) -> None:
        """Ignoring is the first rule, so a file that is both ignored and over the cap reports as
        ignored — and two implementations disagreeing about which would give two different
        accounts of one corpus."""
        _tree(tmp_path, {"big.md": "x" * 50})
        counters = ScanCounters()
        assert (
            _admitted(
                tmp_path,
                counters,
                rules=walk.WalkRules(max_file_bytes=10),
                ignored=frozenset({"big.md"}),
            )
            == []
        )
        assert counters.skipped == {SkipReason.GITIGNORED: 1}

    def test_an_exclude_glob_wins_over_the_size_cap(self, tmp_path: Path) -> None:
        _tree(tmp_path, {"big.md": "x" * 50})
        counters = ScanCounters()
        rules = walk.WalkRules(exclude_globs=("*.md",), max_file_bytes=10)
        assert _admitted(tmp_path, counters, rules=rules) == []
        assert counters.skipped == {SkipReason.EXCLUDED_BY_GLOB: 1}

    def test_the_size_cap_wins_over_the_deny_list(self, tmp_path: Path) -> None:
        _tree(tmp_path, {"big.png": "x" * 50})
        counters = ScanCounters()
        assert _admitted(tmp_path, counters, rules=walk.WalkRules(max_file_bytes=10)) == []
        assert counters.skipped == {SkipReason.OVER_SIZE_CAP: 1}

    def test_a_denied_extension_is_the_last_walk_time_refusal(self, tmp_path: Path) -> None:
        _tree(tmp_path, {"logo.png": "x"})
        counters = ScanCounters()
        assert _admitted(tmp_path, counters, rules=walk.WalkRules(max_file_bytes=_ROOMY)) == []
        assert counters.skipped == {SkipReason.DENIED_EXTENSION: 1}

    def test_a_file_exactly_at_the_cap_is_admitted(self, tmp_path: Path) -> None:
        """The cap is a maximum rather than a strict bound, so the boundary is stated by a test
        instead of being read off an inequality."""
        _tree(tmp_path, {"a.md": "12345"})
        counters = ScanCounters()
        assert _admitted(tmp_path, counters, rules=walk.WalkRules(max_file_bytes=5)) == ["a.md"]


class TestGlobs:
    @pytest.mark.parametrize(
        ("pattern", "admitted"),
        [
            ("*.md", ["notes.md", "docs/a.md", "docs/deep/c.md"]),
            ("docs/*", ["docs/a.md", "docs/deep/c.md"]),
            ("notes.md", ["notes.md"]),
            ("*/deep/*", ["docs/deep/c.md"]),
        ],
    )
    def test_include_globs_match_the_relative_path_with_star_crossing_separators(
        self, tmp_path: Path, pattern: str, admitted: list[str]
    ) -> None:
        """`*` crossing `/` is what makes `*.md` reach into subdirectories, and what makes
        `docs/*` mean the whole tree under `docs` rather than its direct children."""
        _tree(tmp_path, {"notes.md": "x", "docs/a.md": "y", "docs/deep/c.md": "z"})
        counters = ScanCounters()
        rules = walk.WalkRules(include_globs=(pattern,), max_file_bytes=_ROOMY)
        assert _admitted(tmp_path, counters, rules=rules) == admitted

    def test_a_doubled_star_is_two_stars_and_still_requires_the_separators_written(
        self, tmp_path: Path
    ) -> None:
        """The consequence of `*` crossing `/`, stated where it bites: `**` carries no meaning of
        its own, so `docs/**/*.md` asks for a file two directories down and gets exactly that.
        It fails *closed* — an empty corpus rather than a quietly wrong one — and `docs/*` is the
        pattern that means the whole tree."""
        _tree(tmp_path, {"docs/a.md": "y", "docs/deep/c.md": "z"})
        counters = ScanCounters()
        rules = walk.WalkRules(include_globs=("docs/**/*.md",), max_file_bytes=_ROOMY)
        assert _admitted(tmp_path, counters, rules=rules) == ["docs/deep/c.md"]

    def test_matching_is_case_sensitive(self, tmp_path: Path) -> None:
        """Byte-exact, like every other use of this path, so a pattern means one thing to the walk
        and to anyone reading the index back."""
        _tree(tmp_path, {"README.MD": "x"})
        counters = ScanCounters()
        rules = walk.WalkRules(include_globs=("*.md",), max_file_bytes=_ROOMY)
        assert _admitted(tmp_path, counters, rules=rules) == []

    def test_an_empty_include_list_admits_everything_the_excludes_leave(
        self, tmp_path: Path
    ) -> None:
        _tree(tmp_path, {"a.md": "x", "b.txt": "y"})
        counters = ScanCounters()
        rules = walk.WalkRules(exclude_globs=("*.txt",), max_file_bytes=_ROOMY)
        assert _admitted(tmp_path, counters, rules=rules) == ["a.md"]

    def test_an_exclude_beats_an_include_that_also_matches(self, tmp_path: Path) -> None:
        """Excludes are applied first, so the pair is a subtraction rather than a contest."""
        _tree(tmp_path, {"a.md": "x", "draft.md": "y"})
        counters = ScanCounters()
        rules = walk.WalkRules(
            include_globs=("*.md",), exclude_globs=("draft*",), max_file_bytes=_ROOMY
        )
        assert _admitted(tmp_path, counters, rules=rules) == ["a.md"]
