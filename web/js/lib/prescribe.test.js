/** lib/prescribe 계약 — 정량 처방 모델의 판단.

핵심 규약: ① 필요 변화량은 %로 옮기되 solvable=False의 사유가 값 자리를 차지한다
(빈칸·null 누출 금지) ② 적용은 서버가 배율을 이미 곱한 실효 테이블의 **전체
교체**이고(게인 탭 계약과 동일) 상수는 축별 병합이라 기존 키를 지우지 않는다.
*/

import assert from "node:assert/strict";
import test from "node:test";

import {
  applyExport, jointLines, mergeConstants, normalizePrescribe,
  prescribeRequest, singleRows,
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
