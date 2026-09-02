/** `web/js/lib/replay.js`의 타입 있는 얼굴 (이 앱이 쓰는 부분만). */

import { modeSpans as rawModeSpans, strideFor as rawStrideFor } from "../../../js/lib/replay.js";

/** 목표 표본 수(기본 1500)에 맞춘 다운샘플 간격. */
export function strideFor(nTotal: number, target = 1500): number {
  return rawStrideFor(nTotal, target) as number;
}

/** 연속 구간 — `i1`은 **배타적**이다(원본 규약). 필드 이름을 여기서 바꾸지 않는다:
 *  `views/sim.js`가 같은 함수를 쓰므로, 두 화면이 같은 어휘를 써야 대조가 된다. */
export interface ModeSpan { mode: string; i0: number; i1: number }

/** 모드 이름 시계열 → 구간. 화면이 "지금 어느 단계인가"를 말한다. */
export function modeSpans(modes: readonly string[]): ModeSpan[] {
  return rawModeSpans(modes) as ModeSpan[];
}
