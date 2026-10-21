#!/usr/bin/env bash
# 실행 중인 서버와 모델을 재사용하고, 필요한 설명 모델만 준비한다.
set -euo pipefail
cd "$(dirname "$0")/.."
command -v ollama >/dev/null 2>&1 || { echo "Ollama 설치가 필요합니다: https://ollama.com"; exit 1; }
MODEL="${OLLAMA_QUALITY_MODEL:-qwen3.5:2b}"
STARTED_PID=""
SETUP_LOG=""
cleanup() {
  if [ -n "$STARTED_PID" ]; then
    kill "$STARTED_PID" 2>/dev/null || true
    wait "$STARTED_PID" 2>/dev/null || true
  fi
  if [ -n "$SETUP_LOG" ]; then rm -f "$SETUP_LOG"; fi
}
trap cleanup EXIT
if ! curl -fsS --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  SETUP_LOG="$(mktemp -t iot-care-ollama)"
  ollama serve >"$SETUP_LOG" 2>&1 &
  STARTED_PID=$!
  for _ in $(seq 1 30); do
    curl -fsS --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1 && break
    sleep 0.5
  done
fi
curl -fsS --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1 || { echo "Ollama 서버에 연결할 수 없습니다."; exit 1; }
if ollama show "$MODEL" >/dev/null 2>&1; then
  echo "설치된 모델 재사용: $MODEL"
else
  ollama pull "$MODEL"
fi
echo "준비 완료. ollama serve를 실행한 상태에서 bash sh/run_iot_agent.sh ollama를 실행하세요."
