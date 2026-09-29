// 공통 운용공간 (05 §11) — 기본 격자 응답 → 트림 케이스 · 지도 칸 · 요약 글
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  STATE_MAP_LAYOUT, casesFromBaseGrid, gridMapEntries, parseGridSpec, regionLines, stateCountText, stateMapLayout,
  untrimmedSummary,
} from "./opspace.js";
import {
  EXCLUSION_CATEGORY_LABEL, STATE_REASON_LABEL, TRIM_STATE_CELL, stateEvidenceText, trimCueReport, trimEnvelopeCell,
  marginShortText, trimStateCell, trimStateLabel, verdictEvidenceText, verdictExclusionText,
} from "./plot.js";

const LABELS = { not_run: "미계산", model_gap: "모델 부족", undefined: "요구 미정의" };
const pt = (mach, alt, state = "not_run", fuel = 25) => ({ mach, alt, fuel, name: `M${mach}_h${alt}_f${fuel}`, state });

test("기본 격자 → 케이스: 미계산 점만 트림하고 이름을 그대로 싣는다 — 모델 부족은 보내지 않는다", () => {
  const body = { points: [pt(0.1, 100), pt(0.2, 100), pt(0.95, 100, "model_gap")] };
  assert.deepEqual(casesFromBaseGrid(body), [
    { name: "M0.1_h100_f25", mach: 0.1, alt: 100, fuel: 25 },
    { name: "M0.2_h100_f25", mach: 0.2, alt: 100, fuel: 25 },
  ]);
});

test("지도 칸: 트림 결과 + 트림하지 않은 모델 부족 점 — 결과에 같은 점이 있으면 결과가 이긴다", () => {
  const results = [{ case: { name: "M0.1_h100_f25", mach: 0.1, alt: 100, fuel: 25 }, state: "computable" }];
  const grid = { points: [pt(0.1, 100), pt(0.95, 100, "model_gap")] };
  const entries = gridMapEntries(results, grid);
  assert.equal(entries.length, 2);
  assert.deepEqual(entries.map((e) => trimEnvelopeCell(e.trim).kind), ["computable", "model_gap"]);
  assert.deepEqual(gridMapEntries(results, null).length, 1);
});

test("상태 개수 글 — 있는 상태만, 서버가 준 라벨로", () => {
  assert.equal(stateCountText({ not_run: 30, model_gap: 2 }, LABELS), "미계산 30 · 모델 부족 2");
  assert.equal(stateCountText({}, LABELS), "점 없음");
});

test("요구영역 요약 — 미확정 초안이면 그렇다고 먼저 말한다, 경계표 행을 싣는다", () => {
  const draft = { confirmed: false, source: "draft:trim_grid", mach: [0.14, 0.22], alt: [100, 3000], fuel: [25, 25],
    boundary: null, grid: { n_mach: 5, alts: [100, 3000], fuels: [25] } };
  const d = regionLines(draft, { mach: [0, 0.9], fuel: [0, 50] });
  assert.match(d.status, /미확정/);
  assert.match(d.range, /마하 0\.14–0\.22 · 고도 100–3000 m · 연료 25–25 kg/);
  assert.match(d.model, /DB 마하 0–0\.9 · 연료 0–50 kg/);
  assert.deepEqual(d.boundary, []);
  const conf = { ...draft, confirmed: true, source: "profile",
    boundary: [{ fuel: 10, rows: [[100, 0.1, 0.28], [3000, 0.11, 0.28]] }] };
  const c = regionLines(conf, { mach: null, fuel: [0, 50] });
  assert.match(c.status, /확정/);
  assert.doesNotMatch(c.status, /미확정/);
  assert.match(c.model, /DB 마하 미기재/);
  assert.deepEqual(c.boundary, [{ fuel: 10, alt: 100, lo: 0.1, hi: 0.28 }, { fuel: 10, alt: 3000, lo: 0.11, hi: 0.28 }]);
});

test("격자 명세 칸 → 요청: 빈 칸은 보내지 않는다(영역의 기본 명세), 틀린 칸은 던진다", () => {
  assert.deepEqual(parseGridSpec({ nMach: "", alts: "", fuels: "" }), {});
  assert.deepEqual(parseGridSpec({ nMach: "9", alts: "100, 3000", fuels: "25" }),
    { n_mach: 9, alts: [100, 3000], fuels: [25] });
  assert.throws(() => parseGridSpec({ nMach: "1.5", alts: "", fuels: "" }), /마하 점 수/);
  assert.throws(() => parseGridSpec({ nMach: "", alts: "a", fuels: "" }), /수치 목록/);
});

test("상태 셀: 물리적 불가는 첫 근거를 짧게, 계산 실패·제약 도달은 다른 색", () => {
  assert.equal(trimStateCell({ state: "infeasible", state_reasons: ["throttle_high", "not_converged"] }).text, "추력");
  assert.equal(trimStateCell({ state: "infeasible", state_reasons: ["alpha_margin"] }).text, "실속≈");
  const colors = new Set(["computable", "infeasible", "constraint_hit", "calc_failed", "model_gap"]
    .map((s) => trimStateCell({ state: s }).color));
  assert.equal(colors.size, 5);
  assert.equal(trimStateCell({ state: "nope" }), null);
});

test("여유 판정은 상태와 따로 — 수렴한 여유 미달 해는 계산 가능 안의 다른 칸이고, 새 불가 사유는 짧은 글로", () => {
  const short = { state: "computable", state_reasons: [], margin: { status: "short", reasons: ["throttle_high"] } };
  const met = { state: "computable", state_reasons: [], margin: { status: "met", reasons: [] } };
  assert.equal(trimStateCell(short).kind, "margin_short");
  assert.notEqual(trimStateCell(short).color, trimStateCell(met).color);
  assert.equal(trimStateCell(met).kind, "computable");
  assert.equal(trimStateCell({ state: "computable" }).kind, "computable"); // 옛 결과(margin 없음)는 종전대로
  assert.equal(trimStateCell({ state: "infeasible", state_reasons: ["thrust_deficit", "throttle_high"] }).text, "추력");
  assert.equal(trimStateCell({ state: "infeasible", state_reasons: ["above_stall"] }).text, "실속");
  assert.equal(trimStateLabel(short), `${TRIM_STATE_CELL.computable.label} · 추진 여유 미달`);
  assert.equal(trimStateLabel({ state: "infeasible", state_reasons: ["thrust_deficit"] }), TRIM_STATE_CELL.infeasible.label);
});

test("판정 근거 글 — 한계를 고정해 다시 푼 평형 해의 수치를 싣고, 해가 없으면 그렇다고 말한다", () => {
  const ev = { channel: "throttle_high", fixed: { throttle: 1 }, equation: "vdot", tol: 1e-4,
    solutions: [{ alpha: 0.0525, de: -0.022, throttle: 1, vdot: -0.0066, wdot: 0, qdot: 0, alpha_stall: 0.355,
      below_stall: true }] };
  assert.equal(stateEvidenceText(ev),
    "스로틀 100 % 고정 평형 해 1개 — α 0.0525 · δe -0.022 · V̇ -0.0066 m/s² (실속각 0.355 아래)");
  assert.equal(stateEvidenceText({ ...ev, solutions: [] }), "스로틀 100 % 고정 평형 해 없음");
  assert.match(stateEvidenceText({ ...ev, solutions: [{ ...ev.solutions[0], alpha_stall: null, below_stall: null }] }),
    /\(실속 근거 없음\)$/);
  assert.equal(stateEvidenceText(null), "");
  const deEv = { ...ev, channel: "de_high", fixed: { de: 0.35 }, equation: "qdot",
    solutions: [{ ...ev.solutions[0], de: 0.35, throttle: 0.6, qdot: 0.8 }] };
  assert.match(stateEvidenceText(deEv), /^엘레본 0\.35 rad 고정 평형 해 1개 — α 0\.0525 · 스로틀 0\.6 · q̇ 0\.8 rad\/s²/);
});

test("쇼케이스 보고 — 여유 미달 해는 계산 가능과 따로 센다", () => {
  const row = (name, margin) => ({ case: { name, fuel: 25 }, converged: true, flags: {}, state: "computable",
    margin: { status: margin, reasons: margin === "short" ? ["throttle_high"] : [] } });
  assert.equal(trimCueReport([row("a", "met"), row("b", "short"), row("c", "short")]).summary,
    `3 케이스 — ${TRIM_STATE_CELL.computable.label} 1 · ${TRIM_STATE_CELL.margin_short.label} 2`);
});

test("쇼케이스 보고 — 상태가 실린 결과는 상태 라벨로 센다(계산 가능은 0이어도 적는다)", () => {
  const row = (name, state) => ({ case: { name, fuel: 25 }, converged: state === "computable", flags: {}, state });
  const r = trimCueReport([row("a", "computable"), row("b", "infeasible"), row("c", "calc_failed")]);
  assert.equal(r.summary,
    `3 케이스 — ${TRIM_STATE_CELL.computable.label} 1 · ${TRIM_STATE_CELL.infeasible.label} 1 · `
    + `${TRIM_STATE_CELL.calc_failed.label} 1`);
  assert.equal(trimCueReport([row("b", "infeasible")]).summary,
    `1 케이스 — ${TRIM_STATE_CELL.computable.label} 0 · ${TRIM_STATE_CELL.infeasible.label} 1`);
});

test("상태 지도 배치 — 가로는 실제 마하(끝점이 공통 좌표 사이에 떨어진다), 요구 띠는 행 범위, 미정의 행은 띠 없이", () => {
  const rows = [{ alt: 100, fuel: 25, bounds: [0.10375, 0.28] }, { alt: 3000, fuel: 25, bounds: [0.1175, 0.28] },
    { alt: 5000, fuel: 25, bounds: null, state: "undefined" }, { alt: 100, fuel: 50, bounds: [0.11, 0.28] }];
  const e = (mach, alt, fuel = 25) => ({ trim: { case: { mach, alt, fuel }, state: "computable" } });
  const L = stateMapLayout({ rows, entries: [e(0.10375, 100), e(0.12, 100), e(0.14, 100), e(0.1175, 3000), e(0.2, 100, 50)],
    machRange: [0.1, 0.28], fuel: 25, width: 600 });
  assert.deepEqual(L.alts, [100, 3000, 5000]);
  // 등간격 열이었다면 0.10375→0.12와 0.12→0.14가 같은 폭이다 — 실제 마하 간격을 따른다
  const [a, b, c] = L.dots.filter((d) => d.y === L.rowY(100)).map((d) => d.x);
  assert.ok(b - a < c - b);
  assert.ok(L.rowY(3000) < L.rowY(100), "고도는 위로 증가");
  assert.equal(L.bands.length, 3, "연료 25 kg 행만");
  assert.deepEqual(L.bands.find((x) => x.alt === 5000), { alt: 5000, x0: null, x1: null, undefined: true });
  const b100 = L.bands.find((x) => x.alt === 100);
  assert.equal(b100.x0, L.x(0.10375));
  assert.equal(L.height, STATE_MAP_LAYOUT.mT + 3 * STATE_MAP_LAYOUT.rowH + STATE_MAP_LAYOUT.mB);
  assert.ok(L.x(0.1) > STATE_MAP_LAYOUT.mL && L.x(0.28) < 600 - STATE_MAP_LAYOUT.mR, "영역 끝이 여백 안");
});

test("트림하지 않은 것 — 모델 부족 점과 점 없는 행이 보고·머리줄에서 사라지지 않는다", () => {
  const grid = { labels: { model_gap: "모델 부족", undefined: "요구 미정의", out_of_region: "요구영역 밖" },
    points: [pt(0.2, 100), pt(0.95, 100, "model_gap"), pt(1.0, 100, "model_gap")],
    rows: [{ alt: 100, fuel: 25, state: "not_run" }, { alt: 3000, fuel: 25, state: "undefined" }] };
  const u = untrimmedSummary(grid);
  assert.equal(u.modelGap, 2);
  assert.deepEqual(u.rows, [{ alt: 3000, fuel: 25, state: "undefined" }]);
  assert.equal(u.text, "트림하지 않음 — 모델 부족 2점 · 점 없는 행 1 (3000 m·25 kg 요구 미정의)");
  assert.equal(untrimmedSummary({ points: [pt(0.2, 100)], rows: [] }).text, null);
  // 보고: 결과 행은 상태로 세고, 모델 부족 수는 격자에서 — 0으로 두지 않는다, 두 번 세지 않는다
  const row = { case: { name: "a", fuel: 25 }, converged: true, flags: {}, state: "computable" };
  const r = trimCueReport([row], u);
  assert.equal(r.data.counts.model_gap, 2);
  assert.equal(r.summary, `1 케이스 — ${TRIM_STATE_CELL.computable.label} 1 · ${u.text}`);
  assert.deepEqual(r.data.untrimmed, { model_gap: 2, rows: u.rows });
});

// 조건 판정(05 §11.3 · 이관 8단계) — 서버 /trim/batch가 결과마다 싣는 verdict 모양 그대로
const verdict = (exclusion, over = {}) => ({
  trim: { status: "computable", reasons: [] }, model: { status: "valid", reasons: [] },
  limits: { status: "met", reasons: [] }, margin: { status: "met", reasons: [] }, region: null,
  adopted: exclusion == null, exclusion, ...over,
});
const judged = (exclusion, over) => ({ case: { name: "a", fuel: 25 }, converged: true, flags: {}, state: "computable",
  state_reasons: [], margin: { status: "met", reasons: [] }, verdict: verdict(exclusion, over) });

test("조건 판정이 실린 결과: 채택은 계산 가능(여유 미달은 채택된 채 다른 칸), 제외는 항목별 칸 — 제한 위반·모델 범위 밖", () => {
  assert.equal(trimStateCell(judged(null)).kind, "computable");
  const lim = judged({ category: "limits", reasons: ["stall_boundary"] },
    { limits: { status: "violated", reasons: ["stall_boundary"] } });
  assert.deepEqual(trimStateCell(lim), { kind: "limit_violation", color: TRIM_STATE_CELL.limit_violation.color,
    text: "제한" });
  assert.equal(trimStateLabel(lim), "계산 가능 · 실속 경계 위반");
  const mod = judged({ category: "model", reasons: ["db_alpha"] }, { model: { status: "gap", reasons: ["db_alpha"] } });
  assert.equal(trimStateCell(mod).kind, "model_invalid");
  assert.equal(trimStateLabel(mod), "계산 가능 · DB 받음각 범위 밖");
  // 여유 미달은 채택된 채 표시된다(v1.65) — 여유 사유 글로(스로틀 상한 판정선은 추진 여유다), 제외 근거 글은 없다
  const mar = judged(null, { margin: { status: "short", reasons: ["throttle_high"] } });
  assert.deepEqual(trimStateCell(mar), { kind: "margin_short", color: TRIM_STATE_CELL.margin_short.color,
    text: TRIM_STATE_CELL.margin_short.text });
  assert.equal(trimStateLabel(mar), "계산 가능 · 추진 여유 미달");
  assert.equal(verdictEvidenceText(mar), "");
  assert.equal(marginShortText(mar), "추진 여유 미달");
  // 칸 색은 모두 다르다 — 트림하지 않은 model_gap과 트림한 모델 범위 밖도
  const kinds = ["computable", "limit_violation", "model_invalid", "margin_short", "model_gap", "infeasible", "unevaluated"];
  assert.equal(new Set(kinds.map((k) => TRIM_STATE_CELL[k].color)).size, kinds.length);
});

test("조건 판정: 잴 근거가 없는 제한은 위반이 아니라 판정 미완료, 트림 항목 제외는 조건 상태 규칙 그대로", () => {
  const unev = judged({ category: "limits", reasons: ["stall_basis_missing"] },
    { limits: { status: "unevaluated", reasons: ["stall_basis_missing"] } });
  assert.equal(trimStateCell(unev).kind, "unevaluated");
  assert.equal(trimStateLabel(unev), `계산 가능 · ${STATE_REASON_LABEL.stall_basis_missing}`);
  const inf = { state: "infeasible", state_reasons: ["thrust_deficit", "throttle_high"],
    verdict: verdict({ category: "trim", reasons: ["thrust_deficit", "throttle_high"] },
      { trim: { status: "infeasible", reasons: ["thrust_deficit", "throttle_high"] } }) };
  assert.deepEqual(trimStateCell(inf), { kind: "infeasible", color: TRIM_STATE_CELL.infeasible.color, text: "추력" });
  assert.equal(trimStateLabel(inf), TRIM_STATE_CELL.infeasible.label);
  assert.equal(verdictEvidenceText(inf), "", "트림 항목 사유는 상태 근거가 이미 말한다");
  // 판정이 여유 미달을 말하지 않으면 옛 margin 필드로 여유 미달을 만들지 않는다 — 판정이 정본
  const adoptedButOldShort = { ...judged(null), margin: { status: "short", reasons: ["throttle_high"] } };
  assert.equal(trimStateCell(adoptedButOldShort).kind, "computable");
  assert.equal(trimStateLabel(adoptedButOldShort), TRIM_STATE_CELL.computable.label);
});

test("조건 판정 근거 글 — 채택하지 않은 까닭을 항목 이름과 사유로, 채택·옛 결과는 빈 글", () => {
  const lim = judged({ category: "limits", reasons: ["stall_boundary", "q_max"] },
    { limits: { status: "violated", reasons: ["stall_boundary", "q_max"] } });
  assert.equal(verdictExclusionText(lim), "실속 경계 위반 · 최대 동압 초과");
  assert.equal(verdictEvidenceText(lim), "자동 설계 제외 (제한 위반) — 실속 경계 위반 · 최대 동압 초과");
  assert.equal(verdictEvidenceText(judged(null)), "");
  assert.equal(verdictEvidenceText({ state: "computable" }), "");
  // 여유는 제외 항목이 아니다(v1.65 채택 정책)
  // 요구영역 항목(이관 2단계 — 트림하지 않은 점의 판정)이 맨 앞: 엔진 항목 순서
  assert.deepEqual(Object.keys(EXCLUSION_CATEGORY_LABEL), ["region", "trim", "model", "limits"]);
  for (const c of ["stall_boundary", "limiter_clips_trim", "q_max", "mach_no", "db_mach", "db_alpha", "fuel_range",
    "stall_basis_missing", "out_of_region", "undefined", "model_gap"]) assert.ok(STATE_REASON_LABEL[c], c);
});

test("α 리미터 제외 — 작동식이 트림을 못 쥐는 수치(limits.detail.limiter)를 근거 글에 싣는다", () => {
  const limiter = { alpha_trim: 0.34123, alpha_max: 0.33491, law: "theta_cmd <= theta + (alpha_max - alpha)" };
  const lim = judged({ category: "limits", reasons: ["limiter_clips_trim"] },
    { limits: { status: "violated", reasons: ["limiter_clips_trim"], detail: { limiter } } });
  assert.equal(trimStateCell(lim).kind, "limit_violation");
  assert.equal(verdictExclusionText(lim), "α 리미터가 트림을 유지하지 못함 — α_trim 0.341 > α_max 0.335");
  assert.equal(verdictEvidenceText(lim),
    "자동 설계 제외 (제한 위반) — α 리미터가 트림을 유지하지 못함 — α_trim 0.341 > α_max 0.335");
  assert.equal(trimStateLabel(lim), "계산 가능 · α 리미터가 트림을 유지하지 못함 — α_trim 0.341 > α_max 0.335");
  // 근거 수치가 없는 결과는 사유 글만
  const bare = judged({ category: "limits", reasons: ["limiter_clips_trim", "q_max"] },
    { limits: { status: "violated", reasons: ["limiter_clips_trim", "q_max"] } });
  assert.equal(verdictExclusionText(bare), "α 리미터가 트림을 유지하지 못함 · 최대 동압 초과");
});

test("판정 없는 옛 결과는 종전대로 — margin 필드로 여유 미달, 없으면 계산 가능", () => {
  const old = { state: "computable", state_reasons: [], margin: { status: "short", reasons: ["de"] } };
  assert.equal(trimStateCell(old).kind, "margin_short");
  assert.equal(trimStateLabel(old), "계산 가능 · 엘레본 여유 미달");
  assert.equal(verdictExclusionText(old), "");
  assert.equal(trimStateCell({ state: "computable" }).kind, "computable");
  assert.equal(trimStateLabel({ state: "computable" }), TRIM_STATE_CELL.computable.label);
});

test("쇼케이스 보고 — 조건 판정 칸으로 센다, 옛 결과(판정 없음)는 종전대로", () => {
  const lim = judged({ category: "limits", reasons: ["limiter_clips_trim"] },
    { limits: { status: "violated", reasons: ["limiter_clips_trim"] } });
  const mod = judged({ category: "model", reasons: ["db_mach"] }, { model: { status: "gap", reasons: ["db_mach"] } });
  const short = judged(null, { margin: { status: "short", reasons: ["throttle_high"] } });
  const r = trimCueReport([judged(null), short, lim, lim, mod]);
  assert.equal(r.summary, `5 케이스 — ${TRIM_STATE_CELL.computable.label} 1 · ${TRIM_STATE_CELL.margin_short.label} 1 · `
    + `${TRIM_STATE_CELL.limit_violation.label} 2 · ${TRIM_STATE_CELL.model_invalid.label} 1`);
  assert.equal(r.data.counts.limit_violation, 2);
  const old = { case: { name: "o", fuel: 25 }, converged: true, flags: {}, state: "computable",
    margin: { status: "short", reasons: ["throttle_high"] } };
  assert.equal(trimCueReport([old]).summary,
    `1 케이스 — ${TRIM_STATE_CELL.computable.label} 0 · ${TRIM_STATE_CELL.margin_short.label} 1`);
});
