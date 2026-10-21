"""IoT MCP stdio 연결을 재사용한다. 복구 명령은 자동 재시도하지 않는다."""
import asyncio
import json
import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path

from langsmith import traceable
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER_DIR = Path(__file__).parent.parent
DEFAULT_SERVER_SCRIPTS = {"ops": SERVER_DIR / "mcp_server.py"}


class MCPClient:
    def __init__(self, server_scripts: dict[str, Path] | None = None,
                 extra_env: dict[str, str] | None = None):
        self._extra_env = extra_env or {}
        self._server_scripts = server_scripts or DEFAULT_SERVER_SCRIPTS
        self._stack = None
        self.sessions = {}
        self._lock = asyncio.Lock()

    async def start(self):
        self._stack = AsyncExitStack()
        for name, script in self._server_scripts.items():
            params = StdioServerParameters(command=sys.executable, args=[str(script)],
                env={**os.environ, **self._extra_env, "FASTMCP_LOG_LEVEL": "ERROR"})
            read, write = await self._stack.enter_async_context(stdio_client(params))
            session = await self._stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            self.sessions[name] = session

    async def stop(self):
        if self._stack is not None:
            await self._stack.aclose()
            self._stack = None
            self.sessions = {}

    @traceable(run_type="tool", name="mcp.call_tool")
    async def call_tool(self, name: str, arguments: dict, server: str = "ops") -> dict:
        async with self._lock:
            result = await self.sessions[server].call_tool(name, arguments)
        return json.loads(result.content[0].text)
