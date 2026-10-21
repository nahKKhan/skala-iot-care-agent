import asyncio
import json
from agent.device_rules import assess_device

from agent.mcp_client import MCPClient


async def main():
    client = MCPClient()
    await client.start()

    try:
        for device_id in ["sensor-01", "sensor-02", "sensor-03", "sensor-99"]:
            result = await client.call_tool(
                "get_device_status",
                {"device_id": device_id}
            )

            if result["ok"]:
                result["assessment"] = assess_device(result["data"])

                result["manuals"] = await client.call_tool("search_iot_manuals", {
                    "query": " ".join(result["assessment"]["issues"]) or "healthy",
                    "issues": result["assessment"]["issues"],
                })

            print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        await client.stop()


if __name__ == "__main__":
    asyncio.run(main())