# Review — M40-1 build, a background job's own scratch directory

Artifact: the uncommitted changes in the worktree `/home/nathan/Zikaron-m40-1` (branch
`m40-1-job-dir`, over `5a46f5e`): `zikaron/guard/scratch.py`, `zikaron/guard/main.py`,
`design/guards.md`, `README.md`, `tests/guard_table.py`, `tests/test_guard_rule_table.py`,
`tests/test_guard_main.py`, `tests/test_guard_nudge.py`, `tests/test_guard_properties.py`,
`tests/test_guard_selfmatch_table.py` and the new `experiments/m40_1_job_dir_replay.py`. Judged
against `design/build-plan.md` §"M40-1 — A background job's own scratch directory, which the edit
guard called authored" (brief review: `reviews/m40-1-job-dir-review.md`, APPROVED at round 6),
`research/claude-code-job-dir-hook-probe.md`, and `design/coding-standards.md`. Each changed file
was read beside its `5a46f5e` counterpart in the main tree; the unchanged `decision.py`,
`script_file.py`, `nudge.py` and `tests/design_tables.py` were read for the §8.2 values.

## Round 1 — 2026-10-20

**Summary judgment.** The build does what the brief says, and the code agrees with the spec at
every sentence the change touches: `Location.job_dir` normalised through `_usable` and rooted at
`<job>/tmp` alone, the literal `_JOB_TMP_LITERAL` beside `_TMPDIR_LITERAL` with the same
`_substituted`-first order, `_JOB_DIR_PREFIX` in `file_path` answering `None` where the hook has no
value, `main` reading `CLAUDE_JOB_DIR` beside `TMPDIR` inside the fail-open block, and the nudge
inheriting all of it through the one `_location`. Every row of §8.2 comes out as its cell says when
walked through `all_matches`, `ScriptRuns._text`/`_key` and `is_exempt`, both columns; every
invariant the brief lists has a test that the named mutation reddens; the four pin sites are
pinned; nothing in `zikaron/` or `tests/` carries provenance, and no comment narrates a repair.
Nothing I found rises above a nitpick, and none of it touches the three projects that will run
this guard at their next `Bash` call: in a session with no `CLAUDE_JOB_DIR` the roots are what
they were, and the only new silence — the literal `$CLAUDE_JOB_DIR/tmp/…` — is a path the shell
expands under `/tmp` there.

### Findings

1. **[NITPICK] The replay excludes the script's own checkout key, which for the run the note
   records was a key that does not exist.** `experiments/m40_1_job_dir_replay.py` line 32 derives
   `_THIS_REPOSITORY` from `Path(__file__)`, so run from the worktree it is
   `-home-nathan-Zikaron-m40-1` — no such directory under `~/.claude/projects/` (the keys there
   are `-home-nathan-Zikaron`, `-home-nathan-Zikaron-m40-warp`, the two `m40-eval-root-*-warp`
   and `m40-eval-judge-cwd`) — and the main checkout's `-home-nathan-Zikaron` was **included**.
   It holds `Bash` commands naming `CLAUDE_JOB_DIR` beyond greps: session `4dee89b3`'s probe
   staging and four `claude --bg "… cat > \$CLAUDE_JOB_DIR/tmp/…"` launches (the write is inside
   the quoted prompt, so silent), session `2d043f4f`'s `git show HEAD:… > "$CLAUDE_JOB_DIR/…"`
   (a row-5 redirect through the variable — a before-deny in the "spelled through the variable"
   class if it fell under `tmp`), and `b2c64ffe`'s `mkdir -p "$CLAUDE_JOB_DIR/tmp/claude-backup"
   && cp -r …` (no form). So the docstring's "This repository's own transcripts are left out" and
   the note's line 36–37 did not hold for the dated run. **The decision is unaffected**: an
   included project can only add denies, and both false classes are 0 after; the before-counts may
   be a few high. Cheap fix, either: compute the excluded keys from every checkout
   `git -C <script dir> worktree list --porcelain` names (main plus worktrees — the build's own
   sessions quote these commands too), or say in the docstring that the script runs from the main
   checkout and add that to the note's method sentence. While there: `classify` (line 44) tests
   `"$CLAUDE_JOB_DIR/tmp" in p`, which also matches a `…/$CLAUDE_JOB_DIR/tmpx/…` path; anchor it
   (`"/tmp/" in p or p.endswith("/tmp")`) so a conceived-edge spelling is not read as the job's
   `tmp`. Zero in that class after the change shows neither bit; recorded so a later run is read
   right.

2. **[NITPICK] The worktree's `guards.md` cites a note the worktree does not hold, and nothing in
   the gate says so.** `design/guards.md` lines 61, 62 and 436 cite
   `research/claude-code-job-dir-hook-probe.md`; the file exists only in the main tree,
   untracked, and the worktree has no `build-plan.md` §M40-1 either (`M40-1` occurs 0 times
   there). The worktree's gate is green regardless — `tests/test_design_pointers_resolve.py`
   resolves the `` §"…" `` form only, so a bare-path citation to a missing file reddens nothing.
   Not a defect of the build, which the brief says reaches the main tree once green; a check at
   that moment: the note, §M40-1 and `design/kiro-gaps.md` (which the brief's fence cites) land in
   the same commit as `guards.md`.

3. **[NITPICK] One docstring says half the payload.** `tests/test_guard_selfmatch_table.py` line
   3 — *"judged as §8's are — `cwd` `/home/u/proj`, `$TMPDIR` unset, no file for row 6 to read"*
   — while its fixture (lines 51–54) now pins `CLAUDE_JOB_DIR` too and §8 (`guards.md` line 820)
   states both. Say "`$TMPDIR` and `CLAUDE_JOB_DIR` unset", as `test_guard_rule_table.py` line 3
   does.

4. **[NITPICK] `README.md` line 503** — *"a script under `/tmp` or `$TMPDIR` that the command
   runs"* — now also covers a script under the job's `tmp` (§8.2's last row). Optional: line 505,
   which the brief asked for, is complete; this sentence was already a simplification before the
   change.

Checked and found correct: `scratch.py` against §3.3 — `_JOB_TMP_LITERAL`'s `(?:/|$)` giving
"alone or followed by `/…`" and refusing `tmpx`; `_substituted` before the literal match, so a
command-bound `CLAUDE_JOB_DIR=` is read with its value; `roots` adding `f"{job_dir}/tmp"` only
after `_usable` (empty, `/`, trailing `/`, relative — the doctest at lines 163–164 pins the last
two) and the `Location` field order `main._location` relies on. `file_path` against §3.2's "Row
6's text" — both spellings, `None` unset, the doctest at lines 118–124 pinning what §8.2's unset
column cannot see. `main.py` — `job_dir` read inside `suppress(Exception)`, `_location` hoisted to
`respond` with no change to either branch's conditions, the `noqa: PLR0913` the brief settled.
§8.2 values both ways: the literal rows through `_JOB_TMP_LITERAL`; the absolute rows through the
root; `state.json`/`tmpx/a` under neither; `cd "$CLAUDE_JOB_DIR/tmp"` through `moved_to` →
`resolve` (no substitution) naming `/home/u/proj/$CLAUDE_JOB_DIR/tmp/stub.py`, which
`_assert_deny_message`'s `normalise` matches; the staged-and-run absolute row (unset: pipeline
one's row 5 is the first denying form; set: it is exempt and pipeline two's row 6 takes the staged
body through `_key`, naming `/home/u/proj/f`); both variable spellings meeting through `file_path`
set and `resolve` unset; the python-body row judged at the `cd`'s location and its `bash` twin
from the payload's `cwd`; the `os.environ` row naming nothing; the file row read through
`_JOB_DIR_PREFIX` set and silent unset, platform-independent since the row reaches its file only
through the literal. `guard_table.py` — the four-cell header byte-for-byte, `_split_row` keeping a
blank first cell, `job_cases` yielding both settings, the §8 two-column reader unaffected by the
new table in its section. The pin sites — both table fixtures, `test_main_writes_…`, and
`TestTheRealProcess._run`'s environment copy. The mutations the brief names each reaching a red
row (root dropped: 1071/1074/1076 set, the nudge and `main` tests; root widened: 1072 set; literal
dropped: 1070, 1075, 1079 set; literal widened: 1072's variable items; braced spelling dropped:
1070 and 1079's second items; prefix dropped: 1079 set and the doctest). `guards.md` — §1 line
29–31, §2 rows 61–62, §3.3 lines 312–322 and 435–439, §7 lines 735–747 (the old line-725
accepted false deny gone, its §8 row at 1006 now a deny with its reason), §8 lines 819–825, §8.2's
preamble agreeing with the test's two `<job>`s. The replay's `--no-job-dirs` branch constructing a
`Location` the M40 checkout accepts, and `session[:8]` naming the job as Claude Code does for both
top-level and `subagents/` transcripts. Not re-run: the gate, the mutations and the live job,
which the brief reports and whose transcript the brief review's rounds 5–6 read.

VERDICT: APPROVED
