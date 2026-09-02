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
import { elevationAt, parseTerrainPack, type TerrainPack } from "../lib/terrainpack.ts";
import { strideFor } from "../lib/replay.ts";
import { launcherCaptionNotes, launcherPose } from "../core/launcher.ts";
import { SURFACE_NOTES, propellerRate, surfacePose } from "../core/surfaces.ts";
import type { Replay } from "../core/types.ts";
import {
  fetchReplay, fetchTerrainPack, fetchWorldManifest, listSimResults, modelUrl,
  type SimResultRow, type WorldManifest,
} from "../data/api.ts";
import { SceneHost, createSceneHost } from "./SceneHost.ts";
import { buildTerrain } from "./terrain.ts";
import {
  LAUNCHER_NODES, VEHICLE_NODES, applySurfaces, hideVehicle, loadModel,
  setVehiclePose, showLauncher, spinPropeller, type LoadedModel,
} from "./models.ts";

/** 기체는 스팬 2.5 m다 — 300 m 밖에서 한 픽셀이라 시점마다 확대해 그린다.
 *  **표시 선택이고 캡션이 밝힌다.** */
const MODEL_SCALE: Record<CamMode, number> = {
  chase: 8, orbit: 8, onboard: 1, attitude: 3,
};

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

export interface ControllerCallbacks {
  onNotes(notes: string[]): void;
  /** **시점의 정본은 컨트롤러다.** 끌어서 궤도로 넘어가는 조건이 여기 있으므로,
   *  UI가 스스로 짐작하면 자세 관측에서 끌었을 때 버튼만 "자유 궤도"로 바뀌고
   *  카메라는 그대로인 상태가 된다(그리고 배율 캡션이 버튼과 어긋난다). */
  onMode(mode: CamMode): void;
  onReadout(r: Readout): void;
  onResults(rows: SimResultRow[], chosen: string | null): void;
  onStatus(text: string): void;
  onPlaying(playing: boolean): void;
}

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

  private mode: CamMode = "chase";
  private orbit = { az: 2.4, el: 0.45 };
  private dist = 400;
  private playing = false;
  private speed = 5;
  private fromIdx = 0;
  private fromWall = 0;

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
    if (this.terrain) {
      const built = buildTerrain(this.terrain);
      this.host.setTerrain(built.meshes);
      notes.push(...built.notes);
    } else {
      this.host.setTerrain([]);
      if (this.pack && agree.reason) notes.push(agree.reason);
    }

    // --- 궤적 ---
    const { points, breaks } = trackPoints(body.signals, this.n);
    this.host.setPaths([{ points, color: 0x32d3ff, breaks }]);
    this.missingPos = breaks.length;
    this.missingAtt = 0;
    for (let i = 0; i < this.n; i++) if (attitudeAt(body.signals, i) === null) this.missingAtt++;
    if (this.missingPos > 0) {
      notes.push(`위치 결측 ${this.missingPos}/${this.n} 표본 — 그 구간은 선을 끊었습니다.`);
    }
    if (this.missingAtt > 0) {
      notes.push(`자세 결측 ${this.missingAtt}/${this.n} 표본 — 그 구간은 기체를 그리지 않습니다.`);
    }

    // --- 기체 형상 --- (확대 배율은 시점마다 다르므로 여기서 말하지 않는다 — emitNotes)
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
   * 배율은 시점마다 다른데(추적 8배·온보드 1배) 결과를 읽을 때 한 번만 말하면, 시점을
   * 바꾼 뒤 캡션이 옛 배율을 말한다. `views/world.js`가 같은 자리에서 겪고
   * `captionStale` 플래그로 고쳐 둔 것을 여기서는 시점이 바뀔 때 다시 만드는 것으로 푼다. */
  private emitNotes(): void {
    const notes = [...this.resultNotes];
    if (this.vehicle) {
      notes.push(`기체를 ${MODEL_SCALE[this.mode]}배로 확대해 그립니다 (실제 스팬 2.5 m).`);
    }
    if (this.fellBack !== null) {
      const why = this.fellBack === "att" ? "자세가 없어" : "위치가 없어";
      notes.push(
        `${why} 온보드·자세 관측 시점이 궤도 시점으로 물러섰습니다 — `
        + "온보드는 원래 기체 안이라 물러선 것을 알아챌 단서가 없습니다.",
      );
    }
    this.cb.onNotes(notes);
  }

  // ---------------------------------------------------------------- 조작
  setCamMode(mode: CamMode): void {
    if (!CAM_MODES.includes(mode) || mode === this.mode) return;
    this.mode = mode;
    this.chaseEye = null;
    this.dirty = true;
    this.cb.onMode(mode);
    this.emitNotes(); // 배율이 바뀐다 — 캡션이 옛 값을 말하지 않게
  }

  rotate(dxPx: number, dyPx: number): void {
    // **자세 관측에서는 빠져나오지 않는다** — 그 시점도 az·el을 쓰므로 끌면 그 자리에서
    // 돈다. 무조건 궤도로 바꾸면 `attitudeCamera`에 넘기는 각을 영영 못 돌린다.
    // (`views/world.js:228`과 같은 조건.)
    if (this.mode !== "orbit" && this.mode !== "attitude") {
      this.mode = "orbit";
      this.cb.onMode("orbit");
      this.emitNotes(); // 배율이 바뀐다 — 캡션이 옛 값을 말하지 않게
    }
    this.orbit = rotateBy(this.orbit, dxPx, dyPx);
    this.dirty = true;
  }

  zoom(deltaY: number): void {
    this.dist = Math.min(Math.max(this.dist * (deltaY > 0 ? 1.1 : 1 / 1.1), 8), 20000);
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

  setEnvironment(sunEl: number, sunAz: number, visibility: number, exposure: number): void {
    this.host.setEnvironment({ sunAzEl: [sunAz, sunEl], visibility, exposure });
    this.dirty = true;
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

    if (this.playing && this.body && isPlayable(this.body.t)) {
      const next = indexAt(this.fromIdx, this.fromWall, now, this.speed, this.dt, this.n);
      if (next !== this.idx) { this.idx = next; this.dirty = true; }
      if (atEnd(this.idx, this.n)) { this.playing = false; this.cb.onPlaying(false); }
    }
    if (!this.dirty && !this.playing) return;
    this.dirty = false;
    this.draw(dtWall);
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
      if (sample && axes) setVehiclePose(this.vehicle, sample, axes, MODEL_SCALE[this.mode]);
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
    this.host.render(cam);
    this.emitReadout(i, groundElev);
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
      return attitudeCamera({ pos, az: this.orbit.az, el: this.orbit.el, dist: Math.min(this.dist, 40), groundD });
    }
    if (shouldResetSmoothing(this.prevIdx, this.idx)) this.chaseEye = null;
    const cam = chaseCamera({
      pos, vel, q, prevEye: this.chaseEye, dtWall, groundD,
      dist: Math.min(this.dist, 400), height: Math.min(this.dist, 400) * 0.28,
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
