"""Categories 2-5.

cat2 paraphrase_only : gold shares almost no surface tokens with the query. BM25 should struggle.
cat3 error_string    : query is a literal traceback / error line. BM25 should shine.
cat4 polarity        : a memory and its later correction are both present; the query needs the
                       current one, and the superseded one is the hard negative.
cat5 over_length     : content deliberately exceeds 512 WordPiece tokens with the load-bearing
                       detail placed LATE, so a silently-truncating embedder cannot see it. The
                       query targets only that late detail, and the gist deliberately does NOT
                       contain it - otherwise the trap would be defeated by the gist alone.
"""

# ---------------------------------------------------------------------------
# Category 2 - paraphrase only. Queries avoid the memory's distinctive vocabulary.
# ---------------------------------------------------------------------------
CAT2_MEMORIES = [
    dict(key="c2-flaky-clock", cat="paraphrase_only", gist=(
        "Tests that assert on elapsed wall-clock duration fail on the shared runners because the "
        "runners are heavily oversubscribed at the top of the hour."
    ), content=(
        "Several suites assert that an operation completes inside a duration bound. On the shared "
        "runners those assertions fail in bursts, always near the top of the hour, because scheduled "
        "jobs land then and the runner CPU is oversubscribed. Nothing is wrong with the code. Replace "
        "duration assertions with a fake clock, or mark them to run only on the dedicated pool."
    )),
    dict(key="c2-lock-order", cat="paraphrase_only", gist=(
        "Two background jobs acquire the same two advisory locks in opposite order, which deadlocks "
        "roughly weekly under load."
    ), content=(
        "The reconciler takes the account lock then the ledger lock. The sweeper takes them the other "
        "way round. Under low load they never overlap; under load they do, and the pair deadlocks "
        "until one is evicted by the timeout. It presents as a stuck job with no error for several "
        "minutes. Fix is a documented global ordering for lock acquisition, applied in both jobs."
    )),
    dict(key="c2-cold-start", cat="paraphrase_only", gist=(
        "First request after a deploy is slow enough to trip the health check, so the rollout marks "
        "healthy instances as failed unless the warmup probe is configured."
    ), content=(
        "The first request to a freshly started instance pays for lazy initialisation and takes long "
        "enough that the health check's own deadline elapses. The orchestrator then kills the instance "
        "and tries again, producing a rollout that appears to fail for no reason. Configuring the "
        "startup probe with a generous initial delay fixes it; raising the liveness timeout does not, "
        "because the problem is only at start."
    )),
    dict(key="c2-utf8-names", cat="paraphrase_only", gist=(
        "Uploaded files whose names contain non-ASCII characters are stored with mangled keys because "
        "one hop in the path assumes latin-1."
    ), content=(
        "A file named with accented characters ends up under a mangled object key. The mangling comes "
        "from a middle hop that decodes the header as latin-1 before re-encoding. Downstream lookups "
        "by the original name then miss. The fix is to percent-encode the name at the edge and never "
        "pass raw bytes through that hop; retrofitting the existing mangled keys needs a one-off "
        "migration that has not been written."
    )),
    dict(key="c2-tz-report", cat="paraphrase_only", gist=(
        "The daily report boundary is computed in the server's zone, so users in other regions see "
        "days that start at odd hours and rows that appear to be missing."
    ), content=(
        "Report windows are cut on the server's local midnight. For a user several hours away that "
        "means their day appears to start mid-afternoon, and any row they created after their own "
        "midnight but before the server's is filed under the previous day, which reads as a missing "
        "row. The report needs a per-user zone parameter, which the query layer does not currently "
        "thread through."
    )),
    dict(key="c2-orphan-rows", cat="paraphrase_only", gist=(
        "Deleting a parent record leaves its children behind because the constraint was created "
        "without cascade, and the leftovers break the nightly aggregate."
    ), content=(
        "The foreign key was added without a cascade action, so removing a parent leaves children "
        "pointing at nothing. Reads mostly tolerate it, but the nightly aggregate joins through the "
        "parent and the orphaned rows silently drop out of the total, which is how a reporting "
        "discrepancy appeared. Clean up the existing orphans before adding the cascade, or the "
        "constraint addition will fail validation."
    )),
    dict(key="c2-memory-growth", cat="paraphrase_only", gist=(
        "The long-running consumer grows without bound because the metrics library keeps one series "
        "per distinct label value and the label includes a request identifier."
    ), content=(
        "Resident memory on the consumer climbs steadily over days and is not a leak in the usual "
        "sense: the metrics registry retains a time series per unique label combination, and one "
        "label was wired to a per-request identifier, so the registry grows once per request forever. "
        "Removing that label from the metric is the whole fix. Restarting only resets the clock."
    )),
    dict(key="c2-partial-write", cat="paraphrase_only", gist=(
        "A crash mid-export leaves a truncated artefact that downstream jobs happily consume as if "
        "complete, because there is no end marker."
    ), content=(
        "The exporter streams rows straight to the destination name. If it dies partway the file is "
        "shorter but structurally valid, so the consumer reads it and produces quietly wrong numbers. "
        "There is no length header and no terminator to check. Write to a scratch name and move it "
        "into place at the end; the move is atomic on the same volume."
    )),
    dict(key="c2-dup-consumer", cat="paraphrase_only", gist=(
        "Scaling the consumer past the partition count adds no throughput and makes the lag graph "
        "look worse because idle members still report."
    ), content=(
        "Adding consumer instances beyond the number of partitions gains nothing - the extra members "
        "sit idle with no assignment. Worse, they still publish lag metrics, and the aggregate lag "
        "panel averages across members, so adding idle members makes the panel read high while actual "
        "throughput is unchanged. Scale partitions first if you need more parallelism."
    )),
    dict(key="c2-cert-chain", cat="paraphrase_only", gist=(
        "Outbound calls to the partner fail only from inside the cluster because the intermediate "
        "certificate is not in the slim base image's trust store."
    ), content=(
        "The partner endpoint serves a chain that relies on an intermediate the slim base image does "
        "not ship. It works from a developer laptop and fails inside the cluster, which sends everyone "
        "looking at network policy first. Add the intermediate to the image's trust store, or use the "
        "fuller base. Disabling verification was proposed and rejected."
    )),
]

CAT2_QUERIES = [
    dict(qid="q-c2-01", cat="paraphrase_only", gold=["c2-flaky-clock"], hard_neg=[],
         text="Some of our timing-sensitive checks keep going red and then passing on a rerun. What have we found out about that?"),
    dict(qid="q-c2-02", cat="paraphrase_only", gold=["c2-lock-order"], hard_neg=[],
         text="One of the background processes seems to hang completely every so often and then recovers on its own."),
    dict(qid="q-c2-03", cat="paraphrase_only", gold=["c2-cold-start"], hard_neg=[],
         text="Our releases keep getting rolled back even though the new version works fine when I try it by hand."),
    dict(qid="q-c2-04", cat="paraphrase_only", gold=["c2-utf8-names"], hard_neg=[],
         text="Customers with accented characters in their filenames say their documents disappear after upload."),
    dict(qid="q-c2-05", cat="paraphrase_only", gold=["c2-tz-report"], hard_neg=[],
         text="A user in another country says numbers on their summary page don't line up with what they entered."),
    dict(qid="q-c2-06", cat="paraphrase_only", gold=["c2-orphan-rows"], hard_neg=[],
         text="Finance says the totals in the overnight rollup are lower than what they can count by hand."),
    dict(qid="q-c2-07", cat="paraphrase_only", gold=["c2-memory-growth"], hard_neg=[],
         text="One of our services slowly eats RAM until it gets killed, roughly every three days."),
    dict(qid="q-c2-08", cat="paraphrase_only", gold=["c2-partial-write"], hard_neg=[],
         text="A downstream team got a file from us that looked fine but only had half the records in it."),
    dict(qid="q-c2-09", cat="paraphrase_only", gold=["c2-dup-consumer"], hard_neg=[],
         text="We doubled the number of workers and it didn't get any faster, the backlog chart actually looks worse."),
    dict(qid="q-c2-10", cat="paraphrase_only", gold=["c2-cert-chain"], hard_neg=[],
         text="Calls to the third party succeed on my machine but not once deployed. I assumed firewall but nothing is blocked."),
]

# ---------------------------------------------------------------------------
# Category 3 - exact error string. Query is a literal line the user pasted in.
# ---------------------------------------------------------------------------
CAT3_MEMORIES = [
    dict(key="c3-protobuf-desc", cat="error_string", gist=(
        "TypeError: Descriptors cannot not be created directly means the generated protobuf stubs are "
        "older than the installed runtime; regenerate rather than downgrading."
    ), content=(
        "Full message is 'TypeError: Descriptors cannot not be created directly' (the doubled 'not' is "
        "upstream's own typo, so search for it verbatim). It means the checked-in generated stubs were "
        "produced by an older protoc than the installed runtime expects. The advertised workaround of "
        "setting the pure-python implementation environment variable makes it start but is roughly ten "
        "times slower on our message sizes. Regenerate the stubs against the pinned protoc instead."
    )),
    dict(key="c3-oom-137", cat="error_string", gist=(
        "A build step that ends with 'exited with code 137' is the container being OOM-killed, not a "
        "compiler failure; the default memory limit is too low for the link step."
    ), content=(
        "Exit code 137 is the kill signal, and in the build container it always means memory. The link "
        "step peaks well above the default limit while the compile steps stay under it, so the build "
        "gets most of the way through before dying, which makes it look like a code problem. Raise the "
        "step's memory request; parallelism reduction also works but takes much longer."
    )),
    dict(key="c3-ssl-verify", cat="error_string", gist=(
        "'certificate verify failed: unable to get local issuer certificate' from inside the job is "
        "the missing intermediate in the slim image, not a proxy problem."
    ), content=(
        "The exact text is 'SSLCertVerificationError: certificate verify failed: unable to get local "
        "issuer certificate'. Inside the job it means the trust store lacks the intermediate, which "
        "the slim base does not ship. It is not the corporate proxy, which is the first thing everyone "
        "checks. Install the intermediate into the image trust store."
    )),
    dict(key="c3-locked-db", cat="error_string", gist=(
        "'database is locked' in the test suite comes from two tests sharing one file-backed database "
        "with the default busy timeout of zero."
    ), content=(
        "'sqlite3.OperationalError: database is locked' shows up when the suite runs in parallel and "
        "two workers touch the same file-backed database. The default busy timeout is zero, so the "
        "second writer fails instantly instead of waiting. Give each worker its own database file; "
        "raising the busy timeout only converts the hard failure into a slow one."
    )),
    dict(key="c3-address-in-use", cat="error_string", gist=(
        "'OSError: [Errno 98] Address already in use' after a test run is the previous run's server "
        "thread surviving because the fixture never joins it."
    ), content=(
        "Errno 98 on the second consecutive test run means the first run's server thread is still "
        "holding the port. The fixture starts the server but never shuts it down, and because the "
        "thread is non-daemon the interpreter waits on it only at exit. Bind to port zero and read "
        "back the assigned port, and add an explicit shutdown to the fixture teardown."
    )),
    dict(key="c3-symbol-lookup", cat="error_string", gist=(
        "'symbol lookup error: undefined symbol' at import time on the on-prem runner is the glibc "
        "mismatch in the pipeline library wheels."
    ), content=(
        "The runner prints 'symbol lookup error: /usr/lib/.../libpipeline.so: undefined symbol' during "
        "import, well after a green install step. It is the wheel being built against a newer glibc "
        "than the runner image has. Pin the library to the last version that still builds against the "
        "old base rather than trying to patch the image."
    )),
    dict(key="c3-json-extra-data", cat="error_string", gist=(
        "'json.decoder.JSONDecodeError: Extra data' when reading the export means the file is "
        "newline-delimited records, not a single document."
    ), content=(
        "'Extra data: line 2 column 1' means the parser read a complete value and then found more "
        "input. Our export writes one record per line, so a whole-file parse always fails this way. "
        "Read it line by line. The format is deliberate because the file is too large to hold in "
        "memory as one document."
    )),
    dict(key="c3-conn-reset", cat="error_string", gist=(
        "'ConnectionResetError: [Errno 104] Connection reset by peer' from the object store is the "
        "idle-connection reaper, and retrying the request is the intended handling."
    ), content=(
        "Errno 104 from the object store client happens when a pooled connection has been idle past "
        "the gateway's reaper interval and is closed without a shutdown handshake. The next use of it "
        "fails. It is expected and the client's own retry handles it, but our wrapper had retries "
        "disabled. Enable the retry, and set the pool's recycle interval below the reaper interval."
    )),
    dict(key="c3-yaml-dup-key", cat="error_string", gist=(
        "'found duplicate key' from the config loader is fatal in the strict loader we use, even "
        "though the permissive loader everyone tests with tolerates it."
    ), content=(
        "The service loads config with duplicate-key checking on and aborts with 'found duplicate key' "
        "at start. Editors and local scripts use the permissive loader, which silently keeps the last "
        "occurrence, so a config that works locally will refuse to boot in the service. Run the "
        "strict-loader check as a pre-commit step."
    )),
    dict(key="c3-too-many-files", cat="error_string", gist=(
        "'OSError: [Errno 24] Too many open files' in the importer is unclosed response bodies, not "
        "an ulimit that needs raising."
    ), content=(
        "Errno 24 during a large import traces back to response objects that are never closed because "
        "the code reads a header and discards the object without draining the body. The pool keeps the "
        "socket open. Raising the file-descriptor limit hides it for a while and it comes back on a "
        "bigger import. Use the context-manager form at every call site."
    )),
]

CAT3_QUERIES = [
    dict(qid="q-c3-01", cat="error_string", gold=["c3-protobuf-desc"], hard_neg=[],
         text="TypeError: Descriptors cannot not be created directly"),
    dict(qid="q-c3-02", cat="error_string", gold=["c3-oom-137"], hard_neg=[],
         text="The build just died with: process exited with code 137"),
    dict(qid="q-c3-03", cat="error_string", gold=["c3-ssl-verify"], hard_neg=["c2-cert-chain"],
         text="SSLCertVerificationError: certificate verify failed: unable to get local issuer certificate"),
    dict(qid="q-c3-04", cat="error_string", gold=["c3-locked-db"], hard_neg=[],
         text="sqlite3.OperationalError: database is locked"),
    dict(qid="q-c3-05", cat="error_string", gold=["c3-address-in-use"], hard_neg=[],
         text="OSError: [Errno 98] Address already in use"),
    dict(qid="q-c3-06", cat="error_string", gold=["c3-symbol-lookup"], hard_neg=["c1-ver-2-3-1"],
         text="symbol lookup error: undefined symbol"),
    dict(qid="q-c3-07", cat="error_string", gold=["c3-json-extra-data"], hard_neg=[],
         text="json.decoder.JSONDecodeError: Extra data: line 2 column 1 (char 118)"),
    dict(qid="q-c3-08", cat="error_string", gold=["c3-conn-reset"], hard_neg=[],
         text="ConnectionResetError: [Errno 104] Connection reset by peer"),
    dict(qid="q-c3-09", cat="error_string", gold=["c3-yaml-dup-key"], hard_neg=[],
         text='service won\'t boot: while constructing a mapping, found duplicate key'),
    dict(qid="q-c3-10", cat="error_string", gold=["c3-too-many-files"], hard_neg=[],
         text="OSError: [Errno 24] Too many open files"),
]

# ---------------------------------------------------------------------------
# Category 4 - polarity / supersession. Old warning + newer correction both present.
# Gold is the CURRENT truth; the superseded memory is the hard negative.
# ---------------------------------------------------------------------------
CAT4_MEMORIES = [
    dict(key="c4-streamapi-old", cat="polarity", gist=(
        "Do not use the streaming API yet: it has a race on partial flush that corrupts the last "
        "chunk under concurrency."
    ), content=(
        "The streaming API drops or duplicates the final chunk when two writers flush concurrently. "
        "Reproduced reliably at four concurrent writers. Until this is fixed upstream, use the "
        "buffered path even though it costs memory. Do not be tempted by the streaming example in the "
        "docs; it is single-writer."
    )),
    dict(key="c4-streamapi-new", cat="polarity", gist=(
        "The streaming API's partial-flush race was fixed in 4.2 and it is now the recommended path; "
        "the old buffered workaround should be removed."
    ), content=(
        "Upstream fixed the partial-flush race in 4.2 and we have confirmed it at sixteen concurrent "
        "writers with no corruption. Streaming is now the recommended path and the buffered workaround "
        "we carried should be deleted, since it holds whole payloads in memory. Requires 4.2 or later; "
        "the fix was not backported to the 4.1 line."
    )),
    dict(key="c4-parallel-old", cat="polarity", gist=(
        "Running the test suite in parallel is not safe: the shared temporary directory collides and "
        "produces failures that do not reproduce serially."
    ), content=(
        "Parallel test execution fails unpredictably because several suites write to a fixed path "
        "under the temporary directory and stamp on each other. The failures never reproduce when run "
        "serially, which cost a lot of time. Run serially until the fixtures are made hermetic."
    )),
    dict(key="c4-parallel-new", cat="polarity", gist=(
        "Test fixtures are hermetic now, so parallel test execution is safe and is the default; the "
        "serial-only guidance is obsolete."
    ), content=(
        "The fixtures were reworked to allocate per-worker temporary directories, so the collision is "
        "gone and parallel execution is safe. It is now the default in the runner config and cuts the "
        "suite from roughly eleven minutes to under three. If you see a parallel-only failure now, it "
        "is a real bug and not the old fixture problem."
    )),
    dict(key="c4-cache-old", cat="polarity", gist=(
        "The shared cache client must not be used from the request path: it blocks on a global lock "
        "and adds unpredictable latency spikes."
    ), content=(
        "The shared cache client serialises all calls through one lock, so a slow call blocks every "
        "other caller in the process. On the request path that shows up as latency spikes with no "
        "correlation to the request itself. Use the per-request client, or read through the local "
        "in-process cache."
    )),
    dict(key="c4-cache-new", cat="polarity", gist=(
        "The shared cache client's global lock was removed in the 3.x client; it is now safe on the "
        "request path and the per-request client is deprecated."
    ), content=(
        "The 3.x cache client replaced the global lock with per-connection state, so the head-of-line "
        "blocking is gone. It is now the correct thing to use on the request path, and the "
        "per-request client we introduced as a workaround is deprecated and will be removed. Verified "
        "with a latency histogram before and after; the spike class disappeared entirely."
    )),
    dict(key="c4-arm-old", cat="polarity", gist=(
        "Do not build images for the arm runners: two of our native dependencies have no arm wheels "
        "and building them from source times out."
    ), content=(
        "The arm build fails because two native dependencies publish no arm wheels, and building "
        "either from source exceeds the job timeout. Several people have tried; do not spend more time "
        "on it. Stay on the x86 runners."
    )),
    dict(key="c4-arm-new", cat="polarity", gist=(
        "Both native dependencies now publish arm wheels, so arm builds work and are about 30 percent "
        "cheaper; the do-not-build guidance is stale."
    ), content=(
        "Both blocking dependencies now ship arm wheels, so the arm image builds cleanly with no "
        "source compilation. The build is roughly 30 percent cheaper per run and slightly faster. The "
        "previous do-not-build-for-arm guidance is stale and should not stop you. One caveat: the "
        "profiler in the debug image is still x86 only."
    )),
    dict(key="c4-schemareg-old", cat="polarity", gist=(
        "The schema registry rejects field removals, so a deprecated field has to be kept forever in "
        "the payload."
    ), content=(
        "The registry's compatibility mode refuses any change that removes a field, so once shipped a "
        "field is permanent. The practice has been to leave deprecated fields in place and document "
        "them as unused. This has made a couple of payloads quite large."
    )),
    dict(key="c4-schemareg-new", cat="polarity", gist=(
        "The registry's compatibility mode was relaxed to allow removing fields that have been marked "
        "deprecated for two releases, so payload cleanup is now possible."
    ), content=(
        "Compatibility mode was changed so a field marked deprecated for at least two releases can be "
        "removed. Payload cleanup is therefore possible now and there is a backlog of fields eligible "
        "for it. The removal still has to go through the deprecation marker first; deleting a field "
        "outright is rejected exactly as before."
    )),
]

CAT4_QUERIES = [
    dict(qid="q-c4-01", cat="polarity", gold=["c4-streamapi-new"], hard_neg=["c4-streamapi-old"],
         text="I'd like to switch the exporter over to the streaming API. We're on 4.3. Any reason not to?"),
    dict(qid="q-c4-02", cat="polarity", gold=["c4-parallel-new"], hard_neg=["c4-parallel-old"],
         text="Can I run the tests in parallel to speed up my loop, or is that going to bite me?"),
    dict(qid="q-c4-03", cat="polarity", gold=["c4-cache-new"], hard_neg=["c4-cache-old"],
         text="Adding a cache read to the request handler using the shared client. We're on the 3.x client."),
    dict(qid="q-c4-04", cat="polarity", gold=["c4-arm-new"], hard_neg=["c4-arm-old"],
         text="Looking at moving our image builds onto the arm runners to save money."),
    dict(qid="q-c4-05", cat="polarity", gold=["c4-schemareg-new"], hard_neg=["c4-schemareg-old"],
         text="I want to drop a field that's been deprecated for a few releases from the event payload."),
    # reverse-direction probes: the query pins an OLD version, so the OLD memory is gold.
    dict(qid="q-c4-06", cat="polarity", gold=["c4-streamapi-old"], hard_neg=["c4-streamapi-new"],
         text="We're stuck on 4.1 for now. Is the streaming API safe for us to use there?"),
    dict(qid="q-c4-07", cat="polarity", gold=["c4-arm-old"], hard_neg=["c4-arm-new"],
         text="Why did the arm build effort get abandoned last time round? What blocked it?"),
    dict(qid="q-c4-08", cat="polarity", gold=["c4-cache-old"], hard_neg=["c4-cache-new"],
         text="This service is still on the 2.x cache client. Is it OK to call it from the handler?"),
    dict(qid="q-c4-09", cat="polarity", gold=["c4-parallel-old"], hard_neg=["c4-parallel-new"],
         text="What was the original reason we told people to run the suite serially?"),
    dict(qid="q-c4-10", cat="polarity", gold=["c4-schemareg-new"], hard_neg=["c4-schemareg-old"],
         text="Is there any way at all to shrink the event payload, or are we stuck with every field forever?"),
]

# ---------------------------------------------------------------------------
# Category 5 - over-length. Load-bearing detail is LATE in content and absent from the gist.
# The filler is deliberately on-topic prose, not lorem ipsum, so truncation is the only
# thing that hides the answer.
# ---------------------------------------------------------------------------

_FILLER_A = (
    "Background, because this took a while to pin down and the reasoning matters if it regresses. "
    "The service builds its outbound request from three sources: defaults compiled into the client, "
    "an overlay read from the environment, and a per-call argument map. Precedence runs left to right "
    "in that list, so the per-call map wins, then the environment overlay, then the compiled defaults. "
    "That ordering is not written down anywhere except the loader, and reading the loader is genuinely "
    "confusing because the merge is expressed as a fold over a list of providers rather than as an "
    "explicit precedence table. The first thing we tried was adding logging at the merge site, which "
    "showed the final map but not which provider each key came from, so it told us the value was wrong "
    "without telling us why. We then added provenance tagging to the merge, which was more invasive "
    "than it sounds because the provider protocol had no place to carry a label, and the change had to "
    "thread a label through four call sites. That did eventually give us the answer, and the "
    "instrumentation is still there behind a debug flag, which is worth knowing because turning it on "
    "is much faster than re-deriving this. Along the way we ruled out several plausible explanations. "
    "It was not the environment overlay being stale, because the process reads it on every call rather "
    "than caching it. It was not a serialisation problem, because the wire capture matched the merged "
    "map exactly. It was not a race between concurrent calls, because it reproduced with a single call "
    "on an otherwise idle process. It was also not the retry wrapper re-entering the merge, though "
    "that was the theory we spent longest on, because the wrapper does rebuild the map on each attempt "
    "and that would have been a reasonable way for a value to change between attempts. We confirmed "
    "the wrapper is not involved by reproducing with retries disabled entirely. "
)

_FILLER_B = (
    "Some further context that is useful but not the punchline. The behaviour differs between the "
    "local development setup and the deployed one, which sent us down a couple of dead ends early on. "
    "Locally the environment overlay is almost empty, so the compiled defaults dominate and everything "
    "looks sane. In the deployed environment the overlay is populated by the platform's own injection, "
    "which contributes keys nobody on the team wrote, and those keys are the ones that surprise you. "
    "You can list them, but only from inside the running container, because the injection happens at "
    "start rather than being visible in the deployment manifest. That asymmetry between local and "
    "deployed is worth internalising generally: any conclusion reached purely locally about "
    "configuration precedence is suspect. We also spent time reading the platform documentation for "
    "the injection, which describes what it injects but not the precedence relative to application "
    "configuration, and the two teams had different assumptions about it. That ambiguity is the "
    "underlying cause of the whole class of confusion here, rather than any single bug. "
)


def _overlength(key, gist, punchline, filler=(_FILLER_A + _FILLER_B)):
    """Assemble a long content whose only load-bearing sentence is at the very end."""
    return dict(key=key, cat="over_length", gist=gist, content=(filler + punchline))


CAT5_MEMORIES = [
    _overlength(
        "c5-merge-precedence",
        gist=("Outbound request configuration merges three providers and the precedence is only "
              "discoverable by reading the loader; debug provenance tagging exists behind a flag."),
        punchline=(
            "The actual operative rule, and the thing to remember: the platform's injected overlay "
            "silently wins over anything set in the per-call argument map for exactly two keys, "
            "connect_timeout_ms and tls_min_version, because those two are re-applied after the merge "
            "by a post-merge hardening step. Setting them per call has no effect. To change them you "
            "must set PLATFORM_OVERRIDE_ALLOW=connect_timeout_ms,tls_min_version in the deployment, "
            "and that variable is read once at start."
        )),
    _overlength(
        "c5-late-index-hint",
        gist=("Long write-up of the query-planner investigation on the events table, including the "
              "several explanations we ruled out."),
        punchline=(
            "The conclusion, which is the only part worth acting on: the planner will not use the "
            "composite index unless the query filters on tenant_id with a literal rather than a bound "
            "parameter, because the statistics on that column are extremely skewed and the generic "
            "plan is chosen for parameterised queries. Inline the tenant literal, or force a custom "
            "plan for that statement. Adding more indexes does not help and we tried four of them."
        )),
    _overlength(
        "c5-late-cred-path",
        gist=("Extended notes on how credentials reach the batch job, including the dead ends around "
              "the environment overlay and the local-versus-deployed asymmetry."),
        punchline=(
            "The load-bearing detail: the batch job does not read credentials from the environment at "
            "all in the deployed case. It reads them from the file at /var/run/secrets/batch/creds.json "
            "and only falls back to the environment when that file is absent, which is why setting the "
            "environment variable locally works and changes nothing in deployment. Mount a replacement "
            "file to override, and note the fallback is silent."
        )),
    _overlength(
        "c5-late-retry-budget",
        gist=("Full investigation notes on the retry behaviour of the upload path and the several "
              "theories we eliminated along the way."),
        punchline=(
            "What actually matters: retries share a per-process token budget, so a burst of failures "
            "in one caller exhausts the budget and makes an unrelated caller's first attempt appear to "
            "fail without any retry at all. The budget refills at ten tokens per second and is not "
            "observable in the metrics. If you see a single-attempt failure that should have retried, "
            "look at what else was failing at that moment rather than at the caller."
        )),
    _overlength(
        "c5-late-cache-key",
        gist=("Long note on the cache-key derivation for rendered documents and the various theories "
              "about the stale-render reports."),
        punchline=(
            "The operative fact: the cache key does not include the template version, so a template "
            "change serves stale renders until the entries age out, which takes seven days. Bump "
            "TEMPLATE_CACHE_SALT in the deployment whenever a template changes; there is no automatic "
            "invalidation and nothing warns you."
        )),
    _overlength(
        "c5-late-clock-skew",
        gist=("Extended write-up of the signature-validation failures and the several hypotheses that "
              "did not pan out."),
        punchline=(
            "The real cause and the fix: signature validation allows only 30 seconds of clock skew, "
            "and the on-prem runners have no time daemon, so they drift far enough within a day to "
            "fail validation intermittently. Enable time synchronisation on the runner image. "
            "Widening the tolerance was rejected on security grounds and will not be revisited."
        )),
]

CAT5_QUERIES = [
    dict(qid="q-c5-01", cat="over_length", gold=["c5-merge-precedence"], hard_neg=[],
         text="Setting connect_timeout_ms per call doesn't seem to do anything. What's going on?"),
    dict(qid="q-c5-02", cat="over_length", gold=["c5-late-index-hint"], hard_neg=[],
         text="Why won't the planner pick up the composite index when I filter by tenant?"),
    dict(qid="q-c5-03", cat="over_length", gold=["c5-late-cred-path"], hard_neg=[],
         text="Where does the batch job actually get its credentials from in deployment?"),
    dict(qid="q-c5-04", cat="over_length", gold=["c5-late-retry-budget"], hard_neg=[],
         text="An upload failed on the very first attempt with no retry at all. How is that possible?"),
    dict(qid="q-c5-05", cat="over_length", gold=["c5-late-cache-key"], hard_neg=[],
         text="I changed a template and people are still seeing the old rendering. How do I flush it?"),
    dict(qid="q-c5-06", cat="over_length", gold=["c5-late-clock-skew"], hard_neg=[],
         text="Signature checks fail intermittently on the on-prem runners only."),
]

MEMORIES = CAT2_MEMORIES + CAT3_MEMORIES + CAT4_MEMORIES + CAT5_MEMORIES
QUERIES = CAT2_QUERIES + CAT3_QUERIES + CAT4_QUERIES + CAT5_QUERIES
