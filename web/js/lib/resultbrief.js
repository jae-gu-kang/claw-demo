/** 결과 브리핑 모델 — 저장 결과(메타+본문) → 정해진 양식의 결정적 요약 (06 §4 결과 탭).
 *
 * 양식은 종류와 무관하게 한 벌이다: 머리(무엇을·언제·어떤 기체·계보) → 종합 판정 한 줄
 * → 절 몇 개 → (화면이 붙이는) 원본 JSON 접기. LLM 소견서와 다른 자리다 — 이것은
 * 본문에서 **계산으로** 나오는 요약이라 키 없이, 즉시, 언제나 같은 모양으로 선다.
 *
 * 판정을 재기술하지 않는다: 여기 나오는 판정은 전부 본문이 이미 싣고 있는 판정
 * (트림 flags·엔벨로프 verdict·fq)의 집계다. 본문에 없는 판정선(예: 마진 합격선)으로
 * 새로 판정하지 않는다 — 그건 그 결과를 낸 탭의 몫이다.
 */

import { FQ_BADGE, FQ_RANK, fqMeasureText, fqWorst } from "./fq.js";
import { FLAG_LABEL, landingSummary } from "./replay.js";

// 산출물 종류의 우리말 이름 — 서버가 내는 것은 코드다. 모르는 코드는 **그대로** 낸다
// (임의로 "기타"로 뭉치면 새 종류가 생겼다는 사실이 화면에서 사라진다).
export const KIND_LABEL = {
  trim_batch: "트림 배치",
  margin_map: "마진 맵",
  envelope_scan: "엔벨로프 스캔",
  sim: "시뮬레이션",
  auto_design: "자동 설계",
  quick_seed: "초기 게인 빠른 탐색",
  derive_de_trim: "δe_trim 표 도출",
  verify_flight: "검증 — 탑재 C 신뢰성",
  influence_scan: "영향성 — 전 케이스 스캔",
  influence_sweep: "영향성 — 부분 풀 스윕",
  influence_openloop: "영향성 — 개루프 Δ",
  influence_evaluate: "평가 — 대표 카드·나머지 판정",
  influence_verify: "검증 — 3단계 (강건성·중간점)",
  influence_prescribe: "정량 처방 — 얼마나·조합·확인",
  mission_draft: "미션 초안 (LLM)",
  llm_brief: "소견서 (LLM)",
  llm_comms: "교신 대본 (LLM)",
  llm_ask: "문답 (LLM)",
};
export const kindLabel = (k) => KIND_LABEL[k] ?? k ?? "—";

// 트림 판정 플래그의 우리말 — 트림 탭 표의 열 이름과 같은 어휘.
// (시뮬 엔벨로프 플래그 어휘는 replay.js FLAG_LABEL — 다른 축이라 표도 다르다)
const TRIM_FLAG_LABEL = {
  residual_ok: "잔차", saturation_ok: "포화", alpha_margin_ok: "α여유", continuity_ok: "연속성",
};
// 엔벨로프 스캔 사유 — 엔진 envelope_verdict.reasons의 코드 (design/points.py)
const REASON_LABEL = {
  not_converged: "미수렴", alpha_margin: "α 여유", saturated_throttle_high: "추력 한계(상한)",
  saturated_de: "엘레본 포화", saturated_throttle_low: "추력 하한",
};

const num = (v, d = 3) => (typeof v === "number" && Number.isFinite(v)
  ? String(Math.round(v * 10 ** d) / 10 ** d) : "—");
const uniqSorted = (xs) => [...new Set(xs)].sort((a, b) => a - b);

/** 공통 머리 — 종류·생성·기체·계보. 없는 것은 빼지 않고 "—"로 (없다는 사실도 정보다). */
function headRows(meta) {
  const p = meta.profile;
  return [
    ["종류", `${kindLabel(meta.kind)} (${meta.kind ?? "—"})`],
    ["생성", meta.created ? new Date(meta.created * 1000).toLocaleString() : "—"],
    ["기체", p ? `${p.name ?? p.id}${p.variant ? ` · ${p.variant}` : ""} · 리비전 ${p.revision ?? "—"} · 지문 ${p.fingerprint ?? "—"}` : "—"],
    ["계보 지문", meta.fingerprint || "—"],
    ["건수", meta.n != null ? String(meta.n) : "—"],
  ];
}

function trimBrief(body) {
  const rows = body.results ?? [];
  const flagBad = (r) => Object.entries(r.flags ?? {})
    .filter(([, v]) => v === false).map(([k]) => TRIM_FLAG_LABEL[k] ?? k);
  const nOk = rows.filter((r) => r.converged).length;
  const bad = rows.map((r) => {
    if (!r.converged) return [r.case.name, "미수렴"];
    const f = flagBad(r);
    return f.length ? [r.case.name, `판정 위반: ${f.join("·")}`] : null;
  }).filter(Boolean);
  const nFlagBad = bad.filter(([, v]) => v !== "미수렴").length;
  const allPass = nOk === rows.length && nFlagBad === 0;
  const machs = rows.map((r) => r.case.mach);
  const sections = [{
    title: "격자",
    rows: [
      ["마하", rows.length ? `${num(Math.min(...machs))} ~ ${num(Math.max(...machs))}` : "—"],
      ["고도 [m]", uniqSorted(rows.map((r) => r.case.alt)).join(", ") || "—"],
      ["연료 [kg]", uniqSorted(rows.map((r) => r.case.fuel)).join(", ") || "—"],
    ],
  }];
  if (bad.length) {
    const MAX = 8;
    sections.push({
      title: `위반·미수렴 케이스 (${bad.length}건)`,
      rows: [...bad.slice(0, MAX),
        ...(bad.length > MAX ? [["…", `그 외 ${bad.length - MAX}건 — 트림 탭 표에서 전량`]] : [])],
    });
  }
  return {
    // 0건은 통과가 아니다 — 빈 본문을 초록으로 내면 결측이 합격으로 위장된다(리뷰 지적)
    verdict: rows.length === 0
      ? { tone: "na", text: "케이스 없음 — 판정할 것이 없다" }
      : allPass
        ? { tone: "ok", text: `전 케이스 수렴·판정 통과 (${rows.length}건)` }
        : { tone: "bad", text: `수렴 ${nOk}/${rows.length} · 판정 위반 ${nFlagBad}건` },
    sections,
  };
}

function marginBrief(body) {
  const cases = body.cases ?? [];
  const loops = (body.loops ?? []).map((lp) => lp.name);
  // 루프별 최악 PM·GM — 유한값 중 최소. "inf"(무한 여유)는 최악 후보가 아니고,
  // null(판정 불가)은 따로 센다 — 뭉치면 "교차 없음"이 "여유 넉넉"으로 위장된다
  const loopRows = loops.map((name) => {
    let pm = null, gm = null, naCount = 0;
    for (const c of cases) {
      const m = c.margins?.[name];
      if (!m) {
        // 이 케이스에 이 루프의 마진이 아예 없다 — "판정 불가"에 센다. 건너뛰기만 하면
        // 일부 케이스에서 계산이 실패한 루프가 집계에서 조용히 사라진다(리뷰 지적)
        naCount += 1;
        continue;
      }
      const p = m.pm_deg, g = m.gm_db;
      if (typeof p === "number" && Number.isFinite(p) && (!pm || p < pm.v)) pm = { v: p, at: c.trim.case.name };
      if (typeof g === "number" && Number.isFinite(g) && (!gm || g < gm.v)) gm = { v: g, at: c.trim.case.name };
      if (p == null || g == null) naCount += 1;
    }
    const part = [];
    part.push(pm ? `최악 PM ${num(pm.v, 1)}° (${pm.at})` : "PM —");
    part.push(gm ? `최악 GM ${num(gm.v, 1)} dB (${gm.at})` : "GM — (전부 ∞ 또는 판정 불가)");
    if (naCount) part.push(`판정 불가 ${naCount}건`);
    return [`루프 ${name}`, part.join(" · ")];
  });
  // 비행성 수준 — fqWorst·FQ_RANK 재사용 (마진 맵 탭 요약 줄과 같은 계산·같은 서열표)
  const worst = fqWorst(cases);
  let worstKey = null;
  const fqRows = worst.map(({ label, key, j, caseName, mode }) => {
    if (key !== "na" && (worstKey === null || FQ_RANK[key] > FQ_RANK[worstKey])) worstKey = key;
    const b = FQ_BADGE[key];
    const measure = j ? ` (${fqMeasureText(mode, j)} @ ${caseName})` : "";
    return [label, `${b.label}${measure}`];
  });
  const tone = worstKey == null ? "na" : worstKey === 1 ? "ok" : worstKey === 2 ? "warn" : "bad";
  const composition = [
    ["케이스·루프", `${cases.length}건 · ${loops.length}개`],
    ["작동기", body.actuator ? `wn ${num(body.actuator.wn)} · ζ ${num(body.actuator.zeta)}` : "미포함"],
    ["지연", body.delay_s ? `${num(body.delay_s, 4)} s (Padé ${body.pade_order ?? "—"}차)` : "없음"],
    ["비행성 판정선 지문", body.fq_criteria?.fingerprint ?? "— (판정 이전 결과)"],
  ];
  return {
    verdict: {
      tone,
      text: worstKey == null
        ? "비행성 수준 판정 없음(구버전 결과) — 마진 합격 판정은 마진 맵 탭이 한다"
        : `비행성 수준 최악 ${FQ_BADGE[worstKey].label} — 마진 합격 판정(PM·GM 판정선)은 마진 맵 탭이 한다`,
    },
    sections: [
      { title: "루프별 최악 마진", rows: loopRows.length ? loopRows : [["루프", "없음 — 고유치·감쇠비만 계산한 결과"]] },
      { title: "비행성 수준 (모드별 최악 — 무증강 기체)", rows: fqRows },
      { title: "판정 조성", rows: composition },
    ],
  };
}

function envelopeBrief(body) {
  const cases = body.cases ?? [];
  const nOk = cases.filter((c) => c.verdict?.ok).length;
  const counts = new Map();
  for (const c of cases) {
    if (c.verdict?.ok) continue;
    const r = c.verdict?.reasons?.[0] ?? "unknown";
    counts.set(r, (counts.get(r) ?? 0) + 1);
  }
  return {
    verdict: cases.length === 0
      ? { tone: "na", text: "케이스 없음 — 판정할 것이 없다" } // 0/0을 초록으로 내지 않는다
      : {
          tone: nOk === cases.length ? "ok" : "warn",
          text: `가능 ${nOk}/${cases.length}` + (body.n_requested != null && body.n_requested !== cases.length
            ? ` (요청 ${body.n_requested})` : ""),
        },
    sections: [{
      title: "불가 사유별 집계 (대표 사유 기준)",
      rows: counts.size
        ? [...counts.entries()].sort((a, b) => b[1] - a[1])
            .map(([r, n]) => [REASON_LABEL[r] ?? r, String(n)])
        : [["—", "전 케이스 가능"]],
    }],
  };
}

function simBrief(body) {
  const t = body.t ?? [];
  const meta = body.meta ?? {};
  const env = body.envelope ?? {};
  const nSig = Object.keys(body.signals ?? {}).length;
  const wps = meta.waypoints;
  // 착륙 요약 — 시뮬 탭 재생과 **같은 계산**(lib/replay.js landingSummary). 강하율·속도는
  // 엔진이 전 해상도에서 재어 meta.phases에 실은 값이다 — 여기서 다시 계산하지 않는다
  const landing = landingSummary(body);
  // α리미터 작동률·이탈 표본은 본문 신호·플래그의 단순 집계다 — 새 판정선이 아니다.
  // 표본 수/분모를 함께 낸다: 4만 표본 중 1표본이 "0 %"로 접히면 데이터가 있는데
  // 0으로 보인다("0 위조 금지"의 이웃 — 리뷰 지적). 분모가 있어야 1이 몇 초인지 읽힌다
  const lim = body.signals?.limiter_active;
  const limN = Array.isArray(lim) ? lim.filter(Boolean).length : null;
  const pct = (n, total) => {
    const p = (100 * n) / total;
    return `${p > 0 && p < 0.05 ? "< 0.05" : num(p, 1)} % (${n}/${total} 표본)`;
  };
  const limText = limN != null && lim.length ? pct(limN, lim.length) : "—";
  // 플래그 어휘는 재생 화면과 같은 표(replay.js FLAG_LABEL) — 모르는 키는 그대로
  const flagCounts = Object.entries(env.flags ?? {})
    .map(([name, arr]) => [FLAG_LABEL[name] ?? name,
      Array.isArray(arr) ? arr.filter(Boolean).length : 0, Array.isArray(arr) ? arr.length : 0])
    .filter(([, n]) => n > 0);
  const esc = meta.path_escapes;
  // 판정은 본문 동봉 것만: aborted(중단 사유 코드 — "cancelled"·"alt_out_of_range" 등,
  // 모르는 코드는 그대로 낸다)와 any_flag(엔벨로프 감시 요약)
  const verdict = meta.aborted
    ? { tone: "bad",
        text: `중단된 런 (${typeof meta.aborted === "string" ? meta.aborted : "aborted"}) — 끝까지 돌지 않았다` }
    : env.any_flag
      ? { tone: "warn", text: `엔벨로프 이탈 표본 있음 — 첫 이탈 ${num(env.first_flag_t, 2)} s (지표·엔벨로프 절)` }
      : env.any_flag === false
        ? { tone: "ok", text: "정상 종료 — 엔벨로프 이탈 없음" }
        : { tone: "na", text: "엔벨로프 요약 없음(구버전 결과) — 해석은 시뮬레이션 탭 [재생]" };
  return {
    verdict,
    sections: [{
      title: "런 구성",
      rows: [
        ["시간", t.length ? `${num(t[0], 2)} ~ ${num(t[t.length - 1], 2)} s · 표본 ${t.length}` : "—"],
        ["신호", `${nSig}개`],
        ["시작 트림", meta.case ?? "—"],
        ["웨이포인트", wps ? `${wps.length}점 · 도달 반경 ${num(meta.accept_radius)} m` : "없음 (경로 없는 미션)"],
      ],
    }, {
      title: "착륙 요약 (엔진 전 해상도 실측 — 시뮬 탭 재생과 같은 계산)",
      rows: landing.length
        ? [...landing.map((r) => [r.label, r.note ? `${r.value} — ${r.note}` : r.value]),
           // 같은 계산이지만 입력 해상도가 다르다 — 재생 화면은 솎은 표본이라 끝자리
           // (접지→정지 1 m 단위 등)가 어긋날 수 있고, 이쪽(전 해상도)이 더 정확하다
           ["표기", "전 해상도 저장 본문 기준 — 재생 화면(솎은 표본)과 끝자리가 다를 수 있으며 이쪽이 정본이다"]]
        : [["—", "이탈·접지·정지 단계 기록 없음 — 착륙 없는 미션이거나 판정 이전 결과다 (0으로 위조하지 않는다)"]],
    }, {
      title: "지표·엔벨로프 (본문 동봉 요약의 집계)",
      rows: [
        ["최악 실속마진", env.worst_margin != null
          ? `${num(env.worst_margin, 4)} rad @ ${num(env.worst_margin_t, 2)} s` : "—"],
        ["최저 고도", env.min_alt != null ? `${num(env.min_alt, 1)} m @ ${num(env.min_alt_t, 2)} s` : "—"],
        ["α리미터 작동률", limText],
        ["엔벨로프 이탈 표본", flagCounts.length
          ? flagCounts.map(([name, n, total]) => `${name} ${n}/${total}`).join(" · ")
          : env.any_flag === false ? "없음" : "—"],
        ["궤도 이탈 웨이포인트", Array.isArray(esc)
          ? (esc.length ? `${esc.length}건 (#${esc.map((i) => i + 1).join(", #")})` : "없음") : "—"],
        ["더 보기", "궤적·신호 재생·3면도·타면 사용은 시뮬레이션 탭 [재생]"],
      ],
    }],
  };
}

function llmBriefBrief(body) {
  return {
    title: body.headline || "(제목 없음)",
    verdict: null,
    sections: [
      { title: `소견 — 대상 ${body.parent ?? "—"} (${kindLabel(body.parent_kind)})${body.model ? ` · ${body.model}` : ""}`,
        lines: String(body.body || "").split(/\n{2,}/).filter(Boolean) },
      ...(body.look_at?.length ? [{ title: "어디부터 볼까", lines: body.look_at }] : []),
    ],
  };
}

/** 일반 양식 — 본문 최상위 구성을 사실대로. 새 종류가 생겨도 브리핑이 빈손이 되지 않는다. */
function genericBrief(body) {
  const describe = (v) => {
    if (Array.isArray(v)) return `배열 ${v.length}개`;
    if (v && typeof v === "object") return `객체 (키 ${Object.keys(v).length}개)`;
    if (typeof v === "string") return v.length > 60 ? `"${v.slice(0, 57)}…"` : `"${v}"`;
    return String(v);
  };
  return {
    verdict: null,
    sections: [{
      title: "본문 구성 (이 종류의 전용 요약은 아직 없다 — 원본 JSON이 전량이다)",
      rows: Object.entries(body ?? {}).filter(([k]) => k !== "kind")
        .map(([k, v]) => [k, describe(v)]),
    }],
  };
}

const BRIEFERS = {
  trim_batch: trimBrief,
  margin_map: marginBrief,
  envelope_scan: envelopeBrief,
  sim: simBrief,
  llm_brief: llmBriefBrief,
};

/** 메타+본문 → 브리핑 모델 {title, head, verdict|null, sections}. 종류별 요약이 없으면 일반 양식. */
export function briefModel(meta, body) {
  const part = (BRIEFERS[meta.kind] ?? genericBrief)(body ?? {});
  return {
    title: part.title ?? `${kindLabel(meta.kind)} — ${meta.id}`,
    head: headRows(meta),
    verdict: part.verdict ?? null,
    sections: part.sections ?? [],
  };
}

/** 원본 JSON 미리보기 — 상한을 넘으면 자르고 그 사실을 값으로 돌려준다(조용한 절단 금지).
 *  시뮬 본문은 전 해상도 신호라 수 MB일 수 있다 — 전량은 새 탭(원본 링크)의 몫이다. */
export function jsonPreview(body, cap = 300000) {
  const text = JSON.stringify(body, null, 2) ?? "";
  return text.length > cap
    ? { text: text.slice(0, cap), chars: text.length, truncated: true }
    : { text, chars: text.length, truncated: false };
}
