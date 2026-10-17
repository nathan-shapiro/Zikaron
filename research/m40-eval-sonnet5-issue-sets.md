# Research note: which repository and issue set a Sonnet 5 / Sonnet 4.6 / Opus 4.5 / Opus 4.6 evaluation can use

Written 2026-10-16 by memory-assistant for memory-researcher. Every GitHub figure was read from GitHub's REST
API through WebFetch on 2026-10-16 (a small model summarises each response, so counts are the API's
`total_count` fields as relayed; see section 9 for what that does to precision). Anthropic figures were read
from the documentation pages named in section 2. This note extends, and does not repeat,
`research/m40-eval-repository-candidates.md` (the five-candidate screen against Opus 4.6; its first-public
dates and file counts are reused here). It has no shell, so no clone was made: every file count below is
either from the API's tree listing (stated where exact) or an estimate, and section 8 gives the commands that
make them exact.

## 0. The brief, restated, with the two additions

Re-screen the five candidates (macro-inc/macro, warpdotdev/warp, openclaw/openclaw, nearai/ironclaw,
block/buzz) for a code-knowledge evaluation in which a documenter model writes per-file documentation of one
module, and a reader model triages already-triaged GitHub issues (localise the cause to files and explain
it) with and without that documentation, scored against what the maintainers found and the files the merged
fix PR changed. The repository must be newer than the model's training data. Questions:

1. Documented training-data and reliable-knowledge cutoffs, release dates, retirement status of Claude Sonnet 5
   and Sonnet 5.5. Added by the coordinator mid-task: the same for **Claude Opus 4.5** (also its exact API id)
   and **Claude Sonnet 4.6** (Opus 4.6 is in the existing note, re-read here), with a pass/fail column for each.
2. Pass/fail of each candidate's first public commit against each model's training-data cutoff, with margin.
3. For passing candidates, the number of issues that are (a) opened and closed after the cutoff, (b) carry a
   triage-style label, (c) closed by a merged PR; five concrete issue-to-PR examples each, changed-file
   counts, whether the thread contains a diagnosis; exact queries. Added: count against the cutoff of
   whichever model leaves the most, and name it; also against the later of the two 4.6 cutoffs.
4. For the best one or two candidates, a coherent 150-500-file directory where most of the fix PRs land.
5. Confounds: earlier public copies, mirrors, forks, vendored or generated code.

## 1. Bottom line

- **Sonnet 5.5 rules out all five candidates.** Its documented reliable and training-data cutoffs are both
  Jun 2026; the newest candidate (Warp) went public 2026-04-28, 63 days before the end of June.
  **The Claude Code alias `sonnet` resolves to Sonnet 5.5 on the Anthropic API**, so an agent definition
  saying `model: sonnet` runs a model that has probably seen every candidate. Pin an explicit id.
- **Sonnet 5 and Sonnet 4.6 (training-data cutoff Jan 2026 per the API model pages) pass three candidates:**
  Warp (+87 days, 2.9 months), Buzz (+34 days, 1.1 months) and IronClaw (+3 days, effectively no margin).
  Macro (-84 days) and OpenClaw (-68 days; it was Warelay/Clawdbot/Moltbot and went viral in late Jan 2026)
  fail.
- **Opus 4.5 and Opus 4.6 (training-data cutoff Aug 2025) pass all five**, with margins of 69 to 240 days.
- **Sources disagree about Sonnet 4.6.** The API model page says reliable cutoff Aug 2025 and training data
  Jan 2026; the Transparency Hub says "knowledge cutoff date of May 2025"; the support article says "trained
  on data up until August 2025". This note screens against the latest (Jan 2026), which is the safe reading.
- **Warp is the only candidate that holds up across the plausible model pairs** (anything except Sonnet 5.5).
  At the Jan 2026 line it has 351 closed issues with a linked PR, 230 of them labelled `bug` + `triaged`; at the
  Aug 2025 line, 379 and 244. The 10 newest linked issues all had a merged fix PR.
- **No candidate has a 150-500-file directory where most fixes land.** In a sample of 20 Warp fix PRs, 65%
  touch something under `app/src` (2,300+ Rust files), 50% touch `app/src/terminal` or `app/src/workspace`
  (about 620 non-test Rust files, estimated), 30% touch `app/src/terminal` alone (about 540, estimated).
  The module has to be chosen first and the issue set filtered to fixes that land in it.
- **Two things in Warp's threads change what "what the maintainers found" means.** A bot
  (`warp-for-oss[bot]`) posts a root-cause diagnosis naming files and functions within minutes of most triaged
  bug reports, and many fix PRs are written by another bot (`warp-agent-staging[bot]`). The comparison target is
  often one LLM's diagnosis, and the thread leaks the answer if the reader sees it (section 6).

## 2. Question 1: the models, as Anthropic documents them

### 2.1 Exact rows

Source [1] is the model overview, [2] to [6] the per-model pages (all under platform.claude.com/docs/en),
[7] the deprecations page. Rows are quoted from the Capabilities and Availability tables of each model page.

| Model | API id | Released | Reliable knowledge cutoff | Training data cutoff | Status | Retirement |
|---|---|---|---|---|---|---|
| Claude Opus 4.5 [2] | `claude-opus-4-5-20251101`; alias `claude-opus-4-5` | November 24, 2025 | May 2025 | Aug 2025 | Active (legacy) | Not sooner than November 24, 2026 |
| Claude Opus 4.6 [3] | `claude-opus-4-6` | February 5, 2026 | May 2025 | Aug 2025 | Active (legacy) | Not sooner than February 5, 2027 |
| Claude Sonnet 4.6 [4] | `claude-sonnet-4-6` | February 17, 2026 | Aug 2025 | **Jan 2026** | Active (legacy) | Not sooner than February 17, 2027 |
| Claude Sonnet 5 [5] | `claude-sonnet-5` | June 30, 2026 | Jan 2026 | Jan 2026 | Active (legacy) | Not sooner than June 30, 2027 |
| Claude Sonnet 5.5 [6] | `claude-sonnet-5-5` | September 28, 2026 | Jun 2026 | Jun 2026 | Active (latest) | Not sooner than September 28, 2027 |

Quoted rows from the pages (verbatim, short):

- Opus 4.5 page [2]: `| Reliable knowledge cutoff | May 2025 |`, `| Training data cutoff | Aug 2025 |`,
  `| Released | November 24, 2025 |`, `| Retirement | Not sooner than November 24, 2026 |`,
  `| Claude API | claude-opus-4-5-20251101 |`, `| Claude API alias | claude-opus-4-5 |`,
  `| Status | Active (legacy) |`.
- Opus 4.6 page [3]: `| Reliable knowledge cutoff | May 2025 |`, `| Training data cutoff | Aug 2025 |`,
  `| Released | February 5, 2026 |`, `| Retirement | Not sooner than February 5, 2027 |`.
- Sonnet 4.6 page [4]: `| Reliable knowledge cutoff | Aug 2025 |`, `| Training data cutoff | Jan 2026 |`,
  `| Released | February 17, 2026 |`, `| Retirement | Not sooner than February 17, 2027 |`,
  `| Claude API | claude-sonnet-4-6 |`.
- Sonnet 5 page [5]: `| Reliable knowledge cutoff | Jan 2026 |`, `| Training data cutoff | Jan 2026 |`,
  `| Released | June 30, 2026 |`, `| Retirement | Not sooner than June 30, 2027 |`,
  `| Status | Active (legacy) |`.
- Sonnet 5.5 page [6]: `| Reliable knowledge cutoff | Jun 2026 |`, `| Training data cutoff | Jun 2026 |`,
  `| Released | September 28, 2026 |`, `| Retirement | Not sooner than September 28, 2027 |`,
  `| Status | Active (latest) |`.
- Models overview [1], the one-table view for the current lineup: `| Reliable knowledge cutoff | Jun 2026 | Jun 2026 |
  Jun 2026 | Jun 2026 |` and `| Training data cutoff | Jun 2026 | Jun 2026 | Jun 2026 | Jun 2026 |` across
  Fable 5.1, Opus 5.5, Sonnet 5.5, Haiku 5.5; `| Retirement | ... | Not sooner than September 28, 2027 | ... |`
  for Sonnet 5.5. Sonnet 5, Sonnet 4.6, Opus 4.5 and 4.6 are listed there only as legacy links.
- Deprecations page [7] status table: `claude-sonnet-5-5 | Active | N/A | Not sooner than September 28, 2027`,
  `claude-sonnet-5 | Active | N/A | Not sooner than June 30, 2027`, `claude-sonnet-4-6 | Active | N/A | Not sooner
  than February 17, 2027`, `claude-opus-4-6 | Active | N/A | Not sooner than February 5, 2027`,
  `claude-opus-4-5-20251101 | Active | N/A | Not sooner than November 24, 2026`.

All five are documented. None is deprecated as of 2026-10-16.

### 2.2 Retirement, and the Opus 4.5 clock

- The page commits to "at least 60 days' notice" before retirement of a publicly released model [7]. The "not
  sooner than" fields are floors, not dates. The most recent notice on the page: Sonnet 4.5
  (`claude-sonnet-4-5-20250929`) deprecated 2026-09-30, retiring 2026-11-30 [7] (two months).
- **Opus 4.5's floor, 2026-11-24, is five weeks from today** and is the earliest of the five. No deprecation
  notice exists for it. By the 60-day rule, a notice issued today could not retire it before about 2026-12-15
  (my arithmetic, not an Anthropic statement). Sonnet 4.5's pattern (notice about 12 months after its
  snapshot date, retirement two months later) points to a notice for Opus 4.5 around Nov-Dec 2026 and a
  retirement around Jan-Feb 2027 (my inference from [7], not stated by Anthropic). Opus 4.5 is therefore the
  model most likely to disappear mid-programme; Opus 4.6 and Sonnet 4.6 have floors in February 2027.
- Record the exact model id and the Claude Code version per run; reproducibility ends at retirement.

### 2.3 Where Anthropic's own sources disagree

| Model | API model page [2]-[6] | Transparency Hub [8] | Support article [9] |
|---|---|---|---|
| Opus 4.5 | reliable May 2025, training Aug 2025 | "knowledge cutoff date of May 2025" | not listed |
| Opus 4.6 | reliable May 2025, training Aug 2025 | "knowledge cutoff date of May 2025" | "trained on data up until August 2025" |
| Sonnet 4.6 | reliable Aug 2025, **training Jan 2026** | "knowledge cutoff date of May 2025" | "trained on data up until August 2025" |
| Sonnet 5 | reliable Jan 2026, training Jan 2026 | "knowledge cutoff date of January 2026" | "trained on data up until January 2026" |
| Sonnet 5.5 | reliable Jun 2026, training Jun 2026 | not found in the portion read | "trained on data up until June 2026" |

The Hub and the support article use one term ("knowledge cutoff"). Reading them against the API pages, they
match the *reliable* cutoff for Opus 4.5 and the *training-data* cutoff for Opus 4.6 and Sonnet 4.6. The
Hub's Sonnet 4.6 figure (May 2025) is lower than the API page's *reliable* figure (Aug 2025) and cannot be
reconciled from the pages alone. The Hub page was read in two chunks (all 174K characters); an Opus 4.5 or
Sonnet 5.5 entry in a part I did not see is possible. **Use the API model page's training-data row as the
binding line**: it is the later date wherever the sources differ, so a pass against it is a pass against all
three. The Opus 4.6 system card was not readable at the time of the existing note, and the others were not
fetched.

### 2.4 Claude Code aliases (decides which model actually runs)

Claude Code's model-configuration page [10] gives this resolution table:

| Provider | `opus` | `sonnet` | `haiku` |
|---|---|---|---|
| Anthropic API | Opus 5.5 | Sonnet 5.5 | Haiku 5.5 |
| Claude Platform on AWS | Opus 5.5 | Sonnet 4.6 | Haiku 4.5 |
| Amazon Bedrock, Google Cloud | Opus 5.5 | Sonnet 4.5 | Haiku 4.5 |
| Microsoft Foundry | Opus 4.6 | Sonnet 4.5 | Haiku 4.5 |

It says aliases "point to the recommended version for your provider and update over time", and that a full
name or `ANTHROPIC_DEFAULT_SONNET_MODEL` / `ANTHROPIC_DEFAULT_OPUS_MODEL` pins a version; `claude --model
claude-sonnet-4-6`, `claude --model claude-opus-4-5` and subagent frontmatter `model: claude-sonnet-4-6` are
shown as valid forms. **Consequence:** the documenter and reader must be launched with explicit ids
(`claude-sonnet-5`, `claude-sonnet-4-6`, `claude-opus-4-5-20251101` or `claude-opus-4-5`, `claude-opus-4-6`).
An installed agent definition that says `model: sonnet` or `opus` is not a Sonnet 5 / Opus 4.5 run on the
Anthropic API; it is Sonnet 5.5 / Opus 5.5, for which every candidate fails.

## 3. Question 2: first public commit against each cutoff

Training-data cutoffs used (end of the named month): Opus 4.5 and Opus 4.6, 2025-08-31; Sonnet 4.6 and
Sonnet 5, 2026-01-31; Sonnet 5.5, 2026-06-30. A positive margin means the repository's first public commit
came after the cutoff. Days are counted from the last day of the month to the commit's date.

| Candidate | First public commit | Opus 4.5 / 4.6 (Aug 2025) | Sonnet 4.6 / Sonnet 5 (Jan 2026) | Sonnet 5.5 (Jun 2026) |
|---|---|---|---|---|
| macro-inc/macro | 2025-11-08 [11] | **pass**, +69 d (2.3 mo) | **fail**, -84 d (-2.8 mo) | fail, -234 d |
| openclaw/openclaw | 2025-11-24 (as Warelay) [12][13] | **pass**, +85 d (2.8 mo) | **fail**, -68 d (-2.2 mo) | fail, -218 d |
| nearai/ironclaw | 2026-02-03 [14] | **pass**, +156 d (5.1 mo) | **pass, marginal**, +3 d (0.1 mo) | fail, -147 d |
| block/buzz | 2026-03-06 [15] | **pass**, +187 d (6.1 mo) | **pass**, +34 d (1.1 mo) | fail, -116 d |
| warpdotdev/warp | 2026-04-28 [16] | **pass**, +240 d (7.9 mo) | **pass**, +87 d (2.9 mo) | fail, -63 d (-2.1 mo) |

Notes on the evidence:

- **Re-verified this session:** Warp root commit `0dbd3d5`, author date 2026-04-28T13:40:51Z, message
  "Initial public release of Warp." [16]; IronClaw's earliest commits are all dated 2026-02-03 by one author
  [14], and the repo's `created_at` is 2026-02-03; Buzz root commit `916f096f`, 2026-03-06T21:00:58Z, by
  `block-open-source[bot]`, "Initial commit" [15]; OpenClaw's earliest commits seen are 2025-11-25 and the
  Wikipedia article gives 2025-11-24 as first publication under the name Warelay [13].
  **Not re-verified:** Macro's 2025-11-08 root commit. The list endpoint with `until=2025-11-12` returned an
  empty array while `until=2025-11-30` returned commits from 2025-11-28, so the date filter and the last-page
  read in the existing note disagree; this changes nothing here because Macro fails on the volume test in
  section 4, but its date should not be cited as double-checked.
- **OpenClaw's lineage matters for the Jan 2026 line.** Warelay (2025-11-24), CLAWDIS (2025-12-03), Clawdbot
  (2026-01-02), Moltbot (2026-01-27), OpenClaw (2026-01-30), with viral growth in late January [13]. That is
  the existing note's "older public project renamed" disqualifier; it only bites for models whose cutoff
  falls after late January 2026.
- **IronClaw's +3 days** is a pass in principle (a repository that did not exist cannot be in a corpus frozen
  on 2026-01-31) and nothing more: a cutoff stated by month, a crawl lag, and the fact that IronClaw is
  "inspired by" the then-viral OpenClaw make "Jan 2026" an unreliable edge. Treat as marginal.
- **Sonnet 5.5 leads.** Nothing in the existing note's near-miss table helps: `xai-org/grok-build` (public
  2026-07-14, synced commits and no PRs), `edgcpp/compiler` (public 2026-09-30, 16 PRs), the Carbon
  repositories (small), `ZSvirt/zsvirt` (squashed, older project). A repository search for repos created
  after 2026-06-30 with size over 200 MB and over 300 stars returned 126 results, the top 15 being AI-agent
  and plugin projects (for example `deepseek-ai/deepseek-harness`, `anywhere-labs/dsh-desktop`,
  `kirodotdev/KiroCrew`), none examined; any such repository would have under 3.5 months of issue history.
  Sonnet 5.5 is effectively unusable for this evaluation unless it is pinned out.

## 4. Question 3: qualifying issues

### 4.1 Definitions and queries

All counts are GitHub issue-search `total_count` values (REST `search/issues`, unauthenticated, read through
WebFetch on 2026-10-16). Notation: `R` is `repo:OWNER/REPO`; `C` is the cutoff date.

- (a) opened and closed after the cutoff: `R is:issue is:closed created:>C` (an issue created after `C` and
  closed can only have been closed after `C`).
- (c) closed by a merged PR: **approximated** by `linked:pr` (issues that a pull request is linked to, which
  includes open or unmerged PRs). The exact condition needs the issue's `closed` event and the PR's `merged`
  flag. I checked it by sample: the 10 newest closed `linked:pr` Warp issues (#16277, #16121, #16087, #16067,
  #16043, #16019, #15821, #15768, #15753, #15718) each appear as the closing reference of a merged PR
  (#16294, #16124, #16094, #16102, #16055, #16093, #15870, #15999, #15763, #15720), found through the PR-side
  search `R is:pr is:merged linked:issue`, whose Warp total is 301.
- (b) triage-style label: per repository, section 4.2.

Queries (URL-encoded in the API, shown decoded; `C` values: Aug 2025 = `2025-08-31`, Jan 2026 =
`2026-01-31`, Jun 2026 = `2026-06-30`):

```
repo:warpdotdev/warp is:issue is:closed created:>2025-08-31                                   -> 2,182
repo:warpdotdev/warp is:issue is:closed created:>2026-01-31                                   -> 1,278
repo:warpdotdev/warp is:issue is:closed linked:pr created:>2025-08-31                         -> 379
repo:warpdotdev/warp is:issue is:closed linked:pr created:>2026-01-31                         -> 351
repo:warpdotdev/warp is:issue is:closed linked:pr created:>2026-06-30                         -> 63
repo:warpdotdev/warp is:issue is:closed linked:pr label:bug label:triaged created:>2025-08-31 -> 244
repo:warpdotdev/warp is:issue is:closed linked:pr label:bug label:triaged created:>2026-01-31 -> 230
repo:warpdotdev/warp is:issue is:closed linked:pr label:bug label:triaged created:>2026-06-30 -> 43
repo:warpdotdev/warp is:pr is:merged linked:issue                                             -> 301
repo:openclaw/openclaw is:issue is:closed created:>2025-08-31                                  -> 53,539
repo:openclaw/openclaw is:issue is:closed linked:pr created:>2025-08-31                        -> 22,556
repo:openclaw/openclaw is:issue is:closed linked:pr label:bug created:>2025-08-31              -> 7,414
repo:openclaw/openclaw is:pr is:merged linked:issue                                            -> 11,535
repo:nearai/ironclaw is:issue is:closed created:>2025-08-31                                    -> 1,449
repo:nearai/ironclaw is:issue is:closed linked:pr created:>2025-08-31                          -> 788
repo:nearai/ironclaw is:issue is:closed linked:pr label:bug                                    -> 144
repo:nearai/ironclaw is:pr is:merged linked:issue                                              -> 662
repo:block/buzz is:issue is:closed created:>2025-08-31                                         -> 270
repo:block/buzz is:issue is:closed linked:pr created:>2025-08-31                               -> 121
repo:block/buzz is:issue is:closed linked:pr label:bug                                         -> 24
repo:block/buzz is:pr is:merged linked:issue                                                   -> 77
repo:macro-inc/macro is:issue                                                                  -> 70 (all states)
repo:macro-inc/macro is:issue is:closed                                                        -> 33
repo:macro-inc/macro is:issue is:closed linked:pr                                              -> 6
```

IronClaw and Buzz have no issues older than their first public commits (2026-02-03 and 2026-03-06), so
their Aug 2025 and Jan 2026 counts are the same. Warp's Jan 2026 and Aug 2025 counts differ by 28 and 14
because its code was private until 2026-04-28: a fix PR cannot exist before then.

### 4.2 Labels each repository uses (from `repos/OWNER/REPO/labels`)

- **Warp (147 labels):** `bug`, `enhancement`, `triaged`, `needs-info`, `ready-to-implement`, `duplicate`;
  `repro:high|medium|low`; `os:mac|linux|windows`; 27 `area:*` labels (`area:agent`, `area:terminal-input`,
  `area:shell-terminal`, `area:completions`, `area:window-tabs-panes`, `area:workspace`,
  `area:ui-framework`, `area:settings-keybindings`, `area:editor-notebooks`, ...); `agent:bug`,
  `agent:priority-high`; a bot-applied `warp:auto-triage-review`; and about 60 `factory:*` labels from the
  vendor's agent-automation experiments. This is the richest and most consistent triage vocabulary of the five.
- **OpenClaw (168 labels):** `bug`, `bug:behavior`, `bug:crash`, `regression`, `P0` to `P3`, `impact:*`
  (`impact:data-loss`, `impact:crash-loop`, ...), `channel:*` (33 channels), `app:*`, `close:*`, `clawsweeper:*`
  (an automation family), `size:*`.
- **IronClaw (127 labels):** `bug`, `bug_bash_P0..P3`, `p0..p3`, `suggested_P0`, `scope: *` (29 scopes),
  `module:M1..M5`, `risk: *`, `size: *`, `contributor: *`, `reborn`, `epic`.
- **Buzz (16 labels):** `bug`, `enhancement`, `triage-ready`, `impact:high|low`, `risk:high|low`, `duplicate`,
  `invalid`, `wontfix`. Most closed bug issues carry only `bug` or no label (three of the five examples below
  have none).
- **Macro (33 labels):** `bug`, `enhancement`, `planned`, `not-planned`, `web-app`, `native-apps`; almost no
  issues use them.

### 4.3 Counts by model line

"Qualifying" in the table is the upper-bound `linked:pr` count, with the label-filtered count beside it. The
PR-side figure (merged PRs with a linked issue) is a PR-level cross-check, not a strict bound.

| Repository | Opus 4.5 / 4.6 line (created after 2025-08-31): closed + linked PR / with triage label | Sonnet 4.6 / Sonnet 5 line (after 2026-01-31) | Merged PRs with a linked issue (all time) | Verdict on volume |
|---|---|---|---|---|
| Warp | **379 / 244** (`bug` + `triaged`) | **351 / 230** | 301 | enough for 50-100 questions at any module filter |
| OpenClaw | 22,556 / 7,414 (`bug`) | fails the cutoff | 11,535 | far more than needed |
| IronClaw | 788 / 144 (`bug`) | 788 / 144 (marginal pass) | 662 | enough |
| Buzz | 121 / 24 (`bug`) | 121 / 24 | 77 | thin: 24 labelled bugs |
| Macro | 6 (33 closed, 70 total) | fails the cutoff | not queried | **fails**: too few issues |

**The cutoff that leaves the most is the Aug 2025 line (Opus 4.5 and Opus 4.6, which share it).** For Warp
that is 379 / 244, against 351 / 230 for the later of the two 4.6 cutoffs (Sonnet 4.6, Jan 2026) and 63 / 43
if only issues created after the Sonnet 5.5 cutoff are counted (those issues postdate Sonnet 5.5's
training data, but the code they concern was public and inside it, so that line is not a pass; section 6).
Estimated qualifying issues under condition (c) strictly: the `linked:pr` count (379 at the Aug 2025 line) is
the upper bound; the PR-side 301 is a rough floor only if each merged PR closes one issue (some close several,
some issues have several PRs, and some of the 301 close pre-cutoff issues). I put Warp at roughly 250 to 379
at the Aug 2025 line. This is a range from two bounding queries and a 10-of-10 sample, not a count.

### 4.4 Five or more examples per passing candidate

Fix-PR numbers, changed-file counts and thread notes were read from `pulls/N/files`, `issues/N`,
`issues/N/comments` and `issues/N/timeline`. "Files" counts every changed file; the split into source and
test files is in parentheses.

**Warp (15 pairs with a diagnosis or labels worth reporting; all issues created after 2026-01-31).**

| # | Issue (created) | Labels | Fix PR (merged) | Files changed | Diagnosis in the thread |
|---|---|---|---|---|---|
| 1 | #16277 tab rename broken (2026-10-04) | bug, triaged, ready-to-implement, repro:medium, area:ui-framework, area:window-tabs-panes | #16294 | 2 (1 src, 1 test): `app/src/workspace/view.rs`, `view_tests.rs` | Yes, human: a contributor traced it to commit 43eae5e (PR #16138), unconditional focus restoration; bot confirmed. An earlier fix PR #16278 was closed unmerged |
| 2 | #16067 crash opening model selector via keybinding (2026-09-17) | bug, triaged, repro:medium, area:agent, area:ui-framework, agent:bug | #16102 | 2 (1, 1): `app/src/terminal/input.rs`, `input_tests.rs` | Yes, bot: names `AppContext::update_view`, `Input::open_model_selector_and_snapshot_prompt`, `try_update_view`, `ViewUpdateError::WindowClosed`; fix is in `input.rs` |
| 3 | #16043 image paste into Codex broke after macOS 27 (2026-09-16) | bug, triaged, ready-to-implement, repro:high, area:agent, area:terminal-input | #16055 | 3 (2, 1): `crates/warp_tui/src/attachment_bar/image_processing.rs` and its tests, `crates/warpui/src/platform/mac/clipboard.rs` | Partial, human: macOS changed the screenshot format; no files named |
| 4 | #16019 native completions never fire for npx args (2026-09-15) | bug, duplicate, triaged, repro:high, area:completions, area:terminal-input | #16093 | 2 (1, 1): `app/src/terminal/input.rs`, `crates/integration/src/test/native_shell_completions.rs` (one-line comment) | Bot comment states the symptom only; the issue also carries `duplicate` |
| 5 | #15753 crash on emoji at row wrap during secret scan (2026-09-02) | bug, triaged, repro:high, area:shell-terminal | #15763 | 6 (4, 2): `crates/warp_terminal/src/model/grid/{ansi_handler,cell,flat_storage/row_iterator,flat_storage/testing}.rs`, two test files | Yes, bot: names `RowIterator::next`, flat storage, grapheme width; the actual fix is mostly in `ansi_handler.rs` and `cell.rs` |
| 6 | #15718 crash during agent run (2026-09-01) | bug, needs-info, triaged, repro:medium, area:agent, area:editor-notebooks | #15720 | 2 (1, 1): `crates/editor/src/content/core.rs`, `markdown_tests.rs` | Yes, bot twice: names `AIBlock::handle_create_documents_stream_update`, `NotebooksEditorModel::update_to_new_markdown`, `Buffer::apply_formatted_text_delta`, `Buffer::modify_first_selection`; the fix lands in the editor crate |
| 7 | #15410 PS1 expanded twice with honor_ps1 (2026-08-21) | bug, triaged, repro:high, os:linux, area:shell-terminal | #15792 | 4 (1, 3): `app/assets/bundled/bootstrap/bash_body.sh`, three `crates/integration` files | Yes, bot: names `bash_body.sh`, `warp_precmd`, `PROMPT_COMMAND`, `header_grid.rs`, `terminal_model.rs`, `blocks.rs` |
| 8 | #15309 hidden Alt+1 binding cannot be remapped (2026-08-19) | bug, triaged, repro:high, os:windows, area:settings-keybindings, area:terminal-input, area:workspace | #15310 | 1 (1, 0): `app/src/workspace/mod.rs` | Yes, bot twice: names `CustomAction::ToggleProjectExplorer`, `workspace::init`, `app/src/workspace/mod.rs`, `crates/warpui_core/src/keymap/matcher.rs` |
| 9 | #14241 new tab group's terminal steals focus (2026-07-24) | bug, triaged, ready-to-implement, repro:medium, area:window-tabs-panes, area:terminal-input | #14895 | 4 (2, 2): `app/src/terminal/view.rs`, `app/src/workspace/view.rs`, two test files | Yes, bot and the human who wrote the fix, with line numbers in `terminal/view.rs`, `terminal/model/blocks.rs`, `workspace/view.rs` |
| 10 | #13073 "New group with tab" offered on a grouped tab (2026-06-26) | bug, triaged, repro:high, area:window-tabs-panes | #13080 | 4 (2, 2): `app/src/tab.rs`, `app/src/workspace/view.rs`, two tests | The issue body already names `app/src/tab.rs` as the cause |
| 11 | #12817 OSC 1337 without a second parameter panics (2026-06-19) | bug, triaged, ready-to-implement, repro:high, area:shell-terminal | #12889 | 2 (1, 1): `app/src/terminal/model/ansi/mod.rs`, `mod_tests.rs` | The body states the cause (`params[1]` read without a length check) |
| 12 | #12990 `/open-file` cannot clear to empty (2026-06-24) | bug, triaged, ready-to-implement, repro:high, area:completions, area:terminal-input | #13017 | 3 (2, 1): `app/src/terminal/input.rs`, `input/slash_commands/mod.rs`, `input_tests.rs` | 3 comments; not read |
| 13 | #11679 crash in AI block render (2026-05-26) | bug, triaged, repro:high, area:agent, area:ui-framework | #11766 | 2 (1, 1): `app/src/ai/blocklist/block/view_impl/common.rs`, `common_tests.rs` | Title carries the panic site (`warp::ai::blocklist render_text_sections`); 7 comments, not read |
| 14 | #11138 space in tab params switches field (2026-05-17) | bug, triaged, ready-to-implement, repro:high, area:launch-configs | #11412 | 1: `app/src/tab_configs/params_modal.rs` | 4 comments; not read |
| 15 | #11016 stale git diff chip (2026-05-15) | bug, needs-info, triaged, repro:medium, area:code-review, area:workspace | #11242 | 1: `app/src/context_chips/current_prompt.rs` | 1 comment; not read |

Poor ground truth, kept out of any scored set: #15821 (`/model` keybinding erases the typed prompt;
bug, triaged, 2026-09-04) was closed by #15870, whose two files (`app/Cargo.toml`,
`crates/warp_features/src/lib.rs`) only promote a feature flag, so the changed files do not contain the
cause (the bot's diagnosis names `app/src/terminal/input/slash_commands/mod.rs`, `input.rs` and
`app/src/ai/blocklist/agent_view/agent_input_footer/mod.rs`). #16121 (flag completions after `--`, bug,
2026-09-22) was closed by #16124 (8 files, all in `crates/warp_completer`) but has no `triaged` label and no
comments. #7099 (bug, triaged, created 2025-08-17, closed 2026-08-14 by #15118) is excluded by condition
(a) at both lines: it predates 2025-08-31.

**Buzz (5 pairs).** Closed + linked + `bug`: 24. Issue bodies are written as full diagnoses; the threads are
short, so the "diagnosis" is the body.

| Issue (created) | Labels | Fix PR | Files | Notes |
|---|---|---|---|---|
| #6218 desktop deletes keyring identity before fallback (2026-08-18) | bug | #7203 | 2: `desktop/src-tauri/src/app_state.rs`, `app_state_tests.rs` | 0 comments |
| #5313 markdown tables clip long cells (2026-08-08) | bug | #7279 | 5 (3 src/config, 2 e2e tests): `desktop/src/shared/ui/markdown.tsx`, `markdown/MarkdownTable.tsx`, `desktop/playwright.config.ts`, two specs | 0 comments |
| #8122 agent-to-agent mention gives no reply destination (2026-10-06) | none | #8124 | 3: `crates/buzz-acp/src/{lib,pool,queue}.rs` | Body names `resolve_reply_anchor` in `queue.rs` and the root cause; 0 comments |
| #7927 `buzz-pair` panics on wss relays (2026-09-27) | none | #7998 | 3: `Cargo.lock`, `crates/buzz-pairing-cli/Cargo.toml`, `src/main.rs` | Body names the crate and the cause; the PR is labelled `triage-ready` |
| #5450 sibling gate caches transport failure (2026-08-10) | none | #7216 | 2: `crates/buzz-acp/src/lib.rs`, `relay.rs` | Body names three functions and the cause; 2 comments |

**IronClaw (4 pairs, fix PR found by a body search for the issue number; a fifth bug issue, #6900, closed
2026-08-13, had no PR naming its number).** Closed + linked + `bug`: 144.

| Issue (created) | Labels | Fix PR | Files | Notes |
|---|---|---|---|---|
| #6898 `write_file` corrupts binary documents (2026-07-30) | bug, suggested_P0, reborn | #7109 (also #7163) | 4: `crates/extensions/ironclaw_extension_support/src/coding/{file,mod,state}.rs`, `crates/ironclaw_host_runtime/tests/first_party_builtin_tools.rs` | Thread is bot commands only |
| #6896 triggered-run failures never delivered (2026-07-30) | bug, suggested_P0, reborn | #7131 | 13, across at least five crates plus docs and a budget file | Body names six files and states the cause |
| #7204 composer focus on "+ New" (2026-08-05) | bug, size: S, risk: low, scope: channel/web, module:M1-webui-product | #7205 | 10, incl. `crates/ironclaw_webui/frontend/src/...` and `tests/e2e/...` | 2 comments |
| #7209 CI regression gate cannot see `node:assert` (2026-08-05) | bug, size: S, scope: ci | #7211 | not fetched | CI, not product code |

**OpenClaw (5 pairs; Opus line only).** Closed + linked + `bug`: 7,414.

| Issue (created) | Labels | Fix PR | Files | Notes |
|---|---|---|---|---|
| #144148 heartbeat scratch not persisted when `notify=true` (2026-09-10) | P0, impact:data-loss, impact:session-state | #144377 | 9 (3 src, 6 tests): `src/agents/embedded-agent-runner/run/{attempt-result,deferred-lifecycle-owner}.ts`, `src/agents/embedded-agent-subscribe.ts`, `src/auto-reply/reply/dispatch-from-config.prepare-context.ts` | Reporter's body names a bundled `dist/` file, not a source file; closed the same day, 2 comments |
| #144325 dev update repair refuses migrations (2026-09-10) | P0, clawsweeper:fix-shape-clear, impact:ux-release-blocker | #144367 | 4 (1 src, 3 tests): `src/plugins/doctor-contract-registry.ts` | Body names four source files |
| #144380 bundle identifiers lost on plist failure (2026-09-10) | P2, maintainer | #144381 | 2: `src/infra/installed-apps.ts`, `.test.ts` | Filed by the maintainer 30 minutes before the PR |
| #144471 WebChat duplicates commentary (2026-09-10) | P2, clawsweeper:source-repro, impact:session-state | #144498 | 6 (3, 3): `ui/src/lib/chat/chat-types.ts`, `ui/src/pages/chat/{stream-segment-pruning,tool-stream-preamble}.ts` | Filed by `roboclaw-bot`, closed within an hour |
| #148974 doctor cannot migrate legacy Skill Workshop backup (2026-09-15) | bug, regression, P2, clawsweeper:source-repro | #148995 | 3: `src/commands/doctor-skill-workshop-collection-backups.ts`, one test, one doc | Thread has a human diagnosis naming file and functions, then maintainer confirmation |

**Macro.** Fails the volume test (6 closed issues with a linked PR); the one inspected, #7792 (create-API-key
dialog focuses the Close button, created 2026-10-08), has no labels. Not taken further.

## 5. Question 4: is there a 150-500-file module where the fixes land?

### 5.1 Method

For each of 20 Warp bug-fix PRs (the 15 above, #15870 and #16124, plus #11673, #11611, #12965; issues created
from May 2026 onward, three of them dated by issue-number order rather than individually), I listed the
changed files and recorded where the non-test source files sit. The sample is the PRs I happened to retrieve
(newest first within August, September, June and May windows plus the issue-side list), not a random draw.

| Where a source file of the PR lands | PRs (of 20) |
|---|---|
| `app/src/terminal/**` | #16102, #16093, #14895, #12889, #13017, #12965 = 6 (30%) |
| `app/src/workspace/**` (incl. `app/src/tab.rs` with it) | #16294, #15310, #14895, #13080, #11611 = 5 (25%) |
| `app/src/terminal/**` or `app/src/workspace/**` | 10 (50%) |
| `app/src/ai/**` | #11766, #11611 = 2 (10%) |
| anywhere under `app/src/**` | 13 (65%): the above plus `tab_configs` (#11412) and `context_chips` (#11242) |
| only `crates/**` | #16055 (`warp_tui`, `warpui`), #15763 (`warp_terminal`), #15720 (`editor`), #16124 (`warp_completer`), #15870 (`warp_features`) = 5 |
| only bootstrap shell scripts and integration tests | #15792, #11673 = 2 |

With n = 20, a share of 10 has a 95% interval of roughly 30%-70%, and 6 of roughly 14%-52%.

### 5.2 Sizes (estimated; the API tree listings were cut off by the fetch tool except where stated)

| Directory | Files | Basis |
|---|---|---|
| `app/src/workspace` | **93 blobs, 89 `.rs`, 13 test files** | Complete tree listing (`truncated: false`) |
| `app/src/terminal` | **about 770 blobs, about 675 `.rs`, about 130 test files**; about 540 non-test `.rs` | Two chunks of the recursive tree listing (about 450 blobs in the first 100K characters, 317 in the remainder); counts relayed by the summariser, so within perhaps 10% |
| `app/src/ai` | about 700 entries | Only the first 100K of 170K characters read; sub-directory counts are rough (`agent_sdk` about 180, `blocklist` about 80, `agent` about 60) |
| `app/src` (all) | 2,303 `.rs` | Existing note, from a clone |
| Crates | 93 directories under `crates/` | `contents/crates` listing; fix PRs sampled touched `warp_completer`, `warp_terminal`, `editor`, `warp_tui`, `warpui`, `warp_features`, `integration` |

### 5.3 Answer

**No directory of 150-500 files captures most fix PRs, in Warp or elsewhere in the sample.** The best single
choice, `app/src/terminal`, holds about 540 non-test Rust files (just above the band) and caught 30%; adding
`app/src/workspace` (76 non-test) reaches 50% at about 620 files; the rest of the fixes sit in a long tail of
crates and directories. `app/src/ai` is the nearest thing to a second module and catches 10%.

For the other candidates, only small samples exist and they point the same way: Buzz's five fix PRs split
between `crates/buzz-acp/` (2), `desktop/` (2) and `crates/buzz-pairing-cli/` (1); IronClaw's three product
PRs touched three different crate groups (`ironclaw_extension_support`, `ironclaw_webui`, the trigger and
run-delivery crates); OpenClaw's five PRs touched `src/agents` and `src/auto-reply`, `src/plugins`, `src/infra`,
`ui/src/pages/chat`, and `src/commands`. IronClaw additionally has no `src/` at HEAD any more (the contents
call for `src` returned 404); its tree is now `crates/{app,contracts,domains,events,extensions,kernel,lanes,
loop,product,substrates}`, so fixes from before the "reborn" restructure reference paths that a documentation
snapshot at HEAD will not contain.

**Recommended construction, for the operator to decide: choose the module first, then filter the issues to
those whose fix PR changes at least one non-test file in it.** For Warp's `app/src/terminal`, a rough size
for that pool: 89 issues carry `area:terminal-input` or `area:shell-terminal` among the 230 `bug` + `triaged`
+ linked issues at the Jan 2026 line (query: `... label:"area:terminal-input","area:shell-terminal"`), and
30% of 230 is about 70. Area labels are an imperfect proxy: of the five `area:agent` issues in the sample,
only one was fixed in `app/src/ai`. The exact pool needs one `pulls/N/files` call per candidate PR.

## 6. Question 5: confounds

- **Bot-written diagnoses in the thread (Warp).** `warp-for-oss[bot]` posts a triage comment within minutes
  of most triaged bug reports, naming files, functions and sometimes line numbers (rows 2, 5, 6, 7, 8, 9
  of the Warp table). A reader that sees the thread is handed the localisation. The reader must see the issue
  title and body only (and the body can leak too: rows 10 and 11 state the cause). "What the maintainers
  found" is often one model's output; the human diagnoses are rows 1, 3 and 9. The bot also labels issues
  `ready-to-implement` and triggers an agent that opens the fix PR (timeline of #16277: a maintainer comments
  asking `@oz-agent` to implement a fix, and ten seconds later the bot opens draft PR #16294, an agent-written
  PR).
- **Agent-written fix PRs.** Many Warp fixes are authored by `warp-agent-staging[bot]` (label
  `factory:wilson`), and OpenClaw's and IronClaw's streams are heavily bot-authored too (`roboclaw-bot`,
  `clawsweeper`, `ironloopai[bot]`). Changed-file ground truth is then what an agent chose, including
  minimal or indirect fixes such as the flag promotion in #15870.
- **Issue bodies that already contain the answer.** Buzz (all five examples), IronClaw (#6896), OpenClaw
  (#144325, #148974) and Warp rows 10 and 11. For these, "localise from the report" tests nothing. A body
  screen (does it contain a path or a function name that appears in the fix diff?) is needed before
  selection.
- **Same-moment issue and PR (OpenClaw, IronClaw).** OpenClaw maintainers file the issue 30 minutes before
  the PR (#144380) or a bot files and closes it within the hour (#144471); 90 merged PRs with linked issues
  landed on 2026-09-10 alone. These issues are PR descriptions in disguise.
- **Repository-resident documentation.** Warp has `specs/` (162+ per-feature directories named by ticket),
  `AGENTS.md` and `.claude/`; IronClaw has `AGENTS.md`, `CLAUDE.md`, `FEATURE_PARITY.md`, `COVERAGE_PLAN.md`,
  `.codebase-memory/` and `openwiki/`; Buzz has `ARCHITECTURE.md`, `CONTEXT.md`, `VISION*.md`, `PLANS/` and
  `AGENTS.md`. Those are authored documentation a grep arm can read and that Claude Code loads on its own
  (existing note, section 5.4). Hold them equal across arms or remove them. IronClaw's `.codebase-memory/`
  deserves a look: it may be a prior code-knowledge store.
- **Issue-tracker history older than the code (Warp).** `warpdotdev/warp` was created in 2021 and its issue
  tracker is older than its code; the code first appeared 2026-04-28. Issue text from before the cutoff can
  be in training data (condition (a) removes it), but no source code was public before 2026-04-28. The import
  commit and nine others carry a "Repo-Sync-Origin" trailer (existing note), so a few commits are squashed
  syncs.
- **Snapshot drift.** Warp merged 117 PRs with linked issues in May 2026, 64 in June, 29 in August, and 24
  between 1 September and 15 October; OpenClaw merged 90 in one day (2026-09-10); IronClaw restructured its
  tree. Documentation generated at one HEAD describes the repository as of that day; a fix from two months
  earlier changed files whose paths or contents have since moved. Constrain selection to PRs merged within a
  short window after the documented snapshot, or document the PR's parent commit.
- **Forks and mirrors.** Mirror and fork bots appear in IronClaw's event log (`pull[bot]`,
  `personal-upstream-sync[bot]` referencing the fix commit), and OpenClaw had 47,700 forks by March 2026 [13].
  All postdate the fixes; none predates the cutoff because none of the repositories existed. No pre-cutoff
  public copy of any candidate's code was found. Not checked: whether Buzz embeds earlier open-source work
  (its `patches/` holds two `.patch` files for npm dependencies, not vendored sources, and its README claims
  no earlier project).
- **Vendored or generated code.** Warp's 93 crates are first-party by name; `warp_graphql_schema` and
  `command-signatures-v2/js` may hold generated data (not opened), and PR #12798 bumps an external
  `warp-command-signatures` crate. OpenClaw's 425 MB of TypeScript, flagged in the existing note, remains
  unchecked for generated catalogues. Macro has `vendor/ironcalc` (519 `.rs`/`.ts`/`.tsx` files, existing
  note).
- **The existing note's Opus 4.6 conclusion carries over unchanged for the Aug 2025 line**, since that is
  Opus 4.6's training-data cutoff; the new work is the Jan 2026 and Jun 2026 lines and the issue counts.

## 7. Recommendation

1. **Pin models by full id**, never by alias (`claude-sonnet-5`, `claude-sonnet-4-6`,
   `claude-opus-4-5-20251101`, `claude-opus-4-6`). On the Anthropic API the aliases are Sonnet 5.5 and
   Opus 5.5, which fail every candidate.
2. **Choose the cutoff line from the model pair**: Opus 4.5 + Opus 4.6 only (Aug 2025): any of the five;
   anything involving Sonnet 4.6 or Sonnet 5 (Jan 2026): Warp, Buzz, IronClaw (marginal). A pair including
   Sonnet 5.5 has no clean repository.
3. **Warp is the default pick** for the Jan 2026 line and good for the Aug 2025 line: consistent triage
   labels (`bug`, `triaged`, `repro:*`, `area:*`), 351 / 230 qualifying issues at Jan 2026, 2.9 months of
   margin, small fix PRs (median 2 files, range 1 to 8 in the sample), and a merged fix PR for each of the 10
   newest linked issues. Costs: bot diagnoses in threads, agent-authored fixes, scattered fix locations.
4. **If the Opus 4.5 retirement floor (2026-11-24) is a concern**, plan runs on Opus 4.6 (floor
   2027-02-05) or Sonnet 4.6 (2027-02-17) and treat Opus 4.5 as a variant to finish first.
5. **Do a body screen and a diagnosis screen before fixing the set**: drop issues whose body names a file in
   the fix diff, and decide whether the reader's input excludes all comments.
6. **Tell the operator about the Sonnet 4.6 cutoff conflict**, since it decides whether Sonnet 4.6 is a
   Jan 2026 model (Warp, Buzz, IronClaw only) or an Aug 2025 one (all five).

## 8. Gaps and the commands that close them

1. **Exact file counts** (no shell here). With a treeless clone:
   `git clone -q --depth 1 --filter=blob:none --no-checkout https://github.com/warpdotdev/warp.git W` then
   `git -C W ls-tree -r HEAD --name-only | grep -E '^app/src/terminal/' | grep -E '\.rs$' | grep -vE '(_tests?|/tests?)\.rs$' | wc -l`
   (and the same for `app/src/workspace`, `app/src/ai`, and a `ref_tests` exclusion for terminal).
2. **Exact condition (c) and the module filter.** For each closed `bug` + `triaged` + `linked:pr` Warp issue
   (paginate `search/issues`, 100 per page; 230 rows), take the PR that closed it from the issue's
   `timeline` (`closed` event, `commit_id`) or `commits/{sha}/pulls`, require `merged_at`, list
   `pulls/N/files`, and keep those with a non-test file under the chosen module. A `gh api` loop does it in
   minutes; WebFetch made this a call-per-PR job, which is why the sample here is 20.
3. **Body screen**: for each kept issue, extract path-like and identifier tokens from the body and drop the
   issue if any appears in the fix diff.
4. **Sonnet 4.6's cutoff**: ask Anthropic, or read the Sonnet 4.6 system card
   (`https://www.anthropic.com/claude-sonnet-4-6-system-card`, not fetched); the three public statements
   disagree.
5. **A new repository for Sonnet 5.5**, if wanted: first public after 2026-06-30 with at least a few
   hundred closed, triaged, PR-linked issues. None is in view.
6. **The first-tool-call screen** from the existing note, run on Warp, is still the check that catches
   layout familiarity no date can.

## 9. Method, queries, evidence quality

**Method.** Anthropic pages and the Claude Code configuration page were fetched in full with WebFetch.
GitHub data were read from `api.github.com` through WebFetch (no authentication, no shell). Endpoints used:
`repos/{r}`, `repos/{r}/labels`, `repos/{r}/contents/{path}`, `repos/{r}/commits?until=`,
`repos/{r}/git/trees/{sha}?recursive=1`, `repos/{r}/issues/{n}`, `.../comments`, `.../events`, `.../timeline`,
`repos/{r}/pulls/{n}/files`, and `search/issues` with the qualifiers `is:issue`, `is:pr`, `is:closed`,
`is:merged`, `linked:pr`, `linked:issue`, `label:`, `created:`, `merged:`, `comments:>=`, `in:body`.
Web searches: "Claude Sonnet 5.5 training data cutoff reliable knowledge cutoff"; "Clawdbot renamed Moltbot
OpenClaw January 2026 history Peter Steinberger GitHub repository"; plus the Wikipedia article on OpenClaw.
Two fetches returned 403 (rate limits on the unauthenticated search API) and were repeated after a pause.

**Evidence quality.**

- Anthropic cutoffs, ids, release dates and retirement floors are first-party documentation, read on
  2026-10-16; the conflicts among the three Anthropic sources are reported in section 2.3.
- Search `total_count` values are the API's, but WebFetch relays them through a summariser; each count was a
  single-number request (`per_page=1`) to keep that risk small. `linked:pr` is an upper bound for condition
  (c). The "10 of 10" confirmation is an issue-side sample of the newest closed linked issues; older
  periods were not sampled on the issue side.
- File counts for directories are estimates (sections 5.2, 8). Counts of changed files per PR are the
  summariser's reading of `pulls/N/files` (short lists, so low risk).
- The location tally rests on n = 20 non-random PRs from four time windows; its intervals are wide.
- Thread-diagnosis judgements (who wrote it, whether it names files) are the summariser's reading of the
  comments; I did not read comment bodies in full.
- Macro's root-commit date was not reproduced (section 3).

## 10. Open questions and leads

- Does the pilot's memorisation screen (first-tool-call on grep) on Warp show no layout familiarity at the
  Jan 2026 line? Not run.
- Is `warp-for-oss[bot]`'s diagnosis any good? It could be scored as a third arm (an LLM with the issue and
  the repository, no knowledge base), which the thread already provides for free.
- How many Warp bug issues remain after the body screen and the module filter? Unknown until section 8.2.
- What is `.codebase-memory/` in IronClaw? If it is a code-knowledge store it is a close relative of what is
  being evaluated.
- Whether Anthropic will publish a Sonnet 4.6 system-card cutoff statement that resolves section 2.3.

## 11. Open issues at HEAD: the pilot's population

Added 2026-10-16 by memory-researcher, read with an authenticated `gh` on that day, so these counts
are the API's own rather than a summarizer's. **The operator chose to pilot on open issues**
(2026-10-16): an issue opened yesterday is triaged today against a fresh pull, so the documents of
the clone's HEAD (`b80b4e3e0`, 2026-10-16) serve every one of them, and no model can have seen a
fix that does not exist yet.

| Count | `search/issues`, `repo:warpdotdev/warp is:issue` plus |
|---|---|
| 1,883 | `is:open label:bug` |
| 452 | `is:open label:bug label:area:shell-terminal` |
| 450 | the same with `label:triaged`, which nearly every issue carries, so it filters nothing |
| 155 | `is:open label:bug label:area:terminal-input` |
| 26 | `is:open label:bug label:area:shell-terminal created:>=2026-09-16` |
| 58 | `is:open label:bug label:area:shell-terminal linked:pr` |
| 5 | `is:closed label:bug label:area:shell-terminal closed:>=2026-09-16 reason:completed`, 2 of them `linked:pr` |

The 58 linked issues carry 78 PRs (GraphQL `closedByPullRequestsReferences` with
`includeClosedPrs: true`): 46 closed unmerged and 32 open, on 29 issues, and none merged, since
the issues are open. **19 of the 32 touch a file under `app/src/terminal/`** (tests in that tree
included); 10 of those are by Warp's agents (`warp-for-oss[bot]`, `warp-agent-staging[bot]`),
mostly drafts, and 9 by people, on 8 issues:

| PR | Issue | Files | Under `app/src/terminal/` | Draft | Review |
|---|---|---|---|---|---|
| 16187 | 15666 | 2 | 2 | no | approved |
| 16190 | 15666 | 4 | 4 | no | required |
| 16462 | 14231 | 8 | 7 | no | required |
| 16358 | 10355 | 8 | 3 | yes | required |
| 15647 | 15646 | 11 | 2 | yes | required |
| 14124 | 8357 | 6 | 3 | no | required |
| 13170 | 9056 | 4 | 3 | no | required |
| 13041 | 9013 | 2 | 2 | no | required |
| 10729 | 10144 | 2 | 2 | no | required |

**What this means for the pilot.** An open PR is a proposed fix, not ground truth. Scoring against
an agent's PR measures agreement with Warp's agent rather than correctness, so a person's open PR
is the better proxy, and 8 issues is pilot-sized: enough to see whether and how the reader uses
the documents, not an effect size. Waiting for fixes to merge, at about two a month in this area by
the last row, cannot build a sample. So the pilot scores open issues against person-written PRs,
re-scoring any whose fix merges; run over every area rather than this one, the same predicate
selects 16 issues, and `research/m40-evaluation.md` §1 lists them. **The scored stage after the pilot uses
hand-picked closed issues, each at the commit its fix merged onto, with the code knowledge rebuilt
there** (operator, 2026-10-16), and that rebuild is itself a measurement of the planner's
incremental cost.

**Warp's bot is a third comparator** (operator, 2026-10-16). `warp-for-oss[bot]`, signed *"Powered
by Oz"*, posted a diagnosis on the day the issue opened on 5 of the 8 (15666, 14231, 10355, 15646,
10144; 2,000–3,700 characters each), none on 9056 or 9013, and a 401-character note seven months
late on 8357. On 15666 it names five files and the functions in them, and cites an open PR as
addressing the issue, so it reads the PR list. It differs from both arms in model, harness and
tools, and saw the code of its own day, so a treatment-against-bot difference is not the
documents' effect; treatment against control is, and the bot places the control.

Re-derive the PR rows (`$n` loops over the 58 issue numbers from the `linked:pr` search):
`gh api graphql -f query="{repository(owner:\"warpdotdev\",name:\"warp\"){issue(number:$n){closedByPullRequestsReferences(first:5,includeClosedPrs:true){nodes{number state changedFiles files(first:100){nodes{path}}}}}}}"`,
then `gh pr view <pr> -R warpdotdev/warp --json author,isDraft,reviewDecision` for each open one.

## Sources

Anthropic and Claude Code (all read 2026-10-16)

1. Models overview: https://platform.claude.com/docs/en/about-claude/models/overview (redirects from docs.anthropic.com; also reachable as .../en/models/overview)
2. Claude Opus 4.5 model page: https://platform.claude.com/docs/en/models/opus-4-5/overview
3. Claude Opus 4.6 model page: https://platform.claude.com/docs/en/models/opus-4-6/overview
4. Claude Sonnet 4.6 model page: https://platform.claude.com/docs/en/models/sonnet-4-6/overview
5. Claude Sonnet 5 model page: https://platform.claude.com/docs/en/models/sonnet-5/overview
6. Claude Sonnet 5.5 model page: https://platform.claude.com/docs/en/models/sonnet-5-5/overview
7. Model deprecations: https://platform.claude.com/docs/en/about-claude/model-deprecations
8. Transparency Hub model report: https://www.anthropic.com/transparency/model-report
9. How up to date is Claude's training data: https://support.claude.com/en/articles/8114494-how-up-to-date-is-claude-s-training-data
10. Claude Code model configuration: https://code.claude.com/docs/en/model-config

Repositories and lineage

11. Macro: https://github.com/macro-inc/macro ; https://api.github.com/repos/macro-inc/macro ; first commit date from `research/m40-eval-repository-candidates.md` [21]
12. OpenClaw: https://api.github.com/repos/openclaw/openclaw/commits?per_page=3&until=2025-11-25T23:59:59Z
13. OpenClaw (Wikipedia, names and dates; 247,000 stars and 47,700 forks by 2026-03-02): https://en.wikipedia.org/wiki/OpenClaw ; search result also quoted a viral launch around 2026-01-25
14. IronClaw: https://api.github.com/repos/nearai/ironclaw ; https://api.github.com/repos/nearai/ironclaw/commits?per_page=5&until=2026-02-03T23:59:59Z
15. Buzz: https://api.github.com/repos/block/buzz/commits?per_page=5&until=2026-03-07T23:59:59Z ; https://github.com/block/buzz
16. Warp: https://api.github.com/repos/warpdotdev/warp/commits?per_page=4&until=2026-04-28T14:30:00Z

Search and PR/issue examples (API URLs; the repository in each is Warp unless named)

17. Issue search, Warp: https://api.github.com/search/issues?q=repo%3Awarpdotdev%2Fwarp+is%3Aissue+is%3Aclosed+linked%3Apr+created%3A%3E2026-01-31 (and the variants listed in section 4.1)
18. PR search, Warp: https://api.github.com/search/issues?q=repo%3Awarpdotdev%2Fwarp+is%3Apr+is%3Amerged+linked%3Aissue+merged%3A2026-09-01..2026-09-20 (also 2026-09-21..2026-10-15, 2026-08-01..2026-08-31, 2026-06-01..2026-06-30, 2026-05-01..2026-05-31)
19. Warp labels: https://api.github.com/repos/warpdotdev/warp/labels?per_page=100 ; Buzz, IronClaw, OpenClaw, Macro: same path under each repository
20. Warp PR files: https://api.github.com/repos/warpdotdev/warp/pulls/{16294,16124,16102,16093,16055,15870,15792,15763,15720,15642,15310,15118,14895,13080,13017,12889,12965,11766,11673,11611,11412,11242}/files
21. `research/m40-eval-repository-candidates.md` (existing note; first-public dates, file counts, per-candidate background)
22. Warp issue records and threads: https://api.github.com/repos/warpdotdev/warp/issues/{16277 (also /timeline),16121,16067,16043,16019,15821,15753,15718,15410,15309,14241,13073,12990,12817,11679,11138,11016,7099}
23. Warp tree listings: https://api.github.com/repos/warpdotdev/warp/git/trees/{25d411d681dddfe33e346d589d231738e33e529d (app/src/terminal), 428ace70959c801373a3027ac1dc6a9db0d46cc8 (app/src/workspace), fbc489a3beaaba344d7448eb7dbc968bdd74a4f7 (app/src/ai)}?recursive=1 ; https://api.github.com/repos/warpdotdev/warp/contents/app/src ; .../contents/crates
24. Buzz examples: https://api.github.com/repos/block/buzz/pulls/{7203,7279,8124,7998,7216}/files ; https://api.github.com/repos/block/buzz/issues/{6218,5313,8122,7927,5450,7914}
25. IronClaw examples: https://api.github.com/repos/nearai/ironclaw/pulls/{7109,7205,7131}/files ; issues 6896, 6898 (comments and events); body-search PR lookups for 6896, 6898, 7204, 7209
26. OpenClaw examples: https://api.github.com/repos/openclaw/openclaw/pulls/{144377,144367,144381,144498,148995}/files ; issues 144148, 144325, 144380, 144471, 148974 (comments)
27. Repository search for repositories created after 2026-06-30: https://api.github.com/search/repositories?q=created%3A%3E2026-06-30+size%3A%3E200000+stars%3A%3E300+fork%3Afalse&sort=stars&order=desc
