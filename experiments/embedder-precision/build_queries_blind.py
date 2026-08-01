#!/usr/bin/env python3
"""Build queries_blind.json -- the v2, independently-authored query set.

Authored under a blindfold: the author of this table read ONLY stubs_v2.json and
README.md. dataset.json, dataset_src/, results/ and research/embedder-benchmark-results.md
were never opened, so no query phrasing could be tuned against memory prose.

Three variants per stub (64 stubs -> 192 prompts), deliberately differentiated:

  variant 1 = terse      -- what a developer actually types first: a clause, lowercase,
                            no ceremony, often missing context a librarian would supply
  variant 2 = verbose    -- multi-sentence, includes the surrounding story, states what
                            was already ruled out, ends in an open ask
  variant 3 = mid        -- one sentence, different entry angle from v1: usually a
                            sanity-check or "is X involved" question rather than a task
                            statement

`variant_style` is recorded per row so the analysis stage can either pool the three
(uncertainty over phrasings, per review finding on paired variants) or split by register
and report whether terse prompts retrieve worse -- which is the operationally important
question, since real prompts are terse.

`underspecified=True` marks rows that deliberately withhold a cue a careful author would
have included (the exact error string, the distinguishing detail). The v1 set oversampled
well-specified prompts; these sample the other tail.

Discipline applied while authoring:
  - identifiers from `identifiers_involved` appear verbatim, and the *paired* near-miss
    identifier never appears in its twin's prompts (no `v2.3.10` in a `v2.3.1` prompt,
    no `--no-cache-dir` in a `--no-cache` prompt, etc). Validated below.
  - no prompt names a resolution. Prompts state symptom, intent and what the user has
    already checked. Where a user belief is asserted ("I'm sure retries are configured")
    it is a belief the stub's situation implies, not an answer.
  - `historical_intent` stubs ask about the past or about the old pinned version, never
    "what should I do now".
"""
from __future__ import annotations

import json
import re
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUBS = HERE / "stubs_v2.json"
OUT = HERE / "queries_blind.json"

TERSE, MID, VERBOSE = "terse", "mid", "verbose"

# (stub_id, variant, style, underspecified, text)
ROWS: list[tuple[str, int, str, bool, str]] = [
    # ---------------------------------------------------------------- cat 1: near_miss
    ("q-c1-01", 1, TERSE, False,
     "need to cache WidgetV1 instances and read them back later"),
    ("q-c1-01", 2, VERBOSE, False,
     "I'm adding a warm-up job that fills the cache with WidgetV1 objects at startup so "
     "the request path can read them straight back out instead of rebuilding them. It "
     "works in a scratch script but I don't want to find out the hard way in prod. "
     "Anything about WidgetV1 and our cache layer I should know before I wire this up?"),
    ("q-c1-01", 3, MID, False,
     "round-tripping WidgetV1 through the cache in the new warmer, any gotchas?"),

    ("q-c1-02", 1, TERSE, False,
     "how do I turn our old dict payloads into WidgetV2"),
    ("q-c1-02", 2, VERBOSE, False,
     "We still have a pile of handlers passing widgets around as raw dictionaries. I want "
     "to convert those to WidgetV2 so the rest of the pipeline gets a real type instead of "
     "guessing at keys. Where should I start, and what tends to go wrong in that conversion?"),
    ("q-c1-02", 3, MID, False,
     "migrating our legacy dict payloads over to WidgetV2 today, walk me through it"),

    ("q-c1-03", 1, TERSE, True,
     "on-prem runner is red on v2.3.1, need it green before we cut the release"),
    ("q-c1-03", 2, VERBOSE, False,
     "Release is Thursday and our self-hosted CI box is failing while the hosted runners "
     "are perfectly happy on the same commit. We're on v2.3.1. I've already re-run it twice "
     "and cleared the workspace. Can you work out why that one machine is unhappy?"),
    ("q-c1-03", 3, MID, False,
     "what do I need to do to get v2.3.1 passing again on the on-prem runner?"),

    ("q-c1-04", 1, TERSE, False,
     "uploads flaky since we went to v2.3.10"),
    ("q-c1-04", 2, VERBOSE, False,
     "Since last week's bump to v2.3.10 uploads fail maybe one time in twenty, with no "
     "pattern I can find in file size or user. Nothing else went out in that deploy. I "
     "can't reproduce it on demand either. Where should I be looking?"),
    ("q-c1-04", 3, MID, False,
     "we moved to v2.3.10 and now uploads intermittently blow up, is that related?"),

    ("q-c1-05", 1, TERSE, True,
     "where do I put a fixture both suites can use, conftest.py?"),
    ("q-c1-05", 2, VERBOSE, False,
     "The unit suite and the integration suite both need the same fixture and I really "
     "don't want two copies drifting apart. My plan was a single conftest.py high enough "
     "up that both of them pick it up. Does that actually work the way I'm assuming here?"),
    ("q-c1-05", 3, MID, False,
     "adding a shared fixture to conftest.py so unit and integration both see it, sound right?"),

    ("q-c1-06", 1, TERSE, True,
     "collection dies importing conf_test.py"),
    ("q-c1-06", 2, VERBOSE, False,
     "pytest never gets as far as running anything: collection errors out on an import "
     "inside conf_test.py. If I just run python against that module directly it imports "
     "fine, which is what's confusing me. Can you untangle it?"),
    ("q-c1-06", 3, MID, False,
     "test collection is failing with an import error out of conf_test.py, any idea why?"),

    ("q-c1-07", 1, TERSE, True,
     "rotating AUTH_TOKEN this week"),
    ("q-c1-07", 2, VERBOSE, False,
     "It's cleanup week and AUTH_TOKEN has been sitting unrotated for longer than I want "
     "to admit. I'd like to roll it properly rather than in a panic later. What all has to "
     "change when I do that, and what's likely to break while I'm doing it?"),
    ("q-c1-07", 3, MID, False,
     "planning to rotate AUTH_TOKEN, what should I watch out for?"),

    ("q-c1-08", 1, TERSE, False,
     "running the integration tests locally, do I need AUTH_TOKEN_V2 set?"),
    ("q-c1-08", 2, VERBOSE, False,
     "New laptop, and it's the first time I've tried the integration suite on it. I've got "
     "AUTH_TOKEN_V2 exported in my shell but the suite still isn't getting all the way "
     "through, and I suspect I'm missing setup rather than hitting a real bug. Can you get "
     "me to a clean local run?"),
    ("q-c1-08", 3, MID, False,
     "what does a local integration run need besides AUTH_TOKEN_V2?"),

    ("q-c1-09", 1, TERSE, True,
     "bump a dep version in the old build.gradle module"),
    ("q-c1-09", 2, VERBOSE, False,
     "There's exactly one module left that still has a plain build.gradle rather than being "
     "converted along with everything else. I need to bump a dependency version in it. Is "
     "editing that one any different from the rest, or can I treat it the same?"),
    ("q-c1-09", 3, MID, False,
     "anything special about changing a dependency version in build.gradle for the module nobody migrated?"),

    ("q-c1-10", 1, TERSE, False,
     "editing build.gradle.kts and every rebuild is slow now"),
    ("q-c1-10", 2, VERBOSE, False,
     "I'm going back and forth on build configuration in build.gradle.kts and each time I "
     "change a line the rebuild takes far longer than it used to. It's making the whole "
     "iteration painful. Is there something about that loop I'm doing wrong, or is this "
     "just how it is?"),
    ("q-c1-10", 3, MID, False,
     "can the edit-rebuild loop on build.gradle.kts be made less slow?"),

    ("q-c1-11", 1, TERSE, True,
     "joining these two tables on user_id"),
    ("q-c1-11", 2, VERBOSE, False,
     "I'm writing a query that joins two of our tables on user_id and the row counts come "
     "out lower than they should. The data looks present on both sides when I eyeball it. "
     "Before I keep poking at the SQL, is there anything about how user_id is stored across "
     "those tables that I should know?"),
    ("q-c1-11", 3, MID, False,
     "is there anything odd about user_id that would make a join on it misbehave?"),

    ("q-c1-12", 1, TERSE, True,
     "new public endpoint, payload has userId"),
    ("q-c1-12", 2, VERBOSE, False,
     "About to ship a new public API endpoint. The response body carries userId alongside a "
     "few other fields. Once this is out it's contract and I can't quietly change it, so "
     "I'd rather get the field right first time. What conventions apply here?"),
    ("q-c1-12", 3, MID, False,
     "shipping an endpoint that returns userId in the payload, anything I should get right first?"),

    ("q-c1-13", 1, TERSE, False,
     "should I add --no-cache to the image build to get fresh deps?"),
    ("q-c1-13", 2, VERBOSE, False,
     "Our image builds look like they're reusing a stale dependency layer, so I was going "
     "to throw --no-cache onto the build command and force everything to be fetched again. "
     "Is that the right lever for this, and what does it cost us if I do?"),
    ("q-c1-13", 3, MID, False,
     "want fresh dependencies in the next image build, sanity check me on --no-cache"),

    ("q-c1-14", 1, TERSE, True,
     "do we actually want --no-cache-dir in there?"),
    ("q-c1-14", 2, VERBOSE, False,
     "I'm going through the image build tidying up the install step and there's a stack of "
     "flags on it including --no-cache-dir. Some of them look like they were copied in years "
     "ago and never questioned. Which of these earn their place for us and which are cargo cult?"),
    ("q-c1-14", 3, MID, False,
     "auditing the installer flags in our image build, is --no-cache-dir doing anything useful?"),

    ("q-c1-15", 1, TERSE, False,
     "want to clear out old records in staging before the audit"),
    ("q-c1-15", 2, VERBOSE, False,
     "The audit is coming up and staging is stuffed with junk left over from months of "
     "testing. I want to delete everything older than ninety days out of it so the audit "
     "sees something sane. Can I just do that, or is there a process around it?"),
    ("q-c1-15", 3, MID, False,
     "is purging aged objects out of staging something I can just go ahead and do?"),

    ("q-c1-16", 1, TERSE, False,
     "want to rehearse a schema change on staging-2 this afternoon"),
    ("q-c1-16", 2, VERBOSE, False,
     "I've got a schema change that makes me nervous and I want a full dry run somewhere "
     "realistic before it goes anywhere near prod. I've blocked out this afternoon to do it "
     "on staging-2. What do I need to know about that environment before I start?"),
    ("q-c1-16", 3, MID, False,
     "using staging-2 as the rehearsal environment for a risky migration today, set me up?"),

    ("q-c1-17", 1, TERSE, False,
     "set retry_backoff to about half a second"),
    ("q-c1-17", 2, VERBOSE, False,
     "The queue consumer hammers away instantly on failures, so I want to space the retries "
     "out to roughly five hundred milliseconds. There's a retry_backoff setting in the "
     "config. What do I actually put in it to get that?"),
    ("q-c1-17", 3, MID, False,
     "configuring retry_backoff for 500 milliseconds, what value goes in the file?"),

    ("q-c1-18", 1, TERSE, True,
     "retry_backoff_ms isn't doing anything"),
    ("q-c1-18", 2, VERBOSE, False,
     "I set retry_backoff_ms in the config and restarted the service, but from the "
     "timestamps in the log the retries are clearly still firing at the old interval. The "
     "value is definitely in the file and definitely being loaded. Why is it being ignored?"),
    ("q-c1-18", 3, MID, False,
     "set retry_backoff_ms and the retry spacing didn't change at all, what am I missing?"),

    ("q-c1-19", 1, TERSE, True,
     "using parse_date on the incoming records"),
    ("q-c1-19", 2, VERBOSE, False,
     "The new ingest path has to turn a date string on each incoming record into a real "
     "date, and there's already a parse_date helper sitting in the codebase, so I'd rather "
     "use that than write another one. Is there anything I should know about it before I "
     "lean on it?"),
    ("q-c1-19", 3, MID, False,
     "about to wire parse_date into the new ingest, good to go?"),

    ("q-c1-20", 1, TERSE, False,
     "imported timestamps come out a few hours off, we go through parse_datetime"),
    ("q-c1-20", 2, VERBOSE, False,
     "A user uploads a spreadsheet, we import it, and the timestamps that land in the "
     "database are several hours away from what's in the file. The import runs everything "
     "through parse_datetime. The file itself looks fine when I open it. Can you work out "
     "where the shift is introduced?"),
    ("q-c1-20", 3, MID, False,
     "spreadsheet import lands timestamps hours off, is parse_datetime the culprit?"),

    ("q-c1-21", 1, TERSE, True,
     "moving org.example.core.Config into another package"),
    ("q-c1-21", 2, VERBOSE, False,
     "Doing a package tidy-up and org.example.core.Config has ended up somewhere it "
     "doesn't belong, so I want to relocate it. It's referenced from a lot of places. Is "
     "move-the-file-and-fix-the-imports going to be enough here, or is there more to it?"),
    ("q-c1-21", 3, MID, False,
     "what breaks if I relocate org.example.core.Config during this refactor?"),

    ("q-c1-22", 1, TERSE, False,
     "startup got a lot slower after we switched to org.example.config.Core"),
    ("q-c1-22", 2, VERBOSE, False,
     "Boot time went from a couple of seconds to something like fifteen, and the only "
     "change in that window was moving over to org.example.config.Core. I've ruled out the "
     "database being slow to accept connections. Can you figure out what it's doing during "
     "startup?"),
    ("q-c1-22", 3, MID, False,
     "we adopted org.example.config.Core and startup regressed badly, can you dig in?"),

    ("q-c1-23", 1, TERSE, True,
     "where does DATABASE_URL come from?"),
    ("q-c1-23", 2, VERBOSE, False,
     "I'm trying to understand how this service ends up with its database connection "
     "string. I can see DATABASE_URL being read at startup but I can't find where it gets "
     "assembled or who sets it in each environment. Walk me through the whole path before I "
     "change anything."),
    ("q-c1-23", 3, MID, False,
     "reviewing how we build up DATABASE_URL before I touch it, how does it work?"),

    ("q-c1-24", 1, TERSE, True,
     "write then immediate read keeps flaking"),
    ("q-c1-24", 2, VERBOSE, False,
     "There's a flow that inserts a row and then reads it straight back, and about a third "
     "of the time the read comes back with nothing. Retrying always works, which is why it "
     "took us so long to notice. We do have a DATABASE_URL_RO configured. What's going on?"),
    ("q-c1-24", 3, MID, False,
     "is DATABASE_URL_RO involved in why our read-after-write flakes?"),

    ("q-c1-25", 1, TERSE, False,
     "reports get cut off at 30 seconds, want to raise that"),
    ("q-c1-25", 2, VERBOSE, False,
     "Our heaviest report takes longer than 30 seconds to build and the request dies before "
     "it can finish, so the user just sees a failure. I want to give it more headroom. Where "
     "do I raise that ceiling, and how far can I sensibly push it?"),
    ("q-c1-25", 3, MID, False,
     "how do I lift the 30 seconds request limit so the big reports finish?"),

    ("q-c1-26", 1, TERSE, False,
     "batch job dies around 300 seconds and leaves partial files behind"),
    ("q-c1-26", 2, VERBOSE, False,
     "The nightly batch keeps getting cut off somewhere around 300 seconds in, and when it "
     "goes it leaves half-written output sitting there that the next stage cheerfully picks "
     "up as if it were complete. That second part worries me more than the first. Can you "
     "look at both?"),
    ("q-c1-26", 3, MID, False,
     "what's killing our long batch runs near 300 seconds, and why is partial output left over?"),

    ("q-c1-27", 1, TERSE, True,
     "when can we run 0042?"),
    ("q-c1-27", 2, VERBOSE, False,
     "Migration 0042 changes a column type and I need to fit it into this week somewhere. "
     "I'm trying to work out roughly how long it'll take and whether it needs its own "
     "window or can go out with a normal deploy. What's involved in running it?"),
    ("q-c1-27", 3, MID, False,
     "scheduling the 0042 column type change, does it need a maintenance window?"),

    ("q-c1-28", 1, TERSE, True,
     "apply 0042_1, should be quick right?"),
    ("q-c1-28", 2, VERBOSE, False,
     "As far as I can tell 0042_1 only adds an index, so I was going to just run it in the "
     "middle of the working day and not make a fuss about it. Is that fine, or am I being "
     "naive about what that does?"),
    ("q-c1-28", 3, MID, False,
     "running 0042_1 now, index only so I'm expecting seconds not minutes, confirm?"),

    # ----------------------------------------------------------- cat 2: paraphrase_only
    ("q-c2-01", 1, TERSE, True,
     "timing tests fail in clumps then pass on rerun"),
    ("q-c2-01", 2, VERBOSE, False,
     "We've got a handful of tests that assert on how long an operation took, and they go "
     "red several at a time on CI and then all pass the moment I hit rerun. Nobody trusts a "
     "red build any more because of them. Can you sort them out properly rather than just "
     "retrying?"),
    ("q-c2-01", 3, MID, False,
     "our elapsed-time assertions keep flaking in bursts, should I fix them or delete them?"),

    ("q-c2-02", 1, TERSE, True,
     "worker hangs for a few minutes then recovers on its own"),
    ("q-c2-02", 2, VERBOSE, False,
     "One of the background workers just stops making progress for two or three minutes at "
     "a time. No exception, no crash, nothing in the log, and then it picks up where it left "
     "off as though nothing happened. It does this a few times a day. Where do I even start?"),
    ("q-c2-02", 3, MID, False,
     "what would make a worker stall for minutes with no error and then carry on unaided?"),

    ("q-c2-03", 1, TERSE, True,
     "deploys keep rolling back but the build works when I try it"),
    ("q-c2-03", 2, VERBOSE, False,
     "Every rollout of this service gets automatically reverted a few minutes in. If I run "
     "the exact same image myself and hit it, it answers fine, so something in the deployed "
     "environment disagrees with my assessment that it's healthy. Can you work out what?"),
    ("q-c2-03", 3, MID, False,
     "rollout auto-reverts even though the new build responds fine when I curl it, why?"),

    ("q-c2-04", 1, TERSE, True,
     "some uploaded documents just aren't there afterwards"),
    ("q-c2-04", 2, VERBOSE, False,
     "Support has three tickets now from users saying a document they uploaded isn't there "
     "when they go back for it. The one thing those cases have in common is accented "
     "characters in the filename, things like resume with the acute accents. Can you trace "
     "what actually happens to those files?"),
    ("q-c2-04", 3, MID, False,
     "files with accents in the name seem to go missing after upload, can you chase it?"),

    ("q-c2-05", 1, TERSE, True,
     "customer abroad says our totals don't match what they entered"),
    ("q-c2-05", 2, VERBOSE, False,
     "A customer overseas is telling us the summary figures we show them don't agree with "
     "the numbers they typed in themselves. Their individual entries look correct in the raw "
     "table, so whatever is happening is between there and the total. Can you find it?"),
    ("q-c2-05", 3, MID, False,
     "where would an overseas user's totals stop matching their own inputs?"),

    ("q-c2-06", 1, TERSE, True,
     "nightly totals come out lower than finance's numbers"),
    ("q-c2-06", 2, VERBOSE, False,
     "Accounting tallies the month by hand and consistently gets a bigger number than our "
     "overnight aggregation reports. The gap is not rounding-sized, it's percent-sized. I "
     "need to work out which of us is wrong and why before the next close."),
    ("q-c2-06", 3, MID, False,
     "our overnight rollup undercounts against a manual tally, where's the shortfall coming from?"),

    ("q-c2-07", 1, TERSE, True,
     "service memory climbs for days until it gets killed"),
    ("q-c2-07", 2, VERBOSE, False,
     "One of our long-running services grows its memory footprint steadily over about four "
     "days and then gets killed and restarted, at which point the clock resets. The other "
     "services on the same box don't do this. Nothing in the code jumps out at me. Can you "
     "hunt it down?"),
    ("q-c2-07", 3, MID, False,
     "slow memory creep in one long-lived service that a restart clears, where's it going?"),

    ("q-c2-08", 1, TERSE, True,
     "downstream got a file with most of the rows missing"),
    ("q-c2-08", 2, VERBOSE, False,
     "A team consuming our nightly export came back saying the file they received had a few "
     "hundred rows in it instead of the usual few hundred thousand. Our job reported success "
     "and logged no error at all, which is the part that actually scares me. Can you find out "
     "what happened?"),
    ("q-c2-08", 3, MID, False,
     "our export arrived downstream truncated and the job still claimed success, how?"),

    ("q-c2-09", 1, TERSE, True,
     "scaled up consumers, throughput didn't move"),
    ("q-c2-09", 2, VERBOSE, False,
     "We doubled the number of consumer instances expecting to chew through the backlog "
     "faster. Throughput is essentially unchanged and lag has if anything got worse since we "
     "did it. That doesn't match my mental model at all. What's the actual constraint here?"),
    ("q-c2-09", 3, MID, False,
     "why doesn't adding consumer instances buy us any more throughput?"),

    ("q-c2-10", 1, TERSE, True,
     "partner API calls work locally, fail once deployed"),
    ("q-c2-10", 2, VERBOSE, False,
     "I can hit the partner's API from my laptop all day long, but the identical code "
     "running in the deployed environment can't complete the call. Same credentials, same "
     "endpoint, same library version. Textbook works-on-my-machine. Can you tell me what "
     "differs out there?"),
    ("q-c2-10", 3, MID, False,
     "outbound calls to the partner fail from the deployed workload but are fine from my desk"),

    # -------------------------------------------------------------- cat 3: error_string
    ("q-c3-01", 1, TERSE, False,
     "TypeError: Descriptors cannot not be created directly, right after a reinstall"),
    ("q-c3-01", 2, VERBOSE, False,
     "I blew away my virtualenv and reinstalled everything, and now importing our generated "
     "stubs dies immediately with TypeError: Descriptors cannot not be created directly. It "
     "was fine before the reinstall and a colleague on an older environment still can't "
     "reproduce it. What do I do?"),
    ("q-c3-01", 3, MID, False,
     "importing the generated code now fails with TypeError: Descriptors cannot not be created directly, fix?"),

    ("q-c3-02", 1, TERSE, False,
     "build stage exits 137 with no message"),
    ("q-c3-02", 2, VERBOSE, False,
     "One stage of the build runs for several minutes and then just stops with exit code "
     "137 and nothing else in the log. No traceback, no error text, no failing test. The "
     "same stage passes on my machine. What is that actually telling me?"),
    ("q-c3-02", 3, MID, True,
     "one build stage keeps dying late with nothing useful in the log, can you work out why?"),

    ("q-c3-03", 1, TERSE, False,
     "SSLCertVerificationError from the deployed workload"),
    ("q-c3-03", 2, VERBOSE, False,
     "Calls from our deployed workload are failing with SSLCertVerificationError and "
     "certificate verify failed: unable to get local issuer certificate. The very same "
     "request from my machine goes through without complaint. What is the deployed "
     "environment missing?"),
    ("q-c3-03", 3, MID, False,
     "getting certificate verify failed: unable to get local issuer certificate only when deployed"),

    ("q-c3-04", 1, TERSE, False,
     "tests dying with sqlite3.OperationalError: database is locked"),
    ("q-c3-04", 2, VERBOSE, False,
     "Partway through the suite a batch of tests starts failing with "
     "sqlite3.OperationalError: database is locked, and it isn't the same tests each time. "
     "If I rerun just the failures on their own they pass. Something is contending and I "
     "can't see what."),
    ("q-c3-04", 3, MID, False,
     "database is locked hits us mid-suite on different tests every run, what's contending?"),

    ("q-c3-05", 1, TERSE, False,
     "OSError: [Errno 98] Address already in use when I rerun the tests"),
    ("q-c3-05", 2, VERBOSE, False,
     "If I stop the test suite and start it again immediately I get OSError: [Errno 98] "
     "Address already in use. Waiting half a minute and trying again works fine, but having "
     "to wait is a real drag on the loop. Can this be made robust instead?"),
    ("q-c3-05", 3, MID, True,
     "rerunning the suite straight after stopping it fails because something still has the port"),

    ("q-c3-06", 1, TERSE, False,
     "symbol lookup error, undefined symbol, on import"),
    ("q-c3-06", 2, VERBOSE, False,
     "The package installed without a single warning, but importing it on our own hardware "
     "aborts with a symbol lookup error complaining about an undefined symbol. The hosted "
     "runners import the very same thing without trouble. What's different about our boxes?"),
    ("q-c3-06", 3, MID, False,
     "import aborts with undefined symbol on our own machines despite a clean install, why?"),

    ("q-c3-07", 1, TERSE, False,
     "json.decoder.JSONDecodeError: Extra data reading our export"),
    ("q-c3-07", 2, VERBOSE, False,
     "I'm trying to load one of our export files and it fails immediately with "
     "json.decoder.JSONDecodeError: Extra data. The beginning of the file looks like "
     "perfectly good JSON when I eyeball it, so I don't think it's corrupt. What am I "
     "actually dealing with?"),
    ("q-c3-07", 3, MID, False,
     "getting Extra data out of JSONDecodeError when I parse the export in one go"),

    ("q-c3-08", 1, TERSE, False,
     "ConnectionResetError [Errno 104] talking to the object store"),
    ("q-c3-08", 2, VERBOSE, False,
     "Every so often a request to the object store fails with ConnectionResetError: [Errno "
     "104] Connection reset by peer. It seems to happen when the process has been quiet for "
     "a while and then goes to do something. Never under sustained load. Can you make this "
     "stop?"),
    ("q-c3-08", 3, MID, False,
     "Connection reset by peer on object store calls after the connection has been idle"),

    ("q-c3-09", 1, TERSE, False,
     "service won't boot, says found duplicate key"),
    ("q-c3-09", 2, VERBOSE, False,
     "The deployed service refuses to come up and the only thing in the log is a found "
     "duplicate key complaint about its configuration. The identical config file loads "
     "without a murmur when I run the thing locally. Which of the two is right, and how do "
     "I get it started?"),
    ("q-c3-09", 3, MID, False,
     "found duplicate key on boot in the deployed environment, but it loads clean on my machine"),

    ("q-c3-10", 1, TERSE, False,
     "OSError: [Errno 24] Too many open files during a big import"),
    ("q-c3-10", 2, VERBOSE, False,
     "A large import gets maybe forty percent of the way through and then everything starts "
     "failing with OSError: [Errno 24] Too many open files. Small imports are completely "
     "fine. I assume we're leaking handles somewhere in that loop. Can you find it?"),
    ("q-c3-10", 3, MID, True,
     "big import runs fall over partway with file errors everywhere, small ones are fine"),

    # ------------------------------------------------------------------ cat 4: polarity
    ("q-c4-01", 1, TERSE, False,
     "we're on 4.3, can the exporter use the streaming path?"),
    ("q-c4-01", 2, VERBOSE, False,
     "The exporter buffers the entire result set before it writes anything, which is why "
     "it's such a memory hog. There's a streaming interface I'd much rather use instead. We "
     "are running 4.3. Is that a viable move for us now or not?"),
    ("q-c4-01", 3, MID, False,
     "thinking of switching the exporter to streaming on 4.3, go or no go?"),

    ("q-c4-02", 1, TERSE, True,
     "can we run the tests in parallel to speed this up?"),
    ("q-c4-02", 2, VERBOSE, False,
     "The suite takes eleven minutes and it is destroying my iteration speed. I want to run "
     "it with several workers locally so I get an answer in two or three. Is that supported "
     "here, or is it going to fall over in some ugly way?"),
    ("q-c4-02", 3, MID, False,
     "is running our test suite concurrently for a faster local loop actually supported?"),

    ("q-c4-03", 1, TERSE, False,
     "calling the cache from inside the request handler, we're on the 3.x client"),
    ("q-c4-03", 2, VERBOSE, False,
     "I want to add a cache lookup right in the hot request path, and we're on the 3.x "
     "client. Is doing that once per request from inside the handler an acceptable thing to "
     "do here, or is it going to bite us the moment we get real traffic?"),
    ("q-c4-03", 3, MID, False,
     "on the 3.x client, is a per-request cache call inside the handler fine?"),

    ("q-c4-04", 1, TERSE, True,
     "thinking about arm runners, they're cheaper"),
    ("q-c4-04", 2, VERBOSE, False,
     "CI spend is up again and arm runners are noticeably cheaper per minute than what we're "
     "on. I'd like to move our image builds across to them. Is that going to work for us, "
     "and what's the catch I'm not seeing?"),
    ("q-c4-04", 3, MID, False,
     "would moving our image builds onto arm runners actually work here?"),

    ("q-c4-05", 1, TERSE, True,
     "want to drop that deprecated field from the event payload"),
    ("q-c4-05", 2, VERBOSE, False,
     "There's a field in our event payload that has been marked deprecated for well over a "
     "year and nothing in our own code reads it any more. I'd like to finally take it out. "
     "Can I just delete it, or is there something standing in the way?"),
    ("q-c4-05", 3, MID, False,
     "am I clear to remove the long-deprecated field from the event schema?"),

    # q-c4-06 .. q-c4-09 are historical_intent: ask about the past / the pinned old version
    ("q-c4-06", 1, TERSE, False,
     "we're still pinned at 4.1, was the streaming path usable on that version?"),
    ("q-c4-06", 2, VERBOSE, False,
     "We can't move off 4.1 for at least another quarter, so I need the answer that applies "
     "to 4.1 rather than the current one. I have a vague memory of there being something "
     "about the streaming interface on that release. What was the situation back then?"),
    ("q-c4-06", 3, MID, False,
     "what did we know about streaming at 4.1, the version we're pinned to?"),

    ("q-c4-07", 1, TERSE, False,
     "why did we abandon arm runners last time?"),
    ("q-c4-07", 2, VERBOSE, False,
     "Someone mentioned in passing that we tried moving to arm runners a while back and it "
     "didn't stick. Before I go and propose it all over again I'd like the history: what "
     "went wrong then, and who called it off?"),
    ("q-c4-07", 3, MID, False,
     "there was an earlier attempt at arm runners that got dropped, what was the reason?"),

    ("q-c4-08", 1, TERSE, False,
     "we're on the 2.x client, what was the guidance on calling it per request?"),
    ("q-c4-08", 2, VERBOSE, False,
     "This service never got upgraded and is still on the 2.x client. I know the advice "
     "about calling it inside the request path changed at some point. What was the rule "
     "while we were on 2.x, since that's the one that applies to me?"),
    ("q-c4-08", 3, MID, False,
     "back on the 2.x client, was calling it once per request considered acceptable?"),

    ("q-c4-09", 1, TERSE, True,
     "where did the run-the-tests-serially rule come from?"),
    ("q-c4-09", 2, VERBOSE, False,
     "In review today somebody asked why our docs tell people to run the suite serially, "
     "and nobody in the room could remember the origin. I'd like the history rather than a "
     "recommendation: who wrote that down, and what were they reacting to at the time?"),
    ("q-c4-09", 3, MID, False,
     "what was the original reason behind our serial-only testing guidance?"),

    ("q-c4-10", 1, TERSE, True,
     "our payloads are huge, can we trim anything?"),
    ("q-c4-10", 2, VERBOSE, False,
     "The event payloads have grown to the point where they're a real cost line rather than "
     "a rounding error. I want to know what's in them that nobody actually needs, and "
     "whether we're even allowed to take things out. Where do I start looking?"),
    ("q-c4-10", 3, MID, False,
     "payload size has crept way up, is dropping unused fields on the table?"),

    # --------------------------------------------------------------- cat 5: over_length
    ("q-c5-01", 1, TERSE, True,
     "connect_timeout_ms seems to have no effect"),
    ("q-c5-01", 2, VERBOSE, False,
     "I'm passing connect_timeout_ms on the call and it makes no observable difference: "
     "connections still hang for what feels like whatever the default is. I've checked the "
     "spelling and confirmed it's reaching the client. Why is it being ignored?"),
    ("q-c5-01", 3, MID, False,
     "set connect_timeout_ms per call and the timeout behaviour didn't change, what gives?"),

    ("q-c5-02", 1, TERSE, True,
     "query filtering on tenant_id won't use the index"),
    ("q-c5-02", 2, VERBOSE, False,
     "There's a composite index whose leading column is tenant_id, and the planner flatly "
     "refuses to use it for one particular query, seq scanning the whole table instead. "
     "Other queries against the same table use it happily. Can you work out why this one is "
     "different?"),
    ("q-c5-02", 3, MID, False,
     "why would the planner skip our composite index on a tenant_id filter?"),

    ("q-c5-03", 1, TERSE, True,
     "where does the batch job get its secrets in prod?"),
    ("q-c5-03", 2, VERBOSE, False,
     "I'm debugging the deployed batch job and I can't work out where its credentials come "
     "from. They're not in the environment variables I expected and they're not in the "
     "config file either, yet it clearly authenticates fine. How does it get them when it "
     "runs for real?"),
    ("q-c5-03", 3, MID, False,
     "how does the deployed batch job actually source its secrets?"),

    ("q-c5-04", 1, TERSE, True,
     "upload failed and didn't retry at all"),
    ("q-c5-04", 2, VERBOSE, False,
     "An upload failed and from the logs it made exactly one attempt and then gave up, even "
     "though I was fairly confident we had retries configured on that path. Nothing waited, "
     "nothing tried again. Is retrying actually wired up here or have I imagined it?"),
    ("q-c5-04", 3, MID, False,
     "an upload gave up on the first failure with no second attempt, should it have retried?"),

    ("q-c5-05", 1, TERSE, True,
     "changed the template but the old version is still going out"),
    ("q-c5-05", 2, VERBOSE, False,
     "I edited the template, deployed it, and recipients are still getting the previous "
     "wording. I've confirmed my change is present in the deployed artefact, so something "
     "downstream is still serving the old rendering. How do I get my edit to actually take "
     "effect?"),
    ("q-c5-05", 3, MID, False,
     "template edit is deployed but the previous copy keeps being sent, what's serving it?"),

    ("q-c5-06", 1, TERSE, True,
     "signature checks fail now and then, only on our own boxes"),
    ("q-c5-06", 2, VERBOSE, False,
     "Signature validation fails maybe one request in fifty, and only on the self-hosted "
     "machines, never on the managed ones. Same code, same keys as far as I can tell, and "
     "the failures don't cluster around deploys. What differs about our own hardware?"),
    ("q-c5-06", 3, MID, False,
     "intermittent signature validation failures confined to our own hardware, where do I look?"),
]

# Near-miss twins: {stub_id: identifier that must NOT appear in that stub's prompts}
# (Substring containment in the other direction is inherent -- "v2.3.10" contains
# "v2.3.1" -- and is the trap itself, so only the one-way exclusion is checkable.)
FORBIDDEN_TWIN = {
    "q-c1-01": "WidgetV2",
    "q-c1-02": "WidgetV1",
    "q-c1-03": "v2.3.10",
    "q-c1-05": "conf_test.py",
    "q-c1-06": "conftest.py",
    "q-c1-07": "AUTH_TOKEN_V2",
    "q-c1-09": "build.gradle.kts",
    "q-c1-11": "userId",
    "q-c1-12": "user_id",
    "q-c1-13": "--no-cache-dir",
    "q-c1-15": "staging-2",
    "q-c1-17": "retry_backoff_ms",
    "q-c1-19": "parse_datetime",
    "q-c1-21": "org.example.config.Core",
    "q-c1-22": "org.example.core.Config",
    "q-c1-23": "DATABASE_URL_RO",
    "q-c1-25": "300 seconds",
    "q-c1-27": "0042_1",
    "q-c4-01": "4.1",
    "q-c4-03": "2.x",
    "q-c4-06": "4.3",
    "q-c4-08": "3.x",
}


def main() -> int:
    stubs = json.loads(STUBS.read_text())["stubs"]
    by_id = {s["stub_id"]: s for s in stubs}

    errs: list[str] = []

    # 1. structural: exactly 3 variants per stub, numbered 1-3, no extras
    seen: dict[str, set[int]] = {}
    for stub_id, variant, _style, _under, text in ROWS:
        if stub_id not in by_id:
            errs.append(f"unknown stub_id {stub_id}")
            continue
        seen.setdefault(stub_id, set()).add(variant)
        if not text.strip():
            errs.append(f"{stub_id} v{variant}: empty text")
    for stub_id in by_id:
        got = seen.get(stub_id, set())
        if got != {1, 2, 3}:
            errs.append(f"{stub_id}: variants {sorted(got)}, expected [1, 2, 3]")

    # 2. no duplicate prompt text anywhere
    texts: dict[str, str] = {}
    for stub_id, variant, _s, _u, text in ROWS:
        norm = " ".join(text.lower().split())
        if norm in texts:
            errs.append(f"{stub_id} v{variant}: duplicate of {texts[norm]}")
        texts[norm] = f"{stub_id} v{variant}"

    # 3. the paired twin identifier never bleeds into its sibling's prompts
    for stub_id, variant, _s, _u, text in ROWS:
        bad = FORBIDDEN_TWIN.get(stub_id)
        if bad and bad.lower() in text.lower():
            errs.append(f"{stub_id} v{variant}: leaks twin identifier {bad!r}")

    # 4. identifier coverage -- reported, not enforced: some variants omit an identifier
    #    on purpose (underspecified prompts), which is the point.
    coverage: dict[str, dict[str, int]] = {}
    for stub_id, stub in by_id.items():
        rows = [r for r in ROWS if r[0] == stub_id]
        for ident in stub["identifiers_involved"]:
            n = sum(1 for r in rows if ident.lower() in r[4].lower())
            coverage.setdefault(stub_id, {})[ident] = n
        # every stub with identifiers must land at least one of them somewhere
        if stub["identifiers_involved"] and not any(coverage[stub_id].values()):
            errs.append(f"{stub_id}: no identifier appears in any variant")

    # 5. register really is differentiated: terse < mid < verbose on mean word count
    wc = {TERSE: [], MID: [], VERBOSE: []}
    for _sid, _v, style, _u, text in ROWS:
        wc[style].append(len(text.split()))
    means = {k: statistics.mean(v) for k, v in wc.items()}
    if not (means[TERSE] < means[MID] < means[VERBOSE]):
        errs.append(f"register word counts not ordered terse<mid<verbose: {means}")

    if errs:
        for e in errs:
            print("FAIL:", e, file=sys.stderr)
        return 1

    queries = []
    for stub_id, variant, style, under, text in ROWS:
        stub = by_id[stub_id]
        queries.append({
            "query_id": f"{stub_id}-v{variant}",
            "stub_id": stub_id,
            "variant": variant,
            "text": text,
            "variant_style": style,
            "underspecified": under,
            # denormalised from the stub for convenience; stubs_v2.json remains authoritative
            "trap_category": stub["trap_category"],
            "intent": stub["intent"],
        })

    out = {
        "schema_version": 1,
        "source_stubs": "stubs_v2.json",
        "n_stubs": len(by_id),
        "variants_per_stub": 3,
        "n_queries": len(queries),
        "authoring": {
            "blindfold": (
                "Authored from stubs_v2.json and README.md alone. dataset.json, "
                "dataset_src/, results/ and research/embedder-benchmark-results.md were "
                "not opened, so no phrasing could be tuned against memory prose."
            ),
            "variant_1": "terse -- a clause, lowercase, minimal ceremony, often missing context",
            "variant_2": "verbose -- multi-sentence, includes the story and what was ruled out",
            "variant_3": "mid -- one sentence, entered from a different angle than variant 1 "
                         "(sanity check or 'is X involved' rather than a task statement)",
            "underspecified": (
                "True where a cue a careful author would have supplied is deliberately "
                "withheld (the exact error string, the distinguishing symptom detail). v1 "
                "oversampled well-specified prompts; these sample the other tail."
            ),
            "resolution_leakage": (
                "No prompt names a fix. Prompts state symptom, intent, and what the user "
                "already checked. Asserted user beliefs are ones the stub situation implies."
            ),
            "historical_intent": (
                "q-c4-06..q-c4-09 ask about the past or about the old pinned version in all "
                "three variants, never 'what should I do now'."
            ),
        },
        "register_mean_words": {k: round(v, 1) for k, v in means.items()},
        "identifier_coverage": coverage,
        "queries": queries,
    }
    OUT.write_text(json.dumps(out, indent=2) + "\n")

    n_under = sum(1 for q in queries if q["underspecified"])
    print(f"wrote {OUT.relative_to(HERE.parent.parent)}: {len(queries)} queries "
          f"over {len(by_id)} stubs")
    print(f"register mean words: " + ", ".join(f"{k}={v:.1f}" for k, v in means.items()))
    print(f"underspecified variants: {n_under}/{len(queries)}")
    full = sum(1 for sid, cov in coverage.items()
               if all(n == 3 for n in cov.values()))
    partial = len(coverage) - full
    print(f"identifier coverage: {full} stubs with every identifier in all 3 variants, "
          f"{partial} with deliberate omissions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
