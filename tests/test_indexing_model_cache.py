"""Where the embedding model's 64 MB lands, and that nothing of ours puts it in a tempdir.

**The mutation these are written against is the resolver returning `define_cache_dir(None)`** —
fastembed's own answer, which is `$FASTEMBED_CACHE_PATH` or `tempfile.gettempdir()/fastembed_cache`.
Stating it matters because the obvious phrasing, "this must fail against today's code", is false:
before this module existed such a test failed by `ImportError` and proved nothing.
"""

import tempfile
from pathlib import Path
from typing import Final

import pytest

from zikaron.core.indexing.model_cache import (
    FASTEMBED_CACHE_VARIABLE,
    model_cache_dir,
    resolved_model_cache_dir,
    snapshot_dir,
)

_HOME: Final = Path("/home/someone")


def test_linux_falls_back_to_the_xdg_default() -> None:
    resolved = model_cache_dir(environ={}, platform="linux", home=_HOME)
    assert resolved == _HOME / ".cache" / "zikaron" / "models"


def test_macos_falls_back_to_its_own_cache_convention() -> None:
    resolved = model_cache_dir(environ={}, platform="darwin", home=_HOME)
    assert resolved == _HOME / "Library" / "Caches" / "zikaron" / "models"


def test_xdg_cache_home_is_honoured_on_macos_too() -> None:
    """A user who set the variable has said where caches go; `~/Library/Caches` is the answer for
    having not said."""
    environ = {"XDG_CACHE_HOME": "/elsewhere/cache"}
    for platform in ("linux", "darwin"):
        resolved = model_cache_dir(environ=environ, platform=platform, home=_HOME)
        assert resolved == Path("/elsewhere/cache") / "zikaron" / "models"


def test_the_fastembed_variable_is_honoured_verbatim() -> None:
    """Verbatim, because its value is what the `models--<org>--<name>/` trees sit directly under —
    the layout CI's cache already holds, which is what makes that cache survive this change.
    """
    resolved = model_cache_dir(
        environ={FASTEMBED_CACHE_VARIABLE: "/runner/temp/fastembed_cache"},
        platform="linux",
        home=_HOME,
    )
    assert resolved == Path("/runner/temp/fastembed_cache")


def test_the_fastembed_variable_outranks_xdg() -> None:
    resolved = model_cache_dir(
        environ={FASTEMBED_CACHE_VARIABLE: "/explicit", "XDG_CACHE_HOME": "/elsewhere"},
        platform="linux",
        home=_HOME,
    )
    assert resolved == Path("/explicit")


@pytest.mark.parametrize("variable", [FASTEMBED_CACHE_VARIABLE, "XDG_CACHE_HOME"])
@pytest.mark.parametrize("value", ["", "   ", "relative/cache", "./cache"])
def test_an_empty_or_relative_override_is_ignored(variable: str, value: str) -> None:
    """A relative path resolves against the working directory, which for the service is whichever
    project spawned it — a per-store cache arrived at silently, which is what this module exists to
    prevent. An unset variable and an empty one mean the same thing to a shell.
    """
    resolved = model_cache_dir(environ={variable: value}, platform="linux", home=_HOME)
    assert resolved == _HOME / ".cache" / "zikaron" / "models"


def test_the_resolved_directory_is_never_under_the_tempdir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The property, stated over the process's own environment rather than a supplied one, since
    that is the form every caller uses.
    """
    monkeypatch.delenv(FASTEMBED_CACHE_VARIABLE, raising=False)
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    resolved = resolved_model_cache_dir()
    assert not resolved.is_relative_to(Path(tempfile.gettempdir()))


def test_an_explicit_override_is_obeyed_even_into_the_tempdir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The guard above is about the *default*, not a prohibition: CI deliberately points the
    variable at `$RUNNER_TEMP`, and a resolver that refused that would redden every job.
    """
    monkeypatch.setenv(FASTEMBED_CACHE_VARIABLE, str(tmp_path))
    assert resolved_model_cache_dir() == tmp_path


def test_the_snapshot_layout_matches_the_librarys_own() -> None:
    """A premise guard, not a check on our code: `snapshot_dir` derives a path `huggingface_hub`
    owns, because the library spells it in `file_download`, which is not public surface.

    If this fails, the cache layout moved and `doctor` would report a present artefact absent —
    the response is to re-read the layout, not to delete this.
    """
    from huggingface_hub.file_download import repo_folder_name  # noqa: PLC0415

    repo_id = "qdrant/bge-small-en-v1.5-onnx-q"
    revision = "0" * 40
    library = Path("/cache") / repo_folder_name(repo_id=repo_id, repo_type="model")
    assert snapshot_dir(Path("/cache"), repo_id=repo_id, revision=revision) == (
        library / "snapshots" / revision
    )
