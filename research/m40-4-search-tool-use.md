# Which tool an agent searches source with — M40-4's trigger

Measured 2026-10-20 on Claude Code 2.1.304, from the harness's own transcripts under
`~/.claude/projects/`, for M40-4's choice of which tool calls the reminder hook follows
(`design/build-plan.md` §M40-4, item 2).

## Counts, since 2026-10-01

| Who | `Grep`/`Glob` calls | `Bash` calls | Source |
|---|---|---|---|
| Main sessions, this repository | 0 | 5,024 | top-level `*.jsonl`, 10 sessions |
| Main sessions, `~/Trading/LeibaTrader` | 0 | 4,381 | top-level `*.jsonl`, 10 sessions |
| Subagents, this repository | 3,183, all `memory-reviewer` | 815 | `*/subagents/*.jsonl` |
| Subagents, `~/Trading/LeibaTrader` | 1,835, all `zikaron-documenter` | 184 | `*/subagents/*.jsonl` |
| Warp evaluation readers, control | 156 | 0 | `-home-nathan-Zikaron-m40-eval-root-a-warp` |
| Warp evaluation readers, treatment | 231 | 72 | `-home-nathan-Zikaron-m40-eval-root-b-warp` |

Across every main-session transcript the two projects keep, back to 2026-08-16, one `Grep`/`Glob`
call appears, in this repository on 2026-09-29. This build offers the main session neither tool —
a session's own tool list carries `Bash`, `Read`, `Edit` and `Write` and no search tool — so a
main session searches through `Bash`. A subagent whose definition grants `Grep` and `Glob` and withholds `Bash`, as
memory-reviewer's and the documenter's do, searches through them; a headless reader given them by
an allowlist uses them too.

**The command words main sessions search with**, from the first word of each `Bash` command (or
the word after a leading `cd … &&`): this repository `grep` 1,299, `find` 5; LeibaTrader `grep`
243, `find` 10; `rg`, `egrep` and `fgrep` none. `git grep` appears four times in all of this
repository's transcripts since 2026-10-01, subagents included, and never in LeibaTrader's.

## What it decides

- **Both paths are needed.** `Bash` is the only way a main session searches in this build, and
  `Grep`/`Glob` the only way a subagent without `Bash` does. Dropping either leaves one of the two
  kinds of agent unreminded.
- **`find` stays out** (the brief's fence): it is rare in main sessions, and lists files rather
  than searching them. **`git grep` is in**, rare as it is here, on the operator's word
  (2026-10-20).
- **The hook starts on every documenter `Grep`/`Glob` call** even though it is silent there,
  since a hook entry's matcher and `if` filter select a tool and its arguments, not an agent.
  At the 95 ms a start-and-exit took on this busy host (2026-10-20, an ignored event piped to
  `.venv/bin/zikaron-hook`), 1,835 calls are about three minutes of hook time across all of
  LeibaTrader's documenters, which run 19 at a time. The live session of done-when 2 measures the
  hook's wall time per call.

## Re-derive

```bash
cd ~/.claude/projects
# per project directory $d: main sessions, then subagents
find "$d" -maxdepth 1 -name '*.jsonl' -newermt 2026-10-01 \
  -exec grep -o '"name":"\(Grep\|Glob\)","input"' {} + | wc -l
find "$d" -path '*subagents*' -name '*.jsonl' -newermt 2026-10-01 \
  -exec grep -o '"name":"\(Grep\|Glob\)","input"' {} + | wc -l
# the agent type of a subagent transcript is in its sibling .meta.json ("agentType")
```
