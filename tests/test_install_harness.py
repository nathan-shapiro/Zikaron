"""`zikaron.install.harness`: the two questions install asks the installed kiro binary.

Every test here substitutes `subprocess.run`, because the point is what this module does with each
possible answer — including the answers a real harness gives rarely and the ones it should never
give. One test at the end runs the real binary when it is present, since a parser checked only
against fixtures is a parser checked against my own assumptions about the format.
"""

import json
import subprocess
from pathlib import Path

import pytest

from zikaron.install import harness
from zikaron.install.harness import (
    InstallError,
    available_model_ids,
    harness_is_available,
    validate_agent_config,
)

#: These tests never touch the filesystem — `subprocess.run` is substituted — so the path is only
#: ever stringified into an argv this fake records. Named rather than written inline so it reads as
#: "a path nothing opens".
_UNREAD_PATH = Path("a-config-nothing-reads.json")

_MODELS_JSON = json.dumps(
    {
        "models": [
            {
                "model_name": "claude-sonnet-5",
                "model_id": "claude-sonnet-5",
                "rate_multiplier": 1.3,
            },
            {"model_name": "gpt-5.6-sol", "model_id": "gpt-5.6-sol", "rate_multiplier": 2.4},
        ],
        "default_model": "auto",
    }
)


def _completed(
    stdout: str = "", stderr: str = "", returncode: int = 0
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["kiro-cli"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _fake_run(
    monkeypatch: pytest.MonkeyPatch, result: subprocess.CompletedProcess[str] | Exception
) -> list[list[str]]:
    calls: list[list[str]] = []

    def _run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(subprocess, "run", _run)
    monkeypatch.setattr(harness, "harness_is_available", lambda: True)
    return calls


class TestListingModels:
    def test_it_reads_model_ids(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _fake_run(monkeypatch, _completed(stdout=_MODELS_JSON))
        assert available_model_ids() == frozenset({"claude-sonnet-5", "gpt-5.6-sol"})

    def test_it_asks_for_json_rather_than_parsing_the_human_table(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _fake_run(monkeypatch, _completed(stdout=_MODELS_JSON))
        available_model_ids()
        assert calls == [["kiro-cli", "chat", "--list-models", "-f", "json"]]

    def test_an_absent_binary_is_refused_rather_than_treated_as_no_models(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(harness, "harness_is_available", lambda: False)
        with pytest.raises(InstallError, match="not on PATH"):
            available_model_ids()

    def test_a_non_zero_exit_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _fake_run(monkeypatch, _completed(returncode=2, stderr="unknown flag"))
        with pytest.raises(InstallError, match="unknown flag"):
            available_model_ids()

    def test_a_timeout_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _fake_run(monkeypatch, subprocess.TimeoutExpired(cmd="kiro-cli", timeout=60))
        with pytest.raises(InstallError, match="could not run"):
            available_model_ids()

    def test_a_missing_executable_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`harness_is_available` says yes and the exec still fails — a binary deleted between the
        two calls, or one that is not executable. Refused rather than crashing with an `OSError`
        nobody catches.
        """
        _fake_run(monkeypatch, OSError("permission denied"))
        with pytest.raises(InstallError, match="could not run"):
            available_model_ids()

    def test_non_json_output_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _fake_run(monkeypatch, _completed(stdout="Available models (* = default):"))
        with pytest.raises(InstallError, match="was not JSON"):
            available_model_ids()

    def test_json_without_a_models_array_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _fake_run(monkeypatch, _completed(stdout=json.dumps({"default_model": "auto"})))
        with pytest.raises(InstallError, match="no `models` array"):
            available_model_ids()

    def test_a_models_array_with_no_readable_ids_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An empty set would make the caller reject a perfectly good model id for the wrong
        reason — the whole point of refusing every unreadable answer separately."""
        _fake_run(monkeypatch, _completed(stdout=json.dumps({"models": [{"name": "x"}, 7]})))
        with pytest.raises(InstallError, match="no readable `model_id`"):
            available_model_ids()

    def test_entries_missing_an_id_are_skipped_rather_than_failing_the_whole_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = json.dumps({"models": [{"model_id": "a-model"}, {"model_name": "no id here"}]})
        _fake_run(monkeypatch, _completed(stdout=payload))
        assert available_model_ids() == frozenset({"a-model"})


class TestValidatingAConfig:
    def test_a_clean_validation_reports_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _fake_run(monkeypatch, _completed())
        assert validate_agent_config(_UNREAD_PATH) is None

    def test_a_complaint_is_returned_verbatim(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The harness's own text names the offending field; replacing it with "invalid" would throw
        away the only useful part."""
        _fake_run(monkeypatch, _completed(returncode=1, stderr="unknown field `toolz`"))
        assert validate_agent_config(_UNREAD_PATH) == "unknown field `toolz`"

    def test_a_complaint_on_stdout_is_found_too(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _fake_run(monkeypatch, _completed(returncode=1, stdout="malformed"))
        assert validate_agent_config(_UNREAD_PATH) == "malformed"

    def test_a_silent_failure_still_reports_something(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fake_run(monkeypatch, _completed(returncode=3))
        complaint = validate_agent_config(_UNREAD_PATH)
        assert complaint is not None
        assert "exited 3" in complaint

    def test_it_reports_rather_than_raises_when_the_binary_cannot_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A report, not a gate: by the time this runs the files are already written, and an
        exception here would leave the user guessing which file it meant."""
        _fake_run(monkeypatch, OSError("no such file"))
        complaint = validate_agent_config(_UNREAD_PATH)
        assert complaint is not None
        assert "could not run" in complaint


@pytest.mark.integration
class TestAgainstTheRealBinary:
    """A parser checked only against fixtures is checked against my own belief about the format."""

    def test_the_real_harness_lists_model_ids_this_parser_can_read(self) -> None:
        if not harness_is_available():
            pytest.skip("kiro-cli is not installed on this machine")
        ids = available_model_ids()
        assert ids, "the real harness answered with no model ids"
        assert all(model_id != "" for model_id in ids)

    def test_the_real_validator_accepts_a_config_we_write(self, tmp_path: Path) -> None:
        if not harness_is_available():
            pytest.skip("kiro-cli is not installed on this machine")
        config = tmp_path / "probe.json"
        config.write_text(
            json.dumps({"name": "probe", "description": "d", "tools": [], "allowedTools": []})
        )
        assert validate_agent_config(config) is None

    def test_the_real_validator_does_not_check_model_ids(self, tmp_path: Path) -> None:
        """The measurement the whole model check rests on, asserted rather than remembered: if a
        future harness starts rejecting an unknown model, this fails and the reason our own check
        exists is worth re-reading.
        """
        if not harness_is_available():
            pytest.skip("kiro-cli is not installed on this machine")
        config = tmp_path / "bogus-model.json"
        config.write_text(
            json.dumps({"name": "bogus-model", "description": "d", "model": "not-a-real-model-xyz"})
        )
        assert validate_agent_config(config) is None
