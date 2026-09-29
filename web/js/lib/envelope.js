/** 엔벨로프 lib (01 §2.6) — 설계 엔벨로프 응답의 표현 변환 (뷰·캔버스와 분리, 테스트 대상).

수치·합성·귀속은 전부 엔진(design_envelope·envelope_verdict) — 여기서는
다각형 조립·구간 병합·판정 셀 분류·프리필 판단만. 서버가 준 필드를 다시
계산하지 않는다. 모르는 귀속·사유 코드는 코드 그대로 표시한다 (조용히
숨기면 엔진이 코드를 늘렸을 때 화면이 거짓말을 한다).
*/

import { parseGridSpec } from "./opspace.js";
import { niceTicks, STATE_REASON_LABEL, STATUS, TRIM_STATE_CELL } from "./plot.js";

// ── 요구 운용영역 (05 §11.13 이관 9단계 — 엔진 design_envelope requirement가 정본) ──────────
// 선도의 주인은 요구영역이다. 구조·공력 교집합(응답 region)은 추력 조건이 없어 「지속 비행 가능 영역」이 아니고,
// 요구를 깎는 선도 아니다 — 그 뜻 그대로의 이름을 한 곳에 둔다(범례·캔버스·캡션이 같은 말을 하게)
export const ANALYZABLE_LABEL = "현재 분석 가능한 영역 (구조·공력 — 추력 미포함)";
export const REQUIREMENT_UNDEFINED = "요구영역 미정의";

const finiteMach = (r) => Number.isFinite(r?.mach_lo) && Number.isFinite(r?.mach_hi);

/** 선도 연료의 요구 행 [{alt, mach_lo, mach_hi}] — 엔진 requirement.band(이 연료·표시 고도마다 보간한 요구 마하, 밖·미정의는
 *  null)가 정본이다. band가 없으면(옛 응답) 경계표 행 중 선도 연료 층의 것만 — 다른 층을 섞으면 다른 무게의 요구를 그린다. */
function requirementRowsAtFuel(requirement, fuel) {
  const b = requirement?.band;
  if (b?.alt) return b.alt.map((alt, i) => ({ alt, mach_lo: b.mach_lo[i], mach_hi: b.mach_hi[i], state: b.state?.[i] }));
  return (requirement?.rows ?? []).filter((r) => fuel == null || r.fuel === fuel);
}

/** 요구영역 → 선도 연료의 띠 {polys: [[{mach, alt}, …]], lines: [{alt, mach0, mach1}], undefinedAlts: [alt]}.
 *  마하가 없는 행(요구 미정의 · 요구영역 밖)에서 끊는다: 이웃 행으로 이어 칠하면 없는 요구를 그린다. undefinedAlts는
 *  미정의만(요구영역 밖 고도는 요구가 없는 게 정상이다). 한 행짜리 조각은 면이 못 되므로 가로선으로 남긴다. */
export function requirementBands(requirement, fuel = null) {
  const rows = [...requirementRowsAtFuel(requirement, fuel)].sort((a, b) => a.alt - b.alt);
  const polys = [];
  const lines = [];
  const undefinedAlts = [];
  let run = [];
  const flush = () => {
    if (run.length >= 2) {
      polys.push([
        ...run.map((r) => ({ mach: r.mach_lo, alt: r.alt })),
        ...[...run].reverse().map((r) => ({ mach: r.mach_hi, alt: r.alt })),
      ]);
    } else if (run.length === 1) {
      lines.push({ alt: run[0].alt, mach0: run[0].mach_lo, mach1: run[0].mach_hi });
    }
    run = [];
  };
  for (const r of rows) {
    if (finiteMach(r)) run.push(r);
    else {
      flush();
      if (r.state !== "out_of_region") undefinedAlts.push(r.alt);
    }
  }
  flush();
  return { polys, lines, undefinedAlts };
}

/** 선도 응답 → 요구영역 상태 {kind, label, text}. kind: "confirmed" | "draft" | "undefined" | "out_of_region_fuel"
 *  (선도 연료가 요구 연료 범위 밖 — 미정의가 아니다) | "undefined_at_fuel"(범위 안인데 경계표가 안 덮음).
 *  요구가 없으면 표시 고도 범위(0~12,000 m [기본값])가 요구처럼 읽히지 않게 그 사실을 먼저 말한다. */
export function requirementStatus(mh) {
  const req = mh?.requirement ?? null;
  const b = mh?.bounds ?? {};
  const shown = Number.isFinite(b.alt_min_used) && Number.isFinite(b.alt_max_used)
    ? `${b.alt_min_used}~${b.alt_max_used} m` : "표시 고도";
  if (!req) {
    return {
      kind: "undefined", label: REQUIREMENT_UNDEFINED,
      text: `${REQUIREMENT_UNDEFINED} — 기체 문서에 요구 운용영역(operating_region)도 미션 템플릿 격자(trim_grid)도 `
        + `없어 성능을 확보해야 할 범위가 정해지지 않았습니다. 선도의 고도 ${shown}는 표시 범위일 뿐 요구가 아닙니다.`,
    };
  }
  const f = Number(mh.fuel);
  const [fLo, fHi] = (req.fuel ?? []).map(Number);
  if (Number.isFinite(f) && Number.isFinite(fLo) && Number.isFinite(fHi) && (f < fLo - 1e-9 || f > fHi + 1e-9)) {
    // 요구 연료 밖 — 요구가 없는 게 정상이다(엔진 band state out_of_region). 경계표 미정의와 섞으면 문서를 고치라는 말이 된다
    return {
      kind: "out_of_region_fuel", label: `요구영역 밖 (연료 ${mh.fuel} kg)`,
      text: `연료 ${mh.fuel} kg는 요구 연료 범위(${req.fuel[0]}–${req.fuel[1]} kg) 밖입니다 — 이 선도에는 요구가 없습니다. `
        + "요구 연료 범위 안의 연료로 보면 요구 띠가 그려집니다.",
    };
  }
  if (!requirementRowsAtFuel(req, mh.fuel).some(finiteMach)) {
    return {
      kind: "undefined_at_fuel", label: `${REQUIREMENT_UNDEFINED} (연료 ${mh.fuel} kg)`,
      text: `이 연료(${mh.fuel} kg)에서는 요구영역의 경계표가 어느 고도도 덮지 않아 요구가 미정의입니다 — `
        + "가까운 연료 층으로 늘리지 않습니다(05 §11.2).",
    };
  }
  const range = `마하 ${req.mach[0]}–${req.mach[1]} · 고도 ${req.alt[0]}–${req.alt[1]} m · 연료 ${req.fuel[0]}–${req.fuel[1]} kg`;
  return req.confirmed
    ? { kind: "confirmed", label: "요구 운용영역", text: `요구 운용영역 (기체 문서 확정) — ${range}` }
    : { kind: "draft", label: "요구 운용영역 — 미확정 초안",
      text: `요구 운용영역 미확정 초안 — 기체 문서에 요구 운용영역이 없어 미션 템플릿 격자(trim_grid)의 범위로 만든 `
        + `초안입니다(${range}). 기체 문서에 적어야 확정됩니다.` };
}

/** 스캔 격자 명세 칸 → POST /grid/base 본문 — 마하 점 수·고도는 비우면 요구영역의 기본 격자 명세, 연료는 선도의
 *  연료 하나(판정 점은 선도 연료와 같을 때만 겹쳐 그린다). 좌표 규칙(공통 마하 좌표 + 행 끝점)은 엔진 한 곳이다. */
export function scanGridRequest({ nMach = "", alts = "", fuel }) {
  const f = Number(fuel);
  if (!Number.isFinite(f) || String(fuel ?? "").trim() === "") throw new Error(`연료가 숫자가 아님: ${fuel}`);
  return { ...parseGridSpec({ nMach, alts }), fuels: [f] };
}

// ── 경계 귀속 (엔진 lo_source/hi_source 코드가 정본) ──────────────────────
export const BOUND_META = {
  stall: { label: "실속 한계 (공력)", color: "#ff3b30" },
  db: { label: "공력 DB 범위", color: "#af52de" },
  stall_table: { label: "실속표 축 상한 (공력)", color: "#5856d6" },
  mach_no: { label: "M_NO (구조)", color: "#c93400" },
  qbar: { label: "q̄ 한계 (구조)", color: "#ff9500" },
  n_reach: { label: "하중배수 도달 불가", color: "#8e8e93" },
};

export const boundLabel = (code) => BOUND_META[code]?.label ?? code;
export const boundColor = (code) => BOUND_META[code]?.color ?? "#8e8e93";

/** 영역의 위·아래 모서리 귀속 — "실제 천장인가 표시 상한인가"를 문장으로 구분한다.
 * 교과서 엔벨로프는 닫힌 곡선이지만, 우리 상단 모서리는 셋 중 하나다: 운용
 * 상한(실기체 값), 표시 상한([기본값] — 운용 한계 아님), 자연 천장(실속 하한이
 * 마하 상한을 만나 설계 영역이 사라진 지점). 셋을 같은 선으로 그리면 화면이
 * 없는 상승한도를 있는 것처럼 말한다. */
export const CAP_META = {
  ops_alt_max: { label: "운용 고도 상한", color: "#007aff", dashed: false },
  ops_alt_min: { label: "운용 고도 하한", color: "#007aff", dashed: false },
  // 운용 고도가 없으면 표시 고도 끝을 요구영역 고도 끝으로 잡는다(엔진 alt_*_source "region" — 이관 9단계)
  region_alt_max: { label: "요구영역 고도 상한 — 운용 한계 아님", color: "#0040dd", dashed: true },
  region_alt_min: { label: "요구영역 고도 하한 — 운용 한계 아님", color: "#0040dd", dashed: true },
  display_max: { label: "표시 상한 [기본값] — 운용 한계 아님", color: "#aeaeb2", dashed: true },
  display_min: { label: "표시 하한 — 운용 하한 미입력", color: "#aeaeb2", dashed: true },
  natural_ceiling: { label: "자연 천장 (설계 영역 소멸)", color: "#8e8e93", dashed: true },
  natural_floor: { label: "자연 바닥 (설계 영역 소멸)", color: "#8e8e93", dashed: true },
};

export const capLabel = (code) => CAP_META[code]?.label ?? code;
export const capColor = (code) => CAP_META[code]?.color ?? "#8e8e93";

const EPS = 1e-9;

/** region → 닫힌 경계의 상·하 캡 [{side, alt, mach0, mach1, source}].
 * boundarySegments가 좌우(lo·hi)를 내므로 이쪽이 나머지 두 변이다. 한 행짜리
 * run도 위·아래 두 캡을 낸다 — 같은 선이지만 귀속이 다르고, 그 귀속이 정보다. */
export function outlineCaps(region, bounds) {
  const caps = [];
  let run = [];
  const capAt = (i, side) => {
    const alt = region.alt[i];
    // 끝의 출처는 엔진 alt_*_source가 정본(operating · region · display_default), 없으면(옛 응답) 종전 추론
    const src = (s, ops, reg, disp, legacyOps) => (s === "operating" ? ops : s === "region" ? reg
      : s === "display_default" ? disp : (legacyOps ? ops : disp));
    const source = side === "bottom"
      ? (Math.abs(alt - bounds.alt_min_used) < EPS
        ? src(bounds.alt_min_source, "ops_alt_min", "region_alt_min", "display_min", bounds.alt_min != null)
        : "natural_floor")
      : (Math.abs(alt - bounds.alt_max_used) < EPS
        ? src(bounds.alt_max_source, "ops_alt_max", "region_alt_max", "display_max", !bounds.alt_max_is_display_default)
        : "natural_ceiling");
    return { side, alt, mach0: region.mach_lo[i], mach1: region.mach_hi[i], source };
  };
  const flush = () => {
    if (run.length) {
      caps.push(capAt(run[0], "bottom"));
      caps.push(capAt(run[run.length - 1], "top"));
    }
    run = [];
  };
  region.alt.forEach((_, i) => {
    if (region.empty[i]) flush();
    else run.push(i);
  });
  flush();
  return caps;
}

/** region → 채움 다각형 목록 [[{mach, alt}, …], …] — empty 행에서 분할.
 * lo 곡선을 고도 오름차순으로, hi 곡선을 내림차순으로 이어 폐곡선. 한 행짜리
 * 조각은 면이 못 되므로 버린다 (경계선 세그먼트는 별도로 남는다). */
export function regionPolygons(region) {
  const polys = [];
  let run = [];
  const flush = () => {
    if (run.length >= 2) {
      polys.push([
        ...run.map((i) => ({ mach: region.mach_lo[i], alt: region.alt[i] })),
        ...[...run].reverse().map((i) => ({ mach: region.mach_hi[i], alt: region.alt[i] })),
      ]);
    }
    run = [];
  };
  region.alt.forEach((_, i) => {
    if (region.empty[i]) flush();
    else run.push(i);
  });
  flush();
  return polys;
}

/** region → 귀속별 경계선 세그먼트 [{source, side, pts}] — side "lo"|"hi".
 * 같은 source 연속 행을 병합하고, source가 바뀌는 지점은 직전 점을 공유해
 * 곡선이 끊겨 보이지 않게 한다. empty 행은 세그먼트를 끊는다 (가짜 연결선 금지). */
export function boundarySegments(region) {
  const out = [];
  for (const side of ["lo", "hi"]) {
    const srcArr = region[`${side}_source`];
    const machArr = side === "lo" ? region.mach_lo : region.mach_hi;
    let cur = null;
    let prevPt = null;
    region.alt.forEach((alt, i) => {
      if (region.empty[i]) {
        cur = null;
        prevPt = null;
        return;
      }
      const pt = { mach: machArr[i], alt };
      if (!cur || cur.source !== srcArr[i]) {
        cur = { source: srcArr[i], side, pts: prevPt ? [prevPt] : [] };
        out.push(cur);
      }
      cur.pts.push(pt);
      prevPt = pt;
    });
  }
  return out;
}

// ── 제어 가능 영역 스캔 (엔진 envelope_verdict 사유 코드가 정본) ──────────
export const KIND_META = {
  ok: { label: "제어 가능 (트림 성립)", color: STATUS.ok },
  // 채택됐지만 판정선 여유가 미달인 칸 — 트림 탭의 「계산 가능·여유 미달」과 같은 색·같은 뜻(05 §11.3 채택 정책: 여유는
  // 채택을 막지 않고 표시만). 초록으로 칠하면 같은 조건에 두 탭이 다른 말을 한다
  ok_margin_short: { label: "여유 미달 (채택)", color: "#ffcc00" },
  not_converged: { label: "트림 미수렴", color: STATUS.na },
  alpha_margin: { label: "α 여유 부족 (실속 근접)", color: STATUS.bad },
  saturated_throttle_high: { label: "스로틀 상한 포화 (추진 한계)", color: "#ff9500" },
  saturated_de: { label: "타면 포화", color: "#ffcc00" },
  saturated_throttle_low: { label: "스로틀 하한 포화 (아이들)", color: "#5ac8fa" },
  // 조건 판정(05 §11.3 · 이관 8단계) 사유 — 엔진이 종전 사유 뒤에 덧붙인다(종전 사유가 있으면 대표는 종전 사유).
  // 종전 사유가 없는 실패의 대표가 이것들이다. 글은 트림 탭 표 한 벌(plot.js STATE_REASON_LABEL)에서 — 다시 적지 않는다
  ...Object.fromEntries([
    ...["stall_boundary", "limiter_clips_trim", "q_max", "mach_no"].map((k) => [k, "#af52de"]), // 제한 위반
    ...["db_mach", "db_alpha", "fuel_range"].map((k) => [k, "#8e8e93"]), // 모델 범위 밖
    ["stall_basis_missing", "#d1d1d6"], // 판정 미완료
  ].map(([k, color]) => [k, { label: STATE_REASON_LABEL[k], color }])),
  // 트림 범주 제외 — 글은 트림 탭 표 한 벌(plot.js)에서
  ...Object.fromEntries(["thrust_deficit", "idle_thrust_excess", "pitch_moment_short", "below_V_S", "1g_unreachable"]
    .map((k) => [k, { label: STATE_REASON_LABEL[k], color: STATUS.bad }])),
  ...Object.fromEntries([["constraint_hit", "#ff9500"], ["calc_failed", "#636366"]]
    .map(([k, color]) => [k, { label: TRIM_STATE_CELL[k].label, color }])),
  unassessed: { label: "트림 미수렴 (근거 미평가)", color: STATUS.na },
  // 여유 사유는 판정선 여유다(스로틀 상한 = 추진 여유 미달 — 추력이 모자란 것이 아니다)
  throttle_high: { label: "추진 여유 미달", color: "#ff9500" },
  throttle_low: { label: "스로틀 하한 여유 미달", color: "#5ac8fa" },
  de: { label: "엘레본 여유 미달", color: "#ffcc00" },
};

export const kindLabel = (kind) => KIND_META[kind]?.label ?? kind;
export const kindColor = (kind) => KIND_META[kind]?.color ?? "#8e8e93";

/** 스캔 entries → 판정 셀 {mach, alt, fuel, ok, kind}.
 * kind는 엔진 reasons의 첫 항목(우선순위 대표 — points.envelope_verdict 순서).
 * 실패인데 사유가 비면 "unknown" — 성공으로 위장하지 않는다. */
// 판정의 제외 → 스캔 칸 대표. 트림 범주는 물리적 불가면 근거 사유(추력 부족·V_S 미만 …), 그 밖은 트림 상태 — 채널 코드
// (제약 도달의 throttle_high 등)는 여유 사유와 이름이 같아 대표로 쓰면 뜻이 틀린다. 판정이 없으면 null(옛 결과)
function exclusionKind(v) {
  const ex = v?.exclusion;
  if (!ex) return null;
  if (ex.category !== "trim") return ex.reasons?.[0] ?? ex.category;
  const status = v.trim?.status;
  return status === "infeasible" ? (ex.reasons?.[0] ?? status) : (status ?? "unassessed");
}

export function scanCells(entries) {
  return entries.map((e) => ({
    mach: e.trim.case.mach,
    alt: e.trim.case.alt,
    fuel: e.trim.case.fuel,
    ok: e.verdict.ok === true,
    kind: e.verdict.ok === true
      ? (e.verdict.verdict?.margin?.status === "short" ? "ok_margin_short" : "ok")
      // 채택 제외면 판정의 제외 사유가 대표다 — 종전 사유 첫 항목(α 여유·포화)은 v1.65에서 채택을 막지 않으므로 그것으로
      // 칠하면 트림 탭(「제한 위반 — α 리미터」)과 다른 말을 한다. 판정 없는 옛 결과만 종전 첫 사유
      : (exclusionKind(e.verdict.verdict) ?? e.verdict.reasons?.[0] ?? "unknown"),
    // 대표 kind는 우선순위 첫 사유뿐 — 스로틀 포화(3순위)는 미수렴에 가려진다.
    // 추력 한계 경계가 그 가려진 사유를 봐야 하므로 전량을 함께 싣는다.
    reasons: e.verdict.reasons ?? [],
  }));
}

/** 판정 셀 → 추력 한계 경계 [{alt, mach, side}] — 고도별 포화/비포화 전이점.
 *
 * 교과서 엔벨로프의 "available thrust limit"이 **이제 진짜로 이것**이다. 종전에는
 * 추력이 T = max_thrust·δt로 속도·고도와 무관해서 스로틀 포화가 추진 한계의
 * **대리 지표**였지만, 프로펠러 추력 모델(plant/prop.py PropEngine —
 * T = δσ·min(T_static, ηP/V))이 들어오면서 포화가 곧 "이 조건에서 프로펠러가 더
 * 못 낸다"가 됐다.
 *
 * 전선은 스로틀 100%가 아니라 **95% 등고선**이다(trim.py SAT_FRAC): 진짜 한계보다
 * 설계 여유만큼 안쪽이다.
 *
 * **행마다 바깥쪽 포화 구간의 가장자리만** 낸다 — lo 하나, hi 하나가 최대다.
 * 전이를 전부 내면 행 가운데 고립된 포화 셀 하나가 같은 좌표에 lo와 hi를 __둘 다__
 * 내고, 그 hi가 다른 고도의 hi와 한 줄로 이어져 평면을 가로지르는 가짜 전선이 된다
 * (기본 스캔 0.2~0.7/0.05에서 실제로 났다: 5000 m의 M0.25 한 칸이 M0.55 전선을
 * M0.25까지 끌어내렸다). 전선은 정의상 포화 영역의 __바깥 경계__이므로 안쪽 섬은
 * 전선이 아니다.
 *
 * __다만 그 대가를 정확히 적어 둔다__: 안쪽 섬의 포화는 이제 화면 어디에도 안 뜬다.
 * 셀 색이 대신 말해 주지 않는다 — kind는 우선순위 첫 사유뿐이라(위 scanCells) 그
 * 섬이 미수렴을 겸하면 회색으로만 보이고, 실제로 기본 스캔의 그 칸이 그렇다
 * (not_converged·alpha_margin·saturated_throttle_high). 가짜 전선을 지우는 값이
 * 더 크다고 봤을 뿐이고, 섬까지 드러내려면 전선이 아니라 별도 표시가 필요하다 [TBD].
 *
 * 그리고 **해석 곡선이 아니라 측정점**이다: 트림이 실제로 스로틀 상한에 부딪힌
 * 지점을 잇는 것이라 스캔 격자 해상도가 곧 경계 해상도다. 추력 곡선에서 직접
 * 푸는 해석해는 [TBD].
 *
 * side는 포화가 어느 쪽에 있는지다 — "hi"는 빨라서 모자란 것(항력), "lo"는 느려서
 * 모자란 것(유도항력이 커지는 항력곡선 backside). 형상에 따라 둘 다 나오므로 한쪽을
 * 가정하면 안 된다 — lo만 나오는 형상에서 "최저 포화 마하"를 경계라 부르면 스캔의
 * 왼쪽 끝을 경계라고 우기게 된다.
 * 전이가 없는 행(전부 포화/전부 비포화)은 __안 낸다__ — 스캔 가장자리를 경계로
 * 지어내지 않는다 (아래 구현의 row.every(sat) 가지).
 *
 * provisional은 그 전이점의 포화 셀이 **트림 미수렴**이라는 뜻이다. 미수렴 트림의
 * 스로틀은 해가 아니라 솔버의 마지막 반복값이므로 "수평비행에 이만큼 필요하다"는
 * 측정이 아니다 — 버리지도 않는다(대표 kind에 가려진 포화를 드러내는 것이 이
 * 함수의 존재 이유다). 잠정으로 표시하고 화면이 구분해 그린다. */
export function thrustFrontier(cells) {
  const sat = (c) => c.reasons?.includes("saturated_throttle_high") === true;
  const unconverged = (c) => c.reasons?.includes("not_converged") === true;
  const byAlt = new Map();
  for (const c of cells) {
    if (!byAlt.has(c.alt)) byAlt.set(c.alt, []);
    byAlt.get(c.alt).push(c);
  }
  const out = [];
  for (const alt of [...byAlt.keys()].sort((a, b) => a - b)) {
    const row = byAlt.get(alt).sort((a, b) => a.mach - b.mach);
    // 행 전체가 포화면 전이가 없다 — 가장자리를 경계로 지어내지 않는다
    if (row.every(sat)) continue;
    const point = (at, side) => ({ alt, mach: at.mach, side, provisional: unconverged(at) });
    // 저속 쪽: 행 앞머리의 연속 포화 구간, 그 안쪽 가장자리가 경계
    if (sat(row[0])) {
      let i = 0;
      while (i + 1 < row.length && sat(row[i + 1])) i += 1;
      out.push(point(row[i], "lo"));
    }
    // 고속 쪽: 행 꼬리의 연속 포화 구간
    const last = row.length - 1;
    if (sat(row[last])) {
      let i = last;
      while (i > 0 && sat(row[i - 1])) i -= 1;
      out.push(point(row[i], "hi"));
    }
  }
  return out;
}

const KIND_ORDER = [
  "ok_margin_short", // 실패가 아니라 채택 수의 일부 — 요약에서 「그중」으로 먼저 센다
  "thrust_deficit", "idle_thrust_excess", "pitch_moment_short", "below_V_S", "1g_unreachable",
  "constraint_hit", "calc_failed", "unassessed",
  "not_converged", "alpha_margin", "saturated_throttle_high",
  "saturated_de", "saturated_throttle_low",
  // 조건 판정 사유 — 엔진 opspace/verdict.py 항목 순서(모델 → 제한 → 여유)
  "db_mach", "db_alpha", "fuel_range", "stall_boundary", "limiter_clips_trim", "q_max", "mach_no",
  "stall_basis_missing", "throttle_high", "de", "throttle_low",
];

/** 판정 셀 → 종류별 집계 {total, ok, byKind: [{kind, n}]} — ok는 채택 수(여유 미달 채택 포함), byKind는 채택 중
 * 여유 미달(ok_margin_short)과 실패를 엔진 우선순위 순으로. 미정의 코드는 뒤에 그대로 덧붙인다. */
export function scanSummary(cells) {
  const counts = new Map();
  for (const c of cells) counts.set(c.kind, (counts.get(c.kind) ?? 0) + 1);
  const adopted = (counts.get("ok") ?? 0) + (counts.get("ok_margin_short") ?? 0);
  const byKind = [];
  for (const k of KIND_ORDER) {
    if (counts.has(k)) byKind.push({ kind: k, n: counts.get(k) });
  }
  for (const [k, n] of counts) {
    if (k !== "ok" && !KIND_ORDER.includes(k)) byKind.push({ kind: k, n });
  }
  return { total: cells.length, ok: adopted, byKind };
}

/** 추진 히트맵 셀 — 트림 스로틀 소요(연속 색: 초록→주황) + 포화·불가 구분.
 * 판정 문턱을 여기서 만들지 않는다 — 포화 여부는 엔진 verdict 사유가 정본,
 * 색 그라데이션은 소요량의 표시일 뿐이다. */
export function throttleCell(entry) {
  if (!entry.trim.converged) {
    return { color: STATUS.na, text: "불가" };
  }
  const thr = entry.trim.control.throttle[0];
  const pct = `${Math.round(thr * 100)}%`;
  if (entry.verdict.reasons?.includes("saturated_throttle_high")) {
    return { color: STATUS.bad, text: `${pct} 포화` };
  }
  const t = Math.min(1, Math.max(0, thr));
  return { color: `hsl(${Math.round(130 - 100 * t)}, 65%, 42%)`, text: pct };
}

// 표시 행 격자의 이산화 오차를 넘는 실제 이탈만 센다. 스케줄 격자점의 마하는
// 자기 고도에서 정확히 계산되는데 경계는 표시 행(41행 = 300 m 간격)에서만
// 샘플되므로, 보간해도 머리카락만큼은 어긋난다 — 그걸 "영역 밖"이라 부르면
// 경고가 상시 켜져 진짜 이탈(q̄ 경계는 훨씬 크게 벌어진다)을 덮는다.
const REGION_TOL = 1e-3;

/** 점이 합성 영역 밖인가 — 고도 이웃 두 행 사이를 보간한 [mach_lo, mach_hi] 기준.
 *
 * 스케줄 격자점은 좌표를 coarse 격자(design.grid)와 맞추려고 **q̄를 보지 않고**
 * 만들어진다(design_envelope docstring). q̄_max가 낮으면 격자점이 영역 밖에
 * 놓이는데, 그것이 실제 설계점 위치이므로 좌표를 고치면 화면이 거짓말을 한다 —
 * 대신 밖이라는 사실을 표시한다. 이웃 행 중 하나라도 empty면 밖으로 본다. */
export function outsideRegion(point, region) {
  const n = region.alt.length;
  if (!n) return false;
  let hi = region.alt.findIndex((a) => a >= point.alt);
  if (hi < 0) hi = n - 1;
  const lo = Math.max(0, hi - 1);
  if (region.empty[lo] || region.empty[hi]) return true;
  const span = region.alt[hi] - region.alt[lo];
  const t = span === 0 ? 0 : (point.alt - region.alt[lo]) / span;
  const at = (arr) => arr[lo] + (arr[hi] - arr[lo]) * t;
  return point.mach < at(region.mach_lo) - REGION_TOL
    || point.mach > at(region.mach_hi) + REGION_TOL;
}

// ── 표시 보조 (좌표 변환·라벨 배치 — 수치를 만들지 않는다) ────────────────

const FT_PER_M = 1 / 0.3048; // 국제피트 정의값 — 근사 상수를 손으로 적지 않는다
const KT_PER_MS = 3600 / 1852; // 해리 정의값 1852 m — 1.94384…를 손으로 적지 않는다

/** m → ft. 우측 보조 고도축 전용 — 순수 단위 환산이라 근사가 없다. */
export const mToFt = (m) => m * FT_PER_M;

/** ft → m. 우측 보조축이 **자기 눈금**(둥근 ft)을 가지려면 그 자리를 되돌려야 한다. */
export const ftToM = (ft) => ft / FT_PER_M;

/** m/s → kt. 상단 보조 속도축·등속선 라벨 전용 — 순수 단위 환산. */
export const msToKt = (v) => v * KT_PER_MS;

/** 상단 대기속도 보조축 눈금 — [{kt, mach}], 마하 범위 안만.
 *
 * 교과서 엔벨로프(Fig 1)는 마하축 위에 kt 축을 겹쳐 그린다. M ↔ V = M·a의
 * 대응은 고도마다 다르므로 그 축은 **한 고도에서만** 참이다 — 그래서 a를
 * 인자로 받는다: 호출측이 축을 그리는 자리(도표 상단 모서리)의 음속을 엔진
 * echo(bounds.speed_of_sound)에서 넘기면, 축은 적어도 자기가 놓인 선 위에서
 * 정확하다. 고도 의존 자체는 등속선(iso.tas)이 평면 안에서 그린다.
 *
 * a가 비유한·비양수면 빈 목록 — 축을 안 그리는 것이 0 kt 눈금을 늘어놓는 것보다
 * 낫다(단위 환산이 실패한 자리에 그럴듯한 숫자를 남기지 않는다).
 *
 * 범위 필터는 죽은 코드가 아니다 — 상단 축은 호출측에서 **클립을 푼 뒤** 그려지므로
 * 범위 밖 눈금은 잘리지 않고 여백·프레임 밖에 찍힌다. 지금은 `niceTicks`가 이미
 * 범위 안만 내서 필터가 발화하지 않지만, 그 계약이 바뀌는 날 눈금이 캔버스 밖으로
 * 새 나간다(축이 없는 것보다 나쁘다). 테스트도 이 사정을 그대로 적어 둔다.
 */
export function tasAxisTicks(machMin, machMax, a, n = 6) {
  if (!Number.isFinite(a) || a <= 0 || !(machMax > machMin)) return [];
  return niceTicks(msToKt(machMin * a), msToKt(machMax * a), n)
    .map((kt) => ({ kt, mach: kt / KT_PER_MS / a }))
    .filter((t) => t.mach >= machMin && t.mach <= machMax);
}

/** 라벨 세로 겹침 해소 — [{y, …}] → 같은 순서·같은 상하 관계, 간격 ≥ minGap.
 * y 오름순으로 훑으며 앞 라벨 아래로 밀기만 한다(위로 당기지 않는다 — 지시선이
 * 가리키는 점보다 라벨이 위로 튀면 어느 경계 이름인지 되레 헷갈린다). */
export function spreadLabels(items, minGap) {
  const order = items.map((it, i) => i).sort((a, b) => items[a].y - items[b].y);
  const out = items.map((it) => ({ ...it }));
  let prev = -Infinity;
  for (const i of order) {
    out[i].y = Math.max(out[i].y, prev + minGap);
    prev = out[i].y;
  }
  return out;
}

/** 글 상자 — fillText 기준점(x, 기준선 y)·폭 w·글자 크기 size·정렬 → {x0, y0, x1, y1}.
 *  기준선 위로 0.85·아래로 0.25 글자 크기 — 한글 받침·영문 내림까지 덮는 근사(겹침 판정용, 픽셀 정확도 아님). */
export function textBox(x, y, w, size, align = "left") {
  const x0 = align === "right" ? x - w : align === "center" ? x - w / 2 : x;
  return { x0, y0: y - size * 0.85, x1: x0 + w, y1: y + size * 0.25 };
}

/** 두 상자의 겹친 넓이 (px²) — 0이면 안 겹친다(모서리 맞닿음 포함). */
export function boxOverlap(a, b) {
  const w = Math.min(a.x1, b.x1) - Math.max(a.x0, b.x0);
  const h = Math.min(a.y1, b.y1) - Math.max(a.y0, b.y0);
  return w > 0 && h > 0 ? w * h : 0;
}

const boxInside = (b, r) => b.x0 >= r.x0 && b.x1 <= r.x1 && b.y0 >= r.y0 && b.y1 <= r.y1;

/** 점 목록 [{x, y}] → 반지름 r의 상자 — 판정 점·격자점을 라벨이 피할 장애물로. */
export function pointObstacles(points, r) {
  return points.map((p) => ({ x0: p.x - r, y0: p.y - r, x1: p.x + r, y1: p.y + r }));
}

/** 선에 붙는 라벨의 후보 자리 (placeLabels 입력) — 첫 후보가 종전 자리다(겹치지 않으면 그림이 그대로).
 *  kind "v"(세로선, at = 가로축 값): 위 줄들의 선 오른쪽·왼쪽, 그다음 아래 줄들 — 가까운 줄부터.
 *  kind "h"(가로선, at = 세로축 값): 선 바로 위·아래를 왼쪽 끝 → 오른쪽 끝(xEnd, 선이 끝나는 곳) → 가운데 순서로.
 *  plot은 플롯 틀 {x0, y0, x1, y1}, px·py는 값 → 픽셀. */
export function lineLabelCandidates(kind, at, { plot, px, py, xEnd = null, rows = 3, rowStep = 13 } = {}) {
  const out = [];
  if (kind === "v") {
    const x = px(at);
    const ys = [];
    for (let r = 0; r < rows; r += 1) ys.push(plot.y0 + 12 + r * rowStep);
    for (let r = 0; r < rows; r += 1) ys.push(plot.y1 - 5 - r * rowStep);
    for (const y of ys) out.push({ x: x + 3, y, align: "left" }, { x: x - 3, y, align: "right" });
    return out;
  }
  const y = py(at);
  const end = xEnd ?? plot.x1;
  for (const [x, align] of [[plot.x0 + 6, "left"], [end - 6, "right"], [(plot.x0 + end) / 2, "center"]]) {
    out.push({ x, y: y - 4, align }, { x, y: y + 12, align });
  }
  return out;
}

/** 겹침 없는 라벨 자리 — 탐욕 배치 (그림 위 글이 서로·판정 점 밑에 깔리지 않게, 쇼케이스 D10).
 *
 *  labels는 **우선순위 순서**: [{key, w, size, candidates: [{x, y, align}], optional?, region?, accept?, avoid?}].
 *  라벨마다 후보를 차례로 보며 첫 번째로 (a) 틀(bounds) 안이고 (b) region(구역 이름이면 그 구역 사각형) 안이고
 *  (c) accept(상자)가 참이고 (d) 이미 놓인 라벨·obstacles·avoid와 pad 이상 떨어진 자리를 잡는다.
 *  다 막히면 — optional이면 뺀다(skipped: 범례가 이름을 갖는 구역 이름 등), 아니면 겹침이 가장 적은 후보를 틀 안으로
 *  밀어 넣어 쓴다(fits:false — 선 이름을 지우는 것보다 겹쳐도 남는 편이 낫다). 돌려주는 것은 입력 순서
 *  [{key, x, y, align, box, fits, skipped}]. */
export function placeLabels(labels, { bounds, obstacles = [], pad = 2 } = {}) {
  const taken = [...obstacles];
  const grow = (b) => ({ x0: b.x0 - pad, y0: b.y0 - pad, x1: b.x1 + pad, y1: b.y1 + pad });
  return labels.map((l) => {
    const cands = (l.candidates ?? []).map((c) => {
      const align = c.align ?? "left";
      return { x: c.x, y: c.y, align, box: textBox(c.x, c.y, l.w, l.size, align) };
    });
    const blockers = [...taken, ...(l.avoid ?? [])];
    const allowed = (c) => boxInside(c.box, bounds) && (!l.region || boxInside(c.box, l.region))
      && (!l.accept || l.accept(c.box));
    const hit = cands.find((c) => allowed(c) && blockers.every((b) => boxOverlap(grow(c.box), b) === 0));
    let at = hit ? { ...hit, fits: true } : null;
    if (!at) {
      if (l.optional || !cands.length) return { key: l.key, x: null, y: null, align: null, box: null, fits: false, skipped: true };
      for (const c of cands) {
        const dx = c.box.x0 < bounds.x0 ? bounds.x0 - c.box.x0 : c.box.x1 > bounds.x1 ? bounds.x1 - c.box.x1 : 0;
        const dy = c.box.y0 < bounds.y0 ? bounds.y0 - c.box.y0 : c.box.y1 > bounds.y1 ? bounds.y1 - c.box.y1 : 0;
        const box = { x0: c.box.x0 + dx, y0: c.box.y0 + dy, x1: c.box.x1 + dx, y1: c.box.y1 + dy };
        const cost = blockers.reduce((sum, b) => sum + boxOverlap(box, b), 0);
        if (!at || cost < at.cost) at = { x: c.x + dx, y: c.y + dy, align: c.align, box, fits: false, cost };
      }
    }
    taken.push(at.box);
    return { key: l.key, x: at.x, y: at.y, align: at.align, box: at.box, fits: at.fits, skipped: false };
  });
}

/** 도표의 마하 창 {xMin, xMax} — 캔버스와 캡션이 **같은 창**을 봐야 "창 밖"이 한 말이
 * 된다. 창은 DB 하한·합성 하한의 최소와 M_D·합성 상한의 최대에 여백(pad)을 더한 것. */
export function machWindow(bounds, region, pad = 0.03) {
  const lo = dbLoBinds(bounds, region)
    ? Math.min(bounds.db_mach[0], ...region.mach_lo)
    : Math.min(...region.mach_lo);
  return {
    xMin: lo - pad,
    xMax: Math.max(bounds.mach_d, ...region.mach_hi) + pad,
  };
}

/** DB 마하 하한이 **실효 구속인가** — 합성 영역의 하한보다 위에 있을 때만 참.
 *
 * 공력 DB 대역의 하한이 비행 가능 영역보다 아래면 그 선은 아무것도 자르지 않는다.
 * 그래도 창을 거기까지 벌리면 왼쪽에 빈 띠가 생기고, 그 자리에 "DB 0.000" 선이
 * 그려지면 **없는 제약을 있다고 말하는** 그림이 된다 — 조용한 비표시의 반대쪽
 * 잘못이다. 데모 프로파일에서 영역 하한은 항상 실속 귀속(M0.205~0.500)이라
 * DB 하한은 0.1이던 시절에도 구속이 아니었고, 계수 함수가 마하를 쓰지 않아
 * 하한이 0으로 내려가면서 그 사실이 드러났을 뿐이다.
 *
 * 판정은 여기(lib)에서 한다 — 뷰에는 테스트가 없고, 선을 그릴지와 창을 어디까지
 * 벌릴지는 **같은 판단**이라 두 곳에 적으면 갈라진다. */
export function dbLoBinds(bounds, region) {
  const db = Number(bounds?.db_mach?.[0]);
  if (!Number.isFinite(db)) return false;
  const lows = (region?.mach_lo ?? []).filter((m) => Number.isFinite(m));
  if (lows.length === 0) return false;
  return db > Math.min(...lows);
}

/** 등고선 중 마하 창 안에 **한 점도** 없는 것 — 그리면 통째로 사라지는 곡선이다.
 *
 * 요청한(또는 엔진 [기본값]으로 들어간) 곡선이 사유 없이 화면에서 없어지는 것은 이
 * 리포가 금하는 조용한 비표시다 — `iso_curves`가 음수 V를 거부하는 사유로 든 것과
 * 같은 현상이고, 이쪽은 값이 멀쩡한데 창이 좁아서 벌어진다: M_NO·M_D를 낮게 입력하면
 * (저속기 프로파일) 엔진 [기본값] 등속선 100~250 m/s가 전부 창 밖으로 나간다.
 * 화면이 개수와 사유를 말할 수 있도록 목록으로 낸다. */
export function isoOffWindow(curves, xMin, xMax) {
  return curves.filter((c) => !c.mach.some((m) => m >= xMin && m <= xMax));
}

/** 등고선의 마하 구간 {lo, hi} — 창 밖 안내가 "왜 안 보이는지"의 **증거로 화면에 내는**
 * 수라서 뷰가 아니라 여기서 만든다(뷰에는 테스트가 없다).
 *
 * 비유한값이 하나라도 섞이면 null — Math.min은 null을 0으로 취급하고 undefined에는
 * NaN을 내므로, 그대로 쓰면 화면에 "M 0~1.72"나 "M NaN~NaN"이 증거인 척 찍힌다.
 * 현 엔진 계약에는 null이 오지 않지만, 증거 숫자를 지어내지 않는 것이 규칙이다. */
export function machSpan(curve) {
  const ms = curve.mach;
  if (!ms?.length || !ms.every((m) => Number.isFinite(m))) return null;
  return { lo: Math.min(...ms), hi: Math.max(...ms) };
}

/** 등고선 라벨 자리 — preferIdx에서 바깥으로 훑어 처음 만나는 x 범위 안 인덱스, 없으면 -1.
 *
 * 곡선이 평면을 비스듬히 가로지르므로 끝점은 대개 범위 밖이다. 기준점을 호출측이
 * 정하게 두는 이유: 여러 곡선이 모두 도표 천장으로 빠져나가면 "범위 안 마지막
 * 인덱스"가 전부 같은 행이 되어 라벨이 한 줄에 겹쳐 뭉갠다(라이브 확인에서 드러남).
 * 중간 높이를 기준으로 주면 곡선마다 x가 달라 자연히 흩어진다. */
export function isoLabelIndex(curve, xMin, xMax, preferIdx = curve.mach.length - 1) {
  const n = curve.mach.length;
  // 범위 밖 기준점을 그대로 쓰면 바깥 훑기가 배열을 다 못 덮어 -1이 나온다 —
  // "곡선이 화면 밖"과 구분이 안 되므로 기준점을 배열 안으로 접는다
  const start = Math.min(n - 1, Math.max(0, preferIdx));
  const inRange = (i) => i >= 0 && i < n && curve.mach[i] >= xMin && curve.mach[i] <= xMax;
  for (let d = 0; d < n; d += 1) {
    if (inRange(start - d)) return start - d;
    if (inRange(start + d)) return start + d;
  }
  return -1;
}

// ── 필요값 폼 (02 §5.5 — 웹은 엔진 기본값을 재기술하지 않는다) ────────────

/** 프리필 자기 정렬 — 사용자가 손댄 필드는 유지, 아니면 서버 echo로 갱신.
 * incoming null(경계 없음·미지정)은 빈칸. */
export function prefillValue(currentStr, touched, incoming) {
  if (touched) return currentStr;
  return incoming == null ? "" : String(incoming);
}

/** 옵션 수치 입력 — 빈칸은 null(파라미터 생략 = 서버 None 계약), 비유한값은 던진다. */
export function optNum(str, label = "값") {
  const s = String(str ?? "").trim();
  if (s === "") return null;
  const v = Number(s);
  if (!Number.isFinite(v)) throw new Error(`${label}이(가) 숫자가 아님: ${str}`);
  return v;
}

/** 쿼리 문자열 — null/undefined 생략 (서버 None = 데모 프로파일/경계 없음 계약).
 * 값을 보내는 순간 limits_source가 user-input이 되므로, 손대지 않은 필드는
 * 호출측이 null로 넘겨야 한다. */
export function envelopeQuery(params) {
  return Object.entries(params)
    .filter(([, v]) => v !== null && v !== undefined)
    .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
    .join("&");
}

// ── 한계 값의 출처 (⑤ 표) — 서버 echo가 정본, 웹은 라벨로만 바꾼다 ──────────

/** 구조 한계 한 칸의 출처 {text, ok} — limits_source("user-input"|"profile"|"demo-placeholder")와
 * limits_overridden(질의로 덮은 칸)에서. 사용자 기체의 문서 값을 "자리표시"로 부르면 실기체 값을 가짜라고
 * 말하게 되고, 예제 값을 기체 값으로 부르면 가짜를 진짜라고 말한다 (02 §5.6). user-input은 **덮은 칸만**
 * 사용자 입력이다 — 나머지 칸의 출처는 그 기체가 예제인지(echo profile.is_example)로 가린다. */
export function limitSourceLabel(param, limitsSource, overridden, isExample = null) {
  if ((overridden ?? []).includes(param)) return { text: "사용자 입력", ok: true };
  const example = limitsSource === "demo-placeholder"
    || (limitsSource === "user-input" && isExample !== false);
  return example ? { text: "데모 자리표시", ok: false } : { text: "기체 문서", ok: true };
}

/** 동압 한계·운용 고도 한 칸의 출처 {text, ok} — value는 응답 bounds의 값, source는 bounds_source의 그 칸
 * ("query"|"profile"|null). 서버는 문서 값을 하나라도 쓴 응답에만 bounds_source를 싣는다 — 없으면 값이 있는
 * 칸은 전부 질의(사용자 입력)에서 온 것이다. null 값은 문서에도 질의에도 없다는 뜻이라 경계 자체가 없다. */
export function opsSourceLabel(value, source) {
  if (value == null) return { text: "미입력 — 경계 없음", ok: false };
  return source === "profile" ? { text: "기체 문서", ok: true } : { text: "사용자 입력", ok: true };
}

// ── 쇼케이스 신호 보고 (lib/showcasecue.js) — 탭 자신의 산출물로 만든 한 줄 ──────

const num = (v) => (typeof v === "number" && Number.isFinite(v) ? String(Number(v.toPrecision(4))) : "—");

/** V-n·M-h 그리기 → 보고 {summary, data}. data는 진행기 계약(alts·q_max·alt_min·alt_max) + 출처·n_z. */
export function vnCueReport(vnList, mh) {
  const alts = (vnList ?? []).map((v) => v.alt);
  const b = mh?.bounds ?? {};
  const src = mh?.bounds_source ?? null;
  const nz = mh?.maneuver?.nz ?? null;
  const parts = [`V-n ${alts.length}고도(${alts.map((a) => `${num(a)} m`).join(" · ")})`];
  parts.push(b.q_max == null ? "q̄_max 경계 없음" : `q̄_max ${num(b.q_max)} Pa`);
  parts.push(b.alt_min == null && b.alt_max == null
    ? "운용 고도 경계 없음"
    : `운용 고도 ${b.alt_min == null ? "—" : num(b.alt_min)}~${b.alt_max == null ? "—" : num(b.alt_max)} m`);
  if (nz != null) parts.push(`기동 n_z ${num(nz)} g`);
  return {
    summary: parts.join(" · "),
    data: {
      alts, q_max: b.q_max ?? null, alt_min: b.alt_min ?? null, alt_max: b.alt_max ?? null,
      bounds_source: src, nz,
    },
  };
}

/** 스캔 판정 집계(scanSummary) → 보고 한 줄 — 범례와 같은 라벨(kindLabel)만 쓴다. */
export function scanCueSummary(s) {
  const parts = [`${s.total}점 — ${kindLabel("ok")} ${s.ok}`];
  for (const { kind, n } of s.byKind) parts.push(`${kindLabel(kind)} ${n}`);
  return parts.join(" · ");
}
