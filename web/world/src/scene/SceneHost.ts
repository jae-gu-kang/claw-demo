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
  Group, HemisphereLight, LineBasicMaterial, LineSegments, Matrix4, Mesh,
  MeshStandardMaterial, PerspectiveCamera, Scene, SRGBColorSpace, Vector3,
  WebGLRenderer,
} from "three";

import { toWorld } from "./axes.ts";
import { SplitFrustumPass, createPost, type Post, type PostOptions } from "../post/composer.ts";
import { disposeTree } from "./dispose.ts";
import { applyAerialPerspective, setAtmosphere, setCloudTime, setClouds } from "./atmosphere.ts";
import type { CoastField } from "../core/coastfield.ts";
import { createOcean, type Ocean, type SeaState } from "./ocean.ts";
import { createSky, type Sky } from "./sky.ts";

/** 깊이 정책 — **분할 프러스텀**. 로그 깊이버퍼를 쓰지 않는다.
 *
 * ## 왜 로그 깊이를 걷었나
 *
 * `logarithmicDepthBuffer`를 켜면 three 기본 재질이 프래그먼트에서 `gl_FragDepth`에 로그
 * 깊이를 써 넣는데, 커스텀 `ShaderMaterial`은 그 청크를 안 내보내 비교가 어긋난다 —
 * 하늘이 통째로 검게 나온 그 버그다. 바다 셰이더는 지형과 **깊이 비교를 해야** 하므로
 * 하늘처럼 `depthTest: false`로 피할 수도 없다. 게다가 깊이를 읽는 후처리 패스(SSAO·DOF·
 * 모션블러)는 표준 깊이 인코딩을 전제하므로 로그 깊이 위에서는 통째로 틀린다.
 * **역Z는 있다 — 안 쓰는 것이다.** three 0.185.1은 `WebGLRenderer({ reversedDepthBuffer })`를
 * 받고 `EXT_clip_control` 위에서 구현한다(소스 확인). 다만 역Z가 값을 하는 것은 **부동소수
 * 깊이버퍼** 위에서다. 우리 컴포저 타깃은 `DEPTH_COMPONENT24` unorm이라(three의
 * `getInternalDepthFormat` 기본) 역Z를 켜도 눈금 분포가 거의 그대로다 — 32F 깊이 텍스처를
 * 따로 붙이는 일이 되는데, 그러면 분할 프러스텀보다 손이 더 간다.
 *
 * ## 왜 하나로는 안 되나 — 실측
 *
 * 표준 24비트에서 한 깊이 눈금이 세계 좌표로 몇 m인가:
 *
 *     NEAR    1 km      5 km     12 km     30 km
 *      3 m    0.02      0.50      2.86     17.88   ← 해안선 스커트(5 m)보다 크다
 *     10 m   6.0e-3     0.15      0.86      5.36
 *     30 m   2.0e-3     0.05      0.29      1.79   ← 온보드(기체 안 1.2 m)를 못 쓴다
 *
 * 두 번 그리면 양쪽을 다 가진다:
 *
 *     near [3, 2000]        1 km에서 0.02 m
 *     far  [1500, 50000]   30 km에서 0.03 m
 *
 * 겹치는 500 m가 이음매를 없앤다. 원거리부터 그리고 **깊이만 지운 뒤** 근거리를 덮는다 —
 * 근거리 물체는 정의상 더 가까우므로 덮는 것이 옳다.
 *
 * ## 겹침 구간은 **불투명에만** 옳다
 *
 * [1500, 2000]에 있는 것은 두 번 래스터라이즈된다. 불투명이면 두 번째가 첫 번째를 덮어
 * 결과가 같지만, **알파 블렌딩은 두 번 섞인다** — 그 띠에서만 색이 진해진다. 곧 올릴
 * 해면이 반투명이면 폭 500 m의 고리가 눈에 띄게 된다. 해면을 불투명으로 그리거나
 * (프레넬·심해색을 셰이더 안에서 합성), 그 구간에서 한 패스만 그리게 해야 한다.
 */
export const NEAR = 3;
export const NEAR_FAR = 2000;
export const FAR_NEAR = 1500;
export const FAR = 50000;
const SKY_RADIUS = FAR * 0.9;

// 대기 — `FogExp2`를 걷어내고 해석적 단일산란으로 갔다. `scene.fog`는 이제 쓰지 않는다.
// 시정은 `hazeForVisibility`가 미 소산계수로 옮기고, 재질에 거는 일은
// `scene/atmosphere.ts`의 `applyAerialPerspective`가 한다. 이유는 그 머리말에 있다.

/** Engineering 기본 — 블룸은 **태양 원반과 윤슬만** 걸리게 문턱을 높게 잡는다.
 *
 * 문턱 1.0은 `FogExp2` 시절 값이라 못 쓴다. 그때는 하늘이 LDR 그라디언트라 1.0을 넘는
 * 것이 태양 원반뿐이었는데, 대기 산란을 켜면 **하늘 자체가 HDR**이 된다 — 산란식에
 * 넣어 보면 한낮 지평이 1 남짓, 낮은 해 쪽은 그 몇 배다. 그래서 하늘 전체가 블룸에
 * 걸려 화면 절반이 하얗게 뭉갰다(고도 8.6°에서 눈으로 확인). 2.5로 올리면 한낮 하늘은
 * 통째로 빠지고 태양 원반만 남는다 — 곧 올릴 윤슬도 정반사라 이 위에 선다.
 *
 * Cinematic이 오면 세기·반경을 올리고 모션블러·DOF가 붙는다(계획 §7). */
const DEFAULT_POST: PostOptions = {
  bloomStrength: 0.35, bloomRadius: 0.4, bloomThreshold: 2.5, antialias: true,
};

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
  /** 해상 상태 — **표시 값**이다(`core/waves.ts` 머리말). */ sea: SeaState;
  /** 구름 덮임 0~1 — 표시 값. */ cloudCover: number;
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
  /** **장면만** — 후처리 풀스크린 쿼드는 안 센다. */
  drawCalls: number;
  triangles: number;
  /** **CPU 제출 시간**이다 — GPU 실행 시간이 아니다. 2 ms에 제출하고도 60 fps를
   *  놓칠 수 있고 그 반대도 된다. GPU를 재려면 `EXT_disjoint_timer_query_webgl2`가 필요하다. */
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
  private readonly ocean: Ocean;
  private readonly sun: DirectionalLight;
  private readonly ambient: HemisphereLight;
  private readonly groups = {
    terrain: new Group(), paths: new Group(), models: new Group(),
  };

  private stats: SceneStats = { drawCalls: 0, triangles: 0, ms: 0 };
  private disposed = false;
  private post: Post | null = null;
  private readonly scenePass: SplitFrustumPass;
  private size = { w: 1, h: 1, dpr: 1 };
  /** 프레임마다 다시 채운다 — 매번 새로 만들면 GC가 프레임을 갉는다. */
  private readonly gridInvViewProj = new Matrix4();

  constructor(canvas: HTMLCanvasElement, context: WebGL2RenderingContext) {
    // 컨텍스트를 밖에서 만들어 넘긴다 — 같은 캔버스의 두 번째 getContext는 기존 것을
    // 돌려주면서 antialias 같은 속성을 무시하므로, 여기서 다시 만들면 조용히 꺼진다.
    // 로그 깊이버퍼는 쓰지 않는다 — 위 주석. 분할 프러스텀이 그 자리를 대신한다.
    //
    // **`autoClear`는 전역으로 끄지 않는다.** 분할 패스가 자기 안에서만 끄고 되돌린다.
    // 전역으로 끄면 `SMAAPass`가 조용히 망가진다 — 그쪽은 내부 타깃을 `renderer.autoClear`에
    // 기대어 지우고, 에지 셰이더가 `discard`를 쓰므로 안 지우면 마스크가 누적된다.
    this.renderer = new WebGLRenderer({ canvas, context });
    this.renderer.outputColorSpace = SRGBColorSpace;
    this.renderer.toneMapping = ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 0.95;

    // 색·세기는 `setEnvironment`가 대기 모델에서 정한다. 여기 값은 그전 한 프레임용이다.
    this.sun = new DirectionalLight(0xffffff, 1);
    this.ambient = new HemisphereLight(0xbcd6f0, 0x6b6f5a, 0.9);
    this.scene.add(this.sun, this.ambient);

    this.sky = createSky(SKY_RADIUS);
    this.scene.add(this.sky.mesh);
    // 해면은 **두 패스에 다 그린다** — 발밑부터 수평선까지 걸쳐 있어 어느 한쪽에만
    // 두면 그 구간에서 사라진다. 불투명이라 겹침 구간에서 두 번 그려도 결과가 같다.
    this.ocean = createOcean({ maxDist: FAR * 0.98 });
    this.scene.add(this.ocean.mesh);
    for (const g of Object.values(this.groups)) this.scene.add(g);

    this.scenePass = new SplitFrustumPass(
      this.scene, this.camera,
      { near: NEAR, nearFar: NEAR_FAR, farNear: FAR_NEAR, far: FAR },
      [this.sky.mesh],
    );
    // **경로를 하나로 둔다.** 컴포저 없는 직접 렌더 경로를 따로 두면 분할 프러스텀 코드가
    // 두 벌이 되고, 언젠가 한쪽만 고쳐진다(`disposeTree`에서 겪은 그것).
    this.setPost(DEFAULT_POST);
  }

  /** 후처리 구성을 세운다 — 모드가 바뀌면 다시 세운다. */
  setPost(opts: PostOptions): void {
    this.post?.dispose();
    this.post = createPost(this.renderer, this.scenePass, this.size.w, this.size.h, opts);
    this.post.setSize(this.size.w, this.size.h, this.size.dpr);
  }

  resize(width: number, height: number, dpr: number): void {
    // dpr 3 기기에서 픽셀 수가 9배가 되는 것을 막는다.
    this.size = { w: width, h: height, dpr };
    this.renderer.setPixelRatio(Math.min(dpr, 2));
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / Math.max(height, 1);
    this.camera.updateProjectionMatrix();
    this.post?.setSize(width, height, dpr);
  }

  setEnvironment({ sunAzEl, visibility, exposure, sea, cloudCover }: Environment): void {
    const [az, el] = sunAzEl;
    // 태양 방향을 NED로 만든 뒤 같은 toWorld를 태운다 — 하늘·직사광·산란이 한 값에서 나온다.
    const w = toWorld(Math.cos(el) * Math.cos(az), Math.cos(el) * Math.sin(az), -Math.sin(el));
    this.sun.position.set(w[0] * 1000, w[1] * 1000, w[2] * 1000);
    // 대기 밖 세기. 대기를 지나며 붉어지고 어두워지는 몫은 아래 `sunColor`가 맡는다.
    const intensity = 2.4;
    // **하늘·지형·모델이 이 한 벌의 유니폼을 공유한다.** 예전에는 `fog.color`를 지평선
    // 하늘색으로 손수 맞췄는데, 이제는 먼 지형이 그 방향의 하늘색이 되는 것이 산란
    // 함수에서 저절로 나온다 — 맞춰 줄 색이 없다.
    const sunColor = setAtmosphere(w, el, intensity, visibility);
    // 직사광이 **하늘과 같은 태양색**을 쓴다. 저녁에 하늘만 붉고 지형은 하얗게 남는
    // 어긋남이 여기서 닫힌다. 세기는 대기 밖 값 그대로 두고, 색이 감쇠분을 진다
    // (three는 색 × 세기를 곱하므로 결과가 같고, 두 수의 뜻이 갈려 있어 읽기 쉽다).
    this.sun.color.setRGB(sunColor[0], sunColor[1], sunColor[2]);
    this.sun.intensity = intensity;
    // 환경광은 하늘의 대역이다 — 해가 지면 같이 죽어야 한다. 상수로 두면 노을에
    // 지형만 평평한 회색으로 남는다. 표시용 근사이고, 하늘 적분이 아니라 고도의 함수다.
    this.ambient.intensity = 0.12 + 0.8 * Math.max(Math.sin(el), 0);
    this.ocean.setSea(sea);
    // 구름은 바다와 **같은 바람**으로 흐른다 — 표시용 바람은 하나다.
    setClouds(cloudCover, [
      sea.windSpeed * Math.cos(sea.windDir), sea.windSpeed * Math.sin(sea.windDir),
    ]);
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
      const mat = new MeshStandardMaterial({
        vertexColors: true, roughness: 0.95, metalness: 0,
      });
      applyAerialPerspective(mat);
      this.groups.terrain.add(new Mesh(geo, mat));
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
      const mat = new LineBasicMaterial({ color: ln.color });
      // 궤적도 대기를 탄다 — 안 걸면 30 km 밖 선만 또렷해서 지형 위에 떠 보인다.
      applyAerialPerspective(mat);
      this.groups.paths.add(new LineSegments(geo, mat));
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

  /** 해안 거리장 — 결과가 바뀔 때. `null`이면 해면이 전부 열린 바다가 된다. */
  setCoast(field: CoastField | null): void {
    this.ocean.setCoast(field);
  }

  /** 지금의 해상 상태 — 캡션이 수치를 말한다. */
  seaState(): { windSpeed: number; waveHeight: number; slopeVariance: number } {
    return this.ocean.describe();
  }

  /** @param timeSec 해면 위상에 쓸 시각 [s]. **시뮬 시각**을 넣는다 — 벽시계로 돌리면
   *  멈춘 화면에서도 파도가 움직여야 하고, 그러면 온디맨드 렌더 루프가 무너진다. */
  render(cam: CameraPose, timeSec: number): void {
    if (this.disposed || this.post == null) return;
    const t0 = performance.now();
    const eye = toWorld(cam.eye[0]!, cam.eye[1]!, cam.eye[2]!);
    const target = toWorld(cam.target[0]!, cam.target[1]!, cam.target[2]!);
    const up = toWorld(cam.up[0]!, cam.up[1]!, cam.up[2]!);
    this.camera.position.set(eye[0], eye[1], eye[2]);
    this.camera.up.set(up[0], up[1], up[2]).normalize();
    this.camera.lookAt(new Vector3(target[0], target[1], target[2]));
    this.camera.fov = (cam.fovY * 180) / Math.PI;
    // 하늘은 카메라를 따라다닌다 — 반지름이 FAR의 0.9배라 움직이지 않으면 잘린다.
    // (near/far와 투영행렬은 `SplitFrustumPass`가 패스마다 세운다.)
    this.sky.mesh.position.copy(this.camera.position);

    // **투영 격자는 전 구간 프러스텀에서 뽑는다.** 패스별 near/far로 뽑으면 두 패스가
    // 서로 다른 해면 지오메트리를 만들어 겹침 구간에 이음매가 생긴다(`shaders/ocean.ts`).
    this.camera.near = NEAR;
    this.camera.far = FAR;
    this.camera.updateProjectionMatrix();
    // `lookAt`은 쿼터니언만 고친다 — 월드행렬을 손수 갱신해야 역행렬이 이 프레임 것이 된다.
    this.camera.updateMatrixWorld(true);
    setCloudTime(timeSec);
    this.ocean.setView(
      this.camera.position,
      this.gridInvViewProj
        .multiplyMatrices(this.camera.projectionMatrix, this.camera.matrixWorldInverse)
        .invert(),
      timeSec,
      cam.fovY,
      this.camera.aspect,
    );

    // **한 프레임에 draw call이 두 벌**이라 자동 리셋이면 근거리 것만 남는다.
    this.renderer.info.autoReset = false;
    this.renderer.info.reset();
    try {
      this.post.render();
    } finally {
      // 던지면 자동 리셋이 꺼진 채로 남아 카운터가 영영 누적된다.
      this.renderer.info.autoReset = true;
    }
    // **장면만의 수를 쓴다.** `info`를 그대로 읽으면 후처리 풀스크린 쿼드가 섞여
    // (블룸 13 · SMAA 3 · Output 1) 드로우콜의 3분의 1쯤이 장면이 아닌 것이 된다.
    const scene = this.post.sceneStats();
    this.stats = { ...scene, ms: performance.now() - t0 };
  }

  getStats(): SceneStats {
    return this.stats;
  }

  describe(): { name: string; maxTextureSize: number; maxAnisotropy: number; depthBits: number } {
    const caps = this.renderer.capabilities;
    const gl = this.renderer.getContext();
    return {
      name: "three WebGL2",
      maxTextureSize: caps.maxTextureSize,
      maxAnisotropy: caps.getMaxAnisotropy(),
      // 깊이 정책의 전제다 — 24비트를 가정하고 분할 구간을 골랐다(위 주석의 실측표).
      depthBits: gl.getParameter(gl.DEPTH_BITS) as number,
    };
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.post?.dispose();
    this.post = null;
    for (const g of Object.values(this.groups)) disposeTree(g);
    this.sky.dispose();
    this.ocean.dispose();
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
