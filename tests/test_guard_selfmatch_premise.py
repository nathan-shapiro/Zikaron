"""The platform fact the self-match rule rests on, measured on the machine running the suite
(`design/guards.md` §9.6).

Each `pgrep` runs inside `bash -c '<call> 2>"$err"; echo "rc=$?"; true'` with a fresh nonce as its
pattern: the trailing `true` keeps the shell alive past the call, as Claude Code's wrapper does,
and the call's own exit code and stderr come back through the `rc=` line and `$err`. On `linux`
the shell is matchable unless `-A` is given, and `pgrep -a` prints it on one line; on `darwin` it
is matchable only with `-a`. A machine with no `pgrep` fails rather than skips: a skip would report
as checked a premise nobody checked.
"""

import os
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest

from zikaron.guard.selfmatch import Platform

pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class Run:
    """One `pgrep` call's outcome, and the id of the shell that ran it."""

    returncode: int
    stdout: str
    stderr: str
    shell: int

    def found_shell(self) -> bool:
        return any(line.split(maxsplit=1)[:1] == [str(self.shell)] for line in self.lines)

    @property
    def lines(self) -> list[str]:
        return self.stdout.splitlines()


def _platform() -> Platform:
    platform = next((each for each in Platform if each.value == sys.platform), None)
    assert platform is not None, f"the rule reads no pgrep on {sys.platform}"
    assert shutil.which("pgrep") is not None, "pgrep is not on PATH"
    return platform


def _run(tmp_path: Path, call: str, *, then: str = "") -> Run:
    """`call` with a fresh nonce appended, in a shell that outlives it; `then` is a further line
    of the same script."""
    nonce = f"zikaron-premise-{uuid.uuid4().hex}"
    err = tmp_path / "err"
    script = f'{call} {nonce} 2>"$err"; echo "rc=$?"; true{then}'
    bash = shutil.which("bash")
    assert bash is not None, "bash is not on PATH"
    process = subprocess.Popen(  # noqa: S603 — bash and a script this test built.
        [bash, "-c", script],
        stdout=subprocess.PIPE,
        text=True,
        env={"err": str(err), "PATH": os.environ.get("PATH", os.defpath)},
    )
    output, _ = process.communicate(timeout=30)
    *printed, status = output.splitlines()
    assert status.startswith("rc="), output
    return Run(int(status.removeprefix("rc=")), "\n".join(printed), err.read_text(), process.pid)


def test_without_its_exclusion_pgrep_finds_the_shell_running_it(tmp_path: Path) -> None:
    run = _run(tmp_path, "pgrep -f" if _platform() is Platform.LINUX else "pgrep -a -f")
    assert run.returncode == 0, run
    assert run.found_shell(), run


def test_by_default_darwins_pgrep_does_not_find_its_shell(tmp_path: Path) -> None:
    if _platform() is not Platform.DARWIN:
        pytest.skip("darwin's default; linux's is the test above")
    run = _run(tmp_path, "pgrep -f")
    assert (run.returncode, run.stdout) == (1, ""), run


def test_linux_pgrep_with_ignore_ancestors_does_not_find_its_shell(tmp_path: Path) -> None:
    if _platform() is not Platform.LINUX:
        pytest.skip("-A is procps-ng's")
    run = _run(tmp_path, "pgrep -A -f")
    if run.returncode != 0 and run.stderr:
        pytest.skip(f"this pgrep lacks -A: {run.stderr.strip()}")
    assert (run.returncode, run.stdout) == (1, ""), run


def test_linux_pgrep_lists_a_multi_line_shell_on_one_line(tmp_path: Path) -> None:
    """The exemption's premise (§9.2): a line filter that matches the shell drops all of it."""
    if _platform() is not Platform.LINUX:
        pytest.skip("the exemption is linux's")
    run = _run(tmp_path, "pgrep -af", then="\ntrue second-line")
    (line,) = [line for line in run.lines if line.split(maxsplit=1)[0] == str(run.shell)]
    assert "second-line" in line, run
