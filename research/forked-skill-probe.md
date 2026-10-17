# Can a forked skill orchestrate subagents? Claude Code, measured headless

**Probed 2026-10-16, Claude Code 2.1.292**, for M40's amendment: the skill must not occupy the
session that invoked it, and `research/claude-code-background-subagents.md` §Q8 documents a skill
whose frontmatter sets `context: fork` and `agent:` as running in a subagent of its own.

| `agent:` | the fork's tools, as it listed them | `$ARGUMENTS` | spawned `inner`, foreground, and got its answer? |
|---|---|---|---|
| `outer`, a project agent with `tools: Agent, Bash, Write, Read` | exactly `Agent`, `Bash`, `Write`, `Read` | substituted | **yes** |
| `general-purpose` | `Agent`, `Bash`, `Edit`, `ListAgents`, `Read`, `ReportFindings`, `Skill`, `ToolSearch`, `Write` | substituted | **yes** |

**What it shows.** Under `claude -p`, `/probe-custom gamma delta` started the fork as a task
(`task_started`, description `/probe-custom`), and every one of the fork's messages carries
`parent_tool_use_id: "forked-command-probe-custom"` — so it ran in a context of its own, not in the
session. The named agent's `tools:` line is what the fork received, to the tool. The fork's `Agent`
call passed `run_in_background: false`, so `-p`, where fork mode is off, still offers the
parameter; the grandchild's answer came back as that call's result, and the fork went on and used it.
The session itself took no model turn (`num_turns: 0`): the `-p` result is the fork's final line,
returned after it ended, in 14.4 s.

**What it does not show.** An interactive session — whether it stays free while the fork runs
(documented: `background` defaults to `true`), and where a fork's or a grandchild's permission
prompt surfaces. Which `model` wins when both the skill and its agent set one: here both and the
session were `haiku`. No MCP server was configured.

## End to end, through the shipped skill

**Run 2026-10-16, Claude Code 2.1.292**, in a scratch `git init` project holding a three-file
package `pkg/`, after `zikaron init` and `python -m zikaron.install --harness claude-code
--components memory` from this tree: `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0 claude -p --model
haiku --permission-mode bypassPermissions --output-format stream-json --verbose
'/zikaron-document-code pkg'`.

- **It ended `up_to_date` in 39.1 s** (`duration_ms`), with three documents and the README
  written and the corpus registered as `code-knowledge/pkg` over `code-knowledge/pkg`; the
  session took no model turn, and the `-p` result was the orchestrator's report.
- **The fork ran as `zikaron-code-orchestrator`** on `claude-sonnet-5-5`, the install's default
  `sonnet`: all eleven of its messages carry `parent_tool_use_id:
  "forked-command-zikaron-document-code"`. It called `knowledge_status` before the first planner
  run, ran the planner three times, spawned each documenter with `run_in_background: false` — the
  three file items together, then the README — and called `knowledge_list` and `knowledge_add`.
- **Every subagent received the write policy at its start**, the orchestrator and the four
  documenters alike: each transcript holds the subagent policy's heading. None searched or wrote
  memory, over an empty store.
- **One departure from the skill**: the orchestrator passed `--project $PWD` rather than the root
  written out, which holds only while the shell has not changed directory. The skill now names that
  form as the one not to use.

## Interactive, in the playground

**Run 2026-10-16 by the operator**, in `~/PythonPlayground` under auto mode, after a reinstall from
this tree, with the module's documents missing and no knowledge base registered:
`/zikaron-document-code playground/hello` typed into a live session. Read from the session's
transcript and its subagents' (`~/.claude/projects/-home-nathan-PythonPlayground/c81f1b81-…`).

- **The session stayed free.** The invocation answered at once with *"Running in the background as
  @zikaron-document-code"*; the operator asked an unrelated question 13 s later, and the session
  answered it while the run went on.
- **The run took 45.1 s** (the fork's `duration_ms`), the orchestrator's own 33,221 tokens over 13
  tool calls. It read `.mcp.json` and ran `pwd -P`, called `knowledge_status` before the first
  planner run, passed `--project` with the root written out, spawned the three file items together,
  then the README, then ran the planner a third time, found the knowledge base absent with
  `knowledge_list` and created `code-knowledge/playground/hello`.
- **Every spawn ran in the background** — each `Agent` call answered *"Async agent launched"* —
  and the orchestrator waited for the results, which arrived as messages in its own context. No
  call carried `run_in_background` at all: fork mode removes the parameter (§Q3 of the
  background-subagents note), so the skill's *in the foreground* went unexpressed, and harmlessly,
  since no spawn was retried. Once,
  between them, it tried `sleep 60; ls` on the documents directory; the harness blocked the command
  and named `Monitor` instead, and the next message carried the results. The skill now says the
  result arrives as a message, not to poll for it.
- **Every final report went through the harness's handback tool**: each documenter's one line and
  the orchestrator's report were `SubagentHandback` calls, though no agent's `tools:` names it. The
  harness tells each subagent, at its start, that only that call reaches its caller.
- **Every subagent received the write policy at its start**; none searched or wrote memory.
- **The documenters ran at medium reasoning effort** — every one of their transcripts records
  `"effort":"medium"` — though the session ran `py-engineer` at `xhigh`: the documenter's
  definition then set no effort, so it took the harness's default for a subagent rather than the
  session's. The shipped definitions now set it (`design/code-knowledge.md` §5.1). `py-reviewer`, whose definition sets `xhigh`, ran at `xhigh` in the same session.
- **On a regeneration with the test-pin rule**, `greeting.py.md` named the pinning test for every
  behavior a test covers and marked the empty-string case untested, and made one wrong claim:
  that only the `sys.argv` path of `main` is exercised, where
  `test_main_prints_the_first_arguments_greeting` passes `argv` explicitly — the test the next
  bullet of the same document cites. The kind of error the toy run's sample reads for.
- **No permission prompt surfaced** — the planner's command, the documenters' writes and the
  Zikaron calls alike — as the operator observed and auto mode's rules predict.
- **The report reached the session, and the session relayed it in one line**, appended to its
  answer to the unrelated question: that the run had finished and written four files — without the
  knowledge base's name. The operator then asked whether the corpus was indexed. The skill's report
  now opens with one line naming the module, its state and its knowledge base, so a relay that
  keeps one line keeps those.

## How the session searched

The same session's knowledge searches, and its two earlier ones in the playground — the only
searches any agent there made; no subagent searched. Each query as sent, the corpus it named, and
what came back in rank order:

| query | corpus, `limit_per_kb` | results |
|---|---|---|
| *hello module what it does* | `code-knowledge` (the single corpus before the amendment), default | the README, then all three file documents |
| *what does main do with extra command-line arguments* | `code-knowledge/playground/hello`, 3 | `greeting.py.md`, `__main__.py.md`, the README |
| *greeting function default name world*, twice | the same, 1 | `greeting.py.md` — `changed` with the source edited, `fresh` once the edit was reverted |
| *which file makes the package runnable with python -m* | the same, 1 | `__main__.py.md` |

**What it shows**: questions in plain words more than identifier lists — two of the four distinct
queries named a declared name (`main`, `greeting`), and one was a keyword bag built to probe
staleness; every top result was the document a reader wanted. Once the corpus was per module the
agent named it on every call and lowered `limit_per_kb` on its own. n=4, one agent, a three-file
module: a reading of style, not of retrieval quality.

## Re-derive

In a scratch `git init` directory: `.claude/agents/inner.md` with `tools: Write`, told to write the
file its task names; `.claude/agents/outer.md` with `tools: Agent, Bash, Write, Read`; and
`.claude/skills/probe-custom/SKILL.md` with `context: fork`, `agent: outer`, `model: haiku`, whose
body lists the fork's tools into a file, runs `echo "$ARGUMENTS" > custom-args.txt`, spawns `inner`
in the foreground to write `custom-inner.txt`, and writes `inner`'s answer to `custom-done.txt`.
`probe-gp` is the same with `agent: general-purpose`. Then:

```bash
claude -p --model haiku --permission-mode bypassPermissions --output-format stream-json --verbose \
  '/probe-custom gamma delta' > custom.jsonl
cat custom-tools.txt custom-args.txt custom-done.txt
grep -o '"parent_tool_use_id":"[^"]*"' custom.jsonl | sort | uniq -c
```
