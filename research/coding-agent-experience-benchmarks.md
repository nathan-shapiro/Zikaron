# Research note: substrates for a cross-task-memory benchmark for coding agents

## Brief (as given)

Zikaron stores tribal knowledge a coding-agent project accumulates by being lived through — build/test
procedure, silent failure modes, env vars, dead ends — explicitly *not* a repo map or symbol graph
("could you learn this by reading the code? If yes, it is out of scope"). Conversational memory
benchmarks (LoCoMo, LongMemEval) are a construct mismatch. Hypothesis: the right shape is a *derived
protocol on a public coding-agent substrate* — take a benchmark whose tasks are grouped by repository,
order them, run sequentially, and measure whether an agent that accumulated memory from earlier tasks
does better on later ones. Question: does this already exist, and what substrate would support it?
Required: (A) prior art on experiential/cross-task memory, with exact protocol construction; (B) the
SWE-bench family as substrate, especially per-repo instance density; (C) environment-setup/build-test
benchmarks as the purest tribal-knowledge proxy; (D) any published "memory helps a coding agent" result,
including negative ones; (E) a verdict on 2–3 substrates to build on.

## Method

Five rounds of web search (~16 queries) covering: named prior-art systems (ExpeL, AWM, Reflexion,
Voyager, ExpeRepair, SWE-Exp, AgentKB, Memp, AutoGuide, Agent-Pro, CodeAct, ReasoningBank); the SWE-bench
family (Verified per-repo counts, SWE-smith, SWE-Gym, Multi-SWE-bench, SWE-bench-Live, SWE-bench
Multimodal, SWE-Lancer, RepoBench, RepoCod, Commit0); environment-setup benchmarks (SetupBench,
Installamatic, ExecutionAgent, EnvBench); "memory helps SWE agent" ablations and negative results
(CTIM-Rover); and multi-bug/chained-maintenance benchmarks (ChainSWE, SWE-Chain, SWE-EVO), which turned
out to be the closest existing match to the brief's hypothesis. WebFetch was used to try to pull
methodology detail beyond abstracts for ChainSWE and SWE-Exp; both attempts returned only
abstract-level summaries (PDF extraction did not surface full methods text), so protocol mechanics for
those two are marked **inferred from secondary description, not independently verified against full
text** below. All other claims are from search-result synthesis of abstracts/pages, which for arXiv
abstracts is close to primary-source strength but is still not a full-text read; flagged per-claim.

## A. Prior art on experiential / cross-task memory

None of the systems below implement exactly the brief's protocol (sequential runs on tasks grouped by
one repository, comparing an agent with vs without accumulated memory from earlier tasks in that same
repository). The closest matches are ChainSWE/SWE-Chain (section A.11) and the CTIM-Rover repo-level
condition (A.10), both found via the "multi-bug maintenance" search thread rather than the "experiential
learning" thread — worth flagging since the brief's framing (§Q) predicted the "experiential learning"
literature would contain the protocol, but the closer analogue turned up adjacent to SWE-bench itself.

1. **ExpeL** ([2308.10144](https://arxiv.org/abs/2308.10144), Zhao et al., AAAI 2024). Substrate:
   HotpotQA (QA/tool-use) and ALFWorld (embodied text games) — **not code**. Protocol: agent gathers
   experience over a fixed *training* task set via trial-and-error (multiple attempts per task allowed),
   extracts natural-language "insights," then evaluates on a **held-out test set**; insights and/or
   retrieved successful trajectories are given as few-shot context at test time. No-memory baseline =
   plain ReAct agent. Reported: gains attributed jointly to insights and trajectory retrieval; ablating to
   insights-only vs retrieval-only splits differently by environment (36%/31% HotpotQA vs 50%/55%
   ALFWorld — exact metric not confirmed, likely relative contribution to score). Not sequential-online;
   train/test split over *tasks*, not over time within one environment instance.

2. **Agent Workflow Memory (AWM)** ([2409.07429](https://arxiv.org/abs/2409.07429), Wang, Mao, Fried,
   Neubig, 2024). Substrate: Mind2Web and WebArena — web navigation, 1000+ tasks across 200+ domains,
   not code. Protocol: two modes — **offline** (induce workflows from a training split before test) and
   **online** (induce workflows from test queries themselves, on the fly, i.e. genuinely sequential
   within the eval run — the online mode is the one structurally closest to Zikaron's write-as-you-go
   model). No-memory baseline = vanilla agent with no workflow memory. Reported: +24.6% relative success
   rate on Mind2Web, +51.1% relative on WebArena, plus fewer steps to success. The online variant is
   explicitly framed as building compounding, increasingly complex workflows over the course of a run —
   this is the clearest existing precedent for "accumulate across tasks, reuse on later ones," but on web
   tasks, not one repository's build/test tribal knowledge.

3. **Reflexion** ([2303.11366](https://arxiv.org/abs/2303.11366), Shinn et al., NeurIPS 2023). Substrate:
   HumanEval (code), AlfWorld, HotpotQA, plus a new LeetcodeHardGym (40 hard LeetCode problems, 19
   languages). Protocol: **within-task** multi-trial self-reflection (episodic memory buffer reset per
   task, not carried across distinct tasks) — this is trial-and-error on *the same* problem, not transfer
   across a benchmark's task set, so it does not match the brief's cross-task shape despite being
   memory-and-code. Reported: 91% pass@1 on HumanEval vs GPT-4's 80% baseline reported in the paper.

4. **Voyager** ([2305.16291](https://arxiv.org/abs/2305.16291), 2023). Substrate: Minecraft (embodied,
   not code-as-artifact, though its skills are executable JavaScript programs). Protocol: continual
   online skill acquisition within one long-running episode; skill library persists and composes across
   an open-ended task stream — the strongest "accumulate and reuse, unsupervised, no train/test split"
   precedent, but the domain is a game world, not a software repository, and there is no notion of
   distinct discrete "tasks" being scored independently pre/post memory. Reported: 3.3x more unique items,
   2.3x longer distances, unlocks tech-tree milestones up to 15.3x faster than prior SOTA; also
   demonstrated skill-library transfer into a *fresh* Minecraft world for novel tasks.

5. **ExpeRepair** ([2506.10484](https://arxiv.org/abs/2506.10484), "EXPEREPAIR: Dual-Memory Enhanced
   LLM-based Repository-Level Program Repair"). Substrate: repository-level program repair (SWE-bench
   family, per title/topic — exact instance count and split not confirmed by primary text in this pass).
   Mechanism: stores successful repair cases from past trajectories, retrieves similar ones as few-shot
   references for new issues, and separately appends LLM-summarized general repair insights. This is
   architecturally close to what a Zikaron-style memory would do for build/test tribal knowledge, but
   applied to bug-fix trajectories rather than environment setup. Exact train/test protocol **not
   verified** — flagged for follow-up if this becomes a candidate substrate.

6. **SWE-Exp** ([2507.23361](https://arxiv.org/abs/2507.23361), 2025). Substrate: SWE-bench Verified (500
   Python instances, 12 repos). Mechanism: multi-faceted "experience bank" distilled from prior agent
   trajectories (both successes and failures), captured at multiple levels from high-level problem
   comprehension down to specific code edits, explicitly framed against a "memoryless explorer" baseline
   (agents that treat every issue independently). Reported: **73.0% pass@1 on SWE-bench Verified with
   Claude 4 Sonnet**, stated as outperforming prior frameworks. **Not verified from primary text**:
   whether the experience bank is built from a held-out training split of SWE-bench-family issues or
   accumulates online within the same 500-instance eval pass (this is exactly the detail the brief most
   wants, and this pass could not confirm it — WebFetch on the abstract/PDF returned no methods-section
   detail). Flagged for a follow-up full-text read before relying on this number.

7. **AgentKB** ([2507.06229](https://arxiv.org/abs/2507.06229), 2025). Substrate: cross-framework,
   cross-domain — GAIA, Humanity's Last Exam, GPQA, and SWE-bench simultaneously; the point of the paper
   is that experience is shared *across* domains and agent frameworks, not accumulated per-repository.
   Mechanism: hierarchical experience store with a "Reason-Retrieve-Refine" pipeline and a "disagreement
   gate" to avoid retrieved knowledge disrupting reasoning. Reported: smolagents +18.7pp at pass@3
   (55.2%→73.9%) on its own suite; **OpenHands on SWE-bench improved pass@1 24.3%→28.3% (+4.0pp)** with
   Agent KB — this is one of the few numbers in this search that isolates a memory-on/off delta on
   SWE-bench specifically for a real open-source harness (OpenHands), and is worth citing as a positive
   result in section D.

8. **Memp** ([2508.06433](https://arxiv.org/abs/2508.06433), 2025). General procedural-memory framework
   (build/retrieval/update strategies for distilling trajectories into step-by-step instructions and
   higher-level script abstractions); substrate and exact numbers not captured in this pass — general
   agent tasks, not confirmed code-specific.

9. **AutoGuide** (NeurIPS 2024, [proceedings link](https://proceedings.neurips.cc/paper_files/paper/2024/file/d8efbb5dd415974eb095c3f06bff1f48-Paper-Conference.pdf)).
   Derives "conditional guidelines" from offline trajectories as context-aware prompts; general
   web/decision-making agent framework, not code-specific per available summary.

10. **CTIM-Rover** ([2505.23422](https://arxiv.org/abs/2505.23422), REALM @ ACL 2025) — **the one clear
    negative result found in this search, and the closest existing thing to a controlled repo-scoped
    memory experiment.** Built on AutoCodeRover; adds a "Cross-Task-Instance Memory" (CTIM) with both a
    general-purpose store and an explicitly **per-repository** store, inspired by ExpeL. Evaluated on a
    **45-issue stratified subset of SWE-bench Verified**. Finding: every CTIM-Rover memory configuration
    **matched or trailed** the plain AutoCodeRover baseline; the memory-only configuration **dropped
    resolution from 42% to 31%**, with noisy CTIM items blamed for degrading initial repository
    exploration. This is a directly citable negative result for section D and a methodological warning:
    a repo-scoped experience store can *hurt* if retrieval surfaces noise into exploration-stage
    decisions — relevant to Zikaron's push-vs-pull and gist-triage design (open questions 1–2 in
    FINDINGS.md).

11. **ChainSWE** ([2607.02606](https://arxiv.org/abs/2607.02606)) and its sibling **SWE-Chain**
    ([2605.14415](https://arxiv.org/abs/2605.14415v1), package-upgrade chains) — **the closest existing
    match to the brief's hypothesis, though framed as a maintenance-burden benchmark, not a memory
    benchmark.** ChainSWE mines **304 issues across 54 Python projects from six SWE-bench-family
    datasets** into **chronological chains of dependent issues within one repository** — explicitly
    contrasting against standard SWE-bench practice, where "the repository is reset, the codebase is
    re-read, and a single self-contained issue is graded in isolation." Two conditions compared: a
    **no-memory baseline** (each issue evaluated independently, no context from prior fixes in the chain)
    versus a **memory-carrying condition** (agent retains information/code changes from earlier fixes in
    the same chain). Reported: performance **drops by up to 70%** as chain length increases (this reads
    as "later, cumulatively-dependent issues are harder," not directly "memory helps" — the paper's
    framing appears to be diagnostic/stress-testing rather than proposing a memory fix; **the precise
    mechanics of chain construction and what exactly counts as "memory" carried forward were not
    confirmed from primary text** in this pass, flagged as inferred from a secondary WebFetch summary).
    This is the dataset shape Zikaron's protocol wants — repo-grouped, chronologically ordered, multiple
    tasks per repo, explicit memory-on/off arms — but its published framing is about maintenance
    difficulty, not about validating a memory *system*. Reusing its chain construction methodology
    (mining chronological dependent-issue chains from SWE-bench-family data, 54 repos, 304 issues) is
    plausibly the single most actionable lead in this brief. **SWE-EVO** ([2512.18470](https://arxiv.org/pdf/2512.18470))
    turned up adjacent — "long-horizon software evolution scenarios" — and **Live-SWE-agent**
    ([2511.13646](https://arxiv.org/pdf/2511.13646), "Can Software Engineering Agents Self-Evolve on the
    Fly?") also turned up adjacent; neither was read past the title/snippet level, flagged as leads only.

12. **CodeAct** ([2402.01030](https://arxiv.org/abs/2402.01030)) and **Agent-Pro**
    ([2402.17574](https://arxiv.org/abs/2402.17574)) were checked per the brief's list. CodeAct is an
    *action-space* design (executable Python as the unified action format, +up to 20% success rate vs
    alternatives across 17 LLMs, CodeActInstruct dataset of 7k interactions) — not a memory mechanism, and
    not relevant to this brief beyond being infrastructure several memory papers build on. Agent-Pro does
    policy-level (not action-level) reflection over interactive experience in games (Texas Hold'em, etc.);
    general-agent, not code, not directly relevant.

## B. The SWE-bench family as substrate

| Benchmark | Size | Repo distribution | Chronology | Licence/access | Harness notes |
|---|---|---|---|---|---|
| **SWE-bench** (orig.) | 2,294 instances | 12 Python repos | Issue/PR dates present in metadata (not confirmed used for ordering by the benchmark itself) | Public, MIT-adjacent (SWE-bench org) | Per-instance Docker container, reset per instance — [arXiv 2310.06770](https://arxiv.org/abs/2310.06770) |
| **SWE-bench Verified** | 500 (human-filtered subset) | **12 repos**, per-repo counts **confirmed**: django/django **231**, sympy/sympy **75**, sphinx-doc/sphinx **44**, matplotlib/matplotlib **34**, scikit-learn/scikit-learn **32**, astropy/astropy **22**, pallets/flask **1** (smallest observed); remaining repos not individually confirmed in this pass | Not confirmed as chronologically orderable by design, but each instance's base commit implies an order | OpenAI + SWE-bench collaboration; public | Same per-instance Docker isolation as SWE-bench | ([swebench.com/verified.html](https://www.swebench.com/verified.html)) |
| **SWE-bench Lite** | subset of SWE-bench (~300, not independently reconfirmed here) | subset of the same 12 repos | as above | public | as above |
| **SWE-bench Multimodal** | **617/612 instances** (sources disagree slightly — 612 dev+test pairs vs 617 stated total), split **102 dev (5 repos) / 510 test (12 repos)** | **17 JS/TS repos total** | Not confirmed | Public, SWE-bench org | Docker images, some very large (~9 GB for carbon-design-system/carbon) — [2410.03859](https://arxiv.org/pdf/2410.03859) |
| **SWE-bench-Live** | **1,319 tasks**, GitHub issues created since 2024 | **93 repos** | **Chronologically ordered by construction** — instances explicitly noted as ordered, and the "chain" variant resets the Docker image to the base commit of the first bug in a chain | Public, continuously updated ("live") | Standard tuple: repo, base commit, problem statement, gold patch, test patch, FAIL_TO_PASS/PASS_TO_PASS, test commands — [2505.23419](https://arxiv.org/abs/2505.23419) |
| **SWE-smith** | **50k generated instances** across **128 Python repos**; 5k valid trajectories produced from it | 128 repos | Not a natural-history benchmark — instances are **synthetically generated** (bug injection), so no real chronology | Public, NeurIPS 2025 D&B Spotlight | Generation framework + Docker, not a fixed static eval set — [2504.21798](https://arxiv.org/abs/2504.21798), [GitHub](https://github.com/SWE-bench/SWE-smith) |
| **SWE-Gym** | **2,438 tasks** (2.4k), 491 valid trajectories produced | **11 repos** | Not confirmed | Public | Docker-based, built for agent *training* not just eval |
| **Multi-SWE-bench** | not independently confirmed (search surfaced "Multi-SWE-bench-Flash" variant) | multilingual (beyond Python) | Not confirmed | Public — [2504.02605](https://arxiv.org/html/2504.02605v1) | Not confirmed |
| **SWE-Lancer** | Not independently confirmed in this pass (freelance-task-derived benchmark, referenced by SWE-bench Multimodal as using the same "Resolved Rate" metric) | Not confirmed | Not confirmed | Not confirmed | Not confirmed |
| **RepoBench** | Auto-completion, not issue-resolution — three sub-tasks (retrieval/completion/pipeline) | Python + Java, multi-repo, not confirmed count | Not confirmed | Public — [2306.03091](https://arxiv.org/abs/2306.03091) | No container execution — static completion benchmark |
| **RepoCod** | Repo-level completion, Python-only | Not confirmed | Not confirmed | Public | Paper framed skeptically: "Can Language Models Replace Programmers? REPOCOD Says 'Not Yet'" |
| **Commit0** | Referenced but **no detail retrieved** in this pass — flagged as a gap, needs a dedicated follow-up search | — | — | — | — |

**Key finding for the brief's per-repo-density requirement**: SWE-bench Verified's own repo distribution
is already heavily skewed — django/django alone supplies 231 of 500 instances (46%), which is *already*
"many tasks against one project" without needing a different substrate, provided sequential ordering by
base-commit or issue date can be reconstructed from instance metadata (not confirmed as a built-in field
but plausible given each instance is a real historical GitHub issue with a knowable date). SWE-bench-Live
was purpose-built with 1,319 chronologically-ordered instances across 93 repos and explicitly supports a
chained variant resetting to a shared base commit — this looks like the more principled substrate for
"repo-grouped, ordered, sequential" than repurposing Verified's incidental skew. ChainSWE (section A.11)
has already done the chain-mining work across six SWE-bench-family datasets, at 54 repos / 304 issues,
specifically to get chronological, dependent, same-repo chains — this is arguably a ready-made substrate
rather than one to be rebuilt.

**Docker/state-persistence, general**: every SWE-bench-family variant found uses per-instance Docker
containers, generally reset between instances (no persistent state by design) — this matches the brief's
intent of measuring whether an *external memory store* (not agent scratch state) carries information
across otherwise-isolated task runs, which is architecturally the right isolation boundary for testing
Zikaron specifically (the container resets; only what was written to the memory store persists).

## C. Environment-setup / build-test benchmarks

This is the closest published match to Zikaron's actual scope line ("how to build and test this repo,
which steps fail silently").

- **SetupBench** — **93 instances**, starting from a bare Linux sandbox; agent must install packages,
  resolve dependency conflicts, initialize databases, configure background services. Spans **7 language
  ecosystems, 5 database engines**, multi-service orchestration. Scored on whether the environment ends
  up correctly bootstrapped (exact metric/pass criterion not further detailed in this pass). Source:
  [Semantic Scholar entry](https://www.semanticscholar.org/paper/SetupBench:-Assessing-Software-Engineering-Agents'-Arora-Jang/7b136db7d185a66736c02889f4af2d922e14cc22)
  (arXiv id not directly captured — flagged for follow-up).
- **Installamatic (InstallamaticBench)** — **40 Python repositories** with exemplar Dockerfiles; success
  assessed by running tests after the agent's setup. Small, Python-only.
- **ExecutionAgent (ExecutionAgentBench)** — spans **5 languages**, uses **CI-log ground truth**;
  evaluates build/test success *and* deviations in test results (i.e., not just pass/fail on setup but
  whether the resulting test outcomes match what CI actually produced) — this is a stronger correctness
  signal than "tests ran" and closer to catching a silently-wrong setup.
- **EnvBench** — **329 Python + 665 JVM (Java/Kotlin) repositories** (994 total), deliberately selected to
  exclude repos trivially set up by a simple script — i.e., filtered *for* genuine configuration
  difficulty, which is exactly Zikaron's "silent failure" niche. Reported best-approach success:
  **6.69% of Python repos, 29.47% of JVM repos** configured successfully — a strikingly low ceiling,
  meaning most of this benchmark is currently *unsolved* even without any memory mechanism, which bears
  on feasibility (a memory-augmented agent would be tested against a substrate where the baseline is
  already failing >70–93% of the time, so a memory delta would need to be large or measured on a curated
  "hard but reachable" subset to be legible). Source: [2503.14443](https://arxiv.org/html/2503.14443v1).

**Repeated-attempts-on-same-repo**: none of the four sources found explicitly describe running *multiple,
sequentially memory-connected* attempts against the same repository (they appear to be single-attempt,
one-shot evaluations per repo). This is a genuine gap relative to the brief's protocol — these substrates
supply the *content* (build/test tribal knowledge tasks) but not the *sequencing* mechanism; that would
need to be added, analogous to how ChainSWE added sequencing to SWE-bench-family content.

## D. Published "memory helps a coding agent" evaluations, including negative results

Positive:
- **AgentKB on OpenHands/SWE-bench**: pass@1 **24.3% → 28.3% (+4.0pp)** with Agent KB memory retrieval —
  a real open-source harness (OpenHands), memory on/off, single clean number
  ([2507.06229](https://arxiv.org/abs/2507.06229)).
- **SWE-Exp**: 73.0% pass@1 on SWE-bench Verified with Claude 4 Sonnet, claimed to outperform prior
  frameworks — but the ablation isolating the experience-bank's own contribution (vs. baseline without
  it) was **not confirmed from primary text** in this pass ([2507.23361](https://arxiv.org/abs/2507.23361)).
- A memory-ablation figure surfaced in search-result synthesis (source paper not definitively pinned down
  among SWE-MeM / MemGovern / a "structured memory" paper in the result set — **treat as unverified until
  traced to one specific paper**): "removing the Memory Module... resolution rate dropping from 48.3% to
  42.3% on SWE-Bench Lite and from 57.2% to 50.4% on SWE-Bench Verified." This is exactly the kind of
  ablation number the brief wants, but this pass could not confirm which paper it belongs to with
  certainty — likely one of **SWE-MeM** ([2606.28434](https://arxiv.org/pdf/2606.28434)) or a similarly-named
  2026 paper; flagged as **not found with certainty**, needs a direct follow-up read before quoting.
- ReasoningBank reports up to **34.2% relative improvement in success rate** and **16.0% reduction in
  interaction steps** across WebArena, Mind2Web, and SWE-bench Verified combined — the per-benchmark
  breakdown for SWE-bench specifically was not isolated in this pass
  ([2509.25140](https://arxiv.org/pdf/2509.25140)).

Negative:
- **CTIM-Rover** (section A.10): repo-scoped episodic memory **degraded** AutoCodeRover's resolution rate
  from 42% to 31% on a 45-issue SWE-bench Verified subset when memory-only — the clearest published
  negative result found, and directly on-topic (per-repository memory for a code-repair agent). This is
  the single most important citation for a "memory can hurt" caveat in any protocol design.

Harness-level memory components with published numbers:
- **OpenHands** — evaluated with AgentKB's memory layer (above) and referenced as the substrate for
  several derivative memory papers (MemCoder claiming 83.8% pass@2 on SWE-bench Verified with GPT-5.2;
  OpenSage's hierarchical memory beating its own no-memory variant on SWE-bench Pro) — none of these
  derivative numbers were independently verified past search-snippet level in this pass; treat as leads.
- No published memory/experience component with numbers was found for **SWE-agent** or **Aider**
  specifically in this search round — absence noted, not confirmed as true absence (a dedicated search on
  those two names was not run to exhaustion).

## E. Verdict — substrates worth building on

1. **SWE-bench-Live, or ChainSWE's chain-mining methodology applied to the SWE-bench family, as the
   primary substrate.** Both already give repo-grouped, chronologically-orderable, multi-task-per-repo
   structure — the exact shape the brief wants — without inventing new task content. ChainSWE in
   particular has already solved the hardest part (mining 304 chronological, *dependent* issue chains
   across 54 repos from six SWE-bench-family datasets) and reports a memory-vs-no-memory-style comparison
   already, even if its stated purpose is diagnostic rather than memory-system validation.
   **Strongest objection**: SWE-bench-family issue-resolution tasks are centered on code-repair
   correctness, which is adjacent to but not identical to Zikaron's actual scope (build/test tribal
   knowledge, environment gotchas) — a memory system tuned for "how to build and test this repo" may show
   its value more in setup-time signals (env vars, silent failures) than in bug-fix Pass@1, and ChainSWE's
   dependent-issue chains test whether an agent tracks *code state* across fixes, not whether it recalls
   *procedural/environmental* facts. Zikaron's own scope line would exclude much of what a code-repair
   memory (ExpeRepair-, SWE-Exp-, AgentKB-style) stores, since bug-fix strategy is often derivable by
   reading the code and the diff.

2. **EnvBench or SetupBench, made sequential, as a purer scope-matched substrate.** These are the only
   found benchmarks whose task content — bootstrap a real repo's build/test environment from scratch,
   scored on genuine success — matches Zikaron's stated scope almost exactly. Running an agent against
   the *same* repo's setup task multiple times (e.g., variations of the same repo at different commits, or
   repeated cold-start attempts with memory persisting between them) would directly test whether captured
   tribal knowledge ("this env var is required and its absence fails silently") transfers.
   **Strongest objection**: neither benchmark, as published, has multiple task instances per repo or any
   built-in notion of a second attempt — that sequencing would have to be constructed from scratch (e.g.,
   sampling several commits of one repo's config-relevant history, or deliberately running the same setup
   task N times with memory carried between runs), and EnvBench's baseline success rate is already very
   low (6.69%/29.47%), so a memory delta risks being unmeasurable noise unless the substrate is narrowed
   to a "hard but not impossible" subset first.

3. **A CTIM-Rover-style controlled ablation, repo-scoped, on SWE-bench Verified's most repo-dense slice
   (django/django, 231 instances) — as the fastest, cheapest first experiment**, not a full new benchmark.
   Sort django's 231 instances by base-commit date, run an agent through them sequentially with a
   Zikaron-style memory store live, and compare against a no-memory control on the same ordered sequence.
   This reuses an existing, well-understood, well-licensed dataset with no new data collection.
   **Strongest objection**: this is exactly the design CTIM-Rover already tried (repo-level episodic
   memory on a SWE-bench Verified subset) and found it *hurt* — so this path carries real risk of
   reproducing a negative result unless Zikaron's retrieval/write discipline (hybrid dense+BM25 top-5
   gist push, agent-authored writes, explicit "could you learn this by reading the code" scope filter)
   is meaningfully different from CTIM-Rover's noisy CTIM retrieval — which is plausible (Zikaron's scope
   line is designed to exclude exactly the code-derivable noise CTIM-Rover's authors blamed for the
   degradation) but is itself the hypothesis under test, not a given.

## Open questions / follow-ups

- Confirm the mystery 48.3%→42.3% / 57.2%→50.4% ablation's source paper (candidates: SWE-MeM, or another
  2026 "structured memory" paper in the result set) before citing it anywhere load-bearing.
- Full-text read of SWE-Exp and ExpeRepair methods sections to confirm train/test split vs. online
  accumulation — this is the single most important unresolved detail for reusing their protocol.
- Commit0 was named in the brief and never actually found/described in this pass — needs a dedicated
  search.
- SWE-Lancer and Multi-SWE-bench sizing/repo-distribution were not confirmed — needs dedicated searches
  if either becomes a live candidate.
- No dedicated search was run for "Aider memory" or "SWE-agent memory" specifically — the absence noted
  in §D is weak evidence, not a confirmed negative.
- ChainSWE and SWE-Chain's exact chain-construction algorithm (how "dependency" between issues is
  determined) was not confirmed from primary text — worth a full-text read before reusing its
  methodology, since "dependent" could mean anything from "same file touched" to "same test suite" to
  "issue B's fix requires issue A's fix to be in place."

## Sources

1. [ExpeL: LLM Agents Are Experiential Learners](https://arxiv.org/abs/2308.10144) — Zhao et al., arXiv 2308.10144, Aug 2023 (AAAI 2024)
2. [Agent Workflow Memory](https://arxiv.org/abs/2409.07429) — Wang, Mao, Fried, Neubig, arXiv 2409.07429, Sept 2024
3. [Reflexion: Language Agents with Verbal Reinforcement Learning](https://arxiv.org/abs/2303.11366) — Shinn et al., arXiv 2303.11366, Mar 2023 (NeurIPS 2023)
4. [Voyager: An Open-Ended Embodied Agent with Large Language Models](https://arxiv.org/abs/2305.16291) — arXiv 2305.16291, May 2023
5. [SWE-Exp: Experience-Driven Software Issue Resolution](https://arxiv.org/abs/2507.23361) — arXiv 2507.23361, Jul 2025
6. [EXPEREPAIR: Dual-Memory Enhanced LLM-based Repository-Level Program Repair](https://arxiv.org/pdf/2506.10484) — arXiv 2506.10484
7. [Agent KB: Leveraging Cross-Domain Experience for Agentic Problem Solving](https://arxiv.org/abs/2507.06229) — arXiv 2507.06229, Jul 2025
8. [Memp: Exploring Agent Procedural Memory](https://arxiv.org/abs/2508.06433) — arXiv 2508.06433, Aug 2025
9. [AutoGuide (NeurIPS 2024 proceedings)](https://proceedings.neurips.cc/paper_files/paper/2024/file/d8efbb5dd415974eb095c3f06bff1f48-Paper-Conference.pdf)
10. [From Knowledge to Noise: CTIM-Rover and the Pitfalls of Episodic Memory in Software Engineering Agents](https://arxiv.org/pdf/2505.23422) — REALM @ ACL 2025, arXiv 2505.23422
11. [ChainSWE: Benchmarking Coding Agents on Multi-Bug Software Maintenance](https://arxiv.org/abs/2607.02606) — arXiv 2607.02606
12. [SWE-Chain: Benchmarking Coding Agents on Chained Release-Level Package Upgrades](https://arxiv.org/abs/2605.14415v1) — arXiv 2605.14415
13. [SWE-EVO: Benchmarking Coding Agents in Long-Horizon Software Evolution Scenarios](https://arxiv.org/pdf/2512.18470)
14. [Live-SWE-agent: Can Software Engineering Agents Self-Evolve on the Fly?](https://arxiv.org/pdf/2511.13646) — arXiv 2511.13646
15. [Executable Code Actions Elicit Better LLM Agents (CodeAct)](https://arxiv.org/abs/2402.01030) — arXiv 2402.01030
16. [Agent-Pro: Learning to Evolve via Policy-Level Reflection and Optimization](https://arxiv.org/abs/2402.17574) — arXiv 2402.17574
17. [ReasoningBank: Scaling Agent Self-Evolving with Reasoning Memory](https://arxiv.org/pdf/2509.25140) — arXiv 2509.25140
18. [SWE-bench: Can Language Models Resolve Real-World GitHub Issues?](https://arxiv.org/abs/2310.06770) — Jimenez et al., arXiv 2310.06770, ICLR 2024
19. [SWE-bench Verified](https://www.swebench.com/verified.html) — swebench.com
20. [SWE-bench Multimodal: Do AI Systems Generalize to Visual Software Domains?](https://arxiv.org/pdf/2410.03859) — arXiv 2410.03859
21. [SWE-bench Goes Live! (SWE-bench-Live)](https://arxiv.org/abs/2505.23419) — Zhang et al., arXiv 2505.23419
22. [SWE-smith: Scaling Data for Software Engineering Agents](https://arxiv.org/pdf/2504.21798) — arXiv 2504.21798, NeurIPS 2025 D&B Spotlight; [GitHub](https://github.com/SWE-bench/SWE-smith)
23. [Multi-SWE-bench: A Multilingual Benchmark for Issue Resolving](https://arxiv.org/html/2504.02605v1) — arXiv 2504.02605
24. [RepoBench: Benchmarking Repository-Level Code Auto-Completion Systems](https://arxiv.org/abs/2306.03091) — arXiv 2306.03091
25. [SetupBench: Assessing Software Engineering Agents' Ability to Bootstrap Development Environments](https://www.semanticscholar.org/paper/SetupBench:-Assessing-Software-Engineering-Agents'-Arora-Jang/7b136db7d185a66736c02889f4af2d922e14cc22) — Semantic Scholar entry
26. [EnvBench: A Benchmark for Automated Environment Setup](https://arxiv.org/html/2503.14443v1) — arXiv 2503.14443
27. [Process-Level Trajectory Evaluation for Environment Configuration in Software Engineering Agents](https://arxiv.org/html/2510.25694v1) — arXiv 2510.25694 (context for Installamatic/ExecutionAgent comparison table)
28. [Terminal-Bench: Benchmarking Agents on Hard, Realistic Tasks in Command Line Interfaces](https://arxiv.org/abs/2601.11868) — arXiv 2601.11868; [GitHub](https://github.com/harbor-framework/terminal-bench)
29. [SWE-MeM: Learning Adaptive Memory Management for Long-Horizon Coding Agents](https://arxiv.org/html/2606.28434) — arXiv 2606.28434 (candidate source for the unverified 48.3%/42.3% ablation figure)
