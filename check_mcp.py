import asyncio
import json

from agent.mcp_client import MCPClient


async def main():
    client = MCPClient()
    await client.start()

    try:
        for device_id in ["sensor-02", "sensor-99"]:
            result = await client.call_tool(
                "get_device_status",
                {"device_id": device_id}
            )

            print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        await client.stop()


if __name__ == "__main__":
    asyncio.run(main())