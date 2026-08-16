"""The two numbers a shipped kiro hook entry states.

`architecture.md` §"The install contract" is normative. Both are written into every installed kiro
hook entry rather than inherited from the harness's own defaults, and both live here rather than in
`zikaron/install/` so there is exactly one place the installer reads them from.

**Only kiro's entries state either number.** Claude Code offers no field to raise its injection
budget and its hook timeout is a separate, unprobed question, so this module is deliberately not
the general home for "what a harness will accept" — `zikaron.harness.spec` is, and the runtime
budget check reads it there.
"""

from typing import Final

from zikaron.harness.spec import KIRO

#: `timeout_ms` for both shipped entries. Equal to the harness's own documented default, and stated
#: anyway: the corpus recorded that default as 30 s for two milestones on the strength of the public
#: docs, and a budget the hook's ~2 s internal deadline is sized against should not be a number a
#: harness release can move underneath it. Five times the internal deadline, so our own failure path
#: — which produces a `hook.log` line *and* a model-facing relay — always fires before the harness's
#: kill, which produces neither.
TIMEOUT_MS: Final = 10_000

#: `max_output_size` for a shipped kiro entry, in bytes. **Read from the harness table rather than
#: declared here**, because the same number is what the runtime oversize check measures an
#: operator's policy override against: two agreeing declarations of one harness's budget is the
#: drift shape this corpus has already paid for, and the table is the side that a design-document
#: test reads.
#:
#: Its margin is what makes overrun unreachable rather than merely unlikely, and both real worst
#: cases are asserted in the suite rather than estimated: the shipped policy text is ~5.5 kB, and a
#: five-row push block is bounded by the `gist` character bound at 6,087 UTF-16 code units — at most
#: ~18 kB of UTF-8 at the 3-bytes-per-unit ceiling. Both figures are stated in the unit they are
#: measured in, which this module of all places has to get right: a units count wearing a byte
#: suffix is exactly the conflation the runtime budget check exists to prevent.
MAX_OUTPUT_SIZE: Final = KIRO.injection_budget
