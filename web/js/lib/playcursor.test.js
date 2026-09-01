/** lib/playcursor.js — 재생 커서 수치 테스트.

핵심은 하나다: **1×는 정말 1×여야 한다.** 프레임당 샘플로 세던 시절의 회귀(stride가 큰
결과에서 저속 배속이 요청보다 빨라지던 것)를 여기서 못박는다.
*/

import assert from "node:assert/strict";
import { test } from "node:test";

import { atEnd, dtSample, indexAt, isPlayable } from "./playcursor.js";

test("dtSample은 첫 두 샘플의 간격이고, 샘플이 부족하면 0이다", () => {
  assert.equal(dtSample([0, 0.02, 0.04]), 0.02);
  assert.equal(dtSample([0]), 0);
  assert.equal(dtSample([]), 0);
});

test("샘플이 부족하거나 간격이 0이면 재생 불가라고 말한다", () => {
  assert.equal(isPlayable([0, 0.02]), true);
  assert.equal(isPlayable([0]), false);
  assert.equal(isPlayable([]), false);
  assert.equal(isPlayable([0, 0]), false, "간격 0 — 무한 재생이 되면 안 된다");
});

test("1×는 정말 1× — stride가 커도 실시간 1초에 시뮬 1초가 흐른다", () => {
  // stride가 큰 결과: 샘플 간격 0.5 s. 프레임당 샘플로 세면 40 ms 프레임마다
  // 최소 1샘플(=0.5 s)이 흘러 12.5배 빨라진다. 벽시계 기준이면 그럴 일이 없다.
  const dt = 0.5, n = 1000;
  const idx = indexAt(0, 0, 1000, 1, dt, n); // 벽시계 1초, 1배속
  assert.equal(idx, 2, "1초 / 0.5초 = 샘플 2개");
});

test("배속이 정확히 곱해진다", () => {
  const dt = 0.02, n = 100000;
  for (const speed of [1, 2, 5, 10, 20]) {
    assert.equal(indexAt(0, 0, 1000, speed, dt, n), Math.round(speed / dt));
  }
});

test("여러 번 나눠 진행해도 한 번에 진행한 것과 같다 (누적 오차 없음)", () => {
  // 기준점을 다시 잡지 않는 한 경과는 절대시각에서 계산되므로 프레임률과 무관하다
  const dt = 0.02, n = 100000, speed = 5;
  const once = indexAt(0, 0, 1000, speed, dt, n);
  let idx = 0;
  for (let ms = 40; ms <= 1000; ms += 40) idx = indexAt(0, 0, ms, speed, dt, n);
  assert.equal(idx, once);
});

test("끝을 넘지 않는다", () => {
  const n = 10;
  assert.equal(indexAt(0, 0, 1e9, 20, 0.02, n), n - 1);
  assert.equal(atEnd(n - 1, n), true);
  assert.equal(atEnd(n - 2, n), false);
});

test("기준점을 옮기면 거기서부터 센다 (배속 변경·슬라이더 조작)", () => {
  const dt = 0.02, n = 100000;
  assert.equal(indexAt(500, 0, 1000, 1, dt, n), 500 + 50);
  assert.equal(indexAt(500, 1000, 1000, 1, dt, n), 500, "경과 0이면 제자리");
});

test("말이 안 되는 간격·샘플 수는 조용히 통과하지 않는다", () => {
  assert.throws(() => indexAt(0, 0, 100, 1, 0, 10), /간격/);
  assert.throws(() => indexAt(0, 0, 100, 1, -0.02, 10), /간격/);
  assert.throws(() => indexAt(0, 0, 100, 1, 0.02, 0), /샘플 수/);
});
