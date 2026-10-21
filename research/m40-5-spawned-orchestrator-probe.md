# A forked documentation run that ran in the foreground, and the spawn that replaces it

For M40-5 (`design/build-plan.md` §M40-5). Claude Code 2.1.304, except where §2a's table names
2.1.306.

## 1. The field run

2026-10-21, a scratch project of two modules, `go` and `console`, with the memory store
installed from this tree, and two interactive sessions working in it at once. In the first, the
user asked fifteen seconds apart for each directory to be documented, and the session's model
(Opus 5.5) invoked `/zikaron-document-code` once for each:

| | First invocation, `go` | Second, `console`, 15 s later |
|---|---|---|
| the `Skill` result | at once: *"launched (forked execution, running in the background)"* | after 57 s: *"completed (forked execution). Result: Still waiting on the `.gitignore` documenter."* |
| the fork's `meta.json` | `"requestShape":"background"`, `"name":"zikaron-document-code"` | `"requestShape":"foreground"`, no name |
| its spawns | 52 over the run, none refused | 19 issued, 18 refused: *"Concurrent subagent limit reached. You can run 20 subagents at once. Do not retry."* |
| how it ended | its report, 6 min after it started | its first turn's end: the one documenter that started handed back to the session, 10 s after its orchestrator had stopped |

The second orchestrator wrote nothing wrong: it waited for its one running documenter by ending its
turn, as the skill says. **A foreground fork ends at its first turn's end**, so that wait ended
the run. Nothing told it that it was in the foreground — every spawn of both forks answered
*"Async agent launched"*, and the second fork received no hand-back instruction, which both of the
field run's background orchestrators were given. The session noticed, recorded a memory,
and invoked the skill for `console` again once `go`'s report arrived; that run, in the background,
wrote its 37 documents in 4 min and registered the knowledge base.

**Claude Code documents the foreground**: a forked skill waits for its result regardless of its
`background` field *"when you invoke a forked skill while an earlier invocation of the same skill
is still running"* (`research/claude-code-background-subagents.md` §Q8(c)).

## 2. The probes

2026-10-21, a scratch project with a forked skill `probe-fork-a`, a second `probe-fork-b` (the same
agent, a different name), an agent `probe-forker` that spawns one `probe-sleeper` and answers when
it returns, and that sleeper, all on `haiku`. Each run drove an interactive `claude` in `tmux`, one
prompt typed and submitted, a second fifteen to twenty-five seconds later, and was read from the
transcripts and `meta.json` files it left.

| The second launch, while the first's spawn was still running | Shape of each | Did each wait out its own spawn? |
|---|---|---|
| the same forked skill again | both `background`, the second named `probe-fork-a-2` | not measured: neither sleeper handed back, and neither fork resumed after its sleeper ended |
| a different forked skill | both `background` | not measured: each sleeper's `sleep` went to the background (below) |
| **the session spawning `probe-forker` itself**, twice | both `background` | **yes**: each handed back `DONE one` and `DONE two` after its sleeper's 90 s |

**The same-skill case did not reproduce the field run's foreground.** In the probe the first fork
had ended its turn to wait, where in the field run the first orchestrator was mid-turn, running the
planner, when the second invocation came; that difference is untested.

**A probe's spawn must stay busy.** In the first runs the sleeper's `sleep 40` went to the
background and the sleeper ended its turn; its parent was then woken, told *"[handback-send-enforce]
Your report has not been delivered. Call SubagentHandback … now; the call ends your run"*, and
complied before its spawn finished. With the sleeper blocking in a foreground
`python3 -c "import time; time.sleep(90)"`, no parent was told to hand back, and the two the
session spawned handed back once their spawns returned. A documenter's turn is busy until it hands
back, so a documentation run is the second case.

**Headless, the built skill.** `tests/test_code_knowledge_claude_live.py`, 2026-10-21, against
M40-5's install: `claude -p '/zikaron-document-code'` with no argument, the session spawning the
orchestrator in the background and the orchestrator its documenters in the foreground, documented
the toy project whole to `up_to_date` and registered `code-knowledge`, in 67 s.

**A harness block a documenter took for the file's.** In the operator's interactive test of
2026-10-21, the README documenter's hand-back said the planner's `roles.md` *"contained an
embedded 'MCP Server Instructions' block asking for a Claude Docs document"*. It did not: the
`Read` result, 13,799 characters, carries no such text. Claude Code attached an
`mcp_instructions_delta` beside that result — the 1,893-character instructions of the account's
`claude.ai Claude Docs` connector — and every one of the 62 documenter transcripts read carries the
same block after its first tool result. No agent of a run holds that server's tools, and the
documenter ignored the text, as its prompt says of anything in `roles`.

## 2a. The operator's interactive test

2026-10-21, driven by the operator, in four copies of the field run's project, each installed
from this tree with `--components both` (`design/build-plan.md` §M40-5 done-when 5).

| Leg | Claude Code | What was asked | What happened |
|---|---|---|---|
| 1, two modules in two requests | 2.1.304 | *"Document module `go`"*, then *"Document module `console`"* 7 s later | one background orchestrator for `go`, `"requestShape":"background"`; the session said `console` was queued and spawned it 7 s after `go`'s report. `go`: 52 documents in 7 min, batches of 18, 18, 15 and the README's 1, no spawn refused, every documenter first time; `console`: 38. Both `ok` once indexed, and a question answered from the knowledge bases alone in three searches |
| 2, plain words naming one of two | 2.1.304 | *"update the documentation of console"* | `args: "console"`, one spawn; the report named `console` alone, up to date, nothing written |
| 3, the whole project in plain words | 2.1.306 | *"create code documentation"* | no arguments; the orchestrator ran `--module .` and reported 95 documents in 6 batches over 12 min, no spawn refused, every documenter first time, into `code-knowledge`, indexed in 45 s; a question answered from it in six searches. One Haiku documenter corrected its own one-line answer midway, *"written: … — no wait, the document path is …"*; its document was well formed and the orchestrator checked it before reporting |
| 4, a module whose path carries a capital | 2.1.306 | *"Document module `Console`"*, then *"update the code documentation"* | the first run wrote 37 documents in 4 min, batches of 18, 18, 1 and the README's, no spawn refused, into `code-knowledge/Console`, registered as `code-knowledge/console`; the second, with no arguments, took `Console` from the knowledge base's `root_path`, ran `--module Console`, and reported it up to date, as the same request did in a fresh session. The session's thinking at that spawn named a *"No module named"* error that no tool result, hook output or log of the run carries |
| 5, the slot | 2.1.306 | *"Document module `go`"*, in a fresh session, the installed orchestrator's batch set to 20 by hand | **the first batch of 20 had one spawn refused**, *"Concurrent subagent limit reached. You can run 20 subagents at once. Do not retry"*, so the spawned orchestrator holds one of the 20 and the batch stays 18 (`design/build-plan.md` §M40-5 done-when 5). The orchestrator waited for the 19 that started, ran the next batch with `--limit 19`, none refused, then 18 again as step 4 says, which listed the last 13; 52 documents in 5 min, the refused file written in the second batch, up to date. That batch of 19, issued as the first's last documenter reported, found no slot still held |

## 3. Reading

A forked skill's foreground is documented and was observed, but what triggers it was not reproduced,
and once in the foreground a run cannot wait for anything. **Both subagents the session spawned ran
in the background, each waited out its own spawn, and they overlapped without either noticing the
other.** That is the consolidation skill's shape (`design/harness.md` §"Consolidation ownership under
a shared MCP process"), and M40-5 gives the documentation skill the same one. Interactively, on
the built skill, every leg of §2a ran in the background to its report, and the one refused spawn
was waited past rather than ending the run.

Re-derive: the transcripts under `~/.claude/projects/<the scratch project>/`, each session's `Skill`
or `Agent` `tool_result` and each subagent's `meta.json`, `requestShape` and its last `SubagentHandback`.
§2a's transcripts were deleted with its four copies (operator, 2026-10-21), so its table is the
record.
