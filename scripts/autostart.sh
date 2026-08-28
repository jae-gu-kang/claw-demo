#!/usr/bin/env bash
# devcontainer·Codespaces 시작 훅 — 서버를 백그라운드로 띄운다.
# .devcontainer/devcontainer.json의 postStartCommand가 호출한다.
#
# 왜 필요한가: postCreateCommand(설치)는 생성 시 1회지만 이 훅은 컨테이너가
# **켜질 때마다** 돈다. Codespace는 30분 무활동이면 자동 정지하고 그때 터미널에서
# run.sh로 띄운 프로세스도 함께 죽는다. 며칠 뒤 저장해 둔 포워딩 주소로 다시 온
# 사람은 컨테이너가 살아나도 8000번에 아무것도 없는 것을 보고 "어제 되던 게 안
# 된다"고 읽는다. 저장소를 남에게 공유하는 용도라 이 오해가 특히 비싸다.
#
# **블로킹하면 안 된다.** postStartCommand가 반환해야 컨테이너 시작이 끝나므로,
# 포그라운드로 띄우면 Codespace가 "시작 중"에서 넘어가지 않는다.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${PORT:-8000}"
LOG="${CLAW_LOG:-/tmp/claw-server.log}"

# 이미 떠 있으면 두 번 띄우지 않는다 — 손으로 run.sh를 돌려 둔 채 컨테이너가
# 재시작되는 경우가 있고, 그때 두 번째 uvicorn은 포트를 못 잡고 즉시 죽어
# 로그만 어지럽힌다.
if curl -sf -o /dev/null --max-time 2 "http://127.0.0.1:$PORT/api/health" 2>/dev/null; then
  echo "[autostart] 이미 기동돼 있습니다 — 포트 $PORT"
  exit 0
fi

# HOST=0.0.0.0 인 이유: 컨테이너 안 127.0.0.1 바인딩을 포워딩이 못 잡는 경우가
# 실제로 있었다. 컨테이너가 인터넷에 직접 노출되는 것이 아니고 포워딩 포트는
# 기본 private이라, 이걸로 노출 범위가 넓어지지는 않는다.
#
# nohup + & — 이 스크립트가 끝나도 서버는 남아야 한다.
cd "$ROOT"
HOST=0.0.0.0 PORT="$PORT" nohup bash scripts/run.sh > "$LOG" 2>&1 &

echo "[autostart] 서버를 백그라운드로 기동했습니다 (로그: $LOG)"
echo "[autostart] PORTS 패널의 $PORT 번을 열면 웹 UI입니다."
