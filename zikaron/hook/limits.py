"""The two numbers a shipped hook entry states, declared once.

`architecture.md` §"The install contract" is normative. Both are written into every installed hook
entry rather than inherited from the harness's own defaults, and both live here rather than in
`zikaron/install/` so there is exactly one declaration: the installer reads these constants when it
writes an entry, and `write_policy.py` reads `MAX_OUTPUT_SIZE` at runtime to notice an override it
knows the harness will truncate. A value transcribed into the installer *and* asserted in the hook
would be two agreeing declarations of one contract, which is the drift shape this corpus has already
paid for once (`reviews/m7-consolidation-review.md`, round 2).

Its own module, not a constant inside `write_policy.py`, because the `userPromptSubmit` entry needs
the same two numbers and has nothing to do with the write policy. Two ints and a docstring cost
nothing measurable to import, which is the only reason a separate module is affordable on a path
this cost-sensitive (§Components, and `envelope.py`'s own docstring for what "cost-sensitive" turned
out to mean in practice).
"""

from typing import Final

#: `timeout_ms` for both shipped entries. Equal to the harness's own documented default (kiro-cli
#: 2.16.0), and stated anyway: the corpus recorded that default as 30 s for two milestones on the
#: strength of the public docs, and a budget the hook's ~2 s internal deadline is sized against
#: should not be a number a harness release can move underneath it. Five times the internal
#: deadline, so our own failure path — which produces a `hook.log` line *and* a model-facing relay —
#: always fires before the harness's kill, which produces neither.
TIMEOUT_MS: Final = 10_000

#: `max_output_size` for both shipped entries, in bytes. The harness default is 10240 and the
#: overrun behaviour is **truncation, not an error**, so the cost of being wrong is a silently
#: half-delivered write policy or a cut-off injected block. Set well above both real worst cases —
#: the shipped policy text is ~3 kB, and a five-row push block is a few kB at the largest
#: `gist_max_tokens` the config permits — because the margin is what makes the failure
#: unreachable rather than merely unlikely, and `tests/test_install_limits.py` asserts both fit.
MAX_OUTPUT_SIZE: Final = 65_536
