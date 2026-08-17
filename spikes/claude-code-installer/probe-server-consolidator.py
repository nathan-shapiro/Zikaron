from fastmcp import FastMCP
mcp = FastMCP("zikaron-consolidator")
@mcp.tool()
def zikaron_next_group() -> str:
    """Get the next consolidation group."""
    return "GROUP-OK"
mcp.run()
