"""List the tools the Blender MCP server publishes, using its own venv SDK.

Independent check of the very binary the preset row launches: it proves the
command path, the stdio handshake, and the tool-name namespace the model sees.
Blender itself need not be running (the tools connect to localhost:9876 lazily).
"""
import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

BIN = "/Users/zhenkunzhu/Desktop/project/dpharness/mcp-for-blender/.venv/bin/mcp-for-blender"


async def main() -> int:
    params = StdioServerParameters(
        command=BIN,
        env={
            **os.environ,
            "BLENDER_HOST": "localhost",
            "BLENDER_PORT": "9876",
            "DISABLE_TELEMETRY": "true",
        },
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            tools = (await session.list_tools()).tools
            print("server :", init.serverInfo.name, init.serverInfo.version)
            print("tools  :", len(tools))
            for t in tools:
                print(f"  mcp__blender__{t.name}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))