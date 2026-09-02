/** glTF 로컬축 ↔ FRD 동체축 — 모델을 자세대로 세우는 회전의 열벡터 (NED 성분).
 *
 * ## 왜 별도 모듈인가
 *
 * 절차 메시(`lib/uavmesh.js`)는 정점을 **FRD 성분 그대로** 저장했다. 그래서 자세 행렬의
 * 열이 곧 `(forward, right, down)`이었다. GLB는 다르다 — 블렌더 Z-up으로 만들고 glTF가
 * Y-up으로 내보내므로 로컬축이 다시 한 번 돌아 있다. 그 한 겹을 여기서 흡수하지 않으면
 * 어댑터 안에서 축 사상과 뒤섞여 부호 실수가 난다.
 *
 * ## 사상 — GLB 노드 좌표로 확인했다
 *
 * 생성 스크립트가 `FRD x(전방)=+Y, y(우측)=+X, z(하방)=−Z`(블렌더)로 만들고, glTF Y-up
 * 변환이 `블렌더(X,Y,Z) → glTF(X, Z, −Y)`를 건다. 결과:
 *
 *     로컬 +X = 우현      로컬 +Y = 위(= −down)     로컬 +Z = 후방(= −forward)
 *
 * 주석만 믿지 않고 실측했다(`shahed136.glb`). 아래는 **노드 중심**이다 —
 * `translation + 메시 bbox 중심`이지 `translation`만이 아니다. 둘을 섞으면 재확인할 때
 * 어긋난 것처럼 보인다(`Fin_L/R`은 translation이 아예 없고 메시로만 자리를 갖는다):
 *
 *     Propeller      중심 Zc = +1.84   ← 가장 뒤. 기수는 −Z   (translation z = 1.80)
 *     Elevon_In_R    중심 Xc = +0.56   ← 우현이 +X
 *     Elevon_In_L    중심 Xc = −0.56
 *     Fin_L/R        중심 Xc = ∓1.24   ← 익단 부근, 스팬 2.504 m와 정합 (translation 없음)
 *
 * ## 이 층은 렌더러를 모른다
 *
 * 반환은 전부 NED 성분이다. three 축으로 옮기는 일은 어댑터의 `toWorld` 한 줄이 맡는다 —
 * `lib/attitude.js`·`lib/camera.js`와 같은 규약이고, 축 사상이 한 곳에 남는다.
 */

import type { BodyAxes, Vec3 } from "../lib/attitude.ts";

/** 동체축 셋은 `src/lib/attitude.ts`의 것을 그대로 쓴다.
 *
 * 여기서 `readonly number[]`로 다시 선언하면 그 파일이 막으려던 구멍이 되살아난다 —
 * 길이 2짜리 배열이 통과하고 `v[2]!`가 `undefined`를 `number`로 둔갑시킨다. 좁히기는
 * 한 곳(`attitude.ts`)에서만 한다. */
export type BodyAxesNed = BodyAxes;

/** 모델 로컬축이 NED에서 어디를 향하는가 — 자세 행렬의 세 열. */
export interface ModelColumnsNed {
  /** 로컬 +X (우현) */ x: Vec3;
  /** 로컬 +Y (위) */ y: Vec3;
  /** 로컬 +Z (후방) */ z: Vec3;
}

// 튜플이라 인덱스 단언(`!`)이 필요 없다 — 그것이 위 타입을 공유하는 이유다.
const neg = (v: Vec3): Vec3 => [-v[0], -v[1], -v[2]];

/** 동체축 → 모델 로컬축의 열. **행렬식 +1이라 거울상이 되지 않는다.**
 *
 *     로컬 X = right,  로컬 Y = −down,  로컬 Z = −forward
 */
export function modelColumnsNed(axes: BodyAxesNed): ModelColumnsNed {
  return { x: axes.right, y: neg(axes.down), z: neg(axes.forward) };
}

/** 세 열의 행렬식 — +1이어야 손대칭이 보존된다(거울상 기체가 안 나온다). */
export function determinant(c: ModelColumnsNed): number {
  const [a, b, d] = [c.x, c.y, c.z];
  return (
    a[0] * (b[1] * d[2] - b[2] * d[1])
    - a[1] * (b[0] * d[2] - b[2] * d[0])
    + a[2] * (b[0] * d[1] - b[1] * d[0])
  );
}

/** 모델 로컬 방향 벡터를 NED로 — 테스트가 "기수가 어디를 보는가"를 렌더러 없이 묻는 통로. */
export function localToNed(c: ModelColumnsNed, local: Vec3): Vec3 {
  return [
    c.x[0] * local[0] + c.y[0] * local[1] + c.z[0] * local[2],
    c.x[1] * local[0] + c.y[1] * local[1] + c.z[1] * local[2],
    c.x[2] * local[0] + c.y[2] * local[1] + c.z[2] * local[2],
  ];
}

/** 모델 로컬에서 기수가 향하는 방향. **실측으로 확인한 상수**(프로펠러가 +Z에 있다). */
export const LOCAL_NOSE: Vec3 = [0, 0, -1];
/** 모델 로컬 우현. */
export const LOCAL_STARBOARD: Vec3 = [1, 0, 0];
/** 모델 로컬 상방. */
export const LOCAL_UP: Vec3 = [0, 1, 0];
