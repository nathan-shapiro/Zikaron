# Prior art: generated repository documentation, and whether it helps an agent localize

Researched 2026-10-13 for M40's brainstorm (`design/code-knowledge.md` §3). Written by memory-assistant.
Companion notes, not repeated here: `design/evaluation.md` §4.1 (CTIM-Rover, 42% -> 31% on 45
SWE-bench Verified issues), `research/kiro-knowledge-tool.md`, `research/coding-agent-experience-benchmarks.md`
§D, `research/code-knowledge-sizing.md` (the 2.5x-first-build churn figure for `zikaron/`).

## 0. The brief, restated

M40 proposes a producer: subagents write one markdown document per source file
(`code-knowledge/<module>/<path>/<file>.<ext>.md`; purpose, non-trivial symbols, what is not
obvious, forward dependencies only) plus a module README. A deterministic planner compares hashes
and the model rewrites only what is missing or stale. The consumer is a coding agent told to search
this corpus (hybrid BM25 + bge-small, RRF) before grepping, and to treat a `changed` result (K14)
as a lead. Motivating evidence is the operator's anecdote on a ~10M-line codebase. Questions: A prior
art on systems that generate NL documentation of a repository; B whether such documentation helps
localization or task completion; C staleness; D cost and cadence; E what a document should contain.

## 1. Bottom line

1. **Nobody has published a controlled measurement of the exact M40 pattern** (a per-file, NL,
   hash-linked corpus searched by an agent that can also grep) on an end-task metric. What exists is
   (a) localization/retrieval results for LLM-written file summaries, mostly small, mostly on
   benchmarks whose repositories models have seen; (b) two negative or null results for
   LLM-written, always-loaded repository overviews; (c) vendor claims.
2. **Localization evidence for file-level summaries is positive but modest and mixed.** The most
   careful study (Caumartin et al., Jul 2026) finds 1-2-sentence "role-aware" file summaries beat
   path-only retrieval (abstract: up to +40% relative Hit@5; its Table 2 shows +55% in one BM25 cell) at 1/10-1/20 the token footprint of raw code,
   but raw code still wins on Python SWE-bench Verified for 4 of 5 retrievers, and a richer 6x larger
   summary gave no consistent gain. Fusing summaries with raw code (RRF) beat either alone in most cells.
3. **Hierarchy matters more than per-file richness** in the one ablation that tests it (Rafiei
   Oskooei et al., ICSE 2026): removing directory-level routing cost MRR -54%, Recall@10 -37%,
   Pass@10 -18% and added 44% tokens. This supports per-module routing, and says nothing against per-file.
4. **LLM-generated repository overviews did not help localization and raised cost** (Gloaguen et
   al., v3 29 Sep 2026): resolution -0.5 pts (SWE-bench Lite, 300 tasks) and -2 pts (CTXBench, 138
   tasks), both not significant; cost +20% / +23%; steps before first touching a gold-patch file not reduced.
   Developer-written files were +2.4 pts, not significant against none (p = 0.21) but significant against LLM-written (p = 0.038).
5. **The "agentic search beat vector RAG" statements are vendor self-report with no published
   ablation**: Claude Code's creator on Latent Space (7 May 2025), Anthropic's own blog (14 May 2026),
   Cline's blog (27 May 2025, no numbers at all). The opposing vendor claim is Cursor's (6 Nov 2025):
   semantic search + grep beats grep, +12.5% mean accuracy (6.5-23.5% by model), larger on codebases of 1,000+ files.
6. **Drift is common and cheap to detect for identifiers; cost to agents is unmeasured.** More than a
   quarter of the 1,000 most popular GitHub projects carry at least one outdated code-element reference; 23.0% of 356
   sampled repos' AI context files do. No study measures what a stale generated document costs a coding agent;
   the nearest result (Macke & Doyle, NAACL Findings 2024) says incorrect documentation hurts LLM code
   understanding while missing documentation barely does. **K14 handles drift; nothing handles a document that was wrong when written** (about 1 in 5 LLM-generated Java comments contained a demonstrably inaccurate statement, Kang et al. 2024).
7. **Nothing measured approaches 10M lines.** Largest repositories in the evidence: Trino 988,722
   lines (Caumartin), ~1.1M lines / 7,077 files (Oskooei), 1.4M LOC (CodeWiki's benchmark, via
   fetch summary), 26,602 files (Gloaguen's largest). The proposal's scale is >=7x beyond all of them.

## 2. Evidence legend

- **R** = I read the source directly (PDF pages rendered, or a full docs page) and checked the numbers.
- **F** = fetched page, answered through the fetch tool's summarizer; numbers not independently checked.
- **S** = search-result snippet only; not opened.

**Fetch-summarizer reliability warning, observed twice this session.** A fetch of the Caumartin PDF
returned a confident results table whose numbers and setup (GPT-3.5, "dependency-aware" and
"execution-aware" summaries) did not exist in the paper; reading the rendered pages gave the real
design. A re-query of Meta-RAG's HTML corrected a wrong repository/token pairing in an earlier
summary. Every number below that the decision rests on is tagged R or was cross-checked against an
abstract. Treat F numbers as leads.

## 3. Part A: systems that generate NL documentation of a repository

### 3.1 Table: what, how, trigger, cost, scale, measured effect

| System | Generates | How | Regeneration trigger / staleness | Cost | Largest repo run | Measured effect (baseline) | Class, tag |
|---|---|---|---|---|---|---|---|
| **RepoAgent** (OpenBMB; arXiv 2402.16667, EMNLP 2024 demo) | Per code object (class/function) doc: functionality, parameters, code description, notes, examples; Markdown, GitBook-rendered | Jedi + AST project tree; caller/callee graph; **bottom-to-top topological order** so referenced objects are documented first | **Git pre-commit hook**: regenerates an object whose source changed, that **gains** referrers, or **loses** referrers; deliberately does *not* regenerate when a callee changes ("dependency inversion"); state in a `.project_doc_record` JSON (README); Python only | gpt-4-0125 totals: AutoGen (64 classes, 590 functions) 5.46M tokens; AutoGPT (318 / 1,170) 5.0M; ChatDev 2.6M. Per object ~3.4k-8.3k tokens (derived). Doc length 0.4k-1k tokens/object | 9 Python repos, largest ">=10k LOC" (paper); README mentions a ~270k-line project (README claim) | Blind human preference for its docs over originals: 70% (Transformers), 91.33% (LlamaIndex); reference-recall ~97-99%. **No agent task measured** in the paper. Authors flag Python-only and need for human review | Peer-reviewed demo + preprint; F (HTML table and README) |
| **DocAgent** (Meta; arXiv 2504.08725, ACL 2025 demo) | Docstrings for Python components (summary, description, Args/Returns/Raises, examples) | **Navigator** builds an AST dependency DAG, Tarjan cycle handling, **topological order, dependencies first**, one-hop context; five agents: Reader, Searcher, Writer, Verifier, Orchestrator | None described: it is a generator, not a maintainer | Not reported in what I read (only ~500 tokens per LLM-judge evaluation) | 9 Python repos, 366 components; size not given | Completeness 0.934 (GPT-4o-mini DocAgent) vs 0.815 chat baseline; helpfulness 3.88 vs 2.95; truthfulness (existence ratio of referenced identifiers) 95.74% vs 61.10%. **Ablation: random instead of topological order** drops helpfulness 3.88 -> 3.44 and truthfulness 94.64 -> 86.75. No downstream agent task | Preprint + demo; F |
| **DeepWiki** (Cognition) | Wiki pages per topic/system cluster, architecture diagrams, source citations; chat over it | Per a Cognition talk summarized by ZenML: heuristic scoring of files and connections (directory structure, symbol graphs, git history, runtime data) -> codebase graph -> clustering -> v2 "agentic core" that decides what more to read; the hard part is the table of contents | Primary sources I could open do **not** state a refresh trigger; third-party text says paying users get per-commit incremental updates and the free product refreshes badge repos (**unverified**). Steering via `.devin/wiki.json` (<=30 pages; 80 enterprise) | Free tier "low" effort; medium ~5-10 ACUs and high ~20-40 ACUs per wiki (Devin docs) | 50,000+ top public repos at launch (Cognition blog); 1.4M repos and 20M+ queries (talk, via ZenML). Largest single repo: not stated | **None published.** Cognition tracks coverage of active files, citation depth and keeps wiki size stable, but gives no effect on Devin | Vendor blog + vendor docs + secondary summary; F |
| **Google Code Wiki** | Structured wiki, architecture/class/sequence diagrams, chat agent linking to code | Gemini over the repository | Vendor says it "scans the full codebase and regenerates the documentation after each change" (public preview 13 Nov 2025) | Not stated | Public GitHub repos; size not stated | **None.** The announcement offers claims about onboarding speed without data | Vendor blog; F |
| **CodeWiki** (FPT/Melbourne; arXiv 2510.24428, v5) | Repository-level docs with architecture/data-flow/sequence diagrams | Top-down decomposition into modules (leaf ~32,768 tokens, delegation depth 3), bottom-up documenting of leaves, then parent synthesis; topological sort | Not specified | Not specified | 1.4M LOC (C, wazuh) | CodeWikiBench rubric score 68.79% vs DeepWiki 64.06% average over 7 repos; judged by LLMs. **A document-quality benchmark, not an agent-effect one** | Preprint; F |
| **Swimm** | Human-authored docs coupled to code snippets, tokens, paths | Authors couple; tool tracks | **CI check on every PR**: "Auto-sync" updates minor drift and, if it cannot, fails the check or opens an issue and marks the doc potentially out of date (vendor docs). Signals per Swimm's blog snippet: line markers, token references, file history (**S**) | Not stated | n/a | **No numbers** in the docs I opened | Vendor docs; F |
| **Aider repo map** | Not prose: file list plus the most-referenced symbol signatures | tree-sitter tags; graph where files are nodes and dependencies edges, ranked; fits a token budget (`--map-tokens`, default 1k, grows dynamically) | The pages I read describe no staleness handling and say nothing on caching; the map is sized to the chat's state | 1k tokens default | n/a | No ablation in the Aider pages. **Independent evidence**: Agent Retrieval Bench (Jul 2026) found RepoMap gave the best budgeted context yield at 8K tokens among BM25, embeddings and agent logs | Vendor docs; F + S |
| **Claude Code `/init`** | A starter `CLAUDE.md`: build/test commands, conventions it discovers | Agent explores the repo; optional `CLAUDE_CODE_NEW_INIT=1` runs a multi-phase flow with an exploring subagent, follow-up questions and a reviewable proposal | If a `CLAUDE.md` exists, `/init` proposes improvements rather than overwriting. `/doctor prompt-audit` (v2.1.283+) flags references to files or commands that no longer exist. Guidance: under 200 lines, review edits in PRs | Not stated | n/a | None measured by vendor. Gloaguen et al. measured `/init`-style generation (see §4.1) | Vendor docs; **R** |
| **kiro steering generation** | `product.md`, `tech.md`, `structure.md` | "Generate Steering Docs" button in the Steering panel | Docs advise review at sprint planning and treating steering edits like code; **no automated staleness detection** | Not stated | n/a | None | Vendor docs; F |
| **OpenHands repo microagent / `AGENTS.md`** | `.openhands/microagents/repo.md` (now documented as skills / `AGENTS.md`); an `/init` skill writes `AGENTS.md` at root or scoped to a path | Agent analyzes repo; prompt-driven | Always loaded into context; **no staleness handling documented** | Not stated | n/a | None | Vendor docs; F + S |
| **llms.txt** (Jeremy Howard, 3 Sep 2024) | One Markdown index file at a site root: title, summary, links to LLM-friendly pages | Authored or generated by docs platforms | None | None | n/a | **No agent-effect measurement found.** Ahrefs (Jun 2026, 137,210 domains, May 2026 traffic): 28% publish one, 97% of those got zero requests; AI bots never probed for absent files. A web-crawler study, so only analogical for coding agents. Anthropic's own docs pages open with an instruction to fetch their `llms.txt` index first | Spec + third-party SEO vendor study; F |

**Verification of the recollections in the brief.**

- RepoAgent incremental update via a git pre-commit hook: **verified** (paper and README), with
  the refinement that triggers are source change, lost referrers and gained referrers, and *not*
  callee change.
- DocAgent topological dependency ordering, multi-agent: **verified**; five agents, one-hop context,
  ordering ablation measured.
- DeepWiki, Code Wiki, Swimm, Aider, `/init`, kiro steering, OpenHands, llms.txt: **all exist and
  behave roughly as recalled**; the gaps are in what is *documented*: no refresh trigger for
  DeepWiki, no cost for Code Wiki, no measured effect for any of the commercial ones.

### 3.2 Research systems that summarize a repository for retrieval or localization

| System | What it builds | Result and baseline | Scale / cost | Class, tag |
|---|---|---|---|---|
| **Meta-RAG** (arXiv 2508.02611; ICSE 2026 AGENT workshop listing) | Hierarchical summaries (file one-liner, then class and function entries with signatures; imports omitted); AST-checked; a control LLM short-lists files from the one-liners and descends | SWE-bench Lite (300), GPT-4o only: **84.67% file-level, 53.0% function-level** localization. Baselines in the same paper: BM25-Lucene 33.67/13.00, BM25-Plus (50K tokens) 60.00/25.33, Agentless 1.5 69.67/37.00. **No ablation of summary content, and no raw-code arm inside Meta-RAG's own pipeline** | Summaries are 79.8% smaller than code (mean; ~1/5 of code tokens). **Incremental update by git diff** between consecutive instances: per-repo mean 57.9% fewer code tokens to summarize than resummarizing (my arithmetic on the table totals, 138.6M of 605.6M tokens, gives 77.1% token-weighted). Cost per task instance $0.97 mean, $1.92 on SymPy (Aug 2024 OpenAI prices) | Preprint; F (Table 1 re-queried and cross-read) |
| **Rafiei Oskooei et al.** (arXiv 2512.05908, ICSE 2026, 5 Dec 2025) | Bottom-up NL knowledge base: repo seed summary (tree + code + OCR'd docs), file summaries primed with the seed, directory aggregates; LLM routes repo -> directory -> file | DNext, one industrial Java system: 46 repos, ~1.1M lines, 7,077 files, **87 tickets**, 7.2 buggy files per ticket, all arms gpt-4.1. Pass@10 / Recall@10 / MRR: **ours 0.82 / 0.49 / 0.50**; Cursor 0.57 / 0.49 / 0.27; GitHub Copilot 0.61 / 0.27 / 0.25; GraphCodeBERT 0.62 / 0.34 / 0.18; UniXcoder 0.23 / 0.16 / 0.14. **Ablation: no directory filtering -> 0.67 / 0.31 / 0.23, +44% tokens.** Copilot/Cursor were run in interactive Chat/Ask mode in the IDE, so the baselines are not a controlled agent harness | **~$80** to summarize everything (gpt-4.1-mini) = ~$0.011/file or ~$73/MLOC (derived). Regenerated **after each major release, not each commit**, on the authors' argument that purpose and architectural role change slowly (not measured). They list incremental scheduling as future work | ICSE 2026 paper as formatted in the arXiv version; **R** |
| **Caumartin et al.** (arXiv 2607.11046, 13 Jul 2026) | Five file-level representations: paths (STRUCT), raw source, and three LLM summaries made with GPT-OSS-20B: role-aware (1-2 sentence role and main classes), detailed technical (purpose, APIs, dependencies, errors, patterns, identifiers), five synthetic bug reports per file | Long Code Arena bug localization (150 tasks, Python/Java/Kotlin) and SWE-bench Verified (500). Full results in §4.3 | 650 repos summarized for **$1,007.10 total** (all three summary types; Groq prices Jan 2026: $0.075 / $0.30 per M in/out): $1.82 per repo (LCA), $1.47 (SWE). Trino, 988,722 lines, is the largest repo | Preprint; **R** (pp.1-24) |
| **RepoUnderstander / LingmaAgent** (arXiv 2406.01422) | Repository knowledge graph (structure tree + call graph, no NL in the graph) + MCTS exploration + a summary agent that writes NL digests of gathered code during patch generation | SWE-bench Lite, GPT-4-Turbo: **21.33% resolved** vs SWE-agent 18.00% (+18.5% relative) and AutoCodeRover 16.11%. Ablation: without call graph 19.67%; **without the summary module 17.67%**; without MCTS and summary 16.00%. Cost $3.99 vs $2.51 per issue. The summary module is query-time digesting, not a pre-generated corpus | 300 issues; cost as shown | Preprint; F |
| **CodexGraph** (arXiv 2408.03910, NAACL 2025) | Graph database of code entities queried by the agent in Cypher; no NL summaries | SWE-bench Lite GPT-4o 22.96%, equal to AutoCodeRover; DeepSeek-Coder-V2 12.06% vs AutoCodeRover 15.56%. Tokens 102.25k vs 76.01k (AutoCodeRover) vs 14.76k (BM25) | n/a | Peer-reviewed; F |
| **RepoGraph** (arXiv 2410.14684) | Line-level code graph (tree-sitter), k-hop ego-graph as plug-in context | SWE-bench Lite: RAG 2.67 -> 5.33; Agentless 27.33 -> 29.67; AutoCodeRover 19.00 -> 21.33; SWE-agent 18.33 -> 20.33. **Ablation:** 1-hop raw 29.67 beats 1-hop LLM-summarized 28.33; 2-hop raw 26.00 vs 2-hop summarized 28.67, so summarizing lost information at 1 hop and de-noised at 2 | ~5k extra tokens for procedural frameworks | Preprint; F |
| **Code-Craft / HCGS** (Cisco; arXiv 2504.08975) | Bottom-up summaries over an LSP-derived code graph | Up to 82% relative gain in top-1 retrieval precision on a large codebase (libsignal, +27.15 pts) vs "code-only" retrieval (baseline detail not read); 5 codebases, 7,531 functions | n/a | Preprint; F |
| **RepoRepair** (arXiv 2603.01048) | Hierarchical function-to-file documentation (DeepSeek-V3) guiding localization, Claude-4 repairs | SWE-bench Lite 45.7% at $0.44 per fix; Multimodal 37.1% at $0.56. The abstract page has **no documentation-off ablation numbers** | n/a | Preprint; F |
| **Agent4cs** (arXiv 2607.01425, EUMAS 2026) | Multi-agent bottom-up folder summaries with keyword extraction and QA | Folder/subfolder summary consistency +8%, keyword coverage up to +38% over structured-prompting baselines. **Measures summary quality, not agent outcomes** | n/a | Peer-reviewed venue; F |
| **Greptile** (blog, 15 Apr 2025) | AST nodes -> generated NL docstrings -> embeddings | One query: cosine to code 0.7280 vs to its NL description 0.8152; function-level chunk beats file-level (0.768 vs 0.739). **A single illustrative pair, not a retrieval metric** | n/a | Vendor blog; F |

## 4. Part B: does NL documentation help an agent, versus raw code, grep or a structural map?

### 4.1 Context files (AGENTS.md / CLAUDE.md): Gloaguen et al., arXiv 2602.11988 (**R**, v3, 29 Sep 2026)

Authors from ETH Zurich and LogicStar.ai. Preprint (ICLR 2026 virtual-site listings exist; venue and track not verified).

- **Setup.** Four agents: Claude Code + Sonnet-4.5, Codex + GPT-5.2 and GPT-5.1 mini, Qwen Code +
  Qwen3-30B-Coder. Benchmarks: SWE-bench Lite (300 tasks, 11 popular repos, none with developer context
  files) and **CTXBench** (138 instances from 12 niche Python repos that carry a developer-committed context file;
  called AGENTbench in v1 of the paper). CTXBench repos average 3,337 files (151-26,602). Conditions: none, LLM-generated using each agent's own
  recommended init command and model, developer-written (CTXBench only). **One sample per agent per condition**, so the
  differences below sit inside the 2.2-6.0 point single-run spread `design/evaluation.md` records for agent scaffolds.
- **Success.** LLM-generated: **-0.5 pts (SWE-bench Lite), -2 pts (CTXBench)** on average, drops in 5 of 8 settings; Cochran-Mantel-Haenszel p = 0.87 and 0.37.
  Developer-written: **+2.4 pts on average (p = 0.21 vs none)**, improving all agents but Claude Code; developer-written vs
  LLM-generated p = 0.038. (The paper's introduction says 7%; section 4.2 and Table 3 give the figures above. I report section 4.2.)
- **Cost.** LLM-generated files raised steps by 2.45 (SWE) and 3.92 (CTX) and cost by 20% and 23% on average (reported p < 0.001);
  developer-written +3.34 steps and up to +19%. Example per-instance cost, Sonnet-4.5 SWE: $1.30 -> $1.51; GPT-5.2 CTXBench $0.38 -> $0.57.
- **Overviews do not locate files faster.** 100% of Sonnet-4.5-generated files, 99% (GPT-5.2) and 95% (Qwen) contained a codebase overview;
  8 of 12 developer files did. The metric "steps before the first interaction with a file in the gold patch" was **not meaningfully reduced**, and GPT-5.1 mini rose from ~18 to ~22 steps on SWE-bench. Claude Code's own init prompt
  tells the model to keep to a high-level overview and not list easily discoverable components.
- **Instructions are followed, and following costs.** A tool named in a context file was used ~1.6x per instance for `uv` and
  ~2.5x for repo-specific tools, versus under 0.01 and 0.05 when not named; more grep, more reading, more tests. GPT-5.2 reasoning tokens +22% (SWE) with LLM files.
- **Ablations.** A stronger model's context file helps a weaker model +2% on SWE-bench but -3% on CTXBench; the init prompt barely matters; length and instruction category barely matter.
  (From the v1 text, **F**, not re-found in v3: removing all other documentation from the repos raised LLM-generated-file performance by 2.7%, which the authors read as redundancy with existing docs.)
- **Authors' conclusion:** omit LLM-generated context files for now; human-written ones should hold only what is not already in the repository.
- **Limits.** Python only; single sample; always-loaded overviews, **not** a searchable on-demand corpus; models are strong and likely
  know the SWE-bench repos. Result is **third-party, preprint**.

**The recollection in the brief is verified in direction and over-stated in strength**: LLM-generated files lowered success and raised cost; developer-written files helped slightly. Neither success difference is significant against no file, and developer-written files also raised cost.

Related, smaller: **Lulla et al.** (arXiv 2601.20404, short paper; **F**): 10 repos, 124 PRs, Codex and Claude Code, with vs without `AGENTS.md`;
median runtime -28.64%, output tokens -16.58%, "comparable" completion; success rate not the measured outcome. It points the opposite way from Gloaguen's cost result, on
a different outcome and design (co-authors include Treude and Baltes, who wrote the drift paper below). **Chatlatanagulchai et al.** (arXiv 2511.12884; **F**) read
2,303 context files from 1,925 repos: architecture content in 68.1%, testing 75.9%, security 14.8%; the files evolve by frequent small additions.

### 4.2 "Agentic search (grep) beat vector RAG": primary sources and classification

| Statement | Primary source | What it actually claims | Class |
|---|---|---|---|
| Claude Code started with RAG over a local vector database (Voyage embeddings) and moved to agentic search | Boris Cherny and Cat Wu, **Latent Space** podcast, 7-8 May 2025 (transcript, F) | Agentic search "outperformed everything. By a lot"; RAG indexes drift out of sync and carry security cost; agentic search trades latency and tokens for no index. No numbers or benchmark named | **Vendor self-report**, spoken, no ablation |
| Same, restated | Anthropic blog, "How Claude Code works in large codebases", 14 May 2026 (F) | Agentic search needs no embedding pipeline or central index to maintain; RAG indexes go stale and return deleted modules with no freshness indicator; recommends layered CLAUDE.md, LSP code-intelligence plugins, subagents. **Says nothing about generated documentation freshness.** | Vendor blog |
| Same, restated | Anthropic docs "Set up Claude Code in a monorepo or large codebase" (**R**) | Per-directory CLAUDE.md, LSP plugins to avoid file scans, exploration in subagents; if an org already runs a RAG index, expose it as an MCP tool; admits per-directory files go stale and lose owners at scale | Vendor docs |
| Cline does not index | Cline blog, 27 May 2025 (F) | Qualitative: chunking tears logic apart, indexes decay, embeddings are a security surface. **Contains no numbers or benchmarks** (a "45% recall" figure that circulates in secondary posts is not in it) | Vendor blog, argument only |
| Boris Cherny's X post (reported 1 Feb 2026) | Not opened | Third-party posts relay it | **Unverified** |
| Pragmatic Engineer newsletter, 4 Mar 2026 | F, weak | Paraphrases the same line | Secondary |

**Counter-claims, equally vendor self-report:**

- **Cursor** (6 Nov 2025, F): on its internal Cursor Context Bench, semantic search on top of grep gives +12.5% mean accuracy answering questions
  (range 6.5-23.5% by model); in an A/B test, code retention +0.3% overall and **+2.6% on codebases of 1,000+ files**, and 2.2% more dissatisfied follow-ups
  when it was off. It does not separate grep-only from semantic-only. This indexes code, not NL docs.
- **"Code Isn't Memory"** (arXiv 2606.22417, 21 Jun 2026, F; authors link to a `TransformerOptimus/supercoder-eval` repo, so possibly product-adjacent, not verified): a tree-sitter vector + call-graph + BM25 index, 91 instances (34 Go, 20 Java, 37 Python), Claude Opus 4.7, 3 seeds. Localization acc@5 84.5% with the index vs 44.3% without it in the same harness vs 75.3% for an agentic-grep harness; resolve 50.4 / 41.9 / 45.3%; $/solve 2.30 / 2.84 / 2.92. Effective denominators 75-80, so the resolve differences are under-powered by the authors' own statement.
- **Independent benchmark direction.** SWE-Explore (arXiv 2606.07297, Jun 2026; 848 issues, 10 languages, 203 repos; abstract only) finds agentic explorers a clear tier above classical retrieval, with file-level localization already strong and **line-level coverage and ranking** the differentiators. Agent Retrieval Bench (arXiv 2607.24882, Jul 2026; 427 samples, 25 repos; abstract only) finds no retrieval family dominates, with embeddings best on MRR/Recall@20 and **RepoMap best at an 8K-token budget**.

Net: there is **no controlled evidence that grep beats embeddings or the reverse**; there is a vendor split, and
independent benchmarks in 2026 say agents already localize files well, so the remaining headroom is below file level.

### 4.3 Retrieval over NL descriptions versus retrieval over the code itself

Mixed, and it depends on the retriever and the language.

**Caumartin et al. (R), Hit@5, five retrievers; each cell is path-only / role-aware summary / raw code.** Summaries made by GPT-OSS-20B; index units are whole files (raw code is token-chunked for the dense models).

| Dataset | BM25 | GTE-Large | Qwen3-Emb | CodeXEmbed | BGE-Large |
|---|---|---|---|---|---|
| LCA (150 tasks) | .453 / .573 / .627 | .493 / .633 / .593 | .540 / .667 / .620 | .487 / .667 / .587 | .500 / .607 / .613 |
| SWE-bench Verified (500) | .284 / .440 / .676 | .522 / .696 / .526 | .626 / .626 / .768 | .516 / .664 / .732 | .504 / .664 / .732 |

- Summaries beat paths in nearly every cell (+15 to +17 absolute points on SWE for BM25, GTE, CodeXEmbed, BGE) and beat raw code on LCA for 3 of 4 dense retrievers. **Raw code beats summaries on Python SWE-bench for 4 of 5 retrievers** (BM25 .676 vs .440; Qwen3 .768 vs .626).
- Headline discrepancy to know about: the abstract says role-aware summaries beat paths "by up to 40%" Hit@5, while Table 2 shows +55% for BM25 on SWE (.284 -> .440); I report the table.
- Footprint: role-aware summaries are 10.4x (LCA) and 20.9x (SWE) smaller than raw code; raw code is 64.3x and 286.2x larger than paths. Derived (tasks x mean files per task, assuming the footprint counts every task's file set): ~120 tokens per summarized file versus ~1,230 (LCA) and ~2,540 (SWE) raw, and ~740-750 for the detailed technical summary.
- **Fusing representations with RRF helps**: raw + role-aware gains up to +8.9% Hit@5 on SWE for GTE-Large; raw + paths up to +31.9% (GTE, SWE) and +12.4% (CodeXEmbed, LCA); some retriever/representation pairs lose (BM25 on SWE with raw + paths: -18.9%). Gains are relative to the better single representation. The paper's closing line is that no single representation dominates.
- **Synthetic bug-report summaries were worse than paths in every first-stage cell**; the detailed summary was 6.2x larger than role-aware and not consistently better.
- With an LLM as retriever (Qwen2.5-Coder 7B/14B/32B, 16k context), role-aware summaries helped on both datasets only for the 32B model (+11.6% LCA, +10.2% SWE Hit@5) at 5.4-12.2x the path-only input tokens versus up to 259.5x for raw; 7B gained on LCA (+21.7%) and lost on SWE (-18.9%); 14B lost on both (-20.0%, -14.1%).
- Case study in Agentless's file stage on SWE-bench Verified: adding role-aware summaries + paths + raw: Hit@6 0.898 -> 0.918 (+2.2%); with LLM post-retrieval ranking 0.940 (+4.7%).

**Other positive evidence (all LLM-reads-summaries, small or single-system):** Oskooei (above; 87 tickets), Meta-RAG (SWE-bench Lite, memorized repos), Greptile (one cosine pair), Code-Craft (Cisco; baseline unread).

**Generation-augmented retrieval literature** (ReCo, ACL 2024, arXiv 2401.04514; **F** abstract): rewriting the *code in the codebase* into a normalized style raises sparse retrieval up to 35.7%, zero-shot dense 27.6% and fine-tuned dense 23.6%. That attacks the modality gap by code-to-code rewriting, not NL descriptions, so it neither supports nor refutes NL docs.

**Documentation as agent context (end task).**

- **SWD-Bench** (arXiv 2604.06793; **F**): SWE-Agent on **57** SWE-bench Verified issues, top 4,096 tokens of documentation retrieved per issue. No docs 43.86% (25/57); RepoAgent docs 52.63% (30/57, the "+20.00%"); DocAgent 49.12%; AutoDoc 49.12%; DeepWiki 47.37%. **Five issues separate the best arm from the baseline**, with no variance estimate, and the agent's model was not stated in the abstract or the text I retrieved. Same paper: giving the model RepoAgent docs *and* code (context split evenly) beat docs alone by relative 10.4% / 40.4% (B-ACC / MCC) on functionality detection and 12.4% / 12.9% on localization, so code and docs are complementary.
- **RepoRepair** (above): documentation-guided localization reaches 45.7% on SWE-bench Lite, but the abstract has no documentation-off ablation and the pipeline is model-confounded.
- **LingmaAgent**'s summary-module ablation (-3.7 pts when removed) is query-time digesting.
- **Gloaguen** (above): the closest controlled test of NL repository text as context, and negative for LLM-written overviews.
- **CTIM-Rover**: already in `design/evaluation.md` §4.1.

## 5. Part C: staleness and drift

### 5.1 Rates

| Finding | Number | Source, class, tag |
|---|---|---|
| Documentation with outdated code-element references | More than a quarter of the 1,000 most popular GitHub projects contain at least one outdated reference; across 3,000+ projects most have had one at some point in their history | Tan, Wagner, Treude, arXiv 2307.04291 (abstract) and Tan & Wagner, EMSE, arXiv 2212.01479; peer-reviewed + preprint; F |
| AI context files (CLAUDE.md, AGENTS.md, .cursorrules) | **23.0% of 356 sampled repos** have stale code-element references, found by an off-the-shelf README/wiki consistency checker | Treude & Baltes, "Context rot", arXiv 2606.09090, 8 Jun 2026; preprint; F |
| Comment/code co-evolution at scale | 1,500 Java projects, 3.3M commits, ~1.3B AST-level changes; developers' fix taxonomy from 500 commits. Earlier work cited there: 23%/52%/43% of comment changes in three projects were driven by code changes; 97% of those co-changed in the same revision | Wen et al., ICPC 2019 (**R**, pp.1-2) |
| Inconsistent changes and bugs | Inconsistent code-comment changes ~1.5x more likely to be bug-introducing | arXiv 2409.10781 (GPT-3.5 labelling), preprint; F |
| Generated comments' own accuracy | ~1 in 5 of the best LLM's generated Java-method comments (GPT-4) contained a demonstrably inaccurate statement; consistency checkers showed no significant relation to accuracy; executing LLM-written tests from the comment did | Kang, Milliken, Yoo, arXiv 2406.14836, Jun 2024; preprint; F |

Gap: **there is no published rate for "fraction of LLM-generated per-file documents wrong after N commits."** The proposal's own churn figure (`zikaron/`: 501 file-touches in 47 commits over 60 days across ~200 files) is the only churn datum in this note.

### 5.2 Detection

- **Identifier checks** work: DOCER-style detection of dangling code-element references (Tan et al.) and the same checker applied to AI config files (Treude & Baltes). Claude Code ships `/doctor prompt-audit` for the same class (references to missing files or commands).
- **JIT inconsistency detection** from a code change plus the comment (Panthaplackel et al., AAAI 2021, arXiv 2010.01625; S) is a trained classifier on comment/code pairs; it needs the diff.
- **Execution-based doc testing** (Kang et al.) is the only approach with a measured relation to *accuracy* rather than staleness.
- None of these is a hash check; a hash says "the source moved", not "the claim is false". K14's `changed` is the cheap, conservative signal.

### 5.3 How products key regeneration

| Product or system | Key |
|---|---|
| Cursor's code index | **Content hash**: a Merkle tree of per-file hashes (folder hashes from children) finds exactly what changed; teams reuse a teammate's index through a similarity hash over the tree, noting clones average 92% similar. This is for embeddings, not LLM-written text (Cursor blog, S) |
| RepoAgent | **Git commit** (pre-commit hook) plus the reference graph: source change, lost referrers, gained referrers |
| Meta-RAG | **Git diff** between consecutive commits; only changed code is resummarized |
| Swimm | **PR/CI check** over line markers, token references and file history; auto-sync for minor changes, hard fail otherwise |
| Code Wiki | "After each change", full regeneration (vendor wording; cost unknown) |
| DeepWiki | Not documented in the primary sources I could open |
| Oskooei et al. | **Release**, by the authors' stated plan |
| Zikaron K14 | Source blob hash against the hash in the document's front matter |

### 5.4 What stale documentation costs an agent: not measured

I found no study that feeds coding agents documentation made stale by real commits and measures task outcome. Closest evidence, all indirect:
Macke & Doyle (NAACL Findings 2024, arXiv 2404.03114; **F** abstract): incorrect documentation hindered LLM code understanding substantially, while incomplete or missing documentation did not; CTIM-Rover (already covered): noisy repo-scoped memory dropped resolution 11 points; Gloaguen: unnecessary context raised cost 20% even when it was true. Treat "a stale document costs more than no document" as plausible, supported by Macke & Doyle, and untested for agents.

## 6. Part D: cost and cadence

| Source | Unit cost | Notes |
|---|---|---|
| Oskooei et al. (**R**) | **~$80** total for 7,077 files / ~1.1M lines (gpt-4.1-mini): ~$0.011 per file, ~$73 per MLOC (derived) | File + directory + repo-seed summaries, repo seed contains the full source and OCR'd docs, so the figure includes that. One-time offline; regenerated per release |
| Caumartin et al. (**R**) | $1.82 per LCA repo, $1.47 per SWE repo for **three** summary types with a 20B open model at $0.075 / $0.30 per M tokens; $1,007.10 for 650 repos | Prices are Groq, Jan 2026. One summary type costs proportionally less |
| Meta-RAG (F, table re-queried) | $0.97 mean, $1.92 max per task instance, with diff-based update | GPT-4o at Aug 2024 prices. Summaries ~20% of code tokens |
| RepoAgent (F) | gpt-4-0125: 5.46M tokens for AutoGen, 5.0M for AutoGPT; ~0.4-1k tokens of output per object | Caller/callee context is injected, so input dominates; the bidirectional context is why reference changes force regeneration |
| DeepWiki (vendor docs) | Medium ~5-10 ACUs, high ~20-40 ACUs per wiki; free at low effort | ACU price not given in what I read |
| RepoRepair (F) | $0.44 per fixed issue (SWE-bench Lite), $0.56 (Multimodal) | Includes the documentation-guided localization stage and the repair; generation cost separate and not read |
| Time | Meta-RAG: ~137 s per SymPy task instance (first fetch only; not in the re-query) | The only generation-time datum |

**Incremental strategies with measured savings:** Meta-RAG's git-diff updating is the only measured one (57.9% mean, ~77% token-weighted by my arithmetic, fewer code tokens to process than a full resummarize at every task). It is *finer-grained* (changed hunks) than a file-hash planner, so its saving over a **full rebuild** is an upper bound on what file-level hashing gets, and it says nothing about file-level versus hunk-level update. RepoAgent adds a coupling cost by regenerating on referrer changes, which a forward-only document design avoids, a point on which the paper's own "dependency inversion" remark agrees (it also declines to regenerate when a callee changes).

**Order-of-magnitude extrapolation, flagged as mine:** at Oskooei's rate a 10M-line, ~10^5-file codebase costs about $0.7k-1.1k with a small hosted model and one short summary per file; Zikaron's four-section documents are longer (Caumartin's detailed technical summaries averaged ~740-750 tokens per file, derived from its Tables 1-2, against ~120 for role-aware) and the planned models are stronger, so the realistic range is several times that. Use it only to say the first build is not the prohibitive cost; Zikaron's own measurement says steady-state regeneration is (2.5x the first build over 60 days if every touched file regenerates at every commit).

## 7. Part E: what a per-file or per-module document should contain

No study ablates the proposal's four sections (purpose, non-trivial symbols, what is not obvious, forward dependencies). The nearest evidence:

| Content variant | Result | Source |
|---|---|---|
| Role only (what the file is and does, main classes/methods) vs detailed technical (purpose, APIs, deps, errors, patterns, identifiers) | Detailed is ~6.2x larger and **not consistently better**; better for Qwen3 embeddings, worse for GTE/BGE/CodeXEmbed; BM25 on LCA slightly better (.613 vs .573) | Caumartin (R) |
| Synthetic bug reports per file | Worse than paths in all first-stage cells; useful only as an LLM *ranking* representation | Caumartin (R) |
| Hierarchy: directory filter on/off | Off: MRR -54%, Recall@10 -37%, Pass@10 -18%, tokens +44% | Oskooei (R) |
| Repo seed context in file summaries ("context-aware" vs "isolated") | Illustrated by example; **no ablation number** | Oskooei (R) |
| Summary of the graph context vs flattened (RepoGraph) | Hurts at 1 hop (28.33 vs 29.67), helps at 2 hops (28.67 vs 26.00) | RepoGraph (F) |
| Call graph on/off, summary module on/off (LingmaAgent) | -1.66 and -3.66 pts respectively | LingmaAgent (F) |
| Topological (dependencies-first) order when writing docstrings | Helpfulness 3.88 -> 3.44, truthfulness 94.64 -> 86.75 when order is random | DocAgent (F) |
| Codebase overview in a context file | No faster contact with gold-patch files; cost +20% | Gloaguen (R) |
| Only non-inferable content | Authors' conclusion: context files should hold what the repository does not already say | Gloaguen (R) |
| File path alone | A strong baseline: Hit@5 .50 on LCA and SWE with BGE-Large | Caumartin (R) |

**Read-across.** (a) The "what is not obvious" section is the one most consistent with Gloaguen's lesson (non-inferable content), and the one with no direct ablation. (b) The "non-trivial symbols" and "forward dependencies" sections serve a *lexical* role (identifiers), where BM25 on detailed summaries did well in one cell; in an RRF hybrid with grep as backup they plausibly add recall, but nothing here measures it. (c) No evidence supports or undermines forward-only dependencies for localization; the only evidence is on cost (RepoAgent's reverse-reference regeneration trigger) and on docstring quality (dependencies first helps).

## 8. Localization benchmarks (the dependent variable M40 proposes)

| Benchmark | Facts (abstract-level unless stated) | Fit |
|---|---|---|
| **Long Code Arena bug localization** | 150 manually verified tasks (50 each Python/Java/Kotlin); mean 559 files/task, max 7,917; 50% multi-file (R via Caumartin) | File-level Hit@k, MAP@k; repos less likely memorized than SWE-bench |
| **SWE-bench Verified** | 500 tasks, mean 654 files, max 1,008; 85.8% single-file (R via Caumartin) | Memorization risk, as the proposal already notes |
| **SWE-Explore** (arXiv 2606.07297, Jun 2026) | 848 issues, 10 languages, 203 repos; ranked code regions under a fixed line budget; ground truth from successful agents' solution paths | Matches "right files and the tokens spent reaching them"; coverage, ranking, context efficiency |
| **Agent Retrieval Bench** (arXiv 2607.24882, Jul 2026) | 427 samples, 25 repos; relevance = what the agent needs next; includes no-gold and wrong-repository controls | Tests abstention; found logged agent trajectories missed gold files in 27-35% of samples |
| **Gloaguen's first-touch metric** | Steps before first interaction with a file in the gold patch (R) | Cheap, per-trajectory, available on any harness |
| LocAgent / Loc-Bench (arXiv 2503.09089, **S** only) | Snippet says 92.7% file-level on SWE-bench Lite with ~86% cost reduction | Structural-graph alternative; not opened |

None goes near 10^5 files; the largest repo in any of them is 7,917 files (LCA).

## 9. Where the evidence argues against the proposal

1. **Overviews do not help find files, and cost 20% more** when always loaded (Gloaguen, R). The proposal's documents are searched, not preloaded, which removes the instruction-bloat channel, but no experiment tests that.
2. **File-level localization is already strong for modern agents** (SWE-Explore abstract; Agent Retrieval Bench: logged agents miss gold files in 27-35% of cases), so the headroom for a docs corpus is mainly on repositories too large for grep, which no published study includes.
3. **Raw code retrieval often matches or beats summaries** on Python (Caumartin: 4 of 5 retrievers on SWE-bench Verified), so docs-instead-of-code is not the winning read; docs-plus-code is.
4. **A structural map is a serious alternative at small budgets** (RepoMap best at 8K tokens in Agent Retrieval Bench; structural indexes beat grep in the one 91-instance study, with the caveats above).
5. **The vendors with the largest agent deployments say they prefer no index** (Anthropic, Cline), citing staleness. K14 answers the staleness objection by reporting it, but the preference itself is unablated.
6. **Positive end-task evidence is tiny**: SWD-Bench's 5-issue difference on 57; RepoRepair confounded; LingmaAgent's summary module is not a corpus.
7. **Generated documents can be wrong on day one** (Kang et al.: ~20% of GPT-4 comments carry a demonstrably inaccurate statement; DocAgent's truthfulness metric only checks that referenced identifiers exist). K14 cannot see this; `unverifiable` and `changed` both describe the source, never the document.
8. **No evidence that the agent will *use* the corpus** at the right moment (Zikaron's own Q16: unprompted recall in 6-11% of turns); the only controlled instruction-following evidence says agents follow what a context file names, at a cost in extra steps.

## 10. What M40 should take, and what it should avoid

**Regeneration cadence and cost**
- *Take:* hash-keyed regeneration with content-hash gating (Cursor's Merkle tree for embeddings, Meta-RAG's diff for LLM text, RepoAgent's trigger table as the model of what *not* to trigger on). Measure tokens per document in the first build; every cost datum above is for much shorter summaries than four sections produce.
- *Take:* regenerate lazily or on a release/refresh boundary rather than per commit. The only deployed precedent with a stated cadence regenerates per release; Zikaron's own churn number (2.5x the first build in 60 days if every touched file regenerates at every commit) argues the same way. Record in the document which source hash it was built from (already K14) so a `changed` document can be rebuilt on demand when a search returns it.
- *Avoid:* reverse-dependency or caller-context in the generation prompt. It is what makes RepoAgent regenerate when referrers change; forward-only (the proposal) is consistent with that evidence.
- *Avoid:* reading the published per-file costs as a budget. They are for much shorter summaries from smaller models (Groq-hosted 20B, gpt-4.1-mini) than four sections from a capable model will be.

**Whether the generated documents are committed**
- No measurement exists. Vendor guidance for *authored* context files is commit and review in PRs (Anthropic docs); RepoAgent commits its docs through the hook; the index-style systems (Cursor, Meta-RAG, Oskooei) keep generated artifacts out of the repository. Cursor observes team clones average 92% identical, so per-developer generation duplicates cost.
- *Suggest:* leave committed-or-not to the operator but make the corpus rebuildable from a fresh clone from the source hashes alone, and do not let an uncommitted corpus silently fall out of `git_mode: tracked`.

**Where "search before you grep" is said**
- Evidence is indirect. Instructions in an always-loaded file are followed (Gloaguen: a tool named in the file was used 1.6-2.5 times per instance, against under 0.05 when not named), vendors document a session-start text channel for exactly this ("recommend the right plugin at session start", Claude Code docs), and unprompted recall is rare (Q16). No ablation compares corpus description, tool description and session-start text.
- *Suggest, as my inference:* put it in the session-start text, injected only where a code-knowledge corpus exists, and repeat it briefly in the tool description; treat the corpus description as the weakest channel because it is read only after the agent has already chosen to look. Keep it to a sentence or two, since the same paper shows followed instructions raise steps and cost, and measure the added calls.

**Per-file versus per-module granularity**
- *Take both, as proposed.* The measured structures that work are hierarchical (Oskooei: directory routing worth 54% of MRR; Meta-RAG: file one-liners before details; CodeWiki and DeepWiki write module- or topic-level pages). The module README is the routing layer; per-file documents are the retrieval unit.
- *Take:* a first one- or two-sentence role line in every file document. Caumartin's role-aware length was the best cost-effectiveness point and the longer variants did not consistently beat it; chunking will cut longer documents anyway, so the role line should be what leads every chunk's context. `design/indexing.md` names gist-prepending; I have not read it, so check that the role line is what it would prepend.
- *Avoid:* assuming per-file richness pays for itself. Include a module-README-only arm in the evaluation, since no published study separates module-level from file-level documents.
- At 10^5 files, the Oskooei route-then-search design is the one scaling argument in the literature; it matches the proposal's one-corpus-per-module.

**The CTIM-Rover risk**
- Two independent negative results now bracket the proposal: CTIM-Rover (agent-written episodic code memory, -11 pts on 45 issues) and Gloaguen (LLM-written repository overviews, -0.5/-2 pts, +20% cost). Both are consistent with "more LLM-written text in context makes agents explore more and succeed no more often."
- What differs here, per `design/code-knowledge.md`: on-demand search, per-file provenance, a freshness state. What the literature adds: the retrieval-oriented studies that *are* positive all measure localization, not resolution, and the positive resolution evidence is n = 45-57.
- *Take:* an eval whose arms are paths-only, raw-code grep (the current default), repo-map, and docs, with primary metrics steps-before-first-gold-file and tokens-to-localize, resolution secondary (as `design/evaluation.md` §3 already argues). A repository the model has not memorized, per M26's first-tool-call screen.
- *Avoid:* reporting localization gain as a resolution claim, and a single-sample comparison (Gloaguen's own limitation, inside the 2.2-6.0 point spread).

## 11. Gaps and leads

- Per-file cost and time for four-section documents with a current frontier model: unmeasured anywhere. M40's first build should report it.
- A published rate of generated-document inaccuracy at day 0 for module/file-level (not docstring-level) documents: not found. Kang et al.'s ~20% is Java method comments.
- Cost of stale documentation to agents: not found; an A/B with deliberately stale documents (swap in documents built at an older commit) is feasible with M40's planner.
- DeepWiki refresh policy and the Cognition talk (a YouTube video, `u8Im0l_vwqM`, not opened): primary detail unavailable.
- Boris Cherny's X post and Latent Space transcript: the transcript quotes come through the fetch summarizer; verify before quoting.
- LocAgent (arXiv 2503.09089) and `SWE-Explore`/`Agent Retrieval Bench` full papers: not opened beyond abstracts.
- RepoAgent's README mentions a ~270k-line project; not independently confirmed.
- Whether the Gloaguen "removing documentation raises LLM context-file performance 2.7%" finding survives in v3 (it is in v1).

## 12. Method

Searches (WebSearch, standard mode), roughly in order: Evaluating AGENTS.md repository-level context files; RepoAgent arXiv 2402.16667; DocAgent Meta topological multi-agent; Google Code Wiki announcement; DeepWiki Cognition; Meta-RAG bug localization; RepoUnderstander / LingmaAgent; Boris Cherny agentic search vs RAG; Cline blog on indexing; Latent Space transcript; Claude Code `/init`; Lulla AGENTS.md efficiency; Cursor semantic search blog; Rewriting the Code (ReCo); LLM summaries as retrieval index for localization; Swimm auto-sync; CodexGraph and RepoGraph; llms.txt measured use; CodeWiki benchmark; Cursor secure indexing; code-comment inconsistency prevalence; outdated references in documentation (Tan, Wagner); Treude and Baltes context rot; stale context files; Panthaplackel; RepoAgent cost and hook; documentation as agent context ablations; misleading comments and LLMs; Macke and Doyle; Aider repo map ablation; OpenHands microagents; Greptile docstrings; agentic grep vs embeddings benchmarks; hierarchical summaries for monorepo localization; Agent Retrieval Bench; MCP tool description vs system-prompt steering (practitioner-level hits only; nothing citeable).

Fetches: arXiv abstract and HTML/PDF pages for each paper above; `code.claude.com` memory and large-codebase docs (read in full); vendor docs for Devin, kiro, OpenHands, Swimm; Cursor, Cline, Greptile, Google and Anthropic blogs; Ahrefs. PDFs for Gloaguen (pp.1-10), Caumartin (pp.1-24), Oskooei (pp.1-9) and Wen et al. (pp.1-2) were rendered and read directly. Local reads: `design/code-knowledge.md`, `design/evaluation.md`, `research/code-knowledge-sizing.md`.

Timebox: single session; no search was repeated for items already settled.

## 13. Sources

Local
1. `/home/nathan/Zikaron/design/code-knowledge.md` (proposal), `/home/nathan/Zikaron/design/evaluation.md` §3-4.1, `/home/nathan/Zikaron/research/code-knowledge-sizing.md` §2. R.

Context files and agent behaviour
2. Gloaguen, Mündler-Sasahara, Müller, Raychev, Vechev. *Evaluating AGENTS.md: Are Repository-Level Context Files Helpful for Coding Agents?* arXiv 2602.11988 (v3, 29 Sep 2026). https://arxiv.org/abs/2602.11988. R. Preprint.
3. Lulla et al. *On the Impact of AGENTS.md Files on the Efficiency of AI Coding Agents.* arXiv 2601.20404. https://arxiv.org/abs/2601.20404. F. Preprint.
4. Chatlatanagulchai et al. *Agent READMEs: An Empirical Study of Context Files for Agentic Coding.* arXiv 2511.12884. https://arxiv.org/abs/2511.12884. F. Preprint.
5. Treude, Baltes. *Context Rot in AI-Assisted Software Development.* arXiv 2606.09090 (8 Jun 2026). https://arxiv.org/abs/2606.09090. F. Preprint.

Documentation generators
6. Luo et al. *RepoAgent: An LLM-Powered Open-Source Framework for Repository-level Code Documentation Generation.* arXiv 2402.16667; EMNLP 2024 demo. https://arxiv.org/abs/2402.16667 and https://arxiv.org/html/2402.16667v1; repo README https://github.com/OpenBMB/RepoAgent. F.
7. Yang et al. (Meta). *DocAgent: A Multi-Agent System for Automated Code Documentation Generation.* arXiv 2504.08725; ACL 2025 demo. https://arxiv.org/html/2504.08725v2. F.
8. Cognition. *DeepWiki: AI docs for any repo.* https://cognition.com/blog/deepwiki ; Devin docs https://docs.devin.ai/work-with-devin/deepwiki and https://docs.devin.ai/onboard-devin/index-repo ; ZenML summary of a Cognition talk, *Auto-Generated Codebase Documentation and Intelligence at Scale*, https://www.zenml.io/llmops-database/auto-generated-codebase-documentation-and-intelligence-at-scale. Vendor blog and docs; secondary; F.
9. Google. *Introducing Code Wiki.* https://developers.googleblog.com/introducing-code-wiki-accelerating-your-code-understanding/ (public preview 13 Nov 2025; date per press coverage, S). Vendor blog; F.
10. Hoang et al. *CodeWiki: Evaluating AI's Ability to Generate Holistic Documentation for Large-Scale Codebases.* arXiv 2510.24428 (v5). https://arxiv.org/html/2510.24428v5. F.
11. Swimm. *Keep docs updated with Auto-sync.* https://docs.swimm.io/features/keep-docs-updated-with-auto-sync/ ; blog https://swimm.io/blog/continuous-documentation-through-continuous-integration-with-swimm (signals per snippet only). Vendor; F and S.
12. Aider. *Repository map.* https://aider.chat/docs/repomap.html ; https://aider.chat/2023/10/22/repomap.html. Vendor docs; F.
13. Anthropic. *How Claude remembers your project* https://code.claude.com/docs/en/memory ; *Set up Claude Code in a monorepo or large codebase* https://code.claude.com/docs/en/large-codebases. Vendor docs; R.
14. kiro. *Steering.* https://kiro.dev/docs/steering/. Vendor docs; F.
15. OpenHands. *Repository microagents.* https://docs.openhands.dev/usage/prompting/microagents-repo (redirected from docs.all-hands.dev). Vendor docs; F and S.
16. Howard. *llms.txt.* https://llmstxt.org/ ; Ahrefs, *We analyzed 137K sites: 97% of llms.txt files never get read* (Jun 2026), https://ahrefs.com/blog/llmstxt-study/. Spec; third-party vendor study; F.

Research systems for localization
17. Tawosia, Alamir, Liu, Veloso. *Meta-RAG on Large Codebases Using Code Summarization.* arXiv 2508.02611. https://arxiv.org/html/2508.02611v1. F; Table 1 re-queried.
18. Rafiei Oskooei, Yukcu, Bozoglan, Aktas. *Natural Language Summarization Enables Multi-Repository Bug Localization by LLMs in Microservice Architectures.* arXiv 2512.05908; ICSE 2026. https://arxiv.org/abs/2512.05908. R.
19. Caumartin, Chen, Costa. *Retrieval-Oriented Code Representations in Agentic Bug Localization.* arXiv 2607.11046 (13 Jul 2026). https://arxiv.org/pdf/2607.11046. R.
20. Ma et al. *Alibaba LingmaAgent* (RepoUnderstander), arXiv 2406.01422. https://arxiv.org/html/2406.01422v2. F.
21. Liu et al. *CodexGraph.* arXiv 2408.03910; NAACL 2025. https://arxiv.org/html/2408.03910v2. F.
22. Ouyang et al. *RepoGraph.* arXiv 2410.14684. https://arxiv.org/html/2410.14684. F.
23. Sounthiraraj et al. (Cisco). *Code-Craft: Hierarchical Graph-Based Code Summarization for Enhanced Context Retrieval.* arXiv 2504.08975. https://arxiv.org/abs/2504.08975. F.
24. *RepoRepair: Leveraging Code Documentation for Repository-Level Automated Program Repair.* arXiv 2603.01048. https://arxiv.org/abs/2603.01048. F.
25. *SWD-Bench: Evaluating Repository-level Software Documentation via Question Answering and Feature-Driven Development.* arXiv 2604.06793. https://arxiv.org/html/2604.06793. F.
26. Bhola et al. *Code Isn't Memory: A Structural Codebase Index Inside a Coding Agent.* arXiv 2606.22417 (21 Jun 2026). https://arxiv.org/abs/2606.22417. F.
27. *Agent4cs.* arXiv 2607.01425. https://arxiv.org/abs/2607.01425. F.
28. *SWE-Explore: Benchmarking How Coding Agents Explore Repositories.* arXiv 2606.07297. https://arxiv.org/abs/2606.07297. F (abstract).
29. Qin, Xie. *Agent Retrieval Bench.* arXiv 2607.24882. https://arxiv.org/abs/2607.24882. F (abstract).
30. Li, Zhou, Shen. *Rewriting the Code (ReCo).* ACL 2024, arXiv 2401.04514. https://arxiv.org/abs/2401.04514. F.
31. *LocAgent: Graph-Guided LLM Agents for Code Localization.* arXiv 2503.09089. https://arxiv.org/pdf/2503.09089. S only.
32. Greptile. *Semantic codebase search* (15 Apr 2025). https://www.greptile.com/blog/semantic-codebase-search. Vendor blog; F.

Agentic search versus RAG
33. Latent Space podcast with Boris Cherny and Cat Wu, 7-8 May 2025. https://www.latent.space/p/claude-code. F.
34. Anthropic. *How Claude Code works in large codebases* (14 May 2026). https://claude.com/blog/how-claude-code-works-in-large-codebases-best-practices-and-where-to-start. Vendor blog; F.
35. Cline. *Why Cline doesn't index your codebase, and why that's a good thing* (27 May 2025). https://cline.bot/blog/why-cline-doesnt-index-your-codebase-and-why-thats-a-good-thing. Vendor blog; F.
36. Cursor. *Improving agent with semantic search* (6 Nov 2025). https://cursor.com/blog/semsearch. Vendor blog; F. Cursor. *Securely indexing large codebases.* https://cursor.com/blog/secure-codebase-indexing. Vendor blog; S.
37. The Pragmatic Engineer, Claude Code with Boris Cherny, 4 Mar 2026. https://newsletter.pragmaticengineer.com/p/building-claude-code-with-boris-cherny. Secondary; F, weak.

Staleness
38. Wen, Nagy, Bavota, Lanza. *A Large-Scale Empirical Study on Code-Comment Inconsistencies.* ICPC 2019. https://www.inf.usi.ch/faculty/lanza/PUBS/P/Wen2019a.pdf. R (pp.1-2).
39. Tan, Wagner. *Detecting outdated code element references in software repository documentation.* EMSE 29(1); arXiv 2212.01479. https://arxiv.org/abs/2212.01479. F. Tan, Wagner, Treude. *Wait, wasn't that code here before? Detecting outdated software documentation.* arXiv 2307.04291. https://arxiv.org/abs/2307.04291. F.
40. *Investigating the Impact of Code Comment Inconsistency on Bug Introducing.* arXiv 2409.10781. https://arxiv.org/abs/2409.10781. F.
41. Kang, Milliken, Yoo. *Identifying Inaccurate Descriptions in LLM-generated Code Comments via Test Execution.* arXiv 2406.14836. https://arxiv.org/abs/2406.14836. F.
42. Macke, Doyle. *Testing the Effect of Code Documentation on Large Language Model Code Understanding.* NAACL Findings 2024; arXiv 2404.03114. https://arxiv.org/abs/2404.03114. F (abstract).
43. Panthaplackel et al. *Deep Just-In-Time Inconsistency Detection Between Comments and Source Code.* AAAI 2021; arXiv 2010.01625. https://arxiv.org/pdf/2010.01625. S.
