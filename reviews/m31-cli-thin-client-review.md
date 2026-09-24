# M31 review — the knowledge CLI becomes a thin client, and the schema learns to move

The brief is `design/build-plan.md` §M31 and it is normative for scope, done-when and the fence.
This file is where review findings are appended.

## What changed, by claim

1. **`zikaron knowledge`'s six verbs are RPC calls.** `zikaron/knowledge/client.py` is new;
   `zikaron/knowledge/main.py` was rewritten around it. `knowledge/scope.py` keeps only the indexer
   as a caller. The claim this buys: the command manages corpora in a project that has **never had
   a store**, because the service creates one and `Store.open` cannot.
2. **`meta.schema_version` is a range** (D37, new). `core/store/migration.py` is new; version 2
   widens `event.client_kind`'s `CHECK` to admit `ClientKind.CLI`. Only `service/context.py`
   migrates.
3. **Two new error codes.** `store_unavailable {operation, cause}` carries a driver/OS failure that
   previously became `internal_error` with an empty payload; `knowledge_base_dangling {name}` was
   reachable only through the new `knowledge_unlock`.
4. **`ErrorSpec.disposition`** declares refused-vs-failed per code, so the CLI and `zikaron-mcp`
   cannot disagree about whether a caller has a move.
5. **`knowledge_unlock` is an eighth RPC method with no MCP tool**; `refresh --wait` blocks until
   builds end, reporting progress. Both are operator business, not agent business.
6. **`rpc.parse_response`** is shared by both clients; `mcp/errors.py` now uses it.
7. **A conftest autouse reaper** kills any service a test leaves running.

## What I already checked, so the round need not

- `./check.sh` green (3126 passed) and 0 leaked services.
- **Perturbation table walked** before this round — `scratchpad/perturbation.md`, axes: where each
  feature can be interrupted × what may change underneath × which values move. It found the
  global-appearance-deadline hang (fixed, mutation-verified: the old logic *hangs* rather than
  failing) and one predicted defect that **did not exist** (a concurrent migration does not break,
  because `DROP TABLE` takes its indexes with it) — the docstring and test were corrected to claim
  only what is true.
- **Mutation-verified**: the per-corpus deadline, and the in-transaction version re-read.
- **Enum audit**: every `ClientKind` consumer names a specific member; only `_KNOWN_CLIENT_KINDS`
  derives from the set, which is the intended widening. Link-coverage queries name MCP/HOOK.
- Counts deleted rather than incremented where they went stale.

## What I most want challenged

- **Is D37 justified at all?** `schema.md`'s prior rule bumped only when an *old binary would read a
  new store wrongly*, and by that rule version 2 does not qualify. I argue the binding direction is
  a *new* binary meeting an old store, and rewrote the rule to state both. If that reasoning is
  wrong, the whole migration is unnecessary and the `CHECK` should just widen silently.
- **The prose rule in `core/errors.py`.** I revised it three times. It now reads: a caller branches
  on the code, never on wording, which is what makes a payload field safe to hold a sentence; what
  is forbidden is a distinction a caller must *act* on arriving only as prose. Check it against
  `knowledge_base_busy.holder`, `store_unavailable.cause` and the build result's `reason`.
- **`--wait`'s asymmetric deadline**: unbounded once a build is demonstrably running, bounded (30 s,
  per corpus) before one appears. Is the unbounded half defensible?
- **The conftest reaper's blast radius.** It sweeps only `$XDG_RUNTIME_DIR` and does nothing when
  that is unset, because the fallback is `/tmp/zikaron-<uid>` — a real shared path where a
  developer's own service may be listening. Is that reasoning airtight?
- **`_InProcessClient` in `test_knowledge_cli.py`** subclasses `KnowledgeClient` and holds no
  connection. Only the socket is skipped; real handlers and real serialization run. Is that a fair
  test double, or does it hide something the port should have to prove?

---

## Round 1 — 2026-09-24

### Summary judgment

The port itself is sound: every verb is an RPC call, `scope.open_store` has one caller, the
migration is transactional and idempotent by re-read, the frozen-v1 fixture makes the migration
tests real, and the design corpus was moved with the code rather than after it. Two things stop it
shipping as-is. `refresh --wait` does not honour its own contract in the one mixed case its test
exists to cover — and that test's assertion is vacuous, so the gate is green over a defect the test
message describes. And the prose rule for payload fields is stated three different ways across the
brief, `FINDINGS.md` and `core/errors.py`, with the code following the one the normative brief does
not state. Everything else is an improvement or a freshness fix.

### Findings

1. **[BLOCKER] `_await_builds` abandons the builds that did start when another never appears, and
   the test covering that case asserts the opposite of what its message says.**
   `zikaron/knowledge/main.py:412-418`: on the appearance deadline it prints the absent corpora and
   `return True` — without calling `_report_terminal_states` and without waiting on the entries still
   in `pending` that *had* appeared. So in a sweep where corpus A is mid-build and corpus B's spawn
   died, the command returns at 30 s with A still running, which is precisely the "step ends with an
   indexer still running" hazard the `--wait` help (`:150-155`) and `knowledge-index.md:2429` promise
   to remove; and where A already finished, its `built 'A' is ok` line is never printed.
   `tests/test_knowledge_cli.py:1149-1174` is the test for this, and its final assertion is
   `assert "built     'docs' is ok" not in printed.err` with the message *"the corpus that did build
   must still be reported as having built"*. `_report_terminal_states` writes `built` to **stdout**,
   so the assertion is true whether or not the line was ever printed — and with the code as written
   it is not printed. Trace: poll 1 marks docs done (not pending) and runbooks pending-but-absent;
   nothing calls `_report_terminal_states` before the deadline branch returns.
   **Fix (code):** keep a `dead: set[str]`; on the deadline branch add the absent names to it, print
   them, and `continue` rather than return; compute `pending` over `names` minus `dead`; when
   `pending` is empty, `return _report_terminal_states(reports, [n for n in names if n not in dead])
   or bool(dead)`. **Fix (test):** `assert "built     'docs' is ok" in printed.out`, which fails on
   the current tree and passes after the change — that is the mutation check the round-1 summary
   did not list.

2. **[BLOCKER] Three statements of the payload-prose rule, and the code follows the one the
   normative brief does not state.** `design/build-plan.md:3483-3488` (normative): *"no payload
   field is ever filled from a Zikaron exception's own `str()`"*. `FINDINGS.md:239-242`: *"A payload
   field may hold prose only when the prose originated outside Zikaron."* `core/errors.py:12-21`
   and `architecture.md:1942-1945`: a caller branches on the code, so display-only prose is fine.
   The code does the third: `serialize_knowledge.py:183` fills `reason` with `str(entry.refusal)`,
   which for `already_indexing`, `no_database` and `root_missing` is `str(KnowledgeError)` — a
   Zikaron exception's own `str()`, prose that originated inside Zikaron. Meanwhile
   `dispatch_knowledge.py:171-174` still argues the brief's line (*"filling one from `str(error)`
   would put a whole sentence there — after which the message could no longer be reworded"*), which
   is the reasoning `errors.py` rejects. **On the rule itself:** the `errors.py` formulation is the
   right one — it names the property that matters (nothing automated keys on wording) instead of a
   proxy for it — and `knowledge_base_busy.holder`, `store_unavailable.cause` and the build result's
   `reason` all pass it. What it lacks is a sentence saying it governs **result** fields as well as
   error payloads, since `reason` is not in the error table and a reader of the module docstring
   would not know it applies there. **Fix:** amend `build-plan.md:3483-3488` to state the
   `errors.py` rule (the brief is normative, so it must say the rule the code follows); replace
   `FINDINGS.md:239-242`'s sentence with the same rule; reword `_translated`'s docstring to *"every
   payload value a caller might act on comes from the exception's own field; a sentence a person
   reads is rendered from those fields, never parsed"*; and add to `errors.py`'s docstring that the
   rule covers result fields (`KnowledgeBuildResult.reason`) too.

3. **[IMPROVEMENT] The migration step derives its DDL from the live schema, which is the wrong
   property for a step and the same class D37 exists to avoid.** `migration.py:47-52` builds
   `event_migrated` from `ddl.event_statement()` and recreates `ddl.EVENT_INDEXES` — whatever those
   say *now*. Step 2 therefore produces "the current `event`", not "version 2's `event`". The day a
   later step changes `event` (add a column), `INSERT INTO event_migrated SELECT * FROM event` from
   a v1 store fails on column count and every v1 store refuses to migrate. The frozen `_NARROW_EVENT`
   in `test_store_migration.py:20-37` would catch it, so the trap is armed rather than silent — but
   `ddl.py:78-80`'s comment (*"One body, so the migrated table and the created one cannot drift"*)
   claims the derivation as a virtue, and `schema.md` §"Migration posture" says nothing about whether
   a step's DDL is frozen or derived. **Fix:** inline version 2's `CREATE TABLE event ...` and its
   five index statements as literals in `migration.py` (exactly as the test freezes version 1's),
   add one test asserting the literal equals `ddl.event_statement()` *today* with a docstring saying
   the day it fails is the day `event` moved and the literal must stay put, and state in §"Migration
   posture" that a step's DDL is a historical artifact. Then `_EVENT_BODY`'s parameterization and
   the `ddl.py:78-80` comment can go. Minimum acceptable alternative: keep the derivation and write
   the rule in `schema.md` that the change which next touches a rebuilt table must first freeze the
   earlier step's text.

4. **[IMPROVEMENT] The declared disposition is ignored on both client-side render paths.**
   `main.py:190-191` prints `failed:` for every `ZikaronError` raised while establishing the
   connection — `REINDEXING` and `BAD_CONFIG` from the identity read are `REFUSED` by declaration
   and would read `refused:` had the same code arrived over the wire. `scope.py:124-125`, still the
   by-hand indexer's renderer and named in done-when 1 (*"`scope.execute` renders from that rather
   than from an exception type"*), prints `refused:` for every `ZikaronError` — `SCHEMA_INCOMPATIBLE`
   is `FAILED`. Both should print `ERROR_SPECS[error.code].disposition.value`. Same site: `_execute`
   does not catch `AmbiguousMutationError` where `mcp/primary.py:63-70` does, so a service dying
   mid-request gives a person a traceback rather than `failed: …`.

5. **[IMPROVEMENT] Two bare literals where the enums are one import away.** `main.py:551`
   `_CONFIRM_REQUIRED: Final = -32043` violates `errors.py:4-6` (*"no call site anywhere may name a
   bare integer"*) and `client.py:20` already imports `ErrorCode`; use
   `ErrorCode.KNOWLEDGE_CONFIRM_REQUIRED`. `client.py:24` `CLIENT_KIND: Final = "cli"` should be
   `ClientKind.CLI.value`, with the one-line test `test_hook_envelope.py:77` already has for the hook
   — done-when 4 says the CLI's envelope carries `cli`, and today nothing asserts the CLI's constant
   against the enum (`_InProcessClient` bypasses `envelope()`, and the integration file does not
   inspect it).

6. **[IMPROVEMENT] Done-when 1 is not met as written.** It requires *"every verb"* run against a
   project with no service running. `tests/test_knowledge_cli_integration.py` runs `add` (`:87`),
   `list` (`:120`), `status` (`:152`) and `refresh --wait` (`:178`); `rename` and `remove --yes`
   never meet a real service. One chained test — add, rename, remove --yes — closes it; each is the
   same `KnowledgeClient.call`, so the risk is low, but the brief's sentence is explicit.

7. **[IMPROVEMENT] A relative `--project` is handed to a long-lived service unresolved.**
   `main.py:215-217` returns `args.project` as typed; `mcp/main.py:56` derives from `Path.cwd()`
   and the hook from the payload's `cwd`, so this is the first client that can give the service a
   relative store dir. `service/main.py:416` does not resolve it, `context.py:108-114` derives
   `store_directory` from it, `paths.scope_of` inverts it, and `detach.py:43` stringifies it into the
   `foreground` argv the CLI prints — a line that acts on a different project when pasted from
   another directory. The store's corpus roots are safe (`roots.py:46` resolves), so the exposure is
   the service's own paths and that printed command. `return project.absolute()` at `main.py:217`.

8. **[IMPROVEMENT] Claims the change falsified, still standing:**
   - `README.md:98` (indexer row): *"or by the `zikaron.knowledge` command when you do"* — the
     command no longer spawns anything; the service does, for both surfaces.
   - `design/architecture.md:1824-1826`: knowledge verbs *"reach only `bounds` and the
     `knowledge_base_*` codes"* — now also `store_unavailable`.
   - `design/architecture.md:1974-1983`: *"Any other driver-level failure during a read … gets no
     Zikaron code … The rule stated once so no read path decides it locally"* — `knowledge_search`
     is a read and now answers `store_unavailable` via `_naming_the_store`. Scope the paragraph to
     the memory verbs and state the asymmetry, or the rule is false for half the surface.
   - `zikaron/core/store/meta.py:18-20`: *"Compared against `ERROR_SPECS[SCHEMA_INCOMPATIBLE]…`'s
     fixed `supported` value by a test"* — `supported` is no longer fixed; `test_store.py:57-67`
     compares to `SUPPORTED_SCHEMA_VERSIONS`.
   - `zikaron/core/events.py:63` names `test_store_ddl.py`; the file is `tests/test_ddl.py:109`.
   - `design/knowledge-index.md:75-76`: the CLI *"adds `refresh --force-unlock`"* — and `--wait`,
     which §8.2 already lists as the second exception.
   - `design/knowledge-index.md:2468`: `--force-unlock` is *"the only operation with no MCP
     twin"* while §8.2:1315-1321 says *"Both are deliberate exceptions"*; say *the only method
     with no tool*.

9. **[IMPROVEMENT] The reaper's blast radius rests on the environment at teardown, not on the
   directory the suite created.** `conftest.py:370` reads `os.environ["XDG_RUNTIME_DIR"]` after the
   test. The `/tmp` fallback reasoning (`:362-367`) is right. What it does not cover: a test that
   sets the variable through `os.environ` — the mechanism `_runtime_dir_is_never_the_developers`
   itself uses at `:120` — and leaves it pointed at the real runtime dir would have the reaper
   SIGKILL whatever answers `health` there, which can be the developer's own service.
   `monkeypatch.setenv` is safe (its teardown precedes the autouse fixture's), `os.environ` is not.
   **Fix:** have the session fixture store its directory in a module-level variable and have the
   reaper sweep that path, ignoring the environment; two lines, and the reasoning becomes airtight.

10. **[IMPROVEMENT] `_InProcessClient` is a fair double with one gap worth closing.**
    `test_knowledge_cli.py:121-133` returns `result.as_json()` and `dict(error.data)` as Python
    objects; the wire would JSON-encode and decode them. A payload carrying a `Path`, an enum, a
    tuple or a non-string key passes here and changes shape or fails on the wire. Round-trip both
    branches through `json.loads(json.dumps(...))`. What it cannot prove — that `envelope.resolve`
    accepts `kind: "cli"` — the integration file does, and that file is in the default suite, so
    that half is fine.

11. **[IMPROVEMENT] `schema.md` argues both sides of the cost version 2 pays, without saying so.**
    §"Additive tables" (`:367-370`) declines a bump for `knowledge_bases` because *"every older
    build [would] refuse the store outright … the wrong [answer] for a schema it can [read]"*.
    Version 2 does exactly that to `0.1.0`: an old binary reads a widened `event` correctly and is
    refused anyway. §"Migration posture" (`:1463-1469`) explains why the bump is needed but never
    acknowledges that it pays the price §"Additive tables" refused. One sentence there — that a
    recorded fact was judged worth a refusal by a one-day-old release with one user, which is D37's
    own rationale — stops a reader of the first section concluding the second is wrong. With that,
    D37 is justified: the "widen silently" alternative is introspection on every open, and a
    binary that cannot tell which shape it holds is the defect a version exists to prevent.

12. **[NITPICK]** `main.py:240` `_entries(payload)[0]['name']` where every other site unpacks
    `(entry,) = _entries(payload)`; an empty list is a defect and should say so the same way.

13. **[NITPICK]** `main.py:389-392` *"The bound is per corpus, not per call"* — the appearance
    **flag** is per corpus; `deadline` is one instant per call. Say that, since a reader checking
    the claim against the code will see one `deadline`.

14. **[NITPICK]** `migration.py:4-5` *"why the version moves in both directions"* reads as up-and-
    down migration; `schema.md:1456` says it better — *when a binary at either version would use
    the store wrongly*.

15. **[NITPICK]** The pre-verified list records `./check.sh` only; done-when 9 names the matrix.
    A PR satisfies it per `CLAUDE.md`, so this is a note for the summary, not a gap.

### On the five things you asked to have challenged

- **D37:** justified — finding 11 is the one sentence the rationale is missing.
- **The prose rule:** the `errors.py` formulation is right; finding 2 is that the corpus does not
  yet agree with it.
- **`--wait`'s asymmetric deadline:** defensible. The unbounded half rests on a live pid, so a
  build that *hangs* rather than dies is bounded only by the caller's own timeout — which is what
  the docstring says. Finding 1 is not about the asymmetry; it is about the bounded half returning
  before the unbounded half is over.
- **The reaper:** the `/tmp` reasoning is airtight; the environment read is not (finding 9).
- **`_InProcessClient`:** fair; finding 10 closes the one thing it hides.

VERDICT: NEEDS_CHANGES

---

## Round 2 — 2026-09-24

### Summary judgment

Every round-1 item is applied as described, and I re-read each against the tree rather than the
list: `_await_builds` now records a dead spawn and keeps waiting (`main.py:407-441`), the assertion
is on stdout, the prose rule is stated once and pointed to, the step's DDL is frozen with the alarm
test, both renderers read `disposition`, the reaper sweeps the session's own path, the double
round-trips through JSON, and the six stale passages are true of the code now. One new defect stops
it shipping: `refresh --wait` treats a corpus that is *already* being built as nothing to wait for
and exits 0 with that indexer running — and README's own provisioning sequence (`add`, then
`refresh --wait`) lands on exactly that case whenever the `add`'s indexer has taken its lock, which
today it avoids only by a race the integration test's docstring describes. The rest is one dropped
measurement, one test gap against done-when 6, and small items.

### Findings

1. **[BLOCKER] `refresh --wait` exits 0 at once on `already_indexing`, with the build it did not
   wait for still running — and the documented `add` → `refresh --wait` sequence reaches that case.**
   `main.py:344-356`: `building` collects only `started`; `already_indexing` makes `_report_build`
   print *"already being built; nothing was queued"* (`:533-535`) and return `False`; `if not
   building: return 1 if failed else 0`. So a corpus whose lock is held by a live local indexer is
   answered `0` immediately. The help (`:154-155`), `knowledge-index.md:2429-2433`, `README.md:467-470`
   and the brief (`build-plan.md:3562-3575`, *"the build is over when its lock is gone"*) all promise a
   step that does not end with an indexer running; on this path it does. **How a script gets there:**
   README (`:460-470`) says `add` starts a build and tells a CI step to use `refresh --wait`, and `add`
   has no `--wait` — so `add` then `refresh --wait` is the only sequence a script can write. The `add`'s
   indexer takes its lock only after Python start and the model load (`indexer/main.py:88-91`:
   `prepare`, then `build_settings` loads the encoder, then `lifecycle.refresh` → `scan._begin`,
   `scan.py:190-208`, which writes lock and mark together). Inside that one-to-three-second window
   `knowledge_refresh` sees no lock, spawns a second indexer, and the wait tracks whichever wins the
   lock race — it works, at the cost of a wasted model load, and
   `tests/test_knowledge_cli_integration.py:188-193` says as much (*"puts two builds on one
   corpus"*). After the window — a slow shell, a `sleep`, any step in between — the answer is
   `already_indexing`, the command exits 0, the step ends, the container kills the indexer, and the
   lock is stranded on a hostname no later container can probe: the exact chain the brief's
   §"Waiting, and the container case" says `--wait` removes. `tests/test_knowledge_cli.py:792-808`
   pins the exit-0 for the **non**-`--wait` case only; nothing covers `already_indexing` with `--wait`.
   **Fix (code):** in `_refresh`, when `args.wait`, collect `already_indexing` names into a second
   list `running` and pass it to `_await_builds(client, building, running=running, before=before)`.
   For a name in `running`, seed `appeared` with it and use a lock-only predicate
   (`isinstance(lock, dict) and lock.get("live") is not False`) — its mark predates `before`, so
   `_still_building`'s mark test would say *not begun* forever. One guard: a holder `status` reports
   with `live: None` is a lock this wait can never see released, so on the first poll print
   `failed    <name>: its build lock is held by another host, which this wait cannot see released;
   clear it with --force-unlock`, add it to `dead`, and fail — never wait unbounded on it. Under
   `--wait` print `building  'docs' is already being built; waiting for it` rather than *nothing was
   queued*. **Fix (tests):** (a) `_hold_the_lock(project, pid=os.getpid(), host=lock.this_host())`,
   then `refresh docs --wait` with a poll-counting `_InProcessClient.call` (the pattern at
   `:1240-1260`) that `_release_the_lock`s and `_mark_scan_complete`s on the third poll → exit 0,
   `built     'docs' is ok` in stdout, `polls >= 3` — fails on the current tree at the exit code;
   (b) `_hold_the_lock(project, pid=1, host="elsewhere")`, `--wait` → exit 1, stderr names
   `--force-unlock`, and returns within one poll. **Fix (prose):** the help at `:154`,
   `knowledge-index.md:2429` (*"the builds that call started"* → every build against the named
   corpora, one already running when the call arrived included), `README.md:467`, `FINDINGS.md:229`,
   and `_await_builds`'s docstring. **Minimum acceptable alternative** if waiting on a foreign
   holder is judged too much surface: exit 1 with *"already being built and not waited for"* —
   but never exit 0 with a lock held.

2. **[IMPROVEMENT] The first `zikaron knowledge` call in a project with a cold model cache can
   fail with *no server became reachable* while the service is still fetching, and nothing says so
   any more.** `connection.py:387-434` runs the identity read and then `connect_start_if_absent`,
   whose deadline is `lifecycle.py:39` `_HEALTH_POLL_DEADLINE_SECONDS = 10.0` from spawn and whose
   failure is `:462`'s `ConnectionError`, which `main.py:197-203` renders as `failed: no server became
   reachable …`. The socket binds only after the store exists, and creating one needs the artifact;
   on a cold cache that is the 64 MB fetch. The FINDINGS paragraph this milestone replaced measured
   it (health answered 3.74 s after the service's first log line, the fetch at most 3.30 s of that)
   and stated the consequence — the first call reports no reachable server while the service keeps
   fetching, and the second succeeds. The new §M31 block dropped it, and no design document carries
   it (`grep -rn 'no server became reachable\|slower network' design/ FINDINGS.md` is empty). The
   scenario is the one `--wait` was built for: a fresh CI container is a cold cache by definition, so
   the `add` that opens the provisioning sequence is the call most likely to hit it, and
   *retry-and-it-works* is not something a script author will guess. **Fix:** one paragraph in
   `knowledge-index.md` §9 after `:2405-2410` naming the deadline, the cold-cache fetch, that the
   service keeps starting after the client gives up, and that a second call succeeds; one sentence in
   `client.py:94-99` (`connected`'s docstring); and the figures back in `FINDINGS.md` §M31 with where
   they came from, since they are a measured fact that constrains a choice — whether this surface
   owes a longer deadline than the hook's or the script owes a retry. Deciding that is out of this
   round's scope; stating the failure mode is not.

3. **[IMPROVEMENT] Done-when 6's *"against one that fails, which must not report it either"* is
   covered only at the unit level.** `tests/test_knowledge_cli.py:1099-1107` drives
   `_report_terminal_states` directly; no test runs `refresh --wait` end to end against a build that
   started and left the corpus unusable, which is the composition `_await_builds` adds over its
   parts and the case a script author cares about most. The helpers already exist: a spawn stub that
   calls `_begin_a_build(building, pid=_DEAD_PID, host=lock.this_host())` is a build that took its
   lock and died — mark advanced (so it *appeared*), `live: false` (so it is not *still building*),
   never completed (so the terminal state is not `ok`). Assert `_run(project, "refresh", "docs",
   "--wait") == 1` and `"the build left it"` in stderr. One test, no poll hook needed.

4. **[IMPROVEMENT] `FINDINGS.md` §M31 restates rationale the corpus already holds.** `:233-248`
   carries three bullets of reasoning: D37's, including the superseded rule it replaced (*"bumped
   only when an old binary would read a new store wrongly"*), which is what-an-earlier-sentence-said
   and belongs only in `overview.md`'s Rationale column, where it already is; the payload-prose rule,
   verbatim from `errors.py`; and the `--wait`-over-lease argument, verbatim from the brief.
   `CLAUDE.md` §"Project memory" wants a decision and *where its rationale lives*, one line each.
   Round 1 asked for the FINDINGS sentence to agree with `errors.py`; agreeing by pointer is the form
   the house rule wants, and I should have said so. **Fix:** replace the three bullets with one line —
   *Three decisions taken 2026-09-24: D37 (`overview.md` §4); the payload-prose rule
   (`core/errors.py`); `refresh --wait` rather than a lock lease (`build-plan.md` §M31)* — and keep
   the SQLite paragraph (`:250-256`), which is a measured fact with its re-derive command.

5. **[NITPICK] `README.md:98`** — *"always by the service, whether an agent asked or you did"* is
   contradicted two columns later by the `foreground` line the CLI itself prints, which starts one by
   hand. `architecture.md:16` now says both in one breath; borrow it: *by the service on every
   `add`/`refresh` — whether an agent asked or you did — or by you, running the foreground command a
   build result prints.*

6. **[NITPICK] Nothing pins `--project`'s absolutization.** `main.py:229` `return
   project.absolute()`; `TestWhereTheCommandActs` (`tests/test_knowledge_cli.py:630-638`) covers only
   the no-`--project` branch. One test: `monkeypatch.chdir(project.parent)`, patch `cli.connected` to
   record its argument, `main(["--project", project.name, "list"])`, assert the recorded path
   `.is_absolute()` and `== project`. Otherwise the next edit to `_project` can drop the call without
   reddening anything.

7. **[NITPICK] `scope.execute`'s docstring against done-when 1.** The brief says it *"renders from
   [the disposition] rather than from an exception type"*; `scope.py:122-132` still branches on type
   for `KnowledgeError` (→ `refused`) and `aiosqlite.Error | OSError` (→ `failed`), necessarily, since
   neither carries a code. One sentence saying that the codeless two are rendered by type *because
   they are codeless* stops a reader checking the brief against the code from seeing a contradiction.

### Round-1 items, re-verified

1 (`main.py:407-441`, both tests at `:1192-1267` assert stdout); 2 (`errors.py:12-26`,
`build-plan.md:3483-3492`, `_translated` at `dispatch_knowledge.py:171-174`); 3 (`migration.py:38-66`,
`test_store_migration.py:275-285`, `schema.md:1454-1460`, `ddl.py:78-81`); 4 (`main.py:195`,
`scope.py:127`, `AmbiguousMutationError` at `main.py:197`); 5 (`main.py:557`, `client.py:25`);
6 (`test_knowledge_cli_integration.py:227-262`); 7 (`main.py:229`); 8 (all six passages);
9 (`conftest.py:317, 380-386`); 10 (`test_knowledge_cli.py:112-121`); 11 (`schema.md:362-363,
1484-1487`); 12–14 applied. None re-raised.

VERDICT: NEEDS_CHANGES

---

## Round 3 — 2026-09-24

### Summary judgment

Every round-2 item is applied as described and I re-read each against the tree: `_refresh` collects
`already_indexing` into `running` (`main.py:353-361`), `_await_builds` seeds `appeared` and runs a
lock-only branch for those names (`:445-474`), the three tests exist and assert what they say
(`test_knowledge_cli.py:1270-1345`), `--project` is pinned absolute (`:1347-1367`), the cold-cache
paragraph is in §9 (`knowledge-index.md:2412-2421`) and `client.connected` (`client.py:100-104`),
FINDINGS §M31 is one decision line plus the SQLite measurement, README's indexer row names both
spawners, and `scope.execute`'s docstring says why the codeless two are rendered by type. One new
defect stops it shipping, and it is in the lock-only branch itself: it takes *any recorded lock* as
"still running", including one whose holder this host has proved dead, so a `refresh --wait` that
found a build under way and then watched its indexer die hangs forever — the CI-hang class this
option exists to remove, on the branch added to remove it. The design prose already states the
right predicate; the code is the one that disagrees. The rest is one pasteable-but-refused
remedy, one uncited measurement, and nitpicks.

### Findings

1. **[BLOCKER] The lock-only predicate omits the dead-holder half, so a wait on a build somebody
   else started hangs unbounded the moment that indexer dies.** `main.py:460-474`: for a name in
   `lock_only`, `live: None` fails (correct), and then `if held is not None: pending.append(name)`
   — which is also true for `live: False`. `reporting._lock_report` (`reporting.py:220-231`) emits
   `live=lock.probe(...)`, which is `False` for a local holder whose pid no longer answers, and the
   rows persist: `lock.py:21-22` says *"a killed build leaves those behind deliberately"*, and only
   the next `acquire`, a `force_release`, or the build's own unwind clears them — none of which a
   killed process runs. So: `add` spawns a build, `refresh --wait` arrives after the lock is taken
   and gets `already_indexing` (`builds.py:127-132`, via `running_holder`, so the holder is live or
   foreign at that instant), the indexer is then OOM-killed or SIGKILLed, `status` reports `lock:
   {live: false}`, and the loop polls every second until the step's own timeout — which is the
   stranded-lock chain the brief's §"Waiting, and the container case" says `--wait` removes. The
   started-build path does not have this defect: `_still_building` (`:400-403`) returns `False` on
   `live is False`. **The design already says the right thing**: `knowledge-index.md:2454` defines
   the lock half as *"absent, or held by a process this host can see is dead"* and `:2457-2459` says
   an already-running build *"takes the lock half alone"* — so the prose is right and the code is
   the bug, per `build-plan.md`'s standing note. **Fix (code):** make the lock reading one helper so
   the two predicates cannot drift — `def _lock_says_running(held: Mapping[str, object] | None)
   -> bool: return held is not None and held.get("live") is not False` — used by `_still_building`'s
   second line and by the lock-only branch in place of `if held is not None:`. With it, a dead
   holder leaves `pending`, `_report_terminal_states` reads the state (not `ok`, since the scan
   never completed), the command prints `failed    docs: the build left it <state>` and exits 1 —
   the same answer the started path gives for the same event. Amend `_await_builds`'s docstring at
   `:425-426` (*"its lock alone is the evidence, and the lock is already there"*) to *"its lock
   alone — present and not provably dead — is the evidence"*. **Fix (test), and it must be bounded
   because a regression here is a hang and `pyproject.toml` carries no `pytest-timeout`:** copy
   `test_it_waits_for_a_local_build_already_under_way` (`:1278-1307`); on poll 3, instead of
   `_release_the_lock`, orphan it — a helper `_orphan_the_lock(database)` doing `UPDATE meta SET
   value = ? WHERE key = 'lock_pid'` with `str(_DEAD_PID)` — and in `_counted` raise
   `AssertionError("the wait did not end on a holder this host proved dead")` once `polls > 20`;
   assert exit 1, `"the build left it"` in stderr, `polls >= 3`. On the current tree it raises at
   poll 21; after the change it passes. State the mutation result in the next brief.

2. **[IMPROVEMENT] The new failure line names a command that is refused as typed.** `main.py:465-468`
   prints *"clear it with `refresh --force-unlock`"*, and `main.py:338-340` refuses exactly that:
   *"--force-unlock clears one knowledge base's lock, so name one"*. Under a sweep (`refresh --wait`
   with no name) the person has no name in the line to add. The name is in scope: `f"clear it with
   `refresh {shlex.quote(name)} --force-unlock`"`. Same shape at `main.py:752-753` (`_lock_line`) and
   `lifecycle.py:386-388`, both pre-existing and both printed beside the corpus's name — worth the
   same edit while there, but not this milestone's defect.

3. **[IMPROVEMENT] The §9 cold-cache paragraph quotes 3.74 s and 3.30 s without naming where they
   were measured.** `knowledge-index.md:2415-2416` says *"measured in a container"*; the source is
   `research/m30-docker-end-to-end.md:107-113` (§"The fetch happens inside the cold start"), and a
   figure in a normative document with no re-derive pointer is this corpus's own named stale-number
   class. Add the citation after *"measured in a container"*. And the sentence at `:2419-2421` —
   whether the CLI's deadline should exceed the hook's or a script owes the retry — is *an open
   question with what would close it*, which `CLAUDE.md` §"Project memory" puts in `FINDINGS.md`;
   §M31 (`FINDINGS.md:218-242`) does not mention it. One sentence there, pointing at §9, so a fresh
   session provisioning a container does not re-discover it.

4. **[NITPICK]** `main.py:592` prints *"already being built; waiting for it"* before the first
   poll, so for a foreign holder it is followed within one poll by *"failed … held by another
   host"*. Either drop *"; waiting for it"* under `--wait` (the wait itself reports), or accept the
   two-line account.

5. **[NITPICK]** `main.py:466` says *"held by another host"*; `live: None` also covers a pid that is
   not a number (`lock.py:134-135`, a hand-edited row), which `_lock_line` at `:751-753` words
   correctly as *"not something this machine can check"*. *"held by a process this machine cannot
   probe — another host, or an unreadable pid"* covers both, and `--force-unlock` clears both.

6. **[NITPICK]** `knowledge-index.md:2447` is a ~130-character line and `:2459` a ~50-character one
   — re-wrap artefacts from the two inserted passages. Cosmetic; nothing in the gate reads them.

### Round-2 items, re-verified

1 (`main.py:353-371, 445-491`; tests `:1278-1325`, both assert the exit code and stdout/stderr as
specified); 2 (`knowledge-index.md:2412-2421`, `client.py:100-104`); 3 (`:1327-1344`, end to end
through `_await_builds`); 4 (`FINDINGS.md:231-234`); 5 (`README.md:98`); 6 (`:1347-1367`);
7 (`scope.py:115-119`). None re-raised. Round-1 items unchanged since round 2's re-verification.

VERDICT: NEEDS_CHANGES

---

## Round 4 — 2026-09-24

### Summary judgment

The round-3 blocker is closed as described and I re-read it against the tree rather than the
brief: the lock reading is one helper (`main.py:411-420`), both predicates call it (`:402`, `:484`),
the regression test is bounded at `polls > 20` (`test_knowledge_cli.py:1360-1395`) and the stated
mutation result is consistent with the code — `held is not None` alone would keep a `live: false`
lock in `pending`. I walked the lock-only branch's cells (released; holder dies; foreign or
unreadable holder; a live pid takes the lock over mid-wait; the corpus is removed mid-wait) and none
hangs or reports success falsely. What remains is outside the product's code path: an integration
test whose `foreground` extraction depends on winning the same one-to-three-second window round 2
quantified, an open question placed where the corpus's own archive rule will bury it, and a
`--full` under `--wait` that reports `ok` without saying the full rebuild never started. Nothing
blocks; each improvement is a few lines.

### Findings

1. **[IMPROVEMENT] The foreground-command integration test still races `add`'s indexer for the
   lock, and now loses in a way the `--wait` fix did not cover.**
   `tests/test_knowledge_cli_integration.py:212-218`: `add`'s output is discarded, and the
   `foreground` line is taken from `refresh --wait`'s output — which `_report_build` prints only on
   `started` (`main.py:588-597`). When `add`'s indexer has taken its lock before the `refresh`
   arrives, the outcome is `already_indexing`: now waited for, exit 0, `built 'docs' is ok` printed
   — and no `foreground` line, so `(line,) = [...]` at `:218` raises `ValueError`. The window is
   the one round 2 quantified (Python start, then the model load, then `scan._begin`), and the
   `refresh` side is one warm connection plus two RPCs, so the test usually wins; it is the required
   macOS job under load that will occasionally not. The docstring at `:188-192` claims `--wait`
   makes the test *"deterministic rather than a race"*, which is true of the exit code and not of
   the line the test then unpacks. **Fix:** keep `add`'s output — `added = capsys.readouterr().out`
   at `:212` — and take the `foreground` line from `added`, since a fresh corpus always answers
   `started`; leave the `refresh --wait` as the wait. Reword `:216`'s message to *"the build it
   started or found"*.

2. **[IMPROVEMENT] The open question is inside a block the archive rule will move while it is still
   open.** `FINDINGS.md:236-243` sits in §M31, and `CLAUDE.md` §"Project memory" moves *every
   milestone block that has stopped being live* to `FINDINGS-archive.md` — which for this block is
   the merge. The archive is read on demand, so the question a fresh session provisioning a container
   most needs is the one it will not see. The corpus already has the shape for this: §"Live design
   questions", stable ids, 4/10/11/13/15 spent, Q16 the last. **Fix:** move the paragraph there as
   **Q17**, keeping the what-would-close-it sentence and the `knowledge-index.md` §9 pointer; §M31 may
   keep one clause pointing at Q17 if it wants to.

3. **[IMPROVEMENT] `refresh --full --wait` against a corpus already being built exits 0 and never
   says the full rebuild did not happen.** `main.py:360-361` puts it in `running`, `:607-608` prints
   *"already being built"*, the wait ends on the other build's `ok`. The non-wait line at `:610`
   carries *"nothing was queued"*, which is what tells a person their `--full` did not run; the
   `--wait` variant dropped the clause. Nothing on the wire says whether the running build is a full
   one — the lock records pid, host and start only, and `builds.py` carries no `full` — so the CLI
   cannot claim either way about *that* build, but it can say what *this call* did. **Fix:**
   `_report_build(..., full=args.full)`; in the `waiting` branch print `building  'docs' is already
   being built; this call queued nothing`, and when `full`, `… queued nothing — the --full rebuild
   asked for here did not start`. That is the non-wait line's information without the
   *finished-with-it* reading round 2 objected to.

4. **[NITPICK]** `main.py:472-475`: the comment says *"A holder on another machine"*; the message it
   precedes (`:477-478`) covers *"another host, or an unreadable pid"*. *"A holder this host cannot
   probe."*

5. **[NITPICK]** `design/knowledge-index.md:2446`: *"A lock held by another host fails immediately
   instead"* — the code fails on `live: None`, which `lock.py:141-142` also returns for an unreadable
   pid. *"A lock this host cannot probe — another host's, or one whose pid is unreadable — fails
   immediately instead."*

6. **[NITPICK]** `main.py:600-606`: two stacked comments justify the one `waiting` branch, each with
   a different reason for the same line. One is enough (`coding-standards.md` §5); keep the second.

7. **[NITPICK]** `main.py:769` *"Named, because `--force-unlock` refuses without one"* annotates a
   repair, and `test_knowledge_cli.py:1337-1338` already states the reason. Drop the comment.

8. **[NITPICK]** `_explain_detachment` is skipped under `--wait` (`main.py:364-366`), yet a `failed
   … the build left it <state>` line is the moment the pointer to the foreground command is most
   needed. Print the note when `_report_terminal_states` returned `True` and this call started a
   build (`names` non-empty).

9. **[NITPICK]** `design/knowledge-index.md:2450` is ~135 characters — one more of round 3's
   re-wrap class, adjacent to the two that were fixed. Cosmetic.

### Round-3 items, re-verified

1 (`main.py:388-420`, `:484`; `test_knowledge_cli.py:1360-1395`, bounded); 2 (`:476-480`,
`:767-771`, `lifecycle.py:386-389` — all three name the corpus); 3 (`knowledge-index.md:2415-2417`
cites `research/m30-docker-end-to-end.md` §"The fetch happens inside the cold start", whose
timestamps give 3.74 s and ≤3.30 s as stated; `FINDINGS.md:236-243`); 4 (`:607-608`); 5
(`:477-478`); 6 (`:2441-2448`). None re-raised. Rounds 1–2 unchanged since round 3's
re-verification.

VERDICT: NEEDS_CHANGES

---

## Round 5 — 2026-09-24

### Summary judgment

Every round-4 item is applied as described, and I re-read each against the tree: the integration
test now unpacks its `foreground` line from `add`'s captured output and its docstring separates what
`--wait` makes deterministic from what it does not; `_report_build` takes `full` and both the
`queued` and `missed` clauses are asserted end to end; the detachment note fires after a waited
build ends badly; the comment, §9 and Q17 are where round 4 asked. The code path is sound — I
re-walked `_await_builds` for the mixed sweep (one started, one running, one dead spawn) and the
lock-only branch's cells and found nothing new. What stops an APPROVED is one claim, stated in the
normative §9 and in both new modules, that the code contradicts in the ordinary case and that
`main.py`'s own `_execute` docstring contradicts eight lines below it: the CLI does open the store,
read-only, on every connect after the first. That is a wording fix at three sites. The rest is
nitpicks, one of which is a residual imprecision in the fix round 4 itself specified.

### Findings

1. **[IMPROVEMENT] "Opens no store" is stated three times, is false of the code in the ordinary
   case, and `main.py` says so itself a few lines later.** `main.py:5` (*"This command opens no
   store"*), `client.py:3` (*"The CLI is a thin client and opens no store"*),
   `knowledge-index.md:2405` (*"The CLI opens no store"*). `ServiceConnection._connected_socket`
   (`connection.py:420-421`) calls `_read_store_identity`, which runs `Store.open` whenever
   `memory.db` exists (`:137-146`) — every call after the first, i.e. the ordinary case.
   `main.py:199-202` documents the consequence (*"the identity read `ServiceConnection` performs
   opens the store, and a `memory.db` that is not a database fails at the first pragma"*) and
   `:194-196` renders `REINDEXING`/`BAD_CONFIG` from exactly that open — so the command's observable
   behaviour depends on the open the module docstring denies. The brief is the precise one:
   done-when 1 says the verbs *"reach the store only through `ServiceConnection`"*, and §"`cli` is a
   client kind" lists `mcp/connection.py`'s identity read among the openers that accept the range
   read-only. Why it matters beyond tidiness: "which processes open `memory.db`" is a question this
   corpus answers in earnest elsewhere — the migration contract's *only the service migrates*,
   FINDINGS §"Where the stores are" on WAL snapshots — and a reader auditing that from §9 is sent to
   the wrong answer. **Fix:** at all three sites, *"opens no store of its own — the one open it
   makes is `ServiceConnection`'s identity read, shared with every client, read-only, and refused
   for the same reasons the service's own start would be"*. `client.py:3` can carry the sentence
   and `main.py:5` point at it; §9 needs the clause, since it is normative.

2. **[NITPICK]** `main.py:327-328`: *"never for `already_indexing`, which is the idempotent case"*
   — under `--wait` a lock this host cannot probe is `already_indexing` on the wire and exits 1
   (`:477-488`). *"— but, without `--wait`, never for `already_indexing`"*; the paragraph that
   follows already covers the waited case, so one qualifier closes it.

3. **[NITPICK] The detachment note under `--wait` can point at a line that was never printed —
   and round 4's own wording is what specified it.** `main.py:370-375` prints the note when
   `unusable and building`. In a sweep where this call started `A` (which ended `ok`) and found `B`
   already running (which ended `error`), the note says *"run the foreground command printed
   beside it"* and `B` has no such line — it was `already_indexing`, and `_report_build` prints the
   argv only on `started` (`:595-604`). Round 4's nitpick 8 asked for exactly the predicate that was
   implemented, so the imprecision is mine. **Fix:** have `_report_terminal_states` return the set
   of unusable names rather than a bool, `_await_builds` return `unusable | dead`, and `_refresh`
   print the note when `unusable & set(building)`; `1 if unusable or failed` still reads on a set.
   While there, no test asserts the note under `--wait` at all —
   `test_a_build_that_ran_and_left_the_corpus_unusable_fails` (`test_knowledge_cli.py:1341-1358`)
   is the case it exists for, and one more line (`"foreground command printed beside it" in
   captured.out`) pins it.

4. **[NITPICK]** `test_knowledge_cli_integration.py:44` passes `platform="linux"` to
   `paths.socket_path`, where the three other integration reapers (`test_install_e2e.py:164`,
   `test_install_takeover.py:80`, `test_hook_main.py:120`) pass `sys.platform`. Harmless today —
   `platform` decides only the length check (`paths.py:147-150`), and a path darwin would refuse
   was never bound, so `exists()` is false either way — but the literal is a claim the required
   macOS job runs under, and `sys` is already imported at `:20`.

5. **[NITPICK]** Re-wrap artefacts in `design/knowledge-index.md`: `:2453` and `:2482` are ~60
   characters, `:2464` ~65, and `:2479` ~130 — the passage round 4's nitpick 9 named moved rather
   than closed. Cosmetic; nothing in the gate reads them.

### Round-4 items, re-verified

1 (`test_knowledge_cli_integration.py:214-225`: `added` captured, `foreground` unpacked from it,
`refresh --wait` still the wait; docstring `:188-194` states the run/lines split); 2 (`main.py:580,
606-617`; `test_knowledge_cli.py:1360-1394` asserts both clauses and exit 0); 3 (`main.py:370-375`);
4 (`:478`; `knowledge-index.md:2446-2447`; `_lock_line` at `:756-777` carries no annotation); 5
(`FINDINGS.md:366-373`, Q17 with what would close it and the §9 pointer; `Settled decisions` row
D37 at `:64`); 6 (`:608-616` — two comments remain, but each justifies a different variable rather
than the same line twice); 7 (`:756-777`); 8 (`:370-375`, see finding 3); 9 (moved, see
finding 5). None re-raised. Rounds 1–3 unchanged since round 4's re-verification.

VERDICT: NEEDS_CHANGES

---

## Round 6 — 2026-09-24

### Summary judgment

Every round-5 item is applied as described, and the change you asked to have checked is correct: I
traced `set[str]` through all three functions and the four cases that matter — a started build
ending `ok` beside a found build ending `error` (no note), a started build ending badly (note), a
spawn that never appeared (note, and it is the right one — the foreground command is exactly how to
see why), a lock this host cannot probe (never in the intersection, since it can only be in
`running`) — and the code does what the docstrings say. Two things keep it from APPROVED, both a
few lines. The "opens no store of its own" fix now says the identity read is *shared with every
client*, which is false of the hook and contradicts the design's own documented exception; that
wording was mine in round 5 and I should have checked it against `hook/connect.py` before writing
it. And the new intersection predicate has its positive half pinned and its negative half — the
very case round 5 raised it for — not pinned, so the mutation back to `if unusable:` keeps 3137
green. The rest is nitpicks.

### Findings

1. **[IMPROVEMENT] "Shared with every client" is false of the hook, in the normative §9 and in
   `client.py`, and the corpus already says so elsewhere.** `zikaron/knowledge/client.py:10-11`
   (*"`ServiceConnection`'s identity read, shared with every client and read-only"*), `:15-16`
   (*"the store identity check and the session label every other client is under"*), and
   `design/knowledge-index.md:2405-2406` (*"read-only and shared with every client"*). The hook is
   a client, and it makes no such read: `zikaron/hook/connect.py:344-346` — *"This module
   deliberately has no function reading `meta.store_id` from an existing store, and `connect_once`'s
   own identity check stays path-only, on every connection this client ever makes"* — and
   `design/architecture.md:586-592` names it *"a genuine exception"* with two rejected alternatives
   measured. The read is `mcp/connection.py`'s, so it is shared with `zikaron-mcp` (both server
   roles) and nothing else. Why it matters more than a word: round 5 asked for the "opens no store"
   sentence to be corrected *because* "which processes open `memory.db`" is a question this corpus
   answers in earnest, and the corrected sentence now over-claims in the other direction — a reader
   auditing the hook's no-store-access rule from §9 is told the hook reads the store. **Same
   sentence, one more imprecision:** `client.py:11-12` *"on every connect after the first"* —
   `_read_store_identity` (`connection.py:137-142`) opens whenever `memory.db` exists, which for a
   project that already has a store is the first connect too; the one connect that skips it is the
   one in a project's life that precedes the store's creation. **Fix:** `client.py:10-13` → *"The
   one open it does make is `ServiceConnection`'s identity read, read-only and shared with
   `zikaron-mcp` — not with the hook, whose check stays path-only because it may never read the store
   (`architecture.md` §"Store identity is verified, not assumed"): `memory.db`'s `meta.store_id`,
   checked against the service's own, on every connect that finds `memory.db` already there — every
   one but the first in a project's life."* `client.py:16` → *"the session label `zikaron-mcp` is
   under"*. §9 `:2405-2406` → *"read-only and shared with `zikaron-mcp`; the hook makes none"*.
   `main.py:5-6` points at `client.py` and needs nothing.

2. **[IMPROVEMENT] The intersection predicate's negative half is not pinned, so the mutation back to
   the round-5 defect is green.** `main.py:372` `if unusable & set(building):`. The positive half —
   a build this call started ends badly, note printed — is asserted at
   `tests/test_knowledge_cli.py:1360-1363`. The negative half is the case round 5's finding 3 was
   raised for: a corpus this call *found* running ends badly and gets no note, because no `foreground`
   line was ever printed for it. `test_a_build_it_was_waiting_for_dying_ends_the_wait_rather_than_hanging`
   (`:1401-1436`) is exactly that arrangement — `running == ["docs"]`, `building == []`, ends
   *"the build left it"* — and asserts only stderr. I checked the mutation by trace: with `if
   unusable:` the note prints there and in the foreign-lock test (`:1320-1339`, which reads only
   `.err`), and every other `--wait` test either expects the note or has an empty `unusable`; nothing
   reds. **Fix:** at `:1434-1436` capture both streams and add `assert "foreground command" not in
   printed.out, "the note points at a line printed only for a build this call started; this one was
   found running"`. **While there:** `:1107` `assert not cli._report_terminal_states(...)` and
   `:1117` `assert cli._report_terminal_states(...)` are the `bool` contract's assertions surviving
   the type change unchanged; `== set()` and `== {"docs"}` pin what the intersection actually
   depends on — that the set holds *names* — which `unusable.add(state)` would otherwise only fail
   at the end-to-end test. State the mutation result in the next brief.

3. **[NITPICK]** `main.py:437` *"Returns the corpora that ended unusable"* and the local `unusable`
   at `:371`: the set also holds a spawn that never appeared — whose corpus may still be `ok` from an
   earlier build — and a lock this host cannot probe. Behaviour is right for all three (exit 1; the
   note for the second, since running the foreground command is precisely how to see why the spawn
   died). *"Returns every corpus the wait failed on — ended unusable, never started, or locked by a
   holder this host cannot probe"*, and `failed_waits` for the local if you want the name to match.

4. **[NITPICK]** Re-wrap: `design/knowledge-index.md:2407` is ~118 characters and is in the
   paragraph this round edited (the *of its own* clause pushed it); `:2455` (~47), `:2466` (~72) and
   `:2483` (~72) are short lines inside the `--wait` passages this milestone wrote. Cosmetic;
   nothing in the gate reads them, and the ~130-character line in the foreground-refusals paragraph
   is, as you say, not this milestone's.

### On the change you asked to have checked

Correct. `_report_terminal_states` returns names (`:555-563`); `_await_builds` unions `dead` into
it (`:502`), and `dead` can only hold a started build's name via the appearance deadline (`:503-509`)
or a running build's via the unprobeable-lock branch (`:479-490`), so `unusable & set(building)` is
exactly *started builds that failed or never started* and never a found one; `1 if unusable or
failed` reads a non-empty set as truthy. The three signatures and the two call sites agree, and
`surviving` excludes `dead` before the terminal-state report so nothing is reported twice. The gap is
finding 2, not the code.

### Round-5 items, re-verified

1 (`main.py:5-6`; `client.py:3, 10-13`; `knowledge-index.md:2405-2406` — applied, and finding 1 is
the clause the applied wording over-claims); 2 (`main.py:371-378, 436, 502, 547-563`;
`test_knowledge_cli.py:1360-1363` pins the note; finding 2 is the half it does not pin); 3
(`main.py:328-329`); 4 (`test_knowledge_cli_integration.py:44`); 5 (see finding 4). None re-raised.
Rounds 1–4 unchanged since round 5's re-verification; done-when 1 through 8 still hold as traced
in rounds 1–5, and 9 is `./check.sh` here with the matrix satisfied by the PR per `CLAUDE.md`.

VERDICT: NEEDS_CHANGES

---

## Round 7 — 2026-09-24

### Summary judgment

Every round-6 item is applied as described and I re-read each against the tree: the hook claim
is now true (`client.py:10-16` against `hook/connect.py:344-346` and `architecture.md:586-592`),
the negative half of the intersection is pinned on stdout (`test_knowledge_cli.py:1440-1443`) and
the stated mutation result is consistent with the code, the two unit assertions compare sets of
names, and `_await_builds`'s docstring names all three kinds its set holds. I also checked the
wait predicate's one remaining hidden assumption — that a second build's mark cannot equal the
first's — and it holds: `scan._begin` writes lock and mark in one transaction (`scan.py:190-208`)
with a microsecond ISO timestamp (`clock.py:57`). The code path is done. What keeps this from
APPROVED is the same class round 6 closed, on the two modules the milestone *reused* rather than
the two it wrote: `mcp/connection.py` still describes itself as held by one MCP server process
and serving two client kinds, and `service/rpc.py` says `parse_response` is shared by every
client, which the hook is not. A few lines each. The rest is nitpicks, one of which is that the
brief's item 5 is not true of the tree.

### Findings

1. **[IMPROVEMENT] The modules the CLI reuses still describe their callers as they were before
   the CLI existed — the "every client" class round 6 closed in the two new files, standing in the
   two reused ones.**
   - `zikaron/mcp/connection.py:1`: *"held for the life of one MCP server process"* — it is now
     also held for the life of one `zikaron knowledge` command (`client.py:115-119`).
   - `zikaron/mcp/connection.py:220-222` (`envelope()`): *"the same connection type serves both —
     `"mcp"` for the primary agent's process, `"consolidator"` for the consolidator's"* — this is
     the method the CLI calls with `kind="cli"` (`client.py:92`), so the enumeration on the seam
     the milestone widened is the one place a reader adding a kind would look, and it names two of
     three.
   - `zikaron/mcp/connection.py:132-135` (`_read_store_identity`): *"A tool handler that calls
     this lets any such error propagate as a normal FastMCP tool error"* — the CLI is the second
     caller and renders it by disposition (`main.py:194-199`).
   - `zikaron/service/rpc.py:196`: *"Shared by every client rather than reimplemented per
     surface"* — the hook parses its own responses (`hook/connect.py:315-329`) and imports nothing
     from `service/rpc.py` (grep: the only importers are `knowledge/client.py` and `mcp/errors.py`).
     In a corpus that audits the hook's dependency surface, a `service/` module claiming every
     client shares it is a claim about the hook that is false.
   **Fix:** `connection.py:1` → *"held for the life of one client process — an MCP server's, or one
   `zikaron knowledge` command's"*; `:220-222` → *"… `"mcp"` for the primary agent's process,
   `"consolidator"` for the consolidator's, `"cli"` for the knowledge command (`knowledge/client.py`)"*;
   `:132-135` → append *"; the CLI renders it from the code's declared disposition instead"*;
   `rpc.py:196` → *"Shared by both `ServiceConnection` clients rather than reimplemented per
   surface — the hook keeps its own stdlib-only parse — so …"*.

2. **[NITPICK]** `design/knowledge-index.md:2407` cites `§"Store identity" in architecture.md`; the
   heading is `§"Store identity is verified, not assumed"` (`architecture.md:556`), which is what
   `client.py:12` and every other citation in the tree use, and a truncated heading is one a grep
   for the heading does not find. Same line is ~170 characters. **On the brief's item 5**: the
   short lines round 6 named at `:2455` (~46), `:2466` (~72) and `:2483` (~72) are unchanged, and
   `:2407` grew — so "the re-wrap artefacts in the passages this milestone wrote are closed" is not
   true of the tree. Cosmetic either way; nothing in the gate reads them.

3. **[NITPICK]** `zikaron/knowledge/client.py:14-16`: *"which is why `REINDEXING`, `BAD_CONFIG` and a
   driver error reach this command at all"* — `SCHEMA_INCOMPATIBLE` is the third code
   `_read_store_identity`'s own docstring names (`connection.py:130-131`), it is the one this
   milestone made a range, and a store above `{1, 2}` reaches `_execute` through exactly this read
   as a `FAILED` `ZikaronError`. Add it to the list.

4. **[NITPICK]** `zikaron/knowledge/main.py:186-188` (`_execute` docstring): *"The remainder …
   arrives as an exception raised while *establishing* the connection, before any request
   existed"* — `AmbiguousMutationError`, caught at `:200`, is raised after the request was sent
   (`connection.py:340-348, 359-362`). The comment at `:204-205` says so; the docstring above it
   says the opposite. *"… before any request existed — except `AmbiguousMutationError`, which is
   the service dying mid-request"*.

5. **[NITPICK]** `zikaron/knowledge/scope.py:9`: *"`zikaron knowledge` used to share this and no
   longer does"* narrates the change rather than stating the truth (`CLAUDE.md` §"The documents
   carry current truth"; `coding-standards.md` §5). *"`zikaron knowledge` is a thin client of the
   service (`zikaron/knowledge/client.py`), which is what lets it …"* carries the same reason
   without the history.

6. **[NITPICK]** `design/overview.md:186` (D31): *"a third client rather than a store-opener"* —
   the wording round 5 corrected at three sites for the reason that "which processes open
   `memory.db`" is a question this corpus answers in earnest, and the decision table is the entry
   point. D37's own rationale two rows down names "the MCP identity read" as an opener. *"rather
   than a store-opener of its own"* is the fix the other three sites took.

7. **[NITPICK]** `FINDINGS-archive.md:3253-3256` (§References): *"Every blocker it found was in
   `refresh --wait`; the rest is where the payload-prose rule, the frozen-migration-DDL rule and the
   'opens no store *of its own*' wording were each settled"* is an account of what a review round
   covered and of a sentence's wording, which `CLAUDE.md` §"Project memory" puts nowhere — "not to
   the archive". The M30 entry beside it does the same with round counts, so this is a house
   pattern rather than this milestone's invention; but the entry is new in this tree. The pointer
   alone — *"`reviews/m31-cli-thin-client-review.md`. M31's review trail."* — is what the rule wants.

### Round-6 items, re-verified

1 (`client.py:10-16`; `knowledge-index.md:2405-2407`; `main.py:5-6` points at `client.py`;
`hook/connect.py:344-346` confirms the hook makes no such read); 2 (`test_knowledge_cli.py:1440-1443`
asserts on `printed.out`; `:1107` `== set()`, `:1117` `== {"docs"}`; the stated mutation — `if
failed_waits:` in place of the intersection — would print the note in that test, since
`running == ["docs"]`, `building == []`, and the set is non-empty, so the assertion reds as
claimed); 3 (`main.py:437-440`, `failed_waits` at `:371-372, 378`); 4 (see finding 2 — not
closed). None re-raised except 4 as stated. Rounds 1–5 unchanged since round 6's re-verification;
done-when 1 through 8 still hold as traced there, and 9 is `./check.sh` here with the matrix
satisfied by the PR per `CLAUDE.md`.

VERDICT: NEEDS_CHANGES

---

## Round 8 — 2026-09-24

### Summary judgment

Every round-7 item is applied as described, and I re-read each against the tree rather than the
brief: the two reused modules now describe their callers truthfully, and the two "both" claims they
make are exact — product code constructs `ServiceConnection` at `mcp/server.py:61` and
`knowledge/client.py:116` only, and `parse_response` is imported by `knowledge/client.py:33` and
`mcp/errors.py:17` only. Nothing in code needs to move. What keeps this from APPROVED is two
sentences in normative documents, both this milestone's own text and both the over-claim class rounds
6–7 closed elsewhere: D31's amendment asserts that `zikaron-mcp` is stdlib-only, which
`architecture.md` §Components refutes by a recorded operator decision; and the degraded-modes row
done-when 7 names says the CLI meets an unreadable `memory.db` "exactly as any other client does",
through a service that cannot start, when the hook makes no identity read and the route is the
client's own read before any spawn is attempted. One sentence each. The rest is nitpicks.

### Findings

1. **[IMPROVEMENT] D31's new sentence says `zikaron-mcp` is stdlib-only; the architecture document
   says, by operator decision, that it is not.** `design/overview.md:186`: *"It is deliberately
   \*not\* stdlib-only, unlike the two above: no per-message budget constrains a command a person
   types."* "The two above" are `zikaron-mcp` and `zikaron-hook`. `design/architecture.md:14`
   (*"MCP server, built on the `fastmcp` framework"*), `:24` (*"The hook is thin on purpose; the MCP
   server is not"*) and `:32-43` (*"Operator decision, after M9's fourteen-round review … `zikaron-mcp`
   takes a dependency on `fastmcp` … `zikaron-hook` stays stdlib-only; nothing above revises that"*)
   say the opposite; `zikaron/mcp/errors.py:15` imports `fastmcp.exceptions`, `mcp/connection.py:39`
   imports `Store` and everything under it, and `tests/test_hook_stdlib_only.py` guards the hook alone.
   So under either reading of "stdlib-only" — the process or its transport — exactly one client is,
   and the new sentence claims two. It matters because `overview.md` is the entry point `CLAUDE.md`
   sends every fresh session to first, and the row is the one that defines the component split. The
   source is the row's own pre-M31 decision text (*"thin stdlib-only clients"*), which never absorbed
   M9 — not this milestone's defect, and I am not lodging it as one; but the amendment is being written
   into that cell now, and it inherits the claim rather than correcting it. **Fix (the new sentence):**
   *"It is deliberately \*not\* stdlib-only, for the reason `zikaron-mcp` is not (`architecture.md`
   §Components, the M9 decision that took `fastmcp`): only the hook sits on a per-message budget, and
   none constrains a command a person types."* **Optional, and the decision-table rule in `CLAUDE.md`
   is what licenses it:** in the decision column, *"thin ~~stdlib-only~~ clients that start the
   service if absent — the hook stdlib-only, `zikaron-mcp` on `fastmcp` since M9"*, so the row stops
   contradicting the document it cites as its full spec.

2. **[IMPROVEMENT] The unreadable-`memory.db` row done-when 7 names over-claims in the direction
   round 6 corrected, and mis-states the route.** `design/knowledge-index.md:2553`: *"the CLI is an
   RPC client, so it meets this exactly as any other client does — the service cannot start, and the
   failure arrives while the connection is being established rather than from a listing. A `memory.db`
   that is not a database at all raises the driver's own `sqlite3.DatabaseError` from the identity read,
   which both clients catch and report verbatim"*. Three things. (a) *"exactly as any other client
   does"* — the hook makes no identity read (`hook/connect.py:344-346`, `architecture.md:586-592`), so
   it meets this as a service that fails to start, through its degraded path; only `zikaron-mcp` meets
   it as the CLI does. (b) *"the service cannot start"* is true but is not the route: `connection.py:
   423-424` runs `_read_store_identity` *before* `connect_start_if_absent`, so the error is raised in
   the client before any spawn is attempted — and equally when a service is already listening, having
   opened the file before it was clobbered or its permissions changed; the row's own next sentence
   names the identity read, so the two sentences give different mechanisms. (c) *"both clients"* in a
   corpus where that phrase means hook plus MCP (`CLAUDE.md:338`, `harness.md:464`, `schema.md:783`)
   reads as the hook catching an error it never sees. **Fix:** *"**One route since M31, where there
   were two**: the CLI is an RPC client and meets this as `zikaron-mcp` does — `ServiceConnection`'s
   identity read fails before any service is asked to start, so the failure arrives while the
   connection is being established rather than from a listing. A `memory.db` that is not a database at
   all raises the driver's own `sqlite3.DatabaseError` from that read, which both of those clients
   catch and report verbatim, since nothing invented at that boundary would say it better; the hook
   makes no such read and meets this as a service that will not start (`architecture.md` §"Degraded
   modes")."* The `registry_unavailable` sentence that follows is fine as it stands.

3. **[NITPICK] `connection.py:12-16` still describes only the MCP holder after `:1-2` widened it.**
   *"no service call happens until the model calls a tool … which is what lets one process serve many
   tool calls without repeating the ~101 ms cold start-if-absent cost"* — the paragraph that follows
   from the sentence round 7 changed, in the sense `CLAUDE.md` §"How this project works" means. The
   reuse property is the CLI's case too, and not idly: `refresh --wait` polls `knowledge_status` once a
   second over that one socket (`main.py:475`), so a command that reconnected per request would pay
   the sequence every poll. *"no service call happens until the model calls a tool or a verb runs — …
   which is what lets one process serve many tool calls, or one `--wait` poll every second, without
   repeating …"*.

4. **[NITPICK] "A third client" means two different things one row apart in the corpus.**
   `design/overview.md:186` (D31): *"`zikaron knowledge` is a third client"*; `client.py:19-20`:
   *"which is the point of reusing it rather than writing a third client"*. The first counts service
   clients; the second counts transport implementations (`hook/connect.py`, `mcp/connection.py`). A
   reader holding both sees the CLI described as a third client that was not written as one.
   `client.py:20` → *"rather than writing a third transport"*.

5. **[NITPICK] Done-when 4's *"the CLI's envelope carries `kind: "cli"`"* is pinned by nothing, and
   this is the test half of round-1 finding 5 that round 2 re-verified only the code half of — my
   omission.** `client.py:35` derives `CLIENT_KIND` from the enum, so asserting the two equal is a
   tautology; what is unpinned is that the envelope `KnowledgeClient.call` builds (`client.py:93`)
   carries it. `_InProcessClient` overrides `call` (`test_knowledge_cli.py:134`), so that line never
   runs in the unit suite, and the integration file runs it for real but would pass with
   `ClientKind.MCP.value` there too, since `envelope.resolve` accepts every member. One test: a
   `ServiceConnection` double whose `request` records `envelope.kind` and answers `{"result": {}}`;
   `await KnowledgeClient(double).call("knowledge_list", {})`; assert the recorded kind is `"cli"` —
   the literal, since the point is the value on the wire, not the constant's name.

6. **[NITPICK] A test docstring names a path the test's double skips.**
   `tests/test_knowledge_cli.py:946-948`: *"the identity read every call makes is where this command
   meets it"*. Under `_InProcessClient` there is no identity read — the bare `sqlite3.DatabaseError`
   comes from `context_over`'s own `Store.open` (`:135`), which raises the same error from the same
   pragma, so `_execute`'s branch is exercised and the assertion is sound; only the sentence about
   *where* is not true of what runs. *"— here the double's own service-context open stands in for the
   identity read, which raises the identical bare error."*

7. **[NITPICK] One ragged wrap remains in the `--wait` passage.** `design/knowledge-index.md:2468`
   is ~71 characters and is not paragraph-final (`:2469` follows at ~91), so the brief's *"every
   remaining short line is paragraph-final or inside the fenced command block"* is off by one line.
   The ~130-character line at `:2481` and the short `:2484` are in the foreground-refusals paragraph
   round 6 agreed is not this milestone's. Cosmetic; nothing in the gate reads them.

### Round-7 items, re-verified

1 (`connection.py:1-2`, `:222-225` names all three kinds with the module, `:133-135`;
`rpc.py:196-199` — and the "both" is exact per the two greps in the summary); 2
(`knowledge-index.md:2405-2407`: full heading, and the paragraph is wrapped at the house width);
3 (`client.py:15-16` names `SCHEMA_INCOMPATIBLE`); 4 (`main.py:188-189`); 5 (`scope.py:9-11` states
the present tense only); 6 (`overview.md:186`, *"of its own"* — finding 1 is a different clause of the
same amendment); 7 (`FINDINGS-archive.md:3253-3254`, pointer only). The four self-caught items are
as described: `client.py:19` (*"every client of it adopts — this command included"*), `main.py:
197-199` (all three codes, with which side each falls on), and the two wraps. None re-raised.
Rounds 1–6 unchanged since round 7's re-verification; done-when 1 through 8 still hold as traced
there, and 9 is `./check.sh` here with the matrix satisfied by the PR per `CLAUDE.md`.

VERDICT: NEEDS_CHANGES

---

## Round 9 — 2026-09-24

### Summary judgment

Every round-8 item is applied as described, and I re-read each against the tree rather than the
brief: D31's decision cell is struck and corrected without nested bold, the §11 row names the route
and excepts the hook, `connection.py`'s reuse paragraph names both holders, `client.py` counts
transports, the envelope kind is pinned, and the docstring names the double. The code path is
unchanged since round 7 and I re-walked `_refresh` → `_await_builds` for the empty sweep, the
removed-mid-wait cell and the unreadable-mid-build cell without finding anything new. What keeps
this from APPROVED is a class no round has looked at because it sits outside done-when 7's list of
documents: the milestone added an **eighth** knowledge method and a **third** tool-less method, and
the corpus's own counts of both — in the normative RPC listing that calls itself the only place a
client implementer reads a method name off, and in three module docstrings — still say seven and two.
Plus the new chained integration test races `add`'s indexer for a lock `remove` refuses on, the same
class round 4 fixed in its neighbour. The rest is nitpicks.

### Findings

1. **[IMPROVEMENT] `knowledge_unlock` is missing from the normative method list, and every
   enumeration of the tool-less methods still counts two.**
   - `design/architecture.md:2047-2054`: the knowledge bullet names seven methods —
     `knowledge_search` through `knowledge_refresh` — and `knowledge_unlock` is not among them, though
     `:2051-2052` says these are *"named here because they are served by this socket and belong on any
     list of what this service answers"* and `:2011` says this section *"is the only place a client
     implementer should read a method name off"*. `:2002-2004`: *"Five methods depart from that, for two
     reasons … `memory_surface` and `memory_plan_groups` have no tool"* — six depart now, three of them
     tool-less. Nothing parses this list against `KNOWLEDGE_METHODS` (the set is pinned only at
     `tests/test_service_knowledge_management.py:992`), which is why it survived eight rounds.
     **Fix:** add `knowledge_unlock(knowledge_base)` to the bullet — *"and `knowledge_unlock(knowledge_base)`,
     the one with no tool: `zikaron knowledge refresh --force-unlock`'s method (§8.4, §9)"* — and make
     the departures sentence *"Six methods depart from that, for two reasons … `memory_surface`,
     `memory_plan_groups` and `knowledge_unlock` have no tool — the hook, the consolidator's own client and
     `zikaron knowledge` call them"*.
   - `zikaron/service/dispatch.py:12` (*"The knowledge index's seven methods"*), `:32-33`
     (*"`memory_surface` and `memory_plan_groups` are the methods with no tool"*), `:322` (*"the seven
     knowledge methods"*) — and `:16` of the same paragraph says *"no count is written here"*. **Fix:**
     delete both counts (*"the knowledge index's methods"*), and at `:32-33` add `knowledge_unlock`,
     *"the knowledge command calling the third"*.
   - `zikaron/mcp/primary.py:20-22`: the same two-member enumeration. Same fix. While there, `:22`
     *"before either dispatch table is reached"* — `dispatch.py:323` says `server.py` merges three;
     pre-existing, but the sentence is being edited anyway.
   - `design/knowledge-index.md:2494`: *"the only **method with no tool**"* — true of the knowledge
     subsystem, false of the service, and the wording is round 1's (mine). *"the only knowledge method
     with no tool"*; `:1587`'s *"an eighth RPC method with no tool beside it"* is right as it stands.

2. **[IMPROVEMENT] The chained rename/remove integration test races `add`'s indexer for the lock,
   and `remove` refuses on a live one.** `tests/test_knowledge_cli_integration.py:245-266`: `add`
   spawns a detached indexer, and `remove --yes` follows within milliseconds.
   `lifecycle.remove` (`zikaron/core/knowledge/lifecycle.py:384-391`) raises `IndexerBusyError` when
   `observed.blocker` is set — a lock whose holder this host cannot show is dead, which a live local
   pid is — and the CLI renders that as `refused: …` and exits 1, so `assert main(...) == 0` at `:265`
   fails. The indexer takes its lock only after Python start and the model load — the one-to-three-second
   window round 2 quantified — so the test wins by a wide margin, and loses only when its own process is
   starved on the required macOS job while the child it spawned is not: the class round 4's finding 1
   closed in the neighbouring test. **Fix:** insert `assert main(["--project", str(reaped), "refresh",
   "docs", "--wait"]) == 0` between the `add` and the `rename` (`:260`). The wait handles both outcomes
   (round 2's fix), the cost is the build `add` was going to run anyway, and the docstring at `:237-240`
   gains one sentence saying the wait is there so `remove` meets a corpus nothing is building.

3. **[NITPICK]** `FINDINGS.md:220`: *"both local gates green across 3.12, 3.13 and 3.14"* — the
   brief reports `./check.sh` only, and `tests/test_knowledge_cli.py` (code, not prose) changed this
   round. Per `CLAUDE.md` the PR satisfies the matrix, so nothing needs running; the sentence just
   claims more than is known of this tree. *"`./check.sh` green; the matrix is the PR's (`CLAUDE.md`
   §"The check gate")"*.

4. **[NITPICK] A derived ratio beside the two figures it derives from.** `FINDINGS.md:238` *"differ by
   300×"* and `zikaron/core/store/migration.py:74` *"~300x faster"* — 530 / 2 is 265. Both sites state
   the two measurements alongside, and those are what a reader re-derives with the spike. Delete the
   ratio at both; this corpus's own record is that a corrected number comes back stale and a deleted one
   stays dead.

### Round-8 items, re-verified

1 (`overview.md:186`: the decision cell reads *"~~both stdlib-only~~ the hook stdlib-only, `zikaron-mcp`
on `fastmcp` since M9"* and the new sentence cites §Components and the M9 decision; bold pairs close
where they open — no nesting); 2 (`knowledge-index.md:2553`: *"One route since M31, where there were
two"*, `ServiceConnection`'s read *"before any service is asked to start"*, *"both of those clients"*,
and the hook *"makes no such read"*; the §"Degraded modes" citation is the corpus's own truncated form,
used at twenty-odd other sites); 3 (`connection.py:12-16`: *"or a verb runs"*, *"or one `refresh --wait`
poll every second"* — both edits present this time); 4 (`client.py:20`: *"a third transport"*); 5
(`test_knowledge_cli.py:1470-1494`: `_Recording.envelope` records `kind`, `recorded == ["cli"]` on the
literal); 6 (`:946-949`); 7 (§9 re-wrapped as the brief says; I did not re-scan mechanically and take
the awk result as stated). None re-raised. Rounds 1–7 unchanged since round 8's re-verification;
done-when 1 through 8 still hold as traced there, and 9 is `./check.sh` here with the matrix satisfied
by the PR per `CLAUDE.md`.

VERDICT: NEEDS_CHANGES

---

## Round 10 — 2026-09-24

### Summary judgment

All six round-9 changes are applied as described, and I re-read each against the tree rather than
the brief: the RPC listing names `knowledge_unlock(knowledge_base)` with a parameter that matches
`dispatch_knowledge.py:421`, the departures sentence counts six with three tool-less, both counts in
`dispatch.py` are gone and its enumeration and `primary.py`'s name all three, §9 says *knowledge*
method, the chained integration test waits before `rename`, and the ratio is deleted at both sites.
With the code path unchanged since round 7, this round went to what no earlier round had opened: the
migration step against SQLite's own mechanics — `event` has no trigger, view or foreign-key referrer
for `DROP TABLE` to take with it (`ddl.py`, none declared), `id` is copied so D30's `event.id`
ordering survives the rebuild, `foreign_keys=ON` has nothing to check on that table, and the "no gap,
no repeat" claim §"Migration posture" and D37 make of `test_store.py` is a real assertion (`:48-54`);
the wait's cost model; and what the two schema documents say of a version *below* the range. The
code ships. What remains is prose: the entry-page paragraph this milestone extended still counts two
clients and calls both stdlib-only while the decision table beneath it says three and one, and two
normative sentences say a version below the range opens when `meta.py` refuses it. A phrase each.
The rest is nitpicks.

### Findings

1. **[IMPROVEMENT] The one-page description and the decision table disagree, inside one document,
   on how many clients there are and which are stdlib-only.** `design/overview.md:75-76`: *"two thin
   stdlib-only clients — the MCP server and the hook — that start the service if it is absent"*, in
   the paragraph this milestone extended at `:78-84` (*"The service is the only spawner since
   M31"*). Twelve rows down, D31 (`:186`) — as corrected in round 8 — reads *"the hook stdlib-only,
   `zikaron-mcp` on `fastmcp` since M9"* and *"`zikaron knowledge` is a third client rather than a
   store-opener of its own"*. `CLAUDE.md` sends every fresh session to `overview.md` first, and §"The
   system in one page" is what it reads before the table. The diagram at `:103` does show
   `zikaron knowledge ──► zikaron-service`, so the paragraph is now the only place in the file that
   counts two. **Fix:** `:75-76` → *"two thin clients — the MCP server, on `fastmcp`, and the
   stdlib-only hook — that start the service if it is absent, **and since M31 a third,
   `zikaron knowledge`, which reaches the service the same way** (D31)"*. The *Five processes* count
   can stay: the CLI is a command rather than a component, which is what D31's cell says. **While
   there:** `:104`'s annotation *"opens the store directly, no RPC"* is column-aligned under
   *detached indexer process* but sits on the line whose left-hand label is *(a person, from a
   shell)*, so a reader scanning the row reads it of the CLI — the misreading round 5 corrected three
   sites to prevent, in the one ASCII line that fix could not reach. *"— the indexer opens the store
   directly, no RPC"* removes it.

2. **[IMPROVEMENT] Two normative sentences say a version below the supported range opens; the code
   refuses it.** `design/architecture.md:1965` (the `schema_incompatible` row): *"A version
   \*below\* the range is not this error: it opens, and the service alone migrates it."*
   `design/schema.md:444` (the `meta` keys table): *"Below it, the store is opened as it is and
   migrated only by the service"*, where *it* is *the supported range* named two cells earlier.
   Below the range is `0` or less, and `core/store/meta.py:102-104` refuses that as `bad_config`
   (`"int >= 1"`) — which `schema.md:438` (*"a value below `1` or unparseable is `bad_config`"*) and
   `:1439`'s posture table both state, so each document contradicts itself, and the error table does
   so one row after the `bad_config` row that says the opposite. Both sentences mean *inside the
   range but below `CURRENT_SCHEMA_VERSION`*, and both are this milestone's. **Fix:**
   `architecture.md:1965` → *"A version inside the range but below `CURRENT_SCHEMA_VERSION` is not
   this error: it opens, and the service alone migrates it; below the range is `bad_config`, the row
   above."* `schema.md:444` → *"Inside it but below `CURRENT_SCHEMA_VERSION`, the store is opened as
   it is and migrated only by the service; below `1` is `bad_config`."*

3. **[NITPICK] `--wait` polls every corpus once a second for the life of the wait, even when one was
   named.** `main.py:475` (`_await_builds`) and `:389` (`_scan_marks`) call `knowledge_status` with
   `knowledge_base: None`, and `reporting.status` opens each registered corpus's database per call.
   A `refresh docs --wait` on a project with twenty corpora is twenty opens a second for the minutes
   one build takes, to watch one. `knowledge_status(knowledge_base)` already exists and the reports
   are keyed by name either way; pass `args.name` through when it is not `None` — the sweep needs
   all, and a sweep is the only case that does. Optional: cost, not correctness.

4. **[NITPICK] `FINDINGS.md:58`'s D31 index row does not say it was amended.** D1's row (`:28`)
   carries *"amended 2026-09-15"* for its amendment; D31's — whose amendment is this milestone's —
   reads as it did before M31, and the index is the one thing a fresh session sees without opening
   the table. Append *"— **amended at M31**: `zikaron knowledge` is a third client, not a
   store-opener"*.

### Round-9 items, re-verified

1 (`architecture.md:2002-2004`, `:2048-2054` — `knowledge_unlock(knowledge_base)` matches
`dispatch_knowledge.py:421`'s `require_str(params, "knowledge_base")`, and `knowledge_refresh(name,
full)` matches `:394, 400`; `dispatch.py:12, 32-35, 323`; `primary.py:20-23`;
`knowledge-index.md:2494`); 2 (`test_knowledge_cli_integration.py:242-245, 267` — `refresh docs
--wait` between the `add` and the `rename`, and the docstring says why); 3 (`FINDINGS.md:220-221`);
4 (`FINDINGS.md:238-244` and `migration.py:75-76` carry the two measurements and the spike, no
ratio). None re-raised. Rounds 1–8 unchanged since round 9's re-verification; done-when 1 through 8
still hold as traced there — 2's argv parity is `test_service_knowledge_management.py:1077` against
`detach.spawn`, and 8's remedy is `store.py:112-134`, corrected rather than deleted — and 9 is
`./check.sh` here with the matrix satisfied by the PR per `CLAUDE.md`.

VERDICT: NEEDS_CHANGES

---

## Round 11 — 2026-09-24

### Summary judgment

All four round-10 items are applied and I re-read each against the tree. The new material — the
`zikaron/project/` package, the storeless refusal and `zikaron init` — is the right shape: the check
runs before any connection (`knowledge/main.py:177-182`), the ancestor walk binds nothing, the rung
is named, and the integration fixture builds its store through the real command against a real
service. What stops it shipping is the predicate `init` itself keys on. `has_store` is *the
directory exists*, and the service creates that directory **before** it creates the store —
`service/main.py:217` runs `permissions.ensure_store_dir` for the log's sake ahead of `assemble` —
so every first start that fails or is still running leaves a `.zikaron/` with no `memory.db`, a
state in which `init` answers "already initialized" for a store that does not exist and the next
verb goes on to create it through the service. That falsifies the sentence this change writes into
nine places, "the only command that creates a store", in exactly the scenario (a cold cache, a miss
at the deadline) the change's own open question names. Beside it: the refusal under the
`--project` rung advises passing `--project`, `init --project <typo>` builds a directory tree and a
store in it, and a hand-exported `CLAUDE_PROJECT_DIR` equal to the cwd sends the reader round the
loop the docstring says it must not. The rest is nitpicks.

### Findings

1. **[BLOCKER] `init` reports "already initialized" and creates nothing whenever `.zikaron/` exists
   without `memory.db` — and the service produces exactly that state on every failed or unfinished
   first start.** `zikaron/project/resolve.py:53-60`: `has_store` is `self.store_dir.is_dir()`.
   `zikaron/project/initialize.py:36-38` returns 0 on it without connecting, and `_create`'s
   post-check at `:51` tests the same predicate — vacuous once the service answered `health`, since
   the directory precedes the socket. The order that makes this reachable is the service's own:
   `zikaron/service/main.py:217` `log.configure_service_log(service_log_path(_ensure_store_dir_exists(store_dir)))`
   runs *before* `_assemble_or_log_and_raise`, and `permissions.ensure_store_dir` (`permissions.py:89`)
   is `mkdir(parents=True)` — `architecture.md:699-714` documents the ordering as deliberate. So a
   first start that dies inside `assemble` (offline with a cold cache; a bad `.zikaron/config.toml`;
   the Q17 miss, where `init` has already printed `failed:` while the fetch continues) leaves
   `.zikaron/service.log` and no database. From there: (a) a second `init` exits 0 with
   `already initialized <dir>/.zikaron` and a provisioning script proceeds; (b) the next `knowledge`
   verb passes `has_store`, connects, and the **service** creates the store — which is the M31 defect
   with one extra directory level of precondition; (c) on a cold cache that verb meets the 10 s
   deadline `FINDINGS.md:391` and `knowledge-index.md:2438-2439` say only `init` can meet. The claim
   is false in that state at `design/distribution.md:142, 146`, `design/overview.md` D31,
   `design/knowledge-index.md:2417, 2438-2439`, `README.md:471`, `design/coding-standards.md:33-34`,
   `FINDINGS.md:233, 391`, `initialize.py:1` and `__init__.py:1`. And the test pins the wrong branch:
   `tests/test_project_scope.py:31-35` builds `initialized` as an *empty* `.zikaron/`, and
   `:201-211` asserts that `init` then touches no service.
   **Fix (init — required):** branch on the database. Add `Project.has_database`
   (`(self.store_dir / "memory.db").is_file()`) and use it at `initialize.py:36` and `:51`;
   connecting when the directory exists and the file does not is harmless
   (`architecture.md:686-688`: a second `assemble` opens what is there). Tests: the idempotency
   fixture creates `.zikaron/memory.db` (an empty file suffices — `init` opens nothing on that
   branch); add the negative — `.zikaron/` holding only `service.log`, `initialize.connected`
   patched to record the call, assert the call was made and "already initialized" was not printed.
   **Fix (verbs — the operator's call, and I recommend the first):** (i) make `has_store` the same
   `memory.db` test, so "the only command that creates a store" is true of the tree. A config-only
   `.zikaron/` then costs its author one `zikaron init`, which is the deliberate-act argument
   `distribution.md:147-149` makes; the refusal for that case should say so (*"`.zikaron/` is
   there but holds no store; `zikaron init` creates one"*), and the `has_store` docstring's *"the
   service completes it on its next start"* goes, since that completion is what `init` now owns.
   (ii) Keep the directory predicate and weaken the claim at every site above to *"the only command
   that creates a store in a project that has never had a `.zikaron/`"* — which is the property the
   code actually keeps, and a weaker one than anybody meant.

2. **[IMPROVEMENT] Under the `--project` rung with no store above, the refusal tells the reader to
   pass `--project`.** `resolve.py:113-117`: `found is None` yields `pass --project to name the
   project` regardless of origin. What `zikaron knowledge --project /x list` prints:
   ```
   refused: no Zikaron store in /x
            (resolved from --project)

     pass --project to name the project
     or `zikaron init` to create a store here
   ```
   This is the class `test_moving_is_not_offered_when_the_directory_did_not_come_from_the_shell`
   guards for `cd`, and `resolve.py:6-7` states the rule for this rung too (*"a mistyped `--project`
   is not fixed by exporting one"*). It is the one cell both end-to-end tests exercise —
   `test_project_scope.py:197` and `test_knowledge_cli_integration.py:129` — and both assert only
   the first line. **Fix:** name the origin — `EXPLICIT_PROJECT: Final = "--project"` beside
   `WORKING_DIRECTORY`, used at `:76`; in `refusal`, when `project.origin == EXPLICIT_PROJECT` and
   `found is None`, print `  check the path given to --project` instead of the `pass --project` line;
   add the cell to `TestTheRefusal` asserting `"pass --project" not in printed`.

3. **[IMPROVEMENT] `init --project <path that does not exist>` creates the whole tree and a store in
   it.** `initialize.py` never checks `project.directory.is_dir()`, and `ensure_store_dir` is
   `mkdir(parents=True)` (`permissions.py:89`). The verbs' refusal for a mistyped `--project` ends
   with *"or `zikaron init` to create a store here"* (`resolve.py:124`), so the corpus's own remedy
   turns a typo into a project directory holding a store, a running service and a socket — the
   second-store defect by another route. **Fix:** in `initialize.main`, before the `has_store`
   branch: `if not project.directory.is_dir(): stderr(f"refused: {project.directory} is not a
   directory (resolved from {project.origin})"); return 1`. One test. Optionally the verbs' refusal
   says *"is not a directory"* for the same case rather than *"no Zikaron store in"*, so the `init`
   line is not offered there at all.

4. **[IMPROVEMENT] A harness variable equal to the cwd is reported as the working directory, and the
   docstring's claim that "the two remedies coincide" is false.** `resolve.py:80-82` reports the
   variable only when `directory != working`; `:72-73` asserts the remedies coincide otherwise.
   They do not: with `CLAUDE_PROJECT_DIR` exported by hand to the subdirectory the reader stands in —
   the "wrong `CLAUDE_PROJECT_DIR`" case done-when 9 names — origin is `the working directory`,
   `moving_helps` is true, the message says *"run this from <root>"*, the reader `cd`s, and
   `store_scope_dir` returns the variable again: refused, one loop later, with the other origin. That
   is the loop `:101-104` says the message must never send anyone round. **Fix:** report the
   variable whenever it was *used*, not only when it differs. Cleanest at the seam:
   `HarnessSpec.named_project_dir() -> Path | None` returning the usable value (absolute, existing)
   or `None`, with `store_scope_dir` becoming `self.named_project_dir() or fallback` — one predicate,
   not two — and `resolve` reporting `f"${spec.project_dir_variable}"` when it is not `None`. Test:
   marker set, variable = `deep`, `chdir(deep)` → origin `$CLAUDE_PROJECT_DIR`. Delete the
   docstring sentence.

5. **[IMPROVEMENT] The deadline miss — the one failure this change says is `init`'s alone — prints
   nothing actionable.** `lifecycle.py:462` raises *"no server became reachable at <sock> before
   the deadline"*; `project/report.py:48-54` prints `failed: <that>` and returns 1. `client.py:115-119`
   and `knowledge-index.md:2437-2449` both say the service keeps starting and a second run succeeds,
   and neither sentence reaches the person who just got exit 1 from a provisioning script. This does
   not decide Q17 — it makes the failure name its remedy, which is the standard every other refusal
   in this change meets. **Fix:** in `_create`, wrap the `async with connected(...)` in
   `try: ... except ConnectionError as error: raise ConnectionError(f"{error}; the service keeps
   starting after this command gives up — on a cold model cache it is fetching the embedding
   artifact — so run `{prog}` again") from error`, threading `prog` from `main`. Test: patch
   `initialize.connected` to raise `ConnectionError`, assert stderr names the retry.

6. **[NITPICK] Q17's title asks whether `init`'s deadline needs to exceed the hook's; it already
   does, by eight times.** `FINDINGS.md:388`: `init` polls under
   `lifecycle._HEALTH_POLL_DEADLINE_SECONDS` (10 s), the budget `zikaron-mcp` shares; the hook's
   1.2 s is `hook/connect.py:59`, which this path never runs. *"Does `zikaron init` owe a connect
   deadline longer than the 10 s it shares with `zikaron-mcp`?"*; `:395-396`'s contrast with the
   hook can stay as a contrast. Same subject: `initialize.py:8` *"On a cold model cache that call
   pays the artifact's fetch"* — inside the deadline; past it the command exits 1 while the service
   goes on fetching, which is Q17. One clause.

7. **[NITPICK] README shows the verbs before it says they refuse.** `README.md:457-463` is the
   four-verb block, `:465-469` the refusal, `:471-472` `init`. A reader following top-down types
   `knowledge list` first and is refused. Put `zikaron init` as the block's first line, or move the
   `init` paragraph above it.

8. **[NITPICK] `FINDINGS.md` §M31 restates rationale the corpus holds.** `:242-244` (verb over flag,
   with the reason) duplicates `distribution.md:147-149`; `:246-251`'s explanation duplicates
   `resolve.py:9-12`. Round 2's finding 4 and `CLAUDE.md` §"Project memory" want the decision plus
   pointer; the re-derive command at `:249-251` is the measured fact and stays.

9. **[NITPICK]** Re-wrap: `design/knowledge-index.md:1313` is ~150 characters and `:2413` ~70 and
   not paragraph-final, both in passages this change wrote. Cosmetic.

### On the declined eleventh finding

Agreed. `build-plan.md:3189` and `:3349` are M30's brief and record what M30 shipped; current
inventory lives at `distribution.md:136`, which names four.

### Round-10 items, re-verified

1 (`overview.md:75-77` counts three clients with the split stated; `:104-105` *"the indexer opens
the store directly"*); 2 (`architecture.md:1974`, `schema.md:444` — both say *inside the range but
below `CURRENT_SCHEMA_VERSION`*, and *below the range is `bad_config`*); 3 (`main.py:306, 334-335,
345-355, 435-436, 445` — `name`/`only` threaded to both status calls); 4 (`FINDINGS.md:58`).
None re-raised. Rounds 1–9 unchanged since round 10's re-verification. **Done-when 9 as traced:**
the check precedes the connection (`main.py:177-182`), the refusal leaves no `.zikaron/`
(`test_project_scope.py:199`, `test_knowledge_cli_integration.py:131-132`, and the integration
test also asserts no service answered), the rung is named, the monorepo shape is covered
(`:129-135`), and idempotency holds on the directory — which is finding 1. **Done-when 1 as
re-scoped:** the integration fixture runs `init` for real (`:89-99`) and all six verbs then meet the
service (`:135-320`). 10 is `./check.sh` here with the matrix satisfied by the PR per `CLAUDE.md`.

VERDICT: NEEDS_CHANGES

---

## Round 12 — 2026-09-24

### Summary judgment

All nine round-11 items are applied as described and I re-read each against the tree: `has_store`
and `nearest_store_above` key on `memory.db` (`resolve.py:66, 105`), `init` connects when only the
directory exists and refuses a non-directory before creating anything (`initialize.py:38-47`), the
rung comes from `named_project_dir()` (`spec.py:194-211`, `resolve.py:90-93`), the deadline miss
names the retry (`initialize.py:62-70`), and the tests pin each. What stops this shipping is a defect
in the one line round 1 itself specified: `--project` is made absolute but not *resolved*, and this
is the first client whose store path is typed rather than harness-supplied. The socket is keyed on
the resolved path while store identity is compared on the spelled one, so `zikaron init --project ..`
— or any `--project` through a symlink, `"$PWD"` included — starts a service the agent's own MCP
server and hook then refuse with `store_identity` on every call until it idles out. One word fixes
it. Beside that: `init` reports "already initialized" on the `memory.db` a create that failed after
connecting leaves behind, the storeless refusal gives a repairing reader the lost reader's advice,
and four sites say every other command needs a store when `install` and `doctor` do not.

### Findings

1. **[BLOCKER] `--project` hands the service a spelling of the store path no other client produces,
   and store identity is compared on spellings — so a service `init` starts through `..` or a
   symlink is one the agent's own clients refuse for the life of that service.**
   `zikaron/project/resolve.py:89` `explicit.absolute()`: `Path.absolute()` neither collapses `..`
   nor follows symlinks. `zikaron/mcp/connection.py:94-100` keys the socket on `store_dir.resolve()`
   and keeps `store_dir` as spelled; `:423` derives `store_db_path` from the unresolved directory and
   `:431-433` passes the same to `default_server_command`; `service/main.py:416` takes it as
   `Path(sys.argv[2])`, unresolved; `service/dispatch.py:114` reports `str(ctx.store_path)` in
   `health`; and `lifecycle.py:366`, `:372-376` and `hook/connect.py:200` compare
   `store_db_path != Path(health.store_path)` — lexical `Path` equality. Trace: `zikaron init
   --project ..` from `/p/sub` gives directory `/p/sub/..`, the socket of `/p/.zikaron`, and a
   service started with store dir `/p/sub/../.zikaron`, whose `health.store_path` is
   `/p/sub/../.zikaron/memory.db`. The MCP server spawned at `/p` computes `/p/.zikaron/memory.db`
   (`Path.cwd()` is physical; `CLAUDE_PROJECT_DIR` is whatever the harness spelled), reaches the
   same socket, and gets `STORE_IDENTITY` on every tool call; the hook gets `StoreIdentityError` on
   every prompt and prints nothing. The same happens with `--project ~/code/p` where `~/code` is a
   symlink, or `--project "$PWD"` — bash's `$PWD` is the logical path — against a physical
   `Path.cwd()`. Both are ordinary in the provisioning script `--project` exists for, and before M31
   every path reaching the service came from `Path.cwd()` or a harness variable, so the spellings
   agreed by construction. The reverse order is loud — the CLI is refused with both paths shown;
   this order is silent for the hook and a wall of refusals for the agent. Round 1's finding 7 asked
   for `.absolute()` and that was insufficient; that was mine. **Fix:** `explicit.resolve()` at
   `resolve.py:89`, which is what `Path.cwd()` already gives the fallback rung in every client;
   catch `OSError` from it (a symlink loop — `hook/spawn_warm.py:57` records that `resolve()` raises
   there) and refuse naming the rung. Tests in `TestWhichRungAnswered`: `chdir(tmp_path / "sub")`,
   `resolve(Path("..")).directory == tmp_path.resolve()` — fails today with `tmp_path/sub/..`; and
   `link.symlink_to(real)`, `resolve(link).directory == real.resolve()`. `nearest_store_above` gets
   the same repair for free: `Path("/p/sub/..").parents` starts at `/p/sub`, a sibling, so today a
   refusal can name a store "above" that is beside. **Not this milestone's, but worth one sentence
   in `architecture.md` §"Store identity is verified, not assumed":** the socket is keyed on the
   resolved path and identity on the spelled one, so two clients spelling one directory differently
   share a socket and refuse each other; the fallback rung's `Path.cwd()` is what keeps the spellings
   equal, and `CLAUDE_PROJECT_DIR` is taken verbatim by all three.

2. **[IMPROVEMENT] `init` reports "already initialized" on the `memory.db` a create that failed
   after connecting leaves behind — a file the service will refuse to open on every later start.**
   `core/store/connection.py:179-196`: `aiosqlite.connect(db_path)` creates the file (the
   `db_path.stat()` at `:195` depends on it), and `_load_sqlite_vec` and the pragmas run *after*;
   `store.py:312-320` runs the DDL after that and closes without unlinking on failure. So an
   extension that will not load — the interpreter `doctor` exists to flag — a pragma failure, a full
   disk, or a kill inside the DDL leaves a 0-byte `memory.db`. The tree names this state twice as
   real (`store.py:97-98` *"left behind by a process that failed between creating the file and
   running its DDL"*; `:303-304` *"left behind by an earlier failed attempt"*). From there:
   `_open_or_create` (`context.py:246`) sees the file and calls `Store.open`, which raises
   `bad_config` `schema_version=<missing>` (`meta.py:74-75`) — the service never starts again;
   `has_store` (`resolve.py:66`) is true, so `init` prints `already initialized` and exits 0
   (`initialize.py:45-47`) and a provisioning script proceeds; every verb connects and is refused by
   the identity read with the same `bad_config`, which names a key and not a file to delete. Not a
   blocker: no second store, no data lost, and the verbs refuse by code rather than silently; but
   the command whose one job is to say whether the project is ready says yes when the answer is
   permanently no, and done-when 9's *"covered by the state a failed first start leaves"* does not
   cover this one. The Q17 miss cannot produce it — the fetch (`context.py:252`) precedes the
   connect — so the trigger is a broken install or a mid-DDL failure. **Fix (recommended):** drop
   the short-circuit — `init` always connects and sends its one `health`, printing `already
   initialized` when `has_store` was true beforehand. The identity read then reports the broken
   file by disposition, exactly as a verb would; idempotency is unchanged (exit 0); the cost is at
   most the service start the next command in the script pays anyway, so README `:468`'s *"costs
   nothing"* becomes *"costs at most a service start"*; `test_initialize_is_idempotent_and_touches_no_service`
   (`test_project_scope.py:260-270`) becomes *reaches the service and still says so*. It stays inside
   the operator rule, since nothing opens the store. **Minimum acceptable:** keep the short-circuit
   and state the limit at `has_store`'s docstring, `distribution.md:147-150` and `initialize.py:6-10`
   — a `memory.db` the service cannot open is reported as initialized, and the verbs' `bad_config`
   naming a `<missing>` `meta` key is the signal, with removing the file the repair. Either way,
   `test_project_scope.py:47-52`'s fixture docstring should stop calling an empty `memory.db` *"a
   project holding a store"* — it is exactly the artefact above — and say instead that nothing in
   the file opens one.

3. **[IMPROVEMENT] The half-started refusal diagnoses a repairing reader and then advises a lost
   one.** `resolve.py:123-140`: after *"`<dir>/.zikaron` exists but holds no store"* the function
   goes on to the ancestor search and the rung line, so under the working directory it prints *"pass
   --project to name the project, or run this from its root"* to somebody whose `.zikaron/` is right
   there, and under `--project` it prints *"check the path given to --project"* for a path that is
   demonstrably correct. The comment at `:124-125` says which reader this is; the lines that follow
   do not act on it. The round-11 test (`test_project_scope.py:226-230`) asserts only the presence of
   the new line. **Fix:** when `store_dir_exists`, append the half-started line and the `init` line
   and return — no ancestor, no rung advice; add `"pass --project" not in printed` and `"check the
   path" not in printed` to that test, under both rungs.

4. **[IMPROVEMENT] Four sites say every other command needs a store; `install` and `doctor` do
   not.** `zikaron/cli/main.py:71` (`--help`'s own line for `init`: *"which every other command
   needs"*), `README.md:466` (*"every other command refuses a project with no store"*),
   `initialize.py:3` (*"every other typed command refuses"*), `distribution.md:145-146` (*"Every
   other typed command now refuses a project whose store does not exist"*). `zikaron install`
   writes harness artefacts and touches no store — `FINDINGS.md:214-215` is explicit that the
   installer never creates one — and `doctor` is the named exemption, so a reader of `zikaron
   --help` concludes `init` must precede `install`, which README's own install sequence does not
   do. `knowledge-index.md:2418` has the scoped form. **Fix:** *"which the `knowledge` verbs
   need"* at `:71`, and *"every `knowledge` verb"* at the other three.

5. **[IMPROVEMENT] `architecture.md` still states the directory predicate round 11 replaced.**
   `design/architecture.md:692-693`: *"every `zikaron knowledge` verb refuses a project with no
   `.zikaron/` before it connects"*. The predicate is `memory.db` (`resolve.py:58-66`,
   `build-plan.md:3643`, `distribution.md:147-150`), and this is the §"First run" paragraph that
   documents the log-before-store ordering that made the directory the wrong test — so the one
   section explaining *why* the predicate is the file is the one still naming the directory. The
   round-11 site list ran to nine files and missed this one. **Fix:** *"with no store — no
   `memory.db`, since the directory precedes it — before it connects"*.

6. **[IMPROVEMENT] Two normative places disagree about whether `CLAUDE_PROJECT_DIR` reaches a
   process an agent's shell tool spawns, and the new text is on one side without the measurement
   it cites.** `resolve.py:9-12` and `FINDINGS.md:240-245`: the variable *"reaches hooks rather
   than the terminal a person or an agent types in"*, so the fallback rung is *"what every CLI
   invocation actually resolves through"*. `design/harness.md:133-143`: a process tree under an
   enclosing Claude Code session *inherits* `CLAUDE_PROJECT_DIR`, and *"`pytest -m integration_kiro`
   run from inside a Claude Code session is exactly the scenario"* — a Bash-tool subprocess;
   `tests/conftest.py:149-153` deletes the variable for the same reason (*"would otherwise adopt
   whichever project launched pytest — this repository"*). Exactly one is true of a subprocess the
   agent's shell tool spawns. It matters to this change because the refusal's wording rests on which
   rung is *"the usual one"* (`resolve.py:12`), and because if the variable does reach the agent's
   shell, an agent-typed `zikaron knowledge` resolves through the harness rung — the *good* outcome,
   agreeing with `zikaron-mcp` by construction, and the opposite of what the docstring says. The
   FINDINGS paragraph carries a re-derive command (`echo "${CLAUDE_PROJECT_DIR:-unset}"` in a shell
   the harness spawned); I cannot run one from here. **Fix:** run it, once, from the Bash tool of a
   live Claude Code session, and correct whichever side lost — `harness.md:133-143` and the conftest
   comment if it prints `unset`, `resolve.py:9-12`, `FINDINGS.md:240-245` and the docstring of
   `test_neither_harness_exports_a_project_directory_to_a_shell` (`test_project_scope.py:70-79`,
   whose name asserts the runtime claim while its body reads the declaration) if it prints a path.
   Record the result in `research/`, not in FINDINGS.

7. **[IMPROVEMENT] The round-11 fix to the rung is not pinned by the cell it was made for.**
   `test_the_harness_variable_is_honoured_and_named` (`test_project_scope.py:93-107`) sets the
   variable to `tmp_path` and `chdir`s to `deep` — the two *differ*, so the pre-fix comparison
   (`directory != working`) reports the variable there too and the test stays green under the
   mutation. Round 11's finding 4 named the cell: variable `= deep`, `chdir(deep)`, origin
   `$CLAUDE_PROJECT_DIR`. **Fix:** add it, two lines, beside the existing test.

8. **[NITPICK]** `FINDINGS.md:386` is a ~150-character line inside Q17 — one of the two the brief
   says were re-wrapped is not, or a third grew. Cosmetic; nothing in the gate reads it.

9. **[NITPICK]** `test_project_scope.py:349-352`: *"`connected` is what reaches the socket, so the
   `async with` never opens, which is the real shape of a failed connect"* — `connected()`
   constructs `ServiceConnection`, which only computes the location (`connection.py:191-192`);
   the socket is reached inside `client.call` (`:421-434`), so the real failure raises *inside* the
   `async with`. Both shapes sit in `_create`'s `try`, so the test is sound; the sentence about
   where is not. *"— `connected` raising stands in for the `call` that would; both are inside the
   `try`."*

10. **[NITPICK]** `initialize.py:71-73` says *"the service started but no store appeared"* — when a
    service was already listening for a store deleted underneath it, nothing started. *"the service
    answered but no store is at"*.

### Round-11 items, re-verified

1 (`resolve.py:55-71, 97-107`; `initialize.py:45, 71`; `test_project_scope.py:139-147, 175-180,
272-294` — and finding 2 is the state one level further in); 2 (`resolve.py:39, 89, 134-135`;
`:218-224`); 3 (`initialize.py:38-44`; `:332-341`, asserts nothing appears); 4 (`spec.py:192,
194-211`; `resolve.py:90-93`; the docstring sentence is gone — finding 7 is the missing pin); 5
(`initialize.py:59-70`; `:343-358`); 6 (`FINDINGS.md:382-383`; `initialize.py:8-10`); 7
(`README.md:458`); 8 (`FINDINGS.md:233-238`, a paragraph with the pointer, and the re-derive command
at `:252-258` stays); 9 (taken as stated; finding 8 is a third line). The coverage additions are as
the brief says: `test_knowledge_cli.py:1497-1568` drives `KnowledgeClient.call` through
`parse_response` for both raises, the non-object result, `_entries`' two guards and the unknown-code
disposition. None re-raised. Rounds 1–10 unchanged since round 11's re-verification; done-when 1
through 9 hold as traced there, with 9's *"the state a failed first start leaves"* narrowed by
finding 2, and 10 is `./check.sh` here with the matrix satisfied by the PR per `CLAUDE.md`.

VERDICT: NEEDS_CHANGES

## Round 13 — 2026-09-24

### Summary judgment

Nine of the ten round-12 items are applied as the brief describes and I re-read each against the
tree: `explicit.resolve()` with the two-type catch and `report.render` shared by both `main`s
(`resolve.py:99-112`, `report.py:29-36`, `initialize.py:38-42`, `knowledge/main.py:177-181`);
`init` connecting unconditionally with `existed` deciding only the wording (`initialize.py:50-55,
58-63`); the half-started refusal returning after the repair line, parametrised over three rungs
(`resolve.py:146-152`, `test_project_scope.py:279-292`); the four wording sites; `architecture.md:703`;
the research note with its stated limits; the rung pin (`test_project_scope.py:147-160` — the cell
the fix was made for, and it does discriminate the old comparison); the Q17 re-wrap; and items 9
and 10. The tenth is not applied: `README.md:468` still reads *"it costs nothing"*, which the brief
says became *"costs at most a service start"*, and after round-12 #2 that sentence is false on a cold
cache. Beside it, the one new line of code this round added carries a claim that is true on 3.12
only — `Path.resolve()` stopped raising on a symlink loop in 3.13 — so the guard the brief says is
covered by a loop test is exercised on one of three supported interpreters. Nothing blocks; four
things are worth a pass before this ships.

### Findings

1. **[IMPROVEMENT] The `RuntimeError` catch and its comment describe Python 3.12; on 3.13 and 3.14
   a symlink loop does not raise, so the branch is untested there and the loop test passes for a
   different reason.** `resolve.py:102-105`: *"`Path.resolve()` turns `ELOOP` into
   `RuntimeError("Symlink loop from ...")`"*. That is 3.12's `pathlib.py:1228-1253`, whose
   `resolve()` calls `p.stat()` after a non-strict `realpath` and raises `RuntimeError` from
   `check_eloop`. In 3.13 (`pathlib/_local.py:664-670`) and 3.14 (`pathlib/__init__.py:932-938`)
   `resolve()` is `self.with_segments(os.path.realpath(self, strict=strict))` and nothing more, and
   `posixpath.realpath` non-strict on a loop takes `path = newpath; continue`
   (3.13 `posixpath.py:464-469`, 3.14 `:478-483`) — it returns the partly-resolved path and raises
   nothing. So on 3.13/3.14 `test_an_unresolvable_project_is_refused_rather_than_raised`
   (`test_project_scope.py:120-129`) never enters the `except`: `resolve()` returns `<tmp>/loop`,
   `initialize.py:43` finds `is_dir()` false (`ELOOP` is in pathlib's ignored errnos) and prints
   *"is not a directory"* — a refusal, so the `"refused:" in err` assertion holds, but through the
   other branch; a verb on the same path prints *"no Zikaron store in <loop> … check the path given
   to --project"* and offers `init`, which then says *"is not a directory"*. Both are acceptable
   refusals, which is why this is not a blocker. What is wrong: a comment stated as universal that
   is false on two of the three versions the matrix runs and on the one `uv tool install
   --managed-python` will pick; a guard the brief lists as covered that runs uncovered on those two
   (invisible to the ratchet at `fail_under = 95` against 98.13%); and a test docstring (*"A
   symlink loop is the reachable case"*) that names the case the branch does *not* see on 3.13+.
   The branch's version-independent trigger is `OSError` from `os.getcwd()` inside `realpath` when
   `--project` is relative and the working directory has been deleted. **Fix:** keep
   `except (OSError, RuntimeError)`; reword the comment to *"`RuntimeError` as well as `OSError`:
   3.12's `Path.resolve()` reports a symlink loop as `RuntimeError`; 3.13+ resolves it without
   raising and the `is_dir()` check refuses it instead, so what reaches this branch there is an
   `OSError` — a working directory that no longer exists, for one"*. Add one version-independent
   test beside the loop test: `gone = tmp_path / "gone"; gone.mkdir(); monkeypatch.chdir(gone);
   gone.rmdir(); assert initialize(["--project", "."]) == 1` with `"refused:"` in stderr — or, if
   deleting the cwd under pytest proves awkward, `monkeypatch.setattr(Path, "resolve", _raising)`
   where `_raising` raises `OSError(errno.ELOOP, ...)`. Give the loop test a docstring that says
   which branch each version takes. Optionally rename
   `test_an_explicit_project_is_made_absolute_and_says_so` (`:87-95`) to say *resolved*, since
   *made absolute* is the defect round 12 removed. **Aside, outside this fence:**
   `hook/spawn_warm.py:57` (*"`Path.resolve()`, which can raise on a symlink loop"*) carries the
   same 3.12-only claim; the `except Exception` around it is unaffected.

2. **[IMPROVEMENT] `README.md:468` still says `init` "costs nothing" — the brief reports this
   edit made and it is not in the tree.** `README.md:466-469`: *"In a project your agent has
   already opened there is a store already, and `init` will say so and exit 0 — so it costs nothing
   to put at the top of a provisioning script."* Since round-12 #2 `init` connects on every run
   (`initialize.py:50-55`), so on a machine with no service listening it starts one — `Store.open`
   in the CLI for the identity read, then a spawn and the model load, and on a cold cache the 64 MB
   fetch that Q17 says can push it past the 10 s deadline into an exit 1. `grep -rn 'costs
   nothing' README.md` shows the line; nothing else in the corpus makes the claim
   (`initialize.py:54` has the corrected form). **Fix:** *"— so putting it at the top of a
   provisioning script costs at most the service start the next command would pay anyway; on a
   cold model cache that start is the one described under `--wait` below, and a second `init`
   succeeds where the first timed out."* — or the shorter *"costs at most a service start"* the
   brief intended.

3. **[IMPROVEMENT] A fifth site of round-12 #4's class: `FINDINGS.md:386-388` says every other
   typed command refuses a storeless project before it connects.** Q17: *"**`init` is the only
   typed command that can reach this**, since every other refuses a storeless project before it
   connects"*. `install` and `doctor` neither connect nor refuse, and the sentence is in the file
   every session loads. The brief says the class was swept *"in all of its phrasings"*; this
   phrasing shares no word with the four that were fixed, which is the case `CLAUDE.md` §"Sweep
   the class" describes. **Fix:** *"since every `knowledge` verb refuses a storeless project
   before it connects, and `install` and `doctor` never connect at all"*.

4. **[IMPROVEMENT] `architecture.md:560-568`'s "every client but one agrees by construction" is
   true only while the harness's own spelling is physical, which nothing has measured.**
   `:563-565`: *"Every client but one avoids this by construction, because `Path.cwd()` is already
   physical and `CLAUDE_PROJECT_DIR` is taken verbatim by all of them; the exception is a path a
   person types, which is why … resolves `--project`"*; `resolve.py:83-84` says the same. Resolving
   `--project` makes a typed path agree with the *fallback* clients by construction. It agrees with
   the *harness* clients only if `CLAUDE_PROJECT_DIR` is itself a physical path — and
   `harness.md:59` records that the variable is present in both clients' processes, not what it
   spells. If a session is launched from `~/work/p` where `~/work` is a symlink and the harness
   exports the logical path, the hook and `zikaron-mcp` key `~/work/p/.zikaron/memory.db` verbatim
   and `zikaron init --project .` typed in that shell keys `/real/work/p/.zikaron/memory.db`: same
   socket, refused — the round-12 hazard with the sides swapped, and one the pre-round-12
   `.absolute()` would have avoided for a typed `--project ~/work/p` while failing for `--project
   .`, so resolving is still the right choice. Prose honesty, not a code change. **Fix:** in both
   places, *"… agree by construction — the harness clients with each other, and the typed path with
   them whenever the harness's value is physical, which is unmeasured; a symlinked
   `CLAUDE_PROJECT_DIR` would reproduce the mismatch in the other direction, and the lasting repair
   is to compare resolved paths on both sides of the identity check rather than spellings"*.
   Re-derive with one hook line in a session launched from a symlinked directory:
   `echo "$CLAUDE_PROJECT_DIR"; pwd -P`. The comparison change is outside M31's fence and not asked
   for here.

5. **[IMPROVEMENT] `init` typed under an existing store creates a nested one and says nothing
   about the store above it, though the ancestor search is already there.** `README.md:458, 466`
   tells the reader to run `init` first; a reader who does so one directory too deep gets
   `initialized <sub>/.zikaron / resolved from the working directory` and a second store — the
   defect this milestone exists to remove, reached through the one command that legitimately
   creates stores. The verbs' refusal names the ancestor (`resolve.py:153-159`); `init` reached
   directly does not, and `_report`'s docstring (`initialize.py:91-93`) gives the reason it should:
   *"the moment to catch it is while the reader is still looking"*. A monorepo makes the nested
   store legitimate, so this is a note and not a refusal, and it binds nothing. **Fix:** in
   `_create`, before the connection and only when `not existed`: `above =
   nearest_store_above(project.directory)`; if not `None`, `stderr(f"note: a store already exists at
   {above}; this creates a second one at {project.store_dir}")`. One test in
   `TestTheCommandsThemselves` — `initialized / "src"` as `--project`, `connected` patched with the
   recording stub that touches the database — asserting the note names `initialized / ".zikaron"`
   and the exit is still 0; and one asserting no note when nothing is above.

6. **[NITPICK]** `research/claude-project-dir-reaches-hooks-not-shells.md:23`: *"The marker
   `CLAUDECODE` and the session id **are** exported to the shell"* — the transcript at `:12-21`
   shows `CLAUDECODE` and nothing about a session id. Either add the
   `echo "${CLAUDE_CODE_SESSION_ID:-<unset>}"` line that was presumably run, or drop *"and the
   session id"*.

7. **[NITPICK]** `resolve.py:9-10` and `FINDINGS.md:240-241`: *"`CLAUDE_PROJECT_DIR` reaches hooks
   rather than the terminal"* — `harness.md:59` measured it in the MCP server's process too, and
   that is the client a typed command has to agree with. *"reaches hooks and the MCP server, not the
   terminal"*. `FINDINGS.md:243-245`'s re-derive line could also name
   `research/claude-project-dir-reaches-hooks-not-shells.md`, which is where the measurement now
   lives.

8. **[NITPICK]** `tests/conftest.py:149-151`: *"would otherwise adopt whichever project launched
   pytest — this repository"* — per the measurement the agent's shell exports no such value, so
   this is true only when the launching process is one that does (a hook, or a future version).
   *"whichever project launched pytest, whenever that process exported one — a hook does, and this
   repository would be the value"*. The guard itself is right to stay.

### Round-12 items, re-verified

1 (`resolve.py:99-112`; `test_project_scope.py:97-129` — with finding 1's qualification on which
versions the fourth test reaches the branch); 2 (`initialize.py:50-55, 58-63, 81-84`;
`test_project_scope.py:322-343`; the 0-byte case traces to `store.py:92-109` returning `{}` and
`meta.py:73-75` raising `bad_config schema_version=<missing>` from the identity read at
`connection.py:139-148`, which runs before any connect or spawn, so the disposition claim holds —
and `README.md:468` is finding 2); 3 (`resolve.py:146-152`; `:279-292`, all three rungs, all three
negative assertions); 4 (`cli/main.py:71`, `README.md:466`, `initialize.py:3`,
`distribution.md:145-147` — finding 3 is the fifth); 5 (`architecture.md:702-703`); 6 (the research
note; `harness.md:141-146`; `test_project_scope.py:74-83` — findings 6, 7 and 8 are the residue);
7 (`:147-160`; with the variable equal to the cwd the old `directory != working` derivation reports
the working directory, so the test discriminates); 8 (`FINDINGS.md:382-393`); 9
(`test_project_scope.py:423-424`); 10 (`initialize.py:82`). The aside is at
`architecture.md:560-568` and is finding 4. Rounds 1–11 unchanged since round 12's re-verification;
done-when 1 through 9 hold as traced there, and 10 is `./check.sh` here with the matrix satisfied by
the PR per `CLAUDE.md`.

VERDICT: NEEDS_CHANGES

---

## Round 14 — 2026-09-24

### Summary judgment

All eight round-13 items are applied as the brief describes, and I re-read each against the tree
rather than the list: the version comment says what each interpreter does and names the `OSError`
that reaches the branch on 3.13+ (`resolve.py:106-112`), the loop test's docstring says the outcome
is one refusal through different branches and the new test reaches the `except` identically
everywhere (`test_project_scope.py:121-149`), README's *costs nothing* is gone, Q17 names `install`
and `doctor`, both identity-check sites say the harness's spelling is unmeasured and name the lasting
repair with a re-derive line, the note fires only under an existing store and only when none existed
here, the research note carries the session-id line, and the hook-and-MCP wording is at both sites.
The code path is unchanged in substance since round 12 apart from the note, which binds nothing and
is pinned both ways. What this round found with fresh eyes is in the one failure `init` owns alone:
its deadline-miss message asserts *the service keeps starting* unconditionally and advises a retry,
while the tree's own list of first-start failures — offline on a cold cache, a bad `config.toml`, an
extension that will not load — are cases where the service is dead and the retry loops with the same
advice; the discriminator, `service.log`, is on disk by the ordering `architecture.md` §"First run"
chose for exactly this diagnosis, and nothing names it. That is a few lines and a test, not a
blocker. The rest is nitpicks, one of them a residual of round 13's own finding 1.

### Findings

1. **[IMPROVEMENT] `init`'s deadline-miss message asserts the service is still starting in every
   case and advises a retry that loops when it is not — and the fact that tells the two apart is on
   disk, unread.** `zikaron/project/initialize.py:88-96` re-wraps every `ConnectionError` from the
   connect as *"the service keeps starting after this command gives up — on a cold model cache it
   is still fetching the embedding artifact — so run `init` again"*. The `ConnectionError` that
   escapes `connect_start_if_absent` is `lifecycle.py:462`'s deadline (the ones raised inside
   `_poll_until_reachable` are retried at `:456-461`), and a deadline miss has two causes the CLI
   cannot separate by type: a service still fetching on a slow network, and a service that died
   inside its first start. The tree itself lists the second kind as real — `resolve.py:61-64`
   (*"every first start that fails or is still running"*), `test_project_scope.py:65-67`
   (*"a cold cache with no network, a bad `.zikaron/config.toml`"*), `store.py:97-98` (a failure
   between creating the file and running its DDL) — and under every one of them the advice is a
   retry that fails identically, in the provisioning script this surface was argued into existence
   for. What separates them is `service.log`: `service/main.py:217` configures it *before*
   `_assemble_or_log_and_raise`, and `architecture.md:713-716` says that ordering exists so that
   *"a first-run `Store.create` failure must be as diagnosable from this process's own log as any
   other startup failure"* — so the one typed command whose failure this is should name the log.
   **Fix (code):** in `_create`'s `except ConnectionError`, branch on
   `paths.service_log_path(project.store_dir).is_file()`. Present → *"…so run `{prog}` again; if it
   fails the same way, {log} says why the service did not come up"*. Absent → *"…the service left
   no {log}, so it never got as far as its own log — check that {project.directory} is writable"*.
   Neither branch claims which cause applies, so the slow-network case stays correctly advised, and
   the already-listening-but-malformed `health` case (`lifecycle.py:225-263`, which the same
   `except` also catches) lands on the log branch, where the answer is. `from zikaron.service import
   paths` is the one import `initialize.py` gains; `resolve.py` already has it. **Fix (tests):**
   `test_a_connect_deadline_miss_says_to_run_it_again` (`test_project_scope.py:474-489`) runs on
   `tmp_path` with no `.zikaron/`, so it asserts the never-started wording; add its twin on
   `half_started` asserting `str(paths.service_log_path(half_started / ".zikaron"))` is in stderr
   and *"run `python -m zikaron.project` again"* still is. **Fix (prose):** `README.md:469-471`
   (*"running it again succeeds"*) → *"running it again succeeds when the service was only slow,
   and `.zikaron/service.log` says why when it was not"*; `design/knowledge-index.md:2446-2447`
   (*"the client gives up while the service keeps starting, which is why the retry works"*) →
   append *"— or has died in its first start, which `service.log` in the store directory records
   and the command names"*. Q17 (`FINDINGS.md:383-394`) is unchanged: it says the reporting half is
   closed and the budget is what is open, and this closes the reporting half for the failed case too.

2. **[NITPICK] The residual of round 13's finding 1 is the function's own `Raises:` line.**
   `resolve.py:95-96`: *"`--project` cannot be resolved — a symlink loop is the reachable case"* is
   the 3.12-only claim the comment ten lines below corrects (*"3.13 and 3.14 resolve it without
   raising"*), so one function now states both. *"`--project` cannot be resolved: a symlink loop on
   3.12, an `OSError` such as a deleted working directory under a relative path on every version."*

3. **[NITPICK] "The only command exempted" is ambiguous in the normative §9, and one reading is the
   class rounds 12–13 swept.** `design/knowledge-index.md:2411-2415`: *"every verb here refuses until
   it has, for the reason below. `zikaron doctor` is the only command exempted, since it reports on
   an installation that may be broken…"*. Following a sentence about the refusal, *exempted* reads as
   exempt from refusing — under which `install` is not, which is round-12 #4's false claim by
   implication. The intended sense is the operator's thin-client rule, which
   `distribution.md:146-147` states unambiguously. *"`zikaron doctor` is the one command exempted
   from the thin-client rule — it may open the store directly — since it reports on…"*.

4. **[NITPICK] Re-wrap artefacts from the last two rounds' edits.** `design/architecture.md:570`
   (~250 characters: the re-derive sentence and the `Path.absolute()` sentence share a line) and
   `:707` (~200, the *"no `memory.db`, since the directory above precedes it"* insertion);
   `FINDINGS.md:390` (~110, inside Q17). Cosmetic; nothing in the gate reads them.

5. **[NITPICK] Aside, outside this fence and M30's rather than M31's:** `zikaron/doctor/main.py:61`
   passes the *scope* directory (`args.project`, or `store_scope_dir(Path.cwd())`) under the name
   `store_dir`, and `checks.py:195` resolves and hashes it as the store directory — so the socket
   path `doctor` prints at `:198` carries a hash no client ever derives, since every client hashes
   `paths.store_dir(scope).resolve()` (`mcp/connection.py:94-99`, `hook/connect.py:375-379`,
   `mcp/server.py:95`). The hash is fixed-width, so the length verdict is right; the printed name
   is not the socket a person will find under `$XDG_RUNTIME_DIR`. One `paths.store_dir(...)` at
   `doctor/main.py:61`. Not lodged against M31; noted so it is not lost.

### Round-13 items, re-verified

1 (`resolve.py:106-112`; `test_project_scope.py:121-133` docstring names both branches; `:135-149`
patches `Path.resolve` to raise `OSError(ELOOP)` and asserts the refusal names the path; `:88`
renamed — finding 2 is the `Raises:` line the same claim survives in); 2 (`README.md:466-471`,
*"costs at most the service start the next command would pay anyway"* plus the cold-cache
sentence; `grep -c 'costs nothing' README.md` is 0); 3 (`FINDINGS.md:387-389`); 4
(`architecture.md:560-572` and `resolve.py:80-89`: fallback clients agree by construction, the
harness's spelling is unmeasured, a symlinked `CLAUDE_PROJECT_DIR` reproduces the mismatch the other
way, the lasting repair is comparing resolved paths, and `echo "$CLAUDE_PROJECT_DIR"; pwd -P` is
the re-derive — no code change, as agreed); 5 (`initialize.py:74-84`, before the connection, only
when `not existed`, both paths named, exit unchanged; `test_project_scope.py:425-461` pins the note
under `initialized / "src"` and its absence with nothing above); 6 (research note `:19-20`);
7 (`resolve.py:9-13`, `FINDINGS.md:240-244`, both citing the note); 8 (`conftest.py:149-153`).
None re-raised except as finding 2 states. Rounds 1–12 unchanged since round 13's re-verification;
done-when 1 through 9 hold as traced there — 9's *"covered by the state a failed first start
leaves"* is what finding 1 extends from the predicate to the message — and 10 is `./check.sh` here
with the matrix satisfied by the PR per `CLAUDE.md`.

VERDICT: NEEDS_CHANGES

---

## Round 15 — 2026-09-24

### Summary judgment

The four round-14 items are in the tree as the brief describes and I re-read each against it rather
than the list: `_create` re-raises through `_after_the_deadline`, which branches on
`paths.service_log_path(project.store_dir).is_file()` and keeps the retry in both wordings
(`initialize.py:86-120`); the `Raises:` line agrees with the version comment (`resolve.py:95-97`);
§9 says *exempted from the thin-client rule* (`knowledge-index.md:2413-2414`); the two
`architecture.md` passages and Q17 are wrapped; the docstring leftover is gone
(`test_project_scope.py:91-93`); README and §9 both name `service.log` for the dead case. What this
round found is inside the branch that round was made for, from two directions. The new test does not
pin it — the log path it asserts appears in *both* wordings, so removing the present-log branch
leaves the suite green — and on the one path a second `init` always takes, an existing store, the
message names the cold-cache fetch as a cause when `architecture.md` §"The model loads behind the
socket" and `context.py`'s open path put that fetch behind readiness, so it cannot be what missed
the deadline there. Both are a few lines; neither blocks. The rest is nitpicks, two of them residues
of round-14 #3 at sites the sweep did not reach.

### Findings

1. **[IMPROVEMENT] `test_a_deadline_miss_with_a_service_log_points_at_it` does not discriminate the
   branch it was written for.** `tests/test_project_scope.py:492-511` asserts
   `str(paths.service_log_path(half_started / _STORE)) in printed` — but the absent-log wording at
   `initialize.py:117-120` is `f"the service left no {log}, …"`, so the same path is in the output
   whichever branch ran. Mutation: change `initialize.py:111` to `if False:` and both deadline tests
   stay green (`tmp_path` gets the absent wording it asserts; `half_started` gets the absent wording,
   which contains the path). Only the opposite mutation (`if True:`) is caught, by the `tmp_path`
   test. So the guard is pinned in one direction, and the direction that is unpinned is the one
   round 14 asked for. `CLAUDE.md` §"Sweep the class": *mutation-verify every guard added since the
   last round* — the brief reports the gate and the assertion, not the mutation. **Fix:** in the
   `half_started` test add `assert "says why the service did not come up" in printed` and
   `assert "never reached its own logging" not in printed`; in
   `test_a_connect_deadline_miss_says_to_run_it_again` (`:475-490`) add
   `assert "says why the service did not come up" not in printed`. Re-run the `if False:` mutation
   and confirm one of the two goes red.

2. **[IMPROVEMENT] On an existing store the message names the cold-cache fetch as a possible cause,
   and on that path the fetch cannot be what missed the deadline.** `initialize.py:112-116` emits
   *"on a cold model cache it is fetching the embedding artifact"* whenever the log is present,
   regardless of `existed`. `context.py:246-253`: the open path returns from `Store.open` with the
   encoder loading on a background thread (`loading.declare_dim`), and `dispatch.py:112-113` answers
   `ready=True` once the context is assembled — `architecture.md:745-748`: *"The store opens, the
   socket binds, `health()` answers, and the model finishes loading behind all of it."* Only the
   create path (`:252-253`) awaits `loading.artifact()` before the store exists. So with
   `existed=True` a deadline miss is a dead service (or a machine so loaded the open itself took
   10 s), never the fetch — and that is the path README `:466-468`'s *"safe in a script that runs
   twice"* takes on every run but the first. In a CI log the clause reads as a network flake and buys
   a re-run that fails the same way, which is the loop round 14 set out to cut. A second consequence
   on the same path: the first start configured the log before it created the store
   (`main.py:217-218`), so `existed=True` implies the log is present in every state the service
   itself produces, and `is_file()` is a constant there; it discriminates only on the first-start
   path, where both causes are live. **Fix:** thread `existed` into `_after_the_deadline`. When
   `existed`, the present-log wording drops the clause: *"the service did not answer before the
   deadline — run `{prog}` again in case it was only slow; if it fails the same way, {log} says why
   it did not come up"*. When `not existed`, keep the current text. The absent-log wording is right
   as it stands for both (a store copied in without its log is the `existed=True`-and-absent case,
   and *never reached its own logging* is still the fact). **Test:** on `initialized` with
   `(initialized / _STORE / "service.log").touch()` and the `_refusing` stub, assert
   `"embedding artifact" not in printed` and the log path is; in the `half_started` test assert
   `"embedding artifact" in printed`, which pins the other direction.

3. **[NITPICK] The rationale for the branch is written three times.** `initialize.py:90-95` (the
   comment inside `_create`'s `except`), `:105-108` (`_after_the_deadline`'s docstring) and
   `test_project_scope.py:498-501` each say that a timeout has two causes, that a retry loops on the
   dead one, and that the log is the discriminator. The first is the class `CLAUDE.md` §"Comments
   explain measured reasons" names — the annotation of a repair just made — and the docstring beside
   the branch is the copy that should survive. Delete `:90-95`; the `raise` line reads on its own.

4. **[NITPICK] Two more sites of round-14 #3's ambiguity, both following a sentence about
   refusing.** `zikaron/knowledge/client.py:7-9`: *"every verb here refuses before it connects until
   one exists … `zikaron doctor` is the one command exempted, because it reports on…"*; and
   `design/overview.md:187` (D31's row): *"Every other typed command refuses until it has … `zikaron
   doctor` is the one command exempted, because…"*. Same reading as §9 had — exempt from *refusing*,
   which `install` also is. Same fix at both: *"exempted from the thin-client rule — it may open the
   store directly — because…"*.

5. **[NITPICK] The absent-log branch names the wrong directory when `.zikaron/` already exists, and
   omits the other pre-log refusal.** `initialize.py:118-119`: *"check that {project.directory} is
   writable"*. The `touch` that would have created the log is inside `.zikaron/` (`log.py:29`), so
   when `project.store_dir_exists` the directory that has to be writable is `project.store_dir`. And
   `_ensure_store_dir_exists` runs `permissions.ensure_store_dir` before the log
   (`main.py:217`, `permissions.py:83`), whose `_reject_symlinked_store_dir` refuses a `.zikaron`
   that is itself a symlink — with the service's stderr at `DEVNULL` (`lifecycle.py:277-279`), a
   refusal nothing else will ever show. `target = project.store_dir if project.store_dir_exists else
   project.directory`; *"check that {target} is writable and not a symlink"*.

6. **[NITPICK] `tests/test_knowledge_cli.py:1475` still carries the pre-round-12 property in its
   name.** `test_a_relative_project_is_made_absolute`, whose docstring (`:1478-1480`) now says
   *"resolved before it is sent"* — the same leftover class the brief fixed in
   `test_project_scope.py`. The assertion `given == project` holds under either, since `tmp_path` is
   physical. Rename to `..._is_resolved_before_it_is_sent`; if the stronger property is meant, pass
   `..` from a `sub` directory as `test_project_scope.py:99-110` does.

7. **[NITPICK] Re-wrap artefact.** `design/knowledge-index.md:2448` is ~150 characters where the
   round-14 insertion joins *"…since a retry alone would loop on that one. A fresh CI container…"*.
   Cosmetic; nothing in the gate reads it.

### On the brief's question about round-14 #5

Agreed that it stays out. `git status` shows `zikaron/doctor/main.py` already in M31's diff, so the
one-argument change would add no file to the PR — but the fence says *"No store checks in
`doctor`"*, the defect is M30's, and the round-14 entry is where it is recorded. A scope call for the
operator, not a finding against this milestone.

### Round-14 items, re-verified

1 (`initialize.py:86-120`; `test_project_scope.py:475-511`, with finding 1's qualification on what
the second test pins and finding 2's on the `existed=True` wording; `README.md:469-472`;
`knowledge-index.md:2446-2448`); 2 (`resolve.py:95-97`); 3 (`knowledge-index.md:2413-2414` — finding
4 is the same phrasing at two sites the sweep did not reach); 4 (`architecture.md:569-573`,
`:705-713`; `FINDINGS.md` Q17); 5 (not applied, by agreement — above). The docstring fix is at
`test_project_scope.py:91-93`. Rounds 1–13 unchanged since round 14's re-verification; this round's
edits touch `init`'s failure message, one `Raises:` line and prose, none of which move done-when 1
through 9 as traced there, and 10 is `./check.sh` here with the matrix satisfied by the PR per
`CLAUDE.md`.

VERDICT: NEEDS_CHANGES

## Round 16 — 2026-09-24

### Summary judgment

The seven round-15 items are in the tree and I checked each against the code rather than against
the brief's list. The two mutation claims hold by inspection in both directions — `if not
log.is_file():` flipped either way, and `if existed:` flipped either way, each turns exactly one of
the three deadline tests red (`tests/test_project_scope.py:475-543`) — and the `existed` split rests
on a premise I re-derived rather than took from round 15: `service/context.py:246-253` awaits
`loading.artifact()` only on the create path, `service/lifecycle.py:462` raises the `ConnectionError`
that `_create` catches, and `service/main.py:217-218` configures the log before `assemble`. What
this round found is one sentence in `README.md` that still states the claim round 15 #2 removed
from the code — in the paragraph a provisioning-script author reads — plus two nitpicks. The
milestone's code is ready; the README sentence is a one-line edit.

### Findings

1. **[IMPROVEMENT] `README.md:466-472` attaches the cold-cache deadline miss to the existing-store
   start, which is the path the code now says cannot miss it that way.** The paragraph runs: *"In a
   project your agent has already opened there is a store already, and `init` will say so and exit
   0 — so putting it at the top of a provisioning script costs at most the service start the next
   command would pay anyway. On a cold model cache **that start** can outlast the deadline and exit
   1 while the service keeps going…"* — *that start* is the one in a project with a store, and on
   that path `zikaron/project/initialize.py:120-128` deliberately omits the fetch, because
   `context.py:246-251` opens the store and defers the load behind the socket. A reader who gets the
   `existed` wording (*"did not answer before the deadline — run `…` again in case it was only
   slow"*) and then reads this paragraph is told the cache is the cause right after the command
   declined to say so — the misattribution round 15 #2 was fixed for, at the site the sweep did not
   reach, since it shares no word with `existed`. Every other site ties the hazard to the creating
   run: `design/knowledge-index.md:2438-2440` (*"the only one that starts a service against a
   project with no store"*), `zikaron/knowledge/client.py:115-117`, `initialize.py:6-10`. **Fix:**
   replace the sentence at `:469-472` with *"The **first** `init` — the one that creates the store —
   can outlast the deadline on a cold model cache and exit 1 while the service keeps fetching the
   model; running it again succeeds when the service was only slow, and the command points at
   `.zikaron/service.log` for when it was not."*

2. **[NITPICK] A third phrasing of the `doctor` exemption at `zikaron/knowledge/main.py:6-8`.**
   *"`zikaron doctor` is the one surface exempted outright, because…"* — following a sentence about
   what this command opens, it reads as intended, but it is a third wording of the rule the brief
   just unified at `client.py:7-9` and `design/overview.md:187` (*"exempted from the thin-client
   rule — it may open the store directly"*). Use the same phrase, so the next grep for the rule
   finds all three sites.

3. **[NITPICK] Both log-present wordings assert what the log contains, and one reachable case makes
   that false.** `initialize.py:127` and `:131-132`: *"{log} says why … did not come up"*. A service
   that dies before `log.configure_service_log` runs — an import failure in a broken tool
   virtualenv, with the spawn's stderr at `DEVNULL` (`lifecycle.py:277-279`) — writes nothing, and on
   the `existed` path a log from an earlier successful start is present and says nothing about this
   one; the reader opens it and finds yesterday's lines. *"…if it fails the same way, look in
   {log}"* is true in every state and costs nothing. Optional: the case is a corner and `doctor` is
   the channel for it.

### What was re-verified this round

Round-15 items: 1 (`test_project_scope.py:489-490`, `:515-518`, `:541` — the four mutations by
inspection: `is_file()` → `True` reddens `:515`, → `False` reddens `:490`; `existed` → `False`
reddens `:541`, → `True` reddens `:518`); 2 (`initialize.py:91`, `:100`, `:120-128`; premise at
`context.py:246-253`; `existed` is evaluated at `initialize.py:61`, before the connection); 3
(`initialize.py:86-92`, no comment); 4 (`client.py:7-9`, `overview.md:187` — finding 2 is a third
site in a different phrasing); 5 (`initialize.py:112-118`; `core/store/permissions.py:69-90`
refuses a symlinked `.zikaron` *or a symlinked ancestor*, so *"not a symlink"* is right for both
values of `target`); 6 (`tests/test_knowledge_cli.py:1475`); 7 (`knowledge-index.md:2446-2450`,
wrapped). `FINDINGS.md` Q17 (`:384-395`) names `init` and is current. Two spot checks outside the
round-15 delta, both sound: done-when 4's pair writes all four kinds against a created and a
migrated table (`tests/test_store_migration.py:94-116`), and done-when 5's above-range refusal
carries the range rather than a constant (`tests/test_store.py:746`); `core/store/migration.py`'s
re-read inside `BEGIN IMMEDIATE` and single-transaction rollback match the contract build-plan §M31
states. Rounds 1–14 unchanged since round 15's re-verification.

VERDICT: NEEDS_CHANGES

---

## Round 17 — 2026-09-24

### Summary judgment

The three round-16 items are in the tree as the brief says and I read each against the code rather
than the list: `README.md:469-472` ties the cold-cache miss to *the first `init` — the one that
creates the store*; `knowledge/main.py:6-8` carries the same exemption phrase as `client.py:7-9` and
`overview.md:187`; both log-present wordings end *look in {log}* (`initialize.py:133`, `:137`) and
the docstring at `:107-114` records why. The two mutation results are consistent with the code —
`if True:` at `:117` gives every path the absent wording and `:515`'s `"look in" in printed` reds;
`if False:` at `:126` gives the `initialized` test the fetch clause and `:541` reds. The milestone's
code and its documents are otherwise as rounds 1–16 left them. What this round found is a class no
round opened because it sits between two decisions rather than inside either: D37 says what happens
when a *binary* meets a store of the other version, and nothing says what happens when a *client*
meets a service of the other version — and `ClientKind.CLI` makes `zikaron knowledge` the first
client for which that meeting is a hard refusal, reached on the ordinary path of upgrading under an
open agent session, and worded as the caller's mistake. One paragraph and two lines of code. The
rest is nitpicks.

### Findings

1. **[IMPROVEMENT] A `zikaron` upgraded while an agent session is open meets the older service that
   session keeps alive, and the CLI is the one client that meeting refuses — as `bounds` on a field
   the person never typed, with nothing in the corpus saying so.** The mechanism, each step in the
   tree: every verb sends `kind=CLIENT_KIND` (`zikaron/knowledge/client.py:98`); a service built
   before this milestone validates it against its own `_KNOWN_CLIENT_KINDS`
   (`zikaron/service/envelope.py:33, 113-115`), which is `{consolidator, hook, mcp}` there, and
   raises `BOUNDS {field: client.kind, limit: [...], actual: cli}`; `BOUNDS` declares no
   disposition (`zikaron/core/errors.py:225-228`) and so is `REFUSED` (`:187`); `report.py:49-50`
   prints `refused: a field is outside its permitted bounds (field=client.kind,
   limit=['consolidator', 'hook', 'mcp'], actual=cli)`. **`init` passes**, because `health` takes no
   envelope (`zikaron/service/dispatch.py:9`) — so a provisioning script's first line says
   *already initialized* and its second is refused. **The hook and `zikaron-mcp` pass**, since they
   send kinds the old service knows. **The window is the ordinary one**: `idle_timeout` defaults to
   1800 s (`zikaron/core/config/keys.py:363-369`) and is reset by every call
   (`lifecycle.py:100-107`), so an agent session that is in use keeps the pre-upgrade service alive
   for as long as it runs — hours — and `health()` carries no build version (`architecture.md:577`;
   `grep version zikaron/service/lifecycle.py` is empty), so no client can tell an older service
   from its own. Before M31 no client could hit this: every kind on the wire was one every service
   ever shipped knew. D37's rationale (`overview.md:193`) argues both directions for a binary and a
   store and neither for a client and a service; `grep -rn 'older service\|predates this build\|skew'
   design/` finds nothing. Why it is more than a corner: `uv tool upgrade zikaron` with a Claude
   Code session open is how every upgrade will happen on a developer machine, the surface it breaks
   is this milestone's, and the message names a field bound the reader cannot act on — the
   *refused-implies-a-different-call-would-work* reading `ErrorSpec`'s own docstring (`:180-182`)
   warns against. **Fix (prose, the minimum):** one paragraph in `design/distribution.md` §3 —
   where an upgrading reader is — stating that a service started by an earlier build keeps
   answering after an upgrade until it idles out or is sent `SIGTERM` (`architecture.md:499-500`
   already documents that restart for a config change; same remedy), that until then a `knowledge`
   verb from the new build is refused `bounds` on `client.kind` while `init`, the hook and
   `zikaron-mcp` are not, and that `health()` carries no version so nothing detects it; plus one
   sentence in `architecture.md` §"Store identity is verified, not assumed" beside `:577`, that the
   schema range governs a binary meeting a store and nothing governs a client meeting a service.
   **Fix (code, recommended, and inside the fence):** in `ServiceRefusalError.render`
   (`client.py:69-77`), when `self.code == ErrorCode.BOUNDS.value and self.data.get("field") ==
   "client.kind" and self.data.get("actual") == CLIENT_KIND`, append a second line: *"the service
   answering for this project predates this build and does not know this client; it exits after
   `idle_timeout` (default 1800 s) with no calls, or stop it with SIGTERM"*. Test in
   `test_knowledge_cli.py`: an `_InProcessClient` whose `call` raises that `ServiceRefusalError`,
   `list` → exit 1 and the line in stderr; and the negative — `bounds` on any other field prints no
   such line. Not a version handshake: that is a design change (`health()` gaining a field both
   sides compare), and the honest sentence for now is that there is none.

2. **[NITPICK] `client.py:85-88` explains `KnowledgeClient.project` with the behaviour this
   milestone removed.** *"under D17 a command typed one level too deep addresses a project of its
   own, and the service creates its store rather than refusing"* — since `init`, a command typed one
   level too deep is refused before any connection (`main.py:182-186`); the case the field still
   serves is a nested directory that *has* a store (the monorepo shape), which is answered from,
   correctly and about nothing the reader meant. *"…addresses a project of its own — refused before
   the connection when that project has no store, and answered from when it has one, which is why an
   empty listing names the directory it looked in."*

3. **[NITPICK] The refusal's `--project` remedy is not shell-quoted.** `resolve.py:165`
   `f"  a store exists at {found}; reach it with --project {root}"` — a root with a space in it
   pastes as two arguments. Round 3's finding 2 quoted the `refresh <name> --force-unlock` line with
   `shlex.quote` for the same reason; `--project {shlex.quote(str(root))}` here, one import.

4. **[NITPICK] "The only command that creates one" without *typed*, at two sites the harness
   clients falsify.** `README.md:466-467` (*"it is the only command that creates one"*) and
   `design/knowledge-index.md:2418-2419` (*"the one command that creates one"*) — `zikaron-mcp` and
   the hook create a store on their first start, which is why README's next sentence can say *"In
   a project your agent has already opened there is a store already"*. `distribution.md:142` has the
   precise form (*"the only \*typed\* command that creates a store … The harness's own clients still
   cause one on their first start"*), and `initialize.py:1` says *typed*. Add the word at both.

### What was re-verified this round

Round-16 items: 1 (`README.md:469-472`); 2 (`main.py:6-8`, identical phrase at `client.py:7-9` and
`overview.md:187`); 3 (`initialize.py:126-138`; the docstring at `:107-114` names both the
pre-logging death and the earlier start's log). The two mutations by inspection as stated in the
summary. Beyond the delta: `_create`'s post-check reads `has_store` as a property
(`resolve.py:57-69`), so it is re-evaluated after the call rather than frozen at construction;
`health` ignoring the envelope is what lets `init` send one through `KnowledgeClient.call`
(`dispatch.py:9`, and `test_knowledge_cli_integration.py:55-56` sends `pid: 0` to `health` and is
answered); `refusal`'s harness-rung branch (`resolve.py:173-174`) is covered at
`test_project_scope.py:259-263`. Rounds 1–15 unchanged since round 16's re-verification; done-when
1 through 9 hold as traced there, and 10 is `./check.sh` here with the matrix satisfied by the PR
per `CLAUDE.md`.

VERDICT: NEEDS_CHANGES
