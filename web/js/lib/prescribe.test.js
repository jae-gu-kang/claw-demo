/** lib/prescribe 계약 — 정량 처방 모델의 판단.

핵심 규약: ① 필요 변화량은 %로 옮기되 solvable=False의 사유가 값 자리를 차지한다
(빈칸·null 누출 금지) ② 적용은 서버가 배율을 이미 곱한 실효 테이블의 **전체
교체**이고(게인 탭 계약과 동일) 상수는 축별 병합이라 기존 키를 지우지 않는다.
*/

import assert from "node:assert/strict";
import test from "node:test";

import {
  applyExport, jointLines, leverBase, leverChange, leverLine, mergeConstants, normalizePrescribe,
  prescribeRequest, singleRows, unappliedLevers, unappliedNote,
} from "./prescribe.js";

const payload = {
  knobs: ["table.pitch.kp"],
  singles: {
    "table.pitch.kp": {
      alt_rms: { solvable: true, required_span: 0.072, direction: "increase",
                 binding_case: "M0.5", reason: null },
      spd_rms: { solvable: true, required_span: 0.0, direction: null,
                 reason: "이미 전 케이스가 문턱 안이다", binding_case: null },
      worst_stall_margin: { solvable: false, required_span: null,
                            reason: "스팬 안 경향이 비단조(mixed)" },
    },
  },
  joint: { solvable: true, spans: { "table.pitch.kp": 0.12 },
           predicted: { "M0.5": { alt_rms: 9.7 } },
           excluded: [{ knob: "table.pitch.kp", metric: "hdg_rms",
                        reason: "비단조" }],
           violated: [], span_bound: 0.2, reason: null },
  confirm: { cards: [], aggregate: { hard_fail: false, hard_fails: [] } },
  gain_export: { tables: { "pitch.kp": { axes: { mach: [0.3, 0.5] },
                                          data: [1.1, 1.2] } },
                 constants: { scas: { pitch: { kp: -2.0 } }, autopilot: {} } },
  proposal_notes: [], warnings: ["계보 불일치: …"],
  fingerprint: "fp", sweep_fingerprint: "sfp", criteria_fingerprint: "cfp",
};

test("정규화 — 빈 응답에서 죽지 않고 지어내지 않는다", () => {
  const m = normalizePrescribe(null);
  assert.deepEqual(m.knobs, []);
  assert.equal(m.joint, null);
  assert.deepEqual(singleRows(m), []);
});

test("단일 행 — %와 사유, null 누출 없음", () => {
  const rows = singleRows(normalizePrescribe(payload));
  const alt = rows.find((r) => r.metric === "alt_rms");
  assert.match(alt.text, /\+7\.2\s?%/);
  assert.match(alt.text, /M0\.5/);  // binding case
  const zero = rows.find((r) => r.metric === "spd_rms");
  assert.match(zero.text, /이미/);
  const mixed = rows.find((r) => r.metric === "worst_stall_margin");
  assert.equal(mixed.solvable, false);
  assert.match(mixed.text, /비단조/);
  for (const r of rows) {
    assert.ok(!/null|undefined|NaN/.test(r.text), r.text);
  }
});

test("조합 줄 — 스팬은 %로, 제외·위반은 사유 문장으로", () => {
  const lines = jointLines(normalizePrescribe(payload).joint).join(" | ");
  assert.match(lines, /table\.pitch\.kp \+12\s?%/);
  assert.match(lines, /비단조/);
  assert.ok(!/null|undefined|NaN/.test(lines), lines);
});

test("상수 병합은 축별이고 기존 키를 지우지 않는다", () => {
  const merged = mergeConstants({ pitch: { kp: -1.0, ki: -0.5 } },
                                { pitch: { kp: -2.0 }, roll: { kp: 3.0 } });
  assert.equal(merged.pitch.kp, -2.0);
  assert.equal(merged.pitch.ki, -0.5);  // 기존 유지
  assert.equal(merged.roll.kp, 3.0);
});

test("적용 — 실효 테이블 전체 교체 + 출처 표기 + 상수 병합 (게인 탭 계약)", () => {
  const kv = new Map([["scasParams", { pitch: { ki: -0.5 } }]]);
  const store = { get: (k) => kv.get(k), set: (k, v) => kv.set(k, v) };
  applyExport(store, normalizePrescribe(payload).gainExport,
              { sourceId: "r123" });
  assert.deepEqual(Object.keys(kv.get("gainTables")), ["pitch.kp"]);
  assert.equal(kv.get("gainScheduleOff"), false);
  assert.deepEqual(kv.get("gainTablesSource"), { kind: "prescribe", resultId: "r123" });
  assert.equal(kv.get("scasParams").pitch.kp, -2.0);
  assert.equal(kv.get("scasParams").pitch.ki, -0.5);
});

test("요청 본문 — 스윕 참조·확인 깊이가 실린다", () => {
  const body = prescribeRequest({}, {
    resultId: "r1", cases: [{ mach: 0.5 }], knobs: ["table.pitch.kp"],
    confirm: "linear", tSettle: 2, fingerprint: "fp",
  });
  assert.equal(body.result_id, "r1");
  assert.equal(body.confirm, "linear");
  assert.deepEqual(body.knobs, ["table.pitch.kp"]);
  assert.equal(body.t_settle, 2);
});


// ── 지렛대 — 조합 해가 움직인 설계변수가 얼마에서 얼마로 (쇼케이스 보고) ─────────

test("leverChange: 표 설계변수는 배율 되감기로 [최소, 최대] 양끝", () => {
  const m = normalizePrescribe({
    joint: { spans: { "table.pitch.k_rate": -0.2, "table.pitch.kp": 0.05 } },
    gain_export: { tables: { "pitch.k_rate": { axes: { mach: [0.1, 0.2] }, data: [3.136, 0.6253] } },
                   constants: { scas: {}, autopilot: {} } },
  });
  const c = leverChange(m);
  assert.equal(c.lever, "table.pitch.k_rate");
  assert.equal(c.kind, "table");
  assert.equal(c.span, -0.2);
  assert.deepEqual(c.to, [0.6253, 3.136]);
  assert.ok(Math.abs(c.from[0] - 0.781625) < 1e-9 && Math.abs(c.from[1] - 3.92) < 1e-9);
  assert.equal(leverLine(c), "table.pitch.k_rate −20% (0.7816~3.92 → 0.6253~3.136)");
});

test("leverChange: 상수의 from은 같은 형상의 기준값 그대로 — 음수 게인도 부호를 지킨다", () => {
  const ap = leverChange(normalizePrescribe({
    joint: { spans: { "fcl/Autopilot.ki_alt": 0.2 } },
    gain_export: { tables: null, constants: { scas: {}, autopilot: { ki_alt: 0.001176 } } },
  }), { base: { "fcl/Autopilot.ki_alt": 0.00098 } });
  assert.equal(ap.kind, "constant");
  assert.equal(ap.from, 0.00098);
  assert.equal(ap.absolute, false);
  const neg = leverChange(normalizePrescribe({
    joint: { spans: { "fcl/ScasAxis.pitch.kp": 0.1 } },
    // sweep._value_at: -2 + |-2|·0.1 = -1.8 — 음수 게인에서 +스팬은 0 쪽이다
    gain_export: { constants: { scas: { pitch: { kp: -1.8 } }, autopilot: {} } },
  }), { base: { "fcl/ScasAxis.pitch.kp": -2 } });
  assert.equal(neg.from, -2);
  assert.equal(leverLine(neg), "fcl/ScasAxis.pitch.kp +10% (-2 → -1.8)");
});

test("leverChange: 기준값 0인 상수는 절대 스텝 — 스팬을 되감아 지어낸 from을 내지 않는다", () => {
  // sweep._value_at: 기준 0이면 v = 0 + ZERO_STEP·s(= 0.01 × 0.2) — 되감기(to/(1+s))면 0.00167이 나왔다
  const m = normalizePrescribe({
    joint: { spans: { "fcl/ScasAxis.yaw.ki": 0.2 } },
    gain_export: { constants: { scas: { yaw: { ki: 0.002 } }, autopilot: {} } },
  });
  const c = leverChange(m, { base: { "fcl/ScasAxis.yaw.ki": 0 } });
  assert.equal(c.from, 0);
  assert.equal(c.to, 0.002);
  assert.equal(c.absolute, true);
  assert.equal(leverLine(c),
    "fcl/ScasAxis.yaw.ki 0 → 0.002 (기준값 0 — 스팬 +20%는 상대 변화가 아니라 절대 스텝)");
  // 기준값을 모르면(형상 지문 불일치 등) from은 null — 「기준값 미상」이라고 말한다
  const u = leverChange(m);
  assert.equal(u.from, null);
  assert.equal(u.absolute, false);
  assert.equal(leverLine(u), "fcl/ScasAxis.yaw.ki +20% (기준값 미상 → 0.002)");
});

test("leverBase: 구조 모델이 수정안과 같은 형상일 때만 기준값 표 — 다른 형상이면 null", () => {
  const graph = { fingerprint: "fpA", params: [
    { param_id: "fcl/ScasAxis.yaw.ki", value: 0 },
    { param_id: "fcl/Autopilot.kp_alt", value: 0.03 },
    { param_id: "fcl/Mixer.k_da", value: null },
  ] };
  assert.deepEqual(leverBase(graph, "fpA"), { "fcl/ScasAxis.yaw.ki": 0, "fcl/Autopilot.kp_alt": 0.03 });
  assert.equal(leverBase(graph, "fpB"), null);
  assert.equal(leverBase(graph, null), null);
  assert.equal(leverBase(null, "fpA"), null);
});

test("leverChange: 표 배율이 0 아래로 잘리는 스팬(s ≤ −1)은 되감을 수 없어 null", () => {
  const m = normalizePrescribe({
    joint: { spans: { "table.pitch.kp": -1 } },
    gain_export: { tables: { "pitch.kp": { axes: { mach: [0.1] }, data: [0] } } },
  });
  assert.equal(leverChange(m), null);
});

test("leverChange: 제안이 없으면 null — 지렛대를 지어내지 않는다", () => {
  assert.equal(leverChange(normalizePrescribe({})), null);
  assert.equal(leverChange(normalizePrescribe({ joint: { spans: { "table.x": -0.1 } } })), null);
  assert.equal(leverChange(normalizePrescribe({ joint: { spans: { "table.x": -0.1 } },
    gain_export: { tables: {} } })), null);
  assert.equal(leverLine(null), "지렛대 없음 — 조합 해가 움직인 설계변수가 없다");
});

test("unappliedLevers: [적용]이 작업 사본에 못 싣는 설계변수 — 표·AP·SCAS 상수 밖이면 든다", () => {
  const m = (spans) => normalizePrescribe({ joint: { spans } });
  assert.deepEqual(unappliedLevers(m({ "table.pitch.k_rate": -0.2, "fcl/Autopilot.ki_alt": 0.1,
    "fcl/ScasAxis.pitch.out_lo": 0.05 })), []);
  // limiter 소견의 설계변수 — 제안 형상에만 있고 store에는 자리가 없다
  assert.deepEqual(unappliedLevers(m({ "fcl/AlphaLimiter.margin": 0.2, "table.pitch.kp": 0.1 })),
    ["fcl/AlphaLimiter.margin"]);
  // 움직이지 않은 설계변수(서버 문턱 1e-6 미만)는 싣지 못해도 상관없다
  assert.deepEqual(unappliedLevers(m({ "fcl/Mixer.k_da": 1e-9 })), []);
  assert.deepEqual(unappliedLevers(normalizePrescribe({})), []);
});

test("applyExport: [적용]이 못 싣는 지렛대는 적용 문장에 이름을 들어 남긴다 — 조용히 빠지지 않는다", () => {
  const kv = new Map();
  const store = { get: (k) => kv.get(k), set: (k, v) => kv.set(k, v) };
  const ex = { tables: { "pitch.kp": { axes: { mach: [0.1] }, data: [1] } }, constants: {} };
  const plain = applyExport(store, ex, { sourceId: "r1" });
  assert.doesNotMatch(plain, /싣지 못하는/);
  const msg = applyExport(store, ex, { sourceId: "r1", unapplied: ["fcl/AlphaLimiter.margin"] });
  assert.match(msg, /^적용됨 — 테이블 1개 교체/);
  assert.match(msg, /⚠ \[적용\]이 싣지 못하는 지렛대 1개: fcl\/AlphaLimiter\.margin — /);
  assert.match(msg, /적용 뒤 작업 사본은 확인한 형상이 아니다$/);
  assert.equal(unappliedNote([]), null);
  assert.equal(unappliedNote(null), null);
  assert.match(unappliedNote(["a", "b"]), /^\[적용\]이 싣지 못하는 지렛대 2개: a, b — /);
});
