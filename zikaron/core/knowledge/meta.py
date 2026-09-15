"""One knowledge base's `meta`: which keys exist at creation, and what each one accepts.

`knowledge-index.md`'s per-knowledge-base key list is authoritative and this module is its
executable form.
The contract it inherits from the memory store is the same one: **validation happens twice** —
written at creation, parsed and range-checked on every open — and a required key that is missing,
unparseable or out of range on open is fatal, never a silent fall-back to a default.

What differs from the memory store, and it is the whole reason this is a separate module rather
than a parameterization of that one: the keys are different, several are seeded from configuration
that the memory store has no opinion about, and **the ranges are read from `CONFIG_KEYS` rather
than restated here**. That last is deliberate. Four of these values are seeded from a configuration
key at creation, so a bound written here would be a second statement of one the configuration
schema already makes — and the two would be free to disagree the first time either moved.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final
from uuid import UUID

from zikaron.core.config.keys import CONFIG_KEYS_BY_NAME, IntBounds
from zikaron.core.errors import BadConfigSource, ErrorCode, ZikaronError

SCHEMA_VERSION_KEY: Final = "schema_version"
ID_KEY: Final = "id"
NAME_BREADCRUMB_KEY: Final = "name_breadcrumb"
ROOT_PATH_KEY: Final = "root_path"
INCLUDE_GLOBS_KEY: Final = "include_globs"
EXCLUDE_GLOBS_KEY: Final = "exclude_globs"
GIT_MODE_KEY: Final = "git_mode"
EMBED_MODEL_KEY: Final = "embed_model"
EMBED_DIM_KEY: Final = "embed_dim"
CHUNK_MAX_TOKENS_KEY: Final = "chunk_max_tokens"
RRF_K_KEY: Final = "rrf_k"
FUSION_DEPTH_KEY: Final = "fusion_depth"
MAX_FILE_BYTES_KEY: Final = "max_file_bytes"

LAST_SCAN_STARTED_AT_KEY: Final = "last_scan_started_at"
LAST_WALK_COMPLETED_AT_KEY: Final = "last_walk_completed_at"
LAST_SCAN_COMPLETED_AT_KEY: Final = "last_scan_completed_at"
LAST_SCAN_GIT_MODE_EFFECTIVE_KEY: Final = "last_scan_git_mode_effective"

LOCK_PID_KEY: Final = "lock_pid"
LOCK_HOST_KEY: Final = "lock_host"
LOCK_STARTED_AT_KEY: Final = "lock_started_at"

#: The schema version every table in this build implements, for a knowledge base's own `meta`.
#: Independent of `memory.db`'s: the two databases have different schemas that move separately,
#: and tying them together would make a knowledge-index change look like a memory-store one.
SUPPORTED_SCHEMA_VERSION: Final = 1

#: The configuration key each seeded value comes from, for the four whose bounds are declared
#: there. `max_file_bytes` is the one whose `meta` name differs from its configuration name,
#: because the configuration namespace is flat and shared with the memory store.
SEEDED_FROM_CONFIG: Final[Mapping[str, str]] = {
    CHUNK_MAX_TOKENS_KEY: "chunk_max_tokens",
    RRF_K_KEY: "rrf_k",
    FUSION_DEPTH_KEY: "fusion_depth",
    MAX_FILE_BYTES_KEY: "knowledge_max_file_bytes",
}


class GitMode(StrEnum):
    """How much git is consulted for this corpus.

    A closed set rather than a string, because each member names a different *candidate set* and
    a typo that fell through to a default would silently index a different corpus.
    """

    TRACKED = "tracked"
    ALL = "all"
    OFF = "off"


#: The scan-progress and skip-reason counters, plus the four search counters. Written at creation
#: so nothing
#: ever reads a missing key, and so `status` has an answer before any scan has run.
PROGRESS_KEYS: Final[tuple[str, ...]] = (
    "files_seen",
    "files_indexed",
    "files_skipped",
    "bytes_indexed",
)

SKIP_REASON_KEYS: Final[tuple[str, ...]] = (
    "skipped_binary",
    "skipped_denied_extension",
    "skipped_over_size_cap",
    "skipped_excluded_by_glob",
    "skipped_gitignored",
    "skipped_decode_error",
    "skipped_symlink",
    "skipped_unreadable",
    "pruned_directories",
)

SEARCH_COUNTER_KEYS: Final[tuple[str, ...]] = (
    "searches",
    "searches_empty",
    "results_returned",
    "results_stale",
)

#: Every counter seeded to zero at creation, in the order `defaults_at_creation` writes them.
COUNTER_KEYS: Final[tuple[str, ...]] = (
    *PROGRESS_KEYS,
    *SKIP_REASON_KEYS,
    *SEARCH_COUNTER_KEYS,
)

#: The identity and configuration keys required on every open, in the order they are validated.
REQUIRED_KEYS: Final[tuple[str, ...]] = (
    SCHEMA_VERSION_KEY,
    ID_KEY,
    NAME_BREADCRUMB_KEY,
    ROOT_PATH_KEY,
    INCLUDE_GLOBS_KEY,
    EXCLUDE_GLOBS_KEY,
    GIT_MODE_KEY,
    EMBED_MODEL_KEY,
    EMBED_DIM_KEY,
    CHUNK_MAX_TOKENS_KEY,
    RRF_K_KEY,
    FUSION_DEPTH_KEY,
    MAX_FILE_BYTES_KEY,
)

#: The keys whose **absence is the normal state**, and which are therefore exempt from
#: required-key validation. Nothing writes them until a scan starts or an indexer takes the lock,
#: and `last_scan_completed_at`'s absence is precisely what "no build has ever completed" means.
TRANSIENT_KEYS: Final[tuple[str, ...]] = (
    LAST_SCAN_STARTED_AT_KEY,
    LAST_WALK_COMPLETED_AT_KEY,
    LAST_SCAN_COMPLETED_AT_KEY,
    LAST_SCAN_GIT_MODE_EFFECTIVE_KEY,
    LOCK_PID_KEY,
    LOCK_HOST_KEY,
    LOCK_STARTED_AT_KEY,
)

_UUID4_STRING_LENGTH: Final = 36
_UUID_VERSION_4: Final = 4


@dataclass(frozen=True, slots=True)
class KnowledgeMeta:
    """One knowledge base's identity and configuration, parsed and range-checked.

    Constructing one *is* passing validation: every field has been read as its typed value and
    shown to lie in its stated range, so a caller holding one need not re-check any of them.

    `name_breadcrumb` is the non-authoritative copy of this corpus's name. It exists so an
    orphaned file is identifiable by a human, and the registry wins on any disagreement — so it
    is never the answer to "what is this knowledge base called" on a path where the registry is
    reachable.
    """

    schema_version: int
    id: UUID
    name_breadcrumb: str
    root_path: str
    include_globs: tuple[str, ...]
    exclude_globs: tuple[str, ...]
    git_mode: GitMode
    embed_model: str
    embed_dim: int
    chunk_max_tokens: int
    rrf_k: int
    fusion_depth: int
    max_file_bytes: int


def _bad_meta(key: str, value: str, expected: str) -> ZikaronError:
    return ZikaronError(
        ErrorCode.BAD_CONFIG,
        source=BadConfigSource.META,
        key=key,
        value=value,
        expected=expected,
    )


def _config_bounds(meta_key: str) -> IntBounds:
    """The integer bounds the configuration schema declares for a seeded key.

    Raises:
        TypeError: the configuration key is not integer-bounded. A programming error rather than
            a store error — it means this module's `SEEDED_FROM_CONFIG` names the wrong key.
    """
    bounds = CONFIG_KEYS_BY_NAME[SEEDED_FROM_CONFIG[meta_key]].bounds
    if not isinstance(bounds, IntBounds):
        raise TypeError(f"{meta_key} is seeded from a key that is not integer-bounded")
    return bounds


def _describe(bounds: IntBounds) -> str:
    if bounds.maximum is None:
        return f"int >= {bounds.minimum}"
    return f"int {bounds.minimum}-{bounds.maximum}"


def check_bounded(key: str, value: int) -> None:
    """Range-check a value a caller chose for a seeded key, against the configuration's own bounds.

    Exists so a per-corpus override and the global default it replaces are held to one range. A
    value one accepts and the other rejects would be a corpus nobody could reproduce by writing a
    configuration file.

    Raises:
        ZikaronError: `BAD_CONFIG` naming the key and the range it missed.
    """
    bounds = _config_bounds(key)
    if not bounds.permits(value):
        raise _bad_meta(key, str(value), _describe(bounds))


def _require_string(raw: Mapping[str, str], key: str, expected: str) -> str:
    if key not in raw:
        raise _bad_meta(key, "<missing>", expected)
    return raw[key]


def _require_non_empty(raw: Mapping[str, str], key: str, expected: str) -> str:
    value = _require_string(raw, key, expected)
    if value == "":
        raise _bad_meta(key, value, expected)
    return value


def _require_int(raw: Mapping[str, str], key: str, expected: str) -> int:
    text = _require_string(raw, key, expected)
    try:
        return int(text)
    except ValueError as error:
        raise _bad_meta(key, text, expected) from error


def _require_bounded_int(raw: Mapping[str, str], key: str) -> int:
    bounds = _config_bounds(key)
    expected = _describe(bounds)
    value = _require_int(raw, key, expected)
    if not bounds.permits(value):
        raise _bad_meta(key, str(value), expected)
    return value


def _require_globs(raw: Mapping[str, str], key: str) -> tuple[str, ...]:
    """A glob list, stored as a JSON array because `meta` values are text and globs are not.

    JSON rather than a separator-joined string: a glob may legitimately contain any character a
    separator could be, and a corpus silently losing a pattern because it held a comma is the
    kind of failure that shows up as missing files rather than as an error.
    """
    expected = "a JSON array of strings"
    text = _require_string(raw, key, expected)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as error:
        raise _bad_meta(key, text, expected) from error
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise _bad_meta(key, text, expected)
    return tuple(str(item) for item in parsed)


def parse_id(value: str) -> UUID:
    """One knowledge base's id, parsed rather than trusted.

    The single parser for this identifier, used wherever it is read back — the registry row and the
    knowledge base's own `meta` hold the same value, and two parsers of differing strictness would
    mean a value fatal in one place and silently accepted in the other.

    Version 4 specifically, not merely a well-formed uuid: this scheme depends on the name of a
    file being unpredictable, and a version 1 uuid encodes a MAC address and a timestamp. Path
    safety does not rest on the version — any uuid's string form is hex and dashes — so this is the
    identifier's contract rather than the security boundary.

    Raises:
        ValueError: `value` is not a 36-character version 4 uuid.
    """
    if len(value) != _UUID4_STRING_LENGTH:
        raise ValueError(f"not a 36-character uuid: {value!r}")
    try:
        parsed = UUID(value)
    except ValueError as error:
        # Re-raised in this parser's own words. `UUID` reports a 36-character non-hex string as a
        # failed base-16 conversion, which describes its own internals rather than the value a
        # caller supplied — and a caller catching this is told what was wrong with the id.
        raise ValueError(f"not a uuid: {value!r}") from error
    if parsed.version != _UUID_VERSION_4:
        raise ValueError(f"not a version 4 uuid: {value!r}")
    return parsed


def _require_uuid4(raw: Mapping[str, str], key: str) -> UUID:
    """The id from a `meta` row, as a store error rather than a bare `ValueError`.

    Parsing at the boundary is what keeps the path unforgeable: a row edited by hand into something
    path-shaped never becomes a `UUID`, so it never reaches a path.
    """
    expected = "uuid4 string, 36 chars"
    value = _require_string(raw, key, expected)
    try:
        return parse_id(value)
    except ValueError as error:
        raise _bad_meta(key, value, expected) from error


def parse_and_validate(raw: Mapping[str, str]) -> KnowledgeMeta:
    """Turn every required `meta` row's text value into `KnowledgeMeta`, or raise naming the first
    bad key.

    Args:
        raw: every `meta` row's text value, keyed by `key`. Counters and the transient keys are
            ignored here — they are not identity — and an unknown key a newer writer left behind
            is tolerated silently, as on the memory side.

    Raises:
        ZikaronError: `BAD_CONFIG` with `source='meta'`, naming the first required key found
            missing, unparseable, or out of its stated range. There is no partial value to return
            on failure.
    """
    schema_version = _require_int(raw, SCHEMA_VERSION_KEY, "int >= 1")
    if schema_version < 1:
        raise _bad_meta(SCHEMA_VERSION_KEY, str(schema_version), "int >= 1")
    git_mode_text = _require_string(raw, GIT_MODE_KEY, "one of tracked, all, off")
    try:
        git_mode = GitMode(git_mode_text)
    except ValueError as error:
        raise _bad_meta(GIT_MODE_KEY, git_mode_text, "one of tracked, all, off") from error
    embed_dim = _require_int(raw, EMBED_DIM_KEY, "int >= 1")
    if embed_dim < 1:
        raise _bad_meta(EMBED_DIM_KEY, str(embed_dim), "int >= 1")
    return KnowledgeMeta(
        schema_version=schema_version,
        id=_require_uuid4(raw, ID_KEY),
        name_breadcrumb=_require_non_empty(raw, NAME_BREADCRUMB_KEY, "non-empty string"),
        root_path=_require_non_empty(raw, ROOT_PATH_KEY, "non-empty string"),
        include_globs=_require_globs(raw, INCLUDE_GLOBS_KEY),
        exclude_globs=_require_globs(raw, EXCLUDE_GLOBS_KEY),
        git_mode=git_mode,
        embed_model=_require_non_empty(raw, EMBED_MODEL_KEY, "non-empty string"),
        embed_dim=embed_dim,
        chunk_max_tokens=_require_bounded_int(raw, CHUNK_MAX_TOKENS_KEY),
        rrf_k=_require_bounded_int(raw, RRF_K_KEY),
        fusion_depth=_require_bounded_int(raw, FUSION_DEPTH_KEY),
        max_file_bytes=_require_bounded_int(raw, MAX_FILE_BYTES_KEY),
    )


def defaults_at_creation(identity: KnowledgeMeta) -> Mapping[str, str]:
    """Every `meta` row a fresh knowledge base is created with, as text.

    The thirteen identity and configuration values, then every counter at zero. The four
    scan-outcome keys and the three lock keys are deliberately **absent**: a knowledge base that
    has not been scanned has no scan outcome, and writing a placeholder would make
    `last_scan_completed_at`'s absence — which is how *no build has ever completed* is recorded —
    unrepresentable.

    Args:
        identity: the values to seed, already validated by having been constructed.
    """
    seeded: dict[str, str] = {
        SCHEMA_VERSION_KEY: str(identity.schema_version),
        ID_KEY: str(identity.id),
        NAME_BREADCRUMB_KEY: identity.name_breadcrumb,
        ROOT_PATH_KEY: identity.root_path,
        INCLUDE_GLOBS_KEY: json.dumps(list(identity.include_globs)),
        EXCLUDE_GLOBS_KEY: json.dumps(list(identity.exclude_globs)),
        GIT_MODE_KEY: identity.git_mode.value,
        EMBED_MODEL_KEY: identity.embed_model,
        EMBED_DIM_KEY: str(identity.embed_dim),
        CHUNK_MAX_TOKENS_KEY: str(identity.chunk_max_tokens),
        RRF_K_KEY: str(identity.rrf_k),
        FUSION_DEPTH_KEY: str(identity.fusion_depth),
        MAX_FILE_BYTES_KEY: str(identity.max_file_bytes),
    }
    seeded.update(dict.fromkeys(COUNTER_KEYS, "0"))
    return seeded
