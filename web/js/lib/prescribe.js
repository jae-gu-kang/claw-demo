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
 *  바로 그 키들(게인 탭 apply와 동일)이다. 반환은 요약 문장.
 *  `unapplied`(unappliedLevers) — 조합 해가 움직였지만 store에 자리가 없어 못 싣는 설계변수. 적용은
 *  그대로 하되 문장에 **이름을 들어** 남긴다(조용히 빠지면 「확인 런 통과」를 적용본의 판정으로 읽는다). */
export function applyExport(store, gainExport, { sourceId = null, unapplied = [] } = {}) {
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
  const note = unappliedNote(unapplied);
  return `적용됨 — 테이블 ${nT}개 교체(배율 반영본)`
    + " · 시뮬('편집 게인 사용')·Autocode·블록도가 이 형상을 소비한다."
    + " 적용 후 재평가로 카드가 실제로 움직였는지 확인할 것"
    + (note ? ` · ⚠ ${note}` : "");
}

const sig4 = (v) => String(Number(Number(v).toPrecision(4)));
const rangeOf = (xs) => [Math.min(...xs), Math.max(...xs)];

/** 처방 형상의 설계변수 기준값 {param_id: value} — 구조 모델(normalizeGraph)이 **그 수정안과 같은
 *  형상**(지문 일치)에서 나왔을 때만. 다르면 null: 다른 형상의 값을 「얼마에서」로 말하지 않는다. */
export function leverBase(graph, fingerprint) {
  if (!graph || !fingerprint || graph.fingerprint !== fingerprint) return null;
  const out = {};
  for (const p of graph.params ?? []) {
    if (p.param_id && Number.isFinite(p.value)) out[p.param_id] = p.value;
  }
  return out;
}

/** 처방이 실제로 움직인 지렛대 — 조합 해에서 |스팬|이 가장 큰 설계변수와 그 값이 얼마에서 얼마로.
 *
 * {lever, span, kind, from, to, absolute} | null. 표 설계변수(`table.<자리>`)면 from·to는 표 값의
 * [최소, 최대]이고 상수(`fcl/…`)면 수 하나다. **to는 서버 제안(gain_export)이 정본**이다.
 * - 표: 웹은 곡선 배율(gain_scale)을 보내지 않아 기준 배율이 늘 1이다 — from은 배율 1+s를 되감는다
 *   (sweep._value_at). 배율이 0 아래로 잘리는 s ≤ −1이면 되감을 수 없어 null.
 * - 상수: from은 `base`(leverBase — 같은 형상의 구조 모델 값)에서 **그대로** 읽는다. 스팬에서 되감지
 *   않는 이유: 엔진은 기준값 0을 상대 배율이 아니라 **절대 스텝**으로 움직이고(sweep._value_at의 0 기준)
 *   범위 끝에서 자르기도 해서, 제안값과 스팬만으로는 기준값이 하나로 정해지지 않는다. 기준값이 0이면
 *   absolute=true(스팬 %는 상대 변화가 아니다). base가 없으면 from=null — 지어내지 않는다. */
export function leverChange(model, { base = null } = {}) {
  const spans = Object.entries(model?.joint?.spans ?? {}).filter(([, s]) => Number.isFinite(s));
  if (!spans.length || !model?.gainExport) return null;
  const [lever, span] = spans.reduce((a, b) => (Math.abs(b[1]) > Math.abs(a[1]) ? b : a));
  const ex = model.gainExport;
  if (lever.startsWith("table.")) {
    if (!(span > -1)) return null;
    const data = ex.tables?.[lever.slice("table.".length)]?.data;
    if (!Array.isArray(data) || !data.length) return null;
    const flat = data.flat(Infinity).map(Number);
    return { lever, span, kind: "table", absolute: false,
      from: rangeOf(flat.map((v) => v / (1 + span))), to: rangeOf(flat) };
  }
  const m = /^fcl\/(Autopilot|ScasAxis)\.(.+)$/.exec(lever);
  if (!m) return null;
  let to;
  if (m[1] === "Autopilot") to = ex.constants?.autopilot?.[m[2]];
  else {
    const [axis, key] = m[2].split(".");
    to = ex.constants?.scas?.[axis]?.[key];
  }
  if (!Number.isFinite(to)) return null;
  const v0 = base?.[lever];
  const from = Number.isFinite(v0) ? v0 : null;
  return { lever, span, kind: "constant", from, to, absolute: from === 0 };
}

// [적용](applyExport)이 작업 사본에 싣는 설계변수 — 게인 표(배율 반영본)와 AP·SCAS 상수뿐이다
// (엔진 proposal_export 계약). 리미터 여유·믹서·작동기·항법 등은 확인 런의 제안 형상에만 있고
// store에는 자리가 없다
const EXPORTABLE = /^(table\.|fcl\/(Autopilot|ScasAxis)\.)/;

/** 조합 해가 움직인 설계변수 중 [적용]이 작업 사본에 싣지 못하는 것 — 있으면 확인 런이 PASS여도
 *  적용 뒤 형상은 확인한 형상이 아니다(예: limiter 소견의 fcl/AlphaLimiter.margin). 0 스팬은 서버와
 *  같은 문턱(1e-6)으로 「안 움직임」이다. */
export function unappliedLevers(model) {
  return Object.entries(model?.joint?.spans ?? {})
    .filter(([k, s]) => Number.isFinite(s) && Math.abs(s) >= 1e-6 && !EXPORTABLE.test(k))
    .map(([k]) => k);
}

/** [적용]이 못 싣는 지렛대 한 문장 — 없으면 null. 수정안 패널(적용 전)과 적용 문장(적용 뒤)이 같은 말을 한다. */
export function unappliedNote(levers) {
  if (!levers?.length) return null;
  return `[적용]이 싣지 못하는 지렛대 ${levers.length}개: ${levers.join(", ")} — 작업 사본에는 게인 표와 `
    + "AP·SCAS 상수만 실린다. 확인 런은 이 값까지 바꾼 형상이었으므로 적용 뒤 작업 사본은 확인한 형상이 아니다";
}

/** 지렛대 한 줄 — "table.pitch.k_rate −20% (0.7817~3.92 → 0.6253~3.136)".
 *  기준값 0인 상수는 "… 0 → 0.002 (기준값 0 — 절대 스텝, 상대 % 아님)", 기준값을 모르면 "기준값 미상 → …". */
export function leverLine(change) {
  if (!change) return "지렛대 없음 — 조합 해가 움직인 설계변수가 없다";
  const val = (v) => (Array.isArray(v) ? (v[0] === v[1] ? sig4(v[0]) : `${sig4(v[0])}~${sig4(v[1])}`) : sig4(v));
  if (change.absolute) {
    return `${change.lever} ${val(change.from)} → ${val(change.to)} `
      + `(기준값 0 — 스팬 ${signed(change.span)}는 상대 변화가 아니라 절대 스텝)`;
  }
  const from = change.from == null ? "기준값 미상" : val(change.from);
  return `${change.lever} ${signed(change.span)} (${from} → ${val(change.to)})`;
}
