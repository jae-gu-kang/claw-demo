/** 가상환경 — Vite/React 번들로 넘기는 얇은 어댑터.
 *
 * ## 내력
 *
 * 재설계(2026-09) 전에는 이 자리에 바닐라 뷰 + 반입 three가 있었고, 새 화면은 `#world2`
 * 임시 라우트로 나란히 돌았다. 기능 동등(지형·궤적·웨이포인트·재생·카메라 4종 + 캡션
 * 규약)에 이르러 이 어댑터가 `world.js`가 됐고, 옛 뷰(`world.js`·`worldrenderer.js`·
 * `renderer-three.js`)와 반입 three(`vendor/three/`, 2.0 MB)는 걷어냈다 — three는 이제
 * `web/world`의 npm devDependency이고 커밋된 빌드 산출물로만 반입된다. `lib/uavmesh.js`는
 * 은퇴했지만 남겨 둔다(GLB가 대체, 순수 함수 + 테스트라 유지비 0).
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
  // **루트에 `.panel`을 두지 않는다** — 번들이 자기 루트(`section.wv.tab-dark`)를
  // 그리고, 3D 세계는 카드 안이 아니라 페이지 위에 그대로 놓인다(블록도 보드·영향성
  // 그래프와 같은 규약). 로딩·실패 자리에만 카드를 씌우면 마운트 순간에 배경이
  // 밝→어둡으로 튀므로, 여기도 같은 다크 스코프를 미리 입혀 둔다.
  const root = el("div", { class: "tab-dark tab-page" },
    el("div", { class: "tab-top" }, el("h1", {}, "가상환경")),
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
    el("div", { class: "tab-top" }, el("h1", {}, "가상환경")),
    el("p", { class: "hint", style: HINT }, message));
}
