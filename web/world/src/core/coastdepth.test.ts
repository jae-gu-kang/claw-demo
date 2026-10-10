import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { COAST_DEPTH, coastalDepths } from "./coastdepth.ts";
import { CELL } from "./seamask.ts";

/** 문자 격자 → (표고, 판정). `#` 땅(값은 heights), `~` 바다(0), `?` 결측. 행 0이 그림의 첫 줄이다(여기선 방향 무관). */
function grid(art: string[], landZ = 20) {
  const rows = art.length;
  const cols = art[0]!.length;
  const elev = new Float32Array(rows * cols);
  const cells = new Uint8Array(rows * cols);
  art.forEach((line, r) => [...line].forEach((ch, c) => {
    const i = r * cols + c;
    if (ch === "#") { elev[i] = landZ; cells[i] = CELL.LAND; }
    else if (ch === "?") { elev[i] = Number.NaN; cells[i] = CELL.MISSING; }
    else { elev[i] = 0; cells[i] = CELL.SEA; }
  }));
  return { elev, cells, rows, cols };
}

describe("coastalDepths — 바다 쪽 고리에 표시용 수심", () => {
  it("땅은 그대로, 맞닿은 바다는 땅 높이에 따라 1~15 m 내려간다", () => {
    const g = grid(["~~~~~~", "~~##~~", "~~##~~", "~~~~~~"], 10);
    const z = coastalDepths(g.elev, g.rows, g.cols, g.cells);
    assert.equal(z[1 * 6 + 2], 10);
    assert.equal(z[1 * 6 + 1], -8, "땅 10 m × 0.8");
    // 높은 땅은 상한, 낮은 땅은 하한
    const hi = coastalDepths(grid(["~~~", "~#~", "~~~"], 100).elev, 3, 3, grid(["~~~", "~#~", "~~~"]).cells);
    assert.equal(hi[0], -COAST_DEPTH.maxFirstM);
    const lo = coastalDepths(grid(["~~~", "~#~", "~~~"], 0.3).elev, 3, 3, grid(["~~~", "~#~", "~~~"]).cells);
    assert.equal(lo[0], -COAST_DEPTH.minM);
  });

  it("물가선이 변 안쪽으로 들어온다 — 땅(H)과 첫 고리(−D) 사이에서 0이 되는 자리가 꼭짓점이 아니다", () => {
    const g = grid(["~~~~~~~", "~~~#~~~", "~~~~~~~"], 10);
    const z = coastalDepths(g.elev, g.rows, g.cols, g.cells);
    const H = z[1 * 7 + 3]!;
    const D = -z[1 * 7 + 4]!;
    const s0 = H / (H + D); // 땅에서 바다 쪽으로 0이 되는 비율
    assert.ok(s0 > 0.3 && s0 < 0.8, `물가선 위치 ${s0.toFixed(2)}`);
  });

  it("둘째·셋째 고리는 점점 깊어지고 그 바깥은 손대지 않는다", () => {
    const g = grid(["~~~~~~~~~~", "~~~~~~~~~~", "~~~~~~~~~~", "~~~~~~~~~#"], 10);
    const z = coastalDepths(g.elev, g.rows, g.cols, g.cells);
    const at = (r: number, c: number) => z[r * 10 + c]!;
    assert.ok(at(3, 8) < 0 && at(3, 7) < at(3, 8) && at(3, 6) < at(3, 7), "고리마다 깊어진다");
    assert.ok(at(3, 6) >= -COAST_DEPTH.maxM);
    assert.equal(at(3, 5), 0, "넷째 고리부터는 그대로");
  });

  it("결측은 결측이고 결측을 땅으로 세지 않는다", () => {
    const g = grid(["~~~", "~?~", "~~~"]);
    const z = coastalDepths(g.elev, g.rows, g.cols, g.cells);
    assert.ok(Number.isNaN(z[4]!));
    assert.equal(z[0], 0, "결측 옆 바다는 고리가 아니다");
  });

  it("입력을 바꾸지 않는다 — 원자료는 판독이 그대로 쓴다", () => {
    const g = grid(["~~", "~#"], 10);
    const before = Float32Array.from(g.elev);
    coastalDepths(g.elev, g.rows, g.cols, g.cells);
    assert.deepEqual(g.elev, before);
  });
});
