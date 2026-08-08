/** 진입점 — 해시 라우팅 + 헬스 표시. 뷰는 views/*.js가 담당 (조립 전용, 얇게). */

import { api } from "./api.js";
import { clear } from "./dom.js";
import * as gains from "./views/gains.js";
import * as margins from "./views/margins.js";
import * as results from "./views/results.js";
import * as sim from "./views/sim.js";
import * as trim from "./views/trim.js";

const VIEWS = { trim, margins, gains, sim, results };

function route() {
  const name = location.hash.slice(1) || "trim";
  const view = VIEWS[name] ?? VIEWS.trim;
  for (const a of document.querySelectorAll("#nav a")) {
    a.classList.toggle("active", a.dataset.view === (VIEWS[name] ? name : "trim"));
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
