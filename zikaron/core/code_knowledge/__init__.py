"""Code knowledge's planner: which per-source-file documents a module needs, and what to remove.

`design/code-knowledge.md` §3 and §4 are normative. Everything here is a function of a module's
sources with their hashes and its documents' text; the walk, git and the filesystem are
`zikaron.code_knowledge`'s, so every decision is reachable without a repository.
"""
