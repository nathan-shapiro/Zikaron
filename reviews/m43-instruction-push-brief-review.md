# M43 brief — instruction push to teammates and subagents — review

Artifact: `design/build-plan.md` §"M43 — Push for an agent given an instruction: a teammate's
message and a subagent's prompt" (lines 9030–9212 at the time of round 1).

## Round 1 — 2026-11-09

**Summary judgment.** The mechanism is sound where it is measured, and I re-derived the load-bearing
facts from the probe logs rather than from the note: `TeammateIdle` fires in a tmux teammate's own
session with its own `session_id` and no `agent_id`; in-process `TeammateIdle` and `SubagentStop`
carry `agent_id`; both backends' teammates get the spawn message as a `<teammate-message>` user
record; the lead's copies begin `Another Claude session sent a message:` so the first-record test
excludes it; ordinary subagents' meta files carry `agentType` = definition and nothing else; skill
expansions in a subagent's transcript are `isMeta` list-content records, so the skip handles them.
What stops it shipping is three places where the brief's own invariants are false as the mechanism
is worded, each common rather than exotic: the installer cannot recognise a gated `PreToolUse`
command as its own (so every upgrade doubles it), the marker claim is not atomic under a parallel
first tool batch, and the gate's glob breaks with two markers for one session — the normal case of
two teammates spawned together. Each fix is a sentence or two.

### Findings

1. **[BLOCKER] Item 10's claim that an install over an older one replaces the gated `PreToolUse`
   entry is false as `settings_hooks.py` stands, and the brief names no change to it.** Ownership
   is "each command's first shell word" (`zikaron/install/settings_hooks.py::_program`, line 158;
   `design/harness.md` §"The installer's two targets", line 730; `design/architecture.md` §"The
   install contract", line 2560). A gated command's first word is `[`, `test`, `ls` or `set`, so
   `_zikaron_script` returns `None` for it, `_Slot.holds` is false, and the group is classed **a
   user's own**: left in place, never compared, and a fresh gated group appended beside it on every
   re-install. Two gated entries means two hook runs per tool call and, for a marker, two pushes.
   `--force` does not help, since the group is not held to be Zikaron's at all. *Fix:* add to item
   10: "Ownership reads the Zikaron program as the shell word naming `zikaron-hook` or
   `zikaron-guard`, wherever it stands in the command, not the first word
   (`settings_hooks._program`); `design/harness.md` §"The installer's two targets" and
   `design/architecture.md` §"The install contract" say so." Add to the invariants: "a settings file
   carrying the gated entry at this install's path is rewritten, not doubled; at another path it is
   refused."

2. **[BLOCKER] "The marker is deleted before the request" (item 6) does not make "at most one push
   per marker" true under a parallel first tool batch.** Claude Code runs a batch of independent
   tool calls together (it has a `PostToolBatch` event), each with its own `PreToolUse` process; two
   hooks that each `exists()` then `unlink()` both see the marker and both push. An agent's first
   action after an instruction is very often a batch of reads. *Fix:* in item 6, replace the
   sentence with: "The unlink is the claim: a `TOOL_CALL` whose `os.unlink` of its marker raises
   `FileNotFoundError` makes no request, so two hooks racing on one marker push once." Add the cell
   to the invariants: "two `TOOL_CALL`s for one marker, concurrently, push once."

3. **[BLOCKER] The gate's glob is unspecified where it matters: two markers for one session.** Item
   3 says only "a file `<store>/instruction-pending/$CLAUDE_CODE_SESSION_ID*` exists". The obvious
   `[ -e <dir>/$CLAUDE_CODE_SESSION_ID* ]` is an error with two matches (`too many arguments`,
   exit 2), so `&&` never runs the hook, and both markers stay until `SubagentStop` — both pushes
   lost. Two markers for one session is what two in-process teammates spawned in one batch produce
   (`<sid>.<a1>`, `<sid>.<a2>`), i.e. the ordinary team. The invariant list has "no matching file"
   and "a matching file" and no "several". *Fix:* give the form in item 3 — e.g.
   `set -- '<dir>/'"$CLAUDE_CODE_SESSION_ID"*; [ -e "$1" ] && exec '<hook>'` — and add the cell
   "two matching files, it starts" to the gate invariant.

4. **[IMPROVEMENT] Delivery of `additionalContext` on `PreToolUse` with no `permissionDecision`
   is measured under `auto` and `bypassPermissions`, not `default`.** Both probe runs carried
   `permission_mode: "auto"` (`~/ZikaronTesting/teammate-hooks-*/hook-log.jsonl`), and
   `design/guards.md` §2's table, row "`PreToolUse` with no `permissionDecision`", records that
   under `default` "whether `additionalContext` also arrived there was not recorded" for a call that
   asks. A teammate whose first tool call after an instruction needs approval under `default` is
   the unrecorded cell. *Fix:* have done-when 2 state the permission mode of each session and run
   at least one teammate under `default` with a first call that asks; the new `design/harness.md`
   §"Agent teams" names the mode the delivery claim rests on.

5. **[IMPROVEMENT] A resumed subagent's new prompt has an unmeasured shape, and the "last string
   user record" rule fails toward the wrong instruction rather than toward none.** Item 1 counts "a
   message resuming a subagent" as an instruction; the fixture list in the invariants has no resume
   case. If a resume prompt arrives as list content (as `isMeta` skill expansions do), the rule
   finds the *earlier* string record — the original prompt — and pushes for it silently. *Fix:*
   either add a resume fixture from a real resumed-subagent transcript (LeibaTrader has many
   subagents; find one with a second non-`isMeta` user record), or make the rule fail closed: a
   non-`isMeta`, non-`isCompactSummary` user record after the last string record that carries a
   `text` block and no `tool_result` block ends the search with `instruction_unread`.

6. **[IMPROVEMENT] The evidence note and the brief name different meta-file keys.**
   `research/teammate-hook-probe.md` line 35 says the definition is recorded "as
   `customAgentType`"; the brief (item 5) reads `spawnedAgentType`. The measured teammate file
   carries both, equal (`customAgentType: "probe-mate"`, `spawnedAgentType: "probe-mate"`). A
   builder reading the cited evidence will stop at the discrepancy. *Fix:* in item 5, say "its
   `spawnedAgentType` (the file also carries `customAgentType`, equal in every teammate file
   measured; the brief reads the first and does not fall back to the second)", or read
   `spawnedAgentType`, else `customAgentType`, else `agentType` — one line either way — and
   correct the research note's line to name both.

7. **[IMPROVEMENT] D30's six signals move and the brief does not say how.** Item 9 says `trigger`
   "is what tells the two kinds of push apart in every D30 measure that counts them" but names no
   change to `design/schema.md` §"D30's six signals, as queries" (line 1337). Two signals move: a
   tmux teammate is a session of its own, so its instruction pushes put a *teammate* session into
   the zero-write denominator beside human sessions (§"Honest limit on the session denominator",
   line 1308, currently says subagent sessions are absent from both sides — that sentence becomes
   false for tmux teammates); and in-process instruction pushes add `surface` rows under the lead's
   label, enlarging the amend-after-surface denominator. *Fix:* add to item 9 whether the two
   cross-client signals filter on `trigger = 'prompt'` or count both, and list schema.md's signals
   section and its "Subagent sessions are absent from both sides" paragraph among the sections the
   build writes.

8. **[IMPROVEMENT] Three sections the build must write are not in the normative list.**
   (a) `design/architecture.md` §"Paths" file/mode table (line 641): `instruction-pending/` and its
   empty marker files are new store contents and the table enumerates every one with a mode and a
   rule; say 0700 for the directory, files created under the store umask. (b) `design/architecture.md`
   §"Degraded modes" (line 1236): it is the enumeration of `hook.log`'s kinds and of the push's
   chain; the `TOOL_CALL` path's own chain — connect only if serving, 2 s, no notice, the marker
   cleared first, `instruction_unread` — belongs beside the reminder's. (c) `design/architecture.md`
   §"The install contract" (line 2560), for finding 1's ownership sentence. Add all three to the
   opening paragraph.

9. **[IMPROVEMENT] A message delivered to a busy teammate is an unmeasured cell, and it is the
   common one in a working team.** The probe measured `SubagentStart` once per message to an *idle*
   teammate (3 of 3). The docs say a message to a running teammate is read between tool calls
   mid-turn; whether `SubagentStart` fires then is not stated (`research/claude-code-agent-teams-hooks-docs.md`
   §7). If it does not, no marker is set and the message gets no push. *Fix:* have done-when 2 send
   one of its "later messages" while the teammate is mid-task, and record whether `SubagentStart`
   fired for it; harness.md §"Agent teams" states the result.

10. **[IMPROVEMENT] State the mechanism's known loss where the policy variant promises delivery.**
    An instruction answered without a tool call gets no push by construction; in both probe runs
    1 of the 3 later messages was such a turn. Item 8's variant says a block "arrives with the first
    tool call after each instruction", which is exact only if the reader notices the condition.
    *Fix:* have harness.md §"Agent teams" record the probe's reply-only fraction, and have done-when
    2 count, over its sessions, instructions whose turn made no tool call — the number that tells a
    later session what push coverage a teammate actually has.

11. **[IMPROVEMENT] Where the Anthropic feedback draft lives.** Item 12 is a deliverable with no
    path. `research/` is the home for a note that leaves the session; name it (e.g.
    `research/teammate-hook-feedback.md`) so the build has somewhere to put it and done-when can
    see it exists.

12. **[IMPROVEMENT] Version floor and measured version.** Nothing in the brief names the Claude Code
    version the mechanism was measured on (2.1.311) or the one fact with a documented floor:
    `TeammateIdle`'s `agent_id` needs ≥ 2.1.290, below which an in-process idle sets a spurious
    `<lead sid>` marker and costs the lead one hook run per idle (harmless, but it should be said
    rather than discovered). `design/harness.md`'s header rule is that every Claude Code claim is
    dated and versioned; have §"Agent teams" carry both.

13. **[NITPICK] Gate `SubagentStop` with the same shell line.** It only ever deletes a marker, so
    it has nothing to do when the session has none; gating it halves its cost at no loss, and it
    fires for Claude Code's internal agents too (`agent_type` can be empty).

14. **[NITPICK] Read the transcript from the tail.** An in-process teammate's transcript grows for
    the whole session, and the instruction is always at the end; the brief's wording ("the
    transcript's last `user` record ... back to the `assistant` record preceding them") reads as a
    whole-file parse. Say "read backwards in blocks until the preceding `assistant` record", and
    have done-when 3 record the hook's wall time on the largest transcript the live run leaves.

15. **[NITPICK] `CHANNELS` is a total map over `HookEvent`.** `channel_for` is `CHANNELS[event]`
    (`zikaron/harness/spec.py` line 448); the three new members need entries, or `_emit` must never
    be reached for them. One clause in item 1 ("each with no output, and no channel") saves the
    builder a `KeyError`.

VERDICT: NEEDS_CHANGES

## Round 2 — 2026-11-09

**Summary judgment.** Every round-1 finding is applied and holds as written: the unlink-as-claim,
the `set --` gate, the widened ownership, the `instruction_unread` fail-closed, the three-key meta
resolution, the D30 accounting and the dated version claims all check against the code and the
probe notes. Two things still stop a builder implementing it without re-deriving: the service's
`memory_surface` has a side effect the brief does not know about — `on_receipt=_open_the_turn`
clears the lead's search-reminder time, so every in-process instruction push would reset the lead's
`knowledge_reminder_interval` — and items 3 and 10 disagree about whether `SubagentStop` is gated.
Both are one-sentence fixes. The rest is measurement hygiene and three places where the mechanism's
own cost or loss is left for the builder to discover.

### Findings

1. **[BLOCKER] An instruction push opens the lead's turn.** `zikaron/service/dispatch.py` line
   402: `"memory_surface": Method(surface, Access.READ, deadline=caller_deadline,
   on_receipt=_open_the_turn)`, and `_open_the_turn` (line 354) calls
   `ctx.reminders.clear(envelope.session_id)`, which pops `(label, None)` — the *main* agent's
   reminder time (`service/reminders.py` line 23). It runs on receipt, whatever the push answers.
   An in-process teammate's or subagent's instruction push carries the lead's label (item 9), so
   each one resets the lead's clock and its next code-knowledge search reminds again inside the
   300 s `retrieval.knowledge_reminder_interval` (`design/code-knowledge.md` §6 "How often",
   operator 2026-10-19) — the main session is *not* unchanged, and no invariant in the brief would
   see it. *Fix:* in item 9, after "validated by the service": "and the service opens the
   session's turn (`dispatch._open_the_turn`, `code-knowledge.md` §6) for `"prompt"` alone — an
   instruction push opens no turn, so a tmux teammate's reminder is throttled as a subagent's is,
   once per interval." Add the invariant: "a prompt push clears the session's reminder time; an
   instruction push leaves every reminder time in place." If `on_receipt` cannot see `params`,
   say the dispatcher passes them.

2. **[BLOCKER] Items 3 and 10 contradict each other on `SubagentStop`.** Item 3 (line 9099):
   "`SubagentStop`'s entry is gated by the same line". Item 10 (line 9182): "`PreToolUse` gated,
   `SubagentStop` and `TeammateIdle` plain". A builder cannot satisfy both. *Fix:* item 10 →
   "`PreToolUse` and `SubagentStop` gated, `TeammateIdle` plain" (it cannot be gated: it must set a
   marker when its payload lacks `agent_id`, which the shell cannot see). Let the gate invariant
   (line 9221) say "each gated entry".

3. **[IMPROVEMENT] The brief's own gate form fails the brief's own ownership predicate.** Item 10
   says a command is Zikaron's "when it is the gate form and the word after its `exec` names" a
   Zikaron program. `settings_hooks._words` is `shlex.split`, which does not treat `;` as a
   separator, so the form in item 3 — `… && exec '<zikaron-hook>'; exit 0` — splits to the token
   `<zikaron-hook>;`, whose `Path(...).name` is `zikaron-hook;`, not `zikaron-hook`. The ownership
   invariant would catch it at test time, but the brief should not hand over a form its predicate
   rejects. *Fix:* put whitespace before the terminator in item 3's form (`exec '<zikaron-hook>' ;
   exit 0`, or `… && exec '<zikaron-hook>' || exit 0`), and say in item 10 that the predicate reads
   `_words`' token after `exec`, which the form keeps whole.

4. **[IMPROVEMENT] What this path writes to `hook.log` when nothing is listening, and how its
   lines are told from the prompt path's.** Item 6 says the push "connects only to a service already
   serving" and "a failure writes its `hook.log` line"; the model for that is `hook/reminder.py`,
   whose `connect_if_serving` returning `None` writes *nothing* (line 128). With the marker already
   claimed, a push lost to an absent or still-loading service would then be invisible. And the
   reminder's lines carry the detail word `remind` after their kind so a `transport` line is
   attributable (`reminder.LOG_DETAIL`; `architecture.md` §Paths row for `hook.log`, line 645,
   enumerates the detail words); the brief gives this path no detail word, so its `transport` and
   `unanswered` lines would be indistinguishable from a prompt push's. *Fix:* in item 6, state both
   — "no service listening, or one still loading, writes one `hook.log` line" (or "writes nothing",
   if that is the decision, with why) — and "every line this path writes carries the detail word
   `instruction` after its kind, as a reminder's carries `remind`"; the §Paths `hook.log` row is
   then among what the build writes, beside the directory row item 2 already names.

5. **[IMPROVEMENT] The reply-only fraction was measured with a `Bash` matcher, and the brief
   quotes it as a no-tool-call fraction.** `research/teammate-hook-probe.md` line 7: the probe's
   `PreToolUse`/`PostToolUse` were "matched on `Bash`". An in-process teammate replies through the
   `SendMessage` *tool* (the in-process probe-mate "got `SendMessage` added", line 77), so the
   in-process run's "reply only" message was a turn with a tool call the probe could not see; under
   M43's unmatched `PreToolUse` that call claims the marker and carries the push — after the reply
   it might have informed. Only the tmux run's reply-only turn, whose teammate had no `SendMessage`,
   was a turn with no tool call. Item 6's "1 of the 3 later messages in each probe run" therefore
   overstates the loss for in-process agents and understates what done-when 2 should count. *Fix:*
   item 6: "the probe's `Bash` matcher could not see a `SendMessage` reply, so the measured 1 of 3
   is an upper bound in-process and the true fraction for a tmux teammate without `SendMessage`";
   done-when 2: count, under the unmatched entry, instructions whose first tool call was
   `SendMessage` — a push that arrives with the reply rather than before it.

6. **[IMPROVEMENT] Undotted markers are never collected.** Item 2 sets `<session_id>` on every
   `startup` `SessionStart` and on every tmux `TeammateIdle`; only a `TOOL_CALL` claim removes one,
   and the TTL exempts them. A main session that makes no tool call — a question answered from
   context, a headless `-p` run — and every tmux teammate at shutdown (its last idle set one; in the
   probe its shutdown reply failed for want of `SendMessage`, so no call claimed it) each leave an
   empty file for good, in the directory every gated `TOOL_CALL` lists. Slow, certain, unbounded.
   *Fix:* a second constant, `PENDING_SESSION_TTL_SECONDS` (a day fits "a message hours later"),
   swept by the same listing; the invariant "the TTL … spares a tmux one" becomes "spares one
   younger than a day". `SessionEnd` would do it exactly but costs a fourth entry.

7. **[IMPROVEMENT] The gate bakes the store's absolute path into the settings file; nothing else
   the install writes encodes the project's location.** Item 3: "the store's absolute path written
   by the installer". The hook and MCP commands name the venv, and every hook keys the store on
   `CLAUDE_PROJECT_DIR` (D17; measured present in hook processes, `design/harness.md` table row
   "Project-directory variable"). Rename or move the project and every other hook follows it while
   the gate stays shut for good, with no `hook.log` line, since the hook never starts. *Fix:* the
   gate reads `"${CLAUDE_PROJECT_DIR:-.}"/.zikaron/instruction-pending/` — one token, the gate
   still only skips work — or, if the absolute path is kept, item 3 says so and `zikaron doctor`
   compares it to the project (`design/distribution.md` §"what `doctor` checks" then moves).

8. **[IMPROVEMENT] `SubagentStart` on a resume is asserted, not measured.** Item 2: "Set by
   `SubagentStart` (every spawn, every in-process teammate message, every resume)". The probe
   measured spawns and teammate messages; nothing cited measured a resumed subagent, and round 1's
   fixture list still has no resume case — item 4 fails closed on its shape instead. If
   `SubagentStart` does not fire on resume, no marker is set and the loss is silent, which is the
   accepted direction, but `design/harness.md` §"Agent teams" would then state a trigger that does
   not exist. *Fix:* done-when 2 resumes one ordinary subagent with a second prompt and records
   whether `SubagentStart` fired and the prompt's record shape; the transcript is round 1's missing
   fixture.

9. **[IMPROVEMENT] Item 5's "every path that names the consolidator" misses `SessionStart`.**
   `hook/main.py::_is_consolidator` (line 133) tests `event is HookEvent.SUBAGENT_START` only, and
   `spawn_warm.run` has no exclusion. A consolidator spawned by the skill with teams on under tmux is
   a session of its own whose `SessionStart` carries `agent_type: zikaron-consolidator` (the
   definition, measured) and receives the main write policy and the guard start text — the text
   `_is_consolidator`'s docstring says it is "given no start text". The push path is fail-closed
   either way (no `agent_id`, definition = `agent_type`), so D7 holds; the leak is the spawn text.
   *Fix:* item 5 names `SessionStart` among the paths, excluding a session whose `agent_type` is
   the consolidator's from `spawn_warm`'s policy and the start text; done-when 2 says which backend
   the consolidator runs under, or both.

10. **[NITPICK] A citation's count.** Done-when 2 (line 9249): `~/Memory/design/agent-team-workflow.md`
    §4 "saw such a message wait for the turn to end, n=1". The row (line 114) says **n=2**: "both
    probes that were messaged mid-command saw it only after".

11. **[NITPICK] The gate invariant's unset case needs its precondition.** Line 9222:
    "`CLAUDE_CODE_SESSION_ID` unset, it starts" — only with some marker present; with the directory
    empty `$1` is the literal pattern and `-e` fails. Say "unset and any marker present, it starts;
    unset and none, it does not".

12. **[NITPICK] Say the unserved main-session case logs nothing.** Item 4's cause list ("a record
    not shaped as measured …") can be read to include a main session's first tool call, whose
    transcript is simply not served; read that way, every session writes one `instruction_unread`
    line. One clause: "a transcript not served logs nothing — it is every main session's first tool
    call".

13. **[NITPICK] Who creates `instruction-pending/`.** Item 2 gives its mode and says a marker "is
    written only where the store already exists", but not that the setter creates the directory
    (`mkdir` 0700, exist-ok) — every live store predates it, so `init` alone would leave four real
    projects with no directory to write into.

VERDICT: NEEDS_CHANGES

## Round 3 — 2026-11-09

**Summary judgment.** Every round-2 finding is applied and each holds against the code: `on_receipt`
is `(ctx, envelope)` with no params, so item 9's "the dispatcher passes them" is the right
instruction; `shlex.split` of item 3's form yields `exec` then the hook path as one token; items 3
and 10 now agree on what is gated; the detail word, the two TTLs, the `CLAUDE_PROJECT_DIR` gate, the
resume measurement and the `SessionStart` consolidator case are all there. I re-read both probe
logs: under tmux all four `TeammateIdle` events fired in the teammate's own session and none in the
lead's, so item 2's no-`agent_id` rule rests on a measured fact (which the brief should record). Two
things remain that a builder would otherwise discover: the one cell of the exclusion that fails
*toward* a push rather than away from it, which the brief's intentional-list claims fails closed, and
a no-push branch with no `hook.log` line, which the brief's own item 6 argument says must not exist.
Both are a sentence each. The rest is version hygiene and wording.

### Findings

1. **[IMPROVEMENT] The no-`agent_id` exclusion fails open, and the brief says the dependency class
   fails closed.** Item 5 (lines 9141–9142): "Where an agent has no `agent_id`, its definition is
   its `agent_type` (a tmux teammate's is its definition, measured)". With an `agent_id` a missing
   or unreadable definition means no push — closed. Without one there is no second source, and
   `agent_type`'s meaning is the one fact that already differs by backend: the *name* in-process,
   the *definition* under tmux, both measured on 2.1.311, with the docs calling the field "agent
   name". Were a later build to put the name there under tmux too, a consolidator the skill spawns
   under tmux — `subagent_type: zikaron-consolidator`, name chosen by the lead, as the probe's lead
   chose `mate-1` — carries a name, `is_consolidator` is false, and it is pushed five gists on its
   first `next_group`: "the one wrong answer D7 cannot absorb", with no invariant, no log line and
   no test that would see it. The brief's intentional list says the undocumented-format dependency
   "fail[s] to no push with a hook.log line"; this cell does not. *Fix, two parts, both cheap:*
   (a) item 5 and `design/harness.md` §"Agent teams" name this as the one dependency that fails
   toward a push, and done-when 2 records the consolidator's `agent_type` on its tool events under
   each backend; (b) the consolidate skill's spawn instruction
   (`tests/fixtures/installed/claude-code/skills/zikaron-consolidate/SKILL.md` lines 24–26, from
   the installer's asset) adds "and, where the tool takes a teammate name, name it
   `zikaron-consolidator`" — then name and definition are one word, and every path that reads
   `agent_type` alone (this one, and item 5's last sentence's `SubagentStart` paths where the meta
   file is not yet written) recognises the consolidator without the meta file. Item 8's "so no
   install snapshot moves" then becomes "no agent prompt moves; the skill's snapshot is
   re-rendered". If the operator declines (b), (a) alone is the honest statement.

2. **[IMPROVEMENT] A claimed marker whose definition cannot be read leaves no trace, against item
   6's own rule.** Item 5 (lines 9142–9144): "An agent with an `agent_id` whose meta file is missing
   or names no definition is not pushed." Item 4's log list (lines 9132–9135) does not include it,
   and item 6 says a service absent at a claimed marker *must* write a line "since the marker is
   already claimed and the loss would otherwise leave no trace" — the same argument. The probe
   measured that the transcript does not exist at an in-process spawn's `SubagentStart`; whether the
   **meta file** exists by an ordinary subagent's *first tool call* is unmeasured (done-when 2
   measures it at `SubagentStart` only). If it is routinely late, every ordinary subagent's marker
   is claimed, no push is made, nothing is logged, and done-when 2's "no `instruction_unread` line"
   passes while its "push attached after the subagent's prompt" fails with nothing to attribute the
   failure to. *Fix:* in item 5, "… is not pushed, and writes one `hook.log` line — `instruction_unread`,
   or a kind of its own, carrying the detail word `instruction` — since its marker is already
   claimed"; in done-when 2, "whether the meta file exists at a spawn's `SubagentStart` **and at its
   first tool call**".

3. **[IMPROVEMENT] `SubagentStop` clearing the marker needs the version floor the docs note already
   gives.** Item 2 (line 9090): "by `SubagentStop` for its agent". `research/claude-code-agent-teams-hooks-docs.md`
   §3 records a bug fixed at the 2.1.311 boundary: "`SubagentStop` hooks running about twice a minute
   for each running subagent instead of once". Under item 2's rule a build below the fix clears a
   running subagent's marker before its first tool call, the gate then never opens, and every
   subagent's and in-process teammate's push is lost with no line — the whole feature silently off.
   The probe measured once per turn on 2.1.311, so the mechanism is sound at the measured version;
   the brief's header (lines 9042–9043) and §"Agent teams" carry 2.1.311 as the measured version and
   2.1.290 as `TeammateIdle`'s floor, but no floor for this. *Fix:* in §"Agent teams" (and one clause
   in item 2): "the marker's clearing by `SubagentStop` needs 2.1.311 or later; below it a running
   subagent's `SubagentStop` fires repeatedly and clears the marker before any tool call".

4. **[NITPICK] Record the measured fact item 2's `TeammateIdle` rule rests on.** The rule "when its
   payload carries no `agent_id`" sets a session's own marker; it is right only because the lead's
   session fires no `TeammateIdle` for a tmux teammate. `~/ZikaronTesting/teammate-hooks-tmux/hook-log.jsonl`
   shows all four in the teammate's session (`94694e62…`) and none in the lead's (`819ad222…`).
   One clause in §"Agent teams", so a later reader does not have to re-derive why a no-`agent_id`
   idle never means "the lead".

5. **[NITPICK] The marker file's mode is not what item 2 says.** Line 9079: "files take the store's
   umask". The setters are hook processes under the *user's* umask; the store's `0o077` umask is
   set by the service around store creation and reaches no hook. §"Paths"'s table gives a mode per
   path. Say either "created `0o600` by an explicit `os.open(..., O_CREAT, 0o600)`" or "empty, under
   the hook's umask; the 0700 directory is the boundary and the name is the whole content".

6. **[NITPICK] The current turn may hold several trailing `assistant` records, not one.** Item 4
   (lines 9125–9126): "the current turn's own `assistant` record, the one holding this tool call,
   comes after them and does not end the run". Claude Code writes an assistant turn's content blocks
   as separate records — thinking and text before the `tool_use` — so the backward read skips a
   run of them, and a builder reading "record" as exactly one would end the search on the second.
   Say "records, one per content block", and add to the fixture list (line 9242) an instruction
   followed by a text record and a `tool_use` record of the current turn.

7. **[NITPICK] A tmux consolidator's `SessionStart` should still warm.** Item 5 (line 9152): "such a
   session gets neither". `spawn_warm.run` also spawns the warm helper and records the relay; a
   builder reading "gets neither" as "skip `spawn_warm.run`" leaves the consolidator's first
   `next_group` to cold-start the service through its MCP client. Say "emits neither; the warm-up
   and the relay still run".

VERDICT: NEEDS_CHANGES

## Round 4 — 2026-11-09

**Summary judgment.** Every round-3 finding is applied and holds: I re-read both probe logs (all
four tmux `TeammateIdle`s in the teammate's session `94694e62…`, none in the lead's; the tmux
`SessionStart` carries `source: startup` and `agent_type: probe-mate`; `CLAUDE_PROJECT_DIR` is set in
every tmux teammate hook), the shipped skill (`subagent_type` and no `name`, so item 5's reason for
declining 1(b) matches `~/Memory/design/agent-team-workflow.md` §4's "named" = a `name` argument),
`spec.py`'s total `CHANNELS` map, `settings_hooks._words`/`_program`, and `dispatch._open_the_turn`.
One gap remains in the mechanism itself, and it is the shape of the two unmeasured cells the brief
already names rather than a new edge: item 4's backward read has no guard for a hook that runs
*mid-turn*, and in that shape the rule pushes the previous instruction silently — the one outcome
item 4 says it fails closed on. One clause fixes it. The rest is a normative-list omission and
nitpicks.

### Findings

1. **[IMPROVEMENT] Item 4 pushes the *previous* instruction when the first `TOOL_CALL` after a
   marker is not the instruction's own turn's first call.** Lines 9127–9135: the instruction is "the
   transcript's last `user` record whose content is a string", and the only fail-closed shape is a
   later `user` record "that carries a `text` block and no `tool_result`". Two cells the brief
   itself leaves to measurement put the hook on a transcript whose tail, after the last string
   record, is the *previous* turn's `tool_result` and `assistant` records: (a) done-when 2's message
   to a busy in-process teammate, if `SubagentStart` fires at delivery rather than when the
   teammate "handles" it (`research/claude-code-agent-teams-hooks-docs.md` §3 wording; `~/Memory`
   §4 measured delivery waiting for the turn to end, n=2 — so the marker set at delivery is claimed
   by the *running* turn's next tool call); (b) the docs' own caveat that `transcript_path` "may lag
   the in-memory conversation" (docs note §4, line 50). In both, no record after the last string
   record carries a `text` block without `tool_result`, so the search ends on the prior instruction
   and pushes it again under `trigger: "instruction"`, with no `hook.log` line, and done-when 2
   would record the mid-task message as "pushed" when the push carried the wrong words. *Fix, one
   clause in item 4 after the `text`-block sentence:* "**and so does a `user` record after it
   carrying a `tool_result` block**: the instruction's turn is already past its first tool call, so
   this `TOOL_CALL` is not the one its marker was set for — no push, `instruction_unread`." A
   `tool_result` never sits between an instruction and its own turn's first call, so the rule costs
   no measured fixture. Add to the fixture list (line 9262): "an instruction followed by a
   `tool_result` record, which yields `instruction_unread`". Done-when 2's mid-task measurement then
   has the decision attached that `CLAUDE.md` asks a bar to carry: whichever way `SubagentStart`
   fires, the rule holds, and the recorded fact says whether that message's push arrived or logged.

2. **[IMPROVEMENT] The `memory_surface` wire signature is not in the normative list.** Item 9 says
   `trigger` is "sent by the hook and validated by the service", but the build must write
   `architecture.md`'s RPC list (line 2406: `memory_surface(prompt, limit, client, deadline_at_ms?)`)
   and §"Degraded modes" step 2 (line 1244: `memory_surface(prompt, limit=5, deadline_at_ms)`), and
   `hook/rpc.surface_once` (line 65) gains the parameter; none is named. State the wire default
   there too: `service/params.py` refuses no unknown key and `surface` reads named params only, so
   `trigger` absent on the wire reads as `"prompt"` exactly as a row without it does — which is what
   lets an older hook and a newer service, or the reverse across an upgrade's overlap, keep pushing.
   *Fix:* in item 9: "`memory_surface(prompt, limit, client, deadline_at_ms?, trigger?)`, `trigger`
   absent reading `"prompt"` on the wire as in the row; `architecture.md`'s RPC list and §Degraded
   modes step 2 carry it", and add both to the opening paragraph's `architecture.md` sections.

3. **[NITPICK] Item 6 calls a tool event's `additionalContext` ceiling "unmeasured" where the docs
   state it.** Line 9183–9184. `research/claude-code-agent-teams-hooks-docs.md` §5 (line 84) records
   `additionalContext` capped at 10,000 characters on every event, the overflow written to a file
   with a 2,000-character preview — the same figure `CLAUDE_CODE.injection_budget` holds and
   `push_oversize` reads. Say "documented at 10,000 characters, the prompt hook's measured cap,
   unmeasured on a tool event", so done-when 2's "longest block delivered" confirms a number rather
   than finds one.

4. **[NITPICK] Done-when 2 runs the consolidator only in the cell the shipped skill never
   produces.** Line 9288–9289: "told to spawn it by name, once under each backend". The skill as
   shipped passes `subagent_type` and no `name` (`SKILL.md` lines 24–26), so with teams on a
   skill-driven consolidation is an ordinary subagent under either backend and the named run is
   the operator's addition. Keep both named runs — they are the new cell — and add one run of the
   skill as shipped with teams on, which is the path users take and the one "none to the
   consolidator" is claimed for; one backend suffices, since an unnamed spawn is in-process
   whatever `teammateMode` says.

VERDICT: NEEDS_CHANGES

## Round 5 — 2026-11-09

**Summary judgment.** Every round-4 finding is applied and holds: item 4's `tool_result` rule is
stated with its reason and its fixture, item 9 carries the wire signature with `trigger?` absent
reading `"prompt"`, item 6 cites the documented 10,000-character cap, done-when 2 runs the shipped
skill with teams on, and item 13 is consistent with item 5's reason for not naming the consolidator.
I re-checked the shipped texts (`subagent_type`, no `name`, in both skills and the orchestrator's
step 3) and LeibaTrader's meta files, and the one thing the brief gets wrong there is a measured fact
stated at the wrong magnitude — the model names the orchestrator *every* time, not once. The rest is
two done-when bars whose unmeasured answer has no decision attached, three normative passages the
build must rewrite and does not list, and a schema key that reuses the seam's defined term. All are
sentence-level; none changes the mechanism.

### Findings

1. **[IMPROVEMENT] Item 13 understates its evidence in the direction that matters.** Line 9257–9258:
   "one of LeibaTrader's recorded orchestrator spawns carried a `name` the model chose". Measured
   now: of the 936 `*.meta.json` under `~/.claude/projects/-home-nathan-Trading-LeibaTrader/*/subagents/`,
   exactly nine carry a `name`, all nine are `agentType: zikaron-code-orchestrator`, every one of
   them `name: "zikaron-document-code"` — the skill's own name — and no orchestrator meta file lacks
   it (eight agent ids; `agent-ab5580ee19a77efb0` is recorded under two sessions). No other agent
   type carries the key. So the model's choice is its consistent behaviour for this spawn, and with
   teams on every documentation run today would start a teammate that never ends. *Fix:* item 13:
   "every recorded orchestrator spawn in LeibaTrader's transcripts carried `name:
   zikaron-document-code`, the skill's name, and no other subagent of the 936 recorded carried a
   `name`"; done-when 2's "as a model might" → "as the model does for the orchestrator". And since
   `name` is the one measured mark of a named spawn in an ordinary subagent's file, item 5's "an
   ordinary subagent's carries only `agentType`" (line 9149–9150) misleads a builder writing the
   reader — the file also carries `description`, `spawnDepth`, `requestShape` and, when passed,
   `name`; say "carries its definition in `agentType` and neither teammate key", as the probe note
   does.

2. **[IMPROVEMENT] Done-when 2 sets two bars that one unmeasured answer makes jointly
   unsatisfiable, and attaches no decision to that answer.** Lines 9318–9320 require a push "after
   every message whose turn made [a tool call], and after the subagent's prompt and its resume" *and*
   "no `instruction_unread` line". (a) The mid-task message: if `SubagentStart` fires at delivery to
   a busy teammate rather than when it handles the message, then either the running turn's next call
   claims the marker and item 4's `tool_result` rule writes `instruction_unread` — failing the second
   bar — or the turn makes no further call and its `SubagentStop` clears the marker (item 2) before
   the message's turn begins, so the message gets no push and no line — failing the first. (b) The
   resume: if its record is not string content, item 4's `text`-block rule yields `instruction_unread`
   by design, failing both. The brief records each fact (lines 9321–9324) but says nothing about
   what either answer decides, which is the bar `CLAUDE.md` asks to be sized to the decision it
   forces; the build happens before the live run, so the builder cannot know either answer. *Fix,
   one sentence each in done-when 2:* "If `SubagentStart` fires at delivery to a busy teammate, that
   message's push is the mechanism's loss — claimed by the running turn with an `instruction_unread`
   line, or cleared by its `SubagentStop` with none — §"Agent teams" records it, and this bar reads
   'every message handled by an idle teammate'. If the resume's record is not a string, item 4 serves
   its measured shape in a follow-up, the fixture is its specification, and the `text`-block rule keeps
   failing closed on any other" — or the opposite decision for the resume, but one of them.

3. **[IMPROVEMENT] Three normative passages the build must rewrite are not in the opening list.**
   (a) `design/overview.md` §2, lines 126–131: "Neither hook fires in a **subagent** session under
   either harness ..., which closes by construction the door D32's push-suppression rule was built to
   guard: no push can hand the consolidator the broad retrieval D32 withholds from it" — false after
   M43 under Claude Code, where a push hook fires in subagent sessions and the consolidator is
   excluded by definition (item 5), not by construction; the brief lists the D12 and D32 *rows* only.
   (b) `design/code-knowledge.md` §5.2 (lines 503–513) and §5.3 step 2 (lines 605–613) specify the
   orchestrator's and the documenter's spawn parameters (`run_in_background`, and why); item 13 adds
   a parameter rule to both shipped texts, and the document normative for D39 should carry it with
   its reason, or a reader there re-proposes naming. (c) `README.md` line 105 (the hook row: runs "on
   start, before each message, and — under Claude Code — when it spawns a subagent") and line 389
   (the `.claude/settings.local.json` row: "hooks for session start, each message, each subagent
   start and each search") both enumerate what M43 extends by three entries; the brief names only
   "`README.md`'s sentence on push" (lines 66–67). *Fix:* add all three to the opening paragraph.

4. **[IMPROVEMENT] `trigger` as the `surface_call` key reuses the seam's defined term for something
   else.** In `design/harness.md` (rows "Spawn trigger", "Prompt trigger", "Subagent triggers";
   "trigger names" throughout), `CLAUDE.md` §Harness ("trigger names, session variables, output
   channels"), `HookEvent`'s docstring and `hook/main.py::_emit(..., trigger=)`, a *trigger* is the
   harness's event name — `UserPromptSubmit`, `PreToolUse`. Item 9's key takes `"prompt"` or
   `"instruction"`, neither a trigger name, and `"prompt"` equals `HookEvent.PROMPT.value`, so a
   reader of a row will take it for the event and look for `"tool_call"`; item 1 itself uses
   "triggers" in the seam's sense (line 9076). A key in a per-kind row is one word now and a
   data-shape change later. *Fix:* name it for what it distinguishes — `occasion`, say, with the
   values unchanged — in item 9, the RPC signature and the invariant; or keep `trigger` and have item
   9 and `schema.md`'s row say in one clause that it is not the seam's trigger name.

5. **[NITPICK] Item 13's reason for the document-code skill contradicts the Claude Code text it would
   be written into.** Line 9255–9256: "whose session waits for its orchestrator to hand back as a
   subagent does". The shipped skill says the orchestrator "does the work in the background, so you
   stay free and receive its report when it is done" (fixture line 15; `code-knowledge.md` §5.2);
   only kiro's session waits (`harness.md` §Subagents; `README.md` line 368). Since the teams concern
   is Claude Code's, say "whose session receives the orchestrator's report when it ends, as a
   background subagent's — and a teammate never ends".

6. **[NITPICK] Item 4's path rule for a nested subagent rests on an assumption the brief does not
   state.** The fixture "a documenter spawned by the orchestrator, whose transcript sits flat beside
   its parent's under the root session's `subagents/`" (line 9281–9283) is right about the file, but
   `<transcript_path without .jsonl>/subagents/agent-<agent_id>.jsonl` reaches it only if the
   documenter's `PreToolUse` payload carries the *root* session's `transcript_path` rather than the
   orchestrator's — the docs' "the main session's transcript" (docs note §4, `SubagentStop`),
   measured at depth 1 only. The meta file's path derives the same way, so a wrong derivation turns
   every documenter's claimed marker into an `instruction_unread` line (item 5) — harmless, and
   dozens per run. Say in item 4 that a nested agent's payload is read as carrying the root's
   `transcript_path`, and that the fixture's payload has that shape.

7. **[NITPICK] The `default`-mode cell lands nowhere.** Done-when 2 measures "the cell
   `design/guards.md` §2 left unrecorded" (line 9316–9317), and that table row is where the result
   belongs; add `design/guards.md` §2 to the sections the build writes.

VERDICT: NEEDS_CHANGES
