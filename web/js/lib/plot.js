/** 플롯 수치 계층 (뷰·캔버스와 분리, 테스트 대상) — 스케일·눈금·상태색·격자 피벗.

마진 맵 시각화(06 §4)의 수치 부분. 캔버스 그리기 자체는 views/plots.js.
*/

import { marginUnstable } from "./loops.js"; // 발산 칸 판정 — 마진 맵 탭·결과 브리핑과 한 정의

export function linScale(d0, d1, r0, r1) {
  const k = (r1 - r0) / (d1 - d0 || 1);
  return (v) => r0 + (v - d0) * k;
}

export function niceTicks(min, max, n = 5) {
  if (!(max > min)) return [min];
  const span = max - min;
  const step0 = span / Math.max(1, n);
  const mag = 10 ** Math.floor(Math.log10(step0));
  const step = [1, 2, 5, 10].map((m) => m * mag).find((s) => span / s <= n) ?? 10 * mag;
  const out = [];
  for (let v = Math.ceil(min / step - 1e-9) * step; v <= max + 1e-9; v += step) {
    const t = Math.round(v * 1e9) / 1e9;
    out.push(t === 0 ? 0 : t); // -0 정규화 (ceil의 음의 영)
  }
  return out;
}

/** 판정 상태색 팔레트 — 애플 시스템 컬러 (히트맵 셀·범례·엔벨로프 맵이 공유). */
export const STATUS = {
  ok: "#34c759", // 양호
  warn: "#ff9500", // 주의
  bad: "#ff3b30", // 부족·위반
  na: "#aeaeb2", // 판정 불가·트림 불가
};

/** 판정 상태 넷 → 화면 이름 — 엔진 design/criteria.py STATUSES와 그 머리말의 이름 그대로(한 표).
 *  키 순서가 범례 순서다. 다른 탭(영향성·결과·게인)도 이 표를 쓴다 — 이름을 탭마다 다시 적지 않는다. */
export const STATUS_LABEL = Object.freeze({
  fail: "불합격",
  warn: "합격·주의",
  ok: "합격·권장 충족",
  na: "판정 불가",
});

/** 판정 상태 → 상태색. 모르는 값·없음은 판정 불가(회색) — 색을 짐작하지 않는다. */
export function statusColor(status) {
  if (status === "fail") return STATUS.bad;
  if (status === "warn") return STATUS.warn;
  if (status === "ok") return STATUS.ok;
  return STATUS.na;
}

const isStatus = (s) => Object.prototype.hasOwnProperty.call(STATUS_LABEL, s);

/** 마진 칸 하나의 판정 — **서버가 실은 판정**(margins[loop].pm_status | gm_status, 엔진 MarginCriteria.judge_pm·
 *  judge_gm, 고른 기체 프로파일의 기준)을 읽는다. 화면이 PM·GM 문턱으로 다시 짜지 않는다 — 종전엔 웹이 PM 30~45°를
 *  주의로 칠했는데 엔진은 PM<45를 불합격으로 판정해 두 탭이 같은 칸을 다르게 불렀다.
 *  폐루프 발산 칸도 서버 판정이 이미 접어 넣었다(엔진의 나선 모드 예외 규칙 포함) — 웹이 따로 덮어쓰지 않는다
 *  (판정은 한 자리). 판정 필드가 없는 옛 결과·마진 없음은 na — 브라우저에서 다시 판정하지 않는다. key "pm_deg" | "gm_db". */
export function marginCellStatus(m, key) {
  if (!m) return "na";
  // 엔진이 「면제 안 되는 발산이라 불합격」이라고 표시한 칸 — 축별 판정(잰 그대로의 부호 있는 판독)보다 칸 판정이 이긴다.
  // 판정을 여기서 다시 짜는 것이 아니라 엔진 표시(design/criteria.py judge_cell)를 읽는다
  if (m.diverged === true) return "fail";
  const s = m[key === "pm_deg" ? "pm_status" : "gm_status"];
  return isStatus(s) ? s : "na";
}

/** 옛 결과 안내 — 칸 판정(pm_status)이 실리기 전에 저장된 결과는 전 칸이 판정 불가로 보인다. */
export const OLD_RESULT_HINT = "옛 결과 — 판정이 실리기 전에 저장됐다, 다시 계산하면 선다";

/** 결과에 칸 판정이 실렸나 — 마진이 있는 칸 중 하나라도 pm_status를 가지면 true. 마진이 하나도 없으면 true(말할 게 없다). */
export function hasMarginStatuses(body) {
  let any = false;
  for (const e of body?.cases ?? []) {
    for (const m of Object.values(e?.margins ?? {})) {
      if (!m || typeof m !== "object") continue;
      if (isStatus(m.pm_status)) return true;
      any = true;
    }
  }
  return !any;
}

/** 판정선 한 줄 — GET /profiles/{id}/criteria의 적용값(applied.margin)과 판정선 뜻(lines)에서.
 *  metric "pm_deg" | "gm_db". 선을 못 읽으면 null(수치를 지어내지 않는다). */
export function criteriaLineText(criteriaResp, metric) {
  const ln = (criteriaResp?.lines ?? []).find((l) => l?.metric === metric);
  const mc = criteriaResp?.applied?.margin;
  if (!ln || !mc) return null;
  const op = ln.direction === "max" ? "≤" : "≥";
  const val = (k) => (k && typeof mc[k] === "number" && Number.isFinite(mc[k]) ? mc[k] : null);
  const u = ln.unit === "°" ? "°" : ln.unit ? ` ${ln.unit}` : "";
  const pass = val(ln.pass_key);
  if (pass == null) return null;
  const rec = val(ln.rec_key);
  return `${ln.label} ${op}${pass}${u} 합격` + (rec != null ? ` · ${op}${rec}${u} 권장` : "");
}

/** 마진 탭 판정선 범례 — 판정선(기체 기준)과 색 넷의 이름. 기준을 못 읽었으면 색 이름만. */
export function marginLegendText(criteriaResp) {
  const lines = ["pm_deg", "gm_db"].map((k) => criteriaLineText(criteriaResp, k)).filter(Boolean);
  const colours = `색 = 서버 판정: ${Object.values(STATUS_LABEL).join(" · ")}`;
  return lines.length ? `판정선: ${lines.join(" · ")} — ${colours}` : colours;
}

/** 트림 판정 → 비행 엔벨로프 셀 (01 §4.1 자동 판정 플래그 기반 근사).

우선순위: 불가(미수렴/잔차) > 실속 근접(α 여유) > 포화(추력·타면) > 가능.
실속 경계 테이블 기반 정밀 경계선은 공력 정본 확정 후 [백로그].
*/
export function trimEnvelopeCell(r) {
  if (r.state) return trimStateCell(r);
  if (!r.converged || r.flags.residual_ok === false) {
    return { kind: "infeasible", color: STATUS.na, text: "불가" };
  }
  if (r.flags.alpha_margin_ok === false) {
    return { kind: "stall", color: STATUS.bad, text: "실속≈" };
  }
  if (r.flags.saturation_ok === false) {
    return { kind: "saturated", color: STATUS.warn, text: "포화" };
  }
  return { kind: "ok", color: STATUS.ok, text: "가능" };
}

/** 조건 상태(05 §11.3 — 엔진 claw.opspace.states) → 지도 셀. 서버가 트림 결과에 state를 실으면(격자 체계 ②) 이
 *  표를 쓰고, 옛 결과(state 없음)는 위 판정 플래그 규칙을 쓴다. 키 순서가 범례 순서다. 계산 실패(다시 풀 대상)와
 *  물리적 불가(그 조건의 답)와 제약 도달(탐색 제약 — 불가 근거 없음)을 **다른 색**으로 가른다 — 종전 「트림 불가」
 *  한 칸이 셋을 섞었다. 모델 부족은 트림하지 않은 점이다(요구 안인데 모델 유효영역 밖). */
export const TRIM_STATE_CELL = Object.freeze({
  computable: { color: STATUS.ok, text: "가능", label: "계산 가능" },
  // 상태가 아니라 칸 종류 — 계산 가능한 트림(날 수 있는 평형)이 판정선(스로틀·엘레본 포화, α 여유)을 넘은 것. 엔진은 이것을
  // 상태와 따로 margin으로 싣는다(05 §11.3). 물리적 불가와 섞으면 날 수 있는 조건이 불가로 보인다. 조건 판정은 이것을
  // 채택한다(v1.65 — 날 수 있는 평형이라 설계에 쓴다) — 칸은 채택된 채 미달을 표시한다
  margin_short: { color: "#ffcc00", text: "여유↓", label: "계산 가능·여유 미달" },
  // 이 셋도 상태가 아니라 칸 종류 — 조건 판정(05 §11.3 · 이관 8단계, 서버 verdict)이 계산 가능한 트림을 채택하지
  // 않은 까닭. 제한 위반은 풀린 평형이 적용 제한(실속 경계·α 리미터·최대 동압·M_NO)을 넘은 것 — v1.64까지 「물리적
  // 불가(실속각 이상)」로 부르던 수렴 해가 여기다. 모델 범위 밖은 **트림한** 해가 DB 받음각·마하·연료 범위를 벗어난
  // 것이라 트림하지 않은 model_gap과 다르다(후속 조치가 다르다 — 모델 보강 대 격자 조정). 판정 미완료는 잴 근거
  // (실속표 축)가 없는 것 — 통과도 위반도 아니다
  limit_violation: { color: "#af52de", text: "제한", label: "계산 가능·제한 위반" },
  model_invalid: { color: "#5ac8fa", text: "범위밖", label: "계산 가능·모델 범위 밖" },
  unevaluated: { color: "#d1d1d6", text: "미평가", label: "계산 가능·판정 미완료" },
  infeasible: { color: STATUS.bad, text: "불가", label: "물리적 불가" },
  constraint_hit: { color: STATUS.warn, text: "제약", label: "제약 도달·미수렴" },
  calc_failed: { color: "#636366", text: "실패", label: "계산 실패" },
  model_gap: { color: STATUS.na, text: "모델밖", label: "모델 부족 (트림 안 함)" },
});

// 물리적 불가 셀의 글 — 첫 근거(엔진 사유 순서)를 짧게. 표·툴팁은 사유 전량을 싣는다. 옛 결과의 사유(판정선 포화·
// α 여유)도 읽을 수 있게 남긴다
const INFEASIBLE_TEXT = {
  thrust_deficit: "추력", idle_thrust_excess: "추력↑", pitch_moment_short: "타면", above_stall: "실속",
  throttle_high: "추력", de: "타면", throttle_low: "추력↓", alpha_margin: "실속≈", below_V_S: "실속", "1g_unreachable": "1g",
};

/** 조건 상태 사유 코드 → 사람 글 (엔진 claw.opspace.states). 모르는 코드는 그대로. */
export const STATE_REASON_LABEL = Object.freeze({
  thrust_deficit: "최대 추력에서도 감속 — 추력 부족 확인", idle_thrust_excess: "아이들에서도 가속 — 수평 감속 불가 확인",
  pitch_moment_short: "엘레본 한계에서 피치 모멘트 부족 확인", above_stall: "실속각 이상",
  balance_not_found: "한계 고정 평형 해 없음 — 원인 미확인", trim_inside_limit: "한계 안쪽에 트림이 있음 — 다시 풀 대상",
  throttle_high: "스로틀 상한", throttle_low: "스로틀 하한", de_high: "엘레본 상한", de_low: "엘레본 하한",
  de: "엘레본 포화", alpha_margin: "α 여유 미달",
  not_converged: "미수렴", alpha_search_bound: "받음각 탐색 상한", alpha_search_lower: "받음각 탐색 하한",
  below_V_S: "1g 실속 속도 V_S보다 느림", above_V_S: "V_S보다 빠름 (탐색 상한이 좁을 수 있음)",
  stall_basis_missing: "실속 근거 자료 없음 (판단 미완료)", "1g_unreachable": "1g 도달 불가",
  // 조건 판정(opspace/verdict.py) 사유 — 제한·모델 항목
  stall_boundary: "실속 경계 위반", limiter_clips_trim: "α 리미터가 트림을 유지하지 못함", q_max: "최대 동압 초과",
  mach_no: "M_NO 초과", db_mach: "DB 마하 범위 밖", db_alpha: "DB 받음각 범위 밖", fuel_range: "연료 범위 밖",
});

export const stateReasonText = (codes) => (codes ?? []).map((c) => STATE_REASON_LABEL[c] ?? c).join(" · ");

// 여유 판정 사유 → 글. 스로틀 상한 판정선은 추진 여유다(추력이 모자란 것이 아니다)
const MARGIN_REASON_LABEL = Object.freeze({
  throttle_high: "추진 여유 미달", throttle_low: "스로틀 하한 여유 미달", de: "엘레본 여유 미달",
  alpha_margin: "α 여유 미달",
});

const isMarginShort = (r) => r.state === "computable" && r.margin?.status === "short";

// 조건 판정의 제외 항목 → 칸 종류. 트림 항목 제외는 상태 표 그대로(물리적 불가·계산 실패·제약 도달)라 여기 없다.
// 여유 미달은 제외가 아니다(v1.65 채택 정책 — 채택된 해에 margin으로만 붙는다). 제한 항목이 「미평가」로 빠진 것(잴
// 근거 없음)은 위반이 아니다 — 판정 미완료로 따로 둔다
const EXCLUSION_KIND = { limits: "limit_violation", model: "model_invalid" };

/** 조건 판정(서버 verdict)이 실린 계산 가능 결과 → 칸 종류, 판정이 없거나 트림 항목이 계산 가능이 아니면 null
 *  (조건 상태 규칙으로). 채택 → computable(여유 미달이면 margin_short — 채택된 채 표시), 아니면 제외 항목의 칸. */
function verdictKind(r) {
  const v = r.verdict;
  if (!v || r.state !== "computable" || v.trim?.status !== "computable") return null;
  if (v.adopted || !v.exclusion) return v.margin?.status === "short" ? "margin_short" : "computable";
  const cat = v.exclusion.category;
  if (cat === "limits" && v.limits?.status === "unevaluated") return "unevaluated";
  return EXCLUSION_KIND[cat] ?? null;
}

/** 조건 판정 제외 항목 → 이름 (opspace/verdict.py 항목 순서). 트림 탭 근거 열과 자동 설계 점 표가 같은 이름을 쓴다.
 *  여유는 제외 항목이 아니다(v1.65) — 여유 미달 글은 marginShortText. */
export const EXCLUSION_CATEGORY_LABEL = Object.freeze({
  trim: "트림 불성립", model: "모델 범위 밖", limits: "제한 위반",
});

/** 여유 미달 사유 글(「추진 여유 미달」) — 판정이 있으면 verdict.margin, 옛 결과는 margin. 미달이 아니면 빈 글. */
export function marginShortText(r) {
  const m = r?.verdict ? r.verdict.margin : r?.margin;
  if (m?.status !== "short") return "";
  return m.reasons.map((c) => MARGIN_REASON_LABEL[c] ?? STATE_REASON_LABEL[c] ?? c).join(" · ");
}

// α 리미터 제외의 근거 — 문턱을 넘었다는 말만이 아니라 작동식이 트림을 못 쥐는 수치(엔진 limits.detail.limiter)
const limiterText = (d) => d ? `${STATE_REASON_LABEL.limiter_clips_trim} — α_trim ${sig(d.alpha_trim)} > α_max `
  + `${sig(d.alpha_max)}` : STATE_REASON_LABEL.limiter_clips_trim;

/** 조건 판정이 채택하지 않은 까닭 글 — 제외 항목의 사유(「실속 경계 위반」). 채택·판정 없음이면 빈 글. */
export function verdictExclusionText(r) {
  const ex = r?.verdict && !r.verdict.adopted ? r.verdict.exclusion : null;
  if (!ex) return "";
  const lim = ex.category === "limits" ? r.verdict.limits?.detail?.limiter : undefined;
  return ex.reasons.map((c) => c === "limiter_clips_trim" ? limiterText(lim) : STATE_REASON_LABEL[c] ?? c).join(" · ");
}

/** 표 근거 열의 조건 판정 글 — 채택하지 않은 결과만 「자동 설계 제외 (제한 위반) — 실속 경계 위반」. 트림 항목
 *  제외는 조건 상태 사유(같은 사유)가 이미 적혀 있어 되풀이하지 않는다. */
export function verdictEvidenceText(r) {
  const ex = r?.verdict && !r.verdict.adopted ? r.verdict.exclusion : null;
  if (!ex || ex.category === "trim") return "";
  const reasons = verdictExclusionText(r);
  return `자동 설계 제외 (${EXCLUSION_CATEGORY_LABEL[ex.category] ?? ex.category})${reasons ? ` — ${reasons}` : ""}`;
}

/** 트림 결과 행(state 있음) 또는 기본 격자 점(state = model_gap) → 지도 셀. 모르는 상태는 null(빈 칸).
 *  조건 판정이 실린 결과는 그 판정으로(채택·채택된 여유 미달·제한 위반·모델 범위 밖), 옛 결과는 margin으로 가른다. */
export function trimStateCell(r) {
  const base = TRIM_STATE_CELL[r.state];
  if (!base) return null;
  const vk = verdictKind(r);
  if (vk) return { kind: vk, color: TRIM_STATE_CELL[vk].color, text: TRIM_STATE_CELL[vk].text };
  if (!r.verdict && isMarginShort(r)) return { kind: "margin_short", color: TRIM_STATE_CELL.margin_short.color,
    text: TRIM_STATE_CELL.margin_short.text };
  const reasons = r.state_reasons ?? [];
  const first = reasons.find((c) => INFEASIBLE_TEXT[c]);
  return { kind: r.state, color: base.color,
    text: r.state === "infeasible" && first ? INFEASIBLE_TEXT[first] : base.text };
}

/** 표의 상태 글 — 상태에 채택하지 않은 까닭을 붙인다(「계산 가능 · 실속 경계 위반」·「계산 가능 · 추진 여유 미달」).
 *  조건 판정이 있으면 그 제외 사유로, 옛 결과는 여유 판정으로. */
export function trimStateLabel(r) {
  const base = TRIM_STATE_CELL[r.state]?.label ?? r.state;
  const vk = verdictKind(r);
  if (vk === "computable") return base;
  if (vk === "margin_short") return `${base} · ${marginShortText(r)}`;
  if (vk) return `${base} · ${verdictExclusionText(r)}`;
  if (r.verdict || !isMarginShort(r)) return base;
  return `${base} · ${marginShortText(r)}`;
}

// 근거 글의 수치 — 유효 3자리(0.0525 · −0.022). 고정한 채널의 한계값은 그 단위로
const sig = (x) => String(Number(Number(x).toPrecision(3)));
const FIXED_TEXT = {
  throttle: (v) => `스로틀 ${Math.round(v * 100)} %`,
  de: (v) => `엘레본 ${sig(v)} rad`,
};
const FREE_TEXT = { alpha: (v) => `α ${sig(v)}`, de: (v) => `δe ${sig(v)}`, throttle: (v) => `스로틀 ${sig(v)}` };
const EQUATION_TEXT = { vdot: (v) => `V̇ ${sig(v)} m/s²`, qdot: (v) => `q̇ ${sig(v)} rad/s²` };

/** 물리 한계에 붙은 미수렴의 판정 근거(엔진 state_evidence) → 글 — 한계를 고정하고 다시 푼 평형 해마다 수치. */
export function stateEvidenceText(ev) {
  if (!ev) return "";
  const [[fixedKey, fixedVal]] = Object.entries(ev.fixed);
  const head = `${FIXED_TEXT[fixedKey]?.(fixedVal) ?? `${fixedKey} ${fixedVal}`} 고정 평형 해`;
  if (!ev.solutions?.length) return `${head} 없음`;
  const free = ["alpha", "de", "throttle"].filter((k) => k !== fixedKey);
  const one = (s) => [...free.map((k) => FREE_TEXT[k](s[k])), EQUATION_TEXT[ev.equation](s[ev.equation])].join(" · ")
    + (s.alpha_stall == null ? " (실속 근거 없음)" : ` (실속각 ${sig(s.alpha_stall)} ${s.below_stall ? "아래" : "이상"})`);
  return `${head} ${ev.solutions.length}개 — ${ev.solutions.map(one).join(" / ")}`;
}

/** 비행 엔벨로프 셀 종류 → 범례 라벨 — 트림 탭 범례와 쇼케이스 보고가 **같은 말**을 쓴다(한 표).
 *  키 순서가 범례 순서다. */
export const TRIM_CELL_LABEL = Object.freeze({
  ok: "가능",
  stall: "실속 근접 (α 여유 위반)",
  saturated: "포화 (추력·타면 한계)",
  infeasible: "트림 불가",
});

/** 트림 판정 플래그 4종 → 트림 표의 열 이름 (01 §4.1). 키 순서가 표의 열 순서다 — 표·머리줄·보고가 한 표를 본다. */
export const TRIM_FLAG_LABEL = Object.freeze({
  residual_ok: "잔차",
  saturation_ok: "포화",
  alpha_margin_ok: "α여유",
  continuity_ok: "연속성",
});

/** 트림 배치 결과 행 → 탭 머리줄의 근거 — 수렴 수, 판정 플래그 위반 케이스(플래그 하나라도 false — null은
 *  미판정이라 위반 아님), 플래그별 위반 수. line은 탭 머리줄 문장, detail은 플래그별 「연속성 3」 나열. */
export function trimFlagSummary(results) {
  const byFlag = {};
  const badNames = [];
  for (const r of results) {
    const bad = Object.entries(r.flags ?? {}).filter(([, v]) => v === false).map(([k]) => k);
    if (!bad.length) continue;
    badNames.push(r.case?.name ?? "?");
    for (const k of bad) byFlag[k] = (byFlag[k] ?? 0) + 1;
  }
  const known = Object.keys(TRIM_FLAG_LABEL).filter((k) => byFlag[k]);
  const other = Object.keys(byFlag).filter((k) => !Object.hasOwn(TRIM_FLAG_LABEL, k)); // 엔진이 새 플래그를 더하면 키 그대로
  const converged = results.filter((r) => r.converged).length;
  return {
    total: results.length, converged, bad: badNames.length, byFlag, badNames,
    line: `수렴 ${converged}/${results.length} · 판정 플래그 위반 ${badNames.length}건`,
    detail: [...known.map((k) => `${TRIM_FLAG_LABEL[k]} ${byFlag[k]}`), ...other.map((k) => `${k} ${byFlag[k]}`)]
      .join(" · "),
  };
}

/** 트림 배치 결과 행 → 쇼케이스 보고 {summary, data} — 지도 셀 판정(trimEnvelopeCell) 종류별 개수.
 *  「가능」은 0이어도 적고, 나머지는 있는 종류만 적는다(없는 실패를 0건으로 늘어놓지 않는다).
 *  판정 플래그 위반이 있으면 **탭 머리줄과 같은 말**(「판정 플래그 위반 N건 확인 필요」)을 플래그별 수와 함께 붙인다 —
 *  지도 셀은 연속성 플래그를 보지 않아, 셀 집계만 말하면 「가능 20」이 탭 자신의 경고를 가린다(쇼케이스 D6). */
export function trimCueReport(results, untrimmed = null) {
  // 조건 상태가 실린 결과면 상태 표로, 옛 결과면 판정 플래그 셀 표로 센다 — 한 보고에 두 어휘를 섞지 않는다
  const byState = results.length > 0 && results.every((r) => r.state);
  const labels = byState
    ? Object.fromEntries(Object.entries(TRIM_STATE_CELL).map(([k, v]) => [k, v.label])) : TRIM_CELL_LABEL;
  const first = byState ? "computable" : "ok";
  const counts = Object.fromEntries(Object.keys(labels).map((k) => [k, 0]));
  for (const r of results) {
    const kind = trimEnvelopeCell(r)?.kind;
    if (kind in counts) counts[kind] += 1;
  }
  // 모델 부족은 트림하지 않는 점이라 결과 행에 없다 — 기본 격자의 수로 채운다(0으로 두면 없다는 거짓말이 된다)
  if (byState && untrimmed) counts.model_gap = untrimmed.modelGap;
  const parts = Object.keys(labels)
    // 모델 부족은 결과 행이 아니라 아래 「트림하지 않음」 글이 말한다(두 번 세지 않게)
    .filter((k) => k !== "model_gap" && (k === first || counts[k] > 0))
    .map((k) => `${labels[k]} ${counts[k]}`);
  const f = trimFlagSummary(results);
  if (f.bad > 0) parts.push(`판정 플래그 위반 ${f.bad}건 확인 필요 (${f.detail})`);
  if (untrimmed?.text) parts.push(untrimmed.text);
  return {
    summary: `${results.length} 케이스 — ${parts.join(" · ")}`,
    data: {
      cases: results.length,
      converged: f.converged,
      fuels: [...new Set(results.map((r) => r.case.fuel))].sort((a, b) => a - b),
      counts,
      flag_violations: { cases: f.bad, by_flag: f.byFlag, names: f.badNames },
      ...(untrimmed ? { untrimmed: { model_gap: untrimmed.modelGap, rows: untrimmed.rows } } : {}),
    },
  };
}

/** 비율 → 백분율 글 — 소수 자리 고정(기본 1자리). 유효 자리 표기(fmt(x·100, 1))는 20을 「2e+1」로 찍는다(D8).
 *  수가 아니면 "—", 음수는 수학 기호 빼기(−). */
export function pctText(frac, decimals = 1) {
  if (typeof frac !== "number" || !Number.isFinite(frac)) return "—";
  const t = (frac * 100).toFixed(decimals);
  return `${t.startsWith("-") ? `−${t.slice(1)}` : t} %`;
}

/** 한 줄로 그린 곡선(coincidentGroups) → 캡션 한 줄. charts: [{name, groups, tags}] — tags[i]는 곡선 i의 이름.
 *  겹친 무리가 없으면 null. 모든 그림이 같은 방식으로 겹치면 한 번만 말한다. */
export function coincidentNote(charts) {
  const parts = charts.map((c) => ({
    name: c.name,
    text: c.groups.filter((g) => g.length > 1).map((g) => g.map((i) => c.tags[i]).join(" = ")).join(", "),
  })).filter((p) => p.text);
  if (!parts.length) return null;
  const uniform = parts.length === charts.length && parts.length > 1 && parts.every((p) => p.text === parts[0].text);
  const body = uniform ? `${parts.map((p) => p.name).join("·")} 모두 ${parts[0].text}`
    : parts.map((p) => `${p.name}: ${p.text}`).join(" · ");
  return `같은 값의 곡선은 한 줄(앞 곡선의 색)로 그렸습니다 — ${body}`;
}

/** 곡선 무리의 퍼짐 — lists[i]는 곡선 i의 값 배열(null = 끊긴 자리). 모든 곡선이 수인 자리에서 (최대 − 최소)의
 *  최댓값(maxDiff)과 전체 값 범위(range), 그 비율(rel). 곡선이 둘 미만이거나 견줄 자리가 없으면 null. */
export function curveSpread(lists) {
  if (!lists || lists.length < 2) return null;
  const n = Math.min(...lists.map((l) => l.length));
  let maxDiff = null;
  let lo = Infinity;
  let hi = -Infinity;
  for (const l of lists) {
    for (const v of l) {
      if (typeof v === "number" && Number.isFinite(v)) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
    }
  }
  for (let i = 0; i < n; i += 1) {
    const vs = lists.map((l) => l[i]);
    if (!vs.every((v) => typeof v === "number" && Number.isFinite(v))) continue;
    const d = Math.max(...vs) - Math.min(...vs);
    maxDiff = maxDiff == null ? d : Math.max(maxDiff, d);
  }
  if (maxDiff == null) return null;
  const range = hi - lo;
  return { maxDiff, range, rel: range > 0 ? maxDiff / range : 0 };
}

/** 거의 포개진 곡선 → 캡션 한 줄. charts: [{name, spread: curveSpread|null}] — 퍼짐이 값 범위의 frac(기본 1.5 % —
 *  기체 탭 극선·L/D 그림(220 px)의 플롯 영역에서 약 3 px, 1.4 px 선 두 가닥이 갈려 보이지 않는 폭) 아래인 그림만
 *  말한다. 같은 값이 아니므로 「같다」고 하지 않는다 — 한 줄로 **보인다**고 한다. 말할 그림이 없으면 null. */
export function nearOverlapNote(charts, frac = 0.015) {
  const near = charts.filter((c) => c.spread && c.spread.maxDiff > 0 && c.spread.rel < frac);
  if (!near.length) return null;
  const num = (v) => String(Number(v.toPrecision(2)));
  return "겹친 곡선의 차가 그림 해상도보다 작아 한 줄로 보입니다(나중 곡선의 색이 위) — "
    + near.map((c) => `${c.name} 최대 차 ${num(c.spread.maxDiff)} (값 범위의 ${(c.spread.rel * 100).toFixed(1)} %)`)
      .join(" · ");
}

/** 같은 값의 곡선 묶기 — seriesList[i]는 값 배열(null = 끊긴 자리). 앞선 무리의 **대표(첫 곡선)**와 같은 값이면
 *  그 무리에 든다. 같음은 부동소수 잡음(상대 rtol·절대 atol)까지만 — 눈에 안 보일 만큼만 다른 곡선은 다른 곡선이다.
 *  null은 같은 자리에 있어야 같다. 돌려주는 것: [[대표 i, 같은 곡선 j…], …] (대표 순서 = 입력 순서).
 *  겹친 곡선이 전부 같은 값이면 한 줄만 보이는데 범례는 여럿을 말한다 — 뷰가 대표만 그리고 캡션에 그 사실을 적는다(D9). */
export function coincidentGroups(seriesList, { rtol = 1e-9, atol = 1e-12 } = {}) {
  const same = (a, b) => a.length === b.length && a.every((v, i) => {
    const w = b[i];
    if (typeof v !== "number" || typeof w !== "number") return v === w || (v == null && w == null);
    return Math.abs(v - w) <= atol + rtol * Math.max(Math.abs(v), Math.abs(w));
  });
  const groups = [];
  seriesList.forEach((s, i) => {
    const g = groups.find((grp) => same(seriesList[grp[0]], s));
    if (g) g.push(i);
    else groups.push([i]);
  });
  return groups;
}

/** 마진 맵 entries·루프 → 최악 칸 {pm, gm, unstable} — pm·gm은 각각 {loop, entry, value} 또는 null,
 *  unstable은 이 루프를 닫은 폐루프가 발산하는 칸(엔진 closed_loop.stable === false)의 수.
 *  트림이 수렴하고 그 루프의 마진이 수(數)인 **안정** 칸만 후보다: "inf"(교차 없음 — 무한 여유)와 null(판정 불가)은
 *  최악이 아니고, 발산 칸의 PM·GM은 여유가 아니라 루프 교차의 고전 판독이라 최소에 섞지 않는다(섞으면 「최악 PM
 *  82°」 같은 거짓 안심 — 발산 칸 목록은 lib/loops.js unstableCells). 같은 값이면 먼저 온 칸(격자 순서)이 남는다. */
export function marginWorst(entries, loops) {
  let pm = null;
  let gm = null;
  let unstable = 0;
  for (const e of entries ?? []) {
    if (!e.trim?.converged) continue;
    for (const lp of loops ?? []) {
      const m = e.margins?.[lp.name];
      if (!m) continue;
      if (marginUnstable(m)) {
        unstable += 1;
        continue;
      }
      if (typeof m.pm_deg === "number" && (!pm || m.pm_deg < pm.value)) pm = { loop: lp.name, entry: e, value: m.pm_deg };
      if (typeof m.gm_db === "number" && (!gm || m.gm_db < gm.value)) gm = { loop: lp.name, entry: e, value: m.gm_db };
    }
  }
  return { pm, gm, unstable };
}

/** 시리즈 색 순환 팔레트 — 그룹 내 순번으로 배정 (애플 시스템 팔레트, 상태색과 동일 계열). */
export const SERIES_COLORS = ["#007aff", "#ff9500", "#ff3b30", "#34c759", "#af52de", "#5ac8fa"];

/** 게인 테이블 dict {"그룹.게인": {axes, data}} → 그룹별 차트 시리즈.

1D mach 테이블만 대상 (현 데모 스케줄 규격) — 다차원·비mach 테이블과 그룹 내
mach 축이 다른 테이블은 skipped에 사유와 함께 보고. 그룹 = 이름의 점 앞
접두부, 등장 순서 유지. 반환 {groups: [{group, mach, series}], skipped}.
시리즈 data는 입력 배열 참조 — 편집 후 재호출로 최신값 반영.
*/
export function gainPlotGroups(tables, colors = SERIES_COLORS) {
  const groups = [];
  const byGroup = new Map();
  const skipped = [];
  for (const [name, t] of Object.entries(tables)) {
    const axes = Object.keys(t.axes ?? {});
    if (axes.length !== 1 || axes[0] !== "mach") {
      skipped.push({ name, reason: `1D mach 테이블 아님 (축: ${axes.join("×") || "없음"})` });
      continue;
    }
    const dot = name.indexOf(".");
    const grp = dot >= 0 ? name.slice(0, dot) : name;
    const label = dot >= 0 ? name.slice(dot + 1) : name;
    let g = byGroup.get(grp);
    if (!g) {
      g = { group: grp, mach: t.axes.mach, series: [] };
      byGroup.set(grp, g);
      groups.push(g);
    } else if (g.mach.length !== t.axes.mach.length || g.mach.some((v, i) => v !== t.axes.mach[i])) {
      skipped.push({ name, reason: "그룹 내 mach 축 불일치 (차트가 x축 공유)" });
      continue;
    }
    g.series.push({ label, data: t.data, color: colors[g.series.length % colors.length] });
  }
  // 그룹은 생성한 테이블이 첫 시리즈로 반드시 들어감 — 빈 그룹 없음
  return { groups, skipped };
}

/** 시뮬 궤적 → 3면도 뷰 정의 (평면도·측면도·정면도).

평면 이름은 NED 축으로 부른다 (conventions §6 — 북·동·하방). 툴 내부 좌표가
NED이므로 XY/YZ/ZX로 부르면 어느 축이 어디인지 한 번 더 번역해야 한다.

연직 평면(N–D·E–D)의 세로축은 D 대신 고도 h = −D 를 위로 그린다 — 같은 평면을
부호만 뒤집어 본 것이고, 프로파일을 거꾸로 읽는 오독이 D 표기보다 훨씬 잦기
때문. 대신 라벨에 (= −D)를 명시해 규약을 숨기지 않는다.

equal(등축)은 N–E 평면만 true — 선회반경을 왜곡 없이 읽어야 하므로. 연직 평면은
수평 이동이 고도 변화보다 통상 한 자릿수 이상 커서 등축이면 직선으로 뭉개진다.
wpIdx: 웨이포인트 (n, e, alt) 중 그 뷰의 **가로축**에 해당하는 성분 색인 (N–E
평면은 원으로 직접 그리므로 null). 세로축 값은 wpMarks가 함께 뽑는다.
배열은 입력 참조 — 복사하지 않는다.
*/
export function planeViews(sig) {
  return [
    { key: "ne", title: "N–E 평면 (평면도)", equal: true, wpIdx: null,
      xs: sig.pe, ys: sig.pn, xLabel: "E [m]", yLabel: "N [m]" },
    { key: "nd", title: "N–D 평면 (측면도)", equal: false, wpIdx: 0,
      xs: sig.pn, ys: sig.h, xLabel: "N [m]", yLabel: "h [m] (= −D)" },
    { key: "ed", title: "E–D 평면 (정면도)", equal: false, wpIdx: 1,
      xs: sig.pe, ys: sig.h, xLabel: "E [m]", yLabel: "h [m] (= −D)" },
  ];
}

/** 연직 단면(측면도·정면도)에 찍을 웨이포인트 표식 — [{x, alt}].
 *
 * 웨이포인트는 (n, e) **또는 (n, e, alt)**다. 고도가 모드 테이블 전담이던 시절에는
 * 연직 평면이 가로좌표 안내선만 그렸고 그 전제가 세 곳(planeViews·profileCanvas·
 * plot3d)에 주석으로 박혀 있었는데, 경로가 고도도 내게 된 뒤로 그 안내선은
 * **고도 화면에 평면 정보만 그리는** 자리가 됐다 — 사용자가 넣은 고도가 화면에서
 * 사라진다(사용자 제기). 두 성분을 여기서 한 번에 뽑아 그리기 쪽이 다시 고르지
 * 않게 한다.
 *
 * xIdx는 그 뷰의 가로축 성분(planeViews wpIdx). 비수치는 **행을 버리지 않고**
 * null로 남긴다 — 걸러내면 색인이 밀려 몇 번 웨이포인트인지 셀 수 없게 된다.
 * alt가 null이면 "고도 없음"이지 0이 아니다(엔진 set_waypoints의 전부/전무 규약).
 */
export function wpMarks(waypoints, xIdx) {
  const fin = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);
  return (waypoints ?? []).map((w) => ({ x: fin(w?.[xIdx]), alt: wpAlt(w) }));
}

/** 웨이포인트 한 행의 고도 [m] 또는 null — "고도가 있는가"의 **단일 정본**.
 *
 * 색인 2와 유한성 판정이 세 곳(wpMarks·bounds3d·3D 그리기)에 각자 적혀 있었다.
 * 오늘은 셋이 일치하지만 열이 하나 늘거나 색인이 밀리면 테스트가 있는 lib 둘만
 * 터지고 뷰의 사본은 조용히 엉뚱한 양을 그린다 — 이번 버그를 만든 드리프트와
 * 같은 종류다(리뷰 지적). wpMarks가 3D를 못 맡는 이유는 그쪽이 n·e·alt 셋을
 * 다 쓰기 때문이라, 공유할 수 있는 조각은 이 판정 하나다.
 */
export function wpAlt(w) {
  if (w == null || w.length < 3) return null;
  const a = w[2];
  return typeof a === "number" && Number.isFinite(a) ? a : null;
}

/** margin-map entries → 연료 고정 (mach×alt) 격자 조회. */
export function pivotCases(entries, fuel) {
  const sel = entries.filter((e) => e.trim.case.fuel === fuel);
  const machs = [...new Set(sel.map((e) => e.trim.case.mach))].sort((a, b) => a - b);
  const alts = [...new Set(sel.map((e) => e.trim.case.alt))].sort((a, b) => a - b);
  const map = new Map(sel.map((e) => [`${e.trim.case.mach}|${e.trim.case.alt}`, e]));
  return { machs, alts, at: (m, a) => map.get(`${m}|${a}`) ?? null };
}

export function fuelsOf(entries) {
  return [...new Set(entries.map((e) => e.trim.case.fuel))].sort((a, b) => a - b);
}

/** 트림 배치 결과(results 행) → 연료 고정 트림 곡선 데이터.
 *
 * {machs, alts, series: {alpha|throttle|de: [{alt, data}]}} — data는 machs 순서.
 * 없는 (마하, 고도) 조합과 **미수렴 케이스는 null**이다: 곡선이 거기서 끊긴다
 * (lineChartCanvas의 null 규약). 0이나 이웃 보간으로 채우면 "트림이 없는 점"이
 * 그럴듯한 값으로 위장된다 — 히트맵의 "불가" 칸과 같은 사실을 곡선도 말해야 한다.
 * α는 트림 해에서 θ와 같다(수평정상비행 γ=0, engine trim.py) — 그래서 받음각
 * 곡선이 곧 피치각 곡선이고, 두 그림을 따로 내지 않는다.
 */
export function trimCurves(results, fuel) {
  const sel = results.filter((r) => r.case.fuel === fuel);
  const machs = [...new Set(sel.map((r) => r.case.mach))].sort((a, b) => a - b);
  const alts = [...new Set(sel.map((r) => r.case.alt))].sort((a, b) => a - b);
  const map = new Map(sel.map((r) => [`${r.case.mach}|${r.case.alt}`, r]));
  const getters = {
    alpha: (r) => r.euler[1],
    throttle: (r) => r.control.throttle[0],
    de: (r) => r.control.elevon[0],
  };
  const series = {};
  for (const [qty, get] of Object.entries(getters)) {
    series[qty] = alts.map((alt) => ({
      alt,
      data: machs.map((m) => {
        const r = map.get(`${m}|${alt}`);
        return r && r.converged ? get(r) : null;
      }),
    }));
  }
  return { machs, alts, series };
}

// ── 마진 맵 격자 레이아웃 (views/plots.js heatmapCanvas와 **공유**) ────────
// 그리기와 역매핑이 각자 상수를 들고 있으면 갈린다 — 갈려도 화면은 멀쩡해 보이고
// 클릭만 한 칸씩 어긋나므로 눈에 잘 안 띈다. 한 표를 양쪽이 읽는다.
export const HEATMAP_LAYOUT = {
  mL: 64, mT: 28, mR: 10, mB: 34,
  ch: 34,        // 행 높이
  cwMax: 90,     // 열 폭 상한 — 케이스가 적으면 격자가 width를 다 채우지 않는다
  gap: 3,        // 칸 사이 여백 (칠하는 폭은 cw-gap / ch-gap)
};

/** 마하 개수·캔버스 폭 → 열 폭. heatmapCanvas와 같은 식. */
export function heatmapCellWidth(nMach, width) {
  const { mL, mR, cwMax } = HEATMAP_LAYOUT;
  return Math.min(cwMax, (width - mL - mR) / Math.max(1, nMach));
}

/** 고도 개수 → 캔버스 **논리** 높이. 클릭 역변환이 이 값을 알아야 한다 —
 * canvas.clientHeight는 CSS로 축소된 뒤의 높이라 그걸 쓰면 y 배율이 1이 되어
 * 좁은 화면에서 세로 좌표가 안 풀린다(app.css의 max-width·height:auto). */
export function heatmapCanvasHeight(nAlt) {
  const { mT, mB, ch } = HEATMAP_LAYOUT;
  return mT + ch * nAlt + mB;
}

/** 캔버스 논리 좌표 → {mach, alt, entry} | null — 히트맵 칸 역매핑.
 *
 * 칸 사이 여백과 cwMax로 남는 우측 공백은 **null**이다. 가장 가까운 칸으로
 * 끌어붙이면 사용자가 안 누른 운용점의 선도가 뜬다. `entry`는 그 좌표에 케이스가
 * 없으면 null이지만 칸 자체는 존재하므로 mach·alt는 채워 보낸다(호출측이
 * "빈 칸을 눌렀다"와 "격자 밖을 눌렀다"를 구분할 수 있게). */
export function heatmapCellAt(pivot, x, y, { width = 560 } = {}) {
  const { machs, alts } = pivot;
  const { mL, mT, ch, gap } = HEATMAP_LAYOUT;
  const cw = heatmapCellWidth(machs.length, width);
  const dx = x - mL;
  const dy = y - mT;
  if (dx < 0 || dy < 0) return null;
  const i = Math.floor(dx / cw);
  const row = Math.floor(dy / ch);
  if (i >= machs.length || row >= alts.length) return null;
  if (dx - i * cw > cw - gap || dy - row * ch > ch - gap) return null; // 칸 사이 여백
  const alt = alts[alts.length - 1 - row]; // 고도는 위로 증가 (heatmapCanvas와 동일)
  const mach = machs[i];
  return { mach, alt, entry: pivot.at(mach, alt) };
}

// ── 주파수축 (보드선도) ───────────────────────────────────────────────────

/** linScale의 log10판 — 데케이드가 등간격이 된다. */
export function logScale(d0, d1, r0, r1) {
  const a = Math.log10(d0);
  const k = (r1 - r0) / ((Math.log10(d1) - a) || 1);
  return (v) => r0 + (Math.log10(v) - a) * k;
}

/** log 축 눈금 — 넓으면 10^k만, 좁으면 1·2·5×10^k까지 (선형 niceTicks의 log판). */
export function decadeTicks(min, max) {
  if (!(max > min)) return [min];
  const lo = Math.floor(Math.log10(min));
  const hi = Math.ceil(Math.log10(max));
  const decades = [];
  for (let k = lo; k <= hi; k += 1) decades.push(10 ** k);
  const inRange = (t) => t >= min * (1 - 1e-12) && t <= max * (1 + 1e-12);
  const plain = decades.filter(inRange);
  if (plain.length >= 4) return plain;
  const fine = [];
  for (let k = lo; k <= hi; k += 1) for (const m of [1, 2, 5]) fine.push(m * 10 ** k);
  const dense = fine.filter(inRange).sort((a, b) => a - b);
  return dense.length ? dense : plain.length ? plain : [min, max];
}

/** log-x 선형보간 — xs 오름차순, ys에 null 갭 허용. 범위 밖은 가장 가까운 끝값.
 *
 * 보드선도 교차 마커를 **곡선 위에** 찍는 데 쓴다: 교차 위치는 _level_crossings가
 * log-w 보간으로 찾았으므로 같은 자로 되읽어야 마커가 곡선에 앉는다. */
export function interpLogAt(xs, ys, x) {
  const n = xs.length;
  if (!n) return null;
  const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);
  const i = xs.findIndex((v) => v >= x);
  if (i < 0) return num(ys[n - 1]);   // x가 마지막 표본보다 크다 — 끝값
  if (i === 0) return num(ys[0]);
  const a = num(ys[i - 1]), b = num(ys[i]);
  if (a === null || b === null) return b ?? a;
  const lo = Math.log10(xs[i - 1]), hi = Math.log10(xs[i]);
  return a + (b - a) * ((Math.log10(x) - lo) / ((hi - lo) || 1));
}

/** 보드 응답 → 그리기용 시리즈 {w, mag, phase} — 비유한 dB는 null 갭.
 *
 * to_jsonable이 ±inf를 문자열 "inf"/"-inf"로, nan을 null로 보낸다. 그것을 0으로
 * 채우면 없는 교차가 생기고 있는 교차가 사라진다 — 끊어 그린다. */
export function bodeSeries(data) {
  const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);
  return {
    w: data.w,
    mag: data.mag_db.map(num),
    phase: data.phase_deg.map(num),
  };
}
