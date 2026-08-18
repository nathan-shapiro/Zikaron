# Review — D17 store scoping: one resolver for both clients

Artifact: `zikaron/harness/spec.py` (`project_dir_variable`, `store_scope_dir`), `zikaron/hook/main.py`,
`zikaron/mcp/main.py`, `tests/test_harness_store_scope.py`, `tests/test_harness_table.py`
(`test_project_dir_variable`), `design/harness.md` D34 row, `design/overview.md` D17 amendment,
`research/claude-code-dogfood-checkpoint.md` §11b.

## Round 1 — 2026-08-18

**Summary judgment.** The mechanism is right and small: one resolver in the seam, harness difference as
data, kiro's rung byte-identical to its prior behaviour, and the missing agreement property now has a
non-vacuous test on each arm. The evidence base is stronger than the artifact claims — `CLAUDE_PROJECT_DIR`
was in fact measured inside the MCP server process, and nothing cites it. What blocks shipping is not the
code but the corpus around it: the always-loaded FINDINGS index and two `architecture.md` passages still
assert the pre-amendment D17 (one of them asserts the exact claim the measurement refuted), and the
resolver's own docstring misstates its behaviour in the nesting case, where this change quietly makes the
consequence *worse* than before and neither the docstring nor `design/harness.md` §"The nesting limit"
says so.

### Answers to the brief's five pressure-test requests, in short

1. **The kiro caveat is stated in three of four places and flat in the fourth** — finding 4. One
   *stronger* copy also exists: `mcp/main.py` claims agreement "by construction" for both harnesses,
   which the kiro-arm test's own docstring correctly denies.
2. **The test split is honest and neither test is vacuous.** The agreement test reproduces exactly the
   level that differed (moving hook input vs fixed MCP input) and fails on the reverted resolver per the
   stated mutation check. The identity test is not `x == x`: it asserts a property of the *function* —
   it would fail if the kiro rung consulted the environment, normalized, or returned anything but its
   argument — and its parametrization self-retires correctly if kiro ever gains a variable, at which
   point `test_kiro_has_no_project_variable_and_falls_back_to_the_directory_given`'s `is None` pin fails
   loudly first. The one defect in the file is a stale test name in the module docstring (finding 5).
3. **Fallback-on-unusable is right as a default but is misdescribed and silent** — findings 2 and 7.
   The refusal only covers values that do not name an existing directory; the documented nesting case
   inherits a value that *does* exist, and the resolver adopts it.
4. **Things the change touches that the artifact does not say:** the nesting regression (finding 2), the
   conftest hygiene fixture not stripping the new variable (finding 6), the unmeasured meaning of
   `CLAUDE_PROJECT_DIR` for a session started in a subdirectory (finding 8). Existing stores are safe:
   both clients `resolve()` the store dir before use (`mcp/connection.py:70`, `hook/connect.py:364`), so
   the pre-fix MCP store path (physical `Path.cwd()`) and the post-fix `CLAUDE_PROJECT_DIR` path converge
   on the same store and the same socket; no migration issue found. The installer's `--project` is
   legitimately separate from runtime resolution (artefacts and store coincide at runtime because the
   harness reads artefacts from the same directory it exports), but its help text now overclaims
   (finding 9).
5. **Prose coherence:** one stale test name (finding 5), one internal contradiction between
   `mcp/main.py` and the test file (finding 4), and the stale-copy set in finding 1. No garbled
   sentences found in the edited files themselves.

### Findings

1. **[BLOCKER] Three un-annotated copies of pre-amendment D17 survive, one of them in the always-loaded
   file and one asserting the exact claim the measurement refuted.**
   - `FINDINGS.md:37` — the settled-decisions index still reads `D17 | Scope key = literally the current
     working directory`. This file loads every session; the index now contradicts
     `design/overview.md` §4's amended row. Replace with: `D17 | Scope key = the harness's own project
     directory where it names one, else the current working directory (amended 2026-08-18)`.
   - `design/architecture.md:365` — "D17 scopes to the working directory literally" is the withdrawn
     wording. Reword to the amended rule or annotate with a pointer to `harness.md`'s row.
   - `design/architecture.md:1967–1972` — "The hook is safe by construction — it uses the payload's own
     `cwd`. The MCP client uses `Path.cwd()`, which is only correct if kiro spawns the server in the
     workspace … so it does." This paragraph is now measured-false on its first claim (the payload `cwd`
     was precisely the unsafe input under Claude Code, §11b) and stale on both clients, which no longer
     use the raw values. Annotate in place per the withdraw-in-place practice, pointing at
     `HarnessSpec.store_scope_dir` and §11b; the kiro premise it states flatly should carry the
     shell-restore caveat or defer to the harness.md row.
   - Consequence of annotating: `design/harness.md:5–6`'s preamble counts "Deltas are currently placed in
     `architecture.md` (six) and `schema.md` (one)" — update the count when the annotations land, or the
     preamble becomes the next stale copy.

2. **[BLOCKER] The nesting case is misstated in the resolver's docstring, and the consequence this change
   *adds* to it is recorded nowhere.** `spec.py:154–158` says a nested process tree inheriting an
   enclosing session's variables "would otherwise point a store at another project's root" and that
   "refusing an unusable value simply keeps this function from being the thing that acts on it." That is
   backwards in the common case: the inherited `CLAUDE_PROJECT_DIR` names a directory that *exists* (the
   enclosing project is on the same machine), `is_dir()` passes, and the resolver **adopts it**. Under
   the old code a nested kiro session's MCP client keyed the *correct inner* store via `Path.cwd()`
   (measured: kiro spawns the server in the workspace, 21/21 records); under the new code it detects
   Claude Code by the inherited marker and reads and writes the **enclosing project's** store —
   cross-project pollution of durable memory, in both directions (its `remember` lands in the outer
   store; its `search` answers from the outer project's lore), silently. The hook side is partially
   guarded — the misdetection tripwire suppresses pushes on the session-id mismatch — but nothing guards
   the MCP write path. This scenario is not exotic for this repository: kiro-cli run from inside a
   Claude Code session is exactly the `integration_kiro` situation (the test tier is protected only by
   the conftest fixture, finding 6; a human doing it manually is protected by nothing). Required, and
   deliberately not a mechanism: (a) correct the docstring sentence to state that an inherited *existing*
   directory is adopted and what that costs; (b) add the store-repointing consequence to
   `design/harness.md` §"The nesting limit", which currently enumerates wrong-label/lost-push/instrument
   consequences and calls the channel/budget consequences "harmless today" — this one is not harmless and
   is new with this change. The detect-by-agreement remedy already recorded in `detect.py:57–60` remains
   the right future fix and needs no expansion here.

3. **[IMPROVEMENT] The strongest premise of the fix is measured, and the artifact undersells it — cite
   the MCP-server-side measurement.** `design/harness.md:52` supports `CLAUDE_PROJECT_DIR` with "present
   in hook processes and fixed while the payload `cwd` wanders", and the brief itself claims only hook
   presence. But the agreement property depends on the **MCP server process** seeing the same value, and
   that is measured: `spikes/claude-code-harness/mcp.log` records `CLAUDE_PROJECT_DIR=/tmp/zk-ccprobe` in
   **all six** MCP server starts (three sessions, including nested ones). Add that citation to the D34
   row (and ideally the §11b table), otherwise the MCP arm reads as resting on the documentation claim in
   `research/claude-code-install-artefact-contract.md:222` — and this corpus has twice recorded that
   documentation is not measurement. This also gives `mcp/main.py:47`'s "by construction" comment the
   evidence it currently asserts without citing.

4. **[IMPROVEMENT] One flat copy of the unmeasured kiro premise, and one overclaim, both in shipped
   code.** The brief asked for exactly this check. The caveat *is* carried in
   `tests/test_harness_store_scope.py:134–143`, `design/overview.md` D17, and checkpoint §11b ("That last
   point is observational, not measured"). It is **absent** in `spec.py:149–151`: "kiro … does not need
   one, because its shell restores the working directory rather than persisting it" — stated flatly.
   Add the clause, e.g. "…rather than persisting it (observed over twelve days / ~8,000 events, not
   measured — `tests/test_harness_store_scope.py` pins the dependency)". Separately,
   `zikaron/mcp/main.py:46–48` says "Both now ask the seam the same question, so the two clients agree on
   the store **by construction** rather than by luck" — true under Claude Code, false under kiro, where
   the kiro-arm test's own docstring says agreement holds "because their inputs agree, not because
   anything here reconciles them". Scope the comment to match.

5. **[IMPROVEMENT] The test module's docstring names a test that does not exist.**
   `tests/test_harness_store_scope.py:12` cites `test_the_two_clients_resolve_the_same_store_when_the_cwd_moves`
   as "the test this module exists for"; the split renamed it to
   `test_a_project_variable_keeps_both_clients_on_one_store_when_the_cwd_moves` (line 100). A reader
   grepping for the named test finds nothing. Update the name — this is precisely the garbled-edit class
   the brief's item 5 asked to be checked.

6. **[IMPROVEMENT] Extend `conftest._no_inherited_harness_environment` to the new variable.**
   `tests/conftest.py:49–64` deletes every spec's marker and session variable, on the stated rationale
   that tests *and the subprocesses they spawn* inherit whatever harness launched pytest. The seam now
   reads a third environment variable that repoints the store, and the fixture does not strip it — the
   store-scope test file had to grow its own private `_no_inherited_project_dir` autouse fixture to
   compensate (`test_harness_store_scope.py:23–30`), which protects one file out of the whole suite. Any
   other test that sets `CLAUDECODE` and then reaches resolution would silently adopt *this repository*
   as its store scope. Add `if spec.project_dir_variable is not None: monkeypatch.delenv(...)` to the
   conftest fixture; the file-local fixture can then stay as documentation or go.

7. **[IMPROVEMENT] State — or log — what happens when a *set but unusable* value is refused, because the
   failure it produces is the defect this change exists to end.** On refusal, the two clients fall back
   to **different inputs** (hook: the wandering payload `cwd`; MCP: its fixed spawn cwd), so in exactly
   the case where the harness misbehaves, push and pull can again silently answer from different stores.
   `spec.py:153–158` frames the refusal purely as safe ("costs nothing when the harness is behaving and
   matters when it is not") and never says the two fallbacks diverge. Minimum: one docstring sentence
   naming the divergence. Better: one `hook.log` line (a new closed-vocabulary kind, e.g.
   `project_dir_unusable`) when a non-empty value is refused, mirroring the misdetection tripwire — the
   scenario is pathological (deleted project dir, container boundary), which is exactly why it will
   otherwise never be noticed.

8. **[IMPROVEMENT] Name the unmeasured semantics of `CLAUDE_PROJECT_DIR` itself.** Every measurement in
   §11b and the spike logs comes from sessions launched at the project root, where launch directory and
   project directory coincide. Whether the variable names the *launch directory* or a *discovered root*
   when a session starts in a subdirectory (or under `--add-dir`) is unmeasured and stated nowhere, and
   it decides whether a `claude` launched in `proj/src` keys a second store beside the installed one —
   the monorepo/subdirectory pain D17's revisit condition was originally written for. One sentence in
   §11b's "Not measured here" list (or the D34 row) keeps the amended rule from being read as stronger
   than its evidence.

9. **[NITPICK] Two more code-side copies of the old wording.** `zikaron/install/main.py:64–65` help text:
   "the current directory, which is also the directory Zikaron scopes its store to" — no longer generally
   true under Claude Code; suggest "…(default: the current directory). At runtime the store is keyed by
   the harness's own project directory where it names one (D17)." And `zikaron/service/paths.py:31–32`:
   "D17, literally the working directory" — the withdrawn word; the parameter is now the resolved scope
   directory, so e.g. "the `.zikaron` directory for the store scoped to this directory (D17; callers
   resolve it through `HarnessSpec.store_scope_dir`)".

10. **[NITPICK] Harden against a relative variable value.** `store_scope_dir` passes any string to
    `Path(...).is_dir()`, which for a relative value is evaluated against each client's *own* process
    cwd — a relative `CLAUDE_PROJECT_DIR` that happens to exist relative to both would re-split the two
    clients. The harness sets an absolute path, so this is one cheap guard:
    `return candidate if candidate.is_absolute() and candidate.is_dir() else fallback`.

11. **[IMPROVEMENT] Reconcile the gate story and record the green run.** The brief states `./check.sh`
    exits 1 on two pre-existing environmental failures; `FINDINGS.md` priority item 6 (2026-08-18) now
    records those two tests **fixed** — a 30 s mechanism-deadline autouse fixture, present in the tree
    (`tests/test_hook_connect_real_service_integration.py:36–62`) and mutation-verified per the entry.
    The two accounts describe different moments; before shipping, run `./check.sh` once and record the
    exit-0 result wherever this change is written up, since the definition of done is the gate and the
    brief's own snapshot of it is red.

**Verdict rationale.** The resolver, the seam row, and the tests are ready. Findings 1 and 2 are
documentation, but of the class this project treats as load-bearing: an always-loaded index asserting the
withdrawn decision, a normative document asserting the refuted claim, and the artifact's own docstring
promising a safety property it does not deliver in the one scenario the design already documents.

VERDICT: NEEDS_CHANGES

## Round 2 — 2026-08-18

**Summary judgment.** All eleven round-1 findings were addressed, and the two blockers were fixed
properly: the always-loaded index, `overview.md` D17, `architecture.md` §Paths and the annotated premise
paragraph are now correct and mutually consistent, and the nesting regression is stated with the right
mechanism, the right cost, and the right guard asymmetry in both `spec.py` and `harness.md`. The
mechanism and tests are ready to ship. What remains is one accuracy defect the round-1 fix introduced
(the *remedy* sentence attached to the nesting regression describes a check that would not discriminate
in that very scenario, and presents a hook-only remedy as covering the MCP half both passages name as
the unguarded one) plus a sweep residue of pre-amendment D17 copies in `zikaron/mcp/` that the brief
itself asked to be hunted. Each is a sentence-to-paragraph fix; one more pass closes this.

### Answers to the brief's four hardest-check requests

1. **Did the round-1 fixes introduce new errors?** One, and it is finding 2 below: the remedy sentence
   in the new `harness.md` paragraph mischaracterizes what `detect.py` records. No stranded words,
   split sentences, or garbled paragraphs found in any edited passage — FINDINGS.md:37,
   `architecture.md:363–368` and `1969–1984`, `harness.md:6` and `114–127`, `spec.py:133–189`,
   `mcp/main.py:45–51`, `conftest.py:61–69`, `install/main.py:64–66`, `service/paths.py:30–36`,
   checkpoint §11b's two new paragraphs, and the integration-test fixture all read coherently and say
   true things. The `harness.md` delta count (six → eight) is arithmetically consistent with the two
   annotations added.
2. **Finding 7's judgement — documenting the divergence is enough; the log line is not warranted in
   this change, and I withdraw it as the "better" option.** Two reasons the deferral is right rather
   than merely acceptable: the resolver lives in the stdlib-only seam, which must not log, so the line
   would have to be emitted by the hook — which cannot currently distinguish *refused* from *absent*
   without duplicating the seam's own predicate or widening `store_scope_dir`'s return type; and a new
   closed-vocabulary `hook.log` kind is a contract change with its own test surface, out of proportion
   to a pathological case. If refusal observability is ever wanted, the right shape is the seam
   returning a reason alongside the path, not a log call inside it. The docstring paragraph
   (`spec.py:174–178`) states the divergence precisely. Resolved.
3. **The nesting regression: accurately stated, and recordable-not-blocking — I agree with both,
   conditional on finding 2.** The mechanism, the cost (durable memory, both directions), the
   before/after comparison, and the tripwire/MCP guard asymmetry are accurate in both `spec.py` and
   `harness.md` §"The nesting limit", and the `integration_kiro` scenario is named. Shipping is right:
   the defect this change fixes is live and measured in the primary harness, while the regression needs
   cross-harness nesting, has its push half tripwire-guarded and its test-tier instance
   conftest-guarded. But the *remedy* claim attached to it is inaccurate in a way that matters for
   exactly the future session that hits it — see finding 2.
4. **Remaining pre-amendment copies: four in code/tests, two in prose.** Findings 1, 3, 5, 6, 7. The
   sweep is otherwise clean — `schema.md:788` ("per-directory") and `FINDINGS-archive.md:1150` are
   correct as written.

### Findings

1. **[IMPROVEMENT] The round-1 blocker-2 claim survives verbatim in a fourth place — the refusal
   test's own docstring — and now contradicts the corrected resolver.**
   `tests/test_harness_store_scope.py:67–69` still says the nesting case "would otherwise point this
   store at another project's root", i.e. that refusal guards against it — while `spec.py:161–172`,
   corrected this round, says the opposite in bold: "the nesting case is not covered by it", because
   the inherited directory *exists* and is adopted. A reader investigating the nesting case will find
   the test first (it names §"The nesting limit") and be told the refuted thing. Reword the docstring
   to name what refusal actually covers (deleted or never-created directory, empty value, file
   impostor, relative value) and state that the inherited-existing-directory case is deliberately
   *not* caught here — pointing at the resolver's own regression paragraph.

2. **[IMPROVEMENT] The remedy sentence added to `harness.md` misstates the recorded remedy, and both
   new passages present a hook-only remedy as covering the half they call unguarded.**
   `design/harness.md:125–127` says the remedy is "detection by *agreement* between the marker and the
   session variable rather than by the marker alone." That is not what `detect.py:56–60` records, and
   it would not work: under kiro-inside-Claude-Code the inherited marker (`CLAUDECODE`) and the
   inherited session variable (`CLAUDE_CODE_SESSION_ID`) are both present and *agree* — both stale —
   so that check still misdetects. What `detect.py` actually records is agreement between **the hook
   payload's own `session_id`** and whichever harness's variable equals it (`KIRO_SESSION_ID` wins in
   this scenario). And that mechanism is **hook-only by construction**: the MCP client holds no
   payload, so the recorded remedy cannot repair the MCP write path — which is precisely the half both
   `spec.py:170–171` and `harness.md:121–122` identify as the unguarded one. As written, a future
   session hitting this will "apply the remedy" and fix only the half that was already
   tripwire-guarded. Fix in both places, one to two sentences: state the remedy as
   payload-versus-variable agreement, and state plainly that it covers the hook only — no
   discriminator is currently recorded for a nested MCP client, and that half of the regression has a
   named cost and no named repair. (`spec.py:171` — "whose remedy is recorded in `detect.py`" — needs
   only the hook-only qualifier; the `harness.md` sentence needs the paraphrase corrected too.)

3. **[IMPROVEMENT] Two pre-amendment copies in `zikaron/mcp/` misdescribe the mechanism this change
   built — in the component the artifact list names.**
   - `zikaron/mcp/connection.py:57–62` — `StoreLocation`'s docstring: "resolved once from the
     process's own working directory — D17's 'literally the current working directory,' computed here
     rather than trusted from an argument, since an MCP server process has no caller supplying it
     one." Three claims, all now false: the value may be `CLAUDE_PROJECT_DIR` rather than the process
     cwd; the quoted wording is the withdrawn D17; and it *is* now trusted from an argument —
     `main.py:51` resolves `store_scope_dir(Path.cwd())` and hands it down through
     `build_server` → `ServiceConnection` → `StoreLocation.resolve`. Suggested: "Where this process's
     store lives, resolved once from the scope directory the entry point supplies —
     `HarnessSpec.store_scope_dir` over this process's own cwd (D17, amended 2026-08-18)."
   - `zikaron/mcp/server.py:40–41` — `build_server`'s parameter doc: "cwd: this process's own working
     directory, D17's scope key — resolved once here". Neither half holds: the caller passes the
     already-resolved scope directory, and the resolution happens in `main.py`, not here. Reword to
     "the resolved store-scope directory (D17, amended; `main.py` resolves it through
     `HarnessSpec.store_scope_dir`)". Optional beyond this change: the parameter *name* `cwd` is now
     the misleading part; renaming it `scope_dir` would be the honest fix but touches call sites.

4. **[IMPROVEMENT] The new `is_absolute()` guard has no test, so the one mutation it exists to refuse
   would pass the suite.** `spec.py:186–189` was added for round-1 finding 10 with a good comment, but
   no case in `tests/test_harness_store_scope.py` exercises a relative value; someone "simplifying"
   the return to `candidate.is_dir()` alone goes green. One parametrize entry closes it, and it is
   non-vacuous per the project's own break-the-code practice: add
   `(".", "a relative value that exists against each client's own cwd is the split this resolver
   exists to remove")` to `test_an_unusable_project_variable_falls_back_rather_than_being_used` —
   `Path(".").is_dir()` is true, so the reverted resolver returns `Path(".")` and the `== tmp_path`
   assertion fails on the mutation.

5. **[NITPICK] `zikaron/core/store/permissions.py:26–29` quotes pre-amendment D17 as D17's text**
   ("Store scoped to the harness's directory... literally the current working directory") and frames
   the service's store path as "*derived* from the process's cwd in the first place", which the
   amendment also dates — clients now derive it through the resolver and pass it on argv. The
   function's actual argument (symlink vetting, no ambient-cwd comparison) survives the amendment
   intact, arguably strengthened. Mark the quote as the original wording or repoint it at the amended
   row.

6. **[NITPICK] `research/claude-code-harness-probe.md:59–61` still concludes "D17's store scoping is
   unaffected" and "`Path.cwd()` in `zikaron-mcp` remains correct here"** — the confident reading §11b
   refuted two days later, in the document `harness.md`'s preamble names as the measured authority for
   Claude Code claims. Research notes are dated records, but this corpus's practice for a refuted
   conclusion is an annotation beside it (as `claude-code-harness-contract.md` received). One line:
   "Refuted 2026-08-18 — the payload `cwd` wanders with the agent's own `cd`;
   `dogfood-checkpoint` §11b."

7. **[NITPICK] `design/architecture.md:562–563`**: "`realpath` the store directory and require the
   resolved parent to be the cwd" — under the amended D17 the resolved parent is the *scope*
   directory, which under Claude Code is deliberately not the service spawner's cwd.
   `permissions.py` already documents that this clause is implemented as ancestor-symlink vetting
   rather than an ambient-cwd comparison, so the fix is to reword the clause to "the store's scope
   directory" or defer to that reinterpretation.

8. **[NITPICK] Record the green gate where the change is written up.** The brief reports
   `./check.sh` exit 0 (1715 passed, coverage 97.63%, load ~6), which answers round-1 finding 11, but
   the number appears nowhere in the tree — FINDINGS item 6 records the fix mechanism without the run.
   The commit message is the natural place; this round's record here also suffices as a fallback.

**Verdict rationale.** The resolver, both clients, the tests, and the two blockers' fixes are sound,
and I would not hold the ship for findings 3–8 alone. Finding 2 is the one that keeps this from
approval: it is a sentence in the *normative* harness document that names a remedy which demonstrably
would not work in the scenario it is prescribed for, and both new passages let a reader believe the
regression's unguarded half has a recorded fix when only the already-guarded half does. Finding 1 is
the same refuted claim the round-1 blocker existed to remove, still standing in the test file for the
very function. Both are minutes to fix; with them and ideally finding 3 done, this is APPROVED without
another full round.

VERDICT: NEEDS_CHANGES

## Round 3 — 2026-08-18

**Summary judgment.** All eight round-2 findings are fixed, correctly and without collateral damage —
I verified each against the current files rather than the brief's description, re-ran the stale-wording
sweep myself, and read every edited passage for coherence as asked. The corrected remedy paragraphs are
now accurate against `detect.py` and leave the reader with exactly the right expectation: hook-only by
construction, MCP half has a named cost and no named repair. Round 2's conditional stands; this ships.

### The three hardest-check requests, answered

1. **Did the round-2 fixes introduce new errors? None found.** Every edited passage reads as prose,
   not as rewrap debris: `tests/test_harness_store_scope.py:57–78` (the refusal docstring and the new
   parametrize entry with its inline comment), `design/harness.md:114–133`, `spec.py:161–180`,
   `mcp/connection.py:57–69`, `mcp/server.py:38–43`, `permissions.py:25–37`,
   `claude-code-harness-probe.md:59–63`, `architecture.md:562–566`. Each states true things in
   complete sentences, and the withdraw-in-place quotes are all framed as originals rather than
   asserted.
2. **The corrected remedy paragraphs are accurate against `detect.py:56–60`, in both places.**
   Checked claim by claim: the recorded mechanism is payload-`session_id`-versus-whichever-variable-
   equals-it (in the nested-kiro scenario `KIRO_SESSION_ID` wins, so detection lands on kiro —
   correct); marker-versus-session-variable agreement genuinely would not discriminate, since both
   are inherited and both are set; and the mechanism is hook-only because the payload is the hook's
   input and an MCP client has none. `harness.md:125–133` now says all three, bolds the punchline
   ("the MCP write path … has a named cost and no named repair"), and `spec.py:171–174` carries the
   same qualifier in fewer words. A future session hitting the regression will now reach for the
   right fix and know what it does not cover. `detect.py`'s own paragraph needs no edit — it
   attributes the payload to the hook and claims nothing about the MCP half — consistent with round
   2's scoping.
3. **Anything still stale: nothing material.** The sweep over `zikaron/`, `tests/`, `design/`,
   `research/`, both FINDINGS files returns pre-amendment wording only inside withdraw-in-place
   annotations (`mcp/connection.py:63`, `overview.md:118`'s D17 row quoting its own original) and in
   this review file, which is the audit trail. A second sweep on different phrasings
   (`Path.cwd()`-as-correct, "payload's own cwd", "spawns the server in the workspace") likewise
   resolves every hit to either corrected text, an annotated original, or a true kiro-scoped claim
   (`architecture.md:1985` — "the kiro half of the paragraph stands: 21/21" — which is accurate).
   `FINDINGS.md:37` carries the amended row; `harness.md:6`'s delta count of eight is consistent
   with the two `architecture.md` annotations.

### Verification notes on the eight, in brief

Finding 1: the refusal-test docstring now enumerates what refusal covers, bolds that the nesting case
is **not** covered, names the earlier version as wrong, and points at both the resolver paragraph and
§"The nesting limit" — exactly the fix asked for. Finding 2: as above. Finding 3: both `mcp/`
docstrings corrected with the original quoted; leaving the `cwd` parameter name is fine — round 2
called the rename optional, and `server.py:42–43` now says outright that the name is historical,
which removes the misleading half without touching call sites. Do not expand scope for it. Finding 4:
the `(".", …)` entry is present with a comment stating the mutation it refuses; independently
confirmed the arithmetic — `Path(".").is_dir()` is true, so an `is_dir()`-only resolver returns
`Path(".")` and the `== tmp_path` assertion fails. The +1 test count (1715 → 1716) corroborates the
brief's mutation claim. Finding 5: `permissions.py` quotes the original as "D17 as originally
written", dates the amendment, and correctly observes the vetting never compared against an ambient
cwd. Finding 6: the `[Refuted 2026-08-18 …]` annotation sits directly above the refuted conclusion,
in place, citing §11b. Finding 7: `architecture.md:562–566` now says "scope directory (D17 as
amended — under Claude Code deliberately not the spawning process's cwd)" and defers to
`permissions.py`'s implementation note. Finding 8: the gate is recorded in the brief and below;
put it in the commit message as planned.

### Findings

1. **[NITPICK] The refusal-test docstring lists one case its own parametrize does not exercise.**
   `tests/test_harness_store_scope.py:70–71` says refusal covers "a file where a directory was
   promised", but that case lives in the adjacent `test_a_file_where_a_directory_was_promised_falls_back`
   rather than in this test's parametrize. The docstring describes the refusal *predicate*, which is
   defensible, and the case is genuinely tested one function down — so this is optional. If touched
   at all, one clause ("the file case has its own test below") settles it. Not a condition of
   approval.

**Gate, recorded per round-2 finding 8:** `./check.sh` exit 0 — 1716 passed, 10 deselected, coverage
97.63%, load ~6, 2026-08-18. The count is one above round 2's 1715, which is exactly the added
relative-value parametrize case.

**Verdict rationale.** Round 2's condition was findings 1, 2 and ideally 3 done; all eight are done,
each verified against the tree, the fixes introduced no new defects I could find, and the one item
above is a trivial nitpick that does not gate anything. The mechanism was ready at round 1; the corpus
around it is now truthful about the amendment, the regression, and the limits of the recorded remedy.

VERDICT: APPROVED

## Round 3 addendum — 2026-08-18

**Summary judgment.** The post-approval rename (`cwd` → `scope_dir` across the MCP package) is
verified correct and complete within its stated scope, the re-touched prose is coherent, and round
3's nitpick 1 is closed properly. The verdict holds. On the question I was asked directly: the
operator's argument is right and my "do not expand scope for it" was the outlier — round 2 had
already called the rename "the honest fix" and demoted it only for touching call sites, so the
operator's instruction agrees with this review's own earlier judgment rather than overriding it.
One consequence of accepting that argument is recorded below as a non-gating follow-up: the
rationale does not stop at the MCP package boundary, and the hook half still carries the old name.

### The four questions, answered

1. **Was the "do not expand scope" advice right? No — and it was a category error worth naming.**
   It was review-hygiene advice (do not churn a change mid-review to look responsive) stated as if
   it were a code judgment. As a code judgment it was wrong by this review's own round-2 text,
   which called the name misleading and the rename honest. The operator's principle — a docstring
   excusing a name decays, the name is read every time — is the stronger position, and it is
   *especially* strong in a change whose entire subject was one name meaning two things in two
   clients. Where my advice retains any force: an under-review edit against reviewer advice should
   come back for verification rather than ship silently — which is exactly what happened, so the
   process worked. No need to put anything to the operator on my account.

2. **The rename verified: complete and correct within the MCP package, no missed site, no
   over-rename.** Checked against the tree, not the description: `build_server(mode, *,
   scope_dir)` (`mcp/server.py:33`, connection built from it at `:45`);
   `ServiceConnection.__init__(scope_dir)` → `StoreLocation.resolve(scope_dir)`
   (`connection.py:172–173`, `:75`); `mcp/main.py:51` passes `scope_dir=`; every test call site
   uses `scope_dir=` (`test_mcp_server.py` ×7, `test_mcp_consolidator_bridge.py` ×2,
   `test_mcp_tool_descriptions.py`, `test_install_assets.py:130`) and the positional
   `ServiceConnection(tmp_path)` sites are unaffected by construction. A keyword-only parameter
   makes any missed `cwd=` caller a hard `TypeError` under the gate, so green corroborates
   completeness. The two remaining `cwd` mentions in `zikaron/mcp/` are both *correct* uses
   naming a genuine process cwd: `main.py:45–50`'s comment, and `connection.py:59`'s "over this
   process's own cwd". And `main.py:51`'s inner `store_scope_dir(Path.cwd())` is right as
   written, exactly as the brief believed — that argument is the fallback, which genuinely is
   this process's working directory; renaming *that* would be the over-rename. No design-doc
   prose describes either signature, so nothing stale was left behind.

3. **Prose coherence of the re-touched passages: clean.** `server.py:40–42`'s `scope_dir:` doc
   reads as one sentence with no residue from the deleted "the parameter name is historical"
   clause — correctly deleted, since a true name needs no excuse. `connection.py:57–68`'s
   `StoreLocation` docstring is untouched in substance and every claim in it is still true
   post-rename; if anything the rename strengthens its "trusted from an argument" correction.

4. **Round 3's nitpick 1: closed as suggested.** `test_harness_store_scope.py:70–72` now says the
   file-impostor case lives in its own test below and why (it needs a file on disk, not a bare
   string). Accurate and coherent.

### Finding

1. **[IMPROVEMENT — non-gating, follow-up eligible] The rename's own rationale reaches the hook
   half and `service/paths.py`, and stops short of them.** The same resolved-scope value is still
   named `cwd` in `hook/main.py:74` (a local sitting directly beside `payload.get("cwd")` — the
   one place in the codebase where the name collides with a *different live value* of the same
   name, which the adjacent comment exists to disambiguate), in the keyword-only `cwd` of
   `push.run` (`push.py:46`), `spawn_warm.run` (`spawn_warm.py:25`) and `subagent_policy.run`
   (`subagent_policy.py:38`), and in `paths.store_dir(cwd)` (`service/paths.py:30`), whose
   docstring now carries precisely the excusing-the-name pattern the operator rejected. This does
   not gate: these sites pre-date the change, were never flagged in rounds 1–3 because every one
   carries an accurate doc, and nothing in them is false. But the codebase now says `scope_dir`
   in one client and `cwd`-with-a-footnote in the other, for one concept, on the exact axis this
   change is about. Decide it deliberately rather than by where the diff happened to stop: either
   finish the pass (`cwd` → `scope_dir` in those four signatures and the `main.py` local —
   mechanical, keyword-only, mypy-covered) in this commit or the next, or record in the commit
   message why the MCP package is the boundary.

**Condition, stated because the gate had not finished at review time:** this approval assumes the
re-run `./check.sh` exits 0. If it does not, the failure is new information and comes back here.

VERDICT: APPROVED

## Round 3 addendum 2 — 2026-08-18

**Summary judgment.** The full rename pass is verified correct: every production site where the
value is a resolved scope directory now says `scope_dir`, every surviving `cwd` I could find names
a genuine working directory or the harness's live payload field, and the boundary between the two
is now drawn where the concept changes rather than where a package ends. The verdict holds. Two
nitpicks below — one true straggler the mechanical half could not catch (a docstring naming the
deleted keyword), one imprecise clause in the fresh `paths.store_dir` prose — neither gating.

### The three named checks, answered

1. **`service/paths.store_dir`'s new docstring: sound, with one imprecise clause.** The historical
   note ("The parameter was called `cwd` until the amendment, which was true only of the second
   case") is *not* the excusing-the-name pattern — the name is now correct, so the sentence is a
   record of a fixed defect rather than an excuse for a live one, which is exactly this project's
   withdraw-in-place shape. The imprecision is nitpick 2: "else that process's working directory"
   flattens the fact that the two clients' fallbacks are *different* inputs, which round 1 finding
   7 established and `spec.py:176–178` records.

2. **`resolved_policy_text` belonged in the pass — including it was right.** The parameter's first
   act is `store_dir(scope_dir)` (`write_policy.py:312`), and both callers
   (`spawn_warm.py:50`, `subagent_policy.py:57`) pass the value `main.py:74` resolved through
   `HarnessSpec.store_scope_dir`. It is the same concept end to end; the old name there was
   inherited, not chosen. No competing concept found.

3. **No stranded words in anything touched twice.** `hook/main.py:70–74` was the passage most at
   risk (comment written in round 1's wake, code renamed now) and it came out *stronger*: the
   contrast the comment draws — the payload's `cwd` versus the resolved value — is now carried by
   two different names on the two sides of the assignment it annotates, so the comment and the
   code finally say the same thing twice. `push.py`, `spawn_warm.py`, `subagent_policy.py`,
   `tripwire.py` docstrings all read cleanly against their new signatures.

### The not-renamed line, checked survivor by survivor

Every remaining `\bcwd\b` in `zikaron/` is a correct use: `paths.py:4` (functions must not read
`Path.cwd()` — about the real thing), `paths.py:35` (the historical note), `mcp/main.py:45–51`
(genuine process cwd as the fallback argument), `connection.py:59` ("over this process's own cwd" —
true), `install/main.py:63` (`--project` default, a real invocation cwd), `permissions.py` (prose
about ambient-cwd comparison, whose whole point is the distinction), `spec.py`'s evidence and
divergence paragraphs (the payload value and the spawn cwd, both genuine), and `hook/main.py`'s
payload references. Test-side, the `cwd=` remnants are `StdioTransport`/subprocess working
directories (`test_install_e2e.py:150,241`, `test_install_targets.py:1012`,
`test_install_claude_live.py:93`) — real cwds, correctly untouched — and payload literals
throughout `test_hook_main.py`, which mirror the wire shape and must keep the harness's own field
name. The line is drawn correctly; I found no under- or over-rename in production code.

### Findings

1. **[NITPICK] One straggler: `tests/test_hook_push.py:102–103` names the deleted keyword.** The
   `fake_service` fixture docstring says the socket path is what "`push.run` will itself resolve
   for `cwd=tmp_path`" — that spelling no longer exists; the calls below it say
   `scope_dir=tmp_path` (e.g. line 130). This is the class the mechanical half cannot catch (prose,
   not a call) and the same class as round 1 finding 5: a reader grepping for the named argument
   finds nothing. One-word fix: `scope_dir=tmp_path`.

2. **[NITPICK] `zikaron/service/paths.py:33–35`: "else that process's working directory" is true
   of one caller and not the other.** The hook's fallback is the harness's live payload `cwd`,
   not the hook process's own working directory — the two fallbacks being *different* inputs is
   the recorded divergence-on-refusal (`spec.py:176–180`), and this fresh summary line flattens
   it. Suggested: "…where it names one, else the fallback the caller passes — `zikaron-mcp`'s own
   process cwd, or the payload's `cwd` for the hook." Genuinely optional in the same edit:
   `tests/test_hook_tripwire.py:18`'s local helper parameter is still `cwd` for a value used as a
   scope, and `tests/test_install_e2e.py:234`'s "the client scopes its store to its own working
   directory" states the fallback as the general rule — accurate in that kiro-labelled helper's
   own environment, so context carries it, but a qualifier ("under kiro, which exports no project
   variable") would end its grep-level ambiguity.

**Verdict rationale.** The pass did what the operator's principle asked, completely and without
collateral damage in production code; the gate is reported green at an unchanged test count and
coverage, which is the signature of a pure rename, and the keyword-only signatures mean mypy has
already proven the call-site half mechanically. Both findings are prose-level, one word to one
sentence each, and neither makes anything false enough to hold a ship for.

VERDICT: APPROVED
