# Review — M40-5 build, a documentation run the session spawns

Artifact: the M40-5 build in the working tree against `design/build-plan.md` §"M40-5 — A second
documentation run the harness ran in the foreground, where it could not wait" (lines 7324–7613 at
review time): `zikaron/install/code_knowledge.py`, `zikaron/install/entries.py`,
`zikaron/install/targets.py`, `tests/test_install_code_knowledge.py`,
`tests/test_code_knowledge_reminder.py`, `tests/test_code_knowledge_claude_live.py`, the three
re-rendered snapshots under `tests/fixtures/installed/`, `design/code-knowledge.md` §5.2 and §5.4,
`design/harness.md`, `design/kiro-gaps.md`, `design/overview.md`'s D39 row, `README.md`,
`FINDINGS.md` and `research/m40-5-spawned-orchestrator-probe.md`.

## Round 1 — 2026-10-21

**Summary judgment.** The build is the brief's: Claude Code's skill is a two-line frontmatter and a
launcher whose fenced prompt carries `$ARGUMENTS`, the orchestrator's definition carries its own
prompt, then the loop rendered for Claude Code, with `background: true` and the rewritten
description, kiro's skill carries the loop and its own permissions paragraph, the loop states every
rule of item 3 on both harnesses with the batch at 18, and each invariant in the brief's list has a
test whose named mutation would redden it — I walked each against the text. The documents the brief
names are rewritten, and the by-meaning sweep for "fork", "one run at a time", "runs as", the old
description and "19" finds nothing stale outside the exemptions but one line in `FINDINGS.md`. Two
things keep it from shipping as-is: the loop's glob-and-slice predicate is not the brief's and
contradicts itself in the one case the brief's round 4 fixed, and the orchestrator's new description
puts a `: ` inside a plain YAML scalar — tolerated by the harness today, measured, but rejected by
the repository's own PyYAML drift guard, which does not reach this definition.

### Findings

1. **[IMPROVEMENT] The loop's glob-and-slice predicate is not the brief's, and the loop contradicts
   itself where they differ.** `zikaron/install/code_knowledge.py` lines 327–330 (`_LOOP` step 1):
   *"a run of two or more modules — named, or found registered — given a glob or a slice stops
   here … So a run over registered modules passes no globs, and each of its opening lines says
   `globs: none`."* The brief's item 3 (lines 7442–7447) states the predicate once, as round 4's
   finding 3 asked: *"a run that names two or more modules, or names none and finds any
   `code-knowledge/<module>` registered, refuses a glob or a slice"*. The two differ on a no-module
   invocation in a project with exactly one module registered — `/zikaron-document-code --slice 20`
   after `src` was documented with `--slice 20`, which is how `README.md` line 721 teaches the flag:
   by the first sentence that is "a run of one module", so the slice stands; by the second, "a run
   over registered modules passes no globs". A model reading the orchestrator's body picks one, and
   nothing says which. `design/code-knowledge.md` §5.2 lines 509–511 carries the same wording, and
   the rules test (`tests/test_install_code_knowledge.py` line 446) pins only the bold opening, so
   either wording passes it. **Suggested change**: in `_LOOP` and §5.2, *"a run that names two or
   more modules, or names none and finds any knowledge base named `code-knowledge/…` registered,
   given a glob or a slice stops here, before the planner first runs, and reports it"*; and the
   phrase list's entry becomes that clause rather than the bold heading, so the predicate is what
   the test holds.

2. **[IMPROVEMENT] The orchestrator's description is not valid YAML as a plain scalar, and the
   drift guard that would say so does not read this definition.** `code_knowledge.py` lines 53–57,
   shipped as `tests/fixtures/installed/claude-code/agents/zikaron-code-orchestrator.md` line 3:
   *"description: Runs one documentation run in the background: Zikaron's planner in batches …"*.
   A plain scalar may not contain `: ` — the `targets.py` `_MODEL_ID` comment (lines 82–94) and
   `refuse_unknown_model` (lines 586–613) exist for exactly this class in the `model:` value — and
   `yaml.safe_load` on that line raises *mapping values are not allowed here*. It is not a blocker:
   Claude Code's parser is lenient, measured twice — this repository's own
   `.claude/agents/py-runner.md` line 3 carries the same shape and loads every session, and the live
   test spawned this very definition. But the repository's own standard is a parse by something
   that did not write the text — `tests/test_install_targets.py` lines 341–350,
   `test_both_markdown_artefacts_have_frontmatter_that_actually_parses`, whose docstring and
   `pyproject.toml` lines 99–105 give the reason — and it reads the consolidator's agent and skill
   alone, so the two code-knowledge definitions are green for the wrong reason, and a stricter
   parser in a later harness release would drop the agent with nothing saying why. **Suggested
   change**: one character — *"Runs one documentation run in the background — Zikaron's planner in
   batches and a zikaron-documenter per file …"* — with the snapshot re-rendered; and extend that
   test (or add one beside it) to parse `documenter_agent_markdown` and
   `orchestrator_agent_markdown` with PyYAML, asserting `name`, `tools` and, for the orchestrator,
   `background is True`, so the class is held for every definition the installer writes.

3. **[IMPROVEMENT] One `FINDINGS.md` passage still says the batch is 19, and done-when 2 names the
   file.** Lines 288–290: *"batches of 20, Claude Code's measured concurrency limit, issued
   together (operator, 2026-10-16; spec §5.2) — 19 since 2026-10-20, a slot being still held when
   the next batch goes out (operator)."* "19 since" reads as current truth, and the spec it cites
   now says 18. **Suggested change**: *"— 19 since 2026-10-20, a slot being still held when the
   next batch goes out, and 18 since M40-5, the spawned orchestrator's own"*.

4. **[NITPICK] A module the run never reached has no defined opening line.** `_LOOP` step 8
   (lines 461–465) asks for *"one line per module the run was asked for, each naming the module,
   whether it is up to date, and its knowledge base's name"*, and lists the refused, passed-over
   and `globs: none` cases. A run of several modules that stops on contention (step 4) or on
   *"any other failure of the planner"* (step 1) leaves the modules after it untouched, and the
   rule gives their line nothing true to say. One clause beside the refused module's: *"a module
   the run stopped before reaching saying so"*.

5. **[NITPICK] The launcher's retry can collide with its own queue rule.** `_LAUNCH_BODY` lines
   517–527: a refused spawn *"is made again when the next subagent of this session reports"*,
   while a request *"that comes while a run of yours is out is not spawned then"*. With a run out
   and some other subagent of the session reporting first, the retry fires into a running run.
   Rare — it needs the session's twenty held by other agents — and one clause closes it: *"and
   never while a run of yours is out: the rule above comes first"*.

6. **[NITPICK] `_SKILL_DESCRIPTION` says the skill runs the planner and spawns documenters, which
   under Claude Code the session does not.** Lines 270–276: *"by running Zikaron's planner and
   spawning a zikaron-documenter subagent per file"*. The brief keeps the opening and the body
   overrides it, so this is wording only: *"through Zikaron's planner and a zikaron-documenter
   subagent per file"* is true on both harnesses.

7. **[NITPICK] `_LOOP` interpolates one placeholder and spells the other two.** Line 300 writes
   `{_ARGUMENTS_PLACEHOLDER}` while lines 310 and 382 write `@@PLANNER_COMMAND@@` and
   `@@SPAWN_INSTRUCTION@@` as literals; `_loop`'s survival check reads the constants, so a renamed
   constant would ship the old literal unnoticed. Interpolate all three.

8. **[NITPICK] The passed-over corpus's opening line is stated and not pinned.** `_LOOP` lines
   321–323 give it *"an opening line of its own in the report (step 8) saying whose directory it
   is"*, which round 11's second nitpick asked for; the rules phrase list (lines 437–456) pins
   *"a run that passes over every one documents nothing, and says so"* and not the line. Add the
   clause to the list.

VERDICT: NEEDS_CHANGES

### Author response to round 1

All eight accepted and applied, the snapshots re-rendered, `./check.sh` green (5681 passed) and
`new_line_coverage.py` reporting 25 new statements, 0 uncovered:

1. `_LOOP` step 1 and spec §5.2 state the brief's predicate, and the phrase list pins that clause in
   place of the bold heading.
2. The description's `: ` is now an em dash; `tests/test_install_targets.py` gains
   `test_the_code_knowledge_artefacts_have_frontmatter_that_actually_parses`, which parses the
   documenter, the orchestrator and the skill with PyYAML and asserts `background` on the
   orchestrator alone, its tools, and the skill's two keys — red when the `: ` is put back.
3. FINDINGS' passage says 18 since M40-5.
4. Step 8, and spec §5.2's report sentence, give a module the run stopped before reaching its line.
5. The launcher's retry is never made while a run of the session's is out.
6. `_SKILL_DESCRIPTION` says *"through Zikaron's planner and a zikaron-documenter subagent per file"*.
7. `_LOOP` interpolates all three placeholders.
8. The passed-over corpus's line is in the phrase list.

The mutation sweep, re-run with three more mutations (the `: ` put back, the stopped-before line
dropped, the retry's queue clause dropped), reddens at least one test under every one.

## Round 2 — 2026-10-21

**Summary judgment.** Round 1's eight findings are applied as the response says, and I re-walked
the brief's items 1–6 and every invariant against the current files rather than the response:
`_LOOP` step 1 now states the brief's predicate once and the phrase list pins that clause
(`tests/test_install_code_knowledge.py` lines 447–448); the orchestrator's description is a plain
scalar and `tests/test_install_targets.py` lines 352–367 parse all three code-knowledge artefacts
with PyYAML, asserting `background` on the orchestrator alone and `{name, description}` on the
skill; step 8 and spec §5.2 give a module the run stopped before reaching its line; the launcher's
retry is subordinated to its queue rule; all three placeholders are interpolated. The planner's
`_layout` raises every per-module refusal as `--module …` (`zikaron/code_knowledge/main.py` lines
130–141) and nothing else under that prefix, so the loop's skip rule and the prefix test hold
against the code. The by-meaning sweep of `design/`, `README.md`, `FINDINGS.md`, `zikaron/` and
`tests/` finds no passage outside the brief's two exemptions that still has the skill forking,
held to one run, or batched at 19 — `FINDINGS.md` lines 72, 273–274 and 289–290, the D39 row,
`harness.md` lines 95, 303–307 and 631–633, `kiro-gaps.md` line 24 and `README.md` lines 363 and
719–768 all carry the new truth, and `code-knowledge.md` lines 642 and 1199–1201 are the record
the brief exempts. Nothing material remains; three trivial items below.

### Findings

1. **[NITPICK] The orchestrator's body is not pinned to carry no permissions paragraph.** Brief
   item 2 says the loop is rendered into the definition *"without the permissions paragraph"*,
   and the snapshot confirms it today, but no test asserts it: an `orchestrator_prompt` that
   appended `_IN_SESSION_PERMISSIONS` would ship *"This skill runs in the session that invoked
   it"* inside a background subagent's system prompt and stay green. One line in
   `test_its_body_is_its_own_prompt_then_the_loop` (`tests/test_install_code_knowledge.py`
   line 180): `assert "## Permissions" not in _ORCHESTRATOR_BODY`.

2. **[NITPICK] "this skill's own word" has no referent inside the orchestrator's definition.**
   `zikaron/install/code_knowledge.py` line 305, shipped at
   `tests/fixtures/installed/claude-code/agents/zikaron-code-orchestrator.md` line 48: *"`--slice
   N` is this skill's own word, for documenting only N files this time"* — true of kiro's skill,
   which carries the sentence, and odd in an agent that is not a skill. *"the skill's own word"*
   is true in both renderings; re-render the snapshots after.

3. **[NITPICK] §5.2 cites "the probe note of §5.2" from inside §5.2.** `design/code-knowledge.md`
   line 645: *"and for a spawned subagent in the probe note of §5.2"*. Name it:
   *"and for a spawned subagent in `research/m40-5-spawned-orchestrator-probe.md` §2"*.

VERDICT: APPROVED

### Author response to round 2

The three nitpicks applied after the approval: the orchestrator's body asserted to carry no
permissions paragraph (1); *"the skill's own word"*, the snapshots re-rendered (2); §5.2 names the
probe note (3).
