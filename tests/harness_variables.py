"""Every variable a harness exports that a test must not inherit from the harness that launched
pytest: each spec's marker, its session variable, and the variable naming its project.

The last one repoints the **store** — D17's scope — so a test that set a marker and then reached
resolution would otherwise adopt whichever project launched pytest and read and write its real
memories. The agent's own shell exports no such value
(`research/claude-project-dir-reaches-hooks-not-shells.md`), so the launching process has to be
one that does; a hook is, and a future version might be.

Read by `conftest`'s per-test scrub and by `kiro_live.chat`, whose class-scoped callers run before
that scrub, so the two cannot drift into different sets.
"""

from typing import Final

from zikaron.harness.spec import SPECS

HARNESS_VARIABLES: Final = tuple(
    sorted(
        {
            name
            for spec in SPECS.values()
            for name in (spec.marker_variable, spec.session_variable, spec.project_dir_variable)
            if name is not None
        }
    )
)
