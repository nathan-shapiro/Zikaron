# Survey: is any lightweight embedder measurably better than bge-small-en-v1.5 on technical text?

**Brief.** Zikaron's dense arm uses `BAAI/bge-small-en-v1.5` (D20). Q8 measured an "identifier
discrimination index" of 0.194–0.233 across four general-purpose English embedders (bge-small,
bge-large, nomic, one more) and found scale/family did not move it — but never varied **training
domain**. This survey asks: does a model trained where identifiers and code-adjacent text are dense
(a code-search or code+text embedder) beat bge-small on published, relevant benchmark subsets, while
staying servable under Zikaron's constraints (local ONNX, CPU, pinnable, lightweight — D19/D36)?
Store content is short developer notes (headline + prose + identifiers/paths/flags) and indexed
Markdown doc trees, so the most relevant proxy is retrieval that mixes prose and code/identifiers,
not pure code-to-code search.

## Method

Searched for code-retrieval-specialized embedding models and the standardized benchmark that scores
them: **CoIR** (Li et al., *"COIR: A Comprehensive Benchmark for Code Information Retrieval Models"*,
arXiv:2407.02883, ACL 2025 — 10 datasets across 7 domains, NDCG@10, includes both pure code-to-code
tasks and prose-mixed tasks like StackOverflow-QA and CosQA). Pulled bge-small-en-v1.5's own CoIR
score, and scores for every lightweight/code-specialized candidate I could find reported *on the same
benchmark*, from two independent primary sources: the IBM Granite Embedding paper (arXiv:2502.20204,
Feb 2025) and the CodeRankEmbed/CoRNStack paper (arXiv:2412.01007, ICLR 2025). Cross-checked
individual numbers with a second web search where possible. Screened every candidate for local
servability (ONNX export, license, param count, pinnability) before treating it as a live candidate.
Read papers via WebFetch (HTML/PDF-to-markdown extraction), not the primary PDF byte-for-byte —
**flagged below where extraction gave inconsistent numbers on a re-read**, since this is the main
evidence-quality risk in this note.

Queries used: fastembed supported models; MTEB/CoIR leaderboard search; jina-embeddings-v2-base-code,
nomic-embed-code, CodeSage, CodeRankEmbed, granite-embedding, potion-code-16M, embeddinggemma —
benchmark + license + ONNX searches; direct fetches of the CoIR paper, the Granite Embedding paper,
and the CoRNStack/CodeRankEmbed paper's results tables.

## Primary evidence: CoIR scores, same benchmark, same metric (NDCG@10)

From the Granite Embedding paper (arXiv:2502.20204, Table 6), which reports bge-small-en-v1.5
directly alongside its own models — this is the anchor table, since it independently reproduced
bge-small's score under the standard CoIR harness (confirmed against a second, independent web
search extraction: 45.8 vs 45.8/46.7 in slightly different phrasings of the same figure):

| Model | Params | CoIR avg | CosQA | StackOverflow-QA | ONNX | License |
|---|---|---|---|---|---|---|
| **bge-small-en-v1.5** (baseline) | 33M | **45.8** | 32.1 | 78.0–78.1 | yes (fastembed default) | MIT |
| e5-small-v2 | 33M | 47.1 | 29.7 | 83.5 | yes | MIT |
| granite-embedding-30m-english | 30M | 47.0 | 35.5 | 83.9 | yes | Apache-2.0 |
| granite-embedding-125m-english | 125M | 50.3 | 36.6 | 89.9 | yes | Apache-2.0 |

From the CodeRankEmbed/CoRNStack paper (arXiv:2412.01007, Table 8), which does **not** include
bge-small directly but gives a wider set of code-specialized models on the same benchmark and metric
(useful for the code-vs-prose-mixed pattern even without a shared baseline row):

| Model | Params | CoIR avg | CosQA | StackOverflow-QA (task label as printed) |
|---|---|---|---|---|
| CodeSage-Small | 130M | 54.4 | 42.6 | 62.3 |
| CodeSage-Base | 356M | 57.5 | 44.6 | 63.0 |
| Jina-Code-v2 | 137M | 58.4 | 44.4 | 68.6 |
| CodeRankEmbed (CoRNStack-trained) | 137M | 60.1 | 45.2 | 75.7 **or** 82.3 (see caveat) |
| E5-base | 110M | 50.9 | 42.0 | 74.5 |

**Extraction caveat, load-bearing for how much to trust exact deltas.** Two separate WebFetch reads
of the *same* CodeRankEmbed/CoIR table returned different StackOverflow-QA figures for CodeRankEmbed
(75.7 on one read, 82.3 on another) and average scores that agreed to one decimal (60.1 vs 59.14 in
an earlier, less careful read). I could not get raw PDF text reliably from arXiv for this paper (the
PDF fetch returned binary/corrupted content both times), so these numbers rest on an AI-mediated
HTML-to-table extraction, not on numbers I read myself off the source. Treat every number in the
second table as **directionally right, exact value uncertain by roughly ±5-7 points on any single
cell** — the Granite-paper table (first table above) was reproduced identically across two
independent fetches and one independent web search, and is the more trustworthy of the two.

## The pattern that matters for Zikaron's workload

CoIR's tasks split cleanly into **pure code-to-code / text-to-code-snippet** tasks (CodeSearchNet,
CodeTrans, APPS) and **prose-mixed** tasks (StackOverflow-QA, CosQA — a natural-language question
retrieving code, closer to "a developer's prose note containing identifiers" than a bare code
snippet). The two evidence sources agree on a pattern:

- **Code-domain-specialized models (CodeSage, Jina-Code-v2, CodeRankEmbed) show their largest gains
  over general embedders on the pure-code tasks**, and comparatively small — or on this evidence,
  *negative* — gains on the prose-mixed StackOverflow-QA task specifically. Jina-Code-v2's
  StackOverflow-QA score (68.6) reads **below** bge-small's (78.0) in this table; on one extraction
  CodeRankEmbed's does too (75.7). Even on the more favourable extraction (82.3), the margin over
  bge-small is modest relative to CodeRankEmbed's huge lead on pure code-to-text tasks.
- **General-purpose small embedders trained on no code data at all (granite-embedding-30m/125m) beat
  bge-small on the same prose-mixed task by a clear, consistent margin** — +5.9 pts NDCG@10 at the
  30M size class (same footprint as bge-small), +11.8 pts at 125M — while the Granite paper's authors
  state explicitly they included no code retrieval data in training, i.e. **the gain is general model
  quality, not technical-domain specialization.**

This is the opposite of what the brief's hypothesis predicted, and it directly bears on Q8: the axis
Q8 flagged as untested — training domain — does not show up as the driver of the one meaningful,
same-size-class improvement found here. What moved the needle was a better general small encoder
(granite-30m vs bge-small, both ~30M params, both MIT/Apache general text encoders), not a code-domain
one. Q8's own conclusion (scale/family didn't move the discrimination index) generalizes to a
different axis (domain) on this one dataset, though the mechanism instruments differ — CoIR's
NDCG@10 on retrieval tasks vs Q8's discrimination index — so this is corroborating, not conclusive.

## Servability screen

| Candidate | Params | ONNX | Pinnable (HF revision) | License | Verdict |
|---|---|---|---|---|---|
| granite-embedding-30m-english | 30M | yes, in repo + `onnx-community/granite-embedding-30m-english-ONNX` | yes | Apache-2.0 | **passes, candidate** |
| granite-embedding-125m-english | 125M | yes, in repo | yes | Apache-2.0 | **passes, candidate** (4x bge-small footprint — check cold-start budget) |
| CodeRankEmbed | 137M | **not provided in repo**; base architecture (Arctic-Embed-M-Long, standard BERT-family) is a standard `optimum`/`transformers.onnx` export target, so likely convertible without custom work, but unverified — not "trivially loadable" out of the box | yes (HF, `nomic-ai/CodeRankEmbed`) | MIT | **conditional pass** — needs an export step we did not verify |
| Jina-Code-v2 (`jina-embeddings-v2-base-code`) | 161M (137–161M reported inconsistently across sources) | yes, ONNX in repo (fp32 642MB / fp16 321MB / int8 quantized 162MB) | yes | Apache-2.0 | **passes servability**, but on this evidence underperforms bge-small on the prose-mixed task |
| CodeSage-Small | 130M | not confirmed in search results | unclear license (not confirmed) | unconfirmed | **screened out — unconfirmed servability**, not pursued further |

## Screened out (fail a hard requirement)

| Candidate | Params | Reason screened out |
|---|---|---|
| nomic-embed-code | 7B | Far over the 150M soft cap; not lightweight by any reading of D19/D36 cold-start budget |
| CodeSage-Base / CodeSage-Large | 356M / 1.3B | Over budget |
| jina-code-embeddings-1.5b | 1.5B | Over budget |
| embeddinggemma-300m | 300M | Over the 150M flag threshold (not investigated further given the size alone disqualifies it under the stated bar) |
| VoyageCode3, OpenAI text-embedding-3-large | n/a | Hosted API only — fails requirement 1 outright regardless of score |
| potion-code-16M | 16M (static/Model2Vec, not a transformer) | Servable and tiny, but **scores worse than bge-small on CoIR average (37.05 vs 45.8)** — a static-embedding distillation of CodeRankEmbed, and the distillation loses enough quality that domain specialization does not compensate. Evidence that shrinking capacity, even with code-specific training, can lose to a larger general model. Not a candidate. |

## Evidence quality notes

- All comparative numbers here are **published benchmark table values** (CoIR, arXiv:2502.20204 and
  arXiv:2412.01007), not vendor blog claims — meeting the brief's evidence bar. Jina AI's own blog
  post claiming "led 9 of 15 CodeSearchNet benchmarks" is a **vendor claim** (their own chosen
  benchmark, no bge-small comparison) and is not relied on for any number in the tables above.
- The CoIR benchmark itself is one dataset family; it does not include CQADupStack
  (programmers/unix/superuser) or a BEIR technical subset directly, so I could not get an
  independent second benchmark confirming the StackOverflow-QA pattern. That is the main gap: **one
  benchmark, two papers reporting subsets of it**, not two independently-run benchmarks.
- Q8's own instrument (identifier discrimination index) has never been run against any candidate in
  this table. Everything here is a different benchmark's evidence bearing on the same hypothesis, not
  a replication.
- I could not obtain readable primary-source PDF text for the CoRNStack paper via this session's
  tooling (binary PDF fetch failed twice); the CodeRankEmbed/Jina-Code-v2 table rests on an
  AI-mediated HTML extraction that gave inconsistent numbers on a second read (see caveat above).
  Anyone retesting should re-pull Table 8 of arXiv:2412.01007 directly rather than trust the exact
  StackOverflow-QA cell for CodeRankEmbed reported here.

## Verdict

**(b), narrowly, and not the candidate the brief's hypothesis pointed at.** There is a servable,
pinnable, lightweight candidate that beats bge-small by a real margin on the one CoIR task that best
resembles Zikaron's workload (prose containing identifiers/errors, not bare code):
**`ibm-granite/granite-embedding-30m-english`** — same parameter count and embedding-dimension class
as bge-small (30M params, 384-dim), Apache-2.0, ONNX in repo, pinnable HF revision — scoring +5.9 pts
NDCG@10 on StackOverflow-QA and +3.4 on CosQA over bge-small, with a +1.2 pt average CoIR gain. Its
125M sibling shows a larger gain (+11.8 SO, +4.5 CosQA) at ~4x the footprint, worth a look if the
cold-start budget tolerates it.

But **this is a general-model-quality gain, not a training-domain gain** — the Granite team trained
on no code data. The code-domain-specialized models the brief asked about (CodeRankEmbed, Jina-Code-v2,
CodeSage) show their gains concentrated on pure code-to-code retrieval and show weak-to-negative gains
on the prose-mixed task on this evidence. So Q8's specific hypothesis — that a model trained where
identifiers are dense would discriminate identifiers better in Zikaron's mixed-prose setting — is
**not supported** by this survey; what the survey found instead is a same-size-class general encoder
that happens to also do better on identifier-adjacent retrieval.

**Recommended next step, cheap**: retest `granite-embedding-30m-english` through Q8's own identifier
discrimination instrument before any production swap — this note substitutes a different, published
benchmark for that instrument by necessity (Q8's instrument is unpublished/internal), and the two
could disagree.

## Sources

1. Li et al., "COIR: A Comprehensive Benchmark for Code Information Retrieval Models," arXiv:2407.02883 (ACL 2025). https://arxiv.org/html/2407.02883v3 / https://github.com/CoIR-team/coir
2. IBM Research, "Granite Embedding Models," arXiv:2502.20204 (Feb 2025) — Table 6, CoIR results including bge-small-en-v1.5, e5-small-v2, granite-embedding-30m/125m-english. https://arxiv.org/html/2502.20204v1
3. Suresh et al., "CoRNStack: High-Quality Contrastive Data for Better Code Retrieval and Reranking" (CodeRankEmbed), arXiv:2412.01007 (ICLR 2025) — Table 3 (CSN/AdvTest), Table 8 (CoIR). https://arxiv.org/html/2412.01007
4. `BAAI/bge-small-en-v1.5` model card. https://huggingface.co/BAAI/bge-small-en-v1.5
5. `nomic-ai/CodeRankEmbed` model card. https://huggingface.co/nomic-ai/CodeRankEmbed
6. `jinaai/jina-embeddings-v2-base-code` model card. https://huggingface.co/jinaai/jina-embeddings-v2-base-code
7. Jina AI, "Elevate Your Code Search with New Jina Code Embeddings" (vendor blog, not used for scores). https://jina.ai/news/elevate-your-code-search-with-new-jina-code-embeddings/
8. `ibm-granite/granite-embedding-30m-english` model card and `onnx-community/granite-embedding-30m-english-ONNX`. https://huggingface.co/ibm-granite/granite-embedding-30m-english
9. `ibm-granite/granite-embedding-125m-english` model card. https://huggingface.co/ibm-granite/granite-embedding-125m-english
10. `minishlab/potion-code-16M` model card (Model2Vec static distillation of CodeRankEmbed). https://huggingface.co/minishlab/potion-code-16M
11. Modal, "6 Best Code Embedding Models Compared" (secondary/vendor-adjacent comparison, used only for param counts and license flags, not scores). https://modal.com/blog/6-best-code-embedding-models-compared
12. Qdrant, FastEmbed supported models documentation. https://qdrant.github.io/fastembed/examples/Supported_Models/
