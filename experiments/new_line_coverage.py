"""Which lines a change adds under `zikaron/` no test executes — what the coverage ratchet cannot say.

    .venv/bin/python experiments/new_line_coverage.py [--base REF] [--data FILE]

`check.sh`'s floor is a total, so a change can add untested code and stay green as long as the
whole package stays above it. This reads the coverage data `./check.sh` leaves in `.coverage` and
reports, for every line the working tree adds against `--base` (default `HEAD`; untracked files
count whole), the statements no test ran and the branches no test took. Exit status 1 if any
statement is uncovered. Against a committed branch, pass `--base "$(git merge-base main HEAD)"`.

Run it after a green `./check.sh` and before a review round: the coverage data is only as current
as the run that wrote it.
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import coverage

_REPO = Path(__file__).resolve().parent.parent
_HUNK = re.compile(r"\+(\d+)(?:,(\d+))?")


def _git(*arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(_REPO), *arguments], capture_output=True, text=True, check=True
    ).stdout


def _added_lines(base: str) -> dict[str, set[int]]:
    """Every line number added under `zikaron/`, per Python file, against `base`."""
    added: dict[str, set[int]] = {}
    current: str | None = None
    for line in _git("diff", "-U0", base, "--", "zikaron/").splitlines():
        if line.startswith("+++ "):
            current = None if line.endswith("/dev/null") else line.removeprefix("+++ b/")
        elif line.startswith("@@") and current is not None and current.endswith(".py"):
            found = _HUNK.search(line)
            if found is not None:
                start, count = int(found.group(1)), int(found.group(2) or "1")
                added.setdefault(current, set()).update(range(start, start + count))
    for path in _git("ls-files", "--others", "--exclude-standard", "zikaron/").splitlines():
        if path.endswith(".py"):
            count = len((_REPO / path).read_text(encoding="utf-8").splitlines())
            added[path] = set(range(1, count + 1))
    return added


def _report(data: Path, paths: list[str]) -> dict[str, dict[str, object]]:
    measured = coverage.Coverage(data_file=str(data), config_file=str(_REPO / "pyproject.toml"))
    measured.load()
    with tempfile.TemporaryDirectory() as scratch:
        out = Path(scratch) / "coverage.json"
        measured.json_report(
            morfs=[str(_REPO / path) for path in paths], outfile=str(out), ignore_errors=True
        )
        files: dict[str, dict[str, object]] = json.loads(out.read_text(encoding="utf-8"))["files"]
    return {str(Path(name).resolve().relative_to(_REPO)): entry for name, entry in files.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="HEAD")
    parser.add_argument("--data", type=Path, default=_REPO / ".coverage")
    arguments = parser.parse_args()
    added = _added_lines(arguments.base)
    report = _report(arguments.data, sorted(added))
    statements = uncovered = 0
    for path, lines in sorted(added.items()):
        entry = report.get(path)
        if entry is None:
            print(f"{path}: not in the coverage data — not imported by any test, or not measured")
            uncovered += len(lines)
            continue
        executed = set(entry["executed_lines"])  # type: ignore[arg-type]
        missing = sorted(lines & set(entry["missing_lines"]))  # type: ignore[arg-type]
        branches = sorted(
            (source, target)
            for source, target in entry.get("missing_branches", [])  # type: ignore[attr-defined]
            if source in lines
        )
        statements += len(lines & (executed | set(missing)))
        uncovered += len(missing)
        if missing or branches:
            print(f"{path}: lines {missing} branches {branches}")
    print(f"{statements} new statements, {uncovered} uncovered")
    return 1 if uncovered else 0


if __name__ == "__main__":
    sys.exit(main())
