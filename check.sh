#!/usr/bin/env bash
# The check gate. Nothing is done until this exits 0.
#
# The formatter's output is authoritative: a `format --check` failure means running
# `.venv/bin/ruff format .`, not adjusting the code by hand to satisfy it.
#
# The type check covers the tests as well as the package. The drift guards read the design
# documents and parse them, so an unchecked test suite would put the least-reviewed code in
# the repository in charge of deciding whether the most consequential tables are correct.
set -euo pipefail
cd "$(dirname "$0")"

venv=.venv/bin

"$venv/ruff" format --check .
"$venv/ruff" check .
"$venv/mypy" --strict zikaron tests
# Every shipped package, not only `core`. This said `--cov=zikaron/core` alone from M1, when
# `core` was the only package there was, and stayed that way when M9 added `service/` — so the
# ratchet in `[tool.coverage.report] fail_under` was silently not applied to a whole milestone's
# production code. A floor that does not cover a package is not a floor. `zikaron/mcp` and
# `zikaron/hook` are each added here at the same time M10 and M11 introduce them, rather than
# waiting for a coverage gap to surface it the way `service/` was left to.
#
# Wrapped in `timeout`: a real socket/thread/subprocess test that deadlocks — measured directly
# during M11's own build, not a hypothetical — would otherwise hang this gate indefinitely with
# no signal at all, which is a worse failure than a bounded one that at least reports "timed out"
# rather than leaving whoever ran the gate to guess whether it is slow or stuck. 300 s is generous
# relative to the whole suite's own measured ~60 s, including real `fastembed`/`sqlite-vec`
# loading and real subprocess spawns in the `integration` tier — comfortable margin for a slower
# machine without masking a genuine hang for minutes on this one.
timeout 300 "$venv/pytest" --cov=zikaron/core --cov=zikaron/service --cov=zikaron/mcp \
    --cov=zikaron/hook --cov=zikaron/install --cov=zikaron/harness
