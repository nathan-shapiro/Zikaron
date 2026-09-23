"""Where the embedding model's files live on disk, as a pure function of the environment.

**fastembed's default is a temporary directory, and the model is 64 MB.** `TextEmbedding` with no
`cache_dir` calls `define_cache_dir(None)`, which resolves `$FASTEMBED_CACHE_PATH` or
`tempfile.gettempdir()/fastembed_cache`. Measured 2026-09-21: 64 MB under `/tmp/fastembed_cache/`
on Linux, and on macOS `TMPDIR` is a per-session `/var/folders/…` path, so the download is paid
again after a reboot and on macOS potentially after a logout.

**Per-user, never per-store.** The artefact is one pinned set of bytes, so a copy under each
project's `.zikaron/` would be 64 MB duplicated for files identical by construction.

**`$FASTEMBED_CACHE_PATH` is read here because passing `cache_dir` stops fastembed reading it.**
`define_cache_dir` consults the variable only when its argument is `None`, so honouring it is what
keeps a setting that already works — including M28's CI cache — working unchanged.

**A relative override is ignored rather than resolved**, on both variables. Either would resolve
against the process's working directory, which for the service is whichever project spawned it —
turning a per-user cache into a per-store one silently, which is the outcome this module exists to
prevent.
"""

import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Final

#: fastembed's own variable, honoured verbatim as the cache directory: its value is what the
#: `models--<org>--<name>/` trees sit directly under, which is the layout CI already caches.
FASTEMBED_CACHE_VARIABLE: Final = "FASTEMBED_CACHE_PATH"

#: The XDG variable, honoured on macOS too. A user who sets it has said where caches go, and
#: `~/Library/Caches` is the fallback for having *not* said.
_XDG_CACHE_VARIABLE: Final = "XDG_CACHE_HOME"

_APPLICATION_DIRECTORY: Final = "zikaron"

#: Under the application directory rather than at it, so a later cache of something other than
#: model artefacts is a sibling instead of a rename.
_MODELS_DIRECTORY: Final = "models"


def _absolute_override(environ: Mapping[str, str], variable: str) -> Path | None:
    """The variable's value if it names an absolute path, else nothing."""
    value = environ.get(variable, "").strip()
    if not value:
        return None
    candidate = Path(value)
    return candidate if candidate.is_absolute() else None


def model_cache_dir(*, environ: Mapping[str, str], platform: str, home: Path) -> Path:
    """The directory the model's files belong in, given an environment.

    Pure, and taking `environ`, `platform` and `home` rather than reading them, so a test states
    the environment it is checking instead of mutating the process's — the same reason
    `service.paths` and `config.resolution` take theirs.

    Args:
        environ: the process environment, consulted for the two cache variables only.
        platform: `sys.platform`, which selects macOS's cache convention.
        home: the user's home directory.
    """
    fastembed_override = _absolute_override(environ, FASTEMBED_CACHE_VARIABLE)
    if fastembed_override is not None:
        return fastembed_override
    xdg_cache_home = _absolute_override(environ, _XDG_CACHE_VARIABLE)
    if xdg_cache_home is not None:
        return xdg_cache_home / _APPLICATION_DIRECTORY / _MODELS_DIRECTORY
    if platform == "darwin":
        return home / "Library" / "Caches" / _APPLICATION_DIRECTORY / _MODELS_DIRECTORY
    return home / ".cache" / _APPLICATION_DIRECTORY / _MODELS_DIRECTORY


def snapshot_dir(cache_dir: Path, *, repo_id: str, revision: str) -> Path:
    """Where `snapshot_download` puts one revision of one repository, under `cache_dir`.

    Derived rather than imported: `huggingface_hub` spells this in `file_download`, which is not
    part of its public surface, and a private import that moved would leave this looking in the
    wrong place and reporting the artefact absent. The layout is documented, and
    `test_indexing_model_cache.py` pins this against the library's own function so a change turns
    the gate red instead.
    """
    return cache_dir / f"models--{repo_id.replace('/', '--')}" / "snapshots" / revision


def resolved_model_cache_dir() -> Path:
    """`model_cache_dir` against this process's own environment.

    The one impure entry point, so that every caller reaches the same answer without each of them
    assembling the same three arguments.
    """
    return model_cache_dir(environ=os.environ, platform=sys.platform, home=Path.home())
