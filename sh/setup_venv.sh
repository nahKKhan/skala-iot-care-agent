#!/usr/bin/env bash
# 프로젝트 전용 가상환경과 필수 패키지 설치.
set -euo pipefail
cd "$(dirname "$0")/.."

command -v python3 >/dev/null 2>&1 \
    || { echo "ERROR: python3가 설치되어 있지 않습니다."; exit 1; }

# ── 1) .venv 생성 (이미 있으면 건너뜀) ──────────────────────────────────
if [ -x ".venv/bin/python3" ]; then
    echo ".venv가 이미 있습니다 — 생성은 건너뛰고 설치만 다시 확인합니다."
else
    echo "python3 -m venv .venv 로 가상환경을 새로 만듭니다..."
    python3 -m venv .venv
fi

# ── 2) 의존성 설치 — activate 대신 .venv의 python3를 직접 호출 ─────────
#    (plain pip/python3가 alias로 다른 경로를 가리키는 머신에서도 항상
#     .venv 안에 정확히 설치되도록 보장한다)
echo "requirements.txt 설치 중..."
./.venv/bin/python3 -m pip install --upgrade pip --quiet
./.venv/bin/python3 -m pip install -r requirements.txt

echo
echo "설치 확인:"
./.venv/bin/python3 -c "import fastapi, uvicorn, langgraph, langsmith, fastmcp, mcp, httpx, dotenv; print('  필요 패키지 전부 import 성공')"

cat <<EOF

################################################################
 .venv 준비 완료
################################################################

이제 아래 중 하나로 에이전트를 띄울 수 있습니다:
  bash sh/run_iot_agent.sh ollama     (로컬 Ollama)
  bash sh/run_iot_agent.sh openai    (OpenAI API, 과금)

Ollama를 처음 쓰거나 모델을 다시 받아야 하면 먼저:
  bash sh/setup_ollama.sh
EOF
