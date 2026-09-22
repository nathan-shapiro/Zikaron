# Where the answer is lost, and what recovers it — chunking levers measured against reranking

**Run 2026-09-20 against `cockroachdb/cockroach` `docs/RFCS` at commit `13cb3eb2`** — 188 markdown
files, 4,121,360 bytes. Harnesses: `experiments/m26_headroom.py`, `experiments/m26_miss_diagnosis.py`,
`experiments/m26_chunking_levers.py`, `experiments/m26_chunking_variants.py`. Literature review that
reshaped the arms: `research/chunking-for-retrieval.md`.

**This note exists because §M26's premise did not survive measurement.** The milestone was briefed
as a cross-encoder reranker on the pull path. It is not what this corpus needs, and the evidence is
below rather than in an argument.

---

## 1. The gate that should have been run first

A reranker reorders a candidate set fusion has already chosen, so it can only help where fusion
**found** the answer and **mis-ordered** it. That premise was never measured. It is measurable
directly, and the arithmetic is a ceiling rather than an estimate: a perfect reranker over a window
of `N` puts truth at rank 1, where the per-file cap cannot evict it, so **`hit@N` before the cap is
the most any reranker at that `N` can deliver**, and today's post-cap `hit@5` is the floor.

| family | hit@1 | hit@5 | hit@10 | hit@20 | hit@50 | ever in pool |
|---|---|---|---|---|---|---|
| `heading` | 0.200 | 0.387 | 0.473 | 0.553 | 0.633 | 0.687 |
| `masked-100` | 0.193 | 0.433 | 0.660 | 0.833 | 0.940 | 0.973 |
| `masked-50` | 0.480 | 0.713 | 0.860 | 0.987 | 1.000 | 1.000 |
| `verbatim` | 0.687 | 0.873 | 0.967 | 1.000 | 1.000 | 1.000 |

Fusion **is** recall-good and precision-poor, in every family — including `masked-100`, the least
heading-like shape in the set, so the conclusion does not rest on the oracle. On `heading` the
median rank when found is **4**, while the mean is **13.7** and p90 is **44**: a long tail sitting
just outside what a caller sees.

**So the gate passes, and reranking is not refuted by it.** At `N = 20` the headroom over today's
post-cap `hit@5` is `heading` **+0.187**, `masked-100` **+0.400**, `verbatim` **+0.133**, and
`N = 20` captures 70% of what `N = 50` would at 40% of its cost. What refutes the milestone is the
next measurement.

## 2. What the misses actually are

`heading`, n = 150, shipped configuration:

| outcome | top 5 | top 20 | top 400 |
|---|---|---|---|
| answer found | 0.387 | 0.553 | 0.687 |
| **right file found, the answering section never returned** | 0.227 | 0.187 | **0.173** |
| right file never returned at all | 0.380 | 0.240 | 0.113 |
| an adjacent chunk of the right section | 0.007 | 0.020 | 0.027 |

**§M26's central claim is false on this corpus.** The brief says the reranker's target is *"a
ranking failure inside a document retrieval already found, and a cross-encoder is the standard fix
for exactly that shape."* But when the right file is found and the answering section is not, **the
answering chunk is not in the candidate pool at all** — the file is represented there by a
*different* chunk of itself. A reranker reorders what the arms returned; it cannot admit what they
did not. That class, 17–23% depending on depth, is **unreachable by reranking at any `N`**.

What reranking can reach is the narrower band where the answer sits at ranks 6–20: **16.6%**.

**And the pointer to what does work.** Where a chunk of the right file reached the top 20 without
the answer, the two are **within 1–2 chunks in 16 of 31 cases**. The answer is adjacent to
something already retrieved. That is a question about where the cuts fall.

## 3. The oracle had to change, and that is the transferable part

Every earlier measurement here scored *is the truth chunk id in the top five*. **That cannot compare
two indexes that cut the corpus differently** — their chunk ids describe different things, so the
metric is not even defined across arms.

Truth is therefore a **line range**: the body of the section a heading names, read from the file
rather than from any index, with the heading line itself excluded because it contains the query
verbatim. **A query hits when the text delivered to the caller covers ≥ 50% of those lines.**
Identical across every arm, independent of chunking, and closer to what a caller needs than any
chunk identity.

**Delivered characters are reported beside every hit rate**, because one arm buys coverage with
bytes and a comparison that ignored size would recommend it every time.

A second family, `verbatim`, is a **guard rather than a target**: exact 4-line spans lifted from the
corpus, truth being the lines they came from. A chunking change that improved concept lookup by
breaking exact-phrase lookup is not an improvement.

## 4. What the literature said before the arms were fixed

Full detail in `research/chunking-for-retrieval.md`. The four findings that changed this run:

- **Overlap is weakly evidenced and one controlled study finds it does not help** (5 corpora, 472
  queries: 0% vs 50% overlap gave near-identical recall and *worse* precision). The common
  "10–20%" advice has no benchmark behind it.
- **Structure-aware splitting beats fixed-size for corpus-level retrieval** (0.4948 vs 0.3888
  nDCG@10) — **but the same paper finds the ranking reverses for in-document retrieval**, which is
  this corpus's failure mode. So the intuitive fix was not unambiguously favoured going in.
- **Parent-document / neighbour retrieval is the thinnest-measured technique of the set** — one
  52.5% pairwise preference, barely above a coin flip, from vendor tooling.
- **Contextual retrieval** (an LLM writes a sentence of context per chunk before embedding) has the
  strongest reported numbers, 35–67% reductions in retrieval failure, **vendor-reported and
  unreplicated**. It collides with **D2**, *no extra LLM on the write path*. Its mechanism —
  telling the embedder what a passage is about when the passage does not say — suggested a version
  that needs no LLM at all: prepend the **heading breadcrumb** to what is embedded. That arm exists
  because of this finding.

Also carried, unused here: **semantic chunking has negative results** (the popular
embedding-distance method scores near-worst, below plain token splitting); **late chunking requires
an 8K-context embedder** and cannot apply to `bge-small-en-v1.5` at 512; and **optimal chunk size is
query-dependent**, with 20–40% recall@1 gaps between the best fixed size and a per-query oracle —
independently echoing M25's finding that two query classes wanted opposite fusion weights.

## 5. The arms

| arm | what changes | reindex |
|---|---|---|
| `baseline` | shipped: paragraphs packed greedily to 450 tokens, no overlap | — |
| `no_overlap` | **control**: the variants' line-greedy packing with overlap zero | yes |
| `overlap` | line-greedy packing, each chunk repeating ~25% of the previous | yes |
| `breadcrumb` | line-greedy packing; the enclosing headings prepended to **what is embedded** | yes |
| `section` | cuts fall at markdown headings first, packing only within a section | yes |
| `section_overlap` | section cuts, plus overlap inside a section too long for one chunk | yes |
| `section_overlap_crumb` | the above, plus the breadcrumb | yes |
| `neighbours` | baseline index; every delivered result widened to its adjacent chunks | **no** |
| `+stitch` | results of one file whose ranges touch or overlap merged into one | **no** |

`neighbours` and `+stitch` are query-time arms over indexes already built, which is why they carry
no reindex: the first fetches more than was ranked, the second merges what was.

**`no_overlap` is a control, not a candidate, and it earned its place.** The variants pack *lines*
where the shipped chunker packs *paragraphs*, so comparing `overlap` directly against `baseline`
would have confounded the overlap with the change of packing unit.

## 6. Results

n = 150 per family. `heading` is the target; `verbatim` is the guard.

| arm | chunks | **heading** | **verbatim** | chars (heading) |
|---|---|---|---|---|
| `baseline` | 2,720 | 0.267 | 0.640 | 5,702 |
| `no_overlap` *(control)* | 2,440 | 0.253 | 0.527 | 5,784 |
| `overlap` | 3,129 | 0.320 | 0.827 | 5,784 |
| `breadcrumb` | 2,440 | 0.320 | 0.527 | 5,785 |
| `section` | 4,007 | 0.553 | 0.773 | 4,056 |
| `section_overlap` | 4,273 | 0.567 | **0.847** | 4,220 |
| **`section_overlap_crumb`** | 4,273 | **0.593** | 0.827 | 4,174 |
| `neighbours` | 2,720 | 0.540 | 0.933 | **22,584** |

**Section-first cutting is the effect that matters.** Against the shipped baseline,
`section_overlap_crumb` takes the target from **0.267 to 0.593** and the guard from **0.640 to
0.827**, while delivering **27% fewer characters**. Both families improve and the payload shrinks;
the costs are index size (+57% chunks) and build time (366 s → 481 s), neither of which a caller
experiences.

**The control changes how overlap is read.** `no_overlap` scores *below* `baseline` on both
families, so line-greedy packing is itself slightly worse than paragraph-greedy. Overlap's real
effect is therefore **+0.067 heading and +0.300 verbatim against its own control**, not the +0.053
it appeared to gain against `baseline`. Without the control the packing regression would have been
charged to overlap.

**The breadcrumb is free and its gain is mechanistic.** It adds **no chunks** and 4 seconds of
build. Standalone it is +0.067 heading over its control. Combined with section cuts it trades
+0.027 heading for −0.020 verbatim — **inside noise at n = 150**, where the standard error on a
proportion is ≈ 0.04, so the two top arms are not separated by it. What is *not* inside noise is the
`heading` any-coverage rate, **0.793 → 0.853**: the breadcrumb reaches sections the other arm never
touches at all, which is the predicted mechanism rather than the same sections covered more fully.

**`neighbours` is disqualified by cost, not by quality.** It reaches the same neighbourhood on
`heading` (0.540) and the best `verbatim` of any arm (0.933) — but delivers **22,584 characters
against a 24,000-byte response cap**. It would sit permanently at the ceiling, dropping whole
groups.

### Stitching is a no-op here, and it corrects an earlier claim in this note's own argument

Merging results of one file whose line ranges touch or overlap was expected to reclaim the
duplicate text an overlapping chunker delivers, and to free the cap slot spent on it.

| arm | heading | verbatim | chars | with stitching |
|---|---|---|---|---|
| `baseline` | 0.267 | 0.640 | 5,702 | **identical** |
| `overlap` | 0.320 | 0.827 | 5,784 | 5,781 |
| `section` | 0.553 | 0.773 | 4,056 | 4,011 |
| `section_overlap` | 0.567 | 0.847 | 4,220 | 4,208 |

**No hit rate moves at all and delivered characters fall by at most ~1%.** The cause is the
per-file cap: it admits at most two chunks per file, and a file's two best-scoring chunks are
usually **not adjacent**, so there is almost nothing to merge. It fires on a percent or two of
queries.

**The consequence is a correction rather than a null result.** Overlap was objected to during this
milestone on the ground that it costs a caller real money — shared lines read twice, and one of a
file's two capped slots spent on text the other already delivered. **That cost is much smaller than
the objection claimed**, and not because stitching removes it: the situation seldom arises at all.
Overlap is therefore cheaper than it was given credit for, and §9 states the design consequence
with this measurement rather than with the objection.

Stitching remains defensible as **presentation** — two adjacent chunks arriving as one passage
rather than two fragments a reader must reassemble — but it is **not a retrieval lever** and is not
recommended as one on this evidence.

## 7. Instrument defects found, and how

**Every one of these had a symptom visible in the instrument's own output**, which is M25's lesson
arriving again.

1. **The first latency table was measured sequentially on a loaded machine** and was worthless: one
   configuration measured 1,229 ms and 1,647 ms in two runs. Configurations are now **interleaved**,
   one timed call each per round, with the minimum reported beside the median. Caught by the
   operator asking what else was running — a `java` process holding 4.3 of 12 cores.
2. **Delivered characters were computed from the original snippets**, so `neighbours` reported
   baseline's 5,702 while widening every result to three chunks. Its cost was unmeasured and its
   gain looked free.
3. **"The store exists" was treated as "the store is built."** An interrupted build leaves a
   database that opens cleanly and answers with whatever it committed, so a killed run would have
   contributed a short corpus as an arm. Now checked against the build's own completion stamp.
4. **The overlap arm was confounded with the packing unit** until the control was added.
5. **The stitching function was tested on six synthetic cases before use** — contained ranges,
   three-chunk chains, gaps correctly not merged, different files kept apart.

## 8. Threats to validity

- **One corpus, markdown, disciplined heading structure.** A flat or badly-headed corpus has no
  structure to cut on. The design consequence is in §9: the detector must default to today's
  behaviour, so such a corpus is unchanged rather than damaged.
- **Nothing here says anything about source code**, where the boundaries are syntactic rather than
  textual.
- **Queries are section headings and the winning arm cuts at section headings.** This is the
  honest weak point. Two things argue against it being pure oracle alignment: `verbatim` also
  improves substantially, and those queries have nothing to do with headings; and the `any`-coverage
  movement shows sections being reached that were previously never touched. **It is not settled**,
  and the check that would settle it is §10.
- **`heading` never retrieves the right file at all in 11.3% of queries** even 400 deep. No
  chunking change and no reranker touches that.

## 9. What this implies for the design

`design/knowledge-index.md` §4.3 is the section affected. The change is small because the module is
already shaped for it:

| change | where | size |
|---|---|---|
| `_Unit` gains `starts_section` | `chunking.py` | one field |
| the boundary detector sets it | `_paragraph_units` | ~5 lines, defaulting to `False` |
| flush before a unit that starts a section | `_pack`'s loop | 2 lines |
| overlap | `_Packer.flush` retains tail units rather than clearing | ~8 lines |

**Stitching is not in that list**, having been measured to change nothing (§6).

**The default path is provably unchanged**: with no detector every unit has `starts_section=False`
and `_pack` behaves exactly as today, so a non-markdown corpus gets today's chunking rather than a
regression.

**One design statement moves.** §4.3 says *"a file's chunks partition its lines contiguously, with
no gap and no overlap"*, and overlap breaks it. What that costs a caller was argued here to be
duplicate lines and a wasted cap slot, and **measured to be almost nothing** (§6) — the per-file
cap rarely admits two adjacent chunks, so the situation seldom arises. The sentence still has to be
rewritten, because it will otherwise be quoted as a guarantee that no longer holds; what does not
have to be built is a mechanism to defend it.

The snippet contract — *a snippet is byte-identical to its line range* — is **unaffected**, since
every arm here stores whole lines and none changes what a single chunk's text is.

**Existing knowledge bases need no migration.** Old chunks are valid chunks cut differently — not
mislabelled the way a changed embedder would make them — so a corpus keeps serving and picks up new
cuts on its next `refresh`. That is what makes this shippable despite touching the index.

## 10. THE RESULT IS OVERTURNED — real agent queries reverse it

**Everything above §10 is measured correctly and answers the wrong question.** The oracle is
section headings, the winning arm cuts at section headings, and the operator challenged exactly
this three times before it was tested. It is not merely that the gain fails to transfer: **it
points the opposite way.**

**Real agents do not send the user's question, and they do not send headings.** They send short
keyword queries and reformulate. Extracted from the M26 trial transcripts' own `tool_use` blocks —
**55 distinct queries over 10 questions**, 2 to 16 per question:

| the user asked | the agent searched |
|---|---|
| "How does the CockroachDB approach not deadlock? Surely retrying could…" | `deadlock detection transaction locking` |
| "Timestamp cache is critical in providing the guarantee that…" | `timestamp cache availability lease transfer low water mark` |

Scored on those queries, against citations from the trial that were **mechanically validated**
(57/57 real file, real line range):

| arm | all gold (n=53) | control-only gold (n=51) |
|---|---|---|
| **baseline (shipped)** | **0.698** | **0.412** |
| section | 0.566 | 0.353 |
| section_overlap_crumb | 0.547 | 0.333 |

**The shipped chunker wins under both gold sets.** Bias was real — the margin narrows from 13
points to 6 under chunking-independent gold — but the ordering is unchanged.

**The failure is explicable, which is what makes it worth keeping.** q03 drops 2/3 → 0/3 under
section-first cutting. The answer is one bullet under a `# Future work` heading; cutting at every
heading isolates it into a small chunk stripped of surrounding context, so both arms lose signal.
More generally: **section-first helps broad conceptual queries find a topical section, and hurts
specific queries whose answer is one line inside a short section.** That is precisely the split §4
recorded from the literature — structure-aware wins for finding the *document*, reverses for
finding the *passage* — collected that morning and then underweighted because a self-authored
oracle disagreed.

**Nothing from this milestone ships.** Not the reranker (§2: its ceiling is 16.6% and the brief's
stated target class is unreachable by it), not section-first chunking, not overlap, not the
breadcrumb, not stitching (§6: a no-op).

## 11. The methodology finding, which is worth more than the result

**Query shape was the dominant variable in every measurement made here — larger than any chunking
or ranking difference.** Three oracles were used in one day and each was wrong differently:

| oracle | what it got wrong |
|---|---|
| chunk-id + heading queries (M25, §1–2) | not comparable across differently-cut indexes, and heading-shaped |
| line-range + heading queries (§3–6) | comparable, still heading-shaped — **inverted the answer** |
| line-range + verbatim questions | real questions, wrong *form*; agents never send them |
| **line-range + the queries agents actually issued** | **the one that matched reality** |

**The correct input was recorded the whole time**, in transcripts this project had already copied
out of the harness's pruning window for a different purpose. Nobody read the `tool_use` blocks.

**The transferable rule: before choosing a query set, go read what the system's real callers
actually send.** Not the user's words, not a plausible paraphrase, not a mechanically-derived
family — the literal recorded input. Every oracle above was defensible in advance and three of
four were wrong.

**A related correction.** An earlier reading here treated "agents issue many queries per question"
as a product problem. The agents' own verdicts refute it — q05: *"The first search was wasted
effort… The second search actually landed the useful document"*; q06 concluded correctly that the
corpus does not contain founding design rationale. **A low per-query hit rate with successful
convergence is what working search looks like.** Withdrawn.

## 12. What became of the thing this was going to validate

~~**Re-run the winning arms against the 18 real human questions.** If section-first cutting holds
there, the oracle-alignment threat in §8 is answered; if it does not, this measures the
instrument.~~ **— done, and it measured the instrument.** §10 carries the result. The verbatim
questions turned out to be the *wrong form* too; the queries agents actually issue are what
settled it.

**The reranker is deprioritised rather than refuted, and the same caution now applies to it.** Its
within-corpus case is weak on this corpus — 16.6% ceiling, for a model load and ~1 s per corpus per
search, against a target class §2 shows it cannot reach. Its **cross-corpus** case is untouched by
any of this: group ordering by best cosine is `knowledge-index.md` §7.2's own stated approximation,
a cross-encoder score is cross-corpus comparable, and the scores would be in hand anyway.
`research/m26-rerank-preregistration.md` carries that design, is unreviewed, and **its query sets
are both self-authored** — by §11's rule, that is the first thing to fix if it is ever resumed.

## 13. The one thing that did come out positive

Spending a day failing to improve retrieval raised a question nobody had asked: **does the stack
beat a simple one at all?** Measured against kiro's shipped `knowledge` tool on this corpus and
these real agent queries — **ours 0.717 against 0.585** over all **53**, and **0.529 against 0.314**
over the **51** with chunking-independent gold. Same direction under both, identical at top-3 and
top-5 so not a cutoff artifact. Detail, method and caveats: `research/kiro-knowledge-head-to-head.md`.

So the retrieval stack earns its complexity against the obvious alternative. What it does not do is
respond to the levers tried here.
