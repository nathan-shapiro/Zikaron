# Review — M40-1, a background job's own scratch directory

Artifact: `design/build-plan.md` §"M40-1 — A background job's own scratch directory, which the
edit guard called authored" (lines 6538–6615 at the time of round 1), with
`research/claude-code-job-dir-hook-probe.md` as its evidence. Judged against `design/guards.md`
§3.2 (row 6's text), §3.3, §6, §7, §8, §8.1 and `zikaron/guard/scratch.py`, `main.py`, `nudge.py`,
`script_file.py`, `tests/guard_table.py`, `tests/test_guard_rule_table.py`,
`tests/test_guard_properties.py` and `tests/test_guard_main.py` as they stand on
`m40-code-knowledge`.

## Round 1 — 2026-10-20

**Summary judgment.** The mechanism is right against the code: a fourth root on `Location` read
by `main` as `TMPDIR` is, a literal-spelling regex beside `_TMPDIR_LITERAL`, a prefix beside
`_TMPDIR_PREFIX` in `file_path`, and the nudge inheriting all of it through `Location.is_scratch`
— a builder can implement items 1–3 from the brief alone, and the fence and the worktree rule are
sound. What does not hold is the test design in item 4 and the invariants: §8.2's fresh directory
is pytest's `tmp_path`, which on Linux lies under `/tmp`, a fixed root, so the rows the brief
specifies cannot come out as it says on the platform the gate runs on, and the root mutation
cannot be seen red there. One blocker, fixable with a sentence in §8.2's preamble, and several
cheap improvements where the brief leaves a normative sentence, a likely command or the one
environment read untested.

### Findings

1. **[BLOCKER] §8.2's `<job>` directory cannot sit under `tmp_path` and still test the root.**
   Brief item 4 (lines 6570–6573) and the invariants (lines 6587–6593): each row is judged "naming
   a fresh directory into whose `tmp` the test first writes the row's files in §8.1's forms, an
   absolute path to it spelled `<job>`", with `printf x > <job>/tmp/rows.txt` *silent with the
   variable set and a deny without* and `<job>/state.json` *a deny both ways*. §8.1's fresh
   directory is `tmp_path`, and nothing in `check.sh`, `pyproject.toml` or `tests/conftest.py`
   sets `--basetemp` or `TMPDIR`, so on Linux it is `/tmp/pytest-of-<user>/…` — under
   `scratch.py`'s `FIXED_ROOTS` (`"/tmp"`, compared unconditionally) — while on macOS it is
   `/private/var/folders/…/T/…`, under no root once `tmpdir=None` is passed. Consequences, all on
   Linux: `<job>/tmp/rows.txt` and `<job>/state.json` are scratch with the variable **unset**, so
   the two "deny" cells fail; with it **set**, every `<job>/tmp/…` row is silent because of `/tmp`,
   not because of the new root, so the mutation "drop the job directory from `Location.roots`"
   stays green and done-when 1's *seen red* is unreachable for it; and the same rows pass on the
   macOS job, which is the per-machine divergence `test_guard_rule_table.py`'s docstring exists to
   forbid. **Fix, preferred:** split §8.2's payload by whether a row lists files, and say so in its
   preamble. A row listing **no** files is judged with the hook's value `/home/u/.claude/jobs/j` —
   the fake path §8's existing row (`guards.md` line 990) already uses, under no root on either
   platform — and `<job>` stands for that string; a row listing files is judged with `<job>` the
   fresh directory, which is sound because every such row reaches its read through the literal
   `$CLAUDE_JOB_DIR/tmp/…` rule, whose scratch status does not depend on the root, and what the row
   tests is `file_path`'s mapping (set: `<fresh>/tmp/fix.py` read, deny naming `f`; unset: no
   file, silent). Name the columns, since `table_with_columns` matches them exactly and
   `guard_table.py` raises on prose it does not know: `Files in <job>/tmp` | `Command` |
   `Expected, unset` | `Expected, set`. Then restate the invariant list's rows under that split:
   the `printf`, `state.json` and `cd` rows with no files and the fake path; the `fix.py` rows with
   files. **Alternative:** create `<job>` somewhere under no §3.3 root on both platforms and name
   the place — it costs a write outside the test's own tempdir, which is why the split is better.

2. **[IMPROVEMENT] Item 3 points at §8.1 for row 6's read, but the rule is normative in §3.2, and
   item 4 does not list §3.2.** `guards.md` lines 233–236 (§3.2 "Row 6's text"): *"The path is the
   operand's resolved one, except that a leading `$TMPDIR` or `${TMPDIR}` stands for the hook's own
   `$TMPDIR`, and `${TMPDIR:-DEFAULT}` for it or, unset, for `DEFAULT`; any other `${TMPDIR…}`
   names no file."* §8.1's preamble only sets up the files. A builder changing `file_path` as item 3
   says leaves that sentence stating that only `$TMPDIR` is substituted. **Fix:** in the Normative
   line and item 3, cite §3.2 "Row 6's text" (keep §8.1 for the table), and add to item 4: *"§3.2's
   'Row 6's text': a leading `$CLAUDE_JOB_DIR` or `${CLAUDE_JOB_DIR}` stands for the hook's value
   and, unset, names no file."*

3. **[IMPROVEMENT] `cd "$CLAUDE_JOB_DIR/tmp" && …` is a deny both ways and the brief does not say
   so.** `Location.moved_to` resolves the `cd`'s directory through `resolve`, where only a
   command-bound variable is substituted, so the directory becomes `<cwd>/$CLAUDE_JOB_DIR/tmp` and
   every later relative target is authored — the class §7 line 732 and §8 line 1003 state for
   `cd "$TMPDIR" && echo y > f`. The harness names the directory to the job by the variable, and the
   replay's job used the `cd … && cat > stub.py <<'EOF'` shape (§8 line 990), so the variable
   spelling of that shape is likely in the field; and a reader who sees §8.2's absolute `cd` row
   silent will take the variable form to be silent too. **Fix:** item 4 extends §7's clause at line
   732 to name `cd "$CLAUDE_JOB_DIR/tmp" && echo y > f` beside `cd "$TMPDIR"`, and §8.2 carries
   `cd "$CLAUDE_JOB_DIR/tmp" && cat > stub.py <<'EOF'` / `x` / `EOF` — deny both ways, naming
   `$CLAUDE_JOB_DIR/tmp/stub.py` (stated false deny: `DIR` is read as a path). No rule moves,
   which is what §7 and the fence require.

4. **[IMPROVEMENT] The one environment read is untested.** `main()` is the only place
   `CLAUDE_JOB_DIR` is read; §8.2 goes through `respond(job_dir=…)` as `test_guard_rule_table.py`
   does, so a `main` that never passes `os.environ.get("CLAUDE_JOB_DIR")` is green in the suite and
   caught only by done-when 2's single live job. **Fix:** add to the invariants the twin of
   `test_guard_main.py::test_main_reads_tmpdir_from_the_environment` (line 235):
   `setenv("CLAUDE_JOB_DIR", "/home/u/.claude/jobs/j")`, command
   `sed -i 's/a/b/' /home/u/.claude/jobs/j/tmp/f`, no output. And pin the variable unset where §8's
   payload is assumed — `test_guard_rule_table.py`'s `_no_tmpdir` fixture (line 28),
   `test_main_writes_the_rules_output_and_exits_zero` (line 230), and `TestTheRealProcess` (line
   243), whose subprocess inherits the environment — since the gate may itself be run from a
   `claude --bg` job, and then every `main()`-level test runs with the variable set. The payload
   statements in `guard_table.py` line 34 and `test_guard_rule_table.py`'s docstring change with
   §8's.

5. **[IMPROVEMENT] Done-when 2 measures `PreToolUse` only, and the nudge invariant rests on an
   unmeasured half.** The probe's hook was on `Bash` `PreToolUse`; nothing shows the `PostToolUse`
   hook's environment carries `CLAUDE_JOB_DIR`, yet the invariant at line 6596 ("the re-read nudge
   is silent for an edit under the job's `tmp`") is true live only if it does. **Fix:** the same
   job also makes one `Write` to `$CLAUDE_JOB_DIR/tmp/<file>`, and the observation records that no
   re-read attachment follows it (and the variable's presence, from a dumping `PostToolUse` hook
   or the transcript). While there, say what *undenied* is read from, so done-when 2 is checkable
   without interpretation: the file present under the job's `tmp` afterwards, and no
   `PreToolUse:Bash hook error` tool result in the job's transcript.

6. **[IMPROVEMENT] The property test reaches the new literal branch only by accident.**
   `test_guard_properties.py`'s `_FRAGMENTS` spells `/tmp/x` and `Path('/tmp/x')` so the existing
   scratch paths are generated; nothing generates `$CLAUDE_JOB_DIR`, and `st.text(max_size=80)`
   will not. **Fix:** the invariant at line 6595 says both halves — the job directory joins
   `locations` (`st.sampled_from([None, "", "/", "/home/u/.claude/jobs/j", "rel"])`) **and**
   `_FRAGMENTS` gains `"$CLAUDE_JOB_DIR/tmp/x"`.

7. **[IMPROVEMENT] §2's payload row is now false and item 4 does not touch it.** `guards.md` line
   61: *"The payload | Carries `cwd`; carries no scratchpad path"*, under a heading that says every
   row was observed. Item 4 updates §3.3's `(2.1.285 does not)` only. **Fix:** item 4 adds §2's
   row — *"Carries `cwd`; 2.1.285 carried no scratchpad path, 2.1.304 carries `scratchpad_dir`,
   the session's scratchpad under `/tmp` (`research/claude-code-job-dir-hook-probe.md`)"* — so
   the document carries current truth where a reader of §2 would stop.

8. **[NITPICK] §7's own rule turns the fenced edge into a row.** §7 line 756: *"A conceived edge
   becomes a §8 or §9.5 row with the value the rules already give it."* The fence's
   `os.environ['CLAUDE_JOB_DIR']` has a value today: `python3 -c
   "open(os.environ['CLAUDE_JOB_DIR']+'/tmp/x','w')"` is a deny naming no target, both ways (a
   subscript head yields nothing, §3.3 step 5). Optional: one §8.2 row recording it.

9. **[NITPICK] `README.md` lines 503 and 505 enumerate the exempt roots** (*"`/tmp` or
   `$TMPDIR`"*; *"`/tmp`, `/var/tmp` and `$TMPDIR`"*). They already omit `/dev` and the scratchpad,
   so this is a simplification by design; if the list is for someone running background jobs, add
   *"and a background job's `$CLAUDE_JOB_DIR/tmp`"* to line 505. Optional.

Not raised, per the brief: the worktree build, the unchanged start text and deny message, the
literal being scratch in every session, row 6 reading no file when the variable is unset, the
script's own `os.environ` spelling as a rule, kiro, and landing in M40's pull request. Checked and
found correct: item 1 against `Location.roots`/`_usable` and `main._location` (both `_command` and
`_reread` go through it, so the nudge inherits the root); item 2 against `is_scratch`'s order
(`_substituted` before the literal match, so a command that rebinds the variable is read with its
value); staging and running meeting through `_key` with the variable set (`file_path`) and unset
(`resolve`, both spelled `<cwd>/$CLAUDE_JOB_DIR/tmp/fix.py`); `parse_section` ending a `### 8.1`
section at `### 8.2`, and `table_with_columns` keeping §8's two-column reader clear of a
four-column §8.2; "as M38's was" (build-plan line 5927 is inside §M38); and the probe note's
measurements and reading.

VERDICT: NEEDS_CHANGES

## Round 2 — 2026-10-20

**Summary judgment.** Every round-1 finding is applied and checks against the code: the §8.2
split by whether a row lists files is sound (a no-file row's `/home/u/.claude/jobs/j` sits under
no root on either platform, and a file row reaches its file only through the literal spelling, so
each class sees its own mutation red), the §3.2 citation, the `main` environment test, the pinned
`unset` in the three places, the property test's two halves, §2's row and the `cd` false deny are
all where they should be, and the replay's before-counts agree between brief and note. Two things
still stand between this and a brief a builder can execute without deciding anything: done-when
3's nudge observation is vacuous as written — a `Write` that creates a file gets no nudge in any
session, and a literal `$CLAUDE_JOB_DIR` path is scratch in any session — and item 5's "before and
after in one pass" cannot be computed under the new code, whose literal rule has no off switch.
The rest is the §8.2 table's exact shape, which the reader matches byte for byte.

### Findings

1. **[BLOCKER] Done-when 3's `Write` cannot show what it claims.** `nudge.py` line 39 returns
   `None` for a `Write` whose `tool_response.type` is `"create"` *before* `is_scratch` is consulted
   at line 41 — §4's row "a new file has no surroundings", pinned by
   `test_guard_nudge.py::test_a_write_that_creates_a_file_gets_no_nudge`. So "makes one `Write`
   under `$CLAUDE_JOB_DIR/tmp`" (build-plan lines 6639–6642) to a new file is followed by no
   reminder whether or not the `PostToolUse` hook's environment carries the variable, and the
   sentence "which shows the `PostToolUse` hook's environment carries the variable too" is
   satisfied by every outcome. A second hole: if the agent passes the literal
   `$CLAUDE_JOB_DIR/tmp/<file>` as `file_path`, item 2's literal rule makes it scratch in every
   session, again independent of the environment. **Fix:** the `Write` **overwrites** the file the
   `cat > $CLAUDE_JOB_DIR/tmp/…` just created, so its result `type` is `"update"` (§2 line 59), at
   the **absolute** path `/home/<user>/.claude/jobs/<id>/tmp/<file>` — which is scratch only
   through the root `main` reads from its environment — and, as the control that makes a silence
   legible, the same job overwrites one authored file in the throwaway project with `Write` and
   that one's re-read attachment is seen in the transcript. "No reminder after the job-tmp
   overwrite, a reminder after the authored one" is then the observation; without the control, a
   missing attachment is also what §2's fragile-half issues (#19432, #55889, #79616) produce, and
   the done-when cannot tell the two apart.

2. **[IMPROVEMENT] Item 5's "before and after in one pass" is not computable under the new code.**
   Item 2's literal rule is unconditional in `Location.is_scratch`, so judging with the job
   directory withheld under the new tree is not "the rules before": the 37 commands redirecting
   into `$CLAUDE_JOB_DIR…` are already silent there, the before-count comes out below the note's
   261, and "which of the 261 this change clears" (line 6555) needs the before *set*, not a count.
   Recovering it in one pass would need a switch in production code for an experiment's sake.
   **Fix** (lines 6592–6595 and done-when 2): the script judges every such command under the rules
   of the tree it runs in, with each job's directory, and `--dump`s the set; the worktree
   arrangement already gives both runs — the main tree's `.venv` is the pre-change code until the
   worktree's gate is green, so run it there for the before set, which must reproduce the note's
   261, and from the worktree's `.venv` for the after set — and done-when 2 reads the difference and
   classes what remains. One sentence in each place.

3. **[IMPROVEMENT] §8.2's exact shape, since the reader matches it byte for byte and raises on
   what it does not know.** (a) **The header strings.** `table_with_columns` compares the tuple
   exactly, and a bare `<job>` in a Markdown table header is raw HTML — GitHub strips the unknown
   tag and renders "Files in /tmp" — so the header is written as §8.1 writes its own:
   ``Files in `<job>/tmp` `` with the backticks, and the brief gives the four strings as
   `guard_table.py` will spell them (line 6582 currently leaves the backticks ambiguous: the
   brief's own code formatting or the header's text). (b) **A row with no files.** §8.1 never has
   one; `_items("")` yields `[""]` and `_scratch_file("")` raises — say the files cell is blank and
   the reader takes a blank cell as no files. (c) **`<job>` in a command cell.** Write the no-file
   rows with the literal `/home/u/.claude/jobs/j`, as §8's row at `guards.md` line 990 already
   does, so the reader substitutes nothing and `<job>` is only the header's and the preamble's
   word for the value a row is judged with; file rows never need it, since they reach their file
   through the literal spelling. (d) **How the value reaches the rule.** The test passes the job
   directory through `respond`, which gains `job_dir` beside `tmpdir` as `_emit` passes `tmpdir` —
   not through the environment, which the `main` test alone covers; "once with `CLAUDE_JOB_DIR`
   unset and once set" (line 6583) reads as the latter.

4. **[NITPICK] The `os.environ['CLAUDE_JOB_DIR']` row's value is left for the builder to
   discover** (lines 6614–6615, "with the value the rules give it today"). State it: deny naming
   nothing, both ways — the target expression's head is the unbound name `os`, and
   `['CLAUDE_JOB_DIR']` and `+'/tmp/x'` are chain and tail after it (§3.3 steps 4 and 6;
   `expression.py`'s `_chain` reads a subscript as a link) — so the row is checkable against the
   brief rather than against whatever the first run prints.

5. **[NITPICK] The fence's "**Not** re-installed anywhere"** (line 6651) contradicts done-when 3,
   which installs the guards into the throwaway from the worktree's `.venv`. Say "not re-installed
   in the three projects that run this tree".

Checked and found correct, beyond the round-1 applications: every §8.2 row's expected value
against `scratch.py`, `script_file.py` and `decision.py` — the literal rows both ways through
`_TMPDIR_LITERAL`'s twin; the absolute rows through `roots`; `tmpx/a` and `state.json` not under
`<job>/tmp`; `cd "$CLAUDE_JOB_DIR/tmp"` through `moved_to` → `resolve`, which substitutes only a
command-bound variable, so the directory becomes `<cwd>/$CLAUDE_JOB_DIR/tmp` and the deny names
`/home/u/proj/$CLAUDE_JOB_DIR/tmp/stub.py`, which "naming `$CLAUDE_JOB_DIR/tmp/stub.py`" asserts
through `normalise(path, cwd)`; the file rows set (`file_path`'s new prefix → `<fresh>/tmp/fix.py`
→ `read_script` → deny naming `f`) and unset (`file_path` → `None` → `_text` → `None` → silent),
with the set case red if item 3's `file_path` change is missing (`<cwd>/$CLAUDE_JOB_DIR/tmp/fix.py`
is read and absent) and the `${…}` spelling red if `is_scratch`'s second literal branch is missing;
the nudge inheriting the root through `main._location`; `_key` keeping staging and running
together under both spellings; and the note's before-counts, table and text classes, against the
brief's.

VERDICT: NEEDS_CHANGES

## Round 3 — 2026-10-20

**Summary judgment.** Every round-2 finding is applied and holds against the code: done-when 3's
`Write` overwrite at the absolute path with the authored overwrite as its control, item 5's two
runs through `--no-job-dirs` and a `PYTHONPATH` checkout, §8.2's four header cells with the
backticks on the first, the blank files cell, the literal `/home/u/.claude/jobs/j` in command
cells, `respond`'s `job_dir`, the `os.environ` row's value and the narrowed fence. I also checked
three things the brief asserts about the field against the other projects' transcripts (this
repository's excluded, as the replay excludes them): nothing outside this repository writes to a
job-directory path other than `tmp`, which is the evidence "`tmp` alone" rests on; the
`cd`-through-the-variable shape exists and none of it carries a form the rule denies, so item 4's
sentence is exact; and the one observed command that writes a *relative* path inside a Python body
after a `cd` into a job's `tmp` is cleared by the new root, because row 4 judges a body's write
calls under the location in force at its opener. What is left is one observed shape §7's own rule
wants as a §8.2 row, with its shell twin that the root does not reach, and nitpicks.

### Findings

1. **[IMPROVEMENT] An observed job-tmp shape no listed §8.2 row covers, and its shell twin whose
   value differs.** LeibaTrader session `9792ce89` (2026-08-30, `sessionKind: bg`) ran
   `cd /home/nathan/.claude/jobs/9792ce89/tmp && python3 - <<'PY'` / `p="tf_decomp.py";
   s=open(p).read()` / … / `open(p,"w").write(s)` / `PY` — one of the replay's 707, denied before
   naming the job's `tmp` path (so one of the 128) and silent after: `all_matches` passes `here`,
   the location after the `cd`, to `match_pipeline`, and row 4's `script_targets(script,
   location)` (`forms.py` lines 132–135) resolves the bound `p` against it, into the root. Every
   row the invariants list (build-plan lines 6612–6624) spells its target on the command's own
   line; none shows the root reached through a body, and §7 line 751 says an edge found becomes a
   row. **Its twin has the other value**: `cd /home/u/.claude/jobs/j/tmp && bash <<'EOF'` /
   `echo y > f` / `EOF` is a deny naming `f` **both ways**, because a scanned shell body is a unit
   apart that starts from the payload's `cwd` (`decision.py` lines 109 and 122, §3.3's last
   sentence on `cd`), so the root never reaches it — and a reader of the `cd J/tmp && cat >
   stub.py` row (silent set) would take the body form to be silent too. Not in the field (no shell
   body with a write after such a `cd` in the other projects' transcripts), so a conceived edge
   with the value the rules give, which is what §7 asks a row to record. **Fix:** two no-file rows
   in the invariants' §8.2 list: `cd /home/u/.claude/jobs/j/tmp && python3 - <<'EOF'` /
   `p = 'fix.py'; open(p, 'w')` / `EOF` — unset, deny naming `/home/u/.claude/jobs/j/tmp/fix.py`;
   set, silent (the observed shape; a body's write is judged where the `cd` left the command) —
   and `cd /home/u/.claude/jobs/j/tmp && bash <<'EOF'` / `echo y > f` / `EOF` — deny naming `f`
   both ways (stated: a scanned body starts from the payload's `cwd`, §3.3). Optionally, item 4
   adds the second to §7's false-deny clause at line 728 beside "a `cd` the rules do not follow".

2. **[NITPICK] §1's determinism sentence names what fixes the answer and item 4 does not list
   §1.** `guards.md` lines 29–31: *"The same payload, the same `$TMPDIR` (§3.3), the same platform
   (§9) and the same contents of that script always give the same answer."* After item 1 the
   answer also depends on `$CLAUDE_JOB_DIR`; `test_guard_properties.py`'s docstring (lines 3–4)
   says the same. Add §1 to item 4's list with "the same `$TMPDIR` and `$CLAUDE_JOB_DIR`".

3. **[NITPICK] §8's payload sentence lists its exceptions and §8.2's file rows are now one.**
   `guards.md` lines 804–809 end "…and §8.1's rows, which do read files, to the last". Item 4
   restates the payload with `CLAUDE_JOB_DIR` unset; say there that §8.2's file rows are the
   exception to that too, and to the no-file-read clause, as §8.1's are.

4. **[NITPICK] The replay's selector and the note's description of it differ, harmlessly today.**
   `experiments/m40_1_job_dir_replay.py` lines 35–36 select `CLAUDE_JOB_DIR` or the literal
   `/home/nathan/.claude/jobs/`; the note (line 36) says "a path under `~/.claude/jobs/`". The `~`
   spelling is in the field (LeibaTrader `9792ce89`: `~/.claude/jobs/9792ce89/tmp/tier3.log`,
   `…/ExperimentApp.scala.pristine`, in `cp`/`ls`-class commands), and no `>` or `tee` write
   names it, so widening the selector to `~/.claude/jobs/` and `$HOME/.claude/jobs/` changes no
   count — either widen it or have the note say the selection is by the variable and the absolute
   path. Moves no decision; recorded so the next reader does not re-derive it.

5. **[NITPICK] Done-when 3 does not say how the job's tool calls are permitted.** The probe allowed
   `Bash(echo:*)`; this job needs the `cat` heredoc, `Write`, and the `Read` an overwrite requires.
   Either list the allow rules or run the job under `--permission-mode bypassPermissions`, under
   which §2 measured that the deny still holds and `PostToolUse` context arrives; a background job
   that stops at its first approval is a run spent.

6. **[NITPICK] The nudge invariant (lines 6634–6635) names no red twin.** Say: the same `Edit` of
   `/home/u/.claude/jobs/j/tmp/x` with `job_dir` none gets a nudge, so dropping the root is seen
   red, as done-when 1 asks of every new test.

Checked and found correct, beyond the round-2 applications: the before-counts 707 / 243 / 128 / 42
agreeing between brief and note, and the script's `--no-job-dirs` branch passing no `job_dir`, so
the M40 checkout's `Location` accepts the call; `classify` reading `$CLAUDE_JOB_DIR/tmp` in a
resolved path, which is how a `cd` through the variable would have shown in the after-count; the
draft worktree's shape matching items 1–3 (`_JOB_DIR_VARIABLE`, `job_dir` defaulting to `None` on
`respond`, root `f"{job_dir}/tmp"` through `_usable`) — not reviewed, only confirmed as what the
counts came from; the `cd`-through-the-variable shape in the field — five
`cd $CLAUDE_JOB_DIR/tmp && python3 - <<'EOF'` in the deny session `86ba5119`, four
`cd $CLAUDE_JOB_DIR/tmp 2>/dev/null || cd /home/nathan/.claude/jobs/ce5d0813/tmp; …` and several
`cd "$CLAUDE_JOB_DIR/tmp/jarx…"` in `ce5d0813` — none with a form the rule denies; no
`CLAUDE_JOB_DIR/<anything but tmp>` in a command outside this repository's transcripts; the no-file
rows' values both ways through `moved_to` → `resolve` and `_substituted`; the `${CLAUDE_JOB_DIR}`
file row reaching `file_path`'s second spelling; and `tests/test_design_pointers_resolve.py`'s
`POINTER` form (`` `x.md` §"…" ``) not reaching the brief's bare "§8.2", so the forward reference
to a section item 4 adds is not red on the main tree.

VERDICT: NEEDS_CHANGES

## Round 4 — 2026-10-20

**Summary judgment.** Every round-3 finding is applied and holds against the code, and the
replaced invariant is the right one: a job directory of `""` or `/` yields `/tmp`, already a fixed
root, so no test can see that check, while an un-normalised trailing slash does break the root —
`is_under` compares against `root.rstrip("/") + "/"`, and `…/j//tmp` never prefixes `…/j/tmp/x`.
Items 1–3, the §8.2 shape, the invariants' values, done-when and the fence are implementable from
the brief alone. One normative paragraph the change leaves contradicting the sentence it amends,
and four nitpicks.

### Findings

1. **[IMPROVEMENT] §3.3's closing paragraph is left reasoning about the scratchpad as if no
   payload named it.** `guards.md` lines 425–427: *"On macOS … where the scratchpad sits is
   unmeasured; if it is under `$TMPDIR` it is exempt by the same rule, and if not, writes there are
   a false deny the override answers."* Item 4 (build-plan lines 6574–6575, *"its note on
   `scratchpad_dir`, which 2.1.304 sends"*) reads as line 310's parenthetical; after that edit §3.3
   says in one place that 2.1.304's payload carries `scratchpad_dir` — which makes the scratchpad
   a root wherever it sits — and in another that writes to it on macOS may be false denies. A
   builder working from item 4's list leaves the second standing. **Fix:** item 4 names both
   places, and the paragraph becomes: *"2.1.304's payload names it as `scratchpad_dir` (measured
   on Linux, `research/claude-code-job-dir-hook-probe.md`), so it is exempt wherever it sits;
   under a version that sends none, if it is under `$TMPDIR` it is exempt by the same rule, and if
   not, writes there are a false deny the override answers."* One clause; no rule moves.

2. **[NITPICK] The pin list reads as exhaustive and omits one fixture.** Build-plan lines
   6635–6637 name *"the rule table's fixture, `test_main_writes_the_rules_output_and_exits_zero`,
   and `TestTheRealProcess`"*; `tests/test_guard_selfmatch_table.py` lines 51–53 carry the same
   `_no_tmpdir` fixture under the same payload (its docstring, line 3: *"judged as §8's are …
   `$TMPDIR` unset"*). Harmless — `respond` reads no environment, so only `main()`-level tests
   can see the variable — but say "both table fixtures" or name it.

3. **[NITPICK] The Normative line omits §1**, which item 4 edits (line 6573). Add *"§1's
   determinism sentence"* at line 6540.

4. **[NITPICK] Item 3's "names no file" is unobservable through the hook, so pin it at the
   unit.** With the variable unset, a `file_path` that answered `<cwd>/$CLAUDE_JOB_DIR/tmp/fix.py`
   instead of `None` opens a path that does not exist and is silent too, so §8.2's unset column
   cannot tell the two apart and no mutation names it. `scratch.py` lines 106–108 already pin the
   `$TMPDIR` case by doctest (`unset.file_path("$TMPDIR")` → `None`); add
   `unset.file_path("$CLAUDE_JOB_DIR/tmp/a")` beside it, and the invariant can say so.

5. **[NITPICK] Have done-when 2's sample settle the fence's reason.** The fence (lines
   6671–6672) declines `os.environ['CLAUDE_JOB_DIR']` because a rule *"moves only on an observed
   command (§7)"*, while the note (lines 57–58) says several of the nine unresolvable writes reach
   the job's `tmp` *"through a Python variable"*. Done-when 2 already reads a sample of that
   class; add that the note says whether any of the nine spells the variable's read, so the
   reason is either confirmed (unobserved) or replaced (observed and declined on purpose), and the
   next brief does not re-derive it.

Checked and found correct, beyond the round-3 applications: the python-body row through
`all_matches` (the `cd` is its own pipeline, `here` moves before the heredoc pipeline is judged,
and `script_targets` resolves the bound `p` against it) and the shell twin through `top.walk()`
resetting `here = location` per unit; §8's row at `guards.md` line 990 staying a deny under the
payload's unset variable and agreeing with §8.2's unset column; `_split_row` taking a blank first
cell as one empty cell, so a four-cell row with a blank files cell parses; the corpus grep showing
only `guards.md` and `README.md` enumerate the roots (no `harness.md`, `architecture.md` or
`overview.md` row to update); the deny message's partial list (`messages.py` lines 28–29) being
pre-existing and held fixed by the brief; the counts summing both ways (243 = 128+42+55+16+2,
138 = 108+21+9, the 65 moved from the false to the true classes being the staged-and-run scripts
the note's reading describes); the `${CLAUDE_JOB_DIR}` file row reaching the second spelling in
both `is_scratch` and `file_path`; a command-bound `J=$CLAUDE_JOB_DIR` reaching the literal rule
through `_substituted`; and both evidence files the brief cites existing on this tree.

VERDICT: NEEDS_CHANGES

## Round 5 — 2026-10-20

**Summary judgment.** Every round-4 finding is applied and holds: §3.3's closing paragraph is in
item 4's list, both table fixtures are named, §1 is on the Normative line, "names no file" is
pinned at the unit — where it does run, since `tests/test_guard_docstring_examples.py` doctests
every `zikaron.guard` module through `pkgutil.iter_modules` — and the note says none of the nine
unresolvable denies reads the environment. The new done-when 3 agrees with the job it records:
in `3650c925`'s transcript the two `cat`s ran with no hook-error result, the job-tmp `Write` is
followed by no attachment and the worktree `Write` by one. Two things short of a brief that needs
no further decision: the field's commonest job-tmp shape — a script staged there and run in the
same command, which is the mechanism the replay's reading names — has no §8.2 row, and done-when
3 does not say the job-tmp `Write` must be seen to succeed, which the refusal it now records makes
a second way for its silence to be vacuous.

### Findings

1. **[IMPROVEMENT] The staged-and-run shape through the job's `tmp` has no §8.2 row in either
   spelling, though it is observed and is what the note's reading rests on.** Note lines 53–56:
   the true classes grow because *"a command denied before for staging a script in the job's
   `tmp` is now judged for what the script does"* — and under a replay with no file read that can
   only be a script staged and run in one command. It is in the field in both spellings and both
   words: LeibaTrader `9792ce89` ran `cat > $CLAUDE_JOB_DIR/tmp/run_pz.sh <<'EOF'` … `EOF` /
   `bash $CLAUDE_JOB_DIR/tmp/run_pz.sh` (several, `run_delayed.sh`, `run_flip.sh`, `run_to.sh`
   among them) and `cat > /home/nathan/.claude/jobs/9792ce89/tmp/revert_gate.py <<'EOF'` … `EOF`
   / `python3 /home/nathan/.claude/jobs/9792ce89/tmp/revert_gate.py` (and `boost_bracket.py`,
   `start_report14.sh`). Every row the invariants list (build-plan lines 6617–6635) is a staging
   alone, a `cd` then a staging, an inline body, or the run of a file that exists; none stages and
   runs. §7 line 751 makes an observed shape a row, and the absolute one has a red of its own the
   silent/deny rows lack: with the root dropped, the deny names the job path (row 5) instead of
   `f` (row 6). **Fix:** two no-file rows in the invariants' §8.2 list — `cat > J/tmp/fix.py
   <<'EOF'` / `open('f', 'w')` / `EOF` / `python3 J/tmp/fix.py`: unset, deny naming
   `J/tmp/fix.py` (row 5, the before-state; row 6's operand is not scratch); set, deny naming `f`
   (row 5 exempt; row 6's text is the staged body, met through `_key`) — and its variable twin
   `cat > $CLAUDE_JOB_DIR/tmp/fix.py <<'EOF'` / `open('f', 'w')` / `EOF` /
   `python3 $CLAUDE_JOB_DIR/tmp/fix.py`: deny naming `f` both ways, staging and run meeting
   through `_key` under both spellings (`file_path` set, `resolve` unset), and red for a missing
   literal branch, which would name `$CLAUDE_JOB_DIR/tmp/fix.py` under the `cwd` instead.
   Checked against `decision.all_matches` (the `staged` dict is filled after each pipeline and
   read by the next), `script_file.ScriptRuns._text` (a staged body is taken before `read` is
   consulted, so a no-file row suffices) and `_assert_deny_message` (the message names the first
   denying form's targets: row 5's in pipeline one when unset, row 6's `/home/u/proj/f` when
   set). Optionally the shell word's twin, `bash J/tmp/fix.sh` over `sed -i 's/a/b/' f`, the
   observed `run_*.sh` shape.

2. **[IMPROVEMENT] Done-when 3 does not require the job-tmp `Write` to be seen succeeding, and
   the refusal it now records is a way for it not to.** Build-plan lines 6665–6672: the inference
   *"the job-tmp overwrite by none, which shows the `PostToolUse` hook's environment carries the
   variable too"* holds only if that `Write` ran — a `Write` the harness refuses fires no
   `PostToolUse` — and the same done-when now records 2.1.304 refusing a background session's
   `Write` until `EnterWorktree`. Neither it nor the note's "Live" section (lines 78–81) says the
   job-tmp `Write`'s result was a success or where it fell relative to `EnterWorktree`. The
   transcript does: `3650c925` line 57 is the `Write` of
   `/home/nathan/.claude/jobs/3650c925/tmp/group_book.py`, line 59 its result `"type":"update"`,
   `EnterWorktree` comes after it, no `is_error` appears anywhere, and the file holds `print(3)`
   — so the refusal is of the checkout only and the job's own directory needs no worktree.
   **Fix:** in done-when 3, after "an update, which §4 nudges where a creation it never does",
   add *"its result seen in the transcript as `type` `update`, since a `Write` the harness
   refuses fires no `PostToolUse`"*; in the note's second "Live" bullet, *"its result `type`
   `update`, before `EnterWorktree`: the refusal is of the shared checkout, not of the job's own
   directory"*. One clause each; nothing re-runs.

3. **[NITPICK] One number, two quantities.** Build-plan line 6553 says *"707 distinct `Bash`
   commands"*; the note's table (line 44) counts *"707 distinct (command, `cwd`) pairs"*, which is
   the measurement — one command under two `cwd`s is two pairs. Say "distinct (command, `cwd`)
   pairs" in the brief.

Checked and found correct, beyond the round-4 applications: the live job's order and results —
`cat` at transcript lines 25–26 with no `PreToolUse:Bash hook error` result and both files on
disk, `Write` at 57 with `update` at 59, the worktree `Write` at 76 with `update` at 78 and the
`PostToolUse:Write` `hook_additional_context` at 79–81, the only attachment in the transcript;
that the nudge control is also what makes the `cat` silence legible — both guard groups come from
the one `settings.local.json`, so the control's `PostToolUse` firing excludes a session that loaded
no hooks, and no deny control is needed; `state.json`'s `cwd` is the checkout and `worktreePath`
the worktree under `<project>/.claude/worktrees/`, inside the project and under no root, so the
control's nudge is the rule's; the job-tmp path being scratch only through the root
(`scratchpad_dir` is the session's under `/tmp`, `TMPDIR` unset in the hook's environment); the
`m40-before` worktree existing for item 5's before-run and `design/kiro-gaps.md` for the fence's
citation; and one fact worth knowing outside this brief — a job that enters a worktree files its
transcript under the worktree's project key
(`projects/-home-nathan-ZikaronTesting-m40-1-jobdir--claude-worktrees-…`), which the note's
replay covers by reading every project's transcripts, and which §7's per-`<project>` counts would
miss.

VERDICT: NEEDS_CHANGES

## Round 6 — 2026-10-20

**Summary judgment.** All three round-5 findings are applied and hold against the code as it
stands on `m40-code-knowledge`: the staged-and-run rows (build-plan lines 6627–6631) come out as
the brief says — with the root absent, pipeline one's row-5 match is the first denying form and
names `J/tmp/fix.py`; with it present that match is exempt and pipeline two's row 6 takes the
staged body through `_key`, naming `/home/u/proj/f`; both variable spellings meet through
`file_path` set and `resolve` unset, so `f` both ways, and a missing literal branch names the
`$CLAUDE_JOB_DIR/tmp/fix.py` path under the `cwd` instead — done-when 3 now requires the job-tmp
`Write`'s result seen as `type` `update` and the note's live bullet places it before
`EnterWorktree`; and the brief counts (command, `cwd`) pairs as the note does. Items 1–5, the
§8.2 shape, every invariant's value, done-when 2–4 and the fence are implementable from the brief
without a further decision. What is left is one wording wrinkle in done-when 1, below the bar
for holding the brief.

### Findings

1. **[NITPICK] Done-when 1 says "the mutation it names", and the §8.2 rows name none.**
   Build-plan line 6656 against lines 6616–6638: the `main` twin, the normalization invariant and
   the nudge invariant each imply their mutation, but a table row is a test that names no
   mutation, so "seen red" for §8.2 is satisfied by whichever mutations the builder picks — the
   brief's author ran the root dropped and the literal dropped, which leave item 1's "`tmp`
   alone" and item 2's "followed by anything else is not" unexercised as mutations, though the
   `state.json` and `tmpx/a` rows would be red in the normal run under either widening.
   **Fix, one sentence after the §8.2 bullet:** *"The table's mutations: the root dropped from
   `roots` and widened to `<job>`; the literal dropped from `is_scratch` and widened to
   `$CLAUDE_JOB_DIR/…`; `file_path`'s prefix dropped — each turning at least one row red."*
   Optional; nothing a builder does changes without it.

Checked and found correct, beyond the round-5 applications: the `bash` spelling of the
staged-and-run row through `ScriptRuns.__call__` → `_script_text_matches` → `all_matches` over
the staged body with `read=None`, row 1's `sed -i … f` resolving from `in_child()`'s unchanged
`cwd`, and `script_operand` taking a `$`-initial token as the operand; a `cat` heredoc body not
being walked as a unit (§8 line 1014's `cat > /tmp/fix.sh … / /tmp/fix.sh` row is silent), so
the `sed -i` in that body is denied only through row 6, as the brief says; `is_exempt` filtering
pipeline one's row-5 match when its one target is under the root, so the set-case message names
row 6's `f` and nothing else; §4 pointing at "§3.3's test" rather than enumerating roots, §5
naming no environment variable, and `design/harness.md` carrying no guard-environment row, so
item 4's document list is complete; `tests/` holding no `main()`-level guard test outside the
brief's pin list (`_run_main`'s callers and `TestTheRealProcess`; `test_hook_components.py`'s
`main()` is the memory hook's); the fence's reason confirmed by the note (none of the nine
unresolvable denies reads `os.environ`/`getenv`), as round 4's nitpick 5 asked; and the
replay's counts summing both ways. Not reviewed, as the brief directs: the build worktree, the
replay script (absent from this tree) and the modified files outside §M40-1.

VERDICT: APPROVED
