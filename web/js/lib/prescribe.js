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

// ── 목적 선택 (04 §7.3) — 기준 충족 최소 수정(종전) / 성능 개선 ─────────────────
export const OBJECTIVE_LABEL = { min_change: "기준 충족 최소 수정", performance: "성능 개선" };

// 성능 목적의 세 묶음 — 화면은 묶음 가중 셋만 받고 엔진 지표 아홉(PERF_METRICS_DEFAULT)으로 펼친다
export const PERF_FAMILIES = {
  rms: { label: "추종 RMS", metrics: ["alt_rms", "spd_rms", "hdg_rms"] },
  ts: { label: "정착시간", metrics: ["alt_ts", "spd_ts", "hdg_ts"] },
  mp: { label: "오버슈트", metrics: ["alt_mp", "spd_mp", "hdg_mp"] },
};
export const SMOOTH_MAX = 10;  // 서버 PrescribeIn.smooth_weight 상한과 같다

/** 목적 입력 → 요청 필드. 최소 수정이면 목적만(성능 인자는 뜻이 없다). 잘못된 입력은 사유와 함께 throw —
 *  서버 422보다 먼저, 누른 자리에서 말한다. */
// 입력칸 값(문자열) 또는 수 → 수. 빈 칸은 오류다 — Number("")은 0이라 「가중 0(목적에서 뺌)」·
// 「급변 억제 없음」으로 조용히 바뀐다. 수가 아닌 글자는 NaN으로 넘겨 아래 범위 검사가 사유를 낸다
function fieldNum(v, what) {
  if (v == null || (typeof v === "string" && v.trim() === "")) throw new Error(`${what} 비었다`);
  return typeof v === "string" ? Number(v) : v;
}

export function objectiveFields({ objective = "min_change", weights = {}, smooth = 0.1 } = {}) {
  if (!(objective in OBJECTIVE_LABEL)) throw new Error(`알 수 없는 목적: ${objective}`);
  if (objective === "min_change") return { objective };
  const perf_weights = {};
  let any = false;
  for (const [fam, { label, metrics }] of Object.entries(PERF_FAMILIES)) {
    // 키가 없으면 1(엔진 기본값과 같은 뜻), 키가 있는데 비었으면 오류
    const w = fam in weights ? fieldNum(weights[fam], `${label} 가중이`) : 1;
    if (typeof w !== "number" || !Number.isFinite(w) || w < 0) {
      throw new Error(`${label} 가중은 0 이상 유한값이어야 한다: ${w}`);
    }
    if (w > 0) any = true;
    for (const m of metrics) perf_weights[m] = w;
  }
  // 가중이 전부 0이면 남는 것은 급변 억제뿐 — 답은 늘 「안 바꾼다」라 목적이 없다
  if (!any) throw new Error("성능 가중이 전부 0 — 줄일 목적이 없다");
  smooth = fieldNum(smooth, "급변 억제가");
  if (typeof smooth !== "number" || !Number.isFinite(smooth) || smooth < 0 || smooth > SMOOTH_MAX) {
    throw new Error(`급변 억제는 0~${SMOOTH_MAX} 사이여야 한다: ${smooth}`);
  }
  return { objective, perf_weights, smooth_weight: smooth };
}

export function prescribeRequest(state, { resultId, evalResultId, cases,
                                          knobs, confirm, tSettle,
                                          tStep, tHold, fingerprint, objective } = {}) {
  // 판정선은 싣지 않는다 — 서버가 선택 기체의 기준으로 판정하고 요청 기준은 거절한다(v1.54)
  const body = { ...structuralRequest(state), result_id: resultId, cases,
                 ...(objective ?? {}) };  // objectiveFields의 결과 — 없으면 서버 기본(최소 수정)
  if (evalResultId) body.eval_result_id = evalResultId;
  if (knobs != null) body.knobs = knobs;
  if (confirm != null) body.confirm = confirm;
  if (tSettle != null) body.t_settle = tSettle;
  if (tStep != null) body.t_step = tStep;
  if (tHold != null) body.t_hold = tHold;
  if (fingerprint) body.fingerprint = fingerprint;
  return body;
}

export function normalizePrescribe(payload) {
  return {
    // 옛 결과(목적 키 없음)는 최소 수정이다 — 목적 선택 전에는 그것뿐이었다
    objective: payload?.objective ?? payload?.joint?.objective ?? "min_change",
    knobs: payload?.knobs ?? [],
    singles: payload?.singles ?? {},
    joint: payload?.joint ?? null,
    confirm: payload?.confirm ? normalizeEvalReport(payload.confirm) : null,
    // 확인 런 실측 성능 변화(성능 목적에만) — 판정자는 confirm의 evaluate다, 이것은 정보
    confirmPerf: payload?.confirm?.perf ?? null,
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

const sig = (v) => String(Number(Number(v).toPrecision(4)));

/** 예측 지표 변화 중 가장 좋아진 것·가장 나빠진 것 — 아홉 지표 × 케이스를 다 늘어놓지 않는다. */
function bestWorst(perfPredicted) {
  let best = null;
  let worst = null;
  for (const [c, ms] of Object.entries(perfPredicted ?? {})) {
    for (const [m, r] of Object.entries(ms ?? {})) {
      const d = r?.delta_frac;
      if (!Number.isFinite(d)) continue;
      if (d < 0 && (!best || d < best.d)) best = { m, c, d };
      if (d > 0 && (!worst || d > worst.d)) worst = { m, c, d };
    }
  }
  return { best, worst };
}

/** 성능 목적 제외 — 사유별로 묶는다(같은 사유가 지표마다 되풀이되면 표가 된다). case null은 전 케이스. */
function perfExcludedLines(list) {
  const by = new Map();
  for (const e of list ?? []) {
    const who = e.case == null ? `${e.metric}(전 케이스)` : `${e.metric}@${e.case}`;
    by.set(e.reason, [...(by.get(e.reason) ?? []), who]);
  }
  return [...by].map(([reason, who]) => `성능 목적 제외(${reason}): ${who.join(", ")}`);
}

/** 조합 해 → 문장 목록 — 목적·스팬·제외·위반·한계를 전부 낸다 (숨기지 않는다). */
export function jointLines(joint) {
  if (!joint) return ["조합 해 없음"];
  const objective = joint.objective ?? "min_change";
  const lines = [`목적: ${OBJECTIVE_LABEL[objective] ?? objective}`];
  for (const [knob, s] of Object.entries(joint.spans ?? {})) {
    lines.push(`${knob} ${signed(s)}`);
  }
  // 바뀐 게인 수는 두 목적 모두 정보다(엔진 CHANGED_TOL 기준) — 옛 결과엔 없어 지어내지 않는다
  if (Number.isFinite(joint.changed_count)) lines.push(`바뀐 게인 ${joint.changed_count}개`);
  if (objective === "performance") {
    const ov = joint.objective_value;
    if (ov && Number.isFinite(ov.base) && Number.isFinite(ov.predicted)) {
      const rel = ov.base !== 0 ? (ov.predicted - ov.base) / Math.abs(ov.base) : null;
      lines.push(`예측 목적값 ${sig(ov.base)} → ${sig(ov.predicted)}`
        + (rel != null ? ` (${signed(rel)})` : ""));
      // 기준 형상이 하드 위반이면 제약이 요구한 변화가 목적값을 올릴 수 있다 — 개선이라 말하지 않는다
      if (ov.predicted > ov.base) lines.push("기준을 넘기느라 성능이 나빠진다 — 예측 목적값이 오른다");
    }
    const { best, worst } = bestWorst(joint.perf_predicted);
    if (best) lines.push(`가장 좋아짐 ${best.m}@${best.c} ${signed(best.d)}`);
    if (worst) lines.push(`가장 나빠짐 ${worst.m}@${worst.c} ${signed(worst.d)}`);
    if (joint.bound_active?.length) lines.push(`탐색 한계에 닿음: ${joint.bound_active.join(", ")}`);
    // 탐색 경계를 스윕 유효 표본까지 줄인 사유 — 한계에 닿은 자리가 「스윕이 실패로 본 게인」 앞이라는 말
    for (const r of joint.bound_reasons ?? []) lines.push(`탐색 경계: ${r}`);
    if (joint.hard_unmodelled?.length) {
      lines.push(`선형 모델 밖 하드 지표: ${joint.hard_unmodelled.map((h) => `${h.knob}×${h.metric}`).join(", ")}`
        + " — 비단조라 경계를 최소 표본까지 줄였다");
    }
    lines.push(...perfExcludedLines(joint.perf_excluded));
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

const BASE_SOURCE_LABEL = { sweep: "스윕 base", evaluate: "같은 형상의 평가", "evaluate+sweep": "스윕 base·같은 형상의 평가" };
const STATE_WORD = { inf: "미정착", none: "판정 불가" };

/** 확인 런 실측 성능 변화 → 문장 목록 — 지표마다 **가장 덜 좋아진** 케이스 한 줄과 그 자리의 예측.
 *  실측이 판정자가 아니다(확인 런 evaluate가 판정한다) — 예측이 맞았는지 보는 정보다. */
export function confirmPerfLines(confirmPerf, joint) {
  if (!confirmPerf) return [];
  const src = confirmPerf.base_source;
  const lines = [`실측 성능 변화 (기준: ${src ? BASE_SOURCE_LABEL[src] ?? src : "없음"})`];
  const cases = confirmPerf.cases ?? {};
  const metrics = confirmPerf.metrics
    ?? [...new Set(Object.values(cases).flatMap((ms) => Object.keys(ms ?? {})))];
  const odd = [];
  for (const m of metrics) {
    let worst = null;
    for (const [c, ms] of Object.entries(cases)) {
      const r = ms?.[m];
      if (!r) continue;
      if (Number.isFinite(r.delta_frac)) {
        if (!worst || r.delta_frac > worst.d) worst = { c, d: r.delta_frac };
        continue;
      }
      // 미정착(느림의 극한)과 판정 불가(값 없음)는 다른 말이다 — 뭉치지 않는다
      const side = r.new_state !== "ok" ? ["확인 런", r.new_state] : ["기준 런", r.base_state];
      odd.push(side[1] === "none" ? `${m}@${c} 판정 불가`
        : `${m}@${c} ${side[0]} ${STATE_WORD[side[1]] ?? side[1]}`);
    }
    if (!worst) continue;
    const p = joint?.perf_predicted?.[worst.c]?.[m]?.delta_frac;
    lines.push(`${m} 실측 ${signed(worst.d)} @${worst.c} (${Number.isFinite(p) ? `예측 ${signed(p)}` : "예측 없음"})`);
  }
  if (odd.length) lines.push(`비교 불가: ${odd.join(", ")}`);
  for (const o of confirmPerf.omitted ?? []) lines.push(`비교 제외 — ${o.case}: ${o.reason}`);
  // 기준을 썼지만 대조하지 못한 조건(평가 결과의 dt_plant 등) — 숨기지 않는다
  for (const n of confirmPerf.notes ?? []) lines.push(`주의: ${n}`);
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
