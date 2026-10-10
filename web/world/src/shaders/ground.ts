/** 지면 재질 — **지표 피복**(논밭·숲·마을·갯벌·암반)과 **지형 자체 그림자**. 텍스처 0장.
 *
 * ## 무엇을 고쳤나
 *
 * 예전에는 고도 램프(0 m 모래색 → 초록 → 회갈) 위에 얼룩을 얹었다. 그 램프가 저지대를 통째로
 * 모래색으로 칠해 실제로는 논과 마을인 고흥 간척지가 사막처럼 보였고, 산은 고도로만 색이 정해져
 * 숲인데도 회갈색 찰흙으로 읽혔다(사용자 지적 「실사와 비슷하게」). 남해안의 항공사진에서 땅의
 * 색을 정하는 것은 고도가 아니라 **꼴**이다 — 평평하고 낮으면 논, 기울면 숲, 물가는 갯벌. 그래서
 * 고도 램프를 버리고 꼴로 피복을 판정한다:
 *
 *     갯벌    물가 150 m 안, 표고 2.5 m 아래, 평평 — 젖은 회갈, 하늘을 비춘다, 갯골
 *     논밭    경사 약 6° 아래, 낮은 곳(골 바닥은 더 높이까지) — 블록·필지·둑·농로·비닐하우스
 *     마을    산자락(경사가 막 오르는 띠)의 군집 — 집터마다 지붕 색
 *     암반    가파르거나(약 40° 위) 볼록한 봉우리
 *     숲      나머지 — 침엽·활엽 섞임, 높은 곳 활엽의 가을 기운, 수관 얼룩, 가까이선 나무 하나하나
 *     비행장  폭을 아는 활주로 둘레의 착륙대(펴진 바닥과 같은 구역) — 깎은 풀, 포장면·과주로, 도색(ICAO
 *             부속서 14의 표준 배치: 시단 줄무늬·번호·중심선 점선·측면 표지·조준점, 과주로 노란 갈매기표)
 *
 * 전부 **표시용**이고 실제 지표 피복이 아니다. 위성 영상이 정답이지만 반입·라이선스 문제라 그
 * 전까지 이것이 메운다 — 캡션이 말한다(scene/terrain.ts).
 *
 * ## 고도 원장의 바다 턱
 *
 * 원자료는 해안 둘레 바다에 0~8 m의 블록 모양 값을 싣고 있다(얕은 바다를 거친 표고로 메운 흔적).
 * 해수면 판정(core/seamask.ts)은 이것을 뭍으로 남기므로 예전 화면에서는 해안마다 모래색 계단
 * 턱이 바다로 튀어나왔다. 표고를 깎으면 활주로가 있는 0 m 간척지까지 잠긴다(seamask 머리말) —
 * 그래서 **꼴은 그대로 두고 갯벌로 칠한다.** 실제로 고흥 일대 만은 갯벌이 넓고, 젖은 갯벌은
 * 하늘을 비춰 바다와 한 덩어리로 읽힌다 — 계단 윤곽이 거기 묻힌다.
 *
 * ## 거리마다 접는다
 *
 * 무늬는 픽셀 하나가 덮는 땅 크기(`pw`, fwidth로 잰다)에 맞춰 차례로 접힌다 — 남기면 지글거린다:
 * 나무 하나하나(7 m)는 픽셀이 1.2~3.5 m일 때 사라지고, 필지·둑·지붕은 그 크기의 몇 분의 일에서,
 * 수관 무리 얼룩(34 m)과 피복 경계의 흔들림(95 m)도 더 멀리서 평균으로 간다. 접힌 자리에는 그
 * 무늬의 평균색이 남는다 — 먼 들이 회색으로 죽지 않고 황록으로 남는 이유다.
 *
 * ## 조명은 세 곳에 끼운다
 *
 *     <metalnessmap_fragment> 뒤   알베도·거칠기 (GROUND_FRAG_BODY)
 *     <normal_fragment_begin> 뒤   법선 흔들기 — 수관 돔과 미세 기복 (GROUND_NORMAL_BODY)
 *     <lights_fragment_end> 뒤     직사광에 지형 그림자·구름 그늘, 주변광에 하늘 열림,
 *                                 젖은 갯벌에 하늘 반사 (GROUND_LIGHT_BODY)
 *
 * 그림자를 알베도가 아니라 **직사광 항에만** 거는 것이 요점이다 — 그늘에서도 하늘빛(반구광)은
 * 살아 있어야 산그늘이 먹물이 아니라 푸른 그늘이 된다. 반구광은 three에서 간접 확산으로 들어가므로
 * `reflectedLight.directDiffuse/Specular`만 깎으면 태양 하나만 가려진다.
 *
 * ## 지형 자체 그림자 — 표고 텍스처를 태양 쪽으로 훑는다
 *
 * 그림자 맵은 30 km 도메인에 2,048 텍셀이면 15 m라 지형에는 못 쓴다(그래서 기체·지상 장비만
 * 드리운다). 대신 티어 표고를 반정밀도 텍스처 둘(촘촘한 것·넓은 것)로 올리고, 조각마다 태양
 * 방향으로 30걸음(18 m에서 시작해 1.22배씩, 약 5.8 km까지 — 먼 땅은 16걸음·1.42배) 올라가며 지면과의 틈을 잰다. 틈과
 * 거리의 비로 반그늘을 만든다(높이장 광선 추적의 흔한 연성 그림자). 걸음 사이에 낀 좁은 능선은
 * 놓칠 수 있고, 무딘 정도는 격자 해상도(30·90 m)를 따른다 — 캡션 몫. 광선이 팩 최고 표고를
 * 넘으면 더 볼 것이 없으므로 멈춘다(해가 높으면 몇 걸음에 끝난다).
 *
 * `CLOUD_UNIFORM_DECL`·`NOISE_GLSL`·`CLOUD_COVER_GLSL`·`ATMOSPHERE_*`·`COAST_GLSL`이 앞에 있어야
 * 한다 — `scene/materials.ts applyGroundDetail`이 조립한다.
 */

/** 지면 전용 유니폼 — 값은 `SceneHost`가 쥔다(표고 텍스처·변환·최고 표고). */
export const GROUND_UNIFORM_DECL = /* glsl */`
uniform sampler2D uHeightFine;     // 촘촘한 티어 표고 [m] (반정밀도, 선형 필터)
uniform sampler2D uHeightCoarse;   // 넓은 티어 표고 [m]
uniform vec4 uHFine;               // (e0, n0, 간격 [m], 0) — 칸 (0, 0)의 NED와 격자 간격
uniform vec2 uHFineSize;           // (열, 행)
uniform vec4 uHCoarse;
uniform vec2 uHCoarseSize;
uniform float uHeightOn;           // 0이면 표고 텍스처가 없다 — 자체 그림자를 건너뛴다
uniform float uTerrainTop;         // 팩 최고 표고 [m] — 그림자 광선이 이보다 높아지면 멈춘다
uniform vec4 uRunway;              // (cos h, sin h, 길이 [m], 반폭 [m]) — NED 원점에서 heading 방향
uniform float uRunwayOn;           // 0이면 포장면을 칠하지 않는다(폭을 모를 때 — core/runway.ts)
uniform vec4 uRunwayArea;          // (과주로 [m], 착륙대 반폭 [m], 착륙대 끝 너머 [m], 0) — 착륙대는 펴진 바닥과 같은 구역
uniform vec4 uRunwayNum;           // 활주로 번호 (시단 쪽 십·일, 맞은편 십·일) — 모르면 -1이고 번호를 칠하지 않는다
`;

export const GROUND_VARYING_DECL = /* glsl */`
varying vec3 vGroundWorld;
varying vec3 vGroundNormal;
varying vec2 vGroundShade;   // (하늘 열림, 볼록도) — core/terrainshade.ts가 정점에 굽는다
`;

/** 정점 선언 — 정점 속성 aTerrain은 SceneHost.setTerrain이 싣는다. */
export const GROUND_VERT_DECL = /* glsl */`
attribute vec2 aTerrain;
${GROUND_VARYING_DECL}
`;

/** 정점 — `<fog_vertex>` 뒤. */
export const GROUND_VERT_BODY = /* glsl */`
  vGroundWorld = (modelMatrix * vec4(transformed, 1.0)).xyz;
  vGroundNormal = normalize(mat3(modelMatrix) * objectNormal);
  vGroundShade = aTerrain;
`;

/** 피복·무늬·그림자 함수 — 조각 셰이더 앞머리. */
export const GROUND_GLSL = /* glsl */`
// ---- 지표 피복 알베도 (선형) — sRGB 감각으로 고른 색을 2.2제곱해 적었다. 표시 값이다.
const vec3 GR_CONIFER   = vec3(0.028, 0.045, 0.020);
const vec3 GR_BROAD     = vec3(0.055, 0.085, 0.030);
const vec3 GR_AUTUMN    = vec3(0.120, 0.095, 0.028);
const vec3 GR_UNDER     = vec3(0.014, 0.018, 0.011);   // 수관 사이 그늘진 바닥
const vec3 GR_RICE_RIPE = vec3(0.300, 0.235, 0.075);   // 익은 벼 (10월)
const vec3 GR_RICE_GRN  = vec3(0.135, 0.165, 0.050);   // 덜 익은 벼 (황록)
const vec3 GR_STUBBLE   = vec3(0.215, 0.165, 0.090);   // 벤 논
const vec3 GR_SOIL      = vec3(0.150, 0.115, 0.075);   // 갈아엎은 밭
const vec3 GR_VEG       = vec3(0.095, 0.130, 0.050);   // 채소밭
const vec3 GR_VINYL     = vec3(0.360, 0.375, 0.385);   // 비닐하우스 (먼지 낀 흰 비닐)
const vec3 GR_DIKE      = vec3(0.110, 0.125, 0.055);   // 논둑 풀
const vec3 GR_ROAD      = vec3(0.280, 0.270, 0.250);   // 농로 콘크리트
const vec3 GR_ROCK      = vec3(0.190, 0.175, 0.150);
const vec3 GR_MUD_WET   = vec3(0.055, 0.052, 0.046);
const vec3 GR_MUD_DRY   = vec3(0.150, 0.132, 0.105);
const vec3 GR_YARD      = vec3(0.180, 0.170, 0.155);   // 마당·골목
const vec3 GR_GRASS     = vec3(0.125, 0.145, 0.060);   // 깎은 풀 (비행장, 10월의 누런 풀빛)
const vec3 GR_ASPHALT   = vec3(0.070, 0.070, 0.075);
const vec3 GR_GRASS_DRY = vec3(0.165, 0.150, 0.070);   // 깎은 풀밭의 마른 자리
const vec3 GR_PAINT     = vec3(0.600, 0.600, 0.580);   // 활주로 흰 도색 (닳은 흰색)
const vec3 GR_PAINT_YEL = vec3(0.520, 0.360, 0.040);   // 과주로 노란 갈매기표

// ---- 활주로 도색 — 띠·숫자의 덮임을 픽셀 발자국(pw) 상자로 거른다. 가까이선 칼날, 멀어지면 폭/발자국만큼
// 옅어진다(멀리서 지글거리지 않게). 좌표는 활주로 축 기준 [m]. 치수는 ICAO 부속서 14의 표준이다(실측 아님).

// 가운데 0, 반폭 h인 띠의 덮임 — 발자국 상자와 겹친 비율
float grBand(float x, float h, float pw) {
  float r = 0.5 * pw;
  return clamp((min(x + r, h) - max(x - r, -h)) / pw, 0.0, 1.0);
}

// 주기 P로 되풀이되는 띠(반폭 h, 가운데가 P의 배수) — 발자국이 주기에 다가가면 띠 비율의 평균으로 접는다
float grStripes(float x, float P, float h, float pw) {
  float xr = x - P * floor(x / P + 0.5);
  return mix(grBand(xr, h, pw), 2.0 * h / P, smoothstep(0.3 * P, P, pw));
}

// 7획 숫자의 획 비트 — a 위 1, b 오른 위 2, c 오른 아래 4, d 아래 8, e 왼 아래 16, f 왼 위 32, g 가운데 64.
// 1은 가운데 막대 하나라 따로 그린다(활주로 숫자의 1은 오른쪽 두 획이 아니다)
const int GR_SEG[10] = int[10](63, 0, 91, 79, 102, 109, 125, 7, 127, 111);

// 숫자 하나 — 칸 가로 3 m(u, 읽는 이의 오른쪽이 +) · 세로 9 m(v, 읽는 위쪽이 +), 획 0.9 m
float grDigit(float d, vec2 uv, float pw) {
  if (d < 0.0 || uv.x < -1.0 || uv.x > 4.0 || uv.y < -1.0 || uv.y > 10.0) return 0.0;
  const float W = 3.0;
  const float H = 9.0;
  const float S = 0.9;
  int k = clamp(int(d + 0.5), 0, 9);
  if (k == 1) return grBand(uv.x - 0.5 * W, 0.5 * S, pw) * grBand(uv.y - 0.5 * H, 0.5 * H, pw);
  int m = GR_SEG[k];
  float bu = grBand(uv.x - 0.5 * W, 0.5 * W, pw);
  float lu = grBand(uv.x - 0.5 * S, 0.5 * S, pw);
  float ru = grBand(uv.x - (W - 0.5 * S), 0.5 * S, pw);
  float top = grBand(uv.y - 0.75 * H, 0.25 * H, pw);
  float bot = grBand(uv.y - 0.25 * H, 0.25 * H, pw);
  float c = 0.0;
  if ((m & 1) != 0) c = max(c, bu * grBand(uv.y - (H - 0.5 * S), 0.5 * S, pw));
  if ((m & 2) != 0) c = max(c, ru * top);
  if ((m & 4) != 0) c = max(c, ru * bot);
  if ((m & 8) != 0) c = max(c, bu * grBand(uv.y - 0.5 * S, 0.5 * S, pw));
  if ((m & 16) != 0) c = max(c, lu * bot);
  if ((m & 32) != 0) c = max(c, lu * top);
  if ((m & 64) != 0) c = max(c, bu * grBand(uv.y - 0.5 * H, 0.5 * S, pw));
  return c;
}

// 활주로 번호 한 끝 — num (십, 일), s 시단에서 활주로 안쪽 [m], x 읽는 이의 오른쪽 [m]. 두 칸(각 3 m)이 가운데
// 1.5 m를 두고 선다. 시단 줄무늬(6~36 m) 끝에서 12 m 띄운 48~57 m 자리다
float grDesignation(vec2 num, float s, float x, float pw) {
  if (num.x < 0.0 || s < 46.0 || s > 59.0 || abs(x) > 5.5) return 0.0;
  float v = s - 48.0;
  return max(grDigit(num.x, vec2(x + 3.75, v), pw), grDigit(num.y, vec2(x - 0.75, v), pw));
}

// 시단 줄무늬(피아노 건반) — 시단에서 6~36 m, 축 양쪽 같은 수의 줄. 줄과 칸이 같은 너비이고 가운데 칸만
// 두 배다. 바깥 끝은 가장자리에서 3 m 안(최대 축에서 27 m) — 고흥 45 m 폭은 12줄, 너비 1.63 m
float grPiano(float s, float x, float halfW, float pw) {
  if (s < 4.0 || s > 38.0) return 0.0;
  float nSide = halfW <= 9.0 ? 2.0 : halfW <= 11.5 ? 3.0 : halfW <= 15.0 ? 4.0 : halfW <= 22.5 ? 6.0 : 8.0;
  float outer = min(halfW - 3.0, 27.0);
  float sw = outer / (2.0 * nSide);
  float ax = abs(x);
  // 줄 k는 축에서 (2k+1)·sw ~ (2k+2)·sw — 가운데 (2k+1.5)·sw, 주기 2·sw
  float keys = grStripes(ax - 1.5 * sw, 2.0 * sw, 0.5 * sw, pw)
             * grBand(ax - 0.5 * (sw + outer), 0.5 * (outer - sw), pw);
  return keys * grBand(s - 21.0, 15.0, pw);
}

// 중심선 — 30 m 줄과 20 m 칸, 너비 0.9 m. 양 끝 번호(57 m)에서 12 m 띄운 69 m부터 맞은편 69 m까지
float grCenterline(float along, float x, float L, float pw) {
  if (along < 67.0 || along > L - 67.0 || abs(x) > 2.0) return 0.0;
  float dash = grStripes(along - 84.0, 50.0, 15.0, pw);
  return dash * grBand(x, 0.45, pw) * grBand(along - 0.5 * L, 0.5 * L - 69.0, pw);
}

// 과주로 갈매기표 — t 시단 밖으로 [m](0이 시단). 꼭짓점이 활주로 쪽을 가리키는 45도 줄, 30 m 간격, 너비 0.9 m.
// k = t - |x|가 한 갈매기 위에서 일정하다 — 줄의 k 방향 반폭은 0.45의 루트2배, 발자국도 루트2배
float grChevron(float t, float x, float over, float pw) {
  if (t <= 0.0 || t > over) return 0.0;
  return grStripes(t - abs(x) - 6.0, 30.0, 0.64, pw * 1.41);
}

float grHash(vec2 c, float k) { return hash31(vec3(c, k)); }

/** 들 — 블록(보로노이 약 420 m)마다 방향과 필지 크기가 다르고, 블록 안은 회전 격자다.
 *  parcel 필지 난수, dike 가장 가까운 둑까지 [m], road 블록 경계(농로)까지 [m], block 블록 난수,
 *  q 필지 좌표 [m](x가 필지의 긴 변 — 이랑·콤바인 자국은 이 축과 나란하다).
 *
 *  **회전각은 블록마다 상수다.** 처음에 지역 방향을 픽셀마다 노이즈로 뽑았더니, 각이 조금만
 *  변해도 원점에서 수 km 떨어진 좌표가 크게 돌아가 필지가 동심원 호처럼 휘었다(화면 실측). 그래서
 *  지역 방향도 블록 중심에서 한 번 읽고, 회전은 블록 중심 기준 좌표로 한다(정밀도도 산다). */
void grFields(vec2 p, out float parcel, out float dike, out float road, out float block, out vec2 q) {
  const float BLOCK = 420.0;
  vec2 bp = p / BLOCK;
  vec2 bi = floor(bp);
  float d1 = 1.0e9;
  float d2 = 1.0e9;
  vec2 best = bi;
  for (int j = -1; j <= 1; j++) {
    for (int i = -1; i <= 1; i++) {
      vec2 c = bi + vec2(float(i), float(j));
      vec2 o = c + 0.15 + 0.7 * vec2(grHash(c, 1.0), grHash(c, 2.0));
      float d = length(bp - o);
      if (d < d1) { d2 = d1; d1 = d; best = c; }
      else if (d < d2) { d2 = d; }
    }
  }
  vec2 center = (best + 0.5) * BLOCK;
  float ang = 3.0 * vnoise3(vec3(center * (1.0 / 2600.0), 9.1)) + (grHash(best, 4.0) - 0.5) * 0.9;
  vec2 dir = vec2(cos(ang), sin(ang));
  vec2 lp = p - center;
  q = vec2(dot(lp, dir), dot(lp, vec2(-dir.y, dir.x)));
  vec2 cell = mix(vec2(60.0, 24.0), vec2(115.0, 46.0), vec2(grHash(best, 5.0), grHash(best, 6.0)));
  vec2 g = q / cell;
  vec2 fi = floor(g);
  vec2 fr = g - fi;
  vec2 edge = min(fr, 1.0 - fr) * cell;
  parcel = grHash(fi + best * 31.0, 7.0);
  dike = min(edge.x, edge.y);
  road = (d2 - d1) * BLOCK * 0.5;
  block = grHash(best, 3.0);
}

/** 수관 — 7 m 격자에 한 그루씩, 반지름 2.3~3.9 m 포물면 돔(꼭대기 0.7 R). 겹치면 높은 쪽.
 *  돌려주는 것: x 덮임(0 빈틈 ~ 1 꼭대기), y 높이 [m], zw 높이의 기울기(세계 xz). */
vec4 grCrowns(vec2 p) {
  const float CELL = 7.0;
  vec2 gi = floor(p / CELL);
  vec4 res = vec4(0.0);
  for (int j = -1; j <= 1; j++) {
    for (int i = -1; i <= 1; i++) {
      vec2 c = gi + vec2(float(i), float(j));
      vec2 center = (c + 0.2 + 0.6 * vec2(grHash(c, 11.0), grHash(c, 12.0))) * CELL;
      float R = 2.3 + 1.6 * grHash(c, 13.0);
      vec2 d = p - center;
      float u = 1.0 - dot(d, d) / (R * R);
      float h = u * R * 0.7;
      if (u > 0.0 && h > res.y) { res = vec4(sqrt(u), h, d * (-1.4 / R)); }
    }
  }
  return res;
}

/** 마을 — 15 m 집터에 집 한 채(62%), 지붕은 회색·청회·주황·녹색·흰색 중 하나.
 *  돌려주는 것: rgb 지붕색, a 지붕 덮임(0이면 마당). */
vec4 grVillage(vec2 p) {
  const float LOT = 15.0;
  vec2 g = p / LOT;
  vec2 gi = floor(g);
  vec2 off = abs(g - gi - 0.5);
  if (grHash(gi, 21.0) > 0.62) return vec4(GR_YARD, 0.0);
  vec2 hs = 0.22 + 0.16 * vec2(grHash(gi, 22.0), grHash(gi, 23.0));
  float roofIn = step(off.x, hs.x) * step(off.y, hs.y);
  float k = grHash(gi, 24.0);
  vec3 roof = k < 0.30 ? vec3(0.20, 0.21, 0.22)
            : k < 0.55 ? vec3(0.070, 0.110, 0.170)
            : k < 0.75 ? vec3(0.320, 0.100, 0.050)
            : k < 0.88 ? vec3(0.070, 0.150, 0.100)
            : vec3(0.55, 0.55, 0.53);
  return vec4(roof, roofIn);
}

/** 지표 피복 한 점 — 알베도·거칠기·미세 기울기(법선 흔들기)·젖음·미세 차폐.
 *  p 세계 위치, n 기하 법선(세계, 정규화), shade (열림, 볼록도), shoreD 바다까지 [m] (모르면 큰 수),
 *  pw 픽셀 발자국 [m]. */
void grCover(vec3 p, vec3 n, vec2 shade, float shoreD, float pw,
             out vec3 albedo, out float rough, out vec2 grad, out float wet, out float occ) {
  vec2 xz = p.xz;
  float elev = p.y;
  float ny = clamp(n.y, 0.05, 1.0);
  float slope = sqrt(max(1.0 - ny * ny, 0.0)) / ny;   // 경사 tan
  float convex = shade.y;

  // 피복 경계를 흔드는 큰 무늬 — 멀어지면 평균(0.44)으로 접는다
  // 다 접힌 거리에서는 노이즈를 아예 부르지 않는다 — 와이드샷 픽셀 대부분이 거기다
  float nA = pw < 200.0 ? mix(fbm3(vec3(xz * (1.0 / 310.0), 1.7)), 0.44, smoothstep(80.0, 200.0, pw)) : 0.44;
  float nB = pw < 60.0 ? mix(fbm3(vec3(xz * (1.0 / 95.0), 5.3)), 0.44, smoothstep(25.0, 60.0, pw)) : 0.44;

  // ---- 가중치
  // 갯벌 — 물가의 좁은 띠만. 처음엔 900 m까지 칠했는데, 간척지 안 작은 물웅덩이 둘레마다 둥근
  // 검보라 무리가 생겼다(화면 실측). 해안 턱은 이제 해수면 판정이 바다로 흡수한다(core/seamask.ts).
  float wWet = (1.0 - smoothstep(0.8, 2.5, elev)) * (1.0 - smoothstep(40.0, 150.0, shoreD + (nB - 0.44) * 160.0))
             * (1.0 - smoothstep(0.07, 0.16, slope));
  float flatness = 1.0 - smoothstep(0.05, 0.12, slope + (nB - 0.44) * 0.06);
  float lowland = 1.0 - smoothstep(60.0, 150.0, elev - convex * 45.0 + (nA - 0.44) * 70.0);
  // 들 가운데 작은 숲(마을숲·묘역) — 경계를 날카롭게. 반쯤 섞으면 들 위에 검은 수관이 흩뿌린 점으로 떴다
  float woodlot = smoothstep(0.69, 0.715, nB);
  float wField = flatness * lowland * (1.0 - woodlot) * (1.0 - wWet);
  // 마을 — 산자락(경사가 막 오르는 띠)의 드문 군집. 처음 문턱(0.60)으로는 산마다 회색 띠가
  // 둘려 시멘트 고리처럼 읽혔다(화면 실측) — 군집을 드물게, 띠를 좁게 했다.
  float foot = smoothstep(0.035, 0.065, slope) * (1.0 - smoothstep(0.11, 0.17, slope)) * lowland;
  float wVillage = foot * (1.0 - wWet)
                 * smoothstep(0.70, 0.76, vnoise3(vec3(xz * (1.0 / 260.0), 13.0)));
  float wRock = clamp(smoothstep(0.85, 1.4, slope + (nB - 0.44) * 0.7)
                + smoothstep(0.55, 0.95, convex) * smoothstep(0.4, 0.8, slope) * 0.5, 0.0, 1.0);
  float wShore = (1.0 - smoothstep(20.0, 55.0, shoreD)) * smoothstep(0.05, 0.14, slope);

  // ---- 숲
  float broad = smoothstep(0.30, 0.62, nA);
  vec3 forest = mix(GR_CONIFER, GR_BROAD, broad);
  if (elev > 120.0 && broad > 0.0) {
    float autumn = smoothstep(0.55, 0.74, vnoise3(vec3(xz * (1.0 / 520.0), 2.2)))
                 * smoothstep(120.0, 360.0, elev) * broad;
    forest = mix(forest, GR_AUTUMN, autumn * 0.45);
  }
  float mott = pw < 30.0 ? mix(fbm3(vec3(xz * (1.0 / 34.0), 4.4)), 0.44, smoothstep(10.0, 30.0, pw)) : 0.44;
  forest *= (0.72 + 0.62 * mott) * (1.0 + convex * 0.10);
  vec2 forestGrad = vec2(0.0);
  float forestOcc = 1.0;
  float crownFade = 1.0 - smoothstep(1.2, 3.5, pw);
  if (crownFade > 0.001) {
    vec4 cr = grCrowns(xz);
    vec3 crown = cr.x > 0.0 ? forest * (0.85 + 0.40 * cr.x) : GR_UNDER;
    forest = mix(forest, crown, crownFade);
    forestGrad = cr.zw * crownFade;
    forestOcc = mix(1.0, 0.55 + 0.45 * cr.x, crownFade);
  }
  vec3 col = forest;
  float rgh = 0.92;

  // ---- 들
  if (wField > 0.001) {
    // 먼 들의 평균 — 지역마다(약 700 m) 익은 쪽·푸른 쪽으로 기운다. 필지 색의 면적 평균과 맞춘다
    float region = vnoise3(vec3(xz * (1.0 / 700.0), 6.6));
    vec3 field = mix(vec3(0.150, 0.160, 0.065), vec3(0.225, 0.190, 0.080), region)
               * (0.9 + 0.22 * nB);
    float frough = 0.88;
    float parcelVis = 1.0 - smoothstep(10.0, 28.0, pw);
    if (parcelVis > 0.001) {
      float parcel, dikeD, roadD, block;
      vec2 q;
      grFields(xz, parcel, dikeD, roadD, block, q);
      // 블록마다 주 작물이 있고 필지 셋 중 둘이 그것을 따른다 — 이웃끼리 닮고 블록끼리 갈린다.
      // 필지마다 따로 뽑았더니 색이 센 바둑판이 됐다(화면 실측).
      float dom = grHash(vec2(block * 977.0, 3.0), 31.0);
      float u = parcel < 0.66 ? dom : fract(parcel * 7.13);
      int kind = u < 0.40 ? 0 : u < 0.62 ? 1 : u < 0.82 ? 2 : u < 0.90 ? 3 : 4;
      vec3 crop = kind == 0 ? GR_RICE_RIPE : kind == 1 ? GR_RICE_GRN : kind == 2 ? GR_STUBBLE
                : kind == 3 ? GR_SOIL : GR_VEG;
      crop *= 0.94 + 0.12 * fract(parcel * 53.0);
      // 필지 안 결 — 벼 포기는 고운 얼룩, 벤 논은 콤바인 자국(2.2 m), 밭은 고랑(0.9 m), 채소는 이랑(1.2 m).
      // 줄은 필지의 긴 변(q.x)과 나란하다. 줄 간격이 픽셀 몇 개로 줄면 접는다.
      float spacing = kind == 2 ? 2.2 : kind == 3 ? 0.9 : 1.2;
      float rowAmp = (kind == 2 ? 0.10 : kind == 3 ? 0.16 : kind == 4 ? 0.20 : 0.0)
                   * (1.0 - smoothstep(spacing * 0.25, spacing * 0.6, pw));
      float rows = sin(q.y * (6.2832 / spacing));
      float grain = mix(fbm3(vec3(xz * (1.0 / 2.5), 7.7)) - 0.44, 0.0, smoothstep(0.8, 2.5, pw));
      crop *= 1.0 + rowAmp * rows + 0.18 * grain;
      if (kind == 4) crop = mix(crop, GR_SOIL, 0.35 * rowAmp * 5.0 * max(-rows, 0.0));
      // 비닐하우스 — 몇 블록에 몰려, 폭 7 m 동이 1.5 m 틈을 두고 나란히(흩뿌리면 흰 점박이가 된다)
      bool vinyl = block > 0.86 && parcel > 0.62;
      if (vinyl) {
        float house = (1.0 - smoothstep(0.78, 0.80, fract(q.y / 8.5)));
        float ridge = 1.0 - abs(fract(q.y / 8.5) / 0.79 - 0.5) * 2.0;     // 동의 등마루 쪽이 밝다
        vec3 hv = GR_VINYL * (0.8 + 0.3 * ridge);
        float vis = 1.0 - smoothstep(1.5, 5.0, pw);
        crop = mix(mix(GR_VINYL * 0.85, GR_SOIL, 0.18), mix(GR_SOIL, hv, house), vis);
      }
      // 둑 — 폭 0.9 m, 풀빛으로 연하게. 픽셀보다 가늘어지면 면적 비율로 섞는다
      float dike = 1.0 - smoothstep(0.45 - pw * 0.5, 0.45 + pw * 0.5, dikeD);
      crop = mix(crop, mix(crop, GR_DIKE, 0.6), mix(dike, 0.03, smoothstep(1.0, 3.0, pw)));
      // 농로 — 블록 경계, 블록 셋 중 둘
      float road = (1.0 - smoothstep(2.2 - pw * 0.5, 2.2 + pw * 0.5, roadD)) * step(0.33, block);
      crop = mix(crop, GR_ROAD, mix(road, 0.03, smoothstep(3.0, 8.0, pw)));
      field = mix(field, crop, parcelVis);
      frough = mix(frough, vinyl ? 0.45 : 0.88, parcelVis);
    }
    col = mix(col, field, wField);
    rgh = mix(rgh, frough, wField);
  }

  // ---- 마을
  if (wVillage > 0.001) {
    vec3 village = mix(GR_YARD, GR_BROAD, 0.45);   // 먼 마을의 평균 — 지붕·마당·집 사이 나무
    float vilVis = 1.0 - smoothstep(1.5, 5.0, pw);
    if (vilVis > 0.001) {
      vec4 hv = grVillage(xz);
      village = mix(village, mix(GR_YARD, hv.rgb, hv.a), vilVis);
    }
    col = mix(col, village, wVillage);
    rgh = mix(rgh, 0.8, wVillage);
  }

  // ---- 암반·해안 바위
  if (wRock > 0.001) {
    vec3 rock = GR_ROCK * (0.7 + 0.6 * mix(fbm3(vec3(xz * (1.0 / 9.0), elev * 0.2)), 0.44,
                                            smoothstep(3.0, 9.0, pw)));
    col = mix(col, rock, wRock);
    rgh = mix(rgh, 0.85, wRock);
  }
  col = mix(col, GR_ROCK * 0.55, wShore);
  rgh = mix(rgh, 0.6, wShore);

  // ---- 갯벌 — 갯골은 가는 물길, 낮을수록 젖었다
  float wetness = 0.0;
  if (wWet > 0.001) {
    float chn = abs(fbm2(xz * (1.0 / 170.0), 3));
    float channel = (1.0 - smoothstep(0.015, 0.045 + pw * 0.001, chn)) * (1.0 - smoothstep(20.0, 60.0, pw));
    vec3 mud = mix(GR_MUD_WET, GR_MUD_DRY,
                   clamp(smoothstep(0.8, 4.0, elev) * 0.8 + (nB - 0.44) * 0.6, 0.0, 1.0));
    mud = mix(mud, GR_MUD_WET * 0.55, channel);
    wetness = clamp(0.6 + channel * 0.4 - smoothstep(1.0, 4.0, elev) * 0.5, 0.0, 1.0);
    col = mix(col, mud, wWet);
    rgh = mix(rgh, mix(0.85, 0.22, wetness), wWet);
  }

  // ---- 미세 기복 — 30 m 격자가 못 싣는 굴곡(42 m·12 m 두 옥타브). 들·갯벌·마을은 평평하다
  vec2 micro = vec2(0.0);
  float mf1 = 1.0 - smoothstep(8.0, 20.0, pw);
  if (mf1 > 0.001) micro += gnoise2(xz * (1.0 / 42.0)).yz * (3.0 / 42.0) * mf1;
  float mf2 = 1.0 - smoothstep(2.5, 6.0, pw);
  if (mf2 > 0.001) micro += gnoise2(xz * (1.0 / 12.0) + 5.0).yz * (0.9 / 12.0) * mf2;

  // ---- 비행장 — 착륙대 풀밭, 포장면·과주로, 도색. 활주로는 결과의 것, 폭은 시험장 제원(core/runway.ts):
  // 폭을 모르면 uRunwayOn이 0이고 아무것도 칠하지 않는다(포장면을 지어내지 않는다).
  float field0 = 0.0;
  if (uRunwayOn > 0.5) {
    vec2 ne = vec2(-p.z, p.x);   // 렌더 x = e, z = -n
    float along = dot(ne, uRunway.xy);
    float across = dot(ne, vec2(-uRunway.y, uRunway.x));
    float L = uRunway.z;
    float halfW = uRunway.w;
    float over = uRunwayArea.x;
    // 착륙대 — 펴진 바닥(core/runwayfloor.ts)과 같은 구역이고 경계는 발자국만큼만 부드럽다. 예전엔 40~60 m에
    // 걸쳐 섞어 들·비닐하우스 위에 흐린 띠가 얹혀 보였다(사용자 지적)
    field0 = grBand(across, uRunwayArea.y, pw) * grBand(along - 0.5 * L, 0.5 * L + uRunwayArea.z, pw);
    if (field0 > 0.001) {
      // 깎은 풀 — 깎는 기계가 오간 결(활주로와 나란히 5 m씩 번갈아 밝고 어둡다)과 마른 자리 얼룩
      float mow = (smoothstep(-0.25, 0.25, sin(across * (6.2832 / 10.0))) - 0.5) * 0.10
                * (1.0 - smoothstep(1.5, 4.0, pw));
      float dry = pw < 20.0 ? mix(fbm3(vec3(ne * (1.0 / 23.0), 9.1)), 0.44, smoothstep(8.0, 20.0, pw)) : 0.44;
      vec3 grass = mix(GR_GRASS, GR_GRASS_DRY, smoothstep(0.40, 0.62, dry + (nB - 0.44) * 0.5));
      col = mix(col, grass * (0.94 + 0.12 * nB + mow), field0);
      rgh = mix(rgh, 0.9, field0);
      // 포장면 — 활주로와 양 끝 과주로. 접지대(시단에서 100~450 m)에 타이어 자국, 과주로는 덜 다녀 바랬다
      float onRunway = grBand(along - 0.5 * L, 0.5 * L, pw);
      float paved = grBand(across, halfW, pw) * grBand(along - 0.5 * L, 0.5 * L + over, pw);
      float tz = smoothstep(80.0, 160.0, along) * (1.0 - smoothstep(380.0, 480.0, along))
               + smoothstep(80.0, 160.0, L - along) * (1.0 - smoothstep(380.0, 480.0, L - along));
      float rubber = tz * (1.0 - smoothstep(4.0, 9.0, abs(across)));
      float tex = mix(fbm3(vec3(ne * 0.5, 2.0)) - 0.44, 0.0, smoothstep(1.0, 4.0, pw));
      col = mix(col, GR_ASPHALT * (1.0 + 0.25 * tex) * (1.0 - 0.35 * rubber) * mix(1.12, 1.0, onRunway), paved);
      rgh = mix(rgh, 0.75, paved);
      if (paved > 0.001) {
        // 도색 — 시단 사이는 흰색(측면 표지·시단 줄무늬·번호·중심선·조준점), 과주로는 노란 갈매기표.
        // 맞은편 끝은 남쪽으로 읽으므로 가로를 뒤집는다
        float sF = L - along;
        float white = grBand(abs(across) - (halfW - 0.45), 0.45, pw) * onRunway;
        white = max(white, max(grPiano(along, across, halfW, pw), grPiano(sF, -across, halfW, pw)));
        white = max(white, max(grDesignation(uRunwayNum.xy, along, across, pw),
                               grDesignation(uRunwayNum.zw, sF, -across, pw)));
        white = max(white, grCenterline(along, across, L, pw));
        float aimX = grBand(abs(across) - 12.0, 3.0, pw);   // 조준점 — 시단에서 250~295 m, 축에서 9~15 m
        white = max(white, aimX * max(grBand(along - 272.5, 22.5, pw), grBand(sF - 272.5, 22.5, pw)));
        float yel = max(grChevron(-along, across, over, pw), grChevron(along - L, -across, over, pw));
        float wear = 0.80 + 0.20 * clamp(1.0 + 2.0 * tex, 0.0, 1.0);   // 닳은 도색 — 아스팔트 결이 비친다
        col = mix(col, GR_PAINT * wear * (1.0 - 0.45 * rubber), white * paved);
        col = mix(col, GR_PAINT_YEL * wear, yel * paved);
        rgh = mix(rgh, 0.62, max(white, yel) * paved);
      }
    }
  }

  float bare = (1.0 - wField) * (1.0 - wWet) * (1.0 - wVillage) * (1.0 - field0);
  float fShare = bare * (1.0 - wRock) * (1.0 - wShore);
  albedo = col;
  rough = rgh;
  grad = forestGrad * fShare + micro * bare;
  wet = wWet * wetness * (1.0 - field0);
  occ = mix(1.0, forestOcc, fShare);
}

/** 촘촘한 티어가 덮으면 그것, 아니면 넓은 티어, 둘 다 밖이면 해수면. */
float grTerrainH(vec2 xz) {
  vec2 en = vec2(xz.x, -xz.y);   // 렌더 x = e, z = -n (scene/axes.ts)
  vec2 uv = ((en - uHFine.xy) / uHFine.z + 0.5) / uHFineSize;
  if (uv.x > 0.0 && uv.y > 0.0 && uv.x < 1.0 && uv.y < 1.0) return textureLod(uHeightFine, uv, 0.0).r;
  uv = ((en - uHCoarse.xy) / uHCoarse.z + 0.5) / uHCoarseSize;
  if (uv.x > 0.0 && uv.y > 0.0 && uv.x < 1.0 && uv.y < 1.0) return textureLod(uHeightCoarse, uv, 0.0).r;
  return 0.0;
}

/** 지형 자체 그림자 0(그늘) ~ 1(햇빛) — 머리말 「지형 자체 그림자」. p는 표면에서 조금 띄운 점.
 *  pw(픽셀 발자국)가 크면 — 먼 땅이면 — 걸음을 성기게 한다: 30걸음·1.22배 대신 16걸음·1.42배로
 *  같은 약 5.8 km를 덮는다. 먼 산그늘은 넓어서 성긴 걸음으로도 잡히고, 화면 픽셀 대부분이 거기다. */
float grTerrainShadow(vec3 p, vec3 L, float pw) {
  if (uHeightOn < 0.5) return 1.0;
  if (L.y <= 0.0) return 0.0;
  bool far = pw > 8.0;
  int steps = far ? 16 : 30;
  float grow = far ? 1.42 : 1.22;
  float res = 1.0;
  float t = 18.0;
  for (int i = 0; i < 30; i++) {
    if (i >= steps) break;
    vec3 q = p + L * t;
    if (q.y > uTerrainTop + 2.0) break;
    res = min(res, (q.y - grTerrainH(q.xz)) / (t * 0.03));
    if (res < -0.5) break;
    t *= grow;
  }
  res = clamp(res, 0.0, 1.0);
  return res * res * (3.0 - 2.0 * res);
}
`;

/** 조각 — `<metalnessmap_fragment>` 뒤. 알베도·거칠기를 정하고, 뒤의 두 단계가 쓸 값을 남긴다.
 *
 * `<color_fragment>` 뒤가 아니다 — roughnessFactor가 `<roughnessmap_fragment>`에서 선언된다.
 * 뒤 단계가 읽을 변수는 블록 밖(main 범위)에 둔다. */
export const GROUND_FRAG_BODY = /* glsl */`
  vec2 grGrad = vec2(0.0);
  float grWet = 0.0;
  float grOcc = 1.0;
  // 픽셀 발자국 [m] — 화면 도함수는 **분기와 discard 앞에서 한 번만** 잰다. 갈라진 분기 안이나
  // discard 뒤의 도함수는 GLSL에서 정의되지 않는다(조명 단계의 그림자 걸음 수도 이 값을 쓴다).
  float grPw = max(length(fwidth(vGroundWorld)), 1.0e-3);
  {
    vec3 gp = vGroundWorld;
    vec3 gn = normalize(vGroundNormal);
    float pw = grPw;
    vec2 coast = coastAt(gp.xz);
    // 물가의 해수면 높이 조각은 버린다 — 해면이 그 자리를 그린다. 지형은 바다 칸을 **칸 단위로**
    // 빼므로(scene/terrain.ts) 남은 해안 칸이 30 m 계단으로 바다에 걸쳐 해안선이 톱니가 됐다.
    // 해수면에 붙은 조각을 버리면 해안선이 삼각형 안의 0.35 m 등고선이 된다. 바다에서 60 m 넘게
    // 떨어진 0 m 땅(활주로가 있는 간척지)은 거리장이 막는다.
    if (gp.y < 0.35 && uHasCoast > 0.5 && coast.y > 0.5 && coast.x > -60.0) discard;
    // 뭍에서 바다까지 [m] — 거리장은 바다 쪽이 양수다. 모르면(자료 없음) 바다와 먼 것으로 친다
    float shoreD = (uHasCoast > 0.5 && coast.y > 0.5) ? max(-coast.x, 0.0) : 1.0e4;
    vec3 albedo;
    float rough;
    grCover(gp, gn, vGroundShade, shoreD, pw, albedo, rough, grGrad, grWet, grOcc);
    diffuseColor.rgb = albedo;
    roughnessFactor = rough;
  }
`;

/** 조각 — `<normal_fragment_begin>` 뒤. 세계 법선을 미세 기울기만큼 흔들어 뷰 공간으로 돌려놓는다.
 *  높이장 y = h(x, z)의 법선이 (−∂h/∂x, 1, −∂h/∂z)인 것과 같은 꼴 — 기울기가 작다는 전제다. */
export const GROUND_NORMAL_BODY = /* glsl */`
  vec3 grNw = normalize(normalize(vGroundNormal) + vec3(-grGrad.x, 0.0, -grGrad.y));
  normal = normalize((viewMatrix * vec4(grNw, 0.0)).xyz);
`;

/** 조각 — `<lights_fragment_end>` 뒤. 머리말 「조명은 세 곳에 끼운다」. */
export const GROUND_LIGHT_BODY = /* glsl */`
  {
    vec3 L = uSunDirWorld;
    vec3 gn = normalize(vGroundNormal);
    float sunVis = cloudSunTransmit(vGroundWorld, L);
    // 해를 등진 면은 어차피 직사광이 0이다 — 그림자 광선을 쏠 이유가 없다
    if (dot(gn, L) > -0.02) sunVis *= grTerrainShadow(vGroundWorld + gn * 2.0, L, grPw);
    reflectedLight.directDiffuse *= sunVis;
    reflectedLight.directSpecular *= sunVis;
    reflectedLight.indirectDiffuse *= vGroundShade.x * grOcc;
    // 젖은 갯벌은 하늘을 비춘다 — 물의 프레넬(F0 0.02), 하늘과 같은 산란 함수
    if (grWet > 0.001) {
      vec3 V = normalize(cameraPosition - vGroundWorld);
      float NoV = clamp(dot(grNw, V), 0.0, 1.0);
      float F = 0.02 + 0.98 * pow(1.0 - NoV, 5.0);
      vec3 R = reflect(-V, grNw);
      R.y = max(R.y, 0.01);
      reflectedLight.indirectSpecular += grWet * F * skyRadiance(R, uSunDirWorld, uSunIntensity, uHaze);
    }
  }
`;
