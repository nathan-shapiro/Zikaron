"""`python -m zikaron.knowledge` — manage this project's knowledge bases from a shell.

Parity with the tool surface rather than the primary path: an agent manages corpora through its
own tools, and this is what an operator uses when there is no agent in the room.

**Not a console script**, unlike `zikaron-hook` and `zikaron-mcp`. Those are entry points because a
harness config has to name them by one absolute path. Nothing names this command anywhere: a person
runs it, and `python -m` says which interpreter's Zikaron is being asked — the single most
important fact about a command that creates databases, and the one an ambient name on `PATH` would
obscure.
"""
