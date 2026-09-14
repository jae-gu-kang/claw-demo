/** 초기 게인 빠른 탐색 결과 → 화면 요약 (05 §10 · 06 §8).

수치·사유 문구·자리 목록은 엔진(`claw.design.seed`)과 서버 잡이 준다 — 여기는 줄 세우기와 머리말뿐이다.
*/

// 튜너가 잡는 7자리 — 닫는 순서(레이트: 피치·요·롤) 뒤 자세. 엔진 결과에 없는 자리는 줄에서 뺀다
const SLOT_ORDER = ["pitch.k_rate", "yaw.k_rate", "roll.k_rate", "pitch.kp", "pitch.ki", "roll.kp", "roll.ki"];

/** 문서의 게인 출처 한 줄 — law.design이 없으면 미설계, 빠른 탐색이면 「자동 설계 전」을 분명히 적는다. */
export function designSource(doc) {
  const d = doc?.law?.design;
  if (d == null) return { kind: "none", seeded: false, label: "게인 미설계 — 초기 게인 빠른 탐색이 필요합니다" };
  const src = d.provenance?.source ?? null;
  if (src === "quick_seed") {
    return { kind: "quick_seed", seeded: true, ok: d.provenance?.ok !== false, label: "초기 탐색 게인 — 자동 설계 전" };
  }
  return { kind: src ?? "unknown", seeded: false, label: src ? `게인 출처: ${src}` : "게인 출처 기록 없음" };
}

// 기체를 고치는 잡(탐색·도출)의 머리말 — 채택 여부와 저장 여부는 서버 결과 본문이 말한다
function jobHeadline(out, body) {
  if (!out.ok) return `채택하지 않았습니다 — ${out.reason_text ?? out.reason}`;
  if (body.written) return `채택 — 리비전 ${body.profile?.revision}로 저장했습니다`;
  if (body.write_error) return `채택할 수 있었지만 저장하지 못했습니다 — ${body.write_error}`;
  if (body.conflict_head != null) {
    return `채택할 수 있었지만 저장하지 않았습니다 — 도는 사이 리비전 ${body.conflict_head}가 저장됐습니다. `
      + "그 리비전에서 다시 돌리세요";
  }
  return "채택할 수 있었지만 저장하지 않았습니다";
}

/** 결과 본문({seed, written, profile, conflict_head}) → {ok, headline, rows, anchors, warnings, notes, …}. */
export function seedSummary(body) {
  const s = body?.seed;
  if (!s) {
    return { ok: false, headline: "결과 본문에 탐색 결과가 없습니다", rows: [], anchors: [], warnings: [], notes: [],
      autopilotSources: {}, scheduleCreated: false };
  }
  const headline = jobHeadline(s, body);
  const rows = SLOT_ORDER.filter((n) => s.slots?.[n]).map((n) => {
    const r = s.slots[n];
    return { name: n, value: r.value, basis: r.sign_basis ?? "", used: r.anchors_used ?? 0,
      reason: r.reason ?? null, reasonText: r.reason_text ?? null };
  });
  const autopilotSources = {};
  for (const v of Object.values(s.design?.provenance?.autopilot ?? {})) {
    autopilotSources[v] = (autopilotSources[v] ?? 0) + 1;
  }
  return {
    ok: !!s.ok, headline, rows,
    anchors: (s.anchors ?? []).map((a) => `${a.name} (q̄ ${Math.round(a.qbar)} Pa)`),
    warnings: s.warnings ?? [], notes: s.autopilot_notes ?? [], autopilotSources,
    scheduleCreated: !!s.schedule_created, elapsed: s.elapsed_s ?? null,
  };
}

/** 할당 δe_trim 표 상태 — 표의 출처는 문서가, 낡음은 서버 목록 요약(de_trim.stale — 플랜트 지문 대조)이 안다. */
export function deTrimStatus(doc, summary) {
  const t = doc?.law?.alloc?.de_trim ?? null;
  if (t == null) {
    return { kind: "none", stale: false, label: "δe_trim 표 없음 — 선회 할당(롤 예산의 피치 몫)이 조립되지 않는다" };
  }
  if (t.source === "derived") {
    const variants = summary?.de_trim?.stale_variants ?? [];
    if (summary?.de_trim?.stale === true) {
      return { kind: "stale", stale: true, staleVariants: variants,
        label: "도출한 δe_trim 표가 낡았습니다 — 도출한 뒤 플랜트가 바뀌어 법칙 조립이 거부합니다. 다시 도출합니다" };
    }
    if (variants.length) {
      return { kind: "stale", stale: true, staleVariants: variants,
        label: `도출한 δe_trim 표가 형상 변형 ${variants.join(", ")}을 덮지 않습니다 — 도출 뒤에 플랜트를 바꾼 변형이라 `
          + "그 변형으로는 법칙 조립이 거부합니다. 다시 도출합니다" };
    }
    return { kind: "derived", stale: false, staleVariants: [], label: "도출한 δe_trim 표" };
  }
  return { kind: "explicit", stale: false, label: "손으로 넣은 δe_trim 표 — 도출하면 새 리비전으로 바꿉니다" };
}

/** 도출 결과 본문({derive, written, profile, conflict_head}) → {ok, headline, rows[{mach, value}], stats}. */
export function deriveSummary(body) {
  const d = body?.derive;
  if (!d) return { ok: false, headline: "결과 본문에 도출 결과가 없습니다", rows: [], stats: null };
  const t = d.alloc?.de_trim?.table;
  const prov = d.alloc?.de_trim?.provenance ?? {};
  return {
    ok: !!d.ok, headline: jobHeadline(d, body),
    rows: t ? t.axes.mach.map((m, i) => ({ mach: m, value: t.data[i] })) : [],
    stats: t ? {
      checks: d.requirement?.mach?.length ?? 0, shortfall: prov.shortfall ?? null, excessMax: prov.excess_max ?? null,
      iterations: prov.iterations ?? null, excluded: prov.excluded_trims ?? null, undefined: prov.undefined_machs ?? [],
    } : null,
  };
}
