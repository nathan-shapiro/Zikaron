# The guards in the field — `design/guards.md` §7's counts, first read

2026-10-21, from the Claude Code transcripts of the three projects that install the guards
(`~/Trading/LeibaTrader`, `~/Dividends`, `~/Memory`, `--components both` since 2026-10-07),
subagents included. **Only LeibaTrader has sessions since the install**: Dividends and Memory have
none, so every post-install figure below is LeibaTrader's — 3,669 `Bash` calls from 2026-10-08
to 2026-10-21, the install day left out, against 11,686 before it. The would-deny figures are
today's guard replayed over each call with the call's recorded `cwd`; the actual denies are tool
results beginning `PreToolUse:Bash hook error`.

## (a) Denies

| | Pre-install, replayed | Post-install |
|---|---|---|
| find-replace | 1,527 would-deny, 13.1% of calls | 7 denied, 0.19% |
| self-match (live from 2026-10-11) | 136 would-deny, 1.1% of `Bash`/`Monitor` calls | 11 denied |

**The find-replace forms nearly stopped being issued.** Of the 7 denies, 3 are true: an
append to `FINDINGS.md` through `cat >> … <<'EOF'`, a `python3 -` heredoc replacing text in
`tools/group_water_replay.py`, a `sed -i` on `STATE.md`. 4 are false, and 3 of those are fixed
since: two writes into a background job's `tmp` directory (M40-1), and a scratch script reached
through a variable that today's rules allow. The fourth is a `python3 - "$F" <<'EOF'` whose
script writes `sys.argv[1]`, a scratchpad path: a target the rules cannot resolve is denied, as §7
records, and the agent's next call was the `Edit` tool on the same file — one turn.

## (b) Overrides

8 commands carry `#ZIKARON-FORCE #Reason:`, and **every reason says what the command does and
why that is safe** — none is boilerplate: four that a script's list mode is read-only and its split
mode writes only scratch (the false deny since fixed), two a verbatim move of FINDINGS sections with
the original backed up and checksummed, and two an operator-approved mechanical change across 39
and 14 listed tools, verified by `git diff` and `py_compile`. Only one followed a deny; the rest
were written with the override from the first attempt.

## (c) Reflexive overrides and routing around

After each find-replace deny the next call was the `Edit` tool (2), the `Write` tool (2), a `Read`
of the target (1), the same command without its `sed -i` (1), and an override (1, of the false deny
since fixed). **No true deny was overridden or routed around.**

## (d) The nudge

Of the paths a LeibaTrader main session edited inside the project — `code-knowledge/` and its two
agents left out — the share re-read after the last edit, by `Read`, a reading command naming the path, or a
`git diff` showing it:

| | Pre-install | Post-install |
|---|---|---|
| edited with `Edit` | 85 of 105, 81% | 38 of 42, 90% |
| written whole with `Write` only | 67 of 83, 81% | 5 of 8, 62% |

Pre-install, subagents re-read none of their 22; post-install no subagent edited such a path. The
post-install counts are small, so this says the nudge has not hurt, not that it helped.

**In documenters, where it can be told apart.** In a project installed with `--components both`,
2026-10-21, 90 documenters of one session (two modules of the M40-5 interactive test): the nudge
followed an `Edit` of the document and not its first `Write` of a new file, so it reached the 40
that edited, and 39 of those then read their document again — one's reasoning naming the hook as
why — while none of the 50 it did not reach re-read theirs. 24 of the 39 re-reads were followed by a
further correction; 47 documents were written once and never re-read.

## (e) Self-match denies

8 of the 11 are one agent probing the guard on purpose (`selfmatch-guard-probe`, 2026-10-12). The
other 3: one answered with `pgrep -A`, and two by `ps … | grep` with a bracketed pattern
(`'[m]onth_monitor.py'`) — the route §9.4 names, here correct and harmless. Replayed, 5 calls since
2026-10-12 would be denied today (0.14%), against 1.1% before.

## Reading

Nothing here moves a §3 or §9 rule. The one false deny still standing costs one turn and is the
conservative choice §7 already records.

Re-derive: `field_counts.py` and `nudge_counts.py`, this session's scratch scripts, implement
the five definitions of `design/guards.md` §7 over `~/.claude/projects/-home-nathan-<project>/`
with `zikaron.guard.decision.decide` and `zikaron.guard.selfmatch.first_self_match`; the replay
harnesses `experiments/m37_guard_replay.py` and `experiments/m38_selfmatch_replay.py` give the
would-deny side.
