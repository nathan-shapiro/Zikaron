# FINDINGS — Zikaron

> **Working memory for this project, loaded every session.** It holds what a fresh session would
> act differently without: the decision index, where the work stands, the constraints that bind
> how to work here, what is owed with its proposed fix, and the open questions with what would
> close them. Everything else is elsewhere — rationale in `design/overview.md` (never
> re-litigate a decision from the one-line index below), measurements in `research/`, review trails in
> `reviews/`, the finished record in `FINDINGS-archive.md`, whose `##` headings are its index. Read
> the archive's §"Dogfooding notes" before proposing anything. `CLAUDE.md` §"Project memory" says
> what belongs here and what goes nowhere.

## Settled decisions — index
One line each. **Rationale, measurements and rejected alternatives are in `design/overview.md` §4.**

| # | Decision |
|---|---|
| D1 | Tribal knowledge only; ~~codebase KB is a separate system~~ — **amended 2026-09-15: that separate system is now Zikaron's own** (`design/knowledge-index.md`). What `remember` accepts is unchanged |
| D2 | No extra LLM on the write path — hard constraint |
| D3 | Two tiers: journal (unconsolidated) + long-term (consolidated) |
| D4 | Memory record = `{uuid, gist, content}` |
| D5 | Read = hybrid vector + full-text top-K → ids + gists |
| D6 | Write = primary agent's own judgment: new entry / amend (if read first) / nothing; it authors its own gist |
| D7 | Consolidation is the only extra LLM; code picks candidates, model judges — **amended 2026-10-14 (D39)**: the memory store's only one; D39's documenter is a second, outside both stores |
| D8 | Store scoped to the harness's directory; no global tier in v0 |
| D9 | Delivered as an MCP server plus a distributed skill and hooks |
| D10 | Consolidation trigger = a manually-invoked skill spawning a subagent (no compaction hook exists) |
| D11 | Staleness is repaired in-band by the agent the memory misled |
| D12 | Read = push **and** pull; a `userPromptSubmit` hook injects the top 5 gists |
| D13 | The gist's job is relevance triage |
| D14 | End-to-end task-benefit evaluation stoved until an implementation exists (component benchmarks are not) |
| D15 | Write-time dedup, agent-resolved: `remember` writes, then hands back near-duplicates for the agent to resolve |
| D16 | Soft delete only — retire, never `DELETE` |
| D17 | Scope key = the harness's own project directory where it names one, else the cwd (**amended 2026-08-18**) |
| D18 | Write policy injected by an `agentSpawn` hook |
| D19 | Python venv, latest stable; SQLite + FTS5 + sqlite-vec + fastembed; store never in git |
| D20 | Keep `bge-small-en-v1.5`, pass the BGE query prefix, record model id + dim per vector |
| D21 | Embed gist + content, not gist alone |
| D22 | The hook must never load an embedding model |
| D23 | No cross-encoder reranker on the push path; open for pull |
| D24 | Reject the extracted-identifier `tokens` column as specified |
| D25 | Supersession is structural via `superseded_by`, and it **demotes rather than hides** |
| D26 | Optimistic concurrency: `version` + a read receipt required on every `amend`/`retire` |
| D27 | Provenance = `created_at`, `updated_at`, `session_id` only |
| D28 | Chunk the dense side, parameterized; FTS5 stays unchunked; `max` rollup |
| D29 | Consolidation groups topically using retrieval as the adjacency function, mutual-K plus a cohesion pass; session grouping rejected |
| D30 | Write policy v0 drafted, to be experimented against; six signals instrumented |
| D31 | ~~Four~~ **Five** components: core / service / mcp / hook, plus the detached knowledge indexer (D1's amendment), over a Unix-socket JSON-RPC — **amended at M31**: the typed `zikaron` commands are clients, not store-openers, and `init` alone creates a store — **amended 2026-10-13 (M39)**: `health()` reports the service's package version, and a typed command refuses a service of any other version |
| D32 | Two tool sets: ~~five for the primary agent~~ — **five memory verbs plus the knowledge index's seven, twelve in all** (D1's amendment) — and four for the consolidator |
| D33 | Config = two TOML layers (system-wide + `.zikaron` override, per-key amend); `meta` keeps only store-coupled values |
| D34 | Two harnesses, one implementation: kiro-cli and Claude Code, differences carried as data behind one seam — **amended 2026-10-28 (M41-1)**: kiro-cli means its V3 engine at 2.35.1 or later; V2 is dropped |
| D35 | Supported platforms = Linux + macOS arm64; Windows out by transport, Intel Macs out on `onnxruntime` |
| D36 | Obtained by `uv tool install --managed-python zikaron` from PyPI (the flag is load-bearing), host Python still supported; MIT; model fetched never redistributed; semver `0.x`, ~~with an artefact-shape rule~~ — **amended 2026-10-11**: a minor bump means a schema bump, nothing else |
| D37 | `meta.schema_version` is a supported range; only the service migrates a store forward, in one transaction; nothing migrates back — **amended 2026-10-13 (M39)**: a corpus database is brought forward by whichever process opens it with `memory.db` at version 4 or later, and a corpus schema move moves `memory.db`'s too; a corpus schema version is the `memory.db` version that introduced its shape (corpora go 1 → 4), so a corpus is never ahead of its store |
| D38 | Guards: deterministic regex-only Claude Code hooks deny find-replace edits (override `#ZIKARON-FORCE #Reason: …`) and nudge a re-read after edits; installed only on request, memory/guards/both; not on kiro — **amended 2026-10-07**: a script run from scratch is judged too, the guard's one file read — **amended 2026-10-11 (M38)**: a `pgrep -f`/`pkill -f` matching its own command is denied too, on `Bash` and `Monitor`, per platform |
| D39 | Code knowledge: primitives, no workflow — a command classifies a module's per-source-file documents and removes or moves what that implies, a skill has the agent spawn documenters for the rest until the command reports it up to date; K14 front matter on every document; forward `Depends on:` lines only; on demand; corpus `git_mode: off` (operator, 2026-10-14; `design/code-knowledge.md`) — **amended 2026-10-16**: under Claude Code a background orchestrator subagent runs the loop — the session spawns it since **2026-10-21 (M40-5)**, where the skill had forked to it; one corpus per module; the documenter and orchestrator hold Zikaron's tools — **amended 2026-10-20 (M40-4)**: under Claude Code a search of a documented module is followed by one line naming its knowledge bases, at most once per agent each `retrieval.knowledge_reminder_interval` |

## Current state — resume here

**M0–M40 are built, reviewed and landed**, the last through PR #28. Each milestone's record is in
`FINDINGS-archive.md` (M40's in §"M40 as built"), its brief in `design/build-plan.md`. M40 is code
knowledge: the planner, documenter, orchestrator and skill (D39, `design/code-knowledge.md`), K14
links, the follow-ups M40-1 to M40-5, and the Warp evaluation — results in
`research/m40-evaluation.md` §4–§6, written up for readers outside the project in
`research/knowledge-index-issue-triage.md`.

**Release.** `0.4.0` is released (tag `v0.4.0`, 2026-10-22), the minor M39's schema move forced;
its note links the research write-up. The working tree carries `0.4.1.dev0` for the next pull
request. A minor bump means a `meta.schema_version` bump and nothing else (D36,
`design/distribution.md` §3).

**Next: M41, kiro parity against the V3 engine only — M41-1 is built, reviewed and passed the
operator's interactive test; it waits on the operator's request for a pull request.**
Operator, 2026-10-28: kiro V2 is dropped and kiro-cli ≥ 2.35.1 is required; the work is cut into
sub-milestones, each its own commit and review — **M41-1 "make it work"** (D34 amended), then
**M41-2 "the closable gaps"** (the probes, then the `design/kiro-gaps.md` rows they close);
kiro's own Memory is ignored, as Claude Code's is. kiro-cli 3.0 ships at the end of October 2026
by auto-update and makes the V3 engine the default; 2.35.1, installed here, reaches V3 by
`--v3`. Docs: `research/kiro-cli-v3-migration.md`; the binary: `research/kiro-v3-probe.md`.
**Under V3 a kiro install is broken three ways**: its agents are refused, which leaves it dead;
the MCP client's session label splits from the hook's, which splits its instruments; and a first
turn can start before Zikaron's tools exist.
**Briefs:** M41 and M41-1 in `design/build-plan.md` (what ships, invariants, done-when, fence).

M41-2 takes the closable rows — D38's command guard (`PreToolUse` exit 2 measured to block),
in-place documenter edits (`str_replace` measured granted by `write`), the documenter on
`claude-haiku-5.5`, the live code-knowledge test — and the probes still owed: nested subagents,
trust, resume, over-large results, `PostToolUse` stderr, and the `effortOverride` kiro logs for
a subagent (probe §11), which may close the per-agent-effort row.

Plan: (1) done — the docs and the probes; (2) done — the operator's decisions above; (3) M41-1's
brief — done, APPROVED (`reviews/m41-1-brief-review.md`); (4) **build M41-1 — done: built,
done-when 5 passed, APPROVED** (`reviews/m41-1-review.md`; operator, 2026-10-28: *"Let's build
it"*) in the worktree **`/home/nathan/Zikaron-m41-1`, branch
`m41-1-kiro-v3`, whose `FINDINGS.md` is the live one**; the main tree's uncommitted changes were
carried in byte for byte on 2026-10-28 and are frozen there; (5) M41-2's brief.

**M41-1 stands at:** every done-when holds — `pytest -m integration_kiro` passes on 2.35.1
`--v3`, the converted `zikaron-dogfood` profile ran headless on V3 with no `runError`, and the
operator's interactive run passed every bullet of done-when 5, the command-line-prompt bullet
by the operator's acceptance of what it showed (`research/kiro-v3-probe.md` §29–§31). The
committed `.kiro/agents/zikaron-dogfood.json` names `/home/nathan/Zikaron/.venv`, the path that
is right after the merge, so a re-install over it before then runs the worktree's code under
that venv (`PYTHONPATH=/home/nathan/Zikaron-m41-1 /home/nathan/Zikaron/.venv/bin/python -P -m
zikaron.install …`). A typed first prompt without Zikaron's tools is expected, so the
import-time cut stays fenced out (operator, 2026-10-29; the brief's item 8).

**The follow-up done-when 5 forced is part of M41-1:** kiro gives a subagent only what its own
rules and its parent's both allow (probe §28), so the install names the `fs_read` and `fs_write`
rules a spawned documenter needs from its parent — a note, not a grant (operator, 2026-10-29:
*"We should have note, not grant permissions automatically"*) — the write rule scoped to
`./code-knowledge/**`, measured enough. **Next:** the pull request when the operator asks for
one, then M41-2's brief, brainstormed with the operator first. Live tests stay
small: one module of a few files for code knowledge, never a large codebase (operator,
2026-10-28).

The rest of §"Owed work" waits on M41. **Each milestone is brainstormed with the operator before
its brief is written** (operator, 2026-10-13).

**Guards (D38, `design/guards.md`).** Installed with the memory store (`--components both`) in
`~/Trading/LeibaTrader`, `~/Dividends`, `~/Memory` and `~/PythonPlayground`; a project that
installs them instructs agents about edits not at all. This repository installs nothing (its
`.venv` runs the code under development). §3's rules and §9's self-match rule move only on an
observed command, never on a conceived edge, and never toward evaluating the shell; after any §3
or §8 edit run `.venv/bin/pytest -q --no-cov tests/test_guard_rule_table.py`. The replay's
verbatim deny list stays out of the repository (`experiments/m37_guard_replay.py --dump`
re-derives it here).

**Dated re-runs**, on their dates regardless (§"Owed work"): the `bounds`-on-first-call query on
2026-10-29 and Q22's post-release measurement on 2026-10-30.

### Facts that constrain how you work in this repository

- **A schema change is one commit with its design**: `test_ddl.py` and `test_event_kinds.py`
  read `schema.md`'s DDL and per-kind table verbatim.
- **The knowledge status tool's description is at 1,896 of the 1,900 characters**
  `tests/test_mcp_tool_descriptions.py` allows, so a sentence added to it must be paid for.
- **`sun_path` is tighter on macOS**; `design/architecture.md` §Paths holds every figure. A long
  `TMPDIR` reproduces macOS's path geometry on Linux:
  `d=/tmp/mac/$(printf 'x%.0s' {1..39}); mkdir -p "$d" && TMPDIR="$d" .venv/bin/pytest -q`.
- **`design/harness.md` is normative for every harness-coupled fact**; read it before touching
  the hook, the MCP client or the installer.
- **`research/`, `experiments/` and `spikes/` are out of scope for any sweep** (operator,
  2026-09-22); `design/build-plan.md` and `design/evaluation.md` are in.
- **Use `Explore`, not `general-purpose`, for a read-only sweep**; `general-purpose` fans out.
- **The task tracker does not survive compaction** (operator, 2026-09-28): a plan lives here.
- **Harness versions are recorded, never re-probed** (operator, 2026-10-16).
- **The host is busy** (operator, 2026-09-29 and 2026-10-11): no latency figure measured on it is
  comparable with an idle-host budget.
- **CI runs four jobs on `main`** — linux 3.12/3.13/3.14 and macOS 3.12, the last required; the
  operator merges, and there is no branch protection (`design/distribution.md`).

### Where the stores are

`<project>/.zikaron/`, one per directory, no global tier. **`~/Trading/LeibaTrader`,
`~/Dividends`, `~/Memory` and `~/PythonPlayground` run this repository's `.venv`**, an editable
install, deliberately (operator, 2026-09-30): an uncommitted edit here is live there at their next
service or MCP start. LeibaTrader is the primary real-work store and documents its code with code
knowledge; its memory `f6eb10e5-6cf1-4805-bdf4-5d24ed0a71f5` has been false since M40-1, and
retiring it is the operator's. `~/Memory` is a sibling project's store, read-only for this agent
without the operator's per-task say-so; the consolidation A/B there has no pre-run baseline.

**Never snapshot a store with `cp memory.db`**: copied while a service holds its WAL, the file
can open and answer with nothing. Use `Connection.backup()`, `VACUUM INTO`, or all three of
`memory.db`, `-wal` and `-shm`. `experiments/m33_call_log_queries.py` holds the access log's five
queries.

### Owed work — the candidate pool for the next milestone

Nothing here is scoped; each entry says what it is, the fix proposed and what to measure first.
An owed item goes here the moment it is identified. The detail behind each is in
`FINDINGS-archive.md` §"FINDINGS as it stood before the 2026-10-22 trim" and the notes named.

- **`bounds` on first call — re-run 2026-10-29**, per store, read-only: 0 of 18 first calls
  refused on 2026-09-29, a day of data. `WITH c AS (SELECT session_id s, json_extract(detail,'$.method') m, json_extract(detail,'$.error_code') e, id FROM event WHERE kind='call' AND session_id IS NOT NULL) SELECT c.m, count(*), sum(coalesce(c.e,'')='bounds') FROM c JOIN (SELECT s, m, min(id) i FROM c GROUP BY s, m) f ON c.id=f.i GROUP BY c.m`
- **Q22's post-release measurement — re-run 2026-10-30**: `VERDICT_MARKER` from
  `experiments/m34_gist_replay.py` over each store's gists written since 2026-09-30, against
  Q22's 169-record baseline (archive §"Closed with `0.3.0`"). Near the baseline, the write-side
  rule does not bind, which argues for the corpus repair pass first.
- **The corpus repair pass**: re-seed live long-term records as journal entries (a `--tier
  long_term` option on `m34_gist_replay.py`) and consolidate them in a replay store, judged on
  M34's four bars, before any live store.
- **The two documenter fixes — agreed** (operator, 2026-10-21), ready to brief as one follow-up:
  a block the harness attaches beside a tool result is not the file's content (wording
  memory-reviewer's; it recurred once in Warp's 407); and *"no test covers"* scoped to the tests
  it read — *"no test in `<file>` covers"* (`research/m40-toy-run.md` §17). Verify by
  regenerating only the documents the defects were seen in, in a scratch `cp -a` of Warp's clone.
- **A prompt-only arm for the Warp evaluation's medium issues** — proposed, not approved: the
  treatment's prompt with no documents, about $65–90, to separate the prompt's checking paragraph
  from the documents as the cause of the extra cost (`research/m40-evaluation.md` §6). It needs
  `prepare` again, since the rebase replaced the commit `state.json` records. The earlier
  documents and slice are in `~/Zikaron-m40-archive/`.
- **The closed-issue stage of the evaluation** — a milestone of its own: closed issues at the
  commits their fixes merged onto, the documents rebuilt there by the planner.
- **Paged knowledge search** (operator, 2026-10-22): the first three snippets whole, the rest
  named by path, line range and role line, with an `offset`; it changes
  `design/knowledge-index.md` §8.3, so it is brainstormed first. Readers already ask for 10
  results in 57 of 194 searches, yet only 1 of 48 runs opened a document file after a search;
  measure page fetches in a live arm first.
- **K14's partial-coverage field** — `zikaron-coverage: partial` on a document the writer could
  not read whole, reported beside `source.state`; a format change, brainstormed first. Measure how
  many sources in a real module exceed the writer's window.
- **A dependency that moves while its users' bytes do not** leaves `Depends on:` naming a gone
  path under a `fresh` document. Proposed, once one is seen to mislead: the planner rewrites the
  path on a move it detects and lists a document naming a missing path as stale
  (`design/code-knowledge.md` §8).
- **Code knowledge documents prose as code** (low priority): the planner skips `.md`, `.rst` and
  `.txt` under code knowledge by default, `--include` keeping the way back.
- **A push block that fits the harness's budget by construction** (after M41-1, if a truncated
  push is ever seen): kiro V3 cuts hook output at 3,000 characters, marked `...[truncated]` to the
  model alone (`research/kiro-v3-probe.md` §21). The 1,024-character gist bound admits a five-row
  block of 6,097 units. The real worst block is ~2,125, from the longest gist of 652 in the four
  stores, 246. The fix: render rows only while the block fits, and record surface rows for what was
  shown. M41-1 makes the trigger observable: a `push_oversize` line in `hook.log`.
- **A kiro install with no custom agent** (after M41): kiro V3 reads workspace `.kiro/hooks/*.json`
  and `.kiro/settings/mcp.json` for its default agent, measured working
  (`research/kiro-v3-probe.md` §15), so `--agent` could become optional, as Claude Code needs
  none. Two things block it: a per-call approval that no install can pre-answer there, and a
  custom agent that sees workspace servers only with `includeMcpJson`. One exists, outside the
  repository: `~/.kiro/workspace-roots/<hash>/permissions.yaml`, holding `rules: []` and
  `workspaceTrusted: true` after a trusted interactive session (2026-10-29). Measure first whether
  kiro honors a rule written there, and whether an installer writing kiro's own trust record is
  acceptable at all.
- **More files per documenter** — not now (operator, 2026-10-21: *"I don't want context of
  documenters to overfill"*); if taken up, measure *k* = 5 against *k* = 1 on forty files
  (`research/m40-toy-run.md` §16).
- **A cheap reader in the triage evaluation**: Haiku 5.5 as a third reader over the same copies,
  on the hypothesis that the documents help a weak reader more.
- **A reader's verification late in a long session**: measure, where a session crosses
  unfamiliar code, how often a code-knowledge search is followed by a read of the top result's
  source; if it decays, a `PostToolUse` line on `zikaron_knowledge_search` to verify before
  editing.
- **A stop guard for the turn that ends on a promise**: a deterministic D38 guard on the stop
  hook, asking for the evidence the goal is met or the blocker. Count such turns in the guarded
  projects' transcripts first, and probe `Stop` output handling before building.
- **A native hook client** (operator, 2026-10-21: *"rewriting hook (only hook, not service) in
  rust"*): the hook forwards the payload and prints the service's answer; the cold-start spawn,
  `hook.log` and the guards stay Python. Measure the share of session wall time hooks take first
  (`research/m40-4-live-session.md` §3).
- **Cheap and never run**: Q17's `init` connect-deadline measurement (`design/knowledge-index.md`
  §9), and trademark clearance on `Zikaron`.
- **Refused, so not re-proposed**: a relevance floor on push, and degrading the re-shown gist
  (archive §"The read path is barely used"); retrieval-quality tuning has no non-proxy dependent
  variable while D14 defers end-task evaluation.

### How the next review should be briefed

- **The brief is the self-review skill's template, filled with facts and nothing else**; operator
  direction goes in its `On the operator's authority:` line in the operator's exact words.
- **Do not narrow a review's scope to cut it**, and do not name where you expect the findings.
- **Size a preregistered bar to the decision it forces**; with nothing to do differently either
  side of it, measure and report without one.
- **State the predicate, never the tally**: a count in a brief becomes the specification.
- **Research notes and harnesses are reviewed for the decision they support** (operator,
  2026-09-29): a finding counts only if it would change what ships or is decided. Put this in the
  operator's line for such a note, unless the operator asks for the writing itself to be reviewed,
  as for the 2026-10-22 report.
- **A finding is weighed by its likelihood against its fix's cost** — the operator's words, for
  every brief: *"Reviewer tends to find crazy edge cases (and stuck network drive sounds like
  that). Please escalate to me if reviewer continues pushing for over-engineered solutions against
  unlikely to happen situations."*

### Live design questions

Ids are stable and never reused; closed ones are in `FINDINGS-archive.md`. Detail in the archive's
§"FINDINGS as it stood before the 2026-10-22 trim" and the documents named.

- **Q1** — push fires once per prompt, but a memory is most needed mid-task; under Claude Code
  `PostToolUse` could carry one (M40-4's seam), untried.
- **Q2** — fusion erases an embedder upgrade's gain (both `bge-large` and `granite`), structural
  within RRF; M25 closed the config sweep, so the open test is score-based fusion, amending D5. No
  embedder swap until then (`design/retrieval.md`).
- **Q3** — chunking follows entry length, not provenance, and an amendment can make a record
  chunked.
- **Q5** — nothing tells the agent why a demoted memory is shown; the editorial half is open.
- **Q6** — staleness D11 cannot catch: memories silently obsolete, no longer surfacing, or wrong
  when written (one consolidation-authored claim surfaced for days;
  `research/leibatrader-consolidation-2026-09-24.md`).
- **Q7** — the scope test: whether a decision taken in conversation belongs in the store at all,
  a D1 question rather than prompt wording (`research/kiro-container-run.md`).
- **Q9** — end-task evaluation (D14); `design/evaluation.md` is a proposal. The Warp triage
  evaluation is the first controlled result for code knowledge, and none yet exists for memory.
- **Q12** — merging degrades a gist's triage value, at consolidation and at write time; do not
  revert the prompt's lean toward splitting (operator).
- **Q14** — preferences collect in a store designed not to bind; `CLAUDE.md` is the side of the
  seam for a rule that must bind (`research/m30-docker-end-to-end.md` §Coexistence).
- **Q16** — does the agent reach for memory unprompted? Unattributable from the store; the
  harness transcripts can answer it while they last.
- **Q17** — whether `zikaron init` owes a connect deadline longer than 10 s on a cold model
  cache, or a script owes the retry (`design/knowledge-index.md` §9).
- **Q19** — the corpus skews negative by the scope gate's construction; closing it needs Q7 first,
  then whether outcome belongs in the record and in push's selection.
- **Q21** — a consolidator pass that neutralizes register without touching severity; closed only
  by an offline, blind, preregistered replay on a `VACUUM INTO` snapshot, scoring a fact dropped,
  a condition dropped and severity reduced apart — machinery Q12 and Q19 lack too.
- **The knowledge index's own** — nothing owns refreshing a hand-written corpus (proposed: the
  session-start helper, once a no-change refresh is measured); keep `git_mode: tracked` as the
  default for hand-written corpora; no representation for intra-document supersession (no change
  until a withdrawn claim is seen quoted); stop freezing `rrf_k` and `fusion_depth` in a corpus's
  `meta` at creation.

### Harness

`.claude/` is the live crew and `.kiro/` the fallback; what an install ships is snapshotted under
`tests/fixtures/installed/` (`CLAUDE.md` §Harness). memory-reviewer runs `fable` against the
author's `opus`, so an APPROVED carries no cross-vendor independence; per-agent write scoping is
stated in prompts and enforced by nothing; the self-review loop halts when the reviewer model is
down. Do not compare recall numbers across the kiro→Claude Code boundary.
