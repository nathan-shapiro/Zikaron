# M36 brief — review

Artifact: `design/build-plan.md` §"M36 — An upgrade the installer refused, a stale install nothing
reported, and the release" (lines 5471–5617 at the time of round 1).

## Round 1 — 2026-09-30

**Summary judgment.** The diagnosis in items 1, 3 and 4 is correct against the code: `writer.py`
compares whole on both halves, the count sites are where the brief says, and the `reaped` fixture's
loop really does run to its deadline because `init` reaches `service.lifecycle._spawn_detached`
(via `knowledge.client.connected` → `mcp.connection.ServiceConnection`) and that spawner reaps on a
daemon thread. Item 2 is where the brief is not yet buildable: its remedy asserts a property that is
false in the interpreter-mismatch case the brief itself names, and its row-presence rule contradicts
its malformed-file rule. Around those, the brief omits the existing tests item 1 inverts, specifies a
count guard that would miss one live site and scan itself, and writes version prose it knows the next
commit falsifies.

### Findings

1. **[BLOCKER] Item 2's remedy is wrong exactly where the brief says ownership is not checked.**
   Location: §2, first bullet (*"The remedy names the re-install command and says it upgrades in
   place without `--force`"*) against the fourth (*"`doctor` runs under whichever interpreter the
   user typed it from, which need not be the one the project was installed from"*). Under host
   Python (a supported acquisition path, D36) a `doctor` run from venv B against a `.mcp.json` whose
   `command` is `/venvA/bin/zikaron-mcp` fails the row, and the remedy sends the user to
   `targets._refuse_conflicting`, which refuses on `MCP_OWNERSHIP_FIELDS` without `--force`; the
   refusal then recommends `--force`, which replaces the entry whole and drops their keys — the
   loss item 1 and `README.md` both exist to warn about. *Fix:* keep ownership out of pass/fail, but
   let it choose the remedy. If `entry["command"] == str(Commands.from_this_interpreter().mcp)`:
   *"re-run `zikaron install --harness claude-code --project <dir>`; it upgrades the entry in place
   and needs no `--force`"*. Otherwise: *"this `doctor` runs from `<sysconfig scripts dir>` and the
   entry was installed from `<command>`; re-run the installer from that interpreter, or from this one
   with `--force`, which replaces the entry whole and names what it dropped"*. *Tests:* a stale entry
   with this interpreter's command gets the first remedy; one with another interpreter's command gets
   the second; neither remedy contains *"without `--force`"* unconditionally.

2. **[BLOCKER] The row-presence rule and the malformed-file rule contradict each other.** Location:
   §2, the bold sentence *"The row is present when that file names a Zikaron server, and absent
   otherwise"* against the third bullet *"A `.mcp.json` that is not a JSON object fails"*. A
   malformed file names nothing, so by the first sentence it produces no row and by the bullet it
   produces a failing one. The Tests paragraph resolves it (malformed fails; no file → no row;
   well-formed naming no Zikaron server → no row), but the rule sentence is what an implementer
   builds from. Also unspecified: `mcpServers` present but not an object; a Zikaron key whose value
   is not an object (`null`, a string). *Fix:* replace the sentence with the ladder — (i) no file →
   no row; (ii) unreadable, not a JSON object, or `mcpServers` not an object → `FAILED`, remedy
   *fix the file*, since Claude Code loads no project server from it; (iii) an object naming neither
   `MCP_SERVER_NAME` nor `CONSOLIDATOR_AGENT_NAME` **by key** (the two names `entries.py` owns —
   say "by key", not "names a server", so nobody matches on the command's file name as the hook
   path does) → no row; (iv) otherwise checked, and a Zikaron key whose value is not an object is
   `FAILED` with the re-install remedy. Add (ii)'s `mcpServers`-not-an-object and (iv)'s non-object
   entry to the tests.

3. **[IMPROVEMENT] "One of the two servers is missing" fails forever over a plausible deliberate
   edit.** Location: §2, first bullet. `design/harness.md` §"MCP tools may arrive deferred" states
   that *the consolidator's share is paid in every primary session*; a user who removes
   `zikaron-consolidator` from `.mcp.json` to stop paying it has made a choice, and this row would
   exit non-zero on it forever — the exact argument the brief uses to make `alwaysLoad: false` pass
   and to keep the subagent row `REPORTED`. *Fix:* decide explicitly and say why. Either a missing
   consolidator entry **passes** with a detail saying consolidation is unavailable until re-install,
   and only a missing `zikaron` entry fails; or state that a removed consolidator server is not a
   choice this check respects because the shipped skill spawns an agent that cannot run without it.
   Test whichever is chosen.

4. **[IMPROVEMENT] Item 1 names the new tests and not the existing ones its rule inverts.** Location:
   §1 "Tests" paragraph. `tests/test_install_writer.py` class
   `TestAnEntryThatDiffersInAnyFieldIsRefused` (lines 1020–1087) is the *old* contract stated as a
   class docstring — *"equality of the command alone is not equality of the entry"* — and
   `test_an_object_entry_with_the_current_command_but_a_changed_timeout` and
   `test_an_array_entry_with_the_reserved_name_but_a_changed_trigger` assert the refusal item 1
   removes. `test_a_null_zikaron_server_entry_is_refused_rather_than_replaced` (line 1007) and
   `tests/test_install_main.py:423` match on *"pointing somewhere else"*, which the "Wording"
   paragraph replaces. *Fix:* add the predicate to the Tests paragraph: *every existing test that
   asserts a refusal on a non-ownership difference inverts into a rewrite-and-report assertion, and
   the class docstring that states the old contract goes with it; a refusal test that matches on the
   old sentence matches on the field-naming one.* Separately, *"each shown red against the tree
   before the fix"* cannot hold for *"a different command still refuses"* — that is green today. Say
   what done-when 1 already says: red against the tree, or for a guard, against the mutation it
   names.

5. **[IMPROVEMENT] A Zikaron hook entry on a trigger this install does not write is unspecified.**
   Location: §1, second bullet. Today `_differing_zikaron_hooks` refuses it — *"not an entry this
   install writes"*, `writer.py:665–666` — while `_merged_hooks_object` never touches that trigger;
   under Claude Code `_refuse_differing_hook_groups` iterates only `ours` and such a group is
   neither compared nor touched. Ownership by command says "rewrite", but there is nothing to
   rewrite it with. *Fix:* state it — *entries on triggers this install does not write are neither
   compared nor touched, as the Claude Code target already does* — and either keep the current
   refusal deliberately (say why it differs from Claude Code) or drop it. One test either way: our
   command under `stop` in both formats.

6. **[IMPROVEMENT] The count guard as specified misses a live site and would scan itself.**
   Location: §3 "Test" paragraph. (a) `design/knowledge-index.md:2256–2257` reads *"…files it
   refused for one of the eight"* / newline / *"reasons."* — number and noun on different lines, so
   a line-oriented *"number word immediately qualifying reasons"* never sees it; the brief's own
   verified site list omits it. Specify that the guard collapses whitespace, newlines included,
   before matching, and mutation-verify against that site. (b) The guard reads `tests/`, so its own
   docstring and pattern are in scope: assemble the pattern from fragments, as
   `tests/test_publication_hygiene.py:16` already does citing `test_version_seam.py`, or the guard
   either matches itself or cannot describe what it hunts. (c) The bare *"-way compound"* clause
   reddens on `tests/test_indexing_chunking.py:102` (*"A two-way guard"*) and
   `zikaron/core/store/permissions.py:32` (*"one side of a two-way"*): anchor it to `skipped` or
   `breakdown` within a few words, not to any number-word-`way`.

7. **[IMPROVEMENT] Item 5 writes version prose the next commit is known to falsify.** Location: §5,
   second bullet (*"Every document that states the tree's version says `0.3.0` … and says what the
   next commit sets it to"*) against *"The first commit after the tag … is not this milestone's
   commit and not its reviewer's to check."* `design/distribution.md:365` (*"The tree says
   `0.3.0.dev0`, and that is arithmetic"*) and `README.md:454` become sentences that are true for
   exactly one commit — the shape coding-standards §5 and this brief's own item 3 argue against — and
   the brief declines responsibility for the commit that makes them false, so the corpus is
   guaranteed one stale paragraph per release. *Fix:* phrase both so only `pyproject.toml` moves
   after a tag — *"the latest release is `0.3.0`; between releases the tree carries the next patch
   number with `.dev0`"* — and let the `--version` example say *"a `.dev0` suffix means working
   toward the next number"* without naming one. `FINDINGS.md:130` (*"The number is `0.3.0.dev0`"*)
   is a third site the predicate catches; the dash-list of two does not name it.

8. **[IMPROVEMENT] Done-when 2 excludes `README.md`, which is where the user reads the rule it
   withdraws.** Location: "Done when" item 2 (*"nothing in `zikaron/` or `design/` still says kiro
   compares whole"*). `README.md:248–249` (*"Under kiro any changed Zikaron entry is refused
   instead, so a release that moves one needs `--force`"*) and `README.md:321–323` (*"Under kiro any
   difference in a Zikaron entry still refuses, for hooks as well as servers"*) both state it; item 5
   names only the first, and the `--force` row of the flags table (`README.md:422`) describes
   whole-replacement for `.mcp.json` only. *Fix:* *"nothing in `zikaron/`, `design/` or `README.md`
   still says kiro compares whole, and `README.md`'s `--force` row covers kiro's server entry."*
   (`design/harness.md:446–447`, `targets.py:1000–1001`, `writer.py:15` and `plan_kiro_merge`'s
   `Raises:` are already inside the predicate; no list needed.)

9. **[NITPICK] The order test does not see a row inserted where item 2 puts it.**
   `tests/test_doctor.py:390–407` asserts only `names[-2:]`, so a row placed after `check_socket_path`
   is invisible to it whether it lands before the socket row or after. Since the brief makes
   distribution.md's order normative for the new row, extend that test with a `.mcp.json` fixture and
   assert the row's position.

10. **[NITPICK] "A current install passes" should be a generated fixture.** Produce it through
    `ClaudeCodeTarget` or `claude_mcp_servers_value`, not by hand, so the next key added moves the
    fixture with the check instead of reddening it for the wrong reason.

11. **[NITPICK] Item 4's "while still reaping it where it is this process's own zombie" invites a
    race for no benefit.** Every service in that file is spawned in-process, so the daemon thread is
    always the reaper; a zombie still answers `os.kill(pid, 0)` until it is reaped, so the liveness
    poll exits exactly when the process-table entry is gone. Drop the clause, or make it one
    `WNOHANG` `waitpid` under `suppress(ChildProcessError)` before the poll. And the audit will find
    nothing of the named shape: the five sibling loops (`conftest.py:354`,
    `test_service_lifecycle_integration.py:292`, `test_hook_connect_real_service_integration.py:102`,
    `test_hook_warm_helper_integration.py:59`, `test_hook_connect_race.py:150`) *return* on
    `ChildProcessError` rather than continue — say so, so the audit is not widened into that
    different and, for direct children, harmless class.

12. **[NITPICK] The release-notes bullet is a list where the brief's own §"How the next review should
    be briefed" says a list becomes the specification.** State the predicate — *everything M31–M35
    changed that a `0.1.0` user meets, derived from `FINDINGS-archive.md`'s per-milestone blocks,
    with these five as the floor* — and say why `0.2.0` was skipped, since the release page's reader
    will ask.

VERDICT: NEEDS_CHANGES

## Round 2 — 2026-09-30

**Summary judgment.** Every round-1 finding is applied and holds against the tree: item 1 now states
the rule the Claude Code target actually implements (`targets.py:968–1033`, `_is_ours` at 872) and
names the tests it inverts; item 2's ladder resolves the presence/malformed contradiction; item 3's
guard collapses whitespace and self-assembles; item 4 is measured; item 5 no longer writes a number
the next commit falsifies, and no test pins the `.dev` suffix, so the bump cannot redden the gate.
One rule is still not buildable: item 2's remedy is chosen by `command` alone while the brief's own
definition of ownership one item earlier is `command` *and* `args`, and the rule has no answer for
two failing shapes its Tests paragraph enumerates. Around that, item 3's guard pattern misses two
live phrasings the brief's own grep finds, and item 5's predicate stops at the number where the
sentence that follows from it is the one the tag falsifies.

### Findings

1. **[BLOCKER] Item 2's remedy rule tests `command` where ownership is `command` and `args`, and is
   undefined for two shapes the Tests paragraph lists.** Location: §2, *"Ownership does not decide
   pass or fail, but it chooses the remedy"* (lines 5557–5564) against §1's *"owned by
   `entries.MCP_OWNERSHIP_FIELDS` — the interpreter path and the mode"* and against
   `targets._refuse_conflicting` (`targets.py:1006–1012`), which refuses on either field. Three
   cases the rule as written gets wrong or cannot answer: (a) a `zikaron` entry with this
   interpreter's `command` and a differing `args` gets remedy 1 (*"needs no `--force`"*), and the
   installer then refuses naming `args` — the exact loop round 1's blocker 1 was about, one field
   over; (b) a non-object entry (*"when that entry is not an object"*, line 5545) has no `command`
   to read, and the installer's only path through it is `--force` (`_ownership` projects it to `{}`,
   `_merged_server` replaces it only when forced, `targets.py:519–528`); (c) *"when the `zikaron`
   entry is missing"* (line 5545) has no failing entry at all, and what the installer does depends
   on the *consolidator* entry's ownership — `_refuse_conflicting` compares only names present in
   `existing`, so a consolidator owned by this interpreter lets a re-run add `zikaron` without
   `--force`, and one owned by another refuses. *Fix:* derive the remedy from the shared ownership
   predicate item 1 creates, applied to every Zikaron entry present, not from `command` alone:
   *"remedy 1 when each present Zikaron entry's ownership equals this interpreter's for that name;
   otherwise remedy 2, naming the entry's `command` where it is an object carrying one, and saying
   `--force` is what a non-object entry needs."* Since item 1 moves the predicate into one place,
   `doctor` importing it is also what makes *"what `doctor` promises"* and *"what the installer
   does"* provably one predicate. Scope remedy 1's promise to the entry — *"this entry upgrades in
   place"* — rather than to the run, because `_refuse_differing_hook_groups` on
   `settings.local.json` can still refuse the same re-run for a reason this row does not read.
   *Tests to add:* same command with `args: ["--mode", "consolidator"]` → remedy 2 naming the mode;
   `"zikaron": null` → remedy names `--force`; `zikaron` missing with a consolidator owned by this
   interpreter → remedy 1, and by another → remedy 2.

2. **[IMPROVEMENT] Item 3's guard pattern misses two live sites its own grep finds.** Location:
   §3 "Test" paragraph (lines 5589–5597), *"a number word — or a digit — qualifying `reasons` or
   `file reasons`"*. (a) `zikaron/core/knowledge/counters.py:8–9` reads *"the eight skip"* /
   newline / *"reasons count"* — the qualifier is `skip`, not `file`, and it is line-wrapped **in
   code**, so the whitespace collapse the brief attributes to the design (*"because the design
   wraps"*) must apply to `.py` sources too. (b) `design/knowledge-index.md:2185` reads *"the eight
   \*file\* reasons"* — emphasis markers between the number and the noun, which `eight (file )?reasons`
   never sees. *Fix:* state the shape — number word or digit, then optional emphasis, optional
   `file`/`skip`, optional emphasis, then `reasons`, matched after collapsing whitespace in every
   scanned file — and name `counters.py:8–9` beside `knowledge-index.md:2256–2257` as the two
   wrapped mutation sites, one per file kind. The reading pass removes both regardless; this is
   about the guard's stated coverage, which the brief bounds to *"the common form"* and these are
   two of it.

3. **[IMPROVEMENT] Item 5's predicate stops at the number, and the sentence that follows from it is
   the one the tag falsifies.** Location: §5, second bullet (lines 5629–5632), *"Every sentence that
   names the current number"*. `design/distribution.md:365–368` — *"`MIGRATIONS` carries two steps
   that have never been released — `to_version=2` at M31 and `to_version=3` at M33 — so two minors
   have accrued"* — contains no version number and becomes false at the moment `v0.3.0` is tagged,
   as does `FINDINGS.md`'s *"two unreleased `MIGRATIONS` steps since `0.1.0`"* and *"an installed
   `0.1.0` supports schema 1 alone and can no longer open any of them"* (the last stays true, but
   only as history). This is the class `CLAUDE.md` names — the stale sentences are the ones that
   *followed from* the number, sharing none of its words. *Fix:* widen the bullet's predicate to
   *"every sentence that names the current number, or states what is unreleased"*, and phrase the
   arithmetic as a released fact the tag makes true rather than false — *"`0.3.0` ships schema 3;
   `0.1.0` shipped schema 1; the two steps between them are each a minor bump"*.

4. **[IMPROVEMENT] The row passes on a `command` that no longer exists, which is the failure the
   file's own README paragraph names.** Location: §2, step 4 and the remedy paragraph. The check
   reads `command` to choose a remedy and then passes whatever it is; a clone-mate's committed
   `.mcp.json` naming `/home/other/.venv/bin/zikaron-mcp`, or a venv since deleted, is *"a server
   that cannot start"* (`README.md:264–272`, `harness.md` §"`.mcp.json` is committed by design")
   and `doctor` says `ok`. The host-Python argument for keeping ownership out of pass/fail does not
   reach this case: a path that is not an executable file belongs to no interpreter on this machine.
   `Commands.missing()`'s own test (`entries.py:133–137`, `is_file` and `X_OK`) applied to that
   path is free. *Fix:* either add — FAIL when the `zikaron` entry's `command` is not an executable
   file, remedy the `--force` re-install, since ownership then necessarily differs; one test with a
   nonexistent path — or fence it explicitly with the reason. The fence currently excludes hook
   staleness and kiro; it says nothing about this, and a reader of a row that reads `.mcp.json`
   will assume it looked.

5. **[NITPICK] "Beside `check_socket_path`" does not say which side.** Location: §2, line 5534,
   and the Tests paragraph's *"asserts this row's place"*. The two Claude-Code-file rows (this and
   the subagent scan) are both conditional on a project file; putting this one directly after the
   socket row and before the subagent row keeps them adjacent, and the order test then asserts one
   position rather than whichever the implementer chose. Say it once here so `distribution.md`
   states the same one.

6. **[NITPICK] Item 4's sibling claim is true in substance and false to a grep.** Location: §4,
   *"every other `waitpid` polling loop under `tests/` returns on `ChildProcessError` rather than
   continuing"*. `tests/test_hook_connect_race.py:148–155` does `continue` on it — inside a `for`
   over pids with a blocking `waitpid(pid, 0)` per pid, so it advances rather than retries and spends
   nothing. Say *"ends its wait on it"*, or name that one as a `for`, so the next reader who greps
   `continue` does not reopen the audit.

VERDICT: NEEDS_CHANGES

## Round 3 — 2026-09-30

**Summary judgment.** Every round-2 finding is applied and holds against the tree: the remedy is
chosen by the shared predicate over every entry present (§2, lines 5563–5576); the row's position is
fixed and the order test is extended; the guard collapses whitespace in every scanned file and names
both wrapped sites; item 5's predicate reaches the sentences that followed from the number, and no
test pins version prose (`test_distribution.py`, `test_cli_front_door.py` read `pyproject.toml` for
other things); item 4's sibling sentence matches `test_hook_connect_race.py:143–155`; and no
existing test pins the foreign-trigger removal item 1's third bullet narrows, so the inversion
predicate is complete. What remains is three precision defects in rules this round added — a guard
whose number-word set is unbounded and so is red on five ordinary sentences today; an executable
test that fails a working bare-`PATH` command with a remedy that would break it; and a remedy that
names the `command` where the field that differs may be `args`. Each is a sentence or two, but the
first two make the guard or the check wrong on the tree as specified.

### Findings

1. **[IMPROVEMENT] "A number word" is unbounded, so the guard as stated is red on five sentences the
   reading pass must leave alone.** Location: §3 "Test" (lines 5603–5605), *"fails on a number word
   or a digit, then optional emphasis, an optional file or skip, optional emphasis, and reasons"*.
   Over the three scanned roots that shape matches `zikaron/core/knowledge/text.py:108` (*"which of
   the two reasons it failed on"*), `zikaron/core/indexing/chunking.py:314` (*"for two reasons"*),
   `zikaron/install/writer.py:131` (*"the other two reasons"*), `zikaron/install/main.py:366`
   (*"The three reasons want different advice"*) and `tests/test_install_targets.py:1417` (*"for
   three reasons"*) — ordinary English, none about the enumeration. The brief's own grep is bounded
   to `seven…eleven`; the guard's sentence is not, and an implementer building from the sentence
   rather than the grep ships a guard that cannot be green. *Fix:* state the bound and its reason —
   *"a number word from `six` to `twelve`, or a digit string"* — because the enumeration is eight and
   nine today and the guard must catch the neighbours a reason added or removed produces, while
   *"two reasons"* and *"three reasons"* are English this tree uses five times and must stay green.
   The mutation clause is unaffected: every re-inserted site says `eight`.

2. **[IMPROVEMENT] The executable test fails a working config with a remedy that would break it, and
   is undefined when `command` is absent.** Location: §2 step 4, second sub-bullet (lines
   5550–5553), *"fails when a present entry's `command` is not an executable file —
   `Commands.missing()`'s own test, `is_file` and `X_OK`"*. (a) Claude Code resolves a bare
   `command` on `PATH` — every `npx`-style entry in its own documentation relies on it — so
   `"command": "zikaron-mcp"` is a server that starts, and it is the obvious hand-edit for the
   residual `harness.md` §"`.mcp.json` is committed by design" names, being the one form every
   clone-mate can share. `Path("zikaron-mcp").is_file()` is false from any directory, so the row
   fails, and the remedy is `--force`, which writes an absolute path back into the committed file.
   A relative path with a separator has the same problem one step over: `is_file` resolves it
   against `doctor`'s cwd, which is not the project when `--project` is passed. (b) A `command`
   that is absent or not a string is covered by neither bullet — ownership is excluded from the
   missing-keys test, and *"is not an executable file"* then has nothing to test, so an implementer
   reaches `entry["command"]` or `Path(list)`. *Fix:* replace the sentence with — *"fails when a
   present entry's `command` is absent, not a string, or names no executable: a string without a
   separator is looked up as the harness spawns it (`shutil.which`), one with a separator is
   resolved against the project directory, and the result must be `is_file` and `X_OK` —
   `Commands.missing()`'s test, after that resolution"*. Ownership is untouched: a bare name compares
   unequal to this interpreter's absolute path, so if anything else fails the remedy is still
   remedy 2. *Tests to add:* a bare `zikaron-mcp` with `PATH` pointing at a directory holding an
   executable of that name passes the executable test; a relative path under the project passes
   from another cwd; `{"args": [...], "alwaysLoad": true}` with no `command` fails.

3. **[IMPROVEMENT] Remedy 2 names the `command`, but the field that differs may be `args`, and then
   "re-run from that interpreter" points at this one.** Location: §2 "Otherwise" bullet (lines
   5572–5576), *"names the `command` of each entry that differs … and says to re-run the installer
   from that interpreter, or from this one with `--force`"*, against the Tests paragraph (lines
   5579–5580), *"one with this interpreter's command and the other mode's `args`, naming the
   mode"*. The rule names the command and the test asserts the mode is named. And for that entry —
   same `command`, `args` differing or absent — *"re-run the installer from that interpreter"* is
   this interpreter, whose re-run refuses on `args` (`targets.py:1008–1012`), so the remedy sends
   the user round the loop remedy 1 was scoped to avoid. *Fix:* have remedy 2 name the differing
   ownership field(s), as `_differing_ownership_fields` already does, and branch the advice on
   which: *command* differs → re-run from the interpreter that owns it, or from this one with
   `--force`; only *args* differs or is absent → `--force`, or correct the mode by hand, since a
   re-run from any interpreter refuses it. The rule and the test then agree, and
   `_differing_ownership_fields` is one more thing `doctor` imports rather than restates.

4. **[NITPICK] Step 2 fails `"mcpServers": null`, which the installer treats as absent.** Location:
   §2 step 2 (lines 5539–5541). `targets._refuse_unmergeable_shape` returns on `None` (line 678),
   so a re-run installs over that file without complaint; a `doctor` row telling the user to *fix
   the file* names a repair the installer does not need, against the brief's own standard that the
   two are one rule. *Fix:* *"present, not `null`, and not an object"* — `null` then falls to step 3
   and produces no row, as an absent key does.

5. **[NITPICK] The kiro hook refusal's "or an entry you edited" describes the case that stops
   refusing.** Location: §1 "Wording" (lines 5517–5519), which covers the server refusal only.
   `writer.py:607–611` says *"either a previous install from a different interpreter or an entry
   you edited"*; after item 1 a hook refusal fires only on a different command, so the second clause
   names an edit — a timeout — that is now rewritten and reported. Since the predicate moves to one
   shared place, the cheapest fix is for kiro's two refusals to end in `_ANOTHER_INSTALL`
   (`targets.py:639`) from that place, which already says the right thing; otherwise narrow the
   sentence.

6. **[NITPICK] `README.md:728` promises "needs no `--force`" unconditionally, which the brief's
   remedy rule says is false under host Python.** Location: §2, last sentences (lines 5588–5589),
   *"`README.md`'s troubleshooting row for deferred tools points at this check"*. Say the row
   inherits the scoped promise — *upgrades in place when the entry is this interpreter's; `doctor`
   says which* — or item 5's *"checked against the tree"* pass will read the row as current.

7. **[NITPICK] Item 5 sets a release number in a pull request, which `CLAUDE.md` §"How this project
   works" forbids by name, and the brief does not say who lifted the rule.** Location: §5, first
   sentence (lines 5630–5631). A future session holding both documents reads M36's commit as a
   violation. *Fix:* append *"(operator decision 2026-09-30: this commit is the one that gets
   tagged, which is the case the rule reserves for the operator)"*.

VERDICT: NEEDS_CHANGES

## Round 4 — 2026-09-30

**Summary judgment.** Every round-3 finding is applied and holds against the tree: the guard is
bounded to *six*–*twelve* and no site outside its three roots spells the count (the only hits in
`README.md`, `FINDINGS.md` and the rest of `design/` quote the defect); the executable test is
narrowed to absolute paths, which `Commands.missing()` (`entries.py:133–137`) answers without
resolution; remedy 2 branches on `_differing_ownership_fields` (`targets.py:1022–1033`); step 2's
`null` matches `_refuse_unmergeable_shape` (`targets.py:678`); `doctor` is reachable only through the
console script (no `zikaron/__main__.py`), so the case where this interpreter's own `zikaron-mcp` is
absent cannot arise; and nothing but `pyproject.toml` carries the version — no `uv.lock`, no
`__version__` — so item 5's *one file* is true. What remains is two gaps in item 2's remedy rule,
each a sentence: the `command` branch of remedy 2 points at the install that wrote the stale entry,
which by construction predates the key; and an entry running the other mode passes with no word,
though the row already computes the difference and the case is broken from every interpreter.

### Findings

1. **[IMPROVEMENT] Remedy 2's `command` branch sends the user to the installer that wrote the stale
   entry.** Location: §2 "Otherwise" bullet (lines 5580–5582), *"`command` differs: re-run the
   installer from the interpreter that owns it, or from this one with `--force`"*. The row fails
   because `alwaysLoad` is absent, so whatever wrote the entry predates the key. When its `command`
   is another interpreter's, that interpreter's Zikaron is — in the case that produces remedy 2 at
   all, a user running `doctor` from a newer venv or `uv tool` install while the project was
   installed from an older one — the old one: its installer writes the same entry without the key,
   whether it compares whole or on ownership, reports it current, and `doctor` fails again. The
   `--force` alternative works; the first branch loops in its modal case, the class round 1's
   blocker 1 was about. *Fix:* *"re-run the installer from the interpreter that owns it, **after
   upgrading Zikaron there** — the entry is stale because the install that wrote it predates the
   key — or from this one with `--force`"*. *Test:* the remedy for a stale entry whose `command` is
   another interpreter's names upgrading there.

2. **[IMPROVEMENT] An entry running the other mode passes silently, and the row already knows.**
   Location: §2 step 4 (lines 5548–5568) and *"Ownership does not decide pass or fail"* (lines
   5570–5573). `{"command": <this interpreter's>, "args": ["--mode", "consolidator"], "alwaysLoad":
   true}` under `zikaron` fails nothing in the ladder — every key this version writes is present,
   the command is an executable file — so the row is `ok` while the primary session holds four
   consolidation verbs and no memory or knowledge tool; the mirror under `zikaron-consolidator`
   hands the consolidator twelve primary tools and none of its own. The host-Python argument that
   keeps ownership out of pass/fail is an argument about `command`; the brief itself separates the
   two (*"a differing `args` says a different mode instead"*, line 5519), and a wrong mode under
   that key is wrong from every interpreter, which is the same reason the brief gives for testing an
   absolute path. The remedy rule already computes `_differing_ownership_fields` per entry, so the
   cost is one condition and the remedy is the *"only `args` differs"* branch as written. *Fix:*
   narrow the sentence to *"the `command` does not decide pass or fail"*, and add to step 4: *"It
   fails when a present entry's `args` is not that name's mode"*. Or fence it explicitly with the
   reason, so a reader of a row that reads `args` does not assume it judged them. *Tests:* `zikaron`
   with the consolidator's `args` and every key present fails, naming the mode; the generated
   current-install fixture passes.

3. **[NITPICK] Item 1's test sentence has two answers in the array format.** Location: §1 "Tests"
   (line 5525), *"our command on a trigger this install does not write is left in place, in both
   formats"* against bullet 3's last sentence (lines 5508–5510), where an array entry carrying a
   reserved `name` on a changed trigger is rewritten. Say *"without a reserved `name`"*, so the test
   built from the sentence does not contradict the rule beside it.

4. **[NITPICK] `"mcpServers": null` is in the ladder and not in the tests.** Location: §2 "Tests"
   (lines 5587–5598). Step 3 was changed in round 3 to produce no row for it, on the strength of the
   installer treating it as absent; nothing pins that. Add *"`"mcpServers": null` produces no row"*
   beside *"a file naming neither server"*.

5. **[NITPICK] A deleted `alwaysLoad` is indistinguishable from a stale install, and the detail
   should say what to do instead.** Location: step 4, first sub-bullet against the fourth
   (*"`alwaysLoad: false` is how a user asks for deferral"*). A user who removed the key rather than
   setting it `false` fails forever, and the remedy re-installs, which writes `true` back. One clause
   in the failing detail — *set it to `false` to keep deferral* — gives them the exit the fourth
   bullet designed. *Test:* the failing detail on an absent `alwaysLoad` names `false`.

VERDICT: NEEDS_CHANGES

## Round 5 — 2026-09-30

**Summary judgment.** Every round-4 finding is applied and holds against the tree: remedy 2's
`command` branch names the upgrade (lines 5586–5588); the `args` rule fails a wrong mode from any
interpreter and the heading sentence is narrowed to the `command` (5563–5566, 5576); item 1's test
says "without a reserved `name`" (5525–5526); `"mcpServers": null` is in the tests (5605); the
absent-key detail says a value of the user's own is accepted (5552–5554, 5595). The ladder now
matches the installer's own shape rules (`_refuse_unmergeable_shape` at `targets.py:678`,
`_refuse_conflicting` at 1006–1012), `--mode` is `required=True` (`zikaron/mcp/main.py:24`) so
failing an absent `args` is right, `release.yml:49–55` refuses a disagreeing tag, and
`test_cli_front_door.py:65` pins `--version` to `importlib.metadata`, not to a number. Three
sentence-sized defects remain in item 2, each in a rule this round's predecessors added: remedy 1
does not say *which* installer to run, and under the host-Python case the brief itself invokes the
bare command is the wrong one; remedy 2's `command` branch still loops when both fields differ,
which is a case the Tests paragraph enumerates; and step 2 fails an empty file the installer and the
harness both read as `{}`.

### Findings

1. **[IMPROVEMENT] Remedy 1 says "the re-install command" without binding it to this interpreter,
   and the promise it carries is only true of this interpreter's installer.** Location: §2, lines
   5580–5584, *"the remedy is the re-install command, and says these entries upgrade in place
   without `--force`"*. The condition for remedy 1 is ownership equal to
   `Commands.from_this_interpreter()`; the promise is therefore about *this* interpreter's
   installer. The case that produces two remedies at all — *"host Python with several virtualenvs is
   a supported path"*, line 5579 — is one where `zikaron` on `PATH` may belong to another
   interpreter: a user with a `uv tool` install on `PATH` and a project installed from
   `/venvB` runs `/venvB/bin/zikaron doctor`, gets remedy 1, types the printed `zikaron install
   --harness claude-code --project .`, and the `uv tool` interpreter's installer refuses on
   ownership — the loop remedy 1 was scoped to avoid, one hop over. `distribution.md:172–175` keeps
   `python -m zikaron.install` alive for exactly this reason (*"a host-Python install with several
   virtualenvs needs the form that says which interpreter's Zikaron is acting"*), and
   `zikaron/install/__main__.py` exists. *Fix:* *"the remedy is the re-install command **spelled for
   this interpreter** — `<sys.executable> -m zikaron.install --harness claude-code --project <dir>`,
   the form `distribution.md` §"The front door" keeps for a host-Python install with several
   virtualenvs — and says these entries upgrade in place …"*. *Test:* remedy 1 contains
   `sys.executable`'s path; no remedy contains a bare `zikaron install`.

2. **[IMPROVEMENT] Remedy 2's `command` branch still loops when `args` differs as well, and the
   Tests paragraph enumerates that case.** Location: §2, lines 5585–5590, *"**`command` differs**:
   re-run the installer from the interpreter that owns it after upgrading Zikaron there … **Only
   `args` differs**: `--force`, or correct the mode by hand, since a re-run from any interpreter
   refuses it"*, against the test at 5596–5597, *"an entry carrying every key but the other mode's
   `args` fails, naming the mode, with this interpreter's command **as with another's**"*. The
   second half of that test has `_differing_ownership_fields` returning `command, args`
   (`targets.py:1033`), which the rule as written routes to the `command` branch; its first option —
   re-run from the owning interpreter — refuses there on `args`, by the brief's own next sentence.
   The branches are ordered by the wrong field. *Fix:* invert the precedence — *"**`args` differs,
   alone or beside `command`**: `--force`, or correct the mode by hand, since a re-run from any
   interpreter refuses it. **Only `command` differs**: re-run the installer from the interpreter
   that owns it after upgrading Zikaron there, or from this one with `--force`."* — and have the
   test's *"as with another's"* half assert the `--force`-or-hand-correct remedy rather than the
   owner re-run.

3. **[IMPROVEMENT] Step 2 fails an empty `.mcp.json`, which the installer and the harness both read
   as `{}`.** Location: §2 step 2, lines 5541–5543, *"A file that cannot be read, is not a JSON
   object … `FAILED`, with a remedy to fix the file — Claude Code loads no project server from it at
   all"*. `json.loads("")` is not a JSON object, so an empty or whitespace-only file — *"how an
   editor leaves a config someone started and abandoned"* — lands in step 2 with a *fix the file*
   remedy, while `_load_json_object_or_empty` (`targets.py:778–781`) returns `{}` for it on the
   stated ground that *"treating it as `{}` is both what the harness does and the only reading that
   lets an install proceed"*. So `doctor` exits non-zero on a file the harness and the installer
   both accept, naming a repair the installer does not need — the brief's own standard at 5577 is
   that the two are one rule. *Fix:* add to step 3's parenthetical — *"including an absent or `null`
   `mcpServers`, **and an empty or whitespace-only file**, which the installer reads as `{}` — no
   row"* — and *"an empty file produces no row"* to the Tests paragraph's no-row list at 5605–5606.

4. **[NITPICK] A second conditional row falsifies a count in `checks.py`.** `run_all`'s docstring
   (`zikaron/doctor/checks.py:249–250`) says the subagent row is *"the one row whose presence is
   conditional"*, and `doctor --project`'s help (`doctor/main.py:37`) lists *"its socket path, and
   its subagents' reach"*. Neither is inside done-when 2's predicate, which is about kiro comparing
   whole. Add the predicate to item 2's last paragraph: *every sentence that counts the conditional
   rows or lists what `--project` reaches*. `distribution.md:194–195` is about the subagent row
   alone and stays true.

5. **[NITPICK] Item 5's "every sentence … that states what is unreleased" reaches the archive, which
   is not re-pointed by rule.** Location: §5, lines 5671–5675. `FINDINGS-archive.md:6534–6536`
   (*"`pyproject.toml` carries `0.1.1.dev0` … an unreleased tree reporting a version"*) matches the
   predicate, and `CLAUDE.md` §"Project memory" says a moved block *"records what was believed and
   when"* and is not re-pointed; `research/` is out of sweep scope by operator decision. The
   dash-list names three live documents, but *"every sentence"* is what an implementer greps for.
   *Fix:* *"in the live documents — `CLAUDE.md`, `README.md`, `design/`, `FINDINGS.md`; the archive
   and `research/` record what was believed"*.

6. **[NITPICK] An absent `args` is a server that cannot start, and neither bullet nor test says
   so.** Location: §2 step 4, lines 5563–5566 (*"a present entry's `args` is not what this version
   writes"*) and the Tests paragraph, which has *"an entry with no `command` fails"* and no `args`
   twin. `--mode` is `required=True` (`zikaron/mcp/main.py:24`), so an entry without `args` fails
   at spawn with nothing on the harness's channel; `_ownership` (`targets.py:976`) omits an absent
   field, so `_differing_ownership_fields` reports `args` and the fixed branch in finding 2 gives
   the right remedy for free. Say *"absent, or not what this version writes"*, and add *"an entry
   with no `args` fails, naming the mode"* beside the no-`command` test.

7. **[NITPICK] Remedy 2's `command` branch names "the interpreter that owns it" for a `command`
   that no interpreter owns.** A bare `zikaron-mcp` — the hand-edit the brief calls plausible at
   5559–5562 and declines to test — fails only when something else is wrong, say `alwaysLoad`
   absent; ownership then differs on `command`, and the branch says *re-run from the interpreter
   that owns it*, which for a bare name is whichever is on `PATH`, while `--force` replaces the
   shareable bare name with an absolute path. One clause: *when the differing `command` is not an
   absolute path, the branch says to set the missing key by hand instead* — the detail at 5553
   already says a hand-set value is accepted.

VERDICT: NEEDS_CHANGES

## Round 6 — 2026-09-30

**Summary judgment.** Item 2 as the operator narrowed it is correct and buildable against the tree:
every name it uses exists (`ALWAYS_LOAD_KEY`, `MCP_SERVER_NAME`, `CONSOLIDATOR_AGENT_NAME`,
`claude_mcp_servers_value` in `entries.py`), the slot it names is real (`run_all` at
`checks.py:254–262`, socket row then the conditional subagent row), `Finding`'s remedy invariant
(`checks.py:64–66`) fits a row that fails with one generic remedy and passes without one, the
`names[-2:]` order test is as described (`test_doctor.py:407`), and the remedy's "upgrades the entry
in place" is true on the path it names — same interpreter means same `command` and `args`, so
`_refuse_conflicting` (`targets.py:1006–1012`) does not fire and `_merged_server` adds the key. The
scope fence matches the operator's direction sentence for sentence. Round 5's findings 4 and 5 are
applied (lines 5560–5562, 5623–5628). Items 1, 3, 4 and 5 hold as earlier rounds verified them, and
I re-checked item 3's guard against the tree: over its three roots the stated pattern reaches
exactly the enumeration sites (`counters.py:8–9` wrapped, `:96`, `:124`, `primary.py:199`,
`test_knowledge_counters.py:45`, `knowledge-index.md:2151`, `2256–2257` wrapped, `2269`, `2311`) and
the `skipped`/`breakdown` anchor keeps `test_indexing_chunking.py:102` and `permissions.py:32` green.
Nothing pins the version or the `.dev` suffix anywhere under `tests/` or `zikaron/`, so the bump
cannot redden the gate. What remains is three clauses.

### Findings

1. **[NITPICK] The rule carves out a non-object Zikaron entry and the tests do not pin it.**
   Location: §2, second bullet (line 5547, *"a Zikaron entry that is an object"*) against the Tests
   paragraph (lines 5556–5559), which has no such shape. `"zikaron": null` is the shape the installer
   projects to `{}` and refuses (`targets.py:971–976`); by this rule it produces a passing row, and an
   implementation that tests `ALWAYS_LOAD_KEY in entry` without the `isinstance` tracebacks on it —
   the outcome `checks.py:125–127` says this command exists to replace. *Fix:* add to the Tests
   paragraph: *"`\"zikaron\": null` produces a passing row"*. One test, seen red against the
   `isinstance` dropped.

2. **[NITPICK] "Does not parse" is one of two ways reading the file can fail.** Location: §2, first
   bullet (lines 5543–5544, *"no file, a file that does not parse, no Zikaron entry — produces no
   row"*). A directory at `.mcp.json`, or a file without read permission, raises `OSError` from
   `read_text`, which `_load_json_object_or_empty` handles as a separate case from
   `JSONDecodeError` (`targets.py:774–785`); an implementer building from the enumerated examples
   catches only the second. The catch-all *"Anything else"* covers it in principle. *Fix:* *"a file
   that cannot be read or does not parse"*, and the same words in the Tests paragraph's no-row list.

3. **[NITPICK] The path the row reads is spelled in a private method.** `<project>/.mcp.json` lives
   in `ClaudeCodeTarget._mcp_config` (`targets.py:382–383`), so the row will spell it a second time;
   the subagent row's precedent is a module-level helper, `agent_scan.agents_directory(project)`
   (`checks.py:230`). Say which — lift the path to a module-level function the target and the row
   both call, or accept the duplicate — so the implementer does not decide it silently. One clause.

VERDICT: APPROVED
