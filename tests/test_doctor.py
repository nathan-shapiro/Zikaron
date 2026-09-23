"""What `zikaron doctor` reports, and that a broken machine produces a remedy rather than a crash.

**Every failing row is reached by mutation, not by inspection.** A check that has never been seen
failing is a check whose failure path is unexecuted, and the whole value of this command is what it
says when something is wrong.
"""

import hashlib
import sqlite3
import sys
from pathlib import Path
from types import MappingProxyType
from typing import Final

import pytest

from zikaron.core.indexing.model_cache import FASTEMBED_CACHE_VARIABLE, snapshot_dir
from zikaron.core.indexing.model_pin import PinnedArtifact
from zikaron.doctor import checks
from zikaron.doctor.main import main, rendered

#: A synthetic artefact, because a digest cannot be reversed into bytes a test can write. The
#: shipped pin's own shape is asserted in `test_indexing_acquisition.py`; what is under test here is
#: the check, which does not care which artefact it is handed.
_FILES: Final = {"config.json": b"{}", "tokenizer.json": b'{"tokenizer": true}'}
_PIN: Final = PinnedArtifact(
    model_name="fake/model",
    repo_id="fake/model-onnx-q",
    revision="0" * 39 + "a",
    digests=MappingProxyType(
        {name: hashlib.sha256(body).hexdigest() for name, body in _FILES.items()}
    ),
)


def _write_snapshot(cache_dir: Path, pin: PinnedArtifact, *, corrupt: str | None = None) -> Path:
    """A cache holding `pin` at its revision, optionally with one file's bytes wrong."""
    snapshot = snapshot_dir(cache_dir, repo_id=pin.repo_id, revision=pin.revision)
    snapshot.mkdir(parents=True)
    for filename, body in _FILES.items():
        snapshot.joinpath(filename).write_bytes(
            b"not what was pinned" if filename == corrupt else body
        )
    return snapshot


class _StubConnection:
    """A `sqlite3.Connection` stand-in for the machines this suite does not run on.

    Real connections are C objects whose methods cannot be replaced, so the probes' failure paths
    are unreachable without one of these. `has_extension_loading` false is the interpreter built
    without it; `fts5` false is a SQLite built without the module.
    """

    def __init__(self, *, has_extension_loading: bool = True, fts5: bool = True) -> None:
        self.fts5 = fts5
        if has_extension_loading:
            self.enable_load_extension = lambda _enabled: None

    def __enter__(self) -> "_StubConnection":
        return self

    def __exit__(self, *_exception: object) -> None:
        return None

    def execute(self, statement: str) -> object:
        if "fts5" in statement and not self.fts5:
            raise sqlite3.OperationalError("no such module: fts5")
        return None

    def load_extension(self, path: str) -> None:
        raise sqlite3.OperationalError(f"cannot load {path} into this build")


class TestTheChecksOnAHealthyMachine:
    """This suite runs on a machine that can run Zikaron, so these are the pass paths."""

    def test_extension_loading_fts5_and_sqlite_vec_all_pass(self) -> None:
        for finding in (
            checks.check_extension_loading(),
            checks.check_fts5(),
            checks.check_sqlite_vec(),
        ):
            assert finding.outcome is checks.Outcome.PASSED, finding.detail
            assert finding.remedy is None

    def test_the_sqlite_version_is_reported_and_cannot_fail(self) -> None:
        finding = checks.report_sqlite_version()
        assert finding.outcome is checks.Outcome.REPORTED
        assert sqlite3.sqlite_version in finding.detail


def _stub_connections(monkeypatch: pytest.MonkeyPatch, **kwargs: bool) -> None:
    monkeypatch.setattr("sqlite3.connect", lambda _target: _StubConnection(**kwargs))


class TestExtensionLoadingIsAbsent:
    """The python.org-macOS and conda case, which otherwise arrives as a bare `AttributeError`."""

    def test_it_produces_a_remedy_line_and_not_a_traceback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_connections(monkeypatch, has_extension_loading=False)
        finding = checks.check_extension_loading()
        assert finding.outcome is checks.Outcome.FAILED
        assert finding.remedy is not None
        assert "uv python install" in finding.remedy

    def test_sqlite_vec_says_it_was_not_probed_rather_than_that_it_is_broken(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two rows would otherwise report one cause, and the second would name the wrong remedy."""
        _stub_connections(monkeypatch, has_extension_loading=False)
        finding = checks.check_sqlite_vec()
        assert finding.outcome is checks.Outcome.FAILED
        assert "not probed" in finding.detail


class TestFts5IsAbsent:
    def test_the_operational_error_becomes_a_remedy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub_connections(monkeypatch, fts5=False)
        finding = checks.check_fts5()
        assert finding.outcome is checks.Outcome.FAILED
        assert finding.remedy is not None
        assert "FTS5" in finding.remedy


class TestSqliteVecWillNotLoad:
    def test_an_absent_package_is_a_failure_with_the_reinstall_remedy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`None` in `sys.modules` makes `import sqlite_vec` raise the exact `ImportError` the check
        catches, without touching the installed package. Uncaught, this is the traceback the whole
        command exists to replace."""
        monkeypatch.setitem(sys.modules, "sqlite_vec", None)
        finding = checks.check_sqlite_vec()
        assert finding.outcome is checks.Outcome.FAILED
        assert "not installed" in finding.detail
        assert finding.remedy is not None
        assert "reinstall" in finding.remedy

    def test_a_present_but_unloadable_extension_names_the_platform_remedy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Importable and unloadable are different states, which is why a bare import is not the
        test."""
        _stub_connections(monkeypatch)
        finding = checks.check_sqlite_vec()
        assert finding.outcome is checks.Outcome.FAILED
        assert "would not load" in finding.detail
        assert finding.remedy is not None
        assert "arm64" in finding.remedy


class TestTheModelCache:
    def test_an_absent_cache_passes_and_says_when_it_will_be_fetched(self, tmp_path: Path) -> None:
        """**Exit 0, not a failure.** With no install-time prefetch, a stranger's first run finds
        no model at all, and a non-zero exit before anything is wrong ships a red first run."""
        finding = checks.check_model_cache(_PIN, cache_dir=tmp_path)
        assert finding.outcome is checks.Outcome.PASSED
        assert "not yet fetched" in finding.detail

    def test_a_cache_holding_only_another_revision_is_the_absent_case(self, tmp_path: Path) -> None:
        """Nothing is wrong with bytes this release does not claim."""
        other = PinnedArtifact(
            model_name=_PIN.model_name,
            repo_id=_PIN.repo_id,
            revision="f" * 40,
            digests=_PIN.digests,
        )
        _write_snapshot(tmp_path, other)
        finding = checks.check_model_cache(_PIN, cache_dir=tmp_path)
        assert finding.outcome is checks.Outcome.PASSED
        assert "not yet fetched" in finding.detail

    def test_a_verified_cache_passes_naming_the_revision(self, tmp_path: Path) -> None:
        _write_snapshot(tmp_path, _PIN)
        finding = checks.check_model_cache(_PIN, cache_dir=tmp_path)
        assert finding.outcome is checks.Outcome.PASSED
        assert _PIN.revision in finding.detail

    def test_a_mismatched_file_fails_naming_it(self, tmp_path: Path) -> None:
        _write_snapshot(tmp_path, _PIN, corrupt="tokenizer.json")
        finding = checks.check_model_cache(_PIN, cache_dir=tmp_path)
        assert finding.outcome is checks.Outcome.FAILED
        assert "tokenizer.json" in finding.detail

    def test_a_wrong_file_is_told_to_remove_the_snapshot(self, tmp_path: Path) -> None:
        """**The remedy has to match what a start will actually do.** A warm start checks presence
        only, so it repairs nothing here; "start the service" would send the user round a loop that
        cannot help and then blame the source for their disk. Removing the snapshot is what makes
        the next start re-acquire down the path that verifies.
        """
        snapshot = _write_snapshot(tmp_path, _PIN, corrupt="config.json")
        remedy = checks.check_model_cache(_PIN, cache_dir=tmp_path).remedy
        assert remedy is not None
        assert str(snapshot) in remedy
        assert "re-acquires and verifies" in remedy

    def test_an_absent_file_alone_is_told_only_to_start_the_service(self, tmp_path: Path) -> None:
        """The fill path does handle this one, and it verifies what it fetched — so the heavier
        remedy would be wrong advice in the other direction."""
        snapshot = _write_snapshot(tmp_path, _PIN)
        (snapshot / "config.json").unlink()
        remedy = checks.check_model_cache(_PIN, cache_dir=tmp_path).remedy
        assert remedy is not None
        assert "remove" not in remedy
        assert "fetches the missing files and verifies them" in remedy


class TestTheSocketPathBound:
    """M29's owed second channel: the refusal a user would otherwise meet as a dead MCP server."""

    def test_an_ordinary_runtime_directory_passes(self, tmp_path: Path) -> None:
        finding = checks.check_socket_path(
            store_dir=tmp_path, environ={"XDG_RUNTIME_DIR": "/run/user/1000"}, platform="linux"
        )
        assert finding.outcome is checks.Outcome.PASSED

    def test_an_over_long_runtime_directory_fails_with_the_refusals_own_remedy(
        self, tmp_path: Path
    ) -> None:
        finding = checks.check_socket_path(
            store_dir=tmp_path,
            environ={"XDG_RUNTIME_DIR": "/" + "x" * 200},
            platform="linux",
        )
        assert finding.outcome is checks.Outcome.FAILED
        assert finding.remedy is not None
        assert "$XDG_RUNTIME_DIR" in finding.remedy

    def test_macos_refuses_a_directory_linux_accepts(self, tmp_path: Path) -> None:
        """`sun_path` is tighter on macOS, and the bound is checked per platform rather than per
        machine so both rows are exercised wherever the suite runs."""
        environ = {"XDG_RUNTIME_DIR": "/" + "x" * 60}
        assert (
            checks.check_socket_path(store_dir=tmp_path, environ=environ, platform="linux").outcome
            is checks.Outcome.PASSED
        )
        assert (
            checks.check_socket_path(store_dir=tmp_path, environ=environ, platform="darwin").outcome
            is checks.Outcome.FAILED
        )


class TestTheFindingContract:
    def test_a_failure_without_a_remedy_is_a_programming_error(self) -> None:
        """The property that makes this command what it is, enforced where a finding is built."""
        with pytest.raises(ValueError, match="names a remedy"):
            checks.Finding(name="x", outcome=checks.Outcome.FAILED, detail="broken")

    def test_a_pass_carrying_a_remedy_is_a_programming_error(self) -> None:
        with pytest.raises(ValueError, match="names a remedy"):
            checks.Finding(
                name="x", outcome=checks.Outcome.PASSED, detail="fine", remedy="unnecessary"
            )


class TestTheCommand:
    """**The cache is pointed at an empty directory throughout**, so these report on the code and
    not on whatever the developer's own `~/.cache/zikaron/models` holds — one corrupt file in a
    real cache would otherwise redden a test about exit codes.
    """

    @staticmethod
    @pytest.fixture(autouse=True)
    def _empty_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv(FASTEMBED_CACHE_VARIABLE, str(tmp_path / "cache"))

    def test_a_healthy_machine_exits_zero_and_prints_every_row(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["--project", str(tmp_path)]) == 0
        printed = capsys.readouterr().out
        for expected in (
            "extension loading",
            "FTS5",
            "sqlite-vec",
            "model cache",
            "socket path",
            "sqlite version",
        ):
            assert expected in printed

    def test_a_failing_row_makes_the_exit_non_zero_and_prints_its_remedy(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Done-when 2's `main`-level half: the over-long `$XDG_RUNTIME_DIR` must produce the
        socket-path check's remedy *line*, not merely a non-zero status."""
        monkeypatch.setenv("XDG_RUNTIME_DIR", "/" + "x" * 200)
        assert main(["--project", str(tmp_path)]) == 1
        printed = capsys.readouterr().out
        assert "remedy: " in printed
        assert "$XDG_RUNTIME_DIR" in printed

    def test_the_remedy_is_printed_under_the_row_it_belongs_to(self) -> None:
        findings = [
            checks.Finding(name="first", outcome=checks.Outcome.PASSED, detail="fine"),
            checks.Finding(
                name="second", outcome=checks.Outcome.FAILED, detail="broken", remedy="do this"
            ),
        ]
        lines = rendered(findings)
        assert len(lines) == 3
        assert "second" in lines[1]
        assert lines[2].strip() == "remedy: do this"
