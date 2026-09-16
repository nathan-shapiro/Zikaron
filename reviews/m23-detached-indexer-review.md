# M23 — the detached indexer, progress, and the repair paths — review

Artifact set: `zikaron/core/knowledge/{repair,lock,scan,changes,ddl,state,reporting,lifecycle,registry,files,disposal,errors}.py`,
`zikaron/core/clock.py`, `zikaron/knowledge/{main,scope}.py`, `zikaron/knowledge/indexer/{main,detach}.py`, the
named tests, and the in-place amendments to `design/knowledge-index.md` §6.2, §8.4, §8.5, §9, §11 and
`design/build-plan.md` §M24. Brief: `design/build-plan.md` §M23.

## Round 1 — 2026-09-15

### Summary judgment

The code is careful and almost everywhere does what the normative sections say: `running_holder` is the
right single predicate for its three consumers, `full` is genuinely an ordinary scan with the comparison
bypassed, the `lifecycle`/`reporting` split lands on a clean one-directional seam, and the detach path is
checked in a real process tree. Two things stop it shipping. The recovery claim the brief most wants
challenged — an interrupted rebuild is repaired by the next ordinary build with nothing recording that a
repair was owed — holds only while the `meta`-versus-configuration disagreement that triggered the drop
persists; the moment configuration is put back, the corpus reports `ok` over an empty index and every
later build dies on its first vector insert, and the two tests named for "still refuses" produce exactly
that `ok` state without asserting anything about it. And the pre-M21 claim that `refresh` rebuilds a
knowledge base whose database is absent survives in roughly a dozen sites — two of them normative §8.4
bullets and one invariant — beside the M21 correction that says it refuses, in the enumeration-drift
shape this corpus names as its dominant defect.

### Findings

1. **[BLOCKER] An interrupted rebuild is not recoverable once the configuration that triggered it is
   reverted — the corpus reports `ok` over nothing, and every subsequent build fails on the first
   vector insert with nothing naming the exit.** This is brief item (a), and the answer is "no".
   The trigger for the drop is `repair.rebuilt_identity(recorded, build.encoder)`
   (`zikaron/core/knowledge/scan.py:353-355`, `:367-368`), i.e. *`meta` disagrees with the loaded
   encoder*. The physical fact the drop changes is `chunks_vec`'s declared width. Nothing reads that
   width back. Trace, every step from the code as it stands:
   - configuration says model B / 768; `meta` says A / 384; `refresh` → child runs `_begin`
     (`scan.py:365`), then `drop_derived(embed_dim=768)` commits (`repair.py:66-83`; `chunks_vec` is
     now `float[768]`, `files` empty, `chunks` empty), then embeds and is killed;
   - operator puts configuration back to A / 384 (the ordinary "tried a model, too slow, reverted"
     sequence);
   - `state.inputs_for_open` (`state.py:108-115`): `encoder_mismatch` is `False` (`meta` == config),
     `never_built` is `False` (`last_scan_completed_at` is still the earlier build's — neither `_begin`
     nor the drop touches it), `indexing` is `False` (pid gone). `resolve` returns **`OK`**. Search
     serves (`groups.py:317`, `_SERVING`) from an empty `chunks` table — the exact "empty groups
     filling in over minutes ... misinformation" §8.4:1761-1764 rejects, reached by another door;
   - `refresh`: `rebuilt_identity(A/384, encoder A/384)` → `None`; ordinary scan; `files` is empty so
     every candidate is changed by definition (`changes.py:130`); `_record_indexed` →
     `vectors.embed_chunks(..., embed_dim=384)` passes → `writes.index_file` → `vectors.insert` of a
     384-wide blob into a `float[768]` column. Per the design's own probe (§8.4:1694-1695, "rejects
     old-dimension inserts") this raises, inside the per-file transaction, propagated by `propagate`,
     lock released by `finally`; the child's output is discarded. `state` is still `ok`. Every
     `refresh` repeats this. The only exit is `remove` + `add`, and nothing says so.
   Three prose sites assert the property this breaks: `repair.py:17-20` ("drops unconditionally
   whenever the identity disagrees, including on the scan that follows a crashed rebuild" — true, and
   the gap is *when it stops disagreeing*), `scan.py:296-302` (`_complete`'s "with no state anywhere
   saying a repair was owed"), and §8.4:1666-1670 ("The `reindex_required` variant is immune by
   construction: `meta` still names the old identity, so any later scan begins under the mismatch").
   **The test suite already manufactures this state and does not look at it.**
   `tests/test_knowledge_repair.py::test_an_interrupted_rebuild_still_refuses_and_the_next_build_completes_it`
   (`:294-320`) and
   `tests/test_knowledge_build_invariants.py::test_an_unfinished_rebuild_keeps_the_identity_it_has_not_replaced`
   (`:428-449`) both pass a differently-named `FakeEncoder` while **configuration is left at the
   default**, which equals `meta`. So in the interrupted window of both tests the corpus is `ok`, not
   refusing; neither asserts `state`; and the "next build completes it" half passes only because the
   next build is *also* run with the foreign encoder. Run the completing build with `FakeEncoder()`
   and it fails as traced above.
   **Suggested change**, in three parts. (i) Make the drop's trigger the disjunction of the recorded
   identity and the physical width. Add to `repair.py`:
   ```python
   async def declared_vector_width(db: aiosqlite.Connection) -> int:
       """The width `chunks_vec` was created at, read off its own declaration rather than off `meta`."""
       rows = await db.execute_fetchall(
           "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'chunks_vec'"
       )
       ((sql,),) = list(rows)
       return int(re.search(r"float\[(\d+)\]", str(sql)).group(1))  # our own statement's text
   ```
   and in `scan.run`, after `rebuilt` is computed:
   `if rebuilt is None and await repair.declared_vector_width(db) != corpus.embed_dim: rebuilt = corpus`
   — a redo at the recorded identity; `_complete` then rewrites keys that already match, which is
   harmless. (ii) Make the *state* honest in the window too, or the corpus still says `ok` over
   nothing until somebody builds: `state.inputs_for_open` gains the same width check folded into
   `encoder_mismatch` (one `sqlite_master` read per open; §8.5 already budgets "a handful of `meta`
   rows" here). This is not the repair checkpoint §8.4 refuses — it reads a fact the table already
   carries. (iii) Fix the two tests to create the mismatch **through configuration** — `write_config`
   with `embed_model = "other"` and a re-resolved `config_for` (the pattern
   `test_a_full_build_picks_up_a_changed_chunk_budget` already uses for a tuning key) — and assert
   `state is KnowledgeState.REINDEX_REQUIRED` in the interrupted window; then add the regression this
   finding is about: interrupt a rebuild to `_OTHER_DIM`, revert (i.e. build with `FakeEncoder()`),
   assert the build completes, `chunks` is non-empty and every stored vector is 384 wide. Finally
   restate §8.4:1666-1670 and `repair.py:17-24` so the recovery claim names its actual condition.

2. **[BLOCKER] The absent-database repair path is stated two contradictory ways, and the wrong one
   survives in two normative §8.4 bullets, one invariant, and eight code and test docstrings.** M21
   settled that `refresh` **refuses** a registered knowledge base whose file is gone (§8.4:1581-1586,
   §11:2131, `lifecycle._open_registered`, `DanglingKnowledgeBaseError`), because the definition lived
   in the file. The code implements that everywhere. The following still assert that a build rebuilds
   it — all in scope, since §8.4's repair rules and §11's absent-database row are normative here:
   - `design/knowledge-index.md:160-162` (§3.1a): "so the next `refresh` would **silently rebuild** the
     corpus the caller had just asked to destroy" — the reverse-ordering argument now rests on
     §8.4:1601-1608's "stays worse now that the dangling name needs a command", not on resurrection.
   - `design/knowledge-index.md:1594` (§8.4): "for a condition a refresh repairs entirely" — the
     empty-file state is folded into the absent state, which `refresh` refuses; `remove` + `add`
     repairs it.
   - `design/knowledge-index.md:1708-1710` (§8.4): "nothing to refuse: the KB serves as an empty corpus
     (§7.4) **until the scan builds it**".
   - `design/knowledge-index.md:1713-1716` (§8.4): "a scan begun under any of them *is* the repair
     variant, however it was invoked ... the other two are ordinary scans against a corpus that is
     missing rather than wrong" — a scan cannot begin under the first cause at all.
   - `design/knowledge-index.md:1718-1720` (§8.4, the "No database file" bullet): "create the database,
     write `meta` from the current configuration, and index every candidate. This is the ordinary path
     for a KB whose `add` was interrupted" — this is a specification of behaviour the code refuses,
     forty lines below the bullet that says it refuses.
   - `design/knowledge-index.md:2219` (§13, invariant 15): "search answers it as an empty group and
     **`refresh` rebuilds it**".
   - `zikaron/core/knowledge/database.py:236-239`: "an empty knowledge base the next build fills in
     with nobody's involvement".
   - `zikaron/core/knowledge/registry.py:9` ("a row without a file is an empty knowledge base needing a
     build") and `:194-196` ("a name whose corpus the next build would silently recreate").
   - `zikaron/core/knowledge/reporting.py:8` — **written this milestone**: "An absent database is an
     empty corpus a build fills".
   - `zikaron/core/knowledge/groups.py:284-285`: "an absent database is an empty corpus that a build
     fills".
   - `tests/test_knowledge_lifecycle.py:5-6` (module docstring: "an interrupted `add` leaves a corpus
     the next build repairs with nobody's involvement" — contradicted by the same file's
     `TestWhatHasToHoldBeforeABuildStarts::test_a_corpus_with_no_database_is_refused`), `:165` (the
     test name `..._still_leaves_the_healing_state`), `:172-174` ("a condition a rebuild fixes
     entirely"), and `:230-233` ("which the next build would read as an empty corpus and silently
     rebuild").
   **Suggested change.** One claim, one wording, everywhere: *a registered knowledge base with no
   database is reported and searched as an empty corpus; `refresh` refuses it, and `remove` then
   `add` recreates it, losing nothing that was ever indexed under that name.* For §8.4:1718-1720
   specifically: "**No database file** (§11). Nothing to drop and nothing to scan: the definition went
   with the file, so `refresh` refuses and names `remove` + `add`. `list`, `status` and search treat
   it as an empty corpus meanwhile." For invariant 15: "... search answers it as an empty group,
   `refresh` refuses it, and `remove` then `add` recreates it." Rename the test at `:165` to
   `..._still_leaves_the_absent_database_state`. Then grep the corpus for the claim in its other
   phrasings — `fills`, `heals`, `recreate`, `rebuild`, `nobody's involvement`, `needing a build` —
   and reconcile the count against the list above before the next round.

3. **[IMPROVEMENT] `prepare_build` omits the one foreground refusal that leaves no trace when it fires
   in the child, so §9's universal is false.** §9:2064-2066: "**Every** refusal a build can be given
   before it reads a file is given in the foreground ... an unknown name, a knowledge base whose
   database is gone, a lock that cannot be shown to be dead." A root that is gone is a fourth, decided
   by `Path(meta.root_path).is_dir()` with the database already open in
   `lifecycle.prepare_build` (`lifecycle.py:296-299`) — and it is the one refusal that also leaves
   *nothing* behind: `scan.run` raises `CorpusRootMissingError` at `scan.py:357-360` **before**
   `_begin`, so no lock row is written and §9's own "visible as a fact ... `status`'s `lock` shows a
   holder whose process is gone" does not apply. Today `refresh` on a `root_missing` corpus prints
   "building 'x' in the background", the child exits immediately, and the operator has only
   `status`'s `root_missing` to infer from. **Change**: inside `prepare_build`'s `_open_registered`
   block, `if not Path(opened.meta.root_path).is_dir(): raise CorpusRootMissingError(...)` with the
   same wording `scan.run` uses so both surfaces read alike; add the case to
   `tests/test_knowledge_lifecycle.py::TestWhatHasToHoldBeforeABuildStarts` and to
   `tests/test_knowledge_cli.py::TestStartingABuild` (exit 1, `started == []`); add "a root that has
   gone" to §9's enumeration.

4. **[IMPROVEMENT] The done-when's search clause has no test at the search layer, and `_SERVING`
   containing `INDEXING` is guarded by nothing.** "A search during a build returns committed files and
   reports `indexing` with a falling `files_remaining`" is asserted only through `reporting`
   (`tests/test_knowledge_reporting.py:424-444`) and `state`. Nothing under `tests/` exercises
   `groups._serve` (`groups.py:313-327`) with a running lock: grep for `KnowledgeState.INDEXING` and
   `"indexing"` in `tests/` finds reporting and state tests only. Remove `KnowledgeState.INDEXING` from
   `_SERVING` (`groups.py:63`) and the suite stays green — a corpus mid-build would then answer empty
   with `state: indexing`, which is the opposite of §6.3. **Change**: one test on the search entry
   point that builds a corpus, plants `lock_pid=os.getpid()`, `lock_host=lock.this_host()`,
   `lock_started_at`, `last_scan_started_at ≤ last_walk_completed_at` and N `pending` rows, then
   asserts the group carries `state == "indexing"`, `files_remaining == N`, non-empty `results`, and
   `stale: true` on the pending path; a second call after disposing one row pins "falling". Verify
   by the `_SERVING` mutation above.

5. **[IMPROVEMENT] "Provably live" is pid liveness, not identity, and pid reuse closes the only exit
   the design provides.** `_process_is_alive` (`lock.py:105-120`) answers *a process with this id
   exists*. After a crash the pid is free; on a `pid_max = 32768` host it is reused within hours, and
   the lock can sit for days. Then `running_holder` says running — `refresh` reports
   `already_indexing`, `remove` refuses (§8.4:1633-1639) — **and** `force_release` refuses too
   (`lock.py:244-248`, "still running ... stop it first"), telling the operator to kill an unrelated
   process. That is the "knowledge base nothing can manage" §6.2:1058-1062 says `--force-unlock`
   exists to break, with `--force-unlock` itself blocked. §6.2:1063-1065 and §9:2075-2076 call this
   "the one case where the holder is provably running"; it is not provable from a pid. **Change**, at
   minimum: state the limit in §6.2 and in `force_release`'s docstring and message ("pid N answers a
   signal from this host, which is evidence a process exists and not that it is this indexer; if it
   is not, the pid has been reused and the rows must be deleted by hand"), and have `status`'s lock
   line (`main.py:320-333`) say the same for `live: True`. If the project wants a mechanism: on Linux
   read `/proc/<pid>/cmdline` and treat a process not running `zikaron.knowledge.indexer` as gone,
   answering `None` where `/proc` is absent — noting that every "live holder" fixture in the suite
   currently uses `os.getpid()` (pytest) and would have to change.

6. **[IMPROVEMENT] Two docstrings in the indexer package describe the pre-M23 synchronous `refresh`,
   beside code and tests that say the opposite.** `zikaron/knowledge/indexer/__init__.py:8-9`:
   "Invoked **synchronously today by the `refresh` verb**, so the person who asked for a build waits
   for it." `zikaron/knowledge/indexer/main.py:3-5`: "The management command's `refresh` verb
   **calls `build` directly** rather than reimplementing it." `zikaron/knowledge/main.py` imports
   neither `build` nor this module — it calls `detach.spawn` (`main.py:218`) — and
   `tests/test_knowledge_indexer.py:190-192` says so in as many words ("The management verb does not
   run it — it starts it detached"). **Change**: `__init__.py` — "Started detached by `add` and
   `refresh`, and run in the foreground by an operator who wants to see a build's output"; `main.py`
   — "The management command spawns this module rather than calling `build`, so a build means one
   thing however it was asked for; `detach.command` is the argv it uses."

7. **[IMPROVEMENT] The printed `follow` hint is not shell-quoted, and names with spaces are a
   documented input.** `main.py:220`: `print(f"follow    python -m zikaron.knowledge status {name}")`.
   For `Design Docs` (the suite's own first example, `tests/test_knowledge_cli.py:119`) this prints
   `status design docs`, which pasted back fails to parse. The reproduce line two prints later uses
   `shlex.join`; this one should use `shlex.quote(name)`. Pin it in
   `test_add_starts_a_build_of_the_corpus_it_just_created` with a two-word name.

8. **[NITPICK] `lock.is_held`'s docstring justifies its existence by a check `release` does not
   perform.** `lock.py:62-71`: "What this answers is whether anything was ever written, which is what
   a release has to be able to check." `release` (`lock.py:207-215`) is deliberately unconditional and
   checks nothing; `is_held`'s only production caller is `read`. Either make it `_is_held` (tests call
   `lock.is_held` at `test_knowledge_lock.py:43,48,235,250,259,266,274` and `test_knowledge_scan.py:428,462` —
   they can use `lock.read(...) is not None`), or reword: "the presence test `read` is built on, and
   what a test asserts after a release."

9. **[NITPICK] `lifecycle.Refreshed`'s example of an unchanged status is the case this milestone made
   change.** `lifecycle.py:97-99`: "which a build can leave unchanged, for instance when the encoder it
   was configured with has moved on since the index was made" — a moved-on encoder now rebuilds and
   the status *does* change. The surviving example is §8.4:1743-1750's: configuration names a model
   that emits a different width than configuration states, so the rebuilt corpus goes on reporting
   `reindex_required`.

10. **[NITPICK] Two acquirers racing `_begin` produce a driver error for the loser rather than the
    named refusal.** `in_one_transaction` issues a deferred `BEGIN` (`transactions.py:167`); two
    processes that both read *no holder* then both attempt the write, and the second gets
    `SQLITE_BUSY_SNAPSHOT`, propagated raw. Only one wins, so this is outcome-correct, but the loser's
    reason — `database is locked` in a discarded stream — is not `IndexerBusyError`. `BEGIN IMMEDIATE`
    for `_begin` would make the loser wait out `busy_timeout`, read the winner's row, and raise the
    refusal `lock.acquire` documents. Pre-existing from M21; recorded because M23 made the near-
    simultaneous case ordinary (operator runs `refresh` twice).

11. **[NITPICK] `indexer/main.py::build` loads the encoder before any refusal is decided.**
    `main.py:79-81` — `build_settings` (a ~1 s model load) runs before `lifecycle.refresh` reaches
    `prepare_build`. Foreground, that is the operator's second; detached, it is CPU spent before a
    refusal nobody sees. `await lifecycle.prepare_build(...)` first, then load, then `refresh` (which
    re-checks, as §9 already licenses).

12. **[NITPICK] The module path `detach.py:31-33` says is "spelled once" is spelled again at
    `indexer/main.py:26` (`prog="python -m zikaron.knowledge.indexer"`).** `prog=f"python -m {__package__}"`
    keeps the usage text true through a rename.

13. **[NITPICK] `FINDINGS.md:1276` says "Six test files touched and two added"; the brief lists nine
    touched** (`test_knowledge_lock`, `_lifecycle`, `_reporting`, `_scan`, `_cli`, `_indexer`,
    `_build_invariants`, `test_clock`, `knowledge_fixtures`). Outside the artifact list, noted because
    two documents stating one number is two sites.

### On the four questions the brief asked

- **(a)** Fails under configuration reversion — finding 1. Every other interruption point traced
  (before the drop; drop rolled back mid-transaction; during the walk; during disposal; after
  `_complete` before `_release`) recovers as claimed.
- **(b)** No fourth consumer wants a different predicate. `acquire`, `state.inputs_for_open`,
  `reporting.files_remaining`, `reporting.observe` (for `remove`) and `prepare_build` all want
  *cannot be shown stopped*; `force_release` correctly wants *provably running*; the `lock.live`
  report correctly wants the raw tri-state. The weakness is in the shared probe, not in its
  placement — finding 5.
- **(c)** Holds. `Criteria.bypass` marks every admitted candidate changed and reads nothing in the
  walk phase; the replacement, the three disposals, the per-file `_clear`-then-insert and the
  `meta`/§12 keys are untouched (`ScanCounters.as_meta_rows` carries none of §12's four). One
  consequence worth a sentence in §8.4: under `bypass` the walk phase never reads a file, so a file
  that became binary or over-cap since the last build is deleted by the *index* phase rather than the
  walk phase — same end state, different phase, and a reader of `scan.py:9-15` would expect the walk.
- **(d)** The seam is right: `lifecycle` depends on `reporting` and not the reverse; the two answers
  to "database absent" — `observe` reports, `_open_registered` refuses — sit each on its own side and
  are both correct. `Observed.blocker` is a reporting type carrying a field only `remove` reads, which
  is acknowledged in its docstring and acceptable.

VERDICT: NEEDS_CHANGES

## Round 2 — 2026-09-15

### Summary judgment

The round-1 blocker is genuinely closed, and closed better than the sketch: reading the width at
open and carrying it on `KnowledgeDatabase.vector_width` is the right home (one `sqlite_master`
read per open against a measured 1.3 ms open; every consumer already holds the object; a corpus
whose vector table is gone now fails to open instead of reporting `ok` from `status`), the
regression test reproduces the exact trace, and the absent-database wording is one claim
everywhere I looked. What stops it shipping is the thing the brief predicted about itself: the
four-cause story landed in §8.4, `state.py` and the tests, and **§8.5's normative state table —
forty lines below the rewritten §8.4 block — still enumerates three causes and says "the third
refuses"**. Two further passages in §8.4 and `repair.py`'s module docstring still argue the
recovery from `meta` alone, which round 1 named by line and asked to have restated. Everything
else is improvement- or nitpick-grade, including one exception type that escapes the `error`
reporting the brief claims for it.

### Findings

1. **[BLOCKER] §8.5's state table still says `reindex_required` has three causes, and that "the
   third refuses to serve outright".** `design/knowledge-index.md:1836`: *"three causes (§8.4): no
   database file, no scan yet completed (`meta.last_scan_completed_at` absent), or an encoder
   mismatch. The first two serve as an empty corpus (§7.4) and the third refuses to serve outright
   (§11)"*. §8.4:1726 says four; `state.py:74-78` says four and "the last two refuse"; the table is
   the row a reader of `list`'s output goes to, it is named normative for this milestone ("§8.5's
   state machinery"), and it cites §8.4 as its source while contradicting it. No test parses this
   table (grep of `tests/` for `8.5`, `state table`, `` | `reindex_required` `` finds only a memory-side
   test), which is why it survived. **Change** the row to: *"four causes (§8.4): no database file,
   no scan yet completed (`meta.last_scan_completed_at` absent), an encoder mismatch, or a vector
   table declared at a width `meta` does not name — what an interrupted rebuild leaves. The first
   two serve as an **empty** corpus (§7.4) and the last two **refuse to serve outright** (§11) …"*.
   Then grep the corpus for `the third` and `three causes` before the next round — §11:2167's row
   ("embed model/dim in `meta` ≠ configured") is the other place a reader learns which states
   refuse, and it does not need to change, but a fifth site is the pattern this project keeps
   finding.

2. **[IMPROVEMENT] The recovery argument is still made from `meta` alone in two §8.4 passages and
   in `repair.py`'s module docstring — the three sites round 1 finding 1 named for restatement.**
   - `design/knowledge-index.md:1679-1683`: *"The `reindex_required` variant is immune by
     construction: `meta` still names the old identity, so any later scan begins under the mismatch
     and **is** the repair variant"*. After a configuration revert the encoder agrees with `meta`;
     what the later scan begins under is the **width** disagreement, which this sentence does not
     mention. It is true of the non-revert case and silent about the case the new bullet exists for.
   - `design/knowledge-index.md:1795-1800`: *"Flip at completion additionally makes a crash
     mid-repair self-correcting: `meta` still names the old identity, so the KB keeps refusing, and
     the next scan — beginning under that mismatch — is itself the repair variant"*. Same gap.
   - `zikaron/core/knowledge/repair.py:17-20`: *"It drops unconditionally whenever the identity
     disagrees"* — the code (`rebuilt_identity:74-77`) drops on either of two disagreements, and the
     function docstring below says so; the module docstring names one. And `:21-24`: an interrupted
     KB *"still names the old model, still reports that it needs rebuilding"* — the second clause is
     true only because of the width check the same docstring does not mention.
   **Change**: in both §8.4 passages, after "`meta` still names the old identity", add *"— and the
   table is declared at a width that identity does not name, which is what survives if the
   configuration that caused the rebuild is reverted (the fourth cause below)"*; in `repair.py`
   bullet 3, *"whenever the identity disagrees **or the table's declared width disagrees with it**"*.
   `scan.py`'s `_complete` docstring (`:303-317`) already makes the argument correctly ("the table
   already carries it") and is the wording to match.

3. **[IMPROVEMENT] One of `stored_vector_width`'s two failure paths escapes every caller's `error`
   handling, so "a database that cannot report it fails to open — reported as `error`" is true of
   one path and false of the other.** `database.py:143-163` raises `aiosqlite.DatabaseError` when
   `chunks_vec` is absent and lets `ddl.declared_vector_width`'s `ValueError` (`ddl.py:152-155`)
   propagate when the declaration has no `float[N]`. `KnowledgeDatabase.open`'s own `Raises`
   (`:341-347`) names `aiosqlite.Error` and `ZikaronError` only, and its three callers enumerate
   exactly those: `reporting.observe:312` catches `(aiosqlite.Error, ZikaronError, OSError)`,
   `groups._open_group:293` the same, `scope.execute:122-126` `KnowledgeError`, `ZikaronError`,
   `(aiosqlite.Error, OSError)`. A `ValueError` therefore takes down the whole `list`, `status`
   (traceback) and `search_all` call — the "one bad database taking every other corpus's answer with
   it" that `_open_group`'s comment promises against. Our own DDL never writes such a declaration,
   so this needs a foreign or hand-edited database — but that is precisely the population
   `meta.parse_and_validate` already guards with a `ZikaronError(BAD_CONFIG, source='meta')`, and
   this check sits beside it in `_validate_on_open`. The only test of the path
   (`tests/test_knowledge_repair.py:533-538`) is at the `ddl` level; the "defaulting an unreadable
   declaration" mutation was caught there and would also have been caught at `observe` — but
   `observe`'s behaviour on the *raise* was never asserted. **Change**: in `stored_vector_width`,
   `except ValueError as error: raise ZikaronError(ErrorCode.BAD_CONFIG, source="chunks_vec",
   detail=str(error)) from error` (or whatever `BAD_CONFIG`'s payload shape is in `core/errors.py`);
   list it in `open`'s `Raises`; add to `tests/test_knowledge_groups.py` a sibling of
   `test_a_corpus_whose_vector_table_is_gone_fails_to_open_at_all` that rewrites the declaration
   (`DROP TABLE chunks_vec` then `CREATE VIRTUAL TABLE chunks_vec USING vec0 (chunk_id INTEGER
   PRIMARY KEY, embedding float[…])` is not enough — use a declaration the regex misses, e.g. write
   the `sqlite_master` text via `PRAGMA writable_schema` or create with `FLOAT[16]` if `vec0`
   accepts it) and asserts `group.state is KnowledgeState.ERROR` and that `list_bases` still
   answers for a neighbouring healthy corpus.

4. **[IMPROVEMENT] Round 1 finding 5 was fixed at the named sites and the class has three
   survivors, one of them the normative field definition.** `design/knowledge-index.md:1916-1917`
   defines `lock.live` as *"whether the recorded process is still running"* — the exact reading §6.2
   now spends a paragraph withdrawing; `zikaron/core/knowledge/lifecycle.py:340` (`unlock`'s
   `Raises`): *"the recorded holder is on this host and is still running"*; `zikaron/knowledge/
   main.py:113` (`--force-unlock` help): *"Refuses while the recorded process is running here."*
   **Change**: §8.5 — *"whether a process on that host still answers to the recorded pid (§6.2 on
   what that does and does not establish)"*; `lifecycle.py:340` — *"a process on this host answers
   to the recorded pid"*; the help text — *"Refuses while a process on this host still answers to
   the recorded pid."* Optionally one clause in `lock.is_provably_live`'s docstring (`lock.py:150-159`),
   since its name asserts the thing §6.2 now says a pid cannot prove and `force_release` is the only
   place the qualification lives in code.

5. **[IMPROVEMENT] The reversion of finding 10 is the right call on cost; the reasons recorded for it
   are wrong in two places, and a neighbour contradicts it.** You asked me to challenge it, so
   directly: outcome-correct, loss confined to the wording of an error in a discarded stream, not
   worth an orchestrated test — *keep the reversion*. But:
   - `scan.py:158-160` says closing it *"would mean taking the write lock at `BEGIN` on a primitive
     every other caller shares"*. It would not: `in_one_transaction(db, work, *, failure,
     immediate: bool = False)` changes no existing caller. The recorded reason is a false dichotomy,
     and this project's comment rule is measured reasons.
   - `scan.py:156-158` says *"the realistic collision is already caught earlier, by the check the
     command runs before it spawns anything"*. Two spawns inside one model-load window (~1 s) both
     pass `prepare_build` — `add` followed by `refresh --full` in a setup script is that sequence.
     The outcome is still correct (whichever child wins builds the corpus; a fresh corpus has
     nothing for `--full` to bypass), which is the honest reason to leave it.
   - `lock.acquire`'s docstring (`lock.py:183-185`) says running inside one transaction is what
     prevents *"a window in which two processes both read *no holder*"*. `_begin`'s docstring
     (`scan.py:154-156`) says two builds in one deferred transaction each **can** both read no holder.
     The second is right; what one deferred transaction buys is *one commit*, not *one reader*.
   **Change**: `_begin` — replace the two sentences with *"closing it would mean a `BEGIN IMMEDIATE`
   variant of the shared primitive, verified by a test that holds one acquisition's transaction open
   while the other attempts its own — bought for a better sentence in an outcome that is already
   correct, on a path whose output is discarded"*; `lock.acquire` — *"so that of two acquisitions
   racing the same rows, at most one commits; a deferred `BEGIN` does not stop both reading no
   holder, and the loser's failure is the driver's rather than this refusal (see `scan._begin`)"*.
   If you ever do want the guard, the test is deterministic: connection A runs `BEGIN` + `acquire`
   and does not commit; start B's `_begin` as a task; after B has issued its `SELECT` (or after a
   generous sleep), commit A; await B and assert `IndexerBusyError` — with a deferred `BEGIN` it
   raises `aiosqlite.OperationalError` instead, which is the failing-first oracle.

6. **[IMPROVEMENT] The FINDINGS M23 block does not record the milestone's most consequential
   change and carries two numbers the brief contradicts.** `FINDINGS.md:1276-1282`: *"Twenty
   mutations applied; nineteen caught on the first pass and the survivor closed"* against the
   brief's 26/26; *"2648 passed"* against 2725. Nothing in the block mentions the round-1 blocker
   — that an interrupted rebuild was unrecoverable after a configuration revert — the fourth
   `reindex_required` cause, or `KnowledgeDatabase.vector_width`. A fresh session resuming from this
   file would learn the three-cause design and a test count the tree does not produce. The block is
   correctly still "IN PROGRESS"; what it says about the work is what is stale. **Change**: update
   both counts, and add one paragraph under the decisions list stating the width cause, why it is
   read rather than recorded, and where it lives — the §8.4 bullet at `:1755-1767` is already the
   right length to condense.

7. **[NITPICK] Three wording slips in the rewritten §8.4 block.** `:1748` *"The drop described
   below applies"* — the drop is described **above** (`:1696-1719`). `:1729` *"The fourth, an absent
   database"* — it is the **first** bullet in the list that follows and the first in `state.py:74-75`;
   say "the absent-database cause". And "repair variant" now carries two senses: at `:1681` and
   `:1797` it is the drop-and-rebuild scan; at `:1727` it is any scan begun under a scannable cause,
   including the never-built one that takes no drop. Suggest `:1727` reads *"is the scan that
   repairs it, however it was invoked"*.

8. **[NITPICK] A test docstring attributes the interrupted-window refusal to the mechanism its own
   fixture does not exercise.** `tests/test_knowledge_repair.py:340-342`: *"`meta` still names the
   old model, so the knowledge base goes on refusing to serve"* — but configuration is left at the
   default, which equals `meta`, so the `REINDEX_REQUIRED` asserted at `:360` comes from
   `width_mismatch`, not from any encoder mismatch. That is fine as a test (it is now the
   revert-shaped state), but the docstring describes the other path. Also, the brief's "the two you
   named now assert `state`" is half true: `tests/test_knowledge_build_invariants.py:428-453`
   asserts `vector_width`, which is the right assertion for invariant 7, and not `state`.

9. **[NITPICK] Two other sites of the cause count now carry a wrong ordinal or a superseded
   number.** `design/build-plan.md:1667` (§M22, the owed obligation): *"a fourth `reindex_required`
   cause — a recorded version older than the supported one"* — that cause, when built, is now a
   fifth; `:1679` repeats the obligation without the ordinal, so drop it from `:1667`.
   `FINDINGS.md:457`: *"`reindex_required` has three causes, not two"* — an M20 decision record, so
   it stays, but per withdraw-in-place it wants a bracketed *"(four as of M23— the width cause)"*
   so an always-loaded file does not state two counts.

10. **[NITPICK] Finding 11's ordering — refusal before the encoder load — is asserted by nothing.**
    `indexer/main.py:88-91` calls `prepare_build` first, and both refusal tests in
    `tests/test_knowledge_indexer.py:86-99` drive the real command in the `integration` tier, where
    a swapped order merely makes them slower. One hermetic test: monkeypatch
    `zikaron.knowledge.indexer.main.build_settings` to raise `AssertionError("loaded before the
    refusal")`, `await build(store_dir, db, config, name="absent")`, assert
    `UnknownKnowledgeBaseError`.

### On the four questions the brief asked

- **Cascades from round 1's fixes**: yes — findings 1, 2 and 6 are each a site that kept asserting
  the pre-fix world beside a fix, and finding 4 is the class sweep round 1's finding 5 needed.
- **Four-cause story consistent everywhere**: no. §8.5's table (finding 1) and the two §8.4
  recovery passages plus `repair.py`'s module docstring (finding 2). `state.py`, the §8.4 bullets,
  §11, §13 invariant 7, `scan.py`, the tests and `_print_rebuild` all agree.
- **`vector_width` as the home**: right. Reasons checked rather than accepted: the read is one
  `sqlite_master` row per open against the measured 1.32 ms open, so `list` over N corpora pays
  N negligible reads; `create` passing `identity.embed_dim` is safe because the same method issues
  `chunks_vec_statement(identity.embed_dim)`; failing at open converts a corpus with no vector table
  from a `status` of `ok` (nothing read `chunks_vec` before) into `error`, which
  `test_a_corpus_whose_vector_table_is_gone_fails_to_open_at_all` pins. The one reservation is
  finding 3: the `ValueError` path is outside the contract every caller was written against.
- **Reversion of finding 10**: right call; wrong reasons on the record — finding 5.

VERDICT: NEEDS_CHANGES

## Round 3 — 2026-09-15

### Summary judgment

Every round-2 finding is closed as described, and closed carefully: the four-cause story is now one
story in §8.4, §8.5, `state.py`, the tests, the build plan and FINDINGS; the width read is
`aiosqlite.Error` at the boundary with a real two-corpus test behind it; and the pid qualification
is present at every site round 2 named. What stops it shipping is that the round-1 blocker's class
has a **second instance the width fix does not reach**, and the round-2 restatements hardened the
prose around it: a model swapped for another of the **same width** — `bge-small-en-v1.5` and
`all-MiniLM-L6-v2` are both 384, and those are the two models this corpus has actually named —
interrupted after its drop and then reverted, leaves a corpus that reports `ok` and answers every
search as *searched, nothing there* over tables the drop emptied, with nothing recording that a
build is owed and nothing scheduling one. The design now says in four places that the table's
declaration is "the one fact that still disagrees"; for this case it does not disagree. One
cascade from round 2's own fixes (finding 2), one guard the round-2 blocker's own row still lacks
(finding 3), and nitpicks.

### Findings

1. **[BLOCKER] An interrupted rebuild to a model of the *same width*, followed by a configuration
   revert, reports `ok` over an emptied corpus and serves it — the round-1 trace with the width
   check unable to see it.** Every step from the code as it stands:
   - configuration says model B / 384 where `meta` says A / 384 (the MiniLM-for-bge swap, or any
     quantised-for-unquantised swap of one family); `refresh` → child:
     `repair.rebuilt_identity(A/384, encoder B/384, stored_width=384)` returns `B/384` on its
     **first** branch (`repair.py:77-78`); `_begin` writes `last_scan_started_at = T1`, the git
     mode and zeroed counters (`scan.py:170-181`) and **nothing else**; `drop_derived(embed_dim=384)`
     recreates `chunks`, `chunks_fts` and `chunks_vec` at `float[384]` and empties `files`
     (`repair.py:104-109`), writing **no `meta` row**; embedding begins; the process is killed;
   - operator reverts to A (the sequence round 1 named: "tried a model, too slow, reverted");
   - `state.inputs_for_open` (`state.py:132-140`): `encoder_mismatch` **False** (A == A),
     `width_mismatch` **False** (384 == 384), `never_built` **False** — `last_scan_completed_at` is
     still the earlier build's `T0`, since the only writer of that key in the package is
     `scan._complete` (`scan.py:325-326`; grep confirms), `indexing` **False**. `resolve` returns
     **`OK`**. `groups._serve` finds `OK` in `_SERVING` (`groups.py:63`, `:318`) and runs
     `search_one` over an empty `chunks` — an empty group with `state: "ok"`, which §7.4 defines as
     *this corpus was searched and had nothing*. `list` shows `state: ok` beside whatever partial
     `files_indexed` the dead scan had reached;
   - this persists until somebody runs `refresh`, and nothing does — §6.2:1035-1036 "there is no
     scheduler in v0". The next `refresh` then heals it: `files` is empty so every candidate is
     changed, A/384 vectors fit `float[384]`, `_complete` writes a fresh instant. So unlike round 1
     this is not a permanent failure; it is the *exact* misinformation §8.4:1793-1795 spends a
     paragraph refusing ("empty groups ... turns §7.4's 'no matches is a real answer' into
     misinformation"), for an unbounded window, silent, and the brief's done-when — "killing that
     repair leaves it still refusing" — is false for it.
   **The width fix cannot see it by construction**: it detects a rebuild by the *physical* change
   the drop made, and a same-width drop makes none. The suite already names the gap without
   following it: `tests/test_knowledge_repair.py:188-190` — *"a model that changed under an index
   is exactly the divergence nothing later could detect"* — and then tests only the un-interrupted
   case. **Sites now asserting the fix is complete**, each of which this trace refutes:
   §8.4:1763-1765 *"The table's own declaration is the one fact that still disagrees"*;
   §8.4:1680-1682 and :1796-1798 (the two round-2 restatements) — true where the width changed,
   silent where it did not; `repair.py:22-27` bullet 4 *"it is that second disagreement ... which
   keeps it reporting that it needs rebuilding even if the configuration that started the rebuild
   is put back"*; `repair.py:59-66` *"Nothing else records that a rebuild was owed"*;
   `state.py:80-88` *"The table's own declaration is the one fact that still disagrees"*;
   `scan.py:50-55` *"The table is the thing that still disagrees"*; `scan.py:315-318`
   (`_complete`); FINDINGS.md:1296-1303.
   **Suggested change — remove a claim the drop has falsified, rather than add state.** In
   `repair.drop_derived._work`, after `files.forget_all(connection)`:
   `await database.clear_meta(connection, (meta.LAST_SCAN_COMPLETED_AT_KEY,))`. The completion
   instant vouches for a corpus that the same transaction has just destroyed, so it is no longer
   true; `_complete` rewrites it, as it already does. This is not the repair checkpoint §8.4
   refuses — no key is added, and it is the design's own "stated as a persisted fact" reasoning
   (§8.4:1743-1745) applied to the fact the drop changed. Consequences, all in the right direction:
   `never_built` holds through any revert, so the corpus reports `reindex_required` and is not in
   `_SERVING`; the next scan builds it — an ordinary scan where the width is unchanged (it fits),
   the width cause's drop-and-rebuild where it is not; and `width_mismatch` **stays**, because
   `never_built` triggers no drop and a widened table still needs one. Then restate the sites
   above, plus `meta.py:117-119` and `:342-346` (absence now means *no completed build's corpus is
   what is stored*, not only *no build has ever completed*) and §8.4's second bullet
   (`:1739-1742`, which gains "and a rebuild interrupted after its drop"). The cause count stays
   four — this case lands in the existing second cause — so finding 3's guard is unaffected.
   **Test**: a sibling of `test_an_interrupted_rebuild_is_repaired_even_if_the_model_is_put_back`
   with `FakeEncoder(model_name="other", dim=FakeEncoder().dim, embed_error=RuntimeError(...))`;
   after the raise assert `_reported_state(corpus) is KnowledgeState.REINDEX_REQUIRED` — **this
   fails today with `OK`**, which is the failing-first oracle — and that `groups.search_all` answers
   the corpus with no results and a non-`ok` state; then `build_index(corpus)`, assert chunks
   non-empty and `OK`. Mutation: delete the `clear_meta` line and watch the state assertion go red.

2. **[IMPROVEMENT] `scan._begin`'s first paragraph still makes the claim round 2 finding 5
   corrected in `lock.acquire`, and its own second paragraph contradicts it.** `scan.py:150-151`:
   *"The lock is read and written together, because doing it in two transactions leaves a window
   in which two processes both read* no holder"* — then `:154-155`: *"Two builds that begin at the
   very same moment can both read* no holder*, and only one of them commits"*. The first sentence
   names the window one transaction does **not** close; what two transactions would additionally
   allow is both *committing*. This is the cascade the brief asked about: the fix landed in
   `lock.acquire:194-199` and in `_begin`'s second paragraph, and the sentence above them kept the
   pre-fix reading. **Change** `:150-151` to: *"The lock is read and written in one transaction,
   because in two of them both of two racing acquisitions could commit; one transaction lets at
   most one."*

3. **[IMPROVEMENT] The §8.5 state table — the row that carried round 2's blocker — is still pinned
   by no test, and the project has the parser.** `grep` of `tests/` for the table finds only a
   memory-side test (`test_retrieval_eligibility.py:152`). `tests/design_tables.table_with_columns`
   already parses this document's tables (`test_knowledge_ddl.py`, `test_knowledge_counters.py`).
   **Change**: one test in `tests/test_knowledge_state.py` over
   `table_with_columns(document, "8.5 ...", ("`state`", "meaning"))` asserting (i) the `state`
   cells equal `{s.value for s in KnowledgeState}`; (ii) the five names in the *"Precedence,
   top-down:"* sentence (`:1842`) equal `[s.value for s in PRECEDENCE]`; (iii) the cardinal word
   before "causes" in the `reindex_required` row, mapped through a small word→int table, equals
   `sum(1 for s in _ALONE.values() if s is KnowledgeState.REINDEX_REQUIRED)` — which is 4, and
   which is exactly the number that drifted. Cheap, and (iii) is the mechanical version of the
   count-first discipline FINDINGS prescribes for this class.

4. **[NITPICK] "Provably / demonstrably wrong" residue, where the correct statement sits
   adjacent.** The qualification is now everywhere it needs to be; these are the headline
   sentences that still claim the thing the next paragraph says a pid cannot establish:
   §6.2:1086 (*"the one where it is demonstrably wrong"* — seven lines **after** `:1070-1079`
   withdraws exactly that); `lock.py:20` (*"a holder that is provably there"*); `lock.py:166`
   (*"where the holder is demonstrably there"* — inside `is_provably_live`, five lines below its own
   clause saying it proves a process and not a holder); `lock.py:233` and `:242`
   (`force_release`'s first two paragraphs); `lifecycle.py:323`; `tests/test_knowledge_lock.py:241-242`.
   §6.2:1065-1066 is fine as written, since `:1070` explicitly says it is being kept and qualified.
   One wording for the rest: *"the one case the evidence contradicts — a process on this host
   answers to the recorded pid"*.

5. **[NITPICK] §11 has no row for the interrupted-rebuild degraded mode, though §8.5 cites §11 for
   it.** §8.5:1838 says *"the last two refuse to serve outright (§11)"*; §11:2171 covers the encoder
   mismatch and no row covers a table left at a width `meta` does not name — the milestone's own
   headline degraded mode, in the section the brief names normative "in full". Round 2 said this
   row need not change, and that was right for the *encoder* row; what is missing is a sibling:
   *"rebuild interrupted after its drop | refuses to serve and reports `reindex_required`; the next
   build repairs it whole (§8.4)"* — worded to cover finding 1's case as well once fixed. Optionally
   `groups.py:60-62` (`_SERVING`'s comment names two of the four causes; say "any `reindex_required`
   cause").

6. **[NITPICK] FINDINGS M23 block: two counts the brief itself supersedes, one pid-identity
   survivor, and one stale §16 count.** `:1279-1281` still read *26 / 26* and *2725 passed* against
   the brief's 28 / 2730, and *"six more aimed at the fixes"* is now eight. `:1344-1345` *"`status`
   shows the lock's holder and whether **that process** is still alive"* is the reading the
   milestone spent two rounds withdrawing, in the always-loaded file with no qualification beside
   it — *"whether a process on this host still answers to the recorded pid"*. And `:284` *"11 §16
   items of which one is closed ... leaving 10 open"*: §16 now has **13** items (M22 added 12, this
   milestone added 13), of which **three** are closed (2, 9, 11); "10 open" survives by coincidence.

7. **[NITPICK] Two small test gaps against §6.2 and `rebuilt_identity`.** (a)
   `tests/test_knowledge_cli.py:551-560` (`test_no_lock_at_all_is_reported_rather_than_refused`)
   does not take the `started` fixture, so §6.2:1084's *"it says so **and refreshes**"* is pinned
   for the foreign-lock case only; add it and assert
   `started == [_Started(name="docs", project=project, full=False)]`. (b) `rebuilt_identity`'s
   branch order is load-bearing — when both disagree the table must be declared at the width the
   **encoder** emits, or the first insert fails — and swapping the two `if`s survives every unit test
   in `TestWhenARebuildIsDue` (each passes a `stored_width` that makes the other branch moot); it is
   caught only end-to-end by `..._and_the_next_build_completes_it`. A unit test with
   `FakeEncoder(model_name="other", dim=_OTHER_DIM)` and `stored_width=_OTHER_DIM + 1` asserting
   `rebuilt.embed_dim == _OTHER_DIM` names the reason where the rule lives.

### On the three questions the brief asked

- **(a) Cascades from round 2's fixes**: one — finding 2, where round 2 finding 5's correction
  reached `lock.acquire` and `_begin`'s second paragraph and not the sentence above them. Finding 1
  is **not** a cascade; it is the round-1 blocker's class with an instance the fix could never
  reach, and round 2's finding 2 (mine) asked for the recovery argument to be restated *around the
  width*, which is what hardened the over-claim. Everything else from round 2 was checked in the
  current text and holds: the §8.5 row, `:1748` / `:1729` / `:1727`, `stored_vector_width`'s one
  exception type and `open`'s `Raises`, the three-spelling tolerance with its test, `unlock`'s
  `Raises`, the `--force-unlock` help, the `probe` / `is_provably_live` clauses, `_begin`'s recorded
  reasons, `lock.acquire`'s one-commit wording, build-plan `:1667`, FINDINGS `:458`, and the
  `build_settings` ordering test (`TestWhatIsDecidedBeforeTheModelLoads`, in the gate).
- **(b) One story everywhere**: the four causes, yes — §8.4, §8.5, `state.py`, `_ALONE`, the build
  plan and FINDINGS agree, and no enumeration at three survives outside `FINDINGS.md:457`'s
  bracketed record. The **recovery** claim built on them is over-stated at the sites finding 1
  lists. The pid story: qualification present at every consequential site; residue in findings 4
  and 6.
- **(c) Prose pinned by no test**: findings 3 and 7. Checked and pinned: search during a build at
  the search layer (`TestACorpusBeingBuilt`, which the `_SERVING` mutation now trips); the root
  refused before the lock is taken (`test_knowledge_scan.py:525-527`); all four foreground refusals
  in both `TestWhatHasToHoldBeforeABuildStarts` and the CLI with `started == []`; `--force-unlock`
  refusing a live local build and starting nothing (`cli:539-549`); the three `_lock_line` branches;
  `detach.spawn`'s session, streams and argv (`test_knowledge_detach.py`) plus a real `SIGKILL`
  mid-build (`TestAsARealProcess`); the unreadable declaration at both `search_all` and `list_bases`.
- **Checked and deliberately not raised**: the rebuild decision is taken on the open-time snapshot
  (`scan.py:369-370`) before `_begin` takes the lock (`:379`). A second build with a *different*
  encoder completing inside that window — `rebuilt_identity`, one `is_dir`, one git subprocess —
  leaves the later build either redoing a rebuild or dying on its first insert with the lock
  released and an honest state. Bounded the way round 2 finding 5 bounded the both-read-no-holder
  race, and not worth a guard.

VERDICT: NEEDS_CHANGES

## Round 4 — 2026-09-15

### Summary judgment

Every round-3 finding is closed as described, the §8.5 table is now pinned mechanically, the
width/instant division of labour is stated the same way at every site I read, and the answer to
the brief's first question is **yes, the division as written is true of the code**: I traced every
writer of `chunks_vec`'s declaration, of `meta.embed_dim` and of `last_scan_completed_at`, plus the
pre-lock race, and no sequence of this package's own operations leaves the width disagreeing with
`meta` while the instant is present. What stops it shipping is the claim built *on top of* that
division, which rounds 3 and 4 have both now stated in the design and the code: that a corpus
reporting `never_built` with nothing compared disagreeing is repaired by "an ordinary scan". It is
not. An ordinary scan **resumes** — that is what §6.4 makes it do — and after a same-width rebuild
that committed files before it was killed and was then reverted, the files it resumes over carry the
*other* model's vectors under a content hash that says they are current. The scan clears them as
unchanged, completes, and leaves `meta` naming a model that did not produce them, with `state: ok`
and no mechanism that could ever notice. That is invariant 7 violated silently, on the modal revert
scenario rather than an edge of it, and the round-3 suggestion — mine — is where the over-claim
entered. One genuine cascade from round 3's fix (finding 2) and small things otherwise.

### Findings

1. **[BLOCKER] A same-width rebuild interrupted after committing files, then reverted, is resumed
   by the next ordinary scan over vectors the recorded model did not produce — invariant 7 is
   violated with `state: ok`, and nothing can detect it afterwards.** Every step from the code as
   it stands:
   - `meta` A/384, corpus built. Configuration → B/384 (the MiniLM-for-bge swap the round-3 test
     names). `refresh` → child: `repair.rebuilt_identity(A/384, B/384, 384)` → B/384
     (`repair.py:84-85`); `_begin`; `drop_derived(384)` — table redeclared at the same width,
     `files` emptied, instant cleared (`repair.py:122-126`); walk phase lists every file as changed
     (`changes.py:130`, no row); `disposal.run` commits `a.md` with **B's** vectors and a `files`
     row carrying `content_hash(a.md)` (`disposal.py:157-171`); the process is killed on `b.md`.
   - State now: `meta` A/384, table 384, instant absent, `files = {a.md}` (B-vectored),
     `pending = [b.md, …]`. `never_built` → `reindex_required`. Correct so far, and this is as far
     as `test_an_interrupted_rebuild_to_the_same_width_is_caught_too` looks — its encoder dies on
     the **first** embed (`embed_error`), so zero files are committed and the resume below cannot
     happen in that test.
   - Operator reverts to A (the "tried a model, too slow, reverted" sequence rounds 1 and 3 were
     built on — and "too slow" is learned *during* the build, i.e. after files have committed, so
     this is the ordinary shape of the revert rather than a corner of it). Next `refresh`:
     `rebuilt_identity(A/384, A/384, 384)` → `None` (`repair.py:84-88`). **No drop.** Walk phase:
     `files.load_all` → `{a.md}`; `changes.compare` → `_classify` → `content_hash(raw) ==
     row.content_hash` → `keep` (`changes.py:168-173`). `b.md`, `c.md` embedded with A.
     `_complete(db, None)` writes the instant (`scan.py:337-345`). `meta` still A/384. `state` →
     `OK`; `_SERVING` admits it; `a.md`'s chunk answers every query with a cosine between an
     A-query and a B-vector.
   The design says the opposite in five normative places and the code in three:
   `design/knowledge-index.md:1682-1686` (*"immune by construction … any later scan begins under a
   disagreement and **is** the scan that repairs it, whole"* — nothing compared disagrees here, and
   it is not whole), `:1743-1748` (*"an ordinary scan builds it, resuming under §6.4"* — the
   resuming is the defect), `:1786` (*"an ordinary scan fills it"*), `:1827-1829` (*"Its upfront
   drop removes the crashed run's partial work, so recovery is a **redo of the corpus, not a resume
   of the remainder**"* — there is no upfront drop on this path), `:2202` (§11: *"The next build
   repairs it whole"*); `repair.py:17-21` (*"drops unconditionally … including on the scan that
   follows a crashed rebuild. That is what makes recovery a redo"*), `repair.py:69-73` (*"an
   ordinary scan rebuilds it without any of this having to notice"*), `scan.py:57-61`. The
   done-when *"killing that repair leaves it still refusing and the next scan completes it"*
   (`build-plan.md:1722`) is met in letter — the state reaches `ok` — and failed in substance.
   **Two fixes, and I recommend the first.**
   **(d) Write the rebuild-to identity at the drop, in the drop's transaction.** `drop_derived`
   takes the `KnowledgeMeta` rather than a width, and `_work` adds
   `await database.write_meta(connection, identity_rows(identity))`; `_complete` writes the instant
   only. Then `meta.embed_model`/`embed_dim` describe the vectors in the table **always**: the same
   transaction empties the table, declares its width and names the encoder that will fill it, and
   every later insert on this system's paths comes from `Disposals.corpus = rebuilt` with
   `build.encoder`. Trace the blocker's scenario under it: after the kill, `meta` = B/384; revert →
   `encoder_mismatch` (B ≠ config A) reports `reindex_required`, and `rebuilt_identity(B/384,
   A/384, 384)` → A/384 on its first branch → drop → redo with A. Without the revert (config stays
   B): `rebuilt_identity(B, B, 384)` → `None` → an ordinary scan *resumes* over `a.md` — **correctly**,
   because `a.md` is B-vectored — which is cheaper than today's redo and is §6.4 working as
   designed. The different-width interrupted-then-reverted case: `meta` B/16, table 16, revert →
   `rebuilt_identity(B/16, A/384, 16)` → A/384 → drop at 384 → redo. `width_mismatch` and
   `rebuilt_identity`'s second branch become *purely* the tamper backstop the current prose already
   calls them, since `meta.embed_dim` and the declaration are then written together in every
   transaction that writes either. **Invariant 7's exception clause (`:2253-2256`) can be
   withdrawn** rather than weakened. The one stated reason the design gives for rejecting this —
   `:1819-1822`, *"Flip at drop and §11's refusal clears the instant the drop commits, so the KB
   serves throughout the rebuild"* — is no longer true: since round 3, `never_built` keeps the
   corpus out of `_SERVING` for the whole rebuild whatever the identity says (finding 2). Cost: a
   design reversal on §8.4's flip-moment paragraphs, `repair.py` bullets 3–4, `scan._complete`'s
   docstring, `state.resolve`'s second paragraph, invariant 7, `_print_rebuild`'s docstring
   (`indexer/main.py:137-139`), `build-plan.md:1711`, FINDINGS `:1268-1270` and `:1291-1300`, and
   two tests that assert `meta == recorded` after an interruption (`test_knowledge_repair.py:395`,
   `test_knowledge_build_invariants.py:448` — the second becomes *"an unfinished rebuild has already
   recorded what is filling it, and holds no vector from the old identity"*). Count those sites
   before editing and reconcile the count after.
   **(i) The smaller change: treat `never_built` as a rebuild trigger.** In `scan.run`, after
   `rebuilt` is computed: `if rebuilt is None and state.never_built(raw): rebuilt = recorded`.
   One line, no design reversal — but it costs §6.4's resume for exactly the build where it
   matters most: a *first* build over a large corpus that crashes at file 4,900 of 5,000 redoes
   from zero, because the first build's crash is also a `never_built` state. I would not accept
   that trade when (d) removes an invariant exception instead of adding a redo.
   **Test, failing first today, whichever fix is chosen** — a sibling of the same-width test that
   commits one file before dying, via the `disposal.dispose` monkeypatch
   `test_knowledge_scan.py:479-490` already uses:
   ```python
   other = FakeEncoder(model_name="another-model-of-the-same-width", dim=FakeEncoder().dim)
   # monkeypatch disposal.dispose: real on the first call, raise RuntimeError on the second
   with pytest.raises(RuntimeError):
       await build_index(corpus, encoder=other)
   async with open_index(corpus) as opened:
       assert set(await files.load_all(opened.connection)) == {"a.md"}, "one file committed by `other`"
   reverted = FakeEncoder()  # the revert: the identity `meta` names
   await build_index(corpus, encoder=reverted)
   assert any("a.md" in text for batch in reverted.embedded for text in batch), (
       "a.md's vectors were made by the other model and were never redone"
   )
   ```
   Use the encoder's `embedded` log (or `_indexed_at` moving) as the oracle, **not** the stored
   vector values: `FakeEncoder.vector_for` seeds from the text alone (`tests/fake_encoder.py:98-106`),
   so A and B produce byte-identical vectors for one chunk and a value comparison would pass
   vacuously — which is also why the invariant-7 tests could not have seen this. Mutation for (d):
   drop the `write_meta` from `_work`; for (i): delete the added line. Then sweep the sites above
   plus `tests/test_knowledge_repair.py:9-15` (module docstring) and `:447-453`.

2. **[IMPROVEMENT] Round 3's fix falsified the design's argument against flip-at-drop, and the
   passage kept the pre-fix world — the cascade the brief asked about, one instance.**
   `design/knowledge-index.md:1819-1822`: *"it is the safer of the two moments, and the difference
   is observable. **Flip at drop** and §11's refusal clears the instant the drop commits, so the KB
   *serves* throughout the rebuild: empty groups filling in over minutes"*. Since the drop clears
   `last_scan_completed_at`, `never_built` is true for the entire rebuild and `groups._serve`
   (`groups.py:320`, `_SERVING`) never searches it, whichever identity `meta` names. The
   observable difference the paragraph rests on is gone, and `:1823` (*"Flip at completion
   additionally makes a crash mid-repair self-correcting"*) now credits the flip moment for a
   property the cleared instant supplies. Whether or not finding 1 takes option (d), this paragraph
   must be restated: either *"flip at drop was rejected when nothing else gated serving; the
   cleared instant now does, and the moment is chosen for [the reason that survives]"*, or — under
   (d) — withdrawn in place with the round-3 change named as what removed its premise. Neighbours
   to read with it: `:1797-1799` (*"Until then §11's mismatch stands and the KB keeps refusing to
   serve"* — it is the instant that keeps it refusing, not the mismatch) and `scan.py:319-323`
   (`_complete`: *"Written at the drop instead, the knowledge base would start serving the moment
   the old vectors were destroyed"* — false for the same reason).

3. **[IMPROVEMENT] The rebuild decision is taken on the open-time snapshot before the lock, and
   under finding 1's fix that window becomes the only route left to a wrong-model vector under a
   right-looking `meta`.** Round 3 checked this and called it bounded, and for the different-width
   case it still is (the loser dies on its first insert). Same width: build A (encoder A, snapshot
   `meta` A → `rebuilt None`) and build B (encoder B/384) overlap by one `is_dir` and one git
   subprocess; B takes the lock, drops, completes with `meta` B; A then takes the lock, runs an
   ordinary scan, finds one changed file and inserts an **A** vector into a corpus labelled B —
   invariant 7, `state: ok`, the same class as finding 1 by a rarer door. Not re-litigating round 3's
   "not worth a guard" on its own terms; raising it because option (d)'s claim — *invariant 7 holds
   without exception on the system's own paths* — is only literally true if the decision is taken on
   locked state, and the change is nearly free in the function being rewritten anyway:
   `lock.acquire` already reads `meta` inside `_begin`'s transaction (`lock.py:208`); have `_begin`
   return that mapping plus `await database.stored_vector_width(connection)`, and compute
   `rebuilt_identity(meta.parse_and_validate(raw), build.encoder, stored_width=width)` from those
   rather than from `opened.meta` / `opened.vector_width` (`scan.py:381-382`). The `is_dir` and git
   probe can stay before the lock — they do not depend on `meta`'s identity keys. If declined, say so
   in `scan.run`'s comment at `:377-380` with the same-width race named, since the current comment
   describes only the different-encoder case.

4. **[NITPICK] The one-transaction claim about the cleared instant is asserted by no test, and the
   existing rollback test cannot see it.** `test_a_failure_part_way_through_leaves_the_old_index_whole`
   (`test_knowledge_repair.py:318-342`) appends the failing statement to the DDL list, so
   `forget_all` and `clear_meta` never run in that test and the instant survives whether or not the
   clear is in the transaction; it also asserts nothing about the instant. §3.2:297-300, §8.4:1784
   and `repair.py:106-115` all say *"in the same transaction"*. One test pins it in the direction
   that matters: monkeypatch `files.forget_all` to raise, `pytest.raises(RuntimeError)` around
   `drop_derived`, then assert chunks and widths unchanged **and**
   `meta.LAST_SCAN_COMPLETED_AT_KEY in await database.read_meta(opened.connection)`. Also add the
   instant assertion to the existing test, since it is the one named for the rollback.

5. **[NITPICK] `state.inputs_for_open`'s docstring states a universal that three of its own
   inputs falsify.** `state.py:141-143`: *"`width_mismatch` … is the one input here that a
   configuration change can neither create nor clear"*. `never_built`, `root_missing` and
   `indexing` are equally indifferent to configuration; only `encoder_mismatch` reads it. Suggest:
   *"Unlike `encoder_mismatch`, it compares the table against `meta` rather than against
   configuration, so a configuration change can neither create nor clear it: it reports the state
   of the stored table rather than an opinion about it."*

6. **[NITPICK] Two enumeration slips in the rewritten §8.5 and §9 passages.**
   `design/knowledge-index.md:1984-1986`: *"absent where the crashed scan was a rebuild, whose drop
   clears that key"* — also absent where **no scan had ever completed** (a first-scan crash),
   which is the older and commoner case; say *"absent where no scan had yet completed or where the
   crashed scan was a rebuild"*. And `:2128-2130` lists four foreground refusals; `prepare_build`
   opens the database (`lifecycle.py:308`), so a database that is present and will not open is
   refused in the foreground too — as `scope.execute`'s `failed:` (`scope.py:126-130`) rather than
   `refused:`, which is worth one clause: *"and a database that will not open, reported as a
   failure rather than a refusal"*. The universal in that sentence holds; only its list is short.

### On the three questions the brief asked

- **(1) Is the width/instant division true of the code?** Yes, exactly as stated. `chunks_vec`'s
  declaration is written by `create` (at `identity.embed_dim`, which is also what `meta` is seeded
  with) and by `drop_derived` (at `rebuilt.embed_dim`, in the transaction that clears the instant);
  `meta.embed_dim` is written by `create` and by `_complete` (`identity_rows(rebuilt)`, the same
  `rebuilt` whose width the drop declared, in the transaction that writes the instant). Every
  interleaving of two builds I traced — opposite encoders in either order, both rebuilding, one
  dying after its drop — ends with the width and `meta.embed_dim` agreeing wherever the instant is
  present. The state cause is the backstop the prose says it is. **What is not true is the sentence
  that follows it everywhere**: that `never_built` with nothing disagreeing is repaired by an
  ordinary scan. An ordinary scan resumes, and resume is wrong whenever the committed rows were
  made by the identity the drop was rebuilding *to* — finding 1. The division is right; the
  conclusion drawn from it is wrong in a direction neither round 3 nor its suggested fix looked in.
- **(2) Did restating the division create a fourth cascade?** One, and it is structural rather
  than a stale sentence: the flip-at-drop rejection (`:1819-1822`) and its two neighbours
  (finding 2), which round 3's `clear_meta` falsified and the restatement did not reach. Every
  other site the brief listed — `state.py`'s two field comments, `resolve`, `inputs_for_open`
  (modulo finding 5), `scan.py`'s module docstring, `repair.py` bullet 4, §8.4's fourth-cause bullet
  and the same-width paragraph, §3.2's "can also go absent again", §8.5's skip paragraph (modulo
  finding 6), `groups._SERVING`'s comment, the test docstrings — reads consistently with its
  neighbours on the *reporting* claim. The override of my round-2 §8.5 wording is correct and I
  accept it: `_SERVING` gates all four causes identically, and "the last two refuse outright"
  implied a behaviour the code does not have.
- **(3) Anything in §6.1–§6.4, §8.4, §8.5, §11 or §9's `--force-unlock` the code contradicts?**
  §8.4:1682-1688, :1743-1748, :1786, :1827-1829 and §11:2202 — finding 1. §8.4:1819-1823 —
  finding 2. Checked and holding: §6.2's two `--force-unlock` details against `_refresh`
  (`main.py:193-201`: unlock, then `prepare_build`, then spawn; a live local holder raises before
  either); §6.3's per-file progress and `state: "indexing"` with `files_remaining` through
  `_serve`; §6.4; §8.4's `remove` refusal on `running_holder`; §8.5's `files_remaining` rule
  (`reporting.py:228-234`), precedence sentence and cause count (now pinned), `lock` fields
  including `live: None` for a foreign host; §9's foreground-refusal set against `prepare_build`
  (modulo finding 6); §11's absent-database, unreadable, orphan, `registry_unavailable`,
  `root_missing` and reclaim rows. The §16 count in FINDINGS (13 items, three closed: 2, 9, 11)
  agrees with the document.

VERDICT: NEEDS_CHANGES

## Round 5 — 2026-09-16

### Summary judgment

Option (d) is implemented as described and the code is now right: `drop_derived` writes the
identity, clears the instant, declares the table and empties `files` in one `_work`; `_begin` reads
`meta` and the width under the lock it just took; `_complete` writes the instant alone; and the two
encoder-log tests plus the pre-lock-snapshot test are sound oracles that I checked against the
mutations the brief names. **The answer to the brief's first question is yes** — I traced every
file state it asked about and found no case where keeping a dead rebuild's rows is wrong (detail
below). What stops it shipping is the fifth cascade the brief asked about, and it is exactly the
class this corpus predicts: the sweep grepped the *mechanism* claim ("the identity is written at
completion") and not its *consequence* ("a revert makes the encoder agree with `meta` again, so
nothing compared disagrees"). Under (d) a revert does the opposite — `meta` names the abandoned
model, so the reverted encoder is an encoder mismatch — and the old consequence survives in the
normative §8.4 paragraph sixty lines above the paragraph that says so, in `state.resolve`'s
docstring, and in four docstrings of the test file for the mechanism. `database.py` also still says
the width and the identity are written in different transactions "on purpose". Prose only, no
behaviour defect anywhere I read; but §8.4 now contradicts itself on what the next scan does after a
revert, which is the repair rule this milestone exists to state.

### Findings

1. **[BLOCKER] The normative §8.4 says that after a revert "the identity agrees again … nothing
   compared disagrees … an ordinary scan fills it"; the code, the tests and §8.4 itself sixty lines
   later say a revert is an encoder mismatch that takes the drop and redoes the corpus.** Under (d)
   the drop writes `identity_rows(rebuilt)` (`repair.py:145`), so after a kill `meta` names the
   model the dead run was writing. Reverting configuration then makes `encoder_matches_config`
   false (`state.py:150`) and `rebuilt_identity`'s **first** branch fire (`repair.py:95-96`); the
   next scan drops and redoes. `test_a_rebuild_that_committed_files_before_dying_leaves_no_vector_it_does_not_name`
   asserts exactly this, and §8.4:1847-1852 states it correctly. The following still state the
   round-3 world, in which the identity was written at completion and a revert restored agreement:
   - `design/knowledge-index.md:1788-1799` — *"interrupt the rebuild after its drop, and revert: the
     identity agrees again and the declaration never moved, so nothing compared disagrees … an
     ordinary scan fills it — safely, because the same transaction recorded the model that is
     filling it."* Three false clauses: the identity does not agree, the next scan is not ordinary,
     and the "safely" argument (the rows were made by the model `meta` names) is the argument for
     the *seen-through* case, not the revert. Read from here, an implementer expects a resume over
     rows the abandoned model made — the invariant-7 violation round 4 was about.
   - `zikaron/core/knowledge/state.py:83-91` — *"caught by `never_built` alone, and nothing else could
     catch it … every comparison this module makes is quiet — the encoder agrees, the width agrees
     … That covers the case an operator produces by trying a model and reverting."* Where the
     operator reverts, `encoder_mismatch` fires too; "alone" and "nothing else could" are true only
     of the seen-through case, which the paragraph then does not name.
   - `tests/test_knowledge_repair.py:9-15` (module docstring) — *"reverts makes the obvious trace
     vanish: the encoder agrees with `meta` again."* It disagrees.
   - `:209-212` (`TestWhenARebuildIsDue` class docstring) — *"reverts leaves a widened table and an
     encoder that agrees with `meta` again."* Under (d) the table and `meta` move together, so a
     revert leaves an encoder that disagrees with both.
   - `:242-243` (`test_a_table_left_at_another_width_asks_for_one_even_with_nothing_else_wrong`) —
     *"What an interrupted rebuild leaves once the configuration that caused it is reverted: the
     encoder agrees with `meta` again, and the table is the only thing that does not."* No
     interrupted rebuild produces this state any more; `rebuilt_identity`'s own docstring (`:71-78`)
     and §8.4:1777-1786 say it is reachable only from outside the system.
   - `:479-486` and `:496` (`test_an_interrupted_rebuild_is_repaired_even_if_the_model_is_put_back`) —
     *"the operator reverts — so the encoder agrees with `meta` again and the comparison that started
     the rebuild has nothing left to say"* and *"back to the encoder `meta` still names"*. In that
     test, after the kill `meta` names `other`/16; the default encoder is a mismatch, and the
     comparison that started the rebuild is the one that fires. The test passes for a reason its
     docstring rules out.
   **Suggested change.** One statement of the consequence, everywhere: *after a kill `meta` names
   the model the dead run was writing; if configuration is left naming it the next scan resumes
   under `never_built` alone; if configuration is reverted the abandoned identity is an encoder
   mismatch, `rebuilt_identity`'s first branch fires, and the next scan drops and redoes.* For
   §8.4:1788-1799 recast the scenario as the seen-through one — *"interrupt the rebuild after its
   drop, and leave configuration naming the new model, as an operator seeing the swap through would:
   `meta` names it too, because the drop recorded it, and the declaration never moved, so nothing
   compared disagrees — over tables the drop emptied. What covers it is that the drop clears
   `last_scan_completed_at` … and an ordinary scan resumes it, safely, because the same transaction
   recorded the model that is filling it. Reverting instead makes the abandoned identity an encoder
   mismatch, which takes the drop (below)."* For `state.py:83-91`: *"A rebuild interrupted and seen
   through is caught by `never_built` alone … Where the operator reverts instead, `encoder_mismatch`
   fires as well, since `meta` names the abandoned model, and the repair is the drop."* Rewrite the
   four test docstrings and the `:496` comment to the same statement; `:242-243` should say the
   state is the tamper case (restored file, hand-edited row). Then grep the corpus for
   `agrees with .meta. again`, `nothing compared disagrees`, `nothing left to say`, `trace vanish`,
   `widened table` and reconcile the count against the seven line ranges above before the next
   round — those are the phrasings this round found; the claim may have more.

2. **[IMPROVEMENT] `database.py` still says the width and the identity are written in different
   transactions "on purpose", and that the width is "the only evidence" of an interrupted rebuild —
   the round-1 design, contradicted by `repair.py:71-73`, `state.py:93-96` and §8.4:1806.**
   `zikaron/core/knowledge/database.py:146-149` (`stored_vector_width`): *"`meta` is not evidence of
   it: the two are written by different transactions on purpose, so a rebuild interrupted between
   them leaves a table at one width and a record naming another."* And `:208-213`
   (`KnowledgeDatabase` class docstring): *"the two are allowed to disagree — that disagreement is
   precisely what an interrupted rebuild leaves behind, and it is the only evidence of it, since the
   drop that widens the table and the write that records the new identity are deliberately not the
   same transaction."* Both false on three counts under (d): one transaction writes both
   (`repair.py:141-146`); an interrupted rebuild leaves them *agreeing*; and the instant, not the
   width, is what reports one (round 3). This module is where a reader goes for what
   `vector_width` means, and it was not in the brief's sweep list. **Change** `:146-149` to: *"Read
   off the table's own recorded declaration, because `vec0` will not answer for it any other way. On
   this system's paths the width and `meta.embed_dim` are written in one transaction and agree; the
   read exists for a database whose `meta` and tables were joined from different builds — restored
   from a backup, or edited by hand — where every later build would otherwise die on its first
   insert."* And `:208-213`: *"`vector_width` is read from the table rather than from `meta`, and where
   the two disagree the table decides what a build may insert. Nothing this package does separates
   them — the drop writes both in one transaction — so a disagreement means a `meta` and a table
   from different builds, which `state` reports and `repair.rebuilt_identity` declares back. Carried
   here so that …"*

3. **[IMPROVEMENT] Four §8.4 passages still argue from the completion-time rewrite, and one names the
   wrong identity as what the drop records.** None changes the rule; each gives a reason the code no
   longer supports, and two contradict a sentence within fifty lines.
   - `:1689-1690` — *"(The operative cause is the state, not the drop — a drop without the state
     trigger would leave a rebuilt corpus behind a KB refusing forever, because nothing would rewrite
     `meta`.)"* The drop is now what rewrites `meta`. The argument for a state trigger under (d) is
     different and still real: *a drop bound to `full=true` alone would let a plain `refresh` under
     a reverted configuration run as an ordinary scan and insert the reverted model's vectors into a
     corpus `meta` labels with the abandoned one, since nothing would ask `rebuilt_identity`.*
   - `:1820-1827` — *"Both clauses are load-bearing: the trigger and the rewrite moment … while
     nothing rewrote `meta`, leaving the KB refusing to serve forever behind a perfectly consistent
     corpus."* Same premise. Under (d) a crash after a `full=true`-only repair leaves `meta` already
     rewritten, and a plain `refresh` seen through *resumes and completes*; the fork is the reverted
     case above, which violates invariant 7 rather than refusing forever. Recast the paragraph
     around that consequence, or fold it into `:1689`.
   - `:1765-1766` — *"it is the drop that records the **configured** model as the one now filling the
     corpus"* against `:1811-1812` *"the identity of the artifact that actually filled the corpus,
     **not the configured one**"* and `repair.py:64-69`. Say *"the encoder's identity"*.
   - `:1708-1709` and `:1767-1768` — *"§11 has the KB refusing to serve while the mismatch lasts"* /
     *"for as long as the mismatch lasts"*. Round 4 finding 2 named `:1797-1799` for exactly this
     (it is the instant, not the mismatch, that keeps it refusing) and the brief reports it fixed
     there; these are two further sites. After the drop the mismatch is *over* — `meta` agrees with
     the encoder — and the absent instant is what refuses. *"for as long as the completion instant
     the drop cleared is absent"*.

4. **[NITPICK] Three code docstrings state the resume half unconditionally where the design states
   both halves.** `repair.py:23-25` (*"an interrupted rebuild resumes rather than starting over"*),
   `repair.py:80-84` (*"the scan that answers it may treat the dead run's committed rows as
   current"*), `scan.py:55-60` (*"a resume, not a redo"*). All true where the encoder in hand is the
   one `meta` names; §8.4:1847-1852 and §11:2222 give the revert half beside it. One clause each:
   *"— where the encoder in hand is the one `meta` names; a reverted configuration makes it a
   mismatch, and the drop redoes the corpus."*

5. **[NITPICK] The FINDINGS round-1 record reads in the present tense about a design the file later
   says was reversed.** `FINDINGS.md:1305-1308`: *"The drop widens `chunks_vec` and the *completing*
   transaction records the new identity — deliberately two transactions"*. The paragraph is framed
   as history and `:1362-1368` records the reversal, but a skimming reader of an always-loaded file
   takes "deliberately" as current. Insert *"— as the design then stood —"* or *"(the round-1
   design)"* after "identity".

### On the four questions the brief asked

- **(1) Is the resume path safe in every case claimed?** Yes, on every file state I traced against
  `changes.compare`, `_walk_phase` and `disposal.run` with `meta` = B and the dead run's `files`
  rows B-vectored. *Deleted from disk*: in `indexed`, not in `admitted` → `_delete`. *Grown past the
  cap*: `walk.admitted` excludes it → same deletion; if it crosses between the walk's read and the
  index phase's, `dispose` → `_record_skip(was_indexed=True)`. *Became binary*: `_classify` →
  `no_longer_admitted` → deletion, or git reports it changed → read → same. *Killed during the walk,
  before `_close_walk_phase`*: `files` empty, `pending` is the previous scan's, `last_walk_completed_at
  < last_scan_started_at` → `files_remaining` null, `never_built` → not served; next scan finds every
  candidate changed and replaces `pending` wholesale. *Killed after the walk*: `pending` is the dead
  run's remainder; `previously_indexed` is recomputed from the committed rows, so a remainder file
  that turns out binary is a recorded skip (no row) and a committed file that changed and turned
  binary is a deletion. *Dead run was `--full`*: the drop already emptied everything, so a plain
  `refresh` resuming it leaves nothing "silently unfulfilled" in §8.4:1676's sense. *Git blob-hash
  clearing over dead-run rows*: `unchanged_by_git` reads `row.git_blob_hash` written by the dead run
  from the same `answers.listed` a completing run would have used — the semantics of any crash
  resume. *Reverted after the kill*: first branch, drop, redo — the new test pins it. *Different
  width, killed, reverted*: `rebuilt_identity(B/16, A/384, 16)` → A/384 → drop at 384. One thing
  that is not a defect but is worth knowing: a resume reports `rebuilt_identity: None`, so
  `_print_rebuild` is silent and the operator who runs the foreground `refresh` after a kill sees an
  ordinary build; the only sign the corpus was mid-rebuild is the `reindex_required` it reported
  beforehand.
- **(2) Did reversing the flip moment cascade a fifth time?** Yes — findings 1, 2 and 3, and all
  three are one mechanism: the sweep was over the *rule* ("written at completion") and not over its
  *consequences* ("a revert restores agreement", "the width is the only evidence", "nothing would
  rewrite `meta`"). Every site the brief listed as corrected is corrected; every site this round
  found is a sentence that *followed from* the old rule rather than stating it.
- **(3) Is `_begin`'s seam right?** Yes. The read does not need to share the acquire's
  *transaction* to be correct — once `_begin` commits, this process holds the lock and every other
  build's `_begin` refuses, so a second read-only transaction would see the same state — it shares
  it because the round trip is free. The docstring claims only that the deciding build must be the
  one holding the lock (`scan.py:161-167`), which is the true claim, and `in_one_transaction` rolls
  the lock write back if `parse_and_validate` raises inside `_work` (`transactions.py:176-180`),
  so the lock cannot be taken on `meta` this build could not read. Splitting the read out would
  buy a better name and cost a second transaction; not worth it.
- **(4) Anything in §6.1–§6.4, §8.4, §8.5, §11 or §9 the code contradicts?** §8.4:1788-1799
  (finding 1) and §8.4:1689-1690, :1708-1709, :1765-1768, :1820-1827 (finding 3). Checked and
  holding: §6.2's reclaim rule and `--force-unlock` details; §6.3; §6.4; §8.4's `add`/`remove`
  ordering, the `full=true` mechanics, the four-cause list and its bullets other than the sites
  above, the flip-at-drop reversal at :1829-1852; §8.5's table row, precedence, `files_remaining`
  rule and `lock` fields; §9's foreground list including the will-not-open database; every §11 row
  including the new interrupted-rebuild row; invariant 7 as withdrawn-in-place; `build-plan.md:1711`
  and the done-when; `FINDINGS.md` plan item 2 and the round-4 paragraph. `Refreshed.status` is
  computed by `reporting.observe` on a fresh open (`lifecycle.py:280`), so the handle the drop makes
  stale is never what a caller reads.

VERDICT: NEEDS_CHANGES

## Round 6 — 2026-09-16

### Summary judgment

The repair rule is now one statement, and it is the true one, at every normative and code site I
read: §8.4 (six passages), §8.5's row and skip paragraph, §11's new row, §13 invariant 7, §3.2,
`repair.py` (module, `rebuilt_identity`, `drop_derived`), `state.py` (`resolve`, `never_built`,
`inputs_for_open`), `scan.py` (module, `_begin`, `_complete`), `database.py` (both round-5 sites),
`meta.py`, `lifecycle.Refreshed`, `indexer/main.py`, and the test module and class docstrings — and
each agrees with what `repair.py:99-103`, `:145-150` and `scan.py:392-401` do. No code changed and
none needed to; the code has been done since round 5. **The answer to the brief's second question is
yes, a sixth cascade, small and entirely prose, and its two sharpest instances are in the always-loaded
file**: FINDINGS still says the width is what makes the scan after an interrupted width-changing
rebuild declare the table back — the exact claim the brief reports fixing at §8.4:1786 this round,
surviving in the second document — and still says a revert makes "the identity agree", one paragraph
below the site round 5 marked as history. Three test-file survivors of round 5's class (a class
docstring stating the round-1 rationale, a test name saying "at completion", and a docstring that
describes the *other* test's repair) and a structural answer to question 4. Nothing here is a
behaviour defect or a normative contradiction; it is the last of the consequence-class residue, and
the design itself would ship.

### Findings

1. **[IMPROVEMENT] The FINDINGS M23 block states two pre-(d) consequences in the present tense, one
   of them the exact claim the brief reports fixing in §8.4 this round.** This is the sixth cascade,
   in the file a fresh session resumes from, and it is the "two documents stating one claim is two
   sites" case `CLAUDE.md` names.
   - `FINDINGS.md:1325-1327`: *"What stayed load-bearing is the width as a **repair input** — it is
     what makes the scan that follows an interrupted width-changing rebuild declare the table back
     rather than die on its first insert."* Under (d) it is not. Trace: A/384 → B/16 rebuild killed
     after its drop leaves `meta` B/16, table 16. Seen through, `rebuilt_identity(B/16, B/16, 16)` →
     `None`, no declaring back — a resume. Reverted, `rebuilt_identity(B/16, A/384, 16)` fires on
     its **first** branch (`repair.py:99`, `encoder.dim != corpus.embed_dim`), which never consults
     `stored_width`. The width as a repair input is reachable only from the tamper case — which is
     what §8.4:1780-1787 now says, and what the brief says `:1786` was rewritten to say. **Change**
     to: *"What stayed of the width is its second job, as a repair input for the one state that can
     still produce it — a `meta` and a table joined from different builds — where it is what makes the
     next scan declare the table back rather than die on its first insert. (Round 4 then made the
     interrupted-rebuild case unreachable for it too, below.)"*
   - `FINDINGS.md:1338-1340`: *"so interrupt that rebuild and revert the configuration and the
     identity agrees, the declaration never moved, and the corpus reports `ok`"*. Present tense, in
     a paragraph whose next sentence (*"The fix again adds no state … the drop clears
     `last_scan_completed_at`"*) describes the **current** mechanism — so a reader takes the revert
     → agreement → cleared-instant chain as current. Under (d) a revert produces a *mismatch*, and
     the cleared instant covers the *seen-through* case, not the reverted one. Same shape as round 5
     finding 5, which marked `:1307` and not the paragraph below it. **Change**: after "interrupt
     that rebuild and revert the configuration" insert *"— under the rule as it then stood, with the
     identity written at completion —"*, and after "over tables the drop had emptied" add *"(Under
     the round-4 rule the same revert is an encoder mismatch and takes the drop; what the cleared
     instant covers today is the swap seen through.)"*
   `:1357-1358` and `:1385-1387` are the same claim correctly framed as history and need no change.

2. **[IMPROVEMENT] `test_an_interrupted_rebuild_still_refuses_and_the_next_build_completes_it`'s
   docstring describes the repair the *next* test runs, not the one its own body runs — and the body
   is the one test of the different-width seen-through resume, which it does not assert.**
   `tests/test_knowledge_repair.py:447-450`: *"the repair is an ordinary encoder mismatch. What
   reports the refusal meanwhile is the withdrawn completion instant."* The completing build at
   `:476` passes `FakeEncoder(model_name="other", dim=_OTHER_DIM)` — equal to what the drop recorded
   — so `rebuilt_identity` returns `None` and the build **resumes** over the emptied tables with no
   second drop; the encoder-mismatch redo is `:481-515`'s test, which uses `build_index(corpus)`.
   And in this fixture the refusal is reported by *both* the withdrawn instant and `encoder_mismatch`
   (`meta` other ≠ config default), so "the withdrawn instant" is the seen-through description
   again. This is round 2 finding 8's shape recurring after the round-5 rewrite: a docstring
   crediting a mechanism its fixture does not isolate. **Change** the paragraph to: *"Configuration is
   left at the default, so `status` reports what a revert would — the withdrawn instant and an
   encoder mismatch both — while the build that completes it loads the abandoned model and so takes
   no drop: it resumes over the emptied tables. State answers to configuration and the repair to the
   encoder in hand (§8.4), and the two disagreeing here is why the corpus goes on reporting
   `reindex_required` after the build completes."* Then make the body assert what the docstring now
   says, which also closes two gaps no test covers: `refreshed = await build_index(...)` at `:476`;
   `assert refreshed.result.rebuilt_identity is None, "the same model resumed; no second drop"`
   (the only different-width resume in the suite — `…_was_not_reverted_resumes…` is same-width);
   and `assert refreshed.status.summary.state is KnowledgeState.REINDEX_REQUIRED` — which is the
   §8.4:1823-1825 consequence ("the rebuilt corpus goes on reporting `reindex_required`, because it
   goes on being true") and the case `lifecycle.Refreshed`'s docstring (`lifecycle.py:103-105`) names
   as the reason `status` is returned at all, currently pinned by nothing: `test_knowledge_scan.py:449-460`
   builds exactly this state and asserts `meta` only. Both new assertions fail first under the
   obvious mutations — swap the completing encoder to `FakeEncoder()` and the first goes red;
   `write_config` the other model before the completing build and the second does.

3. **[IMPROVEMENT] `TestReadingAStoredWidthBack`'s class docstring states the round-1 rationale for
   the width read, which the design now says the width cannot do.** `tests/test_knowledge_repair.py:868-870`:
   *"the recorded `CREATE` is the only place the width can be read from, and reading it is what makes
   an interrupted rebuild detectable at all."* §8.4:1780 (*"Nothing this system does can produce
   it"*), `state.py:97`, `repair.py:82-88` and this file's own `:704-716` all say an interrupted
   rebuild is detected by the cleared instant and the width sees only a `meta` and a table joined
   from different builds. Fifth docstring of this file in round 5's class; it was not in that list
   because it does not use any of the six phrasings. **Change** the second sentence to: *"Reading it
   is what lets a `meta` and a table joined from different builds — restored, or edited by hand — be
   reported and declared back rather than dying on the first insert; nothing this package does
   separates them (§8.4)."*

4. **[IMPROVEMENT] §8.4 does not yet read as one argument; it reads as the argument plus its
   amendment history, and the repetition is the drift surface rounds 2–5 were spent on.** Counted:
   the two-halves rule or one of its halves is stated **six** times inside §8.4 — `:1682-1688`,
   `:1751-1757`, `:1795-1801`, `:1813-1816`, `:1850-1853`, `:1855-1860` — and the
   state-not-verb consequence twice, nearly verbatim (`:1689-1692` and `:1827-1833`, both ending
   "insert the reverted model's vectors into a corpus `meta` labels with the abandoned one"). Three
   passages are chronology in a normative section: `:1835-1842` ("this reverses an earlier choice"),
   `:1844-1853` ("this paragraph describes the rule as it stood, not as it stands"), and
   `:1808-1811` ("The general shape, since this cost two review rounds"). FINDINGS records the
   operator's rule for *this* document — *"a design document states what we are doing, with rejected
   alternatives at the end … historical traces make it unusable over time, and the review trail
   already holds the history"* — and FINDINGS `:1363-1374` and `:1346-1351` already carry both
   histories. **Suggested shape**, one pass: (i) drop the first sentence of the `:1689` parenthetical
   and point at the state-not-verb paragraph instead; (ii) merge `:1813-1816`, `:1850-1853` and
   `:1855-1860` into one paragraph — the drop rewrites the identity; the cleared instant is what
   refuses; invariant 7 has no exception; seen through, the next scan resumes; reverted, the
   abandoned identity is a mismatch and the next scan drops and redoes — with one sentence pointing
   at §15; (iii) move `:1835-1849` to §15 as *"**Recording the rebuilt identity at the scan's
   completing transaction.** Rejected: its reason — that flipping at the drop would let the KB
   serve during a rebuild — stopped holding once the drop cleared `last_scan_completed_at`; and it
   left a window in which a killed rebuild's committed rows carried a model `meta` did not name, so
   a same-width revert resumed over them and completed `ok` over two models' vectors (invariant 7)."*;
   (iv) move `:1808-1811` to FINDINGS, where it already is. Noted rather than hidden: `CLAUDE.md`'s
   withdraw-in-place rule and §13's own struck-through invariant 7 pull the other way, so this is
   the researcher's and operator's call — but the count above is the mechanism behind five rounds of
   neighbour findings, and it does not go down by adding a seventh statement.

5. **[NITPICK] Three small survivors in `tests/test_knowledge_repair.py`.** `:284` — the test is
   named `test_the_rows_written_at_completion_are_the_two_identity_keys`; the rows are written by
   the drop (`repair.py:149`), and a name is what a failing-test report shows: rename to
   `test_the_rows_the_drop_records_are_the_two_identity_keys`. `:752-754` — *"(The scan following
   an interrupted rebuild takes no drop and resumes instead — a different case, covered above.)"* is
   round 5 finding 4's unconditional resume half, in the test file: *"(… takes no drop and resumes
   where the swap was seen through, and takes this drop where it was reverted — both covered
   above.)"*. `:769-770` — *"the completion instant has not been written"* is the pre-round-3
   world in which the old instant stayed; it has been **cleared**: *"and the completion instant the
   drop cleared has not been written again"*.

6. **[NITPICK] Two wording slips in §8.4 that contradict their neighbours.** `:1686-1688`: *"The
   completion instant the same transaction cleared is what makes some later scan happen at all …
   so the remainder is always indexed"* — nothing makes a scan happen (§6.2: no scheduler;
   `:1805`: "for as long as nobody happened to run `refresh`, which in v0 is nobody"); the instant
   makes one *owed and reported*. Suggest: *"is what keeps a later scan owed and reported — and it
   survives a reverted configuration — so the remainder is never silently unfulfilled: whichever
   scan next runs indexes it, and by the model the finished corpus claims."* `:1766`: *"a
   crash-recovery re-drop is never a no-op"* names crash recovery as a re-drop seventy lines above
   *"Recovery is therefore a resume, not a redo"* (`:1855`); the sentence is right about the case
   it covers (a same-width redo after a revert still empties the tables) and wrong as a name for
   the class: *"so where a crash leaves the drop owed again — the reverted case — the re-drop is
   never a no-op"*.

7. **[NITPICK] `groups._SERVING`'s comment characterises the second cause by a disjunction it does
   not satisfy.** `zikaron/core/knowledge/groups.py:60-64`: `reindex_required` *"means the vectors
   in the table are not the ones this corpus's recorded identity describes or are not there at
   all"*. For a first scan killed after committing files, and for a seen-through interrupted
   rebuild, the vectors present are exactly the ones `meta` describes and some of them are there;
   what is missing is a *completed build's* corpus. Round 4 called this comment consistent under
   the round-3 rule, where `meta` did name another model during a rebuild; (d) removed that. One
   clause: *"… are not the ones this corpus's recorded identity describes, are not a completed
   build's, or are not there at all"*.

### On the four questions the brief asked

- **(1) Is the two-halves statement correct and consistent everywhere?** Yes, at every normative and
  code site (listed in the summary), and each matches the code's actual branches. The reconciling
  grep, re-run here over the eight phrasings plus `detectable`, `at completion`, `completing
  transaction`, `crash-recovery` and `interrupted rebuild`: `nothing compared disagrees` — three
  sites, all correctly scoped, as the brief reports; `agrees … again` / `nothing left to say` /
  `trace vanish` / `widened table` / `the one fact` / `only evidence` — none outside `reviews/`;
  `at completion` / `completing transaction` — §8.4:1583 and `repair.py:34-35, 128, 138` are
  correct (the first scan's instant; the reversal note; "writes it again"), `:2284-2285` is struck
  through, `test:630` is correctly counterfactual, and `test:284` is the stale name (finding 5);
  `detectable` — one site, finding 3. The FINDINGS sites in finding 1 use neither the mechanism's
  phrasings nor the six the round-5 sweep listed, which is how they survived it.
- **(2) Did fixing it cascade a sixth time?** Yes, in the always-loaded file (finding 1) and in the
  test file at sites round 5 did not list (findings 2, 3, 5). Every site the brief lists as
  corrected is corrected, and the three the researcher's own grep found are correct as rewritten.
  No cascade in the code or in §8.4's normative rule.
- **(3) Anything in §6.1–§6.4, §8.4, §8.5, §11 or §9 the code contradicts?** No. Re-read whole
  against the code this round: `repair.py`, `state.py`, `scan.py`, `database.py`; §8.4's four
  bullets, seen-through paragraph, identity paragraphs and recovery paragraph; §8.5's row, `null`
  rule, skip paragraph and `lock` fields; §11 every row; §9's foreground list and `--force-unlock`;
  §13 invariant 7; §3.2's "can also go absent again". Also checked and holding: the typo'd-`embed_dim`
  case (`add` seeds bge/768; the build's `rebuilt_identity(bge/768, bge/384, 768)` fires on the first
  branch, drops at 384, records bge/384, and every later `refresh` is `None` — no repeated drop, and
  `state` reports `reindex_required` against configuration, which is §8.4:1823-1825 and is the
  consequence finding 2 asks to pin). The lifecycle, lock and reporting modules did not change
  since round 5 and were not re-traced.
- **(4) Does §8.4 read as one argument?** Not yet — finding 4, with the count and a concrete shape.
  The *content* is one argument now; the *form* is six statements of it and three paragraphs of how
  it got there.

VERDICT: NEEDS_CHANGES

## Round 7 — 2026-09-16

### Summary judgment

The consolidation is sound: the four-consequence paragraph at §8.4:1810-1819 carries every
load-bearing clause the six statements carried, the three chronology passages have arrived where
they were sent (§15's first entry, FINDINGS `:1364-1391`, and the `:1690` pointer), and §15's new
entry is a faithful account of what was rejected and why — I re-ran round 4's same-width revert
trace under the old rule and it matches the entry sentence for sentence, including the scoping to
equal widths. Round 6 finding 2's two new assertions assert exactly what the rewritten docstring
claims, traced through `rebuilt_identity` and `lifecycle.refresh`'s `reporting.observe` call. The
code contradicts nothing in §6.1–§6.4, §8.4, §8.5, §11, §9 or invariants 7, 8 and 12. What the
reorder did leave is four pointer- and scope-level slips in §8.4 and §8.5 — none a contradiction,
none about behaviour — listed so they can be taken under the operator's every-nitpick rule.

### Findings

1. **[NITPICK] §8.4:1835-1836 "the paragraph above" now points at the wrong paragraph.** The
   state-not-verb paragraph ends *"That is the invariant-7 violation the paragraph above is built to
   prevent, reached through the verb rather than through the moment."* After the consolidation the
   paragraph immediately above (`:1821-1828`, *"What they are rewritten *to* …"*) is about the
   encoder's identity versus the configured one and prevents nothing; the paragraph built to prevent
   the violation is the four-consequence one at `:1810-1819`, now two paragraphs up. The reorder
   created a mis-pointer, not a contradiction. **Change**: *"That is the invariant-7 violation the
   drop's identity write exists to prevent, reached through the verb rather than through the moment."*

2. **[NITPICK] §8.4:1803-1804 "the availability rule above refuses … a door that rule does not
   cover" names a rule that has moved to §15.** The rule that refused *"empty groups filling in over
   minutes"* as misinformation was the flip-at-completion argument, which is now §15's first entry.
   The only availability statements left inside §8.4 are `:1709-1710` and `:1769-1771`, and both say
   the KB refuses to serve *because the completion instant is absent* — so read against them, the
   sentence's counterfactual (*"Without the cleared instant …"*) names as "the rule that does not
   cover this door" the very mechanism that covers it. The sentences before it state the substantive
   claim correctly; this clause is the orphan. **Change**: *"— misinformation of exactly the kind
   §7.4's 'no matches is a real answer' becomes over a corpus that was emptied rather than searched,
   and which no comparison this system makes could see here —"*.

3. **[NITPICK] §8.4:1749-1750 "which is the only thing that reports one" is unscoped, and the same
   bullet corrects it two sentences later.** The second-cause bullet: *"the state **a rebuild
   interrupted after its drop** is in, which is the only thing that reports one."* Read as "this
   cause is the only thing that reports an interrupted rebuild", it is contradicted by the bullet's
   own closing sentence (*"this cause is joined by an encoder mismatch"*) and by `:1789-1790`, which
   scopes the same claim correctly (*"by that cause alone where the swap is seen through"*). Read the
   other way round — an interrupted rebuild is the only thing that produces this state on a built
   corpus — it is true but is not what the sentence says. **Change**: *"… the state **a rebuild
   interrupted after its drop** is in — and, where the swap is seen through, the only cause that
   reports one."*

4. **[NITPICK] §8.5:1869 says the first two causes "have nothing to serve", which §8.4:1757-1759
   and round 6 finding 7's fix both contradict.** The state-table row: *"the first two have nothing
   to serve (§7.4), the last two have rows they cannot stand behind (§11)"*. A first scan killed
   after committing files, and a seen-through rebuild killed after committing files, both sit under
   the second cause with rows in `chunks` — which §8.4's own bullet says in as many words (*"a first
   scan that crashed after committing some files has chunks"*), and which is why round 6 changed
   `groups._SERVING`'s comment from the same disjunction to *"are not a completed build's"*. The fix
   reached the code comment and not the normative table it paraphrases — two sites, one corrected.
   The mechanical test on this row (round 3 finding 3) pins the cause count and the precedence, not
   this clause, which is how it survived. **Change**: *"the first two have no completed build's
   corpus to serve (§7.4), the last two have rows they cannot stand behind (§11)"*.

### On the four questions the brief asked

- **(1) Did the consolidation lose anything load-bearing, or contradict a neighbour?** Nothing
  lost. Checked destination by destination: the identity-at-drop rule, the cleared-instant-refuses
  clause, invariant 7's no-exception clause, the seen-through resume and the reverted redo are all
  in `:1810-1819`; the argument *for* a state trigger under the current rule is at `:1830-1836`;
  the flip-at-completion reason and its lapse are §15's first entry; the "two review rounds" lesson
  is FINDINGS `:1364-1391`; the duplicated state-not-verb consequence is the `:1690` pointer, whose
  target heading exists at `:1830`. A grep of the document for `at completion`, `completing
  transaction`, `as it stood`, `earlier choice`, `reverses` finds only `:1583` (the first scan's
  instant, correct), invariant 7's struck text, and §15. No new contradiction. What the reorder did
  produce is findings 1 and 2 — a pointer whose referent moved to §15 and a pointer whose referent
  is now two paragraphs away rather than one.
- **(2) Is §15's entry faithful and self-sufficient?** Yes. It states the alternative, its reason
  (serving during a rebuild once §11's mismatch refusal lapsed at the drop), why the reason lapsed
  (the cleared instant holds the corpus out of service whatever `meta` names), and the correctness
  cost, correctly scoped to models of equal width. Re-derived under the old rule: A/384 built;
  config → B/384; rebuild drops at 384, commits `a.md` with B's vectors, dies; revert to A;
  `rebuilt_identity(A/384, A/384, 384)` → `None`; walk clears `a.md` as unchanged on hash; `b.md`,
  `c.md` embedded with A; `_complete` writes the instant; `meta` A/384, `state: ok`, two models'
  vectors, no detector. Every clause of the entry corresponds to a step. The different-width revert
  is correctly excluded — under the round-1 width read it was caught and redone. A reader who never
  saw the old rule has what they need: §11's mismatch row still exists to give "§11's refusal" a
  referent, "the drop" is defined in §8.4, which the entry cites, and `repair.py:34-40` gives the
  same account from the code side, clause for clause.
- **(3) Round 6 finding 2's two assertions.** Both assert what the docstring says.
  `rebuilt_identity is None` (`test_knowledge_repair.py:481`): after `_an_unavailable_model()` dies
  on its first embed, the drop has written `other`/16 (`repair.py:149`) and declared the table at
  16; the completing build passes `FakeEncoder("other", _OTHER_DIM)`, so
  `rebuilt_identity(other/16, other/16, stored_width=16)` falls through both branches
  (`repair.py:99-103`) — no second drop, a resume over tables holding zero committed rows, which is
  what "resumes over the emptied tables" describes. `status.summary.state is REINDEX_REQUIRED`
  (`:490`): `lifecycle.refresh` computes `status` through `reporting.observe(store_dir, registered,
  config)` (`lifecycle.py:280`) with `corpus.config`, which `build_index`
  (`knowledge_fixtures.py:116-122`) leaves at the default; `meta` names `other`/16, so
  `encoder_mismatch` is true while `never_built` is false (`_complete` ran) and `width_mismatch` is
  false (16 == 16). The state comes from the mismatch alone — the §8.4:1826-1828 consequence the
  docstring names, and the case `lifecycle.Refreshed`'s docstring (`:101-105`) gives as the reason
  `status` is returned at all, now pinned. Both mutations the brief reports would go red for the
  reasons given.
- **(4) Anything in the normative sections the code contradicts?** No. Re-read against `scan.py`
  (`_begin`, `_complete`, `run`), `repair.py`, `state.py`, `groups._serve` and
  `lifecycle.refresh`: §8.4's four bullets, seen-through paragraph, four-consequence paragraph,
  artifact-identity paragraph and state-not-verb paragraph; §8.5's row, precedence sentence and
  absent/predating clause (`:1985-1989`); §11 every row; §13 invariant 7; §6.2's reclaim rule and
  `--force-unlock` details; §6.3; §6.4; §M23's done-when. Round 6's seven fixes are each present as
  described: FINDINGS `:1333-1336` and `:1348-1357`; the test docstring and two assertions above;
  `TestReadingAStoredWidthBack`'s docstring (`:879-884`); the renamed test (`:284`), the
  parenthetical (`:762-765`) and `_an_unavailable_model`'s docstring (`:780-781`); §8.4:1686-1689
  and `:1765-1767`; `groups.py:60-64`. Checked and deliberately not raised: `repair.py:34-40`
  narrates the reversal in a module docstring — the operator's no-chronology rule is for the design
  document, and the passage gives the measured reason the coding standard asks for, agreeing with
  §15 clause for clause.

VERDICT: APPROVED
