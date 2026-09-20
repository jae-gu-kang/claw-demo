/** 진입점 — 해시 라우팅 + 헬스 표시. 뷰는 views/*.js가 담당 (조립 전용, 얇게). */

import { api } from "./api.js";
import { clear } from "./dom.js";
// 전역 질문 위젯·가이드 투어 — 라우트 뷰가 아니다 (VIEWS 밖: blocks.test.js nav 가드와 무관)
import * as ask from "./views/ask.js";
import * as tour from "./views/tour.js";
// 로그인 게이트·관리자 — 둘 다 파이프라인 탭이 아니다 (VIEWS 밖). 게이트는 부팅
// 오버레이(body 크롬), 관리자는 헤더 세션 알약의 [관리]로만 여는 특례 라우트(#admin)
import * as login from "./views/login.js";
import * as admin from "./views/admin.js";
// 헤더 기체 선택기 — 라우트 뷰가 아니다. 기체 탭(aircraft)은 문서 편집, 이것은 선택
import * as profilepick from "./views/profilepick.js";
import { loadSelection, setSelection } from "./lib/profile.js";
import * as aircraft from "./views/aircraft.js";
import * as autocode from "./views/autocode.js";
import * as autodesign from "./views/autodesign.js";
import * as blocks from "./views/blocks.js";
import * as envelope from "./views/envelope.js";
import * as flow from "./views/flow.js";
import * as gains from "./views/gains.js";
import * as influence from "./views/influence.js";
import * as margins from "./views/margins.js";
import * as results from "./views/results.js";
import * as sim from "./views/sim.js";
import * as trim from "./views/trim.js";
import * as verify from "./views/verify.js";
import * as world from "./views/world.js";

// 블록도(블록 다이어그램 허브)가 진입점 — 블록 클릭으로 각 편집 화면 진입 (06 §1)
// 타면 사용은 탭이 아니다 — 설계 단계가 아니라 시뮬 런 하나를 다시 읽는 방법이라
// 시뮬레이션 탭의 패널로 들어갔다 (v0.54, views/duty.js 머리말)
// 나열 순서는 index.html nav와 **같아야 한다** — 순서가 업무 순서를 뜻하게 된
// 뒤로는(v0.66) 한쪽만 고치면 원문 둘이 다른 순서를 말한다. 드리프트 가드는
// lib/blocks.test.js가 두 원문을 나란히 읽어 대조한다 (집합이 아니라 배열로)
const VIEWS = {
  aircraft, flow, blocks, envelope, trim, gains, margins, autodesign, sim, world, influence,
  autocode, verify, results,
};

// 떠나는 뷰가 자원을 쥐고 있으면 반납시킨다. 지금은 3D 월드뿐인데, WebGL 컨텍스트는
// 브라우저당 개수 제한(보통 8~16개)이 있어 탭을 오갈 때마다 새로 만들면 곧 바닥난다.
// dispose를 내보내지 않는 뷰는 아무 일도 일어나지 않는다 (선택 규약).
let current = null;

function route() {
  const name = location.hash.slice(1) || "blocks";
  // #admin 특례 — VIEWS 리터럴에 넣지 않는다 (blocks.test.js가 VIEWS 순서 ==
  // 파이프라인을 못 박는다). 권한은 서버가 최종 판정하고(403), 여기서는 관리자가
  // 아니면 링크 자체가 없던 것처럼 블록도로 폴백만 한다
  const isAdmin = name === "admin" && login.currentUser()?.role === "admin";
  const view = isAdmin ? admin : (VIEWS[name] ?? VIEWS.blocks);
  if (current !== view) current?.dispose?.();
  current = view;
  for (const a of document.querySelectorAll("#nav a")) {
    a.classList.toggle("active",
      !isAdmin && a.dataset.view === (VIEWS[name] ? name : "blocks"));
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

// 부팅 게이트 — 세션 모드(서버 $CLAW_ADMIN_PASSWORD)면 로그인(블록도 해체→조립)이
// 끝나야 아래가 돈다. 라우팅·헬스·크롬이 게이트보다 먼저 API를 쏘면 401 이벤트가
// 게이트와 경합하므로 **전부 게이트 뒤**다 (top-level await — ES 모듈이라 가능)
await login.gate();
// 기체 선택은 첫 요청보다 먼저 읽는다 — 라우팅이 뷰를 그리자마자 계산 요청을 보낸다 (lib/profile.js)
setSelection(loadSelection(profilepick.browserStorage()));
window.addEventListener("hashchange", route);
route();
refreshHealth();
setInterval(refreshHealth, 5000);
profilepick.mount(); // 헤더 기체 선택기 — 선택이 서버에서 사라졌으면 예제로 되돌리고 사유를 말한다
ask.mount(); // 전역 질문 위젯 — 탭 전환(#view 교체)에 영향받지 않는 body 크롬
tour.mount(); // 가이드 투어 — 탭을 넘나들며 순서를 쥐어야 해서 같은 자리에 산다
login.mountSessionBox(); // 헤더 세션 알약 — 게이트가 알아낸 로그인 사용자를 그린다 (세션 모드만)
