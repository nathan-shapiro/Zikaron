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
+ the three singletons), M2 (store + configuration), M3 (records, versioning, receipts), M4 (indexing), M5
(retrieval), M6 (write path + D15 dedup) and M7 (consolidation) complete and reviewed to APPROVED; M8 (D30's six signals as SQL) is next.** D1–D33 settled. Grounding from
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

**M4 shipped `core/indexing/`** (`encoder.py`, `chunking.py`, `lexical.py`, `vectors.py`, `writes.py`) — the
chunking preflight, unchunked FTS5 maintenance, chunked `vec0` writes, and `remember`/`amend` as one
transaction each over M3's neutral row cores. **Reviewed to `APPROVED` over four rounds**
(`reviews/m4-indexing-review.md`), with a genuine defect in each of the first three. Three things the design
left to be inferred were settled first and written into `design/indexing.md` §Storage rather than only into
code: `token_count` counts `content` alone on both the row and the event (since `gist_tokens` is a sibling
field that would otherwise be double-counted), `memory_chunk.token_count` counts that chunk's own slice rather
than the assembled gist-prepended sequence (whose length stays derivable from the two), and `part_index` is
**0-based** — contrast consolidation's deliberately 1-based shard index, which is 1-based because it is *shown*
to the consolidator, where chunk parts are shown to nobody. **Two measurements changed the implementation.**
fastembed's own tokenizer carries `truncation.max_length = 512`, so counting through it returns 512 for a
1600-token text: a preflight using it would find every over-length paragraph exactly at the cap, never
hard-split, never set `truncated`, and hand the model the whole paragraph to truncate silently — every recorded
number looking healthy. So counting uses an independent, truncation-free copy built from the same artifact, and
an integration test guards the *premise* by asserting fastembed still truncates. And the deployed `bge-small`
already returns unit vectors, which is precisely why the write path normalizes anyway: D20 keeps the model a
config key, and the cosine arithmetic every threshold in the corpus is written in is true only of unit vectors,
so that guarantee has to be ours rather than inherited. Two further decisions worth keeping: the FTS resync
uses FTS5's explicit `'delete'` command with the **pre-write** values, because the plain
`DELETE ... WHERE rowid = ?` reads the content table and so would have to run before authorization finished —
and invariant 10's carve-out *commits* a `version_conflict`, which would then durably drop a live row's lexical
index on a **rejected** amend; and the indexed write path has **two** verbs, not three, because `retire`
changes no indexed column and D16 keeps its chunks. 416 tests, 99.87% branch coverage on `zikaron/core`, and
**24 injected mutations across the four rounds, all 24 caught.**

**M5 shipped `core/retrieval/`** (`eligibility.py`, `query.py`, `arms.py`, `ranking.py`, `retrieve.py`,
`block.py`, `reads.py`) — both arms, RRF, the five-step total order, the supersession repair, the injected
block, and `search`/`surface` as one transaction each. **596 tests, 99.91% branch coverage on
`zikaron/core`, and 50 injected mutations, all 50 caught. Reviewed to `APPROVED` over three rounds**
(`reviews/m5-retrieval-review.md`), with a genuine defect in each of the first two. Fourteen things the
design left to be inferred were settled in `design/` first, the load-bearing ones being: **the RRF formula
written out** with **1-based** ranks — the base the benchmark measured, and a rebase to 0 changes every fused
score while preserving every arm's order, so nothing downstream could notice; **within-arm ties break on
`uuid`**, because two documents matching one term at equal length return *bit-identical* `bm25()` (measured),
which would otherwise leave arm ranks, and so the fused order, to the query plan; **one read is one
transaction**, since the dense arm's coverage test compares against a `chunk_count` a concurrent write would
otherwise move, which makes the instrumentation write a WAL snapshot upgrade and its refusal a plain
`store_busy`; **the injected block prints whole uuids** (the `…` in the design's sample is elision in that
document, and both "fetch by uuid" and the demotion label's one-call promise are unsatisfiable against a
4-character prefix); and **a read has no `index_failed`** — contention maps, everything else propagates,
because that code's contract names index maintenance and a rolled-back write. Two structural choices worth
keeping: invariant 20 is enforced **at construction** (`ArmOutcome` refuses a depth its own stop reason
contradicts, ranks that are not `1…n`, and a null/null pair on any arm but the lexical one), so an arm that
cannot classify itself honestly cannot exist to be logged; and the transaction envelope M4 spent three review
rounds getting right — the failed-commit, failed-rollback, close-the-connection ladder — moved to
`core/store/transactions.py` rather than being copied, since two copies of "which errors commit" is exactly
how a rejected write comes to commit half an index.

**The review's blocker was a rule this codebase already held on the write side and I broke on the read
side.** The query preflight computed its budget as `cap − specials − count(prefix)` and then embedded
`prefix + kept` **without counting the concatenation** — while `indexing.md` step 7 and its implementation
recount the *assembled* gist-plus-chunk sequence precisely "because the parts' counts are exactly what an
assumption of additivity would be". Tokenization is not additive across a configurable boundary:
`embed_prefix_query` is a free-form string, only the shipped default ends in whitespace, and a prefix without
a trailing boundary fuses with the query's first token and can retokenize into *more* pieces than the two
counts predicted. So a short prompt could be recorded `query_truncated = false` while the model silently
truncated what it was handed — the one failure the whole preflight exists to prevent. The fix counts the
assembled string, shrinks a token at a time until it fits, and reports `query_truncated` from what was
actually kept. Two things that fix taught: my own first attempt introduced a *false* truncation, because
slicing to token boundaries strips leading punctuation from a query that already fitted; and the review's
second round then found that dropping the helper which had derived `n_returned` from `uuids` had
reintroduced a disagreement between them, which mutation testing confirmed as a live survivor. **Both halves
of the general lesson are the same one: a rule stated for one direction of one path is not enforced until it
is enforced at the place the value is produced.**

**Round 2 also made the event log's own contract binding in production.** `EVENT_SPECS` declared every kind's
detail shape, and nothing checked it: details travelled as `dict[str, object]`, so `coding-standards.md` §2's
"every payload becomes a typed object" held for records and not for the log every layer writes into. Each of
the nine kinds that has a producer now has a frozen typed value carrying its own `kind`, so **`log_event`
takes no `kind` argument at all** — filing a payload under the wrong kind is unrepresentable rather than
merely tested — and `EventSpec.validate` remains as defence in depth for what a type cannot enforce at
runtime. The six consolidation kinds stay untyped **until their verbs exist**, since a dataclass nothing
constructs is dead code and `log_event`'s signature leaves no dict-shaped way in; a test asserts exactly
which six those are, so adding a producer without its type fails.

**M6 shipped `core/write/`** (`dedup.py`, `tools.py`) — the tool-facing `remember`/`amend`/`retire`
verbs, composing M3's row primitives and M4's indexed writes rather than reimplementing either.
`remember` runs `indexing.writes.remember_within_transaction`, then D15's dedup search, in one
transaction; `amend`/`retire` delegate the entire ladder to `indexing.writes.amend`/
`records.memory.retire`, catching a caught `version_conflict` and returning it as a typed
`Conflict` value — a Python discriminated union (`Amended | Conflict`, `Retired | Conflict`) a
caller pattern-matches on — while every other rejection propagates unchanged; the tool surface's
literal wire object `{conflict: true, current: ...}` is a transport (M10) concern, not core's.
Two things the design left to be settled in code rather than left ambiguous: `dedup_offered` had
no producer and no typed event value before this milestone — `events.py`'s own docstring commits
to adding one "in the same change" as the verb that writes it, so `DedupOfferedDetail` was added
alongside `remember`, filed under the **candidate's** uuid rather than the new row's, and the
file's stale six-kinds-with-no-producer comment (and its mirroring test) dropped to five. And the
directed score `s(new row → candidate)` D15's threshold is defined over — `schema.md`'s "the best
cosine between X's first chunk and *any* chunk of Y" — is independent of `fusion_depth` and of
which arm surfaced a candidate: a candidate the dense arm's bounded overfetch already scored
carries its own exact `best_distance`, and a candidate the **lexical** arm alone surfaced is scored
by one further batched statement using `sqlite-vec`'s own scalar `vec_distance_L2` function,
grouped by candidate and bounded by their own chunk counts rather than by store size — delegating
the exact arithmetic to the same pinned extension the dense arm's KNN path already uses, rather
than a second implementation of the metric that could disagree with it at a threshold boundary.
**Reviewed to `APPROVED` over four rounds** (`reviews/m6-write-dedup-review.md`), with a genuine
defect in each of the first three. Round 1's blocker was exactly the shape open question 5's own
lesson warns about: the first implementation conflated "what the dense arm's bounded probe
happened to surface" with the mathematically-defined directed cosine, silently excluding every
lexical-only candidate from ever being offered regardless of true similarity — caught only by
writing the regression the round asked for, which failed against the first attempted fix (a
KNN query sized to the *candidate's* own chunk count, which is wrong because `vec0`'s `k` is a
*global* rank cutoff and can return zero rows belonging to the memory it was aimed at). Round 2
found the corrected fix technically right but operationally unsound: it ran one unbounded,
full-index KNN probe per lexical-only candidate inside the open write transaction. Round 3 found
the interim fix for that — a batched read of just the named candidates' own stored vectors,
scored with a hand-written Python L2 loop — introduced a subtler risk: decoding float32 to Python
binary64 and re-summing has different rounding characteristics than the pinned extension's own
native arithmetic, so a candidate at the threshold could clear it under one arm's scoring and not
the other's. The round 3 fix, confirmed by directly querying the installed extension rather than
assuming its capabilities from the design corpus's own stated vocabulary, delegates the arithmetic
to `vec_distance_L2` itself — the same function measured bit-identical to `vec0`'s own KNN-reported
distance for the same vectors. 642 tests, 99.83% coverage on `zikaron/core` (`write/dedup.py` at
100%); the two remaining uncovered lines are the established documented-unreachable-defensive-
branch pattern this corpus already carries from M3 and M4, not new gaps. One real defect surfaced
by writing the tests rather than by review: three setup steps had a second session call `amend`
without first calling `fetch` to earn a receipt, which is not a `version_conflict` scenario at
all — a session with no receipt for a row it never touched gets `no_read_receipt` regardless of
which version it presents, since D26's read-before-write is a receipt fact, not a version-guessing
game. The fix mirrors what `retrieval_fixtures.Harness.retire` already does for the identical
reason: fetch first, to earn the receipt the real ladder requires.

**M7 shipped `core/consolidation/`** (`context.py`, `runs.py`, `groups.py`, `rowstate.py`,
`grouping.py`, `planning.py`, `payload.py`, `candidates.py`, `serving.py`, `authorization.py`,
`verbs.py`) — D29's grouping, the run and group state machine with its leases, and the four
consolidator verbs. **790 tests, 99.72% branch coverage on `zikaron/core`, 29 injected mutations, all
29 caught. Reviewed to `APPROVED` over two rounds** (`reviews/m7-consolidation-review.md`).
**Ten things the design left to be inferred were settled in `design/` first**, the load-bearing ones
being: **group order is `(created_at, uuid)`, named once**, because five things are defined over it
(delivery order, `remaining_uuids`, the gist concatenation, the shard cut, `order_key`'s own minimum)
and a statement of it per site is five chances to drop the tiebreak; **an anchored group gets no
cohesion pass**, because the anchor *is* its cohesion criterion while an orphan set has no common
centre; **the anchor is the highest-*ranked* record clearing the floor**, not rank 1 gated — the two
readings are both available from one sentence and give different partitions, since RRF fuses two arms
while `s(X → Y)` is a dense quantity; **`n_gists_used = 0` serves no candidates at all**, because
`candidates` is a merge *authorization* set and a query assembled from the prefix alone would
authorize whichever records sit nearest nothing; **a `pending` group named by a write verb answers
`not_in_group`**, the one status rung 2's own list omitted; and **invariant 14 was rewritten**, because
it called `run_id` internal while the `next_group` payload has always carried it — resolved as a
carve-out rather than a removal, since no verb accepts `run_id` and it authorizes nothing.
Three structural choices worth keeping. **The two row-state re-checks evaluate
`eligibility.CONSUMER_FILTERS`' own SQL clause** rather than mirroring it in Python: the serve's
vacating test and the ladder's rung 6 must apply the *identical* predicate — the design says so
twice — and `row.tier is Tier.JOURNAL and row.active` would be a second statement of a rule with one
home, surviving a change to that table while still passing. **`s(X → Y)` moved to
`retrieval/similarity.py`**, because all three cosine cutoffs threshold one quantity and two
implementations of it would put a pair on opposite sides of a floor depending on which caller asked.
And **a version conflict is *returned* as a typed `GroupConflict` while `no_read_receipt` is
*raised*** — the tool surface states the conflict as a response shape carrying `remaining_uuids`,
which only a read inside the transaction can produce, so returning it keeps that read where it belongs
and makes the committed audit trail ordinary rather than a carve-out.
**An operator decision reversed the round-1 blocker's *remedy*, and sharpened the reasoning behind it.**
The blocker itself was real — `plan_groups` displaced a live worker with nothing stating that it may — but
the fix I chose, refusing with `{busy: true}`, was wrong about the requirement. The user pointed out the
case it strands: refusing pins the store for up to `run_lease` on a worker that has stopped, and **nothing
inside the store can tell a stopped worker from a slow one**. A lease is a timer. A pid check is better than
it looks — measured, a consolidator's MCP client normally exits with its own subagent — but it cannot carry
the decision: it answers whether a process exists, never whether a worker will progress; pid reuse can return
a false *alive* and prolong the very lockout being diagnosed; the service and the client are not guaranteed a
shared pid namespace; and whether a **cancelled** turn tears the client down is unmeasured
(`research/kiro-mcp-lifecycle-probe.md`). The one piece of evidence that exists is outside
the store — a human invoking the skill again — and `plan_groups` is where it arrives. What D32's tool
omission buys is narrower than "no model can reach it": a model confined to a configured tool surface cannot
*request* a takeover, while the consolidator's own client calls the RPC by design — at most once
*successfully* per process, immediately before the first `next_group` it forwards — and any same-uid process
can speak to the socket directly. So **an explicit `plan_groups` now takes the run
over unconditionally**, `next_group` still refuses a stranger, and the displaced run is closed
**`taken_over`** rather than `abandoned` — a new `RunStatus`/`RunPhase` value, because a user retrying in
one kiro session presents the same `session_id` and only a different pid, so nothing else would separate
"the holder restarted its own run" from "the holder was displaced". What makes this safe is the ladder
rather than a convention: rung 2 requires a group's run to be owned by the caller *and* effectively active,
so the displaced worker can commit **nothing** after the takeover instant — asserted directly, not argued.
The general lesson is about the *estimand* again: I had been treating "is this worker still entitled to the
lease" as answerable from stored state, and it is not; the only liveness signal available is a human
action, and a design that refuses to use it substitutes a timer for evidence.

**What round 1 actually found, stated so it cannot be read as the current design.** `plan_groups` called
the neutral planning core directly, and that core's first act closes any stored `active` run as
`abandoned` with no ownership test — so a second worker displaced a live one through the explicit RPC
while `next_group` answered `{busy: true}`, and *silently*, because the victim's next call found its own
run abandoned and was told `group_expired`. Two things were wrong and only one survived review: the
**silence** was a real defect, and the **absence of a stated policy** was too, since the code and
`architecture.md` disagreed. My remedy — refusing with `{busy: true}`, and a `PlanOutcome = Run | Busy`
result — was overturned by the operator for the reason above; that union and its test helper are gone,
and takeover is unconditional. What survives from round 1 is the diagnosis of *how* I got there: my
docstring reasoned that the check "belongs where the busy shape can be returned", which is true of
`next_group` and false of the reachable entry point beside it — capability answered in place of
reachability. **Round 1's second blocker was an invariant test that could not fail**: invariant 13's guard counted one
`memory_fts` row, and an external-content table has one row per content row *whatever was indexed*, so
it would have passed a merge that indexed only the gist. It now forces the content across several dense
chunks and matches a nonsense token appearing only in the last paragraph.

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
| M4 | Indexing — chunking, FTS5 sync, vector writes, **atomic** amend | invariant 2 tested by raising mid-transaction; chunk boundaries deterministic across runs | ✓ |
| M5 | Retrieval — arms, RRF, eligibility, rollup, demotion, stop reasons | invariants 18 and 20 tested (19 moved to M7, which owns the table it constrains); one eligibility implementation used by all five consumers; a superseded row surfaces demoted, behind its replacement | ✓ |
| M6 | Write path + D15 dedup hand-back | a conflict returns the full record and its receipt in one round trip; rejection paths emit exactly the events the signals need | ✓ |
| M7 | Consolidation — grouping, state machine, leases, the four verbs | invariants 12–17 tested; the A~B/B~C/A≁C chain does not over-merge; a second worker in one session with a different pid gets `{busy: true}` from `next_group` | ✓ |
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
10. **Takeover's caller is specified and its premises are now measured — one item remains open.** The
   consolidation lease is taken over by an explicit `plan_groups`, on the reasoning that a human
   reinvoking the skill is the only liveness evidence that exists. A targeted review caught that nothing
   *converted* that invocation into the call: a fresh consolidator's own first tool call is `next_group`,
   which refuses a live foreign run, so the takeover path was unreachable through the real client path.
   The bridge is now specified — `zikaron-mcp` calls `plan_groups` with its own `(session_id, pid)`,
   **lazily, immediately before the first `next_group` it forwards, and at most once *successfully* per
   client process** — and it is an M10/M12 done-when.
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
- **A test written to cover a line can bless the bug on it, and coverage will call that progress.** Chasing
  the last uncovered branch in M4's hard split, I wrote a test for a defensive path that returned the paragraph
  whole when the tokenizer reported no token boundaries — and asserted exactly that. The returned chunk was over
  its own budget, i.e. a sequence the model truncates silently, which is the single failure chunking exists to
  prevent; the reviewer caught the test and the code together. Two practices follow. **Coverage should be a
  by-product of asserting behaviour, never the reason a test exists** — the standards' own "do not chase 100%"
  is about test *value*, and this is the shape the violation takes when you do. And **for a defensive branch,
  write the assertion as "this is refused", not "this is what comes back"**: if returning something plausible
  were acceptable there, the branch would not need to exist. The general fix was better than the reported one —
  a post-condition that recounts every emitted chunk against the budget it was cut to, so the whole class is
  caught rather than the one branch patched.
- **Three rounds on one guard, each finding the previous fix incomplete in the same direction.** The hard split
  went: return a plausible invalid plan (round 1) → refuse only when the spans are *empty*, missing a
  well-formed but **short** span list that drops a paragraph's tail while every later check passes (round 2) →
  compare the span count against a fresh token count at the one place the cut is made (round 3, correct).
  Identically for the transaction wrapper: map every driver error to `index_failed` → distinguish contention but
  leave `BEGIN`/commit unmapped → map all three, and then discover a *failed commit* was reported without being
  rolled back → and finally that a failed *rollback* leaves a poisoned connection on which a write already
  reported as failed can still be published. The recurring lesson is not "review more"; it is that **a fix
  aimed at the reported case tends to inherit the reported case's narrowness.** Both fixes only stopped
  regressing once they were stated as a property of the whole operation — *the emitted chunks account for every
  counted token*, *the connection ends outside a transaction whatever happened* — rather than as a check on the
  input that failed.
- **A verification instruction has to be satisfiable by the agent receiving it.** Every review brief told the
  reviewer to verify the check gate independently rather than trust my numbers; its session exposes no
  process-execution tool, so it could not, and said so plainly in round 3. Same family as the
  subagent-cannot-delegate finding: the brief asked for a capability the delegate did not have. What it cost is
  worth naming precisely, because the review was still valuable — every finding it made was found by *reading*,
  and the one thing it could not do was confirm that what I said had run had run. So the division of labour is
  fine as long as it is stated: the reviewer reads, the author runs the gate, and the author's claims about test
  results are exactly the part no reviewer is checking. That is the argument for mutation testing being the
  author's job and not a nicety — 24 injected mutations across four rounds are what make "the suite would catch
  this" a claim rather than an assurance.
- **An ambiguous rule in a binding document gets resolved silently, three milestones in a row.** The test-tier
  table said `integration` means "real sqlite-vec", and M2, M3 and M4 all built real-store tests in the default
  tier without marking them — because sqlite-vec is an in-process pinned extension, not a service. Nobody
  decided that; it just happened, three times, and M4's test file then *claimed* to be a unit tier while using
  a real store. The reviewer read the table, not the habit, and was right to. The fix that matters is not the
  label: it is that `coding-standards.md` §4 now states where a real store sits and why, so the fourth
  milestone to face the question reads an answer instead of repeating a decision nobody wrote down.
- **A fix's own first attempt can be wrong, and the discipline that catches it is running the whole related
  suite rather than the one test the fix targets.** The first attempt at tracking "did the current fragment start
  inside a string" set a flag only when the fragment's accumulator was empty, on the theory that emptiness meant
  the fragment had just begun. That is false the moment a semicolon resets the accumulator mid-line without the
  fragment actually beginning fresh in the relevant sense, and it passed the new regression test built for
  exactly that case — while silently breaking a *different*, already-fixed case from two rounds earlier (a blank
  line inside a multiline literal), because the flag no longer updated correctly for it. The break was caught
  immediately, before the reviewer ever saw it, only because the fix was checked against the *full* test file
  rather than the single new test — the exact verification discipline this project's own standards ask for
  ("a related set of changes, then the whole suite"), and the exact case where skipping it would have shipped a
  regression under the cover of a passing new test.
- **An unclosed database handle did not leak memory; it hung the entire test run for over an hour while
  printing nothing.** `aiosqlite` runs each connection on a **non-daemon** worker thread, so a store nobody
  closes keeps its process alive after all work is done. Four of my own new tests failed an assertion and
  therefore skipped the `close()` written below it; the suite finished in **0.76 s** and then sat in
  `threading._shutdown` indefinitely, with the summary buffered in a pipe that never closed, so the visible
  evidence was *nothing at all* until the user killed it. Three things worth keeping. **The symptom inverted the
  cause**: a hang looks like slow work, and the actual fault was a fast failure whose cleanup was skipped —
  which is why the first instinct, "the query must be pathological", was wrong. **No late hook can rescue it**,
  because CPython joins non-daemon threads *before* running `atexit`, so the fix has to be at the holder, not
  at exit. And **production has the worse version of this bug**: `zikaron-service`'s idle self-stop would
  complete and unlink its socket while the process stayed alive, so the next client's start-if-absent would
  raise a second server against a store the first still holds. The rule is now in `coding-standards.md` §6 (every
  holder uses `async with`) and §4 (tests included), with an autouse fixture that fails the leaking test and
  stops the thread. Verified twice over: injecting a mid-body failure into a then-unconverted test file made it
  report in a second instead of hanging, and the same injection after the suite was converted reports with no
  leak at all. The whole suite now holds every store and every second connection with `async with` — 115 sites
  converted by an AST-guided rewriter that refused anything it could not classify, plus a dozen by hand where
  the close was the operation under test rather than cleanup. Marking the thread a daemon was considered and
  rejected: it needs private-attribute surgery on a pinned dependency to hide a convention we can simply hold,
  and it would trade a loud hang for a silent exit.
- **Four of thirty-five mutations survived, and the most useful one was a test that passed for the right answer
  by luck.** Deleting the dense arm's `uuid` tiebreak did not fail the test written to defend it, because on that
  fixture SQLite's natural order happened to agree with uuid order — so the assertion was true while the property
  it names was gone. The other three were the same shape in different clothes: nothing asserted arm rank
  *values*, so rebasing them 0-based changed every fused score while preserving every order (the config default
  `rrf_k = 60` would silently stop naming the denominator the benchmark measured); and `n_demoted` counting the
  whole pool passed only because that fixture's pool and returned set were the same rows. The same shape then
  recurred *inside a review fix*: removing a helper that had derived `n_returned` from the uuid list it counts
  let the two disagree again, and only mutation testing noticed. **Two practices carried.**
  For an invariant whose effect is only *sometimes* observable — a tiebreak the engine may satisfy by accident —
  assert the mechanism as well as the outcome; the fix pins both arms' `ORDER BY` text alongside the behavioural
  test, and says why in the test's own docstring. And for a quantity defined as "of the returned set", build the
  fixture where the returned set and the candidate pool **differ**, because a fixture where they coincide cannot
  tell the two definitions apart. Directly a Zikaron requirement: a memory that is true of the case it was
  written against and silent about the set it implies is exactly the confidently-partial recall D11 exists for.
- **A text tool that edits source without parsing it corrupts source, and it corrupts it in the two places
  prose and code meet.** A line-reflow helper written to satisfy the 100-column limit split a *data* string
  literal across lines — the injected block's preamble, whose line breaks are part of its value — and merged a
  one-line docstring into the `if` statement beneath it. Both edits produced invalid Python; both were caught only
  because the next command failed to parse. The rewrite classifies every candidate line through `ast` and
  `tokenize` first (multi-line docstring, single-line docstring, whole-line comment) and refuses anything else,
  re-parses each file after editing and reverts on failure. The lesson generalizes past formatting: **a tool that
  cannot tell prose from data must not be pointed at a file containing both**, and the cheap version of that
  guarantee is to parse rather than to pattern-match. The same claim is what `design_tables.py` rests on, and it
  is why the FTS5 query constructor quotes terms and hands them to SQLite's own tokenizer instead of
  reimplementing `unicode61`.

- **Nine of twenty-six mutations survived the first pass, and every survivor was a fixture in which two
  distinct rules coincided.** Not a missing test — a test that could not tell its own property from a
  neighbouring one. Every fixture gave its rows a distinct `created_at`, so deleting group order's uuid
  tiebreak changed nothing (the exact M5 finding, in a new module). The anchor test passed under both
  readings of "the top-ranked record clearing the floor", because on that fixture rank 1 *did* clear it;
  separating them needed a fixture where the fused rank 1 **fails** the floor, built by giving the far
  record every lexical term and the near record none, so RRF and the directed cosine disagree by
  construction. "Candidates exclude every member" looked defended and was not: a journal member cannot
  surface under a `tier='long_term'` filter anyway, so the exclusion only bites once a member has been
  promoted **in place** — which is the one state that makes it simultaneously a member and a long-term
  record. And the group query's whole reason for existing — counting the *assembled* string rather than
  the sum of its parts — was untestable while the fixture used an empty prefix, since with nothing on
  the left of the join the two counts are equal. **The practice this yields is sharper than "write more
  tests": for each guard, name the smallest state in which it is the only thing deciding the outcome,
  and build that state.** A fixture that satisfies a guard incidentally is indistinguishable from one
  that defends it, and coverage reports both as green.
- **Two guards turned out to be provably unobservable, and disclosing that was better than either
  deleting them or pretending a test covered them.** `disposition_members`' `AND disposition IS NULL`
  cannot fire differently, because rung 2 already refuses an `absorb` uuid that is not an undispositioned
  member; `next_candidate`'s serve-before-pending `CASE` cannot change which row comes back, because
  every transition out of the candidate set removes a group rather than returning it to `pending`, so
  served groups are always an order-prefix. Both stay, and both docstrings now say plainly that a
  mutation removing them survives the suite and why the code keeps them anyway — the second one because
  its redundancy rests on a reachability argument about the *whole* state machine rather than on anything
  local, so encoding the shortcut would silently become wrong if a future transition reopened a group.
  The general shape: **a guard whose redundancy depends on a non-local argument should be written as the
  design states it, and the fact that no test can defend it should be written down where the guard is.**
- **Coverage found dead code that no reasoning had.** `groups.member_count` existed to enforce
  `schema.md`'s "`absorb` ≤ the group's member count", and once rung 1 refused a repeated uuid and rung 2
  required every element to be a member, the bound followed and nothing called the function. Worth
  noting because it is the opposite failure from the usual one: not a line without a test, but a line
  without a *caller*, which only the coverage report was in a position to notice.
- **A fix that changes a rule has to be propagated to every summary of that rule, and four consecutive review
  rounds caught me failing at it — each time on the *previous* round's own fix.** Round 3 found the corpus
  stating both the overturned refusal policy and the new takeover one. Round 5 found the narrowed
  reachability claim ("no model can reach it" → "no model can *request* it") applied in one paragraph and
  contradicted two paragraphs later. Round 6 found "at startup" surviving in five places after the trigger
  moved to the first forwarded serve. Round 7 found "exactly once" surviving everywhere after the bound moved
  from attempts to *successes* — a defect **created by round 6's fix**, which is the part worth keeping: each
  repair left the corpus internally inconsistent in a new way, so "did I fix the thing the reviewer named" is
  the wrong completion test. What finally worked was mechanical rather than attentive: for each changed rule,
  grep the *phrase family* it is stated in — `at startup`, `exactly once`, `once per process`, `retry once` —
  across design, FINDINGS, research, experiments and code, and work the list to empty before answering. The
  pattern is exactly what Zikaron is for: a rule updated in the normative place and left standing in every
  place a reader is more likely to look is a confidently stale memory, and the reader cannot tell which copy
  is current.
- **The same argument that justifies a check can hide where the check belongs.** M7's one blocker was a
  rule I had reasoned my way out of implementing: `plan_groups` needs an ownership test, my docstring
  said the test "belongs where the busy shape can be returned", and that sentence is true of
  `next_group` and false of `plan_groups`, which is a reachable RPC sitting right beside it. The
  reasoning was locally sound and answered the wrong question — *can* this layer return the shape, rather
  than *is* this layer an entry point. The tell, in hindsight, is that the docstring argued about where a
  check belongs at all: a function that has to explain why it is *not* checking something is a function
  whose callers are not all accounted for.

## References
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
  hook firings across two agents: payload `session_id` == `KIRO_SESSION_ID` for top-level sessions (3/3) and
  **differs** for subagent sessions (2/2, payload carries the subagent's own id) —
  `research/kiro-session-id-probe.jsonl`. **One claim previously attributed to this file is withdrawn:** that
  it showed `KIRO_SESSION_ID` present in *live MCP servers*. Those five records contain no MCP process at all;
  whatever established it was never persisted. The MCP-side fact is now measured properly in the probe below,
  which supersedes it.
- **kiro MCP lifecycle probe, measured** — **one MCP server process per agent instance.** Two spawns of one
  subagent config gave two distinct pids, each a child of the session's single `acp` process, each with its own
  `initialize` handshake, each exiting when its subagent finished; all three instances of the session shared one
  `KIRO_SESSION_ID`, so the **pid is the only discriminator**. Confirms three premises — each skill invocation
  supplies a fresh per-process successful-plan guard (the first forwarded `next_group` may re-attempt
  `plan_groups` while the client is still `unplanned`, and the first *success* moves it to `ready` so it never
  plans again), `(session_id, pid)` ownership is sound *and* necessary, and `client_kind` can
  be a per-process fact — and forced one correction, since the handshake is **eager** (first `tools/call` 1.6 s
  after `tools/list`), which is why the bridge's call is lazy. Report `research/kiro-mcp-lifecycle-probe.md`,
  raw records `research/kiro-mcp-lifecycle-probe.jsonl`, harness `experiments/mcp-lifecycle/`.
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
- **M5 code review** — three rounds, ending `VERDICT: APPROVED`, with a genuine defect in each of the first
  two. Round 1's blocker was the read side assuming what the write side already refuses: the query preflight
  added `count(prefix)` and `count(query)` and embedded the concatenation without counting it, so under a legal
  non-default `embed_prefix_query` — a free-form config string, only the shipped default ending in whitespace —
  a fused boundary could retokenize into more pieces than the sum predicted and the model would truncate
  silently while `query_truncated` recorded `false`. Round 1 also found the consumer-filter guards testing only
  which *columns* a predicate mentioned (so `active = 0` would have passed), `ArmOutcome` accepting null/null on
  the dense arm and with rows despite claiming to enforce otherwise, event details travelling as untyped dicts
  against `coding-standards.md` §2, and three circumstantial-provenance references the same standard forbids.
  Round 2 accepted the typed-detail remedy but rejected my scoping of it, and was right: `log_event` now takes
  no `kind` argument at all. Round 2 also caught two pieces of wording claiming more than the algorithm proves —
  "the longest head" for a search that only shrinks, and "any single-token query" for a check that tested one
  query's own first token. Round 3: `APPROVED`, one nitpick, a test docstring still describing the dictionary
  architecture the round-2 fix had replaced — `reviews/m5-retrieval-review.md`.
- **M4 code review** — four rounds, ending `VERDICT: APPROVED` with zero findings in the fourth, and a genuine
  defect in each of the first three. Round 1: the hard split's defensive branch returned a *plausible* plan
  instead of raising, and the test I had written to cover that line blessed the invalid result — the fix is a
  plan-level post-condition that recounts every emitted chunk against the budget it was cut to; and
  `index_failed` was being returned for `SQLITE_BUSY`, erasing the one error the design tells a caller it may
  retry. Round 2 found that the first fix was still incomplete in the dangerous direction — a *short* but
  well-formed span list loses a paragraph's tail while every later check passes — and that exact-name matching
  on `SQLITE_BUSY` misses the extended `SQLITE_BUSY_SNAPSHOT` a deferred amend actually gets under WAL, and that
  my failed-commit test masked a missing rollback with its own cleanup. Round 3 found the remaining hole in that:
  a rollback that *also* fails leaves a poisoned connection in circulation, on which a write already reported as
  failed can later be published. Every finding accepted — `reviews/m4-indexing-review.md`.
- **M7 code review** — **eleven rounds**, ending `VERDICT: APPROVED` with no findings. Rounds 1-2 covered the
  milestone; rounds 3-11 were a **targeted review of run takeover alone**, requested after the operator
  reversed round 1's remedy, and they are worth reading as a case study rather than a defect list: rounds 3-4
  found real holes (the corpus stating both policies; takeover having no caller at all, so the path was
  unreachable through the real client), while **rounds 5-10 each found the same defect in the same kind of
  place** — a summary, a reference entry, an invariant's explanatory paragraph — never in the normative
  statement or the code, and each was created by the previous round's own fix. The completion test that finally
  worked was neither attentiveness nor phrase-matching (the phrases mutate: `once per process` does not match
  `once per client process`) but a **semantic** sweep: enumerate every occurrence of the *subject*, read the
  claim each site makes, and check it against the current rule. Round 1's first blocker
  was a rule I had argued belonged one rung up: `plan_groups` is itself a reachable RPC, and it called a
  neutral planning core whose first act closes any stored `active` run as `abandoned` with no ownership
  test — so a second worker could steal an unexpired lease through the explicit entry point while
  `next_group` correctly answered `{busy: true}`, and silently, since the victim's next call would find
  its own run abandoned and be told `group_expired`. Round 1's second blocker was an invariant test that
  could not fail: invariant 13's guard counted one `memory_fts` row, which an external-content table has
  per content row **whatever was indexed**, so it would have passed a merge that dropped the content's
  tail. Two improvements were also accepted — neither `promote` form had a failure-injection atomicity
  test despite having its own transaction wrapper and two distinct mutation sequences, and five
  production docstrings carried circumstantial review provenance that `coding-standards.md` §5 forbids.
  Round 2: `APPROVED`, one nitpick — `MAX_CANDIDATES` and `_GIST_JOIN` were left behind in `serving.py`
  when the candidate query moved to `candidates.py`, so the cap the shipped prompt promises and the join
  the token budget is counted over each had two agreeing declarations, which no test could catch —
  `reviews/m7-consolidation-review.md`.
- **M6 code review** — four rounds, ending `VERDICT: APPROVED`, with a genuine defect in each of the
  first three. Round 1's blocker was the same shape open question 5's own lesson names: the first
  implementation conflated "what the dense arm's bounded probe happened to surface" with the
  mathematically-defined directed cosine `s(new row → candidate)`, silently excluding every
  lexical-only pooled candidate from ever being offered regardless of true similarity — caught by
  writing the regression the round itself asked for, which then failed against the first attempted
  fix (a KNN query sized to the *candidate's* own chunk count, wrong because `vec0`'s `k` is a
  *global* rank cutoff that can return zero rows belonging to the memory it was aimed at). Round 2
  found the corrected fix technically right but operationally unsound: it ran one unbounded,
  full-index KNN probe per lexical-only candidate inside the open write transaction, multiplying
  cost by store size and by candidate count at once. Round 3 found the interim fix for that — a
  batched read of the named candidates' own stored vectors, decoded and scored with a hand-written
  Python L2 loop — introduced a subtler risk: float32-to-binary64 decoding and re-summation has
  different rounding characteristics than the pinned extension's own native arithmetic, so a
  candidate sitting at the threshold could clear it under one arm's scoring and not the other's.
  The round-3 fix, confirmed by directly querying the installed `sqlite-vec` build rather than
  trusting the design corpus's own stated vocabulary, delegates the arithmetic to the extension's
  scalar `vec_distance_L2` function — measured bit-identical to `vec0`'s own KNN-reported distance
  for the same vectors — inside the identical batched, candidate-scoped statement shape round 2
  established. Two smaller findings ran alongside the numerical one: a rollback test's FTS
  assertion read the content-table row through the external-content join rather than proving what
  the inverted index itself held, fixed with a real `MATCH` query on disjoint old/new marker terms;
  and `remember`'s own transaction wrapper had no test for ordinary lock contention, since it
  composes the *neutral* `remember_within_transaction` core directly rather than going through
  `indexing.writes.remember`'s own transaction-owning wrapper, so M4's existing contention test at
  the lower layer never exercised it. Round 4: `APPROVED`, one nitpick (an optional direct
  cross-check between the scalar function and `vec0`'s KNN path, not required while `sqlite-vec` is
  pinned) — `reviews/m6-write-dedup-review.md`.
