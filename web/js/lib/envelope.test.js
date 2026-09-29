/** 엔벨로프 lib 검증 — 다각형 조립·구간 병합·판정 셀 분류·프리필 판단 (01 §2.6). */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  boundColor, boundLabel, boundarySegments, capLabel, dbLoBinds, envelopeQuery, ftToM, isoLabelIndex,
  isoOffWindow, kindColor, kindLabel, machSpan, machWindow, mToFt, msToKt, optNum, outlineCaps,
  limitSourceLabel, opsSourceLabel, outsideRegion, prefillValue, regionPolygons, scanCells, scanCueSummary,
  scanSummary, spreadLabels, tasAxisTicks, throttleCell, thrustFrontier, vnCueReport,
  boxOverlap, lineLabelCandidates, placeLabels, pointObstacles, textBox,
} from "./envelope.js";
import { linScale } from "./plot.js";

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
  // 조건 판정 사유(이관 8단계 — 엔진이 종전 사유 뒤에 덧붙인다)도 사람 글로, 트림 탭과 같은 말
  assert.equal(kindLabel("stall_boundary"), "실속 경계 위반");
  assert.equal(kindLabel("db_alpha"), "DB 받음각 범위 밖");
  assert.equal(kindLabel("throttle_high"), "추진 여유 미달");
  for (const k of ["limiter_clips_trim", "q_max", "mach_no", "db_mach", "fuel_range", "stall_basis_missing",
    "throttle_low", "de"]) assert.notEqual(kindLabel(k), k, k);
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

test("scanCells — 채택됐지만 여유 미달인 칸은 트림 탭처럼 따로 — 초록 「제어 가능」으로 칠하지 않는다", () => {
  // 스로틀 95 % 등고선 밖에서 수렴한 해 — 채택(ok)이고 종전 사유 saturated_throttle_high가 남는다(추력 전선이 그것을 본다)
  const e = entry(0.6, 1000, true, ["saturated_throttle_high"]);
  e.verdict.verdict = { adopted: true, exclusion: null, margin: { status: "short", reasons: ["throttle_high"] } };
  const [c] = scanCells([e]);
  assert.equal(c.ok, true);
  assert.equal(c.kind, "ok_margin_short");
  assert.notEqual(kindColor("ok_margin_short"), kindColor("ok"));
  // 요약: 채택 수에 포함하고, 그중 여유 미달을 따로 센다(실패 목록이 아니다)
  const s = scanSummary([c, { kind: "ok", ok: true }, { kind: "not_converged", ok: false }]);
  assert.equal(s.ok, 2);
  assert.deepEqual(s.byKind, [{ kind: "ok_margin_short", n: 1 }, { kind: "not_converged", n: 1 }]);
  assert.match(scanCueSummary(s), /여유 미달 \(채택\) 1/);
});

test("scanCells — 채택 제외 칸의 대표는 판정의 제외 사유다 — 종전 사유 첫 항목(α 여유)이 아니라", () => {
  // 실속 근처 리미터 제외 — 종전 사유는 alpha_margin이 먼저 오지만 v1.65에서 여유는 채택을 막지 않는다. 트림 탭처럼
  // 「제한 위반 — α 리미터」로 말해야 한다
  const e = entry(0.12, 3000, false, ["alpha_margin", "limiter_clips_trim"]);
  e.verdict.verdict = { adopted: false, exclusion: { category: "limits", reasons: ["limiter_clips_trim"] },
    margin: { status: "short", reasons: ["alpha_margin"] } };
  const [c] = scanCells([e]);
  assert.equal(c.kind, "limiter_clips_trim");
  assert.deepEqual(c.reasons, ["alpha_margin", "limiter_clips_trim"]); // 전량은 그대로(추력 전선이 본다)
  // 옛 결과(판정 없음)는 종전대로 첫 사유
  assert.equal(scanCells([entry(0.12, 3000, false, ["alpha_margin"])])[0].kind, "alpha_margin");
  // 트림 범주 — 물리적 불가면 근거 사유(추력 부족), 그 밖은 트림 상태. 채널 코드(throttle_high)를 대표로 쓰면 스캔 표의
  // 「추진 여유 미달」 글이 붙어 뜻이 틀린다
  const trimEx = (status, reasons) => {
    const t = entry(0.7, 100, false, ["not_converged", "saturated_throttle_high"], { converged: false });
    t.verdict.verdict = { adopted: false, trim: { status, reasons }, exclusion: { category: "trim", reasons } };
    return scanCells([t])[0];
  };
  assert.equal(trimEx("infeasible", ["thrust_deficit", "throttle_high"]).kind, "thrust_deficit");
  assert.equal(trimEx("constraint_hit", ["throttle_high", "not_converged", "balance_not_found"]).kind, "constraint_hit");
  assert.equal(trimEx("unassessed", ["not_converged"]).kind, "unassessed");
  assert.match(kindLabel("thrust_deficit"), /추력 부족/);
  assert.match(kindLabel("constraint_hit"), /제약 도달/);
});

test("scanSummary — 조건 판정 사유는 종전 사유 뒤, 판정 항목 순(모델 → 제한 → 여유)", () => {
  const s = scanSummary([{ kind: "throttle_high" }, { kind: "stall_boundary" }, { kind: "db_mach" },
    { kind: "alpha_margin" }]);
  assert.deepEqual(s.byKind.map((b) => b.kind), ["alpha_margin", "db_mach", "stall_boundary", "throttle_high"]);
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

test("limitSourceLabel — 구조 한계 출처: 덮은 칸만 사용자 입력, 나머지는 기체가 예제인지로 가린다", () => {
  assert.equal(limitSourceLabel("mach_no", "profile", []).text, "기체 문서");
  assert.equal(limitSourceLabel("mach_no", "demo-placeholder", []).text, "데모 자리표시");
  assert.equal(limitSourceLabel("mach_no", "demo-placeholder", []).ok, false);
  // user-input은 응답 전체의 표지다 — 덮지 않은 칸은 그 기체의 값(예제면 자리표시)
  assert.equal(limitSourceLabel("mach_d", "user-input", ["mach_d"], false).text, "사용자 입력");
  assert.equal(limitSourceLabel("mach_no", "user-input", ["mach_d"], false).text, "기체 문서");
  assert.equal(limitSourceLabel("mach_no", "user-input", ["mach_d"], true).text, "데모 자리표시");
  // 예제인지 모르면(구 응답) 자리표시 쪽으로 — 가짜를 진짜라고 말하지 않는다
  assert.equal(limitSourceLabel("mach_no", "user-input", ["mach_d"]).text, "데모 자리표시");
});

test("opsSourceLabel — 동압·운용 고도 출처: bounds_source가 profile이면 문서, 값이 없으면 경계 없음", () => {
  assert.deepEqual(opsSourceLabel(3000, "profile"), { text: "기체 문서", ok: true });
  assert.deepEqual(opsSourceLabel(3000, "query"), { text: "사용자 입력", ok: true });
  // 서버는 문서 값을 쓴 응답에만 bounds_source를 싣는다 — 없는데 값이 있으면 질의 값이다
  assert.equal(opsSourceLabel(4000, undefined).text, "사용자 입력");
  assert.deepEqual(opsSourceLabel(null, null), { text: "미입력 — 경계 없음", ok: false });
});

test("vnCueReport — 그린 고도·문서 한계를 진행기 계약 모양으로, 없는 경계는 없다고", () => {
  const mh = {
    bounds: { q_max: 3000, alt_min: 0, alt_max: 4000 },
    bounds_source: { q_max: "profile", alt_min: "profile", alt_max: "profile" },
    maneuver: null,
  };
  const r = vnCueReport([{ alt: 0 }, { alt: 1500 }, { alt: 3000 }], mh);
  assert.deepEqual(r.data, {
    alts: [0, 1500, 3000], q_max: 3000, alt_min: 0, alt_max: 4000,
    bounds_source: mh.bounds_source, nz: null,
  });
  assert.equal(r.summary, "V-n 3고도(0 m · 1500 m · 3000 m) · q̄_max 3000 Pa · 운용 고도 0~4000 m");
  const bare = vnCueReport([{ alt: 1000 }], { bounds: { q_max: null, alt_min: null, alt_max: null },
    maneuver: { nz: 3 } });
  assert.equal(bare.summary, "V-n 1고도(1000 m) · q̄_max 경계 없음 · 운용 고도 경계 없음 · 기동 n_z 3 g");
  assert.deepEqual([bare.data.q_max, bare.data.bounds_source, bare.data.nz], [null, null, 3]);
});

test("scanCueSummary — 판정 집계를 범례 라벨 그대로 한 줄로 (엔진 우선순위 순)", () => {
  const cells = scanCells([
    { trim: { case: { mach: 0.1, alt: 0, fuel: 25 } }, verdict: { ok: true, reasons: [] } },
    { trim: { case: { mach: 0.08, alt: 0, fuel: 25 } }, verdict: { ok: false, reasons: ["not_converged"] } },
    { trim: { case: { mach: 0.3, alt: 0, fuel: 25 } },
      verdict: { ok: false, reasons: ["saturated_throttle_high"] } },
  ]);
  assert.equal(scanCueSummary(scanSummary(cells)),
    `3점 — ${kindLabel("ok")} 1 · ${kindLabel("not_converged")} 1 · ${kindLabel("saturated_throttle_high")} 1`);
});

// ── 라벨 겹침 없는 배치 (쇼케이스 D10 — V-n·M-h 라벨이 서로·판정 점 밑에 깔렸다) ────────────────

test("textBox — fillText 기준점·정렬 → 글 상자 (기준선 위 0.85·아래 0.25 글자 크기)", () => {
  assert.deepEqual(textBox(10, 50, 40, 10, "left"), { x0: 10, y0: 41.5, x1: 50, y1: 52.5 });
  assert.deepEqual(textBox(50, 50, 40, 10, "right"), { x0: 10, y0: 41.5, x1: 50, y1: 52.5 });
  assert.deepEqual(textBox(30, 50, 40, 10, "center"), { x0: 10, y0: 41.5, x1: 50, y1: 52.5 });
  assert.equal(boxOverlap(textBox(0, 10, 10, 10), textBox(20, 10, 10, 10)), 0);
  assert.equal(boxOverlap({ x0: 0, y0: 0, x1: 10, y1: 10 }, { x0: 5, y0: 5, x1: 15, y1: 15 }), 25);
});

const BOUNDS = { x0: 0, y0: 0, x1: 200, y1: 100 };
const lab = (key, candidates, extra = {}) => ({ key, w: 40, size: 10, candidates, ...extra });

test("placeLabels — 같은 자리를 원하면 뒤 라벨이 다음 후보로 · 우선순위(입력 순서)가 자리를 먼저 잡는다", () => {
  const a = { x: 10, y: 20, align: "left" };
  const b = { x: 10, y: 40, align: "left" };
  const out = placeLabels([lab("A", [a, b]), lab("B", [a, b])], { bounds: BOUNDS });
  assert.deepEqual(out.map((o) => [o.key, o.y, o.fits]), [["A", 20, true], ["B", 40, true]]);
  assert.equal(boxOverlap(out[0].box, out[1].box), 0);
});

test("placeLabels — 틀 밖(오른쪽 끝에서 잘림) 후보는 건너뛴다: 선 왼쪽으로 뒤집은 후보를 쓴다", () => {
  // V_D 라벨 — 선 오른쪽에 두면 틀을 넘어 「V_D 10…」로 잘렸다
  const out = placeLabels([lab("VD", [{ x: 190, y: 20, align: "left" }, { x: 186, y: 20, align: "right" }])],
    { bounds: BOUNDS });
  assert.equal(out[0].align, "right");
  assert.ok(out[0].box.x1 <= BOUNDS.x1);
});

test("placeLabels — 장애물(판정 점)과 겹치는 후보는 건너뛴다 · pad만큼 떨어져야 한다", () => {
  const dot = { x0: 48, y0: 14, x1: 54, y1: 20 };
  const out = placeLabels([lab("T", [{ x: 10, y: 20, align: "left" }, { x: 10, y: 60, align: "left" }])],
    { bounds: BOUNDS, obstacles: [dot] });
  assert.equal(out[0].y, 60);
  // pad — 상자와 1 px 떨어진 점도 pad 2 안이면 겹친 것으로 본다
  const near = { x0: 51, y0: 14, x1: 55, y1: 20 };
  const out2 = placeLabels([lab("T", [{ x: 10, y: 20, align: "left" }, { x: 10, y: 60, align: "left" }])],
    { bounds: BOUNDS, obstacles: [near] });
  assert.equal(out2[0].y, 60);
});

test("placeLabels — 영역(region)·accept를 만족하는 후보만 (구역 이름은 그 구역 안에)", () => {
  const out = placeLabels([lab("Z", [{ x: 10, y: 20 }, { x: 10, y: 80 }], {
    region: { x0: 0, y0: 50, x1: 200, y1: 100 },
  })], { bounds: BOUNDS });
  assert.equal(out[0].y, 80);
  const acc = placeLabels([lab("Z", [{ x: 10, y: 20 }, { x: 100, y: 20 }], {
    accept: (box) => box.x0 >= 100,
  })], { bounds: BOUNDS });
  assert.equal(acc[0].x, 100);
});

test("placeLabels — 다 막히면: optional은 뺀다(범례가 이름을 갖는다) · 필수는 겹침 최소 후보를 틀 안으로 밀어 쓴다", () => {
  const block = { x0: 0, y0: 0, x1: 200, y1: 100 };
  const out = placeLabels([
    lab("opt", [{ x: 10, y: 20 }], { optional: true }),
    lab("must", [{ x: 190, y: 20, align: "left" }], {}),
  ], { bounds: BOUNDS, obstacles: [block] });
  assert.equal(out[0].skipped, true);
  assert.equal(out[1].fits, false);
  assert.equal(out[1].skipped, false);
  assert.ok(out[1].box.x1 <= BOUNDS.x1, "틀 밖으로 잘리지 않게 밀어 넣는다");
  assert.equal(out[1].box.x1 - out[1].box.x0, 40);
});

test("pointObstacles — 점 → 반지름 상자 (판정 점·격자점을 라벨이 피할 장애물로)", () => {
  assert.deepEqual(pointObstacles([{ x: 10, y: 20 }], 3), [{ x0: 7, y0: 17, x1: 13, y1: 23 }]);
});

// 실측 재현 — 쇼케이스 V-n 3000 m 장(480×330): V_NO 78.86·V_A 82.51 m/s가 12 px 거리라 라벨이 포개졌고, V_D는
// 오른쪽 끝에서 잘렸고, +극한하중 라벨이 V_S 라벨 줄에 앉았다. 후보 생성 + 배치로 셋 다 풀려야 한다
test("V-n 실측 배치 — 속도·하중 라벨이 서로 안 겹치고 틀 안에 선다 (쇼케이스 3000 m 장)", () => {
  const W = 480, H = 330, mL = 52, mT = 30, mR = 16, mB = 40;
  const L = { n_limit_pos: 6, n_limit_neg: -3, n_ultimate_pos: 9, n_ultimate_neg: -4.5, v_no: 78.86, v_d: 98.57 };
  const V0 = 6.57;
  const px = linScale(V0, L.v_d * 1.08, mL, W - mR);
  const py = linScale(L.n_ultimate_neg * 1.15, L.n_ultimate_pos * 1.1, H - mB, mT);
  const plot = { x0: mL, y0: mT, x1: W - mR, y1: H - mB };
  const width = (t) => t.length * 6.2; // 11 px 글꼴의 대략 폭 — 뷰는 ctx.measureText로 잰다
  const speeds = { vs: 33.76, va: 82.51, vno: 78.86, vd: 98.57 };
  const bar = (v) => ({ x0: px(v) - 0.5, y0: mT, x1: px(v) + 0.5, y1: H - mB });
  // 속도선 이름은 **다른** 속도선을 가로지르지 않는다(뷰가 그 선들을 avoid로 준다)
  const mk = (key, text, kind, at) => ({
    key, w: width(text), size: 11,
    candidates: lineLabelCandidates(kind, at, { plot, px, py, xEnd: px(L.v_d) }),
    avoid: kind === "v" ? Object.values(speeds).filter((v) => v !== at).map(bar) : [],
  });
  const labels = [
    mk("vs", "V_S 33.76", "v", 33.76), mk("va", "V_A 82.51", "v", 82.51),
    mk("vno", "V_NO 78.86", "v", 78.86), mk("vd", "V_D 98.57", "v", 98.57),
    mk("ult+", "+극한하중 9 g (제한×1.5)", "h", 9), mk("lim+", "+제한하중 6 g", "h", 6),
    mk("lim-", "−제한하중 −3 g", "h", -3), mk("ult-", "−극한하중 −4.5 g", "h", -4.5),
    mk("n1", "n=1 수평비행", "h", 1),
  ];
  const out = placeLabels(labels, { bounds: plot });
  for (const o of out) {
    assert.ok(o.fits, `${o.key}가 자리를 못 찾았다`);
    assert.ok(o.box.x0 >= plot.x0 && o.box.x1 <= plot.x1 && o.box.y0 >= plot.y0 && o.box.y1 <= plot.y1,
      `${o.key}가 틀 밖(잘림): ${JSON.stringify(o.box)}`);
  }
  for (let i = 0; i < out.length; i += 1) {
    for (let j = i + 1; j < out.length; j += 1) {
      assert.equal(boxOverlap(out[i].box, out[j].box), 0, `${out[i].key} ↔ ${out[j].key} 겹침`);
    }
  }
  // 속도 라벨은 제 선 곁에 선다 — 선과 글 사이가 멀어지면 어느 선의 이름인지 잃는다
  const byKey = Object.fromEntries(out.map((o) => [o.key, o]));
  for (const [k, v] of [["vs", 33.76], ["va", 82.51], ["vno", 78.86], ["vd", 98.57]]) {
    const b = byKey[k].box;
    assert.ok(Math.min(Math.abs(b.x0 - px(v)), Math.abs(b.x1 - px(v))) <= 4, `${k} 라벨이 선에서 떨어졌다`);
  }
  // V_D는 오른쪽 끝이라 선 왼쪽으로 뒤집힌다
  assert.equal(byKey.vd.align, "right");
  for (const k of Object.keys(speeds)) {
    for (const [k2, v2] of Object.entries(speeds)) {
      const b = byKey[k].box;
      if (k !== k2) assert.ok(!(b.x0 < px(v2) && b.x1 > px(v2)), `${k} 이름이 ${k2} 선(${v2})을 가로지른다`);
    }
  }
});

test("lineLabelCandidates — 가로선은 선 바로 위·아래(왼쪽 끝·오른쪽 끝·가운데), 세로선은 위·아래 줄의 좌우", () => {
  const plot = { x0: 0, y0: 0, x1: 200, y1: 100 };
  const id = (v) => v;
  const h = lineLabelCandidates("h", 50, { plot, px: id, py: id, xEnd: 180 });
  assert.deepEqual(h[0], { x: 6, y: 46, align: "left" }); // 종전 자리(왼쪽 위)가 첫 후보
  assert.ok(h.some((c) => c.align === "right" && c.x === 174));
  assert.ok(h.every((c) => Math.abs(c.y - 50) <= 13));
  const v = lineLabelCandidates("v", 120, { plot, px: id, py: id });
  assert.deepEqual(v[0], { x: 123, y: 12, align: "left" }); // 종전 자리(선 오른쪽 윗줄)가 첫 후보
  assert.deepEqual(v[1], { x: 117, y: 12, align: "right" });
  assert.ok(v.some((c) => c.y > 50), "아래 줄 후보도 있다");
});
