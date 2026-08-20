// 구간별 다항식 회귀 검증 — 정확 복원, 차수 클램프, 구간 배정, 경계 점프, 오류
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  evalFit,
  evalFitSlope,
  piecewisePolyfit,
  polyfit,
  rawCoeffs,
  sampleFit,
} from "./polyfit.js";

const close = (a, b, tol = 1e-9) =>
  assert.ok(Math.abs(a - b) <= tol, `|${a} - ${b}| > ${tol}`);

test("polyfit: 2차식 정확 복원 + 원영역 계수 + 기울기", () => {
  const xs = [0.1, 0.25, 0.4, 0.55, 0.7, 0.85];
  const f = (x) => 2 - 3 * x + 0.5 * x * x;
  const fit = polyfit(xs, xs.map(f), 2);
  for (const x of xs) close(evalFit(fit, x), f(x));
  close(evalFit(fit, 0.3), f(0.3)); // 격자점 밖 보간점
  const [a0, a1, a2] = rawCoeffs(fit);
  close(a0, 2, 1e-8); close(a1, -3, 1e-8); close(a2, 0.5, 1e-8);
  close(evalFitSlope(fit, 0.4), -3 + 0.4, 1e-8); // f' = -3 + x
});

test("polyfit: 차수 클램프 — 점 2개에 3차 요청 → 직선", () => {
  const fit = polyfit([1, 3], [10, 14], 3);
  assert.equal(fit.degree, 1);
  close(evalFit(fit, 1), 10);
  close(evalFit(fit, 3), 14);
  close(evalFit(fit, 2), 12); // 중간 = 선형
});

test("polyfit: 단일점 구간(h=0 방어) — 상수 적합, 기울기 0", () => {
  const fit = polyfit([5], [42], 2);
  assert.equal(fit.degree, 0);
  close(evalFit(fit, 5), 42);
  close(evalFit(fit, 100), 42); // 상수이므로 x 무관
  close(evalFitSlope(fit, 5), 0);
});

test("polyfit: 격자점 실질 중복(x 전부 동일) → 특이계로 coeffs=null", () => {
  const fit = polyfit([2, 2, 2], [1, 3, 5], 1);
  assert.equal(fit.coeffs, null);
});

test("polyfit: 평행이동 영역 컨디셔닝 — x∈[10,20] 3차", () => {
  const xs = [10, 12, 14, 16, 18, 20];
  const f = (x) => 1 + 0.2 * x - 0.03 * x * x + 0.004 * x ** 3;
  const fit = polyfit(xs, xs.map(f), 3);
  for (const x of xs) close(evalFit(fit, x), f(x), 1e-7);
  const a = rawCoeffs(fit);
  close(a[3], 0.004, 1e-7);
});

test("piecewisePolyfit: 구간 배정(경계점은 우측) + 구간별 정확 적합", () => {
  const xs = [0, 1, 2, 3, 4];
  const ys = [1, 1, 5, 5, 5]; // 경계 2에서 계단
  const pw = piecewisePolyfit(xs, ys, [2], 1);
  assert.equal(pw.error, undefined);
  assert.deepEqual(pw.segments.map((s) => s.n), [2, 3]);
  close(pw.maxResidual, 0);
  assert.equal(pw.joints.length, 1);
  close(pw.joints[0].x, 2);
  close(Math.abs(pw.joints[0].valueJump), 4); // 좌측 상수 1, 우측 상수 5
});

test("piecewisePolyfit: 연속 선형 데이터 → 경계 값·기울기 점프 ≈ 0", () => {
  const xs = [0, 0.5, 1, 1.5, 2, 2.5, 3];
  const ys = xs.map((x) => 2 * x + 1);
  const pw = piecewisePolyfit(xs, ys, [1.5], 2);
  close(pw.maxResidual, 0, 1e-8);
  close(pw.joints[0].valueJump, 0, 1e-8);
  close(pw.joints[0].slopeJump, 0, 1e-7);
});

test("piecewisePolyfit: 입력 검증 — 차수·경계 범위·빈 구간·중복 경계", () => {
  const xs = [0, 1, 2];
  const ys = [0, 1, 2];
  assert.ok(piecewisePolyfit(xs, ys, [], 0).error);
  assert.ok(piecewisePolyfit(xs, ys, [], 1.5).error);
  assert.ok(piecewisePolyfit(xs, ys, [0], 1).error); // 경계 = 최솟값
  assert.ok(piecewisePolyfit(xs, ys, [2], 1).error); // 경계 = 최댓값
  assert.ok(piecewisePolyfit(xs, ys, [0.4, 0.6], 1).error); // [0.4,0.6) 빈 구간
  assert.ok(piecewisePolyfit(xs, ys, [1, 1], 1).error); // 중복
  assert.ok(piecewisePolyfit([0], [1], [], 1).error); // 격자점 부족
  assert.ok(piecewisePolyfit([2, 0, 1], [0, 0, 0], [], 1).error); // xs 비정렬
  // 경계 없음(단일 구간)은 유효
  assert.equal(piecewisePolyfit(xs, ys, [], 1).error, undefined);
});

test("piecewisePolyfit: 구간 내 격자점 실질 중복(특이계) → error, 잔차 은폐 없음", () => {
  // 리뷰 S1: solve가 특이계에서 NaN을 내면 |NaN|>maxResidual이 false라
  // 잔차가 조용히 0으로 보고됨 — 특이계는 반드시 error로 표면화해야 함
  const pw = piecewisePolyfit([0, 1, 1, 1, 4], [0, 5, 5, 5, 5], [0.5], 2);
  assert.ok(pw.error);
});

test("sampleFit: 구간 사이 null 구분자 + 곡선값 일치", () => {
  const xs = [0, 1, 2, 3, 4];
  const ys = [1, 1, 5, 5, 5];
  const pw = piecewisePolyfit(xs, ys, [2], 1);
  const s = sampleFit(pw, 10);
  assert.equal(s.x.length, s.y.length);
  assert.equal(s.y.filter((v) => v === null).length, 1); // 경계 불연속을 선으로 잇지 않음
  close(s.y[0], evalFit(pw.segments[0].fit, s.x[0]));
  const last = s.y.length - 1;
  close(s.y[last], evalFit(pw.segments[1].fit, s.x[last]));
  // x는 단조 비감소 (null 위치 제외 모두 수치)
  for (let i = 1; i < s.x.length; i++) assert.ok(s.x[i] >= s.x[i - 1]);
});
