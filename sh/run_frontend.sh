#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -x .venv/bin/python ]; then
  echo "먼저 bash sh/setup_venv.sh를 실행해 주세요."
  exit 1
fi
echo "IoT Care 화면: http://localhost:8600 (백엔드: 8100)"
exec .venv/bin/python web_demo_server.py
