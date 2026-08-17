from fastmcp import FastMCP
mcp = FastMCP("zikaron")
@mcp.tool()
def zikaron_search(query: str) -> str:
    """Search project memory. Call when asked to probe."""
    return "PROBE-OK"
mcp.run()
