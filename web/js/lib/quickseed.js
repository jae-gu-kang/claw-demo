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
  if (src === "seed_basis") {
    // 산출 근거 직행 저장(05 §10.1) — 채택 게이트를 안 거친 한 점 후보임을 출처 줄이 그대로 말한다
    return { kind: "seed_basis", seeded: true, ok: true, label: "산출 근거 직행 게인 — 한 점·검증 전, 자동 설계 전" };
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

const VARIANT_SOURCES = new Set(["confirmed", "rule_schedule", "stale", "none"]);

/** 고른 형상 변형에서 확정 표가 어떻게 쓰이나 — "confirmed"|"rule_schedule"|"stale"|"none"|null(모름).
 *  서버 목록 요약의 변형별 출처(gain_tables.variants[id].source — 조립과 같은 자)가 있으면 그것이 정본이다.
 *  없으면(그 칸이 없는 서버) 이미 아는 두 사실로만 가린다: 낡은 변형 목록(stale_variants — 서버 판정)과
 *  그 변형을 적용한 문서의 표 자리(effectiveTables — 변형 패치가 /law/gain_tables를 비우면 null,
 *  호출자가 모르면 undefined). 둘로도 못 가리면 null — 기본형 문구를 변형에 그대로 물려주지 않는다. */
export function variantTableSource(gt, variant, effectiveTables) {
  const s = gt?.variants?.[variant]?.source;
  if (VARIANT_SOURCES.has(s)) return s;
  if (gt == null) return effectiveTables == null ? "none" : null;
  if ((gt.stale_variants ?? []).includes(variant)) return "stale";
  if (effectiveTables === null) return "rule_schedule";
  return effectiveTables ? "confirmed" : null;
}

/** 확정 게인 표(v2) 상태 한 줄 — 목록 요약(gain_tables: {source, stale, stale_variants, variants?}|null)에서.
 *  낡음 판정은 서버(조립 거부와 같은 자)가 동봉한다 — 여기는 문구뿐이다.
 *  `variant`(고른 형상 변형 id)가 오면 **그 형상**의 상태를 말한다 — 확정 표는 기본형 설계 결과라, 변형 패치가
 *  표를 비운 형상(예: 쇼케이스 EO/IR형)은 규칙 스케줄로 난다. 기본형 행의 「이 표를 씁니다」를 그 변형에
 *  달면 사실과 반대다. `effectiveTables`는 variantTableSource 참고. */
export function gainTablesStatus(summary, { variant = null, effectiveTables } = {}) {
  const gt = summary?.gain_tables;
  // 조사는 괄호 앞 낱말(변형)에 붙는다 — 변형 이름의 받침과 무관하게 「은」
  const who = `고른 형상 변형(「${summary?.variants?.find?.((v) => v?.id === variant)?.name ?? variant}」)`;
  if (variant) {
    const src = variantTableSource(gt, variant, effectiveTables);
    const origin = `기본형 설계 결과(출처 ${gt?.source ?? "기록 없음"})`;
    if (src === "rule_schedule") {
      return { kind: "rule", stale: false, variant, staleVariants: gt?.stale_variants ?? [],
        label: `${who}은 규칙 스케줄(설계 게인 × q̄ 역비)로 납니다 — 확정 게인 표는 ${origin}이고 `
          + "이 변형은 그 표를 쓰지 않습니다" };
    }
    if (src === "stale") {
      return { kind: "stale", stale: true, variant, staleVariants: gt?.stale_variants ?? [variant],
        label: `확정 게인 표가 ${who}에서는 낡았습니다 — 표를 확정한 뒤 이 변형이 문서를 바꿔 법칙 조립이 `
          + "거부합니다. 그 변형으로 계산하려면 표를 지우거나 변형 없이 설계합니다" };
    }
    if (src === "none") {
      return { kind: "none", stale: false, variant,
        label: `${who}에는 확정 게인 표가 없습니다 — 조립은 규칙 스케줄` };
    }
    if (src === "confirmed") {
      return { kind: "ok", stale: false, variant, staleVariants: gt?.stale_variants ?? [],
        label: `확정 게인 표 (${origin}) — ${who}도 조립이 규칙 스케줄 대신 이 표를 씁니다` };
    }
    // 모름 — 아래 기본형 문구에 「변형은 모른다」를 단다
  }
  if (!gt) {
    return { kind: "none", stale: false,
      label: "확정 게인 표 없음 — 자동 설계 결과를 [문서에 반영]하면 여기 선다(조립은 규칙 스케줄)" };
  }
  if (gt.stale) {
    return { kind: "stale", stale: true, staleVariants: gt.stale_variants ?? [],
      label: "확정 게인 표가 낡았습니다 — 반영한 뒤 문서가 바뀌어 법칙 조립이 거부합니다. "
        + "자동 설계를 다시 돌려 반영하거나 표를 지웁니다(없음으로)" };
  }
  const sv = gt.stale_variants ?? [];
  return { kind: "ok", stale: false, staleVariants: sv,
    label: `확정 게인 표 (출처 ${gt.source ?? "기록 없음"}) — 조립이 규칙 스케줄 대신 이 표를 씁니다`
      + (sv.length ? `. 단 문서를 바꾸는 형상 변형(${sv.join(", ")})에서는 낡음이라 조립이 거부합니다`
        + " — 그 변형으로 계산하려면 표를 지우거나 변형 없이 설계합니다" : "")
      + (variant ? ` (기본형 기준 — ${who}의 조립이 이 표를 쓰는지는 목록 요약에 없습니다)` : "") };
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
        label: `도출한 δe_trim 표가 덮지 않는 형상 변형이 있습니다(${variants.join(", ")}) — 도출 뒤에 플랜트를 바꾼 `
          + "변형이라 그 변형으로는 법칙 조립이 거부합니다. 다시 도출합니다" };
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
      coverage: prov.coverage ?? null,
    } : null,
  };
}

const machSpanText = (v) => {
  const ms = (v ?? []).filter((m) => Number.isFinite(m));
  return ms.length ? `${Math.min(...ms)}–${Math.max(...ms)}` : null;
};

/** δe_trim 표 커버리지(엔진 de_trim_coverage — 05 §11.13 이관 10단계) → 줄 [{tone, text}].
 *  표의 축이 요구 마하를 덮는 것과 그 구간의 도출 근거가 있는 것은 다르다 — 끝값(clip)으로 답하는 구간, 유효 트림이
 *  없어(트림 실패·모델 부족·제한 위반) 근거가 없는 구간, 보간으로 채운 마하를 각각 따로 적고, 셋 다 없고 표가 낡지
 *  않았을(stale 아님) 때만 「덮는다」고 말한다.
 *  coverage가 없으면 reason(서버가 말한 까닭)만, 그것도 없으면 []. */
export function deTrimCoverageLines(coverage, reason = null) {
  // 엔진이 null이면 「모른다」다(비교할 요구·기록 없음) — 빈 목록 [](「없다」)과 가른다
  if (!coverage) return reason ? [{ tone: "hint", text: reason }] : [];
  const req = machSpanText(coverage.required_mach);
  const tab = machSpanText(coverage.table_mach);
  const out = [{ tone: "hint", text: req
    ? `요구 마하 ${req} · 표 마하 ${tab ?? "—"}`
    : `요구영역 미정의 — 표(마하 ${tab ?? "—"})가 덮어야 할 요구 마하를 모릅니다` }];
  const seg = ([lo, hi]) => (lo === hi ? `M${lo}` : `M${lo}–${hi}`);
  for (const s of coverage.beyond_table ?? []) out.push({ tone: "warn", text: `${seg(s)} 표 범위 밖 · 끝값 사용 · 성능 미확인` });
  // 엔진 need None = 날 수 있는 트림이 없음 — 트림 실패·모델 부족뿐 아니라 제한 위반·요구영역 밖 제외도 여기다
  for (const s of coverage.unsupported ?? []) {
    out.push({ tone: "warn", text: `${seg(s)} 도출 근거 없음(유효 트림 없음 — 트림 실패·모델 부족·제한 위반)` });
  }
  const und = coverage.undefined_machs ?? [];
  if (und.length) out.push({ tone: "warn", text: `M${und.join(", ")} 보간으로 채움` });
  // 근거를 잰 기록이 없다(손으로 넣은 표 · 도출 뒤 요구영역이 바뀜) — 모르는 것을 「근거 있음」으로 말하지 않는다
  if (req && coverage.unsupported == null) {
    out.push({ tone: "warn", text: coverage.basis === "document"
      ? "도출 근거 미확인 — 손으로 넣은 표라 요구 마하마다 트림 근거를 잰 기록이 없습니다(도출하면 잽니다)"
      : "도출 근거 미확인 — 도출한 뒤 요구영역이 바뀌어 지금 요구에서 잰 기록이 없습니다(다시 도출하면 잽니다)" });
  }
  // 낡은 표(도출 뒤 플랜트가 바뀜) — 위 커버리지는 옛 도출의 것이다. 초록 「덮음」을 말하지 않는다
  if (coverage.stale) {
    out.push({ tone: "warn", text: "이 커버리지는 낡은 도출의 것입니다 — 도출 뒤 기체가 바뀌어 지금 기체에서 잰 근거가 아닙니다(다시 도출하면 잽니다)" });
  }
  if (req && out.length === 1) out.push({ tone: "ok", text: "요구 마하를 표가 덮고 도출 근거가 있습니다" });
  return out;
}
