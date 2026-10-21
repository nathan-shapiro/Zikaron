"""Which model each agent is installed with: `--model`, an agent's own flag over it, and what is
refused (`design/harness.md` §"The flags, and what each refuses")."""

import json
from pathlib import Path
from typing import Final

import pytest

from zikaron.harness.spec import CLAUDE_CODE, KIRO, Harness
from zikaron.hook.components import Components
from zikaron.install import harness as install_harness
from zikaron.install.code_knowledge import (
    DOCUMENTER_AGENT_NAME,
    ORCHESTRATOR_AGENT_NAME,
    ORCHESTRATOR_MODEL,
)
from zikaron.install.entries import CONSOLIDATOR_AGENT_NAME, Commands, HookFormat
from zikaron.install.main import main
from zikaron.install.targets import ClaudeCodeTarget, KiroTarget, target_for
from zikaron.install.writer import Plan, Targets

pytestmark = pytest.mark.usefixtures("stub_harness_binaries")

_FLAG_OF: Final = {
    "consolidator": "--consolidator-model",
    "documenter": "--documenter-model",
    "orchestrator": "--orchestrator-model",
}

_AGENT_FILE_OF: Final = {
    "consolidator": CONSOLIDATOR_AGENT_NAME,
    "documenter": DOCUMENTER_AGENT_NAME,
    "orchestrator": ORCHESTRATOR_AGENT_NAME,
}

_CLAUDE_DEFAULTS: Final = {
    "consolidator": CLAUDE_CODE.consolidator_model,
    "documenter": CLAUDE_CODE.documenter_model,
    "orchestrator": ORCHESTRATOR_MODEL,
}

_KIRO_DEFAULTS: Final = {
    "consolidator": KIRO.consolidator_model,
    "documenter": KIRO.documenter_model,
}


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    return root


def _claude(project: Path, *flags: str) -> int:
    return main(["--project", str(project), "--harness", Harness.CLAUDE_CODE.value, *flags])


def _kiro(project: Path, *flags: str) -> int:
    return main(["--project", str(project), "--harness", Harness.KIRO.value, *flags])


def _claude_models(project: Path) -> dict[str, str]:
    """Each agent's `model:`, read from its definition's frontmatter."""
    models: dict[str, str] = {}
    for agent, name in _AGENT_FILE_OF.items():
        text = (project / ".claude" / "agents" / f"{name}.md").read_text(encoding="utf-8")
        frontmatter = text.split("---")[1]
        models[agent] = next(
            line.removeprefix("model: ")
            for line in frontmatter.splitlines()
            if line.startswith("model: ")
        )
    return models


def _kiro_models(project: Path) -> dict[str, str]:
    targets = Targets(project=project)
    configs = {
        "consolidator": targets.consolidator_config,
        "documenter": targets.documenter_config,
    }
    return {
        agent: json.loads(path.read_text(encoding="utf-8"))["model"]
        for agent, path in configs.items()
    }


def _offer(monkeypatch: pytest.MonkeyPatch, *models: str) -> None:
    """Have kiro's model list offer `models` beside its default."""
    offered = frozenset({KIRO.consolidator_model, *models})
    monkeypatch.setattr(install_harness, "available_model_ids", lambda: offered)


def _tree(project: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(project)): path.read_bytes()
        for path in sorted(project.rglob("*"))
        if path.is_file()
    }


class TestEachFlagSetsItsOwnAgent:
    @pytest.mark.parametrize("agent", sorted(_CLAUDE_DEFAULTS))
    def test_under_claude_code(self, project: Path, agent: str) -> None:
        assert _claude(project, _FLAG_OF[agent], "chosen") == 0
        assert _claude_models(project) == {**_CLAUDE_DEFAULTS, agent: "chosen"}

    @pytest.mark.parametrize("agent", sorted(_KIRO_DEFAULTS))
    def test_under_kiro(self, project: Path, agent: str, monkeypatch: pytest.MonkeyPatch) -> None:
        _offer(monkeypatch, "chosen")
        assert _kiro(project, _FLAG_OF[agent], "chosen") == 0
        assert _kiro_models(project) == {**_KIRO_DEFAULTS, agent: "chosen"}


class TestPrecedence:
    @pytest.mark.parametrize("agent", sorted(_CLAUDE_DEFAULTS))
    def test_an_agents_own_flag_wins_over_model(self, project: Path, agent: str) -> None:
        assert _claude(project, "--model", "every", _FLAG_OF[agent], "own") == 0
        assert _claude_models(project) == {**dict.fromkeys(_CLAUDE_DEFAULTS, "every"), agent: "own"}

    @pytest.mark.parametrize("agent", sorted(_CLAUDE_DEFAULTS))
    def test_an_empty_value_is_refused_rather_than_replaced(
        self, project: Path, agent: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _claude(project, _FLAG_OF[agent], "") == 1
        assert "cannot be written into YAML frontmatter" in capsys.readouterr().err
        assert _tree(project) == {}


class TestRefusals:
    @pytest.mark.parametrize("flag", ["--model", *_FLAG_OF.values()])
    @pytest.mark.parametrize("preview", [False, True], ids=["install", "print-only"])
    def test_every_model_flag_is_refused_under_guards(
        self, project: Path, flag: str, preview: bool, capsys: pytest.CaptureFixture[str]
    ) -> None:
        extra = ["--print-only"] if preview else []
        assert _claude(project, "--components", "guards", flag, "a-model", *extra) == 1
        refusal = capsys.readouterr().err
        assert "--components guards ships no agent" in refusal
        assert flag in refusal
        assert _tree(project) == {}

    def test_the_guards_refusal_names_every_flag_given(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        flags = ["--model", "a", "--documenter-model", "b"]
        assert _claude(project, "--components", "guards", *flags) == 1
        assert "nothing would use --model, --documenter-model." in capsys.readouterr().err

    @pytest.mark.parametrize("preview", [False, True], ids=["install", "print-only"])
    def test_orchestrator_model_is_refused_where_no_orchestrator_ships(
        self, project: Path, preview: bool, capsys: pytest.CaptureFixture[str]
    ) -> None:
        extra = ["--print-only"] if preview else []
        assert _kiro(project, "--orchestrator-model", KIRO.consolidator_model, *extra) == 1
        refusal = capsys.readouterr().err
        assert "--orchestrator-model has no meaning under --harness kiro" in refusal
        assert "--documenter-model sets the documenter" in refusal
        assert _tree(project) == {}


@pytest.mark.parametrize("harness", list(Harness), ids=[harness.value for harness in Harness])
def test_ships_orchestrator_agrees_with_what_a_memory_install_writes(
    tmp_path: Path, harness: Harness
) -> None:
    target = target_for(harness)
    plan = Plan(
        project=tmp_path,
        commands=Commands(hook=Path("/venv/bin/zikaron-hook"), mcp=Path("/venv/bin/zikaron-mcp")),
        consolidator_model="a-model",
        documenter_model="a-model",
        orchestrator_model="a-model",
        hook_format=HookFormat.OBJECT,
        force=False,
        trust_tools=True,
        components=Components.MEMORY,
    )
    written = {shipped.path.stem for shipped in target.shipped_files(plan)}
    assert (ORCHESTRATOR_AGENT_NAME in written) is target.ships_orchestrator


class TestTheModelCheck:
    """Each distinct model the install writes is checked once, counted by a recorder put in place
    of each target's check."""

    @pytest.fixture
    def checked(self, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        calls: list[str] = []

        def record(_target: object, model: str) -> None:
            calls.append(model)

        for target in (KiroTarget, ClaudeCodeTarget):
            monkeypatch.setattr(target, "refuse_unknown_model", record)
        return calls

    def test_claude_code_checks_each_agents_default(
        self, project: Path, checked: list[str]
    ) -> None:
        assert _claude(project) == 0
        assert sorted(checked) == sorted(set(_CLAUDE_DEFAULTS.values()))

    def test_an_orchestrator_flag_is_what_is_checked(
        self, project: Path, checked: list[str]
    ) -> None:
        assert _claude(project, "--orchestrator-model", "picked") == 0
        assert sorted(checked) == sorted({**_CLAUDE_DEFAULTS, "orchestrator": "picked"}.values())

    def test_models_that_coincide_are_checked_once(self, project: Path, checked: list[str]) -> None:
        assert _claude(project, "--model", "every") == 0
        assert checked == ["every"]

    def test_kiro_checks_its_agents_and_no_orchestrator(
        self, project: Path, checked: list[str]
    ) -> None:
        assert _kiro(project) == 0
        assert sorted(checked) == sorted(set(_KIRO_DEFAULTS.values()))
