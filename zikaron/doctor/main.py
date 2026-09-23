"""`zikaron doctor` — run the checks, print them, and exit non-zero if any failed.

Everything goes to standard output, remedies included: the whole report is what a person asked for,
and splitting it across two streams interleaves unpredictably the moment it is piped. The exit
status, not the stream, is what a script reads.
"""

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from zikaron.doctor.checks import Finding, Outcome, run_all
from zikaron.harness import detect

#: Unlike `install` and `knowledge`, this command has no `python -m` form: it is new with the
#: umbrella, so there is no documented invocation predating it to keep working, and a package
#: needs a `__main__.py` to have one at all.
_DEFAULT_PROG: Final = "zikaron doctor"


def _parser(prog: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog,
        description=(
            "Check that this machine can run Zikaron, naming a remedy for anything it cannot."
        ),
    )
    parser.add_argument(
        "--project",
        type=Path,
        default=None,
        help="the project whose socket path to check. The default is the harness's own project "
        "directory where it names one, else the current directory.",
    )
    return parser


def rendered(findings: Sequence[Finding]) -> list[str]:
    """The report as lines. Separate from printing them, so a test reads the report itself."""
    width = max(len(finding.name) for finding in findings)
    lines = []
    for finding in findings:
        lines.append(f"{finding.outcome.value:<4} {finding.name:<{width}}  {finding.detail}")
        if finding.remedy is not None:
            lines.append(f"{'':<4} {'':<{width}}  remedy: {finding.remedy}")
    return lines


def main(argv: Sequence[str] | None = None, *, prog: str = _DEFAULT_PROG) -> int:
    """Report on this machine. Returns 1 if any check failed, 0 otherwise.

    An absent model cache is not a failure: there is no install-time prefetch, so the first run of
    this command on a new machine finds none, and a red first run would be reporting the design
    rather than a problem.
    """
    args = _parser(prog).parse_args(sys.argv[1:] if argv is None else argv)
    store_dir = args.project or detect.current_spec().store_scope_dir(Path.cwd())
    findings = run_all(store_dir=store_dir, environ=os.environ, platform=sys.platform)
    for line in rendered(findings):
        print(line)
    return 1 if any(finding.outcome is Outcome.FAILED for finding in findings) else 0
