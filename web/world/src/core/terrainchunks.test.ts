import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { chunkIndices, chunkQuads } from "./terrainchunks.ts";

/** buildTerrainMesh와 같은 배치의 인덱스 — 칸 (r, c)마다 (a, b, d, b, f, d). */
function quadIndices(rows: number, cols: number, keep: (r: number, c: number) => boolean): number[] {
  const idx: number[] = [];
  for (let r = 0; r + 1 < rows; r++) {
    for (let c = 0; c + 1 < cols; c++) {
      if (!keep(r, c)) continue;
      const a = r * cols + c, b = a + 1, d = a + cols, f = d + 1;
      idx.push(a, b, d, b, f, d);
    }
  }
  return idx;
}

describe("chunkIndices — 지형을 블록으로 나눈다", () => {
  it("모든 삼각형이 정확히 한 조각에 든다 — 빠지거나 겹치지 않는다", () => {
    const idx = quadIndices(41, 37, (r, c) => (r * 7 + c * 3) % 5 !== 0);
    const chunks = chunkIndices(idx, 37, 8);
    const total = chunks.reduce((s, ch) => s + ch.indices.length, 0);
    assert.equal(total, idx.length);
    const seen = new Set<string>();
    for (const ch of chunks) {
      for (let k = 0; k < ch.indices.length; k += 3) {
        const tri = [ch.indices[k], ch.indices[k + 1], ch.indices[k + 2]].join(",");
        assert.ok(!seen.has(tri), `겹친 삼각형 ${tri}`);
        seen.add(tri);
      }
    }
  });

  it("조각 안의 칸은 그 블록 안에 있다", () => {
    const cols = 30;
    const chunks = chunkIndices(quadIndices(30, cols, () => true), cols, 10);
    assert.equal(chunks.length, 9);
    for (const ch of chunks) {
      for (let k = 0; k < ch.indices.length; k += 6) {
        const a = ch.indices[k]!;
        assert.equal(Math.floor(Math.floor(a / cols) / 10), ch.br);
        assert.equal(Math.floor((a % cols) / 10), ch.bc);
      }
    }
  });

  it("빈 블록은 내지 않는다 — 바다·안쪽 장에 가린 자리", () => {
    const chunks = chunkIndices(quadIndices(30, 30, (r) => r < 10), 30, 10);
    assert.deepEqual(chunks.map((c) => c.br), [0, 0, 0]);
  });

  it("조각 크기 — 촘촘한 장 약 3 km, 외곽 약 7.5 km", () => {
    assert.equal(chunkQuads(30) * 30, 3000);
    assert.ok(Math.abs(chunkQuads(45) * 45 - 7500) < 45);
    assert.ok(chunkQuads(1000) >= 16);
  });
});
