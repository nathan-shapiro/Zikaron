"""The configuration key schema: every key, its type, its permitted range, and its default.

One table, because a key's default living in the code that reads it and its range living in a
validator elsewhere is how the two come to disagree. Everything a layer can be resolved from —
the built-in default, the accepted type, the accepted range, the TOML location, and whether the
store itself has a say — is declared here and nowhere else.

Resolution over the layered files is a separate concern and reads this table; this module holds
no file, no path, and no merge.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final


class ConfigSection(StrEnum):
    """The TOML sections. They group keys for a reader's benefit and nothing nests deeper."""

    EMBEDDING = "embedding"
    INDEXING = "indexing"
    RETRIEVAL = "retrieval"
    DEDUP = "dedup"
    CONSOLIDATION = "consolidation"
    SERVICE = "service"
    SIGNALS = "signals"


class StoreCoupling(StrEnum):
    """How far a key may move without contradicting what `memory.db` already contains.

    Scoped to the memory store specifically, because it is not the only database Zikaron owns: a
    knowledge base seeds several of these keys into its own `meta` at creation and then ignores
    later changes to them, which is a different policy under a different document. A key that
    couples only to a knowledge base is `NONE` here, and says so in its own notes.

    A configuration file states intent; a store records what was actually done. For most keys
    those cannot conflict, but three describe how existing rows were produced:

    - `NONE`: the file is the only home. A new value simply takes effect.
    - `SOFT`: the store also records what was done. A disagreement leaves the store
      heterogeneous — old rows stay valid — so it is worth reporting and not worth refusing.
    - `HARD`: the store's record wins. A disagreement is a *request* for a rebuild, because
      every existing row was produced by the recorded value and reinterpreting them under a new
      one would be silently wrong rather than visibly stale.
    """

    NONE = "none"
    SOFT = "soft"
    HARD = "hard"


class ConfigUnit(StrEnum):
    """The unit a key's number is in, for the keys whose name does not already say."""

    NONE = "none"
    SECONDS = "seconds"
    DAYS = "days"
    BYTES = "bytes"


@dataclass(frozen=True, slots=True)
class IntBounds:
    """An inclusive integer interval. `maximum is None` means unbounded above."""

    minimum: int
    maximum: int | None = None

    @property
    def value_type(self) -> type[int]:
        """The one Python type this bound accepts."""
        return int

    def permits(self, value: int) -> bool:
        """Whether `value` lies inside the interval."""
        if value < self.minimum:
            return False
        return self.maximum is None or value <= self.maximum


@dataclass(frozen=True, slots=True)
class FloatBounds:
    """A real interval whose two ends are independently open or closed."""

    minimum: float
    maximum: float
    minimum_inclusive: bool
    maximum_inclusive: bool

    @property
    def value_type(self) -> type[float]:
        """The one Python type this bound accepts."""
        return float

    def permits(self, value: float) -> bool:
        """Whether `value` lies inside the interval, respecting each end's openness."""
        above = value >= self.minimum if self.minimum_inclusive else value > self.minimum
        below = value <= self.maximum if self.maximum_inclusive else value < self.maximum
        return above and below


@dataclass(frozen=True, slots=True)
class StringBounds:
    """A string constraint. Emptiness is the only thing any key has to say about its strings."""

    non_empty: bool

    @property
    def value_type(self) -> type[str]:
        """The one Python type this bound accepts."""
        return str

    def permits(self, value: str) -> bool:
        """Whether `value` satisfies the constraint."""
        return not self.non_empty or value != ""


type ConfigBounds = IntBounds | FloatBounds | StringBounds


@dataclass(frozen=True, slots=True)
class ConfigKey:
    """One configuration key: where it lives, what it accepts, and its value with no file.

    `bounds` carries the accepted type and the accepted range as one thing, so there is no
    declared type sitting somewhere a range can contradict.

    A key is checked against itself at construction, which makes an edit to this table that
    puts a default outside its own range fail on import rather than on the first store that
    happens to run without a configuration file.

    Raises:
        TypeError: the default is not of the type the bounds accept.
        ValueError: the default is of the right type but outside the bounds.
    """

    section: ConfigSection
    name: str
    bounds: ConfigBounds
    default: int | float | str
    store_coupling: StoreCoupling = StoreCoupling.NONE
    unit: ConfigUnit = ConfigUnit.NONE

    def __post_init__(self) -> None:
        if type(self.default) is not self.bounds.value_type:
            raise TypeError(
                f"{self.toml_path}: default {self.default!r} is not "
                f"{self.bounds.value_type.__name__}"
            )
        if not self.accepts(self.default):
            raise ValueError(f"{self.toml_path}: default {self.default!r} is out of range")

    @property
    def toml_path(self) -> str:
        """Where this key is written in a configuration file, as `section.name`."""
        return f"{self.section.value}.{self.name}"

    @property
    def value_type(self) -> type[int] | type[float] | type[str]:
        """The one Python type an effective value for this key may have."""
        return self.bounds.value_type

    def accepts(self, value: object) -> bool:
        """Whether `value` is exactly this key's type and inside its range.

        The type test is exact rather than nominal: a subclass of `int` is not an `int` for this
        purpose. `bool` is the case that matters in practice — a TOML `true` would otherwise be
        read as 1 — but an enum member or any other `int` subclass is just as wrong, and a
        configuration value that reaches here already carrying meaning has been parsed by
        something other than the parser this schema is for.

        Widening is a separate question: an integer written where a float is declared may or may
        not be worth accepting, and deciding that belongs to whoever parses the file rather than
        to the schema that says what the key is.
        """
        bounds = self.bounds
        if isinstance(bounds, IntBounds):
            return type(value) is int and bounds.permits(value)
        if isinstance(bounds, FloatBounds):
            return type(value) is float and bounds.permits(value)
        return type(value) is str and bounds.permits(value)


CONFIG_KEYS: Final[tuple[ConfigKey, ...]] = (
    ConfigKey(
        ConfigSection.EMBEDDING,
        "embed_model",
        StringBounds(non_empty=True),
        "BAAI/bge-small-en-v1.5",
        store_coupling=StoreCoupling.HARD,
    ),
    ConfigKey(
        ConfigSection.EMBEDDING,
        "embed_dim",
        IntBounds(1),
        384,
        store_coupling=StoreCoupling.HARD,
    ),
    ConfigKey(
        ConfigSection.EMBEDDING,
        "embed_prefix_query",
        StringBounds(non_empty=False),
        # The trailing space is part of the prefix the model expects, and every retrieval
        # figure was measured with this exact string. A paraphrase is a different pipeline,
        # so the literal is quoted rather than described. Empty disables prefixing.
        "Represent this sentence for searching relevant passages: ",
    ),
    ConfigKey(
        ConfigSection.INDEXING,
        "chunk_max_tokens",
        IntBounds(64, 8192),
        450,
        store_coupling=StoreCoupling.SOFT,
    ),
    ConfigKey(
        ConfigSection.INDEXING,
        "gist_max_tokens",
        IntBounds(8, 256),
        64,
    ),
    ConfigKey(
        ConfigSection.INDEXING,
        "knowledge_max_file_bytes",
        # The maximum is protective rather than arbitrary: text detection decodes a candidate
        # whole, so this cap is what bounds the memory one file can cost. 64 MiB is far above
        # any plausible text file and far below a figure that would matter.
        IntBounds(1, 67_108_864),
        1_048_576,
        unit=ConfigUnit.BYTES,
    ),
    ConfigKey(
        ConfigSection.INDEXING,
        "knowledge_embed_batch",
        # 1 disables batching outright; the maximum is where one forward pass's memory stops being
        # bounded by anything this project controls. Unlike its neighbour above it is not seeded
        # into a knowledge base, because it describes how much work goes into one pass rather than
        # anything about the index that results — a correct implementation's vectors do not depend
        # on it at all.
        IntBounds(1, 256),
        32,
    ),
    ConfigKey(
        ConfigSection.RETRIEVAL,
        "chunk_overfetch",
        IntBounds(1, 64),
        8,
    ),
    ConfigKey(
        ConfigSection.RETRIEVAL,
        "fusion_depth",
        IntBounds(1, 500),
        50,
    ),
    ConfigKey(
        ConfigSection.RETRIEVAL,
        "rrf_k",
        IntBounds(1),
        60,
    ),
    ConfigKey(
        ConfigSection.RETRIEVAL,
        "supersession_penalty",
        FloatBounds(0.0, 1.0, minimum_inclusive=False, maximum_inclusive=True),
        0.5,
    ),
    ConfigKey(
        ConfigSection.RETRIEVAL,
        "retired_penalty",
        FloatBounds(0.0, 1.0, minimum_inclusive=False, maximum_inclusive=True),
        0.5,
    ),
    ConfigKey(
        ConfigSection.RETRIEVAL,
        "supersession_max_depth",
        IntBounds(1, 1024),
        32,
    ),
    ConfigKey(
        ConfigSection.RETRIEVAL,
        "fts_query_max_terms",
        IntBounds(1, 512),
        64,
    ),
    ConfigKey(
        ConfigSection.RETRIEVAL,
        "knowledge_max_chunks_per_file",
        # The maximum is mechanical rather than a taste: a knowledge search returns at most 20
        # results per corpus, so a per-file allowance above 20 could never bind on any call, and a
        # range that admits values which cannot take effect is a range that misleads.
        IntBounds(1, 20),
        2,
    ),
    ConfigKey(
        ConfigSection.RETRIEVAL,
        "knowledge_snippet_max_chars",
        # Counted in Unicode code points, which is also why the ceiling is a sanity bound rather
        # than a derivation: the response cap is in *bytes*, and 24,000 code points can be four
        # times that many bytes, so this number is the response cap's own borrowed as an
        # order-of-magnitude limit. Anywhere near it a single snippet is undeliverable whatever the
        # encoding, which is all the ceiling has to establish. The floor still shows a line or two
        # of context.
        IntBounds(80, 24_000),
        1_200,
    ),
    ConfigKey(
        ConfigSection.DEDUP,
        "dedup_threshold",
        FloatBounds(0.0, 1.0, minimum_inclusive=True, maximum_inclusive=True),
        0.80,
    ),
    ConfigKey(
        ConfigSection.DEDUP,
        "dedup_max",
        IntBounds(0, 20),
        3,
    ),
    ConfigKey(
        ConfigSection.CONSOLIDATION,
        "mutual_k",
        IntBounds(2, 50),
        5,
    ),
    ConfigKey(
        ConfigSection.CONSOLIDATION,
        "orphan_edge_cutoff",
        FloatBounds(0.0, 1.0, minimum_inclusive=True, maximum_inclusive=True),
        0.65,
    ),
    ConfigKey(
        ConfigSection.CONSOLIDATION,
        "anchor_cutoff",
        FloatBounds(0.0, 1.0, minimum_inclusive=True, maximum_inclusive=True),
        0.65,
    ),
    ConfigKey(
        ConfigSection.CONSOLIDATION,
        "group_max",
        IntBounds(2, 64),
        12,
    ),
    ConfigKey(
        ConfigSection.CONSOLIDATION,
        "max_group_serves",
        IntBounds(1, 16),
        3,
    ),
    ConfigKey(
        ConfigSection.CONSOLIDATION,
        "run_lease",
        IntBounds(60, 86400),
        1800,
        unit=ConfigUnit.SECONDS,
    ),
    ConfigKey(
        ConfigSection.CONSOLIDATION,
        "spill_threshold",
        IntBounds(4096, 1_048_576),
        27000,
        unit=ConfigUnit.BYTES,
    ),
    ConfigKey(
        ConfigSection.SERVICE,
        "idle_timeout",
        IntBounds(60, 86400),
        1800,
        unit=ConfigUnit.SECONDS,
    ),
    ConfigKey(
        ConfigSection.SIGNALS,
        "signal_horizon_days",
        IntBounds(1, 3650),
        30,
        unit=ConfigUnit.DAYS,
    ),
)


def _index_by_name(keys: tuple[ConfigKey, ...]) -> Mapping[str, ConfigKey]:
    """Index the schema by bare key name, rejecting a name that appears in two sections.

    Names are unique across the whole schema, not merely within a section, because the
    store-coupled keys are also recorded in a flat single-namespace table — a name that needed
    its section to disambiguate it could not be written there at all.
    """
    index: dict[str, ConfigKey] = {}
    for key in keys:
        if key.name in index:
            raise ValueError(f"configuration key name used twice: {key.name}")
        index[key.name] = key
    return MappingProxyType(index)


CONFIG_KEYS_BY_NAME: Final[Mapping[str, ConfigKey]] = _index_by_name(CONFIG_KEYS)
