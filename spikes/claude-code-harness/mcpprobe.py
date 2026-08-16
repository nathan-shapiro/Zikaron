import os, sys, json
from fastmcp import FastMCP

with open("/tmp/zk-ccprobe/mcp.log", "a") as f:
    f.write("=== mcp server start pid=%d ppid=%d cwd=%s\n" % (os.getpid(), os.getppid(), os.getcwd()))
    for k in sorted(os.environ):
        if k.startswith(("CLAUDE", "AI_AGENT")):
            f.write("  %s=%s\n" % (k, os.environ[k]))

mcp = FastMCP("zkprobe")

@mcp.tool()
def probe_env() -> str:
    """Return the probe server's session identity. Call this when asked to probe."""
    with open("/tmp/zk-ccprobe/mcp.log", "a") as f:
        f.write("--- tool call pid=%d sid=%r\n" % (os.getpid(), os.environ.get("CLAUDE_CODE_SESSION_ID")))
    return "sid=%s pid=%d" % (os.environ.get("CLAUDE_CODE_SESSION_ID"), os.getpid())

mcp.run()
