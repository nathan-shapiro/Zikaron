# Review — container-found defects (`--version`, store remedy, README install path, research note)

## Round 1 — 2026-09-23

**Artifact reviewed**: the working-tree diff at `scratchpad/change.diff` and the current state of
`zikaron/cli/main.py`, `zikaron/core/store/store.py`, `tests/test_cli_front_door.py`,
`tests/test_store.py`, `README.md`, `design/distribution.md` §"The front door", `design/harness.md`
§"Three flags", `research/m30-docker-end-to-end.md`, `FINDINGS.md`, `FINDINGS-archive.md`. Not
re-derived, per the brief: the green gates, the container exercise of the two strings, and the grep
for other pins of those strings.

### Summary judgment

The `--version` fix is small, correctly wired and correctly documented; the README restructuring
around `--harness` is a real improvement; the research note is a valuable record of a run that had
never been done. But the second code fix — the store refusal's remedy — names a command that does not
do what the message says: `zikaron install` never creates a store, and `design/architecture.md`
§"First run" is an operator decision that only the service does, on its own first start. That is a
shipped instruction that fails when followed, in a change whose whole purpose was to make the message
actionable, and the new test pins the wrong remedy. The note's thesis sentence also claims a session
"pushing and searching" that nothing in the note reports. Not ready.

### Findings

1. **[BLOCKER] The remedy in `_store_not_created` is false: `zikaron install` does not create a
   store.** `zikaron/core/store/store.py:126-129` now says `` `zikaron install --project <dir>`
   creates it ``, and the docstring at `:114-115` asserts "`zikaron install` is what creates a store".
   Neither is true. `design/architecture.md:663-668` (§"First run", **operator decision**): "Nothing
   upstream of the service — no installer, no client, no separate bootstrap step — creates
   `memory.db`." `Store.create` has exactly one caller, `zikaron/service/context.py:247`;
   `zikaron/install/main.py:_install` writes shipped files and merges harness config and touches
   nothing under `.zikaron/`; `zikaron/mcp/connection.py:122-127` says the same in its own words.
   A user who follows the new message runs `zikaron install`, re-runs `zikaron knowledge add`, and
   gets the identical refusal — the case the brief's container check did not exercise, since it
   verified that the string *printed*, not that following it works. The same wrong diagnosis is
   written into `research/m30-docker-end-to-end.md:188-192` (defect 1: "it does not say to run
   `zikaron install --project .`"), `FINDINGS.md:224`, and the assertion at `tests/test_store.py:302`.
   **Suggested change.** Name what does create the store — the service's first start, which a
   session triggers — with install as the precondition where it is missing, e.g.:
   ```python
   expected=(
       "an existing, openable memory.db — this store has not been created; nothing has run "
       f"Zikaron in {project} yet. The service creates it on its first start, so start a session "
       f"there (after `zikaron install --project {project} --harness ...`, if Zikaron is not "
       "installed there)"
   )
   ```
   where `project = db_path.parent.parent`. Then retarget the test's name and assertion, rewrite the
   note's defect 1 so the remedy it records is a first session rather than an install, and fix
   `FINDINGS.md:224`. If a session is judged too heavy a remedy for a shell command, the alternative
   is for `knowledge/scope.py:open_store` to create the store itself — but `Store.create` needs the
   encoder artifact for the vector width, so that is a design change with a model load in it, not a
   string fix, and not this PR's.

2. **[BLOCKER] The note's thesis claims a session "pushing and searching" that it does not
   report.** `research/m30-docker-end-to-end.md:3-5`: "It reaches three things CI structurally
   cannot: a genuinely cold model cache, a real Claude Code session pushing and searching, and a real
   subagent." What the note actually reports: the `SessionStart` policy injection (`:132-133`), two
   `zikaron_memory_remember` writes (§Coexistence), and the consolidator's tool calls (`:139-144`).
   There is no `UserPromptSubmit` gist block shown and no `zikaron_memory_search` call anywhere.
   "Push" in this corpus is D12's per-prompt gist injection, and the pre-change `FINDINGS.md` set
   this run's purpose as reaching what "nothing automated has ever exercised — a real session
   pushing or searching"; the note now asserts it did without the evidence. Either add what was seen
   (the injected block after the second prompt, the search call and its result) or narrow the sentence
   to "a real session receiving the write policy and writing through MCP, and a real subagent".
   `FINDINGS.md:205` has the same problem in miniature: "hook fired" should say *which* hook
   (`SessionStart`, on the evidence), and "both MCP modes" is an undefined term — if it means both
   servers loaded, say "both MCP servers loaded".

3. **[IMPROVEMENT] README overstates what `--print-only` previews past, in the sentence right after
   the paragraphs that say a first install refuses.** `README.md:225-226`: "it previews even where a
   real install would refuse, and says so." In `zikaron/install/main.py`, `_resolve_harness` runs at
   `:161`, before the `print_only` branch at `:193`; only `refuse_absent_harness` and
   `refuse_unknown_model` are downgraded to notes (`:199-210`). Unknown harness, missing shipped
   commands, `--agent` under Claude Code and a non-directory project all still refuse. So the reader
   who has just been told detection fails on a first install and then tries
   `zikaron install --project . --print-only` gets the detection refusal, contradicting the sentence.
   Suggested: "pass `--print-only` on either harness; it previews past an absent harness binary or an
   unvalidated model, and says so — but it still needs to know which harness, so a first install
   passes `--harness` with it, as a real one does."

4. **[IMPROVEMENT] The `CLAUDECODE` claim in the normative doc is false for the case the fallback
   exists for.** `design/harness.md:537-538`: "`CLAUDECODE` is exported inside a session rather than
   into the shell an installer runs from"; `README.md:208` says the same. The installer's own docstring
   (`install/main.py:258-263`) describes installs run *from a Claude Code session*, and an agent running
   `zikaron install` through its shell tool has `CLAUDECODE=1` — detection succeeds on that first
   install. So "detection earns its keep from the *second* install onwards" (`harness.md:538-539`) is
   true of a terminal outside a session only, and a Claude Code user asking the agent to install is
   not an exotic first-install path. Suggested harness.md text: "…and `CLAUDECODE` is exported into
   the processes a session spawns — present when the agent itself runs the installer, absent from a
   terminal outside one. From a plain terminal, then, detection earns its keep from the second install
   onwards, and that is the case `README.md` writes for." README `:208`: "not in a terminal outside
   one". Also drop `harness.md:539`'s clause describing README's current wording ("`README.md` names
   `--harness` in the command") — a design doc quoting a README sentence is a coupling that drifts;
   state the rule and let README follow it.

5. **[IMPROVEMENT] Three files disagree on how many defects the run found.** `FINDINGS.md:222`: "Four
   defects". `FINDINGS-archive.md:3258`: "three defects it found". The note's §"Defects found"
   (`:186-195`) lists three; the fourth — README never said where `uv` comes from — appears only as a
   bullet under §"The cold baseline" (`:25-27`). Add it as the note's item 4 and make the archive say
   four, or make `FINDINGS.md` say three defects and one documentation gap. Pick one count.

6. **[IMPROVEMENT] "Reachable there and nowhere else" is an overclaim.** `FINDINGS.md:206`. The `/tmp`
   socket fallback is reached on the development host by unsetting `XDG_RUNTIME_DIR` — `FINDINGS.md:160-161`
   re-derives its figure with exactly `xdg_runtime_dir=None` — and the cold-cache branch by pointing
   `XDG_CACHE_HOME` at an empty directory. The note itself says only that every previous run "took the
   warm branch" (`:59`): unexercised, not unreachable. Suggested: "Four things were exercised for real
   there for the first time".

7. **[IMPROVEMENT] Three measurements in the note are asserted without the observation that supports
   them, against "measure before you assert".**
   (a) `:32-36` — "on `python3.14.4` from `python3-minimal`, `enable_load_extension` is present *and*
   succeeds, and FTS5 is compiled in … measured rather than cited". No command, no output. Add the
   probe that was run (a one-liner against `/usr/bin/python3` connecting `:memory:`, calling
   `enable_load_extension(True)` and reading `pragma compile_options` for `ENABLE_FTS5`, or whatever
   it was), so the claim is re-derivable like the rest of §"Re-deriving this".
   (b) `:89-90` — "verified silently. Service up in 3.7 s (`02:54:14.257` runtime line →
   `02:54:17.998` `service_warm`)". Say what the 3.7 s spans: if the "runtime line" is logged after
   acquisition, the figure is a model-load time and says nothing about the fetch; if before, it is a
   claim that 64 MB arrived and hashed in under 3 s. And "verified silently" is not an observation —
   what was observed is that acquisition emitted no refusal and `doctor` afterwards reported five files
   matching, which is `doctor`'s own hash pass rather than acquisition's. State that.
   (c) §"Re-deriving this" (`:200-205`) installs `sudo` without saying that this is what puts the host
   CPython on the image (`:28-30`) and so is what makes the `--managed-python` claim testable. A
   re-deriver who drops `sudo` as unneeded for `uv` loses the condition the section's headline
   result depends on. One clause on the `apt-get` line fixes it.

8. **[IMPROVEMENT] "`doctor` cannot supply this" is a choice stated as an impossibility.**
   `design/distribution.md:145-146`: "`doctor` cannot supply this: it reports on the *machine*, and
   the build is the one fact a bug report needs that the machine does not carry"; `README.md:396-397`:
   "the one thing `doctor` cannot infer". `doctor` is the same process and can call
   `importlib.metadata.version` as easily as the umbrella does. The sqlite-version row is the
   precedent — it "reports rather than checks", and the build is the same class — and a bug report
   wants `doctor`'s output and the version in one paste. Either add a `--` report row
   (`zikaron version  0.1.0`) to `doctor`, keeping `--version` as the cheap form, or reword both
   sentences to say `doctor` deliberately does not repeat it. At minimum delete "cannot".

9. **[IMPROVEMENT] Two of the new docstrings are the class `CLAUDE.md` §comments forbids.**
   `zikaron/core/store/store.py:114-119` narrates the repair — why the remedy is there, the
   `BAD_CONFIG`-field decision, that a user meets this first — and already carries the false claim in
   finding 1, which is the predicted failure of annotating a fix. `tests/test_store.py:290-295`
   recounts how the defect was found and cites the research note, which `CLAUDE.md` §"Project memory"
   says goes nowhere. Cut the store docstring's second paragraph to at most one sentence on why the
   project directory can be derived (`store_dir` is the `.zikaron` inside it), and the test docstring
   to one line or none — the test name already says what it asserts.

10. **[NITPICK]** `README.md:136` — the edit left one unwrapped ~170-character line. The "name
    `--harness` on a first install" claim is now stated in full three times (`:135`, `:204-210`,
    `:222`); one full statement plus a pointer drifts less. `README.md:149` "needs `uv` and nothing
    else" is contradicted by the next sentence's `curl` and `ca-certificates` — "needs `uv` and no
    Python". `FINDINGS.md:228` "Both fixes were verified" follows a list of four items — "Both code
    fixes"; and once finding 1 lands, that sentence should say the store message was verified to
    print, not that its remedy was followed.

VERDICT: NEEDS_CHANGES

## Round 2 — 2026-09-24

**Artifact reviewed**: the refreshed diff at `scratchpad/change.diff` (447 lines) and the current
state of `zikaron/core/store/store.py`, `zikaron/cli/main.py`, `tests/test_store.py`,
`tests/test_cli_front_door.py`, `README.md` §§Requirements/Install/doctor, `design/distribution.md`
§"The front door", `design/harness.md` §"Three flags", `research/m30-docker-end-to-end.md`,
`FINDINGS.md`, `FINDINGS-archive.md` §References. Independently verified this round, not taken from
the brief: that the new store message is true — `spawn_warm.py` runs `warm_helper.run`, which calls
`connect_start_if_absent`, so a session start does trigger the service's first start under both
harnesses (`harness/spec.py` maps `SessionStart` and `agentSpawn` to the same trigger), and
`Store.create` still has one production caller; that `_store_not_created` is reachable in production
only through `knowledge/scope.py:open_store`, whose `directory` is always `store_dir(scope)` =
`<scope>/.zikaron`, so `db_path.parent.parent` names the right directory; that `_resolve_harness`
reads only `CLAUDECODE` as a marker; and, by grep across `README.md`, `design/`, `zikaron/` and
`CLAUDE.md`, that nothing else in the corpus now says the installer creates a store.

### Summary judgment

All ten round-1 findings landed as described, and the two code fixes are now correct: the store
refusal names the thing that actually creates a store, and `--version` is wired, tested and
documented consistently across `main.py`, `distribution.md` and `README.md`. What remains is one
sentence in `FINDINGS.md` that the round-1 narrowing made *too* narrow — it now says push and pull
have only ever run in the hermetic suite, which the same file's §"Where the stores are" refutes —
plus a handful of consistency and precision items the round-1 fixes left behind, mostly in the
research note. One more pass and this ships.

### Findings

1. **[BLOCKER] "Remain hermetic-suite-only" is false, and `FINDINGS.md` refutes it four paragraphs
   earlier.** `FINDINGS.md:210-212`: "**Push and pull were not exercised** — no `UserPromptSubmit`
   gist block was captured and no search was called, so D12's injection and the read path remain
   hermetic-suite-only." `research/m30-docker-end-to-end.md:8-10` says the same in other words
   ("remain unexercised outside the hermetic suite"). But `FINDINGS.md:187-189` says
   `~/Trading/LeibaTrader` holds 252 memories and "every production report since M17 came from it",
   §"Owed measurements" specifies "the share of surfaced uuids fetched" over that store, and the
   `integration_kiro`/`integration_claude` tiers exist. Push and pull have run for real, many times,
   under kiro on this host. The pre-change text was precise — "nothing *automated* has ever exercised
   a real session pushing or searching" — and the round-1 fix dropped the qualifier. A fresh session
   reading the new sentence would plan the first real exercise of something that has hundreds of
   real runs behind it. Suggested `FINDINGS.md:210-212`: "**Push and pull were not exercised
   there** — no `UserPromptSubmit` gist block was captured and no search was called. Both have run
   for real under kiro on `~/Trading/LeibaTrader`; what has still never happened is a real Claude
   Code session pushing or searching on a machine other than this one, or any *automated* run of
   either." Note `:8-10`: "…so D12's injection and the search path were not exercised in this run.
   The session wrote; it was never asked to recall." — and stop there, since the note is about this
   run.

2. **[IMPROVEMENT] The research note still carries the round-1 `CLAUDECODE` wording in one place,
   so it now contradicts itself.** `research/m30-docker-end-to-end.md:116-117`: "`CLAUDECODE` is set
   only *inside* a session, not in the shell where the installer runs." Round 1 finding 4 was that
   this is false for an agent-run install, and the note's own defect 2 (`:220-221`) now says so:
   "An agent running the installer is detected, because `CLAUDECODE` reaches the processes a session
   spawns." Both sentences are in the same file about the same run. Suggested `:116-117`: "…and
   `CLAUDECODE` is exported into the processes a session spawns, not into a terminal outside one —
   which is where this install was run from."

3. **[IMPROVEMENT] "Agent-run, detection succeeds" is a Claude Code claim stated for both
   harnesses, in the document whose job is to keep the two apart.** `design/harness.md:538-541`:
   "`CLAUDECODE` is exported into the processes a session spawns … which splits the first install in
   two. Agent-run, detection succeeds; person-run into a project not yet set up, nothing says
   anything." `README.md:135-137` ("an agent asked to run the installer is detected") and
   `README.md:212-213` ("Ask your agent to run the installer and detection does succeed") say the
   same without naming the harness. `_resolve_harness` (`install/main.py:272`) reads only
   `CLAUDECODE`, and `harness.md:527-528` itself says kiro exports no marker — so a kiro agent
   running the installer into a project with no `.kiro/` (a global `~/.kiro/agents/` config, which
   is the case where the README's `--agent .kiro/agents/<your-agent>.json` does not apply) gets the
   refusal exactly as a person does. Suggested `harness.md:540-541`: "Agent-run under Claude Code,
   detection succeeds; under kiro, which exports no marker, an agent-run install is detected only
   from a `.kiro/` already in the project; person-run into a project not yet set up, on either
   harness, nothing says anything and the harness has to be named." `README.md:135`: "so a Claude
   Code agent asked to run the installer is detected"; `README.md:212-213`: "(Ask a Claude Code
   agent to run the installer and detection does succeed, because `CLAUDECODE` reaches it; kiro
   exports no marker, so there it is `.kiro/` or nothing.)"

4. **[IMPROVEMENT] The store message's install remedy is the one first-install command in the
   corpus that omits `--harness`.** `zikaron/core/store/store.py:127-128`: "if Zikaron is not
   installed there either, `zikaron install` puts it in that session's way first". The user who
   reads this is by construction on a first install, and `README.md:207` now says "Name it on a
   first install, rather than leaving it to be detected" for exactly this user; from a terminal,
   bare `zikaron install` produces a second refusal before the remedy can be followed. The chain
   does resolve, since that refusal names both `--harness` values, so this is not round 1's loop —
   but the message was rewritten to be followable, and `{project}` is already in hand. "Puts it in
   that session's way" is also the one phrase in the message a user cannot act on directly.
   Suggested `:124-129`:
   ```python
   expected=(
       "an existing, openable memory.db — nothing has run Zikaron in "
       f"{project} yet. The service creates the store on its first start, which starting an "
       "agent session in that project triggers; if Zikaron is not installed there either, run "
       f"`zikaron install --project {project} --harness claude-code` (or `--harness kiro`) first"
   )
   ```

5. **[IMPROVEMENT] The new test's negative assertion does not survive the mutation it was written
   against.** `tests/test_store.py:303`: `assert "`zikaron install` creates" not in expected`. The
   round-1 message read `` `zikaron install --project <dir>` creates it `` — which does not contain
   that substring, so this line would have passed against the very wording it exists to keep out
   (the test is red on the old message only through `:302`'s "first start"). A message that names
   both — "The service creates the store on its first start … `zikaron install --project X` creates
   it" — passes all three assertions today. Pin the relation rather than a phrase: replace `:303`
   with `assert expected.index("first start") < expected.index("zikaron install")`, which fails
   for any message that leads with the installer, whatever the surrounding words.

6. **[IMPROVEMENT] The fetch figure names a lower bound as the value.**
   `research/m30-docker-end-to-end.md:104-107`: "the five blobs land between `02:54:15.879` and
   `02:54:17.547` … So 64 MB arrived and was linked in **1.67 s** of a **3.74 s** cold start."
   A blob's mtime is when it *finished*; 1.67 s is the span between the first blob completing and
   the last completing, and the first blob's own download time — which for the 64 MB file, fetched
   in parallel with four small ones, is most of the fetch — lies before `15.879`. What the
   timestamps bound is `1.67 s ≤ fetch ≤ 3.30 s` (`14.257` → `17.556`). "Name the quantity before
   quoting a number about it": suggested "Blob mtimes are completion times, so the 64 MB fetch took
   at least the 1.67 s between the first and last blob and at most the 3.30 s from the service's
   first log line to the snapshot directory, inside a 3.74 s cold start."

7. **[NITPICK] "README's literal command" describes a README that no longer exists.**
   `research/m30-docker-end-to-end.md:115` ("`zikaron install --project .` — README's literal
   command — refuses") and `:125-126` ("README calls `--harness` an **override**"). True of the
   README shipped with `0.1.0`, false of the tree the note sits in. The note is the evidence trail
   and out of scope for sweeps, but it is being written now: "README's literal command *as published
   with `0.1.0`*" and "README *then* called `--harness` an override" keep it true after the fix.

8. **[NITPICK] "Until a permission or setting is explicitly changed" is stated as measured, and
   only its negative half was.** `design/harness.md:536-537` ("measured in
   `research/m30-docker-end-to-end.md`: a freshly trusted Claude Code project has no `.claude/`
   until a permission or setting is explicitly changed"), `README.md:209-211`, `FINDINGS.md:218-220`.
   The note (`:145-148`) observed that trusting the project and an ordinary tool use did *not* create
   it; "Claude Code writes that file when a permission rule or setting is explicitly changed" is
   stated there without an observation. Say what was seen: "a freshly trusted Claude Code project
   has no `.claude/` — neither the trust dialog nor an ordinary tool use creates one (measured)".

9. **[NITPICK] `doctor` does not open a store path.** `design/distribution.md:146-147`: "behind
   five checks that open a store path and load nothing". `doctor/checks.py:218` resolves a socket
   path from `store_dir` and opens nothing under it; "load nothing" is also not quite right, since
   `check_sqlite_vec` loads the extension. "behind five checks that resolve a socket path and load
   no model" says what it does.

10. **[NITPICK] Three small ones in `FINDINGS.md`.** (a) `:205-206` — the arrow chain puts "model
    fetch at the pinned revision" *before* "the `SessionStart` hook firing", but the hook's warm
    helper is what starts the service that fetches; swap them. (b) `:224-225` — "all fixed on
    `main`" is written from after the merge; until the operator lands the PR they are fixed in the
    tree, and a session resuming from this file on the branch reads a state that is not yet true.
    "all fixed in the tree and none of them in the release on PyPI" holds on both sides of the
    merge. (c) `:322-324` — the Q14 addition quotes “assume these conventions when working here” in
    quotation marks, but the note (`:192`) records the record as "Assume Unreal Engine conventions
    (C++/Blueprints, `.uproject` layout) when working here"; either quote it verbatim or drop the
    quotation marks.

VERDICT: NEEDS_CHANGES

## Round 3 — 2026-09-24

**Artifact reviewed**: the refreshed diff at `scratchpad/change.diff` (489 lines) and the current
state of `FINDINGS.md` §§"The release", "The install path is proven…", "`main` carries…", "Next PR",
Q14; `README.md` §§Requirements/Install/doctor; `design/harness.md` §"Three flags";
`design/distribution.md` §"The front door"; `zikaron/core/store/store.py`, `zikaron/cli/main.py`,
`tests/test_store.py`, `tests/test_cli_front_door.py`; `research/m30-docker-end-to-end.md`;
`FINDINGS-archive.md` §References. Independently verified this round, against the code rather than
the brief: every branch of `install/main.py:_resolve_harness` (`:268-297`) against the three
harness-detection passages; `KIRO.marker_variable is None` and `CLAUDE_CODE.marker_variable ==
"CLAUDECODE"` (`harness/spec.py:207,237`); `release.yml`'s tag-equals-version step and
`tests/test_ci_workflow.py:592-613`'s moving-ref guard; `doctor/checks.py`'s five `check_*`
functions; the shipped policy text the note quotes (`hook/write_policy.py:78-79,90-92` — both
quotes are verbatim or honestly elided); `design/coding-standards.md:324-331` for the lock-file
rule `FINDINGS.md:98-101` cites; and the two claims the next-PR section makes about code, which is
where this round's blocker is.

### Summary judgment

All ten round-2 findings landed as described and none introduced a regression: the three
harness-detection passages now agree with each other and with `_resolve_harness` branch for
branch, the store message is followable, the test pins the relation, and the note's fetch figure is
a bound. The one new section — the next-PR plan — is where the change is not yet shippable: it
states two things about the code that are false, in the file whose whole test is "would a fresh
session act differently", and a session starting that PR from this text would go to the wrong
function and design the change around a premise (one remaining direct path) that the indexer
refutes. Fix that section and this ships.

### Findings

1. **[BLOCKER] `FINDINGS.md` §"Next PR" makes two claims about the code that are false, and both
   are load-bearing for the PR it plans.**
   (a) `FINDINGS.md:242-243`: "**The CLI is the only path that still reaches the store directly**,
   so this deletes a second path rather than adding a capability." `zikaron/knowledge/indexer/main.py:58`
   opens `memory.db` through the *same* `scope.open_store`, and has to keep doing so: it is the
   service's own detached child (`dispatch_knowledge.py:309-314` → `detach.spawn`), the per-build
   process that loads the model (D31: "the second component that loads a model"), and its
   completing transaction writes the registry in `memory.db`. `zikaron/mcp/connection.py:137-146`
   also calls `Store.open` on every reconnect after the first, to read `meta.store_id`. So the change
   cannot be "make `open_store` go through the service": it has to split the CLI's open from the
   indexer's, and afterwards the store still has two direct readers besides the service. The framing
   "deletes a second path" is wrong and would send the PR at the shared helper. Suggested
   `:240-243`: "`zikaron/knowledge/main.py` opens `memory.db` directly through
   `zikaron/knowledge/scope.py:open_store`, while `zikaron/service/dispatch_knowledge.py` already
   serves all seven knowledge methods over RPC and the MCP server is already a thin client over
   them. **The indexer shares `open_store` and keeps it** — it is the service's own detached child
   and the process that holds the model for a build — so the change splits the CLI's open from the
   indexer's rather than rerouting the helper; `mcp/connection.py:_read_store_identity`'s
   `Store.open` stays too. What it deletes is the one *human-facing* surface that bypasses the
   service." Then name what the PR must withdraw in place, since CLAUDE.md requires it and nothing
   here says so: `zikaron/knowledge/scope.py:8-13` (the module docstring stating the rationale being
   reversed — "Requiring a service would make managing and building corpora depend on a harness
   being live", already untrue since the service starts on demand), `design/overview.md:101-102`
   (the one-page diagram: "zikaron knowledge … opens the store directly, no RPC"), and
   `design/knowledge-index.md` §9's framing of the CLI.
   (b) `FINDINGS.md:248`: "`hook/connect.py:connect_start_if_absent` is the client half and already
   exists." There is no such function in that file. `hook/connect.py` deliberately re-implements the
   sequence as `connect_once` (`:105-138`) because of the hook's stdlib-only contract — its own
   docstring (`:1-14`) says so. `connect_start_if_absent` is `zikaron/service/lifecycle.py:297`, and
   the client that already wraps it with the outer retry and `_read_store_identity` is
   `zikaron/mcp/connection.py:ServiceConnection`. The CLI is not stdlib-constrained (it imports
   `aiosqlite` today), so that is the half to reuse. Suggested: "`service/lifecycle.py:
   connect_start_if_absent` is the client half and `mcp/connection.py:ServiceConnection` already
   wraps it with retry and identity; the CLI is not under the hook's stdlib-only contract, so it
   reuses those rather than `hook/connect.py`'s stdlib re-implementation."

2. **[IMPROVEMENT] The next-PR cost sentence names the wrong condition and omits the one measured
   number that decides whether the CLI *waits* or *fails*.** `FINDINGS.md:252-253`: "the first CLI
   call in a cold project pays the 64 MB fetch". The cache is per user (`README.md:189-191`), so a
   cold *project* on a warm cache pays the ~1 s model load plus store creation, never 64 MB; only a
   cold *cache* pays the fetch. And whether it pays rather than fails is a comparison the section
   should carry: `service/context.py:229-236` blocks the create path on the artifact, so `health()`
   cannot answer before the fetch lands — at most 3.30 s in the container (note §Acquisition) —
   against `lifecycle._HEALTH_POLL_DEADLINE_SECONDS = 10.0` (`lifecycle.py:39`). Inside on that
   network; on a slower one the CLI reports "no server became reachable" while the service keeps
   fetching, and the *second* call succeeds — M17's class, now on a surface with no degraded mode.
   Suggested: "The cost is that the first CLI call on a machine whose model cache is cold pays the
   64 MB fetch, because the create path blocks on the artifact (`context.py:_open_or_create`) and
   `health()` cannot answer before it lands: 3.30 s in the container against `lifecycle`'s 10 s poll
   deadline, so it waits rather than fails there, and a slower network turns the first call into a
   transport failure the second call does not repeat. A warm cache pays the model load only."

3. **[IMPROVEMENT] `FINDINGS.md:233-235` records how a defect was found — the class §"Project
   memory" says goes nowhere — and misattributes what looped.** "…and *following* it was verified to
   loop, which is how the first attempt at that fix was caught." What looped was the *first
   attempt's* message; the message in the tree was verified to print and its remedy (start a
   session) was not followed in the container. Suggested: "`--version` was verified under a real
   `uv tool install` in the container, and the store message was verified to print there; its
   remedy was not followed there." Same section, `:249-250`: "the CLI stops being the exception to
   that" — the CLI was never an exception to *the service creates the store* (it created nothing;
   it refused). The exception it stops being is to *every human surface reaches the store through
   the service*; say that, since finding 1 shows the indexer remains a direct reader by design.

4. **[IMPROVEMENT] README's `python -m` sentence now has a second exception it does not name.**
   `README.md:223-225`: "every command below also works as `python -m zikaron.<command>` … `zikaron
   doctor` has no such form; it is new with the `zikaron` command." `zikaron --version` (`:402`) is
   below, is new with the umbrella, and has no `python -m zikaron.<command>` form — there is no
   `zikaron/__main__.py` or `zikaron/cli/__main__.py`, and `distribution.md:142` says it is a flag
   the umbrella alone answers. Suggested: "`zikaron doctor` and `zikaron --version` have no such
   form; both are new with the `zikaron` command."

5. **[NITPICK] Round-2 finding 7 was applied to one of its two sentences.**
   `research/m30-docker-end-to-end.md:129-130` still reads, in the present tense, "README calls
   `--harness` an **override** of detection", which is false of the tree the note sits in; "README
   *then* called". And `:132`: "**`--print-only` refused correctly for a harness that was genuinely
   absent**" — the rest of the paragraph says it did *not* refuse, it noted and previewed. "noted
   correctly", or "previewed correctly past".

VERDICT: NEEDS_CHANGES

## Round 4 — 2026-09-24

**Artifact reviewed**: the refreshed diff at `scratchpad/change.diff` (519 lines) and the current
state of `FINDINGS.md` in full, `research/m30-docker-end-to-end.md` in full, `README.md`
§§Requirements/Install/doctor, `design/harness.md` §"Three flags", `design/distribution.md` §"The
front door" and §3, `zikaron/cli/main.py`, `zikaron/core/store/store.py`, `tests/test_store.py`,
`tests/test_cli_front_door.py`, `FINDINGS-archive.md` §References. Independently verified this
round, against the source rather than the brief: both `scope.open_store` callers
(`knowledge/main.py:152`, `knowledge/indexer/main.py:58`); `connect_start_if_absent` at
`service/lifecycle.py:297` and `hook/connect.py`'s `connect_once` at `:105`;
`mcp/connection.py:_read_store_identity` and its `Store.open` at `:142`; `_open_or_create`
(`service/context.py:217-247`) blocking on the artifact on the create branch, and `serve(ctx, …)`
following context construction (`service/main.py:250`); `_HEALTH_POLL_DEADLINE_SECONDS = 10.0`;
`KiroTarget.plan_merges` returning `()` for `agent is None` (`install/targets.py:272-274`) and
`_install` printing the fragment when nothing merged (`install/main.py:231-236`); the fragment's
`allowedTools`/`subagent` caveats (`targets.py:288-289`); the `--format` help text
(`install/main.py:105-106`); `validate_agent_config` relayed through `complaints_about`; all seven
`knowledge_*` methods in `dispatch_knowledge.py:462-468`; the tag-equals-version step in
`release.yml:41-53` and the moving-ref regex in `tests/test_ci_workflow.py:608-613`; `pyproject.toml`'s
`requires-python` and `license`; `design/distribution.md` §3's patch/minor rule; `design/overview.md:102`;
`knowledge/scope.py:8-13`; that `--version` and `-h`/`--help` are the only flags `cli/main.py` answers;
and, for finding 2, that nothing in `install/` constrains `--agent` to the project directory and that
`research/kiro-cli-hooks-and-introspect.md:129-133,270` records kiro's global `~/.kiro/agents/`
location.

### Summary judgment

All five round-3 findings landed as described, and every claim §"Next PR" makes about the code is
now true — the callers, the client half, the deadline, the create-path blocking, the kiro
no-`--agent` path, the `--format` rule. None of the round-3 fixes introduced a false statement. What
remains is not correctness of the code claims but the plan's completeness and the file's shape:
the list of passages the next PR must correct omits the normative component-table row that most
literally states the mechanism being reversed; the kiro plan asserts a universal that kiro's global
agent location falsifies, and so lacks the case `harness.md` already names; the cost paragraph
compares a component figure against a deadline that bounds a different quantity; the D36 index line
disagrees with the row it indexes; and `FINDINGS.md` now carries second copies of `release.yml`,
`distribution.md` §3, `harness.md` and the research note that a fresh session would act no
differently without. None is a blocker alone; together they are more than nitpicks, so one more
pass.

### Findings

1. **[IMPROVEMENT] "What the PR must correct" is incomplete, and mis-describes one of its three
   entries.** `FINDINGS.md:263-268` says each named passage "states the rationale being reversed"
   and names `scope.py`'s docstring, `overview.md:102`, and `knowledge-index.md` §9. Three more
   state the *mechanism* being reversed, one of them in the normative component table:
   `design/architecture.md:16` — the `zikaron-knowledge-indexer` row: spawned "**by `python -m
   zikaron.knowledge`** directly when a person starts a build from a shell, which opens the store
   itself and never goes through RPC", plus its italic note that naming only the service "made a
   shell-started indexer with no service in the `ps` tree look impossible"; `design/overview.md:81`
   (the same "shell-started indexer with no service in the `ps` tree"); and
   `design/knowledge-index.md:1038` ("The indexer is spawned by the CLI (§9) or by the service
   handling `add`/`refresh` (§8.4)"). After the change the service spawns every indexer that a
   management verb starts, from either client. Conversely §9 (`:2365-2413`) states no rationale
   for direct access at all — it describes behaviour that changes in *mechanism*: "`add` and
   `refresh` … spawn a detached indexer and return immediately" becomes "ask the service to", and
   "every refusal a build can be given before it reads a file is given in the foreground, by the
   command that was asked" becomes a refusal relayed over RPC. Also `knowledge/main.py:7-11`'s
   module docstring ("`add` and `refresh` start one and return"). Note that `architecture.md:16`'s
   case does not vanish: an operator running the indexer's own entry point in the foreground
   (`knowledge/main.py:9-11`; §9 `:2405-2406` "running the same command in the foreground") is still
   a shell-started indexer with no service in the tree and still opens the store directly, so that
   row is reworded rather than deleted. Suggested `:263-268`: "**What the PR must correct**, because
   each states the direct open or its rationale: `zikaron/knowledge/scope.py`'s module docstring
   (*"Requiring a service …"* — already untrue, since the service starts on demand);
   `design/architecture.md`'s component-table row for the indexer (*"opens the store itself and
   never goes through RPC"* — reword, not delete: the indexer's own entry point run by hand in the
   foreground is still shell-started and still direct); `design/overview.md:81` and `:102`;
   `design/knowledge-index.md:1038` (*"spawned by the CLI (§9) or by the service"*) and §9's
   account of who spawns and who refuses; and `knowledge/main.py`'s module docstring."

2. **[IMPROVEMENT] The kiro plan's opening claim is a universal that kiro's global agent location
   falsifies, so the plan lacks the case `harness.md` already names.** `FINDINGS.md:274-278`: "An
   agent config must exist first … Creating it also creates `.kiro/`, which is what detection
   reads — so kiro's first install is the **inverse** of Claude Code's". Stable kiro reads agent
   configs from `.kiro/agents/` *or* `~/.kiro/agents/` (`research/kiro-cli-hooks-and-introspect.md:
   129-133,270`), nothing in `install/` requires `--agent` to be inside the project
   (`_refuse_agent_aliasing_a_shipped_target` is the only path check; `plan_kiro_merge` takes any
   path), and `harness.md:540-541` already states the consequence: "under kiro … an agent-run
   install is detected only from a `.kiro/` already in the project". A user whose agent lives in
   `~/.kiro/agents/` has an agent config, a project that says nothing, and needs `--harness kiro`
   — the *same* first-install outcome as Claude Code, not its inverse. Two further facts the plan
   should carry: the installer's own shipped files (`.kiro/agents/zikaron-consolidator.json`,
   `.kiro/skills/…`) create `.kiro/` on the first `--harness kiro` install whatever `--agent` said,
   so detection works from the second install on for the same reason as under Claude Code; and
   `--agent ~/.kiro/agents/<name>.json` merging into a file outside the project is a cell no test
   has run against the real binary. Suggested `:274-278`: "**An agent config must exist first**,
   and where it lives decides detection: kiro's hooks and `mcpServers` live *inside* an agent
   config (`harness.md` §"Two harnesses" table), which stable kiro reads from `.kiro/agents/` or
   `~/.kiro/agents/`. A project-local config creates `.kiro/` and detection sees it; a global one
   creates nothing in the project and the first install needs `--harness kiro` exactly as Claude
   Code's does. Either way the shipped files put `.kiro/` there, so the second install detects. Run
   both locations; `--agent` pointing outside the project has never met the real binary."

3. **[IMPROVEMENT] `FINDINGS.md` has grown into a second copy of five other places, against
   §"Project memory"'s own test.** Applying "would a fresh session act differently without this"
   to what this change added or kept:
   (a) `:89-92` — the `pypa/gh-action-pypi-publish` paragraph restates `release.yml:84-92`'s
   comment (which the paragraph itself calls normative) and `tests/test_ci_workflow.py:602-606`'s
   docstring; a session that tried to sha-pin it would be stopped by the comment and told why by
   the test. One line: "`pypa/gh-action-pypi-publish` is pinned `@v1.14.2`, never a sha — it is a
   Docker action; `release.yml`'s comment and `test_no_action_is_pinned_to_a_moving_branch` are
   normative."
   (b) `:94-96` "To cut the next one" restates `distribution.md:327-332` and `release.yml:8-11`;
   `research/m30-operator-setup.md` holds the procedure. Pointer only.
   (c) `:98-101` — the lock-file deletion landed in `cc6c896` and §6 is normative. Delete, or
   one line naming §6.
   (d) `:202-207` — the arrow chain is the note's table of contents. Keep the four firsts and the
   negative space (push/pull, macOS, behaviour); the chain adds nothing a session acts on.
   (e) `:221-223` — "The create path is the common first install" is now `harness.md:535-542`,
   normative, with the measurement pointer, and README `:208-215`. Delete.
   (f) `:232-234` — "`--version` was verified … the store message was verified to print there; its
   remedy … was not followed there" is the what-a-sweep-covered class, and the remedy is deleted
   by the next PR anyway. Delete.
   (g) `:274-295` — of the kiro paragraphs, hooks-inside-agent-config is `harness.md:82`;
   `@zikaron` in `tools`/`allowedTools` plus `subagent` is README `:264` and `targets.py:288-289`;
   the model-id rationale is README `:140-142`; the `--format` rule is `install/main.py:105-106`.
   What is *not* elsewhere and belongs here: the operator decision to bundle the run; the two
   agent-config locations (finding 2); the three content cases under the `--format` rule; what
   needs the real binary; auth unverified. Roughly half the length, decisions and cases only.

4. **[IMPROVEMENT] The cost paragraph compares a component against a deadline that bounds the
   whole.** `FINDINGS.md:257-259`: "`health()` cannot answer until the fetch lands — at most 3.30 s
   in the container — against `lifecycle._HEALTH_POLL_DEADLINE_SECONDS = 10.0`". The deadline bounds
   the wait for `health()` to *answer*, and the socket is bound only after the whole
   `ServiceContext` — the artifact wait, `Store.create`, the DDL — is built (`service/main.py:250`).
   The client-observed figure is `service_warm`, which `hook/warm_helper.py:114` logs after
   `connect_start_if_absent` returns: **3.74 s** after the service's first log line (note
   `:104-110`), plus interpreter start-up before that line, which the poll also counts. 3.30 s is
   the fetch's upper bound, one component. The conclusion (waits, does not fail) stands; the
   quantity is wrong. Suggested: "`health()` cannot answer until the fetch lands and the store is
   created: the warm helper saw it answer 3.74 s after the service's first log line in the
   container, the fetch at most 3.30 s of that, against `lifecycle._HEALTH_POLL_DEADLINE_SECONDS =
   10.0` measured from spawn."

5. **[IMPROVEMENT] The D36 index line disagrees with the row it indexes.** `FINDINGS.md:63`:
   "Obtained by `uv tool install --managed-python git+…`". `design/overview.md:186` struck `git+…`
   at M30 and names `zikaron` — PyPI, with the git URL "documented for a version that has not been
   released". `FINDINGS.md:86` then says "`README.md`'s `uv tool install --managed-python zikaron`
   and D36 now resolve", which against an index line naming the git form reads as if the git URL
   had not resolved. Pre-existing from M30, but the release text this change adds leans on it.
   Suggested `:63`: "D36 | Obtained by `uv tool install --managed-python zikaron` (PyPI; the flag
   is load-bearing), host Python still supported; MIT; model fetched never redistributed; semver
   `0.x` with an artefact-shape rule".

6. **[IMPROVEMENT] The provisioning-script benefit carries an unstated cost.** `FINDINGS.md:249-250`
   names "a provisioning script preparing a repo" as what the thin-client CLI buys. After the
   change, `zikaron knowledge add` from a script leaves a service process running until
   `idle_timeout` self-stop, beside the detached indexer it already leaves today. In a `docker
   build` `RUN` step or a CI job, everything still running at step end is killed: the build is cut
   off mid-way and the corpus is left with a dead lock holder and `reindex_required` — §9's
   "visible as a fact and not as a reason" case. Not new for the indexer; new for the service, and
   the use case named is exactly the one that meets it. Either state that the script use is a live
   shell rather than a build step, or name a foreground/`--wait` option as owed and out of this
   PR's scope. One sentence either way.

7. **[NITPICK]** `:246` "the one **human-facing** surface that bypasses the service" — the
   indexer's own entry point run in the foreground by an operator is human-facing and stays
   direct (finding 1); "the one human-facing *management* surface". `:245-246` "reads
   `meta.store_id` on reconnect" — `_read_store_identity`'s docstring (`connection.py:106-109`) has
   it run before *every* connect, returning `None` on the first when the file is absent; "on every
   connect after the first". `:249-250` "buys … **no embedder in the CLI**" — the CLI loads none
   today (`knowledge/main.py` imports no encoder; `Store.open` needs none); the gain is against
   the rejected alternative, `open_store` creating the store itself, which needs the artifact for
   the width: "and keeps the embedder out of the CLI, which the alternative — `open_store`
   creating the store — could not".

8. **[NITPICK]** `:207-208` stray wrap: "consolidator subagent correctly gated. Four" then
   "things were exercised" on the next line. Reflow the paragraph.

VERDICT: NEEDS_CHANGES

## Round 5 — 2026-09-24

**Artifact reviewed**: the refreshed diff at `scratchpad/change.diff` (515 lines) and the current
state of `FINDINGS.md` in full, `research/m30-docker-end-to-end.md` in full, `README.md`
§§Requirements/Install/doctor, `design/harness.md` §"Three flags", `design/distribution.md` §"The
front door" and §3, `zikaron/cli/main.py`, `zikaron/core/store/store.py`, `tests/test_store.py`,
`tests/test_cli_front_door.py`, `FINDINGS-archive.md` §References. Independently verified this
round, against the source rather than the brief: **the round-4 deletions** — grepped the two deleted
headings and their phrasings across the whole repository (no pointer anywhere named them) and
resolved every pointer the replacement text introduces (`distribution.md` §3 at `:313`,
`coding-standards.md` §6 at `:285` with the lock-file rule at `:324-328`,
`test_no_action_is_pinned_to_a_moving_branch` at `test_ci_workflow.py:593` whose docstring does
carry the Docker-action fact, `architecture.md` §"First run" at `:663`, and all three `research/`
files); **the kiro section** — every branch of `_resolve_harness` (`install/main.py:268-297`),
`--agent takes a path to an existing config` (`:168-169`), `KiroTarget.plan_merges` returning `()`
and `_install` appending the fragment when nothing merged (`targets.py:272-275`, `main.py:231-236`),
the `--format` help (`:105-106`), `validate_agent_config` and the model check (`targets.py:315-333`),
and both agent-config locations in `research/kiro-cli-hooks-and-introspect.md:129-133,270`; **the
next-PR section** — all three `Store.open` callers and which of them check for the file first
(`context.py:242-243` and `connection.py:138-142` do, `scope.py:97` does not), `_store_not_created`
as the `connect_failure` of every `Store.open` (`store.py:385`), `_poll_until_reachable` called at
`lifecycle.py:417` after the spawn at `:272`, `_read_store_identity`'s docstring wording "on every
call after the very first"; the release facts against `release.yml` and `pyproject.toml`
(`version = "0.1.1"`, `requires-python = ">=3.12"`); and a sweep of `design/` for other passages
stating the CLI's direct open, which found one the list omits (finding 3).

### Summary judgment

All eight round-4 findings landed as described, the deletions removed nothing a fresh session acts
on and left no dangling pointer, and the reworded kiro and next-PR sections are accurate against the
code branch for branch — with one exception, a "because" clause in the plan that the indexer's own
entry point falsifies. What is left is small and concrete: one shipped-code defect (the store
message interpolates a path into a command line without quoting it, so it fails when followed on a
path with a space), that false clause, and one passage missing from the must-correct list. No
blocker. Each is a one-line edit; if the operator ships without them, the only user-visible
consequence is the quoting.

### Findings

1. **[IMPROVEMENT] "The condition it describes stops existing" is false: the by-hand indexer still
   reaches `_store_not_created` after the PR.** `FINDINGS.md:260-261`: "`_store_not_created`'s
   remedy is deleted rather than reworded, because the condition it describes stops existing."
   `_store_not_created` is the `connect_failure` for *every* `Store.open` (`store.py:385`). Of its
   three callers, the service (`context.py:242`) and the MCP client (`connection.py:138-140`) test
   for the file before opening; `scope.open_store` (`scope.py:97`) does not, and the plan's own
   `:224-225` keeps `open_store` for the indexer. So `python -m zikaron.knowledge.indexer <name>`
   run by hand in a project with no store — the exact case `:228-229` says "stays direct" — still
   produces this error after the change. What stops existing is the *CLI's* route to it, because
   the service it then talks to creates the store. The action (delete the remedy) is right; the
   reason is wrong, and a session that believes the condition is gone will delete the function's
   test and be surprised by the message later. Suggested `:260-261`: "**`_store_not_created`'s
   remedy is deleted rather than reworded**: the CLI no longer meets it, since the service it now
   talks to creates the store; the by-hand indexer — `open_store`'s remaining caller — still can,
   and a one-line refusal is enough there. `tests/test_store.py::
   test_a_missing_store_points_at_the_service_rather_than_the_installer` goes with the remedy."

2. **[IMPROVEMENT] The store message prints a command line with an unquoted path in it.**
   `zikaron/core/store/store.py:128`: `` f"`zikaron install --project {project} --harness
   claude-code`" ``. A project directory with a space — `/Users/x/My Project`, ordinary on macOS,
   which D35 supports — prints `--project /Users/x/My Project`, and the installer parses that as
   `--project /Users/x/My` plus a stray positional, which is an `argparse` usage error. This is the
   class round 1 blocked on: an instruction that fails when followed, in a message rewritten over
   four rounds to be followable. The corpus already treats every other printed command as shell
   source: `knowledge/main.py:309-310` (`shlex.quote(name)`, `shlex.join(argv)`) and
   `install/entries.py:186-193`, whose docstring gives the reason. Suggested: `import shlex` and
   `` f"`zikaron install --project {shlex.quote(str(project))} --harness claude-code`" ``. Two
   things ride on the same line. (a) `store_dir` does not resolve its argument (`paths.py:42-51`)
   and `knowledge/main.py`'s `--project` is `type=Path` with no `resolve`, so `--project .` makes
   the message read "nothing has run Zikaron in . yet"; `project.absolute()` before quoting fixes
   that without following symlinks. (b) `tests/test_store.py:301` — `assert str(tmp_path) in
   expected` — still holds for an unremarkable `tmp_path`; to pin the quoting, use `tmp_path /
   "my project"` as the project and assert `shlex.quote(str(project))` is in the message.

3. **[IMPROVEMENT] "What the PR must correct" omits the failure-mode row that names `scope.py`'s
   open.** `design/knowledge-index.md:2468` (the `memory.db` unreadable row): "**the command refuses
   with `RegistryUnavailableError`, raised by `knowledge/scope.py` when `Store.open` fails — so
   `status` never runs** … On the RPC path the service cannot start, so there is no listing either."
   After the change the CLI *is* the RPC path, and the row's two halves describe one route;
   `scope.py`'s `RegistryUnavailableError` survives for the indexer only. Add it to
   `FINDINGS.md:253-260`. Worth one clause while there, because it bears on what the PR reuses:
   §9's "every refusal a build can be given before it reads a file is given in the foreground"
   (`:2395`) survives the change only through `_read_store_identity`'s own `Store.open`
   (`connection.py:141-142`), which raises the specific error before `connect_start_if_absent` is
   ever called — otherwise an unreadable store costs the CLI the full 10 s poll and a generic "no
   server became reachable". So `:226-227`'s "stays too" is load-bearing, not incidental: "stays
   too, and is what keeps §9's foreground refusal true — without it an unreadable store is a 10 s
   timeout with no reason".

4. **[NITPICK] The store message's kiro remedy omits `--agent`.** `store.py:128` "(or `--harness
   kiro`)". Under kiro without `--agent` the install exits 0 with the entries appended as a note to
   paste (`install/main.py:231-236`); a user who pastes nothing starts a session whose agent has no
   hook, no service starts, and the refusal repeats. The chain resolves through the note, so this is
   not round 1's loop — but `README.md:217-221` says "also name the config for the agent you
   actually work in", and "(or `--harness kiro --agent <your-agent-config>`)" costs nothing.

5. **[NITPICK] The note still states the unobserved half of the `.claude/` claim as fact.**
   `research/m30-docker-end-to-end.md:152`: "Claude Code writes that file when a permission rule or
   setting is explicitly changed." Round 2's finding 8 corrected this in `harness.md`, `README.md`
   and `FINDINGS.md` to what was seen — neither the trust dialog nor an ordinary tool use creates
   it — and the note, which is the evidence for those three, kept the inference. "presumably when a
   permission rule or setting is explicitly changed — not observed here."

6. **[NITPICK] "An agent config must exist first" lost its reason in the rewrite.** `FINDINGS.md:267`.
   Round 4's suggested text carried why (kiro's hooks and `mcpServers` live *inside* an agent config)
   and what enforces it; the applied text opens with the conclusion. Half a sentence: "**An agent
   config must exist first** — kiro's hooks and `mcpServers` live inside one, and `--agent` refuses
   a path that is not a file — **and where it lives decides detection.**"

VERDICT: NEEDS_CHANGES

## Round 6 — 2026-09-24

**Artifact reviewed**: the refreshed diff at `scratchpad/change.diff` (549 lines) and the current
state of `zikaron/core/store/store.py`, `zikaron/cli/main.py`, `tests/test_store.py`,
`tests/test_cli_front_door.py`, `README.md` §§Requirements/Install/doctor, `design/harness.md`
§"Three flags", `design/distribution.md` §"The front door" and §3, `FINDINGS.md` §§"The release"
through "Next PR" and Q14, `FINDINGS-archive.md` §References, `research/m30-docker-end-to-end.md` in
full. Independently verified this round, against the source rather than the brief: **the store
message as a whole** — `open_connection` opens `file:…?mode=rw` (`connection.py:176-177`) and
`connect_failure` is scoped to the connect alone, so what reaches `_store_not_created` is an absent
file (a write-protected one opens read-only under `mode=rw` and fails later, at a pragma), which
makes "nothing has run Zikaron in … yet" true of what reaches it; `shlex.quote` on the test's path
yields the quoted form containing the unquoted one; `install/main.py:65-81` takes `--project`,
`--harness` (choices `kiro`/`claude-code`) and `--agent` under exactly those names; **the
`--version extra` question the brief left to the operator** — `argparse`'s own `_VersionAction`
and `_HelpAction` call `parser.exit()` the moment the flag is consumed, before any later argument is
read, so `zikaron install --help extra` is already status 0 from the parsers the umbrella dispatches
to and the umbrella's `--version extra` agrees with them; `main.py:109-110`'s docstring is not
contradicted and **no edit is needed**; `_reject_symlinked_store_dir` prefixes `Path.cwd()` to a
relative `store_dir` (`permissions.py:53`), which bears on finding 4; `research/
python-portability-probes.md:77-81` and `design/schema.md:7-11` for finding 2; `release.yml:41-53`
for finding 3; `zikaron/knowledge/indexer/__main__.py` exists, so the `python -m` form
`FINDINGS.md` names is real; the D36 index line against `overview.md:186`; and the archive's
"four defects" against the note's list of four.

### Summary judgment

All six round-5 findings and the six whole-read fixes landed as described, and none of them put a
defect into the shipped code: the store message is now correct as a whole — prose path unquoted,
command line quoted, the service named before the installer — on an ordinary path and on one with
a space, and the `--version` question needs no change because the parsers it would have to agree
with already behave the same way. What remains is prose and one test: the README paragraph this
change added to say what a stripped machine lacks omits `git` for the `git+` form it explicitly
covers; the research note claims a "first" that an earlier research file and the normative schema
document refute; "names the build" overclaims for the install path README recommends for unreleased
versions, and the `0.1.1` bump with no release makes that concrete; and the `.absolute()` guard has
no test that would go red without it. One short pass.

### Findings

1. **[IMPROVEMENT] "Both of those need `uv` and no Python" — the second one also needs `git`, and
   the note's own baseline says a stock image has none.** `README.md:158-160` was moved below both
   `uv tool install` commands and reworded to cover both, and its job is to say what a stripped-down
   image must install first (`curl`, `ca-certificates`). `uv` does not bundle git; it shells out to
   the `git` executable for every `git+` source, and `research/m30-docker-end-to-end.md:28` records
   `ubuntu:26.04` as having "no `git`". So a reader following the second command on the image the
   note describes gets a uv error the paragraph was written to pre-empt. The defect is created by the
   whole-read reword — as a paragraph between the two commands it applied to the PyPI form only.
   Suggested `:158`: "Both of those need [`uv`](…) and **no Python**, which is the point; the
   `git+` form also needs `git` on `PATH`, which `uv` calls rather than bundles. `uv`'s own
   installer is …".

2. **[IMPROVEMENT] "The first distro Python measured rather than cited" is false, and the corpus
   says so twice.** `research/m30-docker-end-to-end.md:38-41`. `research/python-portability-probes.md:
   77-81` (2026-09-20) measured host `/usr/bin/python3` **3.12.3 (Ubuntu)**, SQLite 3.45.1, with
   FTS5, `enable_load_extension` *and* a real `vec0` `MATCH … k=2` query all passing;
   `design/schema.md:9-10` records the same build as verified. The container's probe (`:44-52`) is
   the weaker of the two — it calls `enable_load_extension(True)` and reads the FTS5 compile option,
   and probes.md `:85` itself says "the flag being present does not prove the extension loads". The
   claim that matters ("not one of the risky builds") survives, since the flag being on is exactly
   what "reported off" is about; the "first" does not. Suggested: "…and is the second distribution
   build measured rather than cited — this host's Ubuntu 3.12.3 was probed with a real `vec0` query
   in `research/python-portability-probes.md` §4; this probe checks the flag and the FTS5 compile
   option only, which places the build outside the 'reported off' class and proves nothing further."

3. **[IMPROVEMENT] "Names the build" is true of a PyPI install and false of the `git+` install
   README offers two lines above it, and `0.1.1` without a release is where that bites.**
   `README.md:403-404` ("`zikaron --version` names the build, which is the first thing to put in a
   bug report"), `cli/main.py:98` ("names this build"). `distribution.md:142-143` has it right
   ("reports the installed distribution's version"). `README.md:154-155` recommends `git+…` "for a
   version that has not been released", and `FINDINGS.md` records that `pyproject.toml` now says
   `0.1.1` with no release planned and "the number moves again when more ships" — so every `git+`
   install between now and the next bump reports `0.1.1`, one number over every commit `main`
   takes in the interval; if the next release *is* `0.1.1`, the pre-tag trees and the release share
   a name with different contents. In both cases the bug report the flag exists for carries a number
   that does not identify a build. (An editable install has the same property in miniature: it
   reports the version its metadata was written with, which lags a `pyproject.toml` bump until
   reinstall.) Two fixes, the first sufficient. (a) Wording: README `:403` "names the version you
   installed — for a PyPI install that is the build; a `git+` install reports whatever
   `pyproject.toml` said at that commit, which is not a release, so a bug report from one needs the
   commit as well"; `main.py:98` "names this version". (b) Mechanism, operator's call: carry a PEP
   440 pre-release between releases — `0.1.1.dev0` — so an unreleased tree never shares a number
   with a release; `release.yml:41-53` already refuses a tag that disagrees with the file, so the
   `.dev0` is forced off at release time and nothing else changes. Either way `distribution.md` §3
   should say what the number means *between* releases, which it currently does not.

4. **[IMPROVEMENT] The `.absolute()` guard has no mutation coverage, and one of the test's four
   assertions pins nothing.** `tests/test_store.py:296-305`. `tmp_path` is absolute, so removing
   `.absolute()` from `store.py:119` leaves the test green — the `--project .` case round 5 raised
   and the brief says was fixed is not what the test exercises. And `assert str(project) in
   expected` is implied by the next line, since `shlex.quote(str(project))` contains
   `str(project)`; it does not pin the unquoted prose form it reads as pinning. Suggested: take
   `monkeypatch`, `monkeypatch.chdir(tmp_path)`, open `Path("my project") / ".zikaron"` — relative,
   which `_reject_symlinked_store_dir` accepts by prefixing the cwd — and assert
   `shlex.quote(str(tmp_path / "my project")) in expected` for the command line and
   `f"in {tmp_path / 'my project'} yet" in expected` for the prose; that is red without
   `.absolute()` and red if either form loses its shape. While there: `Path.absolute()` does not
   normalise, so `--project ..` prints `/home/u/proj/..` in both places; `Path(os.path.abspath(…))`
   normalises lexically without following symlinks, if that is judged worth a line.

5. **[NITPICK] "The paragraph below says why" now points at the wrong paragraph.** `README.md:149`,
   the comment on the recommended command. Since the `uv` paragraph moved below both commands, the
   paragraph below is about `uv` and `curl`; the reason for `--managed-python` is at `:177-182`.
   "the paragraphs under 'Why `uv` is recommended' say why".

6. **[NITPICK] "Its own installer" has "Python" as its nearest noun, twice.** `README.md:158` ("need
   `uv` and no Python, which is the point. Its own installer is …") and
   `research/m30-docker-end-to-end.md:31` ("assumed `uv` had arrived from somewhere. Its own
   installer is a `curl` pipe"). "`uv`'s own installer" in both.

7. **[NITPICK] The one-line comment is still the annotation of the fix.** `store.py:120-121`
   "# Measured: unquoted, a project path containing a space …". `shlex.quote` on a command line the
   message tells the reader to run needs no justification, and the test's docstring
   (`test_store.py:293-295`) already carries the observation. The `# Measured` prefix elsewhere
   (`harness/spec.py:224,257`, `core/indexing/encoder.py:283`) marks a non-obvious measured
   constant or harness behaviour, not a standard-library idiom. Delete the two lines.

VERDICT: NEEDS_CHANGES

## Round 7 — 2026-09-24

**Artifact reviewed**: the refreshed diff at `scratchpad/change.diff` (564 lines) and the current
state of `zikaron/cli/main.py`, `zikaron/core/store/store.py`, `tests/test_store.py`,
`tests/test_cli_front_door.py`, `README.md` §§Requirements/Install/Verify read end to end,
`design/distribution.md` §"The front door" and §3, `design/harness.md` §"Three flags",
`FINDINGS.md` §§"The release" through "Next PR", `FINDINGS-archive.md` §References,
`research/m30-docker-end-to-end.md` in full. Independently verified this round, against the source
rather than the brief: **the two whole-read fixes** — pytest 9.1.1's `TempPathFactory.getbasetemp()`
(`.venv/lib/python3.12/site-packages/_pytest/tmpdir.py:159,162`) calls `.resolve()` on the temp
root on *both* branches, and `mktemp` builds under that root without un-resolving it, so `tmp_path`
is already the physical path on every platform — which bears on finding 1; **both mutations** —
`Store.open` (`store.py:382-387`) builds `db_path` from the `store_dir` it was handed, and
`_reject_symlinked_store_dir` (`permissions.py:53`) prefixes `Path.cwd()` to a *local* copy without
altering what `open` uses, so a relative `store_dir` does reach `_store_not_created` relative and
dropping `.absolute()` or `shlex.quote` reddens the test as the brief says; `Path('.').absolute()`
yields the cwd with no trailing `/.`, so `--project .` prints cleanly; the `git+` claim — `uv`
shells out to `git` for git sources and bundles none; `research/python-portability-probes.md:81`
carries the host 3.12.3 row with the real `vec0` KNN column the note now cites, under the §4 heading
it names; `cli/main.py`'s `from importlib.metadata import … version` is inside the function, so the
monkeypatch in `test_version_is_honest_when_no_distribution_is_installed` is seen at call time; the
three `__main__.py` files under `zikaron/` (`install`, `knowledge`, `knowledge/indexer`) against
README's "no such form" sentence; and `distribution.md` §3 (`:313-332`) for finding 2. The `sed -i`
disclosure produces no finding: the function is as the diff shows and both guards hold.

### Summary judgment

All seven round-6 findings landed as described, `README.md` §Install and §Verify now read
coherently end to end — one recommendation, its `git+` twin, what both need, the alternative, the
reasons, then the project install with the harness named — and nothing in the shipped code is
wrong: the store message, the umbrella's `--version`, and both tests do what they claim. Two things
remain, both created or left by this round rather than carried from earlier ones. The whole-read fix
to `tests/test_store.py` corrected a macOS failure that pytest's own `tmp_path` precludes, and
recorded the fictitious failure in a three-line comment — the exact class `CLAUDE.md` names as the
most reliable way to create the next defect. And the `0.1.1` bump this diff carries makes
`distribution.md` §3's "`pyproject.toml` is what the version *is*" true only at tag time, and the
sentence round 6 asked for to say what the number means between releases was not written. Both are
one edit each.

### Findings

1. **[IMPROVEMENT] The comment at `tests/test_store.py:302-304` asserts a macOS failure that
   cannot happen, and the change it justifies fixed nothing.** It reads: "on macOS that is the
   resolved `/private/var/...` where `tmp_path` is the `/var/...` symlink. Comparing against
   `tmp_path` would pass on Linux and fail on the required macOS job." pytest resolves the temp
   root before deriving any `tmp_path` from it — `TempPathFactory.getbasetemp()` ends in
   `basetemp.resolve()` on the `--basetemp` branch and `Path(from_env or
   tempfile.gettempdir()).resolve()` on the default one (`_pytest/tmpdir.py:159,162`, pytest
   9.1.1 as pinned) — so on the macOS job `tmp_path` is already `/private/var/…`, `chdir` to it
   followed by `Path.cwd()` returns the same string, and the previous form of the test would have
   been green there. The brief's verification could not have caught this: the long-`TMPDIR` trick
   reproduces macOS's path *length*, not the `/var → /private/var` symlink, so it exercised nothing
   the comment claims. The code as it stands is correct either way — `Path.cwd()` is what
   `.absolute()` prefixes, so comparing against it is the more direct statement — but the comment
   is a false claim about CI behaviour sitting in the suite, and the next reader who "fixes" another
   test the same way, or reasons from it that `tmp_path` is unresolved on macOS, inherits the error.
   **Suggested change**: delete the three comment lines (`:302-304`) and keep `project = Path.cwd()
   / "my project"`. If a reason is wanted at all, one clause on `:305` — `# what absolute()
   prefixes` — is the whole of it.

2. **[IMPROVEMENT] `design/distribution.md` §3 says nothing about what the number means between
   releases, and this diff is what makes that gap live.** Round 6's finding 3 asked for it in both
   of its branches ("Either way `distribution.md` §3 should say what the number means *between*
   releases"); branch (a) was applied to `README.md:406-409` and `cli/main.py:77-78`, branch (b)
   was declined, and the §3 sentence was neither written nor declined. §3 (`:327-328`) states
   "`pyproject.toml` is what the version *is*" and "the file is the thing PyPI receives", and
   `:324-325` says `0.1.0` is the first version with this scheme — all true at the moment a tag is
   cut, and now false in between: the tree says `0.1.1`, nothing is published under it, and the
   same document's new paragraph at `:142-147` introduces the flag that reports that number. The
   policy exists — `FINDINGS.md` §"Next PR" records it ("a CLI flag does not earn one, and the
   number moves again when more ships"; "only load-bearing at the moment a tag is cut") — but
   `FINDINGS.md` is working memory, not the normative doc, and §"Project memory" says a rule
   belongs in the rule. **Suggested change**, after `:332`: "**Between releases the file runs ahead
   of PyPI.** It is bumped when user-facing change lands, not when a release is cut, so a `git+`
   or checkout install reports a number no release carries, and `--version` (§"The front door")
   identifies a build only where that number has a tag. A bug report from an unreleased install
   needs the commit as well."

3. **[NITPICK] README's `--version` paragraph covers two of its three install paths.**
   `README.md:406-409` names the PyPI install (the build) and the `git+` install (the commit's
   `pyproject.toml`) but not the third path it documents at `:163-169`, the editable checkout,
   which reports the version its metadata was written with at `pip install -e .` and lags a later
   `pyproject.toml` bump until reinstalled — this repository's own `.venv` is an instance. One
   clause on `:409`: "…needs the commit as well; a source checkout reports whatever the file said
   when it was last `pip install -e`'d."

4. **[NITPICK] The note's re-derivable probe depends on SQLite's double-quoted-string fallback.**
   `research/m30-docker-end-to-end.md:50-51`: `where compile_options = \"ENABLE_FTS5\"`. In
   SQLite a double-quoted token is an identifier first and a string literal only by the `SQLITE_DQS`
   misfeature, which the amalgamation enables by default and a build compiled with
   `-DSQLITE_DQS=0` rejects as `no such column: ENABLE_FTS5`. It ran here, and the block exists so
   the next build can run it; `print("fts5:", "ENABLE_FTS5" in [r[0] for r in c.execute("pragma
   compile_options")])` asks the same question with no quoting inside the SQL and no dependence on
   the fallback.

VERDICT: NEEDS_CHANGES
