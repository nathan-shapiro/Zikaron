"""A test asserts stdlib-only imports, and specifically that `logging` is
not among them, for every module on the `agentSpawn`/`userPromptSubmit` critical path.

`architecture.md` §Components: "`zikaron-hook` stays stdlib-only." `coding-standards.md` §6 gives
the number the rule rests on — `import logging` alone costs ~15 ms, the same class of number as
the whole stdlib-thinness argument the hook exists to satisfy — and states the exception this
test's own discovery logic encodes: "`logging` for anything long-running or off the critical
path."

`warm_helper.py` is that one deliberate exception, exactly as `service/log.py` is for the service,
and the warm helper's own module docstring states directly: it runs as a **separate, detached
process image**, spawned by `spawn_warm.py` but never imported by it, so its own import cost is
paid in a process nothing on the critical path is waiting on.

**This module is a rewrite of an earlier, weaker version that used two hand-maintained lists — a
"critical path modules" tuple and a "forbidden third-party packages" tuple — both real gaps rather
than merely inelegant.** A denylist of *anticipated* forbidden packages
(`aiosqlite`, `fastembed`, and so on) would silently pass a genuinely new, unanticipated
third-party import — `requests`, say — since nothing about that name was ever listed as forbidden;
the whole enforcement claim of "stdlib-only" rests on catching *any* non-stdlib import, not merely
the ones a past contributor happened to think of. And a hand-maintained list of "every module on
the critical path" opts a new hook module *out* of enforcement by default until someone remembers
to add it to the list — the identical failure class `check.sh`'s own `--cov` flags were caught in
elsewhere, restated here for a test's own coverage rather than a coverage tool's. Both are fixed the
same way: **discover** the true module set from the package directory on disk, and **classify**
every newly-imported top-level package as stdlib, `zikaron` itself, or forbidden — an allowlist of
what is *known good* (`sys.stdlib_module_names`, the interpreter's own authoritative list, plus the
package under test), which cannot be silently defeated by a package nobody happened to name.
"""

import subprocess
import sys
from pathlib import Path

import pytest

#: `warm_helper.py` is the one deliberate exception to this whole file's own enforcement, per the
#: module docstring above and `warm_helper.py`'s own: it runs as a separate, detached process
#: image, off any critical path, and is therefore explicitly excluded from stdlib-only
#: enforcement rather than silently skipped.
_DELIBERATE_EXCEPTION = "warm_helper"

_PACKAGE_ROOT = Path(__file__).resolve().parent.parent / "zikaron"

#: Both packages on the critical path, not only the hook's own. `zikaron.harness` is imported by
#: `zikaron-hook` on every trigger it serves, so an expensive import added there costs exactly what
#: one added to `zikaron.hook` would — and the whole enforcement claim of this file is that a new
#: module is covered by default rather than when someone remembers to list it. A seam that is
#: stdlib-only by intent and unguarded in fact is the gap this closes.
_CRITICAL_PATH_PACKAGES = ("hook", "harness")


def _discover_critical_path_modules() -> frozenset[str]:
    """Every module on the critical path that actually exists on disk right now, minus the one
    documented exception — computed fresh each run rather than hand-maintained, so a new module
    added to either package is enforced by default rather than silently exempt until a test file is
    remembered and edited.
    """
    modules: set[str] = set()
    for package in _CRITICAL_PATH_PACKAGES:
        modules.add(f"zikaron.{package}")
        for path in (_PACKAGE_ROOT / package).glob("*.py"):
            stem = path.stem
            if stem in ("__init__", _DELIBERATE_EXCEPTION):
                continue
            modules.add(f"zikaron.{package}.{stem}")
    return frozenset(modules)


_CRITICAL_PATH_MODULES = _discover_critical_path_modules()


def _sys_modules_after_import(module_name: str) -> frozenset[str]:
    """The top-level package names newly added to `sys.modules` by importing `module_name`, in a
    **fresh subprocess** rather than this test process's own interpreter.

    A subprocess, deliberately: this test suite's own process has already imported half the
    third-party stack for other tests by the time this one runs (`fastembed`, `aiosqlite`, and so
    on, from fixtures and other modules collected in the same session), so checking
    `sys.modules` in-process would either report false positives from unrelated prior imports or
    require painstakingly reverting every one of them first. A fresh interpreter has none of that
    history, so what it reports after importing exactly one module is attributable to that import
    alone.
    """
    script = (
        f"import sys\n"
        f"before = set(sys.modules)\n"
        f"import {module_name}\n"
        f"after = set(sys.modules)\n"
        f"new = after - before\n"
        f"print(','.join(sorted({{m.split('.')[0] for m in new}})))\n"
    )
    result = subprocess.run(  # noqa: S603 — a fixed, test-constructed script and interpreter path.
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    top_level = result.stdout.strip()
    return frozenset(top_level.split(",")) if top_level else frozenset()


def _non_stdlib_non_zikaron(added: frozenset[str]) -> frozenset[str]:
    """Every name in `added` that is neither part of the standard library
    (`sys.stdlib_module_names`, the interpreter's own authoritative list — not a hand-transcribed
    copy of it that could drift) nor this project's own `zikaron` package. Whatever remains is, by
    construction, a third-party import — the positive classification a denylist of *anticipated*
    packages cannot give, since a package nobody thought to list would otherwise pass silently.
    """
    return added - set(sys.stdlib_module_names) - {"zikaron"}


class TestDiscoveredModuleSetMatchesThePackageDirectory:
    """A guard on the guard: proves `_discover_critical_path_modules` is actually reading the
    real package directory rather than, say, silently returning an empty set that would make
    every test below vacuously pass.
    """

    def test_the_discovered_set_is_non_empty(self) -> None:
        assert len(_CRITICAL_PATH_MODULES) >= 5

    def test_warm_helper_is_excluded_from_the_discovered_set(self) -> None:
        assert "zikaron.hook.warm_helper" not in _CRITICAL_PATH_MODULES

    def test_every_known_hook_module_is_present_in_the_discovered_set(self) -> None:
        """Not a hand-maintained list this test could silently disagree with the real directory
        about — a spot check against names known to exist at the time this test was written,
        so a future rename or deletion is at least noticed here even though the enforcement
        itself does not depend on this list staying accurate.
        """
        expected_present = {
            "zikaron.hook",
            "zikaron.hook.main",
            "zikaron.hook.push",
            "zikaron.hook.spawn_warm",
            "zikaron.hook.subagent_policy",
            "zikaron.hook.connect",
            "zikaron.hook.rpc",
            "zikaron.hook.envelope",
            "zikaron.hook.failure",
            "zikaron.hook.tripwire",
            "zikaron.hook.write_policy",
            "zikaron.harness",
            "zikaron.harness.spec",
            "zikaron.harness.detect",
        }
        assert expected_present <= _CRITICAL_PATH_MODULES


@pytest.mark.parametrize("module_name", sorted(_CRITICAL_PATH_MODULES))
def test_no_third_party_package_is_imported(module_name: str) -> None:
    added = _sys_modules_after_import(module_name)
    forbidden = _non_stdlib_non_zikaron(added)
    assert not forbidden, f"{module_name} pulled in non-stdlib package(s): {sorted(forbidden)}"


def test_logging_specifically_is_not_among_the_critical_path_modules_imports() -> None:
    """Named separately from the general third-party sweep above because the contract
    states it as its own clause: "a test asserts stdlib-only imports **and specifically that
    `logging` is not among them**" — worth a dedicated assertion precisely because `logging` is
    itself stdlib and so is *not* caught by `_non_stdlib_non_zikaron`'s own positive
    classification, only by a check that names it directly.
    """
    for module_name in sorted(_CRITICAL_PATH_MODULES):
        added = _sys_modules_after_import(module_name)
        assert "logging" not in added, module_name


def test_a_hypothetical_third_party_import_would_be_caught(tmp_path: Path) -> None:
    """The enforcement claim this whole file exists to make, proven rather than assumed: a
    genuinely arbitrary, previously-unlisted third-party-shaped import must fail
    `_non_stdlib_non_zikaron`'s own classification, since it is neither in
    `sys.stdlib_module_names` nor named `zikaron`. `requests` is not actually installed in this
    project's pinned venv, so this test does not import a real third-party package (which could
    silently start passing if a future dependency change happened to add it as a transitive import
    of something else); it constructs a throwaway module on `sys.path` with an unmistakably
    non-stdlib name instead, which cannot be confused with anything this project's own dependency
    tree could ever legitimately pull in.
    """
    fake_module_dir = tmp_path / "definitely_not_stdlib_or_zikaron"
    fake_module_dir.mkdir()
    (fake_module_dir / "__init__.py").write_text("", encoding="utf-8")
    script = (
        "import sys\n"
        f"sys.path.insert(0, {str(tmp_path)!r})\n"
        "before = set(sys.modules)\n"
        "import definitely_not_stdlib_or_zikaron\n"
        "after = set(sys.modules)\n"
        "new = after - before\n"
        "print(','.join(sorted({m.split('.')[0] for m in new})))\n"
    )
    result = subprocess.run(  # noqa: S603 — a fixed, test-constructed script and interpreter path.
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    added = frozenset(result.stdout.strip().split(","))
    forbidden = _non_stdlib_non_zikaron(added)
    assert "definitely_not_stdlib_or_zikaron" in forbidden


def test_warm_helper_is_the_one_documented_exception_and_does_use_logging() -> None:
    """The converse of every test above: `warm_helper.py` is *expected* to import `logging`, and
    a test suite that only ever asserted absence would not notice if this module's own exemption
    silently stopped being true — e.g. if a future edit removed its `logging` usage without
    updating its own module docstring's claim to be the deliberate exception.
    """
    added = _sys_modules_after_import("zikaron.hook.warm_helper")
    assert "logging" in added
