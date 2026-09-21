# Review: `design/build-plan.md` §M27 — Widen the supported Python range, behind a version seam

Artifact: `/home/nathan/Zikaron/design/build-plan.md`, lines 1938–2057 (§M27), read with §M26 above and
§"Standing notes" below, against `research/python-portability-probes.md`,
`research/python-313-314-porting-audit.md`, `research/python-distribution-portability.md`,
`FINDINGS.md` §"Open: distribution, and a version cap that was hiding a defect", and the code the brief
makes claims about.

## Round 1 — 2026-09-20

### Summary judgment

The brief is factually sound where it counts — every number I could check against the tree checks out
(18 PEP 695 sites across 10 modules; `server.py:322` and `:405`; 14 policy sites, all in
`tests/test_service_main.py`; the seven `not sock_path.exists()` asserts it lists; 3.45.1 vs 3.53.1;
README:65/84; CLAUDE.md:52), and the design argument (seam-as-data, `cleanup_socket=False`, matrix
separate from the inner loop) is coherent and well-reasoned. It is **not yet executable without judgement
calls**: the `check-matrix.sh` contract is undefined and collides with `check.sh`'s hard-coded venv; the
§6 text the milestone is to write is delegated rather than stated; the seam's behaviour on a minor it has
no row for is unspecified while `>=3.12` admits exactly that; one label ("P2") exists only in a
conversation; and the done-when enumerates two of the five sites that state the definition of done, while
missing a test comment that names the pin as the reason an assertion holds. Those are the operator's
stated blocker class. Fix them and this is a one-more-round brief.

### Findings

1. **[BLOCKER] `check-matrix.sh` has no contract, and the one thing it must do collides with `check.sh`
   "staying as it is".** (`build-plan.md:1994–2001`, `:2008–2014`, done-when 7.) `check.sh:13` hard-codes
   `venv=.venv/bin`, so the matrix cannot "run the full gate" on three interpreters without either (a)
   parameterising `check.sh` — which the brief says stays as it is — or (b) duplicating the four commands,
   which puts the `--cov` package list in two scripts while `tests/test_check_gate.py:26,42` polices only
   `check.sh`, the exact two-sites failure this corpus keeps recording. The brief also leaves open: how
   interpreters are "named" (positional args? env var? default `python3.1X` on `PATH`?), where the three
   venvs live and whether they persist between runs, that `.gitignore:25–26` covers only `.venv/` and
   `venv/` so a new location needs an entry, how dev dependencies get into each venv, and how
   `-W error::DeprecationWarning` reaches pytest. A fresh session makes five decisions here.
   **Suggested edit** — state a contract, for example: `check.sh:13` becomes
   `venv="${ZIKARON_VENV:-.venv}/bin"` (default behaviour byte-identical, so "stays as it is" holds in the
   sense that matters); `check-matrix.sh` iterates `3.12 3.13 3.14`, resolves each interpreter as
   `python3.<minor>` on `PATH` unless `ZIKARON_MATRIX_PYTHONS` overrides (uv's `python install` puts such
   shims on `PATH`, which is how "names interpreters" and "uv in practice" reconcile), creates
   `.venv-matrix/<minor>` with `-m venv` + `pip install -e '.[dev]'` if absent (exact pins make reuse
   safe; `-e` keeps package code live), adds `.venv-matrix/` to `.gitignore`, and runs
   `ZIKARON_VENV=.venv-matrix/<minor> PYTEST_ADDOPTS='-W error::DeprecationWarning' ./check.sh` — pytest
   reads `PYTEST_ADDOPTS` natively, so no second copy of the gate exists and `test_check_gate.py` keeps
   covering the only one. Then add to done-when: a test in the `test_check_gate.py` pattern asserting the
   minors named in `check-matrix.sh` equal the set §6 states (coding-standards §2: a table stated in the
   design gets one declarative copy and a drift test).

2. **[BLOCKER] The §6 text is the milestone's normative output and the brief does not say what it
   says; in particular, "supported" is undefined and the seam's behaviour on an unlisted minor is
   unspecified.** (`build-plan.md:1940–1941` "§6 gains the supported range and the seam rule, and this
   milestone writes it"; done-when 4 "on every supported version".) `>=3.12` with no cap means pip will
   install on 3.15 the day it ships. The seam holds rows for 3.12 and 3.13+; a mapping keyed on
   `sys.version_info[:2]` raises `KeyError` on 3.15, an open-ended `>=3.13` row silently assumes the
   private attribute survives, and a startup refusal is a cap by another name. Each is defensible; the
   brief must choose, because the choice decides what `attached_connection_count` does in a user's
   service on the first untested minor. **Suggested edit** — give §6 its propositions in the brief:
   (i) floor `3.12` (PEP 695, 18 sites/10 modules), no cap (`python-distribution-portability.md` §4);
   (ii) **tested** = the minors `check-matrix.sh` runs, today 3.12/3.13/3.14, and "supported" means
   tested; (iii) every stdlib difference between tested minors lives in
   `zikaron/service/asyncio_compat.py` as one row per minor, nothing else in `zikaron/` reads
   `sys.version_info`, and a difference in a module other than `asyncio` is a recorded decision to widen
   the seam, not a second module; (iv) a minor newer than the matrix is installable and untested — the
   seam applies its newest row, so a further private-API move fails loudly at the first shutdown rather
   than being masked, and adding the minor to the matrix is what makes it supported (recommended over a
   runtime refusal, which reintroduces the cap this milestone removes); (v) deprecations are errors in
   the matrix only, with the dependency-release reason. Done-when 4 then reads "on every minor the matrix
   runs".

3. **[BLOCKER] "P2" is a label from a conversation.** (`build-plan.md:2053`, and the identical sentence
   at `FINDINGS.md:887`.) It is defined nowhere in the corpus — not in either research note, not in
   FINDINGS — so the one cell the fence records as debt cannot be read cold. From the code, the cell it
   plausibly names is `main.py:341–360`: the `except BaseException` path calls `shut_down()` *before* its
   unlink at `:360`, so between `server.close()` and that unlink the socket exists and refuses, a client
   takes `hook/connect.py:238`'s vet-and-unlink and spawns a successor, and the old process's unguarded
   `:360` then unlinks the successor's socket — the "our four unlink sites have no inode guard" hazard of
   `python-portability-probes.md` §5b item 3. **Suggested edit** — replace "P2 on 3.12 leaves…" with a
   description in those terms (path, lines, actors), and if the cell is a different one, describe that
   one. Fix `FINDINGS.md:887` in the same pass.

4. **[BLOCKER] Done-when 8 names two of the five sites that state the definition of done, and the
   paragraph directly beneath the CLAUDE.md line it edits becomes false by omission.** The brief's own
   rule at `:2003–2005` is that a silently incomplete rule is worse than an inconvenient one. Sites:
   `CLAUDE.md:52` (named), `README.md:459` ("`./check.sh` is the definition of done" — a different line
   from the two README lines the brief names), `.claude/agents/memory-researcher.md:42` (same sentence,
   in the crew file that runs every session), and `design/coding-standards.md:321–328` §9, which opens
   "One command runs everything" and prints a command line — and which the brief lists nowhere despite
   §9 defining the gate. Then `CLAUDE.md:57–62`, "It is hermetic… Nothing is covered only there": after
   M27 the 3.13/3.14 rows are exercised only in the matrix, which needs three interpreters — machine
   state, exactly what that paragraph says the gate does not depend on. **Suggested edit** — done-when 8
   enumerates all four prose sites; add one sentence to the CLAUDE.md hermetic paragraph saying the
   matrix is the deliberate exception (what it needs, what it alone covers, and that `check.sh` remains
   hermetic); §9 gains a sentence naming `check-matrix.sh`, when it runs, and what it adds. Grep the
   *claim* ("definition of done"), not the filename, when sweeping.

5. **[BLOCKER] `tests/test_service_main.py:555–558` states the pin as the reason an assertion holds,
   and the brief cites the line beneath it without listing it.** The comment reads: *"`asyncio.Server.
   close()` does not remove a Unix socket's path on the pinned 3.12.3 — from 3.13 `create_unix_server`
   defaults to `cleanup_socket=True` … `pyproject.toml` pins `==3.12.*`, so the guard holds as long as
   that pin does."* The corpus already knew about the 3.13 default, in a test comment, before the probe
   found it — worth a line in the brief's narrative — but the actionable point is that this sentence is
   false the moment done-when 1 lands, the assertion at `:559` keeps passing on every minor (because of
   `cleanup_socket=False`), and nothing in the done-when sends the executor to those four lines. This is
   the exact shape CLAUDE.md's M23 note describes: a conclusion that followed from the old proposition,
   sharing no words with the edit. **Suggested edit** — a done-when item: that comment is rewritten to
   say the seam's `cleanup_socket=False` is what keeps `:559` distinguishing `run()`'s unlink from
   asyncio's, on every minor.

6. **[IMPROVEMENT] Name the second seam function and give both of its values.** (`:1966–1967` "Two
   functions: `attached_connection_count(server)`, and the keyword arguments…"; done-when 2 "the two
   normalizers".) `FINDINGS.md:880` already names it `unix_server_kwargs()` but writes its value as
   `{"cleanup_socket": False}` unconditionally — which is the `TypeError` on 3.12 the brief itself
   warns about at `:1978`. Carry the name into the brief and state the rows explicitly: `{}` on 3.12,
   `{"cleanup_socket": False}` on 3.13+. Also resolve "two functions" against "as data": say the shape
   (a table keyed on `(major, minor)` consulted by the two functions), since "data" is what finding 7
   below depends on.

7. **[IMPROVEMENT] The mechanical reason for "as data" is missing, and it constrains how the seam may
   be written.** `pyproject.toml:128` fixes `python_version = "3.12"` for mypy. mypy evaluates
   `sys.version_info` comparisons against that value during semantic analysis and marks the losing
   block unreachable *intentionally* — `checker.py`'s `visit_block` skips such blocks without a
   `warn_unreachable` report — so an `if sys.version_info >= (3, 13):` seam leaves the 3.13+ row
   **un-typechecked on all three matrix interpreters**, and an unused `type: ignore` inside it would go
   unreported too. A table keyed on `sys.version_info[:2]` is checked on both rows. State this at
   `:1962` as the reason, and instruct: no version *branches* in the seam either. Add, for the same
   executor, that `[tool.ruff] target-version = "py312"` and mypy's `python_version` stay at the floor.

8. **[IMPROVEMENT] Done-when 2's precedent cannot detect the thing done-when 2 asserts, and the guard's
   spellings and scope are unstated.** `tests/test_hook_stdlib_only.py` works by diffing `sys.modules`
   in a subprocess — it sees *imports*, and `sys.version_info` is an attribute read on a module every
   file already imports. The mechanism has to be a source scan in `tests/test_check_gate.py`'s style
   (regex over `zikaron/**/*.py` with the seam allowlisted). Say so, and state: the spellings covered
   (`sys.version_info`, `sys.hexversion`, `sys.version`, `platform.python_version`,
   `from sys import version_info`), whether `tests/` is in scope, and — because done-when 9 will want the
   interpreter version in the same log line (see finding 12) — which spelling the log may use or that it
   goes through the seam. Extend the same scan to `_active_count` and `_clients` outside the seam,
   covering `tests/`: `tests/test_service_server.py:148` reads `bare_server._active_count` directly today
   and is one of that file's three 3.13 failures; the porting audit (§2, "treat every one of those
   reaches as a landmine") asks for exactly this guard.

9. **[IMPROVEMENT] Name the mutation oracle for done-when 3, and record the `-W error` measurement so
   done-when 7 is known achievable.** `tests/test_service_server.py:89`
   `test_shut_down_survives_a_connection_accepted_but_not_yet_self_registered` is precisely the test
   that fails if `attached_connection_count` is mutated to `len(running._connections)` — the brief can
   name it rather than leave "verified by mutation" to be designed. And `FINDINGS.md:862–864` records
   that a `-W error::DeprecationWarning` run on 3.14 surfaced *only* the 14 sites; the brief's
   `:1999` implies it without saying the run was otherwise clean or that the filter was all-origins.
   State both, so the executor knows a third-party deprecation on 3.12/3.13 (not measured) is the one
   way done-when 7 can still surprise.

10. **[IMPROVEMENT] Done-when 6 does not say what replaces the 14 sites.** All 14 are inside
    `async def test_…` functions (`test_service_main.py:213, 399, 467, 628, 835, 894`), so a running loop
    exists at each and `type(asyncio.get_running_loop())` is the drop-in for
    `asyncio.get_event_loop_policy().get_event_loop().__class__`. Name it; the alternatives
    (`asyncio.SelectorEventLoop`, `DefaultEventLoopPolicy`) are respectively platform-shaped and
    themselves deprecated.

11. **[IMPROVEMENT] `FINDINGS.md:884` contradicts the brief's deprecation decision, and `:817`
    contradicts `:877`.** FINDINGS says the plan is *"`filterwarnings = error` so the next wave is not
    silent too"* — a `pyproject.toml` setting that would redden `check.sh`, the outcome the brief's
    `:1996–1999` exists to avoid. And `:817` "**Nothing is decided.**" sits sixty lines above `:877`
    "Decisions taken with the operator". Outside the artifact, but the always-loaded neighbour of it;
    fix both when the brief lands.

12. **[IMPROVEMENT] `design/architecture.md` is named as owning the shutdown path and receives no
    edit, so the decision lives only in a docstring.** `architecture.md:715–716` says "On exit the
    socket is unlinked before the process ends" and nothing in the design says the listener is opened
    with `cleanup_socket=False` or that the unlink is Zikaron's alone on every minor. One sentence there
    ("…by this process alone: the listener is opened with `cleanup_socket=False` through
    `service/asyncio_compat.py`, so asyncio's own 3.13+ unlink-on-close never runs") makes "unlinked
    exactly once" a design statement `main.py:197` cites rather than the reverse. Add it to the
    done-when. Relatedly, done-when 9 should say where the line goes relative to the config dump, its
    text, and that it carries `platform.python_version()` beside `sqlite3.sqlite_version` — the minor is
    the *other* variable this milestone makes vary, and it is what selects the seam row.

13. **[IMPROVEMENT] Sites that reason from the private read or from "pinned", for the done-when.**
    `server.py:256–291` (four docstring paragraphs about reading `_active_count` "directly, once per
    pass" and "`type: ignore[attr-defined]` at every read below" — all false once the seam owns the
    read); `test_service_server.py:92–109` (same reasoning, test side); the phrase "this project's own
    pinned Python 3.12.3" at `server.py:231, 270`, `lifecycle.py:75`, `main.py:326`,
    `test_service_server.py:48` — the measurements stay true, "pinned" does not. And
    `tests/test_service_lifecycle_integration.py:851` is an eighth `not sock_path.exists()` assert
    missing from the brief's list at `:1982–1983`.

14. **[IMPROVEMENT] Two costs the executor will discover rather than read.** (a) Each seam row is
    unexecuted on the other two interpreters, so `show_missing` lists it on every run and the matrix
    runs three coverage measurements against one `fail_under = 95`; say whether that is accepted inside
    the ~2-point margin or excluded with a pragma and a comment. (b) The matrix is three venvs of
    ~200 MB `onnxruntime` each and ≥3 × ~150 s of tests plus first-run installs; state it, since the
    brief is careful to say `uv` arrives "through the back door" and should be equally plain about disk
    and wall-clock.

15. **[NITPICK] Wrong attribution at `:1998–1999`.** "the one thing `CLAUDE.md` says a gate may never
    do" — CLAUDE.md does not say it; `coding-standards.md:231` ("a green run today and a red one
    tomorrow with no change of ours") and `pyproject.toml:204–205` do. Cite those.

16. **[NITPICK] `:2008` "1.44 s per managed interpreter"** — the probe (§4) measured one
    `uv python install 3.12` at 1.44 s, likely cache-warm; say "one measured install".

17. **[NITPICK] Fence `:2046` "no packaging change"** reads against done-when 1, which edits
    `pyproject.toml` metadata. "No change to how Zikaron is obtained" is the sentence meant.

VERDICT: NEEDS_CHANGES

## Round 2 — 2026-09-20

Artifact re-read whole: `design/build-plan.md:1938–2212`, against `FINDINGS.md:813–938`, the probe note
§§4–5b–8, the porting audit, `pyproject.toml`, `check.sh`, `tests/test_check_gate.py`, `.gitignore`,
`coding-standards.md` §§1/6/9, `architecture.md` §"Idle self-stop", `service/log.py`, and every code
line the brief cites.

### Summary judgment

Every round-1 finding is closed as the brief describes, and the new material checks out against the tree
almost everywhere: all 14 `get_event_loop_policy()` sites sit inside `async def test_…` bodies; the ten
`not sock_path.exists()` asserts are exactly the ten in `tests/`; the six `3.12.3` sites in five files
are right; `pyproject.toml` has the `dev` extra, `python_version = "3.12"`, `warn_unreachable`,
`target-version = "py312"`, `show_missing`, `fail_under = 95` and no `filterwarnings`; `check.sh:13`,
`main.py:342/360`, `connect.py:237–238`, `log.py:38–48`, `architecture.md:703/716`,
`coding-standards.md:30` and `:327`, and both research citations say what the brief says they say. The
three corrections to my round 1 are all correct. What remains is one decision the brief still delegates
(when the matrix runs — which three normative sites are told to state), one new factual error in the
debt cell it carefully rewrote, and two neighbour contradictions of exactly the class the brief asked me
to look for — one inside the brief, one in the FINDINGS section that was just edited. All four are
sentence-sized. One more round.

### Findings

1. **[BLOCKER] When `check-matrix.sh` runs is undecided, and three normative edits are instructed to
   say it.** `:2119–2120` "§9's block … gains `check-matrix.sh` — *when it runs* and what it adds";
   `:2179` "All five definition-of-done sites name both scripts"; `:2114–2115` the CLAUDE.md sentence
   naming "what it needs, what it alone covers". Nowhere between `:1938` and `:2212` does the brief say
   when. The question is not cosmetic: if `check.sh` alone stays the definition of done, then after M27
   the 3.13/3.14 rows are verified once, at this milestone, and never again unless someone chooses to —
   which silently voids §6 proposition 2 ("supported means tested") for every later milestone that
   touches `service/`. If the matrix is part of done, the five sites and CLAUDE.md's hermeticity claim
   say something different again. **Suggested edit** — decide it in §"The matrix, and its contract"
   as one sentence and reuse it verbatim at all five sites and in §9: *"`check.sh` is the per-edit
   gate and stays the definition of done for a change; `check-matrix.sh` is additionally required
   before a milestone lands, whenever `pyproject.toml`, `check.sh`, `check-matrix.sh` or
   `zikaron/service/asyncio_compat.py` changes, and when a minor is added to it."* Done-when 9 already
   requires both for this milestone, so the general rule and the specific one agree.

2. **[BLOCKER] The rewritten debt cell misdescribes its own mechanism: `main.py:360` vets nothing.**
   `:2206–2207` "the old process's `:360` unlink — which vets ownership and type but **not inode
   identity**", repeated at `FINDINGS.md:909–910`. `main.py:360` reads `sock_path.unlink(missing_ok=True)`
   — a bare unlink. The ownership-and-type vet is `security.vet_socket_for_unlink`, called at
   `hook/connect.py:237` and `lifecycle.py:429` and by **none** of `main.py:261`, `:360`, `:492` (the
   probe note's own list of the four sites, `python-portability-probes.md:195`; its item 3 at `:183–186`
   describes the vet, not `:360`). The hazard is therefore *worse* than the brief records — the
   successor's socket is removed by an unlink that checks nothing — and a reader sent to `:360` to find
   the vet will not find one. **Suggested edit**, both files: *"…and the old process's `:360` unlink —
   a bare `unlink(missing_ok=True)` with no vet at all, where even the client's `:237` vet checks
   ownership and type but not inode identity, and asyncio's own cleanup checks the inode — can then
   remove the successor's live socket."*

3. **[BLOCKER] `:2008–2010` contradicts done-when 12 and the FINDINGS it describes.** The parenthetical
   says *"`FINDINGS.md` states that value unconditionally, which is wrong on 3.12; … FINDINGS is
   corrected when this lands"*. `FINDINGS.md:891–893` already reads `{}` on 3.12 with a withdrawal
   note, and `:2183–2189` says that fix was made "when this brief landed rather than deferred". This is
   the round-1 fix cascade — finding 6's correction landed in FINDINGS and the sentence that had
   predicted it was not revisited. **Suggested edit** — replace the parenthetical with *"(`FINDINGS.md`
   once stated that value unconditionally and now carries the correction with a withdrawal note.)"* or
   delete it.

4. **[BLOCKER] `FINDINGS.md:848–851` is a fourth contradiction of the same shape as the three fixed,
   in the section I was asked to check.** It still reads *"**Open decision**: pass `cleanup_socket=False`
   … or accept the default. Detail and the perturbation table A owes before any review round"* —
   forty lines above `:889` *"`cleanup_socket=False` is settled"* and `:904` *"Deliberately dropped:
   the shutdown perturbation walk"*. The brief's done-when 12 then states a wrong count ("three
   internal contradictions were fixed"). **Suggested edit** — rewrite `:848–851` as *"Decided below:
   `cleanup_socket=False`; the perturbation table is dropped as a recorded debt. Detail:
   `research/python-portability-probes.md` §5b."*, and make done-when 12 say four. In the same pass,
   `:829` "hiding **one** real defect" against `:915` "hiding **two** defects" is narration that reads as
   a count; one word fixes it.

5. **[IMPROVEMENT] Done-when 3's scan is textual, which the brief does not say out loud, and one
   consequence makes "sole allowlisted file" unsatisfiable as written.** `:2146–2152` names
   `test_check_gate.py`'s mechanism, which is a regex over file text — so comments, docstrings and
   strings count. Then: `tests/test_service_server.py:189` is an assertion *message* naming
   `_active_count`; any rewritten `server.py` docstring that explains the seam by naming the attribute
   fails; and the scanning test itself necessarily contains every spelling it forbids, so it cannot be
   scanned and `asyncio_compat.py` cannot be "the sole allowlisted file". **Suggested edit** — state:
   the scan is textual on purpose (prose that names a private attribute outside the seam is the
   drift being guarded against); the scanner assembles its patterns from fragments so it does not
   match itself; `:189` is reworded; and prose elsewhere says "the private counter" rather than the
   name.

6. **[IMPROVEMENT] Proposition 5's stated reason contradicts §6's own first rule, and it is about to
   become §6 text.** `:1990–1991` "a `fastembed` or `fastmcp` *release* must not redden the local gate
   with nothing of ours changed" — but `coding-standards.md:229–231` pins exactly, so a release cannot
   reach the local gate; only a pin bump can, and that is a change of ours. The reason that survives:
   the local gate runs one interpreter, so a deprecation visible only on a newer minor is invisible
   there anyway, and one visible on 3.12 arrives only through a pin bump — error-on-deprecation belongs
   where the interpreter varies. Write that reason, since it is the one that is true under the rule
   two paragraphs above it.

7. **[IMPROVEMENT] Done-when 11's README half asks for something a command line cannot express.**
   `README.md:84` is `python3.12 -m venv .venv`; "the range in … its install command" (`:2181–2182`)
   leaves the executor to choose the replacement. Decide it: `python3 -m venv .venv`, with the
   Requirements bullet at `:65` reading *"Python 3.12 or newer — 3.12, 3.13 and 3.14 are the tested
   set"*.

8. **[NITPICK] "Four docstring paragraphs" at `server.py:256–291` (`:2131`, done-when 7) is three
   — `:254–267`, `:269–281`, `:283–291` — and the range starts mid-paragraph.** My round-1 finding 13
   introduced the count. Write "three paragraphs, `:254–291`" in both places.

9. **[NITPICK] The mutation as phrased cannot be applied to the function it names.** `:2153–2155`
   and `:2051–2054`: `attached_connection_count(server)` receives an `asyncio.Server` and cannot see
   `running._connections`. The mutation is of the read in `close_all_connections` to
   `len(self._connections)` — or of the seam row to a constant `0`, which the same test also fails on
   (the loop exits without cancelling, `wait_closed()` hangs, `wait_for` times out). Say which.

10. **[NITPICK] `:1979–1980` "no second, looser sense of the word anywhere in the corpus"** — D34 and
    `design/harness.md` use "supported" of harnesses in a sense that has nothing to do with
    `check-matrix.sh`. Scope the sentence to "of a Python version".

11. **[NITPICK] The sweep instruction at `:2108–2109` misses one of its own five and finds a sixth.**
    `build-plan.md:5` writes `definition of "done"` with quotes, so a grep for the bare phrase does
    not return it; and the grep does return `FINDINGS-archive.md:773`, which the archive's rule says
    stays as written. Say both, so the executor neither misses the fifth nor edits the archive.

12. **[NITPICK] `:2127` "Six sites, five files" needs its scope stated** — "in `zikaron/` and
    `tests/`". The same grep returns twenty-odd hits in `research/`, `reviews/`, `experiments/` and
    `design/schema.md:5`, and a verifier has to know those are not in the count.

13. **[NITPICK] Done-when 7's criterion is vacuous for two of the six sites.** `main.py:326` and
    `server.py:270` say "installed", as the brief itself notes at `:2124–2125`, so "no longer claim a
    pin" asks nothing of them. Say what changes there — nothing, since each already names the minor
    it was measured on — so a verifier does not go looking.

14. **[NITPICK] `:2158` "is true again"** — `main.py:197` is true today on 3.12 and false only on
    3.13+ without the seam. "Stays true on every minor, and says the seam is why" is the claim.

15. **[NITPICK] `:1996–1997` presents a paraphrase as a quotation.** CLAUDE.md says "a *harness*
    difference", "stdlib-only", and the two clauses are from different sentences. Quote exactly or
    drop the quotation marks.

16. **[NITPICK] Two keys or three?** `:1981–1982` "one row per minor" reads as `(3,12)`, `(3,13)`,
    `(3,14)`; the table at `:2001–2004` merges "3.13, 3.14" into one column. Either satisfies
    proposition 4, but "one row per minor" makes the seam's key set a third copy of the minor list
    with nothing tying it to the other two — done-when 9's drift test ties `check-matrix.sh` to §6
    only. Say which shape, and if three keys, extend that test to assert the seam's keys equal the
    matrix set.

VERDICT: NEEDS_CHANGES

## Round 3 — 2026-09-20

Artifact re-read whole: `design/build-plan.md:1938–2264`, against `FINDINGS.md:813–943`, the probe note
§§5b and 8, `check.sh`, `tests/test_check_gate.py`, `.gitignore`, `pyproject.toml`, `coding-standards.md`
§§6/9, README `:60–86` and `:455–460`, and every code line the brief cites — plus a fresh `unlink(` grep
over `zikaron/` rather than the probe note's list, which is where finding 3 comes from.

### Summary judgment

All sixteen round-2 fixes landed as the brief describes and the new claims check against the tree: the
five vet-free/vetted unlink attributions are right as far as they go, the six `3.12.3` sites and the
four/two "pinned"/"installed" split are exact, all 14 `get_event_loop_policy()` sites are the ones listed,
the five definition-of-done sites are the five the phrase-grep returns (with `build-plan.md:5`'s quoted
form and `FINDINGS-archive.md:773` correctly called out), `test_check_gate.py` does not touch the `venv=`
line so the `ZIKARON_VENV` change is safe against it, `.gitignore:25–26` is as stated, and no design
document other than `schema.md:5` names a Python version. **The F16 design is consistent**: greatest-key-≤
lookup over `{(3,12), (3,13)}` gives 3.14 and any later minor the `(3,13)` row, which is exactly
proposition 4's "newest row", and done-when 9's refusal to tie the key set to the matrix follows. No
decision is left for a fresh session. What remains is two one-clause cascades of round-2 fixes — one
inside the done-when list, contradicting the item four lines above it, and one in the always-loaded
FINDINGS section — plus an unlink-site count that has now been corrected upward twice and is still short
by two. This should be the last round.

### Findings

1. **[BLOCKER] Done-when 10 still says the allowlist is one file; done-when 3 now says two.** Cascade of
   round-2 F5. `:2217–2218` reads *"The version string is read **through the seam**, so done-when 3's
   allowlist stays one file"*, while `:2189–2190` reads *"the allowlist is `asyncio_compat.py` **plus the
   scanning test**, which is two files, not one."* A verifier of done-when 10 would fail the milestone on
   a sentence the brief itself has already withdrawn. **Suggested edit** — `:2218`: *"…read **through the
   seam**, so done-when 3's allowlist gains no third file — it stays the seam plus the scanner."*

2. **[BLOCKER] `FINDINGS.md:904–905` still gives the reason proposition 5 now says is refuted.** Cascade
   of round-2 F6. It reads *"deprecations as errors in the matrix script only, never in `pyproject.toml`,
   since a `fastembed` release must not redden the local gate"* — the "weaker framing" the brief's
   `:2001–2003` says *"the exact-pinning rule refutes"*. A fresh session reading the always-loaded file
   gets the refuted reason as the live one, which is the brief's own standard for "a defect now, not a
   milestone task" (`:2235–2236`). **Suggested edit** — `:905`: *"…never in `pyproject.toml` — because
   the local gate runs **one** interpreter, so a deprecation raised only on a newer minor is invisible
   there whatever the filter says; error-on-deprecation belongs where the interpreter varies. *An earlier
   revision gave "a `fastembed` release must not redden the gate" as the reason; §6 pins every dependency
   exactly, so no release reaches the gate uninvited and that reason was never true.*"* Done-when 12's
   count of four can stand — this is a FINDINGS-versus-brief disagreement rather than a fifth internal
   one — but say so in the item, or the next reader will count five.

3. **[IMPROVEMENT] The unlink-site count is seven, not five, and the probe note mislabels one row.** The
   researcher's brief said the count moved four → five; both counts were taken from the note's own table
   rather than the tree. `grep -n 'unlink(' zikaron/service zikaron/hook` returns **seven** socket-path
   unlinks: `lifecycle.py:116` (`stop_when_idle`, the idle self-stop) and `lifecycle.py:182`
   (`stop_on_encoder_failure`) are bare `sock_path.unlink(missing_ok=True)` too, and they are precisely the
   *"self-stopping tasks"* `main.py:197` and `:257–260` say unlink before closing. Consequently the probe
   note's row `main.py:261 (self-stop)` (`:189`) is mislabelled — `:261` is the **signal** path
   (`main.py:257–260`: *"A signal exit has no such window to close early, so this path owns the unlink
   instead"*) — and its *"There are **five** unlink sites"* (`:184`) is wrong by two. `FINDINGS.md:848–850`
   (*"`main.py`'s three … and the two that do vet"*) and the brief's fence `:2254–2256` (*"as are
   `main.py`'s other two"*) are each literally true and each read as exhaustive. The hazard analysis does
   not change — both lifecycle unlinks precede `shut_down()`, so neither opens the `:342`/`:360` window —
   but the perturbation debt's own axis is *"which unlink site ran"* (probe note `:204–205`), and an
   under-enumerated axis is the wrong thing to record as a debt. **Suggested edits**: probe note item 3
   → *"seven unlink sites"*, add a row `lifecycle.py:116` (idle self-stop), `:182` (encoder-failure stop)
   under "none", and relabel `:261` "signal path"; brief `:2255` → *"as are the four other bare unlinks —
   `main.py:261` and `:492`, and the two self-stop paths at `lifecycle.py:116` and `:182`"*;
   `FINDINGS.md:848–849` → *"five bare unlinks — `main.py`'s three (`:261`, `:360`, `:492`) and the two
   self-stop paths in `lifecycle.py` (`:116`, `:182`) — and the two that do vet…"*.

4. **[IMPROVEMENT] `check.sh`'s own header is a sixth definition-of-done site and a second hermeticity
   paragraph, in the one file the milestone edits.** `check.sh:2` reads *"The check gate. Nothing is done
   until this exits 0."* — the claim, in words the phrase-grep cannot see, which is the exact
   find-by-meaning case CLAUDE.md's M23 note describes — and `check.sh:38–44` is CLAUDE.md `:57–62`'s
   hermeticity paragraph verbatim (*"Nothing is covered *only* there"*), which the brief calls "false by
   omission" at `:2138–2142` and fixes in CLAUDE.md alone. **Suggested edit** — §"The definition of done is
   stated in five places" becomes six, naming `check.sh:2`; done-when 11's verbatim requirement and the
   hermeticity sentence both land in `check.sh`'s header as well, since a script that says "nothing is
   done until this exits 0" beside a `ZIKARON_VENV` hook it exists to give the matrix should say what the
   matrix is.

5. **[IMPROVEMENT] Proposition 4's "newest row applies" cannot be tested as the brief stands, and the
   seam's own test discipline is unstated.** The rule fires only on a minor the matrix does not run, and
   done-when 3 forbids every test from reading `sys.version_info`, so nothing can exercise the lookup on
   `(3, 15)` today. **Suggested edit** — done-when 2: the lookup takes the version tuple as an explicit
   argument (defaulting to the running one *inside* the seam), and a test asserts with literal tuples
   that `(3,12)→(3,12)`, `(3,13)→(3,13)`, `(3,14)→(3,13)` and `(3,99)→(3,13)` — no version read, no private
   name, no third allowlisted file. In the same item, say what the brief already implies at `:2110–2111`
   but never states: the row *bodies* have no unit test of their own, because a stub naming
   `_active_count`/`_clients` would itself trip the scan, and are verified by the matrix alone through
   done-when 4 and 5. And align proposition 3's *"Nothing else under `zikaron/`"* with done-when 3's
   scope, which covers `tests/` too — as §6 text, proposition 3 is what a reader will believe.

6. **[IMPROVEMENT] `ZIKARON_MATRIX_PYTHONS` has no format and an ambiguous relation to the minor list.**
   `:2082–2084` *"resolving each as `python3.<minor>` on `PATH` unless `ZIKARON_MATRIX_PYTHONS`
   overrides"* — overrides the *paths*, or the *set*? If the set, done-when 9's drift test parses a list
   the environment can silently change. **Suggested edit** — decide it in one clause: the minor list is
   fixed in the script and is what the test parses; `ZIKARON_MATRIX_PYTHONS` is a space-separated list of
   interpreter paths in that order (or, simpler still, one `ZIKARON_PYTHON_3_13=/path` per minor), and it
   can name paths only, never add or drop a minor.

7. **[NITPICK] The tested set will be stated in four places and drift-tested in two.** After M27 the set
   appears in §6, §9's command block, `README.md:65` and `check-matrix.sh`; done-when 9 ties the last to
   the first. `test_check_gate.py` already parses prose by fixed sentence (`_STATED_FLOOR`), so either
   extend the test to `README.md:65`'s sentence, or have §9 and README say "the set `check-matrix.sh`
   runs" without restating it. Either way, state the fixed sentence §6 uses so the prose and the regex
   are written together rather than reconciled after.

8. **[NITPICK] Probe note §8 item 2 (`:267–269`) still lists "Whether to support one Python or a range"
   as open**, twelve lines under §5b's *"Decision, taken 2026-09-20 and briefed"*. One line: decided as
   a range, §5b and §M27.

9. **[NITPICK] State the residual of the unconditional rule.** Not re-flagging the simplification — it is
   the right call for the reason given — but its consequence is unstated: a non-milestone commit to
   `service/` (`89a1e00` is the shape) is never matrix-gated. One sentence in the "When it runs"
   paragraph makes that a chosen gap rather than one the next reader discovers.

VERDICT: NEEDS_CHANGES

## Round 4 — 2026-09-20

Artifact re-read whole: `design/build-plan.md:1938–2298`, against `FINDINGS.md:813–952`, the probe note
§§2/5/5b/8, `check.sh`, `tests/test_check_gate.py`, `.gitignore`, `pyproject.toml`, `coding-standards.md`
§§6/9, `architecture.md` §"Idle self-stop", `service/security.py`, `service/log.py`, README `:61–86` and
`:455–460`, `CLAUDE.md:51–62`, `.claude/agents/memory-researcher.md:42`, `FINDINGS-archive.md:773`, and
every code line the brief cites — plus fresh greps, over the tree rather than any document's table, for
`unlink(`, `3.12.3`, `get_event_loop_policy`, `not sock_path.exists()`, every version-read and
private-attribute spelling done-when 3 names, the definition-of-done claim in all its phrasings
(including `.kiro/`, which has none), and PEP 695 sites.

### Summary judgment

All nine round-3 fixes landed as described, and every enumeration I could re-derive now matches the
tree: seven socket-path unlinks (five bare, `:261` the signal path per `main.py:257–260`, two vetted by
`S_ISSOCK` plus `st_uid` and nothing else — `security.py:145–151`), six definition-of-done sites (the
grep's only other hits are `FINDINGS-archive.md:773` and review files, none edited), ten
`not sock_path.exists()` asserts, six `3.12.3` sites in five files split four/two, 14 policy sites, 18
PEP 695 sites across 10 modules, and a two-key seam whose greatest-key-≤ lookup is consistent with
proposition 4 and its literal-tuple test. No decision is left to a fresh session, and done-when 1–12
cover the scope. What remains is one wrong identifier — a function name that exists in no file under
`zikaron/` or `tests/`, carried in the brief and both of its neighbours — one round-3 cascade (a "one
change" sentence beside a done-when asking for three edits to the same file), and five nitpicks, two of
them enumerations in the cited measurement note that drifted behind the brief's own corrections. All
are sentence-sized. This should be the last round.

### Findings

1. **[IMPROVEMENT] `_quiesce` does not exist, and the mutation paragraph names one loop by two names.**
   `:2066` reads *"then `_quiesce`'s loop exits without cancelling anything"*; the loop is
   `RunningServer.close_all_connections` (`server.py:248`, the `while` at `:322`), which the same paragraph
   names correctly four lines later at `:2070`. `grep -rn '_quiesce\|ServiceServer' zikaron tests` returns
   nothing — both names live only in `FINDINGS.md:831/837` and the probe note `:104/:119`, from which the
   brief inherited them. The mechanism clause is also imprecise: `wait_closed()` does not "never resolve",
   because `shut_down` bounds it (`server.py:370–385`, `_SHUTDOWN_QUIESCENCE_DEADLINE_SECONDS = 5.0` at
   `:47`). Under the mutation the loop never enters, the gated handler is never cancelled, and
   `ShutdownTimeoutError` propagates out of `shut_down_task` at its 5 s deadline — a deadline that started
   when the task first ran at `test_service_server.py:185`, before the test's own
   `wait_for(shut_down_task, 5.0)` at `:193`, so it is the task's exception and not the test's timeout that
   fails it. It fails either way; say which. **Suggested edit**, `:2066–2067`: *"— then
   `close_all_connections`'s loop (`server.py:322`) never enters, nothing is cancelled, and `shut_down`'s
   bounded `wait_closed()` raises `ShutdownTimeoutError` at its 5 s deadline, which fails that test."* Then
   `FINDINGS.md:831` and probe note `:104` → `RunningServer.close_all_connections`; `FINDINGS.md:837` and
   probe note `:119` → *"`close_all_connections`'s own docstring"*.

2. **[IMPROVEMENT] `:2076` "gains **one** change" is contradicted by done-when 11's two further edits to
   the same file.** Cascade of round-3 F4: `check.sh:2` gains the two-script sentence and `check.sh:38–44`
   the hermeticity exception (`:2249–2251`), so the file receives three edits, and a verifier reading "one
   change" against the diff fails the milestone on the brief's own sentence. **Suggested edit**:
   *"`./check.sh` keeps its present behaviour byte-identical and gains **one behavioural change** — its
   hard-coded `venv=.venv/bin` becomes `venv="${ZIKARON_VENV:-.venv}/bin"` — plus the two header-comment
   sentences done-when 11 names, which change no behaviour."*

3. **[NITPICK] `:2119–2120` "Each seam row is unexecuted on the other two interpreters" is the
   one-row-per-minor model that round-2 F16 replaced.** Under the two-key table the `(3, 12)` row is
   unexecuted on 3.13 and 3.14 and the `(3, 13)` row on 3.12 only. And *"one line per unused row"* holds
   only if a row body occupies a line of its own: a lambda inside the table literal sits on a line the
   literal executes, and coverage.py reports nothing for it, so the paragraph's prediction depends on a
   shape the brief does not fix. **Suggested edit**: *"The `(3, 12)` row is unexecuted on 3.13 and 3.14 and
   the `(3, 13)` row on 3.12, so `show_missing` lists whatever lines those bodies occupy on their own —
   none if the rows are lambdas in the table literal, one or more if they are `def`s — on every run…"*.
   The accept-no-pragma decision stands either way.

4. **[NITPICK] The hermeticity exception sentence can become a fourth copy of the tested set.**
   `:2154–2155` and done-when 11 ask both sentences to say *"what it needs"*; written as "3.12, 3.13 and
   3.14 on `PATH`", that is a fourth site and done-when 9's *"exactly three places"* is falsified by this
   milestone's own edit. **Suggested edit**, `:2155`: *"…and that `check.sh` itself stays hermetic — naming
   the set by reference, *the minors `check-matrix.sh` runs*, never by listing it."*

5. **[NITPICK] The cited measurement note gives a different PEP 695 count from the brief.** Probe note
   `:26–28`: *"PEP 695 syntax in ten places (… and eight more)"*; the brief (`:1947`, proposition 1) says
   **18 sites across 10 modules** and names that note as its measurement. Re-derived: a grep over
   `zikaron/` for `def …[`, `class …[` and `type … =` returns **18 occurrences in 10 files** — the brief is
   right, and the note's "ten" is the module count wearing the word "places". **Suggested edit**, probe
   note `:26`: *"at 18 sites across ten modules"*.

6. **[NITPICK] Probe note §5b item 2 (`:177–178`) lists nine `not sock_path.exists()` sites; the brief
   (`:2054–2056`) lists ten.** `test_service_lifecycle_integration.py:851` was added to the brief after
   round-1 F13 and never to the note the brief cites for the same list. The note's own rule at `:204–205`
   — an enumeration is re-derived from source every time it is corrected — applies to this list as much as
   to the unlink table two items below it. **Suggested edit**: add
   `test_service_lifecycle_integration.py:851` to the note's list.

7. **[NITPICK] `:2092` says the script adds the `.gitignore` entry.** The bullet sits in the list headed
   *"`check-matrix.sh` then:"* (`:2082`), so read literally the *script* edits `.gitignore` on each run;
   and no done-when item names the entry at all. **Suggested edit**: drop the bullet from the script's
   list and add to done-when 9: *"`.venv-matrix/` is in `.gitignore`, which today covers only `.venv/` and
   `venv/`."*

VERDICT: NEEDS_CHANGES

## Round 5 — 2026-09-20

Artifact re-read whole: `design/build-plan.md:1938–2303`, against `FINDINGS.md:813–956`, the probe note
§§2/5/5b/8, `server.py:40–61` and `:225–406`, `tests/test_service_server.py:43–195`, `main.py:190–199`,
`:252–263`, `:320–364` and `:486–493`, `service/log.py:38–48`, `tests/test_service_main.py:550–559`,
`check.sh`, `tests/test_check_gate.py`, `.gitignore`, `pyproject.toml`, `coding-standards.md:323–327`,
`architecture.md:703–716`, `README.md:65/84/459`, `CLAUDE.md:52–62`, `build-plan.md:1–9`, `schema.md:5`,
`.claude/agents/memory-researcher.md:42` — plus fresh greps over `zikaron/` and `tests/` for
`_quiesce|ServiceServer`, `get_event_loop_policy`, `not sock_path.exists()`, `3.12.3`, `unlink(`, PEP 695
sites, the definition-of-done claim in all its phrasings, and **every spelling done-when 3 names, run as the
bare tokens the brief lists**, which is where finding 1 comes from.

### Summary judgment

All seven round-4 fixes landed as described, and the new mechanism claim is correct as far as I can trace
it: under the constant-`0` mutation the `while` at `server.py:322` never enters, `shut_down` reaches
`wait_for(self.server.wait_closed(), remaining)` at `:380` with the gated transport still attached, and
`:381–385` re-raises the timeout as `ShutdownTimeoutError`; that deadline was set at `:370` when the task
first ran during the test's `:185` await, so it expires before the test's own `wait_for` at `:193`, and it
is the task's exception that fails the test. The confabulated identifier survives only in the two
deliberate withdrawal notes; every enumeration re-derives to the brief's figure (14, 10, 6-in-5 split 4/2,
7 split 5/2, 18-in-10, six definition-of-done sites); no decision of consequence is left to a fresh
session and the twelve done-when items cover the prose with nothing extra. What remains is one gap no
round caught because no round wrote down the pattern it grepped with — the `_clients` spelling, scanned as
the brief lists it, matches six unrelated test names inside the scope done-when 3 puts `tests/` into, and
the two obvious pattern shapes guard different things — one half-specified verification, and four
clause-sized nitpicks, two in the neighbours. Round 6 should be a formality.

### Findings

1. **[IMPROVEMENT] Done-when 3's `_clients` spelling, scanned as written, matches six unrelated test
   names, and the brief must fix the pattern shape because the two candidate shapes guard different
   things.** `:2209–2211` lists the spellings as bare tokens; `:2205–2208` says the mechanism is a regex
   over file *text* with `tests/**/*.py` in scope. `grep -rn '_clients' zikaron tests` returns, beyond
   `server.py`, `tests/test_service_lifecycle_integration.py:562`
   (`test_two_clients_racing_a_cold_store_converge_on_one_server`), `tests/test_harness_store_scope.py:12`
   and `:108`, `tests/test_install_claude_live.py:32` and `:191` (`…both_clients…`), and
   `tests/test_knowledge_cli.py:451` (`…both_clients_use`) — six sites that read nothing. An executor's
   first run of the scanner reddens on them and then chooses: `\._clients\b` (attribute access only)
   exempts prose, which `:2212–2214` says is *"exactly the drift being guarded against"*; `\b_clients\b`
   keeps prose in scope and excludes all six, because `_` is a word character so `h_clients` has no
   boundary while a backticked or dotted `_clients` does. The brief's claim that the tree outside the seam
   is clean but for `:148`, `:189` and the docstrings is true only under the second, and no round has
   recorded which pattern it ran. **Suggested edit**, after `:2211`: *"— each as a word-bounded pattern
   (`\b_clients\b`, `\b_active_count\b`), never a substring: six test names in `tests/`
   (`test_two_clients_racing…` and four `…both_clients…`) contain `_clients` and read nothing, and `_`
   being a word character is what excludes them while keeping a backticked `_clients` in a docstring in
   scope."* The prose sentence at `:2212` then stands as written.

2. **[IMPROVEMENT] Done-when 4's mutation is verified on one interpreter and asserted for three, and
   done-when 5 names no mutation while "through the seam" does not pin the product's call site.**
   `:2219–2222` reads *"returns the same quantity on all three minors, verified by mutating its seam row
   to a constant `0`"* — singular. Run on `.venv`, that mutates the `(3, 12)` row and proves the test's
   sensitivity to a wrong 3.12 row; the `(3, 13)` row, the one this milestone writes, is never shown to be
   load-bearing — M14's *"universal claim proven only by its best-case fixture"*, invoked by the brief
   itself at `:2062–2063`. And `:2062` says *"both guards by mutation"* while only guard 4's is named;
   `:2059` gives guard 5's in prose (*"fails on 3.13+ without the seam"*), but done-when 5's *"started
   through the seam"* is satisfiable by a test that calls `asyncio.start_unix_server(**unix_server_kwargs())`
   itself, which passes with `server.py:405` unchanged and guards nothing. **Suggested edits** —
   done-when 4: *"…verified by mutating **each** row to a constant `0` under an interpreter that selects
   it — the `(3, 12)` row on 3.12, the `(3, 13)` row on 3.13 or 3.14 — and confirming
   `test_shut_down_survives…` fails each time before the guard is trusted."* Done-when 5: *"A server
   started through `server.serve` — the product's own path, so what the test proves is `server.py:405`
   passing `**unix_server_kwargs()` — and closed with `shut_down()` leaves its socket file on disk, on
   every minor the matrix runs; verified by mutating the `(3, 13)` row of `unix_server_kwargs()` to `{}`
   under 3.13 or 3.14 and confirming it fails. On 3.12 no row can make it fail, so that run is not
   evidence."* Change `:2058`'s "through the seam" to match.

3. **[NITPICK] `:2086` "fixed in the script and nowhere else" contradicts done-when 9's "written out in
   exactly three places" (`:2240`).** The intended sense — fixed *by* the script rather than by the
   environment — is recoverable from the `ZIKARON_PYTHON_3_13` sentence that follows, but the words say
   the list appears nowhere else. **Edit**: *"fixed in the script rather than read from the environment"*.

4. **[NITPICK] `:2077` "keeps its present behaviour byte-identical and gains one behavioural change"
   contradicts itself inside one clause.** My own round-4 wording. The object is the default invocation,
   which done-when 9 already names. **Edit**: *"keeps its default-invocation behaviour byte-identical and
   gains one behavioural change — its hard-coded…"*.

5. **[NITPICK] Probe note `:33` still says the cap "did, accidentally, hide **one** real defect — §5"**,
   over the same file's §5b and against `FINDINGS.md:830`'s "two", which round-2 F4 corrected in FINDINGS
   alone. **Edit**: *"hide two real defects — §5 and §5b"*.

6. **[NITPICK] `FINDINGS.md:919` "fix `main.py`'s now-false 'unlinked exactly once'" reads against
   done-when 6.** The brief (`:2225–2227`) says the sentence *"stays true on every minor … a claim being
   made durable, not repaired"* — round-2 F14's correction, made in the brief and not in the neighbour. A
   fresh session reading FINDINGS goes to repair a sentence the brief says is true. **Edit**: *"keep
   `main.py`'s 'unlinked exactly once' true on every minor — the seam's `cleanup_socket=False` is what
   keeps it so — and have the comment say why"*.

VERDICT: NEEDS_CHANGES

## Round 6 — 2026-09-20

Artifact re-read whole: `design/build-plan.md:1938–2320`, against `FINDINGS.md:813–959`, the probe note
`:20–35`, `server.py:316–345` and `:388–405`, `tests/test_service_server.py:43–195` (the oracle test's whole
body, not the docstring), `tests/test_service_main.py:548–559`, `check.sh`, `tests/test_check_gate.py`,
`coding-standards.md` §§6/9 — plus fresh greps over `zikaron/` and `tests/` for `_clients` (bare and
word-bounded), `_active_count`, every version-read spelling done-when 3 names, `def serve`, and
`best-case` in the brief.

### Summary judgment

All six round-5 fixes landed as described and the new claims check: the two serve-path passages
(`:2058–2062`, `:2236–2241`) agree with each other and with `server.py:388`/`:405`; the word-bounded
measurement re-derives exactly (six `_clients` sites, all inside test names, none in `server.py`, none with
a boundary before the underscore); no `sys.version_info`, `hexversion` or `python_version` spelling
exists anywhere under `zikaron/` or `tests/` today, so proposition 3 is true on arrival; the probe note and
FINDINGS carry F5 and F6 as the brief says. What remains is one cascade in exactly the cell the rubric
named — the mutation-mechanism paragraph in §"The contract nobody pinned" describes what a constant-`0` row
does to *today's* oracle test, whose precondition poll at `:148` bypasses the seam; done-when 3 sends that
poll through the seam, after which the same mutation fails the test at `:152` before `shut_down` ever runs
and the `ShutdownTimeoutError` the brief says *"is what fails that test"* is never raised — one coverage
gap (the five §6 propositions, the milestone's stated normative output, have no done-when item), and five
clause-sized nitpicks, two of them counts I introduced in round 5. Nothing blocks; the two improvements
are a paragraph and a line.

### Findings

1. **[IMPROVEMENT] The mutation-mechanism paragraph is true of the test as it stands today and false of
   the test done-when 3 produces — a cascade between done-when 3's scope and done-when 4's oracle.**
   `:2068–2070` reads *"The mutation is of the seam row to a constant `0` — then `close_all_connections`'s
   loop (`server.py:322`) never enters, nothing is cancelled, and `shut_down`'s bounded `wait_closed()`
   raises `ShutdownTimeoutError` at its 5 s deadline, which is what fails that test."* That is the
   mechanism **only while `tests/test_service_server.py:148` reads `bare_server._active_count` directly**:
   the poll at `:147–152` then sees the real count, breaks, and the mutated row is first consulted inside
   `shut_down`. But `:2188–2189` and done-when 3 (`:2214–2215`) say `:148` *"currently violates"* the scan
   and must go through the seam. Once it does, a constant-`0` row makes the `for … else` at `:147–152`
   exhaust its 1,000 turns and raise `AssertionError("the server side never attached the accepted
   transport")` — **before `shut_down_task` is created at `:174`**. The test still fails, so done-when 4's
   pass/fail criterion survives; what does not survive is the sentence naming the failure, and round 4's
   own standard (*"It fails either way; say which"*) now names the wrong one. An executor who runs the
   mutation and sees an `AssertionError` at `:152` instead of the promised `ShutdownTimeoutError` has to
   decide whether the mutation took. The `ShutdownTimeoutError` path is, post-milestone, what the
   **caller** mutation (`len(self._connections)`) produces — the poll passes on the correct row and the
   loop at `:322` then never enters. There is also a decision hiding here: the executor could instead
   re-target the poll at something seam-free (`handler_started` is set inside the same window, `:128`),
   which would keep the paragraph true and change what "attached" means in the test's precondition. The
   brief should choose; I recommend the seam, since the poll then exercises the row against a raw
   `asyncio.Server`, the exact shape production hands it. **Suggested edit**, replacing `:2068–2075`:
   *"**The mutation is of the seam row to a constant `0`.** Once `:148` polls through the seam (done-when
   3), that mutation fails the test at its own precondition — the poll at `:147–152` never sees a positive
   count and raises 'the server side never attached the accepted transport' before `shut_down` runs — so an
   `AssertionError` there, not a `ShutdownTimeoutError`, is the failure to expect under done-when 4. The
   other valid form, mutating the **caller** in `close_all_connections` to `len(self._connections)`, passes
   the poll and fails later: the loop at `server.py:322` never enters, nothing is cancelled, and
   `shut_down`'s bounded `wait_closed()` raises `ShutdownTimeoutError` at its 5 s deadline. Both are
   failures of the same test, which is why it is the oracle for both. (Not 'mutate it to
   `len(running._connections)`': `attached_connection_count` receives an `asyncio.Server` and cannot see
   the `RunningServer`'s own set.)"* Done-when 4 can stand as written.

2. **[IMPROVEMENT] The five §6 propositions have no done-when item.** `:1941` says §6 *"is this
   milestone's normative output and it writes"* it, and `:1972` says *"§6 gains these five propositions"*
   — but the checklist anchors only proposition 2, and only obliquely: done-when 9's *"the set §6 states"*
   and *"§6 proposition 2 (canonical)"*. Propositions 1, 3, 4 and 5 — the floor's reason, the seam rule
   and its `tests/` scope, the newest-row behaviour on an untested minor, the deprecation-placement rule —
   are the standing rules a later session will be bound by, `coding-standards.md` being *"binding"* per
   `CLAUDE.md`, and a verifier running done-when 1–12 can pass this milestone with §6 still reading only
   *"`venv`, latest stable, pinned exactly"* (`coding-standards.md:229`), which says nothing about the
   interpreter. Done-when 11 covers §9 and the six definition-of-done sites and is the natural home.
   **Suggested edit**, prepended to done-when 11: *"`coding-standards.md` §6 opens with the five
   propositions of §'What "supported" means', in that wording — the interpreter being the first dependency
   — with proposition 2's sentence the one done-when 9's drift test parses;"*. In the same spirit, `:2020`'s
   *"must be a function returning a fresh mapping"* is a normative rule stated only in prose; done-when 2's
   *"exposing … `unix_server_kwargs()`"* could read *"`unix_server_kwargs()` returning a fresh mapping"* so
   the checklist carries it.

3. **[NITPICK] The `_clients` parenthetical's counts do not add up, and I wrote them.** `:2216–2218` reads
   *"Six test names under `tests/` contain `_clients` … (`test_two_clients_racing…` and four
   `…both_clients…`)"* — 1 + 4 = 5, not 6, and neither figure is right on either reading. Re-derived: **six
   sites, four test names** — `test_two_clients_racing_a_cold_store_converge_on_one_server`
   (`test_service_lifecycle_integration.py:562`) and three `…both_clients…` names
   (`test_harness_store_scope.py:108`, `test_install_claude_live.py:191`, `test_knowledge_cli.py:451`), two of
   which are quoted a second time in a docstring (`:12` and `:32` of the first two files). Round 5's
   suggested wording carried the error. **Edit**: *"Six sites under `tests/` contain `_clients` and read
   nothing — four test names, `test_two_clients_racing…` and three `…both_clients…`, two of them quoted a
   second time in a docstring —"*.

4. **[NITPICK] `:2233–2235` cites a phrase at a place that does not carry it.** *"M14's 'universal claim
   proven only by its best-case fixture', which §'The contract nobody pinned' invokes two paragraphs above"*
   — that section is ~170 lines up, not two paragraphs, and `best-case` occurs in the brief only at `:2234`
   itself. What `:2064–2065` invokes is M14's mutation practice and its *"three separate times"*, of which
   the best-case fixture is one (`FINDINGS.md` §"Current state", the M14 paragraph). **Edit**: *"— M14's
   'universal claim proven only by its best-case fixture', the same lesson §'The contract nobody pinned'
   cites for verifying both guards by mutation."*

5. **[NITPICK] `close_all_connections` reads the private counter three times, and the brief names one.**
   `:1956` *"`service/server.py:322` reads it"*; the reads are `:322` (the loop condition), `:327` and
   `:336` (the two `ShutdownTimeoutError` messages). Nothing in the design changes — done-when 3's scan
   reddens on all three — but a verifier of the seam rewrite who stops at the line the brief names leaves
   two `type: ignore[attr-defined]` reads behind. **Edit**, `:1956`: *"`close_all_connections` reads it at
   `server.py:322`, `:327` and `:336`, and 18 tests go red."*

6. **[NITPICK] `check-matrix.sh`'s behaviour on an absent interpreter is implied, not stated.** `:2089–2095`
   fixes the minor list and forbids the environment from dropping a minor; `:2101` says the script *"fails on
   the first red minor"*. A missing `python3.14` with no override is the one case that could read as a skip,
   and a skip would let a machine carrying only 3.12 satisfy the milestone rule with one interpreter — the
   same hole `conftest.pytest_runtest_makereport` closes for the integration tiers. **Edit**, `:2101`:
   *"fails on the first red minor, naming which — and an absent `python3.<minor>` with no override is a
   red minor, never a skip."*

7. **[NITPICK] `FINDINGS.md:912–925`'s work list is now a broken sentence.** The semicolon list *"The work
   is then: relax the pin …; the seam; deprecations as errors …"* is interrupted by the italic
   deprecation-reason note, which ends in a full stop, after which `:919` resumes in lowercase — *"keep
   `main.py`'s…"* — as a fragment. The F6 wording is right; only the joinery broke. **Edit**: begin `:919`
   with *"Also in that list: keep `main.py`'s…"*, or move both italic notes to the end of the list.

VERDICT: NEEDS_CHANGES

## Round 7 — 2026-09-20

Artifact re-read whole: `design/build-plan.md:1938–2337`, against `tests/test_service_server.py:89–195`
(traced line by line under both mutations, with `:148` reading the private counter directly and with it
routed through the seam), `server.py:245–406`, `tests/test_service_main.py:545–559`, `check.sh`,
`tests/test_check_gate.py`, `pyproject.toml` (the `dev` extra, `python_version`, `target-version`,
`addopts`, `fail_under`), `coding-standards.md` §§6/9, `FINDINGS.md:813–959` — plus fresh greps over
`zikaron/` and `tests/` for `_clients` and `_active_count`.

### Summary judgment

All seven round-6 fixes landed as described, and the new claims check against the tree independently of
my round-6 wording: a zero row makes the seam-routed poll exhaust its 1,000 turns and raise at `:152`,
before `shut_down_task` is created at `:174`; the caller mutation passes the poll, `:322`'s loop never
enters, and `wait_closed()` at `:380` times out into `ShutdownTimeoutError` at `:382` on a deadline set
at `:370` — before the test's own `wait_for` at `:193`, so it is the task's exception that fails it. The
three reads are `:322`/`:327`/`:336`; six `_clients` sites over four names re-derive exactly; `dev` carries
ruff, mypy, pytest and pytest-cov, so `check.sh` runs whole under `ZIKARON_VENV`; §6 and §9 read as the
brief says; `FINDINGS.md:919` is a sentence again. **Nothing blocks and no done-when criterion is wrong.**
What remains is three sentences, all in the cell the rubric named: the diagnostic clause appended to the
rewritten mutation paragraph is false (a mutation that did not take produces a green test, never a wrong
exception); done-when 11's *"in that wording"* — my round-6 phrase — would paste brief-relative clauses,
one of them a self-reference that becomes false on pasting, into a binding document; and done-when 4's
row mutation, now caught at the test's own precondition, never reaches `close_all_connections` and so no
longer shows the product's seam call is load-bearing, while the caller mutation that would is described
and required nowhere. If those three land as written below I have nothing further.

### Findings

1. **[IMPROVEMENT] The diagnostic clause is wrong in every case it could apply to.** `:2077–2079` reads
   *"Both fail the same test, which is why it is the oracle for both, and an executor who sees the wrong
   exception should suspect the mutation did not take."* Traced: a mutation that did not take leaves the
   test **green** — there is no exception to be wrong. Under the row mutation, `ShutdownTimeoutError` in
   place of the `AssertionError` at `:152` means `:148` is **still reading the private counter directly**:
   the poll passed on the real count and handed the zero row to `close_all_connections`, which is the
   pre-milestone mechanism, so done-when 3's edit to that line has not landed yet. Under the caller
   mutation, an `AssertionError` at `:152` means the row was mutated instead of the caller. The clause
   therefore sends the executor to re-check the edit when the thing to check is the poll's routing or
   which site was mutated. **Edit**, `:2077–2079`: *"Both fail the same test, which is why it is the
   oracle for both. A green run means the mutation did not take. `ShutdownTimeoutError` under the row
   mutation means `:148` is still reading the private counter directly — the poll passed on the real
   count and handed the zero row to `close_all_connections`, the pre-milestone mechanism — so done-when
   3's edit to that line has not landed; an `AssertionError` under the caller mutation means the row was
   mutated instead."* Same paragraph, `:2069`: *"which assertion catches it"* — `ShutdownTimeoutError` is
   not an assertion; *"where it fails"*.

2. **[IMPROVEMENT] "In that wording" pastes brief-relative text, and one self-reference, into §6.**
   Done-when 11 (`:2284–2285`) takes the five propositions *"in that wording"* — the phrase is mine, from
   round-6 F2, and it does not survive contact with the propositions as written. Proposition 3
   (`:1989–1991`) carries *"which done-when 3's scan covers and which this proposition must say, since as
   §6 text it is what a reader will believe"* — commentary *about* §6 text, not §6 text. Proposition 4 has
   *"the brief chooses this behaviour deliberately"* (`:1995`) and *"the cap this milestone removes"*
   (`:1997`), neither of which has a referent in `coding-standards.md`. Proposition 5 (`:2000`) says
   *"§6's own first rule pins every dependency exactly"* — pasted as §6's new opening, that sentence
   points at itself and is false, the pinning rule having become the sixth. Its withdrawal parenthetical
   (`:2004–2006`) is a historical trace of the kind the operator's own rule keeps out of normative
   documents (a design document states what we are doing; the history lives in the trail) — it stays in
   the brief and `FINDINGS.md`, which the researcher's note already marks intentional. And proposition 3's
   *"So today the table has two keys … and 3.14 resolves to the `(3, 13)` row"* (`:1985–1986`) is, in a
   binding document, a count every added row falsifies and which, by the brief's own design, no drift test
   guards — the M13-hash rule. An executor either pastes these or decides what to strip, which is rubric
   (2)'s class in miniature. **Edit**, done-when 11's head: *"`coding-standards.md` §6 opens with the five
   propositions of §'What "supported" means' — each bold lead sentence and its reason, in that wording
   **except** the brief-relative clauses, which are rewritten in §6's own voice: proposition 3's
   'done-when 3's scan' becomes 'a source-scanning test over `zikaron/` and `tests/`' and its 'today the
   table has two keys…' sentence is replaced by 'the module's table is the record of which minors changed
   what'; proposition 4's 'the brief chooses' and 'this milestone removes' become plain statements;
   proposition 5's '§6's own first rule' becomes 'the pinning rule below', and its withdrawal parenthetical
   stays here and in `FINDINGS.md` rather than entering a normative document. Proposition 2's sentence is
   the one done-when 9's drift test parses, so it is written together with the regex."*

3. **[IMPROVEMENT] Done-when 4's row mutation no longer reaches the product's seam call, and the decision
   that routes the poll lives only in prose.** Two consequences of round-6 F1 that done-when 4
   (`:2241–2248`) did not absorb. **(a)** With `:148` through the seam, the row mutation fails at `:152`
   before `shut_down` runs, so it now verifies that the *test's poll* is sensitive to the row and never
   executes `close_all_connections`'s seam call — the product site done-when 3's scan forces to change,
   and the one the pre-round-6 row mutation proved load-bearing in the same run. The suite's normal run
   still guards it (traced: `len(self._connections)` there fails the oracle with `ShutdownTimeoutError`),
   but M14's practice, which `:2065` invokes, is to break the guarded code once and watch the test go
   red; the caller mutation is described at `:2074–2077` and required nowhere. **(b)** `:2079–2081`
   decides the poll goes through the seam rather than `handler_started`, and no done-when carries it:
   an executor who re-targets `:148` at `handler_started` satisfies done-when 3's scan (no private name)
   and done-when 4's *"fails each time"* (the row mutation then fails via `ShutdownTimeoutError`, traced)
   while contradicting the paragraph's stated failure. **Edit**, done-when 4: *"`tests/test_service_server.py:148`
   polls `attached_connection_count(bare_server)`, and `attached_connection_count` returns the same
   quantity on all three minors, verified by mutating **each row** to a constant `0` under an interpreter
   that selects it — the `(3, 12)` row on 3.12, the `(3, 13)` row on 3.13 or 3.14 — and confirming
   `test_shut_down_survives…` fails **at `:152`** each time; and by mutating the caller in
   `close_all_connections` to `len(self._connections)` once, on any minor, and confirming the same test
   fails with `ShutdownTimeoutError` — the row mutation, now caught at the poll, never reaches the
   product's seam call, so this is the one mutation that shows it is load-bearing."* The existing M14
   sentence follows unchanged.

VERDICT: NEEDS_CHANGES

## Round 8 — 2026-09-20

Artifact re-read whole: `design/build-plan.md:1938–2360`, against `tests/test_service_server.py:89–195`
(the poll at `:147–152`, its message at `:152`, `shut_down_task` at `:174`, the message at `:189`),
`design/coding-standards.md:227–231` and `:321–324` — plus fresh word-bounded greps for `_clients` and
`_active_count` over `zikaron/` and `tests/`, and a grep of the brief for the phrase F1 was to remove.

### Summary judgment

All three round-7 edits landed as specified and none contradicts a neighbour. F1's three-outcome reading
(`:2078–2082`) is correct against the traced test and "where it fails" replaces the misnomer at `:2069`.
F3's opening clause (`:2245`) agrees with done-when 3's *"currently violates"* (`:2231`), with
§"The contract nobody pinned"'s routing decision (`:2083–2085`), and with done-when 2's *"verified by the
matrix alone, through done-when 4 and 5"* (`:2224`), since the row mutation now exercises the row through
the poll and the caller mutation the product call. F2's paragraph (`:2298–2310`) is consistent with the
propositions it rewrites — the pinning rule is §6's first bold rule today (`coding-standards.md:229`), so
"the sixth" is right. The brief is ready; the two items below are optional wording inside F2's enumeration,
both residues of my own round-7 phrasing.

### Findings

1. **[NITPICK] F2's enumeration covers half the clause round 7 quoted.** Proposition 3 at `:1989–1991`
   reads *"…reads the running version**, which done-when 3's scan covers **and which this proposition must
   say, since as §6 text it is what a reader will believe**"*; done-when 11 (`:2300–2301`) rewrites only
   *"which done-when 3's scan covers"*. The second half is commentary about §6 from outside it — an
   instruction to the writer, not a rule — and pasted into §6 it is incoherent. The head sentence's
   general rule (*"except the brief-relative clauses"*) covers it; the enumeration, presented as the list
   of what to strip, does not. **Edit**, `:2300–2301`: *"proposition 3's 'which done-when 3's scan covers
   and which this proposition must say, since as §6 text it is what a reader will believe' becomes 'which
   a source-scanning test over `zikaron/` and `tests/` enforces'"*.

2. **[NITPICK] Proposition 1's count enters §6 undated, three lines above where the same paragraph strips
   a sibling count for being undated.** `:1976` *"PEP 695 syntax at 18 sites across 10 modules is the
   floor's reason"* would be pasted verbatim; done-when 11 removes proposition 3's *"two keys"* sentence as
   *"a count every added row falsifies, guarded by no drift test … the M13-hash rule"*, and no test counts
   PEP 695 sites either. The brief's own treatment of the `3.12.3` sites (`:2196–2198`) is the model: a
   measurement that names when it was taken stays true. **Edit**, add to the enumeration: *"proposition 1's
   count is dated — 'measured at 18 sites across 10 modules when the floor was set, 2026-09-20' — or
   dropped, 'PEP 695 syntax is the floor's reason' being sufficient as a rule."*

VERDICT: APPROVED
