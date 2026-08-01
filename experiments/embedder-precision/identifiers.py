#!/usr/bin/env python
"""Deterministic identifier extraction for the `tokens` FTS column (config 5).

Zero LLM. Pure regex. Extracts the token shapes that carry precise meaning in tribal
knowledge and that a WordPiece embedder is most likely to smear:

  * SCREAMING_SNAKE env-var shapes            AUTH_TOKEN_V2, DATABASE_URL_RO
  * snake_case identifiers                    retry_backoff_ms, parse_datetime
  * CamelCase / PascalCase identifiers        WidgetV2, JsonSerializer
  * dotted paths                              org.example.core.Config, conftest.py
  * semver-ish versions                       v2.3.10, 4.2, 0.14.2
  * flags                                     --no-cache-dir
  * file paths                                /var/run/secrets/batch/creds.json
  * bare digit runs that look like ids        0042, 0042_1, 137, 98

Also emits *decomposed* forms alongside the whole token (WidgetV2 -> widget, v2; and the
version 2.3.10 -> 2, 3, 10) because BM25 needs a term to match on and users do not always
type the full identifier. The whole token is emitted first and repeated twice, which is a
crude way of weighting the exact form above its parts within a single FTS column.

GOTCHA, found the hard way and load-bearing for the whole config-5 result: the first version
of this extractor "glued" identifiers by deleting all punctuation (conf_test.py -> conftestpy).
That collapses conftest.py and conf_test.py to the SAME token, i.e. it manufactures a brand-new
collision on precisely the near-miss pair the tokens column exists to disambiguate. The fix is
to keep the identifier's punctuation intact and to build the FTS table with
`tokenize="unicode61 tokenchars '_-./'"` so that FTS5 does not split it back apart. See
TOKENIZE in index.py - the two must stay in sync or the column silently stops matching.

Usage as a script: prints extraction for a few probe strings (a self-test).
"""
import re

RE_PATTERNS = [
    re.compile(r"/[A-Za-z0-9_.\-/]{3,}"),                      # unix paths
    re.compile(r"--[A-Za-z0-9][A-Za-z0-9\-]+"),                # long flags
    re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+"),  # dotted paths / filenames
    re.compile(r"\bv?\d+\.\d+(?:\.\d+)*(?:-[A-Za-z0-9.]+)?\b"),   # versions
    re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b"),           # SCREAMING_SNAKE
    re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b"),           # snake_case
    re.compile(r"\b[A-Za-z]+(?:[A-Z][a-z0-9]+)+[A-Za-z0-9]*\b"),  # CamelCase
    re.compile(r"\b[A-Za-z]+[Vv]\d+\b"),                        # WidgetV2, staging-2 style
    re.compile(r"\b\d{2,}(?:_\d+)?\b"),                         # 0042, 0042_1, 137
    re.compile(r"\b[a-z]+-\d+\b"),                              # staging-2
]

SPLIT = re.compile(r"[^A-Za-z0-9]+")
CAMEL = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+")


def extract(text: str) -> list:
    """Return the extracted identifier tokens, whole forms first, then decomposed parts."""
    whole, parts = [], []
    for pat in RE_PATTERNS:
        for m in pat.finditer(text):
            tok = m.group(0)
            low = tok.lower()
            # Keep the identifier's punctuation. The FTS table declares tokenchars '_-./'
            # so unicode61 will not split this back into pieces. Deleting the punctuation
            # instead (the obvious first implementation) makes conf_test.py collide with
            # conftest.py, which defeats the entire purpose of this column.
            low = low.strip("-./")
            if len(low) >= 2:
                whole.append(low)
            for p in SPLIT.split(low):
                if p:
                    parts.append(p)
            for p in CAMEL.findall(tok):
                if len(p) > 1:
                    parts.append(p.lower())

    seen, out = set(), []
    # whole forms twice, so BM25 term frequency favours the exact identifier over its parts
    for t in whole:
        out.append(t)
    for t in whole:
        out.append(t)
    for t in parts:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def extract_str(text: str) -> str:
    return " ".join(extract(text))


if __name__ == "__main__":
    probes = [
        "WidgetV2 requires tenant_id and raises KeyError",
        "pin the pipeline library at v2.3.1 not v2.3.10",
        "AUTH_TOKEN_V2 must be set or the suite skips",
        "org.example.core.Config is loaded reflectively",
        "pass --no-cache-dir in the container install step",
        "reads them from /var/run/secrets/batch/creds.json",
        "Migration 0042_1 only adds an index",
        "conftest.py versus conf_test.py",
        "exited with code 137",
        "use staging-2 for destructive work",
    ]
    for p in probes:
        print(f"{p}\n  -> {extract_str(p)}\n")
