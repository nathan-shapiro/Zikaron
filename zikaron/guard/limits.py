"""The number every installed guard entry states (`design/edit-guards.md` §5)."""

from typing import Final

#: Each guard entry's `timeout`, in seconds: the worst stall a wedged guard can cost one tool call.
#: Far above one Python start, far below the 600 s an unstated timeout would inherit. Independent of
#: the memory hook's budget, which is sized to that hook's own internal deadlines.
TIMEOUT_SECONDS: Final = 10
