# Review — M28: Publication (a licence, a sweep, and a continuous instrument)

Artefacts: `design/distribution.md`, `.github/workflows/check.yml`, `tests/test_ci_workflow.py`,
`research/publication-sweep.md`, `tests/test_publication_hygiene.py`, `design/overview.md` §4 D35/D36,
`pyproject.toml` `[project]`, `LICENSE`, `README.md` §§Requirements/Install/"Design and development".
Contract: `design/build-plan.md` §M28 done-when 1–10.

## Round 1 — 2026-09-22

### Summary judgment

Against done-when 1–10 the tree is nearly complete and the hard part was done carefully: all seven
definition-of-done sites carry the *distinction* rather than "and CI" (grepped, not counted from the
brief), D35/D36 are consistent across `overview.md`, `FINDINGS.md`'s index and `CLAUDE.md`'s table, the
workflow's environment plumbing is right (`$GITHUB_ENV` in a `run:` step is visible to every later step,
and `${{ runner.temp }}` in a step's `with:` resolves to the same `$RUNNER_TEMP`), and `fastembed` 0.8.0
really does read `FASTEMBED_CACHE_PATH` (`fastembed/common/utils.py:54`). Two things must change before
the repository goes public: the **recommended install command does not deliver the property it is
recommended for** — the probe measured `uv tool install` only with `--python-preference only-managed`
and no host interpreter present, and uv's documented default uses a host Python when no managed one is
installed, which is the state of every fresh Mac — and **D36 asserts the "11 ms" figure that
`distribution.md` §2 withdrew in the same milestone.** Below those, §4's central CI claim about
`runner.temp` is asserted with no source and is very probably wrong in direction, the deprecation
filters are scoped wider in CI than in the matrix, and the drift test passes several mutations it
says it catches.

### Findings

1. **[BLOCKER] The recommended `uv tool install git+…` does not guarantee the interpreter §2's
   recommendation is justified by.** Sites: `README.md:89-90` ("Recommended — uv fetches its own
   interpreter as well as the dependencies"), `README.md:101-105`, `design/distribution.md:54-71` (§2:
   "makes `uv` the path that is known to work rather than the path that happens to"),
   `design/overview.md:140` (D36 rationale, same sentence). Evidence: the only measurement behind this
   is `research/python-portability-probes.md:254`, which ran
   `uv tool install --python 3.14 --python-preference only-managed <tree>` "with no host 3.14 present"
   — the one configuration in which uv has no choice but to fetch. The documented command passes
   neither `--python-preference` nor `--managed-python`. uv's documented default
   (`python-preference = managed`; the `--managed-python` flag's own help text: *by default uv prefers
   the Python versions it manages, but will use system Python versions if a uv-managed Python is not
   installed*) uses a host interpreter satisfying `>=3.12` when no managed one exists — which is every
   fresh uv install. So on the exact machine §2 is written for — a Mac with the python.org installer's
   3.12/3.13 and a freshly installed uv — the tool venv is built on the interpreter §2 says cannot load
   `sqlite-vec`, retrieval fails at first use, and the README's parenthetical is false. This corpus's
   own `check-matrix.sh:99` already reaches for `--managed-python` for the mirror-image reason.
   **Fix:** (a) document `uv tool install --managed-python git+https://github.com/nathan-shapiro/Zikaron.git`
   (or `--python-preference only-managed`, the form §6 measured) at all three sites, with one sentence
   saying the flag is what makes the recommendation true; (b) before shipping, verify the fallback in a
   scratch directory — `UV_PYTHON_INSTALL_DIR=<empty dir> uv python find 3.12` answering
   `/usr/bin/python3.12` shows the default, and the same with `--managed-python` should refuse or
   download — and record it in probe note §6; (c) cite that measurement from §2. Prose only; no test
   reads README.

2. **[BLOCKER] D36 carries the fabricated figure `distribution.md` §2 withdrew.**
   `design/overview.md:140`: *"which is the same budget D31 protected by choosing stdlib-only clients
   over an HTTP client for 11 ms."* `design/distribution.md:77-79`: *"An earlier draft of this sentence
   said D31 made that choice 'for 11 ms'. D31 states no such figure; 11 was this document subtracting
   two of its numbers and presenting the result as a quotation."* D31 (`overview.md:135`) gives 10.9 /
   20.6 / 21.8 ms and no delta. This is the neighbour-contradiction class the brief asked me to look
   for, across the two normative documents of one milestone. **Fix:** in D36 replace "over an HTTP client
   for 11 ms" with "over an HTTP client on measured interpreter cost (D31)", then
   `grep -rn "11 ms"` across `design/` and `FINDINGS.md` for any other copy.

3. **[IMPROVEMENT] The "silently expands to `/fastembed_cache` and nothing reports it" mechanism has
   no source in the corpus and contradicts GitHub's documented behaviour.** Sites:
   `design/distribution.md:160-163`, `.github/workflows/check.yml:43-50`,
   `tests/test_ci_workflow.py:13` and `:176-181`. Neither `research/github-actions-macos-runners.md`
   nor any other note covers context availability; the rubric says to flag exactly this. The half that
   holds: GitHub's context-availability table lists `runner` for `jobs.<job_id>.steps.*` only — not
   for workflow `env:` and not for `jobs.<job_id>.env:`. The half that does not: a reference to a
   context outside its availability is rejected when the workflow is validated ("Unrecognized
   named-value: 'runner'") and no job starts — loud, not silent, and the empty-directory cache story
   never happens. The *design* (export from `$RUNNER_TEMP` in a `run:` step) is right regardless.
   **Fix:** reword the three sites to the supported claim — "`runner` is step-level only, so it is
   exported in a `run:` step; the test stops anyone moving it to a level the workflow would refuse to
   run at, before a push is spent finding that out" — and delete the "expands to `/fastembed_cache`"
   sentence, or keep it labelled *unverified until the first push*. If the silent expansion was
   actually observed, cite where.

4. **[IMPROVEMENT] The deprecation filters are scoped wider in CI than in the matrix, which is a drift
   in the direction the test cannot see.** `check.yml:34-41` sets both at workflow level, so they
   apply to `.venv/bin/pip install -e '.[dev]'` (and the PEP 517 backend subprocess it spawns, and the
   `python -c` version print). `check-matrix.sh:324-331` applies them only around `./check.sh`; the venv
   is built at `:314` without them. A `DeprecationWarning` raised inside pip, its vendored libraries, or
   setuptools 84's editable build on 3.13/3.14 reddens CI's *install* step on a tree the matrix passes —
   CI as the *stricter* definition of done for a reason that is not the code, the mirror of the failure
   §4 names. `test_every_job_gets_both_deprecation_filters` asserts presence, not scope, so it cannot
   see this; it also passes over a step-level `env: PYTHONWARNINGS: ""` on the `./check.sh` step.
   **Fix:** move the two variables into the `./check.sh` step's `env:` in both jobs (keep the comment
   block where it is), and change the test to compute the effective env *of the step that runs
   `./check.sh`*: `{**workflow.get("env", {}), **job.get("env", {}), **step.get("env", {})}`. That
   matches the matrix's scope exactly and closes the override hole in one edit.

5. **[IMPROVEMENT] `actions/cache` saves only when the job succeeds, and the advisory job is expected
   red.** `check.yml:162-166`; the claim it contradicts is `distribution.md:160-163` and the docstring at
   `test_ci_workflow.py:196-197` ("a job that skips this caches nothing and re-downloads the model every
   run"). `actions/cache`'s save is its post step, gated `post-if: success() || …save-always` (and
   `save-always` is deprecated in its own README as not working). So for as long as the macOS job is red
   — its expected state for all of M28 — no cache is ever written and every macOS run downloads 64 MB;
   on Linux the cache first writes on the first *green* run, so the coverage flap §"Coverage on a
   runner" predicts delays it by one. Free on a public repository, but the document says the opposite.
   **Fix:** either split into `actions/cache/restore@v6` + `actions/cache/save@v6` with `if: always()`
   on the save (same `key`; the drift tests still pass — both `uses` contain "cache" and carry
   `with.key`), or state in §4 and the workflow comment that the advisory job re-downloads until it goes
   green.

6. **[IMPROVEMENT] `distribution.md:165` "All of the above are asserted by `tests/test_ci_workflow.py`"
   is false for the second bullet.** No test asserts the interpreter comes from `uv`. A mutation
   replacing `uv python install` + `uv venv` with `actions/setup-python@v5` + `python -m venv` passes
   every test and silently changes what the `load_extension` evidence is *about* — the very thing the
   bullet says is "not a detail". **Fix:** add
   `test_every_job_takes_its_interpreter_from_uv_and_not_setup_python`: assert no step's `uses` starts
   with `actions/setup-python`, and each job's `_run_text` contains `uv python install --no-bin` and
   `uv venv`. Or drop "All of" and list what is asserted.

7. **[IMPROVEMENT] The cache-variable test passes over the failure it names, and nothing asserts step
   order.** `test_ci_workflow.py:192-203` checks `"FASTEMBED_CACHE_PATH=$RUNNER_TEMP" in _run_text(job)`.
   `run: export FASTEMBED_CACHE_PATH=$RUNNER_TEMP/fastembed_cache` passes and sets nothing for later
   steps — precisely "a step that cannot see a variable an earlier step set". It does not tie the
   exported directory to the cached one: `path: ${{ runner.temp }}/fastembed` passes and caches an
   empty directory. And no test orders anything: the export step, or the coreutils step, placed *after*
   `./check.sh` passes every test and the job dies exactly as §4 describes. **Fix:** (a) match the
   export line with `re.search(r'^echo "FASTEMBED_CACHE_PATH=\$RUNNER_TEMP/(\S+)" >> "\$GITHUB_ENV"$',
   run, re.M)` and capture the leaf; (b) assert every cache step's `with.path ==
   f"${{{{ runner.temp }}}}/{leaf}"`; (c) add a `_step_index(job, predicate)` helper and assert
   index(export) < index(`./check.sh`) in both jobs, and index(`brew install coreutils`) <
   index(`command -v timeout`) < index(`./check.sh`) in `macos`.

8. **[IMPROVEMENT] The runner-label test admits the two labels the research note warns against.**
   `test_ci_workflow.py:162-170`: `macos-15-intel` (x64 — the job's whole subject changes) and
   `macos-15-xlarge` (billed even on public repositories, per
   `research/github-actions-macos-runners.md` Q1) both pass `startswith("macos-")`. **Fix:**
   `assert re.fullmatch(r"macos-\d+", str(label))` — the bare label is the arm64 standard runner per Q1,
   and the docstring should say so.

9. **[IMPROVEMENT] README §Requirements repeats the short version `distribution.md` §1 says not to
   repeat.** `README.md:67-69`: *"briefly, `onnxruntime` stopped publishing macOS x86_64 wheels"*.
   `distribution.md:45-48`: *"the honest statement, and the one to repeat rather than the short
   version"*; `FINDINGS.md:1423` strikes the short version in place. **Fix:** *"briefly, supporting Intel
   Macs would mean pinning a year-stale `onnxruntime` on two of the three interpreters and a hard install
   failure on the third; Windows needs a second RPC transport rather than a flag."*

10. **[IMPROVEMENT] The `enable_load_extension`-off claim is stated as fact at three public sites where
    the corpus's own source hedges it.** `distribution.md:66-67`, `overview.md:140` (D36),
    `README.md:102-103` all say python.org's macOS installer and conda-forge ship it off.
    `research/python-distribution-portability.md:68` says *"most likely to fail"*, `:192` says
    *"historically"*, and `:421` files conda-forge under *medium confidence, corroborated but not
    primary-sourced or somewhat dated*. Probe note §4 verified the *uv* builds, not these. **Fix:** one
    hedge word per site ("reported off in …", "unverified here"), or hand M29 a one-command measurement
    on the runner (a python.org build is one `curl` away there). Load-bearing because it is the whole
    reason for finding 1's recommendation.

11. **[IMPROVEMENT] The hygiene guard omits the one credential family with no false-positive population
    in `zikaron/`.** `tests/test_publication_hygiene.py:17-21` justifies omitting family 2 (names) —
    agreed, `meta.py`'s `<NAME>_KEY` convention makes that an allowlist that grows with the schema. But
    family 3 (32/40/64-hex runs, `-----BEGIN`) has, per `research/publication-sweep.md` §3, **zero** hits
    inside `zikaron/` today, and a token pasted into shipped code is the case a guard earns its keep on
    more than a home path does. **Fix:** add family-3 patterns to `_FORBIDDEN`, assembled from fragments
    like the others (`"-----" + "BEGIN"`; `r"(?<![0-9a-fA-F])[0-9a-fA-F]{32}(?![0-9a-fA-F])"` and the
    40/64 forms), with matching samples in `test_every_forbidden_pattern_can_actually_match_something`;
    run once to confirm the sweep note's count, then it stands. While there: `read_text(encoding="utf-8")`
    at `:60` raises on the first non-text asset that ships — `errors="replace"` or a suffix skip.

12. **[NITPICK] D36 counts "nine rejected alternatives"; `distribution.md` §5 has twelve entries, one of
    them (`pysqlite3`) explicitly "not chosen and not refuted".** `overview.md:140`. The brief's own
    warning about lists that state their length. **Fix:** drop the number.

13. **[NITPICK] "A two-core runner" is unsourced.** `distribution.md:172-173`, `build-plan.md:2811`. The
    research note gives macOS 3 vCPU and no Linux figure. **Fix:** "a runner's core count and load differ
    from this machine's".

14. **[NITPICK] "onnxruntime shipped exactly one [universal2 wheel], at 1.12.0"** (`distribution.md:37-38`)
    overstates `research/onnxruntime-macos-wheels.md`, which checked four releases and says it did not
    check every one. **Fix:** "the only one the note found, at 1.12.0 in 2022".

15. **[NITPICK] Linux aarch64 is undefined.** §1's heading says Linux is supported; its table row says
    `Linux (x86_64)`. `onnxruntime` ships `manylinux_2_28_aarch64` per the note. **Fix:** one row or
    clause: "Linux aarch64 — wheels exist for every dependency, unverified".

16. **[NITPICK] `build-plan.md` §M28 done-when 6 still prescribes the job-level form**
    (`FASTEMBED_CACHE_PATH: ${{ runner.temp }}/fastembed_cache`) that the workflow comment and
    `test_the_model_cache_variable_is_never_set_where_the_runner_context_is_unavailable` reject. Strike
    in place with the step-level form beside it, per convention, so the contract does not send its next
    reader to the form its own test forbids.

17. **[NITPICK] `research/python-portability-probes.md:55-56`** — *"Intel Macs cannot install the current
    pin from PyPI"* — is refuted for cp312/cp313 by the onnxruntime note this milestone commissioned.
    Outside the artefact list, but the withdraw-in-place rule says strike it with the refutation beside
    it rather than leave a neighbour asserting the pre-fix world.

18. **[NITPICK] "Verified against the runner image's own readme … so nothing is preinstalled"**
    (`check.yml:136-138`, `distribution.md:154-155`). A package readme lists installed *packages*, not
    `/usr/bin`; absence of a system `timeout` is an inference from BSD userland, not a readme read. The
    "Prove" step makes it moot — under GitHub's `bash -eo pipefail` a BSD `timeout` fails `--version` —
    so only the wording needs softening.

VERDICT: NEEDS_CHANGES

## Round 2 — 2026-09-22

### Summary judgment

Every round-1 fix is real at the sites the brief names, and I checked each against the tree rather
than the brief: `--managed-python` is on the command at all three sites and the prose beside each
matches probe note §6's new preamble; the "11 ms" survives only inside its own withdrawals; the
filters sit on the gate step in both jobs and the test computes that step's effective env; the cache
is split with `always()` on both saves; the export is matched as a whole line with the leaf tied to
every cache `path`; order is asserted for the export and the coreutils pair; the label is
`fullmatch(r"macos-\d+")`; the family-3 guard is bounded on both sides and its samples pair
index-wise; and `.git/HEAD` is `refs/heads/main` with no `master` ref, so the trigger docstring is
true. What this round finds is the fixes' own tail, as the brief predicted: **the split cache plus
`if: always()` plus `cancel-in-progress: true` creates a new silent-cost path the combined action did
not have**; the recommendation's load-bearing claim is still measured on `uv python find`, a command
that never downloads by design, rather than on the `uv tool install --managed-python` the README
documents; two new tests are narrower than their docstrings; the mechanism finding 3 withdrew
survives verbatim in `FINDINGS.md`; and one of the eighteen fixes was applied at one of its two
cited sites. No blocker, but the improvements below are not cosmetic.

### Findings

1. **[IMPROVEMENT] `FINDINGS.md:1335-1340` still asserts the mechanism finding 3 withdrew, and
   frames it as a trap "found before a run."** *"`FASTEMBED_CACHE_PATH: ${{ runner.temp }}/…` in
   workflow- or job-level `env:` expands to `/fastembed_cache` and **nothing reports it** — fastembed
   falls back, `actions/cache` caches an empty directory, and every job re-downloads 64 MB while the
   workflow reads as correct."* The three artefacts now say the opposite (`check.yml:16-23`,
   `distribution.md:187-191`, `test_ci_workflow.py:265-268`: rejected at validation, no job starts,
   loud). This is the always-loaded file, so a fresh session reads the refuted mechanism first.
   **Fix:** strike the sentence in place with the correction beside it, and re-title "(a)": it was not
   a trap found, it was an unsourced claim a review round corrected — which is the more useful
   record, since "(b)" in the same paragraph *was* found by checking.

2. **[IMPROVEMENT] `if: always()` on the save, under `cancel-in-progress: true`, saves a partial
   model directory under a key that never refreshes.** `check.yml:36-38` cancels the in-flight run on
   every push to the same ref; `:123-128` and `:200-207` save under `if: always()`, which GitHub
   documents as running *even when cancelled* (the reason the docs recommend `!cancelled()` for
   cleanup). The download happens inside the gate step, and `huggingface_hub` writes blobs as
   `<blob>.incomplete` until each completes — so a cancel mid-fetch leaves a directory of complete and
   incomplete blobs, the save uploads it under `fastembed-0.8.0-bge-small-en-v1.5-<os>`, and because
   a cache saves only on a key miss (`check.yml:93-95` says so itself), that partial snapshot is what
   every later run restores until M30 changes the key. Each run then re-downloads the missing part;
   nothing fails; nothing reports it — the class the round-1 fix was made to remove, reintroduced by
   the fix. The combined action's `post-if: success()` could not do this. **Fix, preferred:** move the
   fetch out of the gate — a step after "Build the virtualenv" running
   `.venv/bin/python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5')"`
   (the default at `zikaron/core/config/keys.py:189-191`), then the save immediately after it with
   `if: steps.model-cache.outputs.cache-hit != 'true'` and **no** `always()`: a failed or cancelled
   fetch skips the save by default semantics, a completed one saves before the gate can go red, and
   the macOS advisory-red argument disappears because the cache no longer depends on the suite at all.
   Minimum: `if: ${{ !cancelled() }}`, which closes the cancel case but not a gate killed by
   `timeout 600` mid-download. Either way update `check.yml:82-87`, `distribution.md:192-196` and
   `test_the_model_cache_is_saved_even_when_the_job_is_red` (`:326-342`, which asserts `always()`
   literally). While there: `id: model-cache` (`:89`) is unused, the macOS restore has no `id` at all,
   and a save that runs on a restore *hit* tars and re-uploads 64 MB per job per run only to be told
   the key exists — the `cache-hit` gate fixes that too.

3. **[IMPROVEMENT] The documented command has still not been run in the configuration the
   recommendation exists for.** `research/python-portability-probes.md:262-268` measures `uv python
   find 3.12` (host) and `uv python find --managed-python --no-project 3.12` (refuses). `uv python
   find` never downloads by design, so "refuses" is what it says whether or not `uv tool install
   --managed-python` would then *fetch*. The claim at `README.md:113-114` ("The flag makes uv download
   a build that is known to work instead"), `distribution.md:89-90` and D36 (`overview.md:140`) is an
   inference from uv's `python-downloads` default, and it is very probably right — but round 1's own
   lesson, now written at probe note `:278-280`, is that a measurement under one command licenses no
   claim about another. One command closes it:
   `UV_PYTHON_INSTALL_DIR=<empty> UV_TOOL_DIR=<scratch> UV_TOOL_BIN_DIR=<scratch> uv tool install
   --managed-python <tree>`, recording that it downloaded and what `tools/zikaron/bin/python` resolves
   to; add the row to §6's table and cite it from README/§2. Also `distribution.md:86` quotes
   `uv python find --managed-python 3.12` where the probe ran it with `--no-project` as well —
   `check-matrix.sh:90-92` records that the two flags answer differently, so quote the command as run.

4. **[IMPROVEMENT] The scope test misses the one placement that is both wider than the matrix and
   plausible.** `test_ci_workflow.py:132-151` asserts the two names are absent at workflow and job
   level. A step-level `env:` on "Build the virtualenv" (`check.yml:98-101`) — exactly "applied to
   `pip install`, its PEP 517 backend and setuptools' editable build", the failure the docstring
   names — passes. **Fix:** in the same test, also assert that no *non-gate* step's `env` carries
   either name: `for step in _steps(job): if step is not gate: assert not (_REQUIRED_ENV.keys() &
   step.get("env", {}).keys())`.

5. **[IMPROVEMENT] Nothing asserts a restore step exists, or where the cache pair sits relative to
   the gate.** `_cache_steps` (`:93-94`) collects both halves; `test_the_restore_and_save_keys_match`
   passes with a save alone (one key); `test_the_exported_cache_directory_is_the_one_that_gets_cached`
   passes with a save alone; a restore placed *after* `./check.sh`, or a save placed *before* it,
   passes every test and caches nothing — a restore after the gate never feeds fastembed, a save
   before it uploads an empty directory (warning, not failure) on every run forever. The module
   docstring (`:15`) and `distribution.md:204-209` both claim step order is asserted; it is, for the
   export and the coreutils pair only. **Fix:** assert `any("cache/restore" in uses)`, and
   `index(restore) < index(gate) < index(save)` — or, under finding 2's restructure,
   `index(restore) < index(fetch) < index(save) < index(gate)`.

6. **[IMPROVEMENT] The family-3 guard will go red on M30's own deliverable, and nothing says so.**
   `tests/test_publication_hygiene.py:55-69` forbids 40- and 64-hex runs anywhere under `zikaron/`;
   `design/build-plan.md:3144-3160` and `:3236` have M30 pinning a **full 40-hex** HF revision and a
   **SHA256** allowlist in product code, with Zikaron owning the fetch and the verification. The next
   milestone's first green tree cannot exist without editing this guard, and the failure will read as
   a planted secret. **Fix:** name the collision in the module docstring now and choose the exemption
   shape before M30 needs it — a per-line marker (e.g. `# publication-hygiene: pinned-hash`) checked
   by `test_the_shipped_package_names_no_path_off_this_machine`, or a one-file allowlist for the
   module that will hold the pins, with a test that the allowlisted file exists and is the only one.

7. **[IMPROVEMENT] `design/README.md:7` and `:11` still say "the D1–D32 decision table", and
   `FINDINGS.md:1363-1365` says the range "is now simply not written anywhere."** `README.md:508`
   links a public reader to `design/README.md` first. `CLAUDE.md:32` and `FINDINGS.md:9` already
   carry the no-range convention. **Fix:** drop the range at both `design/README.md` sites, and
   narrow FINDINGS' universal to the two files it checked — or leave it and let this be its
   counterexample, but not both.

8. **[IMPROVEMENT] Two round-1 fixes were applied at one of their two cited sites.**
   (a) Finding 13 cited `distribution.md` **and** `build-plan.md:2811`; the brief reports "two-core
   runner replaced". `design/build-plan.md:2817` still reads *"a two-core runner is a different
   load."* (b) Finding 18's "zero matches … so nothing is preinstalled" inference stands in the hard
   form at `build-plan.md:2760-2761` while `check.yml:149-154` and `distribution.md:177-182` hedge it.
   The brief's header says `distribution.md` wins where they disagree, so neither is a contradiction
   of record — but a reported-complete fix that is half-applied is precisely the round-2 class the
   brief asked for. **Fix:** apply the same two rewordings at the two brief sites.

9. **[NITPICK] The flagless shorthand survives at four sites.** `FINDINGS.md:87` (the D36 index row:
   "Obtained by `uv tool install git+…`"), `FINDINGS.md:1433`, `build-plan.md:2521` and `:2808`
   (done-when 8: "`uv tool install git+…` as recommended"). D36 now calls the flag load-bearing and
   the README calls it "not optional"; the index row is the one that matters, being one line and
   always loaded. **Fix:** `uv tool install --managed-python git+…` in the index row; the brief sites
   can stay as an abbreviation or gain the flag, but done-when 8 describes the README and the README
   has changed.

10. **[NITPICK] Finding 3's new wording is supported, with one unit slightly off.** "GitHub refuses
    to start the job" (`distribution.md:189`) / "the job would not start" (`check.yml:20`,
    `test_ci_workflow.py:267`): a workflow that fails validation is rejected as a **run** — no job in
    the file starts, with the annotation *"Invalid workflow file … Unrecognized named-value:
    'runner'"*. That is documented behaviour and the right claim; it is still unobserved here, and §4
    already keeps a first-run record slot. **Fix:** "the run is refused at validation" at the three
    sites, and one clause saying it is documented rather than observed until the first push.

11. **[NITPICK] `README.md:131`** — `ZK=~/.local/share/uv/tools/zikaron/bin/python` is uv's default
    on both platforms but not under `UV_TOOL_DIR`; `ZK="$(uv tool dir)/zikaron/bin/python"` is exact
    everywhere and one character longer to explain.

12. **[NITPICK] `distribution.md:204-205` "every assertion is mutation-verified against a
    deliberately broken copy"** is a universal over a set that grew this round: the brief enumerates
    twelve mutations against nineteen test functions, and the six pre-existing ones (trigger branch,
    version list, summary step, `setup-uv` pin, moving refs, gate-not-copy) are not in that twelve.
    Either record the mutation per test in its docstring, or say "each assertion added in round 1 was".

13. **[NITPICK] Done-when 6 says the key is "on the model name and the `fastembed` pin"; the test
    ties half.** `test_the_cache_key_names_the_library_whose_pin_decides_the_download` (`:345-364`)
    reads the pin from `pyproject.toml`; the model name in the key (`bge-small-en-v1.5`) is a literal
    with no tie to `zikaron/core/config/keys.py:189-191`. A changed default would keep serving the
    old model from cache. **Fix:** read the default from `keys.py` in the test and assert its leaf is
    in the key.

VERDICT: NEEDS_CHANGES

## Round 3 — 2026-09-22

### Summary judgment

The tree is publishable in every respect but one sentence, and that sentence is in the normative
document. The restructured cache is correct GitHub Actions: `id: model-cache` is on the restore step
in both jobs (`check.yml:105`, `:207`), `steps.model-cache.outputs.cache-hit` is the restore action's
documented string output and `!= 'true'` handles both `'false'` and empty, an `if:` with no status
function gets the implicit `success()` so a failed or cancelled fetch really does skip the save, the
`restore`/`save` subpaths exist under the `v6` major the runner note verified on 2026-09-22, and the
order restore → venv → fetch → save → record → gate holds in both jobs. The public record —
`README.md`, `LICENSE`, `pyproject.toml`, D35/D36, `design/README.md` — is consistent with probe note
§6 and with itself. **But `design/distribution.md` §4's "what a job must carry" list still prescribes
`if: always()` on the save** — the form round 2 had removed and the test now forbids — in the one
document whose header says it wins every disagreement. Below that: two guard gaps of the class round 2
was about, a judgement on the family-3 collision (name it now, shape it in M30), and two nitpicks.

**Checked and clear, so nobody re-derives them.** `.git/HEAD` is `refs/heads/main` and the trigger
names `main`. `.git/config` carries only `[core]` — no remote — which matches done-when 10's "the
operator sets the remote". The two tests that commit set `user.email` themselves
(`test_knowledge_git.py`, `test_knowledge_scan_git.py`) and the third git test only runs `git init`,
so no job needs a git identity; no test runs git against the checkout, so `actions/checkout`'s default
shallow clone is safe. `check.sh` is bash-3.2-clean (no arrays; `pipefail` since 3.0), so whichever
`bash` the macOS runner resolves is fine. `test_the_cache_key_…` reading `pins["project"]["dependencies"]`
is what proves `[project.urls]` no longer swallows `dependencies`. The summary step's escaped backticks
are correct inside bash double quotes.

### Findings

1. **[BLOCKER] `design/distribution.md:202-206` prescribes the form the workflow no longer has and the
   test forbids.** *"**The cache split into restore and save, with `if: always()` on the save.**"*
   Neither save carries `always()` (`check.yml:128`, `:222`), the workflow's own comment at `:90-97`
   calls that form "worse", and `test_the_model_cache_is_filled_and_saved_before_the_gate_can_redden_it`
   (`test_ci_workflow.py:371-376`) asserts `"always()" not in condition`. Line 214 then says
   *"`tests/test_ci_workflow.py` asserts each of the above"* — for this bullet it asserts the
   opposite. This is round 2's finding 2 landing in the workflow and the test and not in the normative
   list beside them: the neighbour class the brief asked for, in the public document whose header says
   it wins. **Fix:** replace the bullet with the built shape — *"**The cache split into restore → an
   explicit fetch → save, all before the gate, the save gated on the restore's `cache-hit` and carrying
   no `always()`.** The combined action saves in a post step gated on job success, so the advisory-red
   macOS job would never write one. `always()` on a split save is worse: it runs on the cancelled path,
   `cancel-in-progress` cancels on every push to the same ref, and a cancel mid-fetch would upload
   `huggingface_hub`'s `.incomplete` blobs under a key that never refreshes. Hoisting the fetch into its
   own step means the save completes before anything can redden or be cancelled; the `cache-hit` gate
   skips a 64 MB re-upload on a hit."* The Linux first-green sentence can stay as a statement about the
   combined form. Then `grep -n "always()" design/*.md` — only the summary-step uses should remain.

2. **[IMPROVEMENT] The save's condition is not tied to the restore's `id`, and that is the one
   reference the brief asked to be checked.** `test_ci_workflow.py:377-380` asserts the substring
   `cache-hit` is in the condition. Rename `id: model-cache` on either restore (or drop it — the macOS
   restore had none until round 2) and `steps.model-cache.outputs.cache-hit` evaluates to the empty
   string, `'' != 'true'` is true, and the save runs on every hit: a 64 MB tar-and-upload per job per
   run, answered with *"cache already exists"* — a warning, never a failure. That is the silent-cost
   class the restructure exists to remove, and it passes every test today. **Fix:** in the same test,
   `referenced = re.search(r"steps\.([\w-]+)\.outputs\.cache-hit", condition)`; assert it matched and
   that `steps[restore].get("id") == referenced.group(1)`. Mutation: rename the restore's `id` in one job.

3. **[IMPROVEMENT] The fetch step's model literal is tied to nothing.** `check.yml:124` and `:219`
   fetch `'BAAI/bge-small-en-v1.5'` as a literal; the comment at `:121-123` says the drift test "ties
   that default to the cache key", which is true of the key (`test_ci_workflow.py:416-428`) and not of
   the fetch. A fetch edited to any other valid model id passes every test: the cache then holds the
   wrong model, the gate downloads the real one inside itself on every run, and `cache-hit` is `true`
   so the save never corrects it. **Fix:** one assertion — the step whose `run` contains
   `TextEmbedding(` must also contain `str(embed_model.default)` — in the cache-key test, which already
   has the default in hand. Mutation: change one fetch literal.

4. **[IMPROVEMENT] Round-2 finding 6 — the family-3 / M30 collision: name it in M28, shape it in
   M30.** The judgement the brief asked for, with the reason. The exemption *shape* depends on where
   M30 puts the pins (a module, a data file, one constant or several), which M28 cannot know, so
   choosing it now would be fixing a milestone by reasoning — M30's to solve. But the guard is M28's
   artefact and the red will be read in its own assertion text: *"the installed package must carry no
   machine-local path, private-project name, or credential-shaped value"* (`test_publication_hygiene.py:94-95`),
   against the reader's own pin. `build-plan.md` §M30 pins a full 40-hex revision and a SHA256 set in
   product code (`:3240`, `:3251`) and mentions the guard nowhere; the guard's docstring (`:17-26`)
   explains the family-2 omission at length and says nothing about family 3 colliding with the next
   milestone. **Fix:** one paragraph in the module docstring — *"M30 will put a 40-hex HF revision and
   64-hex SHA256s into product code. That is this guard going red by design, not a planted secret; M30
   chooses the exemption (a per-line marker or a one-file allowlist) once it knows where the pins
   live"* — and one clause in §M30's done-when 4 pointing back at the guard. Nothing in M28's fence
   changes and nothing about publication is wrong today, which is why this is not a blocker.

5. **[NITPICK] `FINDINGS.md:1258` and `:1260` carry the universal round 2 narrowed and a stale
   count.** *"16 assertions … **every one mutation-verified**"* against `distribution.md:215-218`, which
   now says *"Not 'every assertion'"*; and *"2,905 tests"* against the brief's 2,917. The brief says
   FINDINGS may stay messy, and it may — noted only because it is the always-loaded file and the
   universal is the one this trail just withdrew in the normative document. **Fix:** mirror the
   narrowing and drop both numbers, per the file's own no-tally rule.

6. **[NITPICK] The first run will print two cache warnings that read like a defect, and no comment
   says so.** The three linux matrix jobs share one key (`…-${{ runner.os }}` carries no Python
   version — correct, the model is interpreter-independent), so on the first run all three miss, all
   three fetch, all three attempt the save; the first wins and the other two log *"Unable to reserve
   cache … another job may be creating this cache"* — a warning, not a failure. Expected on the first
   push and after every key change. **Fix:** one sentence in the comment above the restore step
   (`check.yml:83-103`), so the first-run record in §4 does not spend a paragraph diagnosing it.

### Done-when 1–10

- **1, 2 — satisfied.** `LICENSE` is the verbatim MIT text with the operator's holder line;
  `pyproject.toml` carries `license = "MIT"`, `license-files`, no OSI classifier, `readme`,
  `[project.urls]` (placed after `dependencies`, and the test reading `project.dependencies` proves the
  placement), `version = "0.1.0"`; §3 states the scheme and the shape rule.
- **3 — satisfied**, subject to finding 1: `distribution.md` exists and is normative; D35/D36 are in
  `overview.md` §4 and match probe note §6; `FINDINGS.md:86-87`, `CLAUDE.md:49` and `design/README.md:22`
  carry the rows; the seven definition-of-done sites were grepped in round 1 and not re-derived here.
- **4, 5, 6 — satisfied as files; unverifiable as runs until the push.** Every clause of 4 is in the
  workflow (label `macos-15`, filters per job and scoped, versions tied to `check-matrix.sh`, uv
  recipe, both `timeout` halves plus the proof step); 5's summary step is `if: always()` and the UI
  record slot in §4 is empty by design; 6 is built beyond the brief (restore → fetch → save, key on
  model leaf and pin, both read from source) and needs finding 1 for the normative text to describe it.
- **7 — satisfied.** `research/publication-sweep.md` runs all four families with the unit stated first,
  classifies every family-3 value, probes liveness for the only class that could have been live, and
  records each decision with its reason; the guard covers the three families that have no permanent
  false-positive population in `zikaron/`.
- **8 — satisfied.** README carries both paths, the flag with its measured reason, the URL (knowable
  now that the remote is known), and the macOS caveat.
- **9 — half-evidenced.** The brief reports `./check.sh` green; it does not report
  `./check-matrix.sh --parallel` on the tree that lands, and `FINDINGS.md:1260` says that run waits for
  the reviewer. Any edit from this round re-owes it; it is satisfied when one run prints one identity
  for the tree the operator pushes.
- **10 — the operator's, and cannot be satisfied by a session.** No remote is configured; per the brief
  local `main` and remote `main` share no history, so the push is a reconcile the operator chooses plus
  a push; the milestone closes on the green run that produces §4's first-run record. Neither is a
  defect in the tree.

VERDICT: NEEDS_CHANGES
