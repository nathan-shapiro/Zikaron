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
# rather than leaving whoever ran the gate to guess whether it is slow or stuck.
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
# pyproject.** `integration_kiro` and `integration_claude` are excluded by `addopts`, because they
# need a third-party binary installed *and working* — somebody else's credential state. An expired
# `kiro-cli` token once turned this script red for a reason with no relationship to the code, and
# the same tests would go green on a machine whose harness behaved differently. Run them by name
# when you mean to: `.venv/bin/pytest -m integration_kiro`. Nothing is covered *only* there; see
# `design/coding-standards.md` §"five tiers".
# **Every package under `zikaron/`, and the list is checked rather than maintained by memory.** It
# was six for a while and should have been seven: `zikaron/knowledge` — the command that creates and
# builds corpora — was under no ratchet at all, which is invisible from a green gate, because a
# package nobody measures reports nothing rather than reporting zero. A test asserts this line names
# every package that exists, so the next one to be added fails here instead of being forgotten.
timeout 600 "$venv/pytest" --cov=zikaron/core --cov=zikaron/service --cov=zikaron/mcp \
    --cov=zikaron/hook --cov=zikaron/install --cov=zikaron/harness --cov=zikaron/knowledge
