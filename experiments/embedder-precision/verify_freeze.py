#!/usr/bin/env python
"""Check that the artefacts PREREGISTRATION.md froze have not moved.

Run this before trusting any round-2 number. If `identifiers.py` has changed, the held-out
extractor test in `extractor_heldout.py` is no longer held out and must be re-authored on fresh
material. If a dataset hash has changed, the recorded results describe a different corpus.

Usage: .venv/bin/python verify_freeze.py   (exit 1 on any mismatch)
"""
import hashlib
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).parent
PREREG = HERE / "PREREGISTRATION.md"


def main() -> int:
    text = PREREG.read_text()
    block = re.search(r"```\n((?:[0-9a-f]{64}  \S+\n)+)```", text)
    if not block:
        print("FAIL: no hash block found in PREREGISTRATION.md")
        return 1
    bad = 0
    for line in block.group(1).strip().splitlines():
        want, name = line.split("  ", 1)
        p = HERE / name.strip()
        if not p.exists():
            print(f"MISSING {name}")
            bad += 1
            continue
        got = hashlib.sha256(p.read_bytes()).hexdigest()
        ok = got == want
        print(f"{'ok  ' if ok else 'MOVED'} {name}")
        if not ok:
            print(f"       preregistered {want}\n       on disk       {got}")
            bad += 1
    if bad:
        print(f"\n{bad} artefact(s) differ from the preregistration. "
              "Round-2 results are not attributable until this is resolved.")
        return 1
    print("\nall preregistered artefacts unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
