# FINDINGS — Zikaron

> **Working memory for this project**, maintained by the **memory-researcher** agent. It loads every
> session, so it stays lean: the decision index, where the work stands, and what is still open.
>
> **The design lives in `design/overview.md`** — what we are building, the shape of the system, and the
> full D1–D33 decision table *with rationale*. §"Settled decisions" below is a one-line index only. Read
> `design/overview.md` before revisiting any decision, and never re-litigate one from the index alone.
>
> **The finished record lives in `FINDINGS-archive.md`** — build history, the milestone plan, the
> dogfooding evidence, and the references. Read on demand, not every session. It was split out when this
> file reached ~49k tokens and stopped being the lean hub this header claims it is; keeping it lean is
> an ongoing job, not a one-off. When a section here stops being live, move it there rather than
> letting it accumulate.

## Settled decisions — index
One line each. **Rationale, measurements and rejected alternatives are in `design/overview.md` §4.**

| # | Decision |
|---|---|
| D1 | Tribal knowledge only; codebase KB is a separate system |
| D2 | No extra LLM on the write path — hard constraint |
| D3 | Two tiers: journal (unconsolidated) + long-term (consolidated) |
| D4 | Memory record = `{uuid, gist, content}` |
| D5 | Read = hybrid vector + full-text top-K → ids + gists |
| D6 | Write = primary agent's own judgment: new entry / amend (if read first) / nothing; it authors its own gist |
| D7 | Consolidation is the only extra LLM; code picks candidates, model judges |
| D8 | Store scoped to the harness's directory; no global tier in v0 |
| D9 | Delivered as an MCP server plus a distributed skill and hooks |
| D10 | Consolidation trigger = a manually-invoked skill spawning a subagent (no compaction hook exists) |
| D11 | Staleness is repaired in-band by the agent the memory misled |
| D12 | Read = push **and** pull; a `userPromptSubmit` hook injects the top 5 gists |
| D13 | The gist's job is relevance triage |
| D14 | End-to-end task-benefit evaluation stoved until an implementation exists (component benchmarks are not) |
| D15 | Write-time dedup, agent-resolved: `remember` writes, then hands back near-duplicates for the agent to resolve |
| D16 | Soft delete only — retire, never `DELETE` |
| D17 | Scope key = literally the current working directory |
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
| D31 | Four components: core / service / mcp / hook, over a Unix-socket JSON-RPC |
| D32 | Two tool sets: five for the primary agent, four for the consolidator |
| D33 | Config = two TOML layers (system-wide + `.zikaron` override, per-key amend); `meta` keeps only store-coupled values |

## Current state — resume here

### Phase: dogfooding. No milestone is outstanding.
Every milestone M0–M12 is built and reviewed; the build is finished. Since then the work has been
**using** the system on two real stores and fixing what use exposed. Two review trails cover it and
should not be re-run: `reviews/m12-distribution-review.md` (seven rounds, APPROVED) for the milestone,
and `reviews/m12-dogfooding-delta-review.md` (two rounds, APPROVED) for everything changed afterwards.
Read `FINDINGS-archive.md` §"Dogfooding notes" before proposing anything — most of what a fresh session
would think to try has already been measured, and several plausible ideas are already refuted there.

**Where the stores are.** `<project>/.zikaron/`, one per directory, no global tier. This repository has
a small store from a seeding experiment. `~/Memory` is the **primary real-work store** — 31 long-term
records and 26 journal entries at last count, one consolidation run completed (all 31 promoted in place,
zero merges), and it is the corpus the next consolidation should run against. `~/Memory` is otherwise
**read-only for this agent**; writing there needs the operator's explicit say-so, which has been given
once, per-task.
Two snapshots exist for comparison, **in `/tmp`, so they will not survive a reboot**:
`memory-backup-before-consolidation.db` (31 journal, pre-run-1) and `memory-run1-post-consolidation.db`
(15 records, the merge-heavy run). Move them somewhere durable if the A/B still matters.

**What to do next, in priority order.**
0. **Make Zikaron work under Claude Code**, keeping kiro working — **one codebase, two harnesses**
   (operator decision 2026-08-16; harness differences are data, not forked code paths). Scoped as four
   briefs in `design/build-plan.md`: **M13** the design delta, **M14** the harness seam and both clients,
   **M15** the installer adapter, **M16** the dogfooding checkpoint. **No schema change is required** —
   an interim plan added a migration milestone to record the consolidator's model, and a measurement
   deleted it (see §Harness). Measured evidence:
   `research/claude-code-harness-probe.md`. This gates items 1 and 2, which both need the memory tools and
   the push hook live in whichever harness the work happens in.
1. **The next consolidation, on a journal grown by real work.** That is when open question 12's *positive*
   merge criterion gets designed and tested. The prompt currently has reasons to split and none to merge,
   deliberately, on operator decision — do not revert it on the strength of the 11-merges-to-0 result.
2. **Read the recall instrument.** `search` calls per session; its pre-change value is **0** across 17
   hours of real work, which is what the recall paragraph was added to move. One working session answers
   whether prose was enough or whether the mechanism half of open question 1 is the real work.
3. **A byte bound on `gist`** in `schema.md` §Bounds — the one deliberately deferred write-path change
   (open question 11). Tokens do not bound bytes, so no output cap is provable today. **No longer
   deferrable, and now folded into M14:** Claude Code's injection budget is a fixed 10,000 characters
   against kiro's 65,536, so the margin this defect eats narrowed 6.5×.
4. **The installer has no notion of *same install, older version*.** It asks only whether a shipped file
   names a *different* interpreter, so upgrading Zikaron and re-running the installer silently keeps a
   stale consolidator prompt unless `--force` is passed. The fix is to compare shipped content. **Folded
   into M15**, which is the installer milestone anyway.
5. **A known intermittent**, diagnosed and left: `test_idle_self_stop_unlinks_the_socket_before_the_process_exits`
   fails under load because the signal handlers are installed after the socket is bound. Low impact, wants
   a test that pins the race deterministically.

**Two instrument properties worth knowing before quoting a number.** The dedup signal reports nothing for
30 days unless `signal_horizon_days` is lowered (only the fully-resolved outcome closes early), and
amend-after-surface currently reads `rate=1.00` meaning *3 of 3 resolved pairs* with 51 still pending.

### Harness: migrating from kiro-cli to Claude Code
**The development crew has moved; the product has not.** `.claude/` now carries memory-researcher,
memory-reviewer, memory-assistant, py-runner and the `self-review` skill, plus a `CLAUDE.md` holding the
static half of this document. `.kiro/` stays in the repository unedited — it is the reference for what
the installer still ships, and the fallback. **Zikaron itself remains kiro-only**: the hook client reads
kiro's `agentSpawn`/`userPromptSubmit` payloads and the installer writes kiro config, so the memory tools
and the push hook are **not live under Claude Code**.

**Probed 2026-08-16 against Claude Code 2.1.233, and the probe refuted three of the claims below.**
Full measurement: `research/claude-code-harness-probe.md`; scripts and raw logs
`spikes/claude-code-harness/`. The list that follows is kept **as it was written**, with each refuted
item marked in place, because the fact that a careful documentation reading got these wrong is itself
the evidence — the same shape as `research/kiro-mcp-lifecycle-probe.md`. A `claude-code-guide`
documentation reading (`research/claude-code-harness-contract.md`) independently repeated the
session-id error, so it is the weaker source of the two.

- **REFUTED — the prompt field is `prompt`, not `user_input`.** `hook/main.py` needs no change there.
- **REFUTED — a session-id environment variable exists.** `CLAUDE_CODE_SESSION_ID` is exported into
  every process Claude Code spawns — both hooks, a subagent's subprocesses, and **the MCP stdio
  server** — and equals the hook payload's `session_id`. The two-rung ladder ports as a **rename**;
  linked sessions, link coverage, both cross-client D30 signals and the recall instrument all survive.
  (`CLAUDE_PID` is *not* overridden for children and must never be read.)
- **REFUTED — the subagent-suppression rule needs no re-derivation.** `UserPromptSubmit` does not fire
  for subagents at all, so the door D32 guards is closed by the harness and the rule is simply inert
  here. `SubagentStart`/`SubagentStop` carry `agent_id` **and `agent_type`**, so the write policy can
  now be injected for every subagent *except* the consolidator — the precise rule kiro's payload could
  not express.
- **NEW, and nobody had it — the injection budget is a fixed 10,000 characters.** Bisected: 9,503 B
  intact, 10,502 B truncated to a 2 KB preview. There is no `max_output_size` field, so 65,536 has no
  analogue. Overrun is **loud** (a notice, a preview, and a path to the full text), unlike kiro's
  silent truncation — but the margin protecting the unbounded-gist defect narrowed 6.5×.
- **NEW — the real structural break is MCP process scope.** Claude Code runs one MCP server per
  **session**, shared by every subagent, not one per agent instance as kiro does. `(session_id, pid)`
  therefore cannot tell two consolidators in one session apart, and `_PlanBridge`'s per-process
  takeover guard becomes per-session. **Operator decision 2026-08-16: accept it** — cross-session
  exclusion is untouched, the lease still lapses, and a run-token fix is named but not built.
- **NEW — D32's tool gating only half ports.** Subagent frontmatter `tools:` genuinely restricts MCP
  tools, so withholding `search`/`fetch` from the consolidator stays mechanical. Withholding the four
  verbs from the primary agent does not: a server must be registered session-wide to reach any
  subagent, `permissions.deny` is global and breaks the subagent too, and per-subagent MCP
  registration does not exist. That half becomes **prompt-only**.
- **NEW — the injected block lands *after* the user message**, with no coercive framing sentence. Under
  kiro it landed before, framed *"I have gathered this context from valuable programmatic script
  hooks"*. Open question 4's stated tension resolves in our favour, by the harness's choice not ours.

Original text, as written before the probe:
- ~~**`userPromptSubmit` → `UserPromptSubmit`, and the prompt field is `user_input`, not `prompt`.**~~
  **[REFUTED by probe §2 — the field is `prompt`. Kept for the record; do not act on it.]**
  `hook/main.py` returns quietly when that field is not a string, so under Claude Code the push path
  fails as *no output and exit 0* — invisible, by the same always-exit-0 design that makes a genuine
  failure relayable. `agentSpawn` → `SessionStart`, same silent-return path.
- ~~**No session-id environment variable exists.**~~ **[REFUTED by probe §1 — `CLAUDE_CODE_SESSION_ID` is
  in every process, MCP server included. Kept for the record; do not act on it.]** `KIRO_SESSION_ID` was the shared key that made the hook
  and the MCP tools speak as one session. Claude Code documents `CLAUDE_PROJECT_DIR` and `CLAUDE_EFFORT`
  among others, and nothing carrying a session id — so the hook would use its payload's real `session_id`
  while the MCP client falls back to its minted `zk-<uuid4>`, and they diverge. That breaks linked
  sessions and **breaks the recall instrument**, which counts `search` calls *per session*. This is the
  first thing to probe and the one most likely to force a design change.
- ~~**The subagent-suppression rule dissolves rather than ports.**~~ **[REFUTED by probe §3 —
  `UserPromptSubmit` never fires for a subagent, so the rule is simply inert. Kept for the record.]** It compares env session id to payload
  session id; Claude Code instead scopes hooks per subagent via frontmatter and has `SubagentStart`/
  `SubagentStop` carrying `agent_id` and `agent_type`. Re-derive it; do not translate it.
- **Hook placement changes who gets memory.** Kiro put hooks inside each agent config, which is what made
  `zikaron-dogfood` a controlled experiment. Claude Code's project `settings.json` hooks fire for every
  session in the directory. Preserving the experiment needs subagent-frontmatter hooks or a deliberate
  decision to drop the distinction.
- **D10's premise is false here: `PreCompact` and `PostCompact` exist.** The manually-invoked
  consolidation trigger becomes a choice rather than a constraint.
- **Open question 1's mechanism half gets new options.** `PostToolUse`, `PostToolUseFailure`,
  `PostToolBatch` and `Stop` all exist, and `PostToolUseFailure`'s exit-2 stderr is documented as
  reaching the model — which is precisely the "this protobuf step just failed silently" moment that
  `userPromptSubmit` cannot serve. Probe it before believing it.
- **The installer's model check has no analogue.** `kiro-cli chat --list-models -f json` exists because
  `agent validate` accepts an unknown model silently; Claude Code offers no equivalent list, so the
  no-silent-fallback rule needs a new mechanism.
- **Simplification:** the two hook formats (object vs array, with the seconds-versus-milliseconds trap)
  collapse to one. That is code to delete.

**Decided 2026-08-16: accept a baseline reset.** The recall instrument is read fresh under Claude Code
(M16), and the pre-migration numbers are recorded as a **different-harness baseline that is not to be
compared against** — the harness, the model, the injection position and the write-policy delivery all
change at once. The caution below became the decision. Original text:

**Undecided, and it should be decided before the migration work starts.** Priority item 2 — reading the
recall instrument after the 2026-08-14 prose change — was calibrated on kiro sessions sharing one
`KIRO_SESSION_ID`. Migrating first confounds that reading, and per the point above it may not be
measurable at all until the session-label question is resolved. Either take the reading in kiro-cli
first (one working session closes it cleanly), or accept a baseline reset and record here that
pre-migration numbers are from a different harness and are not comparable. **Do not quietly compare
across the boundary.**

**Crew fidelity lost in the move, both deliberate.** memory-reviewer ran `gpt-5.6-sol`; Claude Code takes
Claude models only, so it now runs `fable` — a different model, same family, so **cross-family
independence is gone** and an `APPROVED` is weaker evidence than it used to be on anything where
shared-family blind spots are plausible. And per-agent write scoping (`allowedPaths: ["reviews/**"]`,
`["research/**"]`) has no frontmatter equivalent; it is now stated in each agent's prompt and enforced by
nothing. Both are recorded in `.claude/skills/self-review/SKILL.md` where the loop that depends on them
lives.

## Open questions
1. **Pull is now used, and the instrument cannot say by whom or why — so the question it exists to
   answer is still open.** Recall went from **10 searches to 188** after the 2026-08-05 policy
   change (fetch 17 → 90), measured on `~/Memory` across 898 turns and 4,490 pushed gists: 64, 77
   and 46 in the three real working sessions, spread from turn 29 to turn 443 rather than clustered
   at the start, and productive — **0 of 188 came back empty**, 165 hit the 5-result limit, 32% were
   followed closely by a `fetch` and 32% by a write. On its face the prose fix worked.
   **Two operator corrections removed almost all of that as evidence, and the first reading of it
   here was wrong.** Many of those searches were **explicitly nudged by the operator**, and the
   `search` event records no occasion, so a prompted search and a self-initiated one are the same
   row. And a large share came from **`memory-reviewer`, which runs a different model family
   (gpt-5.6) and searches eagerly**, while the Claude primary agent needs nudging — but every agent
   instance in a session shares one `KIRO_SESSION_ID` (measured in the MCP lifecycle probe), all
   five sessions contain both searches and pushes with no pure-subagent session among them, and
   `client_kind` separates only `mcp` from `hook`. So the log **cannot attribute a search to an
   actor or to an occasion**, and 188 does not measure autonomous recall by the primary agent. An
   earlier revision of this entry claimed the store refuted the agent's self-report; that claim is
   **withdrawn**, and it is this corpus's own "name the quantity before quoting a number about it"
   committed against a live store rather than in a design document.
   **Attribution without new instrumentation, by operator direction: read the time clustering.** The
   researcher works for a stretch and then goes through review rounds, so the reviewer's searches
   arrive in dense intervals. That fits the one shape the data does show whoever searched: recall is
   **bursty** — only **6–11% of turns contain any search**, in bursts of up to 9. If the bursts are
   the review rounds, the primary agent's unprompted rate is *lower* than 6–11%, not higher.
   Recording the caller's pid and an `occasion` argument were both considered and **deliberately
   deferred**: pid is the only discriminator the lifecycle probe found between agent instances, and
   `(session_id, pid)` already exists for consolidation ownership, so the fix stays cheap for
   whenever clustering stops being enough.
   **What changed 2026-08-14, from the using agent's own account of why it does not reach out
   unprompted.** Three things, all prose, none in the schema. (a) **The trigger was a category
   requiring a self-assessment** — "search whenever you are about to spend real effort" — and the
   agent's report is that this judgement fails mid-task because *effort feels like progress*. It is
   now four detectable occasions: something surprised you; you are about to propose a design,
   mechanism or plan; you are about to say an approach will not work; you are about to rename, move
   or delete something other work depends on. The third is new and is what the store is most
   directly for. (b) **The injection creates a sufficiency illusion**: five on-point gists make
   memory feel already consulted, while they matched *the user's words* and go stale the moment the
   problem is reframed, with nothing arriving to say so. That is now stated in the **injected block
   itself** (+187 bytes on every push against a 65536-byte cap) rather than only in the policy,
   because the block fires once per message and the policy once per session. (c) **A gate**, which
   the agent ranked first by a distance and which is the only lever carrying its own check: a
   design, a plan, or a claim that an approach is a dead end must state what was searched for and
   what came back, including "found nothing relevant" so silence is not compliance. I argued against
   putting the gate in Zikaron's own policy on scope grounds — a memory system dictating the shape
   of every proposal — and the **operator overruled it, to be wound down if it overfires**; it is
   one sentence, so that is a one-line revert.
   **How we will know if the gate overfires:** searches per turn rising while the fetch-follow rate
   falls below the current 32%, and the burst structure flattening toward one search per proposal.
   The agent predicted that shape itself, about numeric floors: "I would satisfy it hollowly."
   Unchanged below: the mechanism half.
1. **The push hook fires at the wrong moment for half the use case.** `userPromptSubmit` fires **once per
   user message** with `{hook_event_name, cwd, session_id, prompt}`. Good: the query is clean human text.
   Bad: one user message spawns dozens of agent turns, and the moment a memory is most needed ("this
   protobuf step just failed silently") arrives twenty tool calls later, when **no injectable hook fires**.
   Push therefore covers only *task-framing* recall. `postToolUse` fires per tool call and receives
   `tool_response`, but has **no documented stdout→context path**. Options: lean on pull plus D18's
   instruction; use `postToolUse` as a side-channel priming the next injection; or use `stop` (which can
   return `{"decision":"block","reason":...}` as a new user message) as an end-of-turn nudge.
2. **Unweighted RRF is discarding exactly the signal an embedder upgrade would buy.** The strongest finding
   of the benchmark, and unasked-for. Dense-only, `bge-large` **beats** `bge-small` (MRR@10 **+0.0705, CI
   [+0.0283, +0.1156]**); the RRF hybrid **erases it** (0.922 vs 0.938). Mechanism measured: all **960 of
   960** fused top-5 slots are held by documents *both* arms returned, while the arms intersect in only
   ~28% of their union — so ~72% of the candidate pool structurally cannot reach the injection budget. Ties
   were investigated as the cause and **refuted** (max movement 0.0052). RRF `k`, arm weighting and fusion
   depth deserve their own pass; plausibly worth more than any model swap. All three are now named `meta`
   keys (`rrf_k` 60, `fusion_depth` 50) rather than constants, so the pass is a config sweep. Needs no
   reindex, so it is safely post-build. Detail in `design/retrieval.md`.
3. **The real length distribution of memories is now partly measured, and chunking turns out to be a
   *post-consolidation* phenomenon.** First real data, from 31 journal entries and the 15 long-term
   records consolidation made of them: journal entries ran **162–378 tokens** (median 259) against a
   `chunk_max_tokens` of 450, so **not one of them chunked at all**. The consolidated records run
   **184–1877 tokens**, and **9 of 15 chunk**, up to 6 parts. So the chunking path — and the dense
   arm's `max` rollup over parts — was at first credited to **merging specifically**, on the strength of
   the A/B: run 1 (11 merges) produced 9 multi-chunk records of 15, up to 6 parts, while run 2 (0
   merges) produced **0 of 31**, all 162–378 tokens. **That attribution was wrong, and a second working
   session refuted it within a day.** 26 entries written during real work ran **230–879 tokens** and
   **8 of them chunk**, one into 3 parts, with no merging involved at all. So chunking follows entry
   *length*, regardless of provenance, and the first day's corpus was simply uniformly short — a
   seeding session summarising known facts produces shorter entries than live work does. The
   distribution over all 93 authored writes so far: **162–879 tokens, median 273**, against a
   `chunk_max_tokens` of 450. The lesson about the claim rather than the parameter: one day of one
   corpus attributed a phenomenon to the wrong cause, and only a differently-shaped session could tell. 450 looks comfortably above the natural length
   of one written lesson and comfortably below a merged record. Original text below.
3. **The real length distribution of memories is unknown.** D28 settles the chunking mechanism, but its
   parameters rest on zero real data, and the benchmark's six over-length fixtures turned out to be one
   template wearing six hats. `token_count` and the `truncated` canary are instrumented so revisiting
   `chunk_max_tokens` — and chunking itself — becomes a measurement.
10. **Takeover's caller is specified and its premises are now measured — one item remains open.** The
   consolidation lease is taken over by an explicit `plan_groups`, on the reasoning that a human
   reinvoking the skill is the only liveness evidence that exists. A targeted review caught that nothing
   *converted* that invocation into the call: a fresh consolidator's own first tool call is `next_group`,
   which refuses a live foreign run, so the takeover path was unreachable through the real client path.
   The bridge is now **built and tested, not only specified** — `zikaron-mcp` calls `plan_groups` with its
   own `(session_id, pid)`, **lazily, immediately before the first `next_group` it forwards, and at most
   once *successfully* per client process**, exactly the three-state machine (`unplanned | ready | failed`)
   M10's `_PlanBridge` implements, including its own awkward transition (a first `plan_groups` answering
   `store_busy` leaves the client `unplanned` so a retry replans) and, found during M10's own review, its
   cancellation edge: a tool call cancelled while `plan_groups`'s *response* is still in flight moves the
   bridge straight to the terminal `failed` state rather than back to `unplanned`, since the takeover may
   already have committed on the service side by the time the cancellation reached the client, and a
   mistaken retry there would risk the second successful takeover the whole "at most one" bound exists to
   rule out.
   **Both premises were measured 2026-08-02** (`research/kiro-mcp-lifecycle-probe.md`): kiro runs one MCP
   server process **per agent instance**, so each invocation carries its own fresh takeover guard — the
   process supplies the guard, not a limit on attempts, since a failed plan displaces nobody; and the handshake is
   **eager**, which is why the call is made lazily on the first forwarded `next_group` — a start-wired call
   would take the
   lock before the model had been asked anything, so a spawn that then did nothing would displace a live
   worker for nothing. The operator's constraint, stated directly: *do not take the consolidation lock
   unless we plan to consolidate.* **Still open:** whether kiro ever restarts a client mid-subagent for its
   own reasons, which would supply a fresh guard for the next forwarded `next_group` to consume with no new
   human invocation behind it. Three instances showed no such restart,
   which is weak evidence at that sample size, and nothing depends on it being false — a spurious takeover
   costs one worker's in-flight reasoning, never a journal row.

4. **Hook→service transport: designed, and now smoke-tested (M0, spike 3).** D31 settles the shape.
   **Resolved 2026-08-01:** RPC round-trip latency (cold start-if-absent ~101 ms end to end, dominated by
   interpreter start; warm p50 0.146 ms over an established connection); `busy_timeout` at 5 s behaves exactly
   as documented under two real writers, once the service's own blocking `sqlite3` calls are kept off the
   event loop — getting that wrong produces a self-inflicted deadlock that *presents* as a `busy_timeout`
   failure, which is now a normative note in `design/architecture.md`; start-if-absent holds under two clients
   racing the same cold store, converging on one server with no thundering herd; and the connect-as-server-
   exits race is real and reproducible, with the client's own retry-through-start-if-absent logic recovering
   unmodified. Measurements: `research/spike-results.md` §"Spike 3". **Still open:** none of this was measured
   from an actual hook process invocation (the spike used a plain client script, not the real
   `zikaron-hook`/`zikaron-mcp` clients, which do not exist yet), and **whether a consolidation lease survives
   a service restart in practice is untouched** — M0 had no consolidation state to restart against. Both are
   real integration-test material for M9 rather than open design questions. **Three earlier sub-items closed
   2026-08-01.** The `/proc`-ancestry unknowns
   (process topology, Linux-only `/proc`, pid namespaces, the MCP-first race) are gone with the rung — see
   current-state item 4. The round-7 `session_client` resolution-write cost is gone with the write: the preamble
   no longer touches the store. And **where hook stdout lands is now partly answered**: it arrives as a context
   entry framed *"I have gathered this context from valuable programmatic script hooks"*, positioned **before**
   the user message in the same turn. **The size-cap half is now closed and the answer is a number**: every
   object-format hook entry takes `max_output_size`, default **10240 bytes**, and overrunning it truncates
   **silently**. Shipped entries state **65536** explicitly. What that does *not* buy is a proof — see open
   question 11. What stays open here is that placement is *early*, which contradicts `~/Memory`'s "place
   surfaced memories late" lesson; we cannot choose.
   Worth noting the framing instructs the model to follow requests found in the injected text, directly against
   the untrusted-reference-data preamble `retrieval.md` puts on the push block. Still to carry from
   `~/Memory`: keep surfacing ephemeral and exclude it from the summarizer input — kiro exposes
   `compaction.excludeMessages` and `compaction.excludeContextWindowPercent`.
5. **What tells the agent *why* a demoted memory is being shown?** D25 keeps superseded records surfacing
   rather than hiding them, and D27 cut provenance to three fields. **Narrowed by the corpus review:** the
   display half is now specified — the injected block labels a demoted row and names its replacement's uuid,
   and every retrieved replacement is ordered ahead of every record it replaced
   (`design/retrieval.md` §"Supersession: eligible, demoted, and labelled"; round 2 replaced an
   unsatisfiable "immediately above" rule with this precedence rule, since a merge gives several rows one
   shared replacement; round 3 added the dead-lineage case — an ordinary `retire` of a replacement is legal
   and makes a *terminal component*, so `fetch` now reports `superseded_by_latest_state` and the block's label
   deliberately names only the immediate replacement, keeping the graph out of the ranking path). What stays
   open is *editorial*:
   D27 keeps no reason-for-supersession field, so the block can say "replaced, by that" but not "because the
   pin was bumped", and nothing measures whether the agent needs the reason or whether fetching the
   replacement suffices.
6. **Residual staleness under D11.** The repair loop only fires when a memory (a) surfaces, (b) is acted on,
   and (c) fails *loudly* enough for the agent to attribute the waste to it. It misses silently-obsolete
   memories and memories that stopped surfacing. A known limit, and after D27 there is no cheap mechanism
   behind it. One idea that survives D27's objection: an `amend` variant meaning "confirmed, no change",
   which would make `updated_at` mean *last confirmed working* — real freshness evidence with no false
   positives. Parked, because it adds a discretionary verb and cuts against open question 7.
7. **Write discipline.** Delivery is settled (D18); the content is a v0 draft to experiment against (D30).
   `~/Memory`'s evidence says under-writing dominates, so the draft biases toward recording. Six
   deterministic signals are instrumented to reveal which way it actually errs. Still unaddressed: how much
   detail belongs in `content` versus `gist`, and when to supersede rather than amend in place.
8. **Does model capacity actually help identifier discrimination? Still untested.** The counterfactual
   instrument confirms the weakness is **mechanistically real** — discrimination index **0.194–0.233** for
   all four models, direction right in 14/14 blocks (sign test p≈1.2×10⁻⁴), margin thin. `bge-large −
   bge-small` on that index is **+0.029, CI [−0.016, +0.062]** against a preregistered 0.15 bar, so no
   demonstrated remedy. But fastembed serves a *quantized* small against an *unquantized* large, so this
   compares deployed artifacts, **not** capacity. Matched fp32 exports of one family would settle it.
11. **Nothing bounds a gist's length in bytes, and the hook's output cap is therefore unprovable.**
   Found at distribution time, measured rather than reasoned: `gist_max_tokens` (default 64, maximum 256)
   bounds **tokens**, and the deployed WordPiece tokenizer maps anything outside its vocabulary to a single
   `[UNK]` — so an unbroken 4000-character run counts as **one token**, as do 256 emoji. A gist that passes
   every bound the write path states can therefore be arbitrarily long in bytes, and five of them overflow
   any `max_output_size`, after which the harness truncates the injected block in silence. Ordinary prose
   is nowhere near it: the shipped policy is 2950 B and five prose gists at the 256-token ceiling are a few
   kB, both far inside 65536. The fix is a byte bound on `gist` in `schema.md` §Bounds — a write-path
   change, deliberately not made inside a distribution milestone. Asserted as a test
   (`tests/test_install_limits.py`), stated in `architecture.md` §"The install contract", and named in the
   README's troubleshooting notes so it is not a limit only a test knows. **An earlier version of that test
   asserted the opposite**, by multiplying tokens by an invented four-bytes-per-token factor and calling the
   product a worst case — the review caught it, and the lesson is the corpus's own: name the quantity before
   quoting a number about it.
12. **Merging degrades the gist's triage value, and the tension is structural.** Measured on the first
   real consolidation: **6 of 15** long-term gists came back index-shaped — "three live-debugging
   findings: …, …, …" and, worst, "illness/felt-state+energy findings: placement, attribution,
   code-vs-prompt, severity scale, time-freeze, chronotype calibration" in front of 1877 tokens of
   content. The originals were symptom-first one-liners ("grepping session.log for prompt text returns
   zero because it never logs assembled prompts"), and the consolidator kept that shape wherever it
   promoted a single entry. It could not for a merge, and that is arithmetic rather than disobedience:
   one 64-token gist cannot lead with the observable symptom of six different findings. **The damage is
   asymmetric between the two read arms**, which is what makes it a design question rather than a
   prompt tweak: D21 embeds gist *and* content, so pull survives — a symptom-shaped query still
   returned the right record at rank 1 — while the injected block shows gists **only**, so push
   degrades exactly where D13's relevance triage lives. Levers, none yet tried: a stricter merge
   cutoff so fewer unlike findings fuse; permitting a longer gist on a merged record; or having the
   block show something other than the gist for a multi-finding record. Nothing in the corpus named
   this before it happened.
   **The lever was pulled and measured against a byte-identical store, and it over-shot: 11 merges
   became 0.** Run 1 (old prompt) turned 31 journal entries into 15 long-term records — 13 created, 23
   absorbed, 2 in-place flips, 5 merge targets. Run 2 (new prompt, same store restored from backup)
   promoted all **31 in place**, byte-identical prose, zero merges and zero new rows: consolidation
   flipped tier bits and did nothing else, so the long-term tier is now a copy of the journal.
   **And on this corpus that may well be the better outcome**, which is what makes the result awkward
   rather than clean. Run 1's merges look like exactly the over-fusing `consolidation.md` warns about —
   "two appraiser pitfalls" fused two distinct failures of one component, and "three live-debugging
   findings" fused three unrelated gotchas that merely shared arc vocabulary. Corroborating: **zero
   identical gists** in the corpus, and the 7 dedup offers (0.80–0.84) were judged false positives
   independently by the writing agent, the consolidator, and this session.
   **The decisive limitation is that neither run tested what consolidation is for.** The motivating
   case is the same lesson arriving twice, weeks apart — "the protobuf lesson learned today and the
   protobuf lesson learned three weeks ago". All 31 entries were written in **one session by one
   agent**, so no such pair exists. Run 1 merged things that should not have merged; run 2 merged
   nothing; neither had a true duplicate available to merge. So this experiment cannot distinguish
   "correctly refuses bad merges" from "refuses every merge", and tuning further against it would be
   fitting to a corpus with no positive examples in it. The next real test needs a journal containing a
   genuine repeat, which means a second working session rather than another prompt round. What the
   prompt still lacks is the *positive* criterion — it now has reasons to split and none to merge.
   **Operator decision 2026-08-04: the prompt stays as it is, and is not to be reverted on the strength
   of this result.** Reverting would trade a measured over-correction for a measured over-fusion, on a
   corpus that cannot adjudicate between them; the next consolidation runs against a journal grown by
   real work on `~/Memory`, and that is when the positive criterion gets designed and tested.
   **First lever applied 2026-08-04, and both prompts gained a measured length rule alongside it.**
   The consolidator is now told that an inability to lead with one observable symptom is evidence the
   entries are not one finding, and to prefer two records with sharp gists over one with a table of
   contents — the design's own "over-splitting costs one extra call while under-splitting manufactures
   a false record" argument, applied to the gist rather than to the group. Effect unmeasured: it should
   trade record count for push triage, and only a second consolidation on a fresh journal will show by
   how much. Separately, both texts said only "keep it short; over-long gists are rejected", which
   leaves an agent to discover the bound by losing a call — measured across the 49 real gists in the
   two stores, they run **22-53 tokens (median 34, 10-32 words) and not one exceeded the 64-token
   bound**, while 28 words of ordinary technical prose measures 32 tokens, so the ceiling is roughly 50
   words. Both prompts now say "one sentence of about 20 to 25 words", name the 64-token limit and its
   word equivalent, and state that exceeding it costs the call. Worth noting for anyone chasing this:
   a bounds rejection writes **no event**, so a gist that was refused leaves no trace in the store —
   which is why the one the operator saw rejected is invisible to every query above.
9. **Evaluation** (deferred by D14). Grok named LoCoMo, LongMemEval(-V2), BEAM, HaluMem, LongMemCode,
   PersonaMem, LifeBench, AFTER, EvoMemBench; several may be misremembered, and all are conversational or
   codebase-QA proxies rather than tribal-knowledge tests. The benchmark set is the seed but its residual
   threats are the work: 187 synthetic memories is 1–2 orders below real scale, relevance labels were
   authored by the same agent that wrote the corpus, and query-set independence is attested rather than
   mechanically provable. Real memories from a real repository with independent annotators is the fix.

