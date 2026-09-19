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

/** 레이트 자리 줄 — body.order 순서. 판정 불리언은 엔진 것 그대로다. */
export function basisRates(body) {
  return (body?.order ?? []).map((name) => {
    const r = body.rates?.[name] ?? {};
    return {
      name,
      slot: r.slot ?? name,
      model: modelText(r.model),
      k: r.candidate ? r.candidate.k : null,
      note: r.candidate?.note ?? null,
      metric: r.target?.metric ?? null,
      target: r.target?.value ?? null,
      achieved: r.full?.achieved ?? null,
      achievedOk: r.full?.ok ?? null,
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
