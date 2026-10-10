/** 활주로 도색 — 착륙대 풀밭·포장면·도색이 **어디에 얼마나 덮이는가**. 실사 지면(shaders/ground.ts `grCover`)과
 * 게임 지형(scene/materials.ts `applyGameRunway`)이 이 한 벌을 쓰고, 색은 각자 정한다 — 실사는 깎은 풀 결·타이어
 * 자국·닳은 도색, 게임은 무늬 없는 한 색씩.
 *
 * ## 왜 한 벌인가
 *
 * 게임 모드는 실사 지형을 숨기고 성긴 로우폴리 지형을 그린다(SceneHost `setGameTerrain`). 도색이 실사 지면
 * 셰이더에만 있어 게임 모드에서는 활주로가 통째로 없었다(사용자 지적). 게임 지형에 도색을 따로 적으면 배치·치수가
 * 두 벌이 되어 한쪽만 고쳐진다 — 그래서 자리와 덮임은 여기 하나다. 유니폼도 SceneHost의 한 벌을 두 재질이 같이
 * 꽂는다(`setRunwaySurface`가 한 번 쓰면 두 지형이 같이 바뀐다).
 *
 * ## 배치와 거르기
 *
 * 배치와 치수는 ICAO 부속서 14의 표준이다(실측 아님 — core/runway.ts 머리말). 착륙대는 펴진 바닥
 * (core/runwayfloor.ts)과 같은 구역이다. 띠·숫자의 덮임은 픽셀 발자국 상자로 거르고, 발자국은 축마다 잰다(아래
 * 함수 주석). 화면 도함수는 호출측이 분기와 discard 앞에서 잰 것을 받는다(`dxy`) — 갈라진 분기 안의 도함수는
 * GLSL에서 정의되지 않는다.
 */

/** 활주로 유니폼 — 값은 `SceneHost.setRunwaySurface`가 쓴다. 실사 지면·게임 지형이 같은 객체를 꽂는다. */
export const RUNWAY_UNIFORM_DECL = /* glsl */`
uniform vec4 uRunway;              // (cos h, sin h, 길이 [m], 반폭 [m]) — NED 원점에서 heading 방향
uniform float uRunwayOn;           // 0이면 포장면을 칠하지 않는다(폭을 모를 때 — core/runway.ts)
uniform vec4 uRunwayArea;          // (과주로 [m], 착륙대 반폭 [m], 착륙대 끝 너머 [m], 0) — 착륙대는 펴진 바닥과 같은 구역
uniform vec4 uRunwayNum;           // 활주로 번호 (시단 쪽 십·일, 맞은편 십·일) — 모르면 -1이고 번호를 칠하지 않는다
uniform vec4 uRunwayDash;          // 중심선 (줄 길이, 주기 — 줄 하나면 0, 시단에서 시작, 0) [m] — 줄 길이 0이면 없다
uniform vec4 uRunwayAim;           // 조준점 (시단에서 시작, 줄 길이, 폭, 두 줄 안쪽 간격) [m]
`;

/** 자리·덮임 함수 — 조각 셰이더 앞머리, `RUNWAY_UNIFORM_DECL` 뒤. 다른 조각에 기대지 않는다. */
export const RUNWAY_GLSL = /* glsl */`
// ---- 활주로 도색 — 띠·숫자의 덮임을 픽셀 발자국 상자로 거른다(발자국은 축마다 — 아래). 가까이선 칼날, 멀어지면
// 폭/발자국만큼 옅어진다(멀리서 지글거리지 않게). 좌표는 활주로 축 기준 [m]. 치수는 ICAO 부속서 14의 표준이다(실측
// 아님). 길이로 정해지는 배치(중심선 줄·주기, 조준점)는 core/runway.ts가 셈해 유니폼으로 준다 — 시험이 닿는 곳이다.

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

// 아래 도색 함수는 발자국을 **축마다** 받는다 — pa 활주로 축 방향, pc 가로 방향(읽는 이의 u가 가로, v가 축이다).
// 비스듬히 보면 축 방향 발자국만 늘어나므로, 등방 발자국으로 거르면 가는 가로 띠(중심선·측면 표지)가 앞쪽
// 100~200 m에서 거의 사라졌다(v1.92 리뷰 실측). 조기 반환 경계는 발자국만큼 넓힌다 — 좁으면 멀리서 거른 띠의
// 가장자리가 그 경계에서 잘려 점선처럼 기었다(같은 리뷰).

// 숫자 하나 — 칸 가로 3 m(u, 읽는 이의 오른쪽이 +) · 세로 9 m(v, 읽는 위쪽이 +), 획 0.9 m. pu·pv는 u·v 방향 발자국
float grDigit(float d, vec2 uv, float pu, float pv) {
  if (d < 0.0 || uv.x < -1.0 - pu || uv.x > 4.0 + pu || uv.y < -1.0 - pv || uv.y > 10.0 + pv) return 0.0;
  const float W = 3.0;
  const float H = 9.0;
  const float S = 0.9;
  int k = clamp(int(d + 0.5), 0, 9);
  if (k == 1) return grBand(uv.x - 0.5 * W, 0.5 * S, pu) * grBand(uv.y - 0.5 * H, 0.5 * H, pv);
  int m = GR_SEG[k];
  float bu = grBand(uv.x - 0.5 * W, 0.5 * W, pu);
  float lu = grBand(uv.x - 0.5 * S, 0.5 * S, pu);
  float ru = grBand(uv.x - (W - 0.5 * S), 0.5 * S, pu);
  float top = grBand(uv.y - 0.75 * H, 0.25 * H, pv);
  float bot = grBand(uv.y - 0.25 * H, 0.25 * H, pv);
  float c = 0.0;
  if ((m & 1) != 0) c = max(c, bu * grBand(uv.y - (H - 0.5 * S), 0.5 * S, pv));
  if ((m & 2) != 0) c = max(c, ru * top);
  if ((m & 4) != 0) c = max(c, ru * bot);
  if ((m & 8) != 0) c = max(c, bu * grBand(uv.y - 0.5 * S, 0.5 * S, pv));
  if ((m & 16) != 0) c = max(c, lu * bot);
  if ((m & 32) != 0) c = max(c, lu * top);
  if ((m & 64) != 0) c = max(c, bu * grBand(uv.y - 0.5 * H, 0.5 * S, pv));
  return c;
}

// 활주로 번호 한 끝 — num (십, 일), s 시단에서 활주로 안쪽 [m], x 읽는 이의 오른쪽 [m]. 두 칸(각 3 m)이 가운데
// 1.5 m를 두고 선다. 시단 줄무늬(6~36 m) 끝에서 12 m 띄운 48~57 m 자리다
float grDesignation(vec2 num, float s, float x, float pa, float pc) {
  if (num.x < 0.0 || s < 46.0 - pa || s > 59.0 + pa || abs(x) > 5.5 + pc) return 0.0;
  float v = s - 48.0;
  return max(grDigit(num.x, vec2(x + 3.75, v), pc, pa), grDigit(num.y, vec2(x - 0.75, v), pc, pa));
}

// 시단 줄무늬(피아노 건반) — 시단에서 6~36 m, 축 양쪽 같은 수의 줄. 줄과 칸이 같은 너비이고 가운데 칸만
// 두 배다. 바깥 끝은 가장자리에서 3 m 안(최대 축에서 27 m) — 고흥 45 m 폭은 12줄, 너비 1.63 m
float grPiano(float s, float x, float halfW, float pa, float pc) {
  if (s < 4.0 - pa || s > 38.0 + pa) return 0.0;
  float nSide = halfW <= 9.0 ? 2.0 : halfW <= 11.5 ? 3.0 : halfW <= 15.0 ? 4.0 : halfW <= 22.5 ? 6.0 : 8.0;
  float outer = min(halfW - 3.0, 27.0);
  float sw = outer / (2.0 * nSide);
  float ax = abs(x);
  // 줄 k는 축에서 (2k+1)·sw ~ (2k+2)·sw — 가운데 (2k+1.5)·sw, 주기 2·sw
  float keys = grStripes(ax - 1.5 * sw, 2.0 * sw, 0.5 * sw, pc)
             * grBand(ax - 0.5 * (sw + outer), 0.5 * (outer - sw), pc);
  return keys * grBand(s - 21.0, 15.0, pa);
}

// 중심선 — 너비 0.9 m 줄을 양 끝에서 a0(69 m) 안쪽 구간에 고르게 깐다. 줄 길이·주기는 core/runway.ts
// centerlineLayout이 셈한다(줄 + 칸 50~75 m, 줄 ≥ 칸·30 m, 양 끝이 온 줄 — 고흥은 30 m 줄 21개, 주기 51.85 m)
float grCenterline(float along, float x, float L, float pa, float pc) {
  float s = uRunwayDash.x;
  float P = uRunwayDash.y;
  float a0 = uRunwayDash.z;
  if (s <= 0.0 || along < a0 - pa || along > L - a0 + pa || abs(x) > 1.0 + pc) return 0.0;
  float dash = P > 0.0 ? grStripes(along - (a0 + 0.5 * s), P, 0.5 * s, pa) : 1.0;
  return dash * grBand(x, 0.45, pc) * grBand(along - 0.5 * L, 0.5 * L - a0, pa);
}

// 과주로 갈매기표 — t 시단 밖으로 [m](0이 시단). 꼭짓점이 활주로 쪽을 가리키는 45도 줄, 30 m 간격, 너비 0.9 m.
// k = t - |x|가 한 갈매기 위에서 일정하다 — 줄의 k 방향 반폭은 0.45의 루트2배, k의 발자국은 두 축 발자국의 합
float grChevron(float t, float x, float over, float pa, float pc) {
  if (t < -pa || t > over + pa) return 0.0;
  return grStripes(t - abs(x) - 6.0, 30.0, 0.64, pa + pc) * grBand(t - 0.5 * over, 0.5 * over, pa);
}

// 활주로 축 좌표와 축마다 발자국 — p 세계 위치(렌더 x = e, z = -n), dxy 세계 xz의 화면 도함수(dFdx의 x·z, dFdy의
// x·z). 돌려주는 값은 (along 시단에서 축 방향 [m], across 축의 오른쪽이 + [m], pa 축 방향 발자국 [m], pc 가로
// 발자국 [m]) — 발자국은 세계 xz 도함수를 활주로 축으로 돌려 잰다
vec4 grRunwayAxes(vec3 p, vec4 dxy) {
  vec2 ne = vec2(-p.z, p.x);
  float along = dot(ne, uRunway.xy);
  float across = dot(ne, vec2(-uRunway.y, uRunway.x));
  float pa = max(abs(dxy.x * uRunway.y - dxy.y * uRunway.x) + abs(dxy.z * uRunway.y - dxy.w * uRunway.x), 1.0e-3);
  float pc = max(abs(dxy.x * uRunway.x + dxy.y * uRunway.y) + abs(dxy.z * uRunway.x + dxy.w * uRunway.y), 1.0e-3);
  return vec4(along, across, pa, pc);
}

// 비행장 층마다 몫 (착륙대, 포장면, 흰 도색, 노란 도색) 각 0~1 — ax는 grRunwayAxes. 층은 안으로 겹친다(도색 ⊂ 포장면
// ⊂ 착륙대)이므로 안쪽 몫은 바깥 몫을 넘지 않게 자르고, 칠할 때는 안쪽 층이 **바깥 층의 몫만** 바꾼다:
//     c = mix(바탕, 풀, f.x);  c += f.y·(아스팔트 − 풀) + f.z·(흰색 − 아스팔트) + f.w·(노랑 − 아스팔트)
// 덮임을 곱해 섞으면(mix(c, 흰색, 흰 덮임 × 포장면)) 가장자리에 붙은 측면 표지가 두 번 걸러져 멀리서 중심선보다 40 %
// 어둡고 움직이면 깜빡였다(v1.94 리뷰 실측). 착륙대 경계는 발자국만큼만 부드럽다 — 예전엔 40~60 m에 걸쳐 섞어 들·
// 비닐하우스 위에 흐린 띠가 얹혀 보였다(사용자 지적). 시단 사이는 흰색(측면 표지·시단 줄무늬·번호·중심선·조준점),
// 과주로는 노란 갈매기표이고, 맞은편 끝은 남쪽으로 읽으므로 가로를 뒤집는다
vec4 grAirfield(vec4 ax) {
  float along = ax.x;
  float across = ax.y;
  float pa = ax.z;
  float pc = ax.w;
  float L = uRunway.z;
  float halfW = uRunway.w;
  float over = uRunwayArea.x;
  float field = grBand(across, uRunwayArea.y, pc) * grBand(along - 0.5 * L, 0.5 * L + uRunwayArea.z, pa);
  if (field <= 0.001) return vec4(0.0);
  float paved = min(grBand(across, halfW, pc) * grBand(along - 0.5 * L, 0.5 * L + over, pa), field);
  if (paved <= 0.001) return vec4(field, paved, 0.0, 0.0);
  float onRunway = grBand(along - 0.5 * L, 0.5 * L, pa);
  float sF = L - along;
  float white = grBand(abs(across) - (halfW - 0.45), 0.45, pc) * onRunway;
  white = max(white, max(grPiano(along, across, halfW, pa, pc), grPiano(sF, -across, halfW, pa, pc)));
  white = max(white, max(grDesignation(uRunwayNum.xy, along, across, pa, pc),
                         grDesignation(uRunwayNum.zw, sF, -across, pa, pc)));
  white = max(white, grCenterline(along, across, L, pa, pc));
  // 조준점 — (시작, 길이, 폭, 안쪽 간격)은 core/runway.ts aimingPoint가 활주로 길이의 열에서 고른다
  vec4 aim = uRunwayAim;
  float aimX = grBand(abs(across) - 0.5 * (aim.w + aim.z), 0.5 * aim.z, pc);
  white = max(white, aimX * max(grBand(along - (aim.x + 0.5 * aim.y), 0.5 * aim.y, pa),
                                grBand(sF - (aim.x + 0.5 * aim.y), 0.5 * aim.y, pa)));
  float yel = max(grChevron(-along, across, over, pa, pc), grChevron(along - L, -across, over, pa, pc));
  white = min(white, paved);
  return vec4(field, paved, white, min(yel, paved - white));
}
`;

/** 게임 지형의 세계 위치 — 정점·조각이 같은 선언을 끼운다. */
export const RUNWAY_GAME_VARYING_DECL = /* glsl */`
varying vec3 vRunwayWorld;
`;

/** 게임 지형 정점 — `<fog_vertex>` 뒤. */
export const RUNWAY_GAME_VERT_BODY = /* glsl */`
  vRunwayWorld = (modelMatrix * vec4(transformed, 1.0)).xyz;
`;

/** 게임 지형의 활주로 색 (선형) — sRGB 감각으로 고른 색을 2.2제곱해 적었다. 로우폴리 램프(core/gamestyle.ts)처럼
 *  무늬 없이 한 색씩이다. 흰 도색은 램프의 눈(sRGB 0.90 위)보다 어둡게 둔다 — 게임 후처리의 블룸 문턱이 설산에
 *  걸리게 맞춰져 있어(SceneHost `GAME_POST`) 눈만큼 밝으면 도색이 번져 빛난다. 표시 값이다. */
export const RUNWAY_GAME_GLSL = /* glsl */`
const vec3 GAME_RW_STRIP   = vec3(0.268, 0.516, 0.106);   // 깎은 풀밭 — sRGB (0.55, 0.74, 0.36), 들판 (0.44, 0.67, 0.31)보다 밝게
const vec3 GAME_RW_ASPHALT = vec3(0.087, 0.093, 0.106);   // 아스팔트 — sRGB (0.33, 0.34, 0.36)
const vec3 GAME_RW_PAINT   = vec3(0.681, 0.681, 0.646);   // 흰 도색 — sRGB (0.84, 0.84, 0.82)
const vec3 GAME_RW_YELLOW  = vec3(0.914, 0.579, 0.036);   // 노란 갈매기표 — sRGB (0.96, 0.78, 0.22)
`;

/** 게임 지형 조각 — `<color_fragment>` 뒤(정점색 램프가 곱해진 뒤). 화면 도함수는 분기 앞에서 한 번 잰다. 알베도만
 *  바꾸므로 낱면 음영·대기 원근은 그대로 탄다. */
export const RUNWAY_GAME_FRAG_BODY = /* glsl */`
  {
    vec3 rwDx = dFdx(vRunwayWorld);
    vec3 rwDy = dFdy(vRunwayWorld);
    if (uRunwayOn > 0.5) {
      // 층마다 몫 — 안쪽 층은 바깥 층의 몫만 바꾼다(grAirfield 주석, 실사 지면과 같은 셈)
      vec4 af = grAirfield(grRunwayAxes(vRunwayWorld, vec4(rwDx.xz, rwDy.xz)));
      vec3 c = mix(diffuseColor.rgb, GAME_RW_STRIP, af.x);
      c += af.y * (GAME_RW_ASPHALT - GAME_RW_STRIP);
      diffuseColor.rgb = c + af.z * (GAME_RW_PAINT - GAME_RW_ASPHALT) + af.w * (GAME_RW_YELLOW - GAME_RW_ASPHALT);
    }
  }
`;
