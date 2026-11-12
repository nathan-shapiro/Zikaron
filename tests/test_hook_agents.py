"""`zikaron.hook.agents`: which of Zikaron's agents an agent is, by its definition.

`design/harness.md` §"Agent teams" is normative. An in-process teammate's `agent_type` is its name,
and any spawn given a name becomes one, so the consolidator is recognized by the record the harness
keeps for it — and an agent with an `agent_id` and no readable record is named by nothing.
"""

import json
from pathlib import Path

import pytest

from zikaron.harness.spec import CLAUDE_CODE, InstructionPush
from zikaron.hook import agents
from zikaron.install.code_knowledge import DOCUMENTER_AGENT_NAME, ORCHESTRATOR_AGENT_NAME
from zikaron.install.entries import CONSOLIDATOR_AGENT_NAME

AGENT = "amate-1-d82c396dc9f48005"


@pytest.fixture
def push_spec() -> InstructionPush:
    assert CLAUDE_CODE.instruction_push is not None
    return CLAUDE_CODE.instruction_push


@pytest.fixture
def session_transcript(tmp_path: Path) -> Path:
    return tmp_path / "session.jsonl"


def _record(push_spec: InstructionPush, session_transcript: Path, record: object) -> None:
    path = push_spec.agent_file(session_transcript, AGENT, push_spec.record_suffix)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record), encoding="utf-8")


def _definition(push_spec: InstructionPush, session_transcript: Path, **payload: object) -> object:
    return agents.definition(
        push_spec,
        session_transcript=str(session_transcript),
        agent_id=payload.get("agent_id"),
        agent_type=payload.get("agent_type"),
    )


def test_the_copies_match_the_installers_own_names() -> None:
    assert agents.CONSOLIDATOR_AGENT_TYPE == CONSOLIDATOR_AGENT_NAME
    assert agents.DOCUMENTER_AGENT_TYPE == DOCUMENTER_AGENT_NAME
    assert agents.ORCHESTRATOR_AGENT_TYPE == ORCHESTRATOR_AGENT_NAME


@pytest.mark.parametrize(
    ("record", "expected"),
    [
        (
            {"agentType": "mate-1", "spawnedAgentType": "probe-mate", "customAgentType": "x"},
            "probe-mate",
        ),
        ({"agentType": "mate-1", "customAgentType": "probe-mate"}, "probe-mate"),
        ({"agentType": "general-purpose", "name": "chosen"}, "general-purpose"),
        ({"agentType": "", "spawnedAgentType": ""}, None),
        ({"description": "no definition"}, None),
        (["not", "an", "object"], None),
    ],
)
def test_an_agents_record_names_its_definition(
    push_spec: InstructionPush, session_transcript: Path, record: object, expected: str | None
) -> None:
    _record(push_spec, session_transcript, record)
    assert _definition(push_spec, session_transcript, agent_id=AGENT, agent_type="mate-1") == (
        expected
    )


def test_a_missing_or_unreadable_record_names_nothing(
    push_spec: InstructionPush, session_transcript: Path
) -> None:
    assert _definition(push_spec, session_transcript, agent_id=AGENT, agent_type="x") is None
    path = push_spec.agent_file(session_transcript, AGENT, push_spec.record_suffix)
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    assert _definition(push_spec, session_transcript, agent_id=AGENT, agent_type="x") is None


def test_without_an_agent_id_the_type_is_the_definition(
    push_spec: InstructionPush, session_transcript: Path
) -> None:
    assert _definition(push_spec, session_transcript, agent_type="probe-mate") == "probe-mate"
    assert _definition(push_spec, session_transcript, agent_type=42) is None
    assert _definition(push_spec, session_transcript) is None


def test_an_agent_id_with_no_transcript_path_names_nothing(push_spec: InstructionPush) -> None:
    assert (
        agents.definition(push_spec, session_transcript=None, agent_id=AGENT, agent_type="x")
        is None
    )


def test_a_consolidator_spawned_by_name_is_known_by_its_record(
    push_spec: InstructionPush, session_transcript: Path
) -> None:
    _record(
        push_spec,
        session_transcript,
        {"agentType": "consolidate-now", "spawnedAgentType": CONSOLIDATOR_AGENT_NAME},
    )
    named = agents.known_as(
        push_spec,
        session_transcript=str(session_transcript),
        agent_id=AGENT,
        agent_type="consolidate-now",
    )
    assert named == CONSOLIDATOR_AGENT_NAME


def test_known_as_falls_back_to_the_type_before_a_record_exists(
    push_spec: InstructionPush, session_transcript: Path
) -> None:
    named = agents.known_as(
        push_spec,
        session_transcript=str(session_transcript),
        agent_id=AGENT,
        agent_type=CONSOLIDATOR_AGENT_NAME,
    )
    assert named == CONSOLIDATOR_AGENT_NAME
    assert agents.known_as(None, session_transcript=None, agent_id=AGENT, agent_type=7) is None
