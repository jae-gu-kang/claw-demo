/** lib/wpmap.js — 지도 편집기 수치 계층 테스트. */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  CRUISE_ALT_DEFAULT, DEFAULT_SPAN, DRAG_PX, ZOOM_STEP, defaultWaypointAlt,
  fitView, fmtMeters, hitTest, isDrag,
  makeProjection, moveWaypoint, panBy, planProfile, profileHitTest, profileScale,
  rowsToPoints, toCanvasXY, trackProfile, zoomAt,
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
  assert.deepEqual(pts[0], { n: 8000, e: 0, ok: true, d: null }); // 고도 열은 선택
  assert.equal(pts[1].ok, false); // Number("")===0 함정 회피
  assert.equal(pts[2].ok, false);
  assert.deepEqual(pts[3], { n: 3, e: -2, ok: true, d: null });
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

test("ZOOM_STEP: 휠 한 이벤트당 줌이 로그 기준 20배 둔하다 (사용자 제기)", () => {
  // 종전 1.2는 이벤트당이라 트랙패드 한 제스처(수십 이벤트)에 지도가 튀었다.
  // 20회 굴려야 종전 한 번과 같아진다 — 그것이 "20배 둔하게"의 정의다
  // (처음 100배는 반대로 너무 둔해서 사용자가 5배 올려 달라고 했다)
  assert.ok(Math.abs(ZOOM_STEP ** 20 - 1.2) < 1e-9);
  assert.ok(ZOOM_STEP > 1 && ZOOM_STEP < 1.01); // 방향은 확대, 한 번에 1%도 안 움직인다
});

test("rowsToPoints: 고도는 선택 — 빈 칸은 null이지 0이 아니다", () => {
  const pts = rowsToPoints([
    { n: "100", e: "200", d: "1500" },
    { n: "300", e: "400" }, // 고도 열 자체가 없는 구버전 행
    { n: "500", e: "600", d: "" },
    { n: "700", e: "800", d: "abc" },
  ]);
  assert.deepEqual(pts.map((p) => p.d), [1500, null, null, null]);
  assert.ok(pts.every((p) => p.ok)); // 고도 유무는 표시 가능 여부와 무관
});

test("planProfile: 누적 수평거리 — 출발점(원점)부터, 표시 불가 행은 건너뛴다", () => {
  const pts = rowsToPoints([
    { n: "300", e: "400", d: "1500" }, // 원점에서 500 m
    { n: "", e: "0", d: "900" }, // 표시 불가 — 거리 누적에서도 빠진다
    { n: "300", e: "1400", d: "800" }, // 앞 유효점에서 1000 m
  ]);
  const prof = planProfile(pts, 200); // 반경 0 = 중심끼리 잇기 (폴백)
  assert.deepEqual(prof.map((p) => p.idx), [-1, 0, 2]);
  assert.deepEqual(prof.map((p) => Math.round(p.dist)), [0, 500, 1500]);
  assert.deepEqual(prof.map((p) => p.alt), [200, 1500, 800]);
  assert.deepEqual(prof.map((p) => p.mark), ["start", "wp", "wp"]);
  // 고도 미입력은 null 그대로 — 이웃 값으로 메우면 안 넣은 고도를 그리게 된다
  assert.equal(planProfile(rowsToPoints([{ n: "0", e: "100" }]))[1].alt, null);
  assert.equal(planProfile([], null)[0].alt, null); // 출발 고도 미상도 null
});

test("trackProfile: 비수치 샘플은 건너뛴다 — x가 뒤로 감기지 않는다", () => {
  const prof = trackProfile([0, 300, null, 300], [0, 400, 0, 1400], [100, 200, 300, 400]);
  assert.deepEqual(prof.map((p) => Math.round(p.dist)), [0, 500, 1500]);
  assert.deepEqual(prof.map((p) => p.alt), [100, 200, 400]);
  // 거리는 단조 증가여야 한다 (접힌 곡선 금지)
  for (let i = 1; i < prof.length; i += 1) assert.ok(prof[i].dist >= prof[i - 1].dist);
  assert.deepEqual(trackProfile([], [], []), []);
});

test("planProfile: 도달 반경을 주면 램프 마루가 생긴다 — 엔진 명령과 같은 모양", () => {
  // 엔진 램프는 웨이포인트 중심이 아니라 반경 경계에서 끝나고 그 뒤는 평평하다
  // (guidance/path.py _leg_alt). 중심끼리 곧게 이으면 화면이 구간 내내 명령보다
  // 뒤처진 기울기를 그린다 — 최대 Δalt·r/seg
  const pts = rowsToPoints([{ n: "1000", e: "0", d: "1500" }]);
  const prof = planProfile(pts, 500, 200);
  assert.deepEqual(prof.map((p) => p.mark), ["start", "ramp", "wp"]);
  assert.deepEqual(prof.map((p) => p.dist), [0, 800, 1000]); // 마루는 1000-200
  assert.deepEqual(prof.map((p) => p.alt), [500, 1500, 1500]); // 마루부터 평평
  // 구간이 반경보다 짧으면 이을 자리가 없다 — 구간 시작에서 곧바로 목표 고도
  // (엔진 denom <= 0 분기와 같은 퇴화). 같은 x의 두 점 = 수직 계단
  const short = planProfile(rowsToPoints([{ n: "100", e: "0", d: "900" }]), 500, 200);
  assert.deepEqual(short.map((p) => p.dist), [0, 0, 100]);
  assert.deepEqual(short.map((p) => p.alt), [500, 900, 900]);
  // 고도 없는 웨이포인트에는 마루를 만들지 않는다 (없는 계획을 그리지 않는다)
  const noAlt = planProfile(rowsToPoints([{ n: "1000", e: "0" }]), 500, 200);
  assert.deepEqual(noAlt.map((p) => p.mark), ["start", "wp"]);
});

test("profileScale: toAlt는 py의 역함수 — 끈 자리가 곧 고도가 된다", () => {
  const plan = planProfile(rowsToPoints([
    { n: "1000", e: "0", d: "1500" }, { n: "2000", e: "0", d: "500" },
  ]), 1000);
  const sc = profileScale(plan, [], 380, 190);
  // 왕복: 고도 → y → 고도
  for (const a of [500, 1000, 1500, sc.a0, sc.a1]) {
    assert.ok(Math.abs(sc.toAlt(sc.py(a)) - a) < 1e-9, `왕복 실패 ${a}`);
  }
  // 위로 끌면 고도가 오른다 (화면 y는 아래가 큰 값)
  assert.ok(sc.toAlt(50) > sc.toAlt(150));
  assert.ok(sc.a0 < 500 && sc.a1 > 1500); // 여백이 데이터를 감싼다
});

test("profileHitTest: 웨이포인트 점만 잡는다 — 출발점·램프 꼭대기는 아니다", () => {
  const pts = rowsToPoints([{ n: "1000", e: "0", d: "1500" }]);
  const plan = planProfile(pts, 1000, 200); // 반경 200 → 램프 꼭대기 생성
  const sc = profileScale(plan, [], 380, 190);
  const wp = plan.find((p) => p.mark === "wp");
  const ramp = plan.find((p) => p.mark === "ramp");
  const start = plan.find((p) => p.mark === "start");
  assert.equal(profileHitTest(plan, sc.px(wp.dist), sc.py(wp.alt), sc), 0);
  // 램프 꼭대기는 웨이포인트 고도에서 유도된 점이라 끌 대상이 아니다.
  // (x가 wp와 다르므로 그 자리를 눌러도 wp가 잡히지 않는다)
  assert.equal(profileHitTest(plan, sc.px(ramp.dist), sc.py(ramp.alt), sc), -1);
  // 출발점 고도는 시작 트림 고도라 이 표의 값이 아니다
  assert.equal(profileHitTest(plan, sc.px(start.dist), sc.py(start.alt), sc), -1);
  assert.equal(profileHitTest(plan, 5, 5, sc), -1); // 빈 곳
  // 고도 없는 웨이포인트는 점이 없어 잡히지 않는다 (없는 것을 끌 수 없다)
  const noAlt = planProfile(rowsToPoints([{ n: "1000", e: "0" }]), 1000, 200);
  const sc2 = profileScale(noAlt, [], 380, 190);
  assert.equal(profileHitTest(noAlt, sc2.px(noAlt[1].dist), 95, sc2), -1);
});

test("defaultWaypointAlt: 원점 반경 안은 0 — 이륙점으로 돌아오면 착륙 고도", () => {
  const rows = [{ n: "8000", e: "0", d: "700" }];
  const opt = { acceptRadius: 1500 };
  assert.equal(defaultWaypointAlt(0, 0, rows, opt), "0"); // 정확히 원점
  assert.equal(defaultWaypointAlt(900, 1200, rows, opt), "0"); // 반경 1500 안 (거리 1500)
  // 반경 밖은 직전 행 상속 — "같은 고도로 계속"이라는 기존 관례
  assert.equal(defaultWaypointAlt(0, 1501, rows, opt), "700");
  assert.equal(defaultWaypointAlt(8000, 8000, rows, opt), "700");
});

test("defaultWaypointAlt: **고도 없는 목록에는 값을 넣지 않는다** (null)", () => {
  // 넣으면 "전부 있거나 전부 없거나"가 그 자리에서 깨져, 모드가 고도를 내는 미션에서
  // 지도 클릭 한 번마다 제출이 거부되고 앞 행들에 "고도가 빈 행" 경고가 뜬다(리뷰 실측)
  const none = [{ n: "8000", e: "0" }, { n: "8000", e: "8000" }];
  const opt = { acceptRadius: 1500 };
  assert.equal(defaultWaypointAlt(5000, 3000, none, opt), null); // 먼 곳
  assert.equal(defaultWaypointAlt(0, 0, none, opt), null); // 원점도 마찬가지 — 목록을 따른다
  // 빈 문자열·공백만 있는 것도 "고도 없음"이다
  assert.equal(defaultWaypointAlt(5000, 3000, [{ n: "1", e: "2", d: "  " }], opt), null);
  // **빈 목록**은 첫 점이므로 값을 준다 (여기서 고도 있는 목록이 시작된다)
  assert.equal(defaultWaypointAlt(8000, 0, [], opt), String(CRUISE_ALT_DEFAULT));
  assert.equal(defaultWaypointAlt(0, 0, [], opt), "0");
  // 하나라도 차 있으면 "고도 있는 목록" — 섞인 상태는 이미 무효라 값을 준다
  assert.equal(defaultWaypointAlt(8000, 0, [{ n: "1", e: "2" }, { n: "3", e: "4", d: "700" }], opt), "700");
});

test("defaultWaypointAlt: 직전이 비면 순항 [기본값] — 목록의 첫 점", () => {
  const opt = { acceptRadius: 1500 };
  assert.equal(defaultWaypointAlt(8000, 0, [], opt), String(CRUISE_ALT_DEFAULT));
  // 호출측이 순항값을 정할 수 있다 (기본값을 뷰가 재기술하지 않게)
  assert.equal(defaultWaypointAlt(8000, 0, [], { ...opt, cruiseAlt: 900 }), "900");
  // null·""·0·음수는 0으로 통과하면 안 된다 — Number(null)===0 함정
  for (const bad of [null, "", 0, -100, NaN, "abc"]) {
    assert.equal(defaultWaypointAlt(8000, 0, [], { ...opt, cruiseAlt: bad }),
      String(CRUISE_ALT_DEFAULT), `cruiseAlt=${JSON.stringify(bad)}`);
  }
});

test("defaultWaypointAlt: 착륙점(0)은 물려받지 않는다 — 원점 밖은 날고 있는 자리", () => {
  // 기본 목록은 원점 복귀(0)로 끝난다. 그냥 상속하면 그 뒤에 찍는 공중 웨이포인트가
  // 전부 지상 고도를 받는다 — 라이브에서 지도 먼 곳을 찍었는데 0이 들어왔다
  const opt = { acceptRadius: 1500 };
  const landed = [{ n: "8000", e: "0", d: "700" }, { n: "0", e: "0", d: "0" }];
  assert.equal(defaultWaypointAlt(8000, 8000, landed, opt), String(CRUISE_ALT_DEFAULT));
  assert.equal(defaultWaypointAlt(8000, 8000, landed, { ...opt, cruiseAlt: 900 }), "900");
  const neg = [{ n: "1", e: "2", d: "-50" }];
  assert.equal(defaultWaypointAlt(8000, 8000, neg, opt), String(CRUISE_ALT_DEFAULT));
  // 양수는 그대로 — 문자열 원형 보존 (소수점 표기를 정규화하지 않는다)
  assert.equal(defaultWaypointAlt(8000, 8000, [{ n: "1", e: "2", d: "1250.5" }], opt), "1250.5");
});

test("defaultWaypointAlt: 반경이 없거나 비유한이어도 **정확히 원점**은 0", () => {
  const rows = [{ n: "8000", e: "0", d: "700" }];
  for (const bad of [undefined, null, NaN, Infinity, -100, 0]) {
    assert.equal(defaultWaypointAlt(0, 0, rows, { acceptRadius: bad }), "0");
  }
  // 그때 원점이 아닌 점은 원점 규칙을 안 탄다 (반경 0 = 원점만 원점)
  assert.equal(defaultWaypointAlt(1, 0, rows, { acceptRadius: NaN }), "700");
});

test("defaultWaypointAlt: 좌표가 비유한이면 원점 규칙을 안 탄다", () => {
  const opt = { acceptRadius: 1500 };
  assert.equal(defaultWaypointAlt(NaN, 0, [{ n: "1", e: "2", d: "700" }], opt), "700");
  assert.equal(defaultWaypointAlt(0, undefined, [], opt), String(CRUISE_ALT_DEFAULT));
});

test("defaultWaypointAlt: 비배열 rows는 던진다 — 빈 목록으로 눙치지 않는다", () => {
  // 눙치면 "고도 없는 목록"이 값을 받아 불변식 회귀가 조용히 되살아나고,
  // 옛 3인자 호출이 그럴듯한 값을 돌려받아 더 안 들킨다
  assert.throws(() => defaultWaypointAlt(0, 0, undefined, { acceptRadius: 1500 }), /배열이어야 함/);
  assert.throws(() => defaultWaypointAlt(5000, 3000, { prevAlt: "700" }), /배열이어야 함/);
  assert.throws(() => defaultWaypointAlt(0, 0, null), /배열이어야 함/);
});
