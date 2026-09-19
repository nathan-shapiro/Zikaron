# Review — M25 fusion sweep

Artifacts: `research/m25-fusion-sweep.md`, `research/m25-fusion-sweep-preregistration.md`,
`experiments/m25_fusion_sweep.py` (and `experiments/m25_build_sweep_corpus.py`), plus the four
amended sites the brief names (`design/knowledge-index.md` §16 items 1 and 3,
`zikaron/core/retrieval/__init__.py`, `design/schema.md`, `design/build-plan.md`).

## Round 1 — 2026-09-18

### Summary judgment

The preregistration-then-withdraw-in-place handling is honest and the instrument finding is real
and well told. But the decision procedure the note reports is not the one the preregistration
fixed — thresholds 1, 2 and 4 were defined on *pooled* MRR@10 and the note applies them to `heading`
alone without recording the deviation, so "no cell clears the preregistered bar" is unproven on the
bar as written and the "0.02 fixed in advance" phrasing names the wrong quantity. Two further
claims exceed their evidence and have already reached a normative document: "hybrid beats **both**
single arms" rests on a +0.013 difference with no CI, compared against a best-of-36 maximum; and
the headline CI and the overlap table — the two numbers the whole conclusion hangs on — are not
produced by the harness the note says produced everything and cannot be regenerated from anything
in the repository. Not shippable as-is; every fix is concrete and none requires re-running the
build.

### Findings

1. **[BLOCKER] The bar applied is not the bar preregistered, and the deviation is unrecorded.**
   `research/m25-fusion-sweep-preregistration.md` lines 99–106 define threshold 1 ("pooled MRR@10
   improves by ≥ 0.02"), threshold 2 (bootstrap on that difference) and threshold 4 on the
   *pooled* quantity. `research/m25-fusion-sweep.md` lines 18–21 apply the 0.02 and the CI to
   `heading` only and call it "the 0.02 threshold fixed in advance". The threshold *value* was fixed
   in advance; the *quantity* it is applied to changed after the data was seen. That is exactly the
   "name the quantity" rule. Consequences:
   - The headline "No cell in the 252-cell grid clears the preregistered bar" (line 14) is shown
     only for the pooled-best cell (lines 55–61, rejected on threshold 3). It is not shown for any
     other cell. On the bar *as written*, a cell at `w = 0.4` (best `heading` 0.2617, i.e. −0.0054
     against shipped 0.2671 — inside threshold 3's 0.01) or at `w = 0.5, rrf_k = 10` (`heading`
     0.2699, *above* shipped) needs only pooled +0.02 with a CI excluding zero and a gain visible
     in `masked` to pass all four. Given `masked` moves +0.27–0.37 at `w = 0`, that is plausible
     and is nowhere checked.
   - The preregistration is also internally inconsistent: §Metric (line 79) says pooled "is not the
     decision metric on its own" while threshold 1 makes it exactly that. The note inherits the
     inconsistency and silently resolves it.
   **Fix.** (a) In the preregistration, under "Decision thresholds", add a recorded deviation in
   the same strike-through style as the masked claim: thresholds 1, 2 and 4 re-scoped from pooled
   to `heading` after the instrument measurement, with the reason (pooled is 75% invalid families
   by construction), the original text standing. (b) In the note, either enumerate every cell that
   passes thresholds 1, 2 and 4 *as written* and show its threshold-3 value, or state plainly that
   the bar as written was not evaluated cell-by-cell and why. (c) Reword line 20 to "below the 0.02
   value fixed in advance, applied to `heading` rather than to the pooled quantity the
   preregistration named — see the recorded deviation".

2. **[BLOCKER] "Hybrid beats both single arms" is not supported at this n, and it is now in a
   normative document.** `research/m25-fusion-sweep.md` lines 75–83: dense-only 0.2545 against the
   shipped cell 0.2671 is +0.0126, and against the best blend 0.2739 is +0.0194. Both are below the
   0.02 bar; neither carries a CI; and the note's own standard (line 19–21) is that +0.0068 with a
   CI spanning zero is "nothing ships". The same paragraph then calls +0.013 "loses to the blend"
   and "the first direct evidence in this project that hybrid fusion beats either arm alone".
   Compounding it, the table at line 75 compares unlike things: at `w = 1.0` and `w = 0.0` the
   fused top-10 is one arm's top-10, which is invariant to `rrf_k` and to any `fusion_depth ≥ 10`
   (`experiments/m25_fusion_sweep.py` `fuse()` lines 226–229 — the zero-weight arm contributes
   `0.0`), so each single-arm column is **one value** while each blended column is a **maximum over
   36 cells**. A max-of-36 against a point estimate is the grid-maximum reading the brief asks
   about, in the one comparison the note treats as a positive result. Propagated to
   `design/knowledge-index.md` §16 item 1 lines 2691–2694 ("fusion beats **both** single arms …
   D5's premise measured rather than assumed") and item 3 lines 2716–2717 ("with both single-arm
   extremes losing"); the same sentence is in `FINDINGS.md` lines 564–567 (not a named artifact —
   listed so the sweep reaches it).
   **Fix.** Run the paired bootstrap on `heading` for shipped-vs-`w=0` and shipped-vs-`w=1`
   (fixed cells, not maxima) and report both CIs. Restate as: lexical-only loses to the shipped
   cell by 0.060 [CI]; dense-only is 0.013 below the shipped cell [CI], which at n=150 is (if the
   CI spans zero) not distinguishable from no difference. Then "this run shows fusion beating the
   lexical arm; it does not show it beating the dense arm" — and amend §16 items 1 and 3 to match.
   Label the `0.00` and `1.00` columns of the line-75 table as single values rather than "best
   cell over `rrf_k` and `fusion_depth`".

3. **[BLOCKER] The two numbers the conclusion rests on are not reproducible from the repository.**
   `research/m25-fusion-sweep.md` line 7 says both harnesses are "re-runnable in one command", and
   the brief says the harness "produced every number". `experiments/m25_fusion_sweep.py` emits
   per-cell means only (lines 306–327): no per-query reciprocal ranks, so no bootstrap can be run
   from its output; and nothing in it computes the query-term-overlap table (note lines 43–48) that
   the whole withdrawal rests on. Neither the CI `[−0.0067, +0.0191]` nor the `1.000 / 0.571`
   overlap figures can be regenerated by anyone, including the author, from what is checked in.
   Further reproducibility gaps in the same class: no results JSON is committed (precedent exists:
   `experiments/embedder-precision/results/*.json`); the corpus is named as `docs/RFCS/` with no
   upstream commit or ref (the FINDINGS §M25 block says "depth-1 sparse checkout" — of what?);
   the store directory is not named; and the note's "150 per family" (line 30) is reachable only
   by passing `150` as argv[3], since `DEFAULT_PER_FAMILY = 60` (harness line 58) — and the
   `heading` sample depends on that value through the shared `rng` sequence, so the default
   command reproduces a **different query set** than the one reported.
   **Fix.** Add per-query output (family, query text, truth ids, reciprocal rank and hit@5 at
   every cell, or at least at shipped and at every `w`-column best) and the overlap measurement to
   the harness or to a sibling `experiments/m25_fusion_stats.py` that reads the JSON; commit the run's
   JSON under `experiments/results/` or beside the note; record the upstream commit SHA of the
   checkout; and print the exact two commands, with `150`, in the note's line-7 paragraph.

4. **[BLOCKER] Three amended sites state an unscoped universal that is false on the quantity the
   preregistration named.** `zikaron/core/retrieval/__init__.py` lines 26–27: "no configuration
   beat the shipped one by more than 0.0068 MRR@10 against a 0.02 bar fixed in advance";
   `design/schema.md` line 891: "found no configuration beating the shipped one by more than
   0.0068 MRR@10"; `design/build-plan.md` line 1840: "best cell +0.0068 MRR@10 against a 0.02 bar".
   On pooled MRR@10 — threshold 1's own quantity — a configuration beat the shipped one by
   **+0.2246** (note line 57). A reader of any of these three sites cannot learn that the 0.0068 is
   `heading`-only, nor that a cell won by 0.22 on the preregistered metric and was rejected on a
   different threshold. This is the enumeration-drift class the corpus has a standing rule about,
   arriving in a code docstring and two design documents in one pass.
   **Fix.** One clause per site: "… by more than 0.0068 MRR@10 **on the one query family measured
   valid (`heading`, n=150; the three span families were measured invalid and on them a
   lexical-only cell won by +0.22 pooled)** …". The build-plan and schema sites can carry the short
   form "on the one valid query family".

5. **[IMPROVEMENT] `heading` is not clean either: it carries two structural sources of
   *exact-match non-truth chunks*, which is the mirror image of the span families' contamination.**
   The brief asks for the other side; here it is.
   - **The holding chunk.** `experiments/m25_fusion_sweep.py` lines 185–192 exclude the chunk
     containing the heading line from truth. That chunk still exists in both indexes — FTS over
     `text` **and `path`** (`zikaron/core/knowledge/ddl.py` line 84), dense over `path ⊕ text` —
     and it contains the query verbatim. So every `heading` query has, by construction, a
     guaranteed non-truth chunk that both arms will rank at or near 1. That is not the same as
     "genuine lexical distance"; it is a built-in exact-match distractor.
   - **Duplicate titles across RFCs.** Nothing dedupes heading text corpus-wide (only `_GENERIC` is
     filtered, lines 67–91). "Range leases", "Raft", "Schema changes" and the like plausibly head
     sections in several RFCs; a same-titled section in another file is a second exact-match
     non-truth chunk.
   Both penalise whichever arm rewards exact matches. The direction of net bias is unknown — the
   dense arm probably ranks the holding chunk first too — but the family the entire conclusion
   rests on should not carry an unmeasured one, and the note's own lesson (line 136) is to measure
   the instrument first.
   **Fix.** Score with a *filtered* ranking (drop `holding` ids from the fused list before computing
   rank — standard practice in link prediction; ~5 lines), and either dedupe titles corpus-wide or
   report how many `heading` queries have a same-titled heading elsewhere. Report, per arm, how
   often its rank-1 is the holding chunk or a same-title chunk. Two further instrument points to
   state in the note: (i) the 0.571 overlap was measured over chunk *text* with the harness's
   3+-character ASCII regex (`_WORD`, line 63), while the lexical arm queries `text` **and `path`**
   through `str.isalnum()` runs joined by `OR` (`zikaron/core/retrieval/query.py` lines 116–169) —
   so measure the instrument against what the arm actually indexes; (ii) for multi-chunk truth
   say which statistic the 0.571 is (max over truth chunks? union?), and report the fraction of
   `heading` queries at overlap 0 — "min 0.000" says some exist, and those are dense-only by
   construction, pulling the weight optimum toward dense. Finally, `_HEADING` (line 64) fires on
   `## ` lines inside fenced code blocks (shell/YAML/Python comments, common in RFCs);
   `tests/design_tables.py` line 70 already has a fence-aware heading parser — reuse or mirror it
   and report how many headings it removed. Also say in the note that "section" means "up to the
   next heading of *any* level 2–4", not the subtree (line 184).

6. **[IMPROVEMENT] Calling the span-family result "entirely artefactual" (note line 58) discards a
   real measurement about a real query class.** On exact-phrase queries — 15 words lifted from the
   answer — lexical-only beats the shipped hybrid by +0.27–0.37 and verbatim sits at 0.712 at the
   shipped cell. That is not an artefact *of retrieval*; it is the shipped fusion pulling an
   exact-match chunk from rank ~1 down to MRR 0.71, on the query shape a coding agent produces when
   it pastes an error string, an identifier or a sentence it just read — and it is the shape
   FINDINGS open question 8 and AWS's lexical steer are about. What the families cannot do is
   measure arm *balance* for queries that are not substrings of their answer. The two families pull
   `w` in opposite directions, which is the preregistration's own line 113–116 argument ("a weight
   optimal only at one masking rate is evidence the right weight is query-dependent … against a
   global constant") — the note should say that rather than "artefactual". Related misattribution:
   the threats bullet at lines 106–108 blames "sibling near-duplicates" for verbatim's 0.712, but
   if lexical-only scores ≈0.98 on the same queries (0.712 + 0.27), siblings are not what held it
   down at the shipped cell — the dense arm's votes did. **Fix.** Add a small table, family ×
   {shipped, `w=0`, `w=1`} MRR@10 (the harness already computes every cell of it); rewrite line
   58–59 as "a valid measurement of exact-phrase lookup and an invalid instrument for arm balance";
   correct the sibling bullet.

7. **[IMPROVEMENT] The closure's scale is an order of magnitude short of the scale the item was
   posed at, and the note does not say so.** `design/knowledge-index.md` §16 item 1's original
   text (line 2671) poses the question at "~22,800 chunks"; the closure is at 2,720 (12%).
   `FINDINGS.md` line 533 already records that no public prose tree reaches the figure. The
   preregistration says "two orders of magnitude larger" at lines 13 and 108–109; 187 → 2,720 is
   1.2 orders, and the note's own "~15×" (line 15) is the honest number. **Fix.** In the §16
   closure and the note's "What this changes" item 1, add "at 2,720 chunks — an order of magnitude
   short of the ~22,800 the item named; no public prose tree reaches that, and a code corpus is
   item 3's". Annotate the preregistration's "two orders" in place. And state the resolution the
   run had: the CI width (0.026) implies a minimum detectable effect of roughly 0.03 for a
   best-vs-shipped comparison, so "the defaults survive" means "no cell was shown better at
   ±0.013", not "no better cell exists".

8. **[IMPROVEMENT] A preregistered report was dropped silently.** Preregistration lines 75–77
   promise MRR@10 and hit@5 **after** the shipped `max_chunks_per_file = 2` cap, "reported
   separately, because the cap can evict a true chunk that ranking placed correctly". The harness
   never computes it and the note never mentions not doing so. It matters most for `heading`: the
   truth is several chunks of one file and the holding chunk from the *same* file competes for the
   two slots, so this is precisely where the cap evicts truth. The hit@5 the note reports is
   pre-cap, while a caller at `limit_per_kb = 5` sees post-cap. **Fix.** Compute it (the harness
   has `path` per chunk; `zikaron/core/knowledge/search.py` `_capped` is the reference) or record
   the deviation in the preregistration in place.

9. **[IMPROVEMENT] Post-selection inference and slice-only "flat" claims need one sentence each.**
   The CI at note line 19–20 is on the grid *maximum*; it is a post-selection interval (winner's
   curse), conservative for retaining a null but not an estimate of that cell's true effect — say
   so, since the same paragraph is the headline. "`rrf_k` is flat" (line 85) is measured on one
   slice (`w = 0.5, depth = 50`) and "`fusion_depth` is flat-to-slightly-negative" (line 86) on one
   slice (`w = 0.5, k = 60`); qualify both with "on the shipped slice". "Depth costs latency"
   (line 90) is asserted, not measured: `vec0` brute-forces the whole table whatever `k` is
   (`zikaron/core/knowledge/arms.py` lines 72–75), so depth's latency cost is the fusion loop and
   `_stored_chunks` — write "presumably costs" or measure it.

10. **[NITPICK] Corpus counts disagree between the two notes without comment.** Preregistration
    line 28: 188 files, 4,121,360 bytes; note line 27: 198 files, 4,135,684 bytes. `FINDINGS.md`
    lines 515–517 explain the 188 (`.md/.rst/.txt` only). One sentence in the note: what the ten
    additional admitted files were.

11. **[NITPICK] Harness fidelity to the product is claimed, not checked.** `fuse()` (harness lines
    223–232) sorts by `(-score, chunk_id)`; the product's `_fuse` (`search.py` line 102) sorts by
    `(-score, best_rank, chunk_id)`. Rare divergence, but "the shipped cell" is then a claim.
    Add a one-off assertion that `fuse(SHIPPED)` reproduces `search._fuse(...)` order for every
    query. Also `except Exception: lexical = ()` (line 295) swallows lexical failures with no
    count, and a swallowed failure scores `w = 0` cells at zero on that query — emit
    `lexical_failures` in the JSON (expected 0, and `expression is None` should be handled as the
    product does, line 304). Docstring line 46: at 2,720 chunks, 400 is 14.7%, not "~13%".

12. **[NITPICK] Undefined reference.** Note line 123, "the frozen-`meta` question … still
    recorded": cite where (the `FINDINGS.md` §M25 paragraph beginning "a swept value cannot reach an
    existing knowledge base"), so the note stands alone once that block is archived.

VERDICT: NEEDS_CHANGES

## Round 2 — 2026-09-18

### Summary judgment

Round 1's four blockers are genuinely resolved — the as-written bar is evaluated cell by cell in
the harness, the single-arm contrasts are fixed cells with CIs, the JSON is committed, and every
amended site carries the family scope. The rewrite is more honest than the original in every
direction it moved. Three things still stop it. Six figures in the note come from the superseded
run and disagree with the committed JSON (one of them with the note's own next table), while the
note and the harness docstring both say every number regenerates. The `rrf_k` section asserts a
conflict between families that its own table refutes — `heading`'s row maximum is at `k = 10` —
and that claim has already reached the code docstring, §16 and `FINDINGS.md` carrying a misquoted
0.106. And `heading`'s "measured valid" rests on the overlap axis alone: by the harness's own
`_GENERIC` rationale, 146 of its 150 queries fail the oracle's one-true-section premise, and no
sensitivity check was run. All fixes are cheap and none needs a rebuild; the store in the
scratchpad is enough to re-score.

### Findings

1. **[BLOCKER] Six figures from the superseded run survive in the note and disagree with the
   committed JSON.** The brief says all six sites carrying superseded figures were swept; these
   were not.
   - `research/m25-fusion-sweep.md` line 100, weight table, column `0.00`: **0.2462**. JSON
     `cells` at (60, 50, 0.0) `mrr10_heading` = **0.2475**, which is also what the note's own line
     128 and `by_arm.heading.lexical_only` say. 0.3226 − 0.0764 = 0.2462 is the pre-tie-break
     run's value (the brief's "0.0764 → 0.0751").
   - Line 152, `masked-50` at `k = 10`: 0.6468 → JSON (10, 50, 0.5) **0.6469**. Line 153,
     `masked-100` at `k = 10`: 0.4471 → **0.4475**; at `k = 20`: 0.3879 → **0.3883**.
   - Lines 172–173: "`fusion_depth` … 0.2704 → 0.2652 across 40×". JSON (60, 10, 0.5) heading =
     **0.3269**, (60, 400, 0.5) = **0.3195**. Those are the pre-filter run's numbers (shipped
     was 0.2671 then). The qualitative claim survives; the numbers do not — and the corrected
     depth-10 value is *above* shipped, which finding 2 needs.
   Consequence: line 18 "Full output, committed", harness docstring line 8 "This harness produces
   every number in `research/m25-fusion-sweep.md`", and the brief's "every number in the note
   comes from it" are false at six cells — the exact claim round 1's B3 was about.
   **Fix.** Replace each figure from the JSON. Then diff every number in the note against the JSON
   once, mechanically, rather than by sweep — the two tables sit twenty lines apart and disagree
   about one cell.

2. **[BLOCKER] The `rrf_k` "different directions / query-dependent" claim is refuted by the
   note's own table, and it has propagated with a misquoted number.**
   - Note lines 167–170: "the two families pull `rrf_k` in different directions … evidence that
     the right `rrf_k` is query-dependent". The table at lines 149–154 shows every family's row
     maximum at `k = 10`, `heading` included (0.3268 against 0.3226 shipped). "Different
     directions" requires a family that a small `k` *hurts*; none is shown. `heading` is
     indifferent-to-slightly-favouring, not opposed. The same is true of depth, which the note
     does not say: JSON (60, 10, 0.5) beats shipped on **all four** families (heading 0.3269,
     masked-100 0.4349, masked-50 0.6552, verbatim 0.7770) and is one of the 48 passing cells,
     worst family delta +0.0043.
   - Lines 204–205: "the gain is confined to families that cannot support a global change".
     `heading` gains +0.0042 at (10, 50, 0.5). "Confined" is wrong; "below the bar on the valid
     family" is right.
   - Propagated: `zikaron/core/retrieval/__init__.py` lines 31–34 ("`rrf_k = 10` beating 60 by
     0.106 MRR@10 on one family, which is evidence the right `k` is **query-dependent**");
     `design/knowledge-index.md` lines 2700–2703 (same sentence); `FINDINGS.md` lines 595–600
     (same). All three quote **0.106 as the 10-vs-60 difference**. JSON: 0.6469 − 0.5447 =
     **0.102**. 0.106 is the 10-vs-**200** span, which the note's line 157 states correctly.
   - What the data supports, and it is a cleaner statement: at the shipped weight, smaller `k` and
     smaller depth are **weakly dominant on every family**; the gains are large only where one arm
     is confidently right (the span families) and ~+0.004 on `heading`; nothing moves because
     +0.004 on the valid family is under the bar and the span families' representativeness for
     agent queries is unestablished. The "opposite optima, therefore query-dependent" shape is
     correctly stated for `w` (0.2475 vs 0.9780 at `w = 0`) and should not be extended to `k`.
   **Fix.** Rewrite lines 167–170 and 204–206 to the statement above; add depth to the same
   paragraph; correct 0.106 → 0.102 (or "spans 0.106 across the `k` grid") at the three
   propagated sites and reword their "query-dependent" clause to match.

3. **[BLOCKER] `heading`'s validity was measured on one axis; on the other, the harness's own
   rationale disqualifies 146 of its 150 queries.**
   - `experiments/m25_fusion_sweep.py` lines 91–92 filter `_GENERIC` titles because "as queries
     they are ambiguous across every RFC at once, so the oracle's 'one true section' premise fails
     for them." JSON: `heading_queries_with_duplicate_title` = **146**, `chunks_excluded_from_ranking`
     = 1,595 → roughly **9.6 other same-titled sections per sampled query**. The premise the
     harness names fails for 97% of the family by the harness's own criterion.
   - The sample is **size-biased**: `_heading_queries` shuffles heading *occurrences* (line 292),
     so a title occurring *k* times is *k* times as likely to be drawn — over-representing exactly
     the ambiguous titles. Nothing in the note says this.
   - The link-prediction analogy (note line 82, "filtered ranking, as in link prediction") is
     half-applied. Filtered ranking removes *other true answers* from the candidate list. Here the
     other same-titled sections' *heading chunks* are removed and their *bodies* stay and score as
     wrong. For a title in ten RFCs, nine sections on the same subject are negatives.
   - "Only differences between cells were read" (line 183) is not a defence: an oracle wrong for
     most queries adds noise identically to every cell, and noise favours the null that is the
     headline. Resolution (line 188) is bounded by this before it is bounded by n.
   - Answer to the brief's question 3: the intervention is not the distortion — removing
     guaranteed exact-match non-truth is right. What it left in is.
   **Fix (~15 lines, no rebuild).** A sensitivity run under a widened oracle — every same-titled
   section's body chunks count as truth (or, the full filtered-ranking analogue, exclude them from
   the ranking too) — reporting the three contrasts (best-vs-shipped, shipped − lexical,
   shipped − dense) and the weight row beside the current ones. Report the multiplicity
   distribution among the 150 (how many at 1, 2–4, 5–9, ≥ 10). If signs and bar hold, one
   sentence in the note and §16 item 1; if not, the closure needs its qualifier. Either way,
   "measured valid" at its six sites (note, §16 item 1, `__init__.py`, `schema.md`,
   `build-plan.md`, `FINDINGS.md`) should read "valid on the overlap axis", since that is what was
   measured.

4. **[IMPROVEMENT] The zero-weight arm leaks into the single-arm cells, refuting a stated
   invariance.** `fuse()` lines 338–343 insert rows from a zero-weight arm with score 0.0 and a
   `best_rank`. Whenever the non-zero arm's list, after exclusions, is shorter than ten, those
   rows fill the tail of the top-10 ordered by the *other* arm's rank. Evidence already in the
   JSON: (10, 10, 0.0) heading **0.2515** vs (60, 50, 0.0) **0.2475**, with the three span
   families byte-identical — the note (lines 112–113) and the preregistration (line 97) say these
   cells cannot differ ("invariant to `rrf_k` and to every `fusion_depth ≥ 10`"). Direction: the
   leak flatters "lexical-only", so the +0.0751 contrast is conservative; dense-only at depth 50
   is clean because `vec0` always returns 400 rows. No conclusion moves; the "constant by
   construction" sentence used to criticise the previous revision is false as written.
   **Fix.** Skip a zero-weight arm's rows in `fuse()`, re-score (seconds), re-derive `by_arm` and
   `contrasts`, and state the delta; or keep it, and correct lines 112–113 and prereg line 97 to
   "invariant except where the surviving arm returns fewer than ten rows".

5. **[IMPROVEMENT] "A caller sees the capped numbers" (note line 94) is not what a caller
   sees.** The post-cap metrics cap the *filtered* ranking (`score_grid` lines 482–486 cap
   `ranking`, which `fuse()` has already stripped of `excluded`). In production the holding chunk
   is in the ranking, sits in the **same file** as every truth chunk, contains the query verbatim,
   and so takes one of the two per-file slots ahead of truth. The caller-facing hit@5 is below
   0.3867 and the cap's cost is above 0.015. **Fix.** Cap the unfiltered ranking as a second
   column, or say "under the cap, on the filtered ranking" and delete "A caller sees".

6. **[IMPROVEMENT] The exact-phrase finding is sound; it is under-reported in one direction and
   over-generalised in another.**
   - Under-reported: hit@5 is the caller-facing quantity and it is *stronger*. JSON (60, 50, 0.5)
     vs (60, 50, 0.0): verbatim hit@5 **0.8267 vs 0.9933** (capped 0.7733 vs 0.9867); masked-50
     0.6933 vs 0.9733; masked-100 0.5267 vs 0.7733. One 15-word verbatim span in six does not
     have its source chunk in the top five under shipped fusion; nearly every one does under the
     lexical arm alone. Put hit@5 beside MRR in the line-123 table.
   - Over-generalised: what was measured is 15-word contiguous lowercase prose spans and their
     masked variants, whose truth is the **single** chunk they were lifted from. "An error string,
     an identifier" (note lines 119 and 161–163; `FINDINGS.md` line 598) are not in the set — an
     identifier is one rare token, an error string is short and punctuation-heavy, and either may
     occur in several files, where "which occurrence is the answer" is exactly what the dense arm
     might contribute and this oracle cannot see. Scope to "multi-word verbatim spans with a unique
     source"; name identifiers and error strings as the hypothesis they are.
   - The 47% end of "27–47%" is `masked-100`, the family the preregistration itself calls "text
     no human would type" (line 142). The clean number is `verbatim`'s 27% (and −17 points
     hit@5); say so where the range is quoted (note lines 41 and 130; `FINDINGS.md` line 587).
   - On the brief's question 2: the other side is the uniqueness assumption above, not the
     lookup-versus-balance distinction, which I accept as stated.

7. **[IMPROVEMENT] The `text + path` overlap column is measured with a tokenizer that cannot see
   a path match.** `_WORD` (harness line 88) keeps `_` inside a token and requires a leading
   letter; `chunks_fts` is `unicode61` (`zikaron/core/knowledge/ddl.py` line 87), which splits on
   `_` and accepts digit-led tokens, and the query side is `str.isalnum()` runs
   (`zikaron/core/retrieval/query.py` lines 116–134). So `docs/RFCS/20160210_range_leases.md`
   is `range_leases` to the harness and `range`, `leases` to the arm. The symptom is in the JSON:
   `text_plus_path_mean` equals `text_mean` to four decimals (0.5708) across all 150 queries —
   the column is a no-op, and note line 64's "because `chunks_fts` indexes both" describes a
   measurement that did not happen. `_WORD`'s three-character minimum also drops `db`, `2pc` and
   the like, which the arm matches. **Fix.** Tokenize query and target with `isalnum` runs,
   re-report, and restate the 27 zero-overlap count (lines 72, 184–185) if it moves.

8. **[IMPROVEMENT] The pooled bootstrap treats 600 queries as independent; 450 are triplets.**
   `verbatim`, `masked-50` and `masked-100` are built from the same 150 spans (harness lines
   308–317), so their per-query differences are correlated and the pooled CIs (lines 561–564)
   are narrower than warranted. The count of 48 is robust — threshold 1 is a point estimate, and
   the narrowest lower bound is 0.0126 at (60, 400, 0.4), which a √3 inflation would not push
   through zero — but say so, or cluster-bootstrap by span. Note line 180's "the 600 is not the
   n" is about `heading`; this is a second, independent reason.

9. **[IMPROVEMENT] State threshold 4's reading, and name the change the procedure would have
   shipped.**
   - `as_written_bar` line 557 reads "not confined to `verbatim`" as *any strictly positive
     rounded delta on a non-`verbatim` family*. Defensible and literal; the other reading is that
     the ≥ 0.02 must survive with `verbatim` removed. Emit `non_verbatim_pooled_gain` per passing
     cell and report the count under both readings — if 48 either way, the ambiguity is closed;
     if not, say which cells fall.
   - "Would have shipped a parameter change" (note line 32; `FINDINGS.md` line 565) — which?
     Arm weighting has its own clause (prereg lines 134–137: stable direction across `heading` and
     `masked`) that every `w = 0.4` cell fails (heading −0.005 to −0.008, masked positive). What
     the procedure would actually have shipped is a `w = 0.5` cell — e.g. (10, 10, 0.5), pooled
     +0.0667 [+0.0510, +0.0827], heading +0.0043 — a change to **both** `rrf_k` and
     `fusion_depth`. Naming it makes the counterfactual concrete and ties it to finding 2.

10. **[NITPICK] `as_written_bar` never applies threshold 2.** `ci_excludes_zero` is reported
    (line 573), not filtered on; all 48 happen to pass. Add `if lower <= 0 <= upper: continue` so
    the function does what its docstring says.

11. **[NITPICK] `_file_lines` (line 208) uses `str.splitlines()`; the product splits on `\n`
    only** (`zikaron/core/knowledge/chunking.py` line 31, M22's own decision, for exactly the
    reason that matters here — line numbers). Use `split("\n")` and assert
    `len(lines) == end_line − start_line + 1` per chunk, which turns the docstring's reliance on
    invariant 16 into a check.

12. **[NITPICK] `_headings_of` docstring (lines 216–217) asserts "RFCs in this corpus are full of
    them" while the run measured 0 of 2,586.** Reword to the measurement; the fence branch is
    unexercised on this corpus, so a three-line self-check with a synthetic fenced heading would
    be the only evidence it works.

13. **[NITPICK] Note line 16 contradicts itself**: "The `150` is required: `DEFAULT_PER_FAMILY`
    is 150 now". Say "150 is the default; any other count draws a different query set, not a
    subset."

14. **[NITPICK] Preregistration lines 129–130 still say "two orders of magnitude larger"
    unannotated.** Round 1 finding 7 named both sites; line 13 was annotated, this one was not.

15. **[NITPICK] Preregistration line 31 "188 files, 4,121,360 bytes" now disagrees with the
    built corpus (198 / 4,135,684) with no annotation**, against its own lines 7–8 rule. One
    bracketed line: "188 markdown files; the build admitted 198 — note §Corpus".

VERDICT: NEEDS_CHANGES

## Round 3 — 2026-09-18

### Summary judgment

Round 2's fifteen findings are genuinely addressed, the figure checker is a real addition, and
every four-decimal figure I re-derived from the committed JSON — the shipped row, the weight row,
the `rrf_k` slice, the depth endpoints, the best cell, the sensitivity table, the multiplicity
table — reconciles. The product's `_fuse` and `_capped` match the harness. What remains is the
class the checker cannot reach and the brief asked me to look for: the note's own "What this
changes" §4 restates, word for word, the `rrf_k` claim withdrawn 45 lines above it; the Threats
section still carries the pre-tokenizer-fix `27`; and the tokenizer fix moved the span-family
overlap from "1.000, minimum included" to 0.9975 / min 0.70 — a figure that survives unchanged at
three sites outside the note, one of them normative, beside a `+0.2219` that is the third value
that site has carried in three rounds. Nothing moves a conclusion. All of it is cheap, and all of it
is the round-2 B1 class arriving in the files the checker does not read.

### Findings

1. **[BLOCKER] The note's summary section restates the claim the body withdraws.**
   `research/m25-fusion-sweep.md` lines 313–315, "What this changes" item 4: *"Nothing moves on
   this evidence — the gain is confined to families that cannot support a global change — but
   'flat' is withdrawn, and a query-dependent `k` is the shape any future work should test."* Lines
   265–271 say the opposite in so many words: *"the reason is 'below the bar on the valid family',
   **not** 'confined to families that cannot support a global change', which an earlier revision
   said and which the +0.0042 refutes"* — and lines 257–259 strike through "query-dependent" for
   `k`. This is round 2's B2 surviving in the one section a reader copies into §16. The propagated
   sites (`__init__.py` lines 31–36, `knowledge-index.md` lines 2700–2707, `FINDINGS.md` lines
   602–613) all carry the corrected statement; the note's own summary does not.
   **Fix.** Rewrite item 4 to the body's statement: *"`rrf_k` and `fusion_depth`: 'flat' is
   withdrawn. Smaller values are weakly dominant on every family, ~+0.004 on the valid family and
   under the bar; large only on exact-phrase queries, whose representativeness for agent queries is
   unestablished. Nothing moves. Opposite optima is established for `w` alone (item 3)."*

2. **[BLOCKER] Five stale figures survive where the checker does not look — four of them from the
   round-2 tokenizer fix, one from the leak fix.**
   - Note line 286: *"**27 of 150 `heading` queries have zero lexical overlap with truth** and are
     dense-only by construction."* JSON `instrument.overlap.heading.at_zero_overlap` = **23**,
     `at_zero_overlap_with_path` = **22**; the note's own table at line 86 says 23. Round 2 finding
     7 named this line by number and the brief reports it fixed. Since the lexical arm indexes
     `path`, the by-construction dense-only count is 22; write "22 (23 against text alone)".
   - Preregistration lines 60–61, inside the refutation block: *"**1.000 at every masking rate,
     minimum included** — against 0.571 for `heading`."* Current run: means 0.9975 / 0.9992 /
     1.0000, minima **0.70** / 0.875 / 1.0; `heading` 0.5950 (0.6069 with path). The refutation
     block is the record of the refutation and now quotes figures the committed run does not
     produce, in a document whose own line 8 says corrections are recorded in place.
   - `design/knowledge-index.md` line 2740: *"(100.0% of query terms, minimum included)"* — same
     claim, normative document.
   - `design/knowledge-index.md` line 2742: *"the winner is **lexical-only by +0.2219**"*. JSON:
     every `w = 0` cell is pooled 0.7056, shipped is 0.4850, so **+0.2206**. Round 1 read +0.2246
     (first run), this is the tie-break run's value, and the committed run gives a third. Three
     values at one site in three rounds is the checker's case for reading this file too.
   - `FINDINGS.md` lines 573–574: *"**100.0% of their query terms appear verbatim in the true
     chunk**, minimum included, at every masking rate"* — same claim; not a named artifact, listed
     so the sweep reaches it.
   The substance survives every one of these (the span families still hand the lexical arm the
   answer), which is exactly why they went unnoticed: nobody re-derived them because nothing
   depended on them. Fix each from the JSON, then see finding 4 for stopping the class.

3. **[IMPROVEMENT] "Constant by construction … invariant to every `fusion_depth ≥ 10`" is false
   for `w = 1`, and the brief already knows the number.** Note lines 181–182 (and `FINDINGS.md`
   line 587): *"single-arm columns that are **constant by construction** — at `w = 0` and `w = 1`
   the fused order is one arm's order, invariant to `rrf_k` and to every `fusion_depth ≥ 10`."*
   JSON: `mrr10_heading` at `w = 1.0` is **0.2936** at depth 10 and **0.2942** at every depth
   ≥ 25, for all six `k`. The brief reports this as "`w = 1` still varies by 0.0006 across depths
   because exclusions can leave the dense arm shorter than ten" — correct, and a mechanism the leak
   fix cannot touch, since it is the exclusion set and not the zero-weight arm doing it. Round 2
   finding 4 offered the alternative wording for exactly this residue; the leak was fixed and the
   sentence kept, so it now asserts the pre-fix world in the sentence used to criticise the previous
   revision. The preregistration's line 99 (*"`rrf_k` cannot change the order"*) is the true half
   and should stay. **Fix.** *"invariant to `rrf_k`; invariant to depth except at depth 10, where
   the exclusion set can leave the surviving arm short of ten rows (dense-only `heading` 0.2936 at
   depth 10 against 0.2942 above it)"*, at both sites.

4. **[IMPROVEMENT] The checker's oracle is "appears anywhere in the JSON", which is weaker than
   its docstring says, and the note already contains the case that shows it.**
   `experiments/m25_verify_note_figures.py` line 11–12: *"a four-decimal figure in the note is a
   measurement, so it must appear somewhere in `…json`."* The JSON holds roughly 5,000 numbers
   (252 cells × 17 metrics plus the passing list), thousands of them distinct four-decimal values
   in [0, 1], so a stale figure reconciles by coincidence with a probability that is not small.
   Concrete instance: note line 148 quotes **0.2671** as the superseded shipped `heading` value. It
   is not in any summary field; it passes because `(10, 25, 0.25)` happens to have
   `mrr10_capped_heading = 0.2671`. Had the old value been 0.2670 the checker would have failed on a
   legitimately historical figure; as it stands it accepts one by luck. Neither behaviour is the
   one described. I did check the brief's claim: five of round 2's six stale figures (0.6468,
   0.4471, 0.3879, 0.2704, 0.2652) are absent from the committed JSON, so it would have caught
   them; the sixth, 0.2462, is now the correct value.
   **Fix.** (a) Print `len(known)` and state the coincidence rate in the docstring. (b) Add an
   explicit allowlist of figures the note quotes *historically* — today `0.2671` — each with its
   reason, so historical figures are exempted deliberately rather than by collision, and a figure
   not on the list must reconcile. (c) The docstring says integers are not checked; after finding 2
   that is the hole the `27` went through. A short named-integer list (`at_zero_overlap`,
   `heading_queries_with_duplicate_title`, `chunks_excluded_from_ranking`, `headings_seen`,
   `headings_dropped_generic`, the multiplicity counts) checked against the note's prose costs ten
   lines. (d) `NOTE` is one file; the preregistration and `knowledge-index.md` §16 items 1 and 3
   quote the same run. Read all three, or state the limit where the docstring claims the class is
   closed.

5. **[IMPROVEMENT] The brief's question 2, answered: the sensitivity analysis settles B3 as
   posed, but its agreement is bounded by construction and the note presents it as a finding.**
   Note lines 142–146: *"All three agree on every sign, every significance decision and every
   conclusion."* They could hardly not. Only 14 of 150 queries have any same-titled section and
   their widened truth adds 25 body sets in total, so the three oracles could not have disagreed
   by more than ~0.09 even if every affected query flipped from 0 to 1, and they disagree by 0.0033.
   The table confirms the multiplicity count; it does not add independent evidence that `heading`
   is valid. Say that in one sentence, since the paragraph currently reads as though agreement
   were the evidence. Three related corrections:
   - Lines 145–146, *"`strict` is numerically identical to as-scored because the excluded bodies
     almost never reach the top ten anyway"*, is refuted by the row above it: `widened` moves
     +0.0033 ≈ 0.5/150, which is one query with a same-title body at **rank 2** and no truth in the
     top ten — a body *did* reach the top ten. The correct mechanism is that no same-title body ever
     sits *above a truth chunk* within the top ten, so removing one changes no reciprocal rank.
   - `sensitivity()` (`m25_fusion_sweep.py` lines 629–632): `widened` adds other sections' bodies to
     truth while `excluded` still removes their heading chunks. If those sections are legitimate
     answers their heading chunks are too, so `widened` is slightly less generous than its name.
     Immaterial at these magnitudes; one clause in the docstring.
   - The axis no oracle here tests, and the note should name as the remaining one: same-subject
     sections under *different* titles ("Range leases" against "Lease transfers"), which score as
     negatives under all three. The preregistration's within-file near-miss threat (line 150) is
     the same limitation one file wider.
   - **Withdrawing my own round-2 instruction.** Finding 3 asked, "either way", that "measured
     valid" read "valid on the overlap axis" at six sites. It was not done, and it should not be:
     validity has now been measured on the title-ambiguity axis as well. "Measured valid" stands —
     but the note should say *on which two axes*, so the next reader knows what a third one would be.

6. **[IMPROVEMENT] The brief's question 3, one instance: the headline's hit@5 is the pre-cap
   pool figure, and the preregistration defines hit@5 as the caller-facing one.** Note line 49
   (*"drops hit@5 from 0.9933 to 0.8267"*), lines 194–203 and `FINDINGS.md` line 590 all quote
   `hit5_verbatim`; preregistration lines 79–80 define hit@5 as *"what a caller at the shipped
   `limit_per_kb` would actually see"*. For `heading` the note is careful that the capped figure is
   *not* caller-facing because of the exclusion set (lines 158–163). For the span families there
   is **no** exclusion set, so `hit5_capped` is exactly caller-facing — and it is the stronger
   number: JSON shipped `hit5_capped_verbatim` **0.7733** against lexical-only **0.9867**, a drop of
   0.213 rather than 0.167. Quote the capped pair for the span families, or label the current one
   "pre-cap". Either way the sentence *"One 15-word span in six does not have its own source chunk
   in the top five"* becomes "more than one in five" on the number a caller sees.

7. **[IMPROVEMENT] The brief's question 1, answered: yes, but only in one of the two kinds of
   self-reference, and the split is clean.** Seventeen "earlier/previous revision" references and
   two strikethroughs in 330 lines. They divide:
   - **Withdrawals of published claims** — masking (98), hybrid-beats-both (176), "artefactual"
     (186), 27–47% (210), scope (213), sibling misattribution (220), `rrf_k` directions (257),
     "confined" (269). The withdraw-in-place rule protects these; keep every one.
   - **Narration of instrument bugs fixed before the result was final** — the FINDINGS
     reconciliation (58–64), `splitlines` (68–73), the tokenizer (88–96), the mislabelled field
     (113–126), post-cap (155–163). About 35 lines. These are review-trail history rather than
     beliefs the note ever published as results, and §"The instrument" is now half process
     narrative: a reader who wants the validity table reads three paragraphs of how it was
     previously wrong first.
   **Fix.** Compress each item of the second kind to one clause carrying the measurement and a
   pointer to the review round (*"tokenized as the arm tokenizes — round 2 finding 7; the earlier
   `_WORD` measurement made the path column a no-op"*). Line 20, *"Round 1 of review rewrote this
   note"*, is itself stale after rounds 2 and 3; say "three review rounds".

8. **[NITPICK] The counterfactual cell is chosen by an unstated rule, and depth alone would have
   sufficed.** Note line 36 names (10, 10, 0.5) as what the procedure "would have shipped". The
   preregistration has no tie-break among 48 passing cells; the implicit rule is *largest pooled
   gain among `w = 0.5` cells*. JSON: (20 | 40 | 60 | 100 | 200, 10, 0.5) are byte-identical at
   pooled +0.0635, worst-family +0.0043, CI [+0.0482, +0.0794] — at depth 10 every `k ≥ 20` fuses
   the same — so `fusion_depth` 50 → 10 alone passes the same bar with the same worst-family
   delta. State the rule, and that the minimal change was a single parameter.

9. **[NITPICK] Harness docstring lines 24–29 is the pre-round-2 world.** *"Two instrument
   corrections, both from review round 1"* — there are now six (fence, holding-chunk exclusion,
   product tie-break, zero-weight leak, arm tokenizer, `\n`-only splitting), four of them from
   round 2. Either list them or say "the instrument corrections are recorded at their sites".

VERDICT: NEEDS_CHANGES

## Round 4 — 2026-09-18

### Summary judgment

**No blocker.** I read this round the way the brief asked — weighted toward what round 3's fixes
touched — and re-derived every figure those fixes moved from the committed JSON: the post-cap by-arm
table (all sixteen cells, plus the eight pre-cap values beneath it), the sensitivity table and its
±0.09 bound, the `rrf_k` slice, the weight row, the depth endpoints, the (10, 10, 0.5) cell and the
five depth-10 `k ≥ 20` cells at +0.0635, the `w = 1` 0.2936/0.2942 residue (and `w = 0`, which is
0.2462 at every one of the 36 cells), the 48-of-48 under both threshold-4 readings, the narrowest
lower bound (0.0126 at (60, 400, 0.4)), the 175 = 150 + 25 exclusion count, and the +0.2206
derivation. All reconcile. The summary section, the four propagated sites and the preregistration's
deviation block now say what the body says. **On the brief's question 2: yes, it reads as a result.**
The headline is the result, the corrections are marked where they stand, and 13 "earlier revision"
references remain of the 17 — the ones left are the withdrawals the corpus rule protects. Four
improvements below, each a few lines; one (finding 2) needs a harness re-run of minutes and no
rebuild. I would approve on those being made, and a fifth round need not re-read the note.

### Findings

1. **[IMPROVEMENT] The Threats bullet attributes the filtering choice's size to the half that does
   not carry it — the brief's question 3, one instance.** `research/m25-fusion-sweep.md` lines
   303–306: *"`heading` is shaped by a filtering choice, though a smaller one than it first appeared:
   excluding same-title heading chunks touches **14 of 150** queries … and the sensitivity table above
   shows the three defensible choices agreeing on every conclusion."* Two exclusions are made
   (`fuse()` line 412 over `Query.excluded`, built at harness line 321 as `holding | titled_holders`).
   The **holding-chunk** exclusion touches **all 150** queries (150 of the 175 exclusions) and is the
   source of the +0.055 at line 160; the same-title exclusion touches 14 and contributes 25. The
   sensitivity table tests only the same-title *bodies* choice; the holding-chunk exclusion has no
   sensitivity run and rests on the argument that the chunk contains the query verbatim and is
   non-truth by the oracle's definition (preregistration line 73). That argument is right — but the
   bullet as written lets a reader take "14 of 150" as the size of the choice the conclusion depends
   on, when the choice that moved the number touches every query and was not varied.
   **Fix.** *"`heading` is shaped by two filtering choices. The holding chunk is excluded from the
   ranking for every query — that is where the +0.055 came from; it is not sensitivity-tested, and
   the justification is that it contains the query verbatim and is non-truth by the oracle's own
   definition. Same-title heading chunks are also excluded, touching 14 of 150 queries, and that
   choice is the one the sensitivity table varies; the three completions agree."*

2. **[IMPROVEMENT] One integer in the note has no source in the committed run, and it is the one
   the harness says it produces.** Note line 66 (and `FINDINGS.md` line 669): the 20 non-markdown
   chunks are *"**zero** queries in any family draw truth from"*. The JSON carries
   `non_markdown_chunks: 20` and nothing about which queries' truth lies in them; the harness prints
   no truth ids; so "zero" cannot be regenerated from `experiments/results/m25_fusion_sweep.json`,
   which is round 1's B3 class at small stakes. It is also not obviously true a priori: an SVG's XML
   and a PlantUML file tokenize to plenty of three-letter words, so those chunks are plausibly in
   `usable` (harness line 362), and 150 draws against ~20 of ~2,500 usable chunks leave "none drawn"
   somewhere near a coin flip. For `heading` it is zero by construction (no `## ` lines); for the
   three span families it is a sample fact. If it is not zero, the figure that moves is not the
   headline but the framing at line 203 — a span lifted from an SVG is not "a sentence an agent just
   read".
   **Fix (~5 lines, re-run the sweep, no rebuild).** Emit, per family, the count of queries whose
   truth contains a non-`.md` chunk — e.g. `"queries_with_truth_in_non_markdown": {family: n}` next
   to `non_markdown_chunks` in `main()` — quote the note from it, and add it to the checker's
   `NAMED_INTEGERS`. With the fixed seed every other figure should come back byte-identical; run
   `m25_verify_note_figures.py` afterwards to confirm that rather than assume it.

3. **[IMPROVEMENT] The checker has two guards that cannot fail, and one of them is quoted as
   closing the hole it does not close.**
   - `experiments/m25_verify_note_figures.py` lines 146–152: the named-integer check prints
     `quoted` / `NOT QUOTED` and never touches `failures`. It also checks only that the *correct*
     integer appears somewhere in the note (`\b23\b` — anywhere, including inside another number),
     so a note that still said "27 of 150" beside a correct "23" elsewhere would print `quoted` and
     exit 0. The docstring (lines 79–80) and `FINDINGS.md` lines 656–657 (*"checks named integers
     too (the stale `27`-against-23 went through the four-decimal hole)"*) read as though that hole
     is closed. It is half-closed: the check sees a correct value *absent*, not a stale value
     *present*. That is the docstring's own warning — a check "quoted as coverage" — applied to
     itself.
   - `_scoped()` lines 107–115: a start marker that is not found yields `""`, which yields **zero
     figures and `ok`**. `SOURCES` keys `FINDINGS.md` on the literal `"**Track B's result"` and
     `schema.md` / `build-plan.md` on mid-sentence phrases; the first is the lede finding 8 below asks
     to edit. Editing any of those markers turns that file's check silently vacuous.
   **Fix.** (a) Count `NOT QUOTED` into `failures`, and reword the docstring and `FINDINGS.md`
   656–657 to what the check does: *"asserts the run's integers appear in the note; it cannot see a
   stale integer that is also present"*. (b) In `_scoped`, raise if `start` or `end` is not found,
   and fail if a scoped source yields zero figures — a source that contributes nothing is a marker
   that stopped matching. Mutation-verify both by deleting a marker character and by re-inserting
   "27 of 150" in the note.

4. **[IMPROVEMENT] The span-family lede names, as the shape measured, the two things the scope
   paragraph excludes.** Note lines 203–204: exact-phrase lookup *"is a query shape a coding agent
   produces constantly: pasting an error string, an identifier, or a sentence it just read."* Lines
   234–239 then say an error string or bare identifier *"is **not** in this query set"* and is a
   hypothesis. The `rrf_k` section (lines 271–273) gets it right; this lede does not, and it is the
   sentence a reader carries into the table. **Fix.** *"… a query shape a coding agent produces
   constantly — pasting back a sentence it just read; whether it extends to error strings and bare
   identifiers is the hypothesis stated under Scope below."*

5. **[NITPICK] "fuses identically" is a mechanism claim the mechanism does not make.** Note line
   42: *"at depth 10 every `k ≥ 20` fuses identically"*. The five cells are identical to four
   decimals on every family (verified: (20|40|60|100|200, 10, 0.5) all +0.0635, worst +0.0043),
   but RRF at different `k` can order two chunks differently at depth 10 — ranks (1, 10) beat (5, 5)
   at `k = 20` (1/21 + 1/30 = 0.0810 > 2/25 = 0.0800) and lose at `k = 200` (0.009737 <
   0.009756). Identical figures are the observation; write *"scores identically on every family"*,
   since round 3's finding 3 is about exactly this distinction.

6. **[NITPICK] Harness docstring line 24: "Six instrument corrections, from three review rounds"
   — they are from two.** Fence, holding-chunk exclusion and the tie-break are round 1 (findings 5
   and 11); the zero-weight leak, the arm tokenizer and `\n` splitting are round 2 (4, 7, 11). Round
   3 changed no instrument. The seventh correction that *is* missing from the list — the
   multiplicity counters re-scoped from every section to the sampled set, harness lines 339–343 — is
   also round 2's. Say "two review rounds" or list the seven.

7. **[NITPICK] The preregistration's corpus annotation landed inside a number.** Lines 31–34 now
   read *"median file 17,080 bytes, largest *(as planned. **The build admitted 198 files** … )*
   181,756."* — the bracket splits "largest 181,756". Move the parenthetical to the end of the
   sentence after "181,756."

8. **[NITPICK] Two referents went ambiguous in the compression.** Note lines 160–161: *"**The
   instrument fix** moved `heading` by +0.055 … Every `heading` number in **the previous revision**
   is superseded."* After round 3's cuts, "the instrument fix" sits 55 lines and one sensitivity
   analysis after the fix it means (lines 101–105), and "the previous revision" is one of three.
   *"Excluding the two distractors moved `heading` by +0.055 … every `heading` number in the round-1
   revision"*. Same class, `FINDINGS.md` — not a named artifact, listed so the sweep reaches it:
   line 553 *"as it stands after review round 1 rewrote it"* (three rounds; the note's twin at line
   20 was fixed in round 3); line 572 *"The instrument was broken twice"* against the same block's
   later count of five; line 632's *"All three agree on every sign …"* carries none of the
   bounded-by-construction clause the note now has at lines 138–142. **When line 553 is edited, keep
   the `**Track B's result` prefix intact or the checker's `FINDINGS.md` scope goes empty — finding
   3(b).**

9. **[NITPICK] The validity table's last column is the text-only count and does not say so.** Note
   lines 83–88: "queries at zero overlap" reads 23 for `heading`; the Threats bullet (line 307) leads
   with 22 and explains the difference. Head the column "at zero overlap (text)" or add the
   with-path column, so the table and the bullet are visibly the same measurement.

10. **[NITPICK] Round 3 finding 5's last request is half-done: the two axes are never named where
    "measured valid" is claimed.** Line 157 says *"the third axis"*; nothing before it enumerates
    the first two. One parenthetical at line 97–99: *"valid on the two axes measured here — term
    overlap against truth, and title multiplicity"*.

VERDICT: NEEDS_CHANGES
