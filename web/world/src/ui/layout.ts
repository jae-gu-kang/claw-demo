/** 가상환경 탭의 배치 규칙 — 순수 함수만. WorldTab.tsx가 JSX라 node --test로 못 읽으므로
 *  판정이 되는 값은 여기 둔다(다른 core/·lib/ 모듈과 같은 규율). */

/** 뷰포트 대비 캔버스 높이 상한 — 재생줄·판독까지 한 화면에 남기는 몫. */
export const VIEWPORT_FRAC = 0.62;
/** 폭 대비 상한 (2:1). 넓은 창에서 걸리는 쪽은 보통 위의 뷰포트 상한이다. */
export const WIDTH_FRAC = 0.5;
/** 아래로는 더 안 줄인다 — 이보다 낮으면 3D가 띠가 되어 지형을 못 읽는다. */
export const MIN_H = 360;

/** 캔버스 높이 — **2:1은 상한이지 고정비가 아니다.**
 *
 * 종전에는 정확히 2:1이었다(시야각이 폭에 따라 흔들리지 않게). 전면 배치로 폭이
 * 1560까지 넓어지면서 그 규칙이 780 px을 요구하는데, 그러면 재생 컨트롤과 판독이
 * 화면 밖으로 밀린다 — 3D를 크게 보려던 변경이 3D 말고는 아무것도 못 보게 만드는
 * 셈이다. 그래서 뷰포트에도 상한을 건다.
 *
 * 걸리는 쪽이 이기므로 넓은 창에서는 2:1보다 **납작**해진다. three
 * PerspectiveCamera는 **수직 FOV 고정**이라 그만큼 수평 시야가 넓어질 뿐,
 * 세로가 잘리는 것이 아니다 — 위아래로 보이던 것은 그대로 보인다.
 */
export function canvasHeight(width: number, viewportHeight: number): number {
  const byWidth = Math.round(width * WIDTH_FRAC);
  const byViewport = Math.round(viewportHeight * VIEWPORT_FRAC);
  return Math.max(MIN_H, Math.min(byWidth, byViewport));
}
