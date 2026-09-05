/** 평가 lib v2 — A급 카드·B급 체크·C급 검증 모델의 판단 (views가 조립).

서버 응답(influence_evaluate·influence_verify)을 화면 모델로 정규화하고, 요청
본문을 만들고, 상태 어휘를 색·라벨로, 카드 값을 문장으로 옮긴다. **카드·체크의
이름·순서·문턱은 여기 없다** — 전부 서버가 준다(criteria/defaults·결과 echo).
웹이 재기술하면 엔진 재편 날 화면이 옛 순서를 말한다 (02 §5.5).

색은 좋고 나쁨(판정)을 말한다 — 이 표면은 판독대와 달리 **문턱을 아는** 표면이라
(기준이 응답에 동봉된다) 판정색이 참칭이 아니다. na는 판정색이 아니라 회색이다.

B급 요약("추가 판정 n/n PASS")의 규칙은 checksSummary 한 곳에 산다:
- PASS 분자는 ok만이다 — warn은 "통과했지만 주의"지 정상이 아니다
- na는 분모에서 빠지되 **반드시 병기**된다 — 요약이 판정 불가를 숨기면
  "9건 중 2건은 잴 수도 없었다"가 화면에서 사라진다
*/

import {
  BAD_INK, DIRECTION_LABEL, GOOD_INK, KNOB_CLASS, WARN_INK, structuralRequest,
} from "./influence.js";

// 상태 어휘 — 엔진 evaluate._RANK와 한 벌 (드리프트는 evaluate.test.js가 핀)
export const STATUS_LABEL = { ok: "통과", warn: "주의", fail: "실패", na: "판정 불가" };
const NA_INK = "#98989d";

export function statusInk(status) {
  return { ok: GOOD_INK, warn: WARN_INK, fail: BAD_INK }[status] ?? NA_INK;
}

/** 형상 + 케이스 + 깊이 → /influence/evaluate 본문 (v2 — items 선택은 없다:
 *  비용 게이트는 depth와 별도 검증(verify)이 대신한다). */
export function evaluateRequest(state, { cases, criteria, depth, tSettle, tStep,
                                         tHold, fingerprint } = {}) {
  const body = { ...structuralRequest(state), cases };
  if (depth != null) body.depth = depth;
  if (criteria != null) body.criteria = criteria;
  if (tSettle != null) body.t_settle = tSettle;
  if (tStep != null) body.t_step = tStep;
  if (tHold != null) body.t_hold = tHold;
  if (fingerprint) body.fingerprint = fingerprint;
  return body;
}

/** 형상 + 케이스 → /influence/verify 본문 (C급 — 후보 확정 후 별도 실행). */
export function verifyRequest(state, { cases, criteria, depth, midpoints,
                                       tSettle, tStep, tHold,
                                       fingerprint } = {}) {
  const body = { ...structuralRequest(state), cases };
  if (depth != null) body.depth = depth;
  if (midpoints != null) body.midpoints = midpoints;
  if (criteria != null) body.criteria = criteria;
  if (tSettle != null) body.t_settle = tSettle;
  if (tStep != null) body.t_step = tStep;
  if (tHold != null) body.t_hold = tHold;
  if (fingerprint) body.fingerprint = fingerprint;
  return body;
}

/** 서버 응답 → 화면 모델 — 방어적 기본값만, 재계산 없음 (판정은 엔진 몫). */
export function normalizeEvalReport(payload) {
  return {
    depth: payload?.depth ?? null,
    cards: payload?.cards ?? [],
    checks: payload?.checks ?? null,
    stageOrder: payload?.stage_order ?? [],
    items: payload?.items ?? {},
    hardChecks: payload?.hard_checks ?? [],
    cases: payload?.cases ?? [],
    aggregate: payload?.aggregate ?? null,
    warnings: payload?.warnings ?? [],
    fingerprint: payload?.fingerprint ?? null,
    criteriaFingerprint: payload?.criteria_fingerprint ?? null,
    criteria: payload?.criteria ?? null,
    aborted: payload?.aborted ?? null,
  };
}

/** 검증 응답 → 화면 모델 — 블록 목록(라벨은 서버 verify_meta가 정본). */
export function normalizeVerifyReport(payload) {
  const meta = payload?.verify_meta ?? {};
  const blocks = Object.entries(payload?.verify ?? {}).map(([key, b]) => ({
    key, label: meta[key] ?? key, ...b,
  }));
  return {
    blocks,
    status: payload?.status ?? null,
    depth: payload?.depth ?? null,
    warnings: payload?.warnings ?? [],
    fingerprint: payload?.fingerprint ?? null,
    criteriaFingerprint: payload?.criteria_fingerprint ?? null,
    aborted: payload?.aborted ?? null,
  };
}

/** B급 요약 한 줄 — 머리말의 규칙이 전부 여기 산다 (재기술 방지). */
export function checksSummary(checks) {
  if (!checks) return "추가 판정 — 아직 없다";
  const parts = [`추가 판정 ${checks.n_pass}/${checks.n_judged} PASS`];
  if (checks.n_fail) parts.push(`실패 ${checks.n_fail}`);
  if (checks.n_warn) parts.push(`주의 ${checks.n_warn}`);
  if (checks.n_na) parts.push(`판정 불가 ${checks.n_na}`);
  return parts.join(" · ");
}

const fmt = (v, digits = 3) => {
  if (v == null) return "—";
  const n = Number(v);
  if (Number.isNaN(n)) return String(v);  // 수가 아닌 값(케이스 이름 등)은 그대로
  if (!Number.isFinite(n)) return n > 0 ? "∞" : "−∞";
  return String(Number(n.toPrecision(digits)));
};

/** 카드 하나 → 표시 줄 목록 — 값/기준/최악 운용점 (사용자 확정 카드 문법).
 *
 * 값 dict의 모양은 카드마다 다르다(서버 _build_cards가 정본) — 여기는 알려진
 * 키를 문장으로 옮기고, 모르는 키는 "이름 값"으로 그대로 낸다(새 필드가 생겨도
 * 화면에서 사라지지 않게). 값이 없으면 note(사유)가 줄이 된다.
 */
export function cardLines(card) {
  const lines = [];
  const v = card.value;
  if (v == null) {
    lines.push(card.note || "값 없음 — 사유 미상");
    return lines;
  }
  const th = card.threshold ?? {};
  const known = {
    // ①: 최악 모드 ζ·ωn
    mode: (x) => `최악 모드 ${String(x).replace("zeta_", "")}`,
    case: () => null,  // worst_case 줄이 이미 싣는다 — 두 번 찍지 않는다
    zeta: (x) => `ζ ${fmt(x)} (기준 ≥ ${fmt(th.zeta_min)})`,
    wn: (x) => `ωn ${fmt(x)} rad/s`,
    // ②③
    gm_db: (x) => `GM ${fmt(x)} dB (기준 ≥ ${fmt(th.gm_min_db)} dB)`,
    pm_deg: (x) => `PM ${fmt(x)}° (기준 ≥ ${fmt(th.pm_min_deg)}°)`,
    delay_margin_s: (x) => `지연 여유 ${fmt(x * 1000.0)} ms (PM의 환산)`,
    loop: (x) => `루프 ${x}`,
    // ④
    roll_lambda: (x) => `λ_roll ${fmt(x)} rad/s (목표 ${fmt(th.roll_lambda_target)})`,
    min_crossover: (x) => x
      ? `최저 교차 ${fmt(x.value)} rad/s (${x.loop} @${x.case})` : null,
    participation: (x) => x != null ? `참여도 ${fmt(x)}` : null,
    unstable: (x) => x ? "발산근 — 대역폭이 아니라 발산이다" : null,
    target: () => null,  // roll_lambda 줄이 이미 실었다
    // ⑤
    ts_worst: (x) => x
      ? `Ts 최악 ${fmt(x.value)} s (${x.axis} @${x.case})` : null,
    mp_worst: (x) => x
      ? `Mp 최악 ${fmt(x.value * 100.0)} % (${x.axis} @${x.case})` : null,
    // ⑥
    rel_worst: (x) => `판정선 대비 ${fmt(x * 100.0)} %`,
    axis: (x) => `축 ${x}`,
    value: (x) => `RMS ${fmt(x)}`,
    limit: (x) => `기준 ≤ ${fmt(x)}`,
    judged: () => null,
    // ⑦
    usage_worst: (x) => x
      ? `사용률 최악 ${fmt(x.value * 100.0)} % (${x.channel} ${x.kind} @${x.case})`
      : null,
    trim_frac_worst: (x) => x
      ? `트림 소모 최악 ${fmt(x.value * 100.0)} % (@${x.case})` : null,
    remaining_worst: (x) => x
      ? `잔여 권한 최악 ${fmt(x.value * 100.0)} % (${x.axis} @${x.case}, `
        + `기준 ≥ ${fmt((th.b_min_frac ?? 0) * 100.0)} %)`
      : null,
  };
  for (const [k, val] of Object.entries(v)) {
    const f = known[k];
    const line = f ? f(val) : `${k} ${fmt(val)}`;
    if (line) lines.push(line);
  }
  if (card.worst_case) lines.push(`최악 운용점 ${card.worst_case}`);
  if (card.note) lines.push(card.note);
  return lines;
}

/** 마진 조성 한 줄 — **무슨 플랜트에서 판정했나**. 마진 맵이 판정선을 늘 말하는
 *  것과 같은 규약이고, 조성이 갈리면 같은 설계가 화면마다 다른 마진을 받는다
 *  (작동기·지연을 빼면 −180° 교차가 비물리 자리로 가 GM이 아티팩트가 된다). */
export function compositionLine(model) {
  const c = model.cases?.[0]?.stages?.margins?.composition;
  if (!c) return null;
  if (typeof c === "string") return c;  // 구버전 저장물 — 문장 그대로
  const bits = [];
  if (c.actuator_wn != null) {
    bits.push(`작동기 ωn ${fmt(c.actuator_wn)} rad/s · ζ ${fmt(c.actuator_zeta)}`);
  }
  if (c.delay_s != null) bits.push(`지연 ${fmt(c.delay_s * 1000)} ms`);
  if (c.pade_order != null) bits.push(`Padé ${c.pade_order}차`);
  return [c.text, bits.join(" · ")].filter(Boolean).join(" — ");
}

/** 케이스별 소견(원인 귀속) 행 — **판정 옆에 서는 표면**이지 별도 실행이 아니다.
 *
 * 서버가 실패 케이스의 같은 런에서 귀속까지 내므로(엔진 evaluate 인라인 귀속),
 * 화면은 그것을 케이스마다 한 줄로 옮긴다. 귀속이 없으면 사유가 값 자리다.
 */
export function attributionRows(model) {
  return model.cases.map((c) => {
    const a = c.attribution;
    if (!a || a.status !== "ok") {
      return { case: c.case, solvable: false, knobs: [],
               text: a?.note ?? "소견 없음 — 사유 미상" };
    }
    const pres = a.prescriptions ?? [];
    if (!pres.length) {
      return { case: c.case, solvable: false, knobs: [],
               text: "결함은 있으나 처방 가능한 자리를 못 찾았다" };
    }
    const knobs = [...new Set(pres.flatMap((p) => p.knobs ?? []))];
    const text = pres.map((p) => {
      const cls = KNOB_CLASS[p.knob_class]?.label ?? p.knob_class;
      const dir = DIRECTION_LABEL[p.direction] ?? "";
      return `${(p.knobs ?? []).join(", ")} ${dir} [${cls}]`;
    }).join(" · ");
    return { case: c.case, solvable: true, knobs, text,
             findings: a.findings ?? [], prescriptions: pres };
  });
}

/** 국소성 — 어디서 나쁜가와 그래서 어느 층을 만질 것인가. 통과 지표는 줄을
 *  차지하지 않는다(전부 통과면 빈 목록이고, 그건 요약 한 줄이 이미 말한다). */
export function localityLines(locality) {
  const metrics = locality?.metrics ?? null;
  if (!metrics) return [];
  const VERDICT = { local: "국소", global: "전역" };
  const out = [];
  for (const [key, v] of Object.entries(metrics)) {
    if (v.verdict === "ok") continue;
    const cls = KNOB_CLASS[v.knob_class]?.label ?? v.knob_class ?? "—";
    const cases = (v.bad_cases ?? []).slice(0, 3).join(", ")
      + ((v.bad_cases ?? []).length > 3 ? " 외" : "");
    out.push(`${key} ${VERDICT[v.verdict] ?? v.verdict}`
      + ` ${v.n_bad}/${v.n_cases} · 처방 층 ${cls} · ${cases}`);
  }
  return out;
}

/** 재측정 델타 — 카드 대표 스칼라끼리 짝지어 "얼마에서 얼마로"를 낸다.
 *
 * 좋아졌는지는 카드가 선언한 극성(primary.better)이 정한다 — 화면이 부호로
 * 추측하면 실속마진처럼 클수록 좋은 지표에서 정반대를 말한다. 한쪽이라도 못 잰
 * 카드는 improved=null이고 사유가 값 자리다(개선만 보여 주면 낙관 편향이 된다).
 */
export function cardDeltas(beforeCards, afterCards) {
  const before = new Map((beforeCards ?? []).map((c) => [c.key, c]));
  return (afterCards ?? []).map((a) => {
    const b = before.get(a.key);
    const pb = b?.primary;
    const pa = a.primary;
    if (!pb || !pa) {
      return { key: a.key, label: a.label, improved: null,
               text: !pb ? "이전 값 없음 — 비교 불가" : "이번 값 판정 불가" };
    }
    const d = pa.value - pb.value;
    const improved = d === 0 ? null
      : (pa.better === "higher" ? d > 0 : d < 0);
    const u = pa.unit && pa.unit !== "-" ? ` ${pa.unit}` : "";
    return {
      key: a.key, label: a.label, improved,
      delta: d,
      text: `${fmt(pb.value)} → ${fmt(pa.value)}${u}`
        + ` (${d >= 0 ? "+" : "−"}${fmt(Math.abs(d))})`,
    };
  });
}

/** 케이스 × 항목 상태 격자 — 상세 표용. 행이 케이스, 열이 stage_order(원자료). */
export function caseGrid(model) {
  return model.cases.map((c) => ({
    case: c.case,
    midpoint: !!c.midpoint,
    aborted: !!c.aborted,
    hardFails: (c.hard_fails ?? []).length,
    statuses: model.stageOrder.map((k) => c.stages?.[k]?.status ?? "na"),
  }));
}

/** J 한 줄 — null은 빈칸이 아니라 사유다 (0으로 위장 금지, 저장소 전역 규약). */
export function jLine(aggregate) {
  if (aggregate?.J != null) {
    const j = aggregate.J;
    return `J = ${Number(j.worst).toPrecision(3)} (최악 케이스 ${j.case})`;
  }
  const why = aggregate?.J_reason ?? "사유 없음";
  return `J 없음 — ${why}`;
}

/** 하드 실패 목록 → 사람 문장. check 키는 엔진 HARD_CHECKS 어휘 그대로 둔다 —
 *  번역하면 엔진에 검사가 하나 늘 때 여기가 조용히 낡는다. */
export function hardFailLines(aggregate) {
  return (aggregate?.hard_fails ?? []).map((f) => {
    const where = f.loop ?? f.channel ?? f.axis ?? null;
    const value = Array.isArray(f.value)
      ? `[${f.value.map((v) => Number(v).toPrecision(3)).join(", ")}]`
      : Number(f.value).toPrecision(3);
    return `${f.check}${where ? ` (${where})` : ""} — ${value}`
      + ` (한계 ${f.limit}) @${f.case}`;
  });
}
