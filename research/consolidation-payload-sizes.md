# How big a consolidation group actually gets

Measured 2026-09-13 against `~/Trading/LeibaTrader/.zikaron`, read-only, at 252 memories / 116
planned groups / 16 runs — the store whose consolidation run stalled and prompted M18. Sizes in the first
two sections are **prose characters**: `len(gist) + len(content)` summed over the rows a serve
delivers, with JSON framing, escaping and the payload's own keys extra — so those figures are
floors. §"Serialized size" then makes them commensurable with the unit a threshold is actually
compared against.

A caveat that matters for how these numbers are used: this is **one store, at one moment**. The
mechanism M18 builds must not be fitted to this distribution — these numbers say the defect is real
and roughly how often it bites, not what any threshold should be.

## Per-group totals

| | anchor + members + candidates |
|---|---|
| max | **69,265** |
| median | 27,206 |
| over 40,000 chars (the smallest payload measured to spill) | **20 of 116** |
| over 52,000 chars (measured to spill) | 3 of 116 |

## Where the bytes are

**Candidates dominate**: a median **70%** of a group, up to **94%**. One group carrying a single
journal entry reached 50,663 characters because its candidates were 40,103 of them. `group_max`
caps the *number* of journal entries (default 12) and `MAX_CANDIDATES` caps candidates at 4, but
neither bounds how much prose those rows carry — a record's `content` has no length bound at all,
where a gist does (`GIST_MAX_CHARACTERS`).

**Anchor plus members alone** — the part no candidate trimming could shrink:

| | anchor + members |
|---|---|
| max | 47,406 |
| median | 7,515 |
| over 40,000 chars | **2 of 116** (47,406 and 45,013) |

Those two are why a candidate-trimming fix would have been incomplete, and they are the evidence
base for a future size-aware sharding brief. M18 does not address them: a spilled payload carries
them whole, so they need no special handling there.

## Serialized size, which is the unit a threshold is actually compared against

The figures above are prose characters. What a client compares against a threshold is the
serialized JSON result, so the two must be made commensurable. Measured by building a
representative `next_group` payload per group — group and run ids, shard, counts, anchor, journal
entries and ranked candidates, each row carrying uuid, gist, content, version, tier and timestamps —
and taking `len(json.dumps(payload))`:

| | prose | serialized |
|---|---|---|
| median | 27,206 | **29,258** |
| max | 69,265 | **73,331** |

Framing, keys, timestamps and escaping cost a median **1.074×**, max 1.165× — materially less than
the 10–20% a guess would have assumed, which is why it is measured here rather than estimated in a
brief.

Groups that would exceed a given serialized threshold:

| threshold | groups spilling |
|---|---|
| 32,000 | 43 / 116 |
| 36,000 | 29 / 116 |
| 40,000 | 25 / 116 |

**The longest single JSON-escaped `content` string in the store is 17,275 characters, which is also
17,275 UTF-8 bytes** — that record is pure ASCII, so the two agree here and the escaping mode does
not separate them. It will separate them on any store holding CJK or emoji: `json.dumps` with
`ensure_ascii=True` renders one such character as a six-character `\uXXXX` escape, with
`ensure_ascii=False` as one character, and in UTF-8 as three or four bytes. That is why the bound
M18 sets is denominated in **bytes** — a token spans at least one byte, so bytes bound tokens for
any content, while a character count bounds nothing without a content-dependent ratio.

Serialized in UTF-8 bytes with `ensure_ascii=False`, the same 116 payloads run to a median of
**29,150.5** and a max of **73,184** — within 0.4% of the character figures above, because this
store is almost entirely ASCII. Groups exceeding a byte threshold:

| threshold (UTF-8 bytes) | groups spilling |
|---|---|
| 27,000 | 67 / 116 (58%) |
| 29,000 | 59 / 116 (51%) |
| 29,900 | 54 / 116 (47%) |
| 32,000 | 43 / 116 (37%) |
| 36,000 | 29 / 116 (25%) |

The median is the mean of the 58th and 59th values, **29,025 and 29,276**. So a threshold below
29,025 is exceeded by at least 59 groups and one at or above 29,150 by at most 58 — which is why the 29,000
and 29,900 rows differ by five groups over a 900-byte span. Recorded because a spill rate quoted
without its threshold cannot be checked against a median.

**One correction, recorded rather than quietly fixed.** An earlier pass of the per-group table
reported a prose median of 27,218; re-running both passes under one definition gives **27,206**.
The figures above are the reconciled pass.

## What a trimming fix would have cost, had it been built

Modelled over the same 116 groups, dropping lowest-ranked candidates until the group fit:

| budget | groups trimmed | candidates kept | groups still over on anchor+members |
|---|---|---|---|
| 25,000 | 69 / 116 | 306 / 459 (67%) | 5 |
| 30,000 | 43 / 116 | 366 / 459 (80%) | 3 |
| 35,000 | 28 / 116 | 402 / 459 (88%) | 2 |
| 40,000 | 20 / 116 | 421 / 459 (92%) | 2 |

Recorded because it is the rejected alternative's real price: at any budget that reliably fits, a
double-digit percentage of candidates never reach the consolidator, and each one is a merge it was
not offered. The spill design keeps all of them.

## Method

```sql
-- per group: members, then candidates excluding the anchor row, then the anchor
SELECT memory_uuid FROM consolidation_group_member    WHERE group_id = ?;
SELECT memory_uuid FROM consolidation_group_candidate WHERE group_id = ? AND role = 'candidate';
```

`consolidation_group_candidate` holds the anchor too, as `role='anchor'` — a first pass that summed
the whole table double-counted every anchor and inflated the maximum to 71,154. The figures above
are the corrected pass.
