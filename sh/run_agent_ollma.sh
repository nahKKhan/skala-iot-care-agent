#!/usr/bin/env bash
# 기존 실행 명령을 현재 IoT 진입점으로 연결한다.
set -euo pipefail
exec bash "$(dirname "$0")/run_iot_agent.sh" ollama
