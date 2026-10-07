# Claude Code runs a hook `command` through a shell — probe

Measured 2026-10-07 on Claude Code 2.1.285, `claude -p --model haiku --permission-mode
bypassPermissions "reply ok"`, in a throwaway git repository under the session scratchpad whose
own path contains a space (`…/shellprobe/my dir/`).

## Setup

`.claude/settings.local.json` registered three `SessionStart` groups, each running the same
executable `…/my dir/bin dir/h.sh`, which appends its `$0` and arguments to a log:

| Group | `command` |
|---|---|
| A | the path unquoted, then ` --components guards` |
| B | `shlex.quote(path)`, then ` --components quoted` |
| C | the path unquoted, alone |

## Result

The log holds **one** line, from B: `…/bin dir/h.sh|--components|quoted|`. A and C never ran.

## What follows

- **The field is a shell command line.** B's quoted path was unquoted and its two arguments
  split, which only a shell does; A and C were split at the space in `my dir`, as a shell splits
  an unquoted word.
- So `zikaron-hook --components guards` (`design/edit-guards.md` §5) works as written, **provided
  the path is shell-quoted**, and an unquoted path containing a space or any other shell
  metacharacter does not run at all.
- `shlex.quote` returns a path made only of `[A-Za-z0-9@%+=:,./_-]` unchanged, so quoting alters
  the bytes of no command that runs today.

Re-derive: the setup above with any executable that logs its argv; the log after one session is
the result.
