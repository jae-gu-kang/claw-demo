/** 로그인 게이트 — 부팅 오버레이 + 헤더 세션 알약 (탭이 아니다: ask/tour 같은 body 크롬).

세션 모드(/api/auth/me → mode:"session")에서 미인증이면 앱 대신 이 오버레이가
선다: 최상위 블록도(TOP_SVG)의 블록들이 **해체되어 둥둥 떠다니다가**, 로그인이
되면 조립 순서(뒷줄 → CHAIN → 항법 = DOM 등장 순서)대로 **착착 제자리에 꽂힌다**.
조립이 끝나면 오버레이가 걷히고 #blocks — 방금 조립된 그 보드 — 로 들어간다.

연출 수치(흩뿌리기·스태거)는 lib/logingate.js (node --test 페어). 여기는 조립만.

지켜야 하는 것 (계획서·diagram.js 주석):
- TOP_SVG는 **불변** — 클론 DOM에 클래스·CSS 변수만 얹는다 (replayoverlay.js 선례).
- transform은 .blk 안 .lift에만. 게이트는 pointer-events:none이라 히트 진동
  문제 자체가 없지만, 스코프가 새면 blocks 탭이 다친다 — 규칙을 같게 유지.
- blocks 탭과 이 오버레이의 TOP_SVG가 **동시에 DOM에 있으면 안 된다**
  (defs id bd-arr 등 4개 충돌) — 재게이트 시 #view를 먼저 비운다.
*/

import { api } from "../api.js";
import { clear, el } from "../dom.js";
import { loginFailText, needsGate, scatterPlan, snapDelays } from "../lib/logingate.js";
import { TOP_SVG, fromMarkup } from "./diagram.js";

let me = null;      // 마지막 /api/auth/me 응답 — 세션 알약·#admin 라우트 판정이 읽는다
let overlay = null; // 떠 있는 게이트 (재게이트 중복 방지)

export function currentUser() {
  return me?.user ?? null;
}

const reduceMotion = () =>
  window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;

/** 부팅 게이트 — main.js가 라우팅 전에 await 한다. 세션 모드 미인증이면
로그인(과 조립 연출)이 끝나야 resolve. me를 못 읽어도 부팅은 막지 않는다 —
이후 첫 401이 claw:auth-required로 게이트를 다시 세운다 (api.js). */
export async function gate() {
  try {
    me = await api.get("/auth/me");
  } catch {
    me = null;
  }
  window.addEventListener("claw:auth-required", regate);
  if (!needsGate(me)) return;
  await new Promise((resolve) => show(resolve, { boot: true }));
}

/** 세션 만료·거절 뒤의 401 — 화면을 비우고(defs id 충돌 방지) 게이트를 다시 세운다.
재로그인이 끝나면 hashchange 재발화로 현재 탭을 다시 그린다 (main.js route). */
function regate() {
  if (overlay) return; // 이미 서 있다 — 401이 연달아 와도 한 장
  me = me && { ...me, user: null };
  clear(document.getElementById("view"));
  show(() => {
    mountSessionBox();
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  }, { boot: false });
}

// ── 오버레이 조립 ────────────────────────────────────────────────────────

function show(done, { boot }) {
  const svg = fromMarkup(TOP_SVG);
  svg.setAttribute("aria-hidden", "true"); // 연출 전용 — 블록 role/label 낭독 불필요
  const lifts = [...svg.querySelectorAll(".blk .lift")];
  const still = reduceMotion();
  if (!still) {
    // CSS 변수만 주입 — 흩어진 위치·둥둥 위상은 @keyframes login-float가 소비
    scatterPlan(lifts.length).forEach((p, i) => {
      const s = lifts[i].style;
      s.setProperty("--sx", `${p.dx.toFixed(1)}px`);
      s.setProperty("--sy", `${p.dy.toFixed(1)}px`);
      s.setProperty("--srot", `${p.rot.toFixed(1)}deg`);
      s.setProperty("--fx", `${p.fx.toFixed(1)}px`);
      s.setProperty("--fy", `${p.fy.toFixed(1)}px`);
      s.setProperty("--fdur", `${p.dur.toFixed(2)}s`);
      s.setProperty("--fdel", `${p.delay.toFixed(2)}s`);
    });
  }

  const msg = el("p", { class: "login-msg" });
  const user = el("input", {
    class: "login-user", name: "username", autocomplete: "username",
    placeholder: "아이디", required: true, maxlength: 64,
  });
  const pass = el("input", {
    type: "password", name: "password", autocomplete: "current-password",
    placeholder: "비밀번호", required: true,
  });
  const submit = el("button", { class: "primary", type: "submit" }, "로그인");
  const alt = el("button", { class: "alt", type: "button" }, "계정이 없습니까? 가입 신청");

  let mode = "login"; // "login" | "signup"
  const setMode = (m) => {
    mode = m;
    submit.textContent = m === "login" ? "로그인" : "가입 신청";
    alt.textContent = m === "login" ? "계정이 없습니까? 가입 신청" : "돌아가기 — 로그인";
    pass.autocomplete = m === "login" ? "current-password" : "new-password";
    say("", "");
    if (m === "signup") say("아이디는 영문·숫자·_- · 비밀번호는 4자 이상 · 관리자 승인 후 로그인됩니다", "");
  };
  const say = (text, cls) => {
    msg.textContent = text;
    msg.className = `login-msg${cls ? ` ${cls}` : ""}`;
  };
  alt.addEventListener("click", () => setMode(mode === "login" ? "signup" : "login"));

  const form = el("form", {
    onsubmit: async (e) => {
      e.preventDefault();
      submit.disabled = true;
      try {
        if (mode === "signup") {
          await api.post("/auth/signup", { username: user.value.trim(), password: pass.value });
          setMode("login");
          say("신청 완료 — 관리자 승인 후 로그인할 수 있습니다", "ok");
        } else {
          const u = await api.post("/auth/login",
            { username: user.value.trim(), password: pass.value });
          me = { mode: "session", user: { ...u, status: "active" } };
          assemble(svg, lifts, () => {
            if (boot) location.hash = "#blocks"; // 방금 조립된 그 보드로 들어간다
            done();
          });
          return; // 성공 — 버튼은 조립 동안 잠긴 채 둔다
        }
      } catch (err) {
        say(loginFailText(err), "bad");
      }
      submit.disabled = false;
    },
  }, user, pass, submit);

  overlay = el("div", { class: `login-gate bd${still ? "" : " scattered"}` },
    el("div", { class: "login-board canvas-wrap top", "aria-hidden": "true" }, svg),
    el("div", { class: "login-card" },
      el("h1", {}, "CLAW", el("span", { class: "sub" }, "비행제어법칙 설계·해석·시뮬레이션")),
      form, msg,
      el("div", { class: "login-alt" }, alt),
    ),
  );
  document.body.append(overlay);
  user.focus();
}

/** 착— 조립: 둥둥(애니메이션)의 현재 자세를 인라인 행렬로 얼리고, 애니메이션을
끊은 뒤 스태거 지연과 함께 행렬을 지운다 → transform이 원위치(none)로 전이.
"애니메이션 제거 직후 전이 시작값"은 브라우저마다 미덥지 않아 얼리는 쪽이 확실하다. */
function assemble(svg, lifts, after) {
  const gate = overlay;
  const finish = () => {
    if (!gate.classList.contains("done")) {
      gate.classList.add("done"); // opacity 페이드 (app.css)
      setTimeout(() => {
        gate.remove();
        overlay = null;
        after();
      }, 500);
    }
  };
  if (reduceMotion() || lifts.length === 0) {
    finish();
    return;
  }
  for (const g of lifts) {
    const m = getComputedStyle(g).transform;
    if (m && m !== "none") g.style.transform = m; // 현재 자세 고정
  }
  gate.classList.remove("scattered"); // 둥둥 종료 — 판·배선 페이드인도 여기 걸려 있다
  void gate.offsetWidth; // 강제 리플로 — 고정 자세가 전이 시작값으로 굳는다
  const delays = snapDelays(lifts.length);
  lifts.forEach((g, i) => {
    g.style.transitionDelay = `${delays[i]}ms`;
    g.style.transform = ""; // → none으로 전이 (오버슛 곡선은 app.css)
  });
  const last = lifts[lifts.length - 1];
  last.addEventListener("transitionend", finish, { once: true });
  setTimeout(finish, delays[delays.length - 1] + 1600); // transitionend 유실 대비
}

// ── 헤더 세션 알약 ──────────────────────────────────────────────────────

/** 세션 모드일 때만 그린다 — 사용자명 · [관리](admin만) · 로그아웃. */
export function mountSessionBox() {
  const box = document.getElementById("session-box");
  if (!box) return;
  clear(box);
  if (me?.mode !== "session" || !me.user) {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  box.append(
    el("span", { class: "who" }, me.user.username),
    // 관리자 화면은 파이프라인 탭이 아니다 — data-view 없이 여기서만 진입
    // (blocks.test.js nav 가드·02 §8 단계 대조와 무관해야 한다)
    me.user.role === "admin" ? el("a", { href: "#admin" }, "관리") : null,
    el("button", {
      class: "logout",
      onclick: async () => {
        try {
          await api.post("/auth/logout");
        } catch { /* 이미 만료됐어도 새로 선다 */ }
        location.hash = ""; // 재로그인 후 기본 탭(#blocks)부터
        location.reload(); // 프로세스 상태 전부 초기화 — 게이트가 다시 선다
      },
    }, "로그아웃"),
  );
}
