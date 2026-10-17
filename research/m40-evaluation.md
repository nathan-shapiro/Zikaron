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
the documenter's context window, so its current document lists 136 functions of about 750, and its
role line says so: *"This document describes the file in part (lines 1–3200, 27463–27463,
28982–29590 read in full; remaining method bodies located by search)"* (`research/m40-toy-run.md`
§8). **The specs count is broad for a central file**: `view.rs`
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
