# Five owed measurements, taken on an idle host

2026-10-30, by memory-researcher, after `0.4.1` shipped, with the host idle (load average 0.7–0.8,
against the 8–9 of `research/m40-4-live-session.md` §3). Each section names the owed entry in
`FINDINGS.md` it answers, the number, and what it implies. The stores were read read-only
(`?mode=ro`, or a `VACUUM INTO` snapshot); nothing was written to a real store.

## 1. Q22's post-release marker rate

**Question** (Q22, `FINDINGS-archive.md` §"Closed with `0.3.0`"): does M34's headline rule — a gist
carries no verdict — bind on new `remember` writes, or only through the consolidator?

**Method.** `VERDICT_MARKER` from `experiments/m34_gist_replay.py` over every row with a `remember`
event, split at 2026-09-30, the day after `0.3.0` shipped. Current prose, so a later amend or a
consolidation rewrite is counted as it now reads.

| Store | Written since 2026-09-30 | Written before, same screen |
|---|---|---|
| `~/Trading/LeibaTrader` | **18 of 70 (26%)** — journal 17 of 63; journal never amended 14 of 46 (30%) | **160 of 284 (56%)**; Q22's baseline was 93 of 169 live long-term (55%) |
| `~/PythonPlayground` | 0 of 2 | — |
| `~/Memory`, `~/Dividends` | no `remember` since | — |

**Reading the 18.** The screen is a floor for reading, not a classifier: it counts *so*, *thus* and a
dash clause. Read one by one, twelve are a mechanism and its symptom (*"… keeps maxScore/minScore
(0,0) for life, so its trailing stop never fires"*) or a dash clause carrying a date, a source or a
rule (*"— measured on salvaged arm stores"*, *"— never only on the catastrophic days"*), which Q22
accepted as not verdicts. About four state the conclusion the record exists to support — *"erased
the D-1 picker's edge over it"*, *"so it did not block pre-09:30 trading after the resize"*,
*"first engine evidence for the operator's fractal-Z idea"*, *"runtime from one month misestimates a
full-range run"* — and two more are borderline.

**Implication.** The rate halved on the one store with traffic, so the write-side description binds;
the consolidator is not the only enforcement. The pre-release corpus still carries its rate — 79 of
150 live long-term rows written before 2026-09-30 are marked — which is what the corpus repair pass
is for, and it is no longer urgent.

## 2. A push against kiro's 3,000-character cut

**Question** (the owed "push block that fits by construction"): has any real push come near kiro
V3's 3,000-character hook cut?

**Method.** Every push the stores recorded, rebuilt from its `surface` rows (grouped by `op_id`, in
rank order) with `zikaron.core.retrieval.block`'s own `HEADER`, `PREAMBLE`, `ROW`,
`SUPERSEDED_LABEL` and `FOOTER`, measured in UTF-16 units as `exceeds_injection_budget` counts them.
Current gists, not the gists at push time. `hook.log` in every store holds no `push_oversize` line.

| Store | Pushes | Median | p99 | Largest |
|---|---|---|---|---|
| LeibaTrader | 5,710 | 1,617 | 1,755 | 1,811 |
| `~/Memory` | 1,250 | 1,622 | 1,874 | **1,921** |
| `~/Dividends` | 37 | 1,094 | 1,094 | 1,094 |
| `~/PythonPlayground` | 6 | 709 | 711 | 711 |

**Implication.** Of 7,003 pushes, none passes 1,921 units; the longest live gist in the four stores
is 246 characters. A five-row block carries 712 units besides its gists, so it reaches 3,000 only
with gists averaging about 458, which no store holds. The fix stays unbuilt until a `push_oversize` line appears.

## 3. K14's partial coverage

**Question** (the owed `zikaron-coverage: partial` field): how many sources in a real module does a
documenter fail to read whole?

**Method.** Every document in two code-knowledge corpora, its role line — the paragraph after the
title, where the prompt requires a partial document to say so — searched for *in part* or
*partial*, beside its source's length.

| Corpus | Documents | Partial by its role line | Sources over 2,000 / 5,000 / 10,000 lines |
|---|---|---|---|
| Warp's `app/src/terminal` (`~/Zikaron-m40/warp`, §17's run) | 407 | **4** — `view.rs` 30,181 lines, `input.rs` 17,395, `input_tests.rs` 11,028, `view_tests.rs` 11,011 | 18 / 4 / 4 |
| LeibaTrader | 196 | **0** — largest source 6,998 lines | 2 / 1 / 0 |

**Implication.** One document in a hundred, in the large Rust module, and exactly the four sources
over 10,000 lines; the 14 between 2,000 and 10,000 lines were documented whole by their role lines.
Each partial document already says so in its role line, which every search result shows, so a
front-matter field would add only a value to filter on.

## 4. Q17: `zikaron init` on a cold model cache

**Question** (Q17, `design/knowledge-index.md` §9): does the 10 s from spawn that
`lifecycle._HEALTH_POLL_DEADLINE_SECONDS` gives a cold service suffice, or does `init` owe a longer
deadline or a script the retry?

**Method.** Five `zikaron init` runs in fresh scratch projects with `FASTEMBED_CACHE_PATH` set to a
fresh empty directory — which the design ranks above the durable cache, so the real cache was never
touched — and five with the durable cache. Each cold run fetched the 66,465,124-byte
`model_optimized.onnx` over the network: the model is in no other local cache, and each cold cache
ended holding its own copy. Wall time of the command, from `date +%s.%N` on each side.

| Cache | Runs | Exit 0 on the first try | Wall time |
|---|---|---|---|
| cold | 5 | 5 | 3.41–3.66 s, median 3.51 |
| warm | 5 | 5 | 1.23–1.32 s, median 1.29 |

**Implication.** The fetch costs about 2.2 s here, and a cold `init` finishes with about 6.5 s of the
10 s to spare; a miss needs the 66 MB fetch to run below about 8 MB/s. Measured on one link: a slow
CI runner or a congested link can still miss, and then the documented retry works, since the
service keeps starting. No change is proposed.

## 5. The hooks' cost per call, and their share of a session

**Question** (the owed native hook client): what share of a session's wall time do the hooks take,
before rewriting the hook client in another language?

**Per call.** Thirty runs each of the installed entry points on the idle host, through
`subprocess.run` with `perf_counter` on each side, in a scratch project holding a `VACUUM INTO`
snapshot of LeibaTrader's store (408 memories) with its service up, the environment a Claude Code
session gives a hook (`CLAUDECODE`, `CLAUDE_PROJECT_DIR`, `CLAUDE_CODE_SESSION_ID`):

| Hook | Median | p90 | Max |
|---|---|---|---|
| `UserPromptSubmit` push (printing a real block, up to 1,676 characters) | 80.6 ms | 90.1 | 95.5 |
| `PostToolUse` search reminder, no corpus to remind of | 57.3 ms | 61.9 | 64.8 |
| `PreToolUse` guard on a `Bash` call | 64.0 ms | 67.5 | 75.5 |
| `PostToolUse` guard after an `Edit` | 64.3 ms | 73.4 | 84.0 |
| `python -c pass`, the interpreter alone | 23.2 ms | 26.7 | 31.1 |

The editable install's finder adds about 15 ms of these (§3 of `research/m40-4-live-session.md`); a
`uv tool install` does not pay it.

**Share of a session.** LeibaTrader's 25 Claude Code sessions with any activity, subagent
transcripts included, counted by what each hook fires on — a typed prompt (push), `Bash` and
`Monitor` (the `PreToolUse` guard), `Grep`, `Glob` and a `Bash` command running `grep` or `rg` (the
reminder), `Edit`, `MultiEdit`, `NotebookEdit` and `Write` (the `PostToolUse` guard), and a subagent
spawn (`SubagentStart`, priced as a push) — each weighted by the medians above. A session's active
time is the sum of the gaps between its events, each gap capped at 5 minutes.

| | |
|---|---|
| Active time | 381.9 hours |
| Hook calls | 5,656 pushes, 16,285 `PreToolUse` guards, 7,847 reminders, 6,252 `PostToolUse` guards, 1,183 subagent starts — about 98 an active hour |
| Hook time | about 2,444 s |
| **Share of active time** | **0.18%**; per session median 0.17%, p90 0.61%, max 0.94% |

**Implication.** A hook client that started in no time at all would return under 0.2% of a session's
wall time — at the busy host's costs, under 0.3%. Per prompt, the push's 81 ms sits beside a model
turn measured in seconds. The rewrite is not worth its cost on wall time; what it could still buy is
CPU, a reason nobody has raised.
