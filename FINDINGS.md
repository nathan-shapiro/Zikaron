# FINDINGS — Zikaron

> **Working memory for this project**, maintained by the **memory-researcher** agent. It loads every
> session, so it stays lean: current state, open questions, dogfooding evidence, and an index into the
> design and research record.
>
> **The design lives in `design/overview.md`** — what we are building, the shape of the system, and the
> full D1–D33 decision table *with rationale*. §"Settled decisions" below is a one-line index only. Read
> `design/overview.md` before revisiting any decision, and never re-litigate one from the index alone.

## What Zikaron is
**Zikaron** (Hebrew/Yiddish זיכרון — "memory, remembrance") gives a coding agent the **tribal knowledge** a
project accumulates: how to build and test, which steps fail silently, which env vars the integration tests
need, which API is not safe to use yet and why, what was already tried and how it failed.

Scope line, set by the user: Zikaron is **not** a codebase knowledge base — a separate system handles code
structure, symbols and repo maps. Zikaron stores what is learned by living through the work. The
operational test: *could you learn this by reading the code?* If yes, it is out of scope.

## Design documents
| Document | Covers |
|---|---|
| **`design/overview.md`** | **Start here.** What we are building, the system in one page, provenance, and the full D1–D33 table with rationale |
| `design/schema.md` | v0 SQLite tables, indexes, the retrieval-eligibility predicate and its per-consumer filter table, the `meta` initialization contract, bounds, 20 invariants (21 withdrawn), per-kind event shapes, linked sessions, what is deliberately absent |
| `design/architecture.md` | four components, RPC choice and rejections, request envelope (resolved and bootstrap forms), the two-rung session-label ladder and derived `label_source`, subagent-session push suppression, paths, filesystem security, lifecycle, degraded modes, both tool surfaces, two validation-precedence ladders, error table, distribution artefacts including the consolidator's model field |
| `design/retrieval.md` | the read path: hybrid fusion, push vs pull, fusion depth vs output budget, total order, query construction on both arms for external and internal queries, embedding, no reranker, supersession demotion, the known fusion defect |
| `design/indexing.md` | chunking contract: boundaries, gist-prepending, rollup, atomicity |
| `design/consolidation.md` | grouping mechanism and rejected alternatives, candidate construction, provisional parameter seeds and what they are not, consolidator identity and model, never-lose guard |
| `design/write-policy.md` | the `agentSpawn` prompt text, its rationale, the secrets and poisoning boundary, the operator erasure procedure, six instrumented signals, known gaps |
| **`design/build-plan.md`** | **Per-milestone briefs: scope, normative sections, invariants, done-when, scope fence.** Read the brief for the milestone you are on |
| **`design/coding-standards.md`** | **Binding.** Structure, domain model, typing, the three test tiers, invariant tests, comment rules, dependency rules, the check gate |
| `design/prior-art.md` | `~/Memory` as built, the four divergences and how each resolved, lessons carried across |

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
**Phase: design complete, independently reviewed to approval, operator-reviewed. M0 (spikes), M1 (skeleton
+ the three singletons), M2 (store + configuration) and M3 (records, versioning, receipts) complete; M4 is
next.** D1–D33 settled. Grounding from
`research/initial-brainstorm-transcript.md` and `~/Memory` complete; kiro hook
capabilities verified by probe; the retrieval stack benchmarked and reviewed to approval; schema, architecture,
retrieval, indexing, consolidation and write policy all specified in `design/`. **M0's four spikes all
confirmed their assumption — sqlite-vec, FTS5 external-content, the UDS transport, fastembed cold/warm — with
no D-decision, invariant or table changed.** Two rationale notes were added from what the spikes surfaced (the
FTS5 naive-delete corruption shape; the `asyncio.to_thread` requirement for M9's service, discovered by a
self-inflicted deadlock in the spike server itself). Full measurements: `research/spike-results.md`.

**M1 shipped the package skeleton, the exact-pinned venv and `./check.sh`, plus the three singletons —
`core/errors.py`, `core/events.py`, `core/config/keys.py`.** Reviewed to `APPROVED` over three rounds
(`reviews/m1-skeleton-review.md`). It left two things for the milestones that own them, both now written into
`design/build-plan.md` so neither depends on being remembered: **M2** must make whatever it needs the schema
version for agree with the one declaration already in `errors.py`, and **M3** must settle `inactive_row.state`'s
value set in the design before defining the row-state enum — the design gives the row-state vocabulary in the
MCP tool surface but states no set on the error row, so two implementations could disagree today. Also worth an
operator's eye: the design deliberately spells the same situation two ways, error `no_read_receipt` (−32002)
against event kind `no_receipt`. Both are pinned by a test so neither gets tidied into the other.

**M2 shipped the store and the two-layer TOML config resolution — `core/store/` (`ddl.py`, `meta.py`,
`permissions.py`, `store.py`, `embedder.py`) and `core/config/resolution.py`.** Reviewed to `APPROVED` over
**five** rounds (`reviews/m2-store-config-review.md`) — longer than the self-review skill's usual three, and
deliberately so, since every round through the fourth found a genuine, independently verified defect rather
than a manufactured one, and the fifth found none. `Store.create` validates the effective `embed_dim`, checks
the configured embedder's *actual* reported width and model name against it, and only then runs any `CREATE`
statement, with no database file on disk if either check fails. `Store.open` re-validates on every call:
the `reindexing` sentinel, all five required `meta` keys, the physical `memory_vec` column's own recorded
width (not only `meta`'s claim about it), `schema_version`, and the effective config's `embed_model`/`embed_dim`
— existing-only, via SQLite's `mode=rw` URI, so a missing store is reported rather than silently created.
Config resolution merges three layers (built-in defaults, system-wide, project override) per key at depth 2,
rejects an unknown key or a wrong TOML type per file at parse time, and range-validates the merged result;
`EffectiveConfig` self-validates on construction rather than trusting only its one real caller. Filesystem
permissions are enforced on both create and open, and a store reached through a symlinked ancestor — not only
a symlinked `.zikaron` itself — is refused. Invariant 1 has no enforcement code at this milestone and the test
file says so explicitly, per `coding-standards.md`'s own escape hatch for a genuinely untestable invariant;
M4's indexing path is where it becomes real. 256 tests, 100% branch coverage on `zikaron/core`.

**M3 shipped `core/records/`** (`receipts.py`, `supersession.py`, `memory.py`) — the row-level primitives
`create`/`amend`/`retire`/`fetch` compose, with optimistic-concurrency versioning, read-receipt mint/spend/
revocation, and the supersession graph's write-time checks. Settled the one item M1 deferred:
`inactive_row.state`'s value set is now `superseded | retired` (never `live`, by construction), encoded as
`RowState`/`INACTIVE_ROW_STATES` in `errors.py` and stated in `architecture.md` §Errors. A real design
boundary drawn here, not merely an implementation choice: `create`/`amend` do **not** emit `remember`/`amend`
`event` rows, because those kinds carry `token_count`/`gist_tokens`/`n_chunks`/`truncated` — chunking-preflight
outputs `indexing.md` assigns to M4 — and `schema.md`'s own nullability table does not list them as nullable
for these two kinds the way it does for `merge`/`promote`'s non-authoring rows, so a value M3's fake embedder
cannot produce honestly must not be invented. `retire`/`fetch`/`version_conflict`/`no_receipt` carry no such
dependency and are fully M3's own. Transaction handling required getting the invariant-10 rejection carve-out
right, and getting it right took two of the four review rounds: `_reject_version_conflict`/`_reject_no_receipt`
stage a receipt and event and raise, but never commit — only the transaction-*owning* wrapper
(`create`/`amend`/`retire`/`fetch`, never the neutral `_<verb>_within_transaction` core M4 composes into its
own wider transaction) decides commit-versus-rollback, via one function, `_commit_or_roll_back`, that inspects
the raised error's code. Three small value
types (`CallParams`, `Rewrite`, `ReceiptKey`) exist because bundling them was the correct fix for genuine
`PLR0913` violations, not a suppression — each is a natural grouping the design already implies (an RPC call's
constant fields; a full rewrite's two fields; `read_receipt`'s own primary key). **Reviewed to `APPROVED` over
four rounds** (`reviews/m3-records-review.md`), and the first two rounds changed the transaction architecture
materially rather than only its prose: round 1 found the retire ladder checked an unknown `superseded_by`
target's existence *after* the source's own version and receipt, contrary to `architecture.md`'s fixed rung
order, and found the single-row conflict payload wrongly wrapped in a list where the tool surface states one
object. Round 2 found the fix for a third round-1 defect — that the whole transaction-owning API could not
compose into M4's wider transactions, since a nested `BEGIN` raises `OperationalError`, verified empirically —
was itself unsafe: splitting each verb into a transaction-owning wrapper around a neutral
`_<verb>_within_transaction` core left the neutral core's own rejection helpers still calling `db.commit()`
directly, which could durably commit an outer composing caller's earlier writes. The structural fix moves that
decision into one function, `_commit_or_roll_back`, that inspects the caught error's code and lives only in
the wrappers; the neutral cores now never touch the transaction on any path. Round 2 also caught the
concurrent-cycle acceptance test racing an already-illegal graph instead of two legal opposite edges on an
edgeless pair, and two missing end-to-end regression tests for the corrected ladder order — both added and
verified by mutation testing to fail against the pre-fix code. 333 tests, 99.82% coverage on `zikaron/core`;
the one remaining uncovered branch (`supersession.py`'s defensive row-is-None case inside the chain walk) is
documented in-code as unreachable through any well-formed call, since `superseded_by`'s `ON DELETE RESTRICT`
foreign key makes the state it guards against impossible to construct without disabling FK enforcement.

**Sixteen rounds of independent review, ending APPROVED with no open blockers.** Rounds 1–12 covered the
corpus, 13–16 the operator-review delta. 26 findings in round 1, ~130 across all sixteen; every one accepted,
**no user decision reversed in any round**, and roughly twenty D-row *rationales* corrected where one asserted
more than its mechanism or evidence supported. The blow-by-blow — every finding, response and rejection — is
`reviews/design-corpus-review.md`; the corrections themselves live in the D-rows they amend, in
`design/overview.md` §4. Do not reconstruct that history here.

**The operator review raised four things.** (1) *Why is the event log in the database?* — answered, no change:
`.zikaron/service.log` covers operational logging, while `event` is instrumentation whose signals are
relational joins and whose rows must commit in the same transaction as the mutation they describe (invariant
10), which a file cannot do. It did expose a real gap — retention was one unexplained line. (2) *Why is config
in `meta`?* — a genuine conflation, now **D33**. (3) *Event-log retention* — never pruned on a schedule;
`design/schema.md` §"Retention: `event` is not pruned". (4) *Is the `/proc`-ancestry rung needed?* — **measured:
no**, and the machinery is deleted; see **D31**, `design/architecture.md` §"Both clients resolve the same
label" and §"Subagent sessions". Raw probe evidence: `research/kiro-session-id-probe.jsonl`.

## Build plan — start here when writing code
**Read `design/coding-standards.md` before writing any code; it is binding, and its check gate is the
definition of done.** Per-milestone briefs — normative design sections, invariants to cover, done-when, and an
explicit scope fence — are in **`design/build-plan.md`**. Work the lowest-numbered incomplete milestone; do not
skip ahead, since each assumes its predecessors are built and tested.

**`zikaron-core` is deliberately split into seven milestones (M2–M8) rather than built in one pass.** One-shot
it would be a few thousand lines with no verifiable intermediate state, and the first end-to-end test would
arrive only after all of it existed. The design already supplies the seams: twenty invariants each attached to
a layer, two validation ladders, and a state machine — so a milestone is done when its invariants have tests
that fail when violated. M1, M8, M10 and M11 are *not* split further; the two clients are thin by design.

| # | Milestone | Done when | Status |
|---|---|---|---|
| **M0** | **Spikes** — sqlite-vec + the `float[<dim>]` template, FTS5 external-content under amend and erasure, UDS round-trip cold/warm + start-if-absent race, fastembed cold/warm | `research/spike-results.md` records each measurement; any failed assumption has a design correction applied | ✓ |
| M1 | Skeleton + check gate; the three declarative singletons (error codes, config keys, event kinds) | gate passes; a test asserts each singleton matches its design table exactly | ✓ |
| M2 | Store + configuration | invariants 1, 3, 11 tested; create→close→open round-trips; dimension mismatch rejected before any table exists | ✓ |
| M3 | Records, versioning, receipts | invariants 4–10 tested (10 is cross-cutting — M4/M6/M7 re-assert it for their own verbs); a version bump revokes others' receipts but not the writer's; a consolidator receipt cannot license an `mcp` amend | ✓ |
| M4 | Indexing — chunking, FTS5 sync, vector writes, **atomic** amend | invariant 2 tested by raising mid-transaction; chunk boundaries deterministic across runs | ☐ |
| M5 | Retrieval — arms, RRF, eligibility, rollup, demotion, stop reasons | invariants 18–20 tested; one eligibility implementation used by all five consumers; a superseded row surfaces demoted, behind its replacement | ☐ |
| M6 | Write path + D15 dedup hand-back | a conflict returns the full record and its receipt in one round trip; rejection paths emit exactly the events the signals need | ☐ |
| M7 | Consolidation — grouping, state machine, leases, the four verbs | invariants 12–17 tested; the A~B/B~C/A≁C chain does not over-merge; a second worker in one session with a different pid gets `{busy: true}` | ☐ |
| M8 | D30's six signals as executable SQL | each runs against a fixture whose expected value is hand-computed in the test; a post-deadline follow-up cannot change a matured classification | ☐ |
| M9 | Service — UDS, JSON-RPC, preamble, lifecycle | integration tests cover the start-if-absent race, connect-as-server-exits, a stale socket, and a refused foreign-store handshake | ☐ |
| M10 | MCP client — 5 primary tools, 4 consolidator tools | a consolidator config provably cannot reach `search` or `fetch` | ☐ |
| M11 | Hook client — suppression, degraded chain, always-exit-0 | a test asserts stdlib-only imports; every failure mode exits 0 with empty stdout | ☐ |
| M12 | Distribution — agent config, skill, hook entries (stable + `--v3`), policy asset | a clean install on a fresh directory does push, pull, write and a consolidation run | ☐ |

**M0 is first and is throwaway.** Four assumptions underpin the architecture and none has been exercised in
code; finding a broken one in a 50-line spike costs an afternoon, finding it after M2 means rewriting the
store. This is open question 4 turned into a task.

**Two standing instructions.** Ship D30's six signals as **executable SQL** (M8) rather than spending another
design round on them — that is the review's own recommendation, and the reason is that a unit mismatch then
becomes a wrong number instead of a prose ambiguity. And **do not tune RRF during M5**: open question 2 is the
largest known quality lever, it needs no reindex, and it is deliberately post-build.

## Open questions
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
3. **The real length distribution of memories is unknown.** D28 settles the chunking mechanism, but its
   parameters rest on zero real data, and the benchmark's six over-length fixtures turned out to be one
   template wearing six hats. `token_count` and the `truncated` canary are instrumented so revisiting
   `chunk_max_tokens` — and chunking itself — becomes a measurement.
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
   the user message in the same turn. Two things that leaves open — whether any size cap applies, and that
   placement is *early*, which contradicts `~/Memory`'s "place surfaced memories late" lesson; we cannot choose.
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
9. **Evaluation** (deferred by D14). Grok named LoCoMo, LongMemEval(-V2), BEAM, HaluMem, LongMemCode,
   PersonaMem, LifeBench, AFTER, EvoMemBench; several may be misremembered, and all are conversational or
   codebase-QA proxies rather than tribal-knowledge tests. The benchmark set is the seed but its residual
   threats are the work: 187 synthetic memories is 1–2 orders below real scale, relevance labels were
   authored by the same agent that wrote the corpus, and query-set independence is attested rather than
   mechanically provable. Real memories from a real repository with independent annotators is the fix.

## Dogfooding notes (evidence from our own sessions)
- **A self-delegated subagent does not inherit the `subagent` tool.** The crew system strips it, so a
  spawned `memory-researcher` cannot delegate further. A brief instructing one to obtain an independent
  review was therefore unsatisfiable; it degraded to self-critique and disclosed that clearly. Verify a
  delegate's capabilities before writing a brief that depends on them.
- **The review loop earned its cost.** Three rounds of independent critique overturned four of the first
  benchmark run's eight conclusions — including killing our own `tokens`-column proposal and inverting the
  reason for keeping `bge-small`. A self-graded benchmark would have shipped all eight.
- **Authorship independence has to be structural, not promised.** Blind query authoring only worked because
  the blind author ran as a separate pipeline stage with no access to the corpus, before it existed.
- **This file is now a live test of D4's progressive disclosure.** The decision *gists* stay loaded every
  session; the rationale is fetched from `design/overview.md` on demand. If a future session re-litigates a
  settled decision because the one-line index was not enough, that is direct evidence that gist-only
  surfacing is too thin — which is exactly what D13 and D21 are about.
- **Twelve rounds of review made an unnecessary mechanism airtight.** The `/proc`-ancestry rung of the
  session-label ladder was introduced in round 3 and hardened through round 8: a defined race outcome, a
  fail-closed ambiguity rule, a `register_session` RPC with a named sender, a durable `session_client`
  provenance table, an `event.label_source` copy, invariant 21, durability-precedes-adoption, and a rung-0
  error code. Every round found a genuine internal defect and every fix was correct. **None of it could tell us
  the premise was false.** One `env` check did: `KIRO_SESSION_ID` is in every process kiro spawns, including
  live MCP servers, so the case the rung existed for never occurs. The lesson is not "review less" — the same
  loop caught eleven other classes of defect that measurement would not have. It is that **internal review
  pressure-tests consistency, not premises**, and a corpus needs a distinct mechanism for the second: an
  explicit list of assumptions about the environment, each with a named cheap experiment. The corpus's own
  phrase "specified but unverified" is the only reason this was findable, so the practice to keep is writing
  that phrase into the design and then *acting* on it before building around it. Directly a Zikaron
  requirement: a memory that is internally coherent and premised on something no longer true is precisely the
  confidently-stale memory D11 exists for, and no amount of self-consistency checking detects it.
- **A drift guard that re-transcribes the table only guards one direction.** M1's job was "a test asserts each
  singleton matches its design table exactly". The obvious build — compare the code against a second, hand-typed
  copy of the table in the test — catches a code edit and is blind to a *design* edit, which is the likelier one
  because the design keeps being revised. So the tests parse the design markdown at test time and compare. What
  made that a claim rather than a hope was **mutation testing**: 100% branch coverage over 102 tests said
  nothing at all about whether any guard could detect drift, while 31 deliberate one-line mutations — 12 of them
  on the *design* side — did. All 31 tripped. Coverage measures which lines ran; only mutation measures whether
  a test can fail.
- **Every defect three review rounds found in that parser was the same shape: a reader that returns a
  *plausible* answer instead of raising.** Not "returns nothing" — that fails loudly and is safe. The dangerous
  set: a heading occurring twice read as the first copy; a revised TOML sample added beside the old one and
  ignored; two contradictory bullets resolved by document order; one stray unterminated fence hiding every later
  heading while everything before it parsed perfectly. My first fix for the first one was *placed where it could
  never fire*, which the second round caught. Two practices carried: for each reader, enumerate how it could
  return the **wrong** thing rather than no thing; and write the test as a stale-read scenario where the stale
  answer is exactly what the code already agrees with, since that is the case that would have passed.
- **The design stated one fact in four places and in collective terms, and that made it unguardable.**
  Event-detail nullability was written inline in one field's value set, as a clause on two rows, as a paragraph
  about "the two dense fields", and — for `retire.superseded_by` — only inside a signal's query. Collective
  references cannot be parsed, so the choice was a code-side transcription nothing checks, or gathering the
  statements. Gathering won: `design/schema.md` now has a nullability table that invents nothing and says
  explicitly that a field's absence means the document is silent, **not** that null is impossible. Directly a
  Zikaron requirement: a claim whose qualifier lives in a different paragraph will be recalled without its
  qualifier.
- **A scope fence protects against building the next milestone's behaviour, not against finishing this one's
  data.** I deferred the event `detail` closed value sets (`role`, `form`, `phase`, `demotion`, the stop reasons)
  to M5/M7 on the grounds that their domains live there, and the reviewer overruled it: they are stated *inside*
  the very table M1 owns, my parser was already reading those cells and discarding the values, and deferring
  them would have forced M5/M7 to invent literals. The distinction worth keeping is that M1 correctly refused to
  write a row-state enum for `inactive_row.state` — that would have required *deciding* something the design
  does not state, which is a different act from transcribing something it does.
- **A large hub document crowds the index it shares with focused ones.** `design/` is indexed in the
  knowledge base as `zikaron-design` (9 items). First real query — "why was grouping consolidation by
  session rejected" — returned the correct passage, but **two of three results were chunks of
  `overview.md`** rather than of `consolidation.md`, which actually answers it. `overview.md` is the largest doc
  and carries the whole decision table, so it matches nearly any design query and competes with the
  specific spec. Same phenomenon Zikaron will hit when one accreted memory outranks the precise one. Worth
  watching; if it worsens, the fix is to index the specs and keep the hub out, or split the decision table
  out of the overview.
- **This knowledge tool lists results in ascending score order.** In that same query the scores ran
  0.5163 → 0.5899 → 0.5999, so the best match printed **last**. Trivial to misread as "top result first",
  and a reminder for our own surface: an injected block whose order does not mean what the reader assumes is
  worse than one with no order at all.
- **A looping subagent stage's prompt is static, so any state it asserts goes stale.** The design-corpus
  loop's remediation brief said "round 8's findings are outstanding" — true when written, false by the third
  iteration, and two remediation runs opened by correcting me before doing the work. They were right to.
  Write loop prompts to *derive* current state ("address the newest round with no response") rather than to
  name it. Directly analogous to what Zikaron is for: a confidently stale instruction is worse than none.
- **Sixteen rounds found the same handful of defect classes over and over.** Worth keeping as a checklist,
  because each is a rule that is *correct about the case it names and silent about the set it implies*:
  *stable is not shared* (both clients held a stable label; the signals needed the **same** label);
  *a rejection can still be a read* (a `version_conflict` payload returns the full record, so checking versions
  before authorization turned `merge` into the `fetch` D32 withholds);
  *a disposition is not always a write* (serve-time vacating could empty a group with no write verb to close it);
  *derived expiry has two sides* (treating a lapsed lease as expired stranded its own owner);
  *a fallback can be a bypass* (the degraded read answered `bad_config` and `reindexing` too);
  *the observable was specified and the state behind it left to be inferred* (a reported `of` with no stored
  count, a depth with no stop reason);
  *a rate whose unit differs on the two sides is not a rate* (rows over calls; a condition with no aggregation
  unit);
  *the fix was recorded somewhere the reader does not look* (a read-side rule for a write-side fact; an erratum
  applied to the design but not to the cited artifact);
  and *the fix landed in the normative place and not in its summaries* — which is what rounds 13–16 were almost
  entirely about, and the one I kept committing myself.
  One meta-lesson above them: **name the quantity before quoting a number about it.** Two consecutive rounds
  failed on the *estimand* rather than the statistics — a figure that did not measure the axis it was cited for.
- **Sixteen review rounds grew the corpus ~6×** (11.5k → 66k words) with no user decision reversed. Three
  observations worth carrying. Rounds 9–11 were *all* about D30's six instrumented signals, because the
  instrumentation spec is the only part of the corpus with no consumer — invariants and validation ladders
  pressure-test everything else, while a signal definition is checked only by reading it; the remediation's
  own recommendation is to make "the six signals as executable SQL" a build deliverable rather than run
  another design round. Round 9's defect was created by round 8's fix, and merely by *naming* a set.
  And `shard_count` (round 5) is flagged as the one mechanism plausibly not needed — a persisted count an
  invariant then has to police, when it is derivable as a `COUNT(*)`; left alone pre-code, recorded so it
  need not be rediscovered.
- **A design rule stated for one caller's situation is not automatically a rule for every function that touches
  the same fact.** `architecture.md` says "`realpath` the store directory and require the resolved parent to
  be the cwd" — true and load-bearing for `zikaron-service`, which derives the store path *from* its own cwd in
  the first place (D17). Read literally and implemented inside `Store.create`/`Store.open` themselves, it broke
  33 of the milestone's own tests immediately, because those two functions take `store_dir` as an explicit
  parameter and have no way to know whether the caller's cwd is the concept the caller meant by it — a test
  fixture, or a future tool iterating several projects' stores from one process, is not the service. The fix
  was not to route around the failing tests; it was to ask what the rule actually protects against (a symlink
  hijacking the path between what the caller believes and what the filesystem holds) and implement *that*,
  independent of the ambient process cwd. The general lesson: a design sentence written from one component's
  vantage point can be true and still be the wrong thing to copy verbatim into a different component's code,
  and a sudden wall of test failures is worth reading as "the design's premise doesn't hold here" before it is
  read as "route around this."
- **The same ~15 lines of test infrastructure took four consecutive review-round fixes for one bug class, each
  narrower than the last, in a way worth naming precisely because "we fixed the multiline-string bug" is a false
  summary of what happened.** A hand-rolled SQL statement scanner (backing the DDL drift guard, itself built to
  stop the design and the code from silently disagreeing) needed to know, for every line it read, whether that
  line was inside a quoted string literal — because a string can legally contain a parenthesis, a semicolon, or
  a blank line that must not be read as SQL structure. Four things went wrong in succession, in the same small
  function: whitespace was stripped from a continuation line without checking whether a string was already open
  (round 2); a wholly blank line *inside* an open string was dropped entirely rather than merely having
  whitespace trimmed, because an empty string failed an `if remainder != "":` guard (also round 2); trailing
  whitespace on the line where a string *opens* was stripped because the fix decided for the whole line from a
  single start-of-line flag, which cannot see that the line's own end is a different quote state from its start
  (round 3); and a fresh, empty statement fragment that began immediately *after* a mid-line semicolon inherited
  a stale "started inside a string" fact left over from before that semicolon fired (round 4, and the fix's own
  first attempt was itself wrong, described next). Each fix solved exactly the case in front of it and no more,
  which is what let three further, related cases keep surfacing in the same function — the actual defect was
  never "this one case," it was "deciding whitespace and blank-line handling from state that does not update at
  every point state can meaningfully change," and only round 4's rewrite finally modeled that.
- **The round-4 fix's own first attempt was wrong, and the reason it did not ship wrong is a discipline worth
  keeping as a rule rather than a lucky habit: run the whole related test suite before considering any fix
  done, not just the one test the fix targets.** The first attempt at tracking "did the current fragment start
  inside a string" set a flag only when the fragment's accumulator was empty, on the theory that emptiness meant
  the fragment had just begun. That is false the moment a semicolon resets the accumulator mid-line without the
  fragment actually beginning fresh in the relevant sense, and it passed the new regression test built for
  exactly that case — while silently breaking a *different*, already-fixed case from two rounds earlier (a blank
  line inside a multiline literal), because the flag no longer updated correctly for it. The break was caught
  immediately, before the reviewer ever saw it, only because the fix was checked against the *full* test file
  rather than the single new test — the exact verification discipline this project's own standards ask for
  ("a related set of changes, then the whole suite"), and the exact case where skipping it would have shipped a
  regression under the cover of a passing new test.

## References
_(One line per research note and review: topic — key takeaway — file path.)_
- Prior Grok brainstorm — framing, D1–D9, unverified benchmark list — `research/initial-brainstorm-transcript.md`
  (verbatim extract; the source PDF was deleted 2026-08-01 at the user's request).
- Prior art as built — schema, RRF+recency ranking, `/sleep`, `merge_reframes` — `~/Memory/design/long-term-memory.md`, `~/Memory/design/ltm-revision-revamp.md`; digested in `design/prior-art.md`.
- kiro-cli hooks + `introspect` — exactly 5 triggers (`agentSpawn`, `userPromptSubmit`, `preToolUse`,
  `postToolUse`, `stop`); **no compaction hook** (confirms D10); `userPromptSubmit` and `agentSpawn` are the
  only two whose stdout reaches context on exit 0; `preToolUse` can block via exit 2; hook entries take
  `command` / `matcher` / `timeout_ms` (30 s default) / `cache_ttl_seconds`; **v3 mode uses an incompatible
  standalone `.kiro/hooks/` schema** — a distribution concern —
  `research/kiro-cli-hooks-and-introspect.md`.
- Embedding models for technical prose — bge-small suboptimal not disqualified; **no published evidence
  either way on near-miss identifier discrimination**, closest adjacent result is embedder blindness to
  negation (Nikiema et al. 2025, arXiv:2509.09714, 96.2% FP rate); code embedders confirmed trained for
  NL→code, so wrong task; reranker is a complement not a substitute and needs no reindex; same-dimension
  model swaps corrupt `vec0` silently — `research/embedding-models-technical-prose.md`.
- **Design-corpus review trail** — sixteen rounds, ~130 findings, all accepted, no user decision reversed;
  ends `VERDICT: APPROVED`. The audit trail for every design decision and every rejected alternative, plus an
  `Operator finding` note recording what the 2026-08-01 measurement did to rounds 3–8's remediations —
  `reviews/design-corpus-review.md`.
- **kiro session-id probe, measured** — the evidence that collapsed the label ladder to two rungs (D31). Five
  hook firings across two agents: payload `session_id` == `KIRO_SESSION_ID` for top-level sessions (3/3),
  **differs** for subagent sessions (2/2, payload carries the subagent's own id), and `KIRO_SESSION_ID` is
  present in hook processes, shell subprocesses and live MCP servers while absent from kiro's own —
  `research/kiro-session-id-probe.jsonl`.
- **Embedder benchmark, measured** — the evidence behind D20–D25 and open questions 2 and 8. Preregistered
  effect sizes, 187-memory synthetic corpus, 192 blind prompts authored by an agent that never saw the
  corpus, factorial `tokens`-column ablation, frozen-extractor held-out test, counterfactual
  identifier-swap instrument, reranker latency curve, cold/warm latency table. Independently reviewed to
  **APPROVED over 3 rounds**. Report `research/embedder-benchmark-results.md`; review trail
  `reviews/embedder-benchmark-independent.md`; re-runnable harness + preregistration + gotchas
  `experiments/embedder-precision/README.md`.
- **M0 spike results, measured** — all four architectural assumptions (sqlite-vec, FTS5 external-content, the
  UDS transport, fastembed cold/warm) confirmed, no D-decision, invariant or table changed. Two rationale
  notes added from what the spikes surfaced: the FTS5 naive-delete failure shape (silent wrong answer, then
  corruption on the next touch — `design/write-policy.md`), and the `asyncio.to_thread` requirement for M9's
  service, discovered via a self-inflicted deadlock in the spike server itself
  (`design/architecture.md` §RPC) — `research/spike-results.md`.
- **M1 code review** — three rounds, ending `VERDICT: APPROVED`. Two blockers were the same class twice over:
  design readers that could return a plausible stale answer, and contract *values* omitted from tables whose
  *names* were guarded. Both accepted; the second produced the design's nullability table. One nitpick stands as
  an M3 prerequisite (`inactive_row.state`), recorded in `design/build-plan.md` §M3 —
  `reviews/m1-skeleton-review.md`.
- **M2 code review** — five rounds, ending `VERDICT: APPROVED` with zero findings in the fifth. Every one of the
  first four rounds found a genuine, independently verified defect: invariant 11's physical-`vec0`-width check
  went through three tightenings before it could no longer be satisfied by a string literal merely *quoting*
  the expected DDL shape as data; the filesystem symlink check needed one round to fix and a second to correct
  the author's own over-literal first attempt (comparing against the ambient process cwd, which broke 33 tests
  and was caught before it shipped); `Store.open` gained an existing-only mode so a missing store is reported
  rather than silently created, then a further fix so an *existing* store with a dropped `meta` table is too;
  and the same ~15 lines of test infrastructure (a hand-rolled SQL statement scanner backing the DDL drift
  guard) accumulated four consecutive fixes for progressively narrower instances of one bug class — a
  multiline string literal's internal whitespace and blank lines being mishandled by state that looked
  right for one case and wrong for the next. One of those four fixes was itself wrong on the first attempt
  and was caught only by re-running the *whole* related test suite before calling it done, which is the
  dogfooding-relevant lesson below — `reviews/m2-store-config-review.md`.
- **M3 code review** — four rounds, ending `VERDICT: APPROVED` with one optional nitpick in the fourth. The
  first two rounds changed the transaction architecture rather than only its prose: round 1 found the retire
  ladder's existence rung misordered against version/receipt for an unknown `superseded_by` target, and the
  single-row conflict payload wrapped in a list contrary to the tool surface's own contract. Round 2 found
  that round 1's fix for transaction composability — splitting each verb into a transaction-owning wrapper
  around a neutral `_<verb>_within_transaction` core — was itself unsafe, because the neutral core's own
  rejection helpers still called `db.commit()` directly and could durably commit an outer composing caller's
  earlier writes; the structural fix moved that one decision into `_commit_or_roll_back`, living only in the
  wrappers. Round 2 also caught a "concurrent" cycle test that raced an already-illegal graph rather than two
  legal opposite edges on an edgeless pair, rebuilt as a genuine check-then-write race synchronized on both
  attempts' validation completing before either write. Round 3 found stale docstrings and test narrative
  still describing the removed commit-inside-rejection mechanism, and one event assertion that excluded two
  named kinds rather than asserting the exact list. Round 4: `APPROVED` — `reviews/m3-records-review.md`.
