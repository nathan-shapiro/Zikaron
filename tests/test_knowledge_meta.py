"""One knowledge base's `meta`: what is written at creation, and what is refused on open.

The contract inherited from the memory store is that validation happens twice and that a required
key which is missing, unparseable or out of range is fatal rather than quietly defaulted. These
tests are the second half of that: every required key is shown to be refusable, because a
validator that accepted a bad value would substitute a default and let two stores rank differently
while both looked healthy.
"""

import json
import uuid
from collections.abc import Mapping

import pytest

from zikaron.core.config.keys import CONFIG_KEYS_BY_NAME, IntBounds
from zikaron.core.errors import BadConfigSource, ErrorCode, ZikaronError
from zikaron.core.knowledge import meta


def _identity(**overrides: object) -> meta.KnowledgeMeta:
    base: dict[str, object] = {
        "schema_version": meta.SUPPORTED_SCHEMA_VERSION,
        "id": uuid.uuid4(),
        "name_breadcrumb": "docs",
        "root_path": "/a/corpus/root",
        "include_globs": (),
        "exclude_globs": (),
        "git_mode": meta.GitMode.TRACKED,
        "embed_model": "BAAI/bge-small-en-v1.5",
        "embed_dim": 384,
        "chunk_max_tokens": 450,
        "rrf_k": 60,
        "fusion_depth": 50,
        "max_file_bytes": 1_048_576,
    }
    base.update(overrides)
    return meta.KnowledgeMeta(**base)  # type: ignore[arg-type]


def _rows(**overrides: str) -> dict[str, str]:
    written = dict(meta.defaults_at_creation(_identity()))
    written.update(overrides)
    return written


class TestWhatIsWrittenAtCreation:
    def test_every_required_key_and_every_counter_is_written(self) -> None:
        written = meta.defaults_at_creation(_identity())
        for key in (*meta.REQUIRED_KEYS, *meta.COUNTER_KEYS):
            assert key in written, key

    def test_every_counter_starts_at_zero(self) -> None:
        written = meta.defaults_at_creation(_identity())
        assert {written[key] for key in meta.COUNTER_KEYS} == {"0"}

    def test_no_transient_key_is_written(self) -> None:
        """Their absence is the normal state, and one of them carries real meaning by being
        absent: a knowledge base that has never completed a build has no completion instant, and
        seeding a placeholder would make that state unrepresentable."""
        written = meta.defaults_at_creation(_identity())
        for key in meta.TRANSIENT_KEYS:
            assert key not in written, key

    def test_the_three_key_groups_do_not_overlap(self) -> None:
        """Required, counter and transient are three disjoint sets, because each is handled by a
        different rule — validated strictly, defaulted to zero, or allowed to be missing — and a
        key in two of them would be handled by whichever rule ran last."""
        groups = [set(meta.REQUIRED_KEYS), set(meta.COUNTER_KEYS), set(meta.TRANSIENT_KEYS)]
        for first in range(len(groups)):
            for second in range(first + 1, len(groups)):
                assert not groups[first] & groups[second]

    def test_what_is_written_round_trips_through_validation(self) -> None:
        identity = _identity(include_globs=("*.md",), exclude_globs=("draft/*",))
        assert meta.parse_and_validate(meta.defaults_at_creation(identity)) == identity


class TestWhatIsRefusedOnOpen:
    @pytest.mark.parametrize("key", meta.REQUIRED_KEYS)
    def test_a_missing_required_key_is_fatal(self, key: str) -> None:
        rows = _rows()
        del rows[key]
        with pytest.raises(ZikaronError) as caught:
            meta.parse_and_validate(rows)
        assert caught.value.code is ErrorCode.BAD_CONFIG
        assert caught.value.data["source"] == BadConfigSource.META
        assert caught.value.data["key"] == key

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("schema_version", "nope"),
            ("schema_version", "0"),
            ("id", "not-a-uuid"),
            ("id", str(uuid.uuid1())),
            ("name_breadcrumb", ""),
            ("root_path", ""),
            ("git_mode", "sometimes"),
            ("embed_model", ""),
            ("embed_dim", "0"),
            ("include_globs", "not json"),
            ("include_globs", '{"a": 1}'),
            ("include_globs", "[1, 2]"),
            ("chunk_max_tokens", "1"),
            ("rrf_k", "0"),
            ("fusion_depth", "100000"),
            ("max_file_bytes", "0"),
        ],
    )
    def test_a_value_outside_its_range_is_fatal(self, key: str, value: str) -> None:
        with pytest.raises(ZikaronError) as caught:
            meta.parse_and_validate(_rows(**{key: value}))
        assert caught.value.code is ErrorCode.BAD_CONFIG
        assert caught.value.data["key"] == key

    def test_an_id_that_is_a_uuid_of_the_wrong_version_is_refused(self) -> None:
        """The id names a file, so it is parsed rather than trusted — and a uuid1 encodes a MAC
        address and a timestamp, which is not the unpredictable name this scheme depends on."""
        with pytest.raises(ZikaronError):
            meta.parse_and_validate(_rows(id=str(uuid.uuid1())))

    def test_an_unknown_key_is_tolerated(self) -> None:
        """A newer writer's extra setting must not brick a knowledge base a supported build can
        otherwise read, which is the same forward-compatibility rule the memory store follows."""
        rows = _rows()
        rows["something_a_later_build_added"] = "1"
        assert meta.parse_and_validate(rows).name_breadcrumb == "docs"


class TestRangesComeFromTheConfigurationSchema:
    """The bounds are read from the configuration key each value is seeded from rather than
    restated here, so the two cannot disagree the first time either moves."""

    @pytest.mark.parametrize(("meta_key", "config_key"), sorted(meta.SEEDED_FROM_CONFIG.items()))
    def test_each_seeded_key_names_a_declared_integer_configuration_key(
        self, meta_key: str, config_key: str
    ) -> None:
        assert config_key in CONFIG_KEYS_BY_NAME, meta_key
        assert isinstance(CONFIG_KEYS_BY_NAME[config_key].bounds, IntBounds)

    @pytest.mark.parametrize(("meta_key", "config_key"), sorted(meta.SEEDED_FROM_CONFIG.items()))
    def test_the_bound_enforced_is_the_one_the_configuration_declares(
        self, meta_key: str, config_key: str
    ) -> None:
        bounds = CONFIG_KEYS_BY_NAME[config_key].bounds
        assert isinstance(bounds, IntBounds)

        meta.check_bounded(meta_key, bounds.minimum)
        with pytest.raises(ZikaronError):
            meta.check_bounded(meta_key, bounds.minimum - 1)
        if bounds.maximum is not None:
            meta.check_bounded(meta_key, bounds.maximum)
            with pytest.raises(ZikaronError):
                meta.check_bounded(meta_key, bounds.maximum + 1)

    def test_every_seeded_key_is_a_required_key(self) -> None:
        assert set(meta.SEEDED_FROM_CONFIG) <= set(meta.REQUIRED_KEYS)


class TestGlobsSurviveTheirStorage:
    """Stored as JSON because `meta` values are text and a glob may contain any character a
    separator could be. A corpus silently losing a pattern shows up as missing files rather than
    as an error, which is the failure this encoding removes."""

    @pytest.mark.parametrize(
        "globs",
        [
            (),
            ("*.md",),
            ("*.md", "docs/**/*.txt"),
            ("a,b.md",),
            ('has"quote.md',),
            ("has space.md", "tab\there.md"),
            ("ünïcode/*.md",),
        ],
    )
    def test_any_glob_round_trips(self, globs: tuple[str, ...]) -> None:
        identity = _identity(include_globs=globs, exclude_globs=globs)
        parsed = meta.parse_and_validate(meta.defaults_at_creation(identity))
        assert parsed.include_globs == globs
        assert parsed.exclude_globs == globs

    def test_globs_are_stored_as_a_json_array(self) -> None:
        written: Mapping[str, str] = meta.defaults_at_creation(_identity(include_globs=("*.md",)))
        assert json.loads(written[meta.INCLUDE_GLOBS_KEY]) == ["*.md"]


class TestTheIdParserSpeaksWithOneVoice:
    """All three refusals name the value and say it is not a uuid.

    A caller catching this is being told what was wrong with an identifier, so a message about
    base-16 conversion — which is what `UUID` reports for a right-length non-hex string — would be
    describing the parser's internals instead. The three cases reach three different branches, and
    the branch a test never reaches is the one whose message nobody has read.
    """

    @pytest.mark.parametrize(
        "value",
        [
            pytest.param("../memory", id="too short"),
            pytest.param("zzzzzzzz-zzzz-zzzz-zzzz-zzzzzzzzzzzz", id="right length, not hex"),
            pytest.param(str(uuid.uuid1()), id="a uuid of the wrong version"),
        ],
    )
    def test_every_refusal_names_the_value_and_the_expectation(self, value: str) -> None:
        with pytest.raises(ValueError, match="uuid") as caught:
            meta.parse_id(value)
        assert repr(value) in str(caught.value)

    def test_a_version_4_uuid_round_trips(self) -> None:
        generated = uuid.uuid4()
        assert meta.parse_id(str(generated)) == generated


class TestTwoGuardsThatShouldNeverFire:
    def test_an_id_of_the_right_length_that_is_not_a_uuid_is_refused(self) -> None:
        """The length check runs first, so a *short* non-uuid never reaches the parse. This is the
        other half: 36 characters of nonsense, which only parsing can reject."""
        with pytest.raises(ZikaronError) as caught:
            meta.parse_and_validate(_rows(id="x" * 36))
        assert caught.value.data["key"] == meta.ID_KEY

    def test_a_seeded_key_pointing_at_a_non_integer_setting_is_a_programming_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Raised as `TypeError` rather than as a store error, because it cannot be caused by
        anything in a store: it means this module's own table of where each value is seeded from
        names the wrong configuration key."""
        monkeypatch.setattr(
            meta, "SEEDED_FROM_CONFIG", {**meta.SEEDED_FROM_CONFIG, meta.RRF_K_KEY: "embed_model"}
        )
        with pytest.raises(TypeError, match="not integer-bounded"):
            meta.check_bounded(meta.RRF_K_KEY, 60)
