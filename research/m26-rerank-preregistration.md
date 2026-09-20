# M26 cross-encoder reranker — preregistration

**Written 2026-09-20, before any query was scored, before a corpus was built, and before a single
relevance label existed.** Its purpose is to fix what the numbers will be numbers *of*, so that a
result cannot be rescued by choosing the quantity after seeing the data.

**That is this document's whole reason for existing, and it is written against a specific failure
this project has already committed.** M25 preregistered a threshold of 0.02 and honoured it
exactly; what moved was *what the 0.02 was 0.02 of*, and that alone is the difference between 48
cells clearing the bar and none clearing it. The threshold was never the weak part. So this
document fixes the metrics, the query sets, what makes a query admissible, the exclusions, and the
decision rule — each before the thing it governs exists.

---

## The question, which is two questions

A knowledge search produces two orderings, and a cross-encoder can serve both. They are graded
separately because they can move in opposite directions.

| ordering | decided today by | what is known about it |
|---|---|---|
| **within a corpus** — which chunk of this corpus answers | full hybrid RRF over both arms | M25 measured hit@5 on the one admissible family at **0.3867** |
| **across corpora** — which corpus's group is shown first | the **best dense cosine** in the group | §7.2 calls it *"approximate"* and accepts in writing that *"an agent reading only the first group may miss a better result in the third"* |

**Why one mechanism serves both, and why the second is nearly free.** BM25 cannot cross a corpus
boundary — measured on two 200-document corpora, the one containing a hundred matches scored its
best hit at zero, so pooling BM25 buries the most on-topic corpus. Cosine can cross it, because it
is a function of a query and one passage and nothing corpus-relative. **A cross-encoder score has
that same property and is a far stronger function.** Once each corpus's candidates have been
rescored for the within-corpus ordering, every returned chunk already carries a cross-corpus
comparable score, so using the best of them as the group key costs **no additional inference** —
it is a different line, not a second model.

**Both are measured. Neither is assumed.** M19 spike C measured cosine beating fused-contribution
ordering 0.74 to 0.57 on mechanical identifier queries, so cosine is the incumbent on evidence and
has to be beaten rather than displaced by argument.

## What is being compared

| arm | within-corpus ranking | group key |
|---|---|---|
| **shipped** | RRF, then the per-file cap, then the output limit | best cosine |
| **reranked** | RRF, top `N` rescored by a cross-encoder, then the same cap and limit | best cosine |
| **reranked + routed** | as above | best cross-encoder score |

The third arm exists so that a gain in group ordering cannot be credited to the within-corpus
change or the reverse. Everything else is held identical: same corpora, same commits, same chunks,
same `rrf_k`, `fusion_depth`, `knowledge_max_chunks_per_file` and `limit_per_kb`. No embedder
change, no query rewriting, no chunking change.

## Fixed parameters

| | value | why it is fixed here |
|---|---|---|
| corpus 1 | `cockroachdb/cockroach` `docs/RFCS` at `13cb3eb27674b4a981e5c526d04c2387e81efd0b` | M25's corpus at M25's commit, so the within-corpus baseline is one already measured |
| corpus 2 | `pingcap/tidb` `docs/design` | 116 files, Apache-2.0 |
| corpus 3 | `MaterializeInc/materialize` `doc/developer/design` | 142 files |
| build | `experiments/m25_build_sweep_corpus.py`, `chunk_max_tokens` 450 | the shipped chunker; corpus 1 measured at 2,700 chunks over 188 markdown files |
| reranker | `Xenova/ms-marco-MiniLM-L-6-v2` | the cheaper candidate and within noise of the other; a model comparison is not this milestone |
| candidates rescored, `N` | `4 × limit_per_kb` = 20, **per corpus** | fixed in advance so it cannot be tuned to the result |
| `limit_per_kb` | 5 | shipped default |
| `knowledge_max_chunks_per_file` | 2 | shipped default |
| bootstrap | paired, 10,000 resamples, 95% CI | M25's procedure |
| seed | 20260920 | fixed now |

**The three corpora are all distributed-SQL design documents, deliberately.** Overlapping subject
matter is the hard case for routing and the realistic one — nobody registers three unrelated
corpora, and a router that only works on disjoint topics has not been tested. It also means a
question about MVCC may be legitimately answerable from more than one corpus, which the labels
below handle and a "which corpus is correct" oracle could not.

**The reranker's input is `path + "\n" + chunk text`, sliced to 4,096 characters before
tokenization.** Stated because it is a choice: the path is already what the dense arm embeds, and
the slice is a cost guard — a chunk's stored text is *not* bounded by the chunking budget, since a
single line longer than the budget is stored whole, and tokenizing an unbounded one costs seconds.
The model's own tokenizer makes the final cut at its 512-token window, truncating the longer member
of the pair, which is always the document.

---

## The query sets, and why there are two

**Neither set alone can answer the question, and the reason is a straight trade between realism and
statistical power.**

### Set A — real human questions (n = 18)

`research/cockroachdb-architecture-questions.md`: questions asked by real people on
`forum.cockroachlabs.com`, the archived `cockroach-db` mailing list, GitHub Discussions and Hacker
News, each verified against the live page, and gathered **without filtering on whether a design
document answers them**, which would have rigged the set.

This is the set whose shape is not in dispute. It is also **too small to support a significance
claim about a small effect**, stated now rather than discovered later. Set A's job is to check that
Set B is not an artifact of how Set B was made.

It is also the set that makes routing meaningful: every Set A question is about CockroachDB, so a
router that cannot prefer corpus 1 over two corpora of adjacent prose is failing a case a user
would notice immediately.

### Set B — generated decision questions (target n = 60)

Model-generated questions, each written from one randomly chosen chunk, in the vocabulary an agent
would use — *"how does a lease transfer interact with a closed timestamp"*, not *"Range leases"*.
The generator sees the chunk's prose and **never its heading or its file path**. Questions are
generated from all three corpora in proportion to their chunk counts.

**Generation is only a way to obtain queries the corpora can answer. The source chunk is not
truth.** Truth comes from the relevance labels below, exactly as for Set A. A source chunk is
frequently not the best answer available, and treating it as truth is the known-item oracle M25
measured and this project rejected.

**Admissibility, fixed before the questions exist.** A generated question is admitted only if its
term overlap with its source chunk is **below 0.5**, where overlap is the share of the question's
terms appearing in the chunk, tokenized **exactly as the lexical arm tokenizes** — `unicode61`,
runs of `isalnum`. M25 measured its own families at 0.9975–1.0000 overlap and found out only
afterwards, because its first overlap instrument used a different tokenizer and returned a column
identical to its neighbour to four decimals. The rule keeps Set B from being known-item retrieval
wearing a question mark; the threshold is named now so it cannot be relaxed to reach a target n.

Rejected questions are counted and reported. If fewer than 40 survive, the run proceeds with what
survived and says so; the filter is not loosened.

---

## Relevance labels

For each question, the judged universe is **the top 20 before the per-file cap from each of the
three corpora** — 60 passages, the complete set either arm could return from anywhere.

Each `(question, passage)` pair is rated by a **separate opus session with no knowledge base**,
shown the question and the passage text and nothing else:

| label | meaning | gain |
|---|---|---|
| 2 | answers the question | 3 |
| 1 | related to the question but does not answer it | 1 |
| 0 | does not bear on the question | 0 |

**The grader never sees the rank, never sees which corpus the passage came from, never sees which
arm ranked it, and never sees the other passages' labels.** Passages are presented in a randomized
order per question under the fixed seed. Hiding the corpus matters more here than hiding the rank:
a grader told a passage came from the TiDB corpus while answering a CockroachDB question would be
labelling provenance rather than relevance, and that is precisely the judgement the routing metric
is supposed to make independently.

**Why contamination does not bite here, where it killed the end-to-end trial.** That trial used the
model's own pretrained recall of CockroachDB as the control arm, so a memorized codebase destroyed
the comparison. This grader is asked whether a passage in front of it answers a question in front
of it. Knowing the systems makes it a *better* judge of that, not a confounded one, and it never
sees a ranking.

**Cost, stated so it is a choice:** (18 + 60) questions × 60 passages ≈ 4,700 judgments, batched.

### Grader reliability, measured rather than assumed

A **20% random sample of questions is relabelled in an independent second pass**, and agreement is
reported as exact agreement and as Krippendorff's α on the ordinal scale. **An instrument that
cannot agree with itself flattens every comparison made with it**, and a null from a noisy grader
is indistinguishable from a null from an ineffective reranker. The α is reported beside the
headline figures, never after them.

**A hand-checked sample of 15 labels** is read by the author against the passages and disagreements
reported. The grader and this session are the same model family, so a misconception they share is
invisible to both — the same independence loss the review loop carries, with a shared corpus on top.

---

## Metrics

### Within a corpus

**nDCG@5 over the post-cap results of the corpus the question was drawn from** (Set B) or of corpus
1 (Set A), per query, averaged over queries.

- **Post-cap**, because that is what a caller receives. M25 capped a filtered ranking once and so
  reported a number in the direction that flatters; the correction is preregistered here rather
  than left to be rediscovered.
- **Ideal DCG is computed over that corpus's labelled pool, uncapped.** Both arms are depressed
  identically by the cap, so the comparison is unaffected while the absolute level is understated.
  Stated so nobody reads a low absolute nDCG as a failure of either arm.
- **Gains are `2^label − 1`** = 0, 1, 3.

### Across corpora

**First-group hit rate**: the share of questions whose first-ordered group contains at least one
label-2 passage among the results it actually returns.

**Group MRR**: the reciprocal rank of the first group that does, averaged over questions.

Both are derived from the same labels, so routing needs no second oracle and no "which corpus is
correct" judgement — which is what lets a question legitimately answerable from two corpora count
as correct under either.

**Reported alongside, and explicitly not gating:** hit@5 within a corpus, mean reciprocal rank of
the first label-2 passage, the full per-query delta distribution, and the share of label-2 passages
found at each fused-pool depth.

---

## Decision rule — fixed before any number exists

**The within-corpus reranker ships** — the config key is added, defaulting off, documented — only
if all three hold:

1. **Set B: nDCG@5 improves by ≥ 0.05 absolute, with a 95% paired-bootstrap CI excluding zero.**
   0.05 because the cost is *visible*: a model load and roughly a second of compute per corpus per
   search. Something that costs that must buy something a user could notice, not something a
   statistic can detect. Roughly, +0.05 mean nDCG@5 is what you get when about one query in five
   has a clearly-answering passage lifted from the bottom of the five to the top.
2. **Set A agrees in sign**, with its own CI reported. A point estimate pointing the other way on
   real human questions **blocks the ship** whatever Set B says, because Set B's realism is the
   assumption Set A exists to test. Set A is not required to reach significance; it is required not
   to contradict.
3. **No regression on known-item lookup.** M25's `verbatim` family — multi-word contiguous spans
   with a single known source — must not lose more than **0.01 MRR@10**. A reranker that improves
   conceptual questions by wrecking exact-phrase retrieval is not an improvement, and M25 measured
   that fusion already discards 27% of the lexical arm's MRR on that family, so the headroom is
   small. This is the one remaining honest use of the mechanical families: as a **guard**, never as
   the bar.

**The cross-encoder group key ships separately, and only if it beats the incumbent on its own
terms:** first-group hit rate improves by **≥ 0.05 absolute with a CI excluding zero**, and group
MRR does not fall. **Cosine is the incumbent on measured evidence** — M19 spike C — so a tie leaves
cosine in place. The two decisions are independent: the within-corpus reranker may ship with
cosine ordering retained, and the group key may not ship alone, since it exists only as a by-product
of scores the within-corpus stage computes.

**Miss a bar and that part does not ship.** `design/knowledge-index.md` §16 gains the negative
result and the note says so. **Naming that as an acceptable outcome now is deliberate** — M25
produced four artefacts, closed an open question and changed no product code, and the failure mode
to avoid is not a negative result but a bar quietly re-scoped to avoid one.

---

## Exclusions, fixed in advance

- **A question with no label-2 passage anywhere in its 60 cannot distinguish the arms** — there is
  nothing for either to rank first. **Counted, reported, and excluded**, with the count beside every
  figure. Including them adds identical zeros to both arms and shrinks the apparent effect toward
  nothing.
- **A question whose pool is entirely label-2** is excluded for the mirror reason.
- **For the routing metrics only, a question whose label-2 passages all sit in one corpus is kept**
  — that is the ordinary case and the one routing exists for. A question with label-2 passages in
  all three corpora cannot distinguish orderings and is excluded from the routing metrics alone,
  while remaining in the within-corpus metric.
- **No exclusion is decided after seeing an arm's score.** All of the above are functions of the
  labels, which are produced before either ranking is scored.

M25's `heading` family needed two exclusions nobody anticipated — the chunk physically containing
the heading line, and the heading chunks of same-titled sections elsewhere — and applying them
moved that family by +0.055. Neither applies here, because neither query set lifts its text out of
a corpus. Stated so a reader does not assume an omission.

---

## Threats named in advance

- **Three corpora of technical design prose, in English.** Nothing here generalizes to source code,
  and §16 item 3 — which asks about code — stays open whatever this run says.
- **The grader and this session are one model family.** A shared misconception is invisible. The
  hand-checked sample bounds it weakly and does not remove it.
- **Set B's questions are written by a model reading the passage.** The overlap filter removes the
  lexical shortcut; it does not prove the questions are shaped like a working agent's. That is
  exactly why Set A gates the sign.
- **Set A is entirely about CockroachDB**, so its routing result measures "prefer the right corpus
  among adjacent ones" and says nothing about a corpus set with no clear owner per question. Set B,
  drawn from all three, covers that case and is the one with power.
- **`N = 20` may be too shallow.** If the answer frequently sits at fused rank 21–50, the reranker
  never sees it and this measures a ceiling rather than the mechanism. The depth distribution of
  label-2 passages is reported so the ceiling is visible; `N` is not changed mid-run.
- **Latency is reported, and is not a bar.** The build-plan's `≤ 250 ms at p50 for a five-corpus
  search` was written with no measurement behind it and is withdrawn. Cost is reported with the
  machine's load average beside it, and the property that replaces it is **boundedness**: work per
  search does not grow without limit in the number of corpora named or in the size of a chunk.

---

## Harness

`experiments/m26_rerank_eval.py`, reusing `experiments/m25_fusion_sweep.py`'s query builder, its
per-file cap mirror, its paired bootstrap and its lexical-arm tokenizer for the overlap filter, and
`spikes/spike_group_ordering.py`'s group-assembly shape for the routing arms.
**`experiments/m25_verify_note_figures.py`'s `SOURCES` is extended to this note**, or it silently
covers only M25's figures.

**The instrument is checked before it is used**, because M25 needed seven corrections and every one
had a symptom already visible in its own output: a column identical to its neighbour to four
decimals, a "constant" arm that was not constant, a field whose name described a population it had
not counted. Concretely, before any headline figure:

- the two within-corpus arms differ on at least one query and agree on at least one;
- the overlap column distinguishes a known-verbatim query from a known-paraphrase one;
- the label file's question count matches the query set's, and its passage count matches 60 per
  question;
- a deliberately reversed ranking scores **worse** on every metric, and a deliberately perfect one
  scores better — both directions, since a metric that cannot fall is not measuring;
- the three group keys produce at least two distinct orderings across the query set, or the routing
  comparison is vacuous and says so rather than reporting a tie.
