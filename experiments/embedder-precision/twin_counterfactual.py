#!/usr/bin/env python
"""Counterfactual identifier instrument - replaces the round-1 twin duel (review BLOCKER 3).

WHAT WAS WRONG WITH THE TWIN DUEL. It embedded a bare identifier and compared it against two
full, topically DIFFERENT memories. Passage topic, identifier frequency, document length and
asymmetric containment were all still available, so a win did not demonstrate sub-token identity.
It then counted each of 14 twin sets twice with reversed gold and treated the 28 outcomes as
independent Bernoulli trials against a 0.500 "chance" baseline.

WHAT THIS DOES INSTEAD.
  * **Byte-identical passage templates.** The two passages in a trial differ in exactly one
    substring: the identifier. Everything else - wording, length, position, frequency - is equal
    by construction. `verify_byte_identity()` proves it per trial rather than asserting it.
  * **Both directions, always.** Within a twin set every template is run with A as gold and with
    B as gold, so an identifier that is intrinsically more similar to arbitrary prose cannot
    produce a spurious directional effect.
  * **The twin set is the statistical block, n=14.** Per-set means first, then inference across
    the 14 blocks. The effective sample size is 14 and is stated wherever a number is quoted.
  * **The null is not a coin flip.** If a model is entirely blind to the identifier, the two
    passages embed IDENTICALLY and the margin is exactly 0 - not a 50/50 win rate. So the analysis
    is on the margin distribution, with a sign test over the 14 blocks. Win rate is reported for
    continuity with round 1 and is explicitly ill-conditioned near the null.

CONDITIONS (all on the same templates, so they are directly comparable).
  near_miss  the real twin identifiers. THE MEASUREMENT.
  exact      an unrelated, unmistakably distinct token pair per set. The instrument's CEILING:
             what separation looks like when the model definitely can tell the tokens apart.
  identity   the identifier masked to the SAME placeholder in both passages, so the passages are
             byte-identical. The instrument's FLOOR: margin must be 0.0000 or the harness is
             broken.

REPORTABLE QUANTITY, declared in PREREGISTRATION.md 5.5 before construction:
  discrimination index = mean near_miss margin / mean exact margin.
  ">= 0.75 usable, <= 0.35 a real weakness", and a between-model difference counts as a capacity
  effect only with a paired-by-block CI excluding 0 and a point difference >= 0.15.

TWO ESTIMANDS, disambiguated in PREREGISTRATION-R3.md R3.1 after review round-2 BLOCKER 1 caught
round 2 quoting one and testing the other:
  RoM  ratio of means = mean(near_miss margin) / mean(exact margin).  **PRIMARY** - this is what
       PREREGISTRATION 5.5 literally says. The between-model contrast is the difference of RoMs,
       with a paired cluster bootstrap that recomputes BOTH models' RoM inside each resample of
       the 14 twin sets (`paired_rom_bootstrap`).
  MBR  mean block ratio = mean over the 14 blocks of (block near_miss margin / block exact
       margin).  **SECONDARY**, reported because it is what round 2 quoted, and dropping it would
       hide the correction. Jensen's inequality guarantees RoM != MBR: they are different
       estimands and both are now named wherever either is used.

WHAT THIS INSTRUMENT CANNOT SAY (PREREGISTRATION-R3.md R3.2). fastembed serves a *quantized*
bge-small and an *unquantized* bge-large, so a between-model difference here is a difference
between two deployed artifacts, not a clean capacity control. Permitted wording is "this deployed
bge-large artifact did not materially improve the controlled identifier instrument". "Capacity does
not help" is not a supported claim.

Usage: .venv/bin/python twin_counterfactual.py
Out:   results/twin_counterfactual.json
"""
import json
import pathlib
import statistics
import sys

import numpy as np

import retrieval as R
from embcache import EmbedCache

HERE = pathlib.Path(__file__).parent
OUT = HERE / "results" / "twin_counterfactual.json"
SEED = 20260801
N_BOOT = 10000

# The 14 twin sets, from twin_duel.DISCRIMINATOR paired up. `nested` records whether one form
# contains the other, which round-1 finding 3 correctly identified as an uncontrolled asymmetry;
# here it is the only remaining difference, so it can be reported as its own subgroup.
TWIN_SETS = [
    ("widget",       "WidgetV1", "WidgetV2"),
    ("version",      "v2.3.1", "v2.3.10"),
    ("conftest",     "conftest.py", "conf_test.py"),
    ("authtoken",    "AUTH_TOKEN", "AUTH_TOKEN_V2"),
    ("gradle",       "build.gradle", "build.gradle.kts"),
    ("userid",       "user_id", "userId"),
    ("nocache",      "--no-cache", "--no-cache-dir"),
    ("staging",      "staging", "staging-2"),
    ("backoff",      "retry_backoff", "retry_backoff_ms"),
    ("parsedate",    "parse_date", "parse_datetime"),
    ("dotted",       "org.example.core.Config", "org.example.config.Core"),
    ("dburl",        "DATABASE_URL", "DATABASE_URL_RO"),
    ("timeout",      "30 seconds", "300 seconds"),
    ("migration",    "migration 0042", "migration 0042_1"),
]

# Unrelated, unmistakably distinct pairs - the ceiling control. One pair per set so the blocking
# structure of the control matches the measurement exactly.
EXACT_PAIRS = [
    ("KESTREL_MODE", "MARMOT_MODE"), ("v9.9.9", "v1.0.0"),
    ("alpha_probe.py", "zulu_engine.rb"), ("QUILL_SECRET", "TROMBONE_KEY"),
    ("pom.xml", "Makefile.am"), ("tenant_slug", "invoiceNumber"),
    ("--verbose", "--quiet"), ("canary", "obsidian"),
    ("cache_ttl", "socket_linger"), ("render_pdf", "compile_shader"),
    ("com.acme.billing.Ledger", "net.zeta.render.Pipeline"), ("SMTP_HOST", "REDIS_SENTINEL"),
    ("7 minutes", "45 hours"), ("migration 0900", "migration 0311"),
]

MASK = "PLACEHOLDER_TOKEN"

# Six neutral memory-voice templates. Each mentions {ID} twice. No topical content that could
# favour either member of any pair.
TEMPLATES = [
    "The team hit a problem with {ID} last quarter. Nobody wrote down why, so it was "
    "rediscovered the hard way. If you are touching {ID}, read the tracker notes first.",

    "Note on {ID}: the behaviour is not what the documentation implies. We spent an afternoon on "
    "it before working that out. Treat {ID} as load-bearing until proven otherwise.",

    "When the build failed the cause turned out to involve {ID}. The workaround is written down "
    "in the runbook. Do not change {ID} without telling whoever is on call.",

    "{ID} was introduced during the migration and never revisited. It works, but the reasoning "
    "is undocumented. Anyone changing {ID} should expect surprises.",

    "A previous attempt to simplify this removed {ID} and broke the nightly job. It was restored "
    "the next morning. Keep {ID} unless you have a replacement plan.",

    "For historical reasons {ID} is special-cased in two places. The second one is easy to miss. "
    "Grep for {ID} before assuming there is a single site.",
]

TAGS = ["bge-small", "bge-small-prefix", "bge-large-prefix", "nomic"]


def verify_byte_identity(pa: str, pb: str, a: str, b: str) -> bool:
    """The two passages must differ ONLY by A->B substitution."""
    return pa.replace(a, "\x00") == pb.replace(b, "\x00")


def build_trials(rng: np.random.Generator) -> list:
    """One trial = (block, condition, template_idx, query_text, gold_passage, foil_passage).

    Randomisation: template order is shuffled independently per block and per condition, and the
    direction order (which member is queried first) is shuffled too. Because every template is run
    in both directions within every block, the randomisation affects only presentation order, not
    the estimand - which is the point: the design is balanced by construction and the shuffle is
    there so no residual ordering artefact can creep in.
    """
    trials = []
    for bi, (block, a, b) in enumerate(TWIN_SETS):
        ea, eb = EXACT_PAIRS[bi]
        conds = {
            "near_miss": (a, b),
            "exact": (ea, eb),
            "identity": (MASK, MASK),
        }
        for cond, (ia, ib) in conds.items():
            order = list(range(len(TEMPLATES)))
            rng.shuffle(order)
            for ti in order:
                T = TEMPLATES[ti]
                pa, pb = T.format(ID=ia), T.format(ID=ib)
                if cond != "identity" and not verify_byte_identity(pa, pb, ia, ib):
                    raise AssertionError(f"template {ti} not byte-identical for {ia}/{ib}")
                if cond == "identity" and pa != pb:
                    raise AssertionError("identity control passages differ")
                dirs = [(ia, pa, pb, "A"), (ib, pb, pa, "B")]
                if rng.random() < 0.5:
                    dirs.reverse()
                for tok, gold, foil, side in dirs:
                    trials.append(dict(block=block, block_idx=bi, cond=cond, template=ti,
                                       side=side, token=tok, gold=gold, foil=foil,
                                       nested=(a in b or b in a) if cond == "near_miss" else None))
    return trials


def block_bootstrap(per_block: dict, n=N_BOOT, seed=SEED) -> dict:
    """Cluster bootstrap over the 14 twin sets. per_block: block -> value."""
    keys = sorted(per_block)
    vals = np.array([per_block[k] for k in keys], dtype=float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(vals), size=(n, len(vals)))
    means = vals[idx].mean(1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return dict(n_blocks=len(vals), point=round(float(vals.mean()), 4),
                ci95=[round(float(lo), 4), round(float(hi), 4)],
                blocks_positive=int((vals > 0).sum()), blocks_zero=int((vals == 0).sum()),
                blocks_negative=int((vals < 0).sum()))


def paired_block_bootstrap(a: dict, b: dict, n=N_BOOT, seed=SEED) -> dict:
    keys = sorted(set(a) & set(b))
    va = np.array([a[k] for k in keys], dtype=float)
    vb = np.array([b[k] for k in keys], dtype=float)
    d = va - vb
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(d), size=(n, len(d)))
    means = d[idx].mean(1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return dict(n_blocks=len(d), point=round(float(d.mean()), 4),
                ci95=[round(float(lo), 4), round(float(hi), 4)],
                excludes_zero=bool(lo > 0 or hi < 0),
                blocks_favouring_a=int((d > 0).sum()), blocks_tied=int((d == 0).sum()),
                blocks_favouring_b=int((d < 0).sum()))


def _rom(nm: np.ndarray, ex: np.ndarray) -> float:
    """Ratio of means. Equals mean(nm trials)/mean(ex trials) because every block contributes the
    same number of trials (6 templates x 2 directions) in every condition."""
    return float(nm.sum() / ex.sum())


def rom_bootstrap(nm_blocks: dict, ex_blocks: dict, n=N_BOOT, seed=SEED) -> dict:
    """Cluster bootstrap of ONE model's discrimination index under the ratio-of-means estimand.

    Resample twin sets with replacement and recompute the ratio inside each resample, so the
    interval propagates uncertainty in the denominator (the exact-control margin) as well as the
    numerator. A ratio estimator's bootstrap distribution is not symmetric; the point estimate is
    the full-sample ratio, not the bootstrap mean.
    """
    keys = sorted(set(nm_blocks) & set(ex_blocks))
    nm = np.array([nm_blocks[k] for k in keys], dtype=float)
    ex = np.array([ex_blocks[k] for k in keys], dtype=float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(keys), size=(n, len(keys)))
    vals = nm[idx].sum(1) / ex[idx].sum(1)
    lo, hi = np.percentile(vals, [2.5, 97.5])
    return dict(estimand="ratio_of_means", n_blocks=len(keys),
                point=round(_rom(nm, ex), 4),
                ci95=[round(float(lo), 4), round(float(hi), 4)],
                boot_mean=round(float(vals.mean()), 4))


def paired_rom_bootstrap(nm_a: dict, ex_a: dict, nm_b: dict, ex_b: dict,
                         n=N_BOOT, seed=SEED) -> dict:
    """Paired cluster bootstrap of RoM(A) - RoM(B), the PREREGISTERED estimand (R3.1).

    The SAME resample of twin sets is applied to both models, and each model's ratio of means is
    recomputed inside the resample. This is what PREREGISTRATION 5.5's "mean near-miss margin /
    mean exact-control margin" difference actually requires; round 2 bootstrapped the mean of
    per-block ratios instead, which is a different estimand.
    """
    keys = sorted(set(nm_a) & set(ex_a) & set(nm_b) & set(ex_b))
    na = np.array([nm_a[k] for k in keys], dtype=float)
    ea = np.array([ex_a[k] for k in keys], dtype=float)
    nb = np.array([nm_b[k] for k in keys], dtype=float)
    eb = np.array([ex_b[k] for k in keys], dtype=float)
    point = _rom(na, ea) - _rom(nb, eb)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(keys), size=(n, len(keys)))
    d = (na[idx].sum(1) / ea[idx].sum(1)) - (nb[idx].sum(1) / eb[idx].sum(1))
    lo, hi = np.percentile(d, [2.5, 97.5])
    # per-block direction counts use the per-block ratios, which is the only way to say
    # "k of 14 blocks favoured A" for a ratio estimand at all.
    ra = na / ea
    rb = nb / eb
    diff = ra - rb
    return dict(estimand="difference_of_ratio_of_means", n_blocks=len(keys),
                point=round(float(point), 4),
                ci95=[round(float(lo), 4), round(float(hi), 4)],
                excludes_zero=bool(lo > 0 or hi < 0),
                boot_mean=round(float(d.mean()), 4),
                blocks_favouring_a=int((diff > 0).sum()),
                blocks_favouring_b=int((diff < 0).sum()),
                meets_prereg_capacity_bar=bool((lo > 0 or hi < 0) and abs(point) >= 0.15))


def main() -> int:
    rng = np.random.default_rng(SEED)
    trials = build_trials(rng)
    print(f"{len(trials)} trials: {len(TWIN_SETS)} blocks x 3 conditions x "
          f"{len(TEMPLATES)} templates x 2 directions", flush=True)

    from fastembed import TextEmbedding
    out = dict(seed=SEED, n_blocks=len(TWIN_SETS), n_templates=len(TEMPLATES),
               n_trials=len(trials), templates=TEMPLATES, twin_sets=TWIN_SETS,
               exact_pairs=EXACT_PAIRS, models={})

    for tag in TAGS:
        model, qpre, ppre = R.MODELS[tag]
        cache = EmbedCache(model, TextEmbedding(model_name=model))

        for probe in ("bare", "carrier"):
            qtexts, ptexts = [], []
            for t in trials:
                q = t["token"] if probe == "bare" else f"Tell me about {t['token']}."
                qtexts.append(qpre + q)
                ptexts.append(ppre + t["gold"])
                ptexts.append(ppre + t["foil"])
            qv = cache.embed(qtexts)
            pv = cache.embed(ptexts)

            rows = []
            for i, t in enumerate(trials):
                g, f = pv[2 * i], pv[2 * i + 1]
                sg, sf = float(qv[i] @ g), float(qv[i] @ f)
                rows.append(dict(t, cos_gold=round(sg, 6), cos_foil=round(sf, 6),
                                 margin=sg - sf, win=sg > sf))

            res = {}
            for cond in ("near_miss", "exact", "identity"):
                sel = [r for r in rows if r["cond"] == cond]
                per_block_margin = {}
                per_block_win = {}
                for b in {r["block"] for r in sel}:
                    bs = [r for r in sel if r["block"] == b]
                    per_block_margin[b] = statistics.mean(r["margin"] for r in bs)
                    per_block_win[b] = statistics.mean(float(r["win"]) for r in bs)
                res[cond] = dict(
                    n_trials=len(sel),
                    margin=block_bootstrap(per_block_margin),
                    abs_margin_mean=round(statistics.mean(abs(r["margin"]) for r in sel), 6),
                    win_rate_blockmean=block_bootstrap(per_block_win),
                    win_rate_trials=round(statistics.mean(float(r["win"]) for r in sel), 4),
                    mean_cos_gold=round(statistics.mean(r["cos_gold"] for r in sel), 4),
                    per_block_margin={k: round(v, 6) for k, v in sorted(per_block_margin.items())},
                    per_block_win={k: round(v, 4) for k, v in sorted(per_block_win.items())},
                )

            nm = res["near_miss"]["margin"]["point"]
            ex = res["exact"]["margin"]["point"]
            nmb = res["near_miss"]["per_block_margin"]
            exb = res["exact"]["per_block_margin"]
            # equal trial counts per block per condition is what makes RoM == trial-level ratio
            assert res["near_miss"]["n_trials"] == res["exact"]["n_trials"], "unbalanced blocks"
            di_blocks = {}
            for b in nmb:
                di_blocks[b] = (nmb[b] / exb[b]) if exb.get(b) else float("nan")
            di_clean = {k: v for k, v in di_blocks.items() if v == v}
            rom = rom_bootstrap(nmb, exb)
            res["discrimination_index"] = dict(
                primary_estimand="ratio_of_means",
                note=("RoM and MBR are different estimands (R3.1). RoM is what PREREGISTRATION 5.5 "
                      "declared; MBR is what round 2 quoted for between-model contrasts."),
                # --- PRIMARY: ratio of means, with its own cluster bootstrap
                ratio_of_means=rom,
                # --- SECONDARY: mean of per-block ratios
                mean_block_ratio=dict(estimand="mean_of_per_block_ratios",
                                      **block_bootstrap(di_clean)) if di_clean else None,
                per_block_values={k: round(v, 4) for k, v in sorted(di_clean.items())},
                # one number, not two: `aggregate` IS the ratio of means, computed from the same
                # unrounded per-block margins as the bootstrap, so the report cannot quote a
                # rounding artefact as a second estimate.
                aggregate=rom["point"],
                aggregate_definition="ratio_of_means (identical to ratio_of_means.point)",
            )
            nested = {r["block"]: None for r in rows if r["cond"] == "near_miss" and r["nested"]}
            res["nested_blocks"] = sorted(nested)
            for grp, want in (("nested", True), ("disjoint", False)):
                sel = [r for r in rows if r["cond"] == "near_miss" and bool(r["nested"]) == want]
                if sel:
                    pb = {}
                    for b in {r["block"] for r in sel}:
                        pb[b] = statistics.mean(r["margin"] for r in [x for x in sel
                                                                     if x["block"] == b])
                    res[f"near_miss_{grp}"] = block_bootstrap(pb)

            out["models"].setdefault(tag, dict(model=model))[probe] = res
            print(f"{tag:18} {probe:8} near_miss margin={nm:+.4f} exact={ex:+.4f} "
                  f"identity={res['identity']['margin']['point']:+.4f} "
                  f"DI={res['discrimination_index']['aggregate']} "
                  f"win(nm)={res['near_miss']['win_rate_trials']:.3f}", flush=True)
        cache.flush()

    # ---- paired between-model comparison, blocked by twin set.
    # BOTH estimands are computed and labelled (R3.1). The preregistered gate in section 5.5 is
    # applied to the PRIMARY (difference of ratio-of-means).
    cmp_out = {}
    for probe in ("bare", "carrier"):
        bmod = out["models"]["bge-small-prefix"][probe]
        b_nm = bmod["near_miss"]["per_block_margin"]
        b_ex = bmod["exact"]["per_block_margin"]
        b_mbr = bmod["discrimination_index"]["per_block_values"]
        for tag in ("bge-large-prefix", "nomic"):
            omod = out["models"][tag][probe]
            o_nm = omod["near_miss"]["per_block_margin"]
            o_ex = omod["exact"]["per_block_margin"]
            o_mbr = omod["discrimination_index"]["per_block_values"]
            key = f"{probe}|{tag}_vs_bge-small-prefix"
            # PRIMARY: difference of ratio-of-means, bootstrap recomputing both ratios per resample
            cmp_out[key + "|DI_rom"] = paired_rom_bootstrap(o_nm, o_ex, b_nm, b_ex)
            # SECONDARY: difference of mean-per-block-ratios (what round 2 reported as "DI")
            cmp_out[key + "|DI_mbr"] = dict(estimand="difference_of_mean_block_ratios",
                                            **paired_block_bootstrap(o_mbr, b_mbr))
            # raw near-miss margin difference, unnormalised
            cmp_out[f"{probe}|margin|{tag}_vs_bge-small-prefix"] = dict(
                estimand="difference_of_mean_near_miss_margins",
                **paired_block_bootstrap(o_nm, b_nm))
    out["model_comparisons"] = cmp_out
    out["estimand_note"] = (
        "DI_rom is the preregistered estimand (PREREGISTRATION 5.5, pinned down in "
        "PREREGISTRATION-R3.md R3.1): difference of (mean near-miss margin / mean exact margin). "
        "DI_mbr is the difference of per-block ratio means, which is what round 2 quoted as "
        "'+0.0181'. They are not the same quantity and neither is a substitute for the other.")

    # ---- instrument validation against the predeclared criteria
    val = {}
    for tag in TAGS:
        for probe in ("bare", "carrier"):
            r = out["models"][tag][probe]
            val[f"{tag}|{probe}"] = dict(
                identity_margin_is_zero=abs(r["identity"]["margin"]["point"]) < 1e-4,
                identity_margin=r["identity"]["margin"]["point"],
                exact_win_rate=r["exact"]["win_rate_trials"],
                exact_win_ge_090=r["exact"]["win_rate_trials"] >= 0.90,
                exact_margin_gt_near_miss=(r["exact"]["margin"]["point"]
                                           > r["near_miss"]["margin"]["point"]),
            )
    out["instrument_validation"] = val

    OUT.write_text(json.dumps(out, indent=2) + "\n")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
