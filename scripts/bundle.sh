#!/usr/bin/env bash
# 폐쇄망 반입 산출물 생성
#
#   scripts/bundle.sh              # 코드 + 의존성 → dist/
#   scripts/bundle.sh --code-only  # 코드만 → dist-code/  (의존성이 안 바뀐 재반입)
#
# 반입은 사내 망이동 시스템을 거치는 느린 승인 이벤트다. 그래서 **반입 횟수**를
# 줄이는 게 최적화 대상이고, 코드(~0.9MB)와 의존성(수십 MB)을 갈라 담는 이유가
# 그것이다. 락파일이 안 바뀌었으면 --code-only 로 1MB 미만만 보내면 된다.
#
# 출력 디렉터리를 모드별로 나눈 이유: 같은 곳에 쓰면 --code-only 한 번에 이전
# wheelhouse가 지워진다(업로드 도중일 수도 있다).
#
# **반드시 대상 플랫폼(Linux x86_64)에서 실행할 것** — 휠은 플랫폼별 바이너리다.
# requirements.lock 머리의 각인과 대조해 어긋나면 여기서 멈춘다.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-python3}"
LOCK="$ROOT/requirements.lock"

# setup.sh와 같은 방식으로 전 인자를 본다. `[ "$1" = ... ]` 로 첫 인자만 보면
# `bundle.sh --verbose --code-only` 가 말없이 **전체 꾸러미**를 만든다 —
# 0.9MB냐 수십 MB냐가 승인 큐를 타는 상황에서 조용히 틀리면 안 된다.
CODE_ONLY=""
while [ $# -gt 0 ]; do
  case "$1" in
    --code-only) CODE_ONLY=1; shift ;;
    -h|--help)
      cat <<'USAGE'
폐쇄망 반입 꾸러미 생성

  scripts/bundle.sh              # 코드 + 의존성 → dist/
  scripts/bundle.sh --code-only  # 코드만 → dist-code/

대상 플랫폼(Linux x86_64)에서 실행할 것. 절차는 docs/deploy-airgap.md.
USAGE
      exit 0 ;;
    *) echo "오류: 알 수 없는 인자 '$1' (사용법은 --help)." >&2; exit 2 ;;
  esac
done

DIST="$ROOT/dist"
[ -n "$CODE_ONLY" ] && DIST="$ROOT/dist-code"

# sha256: 리눅스는 sha256sum, macOS는 shasum -a 256. 출력 형식은 서로 호환되므로
# far side 안내에는 양쪽 명령을 다 적어 둔다(대상은 Linux지만 꾸러미를 검사하는
# 자리가 늘 Linux라는 보장은 없다).
if command -v sha256sum >/dev/null 2>&1; then
  SHA() { sha256sum "$@"; }
else
  SHA() { shasum -a 256 "$@"; }
fi

# --- 1. 전제 검사 -----------------------------------------------------------
[ -f "$LOCK" ] || { echo "오류: requirements.lock 이 없습니다 — 먼저 scripts/lock.sh 를 실행하세요." >&2; exit 1; }

PLATFORM="$("$PY" -c 'import sysconfig; print(sysconfig.get_platform())')"
PYVER="$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
LOCK_PLATFORM="$(sed -n 's/^# platform: //p' "$LOCK" | head -1)"
LOCK_PYVER="$(sed -n 's/^# python: //p' "$LOCK" | head -1)"

# --code-only 에서도 반드시 대조한다. 휠을 안 담아도 **requirements.lock 자체가
# 커밋되어 git bundle을 타고 far side로 가고**, 거기서 setup.sh가 -c 제약으로 건다.
# 엉뚱한 플랫폼에서 만든 락이 실려 가면 기존 wheelhouse와 안 맞아 설치가 죽는데,
# 재반입이 주 경로인 --code-only에서 방어가 빠져 있으면 그게 상시 위험이 된다.
if [ "$PLATFORM" != "$LOCK_PLATFORM" ] || [ "$PYVER" != "$LOCK_PYVER" ]; then
  echo "오류: 락파일과 현재 환경이 다릅니다 — 대상에서 설치가 실패합니다." >&2
  echo "  락파일: $LOCK_PLATFORM · Python $LOCK_PYVER" >&2
  echo "  현재:   $PLATFORM · Python $PYVER" >&2
  echo "  대상 플랫폼(Codespaces 등)에서 scripts/lock.sh 부터 다시 실행하세요." >&2
  echo "  (--code-only 라도 락파일은 번들에 실려 가므로 이 검사를 건너뛰지 않습니다.)" >&2
  exit 1
fi

# 미커밋 변경은 git bundle에 안 담긴다 — 모르고 보내면 반입한 코드가 여기서
# 테스트한 코드와 다르다. 반입 왕복 비용이 크므로 조용히 넘기지 않는다.
if [ -n "$(git status --porcelain)" ]; then
  echo "오류: 커밋되지 않은 변경이 있습니다. git bundle 은 커밋된 것만 담습니다." >&2
  echo "  아래를 커밋하거나 되돌린 뒤 다시 실행하세요:" >&2
  git status --short >&2
  exit 1
fi

rm -rf "$DIST"
mkdir -p "$DIST"

# --- 2. 코드 ---------------------------------------------------------------
# git bundle = 전체 이력이 담긴 파일 하나. 작업트리 zip보다 나은 이유: far side에서
# 그냥 clone 하면 되고, 다음 반입 때 증분 번들(A..B)로 더 작게 보낼 수 있다.
#
# --all 이 아니라 main만 담는다 — 로컬 실험 브랜치·remote-tracking ref까지 폐쇄망에
# 들여보내면 승인 surface만 넓어진다. HEAD를 함께 넣어야 clone이 체크아웃할
# 브랜치를 안다.
echo "[1/4] 코드 번들"
git rev-parse --verify main >/dev/null 2>&1 || { echo "오류: main 브랜치가 없습니다." >&2; exit 1; }
[ "$(git rev-parse HEAD)" = "$(git rev-parse main)" ] || {
  echo "오류: HEAD가 main과 다릅니다 — 반입물은 main 기준입니다." >&2
  echo "  현재: $(git rev-parse --abbrev-ref HEAD)" >&2
  exit 1
}
git bundle create "$DIST/claw-code.bundle" HEAD main 2>&1 | sed 's/^/  /'
git rev-parse HEAD > "$DIST/COMMIT"

if [ -n "$CODE_ONLY" ]; then
  echo "[2/4] 의존성 건너뜀 (--code-only)"
  echo "[3/4] 락파일 사본 건너뜀"
else
  # --- 3. 의존성 -----------------------------------------------------------
  echo "[2/4] 휠 수집 — 몇 분 걸립니다"
  mkdir -p "$DIST/wheelhouse"
  "$PY" -m pip download --quiet --only-binary=:all: \
    --dest "$DIST/wheelhouse" -r "$LOCK"

  # setuptools·wheel은 런타임 의존이 아니라서 락파일에 없다. 하지만 far side에서
  # `pip install -e` 가 **빌드 격리**를 위해 이 둘을 새로 받으려 하고, 폐쇄망에선
  # 그 순간 실패한다. 이 계획에서 가장 놓치기 쉬운 함정이라 명시적으로 담는다.
  # pip 자신도 담는다 — 대상의 pip이 낡아 최신 휠 태그를 못 읽는 경우의 보험.
  echo "[3/4] 빌드 도구 휠 (setuptools·wheel·pip) — -e 설치의 빌드 격리용"
  "$PY" -m pip download --quiet --only-binary=:all: \
    --dest "$DIST/wheelhouse" setuptools wheel pip

  cp "$LOCK" "$DIST/requirements.lock"
fi

# --- 4. 무결성·안내 ---------------------------------------------------------
# 망이동 시스템이 압축을 풀어 검사하거나 파일을 건드릴 수 있다. far side에서
# 이걸로 검증하지 않으면 손상된 휠이 설치 중에 이상한 오류로 나타난다.
{
cat <<EOF
CLAW_DEMO 반입 꾸러미
=====================

생성: $(git rev-parse --short HEAD) · $PLATFORM · Python $PYVER
종류: $([ -n "$CODE_ONLY" ] && echo "코드만 (의존성은 기존 것 재사용)" || echo "코드 + 의존성 (최초 반입)")

폐쇄망에서 할 일
----------------

1) 무결성 확인 (이 디렉터리에서)
   sha256sum -c MANIFEST.sha256          # macOS라면: shasum -a 256 -c MANIFEST.sha256
EOF

if [ -n "$CODE_ONLY" ]; then
cat <<'EOF'

2) 기존 클론에 코드 갱신 — wheelhouse는 이미 반입돼 있어야 합니다
   cd claw-demo
   git fetch /경로/claw-code.bundle main
   git reset --hard "$(cat /경로/COMMIT)"
   git rev-parse HEAD                    # COMMIT 파일과 같은지 눈으로 확인

   git pull 을 쓰지 마세요. 일반망에서 커밋을 고쳐 쓴 적이 있으면(amend·rebase)
   이력이 갈라져 있고, pull은 그걸 **머지**해 버립니다. 충돌이 없으면 조용히
   섞인 트리가 남는데, 그건 아무도 리허설한 적 없는 코드입니다.
   reset --hard 는 이 장비의 로컬 변경을 버립니다 — 배포 장비이므로 그게 맞습니다.

3) 의존성 재확인 (락파일이 안 바뀌었으면 아무것도 안 깝니다)
   scripts/setup.sh --offline /경로/wheelhouse

   여기서 "찾을 수 없다"는 오류가 나면 원인이 둘입니다.
   - 이 장비의 Python/플랫폼이 꾸러미와 다름 → setup.sh가 그렇다고 말해 줍니다.
     그 경우 재반입해도 똑같이 실패합니다.
   - 정말 의존성이 바뀜 → 일반망에서 전체 꾸러미를 다시 만들어 반입하세요.

4) 재기동 (돌던 서버를 멈추고)
EOF
else
cat <<'EOF'

2) 코드 풀기
   git clone claw-code.bundle claw-demo
   cd claw-demo

3) 설치 (네트워크를 쓰지 않습니다)
   scripts/setup.sh --offline ../wheelhouse

4) 기동
EOF
fi

cat <<'EOF'
   scripts/run.sh                  # 본인만 쓸 때
   HOST=0.0.0.0 scripts/run.sh     # 팀원이 접속할 때

   브라우저에서 http://<서버IP>:8000/

운영 주의
---------

* uvicorn 워커를 늘리지 마세요. 작업 관리자가 프로세스 메모리에 있어서
  --workers 2 이상이면 진행률 조회가 조용히 404가 됩니다.
* 항상 리포 루트에서 기동하세요. 결과 저장 경로가 CWD 상대경로입니다.
  (scripts/run.sh 가 알아서 이동합니다)
* 이 서버에는 인증이 없습니다. 신뢰된 망에서만 쓰세요.

자세한 절차: docs/deploy-airgap.md
EOF
# 파일명은 ASCII로 — 망이동 시스템이 비ASCII 파일명을 음역하거나 인코딩을 바꾸면
# far side의 첫 단계인 sha256sum -c 가 실패하고, 담당자는 "전송이 꾸러미를
# 손상시켰다"는 합리적이지만 틀린 결론에 이른다. 내용은 한글 그대로.
} > "$DIST/README-airgap.txt"

# 안내문까지 만든 뒤에 걸어야 그것도 검증 대상에 든다. 경로를 dist 기준
# 상대경로로 적어야 far side에서 그대로 -c 검증이 된다.
echo "[4/4] 체크섬"
(
  cd "$DIST"
  find . -type f ! -name MANIFEST.sha256 | LC_ALL=C sort | while IFS= read -r f; do
    SHA "$f"
  done > MANIFEST.sha256
)

echo
echo "완료 — $DIST"
du -sh "$DIST" | awk '{print "  전체:      " $1}'
[ -d "$DIST/wheelhouse" ] && {
  du -sh "$DIST/wheelhouse" | awk '{print "  wheelhouse: " $1}'
  echo "  휠 개수:    $(ls -1 "$DIST/wheelhouse" | wc -l | tr -d ' ')"
}
du -sh "$DIST/claw-code.bundle" | awk '{print "  코드 번들:  " $1}'
echo
echo "망이동 시스템의 크기·형식 제한과 위 수치를 대조하세요."
if [ -n "$CODE_ONLY" ]; then
  # rehearse.sh는 wheelhouse가 있어야 돌므로 code-only 꾸러미에는 권하지 않는다.
  echo "코드만 담았습니다 — 대상에 wheelhouse가 이미 반입돼 있어야 합니다."
  echo "의존성이 바뀌었다면(git diff requirements.lock) --code-only 없이 다시 만드세요."
else
  echo "보내기 전에 scripts/rehearse.sh 로 오프라인 설치를 증명하는 것을 권합니다."
fi
