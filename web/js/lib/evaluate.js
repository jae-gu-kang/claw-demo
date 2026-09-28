/** 평가 lib v2 — 카드 7·판정 10·3단계 검증 모델의 판단 (views가 조립).

서버 응답(influence_evaluate·influence_verify)을 화면 모델로 정규화하고, 요청
본문을 만들고, 상태 어휘를 색·라벨로, 카드 값을 문장으로 옮긴다. **카드·체크의
이름·순서·문턱은 여기 없다** — 전부 서버가 준다(criteria/defaults·결과 echo).
웹이 재기술하면 엔진 재편 날 화면이 옛 순서를 말한다 (02 §5.5).

색은 좋고 나쁨(판정)을 말한다 — 이 표면은 판독대와 달리 **문턱을 아는** 표면이라
(기준이 응답에 동봉된다) 판정색이 참칭이 아니다. na는 판정색이 아니라 회색이다.

판정 요약("나머지 판정 n/n PASS")의 규칙은 checksSummary 한 곳에 산다:
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
export function evaluateRequest(state, { cases, depth, tSettle, tStep,
                                         tHold, fingerprint } = {}) {
  // 판정선은 싣지 않는다 — 서버가 선택 기체의 /criteria·/tuning으로 판정하고 요청 기준은 거절한다(v1.54)
  const body = { ...structuralRequest(state), cases };
  if (depth != null) body.depth = depth;
  if (tSettle != null) body.t_settle = tSettle;
  if (tStep != null) body.t_step = tStep;
  if (tHold != null) body.t_hold = tHold;
  if (fingerprint) body.fingerprint = fingerprint;
  return body;
}

/** 두 결과를 **같은 자로 잰 것인가** — 다르면 델타는 개선이 아니라 기동 차이다.
 *
 * `t_step`은 사용자가 화면에서 고치는 값이라(기본 15) 한 세션 안에서도 바뀐다.
 * 15로 돌리고 30으로 바꿔 다시 돌리면 추종 RMS가 9.17 → 6.65로 찍히는데 게인은
 * 한 글자도 안 바뀌었다 — 「직전 대비 개선」이 정면으로 거짓말이 되는 자리다.
 * 기록이 한쪽이라도 없으면 **모른다**(false)로 둔다: 옛 결과는 스텝을 알 수 없다.
 *
 * **선형끼리는 기동과 무관하게 비교된다.** 선형은 시뮬을 한 번도 안 돌아 기동이
 * 결과에 쓰이지 않는데(결과에 적히기만 한다), 스텝만 바꿔 다시 돌렸다고 ζ·GM·PM
 * 델타를 막으면 **없는 비교 불가를 지어내는** 반대 방향 거짓말이 된다.
 * `maneuverLine`이 같은 이유로 선형에서 침묵하는 것과 한 벌이다.
 */
export const MANEUVER_KEYS = ["dv", "dh", "dpsi", "t_settle", "t_step", "t_hold"];

export function sameManeuver(a, b) {
  if (a?.depth !== b?.depth) return false;
  if (a?.depth === "linear") return true;  // 기동이 쓰이지 않았다
  const x = a?.maneuver, y = b?.maneuver;
  if (!x || !y) return false;
  return MANEUVER_KEYS.every((k) => x[k] === y[k]);
}

/** 결과가 **어느 기동으로** 쟀는가 — 결과 메타 줄의 한 조각.
 *
 * 형상·기준 지문만으로는 두 결과가 같은 자로 잰 것인지 알 수 없다: 스텝이 바뀌면
 * RMS·J가 통째로 다른 뜻이 되는데 지문은 그대로다. 셋을 가른다.
 *
 *   linear   — 빈 문자열. 시뮬을 한 번도 안 돌았으므로 기동을 찍으면 **안 돈
 *              기동을 돈 것처럼** 읽힌다(결과에는 적혀 있어도 쓰이지 않았다)
 *   기록 있음 — 값과 단위. 단위를 빼면 dψ가 rad인지 deg인지 화면만으로 못 정한다
 *   기록 없음 — 옛 결과다. 현행 기본값으로 채우지 않는다(「없음」과 「값」을 섞지 않는다)
 */
export function maneuverLine(model) {
  if (!model || model.depth === "linear") return "";
  const m = model.maneuver;
  if (!m) return "기동 미기록 — 옛 결과라 스텝이 지금과 다를 수 있다";
  return `기동 dh ${m.dh} m · dv ${m.dv} m/s · dψ ${m.dpsi} rad`
    + ` · 간격 ${m.t_step} s`;
}

/** 형상 + 케이스 → /influence/verify 본문 (3단계 검증 — 후보 확정 후 별도 실행). */
export function verifyRequest(state, { cases, depth, midpoints,
                                       tSettle, tStep, tHold, tMission,
                                       fingerprint } = {}) {
  const body = { ...structuralRequest(state), cases };  // 판정선은 싣지 않는다(evaluateRequest와 같은 이유)
  if (depth != null) body.depth = depth;
  if (midpoints != null) body.midpoints = midpoints;
  if (tSettle != null) body.t_settle = tSettle;
  if (tStep != null) body.t_step = tStep;
  if (tHold != null) body.t_hold = tHold;
  if (tMission != null) body.t_mission = tMission;  // 미션 런 천장 덮개 (v1.41)
  if (fingerprint) body.fingerprint = fingerprint;
  return body;
}

/** 서버 응답 → 화면 모델 — 방어적 기본값만, 재계산 없음 (판정은 엔진 몫). */
export function normalizeEvalReport(payload) {
  return {
    depth: payload?.depth ?? null,
    // 어느 기동으로 쟀는가 — 형상·기준 지문만으로는 두 결과가 같은 자로 잰
    // 것인지 알 수 없다(스텝이 바뀌면 RMS·J가 통째로 다른 뜻이 되는데 지문은
    // 그대로다). 옛 결과에는 없으므로 null이고, 화면은 그 사실을 그대로 낸다
    maneuver: payload?.maneuver ?? null,
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

/** 판정 요약 한 줄 — 머리말의 규칙이 전부 여기 산다 (재기술 방지).
 *
 *  이름이 「추가 판정」이었다(v0.67에 고침): 화면이 이 줄을 등급으로 부르지 않으니
 *  단계표의 「나머지 판정」과 결과 줄이 같은 것을 말하는지 알 수 없었고, "추가"는
 *  덤처럼 읽혀 하드 게이트가 여기 들어 있다는 사실과 어긋났다. */
export function checksSummary(checks) {
  if (!checks) return "나머지 판정 — 아직 없다";
  const parts = [`나머지 판정 ${checks.n_pass}/${checks.n_judged} PASS`];
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

/** 미션 프로파일 블록(verify.mission_profile) → 표시 줄 [문자열] (v1.41).

 * 시간축 스케줄 통과 검증(04 §5.5)의 상세다: 무엇을 가로지르려 했고(scenario),
 * 실제로 넘었는지(crossed — 시계열 실측이 정본), 그 동안의 포화·와인드업·실속
 * 여유(facts). RMS는 판정이 아니라 보고다 — 문구가 그렇게 말해야 한다.
 * na(시나리오 없음·미도달·트림 미수렴)는 note가 이미 사유를 드니 줄을 더하지
 * 않는다(없는 수치를 지어내지 않는다).
 */
export function missionProfileLines(block) {
  if (!block?.scenario) return [];
  const lines = [];
  const legs = block.scenario.legs ?? {};
  const legText = (axis, unit) => {
    const l = legs[axis];
    if (!l) return null;
    const [b1, b2] = l.pair;
    return `${axis} ${fmt(b1)}→${fmt(b2)}${unit} (시작 ${fmt(l.start)} → 목표 ${fmt(l.target)})`;
  };
  const legParts = [legText("mach", ""), legText("alt", " m")].filter(Boolean);
  if (legParts.length) {
    lines.push(`가로지르기: ${legParts.join(" · ")}`
      + (block.scenario.t_end != null ? ` · 천장 ${fmt(block.scenario.t_end)} s` : ""));
  }
  for (const [axis, c] of Object.entries(block.crossed ?? {})) {
    lines.push(`통과 실측(${axis}): `
      + c.expected.map((b) => `${fmt(b)}${c.crossed.includes(b) ? "✓" : "✕"}`).join(" "));
  }
  const f = block.facts;
  if (f) {
    lines.push("포화 " + (f.sat_frac == null ? "—" : `${fmt(f.sat_frac * 100)}%`)
      + " · 타율 " + (f.rate_sat_frac == null ? "—" : `${fmt(f.rate_sat_frac * 100)}%`)
      + " · 와인드업 " + (f.windup_frac == null ? "—" : `${fmt(f.windup_frac * 100)}%`)
      + " · 최악 실속마진 " + fmt(f.worst_stall_margin));
    const rms = f.rms ?? {};
    lines.push(`추종 RMS(보고만 — 램프 런에 판정선 없음): 고도 ${fmt(rms.alt_rms)} m · `
      + `속도 ${fmt(rms.spd_rms)} m/s · 헤딩 ${fmt(rms.hdg_rms)} rad`);
  }
  for (const n of block.scenario.notes ?? []) lines.push(n);
  return lines;
}

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
    // 한계 − 트림 몫 − 기동 편차 — 트림은 되지만 기동 여유가 없는 점(하드, 01 §4.1)
    dyn_reserve_worst: (x) => x
      ? `가용 동적 여유 최악 ${fmt(x.value * 100.0)} % (${x.run === "combined" ? "동시명령" : "표준"} 런 @${x.case}, `
        + `기준 ≥ ${fmt((th.dyn_reserve_min_frac ?? 0) * 100.0)} %)`
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

/** 그래프 초점 — 평가 결과가 그래프에서 **어디를 켤 것인가**.
 *
 * 소견이 귀속한 설계변수(파라미터 노드)와 문턱을 넘은 지표(지표 노드)를 뽑는다.
 * 카드·표에 있는 사실을 그림에도 같이 세우는 것이고, 새로 판정하지 않는다 —
 * 판정은 엔진이 이미 했고 여기는 id로 옮길 뿐이다.
 *
 * 귀속도 실패도 없으면 **null**이다. 빈 초점을 내면 캔버스가 전부를 흐린 채
 * 아무것도 안 켜서, 통과한 형상이 "모두 무관"처럼 보인다.
 */
export function evalFocus(model) {
  const knobs = [];
  for (const c of model.cases ?? []) {
    for (const p of (c.attribution?.prescriptions ?? [])) {
      for (const k of (p.knobs ?? [])) if (!knobs.includes(k)) knobs.push(k);
    }
  }
  const metrics = [];
  const loc = model.aggregate?.locality?.metrics ?? {};
  for (const [key, v] of Object.entries(loc)) {
    if (v.verdict && v.verdict !== "ok" && !metrics.includes(key)) metrics.push(key);
  }
  if (!knobs.length && !metrics.length) return null;
  return {
    paramIds: knobs.map((k) => `param:${k}`),
    metricIds: metrics.map((k) => `metric:${k}`),
    caption: `평가 결과 — 귀속된 설계변수 ${knobs.length}개가 문턱을 넘은 `
      + `지표 ${metrics.length}개까지 어떻게 닿는지`,
  };
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

/** 평가 판정 — 칩 배지와 같은 하드 게이트 한 비트: "PASS" | "FAIL" | null(판정 없음 — 케이스 0건·취소).
 *  쇼케이스 보고 data.verdict가 이것이다(진행기가 기대 판정과 대조한다 — lib/showcase verdictOf). */
export function hardGateVerdict(model) {
  const hf = model?.aggregate?.hard_fail;
  if (hf == null) return null;
  return hf ? "FAIL" : "PASS";
}

/** 평가 결과 한 줄 — 칩 배지와 같은 판정 머리(FAIL n / PASS) + 케이스 수·깊이 + 최악 한 줄.
 *  쇼케이스 보고 summary가 이것이다(탭 산출물에서 만든 문장 — 새 해설을 쓰지 않는다).
 *  FAIL이면 하드 위반 첫 줄, PASS면 J 줄이 최악 자리다. 판정이 없으면(케이스 0건·취소) 그렇다고 한다. */
export function evalVerdictLine(model) {
  const agg = model?.aggregate;
  const n = agg?.n_cases ?? (model?.cases ?? []).length;
  const depth = model?.depth ? ` · ${model.depth}` : "";
  const verdict = hardGateVerdict(model);
  if (!verdict) return `판정 없음 — 케이스 ${n}건${depth}`;
  if (verdict === "FAIL") {
    // 위반 목록이 비어 오면(옛 결과) 「undefined」를 찍지 않는다 — 머리만 선다
    const first = hardFailLines(agg)[0];
    return `FAIL ${(agg.hard_fails ?? []).length} — 케이스 ${n}건${depth}${first ? ` · ${first}` : ""}`;
  }
  return `PASS — 케이스 ${n}건${depth} · ${jLine(agg)}`;
}

// 하드 게이트에 말을 거는 소견 규칙 — 포화(축별 기여·타면 예산)와 리미터(실속 여유). 추종 오차
// 분할(error_split)·와인드업은 하드 게이트가 아니다(추종 RMS는 J의 항) — 하드 위반 케이스라도 그
// 카드를 먼저 고르면 실패와 무관한 자리를 흔든다(예제 기체 h3000 고도 추종이 그렇게 늘 서 있다)
const HARD_RULES = new Set(["sat_attrib", "mix_sat", "limiter"]);

/** [얼마나 →]의 대상 — 하드 위반 케이스의 소견에서 **하드 게이트에 말을 거는 첫 처방 카드**.
 *  {case, knobs, card} | null. 카드는 소견 안 순서(엔진 diagnose가 규칙·지배 기여 순으로 낸다)대로 보고,
 *  하드 규칙 카드가 없으면 그 케이스의 첫 카드다. 행 전체(attributionRows의 knobs 합집합)가 아니라
 *  카드 하나인 이유는 비용이다 — 스윕은 설계변수 × 스팬 × 케이스의 곱이라 셋이면 셋 배다. */
export function prescriptionTarget(model) {
  for (const c of model?.cases ?? []) {
    if (!(c.hard_fails ?? []).length) continue;
    const a = c.attribution;
    if (!a || a.status !== "ok") continue;
    const pres = (a.prescriptions ?? []).filter((p) => (p.knobs ?? []).length);
    if (!pres.length) continue;
    const rules = (p) => (p.findings ?? []).map((i) => a.findings?.[i]?.rule);
    const card = pres.find((p) => rules(p).some((r) => HARD_RULES.has(r))) ?? pres[0];
    return { case: c.case, knobs: [...card.knobs], card };
  }
  return null;
}

// ── 실행 버튼 진행 — 버튼에 「케이스 k/N」, 아래 줄에 %·남은 시간 ────────────────
//
// 서버 done/total은 틱 **개수**다. 그런데 틱 비용이 고르지 않다: 트림·선형화는 한순간이고
// 시간축 런이 케이스당 수 초를 먹는다. 틱 개수 그대로 %를 내면 트림 동안 25%까지 튀고
// 런에서 오래 멈춘 것처럼 보이며, 그 %로 낸 남은 시간은 처음에 크게 짧게 나온다.
// 틱 순서는 서버·엔진이 고정한다(routes/influence·pipeline/evaluate) — done만으로 어느 틱까지
// 끝났는지 알므로 그 순서에 비용 가중을 매긴다:
//   evaluate  트림 n → 케이스마다 선형[·표준·동시명령]
//   verify    코너·케이스 블록마다 트림·선형[·표준·동시명령] → 미션 1틱(켜졌으면)
//   openloop  트림 n → 케이스마다 선형화 1
//   scan      트림 n → 케이스마다 base 런 1
//   sweep     트림 n → 런(케이스 × 스팬 점)
// 가중은 상대값이다(grid.js 주석의 실측: 풀 평가 케이스당 5~8 s, 트림·선형은 1 s 미만).
const TICK_COST = { trim: 1, linear: 1, std: 8, comb: 8, base: 8, sweep: 8, mission: 24 };
// 서버 message는 **방금 끝난** 틱이다(「선형: X」가 떠 있는 동안 실제로는 표준 런이 돈다).
// 지금 도는 틱은 순서로 안다 — 그 이름
const TICK_DOING = {
  trim: "트림", linear: "선형화", std: "표준 기동 런", comb: "동시명령 런",
  base: "base 런", sweep: "스윕 런", mission: "미션 프로파일 런",
};

function stageTicks(kind, total, { n = 0, depth = "full" } = {}) {
  const runs = depth === "linear" ? [] : ["std", "comb"];
  const ticks = [];
  if (kind === "verify") {
    const unit = 2 + runs.length;  // 블록 = 트림 + 선형 + 런들
    const blocks = Math.floor(total / unit);
    for (let b = 0; b < blocks; b++) ticks.push("trim", "linear", ...runs);
    if (total - blocks * unit === 1) ticks.push("mission");
    return { ticks, unit, lead: 0, blocks, noun: "코너" };
  }
  for (let i = 0; i < n; i++) ticks.push("trim");
  const block = kind === "evaluate" ? ["linear", ...runs]
    : kind === "openloop" ? ["linear"] : kind === "scan" ? ["base"] : ["sweep"];
  const blocks = Math.max(0, Math.floor((total - n) / block.length));
  for (let b = 0; b < blocks; b++) ticks.push(...block);
  return { ticks, unit: block.length, lead: n, blocks,
           noun: kind === "sweep" ? "런" : "케이스" };
}

/** 실행 잡 진행 → 표시값 {count, frac, eta, doing}.
 *  kind = "evaluate" | "verify" | "openloop" | "scan" | "sweep", n = 케이스 수(트림 선행 틱).
 *  count는 버튼에 서는 짧은 글(「트림 3/15」「케이스 6/15」「코너 12/60」「미션 런」),
 *  frac는 비용 가중 진행(0..1), eta는 남은 초(추정할 근거가 모자라면 null),
 *  doing은 지금 도는 틱의 이름(다 끝났으면 null).
 *  skipped = 본 트림 미수렴 수 — 검증은 그 블록을 1틱으로 건너뛰는데(엔진 verify eval_block)
 *  서버 total은 그대로라, 건너뛴 만큼 틱 순서에서 앞으로 당겨 읽는다. */
export function stageProgress(kind, job, { n = 0, depth = "full", elapsed = null,
                                          skipped = 0 } = {}) {
  const total = Math.max(0, job?.total ?? 0);
  const done = Math.min(Math.max(0, job?.done ?? 0), total);
  if (!total) return { count: "제출 중", frac: 0, eta: null, doing: null };
  const { ticks, unit, lead, blocks, noun } = stageTicks(kind, total, { n, depth });
  const pos = kind === "verify"
    ? Math.min(ticks.length, done + skipped * (unit - 1)) : done;
  const cost = (k) => TICK_COST[k] ?? 1;
  const all = ticks.reduce((s, k) => s + cost(k), 0) || 1;
  const spent = ticks.slice(0, pos).reduce((s, k) => s + cost(k), 0);
  const frac = Math.min(1, spent / all);
  let count;
  if (pos < lead) {
    count = `트림 ${pos + 1}/${lead}`;
  } else if (ticks[pos] === "mission") {
    count = "미션 런";
  } else if (!blocks) {
    count = "마무리";  // 트림이 전부 미수렴 — 셀 케이스가 없다(「케이스 1/0」을 찍지 않는다)
  } else {
    // 지금 도는 블록 — 끝난 블록 수 + 1 (마지막 틱이 끝나면 N/N에 선다)
    const k = Math.min(blocks, Math.floor((pos - lead) / unit) + 1);
    count = `${noun} ${Math.max(k, 1)}/${blocks}`;
  }
  // 남은 시간 — 5% 전·3초 전에는 표본이 모자라 크게 흔들린다(없는 편이 낫다)
  const eta = (elapsed != null && elapsed >= 3 && frac >= 0.05 && frac < 1)
    ? elapsed * (1 - frac) / frac : null;
  return { count, frac, eta, doing: TICK_DOING[ticks[pos]] ?? null };
}

/** 초 → 「약 40초」「약 3분」(남은 시간), exact면 「21초」「3분 5초」(걸린 시간). */
export function durText(sec, { exact = false } = {}) {
  if (sec == null || !Number.isFinite(sec)) return "";
  if (exact) {
    const s = Math.max(0, Math.round(sec));
    return s < 60 ? `${s}초` : `${Math.floor(s / 60)}분${s % 60 ? ` ${s % 60}초` : ""}`;
  }
  if (sec < 60) return `약 ${Math.max(5, Math.round(sec / 5) * 5)}초`;
  return `약 ${Math.round(sec / 60)}분`;
}

/** 끝난 평가 → 버튼에 남는 판정 머리 — 칩 배지와 같은 말(PASS / FAIL n)에 탭의 기호(○✕—)를 붙인다.
 *  판정이 없으면(케이스 0건·취소 뒤 부분 결과) PASS로 위장하지 않고 「판정 없음」이다. */
export function runVerdictMark(model) {
  const v = hardGateVerdict(model);
  if (v === "PASS") return "○ PASS";
  if (v === "FAIL") return `✕ FAIL ${(model.aggregate.hard_fails ?? []).length}`;
  return "— 판정 없음";
}
