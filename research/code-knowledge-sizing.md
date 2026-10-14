# Sizing linked code knowledge, and how the knowledge index is used today

**Measured 2026-10-13**, for `design/code-knowledge.md`. Each figure carries the command that
re-derives it. The host was at load average ~5 throughout, so the timing is not an idle-host figure.

## 1. The cost of checking a linked result's source at search time

K14 (proposed) hashes the source file behind each linked search result, two ways measured: in
process, as git's blob hash of the raw bytes — `sha1(b"blob %d\0" % len(data) + data)`, which is
`git hash-object --no-filters` — and through git, one batched `git hash-object --stdin-paths`.

| quantity | value |
|---|---|
| in-process agreement with `git hash-object` on 20 files of `zikaron/` | **20 / 20** |
| in-process, the sources behind 10 results | **0.43 ms** |
| in-process, the sources behind 25 results | **1.16 ms** |
| in-process, the largest file in `zikaron/` (51,615 B) | **0.10 ms** |
| through git, the sources behind 25 results on `--stdin-paths`, p50 / p90 | **3.03 / 3.17 ms** |
| through git with `--no-filters`, p50 / p90 | 2.89 / 3.06 ms |
| through git, the same 25 as arguments after `--`, p50 / p90 (load 7.5) | **3.66 / 3.81 ms** |
| `git ls-files -s`, the whole index | 2.03 ms |
| `zikaron/*.py` files, median size | 200 files, 7,768 B |

Warm page cache; in-process figures are the mean of 50 repetitions, git figures over 30. **Either
way the cost is bounded by the number of results a search returns, not by corpus size.**

**The 20/20 agreement holds because this repository has no end-of-line attributes.** Plain
`git hash-object <path>` applies the clean and end-of-line filters that `.gitattributes` selects —
which is what makes its output git's object id — and the raw-bytes hash does not, so the two diverge
in a repository that normalizes line endings or stores files through LFS. That, and not speed, is
why K14 computes the hash through git inside a work tree. **`git ls-files -s` is cheaper still and
is not usable for this check**: the index records the staged version, so a file edited and not
staged would read as unchanged. Its place is M40's planner, over a whole corpus, beside git's own
modified-file detection.

```bash
.venv/bin/python - <<'EOF'
import hashlib, subprocess, time, pathlib
files = list(pathlib.Path('zikaron').rglob('*.py'))
def blob(p):
    b = p.read_bytes(); return hashlib.sha1(b"blob %d\0" % len(b) + b).hexdigest()
s = files[:20]
g = subprocess.run(['git', 'hash-object', *map(str, s)], capture_output=True, text=True).stdout.split()
print("agree:", sum(blob(p) == h for p, h in zip(s, g)), "/", len(s))
for n in (10, 25):
    t = time.perf_counter()
    for _ in range(50): [blob(p) for p in files[:n]]
    print(n, f"{(time.perf_counter() - t) / 50 * 1e3:.2f} ms")
inp = "\n".join(map(str, files[:25])) + "\n"
ts = []
for _ in range(30):
    t = time.perf_counter()
    subprocess.run(['git', 'hash-object', '--stdin-paths'], input=inp, capture_output=True, text=True)
    ts.append((time.perf_counter() - t) * 1e3)
ts.sort(); print("git p50/p90", f"{ts[15]:.2f} / {ts[27]:.2f} ms")
EOF
```

### 1a. What decides git's answer: the working directory, not the file's repository

Probed 2026-10-13 with git 2.43.0, on a file holding `a\r\nb\r\n`, whose raw blob id is `c30dea8…`
and whose id after `text=auto` normalization is `422c2b7…`:

| run from | file | `.gitattributes` | printed |
|---|---|---|---|
| repository Z | at Z's root | `* text=auto` at Z's root | `422c2b7…` |
| repository Z | at Z's root | `* -text` at Z's root | `c30dea8…` |
| this repository, which has no attributes | at Z's root | `* text=auto` at Z's root | `422c2b7…` |
| this repository | `Z/sub/f.txt` | `* text=auto` at Z's root only | `422c2b7…` |
| a directory that is no work tree | `Z/sub/f.txt` | `* text=auto` at Z's root | `c30dea8…` |
| a directory that is no work tree | a file beside its own `* text=auto` | as stated | `c30dea8…` |

**Run from inside any work tree, git applies the `.gitattributes` found along the file's own
path, even in another repository; run from outside one, it applies none and prints the raw blob
form**, which the in-process computation reproduces. **A repository git declines for its ownership
is treated the same way**: with `GIT_TEST_ASSUME_DIFFERENT_OWNER=1`, `git hash-object -- f` on the
`text=auto` file above exits 0 printing the raw `c30dea8…`, not dying — so a container that owns the
work tree differently is not a git failure, only a machine on which no filter applies. So the hash K14 records depends on where git is
run, which is why its one function fixes the working directory to the Zikaron root. A FIFO given to
`git hash-object` blocks it until it is killed (`timeout 3` returned 124).

### 1b. How the path reaches git matters when the root is below the repository's top

Probed 2026-10-13: a repository `top/` whose Zikaron root would be `top/pkg/`, a file
`pkg/docs/x.md` holding `a\r\nb\r\n`, a different file `top/docs/x.md`, and one top-level
`.gitattributes` line, `pkg/docs/*.md text=auto` — anchored, so it matches only by the path from the
top. The oracle is `git add` then `git ls-files -s`: `422c2b7…`.

| run from | how the path is given | printed |
|---|---|---|
| `pkg/` | argument after `--`, relative: `docs/x.md` | `422c2b7…` ✓ |
| `pkg/` | `--stdin-paths`, relative: `docs/x.md` | `2c8b2a0…` — **`top/docs/x.md`, the wrong file** |
| `pkg/` | `--stdin-paths`, absolute | `422c2b7…` ✓ |
| `pkg/` | argument after `--`, absolute | `422c2b7…` ✓ |
| `top/` | argument after `--`: `pkg/docs/x.md` | `422c2b7…` ✓ |

**`--stdin-paths` resolves a relative path against the work tree's top, not the working directory**,
so it silently hashes another file of the same name when the root is a subdirectory — a monorepo
shape. An argument is resolved against the working directory, and the anchored attribute applied
in every correct row.

**A source reached by `..` needs one more step.** Same repository, a file `lib/foo.py` holding
`a\r\nb\r\n`, and a `.gitattributes` of `* text=auto` in `pkg/` alone, so `git add lib/foo.py` stores
the raw form, `c30dea8…`:

| run from `pkg/`, the path given as an argument | printed |
|---|---|
| `../lib/foo.py`, as declared | `422c2b7…` — **`pkg/.gitattributes` applied to a file outside `pkg/`** |
| `<abs>/top/pkg/../lib/foo.py`, joined and not normalised | `422c2b7…` — the same mistake |
| the real path, `<abs>/top/lib/foo.py` | `c30dea8…` ✓ |

git builds its attribute stack from the path as given, so a `..` walks it through the directories
the text names rather than the ones the file is in. **So K14's function resolves each source to its
absolute real path — the kernel's resolution, symlinks first — and gives git and its own regular-file
check that one path**, as an argument after `--`.

```bash
mkdir -p top/pkg/docs top/docs && cd top && git init -q
printf 'a\r\nb\r\n' > pkg/docs/x.md; printf 'TOP\n' > docs/x.md
printf 'pkg/docs/*.md text=auto\n' > .gitattributes; git add pkg/docs/x.md
git ls-files -s pkg/docs/x.md                     # oracle
cd pkg && git hash-object -- docs/x.md            # matches
echo docs/x.md | git hash-object --stdin-paths    # hashes top/docs/x.md
```

## 2. How big a corpus the producer would write here, and how fast it goes stale

Source files outside `tests/`, by extension (`py ts js rs go cs cpp h java`):

| repository | files | bytes |
|---|---|---|
| `zikaron/` | 200 | 2.0 MB |
| `~/Trading/LeibaTrader` | 243 | 1.7 MB |

**Both are small enough that grep still finds things**, so neither can show the benefit the
proposal is for. They exercise the plumbing only.

**Churn, `zikaron/` over the 60 days to 2026-10-13: 47 commits touched a `zikaron/*.py` file 501
times**, median 4 per commit, maximum 64. Against ~200 files, regenerating every touched file at
every commit would have cost about **2.5× the first full build** over two months — so the
steady-state cost dominates the first build, and regeneration cadence is a design input rather
than an operational detail. LeibaTrader cannot answer this: its 30-day history is five commits,
one of them adding 240 files, because its work is mostly uncommitted.

```bash
git log --since='60 days ago' --no-merges --format='@%h' --name-only \
  | awk '/^@/{c++;next} /^zikaron\/.*\.py$/{n[c]++} END{for(i=1;i<=c;i++) print (i in n)?n[i]:0}' \
  | sort -n | awk '{a[NR]=$1;t+=$1} END{print NR, t, a[int((NR+1)/2)], a[NR]}'
```

## 3. How the knowledge index is used in the field

`~/Trading/LeibaTrader` is the only store with corpora — `arcs` and `research`; `~/Dividends` and
`~/Memory` have none. Its access log (M33's `call` rows) spans 2026-09-29 to 2026-10-13:

| method | calls |
|---|---|
| `knowledge_refresh` | **26** |
| `knowledge_search` | **9** |
| `knowledge_list` | 1 |
| `memory_search`, for comparison | 38 |

**Refreshes outnumber searches about 3:1**, across three sessions. The project's `CLAUDE.md`
instructs a refresh after every write to `arcs/` or `research/`, because nothing in the product
schedules one (`design/knowledge-index.md` §16, item 6), and a file that was never indexed is
invisible to search with no `stale` signal to say so (§7.5 flags only files already indexed). All 27
`knowledge_build` rows are `ok`, at 1.1–21.3 s, most 4–7 s; the 26 `arcs` builds each leave 22–24
files indexed, the one `research` build 3.

```bash
.venv/bin/python - <<'EOF'
import sqlite3
c = sqlite3.connect("file:/home/nathan/Trading/LeibaTrader/.zikaron/memory.db?mode=ro", uri=True)
print(c.execute("SELECT json_extract(detail,'$.method'), count(*) FROM event "
                "WHERE kind='call' GROUP BY 1").fetchall())
print(c.execute("SELECT min(at), max(at) FROM event WHERE kind='call'").fetchone())
EOF
```
