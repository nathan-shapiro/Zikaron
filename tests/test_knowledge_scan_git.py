"""Building an index over a real repository: the three git modes, and the shapes a tree can take.

Real repositories, because every claim here is about what git reports and what the walk does with
it. The shapes — a linked worktree, a file checked out sparsely, a submodule — are the ones that
break a design which takes its file set from git rather than from the filesystem, so each is built
and scanned rather than described.
"""

import subprocess
from pathlib import Path

import pytest

from tests.knowledge_fixtures import Corpus, add_request, build_index, open_corpus, open_index
from zikaron.core.knowledge import files, git, lifecycle
from zikaron.core.knowledge.counters import SkipReason
from zikaron.core.knowledge.database import read_meta
from zikaron.core.knowledge.meta import LAST_SCAN_GIT_MODE_EFFECTIVE_KEY, GitMode


def _git(root: Path, *arguments: str) -> None:
    subprocess.run(  # noqa: S603 — a fixed argv built from this file's own literals.
        ["git", *arguments],  # noqa: S607
        cwd=root,
        check=True,
        capture_output=True,
        timeout=30,
    )


def _write(root: Path, relative: str, content: str) -> Path:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    """A repository with one committed file, an identity, and nothing else."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "suite@example.invalid")
    _git(root, "config", "user.name", "Suite")
    _write(root, "tracked.md", "alpha\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "first")
    return root


async def _build(corpus: Corpus) -> lifecycle.Refreshed:
    return await build_index(corpus)


async def _indexed(corpus: Corpus) -> dict[str, files.IndexedFile]:
    async with open_index(corpus) as opened:
        return await files.load_all(opened.connection)


class TestTheThreeModes:
    async def test_tracked_indexes_only_what_git_tracks(
        self, tmp_path: Path, repository: Path
    ) -> None:
        """An untracked file is *seen* and outside the corpus without being *skipped*: no reason
        describes it, and what explains its absence is the mode itself."""
        _write(repository, "untracked.md", "beta\n")
        async with open_corpus(
            tmp_path, add_request(repository, git_mode=GitMode.TRACKED)
        ) as corpus:
            refreshed = await _build(corpus)
            rows = await _indexed(corpus)
        assert set(rows) == {"tracked.md"}
        assert refreshed.result.counters.files_seen == 2
        assert refreshed.result.counters.files_skipped == 0

    async def test_all_indexes_untracked_files_too_and_honours_gitignore(
        self, tmp_path: Path, repository: Path
    ) -> None:
        _write(repository, "untracked.md", "beta\n")
        _write(repository, ".gitignore", "*.log\n")
        _write(repository, "noisy.log", "gamma\n")
        async with open_corpus(tmp_path, add_request(repository, git_mode=GitMode.ALL)) as corpus:
            refreshed = await _build(corpus)
            rows = await _indexed(corpus)
        assert set(rows) == {"tracked.md", "untracked.md", ".gitignore"}
        assert refreshed.result.counters.skipped == {SkipReason.GITIGNORED: 1}

    async def test_a_tracked_but_ignored_file_stays_in_the_corpus(
        self, tmp_path: Path, repository: Path
    ) -> None:
        """Git's own rule: ignore patterns never affect tracked files. Diverging from it would be
        more surprising than following it, and it holds because the index is consulted."""
        _write(repository, ".gitignore", "*.log\n")
        _write(repository, "kept.log", "delta\n")
        _git(repository, "add", "-f", "kept.log", ".gitignore")
        _git(repository, "commit", "-qm", "second")
        async with open_corpus(tmp_path, add_request(repository, git_mode=GitMode.ALL)) as corpus:
            await _build(corpus)
            rows = await _indexed(corpus)
        assert "kept.log" in rows

    async def test_off_indexes_everything_the_walk_admits(
        self, tmp_path: Path, repository: Path
    ) -> None:
        _write(repository, "untracked.md", "beta\n")
        _write(repository, ".gitignore", "*.md\n")
        async with open_corpus(tmp_path, add_request(repository, git_mode=GitMode.OFF)) as corpus:
            await _build(corpus)
            rows = await _indexed(corpus)
        assert set(rows) == {"tracked.md", "untracked.md", ".gitignore"}

    async def test_the_fast_path_and_no_git_at_all_agree_on_a_clean_tree(
        self, tmp_path: Path, repository: Path
    ) -> None:
        """The whole point of consulting git is to avoid reading files, so the two must produce
        the same corpus — one of them having been read and the other cleared by a subprocess."""
        _write(repository, "docs/b.md", "beta\n")
        _git(repository, "add", "-A")
        _git(repository, "commit", "-qm", "second")
        async with open_corpus(
            tmp_path, add_request(repository, name="fast", git_mode=GitMode.TRACKED)
        ) as fast:
            await _build(fast)
            # A second build, so the first one's rows exist for the fast path to clear.
            await _build(fast)
            with_git = await _indexed(fast)
            await lifecycle.add(
                fast.store_dir,
                fast.db,
                fast.config,
                add_request(
                    repository,
                    name="plain",
                    git_mode=GitMode.OFF,
                    home=fast.store_dir.parent / "not-the-home-directory",
                ),
            )
            plain_corpus = Corpus(
                store_dir=fast.store_dir,
                db=fast.db,
                config=fast.config,
                name="plain",
                root=repository,
            )
            await _build(plain_corpus)
            without_git = await _indexed(plain_corpus)
        assert {path: row.content_hash for path, row in with_git.items()} == {
            path: row.content_hash for path, row in without_git.items()
        }


class TestACorpusRootedBelowItsRepository:
    """A corpus root inside a work tree rather than at its top — a vendored dependency, or a
    documentation tree, both of which §8.6 endorses by name.

    The two git calls that decide change detection disagree about what their paths are relative to,
    and only one of them agrees with the walk. Measured, from `repo/docs`: `ls-files -s -z` reports
    `guide.md`, `status --porcelain -z` reports `docs/guide.md`, and `rev-parse --show-prefix`
    reports `docs/`. Porcelain output is repository-relative whatever the working directory, so the
    status guard silently matches nothing unless the prefix is reconciled.
    """

    async def test_an_uncommitted_edit_is_noticed(self, tmp_path: Path, repository: Path) -> None:
        """The failure this pins is the one the design calls unacceptable: `ls-files` still lists
        the committed blob, so a status report that fails to join clears the file as unchanged —
        for every scan, until someone commits it. Nothing raises and nothing is counted."""
        _write(repository, "docs/guide.md", "alpha\n")
        _git(repository, "add", "-A")
        _git(repository, "commit", "-qm", "second")
        async with open_corpus(
            tmp_path, add_request(repository / "docs", git_mode=GitMode.TRACKED)
        ) as corpus:
            await _build(corpus)
            before = (await _indexed(corpus))["guide.md"]
            _write(repository, "docs/guide.md", "changed\n")
            await _build(corpus)
            after = (await _indexed(corpus))["guide.md"]
        assert after.content_hash != before.content_hash

    async def test_a_change_outside_the_corpus_is_not_mistaken_for_one_inside_it(
        self, tmp_path: Path, repository: Path
    ) -> None:
        """Stripping the prefix must also discard what is above it: a sibling's path, once
        shortened, could otherwise collide with a corpus path of the same name."""
        _write(repository, "docs/guide.md", "alpha\n")
        _write(repository, "guide.md", "a sibling with the same name\n")
        _git(repository, "add", "-A")
        _git(repository, "commit", "-qm", "second")
        async with open_corpus(
            tmp_path, add_request(repository / "docs", git_mode=GitMode.TRACKED)
        ) as corpus:
            await _build(corpus)
            first = (await _indexed(corpus))["guide.md"]
            _write(repository, "guide.md", "the sibling changed, not the corpus\n")
            await _build(corpus)
            rows = await _indexed(corpus)
        assert set(rows) == {"guide.md"}
        assert rows["guide.md"] == first


class TestTheFastPathStaysUsable:
    async def test_committing_a_file_after_it_was_indexed_gives_it_a_blob_hash(
        self, tmp_path: Path, repository: Path
    ) -> None:
        """Without writing the new hash the file is read and hashed on every scan for the rest of
        its life — which is every new file's ordinary lifecycle in a corpus that indexes untracked
        files too. Its own content is unchanged, so nothing else about the row moves."""
        _write(repository, "untracked.md", "beta\n")
        async with open_corpus(tmp_path, add_request(repository, git_mode=GitMode.ALL)) as corpus:
            await _build(corpus)
            before = (await _indexed(corpus))["untracked.md"]
            assert before.git_blob_hash is None

            _git(repository, "add", "-A")
            _git(repository, "commit", "-qm", "second")
            await _build(corpus)
            after = (await _indexed(corpus))["untracked.md"]
        assert after.git_blob_hash is not None
        assert after.content_hash == before.content_hash
        assert after.indexed_at == before.indexed_at


class TestEveryRefusalIsReachableInOneBuild:
    async def test_all_eight_reasons_fire_against_one_repository(
        self, tmp_path: Path, repository: Path
    ) -> None:
        """A file silently missing from an index is indistinguishable from a file with nothing
        relevant in it; one is a legitimate answer and the other is a defect. Asserting the whole
        set rather than the reasons this fixture happens to trigger is what makes a reason nobody
        can produce fail here rather than sit in the schema unreachable."""
        _write(repository, ".gitignore", "*.log\n")
        _write(repository, ".gitattributes", "*.dat -text\n")
        _write(repository, "noisy.log", "ignored\n")
        _write(repository, "logo.png", "denied by name\n")
        _write(repository, "huge.md", "x" * 64)
        _write(repository, "draft.md", "excluded by glob\n")
        _write(repository, "marked.dat", "called binary by the repository\n")
        (repository / "bad.md").write_bytes(b"\xff\xfe")
        (repository / "raw.bin").write_bytes(b"\x00\x01\x02")
        (repository / "unreadable.md").write_text("locked\n", encoding="utf-8")
        (repository / "link.md").symlink_to(repository / "tracked.md")
        _git(repository, "add", "-A")
        _git(repository, "commit", "-qm", "second")
        # Made unreadable only after the commit: git cannot add a file it may not read either.
        (repository / "unreadable.md").chmod(0o000)
        try:
            async with open_corpus(
                tmp_path,
                add_request(
                    repository,
                    git_mode=GitMode.ALL,
                    exclude_globs=("draft*",),
                    max_file_bytes=32,
                ),
            ) as corpus:
                refreshed = await _build(corpus)
        finally:
            (repository / "unreadable.md").chmod(0o600)
        assert set(refreshed.result.counters.skipped) == set(SkipReason)


class TestDegrading:
    async def test_a_root_outside_a_repository_builds_as_though_git_were_off(
        self, tmp_path: Path
    ) -> None:
        """The default mode is `tracked` while indexing a documentation tree outside any
        repository is an endorsed use, so this case is ordinary rather than exotic."""
        root = tmp_path / "docs"
        root.mkdir()
        _write(root, "a.md", "alpha\n")
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.TRACKED)) as corpus:
            refreshed = await _build(corpus)
            rows = await _indexed(corpus)
            async with open_index(corpus) as opened:
                raw = await read_meta(opened.connection)
        assert set(rows) == {"a.md"}
        assert refreshed.result.git_mode_effective is GitMode.OFF
        assert raw[LAST_SCAN_GIT_MODE_EFFECTIVE_KEY] == GitMode.OFF.value

    async def test_a_listing_that_does_not_answer_degrades_the_whole_scan(
        self, tmp_path: Path, repository: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A candidate set intersected with a subprocess that did not answer is an empty corpus
        wearing the shape of an answer, so every git-derived rule is dropped together."""
        _write(repository, "untracked.md", "beta\n")

        async def _refuse(*_args: object, **_kwargs: object) -> None:
            raise git.GitUnavailableError("dubious ownership")

        async with open_corpus(
            tmp_path, add_request(repository, git_mode=GitMode.TRACKED)
        ) as corpus:
            monkeypatch.setattr(git, "list_files", _refuse)
            refreshed = await _build(corpus)
            rows = await _indexed(corpus)
            async with open_index(corpus) as opened:
                raw = await read_meta(opened.connection)
        assert refreshed.result.git_mode_effective is GitMode.OFF
        assert set(rows) == {"tracked.md", "untracked.md"}
        # The degradation was discovered *after* the work-tree probe had already recorded
        # `tracked` at the scan's start, so only the walk phase's closing rewrite can leave this.
        assert raw[LAST_SCAN_GIT_MODE_EFFECTIVE_KEY] == GitMode.OFF.value

    async def test_a_degraded_scan_does_not_erase_the_hashes_it_could_not_check(
        self, tmp_path: Path, repository: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """*Git says this file is untracked* and *git was never asked* both look like an absent
        listing entry, and only the first is an observation. Nulling a stored hash on the second
        would charge the next healthy scan a full read of every file in the corpus."""

        async def _refuse(*_args: object, **_kwargs: object) -> None:
            raise git.GitUnavailableError("dubious ownership")

        async with open_corpus(
            tmp_path, add_request(repository, git_mode=GitMode.TRACKED)
        ) as corpus:
            await _build(corpus)
            before = (await _indexed(corpus))["tracked.md"]
            assert before.git_blob_hash is not None

            monkeypatch.setattr(git, "list_files", _refuse)
            degraded = await _build(corpus)
            after = (await _indexed(corpus))["tracked.md"]
        assert degraded.result.git_mode_effective is GitMode.OFF
        assert after.git_blob_hash == before.git_blob_hash

    async def test_attributes_that_cannot_be_read_leave_the_candidate_set_alone(
        self, tmp_path: Path, repository: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unlike the calls that decide candidacy: this one runs after the set is settled and can
        only remove from it, so flipping the mode now would retroactively invalidate a set already
        computed under another one."""

        async def _refuse(*_args: object, **_kwargs: object) -> None:
            raise git.GitUnavailableError("attributes unavailable")

        monkeypatch.setattr(git, "attributes", _refuse)
        async with open_corpus(
            tmp_path, add_request(repository, git_mode=GitMode.TRACKED)
        ) as corpus:
            refreshed = await _build(corpus)
            rows = await _indexed(corpus)
        assert refreshed.result.git_mode_effective is GitMode.TRACKED
        assert not refreshed.result.attributes_available
        assert set(rows) == {"tracked.md"}


class TestGitAttributes:
    async def test_a_file_the_repository_calls_binary_is_excluded(
        self, tmp_path: Path, repository: Path
    ) -> None:
        _write(repository, ".gitattributes", "*.md -text\n")
        _git(repository, "add", "-A")
        _git(repository, "commit", "-qm", "second")
        async with open_corpus(
            tmp_path, add_request(repository, git_mode=GitMode.TRACKED)
        ) as corpus:
            refreshed = await _build(corpus)
            rows = await _indexed(corpus)
        assert "tracked.md" not in rows
        assert refreshed.result.counters.skipped[SkipReason.BINARY] == 1

    async def test_marking_an_unchanged_file_binary_removes_it_from_the_index(
        self, tmp_path: Path, repository: Path
    ) -> None:
        """The non-obvious half: the file's own blob hash is untouched, so git clears it as
        unchanged — and a batch run only over the files being read would never discover it."""
        async with open_corpus(
            tmp_path, add_request(repository, git_mode=GitMode.TRACKED)
        ) as corpus:
            await _build(corpus)
            assert "tracked.md" in await _indexed(corpus)
            _write(repository, ".gitattributes", "*.md binary\n")
            refreshed = await _build(corpus)
            rows = await _indexed(corpus)
        assert rows == {}
        assert refreshed.result.files_deleted == 1

    async def test_the_line_a_repository_is_most_likely_to_carry_excludes_nothing(
        self, tmp_path: Path, repository: Path
    ) -> None:
        """`* text=auto` is what GitHub's own guidance recommends as a repository's first line,
        and the predicate an implementer infers from "exclude unless text is set" empties the
        corpus for every repository that follows it."""
        _write(repository, ".gitattributes", "* text=auto\n")
        async with open_corpus(
            tmp_path, add_request(repository, git_mode=GitMode.TRACKED)
        ) as corpus:
            await _build(corpus)
            rows = await _indexed(corpus)
        assert "tracked.md" in rows


class TestRepositoryShapes:
    async def test_a_linked_worktrees_git_pointer_file_is_never_indexed(
        self, tmp_path: Path, repository: Path
    ) -> None:
        """Its `.git` is a *file* holding a pointer, and directory pruning never sees it."""
        worktree = tmp_path / "linked"
        _git(repository, "worktree", "add", "-q", str(worktree))
        assert (worktree / ".git").is_file()
        async with open_corpus(tmp_path, add_request(worktree, git_mode=GitMode.TRACKED)) as corpus:
            await _build(corpus)
            rows = await _indexed(corpus)
        assert set(rows) == {"tracked.md"}

    async def test_a_file_absent_from_a_sparse_checkout_is_treated_as_deleted(
        self, tmp_path: Path, repository: Path
    ) -> None:
        """Git lists a hash for it and reports nothing about it as changed, so the inverted rule
        would conclude *unchanged* for a file that is not there — and keep serving chunks the
        agent cannot open. Under a walk-first design it is simply never found."""
        async with open_corpus(
            tmp_path, add_request(repository, git_mode=GitMode.TRACKED)
        ) as corpus:
            await _build(corpus)
            assert set(await _indexed(corpus)) == {"tracked.md"}
            _git(repository, "update-index", "--skip-worktree", "tracked.md")
            (repository / "tracked.md").unlink()
            refreshed = await _build(corpus)
            rows = await _indexed(corpus)
        assert rows == {}
        assert refreshed.result.files_deleted == 1

    async def test_under_tracked_a_submodules_files_are_outside_the_corpus(
        self, tmp_path: Path, repository: Path
    ) -> None:
        """The superproject lists only the gitlink, never the files inside it — and that gitlink's
        hash is a commit, not content."""
        inner = tmp_path / "inner"
        inner.mkdir()
        _git(inner, "init", "-q")
        _git(inner, "config", "user.email", "suite@example.invalid")
        _git(inner, "config", "user.name", "Suite")
        _write(inner, "inside.md", "gamma\n")
        _git(inner, "add", "-A")
        _git(inner, "commit", "-qm", "inner")
        _git(
            repository,
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "add",
            "-q",
            str(inner),
            "sub",
        )
        async with open_corpus(
            tmp_path, add_request(repository, git_mode=GitMode.TRACKED)
        ) as corpus:
            await _build(corpus)
            rows = await _indexed(corpus)
        assert "sub/inside.md" not in rows
        assert "tracked.md" in rows

    async def test_under_off_a_submodules_files_are_walked_like_any_others(
        self, tmp_path: Path, repository: Path
    ) -> None:
        inner = tmp_path / "inner"
        inner.mkdir()
        _git(inner, "init", "-q")
        _git(inner, "config", "user.email", "suite@example.invalid")
        _git(inner, "config", "user.name", "Suite")
        _write(inner, "inside.md", "gamma\n")
        _git(inner, "add", "-A")
        _git(inner, "commit", "-qm", "inner")
        _git(
            repository,
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "add",
            "-q",
            str(inner),
            "sub",
        )
        async with open_corpus(tmp_path, add_request(repository, git_mode=GitMode.OFF)) as corpus:
            await _build(corpus)
            rows = await _indexed(corpus)
        assert "sub/inside.md" in rows
