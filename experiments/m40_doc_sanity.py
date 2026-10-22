"""Mechanical checks of a code-knowledge corpus: format, K14 front matter, dependency paths, wording.

    .venv/bin/python experiments/m40_doc_sanity.py <project root> <module> [<old documents dir>]

Run over Warp's clone for `research/m40-toy-run.md` §17. The wording hits are candidates for a
reader to judge, not findings: most are identifiers, constants and comments read from the source.
"""

import re
import statistics
import subprocess
import sys
from pathlib import Path

SECTIONS = ("## Purpose", "## Declarations", "## Behavior", "## Dependencies")
WORDING = re.compile(
    r"#\d{3,5}\b|\bissue\b|\bbug\b|\bpull request\b|\bPR\b|github|warpdotdev|\bregression\b|"
    r"\bworkaround\b|\bknown (?:issue|problem|bug)\b",
    re.IGNORECASE,
)
PATH = re.compile(r"`([\w./-]+\.\w+)`")
DASH = re.compile(r" (?:—|-) ")


def main() -> int:
    root, module = Path(sys.argv[1]), sys.argv[2]
    old = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    docs = root / "code-knowledge"
    problems: list[tuple[str, str]] = []
    missing: list[tuple[str, str]] = []
    wording: list[tuple[str, int, str, str]] = []
    sizes: list[int] = []
    ratios: list[float] = []
    deps = 0
    documents = sorted(p for p in (docs / module).rglob("*.md") if p.name != "README.md")
    for doc in documents:
        rel = doc.relative_to(docs).as_posix()
        source = rel.removesuffix(".md")
        text = doc.read_text(encoding="utf-8")
        sizes.append(len(text))
        if old is not None and (old / rel).exists():
            ratios.append(len(text) / max(1, len((old / rel).read_text(encoding="utf-8"))))
        front = re.match(r"---\n(.*?)\n---\n", text, re.S)
        if front is None:
            problems.append((rel, "no front matter"))
            continue
        fields = dict(line.split(": ", 1) for line in front.group(1).splitlines() if ": " in line)
        if fields.get("zikaron-source") != source:
            problems.append((rel, f"zikaron-source is {fields.get('zikaron-source')!r}"))
        blob = subprocess.run(
            ["git", "-C", str(root), "hash-object", source],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        if fields.get("zikaron-source-blob") != blob:
            problems.append((rel, "zikaron-source-blob differs from git hash-object"))
        problems += [(rel, f"no {s}") for s in SECTIONS if f"\n{s}\n" not in text]
        for n, line in enumerate(text.splitlines(), 1):
            if line.lstrip("- ").startswith("Depends on:"):
                for path in PATH.findall(DASH.split(line, maxsplit=1)[0]):
                    deps += 1
                    if not (root / path).exists():
                        missing.append((rel, path))
            wording += [(rel, n, m.group(0), line.strip()[:200]) for m in WORDING.finditer(line)]

    print(f"documents, README aside: {len(documents)}")
    print(f"README: {'present' if (docs / module / 'README.md').exists() else 'absent'}")
    print(f"format and front-matter problems: {len(problems)}")
    for rel, what in problems:
        print(f"   {rel}: {what}")
    print(f"Depends-on paths: {deps}, not found: {len(missing)}")
    for rel, path in missing:
        print(f"   {rel}: {path}")
    if sizes:
        print(f"bytes: median {statistics.median(sizes):.0f}, max {max(sizes)}, total {sum(sizes)}")
    if ratios:
        print(f"length against the old document: median {statistics.median(ratios):.2f}x")
    print(f"wording hits: {len(wording)} in {len({w[0] for w in wording})} documents")
    for rel, n, term, line in wording:
        print(f"   {rel}:{n} {term!r} | {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
