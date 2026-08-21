// 재생 유틸 검증 — stride 산정, 모드 구간 분할, 극값
import { test } from "node:test";
import assert from "node:assert/strict";

import { extent, flaggedNames, modeSpans, strideFor } from "./replay.js";

test("strideFor: 목표 점수 이하로 다운샘플", () => {
  assert.equal(strideFor(18000, 1500), 12);
  assert.equal(strideFor(1000, 1500), 1); // 이미 작으면 원해상도
  assert.equal(strideFor(1501, 1500), 2);
});

test("modeSpans: 연속 구간 분할 (경계 인덱스)", () => {
  const spans = modeSpans(["a", "a", "b", "b", "b", "c"]);
  assert.deepEqual(spans, [
    { mode: "a", i0: 0, i1: 2 },
    { mode: "b", i0: 2, i1: 5 },
    { mode: "c", i0: 5, i1: 6 },
  ]);
  assert.deepEqual(modeSpans([]), []);
});

test("extent: null(NaN 직렬화) 무시 극값", () => {
  assert.deepEqual(extent([3, null, 1, 2]), [1, 3]);
  assert.deepEqual(extent([null, null]), [0, 1]); // 전부 null — 안전 기본
});

test("flaggedNames: 뜬 플래그만 이름으로 — 고도 이탈이 DB 이탈로 오독되지 않게", () => {
  const env = (f) => ({ flags: f });
  assert.equal(flaggedNames(env({ alpha: [false, false], altitude: [false, true] })), "고도");
  assert.equal(flaggedNames(env({ alpha: [true], mach: [true], altitude: [false] })), "α·마하");
  assert.equal(flaggedNames(env({ alpha: [false] })), "—");
  // 엔진이 플래그를 추가해도 이름 그대로 통과 (미정의 라벨에 안전)
  assert.equal(flaggedNames(env({ nz: [true] })), "nz");
  assert.equal(flaggedNames({}), "—"); // 엔벨로프 없음/구버전 결과
});
