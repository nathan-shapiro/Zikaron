# M40-2 — build review

Artifact: the uncommitted tree in the worktree `/home/nathan/Zikaron-m40-2` (branch `m40-2-indexer-log`,
over `bed5430`), judged against `design/build-plan.md` §"M40-2 — A command no one should paste, and a log
that keeps why a build died" (main tree, lines 6691–6880), the normative sections it cites, and
`design/coding-standards.md`. The brief's own review is `reviews/m40-2-indexer-log-review.md`.

## Round 1 — 2026-10-20

Read rather than taken from the brief's "verified myself" line: `detach.open_log` opens
`O_WRONLY | O_CREAT | O_TRUNC | O_APPEND` at `0600` and `fchmod`s the open descriptor; `spawn` opens the
log after the environment copy and before `Popen`, closes its copy in a `finally`, and sets
`PYTHONUNBUFFERED=1` per spawn; `_naming_the_store` turns the open's `OSError` into `store_unavailable`
(`dispatch_knowledge.py` 635–636); `reporting.observe` stats the log before the database is opened and
hands it to both constructors, so `state: error` carries it; `_status_entry` is the only emitter and
`KnowledgeRemoveResult.as_json` goes through `KnowledgeBaseJson` alone; `lifecycle.remove` unlinks
`(log_path, *database_files(db_path))` in that order and reports only what was there;
`orphan_candidates` still filters on `.db`; every CLI read of the field is `.get`; the integration test
polls the log for the `built` line to a 30 s deadline; the ordering test strips `PYTHONUNBUFFERED` from
the inherited environment first; the two-writers test opens both descriptors before either writes. Each
invariant in the brief maps to a test I read, and each named mutation would redden it as the brief says.
The comments added explain reasons (why `fchmod` after `O_TRUNC`, why unbuffered, why the log line sits
outside the diagnostic guard) and narrate no repair.

**Summary judgment.** The mechanism is built as specified and the tests pin it; code and comments meet
the standards. What stops it shipping is one normative passage in a section the brief's own list names:
`schema.md`'s `spawned_by_op_id` paragraph still reasons from `detach.spawn` returning the argv and
§8.4 printing it as the command to reproduce a build, which is now false twice over and is exactly what
done-when 2 forbids. Besides that, the one security-bearing property the brief states for the new path
builder has no test, and two enumerations in the README go incomplete the same way the brief review
found in the design corpus. One blocker with a one-sentence fix, two improvements, two nitpicks.

### Findings

1. **[BLOCKER] `design/schema.md` §"What is instrumented, what is not, and why" still says a build
   result prints the argv, in the paragraph the brief review named.** Worktree lines 1197–1201:
   *"It is **not** on the argv because `detach.spawn` returns the argv the child actually ran and
   `knowledge-index.md` §8.4 prints that as the command to reproduce a build — a flag the printed form
   stripped would break that identity."* After item 3 `spawn` returns the child's handle alone and
   §8.4 says *"Neither verb's result names a command to run"* (knowledge-index.md 1979–1980). The
   brief's normative list names this section *because* it cites the printed command, and
   `reviews/m40-2-indexer-log-review.md` round 1 finding 10 points at this paragraph by name; the
   neighbouring paragraph (1166–1175) was updated and this one was not — it carries none of
   done-when 2's grep words, which is how it survived. Suggested replacement for the sentence at
   1199–1201, keeping the rest of the paragraph: *"It is **not** on the argv because an attribution
   token is not an input that changes what a build does — a person running the indexer by hand sets
   none and gets the same build — so the command line is the wrong place for it
   (`knowledge-index.md` §8.4)."* The paragraph's closing clause, *"declared once in `detach.py`, which
   already owns the argv"*, stays true. (The two other hits for this phrasing, `build-plan.md` 3474 and
   3982, are in landed briefs and exempt.)

2. **[IMPROVEMENT] `knowledge_log_path`'s re-parse of the id is stated by the brief and pinned by no
   test.** `tests/test_knowledge_invariants.py::test_the_path_builder_will_not_accept_a_string_at_all`
   (lines 89–95) calls `paths.knowledge_db_path(tmp_path, "../memory")` only; nothing calls
   `knowledge_log_path` with a string, so the mutation `f"{kb_id}{_LOG_SUFFIX}"` in
   `core/knowledge/paths.py` line 52 reddens nothing while producing `knowledge/../memory.log`. The
   brief's item 1 says the log's path is built *"re-parsing the id as that function does"*, which is the
   module's one security property, and this is the second path under `.zikaron/` derived from the id.
   Suggested: parametrize that test over both builders —
   `@pytest.mark.parametrize("build", [paths.knowledge_db_path, paths.knowledge_log_path])` — and in
   `design/knowledge-index.md` invariant 11 (line 3162–3163) widen the enumeration from *"Every knowledge
   database path is `knowledge/<id>.db`"* to *"Every knowledge database path is `knowledge/<id>.db`, and
   its build log `knowledge/<id>.log`,"* so the invariant names both paths it now holds over.

3. **[IMPROVEMENT] The README's `.zikaron/` layout lists `knowledge/` as databases alone and names three
   logs.** `README.md` lines 883–884: *"`knowledge/` one database per knowledge base, named by a
   generated id. Absent until you create one"*, followed by `service.log`, `hook.log` and `warmup.log`
   with nothing for the per-corpus log. This is the README twin of `knowledge-index.md` §2's diagram and
   `architecture.md`'s `Logs` bullet, both of which item 4 added, and it is the listing an operator reads
   to learn what is in the directory; done-when 2 cannot see it. Suggested: *"`knowledge/` one database
   per knowledge base, named by a generated id, and beside each the log of the last build the service
   spawned for it. Absent until you create one"*.

4. **[NITPICK] The status description says `build_log` "is the output" where the value is a path.**
   `knowledge-index.md` 2745–2746 and `mcp/primary.py` 217–218: *"`build_log` is the output of the last
   build `zikaron_knowledge_add` or `zikaron_knowledge_refresh` started, or null."* The field is the
   file's path as a string. *"`build_log` is the file the last build `zikaron_knowledge_add` or
   `zikaron_knowledge_refresh` started wrote to, or null."* says so at +5 code points against the 8 the
   1,900 budget has left; both copies move together, since `tests/test_mcp_tool_descriptions.py` holds
   them equal, and the brief's item 2 quotation would then be updated in the main tree as it was for the
   `lock` sentence.

5. **[NITPICK] The README's troubleshooting table has no route from a build that keeps dying to the
   log.** Row 976 (*"a knowledge search returns nothing, or too little"*) explains `reindex_required` and
   ends at *"`refresh` rebuilds it"*; a reader whose `refresh` leaves it `reindex_required` again is sent
   nowhere. One clause at the row's end: *"— and if it does not, `zikaron knowledge status <name>`'s
   `log` line names where that build wrote why"*. Optional; the `--wait` paragraph the brief added covers
   the scripted case and this is the interactive one.

VERDICT: NEEDS_CHANGES

## Round 2 — 2026-10-20

Read again rather than taken from the brief: round 1's five findings are applied as described — `schema.md`
1197–1202 now reasons from the attribution token and cites §8.4, and no sentence in `design/` outside
`build-plan.md`, `README.md`, `zikaron/` or `tests/` says a build result prints a command or that a
detached build's output is discarded; `tests/test_knowledge_invariants.py` 91–100 parametrizes the
string-rejection test over both builders and invariant 11 (3162–3164) names both paths; `README.md`
883–885 names the log beside each database; both copies of the status description read *"the file the
last build … started wrote to"* and the brief's quotation matches; row 977 ends at the `log` line. The
invariant-to-test map holds for every bullet in the brief, including the two I checked hardest:
*an entry without the key* is driven through both `_print_listing` and `_report_terminal_states` by one
test (`test_knowledge_cli.py` 1048–1060), so the `--wait` half reddens on `entry["build_log"]` too; and
`test_a_log_is_never_an_orphan` (`test_service_knowledge_management.py` 1264–1274) has a `.log` on disk
when the scan runs, so widening the scan reddens it. `core/events.py` 928–931, `builds.py`'s module
docstring, `LockReport`, `scope.py`, `build_log._report`, `indexer/main.py` and the test docstrings the
brief names all state the log rather than the terminal or the discarded output. Nothing shipped —
installer text, snapshots, skills — names `foreground_command`; the only remaining mention outside
landed briefs is a test name in `research/build-transaction-upgrade-race.md`, which is a record and out
of scope. `knowledge/` exists before every spawn, since `add` creates the database first and
`no_database` never starts one, so `open_log` cannot meet a missing directory on the paths that reach
it. `/dev/fd` is where both supported platforms list descriptors, so the leak test is honest on macOS.

**Summary judgment.** The build is complete against the brief and its normative sections, every stated
invariant is pinned by a test its mutation reddens, the comments explain reasons and narrate no repair,
and the risk to the three projects on this tree is the transient the brief already names — an old
service answers without `build_log` and the new command reads that as no log. Two trivial items remain,
one of which is the class done-when 2 names in words its grep cannot see; both are one-clause edits.
Ship once they are in.

### Findings

1. **[NITPICK] One clause in §8.4's rebuild rules still says a spawned build's output goes unread.**
   `design/knowledge-index.md` 2269–2271: *"every later build would die inserting a vector of the
   recorded width into a table declared for another, one rejected insert per file in a process whose
   output nobody reads."* The argument — `state` must report the condition because nobody is watching
   the failing build — still holds; the clause as worded asserts the proposition this milestone retires,
   and it carries none of done-when 2's words, which is how it survived the sweep. Suggested: *"… one
   rejected insert per file in a process nobody is watching."* Apply before the commit; it is the
   round-1 schema.md class at nitpick size.

2. **[NITPICK] The README's `--wait` paragraph names the log for one of the two failures the command
   names it for.** `README.md` 662–663: *"exiting non-zero if any build left its corpus unusable, and
   naming the build log of each one that did"*. `_await_builds` also names it for a build that never
   appeared (`main.py` 494–499), which is the refusal case the log most often holds. Suggested:
   *"… and naming the build log of each one that did, or that never started"*. Optional.

VERDICT: APPROVED
