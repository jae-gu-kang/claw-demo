/** 절차 노이즈 GLSL — **텍스처 0장**이라는 규칙의 값을 치르는 자리.
 *
 * 바다 잔물결과 구름이 같은 해시·같은 노이즈를 쓴다. 두 벌로 두면 한쪽만 고쳐져 잔물결과
 * 구름이 다른 질감으로 갈린다 — 눈에는 "어딘가 어색하다"로만 보인다.
 *
 * ## 그래디언트 노이즈 (iq 형식)
 *
 * 값과 **해석 도함수**를 함께 낸다. 바다는 도함수만 쓰고(기울기 → 법선), 구름은 값만
 * 쓴다. 수치미분이면 픽셀마다 두 번 더 뽑아야 하고 그 자체가 에일리어싱한다.
 *
 * ## 해시의 한계
 *
 * sin 기반 해시는 좌표가 커지면(월드 좌표 수만 m를 파장 0.5 m로 나누면 10⁵) 정밀도가
 * 떨어진다. Node로 재 보니 그 범위에서도 기울기 크기가 유지됐지만(평균 0.65), GPU
 * fp32의 sin 구현은 드라이버마다 다르다. 눈에 띄는 격자 결함이 보이면 여기가 첫 용의자다.
 */

export const NOISE_GLSL = /* glsl */`
#ifndef NOISE_GLSL_G
#define NOISE_GLSL_G
vec2 hash2(vec2 p) {
  p = vec2(dot(p, vec2(127.1, 311.7)), dot(p, vec2(269.5, 183.3)));
  return fract(sin(p) * 43758.5453) * 2.0 - 1.0;
}

/** 그래디언트 노이즈 — (값, ∂/∂x, ∂/∂y). 값은 대략 [−0.7, 0.7]. */
vec3 gnoise2(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  vec2 u = f * f * f * (f * (f * 6.0 - 15.0) + 10.0);
  vec2 du = 30.0 * f * f * (f * (f - 2.0) + 1.0);
  vec2 ga = hash2(i);
  vec2 gb = hash2(i + vec2(1.0, 0.0));
  vec2 gc = hash2(i + vec2(0.0, 1.0));
  vec2 gd = hash2(i + vec2(1.0, 1.0));
  float va = dot(ga, f);
  float vb = dot(gb, f - vec2(1.0, 0.0));
  float vc = dot(gc, f - vec2(0.0, 1.0));
  float vd = dot(gd, f - vec2(1.0, 1.0));
  float k1 = vb - va;
  float k2 = vc - va;
  float k3 = va - vb - vc + vd;
  float v = va + k1 * u.x + k2 * u.y + k3 * u.x * u.y;
  vec2 d = ga + u.x * (gb - ga) + u.y * (gc - ga) + u.x * u.y * (ga - gb - gc + gd)
         + du * (vec2(k1, k2) + k3 * vec2(u.y, u.x));
  return vec3(v, d);
}

/** 3D 값 노이즈 — 재질 마모용. 그래디언트 노이즈보다 싸고(해시 8번) 표면 얼룩에는 충분하다. */
float hash31(vec3 p) {
  p = fract(p * 0.1031);
  p += dot(p, p.yzx + 33.33);
  return fract((p.x + p.y) * p.z);
}

float vnoise3(vec3 p) {
  vec3 i = floor(p);
  vec3 f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  float a = mix(hash31(i), hash31(i + vec3(1.0, 0.0, 0.0)), f.x);
  float b = mix(hash31(i + vec3(0.0, 1.0, 0.0)), hash31(i + vec3(1.0, 1.0, 0.0)), f.x);
  float c = mix(hash31(i + vec3(0.0, 0.0, 1.0)), hash31(i + vec3(1.0, 0.0, 1.0)), f.x);
  float d = mix(hash31(i + vec3(0.0, 1.0, 1.0)), hash31(i + vec3(1.0, 1.0, 1.0)), f.x);
  return mix(mix(a, b, f.y), mix(c, d, f.y), f.z);
}

/** 3옥타브 fBm — 0~0.875. */
float fbm3(vec3 p) {
  return 0.5 * vnoise3(p) + 0.25 * vnoise3(p * 2.07 + 1.7) + 0.125 * vnoise3(p * 4.13 + 3.1);
}

/** fBm — 값만. 옥타브는 최대 5, 라쿠나리티 2.03(정수를 피해 반복 무늬를 줄인다). */
float fbm2(vec2 p, int octaves) {
  float v = 0.0;
  float a = 0.5;
  float norm = 0.0;
  for (int i = 0; i < 5; i++) {
    if (i >= octaves) break;
    v += a * gnoise2(p).x;
    norm += a;
    p = p * 2.03 + vec2(17.3, 9.1);
    a *= 0.5;
  }
  return v / max(norm, 1.0e-6);
}
#endif
`;
