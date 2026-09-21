# M27 — implementation review: the Python range, the seam, and `check-matrix.sh`

Artifact under review: the M27 implementation against `design/build-plan.md` §M27's twelve done-when
items. New: `zikaron/service/asyncio_compat.py`, `check-matrix.sh`, `tests/test_version_seam.py`,
`tests/test_asyncio_compat.py`, `tests/test_service_log.py`. Modified: `server.py`, `main.py`, `log.py`,
`lifecycle.py`, `pyproject.toml`, `check.sh`, `.gitignore`, three test files, `CLAUDE.md`, `README.md`,
`coding-standards.md` §6/§9, `architecture.md`, `schema.md`, `build-plan.md`, `FINDINGS.md`, two agent files.

## Round 1 — 2026-09-21

### Summary judgment

The seam is right and the twelve done-when items are met in substance: the table is data, `row_for`'s
greatest-key-≤ lookup and floor refusal are correct, `unix_server_kwargs()` cannot leak a shared mapping
(frozen row, tuple of pairs, fresh `dict` per call), both `type: ignore[attr-defined]` reads are genuinely
required (the bundled typeshed declares neither `_active_count` nor `_clients` on `asyncio.Server`, and
`--strict`'s `warn_unused_ignores` would redden the gate on all three venvs if either were spurious), and
my own sweeps of `zikaron/` and `tests/` — every version-read spelling, both private names, `3.12.3`,
"pinned", `python3.12`, `get_event_loop_policy` — come back clean. What is not ready is
`check-matrix.sh` **as a gate**: it can print `all of 3.12 3.13 3.14 green` after testing dependencies
the tree no longer declares, and its comment argues the opposite on a reason that does not cover the
case. Beyond that, three pieces of new prose state as universal an ordering the brief itself records as
false on one path. One blocker, a short round.

### Findings

1. **[BLOCKER] `check-matrix.sh` reuses a venv whose dependencies no longer match `pyproject.toml`,
   and reports green.** `check-matrix.sh:61–69` builds `.venv-matrix/<minor>` only when
   `bin/python` is absent. After a pin bump in `pyproject.toml` — the deliberate event §6's own
   "bump deliberately rather than drifting" sentence describes — all three venvs keep the old pins,
   `check.sh` runs the old `ruff`/`mypy`/`pytest` and old runtime deps, and the last line says
   `all of 3.12 3.13 3.14 green`. Nothing announces it; nothing in `CLAUDE.md`, `README.md` or §9
   says to delete `.venv-matrix/` after a bump. The comment at `:63–65` — *"safe because every
   dependency is pinned exactly, and an editable install keeps the package's own code live, so a
   stale venv cannot serve stale source"* — is true of source and false of dependencies (and of
   `[project.scripts]` entry points, which `-e` does not refresh either). Exact pinning rules out an
   *upstream* change reaching the venv; it says nothing about *our* change not reaching it, which is
   the same gap §6 proposition 5 already had to correct in its own reasoning.
   **Fix (stamp, ~6 lines).** Write the stamp only after a successful install, and reinstall on
   mismatch or absence:
   ```bash
   stamp="${venv}/.zikaron-pyproject.sha256"
   wanted="$(sha256sum pyproject.toml | cut -d' ' -f1)"
   if [[ ! -x "${venv}/bin/python" ]]; then
       "$interpreter" -m venv "$venv"
   fi
   if [[ ! -f "$stamp" || "$(cat "$stamp")" != "$wanted" ]]; then
       echo "check-matrix: installing into ${venv} (pyproject.toml changed or never installed)"
       "${venv}/bin/pip" install --quiet -e '.[dev]'
       printf '%s\n' "$wanted" > "$stamp"
   fi
   ```
   Writing the stamp last also repairs a second case the current shape mishandles: an install
   interrupted midway leaves `bin/python` present, so today the next run skips the install and dies
   at `$venv/ruff: No such file` — red for a reason unrelated to the code, which `check.sh`'s own
   header calls the one thing a gate may never do. Rewrite the `:63–65` comment to give the actual
   reason reuse is safe (the stamp), not the pinning argument.

2. **[IMPROVEMENT] The interpreter behind a version label is never verified, so the script can run
   one minor three times and print three greens.** `check-matrix.sh:49–50` resolves
   `${ZIKARON_PYTHON_3_14:-python3.14}` and trusts the name; `:60–61` then trusts a venv by its
   *directory* name for every later run. `ZIKARON_PYTHON_3_14=/usr/bin/python3.12 ./check-matrix.sh`,
   a `python3.14` shim that resolves elsewhere, or a `.venv-matrix/3.14` created under an earlier
   wrong override all run 3.12 under the 3.14 label and finish with `all of 3.12 3.13 3.14 green`.
   That is the failure the absent-interpreter refusal at `:52–58` exists for — success reported for a
   version that never ran — by another door, and §6 proposition 2 ("supported means tested") rests on
   that line being true. **Fix (three lines, after the venv exists, checking the venv's python rather
   than `$interpreter` so a stale venv is caught too):**
   ```bash
   actual="$("${venv}/bin/python" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
   if [[ "$actual" != "$minor" ]]; then
       echo "check-matrix: ${venv}/bin/python is Python ${actual}, not ${minor}" >&2; exit 1
   fi
   ```
   and have `:71` print `$actual` (full `python --version` output) rather than the name it looked
   for, so the log says what ran. (A `.sh` file is outside the scanner's `*.py` scope, so the
   `sys.version_info` in that one-liner trips nothing.)

3. **[IMPROVEMENT] The deprecation filter reaches only the pytest process; the spawned service, hook
   and MCP processes run unfiltered.** `PYTEST_ADDOPTS='-W error::…'` (`check-matrix.sh:72`) is
   applied by pytest *in-process*. The `integration` tier spawns real `zikaron.service.main`,
   `zikaron-hook` and `zikaron-mcp` processes via `sys.executable`; they inherit the environment but
   not pytest's `warnings` filters, so a `DeprecationWarning` raised only inside a spawned service on
   3.14 goes to the child's stderr (or `/dev/null`, per `main.run`'s own docstring) and the matrix
   stays green. The brief's "14 sites … and nothing else" measurement was, by its own description, an
   in-process run and cannot have seen this either. Two honest options: (a) also export
   `PYTHONWARNINGS=error::DeprecationWarning` from `check-matrix.sh` — it propagates to children;
   cost is that `mypy`, itself a Python program, runs under it too, which exact pins make acceptable
   but which should be stated; or (b) keep the script as is and state the gap in its header and in
   §6 proposition 5 (*"in the test process; processes the suite spawns are not covered"*). Either is
   fine. Silence is not, because §6 now reads as a complete claim.

4. **[IMPROVEMENT] Three new sentences assert unlink-before-close as a property of the service; the
   brief's own fence paragraph records the path where it is false.** `server.py:406–408` (*"This
   service unlinks the socket itself, *before* closing the listener"*), `asyncio_compat.py:10–12`
   (same words) and `architecture.md:721–722` (*"That is what keeps the unlink ordered *before* the
   close on every supported version"*). `main.run`'s `except BaseException` path calls
   `shut_down()` at `main.py:348` and unlinks at `:366` — close, *then* unlink — which
   `build-plan.md` §M27 "Fence" and `FINDINGS.md:936–939` both record as the sharpest cell of the
   dropped perturbation walk. So the new prose states as universal what the same milestone records
   as false on one path: the "sentences that followed from the change" class `CLAUDE.md` names. Fix
   in all three: *"on its self-stop and signal paths the service unlinks the socket before closing
   the listener (the error path in `main.run` closes first, and that ordering is a recorded debt);
   a second unlinker would make the ordering meaningless wherever it holds"*. Keep the `serve`
   comment free of document references — name the path, not the section.

5. **[IMPROVEMENT] `asyncio_compat.py:26` names the wrong function.** *"So this module contains no
   version comparisons outside `_running_row`, only rows"* — `_running_row` (`:96–97`) contains no
   comparison; both live in `row_for` (`:88` `version < _FLOOR`, `:93` `key <= version`). A reader
   checking the claim against the code twenty lines down finds it false at once, in the module whose
   whole argument is about where comparisons are allowed. Fix: *"…outside `row_for`, whose two
   comparisons are on its argument rather than on `sys.version_info`, so the type checker cannot
   constant-fold them and both rows stay checked"* — which also says why the floor check does not
   violate done-when 2's "no version branch inside it".

6. **[IMPROVEMENT] The scan can be defeated by an ordinary import style.** The brief's listed
   spellings are all covered, but the rubric asked whether the scan can be beaten, and it can:
   `from platform import python_version` then `python_version()` matches nothing (the pattern at
   `test_version_seam.py:32` requires `platform.`); likewise `from sys import hexversion`,
   `from sys import version`, `sys.implementation.version`, `sysconfig.get_python_version()`, and
   `platform.python_version_tuple()` — the trailing `\b` at `:32` fails because `_` is a word
   character, the very property the scan relies on elsewhere. Fix, keeping the assembled-fragment
   discipline: replace the `sys`/`platform` families with
   `r"\bsys\." + "(version_info|hexversion|version|implementation)" + r"\b"`,
   `r"\bfrom sys import\b.*\b" + "(version_info|hexversion|version)" + r"\b"`,
   `r"\bplatform\." + "python_version"` (no trailing `\b`),
   `r"\bfrom platform import\b.*" + "python_version"`, and
   `r"\bsysconfig\." + "get_python_version" + r"\b"`; add one sample per pattern to
   `test_every_forbidden_pattern_can_actually_match_something`. `zikaron/install/entries.py:17,110`
   legitimately imports `sysconfig` for `get_path("scripts")`, so forbid the function, not the module.

7. **[IMPROVEMENT] The suite collects one more test on 3.13/3.14 than on 3.12, and nothing explains
   it.** The brief reports 2,881 on 3.12 against 2,882 on 3.13 and 3.14. §6 proposition 3 and
   done-when 3 say nothing under `tests/` reads the running version; a collection count that varies
   with the interpreter is a version dependence whether or not it is a *read*. The dynamic
   parametrizations I can find — `test_hook_stdlib_only.py:151` (files on disk),
   `test_knowledge_walk.py:78`, `test_knowledge_state.py:76`, `test_harness_store_scope.py:92`,
   `test_meta.py:46` — are all constant across versions, so it is not obvious what it is. Diff
   `pytest --collect-only -q` between `.venv` and `.venv-matrix/3.13` (two cheap runs), name the
   test in `FINDINGS.md`'s "M27 as built" block, and if it is a version-conditional collection decide
   whether the seam's exemption story has to mention it.

8. **[IMPROVEMENT] The runtime line is missing from exactly the failure it is most useful for.**
   `main.py:93–97` calls `log_runtime_versions()` *after* `resolve(...)`, so a `BAD_CONFIG` startup —
   which the `except` at `:100–101` logs as "failed to start" — carries no Python/SQLite line. The
   line depends on nothing; make it the first statement inside the `try` (or call it in `run()`
   directly after `configure_service_log` at `:213`). "Beside the configuration dump" still holds on
   the success path, and the failure path gains the one fact a bug report needs.

9. **[IMPROVEMENT] The brief's "measured afterwards" citation note is itself incomplete, in two
   files.** `build-plan.md:1941–1945` lists three moved citations. The same docstring edit moved
   every `main.py` reference below `:198` by +6, and the fence paragraph at `:2369–2374` and
   `FINDINGS.md:936–939` still cite `:342`, `:360`, `:261`, `:492` — now `:348`, `:366`, `:267`,
   `:498` (grepped `unlink(missing_ok=True)`; the `lifecycle.py:116`/`:182` citations are still
   right). Either correct the four in both files or extend the header note to *"every `main.py`
   citation below `:198` moved by six lines"*. Two sites, as the note itself warns.

10. **[IMPROVEMENT] Done-when 11 says "verbatim" and no site is.** Every one of the six drops the
    brief's *"remains"*, and four insert a relative clause: `check.sh:2–4` (*"This is the per-edit
    gate…; `./check-matrix.sh`, which runs this whole script once per supported Python version, is
    additionally required…"*), `README.md:459–462`, `coding-standards.md:351–353`,
    `build-plan.md:5–6` (", and" for ";"). All six do share *"additionally required before a
    milestone lands"*, so a sweep by that phrase returns all six plus `check-matrix.sh:4` — which is
    the property "verbatim" was there to buy. Do not rewrite the sites; withdraw the word in place in
    done-when 11: *"carry the sentence's claim with the phrase `additionally required before a
    milestone lands` intact, so one grep returns every site"*. The brief is the contract and should
    say what shipped.

11. **[IMPROVEMENT] The milestone gate, as the crew is told to run it, is three subset runs with
    nothing tying them to one tree.** `.claude/agents/py-runner.md:54–59` and
    `memory-researcher.md:42` instruct one minor per call, so the crew never produces
    `all of … green`; the gate is three `SUBSET RUN` lines assembled by hand, and three green lines
    from three tree states would pass. Cheap fix: print the tree identity on the last line in both
    forms — `git rev-parse --short HEAD` plus a dirty marker from `git status --porcelain` — and say
    in §9 that the milestone gate is *"every minor green on the same tree"*. Otherwise the subset
    label warns about the wrong thing: the risk is not that one run is a subset, it is that three
    subsets are not of one thing.

12. **[NITPICK] Interpreter presence is checked inside the loop.** A machine missing `python3.14`
    learns it after the 3.12 and 3.13 runs (~5 min). Resolve and check all three before running any.

13. **[NITPICK] The floor refusal's stated reason is unreachable.** `asyncio_compat.py:39–40` and
    `test_asyncio_compat.py:46–47` justify it by a bare `max()` failing *"from inside a shutdown
    path"*. A below-floor interpreter cannot import this package (PEP 695 syntax in ten modules) and
    pip refuses it on `requires-python`, so `_running_row` never runs there; the only caller that can
    pass a below-floor tuple is an explicit `row_for(...)`. Say that: the refusal exists so an
    explicit caller gets a message naming the floor rather than `max()`'s.

14. **[NITPICK] `check.sh:58→59`** — the hermeticity-exception paragraph runs straight into
    **"Every package under `zikaron/`…"** with no `#` separator; every other paragraph in that
    header has one.

15. **[NITPICK] `test_version_seam.py:94–96`** says four test names *"end in"* the second private
    name; they contain it (`test_two_clients_racing_…`, `…both_clients_on_one_store_…`,
    `…both_clients_use`). Say "contain".

16. **[NITPICK] `check-matrix.sh:67` `pip install --quiet --upgrade pip`** pulls whatever pip is
    current — the one unpinned install in a script whose reuse argument rests on exact pins, and a
    network round-trip on every venv build. Drop it (the venv's bundled pip installs a pinned
    editable project fine) or pin it.

### Verified and not re-raised

Done-when 1–12 each have a site that satisfies them: `pyproject.toml:14,79,133`; the seam's two keys,
explicit-argument `row_for`, fresh `dict`, `interpreter_version()`; the scanner's two-file allowlist and
its three self-checks; `test_service_server.py:148` polling through the seam and `:188–190` reworded;
`test_asyncio_compat.py:69–100` through `server.serve`; `main.py:198–205` and
`test_service_main.py:559–562`; `lifecycle.py:75`, `server.py:232,272`, `main.py:332` say "measured"
not "pinned"; `server.py:285–292` names no attribute; `architecture.md:718–724`; the 14
`get_event_loop_policy` sites are one helper at `test_service_main.py:38–45`; `.gitignore:27–28`;
`test_check_gate.py:91–104` parses all three statements of the set and `:107–111` ties the floor to
`requires-python`; `log.py:40–58` logs both values on one line beside the dump with a content test;
§6 carries the five propositions in its own voice; both hermeticity paragraphs name the matrix by
reference; §9's command block matches `check.sh`; `README.md:65,84`; `FINDINGS.md:813–983` is off
"briefed". `FINDINGS-archive.md:773` is untouched. The `**unix_server_kwargs()` call needs no ignore
because typeshed's `start_unix_server` takes `**kwds: Any`, which also means the socket test at
`test_asyncio_compat.py:69` is the *only* thing that would catch a misspelled keyword — worth knowing,
not a finding.

VERDICT: NEEDS_CHANGES

## Round 2 — 2026-09-21

### Summary judgment

Fifteen of the sixteen round-1 fixes land as described and I found no cascade in the three unlink
passages, the seam module, or the scan's new patterns — the tree has no false positive under them, and
every hit outside the two exempt files is in `experiments/`, which is out of scope. What is not ready is
the one fix that was *not* the one I asked for: the tree-identity line, whose implementation crashes the
gate after every version has passed whenever a tracked file has been deleted, and prints the same
identity for a tree with and without staged changes — staging being an operation `CLAUDE.md` explicitly
permits. Beyond that, the brief still describes the pre-round-1 script in three places, the rebuilt
`FINDINGS.md` section claims a three-version green it elsewhere says does not count yet, and two sites
of the F4 universal-ordering class sit in the test file the sweep did not reach. One blocker.

### Findings

1. **[BLOCKER] The tree identity crashes the gate on a deleted file, is blind to staged changes, and is
   taken after the run rather than before it.** `check-matrix.sh:129–134`. Three separate defects in
   six lines:
   (a) `git ls-files --modified` lists a tracked file that has been *deleted* from the working tree
   (it differs from the index); `xargs -r sha256sum` then fails on it, `xargs` exits 123, `pipefail`
   makes that the pipeline's status, and the assignment at `:132` trips `set -e`. So a milestone run
   in which a spike or test file was deleted — ordinary — runs all three versions green and then exits
   non-zero **with no last line**, which is the "red for a reason unrelated to the code" that
   `check.sh`'s own header calls the one thing a gate may never do.
   (b) `--modified` compares the working tree to the **index**, and `--others` excludes anything in
   the index, so a staged change is invisible: after `git add -A`, `changed` is empty and the line
   prints the bare `HEAD` hash — byte-identical to a clean checkout. `CLAUDE.md` says staging is fine;
   the fingerprint says a staged tree is the committed one. That is F11's original "three subsets are
   not of one thing" gap reopened for exactly the case the operator's workflow produces.
   (c) The identity is computed at `:129`, after the versions have run, so it names the tree at the
   *end*. An edit landed during the 3.12 run gives the 3.12 line and a later 3.13 line the same
   identity while they tested different trees. Also minor: `printf '%s\n' | xargs` splits a path on
   whitespace, and a mode-only change hashes identically.
   **Fix.** Hash the content of every change relative to `HEAD`, not the index; take it before the
   loop and again after, and refuse if they differ:
   ```bash
   tree_identity() {
       local head fingerprint
       head="$(git rev-parse --short HEAD 2>/dev/null || echo 'no-git')"
       if [[ -z "$(git status --porcelain --untracked-files=all 2>/dev/null)" ]]; then
           printf '%s\n' "$head"; return
       fi
       fingerprint="$(
           {
               git diff --binary HEAD   # every tracked change: staged or not, deletions, mode
               git ls-files -z --others --exclude-standard \
                   | while IFS= read -r -d '' path; do
                         if [[ -f "$path" ]]; then sha256sum -- "$path"; fi
                     done
           } | sha256sum | cut -c1-12
       )"
       printf '%s+%s\n' "$head" "$fingerprint"
   }
   tree_before="$(tree_identity)"
   # … the version loop …
   tree="$(tree_identity)"
   if [[ "$tree" != "$tree_before" ]]; then
       echo "check-matrix: the tree changed during the run (${tree_before} → ${tree}); nothing above is evidence about either" >&2
       exit 1
   fi
   ```
   `git diff HEAD` carries deletions and staged content and cannot fail on a missing path; the
   `-f` guard keeps an untracked dangling symlink from re-creating (a). **Verify by walking the
   cells, not one of them**: the brief says the fingerprint was "verified to change when a file
   changes", and the probe was an unstaged append to `FINDINGS.md` — one cell of four. Delete a
   tracked file (the line must still print); `git add` a change (the identity must differ from the
   bare hash); an untracked file with a space in its name; then `git reset` and confirm the
   identity returns to what it was. Rewrite the `:124–128` comment to say what the identity is a
   hash *of* (every difference from `HEAD`, tracked or not), since "modified or untracked" is the
   description of the bug.

2. **[IMPROVEMENT] The F2 label check runs after the install, so a wrong venv is paid for, stamped,
   and then refused on every later run with no way out named.** `check-matrix.sh:86–102`. With
   `ZIKARON_PYTHON_3_14=/usr/bin/python3.12`, the script creates `.venv-matrix/3.14` from 3.12,
   spends the full `pip install` into it, writes the stamp, and *then* exits at `:100`. Fix the
   override and run again: `bin/python` exists so `:73` does not recreate, the stamp matches so `:86`
   does not reinstall, and `:98` fails identically — forever, until someone guesses to delete the
   directory, which the message does not say. Move the check to directly after the `:73–76` block,
   before the stamp block, and have the message name the remedy: `echo "check-matrix:
   ${venv}/bin/python is Python ${actual}, not ${minor} — remove ${venv}, or fix ${override_var}"`.
   The `:92–97` comment's "read from the venv rather than from `$interpreter` so a stale venv is
   caught too" stays true in the new position.

3. **[IMPROVEMENT] The stamp closes the pin-bump case and the comment now reads as if it closed
   dependencies generally; two residuals are real and one contradicts the script's own sentence.**
   (a) `pip install -e '.[dev]'` into an existing venv never *removes* anything, so a dependency
   deleted from `pyproject.toml` stays importable in all three venvs and a module that still imports
   it passes the matrix while a fresh install fails — the "dependencies the tree no longer declares"
   phrasing in round 1's summary, which the stamp does not reach. (b) `check-matrix.sh:81–82` says
   *"exact pinning rules out an upstream change arriving uninvited"*, and the install is unconstrained:
   `pyproject.toml` pins direct dependencies only, `requirements-lock.txt` exists at the root with
   `numpy==2.5.1`, `onnxruntime==1.28.0`, `tokenizers==0.23.1` and 90-odd others, and **nothing
   installs from it** (README `:84–85` and this script both run bare `pip install -e`; the only
   reference to the file in the corpus is `FINDINGS-archive.md:3177`, "regenerated"). So each
   `.venv-matrix/<minor>` resolves the transitive set on the day it is built, the three venvs can
   differ from one another and from `.venv`, and under `error::DeprecationWarning` a transitive's
   deprecation on 3.14 reddens the matrix with no change of ours — the outcome §6 proposition 5 says
   pinning prevents. **Fix.** On stamp mismatch or absence, `rm -rf "$venv"` before creating it, which
   makes the stamp mean "this venv *is* `pyproject.toml` at hash X" and closes (a) at the cost of a
   rebuild on the rare install-bearing edit. For (b), measure `pip install --constraint
   requirements-lock.txt -e '.[dev]'` on all three minors; if it resolves, use it and hash the lock
   into the stamp beside `pyproject.toml`; if it does not (the file is a 3.12 freeze), say in the
   `:78–85` comment and in §6 proposition 5 that transitives are resolved at venv build time and are
   not what "pinned exactly" covers. Either outcome is fine; the current sentence is not.

4. **[IMPROVEMENT] Two more sites of the F4 universal, in the test that guards the mechanism.**
   `tests/test_asyncio_compat.py:79–80` — *"unlinking it stays this service's own decision and stays
   ordered before the close"* — and the assertion message at `:101–104` — *"must stay ordered before
   the listener closes"*. Both assert as universal what `server.py:409–410`, `asyncio_compat.py:10–13`
   and `architecture.md:722–725` now scope to the self-stop and signal paths; the sweep fixed the three
   sites round 1 quoted and not the file that reads the same sentence back. Docstring: *"closing the
   listener leaves the file, so which process unlinks it, and when, stays this service's own decision
   — before the close on its self-stop and signal paths, after it on `run`'s error path"*. Message:
   *"shut_down() removed the socket file; unlinking it is the service's own step and asyncio must not
   take it"*.

5. **[IMPROVEMENT] `build-plan.md` §M27 still describes the pre-round-1 script in three places and
   contradicts its own done-when in a fourth.** The header note at `:1941–1946` covers *line
   numbers*; these are behavioural claims, and F10's own principle — accepted this round — is that the
   brief is the contract and says what shipped. (a) `:2121–2122`: *"reuses it otherwise — safe because
   every dependency is pinned exactly, and `-e` keeps package code live"* — the exact reasoning round
   1 refuted and the script no longer states; replace with *"reuses it while a stamp of
   `pyproject.toml`'s hash, written only after a successful install, still matches"*. (b) `:2123–2125`
   names `PYTEST_ADDOPTS` alone; add *"plus `PYTHONWARNINGS=error::DeprecationWarning`, because the
   pytest filter does not reach the processes the integration tier spawns"*. (c) `:2131`: *"stated
   once here and quoted verbatim at every site that must say it"* — the same section's done-when 11 at
   `:2339–2343` withdraws "verbatim" in place; change to *"stated once here, and every site that must
   say it carries the phrase `additionally required before a milestone lands`"*. (d) `:2171` and
   `:2177`, *"six places"* / *"all six change"*: `check-matrix.sh:4–5` now also states the definition
   of done and the brief itself counts "seven sites"; say seven, or say six plus the script's own
   header. Note that the phrase grep returns nine lines — the seven sites plus `:2133` and `:2342` in
   the brief — which is fine and worth one clause so the next counter does not re-derive it.

6. **[IMPROVEMENT] Three places in the rebuilt `FINDINGS.md` section disagree with the brief or with
   themselves, and the third looks like a rebuild loss.** (a) `FINDINGS.md:88–89` says M27 is *"green
   on 3.12/3.13/3.14"*; `:912–919` says the three greens were of different trees and *"every version
   green means nothing unless the versions saw the same tree"*, and the same-tree sweep the researcher's
   brief calls owed is recorded nowhere in the file. The phase line should say what is true: *"green
   per version on differing trees; the same-tree sweep is owed before it is called done"* — this is
   the file's own "confidently stale state at the top" lesson, and it is stale on the day it was
   written. (b) `:921–922` states 3.13 and 3.14 *"report 49"* `ResourceWarning`s; the review brief
   says 49/47. Name which run each number came from, and if the count moves between runs of one tree
   say so beside the existing *"collection timing is unmeasured"* sentence — a moving count is
   evidence about the mechanism, and a fixed "49" hides it. (c) Done-when 12 asks this section to
   record *"the review trail"*; it cites the brief review at `:819–820` and never names
   `reviews/m27-python-range-code-review.md`, which appears only in `FINDINGS-archive.md:3236`. Add
   it beside the brief-review citation.

7. **[IMPROVEMENT] The second half of F11 did not land: the rule that the three subset runs must
   share one identity lives only in a shell comment and a FINDINGS paragraph.** `coding-standards.md`
   §9 (`:363–365`) says a subset *"is not a milestone gate"* and nothing about how three subsets become
   one; `.claude/agents/memory-researcher.md:42` — the instruction that produces the one-version-per-call
   form — says nothing about comparing the printed identities; `py-runner.md:54–59` reports the line
   "verbatim", which happens to carry the identity but does not say that is what the caller needs from
   it. Add to §9: *"The milestone gate is every tested version green **on one tree identity**, which
   the script prints on its last line; three subset runs are a gate only if their identities
   match."* Add the same clause to `memory-researcher.md:42`, and to `py-runner.md:56` *"…and the tree
   identity after `on`, which the caller compares across versions"*.

8. **[NITPICK] The two filters disagree on `PendingDeprecationWarning`, and the measurement is on the
   wrong version.** `check-matrix.sh:113` errors on both classes in-process; `:114` exports only
   `DeprecationWarning` to children. Either add `,error::PendingDeprecationWarning` to
   `PYTHONWARNINGS` or say why the spawned processes get the narrower net. And `:110` says *"measured
   on 3.13"* for a filter whose whole purpose is the newest minor; when the 3.14 run completes, record
   that instead — if mypy itself warns there, the export is the cause and the note should say what to
   do (narrow it, not drop it).

9. **[NITPICK] Three small things in `test_version_seam.py`.** (a) `:39`'s `.*` runs to end of line, so
   `from sys import argv  # the version of…` trips it on a comment; bound it to `[^#]*`. (b) A
   parenthesised multi-line `from sys import (\n    version_info,\n)` escapes every line-wise pattern;
   `ruff`'s `I` rules keep a short import on one line, so the residual is a list long enough to wrap —
   name it in the docstring, or add bare `\bversion_info\b|\bhexversion\b`, neither of which has an
   innocent use in this tree. (c) `sysconfig.get_config_var("py_version_short")` is a further running-
   version read with no legitimate use here (grep: none) and could join `:44`. And the function name
   at `:105` still says `merely_end_in_clients` after F15 corrected its docstring to "contain".

### Verified and not re-raised

F5 (`asyncio_compat.py:26–28` names `row_for` and says why the argument comparisons do not fold); F6
(all five families plus `python_version_tuple`, one sample per pattern at `:91–99`, and a grep over
`zikaron/` and `tests/` for every forbidden spelling returns hits only in the two exempt files — the one
`sys.version` in `experiments/embedder-precision/latency.py:96` is outside the scan's scope, correctly);
F7 (`FINDINGS.md:912–919`); F8 (`main.py:92–97`, first statement in the `try`, with a comment giving
the reason); F9 (names not numbers at `build-plan.md:1941–1946` and `FINDINGS.md:877–884`); F10 (all
seven sites carry the phrase on one line, `check-matrix.sh:5` included); F12 (`:52–64`, all
interpreters resolved before any run); F13 (`asyncio_compat.py:41–45`, `test_asyncio_compat.py:49–50`,
both say "explicit caller"); F14 (`check.sh:59`); F16 (no pip upgrade). `test_check_gate.py:34,43`
parse `minors=(3.12 3.13 3.14)` (the indented `minors=("${requested[@]}")` at `:47` does not match
`^minors=`), `coding-standards.md:234` and `README.md:65`. §9's command block matches `check.sh`.
`schema.md:5–13` records the three builds as `FINDINGS.md:862–867` describes. `CLAUDE.md:65–71` names
the matrix as the hermeticity exception by reference. `test_service_main.py:559–562` is correctly
scoped to the signal path. The F1 stamp is written after a successful install and an interrupted
install leaves no stamp, as claimed; the stamp key is complete for what `pip install -e` reads, since
no `setup.py`, `setup.cfg` or `MANIFEST.in` exists — finding 3 is about what that install does not do,
not about the key.

VERDICT: NEEDS_CHANGES

## Round 3 — 2026-09-21

### Summary judgment

Eight of the nine round-2 fixes land as described and I walked the six `tree_identity` cells against
the script rather than the brief: deletions and staged content ride in `git diff HEAD`, untracked
paths are read `-z`, a dangling symlink is skipped, mode-only changes carry `old mode`/`new mode`
lines, and nothing the run itself writes (`.coverage`, the three caches, `*.egg-info/`,
`.venv-matrix/`, `*.log`) is outside `.gitignore`, so the guard cannot trip on its own output. Two
things are not ready. **F6 did not land** — the brief reports all three edits and `FINDINGS.md` still
carries the round-2 text at every one of the three sites — and the rebuild condition that F3(a)
made load-bearing has a hole that this machine will fall into on its next reboot, because every
matrix venv's base interpreter lives in the session scratchpad under `/tmp`. Beyond those, §6 now
contradicts the paragraph beneath it, and the reasoning §6 withdrew survives in two other files.
One process note, stated once here rather than as a finding: this round was spawned into a live
sweep with an instruction to write under `reviews/`, and that write changes the tree identity — so
the sweep now running will refuse at its end, or its per-version identities will differ, **by the
script's design**. The identity is doing its job; the protocol around it is what finding 5 is about.

### Findings

1. **[BLOCKER] Round 2's F6 is reported as landed and none of its three edits is in the file.**
   `FINDINGS.md:88–89` still reads *"M27 — `requires-python >=3.12` behind a version seam — is
   built, green on 3.12/3.13/3.14, and in code review"*, the sentence F6(a) was to replace with
   "green per version on differing trees; the same-tree sweep is owed". `:928–929` still reads
   *"3.12 reports 0 warnings, 3.13 and 3.14 report 49"* with no per-run attribution and no 47
   (F6(b)). And `reviews/m27-python-range-code-review.md` is cited nowhere in the file — a grep for
   `code-review` returns nothing, and the only trail citation is still the brief review at `:819–820`
   (F6(c)). Read twice, at the start of this round and again before writing it; unchanged both times,
   and the line numbers are the ones round 2 quoted, so the region has not moved since. Whether the
   edits were lost — this file was destroyed and rebuilt from context once today, and `CLAUDE.md`
   changed under me between two reads during this round, so concurrent editing is the working
   state — or were never made, the effect is the same: the always-loaded phase line is false on the
   file's own terms, and the brief's "accepted, done" is not evidence about the tree. **Fix**: land
   the three edits as round 2 specified, then re-verify by reading the file rather than the
   transcript. Note that after this round's own append the same-tree sweep is owed *again*, so the
   phase line's honest form today is still "owed", not "done".

2. **[BLOCKER] A venv whose `bin/python` dangles is neither rebuilt nor recreated, and on this
   machine that is the expected future of all three.** `check-matrix.sh:126` rebuilds only when
   `-x "${venv}/bin/python"` is **true** and the stamp is wrong; `:131` creates only when it is
   false. A venv whose base interpreter has been removed satisfies neither usefully: `bin/python` is
   a symlink into the interpreter's directory, `test -x` follows it and is false on a dangling
   link, so `:126` skips the `rm -rf` and `:133` runs `-m venv` over the existing directory — and
   CPython's `venv.EnvBuilder.symlink_or_copy` skips any `dst` for which `os.path.islink` is
   already true, so the dangling link is left exactly as it was and `ensurepip` then fails through
   it. The script dies with a Python traceback, no remedy is printed, and every later run does the
   same, because nothing ever removes the directory: the stamp is present, so even the comment's
   own promise at `:123–125` — *"a half-built venv has no stamp, so the next run rebuilds"* — does
   not apply. **This is not an edge case here.** `.venv-matrix/3.13/pyvenv.cfg` and
   `.venv-matrix/3.14/pyvenv.cfg` both give `home = /tmp/claude-1000/-home-nathan-Zikaron/<session>/
   scratchpad/uvprobe/pythons/cpython-3.1x.y-linux-x86_64-gnu/bin`; `.venv-matrix/3.12/pyvenv.cfg`
   gives `home = /home/nathan/.local/bin` with `executable` in the same scratchpad, so the
   `python3.12` shim on `PATH` points there too, and `command -v python3.12` will fall through to
   `/usr/bin/python3.12` (3.12.3, the `.venv` base) once it dangles.
   `research/python-portability-probes.md:68–69` records the scratch `UV_PYTHON_INSTALL_DIR` for the
   probes; nothing records that the matrix venvs were built on it. The scratchpad is session-scoped
   and `/tmp`-resident; `FINDINGS.md` already says of `/tmp` artefacts that they *"will not survive
   a reboot"*. So the sequence on this machine is: reboot → 3.13 and 3.14 refuse cleanly at `:56–61`
   (interpreter absent, correct) → 3.12 resolves to the system interpreter and wedges as above.
   **Fix, two parts.** (a) Make "exists but is not a finished, stamped venv on a live interpreter"
   the single rebuild condition:
   ```bash
   if [[ -d "$venv" && ( ! -x "${venv}/bin/python" || ! -f "$stamp" || "$(cat "$stamp")" != "$wanted_pyproject" ) ]]; then
       echo "check-matrix: rebuilding ${venv} (pyproject.toml changed, the last install did not finish, or its interpreter is gone)"
       rm -rf "$venv"
   fi
   ```
   and add the dangling case to the `:116–125` comment in its own terms (a symlink into a removed
   interpreter directory; `-m venv` over it does not replace the link). I reasoned this from the
   `venv` source rather than running it — no shell in this seat — so **reproduce in a scratch
   directory before trusting either the diagnosis or the fix**: `python3 -m venv v; ln -sfn
   /nonexistent v/bin/python; touch v/.zikaron-pyproject.sha256; python3 -m venv v` and observe
   whether `v/bin/python` is repaired (I expect not, and a non-zero exit from `ensurepip`). If venv
   *does* repair it, the finding downgrades to "the stamp survives a change of base interpreter and
   the install is skipped onto it", which the same condition also closes. (b) Record in
   `FINDINGS.md` §"M27 as built" where the three interpreters actually are — the session
   scratchpad, via `UV_PYTHON_INSTALL_DIR` — and that a durable `uv python install 3.12 3.13 3.14`
   into uv's default directory is owed before the next milestone's matrix run. The brief's
   §"Three interpreters have to come from somewhere" (`build-plan.md:2171–2176`) says `uv python
   install` puts shims on `PATH`; what shipped puts them in a directory the harness deletes.

3. **[IMPROVEMENT] §6's new limit paragraph contradicts the paragraph directly beneath it, precedes
   the phrase it limits, and is fused to the paragraph above it.** `coding-standards.md:255–263`
   says *"`requirements-lock.txt` exists at the repository root and nothing installs from it"* and
   *"two virtualenvs built on different days can carry different transitive versions"*.
   `:265–267`, the next paragraph, states the rule as *"pin them exactly in a lock file so a build
   is reproducible"* and gives as the rule's payoff *"an unpinned range means a green run today and
   a red one tomorrow with no change of ours"* — the exact outcome the paragraph above says is
   currently open. A binding document with the rule and its refutation in adjacent paragraphs
   leaves a reader to guess which binds. Two smaller defects in the same lines: the limit opens
   *"how far 'pinned exactly' reaches"* before the phrase has appeared (it is `:265`'s lead), and
   `:254→255` has no blank line, so in rendered Markdown the deprecations paragraph and the limit
   are one paragraph with two bold leads. **Fix**: swap the order and reword the rule to what is
   true —
   *"**`venv`, latest stable, pinned exactly.** Resolve to current stable versions, pin each
   **direct** dependency exactly in `pyproject.toml`, and bump deliberately rather than drifting: an
   unpinned range means a green run today and a red one tomorrow with no change of ours."* — then,
   after a blank line, the limit as *"**How far that pin reaches, and where it stops.** The
   transitive set is resolved when a virtualenv is built. `requirements-lock.txt` records one full
   resolution and nothing installs from it — … — so the outcome the direct pin prevents for direct
   dependencies is still open for transitives. Measured 2026-09-21: …"* (the rest as written).
   "Stated because the sentence that used to sit here overclaimed it" can go; the trail holds it.

4. **[IMPROVEMENT] The reasoning §6 withdrew survives in two other files, one of them the script
   the rule is about.** `check-matrix.sh:14–18`: *"… and dependencies are pinned exactly, so the
   local gate has nothing to learn from the filter that this does not tell it sooner"*. With
   transitives unpinned, a `.venv` rebuild can pull a transitive whose deprecation fires on 3.12
   while the stamped `.venv-matrix/3.12` still carries the older one — the local gate *would* learn
   something the matrix did not tell it. §6 `:252–254` now gives the interpreter as the only reason
   and drops this clause; the script header should match: *"And erroring on deprecations belongs
   here rather than in `pyproject.toml`: a deprecation raised only on a newer version is invisible
   to a single-version run whatever the filter says, so the filter belongs where the interpreter
   varies."* (Also fixes `:14`, which names one warning class where the script now sets two.)
   And `build-plan.md:2008–2015`, proposition 5: *"§6's own first rule pins every dependency
   exactly, so no upstream release can reach the local gate; only a pin bump can, and that is a
   change of ours"*, with a parenthetical saying the weaker framing is what *"the exact-pinning rule
   refutes"*. The pin covers direct dependencies; a transitive release reaches any venv on its next
   build, pin bump or not. F5's accepted principle is that the brief says what shipped — add
   *"(as built, narrower: the pin is on direct dependencies only, and §6 now states that limit; the
   interpreter reason stands on its own)"*. Both are the "sentences that followed from the change"
   class: neither shares a word with the §6 paragraph that was edited.

5. **[IMPROVEMENT] The whole-tree identity and the crew's own protocol collide, and the collision is
   documented only by the refusal itself.** `FINDINGS.md:920–926` records the guard catching an
   edit to `CLAUDE.md` during a live 3.12 run — *"the discipline is not sufficient"* — and this
   round was then spawned into a live sweep with an instruction to write under `reviews/`, a
   directory nothing in the gate reads. The identity hashes every difference from `HEAD` and every
   untracked file, so a review round landing, a `FINDINGS.md` note, or a `research/` edit during a
   sweep voids it. `coding-standards.md` §9 `:375–377` and `memory-researcher.md:43` both say what
   to do about edits *between* per-version runs and nothing about edits *during* one, and the
   reviewer protocol (`CLAUDE.md`, the `self-review` skill) says nothing about when it is safe to
   spawn a writer. **Fix, either of two.** (a) Keep the whole-tree identity — it is the honest one,
   and narrowing it is the judgement call the script's header refuses for file-conditional runs —
   and say the consequence where the rule lives: in §9 after `:377`, *"A sweep is also voided by an
   edit landing during it, whatever the file — the script samples the identity before and after
   and refuses if they differ — so a review round appending to `reviews/` or a note added to
   `FINDINGS.md` while a version runs costs the whole set. Spawn writers after the last version
   reports, not into a running sweep."*, and the same clause at `memory-researcher.md:43`.
   (b) Exclude `reviews/` and `research/` from both the diff and the untracked walk (`git diff
   --binary HEAD -- . ':!reviews' ':!research'`, and a `case` on the path in the loop): no file under
   `tests/` names either directory (grepped), `ruff` reads only `.py`, `mypy` only `zikaron tests`,
   and the drift tests read `design/`, `README.md`, `check.sh`, `check-matrix.sh` — so those two are
   the only directories provably outside every reader, and their exclusion is mechanical rather than
   a judgement. If (b), the `:73–74` comment, `FINDINGS.md:917–919` and §9 all say "every
   difference" and must say the exception. I would take (a): it is one sentence, and it names the
   behaviour this round just exhibited.

6. **[IMPROVEMENT] The brief's matrix contract omits the two behaviours §9 now depends on.**
   `build-plan.md:2112–2135` lists four bullets — the minors, the venv, the filters, the red minor
   — and nothing about the label check (F2, round 1) or the tree identity (F1/F11), both of which are
   as-built contract: §9 `:375–377` makes matching identities *the* condition for subset runs to be
   a gate, and `py-runner.md:57` and `memory-researcher.md:43` instruct against the last line's
   format. F5's principle applies. Add two bullets: *"checks that `.venv-matrix/<minor>/bin/python`
   reports the minor it is labelled with, before anything is installed into it, and refuses naming
   the remedy otherwise (as built)"* and *"prints a tree identity on its last line — `HEAD`'s short
   hash alone when the tree is clean, otherwise `HEAD+<12 hex>` over every difference from `HEAD`
   and the content of every untracked non-ignored file — samples it before and after the loop, and
   refuses if they differ; §9 makes matching identities the condition for per-version runs to
   count as a milestone gate (as built)"*.

7. **[NITPICK] "They have no undo" is false for one of the five, in both copies.** `CLAUDE.md:98`
   and `memory-researcher.md:42` list `git stash` among commands that *"have no undo"*; `git stash
   pop` exists. The reason stash belongs on the list is different and worth stating, because an
   agent who knows about `pop` will discount the whole rule: it takes *everything* uncommitted —
   which here is everything — in one step, and a stash nobody remembers is as gone as a revert.
   *"None of them has an undo an agent will find in time; `git stash` technically keeps what it
   took, but it takes all of it at once, and a forgotten stash is a lost one."* Otherwise the rule
   checks out: no instruction file, skill or design document tells an agent to run any of the five
   (grepped `*.md`); `build-plan.md:1907`'s `git checkout <sha>` is a commit checkout in a separate
   clone, and `FINDINGS-archive.md:4260` is history; `git reset` without `--hard` and `git restore
   --staged` are not named and are safe, consistent with "staging remains fine".

8. **[NITPICK] The version-argument membership test is a substring match.** `check-matrix.sh:42`
   `[[ " ${minors[*]} " == *" ${one} "* ]]` accepts `one=""` (the pattern `* *` matches any string
   containing a space). Anything else malformed fails earlier for other reasons, and `""` most
   likely dies at `:63` on an empty associative-array subscript — but if a bash build accepts that
   key, `venv` becomes `.venv-matrix/` and a second such run reaches `rm -rf` on the whole matrix
   directory: bounded to throwaway state, never outside it, and still not what a typo should do.
   Replace with exact equality in a loop over `minors` (`[[ "$one" == "$known" ]]`), which is
   also easier to read than the padded-string idiom.

9. **[NITPICK] One sentence in the brief is now stale by the milestone's own result.**
   `build-plan.md:2156–2157`: *"3.12 and 3.13 were not run under the filter, so a third-party
   deprecation there is the one way this can still surprise on first execution"* — all three have
   since run green under both filters. Mark as-built: *"(since run on all three; nothing further
   surfaced)"*.

### Verified and not re-raised

F1: the six cells walked against `:84–102` — clean → bare hash; deleted tracked file → in `git
diff HEAD`, nothing hashed from disk; staged and unstaged forms of one change → identical diff
against `HEAD`; untracked path with spaces → `-z`/`read -d ''`; dangling symlink → `-f` skips it;
mode-only change → `old mode`/`new mode` lines. Sampled before (`:107`) and after (`:172`), and
the run's own writes are all ignored so the guard cannot trip on itself. F2: `:136–148`, after
creation, before the stamp and the install, message names both remedies. F3(a): `:126–129`. F3(b):
§6's limit paragraph is accurate on what it asserts — every one of `pyproject.toml`'s twelve
entries is `==`, `README.md:85` and `check-matrix.sh:152` both install bare, and the lock file is
referenced nowhere an install reads. F4: `test_asyncio_compat.py:79–81` and `:102–105`. F5: all
four passages at `:2121–2125`, `:2126–2131`, `:2137–2138`, `:2178–2188`, nine-line grep explained.
F7: §9 `:375–377`, `memory-researcher.md:43`, `py-runner.md:57`. F8: both classes in both filters,
`PYTHONWARNINGS` syntax valid, and it is *not* exported around the `pip install` at `:152` or the
label check at `:144`, which is correct — pip's own deprecations on 3.14 cannot redden a build.
F9: `[^#]*` in both import patterns, `get_config_var` with a sample, the parenthesised gap named at
`:36–39`, the function name at `:112`. **`rm -rf "$venv"` reachability**: only through `:126`, only
with `-x` true; `$venv` carries a literal `.venv-matrix/` prefix and `$minor` comes from the literal
list or an argument checked against it; `sha256sum pyproject.toml` at `:109` precedes the loop, so
an invocation whose `cd` landed outside a project exits before any removal — safe as written, with
finding 8's caveat. New loop ordering: a refused label leaves an unstamped venv, which `:126`
rebuilds on the next run once the override is fixed; an interrupted `-m venv` likewise. The label
check's `sys.version_info` is in a `.sh` file, outside the scanner's `*.py` scope.
`test_check_gate.py` still parses `^minors=` at `:35` only. `.venv/pyvenv.cfg` is on
`/usr/bin/python3.12`, so `check.sh` itself is unaffected by finding 2.

VERDICT: NEEDS_CHANGES

## Round 4 — 2026-09-21

### Summary judgment

All nine round-3 fixes are in the tree as described, and the interpreter problem is closed at its
root rather than at the symptom: every `.venv-matrix/<minor>/pyvenv.cfg` now names
`~/.local/share/uv/python/…`, `~/.local/bin/` carries no `python3*`, and the rebuild condition at
`check-matrix.sh:168` covers the dangling case anyway. The conftest fix is the right shape for the
flake it fixes — the diagnosis matches the installed `aiosqlite` (`core.py:162–172`: `_connect`
calls `stop()` on `BaseException` and never joins) and a blocked worker still trips the deadline
and fails — and the per-version cache isolation covers every path the gate writes that is not
already interpreter-tagged, atomic by design, or derived from a per-test directory. Two things are
not ready. **Interrupting a `--parallel` run does not stop it**: bash sets SIGINT to ignored for
every background job when job control is off, the disposition survives `exec` into `check.sh`,
`timeout` and `pytest`, and nothing in the script kills them — so Ctrl-C leaves three full gates
running, and the next invocation merges their coverage into its own. And `FINDINGS.md` still
says the durable interpreters are *"Still owed … not done here"* under a heading that says they
are in the scratchpad, which is round 3's F1 class again: the always-loaded file stating a state
the tree refutes. One process note: this round writes under `reviews/`, so by §9's own rule the
sweep is owed again once the fixes land.

### Findings

1. **[BLOCKER] Ctrl-C (or any signal to the parent) on a `--parallel` run leaves all three gates
   running to completion, and the next run silently merges what they leave behind.**
   `check-matrix.sh:229–232` launches each version with `&` under `set -euo pipefail` and no
   `set -m`. Bash's rule for that case (manual, §Signals): *"When job control is not in effect,
   asynchronous commands ignore SIGINT and SIGQUIT."* An ignored disposition is inherited across
   `exec`, so `check.sh`, `timeout` and `pytest` all start with SIGINT ignored, and CPython
   installs its `KeyboardInterrupt` handler only over `SIG_DFL`, never over an inherited
   `SIG_IGN` — the three pytest processes cannot be interrupted from the terminal at all. The
   parent, sitting in `wait` at `:243`, *does* die on Ctrl-C. Nothing kills the children. Two
   consequences, both of the "gate that misleads" class `check.sh`'s own header names:
   (a) the next `--parallel` run truncates `check-matrix.<minor>.log` with `>` while the orphan
   keeps writing through its own descriptor, so the log the RED message points at is two runs
   interleaved; (b) `pytest-cov` writes per-process data files as `${COVERAGE_FILE}.<host>.<pid>.X…`
   and its finish step combines every `${COVERAGE_FILE}.*` in the directory — so an orphan that
   saves before the next run combines has its data, from a possibly different tree, folded into
   that run's coverage report, and a floor computed over two runs of two trees is exactly the
   "not a floor" the suffix was introduced to prevent (`check.sh:14–15`). The tree-identity guard
   cannot see any of this: the orphan is a process, not a difference from `HEAD`. SIGTERM from a
   harness timeout or a closed terminal (SIGHUP) behaves the same way.
   **Fix (~10 lines, before the launch loop).** A group kill is not enough, because coreutils
   `timeout` puts its command into a new process group of its own; walk descendants instead:
   ```bash
   # `timeout` runs pytest in a process group of its own, so killing a version's group would stop
   # `check.sh` and leave pytest running; walk the tree instead.
   kill_tree() {
       local child
       for child in $(pgrep -P "$1"); do kill_tree "$child"; done
       kill -TERM "$1" 2>/dev/null || true
   }
   on_signal() {
       echo "check-matrix: interrupted — stopping every version" >&2
       local pid
       for pid in "${pids[@]}"; do kill_tree "$pid"; done
       wait 2>/dev/null || true
       exit 130
   }
   trap on_signal INT TERM HUP
   ```
   (`pids` is empty until the loop runs, so a signal during venv preparation kills nothing and
   exits, which is right.) **Verify by doing it, not by reading**: run `./check-matrix.sh
   --parallel`, Ctrl-C after ~30 s, then `pgrep -af 'check.sh|pytest'` must return nothing and
   `ls .coverage.3.1*` must show no `.<host>.<pid>.X…` leftovers. Then answer one more question the
   fix does not: whether a stale `.coverage.<minor>.*` file from a run killed *outside* this trap
   (SIGKILL, power) is erased or merged by the next run — if merged, `rm -f
   "${COVERAGE_FILE}".*` at the top of `check.sh`, guarded on the suffix being non-empty so a
   plain `./check.sh` is unchanged, closes the leftover case. Rubric answer, stated plainly: the
   parallel mode weakens the "a floor is a floor" guarantee by this one path, and only this one.

2. **[BLOCKER] `FINDINGS.md:966–978` records the durable interpreters as owed and undone; the
   tree, the brief and `CLAUDE.md` say done.** The paragraph's lead is *"The three matrix
   interpreters are in the session scratchpad, and that is owed before the next milestone"* and
   it closes with *"**Still owed**: a durable `uv python install 3.12 3.13 3.14` into uv's default
   directory, with `uv` itself installed somewhere that survives — not done here, because where an
   operator's toolchain lives is his decision"*. Read against the tree: all three
   `.venv-matrix/<minor>/pyvenv.cfg` give `home = /home/nathan/.local/share/uv/python/cpython-3.1x-…/bin`
   (3.12.14, 3.13.15, 3.14.7), `~/.local/bin/python3*` does not exist, and `CLAUDE.md:51–88`
   documents the durable setup as *"Verified end to end on 2026-09-21"*. This is round 3's F1
   class — the always-loaded file asserting a state the file's own rules say gets edited, not
   withdrawn — and the phase line at `:88–90` is fine, which makes the stale paragraph 880 lines
   below it the one a fresh session will act on. **Fix**: keep the paragraph as the record of the
   hazard (it is the only place the shim's mechanism is written down), change its lead to *"were
   in the session scratchpad"*, and append: *"**Done the same day, on operator instruction,
   overriding the reason above**: `uv` installed durably, `uv python install --no-bin 3.12 3.13
   3.14` under `~/.local/share/uv/python/`, the `~/.local/bin/python3.12` shim removed, and all
   three `pyvenv.cfg` files re-read to confirm they name those paths. `check-matrix.sh` now asks
   `uv python find --managed-python --no-project` before falling back to `PATH`; the setup is
   `CLAUDE.md` §'Setting up a development environment'."* The overridden reason is worth one
   clause because it was a stated principle, and the operator's decision is the evidence that it
   does not bind here.

3. **[IMPROVEMENT] "Needs a `python3.<minor>` on `PATH`" survives in three files, and one of them
   contradicts itself thirty lines apart.** `CLAUDE.md:105` — *"It needs a `python3.<minor>` on
   `PATH` for each version it runs — machine state"* — sits under `CLAUDE.md:70` (*"both work with
   no `PATH` setup of any kind"*) and `:81` (*"so nothing needs to be on `PATH` at all"*).
   `check.sh:69` says the same as `:105`. `design/build-plan.md:2117–2120` says the opposite of
   what shipped: *"resolving each as `python3.<minor>` on `PATH` — `uv python install` puts
   exactly such shims there, which is how 'names interpreters rather than requiring uv' and 'uv
   in practice' reconcile"* — `--no-bin` exists precisely so that uv puts **nothing** on `PATH`,
   and `CLAUDE.md:75–82` now calls that *"the part to get right"* because the shim it prevents is
   what made every matrix venv ephemeral. `check-matrix.sh:72–78` is the accurate statement
   (three sources in order; `PATH` is the last resort). **Fix**: `CLAUDE.md:105` and `check.sh:69`
   → *"It needs an interpreter per version it runs — a uv-managed one, an explicit
   `ZIKARON_PYTHON_3_13`, or a bare `python3.<minor>` on `PATH` as the last resort — machine
   state, which `check.sh` depends on nothing of"*. `build-plan.md:2117–2120` gets an as-built
   note in F5's accepted form: *"(as built: three sources in order — the override, `uv python find
   --managed-python --no-project`, then `python3.<minor>` on `PATH`; `uv python install --no-bin`
   deliberately puts nothing on `PATH`, after a shim there pointed every matrix venv into a `/tmp`
   session directory)"*, and `:2135`'s *"an absent `python3.<minor>` with no override"* becomes
   *"no interpreter from any of the three sources"*.

4. **[IMPROVEMENT] The leak detector counts threads where it should track them, and the join is
   on the wrong set.** `tests/conftest.py:184–197` joins **every** live worker thread, baseline
   included, and `:203–205` compares counts. Two consequences. (a) The first fixture wider than
   function scope that holds a `Store` open — none exists today; I read all thirteen
   `scope="module"` fixtures and they are encoders and parsed design tables — would make every
   test in its module pay the full 5 s at teardown, because `join(timeout=remaining)` on a thread
   that is not going to exit spends the whole deadline, and the symptom would read as slow tests
   rather than as a detector cost. The constant's comment (`:176–180`) says the headroom is
   *"free"*; it is free only for threads that are exiting. (b) After a detected leak,
   `_stop_open_connections()` (`:155–164`) queues the stop and does not join, so the *next* test's
   `before` can count the still-exiting thread — the same millisecond window this fix exists for —
   and `len(after) - before` then masks one genuine leak in that test. Both go away with identity
   instead of arithmetic:
   ```python
   before = set(_live_connection_threads())
   yield
   leaked = _settled_new_connection_threads(before)   # joins only threads not in `before`;
   if leaked:                                          # returns those still alive after
       _stop_open_connections()
       ...
   ```
   and join the stopped threads after `_stop_open_connections()` under the same bound so the
   next test starts from a clean baseline. Rubric answer: **yes, every genuine leak still
   fails** — a worker blocked on its queue never exits, `join` returns at the deadline, and the
   thread is counted; the two cases above are a future cost and a masked *second* failure, not a
   false pass today. The `1, 0, 0, 2, 1` measurement in the constant's comment matches
   `FINDINGS.md:934–935`.

5. **[IMPROVEMENT] The "one version per call" era survives in the script's own header and in
   `FINDINGS.md`.** The brief predicted more of this class and there are three. (a)
   `check-matrix.sh:24–29` describes arguments and the `SUBSET RUN` label and never names
   `--parallel` — every instruction file now calls that the normal form, and the script's header
   is the one place a reader of the *script* learns how to invoke it. Add after `:29`:
   *"`--parallel` runs every version at once, each into its own `check-matrix.<minor>.log` with its
   own coverage file and caches (`ZIKARON_CACHE_SUFFIX`), and is the form the instruction files
   name; virtualenv preparation stays sequential (see below)."* (b) `check-matrix.sh:102–103`:
   *"when versions are run one per call — which is how a long loop gets driven — nothing otherwise
   connects them"* → *"which `--parallel` makes unnecessary but arguments still allow"*. (c)
   `FINDINGS.md:898–899`: *"**It takes version arguments** because the full loop outlasts a single
   command — that is how py-runner drives it — and a subset run says so"* → *"took version
   arguments because the sequential loop outlasted a single py-runner command; `--parallel`,
   added on operator instruction, brings the whole set inside one call (~3.5 min warm), and
   arguments remain for debugging one version"*. Everything else in this class checks out:
   `coding-standards.md` §9 `:375–393`, `CLAUDE.md:111–114` and `:258`, `memory-researcher.md:43`,
   `py-runner.md:54–64`, `build-plan.md:2143–2149` all agree on the normal form, the isolation
   mechanism, the sequential preparation and the during-a-run rule.

6. **[NITPICK] `py-runner.md:55` says 3.5 minutes is "comfortably inside one command" and nothing
   makes that true.** `.claude/settings.json` sets no `BASH_DEFAULT_TIMEOUT_MS`; the harness's
   documented default for a Bash call is 120 s, with a per-call `timeout` up to 600 s that the
   *runner* has to pass. The crew evidently already drove ~3-minute single-version runs through
   py-runner, so haiku is presumably setting it — but the instruction file does not say so, and a
   run killed at the default is finding 1's orphan case exactly. One line: *"pass the Bash tool's
   maximum `timeout` (600000 ms) for this command; the default is two minutes."*

7. **[NITPICK] `.gitignore:35–36`'s example names a path the script never writes.**
   *"`.coverage.3.13`, `.mypy_cache-3.13`"* — `check.sh:34` builds `".mypy_cache${suffix}"` with
   `suffix=".3.13"`, so the second is `.mypy_cache.3.13`. The pattern `.mypy_cache*` covers both,
   which is why nothing broke; the comment should still name the real shape.

8. **[NITPICK] The one shared path the suffix does not isolate is the model cache, and the first
   parallel run on a fresh machine populates it three times at once.** `encoder.py:238` calls
   `TextEmbedding(model_name=…)` with no `cache_dir`, so fastembed's default under the system temp
   directory is shared by all three runs — correct, it is one model — but on a machine that has
   never loaded it the download and extraction happen *inside the tests*, concurrently.
   `huggingface_hub` locks per-file downloads; nothing here serialises the rest, and I have not
   verified fastembed's extraction path. Either say in the `:205–207` comment that the first run
   on a fresh machine is the one unverified case, or pre-warm once during the sequential
   preparation phase, which would also prove `onnxruntime` imports on each interpreter before
   three gates start.

### Verified and not re-raised

Round 3: F1 — `FINDINGS.md:88–90` names one sweep and one identity, `:951–952` attributes 49/47/48
per run, `:821–822` cites this file. F2 — `check-matrix.sh:161–171`, and the root cause is gone
per finding 2's reading of the three `pyvenv.cfg` files. F3 — §6 `:256–268`, rule before limit,
blank line present. F4 — `check-matrix.sh:14–16` gives the interpreter reason alone;
`build-plan.md:2009–2012` carries the as-built narrowing. F5 — §9 `:387–393`,
`memory-researcher.md:43`, `CLAUDE.md:111–114`, all three say during-a-run edits void the sweep.
F6 — `build-plan.md:2139–2154`, both bullets. F7 — `CLAUDE.md:141–143` and
`memory-researcher.md:42`, stash reasoning corrected in both. F8 — `check-matrix.sh:54–64`,
exact equality, empty string refused. F9 — `build-plan.md:2175–2178`.
**Parallel-mode isolation, walked path by path**: `COVERAGE_FILE`, `RUFF_CACHE_DIR`,
`MYPY_CACHE_DIR` and `-o cache_dir` (`check.sh:32–35,80`) cover the four tool caches;
`__pycache__` is interpreter-tagged (`*.cpython-312.pyc` beside `-313`, `-314`) so three
interpreters never write one file; `.hypothesis/` is written by ten test files and Hypothesis's
directory database is atomic-rename by design; sockets derive from `paths.socket_path(runtime,
store_dir.resolve())` over `tmp_path`/`mkdtemp` store directories, so three suites cannot
collide on a socket path; console scripts are resolved from the venv's `scripts` directory
(`test_install_main.py:62,285,582`), never by `shutil.which`, so `.venv`'s 3.12 entry points
cannot leak into a 3.13 run; `tree_before` at `:142` is sampled before preparation, and
`zikaron.egg-info/`, `.venv-matrix/`, `*.log` and the four `*`-suffixed cache patterns are all
ignored, so the guard cannot trip on the run's own output. `wait` at `:243` is inside an `if`, so
`set -e` does not short-circuit the per-version report. `requested=("${args[@]+"${args[@]}"}")`
is correct under `set -u` for an empty list. **Conftest**: the fixture is function-scoped and
autouse, so it is set up first and torn down last, after every function-scoped store fixture has
closed; a sync teardown joining threads needs no loop; `remaining <= 0: break` then counts, so
the bound is one deadline over the set as the docstring says. `test_check_gate.py:34` still
parses `^minors=` at `check-matrix.sh:33` only.

VERDICT: NEEDS_CHANGES

## Round 5 — 2026-09-21

### Summary judgment

All eight round-4 fixes are in the tree as described, the `extend-exclude` change does what its comment
says and loses nothing the gate was usefully checking (the two directories hold 81 `.md` and two
`.jsonl`, no `.py`, and 81 is exactly the 394→313 drop — which is also the evidence that ruff 0.16.7
enumerates Markdown), and the conftest rewrite is correct on every path I walked, including the
two `_settle` calls. What is not ready is the signal trap: it was verified against one delivery
shape — a terminal Ctrl-C — and that is the one shape in which the intermediate shells survive to be
walked, because bash starts `&` jobs with SIGINT *ignored*. For `TERM` and `HUP`, which the trap also
names and which arrive at the whole process group from an outer `timeout`, a harness kill, or a
hangup, the intermediate `bash` processes die at once, `timeout 600` and `pytest` (in their own group)
are reparented before `pgrep -P` runs, and the orphan round 4 described is back — minus only the
leftover-fragment case `check.sh`'s new `rm -f` closes. One blocker with a two-command reproduction,
one improvement on where the Markdown exclusion should live, and hygiene.

### Findings

1. **[BLOCKER] The descendant walk works only while the intermediate shells are alive, which is
   guaranteed for a terminal SIGINT and false for the `TERM` and `HUP` the trap also claims.**
   `check-matrix.sh:229–247`. Bash's rule is specific: with job control off, an `&` job ignores
   **SIGINT and SIGQUIT only**; `SIGTERM` and `SIGHUP` keep their default disposition in the
   `run_one` subshell, in `check.sh`'s bash, and in `ruff`/`mypy`. So the round-4 verification —
   Ctrl-C in a terminal — is the one case where the subshell and `check.sh` survive (they ignore the
   signal) to be walked, and `timeout`/`pytest` (their own process group, never signalled by the
   TTY) are found through them. Every non-interactive interruption delivers to the **group**: an
   outer `timeout N ./check-matrix.sh --parallel` sends `TERM` to its child *and* `kill(0, TERM)` to
   its group; a harness killing on timeout does the same or worse; `kill -- -<pgid>`; a terminal or
   ssh hangup sends `HUP` to the foreground group. In all of those the `run_one` subshell and
   `check.sh`'s bash are dead (default action, no deferral — a non-interactive bash does not wait
   for its foreground child on an untrapped `TERM`) before the parent's `wait` returns and
   `on_signal` forks its first `pgrep`; `pgrep -P <dead subshell>` is empty because the survivors
   were reparented; `kill -TERM` hits a zombie; `exit 130`. Three `timeout 600 …/pytest` trees keep
   running, each `run_one` still holding the *old* descriptor of `check-matrix.<minor>.log`. The
   consequences are round 4's, less one: `check.sh:42–44` now erases fragments a *finished* orphan
   left, but an orphan still running when the next `--parallel` starts interleaves its log with the
   new one's, lands `.coverage.<minor>.<host>.<pid>.X` files mid-run for that run's combine to fold
   in, and finally writes its own combined `.coverage.<minor>` over the new run's. The identity guard
   cannot see any of it (`.coverage*` and `*.log` are ignored).
   **A second gap the walk can never close, whatever survives**: every service the integration tier
   starts is spawned with `start_new_session=True` and an inherited environment
   (`lifecycle.py:270–293`, `hook/connect.py:250–253`), so it carries pytest-cov's `COV_CORE_*` and
   writes a fragment into the project root on its own clean exit — and its spawner is the OS parent
   *only while the spawner lives* (the comment at `:280–292` says so). A service started by a hook
   process is reparented within ~70 ms and is invisible to `pgrep -P` from then on; after an
   interrupted run it idle-stops on its own clock and its fragment lands whenever that is.
   **Fix: find the run's processes by content, not ancestry.** Export a per-invocation token into
   `run_one`'s environment and kill every process whose `/proc/<pid>/environ` carries it. Anything
   that can write a fragment inherited pytest's environment and therefore carries the token; a
   subprocess a test spawns with a hand-built `env=` (five sites under `tests/`) has neither the
   token nor `COV_CORE_*`, so it can neither be found nor write. Forked subshells show the parent's
   *initial* environment in `/proc` and so are not matched; they exit when their children do and
   are reaped by the existing `wait`. ~12 lines, replacing `kill_tree`:
   ```bash
   # Found by a token in each process's environment rather than by walking parent links: a
   # group-delivered TERM or HUP (an outer `timeout`, a harness kill, a hangup) kills the
   # intermediate shells before this handler runs, after which `timeout`/`pytest` have no
   # ancestry left to walk — and a service a test spawned is reparented the moment its hook
   # exits. Everything that inherited pytest's environment carries the token; so does everything
   # that can write a coverage fragment, because `COV_CORE_*` travels the same way.
   ZIKARON_MATRIX_RUN="matrix-$$-$(date +%s%N)"
   export ZIKARON_MATRIX_RUN
   kill_run() {
       local pid
       for pid in $(grep -lsz -- "ZIKARON_MATRIX_RUN=${ZIKARON_MATRIX_RUN}" /proc/[0-9]*/environ \
                    | cut -d/ -f3); do
           kill -TERM "$pid" 2>/dev/null || true
       done
   }
   ```
   and `on_signal` calls `kill_run` once instead of looping over `pids`. Keep `-TERM`: the service
   handles it before its bind (`57907c9`), pytest dies at once. **Reproduce before and after, and
   let the reproduction decide the tag**: on warm venvs, `timeout 120 ./check-matrix.sh --parallel`
   from a terminal (by 120 s all three `check.sh` are inside pytest), then after it exits
   `pgrep -af '\.venv-matrix/'` — before the fix I expect three `timeout 600 …/pytest` lines and
   three `pytest` lines still running; after it, nothing. If nothing survives *before* the fix, my
   reading of group delivery is wrong and this finding is void — say so in the round-6 brief and
   keep the walk. Either way the `:215–228` comment should name the delivery shapes it covers, since
   today it reads as covering all three signals.

2. **[IMPROVEMENT] The Markdown exclusion is placed by directory while its stated reason is about a
   file type, and three trees the reason applies to harder are still in scope.** `pyproject.toml:81–88`.
   The comment's argument — fences are quotations of code as it *was*, and reformatting edits the
   record — is truest of `FINDINGS.md` and `FINDINGS-archive.md`, the withdraw-in-place record, and
   of `.kiro/`, which `CLAUDE.md:269` says is not to be edited; all three stay in `ruff format
   --check .`'s scope, as does `design/`. None has bitten yet, and I checked why: `.kiro/`, `.claude/`
   and both FINDINGS files carry **zero** Python fences, and `design/`'s four (`coding-standards.md:214`,
   `knowledge-index.md:1347,1563,2021`) are one comments-only block and three signature stubs that
   **do not parse** (`) -> object` with no body), which is the only reason ruff has never rewritten
   them. The first parseable fence in any of those files turns the gate red until `ruff format .`
   rewrites a normative document or the reference tree — and §9's *"formatting is not reviewed"*
   then silently covers design prose. The directory form also costs something forward: `ruff check`
   no longer reaches any `.py` that later lands in `research/`. **Fix**: find where `*.md` enters.
   `.venv/bin/ruff config include` prints the default; if `*.md` is in it, state `include = ["*.py",
   "*.pyi", "*.ipynb", "**/pyproject.toml"]` explicitly and drop `reviews`/`research` from
   `extend-exclude`; if Markdown is instead a `[tool.ruff.format]` option (`ruff config format`), turn
   that off. Keep the comment's reasoning, re-pointed at the file type — it is the right reasoning.
   If 0.16.7 has neither knob, keep the directory exclusion, add `.kiro` (the one tree the
   instructions forbid editing), and say in the comment that `design/` and the two FINDINGS files stay
   in scope by choice. Rubric answer on `research/`: it contains no runnable code — 83 files, 81
   `.md`, two `.jsonl` probe captures — so nothing was being usefully linted there.

3. **[IMPROVEMENT] The always-loaded phase line names a tree identity that is already one sweep
   behind.** `FINDINGS.md:88–90` says green *"on a single verified tree identity
   (`51d0105+e9e8740c3db2`)"*; the round-5 brief's latest sweep is `51d0105+3d5ecaf872a6`, and by
   §9's own rule the sweep is owed again after this round's append. A twelve-hex identity in the
   phase line has a half-life of one edit — the M13-hash lesson this file records about itself.
   Replace the hex with a statement that survives edits: *"green on 3.12, 3.13 and 3.14 in one
   parallel sweep on one tree identity — the current one is in the review file's latest round, and
   the sweep is owed again after any edit, this file included"*.

4. **[IMPROVEMENT] The brief's matrix contract and the FINDINGS as-built block omit the two
   behaviours round 4 added.** Round 3's F6 principle, accepted and applied twice since: the brief
   says what shipped. `build-plan.md:2115–2158` has no bullet for interruption or for fragment
   erasure, and `FINDINGS.md:891–916` records four things the build taught and not the fifth — that
   bash starts `&` jobs with SIGINT ignored, so a parallel run could not be stopped from the
   terminal at all — nor the sixth, that `ruff format` reaches into Markdown, which is a reusable
   lesson currently written down only in a `pyproject.toml` comment. Add one bullet after `:2158`
   whose mechanism matches whatever finding 1 settles on: *"stops every process it started on
   `INT`/`TERM`/`HUP` (as built, after a review round: bash starts `&` jobs with SIGINT ignored, so a
   Ctrl-C would otherwise leave three full gates running), and `check.sh` erases
   `${COVERAGE_FILE}.*` fragments before its gate whenever the suffix is set, so a run killed outside
   the trap cannot lend its data to the next"*; and a sentence in the as-built block for each of the
   two lessons.

5. **[NITPICK] The trap is installed after virtualenv preparation, so a `TERM` to the parent during
   `pip install` orphans the install.** `check-matrix.sh:247` sits below the `:153–210` loop. A
   terminal SIGINT during preparation is fine (foreground group, `pip` dies, bash follows); a `TERM`
   or `HUP` to the parent alone kills bash and leaves `pip` finishing into an unstamped venv —
   harmless in itself, but a re-run inside its remaining seconds races `rm -rf "$venv"` at `:177`
   against it. Move the `trap` line above the loop: bash defers a trapped signal until the
   foreground `pip` returns, then runs the handler and exits 130 *before* the `printf > "$stamp"`
   at `:206`, so the venv is rebuilt next time; `pids` is empty so the handler kills nothing. One
   line moved.

6. **[NITPICK] The trap stays armed over reaped pids.** After the wait loop at `:291–298` every
   entry in `pids` has been reaped and can be reused by any new process, and the trap is still live
   through `tree_identity` at `:305` — a `git diff` plus a hash of every untracked file, seconds on
   a dirty tree. A signal there sends `TERM` to whatever now owns those numbers. `trap - INT TERM
   HUP` after the parallel block closes it; with finding 1's token this goes away by itself, since a
   reused pid does not carry the token.

7. **[NITPICK] In sequential mode Ctrl-C is deferred for the whole version and then discards its
   result.** `run_one` runs in the foreground at `:283`, so the parent's trap waits for `check.sh`;
   `check.sh`'s `timeout` is in its own process group and never receives the TTY's SIGINT, so
   pytest runs to completion (~3 min), `check.sh` returns, and *then* `on_signal` runs with an
   empty `pids` and exits 130. Nothing is orphaned, and the `timeout` predates M27, so this is out
   of fence — recorded because `INT` in the trap line reads as if it applies to both modes. If it
   should: run the sequential branch through `&` + `wait` as well (one code path; the trap fires at
   once in both modes), or `timeout --foreground` in `check.sh`, which trades away the expiry
   group-kill for subprocesses tests spawn *without* `start_new_session`.

8. **[NITPICK] `check.sh:38–39` asserts three events as having happened here, and the corpus records
   none of them.** *"a `SIGKILL`, a power loss, an OOM kill, all of which have happened here"* —
   grepped `FINDINGS*.md`; the only hit is `FINDINGS-archive.md:4853–4854`, which lists them as
   *possible* deaths the service does not handle. `CLAUDE.md`'s rule is measured reasons. *"any of
   which skips the combine — as does the `TERM` the matrix's own interrupt sends, since coverage
   saves only at exit, while subprocesses that had already exited have saved theirs"*.

9. **[NITPICK] `pyproject.toml:86–87` calls `experiments` "throwaway probes".** `CLAUDE.md:48–49`
   separates the two on purpose — `experiments/` re-runnable harnesses, `spikes/` throwaway probes.
   *"probes and experiment harnesses are not held to the shipped standard"*.

10. **[NITPICK] `_settle`'s docstring describes the caller.** `conftest.py:187–193` — *"Only the
    threads this test actually added are waited on and counted"* is what the fixture's filter at
    `:216` guarantees; `_settle` waits on whatever it is handed, and its second call at `:221` is
    handed the leaked set. Move the paragraph to the fixture's docstring, or open it with *"The
    caller passes only threads the test added; comparing counts instead would…"*.

### Verified and not re-raised

Round 4: F1's terminal-Ctrl-C path holds for the reason given in finding 1 — the async jobs ignore
SIGINT and survive to be walked, `timeout`'s group never sees the TTY signal, and `kill_tree` reaches
`pytest` directly with `TERM`; `check.sh:42–44` erases `"${COVERAGE_FILE}".*` with the glob correctly
outside the quotes, cannot match a sibling version's files or the bare `.coverage.<minor>`, and is
guarded on the suffix. F2 — `FINDINGS.md:982–1002`, lead in the past tense, the hazard kept, the
override recorded with its overridden principle. F3 — `CLAUDE.md:104–107`, `check.sh:77–79`,
`build-plan.md:2120–2124` as-built note, `:2139` "from any of the three sources". F4 — identity
tracking is correct: higher-scoped fixtures set up before and tear down after the autouse one, so a
module-held store's thread is in `before` for every test and joined by none; `Thread` hashes by
identity; a thread that outlives the second `_settle` lands in the next test's `before` and is
excluded; `_target` is deleted only after the target returns, so a thread past its target is in
neither set. The second `_settle` is necessary (`stop()` queues and never joins), bounded to one more
deadline, and its return is rightly discarded; `pending = list(threads)` closes the generator hole.
F5 — `check-matrix.sh:24–35`, `:107–113`, `FINDINGS.md:898–902`. F6 — `py-runner.md:55–57`. F7 —
`.gitignore:35`. F8 — `check-matrix.sh:261–267`. No prose outside the script asserts anything about
interruption (grepped `interrupt|Ctrl-C|orphan` over the instruction files, design and FINDINGS), so
finding 1 has no cascade to sweep. `test_check_gate.py:34` still parses `^minors=` at
`check-matrix.sh:39` only. `README.md:459–462` carries the phrase. `"${pids[@]:-}"` with the `-n`
guard is correct under `set -u` for an empty associative array, and `kill -TERM … || true` plus
`pgrep` in a `for` word list cannot trip `set -e` inside the handler.

VERDICT: NEEDS_CHANGES

## Round 6 — 2026-09-21

### Summary judgment

All five round-5 fixes are in the tree as described, the token mechanism is the right one and I found
no cascade in the restructured script: the stamp, label check, sequential preparation, per-version
isolation and both identity samples are intact, and `test_check_gate.py` still parses `^minors=` at
`check-matrix.sh:39` alone. Two things are not ready. The handler's **first statement is an `echo`
to stderr under `set -e`**, so on the one `HUP` shape that actually happens — a closed terminal or a
dropped ssh session, where the pty is already hung up and every write to it returns `EIO` — bash
exits at line 190 before `kill_run` runs, and the orphan set rounds 4 and 5 were spent on is back
for the signal the trap line names last. And `_join_abandoned_worker` is **product code with no
test that can go red without it**: both of its branches execute (so the ratchet sees nothing), the
matrix filter errors only on deprecations, and the `getattr` guard turns the one library change its
docstring names into a silent no-op — while the docstring attributes to this path a symptom the
library's own code shows the path cannot produce, which bears directly on the stopped hunt: a grep
finds an unclosed raw `sqlite3.Connection` the hunt's premise says does not exist. Tree identity as
reported in the round-6 brief: `51d0105+78d7ce621829`; this append voids it, per §9.

### Findings

1. **[BLOCKER] `on_signal` aborts before `kill_run` whenever its stderr is dead, which is the
   common `HUP`.** `check-matrix.sh:189–194`: the handler's first statement is `echo "…" >&2`.
   A terminal closing or an ssh session dropping hangs the pty up *first* — that is what generates
   the `SIGHUP` — and every subsequent write to it returns `EIO`; bash's `echo` returns failure on a
   write error, `set -e` is in effect inside a trap action, and the shell exits with the handler
   one line in. `kill_run` never runs, `timeout 600 … pytest` × 3 and any spawned service keep
   going, and the next `--parallel` run inherits the interleaved logs and the coverage fragments —
   the outcome of round 4's finding 1, on the delivery shape the trap line at `:198` names third
   and the build-plan bullet at `:2154` and `FINDINGS.md:919–926` both claim. The round-5
   reproduction (`timeout 130`) is a `TERM` with a live terminal, so it could not see this.
   **Fix (two lines).** Kill first, and never let the message decide anything:
   ```bash
   on_signal() {
       kill_run
       echo "check-matrix: interrupted — stopped every process this run started" >&2 || true
       wait 2>/dev/null || true
       exit 130
   }
   ```
   **Reproduce before and after, and let it decide the tag** — the mechanism is a failing write,
   which `/dev/full` supplies deterministically: on warm venvs,
   `./check-matrix.sh --parallel 2>/dev/full & sleep 90; kill -HUP $!; sleep 3; pgrep -af '\.venv-matrix/'`
   — before the fix I expect three `timeout`/`pytest` pairs; after it, nothing. Then the real
   shape once: run it in a `tmux` pane and `kill-pane` at ~90 s. If the pre-fix run leaves nothing,
   my reading of `set -e` inside trap actions is wrong and the finding downgrades to "reorder anyway,
   because the message is the one statement that can fail". Add "and it kills before it speaks,
   because on a hangup stderr is already gone" to the `:151–176` comment.

2. **[BLOCKER] `_join_abandoned_worker` is unpinned, and its guard makes the one failure it
   names silent.** `zikaron/core/store/connection.py:49–78`, called at `:169`. No test asserts
   the behaviour: deleting the `await _join_abandoned_worker(connector)` line leaves `./check.sh`
   and the matrix green, because (a) both branches already execute — the real-connector branch via
   `test_store_connection.py:49–55` and the `None` branch via `test_store.py:259–262` — so the
   ratchet cannot move; (b) neither `PytestUnhandledThreadExceptionWarning` nor `ResourceWarning`
   is errored by either filter; and (c) the conftest detector (`conftest.py:216`) *joins* an exiting
   thread before counting it, which is exactly the fix round 4 made and exactly why it cannot see
   this. The measurement in the docstring (`:61–62`, "twenty… sixteen… zero") lives nowhere in the
   repository — `spikes/` has no file mentioning the mechanism — so the only evidence the join
   works is a sentence. Meanwhile `:69–73` says a future library version "may keep its thread
   elsewhere; in both cases there is nothing to wait for": false in the second case — there is a
   thread, the code has lost it, and `getattr(connector, "_thread", None)` returns `None` and the
   bug comes back with nothing to say so. This project's own rule is that every guard added is
   mutation-verified; this one was verified against an off-tree script.
   **Fix, three parts.** (i) Type the guard so the tolerated case is the substituted-coroutine
   case only: `worker = getattr(connector, "_thread", None); if not isinstance(worker,
   threading.Thread): return`, and reword `:69–73` — absence is tolerated for a *substitute*
   connector, and a real `aiosqlite.Connection` without the attribute is what part (iii) catches.
   (ii) Commit the measurement as the test, in `tests/test_store_connection.py`, a **sync** test
   so each iteration gets its own loop:
   ```python
   @pytest.mark.filterwarnings("error::pytest.PytestUnhandledThreadExceptionWarning")
   def test_a_failed_connect_never_outlives_its_loop(tmp_path: Path) -> None:
       """Twenty failed connects on twenty loops: sixteen thread exceptions without the join,
       zero with it. Kept as the test because nothing else in the gate can tell the two apart."""
       for _ in range(20):
           with pytest.raises(aiosqlite.Error):
               asyncio.run(open_connection(tmp_path / "absent.db", pragmas=PRAGMAS, existing_only=True))
   ```
   **Verify it red with the join line removed before trusting it** — pytest's `threadexception`
   plugin already routes the worker's `RuntimeError: Event loop is closed` into that warning, and
   the marker turns it into a failure; if twenty is not enough to be reliably red on this machine,
   raise it, since the fixed case is deterministic (the join returns because the thread ended).
   (iii) A drift pin so a bump that moves the attribute reddens the matrix instead of disabling
   the join: `connector = aiosqlite.connect(":memory:"); assert isinstance(connector._thread,
   threading.Thread)` — an un-awaited `Connection` starts no thread and its `__del__` returns
   early on `_connection is None`, so the pin leaks nothing and the detector ignores it.

3. **[IMPROVEMENT] The docstring and `FINDINGS.md` attribute to this path a symptom it cannot
   produce, and the "one bug, two symptoms" story is the premise the stopped hunt rests on.**
   `connection.py:56–59`: *"raises `RuntimeError: Event loop is closed`. That exception escapes the
   thread, and whatever object it was carrying is dropped with nobody left to close it, which
   surfaces separately as `ResourceWarning: unclosed database`"*; `FINDINGS.md:991–999` says the
   same and closes *"One bug, two symptoms"*. Read against the installed library
   (`aiosqlite/core.py:116–132,162–172`): on a *failed* connect the worker's next item is
   `close_and_stop`, whose result is `_STOP_RUNNING_SENTINEL` — there is no `sqlite3.Connection`
   anywhere, because `sqlite3.connect` raised. And CPython assigns `self->db` only after
   `sqlite3_open_v2` succeeds, so a failed `sqlite3.connect` never has a database for 3.13's
   finalizer to warn about. What the join fixes is the thread exception; the `ResourceWarning`
   half of the story belongs to a *different* path (a connect that succeeded on the worker after
   its loop died — cancellation, not failure — which `except aiosqlite.Error` never sees and the
   join cannot reach). Consequence for the record: the 49 → 1 drop is the `closing` conversions
   alone, and the residual was never going to move with this change. **Fix**: say what the
   failed path actually drops (the stop sentinel and the thread's own exception), say what the
   "sixteen" counted (thread exceptions, presumably — the brief's own numbers are 16 → 0 for the
   repro and 49 → 1 for `closing`, which already adds up without a second symptom), and withdraw
   "two symptoms" in place at `:997`.

4. **[IMPROVEMENT] A raw `sqlite3.Connection` is opened and never closed at
   `tests/test_knowledge_invariants.py:299`, and it has exactly the residual's shape.**
   `((journal_mode,),) = sqlite3.connect(foreign).execute("PRAGMA journal_mode").fetchall()` — a
   temporary that is never `close()`d, two lines below a `handmade` connection that is closed in a
   `finally`. Since 3.11 a `sqlite3.Connection` is *not* freed when its last reference goes: its
   statement cache is `lru_cache(maxsize)(self)`, which holds the connection back, so the object
   lives until the cyclic collector reaches it, and on 3.13/3.14 the `ResourceWarning` then fires
   inside whichever test happens to be running — "fires wherever the collector reaches the
   object", `FINDINGS.md:974–975`, in the file's own words. `FINDINGS.md:1009–1010` lists the sites
   read for the stopped hunt — four product files and *"the shared test fixture"* — and not the
   `sqlite3.connect(` grep over `tests/`, which returns seven sites of which this is the one
   unclosed (`:292` closes, `test_knowledge_groups.py:788` closes, `test_install_takeover.py:124`
   closes; the two converted files are clean). I am not re-flagging the decision to stop; I am
   supplying the site the decision's premise — *"every open site reads clean"* — says does not
   exist, found by the grep `CLAUDE.md` says to run before spawning a round. **Fix**:
   `with closing(sqlite3.connect(foreign)) as probe: ((journal_mode,),) =
   probe.execute("PRAGMA journal_mode").fetchall()`; re-run 3.13 and 3.14 twice; if the residual is
   gone, withdraw `:1008–1023` in place rather than deleting it, since the 18-minute `tracemalloc`
   run is itself a result worth keeping.

5. **[IMPROVEMENT] `FINDINGS.md:1008–1023` contradicts its own head and the paragraph above it.**
   The paragraph opens with the hunt stopped because `tracemalloc` was run, found zero, and *"is a
   closed avenue, not an unlucky run"*; it ends with the pre-fix text: *"whether 3.13 added the
   warning or merely changed collection timing is unmeasured"* (`:1021–1022`) — refuted at
   `:976–977`, *"measured directly on both interpreters"* — and *"start by running the suite under
   3.13 with `tracemalloc` on"* (`:1022–1023`), the closed avenue, as the next step. `:1019–1020`'s
   *"The warnings are attributed to `tests/test_knowledge_files.py`"* is the pre-fix plural (49
   from the detach helpers, collected in the next file alphabetically) and the residual's current
   attribution is recorded nowhere. This is the edited-head, unedited-tail class the file records
   about itself. **Fix**: strike the three tail sentences in place, record where the residual is
   attributed now on each of 3.13 and 3.14, and rewrap `:1015`, a 200-character line the edit left
   behind.

6. **[IMPROVEMENT] The one `aiosqlite.connect` outside `open_connection` has the same failed-connect
   shape and is not joined.** `zikaron/core/knowledge/reporting.py:375–379`: a `mode=ro` connect
   on an orphan candidate, `except (aiosqlite.Error, OSError): return None`. A candidate that was
   listed and then unlinked, or one the process cannot read, fails the connect and returns at once
   with the worker mid-shutdown — the mechanism `connection.py:52–59` describes, and the
   `connection.py:55–56` sentence *"as every `existing_only` caller does"* reads as if this path
   were among the callers. Narrow, and real. **Fix**: make the join a module-level helper
   (`join_abandoned_worker`, exported from `connection.py`) and call it in reporting's `except`;
   the `:359–365` docstring already explains why this site bypasses the opener, so one line
   saying it does not bypass the join is enough. Or state there that the path is accepted
   unjoined and why — either is fine; silence is not, given `FINDINGS.md:991` says "fixed in
   product code" as if once.

7. **[NITPICK] `kill_run` matches the `grep` it forks, and the `$$` skip guards a case that cannot
   occur.** `check-matrix.sh:182–184`. The `grep` (and, depending on fork order, the `cut`) is
   exec'd with the exported token in its environment, and the `/proc/[0-9]*/environ` glob is
   expanded in that child *before* exec, so its own pid is in the list and it reads its own
   environ after exec — a match. Harmless: both have exited by the `kill`, `ESRCH` is suppressed,
   and a pid reused inside that window is the only false positive. Meanwhile `/proc/$$/environ` is
   the block from the script's own `execve`, before line 178 ran, so it never carries the token
   and `:184` skips nothing. Say both in the comment, or close them: `env -u ZIKARON_MATRIX_RUN
   grep -lsxz -- "ZIKARON_MATRIX_RUN=${token}" …` with `token` captured into a local first, `-x`
   anchoring the NUL-delimited record so the match is the variable and not a substring of some
   other one. Separately, `:175–176` — *"A subprocess a test builds its own `env=` for carries
   neither"* — describes an empty set: every `env=` under `tests/` spreads `os.environ`
   (`test_hook_main.py:660`, `:593`, `:624`; `test_install_targets.py:1026`;
   `test_install_e2e.py:125,244`), so all of them carry the token and are found. Reword to say
   that, since the sentence as written implies a class of process outside the net.

8. **[NITPICK] The phase line's pointer is only as true as the reviewer's habit.**
   `FINDINGS.md:88–91` says the current identity *"is in the latest round of"* this file; a round
   carries it only if the reviewer copies it from the brief, which round 5 did incidentally and
   this round does deliberately (`51d0105+78d7ce621829`, from the brief). Either say *"as copied
   from the round's brief"* or drop the pointer and keep the rule alone.

9. **[NITPICK] Round-5 nitpicks 8, 9 and 10 are unchanged and unmarked.** `check.sh:38–39` still
   says three deaths *"have happened here"* with no record of any; `pyproject.toml:93–94` still
   folds `experiments` under *"throwaway probes"*; `conftest.py:187–193` still describes the caller
   in `_settle`'s docstring. Round-5 F6 is closed by the token (a reused pid carries none) and F7
   is out of fence, as agreed. One line each if taken; recorded so they are not lost between
   rounds.

### Verified and not re-raised

Round 5: F1 — `:177–178` token, `:180–187` kill by content, `:189–194` one call, `:151–176` names
the three delivery shapes and the six-versus-zero measurement (the comment says `timeout 120`, the
brief `130`; the comment is the record). F2 — `pyproject.toml:81–95`: I cannot run `ruff config
include` from this seat, so the claim that `*.md` is in 0.16.7's default rests on the researcher's
measurement and the round-5 file counts, which are consistent with it (81 for two directories, then
25 more for the rest of the tree); the explicit list governs both `format` and `check`, so fences are
neither formatted nor linted, which is the intent; `.venv-matrix/` is outside ruff's scope through
`.gitignore` (`respect-gitignore`), not through the default `exclude`, which does not name it — worth
knowing, not a finding; `reviews/` and `research/` hold no `.py`, so "linted again" is vacuous today
and correct. F3 — `FINDINGS.md:88–93`. F4 — `build-plan.md:2154–2161`, and `FINDINGS.md:906` says
"Six" over (a)–(f). F5 — `:196–198` above the preparation loop; a `TERM` during `pip install` is
deferred until pip returns, the handler then exits before `:255` writes the stamp, and the next run
rebuilds. **`kill_run` walked against the process table**: `/proc/<pid>/environ` is the `execve`-time
block, so every process exec'd from the parent after `:178` carries it (`check.sh`'s bash, `ruff`,
`mypy`, `timeout`, `pytest`, and every service, hook or MCP process the integration tier spawns with
an inherited environment, `start_new_session` or not), the un-exec'd `run_one` subshells do not and
exit when their `check.sh` dies of `TERM`, other users' processes are unreadable and `-s` hides them,
a pid that exits between the glob and the open is `-s`-hidden too, a second concurrent matrix or a
bare `./check.sh` carries a different token or none, and `timeout` forwards `TERM` to its own group
so `pytest` is reached twice, harmlessly. The one gap is the sub-millisecond window between `&` and
`exec` in `:294`, where a not-yet-exec'd subshell is unmatched and then runs a full gate that
`on_signal`'s `wait` blocks on — three iterations, negligible, and not an orphan. `-z` does not
NUL-terminate `-l`'s filenames (that is `-Z`), so `cut` sees lines. **`_join_abandoned_worker` on
the path it does run**: `aiosqlite`'s `_connect` has already queued `close_and_stop` on a live loop
when `:169` runs, the worker delivers the sentinel through `call_soon_threadsafe` while this
coroutine is awaiting `to_thread` — the loop is open, so no deadlock — and exits, so the join
returns in microseconds and the 5 s bound is never spent; a timeout returns silently and the
original error still propagates, which is the pre-fix state and acceptable; `CancelledError` is not
an `aiosqlite.Error`, so cancellation is not joined, correctly (`stop()` was still called by the
library). **`closing` conversions**: `_record_a_different_model` commits explicitly inside the
block, which `closing` requires and a bare `with` did for it; `_count`'s cursor unpacking and
`_recorded_lock_pid`'s `except sqlite3.Error` both close on the error path, which is one of the
routes the old form leaked through. `test_check_gate.py:34` still parses `^minors=` at
`check-matrix.sh:39` only.

VERDICT: NEEDS_CHANGES

## Round 7 — 2026-09-21

### Summary judgment

All seven round-6 fixes are in the tree as described and I found no cascade in the code: the handler
kills before it speaks and nothing in it can trip `set -e`; the token search is exec'd without the
token and anchored on the whole record; the join is typed, pinned against the installed library, and
called on both failed-connect paths; the two new tests can go red only from their own threads,
because the conftest detector joins any abandoned worker at the end of the test that abandoned it.
Both deliberate additions are right in substance. What remains is prose, all of it in the passages
this round edited, and all of it the enumeration class this trail keeps recording: a measurement
whose stated total is one more than its own breakdown, in three files; a binding document that
names a `grep` which errors as written and a count of its output that is wrong (my own round-6
count — I am correcting myself); and a withdrawal that elides, rather than strikes, the one sentence
in the old block that was wrong for a *different* reason than the headline. Three one-line edits and
four nitpicks; no code changes. Tree identity as reported in the brief: `51d0105+6b81d6080e3c`; this
append voids it.

### Findings

1. **[IMPROVEMENT] "Ten surviving processes" is enumerated as nine, at three sites.**
   `check-matrix.sh:185–187`, `design/build-plan.md:2162–2163`, `FINDINGS.md:931–932` all give the
   `/dev/full` measurement as *"ten surviving processes — three `timeout`/`pytest` pairs and three
   indexer subprocesses"*: three pairs are six, plus three is nine. Either the count is ten and the
   breakdown omits one — most plausibly a service or hook the integration tier had spawned, which
   `pgrep -af '\.venv-matrix/'` would list by its `sys.executable` — or the count is nine. The
   direction of the result (many against zero) does not move, which is why this is not a blocker;
   but this is "name the quantity" in the always-loaded file and the brief's contract, stated three
   times, and a reader who adds it up stops trusting the paragraph. **Fix**: re-read the survivor
   list from the reproduction if it was kept and name the tenth (*"…three indexer subprocesses, and
   one service the suite had started"*), or change all three sites to the number the breakdown
   supports. Whichever it is, the three sites must agree — the brief's own "two documents stating
   one number is two sites".

2. **[IMPROVEMENT] The enumeration command in the binding document does not run as written, and
   the count attached to it is wrong.** `design/coding-standards.md:311` — *"The enumeration that
   finds every instance is `grep -n 'sqlite3\.connect(' tests/`"* — and `FINDINGS.md:1060` — *"…
   returns seven sites in seconds, of which exactly one was unclosed"*. Without `-r`, GNU `grep`
   given a directory answers `grep: tests/: Is a directory`, exit 2, and lists nothing; the one
   sentence whose job is to be *"the coverage claim"* is a command that returns no coverage. And a
   recursive grep returns **nine** lines, not seven: `test_knowledge_indexer.py:288,301,355`,
   `test_knowledge_detach.py:224`, `test_knowledge_groups.py:788`,
   `test_knowledge_invariants.py:293,304`, `test_install_takeover.py:124`,
   `test_install_claude_live.py:114`. "Seven" was my count in round 6, copied into `FINDINGS.md`
   as the reviewer's — it was wrong, and `:1065`'s *"The reviewer ran that grep"* is now attached
   to a number the grep refutes. Two of the nine (`indexer:288,301`) wrap across lines, so the
   matching line shows no `closing(`; the reader has to open each hit. **Fix**: `grep -rn
   'sqlite3\.connect(' tests/` at both sites; `FINDINGS.md:1060` → *"returns nine lines in
   seconds, every one of which was then read for a `closing(` or a `finally`, and exactly one was
   unclosed"*; and one clause in §6 saying the grep locates and the reading decides — which is the
   distinction `CLAUDE.md` draws and this paragraph is about.

3. **[IMPROVEMENT] The struck block at `FINDINGS.md:1044–1050` is an ellipsis, and what it elides
   includes a claim that was wrong on its own terms.** The strikethrough runs *"…so reading will
   not find it.** … **Cost of the residue…"* — a condensed paraphrase with the middle removed and
   the tail reordered, not the text that stood there. As the block read before this round's edit,
   the elided middle was: *"**The instrument that would name it destroys it**: a full suite under
   `tracemalloc` reported **zero** occurrences and took 18m35s against 3m10s … That is a closed
   avenue, not an unlucky run."*, *"**Not introduced by M27** — nothing it touched is in that path,
   and the 3.12 run of the identical tree is clean — and not a gate failure, since the filter errors
   only on deprecations."*, and *"**But it is exactly the class `design/coding-standards.md` §6
   calls 'a rule about process exit, not about tidiness'**: an unclosed connection holds a
   non-daemon thread and can keep a process alive after its work is done."* That last sentence was
   false independently of the hunt being wrong: a raw `sqlite3.Connection` has no thread — which
   `:996–998` in the same section says in so many words (*"raw connections with no thread at
   all"*) — so the residual was never the process-exit class, and the block that stopped the hunt
   had also mis-classed what it was hunting. The "Two claims survive" paragraph restates the
   `tracemalloc` result and the attribution; it does not record this one, and the ellipsis removes
   the evidence that it was believed. `CLAUDE.md`'s rule is that the original text stays. **Fix**:
   restore the elided sentences verbatim inside the strikethrough (the block is ~12 lines; the
   file can carry it), and add one clause to the correction: *"and the struck block also filed the
   residual under §6's process-exit rule, which a raw handle with no worker thread cannot be —
   the same distinction drawn three paragraphs up"*.

4. **[NITPICK] The test docstring quotes the second signal at N=50 and then explains N=20 with
   it.** `tests/test_store_connection.py:40–41` — *"Measured over 50 iterations with the wait
   bypassed: 3, 5 and 11 threads still alive on three trials, against 0 of 50"* — is followed at
   `:43–44` by *"which is why … the count is twenty rather than one"*. The test runs twenty; the
   headline reliability (`:36–37`, red 5 of 5, green 5 of 5) is of the test as written, so the
   guard is measured in position — but the reader is left to work out that the 50 was a separate
   probe. Say so: *"(a separate 50-iteration probe, not this test's 20)"*, or restate the alive
   count at 20. `FINDINGS.md:1021–1023`'s "0 to 13 of 20" is the *other* signal (thread
   exceptions) and does not cover this one.

5. **[NITPICK] Two words in the §6 addition overstate.** `design/coding-standards.md:303–304`:
   *"attributed to whichever test the garbage collector happened to be inside, **never** to the
   test that opened it"* — the collector can run inside the opening test; what was measured is that
   here it did not. *"…and not reliably to the test that opened it"*. And `:303` *"it **raises**
   `ResourceWarning`"* — it *emits* one; a warning is raised only under a filter that errors it,
   which neither gate filter does (`error::DeprecationWarning`/`PendingDeprecationWarning` only),
   and that is exactly why the sentence two lines down can say the matrix *reports* it rather than
   fails on it. Being precise here costs nothing and the paragraph is about precisely this.

6. **[NITPICK] `FINDINGS.md:992` — "Product code contains no raw `sqlite3` at all".** Three product
   modules import it: `service/log.py:57` (`sqlite3.sqlite_version`, the startup line M27 added),
   `core/store/transactions.py:46` (result codes), `core/knowledge/registry.py:65,77`
   (`IntegrityError`). None connects, which is the claim §6 makes and the one that matters. *"no
   raw `sqlite3` connection"*.

7. **[NITPICK] `design/build-plan.md:2154` says "after two review rounds"; the bullet narrates
   three.** Round 4 added the trap, round 5 replaced the walk with the token, round 6 reordered
   the handler — and the bullet's own text (`:2155–2163`) now describes all three. *"after three
   review rounds"*.

### Verified and not re-raised

Round 6: **F1** — `check-matrix.sh:212–217`: `kill_run` first, the message `|| true`, then `wait`
and `exit 130`; `:179–187` states the ordering and its reason. Nothing in the handler can trip
`set -e`: a `for` word list discards its command substitution's status, `kill … || true`, `wait …
|| true`. **F7** — `:204–207`: the `unset` runs in the substitution subshell, so `grep` and `cut`
are exec'd without the token; `-x` anchors the NUL-delimited record; the `$$` skip is gone and
`:193–200` says why neither the subshell's own `/proc` entry nor the script's carries the token (a
fork keeps the parent's `execve`-time block; the export came after). `:175–177` is now true: all
seven `env=` sites under `tests/` spread `os.environ` — `test_hook_main.py:593,624` (`{**os.environ,
…}`), `:660` (`dict(os.environ)`), `test_install_e2e.py:125` (`_hook_env`, `{**os.environ, …}`),
`:244`, `test_install_targets.py:1026`, `test_install_claude_live.py:94` (`os.environ.copy()`).
**F2** — `connection.py:89–91` types the guard on `threading.Thread`; `test_store.py:259–262`'s
substitute is an `async def`, whose coroutine has no `_thread`, so it returns — the one tolerated
case. `test_store_connection.py:21–64`: synchronous, one loop per iteration through `asyncio.run`,
`_recording` matches both call shapes `open_connection` uses (`:177,179`), the marker's filter
applies to setup, call and teardown, and it can go red only from its own threads — the conftest
detector (`conftest.py:217–222`) joins any abandoned worker at the end of the test that abandoned
it, so a thread exception from an earlier test lands in that test's teardown, not here. `:67–81`
starts no thread (`aiosqlite/core.py:176–178`: `__await__` starts it; `:98–100`: `__del__` returns
on `_connection is None`), so the detector ignores it, and its second assertion pins that premise.
**F3** — `connection.py:62–69` superseded in place; `FINDINGS.md:1008–1020` withdrawn in place with
the cancellation path recorded; `core.py:120–124` confirms `close_and_stop` finds `_connection is
None` after a failed connect. **F4** — `test_knowledge_invariants.py:22,300–305`. **F5** — the tail
sentences are inside the strike (finding 3 is about what else the strike does). **F6** —
`reporting.py:32,376–386`: the connect is split from the await and the `except (aiosqlite.Error,
OSError)` joins on both; `Thread.join` cannot raise here, since `__await__` starts the thread before
anything that can raise `aiosqlite.Error`. **Round-5 nitpicks 8/9/10** — `check.sh:37–42` lists the
deaths without claiming them; `pyproject.toml:93–95` separates probes from harnesses as `CLAUDE.md`
does; `conftest.py:184–190` describes `_settle` and `:207–213` the fixture. **§6 addition** — the
three claims that carry it are right: the context manager is transactional; 3.13 added the warning
(`research/python-313-314-porting-audit.md:54`, row 12, agrees); attribution is GC-timed. Its numbers
match `FINDINGS.md:981–982`. The try/`finally` sites (`test_knowledge_groups.py:788`,
`test_install_takeover.py:124`, `test_install_claude_live.py:114`) satisfy the rule's second clause,
so the tree conforms to the rule it now states. **Docstring counts** — `connection.py:57` "the
situation every caller of this function is in" is true of both callers. **Sweep** — no survivor of
"two symptoms" / "surfaces separately" / `_join_abandoned_worker` outside `reviews/` (`*.md`
corpus-wide, `research/` clean); the phase line `:86–94` carries no hex; `test_check_gate.py` still
parses `^minors=` at `check-matrix.sh:39` only.

VERDICT: NEEDS_CHANGES

## Round 8 — 2026-09-21

### Summary judgment

All seven round-7 fixes are in the tree as described, and I re-derived every number they touch
rather than reading it back: the survivor breakdown adds to its total at all three sites, the
enumeration command runs under GNU `grep` and answers nine, the struck block is the pre-round-6 text
word for word in one unbroken paragraph, and the three product modules that import `sqlite3` are
exactly the three `FINDINGS.md` now names. No code changed and nothing behavioural is wrong. What
remains is one sentence of the class the brief asked me to hunt — a cascade from round 7's own F1
fix, in the comment whose number was corrected: it now credits the three `zikaron.knowledge`
survivors to the explicit-`env=` mechanism, and no site that spawns those processes passes `env=`.
Round 7 verified the `env=` half of that sentence and not the attribution, so this is partly my
miss. One improvement, comment-only; two nitpicks, one of them a phrase I originated. Tree identity
as reported in the brief: `51d0105+5e850924e611`; this append voids it, per §9.

### Findings

1. **[IMPROVEMENT] `check-matrix.sh:175–178` attributes the three `zikaron.knowledge` survivors to
   the explicit-`env=` path, and none of them was spawned that way.** The sentence reads *"That
   includes every subprocess the suite builds an explicit `env=` for: each of those spreads
   `os.environ` into the mapping it passes, so the token travels with them too, and the three
   `zikaron.knowledge` processes the reproduction below left behind were found this way."* The
   seven `env=` sites under `tests/` (grepped: `test_install_e2e.py:152,244`,
   `test_install_targets.py:1026`, `test_hook_main.py:593,624,671`,
   `test_install_claude_live.py:94`) spawn hooks, services and installer probes — not one of them a
   knowledge process. Every spawn of `-m zikaron.knowledge.indexer` or `-m zikaron.knowledge` in
   the suite (`test_knowledge_indexer.py:218–224,237–241,258–264`, `test_knowledge_detach.py:191–196`,
   `test_knowledge_cli.py:369–375,394–399`) passes no `env=` at all, and neither does the product's
   own `detach.py:69–75` (`start_new_session=True`, environment inherited) — so whichever of those
   spawned the two indexers and the CLI, they carried the token by plain `subprocess` inheritance,
   the simplest case in the paragraph, not the `env=` case the sentence puts them under. Round 7's
   F1 corrected *"three indexer processes"* to *"three `zikaron.knowledge` processes"* in this
   sentence and the attribution around the number went unread; the pre-round-7 text was wrong in the
   same way, and my round-7 verification (*"`:175–177` is now true: all seven `env=` sites … spread
   `os.environ`"*) checked the spreading claim and not the "found this way" claim attached to it.
   **Fix (one sentence)**: end the `env=` clause at *"…so the token travels with them too."* and
   add, as its own sentence, *"The three `zikaron.knowledge` processes the reproduction below left
   behind were spawned with no `env=` at all and carried the token by plain inheritance — the
   default case, which is the one that matters most and the one every test-spawned indexer and CLI
   exercises."* Nothing else in the paragraph depends on the attribution; the mechanism claim
   (`COV_CORE_*` travels the same way, so anything that can write a fragment is findable) is
   unchanged and still true.

2. **[NITPICK] "Three paragraphs" is two, at both sites, and I wrote the phrase.**
   `FINDINGS.md:1083–1084` — *"refuted by a measurement three paragraphs earlier in this same
   section"* — and `:1106` — *"which the paragraph three above says in those words"*. Counting
   blank lines (`:982`, `:1004`, `:1048`), the paragraphs above the struck-block paragraph
   (`:1049–1111`) are `:1005–1047` and then `:983–1003`; both the *"measured directly on both
   interpreters"* sentence (`:988–989`) and *"raw connections with no thread at all"* (`:1002–1003`)
   are in the second, i.e. **two** above. Three above is the flaky-detector paragraph, which says
   neither. Round 7's F3 supplied *"the same distinction drawn three paragraphs up"* and the
   researcher copied it — the number-you-did-not-produce rule `:1088–1089` states, applied to the
   reviewer's own prose. *"two paragraphs earlier"* / *"the paragraph two above"*.

3. **[NITPICK] The correction note at `FINDINGS.md:934–935` records that the total was wrong and
   not that the breakdown beside it was too.** *"This read 'ten' at three sites until review round
   7 added up the breakdown printed beside it; the survivor list was in the scratchpad the whole
   time and the total was never derived from it."* The brief's own account is sharper: the
   breakdown said *"three indexer subprocesses"* and the list says two indexers and one CLI, so the
   old breakdown summed to nine only by coincidence — neither half had been read off the list. One
   clause: *"…and the breakdown was wrong as well — 'three indexer subprocesses' was two plus a
   `zikaron.knowledge` CLI — so neither number had been derived from it."* That is the lesson the
   note is there to carry, and the stronger form is the true one.

### Verified and not re-raised

**F1** — `check-matrix.sh:186–188`, `design/build-plan.md:2162–2163`, `FINDINGS.md:931–933` all say
nine; 3 + 3 + 2 + 1 = 9; the walk-era figure is consistent across its three sites too
(`check-matrix.sh:168–169` three pairs, `FINDINGS.md:926` six, `build-plan.md:2159` six). No
"ten"/"10 surviving"/"three indexer" outside `reviews/`. **F2** — both sites `grep -rn`
(`coding-standards.md:313`, `FINDINGS.md:1075`); I re-ran the enumeration over `tests/` and it is
nine lines: `test_knowledge_indexer.py:288,301,355`, `test_knowledge_detach.py:224`,
`test_knowledge_groups.py:788`, `test_knowledge_invariants.py:293,304`, `test_install_takeover.py:124`,
`test_install_claude_live.py:114`; the two that wrap are `indexer:287–289` and `:300–302`, with
`closing(` on the line above the match, as §6 says; the five that were wrong (indexer ×3, detach,
invariants `:304`) plus four `try`/`finally` sites account for all nine, so "five sites" and "nine
lines" are one enumeration seen at two times. For a GNU reader: `\.` and `(` are literal in BRE,
`-r` takes the directory operand, and since all nine are code lines rather than string constants no
`__pycache__/*.pyc` under `tests/` can carry the literal, so GNU `-r` answers nine as well. The
corpus-wide sweep for other prescribed bare-directory greps (`` `grep -<flags> '…' <dir>/` `` over
`*.md` and `.claude/`) returns only these two sites; `py-runner.md:43–44`'s are pipe and file forms.
**F3** — `FINDINGS.md:1049–1065` compared word for word against the block as it stood before round 6
(the pre-fix copy was in my context at spawn): identical, including the four sentences round 7
listed as elided; one paragraph, no internal blank line, opened at `~~**One` and closed at `on.~~`;
the correction at `:1103–1111` names the §6 misclass and the neighbour contradiction; the "two claims
still true" at `:1097–1102` match `:999` (git) and `:1062` (files), neither file among the nine.
**F4** — `test_store_connection.py:40–44`, the 50 named as a separate probe and the 20 as this
test's. **F5** — `coding-standards.md:303–305` *emits* and *not reliably*; the superlative is gone and
its replacement is accurate (the `sqlite3` module's own note: the context manager neither opens a
transaction nor closes the connection); no survivor of *"raises `ResourceWarning`"*, *"never to the
test"* or *"most common mistake"* outside `reviews/`. **F6** — `FINDINGS.md:995–998`; `import sqlite3`
under `zikaron/` is exactly `service/log.py:10`, `core/store/transactions.py:25`,
`core/knowledge/registry.py:14`, and none connects. **F7** — `build-plan.md:2154`. **§6 as a
neighbourhood** (`:299–316`): 47–49 / 48–56 / 0 match `FINDINGS.md:984–985`; "filed against two test
files that contained none of them" matches `:999` and `:1062`; "never fails a run" matches
`check-matrix.sh:293–294`; the statement-cache sentence is right for 3.11+ (`lru_cache(maxsize)(self)`
is a cycle through the connection). **`FINDINGS.md:1066–1072`** — "fifth" is four helper sites plus
one; 2,884 and zero `ResourceWarning`s match the brief. **The dogfooding note `:1090–1096`** — the
GNU half I can confirm (`--directories=read` is the default, so a directory operand is `EISDIR`); the
`ugrep` mechanism is the researcher's own `type grep` reading and I cannot run a shell from this seat
— it is consistent with the harness's `find`-wraps-`bfs` precedent at `FINDINGS-archive.md:4675`, and
the observable claim (works in the agent's shell, fails in the reader's) is what the note rests on.
**`check-matrix.sh:39`** is unchanged, so `test_check_gate.py`'s `^minors=` parse is unaffected.

VERDICT: NEEDS_CHANGES

## Round 9 — 2026-09-21

### Summary judgment

All three round-8 fixes are in the tree and each is correct on the point it was raised for: the
`env=` clause now ends where the evidence ends and the three knowledge survivors are credited to
inheritance, which every spawn path they could have come from — the six test sites and the product's
own `detach.py` — actually uses; both pointers are content-addressed with quotes that resolve verbatim;
the correction note now records the breakdown as wrong too. No code changed. What remains is the
class the brief asked me to weight, and it is in the two passages this round edited: the correction
note about a miscounted number mis-states *which* number summed to nine, and the sentence three lines
under the re-pointed quote still calls the two contradicting paragraphs *adjacent* — a positional
claim that survived a sweep for positional pointers because it shares no phrasing with them, and that
disagrees with *"a screen earlier"* in its own sentence. Two one-phrase edits and one nitpick; nothing
behavioural. Tree identity as reported in the brief: `51d0105+16188885a442`; this append voids it.

### Findings

1. **[IMPROVEMENT] The correction note says the old *total* summed to nine; the old total was ten.**
   `FINDINGS.md:934–936`: *"This read 'ten' at three sites until review round 7 added up the breakdown
   printed beside it — and the breakdown was wrong too, 'three indexer subprocesses' being two plus a
   `zikaron.knowledge` CLI, so the old total summed to nine only by coincidence."* The sentence opens
   by saying the total read ten and closes by saying it summed to nine. What summed to nine was the
   old *breakdown* (three pairs plus three), and the point being made is that its sum landed on the
   right number without either half having been derived. This is the note whose whole job is to carry
   "name the quantity", in the always-loaded file, and a reader who adds it up gets the same jolt
   round 7 described for the original. **Fix**: *"…so the old breakdown summed to nine — the right
   number — only by coincidence, beside a total that said ten."* Round 8's F3 wording said
   "breakdown"; "total" entered in the transcription.

2. **[IMPROVEMENT] "Two adjacent paragraphs" is false, and the same sentence says "a screen
   earlier".** `FINDINGS.md:1113–1115`: *"**Two adjacent paragraphs of one section contradicted each
   other about the same object**, which is this file's own neighbour-contradiction class, committed
   against a distinction it had drawn correctly a screen earlier."* The two paragraphs are the struck
   block (`:1053–1115`) and the `ResourceWarning` paragraph that ends *"raw connections with no thread
   at all"* (`:987–1007`); the *"second, unrelated defect"* paragraph (`:1009–1051`) sits between them,
   which is exactly the count round 8's F2 established and the brief says it re-derived (blank lines
   at `:1008` and `:1052`). "Adjacent" is the positional claim the brief's sweep was for, and it
   survived because it is not phrased as a pointer — `CLAUDE.md`'s "sentences that go stale are the
   ones that followed from what you edited". It also contradicts its own tail: adjacent paragraphs
   are not a screen apart. **Fix**: *"Two paragraphs of one section, a screen apart, contradicted each
   other about the same object — this file's own neighbour-contradiction class, committed against a
   distinction it had drawn correctly."* Round 7's F3 introduced the distance ("three paragraphs up")
   and I did not check "adjacent" against it in round 8; that is partly my miss.

3. **[NITPICK] The second content-addressed label names the wrong paragraph; the quote rescues it.**
   `FINDINGS.md:1110–1111`: *"which the leak-detector paragraph above says in those words (*'raw
   connections with no thread at all'*)"*. The paragraph a reader will take as "the leak-detector
   paragraph" is `:966–985` — its subject is the autouse leak detector, from *"the suite's own autouse
   leak detector"* through *"Fixed in the detector"* — and it does not contain the words. They are in
   `:987–1007`, the `ResourceWarning` paragraph, whose last sentence mentions the detector in passing.
   The verbatim quote means the reader recovers by searching, so this resolves, but not on the first
   try. Content addressing is the right form for this file — I agree with the brief's choice over my
   round-8 wording — and the label should name the paragraph by its subject: *"which the
   `ResourceWarning` paragraph above says in those words"*. The first pointer (`:1087–1088`) is fine:
   *"measured directly on both interpreters"* is at `:993`, unique in the section.

### Verified and not re-raised

**F1** — `check-matrix.sh:175–179`: the `env=` clause ends at *"…so the token travels with them
too."*; the next sentence credits the three `zikaron.knowledge` survivors to inheritance. Every path
that could have produced them passes no `env=`: `test_knowledge_indexer.py:218–223,237–241,258–263`,
`test_knowledge_detach.py:191–196`, `test_knowledge_cli.py:369–375,394–400` (the second is the
`status no` refusal test, argv built at `:385–393`), and the product's `detach.py:69–76`
(`start_new_session=True`, three `DEVNULL`s, no `env=`), which is what a test-driven `add`/`refresh`
reaches. `test_service_knowledge_management.py:57–61` monkeypatches `detach.spawn` and spawns
nothing. All seven `env=` sites under `tests/` remain the ones round 8 listed and none is a knowledge
spawn; `test_hook_main.py:660–671` builds `env = dict(os.environ)` before `env=env`, so `:175–176`'s
spreading claim holds at the one site that does not spread inline. No product module passes `env=`
(`Popen` at `hook/connect.py:250`, `service/lifecycle.py:271`, `hook/spawn_warm.py:74`,
`knowledge/indexer/detach.py:69`, all `start_new_session=True`). *"the reproduction below"* points
into the same comment block, which is a fixed unit. No *"found this way"* outside `reviews/`
(`test_hook_main.py:179` is an unrelated docstring). **F2** — both pointers quote text that exists
verbatim (`:993`, `:1006–1007`); no *"three paragraphs"*, *"paragraph three"*, *"paragraphs
earlier/up/above"* survives in `FINDINGS.md`. **F3** — `:934–939` records the breakdown as wrong, the
two-plus-CLI split, that neither number was read off the list, and the round-8 `env=` misattribution;
*"the simpler case the same paragraph already covers"* is true of `check-matrix.sh:173–174`. **Counts
across sites** — `check-matrix.sh:187–190`, `FINDINGS.md:931–933`, `build-plan.md:2162–2163` all say
nine; 6 + 2 + 1 = 9; the walk-era six is consistent at `check-matrix.sh:168–169`, `FINDINGS.md:926`,
`build-plan.md:2159`. **Build-plan bullet** — `:2154–2163` rewrapped with the same words, *"after
three review rounds"* intact, no breakdown and no attribution, so F1 could not cascade there.
**Round-usage** — *"until review round 7 added up"* and *"corrected in round 8"* both name the round
that found the defect, consistently.

VERDICT: NEEDS_CHANGES

## Round 10 — 2026-09-21

### Summary judgment

All three round-9 fixes are in the tree as described and each is correct on the point it was raised
for: the correction note now says the *breakdown* summed to nine beside a total that said ten
(`FINDINGS.md:934–937`); the two contradicting paragraphs are "a screen apart", which I re-derived
from the blank lines — the struck block `:1054–1116`, the raw-`sqlite3` paragraph `:988–1008`, the
aiosqlite-join paragraph `:1010–1052` between them (the brief's numbers are one lower throughout,
consistent with the F1 rewrap adding a line above them; nothing in the file cites a line, so nothing
is affected); and the relabelled pointer names the paragraph that actually contains the quoted words.
I hunted the cascade class the brief weighted hardest and found none: no sentence in the edited
passages depends on "adjacent", "total", or the old label, and the nine-and-its-breakdown agrees at
all three sites. **To the explicit question: there is nothing in the code, tests, or gate scripts I
would change.** I re-read `asyncio_compat.py`, `server.py`, `main.py`, `log.py`, `connection.py`,
`reporting.py`'s probe, the four M27 test files, `conftest.py`'s detector, `check.sh`,
`check-matrix.sh` end to end and `.gitignore`, and checked each mechanism against what CPython and
GNU grep actually do rather than against the comments; the list is under "Verified" below. The
remaining surface is entirely narrative, and what is left of that is three nitpicks, two of them
optional. Tree identity as reported in the brief: `51d0105+3a5fb8773281`; this append voids it.

### Findings

1. **[NITPICK] The emphasis added in transcribing round 9's F1 wording is invisible where it sits.**
   `FINDINGS.md:936`: *"so the old \*breakdown\* summed to nine"* is inside a note that is itself
   wrapped in single asterisks (`:934` opens `*This read "ten"`, `:940` closes `covers.*`). CommonMark
   parses that as `<em>` nested in `<em>`, which every common renderer shows as plain italic — the word
   the fix exists to stress carries no visible stress. The note's own idiom two lines down is bold
   inside the italic (`:938` `**neither**`). **Fix**: `**breakdown**`. My round-9 wording carried no
   markup; the asterisks entered in transcription.

2. **[NITPICK] "Exactly three places" is now four.** `design/build-plan.md:2349`: *"The set is written
   out in exactly three places and drift-tested in all three: §6 proposition 2 (canonical),
   `check-matrix.sh`, and `README.md:65`."* `CLAUDE.md:62` — `uv python install --no-bin 3.12 3.13
   3.14`, in the setup section written after the brief and verified end to end on 2026-09-21 — is a
   fourth, and `test_check_gate.py` does not read it (`FINDINGS.md:1132` repeats the command, but as a
   record of what was run, which is fine). This is the enumeration-drift class in the document that
   defines the count, so it is worth one clause; it is not more than that because the failure is
   self-correcting: when 3.15 joins `minors` and the stale command installs three of four,
   `check-matrix.sh:99–101` refuses and prints the remedy from its own list. **Fix**: drop "exactly",
   and add: *"…and once more as the install command in `CLAUDE.md` §"Setting up a development
   environment", which is not drift-tested and does not need to be — the script's own
   absent-interpreter message regenerates it from `minors`."*

3. **[NITPICK, optional] The venv reuse condition has no trigger for "same minor, different
   build".** `check-matrix.sh:250` rebuilds on a changed `pyproject.toml`, a missing stamp, or a
   dangling `bin/python`. An operator who points `ZIKARON_PYTHON_3_13` at a distribution 3.13 after a
   uv-built `.venv-matrix/3.13` exists gets the old base interpreter: the label check at `:268–272`
   passes (same minor), the stamp matches, and nothing prints which build ran except the patch
   version at `:301`. That is precisely the axis §"Distribution" says no seam can absorb — SQLite is
   the interpreter's, `FINDINGS.md:866–868` — and the reason the service logs it. Cheap fix if wanted:
   fold `realpath "$interpreter"` into the stamp content beside the `pyproject.toml` hash, so a
   different base rebuilds and a `uv python upgrade` that moves the managed build does too; the cost
   is one 200 MB rebuild per genuine change. Optional because `rm -rf .venv-matrix/3.13` is the
   documented remedy for every other stale-venv case and works for this one.

### Verified and not re-raised

**Round-9 F1** — `FINDINGS.md:934–940` in full: "read ten … breakdown was wrong too … old breakdown
summed to nine — the right number — only by coincidence, beside a total that said ten … neither
number had been read off it … corrected in round 8". Internally consistent, and consistent with the
figure at `:931–933`, `check-matrix.sh:187–190` and `build-plan.md:2162–2163` (nine; 6 + 2 + 1); the
walk-era six at `FINDINGS.md:926`, `check-matrix.sh:168–169`, `build-plan.md:2159`. No "ten
surviving", "three indexer" (outside the withdrawal at `:935`, which quotes it), "found this way"
(`test_hook_main.py:179` is unrelated) or "two symptoms" (outside the strike at `:1018` and the
supersession note at `connection.py:66–69`) anywhere outside `reviews/`. **F2** — `:1114–1116` reads
"Two paragraphs of one section, a screen apart"; "adjacent" survives in `FINDINGS.md` only at `:264`,
`:275`, `:359` (chunk adjacency, M26) and `:1314` (the class definition itself); no "three
paragraphs"/"paragraph three"/"two paragraphs earlier" anywhere. The class label still fits: `:1314`
defines it by *section*, and these are two paragraphs of one section. **F3** — `:1110–1112` names "the
paragraph above recording the raw-`sqlite3` defect", and `:997` opens that paragraph's defect sentence
with those words; the quote at `:1007–1008` is verbatim. The other content-addressed pointer,
`:1088–1089` "measured directly on both interpreters", resolves uniquely to `:994`. **Relational
claims not phrased as pointers**, swept over `:818–1138` for *adjacent / neighbouring / immediately
above|below / just above|below / next|previous paragraph / a screen / lines apart|above|below /
paragraph above|below*: only `:1111` and `:1115`, both correct. `:1072–1073` "two lines below a
connection the same test closes in a `finally`" is past tense about the pre-fix layout
(`test_knowledge_invariants.py:298–299` closes, the temporary followed the `finally` directly before
the four-line comment at `:300–303` was inserted) and is not re-raised. **Neighbours in §Distribution**
— `:838–843` (asyncio's guarded unlink) against `:844–848` and `:883–888` (the service's bare
unlinks) are about different unlinkers and say so; `:898` "three private reads" is `server.py:323,
328, 337`; `:900` "allowlist of two files" is `test_version_seam.py:60`; `:916–919` matches
`check-matrix.sh:233–253`; `:956–958` matches `:115–144`; `:979–982` matches `conftest.py:181–200`;
`:1016–1017` "join that worker off the event loop" is `connection.py:92` `asyncio.to_thread`;
`:1127–1128`'s rebuild condition is `check-matrix.sh:243` verbatim; `:1135–1137`'s two flags are
`:90`. `coding-standards.md:307` and `:313` agree with `FINDINGS.md:989–990` and `:1080`.

**The code, tests and gate scripts, against the mechanisms rather than the comments.**
*Seam* — `_ROWS` keyed `(3,12)`/`(3,13)`; `row_for` is greatest-key-≤ with a named floor; the
3.12 row reads the integer `_active_count`, the 3.13 row `len()` of `_clients`, which CPython 3.13 and
3.14 keep as a `weakref.WeakSet` (`len` valid); `cleanup_socket` reaches `create_unix_server`
through `start_unix_server`'s `**kwds` on 3.13+ and does not exist on 3.12, so the empty 3.12 row is
the only correct one; `unix_server_kwargs` returns `dict(tuple)`, fresh each call; the only version
comparisons are on `row_for`'s argument; `interpreter_version` keeps `platform` inside the seam. The
docstring's mypy argument (`pyproject.toml:147` `python_version = "3.12"`) is the measured one.
*Callers* — `server.py:26` imports both; `:323`, `:328`, `:337` are the three reads; `:413–415` passes
`**unix_server_kwargs()`; `log.py:56` reads the version through the seam. Unlink ordering as the seam
docstring states it: `lifecycle.py:116–117` and `:182–183` unlink then `shut_down`, `main.py:271–272`
likewise on the signal path, `:352`/`:370` close-then-unlink on the error path, `:502` in the force
exit — matching `architecture.md:718–726` and `test_service_main.py:559–562`. *Guards* —
`test_asyncio_compat.py:24–42` covers `(3,12)`, `(3,13)`, `(3,14)→(3,13)`, `(3,99)` and `(4,0)`;
`:45–53` the floor; `:56–64` the fresh mapping; `:73–105` goes through `server.serve` and
`shut_down()` and asserts `is_socket()` afterwards, which is the assertion that is false on 3.13+
without the row. `test_version_seam.py`: seven patterns assembled from fragments, both `sys` and
`platform` import styles, `[^#]*` so a trailing comment on an import is prose, word-bounded
`_clients`/`_active_count`, allowlist of exactly the seam and itself, and three self-checks (reaches
`server.py` and `test_service_server.py`, excludes the two, every pattern matches a sample). Nothing
under `zikaron/` or `tests/` matches outside the allowlist; `get_event_loop_policy` is gone from every
`*.py`, replaced through one helper (`test_service_main.py:38–45`, 15 call sites). *Log* —
`main.py:217` configures the file before `:218` reaches `log_runtime_versions` at `:97`;
`test_service_log.py` asserts both values are present and dotted, not merely that the call ran.
*Connection* — `join_abandoned_worker` is typed on `threading.Thread`, joins in `to_thread` under a
5 s bound, and is called on both failed-connect paths (`connection.py:183`, `reporting.py:385`);
`test_store_connection.py:23–67` is synchronous with one `asyncio.run` per iteration and pins
`_thread` at `:70–84`. *Detector* — `conftest.py:184–200` joins with one deadline over the set;
`:203–228` compares identity, not counts. *`check.sh`* — `ZIKARON_VENV` at `:26`, the four suffixed
paths at `:31–35`, fragment erase guarded on the suffix at `:43–45`, seven `--cov` flags which
`test_check_gate.py:55–57` compares to the tree. *`check-matrix.sh`* — `minors=(...)` at `:39` is
what `test_check_gate.py:34` parses and `:91–97` compares to `coding-standards.md:234` and
`README.md:65` (the regex's `\.` lands on the sentence's full stop before `**`); requested versions
are equality-checked against the list; three-source resolution with `--managed-python --no-project`;
an absent interpreter is `exit 1`; the label is read from the venv's own `python` before the install
and before the stamp; the stamp is written only after a successful install; preparation is
sequential and the runs are parallel with per-version logs, caches and coverage files; both warning
filters name the same two classes. Tree identity: `git diff --binary HEAD` plus `sha256sum` of every
untracked non-ignored regular file; `.gitignore:28,33,40–43,54` cover `.venv-matrix/`, `*.egg-info/`,
every suffixed cache and coverage path, and `check-matrix.<minor>.log`, so the run's own artefacts
cannot move the identity between the two samples. Interrupt: `grep -lsxz` — `-z` sets the input
record terminator so each `NAME=value` of `environ` is one record, `-x` anchors it, and without `-Z`
the listed filenames stay newline-terminated, so `cut -d/ -f3` sees one path per line; the token is
`unset` in the forked subshell before `grep` execs, and `/proc/<pid>/environ` is the execve-time
block, so neither the script nor that subshell can match itself; `kill -TERM` reaches `check.sh`,
`timeout` (which forwards to `pytest`), `pytest`, and every `start_new_session=True` child by token.
The one escape — a test spawning with an `env=` that does not spread `os.environ` — is structurally
paired with the inability to write a coverage fragment, since `COV_CORE_*` travels the same way, so
the harm the token exists to prevent cannot come from a process the token cannot find. `on_signal`
kills before it writes and every statement in it is `|| true`d or a `for` word list, so `set -e`
cannot end it early. *Packaging* — `requires-python = ">=3.12"`, `target-version = "py312"`, mypy
`3.12`; `test_check_gate.py:107–111` pins the first against §6.

Nothing above is a change I would ask for. The three findings are prose.

VERDICT: APPROVED

## Round 11 — 2026-09-21

### Summary judgment

The stamp change is correct and complete, and I checked it against the filesystem rather than
against the brief: `.venv-matrix/3.12/.zikaron-venv-stamp` holds the `pyproject.toml` hash and the
*patch*-named uv path (`cpython-3.12.14-…/bin/python3.12`), while the same venv's `pyvenv.cfg` shows
it was created through the *minor*-named link (`home = …/cpython-3.12-linux-x86_64-gnu/bin`,
`command = …/cpython-3.12-…/bin/python3.12 -m venv …`), which is exactly the symlink structure the new
comment claims `realpath` resolves — measured from disk, not read back from the comment. The rename
left no survivor of `.zikaron-pyproject.sha256` anywhere outside `reviews/`, on disk or in the corpus;
the rebuild condition, the message and the comparison agree with each other and with the three prose
sites the brief listed. To the brief's rubric (a): **one more site refers to the old rebuild
condition** — the References entry in `FINDINGS-archive.md` — and to (b): applying nitpick 2 left a
one-word quote dangling in `build-plan.md`, and the stamp change left the script's own one-sentence
statement of "the condition" stating half of it. Both are one-line and neither leads a reader to a
wrong action. Item (d) is accurate on every claim I could check and the list is six. Nothing here
is material; three nitpicks, and I would ship as-is. Tree identity as reported in the brief:
`51d0105+4de9b66ee82f`; this append voids it, per §9.

### Findings

1. **[NITPICK] The archive's References entry still states the round-1 stamp in the present tense
   and counts round 10's find out of "the same family".** `FINDINGS-archive.md:3242–3244`: *"Now
   keyed on a `pyproject.toml` hash stamp written after a successful install … Three more of the same
   family: nothing verified the **interpreter behind a version label** …"*. The stamp is now the hash
   and the base interpreter's `realpath`, and round 10's defect — a matching label over a different
   build of the same minor — is a fourth member of the family the sentence goes on to name (success
   reported for an interpreter that never ran). This is the one present-tense site the brief's
   by-meaning sweep did not list, and it is the direct answer to rubric (a). I am aware the archive
   records what was believed and when; that rule is about *moved blocks*, and this is an index entry
   the milestone's own notes say is maintained (*"indexed in `FINDINGS-archive.md` §References"*).
   **Fix (one clause)**: *"Now keyed on a `pyproject.toml` hash stamp written after a successful
   install — and, from round 10, the base interpreter's `realpath` beside it, since a matching minor
   over a different build had passed the label check and reused the venv."* and *"Three more"* →
   *"Three more of the same family, and that fourth"*, or leave the count and let the added clause
   carry it. If the researcher prefers to leave the archive untouched on principle, one dated
   sentence saying so beside the entry is enough.

2. **[NITPICK] The script's one-sentence statement of "the condition" now states half of it, and
   `FINDINGS.md` quotes a different string as the same condition.** `check-matrix.sh:263`: *"The
   condition is 'a directory that is not a finished, stamped venv on a live interpreter'"* — after
   this round the condition is also *the same* interpreter it was stamped with, which the paragraph
   above (`:233–247`) and the message at `:271` both say and this sentence does not. And
   `FINDINGS.md:1137–1139` quotes, in quotation marks, *"a directory that is not a finished venv,
   stamped for this `pyproject.toml`, on the live base interpreter it was stamped with"* — the fuller
   and more accurate form, which no longer appears in the script. Round 10 verified these two
   verbatim-equal (`:1127–1128` against `check-matrix.sh:243` then); this round's edit to one side
   broke that. **Fix**: make `:263` read the `FINDINGS.md` form, which restores the verbatim match
   and completes the sentence. Optional, same paragraph: `:257–259` wraps as *"…never removes a /
   dependency that the file has / stopped declaring"*, a five-word line left by the rewrap; and the
   lead sentence *"Reuse is keyed on `pyproject.toml`, not on the venv merely existing"* now reads as
   the whole key when the paragraph above has just said it is half — *"keyed on `pyproject.toml` and
   the interpreter, not on the venv merely existing"* costs four words.

3. **[NITPICK] `build-plan.md:2243` quotes `done-when 9's "exactly three places"`, and nitpick 2
   removed "exactly" from done-when 9.** `:2353` now reads *"written out in three places and
   drift-tested in all three"*; the quoted phrase resolves nowhere in the item it names. The
   reasoning around it still holds — listing the set in §9 would still falsify *"three places"* —
   so this is an inexact quote, not a false claim. **Fix**: `done-when 9's "three places"`. This is
   the class rubric (b) asked about: the phrase changed at one site and the sentence that quoted it
   shares the words, so a grep for `exactly three places` would have found it.

### Verified and not re-raised

**The stamp, against the code.** `check-matrix.sh:226` hashes `pyproject.toml` once; `:231` names
`.zikaron-venv-stamp`; `:248` resolves `$interpreter` through `command -v` — the same call `:95`
already required to succeed, so under `set -e` the assignment cannot fail — and `:249` `realpath`s it
with a fallback to the unresolved path, so a missing `realpath` or a symlink loop degrades to a
path-string comparison rather than to an exit. `:250` joins hash and path with one space; `:301`
writes it with `printf '%s\n'` and `:270` reads it back through `$(cat …)`, which strips exactly that
newline, so the comparison is byte-exact. The `||` chain at `:270` short-circuits, so `cat` runs only
when `-f "$stamp"` holds. The four causes in the message at `:271` are the four disjuncts of the
condition, in order. Every path out of the loop that can leave a stamp goes through the label check
first (`:288–292`, `exit 1` before `:298`), so a refused venv is still never stamped. **Migration**:
a venv built before the rename carries no `.zikaron-venv-stamp`, so `! -f` rebuilds it once — which
is what the brief's mutation runs paid — and the three venvs on disk now carry only the new file
(`Glob .venv-matrix/*/.zikaron-*` returns exactly the three `.zikaron-venv-stamp`s). Both stamps I
read share the hash `33124bac…` and name their own patch directory (3.12.14, 3.13.15). **Steady
state**: the same `uv python find` → same minor link → same `realpath` → no rebuild, consistent with
the brief's "no rebuild line". **A property the comment does not claim and gets for free**: because
the stamp holds the *resolved* path, a later `uv` that answers `python find` with the patch path
instead of the minor link would still match, so a uv upgrade alone cannot force a rebuild. **What the
venv itself does under `uv python upgrade`**: `pyvenv.cfg`'s `home` is the minor link, so the venv
would follow the new patch transparently even without a stamp; the rebuild the stamp adds is the
conservative choice — dependencies installed under one patch are reinstalled rather than run under
another — and the comment's "moves the target and rebuilds" is true as written. **One boundary,
recorded and not a finding**: for a distribution interpreter, `sqlite3.sqlite_version` comes from the
system `libsqlite3.so`, so a `libsqlite3` package upgrade changes SQLite behind an unchanged
`realpath`; the stamp cannot see that and does not claim to, and the service's startup line
(`log.py`) remains the observable, as §"Distribution" says. The corpus's "compiled into the
interpreter" phrasing predates this round and is exact for the standalone builds.

**Nitpick 1** — `FINDINGS.md:946` `**breakdown**`; the note is still wrapped `*…*` at `:944`/`:950`,
so bold-in-italic renders. **Nitpick 2** — `build-plan.md:2353–2358`: "exactly" gone, the `CLAUDE.md`
line named as a fourth untested copy with the reason; `check-matrix.sh:99–101` does print
`uv python install --no-bin ${minors[*]}` from the array, and `README.md:65` still carries *"Tested
versions: 3.12, 3.13, 3.14."* for `_STATED_TESTED_SET`. **Nitpick 3** — as above, plus the three
prose sites the brief listed: `CLAUDE.md:84–90` (changes-or-disappears, naming both the override
switch and `uv python upgrade`), `FINDINGS.md:1137–1139`, `build-plan.md:2128–2136` (the interpreter
half attributed to round 10, the SQLite reason beside it). No `zikaron-pyproject`, `pyproject.sha256`
or `hash stamp` survives outside `reviews/` except the archive entry in finding 1. **Item (d)**
(`FINDINGS.md:916–929`): round 1's finding was the `bin/python`-absent reuse (`reviews/…:27–29`);
round 10's was the interpreter half (finding 3 above); the SQLite figures match `:866–868`; the
three mutation cases match `check-matrix.sh:240–242`; the `realpath`/minor-link claim matches
`pyvenv.cfg` on disk. The list is (a)–(f), six, with (f) at `:954` and nothing after it before the
next bold paragraph. **Unchanged surfaces**: `check-matrix.sh:39` `minors=(...)` is what
`test_check_gate.py:34` parses and it did not move; `.gitignore` covers `.venv-matrix/`, so the stamp
cannot enter the tree identity; the `--parallel` path, the interrupt handler and the tree-identity
function are untouched by this round.

VERDICT: APPROVED

## Round 12 — 2026-09-21

### Summary judgment

Nothing in the code, tests or gate scripts has changed since round 11 and nothing in them needs to:
the six edits are in the tree as the brief describes, the verbatim match between `check-matrix.sh`
and `FINDINGS.md` is real (I normalised the wrap on both sides and compared inside the quotation
marks), and the `libsqlite3` paragraph is accurate on both halves — python-build-standalone links
SQLite statically, a distribution `_sqlite3` loads `libsqlite3.so.0`, and `sqlite3.sqlite_version`
reports whichever is linked at runtime. On the code this is the clean confirmation the brief expected.
What is not clean is the two rubric items the brief asked me to check against the record, and both
answers are "no": the eleven-rounds characterisation says round 10 found nothing behavioural while
the archive's own References entry — edited this round, on my round-11 wording — records round 10's
finding as a gate defect of the *"green for an interpreter that never ran"* family; and the phase
line's list of what landed unreviewed after round 11 omits two of the paragraphs the brief itself
lists. Both are one-paragraph fixes to `FINDINGS.md`, the phase line is superseded by this round's
existence anyway, and the next round need read three passages of one file. Tree identity as reported
in the brief: `51d0105+6551ca1cf080`; this append voids it, per §9.

### Findings

1. **[IMPROVEMENT] "Rounds 7–11 found nothing behavioural at all" is false of round 10, at two
   sites, and the archive says so in the same corpus.** `FINDINGS.md:833–836`: *"Rounds 1–6 found
   defects in the product and the gate; **rounds 7–11 found nothing behavioural at all** — every
   finding was corpus consistency in prose that the *previous round's own fix* had disturbed"*;
   `FINDINGS.md:1494–1496`: *"rounds 7–11 of that trail found nothing behavioural, so the capacity
   that ran out had been going into prose consistency for five rounds"*. Checked against rounds 7–11
   as recorded above:
   *Round 10, nitpick 3* — the venv reuse key had no trigger for "same minor, different build", so a
   repointed `ZIKARON_PYTHON_3_13` ran the old base interpreter and printed green. That is a
   behaviour of the gate, it was taken as a change to `check-matrix.sh` (the stamp now carries
   `realpath`), and `FINDINGS-archive.md:3244–3246` — edited this round — files it as *"reporting
   green for an interpreter that never ran"*, the family round 1's blocker belongs to. I tagged it
   optional; the researcher elevated it, and the archive entry is the one that is right.
   *Round 10, nitpick 2* — `"exactly three places"` against `CLAUDE.md`'s install line was
   enumeration drift from the setup section written at round 4, not prose round 9's fix had
   disturbed.
   Every other finding in rounds 7–11 is the cascade class as described, the class did produce a
   finding in each of the five rounds (round 10's was nitpick 1), and *"two of them were errors the
   reviewer had introduced"* is exactly right — round 7 F2's "seven" and round 8 F2's "three
   paragraphs". So the paragraph's lesson survives the correction; its universal does not. **Fix,
   both sites.** `:834–836` → *"rounds 7–9 and 11 found nothing behavioural; round 10 found one gap
   in the gate's reuse key (a different build of the same minor kept the old venv — optional as
   raised, taken, and the archive's 'fourth' of round 1's family) and one enumeration drift older
   than the round before it; every other finding in rounds 7–11 was corpus consistency in prose that
   the previous round's own fix had disturbed, and that class produced a finding in all five"*.
   `:1494–1496` → *"rounds 7–11 of that trail found one behavioural gap and otherwise prose, so the
   capacity that ran out had been going into prose consistency for most of five rounds"*. This is
   the two-sites class inside the paragraph about the two-sites class, which the corpus has caught
   itself in once before (`CLAUDE.md`'s "14 of 18").

2. **[IMPROVEMENT] The phase line's account of what is unreviewed names five things; seven
   paragraphs landed.** `FINDINGS.md:91–96`: *"Those three fixes, one comment naming a limit round
   11 had recorded in passing, and this status block itself landed **after** that verdict and are
   unreviewed"*. Not named: the §Harness second-instance paragraph (`:1488–1496`) and the
   §Distribution eleven-rounds paragraph (`:833–842`) — the brief's own items 5 and 6. *"(see
   §Harness)"* points at the first as the record of the outage, not as an edit awaiting review, and
   nothing points at the second. Rubric (d)'s answer is therefore "incomplete", and the omitted two
   are the two that finding 1 is about. **Fix, folded into the rewrite this round forces anyway**:
   the sentence *"round 12 was spawned to cover them and died on a `fable` rate limit before
   writing"* is now false, since round 12 has written; replace the whole italic aside with *"round
   11 approved the tree; round 12 confirmed the code unchanged and corrected two sentences of this
   file's own account of the trail"*, and carry the round count forward at `:831–833` (*"APPROVED
   after eleven rounds"*, *"What those eleven rounds are evidence of"*) so the number does not sit
   at eleven beside a twelfth header. `:1493`'s *"eleven headers, eleven `VERDICT:` lines"* stays —
   it is what the outage left, and it was true.

3. **[NITPICK] Edit 4 states the distribution case correctly and three older sentences still state
   the standalone mechanism as universal.** *"SQLite is compiled into the interpreter"* at
   `check-matrix.sh:234`, `FINDINGS.md:939` and `build-plan.md:2136` is exact for python-build-
   standalone and is the mechanism the new paragraph at `check-matrix.sh:249–253` says does **not**
   hold for a distribution build — the very contrast `:234–236` draws with the 3.45.1/3.53.1 figures.
   `FINDINGS.md:884` *"Pinning the interpreter is the only fix"* and `build-plan.md:2423` *"pinning
   the library means pinning the interpreter"* follow from the old sentence: with the limit stated,
   pinning `/usr/bin/python3.12` pins nothing about SQLite, and the fix is a *statically-linked*
   interpreter — which `build-plan.md:1960` (*"a single managed interpreter would … pin SQLite for
   free"*) already says. One word each: *"comes with the interpreter"* — `log.py:44`'s *"bundled
   with the interpreter rather than chosen here"* and `FINDINGS.md:882`'s *"bundled with"* are the
   forms in the corpus true of both builds — and *"pinning a standalone interpreter"*. Optional:
   nothing leads a reader to the wrong milestone, because every site that names the remedy names a
   managed one.

4. **[NITPICK] Two cosmetic leftovers of this round's edits.** (a) `check-matrix.sh:259` is now
   `# An editable install`, three words on a line — the rewrap moved the ragged line from `:257–259`
   rather than removing it. (b) `FINDINGS.md:1493–1494` *"measured twice rather than argued
   once"*: the first instance was also observed — `:1485`, *"every failure wrote nothing"*, four
   spawns — so *"observed twice"* is the accurate word.

### Verified and not re-raised

**(a), each edit against the tree.** Nitpick 1: `FINDINGS-archive.md:3242–3253` carries the
`realpath` clause and *"Three more of the same family, and that fourth:"*, after which the three
listed items are round 1's label check, the deprecation filter and the untied subset runs — the
colon introduces the three and *"that fourth"* refers back, which parses. Nitpick 2:
`check-matrix.sh:258` leads with *"keyed on `pyproject.toml` and the interpreter"*; `:269–270` is the
full condition. Nitpick 3: `build-plan.md:2243` quotes `"three places"` and `:2353` reads *"written
out in three places and drift-tested in all three"* — resolves. Edit 4: `:249–253`, and the
`sqlite3.sqlite_version` claim is right — the module reports the linked library's version, so on a
distribution build it moves with the package. Edit 5: `:1488–1496`, the 429 and the quoted last
words match the brief; I cannot verify the status code and do not need to. Edit 6: `:86–100` and
`:833–842` read as the brief says, with the two defects above. **(b)**: `check-matrix.sh:269–270`
and `FINDINGS.md:1153–1155` are identical inside the quotation marks after joining lines: *a
directory that is not a finished venv, stamped for this `pyproject.toml`, on the live base
interpreter it was stamped with*. **The count the §Harness paragraph rests on**: eleven `## Round`
headers and eleven `VERDICT:` lines before this append (grepped at the start of this round).
**The script's behaviour is untouched**: `minors=(...)` at `:39` is what `test_check_gate.py:34`
parses; the rebuild condition at `:277`, the label check at `:295–299`, the stamp write at `:308`,
the token search, the handler and both identity samples are byte-for-byte what round 11 read;
everything this round changed in the file is inside `#` comments. **Assumption stated**: I cannot
run `git` from this seat, so "anything in the tree the phase line does not name" was answered
against the brief's own change list, which is the six items; the tree identity in the brief is the
researcher's measurement, not mine.

VERDICT: NEEDS_CHANGES

## Round 13 — 2026-09-21

### Summary judgment

The M27 artefacts are clean: all four round-12 findings are applied as described, the withdraw-in-place
at §"Distribution" reads correctly beside its correction and disturbs nothing around it, the F3 fix
holds at every site I could find by meaning as well as by string (no sentence outside `reviews/` still
reasons from "compiled into", and the three "pin SQLite for free" sentences survive because the
interpreter they name is a managed, statically-linked one), and the `check-matrix.sh` condition string
is byte-identical to `FINDINGS.md`'s after the rewrap. Nothing in code, tests or gate behaviour has
changed. The one material item is in a non-M27 artefact: `py-runner.md`'s new rule names the right
defect, but the file still carries, six lines below it, the sentence that *licensed* that defect —
"if a command looks long-running … say so instead of hanging" — which is a plausible reading of exactly
what the backgrounded run did. That is one line; everything else here is nitpick-grade. Tree identity
as reported in the brief: `51d0105+c30af9d31ac5`; this append voids it, per §9.

### Findings

1. **[IMPROVEMENT] `py-runner.md` forbids backgrounding at `:51–62` and still permits the early
   return at `:67`.** The new rule: *"Run it in the foreground, pass the Bash tool's maximum
   `timeout` … and wait for it to exit … Never report a command as pending."* Six lines later, an
   untouched older rule: *"Run non-interactively; if a command looks long-running or interactive, say
   so instead of hanging."* `./check-matrix.sh --parallel` *looks* long-running by any reading, and
   "say so instead of hanging" is satisfied by *"Running in background (expected ~3.5 min). Awaiting
   completion."* — the agent said so and did not hang. So the brief's diagnosis, *"the real defect was
   backgrounding, which nothing forbade"*, is half the answer to rubric (c): nothing forbade it, and
   this sentence invited it. It is the neighbour class, in a prompt read by a low-effort model that
   now holds two rules pulling opposite ways on the one command this agent is most often given.
   **Fix (one line)**: `:67` → *"Run non-interactively; a command that would wait on a terminal is
   refused with a one-line verdict, not hung on. A command that merely looks long-running is not
   that case — run it in the foreground with the maximum timeout, per the rule above."* The end-to-end
   verification in the brief (one foreground run, identity reported verbatim) is evidence the bold
   rule wins when both are present; it is not evidence the older sentence is harmless.

2. **[NITPICK] `py-runner.md:56–58` states a consequence the gate's own reuse logic makes false.**
   *"re-asking would have started a second concurrent gate on the same tree — three more
   virtualenvs, and two runs' coverage fragments merging into one report."* On the warm tree that
   run was on, a second `check-matrix.sh` finds each `.venv-matrix/<minor>` with a matching stamp
   (`check-matrix.sh:275–278`, `:303`) and reuses it — no virtualenv is created. What a second run
   actually does is share the *same* three venvs and, since both runs set the same per-version
   `ZIKARON_CACHE_SUFFIX`, the same `COVERAGE_FILE` (`check.sh:31–32`), so the coverage half of the
   sentence is right and the venv half is not; and on a *cold* tree it is worse than stated, since
   `! -f "$stamp"` on a venv the first run is still installing into runs `rm -rf` under a live `pip
   install` (`:275–277`). Nothing locks the script against a concurrent self. **Fix**: *"— the same
   three virtualenvs and the same three coverage files, so two runs' fragments merge into one
   report (and on a cold tree the second run deletes the venv the first is still installing into)"*.
   The deterrent is right; the mechanism it cites is the corpus's "measured reasons" rule and should
   be the true one.

3. **[NITPICK] The rewritten §"Distribution" paragraph carries a second universal that round 12's own
   findings do not fit.** `FINDINGS.md:840–842`: *"Every other finding in rounds 7–12 was corpus
   consistency in prose that the *previous round's own fix* had disturbed"*. Round 12's findings 1
   and 2 were fresh prose written *after* round 11 — a false universal and an incomplete list in
   paragraphs no earlier fix had touched — not neighbours a fix disturbed; findings 3 and 4 were of
   that class, so *"produced a finding in six consecutive rounds"* stands. **Fix**: *"Every other
   finding in rounds 7–11 was …"* — the count sentence after it needs no change. Raised only because
   the sentence sits four lines above a strikethrough of the previous universal in the same
   paragraph, and the paragraph is the corpus's own evidence about review cost.

4. **[NITPICK] `check-matrix.sh:235–236` attributes the SQLite pair to a build that was never
   measured, and keeps the pre-F3 mechanism in one verb.** *"so a distribution 3.13 and a downloaded
   one ship different SQLite versions (3.45.1 against 3.53.1, measured here)"*. The measured pair is
   the host's distribution **3.12.3** against the downloaded 3.13/3.14 builds
   (`research/python-portability-probes.md:73–75`, `FINDINGS.md:894–895`, `schema.md:8`); no
   distribution 3.13 appears anywhere in the corpus, and on this machine a distribution 3.13 would
   load the same `libsqlite3.so` as the 3.12 does. And *"ship"* is the sentence the limit paragraph
   at `:249–253` corrects fifteen lines later — a distribution build ships no SQLite. This is the
   one site the by-meaning half of rubric (b) turns up: F3 changed the noun at `:234` and left the
   verb and the attribution beside it. **Fix**: *"so a distribution build and a downloaded one can
   link different SQLite versions (this machine's `/usr/bin/python3.12` at 3.45.1 against its
   downloaded 3.13 at 3.53.1)"*. The argument the paragraph makes — two 3.13s can be two machines —
   is unaffected.

5. **[NITPICK, optional] `FINDINGS.md:896` — "Pinning a statically-linked interpreter is the only
   fix" is one more universal, and it is not quite true.** A vendored library — a `pysqlite3`-style
   wheel carrying its own statically-linked SQLite, reached through a `sys.modules["sqlite3"]` shim
   since `aiosqlite` imports the stdlib module by name — pins SQLite without pinning the
   interpreter. It is outside M27's fence (*"No SQLite pinning"*) and I am not proposing it; but the
   sentence feeds §"Still open: how Zikaron is obtained", where "only" would over-weight the managed-
   interpreter route. *"the only fix short of vendoring the library itself"* keeps the claim true.

### Verified and not re-raised

**(a) The round-12 fixes, each against the tree.** F1: `FINDINGS.md:835–848` — the correction is
stated first (*"Rounds 7–9 and 11 found nothing behavioural; round 10 found one gap …"*), the struck
universal follows in an italic note with the date and the mechanism, and its account of round 10
matches the archive entry (`FINDINGS-archive.md:3242–3247`, *"that fourth"*) and item (d) at
`:947–955`, which already said *"wrong twice"*. `:1509–1511` reads *"one behavioural gap and otherwise
prose … most of five rounds"*. F2: the phase line at `:86–101` names round 12's outcome, the two
non-M27 files, and *"Every edit after round 11 is prose or a comment"*, which is true of the list in
the brief; the *"died before writing"* clause survives only at `:1503–1505`, of the first attempt, and
`:1512` (*"The retry … was worth its spawn"*) resolves which attempt is round 12. The count sites
agree: *"APPROVED at code-review round 11"* (`:88–89`), *"eleven rounds, with a twelfth confirming"*
(`:832–833`), *"those twelve rounds"* (`:835`). F3: `check-matrix.sh:234`, `FINDINGS.md:894`/`:896–899`
/`:954`, `build-plan.md:2136`/`:2423–2426` — and the remedy sentences that reasoned from the old
mechanism now say *statically-linked*, with the reason beside each. By meaning: `FINDINGS.md:923`,
`:1182` and `build-plan.md:1960` (*"pin SQLite for free"*) hold because a uv-managed interpreter is a
python-build-standalone build; `schema.md:5–13` says *"bundled with the interpreter rather than chosen
here"* and *"a function of the linked library"*; `log.py:43–47` says *"bundled"* and *"linked"*. No
`compiled into` survives outside `reviews/` except an unrelated experiment fixture. F4: `:1508`
*"observed twice"*; the comment block `check-matrix.sh:233–274` has no mid-paragraph line under 70
characters; and `:268–269` joined is byte-identical to `FINDINGS.md:1168–1170` inside the quotation
marks. **The script's behaviour is untouched**: `minors=(...)` at `:39` is what
`tests/test_check_gate.py:34` parses and nothing in `tests/` reads a comment or a message from this
script; the rebuild condition, label check, stamp write, token search and both identity samples are
what round 12 read.

**(c) `SKILL.md:25`.** The YAML claim is correct by the spec and not only by the one run: in block
context a plain scalar ends at `: `, so `description: Dumb command/test runner: executes…` is a
second mapping indicator inside a value and PyYAML's scanner reports *"mapping values are not allowed
here"*. The inference — the harness parsed a file a YAML library rejects, so the prescribed check can
fail on a working file — follows, and the replacement (`name` and `description` present; spawn it)
is the test that was actually run. **Assumption stated**: I cannot run `git` from this seat, so I
take *"a malformed file is simply absent from `/agents` rather than reported as an error"* as text
that predates this edit, since the brief does not list it as new. **Noted, not raised**: the same
step 5 caps the loop at *"3 iterations"*, which this trail and M18's have exceeded by an order of
magnitude on operator direction; pre-existing, not what this round changed, and a decision for the
operator rather than a finding.

**py-runner otherwise.** The rule at `:51–62` names the observed behaviour (backgrounding and
returning), the step-3 clause at `:47` makes such a message a failed call in the one place the agent
composes its return value, and the two agree with the timeout paragraph at `:68–80`. The measured
consequences that are measured — no result, and the caller reading logs — are accurate; finding 2 is
about the counterfactual only.

**Forward note, not a finding on this tree.** The round count is now stated at three sites
(`FINDINGS.md:88–94`, `:832–835`, and §Harness's *"rounds 7–11"* at `:1509`), and this round makes
the first two stale by one whatever its verdict; the third stays true as a statement about the
outage.

VERDICT: NEEDS_CHANGES

## Round 14 — 2026-09-21

### Summary judgment

All five round-13 fixes are in the tree as described and each is correct on its own terms: the
`py-runner.md` rule and its aside now say one thing about a long-running command from three places
(`:47`, `:51–64`, `:69`) with nothing left in the file pulling the other way; the concurrent-gate
mechanism matches what `check-matrix.sh:275–277` and `:303–306` actually do; the SQLite pair is the
measured one; the escape clause is fenced; and no site outside `reviews/` carries a total for this
trail any more. Nothing in code, tests or gate behaviour has changed since round 11. What remains is
one paragraph — the tail of §"Distribution"'s account of the trail — where the F3 insertion broke a
pronoun's antecedent, misdescribes round 13, and sits beside a count that is now one short partly on
my own round-13 instruction; and one optional sibling of F5 in `build-plan.md`. Both are prose about
the review's own history with no behavioural implication, and the replacement text is supplied so
they can be applied without another round. Tree identity as reported in the brief:
`51d0105+832e824fafa0`; this append voids it, per §9.

### Findings

1. **[NITPICK] `FINDINGS.md:840–846` — the F3 insertion disturbed its neighbour, and the
   parenthetical it added is wrong about round 13.** Three defects in one spot, one edit to fix.
   *(i) The antecedent.* Before F3 the paragraph read *"…that class produced a finding in six
   consecutive rounds. Two of them were errors the reviewer had introduced"* — "them" being the
   cascade findings (round 7 F2's "seven", round 8 F2's "three paragraphs"). The parenthetical about
   rounds 12 and 13 now sits between the two sentences, so "Two of them" reads as two of *those*
   rounds' findings, which is false of both. This is rubric (a)'s question answered "yes" for one
   site.
   *(ii) Round 13.* *"their leading findings were in prose written fresh after the last approval —
   a false universal, an incomplete list — which no earlier fix had disturbed. Prose written to
   summarise a review…"* is exact for round 12 (F1 and F2, both fresh prose in this file) and does
   not describe round 13. Round 13's leading finding was a rule added to `py-runner.md` sitting six
   lines above an older, **untouched** sentence that had licensed the very defect the rule names —
   the neighbour class, in a file no review had read, and not summary prose; round 13 said so
   (*"It is the neighbour class"*). Both examples in the parenthetical are round 12's.
   *(iii) The count.* *"six consecutive rounds"* was true through round 12 and is now seven: round
   13's findings 3 and 4 were cascades from round 12's own fixes (the `7–12` universal that fix
   wrote; the verb and attribution left beside the noun that fix changed). I wrote *"the count
   sentence after it needs no change"* in the same round whose findings extended it — the
   reviewer-introduced-error class the paragraph records, third instance. And this finding is
   itself the class: the parenthetical was round 13's fix, and it is defective. **So any
   "consecutive" cardinal drifts while the trail is open**; state a closed interval, which stays
   true whatever a later round finds. Rubric (b)'s residue is this one number.
   **Fix, replacing `:840–846` from *"Every other finding"* through *"re-deriving."***: *"Every
   other finding in rounds 7–11 was corpus consistency in prose that the* previous round's own fix
   *had disturbed; two of those were errors the reviewer had introduced and I had copied without
   re-deriving. That class produced a finding in every round from 7 through 13, the later ones
   cascading from the previous round's corrections to this very paragraph. *(Round 12 added a shape
   the cascade does not cover: its leading findings were in prose written **fresh** after round
   11's approval — a false universal, an incomplete list — which no earlier fix had disturbed.
   Round 13's was different again: a rule added to `py-runner.md` sat six lines above an older,
   untouched sentence that had licensed the very defect the rule names — the neighbour class, in a
   file no review had read. Prose written to summarise a review is as defect-prone as prose edited
   during one.)*"* — "through 14" if this finding is counted, which it should be; either way no
   bare cardinal and no "consecutive".

2. **[NITPICK, optional] `design/build-plan.md:2423` is F5's sibling and still says "means".**
   *"pinning the library means pinning a statically-linked interpreter, which is the packaging
   milestone this one deliberately is not"*. `FINDINGS.md:899–906` now records that a vendored
   `pysqlite3`-style wheel pins the library without pinning the interpreter, so "means" is one
   route stated as the only one — the two-sites shape of a fix I tagged optional, which is why this
   is optional too. The fence's conclusion is unaffected, since a vendored wheel is also packaging.
   **Fix**: *"pinning the library means pinning a statically-linked interpreter or vendoring the
   library, either of which is the packaging milestone this one deliberately is not"*.

### Verified and not re-raised

**(a) Each fix against the tree.** F1: `py-runner.md:69` is the two-case form with the aside, and
the aside's quotation is the sentence round 13 quoted. Its neighbours agree: `:47` makes a pending
report a failed call, `:51–64` is the foreground-plus-maximum-timeout rule the new line points back
to, `:63–64` covers the cannot-finish case, and `:70–82`'s matrix bullet names the same timeout and
says an install is *"expected, not a hang"*. Nothing else in the file licenses an early return.
`.kiro/agents/py-runner.json:5` still carries the old sentence; `CLAUDE.md` puts `.kiro/` out of
bounds, so not raised. F2: `:56–60` — on a warm tree a second run hits `-d` true and every other
disjunct at `:275` false, so no venv is touched and both runs share `.venv-matrix/<minor>` and, via
the same `ZIKARON_CACHE_SUFFIX`, one `COVERAGE_FILE` per version; on a cold tree `! -f "$stamp"`
(or `! -x bin/python` during the first run's `-m venv`) is true and `:277` removes the directory.
The wording matches. F3: `:840` reads *"rounds 7–11"*; the residue is finding 1. F4:
`check-matrix.sh:233–236` — verified against `research/python-portability-probes.md:73–75` (host
`/usr/bin/python3` = 3.12.3 at 3.45.1; uv-managed 3.13.15 at 3.53.1), and `/usr/bin/python3.12` is
the name `:241` already uses for the same binary. "Two 3.13 builds" followed by a 3.12-vs-3.13
example is the analogy round 13 proposed and is labelled as what was measured. F5: `:899–906`, with
the fence and the shim named, and *"so 'only' does not over-weight"* pointing at §"Still open".

**(b) Round totals, swept by grep outside `reviews/`.** `FINDINGS.md:88–97` and `:831–834` both
state *round 11* as the fixed fact; `:95–97` names `grep -c` as the count; `:1515` *"eleven
headers, eleven `VERDICT:` lines"* is true of the outage; `:900`/`:903`, `build-plan.md:2134`/
`:2424` and `FINDINGS-archive.md:3244` cite specific rounds; the archive's References entry
(`:3236–3253`) carries no total; `CLAUDE.md` and `SKILL.md` carry none. The only number that moves
with the count is `:842`'s "six", finding 1(iii). `build-plan.md:2158`'s *"after three review
rounds"* dates when the handler landed and does not drift.

**(c)** Answered in finding 1(ii): accurate for round 12, not for round 13.

**(d) The cleanup and the script.** `:268–269` joined is byte-identical to `FINDINGS.md:1175–1177`
inside the quotation marks. The comment block `:233–274` has no mid-paragraph line under 70
characters (`:267`, 76 characters, ends a sentence before `:268` begins one). Every non-comment line
between `:226` and `:310` — the stamp derivation, the rebuild condition, the label check, the
install-then-stamp — is what round 13 read. **Observation, not a finding**: `py-runner.md:71–73`
*"a run killed at that default leaves three gates running"* predates the handler's
environment-token fix and whether the Bash tool's timeout delivers a trappable signal or `KILL` is
unmeasured from this seat; if it is now false the only consequence is over-caution. **Assumption
stated**: I cannot run `git` here; the identity in the brief is the researcher's measurement, and
"nothing else changed" was answered against the brief's change list.

VERDICT: APPROVED

## Round 15 — 2026-09-21

### Summary judgment

Both round-14 fixes are in the tree as described and the rewritten paragraph is right on the three
things round 14 asked for: the "two of those" clause is back beside the sentence that gives it its
antecedent, the parenthetical now describes round 12 and round 13 as two different shapes and gets
each one's shape right, and the closed interval *"every round from 7 through 14"* is true and stays
true whatever this round finds. No site outside `reviews/` carries a drifting total any more. Nothing
in code, tests or gate behaviour has changed since round 11. One clause in the parenthetical is false
by this trail's own record — and it is the fourth instance of the reviewer-introduced-error class the
paragraph names, because I supplied it in round 14 and it was copied without re-deriving. It is a
one-clause strike with no behavioural weight; apply it and do not spend a round on it. **This is the
stop signal the brief asked for**: the artefact is done, and what remains is prose about the review's
own history correcting prose about the review's own history. Tree identity as reported in the brief:
`51d0105+2966dd138595`; this append voids it, per §9.

### Findings

1. **[NITPICK] `FINDINGS.md:847–849` — "the neighbour class, in a file no review had read" is false,
   and the falsehood is mine.** Rounds 1, 2, 3, 4, 5 and 8 of this trail cite `py-runner.md` — round
   1 finding 11 at `.claude/agents/py-runner.md:54–59` (`reviews/…:170`), round 2's proposed edit at
   `:56` (`:375–379`), round 3 at `:57` (`:573`, `:621`), round 4 finding 6 at `:55` (`:797–803`),
   round 5's F6 verification at `:55–57` (`:1037`), round 8 at `:43–44` (`:1496`). What no round
   before 13 had *quoted* is the licensing sentence itself — `grep 'looks long-running' reviews/`
   returns only round 13 and later — but a file read for its matrix bullet by six rounds is not "a file
   no review had read". Round 13 did not say this; it said *"in a prompt read by a low-effort model"*
   (`:2006`). The clause first appears in round 14's supplied replacement (`:2163`), which the
   researcher copied as instructed. That is the class at `:841–842` (*"errors the reviewer had
   introduced and I had copied without re-deriving"*), and the paragraph's own counter at `:863–864`
   applies to a clause as much as to a number. **Fix, `:847–849`**, replacing *"sat six lines above an
   older, untouched sentence that had licensed the very defect the rule names — the neighbour class, in
   a file no review had read."* with *"sat a few lines above an older, untouched sentence that had
   licensed the very defect the rule names — the neighbour class, in a file six earlier rounds had
   read for its matrix bullet, before there was a rule for that sentence to contradict."* The line
   count goes with it: it was my round-13 figure, the file has moved since, and a stale line offset is
   the thing `FINDINGS.md:966–967` already records dropping twice. If the sharper clause is not wanted,
   end the sentence at *"the neighbour class."* — either form is true; the current one is not.
   **Verifiable without a round**: `grep -n 'py-runner' reviews/m27-python-range-code-review.md` is
   the whole check.

### Rubric answers, verified and not raised

**(a) The paragraph, read against the record rather than against round 14's summary of it.**
*Antecedent*: `:840–842` now runs *"Every other finding in rounds 7–11 was corpus consistency in
prose that the previous round's own fix had disturbed; two of those were errors the reviewer had
introduced"* — "those" resolves to the rounds-7–11 cascade findings, which is round 7 F2's "seven" and
round 8 F2's "three paragraphs" (round 12 finding 1, `:1902–1905`). Correct. *Round 12*: *"leading
findings were in prose written fresh after round 11's approval — a false universal, an incomplete
list"* matches round 12's F1 (`:1886–1914`, the `7–11` universal) and F2 (`:1916–1930`, the
five-of-seven list); its F3 and F4 were the cascade class, which is what keeps 12 inside the interval.
Correct. *Round 13*: a rule added to `py-runner.md` above an untouched older sentence that licensed
the defect — matches round 13 finding 1 (`:1998–2012`) except for the clause in finding 1 above; its
F3 and F4 (`:2029–2051`) were cascades from round 12's own fixes, which keeps 13 inside the interval.
*Round 14*: finding 1 was a cascade from round 13's F3 insertion, so *"through 14"* holds; and if
finding 1 above is counted, the class reaches 15 without the sentence becoming false — which is the
point `:851–853` makes, and it survives its own example. *The added sentence*: *"written as 'six' at
round 13"* — the "six" was written in the fix pass round 13 reviewed (round 12's fix text said *"all
five"*, `:1910`; the researcher wrote six consecutive, counting 7–12), round 13 endorsed it (*"needs
no change"*, `:2035`), and round 13's own F3/F4 made it seven. Loose on "at", true on substance; not
raised. *Neighbours*: `:835–839` (rounds 1–6, round 10's gap and drift) and `:854–864` (the struck
universal, the transferable part) are byte-for-byte what round 14 read; `:865` follows as before.

**(b) Tallies, swept by grep outside `reviews/` for `round 1[2-5]`, `consecutive`, `eleven`,
`twelfth`–`fifteen`.** `FINDINGS.md:88–97` and `:831–834` state round 11 as the fixed fact and `:95–97`
delegates the count to `grep -c`; `:842–843` is the closed interval; `:1517–1528` names round 12's
retry and *"eleven headers, eleven `VERDICT:` lines"* as what the outage left, which stays true;
`:907`/`:910` and `build-plan.md:2425`/`:2427` cite specific rounds. `FINDINGS-archive.md:3751`'s
*"Rounds 13–14"* is M9's trail, not this one. No cardinal for this trail's length exists outside
`reviews/`.

**(c) The two deferrals, both defensible as stated.** *`.kiro/agents/py-runner.json:5`*: `CLAUDE.md`
§Harness fences `.kiro/` as the reference for what ships, the operator has been told the shipped
prompt carries the pre-fix sentence, and the decision is his. Agreed. *`py-runner.md:72` "leaves three
gates running"*: over-caution in the safe direction, since the only behaviour it produces is passing
the maximum timeout, which is wanted regardless. Agreed, with one correction to the reason given for
not measuring: the instrument is not a deliberately timed-out matrix run. A ten-line probe — a script
that traps `TERM`/`INT`, records which arrived to a file, and `wait`s on a backgrounded `sleep` —
run under the Bash tool with a short `timeout` answers whether the tool's timeout delivers a
trappable signal, to the process or its group, or `KILL`, in seconds and with no orphan risk. Not
asked for; recorded so the cost is not overstated if anyone does want it.

**(d) The rest of the M27 artefacts.** `build-plan.md:2422–2427` reads correctly after the rewrap:
*"pinning a statically-linked interpreter or vendoring the library, either of which is the packaging
milestone this one deliberately is not"* keeps the fence's conclusion, and the parenthetical's two
attributions are both about when *that sentence* was edited (adjective at round 12, alternative at
round 14). **Observation, not raised**: `FINDINGS.md:909–910` says *"The escape clause is round
13's"* of the same idea — also true of *that* site, since round 13's F5 originated it and round 14's
F2 carried it to the brief. A reader cross-reading the two sees 13 and 14 for one idea; each is
locally correct under its own frame, so I am not asking for an edit, only noting that "is round N's"
is doing two jobs. Nothing in `check-matrix.sh`, `asyncio_compat.py`, `server.py`, `log.py`, the
tests or `schema.md` is in the brief's change list, and round 14 read all of them against the tree;
the brief's identity and its all-green sweep are the researcher's measurement. **Assumption stated**:
I cannot run `git` from this seat; "nothing else changed" was answered against the brief's change
list.

**Plainly, as the brief asked.** Nothing material remains. Finding 1 is a true defect and it is the
species the brief predicted — a wording defect in the paragraph about wording defects, introduced by
the reviewer, in a file the researcher had no reason to distrust. Applying it takes one edit and
verifying it takes one grep; neither needs a round 16, and spawning one would be the pattern
`FINDINGS.md:859–861` describes rather than a check on the product.

VERDICT: APPROVED
