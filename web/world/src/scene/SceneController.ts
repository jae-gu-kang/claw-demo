/** 화면 하나를 굴리는 명령형 오케스트레이터 — React는 여기에 값을 밀어 넣기만 한다.
 *
 * ## 왜 클래스인가
 *
 * WebGL 컨텍스트가 브라우저당 8~16개뿐이고, 렌더러를 `useEffect` 안에서 만들면 의존성이
 * 하나 바뀔 때마다 다시 만들어진다. 생성·파괴를 **대칭인 한 쌍**으로 묶어 두면 React가
 * 몇 번 렌더되든 컨텍스트는 하나다.
 *
 * ## 결측을 그리지 않는다
 *
 * 위치·자세가 없으면 기체를 숨기고, 발사 정보가 없으면 발사관을 숨긴다. 0으로 메우면
 * 없는 수평비행과 없는 발사 자세를 지어내게 된다 — 그리고 그건 화면에서 옳은 것과
 * 구별되지 않는다.
 */

import { atEnd, dtSample, indexAt, isPlayable } from "../lib/playcursor.ts";
import { bodyAxesNed, eulerToQuat, type Quat, type Vec3 } from "../lib/attitude.ts";
import {
  CAM_MODES, FOV_Y, attitudeCamera, chaseCamera, onboardCamera, orbitCamera,
  rotateBy, shouldResetSmoothing, type CamMode, type CameraPose,
} from "../lib/camera.ts";
import { attitudeAt, originsAgree, sampleAt, sceneExtent, trackPoints, velocityAt }
  from "../lib/world3d.ts";
import { elevationAt, parseTerrainPack, tierRect, type TerrainPack } from "../lib/terrainpack.ts";
import { spawnArcade, stepArcade, type ArcadeInput, type ArcadeState } from "../core/arcade.ts";
import { reliefOf } from "../core/gamestyle.ts";
import { placeProps } from "../core/propfield.ts";
import { buildPropsGroup } from "./props.ts";
import { strideFor } from "../lib/replay.ts";
import { ATMOSPHERE_NOTES, CLOUD_NOTES } from "./atmosphere.ts";
import { WEAR_NOTES } from "./materials.ts";
import { launcherCaptionNotes, launcherPose } from "../core/launcher.ts";
import { SURFACE_NOTES, propellerRate, surfacePose } from "../core/surfaces.ts";
import { WAVE_NOTES } from "../core/waves.ts";
import type { Replay } from "../core/types.ts";
import {
  fetchReplay, fetchTerrainPack, fetchWorldManifest, listSimResults, modelUrl,
  type SimResultRow, type WorldManifest,
} from "../data/api.ts";
import { SceneHost, createSceneHost, type Marker, type ViewStyle } from "./SceneHost.ts";
import { buildCoastField } from "../core/coastfield.ts";
import { buildTerrain } from "./terrain.ts";
import {
  LAUNCHER_NODES, VEHICLE_NODES, applySurfaces, hideVehicle, loadModel,
  setVehiclePose, showLauncher, spinPropeller, type LoadedModel,
} from "./models.ts";

/** 기체는 **실물 크기(1배)로만** 그린다.
 *
 * 처음에는 시점마다 8배·3배로 키웠다(스팬 2.5 m가 300 m 밖에서 한 픽셀이라). 걷어낸
 * 이유는 발사관이다 — 발사관은 1배인데 기체만 8배면 캐니스터에 들어갈 수 없는 크기로
 * 보여, 배율을 캡션이 밝혀도 화면 자체가 비례를 거짓말한다(사용자 지적). 대신 추적·자세
 * 카메라가 실물에 맞게 **가까이** 붙는다(`closeDist`). 궤도 시점에서 기체가 점이 되는
 * 것은 사실이 그런 것이다 — 휠로 다가가면 된다. */
const MODEL_SCALE = 1;

/** 게임 웨이포인트의 표시용 포획 반경 [m] — 시뮬레이션 탭 도달반경 **기본값(100)**과
 *  같은 수다(views/sim.js `f.accept`). 다른 수를 쓰면 게임에서 본 원과 실행에 들어가는
 *  원이 어긋난다 — 물론 시뮬 탭에서 반경을 고치면 그때부터는 그쪽이 정본이다. */
const GAME_ACCEPT_RADIUS = 100;
/** 지형 클릭 웨이포인트의 지면 위 여유 [m] — 계획용 기본값. 캡션·시뮬 탭 표에서 보인다. */
const GAME_CLICK_CLEARANCE = 150;
/** 게임 지형의 목표 낱면 크기 [m] — 이보다 촘촘한 티어는 스트라이드로 성기게 한다. */
const GAME_FACET_M = 90;

export interface Readout {
  t: number | null;
  mode: string | null;
  /** MSL 고도 [m] */
  alt: number | null;
  /** **실제 지면 위** 높이 [m] — 지형 격자 밖이면 null이고 화면이 "—"를 낸다.
   *  활주로 표고로 물러서면 "대지고도"라는 이름으로 다른 양을 내놓게 된다. */
  aboveGround: number | null;
  speed: number | null;
  phi: number | null;
  theta: number | null;
}

/** 프레임마다의 비용 — 화면이 계속 말한다. 분할 프러스텀은 장면을 두 번 그리므로
 *  그 대가가 보여야 판단이 선다(계획 §검증). */
export interface FrameStats {
  drawCalls: number;
  triangles: number;
  ms: number;
  depthBits: number;
}

export interface ControllerCallbacks {
  onNotes(notes: string[]): void;
  /** **시점의 정본은 컨트롤러다.** 끌어서 궤도로 넘어가는 조건이 여기 있으므로,
   *  UI가 스스로 짐작하면 자세 관측에서 끌었을 때 버튼만 "자유 궤도"로 바뀌고
   *  카메라는 그대로인 상태가 된다(그리고 시점 캡션이 버튼과 어긋난다). */
  onMode(mode: CamMode): void;
  /** null = 판독 없음("표본 없음") — 결과 없이 게임을 나간 뒤 옛 게임 값이 굳지 않게. */
  onReadout(r: Readout | null): void;
  onResults(rows: SimResultRow[], chosen: string | null): void;
  onStatus(text: string): void;
  onPlaying(playing: boolean): void;
  onStats(s: FrameStats): void;
  /** 게임 모드 웨이포인트 목록 — 찍고/지울 때마다. UI 목록·보내기 버튼이 이걸 그린다. */
  onGameWps(wps: ReadonlyArray<readonly [number, number, number]>): void;
}

/** 통계를 화면에 올리는 주기 [ms] — 초당 60번 바뀌는 숫자는 읽을 수 없다. */
const STATS_INTERVAL_MS = 500;

const num = (v: unknown): number | null =>
  typeof v === "number" && Number.isFinite(v) ? v : null;

export class SceneController {
  private readonly host: SceneHost;
  private readonly cb: ControllerCallbacks;

  private raf = 0;
  private disposed = false;
  private dirty = true;

  private pack: TerrainPack | null = null;
  /** **원점이 맞아 실제로 얹은** 지형. `pack`과 다르다 — 원점이 어긋나면 그리지도,
   *  표고를 재지도 않는다. 그리지 않으면서 그것으로 고도를 재면 화면이 "얹을 수 없다"고
   *  말하면서 그 지형 기준 고도를 판독부에 찍는다(그리고 카메라를 보이지 않는 능선 위로
   *  들어 올린다). `views/world.js:386`이 `state.terrain`을 따로 두는 이유가 이것이다. */
  private terrain: TerrainPack | null = null;
  private manifest: WorldManifest | null = null;
  private vehicle: LoadedModel | null = null;
  private launcher: LoadedModel | null = null;
  private results: SimResultRow[] = [];

  private body: Replay | null = null;
  /** 마지막으로 성했던 위치·자세. **결측 프레임에서 그 자리에 머문다** — 0으로 메우면
   *  기체가 원점으로 순간이동하고, 그 도약을 후방차분한 속도가 체이스 방향까지 정한다. */
  private lastPos: Vec3 | null = null;
  private lastAtt: Vec3 | null = null;
  private n = 0;
  private dt = 0.1;
  private idx = 0;
  private prevIdx: number | null = null;
  private chaseEye: Vec3 | null = null;
  private lastFrameMs = performance.now();

  // 첫 시점은 **자유 궤도** — 추적으로 시작하면 첫 화면이 마른 땅과 발사관뿐이라
  // 바다·해안이 있는 줄도 모른다(사용자 지적). 카메라를 동쪽(az≈1.4)에 두어 서쪽
  // 바다를 바라보고, 기본 태양(서남서)의 윤슬이 그 방향에 선다.
  private mode: CamMode = "orbit";
  private orbit = { az: 1.15, el: 0.25 };
  private dist = 400;
  /** 추적·자세 시점의 근접 거리 [m] — 궤도의 `dist`(장면 규모)와 분리한다.
   *  하나로 쓰면 궤도에서 한 번 벌린 값이 추적으로 넘어와 기체가 점이 된다. */
  private closeDist = 16;
  private playing = false;
  private speed = 5;
  private fromIdx = 0;
  private fromWall = 0;

  // ---- 게임 모드 상태 — 정본은 컨트롤러다(시점·재생과 같은 사유).
  private arcade: ArcadeState | null = null;
  private gameInput: ArcadeInput = { turn: 0, pitch: 0, throttle: 0 };
  /** [n, e, 고도 h] — 시뮬 탭 표와 같은 어휘(고도 상방 +). */
  private gameWps: [number, number, number][] = [];
  private gameEye: Vec3 | null = null;
  private gameDist = 18;
  /** 어느 지형 팩으로 게임 자산을 구웠나 — 팩이 바뀌면 다시 굽는다.
   *  **undefined = 아직 안 구움**, null = "팩 없음" 상태로 구움. 이 둘을 한 값으로
   *  쓰면 "지형 로드 전에 게임 진입 → 뒤늦게 팩 도착"에서 null === null이 참이 되어
   *  게임 지형이 영영 안 구워진다(실측 — 조기 클릭 재현). */
  private gameBuiltFor: TerrainPack | null | undefined = undefined;
  private replayMarks: Marker[] = [];
  private get gameOn(): boolean { return this.style === "game"; }

  private terrainNotes: string[] = [];
  /** 결과에서 나오는 캡션 — 결과가 바뀔 때만 다시 만든다. */
  private resultNotes: string[] = [];
  private loadGen = 0;
  private shownId: string | null = null;
  private missingPos = 0;
  private missingAtt = 0;

  constructor(host: SceneHost, cb: ControllerCallbacks) {
    this.host = host;
    this.cb = cb;
    this.depthBits = host.describe().depthBits;
  }

  /** 결과와 무관한 자산 — 한 번만 읽는다. 없으면 **사유를 문장으로** 남긴다. */
  async loadWorld(signal: AbortSignal): Promise<void> {
    try {
      this.manifest = await fetchWorldManifest();
    } catch (e) {
      this.terrainNotes.push(`자산 목록을 읽지 못했습니다 — ${(e as Error).message}`);
      return;
    }
    if (signal.aborted || this.disposed) return;

    const packName = this.manifest.terrain[0]?.name;
    if (packName) {
      try {
        this.pack = parseTerrainPack(await fetchTerrainPack(packName, signal));
      } catch (e) {
        this.terrainNotes.push(`지형 팩을 읽지 못했습니다 — ${(e as Error).message}`);
      }
    } else if (this.manifest.reason) {
      this.terrainNotes.push(this.manifest.reason);
    }
    if (signal.aborted || this.disposed) return;

    // 모델 — 없으면 사유가 매니페스트에 실려 온다(빼 놓고 침묵하지 않는다).
    const names = new Set(this.manifest.models.map((m) => m.name));
    if (names.has("shahed136.glb")) {
      const r = await loadModel(modelUrl("shahed136.glb"), VEHICLE_NODES, signal);
      if (r.model) { this.vehicle = r.model; this.host.modelGroup.add(r.model.root); }
      else this.terrainNotes.push(r.reason);
    }
    if (names.has("launcher.glb")) {
      const r = await loadModel(modelUrl("launcher.glb"), LAUNCHER_NODES, signal);
      if (r.model) { this.launcher = r.model; this.host.modelGroup.add(r.model.root); }
      else this.terrainNotes.push(r.reason);
    }
    if (this.manifest.models_reason) this.terrainNotes.push(this.manifest.models_reason);
    for (const m of [this.vehicle, this.launcher]) {
      if (m && m.missing.length > 0) {
        this.terrainNotes.push(
          `모델에서 못 찾은 노드: ${m.missing.join(", ")} — 그 부분은 움직이지 않습니다.`,
        );
      }
    }
    this.dirty = true;
  }

  /** 결과 목록. `prefer`(시뮬 탭이 고른 것)가 목록에 있으면 그것을 먼저 연다. */
  async loadResults(prefer?: string | null): Promise<void> {
    this.results = await listSimResults();
    const chosen = this.results.find((r) => r.id === prefer)?.id
      ?? this.results[0]?.id ?? null;
    this.cb.onResults(this.results, chosen);
  }

  /** 결과 하나를 읽어 장면을 세운다. 세대 토큰으로 늦은 응답이 새 선택을 못 덮게 한다. */
  /** 실패하면 **false**를 낸다 — 호출측이 슬라이더·커서를 옛 결과 것으로 갱신하지 않게.
   *
   * `signal`은 안 받는다: `api.get`이 신호를 안 받아 요청 자체를 못 끊으므로, 있으면
   * "취소된다"는 잘못된 기대를 준다. 늦은 응답은 **세대 토큰**이 막는다. */
  async loadResult(id: string): Promise<boolean> {
    const gen = ++this.loadGen;
    this.cb.onStatus("결과를 불러오는 중…");
    // 표본 수는 **목록이 들고 있다** — 예전처럼 결과 전체를 받지 않는다.
    // 없으면 큰 결과라고 **보수적으로** 가정한다. stride 1은 서버가 payload를 통째로
    // 내주는 경로라(routes/sim.py), 모르는 채 그쪽으로 가면 안 된다.
    const n = this.results.find((r) => r.id === id)?.n;
    const known = typeof n === "number" && Number.isFinite(n) && n > 0;
    let body: Replay;
    try {
      body = await fetchReplay(id, strideFor(known ? n : 20000));
    } catch (e) {
      if (gen === this.loadGen) this.cb.onStatus(`불러오지 못했습니다 — ${(e as Error).message}`);
      return false;
    }
    if (gen !== this.loadGen || this.disposed) return false;

    this.body = body;
    this.n = body.t.length;
    this.dt = dtSample(body.t) ?? 0.1;
    this.idx = 0;
    this.prevIdx = null;
    this.chaseEye = null;
    this.playing = false;
    this.cb.onPlaying(false);
    this.lastPos = null;
    this.lastAtt = null;
    this.fellBack = null;
    this.shownId = id;
    try {
      this.buildScene();
    } catch (e) {
      // **반쯤 세워진 장면을 "성공"이라고 하지 않는다.** 몸통은 새 결과인데 지형·궤적이
      // 옛 것일 수 있어, 화면과 선택칸이 조용히 갈린다. 사유를 내고 실패로 답한다.
      this.cb.onStatus(`장면을 세우지 못했습니다 — ${(e as Error).message}`);
      return false;
    }
    this.dirty = true;
    this.cb.onStatus("");
    return true;
  }

  private buildScene(): void {
    const body = this.body;
    if (body == null) return;
    const notes = [...this.terrainNotes];

    // --- 지형 (원점이 맞을 때만 얹는다) ---
    const agree = originsAgree(this.pack?.origin, body.meta?.origin);
    this.terrain = this.pack && agree.ok ? this.pack : null;
    // 게임 자산은 이 지형에 매여 있다 — 팩이 바뀌면(원점 불합의 포함, 그리고
    // "없음 → 도착"의 조기 진입 경로 포함) 다시 굽거나 무효화한다.
    if (this.gameBuiltFor !== undefined && this.gameBuiltFor !== this.terrain) {
      this.gameBuiltFor = undefined;
      if (this.gameOn) this.buildGameWorld();
    }
    if (this.terrain) {
      const built = buildTerrain(this.terrain);
      this.host.setTerrain(built.meshes);
      notes.push(...built.notes);
      // 해안 거리장은 **지형과 같은 마스크에서** 나온다. 따로 판정하면 해안선이 두 벌이
      // 되고, 파고가 잦아드는 자리와 지형이 끝나는 자리가 어긋난다.
      const tiers = this.terrain.tiers
        .map((tier) => ({ tier, mask: built.masks.get(tier.name) }))
        .filter((x): x is { tier: typeof x.tier; mask: NonNullable<typeof x.mask> } =>
          x.mask !== undefined);
      const t0 = performance.now();
      const field = buildCoastField(tiers);
      this.host.setCoast(field);
      notes.push(
        `해면: 해안 거리장 ${field.size}² (${field.metersPerCell.toFixed(0)} m/칸, `
        + `${(performance.now() - t0).toFixed(0)} ms) — 파고는 해안에서 잦아듭니다.`,
      );
    } else {
      this.host.setTerrain([]);
      // 지형이 없으면 해안선도 모른다 — 해면을 **그리지 않는다**(`Ocean.setCoast`).
      this.host.setCoast(null);
      notes.push("지형이 없어 해안선을 모릅니다 — 해면도 그리지 않습니다.");
      if (this.pack && agree.reason) notes.push(agree.reason);
    }

    // --- 활주로: 중심선 + 시단·종단 --- (원점에서 heading 방향 length 구간 — lib/site.js와
    // lib/replay.js가 이 규약을 전제로 판정한다. 폭은 결과에 없어 그리지 않는다.)
    const rw = body.meta?.runway;
    const rwLines: { points: Float32Array; color: number }[] = [];
    if (rw && num(rw.heading) !== null && num(rw.length) !== null) {
      const el = num(rw.elevation) ?? 0;
      const h = num(rw.heading)!;
      const L = num(rw.length)!;
      const n1 = Math.cos(h) * L;
      const e1 = Math.sin(h) * L;
      const pts: number[] = [0, 0, -el, n1, e1, -el];
      // 시단·종단 가로선 — 접지 지점을 눈으로 짚을 수 있게 (옛 화면과 같은 22 m 반폭).
      for (const [n0, e0] of [[0, 0], [n1, e1]] as const) {
        pts.push(n0 - -Math.sin(h) * 22, e0 - Math.cos(h) * 22, -el,
                 n0 + -Math.sin(h) * 22, e0 + Math.cos(h) * 22, -el);
      }
      rwLines.push({ points: new Float32Array(pts), color: 0xffffff });
      notes.push("활주로는 중심선과 양 끝만 그립니다 — 폭은 결과에 없습니다.");
    }


    // --- 궤적 ---
    const { points, breaks } = trackPoints(body.signals, this.n);
    this.host.setPaths([{ points, color: 0x32d3ff, breaks }, ...rwLines]);
    this.missingPos = breaks.length;
    this.missingAtt = 0;
    for (let i = 0; i < this.n; i++) if (attitudeAt(body.signals, i) === null) this.missingAtt++;
    if (this.missingPos > 0) {
      notes.push(`위치 결측 ${this.missingPos}/${this.n} 표본 — 그 구간은 선을 끊었습니다.`);
    }
    if (this.missingAtt > 0) {
      notes.push(`자세 결측 ${this.missingAtt}/${this.n} 표본 — 그 구간은 기체를 그리지 않습니다.`);
    }

    // --- 표지: 웨이포인트 + 출발점 --- (옛 화면과 같은 어휘 — 기능 동등의 마지막 조각)
    const marks: Marker[] = [];
    const acceptRadius = num(body.meta?.accept_radius) ?? 0;
    const rwElev = num(body.meta?.runway?.elevation) ?? 0;
    for (const w of body.meta?.waypoints ?? []) {
      const n0 = num(w[0]);
      const e0 = num(w[1]);
      if (n0 === null || e0 === null) continue;
      // 고도가 없는 웨이포인트는 활주로 표고에 놓는다 — 옛 화면과 같은 관례다.
      const d = w.length > 2 && num(w[2]) !== null ? -num(w[2])! : -rwElev;
      marks.push({ ne: [n0, e0, d], kind: "waypoint", radius: acceptRadius });
    }
    // 출발점은 **성한 첫 표본**에만 찍는다 — 결측이면 원점에 초록 점을 지어내게 된다.
    for (let i = 0; i < this.n; i++) {
      const s0 = sampleAt(body.signals, i);
      if (s0) { marks.push({ ne: s0, kind: "start", radius: 0 }); break; }
    }
    // 게임 모드 중에 결과를 갈아 끼워도 게임 표지를 덮지 않는다 — syncMarkers가 정본.
    this.replayMarks = marks;
    this.syncMarkers();

    // --- 기체 형상 --- (실물 1배 — MODEL_SCALE 주석 참조)
    if (this.vehicle == null) {
      notes.push("기체 모델이 없어 궤적만 그립니다.");
    } else {
      notes.push(SURFACE_NOTES.innerOuterShared, SURFACE_NOTES.rudderShared,
        SURFACE_NOTES.propellerDisplay, SURFACE_NOTES.holdOnMissing);
    }

    // --- 발사관 ---
    const lp = launcherPose(body.meta?.launch);
    if (this.launcher) {
      const site: Vec3 = [0, 0, -(num(body.meta?.runway?.elevation) ?? 0)];
      showLauncher(this.launcher, site, lp);
      if (lp == null) notes.push("발사 정보가 없어 발사관을 그리지 않습니다.");
      else notes.push(...launcherCaptionNotes(body.meta?.launch, lp));
    }
    this.dist = Math.max(sceneExtent(body.signals) * 0.25, 200);
    this.resultNotes = notes;
    this.emitNotes();
  }

  /** 결과 캡션 + **지금 시점에 달린** 캡션.
   *
   * 시점에 달린 캡션(물러섬 사유 등)은 시점이 바뀔 때 다시 만들어야 한다 —
   * 결과를 읽을 때 한 번만 만들면 옛 문장이 남는다. `views/world.js`가 같은 자리에서 겪고
   * `captionStale` 플래그로 고쳐 둔 것을 여기서는 시점이 바뀔 때 다시 만드는 것으로 푼다. */
  private emitNotes(): void {
    const notes = [...this.resultNotes];
    if (this.fellBack !== null) {
      const why = this.fellBack === "att" ? "자세가 없어" : "위치가 없어";
      notes.push(
        `${why} 온보드·자세 관측 시점이 궤도 시점으로 물러섰습니다 — `
        + "온보드는 원래 기체 안이라 물러선 것을 알아챌 단서가 없습니다.",
      );
    }
    notes.push(ATMOSPHERE_NOTES.model, ATMOSPHERE_NOTES.visibility);
    const sea = this.host.seaState();
    notes.push(
      `해상 상태: 풍속 ${sea.windSpeed.toFixed(1)} m/s · 유의파고 ${sea.waveHeight.toFixed(2)} m`
      + ` · 경사분산 σ² ${sea.slopeVariance.toFixed(4)} (윤슬 폭).`,
    );
    notes.push(WAVE_NOTES.displayOnly, WAVE_NOTES.model);
    notes.push(CLOUD_NOTES.model, CLOUD_NOTES.shadows);
    if (this.vehicle || this.launcher) notes.push(WEAR_NOTES.model);
    const scale = this.host.getRenderScale();
    if (scale < 1) {
      notes.push(
        `성능: 프레임이 늦어 렌더 해상도 배율을 ${scale}로 내렸습니다 — 빨라지면 되돌립니다.`,
      );
    }
    if (this.gameOn) {
      notes.push(
        "게임 모드 — 표시·계획 전용 아케이드 비행입니다. 실제 기체 동역학이 아니며, "
        + "검증은 웨이포인트를 보낸 뒤 시뮬레이션 탭(실제 엔진)에서 합니다.",
        "조작: ←→ 선회 · ↑↓ 승강 · Shift 가속 · Ctrl 감속 · Space 현재 위치 웨이포인트 · "
        + `지형 클릭 = 그 지점 지면 +${GAME_CLICK_CLEARANCE} m 웨이포인트 · 휠 = 시점 거리.`,
        "로우폴리 지형·수목·가옥은 같은 실측 지형 팩을 성긴 면과 게임 색으로 다시 그린 "
        + "표시용 장식입니다 — 실제 식생·건물이 아닙니다.",
      );
      if (this.terrain == null) {
        // 사유를 가른다 — 팩 자체가 없는 것과, 팩은 있는데 얹을 결과(원점 합의)가
        // 없는 것은 다른 사실이다. 뭉뚱그리면 팩이 멀쩡한데 "없다"고 단정하게 된다.
        notes.push(this.pack == null
          ? "지형 팩이 없어 기준면 위를 납니다 — 지면 표고는 활주로 표고로 봅니다."
          : "지형 팩은 있지만 아직 결과에 얹지 못해(결과 없음 또는 원점 불일치) "
            + "기준면 위를 납니다 — 지면 표고는 활주로 표고로 봅니다.");
      }
    }
    if (this.style === "cinematic") {
      notes.push(
        "시네마틱 모드 — 궤적 오버레이를 숨기고 블룸·비네트·그레이딩을 겁니다. "
        + "판독 값과 이 캡션은 계속 표시합니다.",
      );
    }
    notes.push(
      "해면은 지형 격자 밖(외곽 티어 30 km 밖)까지 이어 그립니다 — "
      + "그 부분은 실측 지리가 아니라 이어 붙인 평면입니다.",
    );
    this.cb.onNotes(notes);
  }

  // ---------------------------------------------------------------- 조작
  /** Engineering ↔ Cinematic은 표시 구성만 바뀐다(결과·커서·카메라 그대로).
   *  Game은 그 위에 기체의 정본이 바뀐다 — 재생 표본이 아니라 아케이드 상태다. */
  setViewStyle(style: ViewStyle): void {
    if (style === this.style) return;
    const wasGame = this.gameOn;
    this.style = style;
    // 가시성 먼저 — exitGame의 마지막 한 프레임이 게임 그룹을 그리지 않게.
    this.host.setViewStyle(style);
    if (this.gameOn) this.enterGame();
    else if (wasGame) this.exitGame();
    // 모드 전환의 동기 비용(컴포저 재구성·게임 자산 굽기 수십~수백 ms)이 다음 프레임
    // dtWall에 통째로 들어가면 autoQuality가 일회성 정지를 지속 부하로 오독해 진입마다
    // 해상도를 내리고 거짓 캡션을 낸다(리뷰 확정) — 기준 시각을 지금으로 되돌린다.
    this.lastFrameMs = performance.now();
    this.dirty = true;
    this.emitNotes();
  }

  // ---------------------------------------------------------------- 게임 모드
  private enterGame(): void {
    if (this.playing) {
      this.playing = false;
      this.cb.onPlaying(false);
    }
    this.buildGameWorld();
    const elev = this.groundElevationAt([0, 0, 0])
      ?? num(this.body?.meta?.runway?.elevation) ?? 0;
    this.arcade = spawnArcade(num(this.body?.meta?.runway?.heading), elev);
    // 재생이 마지막으로 적용한 타각이 남으면 게임 내내 그 타각으로 동결 표시된다
    // (리뷰 확정 — "마지막 값 유지"는 재생 결측 규약이지 게임 규약이 아니다). 게임
    // 상태는 타면 정보를 갖지 않으므로 중립이 정직하다.
    if (this.vehicle) {
      applySurfaces(this.vehicle, surfacePose(0, 0, 0, this.body?.meta?.limits ?? {}));
    }
    this.gameEye = null;
    this.gameInput = { turn: 0, pitch: 0, throttle: 0 };
    this.syncMarkers();
    this.emitGameWps();
  }

  /** 이탈 — 표지를 재생 것으로 되돌린다. 재생 결과가 없으면 기체를 숨기고 중립 궤도
   *  한 프레임을 그린다(마지막 게임 프레임이 정지화면으로 남지 않게 — draw()는
   *  body 없이는 아무것도 안 그린다). */
  private exitGame(): void {
    this.arcade = null;
    this.gameInput = { turn: 0, pitch: 0, throttle: 0 };
    this.syncMarkers();
    if (this.body == null) {
      // draw()는 body 없이는 emitReadout에 닿지 않는다 — 여기서 지우지 않으면 화면은
      // 빈 중립 장면인데 판독 줄만 마지막 게임 값을 영영 말한다(리뷰 확정).
      this.cb.onReadout(null);
      if (this.vehicle) hideVehicle(this.vehicle);
      const groundD = -(this.groundElevationAt(null) ?? 0);
      this.host.render(orbitCamera({
        pivot: [0, 0, groundD], az: this.orbit.az, el: this.orbit.el, dist: this.dist, groundD,
      }), this.lastSeaTime);
    }
  }

  /** 게임 자산(로우폴리 지형·소품) — 같은 팩이면 다시 굽지 않는다(진입 비용은 첫
   *  한 번). 팩이 없으면 비운다 — 기준면 위를 나는 것도 계획에는 쓸 수 있고,
   *  캡션이 사유를 말한다. */
  private buildGameWorld(): void {
    if (this.gameBuiltFor === this.terrain) return;
    this.gameBuiltFor = this.terrain;
    const pack = this.terrain;
    if (pack == null) {
      this.host.setGameTerrain([], 800);
      this.host.setProps(null);
      return;
    }
    const relief = reliefOf(pack.tiers);
    // 낱면이 GAME_FACET_M쯤 되게 촘촘한 티어를 스트라이드로 성기게 한다 — 로우폴리는
    // 해상도를 버리는 것이 곧 문법이고, 형상 원본은 같은 팩이다(캡션 몫).
    const built = buildTerrain(pack, (t) => Math.max(1, Math.round(GAME_FACET_M / t.step)));
    this.host.setGameTerrain(built.meshes, relief);
    const core = [...pack.tiers].sort((a, b) => a.step - b.step)[0];
    if (core == null) {
      this.host.setProps(null);
      return;
    }
    const sample = (n: number, e: number): number | null => {
      for (const tier of pack.tiers) {
        const z = elevationAt(tier, n, e);
        if (z !== null) return z;
      }
      return null;
    };
    this.host.setProps(buildPropsGroup(placeProps(sample, tierRect(core), relief)).group);
  }

  /** 게임 입력 축 — WorldTab 키보드가 민다. 게임이 아니면 step이 읽지 않는다. */
  setGameInput(input: ArcadeInput): void {
    this.gameInput = input;
  }

  /** 현재 기체 위치를 웨이포인트로 — [n, e, 고도]를 미터 정수로 찍는다(표에서 읽는 수). */
  dropGameWaypoint(): void {
    if (!this.gameOn || this.arcade == null) return;
    const [n, e, d] = this.arcade.pos;
    this.pushGameWp(Math.round(n), Math.round(e), Math.round(-d));
  }

  /** 지형 클릭 웨이포인트 — 교점의 지면 표고 + 여유고도. 하늘을 클릭하면 지면 교점이
   *  없다는 사실 그대로 아무것도 안 찍는다(0으로 메우지 않는다). */
  addGameWaypointAt(ndcX: number, ndcY: number): void {
    if (!this.gameOn) return;
    const planeY = this.groundElevationAt(null) ?? 0;
    const hit = this.host.raycastGround(ndcX, ndcY, planeY);
    if (hit == null) return;
    // 고도는 성긴 게임 메시의 교점이 아니라 **원본 격자**에서 다시 잰다 — 90 m 낱면의
    // 중간값이 아니라 그 지점의 표고 위에 여유를 얹어야 계획 값으로 읽힌다.
    const ground = this.groundElevationAt(hit) ?? -hit[2];
    this.pushGameWp(
      Math.round(hit[0]), Math.round(hit[1]), Math.round(ground + GAME_CLICK_CLEARANCE));
  }

  removeGameWaypoint(i: number): void {
    if (!Number.isInteger(i) || i < 0 || i >= this.gameWps.length) return;
    this.gameWps.splice(i, 1);
    this.afterWpChange();
  }

  clearGameWaypoints(): void {
    if (this.gameWps.length === 0) return;
    this.gameWps = [];
    this.afterWpChange();
  }

  /** 시뮬 탭으로 보낼 사본 — 내부 배열을 그대로 내주지 않는다(밖의 수정이 표지와 갈린다). */
  getGameWaypoints(): [number, number, number][] {
    return this.gameWps.map((w) => [w[0], w[1], w[2]]);
  }

  private pushGameWp(n: number, e: number, h: number): void {
    this.gameWps.push([n, e, h]);
    this.afterWpChange();
  }

  private afterWpChange(): void {
    this.syncMarkers();
    this.emitGameWps();
    this.dirty = true;
  }

  private emitGameWps(): void {
    this.cb.onGameWps(this.getGameWaypoints());
  }

  /** 표지의 정본 전환 — 게임 중엔 찍는 중인 웨이포인트, 아니면 재생 결과의 표지. */
  private syncMarkers(): void {
    this.host.setMarkers(this.gameOn
      ? this.gameWps.map(([n, e, h]) => ({
        ne: [n, e, -h] as const, kind: "waypoint" as const, radius: GAME_ACCEPT_RADIUS,
      }))
      : this.replayMarks);
  }

  setCamMode(mode: CamMode): void {
    // 게임 시점은 체이스 고정 — 받아 두면 버튼만 바뀌고 화면은 그대로인 상태(onMode
    // 주석이 결함이라 명시한 그것)가 되고, 이탈 시 저장된 모드로 예고 없이 튄다.
    // 지금 모드를 되쏘아 UI를 되돌린다(조용한 무시 금지).
    if (this.gameOn) {
      this.cb.onMode(this.mode);
      return;
    }
    if (!CAM_MODES.includes(mode) || mode === this.mode) return;
    this.mode = mode;
    this.chaseEye = null;
    this.dirty = true;
    this.cb.onMode(mode);
    this.emitNotes(); // 배율이 바뀐다 — 캡션이 옛 값을 말하지 않게
  }

  rotate(dxPx: number, dyPx: number): void {
    // 게임 시점은 진행 방향이 정본 — 드래그 회전이 없다. 클릭(웨이포인트)과 드래그를
    // 가르는 일은 WorldTab이 하고, 여기는 어느 쪽이든 시점을 안 바꾼다.
    if (this.gameOn) return;
    // **자세 관측에서는 빠져나오지 않는다** — 그 시점도 az·el을 쓰므로 끌면 그 자리에서
    // 돈다. 무조건 궤도로 바꾸면 `attitudeCamera`에 넘기는 각을 영영 못 돌린다.
    // (`views/world.js:228`과 같은 조건.)
    if (this.mode !== "orbit" && this.mode !== "attitude") {
      this.mode = "orbit";
      this.cb.onMode("orbit");
      this.emitNotes(); // 물러섬 사유가 캡션에 실린다 — 옛 문장이 남지 않게
    }
    this.orbit = rotateBy(this.orbit, dxPx, dyPx);
    this.dirty = true;
  }

  zoom(deltaY: number): void {
    // 휠은 지금 시점의 거리를 움직인다 — 추적·자세는 근접 거리, 궤도는 장면 거리.
    // 종전 1.1(휠 한 눈금 10%)이 너무 예민하다는 사용자 제기 — 2D 웨이포인트 지도와
    // 같은 방식(지수를 N으로 나눠 "N배 둔하게")으로 감도 1/5: 1.1^(1/5) ≈ 1.9%/눈금.
    const WHEEL_DULL = 5;
    const step = Math.pow(1.1, 1 / WHEEL_DULL);
    const k = deltaY > 0 ? step : 1 / step;
    if (this.gameOn) {
      this.gameDist = Math.min(Math.max(this.gameDist * k, 8), 120);
      this.dirty = true;
      return;
    }
    if (this.mode === "chase" || this.mode === "attitude") {
      this.closeDist = Math.min(Math.max(this.closeDist * k, 5), 200);
    } else {
      this.dist = Math.min(Math.max(this.dist * k, 8), 20000);
    }
    this.dirty = true;
  }

  setPlaying(playing: boolean): void {
    // **여기서도 막고, 막았다는 것을 알린다.**
    //
    // 못 돌 결과에서 `playing`이 참인 채로 남으면 `step()`의 조기 반환이 영영 안 걸려
    // 60 Hz가 헛돈다 — 전진 블록이 `isPlayable`로 막혀 있어 `atEnd`가 **평가되지도**
    // 않기 때문이다(`atEnd(0, 1)` 자체는 참이다. 멈추는 경로에 안 닿을 뿐이다).
    // 조용히 반환하면 UI의 `playing`이 참으로 남아 버튼이 "일시정지"인 채 굳고,
    // UI 쪽 폴링 rAF가 대신 헛돈다 — 막으려던 낭비를 한 층 옮길 뿐이다.
    if (playing && !this.playable) {
      this.cb.onPlaying(false);
      return;
    }
    // 게임 모드에서 재생은 성립하지 않는다 — 기체의 정본이 아케이드 상태다.
    // 조용히 무시하지 않고 꺼진 상태를 알린다(위와 같은 사유).
    if (playing && this.gameOn) {
      this.cb.onPlaying(false);
      return;
    }
    if (playing && this.body && atEnd(this.idx, this.n)) this.idx = 0;
    this.playing = playing;
    this.fromIdx = this.idx;
    this.fromWall = performance.now();
    this.cb.onPlaying(playing);
    this.dirty = true;
  }

  setSpeed(speed: number): void {
    this.fromIdx = this.idx;
    this.fromWall = performance.now();
    this.speed = speed;
  }

  setCursor(idx: number): void {
    this.idx = Math.min(Math.max(Math.round(idx), 0), Math.max(this.n - 1, 0));
    this.fromIdx = this.idx;
    this.fromWall = performance.now();
    this.dirty = true;
  }

  get cursor(): number { return this.idx; }
  get sampleCount(): number { return this.n; }
  /** 재생할 수 있는가 — 표본이 둘 이상이고 간격이 양수인가(`playcursor.isPlayable`).
   *  아니면 재생 버튼을 막는다. 사유는 `setPlaying`에 적어 두었다. */
  get playable(): boolean { return this.body != null && isPlayable(this.body.t); }
  /** 지금 화면이 설명하는 결과 id — 실패한 로드 뒤에 선택칸과 화면이 갈렸는지 판정한다. */
  get shownResultId(): string | null { return this.shownId; }

  resize(w: number, h: number, dpr: number): void {
    this.host.resize(w, h, dpr);
    this.dirty = true;
  }

  setEnvironment(env: {
    sunEl: number; sunAz: number; visibility: number; exposure: number;
    windSpeed: number; windDir: number; cloudCover: number;
  }): void {
    this.host.setEnvironment({
      sunAzEl: [env.sunAz, env.sunEl],
      visibility: env.visibility,
      exposure: env.exposure,
      sea: { windSpeed: env.windSpeed, windDir: env.windDir },
      cloudCover: env.cloudCover,
    });
    this.dirty = true;
    // 해상 상태가 캡션에 실린다 — 바꿀 때마다 다시 낸다.
    this.emitNotes();
  }

  // ---------------------------------------------------------------- 루프
  start(): void {
    const tick = () => {
      if (this.disposed) return;
      this.raf = requestAnimationFrame(tick);
      this.step();
    };
    this.raf = requestAnimationFrame(tick);
  }

  private step(): void {
    const now = performance.now();
    const dtWall = Math.min((now - this.lastFrameMs) / 1000, 0.25);
    this.lastFrameMs = now;
    this.autoQuality(dtWall);

    if (this.gameOn && this.arcade) {
      const ground = this.groundElevationAt(this.arcade.pos);
      this.arcade = stepArcade(this.arcade, this.gameInput, dtWall, ground);
      // 게임에는 시뮬 시각이 없다 — 해면 위상은 벽시계로 흐른다. 매 프레임 그리므로
      // 온디맨드 루프(dirty)의 전제와도 충돌하지 않는다.
      this.lastSeaTime += dtWall;
      this.drawGame(dtWall, ground);
      return;
    }

    if (this.playing && this.body && isPlayable(this.body.t)) {
      const next = indexAt(this.fromIdx, this.fromWall, now, this.speed, this.dt, this.n);
      if (next !== this.idx) { this.idx = next; this.dirty = true; }
      if (atEnd(this.idx, this.n)) { this.playing = false; this.cb.onPlaying(false); }
    }
    if (!this.dirty && !this.playing) return;
    this.dirty = false;
    this.draw(dtWall);
  }

  /** 게임 프레임 — 아케이드 상태로 기체·카메라를 세운다. 재생 경로(draw)와 갈라
   *  둔다: 저쪽은 "결측을 그리지 않는다"가 규율이고 이쪽은 상태가 항상 성하다. */
  private drawGame(dtWall: number, groundElev: number | null): void {
    const a = this.arcade;
    if (a == null) return;
    const q = eulerToQuat(a.phi, a.theta, a.psi);
    const axes = q ? bodyAxesNed(q) : null;
    if (this.vehicle) {
      if (axes) setVehiclePose(this.vehicle, a.pos, axes, MODEL_SCALE);
      // 프로펠러 — 스로틀 축(−1‥1)을 0‥1로 옮겨 돌린다. 표시 값이다.
      const thr = 0.5 + 0.5 * this.gameInput.throttle;
      spinPropeller(this.vehicle, propellerRate(thr, thr), dtWall);
    }
    const vel: Vec3 = [
      a.V * Math.cos(a.theta) * Math.cos(a.psi),
      a.V * Math.cos(a.theta) * Math.sin(a.psi),
      -a.V * Math.sin(a.theta),
    ];
    const groundD = -(groundElev ?? num(this.body?.meta?.runway?.elevation) ?? 0);
    const cam = chaseCamera({
      pos: a.pos, vel, q, prevEye: this.gameEye, dtWall, groundD,
      dist: this.gameDist, height: this.gameDist * 0.35,
    });
    this.gameEye = cam.eye;
    this.host.render(cam, this.lastSeaTime);
    const alt = -a.pos[2];
    this.cb.onReadout({
      t: null, mode: "게임", alt,
      aboveGround: groundElev !== null ? alt - groundElev : null,
      speed: a.V, phi: a.phi, theta: a.theta,
    });
    this.emitStats(performance.now());
  }

  private draw(dtWall: number): void {
    const body = this.body;
    if (body == null) return;
    const i = this.idx;
    const sample = sampleAt(body.signals, i);
    const att = attitudeAt(body.signals, i);
    if (sample) this.lastPos = sample;
    if (att) this.lastAtt = att;
    // **카메라는 마지막으로 성했던 자리·자세에 머문다.** 기체를 안 그리는 것만으로는
    // 부족하다 — 쿼터니언이 카메라로 흘러가 온보드 시점이 없는 수평·정북을 본다.
    const pos = sample ?? this.lastPos;
    const attUse = att ?? this.lastAtt;
    const q: Quat | null = attUse ? eulerToQuat(attUse[0], attUse[1], attUse[2]) : null;
    const axes = sample && att && q ? bodyAxesNed(q) : null;

    // 기체 — 이 프레임의 위치나 자세를 모르면 **그리지 않는다**(유지한 값으로 그리지 않는다).
    if (this.vehicle) {
      if (sample && axes) setVehiclePose(this.vehicle, sample, axes, MODEL_SCALE);
      else hideVehicle(this.vehicle);
      // 한계는 결과가 들고 오는 것을 그대로 쓴다 — 없으면 자르지 않는다(§ surfaces.ts).
      applySurfaces(this.vehicle, surfacePose(
        body.signals.de?.[i], body.signals.da?.[i], body.signals.dr?.[i],
        body.meta?.limits ?? {},
      ));
      spinPropeller(this.vehicle,
        propellerRate(body.signals.thr_l?.[i], body.signals.thr_r?.[i]), dtWall);
    }

    const groundElev = this.groundElevationAt(pos);
    const cam = this.cameraFor(pos, q, dtWall, groundElev);
    // **해면 위상은 시뮬 시각으로 돈다.** 벽시계로 돌리면 멈춘 화면에서도 파도가 움직여야
    // 하고, 그러면 `dirty` 기반 온디맨드 루프가 매 프레임 다시 그려야 한다.
    // 시각을 모르는 표본이면 마지막 값을 쓴다 — 0으로 되돌리면 바다가 튄다.
    const t = body.t[i];
    if (typeof t === "number" && Number.isFinite(t)) this.lastSeaTime = t;
    this.host.render(cam, this.lastSeaTime);
    this.emitReadout(i, groundElev);
    this.emitStats(performance.now());
    this.prevIdx = i;
  }

  /** 기체 발밑의 지면 표고 [m] — 지형이 있으면 격자에서, 없으면 활주로 표고에서.
   *
   * 네 갈래다.
   * 1. **얹은 지형이 이 자리를 덮으면** 그 표고. (얹지 않은 지형은 안 본다 — 위 `terrain` 주석)
   * 2. 얹었는데 격자 밖이면 **null** — 활주로 표고로 물러서면 "지면 위 높이"라는 이름으로
   *    다른 양을 내놓게 된다.
   * 3. 지형을 안 얹었으면 화면이 깐 기준면과 **같은 값**을 낸다. 여기서 null을 내면 판은
   *    0 m에 깔려 있는데 판독부는 "—"라고 답해 화면이 자기 말과 어긋난다.
   * 4. 지형은 얹었는데 **위치를 모르면**(성한 표본을 아직 못 봄) 3번으로 떨어진다 —
   *    즉 지형이 그려져 있는데 활주로 표고를 쓴다. 잴 자리 자체가 없으니 다른 수가 없고,
   *    `views/world.js`도 같은 선택을 한다. 위치가 오는 순간 1·2번으로 돌아간다.
   *
   * `views/world.js`의 `groundElevationAt` + `state.terrain` 게이트와 같은 규약이다. */
  private groundElevationAt(pos: Vec3 | null): number | null {
    if (this.terrain && pos) {
      for (const tier of this.terrain.tiers) {
        const z = elevationAt(tier, pos[0], pos[1]);
        if (z !== null) return z;
      }
      return null; // 지형은 있는데 이 자리를 안 덮는다
    }
    return num(this.body?.meta?.runway?.elevation) ?? 0;
  }

  private cameraFor(
    pos: Vec3 | null, q: Quat | null, dtWall: number, groundElev: number | null,
  ): CameraPose {
    const groundD = -(groundElev ?? num(this.body?.meta?.runway?.elevation) ?? 0);
    // 성한 표본을 **한 번도** 못 봤다 — 기준면 원점을 멀찍이 내려다본다(지어낼 위치가 없다).
    // 여기서 렌더를 건너뛰면 검은 캔버스만 남고, 캡션은 보이지도 않는 장면을 설명한다.
    if (pos == null) {
      // 위치가 없으면 어떤 시점도 세울 수 없다 — 온보드를 골라 뒀어도 궤도로 물러선다.
      // 그 사실을 여기서도 알린다(아래 `fellBack`은 자세만 보므로 이 경로를 못 덮는다).
      this.setFellBack(this.mode === "onboard" || this.mode === "attitude" ? "pos" : null);
      return orbitCamera({
        pivot: [0, 0, groundD], az: this.orbit.az, el: this.orbit.el, dist: this.dist, groundD,
      });
    }
    const vel = velocityAt(this.body!.t, this.body!.signals, this.idx);

    // 자세를 모르면 **자세에 기대는 시점을 쓸 수 없다.** 단위 쿼터니언으로 물러서면
    // 온보드가 있지도 않은 수평·정북을 보여 주는데, 온보드는 원래 기체 안이라
    // 알아챌 단서가 없다. 궤도로 물러서고 **캡션이 사유를 말한다.**
    const fellBack = q == null && (this.mode === "onboard" || this.mode === "attitude");
    this.setFellBack(fellBack ? "att" : null);
    const mode = fellBack ? "orbit" : this.mode;

    if (mode === "orbit") {
      return orbitCamera({ pivot: pos, az: this.orbit.az, el: this.orbit.el, dist: this.dist, groundD });
    }
    if (mode === "onboard" && q) return onboardCamera({ pos, q });
    if (mode === "attitude") {
      return attitudeCamera({ pos, az: this.orbit.az, el: this.orbit.el, dist: this.closeDist * 0.6, groundD });
    }
    if (shouldResetSmoothing(this.prevIdx, this.idx)) this.chaseEye = null;
    // 실물 1배라 카메라가 붙는다 — 스팬 2.5 m 기체에 16 m 뒤·5 m 위가 고전적 추적 구도다.
    const cam = chaseCamera({
      pos, vel, q, prevEye: this.chaseEye, dtWall, groundD,
      dist: this.closeDist, height: this.closeDist * 0.3,
    });
    this.chaseEye = cam.eye;
    return cam;
  }

  /** 궤도로 물러선 **사유** — null이면 안 물러섰다. 사유를 안 들고 있으면 캡션이
   *  "자세가 없어"라고 단정하는데, 위치가 없어 물러선 경우에는 그것이 틀린 말이 된다. */
  private fellBack: "att" | "pos" | null = null;

  private setFellBack(v: "att" | "pos" | null): void {
    if (v === this.fellBack) return;
    this.fellBack = v;
    this.emitNotes();
  }

  /** 품질 자동 강등 — 렌더 해상도 배율 사다리 1 → 0.85 → 0.7 → 0.55 (계획 §리스크 7).
   *
   * 신호는 **재생 중의 프레임 간격**이다. CPU 제출 ms는 GPU가 막힌 것을 못 보고
   * (바다·구름·대기가 다 픽셀 셰이더라 병목은 GPU 쪽이다), 재생이 아닐 때는 온디맨드
   * 루프라 간격이 뜻이 없다. 250 ms를 넘는 표본은 버린다 — 그건 부하가 아니라 브라우저
   * 스로틀(가려진 탭은 rAF가 1 Hz다)이고, 그걸 부하로 읽으면 탭을 가렸다 돌아올 때마다
   * 화질이 떨어져 있다.
   *
   * 내리기는 빠르게(EMA 24 ms 초과가 이어지면), 올리기는 천천히(11 ms 미만이 오래) —
   * 경계에서 오르내리면 해상도가 숨쉬는 것이 눈에 띈다. */
  private autoQuality(dtWall: number): void {
    // 재생과 게임 — 둘 다 매 프레임 그리는 구간이라 프레임 간격이 부하를 말한다.
    // 스로틀 표본 폐기는 >=다: dtWall이 step()에서 정확히 0.25로 클램프되므로
    // 초과(>)는 영영 참이 안 되는 죽은 가드였다(리뷰 확정 — 머리말의 "버린다"가 의도).
    if ((!this.playing && !this.gameOn) || dtWall >= 0.25) return;
    this.frameEma = this.frameEma === 0 ? dtWall : this.frameEma * 0.9 + dtWall * 0.1;
    if (this.qualityHold > 0) { this.qualityHold--; return; }
    const LADDER = [1, 0.85, 0.7, 0.55];
    const cur = LADDER.indexOf(this.host.getRenderScale());
    if (this.frameEma > 0.024 && cur >= 0 && cur < LADDER.length - 1) {
      this.host.setRenderScale(LADDER[cur + 1]!);
      this.qualityHold = 120;
      this.dirty = true;
      this.emitNotes();
    } else if (this.frameEma < 0.011 && cur > 0) {
      this.upgradeStreak++;
      if (this.upgradeStreak > 300) {
        this.host.setRenderScale(LADDER[cur - 1]!);
        this.upgradeStreak = 0;
        this.qualityHold = 120;
        this.dirty = true;
        this.emitNotes();
      }
      return;
    }
    this.upgradeStreak = 0;
  }

  /** **시간 간격으로** 올린다 — 값 비교로는 못 줄인다.
   *
   * 처음엔 "바뀔 때만"으로 두었는데, `ms`를 0.1 ms 단위로 비교하니 CPU 제출 시간이 그보다
   * 훨씬 크게 흔들려 사실상 매 프레임 통과했다. 그리고 그때 적은 사유("매 프레임 setState하면
   * 프레임을 먹는다")도 틀렸다 — `emitReadout`이 이미 매 프레임 새 객체를 올리고 React 18이
   * 둘을 한 렌더로 묶는다. 줄여야 하는 진짜 이유는 **읽는 사람**이다: 초당 60번 바뀌는
   * 숫자는 못 읽는다. */
  private emitStats(now: number): void {
    if (now - this.lastStatsAt < STATS_INTERVAL_MS) return;
    this.lastStatsAt = now;
    const s = this.host.getStats();
    this.cb.onStats({
      drawCalls: s.drawCalls, triangles: s.triangles,
      ms: Math.round(s.ms * 10) / 10, depthBits: this.depthBits,
    });
  }

  private style: ViewStyle = "engineering";
  private frameEma = 0;
  private qualityHold = 0;
  private upgradeStreak = 0;
  private lastSeaTime = 0;
  private lastStatsAt = 0;
  private readonly depthBits: number;

  private emitReadout(i: number, groundElev: number | null): void {
    const s = this.body?.signals;
    const h = num(s?.h?.[i]);
    this.cb.onReadout({
      t: num(this.body?.t[i]),
      mode: s?.mode?.[i] ?? null,
      alt: h,
      // **지형이 있는데 활주로 표고를 빼면** 400 m 능선 위 450 m에서 "지면 +450"이 나온다.
      aboveGround: h !== null && groundElev !== null ? h - groundElev : null,
      speed: num(s?.V?.[i]),
      phi: num(s?.phi?.[i]),
      theta: num(s?.theta?.[i]),
    });
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    cancelAnimationFrame(this.raf);
    this.vehicle?.dispose();
    this.launcher?.dispose();
    this.host.dispose();
  }
}

/** 컨트롤러 생성 — WebGL2를 못 만들면 **던지지 않고 사유를 낸다**. */
export function createController(
  canvas: HTMLCanvasElement, cb: ControllerCallbacks,
): { controller: SceneController; reason: null } | { controller: null; reason: string } {
  const made = createSceneHost(canvas);
  if (made.host == null) return { controller: null, reason: made.reason };
  return { controller: new SceneController(made.host, cb), reason: null };
}

export { CAM_MODES, FOV_Y };
export type { CamMode };
