/** 엔벨로프 lib 검증 — 다각형 조립·구간 병합·판정 셀 분류·프리필 판단 (01 §2.6). */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  boundColor, boundLabel, boundarySegments, envelopeQuery, kindColor, kindLabel,
  optNum, prefillValue, regionPolygons, scanCells, scanSummary, throttleCell,
} from "./envelope.js";

const region = (rows) => ({
  alt: rows.map((r) => r[0]),
  mach_lo: rows.map((r) => r[1]),
  mach_hi: rows.map((r) => r[2]),
  lo_source: rows.map((r) => r[3]),
  hi_source: rows.map((r) => r[4]),
  empty: rows.map((r) => r[5] ?? false),
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
