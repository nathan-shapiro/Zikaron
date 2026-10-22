# M40's evaluation: issue triage on Warp

memory-researcher with the operator, from 2026-10-16. **The protocol is `design/code-knowledge.md`
§7**, normative, prompts included; this note holds what the protocol selected and, as the runs
happen, what they measured. The screening of repositories and models behind it is
`research/m40-eval-sonnet5-issue-sets.md`, whose §11 counts the open issues of the area first
considered.

## 1. The issues

Selected 2026-10-16 against the clone's HEAD, `b80b4e3e0`, by §7's predicate: open, labeled `bug`,
linked as closed by an open PR written by a person that changes a file under `app/src/terminal/`.
**Frozen in `experiments/m40_eval_issues.json`** — bodies, PR heads, the strata's flags and the
bot's comment — **with each truth PR's diff at its recorded head in `experiments/m40_eval_diffs/`**,
since an open issue's body and an open PR's diff both move.

The predicate was first run over the 452 open `bug` issues labeled `area:shell-terminal`, which
gave 8; run over all 245 open `bug` issues with a linked PR, whatever their area, it gives 16. Those
245 carry 147 links to open PRs; §7 excludes the ones by Warp's agents, and closed unmerged PRs
never count. Re-derive: page `search/issues` with `q=repo:warpdotdev/warp is:issue is:open
label:bug linked:pr`, then for each issue read GraphQL's
`issue.closedByPullRequestsReferences(first:10, includeClosedPrs:true)` for each PR's `state`,
`author`, `isCrossRepository` and `files`.

The truth follows §7's exclusion rule and is mapped to HEAD. **Two kinds of path did not stand at
HEAD.** PR 13041 (for 8881 and 9013) changes `app/src/terminal/model/grid/resize.rs`, which commit
`21f413b79` (2026-08-25, *"Move a lot of terminal grid code to the `warp_terminal` crate"*) renamed
to `crates/warp_terminal/src/model/grid/resize.rs` — outside the module, so neither issue has a
documented truth file. PR 16358 (for 10355) adds `grid_renderer/rtl.rs`, which `master` never
held, so it stays in the judge's diff and leaves the mechanical truth. The exclusion's
test-registration clause takes `crates/integration/src/bin/integration.rs` out of 12425's truth,
since its whole change is one `register_test!` line.

| Issue | Opened | Truth files | Under the module | Documented | Reported apart | Bot's first five files: first truth file at | Specs naming a truth file |
|---|---|---|---|---|---|---|---|
| 3265 | 2023-06-27 | 1 | 1 | 1 | pre-cutoff | no diagnosis | 54 |
| 3970 | 2023-12-15 | 2 | 2 | 2 | pre-cutoff, agent-written | no diagnosis | 54 |
| 8357 | 2026-01-02 | 4 | 2 | 2 | | no diagnosis | 2 |
| 8881 | 2026-03-15 | 1 | 0 | 0 | located by symbol, undocumented | no diagnosis | 0 |
| 9013 | 2026-04-04 | 1 | 0 | 0 | located by symbol, undocumented | no diagnosis | 0 |
| 9056 | 2026-04-13 | 2 | 2 | 2 | | no diagnosis | 15 |
| 9145 | 2026-04-21 | 4 | 3 | 3 | | no diagnosis | 4 |
| 10144 | 2026-05-05 | 1 | 1 | 1 | | 4th of 4 | 10 |
| 10355 | 2026-05-07 | 3 | 1 | 1 | | 2nd of 5 | 23 |
| 11262 | 2026-05-19 | 1 | 1 | 1 | located, agent-written | 4th of 4 | 0 |
| 12425 | 2026-06-09 | 2 | 2 | 2 | | 1st of 5 | 2 |
| 14231 | 2026-07-24 | 5 | 4 | 4 | located | 1st of 2 | 1 |
| 14234 | 2026-07-24 | 6 | 6 | 6 | | 1st of 5 | 81 |
| 15590 | 2026-08-27 | 2 | 1 | 1 | | 4th of 5 | 57 |
| 15646 | 2026-08-28 | 9 | 2 | 2 | located | 1st of 3 | 4 |
| 15666 | 2026-08-29 | 2 | 2 | 2 | located | 1st of 4, and cites PR 15665 | 12 |

**Eight issues are in no reported-apart kind**: 8357, 9056, 9145, 10144, 10355, 12425, 14234 and
15590. **`app/src/terminal/view.rs` is documented in part**: a truth file of 3265, 3970, 14234 and
15590 — the only one of 3265's and of 15590's under the module — it was over the default size cap
and has a document only because the clone raises the cap to 5 MiB, and at 30,181 lines it is past
the documenter's context window, so its Sonnet 4.6 document listed 136 functions of about 750, and
its role line said so: *"This document describes the file in part (lines 1–3200, 27463–27463,
28982–29590 read in full; remaining method bodies located by search)"* (`research/m40-toy-run.md`
§8). The regenerated document the runs searched lists 208, read 942 lines in full and indexes
declarations through line 10,039, and says so in its role line (that note's §17). **The specs count is broad for a central file**: `view.rs`
alone is named in 54 spec files, while the mechanism-level overlap is narrower — five spec
directories describe 15666's agent-support gate, one 14231's ordering assumption.

**The bot's files follow §7's one rule** for what names a file and its rename mapping: on 11262 its
second path-like token, `templatable_mcp_server.template.json`, is a field chain in its prose and is
skipped; on 10355 its first, `app/src/terminal/model/grid/ansi_handler.rs`, maps through
`21f413b79` to `crates/warp_terminal/src/model/grid/ansi_handler.rs`, which is not a truth file.
On 8357 and 9145 its only comment is the `announce-ready-issue` notice, so both read *no
diagnosis*.

**Agent-written** is the trailer rule of §7: PRs 16440 and 11457 end *"🤖 Generated with [Claude
Code]"*. PR 13079 (for 12425) links evidence from a branch named `codex-pr-12425-evidence` and
carries no trailer, so the rule does not mark it.

**Correlated pairs**: 8881 and 9013 report one crash and share PR 13041, so they share a truth.
**Feature-shaped**: 10355 asks for right-to-left text support, so its "cause" is where the support
would go, and its PR adds a module and a feature flag.

## 2. What the bot's diagnoses already say

The bot's half of the file-level comparison is static, so it is computed here once. **On every one
of the 9 issues it diagnosed, a truth file is among the first five it names**, and the first it
names is a truth file on 5 of them. That bar is high, and it is an upper bound (§7): every one of
those 9 issues' person-written PRs was opened after the bot's comment, from 41 minutes to five
months later, so a contributor may have fixed where the bot pointed. On 15666 it also cites an open
PR as addressing the issue, which it can read and the reader cannot.

## 3. Decisions taken in settling the protocol

Recorded once here; §7 states the result.
- **Widening the predicate to every area** doubled the set at no cost to cleanliness, since the
  module test is on the PR's files, not the issue's label.
- **No unscored issues**: sixteen scored issues already give the triage to read.
- **The copies are cut off from GitHub's history**: the clone carries 2,182 remote branches, the
  branches of same-repository PRs among them (PR 12957, for 9145, is one), and its `origin` is a
  blobless partial clone's promisor (`remote.origin.partialclonefilter blob:none`), which would
  fetch from GitHub on any `git log -p`. So `HEAD`'s history is fetched whole, by its sha and
  with no tags (by `master` if the server refuses a sha), before `origin` is removed — 2,556 commits; GitHub reports the repository at about
  372 MB — and every ref but `master` goes, tags included, since the clone holds 61 tags and a
  new one on `master` would carry commits past the documented one.
- **`--strict-mcp-config`**: Warp's tracked `.mcp.json` declares `@modelcontextprotocol/server-github`.
- **`Skill` denied**: Warp's `changelog-draft` skill runs `fetch_issue_reporters.py`, which calls
  `gh`.
- **No `--max-turns`**: this Claude Code's `--help` lists none, so a run's ceilings are
  `--max-budget-usd` and a wall-clock timeout.
- **The judge is a model, not the operator**, who does not know Warp's code; it is pinned to a model
  other than the reader's, so its preference for its own phrasing, if any, does not favor one arm.
- **The reader at `--effort high`**, which Claude Code's `--effort` flag sets per session.
- **The reader's tools are an allowlist, measured** (2026-10-17, Claude Code 2.1.292, `haiku`
  on a one-word prompt). A session otherwise carries 56 tools — among them `Task` (the spawn
  tool, under that name), `Workflow`, `EnterWorktree`, `RemoteTrigger`, the cron tools and the
  account's `claude.ai Claude Docs` connector. `--tools Bash,Read,Grep,Glob` with
  `--strict-mcp-config` and an empty `--mcp-config` left `['Bash', 'Glob', 'Grep', 'Read']` and
  no server; with the copy's `zikaron` entry as the config and the seven writing verbs in
  `--disallowedTools`, run in the clone, it left those four and
  `mcp__zikaron__zikaron_knowledge_list`, `…_knowledge_search`, `…_knowledge_status`,
  `…_memory_fetch`, `…_memory_search`, the server `connected`; and `--tools ""` left `[]`, the
  judge's set.
- **Both prompts name the module**: every issue is selected by a fix under `app/src/terminal/`, so
  a pointer there in the treatment alone would be a hint about where the truth is.
- **`specs/` kept in both trees** rather than removed: it is the tree Warp's contributors and its
  bot work in, and the bot is a comparator; what that costs is that the control is the code plus
  Warp's specs, so the note counts each arm's reads of them.
- **The copies live at `<root>/a/warp` and `<root>/b/warp`**, the letters assigned by the seed:
  Claude Code's system prompt shows the working directory, and `ls ..` beside the clone
  (`~/Zikaron-m40/warp`, which keeps the documents) or the toy run's transcripts would hand the
  control the documents.
- **The skills both arms see are project-level**: the clone's `.claude/skills` is a symlink to
  `.agents/skills`, which holds Warp's 21 skills and Zikaron's two. Outside the tree, two things
  load into every run of both arms and the judge, and there is no `~/.claude/CLAUDE.md`: the
  user's `~/.claude/settings.json` (1,148 bytes), which sets `outputStyle: "Concise"`,
  `effortLevel: "xhigh"` (with `claude-opus-5-5` at `xhigh` under `modelSettings`, which the
  judge's `--effort high` overrides), `alwaysThinkingEnabled: true`, an `env` turning on the todo
  tools, and `permissions`; and the thirteen user-level skills in `~/.claude/skills/synced/` —
  `built-in-browser`, `chrome-browser`, `computer-use`, `deep-research`, `docs`, `docx`,
  `import-memory`, `morning`, `pdf`, `pptx`, `setup-writing-style`, `skill-creator`, `xlsx` — which
  the `Skill` deny keeps from being invoked. The specs column counts `specs/` and `.agents/specs/`
  both.
- **Issues whose truth left the module or has no document are kept and reported apart**
  (*undocumented*) rather than dropped: they are where the documents can help only by pointing
  past themselves, which is worth seeing.

## 4. Runs

**Prepared 2026-10-17** with seed `20261017`, which made `b` the treatment and `a` the control,
on Zikaron `06deae8` and Claude Code 2.1.292; `<base>/eval/state.json` keeps both and each copy's
baseline. **The cut-off needed one step §7 did not first name**: the blobless clone's pack carries
a `.promisor` marker, and `gc` keeps every object of a marked pack whatever the config says, so
the first `prepare` refused with PR 12957's head still in the treatment's object store — the
same-repository branch §3 names — and with the
markers deleted before `gc`, one pack remains, every PR head is gone, no object is missing, and
`HEAD` reaches 2,556 commits.

**The probe passed on its first attempt** (`probe-0-0`): the `init` tool set was the allowlist's
nine, the `zikaron` server `connected`, and all eighteen `Bash` rules refused natively under
`bypassPermissions` — each `tool_result` *"Permission to use Bash with command … has been
denied."* with `is_error`, and each listed in the result's `permission_denials` — so the fallback
hook is not installed. The reader issued the eighteen calls in one message: 15 s, $0.25. **The
result's `usage` is the run's sum** — it matched the two assistant messages' input fields — while
a stream-json message's `output_tokens` is its count when streaming began (12 against the
result's 1,375), so a capped run's output tokens, summed from its messages, are a lower bound.

**The slice's readers restyled the reply's block, and the parse rule was widened for it.** Both of
14234's replies bolded the labels (`**FILES:**`, `**CONFIDENCE:** high`), and 15590's treatment
reply put each under a heading with no colon (`## FILES`) and listed nine files in a Markdown
table; under the rule as first written, all three scored as naming none. §7 now reads a label in
those forms and an item as a numbered or bulleted line or a table row, the first five scored, and
`experiments/m40_eval.py reanalyze` rebuilt every run's record from its transcript under it, so no
run is scored under a different rule from another.

### The slice

2026-10-17, repeat 1 of the order's first four issues — the order is
`14234, 15590, 8881, 15666, 15646, 9145, 10144, 11262, 9013, 9056, 3970, 10355, 14231, 3265, 8357,
12425`, drawn with `order-20261017` — at one hour and $15 a run, both arms at once per issue.
Tokens are the four `usage` fields summed, almost all of it `cache_read_input_tokens`; the grade
is the judge's.

| Issue | Arm | First is truth | Rank | Grade | Confidence | Tokens | Output | Wall-clock | Cost | Turns | Searches |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 14234 | treatment | yes | 1 | partly | high | 11,835,706 | 52,948 | 1,307 s | $9.21 | 137 | 5 |
| 14234 | control | no | 2 | partly | medium | 14,084,857 | 42,987 | 1,087 s | $10.06 | 151 | — |
| 15590 | treatment | yes | 1 | partly | medium | 17,020,511 | 73,936 | 1,629 s | $12.99 | 207 | 3 |
| 15590 | control | yes | 1 | partly | medium | 12,106,273 | 38,768 | 745 s | $8.43 | 126 | — |
| 8881 | treatment | yes | 1 | partly | medium | 7,537,261 | 82,169 | 1,565 s | $7.11 | 97 | 3 |
| 8881 | control | yes | 1 | correct | high | 550,915 | 13,229 | 247 s | $0.94 | 21 | — |
| 15666 | treatment | yes | 1 | correct | high | 72,553 | 1,335 | 30 s | $0.22 | 4 | 2 |
| 15666 | control | yes | 1 | correct | high | 117,063 | 1,375 | 27 s | $0.23 | 7 | — |

**The judge** (`claude-opus-5-5` at `--effort high`, 49 calls, $5.02, none failed) **graded its
calibration controls without a miss**: all 16 truth-PR descriptions `correct`, all 16 unrelated
ones `wrong`. Over the nine issues the bot diagnosed it graded the bot `correct` on six and
`partly` on three, a truth file among the bot's first five on all nine (§2).

**Eight runs, $49.19, no discard, no cap, no refused command.** Three of the four treatment runs
also called `memory_search`, once or twice, over its empty store; no run read a document file
directly or named one in a shell command; and three results of one run, 15590's treatment, showed
a path under `specs/`. Of the treatment's 80 search results, 4 were chunks of the module README,
3 of them lines of its `## Files` list, each repeating a file's role line under `README.md`. The
judge graded the treatment `correct` once and the control twice, every
other run `partly`. Four readings, none of them a result at n=1:
on **14234** the treatment put a truth file first and four in its five, the control one at rank 2
and three; on **8881**, whose truth left the module and has no document, both found it first, the
treatment at 7.6× the dollars and 6.3× the time; **15666**, *located*, took both arms half a
minute; and **15590** cost the treatment half again the control's dollars for the same rank.

**The ceilings, set from the slice by §7's rule**: `--max-budget-usd 39` — three times 15590's
treatment run, $12.99 — and a timeout of 4,887 s, three times its 1,629 s.

**What the repeats would cost.** At the slice's mean of $6.15 a run, the 88 runs left — repeat
1's twelve other issues and two full repeats, both arms — come to about $540, and at its mean of
about 19 minutes an issue, both arms at once, about 14 hours; the ceilings bound one run at $39 and
81 minutes.

### Re-prepared on the M40-5 build, over the regenerated documents

**The slice's runs are the record of the M40 commit's build alone**, in
`~/Zikaron-m40-archive/eval-06deae8`: the branch then moved `zikaron/`, and the documents were
written again by Haiku 5.5 under Opus 5.5 (`research/m40-toy-run.md` §17), so every cell is run
again. **Prepared 2026-10-21** with the same seed, `b` again the treatment, on Zikaron's M40-5
commit and Claude Code 2.1.306, the binary pinned in
`state.json` by its resolved path and recorded in every run and grade. The probe passed on its
first attempt, all eighteen `Bash` rules refused natively.

**The dry run, 15666, both arms**, kept as its first repeat: each named
`cli_agent_sessions/listener/mod.rs` first, `view.rs` and `cli_agent.rs` after it, at high
confidence, graded `correct` — treatment 32.8 s, $0.29, 157,947 tokens, two knowledge searches
before any `Grep`; control 36.2 s, $0.28, 146,527 tokens. No discard, cap or refused command. The
judge graded its two controls as expected and the bot `correct`, five calls, $0.54. **M40-4's
search reminder fired for neither**: the control has no documented module, and in the treatment
the reader's own searches count as its reminder for `knowledge_reminder_interval`, 300 s, so the
five `knowledge_remind` calls after its `Grep`s answered with no line, and no
`hook_additional_context` is in its transcript. A reader that greps the module 300 s after its last
knowledge search is reminded, so a long treatment run can carry one; §7 predates M40-4, and the
copies run the install as it ships.

**The audit discarded a run for reading its own output**: 9145's control `Read` the file Claude
Code saves a tool result too large to return to, under
`~/.claude/projects/<the copy>/<its session>/tool-results/`, which it had been told to read. §7's
rule now excepts the run's own session's `tool-results/` and nothing else under `~/.claude`;
`reanalyze` applied it to every run, and no other run's discards changed. The harness was stopped
between cells, after 10144, and resumed, so no cell was re-run for it.

### Repeat 1

2026-10-21 to 2026-10-22, all sixteen issues once per arm, both arms at once per issue, in the
order, ceilings `--max-budget-usd 39` and 4,887 s. **One discard, replaced**: 3970's control ran
`find /home/nathan/Zikaron-m40 -path "*/urlocator*/src/lib.rs"`, looking for a crate's source,
from `<base>` — nothing matched, but the search reached the treatment's copy and the clone — so
both arms of 3970 ran again at the repeat's end, cleanly. No cap, no refused command but one
`cargo doc` in that same discarded run. Grade is the judge's; *first* is whether the first file
named is a truth file, *rank* the first truth file's; searches are `zikaron_knowledge_search`
calls, reminders the M40-4 lines that reached the reader.

| Issue | Kind | Treatment: first, rank, grade, confidence | Cost, time | Searches, reminders | Control: first, rank, grade, confidence | Cost, time | Bot |
|---|---|---|---|---|---|---|---|
| 14234 | | yes, 1, correct, medium | $13.86, 1,749 s | 8, 4 | yes, 1, correct, medium | $17.04, 1,952 s | partly |
| 15590 | | no, 2, partly, medium | $9.35, 1,538 s | 2, 3 | no, 2, partly, medium | $13.07, 1,590 s | correct |
| 8881 | undocumented | yes, 1, correct, high | $2.49, 594 s | 2, 0 | yes, 1, correct, medium | $5.67, 1,446 s | — |
| 15666 | located | yes, 1, correct, high | $0.29, 33 s | 2, 0 | yes, 1, correct, high | $0.28, 36 s | correct |
| 15646 | located | yes, 1, correct, high | $0.53, 73 s | 1, 0 | yes, 1, correct, high | $0.50, 69 s | correct |
| 9145 | | no, none, wrong, high | $8.63, 1,234 s | 1, 2 | no, 5, partly, high | $9.14, 1,651 s | — |
| 10144 | | no, 2, correct, medium | $17.05, 2,658 s | 20, 5 | no, 3, wrong, high | $11.56, 1,044 s | partly |
| 11262 | located, agent-written | yes, 1, correct, medium | $7.28, 974 s | 2, 1 | yes, 1, correct, medium | $4.77, 689 s | correct |
| 9013 | undocumented | yes, 1, correct, medium | $12.51, 3,003 s | 3, 2 | yes, 1, partly, medium | $6.79, 1,557 s | — |
| 9056 | | no, none, correct, high | $0.41, 64 s | 2, 0 | no, none, correct, high | $0.39, 54 s | — |
| 3970 | pre-cutoff, agent-written | no, 2, correct, medium | $5.18, 764 s | 3, 2 | no, 2, wrong, high | $1.71, 178 s | — |
| 10355 | | no, 2, correct, high | $0.65, 84 s | 4, 0 | no, 2, correct, high | $0.72, 87 s | correct |
| 14231 | located | yes, 1, partly, high | $0.45, 61 s | 1, 0 | yes, 1, partly, high | $0.25, 30 s | partly |
| 3265 | pre-cutoff | yes, 1, correct, high | $1.58, 185 s | 4, 0 | yes, 1, correct, high | $2.27, 218 s | — |
| 8357 | | yes, 1, correct, high | $0.85, 122 s | 2, 0 | yes, 1, correct, high | $1.04, 175 s | — |
| 12425 | | no, 2, partly, medium | $5.49, 1,129 s | 4, 0 | yes, 1, partly, high | $2.70, 675 s | correct |

**Totals over the kept runs**: the treatment $86.60, 14,264 s and 97.8 M tokens; the control
$77.92, 11,452 s and 93.3 M tokens. **Grades**: treatment 12 correct, 3 partly, 1 wrong; control
9 correct, 5 partly, 2 wrong. **Mechanically**: a truth file first on 9 issues against 10, and
among the five on 14 against 15. **The grades differ on four issues**: the treatment is the
better on 9013, 10144 and 3970, in each at the higher cost, and the control on 9145, `partly`
against `wrong`. **The control called Zikaron's tools over its empty
store** on three issues: a knowledge search on 9145 and 10144, and two memory searches on 10144
and on 14234. **The judge** graded all 32 calibration controls as expected — 16 `correct`, 16
`wrong` — over 73 calls and $7.61, the dry run's included; the bot, on its nine diagnoses, 6
`correct` and 3 `partly`, a truth file among its five on all nine. **What it cost**: $171.02 for
every reader run, the dry run and 3970's discarded pair included, and $7.61 of judge.

**Readings, none of them a result at one run a cell.** The treatment's grade is the higher on
three issues and the lower on one, at 1.11× the dollars and 1.25× the time overall, and its
mechanical score is one issue lower on each measure. On the four issues the slice also ran, the
arms' order of cost reversed between the passes (§"The slice"), the control's alone moving 1.8×
with nothing in it changed, so a cost difference between the arms is not yet separable from a
run's own spread.

### Repeats 2 and 3, and the three together

2026-10-22, back to back, on the same build and the pinned 2.1.306. **One discard, replaced**:
repeat 3's 3970 treatment ran `echo $CARGO_HOME && ls … || echo "No cargo registry found"`, whose
message holds `cargo` as a word — the false discard §7 names, absorbed by the replacement rule —
so both arms of 3970 ran again, cleanly. **The parse was widened once**: both readers of repeat
3's 14234 put the list in a code fence as plain lines, which parsed as naming nothing; §7 now
reads such a list one item a line, and `reanalyze` changed those two records and no other.
**Scoring by the first five entries rather than five distinct files** moves one rank, repeat 1's
10144 control, from 3 to 2, and no first or any.

Grades are the judge's, one letter a repeat (**c**orrect, **p**artly, **w**rong); *files* is per
repeat `1` for a truth file first, `a` for one among the five not first, `0` for none; cost and
time are the median of three, with the cost's range.

| Issue | Treatment grades, files | Cost, median [range] | Time | Control grades, files | Cost, median [range] | Time |
|---|---|---|---|---|---|---|
| 14234 | ccp 11a | $9.03 [7.93–13.86] | 1,214 s | cpp 1a1 | $11.60 [9.28–17.04] | 1,699 s |
| 15590 | ppp aa1 | $9.89 [9.35–12.68] | 1,663 s | ppp aaa | $12.42 [11.19–13.07] | 1,585 s |
| 8881 | ccc 111 | $2.49 [1.34–2.76] | 548 s | ccc 111 | $5.67 [1.60–10.74] | 1,446 s |
| 15666 | ccc 111 | $0.24 [0.22–0.29] | 26 s | ccc 111 | $0.23 [0.19–0.28] | 27 s |
| 15646 | ccc 111 | $0.53 [0.51–0.56] | 70 s | ccc 111 | $0.51 [0.50–0.59] | 77 s |
| 9145 | wwp 0aa | $7.24 [7.13–8.63] | 1,234 s | pww aaa | $6.44 [2.89–9.14] | 1,331 s |
| 10144 | cpc aa1 | $14.86 [13.09–17.05] | 2,297 s | wwp aaa | $11.01 [9.84–11.56] | 939 s |
| 11262 | ccc 111 | $5.62 [5.50–7.28] | 974 s | ccc 111 | $1.23 [1.00–4.77] | 104 s |
| 9013 | ccc 111 | $8.81 [1.70–12.51] | 2,074 s | pcc 111 | $1.09 [0.94–6.79] | 186 s |
| 9056 | ccc 000 | $0.41 [0.37–0.42] | 58 s | ccc 000 | $0.48 [0.39–0.51] | 58 s |
| 3970 | ccc aa1 | $4.37 [3.84–5.18] | 764 s | wpc aa1 | $1.71 [1.45–1.76] | 178 s |
| 10355 | ccc aaa | $0.93 [0.65–0.93] | 87 s | ccc aaa | $0.84 [0.72–0.92] | 87 s |
| 14231 | ppp 111 | $0.45 [0.45–0.47] | 56 s | ppp 111 | $0.25 [0.21–0.31] | 30 s |
| 3265 | ccc 111 | $2.95 [1.58–4.18] | 404 s | ccp 111 | $2.68 [2.27–2.70] | 252 s |
| 8357 | ccc 111 | $1.19 [0.85–1.48] | 190 s | ccc 111 | $1.13 [1.04–1.26] | 136 s |
| 12425 | pww aaa | $5.49 [3.74–6.10] | 1,129 s | pwp 1aa | $4.58 [2.70–5.27] | 1,088 s |

**Over the 48 kept runs an arm**: grades, the treatment 34 correct, 10 partly, 4 wrong, and the
control 27, 15 and 6; a truth file first on 29 runs against 28, and among the five on 44 against
45; $227.11 against $194.82 (1.17×), 38,045 s against 28,653 s (1.33×), 251.8 M tokens against
228.2 M (1.10×). The judge graded all 32 calibration controls as expected, over 137 calls and
$14.20 for the three repeats.

**Per issue**, scoring a grade 2, 1 or 0 and summing the three: the treatment is the higher on
five issues — 10144 by 4, 3970 by 3, and 14234, 9013 and 3265 by 1 — the control on one, 12425 by
1, and ten are equal, among them all five of the cheap located or fast ones. Five against one has
a one-sided sign-test p of 0.11, and a Wilcoxon signed-rank over the six non-zero differences
W− = 2.5, above the one-sided 5% critical value of 2: **a lean toward the treatment on
correctness, not a result at sixteen issues**. Where the treatment grades higher it costs more —
10144, 9013 and 3970 at 1.3× to 8× the control's median — and on 11262, *located*, it spends a
median 974 s to the control's 104 s for the same three `correct`s. **The mechanical score does
not separate the arms**: where they differ, it is in the judge's grade of the mechanism, not in
which file comes first.

**The treatment also reached the documents outside the knowledge tool**, a route §7's counts
missed until `routes()` gained `grep_results_showing_documents` (2026-10-22, applied by
`reanalyze`): a `Grep` with no `path` searches the whole copy, documents included. Over the 48
kept treatment runs, 9 results in 6 runs returned document lines beside code and 13 in 9 runs
listed document files among their matches, 13 runs in all through grep; one more, 3970's first,
read a document directly after a `Glob` (`document_file_tool_calls`), 14 runs by either route. No control run did either, since its copy
holds none.

## 5. The retrieval replay: did the regenerated documents navigate better?

2026-10-22, on the operator's question whether the documenter's changes since the toy run made
better documents (operator, 2026-10-21). **Every knowledge search a treatment reader sent** — 13
from the slice, over the Sonnet 4.6 documents, and 181 from the three repeats, over the
regenerated ones; 194 in all, 186 distinct — **was run again against both corpora**, with its own
`limit_per_kb`: the archived Sonnet 4.6 documents registered in the clone's store as
`replay-sonnet46-terminal` (408 files, 2,463 chunks, all 407 linked), and the regenerated
`code-knowledge/app/src/terminal` (3,216 chunks). One store and one project root, so both link to
the same sources and only the documents differ. A query *hits* when a result's source is a truth
file; its rank is the first such among the distinct sources returned.

| Queries | Corpus | Hit | Truth file first | MRR | Truth files returned |
|---|---|---|---|---|---|
| all 194 | Sonnet 4.6 | 109 | 58 | 0.398 | 140 |
| all 194 | regenerated | 98 | 60 | 0.385 | 126 |
| the slice's 13 | Sonnet 4.6 | 6 | 5 | 0.423 | 9 |
| the slice's 13 | regenerated | 6 | 2 | 0.295 | 10 |
| the repeats' 181 | Sonnet 4.6 | 103 | 53 | 0.396 | 131 |
| the repeats' 181 | regenerated | 92 | 58 | 0.391 | 116 |

**Paired, query by query, the regenerated documents rank a truth file higher on 32 and lower on
41**, the same on 121 — a two-sided sign-test p of about 0.35, with queries clustered by issue
(10144 sent 55, 14234 37), so weaker still. Both return a mean of 4.9 distinct sources a query,
so the longer documents do not crowd the results with one file's chunks. The bias the replay
carries favors the regenerated documents — 181 of the queries were written by readers looking at
them — and they still do not rank better. **So the documenter's changes did not make the
documents better to navigate by**, on these queries: retrieval of a truth file is flat, and the
treatment's lean on grades (§4) is not explained by its finding the right file sooner. **Nor did
the treatment reach a truth file sooner**: over the 48 kept runs an arm, the median run made 4
tool calls before it first read, grepped or named a truth file, in both arms, and 3 runs an arm
never did. What the replay cannot see is what a search result *says* once it lands — the
mechanism a document describes and the tests it names — which is where a grade difference
would come from if the documents caused it.

Re-derive: `.venv/bin/python experiments/m40_retrieval_replay.py`, with both corpora registered
in the clone's store and `ok`; it writes every query's two ranks to `<base>/eval/replay.json`.

## 6. Where the treatment spends more, and what it buys

2026-10-22, on the operator's three axes: an issue's difficulty, which arm spent more, and which
graded better (operator, 2026-10-22). **Spend is dollars**, `total_cost_usd`, which prices cached,
uncached and output tokens apart, where a token sum weighs a cache read like an output token
(operator). The unit is a **pair**, one repeat of one issue, both arms run at once — 48 pairs.
**Difficulty** is the control's median dollars over its three runs, what the issue costs a reader
with no documents: *trivial* under $1 (15666, 14231, 9056, 15646, 10355), *medium* $1–$8 (9013,
8357, 11262, 3970, 3265, 12425, 8881, 9145), *hard* over $8 (10144, 14234, 15590). A pair's grade
difference scores correct 2, partly 1, wrong 0.

| Tier | Pairs | Dollars, T vs C | Median pair T/C | Calls T/C | Context a call T/C | Grade points T vs C | Truth file first T vs C |
|---|---|---|---|---|---|---|---|
| trivial | 15 | $7 vs $7 | 1.04× | 0.90× | 1.07× | 27 vs 27 | 9 vs 9 |
| medium | 24 | $112 vs $81 | 1.43× | 1.34× | 1.20× | 38 vs 34 | 16 vs 17 |
| hard | 9 | $108 vs $107 | 0.97× | 0.96× | 0.96× | 13 vs 8 | 4 vs 2 |

| Tier | Treatment spent over 1.5× | Within 1.5× | Control spent over 1.5× |
|---|---|---|---|
| trivial | 3 pairs: 0 better, 3 equal | 12: all equal | — |
| medium | 12: **5 better, 7 equal, 0 worse** | 10: 0 better, 8 equal, 2 worse | 2: both equal |
| hard | 1: better | 8: **3 better**, 5 equal | — |

**Trivial issues cost the same and grade the same**: the documents neither help nor charge.
**Medium issues hold the whole excess** — $31 of the treatment's $32 over the control — and it
comes from more model calls (1.34×, more `Read`s: 22.5 a run against 16.7) and a larger context a
call (1.20×, about 22 KB of search results carried forward). The excess buys a better grade in 5
of the 12 pairs where the treatment spent over 1.5× and nothing in the other 7; it is never worse
there. **Hard issues are the documents' best case: the same dollars, better grades** (13 against
8 points, a truth file first in 4 pairs against 2), the treatment reading fewer files (12.4 a run
against 17.8, `Read` 56.7 against 75.2) and searching ten times a run instead. Three hard issues
is few, and 10144 carries most of the difference (+4 of +5).

**Within the treatment, more spend on the same issue does not buy a better grade**: on the one
issue whose cheapest and costliest treatment runs graded differently, the costlier graded worse.
So the gain is the arm's, not the effort's.

**The plainest waste is 11262**, *located* — its body names the fix file — graded `correct` three
times in both arms, the treatment at 1.5×, 5.6× and 4.5× the control's dollars. In repeat 2 the
control answered in 25 tool calls; the treatment had the same files by its eighteenth — the
issue's file, `privacy.rs`, the settings macros — and went on to 94, through the cloud-preference
syncer, safe-mode settings, feature flags and settings hot-reload, of which only safe-mode
settings reached its answer, as a fifth file. **Proposed, as the next variable to isolate**: the treatment's prompt alone, with no
documents, as a third arm on the medium issues — its paragraph *"It is a lead, not the source. A
document can be wrong … check anything a document says about another file in that file"* is the
one text the control lacks besides the documents, and over-verification is what 11262's run looks
like.

**What a tool result costs is its size times the calls that follow it** — it stays in the
context and is read again, from the cache, on every later call — so a run's cost by tool kind is
measured as that product, *carried*, summed over its results (operator's model, 2026-10-22: the
treatment both searches and reads, and a knowledge result is a snippet where a grep returns
lines). Per run, by tier:

| Tier | Arm | Carried, M chars | Read | Grep | Knowledge search |
|---|---|---|---|---|---|
| trivial | treatment | 0.3 | 5.0 × 3.5 k, 37% | 7.8 × 0.9 k, 14% | 1.9 × 7.3 k, 46% |
| trivial | control | 0.3 | 6.5 × 4.0 k, 71% | 9.0 × 1.0 k, 25% | — |
| medium | treatment | 7.1 | 22.5 × 4.0 k, 54% | 42.0 × 1.3 k, 31% | 2.2 × 9.3 k, 15% |
| medium | control | 4.8 | 16.7 × 5.4 k, 56% | 36.2 × 1.6 k, 43% | — |
| hard | treatment | 42.6 | 56.7 × 3.6 k, 39% | 93.3 × 1.8 k, 33% | 10.3 × 8.1 k, 28% |
| hard | control | 37.5 | 75.2 × 3.6 k, 71% | 97.4 × 1.1 k, 28% | — |

Each cell is results a run × mean characters, and the share of the run's carried total. **A
knowledge result is 7–9 k characters, about two `Read`s or five to eight `Grep`s**, and a reader
issues its searches first, where a result is carried longest. **On trivial issues the searches
replace reads one for one** — the same 0.3 M carried. **On medium issues they replace nothing**:
the treatment carries 2.3 M more, half of it the search results and half more reading (22.5
`Read`s a run against 16.7) — the reader searched and then verified as if it had not. **On hard
issues they replace reading**: 10 M fewer characters of `Read`, 12 M more of search, at the same
dollars. So the threshold the operator named is visible: a knowledge search pays when it saves
about two reads it would otherwise make, and on the medium tier it saved none.

Re-derive: `.venv/bin/python experiments/m40_breakdown.py`.
