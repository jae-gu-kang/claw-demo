/** lib/wpmap.js — 지도 편집기 수치 계층 테스트. */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  DEFAULT_SPAN, DRAG_PX, fitView, fmtMeters, hitTest, isDrag,
  makeProjection, moveWaypoint, panBy, rowsToPoints, toCanvasXY, zoomAt,
} from "./wpmap.js";

const W = 380, H = 380, M = 42;

test("fitView: 모든 점 포함 등축 뷰 — 중심·span, 빈 목록은 원점 기본 뷰", () => {
  const v = fitView([[0, 0], [8000, 0], [8000, 8000]]);
  assert.equal(v.cN, 4000);
  assert.equal(v.cE, 4000);
  assert.equal(v.span, 8000 * 1.15); // trackCanvas와 동일 pad 규약
  assert.deepEqual(fitView([]), { cN: 0, cE: 0, span: DEFAULT_SPAN });
});

test("fitView: 단일 점·전부 동일 점 퇴화 시 minSpan 하한 (0-span 나눗셈 금지)", () => {
  const v = fitView([[500, 300], [500, 300]]);
  assert.equal(v.cN, 500);
  assert.equal(v.cE, 300);
  assert.equal(v.span, 200); // minSpan
});

test("makeProjection: toPx↔toNed 왕복 항등 + 북쪽 위(y 반전) · 등축(kScale 단일)", () => {
  const view = { cN: 4000, cE: 4000, span: 10000 };
  const { toPx, toNed, kScale } = makeProjection(view, W, H, M);
  // 왕복 항등
  for (const [n, e] of [[0, 0], [4000, 4000], [9000, -1000]]) {
    const { x, y } = toPx(n, e);
    const back = toNed(x, y);
    assert.ok(Math.abs(back.n - n) < 1e-9 && Math.abs(back.e - e) < 1e-9, `왕복 실패 (${n},${e})`);
  }
  // 북쪽 위: n 증가 → y 감소
  assert.ok(toPx(5000, 4000).y < toPx(3000, 4000).y);
  // 등축: 1000 m가 x·y에서 같은 픽셀 수
  const dx = toPx(4000, 5000).x - toPx(4000, 4000).x;
  const dy = toPx(4000, 4000).y - toPx(5000, 4000).y;
  assert.ok(Math.abs(dx - dy) < 1e-9);
  assert.ok(Math.abs(dx - 1000 * kScale) < 1e-9);
});

test("zoomAt: 커서 아래 NED 점 화면 고정 (커서 중심 줌) — 확대·축소 양방향", () => {
  const view = { cN: 4000, cE: 4000, span: 10000 };
  const cursor = { n: 7000, e: 2000 };
  const before = makeProjection(view, W, H, M).toPx(cursor.n, cursor.e);
  for (const factor of [1.2, 1 / 1.2]) {
    const zoomed = zoomAt(view, factor, cursor);
    const after = makeProjection(zoomed, W, H, M).toPx(cursor.n, cursor.e);
    assert.ok(Math.abs(after.x - before.x) < 1e-9 && Math.abs(after.y - before.y) < 1e-9,
      `factor=${factor}에서 커서 지점 이동`);
  }
});

test("zoomAt: span 상·하한 클램프 — 한계에서 추가 줌은 뷰 불변 (미끄러짐 회귀)", () => {
  const atMin = { cN: 100, cE: 200, span: 50 };
  assert.deepEqual(zoomAt(atMin, 2, { n: 999, e: 999 }), atMin); // 실효 factor 1 → 중심도 불변
  const atMax = { cN: 100, cE: 200, span: 1e6 };
  assert.deepEqual(zoomAt(atMax, 0.5, { n: 999, e: 999 }), atMax);
});

test("panBy: 픽셀 델타 → 미터 이동 — 끌기 방향과 지도 이동 방향 일치 (y 반전 회귀)", () => {
  const view = { cN: 0, cE: 0, span: 1000 };
  const { kScale } = makeProjection(view, W, H, M);
  // 오른쪽으로 100px 끌면 지도 내용이 오른쪽으로 → 중심 E는 감소
  const right = panBy(view, 100, 0, kScale);
  assert.ok(right.cE < 0 && right.cN === 0);
  assert.ok(Math.abs(right.cE + 100 / kScale) < 1e-9);
  // 아래로 100px 끌면 북쪽이 내려옴 → 중심 N은 증가 (화면 y↓ = 북↓ 반전)
  const down = panBy(view, 0, 100, kScale);
  assert.ok(down.cN > 0 && down.span === view.span);
});

test("hitTest: 겹친 WP는 뒤 인덱스(위에 그려진 것) 우선, 반경 밖은 -1", () => {
  const view = { cN: 0, cE: 0, span: 1000 };
  const { toPx } = makeProjection(view, W, H, M);
  const pts = [{ n: 0, e: 0, ok: true }, { n: 2, e: 2, ok: true }]; // 픽셀상 거의 겹침
  const { x, y } = toPx(0, 0);
  assert.equal(hitTest(pts, x, y, toPx), 1); // 나중 인덱스 우선
  assert.equal(hitTest(pts, x + 200, y, toPx), -1);
});

test("hitTest: ok:false(빈·비수치 행) 점은 집히지 않음", () => {
  const view = { cN: 0, cE: 0, span: 1000 };
  const { toPx } = makeProjection(view, W, H, M);
  const pts = [{ n: 0, e: 0, ok: false }];
  const { x, y } = toPx(0, 0);
  assert.equal(hitTest(pts, x, y, toPx), -1);
});

test("toCanvasXY: CSS max-width 축소로 rect≠논리 크기일 때 좌표 보정 (app.css canvas.plot 회귀)", () => {
  // 논리 380px 캔버스가 CSS로 190px에 그려진 경우 — 화면 절반 지점 = 논리 절반 지점
  const rect = { left: 10, top: 20, width: 190, height: 190 };
  const { x, y } = toCanvasXY(10 + 95, 20 + 95, rect, W, H);
  assert.equal(x, 190);
  assert.equal(y, 190);
});

test("rowsToPoints: 빈 문자열이 0으로 조용히 주입되지 않음 — ok:false 표시 제외", () => {
  const pts = rowsToPoints([
    { n: "8000", e: "0" }, { n: "", e: "5" }, { n: "abc", e: "1" }, { n: " 3 ", e: "-2" },
  ]);
  assert.equal(pts.length, 4); // 행 순서·길이 보존 (인덱스 = 표 행)
  assert.deepEqual(pts[0], { n: 8000, e: 0, ok: true });
  assert.equal(pts[1].ok, false); // Number("")===0 함정 회피
  assert.equal(pts[2].ok, false);
  assert.deepEqual(pts[3], { n: 3, e: -2, ok: true });
});

test("isDrag: 임계 — 미만은 클릭(추가/선택), 초과는 드래그/팬", () => {
  assert.equal(isDrag(DRAG_PX, 0), false); // 경계는 클릭
  assert.equal(isDrag(DRAG_PX + 1, 0), true);
  assert.equal(isDrag(4, 4), true); // 대각 √32 > 5
});

test("moveWaypoint: 인접 스왑 · 경계(첫 행 ▲, 끝 행 ▼)는 무변경 반환", () => {
  const rows = [{ n: "1" }, { n: "2" }, { n: "3" }];
  assert.equal(moveWaypoint(rows, 2, 1), true);
  assert.deepEqual(rows.map((r) => r.n), ["1", "3", "2"]);
  assert.equal(moveWaypoint(rows, 0, -1), false); // 첫 행 ▲
  assert.equal(moveWaypoint(rows, 2, 3), false); // 끝 행 ▼
  assert.deepEqual(rows.map((r) => r.n), ["1", "3", "2"]); // 무변경
});

test("fmtMeters: 1 m 반올림 · -0 정규화 — 표 문자열 오염 방지", () => {
  assert.equal(fmtMeters(1234.6), "1235");
  assert.equal(fmtMeters(-0.4), "0"); // "-0" 금지
  assert.equal(fmtMeters(-1234.6), "-1235");
});
