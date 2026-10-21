import asyncio
import json

from agent.device_rules import assess_device
from agent.mcp_client import MCPClient


async def main():
    client = MCPClient()
    await client.start()

    try:
        # 1. 복구 전 상태
        before = await client.call_tool(
            "get_device_status",
            {"device_id": "sensor-02"}
        )

        # 2. 가상 복구 명령
        command = await client.call_tool(
            "restart_collection",
            {"device_id": "sensor-02"}
        )

        # 3. 복구 후 상태를 별도로 조회
        after = await client.call_tool(
            "get_device_status",
            {"device_id": "sensor-02"}
        )

        assessment = assess_device(after["data"])

        # 명령이 처리되고 새 데이터가 들어왔으며 상태도 정상인지 확인
        verified = (
            command["ok"]
            and after["data"]["telemetry_sequence"]
            > before["data"]["telemetry_sequence"]
            and assessment["status"] == "healthy"
        )

        print(json.dumps({
            "before": before["data"],
            "command": command,
            "after": after["data"],
            "assessment": assessment,
            "recovery_verified": verified
        }, ensure_ascii=False, indent=2))

    finally:
        await client.stop()


if __name__ == "__main__":
    asyncio.run(main())