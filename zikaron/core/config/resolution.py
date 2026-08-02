"""Layered TOML resolution over the schema `keys.py` declares.

Three layers, later wins per key: the built-in defaults, a system-wide file, and a per-store
override. `architecture.md` §"Configuration" is the normative source for what follows; this
module is the mechanism, not a second statement of the rule.

Two checks happen at different points, deliberately. An unknown key or a value of the wrong
TOML type is rejected **per file, at parse time** — a file was typed by a person, so silently
ignoring a misspelling is how a setting goes unnoticed. Range validation runs once, on the
**merged** result, because what matters is the value the store will actually use, not whether
every layer that touched a key was independently in range.
"""

import tomllib
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Final

from zikaron.core.config.keys import CONFIG_KEYS, CONFIG_KEYS_BY_NAME, ConfigKey
from zikaron.core.errors import BadConfigSource, ErrorCode, ZikaronError

#: A key's resolved value, and where it came from — a layer path, or `None` for the built-in
#: default. `architecture.md` requires the resolved config to be logged with a layer per value;
#: this is the mapping that statement is computed from.
type Provenance = Mapping[str, Path | None]


class EffectiveConfig:
    """Every configuration key, resolved to one typed value.

    Immutable, and self-validating on construction: `__init__` checks every value against
    `CONFIG_KEYS` itself rather than trusting that whoever called it already ran
    `_validate_ranges`. `resolve()` is the only path that constructs one through ordinary use,
    but "the only real caller validates first" is a fact about today's call sites, not an
    enforced property of this type — and a value that could later change, or a value this
    constructor let through unchecked, would let two `event` rows written in one run disagree
    about the parameters that produced them, which is exactly what `architecture.md` reads the
    files once at startup to prevent.

    Access a key by its bare name — `effective.get("rrf_k")` — rather than by an attribute, since
    the schema is a runtime table (`CONFIG_KEYS`) and a fixed set of attributes would need to be
    kept in step with it by hand.

    Raises:
        ValueError: `values` or `provenance` does not carry exactly the keys `CONFIG_KEYS`
            declares, or a value fails its own key's type/range check.
    """

    __slots__ = ("_provenance", "_values")

    def __init__(self, values: Mapping[str, int | float | str], provenance: Provenance) -> None:
        declared = set(CONFIG_KEYS_BY_NAME)
        if set(values) != declared or set(provenance) != declared:
            raise ValueError("EffectiveConfig requires exactly the keys CONFIG_KEYS declares")
        for key in CONFIG_KEYS:
            if not key.accepts(values[key.name]):
                raise ValueError(f"{key.toml_path}: {values[key.name]!r} is out of range")
        self._values: Final = MappingProxyType(dict(values))
        self._provenance: Final = MappingProxyType(dict(provenance))

    def get(self, name: str) -> int | float | str:
        """This key's resolved value, typed exactly as `CONFIG_KEYS_BY_NAME[name]` declares.

        Prefer `get_int`/`get_float`/`get_str` at a call site that needs one specific type: this
        method's union return type forces a narrowing check on every access, which is exactly
        what the typed accessors below exist to avoid.
        """
        return self._values[name]

    def get_int(self, name: str) -> int:
        """This key's resolved value, which must be declared as an `int` in `CONFIG_KEYS`."""
        value = self._values[name]
        if type(value) is not int:
            raise TypeError(f"{name} is declared {type(value).__name__}, not int")
        return value

    def get_float(self, name: str) -> float:
        """This key's resolved value, which must be declared as a `float` in `CONFIG_KEYS`.

        A `float`-declared key only: an `int` is not silently widened, because a key whose declared
        type has changed is a schema edit worth a loud failure rather than a quiet coercion.
        """
        value = self._values[name]
        if type(value) is not float:
            raise TypeError(f"{name} is declared {type(value).__name__}, not float")
        return value

    def get_str(self, name: str) -> str:
        """This key's resolved value, which must be declared as a `str` in `CONFIG_KEYS`."""
        value = self._values[name]
        if type(value) is not str:
            raise TypeError(f"{name} is declared {type(value).__name__}, not str")
        return value

    def source_of(self, name: str) -> Path | None:
        """Which layer this key's winning value came from, or `None` for the built-in default."""
        return self._provenance[name]

    @property
    def provenance(self) -> Provenance:
        """Every key's source, for a startup log line naming the layer behind each value."""
        return self._provenance


def _read_layer(path: Path) -> Mapping[str, object]:
    """Parse one TOML file, or treat its absence as an empty, contributing-nothing layer.

    A parse failure is `bad_config` naming the file rather than a bare `tomllib` traceback,
    since an operator's typo should read as a Zikaron error and not as a library exception with
    no key or file attached.
    """
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return {}
    try:
        return tomllib.loads(raw.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as error:
        raise ZikaronError(
            ErrorCode.BAD_CONFIG,
            source=BadConfigSource.FILE,
            file=str(path),
            key="<file>",
            value=str(error),
            expected="valid TOML",
        ) from error


def _flatten_and_validate_shape(path: Path, sections: Mapping[str, object]) -> Mapping[str, object]:
    """Every scalar in a parsed file, keyed by bare name, after checking it against the schema.

    Two things are rejected here, per file, before any merge happens: a key this schema does not
    declare, and a value whose TOML type does not match what the schema declares for it. Nothing
    that nests deeper than one section reaches here, because a key two levels below a section
    could not be one of `CONFIG_KEYS_BY_NAME`'s bare names in the first place — it fails the
    unknown-key check on its own terms rather than needing a separate depth check.
    """
    flat: dict[str, object] = {}
    for section_name, section_value in sections.items():
        if not isinstance(section_value, dict):
            raise ZikaronError(
                ErrorCode.BAD_CONFIG,
                source=BadConfigSource.FILE,
                file=str(path),
                key=section_name,
                value=repr(section_value),
                expected="a table (TOML section)",
            )
        for key_name, value in section_value.items():
            declared = CONFIG_KEYS_BY_NAME.get(key_name)
            if declared is None or declared.section.value != section_name:
                raise ZikaronError(
                    ErrorCode.BAD_CONFIG,
                    source=BadConfigSource.FILE,
                    file=str(path),
                    key=f"{section_name}.{key_name}",
                    value=repr(value),
                    expected="a declared configuration key",
                )
            if type(value) is not declared.value_type:
                raise ZikaronError(
                    ErrorCode.BAD_CONFIG,
                    source=BadConfigSource.FILE,
                    file=str(path),
                    key=declared.toml_path,
                    value=repr(value),
                    expected=declared.value_type.__name__,
                )
            flat[key_name] = value
    return flat


def _merge_layer(
    path: Path,
    values: dict[str, int | float | str],
    provenance: dict[str, Path | None],
) -> None:
    """Apply one file's keys onto the running merge, in place — later layers overwrite earlier."""
    parsed = _read_layer(path)
    if not parsed:
        return
    for key_name, value in _flatten_and_validate_shape(path, parsed).items():
        # `_flatten_and_validate_shape` has already checked `value`'s type against the
        # declared key's `value_type`, which is always one of these three — but that fact is
        # not visible to the type checker across the function boundary, so it is checked again
        # here rather than asserted past.
        if not isinstance(value, int | float | str):
            raise TypeError(f"{key_name}: resolved to {type(value).__name__}, not int/float/str")
        values[key_name] = value
        provenance[key_name] = path


def _validate_ranges(values: Mapping[str, int | float | str], provenance: Provenance) -> None:
    """Range- and type-check every key's winning value, naming the file it came from.

    Runs once, after every layer has been merged, because a value the system-wide layer got
    wrong and the project override corrected is fine — what the service will use is what is
    checked. An out-of-range built-in default cannot occur: `ConfigKey.__post_init__` already
    refuses that at import time.
    """
    for key in CONFIG_KEYS:
        value = values[key.name]
        if key.accepts(value):
            continue
        source = provenance[key.name]
        raise ZikaronError(
            ErrorCode.BAD_CONFIG,
            source=BadConfigSource.FILE,
            file=str(source) if source is not None else "<default>",
            key=key.toml_path,
            value=repr(value),
            expected=f"{key.value_type.__name__} in {key.bounds}",
        )


def resolve(system_path: Path, project_path: Path) -> EffectiveConfig:
    """Resolve the effective config from the built-in defaults plus the two file layers.

    Neither file has to exist, and neither has to be complete: an absent file contributes
    nothing, and a present one states only what it changes. `system_path` is read first, so
    `project_path` amends it per key — exactly `architecture.md`'s "later layer wins, per key."

    Raises:
        ZikaronError: `BAD_CONFIG`, for an unparseable file, an unknown key, a key of the wrong
            TOML type, or an effective value out of range — always naming the offending file
            and key.
    """
    values: dict[str, int | float | str] = {key.name: key.default for key in CONFIG_KEYS}
    provenance: dict[str, Path | None] = {key.name: None for key in CONFIG_KEYS}
    _merge_layer(system_path, values, provenance)
    _merge_layer(project_path, values, provenance)
    _validate_ranges(values, provenance)
    return EffectiveConfig(values, provenance)


def default_system_config_path(xdg_config_home: str | None, home: Path) -> Path:
    """Where the system-wide layer lives, per `architecture.md`'s `${XDG_CONFIG_HOME:-~/.config}`.

    A pure function of its inputs rather than one that reads `os.environ`/`Path.home()` itself,
    so a test can state the environment it is checking instead of having to mutate the process's.
    """
    base = Path(xdg_config_home) if xdg_config_home else home / ".config"
    return base / "zikaron" / "config.toml"


def project_config_path(store_dir: Path) -> Path:
    """Where the per-store override lives: `config.toml` beside `memory.db`, inside `.zikaron/`."""
    return store_dir / "config.toml"


def key_for_toml_path(toml_path: str) -> ConfigKey | None:
    """The declared key for a dotted `section.name` path, or `None` if no such key exists there.

    Validates the **whole** path, not merely the bare name after the last dot: a key that
    exists under a different section, or a bare name with no section at all, is not "the key
    for" the path given — `toml_path` names both halves, and a lookup that discarded the
    section would accept `"dedup.rrf_k"` as if it named `retrieval.rrf_k`, which is a
    misspelled, not a matching, path.
    """
    section, separator, bare_name = toml_path.rpartition(".")
    if separator == "":
        return None
    key = CONFIG_KEYS_BY_NAME.get(bare_name)
    if key is None or key.section.value != section:
        return None
    return key
