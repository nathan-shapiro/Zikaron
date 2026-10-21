"""When each agent was last reminded that its search reached documented code.

`design/code-knowledge.md` §6 is normative. Kept in memory for the life of the service, so a restart
costs at most one extra reminder, and keyed by agent: the session label, and inside a subagent its
`agent_id`, since a subagent starts with a fresh context that holds none of its parent's reminders.

Every method is synchronous: the service runs one event loop, so a check and the stamp it earns
cannot be interleaved by another request — two hooks one search starts yield one reminder.
"""

from dataclasses import dataclass, field

#: An agent, as the throttle knows one: its session label and, for a subagent, its `agent_id`.
type Agent = tuple[str, str | None]


@dataclass(slots=True)
class ReminderTimes:
    """Each agent's last reminder, on the monotonic clock."""

    _last: dict[Agent, float] = field(default_factory=dict)

    def clear(self, label: str) -> None:
        """A user prompt opened the session's turn, so its next such search reminds."""
        self._last.pop((label, None), None)

    def note_searched(self, label: str, *, now: float) -> None:
        """The session searched its code knowledge itself, which counts as its reminder."""
        self._last[(label, None)] = now

    def take(self, label: str, agent_id: str | None, *, now: float, interval: float) -> bool:
        """Whether this agent is due a reminder, recording that it was given one when it is.

        Every entry already past `interval` is dropped first, so the table holds only agents still
        searching.
        """
        self._last = {agent: at for agent, at in self._last.items() if now - at < interval}
        agent = (label, agent_id)
        if agent in self._last:
            return False
        self._last[agent] = now
        return True
