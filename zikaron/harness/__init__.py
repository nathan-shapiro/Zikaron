"""The one seam where the two supported harnesses differ.

`design/harness.md` is normative. Everything downstream of this package is written once: the
difference between kiro-cli and Claude Code is carried as **data in `spec.py`'s table**, never as a
forked code path, because forking doubles every future change to the two components the design
deliberately keeps thin.

**This package is stdlib-only and import-cheap, and that is a measured constraint rather than a
style preference.** It is imported by `zikaron-hook`, which runs once per user message, so its
import cost is a per-turn tax on the exact critical path the push architecture's whole argument
rests on. `zikaron.hook.envelope` records the number that governs it: importing
`zikaron.core.events` alone costs ~28 ms against a whole-process hook budget of ~48 ms without it,
which is why that module keeps its own guarded copy of the request envelope rather than importing
the canonical one. Nothing here may import from `zikaron.core`, `zikaron.service` or any third-party
package.

`enum` and `typing` are the two imports this package does take, and both were measured before being
taken: against a 24 ms bare interpreter and the hook's existing 30 ms `os`/`sys`/`json`/`socket`/
`pathlib`/`subprocess` floor, adding `enum` costs **nothing measurable** (`socket` already imports
it) and adding `typing` costs ~2 ms (and `zikaron.hook.envelope` already pays it for its own
`NamedTuple`). So the closed sets `coding-standards.md` §2 asks for are affordable here; a frozen
dataclass would not be, since `dataclasses` pulls in `inspect`.
"""
