"""Category 1 - near-miss identifier / version traps.

The decisive category. For each query, BOTH confusable memories are in the corpus and the
query must surface exactly one. The other is registered as a hard negative: if it outranks
the gold, that counts as a hard-negative displacement.

Authoring rules applied here:
  - Queries are phrased as a *session-opening user message*, not a paraphrase of the memory.
  - The discriminating token appears in the query, because that is the realistic case: a user
    who is working on WidgetV2 says "WidgetV2". The question under test is whether retrieval
    keeps the WidgetV1 memory from outranking it.
  - The two confusable memories are written to be near-identical in prose shape, so the only
    real signal separating them is the identifier itself. That is deliberately adversarial
    toward the dense side.
"""

MEMORIES = [
    # --- pair: WidgetV1 / WidgetV2 -------------------------------------------------
    dict(key="c1-widgetv1", cat="near_miss", gist=(
        "WidgetV1 serialisation drops the trailing nullable field, so round-tripping through the "
        "cache loses data; keep using the explicit field list."
    ), content=(
        "Hit this while wiring the cache warmer. WidgetV1's generated serialiser walks the field list "
        "from the schema descriptor and stops at the first field whose presence bit is unset, which "
        "silently truncates the trailing nullable field instead of emitting a null. Round-tripping a "
        "WidgetV1 through the cache therefore loses whatever was in that last field and no error is "
        "raised. Workaround that worked: pass the explicit field list to the serialiser call rather "
        "than relying on the descriptor walk. Do not try to fix the generated code, it is regenerated "
        "on every build."
    )),
    dict(key="c1-widgetv2", cat="near_miss", gist=(
        "WidgetV2 serialisation is fine, but its constructor requires the tenant id up front and "
        "throws a bare KeyError if you construct it from a legacy dict."
    ), content=(
        "WidgetV2 replaced the descriptor walk so the trailing-field truncation is gone. The new "
        "problem is construction: WidgetV2 requires tenant_id as a positional argument and "
        "the legacy dict shape does not carry one. Constructing from a legacy dict raises a bare "
        "KeyError with no field name in the message, which is very hard to trace back. Build the "
        "tenant id in from the request scope before the conversion, not after."
    )),

    # --- pair: v2.3.1 / v2.3.10 ----------------------------------------------------
    dict(key="c1-ver-2-3-1", cat="near_miss", gist=(
        "Pinning the pipeline library at v2.3.1 is required for the on-prem runner; later patches "
        "need a glibc the runner image does not have."
    ), content=(
        "The on-prem runner image is stuck on an older base and the pipeline library's wheels built "
        "after v2.3.1 link against a newer glibc. v2.3.1 is the last version that loads there. It "
        "fails at import time with a symbol lookup error, not at install time, so the install step "
        "goes green and the failure shows up much later in the run. Pin exactly, not with a caret."
    )),
    dict(key="c1-ver-2-3-10", cat="near_miss", gist=(
        "The pipeline library v2.3.10 changed the retry default from 3 to 0, so transient upload "
        "failures now surface instead of being retried."
    ), content=(
        "v2.3.10 shipped a behaviour change that is not in the changelog headline: the default retry "
        "count on the upload client went from 3 to 0. Anything that relied on the implicit retry now "
        "sees transient upload failures propagate. If you move to v2.3.10 you must set retries "
        "explicitly at the client construction site. Noticed because a job that had been stable for "
        "months started failing roughly one run in twenty after the bump."
    )),

    # --- pair: conftest.py / conf_test.py ------------------------------------------
    dict(key="c1-conftest", cat="near_miss", gist=(
        "Fixtures added to the top-level conftest.py are not picked up for the integration suite "
        "because that suite sets its own rootdir."
    ), content=(
        "Spent a while confused about a fixture that resolved in unit tests and not in integration "
        "tests. The integration suite is invoked with its own rootdir, so collection never ascends to "
        "the repository-level conftest.py and the fixture is simply not visible. There is no error, "
        "just a fixture-not-found at request time. Put shared fixtures in the plugin module that both "
        "suites load explicitly instead of relying on conftest.py discovery."
    )),
    dict(key="c1-conf-test", cat="near_miss", gist=(
        "conf_test.py is a real module in the config package and is not a test file; the collector "
        "tries to import it and fails on a missing optional dependency."
    ), content=(
        "There is a module named conf_test.py inside the config package. It is production code that "
        "tests a config file for validity, not a test module, but the default collection glob matches "
        "it and the collector imports it, which pulls in an optional dependency that is not in the "
        "test extra. The result is a collection error that looks like a broken test file. Exclude it "
        "by path in the collector config; renaming it was rejected because external callers import it."
    )),

    # --- pair: build.gradle / build.gradle.kts ------------------------------------
    dict(key="c1-gradle-groovy", cat="near_miss", gist=(
        "The legacy module still uses build.gradle in Groovy and its dependency block is ignored if "
        "the same coordinates appear in settings-level dependency management."
    ), content=(
        "One module was never migrated and still has a Groovy build.gradle. Its dependency "
        "declarations are shadowed if the same coordinates appear in the settings-level dependency "
        "management, and the shadowing is silent - you get the version from settings, not the one you "
        "are reading in the module file. This wasted an afternoon of reading the wrong file."
    )),
    dict(key="c1-gradle-kts", cat="near_miss", gist=(
        "build.gradle.kts in the service modules recompiles the whole build script on any change, "
        "which is why incremental builds feel slow after touching build config."
    ), content=(
        "The Kotlin DSL build.gradle.kts files are compiled, so editing one invalidates the build "
        "script cache and the next build spends a long time in configuration before any task runs. "
        "It is not the compile step being slow, it is script compilation. Batch build-config edits "
        "together rather than iterating one line at a time."
    )),

    # --- pair: user_id / userId (casing near-miss) --------------------------------
    dict(key="c1-user-id-snake", cat="near_miss", gist=(
        "The events table column is user_id and is a string, not an integer, because early rows hold "
        "external provider ids."
    ), content=(
        "user_id in the events table is declared as text. Early rows carry ids issued by an external "
        "provider that were never numeric, so the column could not be narrowed. Any join that casts "
        "it to an integer will drop those rows without warning because the cast fails to null and the "
        "join then misses. Compare as text."
    )),
    dict(key="c1-user-id-camel", cat="near_miss", gist=(
        "The public API serialises the field as userId; the mapper does not rename it automatically "
        "and a missing alias produces a null field rather than an error."
    ), content=(
        "On the wire the field is userId. The internal model uses a different name and the mapping is "
        "declared with an explicit alias. If you add a new endpoint and forget the alias, the "
        "serialiser emits userId as null rather than failing, so the endpoint looks like it works and "
        "the consumer sees a missing user. Add the alias and assert on it in the contract test."
    )),

    # --- pair: --no-cache / --no-cache-dir ----------------------------------------
    dict(key="c1-no-cache", cat="near_miss", gist=(
        "Passing --no-cache to the image build defeats layer caching and pushes the build from about "
        "two minutes to over twenty; it is not what you want for a dependency refresh."
    ), content=(
        "--no-cache on the image build discards every layer, including the base dependency layer that "
        "takes the bulk of the time. People reach for it to force a dependency refresh, but the "
        "correct move is to bump the lock file so the dependency layer's cache key changes, leaving "
        "the rest of the cache intact. Using --no-cache turns a two-minute build into more than "
        "twenty minutes for no benefit."
    )),
    dict(key="c1-no-cache-dir", cat="near_miss", gist=(
        "--no-cache-dir on the package installer is required inside the build container or the image "
        "carries several hundred megabytes of wheel cache."
    ), content=(
        "Without --no-cache-dir the installer leaves its wheel cache in the layer and the final image "
        "grows by a few hundred megabytes of files nothing reads at runtime. It does not affect build "
        "time meaningfully. Always set it in the container install step. Note this is a different flag "
        "from the image builder's own cache control and the two get confused constantly."
    )),

    # --- pair: staging / staging-2 environments -----------------------------------
    dict(key="c1-staging", cat="near_miss", gist=(
        "The staging environment shares its object store bucket with production, so destructive "
        "cleanup jobs run there are genuinely dangerous."
    ), content=(
        "staging was set up before the bucket-per-environment convention and still points at the "
        "production bucket with a key prefix. A cleanup job that deletes by prefix is fine; one that "
        "lists and deletes by age is not, because it will walk out of the prefix. Verify the prefix "
        "guard in any cleanup job before running it against staging."
    )),
    dict(key="c1-staging-2", cat="near_miss", gist=(
        "staging-2 is the isolated environment with its own bucket and database; use it for anything "
        "destructive, but its data is reset nightly."
    ), content=(
        "staging-2 was built to be properly isolated: separate bucket, separate database, no "
        "production credentials in scope. It is the right place for destructive testing. The tradeoff "
        "is a nightly reset, so anything you want to keep across a day has to be re-seeded. The seed "
        "script is idempotent and safe to re-run."
    )),

    # --- pair: retry_backoff / retry_backoff_ms -----------------------------------
    dict(key="c1-retry-backoff", cat="near_miss", gist=(
        "retry_backoff in the queue config is interpreted as seconds despite the surrounding keys "
        "being milliseconds."
    ), content=(
        "Almost every duration key in the queue config is in milliseconds, but retry_backoff is "
        "seconds because it predates the convention. Setting it to 500 expecting half a second gives "
        "you an eight-minute backoff and the consumer looks hung. There is no validation on the "
        "range. Read the unit from the loader, not from the neighbouring keys."
    )),
    dict(key="c1-retry-backoff-ms", cat="near_miss", gist=(
        "retry_backoff_ms is the newer key and it overrides retry_backoff silently when both are "
        "present, with no warning logged."
    ), content=(
        "retry_backoff_ms was added to fix the unit confusion. The loader prefers it when both keys "
        "are present and logs nothing, so a config that sets the old key and the new key disagreeing "
        "will quietly use the new one. If you are debugging a backoff that does not match the config "
        "you are reading, check whether the other key is also set."
    )),

    # --- pair: parse_date / parse_datetime ----------------------------------------
    dict(key="c1-parse-date", cat="near_miss", gist=(
        "parse_date returns a naive date and drops any timezone in the input without complaint, "
        "shifting day boundaries for non-UTC callers."
    ), content=(
        "parse_date takes the date portion and discards the rest, including the offset. For an input "
        "late in the day in a negative-offset zone this yields the wrong calendar day, and the bug "
        "only shows up for a few hours a day, which is why it survived so long. Use the datetime "
        "variant and truncate deliberately in the caller's zone."
    )),
    dict(key="c1-parse-datetime", cat="near_miss", gist=(
        "parse_datetime assumes UTC for offset-less input rather than local time, which is correct "
        "for the API but wrong for the CSV importer."
    ), content=(
        "parse_datetime attaches UTC when the input has no offset. That matches what the API "
        "contract says, so it is right there. The CSV importer feeds it operator-entered local "
        "timestamps with no offset, so every imported row is shifted by the operator's offset. The "
        "importer needs to attach the zone before parsing; do not change the shared function."
    )),

    # --- pair: org.example.core.Config / org.example.config.Core ------------------
    dict(key="c1-dotted-a", cat="near_miss", gist=(
        "org.example.core.Config is loaded reflectively by the plugin host, so renaming or moving it "
        "breaks plugins at runtime with no compile error."
    ), content=(
        "The plugin host resolves org.example.core.Config by name from a manifest string. Nothing "
        "references it statically, so a rename or package move compiles cleanly and then fails at "
        "plugin load with a class-not-found. Grep the manifests as well as the source before touching "
        "that class."
    )),
    dict(key="c1-dotted-b", cat="near_miss", gist=(
        "org.example.config.Core is the newer replacement and reading it eagerly at startup adds "
        "noticeable time because it validates every key against the remote schema."
    ), content=(
        "org.example.config.Core validates each key against a schema fetched from the config service. "
        "Constructing it during startup therefore blocks on a network round trip per key group and "
        "adds a large fraction of the startup budget. Construct it lazily on first use, and cache. "
        "Easy to confuse with the older core.Config, which does no validation at all."
    )),

    # --- pair: DATABASE_URL / DATABASE_URL_RO ------------------------------------
    dict(key="c1-db-url", cat="near_miss", gist=(
        "DATABASE_URL must include the sslmode parameter or the connection silently falls back to "
        "plaintext against the managed instance."
    ), content=(
        "The managed database accepts both TLS and plaintext, and the driver will happily downgrade "
        "if sslmode is not in DATABASE_URL. Nothing logs the downgrade. Include the sslmode parameter "
        "explicitly in the URL. This was caught by a network audit, not by us."
    )),
    dict(key="c1-db-url-ro", cat="near_miss", gist=(
        "DATABASE_URL_RO points at a read replica with replication lag of a few seconds; read-after-"
        "write through it fails intermittently in tests."
    ), content=(
        "DATABASE_URL_RO is the replica. Lag is usually under a second but spikes to several seconds "
        "under load. Any test that writes and then reads through the read-only URL is flaky by "
        "construction. Either read back through the primary URL or add an explicit wait on the "
        "replication position; the second is what the durable tests do."
    )),

    # --- pair: 30 second gateway timeout / 300 second worker timeout -------------
    dict(key="c1-timeout-30", cat="near_miss", gist=(
        "The gateway's upstream timeout is 30 seconds and cannot be raised; long requests must be "
        "made asynchronous instead."
    ), content=(
        "The gateway cuts upstream requests at 30 seconds. The value is set in the shared platform "
        "config and the platform team has declined to raise it. Anything that can exceed it has to "
        "become a submit-then-poll flow. Attempting to stream a keepalive to hold the connection open "
        "does not help; the timeout is on total duration, not idle time."
    )),
    dict(key="c1-timeout-300", cat="near_miss", gist=(
        "The batch worker's own timeout is 300 seconds, and it is enforced by the supervisor killing "
        "the process, so cleanup handlers do not run."
    ), content=(
        "The batch worker gets 300 seconds before the supervisor sends a kill rather than a term, so "
        "no finally block or exit handler runs and any partially written output stays behind. This "
        "is why the output directory accumulates half-files. Write to a temporary name and rename at "
        "the end so a killed run leaves nothing that looks complete."
    )),

    # --- pair: migration 0042 / 0042_1 -------------------------------------------
    dict(key="c1-mig-0042", cat="near_miss", gist=(
        "Migration 0042 takes an exclusive lock for the whole table rewrite and must not be run "
        "during business hours."
    ), content=(
        "Migration 0042 changes a column type, which the engine implements as a full table rewrite "
        "under an exclusive lock. On the production-sized table that is tens of minutes of total "
        "unavailability for that table. It ran fine in staging because the table there is tiny. Run "
        "it in a maintenance window, or do the add-column-backfill-swap dance instead."
    )),
    dict(key="c1-mig-0042-1", cat="near_miss", gist=(
        "Migration 0042_1 is the hotfix that only adds an index and is safe to run online with the "
        "concurrent flag."
    ), content=(
        "0042_1 was split out of 0042 precisely so the index could go in without the rewrite. It uses "
        "the concurrent index build so it does not take a blocking lock, but that also means it "
        "cannot run inside a transaction, and the migration runner wraps everything in one by "
        "default. Run it with the runner's no-transaction escape hatch."
    )),
]

QUERIES = [
    dict(qid="q-c1-01", cat="near_miss",
         text="I'm adding a cache warmer path for WidgetV1 today, anything I should know before I start?",
         gold=["c1-widgetv1"], hard_neg=["c1-widgetv2"]),
    dict(qid="q-c1-02", cat="near_miss",
         text="Working on constructing WidgetV2 from our old dict payloads this morning.",
         gold=["c1-widgetv2"], hard_neg=["c1-widgetv1"]),
    dict(qid="q-c1-03", cat="near_miss",
         text="Need to get the on-prem runner green again. It's on pipeline lib v2.3.1 right now.",
         gold=["c1-ver-2-3-1"], hard_neg=["c1-ver-2-3-10"]),
    dict(qid="q-c1-04", cat="near_miss",
         text="We just bumped the pipeline library to v2.3.10 and uploads are failing sometimes.",
         gold=["c1-ver-2-3-10"], hard_neg=["c1-ver-2-3-1"]),
    dict(qid="q-c1-05", cat="near_miss",
         text="I want to add a shared fixture in conftest.py so both suites can use it.",
         gold=["c1-conftest"], hard_neg=["c1-conf-test"]),
    dict(qid="q-c1-06", cat="near_miss",
         text="Collection is erroring on conf_test.py, what's the story there?",
         gold=["c1-conf-test"], hard_neg=["c1-conftest"]),
    dict(qid="q-c1-07", cat="near_miss",
         text="Rotating AUTH_TOKEN today as part of the credential cleanup.",
         gold=["c1-auth-token"], hard_neg=["c1-auth-token-v2"]),
    dict(qid="q-c1-08", cat="near_miss",
         text="Trying to run the integration suite locally, do I need AUTH_TOKEN_V2 set?",
         gold=["c1-auth-token-v2"], hard_neg=["c1-auth-token"]),
    dict(qid="q-c1-09", cat="near_miss",
         text="Touching the legacy module's build.gradle to change a dependency version.",
         gold=["c1-gradle-groovy"], hard_neg=["c1-gradle-kts"]),
    dict(qid="q-c1-10", cat="near_miss",
         text="Builds got slow after I started editing build.gradle.kts, is that expected?",
         gold=["c1-gradle-kts"], hard_neg=["c1-gradle-groovy"]),
    dict(qid="q-c1-11", cat="near_miss",
         text="Writing a join against the events table on user_id.",
         gold=["c1-user-id-snake"], hard_neg=["c1-user-id-camel"]),
    dict(qid="q-c1-12", cat="near_miss",
         text="Adding a new public endpoint that returns userId in the payload.",
         gold=["c1-user-id-camel"], hard_neg=["c1-user-id-snake"]),
    dict(qid="q-c1-13", cat="near_miss",
         text="Thinking of adding --no-cache to force our dependencies to refresh in the image build.",
         gold=["c1-no-cache"], hard_neg=["c1-no-cache-dir"]),
    dict(qid="q-c1-14", cat="near_miss",
         text="Reviewing our container install step, should --no-cache-dir be there?",
         gold=["c1-no-cache-dir"], hard_neg=["c1-no-cache"]),
    dict(qid="q-c1-15", cat="near_miss",
         text="I need to run a cleanup job in staging to clear out old artefacts.",
         gold=["c1-staging"], hard_neg=["c1-staging-2"]),
    dict(qid="q-c1-16", cat="near_miss",
         text="Planning to do the destructive migration rehearsal in staging-2 this afternoon.",
         gold=["c1-staging-2"], hard_neg=["c1-staging"]),
    dict(qid="q-c1-17", cat="near_miss",
         text="Setting retry_backoff in the queue config, want to give it half a second.",
         gold=["c1-retry-backoff"], hard_neg=["c1-retry-backoff-ms"]),
    dict(qid="q-c1-18", cat="near_miss",
         text="The backoff I set in retry_backoff_ms doesn't seem to be taking effect.",
         gold=["c1-retry-backoff-ms"], hard_neg=["c1-retry-backoff"]),
    dict(qid="q-c1-19", cat="near_miss",
         text="Using parse_date on the incoming records, is that the right call?",
         gold=["c1-parse-date"], hard_neg=["c1-parse-datetime"]),
    dict(qid="q-c1-20", cat="near_miss",
         text="The CSV importer goes through parse_datetime and the timestamps look off by hours.",
         gold=["c1-parse-datetime"], hard_neg=["c1-parse-date"]),
    dict(qid="q-c1-21", cat="near_miss",
         text="I want to move org.example.core.Config into a different package as part of the tidy-up.",
         gold=["c1-dotted-a"], hard_neg=["c1-dotted-b"]),
    dict(qid="q-c1-22", cat="near_miss",
         text="Startup got slower after we wired in org.example.config.Core.",
         gold=["c1-dotted-b"], hard_neg=["c1-dotted-a"]),
    dict(qid="q-c1-23", cat="near_miss",
         text="Reviewing how we build DATABASE_URL for the managed instance.",
         gold=["c1-db-url"], hard_neg=["c1-db-url-ro"]),
    dict(qid="q-c1-24", cat="near_miss",
         text="A test that reads through DATABASE_URL_RO right after writing is flaking.",
         gold=["c1-db-url-ro"], hard_neg=["c1-db-url"]),
    dict(qid="q-c1-25", cat="near_miss",
         text="Can we raise the gateway timeout past 30 seconds for the report endpoint?",
         gold=["c1-timeout-30"], hard_neg=["c1-timeout-300"]),
    dict(qid="q-c1-26", cat="near_miss",
         text="Batch worker runs are getting killed around 300 seconds and leaving junk behind.",
         gold=["c1-timeout-300"], hard_neg=["c1-timeout-30"]),
    dict(qid="q-c1-27", cat="near_miss",
         text="Scheduling migration 0042 for this week, what's involved?",
         gold=["c1-mig-0042"], hard_neg=["c1-mig-0042-1"]),
    dict(qid="q-c1-28", cat="near_miss",
         text="Just need to get migration 0042_1 applied, it's only an index.",
         gold=["c1-mig-0042-1"], hard_neg=["c1-mig-0042"]),
]

# AUTH_TOKEN pair lives here (kept out of the block above only for readability of the diff)
MEMORIES += [
    dict(key="c1-auth-token", cat="near_miss", gist=(
        "AUTH_TOKEN is only read at process start; rotating it in the environment mid-run has no "
        "effect and the stale token is used until restart."
    ), content=(
        "AUTH_TOKEN is captured once into a module-level constant at import time. Rotating the value "
        "in the environment while the process is running does nothing, and because the old token stays "
        "valid for its remaining lifetime the failure appears only after expiry, far from the rotation. "
        "If you rotate, restart the process. There is no reload path."
    )),
    dict(key="c1-auth-token-v2", cat="near_miss", gist=(
        "AUTH_TOKEN_V2 must be set for the integration suite; when it is absent the suite skips "
        "silently and reports green."
    ), content=(
        "The integration suite gates on AUTH_TOKEN_V2 being present and, when it is not, marks its "
        "cases as skipped rather than failing. The overall run then reports success with almost "
        "nothing executed, which is how a broken integration path shipped unnoticed. Export "
        "AUTH_TOKEN_V2 before running the suite locally, and treat a suspiciously fast integration "
        "run as a signal that it is unset."
    )),
]
