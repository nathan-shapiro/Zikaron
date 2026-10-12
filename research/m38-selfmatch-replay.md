# A `pgrep -f` that finds its own shell — probes and a replay over local transcripts

Measured 2026-10-11 on Claude Code 2.1.287, Linux, procps-ng 4.0.4. It supports
`design/build-plan.md` §M38 and `design/guards.md` §9.

## Why the shell matches

Claude Code runs a `Bash` command as one shell whose argument carries the command verbatim, inside
an `eval`, with work after it — read from `/proc/$$/cmdline` inside a call:

```
/bin/bash -c source <snapshot> 2>/dev/null || true && shopt -u extglob 2>/dev/null || true
  && { \builtin unalias -- 'unsetenv'; … } >/dev/null 2>&1 || true
  && eval '<command, each ' written '"'"'>' && pwd -P >| /tmp/claude-<id>-cwd
```

Because `pwd -P` follows the `eval`, bash cannot replace itself with the last command, so this
shell is alive for the whole call with the command's text in its argv. A `Monitor` command runs
under the same wrapper: the same probe through `Monitor` printed the same shape.

| Probe, inside one call | Exit |
|---|---|
| `pgrep -f 'zz_probe_marker_123'` | **0** — it found the calling shell |
| `pgrep -f '[z]z_probe_marker_456'` | 1 |
| `pgrep -f 'zz_probe_marker_789\.x'` | 1 — `\.` does not match its own spelling either |
| `pgrep -A -f 'zz_ancestor_probe_77'` | 1 — `-A`/`--ignore-ancestors` drops the shell |
| `pgrep -f 'zz_ancestor_probe_78'` | **0** |
| the same self-match through `Monitor` | **0** |

So the predicate *does the pattern search the command's own text* is not a heuristic for the
self-match: it is the match `pgrep` performs, run against the string the shell carries, up to the
wrapper's rewriting of `'` and Python's `re` standing in for POSIX ERE.

**A command substitution running a pipeline is a second matching shell.** Inside one call, with
`$$` the calling shell's id:

| Probe | Ids printed |
|---|---|
| `x=$(pgrep -f '<nonce>' \| cat)` | two: `$$`, and the substitution's own shell — a fork with the same command line |
| `y=$(pgrep -f '<nonce>' \| grep -v $$)` | the substitution's shell survives the filter |
| `z=$(pgrep -A -f '<nonce>' \| cat)` | none |
| `for p in $(pgrep -f '<nonce>'); do [ "$p" = "$$" ] && continue; …` | none survive: a substitution of one simple command execs `pgrep` in place, leaving no second shell |

So a filter by `$$` is complete in some shapes and not in others, and `-A` is complete in all.

**`pgrep -a` prints a multi-line command line on one line**: from `bash -c $'pgrep -af <nonce>\n
true'`, the `bash -c` process's entry is one line, the newline printed as a space.

**Two readings of procps-ng 4.0.4's option parser**, each from one call that matches nothing:

| Call | What `pkill`/`pgrep` said |
|---|---|
| `pkill -int` · `pkill -INT` | *no matching criteria specified* — `-int` is read as the signal, its name compared without regard to case |
| `pkill -i -n -t` | *option requires an argument -- 't'* — the options `-int` would be if it were not a signal |
| `pgrep -A -f <nonce>` | exit 1, nothing on stderr — `-A` accepted, nothing matched |
| `pgrep -Q -f <nonce>` | exit 2, *invalid option -- 'Q'* on stderr — what an absent option looks like |

## `PreToolUse` on `Monitor`

A throwaway project with one `PreToolUse` group, matcher `Bash|Monitor`, whose script logged its
stdin and denied every `Monitor` call with a nonce; `claude -p --model haiku --permission-mode
bypassPermissions`, asked to call `Monitor` with `echo probe-line`. The hook received
`{"hook_event_name": "PreToolUse", "tool_name": "Monitor", "tool_input": {"description": …,
"timeout_ms": 5000, "command": "echo probe-line"}}`, and the nonce came back as the tool's result,
whose text began `PreToolUse:Monitor hook error: NONCE-MON-DENY-4471: …`. A second run, logging the
whole payload, found the fields a `Bash` payload carries: `cwd` (the project's absolute path),
`hook_event_name`, `permission_mode`, `prompt_id`, `session_id`, `tool_input`, `tool_name`,
`tool_use_id` and `transcript_path`.
**A `Monitor` call reaches a `PreToolUse` hook, carries its command in `tool_input.command`, and a
deny holds.**

## The replay

`experiments/m38_selfmatch_replay.py` reads every `Bash` and `Monitor` `tool_input.command` under
`~/.claude/projects/`, subagents included, leaving out the session that ran it, whose probes above
are deliberate self-matches (`--exclude-session`) — 33,597 `Bash` and 187 `Monitor` commands on
2026-10-11 — and parses each with the find-replace guard's own §3.1 grammar, plus `!` as a
prefix. A `pgrep`/`pkill` in command position is judged by the prototype of
`design/guards.md` §9's rule (`experiments/m38_selfmatch_prototype.py`): `-f` present, none of
`-x`, `-A`, `-v`; `pkill`'s signal read
from a fixed list; a literal first operand; Python `re.search` of that operand over the whole
command; silent when a `pgrep -a` pipes into a `grep -v` whose own literal pattern searches the
command. A command counts as **signalled** when its recorded result says `Exit code 144` or `143`.
The corpus is live — other sessions keep adding to it — so a re-run on another day moves the
counts; what the decisions rest on is the rates and the signalled column.

| Occurrences of `pgrep`/`pkill` in command position | `pgrep` | `pkill` |
|---|---|---|
| **deny** | 308 | 35 |
| silent: no self-match | 545 | 16 |
| silent: `-a` piped into a `grep -v` that removes the shell's line | 65 | — |
| silent: no `-f` | 64 | 0 |
| silent: pattern not literal (`$`, backtick) | 6 | 4 |
| silent: `-A` / `-x` | 0 / 1 | 0 |

**301 commands would be denied, 0.89% of the 33,784.** `Monitor` contributes 5 of the
occurrences. **That is a floor**: 21 further commands carry a `pgrep -f`/`pkill -f` only inside a
double-quoted `$(…)` — `echo "running: $(pgrep -cf …)"`, `"$(pgrep -f … | head -1)"` — which §3.1
keeps whole, so the rule never judges them (5 more carry one beside an occurrence that is denied).
None of the 26 is signalled; most are counts and `head -1` picks, the class whose answer is wrong
without anything recording it.

| Denied commands, by what the call did with the match | Signalled | Not signalled |
|---|---|---|
| kill — `pkill`, or `pgrep` output fed to `kill` | 32 | 5 |
| status — `if`/`while`/`until`/`!`, `&&`/`||`, `>/dev/null`, `-c`, `$( )`, `wc` | 4 | 191 |
| listing — output read by the agent | 2 | 67 |

The labels are a regular-expression reading of each command, and coarse; a status or count use
classed as a listing (`pgrep -fc …`, `pgrep -f … | head -1`) is common in the listing row.

### Readings

- **38 of the 40 signalled commands that run `pgrep`/`pkill` are denied, and the other two are not
  self-matches.** Exit 144 is how the harness reports a call whose shell was killed — by `pkill`,
  or by `kill $(pgrep -f …)` — as `CLAUDE.md` records for `pkill -f 'bin/pytest'`. The two
  exit-143 commands denied are `until ! pgrep -f …` and `if ! pgrep -f …` liveness loops that
  never ended and were killed at their timeout — found only once `!` was read as a prefix. The two
  not denied are `timeout N ssh host '…'` with `pgrep` inside the quoted remote script, which the
  grammar keeps whole (§7's `bash -c` gap), and each ran out its timeout for another reason: one
  sleeps 35 s under `timeout 30`, the other already drops shells from `pgrep`'s output by hand. So
  the observed harm is caught 38 of 38.
- **The status uses are wrong every time, signalled or not.** A self-matching `pgrep -f` always
  exits 0 and always counts at least one, so every `&& echo RUNNING || echo FINISHED` among the 191
  reported *RUNNING*. Nothing in a transcript records that the answer was wrong, which is why
  these are not signalled.
- **The 67 unsignalled listings are the only class where a deny can cost more than it saves.** Each
  prints one line too many — the agent's own shell — which is noise to a reader and wrong to a
  `head -1` or a `-c`. The 65 filtered listings, which already remove that line, are exactly the
  class the exemption keeps silent.
- **36 of the 343 denied occurrences match only *elsewhere* in the command, 30 of them with a
  bracketed pattern**: `pgrep -af '[c]heck.*\.sh' || echo "clean"` after an `rm -f /tmp/check.sh`
  in the same command, or `[c]heck.*\.sh` spanning `ruff check … ./check.sh`. The bracket fixes
  only the pattern's own spelling, so the deny must show *where* it matched; `-A` fixes all 36.
- **Unobserved, so not ruled on:** a pattern matching only the wrapper's own words (`bash`,
  `eval`, `claude`, `snapshot`) — 0 of the corpus's `-f` patterns; and `ps … | grep … | kill`,
  425 commands carrying `ps … | grep` with **no** signalled self-kill.

## The shipped rule against the prototype

`design/build-plan.md` §M38 item 6. The replay judges every command twice in one pass, by the
prototype and by `zikaron.guard.selfmatch` on `linux`, leaving out the build session and the live
tests' throwaway projects, whose commands are deliberate self-matches. On 2026-10-11, after the
bound-variable amendment below, the corpus had grown to 33,654 `Bash` and 188 `Monitor` commands,
and **the two disagree on one of the 33,842**: the shipped rule denies 305, the prototype 304 —
both with the same 36 signalled `exit 144` and 2 `exit 143`. The one is the operator's probe of
the amendment, `P=selfmatch-guard-probe; pgrep -af "$P"; echo "rc=$?"`, run in another session
that day: the shipped rule reads `"$P"` as its bound value and denies, where the prototype reads
any `$` as not literal. Before the amendment the two disagreed on none, over 33,820. 21 commands
carry a `pgrep -f`/`pkill -f` only inside a double-quoted `$(…)`, which neither judges (§9.4), and
5 more carry one beside an occurrence that is denied.

**A pattern from a variable bound in the same command** (§9.1, amended 2026-10-11, operator). Of
the 10 `-f` patterns the brief's replay read as not literal, 4 are a variable an earlier
assignment in the same command binds, in 3 commands — `P="zikaron.serv""ice.main"; pkill -f "$P"`
and two like it — and each split its literal precisely so that the value does not occur in the
command's text, so reading the value leaves all 3 silent. The other 6 are a variable the command does not bind (1)
and a substitution or other (5). The operator's probe is the first command whose bound value does
occur in its text.

**The agreement says nothing outside what the corpus holds.** The two differ by construction on
shapes it does not contain, and §9.5's rows are what decide those: a `!` followed by a wrapper
(`! timeout 5 pgrep -f …`, which the prototype reads as `timeout`), `pgrep -i`, which the
prototype does not read, a pattern token mixing single-quoted and unquoted parts around a `$` or
backtick (`a'$'`, `'a'$b`), a `grep --regexp=` or `-e` pattern written attached and not literal,
an escaped backslash in a basic `grep` pattern, a `grep` operand before an `-e`, and every
`darwin` row. **One shape the corpus does hold, without a verdict riding on it**: a redirect
token where the pattern would stand, which the shipped rule skips (§9.1) and the prototype reads
as the pattern — 2 of the 1,055 `pgrep`/`pkill` calls, both `pgrep -P <pid> -a 2>/dev/null`, with
no `-f`, so neither judge rules on them.

## The live session

`design/build-plan.md` §M38 done-when 3, run 2026-10-11 as
`tests/test_guard_claude_live.py::test_the_self_match_rule_denies_on_bash_and_monitor_in_a_real_session`:
Claude Code 2.1.287, `--model haiku`, `--permission-mode bypassPermissions`, a throwaway project
under `~/.cache/zikaron-live-tests/` with `--components guards` installed from the build's own
`.venv`, and three commands given exactly, each with a fresh random pattern no process carries.
What the harness recorded, with the final wording:

| Call | Recorded `tool_result` |
|---|---|
| `Bash`: `pkill -f <nonce>` | the deny, opening ``PreToolUse:Bash hook error: Zikaron's self-match rule refused this command: the `pkill` pattern``, its excerpt the whole command |
| `Bash`: `pkill -A -f <nonce>` | `Exit code 1` — it ran, and matched nothing |
| `Monitor`: `pgrep -f <nonce>` | the deny, opening ``PreToolUse:Monitor hook error: Zikaron's self-match rule refused this command: the `pgrep` pattern`` |

**After the `Monitor` deny, the model re-issued the call with `-A` unprompted, and the monitor
started** — the one retry the brief accepts for a deny that carries its own fix, n=1. The same run
passed M37's live test against the renamed tree. **Told only to run the commands, `haiku` declined
the `pkill`** as an action it had no reason for; the test's prompt now says what the commands are
for and why nothing can be stopped, so that the call, not the model's caution, is what is tested.

## Re-running

```
.venv/bin/python experiments/m38_selfmatch_replay.py [--dump PATH] [--exclude-session ID]
```

It prints the counts and each command on which the two disagree, with both verdicts. `--dump`
writes each would-be deny, each signalled miss and each disagreement verbatim to a local file; it
names other projects and private paths, so it stays out of the repository.
