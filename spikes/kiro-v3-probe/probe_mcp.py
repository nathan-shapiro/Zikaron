#!/usr/bin/env python3
"""Throwaway MCP stdio server for the kiro V3 probe: logs its lifecycle, offers whoami and sleep."""

import json
import os
import sys
import time
import ancestry
from typing import Any

LOG = os.environ.get("PROBE_LOG", "/tmp/kiro_v3_probe.jsonl")
TOOLS = [
    {
        "name": "probe_whoami",
        "description": "Return this MCP server's process id and session environment.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "probe_sleep",
        "description": "Sleep for the given number of seconds, then report how long it slept.",
        "inputSchema": {
            "type": "object",
            "properties": {"seconds": {"type": "number"}},
            "required": ["seconds"],
        },
    },
]


def record(event: str, **extra: Any) -> None:
    entry = {
        "at": time.strftime("%H:%M:%S"),
        "label": "mcp",
        "ancestry": ancestry.chain(),
        "event": event,
        "pid": os.getpid(),
        "ppid": os.getppid(),
        "cwd": os.getcwd(),
        "kiro_env": {k: v for k, v in sorted(os.environ.items()) if k.startswith(("KIRO", "PROBE"))},
        **extra,
    }
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")


def reply(request_id: Any, result: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}) + "\n")
    sys.stdout.flush()


def call(name: str, arguments: dict[str, Any]) -> str:
    if name == "probe_whoami":
        env = {k: v for k, v in os.environ.items() if k.startswith(("KIRO", "PROBE"))}
        return json.dumps({"pid": os.getpid(), "env": env})
    seconds = float(arguments.get("seconds", 1))
    start = time.monotonic()
    time.sleep(seconds)
    return f"slept {time.monotonic() - start:.1f}s"


def main() -> None:
    record("startup")
    for line in sys.stdin:
        if not line.strip():
            continue
        message = json.loads(line)
        method = message.get("method", "")
        record("request", method=method, params=message.get("params"))
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
            text = call(params.get("name", ""), params.get("arguments") or {})
            record("call_done", tool=params.get("name"), text=text)
            reply(message["id"], {"content": [{"type": "text", "text": text}]})
        else:
            reply(message["id"], {})
    record("stdin_closed")


if __name__ == "__main__":
    main()
