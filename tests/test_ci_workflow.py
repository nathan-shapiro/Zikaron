"""CI asserts the matrix's claim, and this checks that it still does.

`check.sh` is the per-edit gate. `check-matrix.sh` is what a milestone needs locally. **CI is
neither a third gate nor a looser one**: it runs `check.sh` once per supported version against a
commit, so *every version saw the same tree* comes from the SHA instead of from a fingerprint the
matrix has to sample twice. `design/distribution.md` §"What CI asserts" is normative.

The properties below are the ones that make that claim true, and every one of them is a thing a
workflow can silently stop doing while still being valid YAML and still going green:

- the version list drifting from `check-matrix.sh`'s;
- the deprecation filters losing a value, or gaining a *scope* — wider than the matrix's makes CI
  the stricter definition of done, which is as wrong as looser and far less obvious;
- the model-cache export and the cached directory drifting apart, so the cache holds nothing;
- a setup step moving after the gate step, which no presence check can see;
- the interpreter quietly coming from somewhere other than `uv`, which changes what the
  `load_extension` evidence is *about*;
- the macOS job losing the GNU `timeout` it cannot run `check.sh` without;
- a job acquiring `continue-on-error`, which lets it stay red without reddening the run;
- the macOS job losing the summary line that says a green tick there covers no live harness.

**Parsed rather than grepped.** The file is YAML and its structure carries the meaning — which job,
which step, which level a variable is set at, and in what order. `tests/test_check_gate.py` reads
`check-matrix.sh` with a regex because a shell array is not structured; this one has no such excuse.
"""

import re
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

import pytest
import yaml

from zikaron.core.config.keys import CONFIG_KEYS
from zikaron.core.indexing.model_pin import pin_for

_ROOT: Final = Path(__file__).resolve().parent.parent

#: How the prefetch step is recognised. **Zikaron's own loader, not `fastembed`'s constructor**:
#: only the former honours the pinned revision, so a prefetch that reverted to `TextEmbedding(...)`
#: would fill a revision-keyed cache with upstream's head and is not this step.
_MODEL_FETCH: Final = "FastEmbedEncoder.load("
_WORKFLOW: Final = _ROOT / ".github" / "workflows" / "check.yml"

#: **Every workflow file, for the checks about how a workflow is pinned rather than about what the
#: gate asserts.** Those read the module-scoped fixture and covered `check.yml` alone, leaving the
#: one workflow that holds a publishing credential unpinned by anything — the inverse of where the
#: rule matters most. Discovered rather than listed, so a third workflow is covered by existing.
#: Both extensions, because GitHub reads either and a workflow added as `.yaml` would otherwise be
#: covered by neither pin test while this comment claimed it was.
_WORKFLOW_FILES: Final = sorted(
    path
    for suffix in ("*.yml", "*.yaml")
    for path in (_ROOT / ".github" / "workflows").glob(suffix)
)

#: Both filters, exactly as `check-matrix.sh` sets them. A job missing either is the failure this
#: file exists for: it passes a tree the milestone gate would fail.
_REQUIRED_ENV: Final = {
    "PYTEST_ADDOPTS": "-W error::DeprecationWarning -W error::PendingDeprecationWarning",
    "PYTHONWARNINGS": "error::DeprecationWarning,error::PendingDeprecationWarning",
}

_JOBS: Final = ("linux", "macos")


@pytest.fixture(scope="module")
def workflow() -> dict[Any, Any]:
    """**`dict[Any, Any]`, not `dict[str, Any]`, and the key type is the point.**

    PyYAML implements YAML 1.1, in which `on` is a *boolean literal* — so a workflow's
    trigger block arrives under the key `True`, not `"on"`. Measured against this very
    file: its top-level keys are `name`, `True`, `concurrency`, `permissions`, `jobs`.
    Annotating the parse as string-keyed would be a false statement about the object, and
    `mypy --strict` catches it at the one place that reads the odd key.
    """
    parsed = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict)
    return parsed


def _jobs(workflow: dict[Any, Any]) -> dict[str, Any]:
    return dict(workflow["jobs"])


def _steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    return list(job["steps"])


def _run_text(job: dict[str, Any]) -> str:
    """Every `run:` body in a job, joined. What the job actually executes."""
    return "\n".join(str(step.get("run", "")) for step in _steps(job))


def _step_index(job: dict[str, Any], matches: Callable[[dict[str, Any]], bool]) -> int:
    """Where a step sits in its job. Order is a property no presence check can see: an export or a
    `brew install` placed *after* the gate satisfies every "is it there?" assertion and the job
    fails exactly as if the step were missing."""
    for index, step in enumerate(_steps(job)):
        if matches(step):
            return index
    return -1


def _gate_step(job: dict[str, Any]) -> dict[str, Any]:
    """The step that runs `./check.sh`. Singular by assertion, not by assumption."""
    gates = [step for step in _steps(job) if "./check.sh" in str(step.get("run", ""))]
    assert len(gates) == 1, f"expected exactly one gate step, found {len(gates)}"
    return gates[0]


def _cache_steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    return [step for step in _steps(job) if "cache" in str(step.get("uses", ""))]


def test_the_workflow_parses_and_has_both_jobs(workflow: dict[Any, Any]) -> None:
    """The oracle for everything below. A file that failed to parse, or a job set that lost a
    member, would make most of these tests pass by iterating over nothing."""
    assert set(_jobs(workflow)) == set(_JOBS)


def test_the_trigger_names_a_branch_that_exists(workflow: dict[Any, Any]) -> None:
    """A workflow keyed to a branch nobody pushes never fires, and nothing says so — it simply
    has no runs. The remote's default branch is `main`; local `master` was renamed to match it after
    `git ls-remote` showed the repository had been created with `main` already set.

    **`on` is the YAML 1.1 trap**: `on` is a boolean key there, and PyYAML parses it as `True`.
    """
    triggers = workflow.get("on", workflow.get(True))
    assert triggers is not None, "the workflow has no trigger block under either `on` or `True`"
    assert triggers["push"]["branches"] == ["main"]


@pytest.mark.parametrize("job_name", _JOBS)
def test_the_gate_step_gets_both_deprecation_filters(
    workflow: dict[Any, Any], job_name: str
) -> None:
    """**Effective env of the step that runs `./check.sh`**, which is the only scope that matters —
    and computing it this way also closes the override hole, where a step-level `PYTHONWARNINGS: ""`
    would defeat a workflow-level setting while a presence check kept passing."""
    job = _jobs(workflow)[job_name]
    effective = {
        **workflow.get("env", {}),
        **job.get("env", {}),
        **_gate_step(job).get("env", {}),
    }
    for name, value in _REQUIRED_ENV.items():
        assert effective.get(name) == value, f"{job_name}'s gate step does not get {name}"


@pytest.mark.parametrize("job_name", _JOBS)
def test_the_deprecation_filters_are_no_wider_than_the_matrix_scopes_them(
    workflow: dict[Any, Any], job_name: str
) -> None:
    """**Scope, not presence, and the drift this catches runs in the direction nobody looks.**

    `check-matrix.sh` applies these two around `./check.sh` alone; it builds each virtualenv without
    them. Setting them at workflow or job level here would apply them to `pip install -e '.[dev]'`,
    its PEP 517 backend subprocess and setuptools' editable build — so a `DeprecationWarning` raised
    inside pip on 3.13 or 3.14 would redden CI's *install* step on a tree the matrix passes. That
    makes CI the **stricter** definition of done for a reason that is not this repository's code,
    which is the mirror of the looser-CI failure and just as wrong.
    """
    job = _jobs(workflow)[job_name]
    for level, block in (("workflow", workflow.get("env", {})), (job_name, job.get("env", {}))):
        for name in _REQUIRED_ENV:
            assert name not in block, (
                f"{name} is set at {level} level, which scopes it wider than check-matrix.sh does"
            )

    # **And no *other step* may carry them either, which is the placement the two checks above miss
    # and the likeliest one to be written by hand.** A `PYTHONWARNINGS` on "Build the virtualenv" is
    # literally the failure this docstring names — applied to `pip install`, its PEP 517 backend and
    # setuptools' editable build — and it passes a workflow-and-job-level check.
    gate = _gate_step(job)
    for step in _steps(job):
        if step is gate:
            continue
        overlap = _REQUIRED_ENV.keys() & step.get("env", {}).keys()
        assert not overlap, (
            f"{job_name}'s step {step.get('name', step.get('uses', '?'))!r} carries "
            f"{sorted(overlap)}, which scopes the filters beyond the gate"
        )


def test_the_deprecation_filters_match_the_matrix_script_verbatim() -> None:
    """Two statements of one pair. If `check-matrix.sh` changes its filters and CI does not, CI is
    quietly the looser definition of done — which is the exact thing this workflow must not be."""
    matrix = (_ROOT / "check-matrix.sh").read_text(encoding="utf-8")
    for name, value in _REQUIRED_ENV.items():
        assert f'{name}="{value}"' in matrix, (
            f"check-matrix.sh no longer sets {name} to the value CI asserts"
        )


def test_the_linux_matrix_runs_exactly_the_versions_the_matrix_script_does(
    workflow: dict[Any, Any],
) -> None:
    """Tied to the shell array that drives the local gate, so the two cannot drift apart. Read from
    `check-matrix.sh` rather than restated here, for the reason `test_check_gate.py` gives: the
    version list lives in one executable place."""
    script = (_ROOT / "check-matrix.sh").read_text(encoding="utf-8")
    found = re.search(r"^minors=\(([^)]*)\)", script, re.MULTILINE)
    assert found is not None, "check-matrix.sh no longer declares `minors=(...)`"
    configured = _jobs(workflow)["linux"]["strategy"]["matrix"]["python"]
    assert configured == found.group(1).split()


@pytest.mark.parametrize("job_name", _JOBS)
def test_every_job_takes_its_interpreter_from_uv_and_not_setup_python(
    workflow: dict[Any, Any], job_name: str
) -> None:
    """**`distribution.md` §4 requires an interpreter from `uv` rather than `actions/setup-python`,
    and `.github/workflows/check.yml` is where the phrase "not a detail" appears — nothing asserted
    it until a review round pointed out that swapping in `actions/setup-python` passed every test
    here.**

    *The phrase was attributed to `distribution.md` §4, which does not contain it. Traceable:
    a review round wrote "the very thing the bullet says is 'not a detail'", conflating the §4
    bullet with the workflow's own comment, and this docstring hardened that into an attributed
    quotation. **A quotation picked up from a review finding inherits the finding's precision, not
    the document's.***

    `enable_load_extension` is a compile-time option, and `research/python-portability-probes.md` §4
    verified it on exactly the python-build-standalone builds `uv` fetches — which are also what a
    `uv tool install` user gets. Another provider's build would still be green and would silently
    change what the Gatekeeper and `load_extension` evidence is *about*.
    """
    job = _jobs(workflow)[job_name]
    used = [str(step.get("uses", "")) for step in _steps(job)]
    assert not any(action.startswith("actions/setup-python") for action in used), (
        "the interpreter must come from uv, or the load_extension evidence is about another build"
    )
    runs = _run_text(job)
    assert "uv python install --no-bin" in runs
    assert "uv venv" in runs


def test_no_job_excuses_itself_from_the_run_s_verdict(workflow: dict[Any, Any]) -> None:
    """`continue-on-error` on any job makes this workflow's claim weaker than the matrix's, which
    is the one thing it may not be. Asserted over **every** job rather than over macOS by name: the
    setting is a per-job flag, and a future platform added with it on would restore the state M29
    removed while this file, written to watch one job, stayed green."""
    excused = [name for name, job in _jobs(workflow).items() if job.get("continue-on-error")]
    assert not excused, f"these jobs cannot redden the run: {excused}"


def test_the_macos_job_says_what_a_green_tick_does_not_cover(workflow: dict[Any, Any]) -> None:
    """A required green job reads as "macOS works", and the hermetic gate cannot support that:
    no harness binary exists on a runner, so nothing there exercises a live session. The step
    summary is where a reader meets the run, so the limit is written into it, under `if: always()`
    so the red path says it too."""
    macos = _jobs(workflow)["macos"]
    summary_steps = [
        step
        for step in _steps(macos)
        if "GITHUB_STEP_SUMMARY" in str(step.get("run", ""))
        and "harness" in str(step.get("run", "")).lower()
    ]
    assert summary_steps, "no step tells the reader the harness tiers are unexercised here"
    assert any(str(step.get("if", "")).strip() == "always()" for step in summary_steps), (
        "the summary step would be skipped on the red path, where the caveat matters as much"
    )


def test_the_macos_job_installs_gnu_timeout_and_puts_it_on_path(
    workflow: dict[Any, Any],
) -> None:
    """**Both halves, because one of them alone fails identically to neither.** `check.sh` wraps
    pytest in `timeout`; macOS has none on `PATH`, and Homebrew installs the GNU tools `g`-prefixed.
    Without the `gnubin` prepend only `gtimeout` exists and the job still dies in the shell before a
    single test runs — an advisory job reporting "red, as expected" while having tested nothing."""
    runs = _run_text(_jobs(workflow)["macos"])
    assert "brew install coreutils" in runs, "coreutils is absent, so there is no GNU timeout"
    assert "gnubin" in runs, "without the gnubin directory only `gtimeout` exists, not `timeout`"
    assert "GITHUB_PATH" in runs, "gnubin is named but never put on PATH for the later steps"


def test_the_macos_setup_steps_come_before_the_gate(workflow: dict[Any, Any]) -> None:
    """**Order, which every presence check above is blind to.** `brew install coreutils` placed
    after `./check.sh` satisfies the test above and the job fails exactly as if it were missing."""
    macos = _jobs(workflow)["macos"]
    brew = _step_index(macos, lambda s: "brew install coreutils" in str(s.get("run", "")))
    proof = _step_index(macos, lambda s: "timeout --version" in str(s.get("run", "")))
    gate = _step_index(macos, lambda s: "./check.sh" in str(s.get("run", "")))
    assert -1 not in (brew, proof, gate)
    assert brew < proof < gate, f"steps are out of order: brew={brew} proof={proof} gate={gate}"


def test_the_macos_runner_label_is_a_standard_arm64_one(workflow: dict[Any, Any]) -> None:
    """**`macos-<n>` exactly**, which per `research/github-actions-macos-runners.md` Q1 is the arm64
    standard runner and free on public repositories.

    A looser `startswith("macos-")` admits the two labels that note warns against: `macos-15-intel`
    is **x64**, which changes the job's entire subject, and `macos-15-xlarge` is a larger runner,
    billed even on public repositories. `macos-latest` is excluded for a third reason — it migrated
    from macOS 15 to macOS 26 mid-2026, so it is a moving target under a job whose purpose is to
    characterise one platform.
    """
    label = str(_jobs(workflow)["macos"]["runs-on"])
    assert re.fullmatch(r"macos-\d+", label), (
        f"`{label}` is not a bare standard arm64 macOS label; "
        "`-intel` is x64 and `-xlarge` is billed on public repositories"
    )


def test_the_linux_runner_label_floats_and_that_is_the_stated_choice(
    workflow: dict[Any, Any],
) -> None:
    """The other half of `design/distribution.md`'s runner-label bullet, asserted so the rule and
    its enforcement cannot drift apart again.

    **They had.** The bullet read "**A** pinned runner label", as though it governed every job;
    only the macOS label was checked, and the linux job ran `ubuntu-latest` — the exact shape the
    bullet warns against. The document was the half that was wrong, because the reason it gives
    does not reach the linux job: **both** jobs install their interpreter with
    `uv python install --no-bin`, so neither measures the image's own Python or its system SQLite,
    and a moving ubuntu image changes the kernel and libc beneath a managed interpreter — worth
    tracking forward rather than freezing.

    Pinning this label later is a legitimate decision; making it silently is not, which is why the
    float is asserted rather than merely tolerated.
    """
    label = str(_jobs(workflow)["linux"]["runs-on"])
    assert label == "ubuntu-latest", (
        f"the linux job runs on `{label}`; `design/distribution.md` says it floats on purpose, so "
        "changing it means changing that bullet in the same edit"
    )


def test_the_model_cache_variable_is_never_set_where_the_runner_context_is_unavailable(
    workflow: dict[Any, Any],
) -> None:
    """The `runner` context is available only at step level — not in workflow-level `env:` and not
    in `jobs.<id>.env:`. A reference to a context outside its availability is rejected when GitHub
    validates the workflow — the whole run is refused and no job in the file starts. (Documented
    behaviour; unobserved here until the first push.) This keeps anyone from moving the export back
    to a level the run would be refused for, before a push is spent finding out.
    """
    blocks = [("workflow", workflow.get("env", {}))]
    blocks += [(name, job.get("env", {})) for name, job in _jobs(workflow).items()]
    for where, block in blocks:
        for key, value in block.items():
            assert "runner." not in str(value), (
                f"{where}-level env `{key}` uses the runner context, which is unavailable there"
            )


@pytest.mark.parametrize("job_name", _JOBS)
def test_the_exported_cache_directory_is_the_one_that_gets_cached(
    workflow: dict[Any, Any], job_name: str
) -> None:
    """**Two spellings of one path, asserted to agree.**

    The export writes `$RUNNER_TEMP/<leaf>` and the cache step names `${{ runner.temp }}/<leaf>`;
    they are the same directory only as long as the leaf matches. Editing one and not the other
    caches a directory fastembed never writes — the cache never hits, every job re-downloads 64 MB,
    and nothing fails.

    The export is matched as a whole line rather than as a substring, because
    `run: export FASTEMBED_CACHE_PATH=$RUNNER_TEMP/fastembed_cache` contains the substring, sets the
    variable for that step alone, and leaves `./check.sh` seeing nothing — which is precisely the
    "a step cannot see what an earlier step set" failure this file claims to catch.
    """
    job = _jobs(workflow)[job_name]
    exported = re.search(
        r'^\s*echo "FASTEMBED_CACHE_PATH=\$RUNNER_TEMP/(\S+)" >> "\$GITHUB_ENV"\s*$',
        _run_text(job),
        re.MULTILINE,
    )
    assert exported is not None, (
        f"{job_name} does not export FASTEMBED_CACHE_PATH into $GITHUB_ENV; a plain `export` sets "
        "it for one step only"
    )
    leaf = exported.group(1)

    cache_steps = _cache_steps(job)
    assert cache_steps, f"{job_name} has no cache step"
    for step in cache_steps:
        assert step["with"]["path"] == "${{ runner.temp }}/" + leaf, (
            f"{job_name} caches {step['with']['path']!r} but fastembed writes to "
            f"$RUNNER_TEMP/{leaf}"
        )


@pytest.mark.parametrize("job_name", _JOBS)
def test_the_cache_export_happens_before_the_gate(workflow: dict[Any, Any], job_name: str) -> None:
    """Order again: an export after `./check.sh` passes every content check and caches nothing."""
    job = _jobs(workflow)[job_name]
    export = _step_index(job, lambda s: "FASTEMBED_CACHE_PATH" in str(s.get("run", "")))
    gate = _step_index(job, lambda s: "./check.sh" in str(s.get("run", "")))
    assert -1 not in (export, gate)
    assert export < gate, f"{job_name} exports the cache path after the gate has already run"


@pytest.mark.parametrize("job_name", _JOBS)
def test_the_model_cache_is_filled_and_saved_before_the_gate_can_redden_it(
    workflow: dict[Any, Any], job_name: str
) -> None:
    """**The cache must not depend on the suite's outcome, and must not be written by a cancelled
    run. Those two pull in opposite directions, and the ordering is what satisfies both.**

    `actions/cache`'s combined form saves in a post step gated on job success, so a red job caches
    nothing — and the macOS job is expected to be red while that platform is unverified, meaning
    64 MB re-downloaded every run. The obvious repair, `if: always()` on a split save, is worse:
    `always()` runs **even when the run is cancelled**, `cancel-in-progress: true` cancels on every
    new push to the same ref, and a cancel mid-download leaves `huggingface_hub`'s `.incomplete`
    blobs beside the finished. A cache writes only on a key miss, so that partial directory would
    be restored by every later run until the key changed, each one re-fetching the remainder and
    reporting nothing.

    So the fetch is its own step before the gate and the save is gated on `cache-hit != 'true'` with
    no `always()`: a cancelled or failed fetch skips the save by default semantics, a completed one
    is saved before anything can redden, and a restore hit does not re-upload 64 MB to be told the
    key exists.
    """
    job = _jobs(workflow)[job_name]
    steps = _steps(job)

    restores = [step for step in steps if "cache/restore" in str(step.get("uses", ""))]
    saves = [step for step in steps if "cache/save" in str(step.get("uses", ""))]
    assert restores, f"{job_name} has no cache restore step, so it downloads the model every run"
    assert saves, f"{job_name} restores a cache but never saves one"

    for step in saves:
        condition = str(step.get("if", "")).strip()
        assert "always()" not in condition, (
            "`always()` runs on the cancelled path too, which is how a partial model directory "
            "gets saved under a key that never refreshes"
        )
        # **The reference has to resolve, not merely be present.** `steps.<id>.outputs.cache-hit`
        # against an `id` no step carries evaluates to the **empty string**, `'' != 'true'` is true,
        # and the save then runs on every hit — a 64 MB tar-and-upload per job per run, answered
        # with "cache already exists", which is a warning and never a failure. Renaming or dropping
        # the restore's `id` would do it, and a substring check for "cache-hit" would not notice.
        referenced = re.search(r"steps\.([\w-]+)\.outputs\.cache-hit", condition)
        assert referenced is not None, (
            f"{job_name}'s save is not gated on a restore's cache-hit output, so it re-uploads "
            f"64 MB on every run that already had the model (condition: {condition!r})"
        )
        assert any(str(restore.get("id", "")) == referenced.group(1) for restore in restores), (
            f"{job_name}'s save references `steps.{referenced.group(1)}` but no restore step "
            "carries that id, so the expression is empty and the save always runs"
        )

    fetch = _step_index(job, lambda s: _MODEL_FETCH in str(s.get("run", "")))
    gate = _step_index(job, lambda s: "./check.sh" in str(s.get("run", "")))
    restore = _step_index(job, lambda s: "cache/restore" in str(s.get("uses", "")))
    save = _step_index(job, lambda s: "cache/save" in str(s.get("uses", "")))
    assert -1 not in (fetch, gate, restore, save), (
        f"{job_name} is missing one of restore/fetch/save/gate: "
        f"restore={restore} fetch={fetch} save={save} gate={gate}"
    )
    assert restore < fetch < save < gate, (
        f"{job_name}'s cache steps are out of order: "
        f"restore={restore} fetch={fetch} save={save} gate={gate}. A restore after the gate never "
        "feeds fastembed; a save before the fetch uploads an empty directory forever."
    )


def test_the_cache_key_names_the_library_whose_pin_decides_the_download(
    workflow: dict[Any, Any],
) -> None:
    """A cache saves only on a key miss, so a key that does not name what it is caching goes stale
    permanently rather than refreshing. When the model revision is pinned, it belongs in this key
    for the same reason.

    **Both halves are read from their sources rather than restated.** The `fastembed` pin comes from
    `pyproject.toml` and the model name from `zikaron.core.config.keys`' own default, so either
    changing without the key changing reddens here — where the silent outcome is worse for the model
    than for the library: a changed default would keep serving the *old* model out of cache, so the
    suite would pass against an embedder the product no longer uses.
    """
    pins = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    fastembed = next(
        dep for dep in pins["project"]["dependencies"] if dep.startswith("fastembed==")
    )
    version = fastembed.split("==", 1)[1]

    embed_model = next(key for key in CONFIG_KEYS if key.name == "embed_model")
    model_leaf = str(embed_model.default).split("/")[-1]
    pin = pin_for(str(embed_model.default))

    for job_name, job in _jobs(workflow).items():
        for step in _cache_steps(job):
            key = str(step["with"]["key"])
            assert version in key, (
                f"the cache key does not name fastembed {version}, so it will never refresh"
            )
            assert model_leaf in key, (
                f"the cache key does not name the configured model {model_leaf!r}, so a changed "
                "default would keep serving the previous model out of cache"
            )
            assert pin is not None
            assert pin.revision in key, (
                f"the cache key does not name the pinned revision {pin.revision}, so a cache "
                "filled at the previous one keeps hitting while the snapshot it holds is absent — "
                "64 MB downloaded per job per run and never saved back"
            )

        # **And the step that actually fetches must name the same model the key does.** The fetch is
        # a literal in a `run:`, tied to nothing: edited to any other valid model id it passes
        # every other assertion here, the cache then holds the wrong model, `cache-hit` is `true`
        # so the save never corrects it, and the gate silently downloads the real one inside
        # itself on every run forever.
        fetch = next(
            (step for step in _steps(job) if _MODEL_FETCH in str(step.get("run", ""))), None
        )
        assert fetch is not None, f"{job_name} has no explicit model-fetch step"
        assert str(embed_model.default) in str(fetch["run"]), (
            f"{job_name} fetches a different model than the cache key names; the configured "
            f"default is {embed_model.default!r}"
        )


@pytest.mark.parametrize("job_name", _JOBS)
def test_every_job_proves_the_pinned_digests_against_real_bytes(
    workflow: dict[Any, Any], job_name: str
) -> None:
    """**CI is the only place a gate makes the digest table meet the files it describes** — on a
    machine, `zikaron doctor` does it on demand.

    Startup verifies what it fetched and a warm cache is five `stat` calls, so a digest edited
    wrongly at an *unchanged* revision passes the gate and every warm developer machine, and is
    met first by a stranger's cold fetch refusing with `bad_config`. A revision bump misses the
    cache and the fetch step covers it; nothing else covers this.
    """
    job = _jobs(workflow)[job_name]
    proving = _step_index(job, lambda s: "a.verify(" in str(s.get("run", "")))
    assert proving != -1, f"{job_name} never checks the pinned digests against the fetched files"
    fetching = _step_index(job, lambda s: _MODEL_FETCH in str(s.get("run", "")))
    assert fetching < proving, (
        f"{job_name} proves the digests before fetching them, which proves nothing"
    )
    # Tied to the configured default the way the fetch step is. Otherwise a changed default moves
    # the cache key and the fetch while this step keeps naming the old model — loud, since it would
    # hash an absent snapshot, but reported as a digest failure rather than as the drift it is.
    embed_model = next(key for key in CONFIG_KEYS if key.name == "embed_model")
    assert str(embed_model.default) in str(_steps(job)[proving]["run"]), (
        f"{job_name} proves a different model than it fetches; the configured default is "
        f"{embed_model.default!r}"
    )


@pytest.mark.parametrize("job_name", _JOBS)
def test_the_restore_and_save_keys_match(workflow: dict[Any, Any], job_name: str) -> None:
    """A split cache whose two halves disagree saves to one key and looks for another: a permanent
    miss that costs 64 MB a run and reports nothing."""
    keys = {str(step["with"]["key"]) for step in _cache_steps(_jobs(workflow)[job_name])}
    assert len(keys) == 1, f"{job_name}'s cache steps use different keys: {sorted(keys)}"


def _uses(path: Path) -> list[str]:
    """Every `uses:` in one workflow file."""
    parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict)
    return [
        str(step["uses"])
        for job in _jobs(parsed).values()
        for step in _steps(job)
        if step.get("uses")
    ]


@pytest.mark.parametrize("path", _WORKFLOW_FILES, ids=lambda p: p.name)
def test_setup_uv_is_pinned_to_a_full_version_rather_than_a_bare_major(path: Path) -> None:
    """**The one action pin that fails silently rather than loudly.**

    `astral-sh/setup-uv` has no floating major tag — `@v10` is a 404 and only full patch tags exist.
    A bare major therefore does not mean "the latest of that major": it means whatever that tag
    pointed at when it was last moved — which can be several majors and years behind, missing every
    hardening default since. **A job pinned that way goes green running stale, unmaintained code,
    and nothing says so**, which is worse than a tag that does not resolve at all.
    """
    pins = [use for use in _uses(path) if "setup-uv" in use]
    for pin in pins:
        ref = pin.split("@", 1)[1]
        assert re.fullmatch(r"v\d+\.\d+\.\d+", ref) or re.fullmatch(r"[0-9a-f]{40}", ref), (
            f"`{pin}` in {path.name} is a bare major or branch; setup-uv has no floating major "
            "tag, so this silently resolves to a frozen historical release"
        )


def test_the_gate_workflow_sets_up_uv_at_all() -> None:
    """The oracle above passes over a workflow that never mentions `setup-uv`, which is legitimate
    for a workflow that needs no interpreter and would be a hole in the one that does."""
    assert [use for use in _uses(_WORKFLOW) if "setup-uv" in use]


@pytest.mark.parametrize("path", _WORKFLOW_FILES, ids=lambda p: p.name)
def test_no_action_is_pinned_to_a_moving_branch(path: Path) -> None:
    """`@main` on a third-party action means the workflow's behaviour changes without a commit here,
    which is both a reproducibility problem and a supply-chain one.

    **A ref that is neither a full version nor a commit is moving unless it is a bare major**, and
    a bare major on a first-party action is a deliberate, documented alias. Anything else — a branch
    name like `release/v1`, which is what the PyPI publishing action's own docs recommend — moves
    under the workflow and is caught here rather than by a suffix list that has to guess the names.
    """
    moving = [
        use
        for use in _uses(path)
        if not re.fullmatch(r"v\d+(\.\d+\.\d+)?|[0-9a-f]{40}", use.split("@", 1)[1])
    ]
    assert not moving, f"{path.name} pins a moving ref: {moving}"


@pytest.mark.parametrize("job_name", _JOBS)
def test_every_job_runs_the_gate_itself_rather_than_a_copy_of_its_commands(
    workflow: dict[Any, Any], job_name: str
) -> None:
    """CI runs `check.sh`, not a transcription of its four commands. A second copy of the `--cov`
    list is a second place for it to go stale, which is the argument `check-matrix.sh` already makes
    by reusing this script through `ZIKARON_VENV`."""
    assert "./check.sh" in _run_text(_jobs(workflow)[job_name])
