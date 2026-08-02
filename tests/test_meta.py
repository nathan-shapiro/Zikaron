"""`meta`'s five required keys — parsed and range-checked, per `schema.md`'s init contract."""

import pytest

from zikaron.core.errors import BadConfigSource, ErrorCode, ZikaronError
from zikaron.core.store.meta import (
    CHUNK_MAX_TOKENS_KEY,
    EMBED_DIM_KEY,
    EMBED_MODEL_KEY,
    REINDEXING_KEY,
    REQUIRED_KEYS,
    SCHEMA_VERSION_KEY,
    STORE_ID_KEY,
    StoreMeta,
    defaults_at_creation,
    parse_and_validate,
)

_VALID_RAW = {
    SCHEMA_VERSION_KEY: "1",
    STORE_ID_KEY: "b75ccbfa-f71a-446e-8b81-265ff1f566e0",
    EMBED_MODEL_KEY: "BAAI/bge-small-en-v1.5",
    EMBED_DIM_KEY: "384",
    CHUNK_MAX_TOKENS_KEY: "450",
}


def test_a_fully_valid_row_set_parses_to_store_meta() -> None:
    result = parse_and_validate(_VALID_RAW)
    assert result == StoreMeta(
        schema_version=1,
        store_id="b75ccbfa-f71a-446e-8b81-265ff1f566e0",
        embed_model="BAAI/bge-small-en-v1.5",
        embed_dim=384,
        chunk_max_tokens=450,
    )


def test_an_unknown_extra_key_is_tolerated() -> None:
    """`schema.md`'s forward-compatibility rule: an unrecognized key on a supported schema
    version is left alone, not treated as a validation failure."""
    raw = {**_VALID_RAW, "some_future_key": "whatever"}
    assert parse_and_validate(raw).schema_version == 1


@pytest.mark.parametrize("key", REQUIRED_KEYS)
def test_a_missing_required_key_is_bad_config_naming_it(key: str) -> None:
    raw = {k: v for k, v in _VALID_RAW.items() if k != key}
    with pytest.raises(ZikaronError) as excinfo:
        parse_and_validate(raw)
    error = excinfo.value
    assert error.code is ErrorCode.BAD_CONFIG
    assert error.data["source"] == BadConfigSource.META
    assert error.data["key"] == key


def test_an_unparseable_schema_version_is_bad_config() -> None:
    raw = {**_VALID_RAW, SCHEMA_VERSION_KEY: "not-a-number"}
    with pytest.raises(ZikaronError) as excinfo:
        parse_and_validate(raw)
    assert excinfo.value.data["key"] == SCHEMA_VERSION_KEY


@pytest.mark.parametrize("value", ["0", "-1", "-100"])
def test_a_schema_version_below_one_is_bad_config(value: str) -> None:
    """`schema.md`'s migration posture: a value `< 1` is `bad_config`, distinctly from `> 1`,
    which is `schema_incompatible` and is checked by `Store.open`, not by this parser."""
    raw = {**_VALID_RAW, SCHEMA_VERSION_KEY: value}
    with pytest.raises(ZikaronError) as excinfo:
        parse_and_validate(raw)
    assert excinfo.value.data["key"] == SCHEMA_VERSION_KEY


def test_schema_version_two_parses_fine_here_since_the_ceiling_is_stores_job() -> None:
    """`parse_and_validate` enforces the *floor* (`>= 1`); the ceiling (`<= SUPPORTED`) is
    `Store.open`'s job, since a value the store does not support is `schema_incompatible`, a
    different error entirely, and this parser must not pre-empt that distinction."""
    raw = {**_VALID_RAW, SCHEMA_VERSION_KEY: "2"}
    assert parse_and_validate(raw).schema_version == 2


def test_a_store_id_of_the_wrong_length_is_bad_config() -> None:
    raw = {**_VALID_RAW, STORE_ID_KEY: "too-short"}
    with pytest.raises(ZikaronError) as excinfo:
        parse_and_validate(raw)
    assert excinfo.value.data["key"] == STORE_ID_KEY


def test_a_36_character_string_that_is_not_a_real_uuid_is_bad_config() -> None:
    """Length alone is not the contract: `schema.md` says `store_id` is `uuid4`, so a
    36-character string that merely has the right length but is not valid UUID syntax at all
    must be rejected rather than accepted on length alone."""
    raw = {**_VALID_RAW, STORE_ID_KEY: "not-a-uuid-at-all-but-36-characters!"}
    with pytest.raises(ZikaronError) as excinfo:
        parse_and_validate(raw)
    assert excinfo.value.data["key"] == STORE_ID_KEY


def test_a_well_formed_but_wrong_version_uuid_is_bad_config() -> None:
    """A syntactically valid UUID that is not version 4 — e.g. a version-1 (time-based) UUID —
    must be rejected: `schema.md` names `uuid4` specifically, not "any UUID"."""
    version_1_uuid = "6ba7b810-9dad-11d1-80b4-00c04fd430c8"
    raw = {**_VALID_RAW, STORE_ID_KEY: version_1_uuid}
    with pytest.raises(ZikaronError) as excinfo:
        parse_and_validate(raw)
    assert excinfo.value.data["key"] == STORE_ID_KEY


def test_an_empty_embed_model_is_bad_config() -> None:
    raw = {**_VALID_RAW, EMBED_MODEL_KEY: ""}
    with pytest.raises(ZikaronError) as excinfo:
        parse_and_validate(raw)
    assert excinfo.value.data["key"] == EMBED_MODEL_KEY


@pytest.mark.parametrize("value", ["0", "-1", "not-an-int"])
def test_an_embed_dim_below_one_or_unparseable_is_bad_config(value: str) -> None:
    raw = {**_VALID_RAW, EMBED_DIM_KEY: value}
    with pytest.raises(ZikaronError) as excinfo:
        parse_and_validate(raw)
    assert excinfo.value.data["key"] == EMBED_DIM_KEY


@pytest.mark.parametrize("value", ["63", "8193", "not-an-int"])
def test_a_chunk_max_tokens_outside_64_to_8192_or_unparseable_is_bad_config(value: str) -> None:
    raw = {**_VALID_RAW, CHUNK_MAX_TOKENS_KEY: value}
    with pytest.raises(ZikaronError) as excinfo:
        parse_and_validate(raw)
    assert excinfo.value.data["key"] == CHUNK_MAX_TOKENS_KEY


@pytest.mark.parametrize("value", ["64", "8192"])
def test_chunk_max_tokens_accepts_both_of_its_own_boundaries(value: str) -> None:
    raw = {**_VALID_RAW, CHUNK_MAX_TOKENS_KEY: value}
    assert parse_and_validate(raw).chunk_max_tokens == int(value)


def test_defaults_at_creation_round_trips_through_parse_and_validate() -> None:
    defaults = defaults_at_creation(
        schema_version=1,
        store_id="b75ccbfa-f71a-446e-8b81-265ff1f566e0",
        embed_model="BAAI/bge-small-en-v1.5",
        embed_dim=384,
        chunk_max_tokens=450,
    )
    assert set(defaults) == set(REQUIRED_KEYS)
    result = parse_and_validate(defaults)
    assert result.schema_version == 1
    assert result.store_id == "b75ccbfa-f71a-446e-8b81-265ff1f566e0"
    assert result.embed_model == "BAAI/bge-small-en-v1.5"
    assert result.embed_dim == 384
    assert result.chunk_max_tokens == 450


def test_the_reindexing_sentinel_key_is_not_one_of_the_required_keys() -> None:
    """`schema.md` states the sentinel's absence is normal — it must be exempt from the
    required-key validation `parse_and_validate` enforces, not merely absent from a fixture."""
    assert REINDEXING_KEY not in REQUIRED_KEYS


def test_absence_of_the_reindexing_key_does_not_fail_validation() -> None:
    assert REINDEXING_KEY not in _VALID_RAW
    parse_and_validate(_VALID_RAW)  # must not raise
