import assert from "node:assert/strict";
import test from "node:test";

import {
  achievedText, basisAttitude, basisHead, basisRates, designGain, metricLabel, modelText,
} from "./seedbasis.js";

const BODY = {
  ok: true, reason: null, reason_text: null,
  case: { name: "M0.45_h1000_f200", mach: 0.45, alt: 1000, fuel: 200 },
  e_ref_dps: 10, targets: { zeta_sp: 0.7, zeta_dr: 0.5, roll_lambda: 12, pm_deg: 50, gm_db: 8 },
  trim: { converged: true, alpha: 0.05, de: -0.02, throttle: 0.4 },
  order: ["pitch_rate", "yaw_rate", "roll_rate"],
  rates: {
    pitch_rate: {
      slot: "pitch.k_rate", sign_basis: "B[q,de]=-35",
      model: { kind: "second_order", label: "단주기 2차 근사 (w–q)", states: ["w", "q"],
        b: -35, c1: 2.1, c1_k: 35, c0: 9.6, c0_k: -40, open_wn: 3.1, open_zeta: 0.34 },
      target: { metric: "zeta_sp", value: 0.7 },
      candidate: { k: 0.133, poles: [[-2.4, 2.4], [-2.4, -2.4]], note: null },
      full: { achieved: 0.698, stable: true, ok: false },
      budget: { surface: "elevon", margin: 0.308, delta_cmd: 0.0232, share: 0.075, ok: true },
      neighbors: [
        { mult: 0.7, k: 0.0931, achieved: 0.55, stable: true },
        { mult: 1.0, k: 0.133, achieved: 0.698, stable: true },
        { mult: 1.3, k: 0.173, achieved: 0.81, stable: false },
      ],
      reason: null, reason_text: null,
    },
    yaw_rate: {
      slot: "yaw.k_rate", sign_basis: "B[r,dr]=0",
      model: { kind: "second_order", label: "더치롤 2차 근사 (v–r)", states: ["v", "r"],
        b: 0, c1: 1, c1_k: 0, c0: 4, c0_k: 0, open_wn: 2, open_zeta: 0.25 },
      target: { metric: "zeta_dr", value: 0.5 },
      candidate: null, full: null, budget: null, neighbors: [],
      reason: "seed_sign_ambiguous", reason_text: "조종효율(B)이 0이거나 …",
    },
    roll_rate: {
      slot: "roll.k_rate", sign_basis: "B[p,da]=26.9",
      model: { kind: "first_order", label: "롤 수렴 1차 근사 (p)", states: ["p"], a: -5.1, b: 26.9 },
      target: { metric: "roll_lambda", value: 12 },
      candidate: { k: -0.256, poles: [[-12, 0]], note: null },
      full: { achieved: null, stable: false, ok: null },  // 못 잰 값 — 0으로 위장하지 않는다
      budget: { surface: "elevon", margin: 0.308, delta_cmd: 0.0446, share: 0.145, ok: true },
      neighbors: [], reason: null, reason_text: null,
    },
  },
  attitude: {
    pitch_att: { slot: "pitch.kp/ki", sign_basis: "B[q,de]=-35", kp: -0.89, ki: -0.294,
      wc_att: 2.64, wc0: 2.9, pm_deg: 113.3, gm_db: 12.1, reason: "ok", reason_text: "설계 목표 달성",
      passing: true },
    roll_att: { slot: "roll.kp/ki", sign_basis: "B[p,da]=26.9", kp: 0, ki: 0,
      reason: "margin_floor", reason_text: "지연·작동기 예산이 병목이다", passing: false },
  },
  outer: { separation: 5, wc_outer: 0.526 },
  design_now: { source: "example", gains: { "pitch.k_rate": 0.4, "pitch.kp": -2.0 } },
};

test("머리말 — 조건·트림 요약과 실패 사유", () => {
  const h = basisHead(BODY);
  assert.equal(h.ok, true);
  assert.match(h.line, /M0\.45_h1000_f200/);
  const failed = basisHead({ ok: false, reason: "basis_trim_failed", reason_text: "트림이 수렴하지 않는다" });
  assert.equal(failed.ok, false);
  assert.match(failed.line, /트림이 수렴하지 않는다/);
  assert.equal(basisHead(null).ok, false);
});

test("레이트 줄 — order 순서·후보 없음 사유·결측 null 유지", () => {
  const rows = basisRates(BODY);
  assert.deepEqual(rows.map((r) => r.name), ["pitch_rate", "yaw_rate", "roll_rate"]);
  const p = rows[0];
  assert.equal(p.k, 0.133);
  assert.equal(p.achieved, 0.698);
  assert.equal(p.achievedOk, false);  // 판정은 엔진 불리언 그대로
  assert.equal(p.stable, true);
  assert.equal(p.budget.ok, true);
  assert.equal(p.neighbors.length, 3);
  const y = rows[1];
  assert.equal(y.k, null);
  assert.match(y.reasonText, /seed_sign_ambiguous/);
  const r = rows[2];
  assert.equal(r.achieved, null);  // null은 "—"로 그릴 몫 — 0이 아니다
  assert.equal(r.achievedOk, null);
  assert.equal(basisRates(null).length, 0);
});

test("자세 줄 — 튜너 판정(passing)을 그대로 나른다", () => {
  const rows = basisAttitude(BODY);
  assert.deepEqual(rows.map((r) => r.name), ["pitch_att", "roll_att"]);
  assert.equal(rows[0].passing, true);
  assert.equal(rows[0].kp, -0.89);
  assert.equal(rows[1].passing, false);
  assert.match(rows[1].reasonText, /margin_floor/);
});

test("모델 문구와 지금 문서 게인", () => {
  assert.match(modelText(BODY.rates.roll_rate.model), /a=-5\.1/);
  assert.match(modelText(BODY.rates.pitch_rate.model), /개루프 ζ 0\.34/);
  assert.match(modelText({ kind: "second_order", label: "x", b: 1, open_wn: null, open_zeta: null }),
    /진동쌍 없음/);
  assert.equal(modelText(null), "—");
  assert.equal(designGain(BODY, "pitch.k_rate"), 0.4);
  assert.equal(designGain(BODY, "yaw.k_rate"), null);
  assert.equal(designGain({ design_now: null }, "pitch.kp"), null);
});

// 쇼케이스 결함 D7 — 0.697/0.700·0.590/0.600·11.6/12가 「레이트 후보 달성 0/3」으로만 읽혀 실패처럼 보였다.
// 판정(달성·미달)은 엔진 것 그대로 두고, 달성값·목표·목표 대비 차를 함께 낸다 — 근소 미달과 큰 미달이 갈린다
test("레이트 줄 — 목표 대비 상대 차(gap)를 싣는다 · 못 잰 값·후보 없음은 null", () => {
  const rows = basisRates(BODY);
  assert.ok(Math.abs(rows[0].gap - (0.698 - 0.7) / 0.7) < 1e-12);
  assert.equal(rows[1].gap, null); // 후보 없음
  assert.equal(rows[2].gap, null); // 못 잰 값 — 0 %로 위장하지 않는다
  const zeroTarget = basisRates({ order: ["x"], rates: { x: { candidate: { k: 1 }, target: { metric: "m", value: 0 },
    full: { achieved: 0.1, ok: true } } } });
  assert.equal(zeroTarget[0].gap, null); // 목표 0 — 상대 차를 정의할 수 없다
});

test("achievedText — 「ζ_sp 0.698/0.7 (−0.3 %)」: 지표 이름·달성/목표·목표 대비 차", () => {
  const rows = basisRates(BODY);
  assert.equal(achievedText(rows[0]), "ζ_sp 0.698/0.7 (−0.3 %)");
  assert.equal(achievedText(rows[2]), "λ_roll —/12"); // 못 잰 값 — 차를 적지 않는다
  assert.equal(achievedText(rows[1]), null); // 후보 없음 — 잴 것이 없다
  const over = basisRates({ order: ["p"], rates: { p: { candidate: { k: 1 }, target: { metric: "zeta_dr", value: 0.6 },
    full: { achieved: 0.66, ok: true } } } });
  assert.equal(achievedText(over[0]), "ζ_dr 0.66/0.6 (+10.0 %)");
});

test("metricLabel — 엔진 지표 키 → 화면 기호(목표 줄과 같은 표기), 모르는 키는 그대로", () => {
  assert.equal(metricLabel("zeta_sp"), "ζ_sp");
  assert.equal(metricLabel("zeta_dr"), "ζ_dr");
  assert.equal(metricLabel("roll_lambda"), "λ_roll");
  assert.equal(metricLabel("new_metric"), "new_metric");
  assert.equal(metricLabel(null), "—");
});
