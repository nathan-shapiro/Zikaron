# M37 row 6: how often a scratch script carries an edit, and what judging it denies

**Question.** `design/edit-guards.md` §3.2 left running a script file open, on the reasoning that
a guard that reads no file cannot see what a script does. The operator's interactive live test
(round 3 of the 2×2, `~/ZikaronTesting/story-key/round3/`) showed a vanilla agent doing its bulk
edit exactly that way. Is that a reflexive route worth closing, and what would closing it for
scratch scripts deny?

**Decision it supports.** Row 6 (operator, 2026-10-07): a shell or row-4 interpreter whose script
operand is scratch has the script judged — by a heredoc body staged for it earlier in the same
command, or else by one bounded read of the file.

## What the live test did

Round 3's arm A (no hooks, Opus, a docs tree where a departed co-owner had to be removed) made its
edit in five Bash calls. Its third carried the edit itself: a heredoc writing 140 lines of exact
replacement pairs to `<scratchpad>/fix.py`, then `python3 <scratchpad>/fix.py`, rewriting all 14
files. Replayed through the guard as it stood, calls 2, 4 and 5 (`sed -i`, and an inline
`python3 - <<'EOF'`) were denied and call 3 was silent: the heredoc's target was scratch and the run
was a script file, two exemptions at once. Under row 6, call 3 is denied — "`python3` runs a
scratch script that writes a file; it names no target the guard could resolve", the script's
writes going through a loop variable.

## Across local transcripts

Every project under `~/.claude/projects/` except the live test's own arms: 33,069 Bash calls.

**How scripts are run.** A regex count (`~/ZikaronTesting/story-key/round3/scratch_runs.py`):
231 calls ran an interpreter or shell on a `/tmp` script, in 34 transcript files. 85 had staged
the script with a `cat`/`tee` heredoc in the same command; 146 staged it earlier, 38 of those with
the `Write` tool in the same session.

**What row 6 denies — the product itself.** `experiments/m37_guard_replay.py --all-projects`,
which reads a scratch script as the session's own `Write` calls left it and never touches this
machine's disk:

| | Count |
|---|---|
| Bash calls | 33,069 |
| denied, any row | 2,951 |
| denied, row 6 the first denying form | 54, in 7 sessions across 3 projects |
| — staged by a heredoc in the same command | 35 |
| — staged by an earlier `Write` | 19 |

**Reading the 54** (each script's write lines read by hand):

| Reading | Count | What they are |
|---|---|---|
| true: an authored file rewritten by a scratch script | 47 | 27 in one `~/Memory` session rewriting `FINDINGS.md` and a design draft; 17 in one `~/Trading/LeibaTrader` session — path rewrites over archives, `AGENTS.md` trims, a `.kiro` agent's scope, a generated `tools/README.md`; 3 mutation edits to this repository's tests |
| true, and the override is the right answer | 2 | re-rendering `.kiro` golden files through a script — bytes a program owns |
| false: the script's targets were scratch, but arrive as `sys.argv` or a computed path | 5 | in 2 sessions; §7's stated false deny "a scratch script given its targets as arguments" |

So nine in ten of row 6's denies are the edit the guard exists to stop, and the false ones are one
class the design already names. The 85 same-command stagings are the half a file read alone would
never have caught: at `PreToolUse` the file does not exist yet, or holds an earlier version.

**Re-run:** `.venv/bin/python experiments/m37_guard_replay.py --all-projects` (counts, by form);
`--dump PATH` writes every deny verbatim to a local file, which is not published — it names other
projects' paths.

## What this does not measure

- Whether denying the scratch route changes what an agent does next — override, Read and Edit,
  or another route row 6 misses (§7). That is what arms B–D of the live test are for.
- 108 of the 146 earlier stagings could not be reconstructed (staged by an earlier Bash call), so
  row 6's file-read half is measured only on `Write`-staged scripts.
- Scratchpads are deleted, so no deny here was judged on the file a live hook would have read.
