/** 3D 궤적 뷰 — 축측투영 캔버스 + 드래그 회전 (02 §8 5단계 재생).

수치(정규화·투영·화면 맞춤)는 lib/plot3d.js — 여기는 캔버스 그리기와 포인터
상태만. 캔버스는 재생성 금지: setPointerCapture가 요소에 붙으므로 clearRect 후
재그리기 (views/wpmap.js와 같은 규약).

깊이 단서는 셋: 상자 와이어프레임(뒤 모서리는 흐리게), 바닥면에 떨어뜨린 궤적
그림자, 현재 시각 위치에서 바닥까지 내리는 수선. 원근이 없는 직교투영이라
그림자 없이는 높이를 읽기 어렵다.
*/

import { el } from "../dom.js";
import { wpAlt } from "../lib/plot.js";
import { bounds3d, projector3d } from "../lib/plot3d.js";
import { makeCanvas } from "./plots.js";

const DRAG_PX = 3; // 클릭↔드래그 판별 [px]
const EL_MIN = 0.05; // 고각 하한 [rad] — 0이면 바닥면이 선으로 붕괴해 방향을 잃는다
const EL_MAX = Math.PI / 2;
const ROT_PER_PX = 0.012; // 드래그 1 px당 회전량 [rad]

/** 3D 궤적 뷰 — {root, refresh(markerIdx)}. viewRef로 회전 상태를 바깥이 보관한다. */
export function createTrack3d({
  getSignals, // () => {pn, pe, h}
  getWaypoints, // () => [[n, e], ...] 또는 [[n, e, alt], ...]
  viewRef, // {view: {az, el} | null} — 탭 재진입·재렌더에도 시점 유지
  size = 320,
} = {}) {
  const { canvas, ctx } = makeCanvas(size, size);
  canvas.style.cursor = "grab";
  canvas.style.touchAction = "none"; // 드래그가 스크롤로 새지 않게
  canvas.tabIndex = 0;
  canvas.setAttribute("aria-label",
    "3D 궤적 (NED) — 끌어서 회전, 화살표 키로도 회전");
  const caption = el("div", { class: "hint" });
  let marker = null;
  let drag = null; // {x, y, az, el, moved}

  if (!viewRef.view) viewRef.view = { az: 0.6, el: 0.45 }; // 기본 3/4 시점

  const draw = () => {
    const sig = getSignals();
    const wps = getWaypoints() ?? [];
    const b = bounds3d(sig.pn, sig.pe, sig.h, wps);
    const p = projector3d(b, viewRef.view, { width: size, height: size, margin: 34 });
    ctx.clearRect(0, 0, size, size);

    // 상자 — 바닥면(진하게)과 수직 기둥. 천장은 그리지 않는다 (상자 안에 갇힌
    // 그림처럼 보여 궤적을 가린다)
    const c = p.corners;
    const floor = [c[0], c[1], c[3], c[2]]; // 시계 순서로 재배열 (인덱스는 x 먼저)
    ctx.strokeStyle = "#d2d2d7";
    ctx.lineWidth = 1;
    ctx.beginPath();
    floor.forEach((q, i) => (i ? ctx.lineTo(q.x, q.y) : ctx.moveTo(q.x, q.y)));
    ctx.closePath();
    ctx.stroke();
    ctx.strokeStyle = "#e8e8ed";
    ctx.beginPath();
    for (let i = 0; i < 4; i += 1) {
      ctx.moveTo(c[i].x, c[i].y);
      ctx.lineTo(c[i + 4].x, c[i + 4].y);
    }
    ctx.stroke();

    // 웨이포인트 — 바닥면 위 점, **고도가 있으면 그 높이에 점 + 수선**.
    // 원근 없는 직교투영이라 수선이 없으면 높이가 안 읽힌다(현재 시각 표식과 같은
    // 이유). 고도 없는 열은 종전대로 바닥 점뿐 — 없는 정보를 지어내지 않는다
    for (const w of wps) {
      const [n, e] = w;
      if (!Number.isFinite(n) || !Number.isFinite(e)) continue;
      const alt = wpAlt(w); // 판정은 lib 정본 — 여기 사본을 두면 조용히 갈린다
      const floorQ = p.toPxFloor(n, e);
      if (alt == null) {
        ctx.fillStyle = "#ff9500";
        ctx.beginPath();
        ctx.arc(floorQ.x, floorQ.y, 3.5, 0, 2 * Math.PI);
        ctx.fill();
        continue;
      }
      const upQ = p.toPx(n, e, alt);
      ctx.strokeStyle = "#ffcc80";
      ctx.setLineDash([2, 3]);
      ctx.beginPath();
      ctx.moveTo(upQ.x, upQ.y);
      ctx.lineTo(floorQ.x, floorQ.y);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = "#ffcc80"; // 그림자는 옅게 — 계획 고도의 점이 주인공
      ctx.beginPath();
      ctx.arc(floorQ.x, floorQ.y, 2.5, 0, 2 * Math.PI);
      ctx.fill();
      ctx.fillStyle = "#ff9500";
      ctx.beginPath();
      ctx.arc(upQ.x, upQ.y, 3.5, 0, 2 * Math.PI);
      ctx.fill();
    }

    // 바닥 그림자 (지상 궤적) — 높이를 읽는 기준선
    const poly = (at, style, width) => {
      ctx.strokeStyle = style;
      ctx.lineWidth = width;
      ctx.beginPath();
      let started = false;
      for (let i = 0; i < sig.pn.length; i += 1) {
        const n = sig.pn[i], e = sig.pe[i], h = sig.h[i];
        if (!Number.isFinite(n) || !Number.isFinite(e) || !Number.isFinite(h)) {
          started = false; // 결측은 잇지 않고 끊는다
          continue;
        }
        const q = at(n, e, h);
        if (!started) { ctx.moveTo(q.x, q.y); started = true; } else ctx.lineTo(q.x, q.y);
      }
      ctx.stroke();
    };
    poly((n, e) => p.toPxFloor(n, e), "#c7c7cc", 1.2);
    poly((n, e, h) => p.toPx(n, e, h), "#007aff", 1.6);

    // 시작점 + 현재 시각 — 수선을 내려 그림자와 이어야 높이가 읽힌다
    const dot = (q, color, r) => {
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(q.x, q.y, r, 0, 2 * Math.PI);
      ctx.fill();
    };
    if (Number.isFinite(sig.pn[0]) && Number.isFinite(sig.h[0])) {
      dot(p.toPx(sig.pn[0], sig.pe[0], sig.h[0]), "#34c759", 4);
    }
    const i = marker;
    if (i != null && i < sig.pn.length
      && Number.isFinite(sig.pn[i]) && Number.isFinite(sig.h[i])) {
      const up = p.toPx(sig.pn[i], sig.pe[i], sig.h[i]);
      const down = p.toPxFloor(sig.pn[i], sig.pe[i]);
      ctx.strokeStyle = "#ff3b30";
      ctx.setLineDash([2, 3]);
      ctx.beginPath();
      ctx.moveTo(up.x, up.y);
      ctx.lineTo(down.x, down.y);
      ctx.stroke();
      ctx.setLineDash([]);
      dot(down, "#ffb3ae", 3);
      dot(up, "#ff3b30", 5);
    }

    // 축 안내 — 바닥면 모서리에 N·E 방향을 적는다 (회전해도 어디가 북쪽인지)
    ctx.fillStyle = "#86868b";
    ctx.fillText("N", (c[2].x + c[3].x) / 2 - 4, (c[2].y + c[3].y) / 2 - 3);
    ctx.fillText("E", (c[1].x + c[3].x) / 2 + 4, (c[1].y + c[3].y) / 2 + 3);
    ctx.fillText("h", c[4].x - 12, c[4].y - 4);

    const deg = (r) => Math.round((r * 180) / Math.PI);
    caption.textContent = `끌어서 회전 · 방위 ${deg(viewRef.view.az)}° 고각 `
      + `${deg(viewRef.view.el)}° · 연직 과장 ×${p.vExag.toFixed(1)} (경사각 판독 불가)`;
  };

  canvas.addEventListener("pointerdown", (ev) => {
    canvas.setPointerCapture(ev.pointerId);
    drag = { x: ev.clientX, y: ev.clientY, az: viewRef.view.az, el: viewRef.view.el };
    canvas.style.cursor = "grabbing";
  });
  canvas.addEventListener("pointermove", (ev) => {
    if (!drag) return;
    const dx = ev.clientX - drag.x;
    const dy = ev.clientY - drag.y;
    if (Math.abs(dx) < DRAG_PX && Math.abs(dy) < DRAG_PX) return;
    viewRef.view = {
      az: drag.az + dx * ROT_PER_PX,
      // 위로 끌면 위에서 내려다보게 — 고각은 붕괴·뒤집힘 구간을 잘라낸다
      el: Math.min(EL_MAX, Math.max(EL_MIN, drag.el + dy * ROT_PER_PX)),
    };
    draw();
  });
  const endDrag = (ev) => {
    if (!drag) return;
    canvas.releasePointerCapture?.(ev.pointerId);
    drag = null;
    canvas.style.cursor = "grab";
  };
  canvas.addEventListener("pointerup", endDrag);
  canvas.addEventListener("pointercancel", endDrag);
  canvas.addEventListener("keydown", (ev) => {
    const step = 0.1;
    const { az, el: e0 } = viewRef.view;
    if (ev.key === "ArrowLeft") viewRef.view = { az: az - step, el: e0 };
    else if (ev.key === "ArrowRight") viewRef.view = { az: az + step, el: e0 };
    else if (ev.key === "ArrowUp") viewRef.view = { az, el: Math.min(EL_MAX, e0 + step) };
    else if (ev.key === "ArrowDown") viewRef.view = { az, el: Math.max(EL_MIN, e0 - step) };
    else return;
    ev.preventDefault();
    draw();
  });

  return {
    root: el("div", { style: "display:flex; flex-direction:column; gap:4px;" },
      canvas, caption),
    refresh(markerIdx = null) {
      marker = markerIdx;
      draw();
    },
  };
}
