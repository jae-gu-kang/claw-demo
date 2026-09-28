/** 초기 게인 산출 근거 결과 → 화면 줄 (05 §10.1 · 06 §8).

수치·판정(전체 모델 달성 ok·작동기 포함 안정·예산 ok·자세 passing)·사유 문구는 전부 엔진이 준다 —
여기는 줄 세우기와 문구 조립뿐이다. 못 잰 값(null)은 0으로 위장하지 않고 null 그대로 나른다(화면이 "—").
*/

const num = (v, digits = 3) =>
  (typeof v === "number" && Number.isFinite(v) ? Number(v.toPrecision(digits)).toString() : "—");

/** 저차 근사 모델 한 줄 — 1차는 a·b, 2차는 개루프 ζ·ωn과 b. */
export function modelText(m) {
  if (!m) return "—";
  if (m.kind === "first_order") return `${m.label} — a=${num(m.a)} · b=${num(m.b)}`;
  const open = m.open_wn != null
    ? `개루프 ζ ${num(m.open_zeta)} · ωn ${num(m.open_wn)} rad/s`
    : "개루프 진동쌍 없음";
  return `${m.label} — ${open} · b=${num(m.b)}`;
}

const reasonLine = (r) => (r.reason ? `${r.reason} — ${r.reason_text ?? ""}` : null);

/** 머리말 — 성공이면 조건·트림 요약, 실패면 사유. */
export function basisHead(body) {
  if (!body) return { ok: false, line: "결과 없음" };
  if (!body.ok) return { ok: false, line: body.reason_text ?? body.reason ?? "실패" };
  const t = body.trim ?? {};
  const degOf = (rad) => (typeof rad === "number" && Number.isFinite(rad)
    ? `${(rad * 180 / Math.PI).toFixed(2)}°` : "—");
  return {
    ok: true,
    line: `${body.case?.name ?? ""} 트림 — α ${degOf(t.alpha)} · δe ${degOf(t.de)} · 스로틀 `
      + (typeof t.throttle === "number" ? `${Math.round(t.throttle * 100)} %` : "—")
      + ` · 대표 오차 ${num(body.e_ref_dps)} °/s`,
  };
}

// 엔진 지표 키 → 화면 기호 — 목표 줄(「목표(응답 동봉): ζ_sp · ζ_dr · λ_roll」)과 같은 표기
const METRIC_LABEL = { zeta_sp: "ζ_sp", zeta_dr: "ζ_dr", roll_lambda: "λ_roll" };

/** 지표 키 → 기호. 모르는 키는 그대로(엔진이 지표를 더해도 글이 사라지지 않게), 없으면 "—". */
export const metricLabel = (key) => (key == null ? "—" : METRIC_LABEL[key] ?? String(key));

const finite = (v) => typeof v === "number" && Number.isFinite(v);

/** 레이트 자리 줄 — body.order 순서. 판정 불리언은 엔진 것 그대로다. gap은 목표 대비 상대 차
 *  (달성 − 목표)/목표 — 판정을 대신하지 않고, 근소 미달(−0.4 %)과 큰 미달(−30 %)을 가르는 수다.
 *  못 잰 값·후보 없음·목표 0이면 null. */
export function basisRates(body) {
  return (body?.order ?? []).map((name) => {
    const r = body.rates?.[name] ?? {};
    const achieved = r.full?.achieved ?? null;
    const target = r.target?.value ?? null;
    return {
      name,
      slot: r.slot ?? name,
      model: modelText(r.model),
      k: r.candidate ? r.candidate.k : null,
      note: r.candidate?.note ?? null,
      metric: r.target?.metric ?? null,
      target: r.target?.value ?? null,
      achieved,
      achievedOk: r.full?.ok ?? null,
      gap: r.candidate && finite(achieved) && finite(target) && target !== 0 ? (achieved - target) / target : null,
      stable: r.full?.stable ?? null,
      budget: r.budget ?? null,
      neighbors: (r.neighbors ?? []).map((n) => ({
        mult: n.mult, k: n.k, achieved: n.achieved ?? null, stable: n.stable ?? null,
      })),
      signBasis: r.sign_basis ?? "",
      reasonText: reasonLine(r),
    };
  });
}

/** 레이트 줄 하나의 달성 글 — 「ζ_sp 0.698/0.7 (−0.3 %)」. 판정 배지 옆·쇼케이스 보고에 같은 글을 쓴다.
 *  후보가 없으면 null(잴 것이 없다), 못 잰 값이면 차 없이 「—/목표」. */
export function achievedText(row) {
  if (row?.k == null) return null;
  const head = `${metricLabel(row.metric)} ${num(row.achieved)}/${num(row.target)}`;
  if (row.gap == null) return head;
  const pct = (row.gap * 100).toFixed(1);
  return `${head} (${row.gap < 0 ? `−${pct.slice(1)}` : `+${pct}`} %)`;
}

/** 자세 PI 줄 — 튜너 루프쉐이핑 결과. passing은 엔진 판정 그대로다. */
export function basisAttitude(body) {
  return ["pitch_att", "roll_att"].filter((n) => body?.attitude?.[n]).map((name) => {
    const a = body.attitude[name];
    return {
      name,
      slot: a.slot ?? name,
      kp: a.kp ?? null,
      ki: a.ki ?? null,
      wcAtt: a.wc_att ?? null,
      wc0: a.wc0 ?? null,
      pm: a.pm_deg ?? null,
      gm: a.gm_db ?? null,
      passing: a.passing ?? false,
      signBasis: a.sign_basis ?? "",
      reasonText: reasonLine(a),
    };
  });
}

/** 문서의 지금 게인 — 산출 후보 옆에 나란히 놓는 값(없으면 null). */
export function designGain(body, slot) {
  return body?.design_now?.gains?.[slot] ?? null;
}
