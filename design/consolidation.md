# Consolidation — v0 spec

> Settled with the user 2026-08-01. Summarized as **D29** in `FINDINGS.md`; this is the build contract.
> Trigger is D10 (manually-invoked skill spawning a subagent); the tier split is D3; the "only extra LLM"
> constraint is D2/D7.

## The problem
Journal entries accumulate unconsolidated. Consolidation must decide, for each new observation, whether it
merges into an existing long-term memory or becomes a new one. Per D2 the primary agent never pays for
this; per D7 **code selects the candidates and the model exercises judgment**.

The open part was *grouping*: what set of journal entries and long-term records does the consolidator see
in one call?

### Rejected: model-side grouping
`~/Memory` shows the model everything and lets it group in one call — its original code-side clustering
design was "simplified" to this form (never benchmarked against it). Rejected here on **scale**: Zikaron
expects far more memories, and longer ones, than a character agent's episodic store.

### Rejected: grouping by session
Considered and rejected as a borrowed assumption that does not transfer. In `~/Memory` a session is a
meaningful narrative unit because the memories *are* events and the session is the episode. In Zikaron a
session boundary is an accident of when the developer sat down. It is wrong on both axes simultaneously: it
fuses unrelated lessons from one long session spanning three tasks, and it separates the protobuf lesson
learned today from the protobuf lesson learned three weeks ago — exactly the pair whose merge creates
durable knowledge. Tribal knowledge is defined by surviving across sessions, so the grouping axis must be
topical.

## The asymmetry that shapes the design
The grouping problem splits into two halves that are **not symmetric**:

- **journal → long-term adjacency is retrieval.** Already built, cheap, needs only a score/rank cutoff.
  This is what D7 always meant by "adjacency".
- **journal → journal grouping is clustering.** Needs a threshold, a linkage rule, and an ordering. This is
  the genuinely hard half — and the half that got dropped next door.

We cannot avoid the second, only shrink it.

## Mechanism: retrieval is the adjacency function, everywhere

Planning is a **pure function of the store plus its parameters** — same store, same groups, every time. That
is not decoration: a nondeterministic partition changes what the model is asked, so two runs could reach
different long-term records from identical inputs and neither would be reproducible.

1. **Anchor.** For each unconsolidated journal entry (`tier='journal' AND active=1`), run the **existing
   hybrid search** (D5/D20/D28, with `design/retrieval.md`'s eligibility predicate and total order) against
   the long-term tier. This is an **internal query** in the sense of `retrieval.md` §"Two kinds of query":
   the dense arm uses the entry's **first chunk embedding**, and the lexical arm uses the entry's own
   `gist + content` through the same term constructor — both halves named, because the argument two paragraphs
   down rests on the lexical one. The **top-ranked** long-term record whose `s(entry → record)` is
   `≥ anchor_cutoff` (default **0.65**; the directed quantity, the per-cutoff direction table and the distance
   conversion are all in `schema.md` §"Configuration keys") is the entry's anchor. Entries sharing an anchor form one group
   *with* that record. The consolidator then
   faces exactly the right decision: here is an existing memory and every new observation bearing on it —
   merge, or split off something new.

   **Candidate long-term rows are additionally restricted to `active = 1`.** This is one of the three
   documented consumer filters on the shared eligibility predicate — the complete list is `schema.md`
   §"Consumer filters", where it is stated alongside dedup's and orphan adjacency's so no divergence between
   read paths is left to be discovered at a call site. The reason: every long-term row shown here is a row
   `merge` may be asked to *rewrite*, and rewriting a historical row is incoherent — `superseded_by` is
   immutable once set (invariant 6), so a retired row given fresh prose would be neither the current record
   nor a faithful historical one. Little is lost: a superseded row's replacement is itself active long-term
   and will normally rank in its place. Historical rows stay fully visible to `search`, `fetch` and push;
   they are simply not offered as targets.

   The hybrid decides *which* record is the candidate and the cosine floor decides *whether* it is close
   enough. Both halves matter, and the lexical half is worth stating at exactly its true strength, because an
   earlier draft overstated it while a later section correctly hedged it — a contradiction inside one document.
   The precise position:

   - **Mechanically**, the lexical arm treats `WidgetV1` and `WidgetV2` as **different terms**: under
     `unicode61` each is a single alphanumeric run, so a query term for one does not match the other at all.
     That is a tokenizer property, checkable rather than measured, and what it supplies is an **exact-token
     signal that does not depend on the dense score** — which matters because the dense arm's discrimination
     index on exactly this contrast is 0.194–0.233.
   - **What is not established** is that this rescues the *fused* result. The instrument tested four embedders
     and **no lexical arm**; the blind set's `near_miss` category is saturated at 0.9881 for the lexical arm,
     the dense arm and the hybrid alike, so it separates nothing; and `retrieval.md` §"The known defect in this
     design" measures fusion as decided by arm agreement, with **960 of 960** top-5 slots held by documents both
     arms returned. So a lexical-only win does not automatically survive RRF. Nor does the tokenizer fact reach
     as far as the whole query: a real lexical query carries every other term the two memories share, and
     whether BM25 then ranks the right record ahead of its twin — one differing term against many shared ones —
     is untested too.
   - So the honest claim is: **lexical matching contributes an exact-token signal independent of the weak dense
     signal, and whether that signal changes the fused result is unmeasured.** Saying it "keeps a `WidgetV1`
     entry off a `WidgetV2` record" asserted the outcome. Calling it "the only thing that *can* discriminate"
     was the next draft's error and no better: exclusivity does not follow from a tokenizer property either —
     the dense signal is measured *weak*, in 14/14 blocks with the sign right, not absent — and the claim
     smuggled back in the certainty round 4 removed. What is asserted here is the mechanism and the gap.

   The floor is what stops a store with three long-term records from anchoring everything to whichever one
   happens to rank first.
2. **Cluster the orphans, then check cohesion.** Entries with no anchor above cutoff are grouped among
   themselves using the same hybrid retrieval — each journal entry is a query over the other journal
   entries, again with the first-chunk embedding on the dense arm and its own `gist + content` on the lexical
   one.

   **The candidate pool here is filtered to `tier='journal' AND active=1`, excluding the querying row
   itself** — the third of `schema.md` §"Consumer filters", and the reason is that this filter *is* the
   definition of a group member. A superseded or already-promoted journal row can never become a member, so
   letting it hold one of the `mutual_k` ranks would displace a row that could, silently shrinking the graph
   in the small-journal case where it is already sparsest. Excluding self is not pedantry either: a memory is
   its own nearest neighbour, so without it every row would spend one of its K slots on itself.

   An edge A↔B is drawn only when **both** conditions hold:
   **mutual top-K** (A in B's top-`mutual_k` *and* B in A's, default K=**5**) **and**
   **both directed scores clear the floor**:

   > `s(A → B) ≥ orphan_edge_cutoff` **AND** `s(B → A) ≥ orphan_edge_cutoff`
   > — equivalently `min(s(A → B), s(B → A)) ≥ orphan_edge_cutoff` (default **0.65**).

   **The directionality is not pedantry, and writing this as `cos(A, B)` was a real defect.** `s(X → Y)` is
   defined in `schema.md` §"Configuration keys" as the best cosine between **X's first chunk** and **any chunk of Y**, so it
   is asymmetric whenever the two memories have different chunk counts — X offers one vector, Y offers its
   best of many. A spec that says `cos(A, B)` leaves two conforming implementations free to pick different
   directions, which changes which edges exist and therefore which groups the consolidator is shown. `min` is
   the right symmetrization here for the same reason the test already demands mutuality: an edge should require
   agreement from both endpoints, and the conservative direction is the safe one because an over-split costs one
   extra call while an under-split manufactures a false record. `anchor_cutoff` and `dedup_threshold` need no
   symmetrization because those relations *are* directional by construction — an entry looks for a record, a new
   row looks for what it may duplicate — and `schema.md` names the direction of all three in one table.

   **Stage 2 consumes this same edge relation and computes no score of its own**, so the definition applies
   there unchanged. Acceptance test alongside the chain case: a pair where `s(A → B) ≥ cutoff > s(B → A)` must
   produce **no** edge, and therefore must not be grouped.

   The similarity floor is not redundant with mutuality, and leaving it out was a latent defect: in a journal
   of six rows with K=5, *every* row is in every other row's top-5, so the mutual graph is complete and the
   whole journal fuses into one group. A rank test cannot express "not actually related" when there is
   nothing else to rank against. Then **two stages**, because one is not enough:
   - **Stage 1, components.** Take connected components of the mutual graph. Cheap, and a correct
     *prefilter*: anything not in one component can never be grouped.
   - **Stage 2, cohesion.** Connected components are still single linkage over the accepted edges — A↔B and
     B↔C put A and C in one component even when A and C share no edge. Mutuality raises the bar for an edge;
     it does not stop the chain. So each component is partitioned by **complete linkage**, deterministically:
     order members by `(created_at, uuid)`; seed a subgroup with the earliest unassigned member; add a
     candidate — in that same order — only if it has a mutual edge to **every** member already in the
     subgroup; when nothing more can be added, close it and seed the next subgroup from the earliest
     remaining member. Repeat until every member is assigned.

   On the A↔B↔C chain this yields `{A,B}` and `{C}`, which is the acceptance test. It is deliberately
   conservative and will sometimes split a group that a human would have kept together — and that is the
   safe direction, because step 3 processes groups oldest-first with the store updating as it goes, so a
   later group can still merge into the record an earlier group just created. An over-split costs one extra
   consolidator call; an under-split silently fuses two unrelated lessons into one false record.
3. **Process oldest-first**, in a **total** order: `(earliest member created_at, minimum member uuid,
   shard_index)`. Concurrent writes really do share a `created_at` string, so the uuid tiebreak is load-
   bearing, not decorative. The first two components are computed over the **pre-shard cohesive subgroup** and
   persisted as `consolidation_group.order_key`, so every shard of one subgroup carries the same key, sorts
   adjacently, and is ordered among its siblings by `shard_index` — which is the only reason a third component
   is needed at all. The store updates as we go, so transitive merging emerges without union-find.
4. **Cap group size, and split deterministically.** A cohesive subgroup larger than `group_max`
   (default **12**) is split into consecutive shards of ≤ `group_max` in `(created_at, uuid)` order —
   "consecutive in the group's own order" is the partition rule, so the same subgroup always shards the same
   way. Each shard is served as its own group with `shard: {index, of}` in the payload, and **the anchor is
   repeated into every shard** with a flag, because a shard without its anchor cannot make a merge decision.
   **Both numbers are persisted at plan time** — `shard_index` and `shard_count` on `consolidation_group` — and
   returned verbatim on every serve. `of` cannot be recomputed at serve time: doing so would mean replanning a
   subgroup whose membership is frozen, against a store that has since moved because step 3 lets earlier groups
   mutate it. Indices are **1-based**, so an unsplit group is `{index: 1, of: 1}` rather than a third convention
   meaning "not sharded"; all shards of one subgroup share the subgroup's `order_key`, which is what makes
   `shard_index` a meaningful third component of step 3's total order (`schema.md` invariant 19).
   Mirrors `~/Memory`'s `sleep_batch=40` bound on per-pass input, at a size chosen for the model's attention
   rather than copied.
5. **Membership is frozen at plan time; the payload is rebuilt at serve time.** The plan is persisted
   (`schema.md` §consolidation tables), so a `group_id` survives a service restart and cannot be handed to a
   second consolidator. Group *membership* is a snapshot — a journal row written after planning waits for the
   next run. What is **not** a snapshot is the payload: at serve time each member is re-read at its current
   version, a member that has left the journal is marked `vacated`, an anchor that has stopped being
   targetable is dropped, and candidates are recomputed and then persisted as the group's merge authorization
   set. Vacating **counts as a disposition**, so a serve that vacates a group's last open member closes the
   group inside the serve transaction and the serving loop moves on to the next group rather than handing back
   an empty one. That is what step 3 requires, and the full transactional contract — including whether an
   incomplete group is re-served, the `max_group_serves` bound, the serving loop, and when the run closes — is
   `architecture.md` §"Consolidation lifecycle". Leaving "updating the store as we go" to carry all of that
   allowed several readings.

### What `candidates` actually is
`zikaron_next_group` delivers, at most, one anchor plus four candidates — the "5 candidate memories" the
consolidator prompt promises:

- **`anchor`** is the long-term record from step 1, named separately from the list so the model knows which
  record the group was built around and which uuid `merge` should normally target. `null` for orphan groups,
  and `null` with `anchor_vacated: true` when a planned anchor stopped being `tier='long_term' AND active=1`
  before the group was served.
- **`candidates`** are up to `4` further long-term records, `active=1`, from **one group-level query**: the
  fused retrieval whose query text is the concatenation of the **served set's** gists, in group order — the
  members this serve is actually delivering, i.e. those with `disposition IS NULL` after serve-time
  re-validation (`architecture.md` §"Serving") — excluding the anchor and every member from the *results*, in
  `retrieval.md`'s total order, deduplicated by uuid. Naming that set matters on a **re-serve**: a member
  already merged, promoted, discarded or vacated is not in the payload and does not contribute its gist, so the
  query text of a second serve is narrower than the first's. That is deterministic, since the set is committed
  state and group order is total. It is an
  **external** query — the only one the system assembles from stored prose — so both arms follow the external
  rules: the concatenation is embedded through the dense preflight, and the *same* concatenation goes through
  the lexical term constructor. Not the union of each member's top five — that has no cap, no defined order,
  and would grow with group size.
- **The group query is token-budgeted.** Up to 12 gists of up to 64 tokens each can exceed the embedder's
  512-token input, so the concatenation **stops before the gist that would exceed the budget** and the
  payload reports `n_gists_used` — counted over the served set, so `n_gists_used ≤ |served set|`. Whole gists
  are dropped rather than one being cut in half, because a
  half-truncated gist is a garbled query while a shorter well-formed concatenation is not. Deterministic,
  because group order is total. The rule is `retrieval.md` §"Query construction"; this is the one place in the
  system where an *external* query is assembled from stored prose.
- **The `rank` of each candidate is included** so a run is reproducible from the payload alone, and the
  anchor plus candidates are **persisted** with their served versions and ranks
  (`schema.md` `consolidation_group_candidate`) — that table, not the `group_served` events, is what
  authorizes a later `merge` target, and it survives a service restart.
- **An empty `candidates` list is normal**, not an error: early in a store's life the long-term tier is
  empty, so every group is an orphan group with `anchor: null` and no candidates. The consolidator's only
  available verbs then are `promote` and `discard`, and its prompt says so.

### Why not cosine alone
The benchmark measured the dense side conflating near-miss identifiers: with **topic held constant** — the
instrument uses byte-identical passages differing in exactly one substring — a near-miss identifier buys only
about a fifth of the separation the same model achieves on a plainly distinct token. Discrimination index
**0.194–0.233** across all four models, direction right in 14 of 14 blocks (sign test p ≈ 1.2 × 10⁻⁴) with a
thin margin — **0.036–0.051 cosine**, against an exact-control margin of 0.18–0.24 — so a **contrary signal of
comparable magnitude decides instead** (`research/embedder-benchmark-results.md` §7; round 8 withdrew the wider
"any competing signal overturns it" reading, which fixes the direction and size of a signal the instrument
never measured — see that report's Erratum 2). Cosine-only clustering
would therefore be resting the `WidgetV1` / `WidgetV2` decision on the weakest signal the system has — and that
merge is the worst one available, because it manufactures a record false in both directions.

**What this does not say, corrected in round 4.** An earlier draft claimed "raising a cosine threshold makes
this failure mode more likely, not less," on the strength of "a twin pair already sits at 0.73." That
does not follow and the figure was misread twice over:

- The instrument measured **query→passage** cosines — its probe is a bare identifier token, or the carrier
  sentence "Tell me about X." — not the similarity between two stored memories. It never located a twin *pair*
  on the memory-to-memory axis the cutoffs threshold.
- Even as a level, `≈0.73` is **bge-large-with-prefix's** figure (0.72–0.74); the **deployed**
  bge-small-with-prefix sits at 0.76–0.79 and nomic between them at 0.74–0.79. Quoting a non-deployed model's
  level for a deployed threshold compounded the first error.
- And the inference was invalid on its own terms: a floor *above* a pair's score excludes that pair, so a level
  alone cannot establish which way moving the floor trades duplicates against twins. That needs a
  distribution over both populations, which nothing in the corpus has.

So the supported form is narrower and still sufficient for the decision: **cosine alone cannot be asserted to
separate a duplicate from a near-miss twin**, because the signal that would have to do it is measured weak and
no measurement of either population exists. That is the same conclusion §"Where the three cosine seeds come
from" reaches for D15's dedup floor, and it is why the hand-back is candidates to compare.

Using the hybrid inherits the lexical discrimination we already benchmarked and approved — at the strength
step 1 states precisely: lexical matching supplies an **exact-token signal independent of the dense score**
(`WidgetV1` and `WidgetV2` are distinct `unicode61` terms, a checkable tokenizer property), and whether that
signal changes the fused outcome is **unmeasured**, since the instrument tested four embedders and no lexical
arm and the blind set's `near_miss` category is saturated for every configuration. It is not a claim that
lexical matching is the *only* signal that could tell the two apart — the dense signal is weak, not absent —
nor that BM25 wins once every shared term in a real query contributes.

### Why mutual-K, and why mutual-K is not enough
Single linkage on a one-sided threshold chains badly: A~B, B~C, A≁C collapses into one cluster. That exact
case cost `~/Memory`'s `merge_reframes` a review MAJOR, so it is a requirement here that the chain be
*prevented*, not merely tested for.

Mutual-K earns its place for two reasons: it demands agreement from both endpoints, which prunes the weak
asymmetric edges that chains are usually built from, and it needs no absolute scale. What it does **not** do
is prevent chaining, and claiming otherwise was a defect in the first draft of this document — connected
components over mutual edges are still single linkage over those edges, so A↔B↔C is one component with or
without mutuality. Stage 2's complete-linkage pass is what actually prevents it, and the A↔B↔C case is an
acceptance test of that pass rather than of the component step.

Mutual-K also cannot express "not related at all", which is why the edge test carries `orphan_edge_cutoff`
beside it. A rank test is relative to the candidate pool, so in a six-row journal with K=5 every pair is
mutual and the whole journal becomes one group. Rank says *which* neighbours are closest; the cosine floor
says *whether* they are close. The earlier "one parameter instead of two" claim was therefore also wrong —
this genuinely takes two, and pretending otherwise bought a defect rather than simplicity.

Complete linkage has a real cost, stated plainly: it over-splits. A group of five observations where four
agree pairwise and the fifth only relates to two of them becomes two groups. We accept that because of the
asymmetry in step 2 — an over-split is one extra call and a later merge, an under-split is a false record.

### Why this scales
**Clustering load falls as the store matures.** Early on the long-term store is empty, so everything is an
orphan and this degenerates to pure journal clustering — which is why that path must exist. Later, most
entries find an anchor and never reach the clustering code; what remains is genuinely novel topics, a
smaller and easier set. D15's write-time dedup shrinks it further, since our journal should be far less
redundant than `~/Memory`'s.

## Consolidator identity and model
**A freshly spawned subagent** (D10), not the same model in-session. `~/Memory` reuses its session prefix
byte-identically for prompt-cache savings, which is unavailable to us for a simpler reason than that document
first gave: a fresh subagent has its *own* system prompt and tool set — four verbs the primary agent does not
have — so there is no shared prefix to hit. (The first draft said "consolidation runs at compaction time and
the parent window is exhausted". Under D10 the trigger is a manual skill invocation, which need not coincide
with compaction at all, so that reason was wrong even though the conclusion holds.) A fresh window also stops
session noise from leaking into consolidation judgment.

**Model is a config value, to be measured, not assumed — and the config it lives in is named.** It is the
top-level **`model`** field of the shipped `.kiro/agents/zikaron-consolidator.json`, required to be present
explicitly, with the v0 default and the no-inheritance / no-fallback rules in `architecture.md`
§"The consolidator's model is a shipped config field". Deliberately *not* a Zikaron config key: the store does not
spawn the subagent, so a value there would be read by nothing. Saying "config value" without saying which
config was a gap, because it made the one variable D29 asks us to measure unlocatable.

The cost argument for a cheap model does not bind:
D10 makes consolidation manually-invoked, therefore rare, off the hot path, with nobody waiting. Meanwhile
the error profile is asymmetric and durable — a bad journal row is one noisy row, but a bad consolidation
corrupts the long-term record, and retrieval will keep showing that record whether or not it is right. That
last clause is what D25 actually measured, and it is worth quoting at its true scope: on the **6
current-action polarity stubs (18 prompts)**, a record the query should *not* have acted on was in the
injected five **83–100%** of the time. The measurement is about superseded records under polarity prompts, not
about long-term records in general — but the transferable point is exactly the one that matters here: a
corrupted record does not quietly fail to retrieve, it gets shown. `~/Memory` documents the specific hazard:
`/sleep` "consolidates from the full history (enriches; watch confab)". The counterweight is real, though:
because code pre-selects candidates, the task is narrow — "here are N observations, the one long-term record
they cluster around, and up to four more that might be relevant: merge, create, or discard" — which is where
small models hold up. Hence: configurable, A/B-able on a single journal batch.

## Never lose silently — the guard, in Zikaron's terms
The principle is carried directly from `~/Memory`: **never mark work done unless the work came back.** The
*mechanism* is not carried, because D32 replaces the free-text block with per-group tool calls. Restating the
old protocol here — well-formed block, nudge ×3, present-but-empty block — contradicted `architecture.md`,
D32 and `prior-art.md`, all of which say Zikaron has no parser and no retry protocol. It is prior art, and it
lives in `design/prior-art.md`.

What Zikaron holds instead, at **journal-row** granularity rather than per group:

- A journal row is consolidated only when a write verb dispositions **that row** at its expected version.
  `merge`, `promote` and `discard` each name the rows they touch, and a group may need all three.
- Every `merge` / `promote` / `discard` response — success or `conflict` — carries `remaining_uuids`; a group
  closes only when that list is empty (`schema.md` invariant 16). One call does not close a mixed group, and an
  omitted uuid strands nothing — it simply stays in the journal. On `next_group` the same set arrives as
  `journal_entries`, the served set, which is never empty on a serve, so the field is not repeated there
  (`architecture.md` §"Row-level completion").
- A model that returns nothing, stops halfway, crashes, or lets its run lease expire loses **no** rows: the
  undispositioned ones are still `tier='journal' AND active=1`, so the next run plans them again.
- Empty subsets, unknown uuids, already-dispositioned uuids and members a primary agent retired after the serve
  are errors that mutate nothing, so neither silence nor a typo can complete a group. That last case is
  `not_in_group` as well, and the `vacated` disposition it implies is written by the next serve rather than by
  the rejected write (`architecture.md` §"Validation precedence").

This is stronger than the block protocol it replaces, and for a structural reason: the old rule depended on
the model emitting something parseable, so it needed the retry. Here the store's own state is the record of
what happened, and no cooperation is required for the guard to hold.

## Lessons stolen from `~/Memory`'s `merge_reframes` review
- **Name the processing order and the linkage rule.** Leaving them implicit was a MAJOR finding. Both are
  now named and total: mutual-K plus complete-linkage cohesion, ordered by
  `(earliest created_at, min uuid, shard_index)`.
- **Test the transitive chain case** (A~B, B~C, A≁C) explicitly — against the cohesion pass, which is the
  stage that prevents it.
- **Survivor rule: keep longest, not newest** — *their* lesson, and deliberately **not a Zikaron
  requirement.* It applied to `merge_reframes`, which selected a survivor automatically from a cosine
  cluster. Zikaron never does that: `merge` rewrites a target uuid the model names, and `promote` either
  flips one row or writes new prose the model authored. There is no automatic survivor to pick, so importing
  the rule would be cargo cult. Recorded accurately as prior art in `design/prior-art.md`. The nearest live
  analogue is D15's near-duplicate hand-back, where the *agent* chooses which of two rows survives — and
  "the longer row is usually the substantive one" is a reasonable heuristic to hand it if the instrumentation
  ever shows agents choosing badly. It is not in the v0 prompt.

## Interactions
- **D26 (optimistic concurrency):** the consolidator is the likeliest racer, since it holds candidates across
  a long window while a primary agent may amend them. Every row a verb touches is passed as
  `{uuid, expected_version}` — target, absorbed and discarded rows alike, not the merge target only — all
  versions are validated before anything mutates, and a mismatch mutates nothing and returns the current
  record for every conflicting uuid. **Group authorization runs before all of that**, and that ordering is
  what keeps D7 mechanical: a conflict payload hands back a full record, so if version were checked first a
  consolidator could name any uuid with a wrong version and read the store one deliberate conflict at a time —
  reconstructing the `fetch` D32 withholds. Authorization answers only "is this one of the rows I handed you",
  in uuids. **Then** the version check runs before the receipt check, so an amend that landed between serve and
  call returns `version_conflict` with a fresh receipt rather than `no_read_receipt`; both ladders are in
  `architecture.md` §"Validation precedence". The group payload is what mints the
  consolidator's read receipts, at the versions it actually delivered, which is how it satisfies D26 without
  holding `fetch`. Contracts in `design/architecture.md`.
- **D25 (supersession):** merges that retire an old record use `superseded_by`, which demotes rather than
  hides — historical-intent queries still need the retired row. The graph rules (no cycle, target not
  retired-outright, one immutable outbound edge) are `schema.md` invariant 6, and a merge that would create a
  cycle is an error rather than a silent corruption.
- **D28 (chunking):** a merged or promoted record's chunks are rebuilt atomically with its version bump, in
  the same transaction as the retirements it causes.
- **D27 (provenance):** records the consolidator writes carry the *consolidator's* `session_id`. Original
  authorship survives because D16 keeps the absorbed rows, with their own `session_id`, linked back by
  `superseded_by`.
- **D16 (soft delete):** `discard` retires, it does not delete. A discarded row keeps its prose and its
  `reason` goes to the **`discard` event's `detail.reason`** and nowhere else (`schema.md` §"The `event` log,
  per kind"), so "we decided this was noise" is recoverable if that judgment was wrong.

## Parameters, and what the seeds are worth
Every parameter here is a **config-file** key with a v0 default, a type and a range — the full table is
`schema.md` §"Configuration keys", resolved per `architecture.md` §"Configuration". Buildability does not wait for calibration. What does wait is any claim that these
values are *measured*: none of the three cosine seeds is, and the subsection below says so at length rather
than in a footnote.

| Parameter | v0 | Where it decides |
|---|---|---|
| `anchor_cutoff` | **0.65** | whether a journal entry anchors to a long-term record at all |
| `orphan_edge_cutoff` | **0.65** | whether two orphan journal entries share an edge |
| `dedup_threshold` | **0.80** | which near-duplicates D15 hands back |
| `mutual_k` | **5** | the rank half of the orphan edge test |
| `group_max` | **12** | shard size for an oversized cohesive group |
| `max_group_serves` | **3** | how many times one group may be **delivered** in a run, counting the first, before deferral |
| `run_lease` | **1800 s** | how long an idle consolidator can hold the store |

### Where the three cosine seeds come from
**They are provisional heuristics. No persisted measurement backs their values, and this section previously
claimed otherwise.**

A probe was run during round-2 remediation and reported percentile and floor-sweep tables here. Those tables
have been removed, for two reasons that are worth recording rather than quietly fixing:

- **It did not measure this estimand.** `schema.md` defines all three cutoffs as the best cosine between the
  querying memory's **first chunk** and **any chunk** of the candidate. The probe scored one cached
  whole-record `gist + content` vector per memory — close to the deployed quantity for the short memories that
  dominate the corpus, and simply not the same function. Numbers that do not measure the thing the code will
  compute cannot calibrate it.
- **It was never persisted.** The script lived in `/tmp` and is gone. Quoting figures whose provenance is a
  deleted temp file is precisely the failure mode this project exists to prevent, and the corpus holds every
  other measured figure to a persisted, independently reviewed source (`research/embedder-benchmark-results.md`).
  This section was the one exception, so it is the one that had to go.

What the three values are, then, is **seeds chosen so the system is buildable**, each with a stated reason
that does not depend on a measurement:

- **`anchor_cutoff = 0.65` — loose on purpose, because both error directions are cheap.** The anchor is
  *advice to a model*, never an automatic action. A missed anchor produces an orphan group, which the cohesion
  pass handles and the consolidator can `promote`. A spurious anchor shows the consolidator one irrelevant
  record, which it can decline. Nothing here is destructive in either direction, so the value is chosen to
  keep the mechanism exercised rather than to optimize a tradeoff nobody has measured.
- **`orphan_edge_cutoff = 0.65` — seeded equal, because it thresholds the same kind of relation.** It is a
  separate key only so that a future measurement can separate the two. What is *not* provisional is that this
  cutoff must exist at all: that is a combinatorial result, not an empirical one. With `mutual_k = 5` and six
  orphan rows every pair is mutually top-K, so the mutual graph is complete and the whole journal fuses into
  one group. A rank test cannot express "not related at all" — see §"Why mutual-K, and why mutual-K is not
  enough".
- **`dedup_threshold = 0.80` — and the framing matters more than the number.** What is measured is a fact about
  the **signal**, not about the threshold: with topic held constant, the counterfactual instrument gives a
  discrimination index of **0.194–0.233** across all four models
  (`research/embedder-benchmark-results.md` §"Three conclusions" — whose closing clause on lexical exclusivity is
  **withdrawn**; see `reviews/embedder-benchmark-independent.md` §"Erratum 1"), so a near-miss identifier
  contributes about a
  fifth of the separation a plainly distinct token does, direction right in 14/14 blocks but margin thin. A
  `WidgetV1` memory and a `WidgetV2` memory are exactly the case where the dense score has the least to work
  with — and merging them is the worst mistake this system can make. So the hand-back can never be an assertion
  of duplication. It is a pair of gists for the agent to compare, which `architecture.md`'s `zikaron_remember`
  description says explicitly, and `dedup_max = 3` bounds what a loose floor can cost.

  **Where the *value* 0.80 comes from is nowhere, and round 4 tightened how that is said.** Round 3 replaced the
  withdrawn tables with the claim that "any floor high enough to be interesting also admits twins", quoting
  near-miss pairs at "absolute cosine ≈ 0.73". That is not a claim the approved report supports. The instrument
  measured **query→passage** cosines — probe = a bare identifier token, or "Tell me about X." — never
  memory-to-memory similarity, so it places no pair population on the `s(X → Y)` axis this key thresholds; the
  ≈0.73 level is **bge-large-with-prefix's** (0.72–0.74), while the deployed bge-small-with-prefix is 0.76–0.79; and no duplicate
  population was measured at all. Consequently **nothing in the corpus says which way moving this floor trades
  duplicates against twins**, and the conclusion is stated as the absence of a licence to assert, not as a
  proven impossibility: a floor cannot be *asserted* to separate them. The design consequence — candidates, not
  assertions — is unchanged and rests on the DI plus that absence.

**What it would take to call any of these measured**, stated so the next person does not re-derive it: a probe
that scores the deployed quantity — `s(X → Y)` as `schema.md` §"Configuration keys" defines it, first chunk of X against the
best chunk of Y, through the same rollup the dense arm uses, and **symmetrized with `min` where the relation is
undirected** — over populations named for what they actually are (**designated duplicate pairs** and
**designated twin pairs**, each constructed and labelled as such; not "any pair sharing a query's confusable",
and not a query→passage score borrowed from the identifier instrument), persisted under
`experiments/embedder-precision/` with its result written into `research/`. Two rounds have now failed on the
estimand rather than on the statistics — round 3 on the wrong rollup, round 4 on a query→passage cosine read as
a pair cosine — so **naming the estimand precisely is the first step of that probe, not a footnote to it.**
Until it exists these are seeds, and `schema.md` §"Configuration keys" types and ranges them — and being file keys now, they are cheap to move without touching the store.

**The one parameter that is not a threshold at all** is the cohesion rule: complete linkage takes no
threshold, which is part of why it was chosen over a density or k-core criterion.
