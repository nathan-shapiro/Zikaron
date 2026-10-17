# Can a subagent spawn a subagent? Claude Code and kiro-cli, measured

**Probed 2026-10-13**, for `design/code-knowledge.md` §M40, which asks whether the producer's
orchestration can live in a subagent or must live in the session that invoked the skill.

| harness | version | the spawned agent's tools, as it listed them | did it spawn? |
|---|---|---|---|
| Claude Code | 2.1.287 | `Agent`, `Write`, `Read` — what its `tools:` line named | **yes**: `inner` ran and wrote `inner.txt` |
| kiro-cli | 2.28.0 | `read`, `summary`, `write` — `subagent` absent though its config lists it | **no** |

**Claude Code nests when the subagent's definition grants `Agent`.** The stream-json transcript
shows the inner agent's `Write` under a `parent_tool_use_id` that is the outer agent's own `Agent`
call, so it was a grandchild of the main session and not a sibling. Each `Agent` call returned
*"running in the background"* first and its result in a later notification, so the outer agent
must wait for the inner one rather than read its answer from the call. Depth beyond two was not
probed.

**kiro-cli strips the spawn tool from a spawned agent.** The same three-agent shape — `top` and
`outer` both configured with `subagent` in `tools` and `allowedTools` — gave `outer` no spawn tool,
and it said so. kiro also added a `summary` tool its config did not name.

**What it decides:** a producer that must run under both harnesses (D34) keeps its orchestration in
the session that invoked the skill, which then spawns documenters one level deep. That shape works
on both; a nested orchestrator would work on Claude Code only.

## Re-derive

Claude Code — in a scratch `git init` directory, `.claude/agents/outer.md` with
`tools: Agent, Write, Read` and a prompt to list its tools into `outer-tools.txt` and then launch
`inner`; `.claude/agents/inner.md` with `tools: Write`; both `model: haiku`. Then:

```bash
claude -p --model haiku --permission-mode acceptEdits --allowedTools 'Agent Write Read' \
  --output-format stream-json --verbose \
  'Use the Agent tool to launch subagent_type "outer" with the prompt "Run your probe."' > run.jsonl
ls inner.txt outer-tools.txt
```

kiro-cli — `.kiro/agents/{top,outer,inner}.json`, `top` and `outer` with
`"tools": ["read","write","subagent"]` and the same list in `allowedTools`, `inner` with `["write"]`,
all `"model": "claude-haiku-4.5"`, `outer` given the same prompt. Then:

```bash
kiro-cli chat --agent top --no-interactive --trust-all-tools \
  'Use your subagent tool to launch the agent named "outer" with the task "Run your probe."'
cat outer-tools.txt; ls outer-nospawn.txt
```
