# Review — M28–M30 distribution briefs

Artifacts under review, as one body of work:

- `design/build-plan.md` §§M28, M29, M30 (read together with §M27).
- `FINDINGS.md` §"How Zikaron is obtained — six decisions, and the three milestones they produce".

Every number below was re-derived from the tree rather than taken from either document, per the brief.
Where a figure could not be reproduced from the working tree the reason is stated.

## Round 1 — 2026-09-21

**Summary judgment.** The two artifacts agree with each other almost everywhere, match M27's brief
format, and the sweep counts reproduce exactly once the tool difference is understood (`git grep`
searches two tracked `.log` files that `.gitignore`'s `*.log` hides from ripgrep-family tools — 17
files / 61 hits by that route, 19 / 76 by the brief's). But four things are wrong in the direction
that matters: a headroom figure that does not follow from its own operands and sits in three
documents; a "the design was already safe" claim about the socket path that is false on the branch
the research note's own macOS convention takes; a publication sweep with no secret-shaped pattern,
in a tree whose tracked spike logs are environment dumps carrying a credential-shaped harness token;
and an allowlist mechanism in M30 that, against how `fastembed` actually acquires files, re-downloads
64 MB on every service start forever the first time upstream pushes a commit. Not ready as-is.

### Findings

1. **[BLOCKER] "45 bytes of headroom" is not the difference of its own operands, and it is stated in
   three places.** `design/build-plan.md` §M29 §"The `sun_path` limit…": *"Against macOS's 103 usable
   bytes that is 45 bytes of headroom"*; `FINDINGS.md` §"How Zikaron is obtained" (b): *"That is 45
   bytes of headroom"*; and the source, `research/python-portability-probes.md` §8 item 1: *"45 bytes
   of headroom on the macOS branch"*. Re-derived from `zikaron/service/paths.py`: `/tmp/zikaron-1000/`
   is 18 bytes, plus 32 hex, plus `.sock` = **55**; 103 − 55 = **48**. (60 on the XDG branch is
   correct: `/run/user/1000/zikaron/` = 23 + 32 + 5.) No subtraction of 55 or 60 from 103 or 104
   yields 45. Fix all three sites to 48 and, since uid width is the only thing that moves it, say so:
   uid 501 (macOS's first user) gives 54/49, a ten-digit uid gives 61/42.
   **Also in the same sentence: the lock path is not subject to `sun_path` at all.** `lock_path` is an
   ordinary file opened for `flock` (`paths.py` docstring: *"The `flock` target guarding
   start-if-absent"*); `sun_path` bounds only what is passed to `bind()`. So *"the lock path adds
   five"* is not a bound consumer, and M29 done-when 2's *"a test asserts the socket and lock paths
   fit 103 bytes"* tests a non-constraint for half its subject. Drop the lock path from the bound
   and from the test, or state that it is tested only for tidiness.

2. **[BLOCKER] "The design was already safe" is true of the hash and false of the path.** M29
   §"The `sun_path` limit…" and FINDINGS (b) both argue safety from *"the store path is hashed to
   32 hex characters, never embedded, so no project nesting depth can move this number"*. Correct
   for the store path. But `runtime_dir(xdg_runtime_dir=…)` prepends `$XDG_RUNTIME_DIR` verbatim,
   and that input is unbounded and user-controlled. The convention
   `research/python-distribution-portability.md` §5 found in the wild — `$TMPDIR/runtime-$UID` on
   macOS — gives `/var/folders/zz/<30 chars>/T/runtime-501/zikaron/<32 hex>.sock`: 49 + 12 + 8 + 32
   + 5 = **106 bytes > 103**, i.e. `OSError: AF_UNIX path too long` at bind for any macOS user who
   set the variable the way the note describes. The brief even notes that convention *"would be
   longer"* and then reasons only about the branch where nobody set it. Required changes: (a) M29's
   claim becomes *"the fallback branch is safe by construction; the XDG branch is bounded only by
   what the user exports"*; (b) done-when 2 gains: `socket_path` (or the bind site) refuses an
   over-length path with a `bad_config`-class error naming `XDG_RUNTIME_DIR` and the remedy, rather
   than letting `bind()` raise a bare `OSError` — "reject, never repair" is `architecture.md`
   §"Filesystem security"'s own rule, so refusing rather than silently falling back to
   `/tmp/zikaron-<uid>` is the consistent choice, and the brief should *decide* it now rather than
   have the milestone stop on it under its own fence; (c) the test takes a long `xdg_runtime_dir`
   argument (the function already takes it as a parameter, so no environment mutation) and asserts
   the refusal, plus the 103-byte fit on the fallback branch with a ten-digit uid. Propagate the
   correction to FINDINGS (b) and to `research/python-portability-probes.md` §8.

3. **[BLOCKER] The publication sweep has no secret- or identifier-shaped pattern, and the tree has
   environment dumps of harness-spawned processes in tracked files.** M28 §"The sweep" sweeps five
   path strings and an email address, then takes the position *"accept the history as it stands,
   redact nothing retroactively"*. Measured: `spikes/claude-code-harness/mcp.log:8` and
   `spikes/claude-code-harness/hook.log:11,27,42,57` are per-process environment dumps carrying
   `CLAUDE_CODE_MESSAGING_TOKEN=<32 hex>` alongside `CLAUDE_CODE_MESSAGING_SOCKET`,
   `CLAUDE_CODE_SESSION_ID` and `CLAUDE_CODE_EXECPATH`; `research/kiro-mcp-lifecycle-probe.jsonl`
   (21 lines) and `research/kiro-session-id-probe.jsonl` (5 lines) are full kiro environ dumps —
   the `/proc/<pid>/environ` reads FINDINGS D31 describes — carrying `KIRO_USER_ID`,
   `KIRO_TELEMETRY_CLIENT_ID` and `KIRO_TUI_READY_TOKEN`. A session-scoped messaging token is
   plausibly dead and a builder id is an identifier rather than a secret, but the brief cannot say
   either today because it never looked, and *"accept history"* was taken without this class on the
   table. (The two spike logs are also the *"`spikes/` (2)"* in the `/home/nathan` count, and they
   are tracked despite `.gitignore`'s `*.log` — which is why a ripgrep-family sweep reports 17 files
   / 61 hits against the brief's 19 / 76. Say that in the brief: it is the reason the sweep must be
   `git grep`, and the reason a future tool-based sweep will silently under-count.)
   Required: add rows to the sweep table for (i) env-dump signatures in tracked `.log`/`.jsonl`
   (`^\s*[A-Z][A-Z0-9_]+=` and `"[A-Z][A-Z0-9_]+":`), (ii) `TOKEN|KEY|SECRET|PASSWORD|CLIENT_ID|USER_ID`,
   (iii) 32/40/64-hex runs and `-----BEGIN`; record the counts; for each hit state whether the value
   is live; and re-take the accept-history decision with the operator on that evidence. Done-when 7's
   *"any hit inside `zikaron/` is a blocker"* should extend to *"any live credential anywhere"*.
   `.gitignore` already names `*.pem`/`*.key`/`.env*`, and `.claude/settings.json`'s deny list shows
   the project knows the class — the sweep just does not run it.

4. **[BLOCKER] M30's allowlist remedy diverges on the one mismatch cause that is not local
   corruption.** §"The pinned artefacts" and done-when 4: *"the file deleted on mismatch so the next
   run re-downloads rather than failing forever"*. Read against the installed library
   (`.venv/lib/python3.12/site-packages/fastembed/common/model_management.py`): `download_model`
   tries `local_files_only=True` first (lines 412–425), and on a miss `download_files_from_huggingface`
   resolves `model_info(repo).sha` — the repository's *current head* — and `snapshot_download`s it
   (235–264); `TextEmbedding` forwards no `revision` (`text/onnx_embedding.py:252–257` passes only
   `local_files_only` and `specific_model_path`). So the first time `qdrant/bge-small-en-v1.5-onnx-q`
   pushes a commit, every install's next service start deletes 64 MB, re-fetches the same
   non-matching bytes, and does it again at the next start — the exact *"failing forever"* the
   sentence claims to avoid, now with a 64 MB download attached to each attempt. Delete-and-retry
   covers only a corrupt local copy, which is all done-when 4's test covers. Required: (a) pin the
   HF **revision** beside the hashes and let Zikaron own acquisition —
   `huggingface_hub.snapshot_download(repo_id, revision=<sha>, allow_patterns=[…], cache_dir=<durable>)`
   (`huggingface_hub` is already a transitive dependency), verify the allowlist, then
   `TextEmbedding(model_name, specific_model_path=<dir>)`, which fastembed 0.8.0 supports
   (`onnx_embedding.py:209`); (b) bound the re-fetch to **one** per process and make a second
   mismatch a named failure carrying the remedy (*"artefact at revision X differs from the pinned
   hash — upgrade zikaron"*), never another download; (c) rewrite done-when 4 to prove both branches:
   corrupt-local → one re-fetch, green; upstream-differs → red once, loudly, no loop; (d) retire
   *"~20 lines"*. This is also what makes *"pinning `tokenizer.json` makes the bounds provable"* true
   — a hash without a pinned revision proves only that the fetch will fail.

5. **[IMPROVEMENT] M30 cites a section that does not exist.** M30 Normative line:
   *"`design/harness.md` §"The install contract" is re-read…"*. `harness.md` has no such section
   (its headings run §"The installer's two targets", §"What a Claude Code install writes", …); the
   section is `design/architecture.md` §"The install contract" (line 2029), which `harness.md` itself
   refers to by that name. A fresh session executing the brief cannot resolve the pointer. Cite
   `architecture.md` §"The install contract" and `harness.md` §"The installer's two targets".

6. **[IMPROVEMENT] The gate script itself is the first thing the macOS job will hit, and neither
   brief names it.** `check.sh:91` wraps pytest in GNU `timeout`; macOS ships no such binary. Whether
   the GitHub macOS image provides `coreutils` via Homebrew is a fact to read off the image's
   software manifest, not assume — and if it is absent, M28's advisory job dies at the gate script
   before one test runs, so M28 lands having built no instrument for M29 while reporting the job
   "advisory red" as expected. M29 §"Everything else is 'run it and see'" lists four candidates and
   not this one, though it is knowable by reading. Required: M28 done-when 4 gains a macOS-only
   workflow step that guarantees `timeout` (`brew install coreutils` plus gnubin on `PATH`), which is
   workflow-only and inside the fence; M29's candidate list gains *"the gate script's own
   portability — `timeout`, `bash` version, `rm -f` globbing"*; and §"What CI can and cannot prove"'s
   *"nothing installed but Python and the dependencies"* becomes *"…plus `git`, GNU `timeout`, and
   network access to Hugging Face for the first model fetch"*.

7. **[IMPROVEMENT] Where the four jobs' interpreters come from is unstated, and it decides what the
   macOS evidence is evidence of.** M28 done-when 4 says *"runs `check.sh` on Linux for 3.12, 3.13
   and 3.14, and on the arm64 macOS runner for one version"*; `check.sh` needs `.venv` (or
   `ZIKARON_VENV`) with the dev pins, and nothing says how it is built. It matters twice:
   `enable_load_extension` is compile-time (`research/python-distribution-portability.md` §1:
   python.org macOS builds historically off, `actions/setup-python` builds unverified in this
   corpus), and `uv tool install` users get python-build-standalone builds, which probe §4 already
   verified. Specify the recipe `CLAUDE.md` §"Setting up a development environment" already gives:
   `astral-sh/setup-uv` → `uv python install --no-bin <minor>` → `uv venv --seed --python <minor>
   .venv` → `.venv/bin/pip install -e '.[dev]'`. That makes CI run the interpreter family users get,
   mirrors `check-matrix.sh`'s first resolution source, and makes the Gatekeeper/`load_extension`
   run in §"What CI can and cannot prove" evidence about the right binary. Also name the one macOS
   version — the floor, 3.12, on wheel-availability grounds (`onnxruntime` cp314 arm64 wheels are
   unverified here) — or state another with its reason. And extend done-when 4's drift test to
   assert both deprecation env vars per job, since the brief's own argument for per-version jobs is
   that *"the env vars are per-job and have to be asserted rather than remembered"*.

8. **[IMPROVEMENT] M28 done-when 6 caches a path that is unknowable on macOS.** *"Cache that path in
   the workflow"* — the path is `tempfile.gettempdir()/fastembed_cache` (`define_cache_dir`,
   `fastembed/common/utils.py:48–59`), and on the macOS runner `tempfile.gettempdir()` is `$TMPDIR`
   = `/var/folders/…`, per-session, so `actions/cache` cannot name it at authoring time; on Linux it
   works by accident. Set `FASTEMBED_CACHE_PATH: ${{ github.workspace }}/.fastembed_cache` in the job
   env — fastembed already honours it, so this is workflow-only and inside the no-product-code fence
   — and cache that directory, keyed on model name **and the `fastembed` pin** (the layout is the
   library's). Then M30 done-when 7 (*"the CI model-cache key is revisited"*) is a no-op by
   construction, because M30 keeps `$FASTEMBED_CACHE_PATH` winning; say so in M30 rather than
   leaving an item whose answer is "nothing to do".

9. **[IMPROVEMENT] Done-when 5 asserts a UI property the brief cannot verify and chooses the setting
   whose purpose is the opposite.** *"The macOS job is advisory (`continue-on-error`) … and its
   redness is visible rather than hidden."* `continue-on-error`'s documented purpose is to let the
   run pass; whether the job itself still renders red in the checks list is exactly the kind of
   fact done-when 10 admits is untestable before the first push. Operationalise "visible": an
   `if: always()` step writes the macOS job's outcome and the word *advisory* to
   `$GITHUB_STEP_SUMMARY`; the drift test asserts that step exists; the first real run records in
   `design/distribution.md` what the checks UI actually showed. And name the alternative that needs
   no setting: a plainly failing job that is simply not a required check — there is no branch
   protection today, so nothing blocks on it either way.

10. **[IMPROVEMENT] M29's "one real risk" is answerable by reading, and the brief says it is not.**
    §"The absent `$XDG_RUNTIME_DIR`…": *"whether `security.py`'s vetting passes on macOS's `/tmp`, a
    symlink to `/private/tmp` … This is the one real risk in the milestone and it is a plausible
    blocker"*; done-when 3: *"settled by observation on the runner, not by reading"*.
    `ensure_runtime_dir` (`security.py:111–128`) calls `path.lstat()` on `/tmp/zikaron-<uid>` — the
    leaf — and refuses only if *that* entry is a symlink; `/tmp` is a parent component, which
    `lstat` traverses like `stat`. So by reading, the vet passes on macOS. Keep the runner
    confirmation in done-when 3, but restate the size: *"expected to pass by reading (`lstat` vets
    the leaf, not its parents); confirmed on the runner"*. As written, the brief mis-sizes a risk in
    the paragraph directly after FINDINGS criticises the corpus for *"a plausible worry restated
    across documents until its size was assumed"* — and the genuinely unread risks (findings 2 and
    6) are the ones it does not name.

11. **[IMPROVEMENT] `doctor`'s "five checks" are four checks and a report, and the cache check is
    red on every fresh install by the fence's own rule.** M30 §"The front door" lists:
    `enable_load_extension`; FTS5; `sqlite-vec` loading a `vec0` table; the model cache *"present and
    hash-verified"*; and *"the linked SQLite version printed beside the interpreter's"* — the fifth
    cannot fail, so done-when 2's *"exits non-zero when any fails"* covers four. And with no
    install-time prefetch (the fence), a stranger's first `zikaron doctor` reports the cache absent
    and exits non-zero before anything is wrong. Decide and state: four pass/fail checks plus one
    report; cache absent is *"not yet fetched — fetched on first service start"* at exit 0, present
    but hash-mismatched is a failure; or add `doctor --fetch` as the one sanctioned prefetch. Either
    is fine; unstated, the executor picks and the first user sees red.

12. **[IMPROVEMENT] The brief's six decisions carry fewer rejected alternatives than FINDINGS's
    index, and it is the brief that `design/distribution.md` will be written from.** FINDINGS's
    table records, per row, what was rejected and why — Interpreter: require uv outright, ship
    python-build-standalone; Publication: private repo + PyPI only, a public/private corpus split;
    Order: local work first, paid macOS minutes. M28 §"The six decisions" carries none of those
    three rows' rejections. The operator's rule is that a design document states what we are doing
    with rejected alternatives at the end; a session writing `distribution.md` from the brief will
    omit them, and the index — the document that is *not* normative — becomes the only record. Fold
    FINDINGS's "Rejected, and why" column into the brief's list.

13. **[IMPROVEMENT] M30 done-when 6 assigns the operator's act to the milestone and omits the
    packaging half of a release.** *"The PyPI release is published"* — publishing needs a PyPI
    credential and is the operator's under the same rule M28 done-when 10 applies to the push; say
    so and name the mechanism (trusted publishing from a release workflow, or `uv publish` from the
    operator's shell). Missing alongside it: `readme = "README.md"` and `[project.urls]` in
    `pyproject.toml` (absent today; M28 done-when 1 is the natural home, or the PyPI page is blank),
    and an assertion over the built sdist/wheel that no `research/`, `reviews/`, `.kiro/`,
    `FINDINGS*.md` or `experiments/` content ships (setuptools' defaults should exclude them; a test
    proves it).

14. **[IMPROVEMENT] M28 done-when 8 depends on a URL that done-when 10 says does not exist yet.**
    README must document `uv tool install git+…`; the remote's org/name is the operator's decision at
    the publishing step. Sequence it: the operator names the remote before done-when 8 is written,
    or README carries a placeholder the publishing commit replaces — and say which.

15. **[IMPROVEMENT] Done-when 1's "classifiers a publishable package needs" will send the executor
    to a deprecated combination.** With `setuptools==84.0.0` and PEP 639, the right shape is
    `license = "MIT"` (an SPDX expression) plus `license-files = ["LICENSE"]`, and **no**
    `License :: OSI Approved :: MIT License` classifier — setuptools ≥ 77 deprecates the classifier
    when a licence expression is present. State it so the item is executable without re-deriving
    the standard.

16. **[NITPICK] Done-when 3's site list does not match what its own grep returns.** The command
    returns eleven lines today: the seven sites, three lines in `build-plan.md` §M27/§M28, and
    `reviews/m27-python-range-code-review.md:350` — a quotation, not a site. Say *"lines in
    `reviews/` and in this file's own briefs are quotations, not sites"*, or the executor
    reconciles eleven lines against seven names.

17. **[NITPICK] "Two user-facing CLIs" — there is a third `__main__.py`.**
    `zikaron/knowledge/indexer/__main__.py` exists and is machine-spawned via `sys.executable -m`.
    Say it is deliberately not a console script, so the next reader does not re-derive the count as
    three.

18. **[NITPICK] Done-when 7's test will itself be a `/home/nathan` hit under `tests/`.** Assemble the
    pattern from fragments as M27's version-seam scanner does, or every later sweep counts the test.

19. **[NITPICK] The email row's pattern is unstated, and a naive regex returns six.**
    `spikes/spike_git_shapes.py:23,25`, `tests/test_knowledge_scan_git.py:44,434,463`,
    `tests/test_knowledge_git.py:45` — all `@example.invalid` placeholders. State the pattern (the
    operator's address, or a regex excluding `.invalid`/`.example`) so done-when 7's counts reproduce.

20. **[NITPICK] Two FINDINGS lines go stale on landing.** *"Nothing is built and nothing is
    reviewed"* is false once this round lands; and §"Owed to memory-assistant" omits the
    `onnxruntime` cutoff check the brief's decision 1 asks for (*"verify against PyPI's release
    history before quoting the number"*).

21. **[NITPICK] Singular vs plural.** M29: *"measurement has already retired the largest item"*;
    FINDINGS: *"Two of the three macOS items … are near-nothing"*. Both are true of what was
    measured; pick one phrasing.

22. **[NITPICK] Decision 4 cites probe §6 for the `git+` form; §6 measured a local tree.** Same
    artefact shape, different source; say *"measured on a local tree copy, the `git+` form differing
    only in where the source comes from"*.

23. **[NITPICK] Coverage under CI load is an expected first-run instability, and the brief should
    say so.** `fail_under = 95` against a measured, load-sensitive 96.85–98.07% spread; a two-core
    runner may land lower on the timing-dependent branches. Name it beside *"a red first run is
    expected work"* so nobody raises or lowers the floor from one CI run.

24. **[NITPICK] Done-when 10 should say which refs are pushed.** `backup-pre-rebase` and
    `backup-pre-rebase-2` exist; *"the one branch, no backup branches, no tags"* — or the operator
    decides, but the brief should put the question.

25. **[NITPICK] M28's Normative paragraph reads as if a CI row *is* the drift.** *"§9 gains a CI row
    beside `check.sh` and `check-matrix.sh` — a third definition of done is exactly the drift that
    section exists to prevent."* Done-when 3 says the opposite more clearly (*"not a third thing to
    run; the same claim with the tree identity supplied by the SHA"*). Rephrase the paragraph to
    match done-when 3, and have M28 name the sections `design/distribution.md` will carry
    (§"Platforms" at least), since M29's Normative line already points at one.

VERDICT: NEEDS_CHANGES

## Round 2 — 2026-09-21

**Summary judgment.** The four round-1 blockers are genuinely fixed and the numbers now agree across
all three documents: 55/60 B, 48/49/42 spare, ≈106 on the XDG convention, lock path dropped as a
consumer everywhere — every one re-derived from `paths.py` this round. The sweep counts reproduce
(19/76 = ripgrep's 17/61 plus 15 spike-log lines, mcp.log 6 and hook.log 9; done-when 3's grep returns
11 lines = 7 sites + 4 quotations). What is wrong now is in the prose written *to describe* the fixes
and in the interaction between two of my own round-1 findings: M28 done-when 10 was trimmed into two
paragraphs that say the same thing and one that contradicts both; M29's section heading and lead still
assert the pre-fix world its body withdraws; and M30 done-when 7's "no-op by construction" — which
round 1 told the author to write — is false once round 1's *other* fix pins a revision. Three
blockers, all cheap; not ready as-is.

**Corrections to round 1, in place.** (a) Finding 3 said the messaging token sits at "`mcp.log:8`";
it is on six lines of `mcp.log` (8, 20, 33, 45, 57, 69) and four of `hook.log`. The brief quotes no
count, so nothing in it is wrong — recorded so done-when 7's numbers are not reconciled against mine.
(b) Finding 3 called both kiro `.jsonl` files "full kiro environ dumps". One is; the other carries key
*names* only — finding 5 below. (c) Finding 8 said M30 done-when 7 would be a no-op; that was written
before finding 4 introduced the revision pin, and the two do not compose — finding 3 below. The author
applied both as given, so these are my defects landing in the artifact, and I am the one lodging them.

### Findings

1. **[BLOCKER] M28 done-when 10 now contains the same paragraph twice and a sentence that contradicts
   both.** `design/build-plan.md` §M28 done-when 10 (today lines 2732–2750). It opens *"the milestone
   brings the tree to a publishable state and stops"*, then (b) ends *"M28 is complete when the workflow
   has gone green on a real push … a session that lands them and stops has left M29 without the thing
   it was promised"*, and is followed by a second paragraph — *"**And that is this milestone's real
   risk, stated because the whole ordering rests on it.** M28's justification is …"* — that restates
   (b)'s last three sentences nearly verbatim. So the item tells the executor to stop and tells it that
   stopping is the failure. This is the trim the operator's instruction produced, and it is the fresh
   prose the brief's rubric warned about. Concrete edit: delete the second paragraph outright, and make
   (b) read: *"The workflow cannot be exercised before the first push, and the push is the operator's.
   So the session brings every locally-verifiable item to green, lands the files, and stops — and the
   milestone is not closed until the operator's push has produced a green run, which the session then
   records in `design/distribution.md` (done-when 5's first-run record). An instrument that has never
   run is not yet one; M29 does not start on a workflow that has not gone green."* That reconciles
   "stops" (the session) with "complete when green" (the milestone). While there: *"Every other
   done-when item above is verifiable locally; this one is not"* — done-when 5's UI record is not
   either; say "every other item except 5's first-run record".

2. **[BLOCKER] M29's heading and lead assert the position the body withdraws.** Heading (line 2769):
   *"### The `sun_path` limit is a comment defect, not a code defect"*; lead (2765–2767):
   *"measurement has already retired the largest item, which is why this brief leads with what is *not*
   here"*. The body of that same section (2805–2811) then decides *"an over-length socket path is
   refused, never repaired … **This is a product change and it touches Linux too**"*, and the fence
   carries a named exception for it. So the section's title says no code changes and its body schedules
   a code change on the identical subject — the top-of-section summary contradicted by the section,
   which is this corpus's purest two-sites shape, and exactly the neighbour class the rubric named. Edit:
   heading → *"### The `sun_path` limit: a comment defect on the branch macOS takes, an unbounded input
   on the other"*; lead → *"measurement retired the largest item **on the branch macOS takes** and
   exposed a small product change on the branch it does not, which is why this brief leads with what is
   not here and with the one thing that is"*.

3. **[BLOCKER] M30 done-when 7's "no-op by construction — confirm, do not change" is false, and it
   forbids the fix.** `design/build-plan.md` §M30 done-when 7 (3023–3026): *"M28 sets
   `FASTEMBED_CACHE_PATH` in the job environment and this milestone keeps that variable winning … so
   CI's cache path does not move. Confirm, do not change."* The *path* claim is true; the *key* claim is
   not. M28 done-when 6 keys the cache on model name + `fastembed` pin, and `actions/cache` saves only on
   a key **miss**. After M30, `snapshot_download(revision=R)` looks for `snapshots/R/`; if the cached
   content was populated at upstream head `H ≠ R` — upstream moved between M28's first population and
   M30's pin, or any later pin bump, which is every model bump forever — the key hits, `snapshots/R/` is
   absent, 64 MB downloads, and nothing is saved back because the key hit. Every job, every run, exactly
   the *"cost nobody measures until it is a bill"* the M28 paragraph names. My round-1 finding 8 said
   no-op before finding 4 pinned a revision; the original wording of this item — *"the CI model-cache
   key is revisited"* — was right and I talked the author out of it. Edit: done-when 7 → *"The CI cache
   key gains the pinned revision — `(model name, revision)`; the `fastembed` pin may leave the key since
   the on-disk layout is `huggingface_hub`'s, not fastembed's. The path stays `$FASTEMBED_CACHE_PATH`
   and does not move."* And M28 done-when 6 → *"keyed on the model name and the `fastembed` pin **until
   M30 pins a revision, which then joins the key**"*.

4. **[IMPROVEMENT] M28's prose paragraph on the model cache still describes the pre-fix world beside
   the fixed item.** §"What CI can and cannot prove", *"The model download is a per-job cost…"*
   (2639–2643): *"today caches under `tempfile.gettempdir()` … Cache **that path** in the workflow,
   keyed on the model name; M30's durable-cache fix then makes the key deliberate rather than
   incidental."* Done-when 6, two screens down, says that path is unnameable on macOS, sets
   `FASTEMBED_CACHE_PATH`, and keys on name **and** pin; finding 3 makes M30's contribution the revision,
   not the path. Rewrite: *"The embedder is 64 MB and, left to fastembed's default, lands under
   `tempfile.gettempdir()` — unnameable on the macOS runner. Done-when 6 sets `FASTEMBED_CACHE_PATH`
   and caches that directory, keyed on the model name and the `fastembed` pin; M30's revision pin joins
   the key."*

5. **[IMPROVEMENT] The credential table mis-describes one of its four files, and the family-1 pattern
   would not find it.** M28 §"The sweep" table (2559–2564) says `research/kiro-session-id-probe.jsonl`
   carries *"the same"* as the lifecycle probe, and the next sentence says *"All four are per-process
   environment dumps"*; FINDINGS (d) says *"FOUR TRACKED FILES ARE HARNESS ENVIRONMENT DUMPS … Verified
   independently here"*. Re-read this round: `kiro-mcp-lifecycle-probe.jsonl` carries a `kiro_env`
   **object with every value** (`"KIRO_TUI_READY_TOKEN": "77ef…"`, `"KIRO_USER_ID": "d-9067…"`) on all
   21 lines — the pattern `"KIRO_TUI_READY_TOKEN": "|"KIRO_USER_ID": "` matches 21 lines there and
   **0** in `kiro-session-id-probe.jsonl`, whose five lines carry an `env_kiro_keys` **list of names**
   plus one value, `env_KIRO_SESSION_ID`. So it is three dumps and a listing, and the only thing in the
   fourth that could be live is a uuid4 session id. This inherited my round-1 wording; the "verified
   independently" sentence in FINDINGS did not catch it either. It also matters for the sweep: family 1's
   second pattern `"[A-Z][A-Z0-9_]+":` matches the lifecycle file's keys, but in the session-id probe the
   JSON key is `"env_KIRO_SESSION_ID":` (lowercase-led) and the list items are followed by `,` or `]`,
   never `:` — so the family as written reports nothing in a file the table names. Edits: the table
   row → *"key names only (an `env_kiro_keys` list) plus the `KIRO_SESSION_ID` value"*; *"All four"* →
   *"Three are per-process environment dumps and the fourth is a key listing"*; FINDINGS (d) the same;
   and either widen the pattern to `"[A-Z][A-Z0-9_]+"` (any quoted upper-snake string, whatever follows)
   or say the listing is out of the class by construction.

6. **[IMPROVEMENT] M29's refusal names neither its site nor its limit, and one natural reading breaks
   the fence.** §"The `sun_path` limit…" (2805–2811) and done-when 2. *Site*: `paths.socket_path` is
   reached only from `hook/connect.py:376` and `mcp/connection.py:85`; the service takes `sock_path`
   from argv (`service/main.py` docstring line 3, `main()` at 401–414) and never computes it. A refusal
   placed "at bind" therefore fires *after* a client has run start-if-absent and spawned a service,
   which then dies — the client sees a spawn failure, not a `bad_config`. Put the check in the pure
   function (it cannot be skipped there; the two callers and the service all get the same answer), and
   say so. *Limit*: the brief says the error names *"the limit"* without saying which. CPython's
   `getsockaddrarg` refuses `len >= sizeof sun_path`, so usable is 103 on macOS and 107 on Linux. An
   executor following M27's "identical on every version" instinct will pick a single 103 — which
   tightens Linux by four bytes and makes the fence's *"nothing else Linux-visible moves"* false for a
   path that binds today. Decide it: per-platform, **as data** — a two-row table `{darwin: 104, linux:
   108}` keyed the way `asyncio_compat` keys its rows, taking the platform as a parameter so both rows
   are tested on Linux — and state that the fence's *"no Linux user is likely to have set"* holds only
   under that choice.

7. **[IMPROVEMENT] The three documents agree about the XDG branch except for two words that say the
   opposite of each other.** M29 §"The absent `$XDG_RUNTIME_DIR` already has a fallback" (2820–2821)
   still asserts the convention *"would be **longer** … and buys nothing"* as its live position; FINDINGS
   (b) (1283) says of those words *"'buy nothing' is refuted"*. Substantively both mean the same thing —
   as a *default* the convention buys nothing; as a *user export* it overflows — but on their face one
   document refutes what the other asserts, one screen from the passage each cites for it. Edit FINDINGS
   (b) to *"the fallback clause stands, and so does 'buys nothing' as a default; what is refuted is the
   inference that the XDG branch therefore needed nothing"*, or drop "buys nothing" from M29. One or the
   other.

8. **[IMPROVEMENT] `huggingface_hub` becomes a direct dependency and the brief treats "transitive" as
   settling it.** M30 §"The pinned artefacts" (2972–2975): *"`huggingface_hub` is already a transitive
   dependency"*. True — `fastembed/common/model_management.py:11` imports it — and not a licence:
   `coding-standards.md` §"`venv`, latest stable, pinned exactly" pins every **direct** dependency
   exactly, and the paragraph after it records that transitives are *not* pinned and drift between
   virtualenvs built on different days. Product code calling `snapshot_download` makes it direct;
   `pyproject.toml`'s `dependencies` names `fastembed==0.8.0` and no `huggingface_hub`. Add to
   done-when 4: *"`huggingface_hub` joins `[project] dependencies` with an exact pin (1.26.0 is what the
   tree resolves today)"*. The surface used — `snapshot_download(repo_id, revision=, cache_dir=,
   allow_patterns=, force_download=, local_files_only=)` — exists in both 0.x and 1.x, so the pin is
   about drift, not availability.

9. **[IMPROVEMENT] The pin must be the full 40-hex commit sha, and the warm path must be proved
   network-free — the brief says neither, and M17's budget is what is at stake.** Read against
   `huggingface_hub/_snapshot_download.py` (1.26.0): `REGEX_COMMIT_HASH` is `^[0-9a-f]{40}$`; a
   `revision` matching it skips `api.repo_info` entirely (line 264), the file listing comes from the
   on-disk `trees/<sha>.json` (384), and each `hf_hub_download` returns from the existing pointer
   before any request (`file_download.py` 1073–1085). So a warm start is **zero network calls** — but
   only for that form. A tag, branch or short sha takes `api.repo_info` on every service start: one
   HTTPS round-trip online, and offline a `DEFAULT_ETAG_TIMEOUT` = 10 s stall (`constants.py:36`)
   before the `refs/` fallback — on the cold-start path M17 fought for, once per session. Edits:
   §"The pinned artefacts" says *"the full 40-character commit sha, never a tag or a short form"*;
   done-when 4 gains *"a warm start with a complete cache makes no network call — asserted with
   `HF_HUB_OFFLINE=1` in the test, which turns any call into `OfflineModeIsEnabled`"*. (The listing
   cache is written by the same call; a cache populated by an older `huggingface_hub` lacks it and
   costs one `list_repo_tree` call, which offline **raises** — a second reason finding 8's pin matters.)

10. **[IMPROVEMENT] "Delete-and-retry is correct for a corrupt local copy" is not, against the cache
    layout — and the wrong version lands on the *other* branch's diagnosis.** M30 §"The pinned
    artefacts" (2969–2970) and done-when 4. `hf_hub_download` stores content at `blobs/<etag>` and
    makes `snapshots/<sha>/<file>` a symlink to it; when the blob exists and the pointer does not, it
    **re-links without downloading** (`file_download.py` 1233–1237). So "delete the file, call
    `snapshot_download` again" deletes the symlink, re-links the same corrupt blob, mismatches again,
    and reports *"artefact at revision X differs from the pinned hash — upgrade zikaron"* to a user
    whose disk is bad. The one re-fetch must be `snapshot_download(..., force_download=True)` — an
    existing destination is re-downloaded only under force (`_download_to_tmp_and_move`, 1909) — and no
    deletion of ours. Done-when 4's first-branch test corrupts through the snapshot path (writes reach
    the blob) and asserts one download then a pass; its second-branch test needs the **source** to
    serve the wrong bytes twice (a monkeypatched `hf_hub_download`, or a local `HF_ENDPOINT`), so the
    two diagnoses are proven *distinguishable*, not merely both present. As written, an executor who
    deletes would fail the first test and might "fix" it by relaxing it.

11. **[IMPROVEMENT] After M30, `$FASTEMBED_CACHE_PATH` is Zikaron's to honour, and the brief still
    credits fastembed.** §"The model on disk" (2952–2954): *"with `$FASTEMBED_CACHE_PATH` still winning
    if the user set it"*; done-when 7: *"keeps that variable winning"*. Once `specific_model_path` is
    passed, `download_model` returns it before consulting any cache (`model_management.py` 402–404), so
    fastembed never reads the variable on that path. State: Zikaron's resolver reads
    `FASTEMBED_CACHE_PATH` itself and passes it as `cache_dir`; the layout under it is
    `huggingface_hub`'s (`models--<org>--<name>/snapshots/<sha>/`), identical to what fastembed's own
    path writes today — which is the premise that makes M28's CI cache reusable at all, and is stated
    nowhere. Done-when 3's test then targets Zikaron's function, not `define_cache_dir`.

12. **[NITPICK] `doctor` check 4 predates the revision pin.** §"The front door" table row 4: *"present
    and hash-verified"*. With a revision pinned, "present" is `snapshots/<pinned sha>/` complete; a cache
    holding only some other revision is the *absent* case (exit 0, "not yet fetched"), not a mismatch.
    Say "present at the pinned revision and hash-verified".

13. **[NITPICK] FINDINGS's Model row omits the revision.** *"Durable per-user cache + a SHA256
    allowlist per file, including `tokenizer.json`"* — the trail paragraph at the end of the section has
    the revision pin, the index row does not. Add "at a pinned HF revision".

14. **[NITPICK] Wrong pointer for the `timeout` guarantee.** M28 §"What CI can and cannot prove":
    *"`timeout` is not on macOS (see M29)"*. The guarantee is M28's own done-when 4; M29 owns only the
    residual class. Point at done-when 4.

15. **[NITPICK] The sweep table is stale on landing by the brief's own hand.** The quoting sections now
    put `/home/nathan` in `design/build-plan.md` five times (was 1 at `HEAD`) and in `FINDINGS.md`
    twice (was 1); the other four rows move by one or two the same way. "At `HEAD`" keeps the table
    true today; add to done-when 7 that the two quoting documents are expected to move the `design/` and
    `FINDINGS.md` counts and are reconciled rather than treated as new exposure — the same reason the
    test assembles its patterns from fragments.

VERDICT: NEEDS_CHANGES

## Round 3 — 2026-09-21

**Summary judgment.** All three round-2 blockers are fixed and none of the fixes re-opened anything: M28
done-when 10 now reconciles session and milestone in (b); M29's heading and lead match its body; M30
done-when 7 keys on the revision with the save-on-miss reasoning recorded. Every mechanical claim the
rubric named was re-derived this round and holds — `REGEX_COMMIT_HASH` is `^[0-9a-f]{40}$` and a match
skips `api.repo_info` (`_snapshot_download.py:253–264`); `force_download` is the only thing that
re-downloads an existing blob (`file_download.py:1084`, `:1233`, `:1909`); `huggingface_hub` in `.venv`
is 1.26.0; CPython's `len >= sizeof sun_path` gives 103/107 usable. **No blocker remains.** What is left
is six improvements — two of which would produce a hollow or subtly wrong build if an executor took the
brief literally — and five nitpicks. Every one is a bounded prose edit. Ranked by build consequence in
the list below; the operator can reasonably ship with 1–2 applied and the rest recorded.

**Corrections to round 2, in place.** (a) Finding 9 said a non-hash revision stalls offline on "a
`DEFAULT_ETAG_TIMEOUT` = 10 s" before the `refs/` fallback. For `snapshot_download`'s `repo_info` call
the constant is `DEFAULT_REQUEST_TIMEOUT` (`constants.py:38`), also 10 s, so the number stands and the
name does not; and under `HF_HUB_OFFLINE=1` there is no stall at all — `OfflineModeIsEnabled` is raised
immediately and caught at `:274`. The stall is the network-down case. M30 (ii) copied my wording;
nitpick 10 below carries the one-clause edit. (b) Finding 11 said fastembed "never reads the variable"
once `specific_model_path` is passed. It reads it *and creates the directory* — finding 3 below. The
author applied both as given; both are mine.

### Findings

1. **[IMPROVEMENT — the fix's stated benefit does not reach the caller it was argued from.** M29
   §"Two specifics" (a), lines 2834–2839, and done-when 2.] The argument for putting the refusal in the
   pure function is that a bind-site refusal loses the diagnosis *"exactly where it was needed"* — the
   client. Read against the three call sites the refusal will actually fire in:
   `hook/push.py:82` calls `connect.resolve_sock_path` inside the `try:` whose `except` funnels every
   failure into `failure.record_failure(hook_log_path, kind, code=…)` (`hook/failure.py:24`), and
   `hook.log`'s contract — `architecture.md:551`, restated at `failure.py:96` and
   `write_policy.py:39` — is *"a fixed failure-kind label and an error code, never prompt or memory
   content"*. So for the hook, the message *"naming `XDG_RUNTIME_DIR`, the computed length and the
   limit"* cannot be written anywhere: the diagnosis is still lost, in the one process the section says
   it must not be. `hook/spawn_warm.py:64–66` wraps the same call in `contextlib.suppress(Exception)` —
   swallowed by design, so the policy print survives. Only `mcp/connection.py:177`
   (`StoreLocation.resolve` in `__init__`) surfaces it, as a server-start failure on stderr. And
   "`bad_config`-class" names an RPC code the *service* returns (`hook/push.py:120`, −32023); the
   client-side refusal is a Python exception with no type named, and `paths.py` must stay stdlib-only
   (`hook/connect.py:342–343` relies on it), so it cannot import the store's error types. Concrete edit
   to (a): *"The refusal is a new exception defined in `service/paths.py` itself (stdlib-only, so the
   hook can import it). `push.py` maps it to a new **fixed** `hook.log` kind — `socket_path_too_long`
   — which is the whole of what that log may carry; the variable name, length and limit reach the user
   through the MCP server's start-up failure and through `zikaron doctor` once M30 lands. `spawn_warm`
   suppresses it as it suppresses everything, deliberately."* Done-when 2 then gains: the hook's test
   asserts the `hook.log` line names that kind and nothing else. Without this an executor either
   violates the log contract or stops on it.

2. **[IMPROVEMENT — the one place a subtly wrong build survives every named test.** M29 §"Two
   specifics" (b), lines 2840–2844, and done-when 2.] Four things the brief leaves to the executor,
   each cheap to state: **(i) the comparison.** The brief gives both the sizeof (104/108) and the usable
   (103/107); an executor holding `{darwin: 104}` and writing `len > limit` admits a 104-byte path,
   which `bind()` refuses. Say *"refuse when `len >= row`"* — CPython's own predicate. **(ii) the
   unit.** CPython measures the *encoded* path (`PyUnicode_FSConverter`, then `PyBytes_GET_SIZE`);
   `len(str(path))` counts code points, and `$XDG_RUNTIME_DIR` is user-controlled and may be non-ASCII.
   Say `len(os.fsencode(path))`. **(iii) the boundary tests.** Done-when 2's two cells — ten-digit uid
   (61 B) and the ≈106 B convention — are 42 bytes and 3 bytes from the edge; neither pins (i) or (ii),
   and "mutation-verify by removing the check" passes an off-by-one. Add: exactly 103 B accepted and
   104 B refused with `platform="darwin"`, 107/108 with `"linux"`, plus one non-ASCII runtime dir whose
   byte length crosses the bound while its character length does not. **(iv) the lookup rule and the
   home.** *"keyed the way `asyncio_compat` keys its rows"* cannot mean its rule — that module's lookup
   is greatest-key-≤ over an ordered version tuple (`asyncio_compat.py:86–98`); platform strings have
   no order — and its docstring reserves it for *version* differences (line 1), so the table must not
   live there. Say: exact match on `sys.platform`, the table in `paths.py` beside `_HASH_HEX_CHARS`,
   the value passed in by the two clients per `paths.py`'s own no-environment rule, and an unknown
   platform takes the **smaller** row (104) — it can only refuse what another platform might have
   accepted, never pass what the kernel will reject, and D35 promises nothing beyond the two named.

3. **[IMPROVEMENT] "fastembed never reads `$FASTEMBED_CACHE_PATH` once `specific_model_path` is
   passed" is false, and the fix is one argument.** M30 §"The model on disk" (2996–2999) and done-when
   3's parenthetical (3081–3082). `OnnxTextEmbedding.__init__` runs
   `self.cache_dir = str(define_cache_dir(cache_dir))` at `text/onnx_embedding.py:250`, *before* the
   `download_model` call at `:252` that returns `specific_model_path` early
   (`model_management.py:402–404`); and `define_cache_dir` (`common/utils.py:48–59`) reads the variable
   when `cache_dir is None` **and `mkdir(parents=True, exist_ok=True)`s the result**. So the shipped
   design as written still creates `tempfile.gettempdir()/fastembed_cache` — the `/var/folders/…`
   directory the section complains about — on every service start, empty. The conclusion (Zikaron
   resolves the variable) is right; the premise is not. Edit: *"fastembed still calls `define_cache_dir`
   in `__init__` and creates the directory; pass Zikaron's resolved directory as `cache_dir` **as well
   as** `specific_model_path`, so the stray `mkdir` lands in the durable directory and `define_cache_dir`
   never consults the variable at all."* Done-when 3's test then asserts the stronger, mutation-checkable
   property: constructing the encoder creates nothing under `tempfile.gettempdir()`.

4. **[IMPROVEMENT] The warm path should be `local_files_only=True` first — fastembed's own sequence —
   so "zero network calls" holds by construction rather than by cache state.** M30 (ii) (3034–3040) and
   done-when 4's offline assertion. Re-derived: on the *online* commit-hash path the listing comes from
   `read_tree_cache` (`_snapshot_download.py:384`) and, if `trees/<sha>.json` is absent, from
   `api.list_repo_tree` (`:394`) — one network call, and under `HF_HUB_OFFLINE=1` an uncaught
   `OfflineModeIsEnabled`. So (ii)'s "zero network calls" has an unstated precondition: the tree cache
   exists, which is a `huggingface_hub`-version artefact of whoever populated the cache. With
   `local_files_only=True` and a commit hash the call takes `:301→:316–331`, and
   `_raise_if_incomplete_snapshot` (`:543–581`) *returns* when the tree cache is missing — no API
   object touched, no request possible. That is exactly what `download_model` does first
   (`model_management.py:412–425`). Edit (ii)/done-when 4: *"warm: `snapshot_download(revision=sha,
   local_files_only=True)`; on `LocalEntryNotFoundError` or `IncompleteSnapshotError`, the online call;
   the allowlist verifies whichever returned. The `HF_HUB_OFFLINE=1` test then proves the fallback was
   not reached."* This also removes the only reason the `huggingface_hub` pin would need to join M28's
   cache key, and makes `doctor` check 4's "present" mean *every allowlisted file resolves under
   `snapshots/<sha>/` and matches* — the tree listing is irrelevant to it.

5. **[IMPROVEMENT] One sentence of M28 done-when 10 still says the milestone stops.** Line 2756: *"So
   the milestone brings the tree to a publishable state and stops."* Two paragraphs later (b) says the
   milestone *"is not closed until the operator's push has produced a green run"*, and the italic note
   says the reconciliation is *session* stops / *milestone* closes on green. The opening sentence is
   the survivor of the trim round 2 flagged. Edit: "the **session** brings the tree…".

6. **[IMPROVEMENT] The brief tells the executor to decide family 1's pattern and then does not.** M28
   §"The sweep", lines 2577–2582: *"Widen it to `"[A-Z][A-Z0-9_]+"` … or state that a listing is out
   of the class by construction — but decide"* — and the family list at 2587–2588 still carries the
   colon form. A brief that says "decide" has not. Recommend widening: family 1 is a *signature* family
   whose job is to flag files for a human read, so over-matching costs a count while the colon form
   costs a miss in a file the table names. Verified this round that the other half of family 1 is
   right: `hook.log:11` and `:27` begin `CLAUDE_CODE_MESSAGING_TOKEN=` at column 0, so
   `^\s*[A-Z][A-Z0-9_]+=` reports them.

7. **[NITPICK] `tests/test_hook_connect.py:197` is the third "~108" site and M29 names two.** Its
   docstring — *"over the ~108-byte kernel limit on Linux … a Python-level guard raised before any
   syscall"* — is correct for Linux and describes a 300-character path handed to `_try_connect`
   *below* `paths.socket_path`, so it stays reachable after M29 and stays true. Name it in done-when 2
   as read-and-left, with one clause added to it (*"bypasses `paths.socket_path`'s own refusal
   deliberately"*), so the executor's "108" sweep neither "fixes" it to 104 nor counts it as drift.

8. **[NITPICK] M28 done-when 6 puts a 64 MB untracked directory inside the checkout.**
   `${{ github.workspace }}/.fastembed_cache` is walked by `test_version_seam.py`'s `_ROOT.rglob("*.py")`
   (harmless — no `.py` inside) and by ruff (harmless — `respect-gitignore` only helps if it is
   ignored). Either add `.fastembed_cache/` to `.gitignore` in the same commit or use
   `${{ runner.temp }}/fastembed_cache`, which `actions/cache` names at authoring time just as well.
   Say which.

9. **[NITPICK] `FINDINGS.md:1236` counts a trail that is still open.** *"round 1 … returned four
   blockers, all applied"* reads as the whole trail; rounds 2 and 3 exist. Per the corpus's own rule
   (*"any tally of an open trail is stale on arrival"*), point at the review file and drop the count;
   line 1369's round-1 sentence is fine as a statement about round 1.

10. **[NITPICK] M30 (ii)'s offline clause.** *"offline it stalls on a 10-second ETag timeout before
    falling back"* → *"with the network down it stalls on the 10 s request timeout before the `refs/`
    fallback; under `HF_HUB_OFFLINE=1` it fails over at once"* (round-2 correction (a) above).

11. **[NITPICK] M30 done-when 3's mutation target does not exist yet.** *"the test must fail against
    today's code"* — today's code has no resolver, so the test fails by `ImportError`, which proves
    nothing. State the mutation: the resolver returning `define_cache_dir(None)`.

**Anything from rounds 1–2 still unaddressed:** none found. Every numbered item in both rounds was
traced to an edit this round, including round-1 nitpicks 16–25.

VERDICT: NEEDS_CHANGES
