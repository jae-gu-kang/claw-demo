/** NED 평면 웨이포인트 지도 편집기 — 캔버스 1개 유지·내용 재그리기 (02 §기능 지도 편집).

수치(사상·역사상·줌·팬·히트테스트)는 lib/wpmap.js — 여기는 캔버스 그리기와
포인터 상태 기계만. 캔버스는 재생성 금지: setPointerCapture·wheel 리스너가
요소에 붙어 있으므로 clearRect 후 재그리기. 접근성 기준선은 웨이포인트 표가
전담(표로 모든 편집 가능) — 캔버스는 Delete 키·툴바 버튼 보조.
*/

import { el } from "../dom.js";
import {
  fitView, fmtMeters, hitTest, isDrag, makeProjection, moveWaypoint,
  rowsToPoints, toCanvasXY, zoomAt, panBy,
} from "../lib/wpmap.js";
import { niceTicks } from "../lib/plot.js";
import { makeCanvas } from "./plots.js";

const HIT_PX = 10; // WP 히트 반경 [논리 px]

export function createWpMap({
  getRows, // () => wpRows — 문자열 행 참조 (지도가 직접 변이)
  getAcceptRadius, // () => number [m]
  getTrack, // () => {pn, pe} | null — 최근 시뮬 궤적
  onRowsChanged, // () => void — 추가·삭제·이동·재배열 후 표 재렌더
  viewRef, // {view: {cN,cE,span}|null} — 호출측 스코프 홀더 (탭 재진입 시 줌/팬 유지)
  width = 380, height = 380,
} = {}) {
  const { canvas, ctx } = makeCanvas(width, height);
  canvas.classList.add("wpmap");
  canvas.tabIndex = 0;
  canvas.setAttribute("aria-label", "웨이포인트 지도 편집기 — 표로도 동일 편집 가능");
  // 스타일은 JS로 — app.css는 병행 세션 작업 중이라 건드리지 않음 (커밋 오염 방지)
  canvas.style.touchAction = "none";
  canvas.style.cursor = "crosshair";

  let selected = -1; // 선택 WP 인덱스 (-1 = 없음)

  const fitAll = () => {
    const pts = rowsToPoints(getRows()).filter((p) => p.ok).map((p) => [p.n, p.e]);
    viewRef.view = fitView([...pts, [0, 0]]); // 기체 시작점(원점) 포함, 궤적은 제외
  };
  const view = () => {
    if (!viewRef.view) fitAll();
    return viewRef.view;
  };

  function redraw() {
    const { toPx, kScale } = makeProjection(view(), width, height);
    const m = 42;
    ctx.clearRect(0, 0, width, height); // makeCanvas가 dpr 스케일 완료 — 논리 px로 충분
    const { cN, cE, span } = view();

    // 격자 + 축 눈금 (trackCanvas와 동일 스타일)
    ctx.strokeStyle = "#e5e5ea";
    ctx.beginPath();
    for (const tk of niceTicks(cE - span / 2, cE + span / 2, 5)) {
      const x = toPx(cN, tk).x;
      if (x < m || x > width - m) continue;
      ctx.moveTo(x, m);
      ctx.lineTo(x, height - m);
      ctx.fillStyle = "#86868b";
      ctx.fillText(`${Math.round(tk)}`, x - 10, height - m + 14);
    }
    for (const tk of niceTicks(cN - span / 2, cN + span / 2, 5)) {
      const y = toPx(tk, cE).y;
      if (y < m || y > height - m) continue;
      ctx.moveTo(m, y);
      ctx.lineTo(width - m, y);
      ctx.fillStyle = "#86868b";
      ctx.fillText(`${Math.round(tk)}`, 2, y + 3);
    }
    ctx.stroke();
    ctx.fillStyle = "#86868b";
    ctx.fillText("E [m] →  (북쪽 위)", width / 2 - 40, height - 6);

    // 최근 시뮬 궤적 오버레이 (옅은 파랑 — 편집 대상과 구분)
    const track = getTrack?.();
    if (track) {
      ctx.strokeStyle = "rgba(0, 122, 255, .45)";
      ctx.lineWidth = 1.4;
      ctx.beginPath();
      let started = false;
      track.pn.forEach((n, i) => {
        const e = track.pe[i];
        if (typeof n !== "number" || typeof e !== "number") { started = false; return; }
        const { x, y } = toPx(n, e);
        if (!started) { ctx.moveTo(x, y); started = true; }
        else ctx.lineTo(x, y);
      });
      ctx.stroke();
    }

    const pts = rowsToPoints(getRows());
    const okPts = pts.filter((p) => p.ok);

    // 방문 순서 폴리라인 (시작점 → WP들, 주황 점선)
    ctx.strokeStyle = "rgba(255, 149, 0, .55)";
    ctx.lineWidth = 1.2;
    ctx.setLineDash([5, 4]);
    ctx.beginPath();
    const o = toPx(0, 0);
    ctx.moveTo(o.x, o.y);
    for (const p of okPts) {
      const { x, y } = toPx(p.n, p.e);
      ctx.lineTo(x, y);
    }
    ctx.stroke();
    ctx.setLineDash([]);

    // 도달반경 원 + WP 점 + 순서 배지
    const accept = getAcceptRadius?.() || 0;
    pts.forEach((p, i) => {
      if (!p.ok) return;
      const { x, y } = toPx(p.n, p.e);
      ctx.strokeStyle = "#ff9500";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.arc(x, y, Math.max(3, accept * kScale), 0, 2 * Math.PI);
      ctx.stroke();
      ctx.fillStyle = "#ff9500";
      ctx.beginPath();
      ctx.arc(x, y, 4, 0, 2 * Math.PI);
      ctx.fill();
      if (i === selected) {
        ctx.strokeStyle = "#007aff";
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(x, y, 7.5, 0, 2 * Math.PI);
        ctx.stroke();
      }
      ctx.fillStyle = "#1d1d1f";
      ctx.fillText(String(i + 1), x + 7, y - 7);
    });

    // 시작점 (초록)
    ctx.fillStyle = "#34c759";
    ctx.beginPath();
    ctx.arc(o.x, o.y, 4, 0, 2 * Math.PI);
    ctx.fill();

    syncToolbar();
  }

  // ── 포인터 상태 기계: idle → pending → (dragWp | pan) ─────────────────
  // 드래그 중에는 지도만 재그리기 — 표 재렌더(onRowsChanged)는 pointerup 1회
  // (input 포커스 파괴·성능). pan은 시작 뷰 기준 총 델타 — 누적 드리프트 없음.
  let gesture = null; // {x0, y0, wpIdx, view0, kScale0, moved}

  const eventXY = (ev) =>
    toCanvasXY(ev.clientX, ev.clientY, canvas.getBoundingClientRect(), width, height);

  canvas.addEventListener("pointerdown", (ev) => {
    if (ev.button !== 0) return; // 우클릭은 contextmenu 경로
    const { x, y } = eventXY(ev);
    const proj = makeProjection(view(), width, height);
    gesture = {
      x0: x, y0: y,
      wpIdx: hitTest(rowsToPoints(getRows()), x, y, proj.toPx, { radiusPx: HIT_PX }),
      view0: { ...view() }, kScale0: proj.kScale, moved: false,
    };
    canvas.setPointerCapture(ev.pointerId);
  });

  canvas.addEventListener("pointermove", (ev) => {
    if (!gesture) return;
    const { x, y } = eventXY(ev);
    const dx = x - gesture.x0, dy = y - gesture.y0;
    if (!gesture.moved && !isDrag(dx, dy)) return;
    gesture.moved = true;
    if (gesture.wpIdx >= 0) {
      // WP 드래그 — 현재 뷰 기준 역사상으로 좌표 갱신
      const { toNed } = makeProjection(view(), width, height);
      const ned = toNed(x, y);
      const r = getRows()[gesture.wpIdx];
      r.n = fmtMeters(ned.n);
      r.e = fmtMeters(ned.e);
      selected = gesture.wpIdx;
    } else {
      viewRef.view = panBy(gesture.view0, dx, dy, gesture.kScale0);
    }
    redraw();
  });

  const endGesture = (ev) => {
    if (!gesture) return;
    const g = gesture;
    gesture = null;
    if (canvas.hasPointerCapture?.(ev.pointerId)) canvas.releasePointerCapture(ev.pointerId);
    if (ev.type === "pointercancel") { redraw(); return; }
    if (!g.moved) {
      if (g.wpIdx >= 0) {
        selected = g.wpIdx; // 클릭 = 선택
        redraw();
      } else {
        const { toNed } = makeProjection(view(), width, height);
        const p = eventXY(ev);
        const ned = toNed(p.x, p.y);
        getRows().push({ n: fmtMeters(ned.n), e: fmtMeters(ned.e) });
        selected = getRows().length - 1;
        onRowsChanged();
        redraw();
      }
    } else if (g.wpIdx >= 0) {
      onRowsChanged(); // 드래그 이동 완료 — 표 동기 1회
      redraw();
    }
  };
  canvas.addEventListener("pointerup", endGesture);
  canvas.addEventListener("pointercancel", endGesture);

  canvas.addEventListener("contextmenu", (ev) => {
    ev.preventDefault(); // macOS ctrl+클릭 포함 — 삭제 경로
    const { x, y } = eventXY(ev);
    const { toPx } = makeProjection(view(), width, height);
    const idx = hitTest(rowsToPoints(getRows()), x, y, toPx, { radiusPx: HIT_PX });
    if (idx >= 0) removeAt(idx);
  });

  canvas.addEventListener("wheel", (ev) => {
    ev.preventDefault();
    const { x, y } = eventXY(ev);
    const { toNed } = makeProjection(view(), width, height);
    viewRef.view = zoomAt(view(), ev.deltaY > 0 ? 1 / 1.2 : 1.2, toNed(x, y));
    redraw();
  }, { passive: false });

  canvas.addEventListener("keydown", (ev) => {
    if ((ev.key === "Delete" || ev.key === "Backspace") && selected >= 0) {
      ev.preventDefault();
      removeAt(selected);
    }
  });

  function removeAt(idx) {
    getRows().splice(idx, 1);
    selected = -1;
    onRowsChanged();
    redraw();
  }

  function reorder(delta) {
    if (selected < 0) return;
    if (moveWaypoint(getRows(), selected, selected + delta)) {
      selected += delta;
      onRowsChanged();
      redraw();
    }
  }

  // ── 툴바 ──────────────────────────────────────────────────────────────
  const btnFit = el("button", { onclick: () => { fitAll(); redraw(); } }, "전체 보기");
  const btnDel = el("button", { class: "danger", onclick: () => selected >= 0 && removeAt(selected) }, "삭제");
  const btnUp = el("button", { onclick: () => reorder(-1) }, "▲");
  const btnDown = el("button", { onclick: () => reorder(1) }, "▼");
  function syncToolbar() {
    const rows = getRows();
    btnDel.disabled = selected < 0;
    btnUp.disabled = selected <= 0;
    btnDown.disabled = selected < 0 || selected >= rows.length - 1;
  }

  const root = el("div", {},
    canvas,
    el("div", { class: "row", style: "margin-top: 6px" }, btnFit, btnDel, btnUp, btnDown),
    el("p", { class: "hint" },
      "클릭=추가 · 드래그=이동 · 우클릭=삭제 · 휠=줌 · 빈 곳 드래그=팬 · ▲▼=방문 순서"),
  );

  redraw();
  return {
    root,
    refresh: () => {
      if (selected >= getRows().length) selected = -1; // 표에서 행 삭제된 경우
      redraw();
    },
    fit: () => { fitAll(); redraw(); },
  };
}
