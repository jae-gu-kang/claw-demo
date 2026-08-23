#!/usr/bin/env bash
# requirements.lock 생성 — 의존성 정본.
#
#   scripts/lock.sh
#
# pyproject의 의존성에는 상한 핀이 없다(numpy>=1.24, scipy>=1.11, control>=0.10 …).
# 그래서 설치 시점마다 다른 조합이 나오고, 폐쇄망 반입 번들을 만드는 날 담기는 건
# **한 번도 테스트해 본 적 없는 최신 조합**이 된다. 락파일은 그걸 막는다.
#
# 반입 전략(코드는 자주 작게, 의존성은 드물게 크게)이 성립하려면 "의존성이 정말
# 안 바뀌었나"를 판정할 수단이 필요한데, 이 파일의 diff가 곧 그 판정이다.
#
# **반드시 대상 플랫폼(Linux x86_64)에서 실행할 것.** 다른 플랫폼에서 만들면 환경
# 마커가 다르게 평가돼 대상에 없는/빠진 패키지가 생긴다. 생성된 파일 머리에 플랫폼을
# 각인하고 scripts/bundle.sh가 그걸 대조하므로, 어긋나면 번들 생성에서 걸린다.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-python3}"
OUT="$ROOT/requirements.lock"

PLATFORM="$("$PY" -c 'import sysconfig; print(sysconfig.get_platform())')"
PYVER="$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"

case "$PLATFORM" in
  linux-x86_64)
    ;;
  *)
    echo "주의: 현재 플랫폼이 $PLATFORM 입니다 — 대상은 linux-x86_64 입니다." >&2
    echo "      환경 마커가 다르게 평가돼 대상과 다른 의존성 집합이 나올 수 있습니다." >&2
    echo "      Codespaces에서 실행하는 것을 권합니다. (계속 진행하지만 파일에 각인됩니다)" >&2
    ;;
esac

# 격리된 임시 venv에서 해석한다 — 개발용 .venv에는 과거에 손으로 깐 패키지가
# 섞여 있을 수 있고(이 리포에서 실제로 uvicorn[standard]가 그랬다), 그게 락에
# 들어가면 "왜 깔리는지 아무도 모르는 의존성"이 정본이 된다.
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "[1/3] 임시 환경 생성 (Python $PYVER · $PLATFORM)"
"$PY" -m venv "$TMP/venv"
TPY="$TMP/venv/bin/python"
"$TPY" -m pip install --upgrade --quiet pip

# 비-editable로 깐다 — 버전 해석 결과만 필요하고, editable은 freeze 출력이 지저분하다.
echo "[2/3] 의존성 해석 — 몇 분 걸립니다"
"$TPY" -m pip install --quiet ./engine "./server[dev]"

echo "[3/3] $OUT 기록"
# 임시 파일에 다 쓰고 나서 옮긴다. $OUT 으로 직접 리다이렉트하면 셸이 **파이프라인이
# 돌기 전에** 기존 락을 0바이트로 자르므로, pipefail 아래서 grep이 1을 반환하는
# 것만으로도 헤더만 남은 락파일이 그 자리를 차지한다 — 그 파일이 "의존성이
# 바뀌었나"의 판정 정본이라 조용히 망가지면 안 된다.
NEW="$TMP/requirements.lock"
{
  echo "# CLAW_DEMO 의존성 정본 — scripts/lock.sh 가 생성. 손으로 고치지 말 것."
  echo "#"
  echo "# platform: $PLATFORM"
  echo "# python: $PYVER"
  echo "#"
  echo "# 이 파일은 scripts/setup.sh 가 -c(제약)로 걸고, scripts/bundle.sh 가 휠 수집"
  echo "# 목록으로 쓴다. 위 platform/python 이 번들 생성 환경과 다르면 bundle.sh 가 거부한다."
  echo "#"
  echo "# 빌드 도구(setuptools·wheel)는 여기 없다 — 런타임 의존이 아니라 -e 설치의"
  echo "# 빌드 격리에 필요한 것이라, bundle.sh 가 따로 담는다."
  # claw-engine·claw-server는 로컬 패키지라 제외. pip·setuptools·wheel은 빌드 도구라 제외.
  #
  # 구분자를 [=@ ] 로 받는 이유: 로컬 디렉터리를 비-editable로 깔면 freeze가
  # `claw-engine==0.1.0` 이 아니라 `claw-engine @ file:///…` (PEP 508 직접 참조)를
  # 낸다. `==` 로만 거르면 **빌드 머신의 절대경로가 락파일에 박혀** 폐쇄망까지
  # 실려 가고, 그 경로는 대상에 존재하지 않는다.
  "$TPY" -m pip freeze --exclude-editable \
    | grep -viE '^(claw-engine|claw-server|pip|setuptools|wheel)([=@ ]|$)' \
    | sort -f
} > "$NEW"

COUNT="$(grep -cvE '^#' "$NEW" || true)"
# 해석이 뭔가 잘못돼 빈 목록이 나온 것을 정본으로 승격시키지 않는다.
if [ "$COUNT" -lt 10 ]; then
  echo "오류: 고정된 패키지가 ${COUNT}개뿐입니다 — 해석이 실패한 것으로 보입니다." >&2
  echo "  기존 $OUT 은 건드리지 않았습니다." >&2
  exit 1
fi
mv "$NEW" "$OUT"
echo
# ${COUNT}개 — 중괄호 필수. macOS 기본 bash 3.2는 "$COUNT개"에서 뒤따르는 한글
# 바이트를 변수명의 일부로 읽어 set -u 아래 unbound variable로 죽는다.
echo "완료 — ${COUNT}개 패키지 고정 ($PLATFORM · Python $PYVER)"
echo "git diff requirements.lock 으로 무엇이 움직였는지 확인하세요."
