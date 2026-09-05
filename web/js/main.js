/** 진입점 — 해시 라우팅 + 헬스 표시. 뷰는 views/*.js가 담당 (조립 전용, 얇게). */

import { api } from "./api.js";
import { clear } from "./dom.js";
import * as autocode from "./views/autocode.js";
import * as autodesign from "./views/autodesign.js";
import * as blocks from "./views/blocks.js";
import * as envelope from "./views/envelope.js";
import * as gains from "./views/gains.js";
import * as influence from "./views/influence.js";
import * as margins from "./views/margins.js";
import * as results from "./views/results.js";
import * as sim from "./views/sim.js";
import * as trim from "./views/trim.js";
import * as verify from "./views/verify.js";
import * as world from "./views/world.js";

// 블록도(블록 다이어그램 허브)가 진입점 — 블록 클릭으로 각 편집 화면 진입 (02 §4)
// 타면 사용은 탭이 아니다 — 설계 단계가 아니라 시뮬 런 하나를 다시 읽는 방법이라
// 시뮬레이션 탭의 서랍으로 들어갔다 (v0.54, views/duty.js 머리말)
const VIEWS = {
  blocks, envelope, trim, gains, margins, autodesign, sim, world, autocode,
  verify, influence, results,
};

// 떠나는 뷰가 자원을 쥐고 있으면 반납시킨다. 지금은 3D 월드뿐인데, WebGL 컨텍스트는
// 브라우저당 개수 제한(보통 8~16개)이 있어 탭을 오갈 때마다 새로 만들면 곧 바닥난다.
// dispose를 내보내지 않는 뷰는 아무 일도 일어나지 않는다 (선택 규약).
let current = null;

function route() {
  const name = location.hash.slice(1) || "blocks";
  const view = VIEWS[name] ?? VIEWS.blocks;
  if (current !== view) current?.dispose?.();
  current = view;
  for (const a of document.querySelectorAll("#nav a")) {
    a.classList.toggle("active", a.dataset.view === (VIEWS[name] ? name : "blocks"));
  }
  clear(document.getElementById("view")).append(view.render());
}

async function refreshHealth() {
  const box = document.getElementById("health");
  try {
    const h = await api.get("/health");
    box.textContent = `서버 정상 · 작업 ${h.jobs}건`;
    box.className = "health ok";
  } catch {
    box.textContent = "서버 연결 안 됨";
    box.className = "health bad";
  }
}

window.addEventListener("hashchange", route);
route();
refreshHealth();
setInterval(refreshHealth, 5000);
