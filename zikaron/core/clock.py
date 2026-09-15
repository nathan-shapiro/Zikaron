"""The one clock every layer reads, and the one format every stored instant is in.

A single implementation, because several stored times are compared against **each other** rather
than merely displayed. Two clocks with two formats — one naive and one aware, or one truncated —
would make each of those comparisons a coin flip on a boundary nobody looks at.

**The contract, stated here because several callers depend on it and none of them should have to
rediscover it.** Every instant is ISO-8601 in UTC, so **lexicographic order on these strings agrees
with temporal order**, and a reader may compare two of them with `<` without parsing. That is a
property of the format rather than a coincidence: the offset is always `+00:00`, the fields are
fixed-width and most-significant-first, and the one optional field — microseconds, which
`isoformat()` omits when they are zero — sorts correctly anyway because `+` precedes `.`, putting
`…:12+00:00` ahead of `…:12.000001+00:00`. Measured over every boundary case and several million
random pairs, and pinned by a test, so it is a checked claim rather than an observation that held
the day it was made.

Reliance on it comes in two kinds, and the second is why the contract has to be stated rather than
merely observed. **In Python**, a knowledge base's `files_remaining` rule compares its walk's
completion instant against its build's start with a plain `<`. **In SQL**, every `MIN`, `MAX` or
`ORDER BY` over a stored `at` is this same contract applied inside the database — the signal
queries take lexicographic minima over `event.at` and call the result the earliest instant, which
is true only because of it. That second kind cannot be rewritten to parse: there is no `datetime`
inside a SQLite aggregate, so the ordering is not a convenience there but the mechanism.

Arithmetic is the exception, and it parses: a consolidation lease is a start plus a duration, and a
signal horizon is an event's instant plus a number of days. Adding to a string is not something
ordering can do for you.

**One of those results is itself stored** — the lease's `expires_at` — so the contract has to cover
it, and it does: parsing an aware UTC instant, adding a whole number of seconds and re-formatting
yields the same shape it started from, microseconds present or absent alike. The derivation is
closed under the format, which is what lets "one format" stay true of a value no clock read
produced.

It lives here rather than beside any one kind of record because it belongs to none of them. It was
previously a function of the memory-record module, whose own docstring then had to enumerate which
*tables* drew from it — a list that silently went stale the first time a second database started
storing instants, which is the drift this project has convicted itself of more than once. What is
above is deliberately a classification rather than a list: a new caller orders (in Python or in
SQL) or it does arithmetic, and adding one does not falsify anything written here.
"""

from datetime import UTC, datetime


def timestamp() -> str:
    """The current instant, ISO-8601 in UTC.

    Every stored time in every database Zikaron owns either comes from here or is derived from one
    of these by parse-add-`isoformat()` — the consolidation lease's `expires_at` is the only such
    derivation — and that derivation preserves the format, so any two stored instants order
    correctly under a plain string comparison. See this module's docstring for why that ordering is
    a property of the format rather than luck, and for the arithmetic callers that parse instead.
    """
    return datetime.now(UTC).isoformat()
