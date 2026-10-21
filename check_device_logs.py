"""웹 서버 없이 실제 MCP stdio 도구로 가상 장치 로그를 조회한다."""
import argparse
import asyncio
import json
from agent.mcp_client import MCPClient, SERVER_DIR


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("device_id", nargs="?", default="sensor-03")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--level", choices=["INFO", "WARN", "ERROR"])
    args = parser.parse_args()
    client = MCPClient( server_scripts={"ops": SERVER_DIR / "mcp_server.py"})
    await client.start()
    try:
        result = await client.call_tool("get_device_logs", {"device_id": args.device_id, "limit": args.limit, "level": args.level})
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        await client.stop()


if __name__ == "__main__":
    asyncio.run(main())
