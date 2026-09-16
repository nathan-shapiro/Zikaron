"""`python -m zikaron.knowledge.indexer` — build one knowledge base's index.

**Its own entry point, separate from the management command, because a build is a different kind
of work.** It is one to a few minutes of saturated CPU over a whole directory tree, where every
other knowledge-base verb is a small transaction; putting it in a process that also serves
memories would reintroduce a latency race this project has already paid for once in production.

**Started detached by `add` and `refresh`**, which return as soon as it is running and never wait
for it — and run in the foreground by an operator who wants to watch a build, or to see why one
failed, since a detached build's output goes nowhere. Both reach the same command; only the
invocation differs.
"""
