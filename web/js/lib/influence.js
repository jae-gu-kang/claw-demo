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
