/** 절차 마모를 GLB 재질에 물린다 — 텍스처 0장 규칙 아래에서 "새 플라스틱" 티를 벗긴다.
 *
 * GLSL 본문은 `shaders/wear.ts`, 여기는 three 결선이다. `applyAerialPerspective`와 같은
 * 규율을 지킨다:
 *
 * - **`onBeforeCompile`을 덮어쓰지 않고 잇는다.** 마모 → 에어리얼 순서로 걸리면 에어리얼
 *   래퍼가 마모 래퍼를 부르고, 치환은 서로 다른 앵커에 얹히므로 순서와 무관하게 옳다.
 *   (두 패치 모두 앵커 `#include` 줄을 지우지 않고 뒤에 덧붙인다 — 그래서 겹쳐진다.)
 * - **캐시 키를 잇는다.** 안 그러면 마모 없는 재질이 마모 있는 프로그램을 얻어 쓴다.
 * - 값은 재질별 유니폼이라 프로그램은 공유된다 — 재질 8종이 프로그램 1벌이다.
 *
 * ## 설정이 곧 이야기다
 *
 * 어디에 무엇이 끼는지는 재질 이름으로 정한다(`WEAR_BY_MATERIAL`, `models.ts`가 조회):
 * 기체 동체에는 패널라인과 배기 그을음, 발사관에는 진흙과 사용 흔적. 수치는 전부
 * **표시용 선택**이고 캡션이 밝힌다 — 실제 기체의 마모 상태가 아니다.
 */

import type { Material } from "three";

import {
  WEAR_FRAG_BODY, WEAR_GLSL, WEAR_NORMAL_BODY, WEAR_UNIFORM_DECL, WEAR_VARYING_DECL,
  WEAR_VERT_BODY,
} from "../shaders/wear.ts";
import { NOISE_GLSL } from "../shaders/noise.ts";

export interface WearConfig {
  /** 패널라인 간격 (로컬 x, y, z) [m] — 0이면 그 축 없음 */
  panel: [number, number, number];
  panelDepth: number;
  edge: number;
  dirt: number;
  /** 그을음이 로컬 z (시작→끝)로 짙어진다. [0, 0]이면 없음 */
  soot: [number, number];
  /** 진흙이 로컬 y (위→아래)로 짙어진다. [0, 0]이면 없음 */
  mud: [number, number];
  seed: number;
}

const NONE: [number, number] = [0, 0];

// 재질 이름 → 마모. 이름은 생성 스크립트가 정본이다 — models/<모델>/generate_*.py.
// (블록 주석에 경로 글롭을 넣으면 그 안의 */ 가 주석을 끊는다 — 그래서 줄 주석이다.)
export const WEAR_BY_MATERIAL: Readonly<Record<string, WearConfig>> = {
  // --- 기체 (전장 3.5 m, 동체 z −1.75…+1.77, 기수 −z) --------------------------
  // 패널: 동체 링 프레임(z 0.42 m 간격)과 날개 리브/스파(x 0.30 m). 그을음은 추진부 —
  // 프로펠러가 z=+1.84이고 엔진이 그 앞이라 +0.9부터 뒤로 짙어진다.
  Airframe: {
    panel: [0.30, 0, 0.42], panelDepth: 0.7, edge: 0.5, dirt: 0.35,
    soot: [0.9, 1.77], mud: NONE, seed: 3,
  },
  // 타면은 별 부품이라 패널 없이 힌지 쪽 마모와 때만.
  ControlSurface: {
    panel: [0, 0, 0], panelDepth: 0, edge: 0.6, dirt: 0.3,
    soot: NONE, mud: NONE, seed: 7,
  },
  // --- 발사관 (지상 장비 — 이야기의 대부분이 진흙과 긁힘) -------------------------
  LauncherOlive: {
    panel: [0.45, 0, 0.60], panelDepth: 0.5, edge: 0.6, dirt: 0.55,
    soot: NONE, mud: [0.75, 0.42], seed: 11,
  },
  LauncherFrame: {
    panel: [0, 0, 0], panelDepth: 0, edge: 0.7, dirt: 0.6,
    soot: NONE, mud: [0.80, 0.40], seed: 13,
  },
  Metal: {
    panel: [0, 0, 0], panelDepth: 0, edge: 0.85, dirt: 0.45,
    soot: NONE, mud: [0.65, 0.40], seed: 17,
  },
  DarkDetail: {
    panel: [0, 0, 0], panelDepth: 0, edge: 0.3, dirt: 0.4,
    soot: NONE, mud: [0.55, 0.35], seed: 19,
  },
  // CanisterInner는 뺀다 — 관 안쪽은 거의 안 보이고, 보일 때는 어둠이 이야기다.
};

/** 캡션 원장 — 마모는 표시용이다. */
export const WEAR_NOTES = {
  model:
    "기체·발사관의 패널라인·긁힘·오염·그을음·진흙은 절차 생성 표시 효과이며 실제 기체의 "
    + "상태·도장이 아닙니다.",
} as const;

/** 이 재질에 마모를 얹는다. 같은 재질에 두 번 불러도 안전하다. */
export function applyWear(material: Material, cfg: WearConfig): void {
  const m = material as Material & { __wear?: boolean };
  if (m.__wear) return;
  m.__wear = true;

  const prevCompile = material.onBeforeCompile;
  const prevKey = material.customProgramCacheKey;

  material.onBeforeCompile = function (shader, renderer) {
    prevCompile.call(this, shader, renderer);
    Object.assign(shader.uniforms, {
      uWearPanel: { value: cfg.panel },
      uWearPanelDepth: { value: cfg.panelDepth },
      uWearEdge: { value: cfg.edge },
      uWearDirt: { value: cfg.dirt },
      uWearSoot: { value: cfg.soot },
      uWearMud: { value: cfg.mud },
      uWearSeed: { value: cfg.seed },
    });
    shader.vertexShader = shader.vertexShader
      .replace("#include <common>", `#include <common>\n${WEAR_VARYING_DECL}`)
      .replace("#include <fog_vertex>", `#include <fog_vertex>\n${WEAR_VERT_BODY}`);
    shader.fragmentShader = shader.fragmentShader
      .replace("#include <common>",
        `#include <common>\n${WEAR_UNIFORM_DECL}\n${WEAR_VARYING_DECL}\n${NOISE_GLSL}\n${WEAR_GLSL}`)
      .replace("#include <metalnessmap_fragment>",
        `#include <metalnessmap_fragment>\n${WEAR_FRAG_BODY}`)
      .replace("#include <normal_fragment_begin>",
        `#include <normal_fragment_begin>\n${WEAR_NORMAL_BODY}`);
  };
  material.customProgramCacheKey = function () {
    return `wear-v1|${prevKey.call(this)}`;
  };
  material.needsUpdate = true;
}
