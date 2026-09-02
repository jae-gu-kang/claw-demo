/** 에어리얼 퍼스펙티브를 재질에 물린다 — `FogExp2`를 대신한다.
 *
 * ## 왜 three의 fog 자리에 안 넣나
 *
 * `<fog_fragment>`는 `<colorspace_fragment>` **뒤**에 온다 — 즉 three의 안개는 sRGB로
 * 인코딩된 값에 섞인다. 산란은 선형 복사휘도에서 더해야 뜻이 맞으므로 `<opaque_fragment>`
 * 바로 뒤(= `gl_FragColor`가 막 정해진 자리, 톤매핑 전)에 넣는다.
 *
 * 그리고 three의 fog 유니폼은 `scene.fog` 객체에서만 채워지고 색 하나·밀도 하나뿐이라
 * 태양 방향을 실어 나를 수 없다. 공유 유니폼을 직접 꽂는다.
 *
 * ## 재질마다 불러야 한다
 *
 * `onBeforeCompile`은 재질 단위다. 빠뜨린 재질은 **거리에 상관없이 또렷하게** 남으므로
 * 화면에서 눈에 띈다(조용히 틀리지 않는다). 지금 부르는 곳: 지형·궤적(`SceneHost`),
 * GLB(`models.ts`). 하늘은 자기 셰이더가 같은 함수를 직접 부른다.
 */

import { Vector2, Vector3, type Material } from "three";

import {
  ATMOSPHERE_GLSL, ATMOSPHERE_UNIFORM_DECL, hazeForVisibility, sunColorRgb,
} from "../shaders/atmosphere.ts";

/** **한 벌만 만든다.** 재질마다 이 객체를 그대로 꽂으므로 `.value`를 바꾸면 전부 따라온다. */
const shared = {
  uSunDirWorld: { value: new Vector3(0.4, 0.6, 0.2) },
  uSunIntensity: { value: 1 },
  uHaze: { value: 1 },
};

export const atmosphereUniforms = shared;

/** 구름 유니폼 — 하늘과 바다(반사)가 같은 벌을 꽂는다. `shaders/clouds.ts`의 선언과 짝. */
const cloud = {
  uCloudCover: { value: 0.35 },
  // 밑면·두께는 표시용 고정값이다. 고흥의 여름 적운 밑면이 대개 1~2 km라 그 안에 뒀다.
  uCloudBase: { value: 1500 },
  uCloudThick: { value: 600 },
  uCloudWind: { value: new Vector2(4, 2) },
  uCloudTime: { value: 0 },
  // 표시 보정값 — 윤슬의 `uGlitterGain`과 같은 이유로 있다.
  uCloudGain: { value: 0.85 },
};

export const cloudUniforms = cloud;

/** 덮임·바람은 상태가 바뀔 때, 시각은 프레임마다. 둘 다 **표시 값**이다. */
export function setClouds(cover: number, windXZ: readonly [number, number]): void {
  cloud.uCloudCover.value = Math.min(Math.max(cover, 0), 1);
  cloud.uCloudWind.value.set(windXZ[0], windXZ[1]);
}

export function setCloudTime(timeSec: number): void {
  cloud.uCloudTime.value = timeSec;
}

/** 태양 방향(월드, 정규화)·세기·시정을 넣는다. 하늘과 지형이 **같은 값**을 본다.
 *
 * 돌려주는 것은 **대기를 지나 온 태양색**이다 — 직사광에 그대로 물려야 하늘만 노을이고
 * 지형은 한낮 조명인 화면이 안 된다. 반환값을 쓰는 쪽은 `SceneHost.setEnvironment` 하나다. */
export function setAtmosphere(
  sunDirWorld: readonly number[], sunElRad: number, sunIntensity: number, visibilityM: number,
): [number, number, number] {
  const haze = hazeForVisibility(visibilityM);
  shared.uSunDirWorld.value.set(sunDirWorld[0]!, sunDirWorld[1]!, sunDirWorld[2]!).normalize();
  shared.uSunIntensity.value = sunIntensity;
  shared.uHaze.value = haze;
  return sunColorRgb(sunElRad, haze);
}

/** 캡션 원장 — 화면이 밝혀야 하는 표시용 선택. `SURFACE_NOTES`와 같은 모양이다.
 *
 * 대기는 **비행동역학에 들어가지 않는다.** 시정 슬라이더는 시뮬 입력이 아니라 미
 * 소산계수를 움직일 뿐이고, 궤적·자세·타면은 이 값과 무관하다. */
export const ATMOSPHERE_NOTES = {
  model:
    "하늘·원경은 레일리 + 미 단일산란으로 그립니다 — 표시용 근사입니다. "
    + "원경은 시선을 따라 대기 밀도가 일정하다고 보며, 오존 흡수·다중산란·지구 곡률은 "
    + "넣지 않았습니다.",
  visibility:
    "가시거리 슬라이더는 미 소산계수를 움직이는 표시 값이며 시뮬 입력이 아닙니다 — "
    + "궤적·자세·타면은 이 값과 무관합니다.",
} as const;

/** 구름 캡션 원장. */
export const CLOUD_NOTES = {
  model:
    "구름은 절차 노이즈로 만든 2.5D 층운이며 실제 기상이 아닙니다 — 밑면 1,500 m · "
    + "두께 600 m는 표시용 고정값이고, 덮임 슬라이더는 시뮬 입력이 아닙니다. "
    + "지형·해면의 구름 그림자는 같은 덮임 함수를 한 표본으로 읽는 표시 근사입니다.",
  shadows:
    "그림자 맵은 기체·발사관만 드리웁니다 — 지형 능선의 자체 그림자는 없습니다"
    + "(30 km 도메인에 2,048 맵이면 텍셀이 15 m라 계단이 됩니다).",
} as const;

const VERT_DECL = "varying vec3 vAerialView;\n";
const VERT_BODY = `
  // 카메라에서 이 정점까지의 **월드** 벡터. 길이가 시선 거리, 방향이 산란각의 한 변이다.
  // (three의 vFogDepth는 뷰공간 z라 시야 가장자리에서 실제 거리보다 짧다.)
  vAerialView = (modelMatrix * vec4(transformed, 1.0)).xyz - cameraPosition;
`;

const FRAG_DECL = `
varying vec3 vAerialView;
${ATMOSPHERE_UNIFORM_DECL}
${ATMOSPHERE_GLSL}
`;

const FRAG_BODY = `
  {
    float s = length(vAerialView);
    vec3 dir = vAerialView / max(s, 1e-4);
    vec3 T, S;
    atmosphere(dir, uSunDirWorld, uSunIntensity, uHaze, s, T, S);
    // 선형 공간에서 소산 후 in-scattering을 더한다 — 톤매핑·색공간 변환 **전**이다.
    gl_FragColor.rgb = gl_FragColor.rgb * T + S;
  }
`;

/** 이 재질이 그리는 것에 대기 산란을 얹는다. 같은 재질에 두 번 불러도 안전하다. */
export function applyAerialPerspective(material: Material): void {
  const m = material as Material & { __aerial?: boolean };
  if (m.__aerial) return;
  m.__aerial = true;

  // **덮어쓰지 않고 잇는다.** GLTFLoader는 일부 KHR 확장에서 자기 `onBeforeCompile`을
  // 걸고, 그것을 날리면 그 재질만 조용히 다르게 그려진다. 지금 두 GLB에는 확장이 없어
  // three 기본값(빈 함수)이지만, 모델을 다시 구우면서 생길 수 있는 자리다.
  const prevCompile = material.onBeforeCompile;
  const prevKey = material.customProgramCacheKey;

  material.onBeforeCompile = function (shader, renderer) {
    prevCompile.call(this, shader, renderer);
    Object.assign(shader.uniforms, shared);
    shader.vertexShader = shader.vertexShader
      .replace("#include <common>", `#include <common>\n${VERT_DECL}`)
      .replace("#include <fog_vertex>", `#include <fog_vertex>\n${VERT_BODY}`);
    shader.fragmentShader = shader.fragmentShader
      .replace("#include <common>", `#include <common>\n${FRAG_DECL}`)
      .replace("#include <opaque_fragment>", `#include <opaque_fragment>\n${FRAG_BODY}`);
  };
  // **캐시 키를 갈라 둔다.** 안 그러면 three가 같은 형상의 미적용 재질에서 만든 프로그램을
  // 재사용해, 어떤 재질만 대기가 안 걸린 채로 남는다. 앞의 키를 붙여 두는 이유도 같다 —
  // 확장이 자기 키로 가르던 구분을 여기서 뭉개면 안 된다.
  material.customProgramCacheKey = function () {
    return `aerial-v1|${prevKey.call(this)}`;
  };
  material.needsUpdate = true;
}
