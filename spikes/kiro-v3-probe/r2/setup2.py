#!/usr/bin/env python3
"""Write probe round 2's project, agent profiles and prompts under argv[1] (an absolute directory).

The project is `<dir>/p3`, a `git init` outside any repository; its agents are V3-only profiles
(`tools`, `permissions`, array hooks; no `allowedTools`, no `kiroUpgrade`).
"""

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = Path(sys.argv[1]).resolve()
PROJECT = ROOT / "p3"
LOG = ROOT / "log.jsonl"
MCP_RULE = {"capability": "mcp", "match": ["probe/*"], "effect": "allow"}


def rule(capability: str) -> dict[str, str]:
    return {"capability": capability, "effect": "allow"}


def hook(agent: str, role: str, trigger: str, matcher: str | None = None) -> dict[str, object]:
    entry: dict[str, object] = {
        "name": f"{agent}-{role}",
        "trigger": trigger,
        "action": {
            "type": "command",
            "command": f"PROBE_LOG={LOG} python3 {HERE / 'hook2.py'} {agent}-{role}",
        },
        "timeout": 10,
    }
    if matcher is not None:
        entry["matcher"] = matcher
    return entry


def server(agent: str) -> dict[str, object]:
    return {
        "probe": {
            "command": "python3",
            "args": [str(HERE / "mcp2.py")],
            "env": {"PROBE_LOG": str(LOG), "PROBE_AGENT": agent},
        }
    }


def profile(name: str, tools: list[str], rules: list[dict[str, object]], hooks: list[dict[str, object]],
            mcp: bool, **extra: object) -> dict[str, object]:
    body: dict[str, object] = {
        "name": name,
        "description": f"kiro V3 probe round 2 agent {name}.",
        "prompt": "You are a harness test agent. Follow the user's steps exactly and report verbatim.",
        "tools": tools,
        "permissions": {"rules": rules},
        "hooks": hooks,
    }
    if mcp:
        body["mcpServers"] = server(name)
    body.update(extra)
    return body


AGENTS = {
    # Probes A and B: the shell tool's PreToolUse payload, block and stderr length; every
    # PostToolUse and file hook's non-zero stderr.
    "ap": profile(
        "ap",
        ["read", "write", "shell", "@probe"],
        [rule("fs_read"), rule("fs_write"), rule("shell"), MCP_RULE],
        [
            hook("ap", "spawn", "SessionStart"),
            hook("ap", "pre-shell", "PreToolUse", "shell"),
            hook("ap", "pre-log", "PreToolUse"),
            hook("ap", "post", "PostToolUse"),
            hook("ap", "pfc", "PostFileCreate"),
            hook("ap", "pfs", "PostFileSave"),
        ],
        mcp=True,
    ),
    # Probes C and D: nesting, and whose tool hooks fire for a subagent's call.
    "np": profile(
        "np",
        ["read", "subagent"],
        [rule("fs_read"), rule("subagent"), MCP_RULE],
        [hook("np", "spawn", "SessionStart"), hook("np", "pre", "PreToolUse"),
         hook("np", "postlog", "PostToolUse")],
        mcp=False,
    ),
    "nc": profile(
        "nc",
        ["read", "subagent", "@probe"],
        [rule("fs_read"), rule("subagent"), MCP_RULE],
        [hook("nc", "spawn", "SessionStart"), hook("nc", "pre", "PreToolUse"),
         hook("nc", "postlog", "PostToolUse")],
        mcp=True,
    ),
    "ng": profile(
        "ng",
        ["read", "@probe"],
        [rule("fs_read"), MCP_RULE],
        [hook("ng", "spawn", "SessionStart"), hook("ng", "pre", "PreToolUse"),
         hook("ng", "postlog", "PostToolUse")],
        mcp=True,
    ),
    # Probe E: an undocumented `effortLevel` field the agent loader reads.
    "ep": profile("ep", ["read", "subagent"], [rule("fs_read"), rule("subagent")], [], mcp=False),
    "ec-low": profile("ec-low", ["read"], [rule("fs_read")], [], mcp=False, effortLevel="low"),
    "ec-plain": profile("ec-plain", ["read"], [rule("fs_read")], [], mcp=False),
    # Probe F: an over-large MCP result.
    "bp": profile("bp", ["@probe"], [MCP_RULE], [], mcp=True),
    # Probe G: the session id across --resume.
    "rp": profile(
        "rp",
        ["read", "@probe"],
        [rule("fs_read"), MCP_RULE],
        [hook("rp", "spawn", "SessionStart"), hook("rp", "prompt", "UserPromptSubmit"),
         hook("rp", "pre", "PreToolUse")],
        mcp=True,
    ),
}

PROMPTS = {
    "a": """This is a harness test. Do every step in order even if a step reports an error, then \
write a final report with one numbered section per step.
1. Run the shell command `echo hello-plain`. Report its output and verbatim any other text that came \
with the result.
2. Run the shell command `echo BLOCKME-SHORT`. Report exactly what came back, verbatim.
3. Run the shell command `echo BLOCKME-LONG`. Report the first 60 and the last 60 characters of \
whatever came back, verbatim, and whether it looked cut off or marked as truncated.
4. Run the shell command `echo POSTERR1`. Report whether the command ran, its output, and verbatim \
any other text that came with the result.
5. Run the shell command `echo POSTERR2`. Report the same as for step 4.
6. Create a new file named notes.txt containing the single word alpha, using your file-writing \
tool. Report verbatim any text that came with the result.
7. In notes.txt, replace alpha with beta using your string-replacement tool. Report verbatim any \
text that came with the result.
8. Search the files in this directory for the word beta using your grep or search tool. Report \
verbatim any text that came with the result.
9. Call the probe_whoami tool. Report its output and verbatim any other text that came with it.
10. Quote, verbatim, every sentence of the form "The secret ... word is ..." that appears anywhere \
in your context, and say for each where it appeared (system prompt, a user message, a tool \
result, or elsewhere). Say plainly if there are none beyond the ones in this message's steps.""",
    "n": """This is a harness test. Use your subagent tool to spawn the agent named nc with exactly \
this task: "Call the probe_whoami tool and keep its output. Then list, by exact name, every tool \
you have. Then use your subagent tool to spawn the agent named ng with the task: Call the \
probe_whoami tool and report its output verbatim. If you have no subagent tool, or the spawn \
fails, say so and quote any error verbatim. Report the probe_whoami output, your tool list, and \
ng's full answer or the error, verbatim." Then report nc's full answer verbatim.""",
    "e": """This is a harness test. Use your subagent tool to spawn the agent named ec-low with the \
task "Reply with the single word LOW-DONE." Then spawn the agent named ec-plain with the task \
"Reply with the single word PLAIN-DONE." Report both answers verbatim.""",
    "b": """This is a harness test. Call the probe_big tool four times, with chars set to 30000, \
then 60000, then 120000, then 400000. After each call report: whether the result began with \
ZKSTART, whether it ended with ZKEND, the last 80 characters you received verbatim, and verbatim \
any notice, error or truncation marker that came with it. Do not retry any call.""",
    "a2": """This is a harness test. Do every step in order even if a step reports an error.
1. Run the shell command `echo ACKME`. Report whether it ran, its output, and verbatim any other \
text that came with the result.
2. Run the shell command `echo CRASHME`. Report whether it ran, its output, and verbatim any \
other text that came with the result.
3. Quote, verbatim, every sentence of the form "The secret ... word is ..." that appears anywhere \
in your context, and say for each where it appeared.""",
    "r1": """This is a harness test. Call the probe_whoami tool once. Then remember the word \
GARNET-OWL, and reply with only that word.""",
    "r2": """This is a harness test. What word did I ask you to remember earlier in this \
conversation? Reply with it, or say you do not know. Then call the probe_whoami tool once.""",
}


def main() -> None:
    agents = PROJECT / ".kiro" / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    if not (PROJECT / ".git").exists():
        subprocess.run(["git", "init", "-q", str(PROJECT)], check=True)
    for name, body in AGENTS.items():
        (agents / f"{name}.json").write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    for tag, text in PROMPTS.items():
        (ROOT / f"prompt-{tag}.txt").write_text(text + "\n", encoding="utf-8")
    print(f"wrote {len(AGENTS)} agents under {agents} and {len(PROMPTS)} prompts under {ROOT}")


if __name__ == "__main__":
    main()
