/** 3D 월드 — 무인기가 실제 축척의 공간을 나는 모습 (원근·하늘·대기안개·톤매핑).

시뮬 탭의 축측투영 궤적 뷰(views/plot3d.js)는 원근도 조명도 없어 "어디를 어떻게 나는가"를
말하지 못한다. 이 화면이 그 자리를 맡는다.

## 무엇을 어디서 가져오는가 — 지어내는 것이 없다

전부 **저장된 결과 하나**에서 온다(§"기준선은 결과와 함께 다닌다"):

    meta.runway    활주로 표고·방위·길이  → 기준면과 중심선
    meta.launch    레일 길이·앙각·방위    → 발사대
    meta.waypoints, meta.accept_radius     → 기둥과 포획원
    meta.geometry  스팬·기준면적·접촉점    → 기체 형상 (lib/uavmesh.js)
    signals        pn·pe·h·phi·theta·psi  → 궤적과 자세 (lib/attitude.js)

지형이 있으면 실제 표고 격자를 깔고, 없으면 활주로 표고의 기준면을 깐다 — **어느 쪽인지
캡션이 말한다.** 그리고 지형은 **원점이 맞을 때만** 얹는다: 지형 격자는 팩의 원점 기준이고
궤적은 결과의 원점 기준이라, 둘이 다르면 같은 (N, E)가 지구상 다른 곳이 된다. 그때 겹쳐
그린 화면은 기체가 저 능선 위를 날았다고 거짓말한다(lib/world3d.js `originsAgree`).

## 시뮬 탭을 건드리지 않는다

views/sim.js·lib/mission.js·lib/replay.js에 병행 작업의 미커밋 변경이 올라가 있어
(views/sim.js:55-58의 app.css 회피와 같은 사정) 결과를 여기서 스스로 고른다.
재생 커서 계산만은 복제하지 않고 lib/playcursor.js를 공유한다 — 두 화면이 서로 다른
시각을 말하면 안 되기 때문이다.
*/

import { api, errorText } from "../api.js";
import { clear, el, fmt } from "../dom.js";
import { bodyAxesNed, eulerToQuat, isNearSingular } from "../lib/attitude.js";
import {
  CAM_MODES, attitudeCamera, chaseCamera, onboardCamera, orbitCamera, rotateBy,
  shouldResetSmoothing,
} from "../lib/camera.js";
import { atEnd, dtSample, indexAt, isPlayable } from "../lib/playcursor.js";
import { strideFor } from "../lib/replay.js";
import { uavMesh } from "../lib/uavmesh.js";
import {
  buildTerrainMesh, elevationAt, parseTerrainPack, tierRect,
} from "../lib/terrainpack.js";
import {
  attitudeAt, niceStep, originsAgree, sampleAt, sceneExtent, trackPoints, velocityAt,
} from "../lib/world3d.js";
import { store } from "../store.js";

const CAM_LABEL = {
  chase: "추적", orbit: "자유 궤도", onboard: "온보드 1인칭", attitude: "자세 관측",
};
const HINT = "font-size:12px; color:var(--muted); line-height:1.6;";
const ROW = "display:flex; gap:10px; align-items:center; flex-wrap:wrap;";

/** 탭을 떠나도 살아남는 상태 — 시점·환경은 재진입 시 그대로여야 한다
 *  (views/sim.js의 wpMapView·view3dRef와 같은 관례). */
const view = {
  mode: "chase",
  orbit: { az: 2.2, el: 0.45 },
  dist: 320,
  sunEl: 0.55, // [rad]
  sunAz: 2.0,
  visibility: 25000, // [m]
  exposure: 0.95,
  speed: 5,
};

/** 살아 있는 렌더러·타이머 — WebGL 컨텍스트는 브라우저당 개수 제한이 있어
 *  탭을 떠날 때 반드시 반납해야 한다. main.js의 route()가 dispose()를 부른다. */
let live = null;

export function dispose() {
  if (live == null) return;
  cancelAnimationFrame(live.raf);
  live.resizeObserver?.disconnect();
  live.renderer?.dispose();
  live = null; // boot()이 await 중이면 세션 토큰이 달라져 스스로 물러난다
}

export function render() {
  dispose(); // 재진입 시 이전 컨텍스트를 먼저 반납
  const root = el("section", { class: "panel" },
    el("h2", {}, "가상환경"),
    el("p", { class: "hint", style: HINT }, "결과를 불러오는 중…"));
  boot(root).catch((e) => {
    clear(root).append(
      el("h2", {}, "가상환경"),
      el("p", { class: "hint", style: HINT }, `불러오지 못했습니다 — ${errorText(e)}`));
  });
  return root;
}

async function boot(root) {
  // **세션 토큰** — render()는 동기로 반환하고 boot()은 결과 조회와 three(2 MB) 첫 로드를
  // await한다. 그 사이에 탭을 떠나면 dispose()는 live가 아직 없어 조용히 반환하고, 이어서
  // boot이 재개해 **분리된 캔버스에 렌더러를 만들고 rAF 루프를 돌린다** — 그 고아 루프는
  // 취소할 손잡이가 없고 렌더러를 잡고 있어 GC도 안 된다. 컨텍스트 8~16개 한계를 지키려고
  // 넣은 훅이 정확히 그 경로로 깨지므로, 매 await 뒤에 내가 아직 살아 있는지 확인한다.
  const session = {};
  live = { session, renderer: null, raf: 0, resizeObserver: null, dirty: true };
  const abandoned = () => live?.session !== session;

  const results = (await api.get("/results")).filter((m) => m.kind === "sim");
  if (abandoned()) return;
  // 지형 팩은 결과와 무관한 자산이라 한 번만 읽는다. 없으면 사유가 담겨 온다.
  const world = await loadTerrain();
  if (abandoned()) return;
  if (results.length === 0) {
    clear(root).append(
      el("h2", {}, "가상환경"),
      el("p", { class: "hint", style: HINT },
        "시뮬레이션 결과가 없습니다 — ",
        el("a", { href: "#sim" }, "시뮬레이션 탭"),
        "에서 한 번 실행하면 여기에 나타납니다."));
    return;
  }
  const wanted = store.get("simResult")?.id;
  let chosen = results.find((m) => m.id === wanted)?.id ?? results[0].id;

  const canvas = el("canvas", {
    style: "width:100%; display:block; border-radius:8px; background:#0d1117; touch-action:none;",
    tabindex: "0",
  });
  canvas.setAttribute("aria-label", "가상환경 — 끌어서 시점 회전, 휠로 거리 조절");

  const { renderer, reason } = await import("./worldrenderer.js")
    .then((m) => m.createRenderer(canvas));
  if (abandoned()) { renderer?.dispose(); return; }
  if (renderer == null) {
    clear(root).append(
      el("h2", {}, "가상환경"),
      el("p", { class: "hint", style: HINT }, reason, " ",
        el("a", { href: "#sim" }, "시뮬레이션 탭"), "의 3D 궤적 뷰는 2D 캔버스라 동작합니다."));
    return;
  }

  const picker = el("select", { "aria-label": "결과 선택" },
    ...results.map((m) => el("option", { value: m.id, selected: m.id === chosen },
      `${m.id.slice(0, 8)} · ${new Date(m.created * 1000).toLocaleString("ko-KR")}`)));
  const caption = el("div", { style: HINT });
  const readout = el("span", { class: "num", style: "min-width:340px; display:inline-block;" });
  const slider = el("input", { type: "range", min: "0", max: "0", value: "0",
    style: "flex:1 1 220px;", "aria-label": "재생 위치" });
  const playBtn = el("button", {}, "▶ 재생");
  const modeBtns = CAM_MODES.map((m) => el("button", {}, CAM_LABEL[m]));

  clear(root).append(
    el("h2", {}, "가상환경"),
    el("div", { class: "row", style: ROW }, picker, ...modeBtns),
    canvas,
    el("div", { class: "row", style: `${ROW} margin-top:8px;` }, playBtn,
      speedSelect(), slider, readout),
    envRow(),
    caption,
  );

  live.renderer = renderer;

  // 캔버스 크기를 컨테이너에 맞춘다. 리포의 2D 캔버스들은 CSS 축소를 감수하지만(흐려질 뿐),
  // WebGL은 그리기 버퍼와 표시 크기가 어긋나면 그림이 늘어난다 — 실제 크기를 따라가야 한다.
  // 리포 첫 ResizeObserver이고, 3D 뷰포트에는 이것이 필요한 이유가 그것이다.
  const sizeToBox = () => {
    const w = Math.max(canvas.clientWidth, 1);
    const h = Math.max(Math.round(w * 0.5), 240);
    canvas.style.height = `${h}px`;
    renderer.resize(w, h, window.devicePixelRatio || 1);
    live.dirty = true;
  };
  const ro = new ResizeObserver(sizeToBox);
  ro.observe(canvas);
  live.resizeObserver = ro;

  const state = {
    body: null, mesh: null, n: 0, dt: 0, idx: 0, prevIdx: null,
    chaseEye: null, lastPos: null, lastAtt: null, missing: 0, missingAtt: 0,
    terrain: null,
    loadGen: 0, terrainUploaded: false, terrainReason: null,
    lastFrameMs: performance.now(), playing: false,
    fromIdx: 0, fromWall: 0, notes: [],
  };

  async function load(id) {
    // boot()의 세션 토큰과 같은 이유의 세대 토큰 — 목록에서 두 번 빠르게 고르면 느린 응답이
    // 나중에 도착해 이긴다. 그러면 state.body는 A인데 선택칸·캡션·판독부는 B를 말한다.
    const gen = ++state.loadGen;
    caption.textContent = "결과를 불러오는 중…";
    const head = await api.get(`/results/${id}`);
    if (gen !== state.loadGen || abandoned()) return;
    const body = await api.get(
      `/sim/${id}/replay?stride=${strideFor(head.n_total ?? head.t.length)}`);
    if (gen !== state.loadGen || abandoned()) return;
    state.body = body;
    state.n = body.t.length;
    state.dt = dtSample(body.t);
    state.idx = 0;
    state.prevIdx = null;
    state.chaseEye = null;
    state.lastPos = null;
    state.lastAtt = null;
    state.missing = 0;
    state.missingAtt = 0;
    buildScene(renderer, body, state, world);
    slider.max = String(Math.max(state.n - 1, 0));
    slider.value = "0";
    playBtn.disabled = !isPlayable(body.t);
    playBtn.textContent = isPlayable(body.t) ? "▶ 재생" : "▶ 재생 (샘플 부족)";
    caption.replaceChildren(...captionNodes(state, renderer, world));
    state.captionStale = true; // 삼각형·드로우콜 수는 한 번 그려 봐야 알 수 있다
    live.dirty = true;
  }

  /* ---- 시점 조작 (views/plot3d.js와 같은 손맛) ---- */
  let drag = null;
  canvas.addEventListener("pointerdown", (ev) => {
    canvas.setPointerCapture(ev.pointerId);
    drag = { x: ev.clientX, y: ev.clientY };
  });
  canvas.addEventListener("pointermove", (ev) => {
    if (drag == null) return;
    view.orbit = rotateBy(view.orbit, ev.clientX - drag.x, ev.clientY - drag.y);
    drag = { x: ev.clientX, y: ev.clientY };
    if (view.mode !== "orbit" && view.mode !== "attitude") setMode("orbit");
    live.dirty = true;
  });
  const endDrag = () => { drag = null; };
  canvas.addEventListener("pointerup", endDrag);
  canvas.addEventListener("pointercancel", endDrag);
  canvas.addEventListener("wheel", (ev) => {
    ev.preventDefault();
    view.dist = Math.min(Math.max(view.dist * (ev.deltaY > 0 ? 1.1 : 1 / 1.1), 8), 20000);
    live.dirty = true;
  }, { passive: false });

  function setMode(m) {
    view.mode = m;
    state.chaseEye = null; // 시점을 바꾸면 지연을 리셋 — 안 하면 카메라가 기어온다
    modeBtns.forEach((b, i) => b.classList.toggle("primary", CAM_MODES[i] === m));
    state.captionStale = true; // 표시 배율이 시점마다 다르다 — 캡션이 옛 배율을 말하면 안 된다
    live.dirty = true;
  }
  modeBtns.forEach((b, i) => b.addEventListener("click", () => setMode(CAM_MODES[i])));
  setMode(view.mode);

  /* ---- 재생 ---- */
  const anchor = () => { state.fromIdx = state.idx; state.fromWall = performance.now(); };
  const stop = () => { state.playing = false; playBtn.textContent = "▶ 재생"; };
  playBtn.addEventListener("click", () => {
    if (state.playing) return stop();
    if (atEnd(state.idx, state.n)) state.idx = 0;
    anchor();
    state.playing = true;
    playBtn.textContent = "⏸ 일시정지";
  });
  slider.addEventListener("input", () => {
    stop();
    state.idx = Number(slider.value);
    live.dirty = true;
  });
  picker.addEventListener("change", () => {
    stop();
    chosen = picker.value;
    load(chosen).catch((e) => {
      caption.replaceChildren(el("div", {}, `결과를 불러오지 못했습니다 — ${errorText(e)}`));
    });
  });

  function speedSelect() {
    const sel = el("select", { "aria-label": "재생 배속" },
      ...[1, 2, 5, 10, 20].map((x) =>
        el("option", { value: String(x), selected: x === view.speed }, `${x}×`)));
    // 배속을 바꾸면 기준점을 다시 잡는다 — 안 하면 지난 경과분까지 새 배속으로 곱해져 튄다
    sel.addEventListener("change", () => {
      view.speed = Number(sel.value);
      if (state.playing) anchor();
    });
    return sel;
  }

  function envRow() {
    const sun = rangeField("태양 고도", 2, 88, view.sunEl * 180 / Math.PI, (v) => {
      view.sunEl = (v * Math.PI) / 180;
    }, (v) => `${Math.round(v)}°`);
    const vis = rangeField("시정", 2, 60, view.visibility / 1000, (v) => {
      view.visibility = v * 1000;
    }, (v) => `${v} km`);
    const exp = rangeField("노출", 40, 200, view.exposure * 100, (v) => {
      view.exposure = v / 100;
    }, (v) => (v / 100).toFixed(2));
    return el("div", { class: "row", style: `${ROW} margin-top:6px;` }, sun, vis, exp);
  }

  function rangeField(label, min, max, value, onInput, fmtVal) {
    const out = el("span", { class: "num", style: "min-width:52px;" }, fmtVal(value));
    const input = el("input", { type: "range", min: String(min), max: String(max),
      value: String(Math.round(value)), style: "width:110px;", "aria-label": label });
    input.addEventListener("input", () => {
      const v = Number(input.value);
      onInput(v);
      out.textContent = fmtVal(v);
      live.dirty = true;
    });
    return el("label", { style: "display:flex; gap:6px; align-items:center; font-size:12px;" },
      label, input, out);
  }

  /* ---- 프레임 루프 — 커서·시점이 움직였을 때만 그린다 ---- */
  function frame() {
    if (abandoned()) return; // 다시 걸지 않는 것이 곧 루프의 끝이다
    live.raf = requestAnimationFrame(frame);
    const now = performance.now();
    const dtWall = Math.min((now - state.lastFrameMs) / 1000, 0.25);
    state.lastFrameMs = now;
    if (state.body == null) return;

    if (state.playing) {
      const next = indexAt(state.fromIdx, state.fromWall, now, view.speed, state.dt, state.n);
      if (next !== state.idx) { state.idx = next; slider.value = String(next); }
      if (atEnd(next, state.n)) stop();
      live.dirty = true;
    }
    if (!live.dirty) return;
    live.dirty = false;
    drawFrame(renderer, state, dtWall, readout);
    if (state.captionStale) {
      state.captionStale = false;
      caption.replaceChildren(...captionNodes(state, renderer, world));
    }
  }
  sizeToBox();
  await load(chosen);
  if (abandoned()) return;
  live.raf = requestAnimationFrame(frame);
}

/** 지형 팩을 한 번 읽어 메시까지 만든다 — 실패는 **사유 문장**으로 돌려준다.
 *
 * 바깥 티어는 안쪽 티어가 덮는 사각형을 건너뛴다(`skipRect`). 겹쳐 두면 같은 자리에 면이
 * 둘이라 z-fighting으로 깜빡이는데, 빌드 시점에 잘라 내면 폴리곤오프셋 튜닝이 필요 없다.
 */
async function loadTerrain() {
  try {
    const manifest = await api.get("/world/manifest");
    if (!manifest.terrain?.length) {
      return { reason: manifest.reason ?? "지형 자산이 없습니다." };
    }
    const asset = manifest.terrain[0];
    // 바이너리라 api.get(JSON 전용)을 쓰지 않는다.
    //
    // `cache: "no-cache"`는 **매번 재검증**하되 서버가 304를 주면 캐시 본문을 쓴다
    // (no-store와 다르다 — 그건 캐시를 아예 안 쓴다). 서버가 이미 no-cache를 주지만
    // 여기서도 거는 이유는, 한 번이라도 긴 max-age로 받아 둔 항목이 있으면 그 항목이
    // 만료될 때까지 서버 헤더가 손을 못 대기 때문이다. 실제로 그 상태를 겪었다 —
    // 팩을 다시 구웠는데 화면이 옛 통계를 계속 말했다.
    const res = await fetch(`/api/world/terrain/${encodeURIComponent(asset.name)}`,
      { cache: "no-cache" });
    if (!res.ok) return { reason: `지형 팩을 받지 못했습니다 (HTTP ${res.status}).` };
    const pack = parseTerrainPack(await res.arrayBuffer());
    const core = pack.tiers[0];
    const patches = pack.tiers.map((t, i) =>
      buildTerrainMesh(t, { skipRect: i === 0 ? null : tierRect(core) }));
    return { pack, patches, asset };
  } catch (e) {
    return { reason: `지형을 불러오지 못했습니다 — ${errorText(e)}` };
  }
}

/* ---------------- 장면 조립 ---------------- */

function buildScene(renderer, body, state, world) {
  const meta = body.meta ?? {};
  const s = body.signals;
  const elevation = meta.runway?.elevation ?? 0;
  const extent = sceneExtent(s);

  // **원점이 맞을 때만** 지형을 얹는다. 팩 격자는 팩의 원점 기준, 궤적은 결과의 원점
  // 기준이라 둘이 다르면 같은 (N, E)가 다른 곳이다 — 겹쳐 그리면 화면이 거짓말한다.
  const agree = world.pack
    ? originsAgree(world.pack.origin, meta.origin)
    : { ok: false, reason: world.reason };
  state.terrain = agree.ok ? world.pack : null;
  state.terrainReason = agree.reason;
  if (agree.ok && !state.terrainUploaded) {
    // 지형은 결과와 무관한 정적 자산이다. 결과를 바꿀 때마다 다시 올리면 정점 100만 개
    // 분량(위치·법선·색 + 인덱스)을 매번 GPU에 다시 밀어 넣게 된다.
    renderer.setTerrain(world.patches);
    state.terrainUploaded = true;
  } else if (!agree.ok && state.terrainUploaded) {
    renderer.setTerrain([]); // 원점이 안 맞는 결과로 바꾸면 걷어낸다
    state.terrainUploaded = false;
  }
  const showTerrain = agree.ok;
  renderer.setGround({
    elevation,
    grid: { extent, step: niceStep(extent) },
    runway: meta.runway ?? null,
    rail: meta.launch ? { ...meta.launch, elevation } : null,
    showPlane: !showTerrain,
    showGrid: !showTerrain,
  });

  // 궤적 — 결측에서 선을 끊는다(lib/world3d.js가 정책의 정본). 이어 그리면 없는 구간이
  // 직선으로 위장되고, 그 자리를 0으로 채우면 원점에서 뻗는 가짜 선분이 된다.
  const { points, breaks } = trackPoints(s, state.n);
  renderer.setPaths([{ points, color: 0x32d3ff, breaks }]);
  state.missing = breaks.length;
  state.missingAtt = 0;
  for (let i = 0; i < state.n; i++) if (attitudeAt(s, i) === null) state.missingAtt++;

  const marks = [];
  const radius = meta.accept_radius ?? 0;
  for (const w of meta.waypoints ?? []) {
    marks.push({ ne: [w[0], w[1], w.length > 2 ? -w[2] : -elevation], kind: "waypoint", radius });
  }
  // 출발점은 **성한 첫 표본**에만 찍는다 — 결측이면 원점에 초록 점을 지어내게 된다
  const start = firstSample(s, state.n);
  if (start !== null) marks.push({ ne: start, kind: "start" });
  renderer.setMarkers(marks);

  // 기체는 치수가 있을 때만 — 없으면 그리지 않고 캡션이 그 사실을 말한다
  state.mesh = null;
  state.notes = [];
  try {
    if (meta.geometry) {
      state.mesh = uavMesh(meta.geometry);
      renderer.setModelMesh(state.mesh);
    } else {
      renderer.setModelMesh(null);
      state.notes.push("이 결과에는 기체 기준량(meta.geometry)이 없어 기체를 그리지 않습니다 "
        + "— 형상이 추가되기 전에 저장된 결과입니다.");
    }
  } catch (e) {
    renderer.setModelMesh(null);
    state.notes.push(`기체 형상을 만들지 못했습니다 — ${e.message}`);
  }
}

function drawFrame(renderer, state, dtWall, readout) {
  const s = state.body.signals;
  const i = Math.min(state.idx, state.n - 1);
  const sample = sampleAt(s, i);
  // 결측 프레임에서는 **기체를 그리지 않는다.** 0으로 메우면 기체가 NED 원점·해면으로
  // 순간이동하고, 그 도약을 후방차분한 속도가 체이스 카메라의 진행 방향까지 정한다.
  // 카메라는 마지막으로 성했던 자리에 머문다 — 화면이 멈추는 것이 지어내는 것보다 옳다.
  const pos = sample ?? state.lastPos;
  if (sample) state.lastPos = sample;
  // 자세도 위치와 같은 규약이다. 다만 **기체를 안 그리는 것으로는 부족했다** — 쿼터니언이
  // 카메라로 그대로 흘러가 온보드 시점이 없는 수평·정북을 보고 있었다(리뷰 지적).
  // 위치와 같이 마지막으로 성했던 자세에 머물고, 그마저 없으면 q를 아예 만들지 않는다.
  const att = attitudeAt(s, i);
  if (att) state.lastAtt = att;
  const attUse = att ?? state.lastAtt;
  const q = attUse ? eulerToQuat(...attUse) : null;
  const axes = q ? bodyAxesNed(q) : null;
  // 기체 발밑의 지면 표고 — 판독부의 대지고도와 카메라 클램프가 **같은 값**을 써야 한다.
  const groundElev = groundElevationAt(state, pos);

  renderer.setEnvironment({
    sunAzEl: [view.sunAz, view.sunEl],
    visibility: view.visibility,
    exposure: view.exposure,
  });
  if (state.mesh && sample && att && q) {
    // 기체 실물은 스팬 2.5 m라 300 m 상공에서 한 점이다 — 보이도록 키운다.
    // 배율을 캡션이 밝힌다(형상을 실물 크기로 착각하지 않게).
    renderer.setModelPose({ pos: sample, axes, scale: modelScale(view) });
  } else if (state.mesh) {
    renderer.setModelPose(null);
  }
  if (shouldResetSmoothing(state.prevIdx, i)) state.chaseEye = null;
  state.prevIdx = i;

  const cam = cameraFor(state, pos, q, axes, dtWall, i, groundElev);
  if (view.mode === "chase" && pos) state.chaseEye = cam.eye;
  renderer.render(cam);

  // 대지고도는 **실제 지면**에서 잰다. 지형이 있는데 활주로 표고를 빼면 400 m 능선 위
  // 450 m에서 "지면 +450"이 나온다 — 이름은 대지고도인데 값은 활주로 상대고도다.
  // 지형 격자 밖이면 "—"를 낸다(다른 양을 같은 이름으로 내놓지 않는다).
  const agl = Number.isFinite(s.h?.[i]) && groundElev !== null ? s.h[i] - groundElev : null;
  readout.textContent =
    `t ${dec(state.body.t[i], 1)} s · ${s.mode?.[i] ?? "—"} · `
    + `h ${dec(s.h[i], 1)} m (지면 ${agl == null ? "—" : `+${dec(agl, 1)}`}) · `
    + `V ${dec(s.V?.[i], 1)} m/s · φ ${degOf(s.phi?.[i])} θ ${degOf(s.theta?.[i])}`;
}

function cameraFor(state, pos, q, axes, dtWall, idx, groundElev) {
  // 지면 D — 카메라가 이 아래로 내려가면 지면이 화면을 덮는다. 온보드는 예외다
  // (기체가 실제로 지면에 서 있는 구간이 있고, 그때 시점은 기체를 따라야 한다).
  const groundD = -(groundElev ?? state.body.meta?.runway?.elevation ?? 0);
  // 성한 표본을 한 번도 못 봤다 — 기준면 원점을 멀찍이 내려다본다(지어낼 위치가 없다)
  if (pos == null) {
    return orbitCamera({ pivot: [0, 0, groundD], ...view.orbit, dist: view.dist, groundD });
  }
  const vel = velocityAt(state.body.t, state.body.signals, idx);
  // 자세를 한 번도 못 본 결과에서는 **자세에 기대는 시점을 쓸 수 없다.** 단위 쿼터니언으로
  // 물러서면 온보드 시점이 있지도 않은 수평·정북을 보여 준다 — 기체를 안 그려도 온보드는
  // 원래 기체 안이라 알아챌 단서가 없다. 궤도 시점으로 물러서고 캡션이 사유를 말한다.
  const mode = q == null && (view.mode === "onboard" || view.mode === "attitude")
    ? "orbit" : view.mode;
  switch (mode) {
    case "orbit":
      return orbitCamera({ pivot: pos, ...view.orbit, dist: view.dist, groundD });
    case "onboard":
      return onboardCamera({ pos, q });
    case "attitude":
      return attitudeCamera({ pos, ...view.orbit, dist: Math.min(view.dist, 40), groundD });
    default:
      return chaseCamera({
        pos, vel, q, prevEye: state.chaseEye, dtWall, groundD,
        dist: Math.min(view.dist, 400), height: Math.min(view.dist, 400) * 0.28,
      });
  }
}

/** 기체 발밑의 지면 표고 [m] — 지형이 있으면 격자에서, 없으면 활주로 표고에서.
 *
 * 지형 격자 밖이면 **null**이다: 활주로 표고로 물러서면 "대지고도"라는 이름으로 다른 양을
 * 내놓게 된다. 카메라 클램프는 그때 기준면으로 물러서지만(화면이 덮이는 것보다 낫다)
 * 판독부는 "—"를 낸다.
 */
function groundElevationAt(state, pos) {
  if (state.terrain && pos) {
    for (const tier of state.terrain.tiers) {
      const z = elevationAt(tier, pos[0], pos[1]);
      if (z !== null) return z;
    }
    return null; // 지형은 있는데 이 자리를 안 덮는다
  }
  // 지형이 없으면 화면이 깐 기준면과 **같은 값**을 낸다. 여기만 null을 내면 판은 0 m에
  // 깔려 있는데 판독부는 대지고도를 "—"라고 답해, 화면이 자기 말과 어긋난다.
  return state.body.meta?.runway?.elevation ?? 0;
}

/** 성한 첫 표본의 NED 위치 — 하나도 없으면 null. */
function firstSample(signals, n) {
  for (let i = 0; i < n; i++) {
    const p = sampleAt(signals, i);
    if (p !== null) return p;
  }
  return null;
}

function captionNodes(state, renderer, world) {
  const meta = state.body.meta ?? {};
  const d = renderer.describe();
  const st = renderer.stats();
  const lines = [];

  if (state.terrain) {
    const t = state.terrain.tiers;
    const core = t[0];
    lines.push(`지형: ${t.map((x) => `${x.name} ${x.step} m 격자`).join(" · ")} — `
      + `원자료 ${fmt(core.source_res_m, 3)} m/px, 커버리지 ${(core.coverage * 100).toFixed(1)}%.`);
    lines.push(core.source);
    const seaFrac = core.sea_level_frac ?? core.sea_clamped_frac;
    if (seaFrac > 0) {
      lines.push("해수면 아래 값은 0 m로 평탄화했습니다 — 원자료의 그 부분은 수심입니다. "
        + `표본의 ${(seaFrac * 100).toFixed(1)}%가 해수면 높이(0 m)에 놓여 있습니다 — `
        + "바다만이 아니라 간척지·저지대도 함께 들어가며, 이 자료만으로는 둘을 "
        + "가릴 수 없습니다.");
    }
    lines.push("색은 고도 램프이고 음영은 실제 법선에 조명이 닿아 생긴 것입니다 — "
      + "영상지도가 아닙니다.");
  } else {
    const elev = meta.runway?.elevation;
    lines.push((elev == null
      ? "지형을 얹지 않았습니다 — 바닥은 해면(0 m) 기준면이며 실제 지형이 아닙니다."
      : `지형을 얹지 않았습니다 — 바닥은 표고 ${fmt(elev, 1)} m 기준면(활주로 표고)이며 `
        + "실제 지형이 아닙니다.")
      + (state.terrainReason ? ` ${state.terrainReason}` : ""));
  }
  if (meta.runway) {
    lines.push("활주로는 중심선과 양 끝만 그립니다 — 폭은 결과에 없습니다.");
  }
  if (meta.geometry) {
    lines.push(`기체 형상은 엔진 기준량(스팬 ${fmt(meta.geometry.b, 2)} m, `
      + `면적 ${fmt(meta.geometry.s_ref, 2)} m²)에서 만든 도식이며 실제 외형이 아닙니다. `
      + `보이도록 ${modelScale(view)}배로 키워 그립니다.`);
  }
  lines.push("대기안개·하늘·톤매핑은 표시 효과입니다 — 가시거리·기상 모델이 아닙니다.");
  if (state.missingAtt === state.n) {
    lines.push("이 결과에는 자세 신호(φ·θ·ψ)가 없습니다 — 기체를 그리지 않고, "
      + "온보드·자세 관측 시점은 궤도 시점으로 물러섭니다.");
  } else if (state.missingAtt > 0) {
    lines.push(`자세 표본 ${state.n}개 중 ${state.missingAtt}개가 결측입니다 — 그 구간은 `
      + "마지막으로 성했던 자세에 머뭅니다.");
  }
  if (state.missing > 0) {
    lines.push(`궤적 표본 ${state.n}개 중 ${state.missing}개가 결측입니다 — 그 구간은 선을 `
      + "끊고 기체를 그리지 않습니다(카메라는 마지막으로 성했던 자리에 머뭅니다).");
  }
  if (meta.origin) {
    // 유효숫자 표기(fmt)면 34.601303이 "34.601"이 되어 옛 자리표시 34.60과 구별되지
    // 않는다. 위도 34.6에서 1e-6°는 0.11 m라, 6자리가 측정 분해능과 맞는 자릿수다.
    lines.push(`원점 ${dec(meta.origin.lat, 6)}°N ${dec(meta.origin.lon, 6)}°E `
      + `(곡률반경 기준고도 ${fmt(meta.origin.h_ref, 1)} m — ${meta.origin.h_ref_src})`);
  } else {
    lines.push("측지 원점이 지정되지 않은 결과입니다 — 지도 위 위치를 말할 수 없습니다.");
  }
  const s = state.body.signals;
  if (s.theta?.some?.((v) => v != null && isNearSingular(v))) {
    lines.push("피치가 ±85°를 넘는 구간이 있습니다 — 그 구간의 φ·ψ 표시값은 불정입니다"
      + "(회전 자체는 옳으므로 그림은 정확합니다).");
  }
  lines.push(...state.notes);
  lines.push(`${d.name} · ${d.api} · 삼각형 ${st.triangles.toLocaleString("ko-KR")} · `
    + `드로우콜 ${st.drawCalls}`);
  return lines.map((t) => el("div", {}, t));
}

/* ---------------- 소소한 수치 ---------------- */

/** 기체 표시 배율 — 스팬 2.5 m는 300 m 상공에서 한 점이라 그대로 그리면 안 보인다.
 *  온보드 시점에서는 배율을 1로 둔다(자기 기체 안이라 커지면 시야를 가린다). */
function modelScale(v) {
  return v.mode === "onboard" ? 1 : v.mode === "attitude" ? 4 : 12;
}

/** 소수 자릿수 표기 — dom.js의 fmt는 **유효숫자**라 200 m가 "2e+2"가 된다.
 *  판독부는 자릿수가 흔들리면 눈으로 좇기 어려우므로 고정 소수를 쓴다. */
function dec(x, digits) {
  return x == null || !Number.isFinite(x) ? "—" : x.toFixed(digits);
}

function degOf(rad) {
  return rad == null ? "—" : `${((rad * 180) / Math.PI).toFixed(1)}°`;
}
