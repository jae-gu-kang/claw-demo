/** 대기 산란 — **하늘과 에어리얼 퍼스펙티브가 같은 함수를 읽는다.**
 *
 * ## 왜 `FogExp2`를 걷어냈나
 *
 * `FogExp2`는 거리에 따라 한 가지 색으로 **덮기만** 한다. 기본 시정 25 km에서
 * `ρ = 1.978/25000`이므로 30 km 지점의 투과율은
 *
 *     exp(−(30000 × 7.912e-5)²) = exp(−5.63) ≈ 0.0036
 *
 * 즉 **0.36%** 만 남는다. 수평선의 윤슬이 그 자리에서 지워진다 — 이 화면에서 가장
 * 보고 싶은 것이 안개에 통째로 먹히는 구조였다(사용자 최우선 요구와 정면 충돌).
 *
 * 단일산란 근사는 반대로 움직인다. 태양 쪽을 보면 **in-scattering이 밝아져** 먼 것이
 * 어두워지는 대신 빛나고, 태양 반대쪽에서만 푸르게 가라앉는다. 안개가 윤슬을 지우는
 * 것이 아니라 거든다.
 *
 * ## 모델
 *
 * 레일리 + 미 단일산란을 닫힌 형태로 적분한다.
 *
 *     T = exp(−(τR + τM))                              투과율
 *     L = (τR·pR(θ) + τM·pM(θ)) / (τR + τM) · E(h☉) · (1 − T)
 *
 * `θ`는 시선과 태양 방향의 각, `τ`는 광학두께다. 원경은 `τ = β·s`로 시선을 따라 밀도가
 * 일정하다고 본다(카메라가 경계층 안이라는 전제). 하늘은 척도고도로 세운 수직 기둥이고,
 * **레일리 8 km · 에어로졸 1.2 km로 서로 다르다** — 한 값으로 묶으면 시정 25 km의
 * 에어로졸이 8 km 기둥에 퍼져 천정까지 뿌예진다(실측으로 확인하고 고쳤다).
 *
 * `(1 − T)`가 in-scattering의 누적이고, 나눗셈은 소산 대비 산란 비율이라 광학두께가
 * 커질수록 하늘색으로 수렴한다 — **그래서 먼 지형이 저절로 그 방향의 하늘색이 된다.**
 * `FogExp2`가 `fog.color = horizon`을 손으로 맞추던 일이 여기서는 필요 없어진다.
 *
 * ## `E(h☉)` — 태양도 같은 대기를 지나 온다
 *
 * 태양 복사조도를 상수로 두면 **지평의 해가 정오만큼 밝다.** 실제로 그렇게 만들어 보니
 * 고도 5.7°에서 전방산란 아우레올이 화면을 통째로 하얗게 태웠다. 태양 자신의 경로
 * 감쇠를 넣으면 반대로 움직인다 — 해가 낮을수록 어둡고 붉어지고, 노을이 거기서 나온다.
 * 이 값은 CPU에도 필요하다(`sunColorRgb`): 직사광이 같은 색을 써야 하늘만 노을이고
 * 지형은 한낮 조명인 화면이 안 된다.
 *
 * ## 물리 모델인가
 *
 * **아니다 — 표시용이다.** 오존 없음, 다중산란 없음, 지구 곡률 없음(지평 부근은
 * 평면-평행 근사가 발산하므로 `MU_MIN`으로 바닥을 깐다). 계수는 해수면 표준값에서
 * 왔고 시정 슬라이더가 미 산란 계수를 곱한다. 캡션이 그렇게 말한다. 다만 옛 하늘
 * (순수 그라디언트)보다는 훨씬 덜 지어낸다 — 시간대가 보간이 아니라 감쇠에서 나온다.
 */

/** 산란 계수 — **GLSL과 TS가 이 한 벌을 나눠 쓴다.**
 *
 * 태양색은 셰이더(하늘·원경)와 CPU(직사광 `DirectionalLight.color`) 양쪽에서 필요한데,
 * 두 벌로 적으면 한쪽만 고쳐져 **하늘은 노을인데 지형은 한낮 조명**이 되는, 화면에서
 * 원인이 안 보이는 어긋남이 난다. 그래서 여기서 상수를 만들고 GLSL 문자열에 박아 넣는다. */
export const BETA_R = [5.8e-6, 13.5e-6, 33.1e-6] as const; // 680·550·440 nm [1/m]
export const BETA_M = 21e-6;                               // 해수면 에어로졸 [1/m]
export const MIE_G = 0.76;
/** 척도고도 [m] — 레일리는 대기 자체(8 km), 에어로졸은 경계층에 갇힌다(1.2 km). */
export const H_RAYLEIGH = 8000;
export const H_MIE = 1200;
/** 대기 밖 태양의 상대 분광 — 표시용 틴트. */
export const SUN_TINT = [1.0, 0.95, 0.88] as const;

/** 대기 함수가 전제하는 유니폼 선언 — 하늘·해면·(재질 패치)가 **같은 세 줄**을 쓴다.
 *
 * `ATMOSPHERE_GLSL`은 이 값들을 함수 인자로만 받으므로 선언은 부르는 쪽 몫이다. 세 벌로
 * 적으면 이름 하나를 고칠 때 한 곳이 남는데, 그러면 그 셰이더만 컴파일이 깨지거나
 * (운이 나쁘면) 0으로 읽는다. `scene/atmosphere.ts`의 `atmosphereUniforms`와 **짝이다**. */
export const ATMOSPHERE_UNIFORM_DECL = /* glsl */`
uniform vec3 uSunDirWorld;
uniform float uSunIntensity;
uniform float uHaze;
`;

/** GLSL 실수 리터럴 — 소수점을 **반드시** 남긴다.
 *
 * `String(1.0)`은 `"1"`이 되는데 GLSL에서 그건 정수 리터럴이라, `vec3(1, 0.95, 0.88)`
 * 처럼 섞이면 엄격한 드라이버에서 컴파일이 깨진다. 셰이더 컴파일 실패는 화면이 통째로
 * 검게 나오는 부류라 원인이 안 보인다. */
const glsl = (x: number): string => (Number.isInteger(x) ? x.toFixed(1) : String(x));

/** 두 셰이더가 함께 include하는 본문. `uSunDirWorld`·`uSunIntensity`·`uHaze`를 전제한다. */
export const ATMOSPHERE_GLSL = /* glsl */`
const vec3 BETA_R = vec3(${BETA_R.map(glsl).join(", ")});
const float BETA_M = ${glsl(BETA_M)};
const float MIE_G = ${glsl(MIE_G)};
const float H_R = ${glsl(H_RAYLEIGH)};
const float H_M = ${glsl(H_MIE)};
const vec3 SUN_TINT = vec3(${SUN_TINT.map(glsl).join(", ")});
// 태양 고도가 0에 닿아도 경로가 발산하지 않게 — 평면-평행 근사에 곡률 대신 깐 바닥.
const float MU_MIN = 0.02;

// 레일리 위상함수 — 앞뒤 대칭, 옆이 어둡다
float phaseRayleigh(float c) {
  return (3.0 / (16.0 * 3.14159265)) * (1.0 + c * c);
}

// 헤니-그린슈타인 — g가 클수록 전방으로 몰린다(그래서 태양 쪽이 밝아진다)
float phaseMie(float c, float g) {
  float g2 = g * g;
  float d = 1.0 + g2 - 2.0 * g * c;
  return (1.0 / (4.0 * 3.14159265)) * ((1.0 - g2) / max(d * sqrt(d), 1e-4));
}

/** 대기를 지나 온 태양색.
 *
 *  **이것이 빠져 있으면 지평의 태양이 정오만큼 밝다** — 실제로 그렇게 만들어 보니
 *  낮은 해에서 전방산란 아우레올이 화면을 통째로 하얗게 태웠다. 태양 자신도 같은
 *  대기를 지나 오므로, 고도가 낮을수록 긴 경로를 지나 **어두워지고 붉어진다.**
 *  노을이 여기서 나온다. */
vec3 sunThroughAtmosphere(vec3 sunDir, float sunIntensity, float haze) {
  float mu = max(sunDir.y, MU_MIN);
  vec3 tau = BETA_R * (H_R / mu) + vec3(BETA_M * haze * (H_M / mu));
  return SUN_TINT * sunIntensity * exp(-tau);
}

/** 광학두께를 직접 받는 본체 — 레일리와 미가 **다른 거리**를 지날 수 있다.
 *
 *  하늘에서 그 둘이 갈린다: 레일리는 척도고도 8 km인데 에어로졸은 1.2 km다. 한 거리로
 *  묶으면 시정 25 km에 해당하는 에어로졸을 8 km 기둥 전체에 퍼뜨리게 되어 **천정까지
 *  뿌예진다** — 파랗지 않은 한낮 하늘이 나온다(실측으로 확인하고 고친 자리). 원경은
 *  카메라가 경계층 안이라 둘이 같다.
 *
 *  c는 시선과 태양 방향의 코사인, sunCol은 이미 대기를 지나 온 태양색이다.
 *  (이 주석은 템플릿 리터럴 안이라 백틱을 못 쓴다.) */
void atmosphereOD(float c, vec3 tauR, vec3 tauM, vec3 sunCol,
                  out vec3 transmittance, out vec3 inscatter) {
  vec3 tau = tauR + tauM;
  transmittance = exp(-tau);

  // 산란 **광학두께**에 위상함수를 곱한다 — 두 거리가 같으면 β 비율과 똑같아진다.
  vec3 scatter = tauR * phaseRayleigh(c) + tauM * phaseMie(c, MIE_G);
  // 소산 대비 산란 비율 — 광학두께가 커질수록 하늘색으로 수렴한다
  vec3 ratio = scatter / max(tau, vec3(1e-9));
  // 위상함수는 1/sr 단위라 4π를 곱해 무차원 비율로 되돌린다
  inscatter = ratio * (sunCol * 4.0 * 3.14159265) * (1.0 - transmittance);
}

/** 거리 s를 지난 뒤의 투과율과 in-scattering — 밀도가 일정한 구간용(원경).
 *  haze는 미 산란 배수(시정 슬라이더). dir·sunDir은 정규화된 월드 방향. */
void atmosphere(vec3 dir, vec3 sunDir, float sunIntensity, float haze, float s,
                out vec3 transmittance, out vec3 inscatter) {
  atmosphereOD(dot(dir, sunDir), BETA_R * s, vec3(BETA_M * haze * s),
               sunThroughAtmosphere(sunDir, sunIntensity, haze),
               transmittance, inscatter);
}

/** 하늘 한 방향의 복사휘도 — 대기를 끝까지 본 극한. */
vec3 skyRadiance(vec3 dir, vec3 sunDir, float sunIntensity, float haze) {
  float mu = max(dir.y, MU_MIN);
  vec3 sunCol = sunThroughAtmosphere(sunDir, sunIntensity, haze);
  vec3 T, S;
  atmosphereOD(dot(dir, sunDir),
               BETA_R * (H_R / mu),
               vec3(BETA_M * haze * (H_M / mu)),
               sunCol, T, S);

  // 태양 원반 — 각반경 0.265°. 블룸이 이 값을 물어가므로 1.0을 크게 넘겨 둔다.
  // 원반을 볼 때의 시선 경로는 태양 경로와 같으므로 sunCol이 곧 감쇠분이다:
  // 해가 낮으면 원반이 저절로 어둡고 붉어진다.
  float disc = smoothstep(0.99997, 0.99999, dot(dir, sunDir));
  S += disc * sunCol * 60.0;

  return S;
}
`;

/** 대기를 지나 온 태양색 — 위 GLSL `sunThroughAtmosphere`와 **같은 식**이다.
 *
 * 직사광(`DirectionalLight.color`)에 쓴다. 이것을 안 맞추면 하늘만 노을이고 지형은
 * 한낮 조명인 화면이 된다. 상수를 공유하므로 계수가 갈릴 일은 없지만, 식 자체는 두
 * 곳에 있다 — 한쪽을 고치면 다른 쪽도 고쳐야 한다. */
export function sunColorRgb(sunElRad: number, haze: number): [number, number, number] {
  const mu = Math.max(Math.sin(sunElRad), 0.02);
  const out: number[] = [];
  for (let i = 0; i < 3; i++) {
    const tau = BETA_R[i]! * (H_RAYLEIGH / mu) + BETA_M * haze * (H_MIE / mu);
    out.push(SUN_TINT[i]! * Math.exp(-tau));
  }
  return [out[0]!, out[1]!, out[2]!];
}

/** 시정 [m] → 미 산란 배수.
 *
 * 케슈미더 관계 `V ≈ 3.912 / β_ext`를 미 산란에만 적용한다(레일리는 대기 자체라
 * 사람이 못 바꾼다). 슬라이더가 "얼마나 뿌연가"를 뜻하게 하는 표시용 사상이다. */
export function hazeForVisibility(visibilityM: number): number {
  const betaExt = 3.912 / Math.max(visibilityM, 100);
  return Math.max(betaExt / 21e-6, 0.05);
}
