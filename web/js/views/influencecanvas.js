/** 영향성 캔버스 — Apple 다크모드 씬에 그래프를 그리고 파급을 애니메이션한다.

스타일은 인라인·상수로 준다: `app.css`는 병행 세션 작업 중이라 건드리지 않는다
(views/autocode.js·replayoverlay.js와 같은 회피). 팔레트 정본은 lib/influence.js.

**모양도 색과 같은 정보 채널이다.** 노드가 전부 같은 원이면 파라미터·IR·출력·지표의
구분이 색 하나에만 걸리고, 색각 이상에서는 그 구분이 통째로 사라진다. 그래서 종류마다
윤곽을 다르게 준다 — 파라미터는 스퀘어클, 출력은 캡슐, 지표는 링, 나머지는 원.
테두리는 헤어라인 하나뿐이고, 채도는 가운데 작은 코어에 모은다: 굵은 링으로 두르면
노드가 '풍선'처럼 보이고(이전 스킨의 인상) 발광 레이어가 집어 갈 밝은 점도 없다.

**캔버스인 이유**: 「전체 영향 보기」에서 간선 700개에 발광이 얹힌다. SVG 필터로는
25 fps가 안 나온다. 대신 캔버스는 보조기술에 불투명하므로 **파라미터 표가 정본 표면**이고
(views/influence.js) 이 캔버스는 보조다 — wpmap.js가 웨이포인트 표에 접근성을 맡긴 것과 같다.

**발광을 프레임마다 shadowBlur로 만들지 않는다.** 간선 수백 개에 그림자를 걸면 프레임
예산이 그것만으로 사라진다. 절반 해상도 레이어에 굵게 한 번 그리고 `filter: blur()` +
`lighter`로 **한 번만** 합성한다. 교차점이 밝아지는 것이 홀로그램의 핵심 신호다.

**순차 재생이 이 캔버스의 주된 표현이다.** 파라미터를 고르면 전체가 어두워지고
원뿔이 층을 타고 **한 줄씩 자라며** 연결된다 — 원뿔을 통째로 켜면 "얼마나 넓게
번지나"는 보여도 "무엇이 무엇을 먼저 건드리나"가 화면에서 사라진다. 시각은
`lib/influenceplay.js`가 정하고 여기서는 받은 진행도대로 긋기만 한다.

애니메이션은 setInterval 40 ms(25 fps) + 벽시계 기준 — 이 리포에 rAF는 한 군데도 없다.
*/

import { SKIN, BAND_COLOR, STATE_COLOR, logScale, radiusOf } from "../lib/influence.js";
import { arcPrefix, hitTestNodes, pointAtArc } from "../lib/influencelayout.js";
import { PLAY, captionAt, cycleAt, layerIndexAt } from "../lib/influenceplay.js";

const FRAME_MS = 40; // 25 fps — views/sim.js·replayoverlay.js와 같은 예산
const RING_MS = 320; // 도착 펄스 수명 — 선 끝이 노드에 닿는 순간에 묶여 있다
const HOT_MS = 520; // 도착 직후 노드 헤일로가 커져 있는 시간
const NODE_FADE_MS = 120; // 노드 점등 램프 — 인접 층이 겹치는 대가를 여기서 덮는다
const DIM_ALPHA = 0.16; // 원뿔이 있을 때 나머지 구조를 깔아 두는 밝기 ("모두 어두워지고")
const MAX_PARTICLES = 240;
const GLOW_SCALE = 0.5; // 발광 레이어 해상도 — 흐릴 것이므로 절반이면 충분
const TWINKLE_MS = 1400; // 입자 반짝임 주기 — 흐름(2600 ms)과 어긋나게 둬야 맥놀이가 산다
const WIRE = "235, 235, 245"; // 쉬는 배선·안내선의 중립 회백 — 세 군데가 같은 값을 써야 한다
const FONT = '600 11px -apple-system, "SF Pro Text", "Helvetica Neue", "Malgun Gothic", sans-serif';
// 원뿔 노드의 점등 라벨 — 상시 라벨(캡슐 칩)보다 한 급 가볍게. 원뿔 하나에 노드가
// 60개까지 켜지므로 칩을 다 두르면 배선이 라벨에 묻힌다
const FONT_SMALL = '500 10px -apple-system, "SF Pro Text", "Helvetica Neue", "Malgun Gothic", sans-serif';

const reduceMotion = () =>
  typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

/** 오프스크린 레이어 — **크기·해상도가 같으면 캔버스를 재사용한다.**
 *
 * 매번 새로 만들면 dpr 2에서 장당 ~12 MB를 할당한다. 선택이 바뀔 때마다 다시 굽던
 * 시절에는 클릭 한 번에 두 장이 새로 생겼다. 이제 재굽기는 **레이아웃이 바뀔 때만**이고,
 * 그마저도 같은 크기면 지우고 다시 쓴다.
 */
function ensureLayer(prev, w, h, scale = 1) {
  const dpr = (window.devicePixelRatio || 1) * scale;
  const cw = Math.max(1, Math.round(w * dpr));
  const ch = Math.max(1, Math.round(h * dpr));
  const l = prev && prev.c.width === cw && prev.c.height === ch
    ? prev
    : { c: Object.assign(document.createElement("canvas"), { width: cw, height: ch }), ctx: null };
  if (!l.ctx) l.ctx = l.c.getContext("2d");
  l.ctx.setTransform(1, 0, 0, 1, 0, 0);
  l.ctx.clearRect(0, 0, cw, ch);
  l.ctx.scale(dpr, dpr); // 이후 전부 논리 픽셀 좌표 — 빼먹으면 '흐릿하지만 그럴듯한' 그림이 된다
  l.w = w;
  l.h = h;
  return l;
}

/** 결정적 위상 — Math.random을 쓰면 다시 그릴 때마다 입자가 튄다. */
const phaseOf = (i) => ((i * 2654435761) % 997) / 997;

/** 둥근 사각 — Path2D의 roundRect는 최근 브라우저에만 있어 폴백을 같이 둔다. */
function roundRect(g, x, y, w, h, r) {
  const k = Math.min(r, w / 2, h / 2);
  if (typeof g.roundRect === "function") {
    g.roundRect(x, y, w, h, k);
    return;
  }
  g.moveTo(x + k, y);
  g.arcTo(x + w, y, x + w, y + h, k);
  g.arcTo(x + w, y + h, x, y + h, k);
  g.arcTo(x, y + h, x, y, k);
  g.arcTo(x, y, x + w, y, k);
  g.closePath();
}

/** 라벨이 피해야 할 실제 반폭 — 캡슐은 r보다 넓다. r로만 띄우면 칩이 노드에 물린다. */
const halfExtent = (kind, r) => (kind === "output" ? r * 1.45 : r);

/** 종류별 윤곽 — 색 말고도 모양으로 구분되게. r은 반크기다. */
function nodePath(g, kind, x, y, r) {
  g.beginPath();
  if (kind === "param") roundRect(g, x - r, y - r, r * 2, r * 2, r * 0.62);
  else if (kind === "plant") roundRect(g, x - r, y - r * 0.8, r * 2, r * 1.6, r * 0.5);
  else if (kind === "output") roundRect(g, x - r * 1.45, y - r * 0.7, r * 2.9, r * 1.4, r * 0.7);
  else g.arc(x, y, r, 0, Math.PI * 2);
}

export function createInfluenceCanvas(opts = {}) {
  const {
    getModel, getLayout, getSelection, getCone, getPlay, getLoop, getHeat,
    onSelect, onHover, onCaption, onLayer,
  } = opts;
  let width = opts.width ?? 1180;
  let height = opts.height ?? 620;

  const view = document.createElement("canvas");
  const ctx = view.getContext("2d");
  // CSS 크기는 resize()가 정한다: 논리 폭 + max-width:100% + aspect-ratio —
  // 좁은 화면(폰)에서는 비율을 지킨 채 통째로 줄어 전체가 보인다. width:100%에
  // 높이 px 고정이던 시절의 찌그러짐은 aspect-ratio가 막는다. 포인터 매핑은 rect
  // 비율로 환산하므로(아래 toXY) 축소돼도 좌표는 정확하다
  // margin:0 auto — 넓은 데스크톱에서 박스 중앙(우측 검은 띠 방지)
  view.style.cssText =
    "display:block;margin:0 auto;border-radius:16px;border:1px solid rgba(255,255,255,.08);" +
    "box-shadow:inset 0 1px 0 rgba(255,255,255,.06),0 18px 44px rgba(0,0,0,.55);" +
    "touch-action:none;cursor:default;outline:none";
  view.tabIndex = 0;
  view.setAttribute("role", "img");
  // role="img"에 이름이 없으면 스크린리더가 "그래픽"이라고만 읽는다. 상세는 아래
  // 파라미터 표가 맡으므로(이 캔버스는 보조) 여기서는 무엇을 그린 그림인지와
  // 어디서 읽어야 하는지를 알려 준다
  view.setAttribute(
    "aria-label",
    "제어법칙 영향성 그래프 — 파라미터에서 IR 노드·법칙 출력·설계 지표로 이어지는 " +
      "영향 경로. 수치와 상태는 아래 파라미터 표에서 읽을 수 있다.",
  );

  let bg = null;
  let struct = null;
  let glow = null;
  let timer = null;
  let t0 = 0; // 입자 흐름의 원점 — 재생과 **무관한 별개 시계**다(유지 구간에 흐르는 것이 이것)
  let playAt = 0; // 재생 t=0의 벽시계 앵커 (sim.js·replayoverlay.js의 anchor()와 같은 규약)
  let hover = null;
  let lastSel = null;
  let lastLayout = null;
  let structFor = null; // struct를 구울 때의 레이아웃 신원 — 선택이 바뀌어도 다시 굽지 않는다
  let lastCaption = "";
  let lastLayer = "unset"; // 숫자·null과 안 겹치는 초기값 — 첫 프레임에 반드시 알린다
  let mounted = false;
  let activeCache = { key: null, layout: null, list: [] };

  function resize(w, h) {
    width = Math.max(320, Math.round(w));
    height = Math.max(240, Math.round(h));
    const dpr = window.devicePixelRatio || 1;
    view.width = Math.round(width * dpr);
    view.height = Math.round(height * dpr);
    // 좁은 화면(폰)에서는 **비율을 지킨 채 통째로 줄어든다** — width만 줄고 height가
    // px로 남던 시절이 찌그러짐의 원인이었으므로, 높이는 aspect-ratio가 폭을 따라
    // 정하게 한다. 가로 스크롤 대신 전체가 한눈에 들어온다(글자는 작아지지만 폰에서의
    // 요구가 "다 보이게"다). 포인터 매핑은 rect 비율 환산(toXY)이라 축소돼도 정확하다
    view.style.width = `${width}px`;
    view.style.maxWidth = "100%";
    view.style.height = "auto";
    view.style.aspectRatio = `${width} / ${height}`;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.scale(dpr, dpr);
    bg = null;
    struct = null;
    structFor = null;
    glow = ensureLayer(glow, width, height, GLOW_SCALE);
  }

  // ── 배경: 중립 흑회색 + 아주 흐린 광원 둘 + 비네트 ─────────────────────
  // 점 격자는 뺐다 — 26 px 도트는 '테크 배경' 상투구이고, 성긴 IR 위에 깔리면 노드보다
  // 격자가 먼저 눈에 들어온다. 깊이는 광원과 비네트가 낸다
  function paintBg() {
    const l = ensureLayer(bg, width, height);
    const g = l.ctx;
    const lin = g.createLinearGradient(0, 0, width * 0.35, height);
    lin.addColorStop(0, SKIN.bg2);
    lin.addColorStop(0.55, SKIN.bg1);
    lin.addColorStop(1, SKIN.bg0);
    g.fillStyle = lin;
    g.fillRect(0, 0, width, height);
    for (const [cx, cy, rx, color] of [
      [width * 0.72, -height * 0.12, Math.max(width, height) * 0.85, SKIN.glowA],
      [width * 0.04, height * 1.14, Math.max(width, height) * 0.66, SKIN.glowB],
    ]) {
      const rg = g.createRadialGradient(cx, cy, 0, cx, cy, rx);
      rg.addColorStop(0, color);
      rg.addColorStop(1, "rgba(0,0,0,0)");
      g.fillStyle = rg;
      g.fillRect(0, 0, width, height);
    }
    const vg = g.createRadialGradient(
      width / 2, height / 2, Math.min(width, height) * 0.3,
      width / 2, height / 2, Math.max(width, height) * 0.75);
    vg.addColorStop(0, "rgba(0,0,0,0)");
    vg.addColorStop(1, "rgba(0,0,0,.5)");
    g.fillStyle = vg;
    g.fillRect(0, 0, width, height);
    return l;
  }

  // ── 정적 구조: 쉬고 있는 **전체** 그래프 (레이아웃이 바뀔 때만 다시 굽는다) ──
  // 선택과 무관하다. 원뿔은 이 위에 매 프레임 진행도대로 그려지고, 선택이 있으면
  // 이 레이어를 통째로 흐리게 깔아 "모두 어두워진" 바탕을 만든다
  function paintStruct(model, layout) {
    const l = ensureLayer(struct, width, height);
    const g = l.ctx;
    g.lineCap = "round";
    g.lineJoin = "round";

    // 층 안내선 — 성긴 IR을 감추지 않고 "16단을 거친다"를 읽히게 한다
    g.strokeStyle = `rgba(${WIRE}, .05)`;
    g.lineWidth = 1;
    for (const x of layout.rankX ?? []) {
      g.beginPath();
      g.moveTo(x, 8);
      g.lineTo(x, layout.bounds.h - 8);
      g.stroke();
    }

    for (const e of layout.edges) {
      g.strokeStyle = edgeColor(e, model, 0.34, null);
      g.lineWidth = 1;
      if (e.kind === "ghost" || e.kind === "declared") g.setLineDash([4, 4]);
      else if (e.kind === "offgraph") g.setLineDash([2, 5]);
      strokeEdge(g, e);
      g.setLineDash([]);
    }

    for (const n of model.nodes) {
      const p = layout.pos.get(n.id);
      if (p) drawNode(g, n, p, 1);
    }
    return l;
  }

  function strokeEdge(g, e) {
    const b = e.bez;
    g.beginPath();
    g.moveTo(b.x0, b.y0);
    g.bezierCurveTo(b.c1x, b.c1y, b.c2x, b.c2y, b.x1, b.y1);
    g.stroke();
  }

  /** 호길이 0..s만 긋는다 — 원뿔 간선은 **자라는 중이든 완성이든 항상 이쪽**이다.
   *  완성 순간에 베지어로 갈아타면 표본 오차만큼 선이 튄다. 전환 자체를 없앤다. */
  function strokeEdgeTo(g, e, s) {
    const { n, last } = arcPrefix(e.flat, s);
    if (n < 1) return;
    const pts = e.flat.pts;
    g.beginPath();
    g.moveTo(pts[0].x, pts[0].y);
    for (let i = 1; i < n; i += 1) g.lineTo(pts[i].x, pts[i].y);
    if (last) g.lineTo(last.x, last.y);
    g.stroke();
  }

  /** 간선 진행도 — 원뿔 밖이면 null. 재생이 없으면(빈 원뿔) 완성으로 본다. */
  function edgeProgress(play, idx, t) {
    const v = play?.edges.get(idx);
    if (!v) return null;
    const span = v.t1 - v.t0;
    return span > 0 ? Math.max(0, Math.min(1, (t - v.t0) / span)) : 1;
  }

  /** 노드 점등 0..1 — 도착 직전부터 밝아지는 램프.
   *
   * 인접 층이 겹치므로(층 150 ms vs 성장 180 ms) 나가는 선이 출발할 때 소스 노드는
   * 아직 도착 30 ms 전이다. 램프가 없으면 **어두운 노드에서 선이 나가는** 장면이 된다.
   * 도착 순간 정확히 1.0이므로 "선이 닿아야 켜진다"는 규칙 자체는 지켜진다.
   */
  function nodeOn(play, id, t) {
    const v = play?.nodes.get(id);
    if (!v) return 0;
    if (v.at <= 0) return 1;
    return Math.max(0, Math.min(1, (t - v.at + NODE_FADE_MS) / NODE_FADE_MS));
  }

  // ── 원뿔: 매 프레임 메인 ctx에 진행도대로 ────────────────────────────
  function paintCone(g, model, layout, cone, play, t, fade, tint) {
    g.save();
    g.lineCap = "round";
    g.lineJoin = "round";
    for (const e of layout.edges) {
      if (!cone.edges.has(e.idx)) continue;
      const s = edgeProgress(play, e.idx, t);
      if (s === null || s <= 0) continue;
      g.strokeStyle = edgeColor(e, model, 0.62 * fade, tint);
      g.lineWidth = e.kind === "ghost" ? 1 : 1.3;
      if (e.kind === "ghost" || e.kind === "declared") g.setLineDash([4, 4]);
      else if (e.kind === "offgraph") g.setLineDash([2, 5]);
      strokeEdgeTo(g, e, s);
      g.setLineDash([]);
    }
    for (const n of model.nodes) {
      if (!cone.nodes.has(n.id)) continue;
      const on = nodeOn(play, n.id, t);
      if (on <= 0) continue;
      const p = layout.pos.get(n.id);
      if (p) drawNode(g, n, p, on * fade);
    }
    g.restore();
  }

  /** 선택된 파라미터의 상태 색 — 원뿔 전체가 그 색으로 켜진다.
   *  「덮임」을 골랐는데 원뿔이 파랗게 켜지면 상태와 그림이 서로 다른 말을 한다. */
  function coneTint(model, sel) {
    if (!sel) return null;
    return STATE_COLOR[model.byId.get(sel)?.state] ?? SKIN.blue;
  }

  function edgeColor(e, model, alpha, tint) {
    if (e.kind === "param") {
      const st = model.byId.get(e.src)?.state ?? "live";
      const c = STATE_COLOR[st] ?? SKIN.blue;
      return withAlpha(c, alpha * (st === "inert" ? 0.5 : 1));
    }
    if (e.kind === "ghost") return withAlpha(SKIN.orange, alpha);
    if (e.kind === "offgraph") return withAlpha(SKIN.gray, alpha * 0.8);
    if (e.kind === "declared") return withAlpha(SKIN.orange, alpha * 0.65);
    if (e.kind === "boundary") return withAlpha(SKIN.indigo, alpha);
    // 쉬고 있는 IR 배선은 무채색 헤어라인이다 — 파랗게 물들여 두면 넓은 면이 전부
    // 채도를 갖고, 정작 선택했을 때 켜지는 색이 대비를 못 얻는다
    return tint ? withAlpha(tint, alpha * 0.8) : `rgba(${WIRE}, ${alpha * 0.4})`;
  }

  /** 색 + 알파. `#rrggbb`와 `rgb()/rgba()` 문자열을 둘 다 받는다 — hex 전용으로 두면
   *  팔레트를 손질하다 SKIN의 rgba 항목이 섞이는 순간 parseInt가 NaN을 내고
   *  그 노드·간선이 **오류 없이 사라진다**(가장 찾기 어려운 종류의 고장이다). */
  function withAlpha(c, a) {
    if (c[0] !== "#") {
      const [r, g, b] = c.slice(c.indexOf("(") + 1, c.lastIndexOf(")")).split(",");
      return `rgba(${r.trim()}, ${g.trim()}, ${b.trim()}, ${a})`;
    }
    const n = parseInt(c.slice(1), 16);
    return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
  }

  function nodeColor(n) {
    if (n.kind === "param") return STATE_COLOR[n.state] ?? SKIN.blue;
    if (n.kind === "ghost") return SKIN.orange;
    if (n.kind === "metric") return SKIN.orange;
    if (n.kind === "plant") return SKIN.indigo;
    return BAND_COLOR[n.band] ?? SKIN.blue;
  }

  function drawNode(g, n, p, alpha, boost = 0) {
    const r = p.r + boost;
    const c = nodeColor(n);
    const ring = n.kind === "metric"; // 지표는 속이 빈 링 — 법칙 밖의 결과라는 뜻
    g.globalAlpha = alpha;
    nodePath(g, n.kind, p.x, p.y, r);
    g.fillStyle = withAlpha(c, ring ? 0.05 : 0.14 + 0.34 * boost);
    g.fill();
    g.lineWidth = n.kind === "ghost" ? 1 : ring ? 2.2 : 1;
    if (n.kind === "ghost") g.setLineDash([2.5, 3]);
    g.strokeStyle = withAlpha(c, n.kind === "ghost" ? 0.55 : ring ? 0.85 : 0.7);
    g.stroke();
    g.setLineDash([]);
    // 점등된 코어 — 발광 레이어가 집어 가는 밝은 점. '반짝'은 여기서 시작한다
    if (!ring && n.kind !== "ghost") {
      g.beginPath();
      g.arc(p.x, p.y, Math.max(1, r * 0.4), 0, Math.PI * 2);
      g.fillStyle = withAlpha(c, 0.85 + 0.15 * boost);
      g.fill();
    }
    g.globalAlpha = 1;
  }

  // ── 프레임 ─────────────────────────────────────────────────────────────
  function frame() {
    // 라우터는 떠나는 뷰에 정리 훅을 주지 않는다 (main.js route()는 새 뷰의 render()만
    // 부른다) — 다른 탭으로 가면 이 타이머가 **분리된 캔버스**를 향해 25 fps로 영원히
    // 돈다. 뷰가 dispose를 불러 줄 때까지 기다리지 말고 스스로 멈춘다
    // 단, **한 번이라도 붙은 뒤에만** 종료한다 — 생성 직후의 첫 프레임은 뷰가 아직
    // append하기 전이라 isConnected가 false다. 그걸 종료 신호로 읽으면 타이머가
    // 태어나자마자 죽어 화면이 정지 그림이 된다
    if (view.isConnected) mounted = true;
    else if (mounted) {
      if (timer) clearInterval(timer);
      timer = null;
      return;
    }
    // `document.hidden`으로 프레임을 건너뛰지 않는다 — 배경 탭에서 로드되면 첫 페인트까지
    // 삼켜 캔버스가 빈 채로 남는다(실제로 그렇게 만들었다가 되돌렸다). 진짜 낭비였던
    // 경우(탭을 떠난 뒤 영원히 도는 것)는 위 isConnected가 막는다
    const model = getModel?.();
    const layout = getLayout?.();
    if (!model || !layout) return;
    const sel = getSelection?.() ?? null;
    const cone = getCone?.() ?? null;
    const play = getPlay?.() ?? null;

    // 선택이 바뀌거나 **배치가 바뀌면** 처음부터 다시 튼다. 배치를 A→C로 바꾸면
    // 좌표가 전부 새것이라 재생 도중의 진행도를 이어받는 것이 의미가 없다
    if (sel !== lastSel || layout !== lastLayout) {
      lastSel = sel;
      lastLayout = layout;
      playAt = performance.now();
    }
    if (!struct || structFor !== layout) {
      struct = paintStruct(model, layout);
      structFor = layout;
    }
    if (!bg) bg = paintBg();

    const now = performance.now();
    // 재생 위치를 정하는 자리는 **여기 한 곳뿐**이다. 동작 축소에서는 타이머가 아예
    // 없어 진행시킬 틱이 없으므로 완료 상태(t = playMs)로 착지시킨다 — 그러면
    // 간선 s=1 · 노드 on=1 · 링과 hot은 수명 초과로 꺼짐 · 자막은 요약이 전부 따라온다
    const still = !timer;
    const { t, u, fade } = still || !play
      ? { t: play?.playMs ?? 0, u: Infinity, fade: 1 }
      : cycleAt(now - playAt, { playMs: play.playMs, holdMs: PLAY.holdMs, loop: getLoop?.() !== false });

    ctx.clearRect(0, 0, width, height);
    ctx.drawImage(bg.c, 0, 0, width, height);
    // 원뿔이 있으면 나머지 구조를 통째로 흐리게 깐다 — "모두 다 어두워지고"
    ctx.globalAlpha = cone ? DIM_ALPHA : 1;
    ctx.drawImage(struct.c, 0, 0, width, height);
    ctx.globalAlpha = 1;

    const tint = coneTint(model, sel);
    if (cone) paintCone(ctx, model, layout, cone, play, t, fade, tint);

    paintGlow(model, layout, cone, play, t, u, fade, tint, now);
    ctx.save();
    if (typeof ctx.filter === "string") ctx.filter = "blur(7px)";
    ctx.globalCompositeOperation = "lighter";
    ctx.drawImage(glow.c, 0, 0, width, height);
    if (typeof ctx.filter === "string") ctx.filter = "none";
    // filter 미지원 폴백 — 살짝 어긋나게 세 번 더해 번짐을 흉내낸다
    if (typeof ctx.filter !== "string") {
      ctx.globalAlpha = 0.3;
      for (const [dx, dy] of [[-1.5, 0], [1.5, 0], [0, 1.5]]) {
        ctx.drawImage(glow.c, dx, dy, width, height);
      }
      ctx.globalAlpha = 1;
    }
    ctx.restore();

    drawLabels(ctx, model, layout, cone, play, t, sel, fade);

    // 자막은 **문자열이 바뀔 때만** 내보낸다 — 25 fps로 DOM을 만지지 않는다(층당 1회)
    if (onCaption) {
      const text = cone ? captionAt(play, t, (id) => model.byId.get(id)?.label ?? id) : "";
      if (text !== lastCaption) {
        lastCaption = text;
        onCaption(text);
      }
    }
    // 경로 패널 동기화 — 자막과 같은 절약 규약: 층이 바뀌는 프레임에만 알린다.
    // 판정은 자막과 **같은 함수**(layerIndexAt)다 — 여기서 복제하면 경계가 어긋나도
    // 칩과 자막이 각자 그럴듯해서 못 알아챈다. null = 선택 없음
    if (onLayer) {
      const li = cone ? layerIndexAt(play, t) : null;
      if (li !== lastLayer) {
        lastLayer = li;
        onLayer(li);
      }
    }
  }

  function paintGlow(model, layout, cone, play, t, u, fade, tint, now) {
    const g = glow.ctx;
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.clearRect(0, 0, glow.c.width, glow.c.height);
    const dpr = (window.devicePixelRatio || 1) * GLOW_SCALE;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.lineCap = "round";

    const heat = getHeat?.() ?? null;
    // 프레임마다 간선 수만큼 배열을 새로 만들지 않는다 — 선택이 바뀔 때만 다시 만든다.
    // 키에 **레이아웃 신원**도 넣는다: 후보를 A→B로 바꾸면 선택은 그대로인데 간선
    // 객체(좌표·곡선)가 전부 새것이라, 선택만 보면 옛 좌표에 입자를 뿌리게 된다
    const key = cone ? lastSel : "__all__";
    if (activeCache.key !== key || activeCache.layout !== layout) {
      const pick = [];
      for (const e of layout.edges) {
        if (cone ? cone.edges.has(e.idx) : e.kind === "ir") pick.push(e);
      }
      activeCache = { key, layout, list: pick };
    }
    const active = activeCache.list;

    // 굵은 밑칠 — 이게 흐려져서 발광이 된다. **선과 같은 진행도로 잘라야 한다**:
    // 안 자르면 발광이 선보다 먼저 원뿔 전체를 드러내 순차 재생이 무의미해진다
    for (const e of active) {
      const s = cone ? edgeProgress(play, e.idx, t) : 1;
      if (s === null || s <= 0) continue;
      const w = heat ? 1 + 4 * logScale(heat.get(e.dst)?.rel) : 2;
      g.strokeStyle = edgeColor(e, model, (cone ? 0.5 : 0.16) * fade, tint);
      g.lineWidth = w * 2.1;
      if (s >= 1) strokeEdge(g, e);
      else strokeEdgeTo(g, e, s);
    }

    const still = !timer;
    // 상한은 **총 입자 수**여야 한다. per를 반올림으로 구하면 간선이 많을 때
    // per=2가 되어 총량이 상한을 넘고(실측: 간선 141개 원뿔에서 282개), 상한이
    // 아니라 장식이 된다. per를 내림으로 잡고 예산으로 한 번 더 막는다
    const per = Math.max(1, Math.floor(MAX_PARTICLES / Math.max(1, active.length)));
    let budget = MAX_PARTICLES;
    for (let k = 0; k < active.length && budget > 0; k += 1) {
      const e = active[k];
      if (!e.flat.len) continue;
      // **다 자란 간선에만** 입자를 뿌린다 — 절반만 자란 선에 뿌리면 선 끝을 넘어 날아간다
      if (cone && !(edgeProgress(play, e.idx, t) >= 1)) continue;
      const i = e.idx;
      for (let j = 0; j < per && budget > 0; j += 1) {
        budget -= 1;
        // `u`로 두면 paintGlow의 매개변수 u(주기 내 위치, ms)를 가린다 — 여기는
        // 호길이 비율 0..1이라 단위부터 다르다. 나중에 "유지 구간에만 입자를"
        // 같은 걸 이 루프에 넣으면 ms 대신 비율을 읽어 조용히 항상 참이 된다
        const along = still
          ? (0.5 + j / per) % 1
          : ((now - t0) / 2600 + phaseOf(i) + j / per) % 1;
        const p = pointAtArc(e.flat, along);
        // 반짝임 — 흐름 주기(2600 ms)와 어긋난 주기로 밝기·크기를 같이 흔든다.
        // 위상은 간선·입자마다 결정적으로 달라서 전체가 한꺼번에 깜빡이지 않는다.
        // 정지 프레임은 **평균**이어야 한다: 1로 굳히면 크기·밝기가 동시에 최대가 되고
        // lighter 합성이라 교차부가 흰색으로 포화한다
        const tw = still
          ? 0.5
          : 0.5 + 0.5 * Math.sin((now / TWINKLE_MS + phaseOf(i * 37 + j)) * Math.PI * 2);
        g.beginPath();
        g.arc(p.x, p.y, 1.35 + 0.95 * tw, 0, Math.PI * 2);
        g.fillStyle = edgeColor(e, model, (0.5 + 0.5 * tw) * fade, tint);
        g.fill();
      }
    }

    // 수명이 있는 표현(도착 펄스·hot)은 **클램프하지 않은 `u`**로 잰다.
    //
    // `t`로 재면 둘 중 하나가 깨진다: `t <= playMs`를 그대로 쓰면 t가 유지 구간 내내
    // playMs에 고정돼 마지막 도착 노드(age≈0)의 링·hot이 3.8 s 동안 박히고(동작
    // 축소에서는 영구 정지 프레임), `t < playMs`로 끊으면 **playMs가 곧 마지막 도착
    // 시각**이라 마지막 층(지표 8개 + 기체 — 재생의 클라이맥스)의 펄스가 아예 안 뜬다.
    // `u`는 완료 뒤에도 계속 자라므로 펄스가 제 수명만큼 감쇠하고 저절로 사라진다
    const arriveAge = (at) => u - at;

    // 도착 펄스 — 선 끝이 노드에 닿는 **그 프레임**에 터진다.
    // 진행도 이름은 이 함수 안 어느 것도 가리지 않게 고른다: `u`는 주기 내 위치(ms),
    // `k`는 위쪽 입자 루프의 active 인덱스다. 갈림은 이름이 아니라 **읽는 위치**다:
    // `u`의 유일한 참조(arriveAge)가 이 블록 **위**에 있어 인라인이 항상 선언 앞에
    // 떨어지므로 같은 블록의 TDZ ReferenceError로 **터지고**,
    // `k`로 두면 형제 스코프라 안 터지는 대신 블록을 합칠 때 조용히 엉뚱한 값을 읽는다
    if (cone && play) {
      for (const [id, v] of play.nodes) {
        if (v === null) continue;
        const age = arriveAge(v.at);
        if (age < 0 || age > RING_MS) continue;
        const p = layout.pos.get(id);
        if (!p) continue;
        const grow = age / RING_MS;
        g.beginPath();
        g.arc(p.x, p.y, p.r + 3 + 26 * grow, 0, Math.PI * 2);
        g.strokeStyle = withAlpha(tint ?? SKIN.blue, (1 - grow) * 0.8 * fade);
        g.lineWidth = 2.2;
        g.stroke();
      }
    }

    // 노드 헤일로 — **선택이 없어도 돈다.** 여기 위에 early return을 두면 탭에 처음
    // 들어와 아무것도 안 고른 상태(사용자가 가장 먼저 보는 화면)에서 노드 165개의
    // 코어 발광이 통째로 사라져 홀로그램이 평평해진다
    for (const nd of model.nodes) {
      if (cone && !cone.nodes.has(nd.id)) continue;
      const v = cone ? play?.nodes.get(nd.id) : null;
      if (cone && !v) continue;
      const on = cone ? nodeOn(play, nd.id, t) : 1;
      if (on <= 0) continue;
      const age = v ? arriveAge(v.at) : Infinity;
      // 도착 직후의 뜨거움은 **램프로 식힌다.** 불리언으로 두면 age가 HOT_MS를 넘는
      // 프레임에 반지름과 알파가 한 번에 튀는데, 마지막 층 간선들은 시차가 spread
      // (≤120 ms) 안에 몰려 있어 지표 8개 + 기체의 만료가 3프레임 창에 겹친다 —
      // 유지 구간에 막 들어서서 입자 말고는 화면이 정지한 때라 그 계단이 그대로 보인다.
      // 양끝 값은 종전과 같다(age=0 → 2.4r·0.55, age≥HOT_MS → 1.5r·0.2)
      // 이름이 `heat`가 아닌 이유: 이 함수 위쪽(paintGlow 머리)의 `heat`는 개루프 Δ
      // 히트맵이다. 가려 두면 나중에 노드 굵기를 Δ로 물들일 때 조용히 엉뚱한 값을 쓴다
      const flare = age >= 0 ? Math.max(0, 1 - age / HOT_MS) : 0;  // Infinity·미도착이면 0
      const p = layout.pos.get(nd.id);
      if (!p) continue;
      g.beginPath();
      g.arc(p.x, p.y, p.r * (1.5 + 0.9 * flare), 0, Math.PI * 2);
      g.fillStyle = withAlpha(nodeColor(nd), (0.2 + 0.35 * flare) * on * fade);
      g.fill();
    }
  }

  function drawLabels(g, model, layout, cone, play, t, sel, fade = 1) {
    g.font = FONT;
    // SF는 기본 자간이 넓다 — 11 px 캡슐에서는 살짝 조여야 애플 UI처럼 읽힌다.
    // measureText도 같은 자간을 쓰므로 칩 폭은 저절로 맞는다
    if ("letterSpacing" in g) g.letterSpacing = "-0.01em";
    g.textBaseline = "middle";
    const show = new Set();
    if (sel) show.add(sel);
    if (hover) show.add(hover);
    for (const nd of model.nodes) {
      if (nd.kind === "plant" || nd.kind === "metric" || nd.kind === "output") show.add(nd.id);
    }
    for (const id of show) {
      const nd = model.byId.get(id);
      const p = layout.pos.get(id);
      if (!nd || !p) continue;
      const text = nd.label ?? nd.id;
      const w = g.measureText(text).width;
      // 라벨은 노드 오른쪽에 붙이되, 캔버스를 넘칠 것 같으면 왼쪽으로 뒤집는다.
      // 여백만 키워 두면 배치가 조금만 바뀌어도 글자가 다시 잘린다 — 자기교정이 낫다
      // 출력(조종면)도 **오른쪽**이다: 왼쪽에는 원뿔 재생의 IR 점등 라벨이 서므로
      // 왼쪽 라벨은 그것들과 겹친다. 오른쪽은 기체 열까지의 빈 구간이라 자리가 있고,
      // 기체는 위, 지표는 오른쪽 끝 — 겹칠 만한 이웃끼리는 방향이 갈린다
      const hw = halfExtent(nd.kind, p.r);
      let side = nd.kind === "metric" || nd.kind === "output" ? 1 : 0;
      if (side === 1 && p.x + hw + 12 + w + 12 > width - 4) side = -1;
      if (side === -1 && p.x - hw - 12 - w - 12 < 4) side = 1;
      g.textAlign = side === 1 ? "left" : side === -1 ? "right" : "center";
      const x = side === 1 ? p.x + hw + 12 : side === -1 ? p.x - hw - 12 : p.x;
      const y = side === 0 ? p.y - p.r - 13 : p.y;
      // 캡슐 칩 — 애플이 지도·비디오 위에 글자를 얹을 때 쓰는 반투명 재질.
      // 각진 상자는 배선 위에서 '오려붙인' 티가 난다
      const bx = side === 1 ? x - 6 : side === -1 ? x - w - 6 : x - w / 2 - 6;
      g.beginPath();
      roundRect(g, bx, y - 9, w + 12, 18, 9);
      g.fillStyle = withAlpha(SKIN.raised, 0.82);
      g.fill();
      g.strokeStyle = SKIN.hairline;
      g.lineWidth = 1;
      g.stroke();
      // 원뿔 밖은 물론, **아직 선이 닿지 않은** 노드의 이름도 흐리게 — 라벨만 먼저
      // 또렷하면 "이미 도달했다"로 읽혀 재생이 말하는 순서와 어긋난다
      const lit = !cone || (cone.nodes.has(id) && nodeOn(play, id, t) > 0.5);
      g.fillStyle = lit ? SKIN.ink : SKIN.inkFaint;
      g.fillText(text, x, y);
    }

    // 원뿔 노드는 **켜지는 순간 이름이 함께 나타난다** — 어느 노드가 지금 활성화됐는지
    // 캔버스만 보고도 읽게 한다. 알파를 점등 램프(nodeOn)에 묶어 선이 닿을 때 글자도
    // 같이 떠오른다. 상시 라벨(출력·기체·지표·선택·hover)이 이미 있는 노드는 제외.
    // 캡슐 칩 대신 작은 글자 + 어두운 밑판 — 원뿔 하나에 60개까지 켜지는 라벨이라
    // 칩으로 두르면 배선이 라벨에 묻힌다
    if (cone) {
      g.font = FONT_SMALL;
      for (const nd of model.nodes) {
        if (!cone.nodes.has(nd.id) || show.has(nd.id)) continue;
        const on = nodeOn(play, nd.id, t);
        if (on <= 0) continue;
        const p = layout.pos.get(nd.id);
        if (!p) continue;
        const text = nd.label ?? nd.id;
        const w = g.measureText(text).width;
        // 오른쪽에 붙이되 캔버스를 넘치면 왼쪽으로 — 상시 라벨과 같은 자기교정
        const right = p.x + p.r + 5 + w + 4 <= width - 2;
        const x = right ? p.x + p.r + 5 : p.x - p.r - 5 - w;
        // fade를 같이 곱는다 — 주기 끝 페이드아웃에서 원뿔은 꺼지는데 라벨만
        // 불투명하게 떠 있으면 되감기 이음새에서 글자 60개가 툭 사라진다
        g.globalAlpha = on * fade;
        g.beginPath();
        roundRect(g, x - 3, p.y - 7, w + 6, 14, 7);
        g.fillStyle = "rgba(0,0,0,.55)";
        g.fill();
        g.textAlign = "left";
        g.fillStyle = SKIN.ink;
        g.fillText(text, x, p.y);
        g.globalAlpha = 1;
      }
      g.font = FONT;  // 되돌린다 — 상시 라벨의 measureText가 이 상태를 이어받는다
    }
  }

  // ── 상호작용 ───────────────────────────────────────────────────────────
  // k = CSS 축소 배율(논리 px / 화면 px). 폰에서 캔버스가 ~40%로 줄면 논리 11 px
  // 허용 반경이 화면에서 4-5 px가 되어 노드를 사실상 못 누른다 — 좌표만이 아니라
  // **허용 반경도** 같은 비율로 환산해야 손끝 기준 크기가 유지된다
  const toXY = (ev) => {
    const r = view.getBoundingClientRect();
    return {
      x: ((ev.clientX - r.left) / r.width) * width,
      y: ((ev.clientY - r.top) / r.height) * height,
      k: r.width > 0 ? Math.max(1, width / r.width) : 1,
    };
  };
  view.addEventListener("pointermove", (ev) => {
    const layout = getLayout?.();
    if (!layout) return;
    const { x, y, k } = toXY(ev);
    const id = hitTestNodes(layout.pos, x, y, { radius: 11 * k });
    if (id !== hover) {
      hover = id;
      view.style.cursor = id ? "pointer" : "default";
      onHover?.(id);
      // 동작 축소에서는 타이머가 없어 다음 틱이 오지 않는다 — 커서는 pointer로
      // 바뀌어 "여기 뭔가 있다"고 약속해 놓고 라벨은 영영 안 뜬다 (select()와 같은 이유)
      if (!timer) frame();
    }
  });
  view.addEventListener("pointerleave", () => {
    hover = null;
    onHover?.(null);
    if (!timer) frame();
  });
  view.addEventListener("click", (ev) => {
    const layout = getLayout?.();
    if (!layout) return;
    const { x, y, k } = toXY(ev);
    onSelect?.(hitTestNodes(layout.pos, x, y, { radius: 11 * k }));
  });
  view.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") {
      ev.preventDefault();
      onSelect?.(null);
    }
  });

  resize(width, height);
  t0 = performance.now();
  playAt = t0;
  if (!reduceMotion()) timer = setInterval(frame, FRAME_MS);
  frame();

  return {
    root: view,
    /** 선택이 바뀌었다 — 레이어는 그대로 두고 다시 그리기만. 동작 축소에서 필수.
     *  (타이머가 없으면 frame()을 부르는 유일한 경로다) */
    redraw() {
      frame();
    },
    /** 모델이 통째로 바뀌었다 — 구운 레이어를 버린다. */
    invalidate() {
      bg = null;
      struct = null;
      structFor = null;
      frame();
    },
    setSize(w, h) {
      resize(w, h);
      frame();
    },
    dispose() {
      if (timer) clearInterval(timer);
      timer = null;
    },
  };
}
