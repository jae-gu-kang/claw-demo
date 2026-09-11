import { useCallback, useEffect, useRef, useState } from "react";

import {
  SPEECH_MAX_SPEED, lineAt, nextSpeech, normalizeScript, speakerLabel,
  type CommsLine, type SpeechState,
} from "../core/comms.ts";
import {
  readTour, tourMismatch, tourReady, tourShouldEnd, tourStopped, type WorldTour,
} from "../core/tour.ts";
import {
  errorText, fetchCommsBody, fetchLlmStatus, findCommsFor, requestComms, watchJob,
  type LlmStatus, type SimResultRow,
} from "../data/api.ts";
import { makeSpeech, type SpeechPort } from "./speech.ts";
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

/** 패널 하나 — 이름은 칩에, 내용은 열렸을 때만. 배치 뼈대는 app.css의 `.tab-*`가 준다
 *  (영향성 탭과 같은 것을 쓴다 — 같은 레이아웃을 두 벌 두지 않는다). */
type DrawerKey = "env" | "perf" | "notes" | "comms";

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
  // 열린 패널 하나 (null = 전부 닫힘). 첫 화면은 세계만 보인다 — 그것이 이 배치의 요지다.
  const [drawer, setDrawer] = useState<DrawerKey | null>(null);
  // ── 교신 대본 (F1) — 판정은 core/comms.ts, 부작용은 ui/speech.ts ─────────
  const [llm, setLlm] = useState<LlmStatus | null>(null);
  const [comms, setComms] = useState<CommsLine[] | null>(null);
  const [commsNotes, setCommsNotes] = useState<string[]>([]);
  const [commsErr, setCommsErr] = useState<string | null>(null);
  const [commsBusy, setCommsBusy] = useState(false);
  const [ccOn, setCcOn] = useState(true);
  const [voiceOn, setVoiceOn] = useState(false); // 소리는 옵트인 — 갑자기 말하면 놀란다
  const commsKeyRef = useRef<string | null>(null); // 대본 식별(결과 id) — 발화 상태 리셋 키
  const commsSubmitRef = useRef(false); // await 앞 동기 플래그 — 유료 이중 제출 방지
  const chosenRef = useRef<string | null>(null); // 생성 완료 시점의 stale-run 판정용
  // ── 가이드 투어 (D1) — 조율자는 호스트(web/js/views/tour.js)다. 여기는 그가 건
  // `worldTour`를 **읽기만** 하고(수명은 조율자가 쥔다 — effect에서 읽고 지우면 dev
  // StrictMode 이중 마운트의 두 번째가 빈 키를 본다), 재생을 켜고 끝을 알린다.
  const [voiceErr, setVoiceErr] = useState<string | null>(null);
  // 투어가 거둬져 재생을 멈춘 사유 — **이 화면 자신의 문장**으로 남긴다. 조율자 쪽
  // 카드는 이미 사라졌고 되돌리는 신호도 보내지 않으므로, 여기 없으면 "왜 멈췄지"가
  // 어디에도 안 남는다 (조용한 실패 금지)
  const [tourStopNote, setTourStopNote] = useState<string | null>(null);
  const tourRef = useRef<WorldTour | null>(null);
  const tourReadRef = useRef(false);
  if (!tourReadRef.current) {
    tourReadRef.current = true;
    tourRef.current = readTour(deps.store?.get("worldTour"));
  }
  const tourPhaseRef = useRef<"idle" | "playing" | "ended" | "aborted">("idle");
  // 끝에 닿아 멈춘 정지 — 일시정지와 달리 말하던 교신을 끊지 않는다 (core/comms.ts).
  // 끝난 **그 자리**에서만 참이다: 커서가 움직이면(스크럽) 내린다 — 안 그러면
  // 되감는 동안 지나치는 대사를 하나씩 읽는다 (리뷰 지적)
  const tourEndedRef = useRef(false);
  const tourEndCursorRef = useRef<number | null>(null);
  const speechRef = useRef<SpeechPort | null>(null);
  // 발화 실패 사유(정책 차단 등)를 화면으로 끌어올린다 — 자막만 흐르는 이유가
  // 어디에도 안 남으면 "음성이 왜 안 나오지"로 끝난다 (조용한 비표시 금지)
  if (speechRef.current == null) speechRef.current = makeSpeech({ onError: setVoiceErr });
  const speechStateRef = useRef<SpeechState>(
    { scriptKey: null, spokenIdx: null, lastT: null, active: false });

  /** 투어에게 되돌리는 신호 — 토큰을 실어 지난 투어의 것이 섞이지 않게. */
  const emitTour = useCallback((phase: string, reason?: string) => {
    const t = tourRef.current;
    if (t == null) return;
    deps.store?.set("worldTourState", { token: t.token, phase, ...(reason ? { reason } : {}) });
  }, [deps.store]);
  // 컨트롤러 콜백은 마운트 시 한 번 만들어져 첫 렌더의 클로저를 쥔다 — ref로 잇는다
  const emitTourRef = useRef(emitTour);
  emitTourRef.current = emitTour;
  /** 끝 기장 — 종료 경로 둘(자연 종료·끝 시각)이 같은 넉 줄을 각각 찍고 있었다. 끝에
   *  할 일이 하나 늘 때 한쪽만 고쳐지지 않게 접는다 (리뷰 지적). 의존성이 없어
   *  마운트 콜백이 첫 클로저를 쥐어도 같은 함수다. */
  const markEnded = useCallback(() => {
    tourPhaseRef.current = "ended";
    tourEndedRef.current = true; // 말하던 마지막 교신을 끊지 않는다
    tourEndCursorRef.current = ctlRef.current?.cursor ?? null; // 끝난 자리
    emitTourRef.current("ended");
  }, []);

  // **생성과 파괴가 대칭인 한 쌍**이다 — 그래야 StrictMode의 이중 실행에서도 컨텍스트가
  // 하나로 유지된다. 의존성이 비어 있는 것은 실수가 아니라 이 규율이다.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (canvas == null) return;
    // 컨트롤러가 새로 서면 투어 단계도 백지로 — ref는 마운트를 건너 살아남으므로,
    // dev StrictMode의 재마운트에서 phase가 "playing"인 채 남으면 두 번째 마운트가
    // 재생을 시작하지 않고 조율자는 90초 워치독을 기다리게 된다
    tourPhaseRef.current = "idle";
    tourEndedRef.current = false;
    // 짝인 셋을 함께 백지로 — 커서만 남기면 스크럽 판정(끝난 자리 비교)이 언젠가 물린다
    tourEndCursorRef.current = null;
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
      // **끝에 닿은 것은 이 신호뿐이다** — onPlaying(false)는 로드·거절·게임 진입·
      // 일시정지에서도 온다. 투어의 마무리가 여기서 열린다.
      onEnded: () => {
        if (tourPhaseRef.current !== "playing") return;
        markEnded();
      },
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

  // ── 교신 대본 (F1) — 조달·동기·발화 ──────────────────────────────────────
  // LLM 가용성 — 키 없는 배포는 사유 문장이 온다 (버튼 title로 그대로 낸다)
  useEffect(() => {
    let live = true;
    fetchLlmStatus().then((s) => { if (live) setLlm(s); }).catch((e) => {
      if (live) setLlm({ available: false, model: null, reason: `상태 조회 실패 — ${errorText(e)}` });
    });
    return () => { live = false; };
  }, []);

  // 대본이 소화할 런 길이 — normalizeScript가 런 밖 시각을 버릴 수 있게.
  // 목록이 아직 없으면 null(범위 검사 생략) — 없는 값을 지어내지 않는다.
  const tEndOf = useCallback((id: string | null): number | null => {
    const v = results.find((r) => r.id === id)?.t_end;
    return typeof v === "number" ? v : null;
  }, [results]);

  // 결과가 바뀌면 대본도 그 런의 것으로 — 기존 대본이 있으면 재사용(유료 재생성 방지)
  useEffect(() => {
    chosenRef.current = chosen; // 진행 중인 생성이 stale인지 판정하는 기준
    setComms(null); setCommsNotes([]); setCommsErr(null);
    commsKeyRef.current = null;
    if (chosen == null) return;
    let live = true;
    void (async () => {
      try {
        const id = await findCommsFor(chosen);
        if (!live || id == null) return;
        const body = await fetchCommsBody(id);
        if (!live) return;
        const norm = normalizeScript(body.lines, tEndOf(chosen));
        commsKeyRef.current = id;
        setComms(norm.lines);
        setCommsNotes([...(body.warnings ?? []), ...norm.notes]);
      } catch {
        // 캐시 조회 실패는 조용히 — [교신 대본] 생성 경로가 사유를 크게 말한다
      }
    })();
    return () => { live = false; };
  }, [chosen, tEndOf]);

  const makeComms = useCallback(async () => {
    if (chosen == null || commsSubmitRef.current) return;
    const runId = chosen; // 완료 시점 대조용 — 생성 중 런을 바꾸면 결과를 버린다
    commsSubmitRef.current = true; // await 앞 동기 구간 — 더블클릭 이중 과금 방지
    setCommsBusy(true);
    setCommsErr(null);
    try {
      const job = await requestComms(runId);
      const done = await watchJob(job.id);
      if (done.status !== "done" || done.result_id == null) {
        throw new Error(done.error ?? `대본 생성 ${done.status}`);
      }
      const body = await fetchCommsBody(done.result_id);
      // stale-run 가드 — A런 대본이 B런 재생 위에 흐르면 화면이 거짓말한다
      // (대본 자체는 서버에 저장돼 있어 그 런을 다시 고르면 재사용된다)
      if (chosenRef.current !== runId) return;
      const norm = normalizeScript(body.lines, tEndOf(runId));
      commsKeyRef.current = done.result_id;
      setComms(norm.lines);
      setCommsNotes([...(body.warnings ?? []), ...norm.notes]);
      setDrawer("comms"); // 결과가 사는 패널을 열어 준다 (전 탭 규약)
    } catch (e) {
      if (chosenRef.current !== runId) return; // 옛 런의 실패 사유도 새 런 화면엔 소음이다
      setCommsErr(errorText(e));
      setDrawer("comms");
    } finally {
      commsSubmitRef.current = false;
      setCommsBusy(false);
    }
  }, [chosen, tEndOf]);

  // 자막 선택 — 시각 정본은 readout.t (매 프레임 emitReadout, 일시정지 스크럽 포함).
  // 게임 모드는 시뮬 시각이 없어 자막·음성 대상이 아니다 (SceneController 규약).
  // activeIndex(재생 위치의 대사)와 ccIndex(오버레이 표시)를 가른다 — 자막 토글에
  // 음성까지 묶이면 자막 끄고 음성만 켠 사람이 사유 없이 침묵을 듣는다 (리뷰 지적).
  const tNow = readout?.t ?? null;
  const activeIndex = style !== "game" && comms != null ? lineAt(comms, tNow) : null;
  const ccIndex = ccOn ? activeIndex : null;
  const ccLine = ccIndex != null && comms != null ? comms[ccIndex] : undefined;

  // 발화 — 판정(core nextSpeech)이 낸 액션만 실행한다. readout 객체는 매 프레임
  // 새것이라 의존성은 tNow(수치)만 본다.
  useEffect(() => {
    const port = speechRef.current;
    if (port == null) return;
    const ctl = ctlRef.current;
    // 끝에 닿아 멈춘 정지인가 — 커서 state는 rAF 폴링이라 끝에서 한 프레임 뒤처진다
    const atEndIdx = ctl != null && ctl.sampleCount > 0 && ctl.cursor >= ctl.sampleCount - 1;
    // 끝난 뒤 커서가 움직였으면(스크럽) "끝" 표시를 내린다 — 안 내리면 되감는 동안
    // 지나치는 대사를 하나씩 읽는다. 자연 종료는 atEndIdx가 스스로 거짓이 되지만
    // 투어 종료(정지+여유)는 데이터 끝이 아니라 이 플래그만 남는다 (리뷰 지적)
    if (tourEndedRef.current && ctl != null && tourEndCursorRef.current != null
      && ctl.cursor !== tourEndCursorRef.current) {
      tourEndedRef.current = false;
    }
    const { state, action } = nextSpeech(speechStateRef.current, {
      t: tNow, playing, speed,
      enabled: voiceOn && port.available && style !== "game" && comms != null,
      index: activeIndex, scriptKey: commsKeyRef.current,
      // 끝은 일시정지와 다르다 — 말하던 마지막 교신을 끊지 않는다
      ended: !playing && (atEndIdx || tourEndedRef.current),
    });
    speechStateRef.current = state;
    if (action.kind === "speak" && comms != null) {
      const line = comms[action.index];
      if (line != null) port.speak(line.text, line.speaker);
    } else if (action.kind === "cancel") {
      port.cancel();
    }
  }, [tNow, playing, speed, voiceOn, activeIndex, comms, style]);
  // 언마운트 — 탭을 떠나도 목소리가 남으면 안 된다 (dispose는 동기 unmount)
  useEffect(() => () => { speechRef.current?.cancel(); }, []);

  // 재생이 다시 시작되면 "끝" 표시를 내린다 — 끝난 뒤의 스크럽·재생에서 발화 규칙이
  // 일시정지와 같아야 한다
  useEffect(() => {
    if (!playing) return;
    tourEndedRef.current = false;
    setTourStopNote(null); // 다시 돌기 시작했다 — 멈춤 사유는 지난 이야기다
  }, [playing]);

  // 고른 런이 바뀌어도 멈춤 사유를 내린다 — 문장이 "**이 런을** 그대로 볼 수 있다"라
  // 가리키는 런이 화면에서 바뀌면 그대로 거짓말이 되고, 지금 화면을 설명하는 줄
  // (화면과 선택이 갈림)을 몇 동작 전의 지나간 사건이 가린다 (리뷰 지적)
  useEffect(() => {
    setTourStopNote(null);
    // 투어가 켠 소리도 **투어 런을 떠날 때** 함께 내린다. 자연 종료는 마지막 교신을
    // 살리려 일부러 끄지 않는데(markEnded), 그 예외를 여기서 닫지 않으면 "그 발화가
    // 끝날 때까지"가 "투어 뒤 모든 런에 대해 영구히"로 번진다 — 발표자가 다음 런을
    // 고르는 순간 옵트인한 적 없는 음성이 그 런을 읽기 시작한다 (리뷰 지적)
    const tour = tourRef.current;
    if (tour != null && tourPhaseRef.current === "ended" && chosen !== tour.resultId) {
      setVoiceOn(false);
      // 국면을 종단으로 옮겨 **떠나는 그 한 번**으로 끝낸다. "ended"는 되돌아오는 자리가
      // 없어서, 이걸 안 하면 그 뒤 사용자가 직접 켠 음성까지 런을 바꿀 때마다 말없이
      // 꺼진다 — 버튼이 사유 없이 뒤집히는 것도 조용한 실패의 이웃이다 (리뷰 지적)
      tourPhaseRef.current = "aborted";
    }
  }, [chosen]);

  // 투어 시작 — 투어 런이 **화면에 실제로 서고** 재생 가능하며 대본이 앉은 뒤 한 번만
  useEffect(() => {
    const tour = tourRef.current;
    const ctl = ctlRef.current;
    if (tour == null || ctl == null || tourPhaseRef.current !== "idle") return;
    if (style === "game") return; // 게임에는 시뮬 시각이 없다 — 재생이 성립하지 않는다
    // 스냅샷은 첫 렌더의 것이다 — **재생이 시작되기 전**에 [중단]을 눌러도 이 탭은
    // 리마운트되지 않아 스냅샷이 그대로 남는다. 아래 멈춤 effect는 phase가 playing이라야
    // 보므로 그 창은 아무도 안 본다: 그냥 두면 중단한 뒤에 커서가 0으로 되감기고
    // 배속이 바뀌고 한 프레임 재생·음성이 번쩍인다 (리뷰 지적)
    if (tourStopped(deps.store?.get("worldTour"), tour)) return;
    if (!tourReady(tour, { chosen, shownId, playable, commsKey: commsKeyRef.current })) return;
    tourPhaseRef.current = "playing";
    const port = speechRef.current;
    if (tour.voice && port?.available) setVoiceOn(true);
    setSpeed(tour.speed);
    ctl.setSpeed(tour.speed);
    ctl.setCursor(0);
    ctl.setPlaying(true);
    emitTour("playing");
  }, [chosen, shownId, playable, comms, style, emitTour, deps.store]);

  // 투어가 어긋났다 — 목록에 없는 런(화면은 최신으로 조용히 폴백한다)·사용자가 바꾼
  // 선택·게임 모드 전환. 조용히 다른 런을 투어로 틀지 않고 사유를 돌려준다.
  useEffect(() => {
    const tour = tourRef.current;
    if (tour == null) return;
    if (tourPhaseRef.current === "ended" || tourPhaseRef.current === "aborted") return;
    const reason = style === "game"
      ? "게임 모드로 바꿔 투어를 멈췄습니다."
      : tourMismatch(tour, { chosen, resultIds: results.map((r) => r.id) });
    if (reason == null) return;
    tourPhaseRef.current = "aborted";
    ctlRef.current?.setPlaying(false);
    // 투어가 켠 소리는 **여기서도** 되돌린다. 멈춤 경로만 되돌리면, 어긋남으로 멈춘 뒤
    // 재생 화면으로 돌아왔을 때 옵트인한 적 없는 음성이 다른 런을 말하기 시작한다.
    // (자연 종료는 마지막 교신을 살리려 일부러 끄지 않는다 — 거기와는 다르다) (리뷰 지적)
    speechRef.current?.cancel();
    setVoiceOn(false);
    emitTour("aborted", reason);
  }, [chosen, results, style, emitTour]);

  // 조율자가 투어를 거뒀다 — [중단]·실패에서 `worldTour`가 지워진다. 되돌아오는 구독
  // 창구가 없어(마운트 계약은 get/set뿐) **재생 중 프레임마다** 읽는다. 안 보면 카드는
  // "멈췄다"고 적어 둔 채 기체는 계속 날고 교신은 계속 말한다 (리뷰 지적)
  useEffect(() => {
    const tour = tourRef.current;
    if (tour == null || tourPhaseRef.current !== "playing") return;
    if (!tourStopped(deps.store?.get("worldTour"), tour)) return;
    tourPhaseRef.current = "aborted"; // 시작 effect가 되살리지 않는다
    ctlRef.current?.setPlaying(false);
    speechRef.current?.cancel(); // 끝이 아니라 중단이다 — 말하던 줄을 끊는다
    setVoiceOn(false); // 투어가 켠 소리를 되돌린다 (소리는 옵트인)
    // 신호는 보내지 않는다 — 거둔 쪽이 조율자이고 그쪽 run은 이미 없다. 대신 **이 화면의
    // 문장**으로 남긴다: 일시정지 중에 거둬지면 판독이 멈춰 이 effect가 잠들었다가,
    // 투어와 무관해진 사용자가 혼자 [재생]을 누른 그 순간 깨어나 재생을 뺏는다 —
    // 사유가 없으면 "눌렀는데 안 된다"로만 남는다 (리뷰 지적)
    setTourStopNote("가이드 투어가 중단돼 재생과 음성을 멈췄습니다 — "
      + "다시 [재생]을 누르면 이 런을 그대로 볼 수 있습니다.");
  }, [tNow, deps.store]);

  // 투어 종료 — 기체가 선 뒤 t_end까지 남은 빈 구간을 청중에게 보이지 않는다
  // (끝 시각은 조율자가 재생 본문의 meta.phases에서 계산해 준다)
  useEffect(() => {
    const tour = tourRef.current;
    if (tour == null || tourPhaseRef.current !== "playing") return;
    if (!tourShouldEnd(tour, tNow)) return;
    markEnded();
    ctlRef.current?.setPlaying(false); // 자연 종료와 달리 아직 돌고 있다 — 여기서 세운다
  }, [tNow, markEnded]);

  // 음성이 막혔다(정책 차단 등) — 투어 카드도 그 사유를 말해야 한다
  useEffect(() => {
    if (voiceErr == null) return;
    if (tourPhaseRef.current === "playing") emitTour("voice_error", voiceErr);
  }, [voiceErr, emitTour]);

  // 화면이 지금 말해야 하는 한 줄 — 화면 밖에 두면 사용자가 사유를 못 본다.
  // 순서가 곧 급한 순이다: 실패 > 투어가 거둬져 멈춤 > 화면과 선택이 갈림 > 결과 없음.
  const alert = status !== "" ? status
    : tourStopNote !== null ? tourStopNote
      : shownId !== null && chosen !== null && shownId !== chosen
        ? `지금 보이는 화면은 ${shownId.slice(0, 8)}의 것입니다 — 고른 결과를 세우지 못해 직전 것이 그대로 있습니다.`
        : results.length === 0 ? "시뮬레이션 결과가 없습니다 — 시뮬레이션 탭에서 한 번 실행하면 여기 나타납니다."
          : null;

  const drawers: ReadonlyArray<{ key: DrawerKey; label: string; n: number | null }> = [
    { key: "env", label: "환경", n: null },
    { key: "perf", label: "성능", n: null },
    { key: "notes", label: "캡션", n: notes.length || null },
    { key: "comms", label: "교신", n: comms?.length ?? null },
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
        {/* 교신 자막 (F1) — 상단 중앙, 판독(.wv-hud 좌하단)과 안 겹치는 자리.
            캔버스가 보조기술에 불투명하므로 대본 전문은 「교신」 드로어에도 있다. */}
        {ccLine != null && (
          <div className="wv-cc">
            <span className="spk">{speakerLabel(ccLine.speaker)}</span>
            {ccLine.text}
          </div>
        )}
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
          {/* 교신 (F1) — 못 누르는 상태는 끄되 사유를 title로 (조용한 비활성 금지) */}
          <button
            className={ccOn ? "primary" : ""}
            aria-pressed={ccOn}
            disabled={comms == null}
            title={comms == null ? "대본이 없습니다 — [교신 대본]으로 만듭니다" : "교신 자막 표시"}
            onClick={() => setCcOn((v) => !v)}
          >자막</button>
          <button
            className={voiceOn ? "primary" : ""}
            aria-pressed={voiceOn}
            disabled={comms == null || speechRef.current?.available !== true}
            title={speechRef.current?.available !== true
              ? (speechRef.current?.reason ?? "음성 합성을 쓸 수 없습니다")
              // 정책 차단 등으로 실제 발화가 실패했다 — 사유를 여기서도 말한다
              : voiceErr != null ? `음성이 막혔습니다 (${voiceErr}) — 자막만 흐릅니다`
              : comms == null ? "대본이 없습니다 — [교신 대본]으로 만듭니다"
              : `교신 음성 (배속 ${SPEECH_MAX_SPEED}× 초과에서는 자막만)`}
            onClick={() => setVoiceOn((v) => !v)}
          >음성</button>
          <button
            disabled={commsBusy || chosen == null || llm?.available !== true}
            title={llm == null ? "서버 LLM 상태 확인 중…"
              : !llm.available ? (llm.reason ?? "사용할 수 없습니다")
              : chosen == null ? "결과를 먼저 고릅니다"
              : "이 런의 비행 로그로 관제 교신 대본을 만듭니다 (서버 경유 LLM 호출)"}
            onClick={() => { void makeComms(); }}
          >{commsBusy ? "대본 생성 중…" : comms != null ? "대본 다시 만들기" : "교신 대본"}</button>
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
        {drawer === "comms" && (
          <div style={HINT}>
            {commsErr != null && <div style={{ color: "#ff6b6b" }}>{commsErr}</div>}
            {commsNotes.map((n, i) => <div key={`note${i}`}>· {n}</div>)}
            {comms == null ? (
              <div>
                {llm != null && !llm.available
                  ? llm.reason
                  : "대본이 없습니다 — 재생줄의 [교신 대본]을 누르면 이 런의 비행 "
                    + "로그로 관제 교신이 생성됩니다. 자막·음성은 재생 커서를 따라 흐릅니다."}
              </div>
            ) : comms.length === 0 ? (
              <div>대본이 비어 있습니다 — [대본 다시 만들기]로 재생성해 보십시오.</div>
            ) : (
              comms.map((l, i) => (
                <div
                  key={i}
                  style={i === activeIndex
                    ? { color: "rgba(255,255,255,.95)", fontWeight: 600 }
                    : undefined}
                >
                  <span style={{ fontFamily: "var(--mono)" }}>{`t=${l.t.toFixed(1)}s `}</span>
                  <b>{speakerLabel(l.speaker)}</b> — {l.text}
                </div>
              ))
            )}
          </div>
        )}
      </div>
    </section>
  );
}
