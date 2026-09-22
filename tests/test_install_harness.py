"""`zikaron.install.harness`: what install asks a harness binary, and what it does with each answer.

Three functions now, not two, and one of them is not kiro's: `binary_is_available` answers *is this
harness installed at all* for **either** harness, and is what `HarnessTarget.refuse_absent_harness`
is built on. The model list and the config validator are kiro's alone.

Most tests here substitute `subprocess.run`, because the point is what this module does with each
possible answer — including the answers a real harness gives rarely and the ones it should never
give. **Those fakes are only as good as the shapes they encode**, which this file learned the hard
way: every one of them used a *non-zero exit* to mean "the validator complained", a value the real
binary never produces, so they agreed with each other and with nothing else while
`validate_agent_config` returned "clean" unconditionally for three milestones.

The two `integration_kiro` classes below therefore run the real binary, kept out of the default
run so the gate stays hermetic — a parser checked only against fixtures is a parser checked against
my own assumptions about the format, and a wrapper checked only against fixtures is worse.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from zikaron.harness.spec import KIRO
from zikaron.install import harness
from zikaron.install.entries import (
    CONSOLIDATOR_AGENT_NAME,
    Commands,
    consolidator_agent_config,
)
from zikaron.install.harness import (
    InstallError,
    available_model_ids,
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


def _require_kiro() -> None:
    """Fail — not skip — when `kiro-cli` is absent.

    **Absence is a legitimate failure in this tier**, because the tier is only ever reached by
    explicit request: `pytest -m integration_kiro` on a machine without kiro is a mistake about the
    machine, and a skip would report success for it. Worse, it would report success for the *other*
    cause too — `HarnessSpec.harness_binary` naming a binary that does not exist — which the
    spec↔design drift guard cannot catch, since it pins the code against `harness.md` rather than
    against the machine, and an upstream rename lands on both at once.

    That is exactly the shape seen on the Claude Code side, where a wrong name made the
    whole tier exit 0 on four skips. The message names both causes so the reader does not have to
    guess which one they hit.
    """
    found = shutil.which(KIRO.harness_binary)
    assert found is not None, (
        f"{KIRO.harness_binary!r} is not on PATH. Either this machine has no kiro — in which case "
        "do not run `-m integration_kiro` here — or `HarnessSpec.harness_binary` names the wrong "
        "binary, in which case every kiro install refuses and no other test can see it."
    )


@pytest.mark.integration_kiro
class TestAgainstTheRealBinary:
    """A parser checked only against fixtures is checked against my own belief about the format.

    **Out of the default run**, because these need `kiro-cli` to be installed *and working*, which
    is a dependency on a third party's credential state rather than on anything in this repository.
    Everything above stubs `subprocess.run` and covers the same parsing and refusal behaviour
    hermetically; what only a real binary can establish is the third test below.
    """

    def test_the_real_harness_lists_model_ids_this_parser_can_read(self) -> None:
        _require_kiro()
        ids = available_model_ids()
        assert ids, "the real harness answered with no model ids"
        assert all(model_id != "" for model_id in ids)

    def test_the_real_validator_accepts_the_config_we_actually_ship(self, tmp_path: Path) -> None:
        """The **real shipped artefact**, serialized exactly as `KiroTarget.shipped_files` does.

        It used to validate a four-key toy, which asserted a belief about a document nothing ships.
        That matters more since the tiering: before it, every `test_install_e2e.py`
        run incidentally drove this validator over the real written config through
        `complaints_about`, and stubbing the binary there removed the only place the shipped JSON
        met the real validator at all. This is where that check belongs anyway — the tier that
        exists for claims about the harness's own behaviour.
        """
        _require_kiro()
        scripts = tmp_path / "bin"
        scripts.mkdir()
        commands = Commands(hook=scripts / "zikaron-hook", mcp=scripts / "zikaron-mcp")
        for path in (commands.hook, commands.mcp):
            path.write_text("#!/bin/sh\n")
            path.chmod(0o755)

        config = tmp_path / f"{CONSOLIDATOR_AGENT_NAME}.json"
        config.write_text(
            json.dumps(consolidator_agent_config(commands, model=KIRO.consolidator_model), indent=2)
            + "\n",
            encoding="utf-8",
        )
        assert validate_agent_config(config) is None

    def test_the_real_validator_does_not_check_model_ids(self, tmp_path: Path) -> None:
        """**The one assertion here a stub genuinely cannot make**, and the reason this tier exists
        at all rather than being deleted in favour of the fixtures above.

        It is a claim about the *harness's* behaviour — that `agent validate` accepts a model id it
        has never heard of — and the entire install-time model check exists because of it. A stub
        asserting it would be asserting our own belief back to us. If a future kiro starts rejecting
        unknown models, this fails and the reason our check exists is worth re-reading.
        """
        _require_kiro()
        config = tmp_path / "bogus-model.json"
        config.write_text(
            json.dumps({"name": "bogus-model", "description": "d", "model": "not-a-real-model-xyz"})
        )
        assert validate_agent_config(config) is None


class TestAComplaintIsOutputNotAnExitCode:
    """The predicate this function turns on, pinned after it was wrong for three milestones.

    `kiro-cli agent validate` **exits 0 whether or not it found a problem** and writes its complaint
    to stderr (measured; the table is in `validate_agent_config`'s docstring). Reading the exit code
    made the function return `None` unconditionally, so every install reported a clean validation
    regardless of what it had written.

    These are unit-tier fakes, but they now encode the **measured** shapes rather than the assumed
    ones — which is the whole reason the defect survived: the old fixtures all used a non-zero exit,
    a value the real binary never produces.
    """

    def test_a_complaint_on_stderr_with_a_zero_exit_is_reported(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The exact shape the real binary produces, and the one the old code discarded."""
        _fake_run(
            monkeypatch,
            subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr="Error: Json supplied is invalid"
            ),
        )
        assert validate_agent_config(Path("x.json")) == "Error: Json supplied is invalid"

    def test_silence_with_a_zero_exit_is_a_clean_validation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fake_run(
            monkeypatch, subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        )
        assert validate_agent_config(Path("x.json")) is None


@pytest.mark.integration_kiro
class TestTheRealValidatorComplainsAtAll:
    """Without this, every `is None` assertion in the tier above passes vacuously.

    A validator that accepted everything would satisfy "it accepts the config we ship" perfectly,
    and that is not a hypothetical — it is what our own wrapper *did*, and what made the shipped
    check a no-op that nothing noticed. So the tier asserts the harness can say **no**, and records
    the shape in which it says it.
    """

    def test_it_reports_a_broken_config_on_stderr_while_still_exiting_zero(
        self, tmp_path: Path
    ) -> None:
        _require_kiro()
        broken = tmp_path / "broken.json"
        broken.write_text("{not json", encoding="utf-8")

        # The **measured shape**, asserted directly rather than through our wrapper, because the
        # wrapper hides the exit code — so a future kiro that moved complaints onto a non-zero exit
        # would leave this green (the non-zero branch relays output too) while this test's name and
        # `validate_agent_config`'s measured table both went silently stale.
        completed = subprocess.run(  # noqa: S603 — fixed argv, no shell.
            [KIRO.harness_binary, "agent", "validate", "--path", str(broken)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert completed.returncode == 0, "kiro now signals by exit code — re-read the docstring"
        assert completed.stderr.strip(), "the validator accepted unparseable JSON — no opinions"

        complaint = validate_agent_config(broken)
        assert complaint is not None, "the wrapper discarded a complaint the binary did make"
        # Relay-*exactness*, which is a claim about our code, rather than a substring of kiro's
        # phrasing, which is a claim about theirs. The design says this function keeps the harness's
        # own diagnostics instead of replacing them with "invalid"; this is that sentence, asserted.
        assert complaint == completed.stderr.strip()
