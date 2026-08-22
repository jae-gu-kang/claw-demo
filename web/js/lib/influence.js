/** 영향성 화면의 데이터 계층 — 서버 응답을 화면 모델로, 그리고 팔레트.

판단은 전부 여기 있고 views/는 조립·그리기만 한다. 팔레트가 여기 있는 이유는
`app.css`를 건드리지 않기로 했기 때문이다(병행 세션 작업 중) — 이 화면의 스킨은
캔버스 안에서 색으로 존재하므로 **상수가 곧 스킨**이다.

색은 Apple 다크모드 시스템 팔레트다. 두 가지가 이 스킨의 규칙이다:

① **표면은 중립 흑회색** — 파랑을 섞지 않는다. 바탕에 채도가 있으면 그 위에 얹는
   시스템 색이 전부 한 겹 탁해진다(이전 네이비 홀로 스킨이 촌스러웠던 진짜 이유는
   네온이 약해서가 아니라 **바탕이 이미 파래서** 네온이 대비를 못 얻은 것이다).
② **색은 광원이지 도료가 아니다** — 넓은 면은 무채색으로 두고, 채도는 노드 코어·
   활성 간선처럼 좁고 밝은 곳에만 쓴다. 그래야 발광이 장식이 아니라 신호로 읽힌다.

밝은 패널 위(배지·상태 주석·경고)에는 다크모드 색을 그대로 쓸 수 없다 — 흰 바탕에서
대비가 3:1 밑으로 떨어진다. 같은 이유로 Apple이 내놓은 접근성 변형이 STATE_INK다.
*/

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

/** 밝은 패널(배지·주석)용 — Apple이 흰 바탕 대비를 맞추려고 내놓은 접근성 변형.
 *  다크 색을 그대로 흰 위에 쓰면 #0a84ff가 3.4:1까지 떨어져 본문 대비에 못 미친다. */
export const STATE_INK = {
  live: "#0040dd", structural: "#b25000", overridden: "#d30f45",
  // 무채색 둘도 흰 바탕 기준으로 잡는다 — 다크 시스템 그레이(#8e8e93)를 그대로 쓰면
  // 배지가 2.96:1이 되어 이 파일이 위에 적어 둔 기준 아래로 떨어진다.
  // 「법칙 밖」이 더 진한 이유: 설명이 가장 필요한 상태라 문장으로도 읽혀야 한다
  inert: "#6c6c70", offgraph: "#636366", error: "#d70015",
};

export const WARN_INK = "#b25000"; // systemYellow (accessible, light)

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
