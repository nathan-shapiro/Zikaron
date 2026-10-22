# M40's toy run on Warp, and the first run in the field on LeibaTrader

Two documentation runs of the same build. **The toy run** (`design/code-knowledge.md` §7) documents
Warp's `app/src/terminal`, headless, for the evaluation to read. **The first run in the field**
documented LeibaTrader's `sugar-leiba` interactively, where the operator installed the build to use
it in real work (operator, 2026-10-16).

## 1. The toy run: Warp's `app/src/terminal`, headless

**Run 2026-10-17 UTC (2026-10-16 local) by memory-researcher**, in a clone of `warpdotdev/warp` at
`b80b4e3e0`, installed with `--components memory --model claude-sonnet-4-6` over a fresh store;
Claude Code 2.1.292; the `-p` session on `claude-haiku-4-5-20251001`, the orchestrator and every
documenter on `claude-sonnet-4-6` at the efforts the install sets (high and medium). The command,
from the clone:

```bash
CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0 claude -p --model haiku --permission-mode bypassPermissions \
  --output-format stream-json --verbose "/zikaron-document-code app/src/terminal --include '*.rs'"
```

Read from its stream-json output and the session's subagent transcripts (session `1566de1e-…`,
orchestrator `agent-af25e697…`, 389 documenters). **A slice of 20 went first**, in an earlier
session (`38775782-…`): 280 s, a document's median 74,642 tokens and 41 s, no permission prompt
under `bypassPermissions`.

### What was documented

**406 sources and the module README, 407 documents**, of the module's 407 `*.rs` files; the 160
files the glob leaves out are `ref_tests/data` fixtures. **The 407th, `view.rs`, has no document**:
at 1,275,888 bytes it is over `knowledge_max_file_bytes`, 1 MiB by default, so the walk skips it
and the planner counts it under `skipped.over_size_cap` — and the run's report never mentioned it.
It is the module's largest file, `TerminalView`'s, and a truth file for 4 of the evaluation's 16
issues. The planner's last run reported `up_to_date: true`, `remaining: 0`; nothing was given up
on, and no spawn was refused at the concurrency limit. The
documents total 3.3 MB, the README alone 86,550 bytes, since its `## Files` lists every source.
Registered as `code-knowledge/app/src/terminal`; the build after the final refresh indexed 407 files
in 300 s.

**Two documents were written twice, both because a model mis-copied the planner's 40-character
blob.** For `cli_agent_sessions/listener/mod.rs` the orchestrator wrote a 38-character blob into the
spawn — the planner had printed the full one — and the next run judged the document invalid and
listed it again; for `view/context_menu.rs` the documenter changed one digit of the 40 it was
given, and a later run judged the document stale. The planner caught both, as designed, at one
extra documenter each: 2 in 389 documenter runs. **No source was modified**: `git status` shows only
the installer's `.mcp.json`.

### Time

| | |
|---|---|
| orchestrator, first record → report | **57 min 30 s** (01:51:42 → 02:49:12 UTC) |
| a batch of 20, planner to planner | 1.5 to 3.5 min |
| a documenter's run | median 34 s, 90th percentile 70 s, longest 428 s |
| knowledge base build after the refresh | 300 s, 407 files |

### Tokens

The four `usage` fields, each API message counted once:

| | input | cache writes | cache reads | output |
|---|---|---|---|---|
| 389 documenters | 2,085 | 6,614,723 | 34,606,465 | 959,116 |
| orchestrator, 50 API calls | 52 | 373,104 | 3,932,056 | 110,304 |

A documenter's median, all four fields summed: **94,019 tokens** (90th percentile 158,050, the
largest 1,079,163), its output a median of 1,979. That is half LeibaTrader's 191,243, under another
model and in a project with no `CLAUDE.md`; which of the two accounts for it is not separated.

**The `-p` result's `usage` is all zeros, and its `modelUsage` counts the subagents.** The session
made no model call of its own (`num_turns: 0`): the skill forked at once. Its `modelUsage` for
`claude-sonnet-4-6` — 8,031 input, 6,988,190 cache writes, 38,842,181 cache reads, 1,092,286 output,
$54.27 at list price — matches the subagents' sums within 3% on every field but input. So §7's
question is answered: `usage` does not count a forked skill's subagents, and `modelUsage` does.

**The orchestrator's context grew about 525 tokens a document**, some 10,500 a batch, from 22,778 to
158,119, where the harness compacted it — at 02:20:11 to 36,166, and again at 02:41:19 from 148,942
to 49,424 — and each time it resumed by running the planner, as the operator expected (2026-10-16).
A document's spawn call is a median 515 characters and its hand-back result 811. That is under a
third of LeibaTrader's 4,400 a document, which also carried a launch confirmation and a second
completion notice; headless, a foreground spawn's hand-back returns as its tool result and nothing
else arrives. After the second compaction the orchestrator read the planner's output from the file
the harness had spilled it to.

### Memory

**No documenter called a Zikaron tool** — their calls were `Read` 597, `Write` 389, `Grep` 365,
`Glob` 104 — and the orchestrator called `knowledge_status` and `knowledge_refresh` once each. The
store's `memory` table is empty. So this run did not search memory at all, where LeibaTrader's made
one search.

### The report

It opened *"The `app/src/terminal` module is fully documented."*, naming the module and that it is up
to date in its first line and the knowledge base in a later bullet; it said nothing of
`git_mode_effective`, which was `all`.

## 2. The first run in the field: LeibaTrader's `sugar-leiba`, interactive

**Run 2026-10-16/17 by the operator**, interactively in `~/Trading/LeibaTrader` itself — installed
there before M40 landed (operator, 2026-10-16; `design/code-knowledge.md` §7) — under auto mode,
Claude Code 2.1.292, the orchestrator and every documenter on `claude-sonnet-5-5` (the install's
default `sonnet`). The skill was the version with batches of 20 issued together, and a spawn
refused for the harness's concurrency limit not counted as an attempt
(`design/code-knowledge.md` §5.2). Read from the session's transcript and its subagents'
(`~/.claude/projects/-home-nathan-Trading-LeibaTrader/86ba5119-…`, orchestrator
`agent-a6aeffd4…`). Two earlier runs that evening, with batches of 10 and of 32, are what found the
limit and the spawn latency below; their documents were superseded by this run.

### What was documented

`/zikaron-document-code sugar-leiba`: **197 sources and the module README, 198 documents** — the
123 Scala files under `src/main`, the 59 under `src/test`, and 15 others (build files, `.conf`,
`logback` XML). The planner skipped 542 gitignored files, one denied extension and seven pruned
directories. **Every item succeeded on its first attempt**; nothing was given up on, nothing was
unverifiable, foreign or unplaceable. The README's `## Files` lists exactly the 197 documented
files. Registered as `code-knowledge/sugar-leiba`.

### Time

| | |
|---|---|
| orchestrator, first record → report | **23 min 20 s** (23:58:17 → 00:21:36 UTC) |
| knowledge base build | **1 min 47 s** (00:21:32 → 00:23:19), 198 files, 790 chunks, 845,013 bytes |
| planner runs | 13 |
| spawns | 200 — 198 documenters and two refused at the limit of 20 |
| a documenter's run | median 19 s, 90th percentile 37 s, longest 109 s |
| spawn call → documenter's first record | median 19.2 s, longest 41.7 s |

**The spawn latency is the harness, not the API.** The orchestrator wrote a batch's 19 or 20 spawn
calls into one message, about 2.1 s a call, and the harness started every documenter only once that
message was complete; a documenter's first model reply then followed its start by 2.3–4.8 s. In
the batch-of-32 run, the 20 accepted documenters all started at +66.2 s, as the last refused call
was written. One spawn per message would start each sooner, at a turn per spawn over the context
measured below — weighed and declined (operator, 2026-10-16).

**Claude Code refuses a spawn past 20 concurrent subagents**: *"Concurrent subagent limit reached.
You can run 20 subagents at once. Do not retry. If the user wants more concurrent subagents, ask
them to increase CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS."* — twelve of 32 in the batch-of-32 run.

### Tokens

The four `usage` fields, each message counted once:

| | input | cache writes | cache reads | output |
|---|---|---|---|---|
| 198 documenters | 1,874 | 9,054,184 | 36,502,883 | 500,229 |
| orchestrator, 235 turns | 790 | 2,601,125 | 55,141,704 | 38,287 |

A documenter's median, all four fields summed: **191,243 tokens**. Its first call carries about
44,000 tokens of fixed context — its tools, Claude Code's system prompt and LeibaTrader's own
instructions — **of which only 14,042 are shared between documenters**: the first batch's twenty,
starting cold and together, read none of it from the cache, and every documenter of the ten later
batches read exactly 14,042 and wrote about 30,000 afresh. So roughly 30,000 tokens of each
documenter's start are paid at the cache-write rate, once per document; what keeps them from being
shared is not visible in the transcripts.

**The orchestrator's context grew from 45,118 to 431,892 tokens**, a median of 253,930 a turn —
about 2,000 tokens a document. **That is the harness's framing of each spawn, not the documenter's
answer**, which is one line, a median of 154 characters. Per document the orchestrator's transcript
gains about 4,400 characters that reach its context: the spawn call (about 630, mostly absolute
paths and the front matter), the launch confirmation (1,060), the hand-back message with its safety
framing (1,450) and a second completion notice (1,270). The documenter's start hook output, about
4,200 characters each, is recorded in the orchestrator's transcript and is not in its context.

### Memory

Across the orchestrator and 198 documenters: **one memory search and no write.** No memory in the
store was created during the run. The documenters had the full memory grant and the write policy at
their start (`research/forked-skill-probe.md`), and seeded nothing.

### How the corpus was used

The operator then had LeibaTrader's own `leiba-engineer` trace the market-data flow end to end from
the documents alone, which it did (operator, 2026-10-16). Its nine searches of
`code-knowledge/sugar-leiba`, in bursts of two to four, each named the corpus and asked for 3 to 8
results, and **were mostly identifiers** — *"IqFeedTickActor historical gap fill FirstTrade spawn
child tickStore subscriber push"*, *"OrchestrationActor subscribes to tick actor forwards ticks to
execution strategy"*, *"application.conf iqfeed host realtime-port historical-port keys"* —
unlike the playground's plain questions. Every top result was the file the query named or
described, and every result read `fresh`.

## 3. The edit, rename and deletion re-runs

2026-10-16, in a scratch `cp -a` of the clone once it reported `up_to_date`, its store files copied
with it since the planner refuses a project with no store. A dry run first reported `up_to_date:
true`, no work, `git_mode_effective: all`, `skipped: {over_size_cap: 1, excluded_by_glob: 160}`.
Then three changes at once: a line appended to `find/model.rs`; `git mv cli_agent.rs
cli_agent_renamed.rs`, with `mod.rs`'s declaration edited to keep the module name; and `git rm
ssh/util.rs`.

| | the dry run listed | `--apply` did |
|---|---|---|
| the edit | `find/model.rs` as `stale` work | removed its document, then listed it |
| the rename | a move, `cli_agent.rs.md` → `cli_agent_renamed.rs.md` | moved it: `zikaron-source` and the title name the new path, the body is byte-identical |
| the deletion | `ssh/util.rs.md` to remove | removed it |
| the declaration edit | `mod.rs` as `stale` work | removed its document, then listed it |

A second dry run listed the same two work items and nothing to remove or move, with `readme: null`,
since file work remained; `up_to_date` was `false` throughout. **Three documents still name
`app/src/terminal/cli_agent.rs`** — two `Depends on:` lines and the README's entry — and the two
importers' documents stay `fresh`, since their sources did not change: the dangling-`Depends on:`
gap `design/code-knowledge.md` §8 accepts, seen on Rust as it was described for Scala. The README
is listed again once the file work is done.

## 4. The wrong-claim sample

**It describes §1's documents, the prompt's first version**: nine of the ten were written again
afterwards, under §5–§8's rules — all but `terminal_size_element.rs` — so the sample is evidence
about that version, not about the corpus the evaluation reads (§10).

2026-10-16, by the build session: ten of the toy run's 406 file documents drawn with
`random.Random(20261016).sample` over their sorted paths, each read against its source and, for
every claim of which test pins a behavior, against the tests. **Six wrong claims in four documents,
every one a detail; none would send a reader to the wrong file.** Every test a document names
exists and does what the document says; one claim that branches are uncovered is borderline.

| Document | Wrong claims, each beside what refutes it |
|---|---|
| `history/up_arrow.rs` | *"Entries whose normalized command text appears in `IgnoredSuggestionsModel` … are dropped"* — the filter passes the raw `entry.command`, and `is_ignored` matches it exactly (`ignored_suggestions_model.rs:126–131`). *"When `AISettings` is absent … prompts are always included"* — still only when `config.include_prompts` (lines 142–148) |
| `input/universal.rs` | none |
| `model/session_tests.rs` | *"(and its sibling `sessions.rs`)"* — no such file; `Sessions` is in `session.rs:113`. *"the others use `Session::test()`"* — the injection test builds `Session::new` from a `SessionInfo` (line 119), the event tests use `Sessions::new_for_test()` |
| `resizable_data.rs` | none |
| `shared_session/share_modal/style.rs` | none |
| `shell_recovery.rs` | none; *"No test covers the `used_fallback_directory = true` branch or the partial-output-present branch directly"* is borderline — the one test runs both and asserts neither |
| `terminal_size_element.rs` | *"otherwise returns the child's own result"* — with no z-index it returns `false` even when the child handled the event (lines 73–76) |
| `view/inline_banner/notifications_error.rs` | none |
| `view/link_detection_tests.rs` | none |
| `view/ssh_file_upload.rs` | *"if the metadata call fails (e.g., the path does not exist at render time)"* — the check runs when `start_file_upload` builds the command, not at render |

**The dependency lines are where the documents are weakest, and that is measured over the whole
corpus rather than the sample.** Of the 2,544 paths the bullets under `## Dependencies` name,
**752 (29.6%) do not exist**: 526 of the 1,720 in the template's `- Depends on:` form, in 162
documents, and 226 of the 824 in the 882 bullets that leave it, 387 of those hedged — *"(or
nearby)"*, *"(or equivalent)"*. Among the template-form misses, 231 write `x.rs` for a module at
`x/mod.rs` and 70 the reverse, and most of the rest follow a re-export to a guessed path —
`pub use warp_terminal::shell` in `terminal/mod.rs` becomes `app/src/terminal/shell.rs`.
**LeibaTrader's Scala documents, written by `claude-sonnet-5-5`, miss 7 of 617 (1.1%)** — though
451 of its 619 bullets leave the template's form too. The documenter's prompt already says *"A
file you could not find in the project is not a dependency you can name"*; on Rust at `effort:
medium`, under `claude-sonnet-4-6`, it does not hold, and which of the language and the model
accounts for the difference is not separated. Re-derive with `python
experiments/m40_dependency_lines.py <project root> <module's documents directory>`.

## 5. The dependency-path trial, and an orchestrator that stopped waiting

2026-10-16, after the operator's go. The documenter's dependency rule became a step — *"Every path
is one you saw exist: before you write the section, list or open each one"*, the file that
declares what an import names rather than the import spelled as a path, no hedges — and the clone
was installed again. Twenty of the 251 documents naming a missing path were drawn with
`random.Random(20261016).sample` over their sorted paths, removed, and the skill run headless as in
§1 (session `5f2cb870-…`, $6.20 by `total_cost_usd`).

| The 20 documents | before | after |
|---|---|---|
| dependency paths naming no file | 73 | 24 of 217 |
| bullets out of the template's form | 132 | 0 of 217 |
| hedged bullets | — | 0 |
| documents with a missing path | 20 | 4 |

**Sixteen of the twenty now name no missing path; fourteen of the 24 misses are one document's**,
`model/terminal_model.rs`, a 142,567-byte source whose document still lists sibling modules —
`ansi.rs`, `blockgrid.rs`, `selection.rs` — that live elsewhere; the rest are 5, 4 and 1 in three
others. The documenters now search for each dependency's file before writing it, which the
transcripts show as searches returning the real location.

**The orchestrator broke the loop.** It spawned all twenty documenters without
`run_in_background` — in §1 it passed `run_in_background: false` on all 389 — so headless, where
the model chooses and the default is background (`research/claude-code-background-subagents.md`
§Q3), each answered *"Async agent launched"*. It then spawned a 21st, foreground documenter
described as *"Wait marker - will receive completions"*, and ended its turn with *"Waiting for all
20 background documenters to complete before running the planner again."* Under `-p` a fork that
ends its turn is finished: the documenters' completions reached the launching `haiku` session
instead, which answered each with a progress line, 21 `result` messages in all, and **the
orchestrator never ran the planner again, refreshed the corpus or reported**. All twenty documents
were written, and a dry run reports `up_to_date`; a run of more than one batch would have stopped
after its first. The skill now asks for the foreground by the parameter's name and not to end the
turn while a spawn runs (`design/code-knowledge.md` §5.2 step 2); interactively the parameter is
absent and waiting works, as `research/forked-skill-probe.md` measured.

## 6. The re-documentation, and `view.rs`

2026-10-16/17, on the operator's go once §5 held: the skill installed again with the spawn fix, the
clone's `.zikaron/config.toml` setting `[indexing] knowledge_max_file_bytes = 5242880` for this
experiment (operator), and the other 278 affected documents removed. The planner listed 279 items,
`view.rs` among them, and the run (session `b4d6861d-…`) took **58 min 14 s** and $70.08 by
`total_cost_usd`, ending `up_to_date` with 408 documents — 407 sources and the README, which the
new path set listed again. **All 280 documenters ran in the foreground**; the orchestrator's
context was compacted once and it went on.

| Corpus-wide, after | |
|---|---|
| dependency bullets | 2,444 |
| out of the template's form | 0 |
| in it, naming no file | **180 (7.5%), in 65 documents** — from 752 of 2,544 (29.6%) |

**The step doubles a document's cost.** Paired by source over the 208 files both runs documented
by the same description, a documenter's median, all four fields summed, went from 93,677 tokens
to 208,777 — **2.09×** — with the model, the effort and the file unchanged; the run's median
wall-clock a documenter, unpaired, was 55 s against §1's 34 s. That is the price of searching for
each dependency before naming it.

**`view.rs` is documented in part, and its document does not say so.** The file is 30,181 lines
with about 750 `fn` declarations; its documenter read ten slices of it — the first default read,
then offsets from line 500 to about 29,330, some 3,000 lines in all — over 22 turns and 236 s,
1.27 million tokens, its context peaking at 83,736 with no compaction, and wrote a 31,567-byte
document whose Declarations list 106 functions. The prompt's *"You read the source whole"* cannot
be met by a file past the context window, and nothing in the document tells a reader which parts
were read.

**The report opened** *"Knowledge base refresh started. The run is complete."*, its second line
naming the module and *"documented in full"*; after its compaction the orchestrator did not keep
the first-line rule.

## 7. Two rules that did not bind on Sonnet 4.6

2026-10-17, on the operator's direction: the dependency rule became *search only where you are not
sure which file holds what an import names*, and a source too long to read whole must say in its
role line and Purpose that it is documented in part, with the line ranges read. The 65 documents
still naming a missing path after §6 — `view.rs` among them — were regenerated, with 11 other
`view.rs` documents that named none, which the selection's name match drew in (session
`c54edd8b-…`, 20 min 32 s, $16.14, `up_to_date`).

| The 77 documents | always searching (§6) | searching where unsure |
|---|---|---|
| dependency paths naming no file | 180 of 781 | **249 of 811 (30.7%)** |
| documents with a missing path | 65 | 65, the 11 that had none among them |
| a documenter's median, four fields summed | — | 86,375 tokens |

**Searching only where unsure is no step at all under this model**: 30.7% is §4's rate without
one, and the half-price documenter is §1's. The documenters were never unsure. **The partial rule
did not bind either**: `view.rs`'s documenter read lines 1–3,286 and about fifty near line 29,900
of 30,181, spent 2.0 million tokens, and wrote a 31,246-byte document whose role line and Purpose
say nothing of the rest. The operator's direction is to tune both rules for Sonnet 5.5, tested
separately, not for this model (2026-10-17). **The report** counted *"57 documents … across 4
batches (20 + 20 + 20 + 17)"*, which is 77.

## 8. Checking every path exists

2026-10-17, the operator's rule: *check every path exists before you write the section, and leave
out any that does not — the path, never the dependency*, a dependency whose file was not found
keeping its bullet by the module's name and the names used from it. The same 77 documents were
regenerated (session `37825855-…`, 21 min 52 s, $23.91, `up_to_date`); the partial-document rule
was unchanged.

| The 77 documents | always searching (§6) | where unsure (§7) | **checking existence** |
|---|---|---|---|
| dependency bullets | 782 | 813 | 653 |
| paths naming no file | 180 of 781 | 249 of 811 | **26 of 631 (4.1%)** |
| documents with a missing path | 65 | 65 | **8** |
| bullets naming a module, not a file | 1 | 2 | 22 |
| a documenter's median, paired over the 32 sources all three runs name alike | 221,466 | 94,568 | **296,441** |

**Existence checking is the most accurate and the dearest**: 4.1% missing paths, at 1.34× the
always-searching rule's tokens and 3.1× the unsure one's, paired. **Its second half binds
weakly**: 22 dependencies kept by name against some 130 fewer bullets overall — `model/
terminal_model.rs`'s document went from 30 dependencies to 20, dropping its 14 wrong paths
outright, real modules such as `ansi`, `blockgrid` and `selection` among them, which live in
`crates/warp_terminal` and are now named nowhere in its dependencies. **The partial rule held this
time**: `view.rs`'s role line ends *"This document describes the file in part (lines 1–3200,
27463–27463, 28982–29590 read in full; remaining method bodies located by search)"*, under the
prompt §7's run ignored. **The report** counted *"57 new documents … across 4 batches"* again,
for 77.

**Why it costs more** (operator's question, 2026-10-17): the documenter holds no shell, so each
check is a search call of its own — a median 11.9 against 2.0 — and each call is a turn that reads
the documenter's whole context again, a median of 9 API calls against 3. **In dollars the gap is
smaller than in tokens**, since cache reads are most of the sum and cost a tenth of input: a
documenter's median, at Sonnet 4.6's list prices, was $0.221 against $0.134 (1.65×), and the runs
$23.91 against $16.14 (1.48×).

## 9. One search for every path

2026-10-17: a single search can check them all — a brace pattern, `{src/a.rs,src/b.rs,src/b/mod.rs,
src/c.rs}`, returned only `src/a.rs` and `src/b/mod.rs` in a probe — so the rule now says to check
every path *in one search*, its pattern listing each candidate in braces, both files a module may
be. Six of §8's documents were regenerated (session `8fe83ac1-…`, 4 min 35 s, $3.25):
`model/terminal_model.rs`, which §8 had stripped of its wrong paths outright; three that still
named a missing path; and the two with the most dependencies.

| The six documents | §8, each path checked | one search |
|---|---|---|
| dependency bullets | 112 | 122 |
| paths naming no file | 18 | **0** |
| bullets naming a module, not a file | 0 | 4 |
| documenters' cost at list prices | $2.87 | $3.06 |

**More accurate, and no cheaper.** Every document now names only files that exist, and more
dependencies survive; but the documenters used brace patterns to explore directories —
`app/src/terminal/model/{ansi,block,blockgrid,…}` — beside single searches, not as one final check,
so their calls did not fall: three documents cost less, three more, $3.06 against $2.87 in all. Six
documents is a small sample, and the operator's direction is to tune for Sonnet 5.5.

## 10. The corpus the evaluation reads

The clone's documents as they stand after §9, the planner reporting `up_to_date` (2026-10-17;
operator: the evaluation reads them as they are). Which run last wrote each is read from the
documenters' `Write` calls in each session's transcripts, latest run winning.

| Written under | documents |
|---|---|
| the first prompt (§1, slice and full run) | 108 |
| searching every dependency (§5–§6) | 223 |
| checking each path (§8) | 71 |
| checking every path in one search (§9, the shipped rule) | 6 |
| **in all** | **408** — 407 sources and the README |

`experiments/m40_dependency_lines.py` over them: 2,325 dependency bullets, none out of the
template's form, 41 hedged; **9 of the 2,250 paths in the template's form name no file, in 5
documents** (0.4%). The first prompt's 108 are those §4's scan never flagged, so its documents in
the corpus name no missing path either way.

## 11. The README item, as the orchestrators relayed it

The skill had the orchestrator relay the planner's `readme` item whole, as JSON, and the item
carried every documented file's path and role line. **No Warp orchestrator did.** In the full run
(`warp-full.jsonl`) it wrote the item to `/tmp/terminal_readme_item.json`; in the re-documentation
(`warp-redoc.jsonl`) it pointed the README's documenter at Claude Code's own saved output of the
planner run, under `~/.claude/projects/`. Both told that documenter to read source files under
`app/src/terminal/` — *"read a representative sample of the source files"*, *"read representative
source files … as needed"* — which the README rule forbids. The list the item carried is the
README's `## Files` section, measured on disk from its heading to the end: 85,230 characters on
Warp, and 54,611 on LeibaTrader's `sugar-leiba`. `design/code-knowledge.md` §3.6 moved the list to a file
the item names, and dropped it from the README.

## 12. Haiku 5.5 documenters under an Opus orchestrator, on the playground

The playground's `playground/hello` — three sources, 27 lines, four tests — documented twice
(operator): on 2026-10-17 by Sonnet 5.5 throughout (the install's `sonnet` alias then), and on
2026-10-20 by `haiku` documenters under an `opus` orchestrator, the alias resolving to
`claude-haiku-5-5` on Claude Code 2.1.304. The earlier set was kept beside the project for the
comparison. Cost and waiting from the sessions' transcripts, by
`experiments/m40_run_cost.py ~/.claude/projects/-home-nathan-PythonPlayground/<session>`
(`03ce609d…` and `47e85c30…`), at list price:

| | documenters (4) | orchestrator | shell commands that waited |
|---|---|---|---|
| Sonnet 5.5 | $0.16 | $0.17 | `sleep 1`, `sleep 20; ls`, `sleep 30; ls` on the documents directory |
| Haiku 5.5, Opus 5.5 | $0.02 | $0.40 | none |

**At four documents the run cost more** — $0.42 against $0.33 — because the orchestrator's cost is
mostly its fixed context, which the documenters' 90% saving does not reach. On LeibaTrader's 198
documents the same prices on §2's recorded tokens predict the opposite: documenters $34.94 →
$1.75–8.74, the orchestrator $17.92 → $24.80.

**No wrong claim in either set**, each of the four Haiku documents checked against the source and
the tests. Haiku wrote 1.5–2× as much (`greeting.py.md` 2,691 bytes against 1,830), the extra
correct but partly low-value: the module docstring restated, imports listed as "not
declarations", a closed-stdout exception noted as untested, and sentences about what the document
does not cover. Where Sonnet stated a dependency's behavior, Haiku said it read it from the test
instead (`__main__.py.md`), having not opened the file it depends on. One sentence is imprecise —
`sys.exit` "executes whenever the module is loaded as `__main__`", where it runs on any import —
and its README names no module, where Sonnet's named both.

**The Opus orchestrator wrote one memory** about the documents directory the operator had deleted
for the run, its cause called unknown; the Sonnet orchestrator wrote none, there or on LeibaTrader
(§2).

## 13. A slot still held when the next batch goes out

LeibaTrader's `sugar-leiba` re-documented on 2026-10-20 by the configuration of §12, on Claude Code
2.1.304, the skill then issuing batches of 20. Spawns and refusals per planner `--apply` run, from
the orchestrator's transcript by `experiments/m40_run_cost.py`
(`~/.claude/projects/-home-nathan-Trading-LeibaTrader/d5e50cb7…`), read while the run went on:

| batch | 1 | 2 | 3 | 4 |
|---|---|---|---|---|
| spawns / refused at the limit | 20 / 0 | 20 / 1 | 20 / 1 | 19 / 0 |

**The first batch ran all 20**, so the forked orchestrator is not counted against the limit;
**every later batch of 20 had one spawn refused** — *"Concurrent subagent limit reached. You can run
20 subagents at once. Do not retry"* — which fits a documenter of the previous batch still holding
its slot after its result arrived. On Claude Code 2.1.292 the same skill had two refusals in 198
spawns (§2). After the second refusal the orchestrator chose 19 itself (*"For future batches I'll
just spawn 19 at a time"*), and its batch of 19 had none. With 20, a batch runs 19 anyway and the
refused item leads the next listing, so 19 costs no throughput; `design/code-knowledge.md` §5.2
sets the batch to 19 (operator, 2026-10-20).

**Haiku documenters revise their document, and reach for tools they lack.** From the same run's
documenter transcripts, against LeibaTrader's Sonnet 5.5 session of 2026-10-16/17 (§2, which holds
three runs' documenters), a document counted as written more than once when its `Document:` path
took a second write:

| | documenters | wrote the document more than once | calls to a tool not granted |
|---|---|---|---|
| Sonnet 5.5 | 441 | 14 | 5 `Edit` |
| Haiku 5.5, 96 into the run | 96 | 47 | 59 `Edit`; 35 the knowledge or memory verbs spelled `Mcp__zikaron__…`; 2 `Mutable_placeholder` |

Each refused `Edit` was followed by a read of the document and a whole rewrite, so Claude Code's
documenter is granted `Edit` (operator, 2026-10-20; `design/code-knowledge.md` §5.1). The
capitalized `Mcp__` names are Haiku's own: the harness refuses them as case-sensitive, names the
right spelling, and the next call uses it, so each costs one turn; no prompt names a tool, so
there is nothing to correct there.

**They searched the corpus they were rewriting.** 27 of the 96 documenters ran 41 knowledge
searches between them: 23 across every knowledge base, 11 naming `code-knowledge/sugar-leiba` —
the corpus the run was rewriting — and 7 naming others only. Queries named dependencies
(*"FileSystemBinaryStore"*, *"AdaptiveRenko Renko brick reversal"*), so a document's account of a
dependency could come from that dependency's own document, which reads `fresh` whether or not
what it depends on has moved. The documenter takes nothing from a code-knowledge base since
(operator, 2026-10-20; `design/code-knowledge.md` §5.1).

## 14. LeibaTrader's `sugar-leiba` by Haiku 5.5, against Sonnet 5.5's

§13's run, finished: 197 documents and the README, against the Sonnet 5.5 set of 2026-10-17 kept
beside the project (operator). Cost by `experiments/m40_run_cost.py` on session `d5e50cb7…`, the
Sonnet figures priced on §2's recorded tokens; paths by `experiments/m40_dependency_lines.py`:

| | Sonnet 5.5 throughout | Haiku 5.5 documenters, Opus 5.5 orchestrator |
|---|---|---|
| documenters | $34.94 | $2.49 |
| orchestrator | $17.92 | $15.24 — 8,993 output tokens, $0.18 of it |
| `Depends on:` paths in form / naming no file | 702 / 2 | 714 / 2 |
| document size, Haiku against Sonnet, median (10th–90th percentile) | | 1.49× (1.25–1.82×) |
| README | 4,829 bytes | 2,754 bytes |

**The run cost a third**, $17.73 against $52.86, and the Opus orchestrator less than Sonnet's: it
wrote 0.5M tokens to the cache where Sonnet's wrote 2.6M. Its output, a fiftieth of its cost, says
`effort: high` costs nothing that matters. It waited without a `sleep`, ran batches of 19 after
the two refusals of §13 and had none, and wrote two memories — the documents directory found
empty, which the operator had emptied for the run, and the slot held after a spawn returns —
which the operator retired after the run, so later runs start clean.

**Four of five sampled documents checked** (seed 20261020) against their sources, with the README;
the fifth, `strategy/ExpandingRenkoStrategySpec.scala`'s, was not reached:

- `model/PositionType.scala` (8 lines): both correct on the declarations; Sonnet's says no test
  references the type, where five specs do; Haiku's says it checked none, and adds a filler line.
- `build.sbt`: Haiku's says *"No `SugarLeiba` entry exists under `sugar-leiba/`, so that path
  names no directory on disk"* — the directory holds every source — and narrates its own search;
  Sonnet's is correct.
- `tick/iqfeed/IqFeedHistoricalTickActor.scala` (222 lines): every one of Haiku's fifteen behavior
  bullets holds, the first-batch offset arithmetic among them.
- `simulation/SimulationActor.scala` (284 lines): about fifteen claims checked, all hold — the
  sort, the child's name, the monthly-total flag, the P&L arithmetic and the test's 88.0 — one
  imprecise: the log line is "with two decimals", which only its dollar figure has.
- The README: Haiku's tells the module as a pipeline in four paragraphs where Sonnet's is a layered
  overview with build, configuration and tests; it says ticks *"are deduplicated and fanned out by
  the `orchestration` actor"*, while `DedupTickFlow` is referenced by no main source.

**Both of Haiku's wrong claims are ones nothing read supports**: an absence asserted from a search
that found nothing, and a flow inferred from a role line. The documenter now never writes that a
path or a name does not exist, and the README says how parts connect only as their documents state
it (operator, 2026-10-20; `design/code-knowledge.md` §5.1). Verdict (operator): a win, mostly on
cost.

## 15. A rewritten dependency, and the documents that name it

2026-10-21, on §14's corpus, written 2026-10-20 03:37. Since then
`strategy/zspreadscale/ZSpreadScaleStrategy.scala` has changed, committed in `509f3dc` and further
in the working tree: 138 lines added and 81 removed against `332aa44`. The instance-group trading
is rewritten — `simulateInstanceGroup` became `tradeInstanceGroup`, the veto quantity a supporting
index — `TradeState` and `PositionState` became `InstanceTradeState` and `InstancePositionState`,
and `InstanceGroupPositionState` is new. Eight documents name it in a `Depends on:` line; seven of
their sources did not change, so those seven read `fresh`:

| Document | What it says of the strategy |
|---|---|
| `gelt/GeltConfig.scala` | the `Config` type and its nested `TradeTimeThresholds`, `DesiredVolumeHeuristic`, `DynamicOptimizationMode`, `InstanceGroup`, `Iteration` |
| `zspreadscale/ZSpreadScaleOptimization.scala` | the `Config` types and the `priority` and `instanceNames` members it reads |
| `zspreadscale/ZSpreadScaleOptimizationExperimentApp.scala` | `Config`, `InstanceGroup.generate`, `Iteration`, `DynamicOptimizationMode` |
| `zspreadscale/ZSpreadScaleStrategyStore.scala` | the `VariantKey` and `Config` codecs; what `VariantKey.withName` does with an unknown name is left to the strategy's file |
| `gelt/bootstrap/ExecutionBootstrap.scala` | the class, constructed as the head strategy |
| `resources/logback.xml`, `resources/logback-container.xml` | the logger named by the class's full name |

**None holds a claim the change made false.** Each describes the strategy by what its file uses
from it, and none of that moved. The strategy's own document reads `changed`, and the eighth
dependent, `ZSpreadScaleSimulationApp.scala`, changed itself. One file, seven dependents, a day
and a half.

The reading (operator, 2026-10-21): a dependency is either a black box, whose change is an
implementation detail its users' documents do not describe, or its interface changes, and then so
does the code that uses it. What escapes both is a dependency that moves while its users' bytes do
not — a Scala file, a Rust file whose `mod` declaration keeps its name (§3), a C++ header found
through the compiler's include flags — and the string coupling the two logback files carry is the
same case. The per-dependency blob proposed 2026-10-16 is withdrawn on it.

Re-derive: `git -C ~/Trading/LeibaTrader diff --stat 332aa44 -- <path>`, then grep the corpus for
`` Depends on: `<path>` `` and read each match against the diff.

## 16. What the orchestrator's context is made of

2026-10-21, from §14's orchestrator transcript (`agent-aa8f578d1a4d31fe1` under LeibaTrader's
session `d5e50cb7`), Opus 5.5: 199 spawns, 267 API calls, its context 46,123 tokens at the first
call and 421,516 at the last. **Its tokens are cache reads**: 62,877,208 read, 496,734 written to
the cache, 8,993 output, 1,002 uncached input — reads 127 times the writes and 7,000 times the
output, so nearly all of its $15.24. A read is one call times its context, so the cost is the
number of calls times how large the context has grown.

**What each call added**, from the change in context between consecutive calls, grouped by exactly
what arrived between them:

| Between two calls | Times | Median tokens added | Whose text |
|---|---|---|---|
| a batch of 19 or 20 spawns | 10 | 14,654–14,711, about 750 a spawn | the spawn prompt, median 526 characters — `Root:`, `Source:`, `Document:` and the front matter — and the harness's launch result, 959 characters each |
| one documenter's hand-back | 194 | 482 | the report, median 131 characters (`written: <path>`), inside the harness's frame of about 1,300 |
| one task notification | 38 | 937 | the harness's, its result saying the report came as a message |
| a shell call — the planner, or a script over its JSON | 11 | 2,436, or 2,742 with notifications queued during it | the planner's |

**Zikaron's own text is about a tenth of each document's growth** — the prompt and the one-line
report against about 1,900 tokens a document — and both are already at their floor, so a briefer
prompt or report saves under a tenth of the reads. **The calls are the lever**: 232 of the 267 are
the orchestrator woken for one completion, and each reads the whole context to wait again. The
starting context, read on every call, is a fifth of the reads (267 × 46,123); the growth is the
rest.

Re-derive: for each distinct `message.id` among the transcript's `assistant` rows, sum
`input_tokens`, `cache_read_input_tokens` and `cache_creation_input_tokens` for the context; then
group the `user` and `attachment` rows between consecutive calls by kind.

## 17. Warp's module regenerated by Haiku 5.5 under Opus 5.5, for the evaluation

2026-10-21, by memory-researcher, on the operator's decision that the evaluation reads documents
written by the install's defaults, since the skill and the prompts moved after §1. **The Sonnet
4.6 corpus of §1–§10 is kept, not deleted, in `~/Zikaron-m40-archive/`**:
`warp-code-knowledge-sonnet46/` (the 408 documents), `warp-zikaron-sonnet46/` (the clone's store,
with the toy run's records and its config), and `warp-install-sonnet46/` (the agents and skills
that wrote them). The clone then got a fresh `.zikaron/` holding only the 5 MiB `config.toml`,
`zikaron init`, and this tree re-installed at the M40-5 commit with `--components memory` and no
`--model`; its five agent and skill files are byte-identical to `tests/fixtures/installed/claude-code/`.

**The run**, headless as §1, its stream in `~/Zikaron-m40/warp-regen55.jsonl` (session
`282c63b9-…`, Claude Code 2.1.306): the `-p` session on `claude-haiku-5-5` spawned
`zikaron-code-orchestrator` in the background and relayed its report when it ended, so the
spawned orchestrator of M40-5 held for a whole module headless. **56 min 34 s, $11.66 by
`total_cost_usd`** — documenters `claude-haiku-5-5` $4.89, the orchestrator `claude-opus-5-5`
$6.77 — against §1's Sonnet 4.6 run of 57 min and $54.27. Every source got a document: the
planner reports `up_to_date` over the module's 407 `*.rs` sources, 407 documents and the README,
and the corpus built `ok` with 408 files, 407 linked, 3,216 chunks. Two documenters answered with
the document's body instead of writing it; the planner listed both again and the second attempt
wrote each, and the orchestrator's one memory is that observation. One documenter's hand-back
reported the account connector's MCP instructions as text in its `Read` result — the case of
`research/m40-5-spawned-orchestrator-probe.md` §2, 1 hand-back of 407 — and no document carries
that text.

**What was checked**:

| Check | Result |
|---|---|
| front matter, the four sections, `zikaron-source-blob` equal to `git hash-object` | 407 of 407 |
| `Depends on:` paths | 3,086 backticked before the line's dash; two not found, `view_impl_tests.rs` a bare file name where a repository path belongs, and `telemetry.rs` a parenthetical beside `lifecycle/mod.rs`, which exists |
| length against the Sonnet 4.6 document of the same source | median 1.36× |
| `view.rs` | partial and says so in its role line; 208 `fn` bullets of the file's 750 `fn` lines, against Sonnet 4.6's 124 |
| the sixteen issues' numbers | none cited; the two hits, 9056 and 9145, are line numbers in `view.rs`'s index |
| issue, PR or bug wording | 145 hits in 42 documents, each an identifier, a constant or a source comment; the four issue numbers cited (9286, 9916, 11477, 13228) are all in the source |
| claims in 15666's two truth files, `cli_agent.rs` and `cli_agent_sessions/listener/mod.rs`, against the code (an Opus 5.5 subagent, one finding re-checked by hand) | about 190 checked; 3 wrong, 1 unsupported, no invented issue or fix |

**The wrong claims are of two kinds.** Two say no test pins a behavior that a test outside the
file's own test module does pin — `from_harness` in `app/src/ui_components/agent_icon_tests.rs`,
`supported_skill_providers` for `WarpTui` — so a *"no test covers"* line reads as broader than
what the documenter searched. One vouches that a file's comments match its code when a trait
comment names Codex alone and Grok shares the handler. The unsupported one cites a test as
pinning a case it never builds.

Re-derive the format, path and wording checks with `.venv/bin/python
experiments/m40_doc_sanity.py ~/Zikaron-m40/warp app/src/terminal
~/Zikaron-m40-archive/warp-code-knowledge-sonnet46`, and the cost from the stream's last `result`
record's `modelUsage`.
