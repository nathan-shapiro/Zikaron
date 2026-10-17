# Research note: repositories the model has not seen, for M40's localization A/B on Claude Opus 4.6

Written 2026-10-14 by memory-assistant for memory-researcher. Every GitHub figure below was read from
GitHub's REST API or the repository page on 2026-10-14 through WebFetch, so counts are as of that day.
Not redone here: `research/code-localization-benchmarks.md` §4.3-4.5 and §8.2 (memorization costs
+22% to +255% input tokens; choose a repository the model could not have seen; construction of the
task set).

## 0. The brief, restated

M40 compares two arms on one model, Claude Opus 4.6 under Claude Code: control (grep only) against
treatment (the same agent plus a per-file documentation knowledge base). Task: from a feature request
in intent language that names no file or identifier, find the files that must change; measure tokens
and tool calls before the first touch of a correct file; ground truth is the files a merged PR changed.
The repository must be one the model has not memorized (the CockroachDB pilot: 12 of 30 control runs
opened by grepping the right subsystem path). Asked here:

1. Opus 4.6's documented training data cutoff, reliable knowledge cutoff, release date, and any
   announced deprecation or retirement, from Anthropic's own documentation, with quotes and URLs.
2. Candidate repositories whose public code first appeared after that cutoff (ideally 3+ months
   after), preferring 10,000+ source files or 1M+ LOC (report down to ~3,000 files), covering
   (a) large codebases open-sourced in the window, (b) large new projects that grew fast, (c) large
   codebases released under a new licence. Per candidate: first public commit and whether any earlier
   version was public, size and how it was obtained, languages, licence, merged PRs since release,
   PR-description quality, feature versus bug-fix mix.
3. Disqualifiers: mostly vendored or generated code; squashed sync commits with no PRs; an older public
   project renamed.

## 1. Bottom line

- **Opus 4.6: reliable knowledge cutoff May 2025, training data cutoff Aug 2025, released 2026-02-05,
  retirement "not sooner than" 2027-02-05, not deprecated as of 2026-10-14.** The model's own
  May 2025 self-report matches the documented *reliable* cutoff, not the later *training data*
  cutoff. The safe window opens after Aug 2025, not May 2025. Plan to finish runs before roughly
  Jan 2027 (section 2.4).
- **Nothing in the window is a famous, conventionally governed, 10,000+ file codebase from a major
  vendor with a clean PR trail.** The window is full of large agent-era projects, and the
  corporate open-sourcings that did happen mostly fail on PR ground truth (xAI's Grok Build,
  Facepunch's s&box, EDG's compiler front end, ZStack's ZSvirt). Five repositories pass every
  criterion I could check:
  **Macro** (`macro-inc/macro`, public 2025-11-08, est. 2.5-3.7M lines, 6,815 merged PRs),
  **Warp** (`warpdotdev/warp`, public 2026-04-28, ~1.5M lines at release and ~2.2M text lines now,
  2,564 merged PRs), **OpenClaw** (`openclaw/openclaw`, public 2025-11-24, est. 10M+ lines,
  54,080 merged PRs, but ~60% of them are fixes), **IronClaw** (`nearai/ironclaw`, public
  2026-02-03, 3,612 merged PRs) and **Buzz** (`block/buzz`, public 2026-03-06, 2,966 merged PRs).
- **No file count was obtained for any candidate** (I had no shell and no clone; the tree API
  truncates in the fetch tool). Sizes are GitHub language bytes, converted to lines at 30-45 bytes per
  line, except Warp where GitHub's own line statistics were readable. Treat every "files" figure as
  unverified; section 9 gives the check.
- Two design hazards sit in the repositories themselves rather than in the ranking: they ship
  `AGENTS.md` / `CLAUDE.md` / `specs/` / `docs/` content (Claude Code loads `CLAUDE.md` into context
  automatically, and Warp's `specs/` holds 162+ per-feature spec directories), which a grep arm can read.
  See 5.4.

## 2. Question 1: Opus 4.6 cutoffs, release, retirement

### 2.1 What Anthropic's documentation says

| Fact | Value | Where |
|---|---|---|
| Model id | `claude-opus-4-6` | [1] |
| Released | February 5, 2026 | [1], [6] |
| Reliable knowledge cutoff | May 2025 | [1] capabilities table |
| Training data cutoff | Aug 2025 | [1] capabilities table |
| Status | "Active (legacy)"; the page recommends migrating to Claude Opus 5.5 | [1] |
| Retirement | "Not sooner than February 5, 2027" | [1], [3] (row `claude-opus-4-6`, state Active, deprecated N/A) |
| Notice commitment | at least 60 days' notice before retirement of publicly released models | [3] §Notifications |
| Snapshot stability | the dateless 4.6-generation id maps to one fixed snapshot; weights and configuration are not updated | [4] |
| Serving stack | request router, safety classifiers and sampling logic can change under a fixed id | [4] |
| Price | $5 / $25 per MTok input / output | [1] |

Definitions, from [2]: the reliable knowledge cutoff is "the date through which the model's knowledge is
most extensive and reliable", and the training data cutoff is "the broader range of data used". The
support article [5] states, in the form the fetch tool returned it: "Claude Opus 4.6 was trained on data
up until August 2025", and uses only the single term "knowledge cutoff" without separating the two.

### 2.2 What I could not verify

- **The system card was not read.** `anthropic.com/claude-opus-4-6-system-card` redirects to a PDF
  (`www-cdn.anthropic.com/6a5fa276ac68b9aeb0c8b6af5fa36326e0e166dd/Claude%20Opus%204.6%20System%20Card.pdf`)
  that WebFetch refuses at its 10 MB limit [7]. A search snippet said the card lists web crawler, public,
  opt-in customer and internally generated data as sources; that is unverified and says nothing on dates.
  The two dates above therefore come from the documentation pages, not from the card.
- **The Transparency Hub model report has no Opus 4.6 section** [8]; as returned by the fetch tool
  it lists cutoffs for Opus 4.7 and 4.8 (January 2026), Opus 5 (May 2026) and others. It cannot be used
  to confirm 4.6.

### 2.3 What the cutoffs mean for the window

- The model said "May 2025" when asked, which is the documented *reliable* cutoff. Data between May and
  Aug 2025 is in training but thinly represented, so a repository first public in that interval is not
  clean.
- **Window rule used in this note: first public commit after 2025-08-31 passes; the stated ideal of
  3+ months means after about 2025-11-30.** Macro (2025-11-08) and OpenClaw (2025-11-24) sit 10-12 weeks
  after the end of Aug 2025, a few weeks short of the ideal, and are still outside both cutoffs.
  Warp (2026-04-28), IronClaw (2026-02-03) and Buzz (2026-03-06) clear the 3-month ideal.
- Excluded for being inside the training interval: Windows Subsystem for Linux and Microsoft's Edit editor,
  both open-sourced 2025-05-19 [50][49].

### 2.4 Retirement: how long reproducibility lasts

No deprecation notice exists for `claude-opus-4-6` as of 2026-10-14 [3]. The page's retirement field is a
floor ("not sooner than"), not a date. The history on the same page gives a pattern (my reading, not
an Anthropic statement):

| Model (snapshot in id) | Deprecation notice | Retired / retirement date | Notice to retirement |
|---|---|---|---|
| `claude-opus-4-20250514` | 2026-04-14 | 2026-06-15 | 2 months |
| `claude-opus-4-1-20250805` | 2026-06-05 | 2026-08-05 | 2 months |
| `claude-sonnet-4-5-20250929` | 2026-09-30 | 2026-11-30 (scheduled) | 2 months |
| `claude-3-7-sonnet-20250219` | 2025-10-28 | 2026-02-19 | ~3.7 months |

Each of the first three was retired or scheduled about 12-14 months after its snapshot date, and notices
came 10-12 months after it. For a model released 2026-02-05 that points to a notice between about
Dec 2026 and Feb 2027 and a retirement from Feb 2027. **Recommendation: schedule all Opus 4.6 runs to
finish by about January 2027**, record the exact model id and the Claude Code version for every run, and
keep transcripts. Bedrock and Google Cloud set their own dates [3]. Opus 4.5 (`claude-opus-4-5-20251101`)
has the earlier floor, 2026-11-24.

## 3. Method, and what each number means

Discovery (no shell, so no clones):

1. News and vendor searches for open-sourcing events in the window, by category (game engine, database,
   IDE, OS component, company monorepo, relicensing).
2. GitHub's repository search API filtered by `created:>2025-09-01`, `size`, `stars`, `language` and
   `license`, sorted by stars [35]. This finds repositories created in the window; it cannot find a
   repository that was created earlier and made public later with its old `created_at` (Warp's is 2021,
   though its git history starts with the 2026 import).
3. Per candidate, API calls: repository record, `/languages`, first commit (the commit list at the
   last page, using the commit count from the repository page), merged-PR count
   (`search/issues?q=repo:X is:pr is:merged`), title-keyword counts, and small samples of PR pages.

Reading the numbers:

- **Bytes** are GitHub linguist language bytes: they exclude what linguist flags as vendored or generated,
  imperfectly, and include tests and fixtures.
- **Lines** are bytes divided by 30-45; the only measured line figure is Warp's, from GitHub's
  `stats/code_frequency` (additions minus deletions, all text files including lockfiles and docs).
- **Merged PRs** are the `total_count` of the issue-search API and include bot and dependency-bump PRs.
- **feat / fix share** is the count of merged PRs with "feat" or "fix" in the title. It is crude: it works
  where titles follow conventional commits (Macro, OpenClaw, IronClaw, Buzz) and understates features where
  they do not (Warp).
- **PR-description quality** rests on samples of 4-6 PRs per page at one to three pages per repository. It
  is a smell test, not a measurement.

## 4. Ranked candidates

All first-public dates were read from the root commit unless stated. "Earlier public code" means any
earlier release, mirror, fork lineage or SDK that I checked; the check is limited to the repository's own
history, the owning organisation's repositories, and the README.

### 4.1 Table

| Rank | Repository | First public commit | Earlier public code? | Size (bytes of code -> est. lines; files unverified) | Licence | Merged PRs (2026-10-14) | feat / fix titles | Disqualifier check |
|---|---|---|---|---|---|---|---|---|
| 1 | [`macro-inc/macro`](https://github.com/macro-inc/macro) | 2025-11-08 [19][21] | None found in the org; product was closed-source. Org has separate public forks (lexical, tauri, pdf.js); `packages/lexical-core` may embed fork code, unchecked [25] | Rust 58.1 MB + TypeScript 51.7 MB (+ small others) -> est. 2.5-3.7M lines; 273 crates, ~50 services, 9 packages [20][24] | AGPL-3.0 (commercial offered) | **6,815** [23] | 2,223 / 2,937 of 6,815 (33% / 43%) | Pre-release history squashed (second commit cites internal PR numbers #334, #356) but PR numbering starts at #1 on the release day and 6,815 merged PRs follow. Not a mirror. No generated-code markers in crate names; not exhaustively checked |
| 2 | [`warpdotdev/warp`](https://github.com/warpdotdev/warp) | 2026-04-28 [12] | None found: the repository was created in 2021 but its git history starts at the 2026-04-28 import; the org's other public repos are small libraries and themes [10][26] | Rust 66.9 MB (of ~68.1 MB) -> **measured**: 1.46M lines added in release week, net 2.24M text lines now [14]; 80 crates [15] | AGPL-3.0; UI crates (`warpui_core`, `warpui`) MIT | **2,564** [13] | 61 / 560 (titles are not prefixed, so the feature share is understated; samples below) | First commit is a squashed internal import ("Repo-Sync-Origin: warpdotdev/warp-internal@..."); 9 of 2,531 commits carry that trailer [17]; the rest are PR-based. Many PRs are bot-authored (`warp-agent-staging[bot]`, dependabot) |
| 3 | [`openclaw/openclaw`](https://github.com/openclaw/openclaw) | 2025-11-24 ("Initial commit") [28] | None found; repository created the same day [27] | TypeScript **425 MB** + Swift 19.9 MB + Kotlin 9.5 MB + JS 8.2 MB -> est. 10-15M lines [29]; `src` has 98 subdirectories, `extensions` 290, `packages` 25 [32] | MIT | **54,080** [30] | 3,151 / 32,509 (**5.8% / 60.1%**) | Real history (110,224 commits). Not vendored: the sampled directories are first-party source and tests. Extreme churn and a bug-fix-dominated PR stream (section 5.3) |
| 4 | [`nearai/ironclaw`](https://github.com/nearai/ironclaw) | 2026-02-03 ("Initial implementation of the agent framework") [33] | README calls it "a Rust reimplementation inspired by OpenClaw", so it is a new codebase in a new language | Rust 57.7 MB + Python 5.7 MB + TS 5.0 MB -> est. 1.5-2.3M lines | Apache-2.0 or MIT (dual) | 3,612 [33] | 658 / 1,203 (18% / 33%) | PR-based from the first commit; sampled PRs are mostly fixes with medium to long descriptions. Not exhaustively checked for generated code |
| 5 | [`block/buzz`](https://github.com/block/buzz) | 2026-03-06 ("Initial commit", by a `block-open-source` bot) [34] | None found | Rust 27.4 MB + TS 15.6 MB + Dart 7.0 MB + JS 5.5 MB -> est. 1.2-1.9M lines | Apache-2.0 | 2,966 [34] | 682 / 1,191 (23% / 40%) | PR-based with long descriptions in the sample. Block-owned, so a corporate origin is possible; the README gives none |

Notes on the table:

- Ranks 1 and 2 are close. Choose Macro if the priority is feature-PR volume with human authors and
  filterable `feat(...)` titles; choose Warp if the priority is the widest margin from the cutoff (7.9
  months against 2.3) and a measured line count. Both are product codebases with real-world feature work.
- Rank 3 is the biggest by an order of magnitude and has the most PRs, which is its advantage for
  sample size and its drawback for snapshot discipline.
- None of these is a famous-company, decades-old codebase; they are 2025-2026 products.

### 4.2 Evidence behind the lines

**Macro.** Root commit `add flake.nix`, 2025-11-08T15:22:59Z, no parent [21]. The next commit (same day, one parent) is
titled "move macro-api" and its body lists "(#334)" and "(#356)": internal PR numbers, so earlier work
was squashed in. PR #1 to #3 are dependabot PRs created 2025-11-08 [22]. 6,761 commits and 6,815 merged
PRs [19][23]. The README reports 167 crates and 42 services; the contents API lists 273 crates and about 50
services, so the tree is growing [24]. Sample of five recent PRs by one author: 1,800-3,100 characters, with
test sections; sample of six from a middle page: four features, two fixes, one of the six an unmerged
draft, human authors, medium to long bodies [22][31]. `docs/` holds 37 markdown design documents (e.g.
calendar scheduling, email architecture) [24].

**Warp.** Root commit 0dbd3d56, 2026-04-28T13:40:51Z, "Initial public release of Warp.
Repo-Sync-Origin: warpdotdev/warp-internal@12af1d98..." [12]; the next commit is a normal PR merge (#9220).
`stats/code_frequency` shows 1,464,980 lines added in the first week, 2,706,939 added and 471,686 deleted
in total [14]. 2,564 merged PRs [13]. Three sampled middle pages (16 PRs): features such as a TUI
conversation-resume and a headless login flag, fixes such as WSL symlink completion, telemetry
removals; 7 of the 16 were closed unmerged (so a merged filter is needed); bodies were long; a large
share were authored by Warp's own agent bot [18]. The launch coverage says agents "handle the bulk of
implementation work" [16].

**OpenClaw.** Root commit f6dd362d, 2025-11-24T10:16:47Z [28]. 110,224 commits [33]. Across two samples of
five merged PRs each (latest page and a middle page), 1 of 10 was a feature [33]. The extensions
directory is 290 provider and channel plugins [32], so many tasks would have several near-identical
candidate directories, which suits a localization test but also makes gold sets ambiguous.

**IronClaw / Buzz.** Samples of six PRs each: IronClaw mostly fixes with medium to large descriptions
and one bot dependency bump; Buzz five fixes and one feature, only two merged, all human, long descriptions [34][35].

## 5. Per-candidate cautions

### 5.1 Macro

- 10 weeks after the end of Aug 2025 is slightly under the 3-month ideal.
- 33% of merged PRs have "feat" in the title, 43% "fix", leaving roughly a quarter other (chores,
  refactors, docs). A feature pool of roughly 2,200 PRs is ample for 57-250 questions before filtering.
- Pre-release code (before 2025-11-08) is not usable as task history because it is squashed.

### 5.2 Warp

- The initial import is a single squashed commit, so ground truth exists only for PRs merged after
  2026-04-28; all of them are within 6 months.
- The public repository is the client. It is a terminal and agent product, a domain the model knows by
  name, though not by layout.
- Because a share of PRs is authored by the vendor's own agent, descriptions follow a template, which
  helps rewriting and may make gold sets more regular than a human-written stream.

### 5.3 OpenClaw

- Roughly 330 commits a day. A knowledge base built at one commit is stale within a day; the base
  commit for each task must be the PR's parent or tasks must be restricted to a short window after a
  fixed snapshot.
- 60% of merged PRs are fixes, and only 5.8% have "feat" in the title (3,151 PRs). Fixes tend to arrive
  with symptom language, which leaks identifiers; a "find where to start for this behaviour" task is
  still possible but the intent-language rewrite is harder.
- The 425 MB TypeScript figure is large enough to look generated. The directories I inspected were
  not: `src/agents` has 217 files, 87 of them tests, the largest 161 KB; `src/test-fixtures` holds one
  9 KB file [32]. Not checked: `ui/src/i18n`, `docs/`, generated plugin catalogs.

### 5.4 Repository-resident documentation and agent files (all candidates)

- Claude Code reads `CLAUDE.md` automatically. The candidates ship `CLAUDE.md` (Macro, 5.2 KB; Macro's
  `AGENTS.md` is a 9-byte stub), `AGENTS.md` (Warp; OpenClaw, 19.8 KB), `.claude/` directories (Warp,
  OpenClaw) and `.mcp.json` files. Warp has `specs/` with **162+ directories named by ticket id
  (APP-1915 and so on)** [15]; Macro has `docs/` with 37 markdown files [24]; OpenClaw has `VISION.md`
  and a 113 KB README [32]. These are authored repository documentation: they give the grep arm a
  feature-to-code map and give the task writer ready-made intent language. Remove them or hold them
  equal across arms (my recommendation, not a measured effect).

## 6. Second tier: large, but less vetted

Created in the window, large by bytes, PR-based by merged-PR count. Not checked: first commit (the
`created_at` is a floor on first-public date, not proof), generated or vendored content, PR quality.

| Repository | Created | Code bytes | Merged PRs | Licence | Note |
|---|---|---|---|---|---|
| [`stablyai/orca`](https://github.com/stablyai/orca) | 2026-03-17 | TypeScript 192.4 MB, JS 8.3 MB (est. 4-7M lines) | **12,967** | MIT | Size looks inflated; the latest PR returned by the search was a localization-catalog change. Check for generated locale or catalog files before using |
| [`paperclipai/paperclip`](https://github.com/paperclipai/paperclip) | 2026-03-02 | TypeScript 101.4 MB, JS 3.2 MB, Rust 3.0 MB | 3,220 | MIT | |
| [`nexu-io/open-design`](https://github.com/nexu-io/open-design) | 2026-04-28 | TypeScript 73.1 MB, HTML 23.0 MB, CSS 4.7 MB | 3,564 | Apache-2.0 | 23 MB of HTML is likely templates or fixtures |
| [`fluxerapp/fluxer`](https://github.com/fluxerapp/fluxer) | 2026-01-01 | TypeScript 38.1 MB, Rust 6.7 MB, Erlang 4.9 MB, MDX 2.5 MB | 1,777 | AGPL-3.0 | A chat and voice application; commit titles use `fix(desktop): ... (#3456)` |
| [`iflytek/astron-agent`](https://github.com/iflytek/astron-agent) | 2025-09-19 | Java 6.8 MB, Python 5.0 MB, TS 4.8 MB (~18 MB) | 1,138 | Apache-2.0 | Below the size preference (~500K lines); first public 12 days after the Aug 2025 end |

## 7. Close but fail one criterion

| Candidate | Date | Size | Criterion failed | Evidence |
|---|---|---|---|---|
| [`xai-org/grok-build`](https://github.com/xai-org/grok-build) | created 2026-07-14, announced 2026-07-15 | 844,530 lines of Rust (a secondary source quoting a third party) | **Squashed sync commits, no PRs** | Recent commits are all "Synced from monorepo" by a bot; merged-PR count 0 [36][37]. Apache-2.0 |
| [`Facepunch/sbox-public`](https://github.com/Facepunch/sbox-public) (s&box) | 2025-11-24 ("Open source release. This commit imports the C# engine code and game files, excluding C++ source code.") | C# 30.6 MB (est. 0.7-1.1M lines), HLSL 1.1 MB; the C++ engine is not included | **No merged PRs** | Contributors' PRs are closed with `merged_at` null although `merge_commit_sha` is set, and the merged-PR search returns 0 [38]. History is individual commits with short messages and no PR references. Licence: MIT for source with a native-binary EULA. Whether any s&box code was public earlier is unverified |
| [`edgcpp/compiler`](https://github.com/edgcpp/compiler) (EDG C/C++ front end) | public 2026-09-30 (announced; repo created 2026-09-22) [39][40] | C 500 MB + C++ 353 MB by linguist, which includes the test corpus; `src/` is a flat directory of 228 files, some 1-3 MB each | **Ground truth and layout**: 16 PRs; 62,419 commits back to 1990-03-06, but sampled historical messages are terse ("Version 2.09", "Fix comment typo", "Changes tweak [EDGcpfe/17598]"); a flat 228-file source tree is a poor fit for per-file documentation | Genuinely unmemorized as far as I can tell (proprietary, licensed to vendors, not public before). Post-release commits cite `[GH #n]` issues. Licence: Apache-2.0 per news [40]; the API reports NOASSERTION with a `LICENSE.txt` present. Possible leaks of vendor-licensed source unverified |
| [`modular/modular`](https://github.com/modular/modular) (Mojo compiler) | compiler open-sourced 2026-08-18 [41] | Mojo 50.7 MB, Python 37.9 MB, C++ 12.9 MB | **Earlier public code** | Repository created 2023-04-28 [41]. From general knowledge, not verified this session: the standard library and MAX were public before the cutoff, so only the compiler directories are new. Commits are individual with `(#101153)`-style PR references |
| [`wilsonzlin/fastrender`](https://github.com/wilsonzlin/fastrender) | created 2025-11-16 | HTML 172.7 MB, Rust 66.3 MB | **Fixtures; no licence; small PR stream** | Licence null; 93 merged PRs; the HTML volume looks like test data; the code is agent-written and described by third parties as about 3M lines [51] |
| [`ZSvirt/zsvirt`](https://github.com/ZSvirt/zsvirt) | 2026-08-14 ("initial zsvirt2") | Java 42.1 MB, Groovy 10.4 MB | **Squashed; older public project** | 49 commits, 3 PRs; the README says it brings ZStack's ZSphere engine to open source, and `zstackio/zstack` has been public since 2015-04-04 under Apache-2.0 [42] |
| Carbon (EVE Online), `github.com/carbonengine` | repositories created 2026-05 to 2026-10; announced 2026-07-01 | 19 repositories; the largest, `trinity`, has C++ 10.6 MB (~300K lines, est. ~1,000 files, unverified) | **Size; multi-repository** | MIT mostly, some Apache-2.0 and PSF [43] |
| Unturned `SmartlyDressedGames/U3-SDK` | repository created 2017-10-16; source announced 2026-07-07 | repository size 33.9 MB | **Earlier public repository; licence** | An SDK repository has existed since 2017; custom non-commercial licence, not OSI; two-person studio [44] |
| X's full platform codebase | announced 2026-07-15 for "August 2026" | not applicable | **Not released as of 2026-10-14** (search-based) | `xai-org/x-algorithm` (Rust, 5 MB, created 2026-01-19) is public but small, and an earlier algorithm release was public in 2023 [45] |
| Valve Lepton | 2026-09 | small | Size; hosted on Valve's GitLab | [46] |
| Claude Code source (leaked 2026-03-31) | 2026-03-31 | ~512K lines TypeScript, ~1,900 files | No licence; no PR trail | Published by accident in an npm package; not an open-source release [47] |

## 8. Categories with nothing found

- **Relicensed codebases** (Redis, Elastic and similar returning to AGPL; Unleash moving to
  AGPLv3; Juno to MIT): contaminated by construction, because the source was public before the new
  licence. I found no case of previously private code first published under a new licence in the window
  other than those already listed.
- **OS component**: Lepton is the only one found; small. WSL was May 2025 (before the cutoff).
- **Databases**: no database of the preferred size appeared. `pgrust` (PostgreSQL reimplemented in Rust,
  created 2026-04-20) copies a design the model knows; `seekdb` (created 2025-10-21) and similar names
  were seen in repository searches and not examined.
- **IDEs**: the in-window IDE-class open-sourcing is Warp (an "agentic development environment" by its
  own description). Zed was open-sourced in January 2024.
- **Game engines**: s&box and Carbon only, both failing above. Cocos 4 (MIT, Jan 2026) continues an older
  public engine.
- **Chinese vendors**: Huawei's CANN operators and runtime are published on GitCode (not GitHub), as many
  separate repositories from Sept to Dec 2025 [48]. Unexamined; the multi-repository layout and platform
  make it a poor fit.

## 9. Gaps, and how to close them

1. **File counts, all candidates.** With a shell, per repository:
   `git clone --filter=blob:none --depth 1 URL && git -C DIR ls-files | wc -l`, then `tokei` or
   `cloc --vcs=git` for lines by language. Exclude lockfiles, `docs/`, fixtures and `specs/`.
2. **Merged PRs filtered for the task.** Per repository, with `gh`:
   `gh api -X GET search/issues -f q='repo:OWNER/REPO is:pr is:merged merged:>2026-06-01' -f per_page=1 --jq .total_count`,
   then per PR the changed-file list; keep PRs with 1-15 non-test source files (the construction in
   `research/code-localization-benchmarks.md` §8.2).
3. **Feature share for Warp** needs a content-based classification; the title keyword test fails there.
4. **The first-tool-call screen** (the pilot's own) on Macro and Warp is the cheapest remaining check and
   would catch an unexpected layout familiarity that these date checks cannot.
5. **The system card** should be read by anyone with a PDF reader, for any statement on the training
   data window.
6. **Second-tier generated-code checks** (Orca, open-design) and the X release status after September.

**Gap 1 closed for the five ranked candidates** (memory-researcher, 2026-10-14), with a treeless
clone of each default branch — `git clone -q --depth 1 --filter=blob:none --no-checkout URL DIR`,
then `git -C DIR ls-tree -r HEAD --name-only` — counting every path, so lockfiles, docs and vendored
code are included:

| repository | files | largest extensions |
|---|---|---|
| macro-inc/macro | 27,330 | 9,952 `.ts`, 7,761 `.rs`, 3,086 `.tsx`; 11,351 `.rs`/`.ts`/`.tsx` under `apps/web`, 519 under `vendor/ironcalc` |
| warpdotdev/warp | 6,379 | 4,113 `.rs`, 2,303 of them under `app/src` |
| openclaw/openclaw | 55,536 | 45,017 `.ts`, 1,558 `.swift` |
| nearai/ironclaw | 5,011 | 2,333 `.rs`, 314 `.ts` |
| block/buzz | 5,780 | 1,251 `.ts`, 1,040 `.rs`, 773 `.mjs`, 756 `.tsx` |

## 10. Evidence quality

- Dates and counts come from GitHub's API, which is primary; the summarising model in WebFetch
  occasionally garbled cosmetic details (for example it reported "Total Bytes: 1,282,177" for a language
  list whose bytes sum to about 68 MB), so I used the raw per-language bytes it returned and not its totals.
- Anthropic's cutoffs and retirement are first-party documentation; the retirement pattern is my
  inference from the same page.
- The line estimates are arithmetic from bytes with wide ranges. Only Warp's line count is from GitHub.
- Release-news items (Warp, Grok Build, EDG, Carbon, Lepton, Unturned, X) are from trade press and the
  repositories; the Grok Build line count is a secondary quote.
- All PR-quality statements are small-sample smell tests.

## 11. Queries run (discovery)

News and web: Claude Opus 4.6 system card cutoffs; Anthropic announcement; open-sources internal codebase
2026; GitHub Octoverse 2025 fastest growing; "now open source" engine / database / IDE / browser 2026;
Warp open source; Mojo compiler open source; X codebase open source (twice); s&box open source; Fenris
Carbon; Cursor FastRender; Valve Lepton; Unturned source; EDG front end open source; Macro open source;
Microsoft / Google / Meta / Apple / Amazon / NVIDIA open-sourcing 2026; Huawei CANN GitCode; startup
monorepo opened 2026; source-available to open source relicense 2026; kernel / firmware / driver first
release 2026; Phoronix source released 2026.

GitHub API: repository search with `created:>2025-09-01` plus `size:>` and `stars:>` thresholds, overall
and by language (Rust, C++, Go, Java, C#, C, Python), by topic (database, game-engine, operating-system)
and by licence (AGPL-3.0, Apache-2.0); then per-candidate repository, languages, commits, pulls,
contents, code-frequency and issue-search calls. A commit-message search for "initial public release"
returned only noise and was dropped. The GamingOnLinux "source code release" category page was read in
full for the window [49].

## Sources

Anthropic
1. Claude Opus 4.6 model page: https://platform.claude.com/docs/en/models/opus-4-6/overview (read 2026-10-14)
2. Models overview: https://platform.claude.com/docs/en/models/overview
3. Model deprecations: https://platform.claude.com/docs/en/about-claude/model-deprecations
4. Model IDs and versioning: https://platform.claude.com/docs/en/about-claude/models/model-ids-and-versions
5. How up to date is Claude's training data: https://support.claude.com/en/articles/8114494-how-up-to-date-is-claude-s-training-data
6. Introducing Claude Opus 4.6 (2026-02-05): https://www.anthropic.com/news/claude-opus-4-6
7. Opus 4.6 system card (PDF, unread, over the 10 MB fetch limit): https://www.anthropic.com/claude-opus-4-6-system-card
8. Transparency Hub model report: https://www.anthropic.com/transparency/model-report

Warp
9. https://github.com/warpdotdev/warp
10. https://api.github.com/repos/warpdotdev/warp
11. https://api.github.com/repos/warpdotdev/warp/languages
12. First commit: https://api.github.com/repos/warpdotdev/warp/commits?per_page=1&page=2531
13. Merged PRs: https://api.github.com/search/issues?q=repo%3Awarpdotdev%2Fwarp%20is%3Apr%20is%3Amerged&per_page=1 (feat and fix counts use the same URL with `feat%20in%3Atitle` / `fix%20in%3Atitle`)
14. https://api.github.com/repos/warpdotdev/warp/stats/code_frequency
15. https://api.github.com/repos/warpdotdev/warp/contents/crates and /contents/specs
16. Help Net Security, Warp open sources its AI terminal client (2026-04-30): https://www.helpnetsecurity.com/2026/04/30/warp-open-source-client/
17. https://api.github.com/search/commits?q=repo%3Awarpdotdev%2Fwarp+Repo-Sync-Origin
18. PR samples: https://api.github.com/repos/warpdotdev/warp/pulls?state=closed&per_page=6&page=120 (also pages 240, 330, and the latest page)
26. https://api.github.com/orgs/warpdotdev/repos

Macro
19. https://github.com/macro-inc/macro
20. https://api.github.com/repos/macro-inc/macro/languages
21. https://api.github.com/repos/macro-inc/macro/commits?per_page=1&page=6761 (and page=6760)
22. https://api.github.com/repos/macro-inc/macro/pulls?state=all&sort=created&direction=asc&per_page=5
23. https://api.github.com/search/issues?q=repo%3Amacro-inc%2Fmacro%20is%3Apr%20is%3Amerged&per_page=1 (feat and fix variants as above)
24. https://api.github.com/repos/macro-inc/macro/contents/crates (also /packages, /services, /docs, and the root tree)
25. https://api.github.com/orgs/macro-inc/repos
31. https://api.github.com/repos/macro-inc/macro/pulls?state=closed&per_page=30&page=40

OpenClaw, IronClaw, Buzz and others
27. https://api.github.com/repos/openclaw/openclaw (created 2025-11-24)
28. https://api.github.com/repos/openclaw/openclaw/commits?per_page=1&page=110224
29. https://api.github.com/repos/openclaw/openclaw/languages
30. https://api.github.com/search/issues?q=repo%3Aopenclaw%2Fopenclaw%20is%3Apr%20is%3Amerged&per_page=1 (feat and fix variants)
32. https://api.github.com/repos/openclaw/openclaw/contents/src (also /extensions, /packages, /ui/src, /test, /src/agents, /src/test-fixtures, and the root tree)
33. OpenClaw page and PR samples: https://github.com/openclaw/openclaw ; https://api.github.com/repos/openclaw/openclaw/pulls?state=closed&per_page=6&page=3000 ; IronClaw: https://github.com/nearai/ironclaw , https://api.github.com/repos/nearai/ironclaw/commits?per_page=1&page=4073 , merged-PR search as above
34. Buzz: https://github.com/block/buzz ; https://api.github.com/repos/block/buzz/commits?per_page=1&page=2888 ; merged-PR search as above
35. Repository search, e.g. https://api.github.com/search/repositories?q=created%3A%3E2025-09-01+size%3A%3E150000+stars%3A%3E300+fork%3Afalse&sort=stars&order=desc ; PR page samples for IronClaw and Buzz (`pulls?state=closed&per_page=6&page=200` and `page=150`); per-repository `/languages` and issue-search calls for stablyai/orca, paperclipai/paperclip, nexu-io/open-design, fluxerapp/fluxer, iflytek/astron-agent

Near misses
36. https://api.github.com/repos/xai-org/grok-build and /commits?per_page=6
37. Digital Applied, Grok Build open source (secondary): https://www.digitalapplied.com/blog/grok-build-open-source-72-hours-trust-repair
38. https://api.github.com/repos/Facepunch/sbox-public (also /languages, /pulls?state=closed, /commits?per_page=1&page=2416) ; https://github.com/Facepunch/sbox-public
39. https://github.com/edgcpp/compiler ; https://api.github.com/repos/edgcpp/compiler (also /languages, /contents/src, /commits?per_page=1&page=62419)
40. Hackaday, The EDG C++ compiler frontend has been open sourced (2026-10-06): https://hackaday.com/2026/10/06/the-edg-c-compiler-frontend-has-been-open-sourced/ ; Phoronix (search snippet only, page returned 403): https://www.phoronix.com/news/edg-cpp-open-sourced
41. https://api.github.com/repos/modular/modular (also /languages, /commits) ; Linuxiac (search snippet): https://linuxiac.com/mojo-programming-language-goes-fully-open-source/
42. https://api.github.com/repos/ZSvirt/zsvirt ; https://api.github.com/repos/zstackio/zstack
43. https://api.github.com/orgs/carbonengine/repos ; https://api.github.com/repos/carbonengine/trinity/languages ; Open Source For You (2026-07): https://www.opensourceforu.com/2026/07/fenris-creations-carbon-game-engine-goes-open-source-on-github/
44. https://api.github.com/orgs/SmartlyDressedGames/repos ; search snippet: https://logicservers.com/blog/unturned-source-code-released
45. https://www.opensourceforu.com/2026/07/x-announces-full-open-source-release-of-its-codebase/ ; https://api.github.com/repos/xai-org/x-algorithm
46. https://itsfoss.com/news/valve-lepton/
47. Layer5, Claude Code source leak (search snippet): https://layer5.io/blog/engineering/the-claude-code-source-leak-512000-lines-a-missing-npmignore-and-the-fastest-growing-repo-in-github-history/
48. Huawei, Ascend CANN open-sourcing (search snippet): https://www.huawei.com/en/news/2025/9/hc-shengten-opensource
49. GamingOnLinux source-code-release category (lists WSL on 2025-05-19, s&box, Carbon, Unturned, Lepton): https://www.gamingonlinux.com/articles/category/source-code-release/
50. TechCrunch, Microsoft open sources Edit and WSL at Build (2025-05-19): https://techcrunch.com/2025/05/19/microsoft-open-sources-a-command-line-text-editor-and-more-at-build/
51. Fastrender: https://api.github.com/repos/wilsonzlin/fastrender (also /languages and the merged-PR search); The Register (search snippet): https://www.theregister.com/2026/01/22/cursor_ai_wrote_a_browser/
