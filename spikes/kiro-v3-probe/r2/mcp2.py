#!/usr/bin/env python3
"""Throwaway MCP stdio server for kiro V3 probe round 2: whoami, and a result of a requested size."""

import json
import os
import sys
import time
from typing import Any

LOG = os.environ["PROBE_LOG"]
AGENT = os.environ.get("PROBE_AGENT", "?")
TOOLS = [
    {
        "name": "probe_whoami",
        "description": "Return this MCP server's process id and the agent it was configured for.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "probe_obj",
        "description": "Return an object whose JSON text has the requested number of characters, "
        "as a text block and again as structured content.",
        "inputSchema": {
            "type": "object",
            "properties": {"chars": {"type": "integer"}},
            "required": ["chars"],
        },
    },
    {
        "name": "probe_big",
        "description": "Return a text result of exactly the requested number of characters.",
        "inputSchema": {
            "type": "object",
            "properties": {"chars": {"type": "integer"}},
            "required": ["chars"],
        },
    },
]


def record(event: str, **extra: Any) -> None:
    entry = {
        "at": time.strftime("%H:%M:%S"),
        "label": f"mcp-{AGENT}",
        "event": event,
        "pid": os.getpid(),
        "ppid": os.getppid(),
        **extra,
    }
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")


def big(chars: int) -> str:
    head, tail = "ZKSTART\n", "ZKEND"
    lines, size, n = [head], len(head), 0
    while size + 25 + len(tail) <= chars:
        line = f"line{n:07d} pqrstuvwxyz\n"
        lines.append(line)
        size += len(line)
        n += 1
    lines.append("." * (chars - size - len(tail)))
    lines.append(tail)
    return "".join(lines)


def structured(chars: int) -> dict[str, str]:
    """An object whose compact JSON is exactly `chars` long, opening and closing with sentinels."""
    frame = len(json.dumps({"head": "OBJSTART", "body": "", "tail": "OBJEND"}, separators=(",", ":")))
    return {"head": "OBJSTART", "body": "q" * (chars - frame), "tail": "OBJEND"}


def call(name: str, arguments: dict[str, Any]) -> str:
    if name == "probe_whoami":
        return json.dumps({"pid": os.getpid(), "agent": AGENT})
    return big(int(arguments.get("chars", 1000)))


def reply(request_id: Any, result: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}) + "\n")
    sys.stdout.flush()


def main() -> None:
    record("startup")
    for line in sys.stdin:
        if not line.strip():
            continue
        message = json.loads(line)
        method = message.get("method", "")
        record("request", method=method)
        if "id" not in message:
            continue
        if method == "initialize":
            version = message.get("params", {}).get("protocolVersion", "2024-11-05")
            reply(
                message["id"],
                {
                    "protocolVersion": version,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "probe", "version": "0"},
                },
            )
        elif method == "tools/list":
            reply(message["id"], {"tools": TOOLS})
        elif method == "tools/call":
            params = message.get("params", {})
            if params.get("name") == "probe_obj":
                obj = structured((params.get("arguments") or {}).get("chars", 1000))
                text = json.dumps(obj, separators=(",", ":"))
                record("call_done", tool="probe_obj", chars=len(text))
                reply(
                    message["id"],
                    {"content": [{"type": "text", "text": text}], "structuredContent": obj},
                )
                continue
            text = call(params.get("name", ""), params.get("arguments") or {})
            record("call_done", tool=params.get("name"), chars=len(text))
            reply(message["id"], {"content": [{"type": "text", "text": text}]})
        else:
            reply(message["id"], {})
    record("stdin_closed")


if __name__ == "__main__":
    main()
