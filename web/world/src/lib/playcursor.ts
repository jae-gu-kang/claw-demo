/** `web/js/lib/playcursor.js`의 타입 있는 얼굴.
 *
 * **시뮬 탭과 같은 모듈을 쓴다** — 두 화면이 서로 다른 시각을 말하면 안 되기 때문이다
 * (`views/world.js`가 이 모듈을 뽑아낸 이유). 사본을 만들면 그 불변조건이 깨진다. */

import {
  atEnd as rawAtEnd, dtSample as rawDtSample, indexAt as rawIndexAt,
  isPlayable as rawIsPlayable,
} from "../../../js/lib/playcursor.js";

/** 표본 간 시간 [s] — 못 구하면 null. */
export function dtSample(t: readonly number[]): number | null {
  const v = rawDtSample(t) as number | null;
  return typeof v === "number" && Number.isFinite(v) && v > 0 ? v : null;
}

export function isPlayable(t: readonly number[]): boolean {
  return rawIsPlayable(t) as boolean;
}

/** 시작 인덱스·시작 시각·현재 시각·배속에서 지금 커서. */
export function indexAt(
  fromIdx: number, fromWallMs: number, nowMs: number, speed: number, dt: number, n: number,
): number {
  return rawIndexAt(fromIdx, fromWallMs, nowMs, speed, dt, n) as number;
}

export function atEnd(idx: number, n: number): boolean {
  return rawAtEnd(idx, n) as boolean;
}
