/** 구조도 재생 오버레이 — 마지막 시뮬을 최상위 블록도 위에서 재생한다.

블록마다 그 시각의 실제 신호값을 띄우고, α 리미터가 물리는 순간 그 블록을 붉게
점멸시킨다. 구조도가 "무엇이 어떻게 연결됐나"(지도)에 더해 "지금 무슨 값이
흐르나"(계기판)를 함께 말하게 하는 것이 목적.

- 무엇을 어디에 띄울지는 lib/wiresignals.js가 정본 (블록 id ↔ SVG data-sig)
- 재생 진행 계산은 lib/playback.js (경과 벽시계 기준 — stride 무관 배속 정확)
- 표시 스타일은 여기서 SVG 속성으로 준다: app.css는 병행 세션 미커밋 상태라
  건드리지 않는다 (지도 편집기 4dfaaeb와 같은 회피)

계측되지 않은 신호는 "—"로 나온다. 리미터 미장착 형상에서 θ가 0으로 보이면
"명령이 0으로 떨어졌다"와 구분되지 않기 때문 (엔진이 NaN으로 채우고 여기서 구분).
*/

import { api, errorText } from "../api.js";
import { clear, el } from "../dom.js";
import { dtOf, indexAt } from "../lib/playback.js";
import { strideFor } from "../lib/replay.js";
import { WIRE_SIGNALS, wireText } from "../lib/wiresignals.js";
import { store } from "../store.js";

const FRAME_MS = 40; // 25 fps — SVG 텍스트 갱신 8개라 여유롭다
const BLINK_MS = 220; // 리미터 점멸 주기
const VAL_FILL = "#0071e3";
const VAL_FILL_OFF = "#aeaeb2";

const reduceMotion = () =>
  typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

/** 구조도 SVG에 재생을 붙인다 — {root: 컨트롤 줄, dispose}. */
export function createTopReplay({ svgRoot }) {
  const slots = new Map(); // 블록 id → <text data-sig>
  for (const node of svgRoot.querySelectorAll("[data-sig]")) {
    slots.set(node.dataset.sig, node);
    // 표시 스타일은 여기서 (app.css 비접촉). mono 폭이라 값이 흔들려도 자리가 안 튄다
    node.setAttribute("text-anchor", "middle");
    node.setAttribute("font-size", "11");
    node.setAttribute("font-family", "ui-monospace, SFMono-Regular, Menlo, monospace");
    node.setAttribute("fill", VAL_FILL_OFF);
  }
  const limiterBody = svgRoot.querySelector('[data-block="limiter"] .body');
  const limiterBase = limiterBody?.getAttribute("stroke") ?? null;

  const status = el("span", { class: "hint" });
  const readout = el("span", { class: "progress-label" });
  const playBtn = el("button", { disabled: true }, "▶ 재생");
  const speedSel = el("select", { "aria-label": "재생 배속" },
    ...[1, 2, 5, 10, 20].map((x) =>
      el("option", { value: String(x), selected: x === 5 }, `${x}×`)));
  const slider = el("input", {
    type: "range", min: "0", max: "0", value: "0",
    style: "width: 280px", "aria-label": "재생 시각 커서", disabled: true,
  });

  let body = null; // 재생 데이터
  let dtSample = 0;
  let timer = null;
  let blinkOn = false;
  let fromIdx = 0;
  let fromWall = 0;

  const paintSlots = (i) => {
    for (const [id, node] of slots) {
      const txt = body ? wireText(WIRE_SIGNALS[id], body.signals, i) : "";
      node.textContent = txt;
      // 값이 하나라도 붙으면 활성 색 — 전부 미계측이면 회색으로 남긴다
      node.setAttribute("fill", txt && !/^(—|— · )*—$/.test(txt) ? VAL_FILL : VAL_FILL_OFF);
    }
  };

  const paintLimiter = (i) => {
    if (!limiterBody) return;
    const act = body?.signals?.limiter_active;
    const on = Array.isArray(act) && !!act[i];
    // 점멸은 타이머가 아니라 프레임에서 토글 — 재생이 멈추면 점멸도 멈춘다.
    // 모션 감축 설정에서는 깜박이지 않고 붉게 고정 (정보는 유지, 자극만 제거)
    const show = on && (reduceMotion() || !timer || blinkOn);
    limiterBody.setAttribute("stroke", show ? "#ff3b30" : (limiterBase ?? "#c7c7cc"));
    limiterBody.setAttribute("stroke-width", show ? "2.6" : "1");
  };

  const update = () => {
    const i = Number(slider.value);
    paintSlots(i);
    paintLimiter(i);
    if (body) {
      const flag = body.signals?.limiter_active?.[i] ? " · ⚠ α 리미터 작동" : "";
      readout.textContent = `t=${(body.t[i] ?? 0).toFixed(1)}s`
        + ` · ${body.signals?.mode?.[i] ?? "—"}${flag}`;
    }
  };

  const stop = () => {
    if (timer) clearInterval(timer);
    timer = null;
    playBtn.textContent = "▶ 재생";
    update(); // 점멸 상태를 고정 표시로 되돌린다
  };
  const anchor = () => { fromIdx = Number(slider.value); fromWall = performance.now(); };
  const start = () => {
    if (!body || dtSample <= 0) return;
    if (Number(slider.value) >= body.t.length - 1) slider.value = "0";
    anchor();
    let frame = 0;
    timer = setInterval(() => {
      blinkOn = (frame++ % Math.max(1, Math.round(BLINK_MS / FRAME_MS))) === 0
        ? !blinkOn : blinkOn;
      const next = indexAt({
        fromIdx, fromWall, now: performance.now(),
        speed: Number(speedSel.value), dtSample, len: body.t.length,
      });
      slider.value = String(next);
      update();
      if (next >= body.t.length - 1) stop();
    }, FRAME_MS);
    playBtn.textContent = "⏸ 일시정지";
  };

  playBtn.addEventListener("click", () => (timer ? stop() : start()));
  speedSel.addEventListener("change", () => { if (timer) anchor(); });
  slider.addEventListener("input", () => { if (timer) stop(); else update(); });

  const load = async () => {
    const last = store.get("simResult");
    if (!last?.id) {
      clear(status).append(
        "재생할 시뮬 결과가 없습니다 — ",
        el("a", { href: "#sim" }, "시뮬레이션 탭"),
        "에서 한 번 실행하면 여기서 재생됩니다.");
      return;
    }
    try {
      status.textContent = "결과 불러오는 중…";
      const meta = await api.get(`/results/${last.id}`).catch(() => null);
      const stride = strideFor(meta?.t?.length || 1);
      body = await api.get(`/sim/${last.id}/replay?stride=${stride}`);
      dtSample = dtOf(body.t);
      slider.max = String(Math.max(0, body.t.length - 1));
      slider.disabled = false;
      playBtn.disabled = dtSample <= 0;
      status.textContent = `마지막 시뮬 ${last.id} · ${body.t.length}표본`
        + ` · 끝 t=${(body.t[body.t.length - 1] ?? 0).toFixed(0)}s`;
      update();
    } catch (e) {
      clear(status).append(el("span", { class: "error-box" }, errorText(e)));
    }
  };
  load();

  return {
    root: el("div", { class: "row", style: "margin: 4px 0 10px" },
      playBtn, speedSel, slider, readout, status),
    dispose: () => { if (timer) clearInterval(timer); timer = null; },
  };
}
