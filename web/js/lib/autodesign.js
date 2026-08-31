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
 * 게인을 확정할 수 있으면 **아무것도 검증하지 않은 게인이 정본이 된다.**
 *
 * 커버리지 공백(coverage_gaps)은 여기서 막지 않는다 — 검증점이 모자란 실행도
 * 앵커에서는 판정이 났고, 그것을 확정조차 못 하게 하는 것은 과하다. 대신 무엇을
 * 모르고 확정하는지를 adoptWarnText가 문장으로 낸다. 막는 것과 말하는 것은 다르다. */
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

/** 확정해도 되지만 **무엇을 모르고 확정하는지** — 커버리지 공백이 없으면 null.
 *
 * adoptBlockedText가 "확정 못 한다"라면 이쪽은 "확정은 되는데 이만큼은 안 봤다"다.
 * 둘을 한 문장으로 뭉치면 막는 사유와 경고가 같은 무게로 읽혀, 정작 막아야 할
 * 미검증 실행이 흔한 경고에 섞인다. */
export function adoptWarnText(report) {
  const gaps = coverageLines(report).filter((l) => l.tone !== "hint");
  if (!gaps.length) return null;
  return "확정은 막지 않는다 — 다만 이 실행이 무엇을 안 봤는지는 알고 확정해야 한다. "
    + gaps.map((l) => l.text).join(" / ")
    + " 이대로 확정하면 그 미검증 구간이 검증된 적 없는 채로 시뮬·마진·Autocode의 "
    + "정본이 된다.";
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
    // 원장 행 수 — 처방 카드 수와 다른 수다. 카드 없는 미달이 대부분이라
    // 이 수가 카드 수보다 훨씬 클 수 있고, 그 격차가 곧 "안 보이던 것"의 규모다
    ["ledger_size", "미달 원장"],
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
  na_no_crossover: "교차가 없어 이 루프의 마진을 잴 수 없다 — 통과가 아니라 판정 불가다."
    + " 루프 조성·게인 부호를 확인한다",
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
    // from이 없는 축은 "지금 그것이 없다"는 뜻이다 (필터 추가 프로브) — "—"로
    // 그리면 "값을 모른다"로 읽힌다
    const from = p.from == null && p.to != null ? "없음" : num(p.from);
    const move = p.from == null && p.to == null
      ? "" : ` (${p.change ?? "?"} ${from} → ${num(p.to)})`;
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

// ── 미달 원장 ──────────────────────────────────────────────────────────

/** 원장 행 종류 → {label, text}. label은 표 칸, text는 "무슨 뜻이고 다음에 뭘 하나".
 *
 * 처방 카드가 붙는 실패는 미달의 일부일 뿐이다 — 처방이 나오지 않는 미달(튜닝이
 * 설계 목표를 못 채운 자리, 판정 불가, 엔벨로프 경계, 튜닝을 건너뛴 점, 트림
 * 미수렴, 반영했는데 안 바뀐 처방)이 오히려 더 많다. 종전 화면은 그중 카드가 있는
 * 것만 그려서, **처방이 안 나온 미달은 화면 어디에도 없었다.**
 *
 * 종류마다 다음 행동이 다르므로 라벨만 붙이고 뜻을 안 적으면 표가 "무엇이 안 됐나"만
 * 말하고 "그래서 뭘 하나"는 말하지 않는다. */
export const LEDGER_KIND = {
  verify: {
    label: "검증 미달",
    text: "보간 실효 게인으로 잰 마진이 합격선(fail) 또는 목표선(warn) 아래다 — "
      + "처방 카드가 있으면 승인해 재개하고, 없으면 그 점·자리를 직접 볼 것",
  },
  tune: {
    label: "튜닝 목표 미달",
    text: "자동 튜닝이 설계 목표를 못 채웠다 — 합격선은 넘길 수 있다. 사유를 보고 "
      + "예산을 늘리거나 목표를 낮춘다",
  },
  unjudged: {
    label: "판정 불가",
    text: "교차 없음(nan)이거나 트림 미수렴이라 판정이 안 났다 — 통과가 아니다. "
      + "이 자리는 검증되지 않은 채로 남는다",
  },
  outside_envelope: {
    label: "엔벨로프 경계",
    text: "포화·α 여유가 없어 처방·수렴 판정에서 뺀 점이다 — 마진은 참고값이다. "
      + "설계 범위에서 뺄 점인지 먼저 정할 것",
  },
  not_trimmed: {
    label: "트림 미수렴",
    text: "트림해를 못 찾아 아무것도 못 봤다 — 이 점에는 마진도 게인 근거도 없다. "
      + "격자 범위·조종면 한계를 확인할 것",
  },
  skipped: {
    label: "튜닝 건너뜀",
    text: "이 점에서는 튜닝을 돌리지 않았다 — 게인은 이웃에서 보간된 값이고 그 자리의 "
      + "근거는 없다. 점 예산을 늘리거나 그 점을 breakpoint로 올린다",
  },
  ineffective: {
    label: "무효 처방",
    text: "반영했는데 판정이 안 움직였다 — 이터 예산만 나갔다. 같은 처방을 다시 "
      + "승인하지 말고 상위 설계·격자를 볼 것",
  },
};

/** 종류 라벨 — 모르는 코드는 **코드 그대로**. 삼키면 엔진에 종류가 늘어도 화면이
 * 조용해지고, 그 행은 표에서 이름 없는 줄이 된다. */
export function ledgerKindLabel(kind) {
  return LEDGER_KIND[kind]?.label ?? String(kind ?? "?");
}

export function ledgerKindText(kind) {
  return LEDGER_KIND[kind]?.text
    ?? `화면이 모르는 종류다 (${kind ?? "없음"}) — 엔진과 화면의 어휘가 어긋났다. `
      + "결과 JSON의 ledger를 직접 볼 것.";
}

/** 행 색 계열 — kind가 먼저, 그다음 status.
 *
 * fail 계열은 빨강, 목표 미달·판정 불가는 주황, 설계 대상 밖(엔벨로프·건너뜀)은
 * 회색, 무효 처방은 따로 강조한다 — 무효 처방은 "미달"이면서 동시에 "예산을 태운
 * 처방"이라, 다른 미달과 같은 색으로 두면 눈에 안 띈다. */
export function ledgerTone(row) {
  const kind = row?.kind;
  if (kind === "ineffective") return "ineffective";
  if (kind === "outside_envelope" || kind === "skipped") return "na";
  if (kind === "not_trimmed") return "fail";
  if (kind === "tune" || kind === "unjudged") return "warn";
  const s = row?.status;
  if (s === "fail") return "fail";
  if (s === "warn") return "warn";
  if (s === "ok") return "ok";
  return "na";
}

/** 심각도 정렬 키 — 큰 것이 앞. null(못 잼)이 가장 앞, 그다음 ∞ 부족.
 *
 * 엔진 severity와 같은 규약이다: "얼마나 나쁜지 모른다"가 먼저다. 비유한값은
 * 문자열로 오므로(serialize.py) numeric()으로 걸러 부호만 본다 — 숫자로 다루면
 * "inf" 비교가 전부 false가 되어 최악이 목록 꼬리에 가라앉는다. */
function severityKey(s) {
  if (s == null) return Number.POSITIVE_INFINITY;
  const v = numeric(s);
  if (v != null) return v;
  return s === "inf" ? Number.MAX_VALUE : -Number.MAX_VALUE;
}

/** 원장 행의 처방 칸 한 줄 — 처방이 없으면 null.
 *
 * verdict만 찍으면 "그 처방이 어떻게 됐는가"가 빠진다. 반영 여부와 효과까지 같은
 * 줄에 있어야, 카드 목록을 따로 뒤지지 않고도 이 미달이 손을 탄 자리인지 알 수 있다. */
export function ledgerActionText(action) {
  if (!action) return null;
  const parts = [VERDICT_LABEL[action.verdict] ?? action.verdict ?? action.type ?? "처방"];
  if (!action.applied) parts.push("미반영 — 승인하면 반영된다");
  else if (action.changed === false) {
    parts.push("반영했으나 판정이 그대로다 — 이 자리에서 듣지 않았다");
  } else if (action.changed) parts.push("반영 후 판정이 움직였다");
  else parts.push("반영됨 — 효과는 다음 검증에서 잰다");
  if (action.sealed) parts.push(`봉인: ${action.sealed}`);
  return parts.join(" · ");
}

/** body.ledger → 표 행. 없으면 [] (원장이 생기기 전의 구형 결과도 그대로 뜬다).
 *
 * 표시용 필드를 여기서 붙인다 — 사유 한국어, 부족 한 줄(가장 심각한 지표 하나),
 * 종류 라벨·뜻, 색 계열, 심각도 표기, 처방 한 줄. 뷰는 배치만 한다.
 *
 * 정렬은 엔진 규약(severity 내림차순·못 잼이 맨 앞)을 여기서 한 번 더 세운다.
 * 엔진 순서를 그대로 믿으면 계약이 흔들렸을 때 화면이 조용히 잘못된 순서를 그리고,
 * 상위 N개만 펼치는 화면에서 그것은 곧 **가장 나쁜 행이 접힌 채로 남는 것**이다.
 * 같은 심각도 안에서는 엔진 순서를 지킨다(JS sort는 안정 정렬). */
export function ledgerRows(body, reasonMap) {
  const rows = (body?.ledger ?? []).map((r) => {
    const worst = shortfallLines(r?.shortfall)[0] ?? null;
    const reasonLine = reasonText(r?.reason, reasonMap);
    const note = r?.note ?? null;
    // 튜닝 행에는 shortfall이 없다 — 검증 항목이 아니라서 요구선 대비 부족을 못 낸다.
    // 대신 목표와 달성이 따로 실려 오는데, 그 칸을 비우면 "얼마나 모자란가"가 원장에서
    // 사라진다(그걸 보려고 만든 표다). 달성은 **아는 지표만** 적는다 — 엔진 레코드는
    // 조성 메타를 함께 싣는다 (tunedLines와 같은 이유)
    let shortfallLine = worst?.text ?? null;
    let shortfallKind = worst?.kind ?? null;
    if (!shortfallLine) {
      const parts = [];
      if (r?.target != null) parts.push(`목표 ${num(r.target)}`);
      const ach = achievedText(r?.achieved);
      if (ach) parts.push(`달성 ${ach}`);
      if (parts.length) {
        shortfallLine = parts.join(" · ");
        shortfallKind = null; // 부족량을 잰 것이 아니다 — 빨강으로 칠하지 않는다
      }
    }
    return {
      point: r?.point ?? null,
      loop: r?.loop ?? null,
      kind: r?.kind ?? null,
      status: r?.status ?? null,
      severity: r?.severity ?? null,
      target: r?.target ?? null,
      note,
      // 엔진의 tune 행은 note에 사유 문구를 그대로 넣는다(REASON_TEXT[reason]) —
      // 사유 줄이 같은 문장을 이미 담고 있으면 표에 한 문장이 두 번 뜬다
      noteLine: note && reasonLine && reasonLine.includes(note) ? null : note,
      action: r?.action ?? null,
      kindLabel: ledgerKindLabel(r?.kind),
      kindText: ledgerKindText(r?.kind),
      tone: ledgerTone(r),
      reason: r?.reason ?? null,
      reasonLine,
      // 지표가 여럿이어도 표에는 가장 심각한 하나만 — 나머지는 처방 카드에 있다
      shortfallLine,
      shortfallKind,
      // 못 잰 것을 "0"으로 그리면 최악이 최선처럼 보인다 — 낱말로 적는다
      severityText: r?.severity == null ? "못 잼" : num(r.severity),
      actionLine: ledgerActionText(r?.action),
    };
  });
  return rows.sort((a, b) => {
    const ka = severityKey(a.severity);
    const kb = severityKey(b.severity);
    return ka === kb ? 0 : kb - ka;
  });
}

/** 원장이 잘렸다는 고지 한 줄 — 전량이면 null.
 *
 * 저장물은 원장을 severity 상위 N행만 싣는다(routes/design.py MAX_LEDGER_ROWS).
 * 원장은 "이 실행이 못 맞춘 것 전부"를 뜻하는 목록이라, 조용히 잘린 원장은 **못
 * 맞춘 것이 그것뿐이라고 말하는 목록**이 된다 — 실패 0을 통과로 위장하지 않으려고
 * judged를 함께 세는 것과 같은 이유로, 잘린 사실은 표 위에 적는다.
 *
 * 고지(ledger_truncated)가 없어도 report.ledger_size가 행 수보다 크면 잘린 것이다 —
 * 두 출처 중 하나만 믿으면 다른 쪽이 빠졌을 때 화면이 조용해진다. */
export function ledgerTruncatedText(body) {
  const kept = (body?.ledger ?? []).length;
  if (!kept) return null;
  const total = numeric(body?.ledger_truncated?.total)
    ?? numeric(body?.report?.ledger_size);
  if (total == null || total <= kept) return null;
  return `원장 ${total}행 중 ${kept}행만 이 결과에 실렸다 (저장 크기 상한) — `
    + `나머지 ${total - kept}행은 여기에 없다. 심각도 상위부터 남으므로 잘린 쪽이 `
    + "덜 심각하지만, 이 표를 '미달은 이게 전부'로 읽으면 안 된다.";
}

// ── 검증 커버리지 ──────────────────────────────────────────────────────

/** 격자 세분화 중단 사유 → 한국어 [폴백]. 모르는 코드는 코드 그대로 붙는다. */
const REFINE_ABORT_TEXT = {
  budget_points: "점 예산 소진 (점 예산을 올리면 더 촘촘해진다)",
  budget_iters: "이터 예산 소진",
};

function refineAbortText(code) {
  const t = REFINE_ABORT_TEXT[code];
  return t ? `${code} — ${t}` : String(code);
}

const _TONE_RANK = { fail: 2, warn: 1, hint: 0 };

/** report.coverage·coverage_gaps → 줄 목록 [{key, tone, text}] — 없으면 [].
 *
 * "무엇을 봤나"가 아니라 **무엇을 안 봤나**를 세는 줄이다. 판정·실패 수는 본 것만
 * 세므로, 안 본 것이 많을수록 그 수치는 오히려 건강해 보인다 — 검증점이 0이면
 * 실패도 0이다.
 *
 * 검증점 0인데 못 넣은 구간이 있는 것이 가장 강한 줄이다: 보간 구간 검증이 한 건도
 * 수행되지 않았다는 뜻이고, 그러면 판정된 자리가 전부 자기 게인이 직접 튜닝된
 * 앵커다 — 스케줄이 breakpoint 사이에서 무너지는지는 아무도 보지 않았다.
 *
 * 프로즈는 엔진이 정본이다(coverage_gaps). 여기서 만드는 문장은 **엔진 문장이 없을
 * 때만** 붙는다 — 둘 다 내면 같은 말이 색만 달리해 두 번 뜬다. 수치 줄은 항상 낸다:
 * 엔진 문장은 "왜 문제인가"를 말하고 이 줄은 "몇 개인가"를 말한다.
 *
 * 검증점 수와 못 넣은 수는 **더하지 않는다**. validation_points는 지금 점집합에
 * 실재하는 검증점 수이고(스테이지 카운터로 세면 VERIFY가 여러 번 도는 이터레이션에서
 * 마지막 패스 값만 남아, 15개를 넣고도 0으로 보고된다), validation_missing은 요구했는데
 * 점 예산 때문에 못 넣은 구간 수다. 이터가 돌면 요구가 갱신되므로 둘의 합은 전체 구간
 * 수가 아니다 — "요구 N개 중 M개"라고 쓰면 화면이 분모를 지어내게 된다.
 *
 * 줄 순서는 심각도순(fail → warn → hint)으로 세운다. 엔진 문장이 먼저 오면 가장 큰
 * 공백이 목록 중간에 묻힌다. */
export function coverageLines(report) {
  const c = report?.coverage ?? null;
  const gaps = (report?.coverage_gaps ?? []).filter((g) => String(g ?? "").trim());
  // 엔진 문장이 있으면 화면은 수치만 말한다 — 프로즈를 다시 적지 않는다
  const prose = (s) => (gaps.length ? "" : s);
  const out = [];
  if (c) {
    // 검증점 수가 아예 안 온 것과 0인 것은 다르다 — 없는 수를 0으로 읽으면
    // "한 건도 안 봤다"를 결과가 말한 적 없는데 화면이 단정하게 된다
    const got = numeric(c.validation_points);
    const missing = numeric(c.validation_missing) ?? 0;
    if (got == null && missing > 0) {
      out.push({ key: "validation", tone: "warn",
        text: `보간 구간 ${num(missing)}개가 검증점 없이 남았는데 실제로 몇 개가 검증됐는지를 `
          + "결과가 말하지 않는다 — 무엇을 봤는지 확인할 수 없다." });
    } else if (got === 0 && missing > 0) {
      out.push({ key: "validation", tone: "fail",
        text: `보간 구간 검증점이 한 개도 없다 (검증점 없이 남은 구간 ${num(missing)}개).`
          + prose(" 판정된 자리가 전부 자기 게인이 직접 튜닝된 앵커다 —"
            + " 스케줄이 breakpoint 사이에서 무너지는지는 보지 않았다.") });
    } else if (got > 0 && missing > 0) {
      out.push({ key: "validation", tone: "warn",
        text: `보간 구간 ${num(missing)}개가 검증점 없이 남았다 (검증된 구간은 ${num(got)}개).`
          + prose(" 그 구간의 스케줄은 보지 않았다.") });
    } else if (got > 0) {
      // 못 넣은 구간이 없다 — 이건 공백이 아니라 근거라 회색으로 둔다
      out.push({ key: "validation", tone: "hint",
        text: `보간 구간 검증점 ${num(got)}` });
    }
    // got === 0 && missing === 0이면 아무 말도 안 한다 — 검증할 구간 자체가 없었다

    const rem = numeric(c.refine_remaining);
    const tol = numeric(c.refine_tol);
    if (rem != null && tol != null) {
      out.push(rem > tol
        ? { key: "refine", tone: "warn",
          text: `REFINE이 남긴 최대 플랜트 거리 ${num(rem)} (허용 ${num(tol)})`
            + `${c.refine_aborted ? ` · 중단 사유 ${refineAbortText(c.refine_aborted)}` : ""}`
            + prose(" — 격자가 플랜트 변화를 다 못 따라갔다."
              + " 그 구간의 게인은 보간으로만 채워진다.") }
        : { key: "refine", tone: "hint",
          text: `플랜트 거리 잔여 ${num(rem)} ≤ 허용 ${num(tol)}` });
    } else if (c.refine_aborted) {
      // 거리를 못 재도 중단 사실은 남는다 — 조용히 넘기면 격자가 계획대로 찼는지 모른다
      out.push({ key: "refine", tone: "warn",
        text: `격자 세분화 중단 — ${refineAbortText(c.refine_aborted)}` });
    }
    const nt = numeric(c.not_trimmed) ?? 0;
    if (nt > 0) {
      out.push({ key: "not_trimmed", tone: "warn",
        text: `트림 미수렴 ${num(nt)}점`
          + prose(" — 그 점들은 실패 목록에도 판정 수에도 들어가지 않는다.") });
    }
  }
  // 엔진이 만든 문장 — 화면이 다시 쓰지 않는다. 비어 있지 않다는 것 자체가
  // "무엇을 안 봤는지가 있는 실행"이라는 신호다
  gaps.forEach((g, i) => {
    out.push({ key: `gap${i}`, tone: "warn", text: String(g) });
  });
  return out.sort((a, b) => (_TONE_RANK[b.tone] ?? 0) - (_TONE_RANK[a.tone] ?? 0));
}
