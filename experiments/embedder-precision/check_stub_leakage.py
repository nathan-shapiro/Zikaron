#!/usr/bin/env python3
"""Mechanical prose-leakage check for stubs_v2.json.

The stub file exists so a later stage can author user prompts having never read the
memory corpus. That only works if the stubs carry no memory *prose*. Identifiers are
explicitly allowed to leak verbatim (a user working on WidgetV2 really types
WidgetV2), so only the free-text ``situation`` field is checked.

Rule: no ``situation`` may share a span of N or more consecutive words (default 3)
with any memory's ``gist`` or ``content``.

Normalisation: lowercase, split on whitespace, then strip every non-alphanumeric
character *inside* each token. Token boundaries therefore come from whitespace only,
so ``build.gradle.kts`` collapses to one token ``buildgradlekts`` rather than three.
That is deliberate: it means a single shared identifier can never by itself trip the
check, while two words of shared prose on either side of it still will.

Exit status 0 if clean, 1 if any violation. ``--json`` emits machine-readable output.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
DATASET = HERE / "dataset.json"
STUBS = HERE / "stubs_v2.json"

_STRIP = re.compile(r"[^a-z0-9]+")


def normalise(text: str) -> list[str]:
    """Lowercase, whitespace-split, strip punctuation inside tokens, drop empties."""
    out = []
    for raw in text.lower().split():
        tok = _STRIP.sub("", raw)
        if tok:
            out.append(tok)
    return out


def ngrams(tokens: list[str], n: int) -> list[tuple[str, ...]]:
    return [tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--span", type=int, default=3, help="forbidden span length in words")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    ap.add_argument("--dataset", type=pathlib.Path, default=DATASET)
    ap.add_argument("--stubs", type=pathlib.Path, default=STUBS)
    args = ap.parse_args()

    dataset = json.loads(args.dataset.read_text())
    stubs = json.loads(args.stubs.read_text())

    # Map every forbidden n-gram back to the memories that contain it, so a violation
    # report says which record was echoed.
    corpus: dict[tuple[str, ...], set[str]] = {}
    for mem in dataset["memories"]:
        for field in ("gist", "content"):
            for gram in ngrams(normalise(mem[field]), args.span):
                corpus.setdefault(gram, set()).add(mem["key"])

    violations = []
    for stub in stubs["stubs"]:
        situation = stub["situation"]
        toks = normalise(situation)
        for gram in ngrams(toks, args.span):
            if gram in corpus:
                violations.append(
                    {
                        "stub_id": stub["stub_id"],
                        "span": " ".join(gram),
                        "situation": situation,
                        "memories": sorted(corpus[gram]),
                    }
                )

    over_length = [
        {"stub_id": s["stub_id"], "words": len(s["situation"].split())}
        for s in stubs["stubs"]
        if len(s["situation"].split()) > 15
    ]

    report = {
        "span": args.span,
        "n_stubs": len(stubs["stubs"]),
        "n_memories": len(dataset["memories"]),
        "corpus_ngrams": len(corpus),
        "violations": violations,
        "n_violations": len(violations),
        "situation_over_15_words": over_length,
    }

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(
            f"span={args.span}  stubs={report['n_stubs']}  memories={report['n_memories']}  "
            f"corpus {args.span}-grams={report['corpus_ngrams']}"
        )
        for v in violations:
            print(f"  LEAK {v['stub_id']}: '{v['span']}'  <- {', '.join(v['memories'])}")
            print(f"       situation: {v['situation']}")
        for o in over_length:
            print(f"  LONG {o['stub_id']}: situation is {o['words']} words (max 15)")
        print(f"violations={len(violations)}  over_length={len(over_length)}")

    return 1 if (violations or over_length) else 0


if __name__ == "__main__":
    sys.exit(main())
