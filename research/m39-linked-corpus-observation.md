# A real linked corpus, built by the real service and searched over MCP

**Observed 2026-10-13**, for `design/build-plan.md` §M39's done-when 2: a handful of linked
documents written by hand over this repository's own sources, one of each `state`, built through the
real service and searched through `zikaron-mcp` over stdio. Every process ran the worktree's code
(`/home/nathan/Zikaron-m39/.venv`).

## Setup

A scratch project whose Zikaron root holds a clone of this repository under `src/` and six documents
under `docs/`, each opening with a front-matter block naming a source relative to the root:

| document | declares | expected |
|---|---|---|
| `files.md` | `src/zikaron/core/knowledge/files.py` at its current blob | `fresh` |
| `scan.md` | `src/zikaron/core/knowledge/scan.py` at a blob from four commits back | `changed` |
| `gone.md` | `src/zikaron/core/knowledge/gone.py`, which does not exist | `missing` |
| `package.md` | `src/zikaron/core/knowledge`, a directory | `unverifiable` |
| `malformed.md` | a path and no hash | `unverifiable`, `path: null` |
| `plain.md` | no front matter | no `source` key |

Then `zikaron init`, `zikaron knowledge add notes --path ./docs --git-mode all` and
`zikaron knowledge refresh notes --wait`, followed by `zikaron_knowledge_search` ("indexed files")
and `zikaron_knowledge_status` through a `fastmcp` stdio client running `zikaron-mcp --mode primary`.

## What came back

```
files.md       stale=False source={"path": "src/zikaron/core/knowledge/files.py", "state": "fresh"}
plain.md       stale=False (no source key)
malformed.md   stale=False source={"path": null, "state": "unverifiable"}
gone.md        stale=False source={"path": "src/zikaron/core/knowledge/gone.py", "state": "missing"}
package.md     stale=False source={"path": "src/zikaron/core/knowledge", "state": "unverifiable"}
scan.md        stale=False source={"path": "src/zikaron/core/knowledge/scan.py", "state": "changed"}
{'files_linked': 5, 'results_linked': 5, 'results_source_changed': 1,
 'results_source_missing': 1, 'results_source_unverifiable': 2}
```

Every result's `source` is what §7.7 says it should be, and the counters after one search are the
tally of that search's results. The source is inside a git repository with no `.gitattributes`, so
git's id and the raw blob agree here; the filter cases are covered by `tests/test_knowledge_source_hash.py`.

**Two other things the run showed, on the way.**

- **The spawn dedup, live.** The `refresh --wait` that followed `add` answered `already_indexing` —
  *"is already being built; this call queued nothing"* — waited through the build `add` had spawned,
  and returned `built 'notes' is ok`. Before this milestone that refresh spawned a second build.
- **The version check, live.** A first attempt made the project *itself* a clone of this
  repository, and ran the commands from it. Every command was then refused — *"this project's
  service … is older than this command … and names no version"* — although the service had just been
  spawned from the worktree's interpreter: a spawned process runs `python -m …` in the *client's*
  working directory, Python puts that directory first on `sys.path`, and the clone's own `zikaron/`
  package therefore shadowed the installed one, so the service ran the clone's older code. The check
  named exactly that. It takes a working directory that is a Zikaron checkout *other than* the
  install doing the spawning, which only this scratch setup had; the setup above keeps the clone one
  level down, and every spawn now passes `-P` (`design/build-plan.md` §M39, item 13), so the working
  directory is no longer on a spawned process's `sys.path`.
