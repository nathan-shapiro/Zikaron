# M40-2 — brief review

Artifact: `design/build-plan.md` §"M40-2 — A command no one should paste, and a log that keeps why a
build died" (lines 6691–6813 at the time of each round). Reviewed against the code and the specs the
brief cites; the rest of `build-plan.md` is not under review.

## Round 1 — 2026-10-20

**Summary judgment.** The mechanism is sound and implementable as written: the dispatcher does hold
the store directory and the id, `detach.spawn` is the only redirector so a by-hand run is untouched,
the indexer already puts every refusal on stderr and every uncaught exception reaches Python's
handler, `orphan_candidates` filters on `.db`, and the invariants each name a mutation that would
redden a test. What is not yet complete is the document and comment sweep: two normative passages
that go false are outside the brief's list (one of them in `design/overview.md`, the entry point,
and invisible to done-when 2's literal grep), the comment predicate misses the class that reasons
from the output being *discarded* and so misses two files, and the brief does not say where
`build_log` is computed — which the code constrains more than the brief admits. One blocker, the
rest improvements; all cheap.

### Findings

1. **[BLOCKER] Two passages that go false are outside the brief's document list, and done-when 2
   would not catch the first.**
   - `design/overview.md` §2 "Shape of the system, in one page", lines 93–94: *"What a person can
     still start by hand is the indexer *itself*, through the foreground command a build result
     prints"*. After M40-2 no build result prints a command. The phrase is "foreground command",
     not `foreground_command`, so done-when 2 ("only this brief names it") passes with the sentence
     still there. (Line 119's diagram row, *"the same build, in the foreground"*, stays true.)
   - `design/schema.md` §"The `event` log, per kind", the nullability table's `knowledge_build` row
     (line 786): *"which a re-run of the printed `foreground_command` never has"*. Done-when 2's
     grep does catch this one, but the normative list names only §"File permissions", §"What is
     instrumented" and §"Migration posture", so a builder working from the list misses it. Note
     for the builder: `tests/test_event_kinds.py::design_nullable` parses that table, so the
     field-names column must keep its shape while the prose cell is reworded.

   Suggested change: add both to the brief's normative list and to item 4 — *"`design/overview.md`
   §2's sentence on what a person starts by hand"* and *"`design/schema.md` §"The `event` log, per
   kind"'s nullability row for `knowledge_build`"* — and rewrite done-when 2 as a predicate by
   meaning rather than by token: *"No code writes or reads `foreground_command`; and no passage in
   `design/`, `README.md`, `zikaron/` or `tests/` says that a build result prints a command, or that
   a detached build's output is discarded or goes nowhere, other than this brief."*

2. **[IMPROVEMENT] The comment predicate in item 4 names two classes and the corpus has three, so
   two files are missing — and `tests/` is excluded entirely.** Item 4 covers comments that
   *"reason from the printed command or from the three files"*. A third class reasons from the
   output being discarded, with no mention of a command:
   - `zikaron/core/knowledge/builds.py` module docstring, lines 3–7: *"spawned detached, with its
     output discarded and nowhere to report a refusal to … but by then there is nobody to tell"*.
     Not in the brief's list.
   - `zikaron/core/knowledge/reporting.py` `LockReport` docstring, line 76: *"leaves nothing at all
     to say a detached build died: its output went nowhere"*. Not in the list. (Its twin sentence in
     `knowledge-index.md` §8.5 line 2601 is covered, since §8.5 is normative here.)
   - `zikaron/knowledge/indexer/main.py` line 67, *"a refusal nobody will ever see"*, and
     `zikaron/knowledge/main.py` line 327, *"its own output went nowhere"* — in listed files, but
     matched by this third class and not by either named one, so a builder applying the predicate
     literally skips them.

   Test docstrings carry the same premise and item 4 is scoped to `zikaron/`:
   `tests/test_knowledge_cli.py` lines 792, 806, 965 and the assertion message at 1462;
   `tests/test_knowledge_indexer.py` line 341; `tests/test_project_scope.py` line 92;
   `tests/test_knowledge_build_log.py` lines 215 and 290;
   `tests/test_service_knowledge_management.py` line 1179;
   `tests/test_knowledge_cli_integration.py` line 231 (the test item 8 of the invariants already
   replaces).

   Suggested change: state the predicate as *"comments and docstrings, in `zikaron/` and `tests/`,
   that reason from the printed command, from a detached build's output being discarded, or from
   the three files"*, and add `core/knowledge/builds.py` and `core/knowledge/reporting.py` to the
   list.

3. **[IMPROVEMENT] Where `build_log` is computed and carried is unstated, and the code constrains it;
   item 4's "code that changes" trio contradicts item 1.** `reporting.Status` is `summary` plus
   `details: Details | None` and carries neither the registry id nor the store directory;
   `serialize_knowledge.KnowledgeBaseJson` holds a `Status` and a `detailed` flag and nothing else.
   For `status` to report the path for a corpus whose database will not open — item 2's own
   requirement, and the third assertion of the `status` invariant — the existence check has to run
   where both inputs are known, which is `reporting.observe` (it already builds `db_path` from
   `store_dir` and `registered.id`), and the value has to ride on `Status` beside `details`, not
   inside `Details`, which is `None` in exactly that case. That is a code change to
   `core/knowledge/reporting.py`, which the brief names nowhere. Separately,
   `KnowledgeRemoveResult.as_json` builds its snapshot with `detailed=True`, so `build_log` cannot
   ride the `detailed` flag without reaching `remove`'s snapshot, which item 2 forbids;
   `KnowledgeStatusResult` needs a switch of its own. And item 4 says *"the code that changes in
   `service/serialize_knowledge.py`, `service/dispatch_knowledge.py` and `knowledge/main.py`"*
   while item 1 has `core/knowledge/paths.py` (the path builder), `knowledge/indexer/detach.py`
   (the open and the redirect) and `core/knowledge/lifecycle.py` (the unlink) changing code too.

   Suggested change: in item 2, *"computed by `reporting.observe` from the store directory and the
   id — a stat, whether or not the database opened — carried on `Status` beside `details`, and
   emitted by `KnowledgeStatusResult` alone"*. In item 4, drop the trio and either state the
   predicate (*"every module items 1–3 touch"*) or list all of `core/knowledge/paths.py`,
   `core/knowledge/reporting.py`, `core/knowledge/lifecycle.py`, `knowledge/indexer/detach.py`,
   `service/serialize_knowledge.py`, `service/dispatch_knowledge.py`, `knowledge/main.py` and
   `mcp/primary.py`.

4. **[IMPROVEMENT] The `--wait` failure the log is most for is the one item 3's wording leaves
   out.** *"a build this call started that ended unusable is reported with its log's path"* is
   `_report_terminal_states`' vocabulary, which covers only a build that took its lock. A spawned
   child refused *before* the lock — an unknown name after a `remove`, a missing root, a database
   that will not open — never moves the mark, so `_await_builds` (lines 500–505) reports it as
   `failed <name>: no build started within 60s` and puts it in `dead`, never in `unusable`. That is
   precisely the refusal item 4 says *"now reaches its log"*, and the last poll's entry carries
   `build_log` for it as for any other. The `_explain_detachment` note still fires for it
   (`failed_waits & set(plan.started)` is non-empty), so the reader is pointed at `status`, but the
   path the brief promises is not printed.

   Suggested change: item 3 — *"under `--wait` a build this call started that ended unusable **or
   never appeared** is reported with its log's path, which the wait's last `status` poll
   carries"*; the matching invariant gains a second mutation — *"(the never-appeared line left
   without the path)"*.

5. **[IMPROVEMENT] The one-writer rationale names the wrong mechanism, and the guard against the case
   it misses is one flag.** *"a corpus's lock already admits one build at a time, so it has one
   writer"* — the lock is taken about 1.2 s after the spawn, and the log is opened and emptied *at*
   the spawn. What keeps a second service spawn out of that window is invariant 19's
   `SpawnedBuilds.loading()` (`service/spawned_builds.py`), and the lock takes over only once the
   mark has moved; so the true property is *"the service spawns at most one live child per corpus,
   and only service spawns write the log"* — within one service. Across a service restart inside
   that window the new service has no table (its own docstring says so: *"one a previous service
   spawned, shows itself only by its lock"*), spawns a second child, truncates the log the first
   holds open, and both write from offset 0, so the later writer overwrites the earlier's bytes.
   Rare; but this sentence is the one that replaces the spec's rejection in `knowledge-index.md` §9
   and `coding-standards.md` §6, so it should say what actually holds.

   Suggested change: reword to the mechanism above, and open the log with `O_APPEND | O_TRUNC`, so
   the rare two-writer case interleaves lines rather than overwriting — the *"emptied at the next
   spawn"* invariant's mutation becomes *"(`O_TRUNC` dropped)"*, and `O_APPEND` costs nothing.

6. **[IMPROVEMENT] A normative pointer is misattributed.** The brief cites §8.4 for *"the passage
   beginning 'Every refusal a build can be given before it reads a file'"*. That passage is in
   `design/knowledge-index.md` §9 "CLI surface" (line 2950), beside the `--wait` prose, not in §8.4
   (lines 1935–2472). `tests/test_design_pointers_resolve.py` passes because it resolves section
   names, not where a quoted passage sits. Suggested change: *"§8.4 (what the build-starting verbs
   return, what `remove` unlinks), §9 (the passage beginning …)"*.

7. **[NITPICK] No invariant covers `zikaron knowledge status` printing `build_log` for the corpus
   that needs it.** `_print_details` (`knowledge/main.py` line 717) returns early when `root_path`
   is absent, so a `build_log` line placed with the diagnostic lines would not print for an `error`
   corpus — the case item 2 calls *"when the log is most wanted"*. Add to the `status` invariant:
   *"and `zikaron knowledge status` prints it for a corpus whose database will not open (the line
   placed inside the diagnostic half's guard)"*.

8. **[NITPICK] Say what a log that cannot be opened does to the spawn, and that the descriptor is
   closed on a failed `Popen`.** `os.open` raising (the `knowledge/` directory removed by hand, a
   full disk) happens before `Popen`; through `_naming_the_store` it becomes `store_unavailable` and
   no build starts, which is defensible — a filesystem that cannot create an empty file cannot
   write the index either — but the brief should choose it rather than leave it to the builder,
   and item 1's *"closes its own copy once the child holds one"* should cover the `Popen`-raises
   path too, since the service is long-lived.

9. **[NITPICK] Stream ordering in the log.** The child's stdout to a regular file is block-buffered
   and its stderr line-buffered, so every stderr line lands before every stdout line whatever the
   real order — a `failed: …` from the store's close after the report would sit above `built …`.
   Nothing is lost, since the indexer prints its report last. If order should read true,
   `PYTHONUNBUFFERED=1` in the per-spawn environment copy costs nothing and leaves the indexer and
   its argv unchanged. Optional.

10. **[NITPICK] Say whether the argv plumbing goes, and which reason for the environment channel
    survives.** `Spawned.argv`, `_spawn`'s `spawned` map and `KnowledgeBuildResult.spawned` exist
    only to carry `foreground_command`; after item 3 they are dead. And `detach.py`'s docstring
    reason for `op_id` travelling in the environment (*"a flag the printed form stripped would break
    that identity"*) loses its premise; the surviving reason — an attribution token is not an input
    that changes what a build does — is the one to keep, and saying so in the brief stops the
    builder re-deciding the channel. (`schema.md`'s `spawned_by_op_id` paragraph in §"What is
    instrumented" has the same two-reason structure and is already in the list.)

VERDICT: NEEDS_CHANGES

## Round 2 — 2026-10-20

Artifact at lines 6691–6840. Every round-1 finding is applied as described, and I re-checked the
mechanism the applied text now rests on rather than taking the brief's "verified myself" line for it:
`_naming_the_store` wraps every knowledge handler (`dispatch_knowledge.py` line 655), so an `OSError`
from the log's open inside `_spawn` does reach the caller as `store_unavailable`; `reporting.observe`
is the only constructor of `Status` any verb reaches (`gather` and `without_details` have no other
caller in `zikaron/`), so computing `build_log` there covers `add`, `rename`, `refresh`, `remove` and
`status` alike; `_print_details` returns before the diagnostic lines when `root_path` is absent, as
item 2 says; `orphan_candidates` filters on `.db`; invariant 19's table (`spawned_builds.py`) plus
`builds.plan`'s `already_indexing` on a running holder is exactly "at most one live child per corpus"
within one service; and `O_APPEND` is a property of the open file description, so the child inherits it
and the restart case interleaves as item 1 claims.

**Summary judgment.** The mechanism is sound and the brief is now specific enough to build from. What
is left is in the acceptance criteria and the work list, not the design: done-when 2 as written is
false against a landed brief in `design/build-plan.md` itself; item 4's comment sweep, in being made
precise, acquired a clause that excludes three `zikaron/` sites and the tests of untouched modules,
so the work list is now narrower than the done-when that checks it; and the one integration test the
brief specifies reads the log at a moment the indexer has not finished writing it. One blocker with a
one-clause fix, two improvements, three nitpicks.

### Findings

1. **[BLOCKER] Done-when 2 cannot be met as written, because `design/build-plan.md` is in `design/`
   and M31's landed brief says what done-when 2 forbids.** Line 3473: *"The CLI prints a `foreground`
   line that reproduces a detached build, and it prints the argv the spawn reported"*; lines
   3608–3611: *"`KnowledgeBuildResult` carries the created database path and the per-corpus spawn
   argv … a second construction is the defect the `foreground` line exists to avoid."* Both say a
   build result prints a command; neither is this brief; both are in `design/`. So the builder reaches
   the gate and must either rewrite M31's record of what it shipped or report done-when 2 unmet — a
   decision the brief should make, not the builder.

   Suggested change, done-when 2: *"… other than this brief and the landed briefs above it, which
   record what each milestone shipped as it stood."* The alternative — adding §M31's two passages to
   item 4 — rewrites a landed brief into saying M31 did not ship the thing it shipped, which is the
   record falsified rather than kept current; the exemption is the right one. (FINDINGS.md's line 155
   is outside done-when 2's scope and needs nothing.)

2. **[IMPROVEMENT] Item 4's comment predicate was widened to the right three classes and then
   re-narrowed by its scope clause, so the work list disagrees with done-when 2.** Item 4 now reads
   *"… in every module items 1–3 touch, and in `core/knowledge/builds.py`'s module docstring and
   `core/knowledge/reporting.py`'s `LockReport` besides."* That set excludes sites that carry the
   premise and that done-when 2 — a predicate over all of `zikaron/` and `tests/` — catches:
   - `zikaron/core/events.py` lines 928–929, `KnowledgeBuildEvent`'s docstring: *"which a re-run of
     a printed `foreground_command` never has"* — the code twin of the nullability row item 4 *does*
     list, in a module no item touches (the fence keeps `knowledge_build` rows unchanged);
   - `zikaron/knowledge/scope.py` lines 6–7: *"the one case a person runs by hand is the foreground
     command a build result prints"* — the indexer's own module, which item 1 declares unchanged;
   - `zikaron/knowledge/indexer/main.py` line 67: *"detached it is spent on a refusal nobody will
     ever see"* — likewise the indexer;
   - the docstrings of tests of untouched modules: `tests/test_project_scope.py` line 92,
     `tests/test_knowledge_indexer.py` line 341, `tests/test_knowledge_build_log.py` line 215.

   A builder working item 4 as a list skips all six and meets them only at done-when 2 — if they read
   it by meaning rather than by `foreground_command`. Suggested change: replace the scope clause with
   *"wherever they stand — in the modules items 1–3 touch, and outside them at least in
   `core/knowledge/builds.py`'s module docstring, `core/knowledge/reporting.py`'s `LockReport`,
   `core/events.py`'s `KnowledgeBuildEvent`, `knowledge/scope.py`'s module docstring,
   `knowledge/indexer/main.py`'s `build`, and the docstrings of `tests/test_project_scope.py`,
   `tests/test_knowledge_indexer.py` and `tests/test_knowledge_build_log.py`"* — and one clause
   making explicit that *"the indexer is unchanged"* in item 1 is about its code, so a docstring edit
   in `knowledge/indexer/main.py` and `knowledge/scope.py` is not a fence violation.

3. **[IMPROVEMENT] The replacement integration test reads the log before the indexer has finished
   writing it.** `scan.run` releases the corpus lock in its `finally` (`core/knowledge/scan.py`
   lines 467–475), and `--wait` returns once the lock is gone and the mark has moved (§9: *"the
   indexer process may still be exiting"*). The indexer prints `built …`, `files …`, `state …` from
   `knowledge/indexer/main.py` lines 153–164 **after** `lifecycle.refresh` returns — that is, after
   the release; `scope.execute`'s `refused:`/`failed:` line and Python's own traceback land after
   `asyncio.run` unwinds, later still. So the last invariant's *"reads a real started build's report
   from the log `status` names"*, done straight after `refresh --wait` returns as the test it replaces
   does (`tests/test_knowledge_cli_integration.py` lines 265–275), will intermittently find a log
   missing its last lines — a flaky test specified by the brief.

   Suggested change, in that invariant: *"… reads a real started build's report from the log
   `status` names, polling the log for the `built` line to a deadline rather than reading it once,
   since the report is printed after the lock `--wait` watches is released."* And one clause in
   item 3's note or §9's rewrite — *"written moments after the wait returns"* — so a script that reads
   the log the instant a wait fails is not filed later as the log's defect.

4. **[NITPICK] The `foreground`-line invariant's CLI half has no mutation that reddens it.** *"Neither
   verb's result carries `foreground_command`, and the CLI prints no `foreground` line (the field
   restored to a started entry)"*: restoring the field reddens the wire assertion, but `_report_build`
   no longer reads the field after item 3, so the CLI assertion stays green under that mutation and
   can never be *seen red* as done-when 1 requires. Either name the CLI half's own mutation — *"(a
   `foreground` line printed for a `started` entry)"* — or drop that half, since the clause that
   follows already pins what the CLI prints after a started build.

5. **[NITPICK] The shipped `lock` paragraph now sits beside a paragraph that contradicts it.** §8.5's
   description, held verbatim by `tests/test_mcp_tool_descriptions.py`, says *"`live: false` means a
   build died and nothing else will say so"*; the new paragraph after it says `build_log` is where to
   read why. Suggested: *"… means a build died; `build_log` is where it said why"*, or *"and the corpus
   will not say so on its own"*. One sentence in §8.5 and `mcp/primary.py` line 213.

6. **[NITPICK] The field's name collides with the module that writes the `knowledge_build` event
   row.** `zikaron/knowledge/indexer/build_log.py` and `tests/test_knowledge_build_log.py` are about
   the event row, not a file; after this change every grep for the field hits them, and a reader of
   `status` beside `schema.md`'s event table can take `build_log` for the event log. If the name is
   to be different it is free now and a tool-surface change later; `output_log` or `build_output`
   would not collide. The operator's call — flagged, not pressed.

VERDICT: NEEDS_CHANGES

## Round 3 — 2026-10-20

Artifact at lines 6691–6851. Round-2 findings 1–5 are applied as described; 6 is declined with a reason
I accept. Re-verified against the tree rather than the brief's "verified myself" line: M40-1 was built
in `/home/nathan/Zikaron-m40-1` (`reviews/m40-1-job-dir-build-review.md` line 3), so *"as M40-1's
was"* is true; `_naming_the_store` turns an `OSError` from the log's open into `store_unavailable`
(`dispatch_knowledge.py` 636–637); `add` creates `knowledge/` at `0700` before anything spawns
(`database.py` 274–279), so the open never fails for want of the directory on the one path that
creates corpora; `_report_terminal_states` already names a corpus `status` no longer lists (`main.py`
552); `mcp/primary.py` passes `knowledge_status`'s result through; nothing under
`tests/fixtures/installed/`, `zikaron/install/` or `experiments/*.py` reads `foreground_command` or
the `foreground` line, so no snapshot moves. `detach.spawn` has one caller.

**Summary judgment.** Buildable as written, and the work list is now at least as wide as the done-when
that checks it. What remains is small and all of it cheap: one of the named mutations cannot redden a
test while the code the brief specifies stands, so done-when 1 is unmeetable for it as written; the
one-writer sentence that overturns the spec's rejection is false in a window a scripted
`refresh --wait; refresh` hits by construction, though `O_APPEND` already makes the consequence
benign; the agent-facing `lock` sentence overclaims for a by-hand build; and three enumerations of
log files and of `knowledge/`'s contents go incomplete in ways done-when 2 cannot see. No blocker.

### Findings

1. **[IMPROVEMENT] The `os.open` at `0o644` mutation reddens nothing while `fchmod` stands.** Item 1
   has the spawn *"set `0600` on the open file"* unconditionally, and the invariant names two
   mutations: *"(`os.open` at `0o644`; the `fchmod` dropped, with a leftover log at `0644`)"*. Under
   the first, the file is created `0644` and `fchmod` sets it `0600` before the child starts, so any
   test that reads the mode reads `0600` — green — and done-when 1's *"seen red against the mutation
   it names"* cannot be met for it. The `fchmod`-dropped mutation is the one that holds. No single
   mutation reddens the fresh-create path on its own, because a umask can only narrow what `os.open`
   asks for. Suggested: drop the first mutation, and say in item 1 that the mode `os.open` is given
   covers only the instant before `fchmod`, an empty file since `O_TRUNC` has already run.

2. **[IMPROVEMENT] "At most one live child per corpus" is false after the lock is released, and
   that is the sentence that overturns the spec's rejection.** The sequence in the tree: `scan.run`
   releases the lock in its `finally` (`core/knowledge/scan.py` 474–475); the child then prints its
   report (`knowledge/indexer/main.py` 130, 150–166) — or, on failure, writes its `knowledge_build`
   row first (`build`'s `except`, line 128, after the release, waiting the connection's write-lock
   budget: `build_log.py` 181–194) and then `scope.execute` prints `failed:`/`refused:`. In that
   window the lock is gone and the mark has moved, so `builds.plan` admits a `refresh`,
   `SpawnedBuilds.loading` drops the entry on the moved mark (`spawned_builds.py` 57–59), and the
   next spawn's `O_TRUNC` empties the log the previous child is still writing. This is not the
   restart's rarity: `refresh --wait` returns at exactly that moment (§9: *"the indexer process may
   still be exiting"*), and a script's next `refresh` is milliseconds behind it. Nothing is lost —
   `O_APPEND` lands the old child's last lines after the truncation — but a log can then open with
   the previous build's `built …` or `failed: …` before the new build's output, and on the failure
   path the one line the log exists for is the one that arrives late. The brief's design already
   absorbs this; only its claim does not. Suggested, in "What was found": *"a service spawns at most
   one live child per corpus until the lock is released — invariant 19's table until the child takes
   it, the lock after — and a child still printing its last lines after that may overlap the next
   spawn"*; and in item 1: *"appending is for the two cases of two writers — a service restarted in
   the second before the first one's child takes the lock, and the previous build's child still
   writing its last lines when the next spawn empties the log — whose lines then append rather than
   overwrite, so a log can open with the previous build's last lines."*

3. **[IMPROVEMENT] The `lock` sentence's rewrite overclaims for a build run by hand.** Item 2's
   *"`live: false` means a build died, and `build_log` says why"* is false for the one case the fence
   keeps — the indexer's own entry point, which `README.md` row 106 tells people about — whose output
   went to a terminal; its dead holder shows `live: false` beside a `build_log` that is the last
   *service-spawned* build's output, or null, and an agent reading the description takes a stale log
   for the cause. The new paragraph already has the right scope (*"the last build started by
   `zikaron_knowledge_add` or `zikaron_knowledge_refresh`"*). Suggested, in both copies (§8.5 and
   `mcp/primary.py` 213): *"`live: false` means a build died; when `zikaron_knowledge_add` or
   `zikaron_knowledge_refresh` started it, `build_log` says why"*.

4. **[IMPROVEMENT] Three enumerations go incomplete rather than false, so done-when 2 cannot see
   them, and item 4 does not name them.**
   - `design/architecture.md` §Paths, the *"Logs: one file per process"* bullet (line 403: *"Three
     distinct processes, three distinct files, by design"*) — the normative list of log files; and
     §"Degraded modes" line 1267, *"three independent processes, three files, so an operator checks
     all three"* — where an operator diagnosing a dead build is sent, and the fourth file is the one
     they now need.
   - `design/knowledge-index.md` §2's layout diagram (lines 56–63) shows `knowledge/` holding `.db`
     files alone, and line 67 says everything but the registry *"lives in one SQLite file"*; §9 line
     2877 lists what `remove` unlinks without the log, while §8.4's two `remove` passages are in
     item 4.

   CLAUDE.md's own rule is that an enumeration drifts across documents rather than within one.
   Suggested: add to item 4 — *"`design/architecture.md` §Paths' `Logs` bullet and §"Degraded modes"'
   three-logs sentence, each gaining the per-corpus build log; `design/knowledge-index.md` §2's
   layout diagram, gaining `7f3a9c21-….log ← the last spawned build's output (§8.4)`, and §9's
   `remove` sentence"*.

5. **[IMPROVEMENT] The README says nothing about where a failed build's output went.** Its `--wait`
   paragraph (`README.md` 660–665) is the README's whole guidance for a build in a script, and it
   ends at *"the indexer process itself may still be exiting"*; the troubleshooting table has no row
   for a build that died. Item 4 names only the components-table row. Suggested, added to item 4:
   *"and its `--wait` paragraph, which says that a build that left its corpus unusable is reported
   with its log's path — `build_log` in `status` — and that the log's last lines land moments after
   the wait returns"*, the README twin of the §9 clause item 3 adds.

6. **[IMPROVEMENT] The CLI's tolerance of a `status` entry without `build_log` is asserted and not
   pinned, and it is the one transition property the three projects will exercise.** "What landing
   in this tree does" says *"the command reads a `status` entry without `build_log` as one naming no
   log"*; no invariant names it, and a service in `~/Trading/LeibaTrader` started before the landing
   serves such entries until it restarts. The file's convention is `.get`, so the builder will
   probably comply; done-when 1 is about seen-red. Suggested, appended to the `status` invariant:
   *"and `zikaron knowledge status` and a `--wait`'s report read an entry without the key as naming
   no log (the CLI indexing `build_log` outright)"*.

7. **[NITPICK] Three more sites carry the premise and are not in item 4's "at least" list.**
   `zikaron/knowledge/indexer/build_log.py` `_report`, lines 203–208 (*"Detached, all three streams
   are `DEVNULL`, so this reaches a person only in the foreground"*) — in the indexer package the
   builder is told is unchanged, like the two already listed; `zikaron/project/resolve.py` line 93
   (*"the `foreground` command a build result prints"*); `tests/test_knowledge_cli.py` line 1683
   (the same). Done-when 2 catches all three by meaning; naming them costs nothing.

8. **[NITPICK] Under `--wait`, the never-appeared report has no path for a corpus `status` no longer
   lists.** A corpus removed mid-wait — one of §9's three never-appeared causes, and the accepted
   outliving-log case seen from the CLI — has no `status` entry, so the last poll carries no
   `build_log`; `_report_terminal_states` already names it `gone`. Item 3 promises the path
   unconditionally. One clause: *"…reported with its log's path when `status` still lists the
   corpus"*.

9. **[NITPICK] The `O_APPEND` invariant's test must open both descriptors before either writes.**
   Otherwise `O_TRUNC` alone empties the first's lines and the test is red under the shipped code
   too — red for the wrong reason. One clause in the invariant: *"(both opened, then each writes)"*.

VERDICT: NEEDS_CHANGES

## Round 4 — 2026-10-20

Artifact at lines 6691–6865. Every round-3 finding is applied as the brief says. Re-verified against
the tree rather than the "verified myself" line, and the things below are now settled and need no
re-checking by the builder: `knowledge/` is created only by `KnowledgeDatabase.create` (`database.py`
274–279, through `permissions.ensure_store_dir`), whose only caller is `lifecycle.add` (line 219), and
nothing under `core/knowledge/` calls `mkdir` — so the indexer never recreates the directory, a
`refresh` against an absent database is refused by §11's own row, and failing the spawn when the log
cannot be opened regresses no path the child could have recovered; item 1's choice stands. No drift
guard parses `architecture.md` §"Filesystem security"'s table or `schema.md` §"File permissions"
(`tests/test_design_*.py` name neither), so the log's new row is free in shape.
`_what_would_be_destroyed` carries `name`, `state`, `files_indexed` and `chunks` and no path, and the
`remove` tool description (§8.4 lines 2420–2434) enumerates no files, so neither owes the log a
mention. `encoder.load` hands fastembed `specific_model_path` for a pinned model, so a child spawned on
the cache the service's own start leaves warm downloads nothing, and no progress-bar bytes reach the
log on the ordinary path. The never-appeared branch of `_await_builds` (`main.py` 500–505) has the
current poll's `reports` in scope, so item 3's path comes from the last poll without a further call.
Line 1066 is inside §6.2 (1063–1148); §8.5 line 2717 and `mcp/primary.py` 213 carry the exact text item
2 quotes.

**Summary judgment.** Buildable as written and the mechanism's claims are now true of the tree,
including the two that changed this round — the one-writer sentence and the `fchmod` sentence. What is
left is one enumeration in the knowledge index's own normative degraded-modes table that done-when 2
cannot see, the twin of the `architecture.md` sentence the brief added last round; the rest is test
hygiene and naming. One one-clause improvement, three nitpicks; the next round should be short.

### Findings

1. **[IMPROVEMENT] `knowledge-index.md` §11's own degraded-modes row for a dead indexer says nothing
   about where its reason now is.** Line 3031, *"indexer died holding the lock | next scan reclaims
   after a liveness check on the pid … the exit is `refresh --force-unlock`"*, is the spec's
   operator-facing diagnosis row for exactly the condition the log exists for, and it is the knowledge
   index's twin of `architecture.md` §"Degraded modes"' sentence that item 4 already adds. It carries
   none of done-when 2's trigger words, so only item 4 can reach it. Suggested, appended to item 4:
   *"`design/knowledge-index.md` §11's row for an indexer that died holding the lock, gaining that
   when `add` or `refresh` started it, its output is in the log `status` names (§8.5)"*. Optional, and
   about the document rather than the accepted behaviour: §11's table lists `knowledge/*.db` with no
   registry row (line 3025) and nothing for the `knowledge/*.log` item 1 accepts outliving its corpus,
   which *"nothing reports or sweeps"* — one row saying so keeps §11 the complete table it is written
   as; decline if that reads as re-flagging item 1.

2. **[NITPICK] The `PYTHONUNBUFFERED` invariant's mutation is masked wherever the gate's environment
   already carries the variable.** `spawn` copies `os.environ`, so a shell that exports
   `PYTHONUNBUFFERED=1` hands it to the child whether or not the per-spawn copy sets it, and the test
   is then green under the shipped code and under the mutation alike — never a false failure, but
   done-when 1's *seen red* becomes a property of the shell the builder happened to use. Nothing in
   `check.sh`, `check-matrix.sh`, `check.yml`, `pyproject.toml` or `conftest.py` sets it, so this tree's
   gate is not masked today. One clause in the invariant: *"(`PYTHONUNBUFFERED` not set, with the test
   stripping it from the inherited environment first)"*.

3. **[NITPICK] One more enumeration of what `remove` unlinks goes incomplete, in §3.1.**
   `knowledge-index.md` lines 190–194: *"WAL means a live database is **three** files … Every
   operation that moves or removes a database must handle all three: `remove` unlinks all three"*.
   True of the database, and the paragraph's subject is the database; but it is the sentence a reader
   takes the corpus's on-disk footprint from, and §2's diagram and §9's sentence — both in item 4 —
   will now disagree with it. One clause: *"`remove` unlinks all three, and the corpus's build log
   (§8.4)"*. Same class as round 3's finding 4.

4. **[NITPICK] Three test sites that assert on `foreground_command` are outside item 4's at-least
   list.** `tests/test_service_spawned_builds.py` line 113 and
   `tests/test_service_knowledge_management.py` lines 1162 and 1191 index the field, and the
   docstring at 1179 reasons from it. They go red by `KeyError` the moment the field leaves the entry,
   so nothing can be missed — naming them only saves the builder reading a red gate to find them.

VERDICT: NEEDS_CHANGES

## Round 5 — 2026-10-20

Artifact at lines 6691–6873. All four round-4 findings are applied as the brief says: item 4 names §11's
dead-indexer row and a row for an orphan `.log` (6783–6786), the `PYTHONUNBUFFERED` test strips the
inherited variable (6829–6830), the *"One file" is true at rest* paragraph is in item 4 (6782–6783), and the
`foreground_command` assertions in the two service test files are named (6803–6805).

Re-verified against the tree rather than the "verified myself" line, and settled for the builder:
`tests/test_quoted_design_prose_is_verbatim.py` scans only `zikaron/` and `tests/` Python files
(`_searched_files`), so the brief's quotations of text the build will rewrite — the *"several concurrent
writers"* rejection, the old `lock` sentence — cannot redden the gate. `tests/test_event_kinds.py` reads the
nullability row through `parse_name_lists(table, "`kind`", NULLABLE_COLUMN)`, the field-names column, so
rewording the prose cell is free as item 4 says. No test parses §8.5's field table (`table_with_columns`
over `knowledge-index.md` reaches only §3.2 and the `state` table), so where `build_log` is documented is
unconstrained. `KnowledgeRemoveResult.as_json` serializes with `detailed=True` and `KnowledgeBuildResult.spawned`
feeds nothing but `_build_entry`'s `foreground_command`, so item 2's emit-by-`status`-alone and item 3's
removal of the argv plumbing are both exactly right. `zikaron doctor` audits nothing under `knowledge/`. A
whole-corpus grep for *foreground* and for the output-discarded phrasings maps every site onto the brief's
list, a landed brief, or a sentence that stays true (`schema.md` 705 and 1105, `overview.md` 119, the two
`refuses_in_the_foreground` test names). `architecture.md` §Paths' *Knowledge bases* bullet (373) and
`overview.md`'s §2 diagram (111–120) name the `.db` without claiming it is alone and show no log of any
kind, so neither owes the new file; the `Logs` bullet item 4 names is the right home. The permissions
rule the project does enforce — no symlink anywhere in the store directory's path, `permissions.py` 26–83 —
is applied to `knowledge/` at creation, so the log inherits the store's standing posture and needs no rule
of its own.

**Summary judgment.** Buildable as written and true of the tree: every mechanism claim checks out, every
named mutation reddens a test the shipped code passes, done-when 2 is meetable and at least as wide as the
work list for the classes it names, and the transition in the three projects is stated with the one
property that matters pinned. What remains is two one-clause precisions in prose the builder is told to
write, neither of which changes what ships.

### Findings

1. **[NITPICK] The orphan-`.log` row item 4 adds has a second cause, and the unlink order can remove it
   for free.** `lifecycle.remove` deletes the registry row, commits, and only then unlinks
   (`core/knowledge/lifecycle.py` 368, 411–418) — which is why §11's `.db` row (line 3025) calls an orphan
   *"the residue of an interrupted `remove`"*. After M40-2 the same interruption leaves the `.log` too, so
   the new row's *"item 1's accepted case"* names one of two causes. The order the log is unlinked in is
   free: unlinked **before** the three database files, an interrupted `remove` can never leave a `.log`
   without the orphan `.db` `status` reports beside it; unlinked after, a crash between the two leaves a
   lone log nothing reports. Suggested, item 1: *"`knowledge_remove` unlinks the log, then the database's
   three files"*; item 4's row: *"a row for a `knowledge/*.log` no registry row names — item 1's accepted
   case, and the residue of an interrupted `remove`, left beside the orphan `.db` the row above reports —
   which nothing reports or sweeps"*.

2. **[NITPICK] One more docstring in the "three files" class sits outside item 4's at-least list, and
   done-when 2 cannot see that class at all.** `tests/test_knowledge_lifecycle.py` lines 91–98: *"`files_unlinked`
   reports what was actually there, which is why it is normally one rather than three"* — false once a
   corpus a service spawned for is removed, in a test of an untouched core path with no spawn, so it stays
   green and is found only by reading. Item 4's predicate (*"or from the three files, wherever they stand"*)
   reaches it; the list does not. The spec's own copy, §8.4 line 2326 *"Normally it is one"*, is inside the
   paragraph item 4 names, so the builder reaches it by pointer — but done-when 2's predicate names only the
   printed command and the discarded output, so a surviving *"normally one path"* passes it. Suggested: add
   `tests/test_knowledge_lifecycle.py` to the at-least list, and optionally a third clause to done-when 2 —
   *"or that `remove`'s `files_unlinked` is normally one path"* — so the acceptance criterion sees what the
   work list already asks for.

VERDICT: APPROVED
