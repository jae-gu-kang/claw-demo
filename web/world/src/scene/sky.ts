/** 하늘 — 지형·모델과 **같은 산란 함수**를 읽는다.
 *
 * 예전에는 천정↔지평 그라디언트였고 캡션이 "표시용"이라고 밝히고 있었다. 이제 레일리 +
 * 미 단일산란이라 시간대가 물리에서 나온다 — 여전히 근사지만(밀도 상수·다중산란 없음)
 * 지어낸 색 보간은 아니다. 무엇보다 **먼 지형이 저절로 그 방향의 하늘색이 된다**:
 * 에어리얼 퍼스펙티브가 같은 함수를 s만 유한하게 부르므로, 옛 코드가 `fog.color = horizon`
 * 으로 손수 맞추던 일이 없어졌다.
 *
 * ## 여전히 depthTest를 끈다 — 이유는 정밀도가 아니다
 *
 * 원거리 프러스텀에서 45 km 지점의 깊이 눈금은 0.08 m라 넉넉하다. 진짜 이유는 **구가
 * 유한한 껍질**이라는 것이다: 반지름 45 km인데 프러스텀은 50 km까지 보므로, 깊이 테스트를
 * 켜면 45 km 너머의 지형을 하늘이 **가린다.** 배경은 언제나 가장 뒤라는 사실이 확실하므로
 * 비교할 이유가 없다.
 *
 * **근거리 패스에서는 `SplitFrustumPass`가 명시적으로 숨긴다** — 구가 카메라를 감싸고 있어
 * 프러스텀 컬링이 걸러 주지 않는다.
 */

import { BackSide, Color, Mesh, ShaderMaterial, SphereGeometry } from "three";

import { ATMOSPHERE_GLSL, ATMOSPHERE_UNIFORM_DECL } from "../shaders/atmosphere.ts";
import { atmosphereUniforms } from "./atmosphere.ts";

const VERT = /* glsl */`
varying vec3 vDir;
void main() {
  vDir = normalize(position);
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}`;

const FRAG = /* glsl */`
varying vec3 vDir;
uniform vec3 uGround;
${ATMOSPHERE_UNIFORM_DECL}
${ATMOSPHERE_GLSL}
void main() {
  vec3 dir = normalize(vDir);
  vec3 col = skyRadiance(dir, uSunDirWorld, uSunIntensity, uHaze);
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
    side: BackSide, depthWrite: false, depthTest: false, fog: false,
    vertexShader: VERT, fragmentShader: FRAG,
    uniforms: {
      // **공유 유니폼을 그대로 꽂는다** — 하늘과 에어리얼이 같은 태양·같은 뿌연 정도를 본다.
      ...atmosphereUniforms,
      uGround: { value: new Color(0x5d6352) },
    },
  });
  const geometry = new SphereGeometry(radius, 32, 20);
  const mesh = new Mesh(geometry, material);
  mesh.renderOrder = -1;        // 배경이므로 가장 먼저
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
