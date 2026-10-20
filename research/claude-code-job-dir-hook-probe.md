# What a Claude Code background job's hook sees — probe, 2026-10-20

**Question.** A background job (`claude --bg`) is told by the harness to put its scratch files in
`$CLAUDE_JOB_DIR/tmp` rather than `/tmp`, and the edit guard (`design/guards.md` §3.3) denied a
heredoc written there in `~/Trading/LeibaTrader` on 2026-10-18. Does the guard's hook process see
`CLAUDE_JOB_DIR`, and does the payload name the job's directory?

**Method.** Claude Code 2.1.304. A throwaway project in a trusted directory, with one
`PreToolUse` hook on `Bash` that wrote its environment's `CLAUDE*` and `TMPDIR` variables and its
stdin to a file and exited 0, and `Bash(echo:*)` allowed. Started with
`claude --bg --model haiku "Run exactly this one Bash command and nothing else, then stop: echo probe > \$CLAUDE_JOB_DIR/tmp/probe.txt"`,
then stopped and removed with `claude stop` and `claude rm`.

**Measured.**

- The hook's environment carries `CLAUDE_JOB_DIR=/home/nathan/.claude/jobs/37bc03ae` — the job's
  directory, named by the first eight characters of the session id
  (`37bc03ae-be0b-4ac0-8c19-620d1ba44823`), as LeibaTrader's job of 2026-10-18 was told to use
  `~/.claude/jobs/86ba5119/tmp` in session `86ba5119-…`.
- `TMPDIR` is unset in the hook's environment.
- The payload carries `scratchpad_dir` (`/tmp/claude-1000/-home-nathan-zk-spill-e2e/<session>/scratchpad`),
  which 2.1.285 did not send; it is the session's scratchpad under `/tmp`, not the job's `tmp`.
- The command arrives as written, `echo probe > $CLAUDE_JOB_DIR/tmp/probe.txt`: the variable is
  not expanded in `tool_input.command`.
- This session, which is no background job, has no `CLAUDE_JOB_DIR` in its environment.

**Reading.** The guard can take the job's scratch root from its own environment, as it takes
`$TMPDIR`, and read the literal spelling `$CLAUDE_JOB_DIR/tmp/…` as scratch. The literal is safe
in every session: where the variable is unset the shell expands it to `/tmp/…`, itself scratch.
Only `tmp` under the job directory is scratch; `state.json` and `timeline.jsonl` beside it are the
harness's own.

## How often the field meets it — replay

`experiments/m40_1_job_dir_replay.py`: every `Bash` command in every project's transcripts,
subagents included, that names `CLAUDE_JOB_DIR` or the absolute `/home/nathan/.claude/jobs/…`, the
transcripts of every checkout of this repository left out since they quote such commands in
discussion; judged by the
find-replace rule under its recorded `cwd` with `$TMPDIR` unset, and each deny classed as
`experiments/m37_guard_replay.py` classes one. Whether the guards were installed when a command
ran is not read, so this counts what the rules deny, not what they denied. *Before* is the M40
commit's rules (`--no-job-dirs`, `PYTHONPATH` naming that checkout); *after* is §M40-1's, with each
job's directory taken from its session id. Both were taken together, at 2026-10-20T23:04Z: the
counts grow with the transcripts, these including the live jobs below, so a later run's differ.

| Of 711 distinct (command, `cwd`) pairs | Before | After |
|---|---|---|
| denied | 247 | 138 |
| false: the job's own `tmp`, by its absolute path | 130 | 0 |
| false: the job's own `tmp`, spelled through the variable | 44 | 0 |
| true: an authored file of the session's project | 55 | 108 |
| true: an authored file outside the session's project | 16 | 21 |
| true: a write whose target the rules cannot resolve | 2 | 9 |

**Reading.** The change clears every false deny the field holds. The *true* classes grow because a
command denied before for staging a script in the job's `tmp` is now judged for what the script
does, and a sample of each shows what it does: scripts staged there, and inline ones, that rewrite
the project's Scala sources and Markdown in place — the edit the guard exists to refuse. The nine
unresolvable writes are the rule's deny of any write it cannot place (§3.3), several of them into
the job's `tmp` through a Python variable, which no root reaches; none of the nine reads the job
directory from the environment (`os.environ`, `getenv`), so a script's own spelling of it stays
unobserved. No command `cd`s to the
directory through the variable and writes after it, so that shape stays §7's stated false deny.

The three denies the guard returned in the 2026-10-18 job were the two job-directory writes
`design/build-plan.md` §M40-1 quotes and one scratch script under the session's scratchpad writing
a target the rules cannot resolve, which this change does not touch.

## Live, with the change — 2026-10-20

`design/build-plan.md` §M40-1, done-when 3. Claude Code 2.1.304, a throwaway project under
`~/ZikaronTesting` with `--components guards` installed from the build's worktree, and
`claude --bg --permission-mode bypassPermissions --model sonnet` jobs given numbered steps; job
`3650c925` ran every step of done-when 3.

- **The observed commands run.** `cat > $CLAUDE_JOB_DIR/tmp/leaf_events.py <<'EOF'` and, at the
  job's absolute path, `cat > /home/nathan/.claude/jobs/3650c925/tmp/group_book.py <<'EOF'` each
  completed, both files were on disk afterwards, and no tool result in the transcript is a
  `PreToolUse:Bash hook error`.
- **The `PostToolUse` hook sees the variable too.** A `Write` overwriting `group_book.py` at its
  absolute path, after a `Read` of it — its result `type` `update`, before `EnterWorktree`, so the
  refusal below is of the shared checkout, not of the job's own directory — is followed by no
  `hook_additional_context` attachment. The
  control, a `Write` overwriting the project's committed `notes.md`, is followed by one,
  `PostToolUse:Write`, carrying the re-read reminder.
- **Claude Code refuses a background session's edit to the shared checkout until it calls
  `EnterWorktree`** ("This background session hasn't isolated its changes yet"), which is how an
  earlier job's control failed; so the control overwrote `notes.md` in the worktree the job
  entered, under `<project>/.claude/worktrees/<name>/` — inside the project, and so not scratch.
