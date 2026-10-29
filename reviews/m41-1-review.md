# M41-1 review — an install V3 refuses, a session label only the hook can see, and a first turn that does not wait

Artifact: every change in the worktree `/home/nathan/Zikaron-m41-1` against its HEAD, read directly
(no shell in this reviewer, so the diff was reconstructed by reading the new modules, every file the
brief's normative list names, the seam, the hook, the MCP client, the installer and its tests, the
snapshots, the dogfood profile and the probe note). Brief: `design/build-plan.md` §"M41-1".

## Round 1 — 2026-10-28

### Summary judgment

The build does what the brief says, and the hard parts are right: the relay is written first, atomically,
best-effort, keyed on the parent pid both clients share, read under one spec only, and resolved by the
MCP client at its first labeled request; the three-shape merge matches the brief's predicates and the
probe's measurements, ownership reads past `exec` and through the trigger map, the floor is numeric and
fails closed, the shipped profiles carry `permissions` and no V2 trust field, the budget is 3,000 with
`push_oversize` logged, and the live tier measures the one thing nothing hermetic can — one label across
hook, MCP and consolidator events. The design prose is carefully re-sourced to the V3 probe. What stops
it shipping is one done-when-2 miss on a fact the brief seeds by name, in `zikaron/`: the push block's
own module still states the V2 placement and the V2 wrapper. The rest is small.

### Findings

1. **[BLOCKER] `zikaron/core/retrieval/block.py` still states the two refuted V2 facts done-when 2
   seeds by name.** Lines 28–30: *"kiro makes this load-bearing rather than decorative: it wraps
   injected text in prose inviting the model to follow requests found in it (`harness.md`)"* — the
   citation is now false, since `harness.md`'s table says the block arrives in a `HOOK_INSTRUCTION`
   block whose framing was not recorded (kiro-probe §6), and `design/retrieval.md` line 759–762 was
   rewritten to say exactly that. Lines 33–34: *"It lands after the user's message on Claude Code and
   **before it on kiro**"* — refuted by kiro-probe §6 (after, on both). Line 55, the `_PREAMBLE`
   comment: *"after it on Claude Code, before it on kiro"* — the same. The brief's done-when 2 names
   both facts as seeds and `zikaron/` as in scope. Concrete edit (three places, by `Read`+`Edit`):
   - lines 28–30 → *"A harness's own framing is not this frame's to rely on: kiro's V3 engine
     delivers the block inside a `HOOK_INSTRUCTION` block whose framing was not recorded, and Claude
     Code adds none (`harness.md` §"The table"), so the frame is kept for whatever framing a harness
     uses."*
   - lines 33–34 → *"**The block is bounded at both ends.** It lands after the user's message on both
     harnesses (`harness.md` §"The table"), so a heading alone leaves its leading edge running into
     the user's own words. A tag pair also distinguishes …"*
   - line 55 → *"… the user's own message — after it on both harnesses — and because a Markdown …"*
   Then grep `zikaron/` and `tests/` once more for *"before it on kiro"* and *"follow requests"*;
   this round found no other hit outside `design/build-plan.md` and the two design passages that
   now state it as a dated V2 measurement.

2. **[IMPROVEMENT] `kiro_merge._grants` ignores a rule's `match`, so the `subagent` note is silent on
   the one shape the upgrader actually writes.** `_grants` (kiro_merge.py lines 561–569) counts any
   `{"capability": "subagent", "effect": "allow"}` rule, whatever its `match`. The upgrader derives
   `match: ["<trustedAgents entry>"]` from a V2 profile's `trustedAgents` — this repository's own
   `.kiro/agents/zikaron-dogfood.json` (item 10's output) now carries
   `{"capability": "subagent", "match": ["zikaron-consolidator"], "effect": "allow"}`. Under that rule
   the consolidation skill spawns without asking and the documentation skill's `zikaron-documenter`
   spawn asks (interactive) or is refused (headless), and the install reports nothing, because the
   predicate is satisfied. This is not an edge case: it is the shape every pre-M41-1 kiro user's
   profile takes after `kiro-cli agent upgrade`, which item 5 exists to support. Edit: in `_grants`,
   when `rule.get("match")` is a non-empty list, count the rule for `subagent` only if every agent
   name in `_CREW_AGENTS` `fnmatch`es some pattern in it (for `shell` keep the present predicate — its
   `match` is a command pattern, unmeasured); and when a `match`-restricted rule is what fails, let the
   note name the agent it leaves out, e.g. *"… its `subagent` rule's `match` does not cover
   `zikaron-documenter`, so the code-documentation skill's spawns ask."* Add one test beside
   `test_install_writer.py` line 1679's parametrization: tools `["read", "subagent"]`, rule
   `match: ["zikaron-consolidator"]` → the note is emitted and names the documenter. Mutation: the
   `match` check dropped.

3. **[IMPROVEMENT] `FINDINGS.md` lines 95–124 are a build log, which `CLAUDE.md` §"Project memory" says
   goes nowhere.** The (a)–(j) build order, *"the package passes `ruff` and `mypy --strict`"*, *"every
   mutation the brief names turns its test red (run in memory by a scratch pytest plugin, `-p
   mutplugin`)"*, *"The build found the upgrader calls the shipped documenter out of sync unless its
   `tools` are sorted … so they are"* (already in kiro-probe §26 and `documenter_agent_config`'s
   docstring — a third copy), *"`new_line_coverage.py`'s four lines are now covered"*. A fresh session
   acts differently on none of it. Keep: the worktree and branch, that this `FINDINGS.md` is the live
   one, which done-whens hold (4 and 6) and which are owed (5 with the operator), and *next: the
   review*. Suggested replacement for lines 95–124, one paragraph: *"M41-1 is built in
   `/home/nathan/Zikaron-m41-1` on `m41-1-kiro-v3`, whose `FINDINGS.md` is the live one. Done-when 1,
   3, 4 and 6 hold (`pytest -m integration_kiro` 12 of 12 on 2.35.1 `--v3`; the dogfood profile ran
   headless on V3 with no `runError`). Next: the review to APPROVED (`reviews/m41-1-review.md`), then
   done-when 5 with the operator. Live tests stay small: one module of a few files for code knowledge,
   never a large codebase (operator, 2026-10-28)."*

4. **[IMPROVEMENT] Four docstrings and one design paragraph still name the prompt trigger
   `userPromptSubmit`, which under V3 nothing is called.** The brief's exemption covers `agentSpawn`
   as D18's name for the spawn hook; it does not cover the prompt trigger, which has no decision named
   after it and is `UserPromptSubmit` on both harnesses now (`KIRO_TRIGGERS`). Sites:
   `zikaron/hook/push.py` line 82 (*"the whole `userPromptSubmit` sequence"*), `zikaron/service/paths.py`
   line 185 (*"The `userPromptSubmit` hook's own failure record"*), `zikaron/hook/connect.py` line 491,
   `zikaron/hook/warm_helper.py` line 16. Edit: `UserPromptSubmit` in each, by `Read`+`Edit`. And
   `design/architecture.md` lines 1281–1291 reason from *"kiro's own documentation that a non-zero,
   non-two `userPromptSubmit` exit 'shows STDERR to the user as a warning'"* and a spike *"against a
   real kiro session"* — both V2, while `harness.md`'s table now marks a non-zero exit's stderr
   **unmeasured** under V3 (kiro-probe §6 measured only exit-0 stdout reaching the model). The
   decision the paragraph defends — exit 0, stdout — still holds by the V3 measurement, so the fix is
   one clause: date the spike as *"measured on kiro's V2 engine, 2026-08"*, and point at the table's
   "Output channel, tool event" / exit-0 rows for what V3 was measured to do, rather than leaving a V2
   measurement read as current evidence for a cell the table calls unmeasured.

5. **[NITPICK] `session_relay._write` leaves a stale temporary in place after the one failure the
   atomic design is for.** `os.open(temporary, O_CREAT | O_EXCL)` (line 62) sits outside the `try`, so
   if a hook was killed between `os.open` and `replace` — the SIGKILL-at-timeout case — and a later hook
   draws the same pid before a `SessionStart` sweep, its open raises `FileExistsError`, `record`
   suppresses it, and that turn's relay is lost with the stale file still there. Move the `os.open`
   inside the `try` so the `except BaseException` branch unlinks it (the temporary name carries the
   writer's pid, so a live other writer with that name is impossible), or catch `FileExistsError`
   once, unlink, and reopen. Pid reuse inside one session is unlikely enough that this is optional.

6. **[NITPICK] `kiro_merge._hook_notes` (lines 456–460) reports *"Zikaron's hook entries were rewritten
   from the object form"* for any dict-valued `hooks`, including `{}`**, where nothing of ours existed
   to rewrite. Condition the note on `_recognised_hooks(document, commands)` being non-empty. Whether
   `kiro-cli agent create` writes `"hooks": {}` is not in kiro-probe §22, which is why this is a
   nitpick rather than more.

### What was checked and found sound, so the next round need not re-read it

The relay: written before the suppression check and before any socket (`hook/main.py` `_dispatch`),
under `contextlib.suppress(Exception)` as a whole, through `security.ensure_runtime_dir` on both the
runtime directory and the relay directory, by `O_EXCL` temporary and `replace`, swept at `SessionStart`
only, `PermissionError` read as alive; the reader applies the `zk-` check to what it reads and reads only
under `session_variable_reaches_hooks_only`; both clients derive the directory from
`paths.session_relay_dir`; `conftest._no_session_relay_outlives_its_test` keeps the relay from leaking
across tests that share pytest's parent pid. The MCP client resolves at the first labeled request under
its lock and never again. `tripwire` fires under both specs. The floor: numeric, field by field, suffix
read past, unparsable refused naming the output, a note under `--print-only`. The merge: the three
predicates match the brief and kiro-probe §22; `allowedTools: []` from `agent create` reads as universal;
`tools: ["*"]` is left alone; rules are added once; a V3-only profile's `toolsSettings` is untouched;
object-format hooks holding a user's entry are refused showing the array form and naming the upgrader
only without `permissions`. Ownership reads past `exec` and maps `agentSpawn`/`userPromptSubmit` to V3
names, so a converted install is rewritten once per trigger (kiro-probe §27). Shipped profiles: no
`allowedTools`, `permissions.rules` as measured, the documenter's `tools` sorted (kiro-probe §26), no
`hooks`. Budget 3,000 counted in UTF-16 units; `push_oversize` from a module constant, named in
`architecture.md` §"Degraded modes" beside `session_env_mismatch`; `tests/test_install_limits.py` reads
the 404 from `harness.md`. `.kiro/agents/zikaron-consolidator.json` and `zikaron-documenter.json` are
gitignored, so item 10 commits no installer output; the dogfood profile is upgraded and installed over,
its paths the main tree's `.venv` as `CLAUDE.md` §Harness's restore command implies. The kiro-gaps row
for the write policy is present and `not built`. D31/D32/D34 strike the refuted claims beside their
corrections and nowhere else. The probe note's §25–§27 support the cells that cite them.

VERDICT: NEEDS_CHANGES

## Round 2 — 2026-10-28

### Summary judgment

All six round-1 findings are fixed as described, and the fixes are right: `block.py` states V3's placement
and framing, `_covers` reads a `subagent` rule's `match` and the note names the agent it leaves out, the
relay's writer clears its own stale temporary before the exclusive open, the object-form note is conditioned
on our entries having been there, the prompt trigger is `UserPromptSubmit` everywhere outside the trigger
map, and `FINDINGS.md`'s build log is one paragraph. The code is ready. What is not is done-when 2: three
passages still state refuted V2 facts as current truth — one in the normative harness document, in a section
the brief names, saying the tripwire does the opposite of what item 6 built and naming a function that no
longer exists; one in the entry-point document; and three sites in `README.md` whose kiro remedies do
nothing under V3. Each is a few sentences to fix.

### Findings

1. **[BLOCKER] `design/harness.md` lines 224–232 (§"The nesting limit") state the tripwire's scoping as the
   opposite of what item 6 built, and the document contradicts itself about it.** The passage reads: *"The
   naive rule … uses the **identical predicate** as `hook/envelope.py::is_subagent_session`, and under kiro
   that divergence is the *routine, expected* subagent case — so an unscoped tripwire would fire on every
   subagent turn … Therefore: — **The tripwire fires only when the detected harness is Claude Code** …
   Under kiro the same divergence is the subagent case and stays unlogged."* Every clause is refuted:
   `is_subagent_session` is now `sessions_diverge` (`zikaron/hook/envelope.py` line 58, as item 6 says);
   `tripwire.record_misdetection` has no harness branch and its docstring says *"records it wherever it is
   seen"*; no hook fires for a kiro subagent (kiro-probe §12); and this document's own §"Subagents" line 266
   says *"the tripwire records under both (§"The nesting limit")"* — citing the passage that says it does
   not. The brief names this section as normative text the build writes, and done-when 2 seeds the fact.
   Concrete edit, by `Read`+`Edit`:
   - Lines 224–228 → *"**The tripwire's predicate is the suppression check's own.** The hook compares its
     payload's `session_id` with the resolved environment value — `hook/envelope.py::sessions_diverge` —
     and since neither harness fires a spawn or prompt hook for a subagent session (kiro-probe §12; §3),
     the two agree in every hook either harness fires. So a divergence is a misdetection wherever it is
     seen. Therefore:"*
   - The bullet at lines 230–232 → *"**The tripwire fires under both harnesses.** Payload-equals-environment
     is measured invariant under Claude Code (§1) and under kiro's V3 engine (kiro-probe §12). Should a V3
     build ever fire a hook for a subagent, the cost is one line per such turn with the push still
     suppressed — noise, not a push into the consolidator."*
   - Lines 233–246 stay as they are; they remain true.

2. **[BLOCKER] `design/overview.md` lines 126–129 state as current that both hooks fire in subagent
   sessions.** *"Both hooks fire in **subagent** sessions too, and both print nothing there: pushing
   retrieved gists into a subagent's context would hand the consolidator the broad retrieval D32 withholds
   from it."* This is §2's one-page description of the system — the document `CLAUDE.md` names as the entry
   point — and it is undated prose rather than a decision-table row, so the brief's exemption for the struck
   D31/D32/D34 rows does not cover it. Done-when 2 seeds the fact. Concrete edit: *"Neither hook fires in a
   **subagent** session under either harness (`research/kiro-v3-probe.md` §12;
   `research/claude-code-harness-probe.md` §3), which closes by construction the door D32's push-suppression
   rule was built to guard: no push can hand the consolidator the broad retrieval D32 withholds from it. A
   payload-versus-environment divergence in a hook therefore means a misdetected harness, and the hook prints
   nothing there. A subagent still reaches the service through MCP, under the **top-level** session's label.
   §"Subagent sessions" in `design/architecture.md`."* Lower priority, same file: the provenance row at line
   155 records what the 2026-08-01 hook probe settled — `KIRO_SESSION_ID` in every process, hooks firing for
   subagents — with no engine named; insert *"on kiro's V2 engine"* after the date so it reads as the dated
   measurement `architecture.md` line 1149 already labels it, not as a live finding.

3. **[BLOCKER] `README.md` gives three kiro remedies that are V2's.** Each is a done-when 2 seed
   (`allowedTools` as trust, `toolsSettings.crew`, the byte budget) in a file done-when 2 names, and each
   sends a V3 user to a field V3 does not read:
   - Line 1008: *"every Zikaron tool call asks permission | kiro: add `@zikaron` to the agent's
     `allowedTools`."* A profile carrying `permissions` ignores `allowedTools` under V3, so this remedy does
     nothing. Edit: *"kiro: the `mcp` rule over `zikaron/*` is missing from the agent's `permissions.rules`
     — re-run the installer without `--no-trust-tools`, or add `{"capability": "mcp", "match":
     ["zikaron/*"], "effect": "allow"}` yourself."*
   - Lines 1020–1025: *"kiro truncates a hook's output past a byte cap and says nothing when it does"* and
     *"a gist over 1,024 characters is rejected outright, which keeps a five-row block comfortably inside
     every supported harness's budget."* The cut is 3,000 characters, marked `...[truncated]` to the model
     (kiro-probe §21), and item 13's own derivation says the bound proves the block fits Claude Code's
     budget and not kiro's — a five-row block at the bound is 6,097 units against 3,000. Edit the two
     sentences to: *"kiro cuts a hook's output at 3,000 characters and marks the cut to the model alone;
     Claude Code cuts at 10,000, loudly."* and *"a gist over 1,024 characters is rejected outright, which
     keeps a five-row block inside Claude Code's budget. Under kiro a block fits while its five gists stay
     within 404 characters each — every gist in the four real stores does, the longest being 246 — and an
     overrun is recorded as `push_oversize` in `.zikaron/hook.log`."*
   - Lines 781–784: *"unless you add `zikaron-documenter` to `toolsSettings.crew.trustedAgents`, you are
     asked before each documenter is spawned"*. `trustedAgents` is the V2 field; under V3 the grant is the
     `subagent` allow rule whose `match` covers `zikaron-documenter` or is absent, which lines 441–445 of
     the same file already say. Edit: *"unless the agent's `subagent` allow rule covers `zikaron-documenter`
     — one with no `match`, or a `match` naming it — you are asked before each documenter is spawned; the
     installer says so when it does not."*

4. **[NITPICK] `.kiro/agents/zikaron-dogfood.json` `welcomeMessage` says *"gists are injected before each
   message"*.** Under V3 the block lands after the user's text (kiro-probe §6; the table's "Injected block
   placement" row). `CLAUDE.md` §Harness says this file's prose is editable and should be kept true, and item
   10 touched the file. Edit: *"gists are injected with each message"*. Validate the JSON after.

5. **[NITPICK] `kiro_merge._covers` (lines 591–598) reads a `subagent` rule's `match` as a glob, which is
   inferred from the `mcp` rule's documented `zikaron/*` and unmeasured for `subagent`.** If kiro matches
   agent names exactly, `match: ["zikaron-*"]` keeps the install quiet while kiro asks. One clause in the
   docstring, no code change: *"… patterns are read as globs, as the `mcp` rule's `zikaron/*` is documented
   to be; whether `subagent`'s `match` globs is unmeasured, and a rule naming the agent exactly is covered
   under either reading."*

### What was checked this round and found sound

Round 1's six fixes, each read at its site: `block.py` lines 28–36 and 54–56; `_covers`, `_allow_rules`,
`_selects` and the two `subagent` notes in `_grant_notes`, with `TestTheBuiltInGrantNotes`' two new tests
asserting the documenter is named and the consolidator is not; `_write`'s `unlink(missing_ok=True)` before
the `O_EXCL` open, with `test_a_killed_hooks_temporary_under_this_name_does_not_block_the_write`;
`_hook_notes` conditioned on `_recognised_hooks`, with `test_an_empty_object_is_rewritten_with_no_note`;
`architecture.md` lines 1285–1287 dating the stderr spike to V2; `FINDINGS.md` lines 95–102 as one
paragraph. Beyond them: `harness_cli.parse_version` anchors on the binary's name, reads a suffix past, and
refuses naming the raw output; `KiroTarget.refuse_unsupported_version` compares tuples against
`MINIMUM_VERSION`; `KiroTarget.notes` carries item 1's engine sentence and item 8's `--require-mcp-startup`
sentence; `hooks_array` writes `name`, `trigger`, `action.command` with the prefix read from the spec,
`timeout` in seconds and no size field; the shipped snapshots carry `permissions.rules` and no
`allowedTools`, the documenter's `tools` sorted; `test_harness_table.py` derives both new spec fields from the
"Session variable reaches" and "Hook `command`" cells; `_dispatch` writes the relay for `SPAWN` and `PROMPT`
before anything else and sweeps on `SPAWN` only; `ServiceConnection.request` resolves the label once under
its lock from `paths.session_relay_dir(self._location.runtime_dir)`, the function the hook's `relay_dir()`
also uses; `detect.session_label` reads the relay only when the variable is absent under a spec that relays,
and applies the `zk-` check to what it reads; `tripwire.py` and `envelope.sessions_diverge` state the
both-harness rule; `harness.md` §"The session relay" matches the code, both known limits included;
§"Injection budgets" and `schema.md`'s `gist.characters` row carry the per-harness derivation and the 404
figure; `kiro-gaps.md` carries the write-policy row as `not built`; the live tier asserts one label across
`hook`, `mcp` and `consolidator` events and passes `--require-mcp-startup`; `CLAUDE.md` §Harness names the
upgrade step; README lines 132–135 and 245–248 state the floor, `--v3` and `--require-mcp-startup`;
`zikaron/install` and both shipped skills carry no `role:` line; `.gitignore` keeps the two shipped
`.kiro/agents/` configs out of the tree.

VERDICT: NEEDS_CHANGES

## Round 3 — 2026-10-28

### Summary judgment

Every round-2 finding is fixed at its site and the fixes are right: `harness.md` §"The nesting limit" states
the one predicate and the tripwire under both harnesses, `overview.md` §2 says neither hook fires for a
subagent and dates the 2026-08-01 probe to V2, README's three kiro remedies name V3's fields and figures,
the dogfood `welcomeMessage` is true, and `_covers` says its globbing is inferred. The by-meaning sweep's
three rewrites (`write-policy.md`'s preamble, `schema.md`'s subagent sentence, `code-knowledge.md`'s
relayed-label sentence) are each correct. The code is unchanged since round 2 and still sound. What remains
is one stated kiro fact the probe contradicts, in a design document, that no round has reached — a
one-clause fix — and two passages whose evidence is now stale rather than wrong.

### Findings

1. **[BLOCKER] `design/knowledge-index.md` lines 3041–3043 state kiro's spawn trigger as `agentSpawn`, and
   cite `harness.md` as the authority for it.** *"the **detached session-start warm helper** (trigger name per
   `design/harness.md`, which is normative — it is `agentSpawn` under kiro and `SessionStart` under Claude
   Code)"*. `harness.md`'s table (line 59) says `SessionStart` under kiro too, the payload naming it even for an
   entry configured as `agentSpawn` (kiro-probe §3), and `spec.TRIGGERS` carries no `agentSpawn` at all. This
   is not D18's name for the decision, which the brief exempts; it is a per-harness trigger-name claim, in a
   file done-when 2 covers, that contradicts the document it names as normative. Edit the parenthesis to:
   *"(trigger name per `design/harness.md`, which is normative — `SessionStart` under both harnesses)"*. The
   same sentence's *"already the process performing session registration"* is stale for a reason predating
   this milestone (`architecture.md` §Warming: *"that job is gone with the rung"*); dropping that clause while
   the sentence is open costs nothing, but it is not M41-1's miss.

2. **[IMPROVEMENT] `design/kiro-gaps.md`, the "documenter on Haiku 5.5" row: its *why* says the documenter
   *"has not been run on it there"*, and this milestone ran it there twice.** `research/kiro-v3-probe.md`
   line 4: the whole probe ran on `claude-haiku-5.5`, including §17's headless documenter run that used
   `read_file`, `fs_write` and `str_replace`; and `tests/test_install_kiro_live.py` installs with `--model
   claude-haiku-5.5` and `test_the_documenter_reads_one_file_and_writes_another_unasked` runs the documenter
   on it, passing 12 of 12. The brief names the kiro rows' *why* as normative text this build writes. The
   scope fence rightly leaves moving `KIRO.documenter_model` to M41-2, so the row stays; its two cells should
   say what is true. Edit the *why* to: *"`kiro-cli chat --list-models` lists `claude-haiku-5.5`
   (`research/kiro-v3-probe.md` §10), and the documenter has run on it there only headless, on one file (§17;
   `tests/test_install_kiro_live.py`), never on a module"*, and *closing it takes* to: *"a module-sized run on
   it; then `KIRO.documenter_model` moves to it, checked against the model list as every shipped model is"*.

3. **[IMPROVEMENT] `design/architecture.md` lines 1931–1941 carry done-when 2's second seed fact in a V2
   measurement with no engine named.** *"Measured 2026-08-02 (`research/kiro-mcp-lifecycle-probe.md` …): kiro
   runs **one MCP server process per agent instance** — … each a child of the session's single `acp` process …
   all three instances shared one `KIRO_SESSION_ID`, so the pid is the only thing distinguishing them."* Under
   V3 no MCP server carries `KIRO_SESSION_ID` (kiro-probe §4), which the same document strikes at line 176;
   the parent is the `node` agent server, not `acp`; and the conclusion — one process per agent instance,
   `(session_id, pid)` necessary — stands on kiro-probe §5 and §18 plus the relay. This is the class round 1's
   finding 4 fixed at line 1286: a dated V2 measurement read as current evidence. Edit: *"Measured 2026-08-02
   on kiro's V2 engine (…)"*; replace the `KIRO_SESSION_ID` clause with *"all three instances carried one
   session label — under V3 the one the hook relays (`design/harness.md` §"The session relay") — so the pid
   is the only thing distinguishing them"*; and after the `acp` sentence add *"Under V3 a consolidator's
   server is likewise a child of the same agent server as the primary's (`research/kiro-v3-probe.md` §18)."*

4. **[NITPICK] `README.md` line 246** says a profile with *"`allowedTools` or `toolsSettings` and no
   `permissions` block"* is refused. `profile_shape` and `harness.md` line 707 refuse only a **non-empty**
   `toolsSettings`, since `"toolsSettings": {}` is what `agent create` writes. Edit: *"`allowedTools` or a
   non-empty `toolsSettings`"*.

5. **[NITPICK] `FINDINGS.md` line 71** still heads the section *"M41-1 is briefed and ready to build"* while
   lines 90–102 say it is under way with done-when 1, 2, 3, 4 and 6 holding. Edit the heading sentence to
   *"M41-1 is built and in review"*.

6. **[NITPICK] The decision-era trigger names survive in `design/` outside the exemption's letter**, the
   class round 1 renamed in `zikaron/`: `coding-standards.md` line 388 (*"it fires on every
   `userPromptSubmit`"*) and line 414, `overview.md` line 59, `knowledge-index.md` line 3040. K7 at line 1348
   and D12's row name the decision and read as exempt. Either rename these four to `UserPromptSubmit` or
   leave all of them under a D12/D18 reading; what matters is that `zikaron/` and `design/` follow one rule.

### What was checked this round and found sound

Round 2's five fixes at their sites: `harness.md` lines 224–232 and 261–267 agree with `tripwire.py`,
`envelope.sessions_diverge` and `push.run`; `overview.md` lines 126–131 and the provenance row at 157;
README lines 1009, 1013, 1021–1028 and 781–785; the dogfood `welcomeMessage`; `_covers`'s docstring. The
sweep's three rewrites: `write-policy.md` lines 8–19, `schema.md` lines 1316–1322, `code-knowledge.md`
lines 1401–1405 — each states V3's facts and cites the right section. Read fresh and found consistent with
the brief and the probe: `kiro_merge.py` whole (the three predicates, `_guard_object_hooks`' two remedies,
`_recognised_hooks` by name and by meaning past `exec`, `_grant_notes` naming the agent a `match` leaves
out, `_out_of_sync_notes` on `kiroUpgrade` only); `session_relay.py` whole; `detect.session_label` reading
the relay only under the spec's flag and applying `zk-`; `connection.request` resolving once under the lock;
`hook/main.py` writing the relay for `SPAWN` and `PROMPT` before anything and sweeping on `SPAWN`;
`spec.py`'s two new fields and `KIRO`'s 3,000; `harness.py`'s anchored `_VERSION` and `MINIMUM_VERSION`;
`targets.KiroTarget` (floor, two notes, V3 fragment, `--print-only` downgrade in `main._install`);
`entries.hooks_array`, `hook_command_string`, `primary_rules`, both shipped configs; `push.py`'s
`PUSH_OVERSIZE` on the block `surface_once` returned, printed unchanged; `tests/test_install_kiro_live.py`
asserting one label across `hook`, `mcp` and `consolidator`; `tests/test_hook_session_relay.py`'s atomic,
best-effort, written-first and sweep cases; `tests/test_install_limits.py` reading the 404 from
`harness.md`; `conftest._no_session_relay_outlives_its_test`; `architecture.md` §"Both clients resolve the
same label", §"Subagent sessions", §"Degraded modes" step 0, §"Two hook formats", §"The install contract";
`harness.md` whole through §"What a kiro install writes"; `kiro-gaps.md`'s write-policy row; `CLAUDE.md`
§Harness's upgrade step; the five `.kiro/agents/` configs all carrying `kiroUpgrade`; `.gitignore`; the
shipped kiro skill snapshot carrying no `role:`; `zikaron/` and `tests/` grepped clean of `65_536`,
`timeout_ms`, `max_output_size`, `fires_hooks_for_subagent`, `is_subagent_session`, `trustedAgents` as an
output and `--format`.

VERDICT: NEEDS_CHANGES

## Round 4 — 2026-10-28

### Summary judgment

Every round-3 finding is fixed at its site and each fix is right: `knowledge-index.md`'s warm-helper
parenthesis says `SessionStart` under both harnesses and the registration clause is gone; the Haiku 5.5 row
says what ran and what closing it takes; `architecture.md`'s lifecycle paragraph dates the measurement to V2,
names the V3 parentage and replaces the `KIRO_SESSION_ID` clause with the relayed label; README says a
non-empty `toolsSettings`; `FINDINGS.md` says built and in review; the six prose trigger sites read
`UserPromptSubmit`. Read fresh this round rather than from prior rounds' summaries, the code is sound end to
end — the merge's three predicates, the relay's write-first/atomic/best-effort/sweep sequence, the reader's
`zk-` check, the MCP client's once-under-lock resolution, the numeric floor, the `exec` prefix read from the
seam, the 3,000 budget with `push_oversize` — and so are the sections of `harness.md` no round had named
(§"Tool gating" through §"Tool descriptions are capped", and §"The installer's two targets" to the end). What
remains is one stale spawn instruction in a crew file that done-when 2 does not list by name but that item 7's
reason reaches, and two loose statements of the one merge condition done-when 5 exists to test. Both are
minutes of editing; the build is otherwise ready for done-when 5.

### Findings

1. **[IMPROVEMENT] `.kiro/skills/self-review/SKILL.md` line 29 tells the agent to spawn with `role:
   memory-reviewer`, the V2 vocabulary item 7 removed from both shipped kiro skills.** The line reads *"Use
   the `subagent` tool with `role: memory-reviewer` and a brief containing:"*. kiro-probe §11 is the reason
   item 7 struck the same `role:` line from the consolidation skill: V3 offers each subagent as a spawn tool
   of its own, with a prompt and an explanation as its parameters, and no `role` parameter exists. Item 10
   makes this repository's `.kiro/` fallback load under V3, and `CLAUDE.md` §Harness says this crew skill is
   editable and *"worth keeping in step with its twin"* — the twin (`.claude/skills/self-review/SKILL.md`
   line 29) says *"Use the Agent tool with `subagent_type: memory-reviewer`"*, of which this line was the V2
   translation. Under V3 the model would be told to pass a parameter the tool lacks; the consolidation skill's
   identical line was measured survivable (consolidation still ran, kiro-probe §11), so this is a stale
   instruction rather than a dead path, which is why it is not a blocker. Edit, by `Read`+`Edit`, in the form
   the shipped skills now use: *"**Delegate the review.** Spawn the **memory-reviewer** subagent, giving it a
   brief containing:"*. Nothing else on the line or in the file names V2's spawn tool. This sits outside
   done-when 2's file list, so if the operator would rather carry it to M41-2 with the other `.kiro/` crew
   work, say so in the brief and the next round approves on that alone.

2. **[NITPICK] Two passages state the `availableAgents` feed's condition as "V2 fields" where the predicate is
   the universal shape, so each sends a V3-only reader to a remedy that does nothing for them.**
   `kiro_merge.plan_kiro_merge` feeds `toolsSettings.crew.availableAgents` only when `profile_shape` is
   `UNIVERSAL` — `allowedTools` set beside `permissions` — and `harness.md` line 715 says a V3-only profile's
   `toolsSettings` *"is neither read nor written"*. An upgraded profile whose only V2 trust field was
   `toolsSettings` (item 3's third bullet) still carries that list and is V3-only.
   - `README.md` line 1013: *"a profile that still carries kiro's `toolsSettings.crew.availableAgents`
     restricts which agents spawn: add it there, or re-run the installer"*. Re-running feeds the list only on
     a universal profile. Edit the cell to: *"a profile that still carries kiro's
     `toolsSettings.crew.availableAgents` restricts which agents spawn: add `zikaron-consolidator` and
     `zikaron-documenter` there yourself. The installer adds them only on a profile that also carries
     `allowedTools` beside `permissions`, the shape `kiro-cli agent create` writes, and leaves `toolsSettings`
     alone on any other"*.
   - `design/code-knowledge.md` line 744: *"On a config that still carries kiro's V2 fields,
     `zikaron-documenter` joins `zikaron-consolidator` in `toolsSettings.crew.availableAgents` on the same
     condition"*. Edit the opening clause to: *"On a universal profile — `allowedTools` beside `permissions`,
     the shape `kiro-cli agent create` writes (`design/harness.md` §"What a kiro install writes") —"*. The
     rest of the sentence, *"only where that list is already set"*, stays.

### What was checked this round and found sound

Round 3's six fixes at their sites: `knowledge-index.md` lines 3039–3046; `kiro-gaps.md`'s Haiku row and
the other eight rows, each *why* pointing at the table or the probe; `architecture.md` lines 1931–1946;
`README.md` lines 245–249; `FINDINGS.md` lines 71–102 and the D31/D32/D34 index lines, which carry no
refuted claim; `coding-standards.md` lines 388 and 410–414, `overview.md` line 59, `write-policy.md` lines
3–19. Read fresh: `kiro_merge.py` whole — `profile_shape`'s three predicates, `_guard_object_hooks`'s two
remedies, `_recognised_hooks` by reserved name and by command past `exec` on a trigger matched through
`_V3_TRIGGER`, `_merged_hooks` dropping only what it replaces, `_merged_permissions` adding neither rule
twice, `_grant_notes` naming the agent a `match` leaves out, `_out_of_sync_notes` on `kiroUpgrade` only,
`_merged_tools_settings` extending only a non-empty list and never writing `trustedAgents`;
`session_relay.py` whole, including `_owning_pid` reading a temporary's writer pid and `_alive`'s
`PermissionError`; `detect.session_label` reading the relay only when the variable is absent under a spec that
relays, with the `zk-` check after; `connection.request` resolving once under its lock from
`paths.session_relay_dir`; `hook/main.py` `_dispatch` writing for `SPAWN` and `PROMPT` before anything and
sweeping on `SPAWN`; `spec.py`'s two new fields, `KIRO` at 3,000 and `"exec "`, `exceeds_injection_budget`
in UTF-16 units; `targets.KiroTarget` — the floor against `MINIMUM_VERSION`, both notes, the V3 fragment —
and `main._install` downgrading the floor to a note under `--print-only`; `harness.parse_version` anchored on
the binary's name, reading a suffix past and refusing naming the raw output; `entries.hooks_array` with
`timeout` in seconds and no size field, `hook_command_string` prefixing from the spec, `primary_rules`;
`push.py` logging `PUSH_OVERSIZE` and printing the block unchanged. The live tier asserts one label across
`hook`, `mcp` and `consolidator` against `runFinished.data.sessionId`, passes `--require-mcp-startup`, and
runs the documenter headless where an ask is a deny. Both kiro snapshots carry `permissions.rules`, no
`allowedTools` and the documenter's `tools` sorted; the shipped skill snapshots name the subagent and the
prompt and no `role:`. `.kiro/agents/zikaron-dogfood.json` is universal, in the array form with `exec`, its
`welcomeMessage` true; its `subagent` rule's `match: ["zikaron-consolidator"]` is the upgrader's derivation
from its own `trustedAgents`, which the install reports rather than widens, as item 3 says. `.gitignore`
keeps the two shipped configs and two shipped skills out of the tree. `pyproject.toml` stays `0.4.1.dev0`,
and no schema version moved. `harness.md` whole: the preamble's V3 scoping, every kiro cell sourced to the
probe or the migration note or marked unmeasured, the relay section matching the code with both limits, the
tripwire under both harnesses, the budgets with the 404 derivation that `tests/test_install_limits.py` reads
back, §"The installer's two targets" through §"What the install reports rather than enforces".
`test_harness_table.py` derives both new fields from the "Session variable reaches" and "Hook `command`"
cells. `prior-art.md` lines 66–74 state V3's placement and date the V2 wrapper. `architecture.md` §"Two hook
formats" and §"The install contract" state V3's array form and the merge's refusals. Every `V2` mention in
`design/`, `README.md`, `CLAUDE.md`, `zikaron/` and `tests/` either names the engine or is a dated
measurement; every `agentSpawn` left in `zikaron/` names D18's hook (`paths.py`, `warm_helper.py`,
`spawn_warm.py`, `write_policy.py`, `assets.py`, `primary.py`) and reads as the exemption the brief states.
One benign case noted so the next round need not re-derive it: an install whose entry still lacks `exec`
writes one relay file per prompt, each `sh` having a fresh pid, until the next `SessionStart` sweeps them —
bounded, nobody reads them, and the first re-install rewrites the entry.

VERDICT: NEEDS_CHANGES

## Round 5 — 2026-10-28

### Summary judgment

Both round-4 fixes are in and right: `.kiro/skills/self-review/SKILL.md` line 29 spawns the memory-reviewer
subagent with no `role:` and nothing else under `.kiro/` carries one; README line 1013 and `code-knowledge.md`
lines 743–746 state the `availableAgents` feed's condition as the universal shape. This round swept the design
documents no earlier round had named by meaning — `consolidation.md`, `write-policy.md`, `retrieval.md`, the
`schema.md` DDL comments, `knowledge-index.md`, `coding-standards.md`, `distribution.md` — and the done-when-2
file set by grep for every seed fact, and found the prose clean. What it found instead is one test, outside every
prior round's reading, that states done-when 2's second seed fact by construction: the one hermetic test that
runs the installed hook and the installed MCP server as real subprocesses still hands the server
`KIRO_SESSION_ID`, so it passes by V2's label path and never exercises item 4's relay across processes. Small to
fix, and the fix doubles as the hermetic twin of the live tier's one-label test.

### Findings

1. **[BLOCKER] `tests/test_install_e2e.py` `_stdio` (lines 232–245) spawns the MCP server "exactly as kiro
   spawns one" — with `KIRO_SESSION_ID` in its environment, which is the seed fact done-when 2 names.** Line
   244: `env={**os.environ, "KIRO_SESSION_ID": _SESSION_ID}`; line 233: *"A real `zikaron-mcp` subprocess in
   `project`, exactly as kiro spawns one."* Under V3 no MCP server's environment carries the variable
   (kiro-probe §4; `harness.md` line 57), and `harness.md` §"The session relay" opens with exactly that
   sentence. The consequence is worse than a stale docstring: this is the repository's *"least mocked test"*
   (module docstring, line 3), the only hermetic one driving the installed hook command and the installed
   server command as real processes — precisely the pair whose labels split under V3 — and it resolves the
   server's label through the environment rung the harness no longer provides, so the relay the step-1
   `SessionStart` hook writes (keyed by pytest's pid, since the command opens with `exec`) is written and never
   read. Item 4's end-to-end claim, one label across the hook and the MCP client, is therefore covered only in
   `tests/test_install_kiro_live.py`, against `CLAUDE.md` §"The check gate"'s *"nothing is covered only there"*.
   The process geometry already makes the hermetic version possible: `_run_hook` runs `sh -c "exec '…'"`, so
   the hook's `os.getppid()` is the test process; the MCP SDK's `stdio_client` spawns the server through
   `anyio.open_process([command, *args], …, start_new_session=True)` with no shell
   (`.venv/lib/python3.12/site-packages/mcp/client/stdio.py` lines 343–349), so the server's `os.getppid()` is
   the test process too; `conftest._no_session_relay_outlives_its_test` already keeps that shared-parent relay
   from leaking between tests; and `detect.current_harness` falls back to kiro when no marker is set, so a
   server with no variable reads the relay (`detect.py` lines 63–66, 95–97). Concrete edit, by `Read`+`Edit`:
   - Line 244 → `env=dict(os.environ),` and the docstring at lines 233–238 → *"A real `zikaron-mcp` subprocess
     in `project`, spawned as kiro's agent server spawns one: in the workspace directory, and with no session
     variable, so its label is whatever the relay holds for its parent — here the test process, which is also
     the parent the `exec`'d hook wrote for. `cwd` is the load-bearing argument: …"* (the rest unchanged).
   - Then assert what that makes true, mirroring `test_install_kiro_live._events`: after step 5, open
     `paths.store_db_path(paths.store_dir(project))` with `sqlite3.connect(f"file:{db}?mode=ro", uri=True)`,
     and assert `{row[0] for row in SELECT session_id FROM event WHERE client_kind IN ('hook','mcp','consolidator')}
     == {_SESSION_ID}`, with a message naming the relay (`design/harness.md` §"The session relay"). This is the
     hermetic twin of `test_every_client_resolves_the_harness_session_label`, and the mutation that reddens it
     is the one the brief names for the relay: resolve the label at construction, or write the relay after the
     RPC. Put it in step 6, where the store is already being read.
   - The module docstring's lines 9–12 can then say what the test exercises: *"… and speak MCP over stdio to the
     server command, with no session variable, as kiro does — so the label crosses by the relay."*
   The minimum that meets done-when 2 is the first bullet; the second is what makes the test say something the
   live tier alone says today, and costs about ten lines.

2. **[NITPICK] Two comments in `zikaron/install/` still name `allowedTools` as the kiro grant.**
   `targets.py` line 768 (the Claude Code `_merged_permissions` docstring): *"the same argument
   `architecture.md` §"The install contract" already makes about kiro's `allowedTools`"* — that passage
   (`architecture.md` lines 2651–2654) now argues from the consolidator's permission rule and names V3's headless
   refusal, so edit to *"… already makes about the consolidator's `mcp` rule under kiro"*. `entries.py` lines
   41–44: *"the name appears in three places that must agree — the server map, `tools`, and `allowedTools`"* —
   the `mcp` rule's `match` (`zikaron/*`, line 73) is a fourth, and `allowedTools` is written only on a
   universal profile; edit to *"… in the server map, `tools`, the `mcp` rule's `match`, and a universal
   profile's `allowedTools`"*. Neither changes behaviour.

3. **[NITPICK] The V2 stdout/stderr spike is still undated in two places, the class round 1's finding 4
   fixed at `architecture.md` line 1286.** `design/coding-standards.md` lines 441–443: *"Stdout was measured
   directly (a live spike against a real kiro session) to be the one channel that actually reaches the model
   on this build; stderr, tried first, was measured not to surface visibly at all"*; `tests/test_hook_push.py`
   lines 3–5 say the same. The decision each defends — exit 0, stdout — holds under V3, where exit-0 stdout
   was measured to reach the model (kiro-probe §6) and a non-zero exit's stderr is marked unmeasured in the
   table. One clause each: *"(a live spike against kiro's V2 engine, 2026-08; exit-0 stdout was measured to
   reach the model under V3 too, `research/kiro-v3-probe.md` §6)"*, and drop *"on this build"*, which no
   longer names one.

### What was checked this round and found sound

The two round-4 fixes at their sites, and `role:` grepped absent under `.kiro/`. Swept by meaning, not by
match, for the first time: `design/consolidation.md` (one kiro mention, the model field); `design/write-policy.md`
lines 1–35, whose delivery scope says no kiro hook fires for a subagent and cites §"Subagent sessions";
`design/retrieval.md` lines 27–35 (`PostToolUse` exit-0 stdout not reaching the model, cited to the table) and
754–764 (V3's `HOOK_INSTRUCTION`, V2's wrapper dated); the `schema.md` DDL comments at lines 192–199 and 218–222
(every client of one kiro session shares a label — true under V3 by the relay — and `test_ddl.py` reads them
verbatim, so rightly untouched); `knowledge-index.md` line 1664; `coding-standards.md` line 401 (one server
per agent instance, which kiro-probe §18 confirms); `distribution.md`, which names kiro only as a tier;
`design/evaluation.md`, which does not mention it. Grepped across done-when 2's file set and read at every hit:
`KIRO_SESSION_ID` (hooks-only everywhere; the test sites set it for hooks or the suppression check, bar finding
1), `allowedTools` (universal-only everywhere, bar finding 2), `65,536`/`maxOutputSize`/`timeout_ms` (only as
the input shape a converted install carries, or in `kiro_merge` converting it), `trustedAgents` (read, never
written), `toolsSettings.crew`, `--format`, *"follow requests"* (dated V2 in `retrieval.md` and
`prior-art.md`), and `tool_load`. `detect.py` whole: kiro is the one unmarked spec, so a V3 server with no
variable detects it by absence and reads the relay under the `zk-` check. `connection.request` lines 323–329
resolve once under the lock from `paths.session_relay_dir`. `test_hook_main.py` lines 540–569 test the
divergence check with no claim about who fires it. The MCP SDK's `stdio_client` spawns without a shell, which
is what finding 1's recommended assertion rests on. `architecture.md` lines 1139–1165 state V3's subagent facts
with the V2 measurement struck beside them, as the brief's strike rule asks.

VERDICT: NEEDS_CHANGES

## Round 6 — 2026-10-28

### Summary judgment

The three round-5 findings are fixed as described and each fix is right. The e2e test now spawns both MCP
servers with no session variable, so their label can only arrive by the relay — and the geometry makes that
true rather than merely plausible: `_run_hook`'s `sh -c "exec '…'"` and fastmcp's `StdioTransport`, which
wraps the mcp SDK's shell-less `anyio.open_process`, both give the child `os.getppid()` equal to the test
process; `conftest` points `XDG_RUNTIME_DIR` at a directory the suite owns and removes the relay after each
test; and the new step 7 reads the labels back from the store under a message naming the relay. The two
install comments name V3's grant, and the stdout/stderr spike is dated to V2 with V3's measurement beside it in
both places. Nothing in the delta is wrong, nothing in the brief is left unmet short of done-when 5, and what
remains is cosmetic: a test assertion that could be the full twin of the live one for five lines, and two
passages whose wording the edit ravelled.

### Findings

1. **[NITPICK] `tests/test_install_e2e.py` step 7 (lines 382–388) is a looser twin than the live test it
   mirrors.** `_client_labels` collapses the three client kinds into one set and asserts it equals
   `{_SESSION_ID}`; `test_install_kiro_live.test_every_client_resolves_the_harness_session_label` first asserts
   `set(by_client) >= {"hook", "mcp", "consolidator"}` and then per-kind equality. As written, a kind that wrote
   no events — or wrote them under a `client_kind` the `IN (…)` filter does not name — passes vacuously, and the
   step's comment ("both MCP servers … read what the hook relayed") is then asserted for nobody. This is a
   nitpick rather than more because steps 2 and 5 cannot succeed without `remember` and `promote` being served,
   and the event log's own tests cover that those are recorded. Edit, if taken: have `_client_labels` return
   `dict[str, set[str]]` from `SELECT session_id, client_kind FROM event`, then
   `assert set(labels) >= {"hook", "mcp", "consolidator"}, labels` and
   `assert all(seen == {_SESSION_ID} for seen in labels.values()), (…)` with the present message. The relay
   mutation the brief names still reddens it, and a kind that stops logging now does too.

2. **[NITPICK] `zikaron/install/targets.py` lines 767–772: the re-edited `_merged_permissions` docstring is
   ravelled.** *"…about the consolidator's `mcp` rule\n    under kiro: a subagent\n    has no user to answer a
   permission prompt, so a tool that is available but not allowed is a tool\n    that hangs…"* — a four-word
   line followed by a full-width one, the symptom `CLAUDE.md` §"How this project works" names for a passage
   edited in place. Re-wrap the paragraph to the column; no words change. The pointer itself is right:
   `architecture.md` lines 2651–2654 argue from the permission rule and name V3's headless refusal.

3. **[NITPICK] `design/coding-standards.md` lines 441–444: the dating parenthetical now splits the main
   clause.** *"Stdout was measured directly (a live spike against kiro's V2 engine, 2026-08; exit-0 stdout was
   measured to reach the model under V3 too, `research/kiro-v3-probe.md` §6) to be the one channel that
   actually reaches the model"* — thirty words between "measured directly" and "to be". Move the parenthetical
   after "reaches the model": *"Stdout was measured directly to be the one channel that actually reaches the
   model (a live spike against kiro's V2 engine, 2026-08; exit-0 stdout was measured to reach the model under
   V3 too, `research/kiro-v3-probe.md` §6); stderr, tried first, was measured not to surface visibly at all."*
   Same facts, one clause.

4. **[NITPICK] `tests/test_hook_push.py` lines 2–3 send the reader to a measurement that is not where they
   point.** *"see `push.py`'s own module docstring for the measurement behind this shape"* — `push.py`'s
   docstring (lines 13–15) carries no measurement and defers to `architecture.md` §"Degraded modes", which is
   where the dated spike now lives (line 1286). Pre-existing, but the sentence was just edited; point at
   `architecture.md` §"Degraded modes" directly. `push.py` line 14's *"the harness this ships against"*
   (singular, pre-D34) is the same vintage and not M41-1's to fix.

### What was checked this round and found sound

The three round-5 fixes at their sites: `_stdio` (lines 234–250) with `env=dict(os.environ)` and a docstring
that states the V3 geometry and cites the relay section; the module docstring's lines 9–13; `_client_labels`
and step 7; `entries.py` lines 41–44 naming the `mcp` rule's `match` and a universal profile's `allowedTools`;
`targets.py` line 768; `coding-standards.md` lines 441–444 and `test_hook_push.py` lines 1–9. The claims those
docstrings make, verified against what they rest on: fastmcp `client/transports/stdio.py` lines 255–271 build
`StdioServerParameters` and enter the mcp SDK's `stdio_client`, so no shell sits between the test process and
the server; `conftest._runtime_dir_is_never_the_developers` and `_no_session_relay_outlives_its_test` make the
relay directory the suite's own and clear it per test; `session_relay.record` writes for `os.getppid()` under
the `KIRO` spec the unmarked environment detects, sweeping on `SessionStart` only; `detect.session_label` reads
the relay only when the variable is absent and applies the `zk-` check after; `_run_hook` keeps `shell=True`
with the `exec`-prefixed command, so the hook's parent is the test process. `research/kiro-v3-probe.md` §25
measures the MCP server's `cwd` as the launch directory under V3, so `_stdio`'s second paragraph states a
V3 fact. `harness.md` §"The session relay" (lines 128–176) still matches the code and the test, both limits
included. `FINDINGS.md` lines 71–102 say built and in review, with done-when 5 owed to the operator. Every
remaining `KIRO_SESSION_ID` under `tests/` is set for a hook, for the suppression check, or as the variable
rung of the ladder that both harnesses' MCP clients still read when the variable is present
(`test_mcp_connection_labels.py`), and none states that kiro provides it to an MCP server. The live twin's
assertion shape was read for finding 1.

VERDICT: APPROVED

## Round 7 — 2026-10-29

### Summary judgment

The follow-up done-when 5 forced is built as the brief's new item-3 bullet describes, and it is right where it
matters: `_grant_notes` names the `fs_read`/`fs_write` rules a spawned documenter needs from its parent and
grants neither, the write rule is the one probe §28 measured, `DOCUMENTS_DIRECTORY` is asserted equal to the
planner's default, the out-of-sync note names both programs that write `kiroUpgrade`, the `--require-mcp-startup`
note and README say the flag does not make an interactive session wait, the kiro skill no longer says the
documenter's own config suffices, and the new live test spawns the documenter under the scoped rule. Round 6's
four nitpicks are applied. What stops it is one fact the same interactive session measured and nothing in the
design records: the agent's shell carries `KIRO_SESSION_ID` (probe §30), so a `zikaron knowledge` command the
agent runs resolves the harness label by the variable rung — and the normative relay section still says it mints
and calls the question unmeasured. Beside that, two claims are stated as fact that the probe says were not
measured or did not happen, and the brief's own done-when records a pass condition the measurement failed.

### Findings

1. **[BLOCKER] `design/harness.md` lines 172–176 and `design/architecture.md` line 217 state that a
   `zikaron knowledge` command run from the agent's shell mints under kiro, and harness.md calls whether the
   shell sees `KIRO_SESSION_ID` "not yet measured". Probe §30 measured it: *"The agent's own shell printed
   `KIRO_SESSION_ID` as the label the hook had used."*** `detect.session_label` (`zikaron/harness/detect.py`
   lines 95–100) reads the variable first and the relay only when the variable is absent, so a command the
   agent runs through its shell takes rung 1 and its `cli` events link to the session — D31's `cli` link under
   kiro **holds**, which is exactly what done-when 5's last bullet set out to decide, and the brief's own
   done-when 2 seeds the fact (*"D31's claim that `KIRO_SESSION_ID` reaches the agent's shell subprocesses …
   Done-when 5 measures it"*). The "dead agent server's pid adopted" limit at lines 173–174 does not arise on
   that path either, since the relay is never consulted when the variable is present. This is in the section
   the brief names as normative for item 4, in the class every earlier round tagged a blocker. Concrete edits,
   by `Read`+`Edit`:
   - `harness.md` lines 172–176 → *"**A `zikaron knowledge` command** the agent runs through its shell takes
     rung 1 from its environment, since kiro exports `KIRO_SESSION_ID` to the agent's shell (kiro-probe §30),
     so its `cli` events link to the session as D31 intends. One typed from a shell no harness spawned has no
     variable and goes through the same ladder; its parent is a shell no hook writes for, so it mints — unless
     that shell's pid was an agent server that died and was not yet swept, when it adopts that dead session's
     label. Unlikely, and a `cli` event is the cheapest kind to mislabel."*
   - `architecture.md` lines 216–217 → *"Rung 2 is the fallback where neither is there — a kiro install whose
     hook command predates the `exec` the relay depends on, or a `zikaron knowledge` command typed outside any
     session; one the agent runs through its shell has the variable (kiro-probe §30)."*
   - `harness.md` line 57, the "Session variable reaches" cell: keep the leading `**hooks**` that
     `test_harness_table.py::test_session_variable_reach` parses, and say the third reader: *"**hooks** and the
     agent's shell (kiro-probe §4, §30), and no MCP server: no server's environment carries it, and
     `${KIRO_SESSION_ID}` in a server's `env` arrives literally, so the hook relays it — §"The session relay""*.
   - `design/overview.md` D31's row: the struck clause named *"shell-tool subprocesses"* among what carried the
     variable, and the correction beside it — *"the variable reaches every hook and no MCP server"* — is silent
     on shells, so a reader concludes they lost it too. Edit to *"the variable reaches every hook and the
     agent's shell (`research/kiro-v3-probe.md` §4, §30) and no MCP server"*.
   - `design/build-plan.md` item 4's bullet at lines 7855–7859 states the same "mints" consequence; the brief
     is excepted from done-when 2 and this is the author's call, but one clause there would stop the next
     reader re-deriving the wrong answer from the spec.
   Then grep `design/`, `README.md` and `zikaron/` for *"no hook writes for"* and *"shell no harness
   spawned"*; `schema.md` line 1290 (*"a typed command mints legitimately from any shell no harness spawned"*)
   is still true as qualified and needs no change.

2. **[IMPROVEMENT] The `--no-trust-tools` note states as fact what probe §28 says was not run.**
   `kiro_merge.py` lines 570–572: *"The consolidator's and the documenter's own `mcp` rules do not make up for
   it: kiro gives a subagent only what its parent's rules allow as well"*; `harness.md` lines 704–706 and
   `architecture.md` lines 2654–2656 say the primary's `mcp` rule *"is what lets the consolidator's calls
   through"*. Probe §28's last sentence: *"a primary without it, as under `--no-trust-tools`, was not run."* The
   inference is sound — the documented deny-wins intersection, confirmed for `fs_write` — but the sentence is a
   user-facing behavioural claim (*under this flag, consolidation does not run headless*) that reverses what the
   install said before this milestone, and `CLAUDE.md`'s *measure before you assert* is the standard. The cheap
   fix is the measurement, since the harness is on the machine: one headless run with a primary carrying
   `fs_read`, `subagent` and `skill` rules and no `mcp` rule, the consolidation prompt the live test uses;
   `~/.kiro/logs/<ts>/kiro.log` will show `acp.policy-eval.complete` with `effect: ask` on the consolidator's
   first `zikaron` call, or it will not. Record it as §28's second half and the wording stands. Failing that,
   hedge one clause in the note — *"… do not make up for it, as kiro documents and as was measured for the
   documenter's writes: …"* — and the same in `harness.md` line 705; `tests/test_install_main.py` line 271
   asserts the sentence, so the assertion moves with it.

3. **[IMPROVEMENT] Done-when 5's command-line-prompt bullet is a pass condition the measurement failed, and
   `FINDINGS.md` says every bullet passed.** `design/build-plan.md` lines 8120–8122: *"… is accepted or
   refused, and if accepted, that prompt's turn has Zikaron's tools."* Probe §29: accepted, and *"the turn
   answered that it had no Zikaron tools"*. `FINDINGS.md` line 99: *"the operator's interactive run passed every
   bullet of done-when 5"*. Item 8 records the operator's acceptance of that outcome, so the decision is sound;
   the record is not, since the brief's definition of done and the probe disagree and working memory sides with
   neither. Edit the bullet to say what it showed: *"`kiro-cli chat --v3 --require-mcp-startup "<prompt>"`,
   launched interactively from the terminal, is accepted or refused, and what that prompt's turn has is
   recorded — **measured: accepted, and the turn had no Zikaron tools (probe §29); expected behavior (operator,
   2026-10-29), so item 8's interactive sentence says the flag does not make an interactive session wait**"*.
   And `FINDINGS.md` line 99: *"passed every bullet of done-when 5, the command-line-prompt bullet by the
   operator's acceptance of what it showed (probe §29)"*.

4. **[IMPROVEMENT] Two passages state the TUI's rebuild of an out-of-sync profile as something that happens on
   selection; the probe measured that it did not.** `harness.md` lines 723–724: *"a TUI rebuild of its V3 half
   from its V2 one — documented, and done on selecting a profile the upgrader calls out of sync — keeps
   Zikaron's grant"*; `entries.py` line 527: *"which the TUI answers by rebuilding it"*. Probe §30: launching the
   installed-over profile with `--agent` and reselecting it through `/agent` *"left it byte-identical on
   disk"*, and the probe's §"Not measured here" lists the rebuild as never triggered. The universal-profile
   rule itself is unchanged and right — writing to both halves is the safe choice whether or not a rebuild ever
   comes — but "done on selecting" is now a documented behaviour one session contradicted, and this document's
   own preamble rule is that such a cell says so. Edit `harness.md` 723–724 to *"— documented, and not
   triggered by a launch or a reselection in the one session measured (kiro-probe §30), so the install writes
   for it rather than relying on it —"*, and `entries.py` 526–527 to *"… `kiro-cli agent upgrade` calls the
   profile out of sync, the class kiro documents the TUI answering by a rebuild (`research/kiro-v3-probe.md`
   §26), which no measured launch or reselection triggered (§30)."* `kiro_merge.py` lines 652–657 and the
   note at 670–673 already attribute the rebuild to kiro's documentation and need no change.

5. **[NITPICK] `FINDINGS.md` lines 106–116 are a change log, and their "Next" is stale.** The clause list —
   *"the `--no-trust-tools` note and the docs and the kiro documentation skill stop arguing that a subagent's
   own rules suffice; the install note and README say an interactive `--require-mcp-startup` launch does not
   wait; an `integration_kiro` test spawns the documenter as a subagent under the scoped rule"* — is what the
   follow-up edited, which `CLAUDE.md` §"Project memory" says goes nowhere (round 1's finding 3 removed the same
   class). *"**Next:** `./check.sh`, `new_line_coverage`, then the review"* predates the green gate the brief
   reports. Line 113 is also over-long from the edit. Suggested replacement for the paragraph: *"**The follow-up
   done-when 5 forced, built and in review:** kiro gives a subagent only what its own rules and its parent's
   both allow (probe §28), so the install names the `fs_read` and `fs_write` rules a spawned documenter needs
   from its parent — a note, not a grant (operator, 2026-10-29: *"We should have note, not grant permissions
   automatically"*) — the write rule scoped to `./code-knowledge/**`, measured enough. **Next:** the review to
   APPROVED. Live tests stay small: one module of a few files for code knowledge, never a large codebase
   (operator, 2026-10-28)."*

6. **[NITPICK] `README.md` line 451 is over-long** — *"… and the installer says which is missing. Claude Code
   has no such grant to make: the shipped"* runs past the column, the symptom of an in-place edit. Re-wrap
   lines 447–453; no words change.

7. **[NITPICK] `research/kiro-v3-probe.md` line 9 scopes the interactive exception to "results 29 and 30"; result
   31 is from the same session.** The trust screen's record, the session transcript and the per-launch log with
   its policy-eval lines were observed in the operator's interactive run, and the trust screen exists only
   there. Edit to *"except results 29 to 31"*. Research notes are out of sweep scope (operator, 2026-09-22); this
   is raised only because the conditions paragraph is what a reader of any cited result relies on, and the
   brief lists the file as changed.

### What was checked this round and found sound

`kiro_merge.py` whole, read fresh: `_ParentGrant`, `_DOCUMENTER_PARENT_GRANTS` carrying the `agent create`
read rule and the §28 write rule, `DOCUMENTS_DIRECTORY` asserted equal to `zikaron/code_knowledge/main.py`'s
`DEFAULT_DOCUMENTS`; `_grant_notes` computing `ungranted` over `merged` with `_allow_rules` ignoring `match` (the
brief's stated intent), the note naming the capabilities, the acts and the rules it lacks and nothing it has;
`_out_of_sync_notes` naming both programs. `TestTheDocumenterParentGrantNote`'s four cases cover neither, read
only, both, and the default's identity; the brief's two mutations each reach an assertion there. `KiroTarget.notes`
and `test_install_main.py` line 441. `_IN_SESSION_PERMISSIONS` and its re-rendered snapshot under
`tests/fixtures/installed/kiro/`; the Claude Code snapshot's section is unchanged and still Claude Code's. The
consolidator's and documenter's config docstrings in `entries.py`. The live test: the primary's rules are
`_PRIMARY_RULES` plus the scoped write rule and its `tools` carry no `write`, so a pass shows the parent's rule
alone admits the write, as §28 says; `_one_source` and `_documenter_prompt` are shared with the direct documenter
test. `test_install_e2e.py` `_client_labels` returns labels per client kind and step 7 asserts the three kinds
each resolved the hook's label — round 6's finding 1 as suggested. `targets.py`'s `_merged_permissions` docstring
is re-wrapped and its kiro cross-reference gone; `coding-standards.md` lines 441–444 read as one clause;
`test_hook_push.py` points at `architecture.md` §"Degraded modes". `harness.md` §Subagents' new bullet, the
approval-gates row (two gates, the trust screen's record outside the repository, a subagent's call needing both
rules), §"What a kiro install writes" lines 701–744 (necessary-and-not-sufficient stated, the grants left to the
user with the operator's words, the write rule's scope named), and §"What the install reports rather than
enforces" line 877 left as the Claude Code claim the brief exempts. `architecture.md` lines 2651–2658. README
lines 132–137, 245–251, 441–453, 455–460 and 786–792. `build-plan.md` item 3's new bullet, item 8's fence with the
operator's two quotes, item 12. `FINDINGS.md`'s owed entry on a kiro install with no custom agent, now naming the
`permissions.yaml` §31 found. `FINDINGS-archive.md` §References. `kiro-gaps.md`: no row is touched by a
parent-grant note, and none should be. The grep the brief reports — *"nobody to answer"*, *"no user to answer"*,
*"own config already allows"*, *"was converted by"* — re-run by meaning over `design/code-knowledge.md`, which
carries no claim that a kiro subagent's own rules suffice.

VERDICT: NEEDS_CHANGES

## Round 8 — 2026-10-29

### Summary judgment

Round 7's seven findings are each fixed at the site named and the fixes are right: the relay section, the table
cell, D31's correction clause, §"Which client uses which rung" and the brief all say the agent's shell carries
`KIRO_SESSION_ID`, the spec field is renamed to the predicate the code actually tests and its comment names all
three readers, probe §28 now measures the consolidator's `mcp` case rather than inferring it, done-when 5's
command-line bullet records what was seen and the operator's acceptance, the TUI rebuild is "not triggered in the
one session measured" in both places, and the three cosmetic items are applied. The code is unchanged since
round 6 apart from the rename, which is consistent across `spec.py`, `detect.py`, `session_relay.py` and the
table's drift guard. What remains is the same fact in its softer phrasing at three sites the brief's greps could
not match — "reaches hooks alone", now contradicted by the renamed field and by the table — and one design bullet
that still says the parent-rule intersection was measured for writes only, a day after it was measured for the
consolidator's tools too. Each is one clause.

### Findings

1. **[IMPROVEMENT] Three sites still say the variable "reaches hooks alone", the scope the rename exists to
   withdraw, and one of them contradicts its own section thirty lines on.** The brief's sweep grepped `agent's
   shell`, `shell-tool subprocess` and `KIRO_SESSION_ID` near `shell`; "hooks alone" shares no word with any of
   them, which is `CLAUDE.md`'s named limit of a match-based sweep.
   - `zikaron/harness/detect.py` line 78, the docstring of `session_label`: *"Where the variable reaches hooks
     alone, an absent one is read instead from the session relay"* — the predicate the line below reads is
     `session_variable_misses_mcp_server`, whose own comment (`spec.py` lines 124–126) says *"hooks and the
     agent's shell but no MCP server"*. Edit: *"Where the variable misses the MCP server, an absent one is read
     instead from the session relay"*.
   - `design/architecture.md` line 188, rung 1 of the normative ladder: *"or, under kiro, where the variable
     reaches hooks alone, the MCP client reads the label the hook relayed"*. A reader applying rung 1 to a
     typed command concludes it has no variable under kiro and falls to rung 2 — the conclusion round 7's
     blocker removed — while line 217 of the same section says the opposite. Edit: *"or, under kiro, where the
     variable reaches the hook and the agent's shell but no MCP server (`design/harness.md` §"The table"), the
     MCP client reads the label the hook relayed"*.
   - `design/schema.md` line 1263: *"under kiro, whose variable reaches hooks alone, the MCP client reads the
     label the hook relays"*. Edit: *"whose variable misses the MCP server"*.
   - Optional, the author's call since the brief is excepted: `design/build-plan.md` line 7818, *"`HarnessSpec`
     gains a field saying the session variable reaches hooks alone"*, describes the field by its old predicate;
     *"saying the session variable misses the MCP server"* matches what shipped.
   Then grep `zikaron/`, `tests/`, `design/`, `README.md` and `CLAUDE.md` for *"hooks alone"* and *"hooks only"*;
   this round found no other hit, and the five *"hooks and no MCP server"* phrasings (`harness.md` 130,
   `session_relay.py` 5, `test_hook_session_relay.py` 4, `test_harness_detect.py` 141, `architecture.md` 180) are
   true as written and need no change.

2. **[IMPROVEMENT] `design/harness.md` §Subagents, lines 273–278, says the intersection was *"Measured for
   writes"* and stops, and it is the section two consolidator claims cite.** Probe §28's second half now records
   the consolidator case the previous round asked for — a primary with `fs_read`, `subagent` and `skill` rules
   and no `mcp` rule, the skill loaded, the consolidator spawned, `"effect":"ask"` logged on each of its three
   `zikaron_memory_next_group` calls, headless refused, the journal entry still in the journal. `harness.md`
   lines 706–708 (*"which is why the primary's `mcp` rule matters to the consolidator"*) and `architecture.md`
   lines 2655–2656 (*"so the primary's `mcp` rule, which `--no-trust-tools` withholds, is what lets the
   consolidator's calls through"*) both cite §Subagents for that claim, and §Subagents offers the write
   measurement alone — so the bullet reads as *the `mcp` case is inferred*, which was true on 2026-10-28 and is
   not now. Edit, after *"it wrote (kiro-probe §28)"*: *"— and for Zikaron's tools: a consolidator spawned under
   a parent with no `mcp` rule, as `--no-trust-tools` leaves it, had each of its `next_group` calls ask, headless
   refused, and the journal entry stayed where it was (kiro-probe §28)."* The `--no-trust-tools` note in
   `kiro_merge.py` lines 570–572 and the test asserting it need no change, as round 7 said.

3. **[NITPICK] `FINDINGS.md` line 100 runs past the column** — *"…(`research/kiro-v3-probe.md` §29–§31). The
   committed `.kiro/agents/zikaron-dogfood.json` names `/home/nathan/Zikaron/.venv`,"* — the symptom of the
   in-place edit round 7's finding 3 asked for. Re-wrap lines 97–104; no words change.

4. **[NITPICK] `research/kiro-v3-probe.md` line 3 heads the note *"Run 2026-10-28"*, and result 28's headless
   runs say *"Run 2026-10-29"*.** The conditions paragraph excepts results 29 to 31 as the interactive session, so
   a reader dates §28 by the headline. One clause at line 3: *"Run 2026-10-28, and result 28 on 2026-10-29"*.
   Research notes are out of sweep scope (operator, 2026-09-22); raised only because the brief lists the note as
   changed and §28 is now what two design claims rest on.

### What was checked this round and found sound

Round 7's seven fixes at their sites: `harness.md` line 57 (leading `**hooks**` kept for the drift guard, the
shell named, §4 and §30 cited), lines 130–136, 173–178 (the typed-outside-any-session case mints, the agent's
shell takes rung 1 and the relay is never read — true, since `detect.session_label` reads the variable before
the relay), 696–701, 723–727; `architecture.md` lines 213–218 and 287–289; `overview.md` D31's correction clause;
`build-plan.md` lines 7855–7860, 8095–8097, 8122–8126; `entries.py` lines 526–528; `FINDINGS.md` lines 71–72,
90–112; `README.md` lines 441–453; probe lines 9–11 and §28–§31. The rename: `spec.py` lines 124–127, 258, 291;
`detect.py` line 96; `session_relay.py` line 43; `test_harness_table.py` lines 260–271 deriving the field from
the cell's leading bold; no `reaches_hooks_only` survives outside this review file. The claim behind round 7's
blocker, verified against the code rather than the prose: `zikaron/knowledge/client.py` line 183 opens
`ServiceConnection`, whose `request` resolves through `detect.session_label`, which reads `KIRO_SESSION_ID`
first and the relay only when it is absent — so a `zikaron knowledge` command the agent's shell runs takes rung 1
and its `cli` events carry the hook's label, as D31 and §"Which client uses which rung" now say. `schema.md`
lines 1274–1292 (link coverage, a typed command minting *from any shell no harness spawned*) remain true as
qualified. `code-knowledge.md` lines 1402–1406 and `kiro-gaps.md` carry no claim about the typed command's label.
`kiro_merge._grant_notes` whole, unchanged since round 7. Done-when 5 as recorded reads consistently with §29
and §30, each bullet's outcome in the probe.

VERDICT: NEEDS_CHANGES

## Round 9 — 2026-10-29

### Summary judgment

Round 8's four findings are each fixed at the site named, and each fix says what the evidence says. The three
"hooks alone" sites and the brief's field bullet now state the predicate the renamed field tests — the variable
misses the MCP server — and `architecture.md`'s rung 1 names all three readers with the table as its source, so
the ladder no longer contradicts its own §"Which client uses which rung". `harness.md` §Subagents' intersection
bullet carries the consolidator half of probe §28 in the probe's own terms, so the two `--no-trust-tools` claims
that cite it now rest on a measurement rather than an inference. `FINDINGS.md` lines 97–105 sit within the
column and the probe's headline dates result 28. The code is unchanged since round 8. Nothing in the delta is
wrong, every seed fact of done-when 2 has been swept by match and by meaning across nine rounds, and what remains
is one cosmetic wrap in a file the sweep rule excludes. Ready to ship.

### Findings

1. **[NITPICK] `research/kiro-v3-probe.md` lines 3–6: the dated headline ravelled the paragraph's wrap.** Line 5
   is *"Linux. kiro-cli 3.0 makes this engine the"* — forty characters, followed by a full-width line — the
   symptom of the in-place edit round 8's finding 4 asked for. Re-wrap lines 3–8; no words change. Research
   notes are out of sweep scope (operator, 2026-09-22), so this is optional and raised only because the brief
   lists the file as changed.

### What was checked this round and found sound

The four fixes at their sites, each read with its neighbours: `zikaron/harness/detect.py` lines 74–100 — the
docstring's *"Where the variable misses the MCP server"* names the predicate line 96 reads,
`spec.session_variable_misses_mcp_server`, whose comment at `spec.py` lines 124–126 names hooks, the agent's
shell and no MCP server; `design/architecture.md` lines 174–227 — rung 1 at 187–189 cites §"The table", and
lines 214–219 and 221–227 agree with it; `design/schema.md` lines 1260–1292 — line 1263 says *"misses the MCP
server"*, and the link-coverage bullets that follow still describe the one remaining way to be unlinked;
`design/build-plan.md` line 7818. `design/harness.md` lines 273–280 against `research/kiro-v3-probe.md` §28
lines 216–229: the parent's rules (`fs_read`, `subagent`, `skill`, no `mcp`), the skill loaded, the consolidator
spawned, `"effect":"ask"` on each of three `zikaron_memory_next_group` calls, headless refused, the journal
entry still in the journal — the bullet states each and adds nothing. `harness.md` line 57's cell keeps the
leading `**hooks**` that `tests/test_harness_table.py` lines 259–271 derive the field from, and lines 128–178
(§"The session relay") remain consistent with the cell, the code and the agent's-shell fact at lines 135–136 and
176–178. `design/overview.md` D31's correction clause (line 213) names hooks, the agent's shell and no MCP
server with §4 and §30 cited. `FINDINGS.md` lines 71–113: wrapped to the column, stating built, done-when 5
passed, the follow-up in review, and the operator's three decisions in their words. Swept by meaning for the
"hooks alone" class in phrasings the brief's grep could not match — *only the hook*, *hook alone*, *only hooks*,
*hook's environment only/alone*, *the hook can see* — across `design/`, `zikaron/`, `tests/`, `README.md`,
`CLAUDE.md`, `FINDINGS.md`, `.kiro/` and `.claude/`: every hit is about logging or the per-message budget
(`harness.md` 596, `architecture.md` 597 and 995, `distribution.md` 418, `overview.md` 213's *"only the hook
sits on a per-message budget"*, `test_hook_stdlib_only.py` 45), or the tripwire's inputs (`build-plan.md` 385),
or the milestone's title (`build-plan.md` 7636, a name in the excepted brief); none states the variable's
reach. Every *"hooks and no MCP server"* phrasing (`harness.md` 130, `session_relay.py` 5,
`test_hook_session_relay.py` 4, `test_harness_detect.py` 141, `architecture.md` 180) is true as written.

VERDICT: APPROVED
