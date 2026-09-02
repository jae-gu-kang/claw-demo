/** 하늘 — 지형·모델·바다와 **같은 산란 함수**를 읽고, 그 위에 구름을 얹는다.
 *
 * 예전에는 천정↔지평 그라디언트였고 캡션이 "표시용"이라고 밝히고 있었다. 이제 레일리 +
 * 미 단일산란이라 시간대가 물리에서 나온다 — 여전히 근사지만(밀도 상수·다중산란 없음)
 * 지어낸 색 보간은 아니다. 무엇보다 **먼 지형이 저절로 그 방향의 하늘색이 된다**:
 * 에어리얼 퍼스펙티브가 같은 함수를 s만 유한하게 부르므로, 옛 코드가 `fog.color = horizon`
 * 으로 손수 맞추던 일이 없어졌다.
 *
 * ## 깊이를 **가장 뒤로 박고** 맨 나중에 그린다
 *
 * 구름이 오기 전에는 `depthTest: false`로 **먼저** 그렸다. 하늘 구가 반지름 45 km라
 * 프러스텀(50 km)보다 작아서, 깊이 비교를 켜면 45 km 너머 지형을 하늘이 가렸기 때문이다.
 *
 * 구름 레이마치가 붙자 그 순서가 비싸졌다 — 먼저 그리면 **지형·바다가 곧 덮을 픽셀까지**
 * 전부 적분한다. 화면의 절반이 넘는 낭비다. 그래서 정점 셰이더가 클립 z를 w로 놓아
 * 깊이를 정확히 1.0(가장 뒤)에 박고, `renderOrder`를 맨 뒤로 보내 **깊이 테스트가 켜진
 * 채** 그린다. 지운 깊이도 1.0이라 아무것도 안 그린 곳에서만 LEQUAL이 통과하고, 뭐든
 * 그려진 곳은 early-z가 조각 셰이더 자체를 건너뛴다. 구의 반지름은 이제 깊이와 무관하다.
 *
 * **근거리 패스에서는 `SplitFrustumPass`가 명시적으로 숨긴다** — 구가 카메라를 감싸고 있어
 * 프러스텀 컬링이 걸러 주지 않고, 근거리 패스는 깊이를 지우므로 안 숨기면 다시 다 그린다.
 */

import { BackSide, Color, Mesh, ShaderMaterial, SphereGeometry } from "three";

import { ATMOSPHERE_GLSL, ATMOSPHERE_UNIFORM_DECL } from "../shaders/atmosphere.ts";
import { CLOUD_UNIFORM_DECL, cloudGlsl } from "../shaders/clouds.ts";
import { NOISE_GLSL } from "../shaders/noise.ts";
import { atmosphereUniforms, cloudUniforms } from "./atmosphere.ts";

/** 하늘의 구름 적분 걸음 수. 바다 반사는 `scene/ocean.ts`가 더 거칠게 쓴다. */
export const SKY_CLOUD_STEPS = 16;
export const SKY_CLOUD_LIGHT_STEPS = 3;

const VERT = /* glsl */`
varying vec3 vDir;
void main() {
  vDir = normalize(position);
  vec4 clip = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  // 깊이를 정확히 1.0에 — 클립 공간 [−w, w]의 경계는 안쪽이다. 머리말 참조.
  gl_Position = vec4(clip.xy, clip.w, clip.w);
}`;

const FRAG = /* glsl */`
varying vec3 vDir;
uniform vec3 uGround;
${ATMOSPHERE_UNIFORM_DECL}
${CLOUD_UNIFORM_DECL}
${ATMOSPHERE_GLSL}
${NOISE_GLSL}
${cloudGlsl(SKY_CLOUD_STEPS, SKY_CLOUD_LIGHT_STEPS)}
void main() {
  vec3 dir = normalize(vDir);
  vec3 col = skyRadiance(dir, uSunDirWorld, uSunIntensity, uHaze);
  // 구름 — 투과율만큼 하늘을 남기고 자기 복사휘도를 더한다. 태양 원반도 여기서 가려진다.
  vec4 cl = cloudLayer(cameraPosition, dir, uSunDirWorld, uSunIntensity, uHaze);
  col = col * cl.a + cl.rgb;
  // 지평 아래 — 카메라가 낮으면 구의 아래쪽이 보인다. 지면색으로 가라앉힌다(표시용).
  col = mix(uGround, col, smoothstep(-0.06, 0.02, dir.y));
  gl_FragColor = vec4(col, 1.0);
}`;

export interface Sky {
  mesh: Mesh;
  setGroundColor(hex: number): void;
  dispose(): void;
}

export function createSky(radius: number): Sky {
  const material = new ShaderMaterial({
    // 깊이 테스트 **켠다** — 정점 셰이더가 깊이를 1.0에 박으므로 그려진 것은 전부 이긴다.
    side: BackSide, depthWrite: false, depthTest: true, fog: false,
    vertexShader: VERT, fragmentShader: FRAG,
    uniforms: {
      // **공유 유니폼을 그대로 꽂는다** — 하늘·에어리얼·바다가 같은 태양·같은 구름을 본다.
      ...atmosphereUniforms,
      ...cloudUniforms,
      uGround: { value: new Color(0x5d6352) },
    },
  });
  const geometry = new SphereGeometry(radius, 32, 20);
  const mesh = new Mesh(geometry, material);
  mesh.renderOrder = 1000;      // 맨 나중 — 가려진 픽셀은 early-z가 건너뛴다
  mesh.frustumCulled = false;   // 카메라를 따라다니므로 컬링 판정이 뜻이 없다

  return {
    mesh,
    setGroundColor(hex) {
      (material.uniforms.uGround!.value as Color).set(hex);
    },
    dispose() {
      geometry.dispose();
      material.dispose();
    },
  };
}
