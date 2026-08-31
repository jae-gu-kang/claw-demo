/** NED 평면 웨이포인트 지도 편집기 — 캔버스 1개 유지·내용 재그리기 (02 §기능 지도 편집).

수치(사상·역사상·줌·팬·히트테스트)는 lib/wpmap.js — 여기는 캔버스 그리기와
포인터 상태 기계만. 캔버스는 재생성 금지: setPointerCapture·wheel 리스너가
요소에 붙어 있으므로 clearRect 후 재그리기. 접근성 기준선은 웨이포인트 표가
전담(표로 모든 편집 가능) — 캔버스는 Delete 키·툴바 버튼 보조.
*/

import { el } from "../dom.js";
import {
  PROFILE_LAYOUT, ZOOM_STEP, fitView, fmtMeters, hitTest, isDrag, makeProjection,
  moveWaypoint, planProfile, profileHitTest, profileScale, rowsToPoints, toCanvasXY,
  trackProfile, zoomAt, panBy,
} from "../lib/wpmap.js";
import { niceTicks } from "../lib/plot.js";
import { makeCanvas } from "./plots.js";

const HIT_PX = 10; // WP 히트 반경 [논리 px]

/** 세로 프로파일 (거리-고도) — 계획 꺾은선 + 최근 시뮬 실제 고도.
 *
 * 계획선은 엔진 LosPath가 실제로 내는 명령과 같은 모양이다 — 구간 선형 보간,
 * 첫 구간은 기체 시작 고도에서 시작, 램프는 도달 반경 경계에서 끝나고 거기부터
 * 웨이포인트 중심까지 평평(guidance/path.py). 그 마루를 그리려면 호출측이
 * planProfile에 도달 반경을 넘겨야 한다 — 안 넘기면 중심끼리 곧게 이어져 화면이
 * 구간 내내 명령보다 뒤처진 기울기를 그린다(최대 Δalt·r/seg).
 * 실제선이 있으면 겹쳐 그려 둘의 차이를 보게 한다.
 *
 * 고도가 하나도 없으면 그릴 것이 없다 — 빈 축 대신 사유 문장을 낸다(호출측).
 */
function drawProfile(ctx, plan, track, scale, width, height, selected) {
  const { mL, mT, mR, mB } = PROFILE_LAYOUT;
  const { px, py, d1, a0, a1 } = scale;
  const pts = plan.filter((p) => p.alt != null);
  ctx.clearRect(0, 0, width, height);

  ctx.strokeStyle = "#e5e5ea";
  ctx.strokeRect(mL, mT, width - mL - mR, height - mT - mB);
  ctx.fillStyle = "#86868b";
  for (const tk of niceTicks(0, d1, 4)) {
    ctx.fillText(`${Math.round(tk)}`, px(tk) - 12, height - mB + 14);
  }
  for (const tk of niceTicks(a0, a1, 4)) {
    const y = py(tk);
    if (y < mT || y > height - mB) continue;
    ctx.fillText(`${Math.round(tk)}`, 2, y + 3);
  }
  ctx.fillText("누적 수평거리 [m] →", width / 2 - 48, height - 4);

  // 실제 궤적 (옅은 파랑 — 지도의 궤적 오버레이와 같은 색 언어)
  if (track.length) {
    ctx.strokeStyle = "rgba(0, 122, 255, .55)";
    ctx.lineWidth = 1.4;
    ctx.beginPath();
    track.forEach((p, i) => (i === 0 ? ctx.moveTo(px(p.dist), py(p.alt)) : ctx.lineTo(px(p.dist), py(p.alt))));
    ctx.stroke();
  }
  // 계획 꺾은선 + 웨이포인트 점 (주황 — 지도의 편집 대상과 같은 색).
  // **고도가 빠진 자리에서 선을 끊는다** — 이어 그리면 제출하면 422로 거부될
  // 목록(고도가 섞인 열)이 멀쩡한 램프처럼 보인다. 빠진 자리를 눈에 남기는 것이
  // 이 리포의 "조용한 비표시 금지"다. 몇 번이 빠졌는지는 호출측이 문장으로 낸다
  if (pts.length) {
    ctx.strokeStyle = "#ff9500";
    ctx.lineWidth = 1.6;
    ctx.beginPath();
    let pen = false;
    for (const p of plan) {
      if (p.alt == null) { pen = false; continue; } // 구멍 — 여기서 붓을 뗀다
      const x = px(p.dist), y = py(p.alt);
      if (pen) ctx.lineTo(x, y);
      else { ctx.moveTo(x, y); pen = true; }
    }
    ctx.stroke();
    ctx.fillStyle = "#ff9500";
    for (const p of pts) {
      // 램프 꼭대기는 선만 — 점을 찍으면 웨이포인트마다 점이 둘로 보인다
      if (p.mark === "ramp") continue;
      ctx.beginPath();
      ctx.arc(px(p.dist), py(p.alt), p.idx < 0 ? 3 : 4, 0, 2 * Math.PI);
      ctx.fill();
      if (p.idx >= 0) {
        ctx.fillStyle = "#1d1d1f";
        const label = String(p.idx + 1);
        // 마지막 WP는 축 오른쪽 끝에 있다 — 오른쪽에 적으면 잘린다 (라이브 확인)
        const x = px(p.dist);
        const flip = x + 6 + ctx.measureText(label).width > width - mR;
        ctx.textAlign = flip ? "right" : "left";
        ctx.fillText(label, x + (flip ? -6 : 6), py(p.alt) - 6);
        ctx.textAlign = "left";
        ctx.fillStyle = "#ff9500";
      }
      // 선택한 웨이포인트 — 지도와 같은 표시(파란 테). 끌 수 있는 점임을 알린다.
      // **idx >= 0 필수**: selected 초기값 -1이 출발점의 idx -1과 같아서, 조건을
      // 그냥 두면 페이지를 열자마자 출발점에 테가 붙는다 — profileHitTest가
      // 명시적으로 제외하는 점이라 눌러도 안 잡히고 끌리지도 않는다(화면이
      // 사실이 아닌 것을 말하는 자리). 지도 쪽 루프는 i >= 0이라 무사했다
      if (p.idx >= 0 && p.idx === selected) {
        ctx.strokeStyle = "#007aff";
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(px(p.dist), py(p.alt), 7.5, 0, 2 * Math.PI);
        ctx.stroke();
        ctx.fillStyle = "#ff9500";
      }
    }
  }
}

/** 세로 프로파일 차트 — 그리기 + **점을 위아래로 끌어 고도 편집**.
 *
 * 지도에서 위아래 드래그는 고도가 될 수 없다: 지도 세로축이 N이라 그러면
 * 웨이포인트를 북쪽으로 옮길 수 없다. 위아래가 곧 고도인 평면은 여기뿐이라
 * 고도 편집 제스처의 자리도 여기다 (사용자 요청).
 *
 * 캔버스는 재생성 금지 — setPointerCapture가 요소에 붙는다. 지도와 같은 규약:
 * 끄는 동안에는 캔버스만 다시 그리고 표 재렌더(onRowsChanged)는 pointerup 1회다.
 */
export function createProfileChart({
  getRows, // () => wpRows — 문자열 행 참조 (차트가 직접 변이)
  getStartAlt, // () => number | null — 시작 트림 고도 (계획선의 출발점)
  getAcceptRadius, // () => number [m] — 램프 마루 위치
  getTrack, // () => {pn, pe, h} | null — 최근 시뮬 궤적
  onRowsChanged, // () => void — 편집 확정 후 표 재렌더
  onSelect, // (idx) => void — 선택 동기 (지도와 같은 웨이포인트를 가리키게)
  width = 380, height = 380,
} = {}) {
  const { canvas, ctx } = makeCanvas(width, height);
  canvas.style.touchAction = "none";
  canvas.setAttribute("aria-label", "세로 프로파일 — 점을 위아래로 끌면 고도, 표로도 편집 가능");
  let selected = -1;
  let scale = null; // 마지막 그리기의 축 — 히트테스트·역사상이 같은 표를 본다
  // 드래그 중에는 축을 **얼린다**. 안 얼리면 끌 때마다 y범위가 다시 잡혀
  // 점이 손에서 달아나고(끌수록 축이 따라 커진다) 커서와 점이 어긋난다
  let gesture = null; // {idx, scale, moved}

  const build = () => {
    const pts = rowsToPoints(getRows());
    const plan = planProfile(pts, getStartAlt?.() ?? null, getAcceptRadius?.() || 0);
    const t = getTrack?.();
    const track = t ? trackProfile(t.pn, t.pe, t.h) : [];
    return { plan, track };
  };

  function redraw() {
    const { plan, track } = build();
    scale = gesture ? gesture.scale : profileScale(plan, track, width, height);
    // 그릴 것이 없으면 캔버스를 접는다 — 축·눈금만 있는 빈 프레임에 출발점 점
    // 하나(트림 고도)가 떠 있으면, 바로 아래 "고도를 입력하면 그립니다" 안내와
    // 어긋나고 그 주황이 무엇인지 화면에 설명도 없다. 노드는 유지한다 —
    // 포인터 캡처가 요소에 붙으므로 없앴다 다시 만들면 안 된다
    const nothing = !plan.some((p) => p.idx >= 0 && p.alt != null) && !track.length;
    canvas.style.display = nothing ? "none" : "";
    // 그리기만 조건부다 — 반환은 무조건. 조기 반환으로 두면 "그린 것"과
    // "그렸을 것"이 한 계약에 섞이고, 나중에 다른 가드가 하나 붙는 순간
    // 호출측이 조용히 안 그린 것을 설명하게 된다 (그 재파생 탈출구가 §5.5)
    if (!nothing) drawProfile(ctx, plan, track, scale, width, height, selected);
    return { plan, track };
  }

  const eventXY = (ev) =>
    toCanvasXY(ev.clientX, ev.clientY, canvas.getBoundingClientRect(), width, height);

  canvas.addEventListener("pointerdown", (ev) => {
    if (ev.button !== 0 || !scale) return;
    const { x, y } = eventXY(ev);
    const idx = profileHitTest(build().plan, x, y, scale, { radiusPx: HIT_PX });
    if (idx < 0) return;
    gesture = { idx, scale, moved: false, y0: y };
    selected = idx;
    onSelect?.(idx);
    canvas.setPointerCapture(ev.pointerId);
    redraw();
  });

  canvas.addEventListener("pointermove", (ev) => {
    const { x, y } = eventXY(ev);
    if (!gesture) {
      // 끌 수 있는 점 위에서만 커서를 바꾼다 (app.css는 안 건드린다 — wpmap 관례)
      canvas.style.cursor =
        scale && profileHitTest(build().plan, x, y, scale, { radiusPx: HIT_PX }) >= 0
          ? "ns-resize" : "default";
      return;
    }
    // 문턱은 지도와 같은 정본(DRAG_PX) — 여기 1 px을 따로 적었더니 축 배율상
    // 1 px ≈ 6 m라, 손가락 탭이 2~5 px 흔들리는 터치에서는 **점을 고르려고
    // 누를 때마다 고도가 바뀌었다**(touchAction:none이라 탭도 이 경로로 온다)
    if (!gesture.moved && !isDrag(0, y - gesture.y0)) return; // 클릭=선택만
    gesture.moved = true;
    // 끈 자리가 곧 고도다 — 얼린 축의 역사상. 1 m 반올림은 표 문자열 관례 공유
    getRows()[gesture.idx].d = fmtMeters(gesture.scale.toAlt(y));
    redraw();
  });

  const endGesture = (ev) => {
    if (!gesture) return;
    const moved = gesture.moved;
    gesture = null;
    if (canvas.hasPointerCapture?.(ev.pointerId)) canvas.releasePointerCapture(ev.pointerId);
    if (moved) onRowsChanged?.(); // 표 동기는 여기서 1회 (input 포커스 파괴 방지)
    redraw(); // 얼린 축을 풀고 다시 잡는다
  };
  canvas.addEventListener("pointerup", endGesture);
  canvas.addEventListener("pointercancel", endGesture);

  redraw();
  return {
    root: canvas,
    // 그린 것을 그대로 돌려준다 — 호출측이 캡션(무엇을 설명할지·어느 행이 비었는지)을
    // 고르려고 같은 계산을 두 번째로 적으면, 한쪽만 고쳤을 때 캡션이 그려지지 않은
    // 선을 설명하게 된다 (v0.36·v0.38·v0.40이 반복해서 고쳐 온 실패, 02 §5.5)
    refresh: (sel) => {
      if (sel !== undefined) selected = sel;
      if (selected >= getRows().length) selected = -1;
      return redraw();
    },
  };
}

export function createWpMap({
  getRows, // () => wpRows — 문자열 행 참조 (지도가 직접 변이)
  getAcceptRadius, // () => number [m]
  getTrack, // () => {pn, pe} | null — 최근 시뮬 궤적
  onRowsChanged, // () => void — 추가·삭제·이동·재배열 후 표 재렌더
  onSelect, // (idx) => void — 선택이 **바뀔 때만** (세로 프로파일이 같은 점을 가리키게)
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
      // 고도가 있으면 배지에 함께 — 세로 프로파일과 지도를 눈으로 잇는 자리다
      ctx.fillText(p.d == null ? String(i + 1) : `${i + 1} · ${Math.round(p.d)} m`, x + 7, y - 7);
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
        // 고도는 직전 행에서 물려받는다 — "전부 있거나 전부 없거나" 규칙(엔진
        // set_waypoints)을 클릭 한 번으로 깨뜨리지 않게. 값도 "같은 고도로 계속"이
        // 라는 합리적 기본이고, 표·툴바에서 바로 고칠 수 있다
        const rows = getRows();
        const prevAlt = rows.length ? rows[rows.length - 1].d : undefined;
        rows.push({
          n: fmtMeters(ned.n), e: fmtMeters(ned.e),
          ...(String(prevAlt ?? "").trim() === "" ? {} : { d: String(prevAlt) }),
        });
        selected = rows.length - 1;
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
    // 배율 정본은 lib ZOOM_STEP — 종전 1.2는 **이벤트당**이라 트랙패드 한 제스처에
    // 수십 번 곱해져 지도가 튀었다 (사용자 제기). 여기서 수를 다시 적지 않는다
    viewRef.view = zoomAt(view(), ev.deltaY > 0 ? 1 / ZOOM_STEP : ZOOM_STEP, toNed(x, y));
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
  // 찍은 직후 그 자리에서 고도를 고치는 자리 — 표까지 눈을 옮기지 않아도 된다.
  // 표와 같은 wpRows를 쓰므로 단일 소스는 그대로다 (지도가 직접 변이 → onRowsChanged)
  const altInput = el("input", { class: "num-sm", "aria-label": "선택한 웨이포인트 고도 [m]" });
  altInput.oninput = () => {
    if (selected < 0) return;
    const r = getRows()[selected];
    if (altInput.value.trim() === "") delete r.d; // 빈 칸 = 고도 없음 (0이 아니다)
    else r.d = altInput.value;
    onRowsChanged();
    redraw();
  };
  let notifiedSel = null; // 마지막으로 알린 선택 — 팬 재그리기마다 알리지 않으려고
  function syncToolbar() {
    const rows = getRows();
    if (notifiedSel !== selected) {
      notifiedSel = selected;
      onSelect?.(selected);
    }
    btnDel.disabled = selected < 0;
    btnUp.disabled = selected <= 0;
    btnDown.disabled = selected < 0 || selected >= rows.length - 1;
    altInput.disabled = selected < 0;
    // 입력 중인 칸은 건드리지 않는다 — 자기 타이핑이 커서를 앞으로 튕긴다
    if (document.activeElement !== altInput) {
      altInput.value = selected < 0 ? "" : String(rows[selected].d ?? "");
    }
  }

  // 폭을 캔버스에 맞춘다 — 안 주면 아래 안내문이 늘어나 열이 한 줄을 다 먹고
  // 옆에 놓기로 한 세로 프로파일이 아래로 밀린다(라이브 확인). 좁은 화면에서는
  // shrink로 줄었다가 wrap — 캔버스는 .plot의 max-width:100%가 함께 줄인다
  const root = el("div", { style: `flex: 0 1 ${width + 16}px; min-width: 240px` },
    canvas,
    el("div", { class: "row", style: "margin-top: 6px" },
      btnFit, btnDel, btnUp, btnDown,
      el("label", { class: "field" }, "선택 WP 고도 [m]", altInput)),
    el("p", { class: "hint" },
      "클릭=추가 · 드래그=이동 · 우클릭=삭제 · 휠=줌 · 빈 곳 드래그=팬 · ▲▼=방문 순서. ",
      "새 웨이포인트는 직전 행의 고도를 물려받습니다 — 고도는 전부 채우거나 전부 비워야 하고, ",
      '그 값을 실제로 날려면 모드 테이블의 고도 칸에 "path"를 적습니다.'),
  );

  redraw();
  return {
    root,
    refresh: () => {
      if (selected >= getRows().length) selected = -1; // 표에서 행 삭제된 경우
      redraw();
    },
    // 프로파일에서 고른 점을 지도도 가리키게 — 두 면이 같은 웨이포인트를 말한다
    // 되울림 차단: 프로파일이 부른 선택을 지도가 다시 프로파일에 알리지 않는다
    select: (idx) => { selected = idx; notifiedSel = idx; redraw(); },
    fit: () => { fitAll(); redraw(); },
  };
}
