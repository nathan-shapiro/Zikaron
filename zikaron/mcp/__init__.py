"""The MCP server: translate a tool call into an RPC, return the answer.

Deliberately not stdlib-only, unlike `zikaron.hook` — see `design/coding-standards.md` §6 for the
cost-model reasoning (one `fastmcp` import per agent spawn, not per user message) and
`design/architecture.md` §Components for the measured import cost.
"""
