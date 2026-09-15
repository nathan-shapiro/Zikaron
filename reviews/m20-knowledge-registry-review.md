# M20 — the registry, and knowledge-base lifecycle without indexing — review

## Round 1 — 2026-09-15

**Summary judgment.** This is strong work: the three properties are genuinely enforced and tested by
attack rather than demonstration, the registry-first ordering is tested in both interrupted
directions, the extraction of `open_connection` and `database_files` was the right reuse call, and
the `reindex_required` third-cause amendment is sound and consistently propagated through §8.4, §8.5
and `state.py`. One defect blocks: every knowledge-base connection is opened with the memory store's
**three** pragmas — including `PRAGMA foreign_keys = ON`, which `knowledge-index.md` §3.2 spends a
paragraph explicitly *not* applying — while the two-pragma tuple the design mandates is dead code
guarded by a design-comparison test and a mutation that both prove nothing about runtime. The rest
is docstring-honesty and consistency debt of the class this corpus polices hardest.

### Findings

1. **[BLOCKER] Knowledge databases actually open with `PRAGMA foreign_keys = ON`, the design says
   they must not, and the tuple that says otherwise is applied nowhere.**
   `zikaron/core/store/connection.py:132` applies `zikaron.core.store.ddl.PRAGMAS` — WAL,
   `busy_timeout`, **`foreign_keys = ON`** — to *every* connection it opens, and
   `KnowledgeDatabase.create`/`open` and `lifecycle._breadcrumb` all open through it. Meanwhile
   `zikaron/core/knowledge/ddl.py:20` defines the design's two-pragma `PRAGMAS` with a comment
   asserting "`foreign_keys` is deliberately absent" — and nothing in the package ever executes that
   tuple (grep: its only consumers are `tests/test_knowledge_ddl.py`). Three distinct faults stack:
   - **Normative divergence.** `knowledge-index.md` §3.2: *"Two of the memory store's three pragmas,
     not three. … `foreign_keys` is **not** applied because this schema declares none, and switching
     it on would state a guarantee the section below spends its length denying."* The shipped runtime
     does the opposite. (Behaviourally inert today, since no FK is declared — the harm is exactly the
     wrong-mental-model harm §3.2 names, plus a design the code contradicts.)
   - **Prose contradicting adjacent code, twice.** `knowledge/ddl.py:14-19` claims a property of
     connections that no connection has; `connection.py:4-5` claims "both need the three pragmas
     `schema.md`'s DDL block opens with", which the knowledge design explicitly denies for its half.
   - **A vacuous guard.** `test_the_two_pragmas_match_the_design_exactly` (and FINDINGS' M20
     mutation list: "adding the third pragma — caught") verify the *constant* against the design.
     Since the constant is never applied, the test passes while the runtime carries the third
     pragma. This is the M14 "gate green while something material is wrong" class, rebuilt.
   **Fix:** parameterize the opener — `open_connection(db_path, *, pragmas: tuple[str, ...], …)`
   (or default it to the store's tuple and override from knowledge callers); pass
   `knowledge.ddl.PRAGMAS` from `KnowledgeDatabase.create`, `KnowledgeDatabase.open` and
   `lifecycle._breadcrumb`; rewrite `connection.py`'s docstring sentence to say the pragma set is
   the caller's DDL module's, naming the 3-vs-2 split as the second per-caller variance alongside
   `ConnectFailure`; and add a runtime test that `PRAGMA foreign_keys` answers `0` on a
   knowledge-base connection (the observable-state style `test_the_pragmas_the_design_requires_are_applied`
   already uses). If you instead believe FK=ON is harmless enough to apply uniformly, that is a
   *design amendment* to §3.2 with its rationale rewritten — not a thing to leave in this state,
   where the document, the constant, the test and the runtime say three different things.

2. **[IMPROVEMENT] A failed `add` after file creation lands in a third interrupted state the design
   and the lifecycle docstring both say does not exist — and it is the operator-attention one.**
   `lifecycle.py`'s module docstring and §8.4 present exactly two interrupted states (row-without-file
   → self-healing `reindex_required`; file-without-row → orphan). But `add`'s real sequence is:
   registry commit → `open_connection(db_path)` **creates the file** → tables in one transaction. A
   failure inside `_create_tables_and_meta` (disk full, the fault your own
   `test_creation_is_one_transaction` stages — which demonstrates the file surviving) leaves a
   committed row plus an empty database with no `meta`. `_observe` opens it, `parse_and_validate`
   raises `BAD_CONFIG`, and the KB reports **`error`** — the state §11 defines as "a refresh does
   not obviously repair it and the operator needs to know", for a condition a refresh (or a hand
   `rm`) trivially repairs. **Fix:** in `KnowledgeDatabase.create`, on failure *after*
   `open_connection` succeeded (not on the `FileExistsError` branch — that file is not ours),
   best-effort unlink `permissions.database_files(db_path)` before re-raising, collapsing every
   survivable create failure into the specified row-without-file state; add a test that a failed
   create leaves `reindex_required`, not `error`; and add one sentence (lifecycle docstring or
   §8.4) acknowledging that a hard kill inside the creation window still leaves row-plus-empty-file
   → `error`, so the enumeration stops claiming to be exhaustive.

3. **[IMPROVEMENT] `_breadcrumb`'s docstring says "Opened read-only and closed immediately" — it is
   opened read-write, and the opener then writes.** `existing_only=True` builds a `file:…?mode=rw`
   URI (`connection.py:114`), and the pragma loop issues `PRAGMA journal_mode = WAL`, which is a
   persistent header write on any orphan not already in WAL mode (Zikaron-made orphans are; foreign
   or hand-damaged ones need not be). The surrounding promise — "reported, never opened for search,
   never auto-deleted" — survives, but "read-only" is false as stated, on the artifact the module
   promises to leave alone. **Fix:** either support `mode=ro` in `open_connection` and use it here
   (cleanest, and it makes the promise true), or correct the docstring to say what actually
   happens: opened rw through the shared opener, closed immediately, and a no-op for any database
   already in WAL mode.

4. **[IMPROVEMENT] `timestamp` is imported from the memory-record domain, and that function's own
   docstring is now false by omission.** `lifecycle.py:32` imports it from
   `zikaron.core.records.memory`, whose docstring says "every stored time in this store's own
   format … `created_at`, `updated_at`, `event.at`, … all come from here" — an enumeration that now
   silently excludes `knowledge_bases.created_at`, in the corpus that convicted itself of exactly
   this enumeration-drift class in M19. The reuse itself is right (one clock, one format — the
   string comparison in `reporting.files_remaining` depends on it). **Fix:** relocate `timestamp`
   to a neutral module (e.g. `zikaron/core/clock.py`), re-exporting from `records.memory` so no
   memory-side call site churns — M21 will call it far more (`pending.noticed_at`, the four
   scan-outcome keys); or, minimally, extend the docstring's enumeration to name the registry's
   `created_at` and the knowledge `meta` instants to come.

5. **[IMPROVEMENT] `errors.py` justifies its class-per-refusal design with a claim about the caller
   that is false of the only caller.** `zikaron/core/knowledge/errors.py:9-11`: "every caller so far
   branches on *which* refusal it got — the command prints a different next step for each". The
   command has exactly one `except KnowledgeError` (`main.py:108-110`) and prints `str(exc)`; the
   differing next steps live in the *messages*, and nothing anywhere branches on the subclass. The
   design is still defensible (a future MCP surface can branch without string-matching), but the
   stated evidence is not. **Fix:** rewrite the paragraph to the true reason — each refusal carries
   a caller-facing message naming its next step, and separate classes keep a future surface able to
   branch typed rather than by parsing prose.

6. **[IMPROVEMENT] FINDINGS.md contradicts itself about `design/schema.md`, sixteen lines apart.**
   Line ~292: "`design/schema.md` owns `memory.db`'s tables **including the knowledge-base
   registry**". Line ~311 (the rounds-11–12 paragraph): "**`design/schema.md` is deliberately
   untouched**; it gains its section when the schema change is made." — present tense, now false:
   M20 made the change and the section exists. This is the neighbour-contradiction class the same
   file documents three paragraphs later. **Fix:** supersede in place, e.g. append "— done at M20;
   §'The knowledge-base registry' now exists there" or recast the sentence to past tense as a
   statement about what rounds 11–12 deliberately did not touch.

7. **[IMPROVEMENT] `files_seen` is reported always; §8.5 says it is reported "additionally while a
   scan is running".** `reporting.gather` puts `files_seen` unconditionally into `Details`, and the
   CLI prints it always. §8.5 not only scopes it to a running scan but leans on the contrast:
   "`files_indexed` appears in the main list **rather than the indexing-only sentence**". One side
   should move. Always-reporting is arguably the better behaviour (the counter is seeded, and idle
   it reads as the last walk's total under the same partials/totals rule the skip breakdown already
   states), so the cheap fix is amending §8.5's sentence to say so — but pick one; a response schema
   the normative document describes differently is the drift the §8.5 field-mapping rule exists to
   prevent.

8. **[NITPICK] The CLI's `add` closes with "Build it with a refresh." — and this build ships no
   `refresh` verb.** A user who obeys gets `invalid choice: 'refresh'` from argparse until M21
   lands. Suggest "Nothing is indexed yet — indexing arrives with the `refresh` verb in a later
   milestone", or drop the sentence until the verb exists.

9. **[NITPICK] The two parsers of the same identifier disagree on strictness.** `meta._require_uuid4`
   enforces length 36 *and* version 4 (with a test naming why uuid1 is refused); `registry._row`
   accepts any `UUID`, so a hand-edited registry row with a uuid1 `id` round-trips silently while
   the same value in the KB's own `meta` is fatal. Path safety is unaffected (any UUID's string
   form is hex-and-dashes), so this is symmetry, not security: either add the version check to
   `_row` or leave one comment saying why the registry is deliberately looser.

### Judged and found sound (recorded so later rounds do not re-litigate)

- **Reuse:** extracting `open_connection` (with `ConnectFailure` as the one variance — modulo
  finding 1, which shows the pragma set is a second variance) and `permissions.database_files` were
  the right generalizations; `in_one_transaction`, the permissions module, and config-declared
  bounds (`SEEDED_FROM_CONFIG` reading `IntBounds` from `CONFIG_KEYS_BY_NAME`) are genuine reuse,
  not parallel code. The small `read_meta`/`_read_meta_table` twin is acceptable — five lines,
  different documents govern each.
- **`Observed`'s split of `lock_held` from the reported state** is justified and its docstring says
  exactly why: precedence makes `reindex_required` mask `indexing`, and `remove` asks a different
  question. The test (`test_remove_refuses_while_the_lock_is_held`) restates the reasoning.
- **`list` is `status` projected down structurally**: one `_observe`, `Summary` a field of
  `Status`, and `test_a_summary_carries_only_what_a_caller_needs_to_choose` pins summary equality.
- **The three deliberate decisions** (no version bump with the compatibility rule written into
  `schema.md`; `python -m` with the brief's sentence withdrawn on its own cited grounds; the third
  `reindex_required` cause as the persisted fact `last_scan_completed_at`-absent) are each
  well-reasoned and consistently propagated — I checked §8.4, §8.5's table and `state.resolve`
  against each other and found no residual two-cause phrasing.
- **The security property is enforced and attack-tested**: hostile-name parametrization, the
  registered-hostile-name case, the untyped-caller path test that found the annotation-only hole,
  and uuid re-parse at both the path builder and the registry row reader.
- The state precedence is tested exhaustively over all 64 combinations with an independent oracle;
  the interrupted states are forced, not narrated; the additive-migration clause is asserted against
  a store with the table dropped.

VERDICT: NEEDS_CHANGES

## Round 2 — 2026-09-15

**Summary judgment.** All nine round-1 findings are genuinely fixed, and mostly fixed well: the
pragma parameterization is the right shape (required, un-defaulted, runtime-verified in both
directions), the `_breadcrumb` rework is exemplary — `mode=ro` as a measured tripwire plus a
byte-identity test against a deliberately non-WAL fixture — and the design-document amendments
withdraw in place rather than papering over. What remains is this corpus's dominant defect class,
twice: the third-state cleanup's prose now claims more than the code delivers (two failure windows
still leave the state the fix was built to abolish, one of them also leaking the connection), and
the `timestamp` relocation left three docstrings asserting mutually incompatible contracts about
timestamp comparison. Both are small, neither is a blocker, and both are exactly the kind of thing
round 3 exists to close.

### Findings

1. **[IMPROVEMENT] The create-failure cleanup covers a narrower window than the prose now claims,
   and one uncovered path also leaks the connection.**
   `zikaron/core/knowledge/database.py:212-227`: the cleanup `try` wraps only
   `_create_tables_and_meta`. Two failure paths after the file exists escape it:
   - **Inside `open_connection` after `aiosqlite.connect` succeeded** — the extension load
     (`sqlite_vec` missing or broken is the concrete case), a pragma, or the `stat`. `connect`
     creates the file (§8.4's own words: "The file exists from the moment it is connected to");
     `open_connection` closes the connection and raises; `create` propagates with the row already
     committed and a 0-byte database on disk → `_observe` reports **`error`**, the exact state
     finding 2 was raised to abolish.
   - **The `enforce_store_file_mode` loop** (`database.py:226-227`): a failure there leaves the
     file *and* never closes `db` — the non-daemon-thread hang the class docstring at
     `database.py:152-156` names as the paid-for lesson.
   Meanwhile `lifecycle.py:26-27` says "Creation removes what it made on **any such failure**" and
   `knowledge-index.md` §8.4 (line ~1396) says "removes the database it created on **any failure
   after creating it**" — both now over-claim, leaving only the hard kill as the acknowledged
   residue when two in-process exception paths produce the same state. **Fix (code, preferred):**
   the `if db_path.exists()` check three lines earlier has just proven the path was empty, so
   anything at it afterwards is ours — widen to one `try` from `open_connection` through the mode
   loop: bind `db: aiosqlite.Connection | None = None` before it, and on `BaseException` close
   `db` if bound, `_remove_quietly(db_path)`, re-raise. (`_remove_quietly` already suppresses
   `FileNotFoundError` via `OSError`, so the connect-failed-before-creating case costs nothing.)
   Alternatively narrow the two prose claims to "any failure while creating the schema" and name
   the two escaping paths — but the code fix is ~6 lines and makes the existing prose true.

2. **[IMPROVEMENT] The `timestamp` relocation left three docstrings asserting incompatible
   contracts about comparing stored timestamps — a fix-adjacent neighbour contradiction.**
   Three statements, pairwise inconsistent:
   - `zikaron/core/consolidation/runs.py:21-27` (edited this milestone — it now cites
     `core.clock`): "It is **the only place in the system** comparing two stored timestamps, and
     it does so by **parsing** them rather than comparing the strings: the strings happen to sort
     correctly today … a property of one formatting decision rather than of the contract."
   - `zikaron/core/clock.py:4-8`: "…a knowledge base's `files_remaining` rule compares its walk's
     completion instant against its build's start **the same way**" — naming the second place
     runs.py says does not exist, and describing the lease as "decided by comparing two of these
     **strings**", which runs.py's own code refutes (it parses).
   - `zikaron/core/clock.py:23-24`: "any two of them **may be compared as strings**" — elevating
     to contract exactly what runs.py calls a coincidence of formatting. And
     `reporting.files_remaining` (`reporting.py:152`, `walked < started`) bets on that contract.
   The behaviour is correct today on every path (`+` < `.` makes the zero-microseconds form sort
   correctly), so this is prose, not a bug — but one of the two normative claims must yield.
   **Fix:** make `clock.py` the single authority and state the contract there explicitly ("one
   format, chosen so that lexicographic order agrees with temporal order; `files_remaining`
   relies on this"), then amend `runs.py`: "only place comparing" → "the only place doing
   *arithmetic* on stored timestamps" (it parses because it must add a duration), and recast the
   "happen to sort correctly today" caution as either withdrawn or as defence-in-depth beyond the
   stated contract; also fix `clock.py`'s "comparing two of these strings" description of the
   lease to "parsing two of these". (If you instead decide string order is *not* the contract,
   `files_remaining` must parse — pick one, in one place.)

3. **[IMPROVEMENT] The FileExistsError carve-out — "that file is not ours" — is implemented but
   unpinned by any test.** `test_creation_refuses_a_path_that_is_already_taken`
   (`tests/test_knowledge_database.py:165-173`) asserts only that the second `create` raises; it
   never asserts the first knowledge base's file survived. A regression that ran the new cleanup
   on the `FileExistsError` branch — the one branch round 1 explicitly excluded, because there it
   deletes somebody else's data — would pass the entire suite. **Fix:** after the `pytest.raises`
   block, assert the path still exists, ideally byte-identical to a capture taken before the
   refused call (the `test_reporting_an_orphan_does_not_modify_it` style, which this file now has
   a precedent for).

4. **[NITPICK] `knowledge/ddl.py:22-25` says the test reads the live connection "rather than
   comparing this tuple to the design" — but the tuple-vs-design comparison test still exists**
   (`tests/test_knowledge_ddl.py:38-44`), correctly, guarding the constant's content while the
   runtime tests guard its application. One word: "rather than" → "not merely", so the comment
   stops denying a test that is present and useful.

5. **[NITPICK] The registry parser test's "not a uuid" fixture never reaches the branch its id
   suggests.** `tests/test_knowledge_registry.py:188`:
   `"not-a-uuid-at-all-but-thirty-six-chars"` is **38** characters, so it fails `parse_id`'s
   length check, same as the path-shaped case — the `UUID(value)` ValueError branch is exercised
   only through `meta`'s own tests, not through the registry. Make it exactly 36 non-hex
   characters (and the name honest) so the parametrization covers all three refusal branches it
   reads as covering.

### Round-1 fixes verified correct (recorded so round 3 does not re-check)

- **Finding 1 (pragmas):** fully resolved. Required un-defaulted `pragmas` parameter; both
  knowledge paths pass `knowledge.ddl.PRAGMAS`, both store paths `store.ddl.PRAGMAS`;
  `test_a_knowledge_connection_really_has_foreign_keys_off` checks create *and* open and pins the
  positive pragmas (WAL, 5000) so it cannot pass vacuously off SQLite's FK-off default;
  the memory-store counter-test and the omitted-pragma test close both escape routes I asked for;
  `connection.py`, `knowledge/ddl.py` and §3.2 all now tell the same story (modulo nitpick 4).
- **Finding 2:** resolved as specified — the residue in finding 1 above is a gap in my own
  round-1 specification ("after `open_connection` succeeded"), not a failure to implement it.
- **Finding 3 (`_breadcrumb`):** resolved better than either option I offered — direct `mode=ro`
  connect, no pragmas, docstring saying which half does the work, and the byte-identity test with
  an asserted non-WAL fixture and a breadcrumb read that proves the open actually happened.
- **Findings 4-9:** all resolved as described in the brief and verified against the files:
  `clock.py` exists with no re-export and all three importers moved (modulo finding 2 above);
  `errors.py`'s paragraph now matches `main.py:108-110`'s single `except KnowledgeError`;
  FINDINGS.md line ~311 superseded in place with the strikethrough; §8.5's `files_seen` withdrawal
  is thorough, including recasting the `files_indexed` contrast sentence that leaned on the old
  rule (line ~1687) and the §8.5 detail list (line ~1657); the CLI's add closer names no missing
  verb; `_row` parses through `meta.parse_id` with the three-way parametrization.
- **The `statements` parameter on `_create_tables_and_meta` is an acceptable seam, not a smell.**
  It is data the function operates on rather than a behaviour hook, the single production caller
  passes the module constant at call time, the no-default rationale (a default binds the tuple at
  definition, so a monkeypatched module attribute would never arrive) is technically accurate,
  and the relocated transaction test earns its placement: failing the *last* statement is what
  makes the rollback assertion real, and the docstring at `database.py:247-252` says exactly why
  it cannot live at the `create` level any more.

VERDICT: NEEDS_CHANGES

## Round 3 — 2026-09-15

**Summary judgment.** Every round-2 finding is correctly and completely fixed: the widened cleanup
in `KnowledgeDatabase.create` is the right shape and its parametrized test genuinely forces both
escaping paths I named; the timestamp contract landed in the right place with the right evidence;
the carve-out, the ddl comment and the 36-character fixture are all resolved, and the fixture fix
finding a never-read error message is exactly what correcting a vacuous fixture is for. One thing
remains, and it is this milestone's recurring pattern one more time: the round-2 fix to `runs.py`
introduced a universal claim ("the only place in the system doing arithmetic on a stored
timestamp") that the signals package falsifies, and `clock.py`'s two-caller enumeration undercounts
for the same reason — the grep-for-the-claim step stopped at the three files the finding quoted. I
share the blame: round 2's suggested wording is where the false universal entered. It is a
two-sentence prose fix with zero code impact, but it is a factual defect, not a cosmetic one, in
the defect class this corpus polices hardest.

### Round-2 fixes verified (checked against the files, not the brief)

- **Finding 1:** `database.py:225-236` — `db` bound `None` before one `try` spanning
  `open_connection`, `_create_tables_and_meta` and the mode loop; `BaseException` handler closes a
  bound connection, `_remove_quietly`s, re-raises. `open_connection` (`connection.py:132-146`)
  closes its own connection on setup failure before raising, so the `db is None` case in `create`'s
  handler is real, not a double-close hazard. Both prose claims (`lifecycle.py:24-28`,
  `knowledge-index.md:1396-1400`) now say "every failure it can catch — the connect onwards" and
  keep the hard-kill residue named. The parametrized test is **not vacuous in either arm**: SQLite
  creates the file at connect, so the pragma-failure arm fails after the file exists, and against
  the round-1 code both arms would have gone red (the old `try` wrapped neither path). The
  connection-setup arm's monkeypatch of `Connection.execute` does not break the handler, which
  only closes and unlinks.
- **Finding 2:** measured before choosing, mechanism stated (`+` precedes `.`), contract stated
  once in `clock.py`, pinned by `tests/test_clock.py` (the different-length tripwire at line 34 is
  what keeps the permutation test from going vacuous if the format ever becomes fixed-width),
  `runs.py` recast as arithmetic-not-distrust, and `reporting.files_remaining`'s `walked < started`
  (`reporting.py:152`) matches §8.5's stated rule (`knowledge-index.md:1613-1614`). Verified the
  ordering property independently: fixed-width most-significant-first fields, fixed `+00:00`
  offset, and the omitted-microseconds spelling sorting first is where a zero belongs.
- **Finding 3:** `test_creation_refuses_a_path_that_is_already_taken_and_leaves_it_alone`
  (`tests/test_knowledge_database.py:204-226`) writes a row, captures bytes after close, asserts
  byte-identity after the refusal — and the refusal at `database.py:206-207` runs before
  `ensure_store_dir`, so nothing is mutated first. A regression running cleanup on this branch now
  fails the test.
- **Finding 4:** `ddl.py:22-27` — "not merely", both tests named, with the reason both exist.
- **Finding 5:** the registry fixture is exactly 36 characters (`test_knowledge_registry.py:190`),
  the three-branch parametrization now genuinely reaches all three refusals, `meta.parse_id`
  re-raises in its own words with the cause kept (`meta.py:283-294`), and
  `TestTheIdParserSpeaksWithOneVoice` (`test_knowledge_meta.py:189-213`) asserts both the word
  "uuid" and the offending value's repr in every message — assertions the pre-fix
  `invalid literal for int() with base 16` message fails, so the test is pinned against the defect
  it found.

**On the brief's question 2 — the contract was the right call, and the strongest argument for it
is one the code already contained.** `SELECT MIN(a.at)` in `zikaron/core/signals/dedup.py:48,52`
and `zikaron/core/signals/repair.py:58` are lexicographic minima over stored timestamps computed
*inside SQL*, where parsing is not available — so the system depended on string order agreeing
with temporal order before M20 existed, and having `files_remaining` parse would not have removed
the dependency, only hidden the one place it was visible. Stating the contract once, with the
mechanism and a pin, is strictly better. (`repair.py:22-27`'s note about SQLite's `datetime()`
reformatting is consistent with, not against, the contract: it warns about mixing *formats*, and
the contract is precisely that there is one format.)

**On question 3 — no vacuous test found in rounds 2-3's additions.** Each new test was checked
against the pre-fix code it guards (above), and the clock suite carries its own anti-vacuity
tripwire.

### Findings

1. **[IMPROVEMENT] Round 2's own fix introduced a false universal in `runs.py`, and `clock.py`'s
   caller enumeration undercounts the same way — both falsified by the signals package.**
   - `zikaron/core/consolidation/runs.py:21-22`: "it is **the only place in the system** doing
     *arithmetic* on a stored timestamp" is false. `zikaron/core/signals/horizon.py:26-32`
     (`deadline`) parses a stored event's `at` and adds `signal_horizon_days` — arithmetic on a
     stored timestamp, in a module whose own docstring says "This module is the one place the
     deadline arithmetic lives." This wording is the one round 2 suggested, so the error entered
     through the review; the corpus grep the project mandates after an edit would have caught it.
     **Fix:** drop the universal — e.g. "**The lease arithmetic lives here, with the lease.** It
     parses rather than comparing strings — not because string order is untrustworthy (`core.clock`
     states and pins the opposite) but because a lease is a start plus a duration, and adding
     seconds is not something ordering can do for you." (Or scope it: "the only *lease* arithmetic".)
   - `zikaron/core/clock.py:16-19`: "**Two callers** rely on it in different ways" undercounts.
     The `MIN(a.at)` aggregations above rely on the ordering contract directly — a lexicographic
     minimum over `at` strings is only the earliest instant *because* of it — and they are the one
     reliance that structurally cannot switch to parsing. There is also a small irony worth
     removing: the module's closing paragraph says "A neutral home has nothing to enumerate", two
     paragraphs after enumerating its callers. **Fix:** recast from a count to a classification —
     e.g. "Callers rely on it two ways: Python comparisons (`reporting.files_remaining` compares
     its walk's completion against its build's start with `<`) and SQL, where every `MIN`/`MAX` or
     `ORDER BY` over a stored `at` is this contract applied inside the database, with no option to
     parse. The consolidation lease and the signal horizon instead parse, because they do
     arithmetic." That also imports the strongest argument for the contract into the module that
     states it.

2. **[NITPICK] `tests/test_clock.py:75-76` asserts a monotonicity `datetime.now(UTC)` does not
   promise.** `timestamp() <= timestamp()` can go red on a backwards clock step (NTP correction,
   VM resume) landing between two adjacent calls — vanishingly rare, but it is a red for reasons
   unrelated to the change under test, which FINDINGS' own M20 entry ("a gate that can go red for
   reasons unrelated to the change under test is the thing this project has already decided is not
   a gate") argues against adding. Either delete it (nothing in the contract needs it) or keep it
   with a comment naming the accepted flake window.

3. **[NITPICK] `tests/test_clock.py:44-48` names its permutation parameters `earlier`/`later`, and
   half the generated pairs violate the names.** `itertools.permutations` yields both orders; the
   biconditional assertion is symmetric so coverage is right, but the names claim a relationship
   the fixtures do not have. Rename to `first`/`second` (or `a`/`b`).

VERDICT: NEEDS_CHANGES

## Round 4 — 2026-09-15

**Summary judgment.** All three round-3 fixes are correctly implemented, and the timestamp story's
*operative* text — the classification in `clock.py`, the recast lease paragraph in `runs.py`, the
signal SQL comments, `reporting.files_remaining` — is now one consistent account. But the brief's
claim "I then ran the corpus grep for the claim rather than the phrasing" is falsified by my own
grep: the round-2 caller-count survives in three sentences the round-3 edit did not touch — the
header sentence of `clock.py`'s own docstring, the `timestamp()` function docstring twenty lines
below the fix, and the first line of the test file that pins the contract — and FINDINGS.md's M20
entry (line ~529) records that undercount as *corrected*. Fifth consecutive round, same mechanism:
the fix landed in the paragraph the finding quoted, and the sentences around it kept the pre-fix
world. Three phrase edits from approval; nothing in code, tests or design is wrong.

### Round-3 fixes verified (against the files)

- **Finding 1a (`runs.py`):** the universal is gone; lines 21-26 are the agreed wording, and the
  added tail ("parsing then makes the comparison independent of the format as well, the cheaper
  half of a step taken for another reason") is accurate and non-contradictory.
- **Finding 1b (`clock.py`):** the classification (lines 16-26) is correct and complete — I
  verified its census: exactly one Python string `<` on stored timestamps in the codebase
  (`reporting.py:152`), and the SQL kind is real (`signals/dedup.py:48,52`, `signals/repair.py:58`,
  all `MIN(a.at)`), with the "cannot be rewritten to parse" characterisation right. The irony is
  gone; the closing paragraph's "a new caller is one of these two kinds" reads correctly with
  arithmetic already named as the exception two paragraphs up.
- **Finding 2:** the monotonicity assertion is deleted; nothing in `test_clock.py` can go red on a
  clock step. The remaining `test_the_clock_produces_that_format` asserts format properties only.
- **Finding 3:** parameters renamed `first`/`second` (`test_clock.py:44`), with the docstring
  giving the right reason (the biconditional must hold with the arguments in either order).
- The signal SQL comments are consistent with the contract, checked both ways: `dedup.py:37-43`
  and `repair.py:22-31` justify the Python deadline test by *format mixing* with SQLite's
  `datetime()` output — never by distrust of string order — which is exactly compatible with
  `clock.py`'s one-format contract.

### On the brief's question 2 — `horizon.py:8` stands, but for a narrower reason than the brief gives

The brief's defence — "scoped to deadlines, and the lease is different arithmetic" — is not quite
the right one, because the lease *is* a deadline and `lease_expiry` (`runs.py:112-119`) is deadline
arithmetic of exactly `deadline()`'s shape (parse, add a `timedelta`, `isoformat()`); the codebase
itself calls `Run.has_lapsed` a "deadline comparison" twice (`horizon.py:14`, `repair.py:28`). What
actually makes line 8 true is the anaphor: "closes it with **a deadline** measured from the earlier
event … the one place **the** deadline arithmetic lives, *since both joined-pair signals … measure
it from the same kind of earlier event*" — the definite article and the since-clause bind the claim
to the `signal_horizon_days` deadline, and the module explicitly acknowledges the lease's
comparison as living elsewhere. True as written and scoped; no change required. (Optional, untagged:
"the one place *this* deadline's arithmetic lives" would make the scope skim-proof for one word.)

### Findings

1. **[IMPROVEMENT] The round-2 caller-count survives in three sentences around the round-3 fix,
   and FINDINGS.md records it as corrected.** The claim round 3 flagged — a count of who relies on
   the contract — was fixed in `clock.py`'s classification paragraph and left standing in other
   words at:
   - `zikaron/core/clock.py:7`: "stated here because **two callers** depend on it and **neither**
     should have to rediscover it" — the module's own lines 16-22 name one Python call site plus
     the signal queries across two modules, and line 32 says callers sort into "two kinds",
     implying more than two of them. Fix: "stated here because more than one caller depends on it
     and none of them should have to rediscover it" (or "…because its callers should not each have
     to rediscover it").
   - `zikaron/core/clock.py:44`: "and for **the one caller that parses** instead" — the module
     docstring's own arithmetic paragraph (lines 24-26) names two: the consolidation lease and the
     signal horizon (four parsing functions across `runs.py` and `horizon.py`). Fix: "and for the
     arithmetic callers that parse instead."
   - `tests/test_clock.py:3`: "**Two callers** order stored timestamps with a plain `<`" — exactly
     one caller uses a plain `<` (`reporting.py:152`); the other reliance is `MIN` aggregates
     inside SQL, which is neither "two" nor "`<`". Fix: "Stored timestamps are ordered without
     parsing — by a plain `<` in Python and by `MIN`/`ORDER BY` inside SQL."
   This matters beyond hygiene because `FINDINGS.md` line ~529 states the "two callers" undercount
   was corrected — an always-loaded file asserting a fix the module's opening sentence still
   contradicts, which is the M13-hash shape this corpus documents.

2. **[NITPICK] "Every stored time … comes from here" is falsified to the letter by `lease_expiry`,
   in both files that state it.** `clock.py:42` ("Every stored time in every database Zikaron owns
   comes from here") and `runs.py:26` ("Every timestamp still comes from `core.clock.timestamp`,
   so there is one format"): `consolidation_run.expires_at` is a *stored* timestamp manufactured
   by `lease_expiry`'s parse-add-`isoformat()` (`runs.py:119`, stored at `runs.py:219`), not by
   `timestamp()`. The claimed consequence (one format) does hold — the derivation is closed under
   the format: aware-UTC in, fixed `+00:00` out, and a zero-microseconds input stays
   zero-microseconds under whole-second addition — but that preservation argument is stated
   nowhere, and it is what the universal actually rests on. Fix, one clause each:
   `clock.py:42` → "Every stored time in every database Zikaron owns comes from here or is derived
   from one of these by parse-add-`isoformat()` (the lease's `expires_at`), which preserves the
   format"; `runs.py:26` → "Every timestamp it stores is either a `core.clock.timestamp` output or
   `lease_expiry`'s parse-add-`isoformat()` of one, so there is one format."

VERDICT: NEEDS_CHANGES

## Round 5 — 2026-09-15

**Summary judgment.** Both round-4 findings are fixed completely — in the quoted sentences *and*
their neighbours, which is the first round of this series where that is true — and the census
claims the new prose makes were re-verified against the codebase rather than against the brief:
every one holds. FINDINGS.md's M20 entry now records what actually happened, including the false
"I ran the grep" report, and asserts no fix the code contradicts. The self-caught drift (the
"two kinds" closing sentence) was a real instance of the failure class and the fix is right.
Nothing substantive remains; the two residual observations below are recorded so the trail shows
they were weighed, and neither warrants a round.

### Round-4 fixes verified (against the files, and the claims re-derived from the codebase)

- **Finding 1, all three sentences.** `clock.py:7` now says "several callers … none of them";
  `clock.py:49-53` (`timestamp()`'s docstring) states the comes-from-here-or-derived form with the
  lease named as the only derivation and the arithmetic callers plural; `tests/test_clock.py:3-4`
  states the two ordering mechanisms with no count and no plural-`<` claim. Grepped the corpus for
  the *claims* (caller counts about the clock, "only place", "comes from here", "compared as
  strings"): no survivor. `runs.py:148`'s "two callers want different things" is about run readers,
  not the clock — correctly left alone.
- **Finding 2, plus the census behind it.** `clock.py:29-33` states the closure argument (parse an
  aware-UTC instant, add whole seconds, re-format ⇒ same shape, microseconds present or absent
  alike — analytically sound: a whole-second `timedelta` cannot change the microsecond field, and
  `fromisoformat` of a `+00:00` offset round-trips to `+00:00`); `runs.py:26-28` states the
  same closure for what this module stores. **"The only such derivation" is true**: the only two
  `parse-add-isoformat()` producers in `zikaron/` are `lease_expiry` (`runs.py:121`; stored by
  `create` at 210-221 and `refresh_lease` at 272-275, both writing `expires_at`) and
  `horizon.deadline` (`horizon.py:32`), whose output is consumed only inside `has_passed`
  (`horizon.py:47`) and stored nowhere. **"Every stored time comes from here" is true**: the only
  `datetime.now` in the package is `clock.py:55`; every stored-instant writer (`memory.py` ×8,
  `lifecycle.py:271` for the registry's `created_at`, `runs.py` via `timestamp`/`now()`) draws from
  it; and the knowledge `meta` stores no instants at creation — `meta.py:131-133` makes the three
  scan keys' absence the normal state, so nothing writes them until M21, which the classification
  already covers.
- **The self-caught drift is fixed correctly.** `clock.py:39-40` now reads "a new caller orders (in
  Python or in SQL) or it does arithmetic", consistent with the arithmetic-exception paragraph
  above it. That the fix pass caught its own freshly-introduced contradiction by grepping for the
  claim is the mandated procedure working, and worth the FINDINGS sentence it got.
- **FINDINGS.md's M20 entry (lines ~535-546) is accurate in substance**, which is what the brief
  asked to be checked hardest: it records the grep that was reported but not run, the earlier
  revision asserting a fix the module contradicted, the three surviving sentences by location, and
  the "a claim like any other" lesson. Nothing in the entry asserts a fix the code now contradicts;
  the ~8M-pairs figure (line 512) is consistent with `clock.py`'s "several million" (the test pins
  a smaller seeded sample, which is a pin, not the measurement).
- `memory.py` carries no leftover clock enumeration (checked; its docstring no longer mentions the
  format at all), so `clock.py:35-38`'s account of the relocation's reason is accurate about the
  present, not only the past.

### Judged and found sound (recorded so a later reader does not re-litigate)

- **`tests/test_clock.py:3` "ordered without ever being parsed" against `Run.has_lapsed`, which
  parses and compares.** Weighed as a possible sixth instance of the surviving-universal class and
  judged not one: the em-dash scopes the claim to the two named mechanisms, and the corpus's own
  established classification (`clock.py:25-27`, `runs.py:21-26`) buckets the lease's parsed
  comparison under the arithmetic exception — stated in both places, with `runs.py` explicitly
  calling the parsed comparison the incidental half of a step taken for arithmetic. The sentence is
  true of the reliance the test exists to pin.
- **`ORDER BY created_at` in `grouping.py:146` and `groups.py:45`** are two more SQL reliances on
  the ordering contract beyond the `MIN(a.at)` three. `clock.py:19-20`'s "every `MIN`, `MAX` or
  `ORDER BY` over a stored `at`" is stated generically and its example is an example, not an
  enumeration, so these falsify nothing — and they further strengthen the round-3 argument that the
  contract predates M20.

### Findings

None, at any tag level. Two observations, **no action required and no round owed** — recorded only
so the trail shows they were seen rather than missed:

1. FINDINGS.md line ~543, "a fix that the module's own first sentence contradicted": the
   contradicting sentence was the *contract paragraph's* opening sentence (pre-fix `clock.py:7`),
   not the module's first sentence (line 1, which was always innocent). The parallel locator three
   lines earlier is precise, the substance of the entry is right, and the imprecision descends from
   my own round-4 summary's "the module's opening sentence" — if the file is ever touched for other
   reasons, "the module's own contract sentence" is the two-word repair.
2. Round 4's untagged optional (`horizon.py:8` "the one place *this* deadline's arithmetic lives")
   was, correctly, not taken — it was offered as optional and the line is true as written.

VERDICT: APPROVED
