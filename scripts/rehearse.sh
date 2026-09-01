#!/usr/bin/env bash
# 반입 리허설 — dist/ 를 폐쇄망인 척 설치해서 증명한다.
#
#   scripts/bundle.sh && scripts/rehearse.sh
#
# 왜 필요한가: 반입은 망이동 시스템 승인을 거치는 느린 이벤트라, far side에서
# 설치가 실패하면 그 왕복이 통째로 다시 걸린다(며칠). 보내기 **전에** 실패를
# 발견하는 것이 이 스크립트의 존재 이유다.
#
# 격리 수준: pip에 --no-index 가 걸리므로 설치 중 PyPI 접근은 그 자리에서 실패한다.
# 임시 디렉터리에서만 작업하며 개발용 .venv 는 건드리지 않는다.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST="$ROOT/dist"
PORT="${PORT:-8199}"

[ -d "$DIST" ] || { echo "오류: dist/ 가 없습니다 — 먼저 scripts/bundle.sh 를 실행하세요." >&2; exit 1; }
[ -d "$DIST/wheelhouse" ] || { echo "오류: dist/wheelhouse 가 없습니다 (--code-only 로 만든 꾸러미는 리허설 대상이 아닙니다)." >&2; exit 1; }

if command -v sha256sum >/dev/null 2>&1; then
  SHA_C() { sha256sum -c --quiet MANIFEST.sha256; }
else
  SHA_C() { shasum -a 256 -c MANIFEST.sha256 >/dev/null; }
fi

WORK="$(mktemp -d)"
SRV_PID=""
# 실패했을 때 로그를 지우면 안 된다 — 화면에 남는 건 tail 15~30줄뿐이고, 그걸로는
# 대개 어느 테스트가 왜 죽었는지 안 보인다. 재현하려면 전 과정을 다시 돌려야 한다.
KEEP_WORK=""
# run.sh 는 uvicorn을 exec 하므로 서브셸만 죽이면 uvicorn이 손자로 살아남는다.
# 그대로 두면 다음 리허설이 "포트 사용 중"이라는 엉뚱한 실패로 죽으므로,
# 이 리허설이 쓰는 포트로 확실히 잡는다 (macOS·Linux 공통으로 pkill -f).
cleanup() {
  if [ -n "$SRV_PID" ]; then
    kill "$SRV_PID" 2>/dev/null || true
    wait "$SRV_PID" 2>/dev/null || true
  fi
  pkill -f "uvicorn .*--port $PORT" 2>/dev/null || true
  if [ -n "$KEEP_WORK" ]; then
    echo
    echo "로그를 남겨 뒀습니다: $WORK" >&2
    echo "  (다 보고 나서 rm -rf '$WORK')" >&2
  else
    rm -rf "$WORK"
  fi
}
trap cleanup EXIT

FAIL=0
step() { printf '\n=== %s ===\n' "$1"; }
ok()   { printf '  OK   %s\n' "$1"; }
bad()  { printf '  실패 %s\n' "$1"; FAIL=1; KEEP_WORK=1; }

# --- 1. 무결성 --------------------------------------------------------------
step "1/6 체크섬"
if (cd "$DIST" && SHA_C); then ok "MANIFEST.sha256 일치"; else bad "체크섬 불일치"; fi

# --- 2. 코드 풀기 -----------------------------------------------------------
# far side와 같은 경로를 밟는다 — 작업트리 복사가 아니라 번들에서 clone.
step "2/6 번들에서 clone"
if git clone --quiet "$DIST/claw-code.bundle" "$WORK/claw-demo" 2>/dev/null; then
  ok "clone 성공 ($(cd "$WORK/claw-demo" && git rev-parse --short HEAD))"
else
  bad "clone 실패"; exit 1
fi
REPO="$WORK/claw-demo"

# --- 3. 오프라인 설치 -------------------------------------------------------
step "3/6 오프라인 설치 (네트워크 차단)"
# 격리를 **실제로** 만든다. --no-index 만으로는 증명이 안 된다 — 그 플래그가 걸리면
# pip은 인덱스를 조회하지도, 자기 버전을 확인하지도 않으므로 "네트워크 흔적이
# 없다"는 로그 검사는 매칭될 경우가 아예 없어 언제나 통과한다(= 아무것도 증명 못 함).
# 죽은 포트를 프록시로 걸면 어떤 HTTP 시도든 그 자리에서 실패하므로, 설치가
# 성공했다는 사실 자체가 곧 오프라인 증명이 된다.
if (cd "$REPO" \
    && http_proxy=http://127.0.0.1:9 https_proxy=http://127.0.0.1:9 \
       HTTP_PROXY=http://127.0.0.1:9 HTTPS_PROXY=http://127.0.0.1:9 no_proxy= NO_PROXY= \
       bash scripts/setup.sh --offline "$DIST/wheelhouse" > "$WORK/setup.log" 2>&1); then
  ok "설치 완료 — 죽은 프록시 아래서 성공했으므로 네트워크를 쓰지 않았습니다"
else
  bad "설치 실패 — 아래는 로그 마지막 30줄"
  tail -30 "$WORK/setup.log" | sed 's/^/    /'
  echo "  전체 로그: $WORK/setup.log" >&2
  KEEP_WORK=1
  exit 1
fi

VPY="$REPO/.venv/bin/python"

# --no-index 가 실제로 걸렸는지 (find-links 경로를 탔다는 양성 증거)
if grep -q 'Looking in links:' "$WORK/setup.log"; then
  ok "wheelhouse 경로로 해석됨 (--no-index 적용 확인)"
else
  bad "find-links 흔적 없음 — --offline 이 실제로 걸리지 않았을 수 있습니다"
fi

# --- 4. 테스트 6종 ----------------------------------------------------------
step "4/6 테스트"
run_suite() { # 이름, 디렉터리, 명령…
  local name="$1" dir="$2"; shift 2
  # 두 형식을 함께 받는다 — pytest는 "509 passed", node --test는 "pass 242".
  # skip도 함께 보여준다: cc 없는 장비에서 flight 패리티 2건이 조용히 skip되는데,
  # 건수만 찍으면 "12 passed"가 아니라 "10 passed"인 걸 눈치채기 어렵다.
  if (cd "$dir" && "$@" > "$WORK/$name.log" 2>&1); then
    # || true 필수 — pipefail 아래서 grep이 못 찾으면(예: skip이 없는 스위트) 1을
    # 반환하고, 그 대입이 set -e에 걸려 리허설 전체가 여기서 조용히 끝난다.
    local n s count
    n="$(grep -oE '([0-9]+ passed|pass [0-9]+)' "$WORK/$name.log" | tail -1 || true)"
    s="$(grep -oE '[0-9]+ skipped' "$WORK/$name.log" | tail -1 || true)"
    # **0건은 실패로 친다.** `node --test`는 글로브가 하나도 안 맞으면 `pass 0`을 찍고
    # **종료코드 0**으로 끝난다(실측). 그러면 이 함수가 "OK world — pass 0"을 찍고
    # 리허설이 통과하는데, 그건 정확히 이 게이트가 막으려던 상태다 — 파일을 옮기거나
    # 확장자를 바꾸거나 번들에서 src/가 빠지면 전부 이 모양이 된다.
    # (pytest는 수집 0에서 종료코드 5라 위 if에서 이미 걸린다.)
    count="$(printf '%s' "$n" | grep -oE '[0-9]+' | tail -1 || true)"
    if [ -z "$count" ] || [ "$count" -eq 0 ]; then
      bad "$name — 통과 건수가 0입니다 (테스트를 하나도 못 찾았을 수 있습니다)"
      tail -15 "$WORK/$name.log" | sed 's/^/    /'
      return
    fi
    ok "$name — $n${s:+ · $s}"
  else
    bad "$name"
    tail -15 "$WORK/$name.log" | sed 's/^/    /'
  fi
}
run_suite engine "$REPO/engine" "$VPY" -m pytest -q
run_suite server "$REPO/server" "$VPY" -m pytest -q
run_suite flight "$REPO/flight" "$VPY" -m pytest -q   # cc 없으면 2건 skip
run_suite models "$REPO" "$VPY" -m pytest -q models   # 모델 생성 스크립트 유틸 (블렌더 불요)

if command -v node >/dev/null 2>&1; then
  run_suite web "$REPO/web" node --test "js/**/*.test.js"
  # **가상환경 탭은 별도 스위트다.** 위 글로브는 `web/js/**`만 훑어 `web/world/src`에
  # 닿지 못한다 — 안 걸어 두면 그 테스트들이 한 번도 안 돌면서 위 줄이 초록을 보고한다.
  run_suite world "$REPO/web/world" node --test "src/**/*.test.ts"
else
  echo "  건너뜀 web·world — node 없음 (구동에는 불필요, 대상 서버에도 없어도 됩니다)"
fi

# --- 5. 기동 ---------------------------------------------------------------
step "5/6 서버 기동"
(cd "$REPO" && PORT="$PORT" bash scripts/run.sh > "$WORK/run.log" 2>&1) &
SRV_PID=$!
for _ in $(seq 1 40); do
  curl -sf "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1 && break
  sleep 0.5
done

if curl -sf "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
  ok "/api/health 응답"
else
  bad "기동 실패"; tail -20 "$WORK/run.log" | sed 's/^/    /'
fi
if curl -sf "http://127.0.0.1:$PORT/" 2>/dev/null | grep -q '<title'; then
  ok "웹 UI 서빙 (editable 설치 경로 정상)"
else
  bad "웹 UI 404 — 비-editable 설치면 이렇게 됩니다"
fi

# --- 6. 웹소켓 --------------------------------------------------------------
# uvicorn[standard] 의 websockets 가 실제로 들어왔는지. 빠지면 업그레이드가 거절되고
# 진행률이 폴링으로 degrade 하는데, web/js/api.js 의 폴백 때문에 UI는 살아 있어
# 눈으로는 안 잡힌다 — 그래서 여기서 기계적으로 확인한다.
step "6/6 웹소켓 업그레이드"
if "$VPY" - "$PORT" <<'PY'
import asyncio, sys
try:
    import websockets
    from websockets.exceptions import InvalidStatus
except ImportError:
    print("websockets 미설치"); sys.exit(1)

async def main():
    url = f"ws://127.0.0.1:{sys.argv[1]}/api/ws/jobs/rehearsal-probe"
    try:
        async with websockets.connect(url) as ws:
            await asyncio.wait_for(ws.recv(), timeout=5)
        return 0
    except InvalidStatus as e:
        print("업그레이드 거절 HTTP", e.response.status_code); return 1

sys.exit(asyncio.run(main()))
PY
then ok "101 업그레이드 성립 (폴백 아님)"; else bad "업그레이드 실패"; fi

# --- 결과 -----------------------------------------------------------------
echo
if [ "$FAIL" -eq 0 ]; then
  echo "리허설 통과 — 이 꾸러미는 폐쇄망에서 동작합니다."
  echo "dist/ 를 망이동 시스템에 올리세요."
else
  echo "리허설 실패 — 위 항목을 고치고 bundle.sh 부터 다시 하세요." >&2
  echo "보내기 전에 발견한 것이 이 스크립트의 목적입니다." >&2
  exit 1
fi
