# Chunking for retrieval: what is measured versus asserted

## Brief

From memory-researcher: our hybrid index (dense bge-small-en-v1.5 + BM25/FTS5, RRF fusion) uses
paragraph-greedy chunking — whole paragraphs packed into a 450-token budget, no overlap, splitting
on blank lines, language-blind — with the file path prepended at embed time only. Measured on 150
queries over 2,700 chunks of CockroachDB RFCs (M25's fusion sweep): in 17–23% of queries the right
*document* is retrieved but no chunk of the answering *section* ranks; where a right-file chunk
reaches the pool without the answer, it is usually 1–2 chunks away from the answer. Question: does
practitioner/research literature support believing cut positions are the problem, and what is
actually measured (not asserted) about overlap, structure-aware splitting, small-to-big/parent
retrieval, contextual retrieval, late chunking, semantic chunking, and chunk size — in priority
order matching the brief. Explicitly not asked to recommend a design.

## Method

Five rounds of web search plus targeted fetches of the most load-bearing sources: Anthropic's
Contextual Retrieval announcement (vendor blog, fetched directly), Jina's late-chunking paper
(arXiv:2409.04701, fetched), Chroma's "Evaluating Chunking Strategies" technical report (fetched),
a SIGIR 2026 taxonomy paper (arXiv, "Beyond Chunk-Then-Embed", fetched), a chunking/embedding
sensitivity study (arXiv:2603.06976, fetched), and AI21's query-dependent-chunk-size post (fetched).
Remaining claims are drawn from search-result synthesis without a full fetch and are flagged as
such — treat those as secondary until independently checked, since search summarization can
paraphrase past what a source actually claims (this happened once below, see the overlap section).
Queries covered: chunk overlap RAG benchmarks; Anthropic contextual retrieval numbers; semantic
chunking negative results; late chunking / Jina; optimal chunk size dense retrieval; small-to-big /
auto-merging retrieval evaluation; heading-aware markdown chunking; chunk-boundary failure
literature; Kamradt semantic chunking evaluations; query-dependent chunk size.

## 1. Overlap — folklore-heavy, with one real head-to-head that argues against it on precision

**No independent study found that shows overlap reliably improves top-k retrieval accuracy at
fixed total budget.** The most concrete number available is from Chroma's evaluation
(`trychroma.com/research/evaluating-chunking`, fetched): comparing 400-token chunks at 0% vs 50%
overlap (200-token overlap) with `RecursiveCharacterTextSplitter` and `text-embedding-3-large`,
recall was **effectively unchanged** (88.1% with overlap vs 89.5% without) while precision **fell**
(3.3% vs 3.6%) — overlap duplicates near-identical chunks in the pool, which does not add new
recoverable information but does waste result slots on redundant text. Chroma's own framing: "chunk
overlap does not matter a lot in many cases, as retrieving more chunks sharing similar useful
information does not necessarily increase the total amount of retrieved useful information." This
is a genuine, if small, controlled experiment (5 corpora, 472 synthetic queries, GPT-4-Turbo
generated) and its result is *negative* for overlap on recall/precision, though the underlying
question — does overlap specifically fix boundary-split answers, as opposed to bulk metrics — is
not isolated in it.

A second data point, found via search summary and **not independently verified against the
underlying paper** (a CRUD-RAG-style Chinese-benchmark study), reported task-dependent effects:
minimal impact on QA accuracy metrics like BLEU/ROUGE, but summarization recall improving with
overlap up to "70% overlap" as the reported optimum. Flag this as **secondary, not fetched, and the
specific 70% figure should be treated with real skepticism** — it did not match Chroma's finding and
no methodology detail was retrievable from the summary alone.

**The commonly repeated overlap fractions (10–20%, sometimes 50%) are practitioner convention with
no benchmark backing found in this search.** Every vendor cookbook (LangChain, LlamaIndex docs,
assorted engineering blogs) states a default overlap without citing an ablation. The one default
Chroma's paper specifically tested and criticized — OpenAI's own cookbook default of 800-token
chunks / 400-token overlap (50%) — scored **worst of all configurations tested** on precision/IoU
and only middling on recall, which is a direct rebuttal of "the vendor default is a safe overlap
choice."

**Cost is real and directly measured in the Chroma numbers above**: overlap raises index size
roughly by the overlap fraction (more stored tokens) and demonstrably lowers precision by returning
duplicate-content chunks that compete for the same top-k slots — i.e., overlap can *cost* you a
result slot that could have carried a different relevant chunk, which is exactly the failure mode
our top-5-per-file cap would be sensitive to.

**Bottom line for question 1**: overlap is measured to help essentially not at all on recall in the
one controlled study found, and to hurt precision. It is not established as a fix for the specific
"answer chunk absent from an otherwise-correct-file pool" failure our sweep observed. This is a real
gap in the literature relative to our failure mode — nobody has run the specific ablation "does
overlap specifically rescue boundary-adjacent misses," as opposed to bulk precision/recall.

## 2. Structure-aware / heading-based splitting for markdown — measured, and the evidence favors it, with one important reversal

**Structure-aware chunking (paragraph/heading boundaries) measurably beats naive fixed-size or
character-count chunking, in more than one independent study.**

- The SIGIR 2026 paper "Beyond Chunk-Then-Embed" (arXiv:2602.16974, fetched) found, on six BEIR
  datasets (FiQA, ArguAna, SciDocs, TREC-COVID, SciFact, NFCorpus), that structure-based
  (paragraph) chunking **substantially outperformed** LLM-guided/proposition-based chunking for
  in-corpus retrieval: paragraph-based reached **0.4948 nDCG@10** with a Jina-v3 embedder versus
  proposition-based's **0.3888** — a 15–27% relative degradation for the fancier method. This is a
  genuine head-to-head with real numbers.
- The same paper found the ranking **reverses for in-document retrieval** (GutenQA, 100 literary
  works, 3,000 QA pairs): there, `LumberChunker` (an LLM-guided method) beat paragraph-based,
  0.5640 vs 0.4574 DCG@10. **This is the single most important qualifier in the whole literature
  search: "structure-aware wins" is not a universal law — it depends on whether the retrieval task
  is finding-the-right-document-in-a-corpus (favors structure) or finding-the-right-passage-within-
  a-known-document (favors semantic/LLM segmentation).** Our failure mode (right document already
  found, wrong section) sits closer to the in-document regime where this paper found structure-based
  chunking to be the *weaker* method, not the stronger one — worth being honest about, since it cuts
  slightly against the intuitive fix.
- A separate independent evaluation on the UltraDomain dataset (36 chunking strategies × 6 domains
  × 5 embedding models × 1,080 configurations, LLM-judged relevance) found "Paragraph Group
  Chunking" (structure-aware, coherence-preserving) as best overall, mean nDCG@5 ≈ 0.459, against a
  fixed-character-chunking baseline below nDCG@5 = 0.244 — a large, clean gap. This paper is a
  large-scale, methodologically serious independent evaluation (found via search synthesis, one
  layer removed from the primary source; the specific paper title/arXiv id was not independently
  confirmed by direct fetch, so treat the exact numbers as reported-by-summary rather than
  verified against the PDF).
- A smaller applied evaluation (found via search summary only, not fetched, so **unverified and
  possibly summarizer-invented** — attempts to locate the primary source directly did not succeed)
  reported a "heading-aware chunker" matching a sliding-window chunker's Recall@5 (~0.82) while
  achieving better MRR (right answer ranks higher) using roughly half the chunk count. **This
  specific figure could not be traced to a primary source and should not be relied on**; it is
  included only because it is thematically consistent with the two verified studies above, not as
  independent corroboration.

**Bottom line for question 2**: heading/paragraph-aware splitting has real, multi-study support for
*document-level and corpus-level* retrieval quality over naive fixed-size chunking. It is **not**
established as the fix for the specific problem of a correct document losing its correct in-document
section — the one paper that separated these two regimes found structure-aware chunking *weaker*
than LLM-guided in-document chunking on exactly that axis. Our own paragraph-greedy approach is
already "structure-aware" at the paragraph level; the open question the literature actually
supports investigating is whether *heading*-level boundaries (as opposed to paragraph/blank-line
boundaries, which is what we already do) change anything — this was not isolated as a distinct
variable in any study found.

## 3. Small-to-big / parent-document / auto-merging retrieval — plausible, weakly measured, mostly a positive-but-thin result

This is the one place the literature is thinnest relative to how popular the technique is in
practitioner tooling (LlamaIndex ships it as a first-class retriever).

**The only quantitative evaluation found** (via search synthesis, LlamaIndex/TruLens-based,
not an independent academic benchmark) reported the Auto-Merging Retriever achieving similar scores
to a baseline retriever on TruLens's RAG Triad (context relevance, groundedness, answer relevance)
with a **52.5% pairwise preference** for auto-merging responses over baseline in human/LLM-judged
comparison. **This is a weak result**: 52.5% against a 50% coin-flip baseline is barely above
noise, the evaluation is vendor-adjacent (LlamaIndex's own tutorial ecosystem), and no confidence
interval or sample size was surfaced in the search results. This should be read as "plausibly
slightly positive, essentially unmeasured at the rigor level the other techniques here have," not as
established. No BEIR/MTEB-style independent benchmark of parent-document retrieval specifically was
found in this search.

**Mechanistically, this is the closest technique to what the brief is actually asking about**:
small-to-big keeps the precision benefit of small chunks for the match, then expands to a larger
context window (parent section) at answer-construction time — which is a plausible fix for
"answer chunk didn't rank but a neighbor did," since if the neighbor *did* reach the pool, expanding
it to include the true answer chunk solves the problem without touching the index. Nothing found
measures this specific mechanism ("does expanding a retrieved chunk to its N neighbors recover an
answer that was 1–2 chunks away") directly — it is inferred from the general architecture
description, not from a measured ablation isolating exactly that scenario. Flag this explicitly:
**the literature does not contain the specific experiment your situation needs**; the closest thing
is the auto-merging pairwise-preference number above, which is weak.

## 4. Contextual retrieval (Anthropic) — vendor-measured, real gains reported, methodology has real gaps for judging transfer

Fetched directly from Anthropic's own post (`anthropic.com/news/contextual-retrieval`, Sept 2024).
This is a **vendor blog, not an independent evaluation** — flagged per the brief's instruction.

**Their reported numbers** (failure rate = the fraction of top-20-retrieved-chunk evaluations that
miss the relevant chunk, across their internal codebase/fiction/ArXiv/science-paper corpora):
- Contextual embeddings alone: 5.7% → 3.7% failure rate (35% relative reduction)
- + contextual BM25 (i.e., prepending the same generated context before indexing into BM25 too):
  5.7% → 2.9% (49% relative reduction)
- + a reranking stage on top: 5.7% → 1.9% (67% relative reduction)

**Method**: an LLM (Claude 3 Haiku, cheap model deliberately chosen) is given the *whole document*
and the *specific chunk*, and asked to write a short (50–100 token) "situating" sentence describing
where this chunk sits in the document and what it is about; that sentence is prepended to the chunk
before embedding *and* before BM25 indexing. Cost, per Anthropic: **$1.02 per million document
tokens**, one-time, made cheap specifically by prompt caching the whole document across all its
chunks' generation calls (so the document is "read" by the LLM once per document, not once per
chunk, from a caching-cost perspective).

**What this gives you over a structural (file-path) prefix that a pure-code prepend does not**:
Anthropic's context sentences are chunk-specific and content-aware — they can say things like "this
chunk discusses the company's Q2 2023 revenue growth, which is 3% relative to Q1" (their own
worked example), i.e., they can carry *disambiguating facts extracted from elsewhere in the
document* that a filename or heading path structurally cannot express, because the LLM has read
the whole document and the chunk together. A structural prefix (file path, or even a full heading
breadcrumb) can tell a chunk "you are in section 3.2 of file X" but cannot tell it "the antecedent
of 'this parameter' three paragraphs up is the retry budget" — that requires understanding content,
which is exactly the class of information an LLM-generated situating sentence can inject and a path
prefix cannot.

**Real methodological gaps, stated plainly**: Anthropic does not publish per-corpus breakdowns, the
exact chunk sizes used beyond "usually no more than a few hundred tokens," the number of documents
or queries evaluated, or any variance/confidence interval — this is a single aggregate percentage
improvement across an unspecified mixture of corpora, reported by the team that built the method,
with no third-party replication found in this search. It should be treated as a real, plausible, but
**unreplicated** result. No independent academic paper reproducing Anthropic's specific numbers was
found; several blog posts (MemX, tds.s-anand.net) restate the same figures without new measurement.

## 5. Late chunking (Jina) — real paper, small measured gains, and it structurally does not apply to a 512-token model

Fetched arXiv:2409.04701 ("Late Chunking: Contextual Chunk Embeddings Using Long-Context Embedding
Models") directly.

**Mechanism**: embed the *entire document* through a long-context transformer to get token-level
embeddings that have attended to the whole document, *then* pool those token embeddings into chunk
vectors after the fact — so each chunk's vector reflects context from the whole document (e.g., a
pronoun or short reference correctly resolves to what it refers to elsewhere in the text) without
any generation cost (no LLM call, unlike Anthropic's approach).

**Requirement, unambiguous**: this needs a long-context embedding model that can encode the entire
document (or a large span of it) in one forward pass — the paper tests `jina-embeddings-v2-small`
(8,192-token context), `jina-embeddings-v3`, and `nomic-embed-text-v1`. **It structurally cannot
apply to a 512-token model like bge-small-en-v1.5**: if the model can only encode 512 tokens at a
time, there is no "whole document" pass to pool from — you are back to chunking before embedding,
which is exactly the naive case late chunking exists to avoid. The paper does not test or discuss
short-context models at all; this is an inference from the method's premise, not a discussed
limitation in the paper, but it is not a contentious inference — mean-pooling requires the
transformer to have actually attended across the full span first.

**Measured gains, on BeIR (SciFact, NFCorpus, FiQA, TRECCOVID), averaged across the three models**:
nDCG@10 relative improvements of **3.46%** (fixed-size boundaries), **3.63%** (sentence
boundaries), and **2.70%** (semantic-sentence boundaries) — i.e., roughly **1.5–1.9 percentage
points absolute**. These are real, modest, positive numbers from the paper's own evaluation, not a
vendor blog claim without a benchmark — arXiv:2409.04701 is a proper paper with BeIR numbers, though
it is Jina's own research team publishing about their own models, so it is not third-party either.

**Bottom line for question 5**: not applicable to our stack without swapping the embedder for a
long-context model (an 8K-context model, not a 512-token one), and even then the measured gain on
BeIR is small (~2–4% relative nDCG@10) — not a large lever relative to, say, the structure-aware
chunking or contextual-retrieval numbers above.

## 6. Semantic chunking — the vague sense of negative results is correct; it is a case study in a popular method that mostly does not hold up

This was the question to check most carefully per the brief, and the evidence does support
skepticism.

**Chroma's evaluation (fetched) is the clearest data**: `KamradtSemanticChunker` (Greg Kamradt's
original embedding-similarity-breakpoint method, the one usually meant by "semantic chunking" in
practitioner discussion) scored **worst or near-worst** of all methods tested — 83.6% recall, 1.5%
precision/IoU, both at the bottom of the table, *below* plain `RecursiveCharacterTextSplitter` and
`TokenTextSplitter` at comparable settings. Chroma's own paper (whose authors devised improved
variants specifically because the original underperformed) states the original Kamradt method
tends to produce very short, uneven chunks that hurt precision. Their own improved variants —
`ClusterSemanticChunker` (a global optimization over embedding-similarity clustering rather than
Kamradt's greedy local one) and `LLMSemanticChunker` (an LLM directly proposes boundaries) — *do*
beat naive fixed-size chunking on this benchmark (ClusterSemanticChunker: best precision/IoU at
8.0%; LLMSemanticChunker: best recall at 91.9%). So the more precise finding is: **the original,
widely-cited "semantic chunking via consecutive-sentence-embedding-distance" method (Kamradt's) is a
measured negative result — it underperforms simple recursive/token splitting on a real controlled
benchmark** — while newer, heavier variants that still use embeddings (globally-optimized
clustering, or an LLM directly) can beat naive fixed-size chunking, at meaningfully higher
computational cost (an embedding call per sentence, or an LLM call over the whole document).

**The SIGIR taxonomy paper (fetched) corroborates from a different angle**: proposition-based
(semantic-ish) chunking underperformed simple paragraph-based chunking by 15–27% on in-corpus BEIR
retrieval, though it *did* win on in-document retrieval (GutenQA) — again the corpus-vs-document
distinction from section 2 above. Proposition-based chunking did gain "+22.87% average improvement"
when it was itself embedded with contextualization (i.e., adding surrounding-context signal cheaply
helps semantic methods specifically), but even then it still ranked below plain structure-based
methods in absolute terms on the in-corpus task.

**Bottom line for question 6**: your instinct is right. "Semantic chunking" in its most commonly
cited original form (Kamradt-style breakpoint detection on consecutive-sentence embedding distance)
is a measured underperformer relative to simple methods on at least one real, controlled benchmark,
and a second independent taxonomy study found the broader "split by embedding/LLM judgment of
meaning" family underperforming plain paragraph splitting for the corpus-level retrieval task (the
one closer to ours). It is not that semantic chunking never helps — heavier, more carefully engineered
variants (global clustering, LLM-proposed boundaries) do show gains over naive fixed-size chunking
in Chroma's numbers — but the popular, cheap, "measure embedding distance between adjacent sentences
and cut where it drops" version that most blog posts describe and that gets the most citation is
the version with a real negative result behind it, not the version that was shown to work.

## 7. Chunk size — real measured guidance exists, and it is corpus/task-dependent, not a single number

**Saturation point claim, checked carefully**: search results initially surfaced a specific claim
("95% of peak nDCG@10 by 32 tokens, no gains at 64/128") attributed to a particular arXiv paper
(2603.06976). On fetching that paper directly, **this specific claim was not confirmed** — the
paper's actual reported chunk-size experiment used 256-token fixed chunks and 5-sentence chunks
without systematically sweeping 32/64/128, and it reported chunk-size correlation coefficients (r =
0.41–0.57 for in-document tasks, r = 0.08–0.18 for in-corpus tasks — i.e., chunk size matters
noticeably more when finding a passage inside a document you already know than when finding the
right document in a corpus) rather than a saturation curve. **The specific "32-token saturation"
number should therefore be treated as unverified/likely a search-summary artifact and not repeated
as a fact** — this is exactly the kind of number that looked precise and authoritative and did not
survive being checked against its cited source, worth flagging given this project's own stated
concern about that failure mode.

**What does hold up, from the Chroma study (fetched, real numbers)**: smaller chunks (200 tokens)
consistently produced better precision and IoU than larger chunks (400, 800 tokens) at fixed
recall, across both `RecursiveCharacterTextSplitter` and `TokenTextSplitter`, with recall roughly
flat (85–90%) across all three sizes tested. In other words: **in Chroma's data, going smaller
mostly buys precision without costing recall, up to the point where chunks get too small to carry a
complete thought** — 800-token chunks were not measurably better on recall than 200-token chunks and
were meaningfully worse on precision (1.5% vs 7.0%).

**AI21's finding (fetched) is the most important nuance and the most conceptually interesting
result in this whole search**: the *optimal* chunk size is measurably **query-dependent**, not a
property of the corpus alone. Their oracle experiment — indexing the same corpus at multiple chunk
sizes (50 to 2000 tokens) and, per query, picking whichever chunk-size index actually contained the
right answer at the top rank — found gaps of **20–30% in recall@1 between the best single fixed
chunk size and the oracle**, reaching over 40% on some datasets (QMSum, NarrativeQA, Seinfeld
transcripts). This means: for a meaningful fraction of queries, *no single fixed chunk size setting
was even in the top few candidates* — some questions are answered by a short specific fact (wants
a small chunk) and others need a broader span (wants a large chunk), and a single global chunk-size
parameter cannot serve both. This directly corroborates M25's own "the two classes want opposite
weights" fusion finding, just for chunk size instead of arm weighting, and is a genuinely
independent line of evidence for the same underlying idea: a single global parameter cannot serve
retrieval tasks with structurally different granularity needs. **Caveat**: some of AI21's supporting
numbers come from their own proprietary datasets (Seinfeld transcripts, FinanceBench) rather than
purely independent benchmarks, though the MTEB portion of their evaluation is on public, independent
data.

**Does chunk size interact with the embedder's context window?** No paper found runs this
comparison directly (chunk size swept against embedder context-window size as two crossed
variables). It is a real gap. The one thing that can be said with confidence, not from a benchmark
but from how these models work: a chunk size well under the embedder's max sequence length avoids
truncation, and a bge-small-en-v1.5-class model (512-token limit) chunked at 450 tokens (your
setting) leaves headroom for the BGE query-prefix tokens and normal tokenizer overhead — no direct
evidence either way on whether 450 is closer to over- or under-sized relative to what the model
"wants" for best retrieval, since no paper tested bge-small specifically at multiple sizes with a
comparable methodology to Chroma's (which used OpenAI/other larger embedders).

**Bottom line for question 7**: chunk size measurably trades precision for recall (smaller chunks
tend to raise precision without a strong recall cost, in the one clean study found), the "one right
answer" framing is itself likely wrong — AI21's oracle experiment is real evidence that no single
chunk size serves all queries well, with a 20–40% recall@1 gap to the oracle — and the specific
"saturates at 32 tokens" number circulating should be dropped as unverified.

## Consensus, debate, and evidence quality — summary table

| Question | Measured evidence quality | Direction of the evidence |
|---|---|---|
| Overlap improves retrieval | One real controlled study (Chroma), negative on precision, flat on recall | **Against** the common practice of large overlap; folklore-heavy elsewhere |
| Structure/heading-aware beats fixed-size | Two independent studies, real numbers, one head-to-head reversal by task type | **For**, but conditional — wins for corpus-level, loses to LLM-guided for in-document retrieval |
| Small-to-big / auto-merging | One weak result (52.5% pairwise preference, vendor-adjacent tooling) | Thin, plausibly positive, essentially unmeasured at rigor of the others |
| Contextual retrieval (LLM-generated context) | Vendor-reported (Anthropic), real numbers, unreplicated by any third party found | Plausible real gain, methodology gaps (no per-corpus breakdown, no CI) |
| Late chunking | Real paper (Jina), real BeIR numbers, small effect size, requires long-context embedder | Real but modest gain; structurally inapplicable to our 512-token model |
| Semantic chunking (Kamradt-style) | Real controlled benchmark, clearly negative | **Negative** for the popular cheap version; heavier variants (LLM/global-clustering) do show gains |
| Optimal chunk size is a single number | Multiple studies; AI21's oracle experiment is the sharpest | Query-dependent, not corpus-dependent alone; a global constant leaves 20–40% recall@1 on the table by AI21's oracle measure |

## Open questions and gaps this search did not close

1. **No study isolates the exact failure our sweep found** — "right file retrieved, answer chunk
   1–2 positions away, never surfacing." Everything here is inferred from adjacent, more general
   experiments (overlap's bulk recall/precision effect, small-to-big's weak pairwise-preference
   number) rather than a direct test of this specific scenario. This would need to be run as our own
   ablation to get a real answer, not found in the literature.
2. **Heading-level versus paragraph-level structure was never isolated as a distinct variable** in
   any study found — "structure-aware" in the literature almost always means paragraph-or-better,
   which is what we already do; nothing measures whether going one level up (full heading hierarchy
   as a boundary, as opposed to blank-line/paragraph boundaries) changes retrieval specifically for
   markdown documents with sections.
3. **Chunk size crossed against embedder context window was not tested by anyone found** — a real
   gap, and directly relevant since our embedder (512-token bge-small) is smaller than every model
   used in the cleanest chunk-size study (Chroma used `text-embedding-3-large` and
   `all-MiniLM-L6-v2`, neither BGE).
4. **Anthropic's contextual retrieval numbers have no independent replication found in this
   search** — worth checking again in a future pass, since this is now two years old (Sept 2024)
   and a technique with genuinely public claimed value that no academic paper appears to have
   reproduced or refuted, which is itself slightly notable for how widely the claim gets repeated.
5. **The "heading-aware chunker matches sliding window recall with better MRR at half the chunk
   count" figure could not be traced to a primary source** and should be treated as unconfirmed;
   worth a direct follow-up search if this specific number becomes load-bearing for a decision.
6. **The overlap-helps-summarization-at-70%-overlap claim** was found only via search synthesis and
   not independently verified against its source paper; flagged as suspect above and repeated here
   because it is the kind of specific-sounding number this corpus has been burned by before.

## Sources

1. [Evaluating Chunking Strategies for Retrieval — Chroma Research](https://www.trychroma.com/research/evaluating-chunking) — fetched directly; controlled study, 5 corpora, 472 GPT-4-Turbo-generated synthetic queries, multiple chunkers and embedding models.
2. [Contextual Retrieval — Anthropic](https://www.anthropic.com/news/contextual-retrieval) — fetched directly; vendor blog, Sept 2024, internal benchmark across codebases/fiction/ArXiv/science-paper corpora.
3. [Late Chunking: Contextual Chunk Embeddings Using Long-Context Embedding Models, arXiv:2409.04701](https://arxiv.org/html/2409.04701v2) — fetched directly; Jina AI research team, BeIR evaluation (SciFact, NFCorpus, FiQA, TRECCOVID).
4. [Beyond Chunk-Then-Embed: A Comprehensive Taxonomy and Evaluation of Document Chunking Strategies for Information Retrieval, arXiv:2602.16974](https://arxiv.org/html/2602.16974) — fetched directly; SIGIR 2026 (per DOI record), six BEIR datasets plus GutenQA.
5. [A Systematic Investigation of Document Chunking Strategies and Embedding Sensitivity, arXiv:2603.06976](https://arxiv.org/html/2603.06976) — fetched directly; used to check and refute an unconfirmed "32-token saturation" claim found in search summaries.
6. [Chunk size is query-dependent: a simple multi-scale approach to RAG retrieval — AI21](https://www.ai21.com/blog/query-dependent-chunking/) — fetched directly; oracle experiment across QMSum, NarrativeQA, Seinfeld, plus MTEB retrieval subset.
7. [Greg Kamradt semantic chunking, original tweet](https://x.com/GregKamradt/status/1737921395974430953) — origin of the "semantic chunking" method later benchmarked (unfavorably) by Chroma; not fetched, cited for provenance only.
8. CRUD-RAG: A Comprehensive Chinese Benchmark for Retrieval-Augmented Generation of Large Language Models, arXiv:2401.17043 — found via search synthesis only, not fetched; source of the unverified 70%-overlap-for-summarization claim, flagged as suspect in the note above.
9. Auto-Merging RAG / Improving Retrieval with Auto-Merging — Haystack, LlamaIndex/TruLens tutorial ecosystem — found via search synthesis only; source of the weak 52.5% pairwise-preference figure for small-to-big retrieval, not independently fetched or verified.
10. "I Tested Chunking on Docs, PDFs, and Code" and related dev.to / blog posts on heading-aware chunking — found via search only; could not trace the specific "Recall@5 ~0.82, half the chunks" figure to a primary source, flagged as unconfirmed.
11. UltraDomain-based 36-strategy / 6-domain / 5-model chunking evaluation — found via search synthesis, large-scale independent evaluation described but not fetched directly against a confirmed arXiv id; numbers reported as stated in the summary, not independently checked against the PDF.
