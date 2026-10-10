import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { AO_FLOOR, terrainShade } from "./terrainshade.ts";

const grid = (rows: number, cols: number, f: (r: number, c: number) => number): Float32Array => {
  const out = new Float32Array(rows * cols);
  for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) out[r * cols + c] = f(r, c);
  return out;
};

describe("terrainShade — 하늘 열림·볼록도", () => {
  it("평지는 막힘이 없고 볼록도 0이다", () => {
    const { ao, convex } = terrainShade(grid(30, 30, () => 12), 30, 30, 30);
    assert.ok(ao.every((v) => v === 1));
    assert.ok(convex.every((v) => v === 0));
  });

  it("고른 경사면도 막힘이 없다 — 평균과 같은 높이라 가림이 없다(가장자리 창 잘림 제외)", () => {
    const { ao } = terrainShade(grid(41, 41, (_r, c) => 0.5 * c * 30), 41, 41, 30);
    assert.ok(Math.abs(ao[20 * 41 + 20]! - 1) < 1e-6);
  });

  it("골짜기 바닥은 열림이 줄고 볼록도가 음수, 능선은 열림 1에 볼록도 양수", () => {
    // 동서로 뻗은 V자 골 — 바닥(c=30)이 가장 낮다
    const v = terrainShade(grid(61, 61, (_r, c) => Math.abs(c - 30) * 20), 61, 61, 30);
    const floor = 30 * 61 + 30;
    assert.ok(v.ao[floor]! < 0.85, `골 바닥 열림 ${v.ao[floor]}`);
    assert.ok(v.convex[floor]! < -0.5, `골 바닥 볼록도 ${v.convex[floor]}`);
    const ridge = terrainShade(grid(61, 61, (_r, c) => 600 - Math.abs(c - 30) * 20), 61, 61, 30);
    assert.equal(ridge.ao[floor], 1);
    assert.ok(ridge.convex[floor]! > 0.5, `능선 볼록도 ${ridge.convex[floor]}`);
  });

  it("깊을수록 더 어둡되 바닥값 밑으로는 안 내려간다", () => {
    const shallow = terrainShade(grid(61, 61, (_r, c) => Math.abs(c - 30) * 5), 61, 61, 30);
    const deep = terrainShade(grid(61, 61, (_r, c) => Math.abs(c - 30) * 60), 61, 61, 30);
    const i = 30 * 61 + 30;
    assert.ok(deep.ao[i]! < shallow.ao[i]!);
    assert.ok(deep.ao[i]! >= Math.fround(AO_FLOOR)); // Float32에 담긴 바닥값과 견준다
  });

  it("결측(NaN)을 해수면으로 보고 NaN을 흘리지 않는다", () => {
    const h = grid(20, 20, () => 50);
    h[5 * 20 + 5] = Number.NaN;
    const { ao, convex } = terrainShade(h, 20, 20, 30);
    assert.ok(ao.every(Number.isFinite) && convex.every(Number.isFinite));
  });

  it("간격이 커도(외곽 90 m) 반경이 칸 1 밑으로 안 줄어 0 나누기가 없다", () => {
    const { ao } = terrainShade(grid(15, 15, (r, c) => (r * 7 + c * 13) % 40), 15, 15, 900);
    assert.ok(ao.every(Number.isFinite));
  });
});
