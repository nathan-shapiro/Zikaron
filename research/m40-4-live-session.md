# M40-4's live session: the search reminder in a real Claude Code session

`design/build-plan.md` §M40-4 done-when 2. Claude Code 2.1.304, the main session and the subagent
on `haiku`, headless (`claude -p --permission-mode bypassPermissions --output-format stream-json
--verbose`), in a throwaway project under `~/ZikaronTesting/m40-4-live` carrying the M40-4 build's
install (`python -m zikaron.install --project . --harness claude-code`, run from the worktree's
`.venv`) and one corpus registered as `code-knowledge/src/mod` over a one-document directory. The
default interval, 300 s. A second project, `~/ZikaronTesting/m40-4-nocorpus`, carries the same
install and a store with no corpus.

## 1. What the session showed, in order

Prompt 1 asked for four steps, one tool call each; prompt 2 resumed the same session
(`--resume <id>`), so it fired `UserPromptSubmit` as a typed prompt does.

| Step | Call | Matched | Reminded |
|---|---|---|---|
| prompt 1, step 1 | main session, `Bash`: `grep -rn zzz_no_such_text src/mod` | nothing (exit 1) | **yes** |
| prompt 1, step 2 | main session, `Bash`: `grep -rn zzz_still_nothing src/mod` | nothing | no — within the interval |
| prompt 1, step 3 | subagent `searcher` (`tools: Grep, Read`, no `Bash`), first `Grep`, `path: src/mod` | nothing | **yes** — its own key, though its parent was reminded seconds before |
| prompt 1, step 3 | the same subagent, second `Grep` | nothing | no — within the interval |
| prompt 2 | main session, `Bash`: `grep -rn zzz_after_prompt src/mod` | nothing | **yes** — the prompt opened a new turn |

Each line the agent quoted back was the line the service built:

> Zikaron hook: the files this search covered are documented in the knowledge base
> code-knowledge/src/mod. zikaron_knowledge_search there finds what a file is for and what it
> depends on — a lead to check against the code.

No `hook.log` was written: nothing failed.

## 2. Whether the transcripts record the line

**Both do.** The session's transcript and the subagent's under `subagents/agent-<id>.jsonl` each
carry, for every reminded call, an `attachment` entry of type `hook_additional_context` whose
`content` is the line and whose `toolUseID` is the search's — beside a `hook_success` entry whose
`stdout` is the hook's JSON. An unreminded call has neither. So a reminder is attributable to the
call that earned it from the transcript alone, which is what §4's counter relies on.

## 3. The hook's wall time

One `zikaron-hook` process per call, fed a `PostToolUse` `Bash` payload for `grep -rn zzz src/mod`
under a fixed session label, 30 calls a project, on the busy host (load average 8–9), with no
bar:

| Project | Median | p90 | Max | What the process did |
|---|---|---|---|---|
| `m40-4-live`, its service serving | 104 ms | 107 ms | 107 ms | listing, connect, `health()`, `knowledge_remind`; the first call printed the line, the 29 after it were throttled |
| `m40-4-nocorpus` | 101 ms | 103 ms | 105 ms | the listing found no corpus database, and it exited |

**The process start is the cost**: the connect and the request add about 3 ms to it. So the
throttle saves the agent's context and nothing measurable of the turn's time, and a matched `Bash`
call in a project with no corpus costs what one in a documented project does. The figure agrees
with `research/m40-4-search-tool-use.md`'s ~95 ms start, measured on another day. The script is
`m40_4_hook_timing.py` in that session's scratchpad: a loop of `subprocess.run` around the hook,
`perf_counter` on each side.

**Where the ~100 ms goes**, medians of 20 runs on the same host: the bare interpreter (`python -c
pass`) 36 ms; importing the hook's modules about 65 ms more, of which `-X importtime` puts ~15 ms in
the editable install's finder, a development-install cost a `uv tool install` does not have. The
reminder path alone imports in 94 ms against `zikaron.hook.main`'s 96 ms, so importing per event
would save ~2 ms: the start is the interpreter and the shared core imports, not anything the
reminder adds. **It is paid on every call**, since Claude Code starts a hook process per matched
call, with the service up or not.

**Against the push hook**, from the `call` rows' service-side `duration_ms`, read read-only:
`memory_surface` on `~/Trading/LeibaTrader`, 1,212 answered calls, median 92 ms — so a push is
about twice the reminder's ~104 ms end to end — and `knowledge_remind` here, 35 calls, median
0.5 ms, max 2 ms. 248 of those pushes took 800 ms or more, and every one followed more than 30
minutes without a call, against 4% of the faster ones: the first push to a service restarted after
its idle stop, waiting on the model. The reminder has no such tail, since it never starts a service.

## 4. The quantity that later says whether the line earns its place

**How often a `zikaron_knowledge_search` reaching a reminded corpus follows a reminder within the
next few tool calls, against the same window after a search the throttle left unreminded:**

```
.venv/bin/python experiments/m40_4_reminder_followon.py --project <dir> [--window 5]
```

It reads the project's registry read-only, classifies every search in every transcript, subagents
included, with the hook's own reading of the call (`zikaron.hook.reminder._searched`, then
`corpora_reached`), takes a search as reminded when the transcript holds the reminder's
attachment for that call, and counts, in each class, the searches followed within the window by a
knowledge search whose scope reaches a corpus that search reached. **The documenter's and the
orchestrator's transcripts are left out**, by the `agentType` in the `.meta.json` beside each
subagent's transcript and the hook's own two names: the documenter searches the module it documents
and then its corpus by instruction, so it would fill the unreminded arm with searches no throttle
left alone. Over this session:

```
reminded    searches     3  followed within 5:     0  (0.0%)
unreminded  searches     2  followed within 5:     0  (0.0%)
```

The counts are the session's shape — three reminded searches and two the throttle left alone —
and the zero is the prompts', which allowed no other call; it verifies the instrument, not the
line. The number that decides anything comes from a project whose sessions navigate unfamiliar
code over many turns.

**The baseline before any reminder**, `~/Trading/LeibaTrader`'s transcripts on 2026-10-21, where
M40-4 is not yet installed, the documenter's left out:

```
reminded    searches     0  followed within 5:     0  (—)
unreminded  searches  1358  followed within 5:     4  (0.3%)
```

So unprompted, an agent there follows a search of a documented module with a knowledge search 4
times in 1,358 — the rate a reminded arm is later read against, in that project, whose agent
mostly edits files it already knows (`FINDINGS.md` §"Owed work").
