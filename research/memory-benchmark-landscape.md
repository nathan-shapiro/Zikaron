# Memory benchmark landscape — verification and fit against Zikaron

## Brief

Requested by memory-researcher (2026-09-14). Zikaron stores *tribal knowledge* for coding agents —
operationally, facts not learnable by reading the code (build/test gotchas, silently-failing steps,
unsafe APIs, what was already tried). It is explicitly not a codebase-knowledge system. Mechanism:
SQLite per project, hybrid dense+BM25 retrieval with RRF fusion, agent-authored writes
(`remember`/`amend`/`retire`), push of top-5 gists per user turn, and a separate consolidation pass
(grouping + merge) over the journal. The brief: map the public agent-memory benchmark landscape, verify
an unverified name list carried in this corpus (LoCoMo, LongMemEval(-V2), BEAM, HaluMem, LongMemCode,
PersonaMem, LifeBench, AFTER, EvoMemBench, MemoryAgentBench), judge per-benchmark fit for Zikaron
(especially: can it score an end-task outcome vs. only QA accuracy; does it require the system under
test to *decide what to write*; does it touch conflict/staleness/supersession; does it score
abstention), find published critiques of LoCoMo specifically, and summarize how memory-system products
(Mem0, Zep/Graphiti, Letta/MemGPT, A-MEM, LangMem, Memary, Supermemory) report benchmark results and any
known disputes.

## Method

Five rounds of `WebSearch`, one per unverified name plus targeted follow-ups (LoCoMo critique, Mem0/Zep
dispute, product self-reports), followed by `WebFetch` on two arXiv abstract pages (MemoryAgentBench,
LongMemEval) and two critique pages (a GitHub issue, a dev.to post) to check claims against source rather
than snippet. Time-boxed; I did not fetch every PDF in full, only enough to confirm existence, authorship
pointers, scale and task definitions where the search snippet was ambiguous or where a specific number
needed grounding. Where a search snippet was the only evidence and I did not independently open the
source, I say so.

## Part 1 — verifying the unverified list

| Name as carried in FINDINGS | Verified? | What it actually is |
|---|---|---|
| LoCoMo | **Exists.** "Evaluating Very Long-Term Conversational Memory of LLM Agents," arXiv:2402.17753 (Feb 2024). | See Part 2. |
| LongMemEval(-V2) | **LongMemEval exists**; "-V2" **not separately verified** — I found no distinct paper/dataset by that suffixed name, only the single LongMemEval (arXiv:2410.10813, ICLR 2025, GitHub `xiaowu0162/LongMemEval`). Treat "-V2" as unverified/likely a misremembering of a dataset revision, not a separate benchmark. | See Part 2. |
| BEAM | **Exists**, but not as a solo proper noun matching a coding-agent construct: "Beyond a Million Tokens: Benchmarking and Enhancing Long-Term Memory in LLMs," arXiv:2510.27246, ICLR 2026. | See Part 2. |
| HaluMem | **Exists.** "HaluMem: Evaluating Hallucinations in Memory Systems of Agents," arXiv:2511.03506 (Nov 2025), MemTensor/IAAR-Shanghai; GitHub `MemTensor/HaluMem`, HF dataset `IAAR-Shanghai/HaluMem`. | See Part 2. |
| LongMemCode | **Could not find any benchmark by this name.** Searches surfaced LongMemEval, LONGCODEU (arXiv, long-context *code understanding*, not memory), and no "LongMemCode" hit on arXiv, GitHub, or HuggingFace. Likely a conflation of LongMemEval + a code-context benchmark, or a hallucinated name. **Flagging as not found**, per the brief's instruction. |
| PersonaMem | **Exists**, COLM 2025, with a "-v2"/"-v3" lineage that does look real (alphaXiv pages for PersonaMem-v2 and -v3 were found), unlike LongMemEval-V2. Domain: personal-assistant / recommendation, not coding. | See Part 2. |
| LifeBench | **Exists.** "LifeBench: A Benchmark for Long-Horizon Multi-Source Memory," arXiv:2603.03781, GitHub `1754955896/LifeBench`. Note: arXiv id 2603.xxxxx implies a 2026 submission — i.e., this is very recent/possibly not yet peer-reviewed. | See Part 2. |
| AFTER | **Could not find any benchmark by this name.** The closest hits were "From Recall to Forgetting: Benchmarking Long-Term Memory for Personalized Agents" (arXiv:2604.20006) and "ForgetBench" (arXiv:2607.26455) — both about forgetting, neither named AFTER. **Flagging as not found**; possibly a garbled recollection of one of these two forgetting-themed papers. |
| EvoMemBench | **Exists.** "EvoMemBench: Benchmarking Agent Memory from a Self-Evolving Perspective," arXiv:2605.18421, two GitHub mirrors (`kutluege/EvoMemBench`, `DSAIL-Memory/EvoMemBench`). | See Part 2. |
| MemoryAgentBench | **Exists.** "Evaluating Memory in LLM Agents via Incremental Multi-Turn Interactions," arXiv:2507.05257, ICLR 2026, authors include Yuanzhe Hu, Yu Wang, Julian McAuley (UCSD-affiliated based on McAuley's usual affiliation — **not independently confirmed** from the fetched abstract page, which did not print institution). GitHub `HUST-AI-HYZ/MemoryAgentBench`, HF dataset `ai-hyz/MemoryAgentBench`. | See Part 2 and Part 4 (conflict resolution). |

**Bottom line on verification: 8 of 10 named items are real papers/benchmarks (LoCoMo, LongMemEval, BEAM,
HaluMem, PersonaMem, LifeBench, EvoMemBench, MemoryAgentBench); 2 could not be found under the given name
(LongMemCode, AFTER); "LongMemEval-V2" is an unconfirmed variant of a real base benchmark.** None of the
10 evaluate tribal-knowledge-for-coding-agents as Zikaron scopes it; all are conversational,
personal-assistant, or general long-context memory benchmarks. I did not encounter, in any search, a
benchmark purpose-built for "what a coding agent learned by living through a build/test cycle."

## Part 2 — per-benchmark table and Zikaron fit

Format note: fields marked "unverified" reflect information only surfaced in a search snippet, not
confirmed by opening the primary source.

### LoCoMo
- **Full name / year / venue**: "Evaluating Very Long-Term Conversational Memory of LLM Agents." arXiv:2402.17753, Feb 2024.
- **What it measures**: QA, event-summarization and (in the original paper) multimodal dialogue generation over very long synthetic multi-session dialogues with persistent personas.
- **Domain**: conversational (persona-driven roleplay dialogue), not code.
- **Scale**: 50 conversations, ~300 turns / ~9K tokens average, up to 35 sessions, ~200 QA pairs per the search synthesis — **unverified against the primary PDF in this pass**, but consistent across multiple secondary sources.
- **Task format**: QA (single-hop, multi-hop, temporal, open-domain, plus a 5th "adversarial" category meant to test refusal).
- **Memories pre-authored or system-written?**: The dialogue corpus is pre-authored (LLM-human pipeline); the system under test typically indexes/retrieves over it, not decide-what-to-write in Zikaron's sense — there is no analogue of Zikaron's agent judging "new entry / amend / nothing."
- **Licence/availability**: publicly released dataset, widely mirrored (e.g., on GitHub via third-party harnesses).
- **Zikaron fit**: **poor at face value.** It scores retrieval-QA accuracy over a fixed persona-chat corpus, not an end-task outcome, and it never exercises the agent's write-decision (D6/D15) or consolidation (D7/D29). It is the benchmark the brief already suspects is a construct mismatch — that suspicion is corroborated by the validity critiques in Part 3, independent of domain mismatch. **Could not** score end-task outcome; **QA accuracy only**, and per Part 3, even that accuracy figure is contested.

### LongMemEval (LongMemEval-V2 unconfirmed)
- **Full name / year / venue**: "LongMemEval: Benchmarking Chat Assistants on Long-Term Interactive Memory." arXiv:2410.10813, Oct 2024, ICLR 2025. Authors (from the fetched abstract page): Di Wu, Hongwei Wang, Wenhao Yu, Yuwei Zhang, Kai-Wei Chang, Dong Yu — institutions not printed on the page I fetched; Tencent AI Lab / UCLA affiliation is plausible from author names but **unverified** here.
- **What it measures**: five abilities — information extraction, multi-session reasoning, temporal reasoning, knowledge updates, and **abstention**.
- **Domain**: conversational chat-assistant memory.
- **Scale**: 500 curated questions over "freely scalable" chat histories (i.e., the benchmark can synthetically extend context length).
- **Task format**: QA, with a knowledge-updates category that touches conflict resolution.
- **Memories pre-authored or system-written?**: chat histories are the pre-given corpus; the system's job is indexing/retrieval/reading, again not Zikaron's write-decision loop.
- **Licence/availability**: code and benchmark public on GitHub (`xiaowu0162/LongMemEval`), CC BY 4.0 per the fetch.
- **Zikaron fit**: **better than LoCoMo on one axis (abstention is explicitly scored) but still a construct mismatch on domain and on the write-decision.** Its "knowledge updates" category is the closest any of these ten get to testing something like Zikaron's supersession/amend mechanism, but the update is presented as a fact in the corpus, not authored by the system under test — so it tests *reading* an update, not *deciding to write* one. **QA accuracy, not end-task outcome.**

### BEAM
- **Full name / year / venue**: "Beyond a Million Tokens: Benchmarking and Enhancing Long-Term Memory in LLMs." arXiv:2510.27246, ICLR 2026.
- **What it measures**: ten categories including preference following, instruction following, information extraction, knowledge update, multi-session reasoning, summarization, temporal reasoning, event ordering, **abstention**, and **contradiction resolution** — at 1M and 10M token dialogue scale.
- **Domain**: general long-context/conversational; paper also proposes its own memory architecture (LIGHT).
- **Scale**: dialogues up to 10M tokens (synthetically generated/scaled).
- **Task format**: category-specific QA/probes.
- **Memories pre-authored or system-written?**: pre-authored synthetic dialogue; system indexes it.
- **Licence/availability**: paper public on arXiv; code availability not confirmed in this pass.
- **Zikaron fit**: **interesting on paper for the contradiction/abstention axes, but the scale (millions of tokens of chat) and domain (personal-assistant dialogue) are far from tribal-knowledge-for-a-repo.** Also note it is vendor-adjacent coverage (Mem0's own blog wrote it up, per the search results) — treat any comparative numbers quoted by mem0.ai as self-interested framing, not neutral reporting, until checked against the primary paper.

### HaluMem
- **Full name / year / venue**: "HaluMem: Evaluating Hallucinations in Memory Systems of Agents." arXiv:2511.03506, Nov 2025. MemTensor / IAAR-Shanghai.
- **What it measures**: operation-level hallucination across three stages — memory **extraction**, memory **updating**, and memory **question answering** — i.e., it scores the write path's fidelity, not only recall.
- **Domain**: "user-centric, multi-turn human-AI interaction" — conversational, not code.
- **Scale**: HaluMem-Medium and HaluMem-Long, ~15K memory points and ~3.5K questions.
- **Task format**: hallucination/error detection at each of the three stages (fabrication, error, conflict, omission).
- **Memories pre-authored or system-written?**: **This is the one benchmark in the list whose extraction/updating stage is written by the system under test** — closer in shape to Zikaron's write-decision than any of the QA-only benchmarks, because it specifically scores whether the system's *written* memory correctly reflects the source conversation, and whether its *updates* introduce conflicts or omissions.
- **Licence/availability**: dataset and code public (GitHub `MemTensor/HaluMem`, HF `IAAR-Shanghai/HaluMem`).
- **Zikaron fit**: **the most structurally relevant of the ten for testing the write side**, even though its domain is conversational. Its "updating" stage — does the system correctly overwrite/merge without fabricating or dropping information — is conceptually adjacent to Zikaron's D6 write-decision and D29 consolidation-merge, and could plausibly be adapted (methodology, not corpus) to a tribal-knowledge setting. Still QA/hallucination-detection scoring, not end-task outcome.

### PersonaMem (with -v2/-v3 lineage)
- **Full name / year / venue**: PersonaMem, COLM 2025 (per search synthesis, **unverified directly**); alphaXiv pages exist for PersonaMem-v2 (arXiv:2512.06688) and PersonaMem-v3 (arXiv:2608.21381).
- **What it measures**: personalization — factual recall, preference tracking/evolution, reasons behind preference updates, recommendations, generalization.
- **Domain**: personal-assistant / recommendation (family, legal, medical, movies/food/books).
- **Scale**: ~32K-token contexts per user, scaled corpora at 32K/128K/1M entries in later versions.
- **Task format**: multiple-choice QA.
- **Memories pre-authored or system-written?**: pre-authored dialogue corpus.
- **Zikaron fit**: **poor.** This is squarely a personalization/preference benchmark; Zikaron's write policy (open question 14 in FINDINGS) explicitly treats standing preferences as *advisory reference material*, not the directive personalization PersonaMem tests. No code or build/test content.

### LifeBench
- **Full name / year / venue**: "LifeBench: A Benchmark for Long-Horizon Multi-Source Memory." arXiv:2603.03781 — note the 26xx arXiv prefix implies a 2026 submission, i.e. very recent and possibly not yet peer-reviewed.
- **What it measures**: integration of declarative *and* non-declarative (habitual/procedural) memory inferred from fragmented multi-source signals (chats, calendar, notes, SMS, health records).
- **Domain**: personal life-management, not code.
- **Scale/results**: top systems reach 55.2% accuracy (per search synthesis).
- **Zikaron fit**: **poor domain fit**, though the *methodological idea* — memory that must be inferred from fragmented traces rather than stated outright — is philosophically closer to "tribal knowledge learned by living through work" than most QA benchmarks are. Not code-relevant as constructed.

### AFTER
**Could not find any benchmark by this name.** No further entry.

### EvoMemBench
- **Full name / year / venue**: "EvoMemBench: Benchmarking Agent Memory from a Self-Evolving Perspective." arXiv:2605.18421.
- **What it measures**: memory evolution along two axes — scope (in-episode vs. cross-episode) and content (**knowledge-oriented vs. execution-oriented**). The execution-oriented / cross-episode axis is notable: it is the first benchmark surfaced here whose framing (evolving *how to do things*, across episodes) is structurally close to what Zikaron calls tribal knowledge.
- **Domain**: general agent memory, not specifically coding, but not specifically conversational either — the "execution-oriented" content axis implies task/procedure memory, which is the closest conceptual neighbor to Zikaron's "how to build and test" scope in the whole list.
- **Task format**: standardized evaluation protocol comparing memory methods across the four settings; **not confirmed whether it scores end-task outcome or QA-style probes** — this needs a closer read before use.
- **Zikaron fit**: **the most promising lead in this list for adaptation**, on construct alone — worth a closer read (full paper, not abstract) before ruling in or out. Flagged as an open lead, not a verified fit.

### MemoryAgentBench
- **Full name / year / venue**: "Evaluating Memory in LLM Agents via Incremental Multi-Turn Interactions." arXiv:2507.05257, ICLR 2026. Authors (from fetched page): Yuanzhe Hu, Yu Wang, Julian McAuley — institution not printed on the fetched abstract; **not independently confirmed**.
- **What it measures**: four competencies. The search-result framing named them "accurate retrieval, test-time learning, long-range understanding, and conflict resolution"; the *fetched* abstract page (which may reflect a later paper revision — it lists itself as v4, revised June 2026) instead lists "accurate retrieval, test-time learning, long-range understanding, and **selective forgetting**." **This is an internal discrepancy worth flagging rather than silently resolving**: either the paper's four competencies were renamed/reframed across revisions (plausible, given the v4 tag), or one of the two sources mislabeled a competency. Two new datasets are named regardless: **EventQA** and **FactConsolidation** — the latter explicitly "designed to test conflict resolution capabilities, including single-hop and multi-hop difficulty levels."
- **Domain**: general long-context/agent memory; not code-specific. Built by "transform[ing] existing long-context datasets and incorporat[ing] newly constructed datasets" (book-based QA plus new interactive datasets).
- **Scale**: not confirmed in this pass — the fetched abstract text did not print exact QA-pair counts.
- **Task format**: QA/accuracy per competency.
- **Reported numbers** (per search synthesis, unverified against the PDF body): single-hop conflict resolution — GPT-4o-based memory agents reach only ~60% accuracy; multi-hop conflict resolution — all methods score in the single digits, at most 7%. **These are exactly the kind of numbers the brief asked to be quoted precisely with the quantity named** — they are FactConsolidation-dataset accuracy under the paper's own harness, and I have not independently reproduced or read the harness definition, so treat as reported-not-verified.
- **Memories pre-authored or system-written?**: the memory agent under test builds and updates its own memory incrementally as it receives multi-turn interactions — this **is** a decide-what-to-write test, closer to Zikaron's D6/D15/D25 than LoCoMo/LongMemEval/PersonaMem.
- **Licence/availability**: code public (`HUST-AI-HYZ/MemoryAgentBench`), dataset on HF (`ai-hyz/MemoryAgentBench`).
- **Zikaron fit**: **the strongest conflict-resolution match in the list (see Part 4), and the write-decision structure is closer to Zikaron's mechanism than any QA-over-fixed-corpus benchmark.** Domain is still general-purpose, not coding/tribal-knowledge, and task format is accuracy on constructed QA pairs (EventQA, FactConsolidation), not an end-task outcome measure. Worth a full read of the FactConsolidation task definition before deciding whether its update-conflict structure (single-hop vs multi-hop fact overwrite) can be adapted to Zikaron's supersession semantics (D25) even if the corpus itself is unusable.

## Part 3 — LoCoMo validity critiques (verified)

Multiple independent critiques surfaced, converging on the same general theme: **LoCoMo's headline
numbers are far less comparable and far less discriminative than the vendor marketing built on them
implies.**

- A dev.to critique piece (fetched directly): LoCoMo's official evaluation harness sets
  `CATEGORIES_TO_EVALUATE = [1, 2, 3, 4]`, **excluding the 5th "adversarial" category — 446 questions,
  22.5% of the total — where the correct answer is refusal/abstention.** The evaluation prompt itself
  instructs the model "NEVER say 'not specified'... COMMIT AND ANSWER," i.e. the harness actively biases
  against abstention on the very questions built to test it. The critique's own audit found the LLM-judge
  "over-accepting 62.8% of deliberately wrong answers," putting an honest accuracy ceiling around 93.6%.
  Author reports scoring 0.000 discrimination on the excluded adversarial set with a system built
  specifically for calibrated abstention — i.e., LoCoMo as commonly run **cannot see abstention behavior
  at all**, despite having built a category for it.
  Source: https://dev.to/gde03/the-ai-memory-benchmark-everyone-quotes-forbids-saying-i-dont-know-o1n
- A related DEV Community piece ("Critical Flaws in Long-Term Memory Benchmarks," found by search, not
  independently fetched) reports: small per-category sample sizes (10 conversations per category makes
  statistical comparison unreliable); a reported case where "simple filesystem operations achieved 74%
  accuracy on LoCoMo, matching or exceeding sophisticated memory systems" — cited as evidence the
  benchmark under-discriminates between approaches. **Unverified beyond the search snippet** — worth
  reading the primary post before quoting the 74% figure further; it aligns with, but is a separate claim
  from, Letta's own "Is a Filesystem All You Need?" blog post (see Part 4 below), which is a stronger,
  vendor-published version of the same claim.
- A LinkedIn post ("LoCoMo Benchmark Flawed: 64% Wrong Answers Accepted") surfaced in search but was
  **not independently verified** — flagging rather than quoting a number I did not confirm at source.

Net read: LoCoMo's construct-validity problems are (a) domain mismatch for Zikaron (roleplay-persona
chat, not tribal engineering knowledge) — the a priori suspicion in the brief — **and separately** (b) a
now well-documented measurement-validity problem independent of domain: no canonical grading harness,
an abstention category that is excluded by convention, and a lenient LLM-judge. Point (b) means that even
a domain-adapted LoCoMo-style benchmark would need its own harness built carefully, not borrowed.

## Part 4 — conflict resolution / contradiction / staleness coverage

- **MemoryAgentBench** is the clearest hit: "conflict resolution" is one of its four named competencies,
  operationalized via the **FactConsolidation** dataset (single-hop and multi-hop fact-overwrite
  difficulty levels). Reported results (search-sourced, unverified at source): GPT-4o-based agents ~60%
  on single-hop conflict resolution, ≤7% on multi-hop — i.e., current systems are reported to fail badly
  at multi-hop contradiction resolution specifically. This is the one benchmark in the list built to
  probe exactly the mechanism Zikaron's D25 (structural supersession, demote-don't-hide) and D11
  (in-band staleness repair) target, even though its corpus and domain are not tribal-knowledge.
- **LongMemEval**'s "knowledge updates" category and **BEAM**'s "knowledge update" and "contradiction
  resolution" categories are the same idea at lower fidelity — a stated fact changes later in the
  dialogue, and the system must retrieve the current, not stale, value. None of the three test the
  agent *authoring* an update the way Zikaron's `amend`/D26 optimistic-concurrency path does; they test
  reading a corpus that already contains the contradiction.
- **HaluMem**'s "updating" stage scores whether a system-authored memory update introduces
  fabrication/omission/conflict — this is closer to testing the *write* side of staleness repair than
  the read-side tests above, though again in a conversational, not coding, domain.
- No benchmark surveyed tests Zikaron's specific loop — a memory surfaces, is acted on, and fails loudly
  enough that the agent attributes the waste and repairs it in-band (D11) — because that requires an
  interactive coding-agent harness with real tool execution and failure feedback, which none of these ten
  provide.

## Part 5 — abstention coverage

- **LongMemEval** names abstention as one of its five core abilities — the most directly relevant hit,
  and unlike LoCoMo it does not appear (from what I could verify) to systematically exclude the
  abstention category from headline scoring; I did not, however, independently fetch its scoring harness
  to confirm this the way I did for LoCoMo, so treat as a lead not a confirmed advantage.
- **BEAM** also names abstention as one of its ten categories.
- **LoCoMo** nominally has an "adversarial" category meant to test refusal, but Part 3's critique
  establishes that the standard harness both excludes it from the scored categories and instructs models
  against abstention in the prompt — so LoCoMo's abstention coverage is **real in the corpus, defeated in
  the harness**, a distinction worth keeping if Zikaron's own evaluation ever borrows LoCoMo's data
  without its default harness.
- This matters directly for Zikaron because empty retrieval is a valid, non-failure outcome for the
  system (per the brief) — any benchmark or benchmark harness adapted for Zikaron needs to score
  correct-empty-return the way LongMemEval's design intends and LoCoMo's default harness does not.

## Part 6 — how memory-system products report results

- **Mem0 vs. Zep/Graphiti — the one clearly public, documented dispute.** Zep originally published an
  **84%** LoCoMo accuracy claim. Mem0's team publicly alleged three methodology issues: (1) Zep's
  evaluation incorrectly folded Category-5 (adversarial) correct answers into the numerator while
  excluding Category-5 questions from the denominator, inflating the score; (2) Zep used a modified
  system prompt/retrieval template not applied identically to baselines, and published a single run
  versus ten independent runs for baselines; (3) Zep's prompt added timestamp-handling instructions not
  present in the shared benchmark prompt. Mem0's re-evaluation under corrected, standardized conditions
  put Zep's LoCoMo accuracy at **58.44% ± 0.20** — a 25.56-point drop from the original claim. Source:
  https://github.com/getzep/zep-papers/issues/5 (fetched directly).
  Search results also surfaced a further round: more recent vendor blog posts show Zep claiming 94.7% and
  Mem0 claiming 92.5% on LoCoMo, with each vendor now publicly disputing the other's methodology — i.e.
  the dispute did not resolve into a settled number, it recurred at a higher score. **Unverified beyond
  the search synthesis**; I did not independently fetch the newer 94.7%/92.5% claims at source.
- **Letta (MemGPT)** published its own comparison arguing a simple filesystem-based agent scores
  competitively with dedicated memory frameworks on LoCoMo — one search result quoted Letta's own agent
  at 74.0% with GPT-4o-mini and minimal tuning against a stated Mem0 graph-variant figure of 68.5% (blog:
  "Benchmarking AI Agent Memory: Is a Filesystem All You Need?," letta.com). **This is Letta's own
  self-reported comparison**, not a third-party replication, and directly rebuts a Mem0 claim — a second
  documented vendor dispute alongside the Zep/Mem0 one, though I did not fetch the Letta post directly to
  confirm exact wording.
- **A-MEM** (arXiv:2502.12110) reports its own LoCoMo comparison against LoCoMo's original baseline,
  ReadAgent, MemoryBank and MemGPT — self-reported, not third-party. Claims: outperforms baselines with
  non-GPT foundation models across categories, "at least two times better performance" on multi-hop tasks
  for GPT-based models, while using far fewer tokens (~1,200–2,500 vs. ~16,900) than LoCoMo/MemGPT
  baselines via selective top-k retrieval. **Unverified beyond the search snippet** — not independently
  fetched.
- **LangMem, MemoBase, MemoryOS, Nemori** appear in a comparative evaluation cited by search (source not
  independently identified/fetched) alongside A-Mem and Mem0, described as "local, cloud-based, and
  hybrid memory designs" — I could not confirm the primary source of this comparison table in this pass,
  so it is flagged as a lead only.
- **Memary and Supermemory**: **no benchmark results — self-reported or third-party — surfaced in any
  search in this session.** Both appear in the memory-tooling ecosystem in general product searches but I
  found no LoCoMo/LongMemEval/other-benchmark number attributed to either. Flagging as "not found" rather
  than omitting silently, per the brief's instruction.
- **General pattern, worth stating plainly**: essentially every vendor-reported number in this space is
  **tier-3 evidence** — self-reported, on a benchmark (LoCoMo) that Part 3 shows has no canonical grading
  harness, so "SOTA on LoCoMo" is a claim with no fixed meaning across publishers. One synthesis source
  used almost this exact framing ("'run LoCoMo' isn't one fixed procedure... small protocol differences
  compound into large score differences... vendor self-reported numbers are tier 3 until replicated by a
  third party") — I did not independently fetch that source (dreaming.press) to confirm authorship/date,
  but the claim is corroborated by the Zep/Mem0 dispute itself, which is independently verified above.

## Evidence quality summary

- **Directly fetched and confirmed**: the Zep/Mem0 GitHub dispute thread; the dev.to LoCoMo-abstention
  critique; MemoryAgentBench and LongMemEval abstract-page content (with the internal competency-naming
  discrepancy flagged above).
- **Search-snippet only, not independently fetched**: exact scale numbers for LoCoMo, BEAM's code
  availability, A-MEM's comparative numbers, the Letta blog's exact figures, the 74%-filesystem claim's
  primary source, LifeBench's 55.2% figure, HaluMem's exact dataset composition beyond what's stated
  above, and all "further round" Zep 94.7%/Mem0 92.5% claims.
- **Not found at all**: LongMemCode, AFTER, any benchmark result for Memary or Supermemory.

## Open questions / leads for the researcher

1. **EvoMemBench** (arXiv:2605.18421) is the single most promising construct match found — its
   "execution-oriented, cross-episode" axis is conceptually close to tribal knowledge. Needs a full read
   of the paper body (not just abstract) to check task format (QA vs. end-task) and whether its
   methodology, not corpus, could be adapted to a coding-agent harness.
2. **MemoryAgentBench's FactConsolidation** dataset (single/multi-hop conflict resolution) is the closest
   existing instrument to Zikaron's supersession mechanism (D25) and worth a full read to see whether its
   task structure — not its general-domain corpus — could be reused to construct a Zikaron-specific
   contradiction-resolution eval.
3. **No benchmark surveyed measures end-task coding-agent outcome** (e.g., "agent completes the build
   correctly because it recalled the env-var gotcha") as opposed to QA/recall accuracy. This confirms
   D14's stance (end-to-end task-benefit evaluation stoved until an implementation exists) rather than
   surfacing a shortcut around it — nothing here substitutes for a purpose-built, real-repository
   evaluation of the kind open question 9 already calls for.
4. If any LoCoMo-adjacent benchmark is ever adapted for Zikaron, Part 3's finding that the harness (not
   just the corpus) determines the abstention/discrimination properties means the harness must be
   rebuilt, not borrowed by pointing at LoCoMo's GitHub repo.
5. Memary and Supermemory's absence from every search result here (no benchmark, no comparative number)
   is itself worth noting to the researcher as a gap, not assumed to mean they lack one — a more targeted
   search of their own docs/GitHub repos was out of scope for this timeboxed pass.

## Sources

1. LoCoMo — "Evaluating Very Long-Term Conversational Memory of LLM Agents," arXiv:2402.17753 (Feb 2024) — https://arxiv.org/abs/2402.17753
2. LongMemEval — "Benchmarking Chat Assistants on Long-Term Interactive Memory," arXiv:2410.10813 (Oct 2024, ICLR 2025) — https://arxiv.org/abs/2410.10813 ; code: https://github.com/xiaowu0162/LongMemEval
3. BEAM — "Beyond a Million Tokens: Benchmarking and Enhancing Long-Term Memory in LLMs," arXiv:2510.27246 (ICLR 2026) — https://arxiv.org/pdf/2510.27246
4. HaluMem — "Evaluating Hallucinations in Memory Systems of Agents," arXiv:2511.03506 (Nov 2025) — https://arxiv.org/abs/2511.03506 ; code: https://github.com/MemTensor/HaluMem ; data: https://huggingface.co/datasets/IAAR-Shanghai/HaluMem
5. PersonaMem-v2 — alphaXiv, arXiv:2512.06688 — https://www.alphaxiv.org/abs/2512.06688
6. PersonaMem-v3 — arXiv:2608.21381 — https://arxiv.org/html/2608.21381
7. LifeBench — "A Benchmark for Long-Horizon Multi-Source Memory," arXiv:2603.03781 — https://arxiv.org/abs/2603.03781 ; code: https://github.com/1754955896/LifeBench
8. EvoMemBench — "Benchmarking Agent Memory from a Self-Evolving Perspective," arXiv:2605.18421 — https://arxiv.org/abs/2605.18421 ; code: https://github.com/kutluege/EvoMemBench, https://github.com/DSAIL-Memory/EvoMemBench
9. MemoryAgentBench — "Evaluating Memory in LLM Agents via Incremental Multi-Turn Interactions," arXiv:2507.05257 (ICLR 2026) — https://arxiv.org/abs/2507.05257 ; code: https://github.com/HUST-AI-HYZ/MemoryAgentBench ; data: https://huggingface.co/datasets/ai-hyz/MemoryAgentBench
10. LoCoMo abstention/harness critique — "The AI-memory benchmark everyone quotes forbids saying 'I don't know'" — https://dev.to/gde03/the-ai-memory-benchmark-everyone-quotes-forbids-saying-i-dont-know-o1n
11. "Critical Flaws in Long-Term Memory Benchmarks: Addressing Unreliable and Uninterpretable Results" — https://dev.to/valesys/critical-flaws-in-long-term-memory-benchmarks-addressing-unreliable-and-uninterpretable-results-1o05 (search-snippet only, not independently fetched)
12. Zep/Mem0 LoCoMo dispute thread — "Revisiting Zep's 84% LoCoMo Claim: Corrected Evaluation & 58.44% Accuracy," GitHub issue — https://github.com/getzep/zep-papers/issues/5 (fetched directly)
13. Letta — "Benchmarking AI Agent Memory: Is a Filesystem All You Need?" — https://www.letta.com/blog/benchmarking-ai-agent-memory/ (search-snippet only)
14. A-MEM — "Agentic Memory for LLM Agents," arXiv:2502.12110 — https://arxiv.org/pdf/2502.12110 (search-snippet only)
15. Mem0 — "LoCoMo vs. LongMemEval vs. BEAM: The 2026 AI Memory Benchmark Guide" — https://mem0.ai/blog/ai-memory-benchmarks-in-2026 (vendor source, self-interested framing; search-snippet only)
16. Mem0 — "State of AI Agent Memory 2026: Benchmarks & Trends Report" — https://mem0.ai/blog/state-of-ai-agent-memory-2026 (vendor source; search-snippet only)
17. "How to Read an Agent-Memory Benchmark: The LoCoMo and LongMemEval Number Wars" — https://dreaming.press/posts/how-to-read-an-agent-memory-benchmark.html (search-snippet only, not independently fetched)
18. LONGCODEU — "Benchmarking Long-Context Language Models on Long Code Understanding," arXiv:2503.04359 — https://arxiv.org/pdf/2503.04359 (found while searching for "LongMemCode"; distinct benchmark, code-domain but not memory-focused)
19. "From Recall to Forgetting: Benchmarking Long-Term Memory for Personalized Agents," arXiv:2604.20006 — https://arxiv.org/abs/2604.20006 (found while searching for "AFTER"; not the same benchmark)
20. ForgetBench — arXiv:2607.26455 — https://arxiv.org/html/2607.26455 (found while searching for "AFTER"; not the same benchmark)
