"""Where a typed command's refusals and failures are printed, and how a `ZikaronError` reads there.

Apart from `report.py` because that module imports the service client, and a command that never
connects — `zikaron code-knowledge plan` — prints its refusals the same way without paying for it.
"""

import sys

from zikaron.core.errors import ERROR_SPECS, ZikaronError


def stderr(line: str) -> None:
    """Where every refusal and failure from a typed command goes.

    Standard error, so redirecting a sweep's report leaves the reasons visible.
    """
    print(line, file=sys.stderr)


def render(error: ZikaronError) -> None:
    """Print one `ZikaronError` by its code's own declared disposition.

    Exactly as a refusal that arrived over the wire is printed, so a failure raised locally and one
    the service sent cannot disagree about whether a caller has a move. Reached from `execute` and
    from the resolution that runs before any connection exists.
    """
    stderr(f"{ERROR_SPECS[error.code].disposition.value}: {error.message} ({error.detail()})")
