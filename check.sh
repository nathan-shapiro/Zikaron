#!/usr/bin/env bash
# The check gate. This is the per-edit gate and the definition of done for a change;
# `./check-matrix.sh`, which runs this whole script once per supported Python version, is
# additionally required before a milestone lands.
#
# **CI is not a third thing to run.** `.github/workflows/check.yml` asserts the *matrix's* claim —
# every supported version green on one tree — against a commit rather than a working tree, by
# running this script once per version rather than by running `check-matrix.sh` at all. So the tree
# identity comes from the SHA instead of from a fingerprint sampled twice. What it cannot do is
# dogfood: no live harness, so `integration_kiro` and `integration_claude` stay local-only.
# `design/distribution.md` §"What CI asserts" is normative.
#
# `ZIKARON_VENV` selects which virtualenv to run in, defaulting to `.venv`. That exists so
# `check-matrix.sh` can reuse this script rather than keep a second copy of the four commands below —
# the `--cov` list in particular is checked against the tree by a test, and a second copy of it would
# be a second place for it to go stale.
#
# `ZIKARON_CACHE_SUFFIX` gives this run its own coverage file and tool caches, so that several runs
# can share a working tree at the same time. Empty by default, which keeps a plain `./check.sh`
# writing exactly the paths it always did. `check-matrix.sh` sets it per Python version, because
# otherwise three concurrent runs write one `.coverage` between them — and a coverage floor computed
# from three interleaved runs is not a floor.
#
# The formatter's output is authoritative: a `format --check` failure means running
# `.venv/bin/ruff format .`, not adjusting the code by hand to satisfy it.
#
# The type check covers the tests as well as the package. The drift guards read the design
# documents and parse them, so an unchecked test suite would put the least-reviewed code in
# the repository in charge of deciding whether the most consequential tables are correct.
set -euo pipefail
cd "$(dirname "$0")"

venv="${ZIKARON_VENV:-.venv}/bin"

# Every path a concurrent run would otherwise share. With an empty suffix these are the defaults,
# spelled out rather than left implicit so that the set is visible in one place: anything added here
# later that writes to a fixed path has to join this list or parallel runs corrupt it.
suffix="${ZIKARON_CACHE_SUFFIX:-}"
export COVERAGE_FILE=".coverage${suffix}"
export RUFF_CACHE_DIR=".ruff_cache${suffix}"
export MYPY_CACHE_DIR=".mypy_cache${suffix}"
pytest_cache_dir=".pytest_cache${suffix}"

# `pytest-cov` writes one data file per process as `${COVERAGE_FILE}.<host>.<pid>.<n>` and combines
# every `${COVERAGE_FILE}.*` it finds at the end. Any death that skips that combine — a `SIGKILL`, a
# power loss, an OOM kill, and the `TERM` the matrix's own interrupt sends, since coverage saves only
# at exit while subprocesses that had already exited have saved theirs — leaves those fragments
# behind, and the *next* run folds them into its own report. Erasing them first makes each run's
# coverage its own. Guarded on the suffix so a plain `./check.sh` touches nothing it did not before.
if [[ -n "$suffix" ]]; then
    rm -f "${COVERAGE_FILE}".*
fi

"$venv/ruff" format --check .
"$venv/ruff" check .
"$venv/mypy" --strict zikaron tests
# Every shipped package, not only `core`. This said `--cov=zikaron/core` alone while `core` was the
# only package there was, and stayed that way when `service/` arrived — so the ratchet in
# `[tool.coverage.report] fail_under` was silently not applied to a whole package's production
# code. A floor that does not cover a package is not a floor. `zikaron/mcp` and `zikaron/hook` were
# each added here in the change that introduced them, rather than waiting for a coverage gap to
# surface it the way `service/` was left to.
#
# Wrapped in `timeout`: a real socket/thread/subprocess test that deadlocks — measured directly
# while the hook's socket tests were being written, not a hypothetical — would otherwise hang this
# gate indefinitely with no signal at all, which is a worse failure than a bounded one that at least
# reports "timed out" rather than leaving whoever ran the gate to guess whether it is slow or stuck.
#
# **The number is a hang detector, not a performance budget, so it is set with room to spare.** The
# whole suite measures ~150 s on this machine, and a large share of that is real model loads and
# real subprocess spawns in the `integration` tier — exactly the work that is slowest on a machine
# under other load, or on a colder one. A margin that merely clears today's figure would make this
# gate go red for being on a busy laptop, which is the same class of failure as a coverage floor set
# against a lucky run: a gate that can mislead is not a gate. Ten minutes is far above any honest
# run and far below the point where a genuine deadlock stops being obvious.
#
# **The gate is hermetic, and that is a property worth stating here rather than only in
# pyproject.** `manual`, `integration_kiro` and `integration_claude` are excluded by `addopts`. The
# harness two need a third-party binary installed *and working* — somebody else's credential state.
# An expired
# `kiro-cli` token once turned this script red for a reason with no relationship to the code, and
# the same tests would go green on a machine whose harness behaved differently. Run them by name
# when you mean to: `.venv/bin/pytest -m integration_kiro`. Nothing is covered *only* there; see
# `design/coding-standards.md` §"five tiers".
#
# **One deliberate exception to that hermeticity, and it is outside this script.** `check-matrix.sh`
# needs an interpreter per version it runs — a uv-managed one, an explicit `ZIKARON_PYTHON_3_13`, or
# a bare `python3.<minor>` on `PATH` as the last resort — machine state, which this script
# depends on nothing of. What it alone covers is the two version-dependent rows in
# `zikaron/service/asyncio_compat.py`: each is unexecuted on the interpreters that do not select it,
# so only a run under each version exercises both. This script stays hermetic and stays the gate for
# an ordinary edit.
#
# **Every package under `zikaron/`, and the list is checked rather than maintained by memory.** It
# was six for a while and should have been seven: `zikaron/knowledge` — the command that creates and
# builds corpora — was under no ratchet at all, which is invisible from a green gate, because a
# package nobody measures reports nothing rather than reporting zero. A test asserts this line names
# every package that exists, so the next one to be added fails here instead of being forgotten.
timeout 600 "$venv/pytest" -o "cache_dir=${pytest_cache_dir}" \
    --cov=zikaron/core --cov=zikaron/service --cov=zikaron/mcp \
    --cov=zikaron/hook --cov=zikaron/install --cov=zikaron/harness --cov=zikaron/knowledge
