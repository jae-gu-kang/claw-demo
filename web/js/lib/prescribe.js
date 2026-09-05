/** 정량 처방 lib — "얼마나 고쳐야 넘나"의 화면 판단 (views/influence.js가 조립).

서버 influence_prescribe 응답을 정규화하고, 필요 변화량을 문장으로 옮기고,
[적용]의 store 쓰기 규칙을 한 곳에 둔다. **풀이는 전부 엔진**(pipeline/prescribe)
이다 — 여기서 스팬·문턱을 다시 계산하면 제안과 확인이 다른 산술 위에 선다.

적용 계약(게인 탭과 동일 경로): 테이블은 서버가 배율을 **이미 곱한** 실효본의
전체 교체이고(웹이 다시 곱하면 같은 산술이 두 곳에 적힌다), fcl/* 상수는 축별
병합이라 기존에 고쳐 둔 다른 키를 지우지 않는다.
*/

import { normalizeEvalReport } from "./evaluate.js";
import { fmtPercent, structuralRequest } from "./influence.js";

export function prescribeRequest(state, { resultId, evalResultId, cases,
                                          knobs, criteria, confirm, tSettle,
                                          tStep, tHold, fingerprint } = {}) {
  const body = { ...structuralRequest(state), result_id: resultId, cases };
  if (evalResultId) body.eval_result_id = evalResultId;
  if (knobs != null) body.knobs = knobs;
  if (criteria != null) body.criteria = criteria;
  if (confirm != null) body.confirm = confirm;
  if (tSettle != null) body.t_settle = tSettle;
  if (tStep != null) body.t_step = tStep;
  if (tHold != null) body.t_hold = tHold;
  if (fingerprint) body.fingerprint = fingerprint;
  return body;
}

export function normalizePrescribe(payload) {
  return {
    knobs: payload?.knobs ?? [],
    singles: payload?.singles ?? {},
    joint: payload?.joint ?? null,
    confirm: payload?.confirm ? normalizeEvalReport(payload.confirm) : null,
    gainExport: payload?.gain_export ?? null,
    proposalNotes: payload?.proposal_notes ?? [],
    warnings: payload?.warnings ?? [],
    fingerprint: payload?.fingerprint ?? null,
    sweepFingerprint: payload?.sweep_fingerprint ?? null,
    criteriaFingerprint: payload?.criteria_fingerprint ?? null,
    sweepResultId: payload?.sweep_result_id ?? null,
  };
}

const pct = (s) => fmtPercent(Math.abs(s), Math.abs(s) < 0.1 ? 1 : 0);
const signed = (s) => `${s >= 0 ? "+" : "−"}${pct(s)}`;

/** 단일 필요 변화량 → 평탄한 행 목록 [{knob, metric, solvable, text}].
 *
 * solvable=False의 **사유가 값 자리**다 — 빈칸이나 「—」로 두면 "안 풀린다"와
 * "안 풀었다"가 화면에서 같아진다.
 */
export function singleRows(model) {
  const rows = [];
  for (const [knob, metrics] of Object.entries(model.singles)) {
    for (const [metric, r] of Object.entries(metrics)) {
      let text;
      if (r.solvable && r.required_span === 0.0) {
        text = r.reason ?? "이미 문턱 안";
      } else if (r.solvable) {
        text = `${signed(r.required_span)} 필요`
          + (r.binding_case ? ` (결정 케이스 ${r.binding_case})` : "");
      } else {
        text = r.reason ?? "풀 수 없음 — 사유 미상";
        if (r.extrapolated_span != null) {
          text += ` · 참고 추정 ${signed(r.extrapolated_span)}`;
        }
      }
      rows.push({ knob, metric, solvable: !!r.solvable, text });
    }
  }
  return rows;
}

/** 조합 해 → 문장 목록 — 스팬·제외·위반·한계를 전부 낸다 (숨기지 않는다). */
export function jointLines(joint) {
  if (!joint) return ["조합 해 없음"];
  const lines = [];
  for (const [knob, s] of Object.entries(joint.spans ?? {})) {
    lines.push(`${knob} ${signed(s)}`);
  }
  for (const e of joint.excluded ?? []) {
    lines.push(`제외: ${e.knob} × ${e.metric} — ${e.reason}`);
  }
  for (const v of joint.violated ?? []) {
    lines.push(`위반: ${v.case} ${v.metric} 예측 ${Number(v.predicted).toPrecision(3)}`
      + ` (문턱 ${v.limit})`);
  }
  if (joint.reason) lines.push(joint.reason);
  if (joint.span_bound != null) {
    lines.push(`탐색 한계 ±${fmtPercent(joint.span_bound, 0)}`);
  }
  return lines;
}

/** 축별 상수 병합 — 기존 키를 지우지 않는다. */
export function mergeConstants(existing, add) {
  const out = { ...(existing ?? {}) };
  for (const [axis, kv] of Object.entries(add ?? {})) {
    out[axis] = { ...(out[axis] ?? {}), ...kv };
  }
  return out;
}

/** [적용] — 제안 형상을 설계 상태(store)에 쓴다. 시뮬·Autocode·블록도가 소비하는
 *  바로 그 키들(게인 탭 apply와 동일)이다. 반환은 요약 문장. */
export function applyExport(store, gainExport, { sourceId = null } = {}) {
  if (!gainExport) return "적용할 것이 없다 — 확인 런이 없었다";
  if (gainExport.tables) {
    store.set("gainTables", JSON.parse(JSON.stringify(gainExport.tables)));
    store.set("gainScheduleOff", false);
  }
  store.set("gainTablesSource", { kind: "prescribe", resultId: sourceId });
  const c = gainExport.constants ?? {};
  if (c.scas && Object.keys(c.scas).length) {
    store.set("scasParams", mergeConstants(store.get("scasParams"), c.scas));
  }
  if (c.autopilot && Object.keys(c.autopilot).length) {
    store.set("autopilotParams",
      { ...(store.get("autopilotParams") ?? {}), ...c.autopilot });
  }
  const nT = Object.keys(gainExport.tables ?? {}).length;
  return `적용됨 — 테이블 ${nT}개 교체(배율 반영본)`
    + " · 시뮬('편집 게인 사용')·Autocode·블록도가 이 형상을 소비한다."
    + " 적용 후 재평가로 카드가 실제로 움직였는지 확인할 것";
}
