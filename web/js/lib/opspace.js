/** 공통 운용공간 (05 §11) — 서버 `POST /grid/base` 응답을 화면이 쓰는 모양으로 (순수 로직, 테스트 대상).

점을 어디에 둘지(요구 운용영역 → 공통 마하 좌표 기본 격자)와 트림 전 상태(미계산 · 모델 부족)는 엔진
claw.opspace가 정한다. 여기서는 규칙을 다시 적지 않고 응답을 케이스·지도 칸·요약 글로 옮기기만 한다.
*/

import { parseNumberList } from "./grid.js";

/** 트림 전 상태(요구영역 판정) → 화면 이름 — 트림 결과 행의 region_state(손으로 더한 케이스가 영역 밖일 때). */
export const PRE_STATE_LABEL = Object.freeze({
  out_of_region: "요구영역 밖", undefined: "요구 미정의", model_gap: "모델 부족",
});

/** 기본 격자 → 트림 케이스 — **미계산 점만** 보낸다. 모델 부족 점은 트림하지 않고(모델 밖에서 푼 해는 근거가
 *  없다) 지도에 그 상태로 남는다. 이름은 서버가 값 그대로 지은 것을 싣는다(격자 좌표 = 케이스 매핑 키). */
export function casesFromBaseGrid(body) {
  return (body?.points ?? []).filter((p) => p.state === "not_run")
    .map((p) => ({ name: p.name, mach: p.mach, alt: p.alt, fuel: p.fuel }));
}

/** 지도 칸 목록 — 트림 결과 + 트림하지 않은 기본 격자 점(모델 부족). 같은 이름이 결과에 있으면 결과가 이긴다.
 *  칸의 모양은 plot.js pivotCases가 읽는 {trim: {case, state}}다. */
export function gridMapEntries(results, grid) {
  const entries = (results ?? []).map((r) => ({ trim: r }));
  const seen = new Set((results ?? []).map((r) => r.case?.name));
  for (const p of grid?.points ?? []) {
    if (p.state === "not_run" || seen.has(p.name)) continue;
    entries.push({ trim: { case: { name: p.name, mach: p.mach, alt: p.alt, fuel: p.fuel }, state: p.state,
      state_reasons: [] } });
  }
  return entries;
}

/** 기본 격자에서 **트림하지 않은 것** — 모델 부족 점, 점이 없는 행(요구 미정의 · 요구영역 밖). 트림 결과만 세면
 *  이것들이 보고·머리줄에서 사라진다(05 §11.8 「계산하지 못한 점이 요약에서 사라지지 않는다」). 한 연료 층의 행이 전부
 *  미정의면 그 층은 지도가 서지 않으므로 이 글이 유일한 흔적이다. {modelGap, rows: [{alt, fuel, state}], text|null} */
export function untrimmedSummary(grid, labels = grid?.labels) {
  const modelGap = (grid?.points ?? []).filter((p) => p.state === "model_gap").length;
  const rows = (grid?.rows ?? []).filter((r) => r.state !== "not_run").map(({ alt, fuel, state }) => ({ alt, fuel, state }));
  const parts = [];
  if (modelGap) parts.push(`${labels?.model_gap ?? "모델 부족"} ${modelGap}점`);
  if (rows.length) {
    parts.push(`점 없는 행 ${rows.length} (${rows.map((r) => `${r.alt} m·${r.fuel} kg ${labels?.[r.state] ?? r.state}`)
      .join(", ")})`);
  }
  return { modelGap, rows, text: parts.length ? `트림하지 않음 — ${parts.join(" · ")}` : null };
}

/** 상태별 개수 → 「미계산 30 · 모델 부족 2」. labels는 서버가 준 상태 라벨(엔진 STATE_LABEL). */
export function stateCountText(counts, labels) {
  const parts = Object.entries(counts ?? {}).filter(([, n]) => n > 0).map(([s, n]) => `${labels?.[s] ?? s} ${n}`);
  return parts.length ? parts.join(" · ") : "점 없음";
}

const span = ([lo, hi]) => `${lo}–${hi}`;

/** 요구영역·모델 영역 → 요약 글 {status, range, model, boundary: [{fuel, alt, lo, hi}]}. 미확정 초안이면 status가
 *  먼저 그렇다고 말한다 — 초안으로 계산한 결과를 확정 요구영역의 결과처럼 읽지 않게(05 §11.2). */
export function regionLines(region, model) {
  const status = region.confirmed
    ? "확정 — 기체 문서의 요구 운용영역(operating_region)"
    : "미확정 초안 — 기체 문서에 요구 운용영역이 없어 미션 템플릿 격자(trim_grid)의 범위로 만든 초안입니다. "
      + "요구영역은 계산할 점 목록이 아니라 성능을 확보해야 할 범위라, 기체 문서에 적어야 확정됩니다.";
  const range = `마하 ${span(region.mach)} · 고도 ${span(region.alt)} m · 연료 ${span(region.fuel)} kg`;
  const modelText = `${model?.mach ? `DB 마하 ${span(model.mach)}` : "DB 마하 미기재"} · 연료 ${span(model?.fuel ?? [0, 0])} kg`;
  const boundary = (region.boundary ?? []).flatMap((layer) =>
    layer.rows.map(([alt, lo, hi]) => ({ fuel: layer.fuel, alt, lo, hi })));
  return { status, range, model: modelText, boundary };
}

/** 격자 명세 칸 글 → 요청 본문 조각. 빈 칸은 싣지 않는다 — 서버가 요구영역의 기본 격자 명세를 쓴다. */
export function parseGridSpec({ nMach = "", alts = "", fuels = "" }) {
  const out = {};
  nMach = nMach ?? "";
  alts = alts ?? "";
  fuels = fuels ?? "";
  if (String(nMach).trim()) {
    const n = Number(nMach);
    if (!Number.isInteger(n) || n < 2) throw new Error(`마하 점 수는 2 이상 정수: ${nMach}`);
    out.n_mach = n;
  }
  if (String(alts).trim()) out.alts = parseNumberList(alts);
  if (String(fuels).trim()) out.fuels = parseNumberList(fuels);
  return out;
}

/** 조건 상태 지도(연료 한 장)의 배치 — 가로는 **실제 마하**(등간격 열이 아니다: 행 끝점은 공통 좌표 사이에 떨어진다),
 *  세로는 고도 행(위로 증가). 행마다 요구 마하 띠(경계표가 정한 하한–상한)를 먼저 깔고 점을 그 위에 둔다 — 요구영역과
 *  계산 결과의 겹침이 한눈에 보이게(06 §10). 요구 미정의 행은 띠 없이 그 사실만.
 *  입력: rows [{alt, fuel, bounds|null, state}] · entries [{trim: {case, state, …}}] · machRange [lo, hi] · fuel.
 *  돌려줌: {x(mach)→px, rowY(alt)→px, height, alts, bands:[{alt, x0, x1, undefined}], dots:[{x, y, entry}], ticks} */
export const STATE_MAP_LAYOUT = Object.freeze({ mL: 64, mR: 16, mT: 28, mB: 34, rowH: 34 });

export function stateMapLayout({ rows, entries, machRange, fuel, width }) {
  const { mL, mR, mT, mB, rowH } = STATE_MAP_LAYOUT;
  const mine = (rows ?? []).filter((r) => r.fuel === fuel);
  const dotsIn = (entries ?? []).filter((e) => e.trim.case.fuel === fuel);
  const alts = [...new Set([...mine.map((r) => r.alt), ...dotsIn.map((e) => e.trim.case.alt)])].sort((a, b) => a - b);
  const machs = dotsIn.map((e) => e.trim.case.mach);
  const lo = Math.min(machRange?.[0] ?? Infinity, ...machs);
  const hi = Math.max(machRange?.[1] ?? -Infinity, ...machs);
  const pad = (hi - lo || 0.1) * 0.04;
  const m0 = lo - pad;
  const m1 = hi + pad;
  const x = (m) => mL + ((m - m0) / (m1 - m0)) * (width - mL - mR);
  const height = mT + alts.length * rowH + mB;
  const rowY = (alt) => mT + (alts.length - 1 - alts.indexOf(alt)) * rowH + rowH / 2;
  const bands = mine.map((r) => (r.bounds
    ? { alt: r.alt, x0: x(r.bounds[0]), x1: x(r.bounds[1]), undefined: false }
    : { alt: r.alt, x0: null, x1: null, undefined: true }));
  const dots = dotsIn.map((e) => ({ x: x(e.trim.case.mach), y: rowY(e.trim.case.alt), entry: e }));
  return { x, rowY, height, alts, bands, dots, domain: [m0, m1] };
}


// ── 영향성 탭의 비행조건 — 기본 격자에서 고른다 (05 §11.13 5단계 결정) ─────────────────────────
// 영향성 탭은 비행조건 구간을 따로 정하지 않는다: 「같은 조건에서 게인을 바꾸면」의 바닥인 조건이 탭마다 다르면
// 설계·평가와 다른 점에서 잰 감도가 된다. 점은 기본 격자(casesFromBaseGrid — 미계산 점만, 모델 부족·영역 밖은 안
// 보낸다)에서 **고르거나 거른다**. 없는 조건을 더하는 길은 두지 않는다(더하면 05 §11.11 보강 사유를 남겨야 한다).

/** 기본 격자 점의 필터 칸 — 고도·연료 값 목록(오름차순)과 마하 범위. */
export function pointAxes(points) {
  const uniq = (k) => [...new Set((points ?? []).map((p) => p[k]))].sort((a, b) => a - b);
  const ms = (points ?? []).map((p) => p.mach);
  return { alts: uniq("alt"), fuels: uniq("fuel"), mach: ms.length ? [Math.min(...ms), Math.max(...ms)] : null };
}

/** 거르기 — {alts, fuels}는 남길 값 목록(null = 전부, 빈 목록 = 없음 — 칩을 다 끄면 아무것도 안 보여야 한다),
 *  machLo·machHi는 포함 경계(null = 열림).
 *  돌려주는 순서는 입력 순서(기본 격자의 서펜타인 — 인접 트림 시드)다. */
export function filterPoints(points, { alts = null, fuels = null, machLo = null, machHi = null } = {}) {
  const inSet = (list, v) => list == null || list.includes(v);
  const lo = Number.isFinite(machLo) ? machLo - 1e-9 : -Infinity;
  const hi = Number.isFinite(machHi) ? machHi + 1e-9 : Infinity;
  return (points ?? []).filter((p) => inSet(alts, p.alt) && inSet(fuels, p.fuel) && p.mach >= lo && p.mach <= hi);
}

/** 대표점 — 종전 대표 부분 격자(lib/grid.js representativeGrid n=4: 마하 양끝 × 고도 양끝 × 연료 가운데)의 규칙을
 *  기본 격자 점 위에 옮긴 것. 기본 격자는 사각이 아니라(행마다 요구 마하 범위가 다르다) 규칙을 행 단위로 읽는다:
 *   ① 연료 — 있는 연료 값 중 [최소, 최대]의 가운데에 가장 가까운 것(같으면 낮은 쪽 — 옛 pickSpread가 짝수 개에서
 *      아래 가운데를 골랐다)
 *   ② 고도 — 그 연료의 행 중 가장 낮은 고도와 가장 높은 고도
 *   ③ 마하 — 그 두 행 각각의 가장 낮은 마하와 가장 높은 마하(행 끝점 — 동압 최저·최고, 게인 스케줄이 가장 멀리 가는 자리)
 *  최대 4점(겹치면 줄어든다). 돌려주는 것은 입력 점의 부분집합(입력 순서). */
export function representativePoints(points) {
  const list = points ?? [];
  if (!list.length) return [];
  const { fuels } = pointAxes(list);
  const mid = (fuels[0] + fuels[fuels.length - 1]) / 2;
  const fuel = fuels.reduce((best, f) => (Math.abs(f - mid) < Math.abs(best - mid) - 1e-12 ? f : best), fuels[0]);
  const atFuel = list.filter((p) => p.fuel === fuel);
  const alts = pointAxes(atFuel).alts;
  const pick = new Set();
  for (const alt of new Set([alts[0], alts[alts.length - 1]])) {
    const row = atFuel.filter((p) => p.alt === alt);
    const ms = row.map((p) => p.mach);
    for (const m of new Set([Math.min(...ms), Math.max(...ms)])) pick.add(row.find((p) => p.mach === m).name);
  }
  return list.filter((p) => pick.has(p.name));
}

/** 이름으로 고르기 — 이름이 하나라도 격자에 없으면 던진다(조용히 빠지면 「그 점을 쟀다」는 기록이 거짓이 된다).
 *  돌려주는 순서는 격자 순서다. */
export function pickNamed(points, names) {
  const have = new Set((points ?? []).map((p) => p.name));
  const missing = (names ?? []).filter((n) => !have.has(n));
  if (missing.length) {
    throw new Error(`기본 격자에 없는 점 ${missing.length}건: ${missing.join(", ")} — 요구영역·격자 명세를 확인한다`);
  }
  const want = new Set(names);
  return points.filter((p) => want.has(p.name));
}

/** 같은 기체 리비전의 응답인가 — 서버 profile 블록(id·variant·revision)을 대조한다. 한쪽이라도 없으면 아니다. */
export function sameProfileEcho(a, b) {
  if (!a || !b) return false;
  return a.id === b.id && (a.variant ?? null) === (b.variant ?? null) && (a.revision ?? null) === (b.revision ?? null);
}

/** 트림 배치 결과 → 이름별 결과 — 기본 격자와 **같은 기체 리비전**의 결과일 때만(다른 리비전의 트림 상태를 이 격자
 *  점에 붙이면 옛 판정을 지금 것으로 읽는다). 아니면 null. */
export function trimResultsByName(trimBody, grid) {
  if (!trimBody?.results || !sameProfileEcho(trimBody.profile, grid?.profile)) return null;
  return new Map(trimBody.results.map((r) => [r.case?.name, r]));
}

// ── 역할별 조건 고르기 (05 §11.13 5단계 나머지) — 마진 맵·게인 카드·흐름 평가도 기본 격자에서 ─────────────
// 탭마다 다른 격자를 쓰면 「최악 운용점」이 탭마다 다른 점 집합의 최악이 된다(04 §5). 마진 맵·지표(게인 카드·흐름
// 평가)는 보낼 수 있는 점 **전부**가 기본이다 — 마진 맵만 공용 고르개(views/condpick.js)로 좁힐 수 있다.

/** 역할 → 기본 선택 규칙. 지금은 셋 다 「보낼 수 있는 점 전부」(영향성 탭의 대표점은 신호의 선택이지 기본이 아니다). */
const ROLE_RULE = Object.freeze({ margin: "all", metric: "all", influence: "all" });

/** 역할의 기본 점 — {cases, reason}. reason이 있으면 보내지 않는다(cases 빈 목록): 격자를 못 받았다 · 요구영역
 *  미정의(region null — 템플릿 격자로 되돌아가지 않는다) · 보낼 점이 없다(전부 모델 부족). */
export function defaultRoleSelection(role, grid) {
  if (!Object.hasOwn(ROLE_RULE, role)) throw new Error(`모르는 역할: ${role}`);
  if (!grid) return { cases: [], reason: "기본 격자를 받지 못했다" };
  if (!grid.region) return { cases: [], reason: `요구영역 미정의 — ${grid.reason ?? "사유 없음"}` };
  const cases = casesFromBaseGrid(grid);
  if (!cases.length) return { cases: [], reason: "보낼 수 있는 점이 없다 — 기본 격자의 점이 전부 모델 부족이다" };
  return { cases, reason: null };
}

/** 요구영역이 미확정 초안이면 그 꼬리표 — 초안으로 잰 결과를 확정 요구영역의 결과로 읽지 않게(05 §11.2). */
export const DRAFT_TAG = "요구영역 미확정 초안";
export const draftTag = (grid) => (grid?.region && grid.region.confirmed === false ? DRAFT_TAG : "");

/** 점들의 가운데 — 가운데 연료 → 그 연료의 가운데 고도 → 그 행의 가운데 마하(짝수 개면 아래쪽 가운데).
 *  기본 격자는 사각이 아니라 축별 가운데를 따로 고르면 없는 점이 된다 — 행을 따라 좁힌다. 빈 목록이면 null. */
export function centrePoint(points) {
  const list = points ?? [];
  if (!list.length) return null;
  const mid = (xs) => xs[Math.floor((xs.length - 1) / 2)];
  const fuel = mid(pointAxes(list).fuels);
  const atFuel = list.filter((p) => p.fuel === fuel);
  const alt = mid(pointAxes(atFuel).alts);
  const row = atFuel.filter((p) => p.alt === alt);
  const mach = mid([...new Set(row.map((p) => p.mach))].sort((a, b) => a - b));
  return { mach, alt, fuel };
}

/** 서버 trim_reuse 되울림 → 「트림 재사용 k · 새로 n」. 없거나 모양이 다르면 null(옛 결과·옛 서버). */
export function reuseLine(trimReuse) {
  const r = trimReuse;
  if (!r || !Number.isFinite(r.reused) || !Number.isFinite(r.computed)) return null;
  return `트림 재사용 ${r.reused} · 새로 ${r.computed}`;
}

/** 같은 되울림의 툴팁 — 재사용 규칙·다시 푼 점. */
export function reuseTip(trimReuse) {
  const r = trimReuse;
  if (!reuseLine(r)) return "";
  const parts = ["같은 기체·같은 풀이 설정으로 이미 수렴한 수평 트림은 다시 풀지 않는다(서버 메모리 — 재시작하면 비워진다)"];
  if (r.policy) parts.push(`규칙 ${r.policy}`);
  if (Number.isFinite(r.resolved_failed) && r.resolved_failed > 0) parts.push(`저장된 미수렴 ${r.resolved_failed}점은 다시 풀었다`);
  return parts.join(" · ");
}

/** 기본 격자 점 중 서버 트림 저장소에 수렴 기록이 있는 점 수(points[].stored — 없는 서버면 0). */
export const storedCount = (grid) => (grid?.points ?? []).filter((p) => p.stored?.converged === true).length;
