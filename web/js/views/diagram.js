/** 고정 구조 신호흐름 다이어그램 (02 §4 (a)) — 층 보드 스타일 SVG 최상위.

자유 블록 배선 에디터는 [확정] 스코프 제외 — 아키텍처가 고정(01 §3)이므로
편집은 파라미터(게인·옵션·모드 테이블)로만 하고, 구조는 이 다이어그램이 정본을
표시한다. 블록 id·편집 경로 계약은 lib/blocks.js가 정본 (하위 페이지와 공유),
SVG 기하는 여기서 **계산**한다 — data-block 속성이 lib 블록 id와 1:1.

## 왜 3D인가 — 설계 순서를 높이로 옮겼다

설계 순서 ①~⑤("안쪽 루프부터 닫는다", 01 §1)는 예전엔 중첩 점선 프레임이었다.
프레임 다섯 겹은 블록·배선과 계속 부딪혀 라벨을 우상단 범례로 빼야 했고, 그러면
"어느 블록이 몇 단계냐"를 색으로 되짚어야 했다. 지금은 **층을 높이로 세운다**:
①이 가장 높은 판, ⑤가 바닥 판. 블록은 자기 단계의 판 위에 앉으므로 소속이
위치로 즉시 읽히고, 층 이름은 항상 보이는 판 앞면(책등)에 찍혀 범례가 필요 없다.

## 투영 — 왜 이런 축인가

  화면x = (MIRW − u) + VX·(v′ − VREF)      화면y = VY·(v′ − VREF) − KY·z

- **u(주 신호 경로)는 수평**이라 블록의 위·아래 변과 모든 글자가 수평이다.
  기울어진 글자는 조밀한 라벨에서 읽기 비용이 크다 — 도면처럼 읽히는 게 우선.
- **z(높이)는 수직**(VX 성분 0). 세로 모서리가 서지 않으면 어느 각도로 눕혀도
  "성립하지 않는 입체"로 보인다 — 이 다이어그램에서 제일 먼저 어색해지는 부분.
- **v(깊이)만 24° 눕히고 0.88로 압축**한다. 좌우 변이 기울어 판이 바닥에 누운
  것으로 읽히고, 압축이 없으면 깊이 496이 그대로 496px이라 벽처럼 선다.
- **MIRW 좌우 반전**: 신호는 오른쪽(유도)에서 왼쪽(기체)으로 흐른다. 시점이
  앞-오른쪽 위라 보이는 옆면이 오른쪽인데, 화살표가 왼쪽에서 들어오면 블록
  윗면에 먹혀 화살촉이 사라진다. 반전하면 화살표가 보이는 면에 닿고, 덤으로
  설계 순서 ①→⑤가 왼쪽→오른쪽으로 읽힌다.
- **DROP**: 뒷줄(미션플래너·게인 스케줄링)만 두고 나머지를 앞으로 70 민다.
  게인 스케줄링에서 내려오는 배선이 지나갈 자리 — 없으면 화살촉이 블록에 붙는다.

배선의 층 변화는 **판 옆면에서 수직**으로 오르내린다(대각 경사로 아님) — 가로는
가로, 세로는 판 모서리와 나란해야 줄이 맞아 보인다. 예외는 뒷줄에서 내려오는
K_ap 하나로, 거기서 계단을 밟으면 화면에선 위로 튀는 톱니가 된다.

블록 그리기 순서는 **뒤 → 앞**이어야 겹침이 성립한다. 주 경로 블록끼리는 간격
52로 화면에서 겹치지 않으므로, 마크업 순서를 CHAIN(M7 조립 순서)으로 두어도
그림이 깨지지 않는다 — lib/blocks.test.js가 그 순서를 판다.
*/

import { BLOCKS, CHAIN } from "../lib/blocks.js";

const B = Object.fromEntries(BLOCKS.map((b) => [b.id, b]));

/** 정적 마크업 → DOM 요소. 반드시 정적(수작성) 문자열만 — 사용자 데이터 삽입 금지. */
export function fromMarkup(markup) {
  const box = document.createElement("div");
  box.innerHTML = markup;
  return box.firstElementChild;
}

/** 층 판 ①~⑤ — rect는 [x, y, w, h](원좌표), z는 판 밑면 높이.
바깥 판일수록 낮고 넓다. page는 클릭 시 이동할 서브시스템(=설계 단계 페이지).
**색·이름의 정본은 여기 한 곳**이다 — 판과 층 칩이 어긋나면 색으로 층을 되짚는
독법 자체가 깨진다 (app.css --l1~--l5도 같은 값). */
const LAYERS = [
  { n: 5, page: "verify", name: "비선형 시뮬 검증", color: "#6b7280", z: 0,
    rect: [24, 56, 1258, 496], fill: { top: "#e2e6ed", side: "#b3bac7", front: "#c9cfd9" } },
  { n: 4, page: "guidance", name: "유도", color: "#b45309", z: 12,
    rect: [40, 64, 1230, 472], fill: { top: "#fbe3cd", side: "#e2ad7c", front: "#f1c9a3" } },
  { n: 3, page: "autopilot", name: "오토파일럿", color: "#1f7a4d", z: 24,
    rect: [212, 72, 1046, 450], fill: { top: "#d5efdf", side: "#8fcaa8", front: "#b5dfc5" } },
  { n: 2, page: "scas", name: "SCAS · 내측 루프", color: "#2563eb", z: 36,
    rect: [556, 80, 690, 430], fill: { top: "#d8e6fa", side: "#93b3e6", front: "#b7cdf0" } },
  { n: 1, page: "plant", name: "트림 · 선형해석", color: "#7c3aed", z: 48,
    rect: [1072, 226, 160, 118], fill: { top: "#e9def9", side: "#b79ce8", front: "#cfbdf0" } },
];

/** 설계 순서 칩 (①→⑤) — page id로 이동. 판에서 그대로 뽑아 쓰므로 색이 어긋날 수 없다. */
export const DESIGN_ORDER = [...LAYERS].sort((a, b) => a.n - b.n).map((L) => ({
  page: L.page, n: L.n, name: L.name, color: L.color, tint: L.fill.top, edge: L.fill.side,
}));

// ── 투영 ────────────────────────────────────────────────────────────────

const TILT = (24 * Math.PI) / 180;
const VX = -Math.tan(TILT); // 깊이축 기울기 (좌우 변 24°)
const VY = 0.88;            // 깊이 원근 압축
const KY = 1.8;             // 높이 과장 — 판·블록 두께가 읽히는 정도
const VREF = 300;           // 기울기·압축의 회전 중심 (구도가 좌우로 쏠리지 않게)
const MIRW = 1306;          // 좌우 반전 폭
const DROP = 70;            // 뒷줄을 뺀 나머지를 앞으로 미는 양
const PH = 12;              // 판 두께
const BT = 15;              // 블록 두께
const BW = 120;             // 블록 폭 (u 방향)
const HB = 36.5;            // 블록 깊이 절반 (압축 후 화면 높이 64px)

const sv = (v) => (v > 172 ? v + DROP : v);
const P = (u, v, z) => [(MIRW - u) + VX * (sv(v) - VREF), VY * (sv(v) - VREF) - KY * z];
const fx = (n) => +n.toFixed(2);
const pts = (arr) => arr.map(([x, y]) => `${fx(x)},${fx(y)}`).join(" ");

/** 블록 배치 — u는 주 신호 경로(좌→우가 원좌표), v는 깊이, 값은 중심. */
const POS = {
  planner: [120, 120], schedule: [636, 120],
  guidance: [120, 280], autopilot: [292, 280], limiter: [464, 280], scas: [636, 280],
  mixer: [808, 280], actuator: [980, 280], plant: [1152, 280],
  nav: [1152, 450],
};

/** 블록이 앉는 판의 윗면 높이 = 그 블록의 설계 단계. 위치가 곧 소속이다. */
const BASE_Z = {
  planner: 24, schedule: 48, guidance: 24, autopilot: 36, limiter: 36,
  scas: 48, mixer: 48, actuator: 48, nav: 48, plant: 60,
};

/** 블록 id → 재생 값 슬롯 (lib/wiresignals.js WIRE_SIGNALS 키와 1:1 — 한쪽만
바뀌면 값이 조용히 안 뜬다). 계측 신호가 없는 블록(게인 스케줄·믹서)은 슬롯이 없다. */
const SIG = {
  planner: "w_plan", guidance: "w_gui", autopilot: "w_ap", limiter: "w_lim",
  scas: "w_scas", actuator: "w_act", plant: "w_plant", nav: "w_nav",
};

// ── 도형 ────────────────────────────────────────────────────────────────

const bb = []; // viewBox 계산용 — 실제로 잉크가 닿는 점만 모은다
const at = (u, v, z) => { const p = P(u, v, z); bb.push(p); return p; };

const poly = (p, fill, extra = "") =>
  `<polygon points="${pts(p)}" fill="${fill}"${extra ? ` ${extra}` : ""}/>`;

/** 볼록 껍질 (모노톤 체인) — 상자의 실루엣 외곽선.
면마다 테두리를 그리면 내부 모서리까지 그어져 지저분하고, 재생 오버레이가
"이 블록"을 강조할 손잡이도 없다. 껍질 하나를 .body로 두면 둘 다 해결된다. */
function hull(ps) {
  const s = [...ps].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const cross = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const half = (arr) => {
    const out = [];
    for (const p of arr) {
      while (out.length >= 2 && cross(out[out.length - 2], out[out.length - 1], p) <= 0) out.pop();
      out.push(p);
    }
    return out.slice(0, -1);
  };
  return [...half(s), ...half([...s].reverse())];
}

/** 직육면체 — 보이는 옆면은 시점이 정한다(화면 오른쪽에 오는 세로 모서리).
반대쪽 면을 그리면 성립하지 않는 입체가 된다. */
function slab(x, y, w, h, z, t, fill, cls = "") {
  const zt = z + t;
  const su = P(x, y, z)[0] > P(x + w, y, z)[0] ? x : x + w;
  const side = [P(su, y, z), P(su, y + h, z), P(su, y + h, zt), P(su, y, zt)];
  const front = [P(x, y + h, z), P(x + w, y + h, z), P(x + w, y + h, zt), P(x, y + h, zt)];
  const top = [P(x, y, zt), P(x + w, y, zt), P(x + w, y + h, zt), P(x, y + h, zt)];
  const corners = [];
  for (const [cu, cv] of [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]) {
    corners.push(at(cu, cv, z), at(cu, cv, zt));
  }
  return poly(side, fill.side, `class="face ${cls}"`)
    + poly(front, fill.front, `class="face ${cls}"`)
    + poly(top, fill.top, `class="face ${cls}"`)
    + `<polygon class="body" points="${pts(hull(corners))}" fill="none"/>`;
}

/** 배선 — (u, v, z) 꼭짓점 목록. dash는 보조 신호(스케줄 주입·피드백)용. */
const wire = (p, cls = "wire") =>
  `<path class="${cls}" d="${p.map(([u, v, z], i) => (i ? "L" : "M") + P(u, v, z).map(fx).join(","))
    .join(" ")}" marker-end="url(#bd-arr)"/>`;

const label = (u, v, z, s, cls = "siglabel", anchor = "middle") => {
  const [x, y] = at(u, v, z);
  return `<text class="${cls}" x="${fx(x)}" y="${fx(y)}" text-anchor="${anchor}">${s}</text>`;
};

// ── 조립 ────────────────────────────────────────────────────────────────

function buildTopSvg() {
  bb.length = 0;
  let s = "";

  // 바닥 그림자 — 보드가 지면 위에 떠 있게. bb에서 제외한다(흐릿해서 잉크로 안 보이는데
  // 프레임만 넓혀 그림을 축소시킨다)
  const [gx, gy, gw, gh] = LAYERS[0].rect;
  s += poly([[gx, gy], [gx + gw, gy], [gx + gw, gy + gh], [gx, gy + gh]]
    .map(([u, v]) => P(u - 14, v + 20, 0)), "#0f172a", 'class="board-shadow"');

  // 층 판 ⑤ → ① (바깥·낮은 것부터). 판 앞면에 층 이름을 찍는다 — 항상 보이는 띠라
  // 범례가 필요 없고, 클릭하면 그 설계 단계 페이지로 간다
  for (const L of LAYERS) {
    const [x, y, w, h] = L.rect;
    s += `<g class="plate">`;
    s += slab(x, y, w, h, L.z, PH, L.fill, "plate-face");
    const inset = [[x + 6, y + 6], [x + w - 6, y + 6], [x + w - 6, y + h - 6], [x + 6, y + h - 6]]
      .map(([u, v]) => P(u, v, L.z + PH));
    s += poly(inset, "none", 'class="plate-sheen"');
    // 클릭 대상은 **판이 아니라 책등 라벨**이다. 판은 보드 전 면적을 타일링하므로
    // 그룹 전체를 대상으로 두면 빈 배경 아무 데나 눌러도 페이지가 넘어간다
    const [bx, cy] = P(x + w - 26, y + h, L.z + PH / 2);
    const nameW = L.name.length * 10.5 + 24;
    s += `<g class="plate-tag" data-page="${L.page}" tabindex="0" role="button"`
      + ` aria-label="설계 ${L.n}단계 ${L.name} — 설계 화면 열기">`
      + `<rect class="plate-hit" x="${fx(bx - 11)}" y="${fx(cy - 10)}" width="${fx(nameW)}" height="20" fill="transparent"/>`
      + `<circle class="plate-badge" cx="${fx(bx)}" cy="${fx(cy)}" r="7.6" fill="${L.color}"/>`
      + `<text class="plate-num" x="${fx(bx)}" y="${fx(cy + 2.9)}" text-anchor="middle">${L.n}</text>`
      + `<text class="plate-name" x="${fx(bx + 13)}" y="${fx(cy + 3.6)}">${L.name}</text>`
      + "</g>";
    s += "</g>";
  }

  // 배선 — 층이 바뀌는 곳은 판 옆면에서 수직으로 (가로는 가로, 세로는 판 모서리와 나란히)
  s += '<g class="wires">';
  s += wire([[120, 156, 24], [120, 213, 24]]);                                  // 임무프로파일 → 유도
  s += wire([[600, 156, 48], [600, 172, 48], [556, 172, 48],                    // K_ap: ②에서 ③으로
             [556, 172, 36], [292, 172, 36], [292, 213, 36]], "wire gs");
  s += wire([[636, 156, 48], [636, 213, 48]], "wire gs");                       // K_scas: 같은 층
  const CHAIN_STEP = [
    [[180, 280, 24], [212, 280, 24], [212, 280, 36], [232, 280, 36]],
    [[352, 280, 36], [404, 280, 36]],
    [[524, 280, 36], [556, 280, 36], [556, 280, 48], [576, 280, 48]],
    [[696, 280, 48], [748, 280, 48]],
    [[868, 280, 48], [920, 280, 48]],
    [[1040, 280, 48], [1072, 280, 48], [1072, 280, 60], [1092, 280, 60]],
  ];
  for (const p of CHAIN_STEP) s += wire(p);
  s += wire([[1200, 317, 60], [1200, 344, 60], [1200, 344, 48], [1200, 383, 48]]); // 기체 → 항법
  // 피드백 버스 — 항법 출력만 소비 (참값 차단 계약 03 §4)
  s += wire([[1092, 450, 48], [556, 450, 48], [556, 450, 36], [212, 450, 36],
             [212, 450, 24], [120, 450, 24], [120, 317, 24]], "wire fb");
  s += wire([[636, 450, 48], [636, 317, 48]], "wire fb");
  s += wire([[292, 450, 36], [292, 317, 36]], "wire fb");
  for (const [u, v, z] of [[636, 450, 48], [292, 450, 36]]) {
    const [x, y] = P(u, v, z);
    s += `<circle class="branch" cx="${fx(x)}" cy="${fx(y)}" r="3.4"/>`;
  }
  s += "</g>";

  // 블록 — 뒷줄 → 주 경로(CHAIN 순서) → 항법. 주 경로끼리는 화면에서 겹치지 않아
  // 마크업을 조립 순서로 둘 수 있다 (lib/blocks.test.js가 이 순서를 판다)
  const order = ["planner", "schedule", ...CHAIN, "nav"];
  for (const id of order) {
    const [cu, cv] = POS[id];
    const z = BASE_Z[id];
    const x = cu - BW / 2;
    const y = cv - HB;
    const sel = id === "scas";
    const fill = sel
      ? { top: "#2563eb", side: "#1e3a8a", front: "#3b82f6" }
      : { top: "#ffffff", side: "#bfc7d3", front: "#d9dee6" };
    const [tx, ty] = P(cu, cv, z + BT);           // 윗면 중심 — 제목
    const [fu, fv] = P(cu, cv + HB, z + BT / 2);  // 앞면 중심 — 세부 설명
    s += `<g class="blk${sel ? " sel" : ""}" data-block="${id}" tabindex="0" role="button"`
      + ` aria-label="${B[id].title} — 서브시스템 내부 블록도 열기">`;
    s += slab(x, y, BW, 2 * HB, z, BT, fill, sel ? "sel" : "");
    s += `<text class="ttl" x="${fx(tx)}" y="${fx(ty + 5)}" text-anchor="middle">${B[id].title}</text>`;
    s += `<text class="ttl2" x="${fx(fu)}" y="${fx(fv + 3.4)}" text-anchor="middle">${B[id].sub}</text>`;
    s += "</g>";
    // 재생 값 슬롯 — 블록 바로 앞 판 위 (블록 간격 52로는 배선 사이에 값이 안 들어간다).
    // 뒷줄의 +14는 간격 조절이 아니라 **DROP 절벽(172) 회피**다: 120+36.5+14 = 170.5로
    // 1.5 남는다. +16으로 키우거나 HB를 올리면 sv()가 70을 더해 값이 화면에서 61px
    // 아래로 순간이동한다
    if (SIG[id]) {
      const [sx, sy] = at(cu, cv < 172 ? cv + HB + 14 : cv + HB + 22, z);
      s += `<text class="sigval" data-sig="${SIG[id]}" x="${fx(sx)}" y="${fx(sy)}"></text>`;
    }
  }

  // 신호 라벨 — 배선이 실제로 보이는 구간 위에
  s += '<g class="labels">';
  s += label(128, 168, 24, "임무프로파일", "siglabel", "start");
  s += label(362, 158, 36, "K_ap", "siglabel gs-ink");
  s += label(648, 190, 48, "K_scas", "siglabel gs-ink", "start");
  const CHAIN_LBL = ["V h ψ", "θ φ δT", "θ φ", "δa δe δr", "δ cmd", "δ"];
  CHAIN_LBL.forEach((t, i) => {
    s += label(POS[CHAIN[i]][0] + 86, 262, Math.max(BASE_Z[CHAIN[i]], BASE_Z[CHAIN[i + 1]]), t);
  });
  s += label(1210, 369, 48, "x", "siglabel", "start");
  s += label(860, 443, 48, "x̂ · 추정 상태");
  s += "</g>";

  const xs = bb.map((p) => p[0]);
  const ys = bb.map((p) => p[1]);
  const mx = 30;
  const my = 24;
  const vb = [Math.min(...xs) - mx, Math.min(...ys) - my,
    Math.max(...xs) - Math.min(...xs) + 2 * mx,
    Math.max(...ys) - Math.min(...ys) + 2 * my].map(fx);
  // 이 모듈의 유일한 조용한 실패 경로를 막는다: BASE_Z 키가 하나만 빠져도
  // P(u, v, undefined) → NaN → viewBox="NaN …" → 보드가 통째로 안 그려지는데
  // 테스트는 data-block 정규식만 보므로 전부 통과한다
  if (!vb.every(Number.isFinite)) {
    throw new Error(`블록도 viewBox 계산 실패 (${vb.join(" ")}) — POS·BASE_Z 키 누락 의심`);
  }

  // role="img"를 루트에 두면 하위가 presentational이 되어 블록·층 라벨의 role/label이
  // 무시된다 — 이 SVG는 그림이 아니라 네비게이션 허브라 노출이 맞다.
  // <title>은 쓰지 않는다: 이름 계산은 aria-label이 이기고 <title>은 **네이티브 툴팁**으로만
  // 남아, 자체 title이 없는 하위에 호버할 때마다 조상 title이 떠오른다
  return `<svg viewBox="${vb.join(" ")}" xmlns="http://www.w3.org/2000/svg"
     aria-label="제어법칙 블록도 최상위 — 설계 순서 ①~⑤가 층으로 쌓인 보드">
  <defs>
    <marker id="bd-arr" markerWidth="10" markerHeight="10" refX="9" refY="5"
            orient="auto" markerUnits="userSpaceOnUse">
      <path d="M0 1 L9 5 L0 9 z"/>
    </marker>
    <filter id="bd-blk" x="-30%" y="-30%" width="170%" height="180%">
      <feDropShadow dx="2" dy="7" stdDeviation="6" flood-color="#0f172a" flood-opacity=".22"/>
    </filter>
    <filter id="bd-sel" x="-40%" y="-40%" width="180%" height="180%">
      <feDropShadow dx="0" dy="8" stdDeviation="9" flood-color="#2563eb" flood-opacity=".45"/>
    </filter>
    <filter id="bd-ground" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="16"/>
    </filter>
  </defs>
${s}
</svg>`;
}

/** 최상위 블록도 마크업 — export는 테스트의 배선 드리프트 가드용 (data-block/
data-page id ↔ SUBSYSTEMS 키·CHAIN 순서 대조, lib/blocks.test.js). */
export const TOP_SVG = buildTopSvg();

/** 최상위 블록도 SVG. onNavigate(pageId) — 블록·층 판 라벨 클릭 시 호출. */
export function topDiagramSvg(onNavigate) {
  const svg = fromMarkup(TOP_SVG);
  for (const node of svg.querySelectorAll("[data-block], [data-page]")) {
    const page = node.dataset.block ?? node.dataset.page;
    const nav = () => onNavigate(page);
    node.addEventListener("click", nav);
    node.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); nav(); }
    });
  }
  return svg;
}
