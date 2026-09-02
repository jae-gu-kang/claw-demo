/** 하늘 — 표시용 그라디언트 (Preetham 같은 물리 모델이 아니다. 캡션이 그렇게 말한다).
 *
 * 옛 `views/renderer-three.js`에서 옮겨 온 셰이더다. 대기 산란 모델로 갈아 끼우는 것은
 * 뒤 단계이고, 그때 `FogExp2`도 함께 걷힌다 — 기본 시정 25 km에서 30 km 지점 투과율이
 * **0.36%**라 수평선의 윤슬을 지워 버리기 때문이다(실측).
 *
 * ## depthTest를 끄고 가장 먼저 그린다
 *
 * `logarithmicDepthBuffer`를 켜면 three 기본 재질은 프래그먼트에서 로그 깊이를 써 넣는데
 * 커스텀 `ShaderMaterial`은 그 청크를 포함하지 않아 비교가 어긋나고 **하늘이 통째로
 * 깊이 테스트에서 탈락한다**(화면이 검게 나오는데 셰이더는 멀쩡하다). 하늘은 언제나
 * 가장 뒤이므로 깊이 테스트를 끄고 `renderOrder`로 먼저 그린다 — three 내부 청크 구성에
 * 기대지 않아 버전 올림에도 안전하다.
 */

import {
  BackSide, Color, Mesh, ShaderMaterial, SphereGeometry, Vector3,
} from "three";

const VERT = `
varying vec3 vDir;
void main() {
  vDir = normalize(position);
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}`;

const FRAG = `
varying vec3 vDir;
uniform vec3 uZenith;
uniform vec3 uHorizon;
uniform vec3 uGround;
uniform vec3 uSunDir;
uniform float uSunIntensity;
void main() {
  vec3 dir = normalize(vDir);
  float h = dir.y;
  vec3 sky = mix(uHorizon, uZenith, pow(clamp(h, 0.0, 1.0), 0.45));
  vec3 col = mix(uGround, sky, smoothstep(-0.06, 0.02, h));
  float cosA = dot(dir, normalize(uSunDir));
  col += uSunIntensity * vec3(1.0, 0.93, 0.80) * pow(max(cosA, 0.0), 900.0) * 12.0; // 원반
  col += uSunIntensity * vec3(1.0, 0.85, 0.65) * pow(max(cosA, 0.0), 8.0) * 0.30;   // 둘레 번짐
  gl_FragColor = vec4(col, 1.0);
}`;

export interface Sky {
  mesh: Mesh;
  /** 태양 방향(월드)과 세기를 넣는다. 지평선 색을 돌려준다 — 안개가 같은 값을 쓴다. */
  setSun(dirWorld: readonly number[], elevation: number): Color;
  dispose(): void;
}

export function createSky(radius: number): Sky {
  const material = new ShaderMaterial({
    side: BackSide, depthWrite: false, depthTest: false, fog: false,
    vertexShader: VERT, fragmentShader: FRAG,
    uniforms: {
      uZenith: { value: new Color(0x2f6fb0) },
      uHorizon: { value: new Color(0x9fb4c7) },
      uGround: { value: new Color(0x5d6352) },
      uSunDir: { value: new Vector3(0.4, 0.6, 0.2) },
      uSunIntensity: { value: 1.0 },
    },
  });
  const geometry = new SphereGeometry(radius, 32, 20);
  const mesh = new Mesh(geometry, material);
  mesh.renderOrder = -1;        // 배경이므로 가장 먼저 (위 주석)
  mesh.frustumCulled = false;   // 카메라를 따라다니므로 컬링 판정이 뜻이 없다

  return {
    mesh,
    setSun(dirWorld, elevation) {
      material.uniforms.uSunDir!.value.set(dirWorld[0]!, dirWorld[1]!, dirWorld[2]!);
      // 해가 낮을수록 지평선이 붉어진다 — 표시 효과다(기상 모델 아님).
      const low = 1 - Math.min(Math.max(Math.sin(elevation), 0), 1);
      const horizon = new Color(0x9fb4c7).lerp(new Color(0xd9a066), low * 0.8);
      material.uniforms.uHorizon!.value.copy(horizon);
      material.uniforms.uSunIntensity!.value = Math.max(Math.sin(elevation), 0.05);
      return horizon;
    },
    dispose() {
      geometry.dispose();
      material.dispose();
    },
  };
}
