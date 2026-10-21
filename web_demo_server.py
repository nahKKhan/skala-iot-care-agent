"""Vue 화면(:8600)과 IoT API(:8100)를 같은 출처에서 제공하는 프록시.

실행: .venv/bin/python web_demo_server.py
백엔드는 bash sh/run_iot_agent.sh [ollama|openai|fake]로 별도 실행한다.
"""
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

BACKEND = "http://127.0.0.1:8100"
HERE = Path(__file__).parent

app = FastAPI()


@app.get("/")
async def index():
    return FileResponse(HERE / "web_chat.html")


@app.get("/health")
async def proxy_health():
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f"{BACKEND}/health")
    return JSONResponse(r.json(), status_code=r.status_code)


@app.post("/chat")
async def proxy_chat(req: Request):
    body = await req.body()
    async with httpx.AsyncClient(timeout=210.0) as client:
        r = await client.post(f"{BACKEND}/chat", content=body,
                              headers={"content-type": "application/json"})
    return JSONResponse(r.json(), status_code=r.status_code)


@app.post("/api/recover")
async def proxy_recover(req: Request):
    """8600 화면의 복구 요청을 기존 8100 백엔드로 전달한다. 재시도하지 않는다."""
    body = await req.body()
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{BACKEND}/api/recover", content=body,
                headers={"content-type": "application/json"},
            )
    except httpx.TimeoutException:
        return JSONResponse(
            {"detail": "복구 응답 시간이 초과됐습니다. 실행 결과를 다시 점검해 주세요."},
            status_code=504,
        )
    except httpx.RequestError:
        return JSONResponse(
            {"detail": "복구 서버와 통신하지 못했습니다. 장치 상태를 다시 점검해 주세요."},
            status_code=503,
        )
    try:
        payload = response.json()
    except ValueError:
        return JSONResponse(
            {"detail": "복구 응답을 해석하지 못했습니다. 실행 결과를 다시 점검해 주세요."},
            status_code=502,
        )
    return JSONResponse(payload, status_code=response.status_code)


@app.get("/api/devices")
async def proxy_devices():
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(f"{BACKEND}/api/devices")
    return JSONResponse(response.json(), status_code=response.status_code)


@app.get("/api/maintenance")
async def proxy_maintenance(device_id: str | None = None):
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(f"{BACKEND}/api/maintenance", params={"device_id": device_id} if device_id else {})
    return JSONResponse(response.json(), status_code=response.status_code)


@app.post("/api/scenario/reset")
async def proxy_reset(req: Request):
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(f"{BACKEND}/api/scenario/reset", content=await req.body(), headers={"content-type": "application/json"})
    return JSONResponse(response.json(), status_code=response.status_code)


@app.post("/api/scenario/reset-all")
async def proxy_reset_all():
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(f"{BACKEND}/api/scenario/reset-all")
    except httpx.TimeoutException:
        return JSONResponse({"detail": "전체 초기화 응답 시간이 초과됐습니다. 재점검해 주세요."}, status_code=504)
    except httpx.RequestError:
        return JSONResponse({"detail": "전체 초기화 서버와 통신하지 못했습니다. 재점검해 주세요."}, status_code=503)
    try:
        payload = response.json()
    except ValueError:
        return JSONResponse({"detail": "전체 초기화 결과를 해석하지 못했습니다."}, status_code=502)
    return JSONResponse(payload, status_code=response.status_code)


@app.get("/chat/stream")
async def proxy_stream(message: str, thread_id: str = "web-demo"):
    async def relay():
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "GET", f"{BACKEND}/chat/stream",
                params={"message": message, "thread_id": thread_id},
            ) as upstream:
                async for chunk in upstream.aiter_bytes():
                    yield chunk

    return StreamingResponse(relay(), media_type="text/event-stream")


if __name__ == "__main__":
    print("브라우저에서 http://localhost:8600 을 열어보세요 (server.py가 8100에 떠 있어야 합니다)")
    uvicorn.run(app, host="0.0.0.0", port=8600)
