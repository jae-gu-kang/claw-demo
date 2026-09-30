// 결과 브리핑 모델 — 정해진 양식(머리·종합 판정·절)이 종류마다 결정적으로 나온다
import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";

import { briefModel, jsonPreview, kindDetail, kindLabel } from "./resultbrief.js";
import { GOHEUNG } from "./site.js";

const META = {
  id: "r1", kind: "trim_batch", created: 1758240000, n: 3,
  profile: { id: "example-delta", name: "예제 델타윙", revision: 1, fingerprint: "f".repeat(16) },
  fingerprint: "web-trim-v1",
};

const trimRow = (name, mach, alt, fuel, { converged = true, bad = null } = {}) => ({
  case: { name, mach, alt, fuel },
  converged,
  euler: [0, 0.05, 0],
  control: { elevon: [-0.01, -0.01], throttle: [0.5, 0.5] },
  flags: { residual_ok: converged, saturation_ok: bad !== "saturation_ok",
    alpha_margin_ok: bad !== "alpha_margin_ok", continuity_ok: true },
});

test("kindLabel: 아는 코드는 우리말, 모르는 코드는 그대로 — 뭉개지 않는다", () => {
  assert.equal(kindLabel("trim_batch"), "트림 배치");
  assert.equal(kindLabel("brand_new_kind"), "brand_new_kind");
});

test("kindDetail: 처방 결과는 목적을 덧붙인다 — 옛 결과(목적 없음)·다른 종류는 빈칸", () => {
  assert.equal(kindDetail({ kind: "influence_prescribe", objective: "performance" }), "성능 개선");
  assert.equal(kindDetail({ kind: "influence_prescribe", objective: "min_change" }), "기준 충족 최소 수정");
  assert.equal(kindDetail({ kind: "influence_prescribe" }), null);
  assert.equal(kindDetail({ kind: "sim", objective: "performance" }), null);
  const head = briefModel({ id: "p1", kind: "influence_prescribe", objective: "performance" }, {}).head;
  assert.match(head.find(([k]) => k === "종류")[1], /성능 개선/);
});

test("트림 배치 — 수렴·판정 위반 집계와 격자 범위, 위반 케이스 목록", () => {
  const body = { kind: "trim_batch", results: [
    trimRow("a", 0.2, 0, 200),
    trimRow("b", 0.3, 1000, 200, { bad: "alpha_margin_ok" }),
    trimRow("c", 0.4, 1000, 400, { converged: false }),
  ] };
  const m = briefModel(META, body);
  assert.ok(m.head.some(([k, v]) => k === "기체" && v.includes("예제 델타윙")));
  assert.equal(m.verdict.tone, "bad");
  assert.match(m.verdict.text, /수렴 2\/3/);
  assert.match(m.verdict.text, /판정 위반 1건/);
  const grid = m.sections.find((s) => s.title.includes("격자"));
  assert.ok(grid.rows.some(([k, v]) => k.includes("마하") && v.includes("0.2") && v.includes("0.4")));
  const badSec = m.sections.find((s) => s.title.includes("위반"));
  assert.ok(badSec.rows.some(([k, v]) => k === "b" && v.includes("α여유")));
  assert.ok(badSec.rows.some(([k, v]) => k === "c" && v.includes("미수렴")));
});

test("트림 배치 — 전 케이스 통과면 verdict가 ok다", () => {
  const body = { kind: "trim_batch", results: [trimRow("a", 0.2, 0, 200)] };
  assert.equal(briefModel(META, body).verdict.tone, "ok");
});

test("마진 맵 — 루프별 최악 PM·GM(∞·판정 불가 구분)과 비행성 수준 최악(fq 재사용)", () => {
  const caseOf = (name, pm, gm, spiralLevel, t2) => ({
    trim: { case: { name, mach: 0.4, alt: 1000, fuel: 200 }, converged: true },
    lon: { fq: { short_period: { level: 1, zeta: 0.5 }, phugoid: { level: 1, zeta: 0.06 } } },
    lat: { fq: { dutch_roll: { level: 1, zeta: 0.2, wn: 2, zwn: 0.4 },
      roll: { level: 1, tau_s: 0.5 },
      spiral: { level: spiralLevel, stable: false, t2_s: t2 } } },
    margins: { pitch_q: { pm_deg: pm, gm_db: gm } },
  });
  const body = {
    kind: "margin_map",
    loops: [{ name: "pitch_q" }],
    cases: [caseOf("m1", 62.1, "inf", 1, 25.0), caseOf("m2", 41.3, 7.2, 2, 14.0)],
    fq_criteria: { fingerprint: "abcd" },
    actuator: { wn: 60, zeta: 0.7 }, delay_s: 0.02, pade_order: 2,
  };
  const m = briefModel({ ...META, kind: "margin_map" }, body);
  const loopSec = m.sections.find((s) => s.title.includes("루프"));
  const pmRow = loopSec.rows.find(([k]) => k.includes("pitch_q"));
  assert.match(pmRow[1], /PM 41.3.*m2/); // 최악 PM과 그 케이스
  assert.match(pmRow[1], /GM 7.2.*m2/); // ∞는 최악 후보가 아니다
  const fqSec = m.sections.find((s) => s.title.includes("비행성"));
  const spiralRow = fqSec.rows.find(([k]) => k === "나선");
  assert.match(spiralRow[1], /수준 2/);
  assert.match(spiralRow[1], /14/); // 가장 짧은 T₂의 케이스
  assert.equal(m.verdict.tone, "warn"); // 최악 수준 2
  const cond = m.sections.find((s) => s.title.includes("조성"));
  assert.ok(cond.rows.some(([k, v]) => k.includes("작동기") && v.includes("60")));
});

test("마진 맵 — fq가 없는 구버전 결과도 브리핑이 선다 (판정 없음)", () => {
  const body = {
    kind: "margin_map", loops: [],
    cases: [{ trim: { case: { name: "m1", mach: 0.4, alt: 0, fuel: 200 }, converged: true },
      lon: null, lat: null, margins: {} }],
  };
  const m = briefModel({ ...META, kind: "margin_map" }, body);
  assert.equal(m.verdict.tone, "na");
  assert.ok(m.sections.some((s) => s.title.includes("비행성")));
});

test("엔벨로프 스캔 — 가능/불가와 사유별 집계", () => {
  const c = (name, ok, reason) => ({
    trim: { case: { name, mach: 0.3, alt: 0, fuel: 200 }, converged: true },
    verdict: { ok, reasons: reason ? [reason] : [] },
  });
  const body = { kind: "envelope_scan", n_requested: 3,
    cases: [c("a", true), c("b", false, "alpha_margin"), c("c", false, "saturated_throttle_high")] };
  const m = briefModel({ ...META, kind: "envelope_scan" }, body);
  assert.match(m.verdict.text, /가능 1\/3/);
  const sec = m.sections.find((s) => s.title.includes("사유"));
  assert.ok(sec.rows.some(([k, v]) => k.includes("α 여유") && v === "1"));
  assert.ok(sec.rows.some(([k]) => k.includes("추력 한계")));
});

test("소견서(LLM) 결과는 제목·문단이 브리핑 몸이 된다", () => {
  const body = { kind: "llm_brief", parent: "r9", parent_kind: "sim",
    headline: "착륙이 짧다", body: "문단 하나.\n\n문단 둘.", look_at: ["재생 32 s"] };
  const m = briefModel({ ...META, kind: "llm_brief" }, body);
  assert.equal(m.title, "착륙이 짧다");
  const sec = m.sections.find((s) => s.lines);
  assert.deepEqual(sec.lines, ["문단 하나.", "문단 둘."]);
});

test("모르는 종류는 일반 양식 — 본문 최상위 구성을 사실대로", () => {
  // 전용 요약이 없는 종류(영향성 스캔) — verify_flight·auto_design은 전용 요약이 생겼다
  const body = { kind: "influence_scan", report: { a: 1 }, cases: [1, 2, 3], note: "x".repeat(100) };
  const m = briefModel({ ...META, kind: "influence_scan" }, body);
  assert.equal(m.verdict, null);
  const sec = m.sections.find((s) => s.title.includes("본문 구성"));
  assert.ok(sec.rows.some(([k, v]) => k === "cases" && v.includes("3")));
  assert.ok(sec.rows.some(([k, v]) => k === "report" && v.includes("객체")));
});

test("jsonPreview — 상한을 넘으면 자르고 그 사실을 말한다", () => {
  const small = jsonPreview({ a: 1 });
  assert.equal(small.truncated, false);
  assert.match(small.text, /"a": 1/);
  const big = jsonPreview({ blob: "y".repeat(500) }, 100);
  assert.equal(big.truncated, true);
  assert.ok(big.text.length <= 100);
  assert.ok(big.chars > 500);
});

test("0케이스는 초록이 아니다 — 빈 본문이 합격으로 위장되지 않는다", async () => {
  const trim = briefModel(META, { kind: "trim_batch", results: [] });
  assert.equal(trim.verdict.tone, "na");
  const env = briefModel({ ...META, kind: "envelope_scan" }, { kind: "envelope_scan", cases: [] });
  assert.equal(env.verdict.tone, "na");
});

test("마진 맵 — 루프 항목이 아예 없는 케이스도 판정 불가에 센다", () => {
  const body = {
    kind: "margin_map", loops: [{ name: "pitch_q" }],
    cases: [
      { trim: { case: { name: "m1", mach: 0.4, alt: 0, fuel: 200 } }, lon: null, lat: null,
        margins: { pitch_q: { pm_deg: 0.0, gm_db: 6.0 } } }, // PM 0도 유효한 최악 후보다
      { trim: { case: { name: "m2", mach: 0.5, alt: 0, fuel: 200 } }, lon: null, lat: null,
        margins: {} }, // 이 루프의 마진이 통째로 없다 — 조용히 사라지면 안 된다
      { trim: { case: { name: "m3", mach: 0.6, alt: 0, fuel: 200 } }, lon: null, lat: null,
        margins: { pitch_q: { pm_deg: null, gm_db: null } } }, // 항목은 있는데 값이 판정 불가
    ],
  };
  const m = briefModel({ ...META, kind: "margin_map" }, body);
  const row = m.sections.find((s) => s.title.includes("루프")).rows[0][1];
  assert.match(row, /PM 0.*m1/); // 0이 「후보 없음」으로 오독되지 않는다
  assert.match(row, /판정 불가 2건/); // 항목 결측(m2)과 값 null(m3) 둘 다 센다
});

test("마진 맵 — 폐루프 발산 칸은 최악 PM·GM에서 빼고 「발산 N칸」으로 센다 · 종합은 부족", () => {
  const fq = { short_period: { level: 1, zeta: 0.5 }, phugoid: { level: 1, zeta: 0.06 } };
  const caseOf = (name, m) => ({
    trim: { case: { name, mach: 0.14, alt: 100, fuel: 25 }, converged: true },
    lon: { fq }, lat: null, margins: { pitch_q: m },
  });
  const div = (pm, gm) => ({ pm_deg: pm, gm_db: gm, closed_loop: { stable: false, unstable: [[1.97, 21.6]] } });
  const body = {
    kind: "margin_map", loops: [{ name: "pitch_q" }],
    cases: [
      caseOf("m1", div(-7.5, -2.0)), // 수가 더 작지만 발산 칸 — 최악 여유로 뽑히면 안 된다
      caseOf("m2", { pm_deg: 48.0, gm_db: 9.0, closed_loop: { stable: true } }),
      caseOf("m3", div(82.0, 20.0)),
    ],
  };
  const m = briefModel({ ...META, kind: "margin_map" }, body);
  const row = m.sections.find((s) => s.title.includes("루프")).rows[0][1];
  assert.match(row, /^발산 2칸/);
  assert.match(row, /최악 PM 48.*m2/);
  assert.match(row, /최악 GM 9.*m2/);
  assert.doesNotMatch(row, /-7\.5|−7\.5|판정 불가/); // 발산 칸은 판정 불가도 아니다
  assert.equal(m.verdict.tone, "bad"); // 비행성 수준 1이어도 발산은 결함
  assert.match(m.verdict.text, /^폐루프 발산 2칸 — pitch_q @ m1/);
  // 발산이 없으면 종전과 같다 — 비행성 수준이 종합을 정한다
  const ok = briefModel({ ...META, kind: "margin_map" }, { ...body, cases: [body.cases[1]] });
  assert.equal(ok.verdict.tone, "ok");
  assert.doesNotMatch(ok.sections.find((s) => s.title.includes("루프")).rows[0][1], /발산/);
});

test("시뮬레이션 — 런 구성(시간·신호·웨이포인트)과 해석 안내", () => {
  const body = { kind: "sim", t: [0, 0.5, 1.0], signals: { h: [1, 2, 3], V: [4, 5, 6] },
    meta: { waypoints: [[0, 0], [100, 0]], accept_radius: 50 } };
  const m = briefModel({ ...META, kind: "sim" }, body);
  assert.equal(m.verdict.tone, "na");
  const sec = m.sections.find((s) => s.title.includes("런 구성"));
  assert.ok(sec.rows.some(([k, v]) => k === "시간" && v.includes("표본 3")));
  assert.ok(sec.rows.some(([k, v]) => k === "신호" && v === "2개"));
  assert.ok(sec.rows.some(([k, v]) => k === "웨이포인트" && v.includes("2점")));
});

test("시뮬레이션 — 착륙 요약(landingSummary 재사용)과 지표·엔벨로프 절", () => {
  const body = {
    kind: "sim",
    t: [0, 1, 2, 3],
    signals: {
      pn: [0, 0, 100, 150], pe: [0, 0, 0, 0],
      limiter_active: [false, false, true, false], // 1/4 = 25 %
    },
    envelope: {
      stall_margin: [0.3, 0.05, 0.2, 0.2],
      flags: { alpha: [false, true, false, false], altitude: [false, false, false, false] },
      worst_margin: 0.05, worst_margin_t: 1.0,
      min_alt: 42.0, min_alt_t: 2.5,
      any_flag: true, first_flag_t: 1.0,
    },
    meta: {
      case: "M0.20_h500_f25", aborted: false, path_escapes: [3],
      waypoints: [[0, 0], [100, 0]], accept_radius: 50,
      phases: { launch_exit_t: null, touchdown_t: 2.0, td_sink_rate: -0.8, td_speed: 30.0, stop_t: 3.0 },
    },
  };
  const m = briefModel({ ...META, kind: "sim" }, body);
  assert.equal(m.verdict.tone, "warn"); // 엔벨로프 이탈 표본 있음
  assert.match(m.verdict.text, /첫 이탈 1/);
  const landing = m.sections.find((s) => s.title.includes("착륙"));
  assert.ok(landing.rows.some(([k, v]) => k === "접지" && /강하율 -0.8/.test(v)));
  assert.ok(landing.rows.some(([k]) => k === "정지"));
  const met = m.sections.find((s) => s.title.includes("지표"));
  assert.ok(met.rows.some(([k, v]) => k.includes("실속마진") && v.includes("0.05") && v.includes("1")));
  assert.ok(met.rows.some(([k, v]) => k.includes("최저 고도") && v.includes("42")));
  assert.ok(met.rows.some(([k, v]) => k.includes("리미터") && /25 %.*1\/4 표본/.test(v)));
  // 어휘는 재생 화면과 같은 표(FLAG_LABEL) — alpha가 아니라 α, 분모가 있어야 1이 몇 초인지 읽힌다
  assert.ok(met.rows.some(([k, v]) => k.includes("이탈 표본") && /α 1\/4/.test(v)));
  assert.ok(met.rows.some(([k, v]) => k.includes("궤도 이탈") && v.includes("#4")));
});

test("시뮬레이션 — 4만 표본 중 1표본 작동이 「0 %」로 접히지 않는다", () => {
  const lim = Array(4000).fill(false);
  lim[7] = true; // 0.025 % — 반올림하면 0으로 보이는 자리
  const m = briefModel({ ...META, kind: "sim" },
    { kind: "sim", t: [0, 1], signals: { limiter_active: lim }, envelope: { any_flag: false }, meta: {} });
  const row = m.sections.find((s) => s.title.includes("지표")).rows.find(([k]) => k.includes("리미터"));
  assert.match(row[1], /< 0.05 %.*1\/4000 표본/);
});

test("시뮬레이션 — 중단은 bad, 이탈 없음은 ok, 착륙 단계 없으면 없다고 말한다", () => {
  const base = { kind: "sim", t: [0, 1], signals: {}, meta: {} };
  // aborted는 불리언이 아니라 **사유 코드 문자열**이다("cancelled"·"alt_out_of_range" —
  // 엔진 simulator.py). 실물 모양으로 박아야 truthy → === true 로 "엄밀해지는" 회귀를 잡는다
  const aborted = briefModel({ ...META, kind: "sim" },
    { ...base, meta: { aborted: "cancelled" }, envelope: { any_flag: false } });
  assert.equal(aborted.verdict.tone, "bad"); // 취소 런이 any_flag=false로 초록 위장되면 안 된다
  assert.match(aborted.verdict.text, /cancelled/); // 사유 코드는 그대로 낸다
  const clean = briefModel({ ...META, kind: "sim" },
    { ...base, envelope: { any_flag: false } });
  assert.equal(clean.verdict.tone, "ok");
  const landing = clean.sections.find((s) => s.title.includes("착륙"));
  assert.match(landing.rows[0][1], /기록 없음/); // 0으로 위조하지 않는다
});

test("자동 설계 — 종료 상태·판정 규모·처방·반출, 탭과 같은 함수의 문구 · 탭 인계(openIn)", () => {
  const meta = { ...META, id: "d2", kind: "auto_design", parent: "d1",
    profile: { id: "showcase-delta", name: "쇼케이스", revision: 4, fingerprint: "a".repeat(16) } };
  const body = {
    report: { status: "escalated", stage: "done", iterations: 2, judged: 180, failures: 4,
      n_points: 40, points: { anchor: 12, breakpoint: 8, validation: 20 }, ledger_size: 31,
      criteria_fingerprint: "0123456789abcdef" },
    points: { points: [
      { name: "A", mach: 0.1, alt: 200, fuel: 20, role: "anchor", trimmable: true },
      { name: "B", mach: 0.2, alt: 200, fuel: 20, role: "anchor", trimmable: true },
    ] },
    margin_out: { cases: { A: { loops: { pitch: { status: "ok" } } }, B: { loops: { roll: { status: "fail" } } } } },
    proposed_actions: [{ id: "e1", action: { type: "escalate" } }],
    gain_export: { tables: { "pitch.kp": {} }, tables_resampled: { "pitch.kp": {} }, constants: { "roll.ki": 0 } },
    profile: { id: "showcase-delta", source: "snapshot", is_example: false, variant: null },
  };
  const m = briefModel(meta, body);
  assert.equal(m.verdict.tone, "bad"); // escalated는 통과가 아닌 채 끝난 것 — 탭 칩과 같은 색
  assert.equal(m.verdict.text, "escalated — 판정 180 · 실패 4 · 에스컬레이션 1");
  const run = m.sections.find((s) => s.title === "실행 요약");
  assert.ok(run.rows.some(([k, v]) => k === "재개 이력" && v.includes("d1")));
  assert.ok(run.rows.some(([k, v]) => k === "운영점 판정" && v.includes("ok 1") && v.includes("fail 1")));
  const ge = m.sections.find((s) => s.title === "게인 반출");
  assert.ok(ge.rows.some(([k, v]) => k === "스케줄 · 상수 자리" && v === "1 · 1"));
  // 재개 결과(snapshot)도 반영 대상이다 — 예제로 읽지 않는다
  assert.ok(ge.rows.some(([k, v]) => k === "문서 반영" && v.startsWith("대상 있음")));
  assert.deepEqual(m.openIn && [m.openIn.href, m.openIn.key], ["#autodesign", "designOpen"]);
  // 예제 결과면 반영 사유
  const ex = briefModel(meta, { ...body, profile: { id: "example-delta", source: "request", is_example: true } });
  assert.ok(ex.sections.find((s) => s.title === "게인 반출").rows
    .some(([k, v]) => k === "문서 반영" && /예제/.test(v)));
});

test("탑재 C 검증 — 검사군·커버리지·구성, 두 지문 계보, 판정 없는 본문은 통과로 위장하지 않는다", () => {
  const meta = { ...META, id: "v1", kind: "verify_flight", fingerprint: undefined,
    structure_fingerprint: "bc5d7dc7d4ee4c60", param_fingerprint: "9434b43ca18a887d" };
  const report = {
    verdict: "pass_with_skips", artifact: "fcl", structure_fingerprint: "bc5d7dc7d4ee4c60",
    param_fingerprint: "9434b43ca18a887d", engine: "0.2.0", dt: 0.01, t_end: 180, steps: 25550,
    summary: [
      { key: "compile", label: "컴파일 — 엄격", status: "pass", detail: "빌드 7개 · 경고 0" },
      { key: "coverage", label: "커버리지 — 라인·분기", status: "skip", detail: "llvm-cov 없음" },
    ],
    files: [{ name: "fcl.c", lines: 100 }, { name: "fcl.h", lines: 20 }],
    cases: [{ status: "pass" }, { status: "pass" }, { status: "skip" }],
    coverage: { status: "skip", reason: "llvm-cov 없음" },
  };
  const m = briefModel(meta, { kind: "verify_flight", report });
  assert.equal(m.verdict.tone, "na");
  assert.match(m.verdict.text, /^통과 \(생략 있음\)/);
  assert.ok(m.head.some(([k, v]) => k === "계보 지문" && v === "구조 bc5d7dc7d4ee4c60 · 값 9434b43ca18a887d"));
  const sum = m.sections.find((s) => s.title.startsWith("검사군"));
  assert.deepEqual(sum.rows[1], ["커버리지", "생략 — llvm-cov 없음"]);
  const comp = m.sections.find((s) => s.title === "구성");
  assert.ok(comp.rows.some(([k, v]) => k === "생성 파일" && v === "2개 · 120줄"));
  assert.ok(comp.rows.some(([k, v]) => k === "시험 케이스" && v.includes("통과 2") && v.includes("생략 1")));
  assert.deepEqual(m.sections.find((s) => s.title === "구조적 커버리지").rows, [["측정", "생략 — llvm-cov 없음"]]);
  assert.deepEqual(m.openIn && [m.openIn.href, m.openIn.key], ["#verify", "verifyOpen"]);
  // 측정된 커버리지
  const measured = briefModel(meta, { report: { ...report, verdict: "pass",
    coverage: { status: "measured", justified: [{}],
      totals: { lines: { percent: 100, covered: 694, count: 694 }, branches: { percent: 99.4, covered: 167, count: 168 } } },
    mcdc: { status: "measured", total: 30, covered: 29, justified: 1 } } });
  assert.equal(measured.verdict.tone, "ok");
  assert.deepEqual(measured.sections.find((s) => s.title === "구조적 커버리지").rows, [
    ["라인", "100.0% (694/694)"], ["분기", "99.4% (167/168) (+정당화 1)"], ["MC/DC 조건", "29+1/30"]]);
  // 판정 필드가 없으면 na — verdictModel의 기본 「통과」로 새지 않는다
  const bare = briefModel(meta, { report: { a: 1 } });
  assert.equal(bare.verdict.tone, "na");
  assert.doesNotMatch(bare.verdict.text, /통과/);
  // 전용 요약이 없는 종류는 openIn이 없다
  assert.equal(briefModel({ ...META, kind: "influence_scan" }, {}).openIn, null);
});

// ── 시뮬 착륙 요약의 판정 재료 — 시뮬 탭·투어 마무리와 같은 두 한계(활주로 폭·발사하중) ──

/** 고흥 활주로를 쓴 착륙 런 — 활주로 축 a · 횡편차 c(오른쪽 +)인 점을 NED로(방위가 0이 아니다). */
const goheungSim = (c) => {
  const h = GOHEUNG.runwayHeadingRad;
  const pts = [0, 100, 200, 300].map((a) => [a * Math.cos(h) - c * Math.sin(h), a * Math.sin(h) + c * Math.cos(h)]);
  return {
    kind: "sim", t: [0, 1, 2, 3],
    signals: { pn: pts.map((p) => p[0]), pe: pts.map((p) => p[1]), launch_gx: [5.1, 5.1, 0, 0] },
    envelope: { any_flag: false },
    meta: {
      phases: { launch_exit_t: 1.0, touchdown_t: 2.0, td_sink_rate: -0.8, td_speed: 30.0, stop_t: 3.0 },
      // 서버가 동봉하는 그 런의 활주로(시뮬 탭 기본 폼 = 고흥 제원)와 레일
      runway: { elevation: 0, heading: GOHEUNG.runwayHeadingRad, length: GOHEUNG.runwayLengthM },
      launch: { elev_angle: 0.26 },
      profile: { id: "showcase-delta", revision: 3 },
    },
  };
};
const landingOf = (m) => Object.fromEntries(m.sections.find((s) => s.title.includes("착륙")).rows);

test("시뮬레이션 — 접지·정지 횡편차를 고흥 활주로 폭(한 자리 siteRunwayWidth)으로 판정한다", () => {
  const rows = landingOf(briefModel({ ...META, kind: "sim" }, goheungSim(-0.6)));
  // 종전에는 폭을 안 넘겨 시뮬 탭이 「폭 안」이라 한 같은 런을 브리핑은 「대조하지 않았다, 판정 불가」라 했다
  assert.match(rows["접지 횡편차"], /한계 21 m \(고흥 시험장 제원 활주로 폭 45 m의 반폭 22\.5 m − 가장자리 여유 1\.5 m\)/);
  assert.doesNotMatch(rows["접지 횡편차"], /판정 불가/);
  assert.match(rows["정지"], /횡편차 -1 m ≤ 한계 21 m/);
  // 폼에서 활주로를 고친 런은 시험장 폭을 빌리지 않는다 — 사유와 함께 판정 불가
  const edited = goheungSim(-0.6);
  edited.meta.runway = { ...edited.meta.runway, length: 1500 };
  assert.match(landingOf(briefModel({ ...META, kind: "sim" }, edited))["접지 횡편차"],
    /달라 그 폭을 쓸 수 없다, 판정 불가/);
});

test("시뮬레이션 — 발사하중 한계는 조립이 넘긴다(그 런의 기체 문서) · 안 넘기면 대조 안 함", () => {
  const body = goheungSim(0);
  const judged = landingOf(briefModel({ ...META, kind: "sim" }, body,
    { launchLimit: { nx: 8, source: "쇼케이스 · r3" } }));
  assert.match(judged["레일 이탈"], /축방향 하중배수 5\.36 g .* ≤ 한계 8 g \(쇼케이스 · r3 structural\.n_x_launch\)/);
  const over = landingOf(briefModel({ ...META, kind: "sim" }, body,
    { launchLimit: { nx: 5.2, source: "쇼케이스 · r3" } }));
  assert.match(over["레일 이탈"], /한계를 넘었다/);
  const failed = landingOf(briefModel({ ...META, kind: "sim" }, body, { launchLimit: { error: "문서를 받지 못했다" } }));
  assert.match(failed["레일 이탈"], /문서를 받지 못했다, 판정 불가/);
  assert.match(landingOf(briefModel({ ...META, kind: "sim" }, body))["레일 이탈"],
    /대조하지 않았다, 판정 불가/);
  // 조립(views/results.js)이 실제로 넘긴다 — 원문 대조(뷰는 테스트가 import하지 않는다)
  const view = readFileSync(new URL("../views/results.js", import.meta.url), "utf8");
  assert.match(view, /m\.kind === "sim" \? await launchLimitOf\(body\.meta\) : undefined/);
  assert.match(view, /briefModel\(m, body, \{ launchLimit \}\)/);
  assert.match(view, /import \{ launchLimitOf \} from "\.\/sim\.js";/);
});

test("자동 설계 — 표현·실패 위치·작동기·적합 표본 제외·적합 보고가 브리핑에 선다 (탭과 같은 함수)", () => {
  const meta = { ...META, id: "d3", kind: "auto_design" };
  // 실측 모양(예제 작은 설정, 표 모드) — 튜닝 실패 표본을 적합에서 뺐고 표는 마하 1축이다
  const body = {
    report: { status: "escalated", stage: "DONE", iterations: 0, judged: 290, failures: 45,
      failures_by_role: { anchor: 31, validation: 14 }, fit_mode: "table",
      points: { anchor: 45, breakpoint: 0, validation: 15 }, n_points: 60,
      excluded_samples: [
        { slot: "roll.k_rate", point: "M0.103219_h1500_f25", value: 0, loop: "roll_rate", reason: "no_stable_gain", basis: "own" },
        { slot: "roll.kp", point: "M0.103219_h1500_f25", value: 0.0502, loop: "yaw_rate", reason: "no_stable_gain", basis: "rate_loop" },
      ],
      exclusion_withheld: ["pitch.ki"],
      actuator: { source: { wn: "profile", zeta: "profile" }, wn: 30, zeta: 0.7, delay_s: 0.035, pade_order: 2 } },
    config: { actuator_wn: null, actuator_zeta: null },
    fits: {
      "roll.ki": { kind: "table", axis: "mach", axes_excluded: ["alt"], zigzag: 4, n_breakpoints: 14,
        quality: { cross_axis_frac: 0.5531, status: "na" } },
      "pitch.ki": { kind: "table", axis: "mach", n_breakpoints: 3, zigzag: 0, quality: { cross_axis_frac: 0 },
        exclusion_withheld: { kept_would_be: 1, samples: [{}, {}] } },
    },
    proposed_actions: [{ id: "e1", action: { type: "escalate" } }],
  };
  const m = briefModel(meta, body);
  assert.equal(m.verdict.text, "escalated — 판정 290 · 실패 45 (앵커 31 · 검증점 14) · 에스컬레이션 1");
  const run = Object.fromEntries(m.sections.find((s) => s.title === "실행 요약").rows);
  assert.equal(run["표현"], "표(선형 보간)");
  assert.equal(run["판정 · 실패"], "290 · 45 — 실패 위치 앵커 31 · 검증점 14");
  assert.equal(run["작동기"], "ωn 30 rad/s · ζ 0.700 (기체 문서) · 지연 35 ms · Padé 2차");
  const fit = m.sections.find((s) => s.title === "게인 스케줄 적합").rows;
  assert.deepEqual(fit, [
    ["적합 표본 제외", "튜닝 실패 표본 2개를 적합에서 뺐다 (점 1곳 · 자리 2개 — 그 점의 스케줄 값은 이웃 보간)"],
    ["제외 · roll.k_rate", "1점 — 사유 no_stable_gain 1 · 근거 그 자리 튜닝 실패 1"],
    ["제외 · roll.kp", "1점 — 사유 no_stable_gain 1 · 근거 같은 축 레이트 루프가 실패한 위에서 튜닝 1"],
    ["제외 보류", "pitch.ki — 튜닝 실패 표본 2개를 빼면 1개만 남아 제외를 보류했다 — 이 자리의 표는 실패 표본을 담고 있다"],
    ["적합 보고", "스케줄 축 밖 변동 1/2자리(alt) · 교차축 잔차 최대 55% (roll.ki) · 톱니 최대 4회/절점 14 (roll.ki)"],
  ]);
  // 표현 기록이 없는 옛 결과 — 없는 표현을 지어내지 않고 그 사실을, 작동기는 그때의 config 값을
  const old = briefModel(meta, { report: { status: "converged", judged: 5, failures: 0 },
    config: { actuator_wn: 30, actuator_zeta: 0.7 } });
  const oldRun = Object.fromEntries(old.sections.find((s) => s.title === "실행 요약").rows);
  assert.match(oldRun["표현"], /^기록 없음 — 표현 선택 이전 결과\(다항\)/);
  assert.match(oldRun["작동기"], /설정 — 작동기 출처 기록 이전 결과/);
  assert.equal(oldRun["판정 · 실패"], "5 · 0");
  assert.equal(old.sections.find((s) => s.title === "게인 스케줄 적합"), undefined);
});


test("자동 설계 — 점 줄은 설계점·검증점, 절점 칸은 표별 절점(공통/분리 집합) — 옛 결과는 옛 이름·기록 없음", () => {
  const meta = { ...META, id: "d4", kind: "auto_design" };
  const body = {
    report: { status: "converged", judged: 30, failures: 0, n_points: 19, points: { design: 7, validation: 12 },
      knots: { tables: { "pitch.kp": 8, "pitch.ki": 7 }, shared: false } },
    gain_export: { tables: {}, constants: {}, knots: {
      // 공통 집합의 이름은 엔진 knots.COMMON("common") — 공통/분리는 그 이름으로 가른다
      sets: { common: { coords: [0.1, 0.3, 0.5, 0.7, 0.8, 0.85, 0.9], source: "base_axis", history: [] },
        "pitch.kp": { coords: [0.1, 0.2, 0.3, 0.5, 0.7, 0.8, 0.85, 0.9], source: "split:common", history: [] } },
      tables: { "pitch.kp": { set: "pitch.kp", shared: false, unsupported: [] },
        "pitch.ki": { set: "common", shared: false, unsupported: [] } } } },
  };
  const run = Object.fromEntries(briefModel(meta, body).sections.find((s) => s.title === "실행 요약").rows);
  assert.equal(run["점"], "19 (설계점 7 · 검증점 12)");
  assert.equal(run["절점"],
    "표 2개 · 절점 7~8 · 집합 2 · 공통 1 · 분리 1 — pitch.ki 7(공통 집합) · pitch.kp 8(분리 집합)");
  const old = Object.fromEntries(briefModel(meta, { report: { status: "converged", n_points: 60,
    points: { anchor: 45, breakpoint: 0, validation: 15 } } }).sections.find((s) => s.title === "실행 요약").rows);
  assert.equal(old["점"], "60 (앵커 45 · bp 0 · 검증 15)");
  assert.match(old["절점"], /^기록 없음 — 절점 분리 이전 결과/);
});

test("자동 설계 — 검증점 칸은 계획 요약·요약 격자 칸 수·보강 상태, 계획 이전 결과는 기록 없음", () => {
  const meta = { ...META, id: "d5", kind: "auto_design" };
  const report = { status: "converged", n_points: 20, points: { design: 8, validation: 12 },
    validation: { rule: "plan", conditions: [[0, 50]], mode: "full", omitted: [], requested: 12, out_of_region: 0,
      by_kind: { midpoint: 10, boundary: 2 } },
    coverage: { validation_done: 12 },
    summary_grid: { columns: [{ key: "seg1-2", kind: "segment", lo: 0.2, hi: 0.4 }],
      rows: [{ key: "r0", alt: 0, fuel: 50, kind: "condition" }],
      cells: { r0: { "seg1-2": { n: 2, done: 2, states: { computable: 2 }, verdicts: { fail: 1, good: 1 },
        headline: "불합격", text: "불합격 1 · 완료 2/2" } } }, totals: {} },
    reinforcement: { status: "tol_unset", label: "허용치 미설정 — d 분포만", distribution: {} } };
  const run = Object.fromEntries(briefModel(meta, { report }).sections.find((s) => s.title === "실행 요약").rows);
  assert.equal(run["검증점"], "요청 12 · 완료 12 · 조건 1행(전체 조합) · 구간 내분점 10 · 요구영역 경계 2 — "
    + "격자 불합격 칸 1 · 미완료 칸 0 · 검사한 점 모두 충족 칸 0 — 보강 — 허용치 미설정 — d 분포만");
  const old = Object.fromEntries(briefModel(meta, { report: { status: "converged" } }).sections
    .find((s) => s.title === "실행 요약").rows);
  assert.match(old["검증점"], /^기록 없음 — 검증점 계획 이전 결과/);
});
