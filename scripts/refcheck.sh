#!/usr/bin/env bash
# 문서 참조 검사기 실행 — 문서·코드의 `NN §X.Y` 참조가 실재하는 절을 가리키는지.
#
#   scripts/refcheck.sh
#
# **검사기 본문의 정본은 `docs/README.md` 「검사기」 절이다.** 거기 코드블록으로
# 실려 있는 이유는 규약을 읽는 사람이 그 규약을 집행하는 코드를 같은 자리에서 보게
# 하기 위해서다. 그래서 이 스크립트는 본문을 **복사해 두지 않고 추출해서 돌린다** —
# 복사하면 두 벌이 되고, 두 벌이면 한쪽은 반드시 낡는다(문서 지도 「결정은 한 곳에만」).
#
# 두 수 모두 0이 정상이고, 아니면 exit 1이라 훅·CI에 그대로 걸 수 있다
# (docs/README.md 「검사기」가 그 계약을 적어 둔 자리다).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

DOC="docs/README.md"
SRC="$(mktemp)"
trap 'rm -f "$SRC"' EXIT

# 「검사기」 절의 heredoc 본문만 — 여는 줄과 닫는 EOF는 버린다
sed -n "/^python3 - <<'EOF'\$/,/^EOF\$/p" "$DOC" | sed '1d;$d' > "$SRC"

# **추출 실패를 통과로 위장하지 않는다.** 빈 스크립트는 파이썬이 조용히 exit 0으로
# 끝내므로, 코드펜스 형태가 바뀌면 "끊긴 참조 0건"이 *검사하지 않은* 0건이 된다 —
# 이 리포가 규약 7(죽은 표식)에서 막으려는 것과 똑같은 병이다. 그래서 추출물이
# 검사기다운지 표식 하나로 확인하고, 아니면 시끄럽게 죽는다.
if [ ! -s "$SRC" ] || ! grep -q 'refcheck:ignore' "$SRC"; then
  echo "참조 검사기를 $DOC 에서 추출하지 못했다 — 「검사기」 절의 코드펜스" >&2
  echo "(python3 - <<'EOF' … EOF) 형태가 바뀌었는지 확인할 것." >&2
  exit 2
fi

exec python3 "$SRC"
