import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { refineGrid } from "./refine.ts";

const at = (g: { elev: Float32Array; cols: number }, r: number, c: number) => g.elev[r * g.cols + c]!;

describe("refineGrid — 그릴 때만 2배 촘촘히, 3차 보간", () => {
  it("크기는 (2·rows−1)×(2·cols−1)이고 짝수 칸은 원래 표본 그대로다", () => {
    const src = Float32Array.from([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]);
    const g = refineGrid(src, 3, 4);
    assert.equal(g.rows, 5);
    assert.equal(g.cols, 7);
    for (let r = 0; r < 3; r++) for (let c = 0; c < 4; c++) assert.equal(at(g, 2 * r, 2 * c), src[r * 4 + c]);
  });

  it("고른 경사는 그대로 고른 경사다 — 3차 보간이 직선을 재현한다", () => {
    const src = new Float32Array(6 * 6);
    for (let r = 0; r < 6; r++) for (let c = 0; c < 6; c++) src[r * 6 + c] = 3 * c + 2 * r;
    const g = refineGrid(src, 6, 6);
    for (let r = 2; r < 9; r++) for (let c = 2; c < 9; c++) {
      assert.ok(Math.abs(at(g, r, c) - (1.5 * c + 1 * r)) < 1e-4, `(${r},${c})`);
    }
  });

  it("외톨이 꼭대기가 피라미드가 아니라 둥글다 — 꼭대기 옆 중간점이 직선 보간보다 높다", () => {
    const src = new Float32Array(7 * 7);
    src[3 * 7 + 3] = 60;
    const g = refineGrid(src, 7, 7);
    assert.equal(at(g, 6, 6), 60, "꼭대기 높이는 그대로");
    assert.ok(at(g, 6, 7) > 30, `옆 중간점 ${at(g, 6, 7).toFixed(1)} — 직선이면 30`);
    assert.ok(at(g, 6, 7) <= 60);
  });

  it("넘침을 자른다 — 계단 옆에 원래 범위를 벗어나는 둔덕·고랑이 생기지 않는다", () => {
    const src = new Float32Array(1 * 8);
    for (let c = 0; c < 8; c++) src[c] = c < 4 ? 0 : 50;
    const g = refineGrid(src, 1, 8);
    for (let c = 0; c < g.cols; c++) assert.ok(at(g, 0, c) >= 0 && at(g, 0, c) <= 50, `${c}: ${at(g, 0, c)}`);
    assert.ok(at(g, 0, 5) === 0 && at(g, 0, 9) === 50, "계단 바로 옆 평지는 평지다");
  });

  it("결측 — 지지 범위에만 있으면 선형, 칸 꼭짓점에 있으면 결측", () => {
    const src = Float32Array.from([0, 10, 20, 30, 0, 10, 20, Number.NaN]);
    const g = refineGrid(src, 2, 4);
    assert.ok(Number.isNaN(at(g, 1, 5)), "꼭짓점 결측 칸");
    assert.equal(at(g, 0, 1), 5, "지지 범위 밖이 성한 변은 3차, 여기선 직선이라 5");
    assert.ok(Number.isFinite(at(g, 1, 3)), "결측이 지지 범위에만 있는 칸은 선형으로 채운다");
  });
});
