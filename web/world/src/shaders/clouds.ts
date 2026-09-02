/** 구름 — 하늘 셰이더 안에서 그리는 2.5D 절차 층운.
 *
 * ## 왜 지오메트리가 아니라 하늘 셰이더인가
 *
 * 구름을 별도 메시(빌보드·판)로 올리면 세 가지가 한꺼번에 온다: 반투명이라 분할 프러스텀의
 * 겹침 구간(1500~2000 m)에서 두 번 섞이고, 깊이 정렬을 해야 하고, 바다 반사에는 따로
 * 넣어 줘야 한다. 하늘 셰이더 안에서 시선을 따라 구름 슬래브를 짧게 적분하면 셋 다
 * 없다 — 하늘은 원거리 패스에서 한 번, 깊이 테스트로 **가려진 곳은 아예 안 그리고**,
 * 바다는 반사 방향으로 같은 함수를 부른다.
 *
 * 대가는 카메라가 구름 **속**이나 **위**를 날 때 구름이 언제나 배경이라는 것이다. 이 데모의
 * 최고 고도는 205 m이고 구름 밑면은 1500 m라 그 경우가 없다. 볼류메트릭은 계획 §5가
 * 성능 예산이 남을 때의 상위 단계로 둔 그것이다.
 *
 * ## 모델 — 표시용이다
 *
 * 밑면 uCloudBase, 두께 uCloudThick의 구 껍질 슬래브. 밀도는 2D fBm의 덮임(coverage)에
 * 수직 프로파일(밑은 평평, 위는 노이즈로 울퉁불퉁)을 곱하고 가장자리를 세부 노이즈로
 * 깎는다. 조명은 태양 방향으로 몇 걸음 적분한 투과율 × 두 갈래 헤니-그린슈타인 위상
 * (전방 0.55, 후방 −0.35) + 천정 하늘빛 환경광. 다중산란·지면 그림자 없음. 실제 기상이
 * 아니며 캡션이 그렇게 말한다(`CLOUD_NOTES`).
 *
 * ## 지평선은 구로 푼다
 *
 * 하늘·원경은 평면-평행 근사에 MU_MIN 바닥을 깔았지만, 구름 슬래브를 평면으로 두면
 * 지평선 근처 경로가 발산해 구름이 지평선에 띠로 뭉친다. 지구 반지름의 구 껍질과
 * 교점을 구하면 그 경로가 √(2Rh)로 유한해진다 — 제곱근 하나 값이다.
 *
 * ## 이 파일은 함수 **공장**이다
 *
 * 하늘은 STEPS=10·LSTEPS=3으로, 바다 반사는 STEPS=3·LSTEPS=1로 같은 코드를 쓴다.
 * 반사는 파도에 이미 흐트러져 있어 거친 적분으로 충분하고, 바다 픽셀은 화면의 절반이라
 * 비용이 그대로 프레임에 실린다.
 */

/** 구름 유니폼 — `scene/atmosphere.ts`의 `cloudUniforms`와 짝이다. */
export const CLOUD_UNIFORM_DECL = /* glsl */`
#ifndef CLOUD_UNIFORM_DECL_G
#define CLOUD_UNIFORM_DECL_G
uniform float uCloudCover;    // 덮임 0~1 (표시 값)
uniform float uCloudBase;     // 밑면 고도 [m]
uniform float uCloudThick;    // 두께 [m]
uniform vec2 uCloudWind;      // 흐름 [m/s] (렌더 x·z)
uniform float uCloudTime;     // [s] — 시뮬 시각
uniform float uCloudGain;     // 표시 보정 — 이 렌더러의 절대 밝기는 물리 단위가 아니다
#endif
`;

/** 구름 덮임·그림자 — 하늘 적분과 지면 그림자가 **같은 덮임 함수**를 읽는다.
 *
 * NOISE_GLSL(fbm2)과 CLOUD_UNIFORM_DECL을 앞에 붙여야 한다. 그림자를 별도 노이즈로
 * 만들면 구름과 그림자가 서로 다른 자리에 앉는다 — 하늘을 보고 그림자를 확인하는
 * 시선을 화면이 배신하게 된다. */
export const CLOUD_COVER_GLSL = /* glsl */`
/** 한 지점(수평 xz)의 구름 덮임 0~1 — 밀도의 2D 뼈대. */
float cloudCoverAt(vec2 xz) {
  vec2 q = (xz + uCloudWind * uCloudTime) * (1.0 / 2600.0);
  float shape = fbm2(q, 4) * 0.5 + 0.5;
  float th = 1.0 - uCloudCover;
  return smoothstep(th - 0.08, th + 0.24, shape);
}

/** 월드 한 점에 드리우는 구름 그림자 0(그늘)~1(맑음).
 *
 *  점에서 태양 쪽으로 올라가 구름 밑면과 만나는 자리의 덮임을 읽는다 — 적분이 아니라
 *  한 표본이라 반그림자는 덮임 경사가 대신한다(표시용 근사). 해가 지평에 붙으면 직사광
 *  자체가 없으므로 그림자도 같이 걷는다. */
float cloudShadowAt(vec3 p, vec3 sunDir) {
  if (uCloudCover <= 0.001) return 1.0;
  float up = max(sunDir.y, 0.08);
  vec2 hit = p.xz + sunDir.xz * ((uCloudBase - p.y) / up);
  float cover = cloudCoverAt(hit);
  // 그늘 바닥 0.45 — 실제 구름 그늘도 하늘빛 산란광은 받는다. 우리 근사는 알베도를
  // 통째로 줄여 주변광까지 어두워지므로, 바닥을 두어 그 과장을 되돌린다.
  float strength = smoothstep(0.05, 0.35, sunDir.y);
  return 1.0 - (1.0 - 0.45) * cover * strength;
}
`;

/** `ATMOSPHERE_GLSL`·`NOISE_GLSL`·`CLOUD_COVER_GLSL`을 앞에 붙여야 한다. */
export function cloudGlsl(steps: number, lightSteps: number): string {
  const S = Math.max(1, Math.round(steps));
  const LS = Math.max(1, Math.round(lightSteps));
  return /* glsl */`
const float CLOUD_EARTH_R = 6371000.0;
const float CLOUD_SIGMA = 0.02;     // 소산계수 [1/m] — 두께 600 m에서 광학두께 12

/** 카메라(고도 camY)에서 방향 d로 반지름 R+alt 구 껍질까지의 두 교점 거리. 없으면 false. */
bool cloudShell(float camY, vec3 d, float alt, out float tNear, out float tFar) {
  float oy = CLOUD_EARTH_R + camY;
  float b = oy * d.y;
  float r = CLOUD_EARTH_R + alt;
  float c = oy * oy - r * r;
  float disc = b * b - c;
  if (disc < 0.0) { tNear = -1.0; tFar = -1.0; return false; }
  float s = sqrt(disc);
  tNear = -b - s;
  tFar = -b + s;
  return true;
}

/** 슬래브 안의 적분 구간 [t0, t1]. 구간이 없으면 false. */
bool cloudSpan(float camY, vec3 d, out float t0, out float t1) {
  float base = uCloudBase;
  float top = uCloudBase + uCloudThick;
  float bN, bF, tN, tF;
  bool hitB = cloudShell(camY, d, base, bN, bF);
  bool hitT = cloudShell(camY, d, top, tN, tF);
  if (camY < base) {
    // 아래에서 본다 — 지평 아래로 향하는 시선은 지면이 가린다(평평한 지형이 50 km까지).
    if (d.y < -0.005 || !hitT) return false;
    t0 = max(bF, 0.0);
    t1 = tF;
  } else if (camY > top) {
    // 위에서 본다 — 내려가는 시선만 만난다.
    if (d.y >= 0.0 || !hitT || tN <= 0.0) return false;
    t0 = tN;
    t1 = (hitB && bN > 0.0) ? bN : tF;
  } else {
    // 슬래브 안 — 여기서 시작한다.
    t0 = 0.0;
    t1 = (d.y >= 0.0) ? tF : ((hitB && bN > 0.0) ? bN : tF);
  }
  return t1 > t0;
}

/** 한 점의 구름 밀도 0~1. 2D 뼈대는 cloudCoverAt — 지면 그림자와 같은 함수다. */
float cloudDensity(vec3 p, vec2 drift) {
  float hN = clamp((p.y - uCloudBase) / uCloudThick, 0.0, 1.0);
  float cov = cloudCoverAt(p.xz);
  if (cov <= 0.001) return 0.0;
  // 수직 프로파일 — 밑은 평평하게 잘리고, 윗면은 덮임이 짙을수록 높이 솟는다.
  float top = 0.30 + 0.70 * cov;
  float prof = smoothstep(0.0, 0.10, hN) * (1.0 - smoothstep(top - 0.30, top, hN));
  float dens = cov * prof;
  if (dens <= 0.002) return 0.0;
  // 가장자리 침식 — 얇은 곳부터 깎여 뭉게구름의 너덜너덜한 윤곽이 된다.
  float det = fbm2((p.xz + drift * 1.4) * (1.0 / 420.0) + hN * 0.9, 3) * 0.5 + 0.5;
  return clamp(dens - (1.0 - det) * 0.55 * (1.0 - dens), 0.0, 1.0);
}

/** 구름 위상 — 두 갈래 HG. 4π를 곱해 무차원(방향 평균 1)으로 둔다. */
float cloudPhase(float c) {
  return 4.0 * 3.14159265 * (0.65 * phaseMie(c, 0.55) + 0.35 * phaseMie(c, -0.35));
}

/** 시선 하나의 구름 — rgb는 복사휘도(대기 감쇠·in-scatter 포함), a는 투과율.
 *  camPos는 월드, dir·sunDir은 정규화. 구름이 없으면 (0,0,0,1). */
vec4 cloudLayer(vec3 camPos, vec3 dir, vec3 sunDir, float sunIntensity, float haze) {
  float t0, t1;
  if (uCloudCover <= 0.001 || !cloudSpan(camPos.y, dir, t0, t1)) return vec4(0.0, 0.0, 0.0, 1.0);
  // 스치는 시선은 슬래브를 아주 길게 지난다. 너무 길면 표본이 성겨져 **구름이 층층이
  // 썬 것처럼** 보이고(14배·10걸음에서 실측), 지평선이 통째로 덮인다. 두께의 8배에서
  // 자른다 — 그 너머는 어차피 대기가 지운다.
  t1 = min(t1, t0 + uCloudThick * 8.0);

  vec2 drift = uCloudWind * uCloudTime;
  vec3 sunCol = sunThroughAtmosphere(sunDir, sunIntensity, haze);
  // 환경광 — 천정 하늘빛. 밑면은 그늘이라 절반, 윗면은 그대로.
  vec3 skyUp = skyRadiance(vec3(0.0, 1.0, 0.0), sunDir, sunIntensity, haze);
  float ph = cloudPhase(dot(dir, sunDir));

  float T = 1.0;
  vec3 L = vec3(0.0);
  float dt = (t1 - t0) / float(${S});
  float lstep = uCloudThick * 0.7 / float(${LS});
  // 시작점을 픽셀마다 한 걸음 안에서 흔든다 — 남는 줄무늬가 결이 고운 잡음이 된다.
  // 시선 방향의 해시라 화면 좌표가 없어도 픽셀마다 다르다.
  float jitter = hash2(dir.xy * 4096.0 + dir.zz * 1731.0).x * 0.5 + 0.5;
  for (int i = 0; i < ${S}; i++) {
    float t = t0 + (float(i) + jitter) * dt;
    vec3 p = camPos + dir * t;
    float rho = cloudDensity(p, drift);
    if (rho <= 0.002) continue;
    // 태양 쪽 광학두께 — 몇 걸음이면 밑면이 어둡고 윗면이 밝은 것은 나온다.
    float od = 0.0;
    for (int j = 0; j < ${LS}; j++) {
      od += cloudDensity(p + sunDir * ((float(j) + 0.6) * lstep), drift) * lstep;
    }
    float Ts = exp(-CLOUD_SIGMA * od);
    float hN = clamp((p.y - uCloudBase) / uCloudThick, 0.0, 1.0);
    vec3 direct = sunCol * Ts * ph;
    vec3 amb = skyUp * mix(0.45, 1.0, hN);
    // 이 구간이 산란해 내는 몫(알베도 ≈ 1). 앞에서 뒤로 쌓는다.
    float a = 1.0 - exp(-CLOUD_SIGMA * rho * dt);
    L += (direct + amb) * a * T;
    T *= 1.0 - a;
    if (T < 0.02) break;
  }
  if (T > 0.999) return vec4(0.0, 0.0, 0.0, 1.0);

  // 대기 — 구름까지의 거리로. 지형·하늘·바다와 같은 함수다.
  vec3 Ta, Sa;
  atmosphere(dir, sunDir, sunIntensity, haze, t0, Ta, Sa);
  return vec4(L * uCloudGain * Ta + Sa * (1.0 - T), T);
}
`;
}
