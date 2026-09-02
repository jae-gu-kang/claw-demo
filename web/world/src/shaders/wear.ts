/** 절차 마모 — 텍스처 0장으로 모델 표면에 **역사**를 얹는다.
 *
 * GLB 재질은 색 하나·거칠기 하나뿐이고 UV도 없다. 그래서 전부 **로컬 좌표**에서 만든다:
 * 패널라인은 삼면 투영 격자, 오염·그을음·진흙은 3D 노이즈, 엣지웨어는 화면공간 곡률.
 * 로컬을 쓰는 이유는 스케일과 자세다 — 추적 시점은 기체를 8배로 그리는데 월드 좌표로
 * 노이즈를 뽑으면 그때마다 얼룩 크기가 바뀌고, 기체가 기울면 "중력 방향"도 돈다. 오염은
 * 지상에 세워 둔 동안 생긴 역사이므로 로컬 위쪽이 맞다.
 *
 * ## 세 겹의 거리 처리
 *
 * 전부 표시용이라 멀어지면 사라져야 한다 — 남으면 지글거린다.
 * - 패널라인은 폭을 픽셀 발자국(fwidth)으로 잡아 항상 1~2 px이고, 간격이 몇 px로
 *   줄면 지운다.
 * - 엣지웨어는 베벨보다 픽셀이 커지면 지운다 — 그때 곡률은 1 px 델타가 되어 깜빡인다.
 * - 오염은 노이즈라 밉맵이 없다. 멀어지면 평균으로 수렴하므로 그냥 둔다(눈에 안 띈다).
 *
 * ## 곡률은 화면에서 잰다
 *
 * 곡률 속성이 없으므로 |∂N/∂픽셀| / |∂P/∂픽셀| — 세계 단위 1/m — 을 쓴다. 매끈한 원통
 * 동체(반지름 0.15 m)는 7, 베벨(0.02 m)은 50이 나와 문턱 10~35로 갈린다. 칠이 벗겨져
 * 금속이 드러나는 자리가 딱 모서리다.
 *
 * ## 주입 자리
 *
 * `<metalnessmap_fragment>` 뒤 — diffuseColor · roughnessFactor · metalnessFactor 가 다
 * 정해진 직후, 조명 전. 패널라인의 홈은 `<normal_fragment_begin>` 뒤에서 뷰공간 법선을
 * 살짝 꺾어 만든다(노멀맵이 하는 것과 같은 자리).
 *
 * 이 파일은 `NOISE_GLSL`(fbm3)을 앞에 둔다. `scene/materials.ts`가 조립한다.
 */

export const WEAR_UNIFORM_DECL = /* glsl */`
uniform vec3 uWearPanel;        // 패널라인 간격 (x, y, z) [m] — 0이면 그 축은 없음
uniform float uWearPanelDepth;  // 0~1
uniform float uWearEdge;        // 0~1
uniform float uWearDirt;        // 0~1
uniform vec2 uWearSoot;         // 그을음: 로컬 z (시작, 끝). 끝 ≤ 시작이면 없음
uniform vec2 uWearMud;          // 진흙: 로컬 y (위, 아래). 위 ≤ 아래면 없음
uniform float uWearSeed;
`;

export const WEAR_VARYING_DECL = /* glsl */`
varying vec3 vWearLocal;
varying vec3 vWearNLocal;
varying vec3 vWearWorld;
varying vec3 vWearNWorld;
varying mat3 vWearL2V;
`;

/** 정점 — `<fog_vertex>` 뒤. transformed·objectNormal·normalMatrix가 그 자리에 있다.
 *  균일 스케일을 전제한다(기체는 MODEL_SCALE 배 균일, 발사관은 1). */
export const WEAR_VERT_BODY = /* glsl */`
  vWearLocal = transformed;
  vWearNLocal = objectNormal;
  vWearWorld = (modelMatrix * vec4(transformed, 1.0)).xyz;
  vWearNWorld = normalize(mat3(modelMatrix) * objectNormal);
  vWearL2V = normalMatrix;
`;

export const WEAR_GLSL = /* glsl */`
/** 한 축의 패널라인 — 0~1. grad는 홈의 법선 기울기 부호(선 중심을 향한다). */
float wearPanelLine(float c, float spacing, out float grad) {
  grad = 0.0;
  if (spacing <= 0.0) return 0.0;
  float fw = fwidth(c);
  float d = (fract(c / spacing + 0.5) - 0.5) * spacing;   // 가장 가까운 선까지 부호 거리 [m]
  float w = max(0.004, fw * 1.2);                           // 반폭 — 픽셀보다 좁아지지 않게
  float m = 1.0 - smoothstep(w * 0.5, w * 1.6, abs(d));
  // 간격이 픽셀 몇 개로 줄면 선이 무아레가 된다 — 지운다.
  m *= 1.0 - smoothstep(0.10, 0.28, fw / spacing);
  grad = -sign(d) * m;
  return m;
}

/** 마모를 한꺼번에 — 색·거칠기·금속성을 고치고, 법선을 꺾을 로컬 기울기를 낸다. */
void wearApply(inout vec3 albedo, inout float rough, inout float metal, out vec3 lineGradLocal) {
  vec3 p = vWearLocal;
  vec3 n = normalize(vWearNLocal);
  vec3 seed = vec3(uWearSeed * 7.31, uWearSeed * 3.17, uWearSeed * 5.53);

  // --- 패널라인: 삼면 투영 -------------------------------------------------
  vec3 w = pow(abs(n), vec3(4.0));
  w /= max(w.x + w.y + w.z, 1.0e-5);
  float gx, gy, gz;
  float lx = wearPanelLine(p.x, uWearPanel.x, gx);
  float ly = wearPanelLine(p.y, uWearPanel.y, gy);
  float lz = wearPanelLine(p.z, uWearPanel.z, gz);
  // 축 k 방향에서 본 면에는 나머지 두 축의 선이 그어진다.
  float line = w.y * max(lx, lz) + w.x * max(ly, lz) + w.z * max(lx, ly);
  line *= uWearPanelDepth;
  lineGradLocal = vec3(gx * (w.y + w.z), gy * (w.x + w.z), gz * (w.y + w.x)) * uWearPanelDepth;

  // --- 엣지웨어: 화면공간 곡률 ----------------------------------------------
  float pw = max(length(fwidth(vWearWorld)), 1.0e-5);
  float curv = length(fwidth(vWearNWorld)) / pw;
  float edge = smoothstep(10.0, 35.0, curv) * uWearEdge;
  edge *= 1.0 - smoothstep(0.012, 0.045, pw);                // 베벨보다 픽셀이 크면 지운다
  edge *= smoothstep(0.30, 0.62, fbm3(p * 46.0 + seed));      // 군데군데 벗겨진다

  // --- 오염: 세로 줄무늬 · 밑면 때 · 윗면 먼지 --------------------------------
  // 줄무늬는 로컬 위아래로 늘린 노이즈 — 옆면에서 흘러내린 자국.
  float streak = fbm3(vec3(p.x * 13.0, p.y * 2.6, p.z * 13.0) + seed);
  float side = 1.0 - abs(n.y);
  float under = max(-n.y, 0.0);
  float top = max(n.y, 0.0);
  float dirt = uWearDirt * (
      0.55 * side * smoothstep(0.38, 0.72, streak)
    + 0.40 * under * smoothstep(0.30, 0.60, fbm3(p * 19.0 + seed * 1.3))
    + 0.18 * top * fbm3(p * 31.0 + seed * 0.7));
  dirt = clamp(dirt, 0.0, 1.0);

  // --- 그을음: 배기 뒤 축방향 누적 -----------------------------------------
  float soot = 0.0;
  if (uWearSoot.y > uWearSoot.x) {
    soot = smoothstep(uWearSoot.x, uWearSoot.y, p.z) * (0.55 + 0.45 * fbm3(p * 9.0 + seed));
  }

  // --- 진흙: 아래로 갈수록 -------------------------------------------------
  float mud = 0.0;
  if (uWearMud.x > uWearMud.y) {
    mud = smoothstep(uWearMud.x, uWearMud.y, p.y) * (0.45 + 0.55 * fbm3(p * 6.5 + seed));
  }

  // --- 겹치는 순서: 홈 → 오염 → 그을음 → 진흙 → 마지막에 벗겨진 금속 ----------
  albedo *= 1.0 - line * 0.45;
  rough = mix(rough, 0.85, line * 0.6);

  albedo = mix(albedo, albedo * vec3(0.55, 0.50, 0.42), dirt);
  rough = mix(rough, 0.90, dirt * 0.6);

  albedo = mix(albedo, albedo * 0.22, soot);
  rough = mix(rough, 0.95, soot);

  albedo = mix(albedo, vec3(0.16, 0.12, 0.08), mud * 0.85);
  rough = mix(rough, 0.95, mud);

  albedo = mix(albedo, vec3(0.52, 0.53, 0.55), edge);
  metal = mix(metal, 0.85, edge);
  rough = mix(rough, 0.32, edge);
}
`;

/** 조각 — `<metalnessmap_fragment>` 뒤. */
export const WEAR_FRAG_BODY = /* glsl */`
  vec3 wearLineGrad;
  wearApply(diffuseColor.rgb, roughnessFactor, metalnessFactor, wearLineGrad);
`;

/** 조각 — `<normal_fragment_begin>` 뒤. 홈 방향으로 뷰공간 법선을 꺾는다. */
export const WEAR_NORMAL_BODY = /* glsl */`
  normal = normalize(normal + vWearL2V * (wearLineGrad * 0.35));
`;
