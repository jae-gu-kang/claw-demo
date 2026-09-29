/** lib/prescribe 계약 — 정량 처방 모델의 판단.

핵심 규약: ① 필요 변화량은 %로 옮기되 solvable=False의 사유가 값 자리를 차지한다
(빈칸·null 누출 금지) ② 적용은 서버가 배율을 이미 곱한 실효 테이블의 **전체
교체**이고(게인 탭 계약과 동일) 상수는 축별 병합이라 기존 키를 지우지 않는다.
*/

import assert from "node:assert/strict";
import test from "node:test";

import {
  OBJECTIVE_LABEL, PERF_FAMILIES, applyExport, confirmPerfLines, jointLines, leverBase, leverChange,
  leverLine, mergeConstants, normalizePrescribe, objectiveFields, prescribeRequest, singleRows,
  unappliedLevers, unappliedNote,
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


test("처방 요청은 판정선을 싣지 않는다 — 서버가 요청 기준을 거절한다(v1.54)", () => {
  const b = prescribeRequest({}, { resultId: "r", cases: [], criteria: { margin: { pm_min_deg: 50 } } });
  assert.equal("criteria" in b, false);
});


// ── 목적 선택 — 기준 충족 최소 수정 / 성능 개선 (04 §7.3) ─────────────────────

const perfJoint = {
  objective: "performance", solvable: true, reason: null,
  spans: { "table.pitch.kp": 0.2, "table.spd.kp": 0.0004 },
  changed_knobs: ["table.pitch.kp"], changed_count: 1,
  excluded: [], violated: [], span_bound: 0.2,
  perf_metrics: ["alt_rms", "alt_ts", "spd_ts", "alt_mp"],
  perf_weights: { alt_rms: 1, alt_ts: 1, spd_ts: 1, alt_mp: 1 }, smooth_weight: 0.1,
  objective_value: { base: 2.0, predicted: 1.7, smoothing: 0.1 },
  perf_predicted: {
    A: { alt_rms: { base: 5, predicted: 4.5, delta_frac: -0.1 },
         alt_ts: { base: 10, predicted: 7.5, delta_frac: -0.25 },
         spd_ts: { base: 10, predicted: 10.3, delta_frac: 0.03 } },
    B: { alt_ts: { base: 12, predicted: 11, delta_frac: -0.0833 } },
  },
  perf_excluded: [
    { metric: "alt_mp", case: null, reason: "비단조 — 스팬 안 경향이 뒤집혀 선형 모델에서 제외",
      knobs: ["table.pitch.kp"] },
    { metric: "spd_ts", case: "B", reason: "창 안 미정착·발산 — 선형 모델 정의역 밖" },
    { metric: "alt_rms", case: "B", reason: "창 안 미정착·발산 — 선형 모델 정의역 밖" },
  ],
  bound_active: ["table.pitch.kp"],
};

test("목적 이름 — 두 목적 우리말, 기본은 최소 수정", () => {
  assert.equal(OBJECTIVE_LABEL.min_change, "기준 충족 최소 수정");
  assert.equal(OBJECTIVE_LABEL.performance, "성능 개선");
  assert.equal(normalizePrescribe({}).objective, "min_change");
  assert.equal(normalizePrescribe({ objective: "performance" }).objective, "performance");
});

test("objectiveFields: 최소 수정은 목적만 — 성능 인자를 싣지 않는다", () => {
  assert.deepEqual(objectiveFields({ objective: "min_change", weights: { rms: 5 }, smooth: 3 }),
    { objective: "min_change" });
  assert.deepEqual(objectiveFields(), { objective: "min_change" });
});

test("objectiveFields: 성능은 세 묶음 가중을 아홉 지표 가중으로 펼친다", () => {
  const f = objectiveFields({ objective: "performance", weights: { rms: 2, ts: 1, mp: 0 }, smooth: 0.3 });
  assert.equal(f.objective, "performance");
  assert.equal(f.smooth_weight, 0.3);
  assert.equal(Object.keys(f.perf_weights).length, 9);
  for (const m of PERF_FAMILIES.rms.metrics) assert.equal(f.perf_weights[m], 2);
  for (const m of PERF_FAMILIES.mp.metrics) assert.equal(f.perf_weights[m], 0);
  assert.deepEqual(PERF_FAMILIES.ts.metrics, ["alt_ts", "spd_ts", "hdg_ts"]);
  // 빈 가중은 1(엔진 기본값과 같은 뜻)
  const d = objectiveFields({ objective: "performance" });
  assert.equal(d.perf_weights.hdg_mp, 1);
  assert.equal(d.smooth_weight, 0.1);
});

test("objectiveFields: 잘못된 입력은 제출 전에 사유와 함께 막는다", () => {
  const bad = (o) => assert.throws(() => objectiveFields({ objective: "performance", ...o }));
  bad({ weights: { rms: -1 } });
  bad({ weights: { ts: Number.NaN } });
  bad({ weights: { rms: 0, ts: 0, mp: 0 } });  // 목적이 없다
  bad({ smooth: -0.1 });
  bad({ smooth: 11 });
  bad({ smooth: Number.POSITIVE_INFINITY });
  assert.throws(() => objectiveFields({ objective: "fastest" }), /목적/);
  assert.throws(() => objectiveFields({ objective: "performance", weights: { rms: 0, ts: 0, mp: 0 } }),
    /전부 0/);
});

test("요청 본문 — 목적 필드가 실린다(최소 수정이면 목적만)", () => {
  const perf = prescribeRequest({}, { resultId: "r", cases: [],
    objective: objectiveFields({ objective: "performance", smooth: 0.5 }) });
  assert.equal(perf.objective, "performance");
  assert.equal(perf.smooth_weight, 0.5);
  assert.equal(perf.perf_weights.alt_rms, 1);
  const mc = prescribeRequest({}, { resultId: "r", cases: [] });
  assert.equal("objective" in mc, false);  // 안 보내면 서버 기본(최소 수정)
});

test("조합 줄(최소 수정) — 목적 이름과 바뀐 게인 수가 정보로 선다", () => {
  const lines = jointLines({ ...payload.joint, objective: "min_change",
    changed_knobs: ["table.pitch.kp"], changed_count: 1 });
  assert.equal(lines[0], "목적: 기준 충족 최소 수정");
  assert.ok(lines.includes("바뀐 게인 1개"));
  assert.ok(!lines.some((l) => /목적값/.test(l)));
  // 옛 결과(목적 키 없음)는 최소 수정으로 읽는다 — 바뀐 게인 수는 지어내지 않는다
  const old = jointLines(payload.joint);
  assert.equal(old[0], "목적: 기준 충족 최소 수정");
  assert.ok(!old.some((l) => /바뀐 게인/.test(l)));
});

test("조합 줄(성능) — 예측 목적값·최선/최악 지표·탐색 한계·제외 사유를 요약한다", () => {
  const lines = jointLines(perfJoint);
  const all = lines.join(" | ");
  assert.equal(lines[0], "목적: 성능 개선");
  assert.match(all, /예측 목적값 2 → 1\.7 \(−15%\)/);
  assert.match(all, /가장 좋아짐 alt_ts@A −25%/);
  assert.match(all, /가장 나빠짐 spd_ts@A \+3\.0%/);
  assert.match(all, /탐색 한계에 닿음: table\.pitch\.kp/);
  // 제외는 사유별로 묶는다 — 같은 사유가 줄마다 되풀이되지 않는다
  assert.equal(lines.filter((l) => /미정착/.test(l)).length, 1);
  assert.match(all, /성능 목적 제외\(창 안 미정착·발산 — 선형 모델 정의역 밖\): spd_ts@B, alt_rms@B/);
  assert.match(all, /alt_mp\(전 케이스\)/);
  assert.ok(lines.includes("바뀐 게인 1개"));
  assert.ok(!/null|undefined|NaN/.test(all), all);
});

test("조합 줄(성능) — 기준을 넘기느라 목적값이 오르면 개선이라 말하지 않는다", () => {
  const lines = jointLines({ ...perfJoint, objective_value: { base: 1.0, predicted: 1.2, smoothing: 0 },
    perf_predicted: { A: { alt_ts: { base: 10, predicted: 12, delta_frac: 0.2 } } } });
  const all = lines.join(" | ");
  assert.match(all, /예측 목적값 1 → 1\.2 \(\+20%\)/);
  assert.match(all, /기준을 넘기느라 성능이 나빠진다/);
  assert.doesNotMatch(all, /가장 좋아짐/);  // 좋아진 지표가 없으면 그 칸을 세우지 않는다
});

test("조합 줄(성능) — 쓸 지표가 없으면 목적값 없이 사유만", () => {
  const lines = jointLines({ objective: "performance", solvable: false, spans: null,
    objective_value: null, perf_predicted: {}, bound_active: [], changed_knobs: [], changed_count: 0,
    perf_excluded: [], reason: "성능 목적 지표가 하나도 선형 모델에 들지 않는다", span_bound: 0.2 });
  const all = lines.join(" | ");
  assert.match(all, /하나도 선형 모델에 들지 않는다/);
  assert.doesNotMatch(all, /목적값/);
  assert.ok(!/null|undefined|NaN/.test(all), all);
});

test("confirmPerfLines: 실측 변화와 예측을 나란히 — 지표별 최악 케이스 한 줄", () => {
  const cp = {
    base_source: "sweep", metrics: ["alt_ts", "spd_ts", "alt_rms"],
    cases: {
      A: { alt_ts: { base: 10, new: 8, delta_frac: -0.2, base_state: "ok", new_state: "ok" },
           spd_ts: { base: 10, new: null, delta_frac: null, base_state: "ok", new_state: "inf" },
           alt_rms: { base: null, new: 4, delta_frac: null, base_state: "none", new_state: "ok" } },
      B: { alt_ts: { base: 12, new: 11.4, delta_frac: -0.05, base_state: "ok", new_state: "ok" } },
    },
    omitted: [{ case: "C", reason: "기준 형상의 실측이 없다" }],
  };
  const lines = confirmPerfLines(cp, perfJoint);
  const all = lines.join(" | ");
  assert.match(lines[0], /스윕 base/);
  // 지표별 가장 나쁜(가장 덜 좋아진) 케이스 — alt_ts는 B(−5 %), 예측은 B −8.3 %
  assert.match(all, /alt_ts 실측 −5\.0% @B \(예측 −8\.3%\)/);
  // 미정착과 판정 불가는 다른 말이다
  assert.match(all, /spd_ts@A 확인 런 미정착/);
  assert.match(all, /alt_rms@A 판정 불가/);
  assert.match(all, /C: 기준 형상의 실측이 없다/);
  assert.ok(!/null|undefined|NaN/.test(all), all);
  assert.deepEqual(confirmPerfLines(null, perfJoint), []);
  assert.deepEqual(normalizePrescribe({ confirm: { cards: [], perf: cp } }).confirmPerf, cp);
  assert.equal(normalizePrescribe(payload).confirmPerf, null);
});

test("objectiveFields: 빈 칸은 0이 아니라 입력 오류 — 입력칸 문자열은 수로 읽는다", () => {
  const perf = (o) => objectiveFields({ objective: "performance", ...o });
  // 입력칸은 문자열을 준다 — Number("")은 0이라 「가중 0(목적에서 뺌)」으로 조용히 바뀐다
  assert.throws(() => perf({ weights: { rms: "" } }), /추종 RMS 가중이 비었다/);
  assert.throws(() => perf({ weights: { ts: "  " } }), /정착시간 가중이 비었다/);
  assert.throws(() => perf({ weights: { mp: null } }), /오버슈트 가중이 비었다/);
  assert.throws(() => perf({ smooth: "" }), /급변 억제가 비었다/);
  assert.throws(() => perf({ weights: { rms: "abc" } }), /추종 RMS 가중/);
  const f = perf({ weights: { rms: "2", ts: "0.5", mp: "0" }, smooth: "0.25" });
  assert.equal(f.perf_weights.alt_rms, 2);
  assert.equal(f.perf_weights.spd_ts, 0.5);
  assert.equal(f.perf_weights.hdg_mp, 0);
  assert.equal(f.smooth_weight, 0.25);
});

test("조합 줄(성능) — 탐색 경계 축소 사유와 선형 모델 밖 하드 지표를 짧게 든다", () => {
  const lines = jointLines({ ...perfJoint,
    bound_limits: { "table.pitch.kp": { lo: -0.2, hi: 0.1,
      reason: "+20 % 표본이 미정착(alt_ts)@A — 탐색을 +10 %로 줄였다" } },
    bound_reasons: ["table.pitch.kp: +20 % 표본이 미정착(alt_ts)@A — 탐색을 +10 %로 줄였다"],
    hard_unmodelled: [{ knob: "table.spd.kp", metric: "surf_sat_frac" }] });
  const all = lines.join(" | ");
  assert.match(all, /탐색 경계: table\.pitch\.kp: \+20 % 표본이 미정착\(alt_ts\)@A — 탐색을 \+10 %로 줄였다/);
  assert.match(all, /선형 모델 밖 하드 지표: table\.spd\.kp×surf_sat_frac/);
  // 옛 결과(키 없음)는 그 줄을 세우지 않는다
  assert.doesNotMatch(jointLines(perfJoint).join(" | "), /탐색 경계|선형 모델 밖/);
});

test("confirmPerfLines: 대조하지 못한 조건(노트)을 든다", () => {
  const lines = confirmPerfLines({ base_source: "evaluate", metrics: [], cases: {}, omitted: [],
    notes: ["평가 결과는 dt_plant를 기록하지 않는다 — 확인 런(dt_plant=0.01)과 적분 간격이 같은지는 대조하지 못했다"] },
  perfJoint);
  assert.match(lines.join(" | "), /주의: 평가 결과는 dt_plant를 기록하지 않는다/);
});
