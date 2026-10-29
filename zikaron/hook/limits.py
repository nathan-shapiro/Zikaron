"""The one number a shipped hook entry states.

`architecture.md` §"The install contract" is normative. It is written into every installed hook
entry rather than inherited from the harness's own default, and lives here rather than in
`zikaron/install/` so there is exactly one place the installer reads it from. What a harness will
inject is not here: `zikaron.harness.spec` carries it, and the runtime budget check reads it there.

**The timeout is in seconds, the unit both harnesses' entries state.** Keeping the one constant in
the coarser unit means the mistake that matters — a millisecond figure in a seconds field, which
installs a budget a thousand times too long, during which a wedged hook blocks every user message
with nothing reporting a problem — cannot be made by copying a constant, because no constant here
carries that number.
"""

from typing import Final

#: The hook budget every shipped entry states, in **seconds**. Stated rather than inherited, because
#: the hook's internal deadlines are sized against it — the cold-start one is derived from it — and
#: a harness release should not be able to move it underneath them. Both expire first, so our own
#: failure path — which produces a `hook.log` line *and* a model-facing relay — always fires before
#: the harness's kill, which produces neither.
#:
#: It also has to clear the *tightest* default in the harness table, which is measured and is not
#: the one a casual reading finds: Claude Code defaults `UserPromptSubmit` to **30 s** against 600 s
#: for other events. 10 s sits inside that, so stating it never *raises* a budget we would not
#: otherwise have had.
HOOK_TIMEOUT_SECONDS: Final = 10
