"""What a code-knowledge run cost, and how its orchestrator waited, read from Claude Code's
transcripts of one session.

    .venv/bin/python experiments/m40_run_cost.py ~/.claude/projects/<project>/<session-id>

Every subagent transcript under `<session>/subagents/` is read; each API message is counted once,
by its message id, since a message's content blocks arrive as separate records carrying the same
usage. The four `usage` fields are priced at list price per message, with a 5-minute cache write at
1.25 times the input price and a 1-hour one at twice it, and Haiku 5.5's higher rates for a prompt
over 100,000 tokens. Prices are the API's list prices as of 2026-10-06, Haiku 5.5's cache read
excepted: no price is listed for it, so it is taken as a tenth of its input price, as Sonnet 5.5's
is. A model not listed is reported with its tokens and no price.

Printed per agent: its kind — the orchestrator's transcript opens with the skill's text, a
documenter's with its item's `Root:` line, and anything else is `other` — its model, its tokens and
its dollars, then the totals by kind; every shell command that sleeps, lists or finds, and every
memory written; and, for each planner `--apply` run, how many spawns followed it and how many of
those the harness refused at its concurrency limit.
"""

import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

#: $/MTok: input, cache read, output; Haiku 5.5's second row is for a prompt over 100,000 tokens.
_PRICES: Final = {
    "claude-opus-5-5": ((4.00, 0.20, 20.00), (4.00, 0.20, 20.00)),
    "claude-sonnet-5-5": ((2.00, 0.20, 10.00), (2.00, 0.20, 10.00)),
    "claude-haiku-5-5": ((0.10, 0.01, 0.50), (0.50, 0.05, 2.50)),
}
_LONG_PROMPT: Final = 100_000
_WRITE_5M: Final = 1.25
_WRITE_1H: Final = 2.0
_SKILL_OPENING: Final = "Base directory for this skill:"
_ITEM_OPENING: Final = "Root:"
_WAITING_WORDS: Final = ("sleep", "find ", "ls ")
_REMEMBER: Final = "mcp__zikaron__zikaron_memory_remember"
_APPLY_RUN: Final = "code-knowledge plan"
_REFUSAL: Final = "Concurrent subagent limit reached"


@dataclass
class _Agent:
    kind: str = "other"
    tokens: dict[str, list[int]] = field(default_factory=lambda: defaultdict(lambda: [0, 0, 0, 0]))
    dollars: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    waits: list[str] = field(default_factory=list)
    memories: list[str] = field(default_factory=list)
    #: Per planner `--apply` run: spawns issued, and spawns refused at the concurrency limit. The
    #: first entry holds whatever precedes the first such run.
    batches: list[list[int]] = field(default_factory=lambda: [[0, 0]])


def _price(model: str, usage: dict[str, object]) -> float | None:
    if model not in _PRICES:
        return None

    def count(key: str) -> int:
        value = usage.get(key)
        return value if isinstance(value, int) else 0

    split = usage.get("cache_creation")
    split = split if isinstance(split, dict) else {}
    one_hour = split.get("ephemeral_1h_input_tokens")
    one_hour = one_hour if isinstance(one_hour, int) else 0
    written = count("cache_creation_input_tokens")
    prompt = count("input_tokens") + written + count("cache_read_input_tokens")
    short, long = _PRICES[model]
    input_price, read_price, output_price = long if prompt > _LONG_PROMPT else short
    return (
        count("input_tokens") * input_price
        + (written - one_hour) * input_price * _WRITE_5M
        + one_hour * input_price * _WRITE_1H
        + count("cache_read_input_tokens") * read_price
        + count("output_tokens") * output_price
    ) / 1e6


def _kind(content: object) -> str:
    if isinstance(content, str) and content.startswith(_SKILL_OPENING):
        return "orchestrator"
    if isinstance(content, str) and content.startswith(_ITEM_OPENING):
        return "documenter"
    return "other"


def _note_tool_uses(agent: _Agent, content: list[dict[str, object]]) -> None:
    for block in content:
        if block.get("type") != "tool_use":
            continue
        arguments = block.get("input")
        arguments = arguments if isinstance(arguments, dict) else {}
        if block.get("name") == "Bash":
            command = str(arguments.get("command", ""))
            if any(word in command for word in _WAITING_WORDS):
                agent.waits.append(command[:100])
            if _APPLY_RUN in command and "--apply" in command:
                agent.batches.append([0, 0])
        if block.get("name") == "Agent":
            agent.batches[-1][0] += 1
        if block.get("name") == _REMEMBER:
            agent.memories.append(str(arguments.get("gist", ""))[:160])


def _agent(path: Path) -> _Agent:
    agent, seen = _Agent(), set()
    first_user = True
    for line in path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        message = record.get("message") or {}
        if record.get("type") == "user" and first_user:
            first_user = False
            agent.kind = _kind(message.get("content"))
        if record.get("type") == "user" and _REFUSAL in json.dumps(message.get("content")):
            agent.batches[-1][1] += 1
        if record.get("type") != "assistant":
            continue
        _note_tool_uses(agent, message.get("content") or [])
        if message.get("id") in seen:
            continue
        seen.add(message.get("id"))
        model, usage = str(message.get("model")), message.get("usage") or {}
        tokens = agent.tokens[model]
        for index, key in enumerate(
            (
                "input_tokens",
                "cache_creation_input_tokens",
                "cache_read_input_tokens",
                "output_tokens",
            )
        ):
            value = usage.get(key)
            tokens[index] += value if isinstance(value, int) else 0
        dollars = _price(model, usage)
        if dollars is not None:
            agent.dollars[model] += dollars
    return agent


def main(session: Path) -> None:
    totals: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    for path in sorted((session / "subagents").glob("*.jsonl")):
        agent = _agent(path)
        counts[agent.kind] += 1
        for model, (inp, written, read, out) in agent.tokens.items():
            dollars = agent.dollars.get(model)
            price = "no price" if dollars is None else f"${dollars:.4f}"
            print(
                f"{agent.kind:12} {model:18} input {inp:>7,} cache-write {written:>9,} "
                f"cache-read {read:>11,} output {out:>8,}  {price}  {path.stem}"
            )
            totals[agent.kind] += dollars or 0.0
        for command in agent.waits:
            print(f"    shell: {command}")
        for gist in agent.memories:
            print(f"    remembered: {gist}")
        if any(spawned for spawned, _refused in agent.batches):
            listed = ", ".join(f"{spawned}/{refused}" for spawned, refused in agent.batches)
            print(f"    spawns/refused at the limit, per --apply run: {listed}")
    for kind, dollars in sorted(totals.items()):
        print(f"total {kind}, {counts[kind]} of them: ${dollars:.2f}")


if __name__ == "__main__":
    main(Path(sys.argv[1]).expanduser())
