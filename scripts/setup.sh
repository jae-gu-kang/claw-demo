#!/usr/bin/env bash
# CLAW_DEMO 설치 — 로컬·devcontainer 공용 단일 소스.
# .devcontainer/devcontainer.json의 postCreateCommand가 이 파일을 그대로 호출하므로
# 설치 절차를 여기 말고 다른 데 복제하지 말 것.
#
# 멱등: 이미 설치된 상태에서 다시 돌려도 안전하다.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-python3}"
VENV="$ROOT/.venv"

# --- 1. 파이썬 버전 ---------------------------------------------------------
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "오류: '$PY' 를 찾을 수 없습니다. Python 3.10+ 를 설치하거나 PYTHON=... 으로 지정하세요." >&2
  exit 1
fi

if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "오류: Python 3.10 이상이 필요합니다 (현재: $("$PY" -c 'import sys; print(sys.version.split()[0])'))." >&2
  exit 1
fi

echo "[1/4] Python $("$PY" -c 'import sys; print(sys.version.split()[0])') 확인"

# --- 2. 가상환경 -----------------------------------------------------------
# 컨테이너 안에서도 venv를 그대로 쓴다. 중복이지만 로컬과 코드 경로가 하나로 유지된다.
#
# 재사용 판정을 bin/python 존재가 아니라 **pip 동작 여부**로 한다. `python -m venv`는
# bin/python 심볼릭을 먼저 만들고 그 뒤 ensurepip에서 실패할 수 있는데(데비안·우분투에서
# python3-venv 미설치가 정확히 이 상태를 남긴다), 존재만 보면 그 반쯤 만들어진 venv를
# "재사용"으로 판정해 매번 같은 자리에서 죽는다. 사용자가 원인을 고쳐도 생성 분기를
# 영원히 건너뛰므로 스스로 rm -rf .venv 를 떠올리지 않는 한 복구되지 않는다.
if "$VENV/bin/python" -m pip --version >/dev/null 2>&1; then
  echo "[2/4] 기존 .venv 재사용"
  # 위 [1/4]가 확인한 건 "새로 만들 때 쓸 인터프리터"지 재사용되는 venv의 것이
  # 아니다. PYTHON=python3.12 로 3.10 venv 위에서 돌리면 3.12를 확인했다고
  # 출력한 뒤 3.10에 설치하게 되므로, 어긋나면 사실을 알린다.
  # 순수 안내용 체크이므로 실패해도 설치를 막지 않는다. set -e 아래서 VAR="$(cmd)"
  # 대입은 치환의 종료 코드를 그대로 물려받아, 이 진단 한 줄이 설치 전체를 말없이
  # 죽일 수 있다. tail -1은 파이썬 래퍼가 stdout에 배너를 찍는 환경(pyenv shim 등)에서
  # 값이 여러 줄이 되어 없는 불일치를 경고하는 것을 막는다.
  VENV_VER="$("$VENV/bin/python" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null | tail -1 || true)"
  PY_VER="$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null | tail -1 || true)"
  if [ -n "$VENV_VER" ] && [ -n "$PY_VER" ] && [ "$VENV_VER" != "$PY_VER" ]; then
    echo "  주의: 기존 .venv는 Python $VENV_VER 이고 '$PY'는 $PY_VER 입니다." >&2
    echo "        설치는 기존 .venv($VENV_VER)에 들어갑니다 — 바꾸려면 rm -rf .venv 후 재실행." >&2
  fi
else
  # pip이 없는 venv는 깨진 것일 수도, uv venv처럼 의도적으로 pip을 뺀 것일 수도
  # 있다. 어느 쪽이든 이 스크립트는 pip으로 설치하므로 재생성해야 하는데,
  # 지웠다는 사실을 말하지 않으면 "내 패키지 어디 갔지"가 된다.
  if [ -d "$VENV" ]; then
    echo "[2/4] 기존 .venv가 pip을 쓸 수 없는 상태 — 지우고 재생성합니다"
  else
    echo "[2/4] 가상환경 생성 → .venv"
  fi
  [ -n "$VENV" ] && [ "$VENV" != "/" ] && rm -rf "$VENV"   # 깨진 잔재 제거
  if ! "$PY" -m venv "$VENV"; then
    # 실패한 껍데기를 남기면 다음 실행이 같은 함정에 빠진다.
    [ -n "$VENV" ] && [ "$VENV" != "/" ] && rm -rf "$VENV"
    echo "오류: 가상환경 생성 실패." >&2
    echo "  데비안·우분투라면: sudo apt install python3-venv" >&2
    exit 1
  fi
fi

VPY="$VENV/bin/python"
"$VPY" -m pip install --upgrade --quiet pip

# --- 3. 패키지 (설치 순서가 중요) -------------------------------------------
# claw-engine은 server/pyproject.toml에 의도적으로 미기재다 — 동명 PyPI 패키지
# 오설치를 막기 위함(server/pyproject.toml 주석 참조). 따라서 engine을 먼저
# 깔지 않으면 claw_server가 import 단계에서 claw를 못 찾는다. 순서를 바꾸지 말 것.
#
# editable(-e) 유지도 필수다. claw_server/app.py의 _default_web_dir()가
# __file__ 기준 parents[2]/web 으로 정적 파일을 찾기 때문에, 비-editable로
# site-packages에 깔면 경로가 어긋나 웹 UI가 404가 된다(API만 동작).
echo "[3/4] 의존성 설치 — numpy·scipy 등으로 처음엔 몇 분 걸립니다"
"$VPY" -m pip install -e engine
"$VPY" -m pip install -e "server[dev]"

# --- 4. 자기검증 -----------------------------------------------------------
echo "[4/4] 설치 검증"
"$VPY" - <<'EOF'
import importlib

for mod in ("claw", "claw_server", "fastapi", "uvicorn", "websockets"):
    importlib.import_module(mod)
print("  import OK — claw, claw_server, fastapi, uvicorn, websockets")
EOF

cat <<EOF

설치 완료. 기동:

  scripts/run.sh

그 다음 브라우저에서 http://127.0.0.1:8000/
EOF
