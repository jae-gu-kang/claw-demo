/** 자동 설계 탭 순수 로직 — 설정 페이로드·점/판정 결합·처방 그룹·게인 채택. DOM·통신 없음.

수치의 정본은 서버(GET /design/defaults ← 엔진 AutoDesignConfig)다 — 여기서
기본값을 다시 적지 않고, 사용자가 채운 칸만 config 덮어쓰기로 보낸다.

게인 채택은 기존 스토어 계약(gains 탭 storePayload — {tables, scheduleOff})으로
낸다. v1은 **재샘플 테이블**(gain_export.tables_resampled)을 주입한다 — 다항
정본(kind='poly')은 서버 sim/codegen이 직접 받지만, 웹 스토어 소비자(구조도
표시·influence·웹 코드 미리보기)가 테이블 형상을 전제하므로 스토어 경유는
호환 반출을 쓴다 (다항 스토어 채택은 [백로그] — docs -01 §3.4).

출처(`gainTablesSource`)를 함께 넣는다 — 게인 탭이 되읽을 때 "자동 설계 확정본
(결과 id)"이라고 이름을 댈 수 있어야, 화면에 뜬 표가 어디서 온 것인지가 분명해진다.
*/

import { parseNumberList } from "./grid.js";

/** 수치 표기 — dom.js의 fmt와 같은 정책(null=—, "inf"=∞, 유효자릿수).
 *
 * lib은 DOM 계층을 import하지 않는다는 규약 때문에 여기 한 벌을 둔다. 정책이
 * 갈리면 같은 수가 카드와 표에서 다르게 보이므로 fmt와 함께 고칠 자리다. */
/** 비유한값 문자열("inf"/"-inf")을 걸러낸 수치 — 아니면 null.
 *
 * 크기 계산·정렬에는 이걸 쓴다. `num`은 표시용이라 문자열을 그대로 받아 넘긴다. */
function numeric(x) {
  return typeof x === "number" && Number.isFinite(x) ? x : null;
}

function num(x, digits = 3) {
  if (x == null) return "—";
  if (x === "inf") return "∞";
  if (x === "-inf") return "−∞";
  if (typeof x !== "number") return String(x);
  if (Number.isInteger(x) && Math.abs(x) < 1e6) return String(x);
  return x.toPrecision(digits);
}

export const VERDICT_LABEL = {
  simple_deficit: "단순 마진 부족 — 검증점 추가",
  plant_variation: "플랜트 급변 — 트림/선형화점 승격",
  gain_interp_valley: "게인 보간 valley — breakpoint 승격 + 재튜닝",
  structural_limit: "구조 한계 — 상위 설계 변경 검토 (보고 전용)",
  gain_sign_flip: "게인 부호 뒤집힘 — 부호 보존 재적합 (승격으로는 안 풀린다)",
};

const _STATUS_RANK = { ok: 0, na: 1, warn: 2, fail: 3 };

export function statusRank(s) {
  return _STATUS_RANK[s] ?? 1;
}

/** 자리별 판정 dict → 최악 판정 (fail > warn > na > ok). 빈 dict는 null(미판정). */
export function worstStatus(loops) {
  let worst = null;
  for (const entry of Object.values(loops ?? {})) {
    const s = entry?.status;
    if (s == null) continue;
    if (worst == null || statusRank(s) > statusRank(worst)) worst = s;
  }
  return worst;
}

/** 요구 조정 칸의 정의 — 서버 config.criteria/targets 키와 1:1 (routes/design.py가
 * 중첩 덮어쓰기를 이미 받는다). 라벨만 여기 있고 기본 수치는 없다 — placeholder는
 * /design/defaults가 채운다. */
export const CRITERIA_FIELDS = [
  ["pm_min_deg", "PM 합격선 [°]"],
  ["gm_min_db", "GM 합격선 [dB]"],
  ["pm_bad_deg", "PM 심각선 [°]"],
  ["gm_good_db", "GM 목표선 [dB]"],
  ["zeta_min", "ζ 합격선"],
  ["zeta_good", "ζ 목표선"],
  ["lam_min_frac", "λ 합격 비율"],
  ["lam_good_frac", "λ 목표 비율"],
  ["lam_part_min", "λ 참여도 하한"],
];

export const TARGET_FIELDS = [
  ["pm_deg", "튜닝 목표 PM [°]"],
  ["gm_db", "튜닝 목표 GM [dB]"],
  ["zeta_sp", "목표 ζ_sp"],
  ["zeta_dr", "목표 ζ_dr"],
  ["roll_lambda", "목표 λ_roll [rad/s]"],
];

/** 폼 → config 덮어쓰기 — 채운 칸만. 수치 목록 오류는 던진다 (호출측이 표시).
 *
 * criteria·targets는 **중첩 덮어쓰기**다 (서버 _build_config가 base와 병합한다) —
 * 빈 dict를 보내면 안 되므로 채운 칸이 하나도 없으면 키 자체를 넣지 않는다. */
export function buildConfig(form) {
  const out = {};
  if (form.mode) out.mode = form.mode;
  const nums = [
    ["budgetPoints", "budget_points"],
    ["budgetIters", "budget_iters"],
    ["nMach", "n_mach"],
    ["actuatorWn", "actuator_wn"],
    ["actuatorZeta", "actuator_zeta"],
    ["delayS", "delay_s"],
  ];
  for (const [from, to] of nums) {
    const raw = String(form[from] ?? "").trim();
    if (!raw) continue;
    const v = Number(raw);
    if (!Number.isFinite(v)) throw new Error(`${to}: 수치가 아님 — ${raw}`);
    out[to] = v;
  }
  for (const [from, to] of [["altsText", "alts"], ["fuelsText", "fuels"]]) {
    const raw = String(form[from] ?? "").trim();
    if (!raw) continue;
    out[to] = parseNumberList(raw);
  }
  for (const key of ["criteria", "targets"]) {
    const nested = {};
    for (const [k, raw0] of Object.entries(form[key] ?? {})) {
      const raw = String(raw0 ?? "").trim();
      if (!raw) continue;
      const v = Number(raw);
      if (!Number.isFinite(v)) throw new Error(`${key}.${k}: 수치가 아님 — ${raw}`);
      nested[k] = v;
    }
    if (Object.keys(nested).length) out[key] = nested;
  }
  return out;
}

/** 결과 → 점 행 [{name, mach, alt, fuel, role, trimmable, status}] —
 * 마진맵 판정을 이름으로 결합, 판정 없는 점은 status null(미판정). */
export function pointRows(result) {
  const cases = result?.margin_out?.cases ?? {};
  return (result?.points?.points ?? []).map((p) => ({
    name: p.name,
    mach: p.mach,
    alt: p.alt,
    fuel: p.fuel,
    role: p.role,
    trimmable: p.trimmable,
    // 엔진이 처방·수렴 판정에서 뺀 점(포화·α 여유 미달) — 미수렴과 다른 상태다
    outsideEnvelope: Boolean(cases[p.name]?.outside_envelope),
    status: worstStatus(cases[p.name]?.loops),
  }));
}

/** 트림 상태 표기 — 세 상태를 한 낱말로 뭉치지 않는다.
 *
 * 종전에는 "불가" 하나가 **미수렴**과 **엔벨로프 경계**를 함께 가리켰다. 둘은
 * 성격이 전혀 다르다: 앞은 트림해가 없어 볼 것이 없는 점이고, 뒤는 트림해는
 * 있으나 포화·α 여유가 없어 설계 대상에서 빠진 점이다(마진 수치는 나온다). */
export function trimLabel(row) {
  if (row?.outsideEnvelope) return "엔벨로프 경계";
  if (row?.trimmable === false) return "미수렴";
  if (row?.trimmable) return "OK";
  return "미판정";
}

/** 점 행 목록 → 판정 개수 {ok, warn, fail, na, outside, unjudged}.
 *
 * "경고가 왜 이렇게 많나"에 화면이 스스로 답하려면 먼저 몇 건인지 세어야 한다.
 * 표를 눈으로 세는 것이 유일한 방법이면 사용자는 경고의 규모를 오해한다.
 *
 * 엔벨로프 경계 점은 **판정 칸에서 뺀다** — 엔진이 그 점의 실패를 처방 목록에서
 * 제외하므로(schedmap.outside_envelope), 개수에만 섞으면 화면이 세는 실패와
 * 처방 카드 수가 어긋난다. 빼되 자기 칸에 세어 조용한 누락은 만들지 않는다. */
export function statusCounts(rows) {
  const out = { ok: 0, warn: 0, fail: 0, na: 0, outside: 0, unjudged: 0 };
  for (const r of rows ?? []) {
    if (r?.outsideEnvelope) { out.outside += 1; continue; }
    const s = r?.status;
    if (s == null) out.unjudged += 1;
    else if (s in out) out[s] += 1;
  }
  return out;
}

/** 판정 기준 dict → 판정어의 뜻 문장 [{key, text}] — 기준 수치를 문장에 박아 낸다.
 *
 * 종전 화면은 ok/warn/fail 칩만 띄우고 뜻을 어디에도 적지 않아, warn이 "합격이나
 * 목표 미달"인지 "곧 실패"인지 알 수 없었다. 수치는 결과에 동봉된 criteria(판정에
 * 실제로 쓴 값)에서 읽는다 — 여기에 기본값을 다시 적으면 기준을 바꿨을 때 화면만
 * 옛 수치를 말하게 된다. */
export function verdictLegend(criteria) {
  const c = criteria ?? {};
  const n = (v, unit) => (v == null ? "?" : `${v}${unit}`);
  return [
    { key: "ok", text: `설계 목표 달성 — PM ≥ ${n(c.pm_min_deg, "°")} · `
      + `GM ≥ ${n(c.gm_good_db, " dB")} · ζ ≥ ${n(c.zeta_good, "")}` },
    { key: "warn", text: `합격선은 넘겼으나 목표 미달 — GM ${n(c.gm_min_db, "")}~`
      + `${n(c.gm_good_db, " dB")} 또는 ζ ${n(c.zeta_min, "")}~${n(c.zeta_good, "")}. `
      + "채택해도 되지만 여유가 얇아 형상이 바뀌면 먼저 무너지는 자리다" },
    { key: "fail", text: `합격선 미달 — PM < ${n(c.pm_min_deg, "°")} 또는 `
      + `GM < ${n(c.gm_min_db, " dB")} 또는 ζ < ${n(c.zeta_min, "")}, 혹은 게인 부호 뒤집힘. `
      + "처방 카드로 이어진다" },
    // 문장은 그대로 텍스트 노드로 들어간다 — 마크다운 강조는 별표가 화면에 그대로 뜬다
    { key: "na", text: "판정 불가 — 교차 없음(nan)이거나 트림 미수렴. 통과가 아니다" },
  ];
}

// ── 종료 상태 ──────────────────────────────────────────────────────────

/** 종료 상태 6종 + running의 뜻과 **다음에 할 일**.
 *
 * 영어 토큰만 찍으면 화면이 상태를 말하되 뜻을 말하지 않는다 — 특히
 * nothing_verified는 "실패 0"으로 보여 통과로 오독되는 상태다. */
export const STATUS_TEXT = {
  converged: "수렴 — 판정한 자리가 모두 합격선을 넘었다. 게인을 확정하고 게인·시뮬·"
    + "마진·Autocode 순으로 확인할 것.",
  escalated: "남은 실패가 전부 상위 설계 변경 대상이다 — 게인·격자로는 풀리지 않는다. "
    + "작동기 대역폭·지연 예산 같은 상위 설계를 먼저 정하고 다시 돌릴 것.",
  budget_exhausted: "이터레이션 예산을 다 썼다 — 남은 처방이 있으나 반영하지 못했다. "
    + "이터 상한을 올려 새로 돌릴 것 (이 결과는 재개할 수 없다).",
  awaiting_approval: "처방 카드를 기다리는 중이다 — 승인한 처방만 반영해 그 자리에서 "
    + "이어 돈다. 승인 없이 두면 이 상태로 남는다.",
  nothing_verified: "실패가 없는 게 아니라 볼 것이 없었다 — 트림 전량 미수렴이거나 격자가 "
    + "비었다. 게인을 확정하면 안 된다.",
  cancelled: "사용자 취소로 스테이지 도중에 멈췄다 — 트림·선형모델·튜닝 결과는 남아 있어 "
    + "남은 스테이지부터 이어서 돌 수 있다.",
  running: "아직 도는 중이다 — 종료 상태가 아니므로 이 결과로 판단하지 말 것.",
};

export function statusText(status) {
  return STATUS_TEXT[status]
    ?? `알 수 없는 상태 (${status ?? "없음"}) — 엔진과 화면의 상태 어휘가 어긋났다.`;
}

/** 상태 칩 색. converged만 ok, 사람 손을 기다리는 것(승인 대기·실행 중)은 warn,
 * **통과가 아닌 채 끝난 것**(미검증·에스컬레이션·예산 소진)은 fail 쪽에 둔다.
 * 취소는 판정이 아니라 중단이라 na다 — 실패라 칠하면 사용자가 자기 취소를 결함으로
 * 읽는다 (재개 버튼은 그대로 뜬다). */
export function statusSeverity(status) {
  if (status === "converged") return "ok";
  if (status === "awaiting_approval" || status === "running") return "warn";
  if (status === "nothing_verified" || status === "escalated"
      || status === "budget_exhausted") return "fail";
  return "na";
}

/** 재개 가능 판정 — 서버 계약 그대로 (routes/design.py: awaiting_approval·cancelled만).
 *
 * 종전 화면은 처방 카드가 하나라도 있으면 "승인 반영 재개" 버튼을 그렸다.
 * budget_exhausted는 카드가 남은 채로 끝나는 상태라 버튼이 늘 떴고, 누르면 409다. */
export const RESUMABLE_STATUS = ["awaiting_approval", "cancelled"];

export function resumable(report) {
  return RESUMABLE_STATUS.includes(report?.status);
}

/** 재개 불가 사유 한 줄 — 재개 가능하면 null. 버튼 자리를 빈칸으로 두지 않는다. */
export function resumeBlockedText(report) {
  if (resumable(report)) return null;
  const s = report?.status;
  const why = {
    budget_exhausted: "이터 예산을 다 써 세션이 종료됐다 — 남은 처방이 있어도 재개할 수 "
      + "없다(서버가 409로 거절한다). 이터 상한을 올려 새로 돌릴 것.",
    escalated: "남은 실패가 전부 상위 설계 변경 대상이라 세션이 종료됐다 — 승인해 "
      + "반영할 처방이 없다. 작동기·지연 예산을 바꾼 뒤 새로 돌릴 것.",
    converged: "이미 수렴해 종료된 세션이다 — 재개할 것이 없다.",
    nothing_verified: "판정된 자리가 하나도 없어 종료됐다 — 재개가 아니라 격자·트림을 "
      + "고쳐 새로 돌려야 한다.",
    running: "아직 실행 중이다 — 끝난 뒤에 재개 여부가 정해진다.",
  };
  return why[s] ?? `재개할 수 없는 상태다 (${s ?? "없음"}) — 승인 대기·취소만 재개 가능.`;
}

/** 게인 확정 가능 판정 — **판정이 난 자리가 하나라도 있어야** 한다.
 *
 * failures가 0이라는 것만으로는 통과의 근거가 못 된다: 트림 전량 미수렴·빈 격자·
 * 엔벨로프 밖 격자는 실패 목록도 비어 있다(engine judged_count 머리말). 그 실행의
 * 게인을 확정할 수 있으면 **아무것도 검증하지 않은 게인이 정본이 된다.** */
export function adoptable(report) {
  return Number(report?.judged) > 0;
}

/** 확정 불가 사유 한 줄 — 확정 가능하면 null. */
export function adoptBlockedText(report) {
  if (adoptable(report)) return null;
  if (report?.judged == null) {
    return "이 결과에는 판정 수(judged)가 없다 — 그 필드가 생기기 전의 구형 결과다. "
      + "무엇을 검증했는지 확인할 수 없으므로 확정하지 않는다. 다시 돌릴 것.";
  }
  return "판정이 난 (점, 자리)가 0이다 — 이 실행은 아무것도 검증하지 않았다. "
    + "실패 0은 통과가 아니라 볼 것이 없었다는 뜻이므로 게인을 확정할 수 없다. "
    + "트림 미수렴·빈 격자·엔벨로프 밖 격자를 먼저 확인할 것.";
}

/** report → 상태 줄 조각 [문자열] — 계산해 놓고 안 내던 수치를 담되 0은 생략한다.
 *
 * judged와 failures만은 0이어도 낸다: "실패 0 / 판정 0"이 곧 nothing_verified의
 * 얼굴이라, 하나를 감추면 남은 하나가 통과처럼 읽힌다. */
export function reportLine(report, nPointsFallback) {
  const r = report ?? {};
  const pts = r.points ?? {};
  const parts = [
    `스테이지 ${r.stage ?? "?"}`,
    `이터레이션 ${r.iterations ?? 0}`,
    `점 ${r.n_points ?? nPointsFallback ?? "?"} (앵커 ${pts.anchor ?? "?"} · `
      + `bp ${pts.breakpoint ?? "?"} · 검증 ${pts.validation ?? "?"})`,
    `판정 ${Number(r.judged) || 0}`,
    `실패 ${Number(r.failures) || 0}`,
  ];
  const optional = [
    ["outside_envelope", "엔벨로프 밖"],
    ["tuned", "튜닝"],
    ["escalations", "에스컬레이션"],
    ["ineffective_actions", "무효 처방"],
    ["sealed", "봉인"],
    ["fit_tighten", "적합 조이기"],
  ];
  for (const [key, label] of optional) {
    const v = Number(r[key]) || 0;
    if (v) parts.push(`${label} ${v}`);
  }
  const skipped = r.skipped ?? [];
  if (skipped.length) {
    // 이름을 다 늘어놓으면 줄이 넘친다 — 앞 셋만 보이고 나머지는 수로 말한다
    const head = skipped.slice(0, 3).join(", ");
    parts.push(`튜닝 건너뜀 ${skipped.length} (${head}`
      + (skipped.length > 3 ? ` 외 ${skipped.length - 3}` : "") + ")");
  }
  if (r.criteria_fingerprint) {
    parts.push(`기준 지문 ${String(r.criteria_fingerprint).slice(0, 8)}`);
  }
  return parts;
}

// ── 사유 코드 ──────────────────────────────────────────────────────────

/** 튜닝 포기 사유 코드 → 한국어 [폴백].
 *
 * 정본은 서버 /design/defaults의 reason_text(← 엔진 tune.REASON_TEXT)다 —
 * 여기 문구는 그 응답에 코드가 없을 때만 쓴다. */
export const REASON_TEXT = {
  ok: "설계 목표 달성",
  zero_design: "설계 게인이 0이라 방향 정보가 없다 — 이 자리를 쓸 것이면 설계값을 먼저 정한다",
  target_unreached: "게인을 아무리 키워도 목표 지표가 안 나온다 — 플랜트 한계다."
    + " 목표를 낮추거나 이 조건을 설계 범위에서 뺀다",
  capped: "작동기·지연 포함 폐루프 안정 경계가 목표 전에 묶는다 —"
    + " 작동기 대역폭 예산을 늘리거나 목표를 낮춘다",
  no_stable_gain: "어떤 게인으로도 이 댐퍼 루프가 안정하지 않아 0으로 두었다 —"
    + " 플랜트·루프 구조를 검토한다",
  bandwidth_collapse: "마진은 넘겼으나 교차 주파수가 하한 아래다 — 성능이 무너졌다."
    + " 지연·작동기 예산을 늘리거나 대역폭 하한을 낮춘다",
  margin_floor: "대역폭을 바닥까지 버려도 PM/GM 목표에 못 미친다 — 지연·작동기 예산이 병목이다",
  degenerate: "이 자리의 기저 루프 응답이 무의미하다 — 입출력·플랜트를 확인한다",
  rescued: "백오프 해가 대역폭 하한 아래여서 마무리로 되찾았다 (통과)",
};

/** 사유 코드 → "코드 — 뜻". 서버 맵이 우선, 없으면 폴백, 그것도 없으면 코드 그대로.
 * 모르는 코드를 삼키면 새 사유가 생겼을 때 화면이 조용해진다. */
export function reasonText(code, reasonMap) {
  if (!code) return null;
  const t = reasonMap?.[code] ?? REASON_TEXT[code];
  return t ? `${code} — ${t}` : String(code);
}

/** 처방 카드 그룹 — {approvable, escalations}. supersede는 양쪽 다 제외
 * (같은 점 상위 승격에 흡수됨 — 엔진 promote 래칫과 정합). */
export function actionCards(result) {
  const approvable = [];
  const escalations = [];
  for (const a of result?.proposed_actions ?? []) {
    if (a.superseded_by) continue;
    (a.action?.type === "escalate" ? escalations : approvable).push(a);
  }
  return { approvable, escalations };
}

/** 게인 채택 — gains 탭 스토어 계약 {tables, scheduleOff} + **상수 자리**.
 *
 * 적합이 평탄하다고 판정한 자리는 테이블이 아니라 상수로 나온다(gain_export.constants).
 * 그 자리를 빠뜨리면 시뮬·Autocode가 새 스케줄과 옛 설계 상수를 섞어 돌게 되어,
 * **이 실행이 검증한 마진이 채택한 형상에 해당하지 않는다.** 전 자리가 상수로 접히면
 * tables가 비어 scheduleOff가 서지만 그때도 constants는 반영되어야 한다.
 */
export function adoptStorePayload(result) {
  const tables = result?.gain_export?.tables_resampled ?? {};
  const off = Object.keys(tables).length === 0;
  return {
    tables: off ? null : tables,
    scheduleOff: off,
    constants: { ...(result?.gain_export?.constants ?? {}) },
  };
}

// ── 처방 카드 근거 ─────────────────────────────────────────────────────

/** 지표 키 → 표시 이름·단위 — 엔진 classify._LABEL과 같은 대응. */
const METRIC = {
  pm_deg: ["PM", "°"],
  gm_db: ["GM", " dB"],
  zeta: ["ζ", ""],
  zeta_sp: ["ζ_sp", ""],
  zeta_dr: ["ζ_dr", ""],
  roll_lambda: ["λ", " rad/s"],
};

const TUNED_STATUS_TEXT = {
  ok: "가능 (자유 게인으로 이 자리를 맞출 수 있다)",
  infeasible: "불가 (자유 게인으로도 설계 목표에 못 간다)",
  na: "해당 없음",
};

/** evidence.shortfall → 지표별 한 줄 [{key, kind, text}] — **요구선·달성·부족을 함께**.
 *
 * 종전 화면은 "현재 PM 38.2°"만 말했다. 요구선(45°)도 부족(6.8°)도 없으면 그 수치가
 * 합격인지 미달인지, 얼마나 모자란지를 화면만 보고는 알 수 없다 — 처방 카드에서
 * 가장 먼저 알아야 할 것이 그 둘이다.
 *
 * deficit는 양수가 부족·음수가 여유·null이 판정 불가(교차 없음)다. 정렬은 요구선
 * 대비 비율의 내림차순이고 판정 불가를 맨 앞에 둔다 — 엔진 severity와 같은 규약
 * ("얼마나 나쁜지 모른다"가 목록 맨 앞). */
export function shortfallLines(shortfall) {
  const rows = [];
  for (const [key, rec] of Object.entries(shortfall ?? {})) {
    if (!rec) continue;
    const [label, unit] = METRIC[key] ?? [key, ""];
    const req = `요구 ${num(rec.required)}${unit}`;
    if (rec.deficit == null) {
      rows.push({ key, kind: "na", rank: Infinity,
        text: `${label} ${req} · 달성 판정 불가 (교차 없음 — 통과가 아니다)` });
      continue;
    }
    // 비유한값은 **문자열**로 온다 ("inf" / "-inf" — 엔진이 nan(=null)과 구별하려고
    // 일부러 그렇게 낸다, serialize.py). 숫자로 다루면 `"inf" > 0`이 false라
    // **GM −∞(최악)가 "여유"로 초록칠**되고, Math.abs("−inf")가 NaN이 되어 부족량과
    // 정렬 키가 통째로 망가진다. 부호만 뽑아 쓰고 크기는 ∞로 적는다
    const d = numeric(rec.deficit);
    const short = d == null ? rec.deficit === "inf" : d > 0;
    const frac = numeric(rec.deficit_frac);
    const pct = frac == null ? "" : ` (요구선 대비 ${num(100 * Math.abs(frac), 3)}%)`;
    const size = d == null ? "∞" : num(Math.abs(d));
    rows.push({
      key,
      kind: short ? "short" : "spare",
      // 무한 부족은 유한한 어떤 부족보다 심각하고, 무한 여유는 어떤 여유보다 낫다
      rank: frac ?? (short ? Infinity : -Infinity),
      text: `${label} ${req} · 달성 ${num(rec.achieved)}${unit} · `
        + `${short ? "부족" : "여유"} ${size}${unit}${pct}`,
    });
  }
  rows.sort((a, b) => b.rank - a.rank);
  return rows.map(({ key, kind, text }) => ({ key, kind, text }));
}

/** 달성 지표 dict → 한 줄 ("PM 46.1° · GM 8.2 dB"). 볼 게 없으면 null.
 *
 * **아는 지표만** 적는다. 엔진의 achieved 레코드는 지표만 담은 dict가 아니라
 * 조성 메타를 함께 싣는다 — 자세 자리는 orientation·wc0·wc_fallback·target_pm_deg…,
 * 레이트 자리는 kind·capped·reached·bracket_growth·participation… 전부 훑으면
 * 한 줄이 열두 조각짜리 덤프가 되고, 사유 코드는 바로 위에서 이미 한국어로 푼 것을
 * 원문으로 한 번 더 찍는다. */
function achievedText(ach) {
  const parts = [];
  for (const [key, v] of Object.entries(ach ?? {})) {
    if (!(key in METRIC)) continue;
    const [label, unit] = METRIC[key];
    parts.push(`${label} ${num(v)}${unit}`);
  }
  return parts.length ? parts.join(" · ") : null;
}

/** evidence.tuned → 줄 목록 — 자유 게인으로 그 자리를 맞출 수 있었나와 그 사유.
 *
 * 이 판정이 structural_limit(에스컬레이션)의 근거다. 자리 단위 status를 내고,
 * 점 단위(point_status)가 다를 때만 참고로 덧붙인다 — 둘을 뭉치면 실행 가능한
 * 처방이 적용 버튼 없는 에스컬레이션처럼 읽힌다. */
export function tunedLines(tuned, reasonMap) {
  if (!tuned) return [];
  const out = [];
  const head = [`자유 게인 튜닝 ${TUNED_STATUS_TEXT[tuned.status] ?? tuned.status ?? "?"}`];
  const r = reasonText(tuned.reason, reasonMap);
  if (r) head.push(`사유 ${r}`);
  out.push(head.join(" · "));
  const detail = [];
  if (tuned.judged) detail.push(`그 자리 판정 ${tuned.judged}`);
  if (tuned.target != null) detail.push(`목표 ${num(tuned.target)}`);
  const ach = achievedText(tuned.achieved);
  if (ach) detail.push(`달성 ${ach}`);
  if (tuned.point_status && tuned.point_status !== tuned.status) {
    detail.push(`점 단위 ${tuned.point_status} (참고 — 판정에는 안 쓴다)`);
  }
  if (detail.length) out.push(detail.join(" · "));
  for (const note of tuned.notes ?? []) out.push(`튜너 메모: ${note}`);
  return out;
}

/** 처방 전후 판정 스냅샷 한 줄 — 채점 전이면 그 사실을 적는다.
 *
 * **반영했는데 안 바뀐 처방**을 드러내는 것이 목적이다. "applied"만 찍고 결과를
 * 안 보면 무효 처방이 이터 예산을 태우는 것을 아무도 모른다 (엔진 _score_applied_actions). */
export function effectText(effect) {
  if (!effect) return null;
  const snap = (s) => (s == null ? "없음"
    : `${s.status ?? "?"}${s.severity == null ? "" : ` (심각도 ${num(s.severity)})`}`);
  if (!("changed" in effect)) {
    return `반영됨 — 효과는 다음 검증에서 잰다 (반영 전 ${snap(effect.before)})`;
  }
  if (effect.changed) {
    return `반영 효과 ${snap(effect.before)} → ${snap(effect.after)}`;
  }
  return `반영했으나 판정이 그대로다 ${snap(effect.before)} → ${snap(effect.after)}`
    + " — 이 처방은 이 자리에서 듣지 않았다";
}

/** 완화 프로브 한 줄 — 무엇을 얼마에서 얼마로 바꿨더니 통과했는지까지 낸다.
 *
 * label과 통과 여부만 그리면 "작동기 대역폭 ×3"이 30에서 90인지 10에서 30인지
 * 알 수 없어, 예산을 얼마로 잡아야 하는지가 화면에서 안 나온다. */
export function reliefLines(relief, reasonMap) {
  return (relief ?? []).map((p) => {
    const move = p.from == null && p.to == null
      ? "" : ` (${p.change ?? "?"} ${num(p.from)} → ${num(p.to)})`;
    const why = p.resolves ? null : reasonText(p.reason, reasonMap);
    // 임계값이 이 카드의 실질이다 — "×3이면 통과"가 아니라 "≥ 47 rad/s면 통과"가
    // 사용자가 바로 쓸 수 있는 답이고, docs §7의 "작동기 대역폭 요구 사양"이
    // 요구하던 수치다. 통과한 축에만 붙는다 (미달 축에 숫자를 지어내면 안 된다)
    const th = p.threshold?.text;
    return {
      resolves: Boolean(p.resolves),
      threshold: th ?? null,
      text: `${p.label ?? p.change ?? "?"}${move} → ${p.resolves ? "통과" : "여전히 미달"}`
        + (th ? ` · ${th}` : "") + (why ? ` · 사유 ${why}` : ""),
    };
  });
}

/** 처방 카드 하나 → 표시용 줄 묶음. DOM은 뷰가 만든다.
 *
 * {head} 인라인 수치 · {shortfall} 요구 대비 부족 · {tuned} 자유 게인 결과 ·
 * {relief} 완화 프로브 · {effect} 반영 효과 · {notes} 강조 문장 · {flags} 봉인·건너뜀.
 * 카드에 실려 오는데 화면에 안 나오던 것들이 여기서 전부 줄이 된다. */
export function evidenceLines(a, reasonMap) {
  const ev = a?.evidence ?? {};
  const cur = ev.current ?? {};
  const head = [];
  // 부호 뒤집힘은 **가장 먼저** 말해야 한다 — 마진 수치는 방향 보정 후 값이라
  // PM 116°처럼 건강해 보이고, 그러면 왜 fail인지 화면만 봐서는 알 수 없다
  if (ev.sign_flip) {
    const slots = (ev.sign_flip.slots ?? []).join(", ");
    head.push(`부호 반대: ${slots} (설계와 반대 방향 — 양의 되먹임)`);
  }
  if (cur.pm_deg != null) head.push(`현재 PM ${num(cur.pm_deg)}° / GM ${num(cur.gm_db)} dB`);
  if (cur.zeta != null) head.push(`현재 ζ ${num(cur.zeta)}`);
  if (cur.roll_lambda != null) head.push(`현재 λ ${num(cur.roll_lambda)} rad/s`);
  if (a?.severity != null) {
    head.push(`심각도 ${num(a.severity)} (요구선 대비 부족 비율 — 클수록 심각)`);
  }
  if (ev.interp_gap?.max != null) {
    head.push(`보간 괴리 ${num(100 * ev.interp_gap.max, 3)}% `
      + `(허용 ${num(100 * (ev.interp_gap.tol ?? 0), 2)}%)`);
  }
  if (ev.plant?.d_total != null) {
    head.push(`플랜트 거리 ${num(ev.plant.d_total)} (허용 ${num(ev.plant.tol)})`);
  }
  if (ev.bottleneck) {
    head.push(`ωc/작동기 ${num(ev.bottleneck.wc_over_actuator)} · 지연 위상 `
      + `${num(ev.bottleneck.delay_phase_deg_at_wc)}°`);
  }

  const notes = [];
  // 에스컬레이션은 "무엇을 바꾸면 통과하는가"가 결론이다 — 흐린 회색 나열에 묻히면
  // 사용자는 이 카드를 보고도 다음 행동을 정할 수 없다
  if (ev.bottleneck?.note) notes.push(ev.bottleneck.note);
  // 분류기 자신의 설명 — 왜 이 처방인지를 분류기가 이미 적어 놓았는데 버려져 있었다
  if (a?.action?.note) notes.push(a.action.note);

  const flags = [];
  if (a?.sealed) flags.push(`봉인: ${a.sealed}`);
  if (a?.skipped) flags.push(`건너뜀: ${a.skipped}`);

  const effect = a?.effect
    ? { text: effectText(a.effect), ineffective: a.effect.changed === false }
    : null;

  return {
    head,
    shortfall: shortfallLines(ev.shortfall),
    tuned: tunedLines(ev.tuned, reasonMap),
    relief: reliefLines(ev.bottleneck?.relief, reasonMap),
    effect,
    notes,
    flags,
  };
}
