# The pre-publication sweep — four families, every hit read

**Run 2026-09-21 for `design/build-plan.md` §M28 done-when 7, against the working tree plus the
untracked files that will join the publishing commit.** The brief's own table was measured at `HEAD`
and is superseded by this note for counts; the brief remains normative for which families are run
and for the blocker classes.

**Both blocker classes are clear**: no hit of any family inside `zikaron/` that is not this
repository's own code naming its own constants, and **no live credential anywhere** — established by
reading values and, for the only class that could have been live, by probing the filesystem rather
than by reasoning about it.

---

## 0. The unit, stated before any number

**`files` is `git grep -l | wc -l`; `lines` is the sum of `git grep -c`, which counts *matching
lines*, not occurrences.** A line carrying the string twice counts once. This is said first because
the §M28 table's numbers are the same quantity and an earlier pass in this milestone reported
`git grep -o` *occurrences* against them — `/home/nathan` at 146 against the table's 76 — which reads
as explosive growth and is a different measurement under the same word. Neither number was wrong; the
comparison was.

**`git grep` reads tracked files, and that is a second blind spot the brief does not name.** It
warns — correctly, and it matters — that a ripgrep-family tool honours `.gitignore` and so drops the
two `*.log` files carrying the messaging tokens. But `git grep` has the mirror-image gap: a file that
is **untracked and will be committed** is invisible to it. Three such files exist today, and one of
them carries three `/home/nathan` lines. So the sweep is `git grep` **plus**
`git ls-files --others --exclude-standard`, and the totals below are of both.

---

## 1. Family 0 — the five path strings and the operator's address

**Measured at the end of M28's edits**, so these are the numbers a publishing commit carries. The
`at HEAD` column is §M28's table, taken before this milestone wrote anything.

| pattern | tracked files / lines, 2026-09-22 | as first swept, 2026-09-21 | at `HEAD` (§M28) |
|---|---|---|---|
| `/home/nathan` | **22 files**, line count re-derived per run | 19 tracked + 2 untracked / 86 + 10 | 19 / 76 |
| `LeibaTrader` | **8 / 70** | 7 + 1 / 66 + 2 | 7 / 60 |
| `~/Trading` | **8 / 27** | 7 + 1 / 25 + 1 | 7 / 22 |
| `zk-dogfood` | **8 / 16** | 7 + 1 / 14 + 2 | 6 / 11 |
| `zk-m26-cockroach` | **6 / 11** | 5 + 1 / 9 + 2 | 4 / 6 |
| the operator's address | **0 / 0** | 0 / 0 | 0 / 0 |

`/home/nathan`'s 22 tracked files are `reviews/` 7, `experiments/` 5, `research/` 3, `spikes/` 2,
`.kiro/` 2, `design/` 1, and **both** `FINDINGS.md` and `FINDINGS-archive.md`.

**Two things moved these numbers between the sweep and this re-measurement, and neither is a leak.**
The two files the first pass logged as *untracked* — this note and the M28 review — are now tracked,
which is most of the growth. And the **2026-09-22 archive pass** moved blocks out of `FINDINGS.md`
into `FINDINGS-archive.md`, carrying a `/home/nathan` line with them and making the archive a
carrier it had never been (`git show HEAD:FINDINGS-archive.md | grep -c /home/nathan` is 0).
**That is this note's own §"a document that quotes the strings it counts becomes a site for them",
produced by a *move* rather than by quoting** — and it falsified the count in the very fix that had
just been written to make the count honest. A table of file counts over a live tree is a
measurement with a shelf life; the command that produced it is in §0 and is one line.

**`zikaron/` and `tests/` carry zero path-string hits.** The full `/home/nathan` per-file breakdown
is the 22 tracked files counted above, the largest being `research/kiro-mcp-lifecycle-probe.jsonl`
at 21 lines (one per probe firing). **No second-place figure and no line total is written here**:
`git grep -c "/home/nathan"` is the count that cannot go stale, and by the time the last one was
typed this note had overtaken `spikes/claude-code-harness/hook.log` for second place — **by being
edited to record the count**.
*Two corrections landed on this sentence in consecutive sweep rounds. It said 19 while the table
above said 22, a second statement of one quantity left behind by the pass that fixed the first; and
its "second largest" was falsified by the act of writing it down. **A document that counts strings
it also contains is on a treadmill by construction** — §"Every row grew" below says exactly that,
and this paragraph is its third instance. The remedy is not a better number, it is naming the
command instead.*

**Every row grew, and the brief predicted exactly why**: a document that quotes the strings it counts
becomes a site for them. `design/build-plan.md` alone now carries 6 `/home/nathan` lines and
`FINDINGS.md` 3, almost all of them inside the sections *about* this sweep. `zk-dogfood` and
`zk-m26-cockroach` each gained a file for the same reason. **Read the growth as quoting, not as new
exposure** — which is also why the guard test below assembles its patterns from fragments.

**The address pattern must be stated or it does not reproduce.** "Zero" means *the operator's own
address, matched literally*. A naive `[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}` returns
**exactly six** hits, every one an `@example.invalid` placeholder, in three files:
`spikes/spike_git_shapes.py` (2), `tests/test_knowledge_scan_git.py` (3),
`tests/test_knowledge_git.py` (1). So the pattern either names the address or excludes
`.invalid`/`.example`.

**The committer email is in every commit's metadata and no content sweep reaches it.**
`git log --format='%an <%ae>'` returns one identity for the whole history. Ordinary for an
open-source repository, and recorded so it is a choice rather than a discovery.

---

## 2. Family 1 — environment-dump signatures in tracked `.log`/`.jsonl`

| form | files | lines |
|---|---|---|
| `^\s*[A-Z][A-Z0-9_]+=` | `spikes/claude-code-harness/hook.log` 49, `mcp.log` 66 | 115 |
| `"[A-Z][A-Z0-9_]+"` | `research/kiro-mcp-lifecycle-probe.jsonl` 21, `kiro-session-id-probe.jsonl` 5 | 26 |

**Exactly the four files the brief names, and no fifth.** No other tracked `.log` or `.jsonl` carries
an environment dump.

**The brief's pattern decision is confirmed by measurement, not by its argument.** It reasoned that
the colon form `"[A-Z][A-Z0-9_]+":` would report *nothing* in `research/kiro-session-id-probe.jsonl`
— whose upper-snake strings are list *items*, followed by `,` or `]` — and widened the family to any
quoted upper-snake string. Run both ways: the colon form returns **no match** in that file and the
widened form returns all **5** lines. A family that misses a file its own table names would have been
the sweep's worst possible defect, and the reasoning that caught it was right.

---

## 3. Family 3 — credential-shaped values, every distinct value classified

**33 distinct hex runs of ≥32 characters exist in the tree. Three are credentials. All three are
dead, and that is measured.**

| value(s) | what it is | live? |
|---|---|---|
| `6ae2167d…`, `339b8886…`, `4df37995…` (32 hex) | three `CLAUDE_CODE_MESSAGING_TOKEN`s, in the two `.log` files | **no — probed, see below** |
| `d5fef33f…` (32 hex) | a Zikaron `store_id` inside a socket path quoted in `research/m18-spill-end-to-end.md` | n/a — a hash of a local path |
| `d8efbb5d…`, `178d5a0c…` (32 hex) | URL path components in citations (a NeurIPS proceedings file, a GitHub gist id) | n/a |
| `e3b0c442…` (40 hex) | the SHA-1 of the empty string, an embedder-precision test fixture | n/a |
| `deadbeef…`, `1111…`, `2222…`, `3333…`, `4444…` | test fixtures | n/a |
| `836dbd85…` (64 hex) | `FROZEN_SHA`, the embedder-precision frozen-dataset hash | n/a |
| `13cb3eb2…`, `7b136db7…`, `d7c99931…`, `15cc8f3c…`, `b6fc4c62…` (40 hex) | git commit SHAs in citations and one test assertion literal | n/a |
| remaining 64-hex runs | SHA256s in `experiments/embedder-precision/` results and preregistrations | n/a |

`-----BEGIN` returns three lines: two are this milestone's own prose stating the pattern, and one is
`tests/test_hook_write_policy.py:91`, which writes `-----BEGIN OPENSSH PRIVATE KEY-----` as a fixture
**for the test that asserts the write policy refuses secrets**. Keeping it is correct.

### The liveness probe, which is the only part of this note that is evidence rather than reading

The brief established the messaging tokens were harmless by *reading* how they are used:
`CLAUDE_CODE_MESSAGING_TOKEN` pairs with `CLAUDE_CODE_MESSAGING_SOCKET`, a pid-named socket on tmpfs
under a 0700 directory. Correct, and still a chain of reasoning. **Probed instead:**

- The three sockets named in those logs are `/run/user/1000/cc-socks/{2256639,2256878,2256968}.sock`.
  **All three are absent from the filesystem.** The processes are long gone and `/run/user` is tmpfs,
  so a reboot removes even the directory.
- `/run/user/1000/cc-socks` is `drwx------ nathan nathan`. **0700, owned by the operator** — so even
  while live, the socket was reachable only by the uid that needs no token to reach it.

**So the tokens authenticate nothing, to nothing, for nobody.** That is a measurement, and it is what
licenses "no redaction, no history rewrite" rather than an argument about ephemerality.

### The two values that are genuinely persistent, enumerated rather than grepped

`research/kiro-mcp-lifecycle-probe.jsonl`'s `kiro_env` object was **parsed and fully enumerated**,
because the brief records that a grep for *names* cannot establish that a *value* is present, and
that the sweep's own author once wrote "verified independently" on the output of exactly that blind
instrument. All 17 keys and their values:

- **`KIRO_USER_ID` = `d-9067c98495.<uuid>`** — an AWS Builder ID directory plus user. Stable, and the
  only genuinely persistent identifier in the tree.
- **`KIRO_TELEMETRY_CLIENT_ID`** — a uuid4, stable per install.
- `KIRO_SESSION_ID`, `KIRO_TUI_READY_TOKEN` — uuid4s, per-session, naming local files.
- `KIRO_TELEMETRY_OTLP_ENDPOINT`, `KIRO_VERSION`, `KIRO_ENABLED_FEATURES`, the various rollout and
  colour flags — vendor configuration, not secrets.
- `KIRO_CHAT_CLI_BIN`, `KIRO_FEED_FILE`, `KIRO_TUI_READY_FILE` — local paths, two under `/home/nathan`.

**Neither persistent value authenticates anything**, and both disclose less than the committer
metadata every commit already carries. `research/kiro-session-id-probe.jsonl` is confirmed as the
brief describes: `env_kiro_keys` is a list of 17 **names with no values**, and the file's only value
is `env_KIRO_SESSION_ID`, a uuid4, five distinct across five firings.

---

## 4. Family 2 — credential-shaped names, and its permanent false-positive population

`TOKEN|KEY|SECRET|PASSWORD|CREDENTIAL|CLIENT_ID|USER_ID` matches **40 tracked files**, and outside
the four known ones **every hit is either prose or one of this repository's own constants**.

**Narrowed to what the family is actually for** — an *assignment* of a credential-shaped name to a
non-trivial value — it returns 19 lines outside the four known files, and all 19 are Python
identifiers ending `_KEY`: the `meta` dict-key constants in `zikaron/core/knowledge/meta.py`,
`scan.py`, `repair.py`, `counters.py`, plus test fixtures in `tests/test_meta.py` and two others.

**This population is permanent and a future sweep must not re-litigate it.** `meta.py` names every
dict key `<NAME>_KEY` by convention, so family 2 will report `zikaron/` hits forever. **This is the
one place the "any hit inside `zikaron/`" blocker class needs its exception stated**: the blocker is
a *path string or credential* inside `zikaron/`, and a constant named `EMBED_MODEL_KEY` is neither.
The guard test below therefore checks the path-string family against `zikaron/`, not family 2.

---

## 5. Decisions, each with its reason

1. **No redaction and no history rewrite.** Nothing live, established by probe for the only class
   that could have been. The remedy for a live credential is a history rewrite, which is the
   operator's decision and destructive in the way `CLAUDE.md` forbids an agent to attempt unasked —
   so the bar for reaching for it is evidence, and the evidence points the other way.
2. **`/home/nathan` stays.** A home-directory path is not a secret, and most of the files carrying
   one are evidence directories whose value is that they record what was actually run. **Five are
   not, and the original wording of this decision covered only the ones it was easiest to justify**
   — §1's own breakdown lists them: `design/build-plan.md`, `FINDINGS.md` and `FINDINGS-archive.md`
   quote the strings they count, and the two `.kiro/` configs are real installed output whose
   virtualenv paths the installer rewrites, which `README.md` §Install already tells a clone-mate to
   expect. The decision is unchanged; the reason now covers the files it is about.
3. **`LeibaTrader` stays entirely** — operator decision 2026-09-21, taken with the alternatives on
   the table. The brief is right that redacting the name while keeping the quoted store contents
   discloses the same thing, which makes it a per-passage judgement and his; his judgement is that
   the quoted material is Zikaron's own measured evidence and is worth publishing.
4. **`tests/test_hook_write_policy.py`'s fake private-key header stays**, being the fixture for the
   guard against exactly that class.
5. **The committer email stays in history**, named as a choice.
6. **The sweep's own instrument is recorded, not just its output** — the unit, the `git grep` vs
   ripgrep gap in both directions, the widened family-1 pattern and the family-2 false positives —
   because this note's predecessor was a count with no method beside it, and the method is what
   turned out to be wrong twice.
