# Linked documents end to end through a real agent: indexed by the CLI, and by the agent itself

**Run 2026-10-13** on the M39 build as committed for pull request #26 (`6c8cbac`), at the operator's
request: install Zikaron into a new project, link a document to a source file, index it, ask an
agent, edit the source, and ask again — once with the indexing done through the CLI and once with
the agent doing it through its MCP tools.

## Setup

Two scratch projects, `cli` and `agent`, identical: a git repository with one commit holding
`src/billing.py` (`VAT_RATE = 0.17`, used by `invoice_total`) and `docs/billing.md`, which opens
with `zikaron-source: src/billing.py` and the source's `git hash-object` id, and says the rate is
**17%**. Zikaron installed into each from the worktree's `.venv` with
`python -m zikaron.install --project . --harness claude-code`, then `zikaron init`. Every agent turn
is a fresh `claude -p` (model `claude-opus-5-5`) started with a clean environment, so it runs a
session of its own, and every question is the same prompt:

> Using this project's knowledge index, what VAT rate does invoice_total apply? Answer in two or
> three sentences and say where your answer came from.

Between the first and second question `VAT_RATE` became `0.18`, uncommitted; the document still
says 17%.

## Indexing

**By the CLI** (`cli`): `zikaron knowledge add docs --path ./docs` started a build, and
`zikaron knowledge refresh docs --wait` answered *"'docs' is already being built; this call queued
nothing"*, waited through that build and printed *"built 'docs' is ok"*, in 1.55 s. `status` then
showed one file, `linked 1 files`.

**By the agent** (`agent`), asked to add `docs/` as a knowledge base named `docs`, refresh it and
poll until the build finished: it called `knowledge_list`, listed the directory, then
`knowledge_add` (`outcome: started`), `knowledge_refresh` (`outcome: started` — add's build had
already completed, its scan started 01:52:09.28) and `knowledge_status` once, which showed a later
scan (started 01:52:11.20, completed, `lock: null`), and reported `ok`, one file. It added
unprompted that the default `git_mode` indexes only tracked files, so a new document is not found
until it is committed.

## What the agent did with `source`

| project | question | `source.state` | opened the source | answer |
|---|---|---|---|---|
| `cli` | before the edit | `fresh` | yes, a `grep` for the constant | 17%, the document "current with `src/billing.py`" |
| `cli` | after the edit | `changed` | yes, the file and `git diff` | 18%, the document out of date |
| `agent` | before the edit | `fresh` | **no** — "I didn't open the code myself" | 17%, from the document |
| `agent` | after the edit | `changed` | yes, the file and `git diff` | 18%, the document out of date |

After the four questions each corpus's `status` read `searches 2`, `linked … results 2 (1 source
changed, 0 missing, 0 unverifiable)` — the tally of the two searches. The five turns cost $0.288,
$0.115, $0.159, $0.103 and $0.116.

## Readings

- **`changed` sent the agent to the code both times**, and both times it said which document was
  out of date and why, citing the index's flag. That is the behaviour K14 exists for.
- **`fresh` let the agent stop at the document once in two**, and say so. That is the saving the
  link is meant to buy; with n = 2 it is an observation, not a rate.
- **The agent's one status poll was right by timing, not by reading.** It took a completed scan and
  a null lock as *its* build being over without comparing that scan's start with the one `refresh`
  returned. Here the scan had moved on, because its next call came two seconds later; it would
  have read an earlier build as its own only inside the ~1.2 s a spawned build spends loading its
  model before it takes the lock (`research/build-transaction-upgrade-race.md`), which a model turn
  between two tool calls did not reach. **No change proposed**: `refresh --wait` already makes that
  comparison for a script, and an agent misreading it has not been observed.
