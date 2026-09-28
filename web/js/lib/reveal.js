/** 결과가 사는 패널을 화면 안으로 (06 §2 「결과가 나오면 그 결과가 사는 패널을 연다」).

패널을 여는 것(drawers.open)만으로는 청중이 결과를 못 본다 — 패널이 접힌 칩 아래, 스크롤 밖에 열린다.
쇼케이스 신호가 끝나면 그 패널의 머리를 화면 위로 부드럽게 굴린다. 모션 축소 설정이면 부드러운 이동을 끈다
(`behavior: "smooth"`는 그 설정을 무시한다 — views/blocks.js가 기본값을 쓰는 이유와 같다).
떨어진 노드(떠난 화면 — 잡이 끝난 뒤의 보고는 DOM과 무관하게 간다)는 굴리지 않는다: 지금 보는 탭이 튄다.
*/

/** node를 화면 안으로 — 굴렸으면 true. block: "start"(패널 머리를 위로)·"center"·"nearest". */
export function revealPanel(node, { block = "start", win = globalThis.window } = {}) {
  if (!node || typeof node.scrollIntoView !== "function") return false;
  if (node.isConnected === false) return false;
  let reduce = false;
  try {
    reduce = win?.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches === true;
  } catch {
    reduce = false; // 설정을 못 읽으면 기본(부드럽게) — 보이기가 신호 실패의 원인이 되지 않게
  }
  node.scrollIntoView({ block, behavior: reduce ? "auto" : "smooth" });
  return true;
}
