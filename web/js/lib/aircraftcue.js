/** 기체 탭 쇼케이스 신호의 판단 (06 §8 · 신호 규약 lib/showcasecue.js) — DOM 없음.

진행기가 건 신호(overview·aero·stability·seed-basis·edit-eoir-drag·derive-de-trim)를 기체 탭(views/aircraft.js)이
**자기 버튼과 같은 길**로 처리한다 — 문서 열기·[그리기]·[산출]·폼 쓰기 + [저장]·[δe_trim 표 도출]. 여기는 그 사이의
판단만 있다: 문서에서 기본 조건을 읽고, 공학 수정의 치환 경로를 정하고, 보고 한 줄을 **탭 산출물에서** 만든다.

기체 의존 값(마하·범위·계수)은 코드 상수로 두지 않는다(기체 고정 금지) — 문서에 없으면 지어내지 않고 사유와 함께
멈추거나 빈 칸으로 둔다. 수치·판정은 서버 응답이 정본이고 여기는 줄 세우기다.
*/

import { withJosa } from "./josa.js";
import { applyPatch } from "./profileform.js";
import { achievedText, basisAttitude, basisHead, basisRates } from "./seedbasis.js";
import { deriveSummary } from "./quickseed.js";

const finite = (v) => typeof v === "number" && Number.isFinite(v);
// 부동소수 꼬리를 싣지 않는다 — 0.028 + 0.007은 0.035000000000000003이다(문서·화면에 그대로 박힌다)
const tidy = (v) => Number(v.toPrecision(12));
const r3 = (v) => Number(v.toFixed(3));
const f3 = (v) => (finite(v) ? v.toFixed(3) : "—");
// 경고 문구의 첫 마디 — 서버 문구는 「사실 — 풀이」 꼴이라 한 줄 요약에는 사실만 싣는다
const firstClause = (s) => String(s ?? "").split(" — ")[0];

/** 공력 패널 뷰어의 문서 기본 조건 — 고정 마하(설계 마하, 없으면 M_NO)와 α 구간(DB 유효 범위).
 *  돌려주는 것: {mach: 수|null, machSource, alpha: [lo, hi]|null}. 없으면 null — 칸을 비워 입력을 받는다. */
export function viewerDefaults(doc) {
  const md = doc?.law?.schedule?.m_design;
  const mno = doc?.structural?.mach_no;
  let mach = null;
  let machSource = null;
  if (finite(md) && md > 0) [mach, machSource] = [md, "law.schedule.m_design"];
  else if (finite(mno) && mno > 0) [mach, machSource] = [mno, "structural.mach_no"];
  const a = doc?.aero?.db_ranges?.alpha;
  const alpha = Array.isArray(a) && a.length === 2 && finite(a[0]) && finite(a[1]) && a[0] < a[1] ? [a[0], a[1]] : null;
  return { mach, machSource, alpha };
}

/** 겹치기 마하 기본값 — 문서의 운용 범위에서 고르게 n개(양 끝 포함, 소수 셋째 자리).
 *
 *  범위: 게인 스케줄 마하 격자의 최소 ~ min(격자 최대, M_NO). 격자는 기체가 설계된 비행 마하이고, M_NO(최대 운용
 *  마하)를 넘는 격자점은 운용 범위가 아니다. 돌려주는 것: {value: [마하…], source} | {error}. */
export function operatingMachs(doc, n = 3) {
  const grid = (Array.isArray(doc?.law?.schedule?.mach_grid) ? doc.law.schedule.mach_grid : [])
    .filter((v) => finite(v) && v > 0);
  if (!grid.length) {
    return { error: "문서에 게인 스케줄 마하 격자(law.schedule.mach_grid)가 없어 운용 마하 범위를 정할 수 없습니다 "
      + "— 겹칠 마하를 직접 주세요" };
  }
  const lo = Math.min(...grid);
  let hi = Math.max(...grid);
  let hiSource = `law.schedule.mach_grid 최대 ${hi}`;
  const mno = doc?.structural?.mach_no;
  if (finite(mno) && mno > 0 && mno < hi) [hi, hiSource] = [mno, `structural.mach_no ${mno}`];
  const source = `law.schedule.mach_grid 최소 ${lo} ~ ${hiSource}`;
  if (hi < lo) return { error: `스케줄 마하 격자(최소 ${lo})가 통째로 M_NO(${mno}) 위에 있습니다 — 운용 범위가 없습니다` };
  if (hi === lo) return { value: [r3(lo)], source };
  const k = Math.max(2, Math.floor(n));
  const values = [...new Set(Array.from({ length: k }, (_, i) => r3(lo + ((hi - lo) * i) / (k - 1))))];
  return { value: values, source };
}

/** 신호 args.mach — 양의 유한수 1~6개(뷰어 겹치기 한도와 같다). */
export function machListArg(v) {
  if (!Array.isArray(v)) return { error: "mach는 마하 목록(배열)이어야 합니다" };
  if (v.length < 1 || v.length > 6) return { error: `겹칠 마하는 1~6개입니다: ${v.length}개` };
  if (!v.every((m) => finite(m) && m > 0)) return { error: "겹칠 마하는 양의 유한수여야 합니다" };
  return { value: v };
}

/** CD0 항 — lift_drag 형식의 CD 항 중 **입력 없는 상수항** 하나. 돌려주는 것: {index, k} | {error}.
 *  여럿이면 어느 것이 CD0인지 정하지 않는다(더하면 둘로 나눈 항의 합이 바뀐다). 표 k에는 수를 더할 수 없다. */
export function cd0TermIndex(aero) {
  if (aero?.form !== "lift_drag") {
    return { error: `공력 형식이 ${aero?.form ?? "없음"}입니다 — CD 항은 lift_drag 형식에만 있습니다` };
  }
  const terms = aero?.coefficients?.CD;
  if (!Array.isArray(terms)) return { error: "문서에 CD 항 목록이 없습니다" };
  const idx = terms.flatMap((t, i) => (Array.isArray(t?.inputs) && t.inputs.length === 0 ? [i] : []));
  if (!idx.length) return { error: "CD에 입력 없는 상수항(CD0)이 없습니다" };
  if (idx.length > 1) return { error: `CD 상수항이 ${idx.length}개(${idx.join(", ")}번)라 어느 것이 CD0인지 정할 수 없습니다` };
  const k = terms[idx[0]].k;
  if (!finite(k)) {
    return { error: `CD0 항(/aero/coefficients/CD/${idx[0]}/k)이 수치가 아니라 표입니다 — 수를 더할 수 없습니다` };
  }
  return { index: idx[0], k };
}

/** 공학 수정 「EO/IR 볼 항력」의 계획 — 형상 변형 치환에 `/aero/coefficients/CD/<CD0>/k` = 기본 문서 CD0 + Δ.
 *
 *  **기본 문서** CD0에 더한다(변형이 이미 덮은 값에 또 더하지 않는다) — 같은 신호를 두 번 받아도 같은 문서가 된다.
 *  변형이 CD 목록을 통째로 바꿔 항 자리가 달라졌으면 멈춘다: 기본 문서의 번호가 그 변형에서는 다른 항이다.
 *  돌려주는 것: {ptr, value, base, before(지금 변형에서 보이는 값), changed} | {error}. */
export function cd0EditPlan(doc, variantId, delta) {
  if (!finite(delta)) return { error: "cd0_delta는 유한한 수여야 합니다" };
  const variant = (Array.isArray(doc?.variants) ? doc.variants : []).find((v) => v?.id === variantId);
  if (!variant) return { error: `형상 변형 「${variantId}」이 문서에 없습니다` };
  const base = cd0TermIndex(doc?.aero);
  if (base.error) return base;
  const value = tidy(base.k + delta);
  if (!(value > 0)) return { error: `CD0 ${base.k} + ${delta} = ${value} — 0 이하의 CD0는 쓰지 않습니다` };
  const shown = cd0TermIndex(applyPatch(doc, variant.patch).doc?.aero);
  if (shown.error || shown.index !== base.index) {
    return { error: `형상 변형 「${variantId}」이 CD 항 목록을 덮어써 기본 문서의 CD0 자리(${base.index}번)와 `
      + "다릅니다 — 폼에서 직접 고칩니다" };
  }
  return {
    ptr: `/aero/coefficients/CD/${base.index}/k`, value, base: base.k, before: shown.k, changed: shown.k !== value,
  };
}

/** overview 보고 — GET 응답(서버가 문서 경고를 동봉한다). */
export function overviewReport(body) {
  const d = body?.document ?? {};
  const warnings = Array.isArray(body?.warnings) ? body.warnings : [];
  const head = `${d.name} · 리비전 ${body?.revision}`;
  const w = warnings[0];
  const summary = warnings.length
    ? `${head} · 문서 경고 ${warnings.length}건 — ${w.variant ? `[형상 변형 ${w.variant}] ` : ""}${w.path} `
      + firstClause(w.message)
    : `${head} · 문서 경고 없음`;
  return { summary, data: { id: d.id, name: d.name, revision: body?.revision, fingerprint: body?.fingerprint, warnings } };
}

/** aero 보고 — 겹친 곡선마다 실속 추출(CL 꼭대기) vs 실속 표(그 마하). 값은 서버 응답 그대로. */
export function aeroReport(result) {
  const curves = result?.curves ?? [];
  const mach = curves.map((c) => c.res?.fixed?.mach ?? null);
  const ext = curves.map((c) => c.res?.stall?.extracted ?? null);
  const tab = curves.map((c) => c.res?.stall?.table_at ?? null);
  const reasons = curves.map((c) => c.res?.stall?.reason ?? null);
  const summary = `실속 추출 α ${ext.map(f3).join(" · ")} rad vs 실속 표 ${tab.map(f3).join(" · ")} rad `
    + `(M ${mach.map((m) => (m == null ? "—" : String(m))).join(" · ")})`;
  return {
    summary,
    data: { mach, stall_extracted: ext, stall_table: tab, ...(reasons.some(Boolean) ? { reasons } : {}) },
  };
}

const STAB_NAME = { Cl_beta: "Clβ", Cn_beta: "Cnβ", Cm_alpha: "Cmα" };

/** stability 보고 — 도함수별 판정(서버 judgments)과 위반 α 구간 전부. */
export function stabilityReport(res) {
  const entries = Object.entries(res?.judgments ?? {});
  const violations = entries.flatMap(([name, j]) =>
    (j.violations ?? []).map(([a, b]) => ({ derivative: name, alpha: [a, b] })));
  const summary = entries.map(([name, j]) => {
    const label = STAB_NAME[name] ?? name;
    if (j.all_ok) return `${label} 안정`;
    return `${label} 위반 ${(j.violations ?? []).map(([a, b]) => `α [${f3(a)}, ${f3(b)}]`).join(" · ")} rad`;
  }).join(" · ");
  return { summary, data: { violations } };
}

/** seed-basis 보고 — 머리말(트림점) + 레이트 후보 달성 수·자세 PI 통과 수. 판정 불리언은 엔진 것. */
export function basisReport(body) {
  const head = basisHead(body);
  if (!head.ok) return { error: head.line };
  const rates = basisRates(body);
  const att = basisAttitude(body);
  const achieved = rates.filter((r) => r.k != null && r.achievedOk === true).length;
  const passing = att.filter((a) => a.passing).length;
  // 판정 수만 적으면 근소 미달(0.697/0.700)과 큰 미달이 같은 「달성 0/3」이 된다(쇼케이스 D7) — 판정은 엔진 것 그대로,
  // 자리마다 달성/목표·목표 대비 차를 곁들인다(패널 표의 「전체 모델 달성」 칸과 같은 글). 카드 줄이 잘려도
  // 판정과 수가 남게 앞에 두고, 트림 조건 머리말은 뒤에 둔다
  const each = rates.map(achievedText).filter(Boolean);
  return {
    summary: `레이트 후보 달성 ${achieved}/${rates.length}${each.length ? ` (${each.join(" · ")})` : ""}`
      + ` · 자세 PI 통과 ${passing}/${att.length} · ${head.line}`,
    data: {
      case: body.case ?? null,
      rates: rates.map((r) => ({ slot: r.slot, k: r.k, achieved_ok: r.achievedOk, stable: r.stable,
        metric: r.metric, achieved: r.achieved, target: r.target, gap: r.gap })),
      attitude: att.map((a) => ({ slot: a.slot, kp: a.kp, ki: a.ki, passing: a.passing })),
    },
  };
}

/** edit-eoir-drag 보고 — 값·리비전·형상 변형 지문 전후. after가 null이면 저장하지 않은 것(이미 같은 값).
 *  trim: 저장 뒤 목록 요약으로 본 δe_trim 표 상태(quickseed deTrimStatus) — 낡음을 그대로 싣는다. */
export function editReport({ variant, delta, plan, before, after, trim }) {
  const sign = delta < 0 ? "−" : "+";
  const basis = `(기본 ${plan.base} ${sign} ${Math.abs(delta)})`;
  const staleVariants = trim?.stale ? (trim.staleVariants ?? []) : [];
  const data = {
    revision: (after ?? before).revision,
    fingerprint_before: before.fingerprint, fingerprint_after: (after ?? before).fingerprint,
    variant, path: plan.ptr, cd0_base: plan.base, cd0_before: plan.before, cd0_after: plan.value,
    changed: !!after, base_fingerprint: (after ?? before).baseFingerprint, de_trim_stale_variants: staleVariants,
  };
  if (!after) {
    return { summary: `형상 변형 ${variant} CD0 이미 ${plan.value} — 저장하지 않았습니다 ${basis} · 리비전 ${before.revision}`, data };
  }
  const summary = `형상 변형 ${variant} CD0 ${plan.before} → ${plan.value} ${basis} · 리비전 ${before.revision} → `
    + `${after.revision} · 변형 지문 ${before.fingerprint} → ${after.fingerprint}`
    + (trim?.stale ? ` · δe_trim 표 낡음(${staleVariants.join(", ") || "기본 형상"})` : "");
  return { summary, data };
}

/** derive-de-trim 보고 — 결과 본문({derive, written, profile, conflict_head}). 저장까지 가야 성공이다. */
export function deriveReport(body) {
  const s = deriveSummary(body);
  if (!body?.derive) return { error: s.headline };
  if (!s.ok || !body.written) return { error: s.headline };
  const st = s.stats;
  const t = body.derive.alloc?.de_trim?.table;
  // 저장 성공 머리말은 조사를 맞춰 여기서 짓는다 — quickseed의 머리말이 「리비전 ${n}로」로 조사를 박아 3·6·10에서
  // 「리비전 3로」가 됐다(쇼케이스 D17). 그쪽이 withJosa를 쓰게 되면 s.headline로 되돌린다
  const headline = `채택 — 리비전 ${withJosa(body.profile?.revision ?? "—", "으로/로")} 저장했습니다`;
  return {
    summary: headline + (st ? ` · 검사 ${st.checks}점 · 요구 미달 ${st.shortfall} · 보정 ${st.iterations}회` : ""),
    data: { revision: body.profile?.revision ?? null, table: t ? { mach: t.axes.mach, data: t.data } : null },
  };
}
