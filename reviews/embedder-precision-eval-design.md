# Review — embedder-precision eval design

**Status of this review: SELF-CRITIQUE, not independent.** Phase 2 of the brief asked for the
dataset and metric definitions to be handed to the `memory-reviewer` subagent before spending
compute. **No subagent-spawning tool is exposed in this session**, so `memory-reviewer` could not
be invoked. Rather than skip the phase, I wrote an adversarial critique against my own design and
recorded accept/reject with reasons. This is strictly weaker than an independent review — a
self-critique cannot find the blind spots that produced the design. **The parent should treat an
independent review of this dataset as still outstanding**, and should weight the "threats to
validity" section of the report accordingly.

Reviewed artefacts: `experiments/embedder-precision/dataset.json` (187 memories, 64 queries),
`dataset_src/*.py`, `leakage_audit.py` output, and the metric definitions in the `sweep.py`
docstring.

---

## Attack 1 — The near-miss category is answerable by topic, not by identifier. **ACCEPTED, and fixed.**

This is the most serious defect and it goes to the heart of the experiment.

In every category-1 pair, the two twins differ in *what they say* as well as *which identifier
they name*. `c1-widgetv1` is about serialisation truncation; `c1-widgetv2` is about a constructor
`KeyError`. The query "constructing WidgetV2 from our old dict payloads" contains "constructing"
and "dict" — so a model that cannot distinguish `WidgetV1` from `WidgetV2` **at all** can still
rank correctly on topic alone. A low displacement rate would then be reported as evidence that
embedders handle near-miss identifiers fine, when it is evidence of nothing of the sort.

This is exactly the failure mode the brief warned about: a conclusion that is an artefact of
dataset construction.

**Rejected fix:** making the twins topically identical. That would be cleaner as an experiment but
would stop being tribal knowledge — two real memories about `WidgetV1` and `WidgetV2` genuinely do
say different things. Optimising the dataset for experimental purity would make it unrepresentative
of the corpus we actually intend to build, and the sweep's headline numbers are supposed to predict
production behaviour.

**Accepted fix:** keep the realistic pairs for the sweep, and add a separate isolating diagnostic,
`twin_duel.py`, which removes the confound three ways: restrict the contest to the twin pair only
(so topical ranking against 185 distractors cannot help), and probe with (a) the real query,
(b) the discriminating token **alone**, (c) the token in a topic-free carrier sentence. Probe (b) is
the decisive one: with no topical signal whatsoever, a win rate near 0.5 means the model is blind to
the identifier. The report must lead with the duel result when interpreting the sweep's displacement
numbers, not present the sweep number on its own.

## Attack 2 — Category 1 hands BM25 the answer, so config 5 is set up to look good. **PARTLY ACCEPTED.**

Every near-miss query contains the discriminating token verbatim. The leakage audit confirms the
consequence: mean containment against gold is 0.559 versus 0.348 against the hard negative, a
margin of 0.211, with only 3 of 28 queries having a non-positive margin. Lexical retrieval therefore
has a genuine, measurable edge on this category before any model runs.

Is that unfair? Partly not: it is *realistic*. A user working on `WidgetV2` types "WidgetV2", so the
production distribution really does put the discriminating token in the query. Testing the case
where it is absent would test a different and rarer situation.

But it does mean two things must be said plainly in the report, and they will be:
1. Category 1 measures "does the pipeline preserve BM25's correct signal", not "can the embedder
   resolve identifiers". The duel measures the latter.
2. Any advantage config 5 (the `tokens` column) shows is an advantage *on top of* a BM25 arm that
   already sees the token. The interesting question for config 5 is therefore whether it adds
   anything over plain BM25 at all — and if it does not, that is a clean negative result for the
   parent's proposal, which is a legitimate outcome.

**Rejected:** adding token-free near-miss queries to balance this. It would test an unrealistic
distribution, and with 28 pairs already the category is well-powered for its actual purpose.

## Attack 3 — Error-string queries have containment 1.000. The category is trivial. **ACCEPTED as intended, with a caveat added.**

Median containment of the query in the gold memory is exactly 1.000 for category 3, i.e. every
query token appears in the gold. This category cannot discriminate between good and bad retrievers
on the lexical side; BM25 will near-perfectly solve it.

That is the point — category 3 exists to demonstrate what BM25 is *for* and to catch a
dense-only configuration silently regressing on exact strings. But it inflates the ALL-row
aggregate for every configuration containing a BM25 arm.

**Accepted mitigation:** the report must not lead with the ALL row. Per-category is the primary
table, and the ALL row is explicitly flagged as containing a category that is near-saturated by
construction. Two of the ten error-string queries were also given cross-category hard negatives
(`q-c3-03` → `c2-cert-chain`, `q-c3-06` → `c1-ver-2-3-1`) where a topically-correct-but-wrong-record
memory competes; those are the only informative ones in the category.

## Attack 4 — Over-length traps may be defeated by the gist, not by the content. **ACCEPTED, already designed against, and now verified.**

If the load-bearing detail appeared in the gist, embedding `gist + content` would find it within the
first 512 tokens and the truncation trap would never fire. The gists for category 5 were written
deliberately to describe the memory's *shape* ("long write-up of the query-planner investigation")
without containing the punchline.

The audit corroborates this: category 5 has the lowest Jaccard against gold of any category on the
full text (0.032) while having high containment (0.683) — consistent with the query's tokens
appearing somewhere in a long document rather than being concentrated in the gist.

**Added:** the sweep takes an `--embed-mode` flag (`gist_content` / `gist_only` / `content_only`) so
the truncation question (brief's verdict item (e)) is answered by measurement rather than by
inference from the 512-token spec. Running `gist_only` and comparing category-5 recall to
`gist_content` is the actual test.

## Attack 5 — precision@5 is capped at 0.200 and will be misread. **ACCEPTED.**

Every query has exactly one gold, so precision@5 cannot exceed 1/5 and is just recall@5 divided by
5. It carries no information beyond recall@5. It is reported because the brief asked for it, with
the ceiling stated inline in both the code and the report so nobody reads 0.19 as a poor result.

## Attack 6 — Displacement measured over the full ranking is not what the user experiences. **ACCEPTED, both are now reported.**

Displacement over the full ranking counts a query where gold is at rank 40 and the hard negative at
39. Under D12 the agent sees five gists, so that query is a non-event operationally. But the
full-ranking version is the better measure of the *ranker's ordering preference*, which is the
scientific question, and it is not confounded with recall.

Both are reported: `hnd` (full ranking) and `hnd_top5` (hard negative in the top 5 *and* above the
gold). The second is the operational number.

## Attack 7 — Polarity queries may be unanswerable, making the category pure noise. **ACCEPTED as a genuine limitation; kept deliberately.**

The leakage audit shows the polarity category has a gold-versus-hard-negative containment margin of
only **0.038**, with **5 of 10** queries having a non-positive margin. Lexical retrieval genuinely
cannot separate a memory from its own later correction — they share nearly all vocabulary.

Worse, some of these queries may be *genuinely* ambiguous: `q-c4-01` says "We're on 4.3", and only
the memory content states the fix landed in 4.2, so answering requires relating 4.3 ≥ 4.2. No
first-stage retriever does arithmetic. Expect all configurations to do badly here.

**Kept, because a floor result is still a result**: if every configuration is near chance on
polarity, that is direct evidence for FINDINGS Open question 5 (residual staleness under D11) — it
says retrieval cannot be relied on to prefer current truth over superseded truth, and supersession
must be handled structurally (a `superseded_by` pointer that suppresses the retired record) rather
than hoped for from ranking. That is an actionable design conclusion, not a wasted category. Five of
the ten queries were deliberately written in the reverse direction (the query pins an *old* version,
so the *old* memory is gold) specifically so that a configuration cannot score well by blanket-
preferring whichever memory sounds newer.

## Attack 8 — 187 memories is far smaller than a real store, so all numbers are optimistic. **ACCEPTED, cannot be fixed here.**

Retrieval difficulty grows with corpus size. A real Zikaron store after months on a project might
hold thousands of memories, and top-5 precision will be materially worse there. Every absolute
number in this report is therefore an upper bound.

What survives the scale objection is the *relative ordering* of configurations and the duel result,
which is corpus-size-independent because it is a two-way contest. The report leads with relative
comparisons and marks absolute values as optimistic. Distractors were also written to crowd the
traps' token space on purpose (`distractors_b.py` contains other version strings, other env vars,
other dotted paths, other migration numbers) rather than being off-topic filler, which is the
cheapest available partial defence.

## Attack 9 — Self-authored queries encode the author's knowledge of the answer. **ACCEPTED, unfixable, reported.**

I wrote both the memories and the queries, so the queries inevitably use vocabulary I chose while
holding the target memory in mind. This inflates every number and no amount of care removes it.
Mitigation applied: queries were written as session-opening user messages ("I'm adding a cache
warmer path for WidgetV1 today") rather than as paraphrases of the memory, and the paraphrase-only
category was written by deliberately avoiding the memory's distinctive vocabulary — the audit shows
that worked (Jaccard 0.065, containment 0.248, the lowest of any category). This is listed as the
single largest threat to validity.

## Attack 10 — No per-configuration tuning is claimed, but the tokens column has a weight of 3.0. **ACCEPTED as a stated constant, not a tuned one.**

Config 5 weights the `tokens` FTS column at 3.0 against 1.0 for gist and content. That number was
chosen once, a priori, as "clearly higher", and was not swept. If it had been swept, config 5 would
be tuned while nothing else was, which is exactly the flattery the brief prohibits. The report will
state the weight and note that config 5's result is therefore a result *for that weight*, and that a
negative result does not fully exclude some other weight working better.

RRF `k=60` and fusion depth 50 are likewise fixed for every configuration.

## Attack 11 — The incumbent has two plausible definitions and picking one biases the baseline. **ACCEPTED, both are run.**

`~/Memory` passes raw text with no prefix; BGE's own card recommends a query prefix. Calling either
one "the incumbent" and comparing everything to it would bias the comparison. Both are run
(`4_rrf_small_noprefix` and `4p_rrf_small_prefix`), the prefix effect is isolated by configs 2 vs 3
in the dense-only setting, and configs 5–7 all use the prefixed variant so the lexical-side and
scale-side changes are measured against the same dense convention.

## Attack 12 — fastembed silently serves a *quantized* bge-small. **ACCEPTED; material and must be reported.**

fastembed 0.8.0 resolves `BAAI/bge-small-en-v1.5` to the cache directory
`models--qdrant--bge-small-en-v1.5-onnx-**q**` — an int8-quantized ONNX export — whereas
`BAAI/bge-large-en-v1.5` resolves to `models--qdrant--bge-large-en-v1.5-onnx`, unquantized. So
"bge-small versus bge-large" is not a clean scale-only control: it confounds parameter count with
quantization. This was not anticipated by the design and was found only by inspecting the cache.

It cannot be removed without hand-exporting an fp32 bge-small, which is out of scope here. It is
reported prominently as a confound on the config-6 comparison, and it *understates* nothing
important: if quantized-small already matches unquantized-large, the "scale helps" hypothesis is in
even more trouble than the raw numbers suggest. It matters more for the *latency* comparison, where
small gets an unearned advantage.

---

## Points considered and rejected

- **"Add a third twin to each near-miss pair."** Rejected: 28 pairs already give adequate power for
  a rate statistic, and three-way sets would make the gold/hard-negative labelling ambiguous.
- **"Use a real repository's history instead of synthetic memories."** Rejected as out of scope for
  this brief and infeasible in one session, but it is the correct next step and is named as such in
  the report's threats section.
- **"Report nDCG@5."** Rejected: with exactly one gold per query, nDCG@5 is a monotone function of
  the gold's rank and adds nothing over MRR@10 plus recall@5.
- **"Drop the polarity category since no first-stage retriever can do it."** Rejected — see Attack 7;
  a floor result is a design finding.

## Net verdict on the design

Proceed to the sweep, with two mandatory changes now made: the `twin_duel.py` isolating diagnostic
(Attack 1) and the `--embed-mode` truncation test (Attack 4). Report per-category before ALL,
report both displacement variants, and lead the interpretation with the duel rather than the sweep
displacement rate. Carry Attacks 8, 9 and 12 into threats-to-validity as first-class caveats, and
carry the absence of an independent review as a caveat of its own.
