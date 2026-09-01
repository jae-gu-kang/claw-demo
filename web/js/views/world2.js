/** 가상환경(신) — Vite/React 번들로 넘기는 얇은 어댑터.
 *
 * ## 왜 임시 라우트인가
 *
 * 재설계가 기존 `#world`와 기능 동등에 이를 때까지 **도는 화면을 살려 둔다.**
 * 내비 링크는 만들지 않는다 — `#world2`를 직접 쳐야 열리므로 사용자 화면에 잡음이
 * 늘지 않는다. 동등해지면 이 파일이 `world.js`를 대체하고 라우트가 하나로 돌아간다.
 *
 * ## 세션 토큰
 *
 * `render()`는 동기이고 번들 로드는 비동기다. 그 사이에 탭을 떠나면 `dispose()`가
 * 아직 아무것도 없어 조용히 반환하고, 이어서 import가 재개해 **분리된 DOM에 렌더러를
 * 만든다** — 취소할 손잡이가 없는 고아다. `views/world.js`가 겪고 기록해 둔 그 버그라
 * 같은 방어를 그대로 쓴다.
 */

import { el, clear } from "../dom.js";
import { store } from "../store.js";

const HINT = "font-size:12px; color:var(--muted); line-height:1.6;";
const BUNDLE = "/world/build/world.js";

let live = null;

export function dispose() {
  if (live == null) return;
  const handle = live.handle;
  live = null; // 진행 중인 import가 스스로 물러나도록 먼저 끊는다
  handle?.dispose?.();
}

export function render() {
  dispose();
  const root = el("section", { class: "panel" },
    el("h2", {}, "가상환경"),
    el("p", { class: "hint", style: HINT }, "불러오는 중…"));

  const session = {};
  live = { session, handle: null };

  // **두 인자 형태를 쓴다.** `.then(f).catch(g)`로 쓰면 g가 로드 실패와 마운트 실패를
  // 같이 받아, 멀쩡한 번들을 두고 "빌드를 돌리십시오"라고 잘못 안내하게 된다.
  import(BUNDLE).then(
    (mod) => {
      if (live?.session !== session) return; // 떠났다 — 고아를 만들지 않는다
      try {
        clear(root);
        live.handle = mod.mount(root, {
          store,
          resultId: store.get("simResult")?.id ?? null,
        });
      } catch (e) {
        fail(root, `화면을 세우지 못했습니다 — ${e?.message ?? e}`);
      }
    },
    (e) => {
      if (live?.session !== session) return;
      fail(root, `번들을 불러오지 못했습니다 — ${e?.message ?? e}. `
        + "빌드가 없으면 web/world에서 `npm run build`를 돌리십시오.");
    },
  );

  return root;
}

function fail(root, message) {
  clear(root).append(
    el("h2", {}, "가상환경"),
    el("p", { class: "hint", style: HINT }, message));
}
