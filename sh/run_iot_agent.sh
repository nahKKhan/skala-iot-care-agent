#!/usr/bin/env bash
# 기존 서버나 세션을 삭제하지 않고 IoT 에이전트를 실행한다.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -x .venv/bin/python ]; then
  echo ".venv가 없습니다. 먼저 가상환경을 준비해 주세요."
  exit 1
fi
export LLM_BACKEND="${1:-ollama}"
case "$LLM_BACKEND" in
  openai|ollama|fake) ;;
  *) echo "사용법: bash sh/run_iot_agent.sh [openai|ollama|fake]"; exit 1 ;;
esac
export LANGCHAIN_TRACING_V2="${LANGCHAIN_TRACING_V2:-false}"
export LANGSMITH_TRACING="${LANGSMITH_TRACING:-false}"
echo "IoT 에이전트: $LLM_BACKEND · http://localhost:8100"
exec .venv/bin/python server.py
