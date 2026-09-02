/** 해면 — 투영 격자 메시와 유니폼.
 *
 * 파동 파라미터는 `core/waves.ts`가 만든다(테스트가 거기 붙는다). GLSL은
 * `shaders/ocean.ts`. 여기는 그 둘을 three에 묶고 프레임마다 카메라를 넣어 주는 층이다.
 *
 * ## 왜 DoubleSide인가
 *
 * 투영 격자는 화면 공간 격자를 평면에 되쏜 것이라, **세계 좌표에서의 감김이 카메라
 * 자세에 따라 뒤집힌다** — 지평선을 넘겨 보거나 마루 너머를 스칠 때 삼각형이 뒤집힌다.
 * 고정된 감김을 전제하고 컬링을 켜면 그때 바다에 구멍이 뚫린다. 컬링을 포기하는 대신
 * 그 실패를 없앤다.
 *
 * ## 깊이는 밀어 둔다
 *
 * `polygonOffset`으로 해면을 지형보다 아주 조금 뒤로 민다. 표고가 **정확히 0 m인 육지**가
 * 16.5 km² 있어서(간척지·저지대 — `core/seamask.ts`), 그 위에서 해면과 지형이 같은 깊이에
 * 앉는다. 밀어 두면 지형이 이긴다. 파도가 그 위로 솟는 몫은 4단계의 해안 거리장이
 * 해안 근처 파고를 죽이면서 없어진다.
 */

import {
  BufferAttribute, BufferGeometry, ClampToEdgeWrapping, DataTexture, DoubleSide, LinearFilter,
  Matrix4, Mesh, RGFormat, ShaderMaterial, UnsignedByteType, Vector2, Vector3, Vector4,
} from "three";

import { encodeCoastField, type CoastField } from "../core/coastfield.ts";
import { ATMOSPHERE_GLSL, ATMOSPHERE_UNIFORM_DECL } from "../shaders/atmosphere.ts";
import { CLOUD_COVER_GLSL, CLOUD_UNIFORM_DECL, cloudGlsl } from "../shaders/clouds.ts";
import { NOISE_GLSL } from "../shaders/noise.ts";
import { OCEAN_FRAG, OCEAN_VERT } from "../shaders/ocean.ts";
import { WAVE_COUNT, coxMunkSlopeVariance, gerstnerSet, significantWaveHeight } from "../core/waves.ts";
import { atmosphereUniforms, cloudUniforms } from "./atmosphere.ts";

/** 해상 상태 — 전부 **표시 값**이다(`WAVE_NOTES.displayOnly`). */
export interface SeaState {
  /** 풍속 [m/s] */ windSpeed: number;
  /** 바람이 가는 방향 [rad] — 렌더 x·z 평면, +x 기준 반시계 */ windDir: number;
}

export interface OceanOptions {
  /** NDC 격자 칸 수 (가로, 세로) */ cols: number; rows: number;
  /** 격자를 화면 밖으로 넓히는 여유 — 정점이 파동에 밀려 화면 안으로 들어와도 틈이 없게 */
  margin: number;
  /** 해면을 그리는 최대 수평 거리 [m] */ maxDist: number;
}

export const OCEAN_DEFAULTS: OceanOptions = {
  // 1148×570 캔버스에서 칸 하나가 4 px 안팎. 112줄로 시작했다가 176으로 올렸다 —
  // 성긴 격자에서는 나이퀴스트 판정이 20 m 파까지 접어 버려 바다가 유리처럼 매끈해졌다.
  cols: 288, rows: 176, margin: 0.06, maxDist: 49000,
};

/** NDC 격자 — 정점 좌표가 곧 화면 좌표다. 세계 위치는 정점 셰이더가 만든다. */
function gridGeometry(o: OceanOptions): BufferGeometry {
  const nx = o.cols + 1;
  const ny = o.rows + 1;
  const pos = new Float32Array(nx * ny * 3);
  const lo = -1 - o.margin;
  const span = 2 * (1 + o.margin);
  for (let j = 0; j < ny; j++) {
    for (let i = 0; i < nx; i++) {
      const k = 3 * (j * nx + i);
      pos[k] = lo + (span * i) / o.cols;
      pos[k + 1] = lo + (span * j) / o.rows;
      pos[k + 2] = 0;
    }
  }
  const idx = new Uint32Array(o.cols * o.rows * 6);
  let t = 0;
  for (let j = 0; j < o.rows; j++) {
    for (let i = 0; i < o.cols; i++) {
      const a = j * nx + i;
      idx[t++] = a; idx[t++] = a + 1; idx[t++] = a + nx;
      idx[t++] = a + 1; idx[t++] = a + nx + 1; idx[t++] = a + nx;
    }
  }
  const g = new BufferGeometry();
  g.setAttribute("position", new BufferAttribute(pos, 3));
  g.setIndex(new BufferAttribute(idx, 1));
  return g;
}

export interface Ocean {
  mesh: Mesh;
  /** 프레임마다 — 카메라와 시간. `invViewProj`는 **전 구간** 프러스텀의 것이어야 한다. */
  setView(
    camPos: Vector3, invViewProj: Matrix4, timeSec: number, fovYRad: number, aspect: number,
  ): void;
  /** 해상 상태가 바뀔 때만. 파 성분과 거칠기를 다시 만든다. */
  setSea(sea: SeaState): void;
  /** 해안 거리장 — 결과(지형 팩)가 바뀔 때만.
   *
   * **`null`이면 해면을 아예 그리지 않는다.** 지형이 없으면 해안선도 모르고, 모르는 채로
   * 무한 평면을 깔면 화면 전체가 지어낸 바다가 된다 — 구멍을 구멍으로 두는 규약과 같다. */
  setCoast(field: CoastField | null): void;
  /** 캡션이 말할 지금의 해상 상태. */
  describe(): { windSpeed: number; waveHeight: number; slopeVariance: number };
  dispose(): void;
}

export function createOcean(opts: Partial<OceanOptions> = {}): Ocean {
  const o = { ...OCEAN_DEFAULTS, ...opts };
  const geometry = gridGeometry(o);

  const uWave = Array.from({ length: WAVE_COUNT }, () => new Vector4());
  const uWaveQ = Array.from({ length: WAVE_COUNT }, () => new Vector2());

  const material = new ShaderMaterial({
    // **불투명하다** — 분할 프러스텀의 겹침 구간이 두 번 섞이지 않게(머리말).
    transparent: false,
    side: DoubleSide,
    depthWrite: true,
    polygonOffset: true,
    polygonOffsetFactor: 1,
    polygonOffsetUnits: 1,
    vertexShader: OCEAN_VERT,
    // 반사의 구름은 거친 적분(3걸음·빛 1걸음)이다 — 파도에 이미 흐트러지고, 바다 픽셀은
    // 화면의 절반이라 하늘과 같은 10걸음이면 그 비용이 그대로 프레임에 실린다.
    fragmentShader: [
      ATMOSPHERE_UNIFORM_DECL, CLOUD_UNIFORM_DECL, ATMOSPHERE_GLSL, NOISE_GLSL,
      CLOUD_COVER_GLSL, cloudGlsl(3, 1), OCEAN_FRAG,
    ].join("\n"),
    uniforms: {
      ...atmosphereUniforms,
      ...cloudUniforms,
      uGridInvViewProj: { value: new Matrix4() },
      uCamPos: { value: new Vector3() },
      uMaxDist: { value: o.maxDist },
      uTime: { value: 0 },
      // 격자 한 칸의 화각 (세로, 가로) [rad] — 나이퀴스트 판정용. `setView`가 채운다.
      uGridAngle: { value: new Vector2(0.01, 0.01) },
      // 법선 분산을 거칠기로 옮기는 계수. 눈으로 맞춘다 — 작으면 지글거리고,
      // 크면 가까운 파도까지 흐려진다.
      uSpecAA: { value: 150 },
      // 잔물결 — 세기는 풍속에서, 거리는 화면에서 정한다.
      uRipple: { value: 1 },
      uWindDir: { value: new Vector2(1, 0) },
      uWave: { value: uWave },
      uWaveQ: { value: uWaveQ },
      // 해안 거리장 — `setCoast`가 채운다. 없으면 `uHasCoast = 0`이라 전부 열린 바다다.
      uCoast: { value: null },
      uCoastMin: { value: new Vector2() },
      uCoastInvSpan: { value: new Vector2(1, 1) },
      uHasCoast: { value: 0 },
      // 이 거리 안쪽에서 파고가 0으로 잦아든다. 얕은 물에서 파도가 부서지는 폭과
      // 자리수가 맞고, 표고 0 m 땅 위로 마루가 솟는 것을 막는 몫도 한다.
      uShoreFade: { value: 420 },
      uRoughness: { value: 0.2 },
      uWaveHeight: { value: 1 },
      // 심해색과 상향 산란 — 선형값. 프레넬이 2%(수직)~100%(스침)로 하늘을 섞는다.
      uDeepColor: { value: new Vector3(0.0008, 0.0045, 0.0075) },
      // 얕은 물 — 수심 자료가 없어 해안 거리를 대신 쓴다(표시용 대리값).
      uShallowColor: { value: new Vector3(0.010, 0.045, 0.048) },
      uScatterColor: { value: new Vector3(0.004, 0.030, 0.038) },
      // 포말 양 — 풍속에서 나온다. `setSea`가 채운다.
      uFoamAmount: { value: 0 },
      // **표시 보정값이다.** 이 렌더러의 절대 밝기는 물리 단위가 아니다 — 하늘은
      // 단일산란이 놓치는 다중산란 몫을 4π로 대신 받고, 태양 원반도 60이라는 고른 수다.
      // 윤슬을 그 눈금 위에 세우는 계수이고, 눈으로 맞춘다.
      uGlitterGain: { value: 4 },
    },
  });

  const mesh = new Mesh(geometry, material);
  // 격자가 프레임마다 통째로 움직이므로 경계구가 뜻이 없다.
  mesh.frustumCulled = false;
  // 해안 거리장이 오기 전에는 그리지 않는다 — `setCoast` 참조.
  mesh.visible = false;

  let state: SeaState = { windSpeed: 7, windDir: 0.6 };
  let coast: DataTexture | null = null;

  const apply = (): void => {
    const waves = gerstnerSet(state.windSpeed, state.windDir);
    for (let i = 0; i < WAVE_COUNT; i++) {
      const w = waves[i]!;
      uWave[i]!.set(w.dir[0], w.dir[1], w.amplitude, w.k);
      uWaveQ[i]!.set(w.q, w.omega);
    }
    // 베크만 경사분산이 곧 α²이므로 α = σ (`core/waves.ts` 주석).
    material.uniforms.uRoughness!.value = Math.sqrt(coxMunkSlopeVariance(state.windSpeed));
    material.uniforms.uWaveHeight!.value = significantWaveHeight(state.windSpeed);
    // 백파는 대략 6~7 m/s부터 눈에 띈다. 표시용 램프다.
    material.uniforms.uFoamAmount!.value =
      Math.min(Math.max((state.windSpeed - 5.5) / 9, 0), 1);
    // 잔물결은 바람이 조금만 있어도 곧바로 선다 — 파고보다 훨씬 빨리 포화한다.
    material.uniforms.uRipple!.value = Math.min(state.windSpeed / 5, 1.4);
    (material.uniforms.uWindDir!.value as Vector2)
      .set(Math.cos(state.windDir), Math.sin(state.windDir));
  };
  apply();

  return {
    mesh,
    setView(camPos, invViewProj, timeSec, fovYRad, aspect) {
      (material.uniforms.uCamPos!.value as Vector3).copy(camPos);
      (material.uniforms.uGridInvViewProj!.value as Matrix4).copy(invViewProj);
      material.uniforms.uTime!.value = timeSec;
      // 격자 칸 수는 고정이므로 화각만 바뀐다. 줌인하면 칸이 촘촘해져 짧은 파가 되살아난다.
      (material.uniforms.uGridAngle!.value as Vector2)
        .set(fovYRad / o.rows, (fovYRad * aspect) / o.cols);
    },
    setSea(sea) {
      state = sea;
      apply();
    },
    setCoast(field) {
      coast?.dispose();
      coast = null;
      material.uniforms.uCoast!.value = null;
      material.uniforms.uHasCoast!.value = 0;
      mesh.visible = field !== null;
      if (field === null) return;
      const tex = new DataTexture(
        encodeCoastField(field), field.size, field.size, RGFormat, UnsignedByteType,
      );
      // 밉맵은 만들지 않는다 — 해안선을 뭉개면 파고 감쇠 띠가 뭍 안쪽으로 번진다.
      tex.minFilter = LinearFilter;
      tex.magFilter = LinearFilter;
      tex.wrapS = ClampToEdgeWrapping;
      tex.wrapT = ClampToEdgeWrapping;
      // RG8은 화소당 2바이트라 줄 길이가 4의 배수라는 보장이 없다. 기본값 4로 두면
      // 홀수 폭에서 줄이 어긋난다 — 화면에서는 해안선이 비스듬히 밀린 것으로 보인다.
      tex.unpackAlignment = 1;
      tex.needsUpdate = true;
      coast = tex;
      material.uniforms.uCoast!.value = tex;
      (material.uniforms.uCoastMin!.value as Vector2).set(field.e0, field.n0);
      (material.uniforms.uCoastInvSpan!.value as Vector2)
        .set(1 / field.eSpan, 1 / field.nSpan);
      material.uniforms.uHasCoast!.value = 1;
    },
    describe() {
      return {
        windSpeed: state.windSpeed,
        waveHeight: significantWaveHeight(state.windSpeed),
        slopeVariance: coxMunkSlopeVariance(state.windSpeed),
      };
    },
    dispose() {
      geometry.dispose();
      material.dispose();
      coast?.dispose();
    },
  };
}
