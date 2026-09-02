/** 씬 소유자 — three 객체의 수명을 **명령형으로** 쥔다.
 *
 * ## 왜 React 훅이 아니라 클래스인가
 *
 * WebGL 컨텍스트는 브라우저당 8~16개뿐이라 새는 순간이 곧 화면이 죽는 순간이다.
 * 렌더러를 `useEffect` 안에서 만들면 의존성 배열이 하나 바뀔 때마다 다시 만들어지고,
 * StrictMode의 이중 실행에서는 두 개가 된다. 그래서 생성·파괴를 **대칭인 한 쌍**으로
 * 묶어 이 클래스에 두고, React는 이미 만들어진 것에 값을 밀어 넣기만 한다.
 *
 * `views/world.js`가 겪고 기록한 고아 rAF 루프도 같은 뿌리다 — 그 방어는 마운트 어댑터
 * (`views/world2.js`)의 세션 토큰이 맡는다.
 *
 * ## 이 층에 들어오는 값은 전부 NED·m·rad
 *
 * 축 변환은 `scene/axes.ts`의 `toWorld` 하나뿐이고, 그 정본은 `lib/world3d.js`다.
 */

import {
  ACESFilmicToneMapping, BufferAttribute, BufferGeometry, Color, DirectionalLight,
  FogExp2, Group, HemisphereLight, LineBasicMaterial, LineSegments, Mesh,
  MeshStandardMaterial, PerspectiveCamera, Scene, SRGBColorSpace, Vector3,
  WebGLRenderer,
} from "three";

import { toWorld } from "./axes.ts";
import { disposeTree } from "./dispose.ts";
import { createSky, type Sky } from "./sky.ts";

/** 원거리 지형까지 담으려면 near/far 비가 16,000:1이 된다 — 로그 깊이버퍼 없이는
 *  먼 곳에서 z-fighting이 난다. 후처리를 붙일 때 이 선택을 다시 본다(계획 §7). */
export const NEAR = 3;
export const FAR = 50000;
const SKY_RADIUS = FAR * 0.9;

/** 가시거리 V [m]에서 투과율이 2%가 되는 FogExp2 밀도. exp(−(dρ)²) = 0.02 → ρ = 1.978/V. */
export const fogDensityForVisibility = (v: number): number => 1.978 / Math.max(v, 1);

export interface CameraPose {
  eye: readonly number[];
  target: readonly number[];
  up: readonly number[];
  fovY: number;
}

export interface Environment {
  /** 태양 방위·고각 [rad] */ sunAzEl: readonly [number, number];
  /** 가시거리 [m] */ visibility: number;
  /** 톤매핑 노출 */ exposure: number;
}

/** NED 기하 한 덩어리 — `lib/terrainpack.js buildTerrainMesh`가 내는 모양. */
export interface NedMesh {
  positions: Float32Array;
  normals: Float32Array;
  indices: Uint16Array | Uint32Array;
}

export interface PathLine {
  /** NED 평탄 [n, e, d, …] */ points: Float32Array;
  color: number;
  /** 결측 표본의 인덱스 — 양 끝 중 하나라도 여기 있으면 그 구간은 안 그린다 */
  breaks?: number[];
}

export interface SceneStats {
  drawCalls: number;
  triangles: number;
  ms: number;
}

/** 고도 램프 — 표시용이다(영상지도 아님). 옛 어댑터에서 그대로 옮겨 왔다. */
const RAMP: [number, [number, number, number]][] = [
  [0, [0.76, 0.72, 0.58]], [60, [0.42, 0.53, 0.32]], [300, [0.28, 0.40, 0.24]],
  [700, [0.45, 0.42, 0.36]], [1200, [0.72, 0.72, 0.72]],
];

function hypsometric(elev: number, out: Float32Array, i: number): void {
  let lo = RAMP[0]!;
  let hi = RAMP[RAMP.length - 1]!;
  for (let k = 0; k + 1 < RAMP.length; k++) {
    if (elev <= RAMP[k + 1]![0]) { lo = RAMP[k]!; hi = RAMP[k + 1]!; break; }
  }
  const span = hi[0] - lo[0];
  const t = span > 0 ? Math.min(Math.max((elev - lo[0]) / span, 0), 1) : 0;
  for (let k = 0; k < 3; k++) out[i + k] = lo[1][k]! + (hi[1][k]! - lo[1][k]!) * t;
}

export class SceneHost {
  readonly scene = new Scene();
  readonly camera = new PerspectiveCamera(55, 1, NEAR, FAR);

  private readonly renderer: WebGLRenderer;
  private readonly sky: Sky;
  private readonly fog: FogExp2;
  private readonly sun: DirectionalLight;
  private readonly ambient: HemisphereLight;
  private readonly groups = {
    terrain: new Group(), paths: new Group(), models: new Group(),
  };

  private stats: SceneStats = { drawCalls: 0, triangles: 0, ms: 0 };
  private disposed = false;

  constructor(canvas: HTMLCanvasElement, context: WebGL2RenderingContext) {
    // 컨텍스트를 밖에서 만들어 넘긴다 — 같은 캔버스의 두 번째 getContext는 기존 것을
    // 돌려주면서 antialias 같은 속성을 무시하므로, 여기서 다시 만들면 조용히 꺼진다.
    this.renderer = new WebGLRenderer({ canvas, context, logarithmicDepthBuffer: true });
    this.renderer.outputColorSpace = SRGBColorSpace;
    this.renderer.toneMapping = ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 0.95;

    this.fog = new FogExp2(0x9fb4c7, fogDensityForVisibility(25000));
    this.scene.fog = this.fog;

    this.sun = new DirectionalLight(0xfff3e0, 2.4);
    this.ambient = new HemisphereLight(0xbcd6f0, 0x6b6f5a, 0.9);
    this.scene.add(this.sun, this.ambient);

    this.sky = createSky(SKY_RADIUS);
    this.scene.add(this.sky.mesh);
    for (const g of Object.values(this.groups)) this.scene.add(g);
  }

  resize(width: number, height: number, dpr: number): void {
    // dpr 3 기기에서 픽셀 수가 9배가 되는 것을 막는다.
    this.renderer.setPixelRatio(Math.min(dpr, 2));
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / Math.max(height, 1);
    this.camera.updateProjectionMatrix();
  }

  setEnvironment({ sunAzEl, visibility, exposure }: Environment): void {
    const [az, el] = sunAzEl;
    // 태양 방향을 NED로 만든 뒤 같은 toWorld를 태운다 — 하늘·직사광·안개가 한 값에서 나온다.
    const w = toWorld(Math.cos(el) * Math.cos(az), Math.cos(el) * Math.sin(az), -Math.sin(el));
    const horizon = this.sky.setSun(w, el);
    this.sun.position.set(w[0] * 1000, w[1] * 1000, w[2] * 1000);
    this.sun.intensity = 0.6 + 2.0 * Math.max(Math.sin(el), 0);
    // **안개색 = 지평선 하늘색** — 먼 지형이 회색 띠가 아니라 하늘로 녹아든다.
    this.fog.color.copy(horizon);
    this.fog.density = fogDensityForVisibility(visibility);
    this.renderer.toneMappingExposure = exposure;
  }

  /** 지형 — NED 기하를 그대로 받는다. 음영은 **진짜 법선에 조명이 닿아** 생긴다. */
  setTerrain(patches: readonly NedMesh[]): void {
    disposeTree(this.groups.terrain);
    for (const p of patches) {
      const n = p.positions.length;
      const pos = new Float32Array(n);
      const nrm = new Float32Array(n);
      const col = new Float32Array(n);
      for (let i = 0; i < n; i += 3) {
        // 결측 정점은 인덱스가 참조하지 않지만, NaN이 속성 배열에 남으면 바운딩
        // 스피어가 NaN이 되어 **메시 전체가 프러스텀 컬링으로 사라진다.**
        const d = Number.isFinite(p.positions[i + 2]!) ? p.positions[i + 2]! : 0;
        const w = toWorld(p.positions[i]!, p.positions[i + 1]!, d);
        pos[i] = w[0]; pos[i + 1] = w[1]; pos[i + 2] = w[2];
        const nw = toWorld(p.normals[i]!, p.normals[i + 1]!, p.normals[i + 2]!);
        nrm[i] = nw[0]; nrm[i + 1] = nw[1]; nrm[i + 2] = nw[2];
        hypsometric(-d, col, i);
      }
      const geo = new BufferGeometry();
      geo.setAttribute("position", new BufferAttribute(pos, 3));
      geo.setAttribute("normal", new BufferAttribute(nrm, 3));
      geo.setAttribute("color", new BufferAttribute(col, 3));
      geo.setIndex(new BufferAttribute(p.indices, 1));
      this.groups.terrain.add(new Mesh(geo, new MeshStandardMaterial({
        vertexColors: true, roughness: 0.95, metalness: 0,
      })));
    }
  }

  /** 궤적 — `breaks`의 양 끝 중 하나라도 결측이면 그 구간을 그리지 않는다.
   *
   * **NaN도 직접 막는다.** `breaks`는 선택 인자라, 그걸 안 주고 NaN이 섞인 점을 넘기면
   * 바운딩 스피어가 NaN이 되어 **선 전체가 프러스텀 컬링으로 사라진다** —
   * `setTerrain`이 같은 이유로 방어하는 그 함정이고, 원인이 전혀 안 보인다. */
  setPaths(lines: readonly PathLine[]): void {
    disposeTree(this.groups.paths);
    for (const ln of lines) {
      const count = ln.points.length / 3;
      if (count < 2) continue;
      const broken = new Set(ln.breaks ?? []);
      const ok = (k: number) => !broken.has(k)
        && Number.isFinite(ln.points[3 * k]!)
        && Number.isFinite(ln.points[3 * k + 1]!)
        && Number.isFinite(ln.points[3 * k + 2]!);
      const verts: number[] = [];
      for (let i = 0; i + 1 < count; i++) {
        if (!ok(i) || !ok(i + 1)) continue;
        for (const k of [i, i + 1]) {
          const w = toWorld(ln.points[3 * k]!, ln.points[3 * k + 1]!, ln.points[3 * k + 2]!);
          verts.push(w[0], w[1], w[2]);
        }
      }
      if (verts.length === 0) continue;
      const geo = new BufferGeometry();
      geo.setAttribute("position", new BufferAttribute(new Float32Array(verts), 3));
      this.groups.paths.add(new LineSegments(geo, new LineBasicMaterial({ color: ln.color })));
    }
  }

  /** 모델 그룹 — GLB 루트를 넣고 뺀다.
   *
   * **여기 넣은 것은 `dispose()`가 함께 파괴한다.** `models.ts`가 노드 손잡이를 들고
   * 있을 뿐 소유권은 이 그룹에 있다는 뜻이다. 장래에 GLTF를 모듈 수준으로 캐시하면
   * (탭을 오갈 때 다시 안 받으려고) 그 캐시가 내주는 지오메트리를 여기가 파괴하게 되어
   * 다음 SceneHost가 빈 메시를 받는다 — 캐시를 넣는다면 이 그룹에는 `clone()`을 넣어야 한다. */
  get modelGroup(): Group {
    return this.groups.models;
  }

  render(cam: CameraPose): void {
    if (this.disposed) return;
    const t0 = performance.now();
    const eye = toWorld(cam.eye[0]!, cam.eye[1]!, cam.eye[2]!);
    const target = toWorld(cam.target[0]!, cam.target[1]!, cam.target[2]!);
    const up = toWorld(cam.up[0]!, cam.up[1]!, cam.up[2]!);
    this.camera.position.set(eye[0], eye[1], eye[2]);
    this.camera.up.set(up[0], up[1], up[2]).normalize();
    this.camera.lookAt(new Vector3(target[0], target[1], target[2]));
    this.camera.fov = (cam.fovY * 180) / Math.PI;
    this.camera.updateProjectionMatrix();
    // 하늘은 카메라를 따라다닌다 — 반지름이 FAR의 0.9배라 움직이지 않으면 잘린다.
    this.sky.mesh.position.copy(this.camera.position);
    this.renderer.render(this.scene, this.camera);
    const info = this.renderer.info.render;
    this.stats = { drawCalls: info.calls, triangles: info.triangles, ms: performance.now() - t0 };
  }

  getStats(): SceneStats {
    return this.stats;
  }

  describe(): { name: string; maxTextureSize: number; maxAnisotropy: number } {
    const caps = this.renderer.capabilities;
    return {
      name: "three WebGL2",
      maxTextureSize: caps.maxTextureSize,
      maxAnisotropy: caps.getMaxAnisotropy(),
    };
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    for (const g of Object.values(this.groups)) disposeTree(g);
    this.sky.dispose();
    this.scene.clear();
    this.renderer.dispose();
    // **컨텍스트를 실제로 놓는다.** dispose()만으로는 브라우저가 컨텍스트를 회수하지
    // 않아, 탭을 몇 번 오가면 8~16개 한계에 걸려 새 캔버스가 검게 나온다.
    this.renderer.forceContextLoss();
  }
}

/** WebGL2를 못 만드는 환경에서 **던지지 않고 사유를 낸다** — 검은 캔버스만 남기면
 *  사용자는 무엇이 잘못됐는지 알 수 없다(옛 `worldrenderer.js`의 규약). */
export function createSceneHost(
  canvas: HTMLCanvasElement,
): { host: SceneHost; reason: null } | { host: null; reason: string } {
  if (typeof WebGL2RenderingContext === "undefined") {
    return { host: null, reason: "이 브라우저가 WebGL2를 지원하지 않습니다." };
  }
  const context = canvas.getContext("webgl2", { antialias: true });
  if (context == null) {
    return {
      host: null,
      reason: "WebGL2 컨텍스트를 만들지 못했습니다 — 하드웨어 가속이 꺼져 있거나 "
        + "GPU가 차단된 환경일 수 있습니다.",
    };
  }
  try {
    return { host: new SceneHost(canvas, context), reason: null };
  } catch (e) {
    return { host: null, reason: `렌더러를 만들지 못했습니다 — ${(e as Error).message}` };
  }
}
