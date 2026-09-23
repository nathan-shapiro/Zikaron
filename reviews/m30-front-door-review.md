# M30 — The front door, the model on disk, and the release — review

Artifact under review: the M30 working tree (new `zikaron/cli/`, `zikaron/doctor/`,
`core/indexing/{model_cache,model_pin,acquisition}.py`, `.github/workflows/release.yml`, five new test
files, and the changed modules, config, workflow and prose the brief lists). Normative brief:
`design/build-plan.md` §"M30 — The front door, the model on disk, and the release".

## Round 1 — 2026-09-23

### Summary judgment

The code is well shaped and most of it is exactly what the brief asked for: the umbrella dispatches
lazily, the resolver is pure and tested against the stated mutation, the acquisition path asserts
the *call sequence* on both mismatch branches rather than only the outcome, the warm start is
proved offline in a subprocess, and the publication guard's exemption is narrowed by a positive
check rather than trusted. Four things stop it shipping as-is: the distribution test is green on
this machine only because `setuptools==84.0.0` was hand-installed into `.venv` — the three matrix
venvs and CI's `uv venv --seed` carry no setuptools, so done-when 8 cannot currently hold;
`release.yml` pins `setup-uv` the way `check.yml` and its test say silently runs stale code, and
nothing tests `release.yml`; the knowledge CLI still prints a `python -m zikaron.knowledge` follow
line, which under the recommended install is the unreachable form this milestone exists to retire;
and `FINDINGS.md` still says `doctor` is next. Everything else is improvement-grade.

Done-when items, as verified against the tree rather than the brief: 1 met (umbrella; install
strings pinned by `tests/fixtures/kiro_artefacts.json` and `test_install_targets.py`; `name=value`
rendering asserted at `test_knowledge_cli.py:310` through `execute`'s `printer`); 2 met with one
gap in the `main`-level assertion (finding 12); 3 met (`test_indexing_encoder.py` §
`TestTheCacheDirectoryTheLoadPathHandsFastembed`, `test_indexing_model_cache.py`); 4 met (both
branches distinguishable by call sequence; `HF_HUB_OFFLINE=1` subprocess test; `huggingface_hub`
pinned, and `fastembed==0.8.0` accepts it — `Requires-Dist: huggingface-hub (>=0.20,<2.0)`); 5 met;
6 met only by machine state (finding 1); 7 met (key carries the revision, read from `pin_for`);
8 not evidenced in the brief and would be red (finding 1).

### Findings

1. **[BLOCKER] `test_distribution.py` passes here for a reason nothing in the repository
   provides, and is red on the matrix and in CI.** `tests/test_distribution.py:44–50` runs
   `python -m build --no-isolation`, and `build`'s own `__main__.py` (lines 151–156 of the installed
   1.3.0) checks `[build-system] requires` against the running environment unless
   `--skip-dependency-check` is passed, erroring `Missing dependencies: setuptools==84.0.0`. Nothing
   installs that: `[project.optional-dependencies] dev` does not list it, `check-matrix.sh:290/313`
   builds each venv with `-m venv` + `pip install -e '.[dev]'` (3.12+ `venv` seeds pip only), and
   `check.yml:132` uses `uv venv --seed`, which on 3.12+ also seeds pip only. Verified on disk:
   `.venv/…/setuptools-84.0.0.dist-info` exists; `.venv-matrix/3.13/…/site-packages/setuptools/`
   does not (its `pip/` does), nor does it in `.venv-matrix/3.12` or `3.14`. So the local gate is
   green because someone ran `pip install setuptools==84.0.0` into `.venv` by hand, and the brief
   does not claim the matrix ran — done-when 8 requires it. *Fix:* add `"setuptools==84.0.0"` to
   the `dev` extra with a one-line reason (`build --no-isolation` needs the backend in the venv), and
   add a test — `test_distribution.py` is the natural home — asserting the `dev` pin equals the
   `[build-system].requires` pin, so the two cannot drift. Then let the matrix rebuild its venvs
   (the stamp changes with `pyproject.toml`) and report the matrix result in the next round.

2. **[BLOCKER] `release.yml` pins its actions the way the corpus says fails silently, and no test
   reads it.** `.github/workflows/release.yml:35,37` use `actions/checkout@v6` and
   `astral-sh/setup-uv@v7`. `check.yml:56–63` and
   `tests/test_ci_workflow.py::test_setup_uv_is_pinned_to_a_full_version_rather_than_a_bare_major`
   state that `setup-uv` has no floating major tag, so a bare major "either fails to resolve or
   resolves to a frozen historical tag" — and `check.yml` itself uses `@v10.2.0` and `checkout@v7`.
   One of the two workflows is wrong by the project's own rule, and it is the one that holds the
   publishing credential. `test_ci_workflow.py:45` sets `_WORKFLOW` to `check.yml` alone, so the pin
   tests, the moving-ref test and the setup-python test all skip `release.yml`. *Fix:* pin
   `astral-sh/setup-uv@v10.2.0` and `actions/checkout@v7` in `release.yml`; make
   `test_setup_uv_is_pinned_to_a_full_version_rather_than_a_bare_major` and
   `test_no_action_is_pinned_to_a_moving_branch` iterate every file under `.github/workflows/`
   rather than the one module-scoped fixture. See finding 9 for `pypa/gh-action-pypi-publish@release/v1`,
   which the moving-ref test's suffix list (`@main/@master/@latest`) would not catch either.

3. **[BLOCKER] The knowledge CLI tells the user to run the form the milestone exists to retire.**
   `zikaron/knowledge/main.py:302` prints
   `follow    python -m zikaron.knowledge status <name>` after every `add`/`refresh`. Under
   `uv tool install`, the tool venv's interpreter is not on `PATH`, so a user who follows that line
   gets `No module named zikaron` from the system Python on the first corpus they ever build. The
   same stale form is the `name` help text at `zikaron/knowledge/indexer/main.py:34`. No test pins
   the current text (`grep 'follow  ' tests/` finds nothing), so the fix is unconstrained. *Fix:*
   thread `prog` from `main` to `_start_build` — simplest is `args.prog = prog` after parsing and
   `_start_build(name, store, full=..., prog=args.prog)` — and print
   `f"follow    {prog} status {shlex.quote(name)}"`; add a case in `test_knowledge_cli.py` driving
   `main([...], prog="zikaron knowledge")` and asserting the follow line starts with
   `zikaron knowledge status`, plus one for the `python -m` prog so both forms name themselves.

4. **[BLOCKER] `FINDINGS.md` is not current, in the section a fresh session resumes from.**
   `FINDINGS.md:75–93` is a six-step progress list in which step 4, `doctor`, is marked
   "**Next.**" while `zikaron/doctor/` exists and `README.md` §Verify quotes its output; steps 5–6
   carry no state at all. `CLAUDE.md` §"Project memory" makes currency the whole value of the file
   and says process narration ("Landed", "Next") goes nowhere. *Fix:* replace lines 75–93 with the
   landed state and what is still owed to someone else — e.g. "M30 is built: the `zikaron` umbrella,
   the durable per-user cache, the revision-and-digest pin, `doctor`, `release.yml`. **Owed to the
   operator before a release can happen**: the PyPI pending publisher and the `release` GitHub
   environment (`research/m30-operator-setup.md`), the first upload, and the Codecov token" — and
   delete the numbered list rather than re-marking it.

5. **[IMPROVEMENT] `acquisition.py`'s docstring claims a bound the code does not provide.**
   `zikaron/core/indexing/acquisition.py:19–21`: "a source serving the wrong bytes costs one extra
   64 MB and then stops, rather than costing one on every service start forever." `_REFETCHED` is a
   module-level set, so the bound is per *process*: every new service process finds the mismatching
   snapshot, is not in the set, spends one `force_download`, and fails — one 64 MB per service start
   until the pin changes, and the service is respawned by any client that finds the socket absent.
   `design/distribution.md:212` states it correctly ("one per process per artefact"); the brief's
   (iv) asked for exactly that. *Fix:* rewrite the sentence to the true bound — "so a source serving
   the wrong bytes costs one extra 64 MB per process rather than one per encoder construction; the
   failure then repeats on each service start until an upgrade carries a new pin". If the per-respawn
   cost is judged unacceptable, a marker file beside the snapshot (`<snapshot>/.zikaron-refetched`)
   would make the bound durable; that is a design choice the brief did not ask for, so name it
   rather than take it.

6. **[IMPROVEMENT] `model_pin.py` says `doctor` reports whether a store's model is pinned; it does
   not.** `zikaron/core/indexing/model_pin.py:21–24`: "`zikaron doctor` reports which of the two a
   store is in, so the weaker guarantee is visible rather than silent." `doctor/checks.py:196–206`
   iterates `PINNED_ARTIFACTS.values()` and never reads the `--project` store's configured
   `embedding.embed_model`; a user who set `embed_model = "some/other"` gets a green row about a
   pin they are not using and nothing about the one they are. *Fix, either:* delete the sentence
   (the cheaper true state); or add a `REPORTED` row that resolves
   `knowledge.scope.configuration(store_dir)`'s `embed_model` and prints "pinned at <rev>" or "not
   pinned by this release — fetched by fastembed at upstream head, unverified". If the row is added,
   `test_doctor.py` should drive it with an unpinned model in a project `config.toml`.

7. **[IMPROVEMENT] Two implementations of one verification predicate.** `doctor/checks.py:137–157`
   re-implements `acquisition._mismatched` with a `read_bytes()` digest — the whole-artefact-in-memory
   read `acquisition._HASH_BLOCK_BYTES` (line 31) explains avoiding — so `doctor`'s "5 files verified"
   and the service's refusal are separate walks that can disagree the day one of them changes.
   *Fix:* rename `acquisition._mismatched` to a public `mismatched_files(pin, directory)` and call it
   from `check_model_cache`; delete `checks._digest`.

8. **[IMPROVEMENT] An interrupted first download costs a full 64 MB re-fetch, not the remainder.**
   `huggingface_hub` symlinks each file into `snapshots/<sha>/` as it completes, so a Ctrl-C mid-way
   leaves a snapshot directory with some files present. `acquisition.artifact_directory:117–128`:
   the warm call returns that directory (commit hash, no tree cache → `_raise_if_incomplete_snapshot`
   returns), `_mismatched` counts the *absent* files as mismatches, and the code goes straight to
   `force_download=True`, which re-downloads all five files rather than the missing ones — while a
   plain online call would have filled only the gaps. *Fix:* have `_mismatched` return absent and
   wrong separately; when only absent files remain, make the plain online call and verify, and
   reserve `force_download` for a file whose digest is wrong. `doctor`'s detail should likewise say
   "missing" for an absent file rather than "do not match the pinned digests"; the remedy is the same.

9. **[IMPROVEMENT] The publishing job runs more third-party code than it needs to, on a mutable
   ref.** `release.yml:27–61` does checkout, `setup-uv`, `uv build` (setuptools and any build-time
   code from the tree) and `twine` inside the one job that holds `id-token: write`. The PyPA guide
   the operator-setup note cites recommends a `build` job with no OIDC permission that uploads
   `dist/` as an artifact, and a `publish` job that only downloads it and runs the publish action —
   the token-minting job then executes nothing but the publisher. `pypa/gh-action-pypi-publish@release/v1`
   is a branch and moves; the project's own moving-ref rule (`test_ci_workflow.py:540–549`) should
   apply to the credentialed workflow first. *Fix:* split the jobs; pin the publish action to a full
   commit SHA with a `# vX.Y.Z` comment; add `contents: read` explicitly to the job that checks out
   (with `permissions: {}` at the top, checkout currently relies on the repository being public).

10. **[IMPROVEMENT] The distribution test builds in the live tree, which the parallel matrix
    races on.** `test_distribution.py:44–50` passes `_ROOT` as the source directory; the sdist step
    rewrites `zikaron.egg-info/` at the project root, which `check-matrix.sh:307–310` identifies as
    the one directory three concurrent editable installs race on — and under `--parallel` three
    sessions reach this module-scoped fixture at about the same moment. *Fix:* build a copy —
    `shutil.copytree(_ROOT, tmp, ignore=shutil.ignore_patterns(".git", ".venv*", "build", "dist",
    "*.egg-info", ".zikaron", "__pycache__"))` — keeping `research/`, `reviews/`, `.kiro/` and the
    `FINDINGS*` files in the copy, since their exclusion is what the test proves.

11. **[IMPROVEMENT] A runtime-dependency enumeration is now incomplete.** `design/build-plan.md:2568`
    (M28 brief, decision 3): "Every runtime dependency is permissive — `aiosqlite` MIT, `sqlite-vec`
    MIT/Apache-2.0 dual, `fastembed` and `fastmcp` Apache-2.0". `huggingface_hub` (Apache-2.0) is a
    direct dependency since this milestone. *Fix:* append it with an M30 note, in the withdraw-style
    the corpus uses for a list that grew.

12. **[IMPROVEMENT] Two `doctor` tests depend on, or under-assert, the machine they run on.**
    `test_doctor.py:232–244` (`test_a_healthy_machine_exits_zero_and_prints_every_row`) calls `main`
    against the process environment, so it hashes whatever `~/.cache/zikaron/models` holds and fails
    if a developer's real cache is corrupt — a machine-state result — and its expected-row list omits
    "socket path". `test_a_failing_row_makes_the_exit_non_zero` (246–250) asserts the status but not
    that the remedy line reached stdout, which is the `main`-level half of done-when 2 ("produces the
    socket-path check's remedy line and a non-zero exit"). *Fix:* `monkeypatch.setenv(
    FASTEMBED_CACHE_VARIABLE, str(tmp_path))` in both; add `"socket path"` to the list; in the failing
    case capture stdout and assert `"remedy: "` and `"$XDG_RUNTIME_DIR"` appear.

13. **[IMPROVEMENT] The verified row does not say where the model is, so a silently ignored
    override stays silent.** `model_cache.py:15–19` ignores a relative `$FASTEMBED_CACHE_PATH` or
    `$XDG_CACHE_HOME` by design; `checks.py:152` names `cache_dir` only in the absent case, and the
    verified case (`:167`) names the revision alone. A user whose override did not take has no
    channel that shows the directory actually in use. *Fix:* `f"present at {pin.revision} under
    {cache_dir}, {len(pin.digests)} files verified"`.

14. **[NITPICK] `README.md:601`** "It checks the four things about this machine" — there are five
    checks and one report; the corpus's own rule is to delete the number. "It checks the things about
    this machine that can stop Zikaron working".

15. **[NITPICK] `README.md:364–372`** quotes `doctor` output that the program does not produce:
    `5239827884…` and `2eb0b9c2….sock` are hand-abbreviated where the code prints the full revision
    and the full socket path. Either quote verbatim or say the two values are shortened.

16. **[NITPICK] `README.md:732`** "The workflow in `.github/workflows/`" — there are two now; name
    `check.yml`.

17. **[NITPICK] `release.yml:44`** `uv run --no-project --with tomli` fetches a package from PyPI
    inside the credentialed job for something `tomllib` does on every interpreter this project
    supports. Use `python -c "import tomllib; …"`. Separately, the tag check assumes `v<version>`
    tags; nothing in `design/distribution.md` §3 or `README.md` states that convention.

18. **[NITPICK] `zikaron/cli/main.py:14–17`** says `doctor` survives "a missing `aiosqlite`", which
    is true today (the `checks.py` import chain is stdlib plus `core.errors`, `service.paths`,
    `service.security`, `service.asyncio_compat`), but `checks.py:115`'s bare `import sqlite_vec`
    raises a traceback if that package is absent — the shape the docstring says `doctor` exists to
    replace. Either catch `ImportError` into a failed finding with the same reinstall remedy, or
    narrow the claim.

VERDICT: NEEDS_CHANGES

## Round 2 — 2026-09-23

### Summary judgment

All four round-1 blockers are resolved in the tree, verified against the files rather than the
brief: `setuptools==84.0.0` is in the `dev` extra and tied to `[build-system].requires` by a test;
`release.yml` is an unprivileged `build` job plus a `publish` job holding only `id-token: write` and
running nothing but a SHA-pinned publisher, every `uses:` in both workflows is a full version, a bare
major or a commit, and both pin tests iterate every `*.yml` under `.github/workflows/`; the follow
line prints the `prog` it was run as under both invocations; `FINDINGS.md` §"Current state" carries
landed state and what the operator still owes. The acquisition path is now correct on every cell I
walked — warm-complete, absent, partial, partial-plus-wrong, wrong, source-wrong, and a second call
after a failure — and the `_Hub` stub's partial-snapshot behaviour matches the library's. Three
improvement-grade gaps remain, one of which is a round-1 finding the brief reports applied and is
not; the rest is nitpick-grade. Nothing blocks.

Done-when 1–7 met on the tree. Done-when 8 rests on the brief's report of a green matrix on rebuilt
venvs; I have no shell in this round and accept it as reported. Assumption stated: every claim below
about `huggingface_hub` internals is taken from the docstrings and the round-1 reading, not re-read
from the installed library.

### Findings

1. **[IMPROVEMENT] Round 1 finding 11 is reported applied and is not.** `design/build-plan.md:2568–2569`
   (M28 brief, decision 3) still reads "`aiosqlite` MIT, `sqlite-vec` MIT/Apache-2.0 dual, `fastembed`
   and `fastmcp` Apache-2.0"; `huggingface_hub` occurs in that file only from line 3245 onward, inside
   M30's own brief (`grep -in huggingface design/build-plan.md`). This round's brief says the
   enumeration "gained `huggingface_hub`". *Fix:* append, in the withdraw style decision 5 beside it
   uses, "— and, since M30, `huggingface_hub` Apache-2.0, direct rather than transitive (D19 as
   amended)". Worth saying once: a sweep's report of what it applied is a claim like any other, and
   this one would have been settled by the grep above.

2. **[IMPROVEMENT] The `ImportError` branch in `check_sqlite_vec` is the one failing row not reached by
   mutation.** `zikaron/doctor/checks.py:119–124` catches the absent package and returns the reinstall
   remedy; `tests/test_doctor.py` never takes that branch (`grep -n 'ImportError\|sys.modules'
   tests/test_doctor.py` is empty), against the file's own opening rule — "Every failing row is reached
   by mutation, not by inspection." The coverage floor at 95 absorbs the miss, which is why the gate
   did not say so. *Fix:* in `TestSqliteVecWillNotLoad` add
   ```python
   def test_an_absent_package_is_a_failure_with_the_reinstall_remedy(
       self, monkeypatch: pytest.MonkeyPatch
   ) -> None:
       monkeypatch.setitem(sys.modules, "sqlite_vec", None)
       finding = checks.check_sqlite_vec()
       assert finding.outcome is checks.Outcome.FAILED
       assert "not installed" in finding.detail
       assert finding.remedy is not None
       assert "reinstall" in finding.remedy
   ```
   `None` in `sys.modules` makes `import sqlite_vec` raise `ImportError`, the exact exception the
   branch catches, without touching the real package.

3. **[IMPROVEMENT] Verified-always is an unbudgeted per-start cost on the path M17 measured.**
   `acquisition.artifact_directory` (`zikaron/core/indexing/acquisition.py:149`) runs `verify` on
   every call, and `FastEmbedEncoder.load` (`encoder.py:246`) calls it once per service start and once
   per detached indexer start — so every start now SHA-256s 64 MB before fastembed opens the model.
   The only in-tree throughput figure is `research/knowledge-index-hash-timings.md:15`, in-process
   `hashlib.sha256` over 12.7 MB in 47.1 ms across 369 files, which puts one 64 MB file somewhere
   between 60 and 250 ms warm and more on a cold page cache — the reboot case the durable cache exists
   for. That is off the socket-bind path (`BackgroundLoadedEncoder` loads on a thread) but on the
   first-`surface` path `research/m17-cold-start-ab.md` reports at ~800 ms, and neither
   `design/distribution.md` §"Model acquisition" nor the M30 brief states the number. *Fix:* measure
   it once, warm and cold —
   `.venv/bin/python -c "import time;from zikaron.core.indexing import acquisition as a,model_pin as p,model_cache as c;pin=p.pin_for('BAAI/bge-small-en-v1.5');d=c.snapshot_dir(c.resolved_model_cache_dir(),repo_id=pin.repo_id,revision=pin.revision);t=time.perf_counter();a.verify(pin,d);print(round((time.perf_counter()-t)*1000),'ms')"`
   — and put both figures with that command beside the "verified always" sentence in §"Model
   acquisition", so that "a digest walk on every start rather than a marker file" is a decision with a
   number behind it. If the cold figure is a real share of first-surface latency, round 1 finding 5's
   marker-file alternative is the design change to weigh; the measurement decides whether it is worth
   weighing.

4. **[NITPICK] `tests/test_ci_workflow.py:51`** — `_WORKFLOW_FILES` globs `*.yml` only; GitHub reads
   `*.yaml` too, so a workflow added with the other extension is covered by neither pin test and the
   comment's "a third workflow is covered by existing" is false for it.
   `sorted([*d.glob("*.yml"), *d.glob("*.yaml")])`.

5. **[NITPICK] `.github/workflows/release.yml:48`** — the tag check runs the runner image's bare
   `python`, the one interpreter this corpus otherwise refuses to rely on (`check.yml` never invokes
   one). It works because `ubuntu-latest` ships a `python-is-python3` 3.12, and fails loudly on any
   image whose default lacks `tomllib`; loud is fine, but `uv run --no-project python -c '…'` resolves
   the same interpreter `uv build` uses two steps later and removes the dependency on the image.

6. **[NITPICK] `design/distribution.md:150–152`** — "`zikaron/knowledge/indexer/` likewise has none"
   attaches to "no `python -m` form" from the previous sentence, and that is false:
   `zikaron/knowledge/indexer/__main__.py` exists and `indexer/main.py:29` prints
   `python -m zikaron.knowledge.indexer` as its `prog`. What the indexer lacks is an umbrella
   subcommand. "and `zikaron/knowledge/indexer/` has the `python -m` form *only*".

7. **[NITPICK] `zikaron/core/indexing/acquisition.py:19`** — "A second mismatch is a failure, never
   another download" is wider than the code. For a file absent because the source does not serve it, a
   second call in the same process still makes the plain online fill call (`:157–159`) before reaching
   the `_REFETCHED` check; it transfers nothing new but it is a network round-trip, and
   `test_a_second_call_after_a_failure_downloads_nothing` covers only the present-and-wrong case.
   "never another *forced* download" is the sentence the code supports.

8. **[NITPICK] `tests/test_ci_workflow.py:562–563`** — the docstring says the bare-major exemption is
   for "a first-party action", but the regex exempts a bare major on any action;
   `codecov/codecov-action@v6` passes it. Either enforce (`use.startswith("actions/")` on the
   bare-major arm) or drop "first-party".

9. **[NITPICK] `.github/workflows/check.yml:125–126`** — "`fastembed` stays in the key because it
   decides which files are wanted" was true before M30; now `allow_patterns=pin.filenames` decides and
   fastembed fetches nothing. The over-keying is harmless; the stated reason is stale. Either drop
   `fastembed` from the key and the `version in key` assertion in
   `test_the_cache_key_names_the_library_whose_pin_decides_the_download` (the M30 brief's item 7
   permits exactly that), or restate the reason as the one that holds: the five-file list was measured
   against what this fastembed version loads.

10. **[NITPICK] `tests/test_distribution.py:42`** —
    `test_the_build_backend_is_installed_at_the_version_the_backend_pin_names` asserts the `dev`
    declaration, not what is installed; the `built` fixture is what fails on a wrong installed version.
    Rename to `…is_declared_in_the_dev_extra_at_the_version…`, or add
    `assert importlib.metadata.version("setuptools") == backend.split("==")[1]` so the name is true.

VERDICT: NEEDS_CHANGES

## Round 3 — 2026-09-23

### Summary judgment

The five round-2 items are applied in the tree, each verified against the file rather than the brief:
`build-plan.md:2568–2570` carries `huggingface_hub` in decision 3; `test_doctor.py:128–140` reaches
the `ImportError` branch through `sys.modules`; `test_ci_workflow.py:53–57` globs both extensions
and both pin tests parametrize over it; `release.yml:50` runs the tag check through `uv run
--no-project`; and `distribution.md:221–236` now states the per-start verification cost with a
measurement and a re-derive command. `FINDINGS.md` §"Current state" is current. What stops this
round approving is the one thing the brief asked me to check: the characterisation of the
verification cost is right about the *mechanism* — it lengthens the wait a first `surface` already
makes — and wrong about the *reference*. That wait sits against `push.py`'s fixed 2.0 s budget, the
corpus sized M17's margin against a ~300 ms action threshold, the warm figure alone spends most of
that margin, and the condition under which the M17 defect actually reproduced — load — is exactly
the cell left unmeasured. The instrument that settles it is in the tree and re-runnable. The rest is
improvement- and nitpick-grade.

Round-2 nitpicks 6–10 were not in the brief's applied list and are unchanged in the tree; they are
not re-lodged. Assumption stated: no intentional list was included in this round's brief, so I have
treated the prior rounds' scope as it stood.

### Findings

1. **[BLOCKER] The cost is stated as a share of the wrong quantity, and the quantity the corpus
   sized this by is unmeasured.** `design/distribution.md:226–230` frames ~185 ms as a share of
   first-`surface` latency and concludes "a lengthening of that one wait rather than a new one".
   Mechanically that is right — `FastEmbedEncoder.load` (`encoder.py:246`) runs
   `artifact_directory` on the loader thread, and the first `surface` blocks in `_resolved()` on the
   same `_loaded` event it always did. But the wait is not open-ended: `push.py:40` hands the
   `surface` request whatever is left of `_DEADLINE_SECONDS = 2.0` as a socket timeout (`:90–93`),
   and a request that outlives it lands in `except Exception` → `_degrade(hook_log_path,
   "transport")` (`:99–106`) — the exact signature M17 was built to end
   (`research/m17-cold-start-ab.md:36–37`). The corpus already sized this wait against that budget:
   `build-plan.md:873–885` (M17 fact 2) puts the answer at "~1.5–1.6 s into the 2.0 s budget…
   roughly 400–500 ms to spare", says "the margin has to be measured end to end, not at the socket",
   and `:1060–1061` names "under ~300 ms" as "the threshold worth acting on". Add the warm figure
   and that spare is ~215–315 ms — straddling the corpus's own threshold — on an idle machine with a
   warm page cache. Under load, where M17's defect reproduced 5/5 and the live arm answered `surface`
   at 1348 ms (1128–1428), hashing slows as well, and the paragraph measures nothing there; on M17's
   measured upper bound the spare is already under ~400 ms before any load penalty on the hash.
   *Fix:* measure the quantity rather than derive the share. `experiments/m17_cold_start_ab.py` is
   re-runnable as it stands — `.venv/bin/python experiments/m17_cold_start_ab.py m30 [runs]`,
   against the `.zikaron/` store this repository still has — and prints `surface` from spawn and
   "surface inside the hook budget: N/runs" read from `push._DEADLINE_SECONDS`. Run it idle and
   under the same synthetic load M17 used (`experiments/m17_hook_outcome.sh` reproduces the
   condition), put the `surface` range and the in-budget count into §"Model acquisition" in place of
   the derived-share sentence, state the remaining margin against 2.0 s in ms, and name the two
   levers if it is under ~300 ms: the split connect deadline `build-plan.md:1054–1061` kept on the
   shelf for exactly this, and the marker file the paragraph already names. If the run cannot happen
   before the PR, the measurement belongs in `FINDINGS.md` §"Owed measurements" with that command,
   and the paragraph should say the margin is unmeasured rather than that the share is
   "meaningful".

2. **[IMPROVEMENT] Three sentences in the same paragraph are inaccurate as written.**
   (a) `distribution.md:227–229` "**809–827 ms idle and 1215–1348 ms under load**" blends the two
   M17 arms: 827 and 1215 are the *old* eager-load arm (`research/m17-cold-start-ab.md:23,30`), which
   no longer exists. The live arm's own figures are 809 ms (801–821) idle and 1348 ms (1128–1428)
   under load (`:24,31`); cite those, with their ranges, since the range is what finding 1 divides
   into. (b) `:229` "the share is meaningful idle and smaller under the load case" divides an idle,
   warm hash figure by a loaded-machine denominator; the hash is CPU-bound and slows under the same
   load, so "smaller" is not established. Delete it or measure it. (c) `:226` "It is **off** the
   socket-bind path, since `BackgroundLoadedEncoder` loads on a thread" holds on the open path only.
   On the create path — the first start of a store — `context.py:246` blocks on
   `loading.artifact()` before `assemble` returns, so the bind waits on the load and verification is
   *on* the 1.2 s poll deadline there (`build-plan.md:847`: create-path `assemble` ~847 ms before
   M30). The consequence in that cell is a `hook.log` line and the degrade relay on a first message
   that had no memories to lose, so it is a truth fix rather than a cost one, but the sentence
   should say "on the open path; the create path already blocks the bind on the load, and now on
   this too".

3. **[IMPROVEMENT] The cold-cache reopener names the wrong quantity, and the right one is measurable
   without root.** `distribution.md:223–224,235–236` make verify's own cold duration the number that
   would reopen the decision. That is not the delta to first `surface`: `TextEmbedding` reads the
   same 64 MB immediately afterwards (onnxruntime parses the whole file), so the disk read verify
   pays on a cold cache is one the load then finds in the page cache, and the cold *delta* is
   approximately the hash compute — the warm figure — unless something evicts 64 MB between the two
   reads. State that, and give a re-derive that does not need `drop_caches`: on Linux,
   `os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)` on each pinned file (opened through the
   snapshot symlink, so the blob is what is evicted) drops its clean pages; then time
   `FastEmbedEncoder.load` after that eviction with the pin in place, and again with `pin_for`
   monkeypatched to `None` after the same eviction — the difference is the cold delta. Note that
   `posix_fadvise` is absent on macOS, so the figure is Linux-only.

4. **[NITPICK] `.github/workflows/release.yml:46–48`** — "so it is the same interpreter `uv build`
   uses two steps down" is not what `--no-project` guarantees: it makes `uv run` ignore
   `pyproject.toml`, `requires-python` included, so it takes the first interpreter uv discovers while
   `uv build` honours `>=3.12` and may pick or download another. On `ubuntu-latest` both are the
   image's 3.12 today, so it works; the reason is wrong. Either add `--python '>=3.12'` or remove
   Python from the check altogether with `declared="$(uv version --short)"` (`uv version` has read
   `[project].version` since 0.7; `setup-uv@v10.2.0` installs latest by default).

5. **[NITPICK] `README.md:36–38`** — "verified against a SHA256 set it ships, which it repeats only
   if the cache it lands in is cleared": the nearest antecedent of "which" is the verification, which
   runs on every start, and the download also repeats once on a mismatch (`:187` says so). "a
   download it repeats only if the cache is cleared or a file in it fails verification".

6. **[NITPICK] `design/distribution.md:221–222`** — "on this machine" names neither the platform nor
   the load condition, where the corpus's other timing notes do (`research/m17-cold-start-ab.md:8,19`:
   "12-core machine", "load1 0.55–1.10"). macOS is the other supported platform and its `~/Library/
   Caches` sits on APFS; say Linux, the core count and the idle load, so a macOS re-derive is
   comparable.

VERDICT: NEEDS_CHANGES

## Round 4 — 2026-09-23

### Summary judgment

Five of the six round-3 items are applied in the tree, each verified against the file: the blended
M17 figures and the "smaller under load" sentence are gone (`distribution.md:224–242`), the create
path is stated (`:249–252`), the cold-cache paragraph now names the delta rather than the walk
(`:244–247`), the README's dangling "which" is two sentences naming both repeat conditions
(`README.md:36–39`), and the measurement names platform, cores and load. The blocker was answered
the right way — the M17 instrument, seven timed runs after a discarded warm-up, in-budget counts read
from the shipped constants, a re-derive command — and the harness edit that made it runnable is
correct (`memory_surface` is the method `hook/rpc.py:55` sends). What stops approval is the
paragraph written *around* the measurement: it calls `load1 5.75` "the demanding cell" and 1481 ms
"an *upper* bound on `surface`", and says the decision "rests on the worse of the two", when the
corpus's own M17 load cell — `load1 7.0–8.9`, one table below the idle baseline the paragraph cites
— answered `surface` at up to 1428 ms *before* the ~185 ms walk existed, and is the condition at
which the defect this budget prevents reproduced 5/5. A normative document now founds a design
decision on a bound its own evidence falsifies. That is minutes to fix either way — measure the
cell, or say it is unmeasured — and one round-3 item the brief reports applied is unchanged in the
tree.

### Findings

1. **[BLOCKER] "Upper bound" and "the demanding cell" are false against M17's own load table, and
   the decision is stated as resting on them.** `design/distribution.md:225–226` ("heavier than the
   idle `0.55–1.10` M17's own baseline was taken at, so this is the demanding cell rather than the
   easy one"), `:239–242` ("1481 ms is an *upper* bound on `surface` and 505 ms a *lower* bound on
   the margin … the decision below rests on the worse of the two"), `:257` ("At ≥505 ms of measured
   margin that trade is not worth making"). The comparison is made against M17's *idle* row only.
   `research/m17-cold-start-ab.md:26–31` has the other row: the live arm at `load1 7.0–8.9`
   answered `surface` at 1348 ms (1128–1428), and `:33–45` is where the hook's degrade reproduced
   5/5 at `load1 8.89`. So before M30 added anything, the corpus had already measured a `surface`
   *above* the figure now called an upper bound, at the load where the failure lives; `load1 5.75`
   sits between the two cells and bounds neither. What would make "upper bound" true is that no
   user's machine exceeds `load1 5.75` on 12 cores, and the corpus's own reproduction of the defect
   is the counterexample. (The socket row says the same thing from the other side: 419 ms at
   `load1 5.75` against M17's 395 ms at `7.0–8.9` — `load1` alone does not order these conditions,
   and finding 5 asks for the load *source* for that reason.) Two acceptable resolutions:
   *(a) Measure the cell.* Reproduce M17's condition — the note records "8 busy loops on 12 cores"
   (`:66`) but no command; `for i in $(seq 8); do (while :; do :; done) & done` is one, `kill
   $(jobs -p)` afterwards — confirm `load1 ≥ 7` from `/proc/loadavg`, then
   `.venv/bin/python experiments/m17_cold_start_ab.py m30-verify-load 7` **and**
   `experiments/m17_hook_outcome.sh 5`. The second is not optional: it runs the shipped hook end to
   end, whose own setup, first failed `connect()`, spawn and identity check sit inside
   `_DEADLINE_SECONDS` and outside what the timing harness clocks, so the harness's 505 ms is an
   overstatement of the hook's spare by that much. Add the rows to the table, restate the spare as
   the worst run across both cells, delete the "Read these as bounds" paragraph, and let `:257`
   quote the smaller number. If the outcome run is 5/5 and the worst-run spare is still above
   ~300 ms, the marker-file decision stands on the right evidence.
   *(b) Restate.* Delete `:239–242`; replace `:226`'s "so this is the demanding cell rather than the
   easy one" with "and lighter than the `load1 7.0–8.9` at which M17's defect reproduced — that cell
   is unmeasured since verification was added, and is where the margin is narrowest: M17's live arm
   answered `surface` at up to 1428 ms there before the walk existed"; change `:257` to "At ≥505 ms
   of margin measured at `load1 5.75`"; and add to `FINDINGS.md` §"Owed measurements": "**The
   post-M30 hook margin at M17's load cell is unmeasured.** Quantity: worst-run `surface` from spawn
   against `push._DEADLINE_SECONDS`, and the in-budget count, at `load1 ≥ 7` on this machine;
   command in `design/distribution.md` §"Model acquisition"."

2. **[IMPROVEMENT] Round-3 finding 4 is reported applied and is not.**
   `.github/workflows/release.yml:46–48` still reads "Run through `uv` rather than the image's bare
   `python`, so it is the same interpreter `uv build` uses two steps down", and `:50` is still
   `uv run --no-project python -c …` with no `--python`. `--no-project` makes `uv run` ignore
   `pyproject.toml`, `requires-python` included, so it takes the first interpreter uv discovers;
   `uv build` honours `>=3.12` and may resolve or download another. "Two steps down" is also off —
   the build is the *next* step (`:57`). *Fix, either:* `uv run --no-project --python '>=3.12'
   python -c …` and rewrite the comment to what that buys ("an interpreter satisfying the same
   `requires-python` `uv build` honours, rather than whatever the image aliases"); or replace the
   whole check with `declared="$(uv version --short)"` and delete the `tomllib` sentence. This is
   the second time in this trail that a brief's applied list has not matched the tree (round 2
   finding 1); `git diff HEAD -- <file>` on each file the brief names is the cheap check before
   spawning a round.

3. **[IMPROVEMENT] The reopener is a count that cannot fire until the defect is back.**
   `design/distribution.md:257–259`: "The figure to watch is the in-budget count above; if it ever
   drops below 7/7". A run leaves that count only when `surface` outlives 2000 ms — the hook has
   already degraded, which *is* M17's production failure returning — so the trigger fires after the
   harm. The corpus already names the leading indicator: `design/build-plan.md:1060–1061`, "under
   ~300 ms is the threshold worth acting on", and the paragraph cites that same section for the
   lever. Separately, 7/7 has little power as a detector: at a true per-start degrade rate of 5% the
   chance of still seeing 7/7 is 0.95⁷ ≈ 0.70, at 10% it is ≈ 0.48. *Fix:* "The figure to watch is
   the worst-run spare against 2.0 s: under ~300 ms (`design/build-plan.md` §M17's own threshold) is
   when to weigh the two levers; a run outside the budget at all is the floor, not the trigger."

4. **[NITPICK] Two words in the create-path sentence.** `design/distribution.md:250–251` "awaits
   `loading.artifact()` before `Store.create` returns" — `context.py:246–247` awaits it and only
   then *calls* `Store.create`; "before `Store.create` is even called" is the precise statement and
   the sharper point. And `:252` "That cell costs a `hook.log` line" understates it: `push._degrade`
   also returns the relay instruction on stdout, so the model tells the user the memory hook failed
   on the first message a new store ever sees — the "stranger's first ten minutes" the M30 brief
   opens with (`build-plan.md:3173`). "costs a `hook.log` line and the relay instruction, on a first
   message that had no memories to lose".

5. **[NITPICK] The measurement has no `research/` note.** `design/distribution.md:224–247` is its
   only record: median/min/max with no per-run lines, no statement of what was loading the machine
   (the brief says `./check.sh` was running — pytest with real fastembed loads and subprocess spawns
   is a specific mix, and M17's note records its own at `:66`), and the warm walk figures at `:244`
   have no home either. `CLAUDE.md`: "`research/` measured results". *Fix:* `research/m30-verify-
   cost.md` with the harness output verbatim, the load source, the walk figures and the command
   that produced them (round 2 finding 3), and one line on the `memory_surface` re-point;
   `distribution.md` keeps the table and cites the note the way §2's `uv` table cites its probe note.

VERDICT: NEEDS_CHANGES

## Round 5 — 2026-09-23

### Summary judgment

The round-4 blocker was answered the right way and the answer changed the product: the A/B is
properly controlled (a `sitecustomize` shim, alternating arms, one load source, both harnesses), the
attribution to the acquisition path is sound (`socket`/`health` flat across arms), and the fix —
`missing_files` on a warm start, `verify` only where bytes arrive — is the correct shape and is
tested by call sequence. `research/m30-verify-cost.md` is the note round 4 asked for. Round-4 items
2–5 are applied in the tree, each verified against the file. What stops approval is that the
decision moved a guarantee and two things did not move with it. First, the argument the brief asked
me to check — that `_abandon` closes "the one case" where a warm start would trust known-bad bytes —
is sound as far as it goes and incomplete: read against the installed `huggingface_hub`, the forced
re-fetch itself is a second such case, open for the whole duration of a 64 MB download, and it
closes with a two-line reorder in the same function. Second, `doctor` is now the designated channel
for post-acquisition corruption, and its shipped remedy tells the user to do the one thing that no
longer repairs anything, then misdiagnoses the fault as upstream on the second run — the exact
diagnosis swap the module docstring was written to prevent, now delivered by the product's own
advice. Both are small; both are in the guarantee the pin exists for. Below those, the change
removed the gate's only verification of the digest table without noticing, and a handful of
sentences in the changed module and the normative prose still describe verify-always.

Assumptions stated: no shell this round, so `./check.sh` and the matrix are taken as not yet run
(the brief says so); every `huggingface_hub` claim below is read from the installed 1.26.0 source at
the cited lines rather than from the corpus's summary of it.

### Findings

1. **[BLOCKER] The forced re-fetch is a second window in which a warm start trusts proven-wrong
   bytes, and it is open for the whole download.** `acquisition.py:205–218`: after `verify` finds a
   mismatch, the snapshot directory is left *complete* while `force_download=True` runs, and only
   removed if the re-fetch also fails. Read the library: `file_download.py:1189` skips the
   pointer-exists shortcut under `force_download`; `:1241–1253` downloads to `blobs/<etag>.incomplete`
   and atomically moves it over the blob; `:1254–1255` creates the pointer *only if it does not
   already exist*. So for the entire re-download every one of the five pointers is present and
   resolves to a complete blob, and the blob still holds the bytes this process just proved wrong
   until the move lands. Kill the process anywhere in that window — Ctrl-C on a slow link, a lid
   close, a `kill` of a service that looks hung — and the next start sees five files present,
   `missing_files` returns `()`, and fastembed loads them. In the wrong-source case that is the
   supply-chain threat the pin was built for passing silently and permanently, with `BAD_CONFIG`
   never raised. (A second consequence of `:1254`: if the server's etag differs from the on-disk
   blob's, the forced download lands at a new blob and the old pointer is never re-pointed, so
   `verify` re-reads the old bytes and the re-fetch cannot succeed at all.) `_abandon`'s docstring
   (`:141–143`) and `distribution.md:249–251` both call the post-failure case "the one case"; it is
   not. *Fix:* discard **before** the forced re-fetch as well as after — the invariant is that no
   complete snapshot this process knows to be wrong exists at any instant:
   ```python
   checked = verify(pin, directory)
   if checked.complete():
       return directory
   _discard(directory)                       # the rmtree, factored out of _abandon
   claim = f"{pin.repo_id}@{pin.revision}"
   if claim in _REFETCHED:
       raise _mismatch_failure(pin, checked)
   _REFETCHED.add(claim)
   directory = _snapshot(pin, cache_dir=cache_dir, local_files_only=False, force_download=True)
   checked = verify(pin, directory)
   if not checked.complete():
       _discard(directory)
       raise _mismatch_failure(pin, checked)
   return directory
   ```
   With the directory gone, `:1254` creates every pointer fresh (which also removes the etag-change
   defect), and an interruption leaves a *partial* directory — pointers only for files whose blob
   already moved — which `missing_files` or `IncompleteSnapshotError` routes down the verifying
   path. No `try/finally` is needed because the discard precedes the call. Add to `_Hub` a
   `raise_on_forced_fetch: BaseException | None` knob honoured before it writes, and a test in
   `TestAFailedAcquisitionLeavesNothingToTrust`: `hub.serving["tokenizer.json"] = b"damaged"`,
   `hub.raise_on_forced_fetch = KeyboardInterrupt()`, `with pytest.raises(KeyboardInterrupt):
   _fetch(...)`, then `assert acquisition.missing_files(_PIN, hub.snapshot)` — the property a warm
   start checks, asserted directly. Rewrite `_abandon`'s second paragraph and `distribution.md:249`
   to say "at no point does a complete snapshot this process has proved wrong exist" rather than
   naming one case.

2. **[BLOCKER] `doctor`'s remedy for a mismatched file cannot repair it and misdiagnoses on the
   second run.** `checks.py:165–168`: "start the service, which completes or re-fetches these files
   once on its own; if it reports the same fault again the source is serving something else … Do
   not delete the files by hand: a snapshot entry is a symlink into a shared blob, so removing it
   re-links the same bytes." Trace it against the new `artifact_directory` for the `wrong` case —
   a present file with bad bytes, which is precisely the corruption the design now says `doctor`
   is the channel for (`distribution.md:244–247`): start the service → warm call returns the
   directory → `missing_files` is empty (`:201`) → the corrupt file is used and nothing is
   fetched. `doctor` again: same fault. The remedy's second sentence then tells a user whose disk
   is bad that upstream is serving something else — the diagnosis swap `acquisition.py:26–31`
   exists to prevent. And the third sentence forbids the action that now *works*: unlink the
   pointer → `missing_files` names it → the fill re-links the same blob (`file_download.py:1233–
   1237`) → `verify` at `:206` catches it → `force_download` replaces it. The re-link is real and
   harmless now, because the fill is verified; that was not true when the sentence was written.
   `test_doctor.py:188–194` (`test_the_remedy_does_not_tell_anyone_to_delete_the_files`) pins the
   wrong advice, and `distribution.md:219` ("`doctor`'s remedy says so explicitly") cites it as
   design. *Fix:* the remedy for a `wrong` file names the directory the product's own repair
   removes — `f"remove {snapshot} and start the service, which re-acquires and verifies; if it
   then refuses naming the same file, the source is serving something else and upgrading zikaron
   is what carries a new pin"` — and "start the service, which fills them on its own" for an
   `absent`-only fault. Invert the test: assert `str(snapshot)` appears in the `wrong` remedy and
   `"remove"` does not appear in the absent-only one. Then finding 5 withdraws the doctrine
   sentences the old remedy rested on.

3. **[IMPROVEMENT] The change removed the gate's only verification of the digest table, and
   nothing noticed.** Before this round, `check.yml:135–145` ("Fetch the embedding model" via
   `FastEmbedEncoder.load`) hashed the five files against `model_pin.py` on every CI run, cache
   hit or miss; so did every local start. Now a hit is five `stat`s. The cache key carries the
   revision, so a revision bump misses and verifies — but a digest edited wrongly at the same
   revision is green in CI and green locally on every warm cache, and is discovered by the first
   stranger's cold fetch as `BAD_CONFIG … upgrade zikaron`. That is the proposition the old design
   licensed and the new one does not: "the gate proves the pin names the bytes". *Fix:* one step
   after the fetch in both `check.yml` jobs —
   `.venv/bin/python -c "from zikaron.core.indexing import acquisition as a, model_cache as c, model_pin as p; pin = p.pin_for('BAAI/bge-small-en-v1.5'); v = a.verify(pin, c.snapshot_dir(c.resolved_model_cache_dir(), repo_id=pin.repo_id, revision=pin.revision)); assert v.complete(), v"`
   — or `.venv/bin/zikaron doctor --project .` if a non-zero exit on the socket row is acceptable
   on the macOS runner; ~200 ms either way. Add the step's presence to `test_ci_workflow.py`
   beside the cache-key assertions, and one sentence at `distribution.md:221` saying where the
   table is now proved against real bytes, since the paragraph above it no longer implies it.

4. **[IMPROVEMENT] Three sentences in `acquisition.py` still describe verify-always or contradict
   `_abandon`.** (a) `:174`, the docstring of the very function that changed: "fetched if absent
   and verified always" — now "fetched if absent, and verified whenever it was fetched". (b)
   `:26` "nothing here deletes anything" is flatly false since `_abandon` (and `_discard`, after
   finding 1); `_abandon`'s docstring argues against a narrower claim than the one the module
   makes. Narrow the module's: "nothing here deletes a file in order to *repair* it — the one
   removal is of a snapshot already proved wrong, and it fetches nothing". (c) `Verification`'s
   docstring `:71–74` gives as the reason for the absent/wrong split that "a plain online call
   fills only the gaps … Collapsing the two would make a Ctrl-C during the first fetch cost all
   five files again" — but `verify` no longer drives the fill decision; `missing_files` does, and
   after a fill an `absent` result goes straight to `force_download` (`:211–214`). The split's
   live reason is `doctor`'s two-part detail (`checks.py:157–161`) and the two remedies finding 2
   gives them. Say that.

5. **[IMPROVEMENT] Normative prose still carries the doctrine the code withdrew, and one pointer
   points the wrong way.** `distribution.md:215` "**Nothing deletes anything.**" is contradicted by
   `:249` in the same section; `:252` "the delete this document rules out *below*" — that
   paragraph is above. `build-plan.md:3252–3253` "verified before use", `:3293` "the allowlist
   verifies whichever returned", `:3297` "nothing of ours deletes anything" all describe the
   pre-decision design in the milestone's normative brief. `CLAUDE.md` §"Withdraw a refuted
   claim in place" governs `design/`. *Fix:* `distribution.md:215` → "**Nothing deletes a file to
   repair it.**" and `:252` "above"; in the brief, one *(Narrowed in the build: …)* note in the
   style `:3304–3309` already uses, after (iv), saying verification moved to the acquisition paths
   on the measurement in §"Model acquisition" and that a failed acquisition discards its snapshot.

6. **[IMPROVEMENT] The reopener names a lever the decision already spent and a threshold the
   baseline already breaches at the measured load.** `distribution.md:256–260`: "under ~300 ms is
   the threshold worth acting on … The levers … the split connect deadline … and a marker file
   recording verification." A marker file existed to skip hashing on warm starts; warm starts no
   longer hash, so that lever is gone. And on this round's own numbers the fixed tree's worst run
   is 1786 ms (spare 214 ms) and the *no-pin control's* worst is 1914 ms (spare 86 ms) — both
   under 300 ms at `load1` 9–12, where M17's threshold was sized at `0.55–1.10` and `7.0–8.9`. As
   written, the trigger has already fired for the pre-M30 tree. *Fix:* delete the marker-file
   lever; state the threshold with its load cell ("under ~300 ms *at M17's load cell*,
   `load1 7–9` on 12 cores; heavier load moves the baseline too, so compare against the no-pin
   control from `research/m30-verify-cost.md` rather than against the constant").

7. **[IMPROVEMENT] `FINDINGS.md:113–118` is the class `CLAUDE.md` §"Project memory" sends
   nowhere.** "That is how the above nearly shipped" is an account of a near-mistake; "the first
   of those had rotted unnoticed … because `experiments/` is outside the gate" is how a defect was
   found. The rule — never size a CPU-bound cost from an idle in-process timing — has become a
   rule, so it belongs in `CLAUDE.md` §"Measure before you assert" as one sentence ("A CPU-bound
   cost is sized under the load its budget was set for; an idle timing understated this one by
   2×") and nowhere else. What stays in `FINDINGS.md` is the instrument: "the cold-start budget is
   re-measured with `experiments/m17_cold_start_ab.py` and `experiments/m17_hook_outcome.sh` under
   generated load; `research/m30-verify-cost.md` §Re-deriving has the commands" — which is already
   half of the paragraph above it at `:102–111`.

8. **[IMPROVEMENT] Nothing routes a user to the channel the design moved the guarantee to.**
   `distribution.md:244–247` and `acquisition.py:12–15`: "`zikaron doctor` … is the channel for
   it." On a warm start over a corrupt file, `TextEmbedding(...)` at `encoder.py:248` raises
   whatever `onnxruntime`/`tokenizers` raises, `BackgroundLoadedEncoder` latches it
   (`:507–508`), and the user meets it as a not-ready service and a degrade relay; no text names
   `doctor`, and a bit-flip in the weights raises nothing at all. `grep -rn doctor zikaron/` finds
   no mention outside `cli/`, `doctor/` and `acquisition.py`'s docstring. *Fix:* in `load`, when
   `pin is not None`, wrap the construction — `except Exception as error: raise
   _artifact_failure(model_name, f"an artefact that loads from {specific_model_path}; `zikaron
   doctor` checks its files against the pin") from error` — so the latched failure carries the
   channel's name. The silent case has no cheap fix and the design already states the trade;
   this is the loud half.

9. **[NITPICK] Four sentences in `research/m30-verify-cost.md`.** (a) `:64` "alternating so
   drift hits both" undersells the data: `load1` rose monotonically across A1 < B1 < A2 < B2, so
   each control ran at *heavier* load than the arm before it and the +331/+396 ms delta is
   conservative — say so, as `m17-cold-start-ab.md:44–45` does for its own arms. (b) `:66–67`
   "byte-for-byte pre-M30 behaviour": the shim leaves M30's `cache_dir` argument in place, so it
   is fastembed's own acquisition into Zikaron's directory, not the pre-M30 tree; the right
   control for this question, named precisely. (c) `:81–84` offers the warm `snapshot_download`
   call as a candidate for the 150–210 ms excess over the isolated walk — but the fixed tree
   still makes that call and lands at or below the no-pin arm (`:111`), which rules it out; the
   excess is the hash under contention. (d) `:78` "`socket` … within noise" with no spread given
   (582/560/611/567 is +22/+44 in one direction); print the ranges or drop the phrase.

10. **[NITPICK] `test_indexing_acquisition.py:185–189`** `test_doctor_is_the_channel_that_still_
    finds_it` calls `acquisition.verify`, not `doctor`; the stub's snapshot sits at
    `cache/snapshots/<rev>` rather than the `models--<org>--<name>/snapshots/<rev>` layout
    `check_model_cache` resolves, so the test cannot call it. Either move the stub to the real
    layout (via `model_cache.snapshot_dir`) and assert `checks.check_model_cache(_PIN,
    cache_dir=...).outcome is FAILED`, or rename to what it proves.

11. **[NITPICK] `acquisition.py:151–152`** `contextlib.suppress(OSError)` around the rmtree: if
    the removal fails for any reason but concurrent removal, the process still raises
    `BAD_CONFIG` while the directory the next warm start will trust stays behind, and nothing says
    so. Cheapest honest form: after the suppress, `if directory.exists():` append "; it could not
    be removed, so delete `<directory>` by hand before the next start" to `expected`.

12. **[NITPICK] `acquisition.py:3`, `distribution.md:221`** "checked whenever bytes come off the
    network" — through *this* path. A `$FASTEMBED_CACHE_PATH` shared with another fastembed
    consumer that fetched the same repository at head (which equals the pinned revision today)
    yields a complete snapshot Zikaron never hashed and now never will. Same source, so the
    threat is unchanged; the sentence is one clause wider than the code.

13. **[NITPICK] `distribution.md:230`** "at one sustained load" — the arms started at `load1`
    8.01, 9.75, 11.77, 12.25. "one load source, `load1` 8–12 across the arms" is what the note
    supports; or add the column the note's table has.

VERDICT: NEEDS_CHANGES

## Round 6 — 2026-09-23

### Summary judgment

Both round-5 blockers are closed in the tree and closed correctly, verified against the files and
traced against the library's pointer semantics: `_discard` precedes the forced re-fetch
(`acquisition.py:243–248`), the interruption test asserts the property a warm start actually checks
(`missing_files`, not "the directory is gone"), and the mutation the brief reports is the one that
matters; `doctor`'s two remedies match what `artifact_directory` does on each fault when traced
through the fill and force paths, and the inverted tests pin both. The CI proof step is in both jobs
behind an ordering test; every prose item I re-read is applied as the brief describes, including the
two the researcher's own sweep found. What stops approval is smaller than last round but not
trivial: the two guards added this round are reached by no test, against the corpus's own rule for
a round's new guards — and one of them, the `encoder.load` wrap, *whose text I proposed in round-5
finding 8*, as built turns a broken `onnxruntime` into a `bad_config` that sends the user to a
`doctor` which passes, with the underlying message rendered on no channel. The tree before this
round at least logged the traceback. My suggestion assumed `from error` would surface somewhere;
reading the dispatch path shows it does not. One line plus two tests fixes it. Everything else is
nitpick-grade.

Assumptions stated: no shell this round, so `./check.sh` and the matrix are taken as not yet run,
as the brief says; `huggingface_hub` behaviour is taken from round 5's reading of the installed
1.26.0 and not re-read.

### Findings

1. **[BLOCKER] The `load` wrap replaces a logged traceback with a self-contradicting diagnosis, and
   nothing reaches it.** `zikaron/core/indexing/encoder.py:248–266`. Trace a construction failure
   that is *not* the files — `onnxruntime` unable to load its shared library, an arch mismatch of
   the kind `check_sqlite_vec`'s remedy already names for the other native extension, a
   `tokenizers` version the artefact predates: `TextEmbedding(...)` raises → `pin is not None` →
   `_artifact_failure(...) from error` → latched by `_load_and_check` (`:519–524`) → re-raised
   from `_resolved()` inside a handler → `server.py:137–144` returns `error.data` on the wire and
   **does not log** (`_LOGGER.exception` is the non-`ZikaronError` branch at `:145–153`) →
   `ZikaronError.detail()` (`errors.py:355`) renders payload fields only. `__cause__` is rendered
   nowhere; `grep -rn '__cause__' zikaron/` is empty. So the user sees `bad_config …
   expected=an artefact that loads from …; zikaron doctor checks its files`, runs `doctor`, gets
   "5 files verified", and the one sentence that said what was wrong exists in no log and no
   response. Before this round the same failure reached `:145` raw: `internal error` on the wire
   and the full traceback in the service log — poor, but recoverable. D35 rules a platform out on
   `onnxruntime` by name, so the class is not hypothetical. *Fix, one line:* carry the cause in the
   payload — `f"an artefact that loads from {specific_model_path} — constructing it raised
   {type(error).__name__}: {error}; `zikaron doctor` checks its files against the pin this release
   carries"` — so the refusal itself distinguishes *files wrong* from *runtime wrong*. *And the
   tests the branch has none of* (`grep -n 'doctor' tests/test_indexing_encoder.py` is empty; no
   stub there raises from construction), in `test_indexing_encoder.py` under the autouse
   `_no_acquisition`:
   ```python
   def _raising(**_: object) -> None:
       raise RuntimeError("onnxruntime: cannot load")

   def test_a_pinned_artefact_that_will_not_construct_names_doctor_and_the_cause(
       monkeypatch: pytest.MonkeyPatch, _no_acquisition: Path
   ) -> None:
       monkeypatch.setattr("fastembed.TextEmbedding", _raising)
       with pytest.raises(ZikaronError) as raised:
           FastEmbedEncoder.load(MODEL)
       expected = str(raised.value.data["expected"])
       assert raised.value.code is ErrorCode.BAD_CONFIG
       assert "zikaron doctor" in expected
       assert str(_no_acquisition) in expected
       assert "onnxruntime: cannot load" in expected
       assert isinstance(raised.value.__cause__, RuntimeError)

   def test_an_unpinned_model_that_will_not_construct_raises_unchanged(
       monkeypatch: pytest.MonkeyPatch,
   ) -> None:
       monkeypatch.setattr("zikaron.core.indexing.model_pin.pin_for", lambda _name: None)
       monkeypatch.setattr("fastembed.TextEmbedding", _raising)
       with pytest.raises(RuntimeError):
           FastEmbedEncoder.load(MODEL)
   ```
   Mutations: deleting `if pin is None: raise` reddens the second; deleting the `except` reddens
   the first; dropping `{error}` from the message reddens the first's fourth assertion.

2. **[IMPROVEMENT] The `stranded` branch of `_mismatch_failure` is unreached, at both raise
   sites.** `acquisition.py:145–149`, called from `:246` and `:252`. `grep -n 'rmtree\|stranded\|by
   hand' tests/test_indexing_acquisition.py` is empty. Mutation: replacing `stranded=None if gone
   else directory` with `stranded=None` at either site reddens nothing, so the one remedy the
   docstring calls "worth more than a sentence" is the one no test has seen. *Fix*, in
   `TestAFailedAcquisitionLeavesNothingToTrust`:
   ```python
   def test_a_snapshot_that_cannot_be_removed_is_named_in_the_refusal(
       self, hub: _Hub, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
   ) -> None:
       hub.serving["tokenizer.json"] = b"still wrong"

       def _refuse(path: object, *args: object, **kwargs: object) -> None:
           raise OSError("read-only")

       monkeypatch.setattr(acquisition.shutil, "rmtree", _refuse)
       with pytest.raises(ZikaronError) as raised:
           _fetch(hub, tmp_path)
       expected = str(raised.value.data["expected"])
       assert str(hub.snapshot) in expected
       assert "by hand" in expected
       assert _fetch(hub, tmp_path) == hub.snapshot, (
           "the stranded directory is what the next call trusts — the reason the remedy exists"
       )
   ```
   That reaches `:252` (both discards refused; the forced fetch lands wrong again) and pins the
   hazard the remedy is for. `:246` is reached by applying the same monkeypatch *after* a first
   failed `_fetch` whose discards succeeded — the second call's pre-re-fetch discard then fails with
   the claim already spent.

3. **[NITPICK] A second call in one process is now a network call, and two sentences say it is
   not.** `acquisition.py:40` "A second mismatch is a failure, never another download" and
   `distribution.md:283–284` "never another download". With the discard now preceding the
   re-fetch, a second `artifact_directory` call after a failure finds no snapshot: the warm call
   raises `LocalEntryNotFoundError`, and the *plain online* call runs — one metadata round-trip per
   file, re-linking the existing blobs, no bytes — before `verify` fails and the refusal is raised.
   Before this round that second call was a `stat` walk. True of bytes, not of requests; and
   offline, a lazily reconstructed encoder now gets a connection error where it got `bad_config`.
   `test_a_second_call_in_one_process_forces_nothing_further` asserts only "no forced call" and
   passes either way. "never another *forced* fetch — after the discard the warm call falls through
   to one plain online call, which re-links the existing blobs and transfers nothing", and let that
   test also assert `[(c.local_files_only, c.force_download) for c in hub.calls[before:]] ==
   [(True, False), (False, False)]` so the shape is pinned.

4. **[NITPICK] Two new absolutes.** `check.yml:148` "The only place the digest table is checked
   against real files" and `test_ci_workflow.py:522` "CI is the only place the digest table meets
   the files it describes" — `zikaron doctor` does exactly that on any machine on demand, and
   `distribution.md:249` says so. "the only place *a gate* checks it". The audit loop's own
   finding is that this class decays.

5. **[NITPICK] The prove step is not tied to the config default the way the fetch step is.**
   `check.yml:153,269` hardcode `'BAAI/bge-small-en-v1.5'`;
   `test_the_cache_key_names_the_library_whose_pin_decides_the_download:512` ties the *fetch*
   to `embed_model.default`, and the new test asserts nothing about which model the prove step
   verifies. A changed default moves the key and the fetch and leaves the prove step hashing the
   old pin's absent snapshot — loud (`v.complete()` fails on five absent files) but misnamed. Add
   `assert str(embed_model.default) in str(_steps(job)[proving]["run"])` to
   `test_every_job_proves_the_pinned_digests_against_real_bytes`.

6. **[NITPICK] `distribution.md:212–213`** "**`force_download=True` is reserved for a file that is
   present and wrong**" — after a fill, a file the source never sends comes back from `verify` as
   `absent` and goes to the forced re-fetch like any other verification failure
   (`acquisition.py:236–248`; `test_a_file_the_source_never_sends_counts_as_missing_rather_than_
   crashing` is the case). What the split decides is the *first* repair, fill versus force, and it
   decides it through `missing_files`; "reserved for a fetch that verified wrong" is the sentence
   the code supports.

7. **[NITPICK] `acquisition.py:3–8`** — the parenthetical ends "— but the sentence would otherwise
   be wider than the code", which explains why the clause was added rather than anything about the
   code: the annotate-the-repair class `CLAUDE.md` §comments names. And the reflow left `:7` as the
   two-word line "warm start". Cut after "the threat is unchanged" and reflow the paragraph.

8. **[NITPICK] `README.md:185–189`** tells a user Zikaron "checks every file against a SHA256 it
   ships" with no time qualifier, which reads as every start. `distribution.md:248` says the trade
   is "stated rather than implied"; the README is where the user would read it. "checks every file
   it *downloads* against a SHA256 it ships … A file that goes bad on disk afterwards is
   `zikaron doctor`'s to find, not startup's."

VERDICT: NEEDS_CHANGES

## Round 7 — 2026-09-23

### Summary judgment

All eight round-6 findings are applied in the tree and each is verified against the file rather
than the brief. The blocker is closed the right way: `encoder.py:269–274` carries
`{type(error).__name__}: {error}` in the payload, so the refusal itself separates files-wrong from
runtime-wrong; the message reaches the model through `mcp/primary.py:57` → `ToolError` and the
indexer's stderr through `scope.execute`, and the hook's fixed-label `hook.log` is the one channel
it deliberately does not reach (`hook/failure.py:96–97`, a pre-existing secrets rule, not a gap this
round opened). Both branches of the wrap are tested (`test_indexing_encoder.py:167–196`), the
stranded remedy is reached at the post-force site with `rmtree` restored by name rather than
`undo()` — the right fix, since `undo()` would also revert the `hub` patch — the second-call shape is
pinned to `[(True, False), (False, False)]`, the prove step is tied to `embed_model.default`, and
every absolute the brief lists is narrowed as described. I traced the acquisition path again on
every cell (warm-complete, absent, partial, partial-plus-wrong, wrong, source-wrong, interrupted
force, stranded, second call, new process) and found no behavioural fault. What remains is seven
nitpicks, one of which is a stale copy of the changed claim that the researcher's sweep missed
because the phrase wraps across a line boundary.

Assumptions stated: no shell this round; `./check.sh` and `./check-matrix.sh --parallel` are
reported *running*, not green, so this approval is of the tree as read and is void if either gate
reddens. `huggingface_hub` pointer/blob semantics are taken from round 5's reading of the installed
1.26.0 and not re-read.

### Findings

1. **[NITPICK] One stale copy of "never another download" survives, and it is the one a line-based
   grep cannot see.** `design/build-plan.md:3319–3321`, M30 brief item (iv): "a second mismatch is a
   named failure carrying its remedy … never another\ndownload." The phrase breaks across lines
   3320–3321, so `grep 'never another download'` returns nothing — which is presumably how the
   sweep reported the class clean. The claim is true of bytes and false of requests, exactly as
   round 6 finding 3 said of the other two copies. *Fix:* extend the second *(Narrowed in the
   build…)* note at `:3311–3317` with one clause — "and (iv)'s *never another download* holds for
   bytes, not requests: after the discard a second call in one process falls through to one plain
   online call that re-links the existing blobs and transfers nothing" — leaving (iv)'s original
   text in place, as the note style does. For the next sweep of a multi-word claim,
   `grep -n -A1 '<first half>'` or `rg -U` is the form that finds a wrapped phrase.

2. **[NITPICK] `distribution.md:167` states a `doctor` exit predicate its own test contradicts.**
   "Only *present and mismatched* fails." A snapshot directory that is present with a pinned file
   *missing* also fails — `doctor/checks.py:156–172` reports "`X` missing" with the start-the-service
   remedy, and `test_doctor.py:200` (`test_an_absent_file_alone_is_told_only_to_start_the_service`)
   asserts that row is a failure. *Fix:* "A snapshot directory that is present fails if any pinned
   file is missing or does not match, each with its own remedy; only a directory that is not there
   at all is the absent-and-passing case."

3. **[NITPICK] The stranded test's closing assertion is weaker than its message, and the other
   stranded raise site is unreached.** (a) `tests/test_indexing_acquisition.py:357–361`:
   `hub.serving = dict(_SERVED)` is never consulted — the second `_fetch` takes the warm path and
   makes no online call — and `== hub.snapshot` establishes "did not raise" rather than the hazard
   the message names. Assert the hazard directly:
   ```python
   before = len(hub.calls)
   assert _fetch(hub, tmp_path) == hub.snapshot
   assert [c.local_files_only for c in hub.calls[before:]] == [True]
   assert (hub.snapshot / "tokenizer.json").read_bytes() == b"still wrong"
   ```
   and drop the `serving` reset. (b) `acquisition.py:248` — the `claim in _REFETCHED` site — is
   reached only with `gone=True` (`test_a_second_call_in_one_process_forces_nothing_further`);
   replacing its `stranded=None if gone else directory` with `stranded=None` reddens nothing. Round
   6 finding 2 named the sequence: one `_fetch` that fails with the real `rmtree`, then patch
   `rmtree` to refuse and `_fetch` again — the plain online call re-lands the wrong bytes, the
   pre-re-fetch discard fails, the claim is already spent, and `:248` raises with `stranded` set.
   Six lines in the same class; assert `str(hub.snapshot) in expected`.

4. **[NITPICK] `check.yml:150–151`** — "a digest edited wrongly at an *unchanged* revision is green
   here and green on every warm developer machine" sits in the comment of the step whose purpose is
   that it is *not* green here. "would be green in this job without this step, and is green on every
   warm developer machine". `test_ci_workflow.py:525–528` already says it the clear way ("passes the
   gate").

5. **[NITPICK] `acquisition.py:41–43`** — the reflow left "The bound is **one\nre-fetch per
   process\nper artefact**" as a three-word line between two full ones, the same class as round 6
   finding 7's "warm start". Reflow the paragraph to the module's width.

6. **[NITPICK] Two documents use "the split" for opposite claims.** `distribution.md:213` "What the
   absent/wrong split decides is the *first* repair — fill or force — and `missing_files` decides
   it"; `acquisition.py:83–84` (`Verification`'s docstring) "*The split is no longer what chooses
   between filling and forcing: `missing_files` does that.*" Both are true under their own reading
   of "split" — the distinction versus the `NamedTuple` — and a reader with both open sees a
   contradiction. *Fix `distribution.md:213`:* "Whether a file is absent or wrong decides the
   *first* repair — fill or force — and `missing_files` is what decides it, before any hashing;
   `Verification`'s own absent/wrong split now serves `doctor`'s two remedies."

7. **[NITPICK] The accepted per-start price is stated in bandwidth only; on disk the discard
   removes pointers, not blobs.** `distribution.md:281–285`, `acquisition.py:43–46`. `_discard`
   is an `rmtree` of `snapshots/<sha>/`; the blob a failed acquisition proved wrong stays at
   `blobs/<etag>`, and the forced re-fetch overwrites it only when the server's etag is the one it
   was stored under. A source serving wrong bytes with a stable etag leaves one unreferenced 64 MB
   blob behind; one whose etag varies leaves one per service start, and nothing in the product or in
   `doctor` names or removes them. One clause after "needing no state on disk": "and, since the
   discard removes pointers rather than blobs, a proved-wrong blob stays under `blobs/` until the
   cache is cleared". No code change is warranted for a case that already requires a broken source.

VERDICT: APPROVED
