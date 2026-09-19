# M25 — the fusion sweep: the defaults survive the bar that matters, and fail the bar as written

**Preregistration:** `research/m25-fusion-sweep-preregistration.md`, written before the corpus
finished building and before any cell was scored. Read it first. **Two of its claims are refuted
below**, and one of its decision thresholds turns out to have been fixed on the wrong quantity — a
deviation recorded there in place rather than resolved silently here.

**Reproduction, exactly as reported.** Corpus `cockroachdb/cockroach` at commit
`13cb3eb27674b4a981e5c526d04c2387e81efd0b`, path `docs/RFCS/`, depth-1 blobless sparse checkout.

```
.venv/bin/python experiments/m25_build_sweep_corpus.py <checkout>/docs/RFCS <store-dir> cockroach_rfcs
.venv/bin/python experiments/m25_fusion_sweep.py <store-dir> cockroach_rfcs 150
```

150 is also the default, so the argument is redundant — but write it anyway, because the query set
is drawn from one seeded `random.Random` and **any other count produces a different query set, not
a subset of this one**. Full output, committed: `experiments/results/m25_fusion_sweep.json`.

**Three review rounds rewrote this note**, and the headline below is the opposite of the one that
first stood here. Trail: `reviews/m25-fusion-sweep-review.md`. Claims this note once published and
has since withdrawn are struck through in place; instrument bugs fixed before any result was final
are cited to their review round rather than narrated.

---

## Headline

**On the one query family measured valid, the shipped configuration survives: the best cell in 252
beats it by +0.0069 MRR@10, 95% CI [−0.0084, +0.0227], against a 0.02 bar. Nothing ships.**

**But on the bar as *preregistered* — which was fixed on pooled MRR@10 across all four families —
48 cells clear every threshold, with pooled gains to +0.1314 and bootstrap CIs excluding zero.**
It is refused only because the quantity it was fixed on was later measured invalid, and that
re-scoping is a decision made *after* seeing the data.

**Named concretely, because "would have shipped a parameter change" is too vague to check.** The
procedure would have shipped **`rrf_k` 60 → 10 and `fusion_depth` 50 → 10** — cell (10, 10, 0.5),
pooled +0.0667 [+0.0510, +0.0827], `heading` +0.0043, no family regressing. *The preregistration
fixes no tie-break among 48 passing cells; the rule used here is **largest pooled gain among
`w = 0.5` cells**, stated because it was implicit. **The minimal passing change is smaller still**:
at depth 10 every `k ≥ 20` **scores** identically on every family (pooled +0.0635, same
worst-family +0.0043 — an observation, not a mechanism: RRF at different `k` can order two chunks
differently even at depth 10), so
`fusion_depth` 50 → 10 **alone** clears the same bar — one parameter, not two.* **Not an arm weight**:
the preregistration gives weighting its own extra clause (a stable direction across `heading` and
`masked`), and every `w = 0.4` cell fails it. **Threshold 4 is reported under both its readings** —
*some* non-`verbatim` family gains, and the ≥ 0.02 surviving with `verbatim` dropped — and **48
cells pass either way**, so that ambiguity decides nothing.

**That is the methodological finding worth carrying: preregistering a threshold does not protect you
if you preregister it on the wrong quantity.** The value was fixed in advance and honoured; the
*denominator* was not, and the denominator is where the result lived.

**And the product finding, which the first revision buried by calling three families
"artefactual": on multi-word verbatim spans the shipped hybrid throws away 27% of the lexical arm's
MRR@10, and drops the caller-facing hit@5 from 0.9867 to 0.7733.** Conceptual queries want the blend; exact-phrase
queries want the lexical arm nearly unmixed. **The two classes want opposite weights**, which is why no single constant in this
grid is worth moving to — and is the strongest thing this run says about §16 item 3.

## Corpus

198 files, **4,135,684 bytes, 2,720 chunks**, built in 367 s at load 11.85 on 12 cores.
`bge-small-en-v1.5`, `chunk_max_tokens = 450`, `git_mode = off`.

**198, not the 188 markdown files the preregistration names**: the build passed no `include` glob,
so the default admitted 9 PlantUML files and one `.svg` — **20 chunks of 2,720 (0.74%)**, and
**zero** queries in any family draw truth from them (`queries_with_truth_in_non_markdown` in the
committed run — a *sample* fact for the span families, not a construction one, and so measured
rather than assumed), leaving 20 extra distractors in the pool (round 2, finding 10).

600 queries, 150 per family, seed 20260918, **0 lexical-arm failures**.

**One incidental verification.** Reconstructing each file from its chunks asserts that a chunk
yields exactly the lines its `start_line`/`end_line` claim, splitting on `\n` alone as
`chunking.py` requires (round 2, finding 11). It holds for all **2,720** chunks — **invariant 16
checked against a third-party corpus rather than a fixture** — and changed no figure, this corpus
containing none of the nine characters `str.splitlines()` additionally breaks on.

## The instrument, measured before anything is read off it

**Family validity — fraction of query terms appearing verbatim in the true chunk**, taken against
chunk text and again against text plus path, because `chunks_fts` indexes both. For multi-chunk
truth the statistic is the **maximum over truth chunks**.

| family | text | min | text + path | at zero overlap (text) |
|---|---|---|---|---|
| `verbatim` | **0.9975** | 0.7000 | 0.9975 | 0 |
| `masked-50` | **0.9992** | 0.8750 | 0.9992 | 0 |
| `masked-100` | **1.0000** | 1.0000 | 1.0000 | 0 |
| `heading` | 0.5950 | 0.0000 | 0.6069 | **23** |

**Tokenized as the lexical arm tokenizes** — `isalnum` runs, matching `unicode61` and the query
builder — which took a correction (round 2, finding 7: the earlier `_WORD` pattern could not see a
path match, so the `text + path` column returned values identical to `text` for all 150 queries).

**The preregistration's masking claim is refuted.** It said masking "starves the lexical arm by
construction"; it does not. Masking removes *terms from the query* and leaves every survivor an
exact match, so BM25 keeps a shorter but near-perfect hit at every rate — 0.9975 to 1.0000 mean
across the three span families, never below 0.70 on any single query. **Only `heading` has genuine
lexical distance** (0.5950 mean, 23 of 150 at zero against text), and it is the only family whose
numbers mean anything for arm balance.

**"Measured valid" here means valid on the two axes this run measured** — term overlap against
truth, and title multiplicity. A third, same-subject sections under *different* titles, is named
below and is untested.

**`heading` was not clean either, and this run fixes it.** Two structural exact-match distractors
existed by construction: the chunk *holding* the heading line, which contains the query verbatim
and is excluded from truth but was still being ranked; and the heading chunks of **same-titled
sections elsewhere in the corpus**. Both are now removed from the ranking before scoring — filtered
ranking, as in link prediction — at a mean of **1.17 excluded chunks per query**. Fenced `## ` lines
are no longer read as headings, though on this corpus that removed **0** of 2,586 headings seen;
250 were dropped as generic furniture.

**Title repetition is a real hazard and it is small here.** Among the **150 sampled** queries:

| sections sharing the title | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| queries | **136** | 9 | 1 | 2 | 2 |

So **14 of 150 (9.3%)** share a title at all, and the mean number of other same-titled sections is
**0.17**. *These counters previously reported over every section in the corpus while being named for
the sampled set — 146 and 1,595 — and round 2 built a blocker on the names, correctly (finding 3).
**A mislabelled field is a false claim with a number attached**, and it is the one defect here that
a reader could not have caught by reading more carefully.*

**The sampling is size-biased and that is stated rather than hidden**: `_heading_queries` shuffles
heading *occurrences*, so a title appearing *k* times is *k* times as likely to be drawn. With
136 of 150 unique the effect is small, but the bias runs toward ambiguity, not away from it.

**And filtered ranking was only half-applied, which is round 2's substantive point and survives its
magnitude being wrong**: other same-titled sections' *heading* chunks were removed while their
*bodies* stayed in as negatives. Rather than argue about it, both completions were run.

| `heading` oracle | shipped | lexical-only | dense-only | shipped − lexical | shipped − dense |
|---|---|---|---|---|---|
| **as scored** (bodies are negatives) | 0.3226 | 0.2462 | 0.2942 | +0.0764 [+0.0393, +0.1147] | +0.0284 [−0.0114, +0.0683] |
| **widened** (bodies count as truth) | 0.3259 | 0.2492 | 0.2971 | +0.0768 [+0.0398, +0.1151] | +0.0288 [−0.0113, +0.0688] |
| **strict** (bodies excluded from ranking) | 0.3226 | 0.2462 | 0.2942 | +0.0764 [+0.0393, +0.1147] | +0.0284 [−0.0114, +0.0683] |

**All three agree on every sign, every significance decision and every conclusion.** The largest
disagreement anywhere in the table is `widened`'s shipped 0.3259 against as-scored 0.3226.

**Read that as a confirmation of the multiplicity count, not as independent evidence that `heading`
is valid — the agreement is bounded by construction.** Only 14 of 150 queries have a same-titled
section at all, so even if every affected query flipped from 0 to 1 the three oracles could differ
by at most ~0.09; they differ by 0.0033. The table says the title ambiguity is too small to decide
anything, which is what it was run to find out, and nothing more.

**`strict` is numerically identical to as-scored, and the obvious explanation is wrong.** It is not
that excluded bodies never reach the top ten — `widened` moves +0.0033 ≈ 0.5/150, which is one
query where a same-title body sits at rank 2 with no truth above it. The actual property is that no
same-title body ever sits **above a truth chunk** inside the top ten, so removing one changes no
reciprocal rank.

**One asymmetry in `widened`, stated because its name overstates it**: it promotes other sections'
*bodies* to truth while still excluding their *heading* chunks from the ranking. If those sections
are legitimate answers their headings arguably are too, so `widened` is slightly less generous than
it sounds. Immaterial at these magnitudes.

**And the axis no oracle here tests**: same-subject sections under *different* titles — "Range
leases" against "Lease transfers" — score as negatives under all three. That is the
preregistration's within-file near-miss threat, one file wider, and it is the third axis a future
validity check would have to measure.

**Excluding those two distractors moved `heading` by +0.055** — 0.2671 to **0.3226** at the shipped
cell. Every `heading` number in this note's round-1 revision is superseded.

## What the valid family says

`heading`, at the shipped cell: **MRR@10 0.3226, hit@5 0.4267**; under the shipped
`max_chunks_per_file = 2` cap, **0.3076 and 0.3867** — the cap costs ~0.015 MRR and ~0.04 hit@5,
which is the post-cap figure the preregistration promised and an earlier revision silently did not
compute.

**These are the cap applied to the *filtered* ranking, and that is not what a caller sees.** The
holding chunk is excluded here but present in production, where it sits in the **same file** as
every truth chunk and contains the query verbatim — so it takes one of that file's two slots ahead
of truth. The caller-facing hit@5 is therefore **below** 0.3867 and the cap's real cost **above**
0.015. An earlier revision said "a caller sees the capped numbers", which is wrong in the direction
that flatters the result.

**Arm weight at the shipped `rrf_k` and depth** — fixed cells, not maxima:

| dense weight | 0.00 | 0.25 | 0.40 | **0.50** | 0.60 | 0.75 | 1.00 |
|---|---|---|---|---|---|---|---|
| MRR@10 | 0.2462 | 0.3035 | 0.3173 | **0.3226** | 0.3215 | 0.3190 | 0.2942 |

**The two contrasts that matter, each a fixed cell against a fixed cell, with CIs:**

- **Shipped beats lexical-only by +0.0764, CI [+0.0393, +0.1147]** — excludes zero.
- **Shipped beats dense-only by +0.0284, CI [−0.0114, +0.0683]** — **does not exclude zero.**

~~"Hybrid fusion beats either arm alone."~~ **Withdrawn.** This run shows fusion beating the
**lexical** arm on conceptual queries. It **does not show** it beating the dense arm: +0.028 at
n=150 is not distinguishable from no difference, and asserting it would apply a looser standard to
a claim I wanted than the 0.02-with-a-CI standard applied to the claims I rejected. The previous
revision made exactly that double standard, and compared a max-over-36-cells blend against
single-arm columns that barely move — at `w = 0` and `w = 1` the fused order is one arm's order,
**invariant to `rrf_k`; invariant to depth except at depth 10**, where the exclusion set can leave
the surviving arm short of ten rows (dense-only `heading` 0.2936 at depth 10 against 0.2942 at every
depth above). *An earlier revision wrote "constant by construction"; that residue is the exclusion
set's doing, not a silenced arm's, so the zero-weight-leak fix could not remove it.*

## The span families measure something real, and what they measure is bad news

Calling their result "entirely artefactual" — as an earlier revision did — throws away a genuine
measurement. They are an **invalid instrument for arm balance** and a **valid measurement of
exact-phrase lookup**, which is a query shape a coding agent produces constantly: pasting an error
string, an identifier, or a sentence it just read. Every column below is one fixed cell at the
shipped `rrf_k` and depth.

| family | shipped MRR@10 | lexical-only | shipped hit@5 (capped) | lexical-only hit@5 (capped) |
|---|---|---|---|---|
| `verbatim` | 0.7124 | **0.9780** | 0.7733 | **0.9867** |
| `masked-50` | 0.5447 | **0.9131** | 0.6400 | **0.9600** |
| `masked-100` | 0.3606 | **0.6851** | 0.5067 | **0.7733** |
| `heading` | **0.3226** | 0.2462 | **0.3867** | 0.2733 |

**hit@5 is quoted after the shipped `max_chunks_per_file = 2` cap**, which is the preregistration's
own definition — *what a caller at the shipped `limit_per_kb` would actually see*. For the span
families that is exactly caller-facing, there being no exclusion set; for `heading` it is not, for
the reason given in the previous section. Pre-cap, the same four are 0.8267 / 0.6933 / 0.5267 /
0.4267 against 0.9933 / 0.9733 / 0.7733 / 0.3667.

Dense-only, for completeness: `verbatim` 0.5359, `masked-50` 0.3056, `masked-100` 0.1263,
`heading` 0.2942.

**On `verbatim` — the cleanest of the three — the shipped hybrid discards 27% of the lexical arm's
MRR, and the caller-facing hit@5 falls from 0.9867 to 0.7733.** **More than one 15-word span in
five does not have its own source chunk in the five results a caller receives** under shipped
fusion; under the lexical arm alone, essentially every one does. The lexical arm puts the answer at rank 1 and fusion drags it down by mixing in dense votes
for chunks that merely resemble it. On conceptual queries the ordering reverses and the blend is
best. **The two query classes want opposite weights, and unweighted RRF is a compromise that is
near-optimal for one and badly suboptimal for the other.**

*Quote 27%, not the 27–47% range an earlier revision used: the 47% end is `masked-100`, which the
preregistration itself calls "text no human would type".*

**Scope, because an earlier revision overreached here.** What was measured is **multi-word
contiguous prose spans with a single known source chunk**. An error string or a bare identifier is
**not** in this query set — an identifier is one rare token, an error string is short and
punctuation-heavy, and either may occur in many files, where *which* occurrence answers the question
is exactly the judgement the dense arm might supply and this oracle cannot see. Those remain a
**hypothesis** about where the finding extends, not part of it.

**This also corrects a misattribution in the previous revision**, which explained `verbatim`'s 0.712
by "sibling chunks are near-duplicates". They are not what held it down: lexical-only scores 0.978
on the identical queries. **The dense arm's votes did.**

Nothing moves on this evidence — a global weight cannot serve both classes, which is the point — but
it is the strongest argument in this run for the thing §16 item 3 is actually about, and it says the
lever is **query-dependent weighting**, not a better constant.

**This is the one parameter for which "opposite optima" is established.** `heading` wants dense
weighted at least as heavily as lexical (0.2462 at `w = 0`); the span families want the lexical arm
nearly unmixed (0.9780 at `w = 0`). No other parameter in this grid shows that shape — see the
`rrf_k` section, where an earlier revision borrowed it and was refuted by its own table.

## `rrf_k` is not flat — it was flat on one family

The previous revision called `rrf_k` flat from a single slice of a single family. Across families at
`w = 0.5, depth = 50`:

| `rrf_k` | 10 | 20 | 40 | **60** | 100 | 200 |
|---|---|---|---|---|---|---|
| `verbatim` | 0.7475 | 0.7264 | 0.7134 | **0.7124** | 0.7061 | 0.7055 |
| `masked-50` | **0.6469** | 0.5809 | 0.5502 | **0.5447** | 0.5444 | 0.5410 |
| `masked-100` | **0.4475** | 0.3883 | 0.3640 | **0.3606** | 0.3599 | 0.3562 |
| `heading` | 0.3268 | 0.3227 | 0.3228 | **0.3226** | 0.3224 | 0.3224 |

**Flat on `heading` (spread 0.004) and emphatically not flat on exact-phrase queries** — `masked-50`
gains **+0.102 at `rrf_k = 10` against the shipped 60**, 19% relative, and spans 0.106 across the
whole `k` grid. The mechanism is plain: a small `k` makes rank 1 dominate (1/11 against 1/61), so an
arm that is confidently right wins; where neither arm is confidently right, `k` changes little.

**That is a real result about a real query class** — an agent pasting back a sentence it just read
is issuing exactly this shape. **Identifiers and error strings are a neighbouring hypothesis rather
than part of the measurement**, for the reasons given under Scope above; this corpus's own
FINDINGS open question 8 and AWS's lexical steer concern those, and are what a code corpus would
have to test. What the span families cannot measure is arm *balance* for queries that are not
substrings of their answers — invalid for that, valid for this.

**What this is *not* is an "opposite optima" result, and an earlier revision claimed it was.**
~~"The two families pull `rrf_k` in different directions … evidence that the right `rrf_k` is
query-dependent."~~ **Withdrawn, refuted by the table printed directly above it.** "Different
directions" needs a family that a small `k` *hurts*, and there is none: **every** family's row
maximum is at `k = 10`, `heading` included (0.3268 against the shipped 0.3226). The same holds for
depth — (60, 10, 0.5) beats shipped on **all four** families and is one of the 48 cells passing the
as-written bar, with a worst-family delta of **+0.0043**.

**The honest statement is weaker and cleaner: at the shipped weight, smaller `k` and smaller depth
are weakly dominant everywhere.** The gains are large only where one arm is confidently right — the
span families — and about **+0.004** on the valid family, which is under the bar. **So nothing
moves**, and the reason is *"below the bar on the valid family"*, not *"confined to families that
cannot support a global change"*, which an earlier revision said and which the +0.0042 refutes.
The opposite-optima shape **is** correctly established for the arm weight (0.2462 against 0.9780 at
`w = 0`) and must not be borrowed for `k`.

`fusion_depth` is flat-to-slightly-negative **on the shipped slice** (`w = 0.5, k = 60`): heading
**0.3269 at depth 10 → 0.3195 at 400**. Depth's latency cost is **not measured here** and should not
be asserted: `vec0` brute-forces the whole table whatever `k` is, so what depth actually buys is
fusion-loop and chunk-fetch work.

## Threats

- **The conclusion rests on `heading` alone**, n=150, one prose corpus, one embedding model. The
  600 is not the n and must not be quoted as one.
- **`heading` is shaped by two filtering choices, and only one of them is sensitivity-tested.**
  The **holding chunk** is excluded from the ranking for **every one of the 150** queries — 150 of
  the 175 exclusions, and where the +0.055 came from. It is **not** varied anywhere here; its
  justification is that it contains the query verbatim and is non-truth by the oracle's own
  definition. The **same-title heading chunks** are the second, touching **14 of 150**, and that is
  the choice the sensitivity table varies — the three completions agree. So the choice the
  conclusion actually leans on is the untested one, and "14 of 150" sizes the other.
- **22 of 150 `heading` queries have zero lexical overlap with truth** — 23 against chunk text
  alone, 22 once the path is counted, and the path is what the arm indexes — so they are dense-only by
  construction, which pulls the weight optimum toward dense.
- **Post-selection inference.** The headline CI is on the grid *maximum*: a winner's-curse interval,
  conservative for retaining a null and **not** an estimate of that cell's true effect.
- **The pooled bootstrap treats 600 queries as independent, and 450 are not.** `verbatim`,
  `masked-50` and `masked-100` are three views of the same 150 spans, so their per-query
  differences are correlated and the pooled intervals are **narrower than warranted**. The count of
  48 survives it — threshold 1 is a point estimate, and the narrowest lower bound among the passing
  cells is far enough from zero that a √3 inflation would not close it — but the pooled intervals
  should be read as optimistic. `heading`'s intervals, which carry the conclusion, are unaffected:
  its 150 queries are one per section.
- **Resolution.** The CI half-width is ~0.016, so "the defaults survive" means *no cell was shown
  better at roughly ±0.016*, not *no better cell exists*.
- **Scale.** 2,720 chunks is **an order of magnitude short of the ~22,800** §16 item 1 poses the
  question at, and 1.2 orders above the 187-record benchmark — not the "two orders" the
  preregistration claims. No public prose tree reaches 22,800; a code corpus is item 3's.
- **`heading` is short** (4–90 characters), shorter than a real question, and "section" means up to
  the next heading of any level 2–4 rather than the subtree.
- **No claim about source code follows.**

## What this changes

1. **§16 item 1 closes positive — on the valid family, at 2,720 chunks**, with the as-written-bar
   result recorded beside it so the closure is not read as "the grid found nothing".
2. **§16 item 3 stays open**, and now carries a method it must not reuse: a known-item oracle built
   by lifting text out of the corpus hands the lexical arm the answer.
3. **Arm weighting is not built.** The optimum sits at 0.5–0.6 and no weight clears the bar.
4. **`rrf_k` and `fusion_depth`: "flat" is withdrawn, and nothing replaces it as a reason to move.**
   Smaller values are **weakly dominant on every family** — no family is hurt — but the gain on the
   valid family is ~+0.004, under the bar; it is large only on exact-phrase queries, whose
   representativeness for real agent queries is unestablished. **Nothing moves, because it is below
   the bar on the valid family — not because it is confined to families that cannot support a global
   change**, which the +0.004 refutes. Opposite optima is established for the **arm weight alone**
   (item 3).

## The lesson worth more than the result

Two, and the second is the one that generalises.

**A known-item oracle built by lifting text out of the corpus cannot measure the balance between a
lexical and a dense arm**, because it hands the lexical arm the answer. Obvious stated plainly, not
obvious while writing it: the masking dial *felt* like it removed lexical signal and removed only its
rare-term component.

**And preregistration protects the threshold, not the quantity.** The 0.02 was fixed in advance and
never moved. What moved — after the data — was *what it was 0.02 of*, from pooled to one family, and
that change is the entire difference between 48 passing cells and none. The corpus's standing rule
is *name the quantity before quoting a number about it*; a preregistration has to name it too, and
this one named the wrong one. **Preregister the quantity, and preregister what makes a family
admissible, before the families exist.**
