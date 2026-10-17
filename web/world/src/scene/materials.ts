/** 재질 셰이더 패치 — 지형(지표 피복·그림자·하늘 열림)과 게임 활주로. three 결선이고 GLSL 본문은 `shaders/`.
 *
 * `applyAerialPerspective`와 같은 규율을 지킨다:
 *
 * - **`onBeforeCompile`을 덮어쓰지 않고 잇는다.** 치환은 서로 다른 앵커에 얹히므로 순서와 무관하게 옳다
 *   (패치는 앵커 `#include` 줄을 지우지 않고 뒤에 덧붙인다 — 그래서 겹쳐진다).
 * - **캐시 키를 잇는다.** 안 그러면 패치 없는 재질이 패치 있는 프로그램을 얻어 쓴다.
 *
 * GLB 모델(기체·발사관)에는 아무 패치도 얹지 않는다 — 예전의 절차 마모(삼면 투영 패널라인·화면 곡률 긁힘·노이즈
 * 오염·그을음·진흙)는 걷어 냈다. 노이즈 얼룩과 반짝이는 가짜 긁힘이 인위적으로 읽혔고(사용자 지적), 이음선·점검판·
 * 스텐실은 이제 모델 형상이 직접 가진다(`models/detail_kit.py`). 모델의 실감은 하늘 환경광이 맡는다(`SceneHost`).
 */

import type { Material } from "three";

import { ATMOSPHERE_GLSL, ATMOSPHERE_UNIFORM_DECL } from "../shaders/atmosphere.ts";
import { CLOUD_COVER_GLSL, CLOUD_UNIFORM_DECL } from "../shaders/clouds.ts";
import {
  GROUND_FRAG_BODY, GROUND_GLSL, GROUND_LIGHT_BODY, GROUND_NORMAL_BODY, GROUND_UNIFORM_DECL,
  GROUND_VARYING_DECL, GROUND_VERT_BODY, GROUND_VERT_DECL,
} from "../shaders/ground.ts";
import { COAST_GLSL } from "../shaders/ocean.ts";
import {
  RUNWAY_GAME_FRAG_BODY, RUNWAY_GAME_GLSL, RUNWAY_GAME_VARYING_DECL, RUNWAY_GAME_VERT_BODY, RUNWAY_GLSL,
  RUNWAY_UNIFORM_DECL,
} from "../shaders/runway.ts";

import { NOISE_GLSL } from "../shaders/noise.ts";

/** 지형 재질에 지표 피복·지형 그림자·하늘 열림을 얹는다 — `shaders/ground.ts` 머리말 참조.
 *
 * `applyAerialPerspective`와 같은 규율: onBeforeCompile을 잇고 캐시 키를
 * 잇는다. 유니폼은 공유 벌(구름·대기·해안 거리장·표고 텍스처)을 그대로 꽂아야 한다 —
 * 호출측이 `Object.assign(shader.uniforms, ...)`로 넣도록 uniforms 인자를 받는다.
 *
 * **치환 자리 다섯이 전부 three 셰이더에 있어야 한다** — 하나라도 없으면 그 조각만 조용히
 * 빠져(예: 그림자 없이 피복만) 화면은 그럴듯하게 틀린다. `GROUND_ANCHORS`를 시험이 three
 * 원문과 대조한다(materials.test.ts). */
export const GROUND_ANCHORS = {
  vertex: ["#include <common>", "#include <fog_vertex>"],
  fragment: [
    "#include <common>", "#include <metalnessmap_fragment>", "#include <normal_fragment_begin>",
    "#include <lights_fragment_end>",
  ],
} as const;

export function applyGroundDetail(
  material: Material, uniforms: Record<string, { value: unknown }>,
): void {
  const m = material as Material & { __ground?: boolean };
  if (m.__ground) return;
  m.__ground = true;

  const prevCompile = material.onBeforeCompile;
  const prevKey = material.customProgramCacheKey;

  material.onBeforeCompile = function (shader, renderer) {
    prevCompile.call(this, shader, renderer);
    Object.assign(shader.uniforms, uniforms);
    shader.vertexShader = shader.vertexShader
      .replace("#include <common>", `#include <common>
${GROUND_VERT_DECL}`)
      .replace("#include <fog_vertex>", `#include <fog_vertex>
${GROUND_VERT_BODY}`);
    // 앞머리 순서가 곧 의존 순서다: 대기(하늘 반사) → 구름 유니폼 → 노이즈 → 구름 덮임 →
    // 해안 거리장 → 활주로 도색(shaders/runway.ts) → 지면. 대기·해안·노이즈는 가드가 있어 다른 패치가 또 넣어도
    // 안전하다. 활주로 도색은 지형 재질에 이 패치 하나만 넣는다(게임 지형은 applyGameRunway — 다른 재질).
    shader.fragmentShader = shader.fragmentShader
      .replace("#include <common>",
        `#include <common>
${GROUND_VARYING_DECL}
${ATMOSPHERE_UNIFORM_DECL}
${ATMOSPHERE_GLSL}
`
        + `${CLOUD_UNIFORM_DECL}
${NOISE_GLSL}
${CLOUD_COVER_GLSL}
${COAST_GLSL}
${GROUND_UNIFORM_DECL}
${RUNWAY_UNIFORM_DECL}
${RUNWAY_GLSL}
${GROUND_GLSL}`)
      .replace("#include <metalnessmap_fragment>",
        `#include <metalnessmap_fragment>
${GROUND_FRAG_BODY}`)
      .replace("#include <normal_fragment_begin>",
        `#include <normal_fragment_begin>
${GROUND_NORMAL_BODY}`)
      .replace("#include <lights_fragment_end>",
        `#include <lights_fragment_end>
${GROUND_LIGHT_BODY}`);
  };
  material.customProgramCacheKey = function () {
    return `ground-v2|${prevKey.call(this)}`;
  };
  material.needsUpdate = true;
}

/** 게임 지형 재질에 활주로를 칠한다 — 자리·덮임은 실사 지면과 한 벌(`shaders/runway.ts`), 색은 게임 벌이다.
 *
 * 게임 지형은 정점색 램프만 있는 로우폴리라(SceneHost `setGameTerrain`) 실사의 지표 피복은 걸지 않고 활주로만
 * 칠한다. 정점색이 곱해진 `<color_fragment>` 뒤에서 알베도를 바꾸므로 낱면 음영·대기 원근은 그대로 탄다.
 * `applyGroundDetail`과 같은 규율(잇는 onBeforeCompile·캐시 키, 공유 유니폼 객체를 그대로 꽂기)이고, 치환 자리는
 * `GAME_RUNWAY_ANCHORS` — 시험이 three 원문과 대조한다(materials.test.ts). */
export const GAME_RUNWAY_ANCHORS = {
  vertex: ["#include <common>", "#include <fog_vertex>"],
  fragment: ["#include <common>", "#include <color_fragment>"],
} as const;

export function applyGameRunway(
  material: Material, uniforms: Record<string, { value: unknown }>,
): void {
  const m = material as Material & { __gameRunway?: boolean };
  if (m.__gameRunway) return;
  m.__gameRunway = true;

  const prevCompile = material.onBeforeCompile;
  const prevKey = material.customProgramCacheKey;

  material.onBeforeCompile = function (shader, renderer) {
    prevCompile.call(this, shader, renderer);
    Object.assign(shader.uniforms, uniforms);
    shader.vertexShader = shader.vertexShader
      .replace("#include <common>", `#include <common>
${RUNWAY_GAME_VARYING_DECL}`)
      .replace("#include <fog_vertex>", `#include <fog_vertex>
${RUNWAY_GAME_VERT_BODY}`);
    shader.fragmentShader = shader.fragmentShader
      .replace("#include <common>", `#include <common>
${RUNWAY_GAME_VARYING_DECL}
${RUNWAY_UNIFORM_DECL}
${RUNWAY_GLSL}
${RUNWAY_GAME_GLSL}`)
      .replace("#include <color_fragment>", `#include <color_fragment>
${RUNWAY_GAME_FRAG_BODY}`);
  };
  material.customProgramCacheKey = function () {
    return `game-runway-v1|${prevKey.call(this)}`;
  };
  material.needsUpdate = true;
}
