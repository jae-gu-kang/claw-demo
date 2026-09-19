// 결과 브리핑 모델 — 정해진 양식(머리·종합 판정·절)이 종류마다 결정적으로 나온다
import { test } from "node:test";
import assert from "node:assert/strict";

import { briefModel, jsonPreview, kindLabel } from "./resultbrief.js";

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
  const body = { kind: "verify_flight", report: { a: 1 }, cases: [1, 2, 3], note: "x".repeat(100) };
  const m = briefModel({ ...META, kind: "verify_flight" }, body);
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
