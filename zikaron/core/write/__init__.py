"""The tool-facing write path: the remember, amend and retire verbs."""

from zikaron.core.write.dedup import DedupPolicy, NearDuplicate, offer
from zikaron.core.write.tools import (
    Amended,
    AmendOutcome,
    Conflict,
    Remembered,
    RememberOutcome,
    Retired,
    RetireOutcome,
    WriteCall,
    amend,
    remember,
    retire,
)

__all__ = [
    "AmendOutcome",
    "Amended",
    "Conflict",
    "DedupPolicy",
    "NearDuplicate",
    "RememberOutcome",
    "Remembered",
    "RetireOutcome",
    "Retired",
    "WriteCall",
    "amend",
    "offer",
    "remember",
    "retire",
]
