# Embedding model choice for retrieving technical prose containing precise identifiers

Research note for Zikaron's dense-retrieval component. Written in response to a brief testing
whether `BAAI/bge-small-en-v1.5` (the incumbent, via `fastembed`) is the wrong tool for embedding
prose gists that are dense with identifiers, versioned type names, env vars, and file paths — or
whether the hybrid design (BM25 + dense, fused with RRF) already delegates exact-token matching
away from the dense side, making bge-small adequate.

**Position under test:** small general-purpose prose embedder may mis-serve identifier-heavy text.
**Counter-position:** BM25 carries exact-token matching; dense side only needs paraphrase/concept
matching, which is bge-small's strength. Brief asks for evidence to *measure* this, not resolve it
by argument.

---

## 1. Hard facts on `BAAI/bge-small-en-v1.5`

Sourced from the official HF model card (huggingface.co/BAAI/bge-small-en-v1.5), the model's
`config.json`, and the FlagEmbedding/BGE GitHub repo (github.com/FlagOpen/FlagEmbedding).

| Property | Value | Source |
|---|---|---|
| Architecture | BERT (`model_type: bert`), 12 layers, 12 attention heads, hidden size 384, intermediate size 1536 | `config.json` [1] |
| Embedding dimension | 384 | Model card, `config.json` [1][2] |
| Max sequence length | 512 (`max_position_embeddings: 512`) | `config.json`, model card MTEB table lists "Sequence Length: 512" [1][2] |
| Tokenizer | WordPiece, BERT-standard vocabulary, `vocab_size: 30522` | `config.json` [1] |
| Parameters | 33.4M | HF file listing ("Safetensors ... 33.4M params") [2] |
| License | MIT, "released models can be used for commercial purposes free of charge" | Model card License section [2] |
| Download size (fastembed) | 0.067 GB (~67 MB) | fastembed `TextEmbedding.list_supported_models()` [3] |

**Query-instruction prefix — v1.5 specifically reduces but does not eliminate the recommendation.**
The model card's own FAQ #3 ("When does the query instruction need to be used") states directly:

> "For the `bge-*-v1.5`, we improve its retrieval ability when not using instruction. No instruction
> only has a slight degradation in retrieval performance compared with using instruction. So you can
> generate embedding without instruction in all cases for convenience. For a retrieval task that uses
> short queries to find long related documents, it is recommended to add instructions for these short
> queries... In all cases, the documents/passages do not need to add the instruction." [2]

This **confirms** the brief's claim that v1.5 "reduced the need" — it is an explicit, first-party
statement, not an inference. The exact recommended prefix string, given in the model's own "Model
List" table, is:

```
Represent this sentence for searching relevant passages:
```

This prefix is asymmetric by design: the model list table footnote states "if you need to search the
relevant passages to a query, we suggest to add the instruction to the query; in other cases, no
instruction is needed... In all cases, **no instruction** needs to be added to passages." [2] So the
model is explicitly built for **asymmetric query/passage treatment** (short-query-to-long-passage,
i.e. "s2p" in BGE's own terminology), with the option to skip the query prefix entirely in v1.5 at a
"slight" cost. This maps cleanly onto Zikaron's push path (natural-language task description as
query, prose gist as passage) — the s2p framing is exactly right for that path. It does **not**
obviously fit the pull path, where the "query" is a literal error string or identifier — BGE's own
guidance to add the instruction "for short queries to find long related documents" does not
contemplate a query that is itself a bare technical token.

**Prior Zikaron implementation passes raw text with no prefix on either side** — per the brief. Per
the model's own FAQ, this is an explicitly supported configuration, at a stated "slight" cost on
retrieval quality relative to using the prefix on the query side. Zikaron's current setup is
therefore not a misuse of the model, but it is leaving a small, first-party-acknowledged amount of
retrieval quality on the table on the push path specifically.

**Over-length input: silent truncation, not an error.** Every FlagEmbedding usage example in the
model card tokenizes with `padding=True, truncation=True` set explicitly, and the ONNX/Transformers
examples repeat this pattern without any length-check or exception path shown [2]. `truncation=True`
in the HF `tokenizers`/`transformers` stack truncates silently to `max_length` (defaulting to the
model's `max_position_embeddings`, 512, when not overridden) — there is no first-party warning or
error surfaced to the caller. For Zikaron, whose `content` field is explicitly noted to sometimes
exceed 512 tokens, this means: **anything past ~512 WordPiece tokens is silently dropped from the
embedded representation**, with no signal that truncation occurred. This is a real risk specific to
the `content` field (not `gist`, which is presumably short) and is one of the two clearest,
already-settled arguments for moving to a longer-context model, independent of the identifier
question.

**Symmetric or asymmetric?** Architecturally the model is a single bi-encoder (same weights encode
both queries and passages) — there is no separate query-tower/passage-tower. But BGE's own
documentation treats it as functionally asymmetric via the optional prefix, calling out "s2p" (short
query → long passage) as the intended retrieval shape. So: same weights, asymmetric usage
convention, prefix optional and query-side-only.

---

## 2. The identifier-discrimination question

**Direct evidence — searched for and not found.** No paper, benchmark, or first-party analysis was
located that directly measures whether general-purpose text embedders (bge-small or otherwise)
distinguish near-miss precise tokens such as `WidgetV1` vs `WidgetV2`, `v2.3.1` vs `v2.3.10`,
`conftest.py` vs `conf_test.py`, or near-duplicate snake_case/CamelCase identifiers, in a retrieval
context. This was searched from several angles (tokenizer vocabulary-coverage studies, retrieval
failure-mode papers, code-identifier tokenization analyses, version-string/SKU/error-code retrieval
evaluations) and no matching study surfaced. **This is a genuine evidence gap, not a subtle one** —
stating this plainly per the brief's instruction, because it means the identifier-discrimination
question cannot currently be settled by citation and must be measured directly on Zikaron's own
candidate pairs (a small, targeted eval set of near-miss identifier pairs run through each candidate
model, checked for whether the correct document lands ahead of the near-miss distractor).

**The closest adjacent evidence, and why it is adjacent rather than direct:**

1. **NIKIEMA et al., "How Small Transformation Expose the Weakness of Semantic Similarity Measures"
   (2025)** [4] is the strongest indirect signal. It measures cosine-similarity failures on
   controlled *sentence-level* semantic transformations — synonym substitution, negation, antonym
   substitution, word reordering — not identifier-level tokens. Its most alarming numbers: BERTScore
   assigns 0.95 similarity to negated pairs and 0.95 to antonym pairs (where ≤0.3 would be
   appropriate); `all-MiniLM-L6-v2` and `all-mpnet-base-v2` (both general sentence-embedding models
   in the same architecture family as bge-small) score 0.90 and 0.88 respectively for negation pairs,
   and the paper reports an average false-positive rate of 96.2% across embedding models on its
   semantic-difference categories, confirmed by a Mann-Whitney U test (U=0.0, p<0.001) showing
   embeddings "completely unable to distinguish semantic differences from equivalence" at the
   sentence level. This is evidence that general sentence embedders exhibit broad "semantic
   blindness" to negation/opposition — a related-but-distinct failure mode from failing to
   distinguish `WidgetV1` from `WidgetV2` inside otherwise-similar prose. The mechanism (subword/CLS
   pooling smoothing over a difference that matters) is plausibly shared, but the paper does not test
   identifiers and should not be cited as if it did. Same paper's Experiment 2 finding — that
   switching from cosine to Euclidean distance improves CodeBERT's semantic-difference detection by
   24–66% and GraphCodeBERT's by 37–72% on *code* embeddings, while giving negligible (0–3%)
   improvement on general-purpose *text* embeddings — is a secondary, citable finding: the
   distance-metric fix that helps most for code-trained models does not transfer to prose-trained
   ones, which is one more data point against expecting a quick win from code-aware embedders on this
   specific failure mode. [4]

2. **Li, Deng & Nie, "TokDrift: When LLM Speaks in Subwords but Code Speaks in Grammar" (2025)** [5]
   is adjacent but answers a different question: it measures whether *generative code LLMs'
   downstream task accuracy* (bug-fixing, summarization, translation) shifts when semantically
   identical code is retokenized differently (camelCase→snake_case, spacing changes) — not whether
   *embedding retrieval* is affected. Its most transferable finding for Zikaron's purposes: identifier
   casing changes that alter the underlying LLM subword-fragment boundaries ("identifier fragment
   change") produce measurably higher output sensitivity than casing changes that don't — e.g. 10.82%
   vs 6.61% average sensitivity for large code models on naming-convention rewrites [5]. This confirms
   that *subword fragmentation of identifiers is not a fixed cost that models learn to absorb* — when
   an edit changes fragment boundaries, downstream behavior measurably shifts, even in models trained
   heavily on code. It is evidence that identifier tokenization matters generically to model behavior,
   not specific evidence that embedding cosine similarity for `WidgetV1` vs `WidgetV2` collapses.

3. **Practitioner consensus on dense retrieval and rare tokens (blogs/guides, not peer-reviewed) is
   large and consistent**, though it should be weighted as practitioner wisdom rather than measured
   research: dense embeddings are widely reported to dilute rare, information-dense tokens (error
   codes, SKUs, exact identifiers) because "embeddings average meaning across dimensions... rare or
   unique tokens get diluted" [6], and this is the standard justification for hybrid BM25+dense
   architectures generally (multiple independent sources converge on "recall@10 lift of 10-30% on
   corpora heavy on identifiers" when adding BM25 to vector search, though none of these figures trace
   to a controlled, citable study — they read as practitioner-reported, not benchmarked) [6][7][8].
   This is consensus *for the general claim* that dense retrieval underperforms on rare/exact tokens —
   which supports the counter-position that BM25 should carry this load — but is **not** evidence
   specifically about *near-miss* identifiers (two tokens that are lexically close but semantically
   opposed), which is the user's more specific and harder concern. BM25 handling `WidgetV2` well when
   the query says `WidgetV2` is a different and easier problem than the dense vector for a document
   about `WidgetV2` not spuriously drifting close to a document about `WidgetV1`.

**Conclusion for this section:** the user's core concern is unfalsified but also unproven by any
existing study. The adjacent literature establishes that (a) general text embedders are broadly weak
at fine-grained semantic *opposition* at the sentence level, and (b) identifier subword-fragmentation
does measurably affect model behavior when it changes — both mildly supportive of the user's hunch as
directional priors — but nothing measures the specific failure mode (near-miss versioned identifiers
inside similar prose, embedded by a small BERT-style bi-encoder, retrieved via cosine similarity in
RRF alongside BM25). **This must be measured empirically** with a small targeted eval built from
Zikaron's own memory shapes (e.g. pairs of gists that differ only in a version suffix or a similar
identifier, with human-labeled "these should NOT rank near each other" ground truth) before the
question can be closed either way.

---

## 3. Do code-aware or mixed code+text embedders help here?

The brief asks to separate two claims that are conflated in casual discussion: (a) whether a model's
**training objective** (what it was contrastively trained to retrieve — NL→code, code→code) matches
Zikaron's task (prose→prose), and (b) whether a model's **tokenizer/backbone vocabulary** was
exposed to code-heavy corpora, which is a separable property that could help identifier handling
*regardless* of training objective.

### (a) Training objective: user's claim that code-aware embedders are trained for the wrong task is confirmed for every model checked

| Model | Confirmed training objective | Source |
|---|---|---|
| CodeSage (v2) | Pretrained with MLM + deobfuscation on **The Stack** (code only), then contrastively fine-tuned on (text, code) pairs extracted from **The Stack V2** — summaries paired with function/class bodies. Evaluated by its own authors on **Code2Code Search** and **NL2Code Search** exclusively. | Model card, arXiv:2402.01935 [9] |
| jina-embeddings-v2-base-code | Backbone (`jina-bert-v2-base-code`) pretrained on the `codeparrot/github-code` dataset; embedding model further trained on "150+ million of coding **question answer and docstring source code pairs**." Explicitly a code-search / NL→code model; usage examples pair a natural-language question with a code snippet answer. | Model card, arXiv:2310.19923 [10] |
| nomic-embed-code | 7B-parameter model built on Qwen2.5-Coder-7B, trained on the CoRNStack dataset (docstring/code pairs from deduplicated Stack v2) with the explicit query prefix `"Represent this query for searching relevant code: <text>"`. Self-reported to outperform Voyage Code 3 / OpenAI Embed 3 on **CodeSearchNet**, an NL→code benchmark. | Model card, arXiv:2412.01007 [11] |
| Qodo-Embed-1 (1.5B / 7B) | Built on `Alibaba-NLP/gte-Qwen2-1.5B-instruct`; card states explicitly: "optimized for **natural language-to-code and code-to-code retrieval**." | Model card [12] |

Every one of these models is, by its own documentation, trained and evaluated for NL→code or
code→code retrieval, not prose→prose retrieval. This directly **confirms** the brief's stated
position that these are trained for the wrong task for Zikaron's push path (human task description →
agent-written prose gist) and, more debatably, for the pull path (literal error string → prose gist,
which is at least code-adjacent but still prose-to-prose, not code-to-code). No counter-evidence to
this specific claim was found — the objective mismatch is real and well-documented by the models'
own cards.

Separately, three of the four are disqualified on the **hard operational constraints** before the
objective question even matters: nomic-embed-code is 7B parameters (multi-GB, far outside "runs
locally on CPU... first-run download size matters" — the brief's implicit ceiling given the ~130MB
incumbent), and Qodo-Embed-1 comes in 1.5B/7B variants (2B+ params for the "lite" version) under a
custom `qodoai-open-rail-m` license (not a standard permissive OSS license — RAIL-M variants
typically carry use-based restrictions and should be read in full before any commercial use; this was
not independently verified against Zikaron's shipping plans and should be flagged for legal review if
this model is ever reconsidered) [12]. CodeSage-small-v2 (130M) and jina-embeddings-v2-base-code
(161M) are the only two in this group that are CPU/size-plausible at all; both are apache-2.0 [9][10].

### (b) Tokenizer/backbone vocabulary coverage: genuinely separable, and the two size-plausible candidates differ

- **CodeSage** uses the **StarCoder tokenizer** [9][13] — a BPE vocabulary trained by BigCode
  specifically over source code from The Stack, which by construction has far denser coverage of
  code-shaped subword pieces (common identifier fragments, punctuation runs, indentation patterns)
  than a natural-language WordPiece vocabulary. This is the strongest tokenizer-only candidate for the
  "middle ground" the brief asks about: a code-exposed vocabulary that *might* fragment identifiers
  less, decoupled from its (wrong-for-Zikaron) contrastive objective.
- **jina-embeddings-v2-base-code**'s backbone (`jina-bert-v2-base-code`) was pretrained on
  `codeparrot/github-code`, meaning its vocabulary was also exposed to real code during pretraining,
  distinct from its NL/code-pair fine-tuning objective [10].
- **bge-small-en-v1.5**, by contrast, uses the standard BERT-base WordPiece vocabulary
  (`vocab_size: 30522`), trained on general English corpora with no code exposure [1].

**No controlled comparison of identifier-fragmentation rates between these specific tokenizers was
found** — this falls into the same evidence gap as Section 2. What *is* documented, from the TokDrift
paper's background section, is the general principle that different tokenizer families can share
"less than half" their vocabulary even within the same model lineage, and that code-oriented
tokenizers (the paper specifically discusses CodeQwen-1.5 disabling pre-tokenization to leave
underscores and long ASCII spans intact, and DeepSeek-Coder using code-oriented character-class
splits) make deliberate design choices that reduce identifier fragmentation relative to general NL
tokenizers — but this evidence is about decoder-only code-LLM tokenizers, not encoder embedding
models, and is not a direct measurement of CodeSage's or Jina-code's WordPiece/BPE fragmentation rate
on Zikaron-shaped identifiers [5].

**Verdict on question 3, held to the brief's requested standard:** the training-objective claim
(code-aware embedders are worse-suited to Zikaron's prose→prose task) is well-supported by every
model's own documentation and should be treated as settled. The tokenizer-coverage "middle ground"
claim is *plausible on first-principles grounds* (a code-exposed BPE/WordPiece vocabulary should
fragment identifiers less than a general-English one) but **unmeasured** for the specific models
in play. If the team wants to test this middle ground cheaply, CodeSage-small-v2 (130M, apache-2.0,
StarCoder tokenizer, size-plausible) is the correct object to measure against bge-small on a
tokenizer-fragmentation count (not a retrieval eval) for a sample of Zikaron's actual identifiers —
this is a fast, cheap check (tokenize N identifiers with both tokenizers, count subword pieces) that
would give a direct, citable-to-yourselves answer without running a full embedding benchmark.

---

## 4. Would a reranker be a better spend than a bigger embedder?

**What's available locally, confirmed via fastembed's own supported-model listing**
(`TextCrossEncoder.list_supported_models()`) [14]:

| Model | Size | License |
|---|---|---|
| `Xenova/ms-marco-MiniLM-L-6-v2` | 0.08 GB | apache-2.0 |
| `Xenova/ms-marco-MiniLM-L-12-v2` | 0.12 GB | apache-2.0 |
| `BAAI/bge-reranker-base` | 1.04 GB | **mit** |
| `jinaai/jina-reranker-v1-tiny-en` | 0.13 GB | apache-2.0 |
| `jinaai/jina-reranker-v1-turbo-en` | 0.15 GB | apache-2.0 |
| `jinaai/jina-reranker-v2-base-multilingual` | 1.11 GB | cc-by-nc-4.0 (non-commercial — **excluded** if shipping commercially) |

`fastembed` has first-class reranker support today via `fastembed.rerank.cross_encoder.TextCrossEncoder`,
confirmed directly from Qdrant's own FastEmbed documentation, including a working end-to-end example
that reranks a first-stage dense retrieval and visibly fixes a ranking failure in the demo (moving the
correct "Joan of Arc" result from position 10 to position 1) [14]. This is a proven, low-friction
integration path that requires no change to the embedding/indexing side.

**CPU latency for reranking ~50 pairs: not independently confirmed to the standard this brief
requires.** The only concrete figure found for a bge-reranker-family model was for
`bge-reranker-v2-m3` (a different, larger multilingual variant than `bge-reranker-base`), reported by
a third-party ONNX conversion's own model card as "~600–800 ms (CPU) instead of 4 internal sub-batches
summing ~1 s" for a 30-pair batch [15] — this is a third-party-reported number on a different model
than the one in fastembed's table, not a first-party benchmark of `bge-reranker-base` at ~50 pairs, and
should not be treated as a reliable latency figure for planning purposes. **No authoritative CPU
latency number for `BAAI/bge-reranker-base` (the MIT-licensed, fastembed-native model) at ~50 pairs was
found and none should be assumed** — this needs to be measured directly on target hardware before
being used in any latency budget, especially against Zikaron's push-path 30-second timeout ceiling
(reranking is more naturally a pull-path tool anyway, since pull is where the agent already has a
concrete top-k to refine, whereas push wants a fast top-5 surfaced on every message).

**The honest tradeoff, as the brief requests:**

- A reranker attacks precision *directly on the actual query/document pairs*, seeing both jointly
  (cross-encoder full attention) rather than comparing independently-computed vectors — this is
  architecturally the correct tool for exactly the identifier-discrimination problem in Section 2,
  because a cross-encoder can in principle attend to the difference between `WidgetV1` and `WidgetV2`
  appearing in the query versus the candidate document, where two independently-pooled bi-encoder
  vectors might not preserve that distinction after pooling.
- It requires **no corpus re-embedding** when adopted or swapped — a genuine operational advantage
  over an embedder upgrade, which requires reindexing every existing memory (see Section 7).
- It **adds cost, not replaces it** — a reranker is applied *after* first-stage retrieval (BM25 + dense
  + RRF), so it is a pure latency/complexity addition on the pull path, not a substitute for the
  embedder. It does not fix the embedder's dense-side recall if the embedder's vector for the *correct*
  document doesn't make it into the top-k candidate pool in the first place — a reranker can only
  reorder what is already retrieved.
- It is a better fit for the **pull path** (agent-initiated, more latency headroom, more likely to
  have exactly the near-miss-identifier problem in play) than the **push path** (hook-fired per user
  message, tighter latency budget, arguably less benefit since the query is natural language and BM25
  is not doing heavy lifting there anyway).
- **Bottom line on the tradeoff:** a reranker is a plausible, low-regret pull-path addition
  independent of what happens with the embedder decision, because it doesn't require reindexing and
  directly targets the joint-attention advantage that bi-encoders structurally lack. It is not a
  substitute for evaluating whether the embedder's recall is adequate — that is a first-stage problem
  a reranker cannot fix.

---

## 5. Shortlist of candidate embedders to benchmark

All below verified against fastembed's `TextEmbedding.list_supported_models()` and/or the model's own
HF card. Latency is marked "not confirmed" where no first-party or reliable benchmark was found — per
the brief's instruction, no number is asserted where one could not be confirmed.

| Model | Dim (native) | Matryoshka truncation | Max context | Prefix required | fastembed? | Download size | Warm CPU query latency | License |
|---|---|---|---|---|---|---|---|---|
| **BAAI/bge-small-en-v1.5** (incumbent) | 384 | No | 512 | Optional, query-only: `"Represent this sentence for searching relevant passages: "` | Yes [3] | 0.067 GB [3] | **Not confirmed** — fastembed maintainers have not published an official cross-hardware benchmark [16] | MIT [2] |
| **BAAI/bge-base-en-v1.5** | 768 | No | 512 | Same prefix string, same optional-query-only convention [2] | Yes [3] | 0.42 GB (approx., scaling from base/large fastembed sizes; not independently re-verified) | Not confirmed | MIT [2] |
| **Snowflake/snowflake-arctic-embed-m-v1.5** | 768 | **Yes** — MRL-trained, truncates cleanly to 256 (retains 100% of full-size MTEB retrieval score in Snowflake's own reported comparison) and further to 128 with quantization at ~98% | 512 (tokenizer call in official usage example passes `max_length=512` explicitly) [17] | Optional, query-only: same `"Represent this sentence for searching relevant passages: "` string [17] | Yes (fastembed lists the arctic-embed-xs and arctic-embed-l sizes explicitly [3]; the m-v1.5 variant should be confirmed directly against the installed fastembed version before relying on it) | ~0.44 GB (109M params, float32; not independently re-verified for fastembed's specific packaged size) | Not confirmed | Apache-2.0, "can be used for commercial purposes free of charge" [17] |
| **nomic-ai/nomic-embed-text-v1.5** | 768 | **Yes** — explicit Matryoshka support down to 64 dims, with a published dimension/MTEB tradeoff table (768→62.28, 512→61.96, 256→61.04, 128→59.34) [18] | **8192**, via dynamic RoPE scaling (native BERT-style position embeddings extended) [18] | **Required**, both sides, task-specific: `search_document:` for passages, `search_query:` for queries (also `clustering:`, `classification:` for other uses) [18] | Not confirmed present in fastembed's current supported-model table as fetched in this research (needs direct version check — the model uses `nomic_bert` architecture with `trust_remote_code=True` in its official usage examples, which may or may not be supported by fastembed's ONNX pipeline) | ~0.55 GB (137M params, float32) | Not confirmed | Apache-2.0 [18] |
| **codesage/codesage-small-v2** (deliberately-different option, per Section 3) | 1024 | Yes (v2 family supports MRL per its own changelog: "V2 models also support flexible embedding sizes thanks to Matryoshka Representation Learning") [9] | Not explicitly stated in the fetched model card; StarCoder-tokenizer models are typically long-context but the exact figure was not confirmed and should not be assumed | None documented for the embedding call itself | Not confirmed in fastembed | ~0.5 GB (130M params) | Not confirmed | Apache-2.0 [9] |
| **BAAI/bge-large-en-v1.5** (deliberately larger/stronger option) | 1024 | No | 512 | Same prefix convention as small/base [2] | Yes [3] | 1.2 GB [3] | Not confirmed, but every independent report found agrees large-vs-small BGE variants are markedly slower on CPU proportional to the ~3x parameter increase (33M→ likely ~330M-class); no specific multiplier confirmed | MIT [2] |

**What the "deliberately larger/stronger option" would cost, if the user's hunch is right:**
bge-large-en-v1.5 is the same architecture family and training recipe as bge-small — same tokenizer,
same MIT license, same 512-token ceiling, same optional-prefix convention — just 3x larger (1024-dim,
~10x the download size at 1.2GB vs 0.067GB). Its self-reported MTEB average is 64.23 vs bge-small's
62.17 — a ~2-point gain [2]. This is the cleanest "spend more, same architecture" comparison available:
if bge-large does not measurably improve identifier discrimination over bge-small on a targeted
near-miss eval, that is fairly strong evidence the problem is not primarily solved by scale within this
architecture family, since the tokenizer and training recipe are identical.

**On nomic-embed-text-v1.5 as "the single strongest alternative worth benchmarking":** it is the only
candidate on this shortlist that clears the brief's stated bar of "context longer than 512" with a
first-party-confirmed number (8192, via RoPE scaling) [18], carries a fully permissive Apache-2.0
license, is a reasonable CPU-plausible size (137M), and supports genuine Matryoshka truncation with a
published quality/dimension tradeoff table. Its main open risk is the unconfirmed fastembed
compatibility (it may require `sentence-transformers` with `trust_remote_code=True` rather than a pure
ONNX path through fastembed, which would violate the brief's stated preference, though not its hard
constraint, since `sentence-transformers` is explicitly allowed "only if the quality gain is
demonstrable"). This should be the first thing checked before benchmarking: confirm whether the
installed fastembed version lists `nomic-ai/nomic-embed-text-v1.5` or an ONNX-exported equivalent; if
not, decide whether the long-context and prefix advantages justify the `sentence-transformers`
dependency.

---

## 6. Leaderboard status, with skepticism

**bge-small-en-v1.5's self-reported MTEB numbers** (from its own model card, "self-reported" tag on
every listed eval result) [2]: Average 62.17, Retrieval 51.68, out of 56 tasks. At time of its 2023
release this was reported as competitive with or ahead of same-size contemporaries (gte-small: 61.36,
e5-small-v2: 59.93) and, notably, ahead of OpenAI's `text-embedding-ada-002` (60.99 average) despite
being a fraction of the size and running fully offline [2]. These are the model's **own reported**
numbers, tagged "self-reported" on HuggingFace's evaluation-results metadata — not independently
reproduced in this research pass.

**MTEB-specific caveats, from methodology-focused sources:**

- The **original MTEB paper** (Muennighoff et al., 2022) itself states "no particular text embedding
  method dominates across all tasks" across its 58 datasets and 112 languages [19] — the benchmark's
  own authors do not claim a single leaderboard number captures general quality.
- **Independent robustness analysis** (arXiv:2605.31142, "On the Robustness of Multilingual Text
  Embedding Rankings...") finds that "conclusions about model superiority often depend on implicit
  choices of dataset compositions and performance aggregation methods" [20] — i.e., reordering which
  tasks get averaged can reorder the leaderboard.
- **HUME** (arXiv:2510.10062, "Measuring the Human-Model Performance Gap in Text Embedding Tasks")
  found human annotators scoring 77.6% against a best-model score of 80.1% on the tasks they tested,
  "although variation is substantial: models reach near-ceiling performance on some datasets while
  struggling on others" [21] — evidence that aggregate MTEB scores can mask large per-task variance,
  which is directly relevant to Zikaron: the aggregate score does not tell you how a model performs on
  a distribution shift like "prose full of identifiers," because that specific distribution is not a
  distinct MTEB task.
- **Domain-specific benchmarks report large, systematic gaps from MTEB rank.** The Finance-MTEB paper
  found real-world domain performance diverges from general MTEB rank [22]; the Brazilian Portuguese
  benchmark paper found a model's global multilingual rank predicts its Portuguese-specific rank only
  moderately (Spearman ρ = 0.75; one model ranked 3rd globally and 49th on the domain-specific set) [23].
  No equivalent domain-specific benchmark exists for "technical prose about code" as a distinct MTEB
  category — which is precisely why Section 2's evidence gap exists and why the brief correctly wants
  measurement rather than another leaderboard citation.
- **Snowflake's own arctic-embed-m-v1.5 card includes a footnoted comparison table showing bge-small is
  not listed, but nomic-embed-text-v1.5 (a comparable-size competitor) scores 50.8 vs arctic's 54.2 on
  a 256-dimension MTEB Retrieval comparison Snowflake itself published** [17] — first-party comparison
  tables from competing vendors should be read as directional, not decisive, since each vendor
  naturally reports the comparison that favors their own model.

**No specific instance was found in this research of a headline MTEB score for any model in this
shortlist being flagged as inconsistent with an independent reproduction** — this absence should not
be read as a clean bill of health; it reflects the scope and time-boxing of this search, not a
confirmed absence of such a gap. The consistent, better-supported theme across every skepticism source
found is structural: aggregate leaderboard rank is not a reliable proxy for performance on a specific,
narrow distribution (like Zikaron's identifier-dense prose), regardless of whether any individual score
is "gamed." This is the load-bearing conclusion for question 6: **treat MTEB rank as a coarse, relative
filter for candidate selection (it correctly tells you bge-small, arctic-embed-m, and nomic-embed-text
are all in a similar, credible performance tier for general retrieval), not as evidence about the
specific identifier-discrimination question this brief exists to answer.**

---

## 7. Vector-space hygiene: mixing embeddings from different models in one `vec0` table

**Confirmed practice, from `sqlite-vec`'s own API and multiple independent vector-database sources.**
`sqlite-vec`'s `vec0` virtual tables are declared with a fixed dimension at creation time — the
official sample usage creates a table with `sample_embedding float[8]`, and the dimension is part of
the column type [24]. This means:

- **Cross-dimension mixing (e.g. bge-small's 384 vs bge-large's 1024) is a hard schema violation** —
  the insert or query will fail outright, not silently corrupt results. This is confirmed by
  consistent behavior across other vector stores using the same fixed-dimension-column pattern: Chroma
  raises `InvalidDimensionException`, Pinecone requires deleting and recreating the index on dimension
  mismatch [25][26].
- **Same-dimension, different-model mixing is the dangerous case, because it is not caught by any
  schema check.** Two different 384-dim models produce vectors in entirely different, incompatible
  coordinate spaces; nothing in `vec0`'s type system (or any fixed-dimension vector store's type
  system) can detect that vectors of the same declared dimension came from semantically incompatible
  embedding functions. Independent commentary converges clearly on this exact framing: "even to a
  newer version from the same provider — you are changing the coordinate system entirely... Cosine
  similarity between them is meaningless" [27]; "each model defines its own coordinate space... If the
  dimensions happen to match, nothing errors" [28].
- **Standard mitigation, confirmed across multiple independent sources discussing this exact
  problem:** store the embedding model identifier (and dimension, as a redundant safety check)
  alongside each vector or at the collection/table level, and force a full reindex of the corpus
  whenever the model changes — there is no partial-migration path that preserves correctness, because
  old and new vectors cannot be compared to each other at all [27][28]. This is treated as
  uncontroversial standard practice across every vector-database source consulted; no dissenting or
  alternative approach was found.

**For Zikaron specifically:** this means the vec0 table (or an adjacent metadata table/column) should
record which embedding model (and ideally which model version/hash) produced each stored vector, and
any embedder change — including a same-dimension swap, e.g. bge-small-en-v1.5 → a different 384-dim
model — must trigger a full re-embedding of every existing `content`/`gist` pair before the new
vectors can be trusted to compare meaningfully against each other in the same table. This is standard,
not exotic, and should be built into the migration path regardless of which embedder is ultimately
chosen.

---

## Confirmed vs. unconfirmed

**Confirmed (first-party or directly-fetched primary source):**
- bge-small-en-v1.5: 384-dim, 512 max length, MIT license, BERT-WordPiece tokenizer with 30522 vocab,
  33.4M params, ~67MB fastembed download size.
- bge-small-en-v1.5 v1.5 series explicitly reduces (does not eliminate) the need for a query
  instruction prefix; exact prefix string confirmed; passages never need the prefix; asymmetric
  query/passage usage convention confirmed by the model's own documentation.
- Over-length input is silently truncated (via standard `truncation=True` tokenizer behavior shown in
  every official usage example), not rejected or flagged.
- CodeSage, jina-embeddings-v2-base-code, nomic-embed-code, and Qodo-Embed-1 are all confirmed, from
  their own model cards, to be trained for NL→code or code→code retrieval, not prose→prose.
- nomic-embed-code (7B) and Qodo-Embed-1 (1.5B/7B) are confirmed to violate the CPU/size shippability
  constraint; Qodo-Embed-1's license is confirmed to be a non-standard RAIL-M variant requiring
  separate review.
- CodeSage uses the StarCoder BPE tokenizer (code-heavy vocabulary); jina-embeddings-v2-base-code's
  backbone was pretrained on real GitHub code; bge-small uses a general-English WordPiece vocabulary
  with no code exposure — the tokenizer-vs-objective distinction the brief asked for is real and
  confirmed at the level of "what these tokenizers were exposed to," even though no fragmentation-rate
  comparison was measured.
- `fastembed` has confirmed native reranker support (`TextCrossEncoder`) including the MIT-licensed
  `BAAI/bge-reranker-base`.
- Snowflake/snowflake-arctic-embed-m-v1.5 and nomic-ai/nomic-embed-text-v1.5 specs (dimension, license,
  Matryoshka support, prefix strings, nomic's 8192-token context via RoPE scaling) confirmed directly
  from their model cards.
- `sqlite-vec` vec0 tables are fixed-dimension at schema-creation time; cross-dimension mixing is a
  hard failure; same-dimension cross-model mixing is a silent correctness failure with no schema-level
  protection; storing model identity and forcing reindex on change is confirmed as standard practice
  across multiple independent vector-database sources.

**Unconfirmed — explicitly, per the brief's instruction not to estimate:**
- **No warm single-query CPU latency figure for bge-small-en-v1.5 (or any shortlisted model) via
  fastembed was found from an authoritative source.** A third-party blog explicitly states "there is no
  official cross-hardware latency benchmark published by the FastEmbed maintainers" [16]; other blog
  figures found for related claims were inconsistent with each other (single-source posts on the same
  low-authority domain gave contradictory numbers — 15ms/chunk at batch-16, <5ms single-query, 8ms p50
  — for what should be comparable configurations) and are not cited as fact anywhere in this note. **The
  team must measure this directly on target hardware before committing to any latency budget.**
- **No confirmed CPU latency for `BAAI/bge-reranker-base` (fastembed's MIT-licensed reranker) at ~50
  pairs.** The only concrete number found was for a different model (`bge-reranker-v2-m3`, larger and
  multilingual) from a third-party ONNX repackaging's own claims, not a controlled benchmark of the
  model actually in fastembed's table.
- **No direct study of near-miss precise-token discrimination in text embedders was found** —
  distinguishing `WidgetV1`/`WidgetV2`-style pairs, version-string near-duplicates, or
  near-duplicate snake_case/CamelCase identifiers, specifically in a retrieval context. This is the
  central open question of the whole brief and remains open; Section 2's adjacent evidence
  (sentence-level negation/antonym blindness, identifier-fragment-change sensitivity in code LLMs) is
  suggestive but not a substitute for a direct measurement.
- **No controlled comparison of subword-fragmentation rates between a code-exposed tokenizer (StarCoder,
  used by CodeSage) and bge-small's general WordPiece tokenizer, on identifiers shaped like Zikaron's
  actual content, was found.** This is a cheap, specific, doable measurement the team could run directly
  (tokenize a sample of real identifiers with both tokenizers, count subword pieces) rather than
  estimate.
- **fastembed's current support for `nomic-ai/nomic-embed-text-v1.5` specifically was not confirmed**
  in this research pass — it should be checked directly against the installed fastembed version before
  assuming a pure-ONNX path is available.
- **No instance of a shortlisted model's headline MTEB score being flagged as inconsistent with an
  independent reproduction was found** — this reflects this search's scope and should not be read as a
  clean bill of health on any individual score.
- Approximate download sizes for bge-base-en-v1.5, codesage-small-v2, and nomic-embed-text-v1.5 in the
  candidate table are parameter-count-based estimates, not independently re-verified against a specific
  fastembed packaging, and are marked as such.

---

## Sources

1. BAAI/bge-small-en-v1.5 `config.json` — https://huggingface.co/BAAI/bge-small-en-v1.5/raw/main/config.json
2. BAAI/bge-small-en-v1.5 model card (HuggingFace) — https://huggingface.co/BAAI/bge-small-en-v1.5
3. FastEmbed Supported Models table (Qdrant docs) — https://qdrant.github.io/fastembed/examples/Supported_Models/
4. Nikiema, Djiré, Bonkoungou, Moumoula, Samhi, Kaboré, Klein, Bissyandé, "How Small Transformation Expose the Weakness of Semantic Similarity Measures" (2025) — https://arxiv.org/html/2509.09714v1
5. Li, Deng, Nie, "TokDrift: When LLM Speaks in Subwords but Code Speaks in Grammar" (2025) — https://arxiv.org/html/2510.14972
6. "BM25, SPLADE, and Vector Search Combined" (premai.io) — https://www.premai.io/blog/hybrid-search-for-rag-bm25-splade-and-vector-search-combined/
7. "combining BM25 with embeddings" (firsttoken.beehiiv.com) — https://firsttoken.beehiiv.com/p/hybrid-search-combining-bm25-with-embeddings
8. "Combining Vector and Keyword Retrieval" (bigdataboutique.com) — https://bigdataboutique.com/blog/hybrid-search-explained
9. codesage/codesage-small-v2 model card — https://huggingface.co/codesage/codesage-small-v2 ; Zhang, Ahmad, et al., "Code Representation Learning At Scale," arXiv:2402.01935
10. jinaai/jina-embeddings-v2-base-code model card — https://huggingface.co/jinaai/jina-embeddings-v2-base-code ; Günther et al., arXiv:2310.19923
11. nomic-ai/nomic-embed-code model card — https://huggingface.co/nomic-ai/nomic-embed-code ; Suresh, Reddy, Xu, Nussbaum, Mulyar, Duderstadt, Ji, "CoRNStack," arXiv:2412.01007
12. Qodo/Qodo-Embed-1-1.5B model card — https://huggingface.co/Qodo/Qodo-Embed-1-1.5B
13. StarCoder tokenizer reference — Li et al., "StarCoder: may the source be with you!," arXiv:2305.06161
14. "Reranking with FastEmbed" (Qdrant docs) — https://qdrant.tech/documentation/fastembed/fastembed-rerankers/
15. newtechstudio/bge-reranker-v2-m3-onnx model card (third-party CPU latency claim) — https://huggingface.co/newtechstudio/bge-reranker-v2-m3-onnx
16. "FastEmbed CPU vs GPU: How to Benchmark Latency & Throughput" (markaicode.com) — https://markaicode.com/benchmarks/fastembed-production-benchmark-latency/
17. Snowflake/snowflake-arctic-embed-m-v1.5 model card — https://huggingface.co/Snowflake/snowflake-arctic-embed-m-v1.5
18. nomic-ai/nomic-embed-text-v1.5 model card — https://huggingface.co/nomic-ai/nomic-embed-text-v1.5 ; Nussbaum, Morris, Duderstadt, Mulyar, "Nomic Embed: Training a Reproducible Long Context Text Embedder," arXiv:2402.01613
19. Muennighoff, Tazi, Magne, Reimers, "MTEB: Massive Text Embedding Benchmark" (2022) — https://ar5iv.labs.arxiv.org/abs/2210.07316
20. "On the Robustness of Multilingual Text Embedding Rankings Across Learning Tasks, Languages, and Benchmark Datasets" (2026) — https://arxiv.org/html/2605.31142
21. "HUME: Measuring the Human-Model Performance Gap in Text Embedding Tasks" (2025) — https://arxiv.org/html/2510.10062v1
22. "Finance Massive Text Embedding Benchmark" — https://arxiv.org/abs/2502.10990v2
23. "A Text Embedding Benchmark for Brazilian Portuguese" — http://arxiv.org/abs/2607.04581v1
24. asg017/sqlite-vec GitHub repository (README, sample usage) — https://github.com/asg017/sqlite-vec ; API reference — https://alexgarcia.xyz/sqlite-vec/api-reference.html
25. "ChromaDB InvalidDimensionException: Fix Embedding Dimension Mismatch" (markaicode.com) — https://markaicode.com/errors/chroma-embedding-mismatch-fix/
26. "Pinecone Dimension Mismatch: Complete Fix Guide" (markaicode.com) — https://markaicode.com/errors/pinecone-dimension-mismatch-fix/
27. "When Your Provider Silently Invalidates Your Entire Vector Index" (tianpan.co) — https://tianpan.co/blog/2026-05-07-embedding-model-churn-vector-index-invalidation
28. "Why does switching embedding models silently break my agent's retrieval?" (thehard70.substack.com) — https://thehard70.substack.com/p/why-does-switching-embedding-models

Additional models referenced for context (specs pulled from own model cards, not separately numbered
above): BAAI/bge-base-en-v1.5, BAAI/bge-large-en-v1.5, BAAI/bge-reranker-base — all at
https://huggingface.co/BAAI/ ; FlagOpen/FlagEmbedding GitHub — https://github.com/FlagOpen/FlagEmbedding.

---

## Methodology note

Search queries used (via web_search) covered: FlagEmbedding/BGE official repo instruction-prefix
conventions; BAAI/bge-small-en-v1.5 model card; tokenizer/vocab-size verification; fastembed's
supported-model listing; code-tokenizer vocabulary-coverage literature; text-embedding failure modes
on version numbers/near-duplicate strings; subword fragmentation of camelCase/snake_case identifiers;
CodeSage, jina-embeddings-v2-base-code, Nomic Embed Code, and Qodo-Embed-1 model specs and training
objectives; dense-vs-BM25 rare-token retrieval; bge-reranker CPU latency; MTEB overfitting and
leaderboard-gaming criticism; sqlite-vec dimension-mismatch handling. Primary sources (HF model cards,
config.json files, GitHub repos, arXiv papers) were fetched directly and prioritized over blog
commentary throughout; blog/vendor sources were used only for the practitioner-consensus claims in
Sections 2 and 7, and are explicitly flagged as such rather than presented as measured findings.
Time-boxed to the seven questions in the brief; did not pursue GPU latency, non-English retrieval, or
model fine-tuning paths, none of which were in scope.
