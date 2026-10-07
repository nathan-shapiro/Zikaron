"""Which of Zikaron's two products a project installs: the memory store, the edit guards, or both.

`design/edit-guards.md` §5 is normative. The installer takes the selection as `--components`, and
writes it into `zikaron-hook`'s start entries as the same flag, so the hook can build its start
text from the flag alone — no file read, no service query. A `memory` start entry carries no flag
at all, which keeps a default install's entry byte-for-byte what it always was.

>>> Components.GUARDS.union(Components.MEMORY)
<Components.BOTH: 'both'>
>>> Components.from_arguments(["--components", "guards"]), Components.from_arguments([])
(<Components.GUARDS: 'guards'>, <Components.MEMORY: 'memory'>)
>>> Components.BOTH.arguments, Components.MEMORY.arguments
(('--components', 'both'), ())
"""

import enum
from collections.abc import Sequence
from typing import Final

FLAG: Final = "--components"


class Components(enum.Enum):
    MEMORY = "memory"
    GUARDS = "guards"
    BOTH = "both"

    @property
    def memory(self) -> bool:
        return self is not Components.GUARDS

    @property
    def guards(self) -> bool:
        return self is not Components.MEMORY

    def union(self, other: "Components") -> "Components":
        """The selection carrying both this one's products and `other`'s."""
        memory, guards = self.memory or other.memory, self.guards or other.guards
        if memory and guards:
            return Components.BOTH
        return Components.MEMORY if memory else Components.GUARDS

    @property
    def arguments(self) -> tuple[str, ...]:
        """The arguments a start entry carries for this selection; none for `memory`."""
        return () if self is Components.MEMORY else (FLAG, self.value)

    @classmethod
    def from_arguments(cls, arguments: Sequence[str]) -> "Components":
        """The selection a start entry's arguments name.

        Anything but exactly `--components <selection>` reads as `memory`, which is what the
        entry did before the flag existed: a hook that misread its flag must still do the job it
        always did.
        """
        match tuple(arguments):
            case ("--components", value) if value in {member.value for member in cls}:
                return cls(value)
            case _:
                return cls.MEMORY
