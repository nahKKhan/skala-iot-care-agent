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

                if "telemetry_delayed" in result["assessment"]["issues"]:
                    result["runbook"] = await client.read_resource(
                        "runbook://incident-response/telemetry_delayed",
                        server="ops"
                    )

            print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        await client.stop()


if __name__ == "__main__":
    asyncio.run(main())