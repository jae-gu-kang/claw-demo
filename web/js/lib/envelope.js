/** 엔벨로프 lib (01 §2.6) — 설계 엔벨로프 응답의 표현 변환 (뷰·캔버스와 분리, 테스트 대상).

수치·합성·귀속은 전부 엔진(design_envelope·envelope_verdict) — 여기서는
다각형 조립·구간 병합·판정 셀 분류·프리필 판단만. 서버가 준 필드를 다시
계산하지 않는다. 모르는 귀속·사유 코드는 코드 그대로 표시한다 (조용히
숨기면 엔진이 코드를 늘렸을 때 화면이 거짓말을 한다).
*/

import { niceTicks, STATUS } from "./plot.js";

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
    const source = side === "bottom"
      ? (Math.abs(alt - bounds.alt_min_used) < EPS
        ? (bounds.alt_min != null ? "ops_alt_min" : "display_min")
        : "natural_floor")
      : (Math.abs(alt - bounds.alt_max_used) < EPS
        ? (bounds.alt_max_is_display_default ? "display_max" : "ops_alt_max")
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
  not_converged: { label: "트림 미수렴", color: STATUS.na },
  alpha_margin: { label: "α 여유 부족 (실속 근접)", color: STATUS.bad },
  saturated_throttle_high: { label: "스로틀 상한 포화 (추진 한계)", color: "#ff9500" },
  saturated_de: { label: "타면 포화", color: "#ffcc00" },
  saturated_throttle_low: { label: "스로틀 하한 포화 (아이들)", color: "#5ac8fa" },
};

export const kindLabel = (kind) => KIND_META[kind]?.label ?? kind;
export const kindColor = (kind) => KIND_META[kind]?.color ?? "#8e8e93";

/** 스캔 entries → 판정 셀 {mach, alt, fuel, ok, kind}.
 * kind는 엔진 reasons의 첫 항목(우선순위 대표 — points.envelope_verdict 순서).
 * 실패인데 사유가 비면 "unknown" — 성공으로 위장하지 않는다. */
export function scanCells(entries) {
  return entries.map((e) => ({
    mach: e.trim.case.mach,
    alt: e.trim.case.alt,
    fuel: e.trim.case.fuel,
    ok: e.verdict.ok === true,
    kind: e.verdict.ok === true ? "ok" : (e.verdict.reasons?.[0] ?? "unknown"),
    // 대표 kind는 우선순위 첫 사유뿐 — 스로틀 포화(3순위)는 미수렴에 가려진다.
    // 추력 대리 경계가 그 가려진 사유를 봐야 하므로 전량을 함께 싣는다.
    reasons: e.verdict.reasons ?? [],
  }));
}

/** 판정 셀 → 추력 대리 경계 [{alt, mach, side}] — 고도별 포화/비포화 전이점.
 *
 * 교과서 엔벨로프의 "available thrust limit"에 대응하지만 **추력 모델이 아니다**:
 * 전용 추력 모델은 부재이고(01 §2.6 [TBD] — T = max_thrust×δt로 마하·고도 무관),
 * 여기 쓰는 것은 트림이 실제로 스로틀 상한에 부딪힌 지점, 즉 01 §2.6이 정한
 * "추진 한계는 수평비행 트림의 스로틀 상한 포화로만 표면화한다"의 데이터다.
 * 해석 곡선이 아니라 측정점이므로 **스캔 격자 해상도가 곧 경계 해상도**다.
 *
 * side는 포화가 어느 쪽에 있는지다 — "hi"는 빨라서 모자란 것(항력), "lo"는 느려서
 * 모자란 것(유도항력이 커지는 항력곡선 backside). 둘 다 실제로 나오므로 한쪽을
 * 가정하면 안 된다: 추력을 낮춘 실측에서 포화가 전부 저마하 쪽에 몰렸고, 그때
 * "최저 포화 마하"를 경계라 부르면 스캔의 왼쪽 끝을 경계라고 우기게 된다.
 * 전이가 없는 행(전부 포화/전부 비포화)은 낸다 — 가장자리를 경계로 지어내지 않는다.
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
    for (let i = 0; i + 1 < row.length; i += 1) {
      const a = row[i], c = row[i + 1];
      if (sat(a) === sat(c)) continue;
      const at = sat(a) ? a : c;               // 전이의 포화 쪽 셀이 경계점
      out.push({
        alt,
        mach: at.mach,
        side: sat(a) ? "lo" : "hi",            // 느린 쪽 포화면 저속, 빠른 쪽이면 고속 한계
        provisional: unconverged(at),
      });
    }
  }
  return out;
}

const KIND_ORDER = [
  "not_converged", "alpha_margin", "saturated_throttle_high",
  "saturated_de", "saturated_throttle_low",
];

/** 판정 셀 → 종류별 집계 {total, ok, byKind: [{kind, n}]} — byKind는 실패만,
 * 엔진 우선순위 순. 미정의 코드는 뒤에 그대로 덧붙인다. */
export function scanSummary(cells) {
  const counts = new Map();
  for (const c of cells) counts.set(c.kind, (counts.get(c.kind) ?? 0) + 1);
  const byKind = [];
  for (const k of KIND_ORDER) {
    if (counts.has(k)) byKind.push({ kind: k, n: counts.get(k) });
  }
  for (const [k, n] of counts) {
    if (k !== "ok" && !KIND_ORDER.includes(k)) byKind.push({ kind: k, n });
  }
  return { total: cells.length, ok: counts.get("ok") ?? 0, byKind };
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

/** 도표의 마하 창 {xMin, xMax} — 캔버스와 캡션이 **같은 창**을 봐야 "창 밖"이 한 말이
 * 된다. 창은 DB 하한·합성 하한의 최소와 M_D·합성 상한의 최대에 여백(pad)을 더한 것. */
export function machWindow(bounds, region, pad = 0.03) {
  return {
    xMin: Math.min(bounds.db_mach[0], ...region.mach_lo) - pad,
    xMax: Math.max(bounds.mach_d, ...region.mach_hi) + pad,
  };
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
