# M40-4's three probes: what a search's `PostToolUse` hook sees and delivers

Measured 2026-10-21 on Claude Code 2.1.304, for `design/build-plan.md` §M40-4 item 1. Four
headless runs, `claude -p --model haiku --permission-mode bypassPermissions --output-format
stream-json --verbose`, in a throwaway git project at `~/ZikaronTesting/m40-4-probe`. A logging
hook wrote each call's payload and its environment's `CLAUDE_CODE_SESSION_ID` to a file and
returned a nonce in `additionalContext`. A nonce counts as delivered when the agent that made the
call quoted it back. Runs 1 and 2 cost $0.016 and took 45 s together; runs 3 and 4, below,
about $0.01 more.

**The settings**, registered identically on `PostToolUse` and `PostToolUseFailure`, four groups
each:
- **A, two groups**: `Grep|Glob` with no filter; and `Bash` with one handler per `if`, a string
  each — `Bash(grep *)`, `Bash(egrep *)`, `Bash(fgrep *)`, `Bash(rg *)`, `Bash(git grep *)`,
  `Bash(git -C * grep *)`.
- **B, one group**: matcher `Grep|Glob|Bash`, with handlers whose `if` is `Grep`, `Glob` and
  `Bash(grep *)`.
- **C, the control**: `Bash` with no filter.

A subagent definition, `probe-searcher`, granted `Grep`, `Glob` and `Read` and no `Bash`, was
spawned twice.

## Probe 1 — who is calling

| Field | Main session | Inside a subagent |
|---|---|---|
| `agent_type` | absent | `probe-searcher` |
| `agent_id` | **absent** (the key is not in the payload) | present; one value across a subagent's three calls, another for the second subagent |
| payload `session_id` | the session's | **the parent's** |
| hook's `CLAUDE_CODE_SESSION_ID` | the session's | **the parent's** |
| `cwd` | the session's, following a `cd` an earlier command made | the parent's current one, `cd` included |

A tool event's payload carries `cwd`, `duration_ms`, `effort`, `hook_event_name`,
`permission_mode`, `prompt_id`, `session_id`, `tool_input`, `tool_name`, `tool_response`,
`tool_use_id` and `transcript_path`, plus `agent_id` and `agent_type` inside a subagent. The
subagent's `Grep` carried the `path` it was given, absolute here because the model wrote it so, and
no `path` key when it was given none.

## Probe 2 — the `if` filter

| `Bash` command | Handlers that started |
|---|---|
| `grep -rn needle src` | A `Bash(grep *)`, B `Bash(grep *)`, C |
| `ls src` | **C only** |
| `timeout 5 grep -rn needle src` | **C only**: the filter does not see through the wrapper |
| `LC_ALL=C grep -rn needle src` | A, B, C: an assignment is seen through |
| `git grep -n needle` | A `Bash(git grep *)`, C |
| `git -C src grep -n needle` | A `Bash(git -C * grep *)`, C: a wildcard mid-pattern matches |
| `rg needle src` | A `Bash(rg *)`, C |
| `egrep -rn needle src` | A `Bash(egrep *)`, C |
| `git log --oneline \| grep init` | A `Bash(grep *)`, B, C: a pipeline's later command is matched |
| `cd src && grep -rn needle .` | A `Bash(grep *)`, B, C: a compound command's later command is matched |

On the subagent's calls, `Grep` started A's `Grep|Glob` group and B's `if: "Grep"` handler, and
`Glob` started A's group and B's `if: "Glob"` handler. **So one group serves both arms**: matcher
`Grep|Glob|Bash`, a handler per tool or command word, each with a string `if`. A list-valued `if`
was not tried, since nothing needs it.

## Probe 3 — a search that finds nothing, and one that fails

| Command | Exit | Event fired |
|---|---|---|
| `grep -rn zzznomatch src` | 1 | `PostToolUse`, `tool_response.returnCodeInterpretation: "No matches found"` |
| `git grep -n zzznomatch`, `rg zzznomatch src`, `egrep -rn zzznomatch src` | 1 | `PostToolUse`, the same interpretation |
| the `Grep` tool, no match | — | `PostToolUse`, `numFiles: 0` |
| `grep -rn needle no_such_dir`, `rg needle no_such_dir` | 2 | `PostToolUseFailure`, `error: "Exit code 2\n…"` |
| `false`, `ls no_such_dir` | 1, 2 | `PostToolUseFailure`, control group only |

**A search that finds nothing is a successful call**, because Claude Code reads a search command's
exit 1 as "No matches found". On `PostToolUseFailure` the filter held: `false` and `ls` started only
the control. The payload carried `tool_input`, and the nonce was delivered.

## Probe 2, continued — commands the filter cannot read, a list, a leading wildcard

Two more runs the same day, after review round 6 asked what a `Bash` input Claude Code cannot parse
starts. Run 3 kept group A's six `Bash` handlers, added a handler whose `if` was the list
`["Bash(grep *)", "Bash(rg *)"]`, and the control. Run 4 had one group, matcher `Grep|Glob|Bash`,
with two handlers, `if: "Bash(*grep *)"` and `if: "Bash(rg *)"`, and the control.

| `Bash` command | Filtered handlers that started |
|---|---|
| a heredoc, then `grep -rn needle src` (run 3) | **all six** |
| a heredoc alone, no search (run 4) | **both** |
| `echo $(grep -rn needle src)` (run 3) | three: `grep`, `git grep`, `git -C * grep` |
| `bash -c 'grep -rn needle src'` (run 3) | **none** |
| `grep`, `egrep`, `git grep`, `git -C src grep` (run 4) | `Bash(*grep *)` alone |
| `pgrep -f zzzprobe` (run 4) | `Bash(*grep *)` |
| `ls src`, `python3 -c "print(1)"` (run 4) | none |

- **A list-valued `if` never matched**, not even `grep -rn needle src`, while the file's other
  handlers fired: it is ignored rather than rejected.
- **A command the filter cannot read starts every filtered `Bash` handler**, as the
  documentation says, whether or not it searches. A heredoc is such a command. The handlers start
  together: run 3's seven started within 7 ms of each other, so the wall cost is one start and the
  process count is the handler count.
- **A leading wildcard matches**: `Bash(*grep *)` covers `grep`, `egrep`, `git grep` and
  `git -C … grep`, and `pgrep` too, which the hook's parser reads as no search.
- `bash -c '…'` hides its search from the filter.

## Delivery

Every nonce was quoted back by the agent whose call produced it: all of the main session's, on both
triggers, and each subagent's from its own searches. A subagent that issued its calls together
received their nonces together after them.

## Probe 5 — a main session started as a named agent (run 5, for the build review)

`claude --agent probe-main -p …`, the agent a `tools: Bash, Agent` definition, one `grep`: its
`PostToolUse` payload carried **`agent_type: "probe-main"` and no `agent_id`**, with the same other
keys as a plain session's. So a project whose sessions start as named agents, as the real stores'
do, has its main session keyed as the session — the hook sends an `agent_id` only beside an
`agent_type` — and `memory_surface`'s clear reaches it.

## Probe 6 — `rg` after `cd … &&`, `;` and an assignment (runs 6 and 7)

The group's `Bash(rg *)` handler beside a `Bash(*rg *)` one, logging each start:

| Command | `Bash(rg *)` | `Bash(*rg *)` | Notes |
|---|---|---|---|
| `cd src && rg zzz_probe .` | started | started | no match, read as success |
| `ls; rg zzz_probe src` | started | started | |
| `rg zzz_probe src` | started | started | |
| `LC_ALL=C rg zzz_hit src`, `FOO=1 rg zzz_hit src` | started | started | a match, exit 0 |
| `LC_ALL=C rg zzz_probe src` | — | — | no match: exit 1 came back as an error, so `PostToolUseFailure` fired and no `PostToolUse` handler ran |
| `jq -n --arg a b '$a'` | not started | **started** | a false start |
| `echo cargo build` | not started | not started | |

**The filter is matched per subcommand, assignments stripped**, so `Bash(rg *)` needs no leading
wildcard; `Bash(*grep *)` has one for `egrep`, `fgrep` and `git grep`. **An assignment before a
search makes its miss an error**: Claude Code reads exit 1 as "no matches" only when the command
itself is the search, so such a miss fires `PostToolUseFailure`, a known miss.

## Incidental

- `grep` in Claude Code's `Bash` tool is the harness's bundled `ugrep`: the failure text reads
  `ugrep: warning: no_such_dir: …`. `rg` runs there too, although no `rg` is on this machine's
  `PATH`.
- The subagents' context also carried the instructions of a claude.ai connector configured for
  this account, which both subagents mentioned and ignored. That has nothing to do with the hooks.

## What it decides for M40-4

- **The build goes on**: `agent_type` names the subagent's definition, and `agent_id` is present
  in a subagent, absent in the main session and constant across one subagent's calls, so the
  throttle can key on the session label plus `agent_id`.
- **No label fallback is needed**: a subagent's hook process carries the parent's
  `CLAUDE_CODE_SESSION_ID`, the same value as its payload's `session_id`.
- **One `PostToolUse` group**, matcher `Grep|Glob|Bash`, with four handlers, each with a string
  `if`: `Grep`, `Glob`, `Bash(*grep *)` and `Bash(rg *)`. A command the filter cannot read, such
  as any heredoc, then starts two hook processes together, about one start's wall time, and in
  most such commands the hook's parser finds no search and asks nothing. Ownership on that trigger is still judged per
  program, beside the guard's group.
- **`PostToolUse` alone**: every search that ran, matches or none, fires it. A search that errors
  fires `PostToolUseFailure` instead and is left out, a known miss.
- **Known misses the filter adds**: a search behind `timeout` or another wrapper, and one inside
  `bash -c '…'`.
- **The payload's `cwd` already follows earlier `cd`s**; only a `cd` within the same command is
  not followed.
