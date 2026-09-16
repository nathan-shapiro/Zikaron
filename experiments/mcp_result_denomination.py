#!/usr/bin/env python
"""In what unit an MCP tool result's size should be counted, given that it is delivered twice.

The delivery threshold every payload bound in this repository sits under was measured with a probe
whose tools returned plain strings, and it was recorded in the size of the payload the tool
returned — counted **once**. Meanwhile the transport sends that payload twice: as a text block and
again as structured content. A bound that charges for both copies is therefore in a different unit
from the threshold it is compared against, and would halve the deliverable answer for nothing.

That argument rests on two claims about the transport, and this probe measures both rather than
citing them:

1. A tool that does not declare a structured return shape has its answer wrapped under a single
   `result` key — the shape the spilled result file was observed to hold. Checked for `-> str`,
   which the threshold probe used, and for `-> object`, which the shipped tools use.
2. Both copies arrive, and the structured copy carries the whole payload rather than a summary.

Run:  .venv/bin/python experiments/mcp_result_denomination.py
"""

from __future__ import annotations

import asyncio
import json

from fastmcp import Client, FastMCP

#: Decimal, not binary — the unit the threshold measurements are quoted in. Named for what it holds
#: rather than approximately: this corpus has twice been bitten by a size word that meant two things.
KILOBYTE = 1000


def _server() -> FastMCP:
    mcp: FastMCP = FastMCP("denomination")

    @mcp.tool()
    def emit_str(kilobytes: int) -> str:
        """The threshold probe's shape: a plain string return."""
        return "x" * (kilobytes * KILOBYTE)

    @mcp.tool()
    def emit_object(kilobytes: int) -> object:
        """The shipped tools' shape: an unconstrained return annotation."""
        return {"payload": "x" * (kilobytes * KILOBYTE)}

    return mcp


async def main() -> None:
    async with Client(_server()) as client:
        for tool, arguments in (("emit_str", {"kilobytes": 4}), ("emit_object", {"kilobytes": 4})):
            delivered = await client.call_tool(tool, arguments)
            as_text = sum(
                len(block.text.encode("utf-8"))
                for block in delivered.content
                if hasattr(block, "text")
            )
            structured = delivered.structured_content
            # `json.dumps(None)` is `"null"`, four perfectly real bytes, so a check on the encoded
            # length alone would report a second copy for a delivery that carried none.
            encoded = json.dumps(structured, ensure_ascii=False).encode("utf-8")
            print(
                json.dumps(
                    {
                        "tool": tool,
                        "text_block_bytes": as_text,
                        "structured_bytes": len(encoded),
                        "structured_top_level_keys": sorted(structured or {}),
                        "delivered_twice": as_text > 0 and structured is not None,
                    }
                )
            )


if __name__ == "__main__":
    asyncio.run(main())
