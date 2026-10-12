"""End-to-end check: MCP server 2.1.9 -> protocol-13 addon -> live Blender GUI.

Calls the updated server over stdio against the Blender that is actually
running, so the whole chain is exercised: tool call -> command queue ->
main-thread bpy execution -> response.
"""
import asyncio
import base64
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

BIN = "/Users/zhenkunzhu/Desktop/project/dpharness/mcp-for-blender/.venv/bin/mcp-for-blender"
SHOT = "/Users/zhenkunzhu/Desktop/project/artstudio/tmp/mcp-blender-update/e2e_viewport.png"


async def main() -> int:
    env = {**os.environ, "BLENDER_HOST": "localhost", "BLENDER_PORT": "9876", "DISABLE_TELEMETRY": "true"}
    async with stdio_client(StdioServerParameters(command=BIN, env=env)) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print("server:", init.serverInfo.name, init.serverInfo.version)

            tools = (await session.list_tools()).tools
            print("tools :", len(tools), [t.name for t in tools])
            schema = next(t for t in tools if t.name == "get_addon_status").inputSchema
            print("required(get_addon_status):", schema.get("required"))

            status = await session.call_tool("get_addon_status", {"user_prompt": "e2e check"})
            print("\n--- get_addon_status ---")
            for block in status.content:
                print(getattr(block, "text", block)[:1200])
            print("isError:", status.isError)

            info = await session.call_tool("get_scene_info", {"user_prompt": "e2e check"})
            print("\n--- get_scene_info ---")
            for block in info.content:
                print(getattr(block, "text", block)[:1200])
            print("isError:", info.isError)

            shot = await session.call_tool(
                "look", {"user_prompt": "e2e check", "max_size": 900}
            )
            print("\n--- look ---")
            print("isError:", shot.isError, "blocks:", [type(b).__name__ for b in shot.content])
            for block in shot.content:
                data = getattr(block, "data", None)
                if data:
                    if isinstance(data, str):
                        data = base64.b64decode(data)
                    with open(SHOT, "wb") as fh:
                        fh.write(data)
                    print(f"saved viewport screenshot -> {SHOT} ({len(data)} bytes)")
                else:
                    print(getattr(block, "text", block)[:600])
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))