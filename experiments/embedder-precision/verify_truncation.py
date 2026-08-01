#!/usr/bin/env python
"""Verify the over-length trap actually fires: does the load-bearing punchline fall past the
512-token cap of bge-small's WordPiece tokenizer? If not, category 5 tests nothing.

Usage: .venv/bin/python verify_truncation.py   ->  results/truncation_check.json
"""
import json, pathlib
from tokenizers import Tokenizer
from huggingface_hub import hf_hub_download
import retrieval as R

tk = Tokenizer.from_file(hf_hub_download("BAAI/bge-small-en-v1.5", "tokenizer.json"))
doc = R.load_dataset()
out = []
for m in doc["memories"]:
    text = m["gist"] + "\n" + m["content"]
    n = len(tk.encode(text).ids)
    rec = dict(key=m["key"], cat=m["cat"], n_tokens=n, over_512=n > 512)
    if m["cat"] == "over_length":
        # where does the punchline start? last 25% of the content is the punchline block
        head = m["gist"] + "\n" + m["content"][: m["content"].rfind("The ")]
        rec["tokens_before_punchline"] = len(tk.encode(head).ids)
        rec["punchline_visible_at_512"] = rec["tokens_before_punchline"] < 512
    out.append(rec)

ol = [r for r in out if r["cat"] == "over_length"]
print(f"{'key':24} {'tokens':>7} {'>512':>5} {'pre-punchline':>14} {'visible':>8}")
for r in ol:
    print(f"{r['key']:24} {r['n_tokens']:>7} {str(r['over_512']):>5} "
          f"{r['tokens_before_punchline']:>14} {str(r['punchline_visible_at_512']):>8}")
allm = [r["n_tokens"] for r in out]
nonol = [r["n_tokens"] for r in out if r["cat"] != "over_length"]
print(f"\ncorpus gist+content tokens: max={max(allm)} mean={sum(allm)//len(allm)}")
print(f"non-over-length only:       max={max(nonol)} mean={sum(nonol)//len(nonol)}")
print(f"memories over 512 tokens:   {sum(r['over_512'] for r in out)} / {len(out)}")
pathlib.Path("results/truncation_check.json").write_text(json.dumps(out, indent=2)+"\n")
