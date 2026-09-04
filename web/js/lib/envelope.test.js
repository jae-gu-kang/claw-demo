/** 엔벨로프 lib 검증 — 다각형 조립·구간 병합·판정 셀 분류·프리필 판단 (01 §2.6). */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  boundColor, boundLabel, boundarySegments, capLabel, dbLoBinds, envelopeQuery, ftToM, isoLabelIndex,
  isoOffWindow, kindColor, kindLabel, machSpan, machWindow, mToFt, msToKt, optNum, outlineCaps,
  outsideRegion, prefillValue, regionPolygons, scanCells, scanSummary, spreadLabels,
  tasAxisTicks, throttleCell, thrustFrontier,
} from "./envelope.js";

const region = (rows) => ({
  alt: rows.map((r) => r[0]),
  mach_lo: rows.map((r) => r[1]),
  mach_hi: rows.map((r) => r[2]),
  lo_source: rows.map((r) => r[3]),
  hi_source: rows.map((r) => r[4]),
  empty: rows.map((r) => r[5] ?? false),
});

const bounds = (o = {}) => ({
  alt_min: null, alt_max: null, alt_min_used: 0, alt_max_used: 4000,
  alt_max_is_display_default: true, ...o,
});

test("regionPolygons — lo 오름·hi 내림 폐곡선, empty 행에서 분할", () => {
  const r = region([
    [0, 0.3, 0.75, "stall", "mach_no"],
    [1000, 0.32, 0.75, "stall", "mach_no"],
    [2000, 0.8, 0.75, "stall", "mach_no", true], // 자연 천장 — 여기서 끊김
    [3000, 0.4, 0.75, "stall", "mach_no"],
    [4000, 0.42, 0.75, "stall", "mach_no"],
  ]);
  const polys = regionPolygons(r);
  assert.equal(polys.length, 2);
  assert.deepEqual(polys[0], [
    { mach: 0.3, alt: 0 }, { mach: 0.32, alt: 1000 },
    { mach: 0.75, alt: 1000 }, { mach: 0.75, alt: 0 },
  ]);
  assert.deepEqual(polys[1].map((p) => p.alt), [3000, 4000, 4000, 3000]);
});

test("regionPolygons — 한 행짜리 조각은 면이 못 된다 (버림)", () => {
  const r = region([
    [0, 0.3, 0.75, "stall", "mach_no"],
    [1000, 0.32, 0.75, "stall", "mach_no"],
    [2000, 0.8, 0.75, "stall", "mach_no", true],
    [3000, 0.4, 0.75, "stall", "mach_no"], // 고립 1행 — 면이 못 됨
  ]);
  const polys = regionPolygons(r);
  assert.equal(polys.length, 1);
  assert.deepEqual(polys[0].map((p) => p.alt), [0, 1000, 1000, 0]);
});

test("boundarySegments — 같은 source 병합 + 전환점 공유 (곡선 연속)", () => {
  const r = region([
    [0, 0.3, 0.53, "stall", "qbar"],
    [1000, 0.32, 0.58, "stall", "qbar"],
    [2000, 0.34, 0.75, "stall", "mach_no"],
    [3000, 0.36, 0.75, "db", "mach_no"],
  ]);
  const segs = boundarySegments(r);
  const lo = segs.filter((s) => s.side === "lo");
  const hi = segs.filter((s) => s.side === "hi");
  assert.deepEqual(lo.map((s) => s.source), ["stall", "db"]);
  assert.deepEqual(hi.map((s) => s.source), ["qbar", "mach_no"]);
  // 전환점 공유 — db 세그먼트가 직전 stall 점에서 시작
  assert.deepEqual(lo[1].pts[0], { mach: 0.34, alt: 2000 });
  assert.equal(lo[1].pts.length, 2);
  assert.deepEqual(hi[1].pts[0], { mach: 0.58, alt: 1000 });
});

test("boundarySegments — empty 행이 세그먼트를 끊는다 (가짜 연결선 금지)", () => {
  const r = region([
    [0, 0.3, 0.75, "stall", "mach_no"],
    [1000, 0.8, 0.75, "stall", "mach_no", true],
    [2000, 0.4, 0.75, "stall", "mach_no"],
  ]);
  const lo = boundarySegments(r).filter((s) => s.side === "lo");
  assert.equal(lo.length, 2);
  assert.deepEqual(lo[1].pts, [{ mach: 0.4, alt: 2000 }]); // 직전 점 없이 새로 시작
});

test("bound/kind 라벨·색 — 모르는 코드는 코드 그대로 (조용히 숨기지 않는다)", () => {
  assert.equal(boundLabel("qbar"), "q̄ 한계 (구조)");
  assert.equal(boundLabel("warp_drive"), "warp_drive");
  assert.match(boundColor("stall"), /^#/);
  assert.match(boundColor("warp_drive"), /^#/); // 폴백 색도 유효한 색
  assert.equal(kindLabel("saturated_throttle_high"), "스로틀 상한 포화 (추진 한계)");
  assert.equal(kindLabel("future_reason"), "future_reason");
});

const entry = (mach, alt, ok, reasons = [], { converged = true, thr = 0.3 } = {}) => ({
  trim: {
    case: { name: `M${mach}_h${alt}_f200`, mach, alt, fuel: 200 },
    converged,
    control: { throttle: [thr, thr] },
  },
  verdict: { ok, reasons },
});

test("scanCells — kind는 엔진 reasons 첫 항목 (우선순위 대표), ok는 'ok'", () => {
  const cells = scanCells([
    entry(0.5, 1000, true),
    entry(0.2, 1000, false, ["alpha_margin", "saturated_throttle_low"]),
    entry(0.7, 5000, false, ["saturated_throttle_high"]),
    entry(0.1, 0, false, [], { converged: false }), // 사유 누락 방어
  ]);
  assert.deepEqual(cells.map((c) => c.kind),
    ["ok", "alpha_margin", "saturated_throttle_high", "unknown"]);
  assert.deepEqual(cells.map((c) => c.ok), [true, false, false, false]);
  assert.equal(cells[0].mach, 0.5);
});

test("scanSummary — 실패만 엔진 우선순위 순, 미정의 코드는 뒤에 그대로", () => {
  const s = scanSummary([
    { kind: "ok" }, { kind: "ok" },
    { kind: "saturated_throttle_high" },
    { kind: "not_converged" }, { kind: "not_converged" },
    { kind: "future_reason" },
  ]);
  assert.equal(s.total, 6);
  assert.equal(s.ok, 2);
  assert.deepEqual(s.byKind, [
    { kind: "not_converged", n: 2 },
    { kind: "saturated_throttle_high", n: 1 },
    { kind: "future_reason", n: 1 },
  ]);
});

test("throttleCell — 소요 % 표시, 포화는 엔진 사유가 정본, 미수렴은 판정 불가", () => {
  const ok = throttleCell(entry(0.5, 1000, true, [], { thr: 0.62 }));
  assert.equal(ok.text, "62%");
  assert.match(ok.color, /^hsl\(/);
  // 색 문턱을 웹이 만들지 않는다 — 포화 판정은 verdict.reasons에서만
  const highButNotFlagged = throttleCell(entry(0.5, 1000, false, ["alpha_margin"], { thr: 0.9 }));
  assert.equal(highButNotFlagged.text, "90%");
  const sat = throttleCell(
    entry(0.7, 8000, false, ["saturated_throttle_high"], { thr: 0.97 }));
  assert.equal(sat.text, "97% 포화");
  const na = throttleCell(entry(0.1, 0, false, ["not_converged"], { converged: false }));
  assert.equal(na.text, "불가");
});

test("prefillValue — 손댄 필드 유지, 아니면 echo 갱신, null은 빈칸 (02 §5.5)", () => {
  assert.equal(prefillValue("4.5", true, 6.0), "4.5"); // 사용자 값 보존
  assert.equal(prefillValue("", false, 6.0), "6"); // 첫 응답 프리필
  assert.equal(prefillValue("6", false, 4.0), "4"); // 안 만진 필드는 자기 정렬
  assert.equal(prefillValue("6", false, null), ""); // 경계 없음 — 빈칸
});

test("optNum — 빈칸 null(생략 계약), 비수치는 라벨 달아 던진다", () => {
  assert.equal(optNum(""), null);
  assert.equal(optNum("  "), null);
  assert.equal(optNum("30000"), 30000);
  assert.equal(optNum("-3"), -3);
  assert.throws(() => optNum("abc", "q̄_max"), /q̄_max.*숫자가 아님/);
  assert.throws(() => optNum("Infinity"), /숫자가 아님/);
});

test("envelopeQuery — null 생략 (보내는 순간 user-input이 되므로), 0은 보낸다", () => {
  const q = envelopeQuery({ fuel: 200, q_max: null, alt_min: 0, mach_no: undefined });
  assert.equal(q, "fuel=200&alt_min=0");
});

test("outlineCaps — 상·하 캡 귀속: 운용 한계 / 표시 한계 / 자연 천장", () => {
  // 도메인 바닥(0)에서 시작해 3000에서 자연 천장, 4000은 다시 유효
  const r = region([
    [0, 0.3, 0.75, "stall", "mach_no"],
    [1000, 0.32, 0.75, "stall", "mach_no"],
    [2000, 0.34, 0.75, "stall", "mach_no"],
    [3000, 0.8, 0.75, "stall", "mach_no", true],
    [4000, 0.4, 0.75, "stall", "mach_no"],
  ]);
  const caps = outlineCaps(r, bounds());
  // 첫 run: 바닥은 표시 하한(운용 하한 미입력), 위는 자연 천장
  assert.deepEqual(caps[0], { side: "bottom", alt: 0, mach0: 0.3, mach1: 0.75, source: "display_min" });
  assert.deepEqual(caps[1], { side: "top", alt: 2000, mach0: 0.34, mach1: 0.75, source: "natural_ceiling" });
  // 둘째 run은 한 행짜리 — 아래는 자연 바닥, 위는 표시 상한
  assert.equal(caps[2].source, "natural_floor");
  assert.equal(caps[3].source, "display_max");
  assert.equal(caps.length, 4);
});

test("outlineCaps — 운용 고도를 입력하면 표시 한계가 아니라 운용 한계로 귀속", () => {
  const r = region([
    [500, 0.3, 0.75, "stall", "mach_no"],
    [4000, 0.4, 0.75, "stall", "mach_no"],
  ]);
  const caps = outlineCaps(r, bounds({
    alt_min: 500, alt_max: 4000, alt_min_used: 500, alt_max_is_display_default: false,
  }));
  assert.equal(caps[0].source, "ops_alt_min");
  assert.equal(caps[1].source, "ops_alt_max");
  // 라벨은 "실제 천장인가 표시 상한인가"를 문장으로 구분해야 한다
  assert.notEqual(capLabel("ops_alt_max"), capLabel("display_max"));
  assert.equal(capLabel("존재하지않는코드"), "존재하지않는코드");
});

test("outlineCaps — 전 행이 empty면 캡이 없다 (없는 경계를 그리지 않는다)", () => {
  const r = region([
    [0, 0.8, 0.75, "n_reach", "mach_no", true],
    [1000, 0.8, 0.75, "n_reach", "mach_no", true],
  ]);
  assert.deepEqual(outlineCaps(r, bounds()), []);
});

test("spreadLabels — 겹치는 라벨을 최소 간격으로 밀되 순서를 보존", () => {
  const items = [{ y: 100, t: "a" }, { y: 104, t: "b" }, { y: 300, t: "c" }, { y: 106, t: "d" }];
  const out = spreadLabels(items, 12);
  assert.deepEqual(out.map((o) => o.t), ["a", "b", "c", "d"]); // 입력 순서 유지
  const byY = [...out].sort((p, q) => p.y - q.y);
  assert.deepEqual(byY.map((o) => o.t), ["a", "b", "d", "c"]); // y 순서 유지
  for (let i = 1; i < byY.length; i += 1) {
    assert.ok(byY[i].y - byY[i - 1].y >= 12 - 1e-9);
  }
  // 이미 벌어져 있으면 손대지 않는다
  assert.deepEqual(spreadLabels([{ y: 0 }, { y: 50 }], 12).map((o) => o.y), [0, 50]);
});

test("thrustFrontier — 포화/비포화 전이점을 양쪽 다 낸다 (고속 한계·저속 backside)", () => {
  const sat = ["saturated_throttle_high"];
  const cells = [
    // 고속 쪽 포화 — 마하가 오르며 비포화→포화로 넘어간다
    { mach: 0.3, alt: 0, reasons: [] },
    { mach: 0.5, alt: 0, reasons: [] },
    { mach: 0.6, alt: 0, reasons: sat },
    { mach: 0.7, alt: 0, reasons: sat },
    // 저속 쪽 포화 — 유도항력이 커서 느릴수록 추력이 모자란다 (항력곡선 backside).
    // 최소 마하만 보면 스캔 왼쪽 끝을 경계라고 우기게 된다 — 실측에서 드러난 오류
    { mach: 0.2, alt: 3000, reasons: sat },
    { mach: 0.3, alt: 3000, reasons: ["not_converged", ...sat] }, // 대표 kind에 가려진 포화
    { mach: 0.4, alt: 3000, reasons: [] },
    { mach: 0.4, alt: 6000, reasons: ["alpha_margin"] }, // 포화 없음 — 행 자체가 빠진다
  ];
  assert.deepEqual(thrustFrontier(cells), [
    { alt: 0, mach: 0.6, side: "hi", provisional: false },
    { alt: 3000, mach: 0.3, side: "lo", provisional: true }, // 미수렴 셀이 전이점
  ]);
  // 행 전체가 포화면 전이가 없다 — 경계를 스캔 가장자리에서 지어내지 않는다
  assert.deepEqual(thrustFrontier([
    { mach: 0.2, alt: 0, reasons: sat }, { mach: 0.3, alt: 0, reasons: sat },
  ]), []);
  assert.deepEqual(thrustFrontier([]), []);
});

test("scanCells — reasons 전량을 함께 싣는다 (대표 kind만으로는 못 찾는 사유가 있다)", () => {
  const e = entry(0.5, 1000, false, ["not_converged", "saturated_throttle_high"]);
  const [c] = scanCells([e]);
  assert.equal(c.kind, "not_converged"); // 대표는 여전히 첫 사유
  assert.deepEqual(c.reasons, ["not_converged", "saturated_throttle_high"]);
  assert.deepEqual(scanCells([entry(0.5, 0, true)])[0].reasons, []);
});

test("mToFt/ftToM — 우측 고도축 환산 (정의값 0.3048)", () => {
  assert.equal(mToFt(0), 0);
  assert.ok(Math.abs(mToFt(1000) - 3280.839895) < 1e-6);
  assert.ok(Math.abs(mToFt(0.3048) - 1) < 1e-12);
  // 보조축이 자기 눈금을 가지려면 그 ft 값을 다시 m 자리로 되돌려야 한다
  assert.equal(ftToM(0), 0);
  assert.ok(Math.abs(ftToM(1) - 0.3048) < 1e-15);
  assert.ok(Math.abs(ftToM(mToFt(12345)) - 12345) < 1e-9);
});

test("isoLabelIndex — 기준점에서 바깥으로 훑어 첫 범위 안 인덱스, 전부 밖이면 -1", () => {
  const curve = { q: 10000, mach: [0.2, 0.5, 0.9, 1.4] };
  assert.equal(isoLabelIndex(curve, 0.3, 1.0), 2); // 기본 기준점은 마지막
  assert.equal(isoLabelIndex(curve, 0.0, 0.3), 0);
  assert.equal(isoLabelIndex(curve, 2.0, 3.0), -1);
  // 기준점을 주면 그 근처를 고른다 — 여러 곡선이 같은 행에 몰리는 것을 피하는 수단
  assert.equal(isoLabelIndex(curve, 0.0, 2.0, 1), 1);
  assert.equal(isoLabelIndex(curve, 0.3, 1.0, 0), 1); // 0은 범위 밖 → 바깥으로 한 칸
});

test("outsideRegion — q̄ 경계 밖 스케줄 격자점을 집어낸다 (이웃 행 보간)", () => {
  const r = region([
    [0, 0.3, 0.55, "stall", "qbar"],
    [1000, 0.32, 0.60, "stall", "qbar"],
    [2000, 0.8, 0.75, "stall", "mach_no", true], // empty 행 — 어떤 마하든 밖
  ]);
  assert.equal(outsideRegion({ mach: 0.45, alt: 0 }, r), false);
  assert.equal(outsideRegion({ mach: 0.7, alt: 0 }, r), true); // q̄ 상한 밖
  assert.equal(outsideRegion({ mach: 0.2, alt: 1000 }, r), true); // 실속 하한 밖
  assert.equal(outsideRegion({ mach: 0.5, alt: 2000 }, r), true); // empty 행
  assert.equal(outsideRegion({ mach: 0.5, alt: 0 }, { alt: [], mach_lo: [], mach_hi: [], empty: [] }), false);
  // 행 사이 고도는 보간 — 500 m에서 하한은 0.31, 상한은 0.575
  assert.equal(outsideRegion({ mach: 0.312, alt: 500 }, r), false);
  assert.equal(outsideRegion({ mach: 0.29, alt: 500 }, r), true);
  assert.equal(outsideRegion({ mach: 0.57, alt: 500 }, r), false);
  assert.equal(outsideRegion({ mach: 0.60, alt: 500 }, r), true);
});

test("outsideRegion — 행 이산화만큼의 어긋남은 이탈이 아니다 (상시 경고 방지)", () => {
  // 표시 행은 300 m 간격인데 격자점 마하는 자기 고도에서 정확히 계산된다.
  // 그 차이(≪1e-3)를 이탈로 세면 경고가 늘 켜져 진짜 q̄ 이탈을 덮는다.
  const r = region([
    [4800, 0.3050, 0.75, "stall", "mach_no"],
    [5100, 0.3095, 0.75, "stall", "mach_no"],
  ]);
  assert.equal(outsideRegion({ mach: 0.3080 - 2e-4, alt: 5000 }, r), false);
  assert.equal(outsideRegion({ mach: 0.3080 - 5e-3, alt: 5000 }, r), true); // 진짜 이탈은 잡는다
});

test("thrustFrontier — 행 가운데 고립 포화 섬은 전선이 아니다 (가짜 가로 전선 방지)", () => {
  const sat = ["saturated_throttle_high"];
  // 기본 스캔(0.2~0.7/0.05)의 5000 m 행에서 실제로 났던 모양: M0.25 한 칸만 포화이고
  // 진짜 고속 한계는 M0.55다. 전이를 전부 내면 이 한 칸이 같은 좌표에 hi·lo를 둘 다
  // 내고, 그 hi(M0.25)가 다른 고도의 hi와 이어져 평면을 가로지르는 줄이 그려졌다
  const 섬 = [
    { mach: 0.20, alt: 5000, reasons: ["not_converged", "alpha_margin"] },
    { mach: 0.25, alt: 5000, reasons: ["not_converged", "alpha_margin", ...sat] },
    { mach: 0.30, alt: 5000, reasons: [] },
    { mach: 0.50, alt: 5000, reasons: [] },
    { mach: 0.55, alt: 5000, reasons: sat },
  ];
  assert.deepEqual(thrustFrontier(섬), [
    { alt: 5000, mach: 0.55, side: "hi", provisional: false },
  ]);
  // 양쪽 끝이 다 포화면 lo·hi 하나씩 — 가운데 섬이 있어도 개수는 그대로다
  const 양끝 = [
    { mach: 0.20, alt: 0, reasons: sat }, { mach: 0.25, alt: 0, reasons: sat },
    { mach: 0.30, alt: 0, reasons: [] },
    { mach: 0.40, alt: 0, reasons: sat },                 // 가운데 섬 — 무시된다
    { mach: 0.50, alt: 0, reasons: [] },
    { mach: 0.60, alt: 0, reasons: sat },
  ];
  assert.deepEqual(thrustFrontier(양끝), [
    { alt: 0, mach: 0.25, side: "lo", provisional: false },
    { alt: 0, mach: 0.60, side: "hi", provisional: false },
  ]);
});

test("thrustFrontier — 미수렴 셀의 전이점은 잠정 (해가 아니라 솔버 마지막 반복값)", () => {
  const sat = ["saturated_throttle_high"];
  const pts = thrustFrontier([
    { mach: 0.3, alt: 0, reasons: [] },
    { mach: 0.6, alt: 0, reasons: sat }, // 수렴한 포화 — 측정
    { mach: 0.3, alt: 3000, reasons: [] },
    { mach: 0.6, alt: 3000, reasons: ["not_converged", ...sat] }, // 미수렴 — 잠정
  ]);
  assert.deepEqual(pts.map((p) => p.provisional), [false, true]);
});

test("isoLabelIndex — 범위 밖 기준점은 배열 안으로 접는다 ('화면 밖'과 혼동 금지)", () => {
  const curve = { q: 1000, mach: [0.2, 0.5] };
  assert.equal(isoLabelIndex(curve, 0.1, 0.6, 99), 1); // 접지 않으면 -1이 나온다
  assert.equal(isoLabelIndex(curve, 0.1, 0.6, -5), 0);
  assert.equal(isoLabelIndex(curve, 2.0, 3.0, 99), -1); // 진짜 화면 밖은 여전히 -1
});

test("msToKt — 상단 속도축 환산 (해리 정의값 1852 m)", () => {
  assert.equal(msToKt(1852 / 3600), 1); // 정의 그대로: 1 kt = 1852 m/h
  assert.ok(Math.abs(msToKt(100) - 194.384) < 1e-3);
});

test("tasAxisTicks — 눈금은 기준 고도의 음속으로 마하에 얹히고, 범위 밖은 안 낸다", () => {
  const a = 295.0694935090715; // 12 km ISA — 도표 상단 모서리
  const ticks = tasAxisTicks(0.07, 0.93, a);
  assert.ok(ticks.length >= 3);
  for (const t of ticks) {
    // 눈금 자리는 정확히 M = V/a — 축은 이 고도 선 위에서 참이다
    assert.ok(Math.abs(t.mach - t.kt / msToKt(1) / a) < 1e-12);
    // 범위 밖 눈금을 안 낸다 — 상단 축은 클립 **밖**에서 그려지므로 여기서
    // 걸러야 프레임 밖에 눈금이 찍히지 않는다. 다만 지금 niceTicks가 이미 범위
    // 안만 내므로 이 단언은 필터 **단독**을 핀하지 못한다(필터를 지워도 통과):
    // niceTicks의 범위 계약이 바뀌는 회귀를 잡는 자리다
    assert.ok(t.mach >= 0.07 && t.mach <= 0.93);
    assert.equal(t.kt, Math.round(t.kt)); // niceTicks의 둥근 값이 그대로 라벨
  }
  // 같은 마하라도 기준 고도가 낮으면(음속이 크면) 더 빠른 kt가 붙는다
  const lo = tasAxisTicks(0.07, 0.93, 340.293988026089);
  assert.ok(lo[lo.length - 1].kt > ticks[ticks.length - 1].kt);
});

test("tasAxisTicks — 음속이 비유한·비양수면 축을 안 그린다 (0 kt 눈금 금지)", () => {
  // 환산이 실패한 자리에 그럴듯한 숫자를 남기면 화면이 없는 속도를 말한다
  for (const bad of [0, -1, NaN, Infinity, undefined]) {
    assert.deepEqual(tasAxisTicks(0.1, 0.9, bad), []);
  }
  assert.deepEqual(tasAxisTicks(0.5, 0.5, 340), []); // 폭 0인 축도 마찬가지
});

test("machWindow — 캔버스와 캡션이 같은 창을 본다 (구속하는 DB 하한~M_D + 여백)", () => {
  const r = region([
    [0, 0.30, 0.75, "stall", "mach_no"],
    [1000, 0.32, 0.60, "stall", "qbar"],
  ]);
  // DB 하한 0.1은 합성 하한 0.30보다 아래 → 구속이 아니므로 창을 벌리지 않는다
  const w = machWindow({ db_mach: [0.1, 0.9], mach_d: 0.9 }, r);
  assert.ok(Math.abs(w.xMin - 0.27) < 1e-12); // 합성 하한 0.30 − 0.03
  assert.ok(Math.abs(w.xMax - 0.93) < 1e-12); // max(M_D 0.9, 합성 상한 0.75) + 0.03
  // 합성 하한이 DB 하한보다 낮으면 그쪽이 이긴다 (창이 곡선을 자르지 않게)
  const w2 = machWindow({ db_mach: [0.5, 0.9], mach_d: 0.6 }, r, 0);
  assert.ok(Math.abs(w2.xMin - 0.30) < 1e-12);
  assert.ok(Math.abs(w2.xMax - 0.75) < 1e-12);
  // DB 하한이 실제로 영역을 자르면 그때는 창이 거기까지 벌어진다
  const w3 = machWindow({ db_mach: [0.40, 0.9], mach_d: 0.9 }, r, 0);
  assert.ok(Math.abs(w3.xMin - 0.30) < 1e-12); // min(0.40, 0.30) = 0.30
});

test("dbLoBinds — DB 마하 하한이 실효 구속일 때만 참 (선을 그릴지와 창을 벌릴지가 같은 판단)", () => {
  const r = region([
    [0, 0.30, 0.75, "stall", "mach_no"],
    [1000, 0.32, 0.60, "stall", "qbar"],
  ]);
  assert.equal(dbLoBinds({ db_mach: [0.1, 0.9] }, r), false); // 영역 아래 — 아무것도 안 자름
  assert.equal(dbLoBinds({ db_mach: [0.0, 0.9] }, r), false); // 이착륙 도입 후 데모 값
  assert.equal(dbLoBinds({ db_mach: [0.40, 0.9] }, r), true); // 영역 안 — 실제로 자름
  assert.equal(dbLoBinds({ db_mach: [0.30, 0.9] }, r), false); // 하한과 같으면 자르지 않음
  // 판정 불가를 "구속함"으로 위장하지 않는다 — 근거가 없으면 선을 그리지 않는다
  assert.equal(dbLoBinds({}, r), false);
  assert.equal(dbLoBinds({ db_mach: [NaN, 0.9] }, r), false);
  assert.equal(dbLoBinds({ db_mach: [0.4, 0.9] }, { mach_lo: [] }), false);
});

test("isoOffWindow — 한 점도 창 안에 없는 곡선만 (조용한 비표시를 화면이 세도록)", () => {
  const curves = [
    { v: 100, mach: [0.30, 0.34] }, // 전부 창 안
    { v: 150, mach: [0.44, 0.51] }, // 전부 창 밖 — 켜도 통째로 사라진다
    { v: 120, mach: [0.34, 0.42] }, // 한 점만 걸쳐도 보이는 것이다 (창 밖 아님)
  ];
  assert.deepEqual(isoOffWindow(curves, 0.07, 0.35).map((c) => c.v), [150]);
  // 창이 넓으면 아무것도 숨지 않는다 — 없는 경고를 내지 않는다
  assert.deepEqual(isoOffWindow(curves, 0.07, 0.93), []);
  // 경계는 포함 — 끝점이 정확히 창 모서리인 곡선을 "밖"이라 부르지 않는다
  assert.deepEqual(isoOffWindow([{ v: 9, mach: [0.35, 0.51] }], 0.07, 0.35), []);
});

test("machSpan — 창 밖 안내의 증거 숫자, 비유한값이 섞이면 null (지어내지 않는다)", () => {
  assert.deepEqual(machSpan({ mach: [0.45, 0.52, 0.61] }), { lo: 0.45, hi: 0.61 });
  assert.deepEqual(machSpan({ mach: [0.61, 0.45] }), { lo: 0.45, hi: 0.61 }); // 단조 가정 안 함
  // Math.min은 null을 0으로 취급한다 — 그대로 두면 "M 0~1.72"가 증거인 척 찍힌다
  assert.equal(machSpan({ mach: [null, 1.72] }), null);
  assert.equal(machSpan({ mach: [0.3, undefined] }), null); // 이쪽은 NaN이 된다
  assert.equal(machSpan({ mach: [] }), null);
  assert.equal(machSpan({}), null);
});
