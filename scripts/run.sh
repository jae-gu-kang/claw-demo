#!/usr/bin/env bash
# CLAW_DEMO 기동 — 필요하면 설치까지 알아서 한다.
#
#   scripts/run.sh                    # 127.0.0.1:8000
#   PORT=9000 scripts/run.sh          # 포트 변경
#   HOST=0.0.0.0 scripts/run.sh       # 원격 VM·Docker에서 외부 접속 허용
#   scripts/run.sh --reload           # 나머지 인자는 uvicorn으로 그대로 전달
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# 반드시 리포 루트에서 기동한다. 결과 저장 경로가 CWD 상대경로($CLAW_SERVER_DATA,
# 기본 "server_data")라 기동 위치가 달라지면 별도 server_data/ 가 생기고 이전
# 산출물이 결과 탭에 안 보인다.
cd "$ROOT"

VPY="$ROOT/.venv/bin/python"

# 이미 갖춰졌으면 설치를 건너뛴다 (매 기동마다 pip를 돌리지 않기 위함).
# websockets까지 확인하는 이유: plain uvicorn만 깔린 구 환경을 자동으로 치유한다.
if ! "$VPY" -c 'import claw_server, websockets' >/dev/null 2>&1; then
  # 폐쇄망 설치였다면 setup.sh가 wheelhouse 경로를 남겨 둔다. 그걸 무시하고
  # 그냥 setup.sh를 부르면 PyPI로 나가려 하고, systemd Restart=on-failure 아래서는
  # 그게 무한 재시도 루프가 된다 — 표식이 있으면 반드시 오프라인으로 복구한다.
  MARK="$ROOT/.venv/.claw-offline-wheelhouse"
  if [ -f "$MARK" ]; then
    WH="$(cat "$MARK")"
    if [ ! -d "$WH" ]; then
      echo "오류: 환경이 깨졌는데 wheelhouse를 찾을 수 없습니다 — $WH" >&2
      echo "  이 장비는 폐쇄망 설치본입니다. 네트워크 설치를 시도하지 않습니다." >&2
      echo "  반입한 wheelhouse를 위 경로에 두거나, 직접:" >&2
      echo "    scripts/setup.sh --offline <wheelhouse 경로>" >&2
      exit 1
    fi
    echo "환경이 준비되지 않았습니다 — 오프라인으로 재설치합니다 ($WH)."
    bash "$ROOT/scripts/setup.sh" --offline "$WH"
  else
    echo "환경이 준비되지 않았습니다 — scripts/setup.sh 를 먼저 실행합니다."
    bash "$ROOT/scripts/setup.sh"   # 실행 권한(+x) 유실에 견디도록 bash로 호출
  fi
fi

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"

# --reload 시 감시 범위를 소스로 좁힌다. 기본값(리포 루트 전체)이면 watchfiles가
# .venv 수천 디렉터리와 server_data/ 산출물까지 재귀 감시해 리눅스 컨테이너에서
# inotify 한도에 걸릴 수 있다.
EXTRA=()
for a in "$@"; do
  if [ "$a" = "--reload" ]; then
    EXTRA=(--reload-dir engine --reload-dir server --reload-dir web)
    break
  fi
done

# uvicorn은 뒤 인자가 이기므로, 사용자가 --host/--port를 직접 넘겼다면
# HOST/PORT로 만든 URL은 틀린 주소가 된다. 그럴 땐 안내를 생략한다.
OVERRIDDEN=""
for a in "$@"; do
  case "$a" in
    --host|--host=*|--port|--port=*) OVERRIDDEN=1 ;;
  esac
done
# 0.0.0.0/:: 는 바인딩 주소지 접속 주소가 아니다 — 그대로 안내하면 클릭해도
# 열리지 않는다. README가 HOST=0.0.0.0 을 권하므로 이 경로가 실제로 쓰인다.
case "$HOST" in
  0.0.0.0|::|"") LINK_HOST="127.0.0.1" ;;
  *:*)           LINK_HOST="[$HOST]" ;;   # IPv6 리터럴은 URL에서 대괄호가 필요
  *)             LINK_HOST="$HOST" ;;
esac
[ -n "$OVERRIDDEN" ] || echo "→ http://${LINK_HOST}:${PORT}/"

exec "$VPY" -m uvicorn --factory claw_server:create_app \
  --host "$HOST" --port "$PORT" ${EXTRA+"${EXTRA[@]}"} "$@"
