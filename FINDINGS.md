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
(retrieval), M6 (write path + D15 dedup), M7 (consolidation) and M8 (D30's six signals as SQL)
complete and reviewed to APPROVED. M9 (service) is built and its gate is green, but its review
**did not converge** — see below. M10 (MCP client) is built and reviewed to `APPROVED` over seven
rounds — see below. M11 (hook client) is built and reviewed to `APPROVED` over eleven
rounds — see below. M12 (distribution) is built and reviewed to `APPROVED` over seven rounds, and
the system is installed into this repository for dogfooding.** D1–D33 settled. Grounding from
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

**M8 shipped `core/signals/`** (`horizon.py`, `sessions.py`, `writes.py`, `dedup.py`, `repair.py`,
`retirement.py`, `contention.py`) — D30's six write-policy signals as executable SQL over the
committed `event` log, exactly as `build-plan.md` instructed rather than as a seventh design round:
each signal is a typed result the caller reads properties off, never a bare number. `writes.py`
holds two signals rather than one, because both aggregate the identical authored-write event
population (signal 1's per-session counts and signal 5's size distribution share the same
`remember`/`amend`/`merge`/`promote` rows) and splitting them would have meant two modules agreeing
by convention on what "an authored write" means rather than by sharing one statement of it.
`horizon.py` and `sessions.py` are the two primitives both cross-event signals need — the
`signal_horizon_days` deadline arithmetic (dedup resolution, amend-after-surface) and linked-session
scope (zero-write rate, amend-after-surface) — factored out once specifically so neither signal could
apply a horizon or a linkage rule the other disagreed with by accident.

**One measurement changed the implementation before a line of signal SQL was written.** The design
leaves unstated whether the horizon deadline should be computed in SQL or in Python, and the natural
first attempt — `datetime(event.at, '+N days')` — was checked directly against this store's own
timestamp format rather than assumed compatible: SQLite's `datetime()` drops the timezone offset,
truncates microseconds, and substitutes a space for the `T` separator, so its output is not
string-comparable with `records.memory.timestamp()`'s `datetime.now(UTC).isoformat()`. Doing the
arithmetic in SQL would have made every deadline comparison silently wrong at exactly the boundary
signal_horizon_days exists to get right, with no error raised anywhere. Every deadline comparison is
therefore Python — `horizon.deadline`/`horizon.has_passed`, matching `consolidation.runs.Run.has_lapsed`'s
own precedent of taking `now` as an explicit parameter rather than reading a clock — and SQL is used only
to locate candidate rows and hand back their raw, unmodified timestamps.

**Two things the design left to be inferred were settled in code rather than left ambiguous.**
`schema.md`'s dedup and repair signals both describe a "qualifying follow-up" as a single fact, but the
underlying SQL needs an aggregate to pick one candidate timestamp when several exist; **`MIN(at)`, not
`MAX`, is the correct witness for "does any qualifying follow-up land inside the deadline"**, since a
positive answer needs only the earliest candidate to clear the bound — a later one existing changes
nothing, and picking the latest could report `not_amended` on a pair a human would call repaired within
the hour. And signal 5's numerator states the query as an English list of kinds and roles ("`target`,
`created`, `flipped`"); the implementation filters `merge`/`promote` rows by `role` explicitly rather
than by `token_count IS NOT NULL`, because the null is a *consequence* of the row's role in this
store's own nullability contract (`AuthoredSize.none_authored()`), not an independent fact a query
should key on — a future writer that left `token_count` null for an unrelated reason must not silently
join this distribution.

**Every rate is a typed property that is bounded `[0, 1]` by construction, and each one's docstring
states why, or states plainly that it is not bounded.** Five of the six signals' rates hold that
property because their numerator is provably one disjoint term of the exact sum the denominator is —
never a separately-computed quantity that happens to agree on well-formed input. `retirement.py`'s
`retire_per_write` is the deliberate exception: it is a ratio of two independent counts, exactly as
`schema.md` names it, and forcing it into `[0, 1]` would misrepresent a store where old rows are
retired faster than new ones are written as a bug rather than as the number it actually is.

**Mutation testing found two genuine test gaps and confirmed four survivors as equivalent mutants,
not misses.** 20 targeted mutations were applied one at a time by hand (no automated mutation
tool is in the pinned dependency set, and adding one for a single milestone's exercise was not
worth the dependency) against boundary flips, AND/OR swaps, `DISTINCT` removal, id-ordering
changes, and the early-close-ordering shape the dedup signal depends on. 16 were caught
immediately. Two real gaps were closed: a malformed `surface`-kind row with a null `memory_uuid`
— constructible only by bypassing `EventSpec.validate`, which this milestone's own raw-insert test
helper deliberately can do — reached `has_passed`'s date parsing and crashed rather than being
filtered by the `memory_uuid IS NOT NULL` guard the query already had, so that guard is now
exercised directly; and the fixture defending `MIN(at)` over `MAX(at)` had used two amends at the
identical timestamp, so the two aggregates agreed by coincidence rather than by the property being
tested — rebuilt with two genuinely different timestamps, one inside the deadline and one past it,
which only `MIN` survives. The four remaining survivors were each individually confirmed, by
direct behavioural argument rather than by the coincidence of a passing suite, to be
**unobservable under any reachable database state** rather than untested: a `DISTINCT` the SQL
states but a Python-side `frozenset` already guarantees; a self-join whose two bound literals are
symmetric because the query only asks whether both values are present somewhere, not which alias
holds which; a `SUM(CASE...) AS` label that carries no meaning to a caller who unpacks the row
positionally; and a `>` that cannot differ from `>=` because `event.id` is one unconditional
primary key no two distinct rows can ever share. Each is now documented in its own module,
in-source, with the specific reachability argument that makes it unobservable — the same practice
`consolidation.serving`/`groups` established for a redundant guard whose safety rests on a
non-local property of the whole state machine, applied here to four narrower, purely local cases.
**Reviewed to `APPROVED` over two rounds** (`reviews/m8-signals-review.md`), with three genuine
blockers in the first. `repair.py`'s `RepairCounts` omitted `signal_horizon_days`, even though
`schema.md` requires **both** cross-event signals to report the horizon they used alongside the
rate — `dedup.py` already carried it, so two identical-looking repair results could silently
represent different estimands. `dedup.py`'s `DedupResolution` held its five outcome counts in a
`dict[DedupOutcome, int]`, which `frozen=True` protects only against field *reassignment*, not
against `result.counts[X] = -1` mutating the mapping in place — a concrete way the documented
`[0, 1]`-bounded-by-construction guarantee could be defeated by a caller, not merely a style
objection. And `write_size_distribution` returned a bare `tuple[int, ...]` with no `ORDER BY` on
its three-branch `UNION ALL`, leaving the distribution's order — required deterministic like every
other instrument — genuinely unspecified rather than merely undocumented. All three were fixed:
`RepairCounts` carries the horizon; `DedupResolution` now has five named, non-negative-checked
integer fields with a `count_for()` accessor for enum-keyed lookups, matching every other result
type in the package; and `write_size_distribution` returns a frozen `WriteSizeDistribution` whose
underlying query orders the whole compound result by `event.id`, verified directly against SQLite
rather than assumed. The determinism test written for that last fix caught a defect in itself
before it shipped: the first fixture inserted three same-branch rows in ascending `event.id` order,
which passes with or without the `ORDER BY` because a single unindexed table scan happens to
preserve insertion order regardless — rebuilt to insert a `merge` row **before** a `remember` row
so the query's own branch-scan order and true `event.id` order disagree, then mutation-checked
directly against the `ORDER BY`'s removal before being kept. Round two re-verified each fix at the
specific line and confirmed no call site anywhere in the repository still referenced the removed
dictionary or bare-tuple interfaces. 869 tests, 99% coverage repo-wide; `zikaron/core/signals`
itself: 245 statements, 44 branches, 100% coverage, 74 tests.

**M9 shipped `service/`** (`paths.py`, `security.py`, `envelope.py`, `rpc.py`, `context.py`,
`params.py`, `serialize.py`, `dispatch.py`, `dispatch_consolidation.py`, `server.py`,
`lifecycle.py`, `log.py`, `main.py`) — the long-running UDS JSON-RPC server: the resolution
preamble, both tool surfaces dispatched by wire method name, start-if-absent, idle self-stop, and
the degraded-mode error mapping. Every handler returns a typed `RpcResult` and never a bare
`dict[str, object]`, so a wire shape is a dataclass with one `as_json()` seam rather than a dict
literal built at each call site — a rule adopted mid-review, after an untyped boundary let
`next_group`'s `candidates` ship the wrong shape. 1065 tests, 98.39% coverage across
`zikaron/core` **and** `zikaron/service`.

**The review did not converge, and that is the honest headline.** Fourteen rounds, every single one
of which found at least one genuine, independently verified defect — there was no round that came
back clean, so the loop was stopped by operator direction rather than by reaching `APPROVED`.
`reviews/m9-service-review.md` has the blow-by-blow. What that means for whoever reads this next:
the gate is green and every finding raised was fixed and verified, but nobody should treat this
milestone as having earned the same "reviewed to APPROVED" confidence M1–M8 carry. **Four of the
fourteen rounds found defects that would have broken the service in production**, and all four were
in the same area — shutdown:
- **Round 5:** start-if-absent released its `flock` after a bare TCP connect succeeded, without ever
  confirming a real `health()` response while still holding the lock — directly against
  `architecture.md`'s own step ordering, and a spawning client could hand back a socket whose first
  real request failed.
- **Round 8:** the three consolidator write methods were registered as `merge`/`promote`/`discard`,
  but `architecture.md` §"Service RPC surface" names them `apply_merge`/`apply_promote`/
  `apply_discard`. Any client built against the design would have received `METHOD_NOT_FOUND` for
  every consolidator write. Invisible to the whole suite, because every consolidator test called the
  Python handler functions directly and nothing exercised the wire name.
- **Round 9:** an idle-but-connected client — the documented norm, since a client "adopts the
  returned label and reuses it for its process lifetime" — hung shutdown **forever**, because
  `asyncio.Server.wait_closed()` waits for every accepted connection to drop and nothing was closing
  them.
- **Round 11:** the fix for that then deadlocked against `asyncio.Server.serve_forever()`'s own
  cancellation, which calls `close()` and awaits its *own* `wait_closed()` — a second, independent
  wait for the same connections, which ran first. Resolved structurally: `serve_forever()` is now
  never called at all, since `start_unix_server` already accepts and dispatches on its own and using
  it as a stop-signal was backwards.

**One decision was the operator's, not the reviewer's, and is recorded as such.** Round 12 found a
narrow race inside `asyncio`'s own accept pipeline: a connection accepted at the raw-fd level before
`Server._attach()` increments the private counter the drain loop polls. Closing it provably would
mean replacing `asyncio.start_unix_server` with a hand-rolled accept loop. The operator asked the
question that reframed it — do we need graceful shutdown airtight against every asyncio-internals
edge case, when we already try our best and already fail loudly on a bounded deadline? — and
directed **both**: keep the graceful path exactly as built, and force-terminate the process if its
5 s deadline expires. That is now normative in `architecture.md` §"Idle self-stop", stated plainly as
a choice of engineering effort rather than a claim of airtightness. Rounds 13 and 14 then found the
*implementation* of that directed decision wrong twice, which is the useful part: the force-exit was
first placed outside `asyncio.run`, where it is **unreachable** — `asyncio.run` cancels and awaits
every remaining task before re-raising, and the task that made the deadline expire is by definition
one that did not finish cancelling, so the runner hangs and the handler never runs (measured
directly). It now fires from inside the coroutine, on a dedicated `ShutdownTimeoutError` raised only
from the three shutdown deadline exits, and skips the retry and `ctx.close()` that would otherwise
keep asking a path that already gave up. Round 14 confirmed skipping `ctx.close()` there is safe for
the *next* opener: the kernel releases SQLite's fds and locks, WAL is the journal, committed frames
stay recoverable, and an incomplete transaction is ignored rather than made durable.

**The coverage floor had silently excluded this entire milestone.** `check.sh` said
`--cov=zikaron/core`, written in M1 when `core` was the only package, and nobody updated it when
`service/` was added — so `[tool.coverage.report] fail_under` was not applied to 2,886 lines of
production code. Fixed (the gate now covers both packages), and enabling it immediately found a real
gap: `fetch` was the one primary-agent RPC method with **no** service-level test at all, its twelve-
field wire shape entirely unasserted — the same class as round 8's genuine defect. Now tested
against the field set `architecture.md` states, as a set rather than by spot-checking keys. The
lesson is narrower than "raise coverage": *a gate that names packages by hand stops covering the
code the moment a package is added, and nothing fails to tell you.*

**M10 shipped `zikaron/mcp/`** (`connection.py`, `errors.py`, `primary.py`, `consolidator.py`,
`server.py`, `main.py`) — the MCP client: five primary-agent tools, four consolidator tools, gated
to two separate agent configs by never registering the other mode's tools on a given process's
`FastMCP` instance at all, the lazy `plan_groups` bridge in front of the consolidator's first
forwarded `next_group`, and reconnect-on-death for a service that stops mid-session. **Reviewed to
`APPROVED` over seven rounds** (`reviews/m10-mcp-client-review.md`), with a genuine defect in each
of the first six — the longest review trail of any milestone so far, and worth reading as one,
since nearly every round's defect was in the identical area: correctness properties that only
become observable under concurrency, cancellation, or genuine timing, which is exactly the class a
suite of sequential, synchronous-looking unit tests cannot surface by construction.

**Two operator-directed scope decisions, both settled before the code was written.**
`zikaron-mcp` takes an exact-pinned dependency on `fastmcp==3.4.5` — the standalone jlowin/PrefectHQ
package, not the official `mcp` SDK — breaking `coding-standards.md`'s previous "hook and MCP are
both stdlib-only" rule for the MCP client specifically. The reasoning is a cost model, not a
relaxed standard: measured on this machine, `import fastmcp` costs **594.6 ms** cold (~30× the bare
interpreter), in the same range as the cold embedder load that justifies the service's own
existence — but kiro spawns **one MCP process per agent instance** (`research/kiro-mcp-lifecycle-
probe.md`), not once per message the way the hook fires, so the cost is paid once per spawn rather
than repeatedly on the critical path D12's whole hook-thinness argument rests on. The decision
followed directly from M9's own review history: fourteen rounds on a hand-rolled
`asyncio.start_unix_server` that never converged, weighed against reusing a maintained framework's
already-tested tool-registration and stdio-transport machinery for the client side too. Separately,
**the service now creates the store on its own first startup if `memory.db` is absent** — settled
because nothing else in the distribution ever called `Store.create` in production, and a design
that required a separate bootstrap step before the service could start would mean the system could
never reach its own working state from an empty directory unassisted. Building this surfaced a real,
independent bug in the process: `main.py`'s own log setup ran *before* the store directory existed
on a genuinely first-ever run, so the service crashed attempting to `touch` `service.log` into a
directory that had never been created — invisible to every existing test, since all of them
pre-created `store_dir` as part of their own setup. Both decisions, and the bug, are written into
`design/architecture.md` §Components and §"First run" respectively.

**The review's own shape is worth summarizing on its own terms, because a single "seven rounds"
count understates what those rounds actually found.** Round 1's four blockers were a missing
mechanism entirely (the client re-bootstrapped a fresh session label on every call instead of
adopting the one the service returned, exactly the defect D31's own "the client adopts the
returned label" sentence exists to prevent — it would have split one client process's own receipts
and writes across multiple service-minted labels, and let a consolidator's own successful
`plan_groups` be followed by a `next_group` that saw its own run as foreign), a forwarded `zk-`
harness value violating the reserved-namespace contract, a symlink-bypassing bare `mkdir` in the
first-run log-ordering fix, and an unlocked `_PlanBridge` allowing two concurrent takeovers from
one process. Rounds 2–4 found, in turn: `socket.sendall`'s own documented inability to report
partial-send progress meant a positive-progress send failure was being retried as if it were safe,
risking a duplicate `remember`; a real `sock.send()` zero-return case (permitted by the socket API
without raising) that would have spun forever while holding the connection lock; and an established
socket that silently kept `lifecycle.py`'s own 1-second *connect-phase* timeout indefinitely, which
would cut off any request waiting out the store's own documented 5-second contention window before
it could resolve. **Round 5 found something no round asked for**: while writing the integration
test for round 4's own fix, a concurrent `asyncio.sleep` in the test's own lock-holding fixture was
measured resuming *later than its own coded duration* — the exact self-inflicted-deadlock shape
`coding-standards.md` §6 already documents for the service's own blocking `sqlite3` calls (M0 spike
3), now found on the MCP *client* side: every one of `ServiceConnection`'s own socket calls was
fully synchronous inside `async def` methods, so any real wait for the service blocked the entire
FastMCP event loop, not merely the calling coroutine. Round 6 found the identical defect class
recurring twice more — synchronous filesystem calls still reachable from `_read_store_identity`,
and (traced to its root) `Store.open`/`Store.create` themselves, two already-`APPROVED` M2 files,
running their own permission checks synchronously as their literal first statement before any
`await` — plus `asyncio.to_thread`'s own fundamental limitation (a cancelled awaiting coroutine
cannot actually stop the underlying thread) meaning a cancelled tool call could orphan a worker
thread still touching a live socket, or leak a socket a cancelled connection attempt establishes
after its own caller has already given up on it; and the consolidator bridge had no cancellation
handling at all, which could leave it retryable exactly when a takeover may already have committed.
**Round 7 found no blocker**, one nitpick (a comment overclaiming that closing a socket promptly
wakes an orphaned worker thread blocked on it, corrected to state the guarantee actually
provided — detachment and non-reuse, with the worker's eventual exit bounded by its own request
timeout rather than by the close itself) — and, distinctively, caught a genuine timing bug in the
review's *own* test for round 6's fix (a cancellation test that awaited its cancelled task before
releasing the gate meant to let it, so it was accidentally running out a five-second fallback
rather than exercising a fast release at all), which is exactly the class of defect this whole
review thread was about, this time in the test suite meant to prove the fix rather than in the
fix itself.

**One thing was found, weighed, and deliberately left as a disclosed, bounded risk rather than
fixed further.** `close()`-ing a socket from one thread is not a portable, guaranteed way to
interrupt another thread already blocked inside `send`/`recv` on it — real, and Linux-specific
nuance the design does not paper over. It is accepted rather than layered with
`shutdown(SHUT_RDWR)` or similar for three stated reasons: this project's whole transport is
Unix-domain-socket-only with no cross-platform ambition anywhere in the corpus; the practical
consequence is bounded regardless of whether `close()` wakes the orphaned worker promptly, since
that worker's own socket already carries the 10-second request timeout the established-socket
timeout fix installed, so its eventual exit is bounded either way; and the review had already spent six full
rounds specifically on cancellation-safety edge cases, past the self-review skill's own stated
three-iteration convergence guidance, with each successive finding narrower and lower-severity than
the one before it. The reviewer's own round-7 judgment concurred this is the proportionate place to
stop and disclose rather than continue chasing theoretical airtightness — the same shape of
judgment call M9's own operator-directed shutdown tradeoff already established as precedent for
this corpus.

**1130 tests, 97.71% coverage on `zikaron/mcp` together with every other shipped package** — `check.sh`'s
own `--cov` flags now name `zikaron/mcp` explicitly, added at M10's introduction rather than
discovered as a gap the way M9's own `--cov=zikaron/service` omission was.

**M11 shipped `zikaron/hook/`** (`connect.py`, `envelope.py`, `failure.py`, `main.py`, `push.py`, `rpc.py`,
`spawn_warm.py`, `warm_helper.py`, `write_policy.py`) — the two hooks: `userPromptSubmit`'s push, and
`agentSpawn`'s write-policy print plus best-effort service warming. Both are single-shot, stdlib-only
processes by design (D22, D12's own hook-thinness argument), and the single outer connection attempt this
milestone holds itself to — never `zikaron-mcp`'s own retry-once — is the one deliberately narrower property
that recurs through nearly every finding below. 1259 tests, 97.67% coverage repo-wide, `zikaron/hook` itself
at 95.5%. **Reviewed to `APPROVED` over eleven rounds** (`reviews/m11-hook-client-review.md`) — the longest
review trail of any milestone, and worth reading in two parts: rounds 1–2 covered the whole client broadly,
finding a genuine defect in each; rounds 3–11 were almost entirely consumed by one specific sub-problem —
verifying store identity across a connect-time replacement race — which took a materially different shape
each round and ended, deliberately, on human authority rather than engineering conquest.

**Measured before a line of production code addressed it: kiro's own exit-code and stderr contract for a
hook's stdout is not what the design corpus assumed, and the corpus was wrong twice before the measurement,
not once.** A live spike against a real kiro session — instrumented, then deleted per its own docstring's
instruction, per `coding-standards.md`'s own "spikes are throwaway" convention — walked three shapes in
order: silence on both channels with exit 0 (the original design); reporting on stderr too, still exit 0;
then also making exit non-zero on a failure, reasoned as the more conventional Unix contract. The third
shape was the one actually measured wrong: a non-zero exit suppressed the confirmed-working exit-0 stdout
channel *entirely*, and stderr never surfaced to the model at all on either exit code. The shipped contract,
confirmed working end to end against the real kiro session: always exit 0, never stderr; on failure, the
exact machine-readable detail goes to `hook.log`, and a short, deliberately paraphrasable natural-language
instruction asking the model to relay the failure to the operator (citing `hook.log` for the exact detail)
goes to stdout — verified directly, not merely reasoned about, that this text genuinely reaches the model's
own context and gets relayed in its response. `design/architecture.md`'s "Degraded modes" section keeps the
full three-shape history; every other design site — `coding-standards.md`, `overview.md`, `retrieval.md`,
`schema.md`, `write-policy.md`, `build-plan.md` — was swept for the two superseded phrasings ("prints nothing
and reads nothing", "never stderr, always silent") and corrected everywhere the *failure* contract was
described, while every genuinely unaffected site (subagent-session suppression, an empty successful
`surface` result) was correctly left alone, since both remain silent for reasons this pivot never touched.

**A genuine, independently reviewed shared-infrastructure bug surfaced while building this milestone's own
tests, before the review trail even started.** `tests/design_tables.py`'s `parse_fenced_code` — the parser
every prior milestone's own drift-guard tests read the design corpus through — could not distinguish a
closing fence of a differently-tagged code block from a fresh opener for the target language when the
target language string was empty, a case this milestone's own new tests were the first to exercise. Fixed
generally (a `matched` boolean tracked per open/close pair, not a special case for this one language), and
re-verified against `test_ddl.py`'s own existing assertions after an incidental message-format change had to
be reverted — a small, direct instance of the corpus's own recurring lesson that reformatting a diagnostic
string while fixing its logic is a second, unrelated change wearing the first one's commit.

**Round 1 found eight blockers and two improvements, one in nearly every module this milestone shipped.**
`connect.py`'s own start-if-absent sequence was missing the `flock` lock-and-recheck step entirely — a real
TOCTOU where two racing hooks could unlink each other's live socket — restored, and proven with two new
tests racing real concurrent threads against a real long-running fake server. `push.py` and `spawn_warm.py`
each caught only a finite, named set of exception types rather than genuine `Exception`, meaning an
unanticipated failure could escape both `hook.log` and the stdout relay entirely and propagate past this
package's own outermost catch-all — restructured to catch broadly after the specific cases, with a test
proving a bare, unlisted `RuntimeError` is still caught and relayed. `failure.py`'s own docstring claimed
`os.open`'s mode argument was umask-independent — measured directly and found false, a `0600` process umask
genuinely produces a `0000`-mode file — fixed with `O_EXCL`-first creation detection and `os.fchmod` forcing
the exact mode only on genuine creation; the same fix closed a second, more consequential defect in the same
function, that it never created its own parent `.zikaron` directory, meaning the single most common failure
case — the very first session, before any store exists — silently lost the failure record `hook.log` exists
to make durable. `main.py` used `print(output)`, appending a trailing newline the design's own "empty
`surface` prints nothing at all" contract does not include — fixed to `sys.stdout.write`, proven byte-exact
against a real subprocess. `warm_helper.py` configured its own log file *before* securing the directory that
log needs to exist, meaning a genuinely fresh project crashed the detached warm helper silently on the very
first run, before start-if-absent was ever attempted — fixed by moving both inside one leading failure
boundary. `push.py` always passed `store_id=None` to the connection layer, making the store-identity-mismatch
check unreachable past a store's first-ever creation — the first of several rounds this specific check would
occupy (see below). `test_hook_stdlib_only.py`'s own enforcement was a hand-maintained denylist, blind to any
unanticipated third-party import, and a hand-maintained "critical path" module list, silently exempting any
future module added without updating it — rewritten to discover modules from disk and classify every import
positively against Python's own `sys.stdlib_module_names`, with a negative-control test proving a synthetic
non-stdlib import is actually caught. A comprehensive stale-text sweep found five more sites the original
sweep missed. Two improvements: a carve-out added to `coding-standards.md` §4 for in-process
socket-bound-on-a-background-thread tests, mirroring the design's own existing "where a real store sits"
precedent, since this package's own test suite uses the pattern extensively; and both modules' docstrings
trimmed of round-by-round operator-pivot narrative, per §5's "no circumstantial provenance" rule, pointing to
`architecture.md`'s own "Degraded modes" section for the history instead of duplicating it in code.

**A genuine test-leak bug was found after round 2's own check gate reported clean, and it was found by
distrusting the delegated summary specifically, not by reading it more carefully.** One test never mocked
`subprocess.Popen`, so it genuinely spawned the real detached warm helper, which genuinely spawned a real
`zikaron.service.main`, every time it ran; two other tests spawn a real service as an *intended* side effect
of testing the real end-to-end `agentSpawn` entry point, and needed their own explicit reap-by-health-poll-
then-signal cleanup rather than none at all. Caught specifically by running `pgrep -af
"zikaron.service.main"` directly after a check-gate run, rather than trusting the delegated py-runner
summary's own aggregate pass/coverage numbers — which were separately, independently found inaccurate on
their own terms this same session, a recurring and by-now well-documented lesson in this corpus. Fixed,
re-verified clean via the identical `pgrep` check, and folded into this session's own standing discipline:
every test run that could plausibly spawn a real service gets checked this way, and every delegated coverage
number gets independently recomputed per package from the raw `Stmts`/`Miss` table before being trusted.

**Rounds 3 through 9 are best read as one continuous engineering arc on a single question — can a
stateless, no-store-access client verify the identity of the store it just connected to — that changed shape
five times before the human operator directed it stopped changing shape at all.** Round 3 found the
hook's own path-only identity check was, by construction, unable to detect a store deleted and recreated at
the identical path while a stale service kept it open — the exact scenario `store_id` exists to catch, which
a *stateless* client genuinely cannot resolve on its own (a sidecar file the hook would write and read
itself to remember an id across invocations was considered and rejected as circular: whatever a later
invocation would compare against was itself written by an earlier call to the same, possibly-now-stale
service, so a service that goes stale without restarting reports the identical value both times and the
sidecar never disagrees with itself). The resolution moved to the *service* side instead, since it is the
only party with an independent way to notice: `zikaron/service/lifecycle.py`'s own idle-poll task — already
running every 30 s to check for idle timeout — gained a second, independent exit condition, comparing the
store's own inode at the path against the one captured when the connection first opened, and self-stopping
on drift exactly as it already does on idle. Round 6 found the *capture* of that baseline inode was itself
racing `aiosqlite`'s own documented cross-thread connect handoff (`Connection._connect` queues the real
`sqlite3.connect()` call onto a separate worker thread and only resumes the caller once that thread hands
the result back), and a fix pinning a file descriptor before the connect call — but only ever using it to
read a number, closing it again immediately — left the connect itself going through the still-adversarial
plain pathname, unprotected by anything the pin had established. Round 7 found that fix's own comparison
still could not rule out the path being swapped away and restored *during* the handoff, since two path reads
bracketing a window prove nothing about what happened inside it, and moved to reading SQLite's own
post-connect identity through a `/proc/self/fd` scan for any descriptor matching the path. Round 8 found the
scan itself unsound — it cannot attribute a match to *this* connection over any other same-process,
same-path descriptor, so a coincidentally matching, unrelated one could produce a false accept or reject —
and the fix connected SQLite directly through the pinned descriptor's own `/proc/self/fd/<n>` path instead,
reasoned to sidestep pathname resolution entirely, since that magic symlink resolves to the descriptor's own
file rather than by re-walking the original name. **Round 9 measured that reasoning wrong, directly and
concretely, not merely by argument**: `PRAGMA database_list` on a connection opened through `/proc/self/fd/
<n>` reports the ordinary, canonicalized pathname, not the magic-symlink string handed to it — SQLite's own
VFS resolves it internally — and a file replaced at the path while an existing connection is live can make
even an *already-established* connection fail on its very next statement, disproving the premise the whole
mechanism rested on rather than merely finding it incompletely built.

**At that point the human operator was consulted directly, and made the call the eight prior rounds could
not have made for themselves: stop engineering around a race whose real shape does not warrant the
engineering.** Closing the gap properly would require controlling SQLite's own VFS-level file handle — a
custom VFS or file-control integration, a materially larger undertaking than the milestone's own scope. The
race this whole arc chased is a sub-millisecond window at process startup, not the ordinary case the
mechanism exists for at all — a store deleted and recreated while the service has been sitting open and
idle, which the poll closes completely, with no narrower timing assumption anywhere in *that* half of the
design. The operator's own direction, stated plainly: revert to the simple capture — a bare `db_path.stat()`
immediately after connect, no `await` in between — and accept the narrow startup-instant race as a
documented, out-of-scope gap on human authority, rather than pursued further. This is recorded in both
`architecture.md` and `_open_connection`'s own docstring exactly as a decision, not a silent regression:
what was tried, what was measured wrong about each attempt in turn, what closing it properly would require,
and that the operator judged the race's own shape not worth that cost. Round 10 then found one genuine bug
the revert itself introduced — the reverted `stat()` call sat *outside* the function's existing
close-on-failure boundary, meaning a stat failure would abandon the just-established, worker-thread-backed
connection with nothing left to close it, a real resource leak of exactly the shape this corpus has already
paid for once (`coding-standards.md` §6) — fixed by moving the read to the first statement *inside* the
existing guard, preserving the "no `await` before the read" property the capture still depends on, and
verified by mutation-testing the fix against its own removal. Round 10 also found the design prose itself
had drifted back into overclaiming during the revert — stating unconditionally that the stale connection
"keeps serving whatever inode it opened regardless," directly beside the sentence recording round 9's own
finding that a later operation on it can still genuinely fail — corrected to distinguish the descriptor's
own binding from a promise about every subsequent operation on it, which was never true. **Round 11 approved
with one cosmetic nitpick** (a test docstring's own stale cross-reference to an earlier capture location),
fixed immediately without a twelfth round since it carried no behavioral implication.

**The lesson this arc leaves is not "review more" — every one of rounds 3 through 9 found something real,
and finding it took exactly that many rounds.** It is that an estimand can survive five rounds of
increasingly careful engineering and still rest on a premise nobody had actually measured, and that
recognizing a chase has stopped being proportionate to what it defends against is a judgment call this
corpus's own tooling cannot make for itself — the same shape of call M9's own operator-directed shutdown
tradeoff and M7's own consolidation-takeover reversal already established as precedent, now with a fourth
instance: measure past reasoning-in-place at every step (`PRAGMA database_list` settled in one command what
several rounds of confident implementation had assumed), keep exploring the engineering while a next round
keeps finding something real, and know that a human calling "this is not worth closing further" is itself a
legitimate, recorded design decision rather than a failure to converge.

**M12 shipped `zikaron/install/`** (`assets.py`, `entries.py`, `harness.py`, `writer.py`, `main.py`,
`__main__.py`) plus `zikaron/hook/limits.py`, the `[project.scripts]` entry points `zikaron-hook` and
`zikaron-mcp`, the shipped `zikaron-consolidator` agent config and `zikaron-consolidate` skill, hook and
`mcpServers` entries in both formats the harness accepts, an optional `.zikaron/write-policy.md` override,
and `README.md` as the install documentation. **1435 tests, 98% coverage repo-wide. Reviewed to
`APPROVED` over seven rounds** (`reviews/m12-distribution-review.md`), with genuine defects in each of the
first six.

**Four premises about the harness were wrong or unverified, and all four were settled by asking the
installed binary rather than by reasoning.** (1) `mcpServers` **configures** a server while `tools`
**selects** from it: an agent carrying the server entry with a `tools` list that did not name it reported
its tools as `code, dummy, execute_bash, fs_read, fs_write, glob, grep, todo_list, use_subagent` — the
entire memory surface absent, no warning anywhere — and reported all five `zikaron_*` tools once
`@zikaron` was added. The installer now merges it in; `allowedTools` is still left to the user, with a note
that skipping it means a prompt on every memory write. (2) A hook's `command` is **shell source**, run
through `/bin/bash -c`: an unquoted path containing a space produced
`/bin/bash: line 1: /tmp/.../my: No such file or directory`, exit 127, hook never ran — so both formats
`shlex.quote` the executable, while `mcpServers`' own `command` stays raw because that field takes a
program plus a separate `args` array. (3) The `timeout_ms` default is **10 s**, not the 30 s the corpus had
recorded from the public docs, and there is a **`max_output_size`, default 10240 bytes, that truncates
silently** — both now stated explicitly in every object-format entry rather than inherited. (4)
`kiro-cli agent validate` accepts `"model": "not-a-real-model-xyz"` **silently**, so the design's
no-silent-fallback rule needed its own mechanism: `kiro-cli chat --list-models -f json`, refused when the
binary is absent rather than assumed good. The consolidator's v0 model is now **`claude-sonnet-5`** by
operator decision — same 1.30x multiplier, 1M context against 200k.

**One measured finding changed M11 code rather than M12's.** The shipped push hook cost **70 ms per user
message**, not the ~20 ms `architecture.md` §Components quotes — `zikaron.core.events` alone is 28 ms over
a stdlib floor, imported for one enum, and `zikaron.service.envelope` 34 ms. Stdlib-only is not the same as
cheap. The hook now states the `client` envelope's four fields locally as a `NamedTuple` with a
`CLIENT_KIND` literal, guarded by four drift tests that compare against the real dataclass and enum and
round-trip through the service's own parser: **70.0 → 50.6 ms**, on the one path D12's whole thinness
argument rests on.

**The review's own shape is the instructive part, and it is a variant of a lesson this corpus already
carries.** Rounds 1–6 each found real defects, and **three rounds' worth were defects created by the
previous round's fix**: round 2's plan/commit split left the backup check *after* the shipped writes, so a
blocked `<config>.bak` produced exactly the half-install the split existed to prevent; round 3's
"exclusive" temporary file closed its descriptor and reopened the path by name; round 4's shipped-path
preflight used `Path.exists()`, which is **false for a dangling symlink**, so a dangling `SKILL.md` link
was reported as "kept" and the install exited 0 with no loadable skill. The known lesson is that a fix
aimed at the reported case inherits that case's narrowness; the sharper corollary is that a fix which
*restructures* creates new seams, and the new seams deserve the scrutiny the original defect got.

**Two whole classes were closed by naming the quantity rather than by testing harder.** `is not None`
conflates an absent JSON key with a present `null`, so `"hooks": null`, `"tools": null`,
`"mcpServers": null` and `"mcpServers": {"zikaron": null}` were all silently replaced by guards written to
refuse exactly that — JSON's fourth scalar, fixed by testing presence with `in`. And an existing Zikaron
hook entry was compared by its *command* alone, so an operator's deliberate `timeout_ms` was silently
reset; the comparison is now structural against the generated entry, and the refusal names the differing
keys so a user can tell their own edit from a version change.

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
| M8 | D30's six signals as executable SQL | each runs against a fixture whose expected value is hand-computed in the test; a post-deadline follow-up cannot change a matured classification | ✓ |
| M9 | Service — UDS, JSON-RPC, preamble, lifecycle | integration tests cover the start-if-absent race, connect-as-server-exits, a stale socket, and a refused foreign-store handshake | ✓ |
| M10 | MCP client — 5 primary tools, 4 consolidator tools | a consolidator config provably cannot reach `search` or `fetch` | ✓ |
| M11 | Hook client — suppression, degraded chain, always-exit-0 | a test asserts stdlib-only imports; every failure mode exits 0 with empty stdout | ✓ |
| M12 | Distribution — install command, agent config, skill, hook entries in both formats, policy asset | a clean install on a fresh directory does push, pull, write and a consolidation run, driven through the real shipped commands | ✓ |

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
- **A determinism test can pass for a reason that has nothing to do with determinism.** M8's
  `write_size_distribution` needed an `ORDER BY` because a three-branch `UNION ALL` gives SQLite no
  documented guarantee about row order otherwise. The first test written to defend that `ORDER BY`
  inserted three rows of the *same* branch in ascending `event.id` order and asserted two reads
  agreed — which they did, with the `ORDER BY` present or deleted, because a single unindexed table
  scan with nothing else in flight happens to return rows in the order SQLite physically stored
  them regardless of any explicit ordering clause. The test was asserting "this query is
  self-consistent," which is true of nearly any query run twice against an unchanged database, not
  "this query's order is *specified*." Mutation-checking the fix against its own removal — not just
  running the new test once and moving on — is what caught it: deleting the `ORDER BY` should have
  failed the test and did not. The fix that actually distinguishes the two claims interleaves rows
  from *different* `UNION` branches out of `event.id` order, so the query's own branch-scan order and
  the true global order disagree by construction, and only the specified order survives. The general
  form is the same one M5's fused-rank tiebreak and M7's group-order tiebreak already found: a
  property that is only *sometimes* the thing deciding the outcome needs a fixture where it is the
  *only* thing deciding it, and a fixture that happens to satisfy a guard is indistinguishable from
  the coverage report's point of view from one that defends it.
- **Fourteen review rounds on one milestone, none of them clean, and the same defect class kept
  surfacing: a cleanup path that was never exercised.** Not "untested" in the coverage sense — most of
  these lines *ran* in tests. What went untested was the *exceptional* path through them: the store
  left open when construction failed after it opened; the socket left unclosed when `connect()` raised;
  the background tasks left running when the code that cancelled them was reachable only after a
  normal return; the signal handlers never removed on any path; a retry whose own failure silently
  replaced the failure it was retrying. Each was found by a reviewer asking the same question in a new
  place — *what if this step fails?* — and each was invisible to a suite where nothing failed. The
  practice this yields is a checklist, not a virtue: for every resource acquired, name the exceptions
  that can occur between acquiring it and handing it to whatever will release it, and for every
  cleanup that can itself fail, decide explicitly which exception the caller should see.
- **The most expensive defects were all in one place, and the reason is structural: shutdown is the
  one path with no client waiting for an answer.** Four of the fourteen rounds found
  production-breaking bugs and all four were in shutdown — every other surface has a request/response
  pair, so a wrong answer shows up as a wrong answer. Shutdown's only observable is "did the process
  eventually stop," which no ordinary test asserts and no user reports until it hangs. Three separate
  hangs shipped through review rounds because each fix's own test proved the *new* mechanism worked
  without proving the *whole* sequence still terminated. What eventually worked was testing the
  outcome rather than the mechanism: start the real thing, hold a real connection open, send a real
  signal, and bound the wait.
- **`asyncio` internals were wrong three times in a row about things that read as obviously true.**
  `wait_for(gather(...), timeout=t)` is not a deadline if the awaited task suppresses cancellation —
  its own docstring says so, and a handler that swallows `CancelledError` leaves it waiting forever.
  `task.cancel()` does not reliably deliver `CancelledError` into a coroutine suspended in
  `StreamReader.readline()` — it can surface as an ordinary empty read. `asyncio.run` cancels and
  *awaits* every remaining task before re-raising, so an `except` around it never runs if the failing
  task is the one that will not finish cancelling. Each was settled by a ten-line script measured
  directly, and each had already been reasoned about confidently and wrongly first. For a dependency
  this project does not own, "I read the source and it looks like X" is a hypothesis; running it is the
  answer.
- **A gate that names its packages by hand stops covering the code the moment a package is added, and
  nothing fails to tell you.** `check.sh` said `--cov=zikaron/core` from M1, when `core` was the only
  package. M9 added 2,886 lines of production code that the ratchet in
  `[tool.coverage.report] fail_under` therefore never saw — for the whole milestone, through fourteen
  review rounds, while every gate run reported a healthy number. Enabling it took one line and
  immediately surfaced a real gap (`fetch` had no service-level test at all, its twelve-field wire
  shape unasserted — the same class as the round-8 defect that would have broken every consolidator
  client). The generalisable form: an enumerated allowlist in a quality gate is a silent opt-out for
  anything added later, and the failure is invisible precisely because the gate still passes.
- **A spy that returns cannot verify a function that never returns.** Three tests for the force-exit
  fallback asserted the spy fired *exactly once* and two failed `2 == 1` — because in production
  `os._exit` ends the process at the first call, so exactly-once holds by construction, while a
  returning spy lets execution continue into whatever later terminal route the same failure also
  reaches. The count was an artefact of the test double, not a property of the code. Worth naming
  because the failing assertion looked like a bug in the code and was a bug in the test's model of it:
  when you replace a terminal operation with a non-terminal one, every assertion downstream of it is
  now measuring a different program.
- **A delegated summary reporting a clean exit is not the same claim as "nothing hung."** A subagent run
  during M10 returned a proper pytest summary line (exit 1, 4 failed, 80.64 s) with no obvious sign of
  trouble, and the operator watching the same terminal flagged it as *looking* stuck anyway — the long
  silent wait with verbose output suppressed by design read as a freeze even though the process was
  making progress the whole time. It was not a false alarm to investigate: those four failures were a
  genuine first-run log-ordering bug (§"First run"), and each failing attempt was burning its own full
  10 s health-poll deadline, which is exactly the shape a slow failure and a hang share from the
  outside. After fixing the real defect, the identical class of run was re-verified twice more by
  running the same command directly, wrapped in an explicit `timeout`, with a process list checked
  before and after — both times fast (under 9 s) and clean. The lesson is not "delegation is
  untrustworthy"; it is that *this specific failure mode* — did it hang, or did it just take a while
  in silence — is one a returned summary cannot distinguish from the outside, so it is worth verifying
  directly rather than only through a subagent's own report whenever a session is specifically
  checking for it, which this whole milestone's own review trail gave repeated, independent reason to
  do: one genuine hang inside the author's own test code (an `asyncio.Event` two tasks could never
  both reach, since one of them was waiting on the exact lock the other held while parked on it — a
  self-inflicted deadlock in the *test*, not the code under test), one genuine production bug
  (event-loop starvation) found only because a concurrent `asyncio.sleep` was measured resuming later
  than its own coded duration rather than the delay being attributed to "the lock is just slow," and
  one genuine timing bug in the author's own review-fix test caught by the *reviewer* reading the
  test's own await ordering rather than trusting that a passing assertion meant the right thing was
  being exercised.
- **The property "no blocking call reaches the event loop" is not established by fixing the call sites
  you already suspect.** M10's own review found the identical defect class — a synchronous filesystem
  or permission call reachable from inside an `async def` — three separate times in three separate
  places across two consecutive rounds: the client's own `_read_store_identity`, and then, traced to
  its root, two already-`APPROVED` M2 files' (`Store.open`/`Store.create`) own permission checks,
  running as their literal first statement before any `await`. Each fix was locally correct and
  incomplete in the identical direction: it closed the specific call site named, not the *property*
  "this coroutine never blocks the loop it runs on," which is what let the next call site of the same
  shape keep surfacing. The fix that actually stopped recurring was the one that traced a client-side
  symptom back to a dependency two milestones upstream and fixed it at the root, benefiting every
  caller rather than only the one that happened to notice.
- **`asyncio.to_thread`'s own contract has a corollary nobody states plainly: cancelling the *coroutine*
  does not stop the *thread*.** A cancelled tool call correctly unwinds and can release whatever lock
  it held, while the worker thread underneath its `to_thread` call keeps running the blocking syscall
  to completion regardless — meaning a socket that lock was protecting can still be read from or
  written to by that orphaned thread after a *different* call has already acquired the lock and moved
  on to a fresh one. Getting this right took two full review rounds and touched three separate call
  sites (the ordinary send/receive path, and — a narrower case the same reasoning also applies to —
  connection establishment itself, where a socket a cancelled caller never sees can still be
  genuinely, successfully established moments later with nothing left holding it). The generalisable
  form: adopting `asyncio.to_thread` to fix an event-loop-starvation bug is necessary but not
  sufficient on its own — it trades a starvation bug for a cancellation-safety one, and only fixing
  both closes the class rather than moving it.
- **A residual risk disclosed with its bound stated is a legitimate stopping point; a residual risk
  glossed over as already handled is not, even when the surrounding fix is real.** M10's review round
  7 approved the milestone while explicitly flagging that `close()` is not a guaranteed way to wake an
  already-blocked `send`/`recv` on a separate thread — accepted because the practical consequence is
  bounded by an existing timeout regardless, and because the review had already spent six rounds on
  narrowing cancellation-safety edges specifically. What the same round would not let stand was a
  comment and a test docstring that had drifted into *overclaiming* the guarantee — stating that the
  close reliably wakes the orphaned worker, when the actual guarantee provided is detachment and
  non-reuse, with the worker's eventual exit merely *bounded* rather than *caused* by the close. The
  distinction matters for the identical reason a stale design paragraph matters: a comment that claims
  more certainty than the code actually provides is a confidently wrong memory of what was built,
  and it will mislead the next reader exactly as reliably as a wrong design paragraph would.
- **An estimand can survive nine rounds of increasingly careful engineering and still rest on a
  premise nobody had actually measured — and the single command that measured it settled in seconds
  what several rounds of confident implementation had assumed.** M11's own store-identity mechanism
  went through five distinct shapes across rounds 3–9, each one correctly closing the gap the
  *previous* round had found, until round 9 ran `PRAGMA database_list` against a connection opened
  through the mechanism's own supposedly-race-proof `/proc/self/fd/<n>` path and found SQLite
  reporting the ordinary, canonicalized pathname back — proving the whole mechanism's own premise
  false, not merely incompletely built. Nothing about that measurement required more review rounds;
  it required running one command against the real dependency instead of continuing to reason about
  its documented behavior. This is the identical shape as the earlier lesson about `asyncio`
  internals being "wrong three times in a row about things that read as obviously true" — the
  difference here is what happened *after* the measurement: recognizing that closing the gap
  *properly* (a custom SQLite VFS) was no longer proportionate to what it defended against (a
  sub-millisecond race at process startup, not the ordinary case the mechanism existed for) is a
  judgment call the review process itself could not make, and the human operator making that call
  explicitly — revert to the simple, honestly-documented capture, accept the narrow gap on stated
  authority — is itself a fourth instance of the same precedent M7's takeover reversal and M9's
  shutdown tradeoff already established for this corpus: a design decision, not a failure to
  converge. Directly relevant to what Zikaron is for: an engineering effort that keeps finding real
  problems is not evidence it should continue, and a memory system that only ever remembers "the
  bug was fixed" without also remembering "and here is where we deliberately stopped, and why" would
  misinform whoever reads it next just as confidently as if the fix had never happened at all.

- **Four premises about the harness were wrong, and every one was settled by asking the installed binary
  instead of reasoning about it.** Distribution is where a design meets the thing it has to run inside, and
  the corpus's own record had four claims about kiro that turned out to be stale, inverted, or never
  checked: that configuring `mcpServers` makes its tools available (it does not — `tools` selects, and an
  agent without `@zikaron` there reported *no* memory tools at all); that a hook's `command` is an
  executable path (it is shell source, run through `/bin/bash -c`, so an ordinary project path with a space
  loses both hooks with exit 127); that the hook timeout defaults to 30 s (10 s) and that no output cap was
  documented (`max_output_size`, 10240 bytes, truncating in silence); and that `kiro-cli agent validate`
  would catch a bad model id (it accepts one silently, and the harness then substitutes its default —
  exactly the silent fallback the design forbids). Three came from the binary's own embedded documentation,
  read through its `introspect` tool; two were confirmed by running one command and reading what happened.
  This is the same lesson as `KIRO_SESSION_ID` and `PRAGMA database_list`, and its third instance is the
  one that should make it a habit: **the local artifact is the authority on the local artifact**, and a
  design corpus that cites public documentation is citing a different artifact.
- **`gist_max_tokens` bounds tokens, and tokens do not bound bytes — my own test asserted otherwise by
  inventing a conversion factor.** The push block has to fit the harness's `max_output_size` or it is
  truncated silently, so I wrote a test "proving" five worst-case gists fit, using four bytes per token.
  Measured against the deployed tokenizer, WordPiece maps anything outside its vocabulary to a single
  `[UNK]`: an unbroken 4000-character run is **one token**, and so are 256 emoji. The bound was not
  conservative, it was fictional. The replacement test states what is measurable (the policy's real byte
  length; five gists of ordinary prose at the token ceiling) and *asserts the hole* for the adversarial
  case, with the fix located where it belongs — a byte bound in the write path's own bounds ladder, not in
  the hook's output cap. Directly the corpus's own "name the quantity before quoting a number about it",
  and the first time I committed it in code rather than in prose.
- **Seven review rounds, and three rounds' worth of defects were created by the previous round's fix.**
  Round 2's plan/commit split — introduced to guarantee nothing is written until every check passes — left
  the backup check *after* the shipped writes, producing exactly the half-install it existed to prevent.
  Round 3's "exclusive" temporary file closed its descriptor and reopened the path by name, reinstating the
  symlink-following hole the exclusive creation had closed. Round 4's shipped-path preflight used
  `Path.exists()`, which is **false for a dangling symlink**, so the case it was written for walked
  straight through it. The corpus already knows that a fix aimed at the reported case inherits that case's
  narrowness; the sharper form is that **a fix which restructures creates new seams, and the new seams
  deserve the scrutiny the original defect got** — none of these three was a narrowing of the original bug,
  each was a fresh one at a join the fix had just made.
- **A test whose execution model differs from production cannot see a whole class of defect, however
  end-to-end it looks.** The distribution suite drives the real installed console scripts as real
  subprocesses, which is why it caught real things — and it still could not see that a hook `command` is
  shell source, because it invoked `[command]` as an argv while the harness runs the string through bash.
  The fidelity that mattered was not "a real subprocess" but "the same *way* of starting it". Worth
  generalising: when a test stands in for a caller you do not control, the thing to copy is its execution
  model, and the parts you paraphrase are exactly where a defect can hide from you.
- **`Path.exists()` is false for a dangling symlink, and it cost two separate defects in one milestone** —
  a backup path that `shutil.copy2` would then have followed out of the project, and a shipped-target
  preflight that reported a dangling `SKILL.md` link as "kept" while the install exited 0 with no loadable
  skill. Both read naturally and both were wrong in the same direction: *absent* and *present but broken*
  are different states, and the stdlib's most obvious predicate conflates them. The same shape appeared a
  third time in the same milestone in a different vocabulary — `is not None` conflating an absent JSON key
  with a present `null`, which silently replaced four different user-authored values. **A presence test
  that cannot distinguish "nothing" from "something unusable" is a data-loss bug waiting for an unusual
  input.**

- **Ten minutes of real use found a design error seven review rounds had not, and it was one I had
  argued for explicitly.** The installer put `@zikaron` in the agent's `tools` but deliberately left it
  out of `allowedTools`, on the reasoning that auto-approving writes to a durable store is the user's
  trust decision — stated in the design, in the README, and in the installer's own output. The operator
  started dogfooding and reported it as a bug in the first session: every `remember` interrupts you for
  approval, which suppresses exactly the behaviour D30 asks for ("err toward recording", against prior
  art whose measured failure was recording too *little*) and trains the user to click through prompts.
  The reasoning was a rule imported from the wrong case: it is right about `subagent`, whose reach is
  genuinely wider than memory, and wrong about five tools that read and write rows in a local SQLite
  file with every write reversible by `retire`. Now allowlisted by default with `--no-trust-tools` to
  opt out. Two things worth carrying: the review loop pressure-tested whether the code did what the
  design said, and could not tell me the design was wrong about a *person's* experience of it — the
  same limit as "internal review pressure-tests consistency, not premises", in a new dimension. And the
  finding cost one session to surface, which is the strongest argument yet for dogfooding early rather
  than after a corpus is complete.

- **First fresh-context recall worked exactly as designed, and produced a confidently stale directive in
  the same breath.** Asked "Should I tune rrf_k?" in a session with no prior context, the dogfood agent
  answered from the **injected gist alone** — no tool call — and then volunteered, unprompted: "If you want
  the reasoning... I'd fetch the full record rather than go on the gist alone." That is D12's push arm,
  D13's relevance triage and D4/D21's progressive disclosure all working end to end on a real question, and
  the subsequent `fetch` quoted every figure from the content faithfully (+0.0705, 0.938 vs 0.922, 960/960,
  ~28%/72%), hedging where the memory had not told it something rather than inventing it.
  **The conclusion was defensible and the reasoning behind it was not what I first claimed.** My initial
  read was that the agent had blindly obeyed a directive whose scope had expired — "post-build" is now, since
  every milestone is complete, so tuning is precisely the parked work. The operator corrected that: the agent
  had reasoned that the build was *not* over because the last milestone was still uncommitted, which it knew
  from a **second** memory (the one recording a large uncommitted diff touching production modules, and that
  "HEAD alone does not reflect the working code"). Two memories used jointly to scope a third claim is good
  behaviour, not blind compliance, and the correction is recorded here rather than quietly amended because
  getting it wrong in this file is the exact failure this file is about.
  **What was genuinely wrong is narrower and still instructive.** The agent named the current phase **M5**,
  which finished long ago — so the scope it recovered was right by accident of a different fact rather than
  from the memory itself. And the recovery depended on an unrelated memory happening to be in the same store:
  the gist alone said "do not tune ... it's a deliberate standing instruction", with **no condition at all**,
  and on that basis the first answer was a flat "Don't tune rrf_k, fusion_depth, or arm weighting ... right
  now". The **imperative lived in the gist while its scope lived in the content**, so what got injected was a
  directive stripped of its qualifier; that a second memory rescued it is luck, not design.
  This is the corpus's own "a claim whose qualifier lives in a different paragraph will be recalled without
  its qualifier", realized in production with the **gist/content boundary as the paragraph boundary** —
  which makes it structural rather than incidental, since every memory has that boundary and the gist is the
  half that gets injected. Three consequences worth carrying: D30's prohibition on instruction-shaped gists
  is now evidenced rather than argued, and needs strengthening from "write observations, not orders" to
  something that also names **time-scoped** claims; a gist must carry its own qualifier or drop the claim,
  because the content cannot rescue it; and Zikaron generated the exact failure mode it exists to prevent
  within one session of first use, which is the most useful thing it could have done this early.

- **A known intermittent, found by the gate under load and left unfixed deliberately.**
  `test_idle_self_stop_unlinks_the_socket_before_the_process_exits` failed once during a full gate run that
  shared the machine with a live service and several subagents, and passed 3/3 in isolation immediately
  after, with neither `service/lifecycle.py` nor that test touched in the session. The mechanism is a real
  ordering window rather than test noise: `main.run` binds the socket in `serve()` and installs the
  `SIGTERM`/`SIGINT` handlers *after* it, while the test waits only for the socket to appear before calling
  `terminate()` — so under load a signal can arrive before the handler exists, the default disposition kills
  the process, and the socket is left on disk. Impact is low, since a stale socket is a case start-if-absent
  already handles by design, and the fix wants its own change with a test that pins the race deterministically
  rather than one that reproduces it under load. Recorded so the next person to see this failure does not
  spend the diagnosis again.

- **Planning determinism is verified against real data, and it is the first time that claim has been
  tested outside fixtures.** `consolidation.md` states planning is a pure function of the store plus its
  parameters — same store, same groups, every time. Two independent runs against a byte-identical store
  (restored from a `VACUUM INTO` backup, one prompt changed between them) produced **identical
  partitions**: 18 groups, sizes `[1×6, 2×11, 3×1]`, same membership in each. Worth recording because
  the consolidating agent's own report said "20 groups", and separately said 30 entries promoted where
  31 were — it caught the second slip itself by verifying uuids against the store, and missed the
  first. A model's count of its own tool calls is not a measurement; the store is.
- **The first real consolidation run worked, and the most encouraging thing in it was an agent
  declining to write a memory.** 31 journal entries became 15 long-term records: 13 created plus **2
  in-place tier flips**, so both `promote` forms fired on real data; 11 merge events; **0 discards**
  (it judged everything specific enough to keep, which is what "when in doubt, keep" asks for); 18
  groups all `complete`, every one served exactly **once**, 0 undispositioned members, and 93
  `group_served` rows delivered across them. Two runs exist and both are `complete` — the second
  planned nothing because there was nothing left, which is the correct shape for a re-invocation.
  **The consolidator hit a real tooling oddity and deliberately did not record it.** It issued two
  write calls in parallel within one turn and observed the second call's `remaining_uuids` reflecting
  a pre-first-call state; it verified correctness with a follow-up serve, lost nothing, and reported it
  to the operator as a bug **rather than as a memory** — reasoning explicitly that "don't parallelize
  consolidation writes" would outlive the fix and become a permanent rule whose condition had been
  dropped. That is the expiring-claim rule this project added hours earlier, applied unprompted, by a
  different agent, in a fresh context, to a case nobody had enumerated. The rule changed behaviour.
  **On the oddity itself, the store's committed record is verifiably correct**, which is worth stating
  precisely rather than either dismissing or accepting the diagnosis: the two suspect pairs commit as
  contiguous event ids with no interleaving (121–122 then 123–124, 122 ms apart; 181–182 then 183–184,
  665 ms apart), and there are **zero** `version_conflict` and **zero** `no_receipt` events in the
  whole store. So no transaction was mis-serialized and nothing was lost.
  **The mechanism converged from two directions and needs no store change.** The operator's own reading
  — the harness pushes agents to do work concurrently, so the model emitted both writes in one turn —
  meets what the client already does: `zikaron.mcp.connection` serializes concurrent calls on a
  connection lock, and an `asyncio.Lock` grants in *arrival* order, which for two coroutines dispatched
  together is not the order the model listed them in. So the call the model thinks of as second may
  have executed **first**, and its `remaining_uuids` legitimately predates the other write; the model,
  seeing results rendered in its own call order, reads that as staleness. No guarantee was violated
  because none exists. The fix is therefore in the **shipped consolidator prompt** — issue writes one
  at a time and read each answer before the next, stated with its reason (the store stays correct
  either way; what concurrency costs is the model's ability to trust its own bookkeeping). That is a
  versioned prompt rule, which is exactly the kind of thing the consolidator was right *not* to write
  as a durable memory. Still unconfirmed, and cheap to settle if it recurs: whether the two calls
  really did commit in the reverse of the listed order, which needs a reproduction logging both raw
  responses beside the event ids.

- **Day two: the repair loop fired for the first time, and one of the five amends is the exact failure
  this project was built around.** After a full working session in `~/Memory` — 114 pushes injecting 560
  gists (~4.9 of the 5-slot budget per message), 18 `fetch` calls against 10 `search` calls, 26 new
  memories, 36 receipt-gated mutation calls with **zero** conflicts and zero `no_receipt` — five
  `amend`s landed where the previous day had none. Four were journal rows refined after surfacing 3, 7
  and 20 times. **The fifth amended a long-term record to attach the condition its claim depends on**:
  "verify every reviewer finding against real code before applying it — the *twice wrong on mechanism*
  record was under claude-opus-4.8, not the current gpt-5.6-sol". That is a memory whose claim had
  silently become version-scoped, caught and repaired **in band, on a long-term row, after eight
  surfacings** — D11 doing exactly what it exists for, and the repaired gist now carries its own
  qualifier, which is what the write policy's newest rule asks for. Zero retires against five amends,
  which is also the policy's stated preference (repair in place; retire only when a claim is simply no
  longer true).
  **The new gist-length guidance landed on target.** The 26 new gists run 20–30 words (median **24**)
  and 27–43 tokens, against a stated target of "one sentence of about 20 to 25 words" and a 64-token
  bound none of them approached. The previous day's corpus, written before the rule existed, ran 10–32
  words.
  **And the dedup instrument cannot report for a month, which is a property worth knowing before
  relying on it.** All 18 offers sit in `pending`: only the `fully_resolved` outcome (amend **and**
  retire) closes early, so an offer resolved by an amend alone stays pending until
  `signal_horizon_days` elapses. Correct by design — a later retire would change the classification —
  but it means the signal gives no reading for 30 days on a store being actively tuned. The key is
  configurable down to 1, so an early-stage store that wants readings tomorrow can set it.
  **One number needs its qualifier quoted with it:** amend-after-surface reports `rate=1.00`, which
  means *3 of the 3 pairs that have resolved so far resolved by an amend* — with **51 still pending**
  and nothing yet aged out. Read as "the repair loop catches everything" it would be badly wrong, and
  that is exactly the shape of misreading this corpus keeps recording.

## References
- Prior Grok brainstorm — framing, D1–D9, unverified benchmark list — `research/initial-brainstorm-transcript.md`
  (verbatim extract; the source PDF was deleted 2026-08-01 at the user's request).
- Prior art as built — schema, RRF+recency ranking, `/sleep`, `merge_reframes` — `~/Memory/design/long-term-memory.md`, `~/Memory/design/ltm-revision-revamp.md`; digested in `design/prior-art.md`.
- kiro-cli hooks + `introspect` — exactly 5 triggers (`agentSpawn`, `userPromptSubmit`, `preToolUse`,
  `postToolUse`, `stop`); **no compaction hook** (confirms D10); `userPromptSubmit` and `agentSpawn` are the
  only two whose stdout reaches context on exit 0; `preToolUse` can block via exit 2; hook entries take
  `command` / `matcher` / `timeout_ms` / `cache_ttl_seconds`. **Three items in that file are superseded by
  the installed binary's own embedded docs** (kiro-cli 2.16.0) and carry a dated erratum at its head: the
  `timeout_ms` default is **10 s**, not 30; hook stdout has a documented cap, **`max_output_size`, default
  10240 bytes, truncating silently**; and the "`--v3` uses an incompatible standalone `.kiro/hooks/`
  schema" note is not the distribution problem it looked like — the **stable** agent config accepts *two*
  interchangeable `hooks` formats (object and array) — `research/kiro-cli-hooks-and-introspect.md`.
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
- **M8 code review** — two rounds, ending `VERDICT: APPROVED`, with three genuine blockers in the
  first and none in the second. `repair.py`'s `RepairCounts` omitted `signal_horizon_days`, which
  `schema.md` requires both cross-event signals to carry; `dedup.py`'s `DedupResolution` held its
  five outcome counts in a `dict[DedupOutcome, int]`, which `frozen=True` does not protect from
  in-place mutation, a concrete way its documented `[0, 1]`-bounded-by-construction guarantee could
  be defeated; and `write_size_distribution` returned a bare `tuple[int, ...]` with no `ORDER BY`
  on its three-branch `UNION ALL`, leaving a required-deterministic instrument's order genuinely
  unspecified. All three fixed — the horizon added to `RepairCounts`, `DedupResolution` rebuilt as
  five named non-negative fields with a `count_for()` accessor, and `write_size_distribution`
  returning a frozen `WriteSizeDistribution` ordered by `event.id` — and the determinism test
  written for the last fix caught a coincidentally-passing fixture in itself before shipping, per
  the dogfooding note above. Round 2 re-verified every fix at the specific line and found no call
- **M9 code review** — **fourteen rounds, and it did not converge**: every round found at least one
  genuine, independently verified defect, so the loop was stopped by operator direction rather than by
  reaching `APPROVED`. Read it as the counter-example to M1–M8's trail: those ended clean, this one
  never did. Four rounds found production-breaking defects and all four were in shutdown — a bare TCP
  connect accepted as `health()` readiness before the start-if-absent lock was released (round 5); the
  three consolidator writes registered under `merge`/`promote`/`discard` when the design names them
  `apply_*`, which no test could catch because every consolidator test called the Python handlers
  directly (round 8); an ordinary idle-but-connected client hanging shutdown forever on
  `wait_closed()` (round 9); and the fix for *that* deadlocking against `serve_forever()`'s own
  cancellation, resolved by never calling `serve_forever()` at all (round 11). Rounds 13–14 then found
  the operator-directed force-exit fallback implemented in an unreachable place twice over, which is
  the most instructive part of the whole trail — `reviews/m9-service-review.md`.
- **M10 code review** — **seven rounds, ending `VERDICT: APPROVED`**, with a genuine defect in each of
  the first six — the longest *converging* trail of any milestone, distinct from M9's trail in that
  every round found something and every round's fix held once made. Round 1: missing session-label
  adoption (the client re-bootstrapped a fresh label every call instead of adopting the service's own
  returned one — a functional break, not observability drift), a forwarded `zk`-prefixed harness value
  violating the reserved namespace, a symlink-bypassing bare `mkdir` in the log-ordering fix, an
  unlocked `_PlanBridge` permitting two concurrent takeovers. Rounds 2–4: `sendall`'s own documented
  inability to report partial-send progress, a real `send()` zero-return case that could spin forever
  holding the connection lock, and an established socket silently keeping a 1-second *connect-phase*
  timeout that would cut off any request waiting out the store's own 5-second contention window. Round
  5 found something nobody asked for while writing the test for round 4's own fix: a concurrent
  `asyncio.sleep` measured resuming *later than its own coded duration*, exposing that
  `ServiceConnection`'s socket I/O was fully synchronous inside `async def` methods — the identical
  self-inflicted-deadlock shape `coding-standards.md` §6 documents for the service's own blocking SQL
  calls, now found on the MCP client. Round 6 found the same defect class twice more (synchronous
  filesystem calls, and — traced to its root — two already-`APPROVED` M2 files' own permission checks)
  plus two cancellation-safety gaps `asyncio.to_thread`'s own inability to interrupt a running thread
  makes possible. Round 7: no blocker, one nitpick, and a genuine timing bug caught in the review's
  *own* test for round 6's fix. One risk — `close()` not reliably waking an already-blocked socket call
  on a separate thread — was weighed and deliberately disclosed as bounded rather than layered with
  further defenses, given six rounds already spent on cancellation-safety edges — `reviews/m10-mcp-
  client-review.md`.
- **M11 code review** — **eleven rounds, ending `VERDICT: APPROVED`**, the longest trail of any
  milestone. Rounds 1–2 covered the client broadly (eight blockers in round 1: a missing `flock`
  lock/recheck in start-if-absent; `push.py`/`spawn_warm.py` catching only named exception types
  rather than genuine `Exception`; a false umask-independence claim in `failure.py`'s own docstring,
  measured wrong directly, plus that function never creating its own parent directory;
  `print(output)`'s stray trailing newline; `warm_helper.py` configuring its own log before securing
  the directory that log needs; an unreachable store-identity check from an always-`None` `store_id`;
  a hand-maintained denylist standing in for `test_hook_stdlib_only.py`'s own enforcement; a stale-
  text sweep gap. Two improvements: a `coding-standards.md` §4 carve-out for in-process socket-bound-
  on-a-background-thread tests; docstrings trimmed of round-by-round changelog narrative). Rounds
  3–9 were a single continuous engineering arc on one question — can a stateless, no-store-access
  client verify store identity across a connect-time replacement race — that took five different
  shapes (a path-only check; a service-side inode-drift poll; a pin-then-compare-against-a-second-
  path-read; a `/proc/self/fd` scan for SQLite's own descriptor; connecting directly through the
  pinned descriptor's own `/proc/self/fd/<n>` path) before round 9 measured, directly via `PRAGMA
  database_list`, that the last of these does not actually work as reasoned — SQLite's own VFS
  canonicalizes that magic-symlink path back to the ordinary pathname internally. The human operator
  was consulted at that point and directed reverting to the simple capture (a bare `db_path.stat()`
  immediately after connect) and accepting the narrow, sub-millisecond startup-instant race as a
  documented, out-of-scope gap rather than pursuing a VFS-level fix — recorded in both the design and
  the code as a decision, not a silent regression. Round 10 found one genuine bug the revert itself
  introduced (the reverted `stat()` sat outside the existing close-on-failure boundary, a real
  resource leak on the one path it could raise) and a design-prose contradiction from the revert
  (overclaiming that a stale connection "keeps serving...regardless" beside the sentence recording
  round 9's own finding that it can still fail) — both fixed and mutation-verified. Round 11
  approved with one cosmetic nitpick (a stale test-docstring cross-reference), fixed immediately —
  `reviews/m11-hook-client-review.md`.
  site anywhere still referencing the removed interfaces — `reviews/m8-signals-review.md`.
- **M12 code review** — **seven rounds, ending `VERDICT: APPROVED` with no findings**, and a genuine defect
  in each of the first six. Round 1: the installed primary agent got no memory tools at all, because
  `mcpServers` configures a server and `tools` selects from it (measured both ways); the output-cap "proof"
  multiplied tokens by an invented four-bytes-per-token factor; the README's secret-removal advice
  contradicted the design's own erasure procedure; the skill contradicted itself on `busy`. Round 2: the
  shipped files were written before the user's config was parsed; three shapes of user data were silently
  dropped by defensive filtering on a write path; the atomic writer's `<target>.tmp` was a predictable name
  a symlink could redirect. Round 3: a world- or group-writable store let another uid supply a policy file
  that goes straight into a model's context, and the rejection of that finding in round 2 rested on a false
  same-uid premise; an entry differing from ours in any field but the command was overwritten silently.
  Round 4: a symlinked `--agent` was severed rather than merged or refused; the two shipped paths had no
  preflight, so a directory at `SKILL.md` exited 0 with no loadable skill and a file at `.kiro/skills`
  raised `NotADirectoryError` mid-install; `os.write` was called once and its return ignored. Round 5: the
  preflight used `exists()`, false for a dangling symlink; the store directory was validated by pathname
  and the override then read by resolving that pathname again; explicit JSON nulls bypassed every shape
  guard; `--agent` could name the consolidator config and convert it into a primary agent. Round 6: the
  hook `command` is shell source and was emitted unquoted, so an ordinary path with a space loses both
  hooks — measured against the real harness, exit 127. Two findings were **rejected with reasons the review
  accepted**: refusing a symlinked `.kiro` *ancestor* (a legitimate dotfile setup, and the threat model it
  would close is already open upstream, since kiro reads agent configs out of that same tree), and having
  the `agentSpawn` hook tighten store modes synchronously (a filesystem mutation on the one path whose
  contract is that it cannot fail) — `reviews/m12-distribution-review.md`.
