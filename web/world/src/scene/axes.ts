/** 축 변환 — **이 앱의 유일한 자리**.
 *
 * 정본은 `web/js/lib/world3d.js`의 `nedToRender`이고 여기서는 타입만 씌워 재수출한다.
 * 사본을 만들지 않는 이유가 그 파일 머리말에 적혀 있다 — 사상을 렌더러에 두고 테스트가
 * 그것을 지역에서 다시 선언하면, 어댑터가 바뀌어도 테스트는 옛 사상 기준으로 계속
 * 초록이다. 지형 삼각형의 감김이 옳은지는 이 사상 아래에서만 판정된다.
 *
 *     x = e,  y = −d,  z = −n      (행렬식 +1 — 오른손 좌표계 보존)
 *
 * ## 렌더러 교체 가능성에 대해
 *
 * 옛 `views/worldrenderer.js`는 three를 자체 WebGL2로 갈아 끼울 수 있게 추상 계약을
 * 두었다. 애드온을 전면 허용하기로 하면서 **그 목표는 사실상 포기됐다** — GLTFLoader와
 * 후처리를 손으로 다시 쓰는 것은 현실적이지 않다. 그래서 남긴 것은 교체 가능성이
 * 아니라 **계층**이다: 재미있는 계산(자세·카메라·해수면·타면·발사관)은 전부 `core/`에
 * 순수 함수로 있고 테스트가 붙는다. 그 규율이 유지되는 한, 이 층이 얇게 남는다.
 */

import { nedToRender } from "../../../js/lib/world3d.js";

/** NED [n, e, d] → 렌더러 월드 [x, y, z]. */
export function toWorld(n: number, e: number, d: number): [number, number, number] {
  const v = nedToRender(n, e, d) as (number | undefined)[];
  return [v[0]!, v[1]!, v[2]!];
}

/** NED 벡터를 그대로 받는 형태. */
export function toWorldVec(v: readonly number[]): [number, number, number] {
  return toWorld(v[0]!, v[1]!, v[2]!);
}
