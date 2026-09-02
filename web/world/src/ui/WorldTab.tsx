import { useCallback, useEffect, useRef, useState } from "react";

import type { SimResultRow } from "../data/api.ts";
import type { FrameStats } from "../scene/SceneController.ts";
import {
  CAM_MODES, SceneController, createController, type CamMode, type Readout,
} from "../scene/SceneController.ts";
import type { MountDeps } from "../main.tsx";

const HINT: React.CSSProperties = { fontSize: 12, color: "var(--muted)", lineHeight: 1.6 };
const ROW: React.CSSProperties = { display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" };

const CAM_LABEL: Record<CamMode, string> = {
  chase: "추적", orbit: "자유 궤도", onboard: "온보드 1인칭", attitude: "자세 관측",
};

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
  const dragRef = useRef<{ x: number; y: number } | null>(null);

  const [status, setStatus] = useState("초기화 중…");
  const [notes, setNotes] = useState<string[]>([]);
  const [readout, setReadout] = useState<Readout | null>(null);
  const [results, setResults] = useState<SimResultRow[]>([]);
  const [chosen, setChosen] = useState<string | null>(null);
  const [mode, setMode] = useState<CamMode>("chase");
  const [playing, setPlaying] = useState(false);
  const [playable, setPlayable] = useState(false);
  const [shownId, setShownId] = useState<string | null>(null);
  const [stats, setStats] = useState<FrameStats | null>(null);
  const [speed, setSpeed] = useState(5);
  const [cursor, setCursor] = useState(0);
  const [count, setCount] = useState(0);
  const [sunEl, setSunEl] = useState(0.6);
  const [sunAz, setSunAz] = useState(2.0);
  const [visibility, setVisibility] = useState(25000);
  const [exposure, setExposure] = useState(0.95);
  // 해상 상태 — **표시 값**이다. 7 m/s는 남해안의 흔한 바람이고 유의파고 1.0 m가 나온다.
  const [windSpeed, setWindSpeed] = useState(7);
  const [windDir, setWindDir] = useState(0.6);
  const [cloudCover, setCloudCover] = useState(0.35);

  // **생성과 파괴가 대칭인 한 쌍**이다 — 그래야 StrictMode의 이중 실행에서도 컨텍스트가
  // 하나로 유지된다. 의존성이 비어 있는 것은 실수가 아니라 이 규율이다.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (canvas == null) return;
    const abort = new AbortController();

    const made = createController(canvas, {
      onNotes: setNotes,
      onMode: setMode,
      onReadout: setReadout,
      onResults: (rows, first) => { setResults(rows); setChosen((c) => c ?? first); },
      onStatus: setStatus,
      onPlaying: setPlaying,
      onStats: setStats,
    });
    if (made.controller == null) {
      setStatus(made.reason);
      return;
    }
    const ctl = made.controller;
    ctlRef.current = ctl;
    ctl.start();

    const ro = new ResizeObserver(() => {
      const w = canvas.clientWidth;
      // 2:1 로 고정한다 — 캔버스 비율이 화면 폭에 따라 흔들리면 시야각이 같이 흔들린다.
      const h = Math.max(Math.round(w * 0.5), 240);
      canvas.style.height = `${h}px`;
      // **백킹스토어는 여기서 안 건드린다.** `renderer.setSize(w, h, false)`와
      // `setPixelRatio`가 그 일을 하고, 여기서 또 쓰면 DPR 클램프가 두 파일에 갈린다.
      ctl.resize(w, h, devicePixelRatio);
    });
    ro.observe(canvas);

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
    e.currentTarget.setPointerCapture(e.pointerId);
    dragRef.current = { x: e.clientX, y: e.clientY };
  };
  const onPointerMove = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const d = dragRef.current;
    if (d == null) return;
    // **시점을 여기서 짐작하지 않는다.** 끌어서 궤도로 넘어가는 조건은 컨트롤러가 쥐고
    // 있고(자세 관측에서는 안 넘어간다), 넘어가면 `onMode`로 알려 준다. 여기서
    // `setMode("orbit")`을 하면 카메라는 자세 관측인데 버튼만 자유 궤도가 된다.
    ctlRef.current?.rotate(e.clientX - d.x, e.clientY - d.y);
    dragRef.current = { x: e.clientX, y: e.clientY };
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

  return (
    <section className="panel">
      <h2>가상환경</h2>

      <div style={ROW}>
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
        {CAM_MODES.map((m) => (
          <button
            key={m}
            className={m === mode ? "primary" : ""}
            onClick={() => pickMode(m)}
            aria-pressed={m === mode}
          >
            {CAM_LABEL[m]}
          </button>
        ))}
      </div>

      <canvas
        ref={canvasRef}
        aria-label="가상환경 3D 캔버스"
        style={{ width: "100%", display: "block", borderRadius: 8, background: "#0d1117", touchAction: "none" }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
      />

      <div style={ROW}>
        <button
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

      {/* 판독 — 캔버스가 말하는 것을 **글로도** 남긴다(캔버스는 보조기술에 불투명하다). */}
      <div style={{ ...HINT, fontFamily: "var(--mono)" }}>
        {readout
          ? `t ${fmt(readout.t, 1, " s")} · ${readout.mode ?? "—"}`
            + ` · h ${fmt(readout.alt, 0, " m")}`
            + ` (지면 ${fmtSigned(readout.aboveGround)})`
            + ` · V ${fmt(readout.speed, 1, " m/s")} · φ ${deg(readout.phi)} θ ${deg(readout.theta)}`
          : "표본 없음"}
      </div>

      <div style={ROW}>
        <label style={HINT}>태양 고도
          <input type="range" min={0.03} max={1.53} step={0.01} value={sunEl}
            onChange={(e) => setSunEl(Number(e.target.value))} />
        </label>
        <label style={HINT}>태양 방위
          <input type="range" min={0} max={6.28} step={0.02} value={sunAz}
            onChange={(e) => setSunAz(Number(e.target.value))} />
        </label>
        <label style={HINT}>가시거리
          <input type="range" min={2000} max={60000} step={1000} value={visibility}
            onChange={(e) => setVisibility(Number(e.target.value))} />
        </label>
        <label style={HINT}>노출
          <input type="range" min={0.4} max={2} step={0.05} value={exposure}
            onChange={(e) => setExposure(Number(e.target.value))} />
        </label>
        <label style={HINT}>풍속
          <input type="range" min={0} max={20} step={0.5} value={windSpeed}
            onChange={(e) => setWindSpeed(Number(e.target.value))} />
        </label>
        <label style={HINT}>풍향
          <input type="range" min={0} max={6.28} step={0.02} value={windDir}
            onChange={(e) => setWindDir(Number(e.target.value))} />
        </label>
        <label style={HINT}>구름
          <input type="range" min={0} max={1} step={0.02} value={cloudCover}
            onChange={(e) => setCloudCover(Number(e.target.value))} />
        </label>
      </div>

      {shownId !== null && chosen !== null && shownId !== chosen && (
        <p style={HINT}>
          지금 보이는 화면과 캡션은 <code>{shownId.slice(0, 8)}</code>의 것입니다 —
          고른 결과를 세우지 못해 직전 것이 그대로 있습니다.
        </p>
      )}
      {stats && (
        <div style={{ ...HINT, fontFamily: "var(--mono)" }}>
          {`장면 삼각형 ${stats.triangles.toLocaleString()} · 드로우콜 ${stats.drawCalls}`
            + ` · CPU 제출 ${stats.ms.toFixed(1)} ms · 깊이 ${stats.depthBits}비트`
            + " (분할 프러스텀 — 장면을 두 번 그립니다. 후처리 쿼드는 안 셉니다)"}
        </div>
      )}
      {results.length === 0 && !status && (
        <p style={HINT}>
          시뮬레이션 결과가 없습니다 — <a href="#sim">시뮬레이션 탭</a>에서 한 번 실행하면
          여기에 나타납니다.
        </p>
      )}
      {status && <p style={HINT}>{status}</p>}

      {/* 캡션 — 표시 전용 선택은 전부 여기서 밝힌다 (이 저장소의 규약). */}
      <div style={HINT}>
        {notes.map((n, i) => <div key={i}>· {n}</div>)}
      </div>
    </section>
  );
}
