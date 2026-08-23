#!/usr/bin/env bash
# CLAW_DEMO 설치 — 로컬·devcontainer·폐쇄망 공용 단일 소스.
# .devcontainer/devcontainer.json의 postCreateCommand가 이 파일을 그대로 호출하므로
# 설치 절차를 여기 말고 다른 데 복제하지 말 것.
#
#   scripts/setup.sh                        # PyPI에서 설치 (일반망)
#   scripts/setup.sh --offline dist/wheelhouse   # 미리 받아둔 휠로만 설치 (폐쇄망)
#
# 멱등: 이미 설치된 상태에서 다시 돌려도 안전하다.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-python3}"
VENV="$ROOT/.venv"

# --- 0. 인자 --------------------------------------------------------------
# --offline은 pip에 --no-index --find-links를 붙일 뿐, 아래 설치 절차 자체는
# 온라인과 완전히 같은 경로를 탄다. 폐쇄망용 설치 스크립트를 따로 만들면
# 절차가 둘로 갈라져 "일반망에서만 되는" 상태가 다시 생긴다.
OFFLINE_DIR=""
while [ $# -gt 0 ]; do
  case "$1" in
    --offline)
      [ $# -ge 2 ] || { echo "오류: --offline 뒤에 wheelhouse 경로가 필요합니다." >&2; exit 2; }
      OFFLINE_DIR="$2"
      shift 2
      ;;
    --offline=*)
      OFFLINE_DIR="${1#--offline=}"
      # 빈 값(`--offline=`)을 그냥 두면 아래 전 분기가 [ -n "$OFFLINE_DIR" ] 로
      # 갈리므로 **말없이 온라인 설치로 떨어진다** — 폐쇄망에서 그건 실패가 아니라
      # 잘못된 성공이라 더 나쁘다.
      [ -n "$OFFLINE_DIR" ] || { echo "오류: --offline= 에 wheelhouse 경로가 비었습니다." >&2; exit 2; }
      shift
      ;;
    -h|--help)
      # 헤더 주석을 sed로 잘라 쓰면 주석 한 줄만 늘어도 어긋난다. 여기 직접 적는다.
      cat <<'USAGE'
CLAW_DEMO 설치

  scripts/setup.sh                             # PyPI에서 설치 (일반망)
  scripts/setup.sh --offline dist/wheelhouse   # 미리 받아둔 휠로만 설치 (폐쇄망)

멱등: 이미 설치된 상태에서 다시 돌려도 안전하다.
폐쇄망 절차 전체는 docs/deploy-airgap.md 참조.
USAGE
      exit 0
      ;;
    *)
      echo "오류: 알 수 없는 인자 '$1' (사용법은 --help)." >&2
      exit 2
      ;;
  esac
done

PIP_ARGS=()
if [ -n "$OFFLINE_DIR" ]; then
  # 상대경로로 받아도 되게 절대경로화 — 아래에서 cd 하지는 않지만, 오류 메시지와
  # pip 인자가 호출 위치에 따라 달라지면 진단이 어렵다.
  case "$OFFLINE_DIR" in /*) ;; *) OFFLINE_DIR="$ROOT/$OFFLINE_DIR" ;; esac
  if [ ! -d "$OFFLINE_DIR" ]; then
    echo "오류: wheelhouse 디렉터리가 없습니다 — $OFFLINE_DIR" >&2
    exit 1
  fi
  PIP_ARGS=(--no-index --find-links "$OFFLINE_DIR")
  echo "[0/4] 오프라인 설치 — $OFFLINE_DIR ($(ls -1 "$OFFLINE_DIR" | wc -l | tr -d ' ')개 파일)"
fi

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

# 오프라인일 땐 PyPI에 못 나가므로 wheelhouse에 pip 휠이 있을 때만 갱신한다.
# 없어도 설치는 진행 — 실패해도 무해하도록 || true.
if [ -n "$OFFLINE_DIR" ]; then
  "$VPY" -m pip install --upgrade --quiet --no-index --find-links "$OFFLINE_DIR" pip 2>/dev/null || true
else
  "$VPY" -m pip install --upgrade --quiet pip
fi

# 락파일이 있으면 제약으로 건다 — 상한 핀이 없는 pyproject(numpy>=1.24 등)만으로는
# 설치 시점마다 다른 조합이 나와, 반입 번들이 "테스트한 적 없는 버전 조합"이 된다.
# -c는 설치 목록을 늘리지 않고 고를 수 있는 버전만 좁히므로, 락파일이 없던
# 예전 동작과 호환된다.
LOCK_ARGS=()
if [ -f "$ROOT/requirements.lock" ]; then
  LOCK_ARGS=(-c "$ROOT/requirements.lock")

  # 오프라인이면 이 환경이 휠을 만든 환경과 같은지 **여기서** 확인한다.
  # 안 하면 증상이 "Could not find a version that satisfies..." 로 나오는데, 그건
  # 의존성이 바뀐 것과 구분이 안 된다. 담당자는 66MB 전체 재반입(며칠)을 하고
  # 돌아와 똑같이 실패한다 — 진단을 여기서 이름 대어 끝낸다.
  #
  # 파이썬 마이너 버전이 다르면 cp3XX 휠이 전부 후보에서 탈락하고, 플랫폼이
  # 다르면 애초에 다른 바이너리다. 둘 다 치명적이라 경고가 아니라 중단.
  if [ -n "$OFFLINE_DIR" ]; then
    LOCK_PLATFORM="$(sed -n 's/^# platform: //p' "$ROOT/requirements.lock" | head -1)"
    LOCK_PYVER="$(sed -n 's/^# python: //p' "$ROOT/requirements.lock" | head -1)"
    HERE_PLATFORM="$("$VPY" -c 'import sysconfig; print(sysconfig.get_platform())')"
    HERE_PYVER="$("$VPY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
    if [ -n "$LOCK_PLATFORM" ] && { [ "$LOCK_PLATFORM" != "$HERE_PLATFORM" ] || [ "$LOCK_PYVER" != "$HERE_PYVER" ]; }; then
      echo "오류: 이 꾸러미는 다른 환경에서 만들어졌습니다 — 휠이 맞지 않습니다." >&2
      echo "  꾸러미: $LOCK_PLATFORM · Python $LOCK_PYVER" >&2
      echo "  이 장비: $HERE_PLATFORM · Python $HERE_PYVER" >&2
      echo >&2
      echo "  의존성이 바뀐 게 아닙니다 — 다시 반입해도 같은 실패가 납니다." >&2
      echo "  이 장비에 Python $LOCK_PYVER 를 두거나(PYTHON=python$LOCK_PYVER 로 지정)," >&2
      echo "  일반망에서 이 장비와 같은 환경으로 꾸러미를 다시 만드세요." >&2
      exit 1
    fi
  fi
fi

# --- 3. 패키지 (설치 순서가 중요) -------------------------------------------
# claw-engine은 server/pyproject.toml에 의도적으로 미기재다 — 동명 PyPI 패키지
# 오설치를 막기 위함(server/pyproject.toml 주석 참조). 따라서 engine을 먼저
# 깔지 않으면 claw_server가 import 단계에서 claw를 못 찾는다. 순서를 바꾸지 말 것.
#
# editable(-e) 유지도 필수다. claw_server/app.py의 _default_web_dir()가
# __file__ 기준 parents[2]/web 으로 정적 파일을 찾기 때문에, 비-editable로
# site-packages에 깔면 경로가 어긋나 웹 UI가 404가 된다(API만 동작).
#
# 오프라인에서 -e 설치는 빌드 격리 때문에 setuptools·wheel을 **새로 받으려 한다**.
# wheelhouse에 그 둘이 없으면 여기서 네트워크로 나가 실패하므로 scripts/bundle.sh가
# 반드시 함께 담는다 (가장 놓치기 쉬운 함정).
#
# 배열 확장에 ${X+"${X[@]}"} 를 쓰는 이유: macOS 기본 bash 3.2는 set -u 아래서
# 빈 배열의 "${X[@]}" 를 unbound variable로 본다 (scripts/run.sh의 EXTRA와 같은 이유).
echo "[3/4] 의존성 설치 — numpy·scipy 등으로 처음엔 몇 분 걸립니다"
"$VPY" -m pip install ${PIP_ARGS+"${PIP_ARGS[@]}"} ${LOCK_ARGS+"${LOCK_ARGS[@]}"} -e engine
"$VPY" -m pip install ${PIP_ARGS+"${PIP_ARGS[@]}"} ${LOCK_ARGS+"${LOCK_ARGS[@]}"} -e "server[dev]"

# --- 4. 자기검증 -----------------------------------------------------------
echo "[4/4] 설치 검증"
"$VPY" - <<'EOF'
import importlib

for mod in ("claw", "claw_server", "fastapi", "uvicorn", "websockets"):
    importlib.import_module(mod)
print("  import OK — claw, claw_server, fastapi, uvicorn, websockets")
EOF

# wheelhouse 경로를 venv 옆에 남긴다 — scripts/run.sh가 환경이 깨졌을 때 자동
# 복구를 시도하는데, 이 표식이 없으면 **PyPI로 나가려 한다**. 폐쇄망에서 그건
# systemd Restart=on-failure 아래 무한 재시도 루프가 된다.
if [ -n "$OFFLINE_DIR" ]; then
  printf '%s\n' "$OFFLINE_DIR" > "$VENV/.claw-offline-wheelhouse"
else
  rm -f "$VENV/.claw-offline-wheelhouse"
fi

cat <<EOF

설치 완료. 기동:

  scripts/run.sh

그 다음 브라우저에서 http://127.0.0.1:8000/
EOF
