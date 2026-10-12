"""Dump the updated server's tool surface: name, first description line, params."""
import asyncio, os, sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

BIN = "/Users/zhenkunzhu/Desktop/project/dpharness/mcp-for-blender/.venv/bin/mcp-for-blender"

async def main():
    env = {**os.environ, "BLENDER_HOST": "localhost", "BLENDER_PORT": "9876", "DISABLE_TELEMETRY": "true"}
    async with stdio_client(StdioServerParameters(command=BIN, env=env)) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            for t in (await s.list_tools()).tools:
                props = list((t.inputSchema or {}).get("properties", {}))
                first = (t.description or "").strip().splitlines()[0] if t.description else ""
                print(f"\n{t.name}\n  params: {props}\n  desc  : {first[:150]}")
asyncio.run(main())
