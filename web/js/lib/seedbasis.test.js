import assert from "node:assert/strict";
import test from "node:test";

import { basisAttitude, basisHead, basisRates, designGain, modelText } from "./seedbasis.js";

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
