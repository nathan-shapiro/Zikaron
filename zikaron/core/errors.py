"""The wire error contract: one code per rejection, with its message and its `data` shape.

Two independently written clients have to agree on what a rejection means, so the codes are a
contract rather than an implementation detail. They live here as one enum and one table; no
call site anywhere may name a bare integer, a payload field or one of the values a payload
field is allowed to take.

This module deliberately stops short of the wire envelope. It says what a rejection *is* — its
code, its human message, and the exact fields its payload carries, in order — and leaves
`{code, message, data}` framing to whoever owns the transport.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from types import MappingProxyType
from typing import Final

# JSON-RPC 2.0 reserves -32768..-32000 and leaves the top of that band to the application.
# Zikaron claims the hundred codes below -32000, so a Zikaron rejection is distinguishable
# from a protocol-level one by its numeric range alone, with no out-of-band agreement.
APPLICATION_CODE_MIN: Final = -32099
APPLICATION_CODE_MAX: Final = -32000


class ErrorCode(IntEnum):
    """Every rejection Zikaron can return, by the code that goes on the wire."""

    NOT_FOUND = -32000
    VERSION_CONFLICT = -32001
    NO_READ_RECEIPT = -32002
    INACTIVE_ROW = -32003
    BAD_SUPERSESSION = -32004
    BOUNDS = -32005
    GROUP_UNKNOWN = -32010
    GROUP_EXPIRED = -32011
    GROUP_COMPLETE = -32012
    NOT_IN_GROUP = -32013
    BAD_MERGE_TARGET = -32014
    GROUP_DEFERRED = -32015
    STORE_BUSY = -32020
    INDEX_FAILED = -32021
    REINDEXING = -32022
    BAD_CONFIG = -32023
    SCHEMA_INCOMPATIBLE = -32024
    STORE_IDENTITY = -32030

    @property
    def wire_name(self) -> str:
        """The stable snake_case name for this code, for logs and agent-facing responses."""
        return self.name.lower()


class BadConfigSource(StrEnum):
    """Where a bad configuration value came from, which decides what can be done about it."""

    META = "meta"
    FILE = "file"


class BadMergeTargetReason(StrEnum):
    """Why a merge target was refused.

    `NOT_AUTHORIZED` deliberately covers every uuid outside the group's authorization set
    whether or not it exists, so the rejection cannot be used to discover what the store holds.
    """

    NOT_AUTHORIZED = "not_authorized"
    NOT_TARGETABLE = "not_targetable"


@dataclass(frozen=True, slots=True)
class PayloadField:
    """One key of an error's `data` object.

    `values` is the closed set the contract states for the field, and is empty when the value is
    open — a uuid, a count, a whole record. A set of exactly one member is a **constant**: there
    is nothing for a raise site to decide, so it may omit the field and have the contract supply
    it. Two or more members is a choice, and a value outside the set is a programming error
    either way.

    `required` is about the raise site's obligation, not about the value: only a field the
    contract says may be absent from a well-formed payload is optional.
    """

    name: str
    values: tuple[str | int, ...] = ()
    required: bool = True

    @property
    def is_constant(self) -> bool:
        """Whether the contract fixes the value, leaving a raise site nothing to say."""
        return len(self.values) == 1


@dataclass(frozen=True, slots=True)
class ErrorSpec:
    """What one code says, and what its payload carries.

    The fields are ordered, and that order is the order they are serialized in, so two
    implementations of one rejection produce the same payload rather than merely equivalent
    ones.
    """

    message: str
    data_fields: tuple[PayloadField, ...]

    def __post_init__(self) -> None:
        names = [field.name for field in self.data_fields]
        if len(set(names)) != len(names):
            raise ValueError(f"payload declares a field twice: {names}")

    @property
    def field_names(self) -> tuple[str, ...]:
        """Every field of this payload, in the order the contract states them."""
        return tuple(field.name for field in self.data_fields)


ERROR_SPECS: Final[Mapping[ErrorCode, ErrorSpec]] = MappingProxyType(
    {
        ErrorCode.NOT_FOUND: ErrorSpec(
            "no memory with that uuid",
            (PayloadField("uuid"),),
        ),
        ErrorCode.VERSION_CONFLICT: ErrorSpec(
            "the presented version is not the current one",
            (PayloadField("current"),),
        ),
        ErrorCode.NO_READ_RECEIPT: ErrorSpec(
            "no read receipt for that uuid at the presented version",
            (
                PayloadField("uuids"),
                PayloadField("hint", values=("fetch it first",)),
            ),
        ),
        ErrorCode.INACTIVE_ROW: ErrorSpec(
            "that memory is already inactive",
            (PayloadField("uuid"), PayloadField("state")),
        ),
        ErrorCode.BAD_SUPERSESSION: ErrorSpec(
            "illegal supersession edge",
            (PayloadField("uuid"), PayloadField("target"), PayloadField("reason")),
        ),
        ErrorCode.BOUNDS: ErrorSpec(
            "a field is outside its permitted bounds",
            (PayloadField("field"), PayloadField("limit"), PayloadField("actual")),
        ),
        ErrorCode.GROUP_UNKNOWN: ErrorSpec(
            "no consolidation group with that id",
            (PayloadField("group_id"),),
        ),
        ErrorCode.GROUP_EXPIRED: ErrorSpec(
            "that group's consolidation run is not effectively active",
            (
                PayloadField("group_id"),
                PayloadField("run_status"),
                PayloadField("expires_at"),
                PayloadField("effective_status"),
            ),
        ),
        ErrorCode.GROUP_COMPLETE: ErrorSpec(
            "every member of that group is already dispositioned",
            (PayloadField("group_id"),),
        ),
        ErrorCode.NOT_IN_GROUP: ErrorSpec(
            "not an actionable member of that group",
            (PayloadField("group_id"), PayloadField("uuids")),
        ),
        ErrorCode.BAD_MERGE_TARGET: ErrorSpec(
            "not a legal merge target for that group",
            (
                PayloadField("group_id"),
                PayloadField("uuid"),
                PayloadField("reason", values=tuple(BadMergeTargetReason)),
            ),
        ),
        ErrorCode.GROUP_DEFERRED: ErrorSpec(
            "that group was deferred for the rest of the run",
            (PayloadField("group_id"), PayloadField("serve_count")),
        ),
        ErrorCode.STORE_BUSY: ErrorSpec(
            "the store stayed locked past the busy timeout",
            (PayloadField("verb"),),
        ),
        ErrorCode.INDEX_FAILED: ErrorSpec(
            "index maintenance failed and the transaction rolled back",
            (PayloadField("stage"),),
        ),
        ErrorCode.REINDEXING: ErrorSpec(
            "the store is reindexing and cannot be read",
            (PayloadField("since"),),
        ),
        ErrorCode.BAD_CONFIG: ErrorSpec(
            "a configuration value is missing, unparseable or out of range",
            (
                PayloadField("source", values=tuple(BadConfigSource)),
                # A store value has no file to name, and inventing one would point an operator
                # at a file the bad value did not come from.
                PayloadField("file", required=False),
                PayloadField("key"),
                PayloadField("value"),
                PayloadField("expected"),
            ),
        ),
        ErrorCode.SCHEMA_INCOMPATIBLE: ErrorSpec(
            "the store's schema version is newer than this build supports",
            (PayloadField("found"), PayloadField("supported", values=(1,))),
        ),
        ErrorCode.STORE_IDENTITY: ErrorSpec(
            "that service belongs to a different store",
            (PayloadField("expected"), PayloadField("actual")),
        ),
    }
)


def _wire_type(value: object) -> type:
    """The JSON type a value serializes as, ignoring which Python subclass produced it.

    An enum member and its plain value serialize identically, so they are deliberately the same
    here. A `bool` and an `int` do not — `true` is not `1` on the wire — so `bool` is tested ahead
    of `int`, which it subclasses.
    """
    for wire in (bool, int, float, str):
        if isinstance(value, wire):
            return wire
    return type(value)


def _matches(value: object, declared: str | int) -> bool:
    return _wire_type(value) is _wire_type(declared) and value == declared


class ZikaronError(Exception):
    """A rejection carrying a wire code — the only exception type Zikaron returns to a client.

    Construct it with the code and its payload as keyword arguments. The payload is checked
    against the code's declared shape at construction, so a raise site that has drifted from the
    contract fails where it was written rather than at the client that receives it. A field whose
    value the contract fixes may be omitted and will be filled in.

    A closed set is matched on the value *and* the type it will serialize as, so a field the
    contract declares as the integer 1 accepts neither `True` nor `1.0`. An enum member and its
    plain value stay interchangeable, since those do serialize the same.

    Raises:
        TypeError: the payload omits a required field or names one the code does not carry.
        ValueError: a field was given a value outside the closed set the contract states for it.
    """

    def __init__(self, code: ErrorCode, **data: object) -> None:
        spec = ERROR_SPECS[code]
        supplied = dict(data)
        payload: dict[str, object] = {}
        missing: list[str] = []
        for declared in spec.data_fields:
            if declared.name in supplied:
                value = supplied.pop(declared.name)
                if declared.values and not any(_matches(value, one) for one in declared.values):
                    raise ValueError(
                        f"{code.wire_name}.{declared.name}: {value!r} is not one of "
                        f"{list(declared.values)}"
                    )
                payload[declared.name] = value
            elif declared.is_constant:
                payload[declared.name] = declared.values[0]
            elif declared.required:
                missing.append(declared.name)
        if supplied or missing:
            raise TypeError(
                f"{code.wire_name} payload mismatch: unknown={sorted(supplied)} missing={missing}"
            )
        self.code: Final = code
        self.message: Final = spec.message
        self.data: Final[Mapping[str, object]] = MappingProxyType(payload)
        super().__init__(f"{code.wire_name}: {spec.message}")
