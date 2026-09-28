/** 재생 유틸 (02 §8 7단계) — stride 산정·모드 구간·극값 (순수 로직, 테스트 대상). */

import { GOHEUNG } from "./site.js";

export function strideFor(nTotal, target = 1500) {
  return Math.max(1, Math.ceil(nTotal / target));
}

/** 엔벨로프 플래그 이름(한국어) — 엔진 flags 키와 1:1 (simulator._envelope). */
export const FLAG_LABEL = {
  alpha: "α", beta: "β", mach: "마하", altitude: "고도",
};

/** 실제로 뜬 플래그 이름만 나열 — any_flag 하나로 뭉뚱그리면 기준면 이탈(고도)이
DB 유효범위 이탈로 오독된다. 미정의 키는 원래 이름으로 통과(엔진 확장에 안전). */
export function flaggedNames(env) {
  const hit = Object.entries(env?.flags ?? {})
    .filter(([, arr]) => Array.isArray(arr) && arr.some(Boolean))
    .map(([k]) => FLAG_LABEL[k] ?? k);
  return hit.length ? hit.join("·") : "—";
}

/** 모드 문자열 시계열 → 연속 구간 [{mode, i0, i1}] (i1 배타) — 배경 밴드용. */
export function modeSpans(modes) {
  const spans = [];
  for (let i = 0; i < modes.length; i += 1) {
    if (!spans.length || spans[spans.length - 1].mode !== modes[i]) {
      if (spans.length) spans[spans.length - 1].i1 = i;
      spans.push({ mode: modes[i], i0: i, i1: modes.length });
    }
  }
  return spans;
}

/** null(NaN 직렬화) 무시 극값 — 전부 null이면 [0, 1] 안전 기본. */
export function extent(arr) {
  let lo = Infinity;
  let hi = -Infinity;
  for (const v of arr) {
    if (typeof v !== "number") continue;
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  return lo <= hi ? [lo, hi] : [0, 1];
}

/** 이 런을 난 기체의 문서 좌표 {id, variant, revision, name} — 결과 meta.profile(서버 refs.profile_echo).
 *  기록이 없으면 null.
 *
 * 발사하중 한계(n_x_launch)·표시 모델처럼 **그 런의 기체 문서**에서 읽어야 하는 값이 이 좌표로 문서를
 * 받는다 — 지금 헤더에서 고른 기체가 아니다. 결과는 다른 기체(또는 그 뒤에 고친 문서)로 돌았을 수
 * 있고, 그때 지금 고른 문서로 판정하면 화면이 남의 한계로 이 런을 잰다. */
export function runProfileRef(meta) {
  const p = meta?.profile;
  if (!p || typeof p.id !== "string" || p.id === "") return null;
  return {
    id: p.id,
    variant: typeof p.variant === "string" && p.variant !== "" ? p.variant : null,
    // 리비전이 없으면(해석기를 안 거친 조립) 최신 문서를 받는다 — 경로가 그 사실을 드러낸다
    revision: Number.isInteger(p.revision) && p.revision >= 0 ? p.revision : null,
    name: typeof p.name === "string" && p.name !== "" ? p.name : p.id,
  };
}

/** 그 문서를 받는 API 경로 — 리비전을 알면 **그 리비전**(런 뒤에 문서를 고쳤어도 런이 쓴 값). */
export function profileDocPath(ref) {
  return `/profiles/${encodeURIComponent(ref.id)}${ref.revision == null ? "" : `?revision=${ref.revision}`}`;
}

/** 화면에 적는 기체 이름표 — "이름 / 형상 변형 · r리비전". */
export function refLabel(ref) {
  if (!ref) return "기체 미상";
  return `${ref.name}${ref.variant ? ` / ${ref.variant}` : ""}${ref.revision == null ? "" : ` · r${ref.revision}`}`;
}

/** 런의 **적용 문서**(형상 변형 반영) → 발사하중 한계 {nx, source} — 판정은 landingSummary가 한다.
 *  문서에 값이 없으면(null) nx는 null이다 — 없는 한계를 지어내지 않는다. */
export function launchLimitFrom(doc, ref) {
  const v = doc?.structural?.n_x_launch;
  return { nx: typeof v === "number" && Number.isFinite(v) && v > 0 ? v : null, source: refLabel(ref) };
}

/** 레일 가속 [g] — 레일 축 순가속도 신호(launch_gx)의 최대. 신호가 없으면 null, 레일 위 표본이 없으면 0.
 *  중력 성분이 빠진 값이라 하중배수가 아니다 — 판정은 launchLoad(gx + sin γ)로 한다.
 *  레일 위에서는 상수라(엔진 LaunchRail.launch_gx) stride로 솎인 재생 응답에서도 첫 표본이 그 값을 잡는다. */
export function launchGx(body) {
  const g = body?.signals?.launch_gx;
  return Array.isArray(g) ? g.reduce((m, x) => (typeof x === "number" && x > m ? x : m), 0) : null;
}

/** 발사 축방향 하중배수 [g] — n_x = gx + sin γ를 {gx, grav, nx}로. 레일 위 표본이 없으면(신호 없음·gx 0) null.
 *
 * launch_gx는 레일 축 **순**가속도 ÷ g다(엔진 LaunchRail.accel — 카타펄트 추력·중력의 레일 축 성분·항력이
 * 이미 합쳐진 값). 구조 한계 n_x_launch가 재는 것은 동체 x축 비력(가속 − 중력)이고, 레일 위에서는 동체
 * x축이 곧 레일 축이라(자세가 θ = γ로 물림) 그 성분이 gx + sin γ다(γ = 레일 앙각, 상방 +). 순가속도만
 * 견주면 앙각만큼 낙관이다 — 예제(앙각 15°·레일 10 m·이탈 33.3 m/s)는 가속 5.65 g + 중력 0.26 g = 5.91 g.
 *
 * 앙각은 **그 런이 실제로 쓴 레일**(결과 meta.launch — 서버가 요청의 레일을 동봉)에서 읽는다 — 문서의
 * ground.rail은 칸의 기본값이라 그 런이 바꿔 돌았을 수 있다. 앙각이 없으면 grav·nx는 null이다(0으로
 * 메우면 순가속도를 하중배수라 부르게 된다). */
export function launchLoad(body) {
  const gx = launchGx(body);
  if (!gx) return null;
  const g = body?.meta?.launch?.elev_angle;
  const grav = typeof g === "number" && Number.isFinite(g) ? Math.sin(g) : null;
  return { gx, grav, nx: grav === null ? null : gx + grav };
}

/** 레일 이탈 행의 판정 — 축방향 하중배수 n_x(launchLoad)를 그 런의 문서 한계 n_x_launch와 견준다.
 *
 * 한계를 **대조하지 않았으면**(호출측이 안 넘김) · 문서를 못 받았으면 · 문서에 값이 없으면 · 결과에 레일
 * 앙각이 없으면 판정 불가다 — 넷은 사용자가 할 일이 달라 사유를 가른다. 구조 한계표의 n_limit_pos는 Nz라
 * 이 축(동체 x축)을 판정하지 못한다(엔진 plant/ground.py LaunchRail.launch_gx가 판정 기준으로 n_x_launch를
 * 지목한다). 적는 문장은 합과 두 항을 함께 — 신호(launch_gx)·다른 화면이 말하는 가속과 대조되게. */
function launchVerdict(load, limit) {
  const f = (v) => v.toFixed(2);
  const text = load.nx === null
    ? `레일 가속 ${f(load.gx)} g`
    : `축방향 하중배수 ${f(load.nx)} g (레일 가속 ${f(load.gx)} g ${load.grav < 0 ? "−" : "+"} 중력 성분 ${f(Math.abs(load.grav))} g)`;
  if (limit === undefined) {
    return { note: `${text} — 종방향 발사하중 한계(structural.n_x_launch)와 대조하지 않았다, 판정 불가`, unjudged: true };
  }
  if (limit === null || typeof limit !== "object" || typeof limit.error === "string") {
    const why = typeof limit?.error === "string" ? limit.error : "한계를 받지 못했다";
    return { note: `${text} — ${why}, 판정 불가`, unjudged: true };
  }
  if (typeof limit.nx !== "number") {
    return {
      note: `${text} — 기체 문서(${limit.source})에 종방향 발사하중 한계(structural.n_x_launch)가 없어 판정 불가`,
      unjudged: true,
    };
  }
  if (load.nx === null) {
    return {
      note: `${text} — 결과에 레일 앙각(meta.launch.elev_angle)이 없어 중력 성분(sin γ)을 더하지 못했다, 판정 불가`,
      unjudged: true,
    };
  }
  const src = `(${limit.source} structural.n_x_launch)`;
  return load.nx > limit.nx
    ? { note: `${text} > 한계 ${limit.nx} g ${src} — 한계를 넘었다`, over: true, overLabel: "발사하중 초과" }
    : { note: `${text} ≤ 한계 ${limit.nx} g ${src}`, pass: true, passLabel: "한계 안" };
}

/** 활주로 가장자리 여유 [m] — 횡편차 한계 = 활주로 반폭 − 이 값.
 *
 * 자동착륙 성능 입증 기준(EASA CS-AWO)이 45 m 활주로에서 **외측 착륙장치가 중심선에서 21 m 밖**에 닿는 것을
 * 한계 사건으로 둔다 — 반폭 22.5 m에서 1.5 m 안쪽이다. 여기 판정하는 것은 무게중심 궤적이라(착륙장치 위치는
 * 결과에 없다) 착륙장치 반궤간만큼 낙관이다 — 소형 무인기는 1 m 안팎이라 여유 안에 들지만 여유를 그만큼 덜
 * 남긴다. 그리고 런 하나의 결정론적 판정이지 산포(10⁻⁶) 입증이 아니다. */
export const RUNWAY_EDGE_MARGIN_M = 1.5;

const wrapPi = (a) => Math.atan2(Math.sin(a), Math.cos(a));

/** 그 런의 활주로 폭 → landingSummary의 `runwayWidth` ({width, source} | {error}) — 던지지 않는다.
 *
 * 폭은 결과에 없다(서버는 활주로 방위·길이·표고만 받아 meta.runway로 돌려준다). 그래서 시험장 제원(`site` —
 * lib/site.js GOHEUNG 꼴 {runwayWidthM, runwayLengthM, runwayHeadingRad})에서 받되, 그 런이 **그 활주로**를 썼을
 * 때만 준다 — 폼의 방위·길이 칸을 고친 런은 다른 활주로라, 시험장 폭을 빌려 쓰면 남의 기하로 판정하게 된다.
 * 제원에 폭이 없거나 · 가장자리 여유의 두 배 이하라 한계가 서지 않거나 · 런의 활주로가 다르면 사유를
 * 돌려준다(행은 판정 불가로 선다 — 없는 폭을 지어내지 않는다). */
export function runwayWidthFor(runway, site, source = "시험장 제원") {
  const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);
  const w = num(site?.runwayWidthM);
  if (w === null || w <= 0) return { error: `${source}에 활주로 폭이 없다` };
  if (w <= 2 * RUNWAY_EDGE_MARGIN_M) {
    return { error: `${source}의 활주로 폭 ${w} m가 가장자리 여유 ${RUNWAY_EDGE_MARGIN_M} m의 두 배 이하라 한계가 서지 않는다` };
  }
  const hdg = num(runway?.heading);
  const len = num(runway?.length);
  const sh = num(site?.runwayHeadingRad);
  const sl = num(site?.runwayLengthM);
  // 허용차는 표기 반올림만큼 — 폼이 같은 상수를 문자열로 들고 있다가 되돌려 받는다(simrequest.js RUNWAY_HDG)
  if (hdg === null || len === null || sh === null || sl === null
    || Math.abs(len - sl) > 0.5 || Math.abs(wrapPi(hdg - sh)) > 1e-4) {
    return {
      error: `이 런의 활주로(방위 ${hdg ?? "?"} rad · 길이 ${len ?? "?"} m)가 ${source}의 활주로`
        + `(방위 ${sh ?? "?"} rad · 길이 ${sl ?? "?"} m)와 달라 그 폭을 쓸 수 없다`,
    };
  }
  return { width: w, source };
}

/** 그 런의 활주로 폭을 고흥 시험장 제원(lib/site.js GOHEUNG)에서 — runwayWidthFor 그대로. 착륙 요약을 내는 화면
 *  (시뮬 탭·쇼케이스 보고, 가이드 투어 마무리, 결과 브리핑)이 폭을 받는 **한 자리**다. 제원과 출처 이름표를 화면마다
 *  따로 적으면 같은 런을 두 화면이 다른 문장으로 판정하게 된다 — 발사하중 한계를 views/sim.js launchLimitOf 한
 *  곳에서 받는 것과 같은 규약이다. */
export const siteRunwayWidth = (runway) => runwayWidthFor(runway, GOHEUNG, "고흥 시험장 제원");

/** 횡편차 판정 — 접지·정지가 **같은 자**를 쓴다(따로 적으면 두 행이 다른 기하를 말하게 된다).
 *
 * |횡편차| > 길이면 폭을 몰라도 옆이다(활주로가 자기 길이보다 넓을 수는 없다). 그 밖은 폭이 있어야
 * 판정한다: 한계 = 반폭 − 가장자리 여유(RUNWAY_EDGE_MARGIN_M). 폭을 대조하지 않았거나(호출측이 안 넘김)
 * 받지 못했으면 사유를 달고 판정 불가 — 발사하중 행(launchVerdict)과 같은 규약이다.
 * 돌려주는 것: why(접지 횡편차 행의 사유 — 한계의 근거까지) · short(정지 행에 붙는 짧은 꼴) + 표지. */
function lateralVerdict(cross, len, runwayWidth) {
  const a = Math.abs(cross);
  const m1 = (x) => (Math.round(x * 10) / 10).toLocaleString("ko-KR");
  if (a > len) {
    const lenM = Math.round(len).toLocaleString("ko-KR");
    return {
      why: `활주로 길이 ${lenM} m보다 멀다 — 폭을 몰라도 활주로 옆이다`,
      short: `> 활주로 길이 ${lenM} m`,
      over: true, overLabel: "활주로 옆",
    };
  }
  if (runwayWidth === undefined) {
    return { why: "활주로 폭과 대조하지 않았다, 판정 불가", unjudged: true };
  }
  if (runwayWidth === null || typeof runwayWidth !== "object" || typeof runwayWidth.width !== "number") {
    return { why: `${runwayWidth?.error ?? "활주로 폭을 받지 못했다"}, 판정 불가`, unjudged: true };
  }
  const half = runwayWidth.width / 2;
  const lim = half - RUNWAY_EDGE_MARGIN_M;
  const basis = `한계 ${m1(lim)} m (${runwayWidth.source} 활주로 폭 ${m1(runwayWidth.width)} m의 반폭 ${m1(half)} m`
    + ` − 가장자리 여유 ${m1(RUNWAY_EDGE_MARGIN_M)} m)`;
  return a <= lim
    ? { why: `|횡편차| ≤ ${basis}`, short: `≤ 한계 ${m1(lim)} m`, pass: true, passLabel: "폭 안" }
    : {
      why: `|횡편차| > ${basis}`, short: `> 한계 ${m1(lim)} m`,
      over: true, overLabel: a > half ? "활주로 옆" : "가장자리 근접",
    };
}

/** 재생 응답 → 이착륙 요약 [{label, value, note}] — 단계가 없으면 **행 자체가 없다**.
 *
 * 0으로 채우면 착륙하지 않은 런이 "접지 강하율 0 = 완벽한 착륙"으로 읽힌다.
 * 발사 축방향 하중배수(레일 가속 + 중력 성분 — launchLoad)는 그 런의 기체 문서 한계(`opts.launchLimit` —
 * {nx, source} | {error} — launchLimitFrom)와 견준다. 한계가 없거나 대조하지 않았으면 값과 함께 "판정 불가"를
 * 낸다 — 판정 불가를 통과로 위장하지
 * 않는다는 규약이 화면에 나오는 자리다. 행의 표지: unjudged(판정 불가) · over(+overLabel, 초과·밖) ·
 * pass(+passLabel, 기준 안).
 * 접지·정지 지점의 횡편차는 활주로 폭(`opts.runwayWidth` — {width, source} | {error} — runwayWidthFor)의
 * 반폭에서 가장자리 여유를 뺀 한계와 견준다. 안 넘기면 같은 규약으로 판정 불가다.
 */
export function landingSummary(body, { launchLimit, runwayWidth } = {}) {
  const ph = body?.meta?.phases;
  const sig = body?.signals ?? {};
  const t = body?.t ?? [];
  if (!ph) return [];
  const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);
  const rows = [];
  // 그 사건의 시각이 있고 재생 표본이 있는가 — 시각은 엔진이 전 해상도에서 잰 meta.phases 값이다
  const atEvent = (tv) => typeof tv === "number" && Number.isFinite(tv) && t.length > 0;
  // 사건 시각의 위치 {pn, pe} — 그 시각을 끼는 **두 재생 표본 사이를 선형 보간**한다.
  //
  // 재생 응답은 stride로 솎여 있다. 가장 가까운 표본 하나의 위치를 쓰던 때는 접지·정지 지점이 표본 한 칸
  // (쇼케이스 기체 0.32 s × 40 m/s ≈ 13 m · 예제 기체 0.5 s × 33 m/s ≈ 16 m)씩 뛰었다 — 활주로 축 보정
  // (2026-09-27) 뒤 접지가 실제로는 0.09 s(3.4 m) 옮겼을 뿐인데 화면은 +340 → +320 m를 말했다.
  // 사건 시각이 재생 구간 밖이면 끝 표본(재생이 거기서 끝났다), 표본과 겹치면 그 표본만 본다.
  // 끼는 두 표본 중 하나라도 결측이면 null — 한쪽 표본으로 눙치면 그 한 칸 오차가 되돌아온다.
  const posAt = (tv) => {
    if (!atEvent(tv)) return null;
    const pick = (i) => {
      const pn = num(sig.pn?.[i]);
      const pe = num(sig.pe?.[i]);
      return pn === null || pe === null ? null : { pn, pe };
    };
    const last = t.length - 1;
    if (!(tv > t[0])) return pick(0);
    if (!(tv < t[last])) return pick(last);
    let i1 = 1;
    while (i1 < last && t[i1] < tv) i1 += 1;
    if (t[i1] === tv) return pick(i1);
    const a = pick(i1 - 1);
    const b = pick(i1);
    const span = t[i1] - t[i1 - 1];
    if (a === null || b === null || !(span > 0)) return null;
    const w = (tv - t[i1 - 1]) / span;
    return { pn: a.pn + w * (b.pn - a.pn), pe: a.pe + w * (b.pe - a.pe) };
  };

  if (typeof ph.launch_exit_t === "number") {
    const load = launchLoad(body);
    // gx 0은 "하중 없음"이 아니라 미계측이다(레일 위 표본이 없던 결과) — 판정하지 않는다
    rows.push({
      label: "레일 이탈",
      value: `${ph.launch_exit_t.toFixed(3)} s`,
      ...(load ? launchVerdict(load, launchLimit) : { note: "사출 하중 미계측", unjudged: false }),
    });
  }
  const tdAt = atEvent(ph.touchdown_t);
  if (tdAt) {
    // 강하율·속도는 **엔진이 전 해상도에서 잰 값**을 그대로 쓴다. 여기서 신호로
    // 다시 계산하면 재생 응답이 stride로 솎여 있어 다른 수가 나온다 — 접지 직후
    // 승강률은 0.02 s에 −0.98 → −0.83으로 움직이고, 라이브에서 실제로 −0.98을
    // −0.74로 표시했다. 화면이 조용히 다른 접지를 말하는 자리였다.
    const hdot = num(ph.td_sink_rate);
    const V = num(ph.td_speed);
    rows.push({
      label: "접지",
      value: `${ph.touchdown_t.toFixed(2)} s`,
      note: [
        hdot === null ? "강하율 미계측" : `강하율 ${hdot.toFixed(2)} m/s`,
        V === null ? null : `속도 ${V.toFixed(1)} m/s`,
      ].filter(Boolean).join(" · "),
    });
  }
  // 접지 **지점** — 거리만으로는 활주로에 내렸는지 알 수 없다.
  //
  // 아래 "정지" 행은 접지→정지 직선거리를 활주로 길이와 견주는데, 그것은 **미끄럼이
  // 짧다**는 뜻일 뿐이다. 기본 미션은 발사대에서 떠서 7 km 북쪽에 내리는데도 그 행만
  // 보면 "869 m / 활주로 1205 m"라 활주로에 선 것처럼 읽혔다.
  //
  // 활주로 기하는 화면과 같은 규약을 쓴다 — 원점에서 heading 방향 length 구간
  // (world/src/core/runway.ts runwayDrawing — 옛 renderer-three.js에서 왔다).
  // 두 축을 **행 하나씩** 판정한다:
  //   접지 지점  — 축방향이 0~length 안인가 (폭 없이 단정된다)
  //   접지 횡편차 — |횡편차|가 반폭 − 가장자리 여유 안인가 (폭이 있어야 한다 — lateralVerdict).
  //               단 |횡편차| > length면 폭을 몰라도 옆이다(활주로가 자기 길이보다 넓을 수는 없다)
  // 종전에는 횡편차를 접지 지점 사유에 적기만 하고 판정하지 않아(폭이 결과에 없다), 장주가
  // 중심선에 못 들어와 20 m 옆에 내린 쇼케이스 기체가 축방향만 보고 조용히 넘어갔다.
  //
  // 방위·길이가 없으면 **행 자체를 내지 않는다**. 방위를 0으로 메우면 "활주로 축"을
  // 지어내고 방위를 알 때와 똑같은 확신으로 거리를 찍게 되며, 길이 0은 거의 모든
  // 접지를 "밖"으로 만든다 — 이 파일의 "0으로 채우지 않는다" 규약과 같은 자리다.
  const rw = body?.meta?.runway;
  // 활주로 축 좌표 — 접지와 정지가 **같은 자를 쓴다**. 정지 판정을 따로 적으면
  // 두 행이 다른 기하를 말하게 된다(한쪽만 고치는 일이 생긴다)
  const rwFix = (pos) => {
    if (pos === null || !rw) return null;
    const hdg = num(rw.heading);
    const len = num(rw.length);
    if (hdg === null || len === null || len <= 0) return null;
    const { pn, pe } = pos;
    const along = pn * Math.cos(hdg) + pe * Math.sin(hdg);
    const cross = -pn * Math.sin(hdg) + pe * Math.cos(hdg);
    return { along, cross, len, alongOut: along < 0 || along > len, lat: lateralVerdict(cross, len, runwayWidth) };
  };
  // **축방향은 10 m 단위다.** 재생 응답은 stride로 솎여 있어 표본 간격이 접지 속도에서 10 m를 넘지만
  // (쇼케이스 기체 0.32 s × 40 m/s ≈ 13 m · 예제 기체 0.5 s × 33 m/s ≈ 16 m), 위치는 사건 시각에서 두 표본
  // 사이를 보간하므로(posAt) 그 간격이 오차가 아니다 — 기본 미션의 착륙 창(접지 30 s 전 ~ 정지 1 s 뒤)을 전
  // 해상도와 대조하면 보간 오차가 최대 0.07 m(쇼케이스 기체)·0.13 m(예제 기체), 가장 가까운 표본은 6.7·8.2 m였다.
  // 그래도 자릿수를 올리지 않는 것은 판정(0~길이)에 그 자릿수가 필요 없고, 접지 지점은 미션의 작은 섭동에도
  // 미터 단위로 움직여서다(마지막 WP를 1 m 옮기면 3.4 m, 항법 잡음 시드를 바꾸면 1 m 안팎 — 활주로 축 보정 때
  // 잰 값). 1 m 단위로 내면 그 흔들림이 런 사이의 차이처럼 읽힌다.
  // **횡편차는 1 m 단위다** — 접지·정지 무렵 기체는 활주로 방위로 날고 있어 표본 하나(0.5 s) 사이에
  // 옆으로 움직이는 양이 1 m보다 훨씬 작다(쇼케이스 기체 실측: 플레어 20 s 동안 0.1 m 안팎). 10 m로
  // 뭉개면 한계(수십 m) 근처의 판정이 읽히지 않는다.
  // 로캘을 못박는다(world.js와 같은 규약). 실행 환경 기본 로캘도 쉼표를 쓰는
  // 경우가 많아 **테스트로는 구별되지 않는다** — 변이시험에서 0건이 뜬다.
  const r10 = (x) => Math.round(x / 10) * 10;
  const signed = (x) => `${x >= 0 ? "+" : ""}${r10(x).toLocaleString("ko-KR")}`;
  // −0.3이 "-0"이 되지 않게 0으로 접는다
  const signed1 = (x) => {
    const r = Math.round(x) || 0;
    return `${r > 0 ? "+" : ""}${r.toLocaleString("ko-KR")}`;
  };
  const tdPos = posAt(ph.touchdown_t);
  if (tdAt && rw) {
    const fix = rwFix(tdPos);
    if (fix !== null) {
      const { along, cross, len, alongOut, lat } = fix;
      const span = `활주로 구간(0~${Math.round(len).toLocaleString("ko-KR")} m)`;
      rows.push({
        label: "접지 지점",
        value: `활주로 축 ${signed(along)} m`,
        // 축방향만 말한다 — 「구간 안」은 활주로에 섰다는 뜻이 아니다(횡방향은 다음 행)
        note: alongOut ? `${span} 밖이다` : `${span} 안 — 횡방향은 접지 횡편차 행`,
        over: alongOut,
        // 시단 **앞**에 내린 경우도 있어 "활주로 초과"는 틀린 말이 된다
        overLabel: along < 0 ? "시단 못 미침" : "활주로 밖",
        ...(alongOut ? {} : { pass: true, passLabel: "축 구간 안" }),
      });
      rows.push({
        label: "접지 횡편차",
        value: `${signed1(cross)} m`,
        note: lat.why,
        over: Boolean(lat.over),
        ...(lat.over ? { overLabel: lat.overLabel } : {}),
        ...(lat.pass ? { pass: true, passLabel: lat.passLabel } : {}),
        ...(lat.unjudged ? { unjudged: true } : {}),
      });
    }
  }

  if (atEvent(ph.stop_t) && tdAt) {
    // 거리도 두 사건 시각의 보간 위치로 잰다 — 지점 행과 같은 위치다. 어느 한쪽 위치가 결측이면 거리를
    // 지어내지 않는다(종전에는 결측을 0으로 메워 원점까지의 거리를 「접지→정지」로 말할 수 있었다)
    const stopPos = posAt(ph.stop_t);
    const dist = tdPos && stopPos ? Math.hypot(stopPos.pn - tdPos.pn, stopPos.pe - tdPos.pe) : null;
    const len = body?.meta?.runway?.length;
    const tooFar = typeof len === "number" && dist !== null && dist > len;
    // **미끄럼이 짧은 것과 활주로에 선 것은 다르다.** 종전에는 거리만 견주어,
    // 7 km 북쪽 논에 내린 기본 미션이 "869 m / 활주로 1205 m"라 통과처럼 읽혔다.
    // 이제 정지 **지점**을 접지와 같은 자로 재서 그 구분을 낸다 — 축방향과 횡방향 둘 다.
    const fix = rwFix(stopPos);
    let where = "";
    let flags = {};
    if (fix !== null && fix.alongOut) {
      // 접지 지점 행과 **같은 자릿수**로 낸다 (위 r10 주석이 정본)
      where = ` · 정지 지점이 활주로 구간 밖이다 (축 ${r10(fix.along).toLocaleString("ko-KR")} m)`;
      flags = { overLabel: "활주로 밖 정지" };
    } else if (fix !== null && fix.lat.over) {
      where = ` · 정지 지점 횡편차 ${signed1(fix.cross)} m ${fix.lat.short}`;
      flags = { overLabel: `${fix.lat.overLabel} 정지` };
    } else if (fix !== null && fix.lat.pass) {
      where = ` · 정지 지점 활주로 안 (횡편차 ${signed1(fix.cross)} m ${fix.lat.short})`;
      if (!tooFar) flags = { pass: true, passLabel: "활주로 안" };
    } else if (fix !== null) {
      where = ` · 정지 지점은 구간 안, 횡편차 ${signed1(fix.cross)} m — ${fix.lat.why}`;
      if (!tooFar) flags = { unjudged: true };
    }
    rows.push({
      label: "정지",
      value: `${ph.stop_t.toFixed(2)} s`,
      note: (dist === null ? "접지→정지 직선거리 미계측" : `접지→정지 직선거리 ${Math.round(dist)} m`)
        + (typeof len === "number"
          // 마크다운 **는 여기서 글자 그대로 나온다 — note는 텍스트 노드로 들어간다
          // (views/sim.js). 강조는 이 행이 이미 내는 over 배지가 맡는다
          ? ` / 활주로 ${Math.round(len)} m${tooFar ? " — 넘어섰다" : ""}` : "")
        + where,
      over: tooFar || Boolean(flags.overLabel),
      // 키를 `undefined`로 두지 않는다 — 있는 키와 없는 키의 구분이 곧 계약이다
      ...flags,
    });
  }
  return rows;
}

/** 착륙 요약 행 → 한 줄 — 쇼케이스 진행기 보고의 summary(views/sim.js). 행의 값·사유를 **그대로**
 *  잇는다(새 문구를 짓지 않는다). 접지가 없으면 null — 호출측이 모드 체인으로 대신 말한다. */
export function landingLine(rows) {
  const by = (label) => (rows ?? []).find((r) => r.label === label);
  const td = by("접지");
  if (!td) return null;
  const parts = [`접지 ${td.value}${td.note ? ` (${td.note})` : ""}`];
  const spot = by("접지 지점");
  if (spot) parts.push(`${spot.value}${spot.over ? ` — ${spot.overLabel}` : ""}`);
  // 횡편차는 축방향과 따로 판정된다 — 한 줄에서 빠지면 요약이 축방향만으로 「섰다」고 읽힌다
  const lat = by("접지 횡편차");
  if (lat) parts.push(`횡편차 ${lat.value}${lat.over ? ` — ${lat.overLabel}` : ""}`);
  const stop = by("정지");
  if (stop) {
    // 정지 행 사유의 첫 마디가 거리다(접지→정지 직선거리 / 활주로 길이) — 지점 판정은 표지로
    const dist = String(stop.note ?? "").split(" · ")[0];
    parts.push(`정지 ${stop.value}${dist ? ` (${dist})` : ""}${stop.over ? ` — ${stop.overLabel ?? "활주로 초과"}` : ""}`);
  }
  const rail = by("레일 이탈");
  if (rail?.over) parts.push(rail.overLabel);
  else if (rail?.pass) parts.push(`발사하중 ${rail.passLabel}`);
  return parts.join(" · ");
}

/** 정지 뒤 t_end까지 남은 구간 — {stopT, tEnd, idle, frac}, 정지 단계가 없거나 t_end를 모르면 null.
 *
 * 엔진은 "stopped" 모드에서도 t_end까지 적분한다(모드 표의 끝 행 time_ge 1e9) — 그 구간은 선 기체를
 * 계산할 뿐이라 결과 크기·계산 시간만 늘린다. 예제 기체 기본 미션 실측: 512.7 s에 서고 t_end 750 s까지
 * (32 %, 전 해상도 저장 약 110 MB). 절단된 런은 t_end까지 가지 않았으므로 null이다. */
export function idleTail(body) {
  const meta = body?.meta ?? {};
  const stopT = meta.phases?.stop_t;
  const tEnd = meta.t_end;
  if (meta.aborted) return null;
  if (typeof stopT !== "number" || !Number.isFinite(stopT)) return null;
  if (typeof tEnd !== "number" || !Number.isFinite(tEnd) || tEnd <= 0 || tEnd < stopT) return null;
  const idle = tEnd - stopT;
  return { stopT, tEnd, idle, frac: idle / tEnd };
}

/** 정지 뒤 구간 안내 — 크면(구간의 20 % 초과이면서 30 s 초과) 문장, 아니면 null.
 *  기준은 표시 문턱이다(계산에 쓰이지 않는다): 템플릿이 정지 + 20 s 여유를 주는 기체는 걸리지 않는다. */
export function idleTailNote(body) {
  const tail = idleTail(body);
  if (!tail || tail.frac <= 0.2 || tail.idle <= 30) return null;
  return `정지(${tail.stopT.toFixed(1)} s) 뒤 t_end ${tail.tEnd.toFixed(0)} s까지 ${tail.idle.toFixed(0)} s`
    + `(전 구간의 ${Math.round(tail.frac * 100)} %)는 선 기체를 계산했습니다 — t_end를 정지 시각에 여유를 더한 값으로 `
    + "줄이면 결과 크기와 계산 시간이 그만큼 줄어듭니다.";
}

/** 순수추적으로 못 잡고 넘어간 웨이포인트 안내 — 없으면 null.
 *
 * 경로가 끝난 것과 **계획대로 난 것**은 다르다. 엔진 안전망(궤도 고착 탈출)이
 * 미션을 끝내 주지만, 그 점을 실제로는 지나가지 못했다는 사실이 화면에 없으면
 * 사용자는 자기가 찍은 경로를 날았다고 읽는다 (engine guidance/path.py §궤도 고착).
 *
 * 인덱스는 엔진이 0 기준으로 싣고 화면은 **1 기준**으로 말한다 — 웨이포인트 표의
 * 행 번호와 같은 어휘여야 사용자가 어느 줄인지 바로 찾는다.
 */
export function pathEscapeNote(body) {
  const esc = body?.meta?.path_escapes;
  if (!Array.isArray(esc) || !esc.length) return null;
  const names = esc.map((i) => Number(i) + 1).join(", ");
  return `웨이포인트 ${names}번은 잡지 못하고 넘어갔습니다 — 기체가 그 점을 중심으로 `
    + "한 바퀴 돈 뒤 다음 점으로 넘어갔다는 뜻입니다(안 넘겼으면 경로가 끝나지 "
    + "않습니다). 그 꺾임이 이 속도의 선회 성능보다 급합니다 — 웨이포인트를 더 "
    + "벌리거나 순항 속도를 낮추면 계획대로 지나갑니다.";
}
