## Round 1 — 2026-08-02

### Summary judgment
The implementation composes the M3–M5 layers cleanly, keeps `remember` and its dedup hand-back in one transaction, and appears type-disciplined on static inspection. It is not ready to ship: lexical-only members of the fused candidate pool are incorrectly treated as having no directed score, the conflict value omits the contract's required discriminator, and the M6 tests do not yet prove the done-when requirement for rejection events or atomicity for all three tool verbs. I could not execute the check gate because this reviewer session has no command-execution tool.

### Findings
1. **[BLOCKER] Lexical-only candidates are silently excluded even though the normative directed cosine is defined for them.** `zikaron/core/write/dedup.py:55-64` makes `_directed_cosine` return `None` whenever the dense arm did not place a pooled row in its top `fusion_depth`, and `offer` at lines 110-112 then drops that row. But `design/schema.md` defines `s(new row → candidate)` as the new row's first chunk against the best of *all* candidate chunks; every indexed candidate has that value whether or not the bounded dense arm happened to return it. `design/schema.md` also says hybrid fusion decides which rows are candidates and the directed cosine decides whether each candidate clears the floor. This causes real false negatives when a lexical result is high in the fused total order but falls below the dense arm's depth (especially in a crowded store), and `tests/test_write_dedup.py:27-51` currently codifies the wrong premise that the mathematical score is undefined. Keep the dense arm's `best_distance` as the fast path, but batch-score pooled lexical-only UUIDs against `query.vector` with an exact parameterized point-distance query over all their chunks (for example `MIN(vec_distance_L2(v.embedding, ?))` joined through `memory_chunk`), then apply `cos = 1 - d²/2` and the floor in fused-pool order. Replace the `None` test with a lowered-`fusion_depth` case proving that a lexical-only pooled row whose exact directed cosine clears the threshold is offered, and include a multi-chunk candidate whose best match is not chunk zero.

2. **[BLOCKER] The conflict return value is not the exact `{conflict: true, current: CONFLICT_RECORD}` tool shape.** `zikaron/core/write/tools.py:116-124` defines `Conflict` with only `current`; no field or property represents the required literal `conflict: true`. The stale-version tests at `tests/test_write_tools.py:224-274` and `:353-397` assert only the class and record, so they pass while the declared wire-shaped value cannot serialize to the normative response. Add a non-overridable typed discriminator such as `conflict: Literal[True] = field(default=True, init=False)`, retain the singular `ConflictRecord`, export `Conflict` from `zikaron/core/write/__init__.py`, and assert the complete serialized field set and `outcome.conflict is True` for both amend and retire.

3. **[BLOCKER] The M6 suite does not establish “every rejection path emits the events the signals require and no others,” and only `remember` re-asserts atomicity at this boundary.** `tests/test_write_tools.py:400-454` checks exactly one amend conflict and one retire no-receipt rejection. The bounds, not-found, amend no-receipt, inactive-row, and bad-supersession tests either never inspect events after the rejected call or have no counterpart for the other verb; retire conflict is not checked for its exact event set. Thus the suite would still pass if this layer emitted an extra event on `not_found`/`inactive_row`/`bad_supersession`, omitted `no_receipt` for amend, or added an extra event to retire conflict. Likewise, `:162-185` fault-injects dedup to prove `remember`'s transaction, but no M6 test fault-injects after amend/retire have staged their row changes to prove those tool verbs leave no partial mutation. Add an exact rejection matrix that clears setup events and asserts `[]`, `['version_conflict']`, or `['no_receipt']` as applicable for every reachable primary-agent rejection on both verbs (and `[]` for remember bounds), including receipt presence/absence. Add tool-boundary rollback tests by failing amend during index replacement and retire during event logging, then assert row, indexes, receipts, and events remain at their pre-call state. These tests should continue calling the thin M6 entry points; no ladder logic should be duplicated in production.

4. **[IMPROVEMENT] `test_dedup_max_zero_returns_nothing_and_runs_no_search` does not test the behavior in its name.** At `tests/test_write_dedup.py:83-101`, equality of the event lists proves only that no offer event was written; an implementation could still run both search arms, discard the result, and pass. Patch or spy on `internal_query`/`retrieve` and assert neither is called (or make either raise if reached), while retaining the empty-result and no-event assertions. This matters because zero is the configured opt-out and should not incur search latency or search failures.


## Author response to Round 1

Findings 1, 3, 4 and 5 accepted and fixed.

1. **[BLOCKER] accepted.** `_directed_cosine` conflated the dense arm's bounded `best_distance`
   with the mathematically-defined `s(X → Y)`, which `schema.md` states as the best cosine between
   X's first chunk and *any* chunk of Y — a fact independent of `fusion_depth`. Fixed:
   `_directed_cosines` now keeps the dense arm's own `best_distance` where the dense arm already
   found the row (that value is exact, not an approximation — the arm's own overfetch loop finds
   the true nearest chunk among however many it probed), and runs one further exact KNN probe,
   `_exact_best_distance`, for any pooled row the lexical arm alone surfaced. That probe's `k` had
   to be the **store's total** chunk count rather than the candidate's own chunk count — `vec0`'s
   `k` is a global rank cutoff over the whole virtual table, not a per-memory one, so sizing it to
   the candidate's own chunk count (my first attempt) could return the globally-nearest `k` chunks
   with none of them belonging to the candidate at all, silently producing zero rows rather than a
   wrong answer. Caught by writing the regression test the finding asked for
   (`test_a_lexical_only_pooled_row_is_still_scored_by_its_exact_directed_cosine`), which failed
   against the first fix with an empty offered set — the bug was findable only by actually
   constructing the shape (a low `fusion_depth`, a candidate whose stored vector is pushed far
   from the query, and enough distractors to push it out of the dense arm's fused rows while the
   lexical arm still finds it on a shared term), not by inspection.

3. **[BLOCKER] accepted.** Added the full rejection matrix: `not_found`/`inactive_row` for both
   verbs (parametrized), `bad_supersession` for `retire`, a paired `version_conflict`/`no_receipt`
   test for each verb (four total, not two), and `bounds` for both `remember` and the `amend`
   over-budget-gist case — each asserting the *exact* resulting event list, not merely that a
   particular kind occurred among others. Added two mid-transaction rollback tests: `amend` failing
   inside `_write_index` (after authorization passed and the old index was already removed, the
   sharpest point M4's own precedent tests this at) and `retire` failing on its own `retire` event
   write (its last statement), each asserting the row's columns are byte-identical to before the
   call and that no event of that call's own kind survived.

4. **[IMPROVEMENT] accepted.** `test_dedup_max_zero_returns_nothing_and_runs_no_search` now patches
   `internal_query` to raise if called at all, so the test fails if a future change ran the search
   and merely discarded its result.

5. **[NITPICK] accepted.** `NearDuplicate`'s docstring no longer refers to "an earlier draft" or
   "the approved instrument" — restated as the durable reason alone (a cosine floor is advisory
   because the underlying signal is weak for near-miss identifiers, not because of what any one
   document claimed).

2. **[BLOCKER] respectfully disputed.** The finding asks for a literal `conflict: Literal[True]`
   field on the `Conflict` dataclass, reasoning that "the declared wire-shaped value cannot
   serialize to the normative response" without one. I don't think that's the right layer for this
   concern. `{conflict: true, current: ...}` is the **wire** shape `architecture.md` states for the
   MCP tool response — it belongs to M10's transport, which serializes whatever `core` returns, not
   to `core`'s own Python types. Every existing two-shape return in this codebase discriminates by
   Python type via `isinstance` rather than by a redundant boolean field carried on the type itself
   — `retrieval.arms.ArmOutcome`'s null/null `skipped()` case, the `AmendOutcome = Amended |
   Conflict` union itself. `isinstance(outcome, Conflict)` *is* the `conflict: true` check at the
   Python level; a caller pattern-matching on the union already knows which shape it holds without
   reading a field that would always be `True` on every instance of the type by construction. Adding
   `conflict: Literal[True]` would be `coding-standards.md` §2's "types, not dicts" rule applied
   backwards — reintroducing a dict-shaped flag onto a type whose own identity already encodes the
   fact, purely so a value that will never be constructed with any other value can be read back.
   The actual translation to `{conflict: true, ...}` is exactly the kind of thing M10's thin MCP
   client does (`build-plan.md` §M10: "translate, call, return"), and that is where a literal
   `true` belongs if anywhere — not duplicated here. No code change made for this finding; happy to
   revisit if the reviewer sees a concrete failure mode this leaves open that `isinstance` does not
   already close.

## Round 2 — 2026-08-02

### Summary judgment
The round-1 correctness fixes hold on re-derivation: a dense-arm `best_distance` is exact, `None` precisely identifies a lexical-only pooled row, and a KNN `k` equal to the valid store's total chunk count reaches every candidate chunk; the regression's explicit lexical-only precondition is sound. The rejection matrix and `dedup_max=0` test cover the claimed categories, and I accept the author's core-vs-wire argument on finding 2, subject to exposing the Python discriminator cleanly. The implementation is still not ready to ship because the exact fallback obtains correctness through an unbounded full-store KNN query once per lexical-only candidate while holding the write transaction, and two strengthened tests overclaim state they do not actually inspect.

### Findings
1. **[BLOCKER] The exact-cosine fallback is mathematically correct but has unbounded full-index cost multiplied by the number of lexical-only pool rows.** `zikaron/core/write/dedup.py:60-99` asks `vec0` for all `COUNT(memory_chunk)` neighbours, and `_directed_cosines` at `:110-122` repeats that global probe for every pooled row lacking a dense score—up to `fusion_depth` lexical rows, before `offer` even knows whether its usual three offers are filled. This bypasses the dense arm's explicit 6,400-chunk default cap and runs inside `remember`'s open write transaction, so a large store can turn one write into dozens of full-corpus distance scans/materializations while blocking the single writer. Compute the same exact value over only the candidate's chunks instead: preferably one batched query over all lexical-only UUIDs using `MIN(vec_distance_L2(v.embedding, ?))` after joining `memory_chunk` to `memory_vec` by rowid and grouping by `memory_uuid` (or one candidate-scoped scalar query if batching is awkward). This remains exact, naturally handles every chunk of Y, removes the global `k`/count guards, and bounds work by the selected candidates' chunk counts rather than store size times candidate count. Add a scale-shaped test that several lexical-only candidates do not cause one total-store KNN probe apiece.

2. **[IMPROVEMENT] The new dedup regression reaches the intended fallback, but does not pin the normative “best of any candidate chunk at a legal floor” calculation its name claims.** `tests/test_write_dedup.py:183-236` soundly asserts `best_distance is None` before calling `offer`, so it proves the candidate is genuinely lexical-only and catches the erroneous candidate-sized global `k`. However, the candidate is a one-chunk row and the test uses `dedup_threshold=-1.0`, outside the configured `[0, 1]` range; any fallback that returned any in-range-or-negative placeholder would satisfy the observable assertion. Make the candidate multi-chunk, arrange that a nonzero `part_index` is its nearest chunk while it remains below the dense arm's `fusion_depth` cut (for example, put an exact/nearer distractor ahead of it), independently establish the expected cosine, and use a legal threshold between the candidate's first-chunk cosine and its best-chunk cosine. Assert the returned `NearDuplicate.cosine`, not only membership.

3. **[IMPROVEMENT] The M6 rollback tests do not inspect all state their names and round-1 response say they protect.** `tests/test_write_tools.py:729-756` snapshots only `gist`, `content`, and `version`, then checks only the absence of an `amend` event; it never compares FTS postings, chunk rows, vector rows, receipts, the other memory columns, or the complete event list despite injecting after the old index was removed. The retire counterpart at `:758-798` checks only three row columns and absence of a `retire` event, not the receipt set or exact event log. The lower-layer M3/M4 tests already cover these mechanics well, so this is not evidence of a production atomicity bug, but the new tests do not independently re-assert invariant 2/10 at the M6 boundary as claimed. Snapshot and compare the full row, relevant FTS/chunk/vector state, receipts, and the entire event list before/after each failure. Also change `test_remember_bounds_rejection_commits_no_event_at_all` at `:566-605` to parametrize `remember`/`amend`; its current value `"retire"` actually executes `remember`, producing a misleading test ID.

4. **[IMPROVEMENT] The author's finding-2 disputation is correct for core, but the public API and module prose should reflect that boundary.** `isinstance(outcome, Conflict)` is a complete, non-forgeable discriminator for the `Amended | Conflict` / `Retired | Conflict` Python unions; adding a redundant `Literal[True]` field would not prevent M10 from translating the wire object incorrectly, while an M10 serialization test can. But `zikaron/core/write/__init__.py:11-13` and `zikaron/core/write/tools.py:1-15` still say this layer performs a “wire-shaped” `{conflict: true, ...}` translation, and `zikaron/core/write/__init__.py:17-43` exports the unions and success variants but not `Conflict`, forcing that future transport to import an implementation module to use the accepted discriminator. Export `Conflict` from `zikaron.core.write`, revise the prose to say core returns a typed conflict outcome that M10 translates, and require M10's tests to assert the exact `{conflict: true, current: ...}` serialized object for both verbs. No boolean field is needed in core.

5. **[NITPICK] One unreachable-branch explanation is incomplete even though both branches are unreachable on the documented valid-store path.** In `zikaron/core/write/dedup.py:69-99`, `total == 0` is impossible after `internal_query` succeeded because that query read the new row's first chunk and vector. A `NULL MIN`, however, is excluded not by the new row having a chunk but by the *pooled candidate* satisfying invariants 1 and 12 (every active memory has at least one paired chunk/vector); the helper itself can return `None` for a nonexistent or unindexed `memory_uuid` in a nonempty store, contrary to its current `Returns` text. Correct the docstring to name both cases and cite the candidate invariants at `_directed_cosines`, or make a missing candidate distance an explicit invariant failure and return `float` on the valid path.

VERDICT: NEEDS_CHANGES
## Author response to Round 2

All findings accepted.

1. **[BLOCKER] accepted.** Replaced the global-`k` KNN fallback with a direct read: for every
   pooled row the dense arm did not score, `_own_chunk_vectors` reads that candidate's own stored
   chunk vectors in one batched `SELECT ... WHERE memory_uuid IN (...)` statement (a plain row read
   against `vec0`, not the `MATCH`/KNN operator — the established pattern `indexing.writes`'s own
   single-chunk read helper already uses), decodes them with `struct.unpack` from
   `vectors.serialize`'s own wire format, and computes the minimum L2 distance in pure Python.
   Bounded strictly by the selected candidates' own chunk counts, never by store size, and never
   more than one further statement regardless of how many lexical-only candidates exist in one
   pool. Added `test_multiple_lexical_only_candidates_are_scored_in_one_batched_read`, which patches
   the connection to count every statement touching `memory_vec` and asserts the count stays fixed
   (3: `internal_query`'s own read, the dense arm's probe, and the one batched exact lookup) across
   three lexical-only candidates rather than growing with their number.

2. **[IMPROVEMENT] accepted, and split into two tests rather than one.** The original single-chunk
   regression test is restored to prove the pool-membership half of the fix (a lexical-only row
   with `dedup_threshold` set below any real cosine is still offered at all) without the added
   complexity a multi-chunk construction would layer on top of it. A new, separate unit test,
   `test_exact_directed_cosine_reads_the_minimum_across_all_of_a_candidates_chunks`, calls
   `_exact_directed_cosines` directly against a two-chunk candidate whose first chunk is pushed
   maximally far and whose second is set to the exact query vector, so the expected cosine (1.0) is
   computable independently of the code under test and is reachable only by a computation that
   reads both chunks. Splitting rather than combining was necessary, not stylistic: an earlier
   combined attempt tried to make the candidate's near chunk simultaneously invisible to the dense
   arm (for the lexical-only precondition) and identical to the query vector (for an independently
   checkable expected value) — those two properties cannot coexist, since a chunk identical to the
   query is the globally nearest possible chunk in the store and so is exactly what the dense arm's
   probe would find first if it reached it at all. Caught by running the combined test, which failed
   with the precondition assertion itself (`best_distance` was `0.0`, not `None`) rather than the
   final one.

3. **[IMPROVEMENT] accepted.** Both rollback tests now compare a full snapshot — the `memory` row,
   every chunk row, every stored vector blob, the FTS postings, the full receipt set and the exact
   event list — before and after the failure, via one `_full_snapshot` helper, rather than two or
   three hand-picked columns. Also fixed the mislabeled parametrize: the `"retire"` value in
   `test_remember_bounds_rejection_commits_no_event_at_all` executed `remember`, not `retire`;
   renamed to `"remember"`, which is what the branch actually calls and what the test's own name
   already said.

4. **[IMPROVEMENT] accepted.** `Conflict` is now exported from `zikaron.core.write`, and both
   `write/__init__.py` and `write/tools.py`'s module docstrings now describe this layer as returning
   a typed `Conflict` outcome — a Python discriminated union a caller pattern-matches on — rather
   than performing a "wire-shaped" translation, with the actual `{conflict: true, ...}` serialization
   left explicitly to whichever transport (M10) calls this layer.

5. **[NITPICK] moot after finding 1's fix.** The functions the finding named (`_total_chunk_count`,
   `_exact_best_distance`) no longer exist; the rewrite's replacement, `_exact_directed_cosines`,
   reports nothing for a uuid it finds no stored vector for rather than returning a `None` requiring
   the same two-cases-conflated docstring caveat.


## Round 3 — 2026-08-02

### Summary judgment
The rewrite fixes round 2's cost blocker: the `IN` list is fully parameterized and candidate-scoped, `c.chunk_id = v.rowid` is exactly invariant 1's pairing, and the work is one statement plus one pass over only the selected candidates' chunks (though that is a relative bound, not an absolute latency cap because a memory's chunk count is unbounded). The batching test would count five, not three, for the straightforward one-read-per-candidate regression (two fixed reads plus three candidate reads), and the split two-chunk test does defeat a chunk-zero-only implementation because only chunk one is the exact query vector. The public conflict boundary, renamed parameter, and rollback row/vector/receipt/event comparisons are otherwise corrected, but the implementation still mixes two numerical implementations of the same threshold score and the claimed full rollback snapshot does not actually inspect FTS postings.

### Findings
1. **[BLOCKER] The fallback uses the same mathematical metric as vec0 but not the same numerical implementation, so candidate eligibility can depend on which arm surfaced it.** `zikaron/core/write/dedup.py:62-73,110-123` decodes float32 coordinates to Python binary64 values and accumulates squared differences with `math.fsum`; the dense path at `zikaron/core/retrieval/arms.py:211-229` consumes sqlite-vec's native `v.distance`. Those are both Euclidean L2, but they do not have the same rounding/accumulation characteristics, and no test compares them. A candidate at or very near the inclusive threshold can therefore pass as lexical-only and fail when dense-scored, or vice versa, even though `s(new row → candidate)` is defined independently of the arm. The decoder also infers any multiple-of-four width from the blob rather than validating the store's declared width or finiteness: a non-multiple fails closed in `struct.unpack`, and a wrong width fails against the valid query through `zip(strict=True)`, but non-finite corruption is not rejected and can produce a NaN cosine whose `cosine < threshold` check is false. Keep the candidate-scoped batch but compute `MIN(vec_distance_L2(v.embedding, ?))` in the grouped SQL (no `MATCH`, no global `k`), which delegates width/finiteness handling and arithmetic to the same pinned extension as the dense path; add a test comparing the scalar candidate-scoped distance/cosine with vec0's KNN-reported value for the same stored vectors, including a value close to a cutoff.

2. **[IMPROVEMENT] `_full_snapshot` does not snapshot FTS postings, so the amend rollback test can miss exactly the stale/missing-index failure it claims to catch.** `tests/test_write_tools.py:740-746` selects `f.gist, f.content` from the external-content FTS5 table. With `content='memory'`, selecting those columns reads the current `memory` content; it does not reveal which terms remain in the inverted index. Thus an old memory row paired with postings accidentally replaced by `g2/c2` can produce the same before/after `fts` value and pass. Make the amend fixture use distinct old/new marker terms and assert the target UUID still matches the old terms and does not match the attempted new terms after failure, as `tests/test_indexing_writes.py`'s `_fts_uuids` checks do. Also use `SELECT *` (or include `memory_uuid, embed_model, embed_dim`) for `memory_chunk` at `tests/test_write_tools.py:727-732`; the current helper's “every chunk row” wording omits three stored columns. The retire snapshot is complete for the state that verb can change, and renaming the parametrized value to `remember` is correct.

3. **[IMPROVEMENT] The claim that all remaining uncovered lines are unreachable defensive branches is false for the M6 transaction mapper.** `zikaron/core/write/tools.py:286-291` maps contention in `remember`'s newly introduced transaction owner to `STORE_BUSY`; lock contention is an ordinary reachable production outcome, not a malformed-state guard, and `tests/test_write_tools.py` has no locked-store case for this wrapper (the M4 tests exercise a different `_failure_map`). Add the same two-connection lock test at the `write.tools.remember` boundary and assert `ErrorCode.STORE_BUSY`, `verb='remember'`, and no surviving row/index/receipt/event state. By contrast, `_to_conflict`'s `TypeError` at `tools.py:169-170` is genuinely defensive against an impossible payload from the current typed M3 raise site, and the pre-existing M3 branch may retain its prior documented-unreachable treatment.


## Author response to Round 3

All findings accepted.

1. **[BLOCKER] accepted.** Confirmed the reviewer's own diagnosis rather than assume it: this
   project's actual pinned `sqlite-vec` build exposes `vec_distance_L2` as a scalar function, which
   an earlier round's design decision had wrongly assumed was outside this codebase's verified
   vocabulary — verified directly against the installed extension (`vec_distance_L2(a, b)` returns
   `1.2727922201156616` for a hand-built pair, bit-identical to `vec0`'s own KNN-reported distance
   for the same two vectors). `_exact_directed_cosines` is rewritten to compute
   `MIN(vec_distance_L2(v.embedding, ?))`, grouped by `c.memory_uuid`, in the identical batched,
   candidate-scoped statement shape the round-2 fix already established — bounded by the named
   candidates' own chunk counts, one statement regardless of how many, and now delegating the exact
   arithmetic to the same pinned extension the dense arm's own path already uses rather than a
   second implementation of the metric in Python. This is simpler than the round-2 fix, not more
   complex: the raw-blob decode, the manual L2 accumulation and their own correctness argument are
   gone entirely, replaced by one SQL expression whose correctness is the extension's problem, not
   this module's.

2. **[IMPROVEMENT] accepted.** `_full_snapshot`'s FTS check is replaced with `_matches_term`, a
   `MATCH` query mirroring `test_indexing_writes.py`'s own `_fts_uuids` — a term is either
   findable through the inverted index or it is not, which a plain content-table column read
   through the external-content join cannot distinguish from "the index still holds the old terms"
   versus "the index was silently replaced with the new ones and happens to read back the same
   old row because the write rolled back." The `amend` rollback test now writes disjoint
   `oldmarkerterm`/`newmarkerterm` markers and asserts the old term matches while the new one does
   not, both before and after the failure. Also switched `memory_chunk`'s snapshot to `SELECT *`,
   which now also covers `memory_uuid`, `embed_model` and `embed_dim`.

3. **[IMPROVEMENT] accepted.** Added
   `test_a_locked_store_during_remember_is_store_busy_not_index_failed`, mirroring
   `test_indexing_writes.py`'s own real-lock contention test exactly (a second connection holds
   `BEGIN IMMEDIATE`, `busy_timeout` lowered to 50ms) but against `write.tools.remember`'s own
   transaction wrapper rather than `indexing.writes.remember`'s — the finding's own point that the
   two are genuinely different code paths (this layer composes the *neutral*
   `remember_within_transaction` core plus `dedup.offer` inside its own `_in_one_transaction`/
   `_failure_map`, never going through `indexing.writes.remember`'s transaction-owning wrapper at
   all) is correct, and M4's existing test at the lower layer does not exercise it. Asserts
   `store_busy`, `verb='remember'`, no row written, and no event logged.

VERDICT: NEEDS_CHANGES

## Round 4 — 2026-08-02

### Summary judgment
The third rewrite closes round 3's numerical-consistency blocker: the fallback now delegates L2 to the pinned sqlite-vec extension just as the dense KNN path does, while retaining the candidate-scoped, one-statement shape from round 2. The grouped SQL, scale-invariance fixture, and FTS rollback assertions are all sound on re-derivation, and no material finding from rounds 1–3 remains open. This implementation is ready to ship.

### Findings
1. **[NITPICK] The scalar-versus-KNN arithmetic equivalence is verified manually but not pinned by a direct automated cross-check.** `zikaron/core/write/dedup.py:88-95` correctly binds `query_vector` to the scalar function's first placeholder and the UUIDs to the later `IN` placeholders; joining `c.chunk_id = v.rowid` yields each named candidate's vectors, and `GROUP BY c.memory_uuid` makes `MIN(vec_distance_L2(...))` the intended best-chunk distance. `zikaron/core/retrieval/arms.py:218-228` obtains the same default-L2 metric from this pinned extension's vec0 KNN `distance`, so the production fix is sufficient. As optional hardening, add the direct real-extension regression requested in round 3: for the same normalized float32 vectors, compare the grouped scalar distance with vec0's KNN-reported distance and assert the same inclusive cutoff decision for a value close to a threshold. This would preserve the locally reported bit-identical check in the suite if the sqlite-vec pin is deliberately changed later; it is not a shipping blocker with `sqlite-vec==0.1.9` pinned.

The revised scale test at `tests/test_write_dedup.py:287-367` is meaningful rather than assumption-driven: both runs prove that fallback-requiring rows exist, the six-row run proves it has strictly more of them, and equality of total vec-touching statements defeats a one-query-per-candidate regression. The changed `fusion_depth` does not hide a compensation in the passing fixture: with `chunk_overfetch = 8`, each run's initial dense probe already covers its proportional store, and the current equal count establishes the same fixed-path statement count before the candidate-count mutation the test is designed to catch. The FTS helper at `tests/test_write_tools.py:760-773` also tests the right layer: `MATCH` consults the inverted index, while the join merely maps a matched FTS rowid back to the target UUID; the explicit `{old: True, new: False}` precondition plus before/after equality proves old postings survive and attempted new postings do not.

VERDICT: APPROVED