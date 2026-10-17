"""Count a code-knowledge corpus's dependency bullets that leave the template or name no file.

Usage: python experiments/m40_dependency_lines.py <project root> <documents directory>

The documents directory is the module's, under `code-knowledge/`; its README is skipped. A bullet is
in the template's form when it starts `- Depends on:`, and its path is the first backticked token
with an extension, tested for existence from the project root.
"""

import re
import sys
from pathlib import Path

_SECTION = re.compile(r"^## Dependencies\n(.*?)(?=^## |\Z)", re.S | re.M)
_PATH = re.compile(r"`([^`]+\.[a-z]+)`")
_HEDGE = re.compile(r"\((or [a-z ]+|via [^)]*)\)")


def main(root: Path, documents: Path) -> None:
    bullets = off_form = off_form_paths = off_form_missing = hedged = in_form = missing = 0
    off_form_documents: set[Path] = set()
    missing_documents: set[Path] = set()
    for document in sorted(documents.rglob("*.md")):
        if document.name == "README.md":
            continue
        section = _SECTION.search(document.read_text(encoding="utf-8"))
        if section is None:
            continue
        for line in section.group(1).splitlines():
            if not line.startswith("- "):
                continue
            bullets += 1
            hedged += bool(_HEDGE.search(line))
            path = _PATH.search(line)
            if not line.startswith("- Depends on:"):
                off_form += 1
                off_form_documents.add(document)
                if path is not None:
                    off_form_paths += 1
                    off_form_missing += not (root / path.group(1)).exists()
                continue
            if path is None:
                continue
            in_form += 1
            if not (root / path.group(1)).exists():
                missing += 1
                missing_documents.add(document)
    print(f"bullets {bullets}; hedged {hedged}")
    print(f"off the template's form {off_form} in {len(off_form_documents)} documents;", end=" ")
    print(f"of their {off_form_paths} paths, {off_form_missing} name no file")
    print(f"in form {in_form}; naming no file {missing} in {len(missing_documents)} documents")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
