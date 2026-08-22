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

애니메이션은 setInterval 40 ms(25 fps) + 벽시계 기준 — 이 리포에 rAF는 한 군데도 없다.
*/

import { SKIN, BAND_COLOR, STATE_COLOR, coneOf, logScale, radiusOf } from "../lib/influence.js";
import { hitTestNodes, pointAtArc, wavefrontSchedule } from "../lib/influencelayout.js";

const FRAME_MS = 40; // 25 fps — views/sim.js·replayoverlay.js와 같은 예산
const WAVE_MS = 420; // 파급 링 수명
const WAVE_RANK_MS = 90;
const MAX_PARTICLES = 240;
const GLOW_SCALE = 0.5; // 발광 레이어 해상도 — 흐릴 것이므로 절반이면 충분
const TWINKLE_MS = 1400; // 입자 반짝임 주기 — 흐름(2600 ms)과 어긋나게 둬야 맥놀이가 산다
const WIRE = "235, 235, 245"; // 쉬는 배선·안내선의 중립 회백 — 세 군데가 같은 값을 써야 한다
const FONT = '600 11px -apple-system, "SF Pro Text", "Helvetica Neue", "Malgun Gothic", sans-serif';

const reduceMotion = () =>
  typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

function makeLayer(w, h, scale = 1) {
  const dpr = (window.devicePixelRatio || 1) * scale;
  const c = document.createElement("canvas");
  c.width = Math.max(1, Math.round(w * dpr));
  c.height = Math.max(1, Math.round(h * dpr));
  const ctx = c.getContext("2d");
  ctx.scale(dpr, dpr); // 이후 전부 논리 픽셀 좌표 — 여기를 빼먹으면 '흐릿하지만 그럴듯한' 그림이 된다
  return { c, ctx, w, h };
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
  const { getModel, getLayout, getSelection, getHeat, onSelect, onHover } = opts;
  let width = opts.width ?? 1180;
  let height = opts.height ?? 620;

  const view = document.createElement("canvas");
  const ctx = view.getContext("2d");
  view.style.cssText =
    "display:block;width:100%;border-radius:16px;border:1px solid rgba(255,255,255,.08);" +
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
  let t0 = 0;
  let waveAt = 0;
  let wave = null;
  let hover = null;
  let lastSel = null;
  let mounted = false;
  let activeCache = { key: null, layout: null, list: [] };

  function resize(w, h) {
    width = Math.max(320, Math.round(w));
    height = Math.max(240, Math.round(h));
    const dpr = window.devicePixelRatio || 1;
    view.width = Math.round(width * dpr);
    view.height = Math.round(height * dpr);
    view.style.height = `${height}px`;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.scale(dpr, dpr);
    bg = null;
    struct = null;
    glow = makeLayer(width, height, GLOW_SCALE);
  }

  // ── 배경: 중립 흑회색 + 아주 흐린 광원 둘 + 비네트 ─────────────────────
  // 점 격자는 뺐다 — 26 px 도트는 '테크 배경' 상투구이고, 성긴 IR 위에 깔리면 노드보다
  // 격자가 먼저 눈에 들어온다. 깊이는 광원과 비네트가 낸다
  function paintBg() {
    const l = makeLayer(width, height);
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

  // ── 정적 구조: 간선 + 노드 (선택이 바뀔 때만 다시 굽는다) ──────────────
  function paintStruct(model, layout, cone) {
    const l = makeLayer(width, height);
    const g = l.ctx;
    const dim = cone ? 0.1 : 0.34;
    const tint = coneTint(model);
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

    layout.edges.forEach((e, i) => {
      const inCone = cone?.edges.has(i);
      if (cone && !inCone) return; // 원뿔 밖은 흐린 층에 한 번에 그린다 (아래)
      g.strokeStyle = edgeColor(e, model, inCone ? 0.6 : dim, inCone ? tint : null);
      g.lineWidth = e.kind === "ghost" ? 1 : inCone ? 1.2 : 1;
      if (e.kind === "ghost" || e.kind === "declared") g.setLineDash([4, 4]);
      else if (e.kind === "offgraph") g.setLineDash([2, 5]);
      strokeEdge(g, e);
      g.setLineDash([]);
    });

    for (const n of model.nodes) {
      const p = layout.pos.get(n.id);
      if (!p) continue;
      const on = !cone || cone.nodes.has(n.id);
      drawNode(g, n, p, on ? 1 : 0.14);
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

  /** 선택된 파라미터의 상태 색 — 원뿔 전체가 그 색으로 켜진다.
   *  「덮임」을 골랐는데 원뿔이 파랗게 켜지면 상태와 그림이 서로 다른 말을 한다. */
  function coneTint(model) {
    if (!lastSel) return null;
    return STATE_COLOR[model.byId.get(lastSel)?.state] ?? SKIN.blue;
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
    if (sel !== lastSel) {
      lastSel = sel;
      struct = null;
      waveAt = performance.now();
      wave = sel
        ? wavefrontSchedule(model.nodes, model.edges, layout.ranks,
            [sel, ...(model.byId.get(sel)?.seeds ?? [])], { msPerRank: WAVE_RANK_MS })
        : null;
    }
    const cone = sel ? coneOf(model, sel) : null;
    if (!bg) bg = paintBg();
    if (!struct) struct = paintStruct(model, layout, cone);

    ctx.clearRect(0, 0, width, height);
    ctx.drawImage(bg.c, 0, 0, width, height);

    // 원뿔이 있으면 나머지 구조를 아주 흐리게 깔아 맥락을 남긴다.
    // `struct`에는 원뿔 밖 간선이 없으므로(paintStruct가 건너뛴다) 그 역할은
    // drawContext 하나가 맡는다 — struct를 먼저 흐리게 겹쳐 깔면 원뿔을 자기
    // 자신 위에 한 번 더 합성해 노드 알파만 몰래 밀어 올린다
    if (cone) drawContext(ctx, model, layout, cone);
    ctx.drawImage(struct.c, 0, 0, width, height);

    const now = performance.now();
    paintGlow(model, layout, cone, now);
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

    drawLabels(ctx, model, layout, cone, sel);
  }

  function drawContext(g, model, layout, cone) {
    g.save();
    g.globalAlpha = 0.5;
    layout.edges.forEach((e, i) => {
      if (cone.edges.has(i)) return;
      g.strokeStyle = `rgba(${WIRE}, .055)`;
      g.lineWidth = 1;
      strokeEdge(g, e);
    });
    g.restore();
  }

  function paintGlow(model, layout, cone, now) {
    const g = glow.ctx;
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.clearRect(0, 0, glow.c.width, glow.c.height);
    const dpr = (window.devicePixelRatio || 1) * GLOW_SCALE;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);

    const heat = getHeat?.() ?? null;
    // 프레임마다 간선 수만큼 쌍 배열을 새로 만들지 않는다 — 선택이 바뀔 때만 다시 만든다
    // 키에 **레이아웃 신원**도 넣는다 — 후보를 A→B로 바꾸면 선택은 그대로인데 간선
    // 객체(좌표·곡선)가 전부 새것이다. 선택만 보면 옛 좌표에 입자를 뿌리게 된다
    const key = cone ? lastSel : "__all__";
    if (activeCache.key !== key || activeCache.layout !== layout) {
      const pick = [];
      layout.edges.forEach((e, i) => {
        if (cone ? cone.edges.has(i) : e.kind === "ir") pick.push([e, i]);
      });
      activeCache = { key, layout, list: pick };
    }
    const active = activeCache.list;
    const tint = coneTint(model);
    g.lineCap = "round";

    // 굵은 밑칠 — 이게 흐려져서 발광이 된다
    for (const [e] of active) {
      const w = heat ? 1 + 4 * logScale(heat.get(e.dst)?.rel) : 2;
      g.strokeStyle = edgeColor(e, model, cone ? 0.5 : 0.16, tint);
      g.lineWidth = w * 2.1;
      strokeEdge(g, e);
    }

    const still = reduceMotion();
    // 상한은 **총 입자 수**여야 한다. per를 반올림으로 구하면 간선이 많을 때
    // per=2가 되어 총량이 상한을 넘고(실측: 간선 141개 원뿔에서 282개), 상한이
    // 아니라 장식이 된다. per를 내림으로 잡고 예산으로 한 번 더 막는다
    const per = Math.max(1, Math.floor(MAX_PARTICLES / Math.max(1, active.length)));
    let budget = MAX_PARTICLES;
    for (let k = 0; k < active.length && budget > 0; k += 1) {
      const [e, i] = active[k];
      if (!e.flat.len) continue;
      for (let j = 0; j < per && budget > 0; j += 1) {
        budget -= 1;
        const s = still
          ? (0.5 + j / per) % 1
          : ((now - t0) / 2600 + phaseOf(i) + j / per) % 1;
        const p = pointAtArc(e.flat, s);
        // 반짝임 — 흐름 주기(2600 ms)와 어긋난 주기로 밝기·크기를 같이 흔든다.
        // 위상은 간선·입자마다 결정적으로 달라서 전체가 한꺼번에 깜빡이지 않는다
        // 정지 프레임은 **평균**이어야 한다. 1로 굳히면 크기·밝기가 동시에 최대가 되고
        // lighter 합성이라 교차부가 흰색으로 포화한다 — 움직이는 화면보다 더 밝아진다
        const tw = still
          ? 0.5
          : 0.5 + 0.5 * Math.sin((now / TWINKLE_MS + phaseOf(i * 37 + j)) * Math.PI * 2);
        const p2 = 1.35 + 0.95 * tw;
        g.beginPath();
        g.arc(p.x, p.y, p2, 0, Math.PI * 2);
        g.fillStyle = edgeColor(e, model, 0.5 + 0.5 * tw, tint);
        g.fill();
      }
    }

    // 파급 링 — 랭크에 묶여 있으므로 곧 IR 실행 순서다
    if (wave) {
      const age0 = now - waveAt;
      for (const [id, t] of wave) {
        if (t === null) continue;
        const age = still ? WAVE_MS * 0.8 : age0 - t;
        if (age < 0 || age > WAVE_MS) continue;
        const p = layout.pos.get(id);
        if (!p) continue;
        const u = age / WAVE_MS;
        g.beginPath();
        g.arc(p.x, p.y, p.r + 3 + 26 * u, 0, Math.PI * 2);
        g.strokeStyle = withAlpha(tint ?? SKIN.blue, (1 - u) * 0.8);
        g.lineWidth = 2.2;
        g.stroke();
      }
    }

    for (const nd of model.nodes) {
      if (cone && !cone.nodes.has(nd.id)) continue;
      const p = layout.pos.get(nd.id);
      if (!p) continue;
      const t = wave?.get(nd.id);
      // still이면 hot을 끈다 — 그 경우 waveAt이 바로 이 프레임에서 잡히므로
      // 조건이 파급 노드 **전부**에서 참이 되어 화면 전체가 정점으로 굳는다
      const hot = !still && t !== null && t !== undefined && now - waveAt - t < WAVE_MS * 1.6;
      g.beginPath();
      g.arc(p.x, p.y, p.r * (hot ? 2.4 : 1.5), 0, Math.PI * 2);
      g.fillStyle = withAlpha(nodeColor(nd), hot ? 0.55 : 0.2);
      g.fill();
    }
  }

  function drawLabels(g, model, layout, cone, sel) {
    g.font = FONT;
    // SF는 기본 자간이 넓다 — 11 px 캡슐에서는 살짝 조여야 애플 UI처럼 읽힌다.
    // measureText도 같은 자간을 쓰므로 칩 폭은 저절로 맞는다
    if ("letterSpacing" in g) g.letterSpacing = "-0.01em";
    g.textBaseline = "middle";
    const show = new Set();
    if (sel) show.add(sel);
    if (hover) show.add(hover);
    // 성운(방사형)에서는 상시 라벨을 달지 않는다 — 안쪽 링의 둘레가 라벨 폭을 감당하지
    // 못해 지표 8개가 서로를 덮는다. 얽힘의 규모가 이 배치의 메시지이고, 이름은 hover가 맡는다
    const alwaysLabel = layout.variant !== "radial";
    for (const nd of model.nodes) {
      if (nd.kind === "plant") show.add(nd.id);
      else if (alwaysLabel && (nd.kind === "metric" || nd.kind === "output")) show.add(nd.id);
    }
    for (const id of show) {
      const nd = model.byId.get(id);
      const p = layout.pos.get(id);
      if (!nd || !p) continue;
      const text = nd.label ?? nd.id;
      const w = g.measureText(text).width;
      // 라벨은 노드 오른쪽에 붙이되, 캔버스를 넘칠 것 같으면 왼쪽으로 뒤집는다.
      // 여백만 키워 두면 배치가 조금만 바뀌어도 글자가 다시 잘린다 — 자기교정이 낫다
      // 오른쪽 끝 세 열(출력·기체·지표)은 서로 붙어 있어 라벨이 같은 방향이면 먹힌다.
      // 출력은 왼쪽, 기체는 위, 지표는 오른쪽 — 세 방향으로 흩어 놓는다
      const hw = halfExtent(nd.kind, p.r);
      let side = nd.kind === "metric" ? 1 : nd.kind === "output" ? -1 : 0;
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
      g.fillStyle = cone && !cone.nodes.has(id) ? SKIN.inkFaint : SKIN.ink;
      g.fillText(text, x, y);
    }
  }

  // ── 상호작용 ───────────────────────────────────────────────────────────
  const toXY = (ev) => {
    const r = view.getBoundingClientRect();
    return {
      x: ((ev.clientX - r.left) / r.width) * width,
      y: ((ev.clientY - r.top) / r.height) * height,
    };
  };
  view.addEventListener("pointermove", (ev) => {
    const layout = getLayout?.();
    if (!layout) return;
    const { x, y } = toXY(ev);
    const id = hitTestNodes(layout.pos, x, y, { radius: 11 });
    if (id !== hover) {
      hover = id;
      view.style.cursor = id ? "pointer" : "default";
      onHover?.(id);
      // 동작 축소에서는 타이머가 없어 다음 틱이 오지 않는다 — 커서는 pointer로
      // 바뀌어 "여기 뭔가 있다"고 약속해 놓고 라벨은 영영 안 뜬다. 특히 성운(radial)은
      // 상시 라벨이 없어 hover가 이름을 볼 유일한 수단이다 (select()와 같은 이유)
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
    const { x, y } = toXY(ev);
    onSelect?.(hitTestNodes(layout.pos, x, y, { radius: 11 }));
  });
  view.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") {
      ev.preventDefault();
      onSelect?.(null);
    }
  });

  resize(width, height);
  t0 = performance.now();
  if (!reduceMotion()) timer = setInterval(frame, FRAME_MS);
  frame();

  return {
    root: view,
    redraw() {
      bg = null;
      struct = null;
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
