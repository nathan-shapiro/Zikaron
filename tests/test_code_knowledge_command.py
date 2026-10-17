"""`zikaron code-knowledge plan` against a real repository: the walk, git, the hash and the disk.

`design/code-knowledge.md` §3 is normative. The decisions themselves are covered without a
repository in `test_code_knowledge_plan.py`; what is checked here is what only a real run shows —
which files the walk and git admit, that the hash is git's and agrees with a search's, what
`--apply` changes on disk and what a dry run leaves alone, and that nothing reaches the service.

Each test isolates git from the machine's own configuration, so a `core.autocrlf` on the machine
running the suite cannot change an answer.
"""

import asyncio
import io
import json
import os
import runpy
import stat
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest

from tests.fake_encoder import FakeEncoder
from tests.knowledge_fixtures import add_base, add_request, build_settings, config_for, open_store
from zikaron.code_knowledge import apply as apply_module
from zikaron.code_knowledge import main as command
from zikaron.code_knowledge import survey
from zikaron.core.code_knowledge.document import SECTION_HEADINGS, title
from zikaron.core.code_knowledge.layout import Layout
from zikaron.core.code_knowledge.plan import Move, Plan
from zikaron.core.knowledge import git, groups, lifecycle, meta, source_hash, walk
from zikaron.core.knowledge.source_hash import HashBudget, Hashed, Source

_SHA1_WIDTH: Final = 40


@pytest.fixture(autouse=True)
def _isolated_git(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))


def _git(cwd: Path, *arguments: str) -> str:
    return subprocess.run(  # noqa: S603 — a fixed argv built from this file's own literals.
        ["git", *arguments],  # noqa: S607
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.strip()


def _write(path: Path, content: str | bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        path.write_text(content, encoding="utf-8")
    else:
        path.write_bytes(content)
    return path


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A repository with a store, and a module `src` holding two sources."""
    root = tmp_path / "project"
    root.mkdir()
    _git(root, "init", "-q")
    _write(root / ".zikaron" / "memory.db", b"")
    _write(root / "src" / "a.scala", "object A\n")
    _write(root / "src" / "b.scala", "object B\n")
    return root


def _run(
    project: Path, capsys: pytest.CaptureFixture[str], *arguments: str, module: str = "src"
) -> dict[str, object]:
    status = command.main(["plan", "--project", str(project), "--module", module, *arguments])
    captured = capsys.readouterr()
    assert status == 0, captured.err
    report = json.loads(captured.out)
    assert isinstance(report, dict)
    return report


def _refused(project: Path, capsys: pytest.CaptureFixture[str], *arguments: str) -> str:
    status = command.main(["plan", "--project", str(project), *arguments])
    captured = capsys.readouterr()
    assert status == 1
    assert captured.out == ""
    return captured.err


def _items(report: dict[str, object]) -> list[dict[str, str]]:
    items = report["work"]
    assert isinstance(items, list)
    return items


def _sources(report: dict[str, object]) -> list[str]:
    return [item["source"] for item in _items(report)]


def _role_list(project: Path) -> tuple[Path, Path]:
    """The role list's path and the directory its removal stops at, as the command passes them."""
    base = project / ".zikaron" / "code-knowledge"
    return base / "src" / "roles.md", base


def _written(project: Path, item: dict[str, str], *, role: str = "What it is for.") -> Path:
    """The document a documenter would write for one work item, as §4 lays it out."""
    sections = "".join(f"## {name}\nSomething.\n\n" for name in SECTION_HEADINGS)
    body = f"{item['front_matter']}{title(item['source'])}\n\n{role}\n\n{sections}"
    return _write(project / item["document"], body)


def _document_everything(project: Path, capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    """Write every listed document and the README, until the planner reports `up_to_date`."""
    for _ in range(5):
        report = _run(project, capsys, "--apply")
        for item in _items(report):
            _written(project, item)
        listed = report["readme"]
        if isinstance(listed, dict):
            _write(
                project / listed["document"],
                f"{listed['front_matter']}# `src`\n\nOverview.\n\n"
                "## How its parts relate\n\nText.\n",
            )
        if report["up_to_date"]:
            return report
    raise AssertionError("never up to date")


def _snapshot(root: Path) -> dict[str, bytes | None]:
    """Every path under `root` but `.git`, with a file's bytes or `None` for a directory."""
    found: dict[str, bytes | None] = {}
    for directory, names, files in os.walk(root):
        names[:] = sorted(name for name in names if name != ".git")
        for name in names:
            found[os.path.relpath(Path(directory) / name, root)] = None
        for name in files:
            path = Path(directory) / name
            found[os.path.relpath(path, root)] = path.read_bytes()
    return found


class TestTheSources:
    def test_a_gitignored_file_is_counted_not_listed(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(project / ".gitignore", "*.log\n")
        _write(project / "src" / "debug.log", "noise\n")
        report = _run(project, capsys)
        assert report["git_mode_effective"] == "all"
        assert _sources(report) == ["src/a.scala", "src/b.scala"]
        assert report["skipped"] == {"gitignored": 1}

    def test_an_uncommitted_source_is_documented(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _git(project, "add", "src/a.scala")
        _git(project, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "a")
        assert _sources(_run(project, capsys)) == ["src/a.scala", "src/b.scala"]

    def test_globs_match_the_path_relative_to_the_module(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(project / "src" / "deep" / "c.py", "c = 1\n")
        report = _run(project, capsys, "--include", "*.scala", "--exclude", "b*")
        assert _sources(report) == ["src/a.scala"]
        assert report["skipped"] == {"excluded_by_glob": 2}

    def test_a_file_marked_binary_by_gitattributes_is_counted(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(project / ".gitattributes", "*.bin binary\n")
        _write(project / "src" / "blob.bin", b"\x00\x01")
        report = _run(project, capsys)
        assert "src/blob.bin" not in _sources(report)
        assert report["skipped"] == {"binary": 1}

    def test_a_file_over_the_configured_cap_is_counted(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(
            project / ".zikaron" / "config.toml", "[indexing]\nknowledge_max_file_bytes = 1024\n"
        )
        _write(project / "src" / "large.scala", "x" * 2048)
        report = _run(project, capsys)
        assert "src/large.scala" not in _sources(report)
        assert report["skipped"] == {"over_size_cap": 1}

    def test_each_refusal_of_the_walk_is_counted_under_its_reason(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(project / "src" / "logo.png", b"\x89PNG")
        _write(project / "src" / "build" / "out.scala", "object Out\n")
        (project / "src" / "link.scala").symlink_to(project / "src" / "a.scala")
        locked = _write(project / "src" / "locked.scala", "object L\n")
        locked_dir = project / "src" / "sealed"
        _write(locked_dir / "x.scala", "object X\n")
        locked_dir.chmod(0)
        try:
            report = _run(project, capsys)
        finally:
            locked_dir.chmod(0o755)
        assert locked.exists()
        assert _sources(report) == ["src/a.scala", "src/b.scala", "src/locked.scala"]
        assert report["skipped"] == {
            "denied_extension": 1,
            "symlink": 1,
            "unreadable": 1,
            "pruned_directories": 1,
        }

    def test_the_documents_directory_is_never_a_source(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        report = _run(project, capsys, "--apply", module=".")
        for item in _items(report):
            _written(project, item)
        _write(project / "code-knowledge" / "notes.txt", "by hand\n")
        listed = _sources(_run(project, capsys, module="."))
        assert not [source for source in listed if source.startswith("code-knowledge")]

    def test_the_root_itself_can_be_the_module(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        report = _run(project, capsys, module=".")
        assert _sources(report) == ["src/a.scala", "src/b.scala"]
        assert _items(report)[0]["document"] == "code-knowledge/src/a.scala.md"


class TestWithoutGit:
    def test_outside_a_work_tree_git_is_off_ignore_rules_unapplied_and_the_width_sha1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = tmp_path / "plain"
        _write(root / ".zikaron" / "memory.db", b"")
        _write(root / ".gitignore", "*.log\n")
        _write(root / "src" / "a.log", "noise\n")
        report = _run(root, capsys)
        assert report["git_mode_effective"] == "off"
        (item,) = _items(report)
        assert item["source"] == "src/a.log"
        assert len(item["front_matter"].split("zikaron-source-blob: ")[1].split("\n")[0]) == 40

    def test_with_git_unstartable_git_is_off_and_the_hash_is_the_raw_blob(
        self, project: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write(project / ".gitignore", "*.log\n")
        _write(project / "src" / "debug.log", "noise\n")
        monkeypatch.setenv("PATH", str(project / "no-git-here"))
        report = _run(project, capsys)
        assert report["git_mode_effective"] == "off"
        assert "src/debug.log" in _sources(report)
        (item,) = [item for item in _items(report) if item["source"] == "src/a.scala"]
        raw = source_hash._blob_hash(str(project / "src" / "a.scala"), _SHA1_WIDTH)
        assert item["front_matter"].endswith(f"zikaron-source-blob: {raw}\n---\n")

    def test_a_check_ignore_that_does_not_answer_degrades_to_off(
        self, project: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write(project / ".gitignore", "*.log\n")
        _write(project / "src" / "debug.log", "noise\n")

        async def _refuses(_root: Path, _paths: object) -> frozenset[str]:
            raise git.GitUnavailableError("refused")

        monkeypatch.setattr(git, "ignored_paths", _refuses)
        report = _run(project, capsys)
        assert report["git_mode_effective"] == "off"
        assert "src/debug.log" in _sources(report)

    def test_git_is_never_asked_to_list_or_diff_the_repository(
        self, project: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A scan's change detection, which the planner does not need: `git status` grows with
        the whole repository rather than the module."""

        async def _never(_root: Path) -> object:
            raise AssertionError("asked")

        monkeypatch.setattr(git, "list_files", _never)
        monkeypatch.setattr(git, "changed_paths", _never)
        assert _run(project, capsys)["git_mode_effective"] == "all"


class TestTheHash:
    def test_the_planners_block_reads_fresh_through_a_real_search(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The planner and search agree on a hash, filters included: a CRLF source under a `text`
        attribute hashes differently through git than as its raw bytes."""
        _write(project / ".gitattributes", "*.scala text eol=lf\n")
        _write(project / "src" / "a.scala", b"object A\r\n")
        report = _run(project, capsys, "--apply")
        for item in _items(report):
            _written(project, item, role="Declares the quoting object.")
        assert _items(_run(project, capsys)) == []

        async def _search() -> dict[str, object]:
            async with open_store(project) as (store_dir, db):
                config = config_for(project)
                request = add_request(
                    project / "code-knowledge",
                    name="code-knowledge",
                    include_globs=("*.md",),
                    git_mode=meta.GitMode.OFF,
                )
                await add_base(store_dir, db, config, request)
                await lifecycle.refresh(
                    store_dir,
                    db,
                    config,
                    name="code-knowledge",
                    build=build_settings(config),
                    migrate=True,
                )
                response = await groups.search_all(
                    store_dir,
                    db,
                    config,
                    groups.SearchRequest(text="quoting object", limit_per_kb=20, names=None),
                    encoder=FakeEncoder(),
                    migrate=True,
                )
            (group,) = response.groups
            assert isinstance(group, groups.Group)
            results = group.payload()["results"]
            assert isinstance(results, list)
            return {result["path"]: result["source"] for result in results}

        # The fixture's empty `memory.db` stands in for a store; this test creates a real one.
        (project / ".zikaron" / "memory.db").unlink()
        found = asyncio.run(_search())
        assert found["src/a.scala.md"] == {"path": "src/a.scala", "state": "fresh"}

    def test_sources_past_one_batch_are_hashed_through_git_in_several_calls(
        self, project: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A CRLF source under a `text` attribute hashes to git's normalized id only through git,
        so every source answering git's id is one the in-process form never touched."""
        _write(project / ".gitattributes", "* text eol=lf\n")
        deep = project / "src" / ("d" * 200)
        names = [f"{index:04d}{'n' * 60}.txt" for index in range(450)]
        for name in names:
            _write(deep / name, b"line\r\n")
        calls: list[list[str]] = []
        real = source_hash.hash_sources

        async def _counting(
            root: Path, sources: list[Source], *, budget: HashBudget
        ) -> dict[Source, Hashed]:
            calls.append([source.path for source in sources])
            return await real(root, sources, budget=budget)

        monkeypatch.setattr(survey, "hash_sources", _counting)
        report = _run(project, capsys, "--limit", "1000")
        assert len(calls) > 1
        for batch in calls:
            assert sum(len(os.fsencode(project / path)) + 1 for path in batch) <= (
                survey.HASH_BATCH_PATH_BYTES
            )
        expected = _git(project, "hash-object", "--", str(deep / names[0]))
        assert expected != source_hash._blob_hash(str(deep / names[0]), _SHA1_WIDTH)
        crlf = [item for item in _items(report) if item["source"].endswith(".txt")]
        assert len(crlf) == len(names)
        assert {item["front_matter"].split("blob: ")[1][:40] for item in crlf} == {expected}

    def test_a_source_deleted_after_the_walk_is_unverifiable_not_work(
        self, project: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real = survey.hashes

        async def _after_a_deletion(root: Path, sources: list[str]) -> dict[str, Hashed]:
            (root / "src" / "b.scala").unlink()
            return await real(root, sources)

        monkeypatch.setattr(command, "hashes", _after_a_deletion)
        report = _run(project, capsys)
        assert _sources(report) == ["src/a.scala"]
        assert report["unverifiable"] == [{"source": "src/b.scala", "state": "missing"}]
        assert report["up_to_date"] is False


class TestWhatADryRunLeavesAlone:
    def test_the_tree_is_byte_identical_after_a_dry_run(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _document_everything(project, capsys)
        _write(project / "src" / "a.scala", "object A { def edited = 1 }\n")
        (project / "src" / "b.scala").rename(project / "src" / "c.scala")
        _write(
            project / "code-knowledge" / "src" / "gone.scala.md", "---\nzikaron-source: x\n---\n"
        )
        _write(project / "code-knowledge" / "src" / "notes.md", "by hand\n")
        before = _snapshot(project)
        report = _run(project, capsys, "--limit", "10")
        assert report["would_remove"] != []
        assert report["would_move"] != []
        assert _snapshot(project) == before

    def test_a_dry_run_creates_no_document_directory(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _run(project, capsys)
        assert not (project / "code-knowledge").exists()

    def test_a_slices_check_leaves_a_stale_document_past_the_slice_in_place(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _document_everything(project, capsys)
        _write(project / "src" / "a.scala", "object A { def one = 1 }\n")
        _write(project / "src" / "b.scala", "object B { def two = 2 }\n")
        report = _run(project, capsys, "--limit", "1")
        assert _sources(report) == ["src/a.scala"]
        assert (project / "code-knowledge" / "src" / "a.scala.md").exists()
        assert (project / "code-knowledge" / "src" / "b.scala.md").exists()


class TestWhatApplyChanges:
    def test_a_listed_documents_directory_exists_before_it_is_printed(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(project / "src" / "deep" / "er" / "c.scala", "object C\n")
        report = _run(project, capsys, "--apply")
        for item in _items(report):
            assert (project / item["document"]).parent.is_dir()
            assert not (project / item["document"]).exists()

    def test_a_listed_stale_document_is_gone_and_the_limit_bounds_which(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _document_everything(project, capsys)
        _write(project / "src" / "a.scala", "object A { def one = 1 }\n")
        _write(project / "src" / "b.scala", "object B { def two = 2 }\n")
        report = _run(project, capsys, "--apply", "--limit", "1")
        assert _items(report)[0]["kind"] == "stale"
        assert report["removed"] == ["code-knowledge/src/a.scala.md"]
        assert not (project / "code-knowledge" / "src" / "a.scala.md").exists()
        assert (project / "code-knowledge" / "src" / "b.scala.md").exists()

    def test_orphans_are_removed_whatever_the_limit(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _document_everything(project, capsys)
        (project / "src" / "a.scala").unlink()
        (project / "src" / "b.scala").unlink()
        report = _run(project, capsys, "--apply", "--limit", "0")
        assert report["removed"] == [
            "code-knowledge/src/README.md",
            "code-knowledge/src/a.scala.md",
            "code-knowledge/src/b.scala.md",
        ]

    def test_a_foreign_file_survives_every_run_even_when_the_globs_admit_nothing(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        notes = _write(project / "code-knowledge" / "src" / "notes.md", "by hand\n")
        hand = _write(project / "code-knowledge" / "src" / "a.scala.md", "my own a\n")
        for arguments in ([], ["--include", "nothing-matches"]):
            report = _run(project, capsys, "--apply", *arguments)
            assert notes.read_text(encoding="utf-8") == "by hand\n"
            assert hand.read_text(encoding="utf-8") == "my own a\n"
        assert report["foreign"] == [
            {"document": "code-knowledge/src/a.scala.md", "source": None},
            {"document": "code-knowledge/src/notes.md", "source": None},
        ]

    def test_an_undecodable_or_symlinked_document_is_foreign_and_survives(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        latin = _write(project / "code-knowledge" / "src" / "a.scala.md", b"---\n\xe9\n")
        target = _write(project / "elsewhere.md", "---\nzikaron-source: src/b.scala\n---\n")
        (project / "code-knowledge" / "src" / "b.scala.md").symlink_to(target)
        report = _run(project, capsys, "--apply")
        assert _items(report) == []
        assert latin.exists()
        assert (project / "code-knowledge" / "src" / "b.scala.md").is_symlink()

    def test_an_invalid_document_is_removed_and_listed_with_its_reason(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        report = _run(project, capsys, "--apply")
        cut_off = _written(project, _items(report)[0])
        cut_off.write_text(cut_off.read_text(encoding="utf-8").split("## Dependencies")[0])
        report = _run(project, capsys, "--apply")
        assert _items(report)[0]["kind"] == "invalid"
        assert _items(report)[0]["reason"] == "missing_heading"
        assert not cut_off.exists()

    def test_files_that_are_not_markdown_and_unreadable_directories_are_left_alone(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        other = _write(project / "code-knowledge" / "src" / "diagram.svg", "<svg/>")
        hidden = _write(project / "code-knowledge" / "src" / ".drafts" / "a.scala.md", "draft\n")
        locked = project / "code-knowledge" / "src" / "locked"
        _write(locked / "x.md", "---\nzikaron-source: src/locked/x\n---\n")
        locked.chmod(0)
        try:
            report = _run(project, capsys, "--apply")
        finally:
            locked.chmod(0o755)
        assert other.exists()
        assert hidden.exists()
        assert (locked / "x.md").exists()
        assert report["foreign"] == []

    def test_a_hand_written_readme_is_replaced(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        report = _run(project, capsys, "--apply")
        for item in _items(report):
            _written(project, item)
        readme = _write(project / "code-knowledge" / "src" / "README.md", "# mine\n")
        report = _run(project, capsys, "--apply")
        assert report["removed"] == ["code-knowledge/src/README.md"]
        assert not readme.exists()
        listed = report["readme"]
        assert isinstance(listed, dict)
        assert sorted(listed) == ["document", "documents", "front_matter", "roles"]
        assert listed["roles"] == ".zikaron/code-knowledge/src/roles.md"
        _run(
            project, capsys, "--apply"
        )  # a retry, the README still unwritten: the list is rewritten
        roles = (project / listed["roles"]).read_text(encoding="utf-8")
        assert roles == "- `src/a.scala` — What it is for.\n- `src/b.scala` — What it is for.\n"


class TestTheRoleList:
    """§3.6: a listed README's role lines reach its documenter as a file, never in the item."""

    def test_a_dry_run_writes_none_and_names_none(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        for item in _items(_run(project, capsys, "--apply")):
            _written(project, item)
        listed = _run(project, capsys)["readme"]
        assert isinstance(listed, dict)
        assert listed["roles"] is None
        assert not (project / ".zikaron" / "code-knowledge").exists()

    def test_it_is_written_at_the_stores_modes(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        for item in _items(_run(project, capsys, "--apply")):
            _written(project, item)
        previous = os.umask(
            0o022
        )  # a permissive one, so the modes are the code's and not this host's
        try:
            _run(project, capsys, "--apply")
        finally:
            os.umask(previous)
        roles, base = _role_list(project)
        assert stat.S_IMODE(roles.stat().st_mode) == 0o600
        assert stat.S_IMODE(roles.parent.stat().st_mode) == 0o700
        assert stat.S_IMODE(base.stat().st_mode) == 0o700

    def test_it_is_removed_once_the_readme_is_current_and_its_directories_with_it(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _document_everything(project, capsys)
        assert not (project / ".zikaron" / "code-knowledge").exists()
        assert (project / ".zikaron").is_dir()

    def test_another_modules_role_list_keeps_the_base_directory(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        other = _write(
            project / ".zikaron" / "code-knowledge" / "other" / "roles.md", "- `x` — y\n"
        )
        _document_everything(project, capsys)
        assert other.read_text(encoding="utf-8") == "- `x` — y\n"
        assert not (project / ".zikaron" / "code-knowledge" / "src").exists()

    def test_the_root_modules_role_list_sits_at_the_base(self) -> None:
        layout = Layout(documents="code-knowledge", module="")
        roles = command.roles_path(Path("/s/.zikaron"), layout)
        assert roles == Path("/s/.zikaron/code-knowledge/roles.md")

    def test_a_readme_still_listing_its_files_is_written_again(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _document_everything(project, capsys)
        readme = project / "code-knowledge" / "src" / "README.md"
        readme.write_text(readme.read_text(encoding="utf-8") + "\n## Files\n", encoding="utf-8")
        report = _run(project, capsys, "--apply")
        assert report["up_to_date"] is False
        assert report["removed"] == ["code-knowledge/src/README.md"]


class TestARename:
    def test_a_pure_rename_moves_and_spends_nothing(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _document_everything(project, capsys)
        old = project / "code-knowledge" / "src" / "a.scala.md"
        original = old.read_text(encoding="utf-8")
        (project / "src" / "a.scala").rename(project / "src" / "renamed.scala")
        report = _run(project, capsys, "--apply")
        assert report["moved"] == [
            {"from": "code-knowledge/src/a.scala.md", "to": "code-knowledge/src/renamed.scala.md"}
        ]
        assert _items(report) == []
        assert report["readme"] is not None
        assert not old.exists()
        moved = (project / "code-knowledge" / "src" / "renamed.scala.md").read_text(
            encoding="utf-8"
        )
        assert moved.replace("src/renamed.scala", "src/a.scala") == original
        assert _items(_run(project, capsys)) == []

    def test_a_rename_onto_a_hand_written_file_removes_the_orphan_and_keeps_the_file(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _document_everything(project, capsys)
        hand = _write(project / "code-knowledge" / "src" / "renamed.scala.md", "my notes\n")
        (project / "src" / "a.scala").rename(project / "src" / "renamed.scala")
        report = _run(project, capsys, "--apply")
        assert report["moved"] == []
        assert report["removed"] == [
            "code-knowledge/src/README.md",
            "code-knowledge/src/a.scala.md",
        ]
        assert hand.read_text(encoding="utf-8") == "my notes\n"
        assert {
            "document": "code-knowledge/src/renamed.scala.md",
            "source": "src/renamed.scala",
        } in (
            report["foreign"]  # type: ignore[operator]
        )

    def test_a_move_whose_target_appeared_is_not_made(self, project: Path) -> None:
        origin = _write(project / "docs" / "old.md", "---\nzikaron-source: old\n---\n# `old`\n")
        target = _write(project / "docs" / "new.md", "appeared\n")
        move = Move(origin="docs/old.md", target="docs/new.md", source="new")
        planned = Plan(
            work=(),
            remaining=0,
            readme=None,
            removals=(),
            moves=(move,),
            foreign=(),
            unplaceable=(),
            unverifiable=(),
        )
        applied = apply_module.apply(project, planned, *_role_list(project))
        assert applied.moved == ()
        assert origin.exists()
        assert target.read_text(encoding="utf-8") == "appeared\n"

    def test_a_moved_documents_byte_order_mark_is_kept(self, project: Path) -> None:
        text = "---\nzikaron-source: old\nzikaron-source-blob: " + "a" * 40 + "\n---\n# `old`\n"
        bom = chr(0xFEFF).encode()
        _write(project / "docs" / "old.md", bom + text.encode())
        move = Move(origin="docs/old.md", target="docs/new.md", source="new")
        planned = Plan((), 0, None, (), (move,), (), (), ())
        apply_module.apply(project, planned, *_role_list(project))
        moved = (project / "docs" / "new.md").read_bytes()
        assert moved == bom + text.replace("old", "new").encode()


class TestRefusals:
    @pytest.mark.parametrize("module", ["build/gen", ".github/scripts", "src/target"])
    def test_a_module_under_a_pruned_name_is_refused_before_anything_is_walked(
        self,
        module: str,
        project: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        (project / module).mkdir(parents=True)
        _write(project / module / "x.py", "x = 1\n")

        def _never(*_arguments: object) -> Iterator[walk.Candidate]:
            raise AssertionError("walked")

        monkeypatch.setattr(walk, "entries", _never)
        before = _snapshot(project)
        error = _refused(project, capsys, "--module", module, "--apply")
        assert "prunes" in error
        assert _snapshot(project) == before

    def test_a_project_without_a_store_is_refused(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (project / ".zikaron" / "memory.db").unlink()
        error = _refused(project, capsys, "--module", "src")
        assert "no Zikaron store" in error
        assert "python -m zikaron.project" in error

    @pytest.mark.parametrize(
        ("arguments", "says"),
        [
            (["--module", "absent"], "no such directory"),
            (["--module", "src/a.scala"], "not a directory"),
            (["--module", ".."], "outside the project"),
            (["--module", "src", "--documents", "/abs"], "must be relative"),
            (["--module", "src", "--documents", "."], "project root itself"),
            (["--module", "src", "--documents", "src/.."], "project root itself"),
            (["--module", "src", "--documents", ".."], "contains the project root"),
            (["--module", "src", "--documents", "../.."], "contains the project root"),
            (["--module", "src", "--documents", "src"], "contains --module"),
        ],
    )
    def test_an_argument_the_planner_cannot_document_is_refused(
        self,
        arguments: list[str],
        says: str,
        project: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        assert says in _refused(project, capsys, *arguments)

    def test_a_bad_configuration_is_refused(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(project / ".zikaron" / "config.toml", "[indexing]\nknowledge_max_file_bytes = 0\n")
        assert "knowledge_max_file_bytes" in _refused(project, capsys, "--module", "src")

    def test_an_unresolvable_project_is_refused(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        loop = tmp_path / "loop"
        loop.symlink_to(loop)
        status = command.main(["plan", "--project", str(loop / "x"), "--module", "src"])
        assert status == 1
        assert capsys.readouterr().err

    def test_a_negative_limit_is_a_usage_error(self, project: Path) -> None:
        with pytest.raises(SystemExit) as exited:
            command.main(["plan", "--project", str(project), "--module", "src", "--limit", "-1"])
        assert exited.value.code == 2

    def test_a_failure_on_disk_is_reported_not_raised(
        self,
        project: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def _refuses(_root: Path, _plan: Plan, _roles: Path, _base: Path) -> object:
            raise PermissionError("read-only")

        monkeypatch.setattr(command, "apply", _refuses)
        assert "failed: read-only" in _refused(project, capsys, "--module", "src", "--apply")


class TestTheCommandAsADeliverable:
    def test_it_never_reaches_the_service(self, project: Path, socket_dir: Path) -> None:
        """Run as a subprocess against a real store whose socket nothing listens on: a client that
        connected would start a service there, which writes its log beside the store and binds
        its socket under the runtime directory."""
        (project / ".zikaron" / "memory.db").unlink()

        async def _create() -> None:
            async with open_store(project):
                pass

        asyncio.run(_create())
        before = sorted(path.name for path in (project / ".zikaron").iterdir())
        completed = subprocess.run(
            [sys.executable, "-m", "zikaron.code_knowledge", "plan", "--module", "src", "--apply"],
            cwd=project,
            env={**os.environ, "XDG_RUNTIME_DIR": str(socket_dir)},
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        assert json.loads(completed.stdout)["root"] == str(project)
        assert sorted(path.name for path in (project / ".zikaron").iterdir()) == before
        assert list(socket_dir.iterdir()) == []

    def test_the_same_run_prints_the_same_bytes(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(project / "code-knowledge" / "src" / "notes.md", "by hand\n")
        printed = []
        for _ in range(2):
            assert command.main(["plan", "--project", str(project), "--module", "src"]) == 0
            printed.append(capsys.readouterr().out)
        assert printed[0] == printed[1]

    def test_the_module_entry_point_exits_with_the_commands_status(
        self, project: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """In-process, so its lines are measured; the subprocess run above is what shows it works
        as `python -m`."""
        argv = ["zikaron.code_knowledge", "plan", "--project", str(project), "--module", "src"]
        monkeypatch.setattr(sys, "argv", argv)
        with pytest.raises(SystemExit) as exited:
            runpy.run_module("zikaron.code_knowledge", run_name="__main__")
        assert exited.value.code == 0
        assert json.loads(capsys.readouterr().out)["root"] == str(project)

    def test_a_path_standard_output_cannot_encode_is_escaped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        buffer = io.BytesIO()
        monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(buffer, encoding="utf-8"))
        command._print({"source": "src/\udce9.scala"})
        sys.stdout.flush()
        assert json.loads(buffer.getvalue()) == {"source": "src/\udce9.scala"}

    def test_the_layout_is_relative_to_the_root(self) -> None:
        layout = Layout(documents="code-knowledge", module="")
        assert layout.readme == "code-knowledge/README.md"
        assert layout.source("a.py") == "a.py"
