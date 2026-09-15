# Git plumbing on the shapes the walk must handle — measured

**Date:** 2026-09-14. **Harness:** `spikes/spike_git_shapes.py`, re-runnable
(`.venv/bin/python spikes/spike_git_shapes.py`; `--keep` leaves the fixture tree in place).
**Consumers:** `design/knowledge-index.md` §4.1, §4.2, §5.2, §5.6. **Milestone:** M19 spike B.
**Environment:** git 2.43.0, ext4 (case-sensitive), Linux.

## The question

§5.2's `ls-files`/`status` behaviour was measured when the design was written. The two **batched
`--stdin -z` calls were not** — §4.1's `git check-ignore --stdin -z` and §4.2's `git check-attr
--stdin -z` are written from documentation, and each decides whether a file enters the corpus.

Method: one throwaway fixture tree carrying every shape at once — a submodule, a linked worktree, a
sparse clone, a tracked-but-ignored file, an untracked-and-ignored file, a symlink, a `text=auto`
attribute, and paths containing a space and a newline — driven through each invocation, with the
dubious-ownership refusal reproduced faithfully via git's own `GIT_TEST_ASSUME_DIFFERENT_OWNER=1`.

## Verdict

**No mechanism the design depends on is refuted.** Every shape behaves as §5.2 and §5.6 describe.
But **six specification gaps** turned up, three of which would produce a silently wrong corpus, and
one of which is the sharpest single result of this spike.

---

## 1. `text=auto` is a third attribute value, and the obvious predicate empties the corpus

`check-attr --stdin -z binary text` returns one `path NUL attr NUL value NUL` record per (path,
attribute), and **`value` is not a boolean**:

| `.gitattributes` | `binary` | `text` |
|---|---|---|
| `*.bin binary` | `set` | **`unset`** |
| `*.dat -text` | `unspecified` | **`unset`** |
| `*.auto text=auto` | `unspecified` | **`auto`** |
| `*.md text` | `unspecified` | `set` |
| (nothing) | `unspecified` | `unspecified` |

§4.2 says *"`.gitattributes` `binary`/`-text` markings **exclude** a file the sniff would have
admitted"*, which is correct — but it never names the value shapes, and the predicate an implementer
reaches for from that sentence is "exclude unless `text` is `set`". **`* text=auto` is the single most
common line in a real `.gitattributes`** (it is what GitHub's own template recommends), and under that
predicate it excludes **every file in the repository**: the corpus silently comes back empty with
`skipped_binary` equal to the file count.

**The predicate that is correct, and it is the one to write into §4.2:** exclude iff
`binary == "set"` **or** `text == "unset"`. Everything else — `set`, `auto`, `unspecified`, and any
other string a custom attribute carries — admits. Note that the `binary` macro expands to
`-diff -merge -text` (measured with `--all`), so `text == "unset"` alone is sufficient and the
`binary` half is belt-and-braces.

## 2. `check-ignore` exits 1 when nothing is ignored, and §5.2 reads that as failure

| case | exit | stdout |
|---|---|---|
| at least one path ignored | **0** | the ignored paths |
| **no path ignored** | **1** | empty |
| outside a work tree | **128** | empty, `fatal:` on stderr |
| dubious ownership | **128** | empty, `fatal:` on stderr |

§5.2's degradation rule fires when an enumeration-affecting invocation *"fails for any reason"* and
names `check-ignore` among them. **A repository with no ignored files among the walked paths is the
common case for a docs tree**, and a `returncode != 0` test degrades that scan to effective `off` —
which, for `git_mode = all`, is self-consistent (it is what `off` does) but wrong, silently reported as
a degradation that did not happen, and recorded to `meta.last_scan_git_mode_effective` where it becomes
the explanation for a corpus it did not shape.

**§5.2 must say what "fails" means for this one command — and must say it over the complement, not as
a list of failure codes: exits 0 and 1 are answers, and every other outcome is failure.**

**An earlier revision of this line said "exit 128 is failure, exit 1 is an answer", and that is
withdrawn.** The three exits above are what this probe *observed*, not the space of outcomes: a
`check-ignore` killed by a signal, OOM-killed, or exiting 2 on a bad flag returns none of them, and a
rule naming 128 classifies every one of those as an answer. Since the command's answer for "nothing
ignored" is an empty stdout, that misclassification is indistinguishable from a real answer and stops
`.gitignore` being applied under `git_mode = all` — the silent widening the rule exists to prevent.
The observation is what a probe can give; the rule has to cover what it did not see.

## 3. `ls-files` needs `-z` for the same reason `status` does, and the design never says so

§5.2 is emphatic that `status` requires `-z` because *"the default quotes and escapes unusual paths
under `core.quotePath`, and `path` is the join key"*. The document spells the other call `git ls-files
-s` — with no `-z` — everywhere it appears, the candidate-set table and the skip rule included.
Measured, `ls-files -s` quotes identically:

```
with    -z:  100644 9d0e43d7… 0<TAB>weird<LF>name.md
without -z:  100644 9d0e43d7… 0<TAB>"weird\nname.md"
```

A path with a newline, a quote, or a non-ASCII byte therefore fails to match its `files` row, and the
consequence is not a crash but the *fast path missing* — the file is read and hashed every scan
forever, and under `tracked` it is **excluded from the candidate set entirely**, because the
intersection is against a set of mangled keys. Same argument, same fix: `git ls-files -s -z`.

## 4. `check-ignore` is index-aware by default, which is exactly the rule §4.1 states — do not pass `--no-index`

| call | `build/artifact.txt` (untracked, `build/`) | `tracked_but_ignored.log` (**tracked**, `*.log`) |
|---|---|---|
| `check-ignore --stdin -z` | reported ignored | **not reported** |
| `… --no-index` | reported ignored | **reported ignored** |

§4.1 step 3 applies `.gitignore` *"only to paths not listed by `git ls-files`, which is git's own
semantics"*, and §5.2's `all` row says a tracked-but-ignored file is **in**. Measured: git's default
already implements that, and the separate qualification is **redundant rather than required**. What
matters is the negative — passing `--no-index`, which reads like a harmless optimisation ("we already
know which files are tracked"), inverts the documented behaviour and drops tracked-but-ignored files
out of the corpus.

## 5. Two parsing traps in the batch output

**Without `-z`, `check-ignore` answers a different question and says nothing about it.** Feeding the
ignored path `bad<LF>name.log` on a newline-separated stdin, git split it into `bad` and `name.log`,
found the second matched `*.log`, and printed:

```
without -z:  exit=0  stdout=b'name.log\n'      <- a path that does not exist, reported as ignored
with    -z:  exit=0  stdout=b'bad\nname.log\0' <- correct
```

The failure is not that the call errors; it is that it **succeeds with a plausible answer about a
path nobody asked about**.

**`-v --non-matching` emits three empty fields per non-matching record.** With `-z -v --non-matching`,
each record is `source NUL linenum NUL pattern NUL path NUL`, and a non-matching path fills the first
three with empty strings — 24 fields for 6 paths, of which only 9 are non-empty. A parser that splits
on NUL and discards empties (the obvious implementation, and the one this harness shipped first)
misaligns every subsequent record. **The plain form, which echoes only ignored paths, has no such
hazard and is what the design should use** — it is also what it already specifies.

Both commands interpret paths **relative to the process cwd**, not the repository root.

## 6. Under `git_mode = tracked`, a submodule contributes nothing — and that is never stated

The superproject's view of a file edited inside a checked-out submodule:

```
ls-files entries mentioning 'sub':  ['160000 725e511b… 0\tsub']
status fields mentioning 'sub':     [' M sub']
the file exists on disk:            True
```

**Only the gitlink is ever reported**, and it names a *directory*. §5.6's row says gitlinks are
excluded from the `tracked` intersection, which is correct and which has an unstated consequence: under
`tracked`, **every file inside a submodule is outside the corpus**, because none of them appears in
`ls-files`. Under `all` or `off` the walk descends and indexes them; under `all` they have no
`ls-files` entry either, so §5.2's non-NULL requirement sends each one down the read-and-hash path on
every scan — correct, and permanently off the fast path.

The second half matters for §5.2's `status` parser: ` M sub` is a **path that is a directory**. It
never matches a `files` row, so nothing breaks — but a parser that assumes every reported path is a
file is relying on that accident.

---

## What the probe confirms unchanged

| # | Claim | Result |
|---|---|---|
| §5.2 | rename entries carry two paths in the `-z` stream | **confirmed** — `'R  docs/renamed.md'` then a **bare** `'docs/moved.md'` with *no* `XY` prefix. New first, old second |
| §5.2 | `-unormal` collapses an untracked directory | **confirmed** — `'?? untracked_dir/'` against `-uall`'s two file entries |
| §5.2 | both status columns are needed | **confirmed** — ` M`, ` D`, `R `, `??` all observed, with the interesting bit in either column |
| §5.2 | sparse checkout: listed by `ls-files`, absent from disk, **silent** in `status` | **confirmed** — 5 listed-but-absent, `status` reports **nothing** |
| §5.6 | a linked worktree's `.git` is a **file** | **confirmed** — `gitdir: …/base/.git/worktrees/linked-wt`; `ls-files` works from inside it |
| §5.6 | a submodule's `.git` is also a file | **confirmed** — so §4.1's "prune the *name* `.git`, file or directory" covers both shapes |
| §5.2 | `ls-files -s` modes | **confirmed** — `100644`, `120000` (symlink), `160000` (gitlink) all present |
| §5.2 | *any* enumeration-affecting invocation fails under `safe.directory` refusal | **confirmed** — `rev-parse`, `ls-files`, `status`, `check-ignore` **and** `check-attr` all exit **128** with `fatal: detected dubious ownership` |
| §4.2 | attributes can change while the file does not | **confirmed, and stronger** — the **working-tree** `.gitattributes` wins, so an *uncommitted* edit changes the answer with no commit and no file change |

## Two things worth knowing, neither a defect

**`check-ignore` answers for directories** (`build` and `build/` both come back ignored). §4.1 runs it
at step 3 over walked *file* paths, after step 1's fixed-name pruning — so an ignored directory like
`build/` is descended in full and every file under it is walked, statted and then discarded. Testing
directory nodes during the walk would prune those subtrees instead. This is a throughput question, not
a correctness one, and it belongs with M21's throughput measurement rather than here.

**`core.ignorecase=true` is honoured by `check-ignore` and not by `ls-files` pathspecs.** On a
case-sensitive filesystem with the flag forced on, `check-ignore('BUILD/artifact.txt')` reports it
ignored while `ls-files -- 'DOCS/guide.md'` matches nothing. The design never queries `ls-files` by
pathspec (it reads the whole listing and matches in process, byte-exactly), so nothing here is wrong
today — but the two commands do not agree about case under one config, and any future pathspec use
inherits that.

## Not measured, and named as such

**A genuine case-insensitive mount.** Creating one needs root (a loopback vfat/exfat image), so §5.6's
case row is exercised only through `core.ignorecase` on a case-sensitive filesystem. That row is
anyway a claim about *our* byte-exact path matching rather than about git, so this harness could not
settle it either way.

**A `check-attr` failure in isolation.** §5.2 deliberately places `check-attr` outside the degradation
rule. Under dubious ownership it fails *together with* everything else, so the isolated case the rule
is written for was not reproduced — the rule stays well-formed, but it is untested ground.

## What changes in the design

1. §4.2 — state the three-valued attribute result and the exact exclusion predicate
   (`binary == set or text == unset`), naming `text=auto` as the case that must **not** exclude.
2. §4.1 and §5.2 — for `check-ignore`, **exits 0 and 1 are answers and every other outcome is
   failure**, stated over the complement rather than as a list of failure codes.
3. §5.2 — spell the listing call `git ls-files -s -z` where the candidate-set table and the skip rule
   define it, with the same join-key reasoning the section already gives for `status`.
4. §4.1 — record that the tracked-file exemption comes from `check-ignore`'s default index awareness,
   and that `--no-index` must not be passed.
5. §5.2 — note that a `status` path may name a **directory** (a submodule gitlink), and that under
   `tracked` a submodule's contents are outside the corpus entirely.
6. §4.1/§4.2 — both batch calls resolve paths against the **process cwd**.

**M20 is unblocked by this spike.**
