# Research note: localization benchmarks, contamination of repository layout, and the cost to localize (input to M40)

Written 2026-10-13 by memory-assistant for memory-researcher. Brief: `design/code-knowledge.md` §3 (M40's
evaluation bullet) and the research brief given with this task. Read first and **not redone** here:
`research/coding-agent-experience-benchmarks.md` §B (SWE-bench family as substrate),
`research/agentic-eval-methodology.md` (variance, power, contamination), `design/evaluation.md`.

## 0. The brief, restated

M40 proposes subagents that write one markdown document per source file (purpose, non-trivial
symbols, what is not obvious, forward dependencies) plus a module README, indexed as a hybrid
BM25+dense corpus returning fragments with line ranges. A coding agent searches it before it greps.
The proposed dependent variable is **localization**: does the agent reach the right files for a
feature, and at what token cost, grep-only against grep-plus-code-knowledge, on a large repository
the model has not memorized. A CockroachDB pilot (10 questions x 2 arms x 3 repeats, Claude Code
headless) showed 12 of 30 control runs opening with a grep of a specific subsystem path, medians of
24,452 (index) vs 26,002 (control) new-context tokens, per-question ratios 0.40-2.39, one cell
spanning 10x. Asked: (A) benchmarks with ground-truth localization, (B) layout contamination and how
to pick an unmemorized repository, (C) how the cost to localize is measured, (D) scale to ~10^5 files,
(E) retrieval/summary-augmented localization vs agentic grep, (F) a ranked verdict on 2-4 substrates,
build-your-own, and whether localization is the right dependent variable.

## 1. Bottom line

1. **No published benchmark meets all of: >=10^4 files, unmemorized, feature-level "where do I
   start", localization-only, runnable under Claude Code headless.** The nearest are LoLBench (large,
   feature-level, memorization unaddressed, tasks too big), CTXBench (niche repos, first-touch metric
   already defined, only up to ~26.6K files), and the kernel benchmarks (huge, but bugs and the most
   memorized repository there is). **Building our own task set beats every published one on criteria
   1-3 and 5**, at the price of ground-truth quality, which published sets only partly solve.
2. **The pilot's worry is confirmed by the literature, with numbers.** Stripping repository-specific
   names and paths (SchrodingerRepo, Aug 2026) raised exploration cost by +76% actions and +255% input
   tokens for one model on SWE-bench Verified, and even on *post-release* tasks from old repositories
   raised actions +8% and input tokens +22% with resolve rate unchanged. **Post-cutoff issues in an old
   repository do not remove layout memorization.** The remedies are a repository the model could not
   have seen, or renaming.
3. **Localization is defensible but file-level hit rate is the wrong form of it.** File-level accuracy
   saturates near the grep baseline on small and medium repositories (about 90% Acc@5 for
   shell-search agents on SWE-bench Lite), more than half of Lite issues name their own location, and
   the one controlled index-vs-ripgrep-agent comparison found a +8.1 pp localization gain with p=0.080
   on 78 pairs. What the literature supports instead: **cost to first touch of a gold file** (the
   AGENTS.md paper's "steps before first interaction with a patched file" is the closest published
   metric), **gold-context recall at a budget** (ContextBench, SWE-Explore), on **keyword-agnostic task
   text** (KA-LogicQuery shows agents fall from 77.7% to 22.2% file-level success when names are removed
   from the query), plus a downstream measure on a subset because agents often reach the gold context and
   then do not use it (ContextBench "usage drop" 18-44%).
4. **Documentation as a navigation aid has a mixed record, and two results are direct warnings.**
   Repository overviews in context files did not reduce steps to the first patched file and added
   >20% cost (ETH/LogicStar, v3 Sep 2026). A retrieval tool with precision 0.375 *raised* tokens per
   resolved issue by 21% (CodeGrep). Per-file generated documentation, the closest published analogue
   to M40's producer (RepoAgent-style), did best in the one study that scored it for localization
   (SWD-Bench F1 70.2 vs 29.1 with no documentation), but that study used famous SWE-bench repositories
   and a 57-instance end-to-end check.
5. **Sample size.** With the pilot's per-question spread (rough sigma of the paired log-ratio about
   0.6, estimated from its range), detecting a 20% token reduction needs about 57 questions, a 10%
   one about 254, and the pilot's own observed 6% about 750 (section 8.3, my arithmetic, not sourced).
   The budget stated in the brief buys the 20% question and not the 10% one.

## 2. Must-cover items: status

| Item | Status | One-line finding |
|---|---|---|
| LocBench (LocAgent, arXiv 2503.09089) | **Verified, with a correction on repositories** | 560 instances: 242 bug, 150 feature, 139 performance, 29 security; bug reports created after Oct 2024; Acc@k = all gold locations inside top-k; the paper does not enumerate its repositories (a search-result claim of "five repositories" is unverified); LocAgent+Claude-3.5 file Acc@5 83.39% on LocBench (HTML summary) |
| File-level localization on SWE-bench Lite/Verified by Agentless, OrcaLoca, CoSIL, SweRank, LocAgent | **Verified for Lite; Verified-only file-level not found** | Metrics differ per paper (patch-location correctness, "file match", Top-1, Acc@k), so the same baseline appears as 69.7, 72.6, 78.7 and 79.6 depending on the paper. On Verified only CoSIL function-level Top-1 44.6% was seen |
| SWE-PolyBench retrieval metrics | **Verified** | File-level and CST-node recall/precision, **computed on the files/nodes the agent edited**, not on files it searched; per-language tables in the paper |
| Long Code Arena bug localization | **Verified** | 7,479 issue-PR pairs; 450 manually verified test samples (150 each Python/Java/Kotlin); repositories small: median 331 files, mean ~1K; MAP/Recall@k; GPT-4 MAP 0.39 |
| FEA-Bench / another feature benchmark | **Verified, but not a localization benchmark** | FEA-Bench: 1,401 instances/83 repos (Lite 200/48), ACL 2025; no localization metric, only oracle-files vs BM25-files context. Feature benchmarks that do localize: LoLBench, Loc-Bench (150 feature), SWE-PolyBench (463 feature); NoCode-bench and FeatBench exist (search-snippet only) |
| SWE-bench Pro | **Verified, contamination claim weakly supported** | 1,865 tasks/41 repos; public 731 (11 GPL repos), held-out 858 (12), commercial 276 (18 proprietary); no localization metrics in the paper; a community audit reports 32% of public instances have date-unknown public copies of the gold patch |
| SWE-rebench | **Verified** | V1 21,336 tasks/3,468 repos, decontaminated by creation date, CC BY 4.0; V2 (ICML 2026) 32,079 issue-linked tasks/3,617 repos/20 languages plus 120,000+ PR-derived tasks |
| Bench4BL | **Verified** | ISSTA 2018; Java IR bug localization at file level; 10,017 reports over 51 projects per the repository README (paper abstract: 46 new subjects, 61,431 files, 9,459 reports) |
| Dit et al. feature-location survey and datasets | **Verified** | Survey (JSEP 2013, 89 articles) is separate from the datasets, which are in the MSR 2013 data paper: 6 datasets from 4 Java systems, 633 issues, 4,363 gold-set methods, 74-186 KLOC, 503-1,752 files |
| SWE-Bench Illusion (arXiv 2506.12286) | **Verified** | Up to 76% file-path accuracy from issue text alone on Verified vs below 53% on 245 instances from 7 other popular repositories; a NeurIPS 2025 *workshop* poster, not main track |
| Other memorization probes for layout | **Found** | Issue-only path prediction (Prathifkumar et al.), SchrodingerRepo rename-and-compare, AgentSeal corpus-membership audit |
| Equivalent of our first-tool-call screen | **Not found** | No paper screens repositories by an agent's first action; closest: issue-only path prediction, and rename-and-compare cost deltas |
| Meta-RAG | **Verified (exists)** | arXiv 2508.02611, JPMorgan; summary-based RAG, GPT-4o, file 84.67% / function 53.0% on Lite; baselines copied from leaderboard submissions |
| Scale benchmark at ~10^5 files / 10M LOC | **Found for the Linux kernel only** | LinuxFLBench, Live-kBench, kBenchSyz. Nothing found for Chromium or other monorepos; no independent controlled grep-vs-index study at that scale |

## 3. A. Benchmarks with ground-truth localization

### 3.1 Summary table

Evidence class: P = peer-reviewed venue seen on the paper or listing; W = workshop; X = arXiv preprint;
V = vendor blog/repo; C = community post. "n/v" = not verified. Repository size is files/LOC where a
source gave it.

| Benchmark | Tasks / repos | Type | Size of repos | Ground truth (and weakness) | Metrics | Licence | Contamination | Harness | Cost reported | Class |
|---|---|---|---|---|---|---|---|---|---|---|
| **Loc-Bench** [1][2][3] | 560 / "popular Python repos", count n/v | 242 bug, 150 feature, 139 perf, 29 security | n/v; SWE-bench repos average 3,010 files / 438K LOC [35] | Pre-existing files/functions edited by the PR; instances touching >5 files or >10 functions dropped; docs, imports and comments excluded. Patch files only | Acc@k (all gold in top-k): file @1/3/5, module @5/10, function @5/10; NDCG in appendix | Apache-2.0 (code repo) | Bug reports after Oct 2024, perf/security via keyword search | LocAgent repo; MTEB retrieval variant, MIT, ~3.6M corpus docs, 660 queries [4] | LocAgent+Claude-3.5: 7 rounds, $0.66 per instance on Lite; fine-tuned Qwen $0.05-0.09 | X (venue n/v) |
| **SWE-bench Lite / Verified** | 300 (274 with function edits) / 500; 12 repos | mostly bug (Lite: 254 bug, 43 feature) | ~3,010 files avg [35]; SWE-Explore's SWE-bench-derived repos avg 759 files, 180K LOC [27] | Patch files; **>50% of Lite issues name the file/class/function** [24]; Agentless found about half give the file [8] | as above | per upstream | **High**, see section 4 | many | see 3.3 | - |
| **SWE-PolyBench** [9][10] | 2,110 / 21 repos; Verified 382 (GitHub) or 394 (HF), PB500 | bug 1,572, feature 463, refactor 62; 2.6 files avg | n/v | PRs closing issues, >=1 fail-to-pass test; localization measured on the diff of the agent's *edit* | Pass rate; file and CST-node retrieval recall/precision | **Dataset MIT; the arXiv paper is CC BY-NC-ND** | SWE-bench repos excluded; repos updated within 12 months of collection | GitHub, Docker | tokens per instance in Table 4 (Aider-PB ~64.5K input vs Agentless-PB ~315K) | X |
| **Long Code Arena BL** [11] | 7,479 pairs; 450 verified test (150 x Python/Java/Kotlin) | bug | **median 331 files, mean ~1K** | Files in the linked PR diff; issue completeness manually verified; half single-file, half 2-10 files | MAP, Recall@k, Precision@k, F1 | permissive repos only | n/v | static retrieval, no agent harness | - | X |
| **FEA-Bench** [12] | 1,401 / 83 repos; Lite 200 / 48 | feature (>=25% new-component lines) | n/v | PRs adding functions/classes; signatures of the new components are given to the model | resolve rate; no localization metric; oracle files vs BM25 files | n/v | n/v | tests | - | P (ACL 2025) |
| **SWE-bench Pro** [13][15] | 1,865 / 41; public 731, held-out 858, commercial 276 | long-horizon; avg 4.1 files, 107.4 lines | n/v | patch; human-augmented statements | resolve rate; none for localization | public repos GPL | **design**: GPL public/held-out, proprietary commercial; **evidence**: community audit [14] | Harbor dataset `scale-ai/swe-bench-pro` [15] | n/v | X; audit C |
| **SWE-rebench** V1/V2 [16][17] | 21,336/3,468; leaderboard 294/169; V2 32,079/3,617 | issue-linked, 1-15 files, tests required | n/v | patch | resolve rate | CC BY 4.0 (V1); permissive repo licences | **date-tagged against model release**; V1 shows DeepSeek-V3 39.7% on Verified vs 21.3% on fresh tasks | HF dataset, Docker | n/v | X; V2 P (ICML 2026) |
| **SWE-bench-Live** [18] | 1,319 / 93 (Jan 2024-Apr 2025); Lite 300 | bug/issue | n/v | patch | resolve rate | per repo | fresh by construction, monthly updates; OpenHands+Claude 3.7: 19.25% vs 43.20% on Verified | RepoLaunch | - | X |
| **MULocBench** [25] | 1,100 / 46 top-starred Python repos | issues incl. usage questions | n/v | patches (716), commits (63), resolution comments (321); **19.2% of issues have non-code ground truth**; completeness not validated | Acc@k, F1; best file-level Acc@5 about 35% | HF release | n/v | HF | - | X |
| **ContextBench** [26] | 1,136 / 66 repos / 8 languages | issues from Verified, Multi-SWE-bench, SWE-PolyBench, Pro | n/v | **human-annotated gold context** (522,115 lines in 4,548 files, about 4 files per task), ~40 min per task | context recall/precision at file/block/line, efficiency, redundancy, usage drop | CC BY 4.0; HF dataset with `gold_context` spans | no systematic analysis | five agents, four LLMs | $0.38-0.91 per instance, 5.9-22.2 retrieval steps | X |
| **SWE-Explore** [27] | 848 / 203 repos / 10 languages | issues from Verified, Pro, Multilingual | **avg 759 files, 180K LOC** | lines read in >=2 independent successful agent trajectories (intersection, LLM expansion, manual audit); survivor bias | line P/R, nDCG@500, HitFile, Context Efficiency, First Useful Hit | CC BY-NC-ND 4.0 | SWE-bench-derived | GitHub, HF | none reported | X |
| **CTXBench** (AGENTS.md paper) [28] | 138 / 12 recent niche Python repos | bug and feature; mean 2.5 files, 119 lines | **mean 3,337 files, max 26,602** | PR patch | resolve rate, cost, **steps before first interaction with a patched file** | n/v | niche repos, developer-committed context files | Claude Code, Codex, Qwen Code; release n/v | per-instance cost in Table 2 | X (v3 29 Sep 2026) |
| **LinuxFLBench** [35] | 250 / Linux kernel | bugs (Bugzilla) | **28,808 files, 11.5M LOC avg** | developer patches; three annotators; **reports naming the buggy location were excluded** | Recall@k | n/v | not addressed | n/v | LinuxFL+ ~12-15K tokens (~$0.04), reported as about a tenth of the baseline agents' cost | X |
| **Live-kBench** [36] | 534 / Linux kernel, Apr 2024-Dec 2025 | syzbot crashes | **>20M LOC** | patch files and functions | file and function IoU, crash resolution rate | n/v | live; pre-cutoff bugs get 25% higher equivalent-patch rate than post-cutoff | mini-SWE-agent, SWE-agent, OpenHands | $5.6 budget per bug | X |
| **LoLBench** [38] | 100 / 29 systems (CPython, OpenJDK, Kafka, Kubernetes...) | enhancement proposal to implementation; PRs >=1k lines, >=10 files | **avg 2.4M SLOC (median 1.5M)** | hidden reference PR; proposals average ~5,000 words; only 7.3% of target class names appear in them | resolve; inspection recall/precision, modification recall/precision | n/v | **not addressed** | Claude Code, Codex, OpenCode, Pi, mini-SWE-agent | Claude Code+Opus 5: $15.30, 57.7 min, 17.7M input tokens per task | X (29 Sep 2026); data release n/v |
| **CodeScaleBench** [30][31][32] | 275 (README) / 370 (blog) tasks; 40+ repos | understand, feature, fix, refactor, org-level | designed for ~1M+ LOC | curator `ground_truth.json` for retrieval metrics | reward, F1@5, P@5, recall | **Apache-2.0** | not analysed | **Harbor + Claude Code** | $0.73 vs $0.51 per task (Haiku 4.5) | V |
| **KA-LogicQuery** [24] | 225 queries / 9 projects | keyword-agnostic structural queries | n/v | two authors validated each | file success, perfect-location rate | n/v | n/v | n/v | LogicLoc 16.2K tokens vs ">10x" for LocAgent/Agentless | X |
| **Bench4BL** [19] | 10,017 reports / 51 projects | Java bugs | 46 new subjects: 61,431 files total | bug-fixing commits linked to reports | Top-N, MAP, MRR | n/v | pre-LLM | scripts | - | P (ISSTA 2018) |
| **Dit et al. FL datasets** [20] | 633 issues / 6 datasets of 4 Java systems | bugs and features | **74-186 KLOC, 503-1,752 files** | methods changed in SVN commits whose log names the issue id; AST diff ignores formatting | method-level gold sets, traces | public | pre-LLM | Java tools | - | P (MSR 2013) |

### 3.2 Gold-patch files are not all the relevant files

- **ContextBench** found that a compact, sufficient human-annotated context averages about four files
  and ~460 lines per task, against a patch that touches 1-3 files; annotators needed ~40 minutes a task [26].
- **SWE-Explore** derived ground truth from what >=2 successful agents actually read: about 4.3 files,
  4.7 regions per task. The authors state it is an empirical approximation with survivor bias [27].
- **LoLBench** separates inspection recall (46.4-86.4% of reference files) from modification recall
  (36.9-65.0%) [38].
- **MULocBench** adds that 19.2% of issues' true locations are not source code, and does not validate
  completeness [25].
- **Dit et al.** warn that refactoring between releases makes gold methods disappear from the corpus [20].
- **Tangling.** Herbold et al. (EMSE 2022) labelled bug-fix commits line by line: only 17-32% of changed
  lines fix the bug when all files count (66-87% in production code), and 3-47% of data is noisy without
  manual untangling depending on the use case [47].
- **Report bias.** Kochhar et al. (2014) found already-localized bug reports (stack traces, entity names)
  significantly inflate bug-localization results and should be removed; a replication put the affected
  reports at about 5%, 23% and 30% for misclassified, already-localized and wrong-ground-truth-file
  cases (secondary summary, original not opened) [48].

### 3.3 File-level localization on SWE-bench Lite, as each paper reports it

All numbers below were read from the paper's own table unless marked. **The metrics are not the same
quantity**, so values for one baseline differ across papers.

| System (model) | Metric | File-level value | Source note |
|---|---|---|---|
| Agentless (GPT-4o) | % of submitted patches whose edit covers the gold file | 69.7% (function 52.0, line 35.3), $0.70, 78K tokens | Table 1 of [8]; read directly |
| Agentless (GPT-4o) | file localization step alone, top-3 files contain gold | prompting with the repo tree 78.67% ($0.02); embedding 70.33%; combined 81.67% ($0.06) | Table 2 of [8]; read directly |
| Agentless-1.5 (Claude 3.5) | "file match" (gold files subset of predicted) | 78.67% | OrcaLoca table [6]; HTML summary, not re-read |
| OrcaLoca (Claude 3.5) | file match / function match | 83.33% / 65.33%; search cost about $0.87 per instance | [6]; HTML summary |
| Agentless (Claude 3.5) | Acc@1 / Acc@5 | 72.63 / 79.56 | LocAgent Table 4 [1]; read directly |
| MoatlessTools, SWE-agent, OpenHands (Claude 3.5) | Acc@5 | 86.13, 90.15, 90.15 | [1][5]; read directly |
| **LocAgent (Claude 3.5)** | Acc@1 / Acc@5; function Acc@10 | 77.74 / 94.16; 77.37 | [1][5]; read directly. $0.66, 7 rounds |
| BM25 / CodeRankEmbed (no LLM) | Acc@1 / Acc@5 | 38.69 / 61.68; 52.55 / 84.67 | [1][5]; read directly |
| **SweRankLLM-Large (retrieve + 32B rerank)** | Acc@1 / Acc@5 | 83.21 / 95.99; reported $0.011 per instance (7B) vs LocAgent $0.66 | [5], ICLR 2026; table read directly, cost from HTML summary |
| CoSIL (Qwen2.5-Coder-32B) | Top-1 file; Top-1 function | 61.3 (LocAgent 64.7, Agentless-FL 58.3, OrcaLoca 59.0); 43.3. Verified function Top-1 44.6 | [7]; HTML summary. A "70M tokens" figure for DeepSeek-V3 against $0.022 per instance is dimensionally inconsistent in my read |
| Meta-RAG (GPT-4o) | file / function "correct localization" | 84.67 / 53.0 vs best leaderboard baseline 71.67 / 39.33 | [39]; read directly. **Baselines are leaderboard patch locations, not the same pipeline** |

**What this table says for M40.** File-level Acc@5 on Lite sits between 61.7 (BM25) and 96 (trained
retriever+reranker), with shell-search agents at about 90. The **ceiling is close and the small
repositories leave no room**; the agentic advantage appears at function level and as difficulty (hop
distance between the issue's named functions and the patched ones) rises [1]. A comparison of grep
against code knowledge at file level needs repositories and task text that stop the grep baseline from
saturating.

## 4. B. Contamination of repository layout

### 4.1 The SWE-Bench Illusion, verified

- Liang, Garg, Zilouchian Moghaddam, arXiv 2506.12286 (v4 Dec 2025) [21]. **Venue: NeurIPS 2025 workshop
  poster (LAW)** per the NeurIPS page; an ICSE 2026 SEIP listing appeared in search results but its page
  timed out here, so treat it as unverified.
- **Design**: ten models (GPT-4o variants, GPT-4.1, o3, o3-mini, o4-mini, Claude 3.5/3.7/4 Sonnet, Claude 4 Opus).
  The model gets only the issue text and the repository name, no code or tree, and names the buggy file path.
- **Numbers**: accuracy ranges 60-76% on Verified, 57-71% on full SWE-bench, 50-68% on "SWE-bench Extra", and
  **below 53% on 245 instances from seven popular repositories** (jupyter/notebook, celery, aiohttp, scipy,
  numpy, pytorch, pandas). Function reproduction: up to 34.9% consecutive-5-gram overlap on Verified vs
  18.2% outside SWE-bench.
- **Limits**: the comparison set has different issue text (the paper notes RefactorBench issues are 14.6
  tokens against ~450), and nothing controls how often the issue text itself names the file. So 76 vs 53
  mixes memorization with issue-text hints. Both outside-set repositories are *popular*, so the gap is a
  lower bound on layout familiarity, and the 53% itself is high.
- This matches `research/agentic-eval-methodology.md` §3, which cites 76% vs 53%; the additions here are
  the venue, the per-benchmark ranges, and the confound.

### 4.2 Issue-only path prediction used as a probe, replicated

Prathifkumar, Mathews, Nagappan (arXiv 2512.10218, Dec 2025) [22] ran the probe as a *dataset-level*
test: Claude 3.5 / 3.7 Sonnet, 500 Verified issues vs 500 BeetleBox issues (5 Python repositories) vs
SWE-rebench Jan 2025 (109) and Sep 2025 (50) splits. Share of instances where **all** gold files were
named:

| Setting | SWE-bench Verified | BeetleBox | SWE-rebench Jan 2025 | SWE-rebench Sep 2025 |
|---|---|---|---|---|
| Issue + file structure | 76% / 73% | 21% / 17.6% | 43.1% / 44.0% | 28% / 22% |
| Issue only | 65% / 63.2% | 12.2% / 12% | 17.4% / 19.3% | 12% / 8% |

(first value Claude 3.5, second Claude 3.7). The authors call the 3x/6x gap evidence of memorization and
do not discuss whether the issue texts name files. **This is the closest published relative of our screen.**
It is used to judge a *benchmark*, never to choose a repository for an A/B, and it is a cheap probe: one
model call per task, no tools.

### 4.3 What memorization costs in the units we care about: SchrodingerRepo

Chen et al., arXiv 2609.27891, 21 Aug 2026 [23]; code at github.com/cslsolow/Schrodinger-Repo. Read
directly from the paper.

- **Four transformations** of a SWE-bench Verified instance: (L1) reword the issue with an LLM generator
  and verifier plus human review; (L2) a **seeded, invertible namespace remap of repository paths, modules
  and repository-owned symbols**, applied at the command interface of mini-swe-agent so the agent sees the
  virtual names; (L3) reorder definitions inside a file; (L4) rewrite the issue-relevant code into an
  equivalent form. L3/L4 are applied only to golden-patch files and kept only if pass-to-pass holds and
  fail-to-pass still fails.
- **Validity**: tests for L3/L4, 100 human-reviewed instances per level, a translation-layer argument for
  L2. **No invalid-task rate is reported.** Models: GPT-5.4-mini, GPT 5.1, DeepSeek-v4-Flash,
  Gemini-3.1-Flash-Lite; mini-swe-agent; three seeded views per instance.
- **Pass@1 on Verified (full transform)**: GPT-5.4-mini 46.8 to 35.6 (-11.2), GPT 5.1 44.6 to 36.2 (-8.4),
  DeepSeek 72.8 to 66.8 (-6.0), Gemini 56.7 to 42.3 (-14.4). L2 (names and paths) is the largest single
  level: -7.4/-6.4/-6.0 points.
- **Interaction cost, GPT-5.4-mini**: actions 11.25 to 19.83 (+76.2%), input tokens 65,905 to 234,216
  (+255.4%). L2 alone: +32.6% actions, +108% input tokens. DeepSeek L2: actions 46.19 to 98.13. **81.6-83.6%
  of the extra actions are navigate/search/read/probe**, not editing.
- **Post-release tasks**: on 110 SWE-rebench instances created after the models' release (March 2026
  split), the full transform left Pass@1 at 17.27% but still raised actions 15.82 to 17.11 (+8.2%) and input
  tokens +22%. The text I read says the increase is more pronounced in widely used, long-lived repositories
  (the sentence was cut off at the page break, so the exact wording is unconfirmed). **This is the key
  datum for us**: post-cutoff tasks in an old repository still carry layout memorization.
- **SWE-QA** (144 questions, 3 repositories): score down 0 to 4.64, actions up 18-43%.
- **Limits**: one scaffold (mini-swe-agent), small models, no Claude Code run, no file-level localization
  metric, L3/L4 limited to golden-patch regions.

### 4.4 Choosing a repository the model has not memorized

| Route | Evidence it works | Evidence against / cost |
|---|---|---|
| Post-cutoff **PRs/issues** in an old repository (SWE-rebench, SWE-bench-Live, LocBench) | Removes solution memorization (V1: 39.7% vs 21.3% for DeepSeek-V3) | **Layout survives**: SchrodingerRepo RQ4 (+22% input tokens on post-release tasks); issue-only path accuracy 12-19% on SWE-rebench splits [22] |
| Repository created **after** the model's training cutoff | Not studied as such | Rare for large repositories; I could not find a published example above 10^4 files |
| **Copyleft** repositories (SWE-bench Pro public) | Design intent [13] | Only a community audit [14]: 234 of 731 instances (32%) have public copies of the gold patch text, which the audit itself labels date-unknown and not proof of pre-cutoff exposure. Its "76 source repositories flagged by a Stack v2 filter" does not square with 11 public repositories, so read it as low-grade evidence |
| **Private / commercial** (SWE-bench Pro commercial, 18 repositories) | Best reported resolve is lower on the commercial set (17.8%, Opus 4.1) than on the public one (43.6%, Sonnet 4.5), different models, so only suggestive | Not downloadable; results only [13]. **The operator's own ~10M-line codebase** from `design/code-knowledge.md` §1 is this route and the only one that is both large and unmemorized, if sharing it with the model API is acceptable (not checked here) |
| **Niche** public repositories (CTXBench) | Chosen because popular repositories are unrepresentative [28] | "Niche" is not "unseen" |
| **Renaming** (SchrodingerRepo L2) | Measured cost effect; tests validate the transformed tasks | Python/bash-interface implementation; the paper leaves unclear whether directory names are remapped; **removing names also degrades intent-level tasks such as summarization** [57], so it is not neutral for an index built from generated documentation (my inference, supported by that result) |
| Repository **membership** lookups ("Am I in The Stack") | Free, repository-level [59] | Covers one public corpus, not any specific model |

**Does obfuscation keep the task valid?** For issue resolution, yes within the limits above: tests pass
or fail as before and Pass@1 on post-release tasks was unchanged. For localization, the gold set maps
through the invertible namespace, so the label survives. The validity risks specific to us are that
generated documentation is itself written from names, and that structure and algorithms still identify
a famous project (L2 renames repository-owned symbols and leaves external APIs alone).

### 4.5 Is there a better test than the first-tool-call screen?

- **Nothing published screens repositories by agent behaviour.** What exists: (a) issue-only path
  prediction [21][22], (b) rename-and-compare cost deltas [23], (c) corpus membership audits [14][59].
- **Ours measures the mechanism directly** (does the agent skip exploration?), which is the quantity that
  decides whether an index can save tokens. (a) measures knowledge of paths from text, (b) measures the
  resulting cost.
- **Cheap complements**: run (a) with the target model on the candidate task text with the repository name
  removed, as a control for text-only hints (my suggestion; the Illusion paper does not do this), and
  validate the screen on two or three candidate repositories by (b): if first-tool-call hit rate does not
  predict the input-token increase under renaming, the screen is measuring something else.
- **Comparability**: SWE-Pruner and SchrodingerRepo count cumulative input tokens across rounds;
  the pilot counts new-context tokens. The two are not interchangeable (see 5.2).

## 5. C. Measuring the cost to localize

### 5.1 What exists

| Source | Quantity | Note |
|---|---|---|
| AGENTS.md / CTXBench [28] | **steps before the first interaction with a file in the PR patch** (Figure 4); 3% of runs never touch one and are excluded | Closest published metric to ours; baseline roughly 7-11 steps for Sonnet-4.5/GPT-5.2 and 14-18 for GPT-5.1 mini (read off the bar chart); single sample per instance |
| ContextBench [26] | retrieval steps (5.87 GPT-5, 14.38 Sonnet 4.5, 22.16 Devstral 2), lines per step, "efficiency" (how early gold context is captured; exact formula not confirmed), redundancy, usage drop | Process metrics, not tokens to first gold |
| SWE-Explore [27] | First Useful Hit (rank in the explorer's output), Context Efficiency; Pearson r = 0.950 between context efficiency and downstream patch success, 0.928 for FUH | Across explorers in a restricted-context replay; the number of systems is small (my inference from the system list) |
| SchrodingerRepo [23] | actions, input and output tokens, action categories | Whole run |
| Code Isn't Memory [29] | turns, tokens, $/cell, $/solved | Three seeds; the token column's definition was not confirmed |
| SWE-Pruner [45] | read operations are **76.1% of tokens** (4.38M of ~5.75M; execute 12.1%, edit 11.8%) for mini-SWE-agent + Claude Sonnet 4.5 on Verified, **cumulative per-round tokens**; read directly | One scaffold and model |
| LocAgent, OrcaLoca, CoSIL, Agentless, SweRank [1][5][6][7][8] | $ per instance and rounds for the localization stage | LocAgent 7 rounds, $0.66; Agentless file step $0.06; SweRank $0.011 |
| Meta-RAG [39] | $0.97, 16.2K tokens, 58.5 s per task | Excludes summary generation (see 7.1) |
| LinuxFLBench [35]; Live-kBench [36] | tokens per task; LLM invocations per trajectory (33.67) | Kernel scale |
| FastContext [46] | exploration is >56% of tool-use turns and nearly half of main-agent tokens | **Version 4 was withdrawn (product IP concerns)**; do not cite |
| JetBrains Junie blog [54] | Opus and Gemini first opened a relevant file at step 15 in one example | Anecdote; scaffold-specific |

**No paper found reports tokens to the first correct file.** Most report the cost of the localization
stage or of the whole run. Almost none report variance across repeated runs: Code Isn't Memory (three
seeds, Wilcoxon on per-instance means) and Live-kBench (3 or 10 attempts) do; the AGENTS.md paper, LoLBench
and ContextBench use a single attempt.

### 5.2 Reading for the pilot

The pilot's quantity (new-context tokens ingested) excludes re-reads of cached context, so it is
**smaller and flatter** than cumulative input tokens. Exploration is where most tokens go (SWE-Pruner,
ContextBench) and removing layout familiarity multiplied whole-run input tokens by about 2.6-3.6 in
SchrodingerRepo's full transform (GPT 5.1 +161%, DeepSeek +254%, GPT-5.4-mini +255%), so a 6% difference
between arms is small next to a repository-familiarity effect that large. That supports putting the
screen first.

## 6. D. Scale: ~10^5 files and ~10M LOC

### 6.1 What exists (all kernel)

- **LinuxFLBench** [35]: 250 bugs, **28,808 files and 11.5M LOC per task on average** against SWE-bench's
  3,010 files / 438K LOC. Top-1 file recall 36.8-41.6% for Agentless, AutoCodeRover and SWE-agent with
  GPT-4o, against 70%+ on SWE-bench. The authors' LinuxFL+ (directory-aware expansion, hypothesised
  causes, mailing-list knowledge) lifts SWE-agent from 41.6 to 52.4 using about 12-15K tokens (~$0.04),
  reported as roughly a tenth of the agents' cost. **Report-selection note**: reports that name the buggy
  location were excluded by hand.
- **Code Researcher** [37] (Microsoft Research): kBenchSyz, 279 crashes (200 validated) in a kernel of
  "75K files and 28M lines". File recall 0.51 for the deep-research agent vs 0.37 for SWE-agent and 0.49
  for Agentless; **10 unique files explored per trajectory vs 1.33** for SWE-agent. Commit-history search
  mattered (about 10% when removed).
- **Live-kBench** [36]: 534 syzbot crashes Apr 2024-Dec 2025, >20M LOC. File IoU 51.7-69.2% for
  mini-SWE-agent across Gemini 3 and Claude Opus 4.5; **25% higher equivalent-patch rate on pre-cutoff
  bugs**; localization by pre/post cutoff not broken out.
- **LoLBench** [38]: 29 systems averaging 2.4M source lines. Localization is the largest single failure
  attribution (30.9 units, almost all from "cross-module context missing"). Giving agents
  reference-derived file trees and API specifications raised resolve rates 16-22 points (14% to 34% for
  Claude Code + Opus 5).
- **CodeScaleBench** [30][32] (Sourcegraph, vendor): +0.259 reward from retrieval tools in the 400K-2M LOC
  band and -0.080 below 400K LOC; Kubernetes DRA task (1.4M lines, 22,000 files) 6,000 s with no result
  under grep vs 89 s with an index. Overall mean reward 0.536 vs 0.565, cost $0.73 vs $0.51. The vendor
  says its evidence is directional.
- **FaultLoc** [60] (ICML 2026 listing): 900 vulnerabilities; agents reach about 40% line overlap; repository
  sizes not given [abstract page only].

### 6.2 What is not there

- **No Chromium, Firefox, AOSP or monorepo benchmark was found.** A secondary blog claim that ripgrep needs
  15+ seconds per query above one million files, against 0.013 s for a prebuilt index, was not traced to
  a primary source and should not be cited.
- **No independent, controlled grep-versus-index study at ~10^5 files.** The scale evidence for an index is
  vendor (Sourcegraph, Cursor) or small-n.
- Agentless-style repository-tree prompting (the whole `tree` as input, $0.02 per localization on Lite)
  is a method that does not scale to 10^5 paths by construction (my inference); LinuxFLBench's gap is
  consistent with that.
- The kernel is the **worst case for memorization**, so these benchmarks measure scale and memory at
  once.

## 7. E. Retrieval- or summary-augmented localization against agentic grep

### 7.1 Same model, same tasks

| Study | Setup | Baseline | Augmented | Reading |
|---|---|---|---|---|
| **LocAgent** [1], Lite 274, Claude-3.5 | graph index + 3 tools | SWE-agent / OpenHands file Acc@5 90.15 | **94.16**; function Acc@10 70.07 to 77.37 | +4 points file-level, +7 function-level over shell-search agents |
| **SweRank** [5], Lite 274, ICLR 2026 | trained embedder + reranker, no agent loop | LocAgent+Claude-3.5 94.16 | 95.99 (Acc@5), Acc@1 83.21 vs 77.74 | **Retrieve-and-rerank without an agent loop matches or beats the agents at about 1/60 the cost** on this benchmark, but the models are trained on an initial 67K PR pairs from 3,387 repositories |
| **Meta-RAG** [39], Lite 300, GPT-4o | LLM reads hierarchical NL summaries of files/classes/functions; summaries shrink the codebase by 79.8% | leaderboard patch-location baselines 65.0-71.67% file | **84.67% file, 53.0% function** | Baselines are other teams' submissions, not a controlled arm. Summary tokens for all instances (105.9M) vs 605M code tokens; incremental summary updates save 57.9%. No dollar cost for summarization reported |
| **NL summaries across 46 microservice repos** [40], 87 tickets, one proprietary Java system (7,077 files) | file/directory/repo summaries, gpt-4.1-mini, one-time ~$80 | GitHub Copilot Pass@10 0.61, Cursor 0.57 | Pass@10 0.82, MRR 0.50 | Single proprietary system, n=87, workshop-level evidence; **a useful design reference for M40's README tier** |
| **Code Isn't Memory** [29], Opus 4.7, 91 instances x 3 seeds | structural index (BM25 + vector + call graph) inside one harness, ON/OFF; OpenCode (ripgrep) as comparator | **OFF** 41.9% resolve, acc@5 44.3% | ON 50.4% (p=0.003), acc@5 84.5% (p<0.0001); $/solved $2.30 vs $2.84 | **vs ripgrep agent**: resolve 50.4 vs 45.3 (p=0.087), acc@5 84.5 vs 75.3 (p=0.080), turns 28.3 vs 36.0, tokens 10.1k vs 14.0k (p<0.0001, token definition unconfirmed); authors are the index's vendor |
| **CodeScaleBench** [30][31], Haiku 4.5, Claude Code | 13 Sourcegraph MCP tools vs local grep | recall 0.127, P@5 0.140, F1@5 0.099 | recall 0.277, P@5 0.478, F1@5 0.262; cost -30%, time -38% | Vendor, directional by its own words; "agents mostly do lexical search unless pushed" |
| **Cursor** [33], vendor blog Nov 2025 | semantic search + grep | grep only | +12.5% answer accuracy (6.5-23.5% by model); retention +0.3% (+2.6% on 1,000+ file codebases) | No sample sizes disclosed |
| **turbopuffer talk** [34], ContextBench 50 tasks, Claude Code | windowed reads + semantic tool | stock: file precision 65% | 87%; recall mixed across tasks | Vendor talk, Django |
| **SWD-Bench** [41], GPT-4.1 | model predicts files **from documentation**, documentation from six generators | **no documentation: F1 29.12** | RepoAgent 70.19, DocAgent 68.32, human-written 65.84, DeepWiki 43.76 | 4,170 entries on 12 famous SWE-bench-style repos; SWE-agent resolve on **57** Verified instances 43.86 to 52.63 with RepoAgent docs; docs plus code beats either alone. The no-documentation figure is also a memorization floor |
| **Deep agentic search vs semantic search** [42], SWE-QA 720 questions, 4 models | grep subagent | 46.2% | semantic 65.2%; $0.32 vs $0.74 per correct answer; Qwen3-235B 34K vs 761K input tokens | Read-only QA over indexable code; chunk embedding, not documentation |
| **Codebase-Memory** [44] | tree-sitter graph over MCP, 31 repositories | file-exploration agent 92% answer quality | 83%, with 10x fewer tokens and 2.1x fewer tool calls | Model unspecified in the abstract page |

### 7.2 Results against the index

- **AGENTS.md paper** [28], v3 29 Sep 2026, Claude Code/Codex/Qwen Code, 300 Lite tasks + 138 CTXBench:
  context files, LLM-written or developer-written, **do not generally improve success** (changes of
  about -0.5 / -2 points for LLM-written, +2.4 for developer-written, p between 0.21 and 0.87) and raise
  cost by 20-23%; **repository overviews did not reduce steps to the first patched file** (Figure 4); 95-100%
  of LLM-generated files contained a directory overview. Instruction-following was strong, which is
  the mechanism for the extra cost. Single sample per instance. This is about *injected* overviews, not
  an on-demand search, but it is the only controlled test of "documentation of the repository helps the
  agent find files".
- **CodeGrep** [43], OpenHands + Qwen3-30B-A3B on Verified: a candidate-files block from a retriever
  changed resolve rate and tokens by retriever precision. **BM25 (precision 0.375): 25.2% vs 25.8%,
  tokens per resolved issue +21%** (+38.6% on instances both resolved); Jina-1.5B (0.445) neutral;
  trained agent (0.677) +1.2 points and -19% tokens. **A low-precision lead costs more than no lead**,
  which is also the CTIM-Rover finding in `research/coding-agent-experience-benchmarks.md` §A.10.
- **Probe-and-Refine** [55]: a per-repository guidance file tuned with synthetic bug-fix probes lifted
  Qwen3.5-35B-A3B on Verified from 25.5% to 33.0% (a static knowledge base: 28.3%), by getting the agent to
  the right file more often. Small model, preprint.
- **SWE Context Bench** [56] (arXiv 2602.08316) reports that well-summarized prior cases cut runtime and
  tokens while poorly selected ones gave little or negative value. That is a memory-reuse result adjacent
  to Zikaron's store, not a localization one.

## 8. F. Verdict

### 8.1 Ranked substrates for M40's A/B

Criteria: (1) large; (2) unmemorized and controllable; (3) ground truth at "where to start on this
feature"; (4) runnable under Claude Code headless at tens to low hundreds of dollars per arm; (5) sample
size.

**1. Our own task set on a repository the model could not have seen** (private repository if the operator
can use one, else a post-cutoff repository, else an old large repository with SchrodingerRepo-style
renaming and the screen from 4.5). Best on 1, 2, 3 and 5; 4 holds because no environment build is needed
for a localization-only task. Cost: ground-truth design, below.

**2. CTXBench's construction, applied to a larger repository** [28]. 12 recent niche repositories, mean 3,337
and maximum 26,602 files, PR patch, Claude Code supported, and the first-touch metric is already
defined and run. Its published data is Python-only with 138 instances, mean 2.5 patched files, a release
not confirmed here, and "niche" not "unseen". Use it as the template for metric and harness rather than
as the data.

**3. LoLBench data, if released** [38]. The only public benchmark with large systems (mean 2.4M SLOC) and
feature-level tasks, and it defines inspection recall/precision from trajectories. Against it:
CPython, Kubernetes, OpenJDK and Kafka are among the best-memorized codebases there are, contamination is
not addressed, reference PRs are >=1,000 lines over >=10 files so "where to start" is diffuse, and a full
run costs $15 per task. A localization-only protocol over its proposals would be cheap, but data
availability is **unverified**.

**4. CodeScaleBench's harness** [30][31] (Apache-2.0, Harbor runner with Claude Code, curator
`ground_truth.json`, retrieval metrics) **as infrastructure and as a deliberately memorized contrast
arm**: the same index design on a famous repository and on a renamed or unseen one quantifies how much
of any gain is layout. Vendor-built; the README and blog disagree on the task count (275 vs 370).

**Not recommended**: SWE-bench Lite/Verified, Loc-Bench, SWE-PolyBench (small, popular repositories, task
text often names the location); Long Code Arena (median 331 files); LinuxFLBench/Live-kBench (bugs, the kernel is
the most memorized codebase, no feature intent) except as a scale probe; SWE-bench Pro public (GPL claim
weakly supported, repository sizes not verified here, no localization metric; a Harbor dataset exists, and
its tasks are a source for ContextBench, SWE-Explore and Code Isn't Memory).

### 8.2 Does building our own beat every published set?

**Yes for this question**, because no set above is simultaneously large, unmemorized, feature-shaped and
localization-scored. It does not beat them on label quality, so borrow how they handled it.

How others built post-cutoff PR sets, and what they did about tangling:

| Set | Task source | Handling of tangled or noisy ground truth |
|---|---|---|
| SWE-rebench V1/V2 [16][17] | ~450K PRs linked to resolved issues; permissive licence, >75% Python (V1) | One linked issue, 1-15 files, tests modified, LLM judges for issue clarity (79% accuracy), complexity (81%) and test correctness (67%); V2 adds 120K+ PR-derived tasks whose statements are generated from the PR |
| LocAgent [1] | issues after Oct 2024 | drop instances over 5 files or 10 functions; docs/imports/comments excluded |
| LinuxFLBench [35] | Bugzilla reports with confirmed fixes | three annotators; reports naming the location removed |
| ContextBench [26] | existing benchmarks | humans trace dependencies from the gold patch to a compact sufficient context, with agreement checks and LLM patch regeneration |
| SWE-Explore [27] | existing benchmarks | context = lines read by >=2 successful agents (intersection, LLM expansion, manual audit) |
| Dit et al. [20] | SVN commits naming an issue id | AST diff ignores formatting; manual verification of commit-issue links; refactoring losses acknowledged |
| FEA-Bench [12] | PRs adding functions/classes | at least 25% of edited lines in new components |
| CTXBench [28] | PRs from 12 niche repositories | LLM-written task description to avoid leaking the solution, 10% hand-checked, tests with ~75% coverage of modified code |
| NoCode-bench [49] | documentation changes in release notes paired with the code change | the user-facing doc is the task input (search snippet only) |

A construction that follows from these (my synthesis, not a published recipe):
1. Take merged PRs from the unseen or renamed repository; keep 1-15 non-test files, drop mechanical
   changes (renames, formatting, generated files, lockfiles, vendored code, dependency bumps).
2. **Gold = pre-existing source files the PR modifies or deletes** (as LocAgent does), plus the directory
   of any new file. New files cannot be found beforehand.
3. **Task text = the PR description rewritten into a keyword-agnostic feature request**, then checked
   automatically and by hand for file names, identifiers and distinctive strings (LinuxFLBench removed
   reports that named locations; KA-LogicQuery shows the difference is 55-60 points). Record the
   lexical overlap between each task and its gold paths as a covariate.
4. **Two tiers of ground truth**: gold-patch files, and a "gold context" set as in ContextBench or
   SWE-Explore on a subset (a 40-minute-per-task human cost, or the agent-trajectory proxy).
5. Report both, per-task, with paired analysis; split results by whether the task text overlaps gold paths.

### 8.3 Sample-size arithmetic (mine, unsourced)

Paired design on per-question log-ratio of tokens (index over control) with paired standard deviation
sigma and effect delta = ln(ratio). n = (2.8016 sigma / delta)^2 for alpha 0.05 two-sided, power 0.80
(add about 2 for the t distribution).

The pilot's per-question ratios ran 0.40-2.39, so ln ratios span -0.916 to +0.871, a range of 1.79; the
expected range of ten normal observations is about 3.08 sigma, giving **sigma about 0.58**. That is a
rough estimate from a range and should be replaced by the standard deviation of the pilot's 10 values
(and by a variance-components fit separating question, arm-by-question and repeat noise).

| Effect to detect | sigma 0.4 | sigma 0.6 | sigma 0.8 |
|---|---|---|---|
| 30% fewer tokens (delta 0.357) | 10 | 22 | 40 |
| 20% (0.223) | 25 | 57 | 101 |
| 10% (0.105) | 113 | 254 | 452 |
| 6% (the pilot's median ratio 0.940, delta 0.0615) | 332 | 747 | 1,328 |

Cost anchors from the literature, per run: ContextBench $0.38-0.91 (resolve tasks, four LLMs),
CodeScaleBench $0.51-0.73 (Haiku 4.5), Code Isn't Memory $1.15-1.32 per cell (Opus 4.7). A localization-only
task that stops after the agent names files should cost less than a resolve run; I assume $0.3-1.5. At 57
questions x 3 repeats x 2 arms = 342 runs that is about **$100-510 total**. **The brief's budget buys the
20% question and not the 10% one.** Per `FINDINGS.md` §"How the next review should be briefed", decide
what would change if the answer is 6%, 10% or 20% before preregistering a bar.

Variance handling beyond sample size: the pilot's 10x cell suggests heavy tails. Cap turns per run and
treat capped runs as censored or use a rank-based paired test (Code Isn't Memory used paired Wilcoxon
on per-instance means); more questions help more than more repeats once the repeat component is
averaged down; run the control arm repeats first to measure the repeat variance before fixing k.

### 8.4 Is localization the right dependent variable?

**Partly.** Evidence for:
- It is where failures concentrate at scale: the largest single failure category in LoLBench [38], and
  oracle file trees add 16-22 points.
- Exploration is where tokens go: 76.1% of tokens are read operations [45], 5.9-22.2 retrieval steps per
  instance [26].
- Exploration quality predicts downstream success: r=0.95 for context efficiency [27].
- Memorization acts on exactly this quantity (+255% input tokens, [23]).

Evidence against it as designed:
- **File-level hit rate saturates** on small and medium repositories (about 90% Acc@5 from shell-search
  agents; ContextBench file recall about 0.68-0.73).
- **Task text that names the target hides any index benefit**: over 50% of Lite issues do [24].
- **Reaching is not using**: agents inspect gold context and then drop it (usage drop 17.9-43.5%) [26].
- **The only controlled index-vs-ripgrep comparison** saw a +8.1 point localization gain at p=0.080 [29],
  and its large within-harness gain came from a weak OFF arm (44.3% acc@5, below OpenCode's 75.3%): a
  caution that the control arm must be a *competent* grep agent, which Claude Code is.
- **Misleading or low-precision leads cost more than none** [43][28], so a localization win can coexist
  with an end-to-end loss (the CTIM-Rover pattern).

**What would be better, or additional:**
- Primary: **new-context tokens and tool calls before the first touch of a gold-patch file**, as a
  time-to-event with a cap (the AGENTS.md paper's metric, in our token unit), alongside gold-context recall
  at a fixed token budget.
- On **keyword-agnostic task text**, split by lexical overlap with gold paths.
- A **downstream measure on a subset** (edit-locus recall as in LoLBench, or resolve) to catch found-but-unused
  and stale-document harm. Whether a stale or wrong document costs more than none is the CTIM-Rover risk
  `design/code-knowledge.md` §3 already names.
- Where documentation may help most, comprehension QA over the module (SWE-QA [50], SWE Atlas Codebase QnA
  [51], RepoProbe, 500 Q&A across 50 repositories, via a secondary blog only [53]): SWD-Bench (F1 29 to 70)
  and the semantic-search QA result (46% to 65% pass) show large gains in that setting, though neither is
  a grep-versus-documentation test.

## 9. Evidence quality and tooling caveat

- **WebFetch on PDFs returned unreliable summaries** in this session: for arXiv 2606.22417, 2602.11988 and
  2508.02611 the PDF path produced tables or conclusions that contradicted the paper (an invented results
  table, and an AGENTS.md summary claiming gains). Anything below marked "read directly" was verified by
  opening the page images with the Read tool: LocAgent Tables 3-4, SweRank Table 1, SWE-PolyBench Tables
  2-6, Agentless Tables 1-2, Meta-RAG Tables 1-2, SchrodingerRepo abstract and Tables I-III,
  AGENTS.md abstract/Tables 1-3/Figures 3-4, Code Isn't Memory abstract, SWE-Pruner Figure 2, Dit et al.
  Table 1. **Everything else is a single pass of an HTML summary** and has the same risk: ContextBench,
  SWE-Explore, LinuxFLBench, Live-kBench, Code Researcher, LoLBench, CoSIL, OrcaLoca, CodeGrep,
  SWD-Bench, Deep Agentic Search, MULocBench, SWE-bench Pro, SWE-rebench, FEA-Bench, Long Code Arena.
  The summarizer also mis-stated one count (SWE-PolyBench JavaScript 1,078 instead of 1,017, caught because
  the languages then do not sum to 2,110).
- **Most localization evidence is preprint.** Peer-reviewed in this note: SweRank (ICLR 2026),
  OrcaLoca (ICML 2025), FEA-Bench (ACL 2025), SWE-rebench V2 (ICML 2026), Bench4BL (ISSTA 2018), Dit et
  al. (MSR 2013), Herbold et al. (EMSE 2022). The Illusion paper is a workshop poster.
- **Vendor evidence**: Code Isn't Memory (SuperAGI, the index's vendor), CodeScaleBench (Sourcegraph),
  Cursor, turbopuffer. Every index-beats-grep number at scale comes from a party that sells the index.
- **Almost nothing reports run-to-run variance.** Single attempts are the norm (AGENTS.md paper, LoLBench,
  ContextBench); the pilot's 10x cell is not out of line with the little that is reported.
- **Metric heterogeneity**: "file-level localization" is Acc@k over a ranked list (LocAgent, SweRank),
  correctness of the final patch's location (Agentless, Meta-RAG), subset-of-predicted match (OrcaLoca)
  or recall/precision of edited files (SWE-PolyBench). Do not compare across papers.

## 10. Open questions and leads

1. **Which repository.** The operator's ~10M-line codebase is the only candidate that is large and unseen;
   whether its code may go to the API for an evaluation is an operator question.
2. **Release status of LoLBench and CTXBench** (data, licence) was not established; check the papers'
   repositories before relying on either.
3. **Calibrate the screen**: pick three candidate repositories, run the first-tool-call screen, the
   issue-only path probe and a rename A/B (SchrodingerRepo code is public), and see whether the three agree.
4. **Compute the pilot's sigma** (per-question log-ratio SD, variance components) before fixing n; the
   0.6 above is from its range.
5. **A stale-document arm**: none of the studies tests whether a wrong or outdated generated document costs
   more than none; K14's staleness signal in the result is what such an arm would exercise.
6. **RepoAtlas** (a September 2026 result quoted by a blog: +2.4 resolve points, -5.8% input tokens on
   Verified): **not found**, unverified.
7. SWE-bench Pro: per-repository file counts not verified; AgentSeal numbers are a forum post.
8. Kochhar et al. and the Dit survey itself were not opened (abstract-level only for the survey, a
   secondary summary for Kochhar).
9. Loc-Bench's repository list: not given in the paper or the README; possibly in the HF `repo` field.
10. `design/evaluation.md` §5 sizes its sequential memory A/B for resolve rate; this note's arithmetic is
    for a localization-cost A/B and does not replace it.

## 11. Method

Searches (WebSearch, standard mode unless noted): Loc-Bench/LocAgent; SweRank; OrcaLoca; CoSIL; Agentless
localization; SWE-PolyBench retrieval metrics; Long Code Arena bug localization; FEA-Bench; SWE-bench Pro
repositories and contamination critique; SWE-rebench; Bench4BL; Dit feature location benchmarks (x2);
Meta-RAG; Neurosymbolic/keyword shortcut; issue-localization leakage; SWE-bench Illusion probes; benchmark
mutation; obfuscated identifiers memorization; repository layout memorization probe; LLM layout
prediction; "Am I in the Stack"; Cursor semantic search; agentic grep vs embedding; generated repository
documentation; AGENTS.md evaluation; LLM-generated documentation ablation; NoCode-bench/FeatBench; SWE-QA;
large-repository localization benchmarks (**extended mode**); monorepo scale; Chromium/Firefox; Google/Meta
monorepo; trajectory exploration efficiency; localization efficiency RL papers; "76.1%" token share;
SWE-rebench V2; Herbold tangling; Kochhar biases; CTXBench release; LoLBench release; ContextBench release.
WebFetch on arXiv abstract and HTML pages for every cited paper, then the Read tool on the saved PDFs for
the tables marked "read directly". Dead ends: the William and Mary benchmark pages returned 404; the
Illusion ICSE page and the Bench4BL ISSTA page timed out; the SWE-bench Pro Harbor page did not list task
or repository counts.

## Sources

1. LocAgent: Graph-Guided LLM Agents for Code Localization, Chen et al., arXiv 2503.09089 (v2 Apr 2025) - https://arxiv.org/abs/2503.09089
2. Loc-Bench_V1 dataset card (560 rows) - https://huggingface.co/datasets/czlll/Loc-Bench_V1
3. LocAgent repository (Apache-2.0) - https://github.com/gersteinlab/LocAgent
4. MTEB LocBenchRR dataset card (MIT) - https://huggingface.co/datasets/mteb/LocBenchRR
5. SweRank: Software Issue Localization with Code Ranking, Reddy et al., arXiv 2505.07849, ICLR 2026 - https://arxiv.org/abs/2505.07849
6. OrcaLoca: An LLM Agent Framework for Software Issue Localization, Yu et al., arXiv 2502.00350, ICML 2025 (PMLR v267) - https://arxiv.org/abs/2502.00350
7. CoSIL: Issue Localization via LLM-Driven Iterative Code Graph Searching, Jiang et al., arXiv 2503.22424 - https://arxiv.org/abs/2503.22424
8. Agentless: Demystifying LLM-based Software Engineering Agents, Xia et al., arXiv 2407.01489 - https://arxiv.org/abs/2407.01489
9. SWE-PolyBench, Rashid et al. (Amazon), arXiv 2504.08703, Apr 2025 - https://arxiv.org/abs/2504.08703
10. SWE-PolyBench repository and dataset (MIT) - https://github.com/amazon-science/SWE-PolyBench ; https://huggingface.co/datasets/AmazonScience/SWE-PolyBench
11. Long Code Arena: a Set of Benchmarks for Long-Context Code Models, arXiv 2406.11612 - https://arxiv.org/abs/2406.11612
12. FEA-Bench, Li et al., arXiv 2503.06680, ACL 2025 - https://arxiv.org/abs/2503.06680
13. SWE-Bench Pro, Deng et al. (Scale AI), arXiv 2509.16941 (rev Nov 2025) - https://arxiv.org/abs/2509.16941
14. AgentSeal: A Corpus-Availability Audit of SWE-bench Pro, kyoO7, 30 Jun 2026 (community forum post) - https://discuss.huggingface.co/t/agentseal-a-corpus-availability-audit-of-swe-bench-pro/177267
15. SWE-bench Pro on Harbor - https://hub.harborframework.com/datasets/scale-ai/swe-bench-pro
16. SWE-rebench, Badertdinov et al., arXiv 2505.20411 (rev Nov 2025) - https://arxiv.org/abs/2505.20411
17. SWE-rebench V2, arXiv 2602.23866, ICML 2026 (PMLR v306) - https://arxiv.org/abs/2602.23866
18. SWE-bench Goes Live!, Zhang et al., arXiv 2505.23419 - https://arxiv.org/abs/2505.23419
19. Bench4BL, Lee et al., ISSTA 2018 - https://research.knu.ac.kr/en/publications/bench4bl-reproducibility-study-on-the-performance-of-ir-based-bug/ ; https://github.com/exatoa/Bench4BL
20. A Dataset from Change History to Support Evaluation of Software Maintenance Tasks, Dit, Holtzhauer, Poshyvanyk, Kagdi, MSR 2013 - https://www.cs.wm.edu/~denys/pubs/MSR'13-DataPaper-FLBenchmarksV16-CRC FINAL.pdf ; survey: Feature Location in Source Code: A Taxonomy and Survey, JSEP 25(1), 2013 - https://experts.boisestate.edu/en/publications/feature-location-in-source-code-a-taxonomy-and-survey/
21. The SWE-Bench Illusion, Liang, Garg, Zilouchian Moghaddam, arXiv 2506.12286 (v4 Dec 2025); NeurIPS 2025 LAW workshop poster - https://arxiv.org/abs/2506.12286 ; https://neurips.cc/virtual/2025/137177
22. Does SWE-Bench-Verified Test Agent Ability or Model Memory?, Prathifkumar, Mathews, Nagappan, arXiv 2512.10218, Dec 2025 - https://arxiv.org/abs/2512.10218
23. Schrodinger's Code Repository: Have LLMs Learned SWE-bench or Memorized It?, Chen et al., arXiv 2609.27891, 21 Aug 2026; code https://github.com/cslsolow/Schrodinger-Repo - https://arxiv.org/abs/2609.27891
24. Neurosymbolic Repo-level Code Localization (KA-LogicQuery, LogicLoc), Xu et al., arXiv 2604.16021 - https://arxiv.org/abs/2604.16021
25. A Benchmark for Localizing Code and Non-Code Issues in Software Projects (MULocBench), Zhang et al., arXiv 2509.25242 - https://arxiv.org/abs/2509.25242
26. ContextBench: A Benchmark for Context Retrieval in Coding Agents, Li et al., arXiv 2602.05892, Feb 2026 - https://arxiv.org/abs/2602.05892 ; data https://huggingface.co/Contextbench
27. SWE-Explore: Benchmarking How Coding Agents Explore Repositories, Zhang et al., arXiv 2606.07297, 5 Jun 2026 - https://arxiv.org/abs/2606.07297
28. Evaluating AGENTS.md: Are Repository-Level Context Files Helpful for Coding Agents?, Gloaguen et al. (ETH Zurich, LogicStar), arXiv 2602.11988 (v3 29 Sep 2026) - https://arxiv.org/abs/2602.11988
29. Code Isn't Memory: A Structural Codebase Index Inside a Coding Agent, Bhola et al. (SuperAGI Research), arXiv 2606.22417, 21 Jun 2026; data https://github.com/TransformerOptimus/supercoder-eval - https://arxiv.org/abs/2606.22417
30. CodeScaleBench blog, Sourcegraph - https://sourcegraph.com/blog/codescalebench-testing-coding-agents-on-large-codebases-and-multi-repo-software-engineering-tasks
31. CodeScaleBench repository (Apache-2.0) - https://github.com/sourcegraph/CodeScaleBench
32. Why coding agents fail in large codebases, Sourcegraph blog - https://sourcegraph.com/blog/why-coding-agents-fail-large-codebases
33. Improving agent with semantic search, Cursor blog, 6 Nov 2025 - https://cursor.com/en-US/blog/semsearch
34. Benchmarking semantic code retrieval on Claude Code, K. Rogut (turbopuffer), AI Engineer Europe 2026 - https://ai.engineer/talks/zKk7sDMGDEQ-benchmarking-semantic-code-retrieval-on-claude
35. Benchmarking and Enhancing LLM Agents in Localizing Linux Kernel Bugs (LinuxFLBench), arXiv 2505.19489 - https://arxiv.org/abs/2505.19489
36. Outrunning LLM Cutoffs: A Live Kernel Crash Resolution Benchmark for All (Live-kBench), arXiv 2602.02690 - https://arxiv.org/abs/2602.02690
37. Code Researcher: Deep Research Agent for Large Systems Code and Commit History, Microsoft Research, arXiv 2506.11060 - https://arxiv.org/abs/2506.11060
38. LoLBench: Evaluating Coding Agents with Long-Horizon Proposals on Large Software Systems, Peng et al., arXiv 2609.37143, 29 Sep 2026 - https://arxiv.org/abs/2609.37143
39. Meta-RAG on Large Codebases Using Code Summarization, JPMorgan AI Research, arXiv 2508.02611; ICSE 2026 AGENT workshop listing - https://arxiv.org/abs/2508.02611
40. Natural Language Summarization Enables Multi-Repository Bug Localization by LLMs in Microservice Architectures, Oskooei et al., arXiv 2512.05908, LLM4Code at ICSE 2026 - https://arxiv.org/abs/2512.05908
41. Evaluating Repository-level Software Documentation via Question Answering and Feature-Driven Development (SWD-Bench), Wang et al., arXiv 2604.06793 - https://arxiv.org/abs/2604.06793
42. Deep Agentic Search for Repository-Level Code Question Answering: An Empirical Study, Oskooei et al., arXiv 2608.01507, 2 Aug 2026 - https://arxiv.org/abs/2608.01507
43. CodeGrep: An RL-Trained Retrieval Agent for LLM Coding Agents, Chen et al., arXiv 2608.05886, 6 Aug 2026 - https://arxiv.org/abs/2608.05886
44. Codebase-Memory: Tree-Sitter-Based Knowledge Graphs for LLM Code Exploration via MCP, Vogel et al., arXiv 2603.27277 - https://arxiv.org/abs/2603.27277
45. SWE-Pruner: Self-Adaptive Context Pruning for Coding Agents, Wang et al., arXiv 2601.16746 (v4 May 2026) - https://arxiv.org/abs/2601.16746
46. FastContext: Training Efficient Repository Explorer for Coding Agents, arXiv 2606.14066 (v4 withdrawn) - https://arxiv.org/abs/2606.14066
47. A fine-grained data set and analysis of tangling in bug fixing commits, Herbold et al., Empirical Software Engineering 2022 - https://www.swe.informatik.uni-goettingen.de/node/3024
48. Potential biases in bug localization (Kochhar et al., 2014) and replication, via a secondary search summary; Gotta catch 'em all! Towards File Localisation from Issues at Large, arXiv 2507.18319 - https://arxiv.org/abs/2507.18319
49. NoCode-bench / Doc2Feat-Bench, arXiv 2507.18130; FeatBench, arXiv 2509.22237 (search-result summaries only) - https://arxiv.org/abs/2507.18130 ; https://arxiv.org/abs/2509.22237
50. SWE-QA: Can Language Models Answer Repository-level Code Questions?, arXiv 2509.14635 - https://arxiv.org/abs/2509.14635
51. SWE Atlas: Benchmarking Coding Agents Beyond Issue Resolution, arXiv 2605.08366 (8 May 2026) - https://arxiv.org/abs/2605.08366
52. CodeScout: An Effective Recipe for Reinforcement Learning of Code Search Agents, arXiv 2603.17829 - https://arxiv.org/abs/2603.17829 (abstract only; not used for numbers)
53. RepoProbe: Benchmarking Architecture-Aware Repository Comprehension with Checklists, arXiv 2608.04783 (known only from a secondary blog, https://codex.danielvaughan.com/2026/08/08/repoprobe-edit-bias-architecture-aware-repository-comprehension-codex-cli-exploration-plan-mode/; unverified)
54. From leaderboards to profiles, JetBrains Junie blog, Aug 2026 - https://blog.jetbrains.com/junie/2026/08/from-leaderboards-to-profiles/
55. Probe-and-Refine Tuning of Repository Guidance for Coding Agents, Shepard and Albrecht, arXiv 2606.20512 - https://arxiv.org/abs/2606.20512
56. SWE Context Bench: A Benchmark for Context Learning in Coding, arXiv 2602.08316 - https://arxiv.org/abs/2602.08316
57. When Names Disappear: Revealing What LLMs Actually Understand About Code, arXiv 2510.03178 - https://arxiv.org/abs/2510.03178
58. In-repository: `research/coding-agent-experience-benchmarks.md`, `research/agentic-eval-methodology.md`, `design/evaluation.md`, `design/code-knowledge.md`, `FINDINGS.md`
59. Am I in The Stack (BigCode) - https://huggingface.co/spaces/bigcode/in-the-stack
60. FaultLoc: Evaluating Coding Agents For Fault Localization, Tu et al., ICML 2026 listing (abstract page only) - https://icml.cc/virtual/2026/67968
