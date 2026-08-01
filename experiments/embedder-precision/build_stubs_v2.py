#!/usr/bin/env python3
"""Build stubs_v2.json: a prose-free authoring specification, one stub per v1 query.

Why this file exists
--------------------
`reviews/embedder-benchmark-independent.md` finding 1 is a BLOCKER: the v1 dataset is
self-authored, so query wording was chosen while holding the target memory text in
mind. Every number is inflated by that and no amount of care fixes it.

The cheap half of the fix is a fresh query set authored against the *existing* memory
corpus by someone who has never read the memory prose. This file is the bridge: it
specifies, per situation, only what a real user would plausibly have in hand -- the
literal identifiers, and a <=15-word description of their circumstance -- plus the
grading needed to score whatever queries the next stage writes.

Two review findings are folded in:
  * finding 11 -- one-gold labelling is incomplete, and some records labelled "hard
    negative" are in fact equally useful. `relevant_memory_uuids` is graded, may hold
    several `primary` entries where two records genuinely co-answer, and
    `confusable_uuids` is reserved for records whose application would misdirect.
  * finding 12 -- four of the ten polarity queries are historical-intent and were
    scored with inverted semantics. Every stub is classified on that axis.

Keys, not uuids, are written below for reviewability; uuids are resolved from
dataset.json at build time. The emitted file carries uuids ONLY, because the authoring
keys (`c2-cert-chain`, `c3-ssl-verify`, ...) themselves leak topic.
"""

from __future__ import annotations

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
DATASET = HERE / "dataset.json"
OUT = HERE / "stubs_v2.json"

P = "primary"
A = "also_useful"
H = "harmful_if_applied"

C5_ALL = [
    "c5-merge-precedence",
    "c5-late-index-hint",
    "c5-late-cred-path",
    "c5-late-retry-budget",
    "c5-late-cache-key",
    "c5-late-clock-skew",
]


def c5_siblings(own: str) -> list[str]:
    """The other five over-length records: near-identical 600+ token bodies, different
    operative tails. Genuine retrieval twins whose tails prescribe unrelated fixes."""
    return [k for k in C5_ALL if k != own]


# stub_id, trap_category, intent, identifiers, situation, [(key, grade)], [confusable keys]
STUBS: list[tuple] = [
    # ---------------------------------------------------------------- near_miss
    (
        "q-c1-01", "near_miss", "current_action", ["WidgetV1"],
        "Adding a warmer path that round-trips objects through our cache.",
        [("c1-widgetv1", P), ("c1-widgetv2", H), ("d-cache-stampede", A)],
        ["c1-widgetv2"],
    ),
    (
        "q-c1-02", "near_miss", "current_action", ["WidgetV2"],
        "Converting our legacy dictionary payloads into the replacement type.",
        [("c1-widgetv2", P), ("c1-widgetv1", A)],
        [],
    ),
    (
        "q-c1-03", "near_miss", "current_action", ["v2.3.1"],
        "Getting our on-prem runner back to green before the release.",
        [("c1-ver-2-3-1", P), ("c3-symbol-lookup", A), ("c1-ver-2-3-10", H)],
        ["c1-ver-2-3-10"],
    ),
    (
        "q-c1-04", "near_miss", "current_action", ["v2.3.10"],
        "Uploads intermittently fail since last week's library bump.",
        [("c1-ver-2-3-10", P), ("d-ver-2-4-0", A), ("c3-conn-reset", A), ("c1-ver-2-3-1", H)],
        ["c1-ver-2-3-1"],
    ),
    (
        "q-c1-05", "near_miss", "current_action", ["conftest.py"],
        "Want a single shared fixture usable by both of our suites.",
        [("c1-conftest", P), ("d-test-freeze-time", A), ("c1-conf-test", H)],
        ["c1-conf-test"],
    ),
    (
        "q-c1-06", "near_miss", "current_action", ["conf_test.py"],
        "Test collection breaks on an import failure inside a config module.",
        [("c1-conf-test", P), ("c1-conftest", H)],
        ["c1-conftest"],
    ),
    (
        "q-c1-07", "near_miss", "current_action", ["AUTH_TOKEN"],
        "Rotating a long-lived credential as part of cleanup week.",
        [("c1-auth-token", P), ("d-secret-rotation", A), ("d-env-service-token", A),
         ("d-configmap-reload", A), ("c1-auth-token-v2", A)],
        [],
    ),
    (
        "q-c1-08", "near_miss", "current_action", ["AUTH_TOKEN_V2"],
        "Standing up a local run of our integration-test suite.",
        [("c1-auth-token-v2", P), ("c1-auth-token", A), ("d-env-service-token", A),
         ("d-test-network", A)],
        [],
    ),
    (
        "q-c1-09", "near_miss", "current_action", ["build.gradle"],
        "Bumping a dependency version in the one module nobody migrated.",
        [("c1-gradle-groovy", P), ("d-transitive-pin", A)],
        [],
    ),
    (
        "q-c1-10", "near_miss", "current_action", ["build.gradle.kts"],
        "Iterating on build configuration and each rebuild now drags.",
        [("c1-gradle-kts", P)],
        [],
    ),
    (
        "q-c1-11", "near_miss", "current_action", ["user_id"],
        "Joining two tables on a user identifier column.",
        [("c1-user-id-snake", P), ("d-soft-delete-index", A), ("c1-user-id-camel", H)],
        ["c1-user-id-camel"],
    ),
    (
        "q-c1-12", "near_miss", "current_action", ["userId"],
        "Shipping a new public endpoint whose payload carries a user identifier.",
        [("c1-user-id-camel", P), ("c1-user-id-snake", A), ("d-serialize-bigint", A),
         ("d-null-vs-absent", A)],
        [],
    ),
    (
        "q-c1-13", "near_miss", "current_action", ["--no-cache"],
        "Want dependencies refreshed during our next image build; eyeing a flag.",
        [("c1-no-cache", P), ("d-npm-lock", A), ("d-docker-buildkit", A), ("c1-no-cache-dir", H)],
        ["c1-no-cache-dir"],
    ),
    (
        "q-c1-14", "near_miss", "current_action", ["--no-cache-dir"],
        "Auditing which installer flags belong in our image build.",
        [("c1-no-cache-dir", P), ("c1-no-cache", A), ("d-native-wheel", A)],
        ["c1-no-cache"],
    ),
    (
        "q-c1-15", "near_miss", "current_action", ["staging"],
        "Planning to purge aged objects from an environment before the audit.",
        [("c1-staging", P), ("c1-staging-2", A), ("d-s3-list-cost", A), ("d-artifact-retention", A)],
        ["c1-staging-2"],
    ),
    (
        "q-c1-16", "near_miss", "current_action", ["staging-2"],
        "Booked time this afternoon to rehearse a risky schema change safely.",
        [("c1-staging-2", P), ("c1-staging", A), ("c1-mig-0042", A), ("d-mig-0039", A)],
        [],
    ),
    (
        "q-c1-17", "near_miss", "current_action", ["retry_backoff"],
        "Configuring queue backoff, aiming for about 500 milliseconds.",
        [("c1-retry-backoff", P), ("c1-retry-backoff-ms", A), ("d-queue-visibility", A)],
        ["c1-retry-backoff-ms"],
    ),
    (
        "q-c1-18", "near_miss", "current_action", ["retry_backoff_ms"],
        "A backoff value I set is plainly being ignored at runtime.",
        [("c1-retry-backoff-ms", P), ("c1-retry-backoff", A), ("d-configmap-reload", A)],
        ["c1-retry-backoff"],
    ),
    (
        "q-c1-19", "near_miss", "current_action", ["parse_date"],
        "Parsing dates on incoming records using a helper already in the codebase.",
        [("c1-parse-date", P), ("c1-parse-datetime", A), ("d-serialize-datetime", A)],
        [],
    ),
    (
        "q-c1-20", "near_miss", "current_action", ["parse_datetime"],
        "Imported spreadsheet rows land with timestamps shifted by several hours.",
        [("c1-parse-datetime", P), ("c1-parse-date", A), ("c2-tz-report", A),
         ("d-serialize-datetime", A)],
        [],
    ),
    (
        "q-c1-21", "near_miss", "current_action", ["org.example.core.Config"],
        "Relocating a configuration class into another package during a tidy-up.",
        [("c1-dotted-a", P), ("d-abstract-registry", A), ("c1-dotted-b", H)],
        ["c1-dotted-b"],
    ),
    (
        "q-c1-22", "near_miss", "current_action", ["org.example.config.Core"],
        "Startup time regressed right after we started using a newer config class.",
        [("c1-dotted-b", P), ("c2-cold-start", A), ("c1-dotted-a", H)],
        ["c1-dotted-a"],
    ),
    (
        "q-c1-23", "near_miss", "current_action", ["DATABASE_URL"],
        "Reviewing how our service assembles its database connection string.",
        [("c1-db-url", P), ("c1-db-url-ro", A), ("d-pgbouncer-mode", A)],
        [],
    ),
    (
        "q-c1-24", "near_miss", "current_action", ["DATABASE_URL_RO"],
        "A write followed straight away by a read keeps flaking.",
        [("c1-db-url-ro", P), ("d-cache-negative", A)],
        [],
    ),
    (
        "q-c1-25", "near_miss", "current_action", ["30 seconds"],
        "Long report requests are being cut off; want a bigger ceiling.",
        [("c1-timeout-30", P), ("d-timeout-60", A), ("c5-late-index-hint", A),
         ("c1-timeout-300", H)],
        ["c1-timeout-300"],
    ),
    (
        "q-c1-26", "near_miss", "current_action", ["300 seconds"],
        "Long batch runs die partway and leave half-finished files around.",
        [("c1-timeout-300", P), ("c2-partial-write", A), ("d-signal-handler", A),
         ("c1-timeout-30", H)],
        ["c1-timeout-30"],
    ),
    (
        "q-c1-27", "near_miss", "current_action", ["0042"],
        "Slotting a column-type change into this week's schedule.",
        [("c1-mig-0042", P), ("c1-mig-0042-1", A)],
        ["c1-mig-0042-1"],
    ),
    (
        "q-c1-28", "near_miss", "current_action", ["0042_1"],
        "Just need an index-only migration applied; expecting it to be quick.",
        [("c1-mig-0042-1", P), ("c1-mig-0042", A)],
        ["c1-mig-0042"],
    ),
    # ----------------------------------------------------------- paraphrase_only
    (
        "q-c2-01", "paraphrase_only", "current_action", [],
        "Duration-based checks go red in bursts and pass on retry.",
        [("c2-flaky-clock", P), ("d-clock-monotonic", A), ("d-test-freeze-time", A),
         ("d-flaky-dns", A), ("d-pytest-order", A)],
        [],
    ),
    (
        "q-c2-02", "paraphrase_only", "current_action", [],
        "A worker occasionally wedges for minutes, then carries on unaided.",
        [("c2-lock-order", P), ("d-thread-fork", A), ("d-pgbouncer-mode", A),
         ("c1-retry-backoff", A)],
        [],
    ),
    (
        "q-c2-03", "paraphrase_only", "current_action", [],
        "Rollouts keep reverting though the new build behaves when I poke it.",
        [("c2-cold-start", P), ("d-readiness-vs-liveness", A), ("d-initcontainer-order", A),
         ("d-signal-handler", A), ("d-graceful-drain", A)],
        [],
    ),
    (
        "q-c2-04", "paraphrase_only", "current_action", [],
        "Users report uploaded documents vanishing when names carry accents.",
        [("c2-utf8-names", P)],
        [],
    ),
    (
        "q-c2-05", "paraphrase_only", "current_action", [],
        "An overseas user's totals disagree with the figures they typed in.",
        [("c2-tz-report", P), ("d-leapsecond", A), ("c1-parse-date", A), ("d-tz-cron", A),
         ("c2-orphan-rows", A)],
        [],
    ),
    (
        "q-c2-06", "paraphrase_only", "current_action", [],
        "Overnight aggregate totals come out under what accounting counts manually.",
        [("c2-orphan-rows", P), ("d-float-money", A), ("c2-tz-report", A), ("d-limit-1000", A)],
        [],
    ),
    (
        "q-c2-07", "paraphrase_only", "current_action", [],
        "One long-lived service creeps upward in memory for days until killed.",
        [("c2-memory-growth", P), ("d-metric-cardinality", A), ("c3-oom-137", A),
         ("c3-too-many-files", A)],
        [],
    ),
    (
        "q-c2-08", "paraphrase_only", "current_action", [],
        "A consumer downstream received an artefact missing most of its rows.",
        [("c2-partial-write", P), ("c3-json-extra-data", A), ("c1-timeout-300", A),
         ("d-limit-1000", A)],
        [],
    ),
    (
        "q-c2-09", "paraphrase_only", "current_action", [],
        "We added consumer instances and throughput stayed flat, lag looks worse.",
        [("c2-dup-consumer", P), ("d-rate-limit-shared", A), ("d-conn-pool-size", A),
         ("d-queue-visibility", A)],
        [],
    ),
    (
        "q-c2-10", "paraphrase_only", "current_action", [],
        "Outbound partner calls work from my desk but fail once deployed.",
        [("c2-cert-chain", P), ("c3-ssl-verify", P), ("d-tls-1-0", A), ("d-env-http-proxy", A),
         ("d-tls-sni", A)],
        [],
    ),
    # -------------------------------------------------------------- error_string
    (
        "q-c3-01", "error_string", "current_action",
        ["TypeError: Descriptors cannot not be created directly"],
        "A generated-stub import blows up right after we reinstalled dependencies.",
        [("c3-protobuf-desc", P), ("d-pip-resolver", A)],
        [],
    ),
    (
        "q-c3-02", "error_string", "current_action", ["137"],
        "One build stage dies late with only a numeric exit status.",
        [("c3-oom-137", P), ("d-node-heap", A)],
        [],
    ),
    (
        "q-c3-03", "error_string", "current_action",
        ["SSLCertVerificationError",
         "certificate verify failed: unable to get local issuer certificate"],
        "TLS verification fails for calls made from our deployed workload.",
        [("c3-ssl-verify", P), ("c2-cert-chain", P), ("d-tls-sni", A), ("d-env-http-proxy", A),
         ("d-tls-1-0", A)],
        [],
    ),
    (
        "q-c3-04", "error_string", "current_action", ["sqlite3.OperationalError", "database is locked"],
        "Our suite fails partway complaining about the database.",
        [("c3-locked-db", P), ("c4-parallel-new", A), ("c4-parallel-old", H)],
        ["c4-parallel-old"],
    ),
    (
        "q-c3-05", "error_string", "current_action", ["OSError", "[Errno 98]", "Address already in use"],
        "Restarting the suite straight away trips over a bound port.",
        [("c3-address-in-use", P)],
        [],
    ),
    (
        "q-c3-06", "error_string", "current_action", ["symbol lookup error", "undefined symbol"],
        "An import aborts on our own hardware although installation looked fine.",
        [("c3-symbol-lookup", P), ("c1-ver-2-3-1", P), ("d-native-wheel", A), ("d-ver-py-312", A)],
        [],
    ),
    (
        "q-c3-07", "error_string", "current_action", ["json.decoder.JSONDecodeError", "Extra data"],
        "Parsing an export in one pass fails right away.",
        [("c3-json-extra-data", P), ("c2-partial-write", A)],
        [],
    ),
    (
        "q-c3-08", "error_string", "current_action",
        ["ConnectionResetError", "[Errno 104]", "Connection reset by peer"],
        "Object-store requests sporadically drop after the connection sat idle.",
        [("c3-conn-reset", P), ("c1-ver-2-3-10", A), ("d-conn-pool-size", A)],
        [],
    ),
    (
        "q-c3-09", "error_string", "current_action", ["found duplicate key"],
        "Service refuses to boot on configuration that loads fine locally.",
        [("c3-yaml-dup-key", P), ("d-yaml-anchors", A)],
        [],
    ),
    (
        "q-c3-10", "error_string", "current_action", ["OSError", "[Errno 24]", "Too many open files"],
        "A big import run exhausts descriptors partway through.",
        [("c3-too-many-files", P), ("c3-conn-reset", A), ("d-conn-pool-size", A)],
        [],
    ),
    # ------------------------------------------------------------------ polarity
    (
        "q-c4-01", "polarity", "current_action", ["4.3"],
        "Considering the streaming path for our exporter; we run 4.3.",
        [("c4-streamapi-new", P), ("c2-partial-write", A), ("c4-streamapi-old", H)],
        ["c4-streamapi-old"],
    ),
    (
        "q-c4-02", "polarity", "current_action", [],
        "Want a faster local loop by running tests concurrently.",
        [("c4-parallel-new", P), ("c3-locked-db", A), ("d-test-freeze-time", A),
         ("c4-parallel-old", H)],
        ["c4-parallel-old"],
    ),
    (
        "q-c4-03", "polarity", "current_action", ["3.x"],
        "Adding a cache lookup inside the request handler; client is 3.x.",
        [("c4-cache-new", P), ("d-cache-stampede", A), ("d-cache-negative", A), ("c4-cache-old", H)],
        ["c4-cache-old"],
    ),
    (
        "q-c4-04", "polarity", "current_action", ["arm"],
        "Evaluating a cheaper runner architecture for our image builds.",
        [("c4-arm-new", P), ("d-native-wheel", A), ("c4-arm-old", H)],
        ["c4-arm-old"],
    ),
    (
        "q-c4-05", "polarity", "current_action", [],
        "Trying to delete a long-deprecated field from our event payload.",
        [("c4-schemareg-new", P), ("d-limit-64kb", A), ("c4-schemareg-old", H)],
        ["c4-schemareg-old"],
    ),
    (
        "q-c4-06", "polarity", "historical_intent", ["4.1"],
        "Pinned to 4.1 and deciding whether the streaming path is usable.",
        [("c4-streamapi-old", P), ("c4-streamapi-new", A)],
        [],
    ),
    (
        "q-c4-07", "polarity", "historical_intent", ["arm"],
        "Curious why an earlier attempt at a different runner architecture stopped.",
        [("c4-arm-old", P), ("c4-arm-new", A), ("d-native-wheel", A)],
        [],
    ),
    (
        "q-c4-08", "polarity", "historical_intent", ["2.x"],
        "Still on the 2.x client and wondering about calling it per request.",
        [("c4-cache-old", P), ("c4-cache-new", A)],
        ["c4-cache-new"],
    ),
    (
        "q-c4-09", "polarity", "historical_intent", [],
        "Someone asked where our serial-only testing guidance originally came from.",
        [("c4-parallel-old", P), ("c4-parallel-new", A)],
        [],
    ),
    (
        "q-c4-10", "polarity", "current_action", [],
        "Payloads have grown large and I want to know whether trimming is possible.",
        [("c4-schemareg-new", P), ("d-limit-64kb", A), ("c4-schemareg-old", H)],
        ["c4-schemareg-old"],
    ),
    # --------------------------------------------------------------- over_length
    (
        "q-c5-01", "over_length", "current_action", ["connect_timeout_ms"],
        "A per-call setting for connect timeout appears to do nothing.",
        [("c5-merge-precedence", P), ("d-configmap-reload", A)]
        + [(k, H) for k in c5_siblings("c5-merge-precedence")],
        c5_siblings("c5-merge-precedence"),
    ),
    (
        "q-c5-02", "over_length", "current_action", ["tenant_id"],
        "The planner ignores a composite index for one tenant-filtered query.",
        [("c5-late-index-hint", P), ("d-soft-delete-index", A), ("d-explain-analyze-prod", A),
         ("d-json-column-index", A)]
        + [(k, H) for k in c5_siblings("c5-late-index-hint")],
        c5_siblings("c5-late-index-hint"),
    ),
    (
        "q-c5-03", "over_length", "current_action", [],
        "Need to know where the deployed batch job picks up secrets.",
        [("c5-late-cred-path", P), ("d-configmap-reload", A), ("d-env-service-token", A),
         ("c1-auth-token", A)]
        + [(k, H) for k in c5_siblings("c5-late-cred-path")],
        c5_siblings("c5-late-cred-path"),
    ),
    (
        "q-c5-04", "over_length", "current_action", [],
        "An upload gave up immediately without making a second attempt.",
        [("c5-late-retry-budget", P), ("c1-ver-2-3-10", A), ("c3-conn-reset", A),
         ("d-idempotency-key", A)]
        + [(k, H) for k in c5_siblings("c5-late-retry-budget")],
        c5_siblings("c5-late-retry-budget"),
    ),
    (
        "q-c5-05", "over_length", "current_action", [],
        "Edited a template but the previous rendering is still going out.",
        [("c5-late-cache-key", P), ("d-cdn-invalidate", A), ("d-configmap-reload", A)]
        + [(k, H) for k in c5_siblings("c5-late-cache-key")],
        c5_siblings("c5-late-cache-key"),
    ),
    (
        "q-c5-06", "over_length", "current_action", [],
        "Signature validation fails now and then, only on our own hardware.",
        [("c5-late-clock-skew", P), ("d-clock-monotonic", A), ("d-signature-body", A),
         ("d-secret-rotation", A)]
        + [(k, H) for k in c5_siblings("c5-late-clock-skew")],
        c5_siblings("c5-late-clock-skew"),
    ),
]

NOTES = {
    "purpose": (
        "Authoring specification for an independently-written query set against the "
        "existing memory corpus in dataset.json. Whoever authors the prompts must not "
        "read the memories; everything needed is here."
    ),
    "situation": (
        "At most 15 words on the user's circumstance. Mechanically verified to share no "
        "span of 3+ consecutive words with any memory gist or content "
        "(check_stub_leakage.py)."
    ),
    "identifiers_involved": (
        "Literal tokens the user would plausibly already have in hand -- identifiers, env "
        "vars, versions, paths, error text. These are meant to appear verbatim in the "
        "authored prompt. Answer-side identifiers (ones only the memory knows) are "
        "deliberately excluded."
    ),
    "intent": (
        "current_action = the user wants to do the right thing now. historical_intent = "
        "the user asks about an old/pinned version or why something was once done, so a "
        "superseded record is legitimately the primary answer and must not be scored as "
        "staleness."
    ),
    "grades": {
        "primary": "directly answers or prevents the mistake; more than one is allowed where two records genuinely co-answer",
        "also_useful": "genuinely helps this situation; returning it alongside the primary is not a retrieval failure (D12 injects five gists)",
        "harmful_if_applied": "applying it to this situation produces a wrong action",
    },
    "confusable_uuids": (
        "Records a retriever is likely to return in place of the primary AND whose "
        "application would misdirect. May overlap relevant_memory_uuids: a record can be "
        "also_useful when read carefully and harmful when conflated with the primary."
    ),
}


def main() -> int:
    dataset = json.loads(DATASET.read_text())
    by_key = {m["key"]: m for m in dataset["memories"]}

    seen_ids: set[str] = set()
    stubs = []
    for stub_id, cat, intent, idents, situation, relevant, confusable in STUBS:
        assert stub_id not in seen_ids, f"duplicate stub_id {stub_id}"
        seen_ids.add(stub_id)
        assert cat in {"near_miss", "paraphrase_only", "error_string", "polarity", "over_length"}, cat
        assert intent in {"current_action", "historical_intent"}, intent
        assert len(situation.split()) <= 15, f"{stub_id}: situation too long"
        grades = {}
        for key, grade in relevant:
            assert key in by_key, f"{stub_id}: unknown memory key {key}"
            assert grade in {P, A, H}, grade
            assert key not in grades, f"{stub_id}: {key} graded twice"
            grades[key] = grade
        assert any(g == P for g in grades.values()), f"{stub_id}: no primary"
        for key in confusable:
            assert key in by_key, f"{stub_id}: unknown confusable key {key}"
            assert key in grades, f"{stub_id}: confusable {key} must also be graded"
        stubs.append(
            {
                "stub_id": stub_id,
                "trap_category": cat,
                "intent": intent,
                "identifiers_involved": idents,
                "situation": situation,
                "relevant_memory_uuids": [
                    {"uuid": by_key[k]["uuid"], "grade": g} for k, g in grades.items()
                ],
                "confusable_uuids": [by_key[k]["uuid"] for k in confusable],
            }
        )

    assert len(stubs) == dataset["n_queries"], f"{len(stubs)} stubs vs {dataset['n_queries']} queries"

    out = {
        "schema_version": 1,
        "source_dataset": "dataset.json",
        "source_dataset_memories": dataset["n_memories"],
        "n_stubs": len(stubs),
        "notes": NOTES,
        "stubs": stubs,
    }
    OUT.write_text(json.dumps(out, indent=2) + "\n")
    print(f"wrote {OUT.name}: {len(stubs)} stubs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
