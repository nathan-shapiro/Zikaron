"""The numbers a shipped hook entry states.

`architecture.md` §"The install contract" is normative. All are written into every installed hook
entry rather than inherited from the harness's own defaults, and all live here rather than in
`zikaron/install/` so there is exactly one place the installer reads them from.

**The injection budget is kiro-only**: Claude Code offers no field to raise it. This module is
deliberately not the general home for "what a harness will accept" — `zikaron.harness.spec` is, and
the runtime budget check reads it there.

**The timeout is one number in seconds, deliberately, and the conversions live at the edges.** Kiro
states `timeout_ms` in *milliseconds*; kiro's own array format states `timeout` in *seconds*; Claude
Code states `timeout` in *seconds* (measured, `research/claude-code-installer-probe.md` §2). That is
three spellings of one budget, and the corpus has already recorded the seconds-versus-milliseconds
trap between the first two. Keeping the canonical value in the coarser unit means the mistake that
matters — writing kiro's `10000` into a seconds field, which installs a **10,000-second** budget
during which a wedged hook blocks every user message with nothing reporting a problem — cannot be
made by copying a constant, because no constant here carries that number.
"""

from typing import Final

from zikaron.harness.spec import KIRO

#: The hook budget every shipped entry states, in **seconds**. Equal to kiro's own documented
#: default, and stated anyway: the corpus recorded that default as 30 s for two milestones on the
#: strength of the public docs, and a budget the hook's ~2 s internal deadline is sized against
#: should not be a number a harness release can move underneath it. Five times the internal
#: deadline, so our own failure path — which produces a `hook.log` line *and* a model-facing relay —
#: always fires before the harness's kill, which produces neither.
#:
#: It also has to clear the *tightest* default in the harness table, which is measured and is not
#: the one a casual reading finds: Claude Code defaults `UserPromptSubmit` to **30 s** against 600 s
#: for other events. 10 s sits inside that, so stating it never *raises* a budget we would not
#: otherwise have had.
HOOK_TIMEOUT_SECONDS: Final = 10

#: The same budget in kiro's object-format unit. Derived rather than declared, so the two can never
#: disagree about how long a hook may run.
TIMEOUT_MS: Final = HOOK_TIMEOUT_SECONDS * 1_000

#: `max_output_size` for a shipped kiro entry, in bytes. **Read from the harness table rather than
#: declared here**, because the same number is what the runtime oversize check measures an
#: operator's policy override against: two agreeing declarations of one harness's budget is the
#: drift shape this corpus has already paid for, and the table is the side that a design-document
#: test reads.
#:
#: Its margin is what makes overrun unreachable rather than merely unlikely, and both real worst
#: cases are asserted in the suite rather than estimated: the shipped policy text is ~6.1 kB, and a
#: five-row push block is bounded by the `gist` character bound at 6,429 UTF-16 code units — at most
#: ~19 kB of UTF-8 at the 3-bytes-per-unit ceiling. Both figures are stated in the unit they are
#: measured in, which this module of all places has to get right: a units count wearing a byte
#: suffix is exactly the conflation the runtime budget check exists to prevent.
MAX_OUTPUT_SIZE: Final = KIRO.injection_budget
