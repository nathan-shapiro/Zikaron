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
# production code. A floor that does not cover a package is not a floor.
"$venv/pytest" --cov=zikaron/core --cov=zikaron/service
