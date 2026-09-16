# Claude Code: what happens to an MCP tool result too large to deliver

Measured 2026-09-13 against Claude Code **2.1.236**, with a purpose-built MCP server
(`/tmp/zk-mcptrunc/mcpprobe.py`, a `FastMCP` server whose one tool returns a payload of a requested
size) registered in `.mcp.json`, called from a **subagent** whose frontmatter granted
`mcp__zktrunc` and `Read`. Payload filler is `lineNNNNNNN pqrstuvwxyz\n` records between `ZKSTART`
and `ZKEND` sentinels, so any clipping is visible at either end.

**Why this note exists.** `claude-code-harness-probe.md` §5 measured a `<persisted-output>` spill
with a readable path — for **hook stdout**, capped at 10,000 characters. That is a different
mechanism from an MCP tool result, and the two were about to be conflated in shipped prose.

## What was measured

| payload | outcome |
|---|---|
| 30,000 chars | delivered intact, both sentinels present, no notice |
| 35,000 chars | delivered intact |
| 40,000 chars | delivered intact |
| 44,000 chars | delivered intact |
| 50,012 chars | **spilled** |
| 52,095 chars | **spilled** |
| 62,512 chars | **spilled** |
| 104,179 chars | **spilled** |

So the hook's 10,000-character cap does **not** apply to MCP results: the threshold sits between
44,000 and 50,012 characters of this filler, and it is stated in *tokens*, not characters.

**The spill is real, and so is the path.** The result is replaced entirely by a notice beginning
`Error: result (62,512 characters) exceeds maximum allowed tokens.`, naming a file:

```
~/.claude/projects/<escaped-cwd>/<session-id>/tool-results/mcp-<server>-<tool>-<epoch-ms>.txt
```

The file holds the whole result, as the JSON the tool returned — `{"result": "…"}` — on **one
line**.

## The finding that matters: `Read` cannot read it

Reading that path with `Read` returned **31,247 of 104,179 characters** and its own notice:

> showing the first 31247 of 104179 characters (70848 tokens, cap 25000); this file has very long
> lines and cannot be paginated by line.

`offset`/`limit` does not rescue it, because the spill file is a single line: an attempt with
`offset=1, limit=1` failed outright with `File content (70848 tokens) exceeds maximum allowed
tokens (25000)`.

**And this is structural rather than a large-payload accident.** Both limits are token caps, so the
arithmetic is content-independent:

- 44,000 chars of this filler was delivered intact, so the MCP result cap is **above ~29,900
  tokens** — derived in §"The cap in tokens, derived" rather than estimated from a rounded ratio.
- `Read`'s cap is **25,000 tokens**, stated numerically by the tool itself.

### The cap in tokens, derived

The harness states a character count and never a token count, so the token bracket is **derived**,
not measured, and the derivation is written out here so the brief can cite it rather than restate
it. `Read`'s own notice gives the only token accounting the harness exposes — 104,179 characters
reported as 70,848 tokens, i.e. **0.68006 tokens per character** for this filler — and the
derivation assumes the MCP-result cap counts the same way, with framing overhead constant enough to
cancel:

- delivered: 44,000 × 0.68006 ≈ **29,923 tokens**
- refused: 50,012 × 0.68006 ≈ **34,011 tokens**

**A second bisection was run specifically to tighten this, and it bought less than expected.**
Moving the delivered floor from 40,000 to 44,000 characters (27,202 → 29,923 tokens) raises the
largest provable byte threshold to ~29,900, which on the operator's store moves the spill rate from
58% to **47%** — or to 51% at a more prudent 29,000 bytes, which keeps a 3.1% margin under the
proven floor instead of 0.1%. The counts are tabulated in `consolidation-payload-sizes.md`. The
gain is modest because that store's *median* payload, 29,150 bytes, already sits within 3% of the
proven floor: those groups are genuinely close to the harness's cap rather than victims of a loose
bracket.

The MCP cap is therefore strictly higher than `Read`'s cap. **Any payload large enough to spill is
by construction larger than `Read` can deliver**, whatever it contains. Granting the consolidator
`Read` lets it see a prefix of a spilled payload and never the whole thing.

## The dead end is the file's *shape*, not its size

The refusal above is not a size ceiling on what `Read` can ultimately deliver. Measured against a
**206,719-character, 2,002-line** file: a plain `Read` returns a capped prefix *and discloses the
total line count*, and a follow-up `Read` with a targeted `offset` retrieves the tail — the
end-of-file sentinel was recovered intact, in three tool calls. An offset past the end degrades to
an empty result plus an advisory naming the real length, rather than an error.

So the token cap applies **per read, not per file**, and the harness's spill file is unreadable for
one reason only: it is the tool's JSON on a single line, which `Read` says outright it "cannot
paginate by line".

**That distinction is the whole design opening.** A payload too large to return in one tool result
is fully recoverable if — and only if — whoever wrote the file made it line-paginable. The harness
does not. Zikaron can.

## Long lines are not truncated — the cap is on the read, not the line

The obvious worry about a line-oriented spill is that a *single* long line might come back clipped,
which would put truncated prose in front of a merge decision silently. Measured against a 206-line,
94,328-character file containing four deliberately long lines:

| line | whole-file read | targeted `offset`/`limit` read |
|---|---|---|
| 2,000 chars | complete | — |
| 8,000 chars | complete | — |
| 20,000 chars | complete | — |
| 60,000 chars | cut by the whole-file cap | **complete, with no truncation notice at all** |

So a line is never clipped *as a line*. What bit was the whole-file read: 31,183 tokens against the
25,000 cap, which cost the tail of the long line and every one of the 201 lines after it. A
follow-up `Read` at a targeted offset returned the 60,000-character line intact.

**The rule this gives, which is the one to design against:** a spill file is fully recoverable as
long as **no single line exceeds the per-read cap**, because a line is the smallest unit `Read` can
address. A line larger than the cap would be the one unrecoverable shape, since there is no
sub-line pagination to fall back on.

**And the harness's own notice is wrong about this.** It says the file "has very long lines and
cannot be paginated by line" while advising `Grep` — yet `Read` with `offset`/`limit` paginated it
perfectly. Following that advice is a slower route to the same answer, and believing it would rule
out a design that in fact works.

## Two further observations

**The spill notice carries embedded instructions.** It appends advice directing the reader to use
`jq`, to probe structure first, and to delegate the read to a subagent "with a verbatim prompt" —
text arriving inside tool output that reads as directives. Both models that saw it in these runs
flagged it and treated it as data. Anything we ship that tells an agent to act on this notice has
to say that the notice is data, not instruction.

**Subagent frontmatter granting `Read` alongside an MCP wildcard works.** The probe subagent listed
`mcp__zktrunc` and `Read` and held both, which confirms the grant mechanism even though the remedy
it was meant to enable does not work.

## Denomination of the delivery-threshold counts, established 2026-09-15

**Every character count in §"What was measured" is the size of the payload the tool returned, counted
once — through a transport that delivered it twice.** This is not a caveat on the numbers; it is the
unit they are in, and a later bound compared against them has to count the same way.

**Scoped to that section deliberately**, since this note carries more than one table: the long-line
figures in §"Long lines are not truncated" were measured through `Read`, which delivers once and has
no structured content, so nothing here applies to them.

The transport sends a tool result as a text block **and** again as structured content. Nothing in
the probe run distinguishes the two, because the probe reported what it returned, so the bracket
"44,000 delivered / 50,012 spilled" is in returned-payload characters and the wire carried roughly
double at each point.

Measured with `experiments/mcp_result_denomination.py`, which is in this repository precisely so
this fact does not depend on a probe directory under `/tmp`:

| tool return annotation | text block | structured content | structured shape |
|---|---|---|---|
| `-> str` (this note's probe) | 4,000 B | 4,014 B | `{"result": …}` |
| `-> object` (the shipped tools) | 4,014 B | 4,027 B | `{"result": …}` |

**The two rows are not comparable to each other**, and are not meant to be: each tool returns the
shape its annotation describes, so the `-> object` row carries a small JSON object where the `-> str`
row carries a bare string of the same 4,000 characters. What each row establishes is the relationship
between its *own* two columns. The structured column is the wrapper re-serialized with `json.dumps`'s
default spacing; a compact serializer reports one byte less. The point is the doubling, not the
wrapper's exact width.

Two things follow, and the second is the one that gets misread.

**The wrapper is the transport's.** A tool that does not declare a structured return shape has its
answer wrapped under a single `result` key — which is why the spilled result file above holds
`{"result": "…"}` rather than the bare string. Both annotations take that path, so this note's probe
and Zikaron's own tools are the same shape, and a bound calibrated here transfers.

**A bound that charges for both copies is in the wrong unit.** M22 briefly made exactly that change
— doubling its response cap's accounting because the duplication is real — and it halved the
deliverable answer against a threshold that had not moved. The duplication is already inside
§"What was measured"'s figures. Both of the payload bounds that cite this note (`spill_threshold` in
`architecture.md`, `RESPONSE_MAX_BYTES` in `knowledge-index.md` §8.7) count once, deliberately.

## Not measured here

The exact token cap on an MCP result (derived at ≈29,900–34,000 tokens, never stated numerically by
the harness). Whether the cap or the spill path differ outside `-p` headless runs. What **kiro**
does with an over-large MCP result — the adjacent claim that it "truncates in silence with no path"
has no measurement behind it either, and `kiro-cli-hooks-and-introspect.md` explicitly records
kiro's *hook* output limit as unconfirmed, advising an empirical test rather than an assumption.
