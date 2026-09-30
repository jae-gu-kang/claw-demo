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

import {
  actionCards, actuatorLine, adoptBlockedText, applyGateReason, coverageLines, designReuseLine, excludedSamplesModel,
  failureRoleText, fitFactsModel, fitModeLabel, knotModel, pointCountText, pointRows, reinforcementLines, resumable,
  resumeBlockedText, reverifyLines, statusCounts, statusSeverity, statusText, summaryGridModel, validationSummaryText,
} from "./autodesign.js";
import { FQ_BADGE, FQ_RANK, fqMeasureText, fqWorst } from "./fq.js";
import { lineageText } from "./lineage.js";
import { OBJECTIVE_LABEL } from "./prescribe.js";
import { marginUnstable, unstableCells, unstableTail } from "./loops.js";
import { FLAG_LABEL, landingSummary, siteRunwayWidth } from "./replay.js";
import { covCell, identLine, mcdcCell, statusFlag, verdictModel } from "./verify.js";

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

/** 종류 옆 세부 — 처방 결과의 목적(04 §7.3). 같은 종류라도 목적이 다르면 다른 답이다. 없으면 null. */
export function kindDetail(meta) {
  if (meta?.kind !== "influence_prescribe" || !meta.objective) return null;
  return OBJECTIVE_LABEL[meta.objective] ?? meta.objective;
}

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
    ["종류", `${kindLabel(meta.kind)}${kindDetail(meta) ? ` · ${kindDetail(meta)}` : ""} (${meta.kind ?? "—"})`],
    ["생성", meta.created ? new Date(meta.created * 1000).toLocaleString() : "—"],
    ["기체", p ? `${p.name ?? p.id}${p.variant ? ` · ${p.variant}` : ""} · 리비전 ${p.revision ?? "—"} · 지문 ${p.fingerprint ?? "—"}` : "—"],
    // 결과 목록의 계보 칸과 같은 표기 — 탑재 C 검증은 엔진 발급 두 지문(구조·값)이다(lib/lineage.js)
    ["계보 지문", lineageText(meta)],
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
  // 루프별 최악 PM·GM — 안정 칸의 유한값 중 최소(발산 칸은 따로 센다). "inf"(무한 여유)는 최악 후보가 아니고,
  // null(판정 불가)은 따로 센다 — 뭉치면 "교차 없음"이 "여유 넉넉"으로 위장된다
  const loopRows = loops.map((name) => {
    let pm = null, gm = null, naCount = 0, divCount = 0;
    for (const c of cases) {
      const m = c.margins?.[name];
      if (!m) {
        // 이 케이스에 이 루프의 마진이 아예 없다 — "판정 불가"에 센다. 건너뛰기만 하면
        // 일부 케이스에서 계산이 실패한 루프가 집계에서 조용히 사라진다(리뷰 지적)
        naCount += 1;
        continue;
      }
      // 이 루프를 닫은 폐루프가 발산하는 칸(엔진 closed_loop.stable === false) — 그 칸의 PM·GM은 안정 여유가 아니라
      // 루프 교차의 고전 판독이다. 최악 최소에 섞으면 「최악 PM 82°」 같은 거짓 안심이 되므로 빼고 「발산 N칸」으로 따로
      // 센다(마진 맵 탭 캡션·진행기 보고와 같은 판정 — lib/loops.js marginUnstable)
      if (marginUnstable(m)) {
        divCount += 1;
        continue;
      }
      const p = m.pm_deg, g = m.gm_db;
      if (typeof p === "number" && Number.isFinite(p) && (!pm || p < pm.v)) pm = { v: p, at: c.trim.case.name };
      if (typeof g === "number" && Number.isFinite(g) && (!gm || g < gm.v)) gm = { v: g, at: c.trim.case.name };
      if (p == null || g == null) naCount += 1;
    }
    const part = [];
    if (divCount) part.push(`발산 ${divCount}칸`); // 발산이 먼저 — 여유 수치보다 무겁다
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
  const fqTone = worstKey == null ? "na" : worstKey === 1 ? "ok" : worstKey === 2 ? "warn" : "bad";
  // 폐루프 발산 칸 — 본문이 싣고 있는 판정(closed_loop.stable)의 집계라 새 판정선이 아니다. 하나라도 있으면
  // 종합은 부족(bad)이고 한 줄의 첫머리에 온다(비행성 수준이 1이어도 발산은 결함이다)
  const bad = unstableCells(cases, body.loops ?? []);
  const tone = bad.length ? "bad" : fqTone;
  const composition = [
    ["케이스·루프", `${cases.length}건 · ${loops.length}개`],
    ["작동기", body.actuator ? `wn ${num(body.actuator.wn)} · ζ ${num(body.actuator.zeta)}` : "미포함"],
    ["지연", body.delay_s ? `${num(body.delay_s, 4)} s (Padé ${body.pade_order ?? "—"}차)` : "없음"],
    ["비행성 판정선 지문", body.fq_criteria?.fingerprint ?? "— (판정 이전 결과)"],
  ];
  return {
    verdict: {
      tone,
      text: (bad.length ? `${unstableTail(bad)} · ` : "") + (worstKey == null
        ? "비행성 수준 판정 없음(구버전 결과) — 마진 합격 판정은 마진 맵 탭이 한다"
        : `비행성 수준 최악 ${FQ_BADGE[worstKey].label} — 마진 합격 판정(PM·GM 판정선)은 마진 맵 탭이 한다`),
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

function simBrief(body, _meta, { launchLimit } = {}) {
  const t = body.t ?? [];
  const meta = body.meta ?? {};
  const env = body.envelope ?? {};
  const nSig = Object.keys(body.signals ?? {}).length;
  const wps = meta.waypoints;
  // 착륙 요약 — 시뮬 탭 재생과 **같은 계산**(lib/replay.js landingSummary). 강하율·속도는
  // 엔진이 전 해상도에서 재어 meta.phases에 실은 값이다 — 여기서 다시 계산하지 않는다.
  // 판정 재료도 시뮬 탭과 같다: 활주로 폭은 같은 한 자리(siteRunwayWidth — 그 런이 고흥 활주로를 썼을
  // 때만), 발사하중 한계는 그 런의 기체 문서(views/sim.js launchLimitOf — 조회라 이 순수 모델이 못 하고
  // 조립(views/results.js)이 받아 넘긴다). 안 넘기면 두 행이 「대조하지 않았다, 판정 불가」로 선다 —
  // 종전에는 둘 다 안 넘겨, 시뮬 탭이 「폭 안」이라 한 같은 런을 브리핑은 판정 불가라 말했다
  const landing = landingSummary(body, { runwayWidth: siteRunwayWidth(meta.runway), launchLimit });
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
      { title: `소견 — 대상 ${body.parent ?? "—"} (${kindLabel(body.parent_kind)})`,
        lines: String(body.body || "").split(/\n{2,}/).filter(Boolean) },
      ...(body.look_at?.length ? [{ title: "어디부터 볼까", lines: body.look_at }] : []),
    ],
  };
}

/** 절점 모델 → 브리핑 한 칸 — 요약(표 수·절점 수 범위·공통/분리 집합·범위 밖)에 표별 수를 붙인다. 표가 많으면 앞 넷. */
function knotBriefText(m) {
  const per = m.rows.map((r) => `${r.slot} ${r.n ?? "?"}${r.common == null ? "" : `(${r.sharedText})`}`);
  const head = per.slice(0, 4).join(" · ") + (per.length > 4 ? ` 외 ${per.length - 4}` : "");
  return `${m.summary.replace(/^절점 — /, "")}${per.length ? ` — ${head}` : ""}`;
}

/** 검증점 한 칸 — 계획 요약 · 요약 격자 칸 수 · 보강 상태(탭과 같은 함수). 옛 결과는 기록 없음. */
function validationBriefText(r) {
  const plan = validationSummaryText(r);
  if (!plan) return "기록 없음 — 검증점 계획 이전 결과(구간 중점만)";
  const grid = summaryGridModel(r);
  const rf = reinforcementLines(r)[0];
  return [plan, grid ? grid.summary.replace(/^요약 격자 — /, "격자 ") : null, rf ? rf.text : null]
    .filter(Boolean).join(" — ");
}

/** 자동 설계 — 종료 상태·판정 규모·처방·커버리지·게인 반출. 문구·판정은 자동 설계 탭과 **같은
 *  함수**(lib/autodesign.js)에서 온다 — 두 화면이 같은 결과를 다르게 말하지 않게. 운영점 표·원장·
 *  처방 카드 전문은 자동 설계 탭 보고서(openIn)가 연다. */
function autoDesignBrief(body, meta) {
  const r = body.report ?? {};
  const status = r.status ?? null;
  const tone = { ok: "ok", warn: "warn", fail: "bad", na: "na" }[statusSeverity(status)] ?? "na";
  const judged = Number(r.judged) || 0;
  const failures = Number(r.failures) || 0;
  const c = statusCounts(pointRows(body));
  const cards = actionCards(body);
  const pts = r.points ?? {};
  const pointText = ["ok", "warn", "fail"].map((k) => `${k} ${c[k]}`)
    .concat(c.na ? [`na ${c.na}`] : [], c.unjudged ? [`미판정 ${c.unjudged}`] : [],
      // 조건 판정이 채택하지 않은 수렴 점(자동 설계 탭 「채택 제외」와 같은 말 — 여유 미달은 v1.65부터 채택이라 아니다)
      c.outside ? [`채택 제외 ${c.outside}(판정 제외)`] : []).join(" · ");
  const ge = body.gain_export ?? null;
  const nSched = Object.keys(ge?.tables ?? {}).length;
  const nConst = Object.keys(ge?.constants ?? {}).length;
  const gaps = coverageLines(r);
  // 탭 상태 줄·진행기 보고와 같은 함수 — 실패가 앵커(튜닝 성립)인지 점 사이(스케줄 성립)인지,
  // 검증받은 것이 반출 표 그 자체(표)인지 재양자화 근사(다항)인지
  const where = failureRoleText(r.failures_by_role);
  const act = actuatorLine(body);
  const excluded = excludedSamplesModel(body);
  const knots = knotModel(body);
  const fitFacts = fitFactsModel(body.fits, knots);
  const sections = [
    { title: "상태", lines: [statusText(status)] },
    { title: "실행 요약", rows: [
      ["스테이지 · 이터레이션", `${r.stage ?? "—"} · ${Number(r.iterations) || 0}`],
      // 표현 기록이 없는 결과는 표현 선택이 생기기 전 것이다 — 그때는 다항뿐이었다(지어내지 않고 그 사실을)
      ["표현", fitModeLabel(r.fit_mode) ?? "기록 없음 — 표현 선택 이전 결과(다항)"],
      ["점", `${r.n_points ?? "—"} (${pointCountText(pts, "—")})`],
      // 표별 절점(이관 3단계 — 설계점과 따로 정한다). 절점 분리 이전 결과는 기록이 없다고 말한다
      ["절점", knots ? knotBriefText(knots) : "기록 없음 — 절점 분리 이전 결과(튜닝한 마하가 곧 절점)"],
      // 검증점 계획·요약 격자·보강(05 §11.6~11.8 — 이관 4단계). 계획 이전 결과(구간 중점 규칙)는 기록이 없다고 말한다
      ["검증점", validationBriefText(r)],
      ["판정 · 실패", `${judged} · ${failures}` + (where ? ` — 실패 위치 ${where}` : "")],
      ["작동기", act?.value ?? "기록 없음"],
      ["운영점 판정", pointText],
      ["처방 카드", cards.approvable.length
        ? `${cards.approvable.length}건 — ${resumable(r) ? "승인 후 재개 가능(자동 설계 탭)" : resumeBlockedText(r)}`
        : "없음"],
      ["에스컬레이션", cards.escalations.length ? `${cards.escalations.length}건 — 상위 설계 변경 검토(자동 적용 없음)` : "없음"],
      ["미달 원장", r.ledger_size != null ? `${r.ledger_size}행` : "—"],
      ["재개 이력", meta?.parent ? `재개한 실행 — 부모 ${meta.parent}` : "처음 실행(재개 아님)"],
      // 트림 저장소 재사용(05 §11.10) — 자동 설계 탭 상태 줄과 같은 함수. 블록이 없는 옛 결과는 기록 없음이다
      ["트림 재사용", designReuseLine(body)?.text ?? "기록 없음 — 트림 저장소 재사용 이전 결과"],
      ["기준 지문", r.criteria_fingerprint ? String(r.criteria_fingerprint).slice(0, 8) : "—"],
    ] },
  ];
  if (gaps.length) {
    sections.push({ title: "검증 커버리지 — 이 실행이 안 본 것", lines: gaps.map((l) => l.text) });
  }
  // 스케줄 표에 무엇이 들어갔나 — 튜닝 실패로 뺀 표본(자리별 사유)·제외 보류·마하 1축이 뭉갠 변동
  if (excluded || fitFacts?.summary) {
    sections.push({ title: "게인 스케줄 적합", rows: [
      ...(excluded
        ? [["적합 표본 제외", excluded.excludedText ?? "없음"],
           ...excluded.slots.map((s) => [`제외 · ${s.slot}`, s.text]),
           ...excluded.withheld.map((h) => ["제외 보류", h.text])]
        : [["적합 표본 제외", "없음"]]),
      ...(fitFacts?.summary ? [["적합 보고", fitFacts.summary.replace(/^적합 보고 — /, "")]] : []),
    ] });
  }
  if (ge) {
    sections.push({ title: "게인 반출", rows: [
      ["스케줄 · 상수 자리", `${nSched} · ${nConst}`],
      ["확정(스토어 주입)", adoptBlockedText(r) ?? "가능 — 자동 설계 탭 [게인 확정]"],
      ["문서 반영", applyGateReason(body.profile)
        ?? "대상 있음 — 자동 설계 탭 [문서에 반영]. 반영 여부는 기체 탭 「게인·δe_trim」·설계 흐름이 말한다"],
      ...reverifyLines(ge).map((l) => ["채택 표 재검증", l.text]),
    ] });
  }
  return {
    verdict: { tone, text: `${status ?? "?"} — 판정 ${judged} · 실패 ${failures}`
      + (where ? ` (${where})` : "")
      + (cards.escalations.length ? ` · 에스컬레이션 ${cards.escalations.length}` : "") },
    sections,
    openIn: { href: "#autodesign", key: "designOpen",
      label: "자동 설계 탭에서 보고서 열기 (운영점 표·미달 원장·처방 카드·게인 확정)" },
  };
}

/** 탑재 C 검증 — 판정판 요약(검사군·커버리지·구성). 판정 문구는 엔진 요약 행 그대로이고 머리줄은
 *  검증 탭과 같은 함수(lib/verify.js verdictModel)다. 저장 본문이 소스까지 동봉한 자립 리포트라
 *  검증 탭이 그대로 다시 그린다(openIn → 판정판·유닛 그리드·커버리지 소스·인쇄 보고서). */
function verifyBrief(body) {
  const rep = body.report ?? null;
  // verdictModel은 fail·pass_with_skips가 아니면 「통과」로 읽는다 — 판정 필드가 없는 본문을
  // 통과로 위장하지 않게 엔진 판정어 셋 중 하나일 때만 그 모델을 쓴다
  if (!["pass", "pass_with_skips", "fail"].includes(rep?.verdict)) {
    return { verdict: { tone: "na", text: "판정 없음 — 저장 본문에 검증 판정(report.verdict)이 없다" },
      sections: [] };
  }
  const v = verdictModel(rep);
  const t = rep.coverage?.totals;
  const mc = rep.mcdc;
  const files = rep.files ?? [];
  const cases = rep.cases ?? [];
  const covRows = rep.coverage?.status === "measured" && t
    ? [
        ["라인", covCell(t.lines)],
        ["분기", `${covCell(t.branches)}${rep.coverage.justified?.length ? ` (+정당화 ${rep.coverage.justified.length})` : ""}`],
        ["MC/DC 조건", mcdcCell(mc?.status === "measured"
          ? { total: mc.total, covered: mc.covered, justified: mc.justified } : null)],
      ]
    : [["측정", `생략 — ${rep.coverage?.reason ?? "사유 없음"}`]];
  return {
    verdict: { tone: v.cls === "ok" ? "ok" : v.cls === "bad" ? "bad" : "na", text: `${v.label} — ${v.line}` },
    sections: [
      { title: "검사군 (엔진 요약 행)", rows: (rep.summary ?? []).map((r) => [
        (r.label ?? r.key ?? "?").split(" — ")[0],
        `${statusFlag(r.status).label}${r.detail ? ` — ${r.detail}` : ""}`]) },
      { title: "구성", rows: [
        ["산출물 · 지문", `${rep.artifact ?? "—"} · ${identLine(rep)}`],
        ["대조 미션", `${rep.t_end ?? "—"} s${rep.steps ? ` · 통합 대조 ${rep.steps.toLocaleString()}스텝` : ""}`],
        ["생성 파일", `${files.length}개 · ${files.reduce((n, f) => n + (f.lines ?? 0), 0).toLocaleString()}줄`],
        ["시험 케이스", cases.length
          ? `${cases.length}건 — 통과 ${cases.filter((c) => c.status === "pass").length}`
            + ` · 생략 ${cases.filter((c) => c.status === "skip").length}`
            + ` · 불일치 ${cases.filter((c) => c.status === "fail").length}`
          : "—"],
      ] },
      { title: "구조적 커버리지", rows: covRows },
    ],
    openIn: { href: "#verify", key: "verifyOpen",
      label: "검증 탭에서 전체 보고서 열기 (판정판·유닛 그리드·커버리지 소스·인쇄)" },
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
  auto_design: autoDesignBrief,
  verify_flight: verifyBrief,
  llm_brief: llmBriefBrief,
};

/** 메타+본문 → 브리핑 모델 {title, head, verdict|null, sections, openIn|null}. 종류별 요약이 없으면
 *  일반 양식. openIn {href, key, label} — 그 결과를 **낸 탭**이 전체 화면으로 다시 여는 인계(store
 *  key에 {resultId}를 두고 href로 간다 — 받는 탭이 한 번 읽고 지운다). 없으면 null.
 *  opts — 이 모델이 스스로 못 받는(조회가 필요한) 판정 재료. 지금은 시뮬의 `launchLimit`(그 런의 기체 문서
 *  발사하중 한계 — views/sim.js launchLimitOf) 하나다. */
export function briefModel(meta, body, opts = {}) {
  const part = (BRIEFERS[meta.kind] ?? genericBrief)(body ?? {}, meta, opts ?? {});
  return {
    title: part.title ?? `${kindLabel(meta.kind)} — ${meta.id}`,
    head: headRows(meta),
    verdict: part.verdict ?? null,
    sections: part.sections ?? [],
    openIn: part.openIn ?? null,
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
