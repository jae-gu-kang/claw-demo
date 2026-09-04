import { useCallback, useEffect, useRef, useState } from "react";

import type { SimResultRow } from "../data/api.ts";
import type { FrameStats } from "../scene/SceneController.ts";
import type { ViewStyle } from "../scene/SceneHost.ts";
import {
  CAM_MODES, SceneController, createController, type CamMode, type Readout,
} from "../scene/SceneController.ts";
import type { MountDeps } from "../main.tsx";
import { canvasHeight } from "./layout.ts";

const HINT: React.CSSProperties = { fontSize: 12, color: "var(--muted)", lineHeight: 1.6 };

const CAM_LABEL: Record<CamMode, string> = {
  chase: "추적", orbit: "자유 궤도", onboard: "온보드 1인칭", attitude: "자세 관측",
};

const STYLE_LABEL = { engineering: "엔지니어링", cinematic: "시네마틱", game: "게임" } as const;

/** 서랍 하나 — 이름은 칩에, 내용은 열렸을 때만. 배치 뼈대는 app.css의 `.tab-*`가 준다
 *  (영향성 탭과 같은 것을 쓴다 — 같은 레이아웃을 두 벌 두지 않는다). */
type DrawerKey = "env" | "perf" | "notes";

// 캔버스 높이 규칙은 `./layout.ts` — 이 파일은 JSX라 node --test가 못 읽어서,
// 판정이 되는 값은 순수 모듈로 빼고 거기서 테스트한다.

const fmt = (v: number | null, digits = 1, unit = ""): string =>
  v === null ? "—" : `${v.toFixed(digits)}${unit}`;
/** 라디안 → 도. **음의 0을 만들지 않는다** — `(-1e-6).toFixed(0)`은 "-0"이고,
 *  화면에 "φ -0°"가 뜨면 읽는 사람이 부호를 뜻으로 읽는다(실측으로 나왔다). */
const deg = (rad: number | null): string => {
  if (rad === null) return "—";
  const d = Math.round((rad * 180) / Math.PI);
  return `${d === 0 ? 0 : d}°`;
};
/** 부호를 값에서 만든다 — `+`를 박아 두면 지면 아래일 때 "+-12"가 나온다.
 *
 *  **먼저 반올림하고 나서 부호를 붙인다.** `toFixed(0)`부터 하면 −0.4가 "-0"이 되어
 *  화면에 "지면 -0"이 뜨고, 물리적으로 같은 값이 "+0"과 "-0" 둘로 갈린다.
 *  접지·활주 구간에서 `aboveGround`가 (−0.5, 0)에 상시 머무는 자리다(`deg()`와 같은 사유). */
const fmtSigned = (v: number | null): string => {
  if (v === null) return "—";
  const r = Math.round(v);
  return `${r < 0 ? "" : "+"}${r === 0 ? 0 : r}`;
};

export function WorldTab({ deps }: { deps: MountDeps }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const ctlRef = useRef<SceneController | null>(null);
  const dragRef = useRef<{ x: number; y: number; sx: number; sy: number } | null>(null);

  const [status, setStatus] = useState("초기화 중…");
  const [notes, setNotes] = useState<string[]>([]);
  const [readout, setReadout] = useState<Readout | null>(null);
  const [results, setResults] = useState<SimResultRow[]>([]);
  const [chosen, setChosen] = useState<string | null>(null);
  const [mode, setMode] = useState<CamMode>("orbit");
  const [playing, setPlaying] = useState(false);
  const [playable, setPlayable] = useState(false);
  const [shownId, setShownId] = useState<string | null>(null);
  const [stats, setStats] = useState<FrameStats | null>(null);
  const [speed, setSpeed] = useState(5);
  const [cursor, setCursor] = useState(0);
  const [count, setCount] = useState(0);
  // 기본값이 곧 첫인상이다: 태양은 서남서(바다 쪽 — 궤도 시점에서 윤슬이 보인다),
  // 시정 45 km(25 km는 첫 화면이 우유에 잠겼다).
  const [sunEl, setSunEl] = useState(0.72);
  const [sunAz, setSunAz] = useState(3.6);
  const [visibility, setVisibility] = useState(60000);
  const [exposure, setExposure] = useState(0.95);
  // 해상 상태 — **표시 값**이다. 7 m/s는 남해안의 흔한 바람이고 유의파고 1.0 m가 나온다.
  const [windSpeed, setWindSpeed] = useState(7);
  const [windDir, setWindDir] = useState(0.6);
  const [cloudCover, setCloudCover] = useState(0.35);
  const [style, setStyle] = useState<ViewStyle>("engineering");
  const [gameWps, setGameWps] = useState<ReadonlyArray<readonly [number, number, number]>>([]);
  // 마지막 "보내기"의 개수 — 확인 문장을 그린다. 모드를 떠나면 지운다(아래 효과).
  const [sent, setSent] = useState<number | null>(null);
  // 열린 서랍 하나 (null = 전부 닫힘). 첫 화면은 세계만 보인다 — 그것이 이 배치의 요지다.
  const [drawer, setDrawer] = useState<DrawerKey | null>(null);

  // **생성과 파괴가 대칭인 한 쌍**이다 — 그래야 StrictMode의 이중 실행에서도 컨텍스트가
  // 하나로 유지된다. 의존성이 비어 있는 것은 실수가 아니라 이 규율이다.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (canvas == null) return;
    const abort = new AbortController();

    // 높이는 **컨트롤러보다 먼저** 정한다. 아래 실패 경로(WebGL 컨텍스트를 못 얻는
    // 자리)에서도 자리를 지켜야 하기 때문이다 — 안 그러면 캔버스가 고유비 300×150으로
    // 눌려 납작한 띠가 되고, 사유가 상태줄에 있는데도 "화면이 깨졌다"로 읽힌다.
    const setH = () => {
      const w = canvas.clientWidth;
      if (w > 0) canvas.style.height = `${canvasHeight(w, window.innerHeight)}px`;
    };
    setH();

    const made = createController(canvas, {
      onNotes: setNotes,
      onMode: setMode,
      onReadout: setReadout,
      onResults: (rows, first) => { setResults(rows); setChosen((c) => c ?? first); },
      onStatus: setStatus,
      onPlaying: setPlaying,
      onStats: setStats,
      onGameWps: setGameWps,
    });
    if (made.controller == null) {
      setStatus(made.reason);
      window.addEventListener("resize", setH);
      return () => window.removeEventListener("resize", setH);
    }
    const ctl = made.controller;
    ctlRef.current = ctl;
    ctl.start();

    const fit = () => {
      const w = canvas.clientWidth;
      if (w <= 0) return; // 탭을 떠나는 중 — 0으로 리사이즈하면 카메라 aspect가 NaN이 된다
      setH();
      // **백킹스토어는 여기서 안 건드린다.** `renderer.setSize(w, h, false)`와
      // `setPixelRatio`가 그 일을 하고, 여기서 또 쓰면 DPR 클램프가 두 파일에 갈린다.
      ctl.resize(w, canvasHeight(w, window.innerHeight), devicePixelRatio);
    };
    const ro = new ResizeObserver(fit);
    ro.observe(canvas);
    // 높이가 뷰포트에도 걸리므로 **창 높이 변화도 받아야** 한다 — ResizeObserver는
    // 캔버스 폭만 보므로 창을 세로로만 줄이면 캔버스가 화면 밖으로 남는다
    window.addEventListener("resize", fit);

    void (async () => {
      setStatus("자산을 불러오는 중…");
      await ctl.loadWorld(abort.signal);
      if (abort.signal.aborted) return;
      try {
        await ctl.loadResults(deps.resultId);
        setStatus("");
      } catch (e) {
        setStatus(`결과 목록을 불러오지 못했습니다 — ${(e as Error).message}`);
      }
    })();

    return () => {
      abort.abort();
      ro.disconnect();
      window.removeEventListener("resize", fit);
      ctlRef.current = null;
      ctl.dispose();
    };
  }, []);

  // 결과 선택 → 장면 재구성
  useEffect(() => {
    const ctl = ctlRef.current;
    if (ctl == null || chosen == null) return;
    let live = true;
    void (async () => {
      // **실패하면 아무것도 갱신하지 않는다** — 갱신하면 슬라이더는 옛 결과의 것인데
      // 선택칸은 새 결과를 말하는 상태가 된다(상태줄만 사유를 낸다).
      let ok = false;
      try {
        ok = await ctl.loadResult(chosen);
      } catch (e) {
        // 떠났거나 밀려난 로드가 지금 상태줄을 덮어쓰지 않게 한다.
        if (live) setStatus(`장면을 세우지 못했습니다 — ${(e as Error).message}`);
      }
      if (!live) return;
      // 실패해도 **무엇이 화면에 있는지**는 갱신한다 — 그래야 선택칸과 화면이 갈린
      // 사실을 아래에서 말할 수 있다.
      setShownId(ctl.shownResultId);
      if (!ok) return;
      setCount(ctl.sampleCount);
      setPlayable(ctl.playable);
      setCursor(0);
      setPlaying(false);
    })();
    deps.store?.set("simResult", { id: chosen });
    return () => { live = false; };
  }, [chosen, deps.store]);

  useEffect(() => {
    ctlRef.current?.setEnvironment({
      sunEl, sunAz, visibility, exposure, windSpeed, windDir, cloudCover,
    });
  }, [sunEl, sunAz, visibility, exposure, windSpeed, windDir, cloudCover]);

  // 재생 중에는 커서를 화면이 따라가야 한다 — 컨트롤러가 정본이라 읽어 온다.
  useEffect(() => {
    if (!playing) return;
    let raf = 0;
    const poll = () => { raf = requestAnimationFrame(poll); setCursor(ctlRef.current?.cursor ?? 0); };
    raf = requestAnimationFrame(poll);
    return () => cancelAnimationFrame(raf);
  }, [playing]);

  // 버튼도 컨트롤러에 맡긴다 — `onMode`가 돌아와 상태를 맞춘다(정본이 하나가 된다).
  const pickMode = useCallback((m: CamMode) => { ctlRef.current?.setCamMode(m); }, []);

  const onPointerDown = (e: React.PointerEvent<HTMLCanvasElement>) => {
    // 우클릭·중클릭은 컨텍스트 메뉴·자동 스크롤의 몫 — 클릭(웨이포인트)·드래그(회전)
    // 판별에서 뺀다. 2D 지도 편집기와 같은 관례다(views/wpmap.js "우클릭은 contextmenu 경로").
    if (e.button !== 0) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    dragRef.current = { x: e.clientX, y: e.clientY, sx: e.clientX, sy: e.clientY };
  };
  const onPointerMove = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const d = dragRef.current;
    if (d == null) return;
    // **시점을 여기서 짐작하지 않는다.** 끌어서 궤도로 넘어가는 조건은 컨트롤러가 쥐고
    // 있고(자세 관측에서는 안 넘어간다), 넘어가면 `onMode`로 알려 준다. 여기서
    // `setMode("orbit")`을 하면 카메라는 자세 관측인데 버튼만 자유 궤도가 된다.
    // (게임 모드에서는 rotate가 무시된다 — 클릭 판별만 여기 남는다.)
    ctlRef.current?.rotate(e.clientX - d.x, e.clientY - d.y);
    dragRef.current = { ...d, x: e.clientX, y: e.clientY };
  };
  const onPointerUp = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const d = dragRef.current;
    dragRef.current = null;
    if (d == null || style !== "game") return;
    // 이동량이 작으면 클릭 — 임계 5 px은 2D 지도(lib/wpmap.js DRAG_PX)와 같은 감각.
    if (Math.hypot(e.clientX - d.sx, e.clientY - d.sy) > 5) return;
    const rect = e.currentTarget.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return;
    ctlRef.current?.addGameWaypointAt(
      ((e.clientX - rect.left) / rect.width) * 2 - 1,
      -(((e.clientY - rect.top) / rect.height) * 2 - 1),
    );
  };
  const endDrag = () => { dragRef.current = null; };

  // 휠은 **비수동 리스너**여야 preventDefault가 먹는다 — React의 onWheel은 수동이다.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (canvas == null) return;
    const onWheel = (e: WheelEvent) => { e.preventDefault(); ctlRef.current?.zoom(e.deltaY); };
    canvas.addEventListener("wheel", onWheel, { passive: false });
    return () => canvas.removeEventListener("wheel", onWheel);
  }, []);

  // 게임 조작 — 창 전역 키보드. 눌린 키 집합에서 축을 만든다(키 반복 이벤트 무관).
  // 입력 칸에 포커스가 있으면 건드리지 않는다 — 환경 슬라이더·결과 선택이 계속 살아야 한다.
  useEffect(() => {
    if (style !== "game") return;
    const keys = new Set<string>();
    const apply = () => {
      ctlRef.current?.setGameInput({
        turn: (keys.has("ArrowRight") ? 1 : 0) - (keys.has("ArrowLeft") ? 1 : 0),
        pitch: (keys.has("ArrowUp") ? 1 : 0) - (keys.has("ArrowDown") ? 1 : 0),
        throttle: (keys.has("Shift") ? 1 : 0) - (keys.has("Control") ? 1 : 0),
      });
    };
    const formy = (t: EventTarget | null): boolean =>
      t instanceof HTMLElement && /^(INPUT|SELECT|TEXTAREA)$/.test(t.tagName);
    const AXES = ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Shift", "Control"];
    const down = (e: KeyboardEvent) => {
      if (formy(e.target)) return;
      // Cmd/Alt 조합은 브라우저·OS 단축키다(Cmd+← 히스토리 등) — 게임 입력으로 삼키면
      // 단축키가 죽고, macOS는 Cmd가 눌린 동안 비수정자 keyup을 안 주므로 축이 눌린 채
      // 고착된다(리뷰 확정). Control은 이 게임의 감속 축이라 여기서 거르지 않는다.
      if (e.metaKey || e.altKey) return;
      if (e.key === " ") {
        e.preventDefault(); // 스페이스가 마지막 버튼을 다시 누르는 것도 막는다
        if (!e.repeat) ctlRef.current?.dropGameWaypoint();
        return;
      }
      if (AXES.includes(e.key)) {
        e.preventDefault(); // 화살표의 페이지 스크롤 방지
        keys.add(e.key);
        apply();
      }
    };
    const up = (e: KeyboardEvent) => { if (keys.delete(e.key)) apply(); };
    // 탭 전환 중 keyup이 유실되면 축이 눌린 채 남는다 — 창을 떠나면 전부 놓는다.
    const drop = () => { keys.clear(); apply(); };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    window.addEventListener("blur", drop);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
      window.removeEventListener("blur", drop);
      ctlRef.current?.setGameInput({ turn: 0, pitch: 0, throttle: 0 });
    };
  }, [style]);

  // "보냈습니다" 확인 문장은 게임 모드를 떠나면 치운다 — 남으면 다음 진입에서
  // 보내지 않은 것을 보냈다고 말한다.
  useEffect(() => { if (style !== "game") setSent(null); }, [style]);

  const sendToSim = useCallback(() => {
    // store 없는 마운트(개발 하니스)에서 set이 no-op인데 확인 문장을 그리면
    // **거짓 성공**이 된다 — 보낼 곳이 없으면 보냈다고 말하지 않는다.
    if (deps.store == null) return;
    const wps = ctlRef.current?.getGameWaypoints() ?? [];
    if (wps.length === 0) return;
    // 시뮬 탭 웨이포인트 표의 행 형식(문자열 n·e·d, d = 고도[m])을 그대로 만든다 —
    // 형식의 정본은 views/sim.js wpRows + lib/mission.js buildWaypoints. 소비는
    // 시뮬 탭 render()가 store "wpDraft"를 읽어서 한다(한 번 읽고 지운다).
    deps.store.set("wpDraft", {
      source: "world-game",
      rows: wps.map(([n, e, h]) => ({ n: String(n), e: String(e), d: String(h) })),
    });
    setSent(wps.length);
  }, [deps.store]);

  // 화면이 지금 말해야 하는 한 줄 — 화면 밖에 두면 사용자가 사유를 못 본다.
  // 순서가 곧 급한 순이다: 실패 > 화면과 선택이 갈림 > 결과 없음.
  const alert = status !== "" ? status
    : shownId !== null && chosen !== null && shownId !== chosen
      ? `지금 보이는 화면은 ${shownId.slice(0, 8)}의 것입니다 — 고른 결과를 세우지 못해 직전 것이 그대로 있습니다.`
      : results.length === 0 ? "시뮬레이션 결과가 없습니다 — 시뮬레이션 탭에서 한 번 실행하면 여기 나타납니다."
        : null;

  const drawers: ReadonlyArray<{ key: DrawerKey; label: string; n: number | null }> = [
    { key: "env", label: "환경", n: null },
    { key: "perf", label: "성능", n: null },
    { key: "notes", label: "캡션", n: notes.length || null },
  ];

  return (
    <section className="wv tab-dark">
      <div className="tab-top">
        <h1>가상환경</h1>
        <div className="tab-subline">
          <p>비행한 결과를 3D 세계에 세워 봅니다. 게임 모드에서는 직접 날며 웨이포인트를 찍습니다.</p>
          <span style={{ display: "inline-flex", gap: 4 }}>
            {(["engineering", "cinematic", "game"] as const).map((v) => (
              <button
                key={v}
                className={v === style ? "primary" : ""}
                onClick={() => { setStyle(v); ctlRef.current?.setViewStyle(v); }}
                aria-pressed={v === style}
              >
                {STYLE_LABEL[v]}
              </button>
            ))}
          </span>
        </div>
      </div>

      {/* 조작줄은 캔버스 **위**다 — 시점·결과를 바꾸면 눈이 곧장 화면으로 돌아온다 */}
      <div className="wv-bar top">
        <select
          value={chosen ?? ""}
          onChange={(e) => setChosen(e.target.value)}
          aria-label="결과 선택"
        >
          {results.length === 0 && <option value="">결과 없음</option>}
          {results.map((r) => (
            <option key={r.id} value={r.id}>
              {r.id.slice(0, 8)} · {new Date(r.created * 1000).toLocaleString()}
            </option>
          ))}
        </select>
        {/* 게임 시점은 체이스 고정 — 이 버튼들을 두면 눌림 상태만 바뀌고 화면은
            그대로인 어긋남이 된다(컨트롤러 가드와 이중 방어). */}
        {style !== "game" && CAM_MODES.map((m) => (
          <button
            key={m}
            className={m === mode ? "primary" : ""}
            onClick={() => pickMode(m)}
            aria-pressed={m === mode}
          >
            {CAM_LABEL[m]}
          </button>
        ))}
        {style === "game" && (
          <span style={HINT}>← → 선회 · ↑ ↓ 피치 · Shift/Ctrl 가감속 · Space 웨이포인트</span>
        )}
      </div>

      {/* 세계 — 카드 밖, 페이지 위에 그대로 (블록도 보드·영향성 그래프와 같은 규약) */}
      <div className="wv-stage">
        <canvas
          ref={canvasRef}
          aria-label="가상환경 3D 캔버스"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={endDrag}
          // macOS는 Ctrl+클릭을 보조클릭(contextmenu)으로 합성하는데 Ctrl이 이 게임의
          // 감속 축이라, 안내된 조작 그대로가 OS 메뉴에 덮인다(리뷰 확정) — 게임에서만 막는다.
          onContextMenu={(e) => { if (style === "game") e.preventDefault(); }}
        />
        {/* 판독 — 캔버스가 말하는 것을 **글로도** 남긴다(캔버스는 보조기술에 불투명하다).
            3D 위에 얹는 이유는 보면서 읽는 값이기 때문이다. */}
        <div className="wv-hud">
          {readout ? (
            <>
              <span className="k">t</span><span className="v">{fmt(readout.t, 1, " s")}</span>
              <span className="k">고도</span><span className="v">{fmt(readout.alt, 0, " m")} (지면 {fmtSigned(readout.aboveGround)})</span>
              <span className="k">V</span><span className="v">{fmt(readout.speed, 1, " m/s")}</span>
              <span className="k">φ</span><span className="v">{deg(readout.phi)}</span>
              <span className="k">θ</span><span className="v">{deg(readout.theta)}</span>
              {readout.mode !== null && <><span className="k">모드</span><span className="v">{readout.mode}</span></>}
            </>
          ) : "표본 없음"}
        </div>
      </div>

      {style === "game" ? (
        <>
          <div className="wv-bar">
            <span style={HINT}>웨이포인트 {gameWps.length}개</span>
            {gameWps.map((w, i) => (
              <span key={`${i}-${w[0]}-${w[1]}-${w[2]}`} className="wv-wp">
                {`${i + 1}: N${w[0]} E${w[1]} h${w[2]}`}
                <button
                  aria-label={`웨이포인트 ${i + 1} 삭제`}
                  onClick={() => ctlRef.current?.removeGameWaypoint(i)}
                >×</button>
              </span>
            ))}
            <span style={{ marginLeft: "auto", display: "inline-flex", gap: 4 }}>
              <button className="primary" disabled={gameWps.length === 0} onClick={sendToSim}>
                시뮬레이션으로 보내기
              </button>
              <button
                disabled={gameWps.length === 0}
                onClick={() => ctlRef.current?.clearGameWaypoints()}
              >
                비우기
              </button>
            </span>
          </div>
          {sent !== null && (
            <p style={HINT}>
              웨이포인트 {sent}개를 보냈습니다 — <a href="#sim">시뮬레이션 탭</a>의 표·지도에서
              다듬고 실제 엔진으로 실행하세요.
            </p>
          )}
        </>
      ) : (
        <div className="wv-bar">
          <button
            className={playing ? "" : "primary"}
            onClick={() => { const p = !playing; setPlaying(p); ctlRef.current?.setPlaying(p); }}
            disabled={!playable}
          >
            {playing ? "일시정지" : playable ? "재생" : "재생 (표본 부족)"}
          </button>
          <select
            value={speed}
            onChange={(e) => { const v = Number(e.target.value); setSpeed(v); ctlRef.current?.setSpeed(v); }}
            aria-label="재생 배속"
          >
            {[1, 2, 5, 10, 20].map((v) => <option key={v} value={v}>{v}×</option>)}
          </select>
          <input
            type="range" min={0} max={Math.max(count - 1, 0)} value={cursor}
            onChange={(e) => { const v = Number(e.target.value); setCursor(v); ctlRef.current?.setCursor(v); }}
            style={{ flex: 1, minWidth: 160 }}
            aria-label="재생 위치"
          />
        </div>
      )}

      {alert !== null && <p style={HINT}>{alert}</p>}

      {/* 나머지는 눌렀을 때만 — 한 번에 하나 (영향성 탭과 같은 뼈대) */}
      <div className="tab-chips">
        {drawers.map((d) => (
          <button
            key={d.key}
            className="tab-chip"
            aria-expanded={drawer === d.key}
            aria-controls="world-drawer"
            onClick={() => setDrawer((cur) => (cur === d.key ? null : d.key))}
          >
            {d.label}{d.n !== null && <span className="n">{d.n}</span>}
          </button>
        ))}
      </div>

      <div className="tab-drawer" id="world-drawer">
        {drawer === "env" && (
          <div className="wv-env">
            <label>태양 고도
              <input type="range" min={0.03} max={1.53} step={0.01} value={sunEl}
                onChange={(e) => setSunEl(Number(e.target.value))} />
            </label>
            <label>태양 방위
              <input type="range" min={0} max={6.28} step={0.02} value={sunAz}
                onChange={(e) => setSunAz(Number(e.target.value))} />
            </label>
            <label>가시거리
              <input type="range" min={2000} max={60000} step={1000} value={visibility}
                onChange={(e) => setVisibility(Number(e.target.value))} />
            </label>
            <label>노출
              <input type="range" min={0.4} max={2} step={0.05} value={exposure}
                onChange={(e) => setExposure(Number(e.target.value))} />
            </label>
            <label>풍속
              <input type="range" min={0} max={20} step={0.5} value={windSpeed}
                onChange={(e) => setWindSpeed(Number(e.target.value))} />
            </label>
            <label>풍향
              <input type="range" min={0} max={6.28} step={0.02} value={windDir}
                onChange={(e) => setWindDir(Number(e.target.value))} />
            </label>
            <label>구름
              <input type="range" min={0} max={1} step={0.02} value={cloudCover}
                onChange={(e) => setCloudCover(Number(e.target.value))} />
            </label>
          </div>
        )}
        {drawer === "perf" && (
          <div style={{ ...HINT, fontFamily: "var(--mono)" }}>
            {stats
              ? `장면 삼각형 ${stats.triangles.toLocaleString()} · 드로우콜 ${stats.drawCalls}`
                + ` · CPU 제출 ${stats.ms.toFixed(1)} ms · 깊이 ${stats.depthBits}비트`
                + " (분할 프러스텀 — 장면을 두 번 그립니다. 후처리 쿼드는 안 셉니다)"
              : "아직 프레임 통계가 없습니다 — 장면이 한 번 그려지면 채워집니다."}
          </div>
        )}
        {drawer === "notes" && (
          <div style={HINT}>
            {notes.length === 0
              ? "표시 전용 선택이 아직 없습니다 — 결과를 세우면 여기에 그 단서가 모입니다."
              : notes.map((n, i) => <div key={i}>· {n}</div>)}
          </div>
        )}
      </div>
    </section>
  );
}
