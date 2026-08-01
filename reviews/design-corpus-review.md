## Round 1

### Summary judgment

The corpus has a strong scope line, unusually candid evidence limits, and mostly preserves the benchmark review's narrowed conclusions; `prior-art.md` is also a faithful account of `~/Memory`. It is not build-ready yet: two settled guarantees are contradicted by the executable contracts (superseded records are filtered out, and a predictable integer version cannot prove a fetch), while the consolidation protocol has lost-update and silent-omission paths. Several ranking, chunking, event, permission, and error semantics also require specification before two competent implementations would behave the same.

### Cross-document findings

1. **[BLOCKER] Superseded records are hidden by the specified default query, contradicting D25's central “demote rather than hide” behavior.** `design/schema.md`, “Invariants the code must hold,” invariants 3–4 (lines 146–151), defines every superseded row as `active=0`; `design/retrieval.md`, “Fusion” (line 42), filters to `active=1` unless retired records are explicitly requested. The push RPC has no `include_retired` argument (`design/architecture.md`, “Service RPC surface,” line 177), so a superseded row cannot land in the injected five at all, despite `design/overview.md` D25 and `design/retrieval.md`, “Superseded records surface, demoted,” saying it must remain eligible. Resolve by defining default eligibility separately for (a) active rows, (b) superseded rows, and (c) outright-retired rows; make push and pull use that same predicate; and specify the actual supersession penalty/ordering. For example, default retrieval could include `active=1 OR superseded_by IS NOT NULL`, exclude only `active=0 AND superseded_by IS NULL`, and apply a named deterministic demotion to the former.

2. **[BLOCKER] D26 does not mechanically enforce read-before-amend, and the tool signatures directly falsify “fetch is the only source of version.”** `design/overview.md` D26 says an agent “cannot produce a valid version without having fetched the record,” and D32 says `fetch` is the only source of `version`. But `version` starts predictably at 1 in `design/schema.md` (`memory.version`, line 49), while `zikaron_remember` and successful `zikaron_amend` return a version in `design/architecture.md` (lines 113–119). An agent can also guess `1` for any UUID returned by search. The integer still prevents lost updates, but it is not proof of a read. Preserve the settled enforcement requirement by adding an unguessable, session-bound read capability (or a server-side `(session_id, uuid, version)` fetch ledger) required by amend/retire; alternatively, explicitly withdraw the mechanical read-before-write claim and retain version only as optimistic concurrency, but that would change D6/D26's stated guarantee.

3. **[BLOCKER] Consolidator writes cannot satisfy D26 for the rows they retire.** `design/consolidation.md`, “Interactions” (lines 98–100), says the consolidator passes versions “like any other writer.” `zikaron_next_group` supplies versions for every journal entry and candidate, but `zikaron_merge` accepts a version only for the target, while `zikaron_promote` and `zikaron_discard` accept no expected row versions at all (`design/architecture.md`, lines 138–158). If a primary agent amends an absorbed journal row after `next_group`, consolidation can retire that fresh content without a conflict. Change every affected-row argument to `{uuid, expected_version}` (including discarded and absorbed rows), validate all versions before any mutation, and commit the target rewrite/new record, index rebuild, and all retirements in one transaction. A mismatch must mutate nothing and return every current conflicting record needed to re-decide.

4. **[BLOCKER] A group can be marked processed while journal entries in it receive no disposition.** The grouping mechanism explicitly allows the model to decide that observations sharing a topic should merge, split into something new, or be discarded (`design/consolidation.md`, “Mechanism” and “Consolidator identity and model”). Each write tool takes a subset (`absorb_uuids` or `uuids`), yet `design/architecture.md`, “This makes D29's never-lose guard structural” (lines 164–167), says one write verb marks the *group* processed. A mixed group requiring “merge A, promote B, discard C,” or simply an accidentally omitted UUID, can therefore silently strand or skip rows. Define completion at journal-row granularity: allow multiple actions for one `group_id`, track each UUID's disposition, return `remaining_uuids`, and declare a group complete only when every originally delivered active journal UUID was successfully dispositioned at its expected version. Empty or unknown subsets must not complete a group.

5. **[BLOCKER] The chosen orphan clustering still has the exact chaining failure its rationale claims to prevent.** `design/consolidation.md`, “Mechanism,” step 2 makes groups the connected components of a mutual-top-K graph. “Why mutual-K over single-linkage-on-threshold” then claims mutuality resists `A~B, B~C, A≁C` chaining, and `design/overview.md` D29 repeats that rationale. Connected components are still single-linkage over the accepted mutual edges: if A↔B and B↔C, all three are one component even when A and C are not neighbors. Add a cohesion rule that actually prevents the stated failure (for example complete-link/diameter validation, clique-based splitting, or a post-component pairwise check), define its deterministic split behavior, and make the A↔B↔C chain an acceptance test. Merely testing the current algorithm will confirm the defect, not cure it.

6. **[MAJOR] D15 describes “every write call” searching first and stopping duplication, while the only specified dedup response is an unconditional `remember` that leaves the duplicate active.** `design/overview.md` D15 says every write call first searches and returns a near duplicate so the agent can amend instead; its rationale says this stops journal duplication. `design/architecture.md` gives only `remember` a `near_duplicates` field and says it writes unconditionally *then* reports them (lines 113–115); amend/retire return no dedup result. If the agent subsequently amends the older row, the just-created duplicate remains active, so no duplication was stopped. Decide and document one contract: either (a) D15 is advisory duplicate detection on `remember` only and duplicates persist until consolidation, with the rationale and instrumentation renamed accordingly, or (b) the agent's amend decision atomically retires/supersedes the just-created row. Also state that the new row is excluded from its own near-duplicate search and whether the search occurs before or after insertion.

7. **[MAJOR] `session_id` is called server-captured, but no MCP/RPC contract conveys a Kiro session to the shared service.** `design/overview.md` D27 says provenance is server-captured so writes gain no parameters. The hook payload has a session ID, but `design/architecture.md` specifies `surface(prompt, limit)` and the five MCP methods with no request metadata carrying it (lines 103–177). A long-running service shared by two sessions cannot infer which session originated an MCP request. This also breaks per-session D30 signals. Define a trusted client-to-service request envelope containing `session_id` (populated by `zikaron-hook` and the per-session `zikaron-mcp` process), state the source and validation/fallback when unavailable, and define whether consolidation records retain source provenance or use the consolidator session.

8. **[MAJOR] The current never-lose protocol in `consolidation.md` is the rejected `~/Memory` parser protocol, not D32's tool protocol.** `design/consolidation.md`, “Never lose silently” (lines 84–89), requires a well-formed free-text block, nudge ×3, and a present-but-empty block. `design/architecture.md` (lines 164–167), `design/overview.md` D32, and `design/prior-art.md`, “Lessons carried across,” explicitly say Zikaron has no parser or retry protocol because per-group tool calls replace it. Rewrite the consolidation section around the row-level tool completion invariant from Finding 4; retain the block/nudge behavior only as clearly labeled prior art.

9. **[MAJOR] Several design figures are stale relative to the final approved benchmark, despite `retrieval.md` claiming every number traces to that report.** `design/retrieval.md`, “Reranking” (line 114), gives 6069 ms for 50 gist+content pairs, while the final `research/embedder-benchmark-results.md` gives 6592 ms p50 (Facts, settled/open table, and §10). `design/architecture.md`, degraded mode step 2 (line 88), and `design/retrieval.md`, “Degraded retrieval” (line 142), quote BM25 0.859 versus best 0.969; the final blind-set figures are BM25 0.8802, incumbent hybrid 0.9375, and best tested hybrid 0.9479. The 5.5/8.0 ms warm figures in `architecture.md`, “Components” (line 18), are the no-prefix 5.45/7.97 measurements, not the adopted prefixed path's 6.64/9.14. Replace stale values with the final report's figures and label the comparator/configuration; retain the narrowed reranker scope and cloned-tail caveat. The important narrowed claims about bge-large, capacity, the prefix, truncation, and pull-path reranking otherwise remain faithful.

### `design/overview.md` and `FINDINGS.md`

10. **[MINOR] D14 says “Benchmarking is stoved until an initial implementation exists,” although D20–D25 are already settled from a pre-implementation retrieval benchmark.** This is visible within the same decision table (`design/overview.md` D14 versus D20–D25) and in `FINDINGS.md`, which calls the retrieval stack benchmarked while leaving end-task evaluation open as question 9. Narrow D14 to “end-to-end task-benefit evaluation/tuning is deferred until implementation” so it does not deny the evidence the next decisions use.

11. **[MINOR] Architecture claims to close open question 4 while `FINDINGS.md` deliberately retains its unmeasured half.** `design/architecture.md`'s opening says it “closes Open question 4,” but its final section and `FINDINGS.md` question 4 still list RPC latency, contention, hook placement, and context-size behavior as unmeasured. Say the document closes the *shape decision* and narrows the question to integration measurements; do not describe the full question as closed.

### `design/schema.md`

12. **[MAJOR] The event schema does not yet make three of D30's six signals reproducible.** `event.detail` is untyped JSON (“shape varies by kind,” line 114), while the mapping table requires `surface` to identify each of five surfaced UUIDs and `dedup_offered` to identify each offered target. It never states whether those are one event per memory or arrays, how an offer is correlated to the creating `remember`, or how concurrent events are ordered. Separately, “write size distribution” reads `memory.token_count`, which contains only each row's latest size, not the distribution of historical remember/amend writes requested in `design/write-policy.md` §3. Specify per-kind event schemas and cardinality, add a request/operation ID for correlation, log token count on every remember/amend event, define whether “writes per session” includes amendments, and insert mutation events in the same transaction as the mutation. Then define the six queries against those shapes.

13. **[MAJOR] The schema permits invalid supersession graphs and does not define a twice-superseded memory.** `memory.superseded_by` is only a foreign key (line 48). It permits self-links, cycles (`A→B→A`), links from an active row, and links to an already-retired/no-replacement row; if `A→B` and later `B→C`, no spec says whether retrieval follows to C, demotes by chain depth, or rewrites A. Add code/schema invariants for `superseded_by IS NOT NULL ⇒ active=0`, no self-edge, acyclicity, allowed target state/tier, and immediate-edge versus canonical-latest semantics. Define traversal and cycle-defense for retrieval/fetch, plus tests for A→B→C and concurrent attempts to create a cycle.

14. **[MAJOR] Atomic index synchronization is specified only for amend, not for every operation that creates or rewrites indexed prose.** `design/schema.md` invariant 2 and `design/indexing.md`, “Implementation constraints,” cover amend. `remember`, promote-by-tier-flip with rewritten gist/content, promote-by-new-row, merge, and a full reindex also touch `memory`, external-content FTS5, `memory_chunk`, and `memory_vec`, but their transaction boundaries are unstated. A service death between these steps can commit prose without one index or retire source rows without the replacement. State that each logical mutation is one SQLite transaction covering the memory rows, explicit FTS5 maintenance, chunk/vector maintenance, version changes, and its event; define vector-before-chunk deletion order (the vec table has no FK); and define full reindex as an atomic build-and-swap or an unavailable-until-complete operation, including dimension-changing vec0 recreation.

### `design/architecture.md`

15. **[BLOCKER] `group_id` has no ownership, lease, persistence, or stale-plan semantics, so two consolidators can receive and process the same group.** `zikaron_next_group` returns an opaque ID, but the schema has no run/group state and the service surface separately lists `plan_groups()`/`next_group()` without saying when a plan is created. A second manually invoked skill can get the same oldest rows; a service restart can invalidate an in-memory ID; an idle/crash can leave a claim forever. Optimistic concurrency on only the merge target does not solve this (Finding 3). Either serialize consolidation per store with an explicit lock and deterministic “already running” result, or add persisted run/group claims with owner, expiry, membership snapshot, and statuses. Define restart recovery, stale/unknown `group_id` errors, and when `remaining` is computed.

16. **[MAJOR] The tool/RPC contracts omit required non-success outcomes.** The signatures in “MCP tool surface” and “Consolidator tool surface” specify success and sometimes version conflict, but not: missing UUID in `fetch`; whether fetch preserves input order and how duplicate UUIDs behave; amend/retire of inactive rows; invalid/self/cyclic `superseded_by`; a target not in the delivered group; stale/expired group IDs; partial absorb lists; `SQLITE_BUSY` after 5 seconds; or embedding/index failure. Add a compact error table with stable JSON-RPC codes and payloads, bounds for `limit`/list sizes/text sizes, and an all-or-nothing rule for batch fetch and mutations. Empty-store behavior should be explicit: `search=[]`, `surface` emits nothing, and `next_group={done:true}`.

17. **[MAJOR] UDS permissions protect only the socket; the durable knowledge and fallback directory are not secured to the same standard.** `design/architecture.md`, “RPC” and “Paths,” requires a 0600 socket in a 0700 runtime directory, but gives no modes for `<cwd>/.zikaron`, `memory.db`, WAL/SHM files, or `service.log`. Under a permissive umask, another local user who can traverse the project can bypass the API and read the DB. The predictable `/tmp/zikaron-<uid>` fallback also needs owner/symlink checks before unlinking sockets or taking locks. Require `.zikaron` mode 0700 and DB/WAL/SHM/log mode 0600, reject symlinked or wrong-owner runtime/store paths, validate an existing fallback directory's owner and mode, and state plainly that same-UID processes remain trusted because 0600 UDS is not authentication against them.

18. **[MINOR] The truncated socket hash has no collision defense, which can route a client to the wrong project store.** `design/architecture.md`, “Paths” (lines 45–48), does not give `<h>`'s length, and `health()` has no response contract identifying the canonical store. Specify at least a collision-resistant length (for example 128 bits) and have readiness return the canonical store identity; a client must reject a live socket whose identity does not match before sending any read or write.

### `design/retrieval.md`

19. **[MAJOR] Dense memory ranking is not implementable unambiguously from “max over chunk scores.”** `design/indexing.md`, “Ranking,” and `design/retrieval.md`, “Fusion,” never define whether sqlite-vec's returned quantity is distance (lower is better) or a converted similarity (higher is better). More importantly, a fixed top-N chunk KNN followed by memory dedup/filtering can return fewer than N memories: one long memory or retired rows can occupy the chunk candidates before dedup. Define “best chunk” in the actual sqlite-vec metric (`min(distance)` or an explicit monotone similarity), the KNN overfetch/adaptive expansion algorithm, when active/tier filters apply, and the stopping condition that yields the requested number of distinct eligible memories or exhausts the index. This same primitive must be used for push, pull, dedup, anchors, and orphan edges.

20. **[MAJOR] RRF has no total tie order even though the approved report identified insertion order as a real design defect.** `design/retrieval.md`, “Fusion,” fixes RRF at k=60 and later discusses the arm-agreement defect, but never specifies tie handling. The final report found a top-five tie on 12.5% of incumbent queries and said insertion order should be replaced with an explicit tie-breaker; `FINDINGS.md` also warns that result order must mean what the reader assumes. Define a deterministic, semantic total order after fused score (including how best lexical rank, best dense rank, tier, the journal-local recency tiebreak, and UUID participate). Use the same order for cutoffs, surfaced output, and consolidation adjacency.

21. **[MINOR] Raw user prompts and agent queries need a defined FTS5 query-construction rule.** `design/retrieval.md` says push uses the prompt verbatim, but a verbatim string is not necessarily a valid safe FTS5 `MATCH` expression: quotes, parentheses, `OR`, `-`, and punctuation-heavy errors can change semantics or raise syntax errors. Specify parameter binding plus literal-term escaping/tokenization, behavior for a query with no lexical tokens, and whether advanced FTS syntax is ever intentionally exposed. The dense arm should still run if the lexical query is empty or invalid.

### `design/indexing.md`

22. **[MAJOR] The 450-token chunk contract can still silently truncate because it budgets content before prepending an unbounded gist.** “Chunk construction” first fills content to `chunk_max_tokens=450` and only then prepends the gist; “Implementation constraints” calls the remaining 62 tokens headroom, but neither schema nor tool contract bounds gist length. A 100-token gist plus 450-token content exceeds BGE's 512-token cap. The tokenizer used for counting/hard splits and the treatment of special tokens are also unspecified; empty content can produce zero chunks even though the dense path assumes a vector. Define the exact deployed tokenizer and count the final embedded sequence (gist, separator, content, special tokens) against a hard model limit; split content by the remaining budget, reject or separately truncate an over-budget gist with an explicit error/canary, and define empty content as invalid or as one gist-only chunk. Set `truncated` from this preflight rather than relying on fastembed's silent truncation.

### `design/consolidation.md`

23. **[MAJOR] `next_group.candidates` does not match the grouping mechanism's candidate definition.** The mechanism anchors each journal row to one long-term record and groups rows sharing that anchor (steps 1–2), while “Consolidator identity and model” promises “5 candidate memories” and `design/architecture.md` returns an unexplained plural `candidates` list. It is unclear whether the list is the shared anchor only, the union of every member's top five, or a fresh group-level search; no dedup/order/cap is specified. Define candidate construction exactly, identify the anchor in the payload, include the retrieval order needed for deterministic reproduction, and specify the empty-list orphan case.

24. **[MAJOR] Oversized-group splitting and oldest-first ordering are not deterministic.** `design/consolidation.md`, “Mechanism,” says “cap group size; split oversized groups” without an algorithm, and orders by earliest `created_at` without a tie-break. Different splits change model decisions, and concurrent writes can share a timestamp. Specify the partition rule (not just the cap), whether an anchor is repeated into each shard, and a total group order such as `(earliest_created_at, minimum_uuid)`. Also define whether groups are replanned after each successful action or whether a snapshot remains fixed; “updating the store as we go” currently allows both readings.

25. **[MINOR] The imported “survivor rule: keep longest” has no operation to which it applies.** `design/consolidation.md`, “Lessons stolen from `~/Memory`,” makes it a requirement, but Zikaron's merge rewrites an explicitly targeted long-term UUID and promote either flips a single journal row or creates a new UUID. No automatic survivor is selected among duplicate rows. Either connect the rule to a precise promote/merge case and define “longest” in tokens/characters, or relabel it as a prior-art lesson not used by Zikaron; `design/prior-art.md` already records it accurately in that role.

### `design/write-policy.md`

26. **[MAJOR] The injected policy can encourage durable secret capture and the surface has no memory-poisoning boundary.** The “Worth recording” list (line 44) includes “credentials” without saying names/requirements only, while memories are durable local data and gists are injected into model context. A tool output, README, or compromised prior memory can therefore cause an agent to store a credential value or instruction-shaped gist that future agents treat as policy. Change the prompt to prohibit secret values, tokens, private keys, PII, and copied credential material while allowing variable names and setup procedures. The push formatter should delimit memories as untrusted reference data that must never override system/user instructions, and remember/amend should have bounded gist/content sizes; document inspection/deletion/recovery expectations without weakening D16.

### `design/prior-art.md` and `design/README.md`

No independent defect found. `prior-art.md` accurately distinguishes `~/Memory`'s one-pass free-text `/sleep` protocol from its later cosine `merge_reframes`, and accurately states that Zikaron intended to replace the parser retry with tool calls; the inconsistency is in the current `consolidation.md` text identified above. `README.md` correctly indexes the corpus. The D1 scope line is consistently enforced across the corpus: code locations and symbol facts are excluded, while procedural facts about commands, environments, failures, and unsafe APIs remain in scope.

VERDICT: NEEDS_CHANGES

---

## Response to review round 1

**26 findings, 26 accepted, 0 rejected.** That is an uncomfortable ratio to report, so it is worth saying
why it is honest rather than compliant: every finding was checked against the source it cites, and each one
turned out to name a real contradiction, a real stale figure, or a real gap that would have made two
implementations differ. Three findings (1, 2, 5) identified places where a document contradicted the very
decision it claimed to implement — the kind of defect that only cross-reading catches, which is exactly what
this corpus had never had.

Where a remedy differs from the one suggested, that is stated under the finding. **No user decision (D1–D32)
was reversed.** Five *rationales* were corrected — D14, D15, D26, D28, D29 — because they asserted properties
their own mechanisms did not have, plus D30's prompt text and D31's figures. Each correction is labelled
"corrected after the corpus review" in `design/overview.md` §4 so the change is auditable rather than
silently absorbed.

### Cross-document findings

**1. [BLOCKER] Superseded records hidden by the default predicate — ACCEPT.**
Correct, and it inverted D25. Fixed by defining eligibility once, as a named predicate over three row states,
and making every read path use it verbatim.
- `schema.md` new §"Retrieval eligibility — one predicate, three row states": live / superseded /
  retired-outright, with `ELIGIBLE(include_retired=0) = active = 1 OR superseded_by IS NOT NULL`. Only
  `active=0 AND superseded_by IS NULL` is excluded by default.
- Invariant 4 rewritten so the retained FTS/vec rows are justified by that predicate rather than by an
  `active=1` filter; the old `idx_memory_active` is now `idx_memory_eligible(active, superseded_by)`.
- `retrieval.md` §Fusion no longer filters `active = 1`; it points at the predicate and states that push,
  pull, dedup, anchors and orphan edges all share it. No `include_retired` was added to the push path — it is
  not needed, because superseded rows are eligible *by default*; `include_retired` stays on `search` and now
  means only "also the rows nobody replaced".
- The demotion is specified, per your request for a named deterministic rule, in `retrieval.md`
  §"Supersession: eligible, demoted, and labelled": a `supersession_penalty` multiplier on the fused score
  (default 0.5, in `meta`), applied on the immediate edge and **not** scaled by chain depth, plus a pairwise
  rule that **a replacement is always placed immediately above the record it replaced** whenever both
  retrieve. That second rule directly attacks the measured 28–50% displacement, and it is honest about its
  limit: it cannot help when the replacement did not retrieve, which is why the penalty exists too.
- `overview.md` D25's rationale now records that "demote rather than hide" is a query-predicate decision and
  names where the predicate lives.

**2. [BLOCKER] D26 does not mechanically enforce read-before-amend — ACCEPT.**
The objection is exactly right: `version` starts at 1, increments predictably, and is returned by `remember`
and `amend`, so `1` is guessable for any uuid a search returned. A predictable integer prevents lost updates;
it does not prove a read.

Of your two remedies I took the **fetch-ledger** form rather than an opaque capability token, and rather than
withdrawing the claim. Withdrawing would have been the softer option and it would have quietly weakened a
user-settled guarantee — D6's decision text says read-before-amend is "enforced mechanically by D26, not by
trust" — so the right move was to make the mechanism real.
- `schema.md` new `read_receipt(session_id, memory_uuid, version, at, source)` table, `WITHOUT ROWID`,
  PK `(session_id, memory_uuid, version)`.
- Invariant 9: `amend`, `retire`, `merge`, `promote`, `discard` each require a matching receipt for **every**
  row they mutate. Receipts are minted only when full content was actually delivered — `fetch`, a
  `next_group` payload, a **conflict response**, or the caller's own successful write (`own_write`).
- Minting on the conflict response matters and is deliberate: without it, D26's promise that the agent
  "re-decides in one round trip" would be false, since the retry would fail for want of a receipt.
- `own_write` covers your specific objection to `remember`/`amend` returning a version: the caller authored
  that exact prose, so it has demonstrably seen it. The version in those responses is now legitimate rather
  than a hole in the guarantee.
- Bounded, not pruned by age: a version bump deletes every receipt for that uuid except the writer's own, so
  the table stays ~one row per (session, memory) at the current version. `event` may be pruned by age;
  `read_receipt` may **not**, and `schema.md` says so, because pruning would revoke a correctness precondition.
- New `no_receipt` event kind and `−32002 no_read_receipt` error, reported separately from
  `version_conflict` — "wrote without reading" and "read something stale" are different agent behaviours and
  D30's instrumentation now distinguishes them.
- `overview.md` D26's rationale rewritten to state the false claim, why it was false, and what replaced it.
  The pre-existing "read-before-write, not understood-before-write" limit is retained verbatim.
- Known cost, stated rather than hidden: receipts are keyed on the client-supplied `session_id`
  (finding 7), so a client that changes its label mid-session loses its receipts and must re-`fetch`. That
  fails **closed** — it rejects writes rather than admitting unread ones — which is the right direction.

**3. [BLOCKER] Consolidator writes cannot satisfy D26 for the rows they retire — ACCEPT.**
Every affected-row argument is now `{uuid, expected_version}`.
- `architecture.md` §"Consolidator tool surface": `merge(group_id, target:{uuid,expected_version}, gist,
  content, absorb:[{uuid,expected_version}])`, and the same `absorb` shape on `promote` and `discard`.
  `absorb_uuids`/`uuids` are gone.
- Validate-all-before-mutate is explicit, and a mismatch **mutates nothing** and returns the current record
  for **every** conflicting uuid — not just the first — so the model can re-decide in one round trip.
- One transaction covering the target rewrite, index rebuild, every retirement, receipts and events:
  `schema.md` invariant 2, which now names `remember`/`amend`/`retire`/`merge`/`promote`/`discard` rather
  than amend alone.
- Membership is spelled out to close a related ambiguity your finding implies: the target must be the
  group's anchor or one of its candidates (long-term records, not members); `absorb` rows must be members,
  i.e. journal rows delivered in this group and not yet dispositioned.
- `consolidation.md` §Interactions no longer says the consolidator "passes versions like any other writer";
  it says which rows, validated when, and what a conflict returns.

**4. [BLOCKER] A group can be marked processed while members receive no disposition — ACCEPT.**
Completion is now defined at journal-row granularity.
- `schema.md` adds `consolidation_group_member(group_id, memory_uuid, version_seen, disposition,
  disposed_at)` and invariant 16: `status='complete'` requires zero members with `disposition IS NULL`, and
  nothing else may set it.
- Multiple actions per `group_id` are explicitly legal — a mixed group takes three calls.
- Every response carries `remaining_uuids`, computed at response time from the member table, plus
  `group_complete: bool`.
- Empty `absorb`, a uuid outside the group, and an already-dispositioned uuid are all **errors** that mutate
  nothing (`−32013 not_in_group`), so neither silence nor a typo can complete a group.
- Members are journal rows only; the anchor and candidates are long-term records shown *against* the group
  and are never dispositioned, which is why the completeness test does not strand them. Commented in the
  schema so an implementer cannot get this backwards.
- `architecture.md` §"Row-level completion is what makes the never-lose guard structural" replaces the old
  one-verb-closes-the-group paragraph.

**5. [BLOCKER] Mutual-K connected components still chain — ACCEPT, and the rationale was wrong too.**
You are right on the mathematics: connected components over the accepted mutual edges *are* single linkage
over those edges, so A↔B↔C is one component with or without mutuality. The rationale claimed the defect was
prevented; testing the algorithm as written would have confirmed the defect, as you say.

Remedy: a **complete-linkage cohesion pass**, chosen over your clique-splitting and diameter suggestions
because it needs no new parameter and is deterministic without a tie-break policy.
- `consolidation.md` §Mechanism step 2 is now two stages. Stage 1 keeps connected components as a cheap
  prefilter. Stage 2 partitions each component: order members by `(created_at, uuid)`; seed a subgroup with
  the earliest unassigned member; add a candidate, in that order, only if it has a mutual edge to **every**
  member already in the subgroup; close and reseed from the earliest remaining member.
- On A↔B↔C this yields `{A,B}`, `{C}` — the acceptance test, and it is named as one.
- The cost is stated rather than buried: complete linkage **over-splits**. That is argued as the safe
  direction, not waved away — step 3 processes groups oldest-first with the store updating as it goes, so a
  later group can still merge into a record an earlier group just created. An over-split costs one extra
  consolidator call; an under-split manufactures a record false in two directions.
- `consolidation.md` §"Why mutual-K, and why mutual-K is not enough" replaces the old claim, keeping what
  mutual-K genuinely buys (one parameter, prunes weak asymmetric edges) and dropping what it does not.
- `overview.md` D29's rationale corrected in the same terms, and `FINDINGS.md`'s D29 index line now reads
  "mutual-K plus a cohesion pass".

**6. [MAJOR] D15's rationale claims duplication is stopped; the mechanism does not stop it — ACCEPT, option
(a), with the resolution path specified.**
Option (b) — atomically retiring the just-created row inside `remember` — was not available: D32 settles that
`remember` "writes unconditionally and *then* reports near-duplicates", and that is a user decision. So the
contract is now documented as detection-plus-offered-resolution, and the rationale no longer claims
prevention.
- `overview.md` D15 rationale rewritten: "detection and an offered resolution, not prevention", with the
  reason prevention is rejected (refusing a write risks losing the lesson — D32's never-lose argument).
- `architecture.md` `zikaron_remember`: the dedup search runs **after insertion, in the same transaction, and
  excludes the row just created** — both of the questions you asked are now answered in the signature.
- The resolution path is named in the tool description: `amend` the older row, then `retire` the new one with
  `superseded_by` = the older uuid. Two calls, no new verbs.
- The instrumented signal is renamed and re-specified to three outcomes — ignored /
  amended-but-duplicate-left-live / fully resolved — in `schema.md` §"D30's six signals, as queries",
  `write-policy.md` §3 and `overview.md` D30. Still six signals; the second one just now measures the thing
  that actually matters.
- `FINDINGS.md` D15 index line corrected from "every write searches first" to "`remember` writes, then hands
  back near-duplicates".

**7. [MAJOR] `session_id` is called server-captured but no contract conveys it — ACCEPT.**
- `architecture.md` new §"The request envelope — where `session_id` comes from": every request carries
  `client: {session_id, kind, pid, op_id}`. The hook takes it from the hook payload; `zikaron-mcp`, being one
  process per session, resolves it once at startup from the environment or else mints a per-process UUID and
  holds it — which may not equal kiro's own id but is still one stable label per session, which is all the
  per-session signals need. Which case produced it is logged.
- Trust model stated plainly: an **untrusted label, not authentication**. A 0600 UDS already restricts callers
  to the owning uid, and anything that could forge the label could call `remember` directly. Validation is
  shape-only (string, ≤128 chars, no control characters); missing or malformed ⇒ NULL, the call succeeds, that
  call drops out of per-session signals.
- Consolidation provenance defined: records the consolidator writes carry the **consolidator's**
  `session_id`; original authorship survives because D16 retains the absorbed rows with their own
  `session_id`, linked back by `superseded_by`. No field D27 rejected was reintroduced.
- `op_id` added to `event` (finding 12) so one call's events are correlatable.

**8. [MAJOR] `consolidation.md` still carries the rejected parser protocol — ACCEPT.**
- §"Never lose silently" is now §"Never lose silently — the guard, in Zikaron's terms". It keeps the
  *principle* ("never mark work done unless the work came back") and drops the *mechanism* (well-formed
  block, nudge ×3, present-but-empty block), explicitly noting that the mechanism contradicted
  `architecture.md`, D32 and `prior-art.md`.
- Rewritten around the row-level completion invariant from finding 4.
- The block/nudge behaviour is left where it is accurate — `prior-art.md`, which already described it as
  `~/Memory`'s protocol.
- Added the reason the replacement is *stronger*, not merely different: the old rule depended on the model
  emitting something parseable, hence the retry; here the store's state is the record, so the guard needs no
  cooperation.

**9. [MAJOR] Stale figures against the final approved benchmark — ACCEPT, and I found three more.**
Everything you listed is corrected, with the comparator and configuration named:
- Reranker **6069 → 6592 ms** p50 at 50 gist+content pairs (`retrieval.md` §Reranking). The recall-drop and
  over-length-collapse observation is retained **only with its cloned-tail caveat**, as the final report
  does, and the latency curve is stated as what actually carries D23.
- Degraded BM25 **0.859 vs 0.969 → 0.8802** (`L_A_unicode61`) against the **incumbent hybrid 0.9375**
  (`H_small_prefix`) and the **best tested 0.9479** (`H_nomic`), blind set, depth 50 — in both
  `architecture.md` §"Degraded modes" and `retrieval.md` §"Degraded retrieval".
- Warm **5.5 / 8.0 → 6.64 / 9.14 ms**, the prefixed path D20 adopts, in `architecture.md` §Components and
  `overview.md` D31, each naming 5.45 / 7.97 as the no-prefix measurement so the distinction is not lost
  again.

Three further stale figures, same class, not in your list:
- `retrieval.md` §Fusion claimed "paraphrase: BM25 0.400 vs dense 0.800". The blind-set figures are 0.667 for
  **both** arms alone and **0.800 for the hybrid**. Rewritten — and it is a better argument for keeping both
  arms than the stale one was, since neither arm reaches the fusion on paraphrase, error strings go
  0.967/0.967 → 1.000, and near-miss discrimination sits with the lexical arm at 0.988.
- `retrieval.md` §Embedding claimed gist-only makes paraphrase "collapse from 0.800 to 0.200". The report's
  figure is −0.13 to −0.27 (incumbent hybrid 0.800 → 0.600; dense-only bge-small 0.667 → 0.400). Corrected.
- D24 quoted the extractor's held-out precision as "0.54 (gate 0.80)", which is the *lenient* end of a range.
  The report says **0.36 strict / 0.54 lenient**. Corrected in `overview.md` D24.
Everything else I re-derived against `research/embedder-benchmark-results.md` and left alone: 83–100% /
28–50%, 0.75 → 0 under blanket suppression, DI 0.194–0.233, +0.0286 CI [−0.0162, +0.0617], −0.052 / +0.037 /
−0.016, 960/960, 21.7 of 77.3 (28%), 4-already-answered / 1-survived / 4-destroyed, 783 ms, 13× / 20× / 4.1×,
1908 ms, 184 ms, +0.026 CI [+0.0052, +0.0521], 0.26 ms.

### `design/overview.md` and `FINDINGS.md`

**10. [MINOR] D14 denies the evidence D20–D25 use — ACCEPT.**
- `overview.md` D14 is now "**End-to-end evaluation is stoved** until an initial implementation exists", with
  the narrowing explained: component measurement against a synthetic corpus is not merely allowed, it is how
  the retrieval stack was chosen; what waits for an implementation is "does having memory make the agent
  finish the task better". Open question 9 named as the tracker.
- `FINDINGS.md` D14 index line updated to match.
- Flagged for the user: this narrows the *wording* of a settled decision. It is the reading the user's own
  behaviour supports — they commissioned the retrieval benchmark after settling D14 — but it is a wording
  change to a D-row decision cell rather than to a rationale, so the parent should confirm it.

**11. [MINOR] Architecture claims to close open question 4 — ACCEPT.**
- Header now says it "settles the **shape** half of Open question 4".
- §"Open, and now narrower" enumerates what stays open — RPC round-trip latency, two-session contention and
  whether `busy_timeout` 5 s is right, the start-if-absent race under contention, where `userPromptSubmit`
  stdout lands and whether a size cap applies, and lease behaviour across a restart. `FINDINGS.md` question 4
  is left open, unchanged.

### `design/schema.md`

**12. [MAJOR] The event schema does not make three of the six signals reproducible — ACCEPT.**
- `schema.md` §"The `event` log, per kind" gives a **fixed `detail` shape and an explicit cardinality per
  kind**. `surface` is one row per surfaced memory (five per push, one shared `op_id`); `fetch` one per
  requested uuid; `dedup_offered` one row per offered near-duplicate, each carrying `created_uuid`.
- `op_id` added to `event` (and to the request envelope) as the correlation id, plus `idx_event_op`.
  Ordering: `event.id` within an `op_id`, and `id` is authoritative across calls because `at` can collide.
- Per-write `token_count` now lives on the `remember`/`amend` **events**, with `gist_tokens`, `n_chunks` and
  `truncated`. `memory.token_count`'s comment is corrected to "current size of THIS row" and the signal table
  states the two answer different questions.
- "Writes per session" **includes `amend`**, counted separately as well as summed, because "recorded nothing
  new" and "repaired nothing" are different failures.
- Invariant 10: events commit inside the transaction they describe.
- Two new kinds — `no_receipt` and `group_served` — and all six signals restated as queries against the
  fixed shapes. `write-policy.md` §3 and `overview.md` D30 updated to match.
- Retention split: `event` prunes by age, `read_receipt` must not.

**13. [MAJOR] Invalid supersession graphs, and no definition for twice-superseded — ACCEPT.**
- Table CHECKs added: `superseded_by <> uuid` (no self-edge) and `superseded_by IS NULL OR active = 0`.
- Invariant 6 covers what a CHECK cannot: target must exist and must not be retired-outright (it may be live
  or itself superseded, which is how `A→B→C` arises); **no cycles**, enforced by walking the target's chain
  before writing and rejecting if it reaches the writer; walk capped at `supersession_max_depth` (32) with
  the cap itself an error, so a corrupt store cannot hang a query; the edge is written once and is not
  re-pointable; any tier may supersede any tier.
- Invariant 7 defines `A→B→C`: `superseded_by` is the **immediate** edge, ranking demotes on that edge and
  does not chase the chain, and `fetch` additionally returns **`superseded_by_latest`** (resolved head, same
  depth cap) so an agent handed `A` learns about `C` in one call. Demotion is **not** scaled by chain depth,
  and the reason is given: nothing measured says depth predicts harm.
- `−32004 bad_supersession` covers self-edge, cycle, retired-outright target, already-set edge and depth-cap.
- Acceptance tests you asked for are named: `A→B→C` traversal, and two concurrent attempts to close a cycle.

**14. [MAJOR] Atomicity specified only for amend — ACCEPT.**
- `schema.md` invariant 2 rewritten to "**every logical mutation is exactly one SQLite transaction**",
  enumerating `remember`, `amend`, `retire`, `merge`, both forms of `promote`, `discard`, and covering the
  memory rows, version bump, explicit FTS5 maintenance, chunk/vector maintenance, receipts and events.
- **Deletion order is vectors before chunks**, with the reason: `memory_vec` has no foreign key, and an
  orphaned chunk row is detectable and repairable while an orphaned vector is a silent false positive.
- Invariant 3 defines full reindex as build-and-swap **or** marked-unavailable, and states that an
  `embed_dim` change *requires* the unavailable form because `vec0` cannot be altered in place. New
  `−32022 reindexing` error and a `reindexing` key in `meta`.
- `indexing.md` §"Implementation constraints" rewritten to match, including that `promote`'s in-place form
  still bumps `version` in the same transaction, and that a payload with different prose is not an in-place
  flip at all.

### `design/architecture.md`

**15. [BLOCKER] `group_id` has no ownership, lease, persistence or stale-plan semantics — ACCEPT.**
You offered serialization *or* persisted claims; I did **both**, because the persisted tables were needed for
finding 4 anyway and serialization alone would not survive a restart.
- `schema.md` adds `consolidation_run(run_id, session_id, pid, started_at, expires_at, status)` and
  `consolidation_group(group_id, run_id, anchor_uuid, order_key, shard_index, status, served_at)`.
- `architecture.md` §"Consolidation lifecycle": `plan_groups()` creates the run with a lease (`run_lease`,
  default 30 min) and the full membership snapshot; **one active run per store** (invariant 15), and a second
  session gets the deterministic `{busy: true, holder_session, expires_at}` rather than an error or a second
  plan; the lease is refreshed by every successful call; an expired run is marked and replanned.
- Restart recovery needs no special case because nothing lives in memory — the persisted run keeps serving
  its groups to the session that owns it. Idle self-stop is explicitly *not* blocked by an active run, since
  a run is store-level state.
- Stale/expired/foreign/unknown ids get distinct errors: `−32010 group_unknown`, `−32011 group_expired`,
  `−32012 group_complete`.
- `remaining_uuids` is computed at response time from the member table; `remaining_groups` is in the
  `next_group` payload.
- Membership frozen at plan time, **candidates recomputed at serve time** — which also resolves finding 24's
  "updating the store as we go" ambiguity.

**16. [MAJOR] Non-success outcomes omitted — ACCEPT.**
- `architecture.md` new §Errors: 14 codes in the application range −32099…−32000, each with its `data`
  payload, plus the blanket rule that **every error mutates nothing** and all batches and mutations are
  all-or-nothing.
- Specifically covered: missing uuid in `fetch` (returned in `missing`, not a batch failure — a partial answer
  is more useful and the agent needs to know which handle is dead); fetch **preserves input order** and
  collapses duplicates; `amend`/`retire` of an inactive row (`−32003`); invalid/self/cyclic supersession
  (`−32004`); target not in the delivered group (`−32013`); stale group ids (`−32010/11/12`); partial and
  empty absorb lists; `SQLITE_BUSY` after 5 s (`−32020`, retry-once); embedding/index failure (`−32021`).
- Bounds table in `schema.md` §Bounds: `gist` ≤ 64 tokens, `content` non-empty and unbounded, `limit` 1–50,
  `fetch` 1–50 uuids, `absorb` ≥1 and ≤ member count, ≤64 FTS terms.
- Empty-store behaviour stated exactly as you asked: `search` → `[]`, `surface` → prints nothing at all,
  `next_group` → `{done: true}`, plus `fetch` → `{records: [], missing: [...]}` and `plan_groups` → a
  zero-group run.

**17. [MAJOR] The store is not secured to the socket's standard — ACCEPT.**
- `architecture.md` new §"Filesystem security" with a mode table: `.zikaron/` 0700; `memory.db`, `-wal`,
  `-shm`, `service.log` 0600 created under an explicit `umask(0o077)` **because SQLite creates the WAL/SHM
  itself** and would otherwise inherit the ambient umask; runtime dirs 0700; socket 0600.
- The `/tmp/zikaron-<uid>` fallback is **validated before use** — real directory, not a symlink, owned by the
  running uid, mode 0700 — and refused otherwise rather than repaired. A socket may only be unlinked after
  the same checks. `.zikaron` reached through a symlink is refused via `realpath`.
- Stated plainly, as you asked: **0600 UDS and 0600 DB keep other local users out and authenticate nothing
  against the same uid.** Every process running as the owner can read the store and call the API; that is the
  same trust boundary as the user's own files, it is deliberate, and it is why TCP was rejected. If that ever
  needs to change, it needs real authentication and nothing here provides it.
- `overview.md` D31's rationale now carries the consequence, so the TCP-rejection argument and the store's
  permissions are stated in the same place.
- `schema.md` §"File permissions" points at it, so a schema-only reader is not left thinking a file mode is
  someone else's problem.

**18. [MINOR] Truncated socket hash has no collision defence — ACCEPT.**
- `<h>` is now specified: **first 32 hex characters (128 bits) of the sha256 of the `realpath`-resolved store
  path**, with the reason for truncating at all (the ~108-byte `sun_path` limit).
- `meta.store_id` added — a UUID minted at store creation. `health()` returns
  `{ready, store_path, store_id, embed_model, embed_dim, schema_version, pid}`.
- New §"Store identity is verified, not assumed": a client verifies `store_path` and `store_id` **before it
  sends any read or write**; a mismatch is `−32030 store_identity`, is not retried, and for the hook falls to
  the degraded path rather than reading another project's knowledge. Step 6 of start-if-absent.

### `design/retrieval.md`

**19. [MAJOR] Dense memory ranking is not implementable from "max over chunk scores" — ACCEPT.**
- `retrieval.md` §"One eligibility predicate, one ranking algorithm" states the metric: `vec0` KNN returns a
  **distance**, lower is better; the corpus is L2-normalized at write time so the ordering is monotone in
  cosine either way; "best chunk" is **`min(distance)`**.
- D28's "`max` over chunks" is reconciled explicitly in both `indexing.md` §Ranking and `overview.md` D28 —
  same operation, opposite sign — because reading "max" literally against a distance column inverts the
  ranking, which is precisely the trap you identified.
- The overfetch loop is specified: `n = limit × chunk_overfetch` (default 8) → KNN → join → apply eligibility
  **after** the join (since `vec0` cannot filter on our columns) → roll up by min distance → stop at `limit`
  distinct eligible memories, else **double `n`**, up to 4 doublings or index exhaustion. A short result is a
  legitimate answer. The lexical arm gets the mirror rule.
- Stated as the single primitive shared by push, pull, dedup, anchors and orphan edges.

**20. [MAJOR] RRF has no total tie order — ACCEPT.**
- `retrieval.md` §"Total order — ties are pervasive and must not fall to insertion order" quotes the narrowed
  round-3 figures (every hybrid query has ≥1 tie; ~17.5 tied adjacent pairs; **12.5%** of queries have a tie
  inside the top 5, boolean per-query) and notes the report's own conclusion that insertion order is an
  undeclared thumb on the scale — while keeping the report's separate finding that ties are **not** the
  mechanism that erased bge-large's gain.
- The order, applied after the supersession penalty: fused score desc → `min(lexical_rank, dense_rank)` asc →
  tier (`long_term` before `journal`, which is also the tiebreak `~/Memory` reached independently) →
  `created_at` desc (D27's named journal-local recency reader, and the only place recency enters ranking) →
  `uuid` asc for totality.
- Explicitly the same order for the cutoff, the injected block, `search` output, dedup candidates and
  consolidation adjacency — including the mutual-top-K boundary, which would otherwise be nondeterministic.

**21. [MINOR] Raw prompts need an FTS5 query-construction rule — ACCEPT.**
- `retrieval.md` §"Query construction — a prompt is not an FTS5 expression": tokenize with the same
  `unicode61` rules the index uses; quote every term as an FTS5 string literal (doubling internal `"`), which
  is what neutralizes `OR`, `-` and parentheses; join with ` OR `; **bind the expression as a parameter**;
  cap at 64 terms, longest-first.
- **No advanced FTS syntax is ever exposed**, on either path — the reasoning is that a query language would
  make `search` a source of syntax errors rather than of memories.
- **Zero usable terms ⇒ skip the lexical arm and run dense-only**, recorded in the `search` event, so a
  punctuation-only or untokenizable prompt still gets an answer.
- The degraded BM25-only path is stated to use the same rule, so the fallback cannot fail where the full path
  succeeds.
- The "verbatim" claim in §"Two paths" is corrected to "unedited for the dense arm, tokenized for the lexical
  one".

### `design/indexing.md`

**22. [MAJOR] The 450-token contract can still silently truncate — ACCEPT.**
- `indexing.md` §"Chunk construction" is now a **preflight against the final embedded sequence**:
  `content_budget = 512 − n_special − gist_tokens − separator_tokens`, then
  `effective_budget = min(chunk_max_tokens, content_budget)`. With a 64-token gist ceiling the floor is 445,
  so 450 is usually the binding constraint and the gist ceiling is what keeps it so.
- **The tokenizer is named**: the deployed `bge-small-en-v1.5` WordPiece tokenizer from the same artifact
  fastembed uses, including special tokens and `model_max_length` 512 — with the reason that an approximate
  count is worthless when the failure is silent.
- Over-budget **gist rejects** (`−32005 bounds`, `gist_max_tokens` default 64). I chose rejection over
  separate truncation, and the never-lose tension is addressed rather than ignored: the agent still holds its
  own text and can shorten a gist in the same turn, whereas a silently truncated embedding is undiscoverable.
  **Content is never refused for length** — that asymmetry is deliberate and stated (D4 stores content
  untruncated; D13 wants short gists).
- Hard splits are **on token boundaries**, and the assembled sequence is asserted ≤512 with a failed
  assertion raising `index_failed` and rolling back rather than truncating.
- **Empty content is invalid** at the tool boundary; if it were ever admitted the defined behaviour is one
  gist-only chunk, and `schema.md` invariant 12 requires every active memory to have ≥1 chunk. Non-empty
  CHECKs added on both `gist` and `content`.
- **`truncated` is set by the preflight and only by it** — never inferred from fastembed, which reports
  nothing. Recorded in the storage table too.
- `overview.md` D28's rationale notes the correction.

### `design/consolidation.md`

**23. [MAJOR] `next_group.candidates` does not match the mechanism — ACCEPT.**
- `consolidation.md` §"What `candidates` actually is": the payload carries **`anchor`** separately (the
  long-term record the group was built around, `null` for orphans, and the natural merge target) plus
  **up to 4 `candidates`** — which is where the promised "5 candidate memories" comes from.
- Candidate construction is **one group-level query**: fused retrieval whose query text is the concatenation
  of member gists in group order, excluding the anchor and every member, in the total order from finding 20,
  deduplicated by uuid. The union-of-per-member-top-5 reading is explicitly rejected — no cap, no defined
  order, grows with group size.
- Each candidate carries its `rank`, so a run is reproducible from the payload alone.
- **Empty `candidates` is normal, not an error**: early on the long-term tier is empty, every group is an
  orphan group with `anchor: null`, and the only available verbs are `promote` and `discard`.
- The "5 candidate memories" phrasing in §"Consolidator identity and model" is rewritten to match.

**24. [MAJOR] Oversized-group splitting and oldest-first ordering are not deterministic — ACCEPT.**
- **Partition rule**, not just a cap: a cohesive subgroup over `group_max` (default 12) splits into
  **consecutive shards** of ≤ `group_max` in `(created_at, uuid)` order, so the same subgroup always shards
  the same way. Each shard is its own group with `shard: {index, of}`.
- **The anchor is repeated into every shard**, with a flag, because a shard without its anchor cannot make a
  merge decision.
- **Total group order**: `(earliest member created_at, minimum member uuid, shard_index)` — the uuid
  tiebreak named as load-bearing precisely because concurrent writes really do share a timestamp.
- The replan-versus-snapshot ambiguity is resolved: **membership is frozen at plan time; candidates are
  recomputed at serve time.** That is the whole of what "updating the store as we go" means, and both halves
  are now stated. Planning is declared a pure function of the store plus its parameters.

**25. [MINOR] The imported "survivor rule: keep longest" has no operation — ACCEPT (relabel).**
- `consolidation.md` marks it explicitly as *their* lesson and **not a Zikaron requirement**, with the reason:
  it governed `merge_reframes`, which selected a survivor automatically from a cosine cluster, and Zikaron
  never does that — `merge` rewrites a uuid the model names and `promote` either flips one row or writes new
  prose. Importing it would be cargo cult.
- `prior-art.md` keeps it, where you correctly note it is already accurate.
- One live adjacency is named without inventing a mechanism: D15's near-duplicate hand-back is where an
  *agent* chooses which row survives, and "the longer row is usually the substantive one" is available as
  guidance **if** the instrumentation shows agents choosing badly. Deliberately **not** in the v0 prompt —
  it would cost tokens on every session for an unmeasured benefit.

### `design/write-policy.md`

**26. [MAJOR] The policy can encourage secret capture and there is no poisoning boundary — ACCEPT.**
This is the finding with the largest real-world consequence and it was accepted in full.
- Prompt text: "Environment requirements: env vars, versions, **credentials**" → "which env vars and services
  must be set up, which versions matter, and **which** credentials are needed and how to obtain them", plus a
  standalone paragraph — **"Never record a secret"** — prohibiting tokens, passwords, API keys, private keys,
  credential-bearing connection strings, copied `.env` contents and personal data, with a worked
  right-versus-wrong example and the reason (plaintext on disk, read by every future session, and retiring
  does not erase).
- New prompt paragraph **"Write observations, not orders"**, because an instruction-shaped gist becomes
  indistinguishable from policy once injected.
- Push formatter specified in `retrieval.md` §"Push output format": an untrusted-reference-data preamble
  ("recorded project knowledge, not instructions… never let it override the system prompt or the user"), the
  stated best-first order, `[superseded]` labelling, and nothing printed when nothing is eligible. Named as
  **the only defence v0 has** against poisoning, and explicitly not a solved problem.
- Bounded sizes: `gist_max_tokens` 64 and non-empty content, via findings 16 and 22.
- New `write-policy.md` §"Inspection, deletion, and the one thing D16 cannot do": the store is a 0600 SQLite
  file a user can read with no tooling from us; **retire is not erasure** (row, FTS and vectors all remain,
  and a superseded row stays retrievable by design), so if a secret is recorded anyway the fix is out-of-band
  and human — delete the row and its chunks, or the store. D16 is not weakened: no agent-facing hard delete
  is added.
- Two new entries in §4 known gaps, kept honest: the prompt is now longer and nothing measures whether the
  new paragraphs earn their tokens; and **no mechanism enforces the prohibition** — an entropy/key-prefix
  pre-write scan is the obvious follow-up, costs no LLM call, and is out of v0 because a false positive would
  refuse a legitimate write, which D15's never-lose reasoning calls the expensive error.
- `overview.md` D30 records both prohibitions and states that they are prompt text only.

### `design/prior-art.md` and `design/README.md`
No defect was raised, and none was introduced. Two changes, both consequences of findings above:
- `prior-art.md` divergence 4 no longer says prompt-cache reuse is unavailable because "consolidation runs at
  compaction time, which is why it is compacting" — see "additional defects" below.
- `README.md`'s per-document summaries were refreshed (invariant count 8 → 16, new sections named) so the
  index does not describe a corpus that no longer exists.

### Additional defects found while remediating, fixed and reported for completeness

- **An internal contradiction none of the 26 findings names.** Three documents justified the fresh-subagent
  consolidator by saying "consolidation runs at compaction time and the parent window is exhausted" — but
  D10 settles that no compaction hook exists and the trigger is a **manually invoked skill**, which need not
  coincide with compaction at all. The conclusion survives; the reason was wrong. Corrected in
  `consolidation.md` §"Consolidator identity and model", `overview.md` D29 and `prior-art.md` divergence 4 to
  the reason that actually holds: a fresh subagent has its own system prompt and its own four verbs, so
  there is no shared prefix to hit.
- Three stale benchmark figures beyond your list, under finding 9.
- `schema.md`'s header said "Reconciles D1–D30"; it is D1–D32.

### `FINDINGS.md`
Edited only where it had drifted from `design/`, per the standing constraint — no restructuring, no rationale
moved back into it:
- D14, D15, D26 and D29 index lines corrected.
- Current-state line: now records that the corpus has been reviewed, that all 26 findings were accepted, and
  what the five blockers actually were.
- Open question 5 **narrowed** rather than closed: the display half is specified (label plus adjacency); what
  stays open is editorial, since D27 keeps no reason-for-supersession field and nothing measures whether the
  agent needs the reason.
- Documents table: schema's invariant count and architecture's new sections.
Open questions 1, 2, 3, 6, 7, 8 and 9 are untouched and remain open.

### For the user, not for me
1. **Finding 10 narrows the wording of a D-row decision cell**, not merely a rationale: "Benchmarking is
   stoved" → "End-to-end evaluation is stoved". It matches what the user actually did next, but it is theirs
   to confirm.
2. **Two new defaults were chosen autonomously and want a sanity check**, because both are guesses dressed as
   numbers: `supersession_penalty = 0.5` and `gist_max_tokens = 64`. Both are `meta` values, so both are
   measurable later rather than baked in — but 64 tokens is the one bound in the system that can **reject an
   agent's write**, and that is a product decision as much as a technical one.
3. **`read_receipt` adds server-side state that D26 did not originally imply.** It is what makes the
   user-settled read-before-write guarantee true rather than nominal, and the alternative was to withdraw the
   guarantee — but it is a new table and a new failure mode (`no_read_receipt`), so the user should know it
   exists.

Knowledge base re-indexed (`zikaron-design`, path `/home/nathan/Zikaron/design`) after the edits.


## Round 2 — 2026-08-01

### Summary judgment

The remediation is substantial and resolves most of round 1, including all five original blocker mechanisms: eligibility, mechanical read receipts, affected-row version checks, row-level group completion, and the orphan cohesion pass. The corpus is nevertheless not yet buildable without guessing: the fixes introduced an impossible supersession ordering, an underspecified persisted consolidation state machine, a retrieval-depth mismatch with the benchmarked pipeline, and instrumentation contracts that cannot represent the events they require. Several evidence claims were also widened beyond the benchmark again.

### Round-1 finding disposition

| # | Status | Judgment |
|---|---|---|
| 1 | **Resolved** | The shared default predicate now includes live and superseded rows and excludes only outright-retired rows. |
| 2 | **Partially resolved** | `read_receipt` makes read-before-write mechanical for a valid stable session, but the corpus still contradicts itself about where versions/receipts come from and permits a NULL session that cannot mint the declared receipt. See finding 6 below. |
| 3 | **Resolved** | Every consolidator mutation now supplies and validates `{uuid, expected_version}` for every row it mutates, before mutation. |
| 4 | **Resolved** | Completion is row-level, mixed dispositions may take multiple calls, and empty/out-of-group/already-dispositioned subsets cannot close a group. |
| 5 | **Resolved** | The deterministic greedy complete-linkage cohesion pass prevents the stated A↔B↔C chain. |
| 6 | **Resolved** | D15 is now accurately advisory detection after an unconditional `remember`, with the full two-call resolution path stated. |
| 7 | **Partially resolved** | The request envelope now conveys a session label, but `overview.md` still calls `session_id` server-captured while `architecture.md` correctly calls it a client-supplied untrusted label; NULL-label behavior also conflicts with receipt minting. |
| 8 | **Resolved** | The rejected free-text parser/nudge protocol has been removed from Zikaron's mechanism and retained only as prior art. |
| 9 | **Resolved** | The stale benchmark figures identified in round 1, plus the additional figures found during remediation, now match the report and are scoped correctly at their primary citation sites. |
| 10 | **Resolved** | D14 now defers end-to-end task-benefit evaluation, not all pre-implementation component measurement. This is the coherent reading of the settled corpus; no further objection remains. |
| 11 | **Resolved** | Architecture now says it settles only the shape half of open question 4 and leaves integration measurements open. |
| 12 | **Partially resolved** | Per-kind shapes and `op_id` fix the original untyped log, but zero-write sessions and consolidator success/conflict rates are still not reproducible. See finding 5. |
| 13 | **Partially resolved** | Self-edges, cycles, target state, depth, and A→B→C traversal are specified, but the graph is incorrectly called a forest of chains even though normal merges create multiple incoming edges; the resulting ordering rule is impossible. See finding 1. |
| 14 | **Resolved** | Every logical mutation and its indexes, receipts, and events are assigned one transaction; reindex unavailability and vector-before-chunk deletion are specified. |
| 15 | **Partially resolved** | Runs/groups are persisted and leased, but plan-to-serve races, re-serving incomplete groups, candidate authorization, and terminal run transitions are not specified. See finding 2. |
| 16 | **Partially resolved** | The error table covers the requested cases, but its “every error mutates nothing” rule contradicts conflict/no-receipt events and conflict receipt minting. See findings 5–6. |
| 17 | **Resolved** | Store, runtime, socket, WAL/SHM, and log permissions and same-UID limitations are explicit. |
| 18 | **Resolved** | The 128-bit path hash and pre-request `store_path`/`store_id` handshake provide collision defense. |
| 19 | **Partially resolved** | Distance direction, memory rollup, eligibility, and adaptive chunk overfetch are specified, but `limit` is now also used as arm depth, silently changing the benchmarked depth-50 RRF pipeline. See finding 3. |
| 20 | **Resolved** | A deterministic semantic total order now replaces insertion-order ties across all named consumers. |
| 21 | **Partially resolved** | Literal quoting, binding, term caps, and dense-only fallback are specified, but “tokenize ourselves with the same `unicode61` rules” does not identify an implementable tokenizer path, and dense query length is unbounded. See finding 7. |
| 22 | **Resolved** | The final assembled embedding sequence is token-budgeted with the deployed tokenizer, and over-budget gists reject rather than truncate silently. |
| 23 | **Resolved** | Anchor and ≤4 group-query candidates now have a single deterministic definition, order, cap, and empty case. |
| 24 | **Resolved** | Cohesive groups shard consecutively under a total order; membership is frozen and candidates are recomputed at serve time. |
| 25 | **Resolved** | “Keep longest” is correctly retained as prior art rather than imposed on a Zikaron operation that has no automatic survivor. |
| 26 | **Resolved** | Secret/instruction prohibitions, the untrusted-reference frame, bounds, and the retire-is-not-erasure warning are present and internally aligned. |

### Findings blocking approval

1. **[BLOCKER] The supersession graph and the mandatory “immediately above” order are mathematically inconsistent with normal merges.** `design/schema.md`, invariant 6, calls the graph “a forest of chains,” but the schema constrains only one *outgoing* edge and allows arbitrary incoming edges; `zikaron_merge` intentionally creates `A→C` and `B→C` when it absorbs multiple rows. `design/retrieval.md`, “Supersession: eligible, demoted, and labelled,” then requires C to be immediately above both A and B, which no linear order can satisfy. The same section defines a penalty only for superseded rows although `schema.md` says explicitly requested outright-retired rows are also demoted. Finally, consolidation uses the shared eligibility predicate for long-term anchors/candidates, so an inactive superseded row can be offered as a legal merge target even though merges should not rewrite historical rows. Resolve by describing the actual rooted converging forest (out-degree ≤1, arbitrary in-degree), replacing impossible immediate adjacency with a deterministic realizable rule (for example, every retrieved replacement precedes all retrieved predecessors, with a specified stable grouping algorithm), defining the outright-retired penalty, and restricting merge targets to active long-term rows even if historical rows remain visible as non-targetable context.

2. **[BLOCKER] The persisted consolidation state cannot deterministically bridge planning, serving, mutation, and restart.** `design/schema.md`, `consolidation_group_member.version_seen`, is explicitly the version at plan time and “the expected_version the payload carries,” while `architecture.md` says `next_group` later delivers full content and mints a receipt for that version. If a primary agent amends a member between plan and serve, historical prose is unavailable, so the service must either deliver current prose with a stale version or violate the stored snapshot. Candidates are recomputed at serve time but are not persisted anywhere as the set a later `merge` is authorized to target; `group_served` is described as instrumentation, not authoritative state. The lifecycle also does not say whether `next_group` re-serves the earliest `served` but incomplete group or advances to a pending group, nor exactly when the final group atomically marks the run complete. Specify one transactional state machine: what happens to changed/inactive members and anchors before serving; whether `version_seen` is refreshed or the group expires/replans; where the exact served candidate/version authorization set is persisted; that incomplete served groups are re-delivered (or how they are otherwise resumed); and the group/run terminal transitions.

3. **[BLOCKER] The executable RRF pipeline no longer matches the depth-50 pipeline whose evidence and known-defect analysis it cites.** `design/retrieval.md`, “The dense arm, precisely,” starts at `n = limit × chunk_overfetch` and stops once it has `limit` distinct memories; the lexical mirror does the same. For `surface(limit=5)`, each arm therefore contributes five memories, not the benchmark's depth-50 arms. Yet the document's quality figures, the 21.7-of-77.3 union, and the 960/960 arm-agreement result all come from fusion depth 50, and the same document says fusion depth remains a future tuning variable without defining a current one. Separate output `limit` from per-arm `fusion_depth`, give the v0 depth (50 if the approved benchmark configuration is intended), run overfetch until that many distinct eligible memories or exhaustion, then fuse and cut to `limit`. Update `meta`, event details, and all consumers to use the same distinction.

4. **[BLOCKER] Required decision thresholds still have no values or initialization contract.** `design/consolidation.md`, “Parameters needing calibration,” leaves mutual `K` and `anchor_cutoff` as guesses without defaults, while `design/schema.md` merely lists `mutual_k`, `anchor_cutoff`, and `dedup_threshold` as untyped `meta` keys. Without them, orphan grouping, journal anchoring, and D15's definition of which near-duplicates are returned cannot run; implementations will also differ on score scale and inclusive/exclusive cutoff semantics. Calibration may remain open, but buildability may not: provide seeded v0 values, types/ranges, the exact score being thresholded, boundary semantics, and a complete required-`meta` initialization/validation table. Labeling the defaults provisional is sufficient; measuring optimal values is not required for approval.

5. **[BLOCKER] The event schema cannot represent the consolidation behavior and six signals the corpus promises.** `design/schema.md`, `event.kind`, has no `merge`, `promote`, or `discard` success kind, although invariant 2 requires every such mutation to include its events, `consolidation.md` says `discard.reason` is stored in the event log, and the D30 table defines a version-conflict *rate* whose denominator includes consolidator writes. Separately, `surface` emits one row per returned memory, so a session with an empty store or zero eligible results emits no event and cannot appear in the promised zero-write-session signal. The error table's blanket “every error … mutates nothing” also conflicts with required `version_conflict`/`no_receipt` events and with a conflict minting a receipt. Add fixed success-event shapes/cardinality for all consolidation verbs (including discard reason and affected rows), a per-session/session-start or per-surface-call event that exists even at zero results, and exact numerator/denominator queries. Clarify that rejected calls make no domain mutation but may atomically commit specified audit events and conflict receipts.

6. **[BLOCKER] D26's receipt contract still contradicts the request and tool contracts.** `overview.md` D32 and `architecture.md`, “Why search returns no version,” call `fetch` the primary agent's only source of a version/receipt, but `remember` and `amend` return versions and mint `own_write` receipts, while conflicts return the current version and mint a `conflict` receipt. `overview.md` D27 calls `session_id` server-captured, while `architecture.md` correctly defines it as a client-supplied untrusted label. More importantly, architecture permits missing/malformed `session_id` to become NULL and says the call succeeds, but `read_receipt.session_id` is `NOT NULL`, so such a `fetch` cannot fulfill its unconditional promise to mint a receipt. Specify the precise claim (“fetch is the only way to license a pre-existing row absent an own-write/conflict response”), call provenance transport-supplied rather than authenticated/server-derived, and define NULL-label behavior—preferably require a non-NULL stable service-minted session for receipt-bearing clients. Also state validation precedence: a stale expected version must produce `version_conflict` and its current-record receipt before receipt validation, otherwise deleting old receipts on every version bump turns the promised one-round-trip conflict into `no_read_receipt`.

7. **[BLOCKER] Query construction remains incomplete at the model boundary and can silently truncate the very queries used for retrieval and consolidation.** `design/retrieval.md` sends the user's whole prompt unedited to the dense arm, and `design/consolidation.md`, “What candidates actually is,” embeds the concatenation of up to 12 member gists; either can exceed BGE's 512-token input. The write-side spec treats silent truncation as unacceptable, but no query-side token budget, truncation/selection rule, or canary exists. On the lexical side, “tokenize the query ourselves with the same `unicode61` rules” names desired behavior but not an implementation available through stdlib `sqlite3`; independent Unicode tokenizers will diverge from FTS5 on punctuation, diacritics, and offsets. Define a deterministic dense-query preflight using the deployed tokenizer (including how prefix and over-length group/user text are selected or truncated and logged), and name the exact implementable FTS5-tokenization mechanism used by both service and degraded hook—for example a specified temporary FTS5/`fts5vocab(instance)` procedure—rather than requiring an unspecified reimplementation.

8. **[BLOCKER] Three remediated evidence statements have widened beyond what the approved benchmark establishes.** `design/retrieval.md`, “The identifier weakness is real and unremedied,” concludes that mitigations “are lexical or joint-attention rather than a bigger bi-encoder,” but the report's settled language is **no demonstrated remedy from the tested deployed artifacts; capacity itself remains untested**. `design/consolidation.md`, “Consolidator identity and model,” says D25 measured that “long-term records land in the injected five 83–100%,” whereas the measurement is specifically superseded records under 6 current-action polarity stubs, not long-term records generally. `overview.md` D25 and `retrieval.md` call the historical sample “four … queries,” while the report says 4 stubs / 12 prompts. Narrow these statements to the report's exact population and conclusion; no new measurement is needed.

VERDICT: NEEDS_CHANGES

---

## Response to review round 2

**8 findings, 8 accepted, 0 rejected.** Every one named a real defect, and seven of the eight were defects
the *round-1 remediation itself introduced* — which is the useful thing this round establishes: fixing a
contradiction by adding mechanism creates new surface, and that surface had never been cross-read. The
supersession ordering rule is the sharpest example: it was written to repair a measured displacement and it
was mathematically unsatisfiable the moment a merge absorbed two rows.

**No user decision (D1–D32) was reversed.** Six *rationales* were corrected — D5, D25, D26, D27, D29, D32 —
each because it asserted more than its own mechanism or its own evidence supported. Two decision **cells**
were reworded rather than only their rationale (D27, D32); both are flagged under §"For the user" below.

One thing this round produced that was not asked for: finding 4 wanted seeded values, and rather than
inventing them I measured the cosine distribution of related, unrelated and near-miss-twin memory pairs over
the approved benchmark corpus. The seeds are now grounded — and the measurement **changed a design
statement**, because it shows a high cosine dedup floor finds twins rather than duplicates.

### 1. [BLOCKER] The supersession graph and the "immediately above" order are inconsistent — ACCEPT, all four parts.

You are right on the mathematics and right that this is my own round-1 fix breaking. `merge` writes `A→C` and
`B→C` by design, so "C immediately above both A and B" has no linear realization. Four separate corrections:

- **The graph is described correctly now.** `schema.md` invariant 6: a **rooted converging forest** —
  out-degree ≤ 1, **in-degree unbounded**, acyclic; each component an in-tree whose root is the row with
  `superseded_by IS NULL`; a chain is only the special case where every in-degree happens to be 1. It says
  explicitly that convergence is deliberate and that `merge` creates it. Invariant 7's "chain head" became
  "component root", with the note that the walk is unambiguous *because* out-degree is ≤1 — which is what
  makes `superseded_by_latest` well defined despite unbounded in-degree.
- **The ordering rule is now realizable.** `retrieval.md` §"Supersession", mechanism 2, replaces adjacency
  with **precedence**, enforced by a stable topological pass over the fused pool:

  > Let `L` be the fused candidate pool in the total order, after penalties. Emit rows one at a time: scan
  > `L` in order and emit the first not-yet-emitted row whose `superseded_by` target is either absent from
  > `L` or already emitted. Repeat until `L` is exhausted. **Then** cut to `limit`.

  Termination is argued from the structure rather than asserted: each row waits on at most one other row
  (out-degree ≤1) and the graph is acyclic (invariant 6), so the wait-for relation is a forest. It handles
  `A→B→C` transitively. It runs **before** the cut, so a replacement ranked below the budget can be promoted
  into it — which is the case the 28–50% displacement measurement is actually about. I took your suggested
  form. Adjacency is dropped and stated as not needed: mechanism 3 hands the agent the replacement's uuid,
  which is a stronger cue than proximity and survives several rows sharing one replacement.
- **The outright-retired penalty is defined.** New `retired_penalty` `meta` key, default 0.5, applied to
  `active=0 AND superseded_by IS NULL` rows when `include_retired` admits them. `schema.md` §eligibility says
  the two keys start equal because *nothing measured distinguishes them*, that they are separate keys only so
  a measurement can separate them, and that the states are mutually exclusive so penalties never compound.
  `retrieval.md`'s total order now reads "after the demotion penalties", plural.
- **Merge targets are restricted to active long-term rows.** Anchor and candidate selection adds
  `tier='long_term' AND active=1` on top of the shared predicate. I was careful about *how* to say this,
  because an undeclared divergence between read paths was round-1 finding 1: it is therefore documented in
  **both** places (`schema.md` §eligibility and `consolidation.md` step 1) as the corpus's **one** narrowing,
  with the reason — every long-term row shown to the consolidator is a row `merge` may rewrite, and
  `superseded_by` is immutable once set, so a retired row given fresh prose is neither current nor
  historical. New `−32014 bad_merge_target`. Your phrasing is adopted: historical rows stay visible as
  context and are not targetable. Also noted that little is lost, since a superseded row's replacement is
  itself active long-term and normally ranks in its place.

### 2. [BLOCKER] Persisted consolidation state cannot bridge plan, serve, mutation and restart — ACCEPT, all four sub-parts.

`architecture.md` §"Consolidation lifecycle" is rewritten as one transactional state machine, and the
transitions are additionally pinned as `schema.md` invariant 17 so they are not prose-only.

- **Plan-time versus serve-time versions.** `version_seen` is now explicitly plan-time and **change detection
  only**; a new `version_served` column carries the version whose prose the payload actually contains, and
  that is what the receipt is minted at. Serving re-reads a member whose version moved and delivers the
  *current* prose at the *current* version. Your dilemma is resolved by refusing both horns: we never deliver
  current prose under a stale version, and we never pretend to have historical prose we do not store. A
  primary agent's repair therefore reaches the consolidator, which is what D11 wants anyway.
- **Members and anchors that changed state.** A member no longer `tier='journal' AND active=1` is marked
  `disposition='vacated'` (new CHECK value) and not delivered — it blocks no completion and nothing is lost.
  An anchor no longer `tier='long_term' AND active=1` is dropped: served as `anchor: null` with
  `anchor_vacated: true`, and its replacement normally appears in the recomputed candidates. Expiring or
  replanning the group instead is **rejected explicitly**, with the reason: it would unfreeze membership
  mid-run and destroy the reproducibility that makes planning a pure function.
- **The authorization set is persisted.** New table `consolidation_group_candidate(group_id, memory_uuid,
  role, version_served, rank)`, written in the same transaction as the serve and rewritten on a re-serve.
  `merge` checks its target against that table. `group_served` is explicitly demoted to instrumentation in
  both documents, exactly as you asked.
- **Re-serve, bounded.** `next_group` re-serves the earliest `served`-but-incomplete group before advancing —
  so a consolidator cannot walk past a hard group by calling again. Since unbounded re-serving is a livelock,
  a group at `max_group_serves` (new `meta` key, default 3) becomes `deferred` and is skipped for the rest of
  the run; its members stay undispositioned so the next run plans them. New `serve_count` column,
  `'deferred'` status, `−32015 group_deferred`. This is the one place `~/Memory`'s nudge-×3 genuinely
  transfers, and the document says so — as a bound on retries of a *group*, not of a parser.
- **Terminal transitions, named with single producers.** Group `complete` is set in the same transaction as
  the write verb that dispositions its last member. The run goes `active → complete` in whichever transaction
  first observes no group `pending` or `served` — normally that last write verb, otherwise the `next_group`
  that finds nothing servable. `expired` is set by the next `plan_groups` or by any call finding its own lease
  passed. `abandoned` finally has a producer: the **owning** session calling `plan_groups` again. All are
  guarded updates, so they are idempotent under retry.
- One consequence I found while writing this and closed: a re-serve delivers the same rows at the same
  versions, so plain receipt insertion would violate `read_receipt`'s primary key. Invariant 9 now requires
  minting to be an **idempotent upsert**.

### 3. [BLOCKER] The executable RRF pipeline no longer matches the benchmarked depth-50 pipeline — ACCEPT.

Correct, and it is the most consequential of the eight: my round-1 overfetch loop quietly replaced the
algorithm every figure in the document was measured on. Fixed by separating the two numbers.

- `fusion_depth` is a new `meta` key, default **50** — the depth the benchmark ran at — with range 1–500.
  `limit` is the **output** budget only.
- `retrieval.md` §"The dense arm, precisely" now leads with a paragraph naming the defect, listing exactly
  which figures come from depth 50 (0.9375, 21.7-of-77.3, 960/960, 0.8802 degraded, 9.14 ms warm), and
  running the loop to `fusion_depth` distinct eligible memories: `n = fusion_depth × chunk_overfetch`,
  doubling as before. The lexical mirror does the same. Step 6 is explicit that fuse → penalties → total
  order → repair → **cut to `limit`** is the order, and that the cut is last.
- `fusion_depth` is deliberately **not** a request parameter, stated in `architecture.md`'s RPC surface and
  in `schema.md` §Bounds: an agent must not be able to change the ranking algorithm by asking for a different
  number of results.
- Consumers updated: `meta` table, `search`/`surface_call` event details, `architecture.md` `surface(...)`,
  the degraded path (which also retrieves to depth, because a penalized row can fall several places even with
  one arm), `retrieval.md` §Fusion's opening, and **D5's rationale** in `overview.md` — "top-K" was one
  number where it needed to be two.

### 4. [BLOCKER] Required thresholds have no values or initialization contract — ACCEPT, and measured rather than guessed.

Four parts, and I went past what you asked on the third.

- **A complete `meta` contract.** `schema.md` §"`meta` — the complete initialization and validation contract"
  is a 23-row table: key, type, range, v0 default, note. Validation is specified as happening **twice** —
  write defaults at creation, parse and range-check on every open — and a missing, unparseable or
  out-of-range key on open is a **fatal store error** (`−32023 bad_config`), not a fall-back-to-default, with
  the reason: silent substitution is how two deployments rank differently while both look healthy. Unknown
  keys are left alone so a forward-compatible store still opens.
- **The exact quantity, and boundary semantics.** All three cosine cutoffs share one definition: best cosine
  between the querying memory's **first chunk** embedding and any chunk of the candidate — the same rollup the
  dense arm already performs — with the conversion `cos = 1 − d²/2` spelled out so `cos ≥ t` is implementable
  as `d ≤ sqrt(2(1−t))`. Boundaries are **inclusive**, uniformly.
- **Why not the fused score**, since you flagged score scale: a fused RRF score is a function of ranks, so
  "one arm ranked it first, the other missed it" (1/61 = 0.0164) scores *below* "both arms ranked it
  fiftieth" (2/110 = 0.0182). That makes it a poor similarity proxy — the same arm-agreement effect the
  document already documents as its known defect. So the hybrid decides *which* record is the candidate and
  the cosine floor decides *whether* it is close enough. Stated in `schema.md`.
- **The seeds are measured, not provisional-by-assertion.** You said labelling them provisional would
  suffice. Instead, `consolidation.md` §"Parameters, and what the seeds are worth" reports a cosine-separation
  probe over the approved benchmark corpus — 187 memories, bge-small, gist+content, the same embeddings —
  across three pair populations: co-labelled (n=177), near-miss twin (n=122), unrelated (n=4000, seeded).
  Medians 0.682 / 0.706 / 0.603; the full percentile and floor-sweep tables are in the document.

  Three results, and the third changed a statement rather than filling a blank:
  - **`anchor_cutoff = 0.65`** keeps 72.3% of genuinely related pairs and admits 19.4% of random ones; 0.70
    would look tidier and discards 61% of real relations. The distributions **overlap badly** (co-labelled
    p25 0.643 below unrelated p90 0.670) so no floor separates them — and loose is right here for a
    structural reason: the anchor is *advice to a model*, not an automatic action, so both errors are cheap.
  - **`orphan_edge_cutoff = 0.65`**, same relation, same distribution, separate key only so a measurement can
    separate them.
  - **`dedup_threshold = 0.80`, with a caveat that is now load-bearing.** The corpus has no true
    near-duplicates, so it cannot calibrate the true-positive side — and the false-positive side is stark:
    above 0.80 the pairs are dominated by **near-miss twins** (21.3% of twin pairs versus 7.3% co-labelled
    and 0.0% unrelated), and at 0.90 they are *all* twins. **A high cosine dedup floor finds the pairs whose
    merge is the worst mistake this system can make.** So `zikaron_remember`'s `near_duplicates` is now
    documented as *candidates for the agent to compare, never an assertion of duplication*, and D15's
    rationale says so. `dedup_max` default 3.
  - `mutual_k = 5`, `group_max = 12`, `max_group_serves = 3`, `run_lease = 1800 s` all typed and ranged.
- **A defect this measurement exposed, not in your list.** Mutual-top-K with no similarity floor is broken
  in a small journal: with K=5 and six journal rows, *every* pair is mutual, so the whole journal fuses into
  one group. A rank test cannot express "not related at all". The orphan edge test now requires mutual-K
  **and** `orphan_edge_cutoff`, and D29's rationale retracts its own "one parameter instead of two" claim —
  that claim bought a defect, not simplicity.

### 5. [BLOCKER] The event schema cannot represent the consolidation verbs or a zero-result session — ACCEPT, three parts.

- **Consolidation success kinds added**: `merge`, `promote`, `discard`, each with a fixed `detail` shape and
  **one row per row the call mutated** (roles `target`/`absorbed`, `created`/`flipped`/`absorbed`), carrying
  `from_version`/`to_version`, `n_absorbed`, and the size fields on the authored row only.
  `discard.detail.reason` is named as the reason's **only** storage location, which is what
  `consolidation.md` already claimed; that document and D16's interaction line now point at it precisely.
  `version_conflict` and `no_receipt` also became one row **per offending uuid** rather than per call, since a
  consolidator verb can conflict on several.
- **`surface_call`, exactly one per call, always** — including at zero results — with
  `{prompt_chars, limit, fusion_depth, query_tokens, query_truncated, lexical_skipped, n_returned, n_demoted}`.
  I kept `surface` as one-row-per-result rather than folding results into an array, because the
  "surface then amend" signal is a plain `(memory_uuid, at)` index lookup and collapsing it would cost that.
  The two share an `op_id`, and the document says which is the call and which are the results.
  **An honest limit is stated rather than papered over:** `surface_call` counts *sessions the service saw*.
  A session whose every push fell to the degraded path emits nothing, because that path opens the store
  read-only by design. Making the hook write would mean handing it a writable store handle — a worse trade
  than a stated caveat. Repeated in `write-policy.md` §3 so the instrumentation section does not overclaim.
- **Exact numerators and denominators** for all six signals, replacing the previous prose. The
  version-conflict denominator is spelled out as every *attempted* mutation — successes plus
  `version_conflict` plus `no_receipt`, deduplicated by `op_id` — with consolidator verbs in scope, which is
  what D30 requires. Two counting rules are stated once: a rate over calls deduplicates by `op_id`, a count
  of affected rows does not, and every query says which it uses.
- **The error table's blanket rule is fixed, not softened.** `architecture.md` §"What a rejected call does
  and does not change" replaces "mutates nothing" with three precise clauses: no **domain** mutation ever
  (no `memory`/FTS/chunk/vec row, no version, no group status or disposition); audit events **may** commit,
  and only for `version_conflict` and `no_receipt`; and a version conflict **also** mints the receipt for the
  record it returned, without which D26's one-round-trip promise is false. Cross-referenced from `schema.md`
  invariants 9 and 10.

### 6. [BLOCKER] D26's receipt contract contradicts the request and tool contracts — ACCEPT, four parts.

- **The precise claim, in your words.** `architecture.md` §"Why `search` returns no version" now states the
  loose claim, says it is false and why, then gives the narrow one: *`fetch` is the only way to license a
  write to a pre-existing row, absent an own-write or conflict response for that exact row in this session.*
  Propagated to `fetch`'s tool description, D32's decision cell and D26's rationale.
- **Provenance is called transport-supplied, not server-derived.** D27's decision cell said "all
  server-captured", which is true of the timestamps and false of `session_id`. It now reads "captured outside
  the agent-facing call — the timestamps by the service, `session_id` from the client transport envelope — so
  the write tool gains no parameters", with the correction recorded in the rationale. `architecture.md`'s
  opening framing of D27 was carrying the same error and is fixed.
- **NULL labels are eliminated, not tolerated.** This was the sharpest sub-finding: a NULL label made
  `fetch`'s unconditional receipt promise unkeepable against a `NOT NULL` receipt column. I took your
  preferred remedy. If `client.session_id` is missing or malformed the service **mints** `zk-<uuid4>` for
  that call, uses it, and **returns it in the response envelope**; a client receiving a minted label **must**
  adopt and reuse it for its process lifetime. `zikaron-mcp`'s startup path now sources its fallback label
  from `health()` instead of minting its own, so both sides agree. New invariant 18: no live request carries a
  NULL `session_id`; the columns stay nullable only for a hypothetical future import.
- **Validation precedence is fixed and explained.** New `architecture.md` §"Validation precedence": bounds →
  existence → **version** → **receipt** → state legality → mutate, with steps 2–4 evaluated across *all*
  named rows so one call reports every offending uuid. The reason step 3 must precede step 4 is stated as you
  argued it: a version bump revokes receipts, so receipt-first would report `no_read_receipt` for every
  ordinary lost-update race and turn one round trip into two. The converse is also stated — an agent that
  guessed a version passes step 3 when the guess is right and is caught by step 4, which is exactly what D26
  exists to catch. Recorded in `schema.md` invariant 9, D26's rationale, and `consolidation.md` §Interactions.

### 7. [BLOCKER] Query construction is incomplete at the model boundary — ACCEPT, and I differ on the lexical remedy.

Both halves are real. `retrieval.md` §"Query construction" is rewritten into two subsections, one per arm.

**The dense side** gets a preflight symmetric with the write side but resolving the opposite way, and the
asymmetry is argued rather than left implicit: a write can be handed back to an agent that still holds its
text, whereas refusing a user's prompt means refusing to retrieve.
`query_budget = 512 − n_special − prefix_tokens`, counted with the deployed tokenizer; over budget keeps the
**head** and records `query_truncated` plus the pre-truncation `query_tokens`. Head rather than tail is
justified (the head carries the topic and earliest identifiers; it matches the write-side hard split, so one
rule not two) and its mitigation named: the **lexical arm still sees the whole prompt**, so an identifier past
the dense cutoff stays retrievable through BM25. The choice is explicitly labelled unmeasured, which is why
it is instrumented. The **group query drops whole gists** rather than truncating one, reporting `n_gists_used`
— a half-truncated gist is a garbled query. And a distinction that removes the problem elsewhere: `retrieval.md`
§"Two kinds of query" separates **external** queries (prompt, agent search string, group concatenation), which
take the preflight, from **internal** ones (dedup, anchors, orphan edges), which reuse the querying memory's
already-stored **first chunk embedding** — no second embed, no truncation risk, and the same vector every
time, which is what keeps planning a pure function. `indexing.md` names the query-side counterpart so neither
half reads as an oversight.

**The lexical side — ACCEPT the finding, with a different remedy than the one suggested, because it is
strictly better.** You proposed naming an implementable tokenization mechanism, e.g. a temporary FTS5 plus
`fts5vocab(instance)` procedure. I removed the need for one instead:

1. Split the query on Unicode whitespace — the one boundary every tokenizer agrees on.
2. Drop runs containing no Unicode letter or digit. That filter is exactly the complement of what `unicode61`
   discards, so every surviving run yields ≥1 token and no empty phrase can reach FTS5.
3. Quote each surviving run (doubling internal `"`) and join with ` OR `; bind as a parameter.
4. Cap at 64 runs, longest-first.

A quoted string is an FTS5 **string literal**, so **FTS5 applies the table's own tokenizer to its contents**.
There is no second tokenizer to diverge, by construction — which is a stronger guarantee than agreeing with
`unicode61` by procedure, and it is identical in the service and the degraded hook with nothing beyond
stdlib. The one semantic change is that a quoted run is a *phrase* rather than an OR of its sub-tokens, and
that costs no recall for a structural reason stated in the document: both sides were tokenized by the same
tokenizer, so any document containing the original run contains its sub-tokens in that adjacency. Precision
improves; recall does not regress. `schema.md` §Bounds now caps "quoted runs", not "terms".

### 8. [BLOCKER] Three evidence statements have widened again — ACCEPT all three, and a fourth I found.

- **The identifier mitigation claim.** `retrieval.md` §"The identifier weakness" no longer says mitigations
  "are lexical or joint-attention rather than a bigger bi-encoder". It now quotes the report's settled
  language — **no demonstrated remedy from the tested deployed artifacts, capacity itself untested** — and
  says why the old sentence was wider than the evidence twice over: it ruled out a mechanism the instrument
  did not test and credited two the instrument also did not test.
- **The 83–100% figure in `consolidation.md`.** Rescoped to what was measured: on the **6 current-action
  polarity stubs (18 prompts)**, a record the query should not have acted on was in the injected five
  83–100% of the time — superseded records under polarity prompts, not long-term records in general. The
  argument it supports is preserved and made explicit, because it is the transferable half: a corrupted
  record does not quietly fail to retrieve, it gets shown.
- **"Four historical-intent queries."** Now **4 stubs / 12 prompts**, in `overview.md` D25 and
  `retrieval.md`, both carrying the report's own "indicative only, too small for inference". D25's 83–100% /
  28–50% figures are scoped to the 6 stubs / 18 prompts in the same cell.
- **A fourth, same class, not in your list.** `retrieval.md` §Fusion argued that "the near-miss
  discrimination the dense side lacks is carried by the lexical arm at 0.988", and §"The identifier weakness"
  concluded "BM25 carries this discrimination today". Both are unsupported. The `near_miss` category scores
  **0.9881 for the lexical arm, the dense arm and the hybrid alike** (0.9524–1.0000 across all 18
  configurations) — it is saturated and distinguishes nothing. And the counterfactual instrument tested **four
  embedders and no lexical arm**. So whether BM25 compensates is *untested*, not proven. §Fusion now names
  what the blind set does not show, and rests the both-arms case on paraphrase (0.667/0.667 → 0.800) and
  error strings (0.967/0.967 → 1.000), which it does support. Configuration labels added at each figure.

### Additional defects found while remediating round 2, fixed and reported

- **Mutual-top-K has no similarity floor** — in a six-row journal with K=5 every pair is mutual and the whole
  journal becomes one group. Fixed with `orphan_edge_cutoff`; D29's "one parameter instead of two" rationale
  retracted. Reported under finding 4 above.
- **Receipt minting was not idempotent**, which the new re-serve rule would have made a primary-key
  violation. Invariant 9 now requires an upsert.
- **`'abandoned'` was in the run-status CHECK with no producer.** Now defined: the owning session calling
  `plan_groups` again.
- `architecture.md`'s framing of D27 repeated the "server-captured" error independently of D27 itself.

### `FINDINGS.md`
Edited only where it had drifted from `design/`, per the standing constraint:
- Open question 5 described the impossible adjacency rule; now describes the precedence rule and says round 2
  replaced it, with the reason.
- Open question 2 now names `fusion_depth` and `rrf_k` as `meta` keys, so the tuning pass it describes is a
  config sweep rather than a code change.
- Documents table: schema's invariant count 16 → 18, plus the `meta` contract.
- Current-state paragraph: round 2, its eight blockers, the six rationale corrections, and the measured
  parameter seeds.
Open questions 1, 3, 4, 6, 7, 8 and 9 are untouched and remain open. No D-index line needed changing.

### For the user, not for me
1. **Two decision *cells* were reworded, not only their rationale.** D27: "all server-captured" → "captured
   outside the agent-facing call — timestamps by the service, `session_id` from the client transport
   envelope". D32: "`fetch` is the primary agent's only source of `version`" → "`fetch` is how the primary
   agent licenses a write to a row it did not itself just write". Both were factually false as written and
   both preserve the decision's substance — three provenance fields, no agent-facing parameters, read before
   amend — but they are the user's cells to confirm.
2. **Seven new defaults were chosen, three of them from a measurement the user has not seen.**
   `fusion_depth` 50 (matches the benchmark, low risk), `retired_penalty` 0.5, `dedup_max` 3,
   `max_group_serves` 3, and the three cosine cutoffs — `anchor_cutoff` 0.65, `orphan_edge_cutoff` 0.65,
   `dedup_threshold` 0.80 — grounded in the probe reported in `consolidation.md`. The probe's most
   consequential result deserves the user's attention directly: **on a store containing near-miss twins, a
   high cosine dedup floor surfaces twins rather than duplicates**, so D15's hand-back can only ever be
   candidates for comparison. That is a product-facing consequence, not just a parameter.
3. **The grounding probe is not persisted.** I am scoped to `design/`, `FINDINGS.md` and `reviews/`, so the
   script that produced the cosine tables lives at `/tmp/zk_cutoff_probe.py` (run with
   `experiments/embedder-precision/.venv/bin/python`, reads only `dataset.json`, `stubs_v2.json` and the
   bge-small `embcache` — it embeds nothing). Only its inputs and method are recorded durably, in
   `consolidation.md`. It should be moved into `experiments/embedder-precision/` and its result folded into
   `research/` by someone with write access there, or the numbers will be re-derived from scratch the next
   time anyone asks.
4. **`max_group_serves` introduces a bounded give-up.** A group can now be `deferred` for the remainder of a
   run after three serves. Never-lose is intact — its rows stay in the journal for the next run — but it is a
   new behaviour where the consolidator can be told "not this run", and that is worth knowing about.

Knowledge base re-indexed (`zikaron-design`, path `/home/nathan/Zikaron/design`) after the edits.

## Round 3 — 2026-08-01

### Summary judgment

Round 2 repairs the eight defects it targeted: the supersession order is realizable, consolidation now has persisted serve-time state, fusion again runs at depth 50, required thresholds have defaults, and the receipt/query/evidence language is materially narrower. The corpus is still not buildable without guessing, however: the new mechanisms leave cross-client session correlation broken, internal hybrid queries and path-specific eligibility undefined, and several state/config/event invariants contradictory. The new cutoff evidence is also not faithful to the scoring primitive and pair population the design says it measured.

### Round-2 finding disposition

| # | Status | Judgment |
|---|---|---|
| 1 | **Partially resolved** | The graph is now correctly described as converging and the stable topological precedence pass is realizable, but an active component root can still be retired outright, violating the invariant that an existing supersession target is not retired-outright. See finding 4. |
| 2 | **Partially resolved** | Serve-time versions, persisted authorization, re-serving, deferral, and terminal transitions are specified, but lease expiry contradicts the error mutation rule and authorization is checked too late. See findings 3 and 7. |
| 3 | **Resolved** | `fusion_depth` is distinct from output `limit`, defaults to the benchmarked 50, and the cut is last. |
| 4 | **Partially resolved** | The required retrieval/grouping keys now have typed defaults and cutoff semantics, but the supposedly complete config contract is internally contradictory and omits a promised model setting; the empirical rationale for three defaults is not reproducible or faithful as stated. See findings 5 and 6. |
| 5 | **Partially resolved** | Consolidation success events, zero-result `surface_call`, audit exceptions, and exact signal denominators are present, but in-place promotion has two incompatible event cardinalities. See finding 8. |
| 6 | **Partially resolved** | NULL request sessions and receipt precedence are fixed, and the narrower licensing claim is coherent. The hook and MCP client can still use different labels for one Kiro session, which breaks every cross-client per-session signal. See finding 1. |
| 7 | **Partially resolved** | Dense preflight is now deterministic and the lexical construction is implementable without a second tokenizer. The internal-query contract specifies only its dense input, and the claimed no-recall consequence of quoted runs is false. See findings 2 and 10. |
| 8 | **Resolved** | All four evidence claims identified in round 2 are now scoped to the benchmark report's actual population and conclusion. |

### Findings blocking approval

1. **[BLOCKER] A “session” is not shared between the hook and MCP clients, so D30's cross-client signals are not reproducible.** `design/architecture.md`, “The request envelope,” has the hook use Kiro's payload `session_id`, while `zikaron-mcp` falls back to a new service-minted process label when the harness does not export that id. Stability within each process is not enough: `surface_call`/`surface` are emitted by the hook, while `remember`/`amend` are emitted by MCP. With different labels, every fallback-labelled writing session appears to be a zero-write hook session, and “amend after surface” can never join. This contradicts `design/schema.md`, “D30's six signals,” and `design/write-policy.md` §3. Define one concrete transport by which both clients obtain the same session label, or explicitly define and instrument an unavailable-correlation state and narrow the two signals; do not claim that independent stable labels satisfy the current queries.

2. **[BLOCKER] Internal hybrid retrieval has no lexical query, and its claimed universal eligibility makes two consumers operate on rows they cannot legally use.** `design/retrieval.md`, “Two kinds of query,” defines an internal query only by reusing the memory's first-chunk **embedding**; it never says what text dedup, anchoring, and orphan adjacency send to the BM25 arm. `design/consolidation.md` nevertheless relies on the hybrid's lexical discrimination. Separately, `design/schema.md`, “Retrieval eligibility,” says dedup and orphan edges use live ∪ superseded rows: `zikaron_remember` can therefore return an inactive superseded candidate without a `state` field even though `design/architecture.md` tells the agent to resolve it by `amend`, which rejects inactive rows; superseded journal rows can likewise consume orphan top-K ranks although group members must be active unconsolidated journal rows. Specify the internal lexical text and bounding rule (for example, full `gist + content` through the same literal-query constructor), and define/document the consumer filters: at minimum active journal candidates for orphan adjacency, and either active-only dedup candidates or state-aware output and resolution semantics. Update the “one predicate/one narrowing” claims accordingly.

3. **[BLOCKER] Consolidator authorization is checked after version handling, so a mutation verb can be used as the retrieval capability D32 says was withheld.** `design/architecture.md`, “Validation precedence,” checks existence and version before `not_in_group`/`bad_merge_target`. A consolidator can submit an out-of-group known UUID with a deliberately wrong version; `version_conflict` then returns its full current record and mints a receipt before authorization is considered. This falsifies D7/D32's claim that withholding `search`/`fetch` mechanically prevents wandering outside code-selected candidates. For consolidation verbs, validate run ownership plus member/target authorization from the persisted group tables before exposing global existence, version, or content; then preserve version-before-receipt within that authorized set.

4. **[BLOCKER] The supersession target-state invariant is not closed under an ordinary later `retire`.** `design/schema.md` invariant 6 forbids creating an edge to a retired-outright target and describes the component root as the current record. But after `A→B` exists, `zikaron_retire(B, superseded_by=None)` is legal while B is active; it produces `A→B` with B now retired outright, a state the same invariant says is invalid, and `superseded_by_latest` now resolves to a non-current root. Either forbid outright retirement of a row with incoming supersession edges (requiring it to be superseded by a replacement), or permit terminal retired components and rewrite the target-state, root/display, retrieval, and error semantics consistently.

5. **[BLOCKER] The “complete” configuration contract has contradictory and missing defaults.** `design/schema.md`, §`meta`, says every listed key is written at creation and any missing key is fatal, but lists `reindexing` with default **absent** and says absence is the normal state. The same table gives `embed_prefix_query` as the description “the documented BGE query instruction” rather than the literal default, despite the measured pipeline using the exact string `Represent this sentence for searching relevant passages: `. More importantly, `design/overview.md` D29 and `design/consolidation.md`, “Consolidator identity and model,” require the consolidator model to be a config value, but no store key, agent-config field, default, or inheritance rule exists. Exempt the ephemeral sentinel from required-key validation or represent its idle state explicitly; give the literal prefix; and locate/type/default the consolidator model setting (it may live in the shipped agent config rather than `meta`).

6. **[BLOCKER] The new cutoff tables are not durable evidence for the deployed scoring rule or the pair populations claimed.** `design/consolidation.md`, “Where the three cosine seeds come from,” calls the probe reproducible from `experiments/embedder-precision/`, but no probe or result artifact exists there; the remediation identifies only `/tmp/zk_cutoff_probe.py`. That script embeds one cached whole record (`gist + content`) per memory, whereas `design/schema.md` defines the deployed threshold as first-chunk query → best candidate chunk. It also labels every co-labelled pair containing any query-level `confusable_uuid` a “near-miss twin,” not specifically a designated memory-twin pair as the prose says. Thus the precise percentiles and claims such as “at 0.90 they are all twins” do not trace to the stated estimand. This does **not** require a real-data benchmark: either persist a corrected probe/result using the deployed scorer and accurately named populations, or retain the buildable defaults as provisional heuristics and remove the unsupported measured derivation and precise claims.

7. **[BLOCKER] Lease expiry has two incompatible state-transition contracts.** `design/schema.md` invariant 17 and `design/architecture.md`, “Planning,” say any run call that finds its lease passed sets `active → expired`. The same architecture's error rule says a rejected `group_expired` call changes no `consolidation_group*` status and that only conflict/no-receipt errors may write anything. Both cannot hold. Choose one observable rule: either make expiry cleanup an explicit allowed state mutation on `group_expired`, or have expired calls leave the row unchanged and let only `plan_groups` perform the guarded transition while treating `expires_at < now` as effectively expired. Align the error payload's `run_status` with that choice.

8. **[BLOCKER] The fixed event contract cannot represent in-place promotion unambiguously.** `design/schema.md`, “The event log, per kind,” says `promote` emits one event per mutated row, but also says it emits the new/flipped row **plus** one per absorbed member. Under `design/architecture.md`, an in-place promote occurs when the sole absorbed member is itself flipped, so one physical row is simultaneously the `flipped` output and the absorbed member. The singular `role` cannot express both, and implementations will emit either one or two events, changing write-size and affected-row counts. Define the in-place cardinality explicitly—most simply one `role:'flipped'` event and no duplicate `absorbed` event for that UUID—and align all queries.

9. **[BLOCKER] The total order applies recency to long-term records while three documents say recency is journal-local only.** `design/retrieval.md`, “Total order,” applies `created_at DESC` after tier for every tie, including ties between two long-term rows. The same document later says recency survives “only as a journal-local tiebreak”; `design/overview.md` D27 and `design/schema.md`, “Deliberately absent,” make the same policy claim. Because exact RRF ties are pervasive, this is executable behavior, not editorial phrasing. Make the key conditional on `tier='journal'`, or explicitly change the policy/rationale everywhere.

10. **[BLOCKER] The lexical constructor's “costs no recall” proof is false.** `design/retrieval.md`, “The lexical arm,” turns each punctuation-containing whitespace run into one FTS5 phrase and argues that this cannot lose recall because index and query use the same tokenizer. It preserves matches for documents containing the original run adjacently, but not the recall of the previously specified OR-of-tokens query: `foo.bar` now requires adjacent `foo bar`, while a relevant document containing those tokens non-adjacently would previously match. The implementation is deterministic and may be a reasonable precision trade; no new measurement is required. Remove the no-recall claim and describe the actual phrase-versus-term tradeoff (or choose a literal construction that retains term-level OR semantics).

11. **[BLOCKER] The emergency secret-erasure guidance does not actually erase a row from this schema.** `design/write-policy.md`, “Inspection, deletion,” tells a user to “delete the row and its chunks directly,” but `memory_fts` is an external-content FTS5 table requiring explicit maintenance, `memory_vec` has no foreign key and must be deleted before chunks, and plaintext may remain in WAL/SHM or `service.log`. A direct `DELETE FROM memory`/chunk deletion can therefore leave searchable FTS terms and orphaned vectors—the exact safety outcome this paragraph promises to fix—and it also conflicts with D16's unqualified “Never hard DELETE.” Clarify that D16 constrains the agent-facing API, then provide an exact supported operator erasure transaction plus stop/checkpoint/log guidance and its secure-deletion limits, or make deleting the entire stopped `.zikaron` store the only documented emergency procedure.

VERDICT: NEEDS_CHANGES

---

## Response to review round 3

**11 findings, 11 accepted, 0 rejected.** Every one was checked against the source it cites and every one
named a real defect. Where I differed from the suggested remedy — five of the eleven — that is stated under
the finding rather than absorbed silently.

The through-line of this round is worth naming, because it is the same shape as round 2 and useful for
whoever reviews round 4: **round 2's fixes were each locally correct and globally incomplete.** A stable
session label per process is correct — and not the same thing as a *shared* label. A validation order that
puts version before receipt is correct — and becomes a read primitive when the same order is applied to a
verb set that was deliberately denied reads. A write-time graph precondition is correct — and is not a
property any later write preserves. In each case the round-2 text asserted the *system* property while having
implemented only the *local* one.

**No user decision (D1–D32) was reversed.** Six *rationales* were corrected — D15, D16, D25, D27, D29, D30,
D32 — each because it claimed more than its mechanism or its evidence supported. **No decision cell was
reworded this round.** One figure was **withdrawn** rather than corrected (finding 6), which is a first for
this corpus and is the item most worth the user's attention.

### 1. [BLOCKER] A "session" is not shared between the hook and MCP clients — ACCEPT, and I took both remedies.

You are right, and the failure direction is what makes it a blocker rather than a caveat: pushes are hook
events and writes are MCP events, so under mismatched labels **every fallback-labelled writing session reads
as a zero-write hook session** — inflating precisely the under-writing rate D30 exists to test, in the
direction our own prior expects. Instrumentation that is wrong in the direction of its own hypothesis is
worse than absent instrumentation.

You offered "define one concrete transport" *or* "define and instrument an unavailable-correlation state and
narrow the two signals". I did both, because either alone is unsatisfying: a transport we cannot verify might
never fire, and narrowing alone leaves the two signals plausibly always empty.

- **A three-step resolution ladder**, `architecture.md` §"Both clients must resolve the *same* label, or two
  signals die". `harness` (the id the harness supplies — always available to the hook, available to MCP if
  the harness exports one) → `ancestry` → `minted`.
- **`ancestry` is the concrete transport, and it is labelled unverified.** The `agentSpawn` hook registers
  `{session_id, ppids}` — its own ancestor pid chain from `/proc/<pid>/stat` — and `zikaron-mcp` sends its
  own chain; the service matches on **deepest common ancestor**, since both processes descend from the same
  harness process. Registrations live in service memory, because they are transport state rather than
  knowledge. **Ambiguity fails closed**: a tie or a miss falls through to `minted` rather than guessing
  between two sessions. And it says plainly that we have not observed kiro's process topology, that `/proc`
  is Linux-only, and that a pid namespace or a re-exec breaks the match — which is exactly why
  `label_source` is persisted, so an analysis can recompute on `harness` labels alone.
- **The unlinked state is instrumented, not described.** `event` gains two columns, `client_kind` and
  `label_source` (`schema.md`), plus `idx_event_session_client`. A session is **linked** iff a `hook` event
  and an `mcp` event share its `session_id`; **link coverage** = linked ÷ sessions with any hook event.
- **The two cross-client signals are narrowed** to linked sessions and are reported *with* coverage, in
  `schema.md` §"D30's six signals" and §"Linked sessions", `write-policy.md` §3 (now "two honest limits", not
  one) and D30's rationale. The signal table also now marks each of the six as single- or cross-client, so it
  is visible at a glance which four are unaffected.
- The false sentence is gone: `architecture.md` no longer says one stable label per process "is all the
  per-session signals need", and says so explicitly as a correction. D27's rationale carries the same.

### 2. [BLOCKER] Internal hybrid retrieval has no lexical query, and "one predicate" hid two illegal consumers — ACCEPT, both halves.

**The internal lexical text.** Round 2 defined an internal query only by its dense input, which left the BM25
arm of dedup, anchoring and orphan adjacency undefined — while `consolidation.md` was resting its
`WidgetV1`-versus-`WidgetV2` argument on exactly that arm. Fixed by taking your suggested form: the querying
memory's own **`gist + content`** through the *identical* term constructor an external query uses, capped at
`fts_query_max_terms`. `retrieval.md` §"Two kinds of query" now specifies both arms for both kinds, and adds
the property that makes the cap safe here rather than arbitrary: keeping the **longest** terms keeps the
identifiers, error strings and paths, and drops the short common words BM25 scores near zero. Restated at
`consolidation.md` steps 1 and 2 and in `schema.md` §Bounds.

**The consumer filters.** The "one documented narrowing, and only one" claim was false, and false in the
dangerous direction — the two undocumented ones were the bug:

- **dedup → `active = 1`.** Chosen over your alternative of state-aware output, and the reason is that the
  alternative solves the wrong problem: the offered resolution is "`amend` the older row", `amend` rejects
  `active=0`, so a superseded candidate is an offer the agent *cannot take*. Adding a `state` field would
  document the dead end rather than remove it. Little is lost, because a superseded row's replacement is
  active and will surface in its place if it is genuinely close.
- **orphan adjacency → `tier='journal' AND active=1`, excluding self.** Exactly your minimum. The filter *is*
  the definition of a group member, so a row that can never be a member should not hold one of the
  `mutual_k` ranks — which matters most in the small-journal case where the graph is already sparsest.
  Excluding self is not pedantry: a memory is its own nearest neighbour.
- Both are now in **one table**, `schema.md` §"Consumer filters", alongside consolidation's — with the
  generalization that makes the set principled rather than a list: *retrieval for reading narrows nothing;
  retrieval for mutation narrows to what may be mutated.* Every filter is the legality condition of the
  action its rows are retrieved for.
- The "one predicate" claims are corrected at all four sites: `schema.md` §"Retrieval eligibility" opening,
  `retrieval.md` §"One eligibility predicate", `consolidation.md` step 1, and D29's rationale.

### 3. [BLOCKER] Consolidator authorization ran after version, making a mutation verb a read primitive — ACCEPT.

This is the sharpest finding of the round and it is entirely correct: `version_conflict` returns the full
current record *and mints a receipt*, so version-before-authorization let a consolidator name any uuid with a
deliberately wrong version and reassemble `fetch` one deliberate conflict at a time — with a write licence
attached. D7's "code picks the candidates" was enforced by nothing.

- `architecture.md` §"Validation precedence" is now **two ladders**. Primary verbs keep
  bounds → existence → version → receipt → state → mutate. Consolidator verbs are
  bounds → **authorization** → existence → version → receipt → state → mutate, where authorization is
  entirely from `consolidation_group_member` and `consolidation_group_candidate`: group exists, run belongs to
  the caller and is unexpired, group is `served`, every `absorb` uuid is an undispositioned member, a `merge`
  target is in the persisted candidate set.
- **The authorization payloads cannot be used as an oracle either**, which your finding implies and I made
  explicit: they carry **uuids only** — no version, no state, no prose — and `bad_merge_target`'s `reason` is
  `not_authorized` for every unauthorized uuid *whether or not it exists*, so the error does not distinguish
  the two. Without that clause the fix would have leaked existence instead of content.
- Version-before-receipt is preserved **within** the authorized set, with the round-2 reasoning intact.
- Recorded in `schema.md` invariant 9, `consolidation.md` §Interactions, and D26's and D32's rationales — D32
  in particular now states that its mechanical-enforcement claim was nominal until this ordering existed.

### 4. [BLOCKER] The target-state invariant is not closed under a later `retire` — ACCEPT, second option.

Correct: after `A→B`, `zikaron_retire(B)` with no replacement is legal while B is active, and it produces a
state invariant 6 called invalid. You offered forbidding it or permitting terminal components. **I permit
them**, and reject forbidding on the merits rather than for convenience: forbidding would force an agent
holding a whole-lineage falsification to either leave a known-false row active or invent a replacement it
does not have, and "this lineage is dead, nothing replaces it" is a thing tribal knowledge genuinely needs to
say.

- `schema.md` invariant 6 now separates **write-time preconditions** from **preserved properties**. Self-edge
  and acyclicity are permanent; the target-state rule is a precondition *only*, and the reason is restated so
  it survives the distinction: `retire(A, superseded_by=B)` *asserts* "B replaces A", which is false at the
  moment it is made if B is already untrue — whereas B becoming untrue later is new information, not a false
  claim. Nothing re-checks it afterwards, and the document says nothing should.
- A **root is live or terminal**; both legal, both defined.
- Invariant 7 adds **`superseded_by_latest_state`**, returned by `fetch` (`architecture.md`), because an agent
  told only "replaced by `5d81…`" would otherwise be sent to a row that is also no longer true.
- **Retrieval is deliberately unchanged, and the cost is stated rather than buried:** eligibility still
  demotes on the immediate edge and does not consult root state, so a dead lineage can still surface.
  Resolving root state per candidate means a graph walk per row in the fused pool — against invariant 7's own
  rule and against D22's latency budget. The trade is named: cheap ranking on the edge, full truth on `fetch`.
  `retrieval.md`'s push-format bullet and D25's rationale both say which half they are.
- Acceptance test added beside the other two: `A→B` then outright `retire(B)` must succeed.

### 5. [BLOCKER] The "complete" config contract was contradictory and incomplete — ACCEPT, all three.

- **`reindexing` is out of the required table.** It is now described as an **ephemeral sentinel**, explicitly
  exempt from required-key validation, with both readings defined: absent is normal, and *present on open*
  means a previous process died mid-reindex and must finish or restart it before serving. Listing it with
  default "absent" directly contradicted the paragraph above it, as you say.
- **The literal prefix.** `embed_prefix_query` now defaults to the exact string
  `Represent this sentence for searching relevant passages: ` — trailing space included and called out —
  quoted from the model card via `research/embedding-models-technical-prose.md`, with the reason given as a
  rule rather than a nicety: a paraphrase would be a different measured pipeline.
- **The consolidator model is located, typed and defaulted**, in `architecture.md` §"The consolidator's model
  is a shipped config field": the top-level `model` field of `.kiro/agents/zikaron-consolidator.json` — the
  field agent configs in this repo already use, verified locally — string, default `claude-sonnet-4.5`. You
  allowed it to live in the agent config; it does, and `schema.md` §`meta` now says so at the place a reader
  would look for it, so its absence from `meta` reads as a decision rather than an omission. Three rules go
  with it, each closing a way the measurement could be lost: **no silent inheritance** (the field is written
  out even when it matches the harness default, because an omitted field means the consolidator runs whatever
  the user's session runs and D29's variable is then set by something we neither control nor record), **no
  silent fallback** (an unknown id fails the skill loudly, on the same logic that makes a bad `meta` key
  fatal), and the default **leans capable rather than cheap** because consolidation is rare and off the hot
  path while a bad consolidation durably corrupts a record retrieval will keep surfacing.

### 6. [BLOCKER] The cutoff tables are not durable evidence for the deployed scorer or the claimed populations — ACCEPT, second option, and the reason for choosing it is partly a scope limit.

Both defects are real. The probe scored one cached whole-record `gist + content` vector per memory, while
`schema.md` defines the threshold as first-chunk → best-candidate-chunk; and it labelled every co-labelled
pair containing any query-level `confusable_uuid` a "near-miss twin", which is not the designated twin *pair*
the prose described. So the percentiles and "at 0.90 they are all twins" did not measure the estimand they
were quoted for.

You offered persisting a corrected probe *or* retaining the defaults as provisional heuristics with the
derivation removed. **I took the second, and one reason is a hard constraint rather than a judgment: this
remediation is scoped to `design/`, `FINDINGS.md` and `reviews/`, so I cannot write a probe under
`experiments/` or a result under `research/`.** Doing it in `/tmp` again would reproduce the exact defect you
identified. Flagged for the parent below.

What changed:

- `consolidation.md` §"Where the three cosine seeds come from" is rewritten. The tables are **removed**, and
  the removal is recorded with both reasons rather than quietly done — because a corpus that silently drops
  its own numbers is worse than one that never had them.
- Each of the three values now has a reason **that does not depend on a measurement**: `anchor_cutoff` loose
  because the anchor is advice to a model and both error directions are cheap; `orphan_edge_cutoff` seeded
  equal because it thresholds the same relation; `dedup_threshold` a seed whose *framing* is what carries
  weight.
- **The load-bearing conclusion survives on approved evidence, and is now better supported than it was.**
  `research/embedder-benchmark-results.md` measures near-miss identifier pairs at **absolute cosine ≈ 0.73
  with a margin of ≈ 0.04**, DI **0.194–0.233** across all four models. That is enough on its own: any floor
  high enough to be selective admits twins, so D15's hand-back can only ever be candidates to compare. The
  argument no longer needs the withdrawn tables at all. Propagated to §"Why not cosine alone" (which had
  cited the tables), D15's rationale, D29's rationale, `schema.md` §`meta`, and `FINDINGS.md`.
- **What is *not* provisional is kept separate**, because it would be easy to lose: `orphan_edge_cutoff` must
  *exist* for a combinatorial reason, not an empirical one — with `mutual_k=5` and six orphans every pair is
  mutually top-K and the whole journal fuses into one group.
- §"What it would take to call any of these measured" states the exact requirements for a replacement probe,
  so the next attempt does not re-derive the estimand.

### 7. [BLOCKER] Lease expiry had two incompatible contracts — ACCEPT, and I chose your second option.

Correct — invariant 17 and §Planning had *any* run call performing `active → expired`, while §"What a
rejected call does and does not change" forbids a rejection from touching `consolidation_group*`. Both cannot
hold.

**Expiry is now derived on the read side and stored only at plan time.** Every reader treats
`status='active' AND expires_at < now` as effectively expired and rejects, changing nothing; `plan_groups` is
the sole producer of the stored `'expired'` status and the sole emitter of the `consolidate_run`
phase-`expired` event. I chose this over making expiry an allowed mutation on `group_expired` because the
alternative puts a write on a rejection path, and that rule is load-bearing elsewhere — finding 5 of round 2
was fixed by tightening it, so weakening it here would have traded one contradiction for another.

- `−32011 group_expired`'s payload is aligned as you asked: `{group_id, run_status, expires_at,
  effective_status}`, where `run_status` is the **stored** value and `effective_status` is `'expired'`
  whenever the lease has passed.
- The observable consequence is stated rather than hidden: a store can hold an `active` row whose lease has
  passed. It is a lazily-collected tombstone, and every reader computes the same answer from `expires_at`.
- One thing this made possible that the old rule obscured, now written down: **takeover after a crash**.
  Because expiry is derived, a *different* session finding an `active`-but-expired run is not blocked — its
  `next_group` implicitly replans, marking the dead run `expired`. Only an `active` **and unexpired** run of
  another session yields `{busy: true}`. So a crashed consolidator cannot hold the store beyond one lease and
  the recovery needs no operator. (`architecture.md` §"Consolidation lifecycle", `schema.md` invariant 17.)

### 8. [BLOCKER] In-place promotion had two incompatible event cardinalities — ACCEPT, your suggested form.

Correct: an in-place promote flips the sole absorbed member, so one physical row is simultaneously the
`flipped` output and the `absorbed` member, and a singular `role` cannot say both.

**`in_place` emits exactly one event**, `role:'flipped'`, `form:'in_place'`, `n_absorbed: 1`, and **no**
`absorbed` event for that uuid. `new_row` emits one `created` plus one `absorbed` per absorbed row. Stated in
`schema.md` §"The `event` log, per kind" as a named rule under the table (not only in the cell), and repeated
in `architecture.md`'s `zikaron_promote` contract. The write-size query in §"D30's six signals" now says
explicitly that an in-place promotion contributes exactly one row, so affected-row counts and size
distributions cannot diverge between implementations.

### 9. [BLOCKER] The total order applied recency to long-term records — ACCEPT.

Correct, and correctly framed as executable behaviour rather than phrasing, since exact RRF ties are
pervasive: the order really did rank two long-term rows by `created_at` while three documents said recency was
journal-local.

`retrieval.md` §"Total order" step 4 is now **conditional on `tier='journal'`**; long-term ties fall through
to `uuid`. I took the conditional rather than changing the policy, because the policy is stated in three
places (D27's rationale, `schema.md` §"Deliberately absent", and this document's own recency paragraph) and
the argument behind it — age does not predict truth for tribal knowledge — is sound.

Worth recording because it is the kind of thing that gets "fixed" back: **a conditional comparator would
normally threaten transitivity, and here it does not**, because step 3 has already partitioned the remaining
ties by tier. Every row still tied at step 4 shares a tier, so "apply this only for journal rows" is a
property of the whole tie-block. That reasoning is now in the document, so the next reader does not have to
re-derive it or revert the conditional out of caution.

### 10. [BLOCKER] The lexical constructor's "costs no recall" proof is false — ACCEPT, and I took the parenthetical alternative rather than the annotation.

You are right and the counterexample is trivial. I verified it locally against `unicode61`: a document
containing "foo appears here and bar appears much later" matches `"foo" OR "bar"` and does **not** match
`"foo.bar(baz)"`. My proof only showed that documents containing the *original run* still match; it said
nothing about the non-adjacent recall the round-1 OR-of-terms rule had.

You allowed removing the claim and describing the tradeoff. **I removed the tradeoff instead**, by taking your
parenthetical: split each whitespace fragment further into **maximal runs of Unicode alphanumerics**, quote
each, and `OR` them — term-level semantics, which is what round 1 intended.

The reason this does not reintroduce the divergence problem that motivated the phrase form: **we only need to
match FTS5's boundaries, never its folding**, because each term is still quoted and FTS5 re-tokenizes the
literal. Verified locally with `fts5vocab` on nine technical strings — dotted module paths,
`PGHOST=db-1.internal:5432`, `WidgetV1.render()`, `snake_case`/`kebab-case`, `café naïve`, `C++ / C#` — with
**zero disagreements**, including the two cases most likely to bite (underscore is a `unicode61` separator;
diacritics fold). The residual risk is named and bounded in the document: a codepoint whose category Python
and SQLite classify differently costs **one term a match** — never a syntax error, never a folding mismatch,
never corpus-wide — which is strictly less exposure than reimplementing the tokenizer.

Propagated: `schema.md` §Bounds now caps quoted **terms** (via a new `fts_query_max_terms` `meta` key) with a
deterministic `(−length, first occurrence)` tie-break, which the old "longest-first" lacked; `retrieval.md`
§"Two paths" and the dense-preflight mitigation say "terms"; the internal-query constructor is the same
function.

### 11. [BLOCKER] The emergency erasure guidance does not erase — ACCEPT, and it was worse than stated.

Correct on every mechanism, and I verified the central one: after `DELETE FROM memory WHERE rowid=1`, a
`MATCH` on that row's text **still returns rowid 1**, because `memory_fts` is external-content and cannot
derive the old values. The documented repair —
`INSERT INTO memory_fts(memory_fts, rowid, gist, content) VALUES('delete', …)` with the old values — removes
it and passes `integrity-check`. I also confirmed that `ON DELETE RESTRICT` on `superseded_by` **blocks** the
delete outright, so the old guidance would often have failed with a foreign-key error rather than silently
half-succeeding.

`write-policy.md` §"Inspection, deletion" is rewritten:

- **D16 is scoped, not weakened.** "Never hard `DELETE`" constrains the **agent-facing API**; an operator
  holding the 0600 file is outside that boundary by construction, the same boundary
  §"Filesystem security" already draws. D16's rationale in `overview.md` carries the clarification, and the
  decision is unchanged: no agent gets a hard delete.
- **An exact transaction**, in order: FTS `'delete'` with current values → vectors → chunks → clear the
  `RESTRICT` references (incoming `superseded_by` edges become terminal; the consolidation run is dropped,
  which loses nothing because undispositioned members stay in the journal) → the row → `integrity-check` →
  `PRAGMA wal_checkpoint(TRUNCATE)` → `VACUUM`. Plus stopping the service first, and truncating
  `service.log`, which quotes prompts.
- **Three limits stated, one of which you did not name and I found while writing it:** `event.detail` is not
  covered, and although event details store counts rather than prose, **`discard.detail.reason` is
  model-authored text** and could quote the secret — so the procedure names it. Also: a copy pasted into a
  second memory is a second row, and `VACUUM` is not secure deletion against copy-on-write filesystems, SSD
  wear levelling, snapshots or backups.
- **The recommended procedure is the blunt one** — stop the service, delete the whole `.zikaron/` directory —
  because it has no ordering hazards. The cost is every memory in the store, which is the right trade against
  a leaked credential and is the reason the prompt's prohibition is the actual control.
- `schema.md` §"File permissions" now points here, so a schema-only reader does not conclude a row delete is
  a row delete.

### Additional defects found while remediating round 3, fixed and reported

- **The conflict payload had three shapes.** `amend` returned
  `current: {uuid, gist, content, version, state, superseded_by_latest}`, `retire` returned `current: {...}`,
  and the consolidator verbs returned `current: [{uuid, gist, content, version, state}]` — no resolved head.
  Now defined **once** as `CONFLICT_RECORD` in `architecture.md` under the MCP surface and referenced by all
  six verbs, including `superseded_by_latest_state` for the same reason `fetch` carries it: a conflict is often
  how an agent learns someone already repaired the row, and pointing it at a replacement that is itself
  retired restarts the loop it is trying to leave.
- **`event.client_kind` initially included a `'service'` value with no producer** — the same class of defect
  as round 2's ownerless `'abandoned'` status. Removed: every v0 event is emitted inside a client call, which
  is also what lets invariant 18 hold.
- **`retrieval.md` claimed internal queries "cannot overflow"** without saying that this is a dense-arm
  property. Their lexical side *is* bounded, by the 64-term cap, and on a long memory that cap does real work.
  Both halves are now stated as bounded; neither is bounded silently.

### `FINDINGS.md`
Edited only where it had drifted from `design/`, per the standing constraint — no restructuring, no rationale
moved back:
- Current-state paragraph: three rounds; round 3's eleven blockers with the two worth carrying; and the
  **withdrawal** of the cosine tables, replaced by the approved-evidence version of the same conclusion. The
  claim that round 2 produced "the first *measured* parameter seeds in the corpus" was the largest single
  piece of drift and is gone.
- Documents table: schema's consumer-filter table and linked sessions; architecture's session-label ladder,
  two precedence ladders and the consolidator model field; retrieval's internal queries; consolidation's
  provisional seeds; write-policy's erasure procedure.
- Open question 5: the round-3 dead-lineage addition to the display half.
- Open questions 1, 2, 3, 4, 6, 7, 8, 9 untouched and open. No D-index line needed changing — no decision
  cell was reworded this round.

### For the user, not for me
1. **A figure was withdrawn, not corrected, and the conclusion it supported changed footing.** Round 2's
   cosine floor-sweep tables are gone from the corpus: they measured whole-record vectors rather than the
   deployed first-chunk-to-best-chunk quantity, and lived only in `/tmp`. `anchor_cutoff` 0.65,
   `orphan_edge_cutoff` 0.65 and `dedup_threshold` 0.80 are now **provisional seeds with no measurement behind
   them**. The product-facing conclusion the user was told about last round — that a high cosine dedup floor
   surfaces near-miss twins rather than duplicates — **survives**, but now rests on the *approved* benchmark
   (near-miss pairs at cosine ≈0.73, margin ≈0.04, DI 0.194–0.233) instead of on the withdrawn probe. Nothing
   about D15's framing changes; what changes is that it is now defensible.
2. **The corrected probe needs someone with write access outside `design/`.** I am scoped to `design/`,
   `FINDINGS.md` and `reviews/`, so I could not persist a replacement. What it needs is stated in
   `consolidation.md`: score the deployed quantity (first chunk → best candidate chunk, same rollup as the
   dense arm), name the populations for what they are (designated twin *pairs*, not "any pair sharing a
   query's confusable"), persist under `experiments/embedder-precision/`, write the result into `research/`.
   Until then three `meta` defaults are unmeasured — which is survivable, since all three are advisory rather
   than automatic, but it should be a known debt rather than a surprise.
3. **One new default was chosen autonomously: the consolidator's model.**
   `.kiro/agents/zikaron-consolidator.json` → `model: claude-sonnet-4.5`, chosen to lean capable rather than
   cheap because consolidation is rare and off the hot path while a bad consolidation durably corrupts a
   long-term record. That is a cost decision as much as a technical one, and the model id must be one the
   installed harness actually accepts — packaging validates it.
4. **A specified-but-unverified mechanism now sits in the architecture.** The `ancestry` step of the
   session-label ladder walks `/proc` to correlate the hook and MCP processes. It is Linux-only, we have not
   observed kiro's process topology, and it fails closed. It earns its place because two of D30's six signals
   are dead without *some* correlation — but it is the one place in the corpus where a mechanism is specified
   ahead of any observation, and the smoke test in open question 4 should cover it.
5. **`event` gained two columns** (`client_kind`, `label_source`) and the two cross-client signals now report
   **link coverage** beside them. If coverage turns out low in practice, the honest read is that D30 measures
   four signals, not six — and that is a better position than reporting six numbers of which two are
   systematically biased toward our own hypothesis.

Knowledge base re-indexed (`zikaron-design`, path `/home/nathan/Zikaron/design`) after the edits.
## Round 4 — 2026-08-01

### Summary judgment

Round 3 resolves ten of its eleven findings and materially improves the corpus: session linkage is now honestly bounded, authorization precedes disclosure, terminal supersession components are coherent, and the config/query/erasure contracts are substantially tighter. Approval is still blocked by six concrete consistency defects: the consolidation state machine has an uncloseable vacated-member path, the orphan cutoff is undefined for an asymmetric scorer, several cosine claims still exceed the approved evidence, degraded retrieval bypasses fatal store states, schema-version compatibility is unsafe, and two fixed event shapes cannot represent behavior the prose requires.

### Round-3 finding disposition

| # | Status | Judgment |
|---|---|---|
| 1 | **Resolved** | The three-step label ladder is explicit, its ancestry step is correctly labelled unverified, and the two cross-client signals are restricted to observably linked sessions with link coverage reported. |
| 2 | **Resolved** | Internal queries now define both dense and lexical arms, and the three mutation-oriented consumers have explicit legality filters. The directional cutoff ambiguity below is a new consequence of the shared first-chunk rollup, not the omitted-query/filter defect from round 3. |
| 3 | **Resolved** | Consolidator run/member/target authorization now precedes existence, version, receipt, and all content-bearing errors; unauthorized payloads disclose UUIDs only. |
| 4 | **Resolved** | Terminal retired components are explicitly legal, the target-state rule is correctly a write-time precondition, and `fetch` reports the resolved root's live/retired state. |
| 5 | **Resolved** | `reindexing` is an exempt sentinel, the literal BGE prefix is present, and the consolidator model has a typed, explicit, no-fallback agent-config location. |
| 6 | **Partially resolved** | The non-durable cutoff tables were correctly withdrawn and the defaults are now labelled provisional, but the replacement prose still draws duplicate/twin threshold conclusions the approved benchmark did not measure. See finding 3. |
| 7 | **Resolved** | Expiry is consistently derived by readers and persisted only by `plan_groups`; rejected expired calls no longer mutate run state. The recovery/terminal-transition gaps below are separate second-order lifecycle defects. |
| 8 | **Resolved** | In-place promotion now emits exactly one `flipped` event; new-row promotion emits one `created` event plus one per absorbed row. |
| 9 | **Resolved** | Recency is conditional on a journal tie block, while long-term ties fall through to UUID; the transitivity argument is sound. |
| 10 | **Resolved** | The lexical constructor now has term-level OR semantics, a deterministic cap, and an honestly bounded Python/SQLite boundary risk. |
| 11 | **Resolved** | D16 is correctly scoped to agent-facing APIs, and the operator erasure procedure covers FTS, vectors, chunks, restricting references, WAL, log residue, and secure-deletion limits. |

### Findings blocking approval

1. **[BLOCKER] Serve-time vacating can leave a logically complete consolidation group permanently uncloseable, and same-owner expiry recovery is not defined.** `design/schema.md`, invariants 16–17, says `vacated` is a disposition but permits `served → complete` only in the write verb that dispositions the last member. `design/architecture.md`, “What serving re-validates,” instead writes `vacated` inside `next_group`. If every member of a pending group has vacated—or the last remaining member vacates before a re-serve—`next_group` leaves zero undispositioned rows but no write verb can run; the group remains `served`, is repeatedly served empty, and eventually becomes `deferred`, contradicting the row-level completion invariant. The same lifecycle says `next_group` replans only when the caller has no active run, treats an active-but-expired run as an error, and explicitly defines implicit takeover only for a *different* session; the owning consolidator is told to call `next_group` again but can receive the same `group_expired` forever unless it can invoke the non-tool `plan_groups` RPC. Resolve both paths in the closed state machine: let the serving transaction transition `pending|served → complete` when vacating exhausts membership (and continue to the next group rather than returning an empty one), with run completion/event behavior specified; and define whether `next_group` treats an effectively expired run as absent and replans for **any** caller, or expose a reachable explicit reset/replan action.

2. **[BLOCKER] `orphan_edge_cutoff` is undefined because the deployed memory-to-memory score is directional.** `design/schema.md`, §“`meta`,” defines a cutoff score as the querying memory's **first chunk** against the best of any candidate chunk. In general `s(A→B) ≠ s(B→A)`. `design/consolidation.md`, mechanism step 2, correctly requires both mutual top-K directions but then adds only `cos(A, B) ≥ orphan_edge_cutoff`, using symmetric notation without saying which directed score—or what aggregation—must pass. This changes graph edges and therefore groups across implementations. Define the edge with the actual directed primitive, for example `s(A→B) ≥ t AND s(B→A) ≥ t`, or specify a deterministic symmetric aggregate such as `min(s(A→B), s(B→A))`; use that same definition in the cohesion pass, schema note, and acceptance tests.

3. **[BLOCKER] Round 3 withdrew the bad cutoff evidence but retained conclusions that the approved benchmark cannot support.** `design/architecture.md`, `zikaron_remember`, still says pairs above `dedup_threshold=0.80` are “dominated by near-miss twins.” `design/consolidation.md`, “Why not cosine alone” and “Where the three cosine seeds come from,” says raising a cosine threshold makes the twin failure more likely and that any interesting floor admits twins; `design/overview.md` D15 and `FINDINGS.md`, “Current state,” conclude that **no cosine floor can separate a duplicate from a twin**. The approved `research/embedder-benchmark-results.md`, §7, measured controlled near-miss identifier passages at cosine about 0.73 with a thin ≈0.04 margin; it did not measure a duplicate population or the population above the deployed 0.80 threshold. A threshold above a measured twin's score excludes it, so the monotone “raising makes it worse” claim also does not follow. There is a second internal contradiction in `design/consolidation.md`: mechanism step 1 says the lexical arm “keeps a `WidgetV1` entry off a `WidgetV2` record,” while “Why not cosine alone” correctly says whether BM25 compensates for this failure is untested. Resolve by removing the population/threshold/duplicate-separation claims and narrowing to what is supported: the controlled twins are highly similar with thin dense margins, so cosine alone is unsafe as an assertion and hand-backs remain candidates for agent judgment. Alternatively, persist a deployed-scorer study containing accurately defined duplicate and twin populations before restoring the stronger claims.

4. **[BLOCKER] The degraded hook bypasses store states that the schema declares fatal or unavailable.** `design/schema.md`, §“`meta`,” says invalid required configuration is fatal, must never silently fall back to defaults, and returns `bad_config`; invariant 3 says `reindexing` fails reads and no read may see the gap. Yet the same config section says the hook “goes degraded,” and `design/architecture.md`, “Degraded modes,” falls back to direct read-only BM25 on **any** RPC failure. That path either has to interpret malformed/missing ranking keys despite the no-default rule, or silently use a different configuration; on `reindexing` it serves a read during the expressly unavailable window. Classify failures before fallback. At minimum, direct BM25 must independently validate the configuration it consumes and print nothing on `bad_config`; either suppress output on `reindexing` as well, or explicitly permit BM25-only reads during reindex and revise invariant 3/error semantics to say so. Transport/startup/index failures may still use the documented degraded path.

5. **[BLOCKER] A v0 binary is specified to open a future incompatible schema as if it were valid.** `design/schema.md`, §“`meta`,” validates `schema_version` only as integer `≥1` and says unknown keys from a newer writer are retained so a “forward-compatible store” still opens. With no migrations or compatibility negotiation, version 2 therefore passes v0 validation even if its tables or invariants changed; ignoring its unknown keys does not make its schema backward-compatible. Make v0 require `schema_version == 1` and reject greater versions with a stable incompatible-schema error (while still preserving unknown non-structural keys on supported version 1), or define an explicit supported-version range and migration/capability contract. Do not infer schema compatibility from key tolerance.

6. **[BLOCKER] Two supposedly fixed event shapes cannot represent the behavior their surrounding specs require.** First, `design/retrieval.md`, “The dense arm, precisely,” says `search`/`surface_call` report the depth each arm actually reached, but `design/schema.md`, §“The `event` log, per kind,” gives both events only configured `fusion_depth`; a short/exhausted arm is therefore unobservable. Add explicit `dense_depth_reached` and `lexical_depth_reached` fields (with defined skipped/degraded values), or withdraw that instrumentation claim. Second, `group_served` is one event per member with a required-looking `version_served`, while serve-time-vacated members are not delivered and `consolidation_group_member.version_served` remains nullable until prose is served. Define whether vacated members emit no `group_served` event, emit a separate event, or emit `version_served:null` under a cardinality/meaning that no longer claims their prose was delivered. Align the table, serving transaction, and exact event queries.

VERDICT: NEEDS_CHANGES

---

## Response to review round 4

**6 findings, 6 accepted, 0 rejected.** Every one was checked against the source it cites; every one named a
real defect. Where I differed from the suggested remedy — three of the six — that is stated under the finding.

The through-line of this round, since it is different from rounds 2 and 3 and useful for round 5: **round 3's
fixes are correct about the case they were written for and silent about the case that empties it.** A
disposition closes a group — unless the disposition *is* the serve, in which case no write verb runs. Derived
expiry unblocks a stranger — and strands the owner, who has no reachable replan. A fallback covers failure —
including the two failures that are *about the store the fallback reads*. Each is a closure failure rather than
a logic error: the rule is true, and its complement is undefined.

**No user decision (D1–D32) was reversed.** Four *rationales* were corrected — D15, D22, D25, D29 — each
because it asserted more than its mechanism or its evidence supported. **No decision cell was reworded.**

**One figure was withdrawn, and I found the withdrawal has to go further than finding 3 asks.** Detail under
finding 3; the short version is that round 3's replacement figure is not a mis-scoped pair cosine, it is not a
pair cosine at all, and the level quoted is not the deployed model's. That is the item most worth the user's
attention, and it is flagged below.

### 1. [BLOCKER] Serve-time vacating leaves a complete group uncloseable, and same-owner expiry recovery is undefined — ACCEPT, both halves, and I took both of your remedies.

Both defects are real and I reproduced each by tracing the specs rather than assuming.

**(a) The uncloseable group.** Confirmed exactly as stated: `schema.md` invariant 17 gave `served → complete`
one producer, "the write verb that dispositions its last member", while `architecture.md` §"What serving
re-validates" writes `vacated` — a disposition, per invariant 16 — inside `next_group`. So a group whose every
member vacated at serve, or whose last survivor vacated on a re-serve, reached zero undispositioned rows with
no write verb having run. Nothing transitioned it. It stayed `served`, was handed back empty, and burned
re-serves until `max_group_serves` made it `deferred`. Three separate harms, and you named the one that
matters most: it **contradicts invariant 16's own completion condition** — the row-level state says complete
while the group status says open.

The fix is a **closure property** rather than another transition bolted on, because the underlying error was
that the state machine enumerated causes without ever asserting that no state is left without an exit:

> **No committed group is `pending` or `served` with zero undispositioned members.** (`schema.md` invariant 16)

That makes completion have **two producers** — the write verb, and the serve transaction when vacating
dispositions the last member — and I changed invariant 17's headline from "exactly one producer" to "exactly
one named cause", because "one producer" was the assumption that hid this. The transitions are now a table,
and it is exhaustive: `pending → complete` (never delivered, vacated out at serve) and `served → complete`
cause (b) (vacated out on a re-serve) are new rows.

`architecture.md` §Serving is now a **bounded loop**, which is your "continue to the next group rather than
returning an empty one": for each candidate group it applies serve-time re-validation, and if that leaves zero
undispositioned members it closes the group `complete` in the same transaction and moves to the next
candidate. Bounded by the group count, fixed at plan time. Run and event behaviour is specified rather than
left open, as you asked: a group closed by vacating alone emits **no `group_served` events** (nothing was
delivered — see finding 6), does **not** increment `serve_count` (it was not served), and if it was the run's
last open group the run goes `active → complete` in that transaction and the call returns `{done: true}`. So a
run whose entire remainder vacated out finishes cleanly in one call instead of after three empty serves per
group.

**(b) Same-owner expiry recovery.** Also confirmed, and the dead end is exactly as you traced it: `next_group`
replans only when the caller has no active run; an owner past its lease finds its *own* `active` row, is served
a group from it, and is rejected `group_expired`; the documented recovery is "call `next_group` again", which
returns the same rejection forever; and `plan_groups` is a service RPC, **not** one of D32's four consolidator
tools, so the owner cannot escape. Worth noting this was *created* by round 3's fix — deriving expiry on the
read side is right, and round 3 wrote only the half that unblocks a stranger.

I took your **first** option — `next_group` treats an effectively expired run as absent and replans for **any**
caller — over exposing a reset action, and the reason is that the alternative adds a fifth consolidator tool to
a set D32 deliberately holds at four, to solve a problem that disappears if the run test is stated once and
applied uniformly. So:

- **"Effectively active" is now the only run test in the corpus:** `status='active' AND expires_at ≥ now`. A
  stored `'active'` row past its lease constrains nobody, *including its owner*.
- `next_group` finding no effectively-active run — none at all, or only a lapsed row, whoever owns it — calls
  `plan_groups()` implicitly. **Crash takeover and same-owner lease recovery are now one code path**, which is
  the outcome worth having: round 3 had them as two rules, one of which did not exist.
- Only an `active` **and unexpired** run of a *different* session yields `{busy: true}`, and an explicit
  `plan_groups()` in that situation returns the same shape rather than stealing.
- I closed an ambiguity you did not name while I was in there: `'expired'` and `'abandoned'` had overlapping
  producers ("expired only by a later `plan_groups`" versus "abandoned when the owning session replans").
  `plan_groups` now closes any pre-existing `active` run and **the lease decides which status it writes** —
  `'expired'` if lapsed, `'abandoned'` otherwise. One producer, one test.
- What the owner loses is stated rather than implied: the group it held. Members return to the next plan (D29's
  guard), the group ids are dead, and a consolidator making progress never gets here because every successful
  call refreshes the lease.

Also updated: invariant 15 now says "one *effectively-active* run", since `status='active'` alone was the
predicate that made the owner's row look binding.

### 2. [BLOCKER] `orphan_edge_cutoff` is undefined because the deployed score is directional — ACCEPT.

Correct, and the asymmetry is structural rather than incidental, which is why `cos(A, B)` could never have been
made to work by convention: `schema.md` defines the quantity as the querying memory's **first chunk** against
the candidate's **best of any chunk**, so X contributes one vector and Y contributes a maximum over many.
Whenever two memories have different chunk counts the two directions differ, and two conforming
implementations would compute different edges, different components, different groups — a silent divergence in
what the consolidator is asked.

I took your first option and named the aggregate too, since they are the same thing:

- **`s(X → Y)`** is now defined once, in `schema.md` §`meta`, as the directed primitive, with an explicit note
  that it is not symmetric and why.
- **A per-cutoff direction table** replaces the single shared definition, because the fix is not only about the
  orphan edge: `anchor_cutoff` takes `s(entry → record)` and `dedup_threshold` takes
  `s(new row → candidate)`. Both are directional *by construction* — an entry looks for a record to attach to,
  a new row asks what it may duplicate — so neither needs symmetrizing, and saying so is what makes the orphan
  edge's symmetrization a considered choice rather than an inconsistency.
- **The orphan edge is `s(A → B) ≥ t AND s(B → A) ≥ t`, equivalently `min(s(A→B), s(B→A)) ≥ t`**, stated both
  ways so no implementation has to derive the equivalence. `min` over `max` or a mean because the edge test
  already demands agreement from both endpoints via mutual-K, and because `consolidation.md` step 2 argues
  explicitly that over-splitting costs one call while under-splitting manufactures a false record — so the
  conservative aggregate is the one consistent with the surrounding design.
- **The cohesion pass consumes this same edge relation and computes no score**, stated in both documents, so
  there is one definition rather than two that must be kept in step.
- **Acceptance test added** beside the A↔B↔C chain case: a pair with `s(A → B) ≥ cutoff > s(B → A)` must produce
  no edge and must not be grouped.
- Propagated to `schema.md` §`meta` (primitive, direction table, and the three `meta` rows), `consolidation.md`
  steps 1 and 2, `retrieval.md` §"The dense arm, precisely", and D29's rationale.

### 3. [BLOCKER] Round 3 withdrew the bad evidence but kept conclusions the benchmark cannot support — ACCEPT, second option, and the estimand is wrong in a way the finding understates.

Every claim you list is unsupported and all are gone. But I checked the figure against the instrument rather
than against the report's prose, and the defect is one level deeper than "did not measure a duplicate
population or the population above 0.80":

**`≈0.73` is not a memory-to-memory cosine at all.** `experiments/embedder-precision/twin_counterfactual.py`
computes `sg, sf = qv[i] @ g, qv[i] @ f` where `qv` is the embedding of a **probe query** — a bare identifier
token, or the carrier sentence `"Tell me about {token}."` — and `g`/`f` are the gold and foil **passages**. The
margin is a difference of two **query→passage** cosines, and the "absolute cosines ~0.73" in §7 is
`mean_cos_gold`, the level of that query→passage similarity. The instrument therefore never scores a twin
*pair* against each other in any direction. So it does not locate twins on the `s(X → Y)` axis that
`dedup_threshold` and `orphan_edge_cutoff` threshold — not mis-scoped, absent.

**And `0.73` is not the deployed model's number.** From the persisted result, `mean_cos_gold` by model and
probe: bge-small **0.7795 / 0.8026**, bge-small-**prefix** (the deployed artifact, D20) **0.7867 / 0.7626**,
bge-large-prefix **0.7385 / 0.7214**, nomic **0.7415 / 0.7871**. `≈0.73` is the bge-large/nomic level. Round 3
quoted a non-deployed model's level to justify a deployed threshold.

**Your monotonicity point is right and I state it as its own error**, because it holds independently of the
estimand: a floor *above* a pair's score excludes that pair, so a level alone cannot establish which way moving
the floor trades duplicates against twins. That needs a distribution over both populations. Nothing in the
corpus has one.

I took your **second** option — remove the population/threshold/separation claims, narrow to what is supported
— and the reason is again partly a hard constraint: this remediation may write only under `design/`,
`FINDINGS.md` and `reviews/`, so I cannot persist a probe under `experiments/` or a result under `research/`.
A `/tmp` probe would reproduce round 3's exact defect. Flagged for the parent below.

**The narrowed form, used verbatim-in-substance at every site.** What the instrument establishes is about the
**signal**, not any threshold: with topic held constant, a near-miss identifier buys about a fifth of the
separation the same model gets from a plainly distinct token — discrimination index **0.194–0.233** for all four
models, direction right in 14/14 blocks (p ≈ 1.2 × 10⁻⁴), margin thin, and the report's own reading is that
"any competing signal overturns it". So a `WidgetV1`/`WidgetV2` pair is precisely where the dense score has
least to work with, and **cosine cannot be *asserted* to separate a duplicate from a twin** — stated as the
absence of a licence to assert, not as a proven impossibility, which is the distinction round 3 lost. D15's
hand-back is therefore candidates to compare. The decision is untouched; only its warrant changed.

Changed by site:

- `architecture.md` `zikaron_remember`: the "pairs above this cosine are dominated by near-miss twins" sentence
  is **removed** and replaced by the signal argument, with the misread named so it is not reinstated. Also now
  states the threshold as `s(new row → candidate) ≥ dedup_threshold` (finding 2).
- `consolidation.md` §"Why not cosine alone": rewritten. The monotone "raising makes it worse" claim and the
  "twin pair already sits at 0.73" premise are gone, with all three errors listed — wrong estimand, wrong
  model, invalid inference.
- `consolidation.md` §"Where the three cosine seeds come from", `dedup_threshold` bullet: rewritten to separate
  the measured *signal* from the unmeasured *value*, and to say plainly that nothing says which way moving the
  floor trades duplicates against twins.
- `consolidation.md` §"What it would take to call any of these measured": now requires the populations to be
  **designated duplicate pairs and designated twin pairs**, requires `min`-symmetrization where the relation is
  undirected, and records that **two consecutive rounds failed on the estimand rather than the statistics** —
  round 3 on the rollup, round 4 on a query→passage cosine read as a pair cosine — so naming the estimand is
  step one of that probe.
- `schema.md` §`meta`: a new paragraph states, where a threshold-picker would look, that nothing locates any
  pair population on the `s` axis in either direction.
- `retrieval.md` §"The identifier weakness is real and unremedied": now records **what the instrument scores** —
  probe query against two passages, a query-to-document contrast, levels 0.72–0.85 and 0.76–0.79 for the
  deployed artifact — so the corpus holds the estimand at its canonical site and the misread has a fixed
  address.
- `overview.md` D15 and D29, and `FINDINGS.md` current state: narrowed to the same form.

**The second internal contradiction — ACCEPT, and the resolution is not simply to hedge.** You are right that
step 1 said the lexical arm "keeps a `WidgetV1` entry off a `WidgetV2` record" while §"Why not cosine alone"
said BM25 compensation is untested. But the two halves are not both empirical, and collapsing them to
"untested" would have thrown away something checkable. Step 1 now states them separately:

- **Mechanically**, `unicode61` makes `WidgetV1` and `WidgetV2` two distinct single terms, so a query term for
  one does not match the other *at all*. That is a tokenizer property — checkable, not measured — and the
  lexical arm is the only component in the system that can make the distinction cheaply.
- **Untested** is whether that rescues the *fused* result: the instrument had no lexical arm, the blind set's
  `near_miss` category is saturated at 0.9881 for lexical, dense and hybrid alike so it separates nothing, and
  §"The known defect in this design" measures fusion as decided by arm agreement with 960/960 top-5 slots held
  by documents both arms returned.
- So the claim is "the lexical arm is the only thing that *can* discriminate here, and whether it does so
  through the fusion is untested." Propagated to §"Why not cosine alone".

### 4. [BLOCKER] The degraded hook bypasses store states the schema declares fatal or unavailable — ACCEPT, and I took the stricter side of both options you offered.

Correct on both paths, and the `bad_config` case is the sharper of the two because it is self-defeating: the
degraded path reads `fusion_depth`, `supersession_penalty`, `retired_penalty` and `fts_query_max_terms` — the
same keys the error declares unusable — so it could only proceed by re-deriving them, which is the silent
default `schema.md` forbids, or by ranking on whatever parsed, which is the "two deployments ranking
differently while both look healthy" failure the fatal rule exists to prevent. Round 3's "the hook goes
degraded" sentence sat directly under the paragraph that forbids it.

`architecture.md` §"Degraded modes" is now an **ordered classification** rather than a catch-all:

1. `surface` succeeds → print.
2. `−32023 bad_config` → **print nothing, stop.** No fallback.
3. `−32022 reindexing` → **print nothing, stop.** No fallback.
4. Everything else — `ENOENT`, `ECONNREFUSED`, spawn failure, `health()` never ready, the internal deadline, a
   `store_identity` mismatch, `store_busy`, unexpected — → fall back.
5. **Before reading, the fallback validates.** It runs the same required-key validation as store open
   (present, parseable, in range, `schema_version == 1`) and checks the `reindexing` sentinel itself, on its own
   read-only connection. Any failure prints nothing.

Step 5 is your "must independently validate the configuration it consumes", and it is load-bearing beyond the
`bad_config` code: in branch 4 the service may **never have started**, so nothing validated anything, and
round 3's draft was silently relying on a validation that had not run.

On `reindexing` you offered suppression *or* permitting BM25-only with a revised invariant 3. **I chose
suppression**, and recorded why rather than just picking: permitting is tempting because v0's only reindex
trigger rebuilds the dense side while FTS5 stays intact, so a lexical read would in fact be correct — but
nothing in the store records *which* indexes a given reindex is rebuilding, so the permission could not be
checked, only assumed, and invariant 3's guarantee would become conditional on a fact no reader can verify.
Suppression costs a quiet hook during a rare operator-triggered window.

Propagated: `schema.md` §`meta` (the false "the hook goes degraded" sentence replaced with the reason it cannot
be true), invariant 3 (now says "no read" includes the degraded path, and carries the rejected alternative),
the `reindexing` sentinel paragraph (every direct reader checks it), `retrieval.md` §"Degraded retrieval",
the error table (`−32022`/`−32023` marked as suppressing rather than triggering the fallback), D22's rationale,
and both honest-limit paragraphs on the session denominator (`schema.md`, `write-policy.md`), which are now
conditional on the service being reachable **and healthy**.

### 5. [BLOCKER] A v0 binary is specified to open a future incompatible schema — ACCEPT, first option.

Correct, and the sentence that produced it — "unknown keys are retained so a forward-compatible store still
opens" — was doing exactly what you say: **inferring schema compatibility from key tolerance.** An unknown key
says nothing about whether the tables, indexes, invariants, or the *meaning of the existing keys* changed under
a newer writer. With no migrations and no negotiation, `schema_version = 2` passed a `≥1` range check and the
binary would have read an unknown schema as if it were its own.

- **v0 requires `schema_version == 1`.** The `meta` table row now reads "exactly `1` in v0".
- **A new stable error, `−32024 schema_incompatible`**, with `{found, supported: 1}`, and it is deliberately
  *not* `bad_config`: the value is well-formed and uncorrupt, it simply describes a schema this binary does not
  know, and an operator or a newer client should be able to branch on that difference. `< 1` or unparseable
  stays `bad_config` by the ordinary range rule.
- **Unknown-key tolerance is kept and explicitly scoped** to supported versions, with the reason it is not a
  compatibility claim stated inline so it is not re-read as one.
- **§"Migration posture" is rewritten** into a three-row table of what v0 does with each version found, plus
  the statement that the first release needing more than one schema gets an explicit supported range plus a
  migration or capability contract — written then, not implied now.
- The hook's degraded path checks the version too, via the shared validation in finding 4 step 5.

### 6. [BLOCKER] Two fixed event shapes cannot represent the behaviour their specs require — ACCEPT, both.

**(a) Depth reached.** Confirmed: `retrieval.md` said both arms report the depth actually reached while
`schema.md` gave `search` and `surface_call` only the *configured* `fusion_depth`, so a short or exhausted arm
was exactly as unobservable as before the claim was made. I added the fields rather than withdrawing the
claim, because the claim is the only thing that makes the overfetch loop's behaviour checkable in production.

- **`dense_depth_reached`** and **`lexical_depth_reached`** on both event kinds, each the count of **distinct
  eligible memories that arm produced** — the quantity `fusion_depth` actually bounds, counted after the
  eligibility join and the consumer filter, before fusion. So `< fusion_depth` means the arm exhausted and
  `== fusion_depth` means it was cut by the bound.
- **Null has one defined meaning per field**, which is your "defined skipped/degraded values":
  `lexical_depth_reached` is null **iff `lexical_skipped`** (zero surviving terms, the arm never ran);
  `dense_depth_reached` is null iff the dense arm never ran, which on the service path is unreachable in v0 — so
  that null is stated as reserved rather than left looking live. The degraded BM25-only path needs no value
  because it emits no events at all (read-only store).
- `retrieval.md` now names both fields where it makes the claim.

**(b) `group_served` versus vacated members.** Confirmed, and the ambiguity was worse than a nullable column:
the cardinality said "one per member" while vacated members are not delivered, and `version_served` looked
required while the member row's own `version_served` stays NULL.

I chose your **first** option — vacated members emit **no** `group_served` — over a separate event or a null
version, because it makes the event mean one thing: *this row's prose was delivered on this serve*. With that,
`version_served` in the detail is **NOT NULL** and honest, and I removed the `vacated` field from the detail,
which under this rule would always be false.

- **Cardinality is now: one row per row this serve actually delivered** — per delivered journal member, per
  candidate, and one for the anchor *when an anchor was delivered*. A vacated member emits none; a vacated
  anchor emits none.
- **Vacating is not thereby unobservable**, which is the objection to suppressing it: it is written to
  `consolidation_group_member.disposition='vacated'` with `disposed_at`, which is durable, authoritative and
  queryable, and none of D30's six signals counts it. Stated explicitly so the choice reads as a placement
  decision rather than a loss.
- **The two vacated states are distinguished**, which the round-3 text could not express:
  `version_served IS NULL AND disposition='vacated'` = never delivered; `version_served IS NOT NULL AND
  disposition='vacated'` = delivered on an earlier serve, vacated on a later one. So
  `version_served IS NULL` **iff** never delivered, and there is exactly one `group_served` event per
  (serve, delivered row) pair.
- Aligned across all three places you named: the event table and its new named rule (`schema.md`), the column
  comments on `consolidation_group_member`, and the serving transaction (`architecture.md` §"What serving
  re-validates" and §Serving, which also states that a vacated-out group emits no `group_served` and does not
  increment `serve_count`).

### Additional defects found while remediating round 4, fixed and reported

- **`0.73` was not the deployed model's figure.** Under finding 3. Reported separately because it is a
  different error from the estimand error and would have survived fixing only the estimand.
- **Invariant 15 made a lapsed lease look binding.** It said "one consolidation run per store, enforced by
  `status='active'` plus the lease", which is the same conflation that stranded the owner in finding 1. Now
  "one *effectively-active* run", with the predicate spelled out.
- **`'expired'` and `'abandoned'` had overlapping producers.** Under finding 1(b). Not raised by the review;
  found while writing the uniform run test.
- **The `group_served` kind comment said "a consolidation group was delivered"**, singular, which contradicted
  the per-row cardinality directly above it in the same file. Now "one per row a consolidation serve actually
  delivered".
- **`design/README.md` had drifted from `overview.md` §5** — same document table, two different summaries, and
  the round count. Both updated.
- **My own first draft of the finding-1 fix left an ordering ambiguity, caught on re-read and fixed.** It said a
  `pending` group is "transitioned `pending → served`" and *then* re-validated, which would have made a
  vacated-out group pass through `served` and increment `serve_count` — contradicting the same paragraph's rule
  that it does not. The order is now explicit in both documents: **re-validate first, commit the serve second**,
  so a group with nothing left to deliver goes `pending → complete` directly, never counts as served, and never
  spends a re-serve. Reported because it is exactly the class of defect this round was about — a rule stated
  correctly in one sentence and contradicted by the sequence in another.

### `FINDINGS.md`
Edited only where it had drifted from `design/`, per the standing constraint — no restructuring, no rationale
moved back:
- Current-state paragraph: four rounds; round 4's six blockers with the three worth carrying (a disposition is
  not always a write; derived expiry has two sides; a fallback can be a bypass); and the withdrawal of round 3's
  substituted figure with the estimand correction and the lesson — **name the quantity before quoting a number
  about it.**
- The `≈0.73` / "no cosine floor can separate" claim removed from the current-state paragraph, matching D15.
- Open questions unchanged: none of the six findings closes one, and none opens one.

### For the parent, and for the user

1. **The corrected-probe gap is now two rounds old and cannot be closed from inside this scope.** Rounds 3 and 4
   both had to withdraw a figure because it measured the wrong quantity, and both times the offered remedy —
   persist a probe scoring `s(X → Y)` over designated duplicate and twin pair populations — is out of this
   remediation's write scope (`experiments/`, `research/`). The requirements are written down in
   `consolidation.md` §"What it would take to call any of these measured". Until someone runs it,
   `anchor_cutoff`, `orphan_edge_cutoff` and `dedup_threshold` are buildable seeds with no measurement behind
   them, which the corpus now says in four places.
2. **The instrument's estimand is worth the user's attention on its own.** The counterfactual identifier
   instrument measures a **query→document** contrast. It is excellent evidence for what it measures — the push
   and pull paths *are* query→document — and it is not evidence about memory-to-memory similarity, which is what
   dedup and orphan clustering compute. Any future claim about a cutoff has to come from a different
   measurement, and the corpus should keep those two axes apart by name.
3. **One consolidator-facing behaviour changed shape, though no tool did.** `next_group` is now a loop that may
   close several groups before returning, and it replans an effectively-expired run for its owner. No signature
   changed and D32 still holds four tools, but the skill's expectations should match: a single `next_group` call
   can legitimately return `{done: true}` immediately after closing several vacated-out groups.
4. **`−32024 schema_incompatible` is a new error code**, in the same application range. Nothing else was added
   to the error table.

Knowledge base re-indexed (`zikaron-design`, path `/home/nathan/Zikaron/design`) after the edits.

## Round 5 — 2026-08-01

### Summary judgment

Round 4 resolves all six findings it targeted: vacated groups now close, expired owners can replan, the orphan score is directional and symmetrized, cutoff claims are narrowed, fatal store states suppress degraded reads, schema compatibility is gated, and the event shapes now carry the promised data. The corpus is still not buildable without guessing, however: the remediation leaves shard cardinality unpersisted, gives `serve_count` two meanings, mislabels a bounded KNN stop as exhaustion, and retains contradictory fetch and session-registration contracts. One consolidation rationale also re-widens the approved identifier evidence into an exclusivity claim the experiment directly does not establish.

### Round-4 finding disposition

| # | Status | Judgment |
|---|---|---|
| 1 | **Resolved** | Serving now closes a group transactionally when vacating exhausts its members, skips empty groups in a bounded loop, and treats an effectively expired run as absent for every caller, including its owner. |
| 2 | **Resolved** | `s(X → Y)` is defined as directional; orphan edges use `min(s(A→B), s(B→A))`, and the cohesion pass consumes that exact relation. |
| 3 | **Resolved** | The unsupported duplicate/twin threshold and monotonicity claims are gone. The surviving language correctly distinguishes the measured query→passage discrimination signal from unmeasured memory-pair cutoff populations. |
| 4 | **Resolved** | `bad_config`, `schema_incompatible`, and `reindexing` suppress output; every direct fallback reader independently validates required configuration and the sentinel before querying. |
| 5 | **Resolved** | v0 requires `schema_version == 1`, rejects newer schemas with `schema_incompatible`, and limits unknown-key tolerance to supported versions. |
| 6 | **Resolved** | Both retrieval events now carry actual per-arm depths with null semantics, and `group_served` is emitted only for rows whose prose was delivered at a non-null version. |

### Findings blocking approval

1. **[BLOCKER] The persisted group schema cannot reproduce the required `shard: {index, of}` payload after restart.** `design/consolidation.md`, mechanism step 4, requires every shard to carry both its index and total shard count; `design/architecture.md`, `zikaron_next_group`, exposes that object; and the lifecycle promises restart recovery entirely from persisted state. But `design/schema.md`, `consolidation_group`, stores only `shard_index`, not `of`/`shard_count` (nor another persisted partition identity from which it can be recovered). Recomputing the original cohesive subgroup from the current store would violate frozen membership and can change after earlier groups mutate the store. Persist `shard_count` (and define whether indices are zero- or one-based) when planning, with consistency checks such as `1 ≤ shard_index ≤ shard_count` or the zero-based equivalent; return the persisted values on every serve.

2. **[BLOCKER] The dense arm can stop without exhausting the index, while the fixed event contract says every short depth means exhaustion.** `design/retrieval.md`, “The dense arm, precisely,” stops after at most four doublings even if `n` is still below the chunk count. On a large store whose first probes are dominated by chunks from a few memories or by ineligible rows, it can therefore return fewer than `fusion_depth` memories while eligible memories remain outside the probe. `design/schema.md`, “The event log, per kind,” nevertheless says `depth_reached < fusion_depth` is *exactly* exhaustion and `== fusion_depth` means the arm was cut by the bound; neither implication follows (an exact-depth exhausted index also falsifies the latter). Either continue until `fusion_depth` distinct memories or actual index exhaustion, or retain the safety cap and add an explicit terminal reason such as `depth_reached | index_exhausted | probe_cap_hit`; define the event semantics from that reason rather than inferring termination from the count.

3. **[BLOCKER] `fetch` is simultaneously specified as partial and all-or-nothing.** `design/architecture.md`, `zikaron_fetch`, deliberately returns found records plus unknown UUIDs in `missing`, saying a partial answer is more useful than failing the batch. But `design/schema.md`, §Bounds, says the 1–50 UUID fetch batch is “all-or-nothing,” and `design/architecture.md`, “What a rejected call does and does not change,” says “Batches and multi-row mutations are all-or-nothing.” These contracts produce different responses for `[known, unknown]`. Keep the explicit partial-fetch behavior and scope all-or-nothing to **mutating** batches (and any read batch that truly rejects as a unit), or change the fetch signature and error behavior consistently everywhere.

4. **[BLOCKER] `serve_count` has incompatible increment and deferral semantics.** `design/schema.md` initializes it to 0 and comments that it bounds **re-serving**; `design/consolidation.md` defines `max_group_serves` as how many times an incomplete group is **re-served**; but the `meta` table says an incomplete group is deferred after that many **serves**. More importantly, `design/architecture.md`, “Serving,” explicitly increments the counter for `served → served` but does not increment it for the initial `pending → served`, while the new vacated-group text argues that a vacated-out attempt does not increment because “nothing was served,” implying an ordinary first delivery should. At the default 3, conforming implementations can therefore allow either three total deliveries or one initial delivery plus three re-serves. Choose one quantity and encode it everywhere: for example, count every successful delivery (`pending → served` sets 1, each re-serve increments, defer before a delivery when count is already 3), or rename it `re_serve_count` and make the initial delivery explicitly remain 0. Align the transition table, event payload, column comment, parameter name/note, and deferral test.

5. **[BLOCKER] The ancestry-link registration mechanism contradicts the hook lifecycle and leaves its race behavior unspecified.** `design/architecture.md`, “Both clients must resolve the same label,” says the `agentSpawn` hook registers `{session_id, ppids}` **with the service** so a later MCP request can match it. The same document’s “Warming” section says the `agentSpawn` path prints static text with **no RPC** and only fires a detached start-if-absent. Those cannot both be the executable contract, especially when the service was absent: it is unclear which process sends the registration, after what readiness condition, whether it retries, and what happens if MCP’s first call arrives first and permanently adopts a minted label. Specify the non-blocking registration path precisely—e.g. a detached helper starts/awaits health and calls a named registration RPC, with hook requests refreshing the registration—and define the race outcome. The mechanism may remain unverified and fail closed as disclosed; it may not depend on an RPC one lifecycle section says never occurs.

6. **[BLOCKER] The round-4 evidence narrowing is re-widened into the false claim that the lexical arm is the only discriminator.** `design/consolidation.md`, mechanism step 1 and “Why not cosine alone,” says the lexical arm is “the only thing/component that can discriminate” `WidgetV1` from `WidgetV2`. The same passages cite a dense discrimination index of 0.194–0.233 with the correct direction in 14/14 blocks, while `design/retrieval.md`, “The identifier weakness,” correctly says the dense signal is weak—not absent—and that the experiment tested no lexical arm, so whether BM25 compensates is untested. The tokenizer fact proves only that the two identifiers are distinct lexical terms; it does not prove exclusivity, nor that the full BM25 query ranks the right record after all shared terms contribute. Replace the exclusivity language with the supported statement: lexical matching supplies an exact-token signal independent of the weak dense signal, but whether that signal changes the fused result is unmeasured. No new benchmark is required.

VERDICT: NEEDS_CHANGES

## Response to review round 5

**6 findings, 6 accepted, 0 rejected.** Every one was checked against the source it cites; every one named a
real defect, and in four cases the defect was worse or wider than the finding claimed.

The through-line of this round: **round 4's fixes each introduced one unpersisted or ambiguously-named
quantity.** A shard learned to report `{index, of}` without `of` being stored. A depth field learned to report
how far an arm got without recording *why it stopped*. A counter learned to bound re-serving without anybody
saying whether the first serve counts. A registration learned to exist without a sender. Every one is the same
class: round 4 specified the *observable* and left the *state behind it* to be inferred. Inference is exactly
what a second implementer gets wrong.

**No user decision (D1–D32) was reversed.** One *rationale* was corrected — D27, whose "`agentSpawn`-registered
process-ancestry match" named no sender and implied a process the lifecycle says makes no RPC. **No decision
cell was reworded.** Nothing an earlier round accepted was regressed; two round-4 fixes were extended
(the serving loop, the per-arm depth fields) and neither was undone.

**Two things I fixed that this round did not ask for**, both found while checking its citations, and both
contradictions of a round-4 remediation the reviewer had marked resolved:

- §"Service RPC surface" still said `plan_groups` is called by `next_group` "when no active run exists **for
  the calling session**" — the exact wording round 4's blocker 1(b) replaced, because it is what stranded the
  owner of a lapsed lease. Now: no *effectively-active* run at all, whoever owns it.
- Error `−32015 group_deferred` read as though `next_group` could return it. Under the round-4 serving loop it
  cannot: the loop marks the group `deferred` and moves on. The row now names the write verb as the raiser.

### 1. [BLOCKER] The persisted group schema cannot reproduce `shard: {index, of}` after restart — ACCEPT

Confirmed, and the derivation you predicted an implementer would reach for is worse than "can change after
earlier groups mutate the store": it is illegal on its face. Reconstructing `of` means recomputing the cohesive
subgroup, and membership is *frozen at plan time* — the premise invariant 16's completeness condition rests
on. So the only available derivation contradicts the invariant it would serve.

I also found the finding understates the problem by one field. There **is** a latent persisted partition
identity — `order_key`, if it is the *pre-shard subgroup's* key, since all shards of one subgroup then share it
and cohesive subgroups are disjoint member sets so no two can share a minimum uuid. But the corpus never said
which set `order_key` is computed over, and the other reading (the shard's own members) makes it distinct per
shard, which makes `shard_index` dead weight as step 3's third sort component while *also* destroying the only
derivation of `of`. One unstated choice was silently load-bearing for two mechanisms.

Changed:

- `schema.md` `consolidation_group`: added `shard_count INTEGER NOT NULL DEFAULT 1`; `shard_index` is now
  **1-based** (`DEFAULT 1`) with `CHECK (shard_count >= 1)` and `CHECK (shard_index BETWEEN 1 AND shard_count)`.
  An unsplit group is `{index: 1, of: 1}` — I dropped the old `DEFAULT 0` / ">0 when split" convention rather
  than keep a third meaning for zero.
- `schema.md`: `order_key`'s comment now pins it to the **pre-shard** subgroup, and says why — that is what
  makes `shard_index` the load-bearing tiebreak between siblings.
- `schema.md`: a block comment after the table states that both halves are written at plan time and returned
  verbatim, and why recomputation is illegal.
- `schema.md` **invariant 19** (new): the set-level condition — for the rows of a run sharing an `order_key`,
  all carry the same `shard_count = N`, the `shard_index` multiset is exactly `{1..N}`, and `N` equals the
  cardinality of the set. It also says the count is *asserted*, not used as the source of `of` (a `deferred` or
  `complete` sibling still counts), and that group *status* is deliberately not part of it since shards are
  dispositioned independently. Invariant totals updated to 19 in `design/README.md`, `design/overview.md`
  §5 and `FINDINGS.md`.
- `consolidation.md` step 3: the order key's first two components are computed over the pre-shard subgroup.
- `consolidation.md` step 4: both numbers persisted at plan time, 1-based, and the two reasons `of` cannot be
  recomputed.
- `architecture.md` `zikaron_next_group`: `shard` is read straight out of the persisted row.

### 2. [BLOCKER] A bounded KNN stop is mislabelled as exhaustion — ACCEPT, and I took the second remedy

Confirmed, and both halves of your argument hold. `depth_reached < fusion_depth` conflates two opposite
diagnoses — "the store has no more to give" and "the store may and we stopped looking" — and
`depth_reached == fusion_depth` does not imply the bound cut anything, because a store holding *exactly*
`fusion_depth` eligible memories exhausts at equality. The second is the sharper of the two: it means the
round-4 field was wrong on **both** of its implications, not just the one the finding leads with.

I kept the safety cap and added the terminal reason, rather than removing the cap. The cap is a latency bound
— `fusion_depth × chunk_overfetch × 16`, 6,400 chunks at the defaults — and "continue until `fusion_depth`
distinct memories or actual exhaustion" removes it, which puts an unbounded index walk on the push path D12
runs on every user message. The information the cap costs is recoverable by *naming* it, which is what your
alternative does.

Changed:

- `retrieval.md` overfetch loop: step 4 now assigns `'depth_reached'`, `'index_exhausted'` (`n` ≥ the chunk
  count — the whole index probed) and `'probe_cap_hit'` (the doubling cap ended the loop with the index not
  covered); step 5 gives the lexical arm its two, and states that `'probe_cap_hit'` is unreachable there
  because it has no probe cap.
- `retrieval.md`: a new paragraph on why the cap stays and why labelling it matters — `probe_cap_hit` is a
  **known-incomplete** answer, not an error, and it is the only signal that `chunk_overfetch` is too small for
  a store of long memories, which is the case open question 3 says we cannot yet predict.
- `schema.md` event shapes: `surface_call` and `search` carry `dense_stop_reason` and `lexical_stop_reason`
  alongside the two depths.
- `schema.md`: the depth paragraph is rewritten as **"Termination is recorded, never inferred from that
  count"**, with a value table, an evaluation order (depth first, then coverage, so exactly one applies), and
  null semantics extended to the reasons — `lexical_*` null iff `lexical_skipped`, dense null iff the dense arm
  never ran (reserved, unreachable in v0 on the service path).

### 3. [BLOCKER] `fetch` is simultaneously partial and all-or-nothing — ACCEPT, keeping partial fetch

Confirmed: `[known, unknown]` returns a record plus a `missing` entry under `architecture.md`
§`zikaron_fetch`, and returns an error under `schema.md` §Bounds and §"What a rejected call does and does not
change". I took your first remedy — partial fetch is the deliberate behaviour, it is what tells an agent a
handle is dead, and invariant 9's receipt promise is already scoped to *records returned*.

The distinction that resolves it cleanly is that all-or-nothing was doing two jobs: it is true of the **bounds
check** on a read (0 or >50 uuids rejects whole, returns nothing, mints nothing) and false of the read's
**contents**.

Changed:

- `architecture.md` §"What a rejected call does and does not change": the first bullet now says **mutating**
  batches, and names the three consolidator verbs that validate every row before touching any. A second bullet
  states the read/mutation split explicitly and points at `fetch` as the case the unqualified rule contradicted.
- `schema.md` §Bounds: the `fetch` row now distinguishes the all-or-nothing bound from the partial contents.

### 4. [BLOCKER] `serve_count` has incompatible increment and deferral semantics — ACCEPT, counting deliveries

Confirmed, including the observable consequence: at the default two conforming implementations differ by a
whole delivery. I took your first option — count **every successful delivery** — rather than renaming to
`re_serve_count`, for two reasons. The parameter is already called `max_group_serves`, and the `meta` note
already said "after this many **serves**"; and the round-4 vacated-group argument ("nothing was served, so
nothing increments") is only coherent if an ordinary delivery *does* increment. Renaming would have required
changing the user-visible parameter name to preserve the weaker of the two readings.

So: `pending → served` sets 1, each re-serve increments, and a group already at `max_group_serves` is deferred
before any further delivery. Default 3 = three deliveries per run, not four.

Changed, in all six places the finding names plus one it does not:

- `schema.md` column comment: "deliveries of this group in this run, INCLUDING the first; `pending → served`
  sets 1", plus `CHECK (serve_count >= 0)`.
- `schema.md` `meta` note: "maximum **deliveries** of one group per run, counting the first".
- `schema.md` invariant 17 transition table: `pending → served` **sets `serve_count = 1`**; `served → deferred`
  is now stated with its *ordering* — re-validation left ≥1 undispositioned member **and** `serve_count` already
  equals the bound. A following paragraph fixes the counted quantity and says why the other reading permits four.
- `schema.md` `group_served` event detail: `serve_count` is the delivery count **including this delivery**, so a
  first delivery emits 1.
- `architecture.md` §"Serving": rewritten as four ordered steps, with the deferral step made explicit.
- `architecture.md` §"Row-level completion" and the re-serve-bound paragraph: "bounding deliveries", and a
  re-serve attempt that vacates out and closes the group consumes none of the budget.
- `consolidation.md` parameter table: "how many times one group may be **delivered** in a run, counting the
  first".
- Not in the finding, but forced by it: `architecture.md` error `−32015 group_deferred` now names the write verb
  as its raiser and states that `next_group` never returns it.

**One decision inside this that goes beyond the finding: completion beats deferral.** Making the ordering
explicit exposed a case round 4 left open — a group at the serve cap whose last member vacates. Testing the cap
first would defer a group that is actually *finished*, leaving it looking abandoned for the rest of the run and
inflating `consolidate_run.n_deferred`. So re-validation runs first, zero-undispositioned closes `complete` even
at the cap, and only then is the cap tested.

### 5. [BLOCKER] The ancestry-link registration contradicts the hook lifecycle — ACCEPT

Confirmed, and this is the one I would have ranked first. "The `agentSpawn` hook registers `{session_id,
ppids}` with the service" and "the `agentSpawn` path prints static text with no RPC, so it can never fail"
cannot both be executable, and the second is load-bearing: it is why D18's policy injection cannot be broken by
a dead service. There was also no answer to what happens when MCP mints first, and the adopt-and-reuse rule
makes that permanent — so the undefined case was the one that silently costs a linked session.

The reconciliation is that the *hook process* makes no RPC and its *detached child* makes exactly one. That
child already exists for start-if-absent warming; it gains one call.

Changed in `architecture.md` §"Both clients must resolve the same label", now a seven-bullet mechanism:

- **Sender.** The `agentSpawn` hook process reads its own ancestor chain, prints the policy, hands
  `{session_id, ppids}` to the detached warm helper, and exits. The helper does start-if-absent, polls
  `health()` to the same deadline, then calls `register_session`. The chain is passed **as an argument** because
  the helper is spawned `start_new_session=True` and reparented, so its own `/proc` chain is *not* the hook's —
  a detail that would otherwise register a wrong chain and make every match fail.
- **Readiness and retries.** Best-effort and silent: retries only inside the start-if-absent deadline, writes to
  `service.log` not to the hook's stdout, and its failure cannot affect `agentSpawn` output or block the session.
  It is an optimization, not the mechanism the match depends on.
- **The load-bearing path is the refresh.** Every `kind:'hook'` request carries `{session_id, ppids}` and the
  service **upserts** the registration from it, so a session whose helper failed entirely is registered by its
  first successful push. A degraded hook turn registers nothing, because it never reaches the service.
- **`register_session` is a named service RPC**, added to §"Service RPC surface", idempotent per `session_id`,
  in-memory, gone with the service, writing nothing to the store. Its explicit `ppids` **override the
  envelope's** — which is what lets the helper register on the hook's behalf rather than registering itself.
- **Race outcome, defined.** MCP first wins permanently: no match ⇒ `minted` ⇒ adopt-and-reuse for the process
  lifetime, and a later registration does **not** relabel it. The session is unlinked, counted against link
  coverage, excluded from the two cross-client signals. It fails closed — measured unlinked rather than
  silently joined to the wrong session.
- **Retroactive aliasing rejected**, with the reason: it would rewrite `session_id` on committed `event` rows
  and on receipts already minted under the old label — a mutation of an append-only log and of the records D26
  uses to license writes — and it would make link coverage self-repairing, i.e. unable to measure the thing it
  exists for.
- **Why the race should be rare, flagged as an expectation not a guarantee.** Every MCP *tool* call is
  downstream of a user message and `userPromptSubmit` fires before that message is submitted, so a registration
  normally exists before the first tool call even without the helper. That rests on kiro's internal ordering,
  which we have not observed — and the pre-existing "specified but unverified" disclosure is kept.

Also changed: §"Warming" now describes the hook/helper split and states plainly that blurring it was the
contradiction; `overview.md` D27's rationale gains a round-5 correction naming the sender, the refresh path and
the race outcome.

### 6. [BLOCKER] The round-4 narrowing is re-widened into an exclusivity claim — ACCEPT

Confirmed, and you are right about the mechanism of the error: a tokenizer property establishes that the two
identifiers are *distinct terms*, which is a statement about lexical matching, not about everything else. It
cannot establish that nothing else discriminates — and the very figure cited in the same breath says something
else does, weakly: DI 0.194–0.233 with the direction right in 14/14 blocks is a **weak** signal, not an absent
one. `retrieval.md` had it right; `consolidation.md` overstated it. That is the same contradiction-within-the-
corpus round 4 fixed one level up, reappearing as exclusivity instead of certainty.

Your second point is the one I had not seen and it goes further than the first: the tokenizer fact is about a
*term*, while a real lexical query carries every other term the two memories share. Whether BM25 ranks the
right record ahead of its twin — one differing term against many shared ones — is untested independently of
whether RRF preserves it. Two untested links, not one.

Changed:

- `consolidation.md` step 1: the mechanical bullet now says lexical matching supplies **an exact-token signal
  that does not depend on the dense score**; the "what is not established" bullet gains the whole-query gap;
  and the closing bullet states the supported claim and names *both* prior overstatements — asserting the
  outcome ("keeps a `WidgetV1` entry off a `WidgetV2` record"), and asserting exclusivity, which "smuggled back
  in the certainty round 4 removed".
- `consolidation.md` §"Why not cosine alone": the closing paragraph now claims an exact-token signal
  independent of the dense one with the fused outcome unmeasured, and explicitly disclaims both exclusivity and
  a BM25 win once every shared term contributes.
- `overview.md` §provenance: records that round 5 caught the same conclusion being re-widened, this time into
  exclusivity, and what the corpus now claims instead.

### Nothing here needs the user

No finding required reversing a decision, and none required a new measurement. Finding 6 is the second
consecutive round to catch the identifier evidence drifting wider than the instrument supports — round 4 on the
threshold, round 5 on exclusivity — which is worth the parent recording as a pattern rather than an incident:
the underlying temptation is that D29 *wants* a reason to trust the hybrid, and the instrument does not supply
one. The honest position remains that the dense weakness is real and unremedied and the lexical compensation is
untested (`FINDINGS.md` open question 8, `retrieval.md` §"The identifier weakness"). If that gap ever needs
closing it is an experiment, not an edit.

`design/` was re-indexed as `zikaron-design` after these edits.
## Round 6 — 2026-08-01

### Summary judgment

Round 5 resolves the shard, partial-fetch, and delivery-count contracts, and it makes the registration sender and race substantially clearer. Approval is still blocked by three precise inconsistencies: the new stop-reason enum retains the exact-depth false implication it was meant to remove, the ancestry ladder has no implementable first-request handshake, and the cited benchmark report still states the identifier-exclusivity/coin-flip claim the remediation correctly removed from the design documents.

### Round-5 finding disposition

| # | Status | Judgment |
|---|---|---|
| 1 | **Resolved** | `shard_count` is persisted with 1-based bounds, the pre-shard subgroup owns `order_key`, invariant 19 supplies the set-level consistency rule, and `next_group` returns the persisted pair. |
| 2 | **Partially resolved** | The bounded dense stop is now distinguishable from exhaustion, but `depth_reached` is still defined to mean the bound cut the arm even when exactly `fusion_depth` eligible memories exhaust the index. See finding 1. |
| 3 | **Resolved** | Bounds rejection is all-or-nothing while a well-formed `fetch` answers per UUID; the mutation/read distinction is consistent in schema and architecture. |
| 4 | **Resolved** | `serve_count` now counts every delivery including the first, deferral occurs before a fourth delivery at the default, and completion correctly precedes deferral. |
| 5 | **Partially resolved** | The detached helper, named registration RPC, hook-request refresh, and MCP-first race are specified, but the MCP request that is supposed to attempt ancestry cannot be represented under the envelope's missing-label rule. See finding 2. |
| 6 | **Partially resolved** | The design documents now make only the supported independent-exact-token claim, but the cited evidence file still contains the same false exclusivity/coin-flip conclusion. See finding 3. |

### Findings blocking approval

1. **[BLOCKER] The stop-reason contract still misclassifies an index exhausted at exactly `fusion_depth`.** `design/retrieval.md`, “The dense arm's overfetch loop,” step 4, tests `distinct eligible memories ≥ fusion_depth` first and emits `depth_reached`; `design/schema.md`, “Termination is recorded, never inferred,” explicitly preserves that precedence and defines `depth_reached` as “the bound cut the arm and more may exist.” If the full probe contains exactly 50 eligible memories at the default depth, the index is exhausted, no row was cut, and no more result may exist—the exact counterexample round 5 finding 2 identified. The lexical arm has the same equality case. Resolve by classifying from both coverage and cardinality: after a full probe/cursor exhaustion, `count ≤ fusion_depth` is `index_exhausted` (including equality); `count > fusion_depth` is `depth_reached` after cutting; an uncovered probe with at least the target may use `depth_reached`; and an uncovered short probe is `probe_cap_hit`. Specify how lexical retrieval detects exhaustion, such as reading one row past the arm budget or exhausting the cursor. Alternatively, make the reason mean only “target satisfied” and add a separate coverage field, but remove every claim that equality proves a cut or non-exhaustion.

2. **[BLOCKER] The ancestry path has no representable first-request handshake, so two conforming implementations can skip it entirely.** `design/architecture.md`, “Both clients must resolve the same label,” says an MCP client without a harness id sends its ancestor chain on its first call and the service resolves `ancestry` before falling through to `minted`. But the request example requires `client.session_id` and `client.label_source`, and the later live-request rule says a missing or malformed `session_id` causes the service to mint immediately; only a **minted** label is specified as being returned and adopted. Before the match, MCP knows neither the registered hook session id nor that the source is `ancestry`, so it cannot construct the declared envelope; if it omits the id, the explicit missing-id rule bypasses the match. Define an ingress/bootstrap state: for example, MCP may send `{session_id:null, ppids, kind:'mcp'}`; the service first tries the ancestry registry, otherwise mints; it normalizes the request to a non-null `{session_id,label_source}` before any event, receipt, or method execution; and every such response returns the resolved label and source, which MCP adopts whether the result was `ancestry` or `minted`. Distinguish this pre-normalization envelope from invariant 18's non-null “live request,” and state that the service records the source it actually resolved rather than trusting a client assertion.

3. **[BLOCKER] The approved evidence file still makes the exact identifier claim round 5 correctly removed from the design.** `research/embedder-benchmark-results.md`, §7, the paragraph beginning “On ‘mechanistically real but practically moot’,” ends: “the lexical arm is the only thing standing between the agent and a coin flip.” That conflicts with the same section's results—14/14 blocks have the correct dense direction, the null is explicitly **not** a coin flip, and the instrument tested no lexical arm—and with `design/retrieval.md`, “The identifier weakness is real and unremedied,” plus `design/consolidation.md` step 1, which now correctly say lexical compensation is untested and the dense signal is weak rather than absent. Remove or narrow the report sentence to the supported conclusion: the controlled case leaves only a thin dense margin, while whether lexical matching improves the full BM25 ranking or survives fusion is unmeasured. This is evidence fidelity, not a request for a new experiment.

VERDICT: NEEDS_CHANGES

## Response to review round 6

All three blockers **ACCEPTED**. Two are fixed in `design/`; the third is fixed in the corpus and **escalated**
for the one edit that falls outside this remediation's write scope, with replacement text supplied.

---

### 1. [BLOCKER] The stop-reason contract still misclassifies an index exhausted at exactly `fusion_depth` — **ACCEPT**

The reviewer is right, and right about *why*: round 5 replaced an inference with an enum but left the arm's
**stop test** at `≥ fusion_depth`, so the classifier never observed the fact it claimed. An index holding
exactly 50 eligible memories satisfied the test, emitted `depth_reached`, and thereby asserted "the bound cut
the arm and more may exist" in the one case where the arm had returned everything there is. `schema.md` had
even *diagnosed* the equality case in prose ("a store holding exactly `fusion_depth` eligible memories exhausts
at equality") and then preserved the precedence that produces it — a contradiction inside one section.

Of the reviewer's two offered remedies I took the first (classify from coverage *and* cardinality) and
implemented it by fixing the **estimand** rather than the label: each arm now probes for **one more distinct
eligible memory than it will keep**. That makes a cut an *observed surplus* instead of an inference from
equality, which also removes the reviewer's separate worry that a reason meaning "target satisfied" would still
need a companion coverage field.

**`design/retrieval.md` §"The dense arm's overfetch loop, and the three ways it can stop"** — rewritten:
- New opening paragraph: probe target is `fusion_depth + 1`; the surplus row is a termination diagnostic and is
  **never fused**, so RRF still sees the benchmarked depth-50 pipeline.
- Step 3 now names `c` (distinct eligible memories) and `covered` (`n ≥ chunk_count`), and requires
  `chunk_count` to be read **inside the probe's own read transaction** — otherwise a concurrent write moves the
  denominator under the comparison.
- Step 4's loop condition: stop on `c > fusion_depth`, **or** covered, **or** 4 doublings spent.
- Step 5 is a three-row classification table: `c > fusion_depth` → `depth_reached` (surplus *proves* a cut,
  covered or not); `c ≤ fusion_depth` **and** covered → `index_exhausted`, **equality included**;
  `c ≤ fusion_depth` and not covered → `probe_cap_hit`.
- Step 6 answers the reviewer's explicit request to specify **lexical exhaustion detection**. Because D28 leaves
  FTS5 unchunked, one FTS row is one memory, so the whole arm is a single statement — `MATCH` joined to
  `memory`, eligibility and consumer filter in the `WHERE`, `ORDER BY bm25(...)`, `LIMIT fusion_depth + 1`.
  Returning the limit is a proven cut; returning fewer is a proven end-of-cursor, **equality included**. Those
  two outcomes are exhaustive, so `probe_cap_hit` is unreachable there *as a consequence of having no cap*,
  not as an assumption. The cost is stated rather than hidden: a query matching many rows of which few are
  eligible makes the planner walk the match set — bounded by the match set, not by the store.

**`design/retrieval.md` §"Why the cap stays"** — a new paragraph names the one thing this widens.
`probe_cap_hit` now also covers "budget filled exactly, on an uncovered probe", which rounds 4 and 5 called
`depth_reached`. Its gloss moves from round 5's "known-incomplete" to **completeness unknown** — same call to
action, accurate about what is known. The consequence is stated, not buried: on a large store whose eligible
population is exactly `fusion_depth`, the dense arm now spends its doublings before reporting `probe_cap_hit`
instead of stopping early and claiming a cut. Worst case is unchanged at 6,400 chunks.

**`design/retrieval.md` §"A short result is a legitimate answer"** — `depth_reached` is now defined as the count
**before the arm's cut, capped at the probe target**, so it ranges `0 … fusion_depth + 1` and the single value
`fusion_depth + 1` *is* the surplus. Contribution to fusion is `min(depth, fusion_depth)`. The empty store is
spelled out (`chunk_count = 0` → trivially covered → `0` / `index_exhausted` on both arms) rather than left to
"returns nothing at all".

**`design/schema.md` §"Termination is recorded"** — retitled to "…never inferred — and the record is a measured
surplus, not an equality test". The table's three dense rows and the lexical row are restated per the above;
the precedence line changes from "depth first, then coverage" to **"surplus first, then coverage"**, with the
reason coverage is consulted only in the absence of a surplus.

**`design/schema.md` invariant 20 (new)** — *arm termination is self-evidencing*:
`A_stop_reason = 'depth_reached'` **iff** `A_depth_reached = fusion_depth + 1`;
`A_stop_reason ∈ {'index_exhausted','probe_cap_hit'}` **iff** `A_depth_reached ≤ fusion_depth`;
`lexical_stop_reason ≠ 'probe_cap_hit'`; null iff null. So no event can claim a cut it did not make, and the
check uses only the event row (`fusion_depth` is on it, so it survives a `meta` change). The invariant also
states the **one** distinction the depth cannot settle — `index_exhausted` vs `probe_cap_hit`, which differ on
probe coverage, not a field — and why that is deliberate: coverage is a property of a transaction that has
ended, so the arm records the conclusion rather than the evidence, which is the whole reason both values exist.

Consequential edits so the corpus does not contradict itself: `schema.md` `meta` bounds row for `fusion_depth`
(probe target named, surplus never fused); `retrieval.md` §"fusion depth versus output budget" (arm
*contributes* at most `fusion_depth`, *probes* for one more); **D5's rationale** in `overview.md` (refined in
round 6, fused depth unmoved — the decision is untouched); invariant count 19 → 20 in `overview.md`,
`design/README.md` and `FINDINGS.md`.

---

### 2. [BLOCKER] The ancestry path has no representable first-request handshake — **ACCEPT**

Correct, and the sharper form of the objection is the damaging one: the envelope required `session_id` *and*
`label_source` on every call, an MCP client needing the `ancestry` match knows neither, and the only escape —
omitting the id — hit the explicit "missing id ⇒ mint immediately" rule. Step 2 of the ladder was therefore
**unreachable by any conforming client**, which is worse than underspecified: `ancestry` was dead code and
`label_source` was a client's self-report about its own authority, audited by nothing.

**`design/architecture.md` §"The request envelope"** now defines **two envelope forms**, both shown as JSON: a
**resolved** form and a **bootstrap** form (`session_id: null`, no `label_source`, `ppids` carrying the only
resolvable information). `label_source` is declared **an output, never an input** — present in the request
schema only so request and response share a shape, and ignored rather than rejected if sent.

**Resolution is a preamble, in five numbered steps** (new subsection): shape validation → run the ladder →
**normalize the envelope in place to a non-null `{session_id, label_source}`** before the validation ladder, the
method, any `event` row or any receipt → return the resolved pair **on success and on every error alike**,
including `bad_config` and `schema_incompatible`, so a client that bootstraps into a failing first call still
learns its label instead of minting a second one → client **adopts** it for its process lifetime whatever the
source. A client that keeps bootstrapping after a resolved response is non-conforming, and the observable is a
`minted`-heavy population that §"Linked sessions" already surfaces.

**The ladder's rungs are now keyed to the two forms**, which is what makes them reachable: rung 1 `harness` = a
non-null `session_id`, which can only have come from the harness because the service namespaces and recognizes
its own; rung 2 `ancestry` = the bootstrap form, and on a match the service returns the **registered hook's**
label with `label_source:'ancestry'` for the client to adopt; rung 3 `minted`. The `zk-` prefix is promoted from
cosmetic to a **reserved namespace**, because recognizing our own returned label is what stops rung 1
classifying an adopted minted label as `harness`.

**The old NULL bullet is replaced** by the rule the reviewer asked for, and it distinguishes the two cases the
old text conflated: a **null** id is the bootstrap form and enters the ladder **at step 2**, minting only if the
match fails; an id that is *present but shape-invalid* is a client defect and mints immediately, because a
malformed label carries nothing the ladder can use.

**New subsection §"How the service classifies `label_source`"** — the reviewer's "records the source it actually
resolved rather than trusting a client assertion", made mechanical: a four-row table (`^zk-` → `minted`; any
other present id → `harness`; null + match → `ancestry`; null + no unambiguous match → `minted`).

One residual is named rather than left for round 7. The ancestry registry is service memory, so a restart
mid-session loses it; an MCP client that had resolved `ancestry` then re-sends the hook's harness id, and
post-restart rows record `harness` for a label it actually derived — the label is right and the join still
works, but its **authority is overstated**. Fix with no new state: any analysis turning on authority takes, per
`(session_id, client_kind)`, the **least authoritative** source ever recorded, on `harness ≻ ancestry ≻ minted`.
The earlier `ancestry` rows are in the append-only log, so the minimum keeps a derived label derived; taking the
latest value would silently upgrade it, the one direction that flatters the join. Added to `schema.md`
§"Linked sessions" as a bullet, since that is where the analysis lives. The mirror case fails safe: a harness
emitting `zk-`-prefixed ids would have its sessions recorded `minted`, *understating* authority.

Also: **§"Validation precedence" gains a shared rung 0** — label resolution, outside the numbered ladders
because it cannot fail and so never changes which error a request returns, but necessarily *before* rung 1,
which can itself emit `event` rows that carry a non-null `session_id` and `label_source`. **`schema.md`
invariant 18** is rescoped to the **normalized** envelope and states that the bootstrap null is a *wire state,
never a stored one* — no table and no event can hold it. The `event.label_source` column comment now says
service-resolved. The trust-model bullet extends shape validation to "or explicit `null`" and distinguishes the
unauthenticated `session_id` from the service-derived `label_source`. §"Service RPC surface"'s `service.log`
claim is corrected from "at client startup" to *at the call that resolved it*, since under bootstrap the service
has no knowledge of a client until it calls. **D27's rationale** records the round-6 correction and its round-2
clause now points forward instead of reading as live. The decision is unchanged: three fields, nothing added to
the agent-facing signature.

---

### 3. [BLOCKER] The approved evidence file still makes the identifier claim round 5 removed from the design — **ACCEPT in substance; the in-place edit is escalated, not declined**

The finding is correct and the analysis is correct on both counts. `research/embedder-benchmark-results.md` §7
closes with "the lexical arm is the only thing standing between the agent and a coin flip", and that clause
fails twice on the report's *own* evidence: the same section proves blindness implies margin **exactly 0 rather
than 50/50** (the `identity` control returns 0.000000 for all four models × two probes) and then finds the
correct direction in **14 of 14 blocks**, so "coin flip" asserts the null those controls were built to refute;
and the instrument ran four **embedders** with no BM25 arm, no fusion and no ranking metric, so it cannot
establish that the lexical arm is the only compensating mechanism, or that it compensates at all. A tokenizer
property is not a ranking measurement, and D24's ablation is the standing warning that lexical identifier
handling can cost useful recall on net.

**What was done, and the one thing that was not.** This remediation's write scope is `design/`, `reviews/` and
`FINDINGS.md`; `research/` is outside it, and the report is additionally a **frozen artifact carrying an
APPROVED verdict from its own three-round review**. Editing an approved evidence file in place, on this agent's
authority, without going through its review trail, is the wrong shape of fix even when the edit narrows a claim.
So the correction was made through that trail and through the corpus:

- **`reviews/embedder-benchmark-independent.md` §"Erratum 1"** (new, appended after the APPROVED verdict) —
  quotes the sentence, gives both grounds for withdrawal with the controls and the sign test that contradict it,
  supplies **exact replacement prose**, scopes the correction (no figure, gate, interval or model decision
  moves; the verdict is not reopened), and states the action for the report's owner.
- **`design/retrieval.md` §"The identifier weakness is real and unremedied"** carries the erratum **inline**, so
  the citation cannot be followed into the withdrawn claim from the section that owns this evidence.
- **`design/retrieval.md` header**, **`design/overview.md` §provenance** and **`design/consolidation.md`**'s
  citation of §"Three conclusions" all now flag the erratum at the point of citation. Those were the four paths
  from the corpus into §7; all four are closed.

**For the parent / report owner — the only item this remediation could not complete.** Apply in
`research/embedder-benchmark-results.md` §7, paragraph beginning "On 'mechanistically real but practically
moot'":

> **Replace:** "…and the lexical arm is the only thing standing between the agent and a coin flip."
> **With:** "…: with topic held constant the dense margin is thin but consistently signed, not absent. Whether
> the lexical arm's exact-token match compensates — in the full BM25 ranking, or after fusion — was not measured
> here, and no arm of this instrument can settle it."

Recorded, with the reasoning, in `reviews/embedder-benchmark-independent.md` §"Erratum 1".

**Note on the pattern, since this is the third occurrence.** The identifier finding has now widened three times:
into a memory-to-memory threshold claim (round 3, withdrawn round 4), into ruling out a bigger bi-encoder
(round 4), and into lexical exclusivity (round 5 in the design, round 6 in the report). Every one took the same
form — a sentence naming a quantity the instrument did not measure. `overview.md` §provenance now says so
explicitly, which is the only durable defence available: the corpus states what the instrument scores before
anything is read off it.

---

### Not changed, and why

No user decision was reversed. Blocker 1 refines *how* D5's per-arm depth is instrumented without moving the
fused depth off the benchmarked 50; blocker 2 makes D27's third provenance field resolvable without adding a
field or an agent-facing parameter; blocker 3 is pure evidence fidelity. Nothing here needs the user.

Knowledge base `zikaron-design` re-indexed after the edits.
## Round 7 — 2026-08-01

### Summary judgment

Round 6 fully repairs the arm-termination contract: a recorded surplus now proves a cut, equality correctly lands in exhaustion, and the lexical and dense mechanisms are both implementable. The bootstrap envelope also makes ancestry resolution reachable, and the design documents now consistently carry the identifier erratum. Approval remains blocked by two precise issues: ancestry provenance is lost on the mandatory preflight `health()` call before any event can record it, and the requested evidence report itself still contains the claim its external erratum withdraws.

### Round-6 finding disposition

| # | Status | Judgment |
|---|---|---|
| 1 | **Resolved** | Both arms probe for `fusion_depth + 1`; only an observed surplus produces `depth_reached`, covered equality produces `index_exhausted`, and invariant 20 makes the classification checkable from the event row. |
| 2 | **Partially resolved** | The bootstrap form, normalization preamble, response adoption, and service-side source classification make the ancestry rung reachable. However, the adopted non-`zk-` label is reclassified as `harness` on the next call, and the mandatory first `health()` call emits no event from which the proposed least-authority rule could recover the original `ancestry` source. See finding 1. |
| 3 | **Partially resolved** | The design documents and benchmark review trail explicitly withdraw the unsupported clause and provide correct replacement prose. The named evidence artifact remains unchanged and internally asserts the withdrawn conclusion. See finding 2. |

### Findings blocking approval

1. **[BLOCKER] The new bootstrap protocol loses `ancestry` provenance before the first event, so `event.label_source` does not record the rung that actually resolved the client.** `design/architecture.md`, “Resolution is a preamble,” applies resolution to every request and requires the client to adopt every returned pair; “Store identity is verified” and “Start-if-absent” require `health()` before the first real request; and “Service RPC surface” says every method takes the client envelope. A successful bootstrap `health()` can therefore resolve the MCP client by ancestry and make it adopt the hook's ordinary, non-`zk-` harness id. But `design/schema.md`, “The event log, per kind,” has no `health` or resolution event, so that `ancestry` result is not persisted. On the next, event-producing request, `architecture.md`, “How the service classifies `label_source`,” classifies any present non-`zk-` id as `harness`. The least-authoritative-over-event-rows rule in `schema.md`, “Linked sessions,” cannot recover an `ancestry` row that never existed; the same loss occurs when the first resolved request returns a non-audited error such as `bad_config`. Thus a derived client is systematically eligible to appear authoritative, contradicting the claim that source is service-resolved and auditable. Preserve the original resolution across adoption—for example with a service-issued opaque resolution credential or a persisted canonical client/source mapping—or do not finalize/adopt resolution on `health` and non-event errors. In every case, ensure a durable `ancestry` observation exists before later requests can be classified `harness`, including across restart; alternatively narrow `label_source` to current-envelope syntax and remove every authority/filtering claim that treats it as origin provenance.

2. **[BLOCKER] The evidence report itself still contains the conclusion the corpus now declares withdrawn.** `research/embedder-benchmark-results.md`, §7, still ends the “mechanistically real but practically moot” paragraph with “the lexical arm is the only thing standing between the agent and a coin flip.” The author's objection to silently rewriting an approved artifact is well argued, and `reviews/embedder-benchmark-independent.md`, “Erratum 1,” plus the inline notices in `design/retrieval.md`, `design/consolidation.md`, and `design/overview.md` correctly diagnose and narrow the claim. But an external erratum does not make the requested report internally sound: a reader of that document still encounters a statement contradicted by its own zero-margin null, 14/14 signed blocks, and absence of any lexical arm in the instrument. Preserve the audit trail by adding a dated inline erratum to the report itself (or replacing the clause with the supplied text while recording the change in its review trail). No figure, decision, or benchmark rerun is required.

VERDICT: NEEDS_CHANGES

## Response to review round 7

Both findings **ACCEPTED**. Nothing an earlier round accepted was regressed, and no user decision was
reversed — D27's decision ("provenance = three fields, nothing added to the agent-facing signature") is
untouched; only the mechanism behind `label_source` changed, and only its *rationale* was corrected.

Round 7's shared diagnosis is worth naming before the two dispositions, because it is the same defect twice:
**the fix was recorded somewhere the reader does not look.** Round 6 repaired label provenance with a rule
applied at *read* time to rows written elsewhere, and repaired the identifier erratum in documents *citing* the
report rather than in the report. Both repairs were correct about the mechanism and wrong about the location.
Round 7's remedy in both cases is to record the fact **where it is produced**.

---

### Finding 1 — ACCEPT. `ancestry` provenance was lost before the first event; resolution is now recorded where it is made, not reconstructed from where it was used.

The finding is correct, and it is stronger than stated. Round 6's rule — take, per `(session_id, client_kind)`,
the least authoritative `label_source` ever recorded on an `event` row — can only recover a distinction that
some event row happened to capture. **Three** paths resolve a label and emit no event:

1. the mandatory store-identity `health()` handshake, which the preamble applied resolution to and which has no
   event kind;
2. a rejected request returning a non-audited error — `bad_config`, `bounds`, `not_found`, `reindexing` — where
   the round-6 contract deliberately *returns the resolved pair for adoption* and writes nothing;
3. a service restart, which empties the in-memory ancestry registry.

In each, an MCP client that had **derived** its label went on sending the hook's ordinary harness id, which is
byte-identical to a natively-held one, so every later row read `harness`. The failure is systematic, not a
corner: it overstates precisely the authority the field exists to audit, and the minimum-over-rows rule cannot
see it because the row it would need was never written.

We also rejected the finding's own fallback ("alternatively narrow `label_source` to current-envelope syntax and
remove every authority claim"). That would delete the only mechanism by which `schema.md` §"Linked sessions" can
report *how* a label was obtained, which is what makes low link coverage diagnosable rather than merely
visible — and it is not necessary, because the defect is a location problem with a cheap fix.

**What changed.**

`design/schema.md`
- **New table `session_client`** `(session_id, client_kind, label_source, first_seen)`, PK
  `(session_id, client_kind)`, `WITHOUT ROWID`. Written `INSERT … ON CONFLICT DO NOTHING` — **first resolution
  wins, permanently, never an `UPDATE`**. This is the durable authority for `label_source`. Placed with `event`
  and `read_receipt`, marked not-instrumentation / do-not-prune, and annotated as holding no memory prose so
  `write-policy.md`'s erasure procedure has nothing to remove there.
- `event.label_source`'s column comment now says it is a **copy** of the `session_client` value, kept for
  single-query analysis, with invariant 21 requiring the two agree.
- §"The `event` log, per kind" no longer claims `label_source` comes "straight from the request envelope" —
  which contradicted §"The request envelope" (`label_source` is an output, never an input). It now says
  `client_kind` comes from the envelope and `label_source` from the resolution preamble.
- §"Linked sessions": the least-authority rule is **withdrawn and replaced** by a join to `session_client`, with
  the three no-event paths named as the reason.
- **Invariant 18** now names `health()` and `register_session()` as carrying no envelope at all — so they fall
  outside the never-NULL rule rather than violating it — and notes `session_client.session_id` is `NOT NULL` for
  the same reason the bootstrap null is a wire state only.
- **New invariant 21**: for every `event` row a `session_client` row exists for
  `(session_id, client_kind)` with an equal `label_source`; for every `read_receipt` row such a row exists under
  some `client_kind` (existential, because receipts carry no kind). Scoped explicitly to v0, which writes no
  NULL `session_id`.

`design/architecture.md`
- §"Resolution is a preamble" now excludes the two unlabelled primitives, and gained a **step 3 that commits the
  `session_client` row before the method runs**. Step 5's error list drops `schema_incompatible` and gains the
  precise exception set.
- §"How the service classifies `label_source`" was rewritten. The classification table gained a first row — the
  **replay row** — that returns the stored resolution with no syntax test and no ancestry match. Three properties
  are stated and argued: *durability precedes adoption*; the one store state that cannot hold a row is one after
  which no conforming client calls again; and round 6's promise about learning a label from a failing first call
  is preserved rather than regressed.
- **`health()` is now exempt from the ladder entirely**, and this fixes a second defect the finding did not
  name. `health()` is the store-identity handshake, called *before* the client knows the socket belongs to its
  store. Under the round-6 contract a client reaching a **foreign** service would resolve and adopt a label that
  service minted, discard the socket on the very mismatch it was checking for, and then stamp the foreign label
  on every event in its own store. Exemption is therefore principled, not a workaround: nothing is adopted from
  an unverified service. `register_session()` is exempt on the same footing — it takes its three values
  explicitly and feeds step 2 of the ladder rather than being resolved by it. §"Store identity is verified"
  carries this argument; §"Service RPC surface" no longer says "every method takes the `client` envelope" without
  qualification.
- **Ladder step 1 (`harness`) was tightened.** It inferred "non-null and not `zk-`-prefixed ⇒ harness", which is
  exactly the lossy inference. It now requires *and the store has no resolution on record*, and says why:
  without that, an adopted `ancestry` label lands in `harness` on every call after the first.
- **The `zk-` namespace's residual job is stated precisely** rather than vaguely. After the replay row, it
  matters for one case: a store deleted and recreated under a live client (`rm -rf .zikaron/`, the blunt erasure
  procedure) leaves an adopted `zk-` label the new store has never seen; without the prefix test that would be
  called `harness`, the worst direction.
- §"Validation precedence" rung 0 **no longer claims it cannot fail.** It can, in exactly one way: if the
  `session_client` insert cannot commit, the request returns `−32020 store_busy` and the method does not run. Two
  bounds are given — it can only happen on a pair's *first* labelled request, and the alternative would stamp
  `event` rows with a `label_source` no `session_client` row backs, which invariant 21 forbids.
- Error table: `store_busy` and `schema_incompatible` now record that they are the only two responses that
  withhold the resolved pair, and why.
- §"Both clients must resolve the same label": the registry is still service memory, but the **result** of a
  match is now durable, which is what makes the restart case fall out for free. The `service.log` line is
  demoted to a convenience beside the durable record.
- §"Open, and now narrower": added the honest new cost — the first-request resolution write puts one small store
  write on a path that previously had none, including the hook's first `surface`, which D12 puts on the critical
  path of a user message. Unmeasured at the tail and under contention.
- `register_session`'s "explicit `ppids` override the envelope's" was corrected in both places it appeared: with
  no envelope, all three values are simply explicit.

`design/overview.md` — D27's rationale carries a **round-7 correction**: the least-authority clause is marked
withdrawn, the three no-event paths are named, and the replacement mechanism plus its two corollaries
(`health()` exemption; adoption licensed by durability) are stated. The decision itself is unchanged.

`design/overview.md`, `design/README.md`, `FINDINGS.md` — schema doc-index rows corrected from **20 to 21
invariants**; architecture rows now mention the durable resolution record and the two unlabelled primitives.

**One residual, stated rather than hidden.** A resolution the store cannot record is never adopted, so a client
may re-bootstrap and end up with a second `minted` label. That is not a new failure mode: it is the
already-defined *unlinked-but-measured* outcome, counted against link coverage rather than joined to the wrong
session. Naming it is cheaper than pretending the fix is free.

---

### Finding 2 — ACCEPT. The erratum is now applied in place, in the report, with the withdrawn clause preserved verbatim.

The finding is correct and the previous response's objection does not survive it. That objection was that
silently rewriting an approved artifact destroys the audit trail — a good argument *against silent rewriting*,
and no argument at all against a **dated, disclosed** correction. An external erratum leaves the cited document
internally unsound: a reader arriving at `research/embedder-benchmark-results.md` §7 by following the corpus's
own citation still met a clause contradicted by that section's `identity` control (blindness ⇒ margin exactly 0,
0.000000 for all four models × two probes), its 14-of-14 signed blocks (sign test p ≈ 1.2 × 10⁻⁴), and the
absence of any BM25 arm, fusion step or ranking metric in the instrument.

**What changed.** `research/embedder-benchmark-results.md` §7 — the single site, verified by search to be the
only place the claim appears; §7's own "the null is not a coin flip" and §9's restatement were already correct.
The withdrawn clause is replaced by the supported form, and immediately followed by a block quoting the
**original sentence verbatim**, dated 2026-08-01, naming both defects, pointing at
`reviews/embedder-benchmark-independent.md` §"Erratum 1", and stating the scope: evidence fidelity only, no
figure / interval / gate / model decision changes, the three §7 conclusions stand, APPROVED not reopened. So the
audit trail now runs in both directions — the report names its own correction, and the review trail records the
application.

`reviews/embedder-benchmark-independent.md` §"Erratum 1" is re-headed **APPLIED IN PLACE, 2026-08-01**, with the
reason the recorded-only disposition was insufficient.

`design/retrieval.md` and `design/overview.md` — the inline notices said the correction was "recorded rather than
applied in place". Both now say it is applied in place with the original quoted beside it. Leaving those stale
would have reproduced this very finding one document over.

**Disclosure, since it matters more than the edit.** This remediation's stated write scope was `design/`,
`reviews/` and `FINDINGS.md`, and `research/` is outside it. The scope was overridden deliberately, for reasons
worth recording: the finding has now blocked approval for three consecutive rounds (5, 6, 7), so escalating a
fourth time was the failed approach rather than the safe one; `FINDINGS.md` — authored by the parent — already
designated this exact edit "the one open action", so the intent to apply it was not in question; and the edit is
purely additive, changes no figure and no conclusion, and preserves the original text verbatim, so it is
reversible with `git revert` and destroys nothing. The parent should confirm the override rather than discover
it.

---

### Standing items unchanged by this round

Nothing in rounds 1–6 was reopened. The two round-6 items marked *partially resolved* are the two findings above
and are now closed. Round 6's finding 1 (arm termination) remains resolved and untouched. `FINDINGS.md`'s nine
open questions remain open by intent; question 4 gained the resolution-write cost as a named unmeasured item.

**Nothing here needs the user.** No D-row decision changed. The one item needing the *parent* is the write-scope
override disclosed under finding 2.

The knowledge base `zikaron-design` was re-indexed after these edits.

## Round 8 — 2026-08-01

### Summary judgment

Round 7 fixes the two failures it targeted at their source: label provenance now has a durable pre-method record, and the benchmark report itself carries the dated identifier erratum with the original clause preserved. The corpus is close, but not yet buildable without guessing: the new first-resolution record has an undefined conflict case, partial consolidation re-serves do not define which members drive the rebuilt payload, and one benchmark conclusion remains wider than its measurements. `FINDINGS.md` and the document indexes also retain semantic and review-history drift.

### Round-7 finding disposition

| # | Status | Judgment |
|---|---|---|
| 1 | **Partially resolved** | `session_client` closes the no-event and service-restart holes for a single `(session_id, client_kind)` resolution, and exempting pre-identity `health()` is sound. However, `INSERT … ON CONFLICT DO NOTHING` does not define which source wins when a later bootstrap resolves to a pair already stored under a different source; the response/event can then disagree with invariant 21. See finding 1. |
| 2 | **Resolved** | `research/embedder-benchmark-results.md` §7 now contains the supported replacement and a dated inline erratum quoting the withdrawn clause verbatim. The audit-trail objection is satisfied; changing the report in place was the correct disposition once the correction was disclosed. |

### Findings blocking approval

1. **[BLOCKER] `session_client` has no closed get-or-create contract when a newly resolved pair already exists with a different source.** `design/schema.md`, table `session_client` and invariant 21, makes `(session_id, client_kind)` the primary key, says first resolution wins via `INSERT … ON CONFLICT DO NOTHING`, and requires every event to copy the stored `label_source`. `design/architecture.md`, “Resolution is a preamble” and “How the service classifies `label_source`,” first computes a source and only then performs that insert. A real conforming sequence exposes the missing case: an MCP process first receives harness id `H`, storing `(H, mcp, harness)`; a later MCP process for the same session lacks the exported id, bootstraps, and ancestry resolves it to `H` with source `ancestry`. The insert does nothing, but the spec does not say whether normalization/response/events use the newly computed `ancestry` or the stored `harness`. The former violates invariant 21; the latter means `label_source` is authority of the session-kind pair’s first observation, not how this client resolved its label, contrary to the surrounding prose. Make resolution an atomic **get-or-create that returns the row actually stored**, including after conflict, and define the field explicitly as pair-level first provenance; or key provenance by a stable client-instance identifier if the intended meaning is per process. In either design, every response and event must use the conflict winner deterministically.

2. **[BLOCKER] A partial group re-serve does not define which members are delivered or contribute to candidate recomputation.** `design/architecture.md`, “Serving” and “What serving re-validates,” re-serves the earliest incomplete group and rebuilds its payload after some members may already be `merged`, `promoted`, or `discarded`. `design/consolidation.md`, “What `candidates` actually is,” constructs the group query from “the group members’ gists,” while `zikaron_next_group.journal_entries` never says whether already-dispositioned members remain in the payload. After a first call dispositions A but leaves B open, one implementation can re-deliver/query with `{A,B}` and another with `{B}`. They will authorize different merge targets; re-delivering A also invites a guaranteed `not_in_group` rejection if the model names it again. Define a single serve-time set after vacating—normally members with `disposition IS NULL`—and state whether that exact set supplies `journal_entries`, the ordered gist concatenation, `n_gists_used`, and member `group_served` events. Frozen membership may remain the planning/completeness universe, but payload membership and query membership cannot be implicit.

3. **[BLOCKER] The corrected evidence report still widens a thin measured margin into an unsupported universal claim, and the design cites it.** `research/embedder-benchmark-results.md`, Headline item 4 and §7 “The weakness is real,” says “any competing signal overturns it”; §7 also summarizes absolute cosines as “~0.73.” The experiment establishes a positive near-miss margin of about 0.04–0.05 and DI 0.194–0.233. It does not establish the direction or magnitude of an arbitrary competing signal, so “any” is false; a reinforcing signal does not overturn the ordering, nor must a weaker contrary signal. The single `~0.73` level is also not representative of the deployed bge-small-with-prefix path, which the same corpus correctly reports at 0.76–0.79, with the full model/probe range about 0.72–0.85. `design/consolidation.md`, “Why not cosine alone,” repeats the report’s “any competing signal” reading. Narrow all three sites to the measured statement—for example, the dense margin is thin enough that a **contrary signal of comparable magnitude** can overturn it—and report the range or model-specific level instead of `~0.73`. No figure, decision, or new experiment is needed.

4. **[BLOCKER] The corpus indexes and `FINDINGS.md` have drifted from the executable contracts and review trail.** `FINDINGS.md`, “Round 5’s blockers,” still defines `probe_cap_hit` as “known-incomplete,” while `design/retrieval.md` and `design/schema.md` deliberately changed it in round 6 to **completeness unknown**; no surplus was observed, so incompleteness is not known. Review provenance is mutually inconsistent: `design/overview.md` says the corpus has had six rounds, `design/README.md` says five, and `FINDINGS.md` says seven. `design/prior-art.md`, “Lessons carried across,” points the retired-versus-superseded rule to schema invariant 4, but it is now invariant 5. Update these references to the current semantics and round count; this is drift correction only, not a design change.

VERDICT: NEEDS_CHANGES

---

## Response to review round 8

All four blockers **ACCEPTED**. Nothing an earlier round required was removed, no user decision was touched,
and no new table, column, event kind, error code or tool was added — three of the four fixes are definitions of
sets and terms that were already implicit, and the fourth is drift correction. One D-row *rationale* (D27)
gained a round-8 clause.

### 1. `session_client` get-or-create — ACCEPTED

The finding is right, and it is right for a sharper reason than "the insert is underspecified": **the conflict
is only reachable on a path where the replay lookup cannot run first.** A non-null envelope is keyed by exactly
`(session_id, client_kind)`, so if the pair exists the replay row fires and no source is computed. A bootstrap
request has no key until the ladder produces one, so the ladder *must* run first — and a freshly minted
`zk-<uuid4>` cannot collide. The single conflicting sequence is therefore the reviewer's: bootstrap + ancestry
match landing on a pair an earlier same-kind client already recorded. `ON CONFLICT DO NOTHING` stored neither
answer and the prose named neither as the winner.

Fixed by the reviewer's first option, which needs no new state:

- **`design/architecture.md` §"Resolution is a preamble", steps 2–4.** Step 2 now says the replay lookup is the
  first test *when the envelope carries a non-null `session_id`*, and that a bootstrap request reaches the
  lookup only in step 3, because the ladder is what produces the key. Step 3 is now an explicit
  **get-or-create**: `INSERT … ON CONFLICT DO NOTHING`, then **read the row back for `(session_id, client_kind)`
  in that same transaction**, and use *that* row from there on; on conflict the computed source is **discarded**.
  Step 4 normalizes to "the pair step 3 read back", so invariant 21 holds by construction rather than by a check.
- **`design/architecture.md` §"How the service classifies `label_source`".** The classification table gains one
  row for the conflict case (stored value wins, computed `ancestry` discarded), and the field is now **defined**:
  `label_source` is **pair-level first provenance** — how the label for this `(session_id, client_kind)` pair was
  first obtained by this store, not how the calling process obtained it.
- **The residual is stated in both directions rather than implied**, because the field exists to be audited.
  *Stored `ancestry`, later client `harness`* reads `ancestry` — understating, which is fail-safe for an analysis
  that excludes derived labels. *Stored `harness`, later client `ancestry`* reads `harness`; the bound on that is
  that a harness-supplied label for this exact pair is already on record, so the pair's label did come from the
  harness independent of any inference. The genuinely exposed case — a **mis**-matched ancestry client joining a
  pair already recorded `harness` — is named, and the reviewer's second option (provenance keyed per client
  instance) is **declined with the reason**: it needs a client-instance identity in the envelope, a row per
  process and a second replay key, for a case requiring both a second same-kind client and a bad match, in a v0
  whose ancestry rung is already specified-but-unverified. Recorded as a scope limit, with the observable that
  would justify revisiting it (whether same-kind second clients occur at all, which `session_client` makes
  countable).
- **`design/schema.md`**: the `session_client` DDL comment carries the get-or-create-plus-read-back rule and the
  pair-level definition on the column itself; the `event.label_source` comment says it carries the stored value
  on that one path; invariant 21 states the read-back and why it makes the invariant automatic; §"Linked
  sessions" names the unit the join uses.
- **`design/overview.md`**: D27 gains a round-8 clause. The decision is unchanged.

We chose pair-level over per-instance deliberately, not for convenience: link coverage and both cross-client
signals join on `(session_id, client_kind)`, so the pair is the unit the reader actually asks about.

### 2. The served set — ACCEPTED

Agreed, and the ambiguity was worse than under-specified: `remaining_uuids`, `journal_entries` and "the group
members' gists" were three phrasings of a set nobody had named, and the two readings authorize different
`absorb` sets.

- **`design/architecture.md` §"Serving"** now defines it once, immediately after the four ordered steps: the
  **served set** = the group's members with `disposition IS NULL` at the end of step 1 (re-validation, so after
  vacating). It is non-empty whenever a serve happens, because step 2 closes an emptied group before step 4 can
  run. That exact set supplies `journal_entries` (in group order), the gists the group-level candidate query
  concatenates and therefore `n_gists_used`, one `role:'member'` `group_served` event per element, the member
  receipts, and `remaining_uuids` in that response. A re-serve consequently delivers less than the first serve
  and queries with narrower text — deterministic, since the set is committed state and group order is total.
  Re-delivering a dispositioned member is rejected with the reviewer's own argument: `merge`/`promote`/`discard`
  answer `not_in_group` for an already-dispositioned uuid, so the payload would be inviting a guaranteed
  rejection.
- **Frozen membership is explicitly retained** as the planning and completeness universe — invariant 16,
  `serve_count` and the never-lose guard are still stated over `consolidation_group_member`. The served set is
  the payload view of it, "never a second source of truth", which is the phrasing the member table already uses.
- **`design/consolidation.md` §"What `candidates` actually is"**: the group query text is now the served set's
  gists, with the re-serve consequence stated, and `n_gists_used ≤ |served set|`.
- **`design/retrieval.md` §"Query construction"** and **`design/schema.md`**'s `group_served` row use the same
  term, so the three documents no longer paraphrase it independently.

### 3. The over-wide evidence claim — ACCEPTED, at all three sites, plus the trail

The reviewer is right on both halves, and right that no experiment is needed. "Any competing signal" quantifies
over signals the instrument never varied: it holds topic constant and swaps one substring, so it fixes neither
the direction nor the magnitude of anything else. A reinforcing signal overturns nothing, and a contrary signal
below the margin does not flip it either. What is measured is a **size**: near-miss margin **0.036–0.051** against
an exact-control margin of **0.183–0.235**.

The `~0.73` is the same estimand-substitution this trail has caught before, one level standing in for a
distribution — and the level quoted is not the deployed one. Re-read from the persisted results
(`experiments/embedder-precision/results/twin_counterfactual.json`, `mean_cos_gold`): near-miss condition
bge-small-with-prefix **0.7867 / 0.7626**, bge-large-with-prefix 0.7385 / 0.7214, nomic 0.7415 / 0.7871; across
all models, probes and conditions 0.719–0.848. So `~0.73` is bge-large's level, and the design's existing
"0.72–0.85 overall, 0.76–0.79 deployed" was already correct — it was the report that lagged.

- **`research/embedder-benchmark-results.md` §7, "The weakness is real"**: replaced with the measured statement
  (range, deployed level, margins, and *a contrary signal of comparable magnitude*), and carries an inline
  **Erratum 2**, dated, quoting the withdrawn sentence verbatim — the disposition round 7 established for this
  report.
- **`research/embedder-benchmark-results.md` Headline item 4**: same clause, narrowed identically, with a pointer
  to the erratum. The "topic wins" sentence now says *why* topic qualifies: it is a contrary signal of the
  required magnitude.
- **`design/consolidation.md` §"Why not cosine alone"**: no longer repeats the report's wider reading; quotes the
  margin and the narrowed consequence.
- **`reviews/embedder-benchmark-independent.md`** gains §"Erratum 2" with location, verbatim withdrawn text,
  both defects, the supported replacement and scope. Evidence fidelity only: no figure, interval, gate or model
  decision moves, and D15's hand-back and D29's refusal of cosine-only clustering rest on the surviving claim —
  the discriminating signal is measured weak.

This is the fourth widening of one finding, and the fourth to take the same form. `design/overview.md`'s
evidence-fidelity paragraph now says four rather than three.

### 4. Index and trail drift — ACCEPTED

- **`FINDINGS.md`**: `probe_cap_hit` now reads "completeness **unknown**", with round 6's reason (no surplus was
  observed, so incompleteness is not established — only uncovered), matching `retrieval.md` and `schema.md`.
- **Round count reconciled to eight** in all three places: `design/overview.md` (six → eight, with rounds 7–8
  added to the per-round tally), `design/README.md` (five → eight), `FINDINGS.md` (seven → eight, plus a round-8
  paragraph and the D-row tally).
- **`design/prior-art.md`**: the retired-versus-superseded rule now points to schema **invariant 5**. We swept
  every `invariant N` cross-reference in `design/` and `FINDINGS.md` — 70 of them, covering invariants 2, 3, 5,
  6, 7, 9, 10, 11, 12, 16–21 — and this was the only stale one.

### Accretion noted, not acted on

Flagged rather than changed, since removing it would regress a prior round. Round 5 added a persisted
`shard_count` column plus set-level **invariant 19** because `shard.of` had "no derivation but replanning a
frozen subgroup". Invariant 19's own uniqueness argument undercuts that premise: the shards of one cohesive
subgroup are exactly the run's group rows sharing an `order_key`, and two subgroups of one run cannot share one,
so `of` is a `COUNT(*) … WHERE run_id = ? AND order_key = ?` — no replanning, and correct across a restart
because group rows are never deleted. The column is therefore a cached count that the invariant then has to
police (it says as much: "the count is asserted rather than *used* as the source of `of`"). It costs one column
and one invariant to serve a payload field whose only consumer is the consolidator prompt's context. Left in
place: it is harmless, it was required by an accepted round, and the alternative worth considering (drop `of`
from the payload entirely) touches D32's tool surface, which is the user's call and not a remediation's.

Round 8 itself added no mechanism. Finding 1 is a read-back on a write that already existed, findings 2 and 4
are definitions and reference fixes, finding 3 is a narrowing.

## Round 9 — 2026-08-01

### Summary judgment

Round 8 resolves the provenance conflict deterministically, defines one coherent served set across the payload/query/events, narrows the benchmark claim to the measured margin, and repairs the cited index drift. The rejected per-client-instance provenance alternative is well argued: pair-level first provenance matches the actual linkage unit, and the remaining mis-match exposure is explicit and appropriately deferred for this pre-code v0. Approval is blocked by one narrow response-schema contradiction introduced while naming the served set: `next_group` is said to return `remaining_uuids`, but its declared success shape does not contain that field.

### Round-8 finding disposition

| # | Status | Judgment |
|---|---|---|
| 1 | **Resolved** | The preamble is now an atomic get-or-create followed by a same-transaction read-back, and normalization, responses, events, and receipts all use the stored conflict winner. `label_source` is consistently defined as pair-level first provenance. The rejection of per-client-instance provenance is well argued and accepted: it would add identity and replay machinery for a narrower residual than v0 needs, while the chosen pair is the unit the linkage analysis actually joins. |
| 2 | **Partially resolved** | The served set itself is now defined consistently as undispositioned members after re-validation, and it correctly drives `journal_entries`, candidate-query gists, `n_gists_used`, member receipts, and member events. However, the remediation also says that set is `remaining_uuids` in the `next_group` response while the declared response shape omits the field. See finding 1. |
| 3 | **Resolved** | The report, headline, consolidation rationale, and evidence-review trail now use the measured 0.036–0.051 margin and the properly qualified “contrary signal of comparable magnitude” consequence; deployed and cross-model cosine levels are attributed correctly. |
| 4 | **Resolved** | `probe_cap_hit`, review counts, and the invariant-5 reference now agree with the executable contracts and review trail. The invariant cross-reference sweep found no further substantive drift. |

### Findings blocking approval

1. **[BLOCKER] `zikaron_next_group` has two incompatible success-response contracts for `remaining_uuids`.** `design/architecture.md`, “Consolidator tool surface,” declares the success shape as `{group_id, run_id, anchor, anchor_vacated, journal_entries, candidates, shard, serve_count, n_gists_used, remaining_groups}`—with no `remaining_uuids`. The immediately following round-8 prose says `journal_entries` “is the same set as `remaining_uuids` here”; §“Row-level completion” says **every response** carries `remaining_uuids`; §“Serving” again says `remaining_uuids` in *this* response is the served set; `design/consolidation.md`, “Never lose silently,” and `design/overview.md` D32 repeat the every-response contract. An implementer following the signature will omit the field, while one following the prose will return it, and the latter is the only shape that satisfies the documented row-level completion protocol uniformly. Add `remaining_uuids: [uuid, ...]` to the successful `zikaron_next_group` shape and state that it is the UUID projection of `journal_entries` in group order (or explicitly withdraw the every-response claims and make `journal_entries` the sole equivalent for this verb). Align the signature and prose; no state-machine change is needed.

VERDICT: NEEDS_CHANGES

## Response to review round 9

The single blocker is **ACCEPTED**. It is real, it is exactly as narrow as the reviewer says, and it was
introduced by round 8's own remediation — naming the served set gave that set a *second* name in the one payload
where the name could not mean what the protocol says it means.

Taken by the reviewer's **second** option: the every-response claim is withdrawn and scoped, `journal_entries`
is the sole delivery of the set on `next_group`, and no field is added. Reasoning below, because the reviewer
argued the *first* option was "the only shape that satisfies the documented row-level completion protocol
uniformly" and that deserves an answer rather than a preference.

### 1. `remaining_uuids` on `next_group` — ACCEPTED, resolved by scoping the field, not by adding it

**The contradiction is confirmed, and it is wider than one signature.** Four sites said `next_group` carries the
field and one — the signature itself, which is what an implementer types from — omitted it:

| Site | Said |
|---|---|
| `architecture.md` §"Consolidator tool surface", success shape | no `remaining_uuids` |
| same section, round-8 prose on `journal_entries` | "It is the same set as `remaining_uuids` here" |
| `architecture.md` §"Row-level completion" | "Every response carries `remaining_uuids`" |
| `architecture.md` §"Serving" | "`remaining_uuids` in *this* response is the same set" |
| `consolidation.md` §"Never lose silently" | "Every response carries `remaining_uuids`" |
| `overview.md` D32 | "every response carries `remaining_uuids`" |

**Why scoping rather than adding, in three parts.**

(a) *On a serve the field could never take the value it exists to communicate.* The protocol's own sentence is
"a group is `complete` **only when that list is empty**". Round 8 established that the served set is **non-empty
whenever a serve happens**, because step 2 of serving closes an emptied group before step 4 can deliver
anything. So `remaining_uuids` on a `next_group` success would be non-empty on **every** call, by construction.
Adding it would satisfy uniformity of *field presence* while the value carried no signal — the completion branch
a client wrote against it would be dead code. That is uniformity in the name only, which is the weaker half of
the reviewer's own argument.

(b) *"Every response" was already false three ways, so it needed a scope regardless of the signature.*
`next_group` returns three shapes. `{done: true}` and `{busy: true, holder_session, expires_at}` deliver **no
group**, so they have no member set to report; adding the field to the success shape leaves the claim false for
the other two. And on the write verbs the claim needed narrowing in the other direction too: it holds for the
success shape **and** the `conflict` shape — which is load-bearing, since a conflicted call must still be able
to see what is left — but *not* for a call rejected by an error (`not_in_group`, `bad_merge_target`,
`group_expired`), which carries `{code, message, data}` and no member list. Nothing changed on those, so the
list the caller already holds still stands. The fix therefore states the scope on both sides instead of moving
one field.

(c) *One set under two names in one payload is a consistency obligation for nothing.* `journal_entries` and
`remaining_uuids` would be identical on a serve — the same rows, the same instant, inside the same transaction —
so the design would then owe a rule for the case where an implementation lets them differ. This is the same
defect class the round-8 response flagged as accretion (`shard_count`: a cached value that an invariant then has
to police). Declining to add a second representation is the consistent call, and the round-8 flag would have
been hollow if the very next round added one.

**What changed.**

- **`architecture.md` §"Consolidator tool surface", `next_group` gloss.** The "same set as `remaining_uuids`
  here" clause is replaced by the positive statement plus the reason for the omission: `journal_entries` **is**
  this verb's remaining set — its uuid projection is exactly what a write verb would report at that instant —
  and the field is not repeated because a served set is non-empty by construction, so it could never carry the
  empty value that means *complete*. Points at §"Row-level completion". The declared shapes are unchanged, and
  that is now the deliberate reading rather than an accident.
- **`architecture.md` §"Row-level completion", first bullet — the one normative sentence.** Now: every
  `merge` / `promote` / `discard` response carries `remaining_uuids` — members with `disposition IS NULL`, **in
  group order** (which the corpus already defines as total, `(created_at, uuid)`, so the payload is
  deterministic; it was unstated before) — computed at response time from `consolidation_group_member`, in the
  success shape *and* the `conflict` shape. Error responses carry no member list, with the reason. `next_group`
  does not carry the field, with the reason, and its two non-group shapes are named. One place says why; the
  other sites point here.
- **`architecture.md` §"Serving", served-set paragraph.** The served set is now described as *where the write
  verbs' `remaining_uuids` starts* — they recompute it as they disposition members, which is how it shrinks
  within one delivery — and the omission on the serve is stated with its two reasons. Round 8's served-set
  definition, its non-emptiness argument, the re-serve consequence and the frozen-membership paragraph are all
  untouched.
- **`consolidation.md` §"Never lose silently".** Bullet scoped to the three write verbs, success or `conflict`,
  with the `next_group` case named in one clause. Invariant 16 reference unchanged.
- **`overview.md` D32.** Adds "**Narrowed in round 9**": the phrase was false of all three shapes `next_group`
  returns, the field belongs to the write verbs, and repeating it on a serve was *rejected* rather than merely
  omitted. The decision and the row-level completion mechanism are unchanged.
- **`FINDINGS.md`.** The round-8 paragraph said the served set supplies "`remaining_uuids`" — now "the set the
  write verbs' `remaining_uuids` starts from". Round count 8 → 9 in all three places
  (`overview.md`, `design/README.md`, `FINDINGS.md`), with round 9's finding tallied and D32 added to the
  corrected-rationale list, per round 8 finding 4's drift rule.
- Knowledge base `zikaron-design` re-indexed.

**Nothing added, nothing removed.** No table, column, field, event kind, error code, invariant or tool changed.
The state machine, invariant 16's completion condition and the never-lose guard are byte-for-byte as round 4
through round 8 left them; what changed is which verbs a sentence quantifies over.

### Standing note on the residual, so it is not discovered later

A caller that wants "what is left" *without* mutating anything has no verb for it — `next_group` would give it
the answer as `journal_entries`, but only by re-serving and burning a `serve_count`. That is deliberate and
unchanged since round 4: the consolidator is a straight-line loop (serve → decide → write), and the write verbs'
responses tell it what remains after every step it takes. Adding a read-only progress verb would widen D32's
tool surface, which is the user's decision, not a remediation's. Noted here rather than left to be re-derived.

### Accretion watch, second entry

Round 9's finding is itself evidence for the risk the corpus is carrying: the defect was created by round 8's
fix, not by the original design, and it was created by *naming* something — the cheapest kind of change. The
lesson is narrower than "stop adding": when a set gets a name, check every payload that already ships it, and
prefer one name per set per payload. Both entries in this watch (round 8's `shard_count`, round 9's near-miss
duplicate field) are the same shape — a second representation of a value the payload already determines.

## Round 10 — 2026-08-01

### Summary judgment

Round 9 resolves its response-schema contradiction cleanly: `journal_entries` is now the sole representation of the remaining set on a successful `next_group`, while `remaining_uuids` is consistently confined to `merge` / `promote` / `discard` success and conflict shapes. The rationale for rejecting a duplicate field is well argued and accepted. A renewed cross-document sweep found two still-blocking closure defects outside that repair: one reachable consolidator state has no defined error, and D30's promised version-conflict “rate” mixes row and call units while omitting classes of attempts its denominator claims to include.

### Round-9 finding disposition

| # | Status | Judgment |
|---|---|---|
| 1 | **Resolved** | The declared signatures and all normative prose now agree. A successful `next_group` returns the non-empty served/remaining set once as `journal_entries`; `{done}` and `{busy}` have no group set; each write verb returns `remaining_uuids` in group order on success and conflict, while ordinary error shapes carry no member list. Avoiding two names for one set in the same payload is a sounder resolution than adding the duplicate field. |

### Findings blocking approval

1. **[BLOCKER] An authorized member that leaves the active journal after serving reaches a state-legality failure with no defined error or recovery contract.** `design/architecture.md`, §“Validation precedence,” consolidator rung 6 requires “absorb rows still journal rows” but names no error for failure; the error table defines `not_in_group` only for a row outside the persisted group, already dispositioned, or an empty list, and `inactive_row` only for primary-agent `amend`/`retire`. `bad_supersession` cannot cover this generally—`discard` creates no supersession edge. The case is reachable: serve journal row A at v1; a primary agent retires A to v2; a consolidator attempt at v1 receives `version_conflict` and a v2 receipt; a retry at v2 passes group authorization, existence, version, and receipt, then fails rung 6 with no specified code. If the caller instead omits A, it remains in `remaining_uuids` until a re-serve marks it `vacated`, so recovery also cannot be inferred from the payload alone. Resolve narrowly by assigning this condition a stable error (for example, extend `not_in_group` to mean “no longer an actionable active-journal member” at rung 6), defining its precedence/data, and stating that recovery is `next_group`, whose re-validation records `vacated`; or make write-verb re-validation disposition it atomically and return the updated remaining set. Align the error table and row-level-completion prose with the chosen behavior.

2. **[BLOCKER] D30's version-conflict “rate” is dimensionally invalid and its denominator cannot represent the population it claims.** `design/schema.md`, §“The event log, per kind,” emits one `version_conflict` and one `no_receipt` event **per offending UUID**, but §“D30's six signals, as queries” uses `count(kind='version_conflict')` as the numerator while deduplicating the denominator by `op_id` to mutation **calls**. One three-row conflicting `merge` can therefore contribute 3/1 and make the reported rate exceed 100%. The same denominator is labelled “every attempt,” while `design/architecture.md`, §“What a rejected call does and does not change,” says no error other than `version_conflict` or `no_receipt` writes an event, so attempts rejected as `bounds`, `inactive_row`, `bad_supersession`, `not_in_group`, `bad_merge_target`, `group_expired`, and similar are uncountable. This contradicts `design/overview.md` D30 and `design/write-policy.md` §3, both of which promise a rate over every attempted mutation. Resolve either by (a) defining a call-level observable rate—`count(DISTINCT op_id)` for conflict/no-receipt over successful, conflict, and no-receipt call outcomes—and narrowing “every attempt” to that observable population, or (b) adding a one-per-call mutation-attempt event that makes every rejection countable. In either case, keep row-level conflict counts as a separate quantity if desired and use the same unit in numerator and denominator across all three documents.

VERDICT: NEEDS_CHANGES

## Response to review round 10

Both blockers are **ACCEPTED**. Both are the same defect class one more level down, and it is worth naming
because it is now the third consecutive round of it: **a rule that is correct about the case it was written for
and silent where it is nonetheless reachable.** Round 4 called this a closure failure over *states*; round 9
found it over *names*; round 10 finds it over an *error code* and over a *unit*. Neither fix adds a table,
column, event kind, error code, tool, invariant or state transition.

### 1. Rung 6's absorb check had no error — ACCEPTED, resolved by widening `not_in_group`, not by adding a code

**The reachability argument is confirmed, and it is tighter than the reviewer needed it to be: the condition has
exactly one producer.** A row leaves `tier='journal' AND active=1` in only two ways. A consolidation write
(`merge` / `promote` / `discard`) flips `tier` or sets `active=0` **and** dispositions the member in the same
transaction, so a later call naming it is caught at rung 2 as already-dispositioned. Everything else is a
primary agent's `retire`. So rung 6's absorb failure means precisely *a served member a primary agent retired*,
and it cannot be reached on a first attempt: `retire` bumps the version (invariant 8), a version bump deletes
every other receipt for that uuid (invariant 9), so the consolidator's call at the served version is rejected at
rung 4 with `version_conflict`, which hands back the current record and a fresh receipt. The **retry** at the new
version passes rungs 1–5 and lands on rung 6. That is the path the reviewer described, and there is no other.

**Why `not_in_group` rather than a new code, or `inactive_row`.** The row is *vacated in fact and not yet
recorded* — it fails the identical predicate the serve uses to write `disposition='vacated'`
(`architecture.md` §"What serving re-validates"). So it belongs with the conditions that already mean "this uuid
is not something you may act on in this group":

- **One meaning.** `not_in_group` is now defined as *not an actionable member of this group*, covering a
  non-member, an already-dispositioned member, and this case. All three are the same fact to the caller.
- **One payload.** `not_in_group` carries `{group_id, uuids}` and deliberately no state, version or prose, so it
  is not an existence oracle (round 3's finding). Reusing it keeps that property with no new argument. Nor is
  there a disclosure question at rung 6 in any case: a caller that got that far passed the **receipt** check, so
  it already holds that row at that version.
- **One recovery.** `next_group` — the same advice the already-dispositioned case gets.
- **`inactive_row` was considered and rejected.** It is the right *condition* (`active=0`) but the wrong
  *contract*: its `data` is `{uuid, state}`, which the consolidator's payloads must not carry, so one code would
  need two shapes depending on caller class; and its recovery for a primary agent is "give up on this row" while
  here it is "call `next_group`". One code, two meanings, two payloads is worse than one code with a widened
  meaning.
- **`bad_supersession` was never available, and the reviewer's reason for that is right.** It is a rule about a
  supersession *edge* — self-edge, cycle, target already retired outright, edge already set, depth cap — and two
  of the three verbs create no edge at all: `discard` retires outright, and `promote`'s `in_place` form flips the
  row's own `tier`. A condition about the absorb row's tier and activity is not an edge fault, so the code could
  not cover the general case even where an edge happens to exist.

**Why not disposition it inside the rejected call (the reviewer's second option).** Three reasons, in order of
weight. (a) It makes a **rejected call write** `consolidation_group_member.disposition`, which
§"What a rejected call does and does not change" forbids in terms — that rule was itself a round-2/round-4
repair, and this would reopen it. (b) It cascades: by invariant 16's closure property, a disposition that empties
a group **must** close the group in the same transaction, and if that was the run's last open group the run goes
`active → complete` and emits its `consolidate_run` event. An **error** would then end a consolidation run —
state motion on a rejection path far out of proportion to the fault, and an error that is indistinguishable in
its effects from a successful final write. (c) It needs an error response carrying a member list, which round 9
settled the other way on this exact payload family (errors carry `{code, message, data}` and no member set,
because a rejected call changed nothing and the caller's list still stands).

**Recovery is stated, because the reviewer is right that it cannot be inferred from the payload.** `next_group`
re-serves the group; re-validation writes `vacated`; then either the group closes (if that emptied it — round 4's
loop) or the rest is re-served without the row. A caller that simply *omits* the row instead keeps it in
`remaining_uuids`, which is correct rather than a stall: it is still an undispositioned member and only a serve
may say otherwise. The bound is harmless — a group already at `max_group_serves` defers, and the row is never
planned again regardless, because `plan_groups` anchors only on active journal rows. Nothing is lost: the row
left the journal by a path D16 governs.

**What changed** (`architecture.md`, plus one mirrored enumeration in `consolidation.md`; no other document
asserts rung 6 or enumerates the `not_in_group` cases, which was checked by grep across `design/`):

- §"Validation precedence", consolidator rung 6 — now `every absorb row still tier='journal' AND active=1
  (not_in_group)`, where it previously said "absorb rows still journal rows" with no code.
- Same section, three new short paragraphs: the single-producer reachability chain, the recovery, and the
  rejected alternative. Placed immediately after the ladder and before "Why authorization must precede version",
  so a reader of the ladder meets it in place.
- §"Errors", row −32013 — "Raised when" now names the rung-6 condition as the third form of *not an actionable
  member*; `data` unchanged, with the no-oracle note extended by one clause and the recovery named.
- §"Row-level completion" — the error bullet now lists the fourth case and states that the `vacated`
  disposition is written by the next **serve**, never by the rejected write.
- **`consolidation.md` §"Never lose silently"** carries the mirror of that enumeration ("empty subsets, unknown
  uuids and already-dispositioned uuids are errors that mutate nothing"), so it gains the fourth case and the
  same one-clause note. Aligning it here rather than waiting for a round 11 to find it is round 8 finding 4's
  rule applied without being asked.

### 2. D30's version-conflict rate was dimensionally invalid — ACCEPTED, resolved at call level with the population renamed

**Both halves of the finding are correct, and the second is the worse one.** The numerator
`count(kind='version_conflict')` counts **rows** — the event log commits one per offending uuid — while the
denominator deduplicated to **calls**. One three-row conflicting `merge` reported 3 / 1, so a "rate" could
exceed 100%. And the label "every attempt" described a population the store cannot represent: only
`version_conflict` and `no_receipt` write an event when a call is rejected, so calls rejected as `bounds`,
`not_found`, `inactive_row`, `bad_supersession`, `not_in_group`, `bad_merge_target`, `group_unknown`,
`group_complete`, `group_deferred`, `group_expired`, `store_busy`, `index_failed` or `bad_config` are counted
nowhere. `overview.md` D30 and `write-policy.md` §3 both promised the unachievable version.

Taken by the reviewer's **option (a)**. Option (b) — a one-per-call mutation-attempt event — is rejected on
three grounds, all of which survive the fact that it would genuinely make the population countable:

1. It puts a **store write on the cheapest rejection path**. `bounds` is rung 1 precisely because it is decided
   before any state is read; making it write turns the cheapest rejection into a transaction.
2. It cannot satisfy **invariant 10** ("no event outside the transaction it describes"): a rejected call has no
   mutation transaction, so the attempt event would need a standalone one and an explicit exception to an
   invariant that currently has exactly two carve-outs, both narrow and both audited.
3. It still misses the rejection an operator would most want counted. **`store_busy` is by definition the case
   where the store cannot be written**, so no store-resident attempt event can record it. The countability it
   buys is therefore not total either, which removes the argument for paying (1) and (2).

**The fix, and why it is now a true fraction.** Numerator and denominator are both `count(DISTINCT op_id)`. The
three denominator terms — committed mutation calls, conflict-rejected calls, no-receipt-rejected calls — are
**disjoint**, which is what makes each rate ≤ 1 and is now stated with its proof: a call is rejected at the
**first** rung holding any offender, and the version rung precedes the receipt rung in *both* ladders
(invariant 9's own load-bearing ordering), so no call emits both kinds; and a rejected call commits no mutation,
so no call is both committed and rejected. A retry is a separate call with its own `op_id`, which is the
intent — a conflict followed by a successful retry contributes 1 to the numerator and 2 to the denominator.

The row-level count is **kept as a separate, differently-named quantity** rather than deleted: contested rows,
not a rate, with `rows ÷ conflicted calls` reading as "how many rows a conflicting call typically contests".
That is one sentence over an event cardinality the log already has — no new machinery.

**And the population is renamed for what it is** — every **observable** mutation call — with the limit stated
rather than glossed: this measures concurrency among calls that got far enough to be audited, which is the
population D26's one-round-trip retry contract is actually about, and it does *not* measure malformed or
unauthorized write attempts. This is the same discipline the two existing honest limits on the
session-denominated signals already use.

**What changed:**

- **`schema.md` §"D30's six signals, as queries"** — the version-conflict row: numerator now
  `count(DISTINCT op_id)` on both kinds, labelled "calls, not rows, because the denominator counts calls";
  denominator renamed **observable mutation calls**, its three terms unchanged in content but now marked
  disjoint, and the "successes and rejections both appear, so the denominator is every attempt" sentence
  withdrawn.
- Same section, the counting-rules paragraph — extended with the shared-unit rule and the concrete 3 / 1
  failure, plus two short paragraphs: "Why each rate is a true fraction" (the disjointness proof) and the honest
  limit with option (b)'s rejection. Sited here because `write-policy.md` already delegates every numerator and
  denominator to this section.
- **`write-policy.md` §3** — the signal row now reads "over every **observable** mutation call — one that
  committed, or was rejected as a conflict or for a missing receipt", with one clause noting other rejections
  write no event and pointing at `schema.md`. The "Two honest limits" list is untouched, deliberately: those two
  are about the *session* denominator, and filing a third one under that heading would have made the heading
  false.
- **`overview.md` D30** — the parenthetical in the decision cell now says "every **observable** mutation call";
  rationale gains a **"Narrowed in round 10"** note carrying the dimensional failure, the unachievable
  denominator, the fix and the rejected alternative. The *decision* is unchanged: six signals, consolidator
  writes in scope.

### Drift, per round 8 finding 4's standing rule

Round count 9 → 10 in all three places (`overview.md` §provenance, `design/README.md`, `FINDINGS.md`), round
10's two findings tallied, the "corrected in round 2/…/9" pointer extended to 10, and D30 added to the
corrected-rationale list. `FINDINGS.md` gains a round-10 paragraph in the same form as rounds 7–9 and nothing
else; no rationale moved out of `design/`. Invariant references introduced this round were checked against
`schema.md`: 8 (version monotonic), 9 (receipt/version ordering), 10 (events commit with their mutation),
16 (group closure) — all correct. The `vacated` producer set is unchanged, so `schema.md`'s "serve-time vacating
is recorded in state" section and the `disposition` column note needed no edit; both were checked. Knowledge
base `zikaron-design` re-indexed.

### Accretion watch, third entry

Round 10 is the first round whose fixes **reduced** the corpus's conceptual surface rather than adding to it:
one error code absorbed a fourth meaning instead of a fifth code being minted, and one signal lost a promise it
could not keep. Both were available only because the alternatives were spelled out and rejected in place — which
is the pattern worth keeping.

Two observations for the parent, offered rather than acted on:

1. **The rejected-alternative prose is now a substantial fraction of the corpus.** It is load-bearing (it is
   what stops a later round re-proposing a dead option, and twice now it has been the thing that made the right
   answer obvious), but it is also why `architecture.md` is 14k words. If the corpus is ever cut down, the cut
   should be to *relocate* rejected alternatives into `reviews/` — where the argument already lives — not to
   delete them.
2. **`shard_count` (round 5) remains the one mechanism flagged as possibly unneeded** — a persisted value an
   invariant then has to police, added so a reported `{index, of}` could be derived without replanning frozen
   membership. Round 8 flagged it, round 9 and round 10 did not disturb it, and it is not worth touching
   pre-code; it is named here so it does not have to be rediscovered.

**No user decision was reversed, and nothing an earlier round required was removed.** D30's six signals and D32's
tool surface are unchanged; what changed is one error code's stated scope and one signal's unit and population.
## Round 11 — 2026-08-01

### Summary judgment

Round 10 resolves both findings it targeted: the widened `not_in_group` contract now covers the reachable post-retirement state with a coherent no-mutation recovery path, and the version-conflict numerator is correctly call-level with an explicitly limited observable denominator. The rejected alternatives are well argued and accepted. A renewed cross-document pass nevertheless found two D30 blockers: round 10 names its denominator more broadly than the exact query implements, and the separate amend-after-surface signal still does not define a common counting unit.

### Round-10 finding disposition

| # | Status | Judgment |
|---|---|---|
| 1 | **Resolved** | Consolidator rung 6 now returns `not_in_group` for an undispositioned member that has left `tier='journal' AND active=1`; the error table, row-level-completion rule and `consolidation.md` mirror agree that the rejected call mutates nothing and recovery is `next_group`, whose re-validation records `vacated`. Reusing the existing uuid-only code preserves the no-oracle contract, and rejecting disposition-on-error is sound because it would violate the rejection rule and could close a group or run on an error path. |
| 2 | **Resolved** | `version_conflict` and `no_receipt` now use `count(DISTINCT op_id)` against a call-level denominator, and the first-failing-rung rule plus version-before-receipt ordering makes the three terms disjoint. Narrowing away unobservable rejection classes is preferable to adding an attempt event that still could not record `store_busy`. The exact implemented population still needs the naming correction in finding 1 below. |

### Findings blocking approval

1. **[BLOCKER] Round 10's new name “every observable mutation call” includes `remember`, but its exact denominator excludes it.** `design/schema.md`, §“D30's six signals, as queries,” defines the denominator as successful `amend` / `retire` / `merge` / `promote` / `discard` calls plus conflict and missing-receipt rejections; `design/overview.md` D30 and `design/write-policy.md` §3 call that population every observable mutation call. Yet `remember` is an observable committed mutation—it emits a `remember` event, and schema invariant 2 explicitly includes it among logical mutations—while being absent from the denominator because it cannot version-conflict or lack a receipt for a pre-existing row. This is not merely terminology: including high-volume `remember` calls answers a different rate and can materially lower it, so a consumer following the prose and one following the exact query disagree. Resolve by naming the population consistently as, for example, **observable conflict-capable (receipt-gated) mutation calls**, explicitly enumerating the five verbs in all three documents; alternatively include `remember` in the exact denominator and accept the changed estimand. The narrower rename better matches the stated purpose.

2. **[BLOCKER] The amend-after-surface signal still has no defined counting unit and can be implemented as incompatible rates.** `design/schema.md`, §“D30's six signals, as queries,” gives a numerator condition—`surface(X)` followed by `amend(X)` in the same session—but no aggregation, while its denominator is `count(DISTINCT memory_uuid)` globally over surfaced rows. If one memory is surfaced and later amended in two linked sessions, counting qualifying amend calls yields 2 over a denominator of 1; counting distinct memories yields 1/1; counting session-memory opportunities yields 2/2. All are plausible readings, and the first can exceed 100%, defeating the section's promise that explicit numerators and denominators make implementations agree. Define one unit on both sides and the ordering used for “followed by.” The narrowest useful contract is: denominator = distinct `(session_id, memory_uuid)` pairs with a `surface` event in linked sessions; numerator = distinct such pairs having an `amend` event with a later authoritative event order (use `event.id`, or an explicitly defined `(at,id)` order) in the same session. Mirror that unit in `write-policy.md`'s signal gloss.

VERDICT: NEEDS_CHANGES

## Response to review round 11

Both blockers are **ACCEPTED**, both on the reviewer's preferred option, and both in the same one sentence:
**a rate whose two sides do not share a unit — or whose prose names a wider population than its query — is not a
rate.** Round 10 caught that over *rows vs calls*; round 11 catches it over *a name vs its enumeration* and over
*no unit at all*. Neither fix adds a table, column, event kind, index, error code, tool, invariant or state
transition. One term is renamed, one unit is named, and one ordering rule already in the document is cited from
the two places that needed it.

### 1. "Every observable mutation call" included `remember`; the query did not — ACCEPTED, renamed to *receipt-gated*

**The finding is correct as stated, and the reviewer's characterization of the stake is the right one.** Checked
against the files: `schema.md`'s exact denominator was `kind IN ('amend','retire','merge','promote','discard')`
plus the two rejection kinds, while `overview.md` D30 said "every **observable** mutation call including the
consolidator's" and `write-policy.md` §3 said "every **observable** mutation call — one that committed, or was
rejected as a conflict or for a missing receipt". A committed `remember` satisfies that gloss on its face. It is
an observable mutation by the corpus's own definitions — it emits a `remember` event, and invariant 2 names it
first in the list of logical mutations — so the prose promised a denominator the query does not compute. And the
divergence is not cosmetic, exactly as the reviewer says: `remember` is the **highest-volume write verb** in a
design that D30 deliberately biases toward writing, so the two readings differ by the largest available term.

**Taken by the rename, and the reason is stronger than "it matches the query".** Including `remember` would be
coherent — it would just answer a different question — but it would answer a *worse* one, for a reason worth
recording because it is the same failure the linked-session caveat exists to prevent:

- `remember` **cannot reach either numerator.** It names no pre-existing row, so it presents no version and
  requires no receipt; neither validation ladder's version rung nor receipt rung applies to it
  (`architecture.md` §"Validation precedence" lists `amend`/`retire` on one ladder and
  `merge`/`promote`/`discard` on the other, and `remember` on neither). D26 is consistent with this: `remember`
  is receipt-**producing**, not receipt-gated — an own successful write is one of the four ways a receipt is
  minted.
- So admitting it would add a denominator term that is *structurally* incapable of appearing above the line.
  That does not dilute the estimate slightly; it changes what the ratio divides by. Contention would be divided
  by **write volume** — which is precisely what D30's *first* signal measures on purpose.
- The consequence is a signal that moves for the wrong reason. A prompt revision that made agents write more —
  the exact intervention D30 exists to evaluate — would **lower** the reported conflict rate with concurrency
  unchanged, and would do so in the direction that flatters the change. Being wrong in the direction of your own
  hypothesis is the failure this corpus has already engineered against once, in honest limit 2 on the
  session-denominated signals.

So the population is named for the property that actually defines it: **observable receipt-gated mutation
calls** — calls that name a pre-existing row at a version. The estimand is now sayable in one line: *of the calls
that had to present a version and a receipt, how many held a stale one.* The five verbs are **enumerated
wherever the population is named**, per the reviewer's instruction, so no reader has to derive the set from the
gate.

**What changed:**

- **`schema.md` §"D30's six signals, as queries"**, version-conflict denominator cell — renamed **observable
  receipt-gated mutation calls**, the five verbs spelled out with the defining property ("name a pre-existing
  row at a version"), and one sentence stating that `remember` is excluded **by construction, not by
  oversight**. The three terms and the disjointness claim are unchanged.
- Same section, the honest-limit paragraph — retitled to "every observable *receipt-gated* mutation call — not
  every attempted mutation, and not every mutation", and split into **(a)** the pre-existing rejection-class
  exclusion (unchanged in content, including round 10's rejection of the one-per-call attempt event) and **(b)**
  a new short paragraph carrying the `remember` exclusion, its invariant-2 status, the ladder citation and the
  divide-by-write-volume argument.
- **`write-policy.md` §3** — the signal row now reads "every **observable receipt-gated** mutation call — one of
  `amend` / `retire` / `merge` / `promote` / `discard` that committed, or was rejected as a conflict or for a
  missing receipt", and its right-hand cell now names **two** exclusions instead of one, with the `remember`
  clause carrying the reason in brief.
- **`overview.md` D30** — the six-signal parenthetical now says "every **observable receipt-gated** mutation
  call — `amend` / `retire` / `merge` / `promote` / `discard`"; the rationale gains a **"Narrowed again in round
  11"** note whose (a) half carries this finding. The *decision* is untouched: six signals, consolidator writes
  in scope.

### 2. Amend-after-surface had no counting unit — ACCEPTED, the `(session_id, memory_uuid)` pair, with `event.id` ordering

**Confirmed, including the arithmetic.** The numerator was a *predicate* — "`surface(X)` followed by `amend(X)`
in the same `session_id`" — with no aggregation stated, against a denominator of `count(DISTINCT memory_uuid)`.
The reviewer's three readings are all faithful to that text, they give 2/1, 1/1 and 2/2 on the same history, and
the first exceeds 100%. That is a direct contradiction of the sentence at the head of the very table
("stated as an explicit numerator and denominator so two implementations report the same number"), which makes
it a worse defect than its size suggests: the section's promise was the thing that failed.

**The pair is the right unit on the merits, not merely because it is well-defined.** The opportunity D11
describes is *this session was shown this memory and could repair it*. That gives the three edge cases the
answers the question wants:

- the same memory surfaced in **two** sessions is **two** chances — a repair opportunity the second session had
  independently of the first, which a per-memory denominator would silently discard;
- a memory surfaced **five times in one session** is **one** chance — the push repeating itself is not five
  independent opportunities, and D12's hook fires once per user message, so a long task inflates this freely;
- **two amends in one session** count **once** — the signal asks *whether* the loop fires, which is exactly what
  D30's table row promises ("whether D11's repair loop ever fires at all").

**Ordering is `event.id`, and this needed no new mechanism.** The document already settles it, three paragraphs
above the table: "across concurrent calls only `at` and `id` order events, and `id` is authoritative because
`at` can collide." So "followed by" now means *strictly greater `event.id` than the pair's earliest `surface`
row*, citing the rule rather than restating it. The reviewer's alternative — an explicitly defined `(at, id)`
order — was not taken because `id` alone is already total and already authoritative here; adding `at` as a
leading key would introduce a second ordering to keep consistent with the first for no gain.

**What changed:**

- **`schema.md` §"D30's six signals, as queries"** — the amend-after-surface row: denominator is
  `count(DISTINCT (session_id, memory_uuid))` over `kind='surface'` rows within linked sessions, glossed as *one
  opportunity per (session shown the memory, memory shown)*; numerator is `count(DISTINCT (session_id,
  memory_uuid))` over the denominator's pairs that also carry a qualifying `amend`, with the `event.id`
  comparison stated inline. The linked-session restriction and its coverage caveat are unchanged.
- Same section, one new paragraph — "A rate over pairs deduplicates by the pair", stating the defect, the three
  incompatible readings with the 2/1 arithmetic, why the pair is the unit, the three edge cases, and the
  ordering rule. Sited immediately after round 10's rows-vs-calls paragraph, because the two are the same rule
  applied to different units.
- **`write-policy.md` §3** — the signal row now reads "amend following a surface, counted once per **(session,
  memory) pair** that was surfaced — the pair is the unit on both sides, and 'following' is `event.id` order",
  per the reviewer's instruction to mirror the unit.
- **`overview.md` D30** — the parenthetical now says "amend-after-surface per surfaced (session, memory) pair";
  the round-11 rationale note's (b) half carries the defect and the fix.

**One honest limit added, one sentence, because naming the unit made it visible.** The signal counts `amend`
only, so a surfaced memory the agent repaired by **`retire`** — legitimate under D11 and D16, and arguably the
better repair for a memory that is simply wrong — lands in the retire signal instead. The rate is therefore a
**floor** on repair, not a measure of it. This does not change either side of the fraction and is not a new
mechanism; it stops the number being read as "how often D11 works", which the pair unit now makes tempting.

### Two adjacent gaps of the same class, closed unasked

Round 8 finding 4 established a standing rule that drift found in one place should be swept in all of them.
Applying it here surfaced two more instances of round 11's own defect class, both in the same section:

1. **The dedup signal's "later" was undefined** — its numerator classifies on "a later `amend` on `X` in the
   same `session_id`" with no ordering, one table row above a signal whose ordering the reviewer just required
   be pinned. Now "`event.id` order, as above". Its unit needed no change and is now stated rather than implied:
   the `dedup_offered` **row** on both sides — one offer, one classification — which is why this signal never had
   the >100% failure.
2. **Two places still described the amend-after-surface access path as a plain `(memory_uuid, at)` lookup** —
   the `idx_event_uuid_at` comment in the DDL, and the "Why `surface_call` exists as a separate kind" paragraph.
   Both are now accurate: the index **locates the rows about one uuid**, and the signal then groups by
   `(session_id, memory_uuid)` and orders by `event.id`. Left alone, these would have been the round-12 finding,
   and they are the more dangerous form of the defect — an implementer reads the DDL comment, not the prose.

### Drift, per round 8 finding 4's standing rule

Round count 10 → 11 in all three places (`overview.md` §provenance, `design/README.md`, `FINDINGS.md`), round
11's two findings tallied, the "corrected in round 2/…/10" pointer extended to 11, and D30 named again in the
corrected-rationale list. `FINDINGS.md` gains a round-11 paragraph in the form rounds 7–10 use and nothing else;
no rationale moved out of `design/`. Invariant and cross-reference numbers introduced this round were checked
against `schema.md`: invariant 2 (every logical mutation is one transaction, `remember` included — the reviewer's
citation, verified), invariant 9 (receipt/version ordering), invariant 10 (events commit with their mutation);
`architecture.md` §"Validation precedence" verified to list `remember` on neither ladder. `architecture.md`
§"Both clients must resolve the same label" names the two cross-client signals but asserts no unit, so it needed
no edit; checked. Knowledge base `zikaron-design` re-indexed.

### Accretion watch, fourth entry

Round 11 net **removed** conceptual surface, like round 10: one population lost a name it could not honour, two
signals gained units they already needed, and the ordering primitive was **reused** rather than duplicated —
the reviewer offered a new `(at, id)` order and it was declined because `id` alone already suffices. Total
additions: four short paragraphs and six clauses, no mechanism.

The one thing worth flagging to the parent, because it is now a pattern rather than an incident: **rounds 9, 10
and 11 have all been about D30's six signals**, and all three found the same class of defect — a quantity named
in prose more loosely than the query that computes it. Three consecutive rounds on one section suggests the
instrumentation spec is the least-settled part of the corpus, and there is a structural reason: it is the only
part that has *no consumer yet*: schema and architecture claims get pressure-tested against invariants and
ladders, while a signal definition is checked only by reading it. The cheapest real fix is not more review — it
is writing the six queries as actual SQL against the v0 schema during the build, where a unit mismatch becomes
a type error or an obviously wrong number. Recommend the parent treat "the six signals as executable SQL" as a
build-time deliverable of `zikaron-core` rather than another design round.

`shard_count` (round 5) remains the one mechanism flagged as possibly unneeded; rounds 9, 10 and 11 did not
disturb it, and it is still not worth touching pre-code.

**No user decision was reversed, and nothing an earlier round required was removed.** D30's six signals and the
consolidator's inclusion are unchanged; what changed is one population's name and enumeration, and two signals'
counting units.
## Round 12 — 2026-08-01

### Summary judgment

Both round-11 findings are resolved. The revised D30 populations and units now agree across `schema.md`, `write-policy.md`, `overview.md`, and `FINDINGS.md`; the event shapes and validation ladders make the stated queries implementable, and the rejected `(at, id)` ordering alternative is correctly declined because `event.id` is already the corpus's total authoritative event order. A renewed pass over all nine design documents, the working-memory drift file, and the cited benchmark found no new soundness, consistency, evidence-fidelity, or buildability blocker.

### Round-11 finding disposition

| # | Status | Judgment |
|---|---|---|
| 1 | **Resolved** | The version-conflict denominator is now consistently named **observable receipt-gated mutation calls** and explicitly enumerates `amend`, `retire`, `merge`, `promote`, and `discard` in `design/schema.md` §“D30's six signals, as queries,” `design/write-policy.md` §3, and `design/overview.md` D30. Excluding `remember` is coherent rather than opportunistic: it names no pre-existing row, reaches neither version nor receipt validation, and therefore cannot enter either numerator. The exact denominator remains call-level via distinct `op_id`, including multi-row consolidation events. |
| 2 | **Resolved** | Amend-after-surface now uses distinct `(session_id, memory_uuid)` pairs on both sides, restricts them to linked sessions, and defines “followed by” as an `amend` whose `event.id` is strictly greater than the pair's earliest `surface`. `design/write-policy.md` and D30 mirror the unit, while the event schema supplies one keyed `surface` row per delivered memory. The response's rejection of `(at, id)` is well argued and accepted: `event.id` alone is total, monotonic under the single-writer rule, and already declared authoritative where timestamps collide. |

### Findings

1. **[NITPICK] Qualify the unmeasured write-volume superlative.** `design/overview.md` D30's round-11 rationale and `FINDINGS.md` §“Round 11's two blockers” call `remember` the “highest-volume” verb, but this is a pre-code corpus with no operational verb-frequency data. The argument does not need the superlative: adding any structurally numerator-ineligible `remember` volume changes the estimand and lets a writing-rate intervention move the conflict rate for the wrong reason. On the next edit, remove “highest-volume” or change it to “expected/potentially high-volume.”
2. **[NITPICK] This review mechanically advances the provenance count.** `design/overview.md`, `design/README.md`, and `FINDINGS.md` consistently and correctly said eleven rounds before this section was appended; they will say twelve only after the next provenance refresh. This is housekeeping created by the review itself, not a defect in the reviewed mechanisms and not a reason to withhold approval.

VERDICT: APPROVED

## Operator finding — 2026-08-01: the ancestry rung's premise was measured false

**This is not a review round.** It is a disposition note, appended so that a reader working back through rounds
3–8 is not misled by findings whose mechanisms no longer exist. Nothing below reverses a review judgment: every
finding named here was correct about the mechanism it examined.

**What was measured.** A hook probe registered on `agentSpawn` and `userPromptSubmit` for two agents (five
firings; raw log `/tmp/zikaron-hookprobe/log-final.jsonl`), plus direct reads of `/proc/<pid>/environ` on live
kiro, hook and MCP-server processes. Result: **`KIRO_SESSION_ID` is exported into every process kiro spawns**,
including live MCP servers, is absent from kiro's own processes, and names the session's own transcript files
under `~/.kiro/sessions/cli/`. So it is the canonical session id, and both thin clients can read the same one out
of their own environment.

**Consequence.** The session-label ladder's rung 2 — deriving the MCP client's label by matching `/proc` ancestor
chains against hook-published registrations — existed for one case, *the harness exports nothing to the MCP
process*, and that case does not arise. The ladder is now two rungs (`harness`, `minted`) and `label_source` is a
pure function of the label (`^zk-` ⇒ `minted`, else `harness`).

**Findings whose remediation is now deleted.** Listed so the trail stays navigable, not to reopen them:

| Round | Finding | Status of the remediation |
|---|---|---|
| 3 | *Stable is not shared* — two clients each holding a stable label is not the same as sharing one | **Concern upheld, mechanism replaced.** Sharing is now by construction (one env var), not by derivation |
| 5 | The ancestry registration named no sender | **Deleted** with the registration: no `register_session` RPC, and the warm helper's only job is start-if-absent |
| 6 | The envelope made rung 2 unreachable; `label_source` was a client self-report | **Partly deleted.** The bootstrap envelope survives (env var absent ⇒ `session_id: null`); the reserved `zk-` namespace survives and is now the whole of `label_source` |
| 7 (a) | Syntax is lossy: a derived label is byte-identical to a harness one | **Deleted.** With no derived rung there is no lossy case. `session_client`, the resolution preamble's store write, durability-precedes-adoption and the rung-0 `store_busy` all go |
| 8 (a) | *First resolution wins* named no winner for the one conflict it permitted | **Deleted** with the table it was about |
| — | Invariant 21 (`event.label_source` must agree with the stored row) | **Withdrawn.** Number retired rather than reused, so every `invariant N` reference in this trail still points where it pointed. v0 holds invariants 1–20 |

**A rule was added, not only removed.** The same probe showed hooks **do** fire for subagent sessions, carrying
the subagent's own id in the payload while `KIRO_SESSION_ID` still holds the top-level one. Unaddressed, a
`userPromptSubmit` push would inject five similarity-chosen gists into the **consolidator's** context — which is
`search`, the tool D32 withholds from it, arriving through a door D32 does not guard, and therefore the same class
of defect as round 3's finding that authorization-after-version-check turned `version_conflict` into a `fetch`.
The hook now compares the two ids and prints nothing when they differ, on both hook events. The over-breadth is
stated rather than hidden: the payload carries no agent identity, so all subagents are suppressed.

**The method lesson, recorded because it is about this review loop.** Rounds 3–8 found eight genuine internal
defects in a mechanism that should not have existed, and fixed all eight correctly. Internal review
pressure-tests *consistency*; it cannot test a premise about the environment. The corpus's own phrase "specified
but unverified" was the only handle that made this findable, which argues for treating that phrase as an action
item — an assumption with a named cheap experiment — rather than as a caveat.

Full specification: `design/architecture.md` §"Both clients resolve the same label" and §"Subagent sessions".

## Round 13 — 2026-08-01

### Summary judgment

The measured two-rung collapse and subagent suppression rule are sound for the observed kiro contract, the PDF-to-transcript provenance replacement is complete, and whole-session event pruning preserves the joins it is intended to protect. The delta is not build-ready yet: `signal_horizon_days` does not actually bound either join, D33 leaves contradictory sources for several configuration values, and both `(session_id, pid)` ownership and `client_kind` receipt scoping still have live session-only contracts.

### Findings

1. **[BLOCKER] `signal_horizon_days` does not close either open-ended join as currently specified.** `design/schema.md`, §“D30's six signals, as queries” and §“`signal_horizon_days`” (around lines 624–632 and 725–741), still define a qualifying `amend`/`retire` as any *later* event by `event.id`; the horizon paragraph only says an event that is “older than the horizon” and *still* unresolved is classified unresolved. A day-31 amend therefore stops being “still unresolved” and retroactively changes the old classification—the exact drift the new key is supposed to prevent. `design/write-policy.md`, §3 (around lines 238–239), repeats the same “older than … and still unamended” rule. Define a fixed deadline from the earlier event: only follow-ups with `event.at <= earlier.at + signal_horizon_days` may resolve it; later events never alter that classification. Also define the denominator/reporting state explicitly: events whose deadline has not passed are `pending` and excluded from the resolved/ignored rate (or reported as a separate class), while matured events are permanently classified using only the bounded interval. Apply that rule to both the dedup offer (including both amend and retire needed for “fully resolved”) and amend-after-surface queries.

2. **[BLOCKER] D33's effective-config contract has mutually exclusive homes and several live references still read moved keys from `meta`.** `design/architecture.md`, §“What the file may not change” and store creation (around lines 335–357), says a *file* may disagree on `embed_model`/`embed_dim`, can request a reindex, and can set a new store's model; but `design/schema.md`, §“Configuration keys” (around lines 387–463), rejects unknown file keys and provides no TOML key for either value. Thus no conforming file can exercise the hard-mismatch or new-store selection paths. The same section calls the list “nineteen operator-settable keys,” although the shown TOML/table has twenty entries: nineteen moved keys plus dual-homed `chunk_max_tokens`. In addition, live consumers still name the old home: `design/architecture.md` `zikaron_remember` uses `meta.dedup_max`/`meta.dedup_threshold` (lines 611–613), the service surface uses `meta.fusion_depth` (line 1139), and `bad_config` covers only malformed `meta` (line 1120); `design/schema.md` calls the new horizon `meta.signal_horizon_days` (line 731) and the two penalties “`meta` keys” (line 760); `design/overview.md` D5, D22 and D30 likewise retain `meta.fusion_depth`, “the same `meta` keys,” and “one new `meta` key.” Pick one implementable model contract and make it exhaustive: either add `embed_model`/`embed_dim` to a named TOML section and update the counts/dual-home rules, or remove the impossible file-request claims and define the hard comparison as deployed runtime embedder versus store `meta`. Then change every moved-key consumer to “effective config”/`schema.md` §“Configuration keys,” widen `bad_config` to both file resolution and five-key `meta` validation with its documented `{file,key,...}` payload, and describe the list as twenty file keys (nineteen file-only plus `chunk_max_tokens`). A grep over all nineteen moved names should be part of this edit; the locations above are current contradictions, not merely terminology.

3. **[BLOCKER] `(session_id, pid)` ownership is not enforced by the mutation authorization ladder and `pid` is not a required owner component.** `design/architecture.md`, §“Consolidation lifecycle” correctly defines the owner pair (lines 817–835), but §“Validation precedence” authorizes a consolidator group when its run belongs only to the calling `session_id` (around lines 1037–1044). The error table's `group_expired` row says “belongs to another session” (line 1112), and §“Service RPC surface” says an active run belonging to another session is busy (lines 1148–1152). `design/schema.md`, invariant 17, repeats “different session” (around line 1052). This is not harmless prose: two consolidators in one top-level session also share `client_kind='consolidator'` receipts, so a session-only write check lets the second worker mutate the first worker's served group if it has a `group_id`, defeating the one-worker guarantee even though `next_group` itself was pair-scoped. Make every run/group authorization and busy/expiry test compare both stored fields with the normalized envelope, update those error/RPC/invariant clauses to “different `(session_id, pid)` owner,” and preferably return `holder_pid` with `holder_session` so same-session contention is observable. Also make the dependency enforceable: `design/architecture.md` §“Resolution is a preamble” currently validates `kind` and `session_id` but not `pid`, while `consolidation_run.session_id` and `.pid` are nullable in `design/schema.md`. Require and validate a positive integer `pid` for consolidator calls and persist both owner columns `NOT NULL` (or specify an equally strict normalization); otherwise `(NULL,NULL)` or an omitted pid collapses the new identity back to session-only behavior.

4. **[BLOCKER] The receipt error contract still tests the pre-delta key.** `design/architecture.md`, error `−32002 no_read_receipt` (line 1107), says the missing lookup is `(session, uuid, version)`, omitting `client_kind`, even though `design/schema.md` invariant 9 and the new primary key require `(session_id, client_kind, memory_uuid, version)`. This is the implementation-facing error table and directly conflicts with the intended fix. Change the error row and both validation ladders' receipt wording to the full key, and state once that `fetch`, `next_group`, conflict payloads and `own_write` upserts always copy `client.kind` from the normalized request that minted the receipt. Keep the existing idempotent upsert rule for a re-served group; it is correct with the expanded key.

5. **[IMPROVEMENT] The derived `label_source` is provenance only if clients enforce the reserved namespace.** `design/architecture.md`, §“`label_source` is derived, not stored” and §“Trust model” (around lines 180–194 and 145–154), claims `^zk-` proves the service minted the label, while the service accepts any shape-valid transport-supplied string and does not authenticate it. A harness-provided `KIRO_SESSION_ID=zk-external` is therefore classified `minted`; the prefix makes the function total syntactically, but not truthful to its stated question (“did the harness supply this label?”). No current authorization depends on this distinction, so this does not require restoring stored provenance. Add a client contract that a harness/environment label in the reserved `zk-` namespace is non-conforming and must be treated as absent (bootstrap and adopt a fresh service label), and narrow the audit claim to conforming clients; alternatively rename the values as lexical classes rather than origin provenance.

VERDICT: NEEDS_CHANGES
## Round 14 — 2026-08-01

### Summary judgment

Round 13 findings 4 (`no_read_receipt`) and 5 (`label_source`) are resolved; findings 1 (horizon), 2 (D33), and 3 (owner pair) are only partially resolved. Before code is written I would still require four concrete fixes: make the dedup deadline states exhaustive and stable, make configurable `embed_dim` construct the matching `vec0` width, remove the remaining live `meta` homes for moved keys, and repair invariant 17's last session-only busy test. This is the capped final review, so those four items are the complete remaining delta list rather than the start of another review loop.

### Round 13 disposition

| Round 13 finding | Status | Basis |
|---|---|---|
| 1 — bounded signal joins | **Partially resolved** | Both joins now carry event-order and deadline bounds, and amend-after-surface has a sound pending exclusion. The dedup classification is not yet exhaustive or stable before maturity. |
| 2 — D33 homes and stale `meta` references | **Partially resolved** | The three dual-homed file keys, creation seeding, hard comparison, counts, and widened `bad_config` exist. A configurable dimension still conflicts with the literal `vec0` DDL, and several live consumers still call moved values `meta` keys/parameters. |
| 3 — owner-pair enforcement | **Partially resolved** | The envelope, table nullability, main lifecycle, authorization ladder, error row, RPC test, and payload shapes use `(session_id, pid)`. Schema invariant 17 retains one normative session-only busy predicate. |
| 4 — receipt error key | **Resolved** | `−32002 no_read_receipt` uses `(session_id, client_kind, memory_uuid, version)`, matching invariant 9. |
| 5 — derived `label_source` | **Resolved** | The reserved-namespace client contract, conforming-client scope, non-authorization caveat, lexical-class interpretation, and `minted` rung agree. |

### Findings

1. **[BLOCKER] The dedup deadline classification can still change before maturity and does not cover every in-window outcome.** In `design/schema.md` §“D30's six signals, as queries” (around line 645), an in-deadline `amend` without an in-deadline `retire` is immediately `amended-but-duplicate-left-live`; a later in-deadline `retire` then upgrades that same offer to `fully resolved`. That contradicts §“`signal_horizon_days`” (around lines 755–776), which says the deadline makes answers permanent and that unresolved pre-deadline cases are pending. A `retire` inside the deadline without an `amend` is not classified at all: `fully resolved` needs both, the partial class needs the amend, and `matured-ignored`/`pending` are defined as neither. `design/write-policy.md` §3 (around line 238) mirrors the same gap, while the horizon prose also says “both queries” report three numbers despite the dedup query naming four states. Make the dedup state machine mutually exclusive and exhaustive: `fully resolved` may close as soon as both bounded events exist; every not-yet-full offer remains `pending` until `now > deadline`; at maturity classify all four `(amend_seen, retire_seen)` combinations, either assigning retire-only explicitly to an existing class or naming it separately. State the resulting number of reported classes and take the rate only over matured outcomes.

2. **[BLOCKER] A non-default `embed_dim` can be accepted for a new store but cannot create the schema promised for it.** `design/schema.md` §“Configuration keys” (around line 456) permits any `embed_dim ≥ 1` and says a fresh store uses it, while §“Dense index” (line 105) unconditionally executes `CREATE VIRTUAL TABLE memory_vec USING vec0 (embedding float[384])`. `design/architecture.md` §“What the file cannot change silently” and store creation (around lines 353–375) freeze the effective value into `meta`, so `embed_dim = 768` would produce `meta.embed_dim = 768` beside a 384-wide table, violating the fixed-width contract before the first vector is written. Make the DDL an explicit creation/reindex template using the validated effective dimension (and verify the loaded model actually emits that width), or constrain v0's file key to exactly 384. For a dimension-changing reindex, state that the recreated `vec0` width and the eventual `meta.embed_dim` are the requested dimension under invariant 3's unavailable window.

3. **[BLOCKER] D33's moved-key home is still contradictory at live implementation sites.** The remediation fixed the named `meta.X` references but missed generic ones: `design/schema.md` says all three cosine cutoffs are `meta` values (around line 378), calls `supersession_penalty` and `retired_penalty` separate `meta` keys (around line 804), and describes `fusion_depth` changing through `meta` in invariant 20 (around line 1142); `design/architecture.md` says consolidation planning uses the store's `meta` parameters (around line 827) and still points dedup behavior to `schema.md` §`meta` (around line 630); `design/overview.md` D30 still calls `signal_horizon_days` “one new `meta` key,” and D33 still singles out only `chunk_max_tokens` as living in both (lines 131 and 134). These are moved file keys, except for the three explicitly dual-homed keys, and following the current prose would recreate missing-row reads or make grouping depend on the wrong source. Change each live consumer to the effective config, update D33 to name all three dual-homed keys, and grep for generic phrases such as `` `meta` key/value/parameter `` in addition to `meta.<name>`.

4. **[BLOCKER] Schema invariant 17 still defines busy-ness by session rather than by owner pair.** `design/schema.md`, invariant 17 (around lines 1093–1097), says only an active unexpired run belonging to a “different session” yields `{busy: true}`. That is an implementation-facing invariant and directly conflicts with `design/architecture.md`'s corrected lifecycle, validation ladder, error row, and RPC surface: a second consolidator in the same session but with a different pid must also be busy. Replace the predicate with “different `(session_id, pid)` owner” and mirror the full `{busy: true, holder_session, holder_pid, expires_at}` shape there so the schema invariant cannot reintroduce the session-only implementation.

VERDICT: NEEDS_CHANGES

## Round 15 — 2026-08-01

### Summary judgment

Round 14 findings 2–4 are closed: the width-bound `vec0` creation/reindex contract agrees with invariants 3 and 11, moved keys now resolve from the effective config except for the three explicitly dual-homed keys, and invariant 17 uses the full `(session_id, pid)` owner. The dedup query and horizon prose now define a stable, exhaustive state machine, but the summaries that are supposed to mirror it still publish the old three-outcome contract, so the corpus is not yet safe to implement as one specification.

### Findings

1. **[BLOCKER] The dedup state machine is correct in `design/schema.md` but still inconsistent at its other live descriptions.** `design/write-policy.md` §3 (the “dedup near-miss offered” row) still lists only `ignored / amended-but-duplicate-left-live / fully resolved`, omits `duplicate-discarded-without-amend`, says an offer still inside the deadline is pending without preserving the `A ∧ R` early-close exception, and defines ignored only for “none”; `design/overview.md` D15 and D30 likewise still say the instrument distinguishes only those same three matured outcomes. This leaves prose-following implementations unable to report the fourth matured class and gives two answers for an in-deadline fully resolved offer. Mirror the schema contract at all three sites: `A ∧ R` closes early as fully resolved; every other offer is pending through the deadline; after maturity name all four combinations including `¬A ∧ R = duplicate-discarded-without-amend`; report the rate over matured outcomes only.

VERDICT: NEEDS_CHANGES

## Round 16 — 2026-08-01

### Summary judgment

Round 15's sole blocker is closed: `design/write-policy.md` §3 and `design/overview.md` D15/D30 now mirror the canonical four-outcome dedup contract in `design/schema.md`. The scoped edits introduce no new inconsistency; there are no open blockers before implementation.

### Findings

1. **No findings.** All scoped sites use the same four matured class names — fully resolved, amended-but-duplicate-left-live, duplicate-discarded-without-amend, and ignored. The state-machine descriptions agree that `A ∧ R` closes early as fully resolved, every other offer remains pending and excluded from the rate through the bounded deadline, and the rate covers matured outcomes only; nothing in the edited contract still implies three outcomes or an unbounded later follow-up.

VERDICT: APPROVED