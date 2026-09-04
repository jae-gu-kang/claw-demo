/** 영향성 화면의 데이터 계층 — 서버 응답을 화면 모델로, 그리고 팔레트.

판단은 전부 여기 있고 views/는 조립·그리기만 한다. 팔레트가 여기 있는 이유는
캔버스가 색을 JS로 그리기 때문이다 — **상수가 곧 스킨**이고, DOM 쪽 다크 스킨
(app.css의 `.inf-dark` 스코프)도 같은 값에서 갈라진다.

색은 Apple 다크모드 시스템 팔레트다. 두 가지가 이 스킨의 규칙이다:

① **표면은 중립 흑회색** — 파랑을 섞지 않는다. 바탕에 채도가 있으면 그 위에 얹는
   시스템 색이 전부 한 겹 탁해진다(이전 네이비 홀로 스킨이 촌스러웠던 진짜 이유는
   네온이 약해서가 아니라 **바탕이 이미 파래서** 네온이 대비를 못 얻은 것이다).
② **색은 광원이지 도료가 아니다** — 넓은 면은 무채색으로 두고, 채도는 노드 코어·
   활성 간선처럼 좁고 밝은 곳에만 쓴다. 그래야 발광이 장식이 아니라 신호로 읽힌다.

패널도 캔버스와 같은 다크 표면이다(뷰 루트가 `.inf-dark`) — 배지·상태 주석·경고
잉크는 Apple **다크 접근성 변형**을 쓴다. 순수 시스템 색을 그대로 쓰면 #0a84ff가
#1c1c1e 위 소형 텍스트 기준(4.5:1)에 아슬하게 걸린다. 그 변형이 STATE_INK다.
*/

// 케이스 이름의 격자 좌표는 grid.js가 부여했으므로 되읽는 것도 그쪽이다 —
// 구간 경향 표의 행 순서가 그 좌표를 쓴다 (trendMatrix)
import { orderCaseNames } from "./grid.js";

export const TIER = { STRUCT: "struct", OPEN: "open", CLOSED: "closed" };

export const SKIN = {
  // 표면 (systemBackground / secondary / tertiary, dark)
  bg0: "#000000", bg1: "#0b0b0d", bg2: "#151517",
  raised: "#1c1c1e",
  hairline: "rgba(255,255,255,.09)",
  // 은은한 광원 둘 — 배경에 깊이만 주고 색은 거의 내지 않는다
  glowA: "rgba(10,132,255,.15)", glowB: "rgba(94,92,230,.12)",
  // 라벨 (label / secondaryLabel / tertiaryLabel, dark)
  ink: "rgba(255,255,255,.92)", inkDim: "rgba(235,235,245,.60)",
  inkFaint: "rgba(235,235,245,.30)",
  // 시스템 색 (dark) — withAlpha가 파싱하므로 전부 #rrggbb로 둔다
  blue: "#0a84ff", indigo: "#5e5ce6", purple: "#bf5af2", teal: "#64d2ff",
  mint: "#66d4cf", yellow: "#ffd60a", orange: "#ff9f0a",
  red: "#ff453a", pink: "#ff375f", gray: "#8e8e93", gray2: "#636366",
};

// 파라미터 묶음 색 — 화면의 세로 그룹과 1:1. 법칙 밖 묶음은 무채색으로 묶어
// "여기는 제어법칙이 아니다"를 색 없음으로 말한다
export const BAND_COLOR = {
  ap: SKIN.blue, scas: SKIN.mint, mix: SKIN.indigo, lim: SKIN.red,
  sched: SKIN.purple, rate: SKIN.yellow, nav: SKIN.gray, actuator: SKIN.gray,
  guidance: SKIN.gray, io: SKIN.teal, metric: SKIN.orange, top: SKIN.teal,
};

/** 파라미터의 상태 — 화면이 반드시 구분해야 하는 다섯 가지.
 *
 * 이 구분이 이 화면의 값어치다. 전부 "영향 있음"으로 뭉뚱그리면 사용자는 편집해도
 * 아무 일이 없는 이유를 혼자 알아내야 한다.
 */
export function paramState(node) {
  if (node.error) return "error";
  if (!node.in_law) return "offgraph"; // 법칙 밖 — 개루프가 못 본다 (영향 없음이 아니다)
  if (node.inert) return "inert"; // 상수가 그래프에 방출되지도 않는다
  if (node.overridden?.length) return "overridden"; // 있지만 매 스텝 덮어써진다
  if (node.structural) return "structural"; // 위상이 바뀐다 — 연속 민감도가 아니다
  return "live";
}

export const STATE_LABEL = {
  live: "정상", structural: "구조 변경", overridden: "스케줄에 덮임",
  inert: "그래프에 없음", offgraph: "법칙 밖", error: "섭동 불가",
};

export const STATE_NOTE = {
  live: "",
  structural: "이 값을 올리면 노드가 새로 생기거나 사라진다 — 생성 C도 달라진다",
  overridden: "실행기가 매 스텝 게인 포트로 덮어쓴다. 실효값은 게인 탭의 테이블",
  inert: "스케줄 경로가 상수 대신 조회 노드를 쓴다 — 편집해도 아무 일도 없다",
  offgraph: "제어법칙 그래프 밖이라 개루프 재생으로는 보이지 않는다. 폐루프 스윕에서만 드러난다",
  error: "범위·교차조건이 섭동을 허용하지 않는다",
};

// 캔버스(검은 면)용 — Apple 다크 시스템 색
export const STATE_COLOR = {
  live: SKIN.blue, structural: SKIN.orange, overridden: SKIN.pink,
  inert: SKIN.gray2, offgraph: SKIN.gray, error: SKIN.red,
};

/** 다크 패널(배지·주석)용 — Apple이 어두운 바탕 대비를 맞추려고 내놓은 접근성 변형.
 *  캔버스용 STATE_COLOR를 그대로 배지 텍스트에 쓰면 그레이 계열이 #1c1c1e 위
 *  3:1 밑으로 떨어진다(캔버스 노드는 면이라 되지만 12px 텍스트는 안 된다). */
export const STATE_INK = {
  live: "#409cff", structural: "#ffb340", overridden: "#ff6482",
  // 무채색 둘도 다크 바탕 기준으로 잡는다 — 캔버스용 #636366은 배지에서 2:1대다.
  // 「법칙 밖」이 더 밝은 이유: 설명이 가장 필요한 상태라 문장으로도 읽혀야 한다
  inert: "#98989d", offgraph: "#aeaeb2", error: "#ff6961",
};

export const WARN_INK = "#ffb340"; // systemOrange (accessible, dark)

/** 서버 payload → 화면 모델. 서버가 준 필드를 다시 계산하지 않는다. */
export function normalizeGraph(payload) {
  const nodes = payload.nodes.map((n) =>
    (n.kind === "param" ? { ...n, state: paramState(n) } : n));
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const params = nodes.filter((n) => n.kind === "param");
  const structural = payload.edges.filter((e) => e.kind === "ir" || e.kind === "ghost");
  return {
    fingerprint: payload.fingerprint,
    dt: payload.dt,
    controlHz: payload.control_hz,
    probeRel: payload.probe_rel,
    graph: payload.graph,
    bands: payload.bands,
    metrics: payload.metrics,
    warnings: payload.warnings ?? [],
    elapsedMs: payload.elapsed_ms,
    nodes,
    edges: payload.edges,
    structural,
    byId,
    params,
  };
}

/** 파라미터 하나의 영향 원뿔 — 노드 집합과 그 안에 완전히 들어가는 간선 집합.
 *
 * 도달 노드는 서버가 이미 계산해 `reach`로 준다. 화면이 다시 그래프를 훑으면 같은
 * 답을 두 곳에서 정의하는 꼴이 되고, 어긋나면 어느 쪽이 맞는지 알 수 없게 된다.
 */
export function coneOf(model, paramId) {
  const p = model.byId.get(paramId);
  if (!p || p.kind !== "param") return { nodes: new Set(), seeds: new Set(), edges: new Set() };
  const seeds = new Set(p.seeds ?? []);
  const nodes = new Set(p.reach ?? []);
  for (const s of seeds) nodes.add(s);
  nodes.add(paramId);
  for (const g of p.added ?? []) nodes.add(g);
  for (const o of p.outputs ?? []) nodes.add(`out:${o}`);
  // 타면이 움직이면 기체도 지표도 움직인다 — 출력에서 끊으면 화면이 "지표는 영향
  // 없음"으로 읽힌다. 다만 이 구간은 **유도된 것이 아니라 선언된 것**이라(폐루프는
  // IR 밖에서 닫힌다) 점선 'declared' 스타일로 그려지고, 정량 대응은 3단에서만 나온다
  if (!p.in_law || (p.outputs ?? []).length) {
    nodes.add("sys:plant");
    for (const n of model.nodes) if (n.kind === "metric") nodes.add(n.id);
  }
  const edges = new Set();
  model.edges.forEach((e, i) => {
    if (e.src === paramId || (nodes.has(e.src) && nodes.has(e.dst))) edges.add(i);
  });
  return { nodes, seeds, edges };
}

/** 노드 반지름 — 하류 도달 개수가 클수록 크게. 층 그림에서 "허브"가 눈에 띈다.
 *  모양이 종류마다 다르므로(스퀘어클·캡슐·링) 여기서는 **반크기**로 읽는다. */
export function radiusOf(node, { maxReach = 60 } = {}) {
  if (node.kind === "param") return 4.4;
  if (node.kind === "metric") return 7.5;
  if (node.kind === "plant") return 10;
  if (node.kind === "output") return 5.2;
  if (node.kind === "input") return 3.6;
  const t = Math.min(1, (node.n_reach ?? 0) / maxReach);
  return 4 + 4 * Math.sqrt(t);
}

/** 값 표시 — null은 0이 아니라 「—」다 (미계측과 '실제로 0'을 섞으면 그림이 거짓말한다). */
export function fmtDelta(v, digits = 3) {
  if (v === null || v === undefined) return "—";
  if (v === "inf") return "∞";
  if (v === "-inf") return "−∞";
  if (typeof v !== "number" || !Number.isFinite(v)) return "—";
  if (v === 0) return "0";
  const a = Math.abs(v);
  if (a >= 1e4 || a < 1e-3) return v.toExponential(1);
  return v.toPrecision(digits);
}

export function fmtPercent(v, digits = 1) {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

/** 부호를 항상 붙인 값 — Δ는 방향이 뜻의 절반이라 +를 생략하면 읽는 쪽이 뺀다.
 *  음수는 하이픈이 아니라 U+2212(−): 고정폭 숫자 옆에서 하이픈은 글머리표로 읽힌다. */
export function fmtSigned(v, digits = 3) {
  const s = fmtDelta(v, digits);
  if (typeof v !== "number" || !Number.isFinite(v) || v === 0) return s;
  return v > 0 ? `+${s}` : s.replace("-", "−");
}

const PAIR_MIN_DIGITS = 3;
const PAIR_MAX_DIGITS = 7; // 그 이상은 읽히지 않는다 — 정밀한 차이는 Δ가 따로 말한다

const finiteNum = (v) => typeof v === "number" && Number.isFinite(v);

/** 이 전이를 구분해 찍는 데 필요한 최소 유효숫자 (3~7).
 *
 * 고정 자릿수로 반올림하면 상대 1% 섭동이 「4.0e−4 → 4.0e−4」가 되어 화면이
 * "안 변했다"고 말한다 — 이 화면의 주 질문이 정확히 그 자리에서 죽는다.
 * 7자리까지 가도 같으면 **이 표기로는 못 갈린다**(섭동 클립이거나 차이가 7자리 밑).
 * `expo`를 주면 그 표기로 판정한다 — 열 표기가 정해진 뒤 그 안에서 재야 답이 맞다.
 */
export function pairDigits(from, to, expo) {
  if (!finiteNum(from) || !finiteNum(to)) return PAIR_MIN_DIGITS;
  for (let d = PAIR_MIN_DIGITS; d < PAIR_MAX_DIGITS; d += 1) {
    const [a, b] = fmtPair(from, to, { digits: d, expo });
    if (a !== b) return d;
  }
  return PAIR_MAX_DIGITS;
}

/** 이 값이 지수 표기로 찍혀야 하는가 (0은 어느 쪽으로도 안 민다). */
const wantsExpo = (v) => v !== 0 && (Math.abs(v) >= 1e4 || Math.abs(v) < 1e-3);

/** 전이 한 쌍의 표기 — `[from, to]`.
 *
 * `fmt`(= `columnFormat`의 결과 `{digits, expo}`)를 주면 그대로 찍고, 안 주면 이 쌍만
 * 보고 정한다. **표에서는 주는 것이 맞다**: 행마다 따로 정하면 같은 기준값이 한 열
 * 안에서 40.8·40.847·40.85로 세 번 다르게 찍히고(자릿수), 0.00105가 어떤 행에서는
 * `1.05e-3`으로 어떤 행에서는 `0.00105`로 찍힌다(표기) — 같은 base 런의 같은 수인데도.
 */
export function fmtPair(from, to, fmt) {
  if (!finiteNum(from) || !finiteNum(to)) return [fmtDelta(from), fmtDelta(to)];
  const d = fmt?.digits ?? pairDigits(from, to);
  // 표기 방식은 둘이 **같아야** 한다 — 한쪽만 지수로 찍히면 크기 비교가 안 된다
  const expo = fmt?.expo ?? [from, to].some(wantsExpo);
  return [from, to].map((v) =>
    (expo ? v.toExponential(d - 1) : String(Number(v.toPrecision(d)))));
}

/** 한 열(같은 지표)의 전이들을 **같은 방식**으로 찍기 위한 표기 — `{digits, expo}`.
 *
 * 자릿수는 행별 최소의 **최댓값이 아니다.** 자릿수를 올리면 반올림 경계가 옮겨 가서,
 * 낮은 자릿수에서는 갈리던 쌍이 높은 자릿수에서 새로 뭉개질 수 있다
 * (40.847→40.853은 3자리에서 40.8/40.9로 갈리지만 4자리에서 둘 다 40.85다).
 * 그래서 **모든 행이 동시에 갈리는** 가장 작은 자릿수를 찾는다.
 *
 * 어느 자릿수로도 못 갈리는 행은 탐색에서 **뺀다**. 빼지 않으면 그 행 하나가 열
 * 전체를 7자리로 끌어올리는데, 정작 그 행은 7자리로도 여전히 안 갈린다 — 아무도
 * 못 얻는 정밀도를 위해 나머지 행이 전부 `40.847000` 같은 거짓 정밀도를 뒤집어쓴다.
 * 섭동이 범위에 클립돼 값이 정확히 같아진 행과, 차이가 7자리 밑인 행은 화면에서
 * 같은 처지다(둘 다 "이 표기로는 안 갈린다") — 같이 뺀다.
 */
export function columnFormat(pairs) {
  const usable = (pairs ?? []).filter(([f, t]) => finiteNum(f) && finiteNum(t));
  // 표기는 **열 안 모든 값**을 보고 한 번 정한다 (from·to 양쪽 다)
  const expo = usable.some(([f, t]) => wantsExpo(f) || wantsExpo(t));
  const splittable = usable.filter(([f, t]) =>
    f !== t && pairDigits(f, t, expo) < PAIR_MAX_DIGITS);
  if (!splittable.length) return { digits: PAIR_MIN_DIGITS, expo };
  for (let d = PAIR_MIN_DIGITS; d < PAIR_MAX_DIGITS; d += 1) {
    const fmt = { digits: d, expo };
    if (splittable.every(([f, t]) => {
      const [a, b] = fmtPair(f, t, fmt);
      return a !== b;
    })) return fmt;
  }
  return { digits: PAIR_MAX_DIGITS, expo };
}

/** 상대 변화 (to−from)/|from| — 기준이 0이면 **없다**(null).
 *
 * 0에서의 비율을 ∞나 0으로 적으면 화면이 "무한히 나빠졌다"거나 "안 변했다"고
 * 거짓말한다. 기준값이 정확히 0인 자리는 실재한다(k_diff_thr·ki_hdg·k_thr_turn) —
 * 그때는 비율을 접고 절대 Δ로만 말하는 것이 맞다.
 */
export function relOf(from, to) {
  if (!Number.isFinite(from) || !Number.isFinite(to) || from === 0) return null;
  return (to - from) / Math.abs(from);
}

// 비율이 이보다 작으면 "+0.0%"로 반올림된다 — 소수 1자리 표기의 바닥
const REL_FLOOR = 0.001;

/** 이 비율을 퍼센트로 찍어도 되는가 — 기준이 0이면 비율이 없고(relOf), 0.1% 미만은
 *  「+0.0%」로 반올림돼 "안 변했다"고 거짓말한다.
 *
 * 아래 `fmtChange`가 절대 Δ로 갈아타는 문턱과 **같은 하나**여야 한다. 퍼센트를 손으로
 * 다시 찍는 자리(구간 경향의 감도 칸)가 이 문턱만 빠뜨려 같은 거짓말이 되살아났다. */
export const relReadable = (rel) => rel != null && Math.abs(rel) >= REL_FLOOR;

/** 비율 한 조각 — 부호는 U+2212, 0은 여기 오지 않는다(relReadable이 먼저 막는다). */
export const fmtRel = (rel) => `${rel > 0 ? "+" : "−"}${fmtPercent(Math.abs(rel))}`;

/** 변화량 한 조각 — 비율이 읽히면 비율로, 아니면 절대 Δ로.
 *
 * 두 자리에서 비율이 거짓말한다: 기준이 0이면 비율이 아예 없고(relOf), 비율이
 * 0.1% 미만이면 「+0.0%」로 반올림돼 값은 눈에 띄게 움직였는데 변화량은
 * "안 변했다"고 말한다(0.16969 → 0.16972가 그랬다). 둘 다 절대 Δ로 넘긴다.
 */
export function fmtChange(delta, rel, unit = "") {
  if (relReadable(rel)) return fmtRel(rel);
  return `${fmtSigned(delta)}${unit ? ` ${unit}` : ""}`;
}

/** 전이의 눈에 띄는 정도 — 판독대가 지표 12개 중 **무엇을 먼저 보일지** 정하는 순위.
 *
 * 지표마다 단위가 달라 |Δ|로는 줄을 세울 수 없으므로 상대 변화를 쓴다. 다만 두
 * 자리가 상대 변화로 표현되지 않는다:
 *
 *  - Δ가 0이면 **안 움직인 것**이라 맨 뒤다. `relOf`가 여기서 null을 내는데
 *    (기준 0 → 0), 그 null을 큰 수로 접으면 아무 일도 없던 지표가 맨 앞에 선다
 *    (실제로 그랬다: 엔벨로프 이탈·타면 포화·리미터 작동이 전부 0→0인 채 상위 3줄을
 *    차지하고, 실제로 움직인 속도 RMS가 접혀 들어갔다).
 *  - 기준이 0인데 Δ가 있으면 **없던 일이 생긴 것**이다. 비율은 정의되지 않지만
 *    질적 변화라 맨 앞이 맞다 — 리미터가 한 번도 안 걸리던 형상에서 걸리기 시작했다면
 *    그것이 이 화면이 가장 먼저 말해야 할 사실이다.
 */
export function impactRank(t) {
  if (!t || !t.delta) return -1;
  return t.rel == null ? Infinity : Math.abs(t.rel);
}

/** 전이 둘의 정렬 비교자 (눈에 띄는 것 먼저). **뺄셈으로 쓰지 말 것**:
 *  0에서 벗어난 지표가 둘이면 `Infinity - Infinity`가 NaN이라 비교자 계약이 깨진다
 *  (엔진마다 다르게 처리한다 — V8은 지금 동률로 넘기지만 기댈 값이 아니다). */
export function byImpact(a, b) {
  const ra = impactRank(a);
  const rb = impactRank(b);
  if (ra === rb) return 0;
  return rb > ra ? 1 : -1;
}

/** 1단 탐침 전이 — 이 파라미터가 「얼마에서 얼마로」 흔들렸는가.
 *  섭동을 못 만든 자리(범위가 막힌 자리)는 to가 없으므로 null이다. */
export function probeTransition(param) {
  if (!param || param.probe_to == null || !Number.isFinite(param.value)) return null;
  return {
    from: param.value, to: param.probe_to,
    delta: param.probe_to - param.value,
    rel: relOf(param.value, param.probe_to),
    unit: param.unit && param.unit !== "-" ? param.unit : "",
  };
}

/** 로그 스케일 굵기 매핑 — 기준값이 미소한 노드에서 상대 Δ가 폭주하기 때문.
 *
 * 실측 사례: tau_hdg +10%에 scas_roll_sum의 상대 Δ가 341%였다(기준값이 미소해서다).
 * 선형으로 굵기에 물리면 그 간선 하나가 화면을 먹는다. 상·하한을 정해 로그로 누른다.
 */
export function logScale(v, { lo = 1e-4, hi = 1 } = {}) {
  if (!Number.isFinite(v) || v <= 0) return 0;
  const a = Math.log10(Math.max(v, lo));
  const b = Math.log10(lo);
  const c = Math.log10(hi);
  return Math.max(0, Math.min(1, (a - b) / (c - b)));
}

/** 0..1 → 시스템 색 램프 (mint → blue → orange → red). */
export function rampColor(t, alpha = 1) {
  const stops = [[0, 102, 212, 207], [0.4, 10, 132, 255], [0.75, 255, 159, 10], [1, 255, 69, 58]];
  const x = Math.max(0, Math.min(1, Number.isFinite(t) ? t : 0));
  let i = 0;
  while (i < stops.length - 2 && x > stops[i + 1][0]) i += 1;
  const [t0, r0, g0, b0] = stops[i];
  const [t1, r1, g1, b1] = stops[i + 1];
  const u = t1 === t0 ? 0 : (x - t0) / (t1 - t0);
  const mix = (a, b) => Math.round(a + (b - a) * u);
  return `rgba(${mix(r0, r1)}, ${mix(g0, g1)}, ${mix(b0, b1)}, ${alpha})`;
}

/** 처방 클래스 — 진단(pipeline/diagnose.py knob_class)과 1:1. 잉크는 다크 패널
 *  기준 접근성 변형(STATE_INK와 같은 이유). influence.test.js가 엔진 자구와
 *  대조한다. */
export const KNOB_CLASS = {
  filter: { label: "명령필터", ink: "#409cff" },
  loop_gain: { label: "루프 게인", ink: "#ffb340" },
  rate_gain: { label: "레이트 게인", ink: "#66d4cf" },
  clamp: { label: "클램프", ink: "#98989d" },
  limiter: { label: "리미터", ink: "#ff6961" },
  schedule: { label: "스케줄", ink: "#da8fff" },
};

export const DIRECTION_LABEL = {
  increase: "↑ 키운다 (|값| 기준)",
  decrease: "↓ 줄인다 (|값| 기준)",
};

/** 간선이 목적지에 **어떻게** 들어가는지 — 서버가 준 port/effect/kind를 사람 말로.
 *
 * 경로 설명의 절반이 이 정보다: 같은 화살표라도 입력·게인·인에이블·비활성 폴백은
 * 서로 다른 이야기다(게인 간선은 신호가 아니라 계수를 바꾼다). port 어휘는 엔진
 * pipeline/influence.py가 내는 그대로("input"·"gain:kp"·"enable"·"on_disable:x"·
 * "output") — 모르는 값은 삼키지 않고 원문을 그대로 내보인다.
 */
export function edgeVia(e) {
  if (!e) return "";
  if (e.port === "input") return "입력";
  if (e.port === "output") return "출력";
  if (e.port === "enable") return "인에이블";
  if (e.port?.startsWith("gain:")) return `게인 ${e.port.slice(5)}`;
  if (e.port?.startsWith("on_disable:")) return `비활성 폴백 ${e.port.slice(11)}`;
  if (e.kind === "param") {
    // effect는 파라미터 간선에만 실린다 — 값을 바꾸는 것과 구조를 바꾸는 것은 다르다.
    // **없으면** 기본 갈래(값 주입), **모르는 값이면** 원문 그대로 — 미래 effect를
    // "값 주입"으로 뭉개면 맞는 말 대신 틀린 말을 내보내는 것이다(포트와 같은 규약)
    if (e.effect == null) return "값 주입";
    return { changed: "값 주입", added: "노드 생성", removed: "노드 제거",
      overridden: "덮인 값" }[e.effect] ?? e.effect;
  }
  if (e.kind === "boundary") return "법칙 경계";
  if (e.kind === "declared") return "폐루프 선언";
  if (e.kind === "offgraph") return "법칙 밖 직행";
  if (e.kind === "ghost") return "구조 변경 시";
  return e.port ?? "";
}

/** 노드 한 줄 설명 — 서버가 노드에 실어 준 것부터 쓴다(desc·note·블록·파라미터 값·연산).
 *
 * IR 블록 노드는 desc가 없지만 `params`(블록 상수 값)와 `block`(클래스 이름)이 있다 —
 * "블록 Saturation — lo=-0.35 hi=0.35"가 "IR 연산 노드"보다 훨씬 많은 것을 말한다.
 * 값은 앞 3개만: 다 늘어놓으면 한 줄 설명이 표가 된다. 묶음 라벨은 bands에서 찾고,
 * 없으면(IR 그룹은 파라미터 묶음과 키가 다르다) 엔진이 준 그룹 이름 원문을 쓴다.
 */
export function nodeDetail(n, bands = {}) {
  if (!n) return "";
  if (n.kind === "param" || n.kind === "metric") return n.desc ?? "";
  if (n.kind === "plant" || n.kind === "ghost") return n.note ?? "";
  if (n.kind === "output") return "법칙 출력 — 생성 C가 내보내는 신호. 여기부터는 폐루프 선언이다";
  if (n.kind === "input") return "법칙 입력";
  const band = bands?.[n.band]?.label ?? n.group ?? "";
  const where = band ? `${band} · ` : "";
  if (n.block) {
    const ps = Object.entries(n.params ?? {}).filter(([, v]) =>
      typeof v === "number" || typeof v === "boolean" || typeof v === "string");
    const brief = ps.slice(0, 3)
      .map(([key, v]) => `${key}=${typeof v === "number" ? fmtDelta(v) : String(v)}`)
      .join(" ");
    return `${where}블록 ${n.block}${brief ? ` — ${brief}${ps.length > 3 ? " …" : ""}` : ""}`;
  }
  if (n.op) return `${where}연산 ${n.op}`;
  return `${where}IR 연산 노드`;
}

/** 형상 + 저장된 sim 결과 → /influence/diagnose 본문 — 형상 필드는
 *  structuralRequest에 위임한다 (같은 필드를 두 번 적으면 갈라진다). */
export function diagnoseRequest(state, resultId) {
  return { ...structuralRequest(state), result_id: resultId };
}

/** 처방 카드 → /influence/sweep 본문 — knobs·pairs는 카드에서 그대로 온다
 *  (전 게인 공간이 아니라 처방 부분공간만 흔드는 것이 3단의 비용 구조). */
export function sweepRequest(state, { cases, knobs, pairs = [], span,
                                      tSettle, tStep, fingerprint } = {}) {
  const body = { ...structuralRequest(state), cases, knobs, pairs };
  if (span?.length) body.span = span;
  if (tSettle != null) body.t_settle = tSettle;
  if (tStep != null) body.t_step = tStep;
  if (fingerprint) body.fingerprint = fingerprint;
  return body;
}

/** 형상 + 케이스 격자 → /influence/scan 본문 (3단 A) — sweepRequest에서
 *  knobs·pairs·span을 뺀 형태다: base 스캔은 흔들 것이 없는 것이 정의다. */
export function scanRequest(state, { cases, tSettle, tStep, fingerprint } = {}) {
  const body = { ...structuralRequest(state), cases };
  if (tSettle != null) body.t_settle = tSettle;
  if (tStep != null) body.t_step = tStep;
  if (fingerprint) body.fingerprint = fingerprint;
  return body;
}

// 판정의 표시 순서 — 나쁜 것부터. 모르는 판정은 맨 뒤(조용히 숨기지 않는다).
const VERDICT_RANK = { global: 0, local: 1, ok: 2 };

/** /influence/scan 결과 → 화면 모델 — 서버 판정(diagnose_grid)을 다시 계산하지
 *  않는다. badCaseNames는 전 지표 bad_cases에 **발산으로 잘린 케이스를 합친**
 *  것으로(격자 순서 무관, 중복 제거), 3단 B(부분 풀 스윕)의 기본 케이스 선택이
 *  된다. 잘린 케이스는 판정에서 빠지지만(지표가 잘린 구간만의 값이라 근거가
 *  못 된다) 그건 "볼 필요 없음"이 아니라 재확인이 가장 급한 자리다 — 빼면
 *  판정 불가가 B 대상 선정에서 정상으로 위장된다. */
export function scanSummary(payload) {
  const metrics = payload?.grid?.metrics ?? {};
  const verdicts = Object.entries(metrics).map(([metric, g]) => ({
    metric,
    verdict: g.verdict,
    knobClass: g.knob_class ?? null,
    threshold: g.threshold,
    nBad: g.n_bad,
    nCases: g.n_cases,
    badFrac: g.bad_frac,
    badCases: g.bad_cases ?? [],
  })).sort((a, b) =>
    (VERDICT_RANK[a.verdict] ?? 9) - (VERDICT_RANK[b.verdict] ?? 9)
    || b.badFrac - a.badFrac);
  const abortedCases = [...new Set((payload?.rows ?? [])
    .filter((r) => r.aborted).map((r) => r.case))];
  const badCaseNames = [...new Set(
    [...verdicts.flatMap((v) => v.badCases), ...abortedCases])];
  return { verdicts, badCaseNames, abortedCases,
    localFrac: payload?.grid?.local_frac ?? null };
}

/** 3단 B 대상 케이스 결정 — 스캔이 결함 케이스를 골랐으면 **체크된 것만**,
 *  결함이 없었거나 스캔 전이면 격자 전체. 선택이 격자와 어긋나면 남은 것만 조용히
 *  돌리지 않고 던진다: 화면이 "체크된 케이스만 들어간다"라고 말한 이상, 빠진 채
 *  도는 스윕은 "확인했다"는 오독을 만든다. 이름은 값 그대로라(grid.js nameCases)
 *  이름 일치가 곧 값 일치다. */
export function sweepCases(grid, scan) {
  if (!scan?.result) return grid;
  const bad = scanSummary(scan.result).badCaseNames;
  if (!bad.length) return grid;
  const sel = scan.selected ?? new Set();
  if (!sel.size) {
    throw new Error("결함 케이스 체크가 전부 해제됨 — 3단 B 대상이 없다. " +
      "체크를 되돌리거나, 격자 전체로 돌리려면 다시 스캔한다.");
  }
  const names = new Set(grid.map((c) => c.name));
  const missing = [...sel].filter((n) => !names.has(n));
  if (missing.length) {
    throw new Error(
      `스캔 뒤 격자가 바뀌어 선택 케이스 ${missing.length}건이 지금 격자에 없다: ` +
      `${missing.join(", ")} — 격자를 되돌리거나 다시 스캔한다.`);
  }
  return grid.filter((c) => sel.has(c.name));
}

/** 다중 케이스 스윕 요약 — base 제외 런 label별로, 지표마다 |Δ| 최대인 **전이**와
 *  그 케이스. 케이스 하나뿐이어도 형태는 같다 (요약 표가 곧 그 케이스).
 *
 * Δ만 내던 종전 형태로는 이 화면의 주 질문("얼마에서 얼마로")에 답할 수 없었다.
 * 기준값은 **같은 케이스의 base 런**이 들고 있으므로 여기서 짝지어 from·to를 함께
 * 낸다 — 화면이 base 행을 따로 뒤지면 같은 짝짓기가 두 곳에 적힌다.
 */
export function worstTransitions(rows) {
  const base = new Map();
  for (const r of rows ?? []) {
    if (r.label === "base") base.set(r.case, r.metrics ?? {});
  }
  const out = {};
  for (const r of rows ?? []) {
    if (r.label === "base" || !r.delta) continue;
    const entry = (out[r.label] ??= {});
    for (const [k, v] of Object.entries(r.delta)) {
      if (v == null) continue;
      if (entry[k] && Math.abs(v) <= Math.abs(entry[k].delta)) continue;
      // from·to는 **있으면** 싣는다. 서버 계약상 Δ가 있으면 그 케이스의 base 런도
      // 있으므로(routes/influence.py — base가 없으면 delta를 통째로 None으로 둔다)
      // 실제로는 from이 항상 찬다. 그래도 없는 경우를 0으로 메우지 않는 것이 규약이라
      // null로 남긴다 — 화면은 「—」를 찍고, 있지도 않은 기준을 지어내지 않는다
      const from = base.get(r.case)?.[k];
      const to = r.metrics?.[k];
      entry[k] = {
        delta: v, case: r.case,
        from: from == null ? null : from,
        to: to == null ? null : to,
        rel: relOf(from, to),
      };
    }
  }
  return out;
}

// ── 구간 경향 (3단 C) — 손잡이 하나를 흔들었을 때 **전 구간**이 어느 쪽으로 가는가 ──
//
// 3단 B의 요약(worstTransitions)은 런별 **최악 한 칸**만 낸다: "가장 나쁜 데가
// 어디냐"에는 답하지만 "엔벨로프를 따라 어느 쪽으로 기우느냐"에는 답하지 못한다.
// 케이스×런 전체 표는 사실을 전부 갖고 있지만 15케이스 × 9런 = 135행이라 경향이
// 행 사이에 흩어진다 — 사람이 눈으로 피벗해야 했다. 여기서 그 135행을
// **(구간 × 지표) 한 장**으로 접는다.
//
// 접는 축은 **스팬**이다: 한 케이스에서 손잡이를 −20·−10·기준·+10·+20%로 놓은
// 다섯 점을 스팬 순으로 세우면 그것이 그 구간의 응답 곡선이고, 곡선의 부호가 경향이다.

const SLOPE_SPAN = 0.1;  // 감도의 단위 — "게인 +10%당 Δ" (스팬 기본 간격과 같다)

// 표 칸에 들어가는 것은 기호이고 문장은 툴팁·범례가 받는다. 기호가 **색과 별도로**
// 경향을 말해야 한다 — 색만으로 구분하면 색각 이상·흑백 인쇄에서 표가 무의미해진다
export const TREND_MARK = { up: "↑", down: "↓", mixed: "∿", flat: "=", none: "—" };
export const TREND_LABEL = {
  up: "단조 증가", down: "단조 감소", mixed: "비단조 (스팬 안에 극점)",
  // eps 문턱이 생긴 뒤로 flat은 "정확히 같다"가 아니라 "이 분해능에서는 안 움직인다"다
  flat: "평탄 (분해능 아래)", none: "판정 불가",
};

// 다크 접근성 변형 — 좁은 텍스트에 쓰이므로 순수 시스템 색이 아니다.
// 악화는 「섭동 불가」와 같은 빨강이다(리터럴을 네 번째로 적지 않는다)
export const GOOD_INK = "#32d74b";
export const BAD_INK = STATE_INK.error;

/** 경향의 잉크 — 색은 **방향이 아니라 좋고 나쁨**을 말한다.
 *
 * 같은 「↑」가 실속마진에서는 개선이고 추종 RMS에서는 악화다. 방향에 색을 물리면
 * 화면이 절반의 지표에서 거짓말한다 — 극성은 서버 선언(MetricDef.better)이 정본이고,
 * 선언이 없는 지표는 **판단하지 않는다**(중립 잉크: 모르는 것을 색으로 단언하지 않는다).
 */
export function trendInk(trend, better) {
  if (trend === "none") return SKIN.inkFaint;
  if (trend === "flat") return SKIN.inkDim;
  if (trend === "mixed") return WARN_INK;  // 스팬 안에 극점 — 한쪽으로 밀 수 없다
  if (better !== "lower" && better !== "higher") return SKIN.ink;
  return (better === "lower" ? trend === "down" : trend === "up") ? GOOD_INK : BAD_INK;
}

/** 단독 런 라벨에서 상대 스팬 — `{pid}@{s:+g}` (engine sweep.py `single`의 자구).
 *  기준(0)은 스팬 점이 아니다: base 런은 라벨이 "base"라 애초에 여기 안 온다. */
function spanOf(label, knob) {
  if (typeof label !== "string" || !label.startsWith(`${knob}@`)) return null;
  const s = Number(label.slice(knob.length + 1));
  return Number.isFinite(s) && s !== 0 ? s : null;
}

/** 스윕 결과에서 **단독 런이 있는** 손잡이들 — 구간 경향의 주어가 될 수 있는 것.
 *
 * 쌍 런(A&B)은 제외한다: 두 손잡이가 같이 움직인 Δ를 한쪽의 경향으로 읽으면 귀속이
 * 틀린다(sweepFor의 규약과 같다). 쌍의 단독 점(a@+0.1)은 단독 런이므로 포함된다.
 * 순서는 런 순서 그대로 — 처방 카드가 손잡이를 세운 순서다.
 */
export function sweepKnobs(rows) {
  const out = [];
  for (const r of rows ?? []) {
    const keys = Object.keys(r.overrides ?? {});
    if (keys.length !== 1) continue;
    const pid = keys[0];
    if (spanOf(r.label, pid) == null || out.includes(pid)) continue;
    out.push(pid);
  }
  return out;
}

// 차분이 이 상대 크기 밑이면 **안 움직인 것**으로 본다. 순수한 부호 판정은 1 ulp에
// 갈리는데, 6DOF 적분을 5천 스텝 돌린 지표에서 마지막 자리는 신호가 아니라 반올림
// 잡음이다 — 그 잡음 하나로 이 표의 **가장 센 판정**(「비단조 — 한쪽으로 밀면 안 된다」)이
// 서면 안 된다. 배정밀도 상대오차 2.2e−16의 1만 배로, 실제 신호(관측된 최소가 상대
// 1e−4대)와는 여덟 자리 떨어져 있다
const TREND_EPS_REL = 1e-12;

/** 스팬 순 점열 `[[스팬, 값], …]` → 경향 한 칸. 기준(스팬 0)도 한 점이다.
 *
 * 단조 판정은 **연속 차분의 부호**로 한다. 회귀 기울기의 부호로 하면 −20%에서 튀고
 * +20%에서 돌아오는 곡선이 "단조"로 접혀, 스팬 안에 극점이 있다는 사실 — 이 손잡이를
 * 한쪽으로 밀면 안 된다는 사실 — 이 화면에서 사라진다.
 *
 * 곡선을 못 세울 때의 **사유는 여기서만 만든다.** 부르는 쪽이 나중에 덮어쓰면 맞는
 * 문장이 틀린 문장으로 바뀐다 — `nonfinite`(어딘가 ∞)만 보고 "점이 없다"로 갈아
 * 끼웠더니, 기준은 멀쩡하고 섭동만 발산한 칸(이 기능이 겨냥하는 바로 그 시나리오)에서
 * 「기준」열에 값이 찍혀 있는데 사유는 세울 점이 없다고 말했다. 그래서 문장을 가르는
 * 사실 셋을 전부 인자로 받는다: 기준이 있었는가 · 기준이 ∞였는가 · 섭동이 ∞였는가.
 */
function trendOf(pts, { hasBase = true, divBase = false, divSpan = false } = {}) {
  if (pts.length < 2) {
    let reason;
    if (!pts.length) {
      reason = divBase || divSpan
        ? "곡선에 세울 점이 없다 — 지표가 ∞/비수치다(발산한 런의 자리). 값은 그대로 낸다"
        : "유효 점 없음 — 이 구간에서 이 지표를 재지 못했다";
    } else if (hasBase) {
      reason = divSpan
        ? "유효 점이 기준 하나뿐 — 흔든 런의 지표가 ∞다(발산). 기준값은 그대로 낸다"
        : "유효 점이 기준 하나뿐 — 흔든 런에서 이 지표가 판정 불가다";
    } else {
      reason = divBase
        ? "기준(base) 런의 지표가 ∞다(발산) — 섭동 한 점만으로는 어느 쪽으로 갔는지 모른다"
        : "기준(base) 런의 값이 없다 — 섭동 한 점만으로는 어느 쪽으로 갔는지 모른다";
    }
    return { trend: "none", slope: null, swing: null, reason };
  }
  const scale = Math.max(...pts.map((p) => Math.abs(p[1])));
  const eps = scale * TREND_EPS_REL;
  let up = false;
  let down = false;
  for (let i = 1; i < pts.length; i += 1) {
    const d = pts[i][1] - pts[i - 1][1];
    if (d > eps) up = true;
    else if (d < -eps) down = true;
  }
  const trend = up && down ? "mixed" : up ? "up" : down ? "down" : "flat";
  const n = pts.length;
  const mx = pts.reduce((s, p) => s + p[0], 0) / n;
  const my = pts.reduce((s, p) => s + p[1], 0) / n;
  let num = 0;
  let den = 0;
  for (const [x, y] of pts) {
    num += (x - mx) * (y - my);
    den += (x - mx) * (x - mx);
  }
  const vals = pts.map((p) => p[1]);
  return {
    trend,
    // 평탄이면 기울기는 **정확히 0**이다. 회귀식에 맡기면 값이 전부 같아도 평균
    // 뺄셈의 반올림이 남아 7.7e−34 같은 수가 나오고(실측), 화면은 안 움직인 지표를
    // 「+7.70e−34」로 찍어 움직였다고 말한다. 스팬이 하나뿐이면 기울기가 **없다**
    // (0이 아니다) — bySpan이 중복을 접으므로 n≥2면 den>0이지만 규약을 코드에 남긴다
    slope: trend === "flat" ? 0 : den > 0 ? (num / den) * SLOPE_SPAN : null,
    swing: Math.max(...vals) - Math.min(...vals),
    reason: null,
  };
}

/** 스윕 행 → 구간 경향 표. 손잡이 하나에 대해 (구간 × 지표) 한 장.
 *
 * 반환:
 * - `points`  스팬 점 (오름차순) — 라벨과 그때 손잡이가 놓인 **절대값**.
 *             두 점의 knobValue가 같으면 범위 클립이다(엔진 notes가 사유를 낸다).
 * - `cases`   구간 — 격자 순서(fuel, alt, mach)로 세운다. 실행 순서(서펜타인)는
 *             인접 트림 시드용이라 표에서는 마하가 줄마다 뒤집혀 읽힌다.
 * - `cells`   구간 하나의 지표 한 칸. `base`·`values`는 **곡선에 세울 수 있는**
 *             유한값만이고(없으면 null), `rawBase`·`raw`는 서버가 준 그대로다
 *             (∞는 "inf" 문자열) — 판정에서 빼는 것과 화면에서 지우는 것은 다르다.
 * - `metrics` 한 구간에서라도 잰 값이 있던 지표. 전 구간 전부 없는 지표는
 *             `unmeasured`로 따로 낸다 — 숨기는 것이 아니라, 「—」 열다섯 줄로 표를
 *             채우는 대신 **왜 없는지 한 줄**로 말하는 자리를 만드는 것이다
 *             (이 기동에는 접지도 웨이포인트도 없다).
 */
export function trendMatrix(rows, knob) {
  const all = rows ?? [];
  const bySpan = new Map();
  for (const r of all) {
    const keys = Object.keys(r.overrides ?? {});
    if (keys.length !== 1 || keys[0] !== knob) continue;
    const s = spanOf(r.label, knob);
    if (s == null || bySpan.has(s)) continue;
    bySpan.set(s, { span: s, label: r.label, knobValue: Number(r.overrides[knob]) });
  }
  const points = [...bySpan.values()].sort((a, b) => a.span - b.span);
  const spans = points.map((p) => p.span);

  // 케이스 이름·런 라벨 어느 쪽에도 개행이 없으므로(둘 다 엔진·grid.js가 만든
  // 식별자) 줄바꿈을 구분자로 쓰면 키가 겹칠 수 없다
  const byKey = new Map(all.map((r) => [`${r.case}\n${r.label}`, r]));
  const names = orderCaseNames([...new Set(all.map((r) => r.case))]);
  const keys = [...new Set(all.flatMap((r) => Object.keys(r.metrics ?? {})))];

  const cases = names.map((name) => {
    const at = (label) => byKey.get(`${name}\n${label}`);
    const labels = ["base", ...points.map((p) => p.label)];
    const runs = labels.map(at);
    const cells = {};
    for (const k of keys) {
      // `raw`는 서버가 준 그대로다 — ∞는 "inf" 문자열로 온다(serialize 정책).
      // 곡선에는 못 세우지만(차분이 NaN·±∞다) **없는 값이 아니다**: 발산한 런이
      // 정확히 그 자리라, 화면이 "재지 못했다"로 접으면 같은 행의 「발산」 배지와
      // 정반대를 말한다. 판정에서 빼는 것과 화면에서 지우는 것은 다른 일이다
      const rawBase = runs[0]?.metrics?.[k] ?? null;
      const raw = points.map((p) => at(p.label)?.metrics?.[k] ?? null);
      const base = finiteNum(rawBase) ? rawBase : null;
      const values = raw.map((v) => (finiteNum(v) ? v : null));
      const pts = base == null ? [] : [[0, base]];
      values.forEach((v, i) => { if (v != null) pts.push([spans[i], v]); });
      pts.sort((a, b) => a[0] - b[0]);
      // "안 쟀다"와 "쟀는데 ∞였다"는 다른 사실이다 — 후자를 전자로 적으면 같은 행의
      // 「발산」 배지와 정반대를 말한다 (판독대의 사유 분기와 같은 규약).
      // 어느 쪽이 발산했는지까지 갈라서 넘긴다 — 사유 문장은 trendOf가 만든다
      const div = (v) => v != null && !finiteNum(v);
      const divBase = div(rawBase);
      const divSpan = raw.some(div);
      const t = trendOf(pts, { hasBase: base != null, divBase, divSpan });
      cells[k] = {
        ...t, base, values, rawBase, raw, nonfinite: divBase || divSpan,
        // 기준이 0이면 비율이 없다 — relOf와 같은 이유로 ∞·0으로 위장하지 않는다
        rel: t.slope != null && base ? t.slope / Math.abs(base) : null,
      };
    }
    return {
      name,
      // 잘린 런의 지표는 **잘린 구간만의** 값이다 — 스팬 점마다 잰 구간이 다르면
      // 그 구간의 곡선은 곡선이 아니라 서로 다른 실험의 나열이다. 경향을 지우지는
      // 않되(그 안에서는 사실이다) 행에 표시해 읽는 쪽이 할인하게 한다
      aborted: runs.map((r, i) => (r?.aborted ? labels[i] : null)).filter(Boolean),
      // 취소로 잘린 스윕은 케이스마다 돈 런 수가 다르다 — 없는 런을 0으로 치면
      // 경향이 조용히 달라진다(빠진 점은 곡선에서 빠질 뿐이다)
      missing: runs.map((r, i) => (r ? null : labels[i])).filter(Boolean),
      cells,
    };
  });

  // 열이 서는 기준은 **잰 값이 있는가**이지 곡선에 세울 수 있는가가 아니다 —
  // ∞만 나온 지표는 "이 기동이 못 재는 지표"가 아니라 발산한 지표다
  const has = (k) => cases.some((c) =>
    c.cells[k].rawBase != null || c.cells[k].raw.some((v) => v != null));
  const metrics = keys.filter(has);
  const counts = {};
  const total = { up: 0, down: 0, mixed: 0, flat: 0, none: 0 };
  for (const k of metrics) {
    const c = { up: 0, down: 0, mixed: 0, flat: 0, none: 0 };
    for (const cs of cases) {
      c[cs.cells[k].trend] += 1;
      total[cs.cells[k].trend] += 1;
    }
    counts[k] = c;
  }
  return {
    knob, points, cases, metrics, counts, total,
    unmeasured: keys.filter((k) => !has(k)),
  };
}

/** 2단 다중 케이스 요약 — (knob, 루프)별로 케이스 전체에서 |ΔPM|·|ΔGM|가 가장
 *  큰 전이와 그 케이스. delta가 없는 항목(no_loop·overridden 등)은 세지 않는다 —
 *  판정 불가를 0으로 위장하지 않는 renderOpenloop 규약과 같다.
 *
 * 기준·섭동 마진은 서버가 이미 `base`·`perturbed`로 준다 — Δ만 그리면 "48.3°에서
 * 47.1°로"가 화면에 없어 사용자가 두 열을 눈으로 더해야 했다. 여기서 함께 싣는다.
 */
export function openloopWorst(params, knobs) {
  const rows = [];
  for (const pid of knobs ?? []) {
    const p = params?.[pid];
    if (!p || p.status !== "ok") continue;
    for (const [loop, byCase] of Object.entries(p.loops ?? {})) {
      let pm = null;
      let gm = null;
      let n = 0;
      for (const [caseName, e] of Object.entries(byCase ?? {})) {
        if (!e?.delta) continue;
        n += 1;
        const at = (key, cur, v) => (v != null && (!cur || Math.abs(v) > Math.abs(cur.value))
          ? { value: v, case: caseName,
              from: e.base?.[key] ?? null, to: e.perturbed?.[key] ?? null }
          : cur);
        pm = at("pm_deg", pm, e.delta.pm_deg);
        gm = at("gm_db", gm, e.delta.gm_db);
      }
      // 손잡이 자신의 전이(value → probe_to)도 함께 — 마진이 얼마에서 얼마로 갔는지는
      // **무엇을 얼마로 바꿨을 때**인지와 짝이어야 읽힌다
      if (n) rows.push({ param: pid, loop, nCases: n, pm, gm,
        knobFrom: p.value ?? null, knobTo: p.probe_to ?? null });
    }
  }
  return rows;
}

/** 카드의 동시 수정 후보 → 스윕 쌍 기본값: (대표 knob, 동반 knob). */
export function pairsFor(card) {
  const a = card.knobs?.[0];
  if (!a) return [];
  return (card.joint_with ?? []).map((j) => [a, j]);
}

/** /influence/diagnose 응답 → 화면 모델 — 서버 판정을 다시 계산하지 않는다. */
export function normalizeDiagnosis(payload) {
  const findings = payload.findings ?? [];
  return {
    resultId: payload.result_id,
    fingerprint: payload.fingerprint,
    metrics: payload.metrics ?? {},
    thresholds: payload.thresholds ?? {},
    warnings: payload.warnings ?? [],
    findings,
    prescriptions: (payload.prescriptions ?? []).map((p, i) => ({ ...p, index: i })),
    hasWarn: findings.some((f) => f.severity === "warn"),
  };
}

/** 형상 → /influence/structural 요청 본문. 사용자가 정한 것만 싣는다 (02 §5.5). */
export function structuralRequest(state = {}) {
  const body = {};
  if (state.controlHz) body.control_hz = state.controlHz;
  if (state.withSchedule === false) body.with_schedule = false;
  if (state.withLimiter === false) body.with_limiter = false;
  for (const [k, v] of Object.entries({
    autopilot: state.autopilot, scas: state.scas, mixer: state.mixer,
    nav: state.nav, actuators: state.actuators, guidance: state.guidance,
    gain_tables: state.gainTables,
  })) {
    if (v && Object.keys(v).length) body[k] = v;
  }
  if (state.alphaMargin != null) body.alpha_margin = state.alphaMargin;
  if (state.includeOffgraph === false) body.include_offgraph = false;
  if (state.probeRel) body.probe_rel = state.probeRel;
  return body;
}
