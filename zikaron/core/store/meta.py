"""`meta`'s five required keys, and the `reindexing` sentinel that is deliberately not one of them.

`schema.md` §"`meta` — the store-coupled values, and the initialization contract" is normative.
Two facts from it drive this module's shape: validation happens **twice** — written at creation,
parsed and range-checked on **every** open — and a required key that is missing, unparseable or
out of range on open is a fatal `bad_config`, never a silent fall-back to a default. `reindexing`
is a transient key whose *absence* is normal, so it is exempt from that required-key validation
and handled by its own present/absent check instead.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from zikaron.core.errors import BadConfigSource, ErrorCode, ZikaronError

#: The `meta` row key naming the schema a store records. What this build *supports* is a range
#: (`store.SUPPORTED_SCHEMA_VERSIONS`, `schema.md` §"Migration posture"), and
#: `ERROR_SPECS[SCHEMA_INCOMPATIBLE]`'s `supported` field carries the whole of it rather than a
#: fixed value — `test_store.py` holds the two against each other, so neither drifts alone.
SCHEMA_VERSION_KEY: Final = "schema_version"
STORE_ID_KEY: Final = "store_id"
EMBED_MODEL_KEY: Final = "embed_model"
EMBED_DIM_KEY: Final = "embed_dim"
CHUNK_MAX_TOKENS_KEY: Final = "chunk_max_tokens"

#: The transient sentinel `schema.md` explicitly excludes from required-key validation: normal
#: absence, abnormal presence. Its value is the ISO-8601 instant the unavailable window opened.
REINDEXING_KEY: Final = "reindexing"

#: The five keys required on every open, in the order this module reads and validates them.
REQUIRED_KEYS: Final[tuple[str, ...]] = (
    SCHEMA_VERSION_KEY,
    STORE_ID_KEY,
    EMBED_MODEL_KEY,
    EMBED_DIM_KEY,
    CHUNK_MAX_TOKENS_KEY,
)

_CHUNK_MAX_TOKENS_MIN: Final = 64
_CHUNK_MAX_TOKENS_MAX: Final = 8192
_UUID4_STRING_LENGTH: Final = 36
_UUID_VERSION_4: Final = 4


@dataclass(frozen=True, slots=True)
class StoreMeta:
    """The five required `meta` values, parsed and range-checked.

    Constructing one *is* passing validation: every field has already been read as its typed
    value and shown to lie in its stated range, so a caller holding a `StoreMeta` need not
    re-check any of them.
    """

    schema_version: int
    store_id: str
    embed_model: str
    embed_dim: int
    chunk_max_tokens: int


def _bad_meta(key: str, value: str, expected: str) -> ZikaronError:
    return ZikaronError(
        ErrorCode.BAD_CONFIG,
        source=BadConfigSource.META,
        key=key,
        value=value,
        expected=expected,
    )


def _require_int(raw: Mapping[str, str], key: str, expected: str) -> int:
    if key not in raw:
        raise _bad_meta(key, "<missing>", expected)
    text = raw[key]
    try:
        return int(text)
    except ValueError as error:
        raise _bad_meta(key, text, expected) from error


def _require_string(raw: Mapping[str, str], key: str, expected: str) -> str:
    if key not in raw:
        raise _bad_meta(key, "<missing>", expected)
    return raw[key]


def parse_and_validate(raw: Mapping[str, str]) -> StoreMeta:
    """Turn every `meta` row's text value into `StoreMeta`, or raise naming the first bad key.

    Args:
        raw: every `meta` row's text value, keyed by `key`. Extra keys (an unknown setting a
            newer writer left behind) are tolerated silently, per `schema.md`'s forward-
            compatibility rule for a *supported* schema version.

    Raises:
        ZikaronError: `BAD_CONFIG` with `source='meta'`, naming the first required key found
            missing, unparseable, or out of its stated range. There is no partial `StoreMeta` to
            return on failure, per `schema.md`'s "fatal store error, not a fall-back" rule.
    """
    schema_version = _require_int(raw, SCHEMA_VERSION_KEY, "int >= 1")
    if schema_version < 1:
        raise _bad_meta(SCHEMA_VERSION_KEY, str(schema_version), "int >= 1")
    store_id = _require_string(raw, STORE_ID_KEY, "uuid4 string, 36 chars")
    if len(store_id) != _UUID4_STRING_LENGTH:
        raise _bad_meta(STORE_ID_KEY, store_id, "uuid4 string, 36 chars")
    try:
        parsed_store_id = UUID(store_id)
    except ValueError as error:
        raise _bad_meta(STORE_ID_KEY, store_id, "uuid4 string, 36 chars") from error
    if parsed_store_id.version != _UUID_VERSION_4:
        raise _bad_meta(STORE_ID_KEY, store_id, "uuid4 string, 36 chars")
    embed_model = _require_string(raw, EMBED_MODEL_KEY, "non-empty string")
    if embed_model == "":
        raise _bad_meta(EMBED_MODEL_KEY, embed_model, "non-empty string")
    embed_dim = _require_int(raw, EMBED_DIM_KEY, "int >= 1")
    if embed_dim < 1:
        raise _bad_meta(EMBED_DIM_KEY, str(embed_dim), "int >= 1")
    chunk_max_tokens = _require_int(
        raw, CHUNK_MAX_TOKENS_KEY, f"int {_CHUNK_MAX_TOKENS_MIN}-{_CHUNK_MAX_TOKENS_MAX}"
    )
    if not (_CHUNK_MAX_TOKENS_MIN <= chunk_max_tokens <= _CHUNK_MAX_TOKENS_MAX):
        raise _bad_meta(
            CHUNK_MAX_TOKENS_KEY,
            str(chunk_max_tokens),
            f"int {_CHUNK_MAX_TOKENS_MIN}-{_CHUNK_MAX_TOKENS_MAX}",
        )
    return StoreMeta(
        schema_version=schema_version,
        store_id=store_id,
        embed_model=embed_model,
        embed_dim=embed_dim,
        chunk_max_tokens=chunk_max_tokens,
    )


def defaults_at_creation(
    schema_version: int, store_id: str, embed_model: str, embed_dim: int, chunk_max_tokens: int
) -> Mapping[str, str]:
    """Every required `meta` row's text value at store creation, in `REQUIRED_KEYS` order.

    `schema.md` requires a fresh store to be "fully described" so nothing on open reads a
    missing key — this is the write side of that promise, called once by `Store.create` after
    every value it takes has already been validated by whoever assembled them.
    """
    return {
        SCHEMA_VERSION_KEY: str(schema_version),
        STORE_ID_KEY: store_id,
        EMBED_MODEL_KEY: embed_model,
        EMBED_DIM_KEY: str(embed_dim),
        CHUNK_MAX_TOKENS_KEY: str(chunk_max_tokens),
    }
