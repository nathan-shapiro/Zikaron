# M24 — the MCP management surface: review

Artifact under review: the M24 milestone as described in `design/build-plan.md` §M24 — the six
knowledge-base management tools over six `knowledge_*` RPC methods, the `memory_` prefix on every
memory tool and method, the §12 counters, and the design deltas that go with them.

## Round 1 — 2026-09-16

### Summary judgment

The engineering is sound and the done-when clauses each have a real test behind them: the build
classifier's precedence matches `state.PRECEDENCE`, the "five classes" claim in `_translated` holds
against every raise site, the rename left no bare tool or method name anywhere in shipped prose or
the design, the consolidator server is asserted disjoint from all twelve, the description-parity
guard is mechanical, and §12's counter policy is exactly what `record_search` and `_serve` do. Both
research notes are honest about their conditions ("not idle"; "run after rather than before"). No
M24 code carries circumstantial provenance. What stops approval is one safety defect in the
destruction preview — the only preview an irreversible unlink has reports a fabricated `0` for
precisely the corpus state the design routes agents to `remove` for — plus a cluster of
prose-contradicts-adjacent-code items of the kind this repository names as its dominant class,
three of them on the wire contract itself.

### Findings

1. **[BLOCKER] The destruction preview reports `chunks: 0` (and the CLI prints "0 chunks") for a
   corpus whose database is present and cannot be opened.**
   `zikaron/service/dispatch_knowledge.py:339` — `chunks=0 if found.details is None else
   found.details.chunks`; `zikaron/knowledge/main.py:298` does the same. For an *absent* database
   `0` is true. For `state: "error"` — the file exists and `KnowledgeDatabase.open` raised, which
   includes a `meta` validation failure such as a schema version newer than this build, or a
   permissions problem over an intact, fully built corpus — `0` is a number no stored value backs.
   Two docstrings written in this same milestone say exactly why that is wrong:
   `reporting.without_details` ("Everything else the database would have supplied is absent rather
   than zeroed, so a caller is never handed a confident value that no stored one backs") and
   `serialize_knowledge.KnowledgeBaseJson` ("a zero no stored value backs is a confident answer to a
   question nothing could answer"). The preview contradicts both, on the one irreversible verb, and
   `lifecycle.remove` *proceeds* on an `error` corpus because no lock can be read from it — so an
   agent reading `files_indexed: 0, chunks: 0` will confirm, and §8.4 itself names `remove` as the
   remedy for one `error` cause ("repaired by deleting the file"). The perturbation table walked
   `unreadable × remove` for the *refusal*; the mutation that closed the constant-`0` survivor used
   a built, readable corpus, so this cell is the same "fixture cannot produce the condition" class
   with one more dimension.
   **Fix.** In `_what_would_be_destroyed` and `main._remove`, distinguish the two `details is None`
   cases by state: `REINDEX_REQUIRED` (absent file) keeps `0`; `ERROR` reports `chunks=None`
   (`PayloadField("chunks")` is open-valued, so `None` passes `ZikaronError` construction) and the
   CLI prints `chunks unknown — its database cannot be read`. Then say so in both statements of the
   contract: `knowledge-index.md` §8.4 table row for `knowledge_confirm_required` and
   `architecture.md` −32043 — "`chunks` is `null` when the database cannot be read; `files_indexed`
   is then `0` by §8.5's availability reading and says nothing about what the file holds". Add a
   test that corrupts the file, calls `knowledge_remove` without `confirm`, and asserts
   `data["chunks"] is None`. (Carrying `state` in the payload would be the more complete answer,
   since `files_indexed: 0` in that cell is equally misleading; it changes `ERROR_SPECS`, the §8.4
   table and the architecture row — three sites — and is your call. `chunks: null` is the minimum.)

2. **[IMPROVEMENT] An out-of-range `max_file_bytes` from the tool arrives as `bad_config`, i.e.
   "a configuration value is missing, unparseable or out of range", sourced to the store's `meta`.**
   `zikaron/core/knowledge/lifecycle.py:187–188` calls `meta.check_bounded`, which raises
   `ZikaronError(BAD_CONFIG, …)`; not being a `KnowledgeError`, it passes through
   `_refusals_as_wire_errors` untranslated. That contradicts three things beside it:
   `_translated`'s own rule (a parameter-value rejection reuses `bounds` — and `git_mode`, the
   sibling parameter at `dispatch_knowledge.py:200–213`, does); `core/knowledge/errors.py`'s
   module docstring (knowledge refusals are deliberately *not* `ZikaronError`, because those codes
   "describe something a client asked the memory service to do" — `lifecycle.add` raises one
   anyway); and both statements of the `bounds` row (`knowledge-index.md:1895`,
   `architecture.md:1819`), which enumerate name and `path` and omit this parameter. An agent is
   told the store's configuration is bad when it typed `0`. The tell is in the test:
   `test_a_value_it_cannot_accept_is_a_bounds_rejection` parametrizes `name`, `path`, `git_mode`
   and not `max_file_bytes`.
   **Fix.** Add `InvalidSettingError(KnowledgeError)` carrying `key`, `value`, `expected`; have
   `lifecycle.add` raise it (either by having `check_bounded` return the `IntBounds` and letting
   `add` raise, or by catching at that one site); map it in `_translated` to
   `ZikaronError(BOUNDS, field="max_file_bytes", limit=<the range>, actual=<the value>)`. The CLI's
   generic refusal printing already handles a `KnowledgeError`
   (`test_knowledge_cli.py:258` asserts only "refused", so it should keep passing). Add the
   parameter to both `bounds` rows and to the parametrized test; update `lifecycle.add`'s Raises.

3. **[IMPROVEMENT] Two error payload fields carry a whole refusal sentence where the contract
   wants a value.**
   `dispatch_knowledge.py:130` — `holder=str(error)`. `architecture.md:1834` says "`holder`
   describes the recorded lock holder"; what ships is "a build is running against 'docs' (pid 123
   on host, since …); retry once it has finished". `_translated`'s docstring argues the mapping is
   on the type "so that a message may be reworded without silently changing which code a caller
   sees" — the code is stable, but the payload's `holder` *is* the message, so a rewording changes
   what a client parses. The test at `test_service_knowledge_management.py:517` asserts
   `"docs" in str(holder)` — asserting the *corpus name* appears in the *holder* field is the tell.
   Same shape at `:122`: `InvalidRootError` → `bounds.actual = str(error)`, a message rather than
   the supplied value.
   **Fix.** Give `IndexerBusyError` a required `holder: LockHolder` keyword at its four raise sites
   (`lifecycle.remove:357`, `builds._stopped_by:124`, `lock.acquire:210`, `lock.force_release:270`)
   and translate with `holder=error.holder.describe()`; give `InvalidRootError` a `path: Path` and
   translate with `actual=str(error.path)`. Re-aim the test: `holder` names the pid and host and
   does not contain "retry".

4. **[IMPROVEMENT] `KnowledgeBuildResult` says its entries are "the same shape `status` reports";
   `_build_entry` builds the `list` projection.**
   `zikaron/service/serialize_knowledge.py:169–170` versus `:158` (`detailed=False`). The
   docstring's second paragraph then reasons from "the per-corpus `git_mode_effective`", a field
   the entry it is describing does not carry. `knowledge-index.md:1868` ("the same status shape as
   §8.5") is ambiguous between §8.5's two shapes, and `FINDINGS.md`'s bullet ("two names, at two
   levels") reads as though both levels are in one response. The test that checks the per-corpus
   field (`test_the_per_corpus_effective_mode_is_the_last_build_s_and_is_not_the_probe`) reads it
   from `knowledge_status`, not from the `add` result — consistent with the code, not the prose.
   **Fix.** Keep `detailed=False` (§8.5 spends a paragraph on why twenty diagnostic fields per
   corpus is the wrong default, and `add`'s description already says "Poll `zikaron_knowledge_status`")
   and reword the three sites: the entries are §8.5's `list` projection; `add`'s probe is named
   `requested_git_mode`/`effective_git_mode` rather than `git_mode_effective` because that name is
   `status`'s field for what the last completed build used, and one name for two subjects across
   the two calls is the seam being refused. If you prefer `detailed=True`, state the cost on
   `refresh(None)`.

5. **[IMPROVEMENT] A relative `path` in `zikaron_knowledge_add` resolves against the service
   process's inherited working directory, which nothing states and the agent cannot know.**
   `roots.validate_root:37` does `path.expanduser().resolve()`; the service is spawned at
   `service/lifecycle.py:271` and `hook/connect.py:250` with no `cwd=`, so it inherits whichever
   client's directory started it — possibly days earlier, from a different session. The tool
   description says only "`path` must exist and be a directory" (§8.4:1918, `primary.py:230`);
   §8.6 says nothing about relative paths. An agent under Claude Code will routinely pass `docs`.
   The stored `root_path` is absolute, so the mistake is silent: a corpus over `<inherited cwd>/docs`
   reports `ok`. The CLI has the same ambiguity but the shell convention (relative to the shell's
   cwd) is at least what a person expects.
   **Fix.** In `knowledge_add`, before building `AddRequest`: `root = Path(path)`; if not absolute,
   `root = paths.scope_of(ctx.store_directory) / root` — the one directory the harness and the
   store agree on. Description and §8.4: "`path` is absolute, or relative to the project root." §8.6:
   one sentence. Test: a relative `path`, asserting `status`'s `root_path` is under the project.
   Decide the CLI's rule explicitly in `--path`'s help (shell cwd is fine there; say it).

6. **[IMPROVEMENT] §8.4 says `remove` "refuses with `already_indexing`"; the same section's error
   table, `architecture.md` and the code say `knowledge_base_busy`.**
   `design/knowledge-index.md:1650` versus `:1893` and `architecture.md:1834`. `already_indexing`
   is a `refresh` *outcome* value, not an error code, and a client implementer reading line 1650
   would look for it in a `remove` error. Two names for one refusal inside one section is the
   enumeration-drift class. **Fix:** line 1650 → "refuses with `knowledge_base_busy`".

7. **[IMPROVEMENT] `remove`'s wire shape carries `files_unlinked`; the design's statement of the
   shape does not.**
   `serialize_knowledge.KnowledgeRemoveResult` and `knowledge_remove`'s docstring give
   `{removed, knowledge_bases, files_unlinked}`; `knowledge-index.md:1873` says "a final snapshot
   of what was destroyed plus `removed: true`", and `files_unlinked` appears nowhere under
   `design/`. **Fix:** add it at line 1873 with the one-sentence reason `lifecycle.remove`'s
   docstring already gives — what was actually on disk rather than what was attempted, normally
   one path because SQLite reclaims `-wal`/`-shm` on the last close.

8. **[NITPICK] `builds._stopped_by:110` invents a `RuntimeError` for a case the type it reads
   forbids.** `Observed.unreadable_because`'s docstring says it is `None` "whenever the state is
   anything but `error`", and `observe:323` always supplies it on `error`; the `or RuntimeError(…)`
   is unreachable through `observe` and untested (a short-circuit `or` is not a branch to the
   coverage tool, which is how this line reads 100%). Either make the pairing structural — an
   `Observed.__post_init__` asserting `(state is ERROR) == (unreadable_because is not None)` — and
   drop the fallback, or construct the case in a test.

9. **[NITPICK] `_build_entry`'s docstring overstates a sweep's atomicity.** "there is no state in
   which a corpus was clear to build and then was not built" — on `refresh(None)`, `detach.spawn`
   raising `OSError` for the second corpus leaves the first spawned, the third unspawned, and the
   call an internal error. What is true and sufficient: nothing reaches this function after a
   failed spawn, so no entry can report `started` for a corpus whose spawn failed. Reword to that.

10. **[NITPICK] An abandoned counter write leaves no trace anywhere, and the `False` it returns is
    read only by tests.** `groups._serve:331` discards `record_search`'s result. §12 licenses
    losing the count; nothing licenses making the loss *rate* unobservable, and M25 will read
    `searches` as "is this used at all" — a corpus searched mostly while it is being built
    under-counts by an amount nothing records. A `logger.debug` line in `_serve` when `False` comes
    back costs nothing on the latency path (the service already owns `service.log`); failing that,
    §12 should say the loss rate is deliberately unmeasured.

11. **[NITPICK] A tautological assertion.** `tests/test_service_knowledge_management.py:454` —
    `assert len(await _call(ctx, "knowledge_list", {})) == 1` is `len(dict) == 1`, true of every
    list response since the dict has one key. The next line carries the test; delete this one or
    assert `len(payload["knowledge_bases"]) == 1`.

### Checked and found sound (so the next round need not re-derive them)

- `_stopped_by`'s ordering claim ("unreadable before missing root, missing root before running
  build") is the consequence of `state.PRECEDENCE` (`ERROR > ROOT_MISSING > … > INDEXING`) and
  `inputs_for_open` never yielding `ERROR`; the two ordering tests assert it as orderings.
- `_translated`'s "five classes" claim: the service-reachable raise sites are exactly
  `InvalidName`, `InvalidRoot`, `Duplicate`, `Unknown`, and `IndexerBusy` from `lifecycle.remove`;
  `Dangling`, `CorpusRootMissing` and `RegistryUnavailable` are CLI- or indexer-only.
- The rename: no `zikaron_{search,fetch,…,discard}` or bare method name survives in `zikaron/`,
  `design/`, `README.md`, `.claude/` or `.kiro/`; the hook sends `memory_surface`; the installer's
  consolidator prompt names `zikaron_memory_*`; `design/write-policy.md` names no tool.
- Done-when: each clause has a named test, including the omitted-`confirm` default, the foreign
  lock for both verbs, and `TestTheWholeLifecycleThroughTheTools`; consolidator disjointness is
  asserted against the real servers; `test_no_description_names_a_tool_its_own_server_does_not_have`
  runs over both modes.
- §12 against code: timeout dropped to `0` and restored in `finally`; only `is_contention` is
  swallowed; a non-contention failure reaches `_open_group`'s `except` and becomes that corpus's
  `error` group; only `_SERVING` states raise counters; increments are in SQL. The elapsed-time
  assertion closes the "waited five seconds" vacuity.
- The two measurement notes state their conditions rather than a template's, and the tool-list
  note is explicit that it establishes size, not delivery.
- No circumstantial provenance in `builds.py`, `dispatch_knowledge.py`, `serialize_knowledge.py`,
  `counters.py`, `primary.py`, `tool_names.py`, `knowledge/main.py`, `service/paths.py`,
  `service/params.py` or `core/errors.py`.

VERDICT: NEEDS_CHANGES

## Round 2 — 2026-09-16

### Summary judgment

All eleven round-1 findings are fixed as described, and the fixes hold: the preview reports `null`
and carries `state` in both surfaces, the size cap is a `bounds` rejection sharing the stored-value
path's range phrasing, `holder` and `path` are values read off the exception, the `Observed`
pairing is a constructor check tested in both directions, and the relative-path resolution has a
decoy that makes the wrong answer succeed. No behaviour defect was found in the six verbs or the
counters. What remains is the cascade this project predicts of itself: three places where a round-1
fix left a neighbour asserting the pre-fix world — one normative paragraph in §8.5 quoting a phrase
§8.4 no longer contains and drawing a now-false consequence from it; the `bounds` translation
naming the wrong field and carrying the accepted value when the blank name is `new_name` or
`knowledge_base`, which is finding 3's class one caller over; and the CLI's `status` printer telling
a reader that an unreadable database means "nothing has been built here yet", which is the blocker's
claim in the sibling printer of the one that was fixed. The rest is vocabulary and pointer hygiene,
each with a one-line fix.

### Findings

1. **[IMPROVEMENT] §8.5 still argues from "the same status shape", a phrase round-1 finding 4
   removed from §8.4, and the consequence it draws is now false.**
   `design/knowledge-index.md:2203–2205`: *"The coupling is not decorative — §8.4 defines `add` and
   `refresh` as returning "the same status shape", so a field missing here is a field missing from
   the return that §5.2 requires to report degradation."* §8.4:1870–1892 now says `add` and
   `refresh` answer in the **`list` projection** and that §5.2's degradation travels as
   `requested_git_mode`/`effective_git_mode` *beside* the entries. So the quoted phrase exists
   nowhere else in the corpus (grep: this is the sole surviving site), and the inference is wrong
   in both halves — a field missing from `status`'s diagnostic half was never in `add`'s return,
   and the degradation report does not ride on any §8.5 field. This is the neighbour-contradiction
   class, produced by round 1's own fix.
   **Fix.** Replace the second sentence with what is still true: *"The coupling is not decorative —
   `status` is the only surface that reads §5.2's persisted degradation back
   (`git_mode_effective`), so a field missing here is a field §5.2 promised and nothing reports."*
   Or delete it; the first sentence carries the rule.

2. **[IMPROVEMENT] A blank `new_name` on `rename` is reported as `field: "name"` carrying the
   *old, accepted* name as `actual`; a blank `knowledge_base` on `status` is reported as
   `field: "name"`.**
   `zikaron/service/dispatch_knowledge.py:108–111` — `_as_bounds` answers every
   `InvalidNameError` with `field="name", actual=name`. `registry.rename:169–170` validates `name`
   first and then `normalize_name(new_name)`, so `knowledge_rename(name="docs", new_name="   ")`
   arrives as `bounds {field: "name", actual: "docs"}`: the field that was fine, carrying the value
   that was accepted, and a client that resubmits with a different `name` gets the identical
   refusal. `knowledge_status:222` passes `name=name or ""` for a parameter called
   `knowledge_base`, so a blank one is `field: "name"` for a field the caller never sent. Round-1
   finding 3 established that these payload fields are values a client reads; this is the same
   contract, one caller over, where the value is a value but the wrong one. `errors.py:15` says
   three refusals carry the value they are about — `InvalidNameError` is the one raised with two
   candidates in hand and carries none. No test exercises either case:
   `test_a_value_it_cannot_accept_is_a_bounds_rejection` parametrizes `add` only, and `TestRename`
   has no blank-name case.
   **Fix.** Give `InvalidNameError` a required `value: str` at `registry.normalize_name:101`
   (making `errors.py:15`'s count four). Have `_refusals_as_wire_errors` take the supplied names by
   parameter — `fields={"name": name}` for `add`/`remove`/`refresh`,
   `{"name": name, "new_name": new_name}` for `rename`, `{"knowledge_base": name}` for `status` —
   and let `_as_bounds` report the first key whose value equals `error.value`, with
   `actual=error.value`. Tests in `TestRename` and `TestStatus`: blank `new_name` → `field ==
   "new_name"` and `actual == "   "`; blank `knowledge_base` → `field == "knowledge_base"`.
   Mutation to run: revert `_as_bounds` to `field="name"` and watch both fail.

3. **[IMPROVEMENT] The CLI's `status` tells a reader an unreadable database means "nothing has
   been built here yet".**
   `zikaron/knowledge/main.py:363–366` — `_print_details(None)` prints
   `(no database to read — nothing has been built here yet)` for both `details is None` states.
   For `state error` — the file is present and `KnowledgeDatabase.open` refused it for a
   permission or `schema_version` reason — that parenthetical is exactly the confident claim
   round 1's blocker named, and `_what_goes:296–307` was rewritten to avoid: the file may hold a
   fully built corpus. Same condition, sibling printer, not swept — the "audit the other callers of
   a shared condition" rule from `CLAUDE.md`. The state line above it does say `error`, which is
   why this is not a blocker; the sentence beneath it is still false.
   `test_a_knowledge_base_with_no_database_prints_that_rather_than_zeroes:444` covers only the
   absent case.
   **Fix.** `_print_details(report: reporting.Status)`; when `report.details is None`, branch on
   `report.summary.state`: `ERROR` → `(its database is present and cannot be read — what it holds
   is unknown)`, otherwise the current line. Add the sibling test using `_corrupt_database` and
   `status docs`, asserting "cannot be read" is printed and "nothing has been built" is not; verify
   by reverting the branch.

4. **[NITPICK] `knowledge_refresh` parses `full` after it has consulted the store.**
   `zikaron/service/dispatch_knowledge.py:322–327` — `require_bool(params, "full", …)` is
   evaluated as an argument to `_spawn`, after `builds.plan` has run. `{"name": "absent", "full":
   "yes"}` therefore answers `knowledge_base_unknown`, and only a corrected name reveals the
   `bounds` on `full`; `{"full": "yes"}` over a large store observes every corpus before rejecting
   the parameter. §8.4:1908 defines `bounds` as "decided before any store state is consulted", and
   every other parameter in this module is parsed before the store is touched (`_git_mode`,
   `optional_int`, `require_bool("confirm")`). No side effect — the spawn is never reached — so
   this is ordering only. **Fix:** `full = require_bool(params, "full", default=False)` above the
   `with` block; a test with `{"name": "docs", "full": "yes"}` asserting `bounds` and `spawns == []`.

5. **[NITPICK] `~`-prefixed paths are handled and nowhere stated; and the "value the caller
   supplied" test docstring contradicts `errors.py`'s "as resolved".**
   `dispatch_knowledge.py:263` returns a `~…` path unjoined so `roots.validate_root:37` can expand
   it — correct, and necessary, since `<project>/~/notes` would never expand. But the docstring
   (`:249–260`), the shipped description (`primary.py:230–232`), §8.4's quote (`:1945–1946`) and
   §8.6 (`:2269–2278`) all state a two-way rule — absolute as given, relative from the project
   root — under which `~/notes` is a relative path. Prose narrower than the code. Separately,
   `test_an_absent_root_carries_the_path_rather_than_a_sentence:224` says `actual` is "the value
   the caller supplied" while `errors.py:63–65` says it is the path **as resolved**; the fixture
   (absolute, no symlinks) cannot tell the two apart. **Fix:** one clause — "`~` expands to the
   home directory" — at the four sites (the parity test forces the description and §8.4 to move
   together); reword the test docstring to "as resolved"; add a case with `path="nope"` asserting
   `actual == str(project / "nope")`, which also pins `_corpus_root` on the refusal path, and one
   with `~/…` under a monkeypatched `HOME`.

6. **[NITPICK] §9 says an unreadable database is "reported as a failure rather than a refusal";
   the CLI prints it as `refused`.**
   `design/knowledge-index.md:2358–2360` and `builds._stopped_by:114–115` ("it stays a failure
   rather than becoming a refusal") both draw the line; `main._report_obstacle:258` routes every
   non-`already_indexing` obstacle through `_refuse`, which prints `refused   docs: file is not a
   database` — the prefix `scope.execute:122–130` reserves for a `KnowledgeError`, where `failed:`
   is the driver-error prefix. No CLI test refreshes a corrupt corpus (`_corrupt_database` is used
   only by the `remove` preview). **Fix:** in `_report_obstacle`, `if entry.obstacle is
   BuildObstacle.UNREADABLE: print(f"failed    {name}: {entry.refusal}", file=sys.stderr); return
   True`; a test with `_corrupt_database` + `refresh docs` asserting exit 1, `started == []`, and
   "failed" in stderr.

7. **[NITPICK] §8.4 calls `already_indexing` one of "the four refusals".**
   `design/knowledge-index.md:1683` versus the table two lines above ("the idempotent case, not a
   failure"), `main._report_obstacle:250` ("the one that is not a refusal at all") and
   `BuildObstacle`'s own name. **Fix:** "The four non-`started` outcomes are a closed set of their
   own…".

8. **[NITPICK] `FINDINGS.md:1522` still counts "two refusals that deliberately get none".**
   After round-1 finding 2 it is three — `architecture.md:1819` and §8.4:1905 both now list the
   size cap. The always-loaded file asserting the pre-fix count is the two-sites pattern this
   project names. **Fix:** "three refusals … a blank name, a bad `path` and an out-of-range
   `max_file_bytes` reuse `bounds`".

9. **[NITPICK] `primary.py:20–21` — "`memory_surface` is the one method no tool carries at all".**
   `architecture.md:1859–1861` names `memory_plan_groups` as a second (and `health` is a third).
   The sentence was edited this milestone for the renamed spelling without its universal being
   re-read. **Fix:** "`memory_surface` and `memory_plan_groups` are the methods no tool carries —
   the hook calls the first, the consolidator client the second".

10. **[NITPICK] `architecture.md:1859–1861` — "Three methods depart from that" and then lists
    five.** `memory_surface`, `memory_plan_groups`, and *three* `apply_` verbs. **Fix:** "Five
    methods depart from that, for three reasons — …".

11. **[NITPICK] §12's "§1 gives `core/` no logging" points at this document's own §1, which is
    "Scope".** `design/knowledge-index.md:2462`. The rule lives in `coding-standards.md` — §1
    gives `core/` no process concerns, §6 states the `logging` rule. **Fix:**
    "`coding-standards.md` §6 gives `core/` no logging".

12. **[NITPICK] `dispatch_knowledge.py:260` — "(§8.6)" with no document named.** The one bare
    section pointer across the M24-touched modules; `serialize_knowledge.py:4`,
    `primary.py:4–5,19,65` and `tool_names.py:6` all name theirs. **Fix:** "(`knowledge-index.md`
    §8.6)".

13. **[NITPICK] `lifecycle.refresh:300–306` Raises omits the unreadable-database propagation.**
    `builds.prepare:197–199` documents `aiosqlite.Error | ZikaronError | OSError` for a present
    database that will not open; `refresh:308` re-raises it unchanged and lists five other classes.
    **Fix:** copy the line from `prepare`.

14. **[NITPICK] `IndexerBusyError`'s first paragraph is contradicted by one of its raise sites.**
    `errors.py:98–109`: "raised on a lock that cannot be shown to be dead rather than on one
    proved alive", and the enumeration "a second build, and the removal" — `lock.force_release:270–277`
    raises it precisely on a holder `is_provably_live`, for an operator's forced release. The class
    gained its `holder` paragraph in round 1; the paragraph above it was not re-read. **Fix:**
    "Raised by anything that must not proceed alongside a build — a second build, a removal — on a
    lock that cannot be shown to be dead; and by an operator's forced release, on the one case the
    evidence contradicts: a process on this host answers to the recorded pid."

15. **[NITPICK] The memory→knowledge half of the new cross-reference is stated in no design
    document and pinned by no test.** `primary.py:93–94` — "This reads what agents recorded here;
    for what the project itself has written down … use `zikaron_knowledge_search`" — appears
    nowhere under `design/` (grep), while its twin is quoted at §8.3:1409–1410 and compared
    mechanically. `test_no_description_names_a_tool_its_own_server_does_not_have` guards the
    *name*; nothing guards the sentence. **Fix:** one line in `architecture.md`'s
    `zikaron_memory_search` block (:1097–1101), and a phrase test beside
    `test_zikaron_memory_retire_describes_the_supersession_graph_rules`.

### Checked and found sound (so the next round need not re-derive them)

- **Every round-1 finding, against the code rather than the brief.** 1: `_destroyable_chunks`
  returns `None` only for `ERROR`, `0` for the absent file, and the payload carries `state`;
  `_what_goes` does the same for the CLI; both design statements (§8.4:1904, :1924–1933;
  `architecture.md:1835`) agree. 2: `_check_supplied_size_cap` raises `InvalidSettingError` built
  from `meta.bounds_for`, `_as_bounds` maps it to `bounds {field, limit, actual}` with the
  exception's own values, and both `bounds` rows name it. 3: `holder=error.holder.describe()` and
  `actual=str(error.path)`; all four `IndexerBusyError` raise sites pass `holder`; the test asserts
  pid and host present, "retry" and the corpus name absent. 4: `KnowledgeBuildResult` documents
  the `list` projection with the two-name argument, and `_build_entry` uses `detailed=False`. 5:
  `_corpus_root` joins to `paths.scope_of`, and the test plants a decoy so the wrong resolution
  succeeds. 6 and 7: §8.4:1650–1653 says `knowledge_base_busy` and :1880–1884 carries
  `files_unlinked`. 8: `Observed.__post_init__` raises on either disagreement, tested both ways
  (`test_knowledge_reporting.py:110–128`); `state.inputs_for_open` hard-codes `unreadable=False`
  (`state.py:151`), so the third construction site can never be `ERROR`. 9: `_build_entry`'s
  docstring claims only that no `started` entry follows a failed spawn. 10: §12:2461–2470 and
  `record_search:203–207` both state lower-bound, build-concentrated drops, and ratio survival;
  the four increments are one `executemany` in one transaction. 11: the count assertion is gone
  and the file's existence is asserted.
- **Description parity.** The six management descriptions in `primary.py` are byte-identical to
  §8.4's and §8.5's block quotes by reading; `zikaron_knowledge_search` matches §8.3:1401–1433
  including the restored `zikaron_knowledge_list` sentence; the exemption is withdrawn in place at
  §8.3:1435–1443 and `test_every_knowledge_description_matches_the_design_document` states there
  is no exempted paragraph.
- **Wire shapes against §8.5, field for field.** `_summary_payload`: the five choosing fields.
  `_details_payload`: `root_path`, `git_mode`, `git_mode_effective`, `include`, `exclude`,
  `max_file_bytes`, `chunks`, `bytes_indexed`, `files_seen`, `files_skipped`, the nine-key
  `skipped`, the four counters, both scan instants, and `lock {pid, host, started_at, age_seconds,
  live}` — matching §8.5:2107–2129. Orphans `{path, name, size_bytes}` per :2220–2222; `orphans`
  always present, empty when a name was given. `remove` carries the diagnostic half and
  `files_unlinked`; `rename` carries no `outcome`.
- **Error mapping.** Six classes across `_as_bounds` and `_translated`, matching the raise sites
  reachable from the seven handlers; an unmapped class propagates (tested). Every payload field is
  a value except the blank-name case in finding 2. `KNOWLEDGE_CONFIRM_REQUIRED`'s spec has exactly
  `{name, state, files_indexed, chunks}`.
- **Counters.** `_serve` records only in `_SERVING` states; the elapsed-time assertion sits at a
  fifth of `busy_timeout`; the timeout is restored on the abandon path; non-contention propagates
  into the corpus's own `error` group.
- **Tests for fixture strength.** The relative-path decoy, the built corpus in the preview test,
  the omitted-`confirm` test, the ordering tests as orderings, and the `Observed` pairing tests
  each produce the condition their name claims. No new vacuous fixture found.
- **Comment hygiene.** No milestone, round or FINDINGS reference in any M24-touched module; the one
  undisambiguated section pointer is finding 12.

VERDICT: NEEDS_CHANGES

## Round 3 — 2026-09-16

### Summary judgment

All fifteen round-2 findings are fixed as described, and the `_as_bounds`/`_translated`/
`_refusals_as_wire_errors` signature change — the place the brief named as most likely to cascade —
is clean at every one of its six call sites: the value match picks the right parameter in every case
a handler can produce, insertion order agrees with validation order where it is load-bearing, and
the three new tests each distinguish the fix from the pre-fix code. No behaviour defect in the six
verbs or the counters. What remains is one real hole that round 2's `~` pass-through opened on the
service side and that the CLI already had — a `~user` prefix naming no user reaches
`Path.expanduser`, which raises `RuntimeError`, and neither surface catches it — plus a small set of
the cascade class: a docstring in the function round 2 fixed asserting the state line reads `error`
in both of its branches, the `dispatch.py` sibling of the universal round 2 corrected in
`primary.py`, and a citation in §12 whose paraphrase of `coding-standards.md` §6 is not what §6 says.

### Findings

1. **[IMPROVEMENT] A `~user` path whose user does not exist — or any project directory literally
   named `~something` — is an internal error on the tool and an uncaught traceback on the CLI.**
   `zikaron/service/dispatch_knowledge.py:297` passes anything beginning `~` through untouched, so
   it reaches `zikaron/core/knowledge/roots.py:37` `path.expanduser().resolve()`. For `~alice/docs`
   with no user `alice`, `posixpath.expanduser` returns the string unchanged and pathlib then raises
   `RuntimeError("Could not determine home directory.")` (`/usr/lib/python3.12/pathlib.py:1407–1408`
   — read, not assumed). That is not a `KnowledgeError`, so `_refusals_as_wire_errors` lets it
   through to `server.py`'s `except Exception` fallback: the model sees *internal error* for a value
   it typed. On the CLI, `zikaron/knowledge/scope.py:122–130` catches `KnowledgeError`,
   `ZikaronError`, `aiosqlite.Error` and `OSError` and nothing else, so `python -m zikaron.knowledge
   add x --path '~alice/docs' …` prints a traceback. This contradicts §8.4:1894 ("every refusal
   these four verbs can raise has a wire code"), §11:2441 ("every failure is an error result"), and
   `validate_root`'s own `Raises:` (`roots.py:33–35`), which lists only `InvalidRootError`. The
   service half is new: before round 2, `~alice/docs` was joined to the project root, never reached
   expansion as a leading `~`, and was refused cleanly as *does not exist*. The four `~` sites now
   promise that "a leading `~` expands to the home directory", and this is the case where it cannot.
   **Fix.** In `roots.validate_root`, wrap the expansion:
   `try: expanded = path.expanduser()` / `except RuntimeError as error: raise
   InvalidRootError(f"{path} begins with a ~ naming no home directory this machine knows",
   path=path) from error`; then `resolved = expanded.resolve()`. One site fixes both surfaces, and
   `_as_bounds` already maps the class to `bounds {field: "path"}`. Amend `validate_root`'s
   `Raises:` (a fourth clause, or fold it into "does not exist"), and `InvalidRootError.path`'s
   docstring (`errors.py:73–75` says **as resolved**; here there is no resolved form, so say "as
   supplied where the `~` prefix could not be expanded"). Tests: one in `tests/test_knowledge_roots.py`
   asserting `InvalidRootError` on `Path("~no-such-user-zikaron/docs")`; one in `TestAdd` asserting
   `bounds` and `field == "path"` for the same string; one CLI sibling of `test_a_bad_root_exits_non_zero`
   asserting exit 1 and "refused" in stderr. Mutation: delete the `except` and watch all three fail
   (the service one with `RuntimeError`, the CLI one with a traceback). If you widen the three-way
   enumeration ("absent, not a directory, degenerate") rather than folding, count its sites first
   — I found `roots.py:33–35`, `errors.py:67`, `dispatch_knowledge.py:103` and `:130`,
   `knowledge-index.md:1905`, `:1909`, `:2264–2266`, `architecture.md:1823`, and the two
   description quotes at `primary.py:231` and `knowledge-index.md:1945` — which is why folding into
   "does not exist" is the cheaper honest answer.

2. **[NITPICK] `_print_details`'s docstring says the state line reads `error` in both of its
   branches; in the absent-database branch it reads `reindex_required`.**
   `zikaron/knowledge/main.py:383`: *"The state line above says `error` either way; this line is
   what a reader takes the meaning from."* `reporting.observe:332–334` reports an absent database as
   `REINDEX_REQUIRED`, `state.resolve` never yields `ERROR` for it, and the CLI test written for the
   absent case (`tests/test_knowledge_cli.py:456`) asserts `"reindex_required" in printed`. So the
   docstring of the function round 2 fixed contradicts a test in the same milestone — the cascade
   class, inside the fix. It also undercuts its own argument: if the state line said `error` in the
   absent case, the `else` branch's "nothing has been built here yet" would be exactly the confident
   claim the paragraph says to avoid. **Fix:** *"The state line above already names which —
   `reindex_required` or `error`; this line is what a reader takes the meaning from."*

3. **[NITPICK] The "no tool carries it" universal is still wrong at one site round 2 did not
   reach, and one member short at the site it did.**
   `zikaron/service/dispatch.py:25` — *"`memory_surface` is the one method with no tool at all,
   since the hook calls it directly"* — is the pre-round-2 sentence, in the module that dispatches
   the memory verbs; round-2 finding 9 corrected its twin in `primary.py` and this sibling was not
   swept. `zikaron/mcp/primary.py:20–22` now reads *"`memory_surface` and `memory_plan_groups` are
   the methods no tool carries at all"* — but `health` carries no tool either, which finding 9
   named as the third; the brief's "`health` keeps its bare name" is about its *name*, not about
   this count. `architecture.md:1863–1868` handles it correctly by naming `health` in the next
   sentence. **Fix:** `dispatch.py:25` → "`memory_surface` and `memory_plan_groups` are the methods
   with no tool, the hook calling the first and the consolidator client the second; `health` is the
   one method with no subsystem …". `primary.py:20–22` → "… are the *subsystem* methods no tool
   carries; `health`, which has neither tool nor subsystem, is dispatched before any of them".

4. **[NITPICK] `_as_bounds` has two edges its docstring does not state and no test pins, and one
   of them contradicts the module's own rule for unmapped cases.**
   `zikaron/service/dispatch_knowledge.py:116–119`: when no supplied value equals `error.value`, the
   field falls back to the first key, and when `supplied` is empty, to the literal `"name"`. Neither
   is reachable — every call site passes a non-empty mapping, and every `InvalidNameError` a
   handler can meet is raised on a value the handler supplied (traced: `lifecycle.add:191`,
   `registry.rename:169–170`, `registry.require` from `status`/`remove`/`plan`) — so both defaults
   are the `next()`-argument shape coverage cannot see, the class round-1 finding 8 closed for
   `_stopped_by`. The first-key fallback also names a parameter that was *not* refused, which is
   the "plausible-looking refusal for a defect" `_translated`'s docstring (`:157–160`) says this
   module must not produce. And `TestTranslatingARefusal`'s docstring
   (`tests/test_service_knowledge_management.py:899–901`) still says "the two branches … the six
   handlers cannot reach" — this fallback is a third, added by round 2. Separately, the docstring's
   "insertion order decides ties … so the first blank one is the one named" (`:112–113`) is
   load-bearing only for byte-identical blanks, where either answer is correct; no test exercises
   it. **Fix, either way:** (a) make the fallback `None` — no match means `core` refused a name this
   call did not send, which is the defect case, so return `None` and let `_refusals_as_wire_errors`
   propagate it; or (b) keep it, say so in the docstring, and add a direct test beside the two in
   `TestTranslatingARefusal` (`_as_bounds(InvalidNameError("x", value="  "),
   supplied={"knowledge_base": "docs"})` → `field == "knowledge_base"`), updating "two branches" to
   three. Either way, either soften the tie sentence to "identical blank values name the first,
   which is also the first validated" or pin it with `{"name": " ", "new_name": " "}` → `"name"`.

5. **[NITPICK] §12's paraphrase of `coding-standards.md` §6 is not what §6 says.**
   `design/knowledge-index.md:2465`: *"§6 puts every log file in the hands of a long-lived
   process"*. `coding-standards.md:286–298` says each log file has exactly one writing process
   (because `logging.FileHandler` has no cross-process append locking), that `logging` is for
   processes that are long-running **or off the critical path**, and that `hook.log` is written by
   `zikaron-hook` — which exits after one line — and `warmup.log` by a detached helper that is not
   long-lived either. Two of the three log files are in the hands of short-lived processes. The §1
   half of the citation is exact (`coding-standards.md:15`). **Fix:** "§6 gives every log file a
   single writing process", which is the half that actually bears on a counter write running in
   whichever process imports `core/`.

6. **[NITPICK] `KnowledgeRemoveResult` gives a narrower reason for `files_unlinked` being one path
   than the module that computes it.**
   `zikaron/service/serialize_knowledge.py:223–225` — "a corpus that was never built has no `-wal`
   or `-shm`, so one path is the ordinary answer" — implies a *built* corpus yields three.
   `lifecycle.remove:369–374` and §8.4:1880–1884 give the reason that holds for every corpus:
   reading its state opens and closes it, and SQLite reclaims both siblings on the last close. A
   reader using the list's length to infer whether the corpus was built would be misled. **Fix:**
   replace the clause with the lifecycle wording.

### Checked and found sound (so the next round need not re-derive them)

- **`_as_bounds`'s value match, every reachable case.** `add`: `lifecycle.add:191` normalizes
  `request.name`, the one supplied value. `rename`: `registry.rename` validates `name` via
  `require` before `normalize_name(new_name)`, matching the mapping's insertion order; blank `name`
  with valid `new_name`, valid `name` with blank `new_name`, and distinct blanks all name the refused
  parameter with its own value. `status`: `optional_str` returns `""` for an explicit empty string,
  `reporting.status:427` requires it, and the match lands on `knowledge_base`; `None` never reaches
  `normalize_name`. `refresh`/`remove`/the preview: one key, one value. `subject` for corpus-naming
  codes is the first supplied value at every site; `taken` is passed only by `rename`.
- **The three new dispatch tests distinguish the fix.** Under pre-fix code the blank `new_name`
  case reported `name`/`"docs"`, the blank `knowledge_base` case reported `name`, and the malformed
  `full` case reported `knowledge_base_unknown`; each assertion fails there.
  `test_a_blank_current_name_names_that_one_instead` passes under pre-fix code too, but it pins the
  other side of the same rule (a mutation to the last key fails it), so it is a complement rather
  than a vacuous test.
- **The two new root tests distinguish their conditions.** `path="nope"` asserts `actual` is
  `str(tmp_path / "nope")`, which the absolute fixture cannot tell from *as supplied*; `~/notes`
  under a monkeypatched `HOME` would raise *does not exist* if the path were joined first.
- **Four `~` sites agree** (`_corpus_root:290–294`, `primary.py:232–233`, §8.4:1946, §8.6:2277–2278)
  and **four `bounds` sites agree on three members** (§8.4:1905, `architecture.md:1823`,
  `_as_bounds:102–106`, `FINDINGS.md:1522–1528`). `errors.py:15`'s "Four" matches the four
  value-carrying classes.
- **§8.5:2205's "only place" claim.** `LAST_SCAN_GIT_MODE_EFFECTIVE_KEY` is read at
  `reporting.py:287` alone; `scan.py:200` and `:264` are writes. The narrowing from "only `status`"
  to "this diagnostic half" is right, since `remove`'s snapshot carries `Details` too.
- **§9's failure-versus-refusal line now matches the code.** `_report_obstacle:267–269` prints
  `failed` for `UNREADABLE`, the prefix `scope.execute:130` gives a driver error; the CLI test asserts
  "refused" is absent.
- **`_print_details`'s `ERROR` branch** is exercised with `_corrupt_database` and the test asserts
  the absent-case sentence is not printed and `state error` is.
- **`lifecycle.refresh`'s Raises** now carries the `aiosqlite.Error | ZikaronError | OSError` line
  from `builds.prepare`. **`IndexerBusyError`'s docstring** matches its four raise sites in both
  readings. **`architecture.md:1863`'s five** are `memory_surface`, `memory_plan_groups` and the
  three `apply_` verbs, with `health` handled in the following sentence.
- **The cross-reference** is stated at `architecture.md:1102–1105` and pinned in both directions by
  `test_each_search_tool_names_the_other_store_s_search`. `dispatch_knowledge.py:289` names its
  document.
- **Comment hygiene.** No milestone, round or FINDINGS reference in `dispatch_knowledge.py`,
  `errors.py`, `main.py`, `roots.py`, `builds.py`, `serialize_knowledge.py`, `primary.py`,
  `registry.py`, `reporting.py` or `lifecycle.py`; the design pointers that remain all name their
  document.

VERDICT: NEEDS_CHANGES

## Round 4 — 2026-09-16

### Summary judgment

All six round-3 findings are fixed as described, and this round finds nothing material. The `~`
hole is closed at the one site that serves both surfaces, the fold into *does not exist* left every
statement of `validate_root`'s refusal set agreeing — `Raises:`, `InvalidRootError`, `_as_bounds`,
`lifecycle.add`, §8.4's row, `architecture.md`'s row and FINDINGS — so no design row had to move, and
each of the three new tests fails under the stated mutation at its own layer. `_as_bounds` returning
`None` changes no behaviour a handler can reach and propagates correctly where it cannot. What
remains is three nitpicks of the prose-beside-code kind, none of which touches a wire shape, a
refusal, or a test's strength; the milestone is ready as it stands.

### Findings

1. **[NITPICK] `TestTranslatingARefusal`'s class docstring describes three unreachable branches;
   its second member is neither a branch nor unreachable.**
   `tests/test_service_knowledge_management.py:915–916`: *"The three branches of the translation
   that the six handlers cannot reach between them, and which exist for what a later edit might do
   rather than for what today's code does."* `test_two_identical_blank_names_report_the_first`
   (`:931–939`) is reachable today: `require_str` accepts `" "` (`params.py:48–53`), so
   `knowledge_rename(name=" ", new_name=" ")` reaches `registry.rename:169` → `require` →
   `normalize_name` → `InvalidNameError(value=" ")`, and `_as_bounds` names `name`. Its own
   docstring says so ("A rename can be given the same blank twice"). And it is not a branch — the
   tie is `next()` taking the first match — so the class's count of three is right only for the
   other three tests (`:918`, `:941`, `:955`). **Fix**, preferably: move it into `TestRename` and
   drive it through the handler — `_call(ctx, "knowledge_rename", {"name": " ", "new_name": " "})`
   asserting `code is ErrorCode.BOUNDS`, `data["field"] == "name"` and `data["actual"] == " "` —
   which pins reachability and the validation-order claim at `dispatch_knowledge.py:112–113` in one
   test rather than at the unit alone. Or keep it where it is and reword the class docstring: *"Three
   branches the six handlers cannot reach between them, and the one tie they can."*

2. **[NITPICK] `_translated`'s third paragraph says `None` means an unmapped class; since round 3
   a mapped class returns it too.**
   `zikaron/service/dispatch_knowledge.py:162–165`: *"**An unmapped class returns `None` and is
   propagated unchanged rather than given a nearby code.** The classes these verbs can actually
   raise are the six across both functions; anything else reaching here is a defect…"*. After
   round-3 finding 4's fix, `_as_bounds:121–124` returns `None` for an `InvalidNameError` — one of
   the six — whose `value` matches no supplied name, and `_translated` then returns that `None`
   without the paragraph one function up saying so. `_as_bounds`'s own docstring (`:115–119`)
   states the case; the function that hands the `None` on does not. The first line (`:151`, "or
   `None` for one that has no code") is loose enough to cover it; this paragraph is not. **Fix:**
   *"**An unmapped class — or a mapped one refusing a value this call never sent — returns `None`
   and is propagated unchanged rather than given a nearby code.**"*

3. **[NITPICK] The nineteen review-round mutations are recorded in no file.**
   `FINDINGS.md:1552` — *"Eighteen mutations applied; fifteen caught, three survived"* — is the
   first-pass tally. The brief for this round states nineteen more applied against rounds 2–4's
   fixes, all caught; that number lives only in the review briefs, which are messages rather than
   files. M21's block (`:622–624`, "twenty in the first pass…, three verifying review round 1's
   fixes, two verifying round 2's") and M23's (`:1294–1296`) both record the review-round count
   beside the first pass, and this project's own rule is that a number stated nowhere durable is
   one it has already lost once. **Fix**, when the block is closed at landing: *"…and nineteen more
   aimed at the fixes review rounds 2–4 produced — all nineteen caught, two of them this round: the
   `~` catch clause narrowed to `ValueError`, and `_as_bounds`'s `None` restored to a first-key
   fallback."*

### Checked and found sound (so the record shows what this approval rests on)

- **The `~` fix, both surfaces.** `roots.validate_root:38–45` catches `RuntimeError` from
  `expanduser` alone and raises `InvalidRootError(f"{path} does not exist", path=path)`; the four
  later refusals still report `path=resolved`. Service: `_corpus_root:302` passes `~…` through,
  `lifecycle.add:190` calls `validate_root`, `_as_bounds:131–137` maps to `bounds {field: "path",
  actual: <as supplied>}`. CLI: `scope.execute:122–123` prints `refused:` for any `KnowledgeError`.
  Under the stated mutation (`except ValueError`) the `RuntimeError` escapes: the roots test's
  `pytest.raises(InvalidRootError)` does not match it, the service test's
  `pytest.raises(ZikaronError)` does not match it, and the CLI test's `_run` raises in-process.
- **The refusal set is stated identically at every site under the fold.** `roots.py:32–36`
  (names the `~` case inside the does-not-exist clause), `errors.py:67` and `:73–77` (the
  as-resolved rule with its one stated exception), `_as_bounds:102–103`, `lifecycle.add:184`,
  `knowledge-index.md:1905` and `:1909`, `architecture.md:1823`, `FINDINGS.md:1522–1524`. None
  enumerates a fourth cause, and none needs to.
- **The three new tests pin what their names claim.** `test_knowledge_roots.py:38–50` asserts the
  class, the message and `path == supplied` — the last of which distinguishes this branch from the
  ordinary does-not-exist branch two lines below it, which reports `resolved`.
  `test_service_knowledge_management.py:252–261` asserts `BOUNDS` and `field == "path"`.
  `test_knowledge_cli.py:304–318` asserts exit 1, "refused" and "does not exist"; a traceback would
  surface as an in-process exception from `_run` rather than a return value.
- **`_as_bounds` returning `None`, traced through.** `_translated:167–169` skips it, none of the
  three corpus classes match an `InvalidNameError`, `_translated` returns `None`, and
  `_refusals_as_wire_errors:212–213` re-raises the original. No caller assumed a `bounds` for every
  blank name: each of the six handlers supplies exactly the names it passes to `core` (`:256`,
  `:337`, `:368`, `:386`, `:407`, `:432`), so the `None` path is unreachable through them and
  reachable only by a direct call, which is what the new test does.
- **The `health` claim.** `server.py:109–111` answers `health` in a named branch before
  `_METHODS.get` at `:122`; `_METHODS:33–37` merges the primary, consolidator and knowledge tables.
  `dispatch.py:25–27` and `primary.py:20–23` now name `memory_surface` and `memory_plan_groups` as
  the subsystem methods with no tool and `health` as carrying neither; `architecture.md:1863–1868`
  agrees.
- **`_print_details`** (`main.py:383–384`) now names both states; `reporting.observe` reports an
  absent database as `REINDEX_REQUIRED`, and the two CLI tests (`test_knowledge_cli.py:470–472`,
  `:484–488`) assert the matching state string in each branch.
- **`KnowledgeRemoveResult:223–227`**, `lifecycle.remove:369–374` and §8.4:1880–1884 all now give
  the open-and-close reason, and none implies a built corpus yields three paths.
- **§12:2465–2466** cites `coding-standards.md` §6 for exactly what §6 says — one writing process
  per log file.
- **`roots.py:55`** is left unguarded as the brief states, and the reasoning holds: `lifecycle.add`
  passes `Path.home()`, which is absolute, so the `~` branch of that `expanduser` is never taken
  through any caller but a test.
- **The literal-`~directory` edge** round 3 named (a project directory called `~scratch`) is refused
  as *does not exist*, which is not literally true of it — but it is the wording `bash` itself gives
  (`cd ~scratch` → "No such file or directory"), the tool description states the `~` rule at
  `primary.py:233`, and the remedy (an absolute path) follows from that rule. Not worth a finding.
- **Comment and test hygiene.** No milestone, round or FINDINGS reference in `roots.py`,
  `errors.py`, `dispatch_knowledge.py`, `dispatch.py`, `primary.py`, `serialize_knowledge.py` or
  `knowledge/main.py`, nor in the three new test docstrings. The one "review round" string under
  `zikaron/` is `service/main.py:440`, which predates and is outside this milestone.

VERDICT: APPROVED
