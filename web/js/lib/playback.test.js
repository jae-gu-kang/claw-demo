// 재생 진행 계산 — 경과 벽시계 → 표본 인덱스. 프레임당 고정 샘플로 세면 stride가
// 큰 결과에서 저속 배속의 몫이 1샘플 미만이라 잘리고 요청보다 빨리 재생된다.
import { test } from "node:test";
import assert from "node:assert/strict";

import { dtOf, indexAt } from "./playback.js";

test("indexAt: 배속 1×는 실시간 — 벽시계 2초에 시뮬 2초", () => {
  const i = indexAt({ fromIdx: 0, fromWall: 0, now: 2000, speed: 1, dtSample: 0.01, len: 10000 });
  assert.equal(i, 200); // 200샘플 × 0.01s = 2.0s
});

test("indexAt: stride가 커도 배속이 지켜진다 (프레임당 정수 샘플의 함정)", () => {
  // dt 0.5s짜리 성긴 결과에서 1×로 2초 → 시뮬 2초 = 4샘플. 프레임당 계산이면
  // 40 ms마다 최소 1샘플씩 밀려 25배 빨라진다
  for (const dtSample of [0.01, 0.1, 0.5]) {
    const i = indexAt({ fromIdx: 0, fromWall: 0, now: 2000, speed: 1, dtSample, len: 1e6 });
    assert.equal(i * dtSample, 2, `dt=${dtSample}에서 실효 배속이 1×가 아님`);
  }
});

test("indexAt: 기준점(fromIdx)에서 이어서 진행", () => {
  const i = indexAt({ fromIdx: 500, fromWall: 1000, now: 1400, speed: 5, dtSample: 0.01, len: 10000 });
  // 0.4초 × 5배 = 시뮬 2초 = 200샘플
  assert.equal(i, 700);
});

test("indexAt: 끝을 넘지 않는다", () => {
  const i = indexAt({ fromIdx: 0, fromWall: 0, now: 1e9, speed: 20, dtSample: 0.01, len: 300 });
  assert.equal(i, 299);
});

test("indexAt: 시간이 흐르지 않았으면 제자리 (기준점 그대로)", () => {
  const i = indexAt({ fromIdx: 42, fromWall: 5000, now: 5000, speed: 10, dtSample: 0.01, len: 10000 });
  assert.equal(i, 42);
});

test("indexAt: dtSample이 0이면 진행하지 않는다 — 0-나눗셈으로 NaN 인덱스 금지", () => {
  const i = indexAt({ fromIdx: 7, fromWall: 0, now: 5000, speed: 5, dtSample: 0, len: 100 });
  assert.equal(i, 7);
});

test("indexAt: 길이 1(단일 표본)에서도 0을 넘지 않는다", () => {
  const i = indexAt({ fromIdx: 0, fromWall: 0, now: 9999, speed: 1, dtSample: 0.01, len: 1 });
  assert.equal(i, 0);
});

test("dtOf: 표본 간격 — 표본이 2개 미만이면 0 (재생 불가 신호)", () => {
  assert.equal(dtOf([0, 0.02, 0.04]), 0.02);
  assert.equal(dtOf([1.5]), 0);
  assert.equal(dtOf([]), 0);
});

test("dtOf: 비단조·비유한 입력은 0 — 재생을 시작하지 않게", () => {
  assert.equal(dtOf([0, 0]), 0); // 간격 0
  assert.equal(dtOf([0, NaN]), 0);
});
