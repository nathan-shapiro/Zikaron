#!/usr/bin/env python
"""Held-out evaluation of the FROZEN identifier extractor (review BLOCKER 6).

WHY THIS EXISTS. `identifiers.py` was developed against the very traps it was then scored on -
including a fix for the `conftest.py`/`conf_test.py` collision its first version created. That
makes the round-1 dataset a development set for the extractor. This file is the held-out test.

DISCIPLINE, STATED HONESTLY. I have read `identifiers.py`, so this material is not authored in
ignorance of the implementation. Two things limit the damage:
  * the material CLASSES were specified by the reviewer, not chosen by me: URLs, Windows paths,
    scoped npm packages, git hashes, mixed-language identifiers, prose containing numbers,
    punctuation-heavy shell commands;
  * `identifiers.py` is FROZEN at the sha256 recorded in PREREGISTRATION.md section 8 and is NOT
    edited in response to anything below. `verify_freeze.py` enforces that.
The labels below were written before the extractor was run on them, and are not revised
afterwards. Any label correction that proves necessary is disclosed in the report as a deviation.

RUBRIC, committed in advance.
  expect     whole forms that MUST be extracted. Recall denominator. The bar is "a token a user
             would plausibly type verbatim to find this memory".
  ok_extra   whole forms that are acceptable if emitted - genuinely useful, neither required nor
             penalised.
  Anything else emitted as a WHOLE form is a FALSE POSITIVE.

Whole forms only. The extractor also emits decomposed parts (WidgetV2 -> widget, v2) which are a
deliberate BM25 recall device, not identifier claims, so they are counted separately as index
noise rather than as precision errors. Both numbers are reported.

Also measured, because round 1's real failure was of this shape:
  COLLISIONS - held-out near-miss pairs that must not map to the same whole-form set.
  PROSE FALSE POSITIVES - ordinary English with no identifiers at all.

Usage: .venv/bin/python extractor_heldout.py [--json]
Out:   results/extractor_heldout.json
"""
import argparse
import hashlib
import json
import pathlib
import sys

import identifiers

HERE = pathlib.Path(__file__).parent
OUT = HERE / "results" / "extractor_heldout.json"
FROZEN_SHA = "836dbd85ab63ea578eeacd1c0eb2ab9a6205aaf2769258157880dedd76b5b35f"

# --------------------------------------------------------------------------- held-out material
# (class, text, expect, ok_extra)
CASES = [
    # ---- URLs (7)
    ("url", "the fix is documented at https://github.com/qdrant/fastembed/issues/412",
     ["github.com"], ["fastembed", "qdrant", "issues", "412"]),
    ("url", "pull the wheel from https://pypi.org/project/sqlite-vec/0.1.9/",
     ["sqlite-vec"], ["pypi.org", "0.1.9"]),
    ("url", "our staging host is https://api-staging.internal.example.net:8443/v2/health",
     ["api-staging.internal.example.net"], ["v2", "8443", "health"]),
    ("url", "see http://localhost:5173/#/settings/tokens for the dev console",
     [], ["localhost", "5173", "settings", "tokens"]),
    ("url", "the raw file lives at https://raw.githubusercontent.com/org/repo/main/conf/app.yaml",
     ["app.yaml"], ["raw.githubusercontent.com", "conf", "main"]),
    ("url", "webhook target is https://hooks.example.com/services/T024/B01/XyZ9",
     ["hooks.example.com"], ["services", "t024", "b01"]),
    ("url", "docs moved to https://docs.example.io/guides/retry-policy#exponential-backoff",
     ["docs.example.io"], ["retry-policy", "guides"]),

    # ---- Windows paths (6)
    ("winpath", r"the agent writes to C:\Users\nathan\AppData\Local\Zikaron\store.db",
     ["store.db"], ["appdata", "zikaron", "users"]),
    ("winpath", r"copy the cert into C:\ProgramData\ssl\ca-bundle.crt first",
     ["ca-bundle.crt"], ["programdata"]),
    ("winpath", r"set PYTHONPATH=D:\build\out;D:\build\vendor before running",
     ["PYTHONPATH"], ["build", "vendor"]),
    ("winpath", r"it fails if the repo sits under \\fileserver\shared\team-docs",
     [], ["fileserver", "team-docs", "shared"]),
    ("winpath", r"the hook script is .kiro\hooks\user_prompt_submit.ps1",
     ["user_prompt_submit.ps1"], ["hooks", "kiro"]),
    ("winpath", r"MSBuild reads Directory.Build.props from the solution root",
     ["Directory.Build.props"], ["msbuild"]),

    # ---- scoped npm packages (6)
    ("npm", "install @aws-sdk/client-s3 rather than the v2 aws-sdk monolith",
     ["@aws-sdk/client-s3", "aws-sdk"], ["v2", "client-s3"]),
    ("npm", "pin @types/node at 20.11.5 or the build breaks",
     ["@types/node", "20.11.5"], ["types", "node"]),
    ("npm", "we vendored @internal/ui-kit because the registry proxy drops scoped tarballs",
     ["@internal/ui-kit"], ["ui-kit"]),
    ("npm", "run npx @modelcontextprotocol/inspector against the local server",
     ["@modelcontextprotocol/inspector"], ["npx", "inspector"]),
    ("npm", "eslint-plugin-import and @typescript-eslint/parser disagree on resolver order",
     ["eslint-plugin-import", "@typescript-eslint/parser"], ["parser"]),
    ("npm", "the workspace protocol dependency workspace:^ is not understood by npm 9",
     [], ["workspace"]),

    # ---- git hashes / refs (6)
    ("githash", "the regression landed in 4f9a2c1 and was reverted in 9b1e77d",
     ["4f9a2c1", "9b1e77d"], []),
    ("githash", "bisect blames commit e3b0c44298fc1c149afbf4c8996fb92427ae41e4",
     ["e3b0c44298fc1c149afbf4c8996fb92427ae41e4"], []),
    ("githash", "cherry-pick 1a2b3c4d from release/2.7 into main",
     ["1a2b3c4d", "release/2.7"], ["release", "cherry-pick"]),
    ("githash", "tag v0.4.0-rc2 points at a tree that no longer builds",
     ["v0.4.0-rc2"], []),
    ("githash", "the submodule is stuck at deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
     ["deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"], []),
    ("githash", "git diff HEAD~3..HEAD shows only whitespace",
     ["HEAD~3"], ["head"]),

    # ---- mixed-language identifiers (6)
    ("mixed", "the field is called ユーザーID and the getter is getユーザーID",
     [], []),
    ("mixed", "German column names like Größe_maximal survive the ORM but not the CSV export",
     ["Größe_maximal"], []),
    ("mixed", "benutzerId maps to user_id in the legacy adapter",
     ["benutzerId", "user_id"], ["benutzer"]),
    ("mixed", "the label key is app.kubernetes.io/名前 which fails validation",
     ["app.kubernetes.io"], ["kubernetes"]),
    ("mixed", "we normalise café_name to cafe_name before indexing",
     ["cafe_name"], ["café_name"]),
    ("mixed", "Ünicode identifiers in the Türkçe locale break the lowercase round-trip",
     [], ["locale"]),

    # ---- prose containing numbers (7) - the false-positive stress class
    ("prose_num", "we saw about 30 failures in the last 200 runs, mostly on Fridays",
     [], []),
    ("prose_num", "it took roughly 15 minutes and nobody noticed for 3 days",
     [], []),
    ("prose_num", "the team of 12 reviewed 47 pull requests that quarter",
     [], []),
    ("prose_num", "there were 1000 rows before the cleanup and 998 after",
     [], []),
    ("prose_num", "this has bitten us at least 4 times since 2024",
     [], ["2024"]),
    ("prose_num", "budget is 90 percent spent and the deadline moved twice",
     [], []),
    ("prose_num", "roughly 60 to 70 of the cases are duplicates",
     [], []),

    # ---- punctuation-heavy shell commands (7)
    ("shell", "run: docker run --rm -v $(pwd):/w -w /w node:20 npm ci --omit=dev",
     ["--rm", "--omit", "npm"], ["pwd", "node", "20"]),
    ("shell", "kubectl get pods -n prod -o jsonpath='{.items[*].metadata.name}'",
     ["kubectl", "jsonpath"], ["items", "metadata.name", "prod"]),
    ("shell", "awk -F'\\t' '{print $2}' out.tsv | sort -u | head -n 20",
     ["out.tsv"], ["awk", "sort", "head"]),
    ("shell", "psql -c \"select * from mem where uuid='x' ;\" -h db.internal -p 5432",
     ["db.internal"], ["psql", "5432", "mem"]),
    ("shell", "export PIP_NO_CACHE_DIR=1 && pip install -e '.[dev,test]' --no-build-isolation",
     ["PIP_NO_CACHE_DIR", "--no-build-isolation"], ["pip"]),
    ("shell", "find . -name '*.pyc' -delete 2>/dev/null || true",
     [], ["pyc"]),
    ("shell", "curl -sSf -H 'X-Api-Key: $KEY' https://api.example.com/v1/ping | jq -r .status",
     ["X-Api-Key", "api.example.com"], ["jq", "curl", "v1", "status"]),

    # ---- ordinary prose, zero identifiers (7) - pure false-positive probe
    ("prose_plain", "the previous attempt failed because nobody wrote down why it was abandoned",
     [], []),
    ("prose_plain", "we agreed to revisit this once the migration settles down",
     [], []),
    ("prose_plain", "the integration suite is flaky in a way that wastes an afternoon each time",
     [], []),
    ("prose_plain", "do not trust the cached result after a schema change",
     [], []),
    ("prose_plain", "this was a deliberate decision, not an oversight",
     [], []),
    ("prose_plain", "reading the source is faster than asking, most of the time",
     [], []),
    ("prose_plain", "the fix is obvious in hindsight and was not obvious at all beforehand",
     [], []),
]

# Held-out near-miss pairs. Must not collapse to the same whole-form set.
# None of these appear anywhere in dataset.json.
COLLISION_PAIRS = [
    ("setup.cfg", "setup_cfg.py"),
    ("@types/node", "@types/nodemailer"),
    ("v1.10.0", "v1.1.0"),
    ("MAX_RETRIES", "MAX_RETRIES_TOTAL"),
    ("get_user", "get_users"),
    ("PayloadV10", "PayloadV1"),
    ("--dry-run", "--dry-run-only"),
    ("release/2.7", "release/2.70"),
    ("app.kubernetes.io", "app-kubernetes.io"),
    ("0042_add_index", "0042_add_indexes"),
    ("Directory.Build.props", "Directory.Build.targets"),
    ("client-s3", "client-sts"),
]


def whole_forms(text: str) -> list:
    """The whole (non-decomposed) forms the frozen extractor emits, deduped, order preserved.

    identifiers.extract emits every whole form twice at the front, then the deduped parts. The
    whole-form multiset is therefore the first 2*W entries; W is recovered by halving.
    """
    toks = identifiers.extract(text)
    # find the boundary: whole forms appear as a doubled prefix list
    for w in range(len(toks) // 2, -1, -1):
        if toks[:w] == toks[w:2 * w]:
            return list(dict.fromkeys(toks[:w]))
    return []


def part_forms(text: str) -> list:
    toks = identifiers.extract(text)
    for w in range(len(toks) // 2, -1, -1):
        if toks[:w] == toks[w:2 * w]:
            return toks[2 * w:]
    return toks


def posthoc_sensitivity() -> dict:
    """POST-HOC, labelled as such. Not part of the predeclared gate.

    Some labels above expect the flag's leading dashes (`--rm`) or the npm scope (`@types/node`).
    The extractor strips leading `-./` - and so does `retrieval._fts_query` on the QUERY side, so
    the pair is internally consistent and a `--rm` query would still match an `rm` index token.
    Penalising that as a miss overstates the failure. This recomputes recall and precision under
    a normalisation that strips leading/trailing `-./@` from both sides.

    It is reported ALONGSIDE, never INSTEAD OF, the predeclared numbers. It does not change any
    gate outcome and is not used to argue one was passed.
    """
    def nrm(s):
        return s.lower().strip("-./@")

    exp_tot = tp_tot = fp_tot = ok_tot = 0
    for _cls, text, expect, ok_extra in CASES:
        got = {nrm(g) for g in whole_forms(text)}
        exp = {nrm(e) for e in expect}
        okx = {nrm(e) for e in ok_extra}
        exp_tot += len(exp)
        tp_tot += len(exp & got)
        ok_tot += len(got & okx)
        fp_tot += len(got - exp - okx)
    return dict(
        note="POST-HOC sensitivity, not a predeclared metric",
        normalisation="strip leading/trailing -./@ from both expected and extracted",
        recall=round(tp_tot / exp_tot, 4) if exp_tot else None,
        precision_lenient=round((tp_tot + ok_tot) / (tp_tot + ok_tot + fp_tot), 4)
        if (tp_tot + ok_tot + fp_tot) else None,
        precision_strict=round(tp_tot / (tp_tot + fp_tot), 4) if (tp_tot + fp_tot) else None,
        false_positives=fp_tot)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    sha = hashlib.sha256((HERE / "identifiers.py").read_bytes()).hexdigest()
    frozen_ok = sha == FROZEN_SHA

    per_class, cases_out = {}, []
    for cls, text, expect, ok_extra in CASES:
        got = whole_forms(text)
        gotset = set(got)
        exp = {e.lower() for e in expect}
        okx = {e.lower() for e in ok_extra}
        tp = sorted(exp & gotset)
        missed = sorted(exp - gotset)
        fp = sorted(gotset - exp - okx)
        acc = sorted(gotset & okx)
        d = per_class.setdefault(cls, dict(n=0, expected=0, found=0, fp=0, ok_extra=0,
                                           parts=0, cases_with_fp=0, fp_examples=[]))
        d["n"] += 1
        d["expected"] += len(exp)
        d["found"] += len(tp)
        d["fp"] += len(fp)
        d["ok_extra"] += len(acc)
        d["parts"] += len(part_forms(text))
        if fp:
            d["cases_with_fp"] += 1
            d["fp_examples"] = (d["fp_examples"] + fp)[:8]
        cases_out.append(dict(cls=cls, text=text, expected=sorted(exp), got=got,
                              true_positive=tp, missed=missed, false_positive=fp,
                              accepted_extra=acc))

    tot_exp = sum(d["expected"] for d in per_class.values())
    tot_tp = sum(d["found"] for d in per_class.values())
    tot_fp = sum(d["fp"] for d in per_class.values())
    tot_ok = sum(d["ok_extra"] for d in per_class.values())
    recall = tot_tp / tot_exp if tot_exp else None
    # precision counts required + accepted as correct; everything else emitted is wrong
    precision = (tot_tp + tot_ok) / (tot_tp + tot_ok + tot_fp) if (tot_tp + tot_ok + tot_fp) else None
    strict_precision = tot_tp / (tot_tp + tot_fp) if (tot_tp + tot_fp) else None

    collisions = []
    for a, b in COLLISION_PAIRS:
        wa, wb = set(whole_forms(a)), set(whole_forms(b))
        collisions.append(dict(a=a, b=b, whole_a=sorted(wa), whole_b=sorted(wb),
                              distinct=bool(wa != wb),
                              a_empty=not wa, b_empty=not wb))
    n_collide = sum(1 for c in collisions if not c["distinct"])

    plain = per_class.get("prose_plain", {})
    pnum = per_class.get("prose_num", {})
    out = dict(
        frozen_sha256=sha, frozen_matches_preregistration=frozen_ok,
        n_cases=len(CASES), n_classes=len(per_class),
        summary=dict(
            expected_tokens=tot_exp, extracted_expected=tot_tp,
            recall=round(recall, 4) if recall is not None else None,
            precision_lenient=round(precision, 4) if precision is not None else None,
            precision_strict=round(strict_precision, 4) if strict_precision else None,
            false_positives=tot_fp, accepted_extra=tot_ok,
            prose_plain_cases_with_fp=f"{plain.get('cases_with_fp')}/{plain.get('n')}",
            prose_num_cases_with_fp=f"{pnum.get('cases_with_fp')}/{pnum.get('n')}",
            collision_pairs=len(COLLISION_PAIRS), collisions=n_collide,
            collision_pairs_with_an_empty_side=sum(
                1 for c in collisions if c["a_empty"] or c["b_empty"]),
        ),
        per_class={k: dict(v, recall=round(v["found"] / v["expected"], 4) if v["expected"] else None,
                           fp_per_case=round(v["fp"] / v["n"], 2),
                           parts_per_case=round(v["parts"] / v["n"], 1))
                   for k, v in per_class.items()},
        collisions=collisions, cases=cases_out,
        posthoc_sensitivity=posthoc_sensitivity(),
    )
    OUT.write_text(json.dumps(out, indent=2) + "\n")

    if args.json:
        print(json.dumps(out["summary"], indent=2))
    else:
        s = out["summary"]
        print(f"frozen sha matches preregistration: {frozen_ok}")
        print(f"recall {s['recall']}  precision(lenient) {s['precision_lenient']}  "
              f"precision(strict) {s['precision_strict']}  FP {s['false_positives']}")
        print(f"plain prose cases emitting a false positive: {s['prose_plain_cases_with_fp']}")
        print(f"numeric prose cases emitting a false positive: {s['prose_num_cases_with_fp']}")
        print(f"held-out collisions: {n_collide}/{len(COLLISION_PAIRS)}  "
              f"(pairs with an empty side: {s['collision_pairs_with_an_empty_side']})")
        print()
        for k, v in sorted(out["per_class"].items()):
            print(f"  {k:12} n={v['n']:2} recall={v['recall']} fp/case={v['fp_per_case']:.2f} "
                  f"parts/case={v['parts_per_case']:.1f} fp={v['fp_examples'][:4]}")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
