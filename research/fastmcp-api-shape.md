# FastMCP API Shape — Research Notes

**Research date:** 2026-08-03 (per system clock). This matters a great deal for this note: the MCP Python ecosystem is mid-upheaval at this exact snapshot, with multiple packages simultaneously in the middle of major-version transitions. Treat "current" claims as time-stamped, not evergreen.

## Brief (restated)

Research the FastMCP Python package's current stable API for building an MCP server, to inform implementing `zikaron-mcp`: a thin MCP client/server that (1) exposes tools over stdio to a calling LLM agent, (2) must expose two different tool sets depending on which agent config invokes it (5 tools for "primary", 4 different tools for "consolidator"), likely via CLI flag/env var at startup, (3) needs tool handlers that are async and do no work until first invoked (no eager connection/RPC on startup), (4) must run without `asyncio.run` conflicts alongside its own internal Unix-domain-socket JSON-RPC client that talks to a separate backend service process.

---

## 1. Which package: `fastmcp` vs `mcp`'s `FastMCP` — and a critical complication

**There are two, and as of this snapshot both are simultaneously undergoing disruptive major-version transitions.**

### 1a. The standalone `fastmcp` package (PyPI: `fastmcp`, by Jeremiah Lowin / Prefect, repo `PrefectHQ/fastmcp`, docs at gofastmcp.com)

- This is the actively-developed, feature-rich, community-dominant implementation. PyPI's own project description says "FastMCP 1.0 was incorporated into the official MCP Python SDK in 2024. Today, the actively maintained standalone project is downloaded a million times a day, and some version of FastMCP powers 70% of MCP servers across all languages." (Source: https://pypi.org/project/fastmcp/, fetched 2026-08-03; self-reported marketing figures, but the "actively maintained" framing is corroborated independently — see 1c below.)
- Import: `from fastmcp import FastMCP`. Decorator: `@mcp.tool` **without parentheses** for the zero-arg case (parenthesized form `@mcp.tool(name=..., ...)` also works — see §2).
- **As of this snapshot, PyPI's "Latest release" for `fastmcp` is 3.4.5 (uploaded Jul 27, 2026)**, with release history showing: 3.4.5 → 3.4.4 → 3.4.3 → 3.4.2 → 3.4.1 → then a large gap → 3.3.2 (Dec 2024) → 0.3.1 → 0.3.0 → 0.2.0 → 0.1.0. (Source: https://pypi.org/project/fastmcp/, release history section, fetched 2026-08-03.) The gap between 3.3.2 (Dec 2024) and 3.4.1 (Jun 2026) suggests either heavy version-history pruning on PyPI's display or a long period where the "3.x" line didn't publish patch releases visible in this truncated view — I could not fully explain the gap and flag it as unverified.
- **Critically: `4.0.0a1`, `4.0.0a2`, and `4.0.0b1` pre-releases already exist** (dated Jul 21/24/28, 2026), and **the live documentation site (gofastmcp.com) defaults to serving the v4.0.0-beta docs**, with a banner reading "FastMCP 4 is in beta — build stateful applications on sessionless MCP." This means: **if you go to gofastmcp.com today without appending `/v3/` to URLs, you get beta documentation for an unreleased major version.** I had to explicitly fetch `/v3/...` paths to get docs matching the pinned-stable 3.4.5 release. This is a serious pitfall for anyone (including an LLM) reading "current" FastMCP docs at face value.
- A third-party guide (codersera.com, dated Jun 30 2026, "current as of mid-2026") independently corroborates the two-package confusion and gives a compatible but slightly different version snapshot: "Standalone FastMCP: v3.0.0 (bundles MCP 1.25.0)" vs my PyPI fetch showing 3.4.5 as latest — this is consistent with that guide being ~1 month stale relative to my fetch, not contradictory. (Source: https://codersera.com/blog/how-to-build-an-mcp-server-in-python-2026/, fetched 2026-08-03. Flag: this is a third-party blog, not vendor documentation, and contains monetization content; treat its narrative framing as secondary but its concrete version numbers as roughly corroborating.)
- Maintainer: `jlowin` (Jeremiah Lowin), org `PrefectHQ`. License Apache-2.0. Homepage/docs: gofastmcp.com.

### 1b. The official `mcp` SDK's `FastMCP` class (PyPI: `mcp`, by Anthropic/the MCP project, repo `modelcontextprotocol/python-sdk`)

- Historically: `from mcp.server.fastmcp import FastMCP`. This is "FastMCP 1.0," which was merged into the official low-level SDK in 2024 (both fastmcp's own blog post by jlowin and the official docs corroborate this: https://jlowin.dev/blog/fastmcp-2/, fetched 2026-08-03).
- **As of this snapshot, the official `mcp` package is ALSO mid-transition**, and much more disruptively than `fastmcp`: **`mcp` v2.0.0 is described by its own PyPI page as "the current stable release line"** (https://pypi.org/project/mcp/2.0.0/, fetched 2026-08-03) and by its docs as a "major rework... to support the 2026-07-28 MCP specification... and to fix long-standing architectural issues" (https://py.sdk.modelcontextprotocol.io/v2/whats-new/, fetched 2026-08-03).
- **v2 of the `mcp` SDK renames `FastMCP` to `MCPServer`** and moves the import path from `mcp.server.fastmcp` to `mcp.server.mcpserver`. The `@mcp.tool()`/`@mcp.resource()`/`@mcp.prompt()` decorator *signatures* are declared unchanged (source explicitly says: "`@mcp.tool()`, `@mcp.resource()`, and `@mcp.prompt()` accept what they accepted in v1... and the input schema still comes from your type hints"), but the class name, module path, and a long list of surrounding APIs changed. (Source: https://py.sdk.modelcontextprotocol.io/v2/whats-new/, "FastMCP is now MCPServer" section, fetched 2026-08-03.)
- One third-party source (codersera.com) describes a *different* v2 snapshot — "`mcp[cli]==2.0.0a3`... explicitly marked 'Do not use in production'... Stable v2 is targeted for 2026-07-27" — which is now **stale relative to what I fetched directly from PyPI and the official docs site**, which show v2.0.0 as an actual released stable line, not an alpha, as of my fetch. This is a clear illustration of how fast this is moving even within the span of ~1 month; I'm resolving the conflict in favor of the primary sources (PyPI project page + official SDK docs), which are more authoritative and more recently dated than the third-party blog.
- **Recommendation for pinning purposes:** given the v1→v2 rename (`FastMCP`→`MCPServer`) is a breaking, non-deprecated removal ("the old import path is gone rather than deprecated"), a project depending on `from mcp.server.fastmcp import FastMCP` should pin `mcp>=1.28,<2` if choosing this package — the v1.x line is explicitly stated to remain in "maintenance" with continued security patches, per the official migration guide's framing. (Source: https://py.sdk.modelcontextprotocol.io/migration/, "Not ready to migrate yet?" note, fetched 2026-08-03.)

### 1c. Which one is "the actively maintained / recommended one"?

- Both are separately actively maintained as of this snapshot, but they are diverging in scope and design philosophy, not just versioning:
  - The **standalone `fastmcp`** package explicitly targets richer application-framework territory: it now ships "Apps" (interactive UI-in-conversation support via `ext-apps`), a client-extensions mechanism, response caching, background tasks (via an integration with a package called `docket`), and its own enterprise gateway product ("Prefect Horizon"). Its own README states: "FastMCP is a full MCP application framework for servers, clients, and interactive apps" and explicitly separates itself from being merely a decorator wrapper.
  - The **official `mcp` SDK's v2** is repositioning itself around the *protocol's* v2026-07-28 revision specifically — session-less/stateless multi-round-trip semantics, removal of the `initialize` handshake for "modern" clients, deprecation of push-style sampling/elicitation/roots/logging (SEP-2577) — i.e., it is tracking the wire protocol closely rather than adding an app-framework layer on top.
  - A third-party guide (codersera.com) reports: "MCP co-creator David Soria Parra has publicly praised the standalone version over the official Python SDK that ships with the protocol," and independently: "Paul Iusztin, writing in June 2026, described standalone FastMCP (by Prefect) as having effectively become the practical default for MCP servers in Python." I could not independently verify these two specific attributed quotes at their primary source (I did not fetch a Soria Parra post or an Iusztin post directly) — **flag these as second-hand attributions from a single third-party blog, not confirmed against primary sources.** Given the corroborating structural evidence (feature depth, ecosystem tooling like `fastmcp install cursor`, the marketing-but-plausible "70% of servers" claim), I judge the *substance* of "standalone fastmcp is the practical default" to be reasonably well-supported, even though the specific named-person attributions are unverified by me.
  - **My synthesis for zikaron-mcp's purposes:** the standalone `fastmcp` package is the better fit for a project that wants a mature, batteries-included, actively-maintained framework and is willing to track a fast-moving ecosystem (and to pin an exact version, which this project already intends to do). The official `mcp` SDK's `FastMCP`/`MCPServer` is the better fit for a project that wants the leanest possible dependency footprint and to track the wire protocol as closely and "purely" as possible, at the cost of fewer batteries (no built-in Client-side response cache, no Apps, simpler CLI). **Given the project's stated design goals (thin server, explicit control over async/event-loop behavior, precise error semantics, in-memory test harness, minimal surprise) I lean toward recommending the standalone `fastmcp` package** because of its more mature `Client` in-memory testing story, explicit and well-documented `ToolError`/`mask_error_details` error model, and explicit lazy-loading documentation (see §5–7 below) — but this is a judgment call the implementer should confirm against their own constraints, especially dependency-tree size (see §8).

### 1d. Does the standalone `fastmcp` require a separate dependency from the low-level `mcp` SDK?

**Yes — and the dependency structure is non-obvious and worth flagging explicitly.** I fetched `PrefectHQ/fastmcp`'s actual `pyproject.toml` from GitHub and found:

- The top-level `fastmcp` PyPI package is now a **thin, dynamically-versioned meta-package**. Its `pyproject.toml` declares `dynamic = ["version", "dependencies", "optional-dependencies"]` and its real dependency is generated via a Hatch/uv-dynamic-versioning hook as: `fastmcp-slim[client,server]=={{ version }}`.
- In other words: **`pip install fastmcp` transitively installs a package called `fastmcp-slim`**, which is the package that actually contains the `fastmcp/` Python source tree (per `fastmcp_slim/pyproject.toml`'s `[tool.hatch.build.targets.wheel] packages = ["fastmcp"]`).
- `fastmcp-slim`'s own base dependencies (i.e., what you always get) are: `mcp-types>=2.0.0,<3.0.0`, `platformdirs>=4.0.0`, `pydantic[email]>=2.12.0`, `pydantic-settings>=2.0.0`, `python-dotenv>=1.1.0`, `rich>=13.9.4`, `typing-extensions>=4.0.0`.
- Its `[server]` extra (needed for building servers, and implicitly required by the meta-package's `fastmcp-slim[client,server]` dependency) adds: `fastmcp-slim[mcp]` (see below), `authlib>=1.6.11`, `cyclopts>=4.0.0`, `griffelib>=2.0.0`, `jsonref>=1.1.0` (note: my fetch of this section was truncated mid-line at `joserfc>=1.` — I was not able to fully enumerate the `[server]` extra's tail; flagging as incomplete).
- Critically: **`mcp-types`, not the full `mcp` SDK package, is the actual dependency** — this is the standalone protocol-types-only package that the official SDK's own v2 rework *also* split out (see §1b: "The wire types moved to `mcp-types`... It depends on nothing but pydantic and typing-extensions"). This means **the standalone `fastmcp` package does NOT depend on the full official `mcp` SDK package** (with its Starlette/uvicorn/httpx2 server stack) — it depends only on the lightweight shared protocol-schema package `mcp-types`, and implements its own server/transport/client stack independently. This is an important clarification of the brief's framing: it is not "fastmcp needs a separate dependency *from* the low-level mcp SDK" in the sense of *also* needing `mcp` — rather, fastmcp and the official `mcp` package both depend on the shared `mcp-types` schema package but are otherwise independent implementations that do not depend on each other.
- (Source for all of the above: direct fetch of `https://raw.githubusercontent.com/PrefectHQ/fastmcp/main/pyproject.toml` and `https://raw.githubusercontent.com/PrefectHQ/fastmcp/main/fastmcp_slim/pyproject.toml`, fetched 2026-08-03. These are primary-source files, not documentation describing them, so I am confident in this reading, modulo the truncation noted above.)

**Practical pinning consequence:** if you `pip install fastmcp==3.4.5` (or whatever exact version you pin), pip/uv will resolve `fastmcp-slim` and its extras automatically — you do not need to separately declare `fastmcp-slim` or `mcp-types` in your own `pyproject.toml`; they come transitively. But be aware that a lockfile (e.g., `uv.lock`) will show `fastmcp-slim` as the package actually providing the code, which can be confusing when auditing the dependency tree.

---

## 2. Exact code shape: creating a server, registering an async tool, decorator signature

(All of the below is from https://gofastmcp.com/v3/servers/tools, the version-pinned v3 docs, cross-checked against the live default (v4-beta) docs at https://gofastmcp.com/servers/tools which showed near-identical decorator behavior — I flag the handful of v3-vs-v4 differences inline. Both fetched 2026-08-03.)

### Minimal server + tool

```python
from fastmcp import FastMCP

mcp = FastMCP(name="CalculatorServer")


@mcp.tool
def add(a: int, b: int) -> int:
    """Adds two integer numbers together."""
    return a + b
```

- **Decorator without parentheses** (`@mcp.tool`) is the primary documented form for the standalone package. Contrast with the official `mcp` SDK, which requires parentheses (`@mcp.tool()`) — this decorator-syntax mismatch is called out explicitly by multiple sources as *the* most common source of copy-paste bugs between the two ecosystems (codersera.com: "the decorator syntax differs: the official SDK uses `@mcp.tool()` with parentheses, while standalone FastMCP uses `@mcp.tool` without parentheses").
- FastMCP automatically: uses the function name as the tool name, parses the docstring for the tool description (and per-parameter descriptions if in Google/NumPy/Sphinx style), generates the input schema from the function's parameters and type annotations, and handles parameter validation/error reporting.
- **Restriction:** functions with `*args` or `**kwargs` are **not supported** as tools ("this restriction exists because FastMCP needs to generate a complete parameter schema for the MCP protocol, which isn't possible with variable argument lists").

### Overriding name/description/etc. — the parenthesized decorator-arguments form

```python
@mcp.tool(
    name="find_products",  # Custom tool name for the LLM
    description="Search the product catalog with optional category filtering.",
    tags={"catalog", "search"},
    meta={"version": "1.2", "author": "product-team"},
)
def search_products_implementation(query: str, category: str | None = None) -> list[dict]:
    """Internal function description (ignored if description is provided above)."""
    ...
```

- `name: str | None` — overrides the function name as the exposed tool name.
- `description: str | None` — if set, **the function's docstring is ignored for the tool description**, though docstring-derived *per-parameter* descriptions still apply.
- `tags: set[str] | None` — for organization/filtering (used by `mcp.enable()`/`mcp.disable()` visibility controls — see §3).
- `annotations: ToolAnnotations | dict | None` — MCP protocol-level hints (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`, `title`) that clients like Claude/ChatGPT use to decide e.g. whether to skip confirmation prompts.
- `meta: dict[str, Any] | None` — passed through to the client as the tool object's `meta` field; for custom metadata/versioning.
- `timeout: float | None` — execution timeout in seconds; exceeding it returns an MCP error with code `-32000`.
- `output_schema: dict[str, Any] | None` — override the auto-generated output schema.
- `run_in_thread: bool` (default `True`) — **sync-function-only**: whether a sync `def` tool is dispatched to a thread pool (default) or run inline on the event loop thread (`False`, for thread-affine libraries like `pywin32`/`tkinter`). **Ignored for async functions, which always run on the event loop.** This is directly relevant to the brief's requirement #3 (async handlers that only run on invocation) — async tools are the natural fit and this flag is irrelevant to them.
- One v3-vs-v4-beta doc difference I noticed: v3 docs list `enabled: bool` (default `True`, described as "Deprecated in v3.0.0. Use `mcp.enable()` / `mcp.disable()` at the server level instead") as a decorator argument; the v4-beta docs I also fetched dropped `enabled` from the parameter list entirely and instead list `icons`, `title`, and a docs-generation quirk where `title`'s fallback behavior for missing-title tools with some clients is spelled out more explicitly ("some MCP clients drop tools that have no title at all" — this specific warning appears only in the v4-beta docs, not verified against v3 wording, and may be new information rather than a v4-only *behavior* change). Treat `enabled=` as deprecated-but-present in the pinned v3.4.5 line; use `mcp.enable()`/`mcp.disable()` going forward regardless.

### How type hints/docstrings become the schema

- Standard Python type annotations (`int`, `str`, `bool`, `bytes`, `datetime`/`date`/`timedelta`, `list[X]`/`dict[K,V]`/`set[X]`, `X | None`/`Optional[X]`, `Union[X,Y]`, `Literal[...]`/`Enum`, `Path`, `UUID`, arbitrary Pydantic models) are all converted into the JSON-Schema input schema FastMCP sends the client. All Pydantic-field-compatible types work, including custom Pydantic types.
- Parameters without a default are `required`; parameters with a default become optional in the schema, following ordinary Python semantics.
- Docstrings are parsed for both the overall tool description and per-parameter descriptions; **Google, NumPy, and Sphinx docstring styles are all supported** (the parser tries each style in turn).
- Per-parameter descriptions can also be set explicitly and take precedence over docstring-derived ones, via `Annotated[x, "some description"]` (shorthand) or `Annotated[x, Field(description=...)]` (full Pydantic `Field`, also supporting `ge`/`gt`/`le`/`lt`, `min_length`/`max_length`, `pattern`, etc. for validation constraints that get enforced *before* your function runs).
- To hide a parameter from the LLM entirely (inject it server-side — e.g. for a `user_id` or DB connection), use `Depends()` dependency injection: `def get_user_details(user_id: str = Depends(get_user_id)) -> str: ...`.
- **Validation mode:** by default FastMCP uses Pydantic's flexible/coercive validation (e.g. a client sending `"10"` for an `int` param is coerced), which improves compatibility with LLM clients that often send stringified values. `FastMCP(..., strict_input_validation=True)` at server construction switches to the MCP SDK's strict JSON-Schema validation, rejecting type mismatches outright.

---

## 3. Conditionally registering only a subset of tools (5 vs. 4, per agent config)

**There is no documented, named FastMCP feature literally called "conditional tool sets" or "same binary, different surface depending on config." This is an application-level pattern you build yourself; I found no first-party guidance specifically matching the brief's exact scenario.** However, the docs do surface several composable primitives that directly support it, and I did find one closely-related community pattern worth citing. Below is what is documented, clearly separated from what I am inferring/synthesizing as the recommended approach.

### Documented primitives that compose into the pattern

1. **Server-level `enable()`/`disable()` with tag filtering (this IS documented, and is the closest first-party match).** From https://gofastmcp.com/servers/tools (both v3 and v4-beta docs; identical wording):
   ```python
   @mcp.tool(tags={"admin"})
   def admin_action() -> str: ...


   @mcp.tool(tags={"public"})
   def public_action() -> str: ...


   # Disable specific tools by key
   mcp.disable(
       names={"admin_action"}
   )  # v4-beta spelling; v3 docs show mcp.disable(keys={"tool:admin_action"})

   # Disable tools by tag
   mcp.disable(tags={"admin"})

   # Or use allowlist mode — only enable tools with specific tags
   mcp.enable(tags={"public"}, only=True)
   ```
   **Note a real API-surface discrepancy I found between v3 and v4-beta docs for this exact call:** the v3 tools page uses `mcp.disable(keys={"tool:admin_action"})` (a `keys=` param taking `"tool:name"`-prefixed strings) and a constructor arg named `on_duplicate_tools=`, while the v4-beta tools page uses `mcp.disable(names={"admin_action"})` (a `names=` param taking bare names) and `on_duplicate=` (dropping `_tools`). **This means the exact keyword-argument spelling for `enable`/`disable` changed between v3 and v4 — pin to v3.4.5 and use the v3 spelling (`keys={"tool:...":...}`) if targeting that exact version; do not blindly copy v4-beta doc snippets.** Disabled tools "don't appear in `list_tools` and can't be called."

2. **`mcp.add_tool(fn)` / dynamic registration at any point before `run()`.** Tools don't have to be registered via the decorator at import time; you can call `mcp.add_tool(some_function)` programmatically. This is documented under "Using with Methods" (for binding instance methods with correct schemas) but the mechanism is general.

3. **`mcp.local_provider.remove_tool("name")`** — dynamically remove a tool after registration, documented under "Removing Tools."

4. **The `on_duplicate_tools`/`on_duplicate` constructor argument** controls what happens if you register the same name twice (`"warn"` default / `"error"` / `"replace"` / `"ignore"`) — relevant if a shared "always-on" tool module is registered into both a primary-mode and consolidator-mode server and you want to guard against accidental collisions.

### What I did NOT find documented

- I did not find a first-party FastMCP doc page titled anything like "Conditional Tools" or "Environment-based tool registration." My web search for "fastmcp conditionally register tools based on environment variable startup config" returned no first-party gofastmcp.com hits matching that exact scenario; the closest hits were: (a) a third-party project `ragieai/dynamic-fastmcp` that extends the *official* `mcp` SDK (not standalone fastmcp) with "dynamic tool capabilities... that adapt their behavior and descriptions based on request context, user information, and path parameters" — this is a different problem (per-request personalization, not per-process startup config) and is a third-party GitHub project, not officially documented; (b) a Gist titled "FastMCP v3 Visibility + schema-in-response workaround for Windsurf" describing exactly the "N tools visible at startup, everything else hidden until asked" pattern using FastMCP v3's tag-based Visibility transforms — this independently corroborates that tag-based `enable`/`disable` (item 1 above) is the community-recognized mechanism for this class of problem, but it's a third-party gist, not vendor docs, and addresses progressive-disclosure (hide-then-reveal-on-request) rather than fixed-at-startup mode selection.

### My synthesized recommendation for zikaron-mcp (not a documented FastMCP feature — this is my own design inference from the primitives above)

Two realistic approaches, both fully supported by the documented primitives:

**Approach A — one `FastMCP` instance, conditional decoration at module load time.** Read the CLI flag/env var *before* constructing the `FastMCP` object, then only execute the `@mcp.tool` decorator calls for the relevant subset:
```python
import os
mcp = FastMCP(name="zikaron-mcp")

MODE = os.environ.get("ZIKARON_MODE", "primary")  # or a CLI-parsed value

if MODE == "primary":
    @mcp.tool
    async def tool_a(...): ...
    # ... 4 more primary-only tools
else:  # consolidator
    @mcp.tool
    async def tool_x(...): ...
    # ... 3 more consolidator-only tools
```
This is the simplest, most literal reading of "read a CLI arg or env var before building the server" from the brief, and it is fully consistent with every documented mechanism above (nothing in the decorator or constructor forbids conditional registration; tool registration is just ordinary Python function calls under the hood). **I did not find this exact pattern named/blessed in FastMCP docs, but nothing contradicts it either, and the "tag + enable/disable" mechanism (item 1) is evidence the maintainers expect and support selective tool surfaces.**

**Approach B — tag every tool at definition time, register all of them unconditionally, then call `mcp.enable(tags={mode}, only=True)` once at startup based on the CLI/env value.** This is closer to the documented `enable`/`disable` allowlist pattern and has the advantage that all tool code always exists in the same importable module (useful for a single test suite exercising both tool sets against one `FastMCP` instance, at the cost of a `disable`-filtered list vs. two truly separate schemas). Given the brief explicitly frames this as "5 tools" vs. "4 *different* tools" (not "5 tools, 4 of which overlap"), Approach A (fully separate registration, nothing shared) is likely the better fit for zikaron-mcp's stated requirements, since there's no indication of overlap to be gained from a shared-tag scheme.

**Neither approach requires "building two separate FastMCP instances"** in the sense of running two servers — you construct exactly one `FastMCP` object per process invocation (which is what you want, since you only run one `mcp.run()` per process anyway), and the mode decision happens once, before that single object's tool set is finalized, then `mcp.run()` is called normally. The brief's phrasing ("versus building two separate FastMCP instances") suggests the implementer was already leaning toward Approach A; the research does not contradict that instinct, but also doesn't provide a canonical vendor answer, since none exists.

---

## 4. Running for stdio transport: exact entrypoint, asyncio.run behavior, coexistence with your own async setup

This section is the most safety-critical for the brief's requirement #4 (no `asyncio.run` conflicts with an internal Unix-socket JSON-RPC client). **Findings are unambiguous and well-documented, cross-checked in three independent places (v3 docs, v4-beta docs, and a third-party guide), all agreeing.**

### The `run()` method

```python
from fastmcp import FastMCP

mcp = FastMCP(name="MyServer")


@mcp.tool
def hello(name: str) -> str:
    return f"Hello, {name}!"


if __name__ == "__main__":
    mcp.run()  # defaults to stdio transport
```

- `run()` with **no arguments defaults to stdio transport.** (Source: https://gofastmcp.com/v3/deployment/running-server, "STDIO Transport (Default)" section, explicitly: "When you call `run()` without arguments, your server uses STDIO transport.")
- Explicit spelling is also supported: the docs example table lists stdio's "How it runs" column simply as `mcp.run()` (no `transport=` kwarg needed, though nothing suggests `transport="stdio"` would be rejected — I did not find an explicit test of that exact kwarg spelling in the v3/v4 docs I fetched, but every transport-selection example elsewhere in the docs uses the pattern `mcp.run(transport="streamable-http", ...)`/`mcp.run(transport="sse", ...)`, strongly implying `transport="stdio"` is the symmetric, equally-valid explicit spelling — this is a reasonable inference, not something I saw spelled out character-for-character in the fetched pages).
- **`run()` internally calls `asyncio.run()` (or equivalent) itself — it creates its own async event loop.** Direct quote from https://gofastmcp.com/v3/deployment/running-server, "Async Usage" section: *"The `run()` method we've been using is actually a synchronous wrapper around the async server implementation... The `run()` method **cannot be called from inside an async function** because it creates its own async event loop internally. If you attempt to call `run()` from inside an async function, you'll get an error about the event loop already running."*

### The escape hatch: `run_async()`

- For code that is **already running in an async context** (which describes zikaron-mcp's stated requirement #4 precisely, if the internal Unix-socket client setup needs to happen inside an event loop before/around serving), FastMCP provides `run_async()`:
  ```python
  from fastmcp import FastMCP
  import asyncio

  mcp = FastMCP(name="MyServer")


  @mcp.tool
  def hello(name: str) -> str:
      return f"Hello, {name}!"


  async def main():
      # Use run_async() in async contexts
      await mcp.run_async(transport="http", port=8000)


  if __name__ == "__main__":
      asyncio.run(main())
  ```
  Docs state explicitly: *"Always use `run_async()` inside async functions and `run()` in synchronous contexts. Both `run()` and `run_async()` accept the same transport arguments, so all the examples above apply to both methods."* (Same source as above.)

### Direct answer to the brief's requirement #4

- **If zikaron-mcp's `main()` needs to be `async def` at all** (e.g., to `await` some async setup of its Unix-socket client machinery, or to interleave with other async code) **it must call `await mcp.run_async(transport="stdio")` rather than `mcp.run()`**, and its own top-level entrypoint must then be a **synchronous** function that itself calls `asyncio.run(main())` exactly once — you cannot nest two independent `asyncio.run()` calls (one from your own code, one implicitly inside FastMCP's `run()`) in the same process; you must pick exactly one top-level `asyncio.run()` (yours) and thread everything, including FastMCP serving, through `run_async()` inside it.
- **If zikaron-mcp's own Unix-socket JSON-RPC client code is itself lazy** (as required by requirement #3 — no eager connection until a tool is actually invoked) **then it likely does not need its own async context at import/startup time at all**, and the simplest and safest design is: top-level entrypoint is a plain synchronous function, it parses CLI args/env vars, constructs the `FastMCP` instance and conditionally registers tools per §3, then calls the plain synchronous `mcp.run()` (which internally manages its own single `asyncio.run()`-equivalent loop for the whole server lifetime). Tool handler bodies, which are themselves `async def` functions per requirement #3, run *inside* that same loop when invoked, and can freely construct/use the Unix-socket client's async connection at that point, entirely within FastMCP's event loop — no separate `asyncio.run()` is needed for the socket client because it never needs to run outside of a tool invocation, which is already inside FastMCP's loop.
- **The only scenario that genuinely requires `run_async()` + your own `asyncio.run()`** is if you need async work to happen *before* FastMCP starts serving requests (e.g., a mandatory async handshake with the backend service that must succeed before the server even starts accepting `tools/list`) — but this directly conflicts with requirement #3's "no eager connection... until first invoked" design goal, so for zikaron-mcp specifically, **the plain synchronous `mcp.run()` (stdio-default) is very likely the correct and sufficient entrypoint, with no need for `run_async()` at all**, given the stated design already wants zero eager connection work.

### What none of the documentation addresses explicitly

I did not find any FastMCP doc discussing coexistence with a *second, independent* async system (like a raw `asyncio`-based Unix-socket client library maintained outside of any request/tool-invocation lifecycle) running in the same process. The guidance above is my inference from the documented `run()`/`run_async()` contract, not something I found spelled out for this exact multi-async-system scenario. If the socket client library has its own persistent background task/connection-pool that must be kept alive across multiple tool invocations (rather than opened fresh per-call), that persistent state would need to live as something FastMCP's event loop can reach from within a tool handler — most naturally via the **lifespan** mechanism the official `mcp` SDK's v2 docs describe in detail (an `@asynccontextmanager` passed as `lifespan=` to the server constructor, entered once at startup and exited once at shutdown, whose yielded object becomes reachable from every handler via a context object). I did not confirm whether the standalone `fastmcp` package's `FastMCP` constructor has an equivalent `lifespan=` parameter in v3.4.5 specifically — **this is a gap I was not able to close and flag as an open question for a follow-up read of `gofastmcp.com/v3/servers/server`** (the "FastMCP Server" overview page, not fetched in this research pass).

---

## 5. Error handling: exceptions, `ToolError`, `mask_error_details`, and returning custom error shapes as data

Confirmed identically across both v3 and v4-beta docs (https://gofastmcp.com/v3/servers/tools and https://gofastmcp.com/servers/tools, "Error Handling" section, both fetched 2026-08-03).

### Default behavior: exceptions become MCP tool error responses, server does not crash

Direct quote: *"If your tool encounters an error, you can raise a standard Python exception (`ValueError`, `TypeError`, `FileNotFoundError`, custom exceptions, etc.) or a FastMCP `ToolError`. **By default, all exceptions (including their details) are logged and converted into an MCP error response to be sent back to the client LLM.** This helps the LLM understand failures and react appropriately."*

- So: **the server does not crash**, and **the calling LLM does see the error** — this directly answers the brief's question. The default is maximally informative (full exception details surfaced to the client).

### Masking internal details for security

Two mechanisms, and they interact:
1. `FastMCP(name="SecureServer", mask_error_details=True)` at server construction — masks *all* exception details by default, replacing them with a generic message.
2. `raise ToolError("some message")` inside a tool — explicit `ToolError` messages are **always** sent to clients "regardless of mask_error_details setting." So `ToolError` is the tool author's way of saying "this specific message is safe to always show, even in a hardened deployment," while an ordinary `raise ValueError(...)` respects the server-wide masking policy.
```python
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError


@mcp.tool
def divide(a: float, b: float) -> float:
    """Divide a by b."""
    if b == 0:
        raise ToolError("Division by zero is not allowed.")  # always shown
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        raise TypeError("Both arguments must be numbers.")  # masked if mask_error_details=True
    return a / b
```
When `mask_error_details=True`, "only error messages from `ToolError` will include details, other exceptions will be converted to a generic message."

### Can a tool return a custom error/conflict shape as normal JSON data rather than raising?

**Yes, unambiguously, and this is a first-class documented pattern, not a workaround.** The "Return Values" section makes clear that a tool can simply `return` a dict/dataclass/Pydantic model describing any application-level outcome — success, conflict, validation-failure, whatever — and FastMCP will serialize it as both `content` (JSON text for the model to read) and `structured_content` (typed data for programmatic clients), with `is_error` remaining `False` throughout. For full control, `ToolResult(content=..., structured_content=..., meta=...)` gives explicit control over the exact response shape while still not being an "error" in the protocol sense. Nothing about FastMCP requires distinguishing "success" from "the operation completed but found a conflict" at the transport level — that's an application-level modeling decision the tool author is free to make by choosing between raising (which flips `is_error=True` on the MCP result) and returning (which keeps `is_error=False` and lets the caller inspect the returned shape). This maps directly onto the brief's "return a custom error/conflict shape as normal JSON data rather than raising" question: **yes, trivially, by just not raising** — return a Pydantic model like `class ConflictResult(BaseModel): status: Literal["conflict"]; existing_id: str` and it becomes ordinary `structured_content`.

---

## 6. Testing: in-memory client, no subprocess

Confirmed strongly and in detail, both from the standalone `fastmcp` package's own docs and from the official `mcp` SDK v2's docs — **this pattern is universal across both ecosystems and is explicitly the officially-recommended default testing approach for both.**

### Standalone `fastmcp`: `fastmcp.Client`

From https://gofastmcp.com/clients/client (fetched under the v4-beta default path, but the mechanism described — in-memory transport — matches the general `Client` design described consistently elsewhere, including v3's own `servers/testing` page which I fetched and which shows an essentially identical `Client(mcp, raise_exceptions=True)` pattern under a `pytest` fixture):

```python
from fastmcp import Client, FastMCP

# In-memory server (ideal for testing)
server = FastMCP("TestServer")
client = Client(server)  # <-- pass the FastMCP object directly


async def main():
    async with client:
        tools = await client.list_tools()
        result = await client.call_tool("example_tool", {"param": "value"})
```

Direct quote: *"**In-memory transport** connects directly to a FastMCP server instance within the same Python process. Use this for testing and development where you want to eliminate subprocess and network complexity. The server shares your process's environment and memory space."* And: `Client(server)` is explicitly listed first in the "Choosing a Transport" comparison, with the comment `# In-memory, no network or subprocess`.

The v3-specific "Testing" doc page (https://gofastmcp.com/v3/servers/testing, fetched directly) shows the fully worked pytest pattern:
```python
import pytest
from fastmcp.client import Client
from fastmcp.client.transports import FastMCPTransport
from my_project.main import mcp


@pytest.fixture
async def main_mcp_client():
    async with Client(transport=mcp) as mcp_client:
        yield mcp_client


async def test_list_tools(main_mcp_client: Client[FastMCPTransport]):
    list_tools = await main_mcp_client.list_tools()
    assert len(list_tools) == 5
```
This is directly relevant to zikaron-mcp: **a unit test can assert `len(list_tools) == 5` for the primary config and `== 4` for the consolidator config**, by constructing the `FastMCP` instance twice (once per mode) and connecting an in-memory `Client` to each — no subprocess, no stdio pipes, no real process spawn. The docs also recommend `pytest-asyncio` with `asyncio_mode = "auto"` in `pyproject.toml` so async test functions don't need per-test `@pytest.mark.asyncio` decoration, and recommend the `inline-snapshot` library for asserting on complex `CallToolResult` structures.

### Official `mcp` SDK v2: also `Client(server_instance)`, replacing an older explicit helper

The official SDK's v2 docs (https://py.sdk.modelcontextprotocol.io/v2/llms-full.txt, fetched 2026-08-03) show the identical pattern, and are explicit that this *replaces* an older, more awkward v1 helper:

```python
from mcp import Client
from server import mcp  # an MCPServer instance


async def main() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("add", {"a": 1, "b": 2})
        print(result.structured_content)
```
And, describing the migration from v1: *"`create_connected_server_and_client_session` removed... Use `mcp.client.Client` instead — it accepts a `Server` or `MCPServer` instance directly and handles the in-memory transport and session setup for you."* The v2 docs also explicitly frame this as the reason their own documentation is trustworthy: *"every one of them is exercised by the SDK's own test suite through an in-memory client... If a change to the SDK breaks an example on one of these pages, CI goes red before the page does."*

**One subtlety specific to the official SDK's v2 line, worth flagging for anyone testing elicitation/sampling/interactive flows (probably not directly relevant to zikaron-mcp's 5-tool/4-tool surface, but worth noting for completeness):** `Client(server)` negotiates the newer "2026-07-28" sessionless protocol era by default, which has no server-initiated request channel; a v1-style tool using `ctx.elicit()` will fail against a bare `Client(server)` and needs `Client(server, mode="legacy", ...)` to reproduce the old synchronous back-and-forth for testing. This is unlikely to matter for a "thin" set of 5/4 tools with no interactive elicitation, but is worth remembering if any consolidator-mode tool turns out to need mid-call user input down the line.

**Both ecosystems' testing story is directly compatible with a design requirement to unit-test tool bodies and assert on `CallToolResult`/`structured_content` without a subprocess.**

---

## 7. Lazy initialization: does merely constructing `FastMCP` and calling `run()` trigger any tool logic eagerly?

**This is the single most important question for the brief's stated design requirement ("the client provably makes no service call until the model calls a tool"), and the documentary evidence strongly supports "no eager execution," though I want to be precise about exactly what is and isn't directly confirmed.**

### Direct evidence for lazy tool-body execution

1. **Decoration ≠ execution.** Every single code example across both packages' docs shows the pattern `@mcp.tool` (or `@mcp.tool()`) decorating a function definition — this is a standard Python decorator applied at *function-definition* time (i.e., at module import time), and decorating a function has never in either package's documented behavior been described as *calling* that function. The decorator's documented job is purely registration/schema-generation ("Uses the function name as the tool name... Parses the function's docstring... Generates an input schema... Handles parameter validation") — nowhere in any fetched doc page is there language suggesting the decorated function body is invoked during decoration, server construction, or `run()`.
2. **Explicit confirmation for the sibling primitive, Resources:** the standalone package's Resources docs (https://gofastmcp.com/servers/resources, snippet surfaced via search, fetched 2026-08-03) state directly: *"**Lazy Loading:** The decorated function (`get_greeting`, `get_config`) is only executed when a client specifically requests that resource URI via `resources/read`."* While this is stated specifically about *resources*, not tools, the mechanism (decorator registers a callable; callable is invoked only on the matching protocol verb) is structurally identical for tools (`tools/call` is the analogous verb to `resources/read`), and every description of `tools/call` I found in both packages' docs (e.g. official SDK's "When an LLM decides to use a tool: 1. It sends a request... 2. FastMCP validates... 3. Your function executes... 4. The result is returned") frames execution as happening strictly in response to an incoming `tools/call` request, never at any other point in the server lifecycle.
3. **Explicit confirmation from the official `mcp` SDK v2 troubleshooting page**, which is unusually blunt about *when* tool code runs: *"`@mcp.tool` without parentheses raises **at import time** (this raises when the module is imported, before any client connects)"* — this passage is explicitly contrasting the *decorator-misuse* error (which does fire at import time, because it's a Python-level `TypeError` from the decorator call itself, not from your tool body) against the *normal* case, and by implication confirms that in the normal case (parenthesized/correct decoration), nothing fires at import time; only a decoration-syntax mistake does. The same troubleshooting page's "My host lists zero tools" section further reinforces the request-response framing throughout, with zero mention of any tool ever executing outside of an actual `tools/call`.
4. **`server/discover` / `initialize` are the only things that fire "for free" on connection**, and neither of those touches tool bodies. The official SDK v2 docs are explicit that connecting sends exactly one lightweight negotiation call (`server/discover` in the new sessionless era, or the classic `initialize` handshake in the legacy era) which returns server identity/capabilities/instructions — **this metadata comes from server *construction* arguments (name, instructions, capabilities derived from which handler types were registered), not from executing any tool.** `tools/list` similarly only returns each `Tool` object's already-computed metadata (name/description/schema, all computed once at decoration time from the function's signature/docstring, not by calling the function) — I confirmed this directly by reading the "Try it" walkthroughs in both packages' "First steps"/"Quickstart" pages, none of which show or describe any tool body executing during `tools/list`.

### What I did not find: an explicit, single blanket vendor statement of the form "constructing `FastMCP()` and calling `mcp.run()` never executes any tool body"

I looked directly for this sentence and did not find it phrased that generally in either package's docs (my search query "FastMCP constructor lazy tool function only runs when called tools/call" surfaced the Resources lazy-loading quote above and several tangential hits — a Stack Overflow thread about a different bug, and third-party "lazy MCP discovery" tooling proxies unrelated to this question — but no single first-party page states the tools-specific version of this claim as a blanket, standalone assertion). **My confidence in "no eager tool execution" is therefore built from consistent, convergent, multiply-corroborated indirect evidence (the decorator's documented job description, the explicit Resources lazy-loading statement, the request-response framing of `tools/call` throughout every doc page describing it, and the troubleshooting page's import-time-vs-runtime framing) rather than from one single unambiguous vendor quote naming tools specifically.** I judge this evidence to be strong — every piece of documentation I found is consistent with lazy execution and none contradicts it — but flag it as *synthesized from strongly convergent indirect evidence* rather than *a single directly-quotable guarantee*, since the brief specifically asked me to "confirm" this and I want to be honest about the shape of the confirmation.

### Practical implication for zikaron-mcp

Given the above, the recommended design is safe: constructing the `FastMCP`/`MCPServer` object, registering tools (conditionally per §3), and calling `mcp.run()` will not touch your internal Unix-socket client code at all, **as long as the Unix-socket client object itself is only constructed/connected *inside* a tool handler's body** (i.e., your own code, not FastMCP's, is what determines eagerness at the "does my socket client connect on import" layer — FastMCP will not force that connection to happen early; it's entirely up to how you write the tool bodies). This means the actual "provably no service call until the model calls a tool" guarantee ultimately rests on your own tool-handler code doing lazy connection setup (e.g., constructing the socket client inside the `async def` tool function or via a lazily-initialized module-level singleton that only connects on first `.call()`), not on any special FastMCP feature — FastMCP's contribution is simply "it will not call your tool function for any reason other than an actual `tools/call` request," which the evidence above supports.

---

## 8. Minimum Python version and dependency tree

### Standalone `fastmcp` (3.4.5)

- **Requires Python >=3.10.** Classifiers list explicit support for 3.10, 3.11, 3.12, 3.13. (Source: PyPI project page metadata, https://pypi.org/project/fastmcp/, fetched 2026-08-03, and confirmed identically in the GitHub `pyproject.toml`'s `requires-python = ">=3.10"`.)
- **Direct dependencies (via the real underlying package, `fastmcp-slim`, since `fastmcp` itself is a thin meta-package — see §1d):**
  - Base (always installed): `mcp-types>=2.0.0,<3.0.0`, `platformdirs>=4.0.0`, `pydantic[email]>=2.12.0`, `pydantic-settings>=2.0.0`, `python-dotenv>=1.1.0`, `rich>=13.9.4`, `typing-extensions>=4.0.0`.
  - `[client]` extra (needed for the `Client`/testing functionality): `fastmcp-slim[mcp]` (an internal extra, contents not separately confirmed — I did not fetch far enough to see what `[mcp]` itself contains), `authlib>=1.6.11`, `py-key-value-aio[filetree,keyring,memory]>=0.4.4,<0.5.0`.
  - `[server]` extra (needed for building servers): `fastmcp-slim[mcp]`, `authlib>=1.6.11`, `cyclopts>=4.0.0`, `griffelib>=2.0.0`, `jsonref>=1.1.0`, `jsonschema-path>=0.3.4`, and at least one more (`joserfc>=1....`) that I was unable to fully read due to fetch truncation.
  - Since the top-level `fastmcp` package's dependency is `fastmcp-slim[client,server]`, **both the `[client]` and `[server]` extras are installed unconditionally** when you `pip install fastmcp` — you cannot install a client-only or server-only slim subset via the top-level package name (the docs do mention a separate, even-thinner "Client-Only Package" exists — referenced in the docs nav as `/clients/client-only-package` — but I did not fetch that page to confirm its exact PyPI name or contents; flagging as an unexplored lead for anyone who specifically wants to minimize the client-side footprint).
  - PyPI's "Provides-Extra" list for the top-level `fastmcp` package additionally shows optional extras: `anthropic`, `apps`, `azure`, `code-mode`, `gemini`, `openai`, `tasks` — none of which are needed for a plain stdio tool server and none of which are installed by default.
  - **This is not a small dependency tree.** Between Pydantic (with its own compiled-core dependency, `pydantic-core`), Starlette/uvicorn-class HTTP-serving dependencies pulled in transitively by the `[mcp]`/`[server]` extras (needed even for a stdio-only server, since the same package supports HTTP transports too and the extras aren't split per-transport), `authlib` (OAuth), and the various schema/CLI tooling packages (`cyclopts`, `griffelib`, `jsonschema-path`), a project pinning `fastmcp==3.4.5` should expect on the order of 15-25+ transitive packages, not a handful. **If minimizing dependency-tree size is a hard project goal, the official `mcp` SDK (see below) is very likely materially lighter**, though I did not do a byte-for-byte transitive dependency count for either package.

### Official `mcp` SDK (v1.x line, if pinning `mcp<2` to keep the `FastMCP` class name / avoid the `MCPServer` rename)

- I did not separately re-fetch the v1.x-specific dependency list in this pass (my dependency-tree fetch, https://py.sdk.modelcontextprotocol.io/get-started/installation/, was served under the site's v2-default routing and describes v2's installation requirements) — but the v2 installation page is explicit that Python 3.10+ is required (matching the standalone package) and enumerates the direct dependencies clearly:
  - `mcp-types` (the split-out protocol-types package, versioned in lockstep with the SDK — "exact-pinned to the SDK version").
  - `anyio` (the async runtime abstraction; "the whole SDK is written against anyio, so it runs on either `asyncio` or `trio`" — **this is directly relevant to the brief's async-coexistence concern**: the official SDK is anyio-based, meaning it is not hard-committed to `asyncio` specifically, which may ease coexistence with other async code depending on how that other code is structured).
  - `pydantic` (schema generation/validation, same role as in fastmcp).
  - `httpx2` (a v2-only fork-of-httpx dependency for the SDK's own HTTP client/server transports — **this is itself a v2-specific change**; v1.x almost certainly depends on plain `httpx` + `httpx-sse` instead, per the migration guide's explicit "`httpx` and `httpx-sse` replaced by `httpx2`" section, which frames this replacement as one of the headline v1→v2 breaking changes).
  - `starlette`, `uvicorn`, `sse-starlette`, `python-multipart` — the HTTP *server* transport stack (needed even if you only ever run stdio, since it's one package supporting all transports, same situation as fastmcp).
  - `jsonschema` — validates structured tool output against declared output schemas.
  - `pyjwt[crypto]` — OAuth token handling.
  - `opentelemetry-api` — **new in v2**, "just the lightweight API, so the SDK's tracing middleware costs nothing unless you install an OpenTelemetry SDK and exporter yourself" (v2 ships OpenTelemetry tracing middleware on by default, a genuinely new dependency vs. v1.x).
  - `typing-extensions`, `typing-inspection`.
  - `pywin32` (Windows-only, for stdio subprocess management).
  - Optional extras: `mcp[cli]` adds `typer` + `python-dotenv` (for the `mcp` CLI tool, `mcp dev`/`mcp run`/`mcp install` — you'd want this in dev, may not need it in the deployed zikaron-mcp binary); `mcp[rich]` adds `rich` for nicer logs.
- **This is a comparably-sized-or-larger dependency list than fastmcp's**, not obviously smaller, once you account for the full Starlette/uvicorn HTTP stack, OpenTelemetry, and PyJWT being pulled in regardless of transport choice. My earlier framing in §1c ("leanest possible dependency footprint" for the official SDK) should be read as *relative simplicity of the abstraction layer and closer tracking of the wire protocol*, not necessarily *fewer total installed packages* — I did not find strong evidence either package is dramatically lighter than the other in raw transitive-dependency count; both pull in a full ASGI HTTP server stack unconditionally.

### Concrete pin recommendation

Given the version-pinning discipline the project has stated ("this project pins exact versions"), and given the churn documented above:
- **If choosing standalone `fastmcp`: pin `fastmcp==3.4.5`** — the last release in the stable 3.x line as of this research, immediately before the `4.0.0` alpha/beta pre-releases begin. Do **not** pin an unbounded `fastmcp` or a `>=3.4` range, since `4.0.0` changes are described (in the "What's new" framing on the live default docs) as introducing "stateful applications on sessionless MCP" — a significant semantic shift.
- **If choosing the official `mcp` SDK's `FastMCP`/`MCPServer` class: pin `mcp>=1.28,<2`** if you want to keep using the `FastMCP` class name and `mcp.server.fastmcp` import path (the v1.x line, described by its own docs as remaining in "maintenance" with security patches but no further feature work), OR **pin `mcp>=2.0.0,<3` and use the renamed `MCPServer` class from `mcp.server.mcpserver`** if you're comfortable adopting the newer, actively-developed line and its renamed API. Given that v2 is explicitly framed by its own PyPI page as "the current stable release line" (not a beta/alpha at this snapshot), and that v1.x is explicitly framed as feature-frozen maintenance-only, **I would lean toward recommending the v2/`MCPServer` line if choosing the official SDK at all**, despite the rename requiring `FastMCP`→`MCPServer` find-and-replace in any code samples you might otherwise copy from older tutorials.

---

## Methodology and search queries used

1. `fastmcp official documentation gofastmcp.com tool decorator` (web_search)
2. `FastMCP Python package jlowin vs mcp SDK FastMCP class 2025` (web_search)
3. Fetched https://codersera.com/blog/how-to-build-an-mcp-server-in-python-2026/ (selective, "versioning trap...") — third-party but detailed and dated guide, cross-checked against primary sources below
4. Fetched https://pypi.org/project/fastmcp/ (selective, "version requires python dependencies install") — primary source, PyPI project + release history + metadata
5. Fetched https://github.com/jlowin/fastmcp (redirects to PrefectHQ/fastmcp) — primary source, GitHub README
6. Fetched https://gofastmcp.com/servers/tools (full) — primary source, live default docs (confirmed to be v4.0.0-beta docs via banner text)
7. `gofastmcp.com v3 servers running server mcp.run transport stdio` (web_search) — used specifically to locate version-pinned `/v3/` doc paths after realizing the default site serves v4-beta
8. Fetched https://gofastmcp.com/clients/client (selective, "Client in-memory testing...") — primary source
9. Fetched https://raw.githubusercontent.com/PrefectHQ/fastmcp/main/pyproject.toml (full) — primary source, ground-truth dependency declaration
10. Fetched https://gofastmcp.com/v3/deployment/running-server (full) — primary source, version-pinned v3 docs, critical for §4 (run/run_async/asyncio.run behavior)
11. Fetched https://raw.githubusercontent.com/PrefectHQ/fastmcp/main/fastmcp_slim/pyproject.toml (selective, "dependencies requires-python name fastmcp-slim project") — primary source, real dependency list (partially truncated)
12. `gofastmcp.com/v3/servers/tools error handling ToolError mask_error_details` (web_search)
13. Fetched https://gofastmcp.com/v3/servers/tools (full) — primary source, version-pinned v3 docs, confirms tool decorator + error handling identical to v4-beta wording, with the `enabled=`/`on_duplicate_tools=` v3-specific spelling
14. `pypi.org project mcp python sdk current version modelcontextprotocol` (web_search) — for §1b/§8 comparison
15. `fastmcp conditionally register tools based on environment variable startup config` (web_search) — for §3, confirmed no first-party documented pattern exists matching the brief precisely
16. `FastMCP constructor lazy tool function only runs when called tools/call` (web_search) — for §7, surfaced the Resources lazy-loading quote and the troubleshooting-page import-time framing
17. Fetched https://py.sdk.modelcontextprotocol.io/v2/llms-full.txt (selective, "from mcp.server.fastmcp import FastMCP tool decorator run stdio") — primary source, the ENTIRE official SDK v2 documentation in one file (this fetch, though "selective," returned an enormous amount of content covering installation, migration guide, testing, error handling, transports, auth, and more — used across §1b, §5, §6, §8)
18. Fetched https://gofastmcp.com/v3/servers/testing (full) — primary source, version-pinned v3 testing docs, used for §6

## Evidence quality summary

- **Highest confidence, directly quoted from primary/vendor sources:** package identity and naming (§1a/§1b), decorator signature and schema-generation mechanics (§2), `run()`/`run_async()`/`asyncio.run` behavior (§4), exception→tool-error-response default behavior and `ToolError`/`mask_error_details` (§5), in-memory `Client` testing pattern (§6), Python version requirement (§8).
- **High confidence but synthesized from convergent indirect evidence rather than one blanket vendor statement:** lazy tool-body execution (§7) — I am confident in this conclusion but want the consumer of this note to know it is an inference from consistent evidence, not a single directly-quotable guarantee sentence.
- **Moderate confidence, involves either truncated primary-source fetches or reliance on a single third-party source for framing/attribution:** exact `[server]` extra dependency enumeration for `fastmcp-slim` (§1d/§8, truncated mid-fetch), the specific attributed quotes about "David Soria Parra" and "Paul Iusztin" preferring standalone fastmcp (§1c, single third-party blog, unverified at primary source), the precise current status of the official `mcp` SDK's v2 line relative to a slightly-stale third-party guide describing it as still-alpha (§1b, resolved in favor of my more-recent primary-source fetch, but flagging the conflict for transparency).
- **Explicitly a gap / open question, not resolved in this pass:** whether the standalone `fastmcp` package's `FastMCP` constructor supports a `lifespan=` parameter equivalent to the official SDK's (relevant to persistent-connection-across-invocations design for the Unix-socket client — see end of §4); the exact contents of the `/clients/client-only-package` doc page (relevant to further minimizing client-side dependency footprint — see §8); full enumeration of the `[server]` extra's tail dependencies for `fastmcp-slim` (§1d).

## Sources

1. **PyPI — fastmcp project page** (release history, metadata, dependencies, maintainer info). https://pypi.org/project/fastmcp/ — fetched 2026-08-03, showing v3.4.5 as latest stable, v4.0.0 alpha/beta pre-releases present.
2. **PyPI — mcp project page, v2.0.0** (framing v2 as "the current stable release line"). https://pypi.org/project/mcp/2.0.0/ — fetched 2026-08-03.
3. **gofastmcp.com — Tools (default/v4-beta routing)**. https://gofastmcp.com/servers/tools — fetched 2026-08-03. Confirmed the site's default routing serves v4.0.0-beta docs.
4. **gofastmcp.com — Tools (v3, version-pinned)**. https://gofastmcp.com/v3/servers/tools — fetched 2026-08-03. Primary source for decorator API, error handling, and the `enabled=`/`on_duplicate_tools=` v3-specific spelling.
5. **gofastmcp.com — Running Your Server (v3, version-pinned)**. https://gofastmcp.com/v3/deployment/running-server — fetched 2026-08-03. Primary source for `run()`/`run_async()`/asyncio.run behavior.
6. **gofastmcp.com — Testing (v3, version-pinned)**. https://gofastmcp.com/v3/servers/testing — fetched 2026-08-03. Primary source for pytest + in-memory `Client` testing pattern.
7. **gofastmcp.com — The FastMCP Client (default/v4-beta routing)**. https://gofastmcp.com/clients/client — fetched 2026-08-03.
8. **gofastmcp.com — Resources & Templates** (search-surfaced snippet re: lazy loading). https://gofastmcp.com/servers/resources — snippet fetched via search 2026-08-03.
9. **GitHub — PrefectHQ/fastmcp, pyproject.toml** (ground-truth meta-package dependency declaration). https://raw.githubusercontent.com/PrefectHQ/fastmcp/main/pyproject.toml — fetched 2026-08-03.
10. **GitHub — PrefectHQ/fastmcp, fastmcp_slim/pyproject.toml** (ground-truth real-package dependency declaration; fetch partially truncated). https://raw.githubusercontent.com/PrefectHQ/fastmcp/main/fastmcp_slim/pyproject.toml — fetched 2026-08-03.
11. **GitHub — PrefectHQ/fastmcp README** (via github.com/jlowin/fastmcp redirect). https://github.com/jlowin/fastmcp — fetched 2026-08-03.
12. **jlowin.dev — "Introducing FastMCP 2.0"** (Jeremiah Lowin's own blog, confirms FastMCP 1.0 → official SDK merge history). https://jlowin.dev/blog/fastmcp-2/ — snippet fetched via search 2026-08-03.
13. **codersera.com — "How to Build an MCP Server in Python (2026 Guide)"** (third-party, dated Jun 30 2026, detailed comparison of the two packages; some version specifics found to be ~1 month stale relative to primary sources). https://codersera.com/blog/how-to-build-an-mcp-server-in-python-2026/ — fetched 2026-08-03.
14. **py.sdk.modelcontextprotocol.io — official MCP Python SDK v2 docs, llms-full.txt** (the entire v2 documentation set in one file: installation, migration guide from v1, error-handling semantics, in-memory `Client` testing, transports, deployment). https://py.sdk.modelcontextprotocol.io/v2/llms-full.txt — fetched 2026-08-03.
15. **py.sdk.modelcontextprotocol.io — installation page** (search-surfaced, confirms Python 3.10+ requirement for the official SDK). https://py.sdk.modelcontextprotocol.io/v2/get-started/installation — snippet fetched via search 2026-08-03.
16. **GitHub Gist — "FastMCP v3 Visibility + schema-in-response workaround for Windsurf"** (third-party community pattern, corroborates tag-based `enable`/`disable` as the recognized mechanism for conditional-tool-surface problems). http://gist.github.com/ichoosetoaccept/178d5a0c9aa2db54f11d2e84259b800a — snippet surfaced via search 2026-08-03, not directly fetched in full.
17. **GitHub — ragieai/dynamic-fastmcp** (third-party project extending the official SDK with per-request dynamic tool adaptation; a related but distinct problem from zikaron-mcp's per-process mode selection). https://github.com/ragieai/dynamic-fastmcp/ — snippet surfaced via search 2026-08-03, not directly fetched.
