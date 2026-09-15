"""`python -m zikaron.knowledge.indexer` — build one knowledge base's index.

**Its own entry point, separate from the management command, because a build is a different kind
of work.** It is one to a few minutes of saturated CPU over a whole directory tree, where every
other knowledge-base verb is a small transaction; putting it in a process that also serves
memories would reintroduce a latency race this project has already paid for once in production.

Invoked synchronously today by the `refresh` verb, so the person who asked for a build waits for
it. Nothing about running it detached needs a different module — only a different invocation.
"""
