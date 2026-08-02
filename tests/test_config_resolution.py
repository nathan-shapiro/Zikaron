"""Layered TOML resolution, checked against `architecture.md` §"Configuration".

The fixture matrix `build-plan.md`'s M2 brief requires: missing file, a partial override, an
unknown key, an out-of-range value, and a wrong TOML type, each exercised at both the system-wide
and the project layer.
"""

from pathlib import Path

import pytest

import zikaron.core.config.resolution as resolution_module
from zikaron.core.config.keys import CONFIG_KEYS_BY_NAME
from zikaron.core.config.resolution import (
    EffectiveConfig,
    default_system_config_path,
    key_for_toml_path,
    project_config_path,
    resolve,
)
from zikaron.core.errors import BadConfigSource, ErrorCode, ZikaronError


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Both files missing: every key at its built-in default
# ---------------------------------------------------------------------------


def test_both_files_missing_resolves_to_every_built_in_default(tmp_path: Path) -> None:
    system = tmp_path / "system" / "config.toml"
    project = tmp_path / "project" / "config.toml"
    config = resolve(system, project)
    for key in CONFIG_KEYS_BY_NAME.values():
        assert config.get(key.name) == key.default, key.toml_path
        assert config.source_of(key.name) is None


# ---------------------------------------------------------------------------
# Partial override, both layers: per-key amend at depth 2, unmentioned keys survive
# ---------------------------------------------------------------------------


def test_a_partial_system_layer_amends_only_the_keys_it_states(tmp_path: Path) -> None:
    system = tmp_path / "system" / "config.toml"
    project = tmp_path / "project" / "config.toml"
    _write(system, "[retrieval]\nrrf_k = 30\n")
    config = resolve(system, project)
    assert config.get("rrf_k") == 30
    assert config.source_of("rrf_k") == system
    # A sibling key in the SAME section the file never mentioned stays at its built-in default —
    # this is the "amends, does not replace, the section" rule stated as a fact about resolution.
    assert config.get("fusion_depth") == 50
    assert config.source_of("fusion_depth") is None


def test_a_project_layer_amends_a_system_layer_per_key(tmp_path: Path) -> None:
    system = tmp_path / "system" / "config.toml"
    project = tmp_path / "project" / "config.toml"
    _write(system, "[retrieval]\nfusion_depth = 50\nrrf_k = 60\n")
    _write(project, "[retrieval]\nrrf_k = 30\n")
    config = resolve(system, project)
    assert config.get("rrf_k") == 30
    assert config.source_of("rrf_k") == project
    # fusion_depth is untouched by the project layer, so the system layer's value survives.
    assert config.get("fusion_depth") == 50
    assert config.source_of("fusion_depth") == system


def test_a_project_layer_alone_amends_the_built_in_defaults(tmp_path: Path) -> None:
    system = tmp_path / "system" / "config.toml"
    project = tmp_path / "project" / "config.toml"
    _write(project, "[dedup]\ndedup_max = 5\n")
    config = resolve(system, project)
    assert config.get("dedup_max") == 5
    assert config.source_of("dedup_max") == project
    assert config.get("dedup_threshold") == 0.80
    assert config.source_of("dedup_threshold") is None


# ---------------------------------------------------------------------------
# Unknown key: rejected per file, at parse time — both layers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("which_layer", ["system", "project"])
def test_an_unknown_key_is_rejected_per_file_naming_that_file(
    tmp_path: Path, which_layer: str
) -> None:
    system = tmp_path / "system" / "config.toml"
    project = tmp_path / "project" / "config.toml"
    target = system if which_layer == "system" else project
    _write(target, "[retrieval]\nrrf_dept = 100\n")
    with pytest.raises(ZikaronError) as excinfo:
        resolve(system, project)
    error = excinfo.value
    assert error.code is ErrorCode.BAD_CONFIG
    assert error.data["source"] == BadConfigSource.FILE
    assert error.data["file"] == str(target)
    assert error.data["key"] == "retrieval.rrf_dept"


def test_an_unknown_section_is_rejected(tmp_path: Path) -> None:
    system = tmp_path / "system" / "config.toml"
    project = tmp_path / "project" / "config.toml"
    _write(project, "[nonexistent_section]\nsomething = 1\n")
    with pytest.raises(ZikaronError) as excinfo:
        resolve(system, project)
    assert excinfo.value.data["key"] == "nonexistent_section.something"


def test_a_key_written_under_the_wrong_section_is_unknown_there(tmp_path: Path) -> None:
    """`toml_path` is `section.name`, so a real key in a section it does not belong to is
    indistinguishable from a misspelling — both are keys this schema does not declare there."""
    system = tmp_path / "system" / "config.toml"
    project = tmp_path / "project" / "config.toml"
    _write(project, "[dedup]\nrrf_k = 60\n")
    with pytest.raises(ZikaronError) as excinfo:
        resolve(system, project)
    assert excinfo.value.data["key"] == "dedup.rrf_k"


# ---------------------------------------------------------------------------
# Wrong TOML type: rejected per file, at parse time — both layers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("which_layer", ["system", "project"])
def test_a_wrong_toml_type_is_rejected_per_file(tmp_path: Path, which_layer: str) -> None:
    system = tmp_path / "system" / "config.toml"
    project = tmp_path / "project" / "config.toml"
    target = system if which_layer == "system" else project
    _write(target, "[retrieval]\nfusion_depth = 50.0\n")
    with pytest.raises(ZikaronError) as excinfo:
        resolve(system, project)
    error = excinfo.value
    assert error.code is ErrorCode.BAD_CONFIG
    assert error.data["file"] == str(target)
    assert error.data["key"] == "retrieval.fusion_depth"
    assert error.data["expected"] == "int"


def test_a_toml_boolean_for_an_int_key_is_rejected(tmp_path: Path) -> None:
    """TOML `true`/`false` and an integer are different types; `bool` subclassing `int` in
    Python must not let a boolean pass as 1 or 0."""
    system = tmp_path / "system" / "config.toml"
    project = tmp_path / "project" / "config.toml"
    _write(project, "[retrieval]\nfusion_depth = true\n")
    with pytest.raises(ZikaronError) as excinfo:
        resolve(system, project)
    assert excinfo.value.data["key"] == "retrieval.fusion_depth"


def test_a_string_where_a_float_is_declared_is_rejected(tmp_path: Path) -> None:
    system = tmp_path / "system" / "config.toml"
    project = tmp_path / "project" / "config.toml"
    _write(project, '[dedup]\ndedup_threshold = "0.8"\n')
    with pytest.raises(ZikaronError) as excinfo:
        resolve(system, project)
    assert excinfo.value.data["key"] == "dedup.dedup_threshold"
    assert excinfo.value.data["expected"] == "float"


# ---------------------------------------------------------------------------
# Out-of-range: validated on the MERGED result, naming the file the winning value came from
# ---------------------------------------------------------------------------


def test_an_out_of_range_system_value_the_project_corrects_is_fine(tmp_path: Path) -> None:
    """Range validation runs once, on the merged result — what matters is what the service will
    actually use, per `architecture.md`: an illegal system-wide value a project override
    replaces with a legal one must not fail resolution."""
    system = tmp_path / "system" / "config.toml"
    project = tmp_path / "project" / "config.toml"
    _write(system, "[retrieval]\nrrf_k = -5\n")
    _write(project, "[retrieval]\nrrf_k = 30\n")
    config = resolve(system, project)
    assert config.get("rrf_k") == 30


@pytest.mark.parametrize("which_layer", ["system", "project"])
def test_an_out_of_range_merged_value_is_rejected_naming_its_winning_file(
    tmp_path: Path, which_layer: str
) -> None:
    system = tmp_path / "system" / "config.toml"
    project = tmp_path / "project" / "config.toml"
    target = system if which_layer == "system" else project
    _write(target, "[retrieval]\nrrf_k = -5\n")
    with pytest.raises(ZikaronError) as excinfo:
        resolve(system, project)
    error = excinfo.value
    assert error.code is ErrorCode.BAD_CONFIG
    assert error.data["source"] == BadConfigSource.FILE
    assert error.data["file"] == str(target)
    assert error.data["key"] == "retrieval.rrf_k"


def test_a_legal_system_value_the_project_overrides_out_of_range_names_the_project_file(
    tmp_path: Path,
) -> None:
    """A value that was fine before the project override touched it must not have the system
    file blamed for what the project file actually broke."""
    system = tmp_path / "system" / "config.toml"
    project = tmp_path / "project" / "config.toml"
    _write(system, "[dedup]\ndedup_threshold = 0.5\n")
    _write(project, "[dedup]\ndedup_threshold = 1.5\n")
    with pytest.raises(ZikaronError) as excinfo:
        resolve(system, project)
    assert excinfo.value.data["file"] == str(project)


# ---------------------------------------------------------------------------
# Unparseable TOML
# ---------------------------------------------------------------------------


def test_unparseable_toml_is_bad_config_naming_the_file(tmp_path: Path) -> None:
    system = tmp_path / "system" / "config.toml"
    project = tmp_path / "project" / "config.toml"
    _write(project, "[retrieval\nrrf_k = 30\n")  # missing closing bracket
    with pytest.raises(ZikaronError) as excinfo:
        resolve(system, project)
    error = excinfo.value
    assert error.code is ErrorCode.BAD_CONFIG
    assert error.data["file"] == str(project)


def test_a_key_nested_deeper_than_one_section_is_rejected(tmp_path: Path) -> None:
    """Nothing in the schema nests deeper than `section.name`, so a value one level too deep is
    not a declared key at any depth this schema understands."""
    system = tmp_path / "system" / "config.toml"
    project = tmp_path / "project" / "config.toml"
    _write(project, "[retrieval]\n[retrieval.nested]\nrrf_k = 30\n")
    with pytest.raises(ZikaronError):
        resolve(system, project)


def test_a_top_level_scalar_with_no_section_header_is_rejected(tmp_path: Path) -> None:
    """A key written with no `[section]` above it at all — every declared key lives inside
    exactly one section, so a bare top-level value is not a table this schema can read at all."""
    system = tmp_path / "system" / "config.toml"
    project = tmp_path / "project" / "config.toml"
    _write(project, "rrf_k = 30\n")
    with pytest.raises(ZikaronError) as excinfo:
        resolve(system, project)
    assert excinfo.value.data["key"] == "rrf_k"
    assert excinfo.value.data["expected"] == "a table (TOML section)"


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def test_default_system_config_path_respects_xdg_config_home() -> None:
    home = Path("/home/example")
    assert default_system_config_path("/xdg/config", home) == Path(
        "/xdg/config/zikaron/config.toml"
    )


def test_default_system_config_path_falls_back_to_dot_config(tmp_path: Path) -> None:
    home = tmp_path
    assert default_system_config_path(None, home) == home / ".config" / "zikaron" / "config.toml"
    assert default_system_config_path("", home) == home / ".config" / "zikaron" / "config.toml"


def test_project_config_path_sits_beside_the_store(tmp_path: Path) -> None:
    store_dir = tmp_path / ".zikaron"
    assert project_config_path(store_dir) == store_dir / "config.toml"


def test_key_for_toml_path_finds_the_declared_key() -> None:
    key = key_for_toml_path("retrieval.rrf_k")
    assert key is not None
    assert key.name == "rrf_k"


def test_key_for_toml_path_returns_none_for_an_undeclared_key() -> None:
    assert key_for_toml_path("retrieval.nonexistent") is None


def test_key_for_toml_path_returns_none_for_a_real_key_under_the_wrong_section() -> None:
    """`rrf_k` is declared under `retrieval`, not `dedup` — the path must validate the whole
    dotted name, not merely find some key with that bare name under any section at all."""
    assert key_for_toml_path("dedup.rrf_k") is None


def test_key_for_toml_path_returns_none_for_a_bare_name_with_no_section() -> None:
    assert key_for_toml_path("rrf_k") is None


# ---------------------------------------------------------------------------
# EffectiveConfig's typed accessors
# ---------------------------------------------------------------------------


def test_get_int_and_get_str_return_the_typed_value(tmp_path: Path) -> None:
    config = resolve(tmp_path / "system.toml", tmp_path / "project.toml")
    assert config.get_int("rrf_k") == 60
    assert config.get_str("embed_model") == "BAAI/bge-small-en-v1.5"


def test_get_float_returns_the_typed_value(tmp_path: Path) -> None:
    config = resolve(tmp_path / "system.toml", tmp_path / "project.toml")
    assert config.get_float("supersession_penalty") == 0.5


def test_get_float_on_an_int_key_raises_type_error(tmp_path: Path) -> None:
    """An `int` is not silently widened to a `float`: a key whose declared type has changed is a
    schema edit worth a loud failure, and the two demotion penalties are the keys that would
    otherwise start ranking against an integer nobody declared."""
    config = resolve(tmp_path / "system.toml", tmp_path / "project.toml")
    with pytest.raises(TypeError, match="not float"):
        config.get_float("rrf_k")


def test_get_int_on_a_float_key_raises_type_error(tmp_path: Path) -> None:
    config = resolve(tmp_path / "system.toml", tmp_path / "project.toml")
    with pytest.raises(TypeError, match="not int"):
        config.get_int("dedup_threshold")


def test_get_str_on_an_int_key_raises_type_error(tmp_path: Path) -> None:
    config = resolve(tmp_path / "system.toml", tmp_path / "project.toml")
    with pytest.raises(TypeError, match="not str"):
        config.get_str("rrf_k")


def test_provenance_reports_every_key(tmp_path: Path) -> None:
    system = tmp_path / "system.toml"
    project = tmp_path / "project.toml"
    _write(project, "[retrieval]\nrrf_k = 30\n")
    config = resolve(system, project)
    assert config.provenance["rrf_k"] == project
    assert config.provenance["fusion_depth"] is None
    assert set(config.provenance) == set(CONFIG_KEYS_BY_NAME)


# ---------------------------------------------------------------------------
# EffectiveConfig's own self-validation — defense in depth against a caller that
# constructs one directly rather than through resolve()
# ---------------------------------------------------------------------------


def _all_defaults() -> dict[str, int | float | str]:
    return {key.name: key.default for key in CONFIG_KEYS_BY_NAME.values()}


def _all_none_provenance() -> dict[str, Path | None]:
    return dict.fromkeys(CONFIG_KEYS_BY_NAME)


def test_effective_config_accepts_a_complete_valid_construction() -> None:
    config = EffectiveConfig(_all_defaults(), _all_none_provenance())
    assert config.get("rrf_k") == 60


def test_effective_config_refuses_a_missing_key_in_values() -> None:
    values = _all_defaults()
    del values["rrf_k"]
    with pytest.raises(ValueError, match="requires exactly the keys"):
        EffectiveConfig(values, _all_none_provenance())


def test_effective_config_refuses_an_extra_key_in_values() -> None:
    values = {**_all_defaults(), "not_a_real_key": 1}
    with pytest.raises(ValueError, match="requires exactly the keys"):
        EffectiveConfig(values, {**_all_none_provenance(), "not_a_real_key": None})


def test_effective_config_refuses_a_provenance_missing_a_key() -> None:
    provenance = _all_none_provenance()
    del provenance["rrf_k"]
    with pytest.raises(ValueError, match="requires exactly the keys"):
        EffectiveConfig(_all_defaults(), provenance)


def test_effective_config_refuses_an_out_of_range_value_even_with_complete_keys() -> None:
    """The defense-in-depth case: every key is present, but one value violates its own range —
    exactly what a caller bypassing `resolve()`'s own `_validate_ranges` could construct."""
    values = {**_all_defaults(), "rrf_k": -5}
    with pytest.raises(ValueError, match="out of range"):
        EffectiveConfig(values, _all_none_provenance())


def test_effective_config_refuses_a_wrong_type_value_even_with_complete_keys() -> None:
    values = {**_all_defaults(), "embed_model": 123}
    with pytest.raises(ValueError, match="out of range"):
        EffectiveConfig(values, _all_none_provenance())


# ---------------------------------------------------------------------------
# _merge_layer's defensive type check
# ---------------------------------------------------------------------------


def test_merge_layer_refuses_a_value_of_a_type_its_own_upstream_guarantee_ruled_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_flatten_and_validate_shape` guarantees every value it returns is `int`, `float` or
    `str` — a fact `_merge_layer` re-checks because that guarantee crosses a function boundary
    the type checker cannot see through. Exercised by monkeypatching the guarantee itself, since
    nothing reachable through the public `resolve()` path can violate it."""

    def _lying_flatten(_path: object, _sections: object) -> dict[str, object]:
        return {"rrf_k": None}

    monkeypatch.setattr(resolution_module, "_flatten_and_validate_shape", _lying_flatten)
    project = tmp_path / "project.toml"
    _write(project, "[retrieval]\nrrf_k = 30\n")

    with pytest.raises(TypeError, match="not int/float/str"):
        resolve(tmp_path / "system.toml", project)
