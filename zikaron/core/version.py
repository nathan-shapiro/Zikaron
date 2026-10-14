"""Which version of Zikaron this process is, as its installed distribution states it.

One function for both sides of the comparison a typed command makes against the service it reaches
(`design/distribution.md` §3), so the two cannot come to read the number differently.
"""

import importlib.metadata
from typing import Final

#: The distribution whose metadata names the version.
DISTRIBUTION: Final = "zikaron"

#: What a source tree that was never installed reports, having no metadata to read.
NO_DISTRIBUTION: Final = "unknown — no installed distribution, so this is a source tree"


def package_version() -> str:
    """The installed distribution's version, or `NO_DISTRIBUTION` when there is none.

    A source tree that was never installed has none, and raising there would fail in the one
    situation the answer exists for: establishing what is being run. It identifies a *build* only
    for a released install — a `git+` or editable one reports whatever `pyproject.toml` said when it
    was installed.

    Read from metadata the moment it is called, so a long-lived process that must report the version
    it started with reads it once, at its start.
    """
    try:
        return importlib.metadata.version(DISTRIBUTION)
    except importlib.metadata.PackageNotFoundError:
        return NO_DISTRIBUTION
