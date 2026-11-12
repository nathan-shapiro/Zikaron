# M43 — instruction push to teammates and subagents — brief and build review

Artifacts: `design/build-plan.md` §"M43 — Push for an agent given an instruction: a teammate's
message and a subagent's prompt" (lines 9030–9363 at round 1), and the build in the worktree
`/home/nathan/Zikaron-m43` (branch `m43-instruction-push`, uncommitted against `567b4dd`). The
brief's own five rounds are in `reviews/m43-instruction-push-brief-review.md` and are not repeated.

## Round 1 — 2026-11-09

**Summary judgment.** The build does what the brief says, and the facts it rests on hold when
re-derived rather than read: both probe logs (under tmux the lead's session fires no
`SubagentStart`, `SubagentStop` or `TeammateIdle`, so no stray lead marker; in-process
`SubagentStop` once per turn), the real meta file (`agentType: mate-1`, `customAgentType` and
`spawnedAgentType: probe-mate`, in the order the seam tries them), the real
`<teammate-message teammate_id="team-lead" summary="…">` wrapper the regex assumes, a real
LeibaTrader ordinary-subagent transcript whose prompt is a string-content first record (the one
shape the probe did not measure and the fixtures assume), `shlex.split` of the gate putting the
hook path as the token after `exec`, and `EVENT_SPECS` validating at write only, so an upgraded
store's `occasion`-less rows are untouched. Every invariant the brief lists but one has a test that
fails on the obvious mutation, and the design prose agrees with the code everywhere I compared
them. What stops me approving is not the mechanism but its coexistence with the installs the four
real projects already carry: through the editable `.venv` the new hook code reaches them at the
merge, where `SubagentStart` will tell every subagent that headlines arrive with its first tool
call while no gate exists to deliver them, and will set markers nothing claims or sweeps — and
nothing in `FINDINGS.md` says to re-install. One sentence and one line close it. The rest is
measurement hygiene and wording.

### Findings

1. **[IMPROVEMENT] The new hook code against an un-reinstalled settings file tells subagents a
   falsehood and grows `instruction-pending/` without bound.** `FINDINGS.md` §"Where the stores
   are": the four real projects run this repository's `.venv`, so the merge puts
   `zikaron/hook/subagent_policy.py` line 50 (`pushed = spec.instruction_push is not None and
   known_as not in agents.NEVER_PUSHED`) behind their *existing* `SubagentStart` entry, which
   then delivers `PUSHED_AGENT_WRITE_POLICY_PROMPT` — "A block of headlines arrives with your first
   tool call after each instruction" — into every subagent while their `settings.local.json`
   carries no gated `PreToolUse`: the false first sentence `design/write-policy.md` §2 (lines
   119–122) says the subagent text exists to avoid. And `instruction_push.mark` (lines 57–81) runs
   on their existing `SessionStart` and `SubagentStart` entries, writing one marker per session and
   per spawn, while `instruction_markers.sweep` runs only from `run` (line 94), i.e. only behind
   the gate they do not have, and the `SubagentStop` that would clear them is the third missing
   entry — so the directory gains an empty file per session, per subagent spawn and per in-process
   teammate message until someone re-installs. The same holds for any user who upgrades the
   package without re-running the installer. *Fix, three parts, each a line:* (a) `FINDINGS.md`
   §"Current state" names, after the merge, re-running `python -m zikaron.install --project .
   --harness claude-code --components both` in the four projects, and `design/distribution.md`
   says an upgrade is followed by a re-install if it does not already; (b) `instruction_push.mark`
   sweeps on `SPAWN` with `source: startup` before marking, so growth is bounded to a session's
   worth whatever the settings file carries — one call plus a `TestMarkers` cell "a session start
   removes a marker past its limit", and brief item 2's "Any `TOOL_CALL` run that lists the
   directory deletes…" (line 9102) gains "and every `SessionStart` that marks"; (c) optionally,
   `zikaron doctor` reports a memory install whose settings lack the gate
   (`design/distribution.md` §"what `doctor` checks"), which is the only thing that would make the
   mismatch visible to a user rather than to this project.

2. **[IMPROVEMENT] A lagging transcript after a reply-only turn pushes the previous instruction
   silently, and done-when 2 does not record the one fact that would let the rule close.** Brief
   item 4 (lines 9143–9149) covers lag with the `tool_result` rule, which catches it only when the
   prior turn made a tool call. After a reply-only turn — 1 of 3 messages in each probe run — the
   tail is `user(msg1)`, `assistant(text)`; if `msg2` and the current turn are not yet written when
   `PreToolUse` fires (the docs' caveat, `research/claude-code-agent-teams-hooks-docs.md` line 50),
   `_latest_records` (`zikaron/hook/instruction.py` lines 59–84) collects `msg1` and pushes it under
   `msg2`'s marker with no `hook.log` line — the outcome item 4 says it fails closed on. The
   likelihood is low: the probe found the message present at `SubagentStart` 3 of 3, a model
   round-trip before the first call (`research/teammate-hook-probe.md` lines 43–45). The evidence
   that the transcript is current is the current call's own `tool_use` record, which the fixtures
   assume is there (`tests/transcript_records.py`, every tail) and nothing measured at `PreToolUse`
   time. *Fix, a measurement only, no code now:* done-when 2 (lines 9336–9348) records, for each
   instruction push, whether the transcript's trailing `assistant` records already hold a
   `tool_use` block at `PreToolUse` — and whether the payload carries a `tool_use_id` to match it
   by. If it always does, a later change makes a tail with no `tool_use` block `Unread`, with the
   fixture that specifies it; if it does not, §"Agent teams" records that the transcript can lag the
   call and the reply-only cell is a stated loss.

3. **[IMPROVEMENT] `FINDINGS.md` §"Current state" carries what `CLAUDE.md` §"Project memory" sends
   nowhere, and a "Next" that is already false.** Lines 96–107 of the worktree's `FINDINGS.md`:
   "five review rounds", the mutation count and how the mutation script had to be run ("on
   full-tree copies, since a package-only copy is shadowed by the checkout's own"), and
   "**Next**: `./check.sh` and `experiments/new_line_coverage.py`" — both done, per this brief. A
   fresh session resuming from this block would re-run the gate as its first act. *Fix:* reduce the
   block to what a fresh session acts differently without — the worktree and branch, that the
   build is complete and reviewed, and the three things owed: done-when 2's operator-driven live
   run (with the `default`-mode cell for `design/guards.md` §2 and the facts finding 2 adds),
   done-when 3's cost measurement, and the re-install of the four projects (finding 1). The round
   count and the mutation story go nowhere; the review file and the scratchpad already hold them.

4. **[NITPICK] The brief's invariant list and item 13 disagree on which harness's snapshots carry
   the no-name rule.** Item 13 (lines 9271–9274, changed after round 5): "in their Claude Code text
   — kiro's spawn instructions are separate, and kiro has no agent teams". The invariant (lines
   9314–9315): "through the re-rendered snapshots on both harnesses". The test
   (`tests/test_install_spawn_names.py`) reads `tests/fixtures/installed/claude-code/` only, which
   is right. *Fix:* the invariant → "through the re-rendered Claude Code snapshots".

5. **[NITPICK] The byte-identical invariant is listed and not tested.** Line 9316: "The same
   instruction and store push byte-identical blocks (`coding-standards.md` §4)"; §4 (lines 228–231)
   asks for a test that runs the operation twice and asserts byte-identical output.
   `tests/test_hook_instruction.py` has no such test, and `test_hook_instruction_push.py` stubs
   the service. *Fix:* one test running `latest()` twice over the two-message fixture and asserting
   equality — the reader is the only new code on the path, the service half being the prompt
   path's — or strike the line from the brief; one or the other.

6. **[NITPICK] Where the backward run stops is stated more narrowly than the code does it.** Brief
   item 4 (lines 9134–9136) and `zikaron/hook/instruction.py` lines 4–5: "every such record back to
   the `assistant` record preceding them". `_latest_records` also stops at a list-content `user`
   record once a string record is held (lines 77–78), which is what makes a prior turn ending on a
   `SendMessage` call — `assistant(tool_use)`, `user(tool_result)`, `user(<teammate-message>)` —
   yield the message alone, pinned by `test_an_earlier_turns_tool_result_ends_the_instruction`.
   *Fix:* "back to the `assistant` record, or the list-content `user` record, preceding them", in
   both places.

7. **[NITPICK] `design/harness.md` §"Agent teams" omits that every main session pays one hook run
   for a marker it never uses.** Lines 374–381 say `SessionStart` with `source: startup` sets a
   marker; brief item 2 (lines 9091–9093) says this is every main session's too, cleared by its
   first tool call. The design document is the normative one, and a reader of it would not expect
   `zikaron-hook` to start on a main session's first tool call. *Fix:* in the marker bullet, after
   "by `SessionStart` with `source: startup`": "— a tmux teammate's spawn, and every main session's,
   whose first tool call claims it at the cost of one hook run".

VERDICT: NEEDS_CHANGES

## Round 2 — 2026-11-09

**Summary judgment.** Every round-1 finding is applied as described, and I re-checked each at its
site rather than from the brief: the `SessionStart` sweep (`instruction_push.mark` line 78–81, pinned
by `test_a_session_start_removes_a_marker_past_its_limit`), the three owed items in `FINDINGS.md`
lines 90–96, the Claude Code-only invariant, the byte-identical test, item 4's list-content stop,
and harness.md's marker bullet. The mechanism is sound against the probe and the code: the gate's
`shlex` split, the ownership widening, the per-event marker table, the backward read's stop rules
and the consolidator-by-definition exclusion each match the brief, and the `SessionStart`-consolidator
invariant I could not find in round 1 is `test_hook_components.py` line 150. What keeps this from
approval is two small docs–code gaps that the brief's own intent — "a builder or reader could rely
on any one of them" — makes material: the normative harness document still says `SubagentStart` is
policy-only, which item 2 made false, and the third policy text has none of the drift guard the
other two have. Both are minutes of work.

### Findings

1. **[IMPROVEMENT] `PUSHED_AGENT_WRITE_POLICY_PROMPT` has no drift guard against its design fence
   and no budget test.** `zikaron/hook/write_policy.py` lines 17–21 say a test "parses that document
   at test time and compares it against these constants"; `tests/test_hook_write_policy.py` compares
   `WRITE_POLICY_PROMPT` (line 32) and `SUBAGENT_WRITE_POLICY_PROMPT` (line 36) and parametrizes
   `test_every_shipped_policy_fits_every_harness` (lines 360–370) over those two only. The third text
   is assembled by string-joining at `write_policy.py` lines 157–168, and `design/write-policy.md`
   lines 233–260 (`### Pushed agent`) is a hand-typed second copy of it — the exact two-copies drift
   the docstring says the test exists to prevent, and the one variant this milestone adds. *Fix:*
   `PUSHED_HEADING = "### Pushed agent"`; `test_pushed_agent_prompt_matches_the_design_document_exactly`
   asserting `fenced_code(DOCUMENT, PUSHED_HEADING, "") == PUSHED_AGENT_WRITE_POLICY_PROMPT`; add the
   constant to the fits-every-harness parametrize with id `pushed`; and extend
   `test_the_two_variants_differ_only_in_how_memory_reaches_the_reader` to the third — its text after
   the `Search with zikaron_memory_search` marker equals the others', and "arrives with your first
   tool call" is in it. `write-policy.md` line 116's "Three variants" then has three guards.

2. **[IMPROVEMENT] Three places still say `SubagentStart` carries the policy and nothing else, which
   item 2 falsifies.** `hook/main.py` line 59–61 puts `SUBAGENT_START` in `_MARKED`, so the trigger
   now sets an instruction marker before the policy. Stale: `design/harness.md` lines 102–106 ("under
   Claude Code alone the subagent start, which carries the policy and nothing else, and the search
   reminder's `PostToolUse`" — which also omits `PreToolUse`, `TeammateIdle` and `SubagentStop` from
   the trigger vocabulary it is describing); `design/harness.md` line 336 ("The `SubagentStart` path
   is **policy-only**"); `zikaron/hook/subagent_policy.py` lines 1 and 4–5 ("deliver the write policy
   to a subagent, and nothing else" / "does nothing more"); and `tests/test_hook_main.py` lines
   401–402's docstring ("Policy-only: no warm helper spawn, no push" — the assertions are still
   right). *Fix:* lines 102–106 → "…the subagent start, which carries the policy and sets an
   instruction marker, the search reminder's `PostToolUse`, and the instruction push's `PreToolUse`,
   `TeammateIdle` and `SubagentStop` (§"Agent teams")"; line 336 → "The `SubagentStart` path is
   policy and marker only: it does *not* spawn the warm helper…"; the module docstring → "`SubagentStart`'s
   policy half: deliver the write policy to a subagent. The marker it also sets is
   `instruction_push.mark`'s, called from `main.py`"; the test docstring → "Policy and marker only".

3. **[NITPICK] A `>` inside a `<teammate-message>` `summary` attribute pollutes the pushed
   instruction rather than failing closed.** `zikaron/hook/instruction.py` line 143: `[^>]*>` ends
   the opening tag at the first `>`, so `summary="step a -> b"` — a five-word model-written summary
   with an arrow is not exotic — makes the captured body ` b">\nBody`, which is then embedded as the
   query. The measured shape puts the body on the line after the tag (`tests/transcript_records.py`
   line 56). *Fix:* `re.escape(message_opening) + r"[^\n]*?>\n(.*?)" + re.escape(_CLOSING)` — the tag
   ends at the first `>` that ends a line, which a `>` inside an attribute never does; a body on the
   tag's own line then yields `UNWRAPPED` and an `instruction_unread` line, as a shape not measured
   should. One fixture with an arrow in the summary pins it.

4. **[NITPICK] Done-when 2's mid-task cell names two outcomes where the reader has three.** Brief
   lines 9344–9348: "If at delivery, that message's push is the mechanism's loss — claimed by the
   running turn's next call with an `instruction_unread` line, or cleared by its `SubagentStop` with
   none". `_latest_records` (`instruction.py` lines 59–84) gives `RESULT_AFTER` only when the message's
   record is *not yet* in the transcript when that call fires; if it already is, the tail is
   `user([tool_result])`, `user(<msg>)`, `assistant(tool_use)`, the list-content record ends the run
   *after* the message is collected (lines 77–78), and the message is pushed by the running turn —
   early, silently, and never again. `~/Memory`'s n=2 suggests the record waits for the turn, so this
   is probably not real; but the live run's classification should be total. *Fix:* add the third
   outcome to that sentence — "or, where the message's record is already in the transcript, pushed by
   that call ahead of the turn that handles it, told by a push with no `instruction_unread` line
   whose `surface_call` precedes the turn's end" — so whoever drives done-when 2 can file what they see.

VERDICT: NEEDS_CHANGES

## Round 3 — 2026-11-09

**Summary judgment.** Every round-2 finding is applied, and I checked each at its site: the third
policy text has its drift guard, its budget cell and its variants cell (`tests/test_hook_write_policy.py`
lines 31–59, 373–376); the trigger-vocabulary paragraph and the `SubagentStart` paragraph say policy and
marker (`design/harness.md` lines 102–107, 337); the opening-tag regex ends at a `>` that ends its line,
with the arrow and inline-body fixtures (`instruction.py` line 146; `test_hook_instruction.py` lines
94–108); done-when 2's mid-task cell names three outcomes; and `_is_protocol` reads the body's first line
with its fixture. The gate's cost is measured, re-derivable, and like-for-like with the figure it is set
against (both through `subprocess.run`, `owed-measurements-2026-10-30.md` §5). The mechanism is sound
against the probe, the docs note and the code everywhere I compared them, with one exception that the
brief's own intent makes material: item 4 defines who is served by the transcript's first record, and the
code defines it by a string `agent_type` first — the two part ways for a tmux teammate spawned with no
type, the default spawn shape, which the code drops with no `hook.log` line. That, the cost note's stated
control, and a resume block that says "Next: the next milestone" above "In progress: M43" are what keep
this from APPROVED. All three are small.

### Findings

1. **[IMPROVEMENT] A tmux teammate spawned with no `subagent_type` is served by the brief and dropped,
   silently, by the code.** Brief item 4 (lines 9127–9130): without an `agent_id` the transcript is
   `transcript_path` itself, "served only when its first `user` record whose content is a string begins
   `<teammate-message`" — the transcript's shape is the whole test. The code tests `agent_type` first:
   `instruction_push._instruction` (lines 126–137) calls `agents.definition`, which for an `agent_id`
   that is not a string returns `agent_type if isinstance(agent_type, str) else None` (`agents.py` lines
   42–43), and on `None` returns with no line, since the line is written only for a string `agent_id`.
   Item 5 (lines 9163–9164) says a tmux teammate's `agent_type` "is its definition, measured" — measured
   for `probe-mate`, a *typed* teammate (`research/teammate-hook-probe.md` line 64). The docs give
   `agent_type` as "Present when the session uses `--agent` or the hook fires inside a subagent"
   (`research/claude-code-agent-teams-hooks-docs.md` line 48); a tmux teammate is a `claude` process of
   its own, so one spawned with `name` and a prompt alone — the common shape in a user's team — has no
   `--agent` and, on the docs' rule, no `agent_type`. Its message is then never pushed, and item 4's
   "for every cause but the first one `hook.log` line" (line 9156) is false of it: a transcript this path
   serves, by item 4's definition, leaves no trace. The exclusion loses nothing by the change: the
   consolidator is spawned with `subagent_type: zikaron-consolidator` by its skill, so the cell that
   carries no `agent_type` cannot be the consolidator, and the main session is still told apart by
   `_opens_with_a_message` (its first string record is the operator's prompt), which is what
   `test_a_main_session_is_never_pushed_and_logs_nothing`'s `agent_type=None` row already pins. *Fix,
   one of two, and the brief and code must agree either way:* (a) in `_instruction`, require `named` only
   where `agent_id` is a string — `if named is None and isinstance(agent_id, str): _record(...); return
   None`, then `if named in agents.NEVER_PUSHED or not isinstance(session_transcript, str): return
   None` — so a typeless no-`agent_id` payload falls through to `latest(main_shaped=True)`; add
   `test_a_tmux_teammate_with_no_type_is_pushed_its_message` (the tmux message transcript,
   `agent_type=None`); and done-when 2 spawns one tmux teammate with no `subagent_type` and records
   whether its tool events carry `agent_type`; or (b) keep the code's cell and have item 4 say that a
   no-`agent_id` payload with no `agent_type` is not served, with an `instruction_unread` line, since the
   marker is claimed. (a) is the one that matches what the brief already promises.

2. **[IMPROVEMENT] Done-when 3's named control is not the one the note measured, and the harness-side
   floor is unstated.** Brief lines 9365–9367: "the `PreToolUse` command run with no marker, against a
   control with no `PreToolUse` entry". `research/teammate-hook-probe.md` §"The gate's cost per tool
   call" measures three arms through `subprocess.run` from Python — the gate line, `sh -c true`, and the
   ungated hook — and headlines "0.17 ms over a bare shell", the delta against a floor, while the
   per-prompt figure (10–27 ms) correctly uses the whole 0.82 ms. Neither is "against no entry": what the
   harness itself pays to run an entry at all — its spawn from Node, which shell it uses (a login shell's
   start is tens of milliseconds, not one), the payload's serialization and the await — is outside a
   measurement that spawns `/bin/sh` from Python, and this is the first entry with **no matcher**, so it
   pays that floor on every tool call where the guards' `PreToolUse` paid it on `Bash`/`Monitor` alone.
   `CLAUDE.md`: "name the quantity before quoting a number about it". *Fix, prose only:* (a) the brief's
   done-when 3 first part states what was done — "the gate line against `sh -c true`, the floor any entry
   pays, and against the ungated hook, each through `subprocess.run` as `owed-measurements-2026-10-30.md`
   §5 timed the existing hooks"; (b) the note's closing paragraph names the harness's own per-entry cost
   as unmeasured, bounded by what the guards' `Bash|Monitor` entry already pays per matched call, and
   says the second part — hook processes per tool call from done-when 2's sessions — is where its
   multiplier is read; (c) `FINDINGS.md` says which part remains (finding 3).

3. **[IMPROVEMENT] `FINDINGS.md`'s resume block contradicts itself and is stale on done-when 3.** Lines
   81–82: "**Next: the next milestone, chosen from there with the operator.**", directly above line 84's
   "**In progress: M43**" — a fresh session reads "Next" first. Line 93: "**Done-when 3**, the gate's
   cost, measured as `CLAUDE.md` requires." — its first part is done and in the note. *Fix:* lines
   81–82 → "**Next: finish M43 (below); then the next milestone, chosen from there with the operator.**";
   line 93 → "**Done-when 3's remaining parts**, from done-when 2's sessions: hook processes each new
   entry started against the tool calls and turns made, and a `TOOL_CALL`'s wall time on the largest
   transcript they leave — the gate line's own cost is measured (`research/teammate-hook-probe.md`
   §"The gate's cost per tool call")."

4. **[NITPICK] Brief item 5 names a function the build no longer has.** Lines 9179–9181: "today
   `_is_consolidator` tests `SubagentStart` alone, so it would be given the main policy and the guard
   start text". `hook/main.py` has `_known_as` (lines 169–178) and no `_is_consolidator`; a reader
   checking the brief against the code finds nothing. *Fix:* "before this milestone the consolidator
   check ran on `SubagentStart` alone, so such a session was given the main policy and the guard start
   text; it now emits neither…".

5. **[NITPICK] The invariant list names a nested-documenter fixture that does not exist, and item 4
   disagrees with it on what was measured.** Lines 9302–9304: "a documenter spawned by the orchestrator,
   whose transcript sits flat beside its parent's under the root session's `subagents/`, as
   LeibaTrader's do" — no test in `test_hook_instruction.py` or `test_hook_instruction_push.py` is that
   case. Item 4 (lines 9143–9146) says "measured at depth 1 and assumed deeper", where the invariant's
   "as LeibaTrader's do" reads as measured at depth 2. The code has no nesting-specific path
   (`InstructionPush.agent_file` is the same for every `agent_id`), so *either* strike the fixture from
   the list and keep item 4's sentence, *or* add the one test — an agent whose record names
   `zikaron-documenter` under the root transcript: no push, no line — which is what pins "flat under the
   root" as the assumption the code makes. Round 1 finding 5 was this class.

6. **[NITPICK] The push-side exclusion test omits the orchestrator.** `tests/test_hook_instruction_push.py`
   line 278 parametrizes `CONSOLIDATOR_AGENT_NAME` and `DOCUMENTER_AGENT_NAME`; removing
   `ORCHESTRATOR_AGENT_TYPE` from `agents.NEVER_PUSHED` (lines 24–26) fails nothing on the push path —
   only the policy side covers it (`test_hook_subagent_policy.py` line 89). *Fix:* add
   `ORCHESTRATOR_AGENT_NAME` to that parametrize.

7. **[NITPICK] `write_policy.py`'s docstrings still count two texts.** Line 1: "transcribed from
   `design/write-policy.md` §2's two fences"; `read_policy` lines 282–284: "the main-agent text, or the
   subagent one for an agent the push never reaches. A single override replaces both";
   `resolved_policy_text` line 339: "`subagent_policy` passes the subagent one". Line 10 already says
   three. *Fix:* "three fences"; "the main-agent text, the pushed-agent text, or the subagent one…
   replaces all three"; "`subagent_policy` passes one of the other two".

8. **[NITPICK] A constraint of the tool-description class is missing from `FINDINGS.md` §"Facts that
   constrain".** The pushed-agent policy sits at 2,976 of the 3,000 units
   `test_every_shipped_policy_fits_every_harness` allows under kiro (the brief's own changed-since note),
   so a sentence added to it must be paid for — the same fact the entry for the knowledge tools'
   descriptions records at 1,896 of 1,900. One bullet beside it.

VERDICT: NEEDS_CHANGES

## Round 4 — 2026-11-09

**Summary judgment.** Every round-3 finding is applied, and I re-checked each where it lives rather than
from the brief: `_instruction` requires a definition only where `agent_id` is a string
(`zikaron/hook/instruction_push.py` lines 133–137), the tmux push test runs typed and untyped
(`tests/test_hook_instruction_push.py` lines 318–334), brief item 5 and `design/harness.md` lines 403–406
say so, done-when 3 names the arms the note measured and the note names the harness's per-entry cost as
unmeasured, `FINDINGS.md` lines 81–100 resume correctly, item 5 no longer names `_is_consolidator`, the
push-side exclusion test covers the orchestrator, `write_policy.py` counts three texts, and the 2,976-unit
fact is in §"Facts that constrain". The brief, the design documents and the code agree everywhere I
compared them, including the `occasion` chain (`dispatch.py` lines 342–376, `schema.md` line 693,
`architecture.md` lines 1291–1301). Two things keep it from APPROVED, both small: the one cell item 5
calls "the one dependency that fails toward a push" — a consolidator under tmux, no `agent_id`, named by
`agent_type` — has no test on the push path, and a mutation that scopes the exclusion to the `agent_id`
branch passes the suite; and the live-run kit, the deliverable for done-when 2, collects none of the
payload-level facts done-when 2 lists, so a run driven with it as it stands would have to be repeated.

### Findings

1. **[IMPROVEMENT] The tmux-consolidator cell is unpinned on the push path.** Brief item 5 (lines
   9172–9176) names it as the one cell that fails toward a push, done-when 2 spawns it ("once more under
   each backend told to spawn it by name"), and the code handles it at `instruction_push.py` line 136 —
   `if named in agents.NEVER_PUSHED or not isinstance(session_transcript, str): return None`, reached with
   `named = agent_type` when `agent_id` is absent. No test exercises that path with a `NEVER_PUSHED`
   `agent_type`: `test_an_excluded_definition_is_never_pushed_whatever_its_type_says` (lines 278–293) goes
   through a meta file with an `agent_id`; `test_a_main_session_is_never_pushed_and_logs_nothing` (lines
   305–316) uses `memory-researcher`; `test_hook_components.py` line 150 is the `SessionStart` policy, not
   the push. The mutation that passes the suite: move the `NEVER_PUSHED` test under `if isinstance(agent_id,
   str)` — every agent-id test still refuses, every tmux test still pushes, and a consolidator spawned by
   name under tmux, whose transcript opens with `<teammate-message`, is pushed five headlines chosen over
   the whole store, the search D7 withholds. *Fix:* in `TestWhoIsPushed`, after the tmux teammate test,
   `test_a_tmux_consolidator_is_never_pushed_and_logs_nothing`: the session transcript as the tmux test
   writes it, `_mark(project, None)`, `assert _call(project, session_transcript, None,
   agent_type=CONSOLIDATOR_AGENT_NAME) is None`, `surfaced == []`, `_hook_log(project) == ""`, and
   `_pending(project) == set()` (the marker is claimed, as item 5 says). Parametrize over the three
   `NEVER_PUSHED` names so the documenter and orchestrator cells, which the same line decides, are pinned
   too.

2. **[IMPROVEMENT] `experiments/m43_live_run.py` cannot record most of what done-when 2 asks to be
   recorded, so the run it drives would be repeated.** Done-when 2 (brief lines 9359–9369) lists, beside
   what the transcripts hold: the consolidator's `agent_type` on its tool events under each backend; an
   untyped tmux teammate's `agent_type` (the kit spawns one, lines 94–98, and nothing reads what its
   events carry); whether the meta file exists at a spawn's `SubagentStart` and at its first tool call;
   whether `SubagentStart` fired at delivery or at handling for the mid-task message; whether it fired for
   the resume; and whether the `PreToolUse` payload's `tool_use_id` names the trailing `tool_use` block;
   plus "each session's permission mode is recorded" (line 9342). Every one is a hook-payload or
   hook-time fact, and the kit installs only Zikaron's hooks (`setup`, lines 119–133), none of which logs
   a payload; `analyze` (lines 196–226) reads transcripts, the store, `hook.log` and the markers left.
   Its `_tool_use_already_written` (lines 183–193) answers the lag question by record order in the file
   after the fact, which is a proxy for what the hook saw, not the observation. And its
   `<-- CONSOLIDATOR PUSHED` flag (line 210) keys on a meta-file definition, which a consolidator spawned
   by name under tmux — a session of its own, no meta file — never has, so the one cell item 5 fails
   toward is the one the flag is silent on. Teams run interactively only, so each cell missed is operator
   time. *Fix, in the kit only:* (a) `setup` writes a second, logging entry into the scratch project's
   `.claude/settings.json` beside the `env` key (lines 138–139) — `SessionStart`, `SubagentStart`,
   `SubagentStop`, `TeammateIdle` and an unmatched `PreToolUse`, each a small Python script as
   `teammate_hook_probe.py`'s `HOOK_SOURCE` (lines 95–124) already is — appending to `DIR/hooks.jsonl` one
   line of `{ts, hook_event_name, session_id, agent_id, agent_type, permission_mode, tool_name,
   tool_use_id, meta_exists, transcript_last_type}`, where `meta_exists` tests
   `<transcript_path stem>/subagents/agent-<agent_id>.meta.json` and `transcript_last_type` is the `type`
   of the last record of the transcript the payload names (the agent's file where `agent_id` is set),
   read at hook time; (b) `analyze` prints, per `SubagentStart`, its `ts` beside the `ts` of the
   teammate's preceding `PreToolUse`/`SubagentStop` (delivery vs handling), and per `PreToolUse` that
   found a marker, `tool_use_id`, `transcript_last_type` and `meta_exists`; (c) the consolidator flag also
   fires for a transcript whose `tool_use` blocks name `mcp__zikaron-consolidator__*`, which is how a
   tmux consolidator's session is told from the lead's. A second `PreToolUse` entry costs the scratch
   sessions one extra process per call and changes nothing Zikaron's own entries do.

3. **[NITPICK] `design/harness.md` and `overview.md` D32 name the fail-open cell more narrowly than the
   brief, and the untyped cell now adds a second route to it.** `harness.md` lines 406–408: "**The typed
   cell is the one that fails toward a push**: a build putting a tmux teammate's name in `agent_type` …";
   brief item 5 line 9172: "**The no-`agent_id` cell is the one dependency that fails toward a push**";
   `overview.md` line 216: "named by its session's `agent_type`, should a later build put a name there".
   Since round 3's fix (a), a build that *omits* `agent_type` from a `--agent` session's tool events
   would reach the same cell by the other door — no type, transcript opening with `<teammate-message`,
   pushed — and done-when 2's record of the consolidator's `agent_type` is the one measurement that
   catches both. *Fix:* harness.md → "**The no-`agent_id` cell is the one that fails toward a push**: a
   build putting a tmux teammate's name in `agent_type`, as in-process does, or sending none for a
   `--agent` session, would let a consolidator spawned by name under tmux through"; overview.md D32 →
   "should a later build put a name there, or none".

4. **[NITPICK] An empty block is emitted as an envelope rather than as nothing.** `block.render` returns
   `""` for no rows (`core/retrieval/block.py` lines 127–128); `instruction_push._surface` returns it
   (line 188); `main._run` tests `is not None` and `_emit` wraps it as
   `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": ""}}`. On the prompt path
   the same `return block` (`push.py` line 153) writes `""` to stdout, which *is* "prints nothing at all";
   on the structured channel it is a record the harness may attach. *Fix:* `return block or None` at
   `instruction_push.py` line 188, and one cell in `TestALostPushLeavesATrace` or `TestDispatch`: a
   service answering `""` leaves `hook.log` empty and emits nothing.

VERDICT: NEEDS_CHANGES

## Round 5 — 2026-11-09

**Summary judgment.** Every round-4 finding is applied and I re-checked each where it lives: the three
excluded tmux cells are pinned with no request, no line and the marker claimed (`test_hook_instruction_push.py`
lines 336–359, and the key order the D7 cell rests on at `test_hook_agents.py` line 57); the kit writes its own
logging hook and `analyze` prints what it saw; harness.md and overview.md name both routes to the no-`agent_id`
cell; `_surface` returns `block or None` with its test. The mechanism, the brief and the design documents
agree everywhere I compared them, the gate's cost is stated for what it measured, and `distribution.md` §3
line 375 carries the release-note rule item 10 cites. Three things keep this from APPROVED, none a blocker:
the normative install-contract table still describes a memory install as four triggers where the installer
writes seven; the trigger-to-marker wiring in `main.py` is pinned for one event of four, so a one-line
mutation that turns off every tmux teammate's later pushes passes the suite; and the live-run kit's
consolidator flag would fire on the lead in the in-process run, the one line the run exists to keep clean.

### Findings

1. **[IMPROVEMENT] `design/harness.md` §"What a Claude Code install writes" omits the three entries this
   milestone writes, and its summary sentence counts four triggers.** The table (lines 918–930) has rows
   for the prompt, start, search-reminder and guard entries and none for what `claude_hooks_value` adds at
   `zikaron/install/entries.py` lines 411–417 — `PreToolUse` and `SubagentStop` gated, `TeammateIdle` plain;
   lines 952–953 then say "A memory install's hook entries are a trigger each for the start, the prompt, the
   subagent start and the search reminder." `tests/test_install_components.py` lines 217–225 asserts seven
   triggers, and `README.md` line 391 lists all seven. The brief names §"The installer's two targets" as
   normative for item 10, and this is its subsection; a reader of it would not learn that a memory install
   puts a hook entry on every tool call. *Fix:* a row after "Search reminder entry": `| Instruction push
   entries | the same file's `PreToolUse` and `SubagentStop`, each the gate line, and `TeammateIdle`, plain |
   memory | `zikaron-hook` behind a shell check that starts it only while a marker of this session's is
   pending (`entries.instruction_gate_command`, §"Agent teams"); `TeammateIdle` ungated, since it sets a
   marker where none exists |`; and line 952 → "…the subagent start, the search reminder, and the
   instruction push's `PreToolUse`, `SubagentStop` and `TeammateIdle` (§"Agent teams")."

2. **[IMPROVEMENT] The trigger-to-marker wiring is tested for one event of the four.** `hook/main.py`
   lines 59–61 put `SPAWN`, `SUBAGENT_START`, `TEAMMATE_IDLE` and `SUBAGENT_STOP` in `_MARKED`. The only
   dispatch-level marker assertion is `TestDispatch.test_a_subagent_start_marks_its_agent`
   (`test_hook_instruction_push.py` lines 546–560); `TestMarkers` (lines 132–203) calls
   `instruction_push.mark` directly, and `test_the_marker_only_triggers_reach_no_other_path`
   (`test_hook_main.py` lines 422–431) asserts that nothing *else* runs and nothing about the marker. So
   removing `HookEvent.TEAMMATE_IDLE` from `_MARKED` — after which a tmux teammate's every later message is
   never pushed, since nothing sets its marker — passes the suite, as does removing `SUBAGENT_STOP` (no
   in-process marker is ever cleared before its TTL) or `SPAWN` (no tmux spawn is marked). *Fix:*
   parametrize that `TestDispatch` test over the four cells through `main_module._run`: `SessionStart` with
   `source: startup` → `{SESSION}`; `SubagentStart` with `agent_id` → `{SESSION}.{AGENT}`; `TeammateIdle`
   with no `agent_id` → `{SESSION}`; and `_mark(project, AGENT)` then `SubagentStop` with `agent_id` →
   `set()`.

3. **[IMPROVEMENT] The kit's consolidator flag fires on the lead of the in-process run.**
   `experiments/m43_live_run.py` lines 251–254: `_calls_the_consolidators_tools` is
   `CONSOLIDATOR_TOOL_PREFIX in path.read_text(...)`, a substring over the whole file. The in-process run's
   step 5 is `/zikaron-consolidate`, whose expansion lands in the lead's transcript as an `isMeta` record
   naming all four verbs with that prefix (`tests/fixtures/installed/claude-code/skills/zikaron-consolidate/SKILL.md`
   lines 16–17 and 31), and the lead always has pushes, since `_pushes` (lines 224–235) counts every
   `hookEvent` including its `UserPromptSubmit` ones — so lines 290–291 print `<-- CONSOLIDATOR PUSHED` against
   the lead, a false alarm on the one assertion done-when 2 exists to keep clean ("none to the consolidator").
   The same substring is in any transcript whose tool result quotes the consolidator's report. *Fix:* parse
   the records and test `tool_use` blocks — `block.get("type") == "tool_use" and
   str(block.get("name", "")).startswith(CONSOLIDATOR_TOOL_PREFIX)` — which the lead never calls (the skill
   says the verbs are not its); and raise the flag only on pushes whose `hookEvent` is the tool trigger,
   since the lead's prompt pushes are D12's and not this milestone's.

4. **[NITPICK] The kit gives beta one later message where done-when 2 says two.** `LATER` (kit lines
   106–111): alpha gets two later messages, one mid-task; beta one, reply-only. Brief lines 9337–9338:
   "each teammate given a spawn message and two later messages, one of them sent while it is mid-task".
   Beta's one message is the reply-only cell item 6 wants counted, so the brief is the side to fix:
   "one teammate given a spawn message and two later messages, one sent while it is mid-task, the other a
   spawn message and one reply-only message".

5. **[NITPICK] Item 6 promises a figure done-when 2 does not list and the kit does not compute.** Line
   9208: "done-when 2 records the longest block one delivered"; done-when 2's "Recorded beside them"
   (lines 9359–9369) omits it and `_pushes` keeps line and event only. With a three-record seed no block
   approaches 10,000 units, so the figure would say nothing about the cap. *Fix:* strike the clause — the
   sentence already says the cap is unmeasured on a tool event, which is the true state.

6. **[NITPICK] The logger cannot tell a missing transcript from an empty or unparseable one, and
   `analyze` prints the file-order proxy unlabelled beside the hook-time fact.** `LOGGER` lines 41–52:
   a missing file, an empty file and a `ValueError` on any line (the comprehension aborts whole) all record
   `last=None`, while done-when 2 (line 9362) asks whether the transcript exists at the first tool call.
   *Fix:* a `transcript_exists` field and a per-line parse that sets `partial_tail` when only the last line
   fails. Line 293's `tool_use already written before each` is record order in the file after the fact
   (round 4 finding 2); label it "in file order" so it is not read as the logger's `tool_use_written`.

7. **[NITPICK] The instruction is read before the divergence check, where the prompt path checks
   first.** `instruction_push.run` lines 101–109 call `_instruction`, which may write `instruction_unread`,
   before `sessions_diverge`; `push.py` lines 96–104 and `architecture.md` lines 1170–1171 make the
   divergence check the first thing after the relay. On a misdetected harness this path writes a line the
   prompt path would not. *Fix:* move the label and divergence block above `_instruction`; the claim stays
   first.

8. **[NITPICK] Item 5 quotes the wrong population for the meta-file measurement.** Lines 9163–9164:
   "measured over the two teams' meta files and LeibaTrader's 936"; `research/teammate-hook-probe.md`
   lines 36–37: "LeibaTrader's 400 most recent". 936 is item 13's count of recorded subagent spawns (line
   9283). *Fix:* "LeibaTrader's 400 most recent".

VERDICT: NEEDS_CHANGES

## Round 6 — 2026-11-10

**Summary judgment.** The round-5 findings are applied where they live (the four-cell dispatch test at
`test_hook_instruction_push.py` lines 546–569, the install-contract row, the kit's `tool_use`-block check
and labelled proxy, the divergence check ahead of the read), and the resume fix is right: `_resumed`
keys on `origin.kind` and the two harness lines, fails to `UNWRAPPED` on any other wording, and I
confirmed against the second in-process run's transcripts that the records around it are what the
fixtures say — a spawn's second `user` record is an `isMeta` system reminder the reader passes over,
the response's records are absent at a first call (`api-request` is the last record, a type the reader
skips), and two quick messages do land as two wrappers in one record separated by a blank line. The
mechanism, the live runs and the design agree, and nothing I found produces a wrong push. What keeps
this from APPROVED is the record: `FINDINGS.md` still owes a live run that has been done four times,
the brief records one of done-when 2's four results inline and leaves the other three as open
questions, and a harness fact the runs found — the lead's prompt hook firing on a subagent's report —
is in the research note alone while it accounts for a number two sections leave unexplained. One
two-line reorder also loses a tmux teammate's message after a day idle, silently, in the exact case the
TTL's rationale names.

### Findings

1. **[IMPROVEMENT] `FINDINGS.md` owes a live run that is done.** Worktree `FINDINGS.md` lines 89–93:
   "Owed after the review: **Done-when 2, the live run, with the operator** … its `default`-mode cell
   fills `design/guards.md` §2's row, and its results join `research/teammate-hook-probe.md`." All of
   that is done — four runs, four sections of the note (lines 120–222), the §2 row filled (`guards.md`
   line 61). A fresh session resuming here would set up a fifth run. Lines 94–97 (done-when 3's
   remaining parts) are still owed and correctly listed: the note has no process count or wall-time
   figure (`grep -n 'wall time\|processes each' research/teammate-hook-probe.md` finds only the forward
   reference at line 117). *Fix:* drop the done-when 2 bullet; the paragraph above it says the runs are
   done and where (`research/teammate-hook-probe.md` §"M43 live run, in-process" and the three after
   it), and that the resume shape they found is served; keep the done-when 3 and re-install bullets.

2. **[IMPROVEMENT] The brief records one of done-when 2's results and leaves three as questions.**
   Lines 9360–9363 record the resume result inline ("In-process it fired, and the prompt was the
   `isMeta` record item 4 now serves"), which is the right treatment for a brief the build writes. Three
   others the runs answered are still phrased as open: (a) line 9352's assertion "the lead's pushes
   only at its typed prompts" — the lead also pushed on each subagent report (`research/teammate-hook-probe.md`
   lines 219–222: `origin: {kind: peer}` fires the lead's `UserPromptSubmit`, three of three), which is
   what makes the in-process and tmux sections' "ten of `prompt`" (lines 131, 188) against the kit's
   eight steps (`_steps`, lines 186–191) come out: eight typed, two helper reports; (b) lines
   9354–9360, the mid-task message: measured waiting for the turn's end under both backends, n=1
   each (lines 189–191, 215–218); (c) lines 9369–9374, whether the trailing `assistant` records held
   the call's `tool_use`: never at a first call (0 of 51), the instruction itself on disk every time — so
   the "Always" branch's change is impossible and the "not always" branch's stated loss did not occur,
   since what lags is the response's records and not the instruction. *Fix:* after each, one sentence in
   the resume paragraph's form, and for (c) say which consequence follows: none, the reply-only cell is
   measured not to lose, and §"Agent teams" lines 405–413 already state the lag correctly.

3. **[IMPROVEMENT] A harness fact the runs found is in the research note and not in the normative
   document.** `design/harness.md` has no mention of `peer` or a subagent's report (grep); the fact
   that a subagent's report back to its session is a `user` record of origin `peer` and fires the
   session's `UserPromptSubmit` — so D12's prompt hook pushes on text the operator did not type, once
   per subagent report, and opens the lead's turn, resetting the reminder time item 9 kept instruction
   pushes from touching — lives only at `research/teammate-hook-probe.md` lines 219–222. `FINDINGS.md`
   §"Facts that constrain": "`design/harness.md` is normative for every harness-coupled fact". It is
   also unaccounted for in the two sections whose `prompt` counts it explains (finding 2a). *Fix:* one
   sentence in §Subagents (line 275, after "`UserPromptSubmit` does not fire for subagents") — "It does
   fire for the *session* when a subagent reports back: the report is a `user` record of origin `peer`
   and the prompt hook pushes on it, three of three in M43's default-mode run (2.1.311); a teammate's
   message to the lead fires nothing" — with the in-process and tmux sections saying "eight typed and
   two subagent reports"; and a `FINDINGS.md` §"Live design questions" line, since it is a D12 decision
   the operator has not taken: keep it (a report is a new turn for the lead) or not, noting the
   payload carries no `origin` so the hook cannot tell a report from a prompt without reading the
   transcript. Optionally, for the next run, `UserPromptSubmit` joins the kit's `LOGGED_EVENTS` (line
   85) so `analyze` can reconcile `prompt` rows against typed prompts at hook time.

4. **[IMPROVEMENT] The sweep deletes the marker the call was about to claim.** `instruction_push.run`
   lines 98–100: `sweep(store_dir, now=…)` then `claim(store_dir, marker)`. A tmux teammate's own
   marker is set by its last `TeammateIdle` and waits for the next message; one older than
   `PENDING_SESSION_TTL_SECONDS` (86,400 s) is deleted by the sweep in the very hook run its message's
   first tool call started, so `claim` returns `False`, the push is lost, and no line is written (the
   claim-failed branch is the parallel-batch case, deliberately silent). A team left idle overnight and
   messaged the next afternoon is the case brief item 2 (lines 9105–9107) names as the limit's reason —
   "waits on a message that may come hours later". Claiming first loses nothing: a marker present at its
   own agent's call is that agent's whatever its age, and the transcript read decides what is pushed
   (`RESULT_AFTER` guards the stale case); the sweep then still runs on every call that passes the gate,
   as harness.md line 389 says. *Fix:* swap the two — claim, return on `False`, then sweep — and one
   `TestWhoIsPushed` cell: a session marker aged past `PENDING_SESSION_TTL_SECONDS` (as
   `test_a_session_start_removes_a_marker_past_its_limit` ages one) is still pushed by its own session's
   call. The in-process limit has the same property for a marker older than 1,800 s whose agent's turn
   ends without a tool call and whose next message refreshes the file, so no second cell is needed.

5. **[NITPICK] The measured one-record-two-wrappers shape has no fixture.** The note (lines 131–132)
   says two quick messages "arrived as one record and were pushed as one instruction", and alpha's
   transcript in the second run shows it (`</teammate-message>\n\n<teammate-message`, one `user`
   record). `_text`'s `findall` (`instruction.py` line 186) handles it;
   `test_two_messages_delivered_in_one_turn_are_one_instruction` (lines 65–75) uses two records, so a
   mutation to a first-match `search` passes the suite and drops the second message silently. *Fix:*
   one test, `records.user(records.message("Second.") + "\n\n" + records.message("Third."))` →
   `"Second.\n\nThird."`, and the invariant list's "two messages delivered in one turn" (line 9310)
   gains "as two records and as one".

6. **[NITPICK] No fixture is the shape 51 of 53 hooks saw.** `tests/transcript_records.py` lines 1–5
   says the fixtures are the measured shapes; every tail in `test_hook_instruction.py` and `_agent`'s
   default (`test_hook_instruction_push.py` line 86) ends on `assistant(tool_use())`, the later-call
   shape (2 of 53). At a first call the tail is the instruction, an `isMeta` system-reminder record,
   the attachments, then `api-request-shape`, `api-request-blob` and `api-request` records — types the
   reader passes over, covered incidentally by `attachment()`. *Fix:* an `api_request()` record in
   `transcript_records.py` and one test with that tail yielding the instruction; make it `_agent`'s
   default so the push tests run on the common case.

VERDICT: NEEDS_CHANGES

## Round 7 — 2026-11-10

**Summary judgment.** Round 6's findings are applied where they live, and I re-checked each at its site
rather than from the brief: `run` claims before it sweeps (`instruction_push.py` lines 98–101) with the
aged-marker cell (`test_hook_instruction_push.py` lines 334–349); `at_first_call` is `_agent`'s default
and the one-record-two-wrappers case has its test (`test_hook_instruction.py` lines 87–94); the brief's
done-when 2 records the four results inline; `harness.md` §Subagents carries the report fact (lines
282–286); the kit logs `UserPromptSubmit`; and `FINDINGS.md` owes the re-install alone. The two new
experiments say what the note says: I replayed the default-mode run's `hooks.jsonl` by hand under the
gate's rule and got the table's row exactly (19 calls, 6 gated starts, 4 stop shells and 0 starts, 3
idle starts, 4 turns, 3 pushes), and the wall-time arms, the 157/41/22/44/186 arithmetic and the
re-derive commands all check. The mechanism, the brief, the tests and every design document I compared
agree. What keeps this from APPROVED is not the mechanism but the record of the live runs: their most
informative result — that every pushed teammate answered the lead from the pushed headline, attributed
it to memory, and in three runs of four fetched the pushed record — is in the transcripts under
`~/.claude/projects/` and nowhere in the artifact, while `FINDINGS.md` Q9 still says no such evidence
exists for memory and Q16 says the transcripts can answer it "while they last". Three nitpicks beside it.

### Findings

1. **[IMPROVEMENT] The live runs measured uptake, and the artifact records delivery alone.** The four
   run sections (`research/teammate-hook-probe.md` lines 120–224) count pushes, lines and markers; the
   brief's "Recorded beside them" (lines 9369–9382) lists payload facts; neither says what a pushed agent
   did with its block. The transcripts do, and the kit's `SEED` (lines 111–117) made it decidable: the
   scratch project holds no Makefile, no tests and no `scripts/ship.sh`, so the three facts have one
   source. Every served instruction that asked one was answered with it and attributed to memory — tmux
   alpha (`…m43-live-tmux/8f28051d….jsonl` line 55): "Run the probe build with `make probe-build`; plain
   `make` deletes the fixtures. Project memory says so, but I haven't verified it against the Makefile";
   tmux beta (`ddc4a2da…` line 56): "Tests need PROBE_TOKEN set to any value … (from project memory, not
   checked against the test code)"; the untyped delta (`54245ebc…` line 67) and default-mode gamma
   (`subagents/agent-agamma-….jsonl` lines 30, 61) likewise; both in-process runs' alpha and beta the
   same, the second run's beta saying "I found no test files in this directory to confirm that directly,
   so it comes from a stored memory record". And the pull after the push, by `tool_use` blocks naming
   `mcp__zikaron__zikaron_memory_fetch` with a pushed uuid: six under tmux (alpha twice, beta, delta, the
   helper twice), four in each in-process run (alpha twice, beta, the helper), none by gamma, who answered
   from the headline — 14 after 22 pushes, by my grep. One detail worth its sentence: tmux alpha's
   mid-task turn *opened* with `fetch` of the deploy record (line 92, before that turn's own push at
   line 94), a uuid it knew from its spawn message's block (line 24) — an earlier block informing a later
   turn. This is the first recorded case of a memory push changing what an agent said, Q16's question
   answered for pushed agents, and the register the pushed-agent policy asks for ("verify") visible in
   every reply; it is also the degenerate case, where the push is the only source and the question is
   the seeded fact, so it measures uptake and not benefit over reading code. *Fix, no new run:* (a) the
   kit's `analyze` prints, per pushed agent, its `zikaron_memory_fetch` uuids and each `SendMessage` to
   `team-lead`, beside the pushes it already lists; (b) the note gains one paragraph — in each run
   section or one §"What the pushed agents did with it" — with the figures above re-derived and the
   degenerate-case caveat in the same sentence; (c) done-when 2's "Recorded beside them" gains "and, for
   each pushed agent, whether its reply carried the seeded fact and whether it fetched a pushed record";
   (d) `FINDINGS.md` Q9 and Q16 each gain a clause pointing at it. The scratch directories and their
   transcripts are what hold the evidence, and nothing keeps them.

2. **[NITPICK] The in-process mid-task case rests on an event order measured once, and the normative
   bullet does not name it.** `harness.md` lines 387–390: a message to a busy teammate "is then marked —
   in-process by the `SubagentStart` that fires as it is delivered". The note (lines 221–224) says why
   that works: the turn's `SubagentStop` fired, *then* the new message's `SubagentStart` 0.1 s later,
   "the order is what keeps the stop from clearing the new marker" — and the default-mode `hooks.jsonl`
   shows it (`SubagentStop` 145.86 s, `TeammateIdle` 145.89, `SubagentStart` 145.96), one case. The
   reverse order would have the stop claim the new marker and lose the message with no line, since the
   claim-failed branch is deliberately silent. *Fix, prose:* in that bullet, after "as it is delivered":
   "— which fires after the turn's `SubagentStop`, 0.1 s later in the one case seen; the reverse order
   would clear the new marker silently".

3. **[NITPICK] The §Processes cost sum mixes two sessions' figures, and its list of what the non-push
   starts were is one category short.** Lines 258–261 multiply 44 starts by "about 57 ms, the ungated
   hook's figure above" — measured 2026-11-09 at load 1.2–1.6 (line 98) — beside 73.7 ms measured
   2026-11-10 at load 0.5–1.0 (line 248); `CLAUDE.md`: a cost is compared on the same machine at the same
   load. And the 57 ms arm is the ungated hook finding *no* marker, not what the 44 starts were: a gated
   start whose claim fails because the pending marker is another agent's, a consolidator's claim and
   record read, or an ungated `TeammateIdle` marking. *Fix:* a fourth arm in `m43_tool_call_time.py`,
   "another agent's marker pending" — `instruction_markers.mark(store_dir, f"{session}.other")` before a
   call for `agent_id: "none"`, the marker claimed after — which is the 19 lead and other-agent starts
   as they happened; or say in that sentence that the 57 ms is the previous day's figure. Lines 241–243
   then name three kinds of non-push start; the fourth is a shutdown request's first call, read as
   protocol — default-mode `hooks.jsonl` line 30 (gamma's `SendMessage` with its marker pending) is one
   of that run's three, and the in-process sections record them separately ("read as protocol and
   pushed nothing"). Add the clause.

4. **[NITPICK] Done-when 3 points nowhere for its results, and the reader path a tmux teammate takes
   was not timed.** Done-when 2 ends "Results join `research/teammate-hook-probe.md`" (line 9383);
   done-when 3 (lines 9384–9392) has no such line, so a reader of the brief does not learn the figures
   exist. Add: "Results: `research/teammate-hook-probe.md` §'The gate's cost per tool call' and
   §'Processes per tool call and turn'." And `m43_tool_call_time.py`'s arms carry an `agent_id`, so they
   time the backward reader; the main-shaped path (`instruction.py` lines 94–104, `_opens_with_a_message`),
   which a tmux teammate's and every lead's first call takes, reads *forward* from the file's start and
   is untimed — it stops at the first string-content `user` record the harness does not flag, which sat
   within the first few records of every transcript the runs left, so the note's "does not follow the
   transcript's size" holds for it too, by a different argument. One sentence in the wall-time paragraph
   saying so.

VERDICT: NEEDS_CHANGES

## Round 8 — 2026-11-10

**Summary judgment.** Round 7's findings are applied where they live, and I re-checked each at its site
rather than from the brief: `research/teammate-hook-probe.md` §"What the pushed agents did with it" gives
figures that reconcile with the four run sections (4 + 4 + 6 + 0 fetches after 5 + 6 + 8 + 3 pushes) and
carries the degenerate-case caveat in the same sentence; `FINDINGS.md` Q16 (lines 273–275) points at it;
`design/harness.md` lines 387–391 name the `SubagentStop`-then-`SubagentStart` order and what the reverse
would do; `experiments/m43_tool_call_time.py` has the other-agent arm (`OTHER`, claimed after each call so
the no-marker arm stays clean), `short-first`, and the reader timed alone; §"Processes per tool call and
turn" gives both orders, states the position effect, sums with 79 and 57.4 ms, lists the protocol and
unread starts, and adds the forward read's stopping line; done-when 3 (lines 9392–9393) names where its
results are. The code and tests are unchanged since round 7 and I re-derived the mechanism from them with
fresh eyes — marker naming against the gate's glob, claim before sweep, the `shlex` split that puts the
hook path after `exec`, the exclusion on both the `agent_id` and the `agent_type` branch, the backward
read's two stop rules and the main-shaped forward read, the resume record, `block or None` — and found
nothing that pushes wrongly, pushes twice, or reaches the consolidator. The brief, the design documents, the
tests and the live runs agree everywhere I compared them, and the two declined round-7 edits are declined
on stated grounds. What remains is three nitpicks in the research note, none of which changes what ships or
what is decided.

### Findings

1. **[NITPICK] The cost sum counts the gated shell twice for the 43 shells that started the hook.**
   `research/teammate-hook-probe.md` lines 270–273: "0.91 ms for the 186 shells". The 79 ms and 57.4 ms
   arms time the installed gate line through `/bin/sh`, so each already includes its shell; the 0.91 ms
   belongs to the 143 shells that exited at `[ -e "$1" ]`. The over-count is about 39 ms on 4.43 s, so
   "about 4.4 s" and "28 ms a tool call" both stand. *Optional fix:* "0.91 ms for the 143 shells that
   started nothing".

2. **[NITPICK] `design/harness.md` §"Agent teams" counts the misses over two runs where four are
   measured.** Lines 440–443: "Of the twelve instructions the two in-process live runs gave agents this
   path serves, none made no tool call and two … made `SendMessage` their first." The tmux and
   default-mode runs are in the same note (lines 206, 215): 23 served instructions across the four runs,
   none without a tool call, three `SendMessage`-first. *Optional fix:* state the four-run figure, since the
   document is the normative one and the claim is stronger at n=23.

3. **[NITPICK] One median beside two ranges.** The wall-time table (line 260) gives the other-agent arm a
   single median, 57.4 ms, and ranged p90 and max, which reads as the two orders' medians having
   coincided. If they did, say so; if not, give both, as the marked arms' rows do.

VERDICT: APPROVED
