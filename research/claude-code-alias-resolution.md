# What Claude Code's model aliases resolve to

Recorded 2026-10-29 for M41-2, whose model parity rule (operator, 2026-10-29: *"both claude code and
kiro use the same models for the same tasks"*) pins each kiro agent to the id its Claude Code alias
resolves to. An alias moves when Claude Code's default for it moves, and no test can see that, so
each figure here names the build that served it.

| Alias | Resolved to | Claude Code | Evidence |
|---|---|---|---|
| `sonnet` | `claude-sonnet-5-5` | 2.1.308 | a memory-assistant run of 2026-10-28, whose definition says `model: sonnet`: all 132 of its assistant turns carry `"model":"claude-sonnet-5-5"` |
| `haiku` | `claude-haiku-5-5` | 2.1.306 | the documenters of `research/m40-toy-run.md` §17, installed with the shipped `haiku` default |
| `opus` | `claude-opus-5-5` | 2.1.306 | the orchestrator of the same run, installed with the shipped `opus` default |

The `sonnet` run is the subagent transcript
`~/.claude/projects/-home-nathan-Zikaron/88a28b6b-6a39-4979-98d3-310c3fa58daf/subagents/agent-a0d06ced31dedb807.jsonl`.
Its `.meta.json` names `agentType: memory-assistant`, and `.claude/agents/memory-assistant.md` says
`model: sonnet`. Its one other model line, `claude-opus-5-5`, is an `api-request-shape` record, not
an assistant turn.

## Re-deriving it

```bash
f=~/.claude/projects/-home-nathan-Zikaron/88a28b6b-6a39-4979-98d3-310c3fa58daf/subagents/agent-a0d06ced31dedb807
cat "$f.meta.json"                                    # agentType
grep -o '"version":"[^"]*"' "$f.jsonl" | sort -u      # the Claude Code build
grep -o '"model":"[^"]*"' "$f.jsonl" | sort | uniq -c # what the alias served
```

Transcripts are pruned by the harness, so this works only while that file lasts. A fresh
measurement is any subagent whose definition names the alias, read the same way.
