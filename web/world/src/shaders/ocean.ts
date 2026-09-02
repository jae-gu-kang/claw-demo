/** 해면 GLSL — 게르스트너 변위와 물의 반사.
 *
 * ## 격자를 화면에서 만든다 (projected grid)
 *
 * 정점은 **NDC 격자**로 들어온다. 셰이더가 각 NDC 점으로 광선을 쏘아 해수면(y = 0)과
 * 만나게 하므로, 화면 픽셀당 삼각형 밀도가 카메라 고도와 무관하게 일정하다. 동심원
 * 클립맵처럼 링 경계에서 팝핑이 나지 않는다.
 *
 * **패스마다 바뀌지 않는 역행렬을 쓴다.** 분할 프러스텀은 한 프레임에 near/far를 두 번
 * 바꾸는데, 격자를 `projectionMatrix`에서 뽑으면 두 패스가 **다른 지오메트리**를 만들어
 * 겹침 구간(1500~2000 m)에 이음매가 생긴다. 그래서 전 구간(NEAR..FAR)으로 한 번 세운
 * `uGridInvViewProj`를 CPU가 넣어 주고, 정점 위치는 그것에서만 나온다. 화면 투영만
 * 패스별 행렬로 한다.
 *
 * ## 불투명이다
 *
 * `SceneHost`의 깊이 정책 주석에 있는 그대로다 — 겹침 구간은 두 번 래스터라이즈되므로
 * 알파 블렌딩이면 폭 500 m의 고리가 진해진다. 프레넬·심해색을 셰이더 안에서 합성하고
 * 면은 불투명으로 그린다.
 *
 * ## 파동 세 단
 *
 *     너울·중파   게르스트너 5성분 — **정점을 실제로 움직인다**
 *     잔물결      4성분 해석 사인의 기울기 → 법선만 흔든다 (기하 없음, 텍스처 0장)
 *     그 아래     콕스-먼크 경사분산 → 마이크로패싯 거칠기 (통계로만)
 *
 * 정점을 움직여야 수평선 실루엣이 출렁이고 마루가 선다. 노멀맵만 입힌 물과 갈리는 곳이
 * 여기다. 반대로 격자보다 짧은 파는 기하로 풀 수 없다 — 그리려 들면 정점마다 위상이 튀어
 * **중거리에 흰 띠**가 선다(실측). 그래서 세 단으로 넘긴다: 격자가 푸는 데까지는 기하,
 * 그 아래 수 m까지는 법선, 더 아래는 거칠기. 거칠기는 거리로 죽이지 않는다 — 그것이
 * 멀리서 윤슬이 회색으로 죽지 않는 이유다.
 */

import { COAST_RANGE_M } from "../core/coastfield.ts";
import { WAVE_COUNT } from "../core/waves.ts";

// 조각 셰이더는 `NOISE_GLSL`(gnoise2)을 앞에 붙여야 한다 — `scene/ocean.ts`가 조립한다.

/** 해안 거리장 조회 — 정점·조각이 **같은 식**을 쓴다.
 *
 * 복호는 `core/coastfield.ts`의 `decodeCoastDistance`와 짝이다. 한쪽만 고치면 해안선이
 * 통째로 밀리는데, 그건 "지형이 좀 이상하네"로 보여서 원인이 안 잡힌다. */
const COAST_GLSL = /* glsl */`
uniform sampler2D uCoast;
uniform vec2 uCoastMin;      // (e0, n0) [m]
uniform vec2 uCoastInvSpan;  // 1/(eSpan, nSpan)
// 0이면 거리장이 없다. 그때 해면은 scene/ocean.ts가 통째로 숨기므로 이 갈래는 보수적
// 기본값일 뿐이다 — 지형을 모르면 해안선도 모른다.
uniform float uHasCoast;

/** 월드 (x, z) → (해안거리 [m], known). 도메인 밖은 열린 바다. */
vec2 coastAt(vec2 worldXZ) {
  if (uHasCoast < 0.5) return vec2(${COAST_RANGE_M}.0, 1.0);
  // 렌더 좌표 x = e, z = −n (scene/axes.ts — 주석 안에서 백틱은 리터럴을 끊는다).
  vec2 uv = (vec2(worldXZ.x, -worldXZ.y) - uCoastMin) * uCoastInvSpan;
  if (any(lessThan(uv, vec2(0.0))) || any(greaterThan(uv, vec2(1.0)))) {
    return vec2(${COAST_RANGE_M}.0, 1.0);
  }
  vec2 t = textureLod(uCoast, uv, 0.0).rg;
  return vec2((t.r * 2.0 - 1.0) * ${COAST_RANGE_M}.0, t.g);
}
`;

/** 정점 셰이더 — NDC 격자를 해수면에 눕히고 게르스트너로 밀어 올린다. */
export const OCEAN_VERT = /* glsl */`
${COAST_GLSL}
uniform mat4 uGridInvViewProj;
uniform vec3 uCamPos;
uniform float uMaxDist;
uniform float uTime;
uniform vec2 uGridAngle;       // (세로 한 줄, 가로 한 칸)이 덮는 화각 [rad]
uniform float uShoreFade;      // 이 거리 안쪽에서 파고가 0으로 잦아든다 [m]
uniform vec4 uWave[${WAVE_COUNT}];    // dir.x, dir.z, 진폭 A, 파수 k
uniform vec2 uWaveQ[${WAVE_COUNT}];   // 가파름 Q, 각주파수 ω

varying vec3 vWorld;
varying vec3 vNormal;
varying float vDist;
varying vec2 vCoast;   // (해안거리 [m], known)

/** NDC 한 점 → 해수면 위의 밑점. */
vec3 seaBase(vec2 ndc) {
  vec4 a = uGridInvViewProj * vec4(ndc, -1.0, 1.0);
  vec4 b = uGridInvViewProj * vec4(ndc,  1.0, 1.0);
  vec3 dir = normalize(b.xyz / b.w - a.xyz / a.w);
  // 카메라가 해수면 아래면 광선이 뒤로 간다 — 물 밑은 이 모델의 밖이라 위로 붙여 둔다.
  float h = max(uCamPos.y, 0.05);
  // 아래로 향하는 광선만 평면과 만난다. 지평선 위쪽은 최대 거리로 밀어 고리로 뭉친다
  // (그 줄의 삼각형은 넓이가 0이 된다 — 버려지는 것이 맞다).
  float t = (dir.y < -1.0e-4) ? min(h / -dir.y, uMaxDist) : uMaxDist;
  vec3 p = uCamPos + dir * t;
  return vec3(p.x, 0.0, p.z);
}

void main() {
  vec3 base = seaBase(position.xy);
  vDist = length(base.xz - uCamPos.xz);

  // **격자가 못 푸는 파장은 그리지 않는다 (나이퀴스트).**
  //
  // 투영 격자의 칸은 **길쭉하다.** 시선 방향으로는 높이 h에서 거리 d일 때 d²·θ_v/h로
  // 벌어지고(스치는 각일수록 급격히), 가로로는 d·θ_h로 훨씬 촘촘하다. 처음에 시선
  // 방향만 보고 판정했더니 30 m 상공·300 m 앞에서 칸이 16 m로 잡혀 **20 m 파까지 접혔고
  // 바다가 유리판이 됐다.** 방향이 정해지지 않은 2차원 파의 표본 밀도를 정하는 것은
  // 면적이므로 두 간격의 기하평균을 쓴다.
  //
  // 고정 거리로 죽이는 것과 갈리는 곳은 고도다: 궤도 시점(20 km 상공)에서는 200 m 파도
  // 못 풀고, 해면 근처에서는 10 m 파가 살아야 한다. 이 식은 그 둘을 함께 맞춘다.
  float camH = max(uCamPos.y, 1.0);
  float along = vDist * vDist * uGridAngle.x / camH;
  float across = vDist * uGridAngle.y;
  float cell = max(sqrt(along * across), 0.05);

  // **해안에서 파고를 재운다.** 표고가 정확히 0 m인 땅이 16.5 km² 있어서(간척지·저지대),
  // 재우지 않으면 파마루가 지형을 뚫고 올라온다 — 실측으로 본 그것이다.
  // 얕은 곳에서 파도가 부서져 잦아드는 것과 같은 방향이라 물리적으로도 어긋나지 않는다.
  vCoast = coastAt(base.xz);
  float shore = smoothstep(0.0, uShoreFade, vCoast.x);

  vec3 disp = vec3(0.0);
  vec3 n = vec3(0.0, 1.0, 0.0);
  for (int i = 0; i < ${WAVE_COUNT}; i++) {
    vec2 d = uWave[i].xy;
    float k = uWave[i].w;
    // 파장이 두 칸보다 짧아지면(k·cell > π) 진폭을 0으로 접는다. 잃은 기울기는
    // 프래그먼트의 거칠기가 통계로 받는다 — 그래서 멀리서도 윤슬이 회색으로 안 죽는다.
    float nyq = 1.0 - smoothstep(1.4, 3.14159265, k * cell);
    float A = uWave[i].z * nyq * shore;
    float Q = uWaveQ[i].x;
    float w = uWaveQ[i].y;
    float ph = k * dot(d, base.xz) - w * uTime;
    float S = sin(ph);
    float C = cos(ph);
    disp.x += Q * A * d.x * C;
    disp.z += Q * A * d.y * C;
    disp.y += A * S;
    // GPU Gems 1 §1의 해석 법선 — 변위와 같은 항에서 나오므로 따로 어긋나지 않는다.
    n.x -= d.x * k * A * C;
    n.z -= d.y * k * A * C;
    n.y -= Q * k * A * S;
  }

  vWorld = base + disp;
  vNormal = normalize(n);
  // **투영만 패스별 행렬로 한다.** 위치는 uGridInvViewProj에서 나왔으므로 두 패스가 같다.
  gl_Position = projectionMatrix * viewMatrix * vec4(vWorld, 1.0);
}
`;

/** 조각 셰이더 — 프레넬로 하늘과 물속을 섞고, 태양은 마이크로패싯으로 받는다.
 *
 * `ATMOSPHERE_GLSL` · `NOISE_GLSL` · `cloudGlsl(...)`을 앞에 붙여야 한다(하늘과 **같은
 * 함수**를 읽어야 반사색이 갈리지 않는다). `scene/ocean.ts`가 이어 붙인다. */
export const OCEAN_FRAG = /* glsl */`
uniform vec3 uCamPos;
uniform float uRoughness;      // √(콕스-먼크 σ²)
uniform float uWaveHeight;     // 유의파고 [m] — 마루를 밝히는 데 쓴다
uniform vec3 uDeepColor;
uniform vec3 uScatterColor;
uniform vec3 uShallowColor;
uniform float uGlitterGain;
uniform float uFoamAmount;
uniform float uSpecAA;         // 법선 분산 → 거칠기 변환 계수
uniform float uRipple;         // 잔물결 기울기 세기 — 풍속에서 나온다
uniform vec2 uWindDir;         // 바람이 가는 방향 (렌더 x·z 평면 단위벡터)
uniform float uTime;

/** 잔물결의 기울기 (∂y/∂x, ∂y/∂z).
 *
 *  격자가 못 푸는 4 m 아래 파다. 정점을 못 움직이므로 **법선만** 흔든다.
 *
 *  **사인 합에서 노이즈로 바꿨다.** 처음에는 방향이 다른 사인 넷을 더했는데, 방향을
 *  아무리 흩고 위상을 휘어도 간섭이 규칙적인 짜임을 만들었다(실측 — 근거리 해면이
 *  모눈종이처럼 보였다). 사인 합은 주기적이므로 피할 수 없는 성질이다.
 *
 *  **옥타브마다 픽셀 발자국으로 접는다.** px는 이 픽셀이 덮는 세계 거리다. 파장이 그보다
 *  짧아지면 그리는 순간 에일리어싱이고, 거리로 한꺼번에 접으면 가까운 큰 잔물결까지
 *  같이 죽는다. 접은 몫의 기울기 분산은 lostVar로 내보내 **거칠기가 이어받는다** —
 *  에너지가 사라지지 않으므로 멀어져도 윤슬이 회색으로 죽지 않는다.
 *
 *  흐름은 바람 방향으로 밀어 준다. 심해 분산관계를 이 규모까지 끌고 가지는 않았다 —
 *  1 m 이하는 표면장력이 지배해 식이 달라지고, 화면에서 구별되지 않는다. 표시용이다. */
vec2 rippleSlope(vec2 p, vec2 windDir, float t, float px, out float lostVar) {
  vec2 g = vec2(0.0);
  lostVar = 0.0;
  float L = 4.3;
  // 기울기 진폭. 네 옥타브를 합친 RMS 기울기가 0.1 안팎이 되도록 잡았다 — 풍속 9 m/s의
  // 콕스-먼크 전체 경사 RMS가 0.22이므로 절반쯤을 기하로 들고 나머지는 거칠기가 받는다.
  float amp = 0.16;
  for (int i = 0; i < 4; i++) {
    // 파장이 픽셀의 1.3배 아래로 내려가면 다 접힌다.
    float lod = 1.0 - smoothstep(0.55, 1.3, px / L);
    vec2 q = (p - windDir * (t * (0.9 + 0.55 * float(i)))) / L;
    vec2 d = gnoise2(q).yz / L;
    g += d * (amp * L * lod);
    // 옥타브 하나의 기울기 분산 어림 — 접힌 몫만 거칠기로 넘긴다.
    float dropped = amp * (1.0 - lod);
    lostVar += 0.5 * dropped * dropped;
    L *= 0.47;
    amp *= 0.8;
  }
  return g;
}

varying vec3 vWorld;
varying vec3 vNormal;
varying float vDist;
varying vec2 vCoast;

/** GGX 법선분포 — α는 콕스-먼크 경사분산의 제곱근이다(베크만 경사분산 = α²). */
float ggxD(float NoH, float a2) {
  float d = NoH * NoH * (a2 - 1.0) + 1.0;
  return a2 / (3.14159265 * d * d);
}

/** 스미스 높이상관 가시성항 — 분모의 4·NoL·NoV까지 품는다. */
float ggxV(float NoV, float NoL, float a2) {
  float gv = NoL * sqrt(NoV * NoV * (1.0 - a2) + a2);
  float gl = NoV * sqrt(NoL * NoL * (1.0 - a2) + a2);
  return 0.5 / max(gv + gl, 1.0e-5);
}

void main() {
  // **뭍 위에는 해면이 없다.** 자료가 없는 칸도 마찬가지다 — 지형 구멍으로 바다가 비치면
  // 그건 구멍이 아니라 호수로 읽힌다(core/coastfield.ts). 문턱을 뭍 쪽으로 120 m 밀어
  // 두는 이유는 거리장이 39 m/칸이라 해안선을 이 격자로 그릴 수 없기 때문이다.
  if (vCoast.y < 0.5 || vCoast.x < -120.0) discard;

  vec3 toEye = uCamPos - vWorld;
  float dist = length(toEye);
  vec3 V = toEye / max(dist, 1.0e-4);
  // **기하 스페큘러 안티에일리어싱 — 게르스트너 법선에만 건다.**
  //
  // 한 픽셀 안에서 법선이 많이 흔들리면, 옳은 답은 그 흔들림 위에서 **평균 낸** 반사다.
  // 법선 하나로 계산하면 픽셀마다 튀어 지글거리고, 밉맵처럼 법선을 뭉개기만 하면 이번엔
  // 윤슬이 회색 죽으로 죽는다. 그래서 분산을 **거칠기로 옮긴다**(Kaplanyan/Tokuyoshi 계열).
  //
  // **잔물결을 더하기 전에 잰다.** 섞어서 재면 잔물결의 분산까지 "에일리어싱"으로 읽혀
  // 해면이 통째로 눕는다 — 그렇게 만들어 보니 바다가 무늬 없는 판이 됐다. 잔물결은 이미
  // 픽셀 발자국으로 대역제한돼 있어서 여기서 다시 벌줄 이유가 없다.
  vec3 Ng = normalize(vNormal);
  vec3 dNx = dFdx(Ng);
  vec3 dNy = dFdy(Ng);
  float varN = dot(dNx, dNx) + dot(dNy, dNy);
  // 하늘 반사도 같은 이유로 튄다. 법선을 그만큼 눕혀 반사 방향을 안정시킨다.
  vec3 N = normalize(mix(Ng, vec3(0.0, 1.0, 0.0), clamp(varN * uSpecAA * 0.6, 0.0, 0.6)));

  // 잔물결 — 격자 아래 4 m 파를 법선으로만 되돌린다.
  // px는 이 픽셀이 덮는 세계 거리. 스치는 각에서 커지므로 수평선 쪽이 저절로 접힌다.
  float px = max(length(fwidth(vWorld.xz)), 1.0e-4);
  float lostVar = 0.0;
  vec2 g = rippleSlope(vWorld.xz, uWindDir, uTime, px, lostVar) * uRipple;
  N = normalize(N + vec3(-g.x, 0.0, -g.y));

  // 접힌 잔물결의 분산 + 기하 법선의 흔들림. 둘 다 거칠기가 이어받는다.
  float widen = clamp(varN * uSpecAA + lostVar * uRipple * uRipple * 2.0, 0.0, 0.35);
  // 스치는 각에서 먼 파도의 뒷면이 보일 수 있다. 뒤집힌 법선을 그대로 쓰면 검은 얼룩이
  // 되므로 시선 쪽으로 눕힌다 — 표시용 완화다.
  float NoV = dot(N, V);
  if (NoV < 0.02) {
    N = normalize(N + V * (0.02 - NoV) * 1.05);
    NoV = max(dot(N, V), 0.02);
  }

  // 프레넬 — 물 n = 1.33 → F0 = ((1.33−1)/(1.33+1))² = 0.020
  float F = 0.02 + 0.98 * pow(1.0 - NoV, 5.0);

  // 하늘 반사. 지평 아래로 반사되면(파도 뒷면) 지평선 값을 읽는다 —
  // 실제로 그 방향에 있는 것도 먼바다와 수평선 안개다.
  vec3 R = reflect(-V, N);
  R.y = max(R.y, 0.01);
  vec3 sky = skyRadiance(R, uSunDirWorld, uSunIntensity, uHaze);
  // 구름도 비친다 — 하늘과 같은 함수를 거친 적분으로 부른다(scene/ocean.ts가 걸음 수를 정한다).
  // 반사 광선은 수면에서 출발한다.
  vec4 cl = cloudLayer(vWorld, R, uSunDirWorld, uSunIntensity, uHaze);
  sky = sky * cl.a + cl.rgb;

  // 물속에서 되나오는 빛 — 마루에서 밝다(빛이 얇은 곳을 지난다).
  float lift = clamp(vWorld.y / max(uWaveHeight, 0.05) * 0.5 + 0.5, 0.0, 1.0);
  // 얕은 물은 바닥에서 되비쳐 밝고 푸르다. **수심 자료가 없으므로 해안 거리를 대신 쓴다** —
  // 표시용 대리값이다(terrarium 타일에 수심이 없다: core/seamask.ts).
  vec3 deep = mix(uShallowColor, uDeepColor, smoothstep(0.0, 900.0, vCoast.x));
  vec3 body = deep + uScatterColor * lift * max(uSunDirWorld.y, 0.0);

  vec3 color = mix(body, sky, F);

  // 태양 정반사 — 윤슬. 폭은 uRoughness가 정하고, 그 값은 풍속에서 나온다.
  vec3 sunCol = sunThroughAtmosphere(uSunDirWorld, uSunIntensity, uHaze);
  vec3 L = uSunDirWorld;
  float NoL = max(dot(N, L), 0.0);
  if (NoL > 0.0) {
    vec3 H = normalize(L + V);
    float NoH = max(dot(N, H), 0.0);
    float a2 = clamp(uRoughness * uRoughness + widen, 1.0e-5, 1.0);
    color += ggxD(NoH, a2) * ggxV(NoV, NoL, a2) * F * NoL * sunCol * uGlitterGain;
  }

  // 포말 — 마루와 해안선. 흰 거품은 거의 램버시안이라 하늘빛을 고루 받는다.
  float crest = smoothstep(0.62, 0.95, lift) * uFoamAmount;
  float surf = smoothstep(90.0, 0.0, vCoast.x) * step(0.0, vCoast.x);
  float foam = clamp(crest + surf * 0.8, 0.0, 1.0);
  vec3 foamLit = (sunCol * max(uSunDirWorld.y, 0.0)
                  + skyRadiance(vec3(0.0, 1.0, 0.0), uSunDirWorld, uSunIntensity, uHaze)) * 0.28;
  color = mix(color, foamLit, foam);

  // 대기 — 지형·하늘과 **같은 함수**다.
  vec3 T, S;
  atmosphere(-V, uSunDirWorld, uSunIntensity, uHaze, dist, T, S);
  gl_FragColor = vec4(color * T + S, 1.0);
}
`;
