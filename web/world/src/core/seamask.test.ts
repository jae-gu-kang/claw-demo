import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  CELL, buildSeaMasks, cellToNed, isLand, maskSummary, nedToCell, seaLevelRaw,
  type MaskTier,
} from "./seamask.ts";

const SCALE = 0.05;
const OFFSET = -100;
const NODATA = 65535;
const SEA = Math.round((0 - OFFSET) / SCALE); // 2000 — 실제 팩과 같은 양자화

/** 문자 격자로 티어를 만든다. `~` 해수면 · `#` 육지(20 m) · `?` 결측.
 *  행 0이 남쪽이므로 **아래에서 위로** 읽는다 — 그림과 좌표를 맞추려고 뒤집는다. */
function tier(name: string, art: string[], step = 30, n0 = 0, e0 = 0): MaskTier {
  const rows = art.length;
  const cols = art[0]!.length;
  const raw = new Uint16Array(rows * cols);
  const flipped = [...art].reverse();
  for (let r = 0; r < rows; r++) {
    const line = flipped[r]!;
    assert.equal(line.length, cols, "그림의 행 길이가 다르다");
    for (let c = 0; c < cols; c++) {
      const ch = line[c];
      raw[r * cols + c] = ch === "~" ? SEA : ch === "?" ? NODATA : Math.round((20 - OFFSET) / SCALE);
    }
  }
  return { name, rows, cols, n0, e0, step, scale: SCALE, offset: OFFSET, nodata: NODATA, raw };
}

const cellAt = (m: { cells: Uint8Array; cols: number }, r: number, c: number) =>
  m.cells[r * m.cols + c];

describe("해수면 판정", () => {
  it("가장자리에 닿은 0-성분만 바다다 — 갇힌 0은 육지로 남는다", () => {
    // 왼쪽 절반이 열린 바다, 오른쪽 안쪽에 갇힌 0 웅덩이(= 간척지 위 활주로)
    const t = tier("core", [
      "~~~~######",
      "~~~~#~~~~#",
      "~~~~#~~~~#",
      "~~~~######",
    ]);
    const m = buildSeaMasks([t]).get("core")!;
    // 그림 아래 행이 r=0. 왼쪽 열린 바다
    assert.equal(cellAt(m, 0, 0), CELL.SEA);
    assert.equal(cellAt(m, 3, 2), CELL.SEA);
    // 갇힌 웅덩이 — 표고는 0이지만 육지
    assert.equal(cellAt(m, 1, 6), CELL.LAND);
    assert.equal(cellAt(m, 2, 7), CELL.LAND);
    assert.equal(m.landAtSeaLevel, 8, "갇힌 0 셀 수 — 2행 × 4열");
  });

  it("활주로가 갇힌 0-성분 안에 있으면 육지다 — 실측에서 걸러낸 바로 그 경우", () => {
    // 실측(core 티어): 활주로가 속한 0-성분 87셀이 바다에 연결되지 않았고,
    // 활주로 → 바다 최단거리가 3,275 m였다. 여기서는 같은 형상을 축소해 못박는다.
    const t = tier("core", [
      "~~~~~~####",
      "~~~~~#~~~#",
      "~~~~~#~R~#",   // R = 활주로 자리 (육지 문자로 두지 않고 갇힌 0 안에 둔다)
      "~~~~~~####",
    ].map((s) => s.replace("R", "~")));
    const m = buildSeaMasks([t]).get("core")!;
    assert.equal(cellAt(m, 1, 7), CELL.LAND, "활주로가 바다로 판정되면 화면이 거짓말한다");
  });

  it("결측은 바다가 아니고, 바다를 통과시키지도 않는다", () => {
    const t = tier("core", [
      "~?~~",
      "~?~~",
      "####",
      "####",
    ]);
    const m = buildSeaMasks([t]).get("core")!;
    assert.equal(cellAt(m, 3, 1), CELL.MISSING);
    assert.equal(m.missingCells, 2);
    // 결측 열이 벽이 되어 오른쪽 0들은 자기 가장자리로만 연결된다 — 여전히 바다
    assert.equal(cellAt(m, 3, 2), CELL.SEA);
  });

  it("결측이 가로막으면 그 너머 갇힌 0은 육지다", () => {
    const t = tier("core", [
      "#####",
      "#~~~#",
      "#???#",
      "~~~~~",
    ]);
    const m = buildSeaMasks([t]).get("core")!;
    assert.equal(cellAt(m, 0, 2), CELL.SEA, "아래 가장자리는 바다");
    assert.equal(cellAt(m, 2, 2), CELL.LAND, "결측 너머 갇힌 0 — 없는 바다를 만들지 않는다");
  });

  // 두 테스트가 **같은 형상**을 봐야 뜻이 있다 — 하나만 손대면 순서 테스트가 조용히
  // 변별력을 잃는다(예: core를 키우면 혼자서도 흘러 버린다). 그래서 한 곳에서 만든다.
  const bayFixture = () => ({
    // 전 구간 바다. core를 감싸므로 시드를 줄 수 있다.
    outer: tier("outer", [
      "~~~~~~~~",
      "~~~~~~~~",
      "~~~~~~~~",
      "~~~~~~~~",
    ], 60, -90, -90),
    // 자기 가장자리가 전부 육지라 **혼자서는 못 흘린다** — 바깥으로만 연결된 만.
    core: tier("core", [
      "####",
      "#~~#",
      "#~~#",
      "####",
    ], 30, 0, 0),
  });

  it("바깥으로만 연결된 만은 넓은 티어가 좁은 티어에 알려 준다", () => {
    const { outer, core } = bayFixture();

    const alone = buildSeaMasks([core]).get("core")!;
    assert.equal(cellAt(alone, 1, 1), CELL.LAND, "core 혼자면 만이 통째로 빠진다");

    const both = buildSeaMasks([outer, core]).get("core")!;
    assert.equal(cellAt(both, 1, 1), CELL.SEA, "넓은 티어의 답이 시드가 되어야 한다");
    assert.equal(cellAt(both, 2, 2), CELL.SEA);
  });

  it("티어 순서를 거꾸로 줘도 넓은 것부터 흘린다", () => {
    // **이 테스트가 `extentOf` 정렬의 유일한 파수꾼이다.** 앞 테스트는 이미 올바른
    // 순서로 넘기므로 정렬을 지워도 통과한다 — 실제로 지우고 돌렸더니 16개가 전부
    // 초록이었다(리뷰 실측). 여기서는 **좁은 티어를 먼저 넘긴다.**
    const { outer, core } = bayFixture();

    const masks = buildSeaMasks([core, outer]); // 좁은 것을 먼저 줬다
    assert.equal(cellAt(masks.get("core")!, 1, 1), CELL.SEA,
      "정렬이 없으면 core가 먼저 흘러 시드를 못 받고 만이 통째로 빠진다");
    assert.equal(cellAt(masks.get("core")!, 2, 2), CELL.SEA);
    assert.equal(masks.get("outer")!.seaCells, 32);
  });
});

describe("큐 안전", () => {
  it("전부 바다면 셀 수만큼 정확히 담는다 — BFS 큐 상한 케이스", () => {
    // 큐가 `Int32Array(rows*cols)`라, 한 셀이 두 번 들어가면 그 자리에서 넘친다.
    // `push`가 넣기 **전에** SEA로 표시하는 것이 그 불변조건이고, 전부 바다인 격자가
    // 그것을 정확히 상한에서 시험한다. 1행·1열도 함께 본다(경계 시드가 중복되는 형상).
    for (const [rows, cols] of [[1, 1], [1, 64], [64, 1], [40, 40]] as const) {
      const raw = new Uint16Array(rows * cols).fill(SEA);
      const t: MaskTier = {
        name: "t", rows, cols, n0: 0, e0: 0, step: 30,
        scale: SCALE, offset: OFFSET, nodata: NODATA, raw,
      };
      const m = buildSeaMasks([t]).get("t")!;
      assert.equal(m.seaCells, rows * cols, `${rows}x${cols}`);
    }
  });

  it("좌표가 겹치지 않는 두 티어는 서로에게 시드를 주지 않는다", () => {
    const far = tier("far", ["~~", "~~"], 90, 100000, 100000);
    const near = tier("near", ["##", "##"], 30, 0, 0);
    assert.equal(buildSeaMasks([far, near]).get("near")!.seaCells, 0,
      "멀리 있는 티어가 여기를 바다로 만들면 안 된다");
  });
});

describe("양자화", () => {
  it("해수면이 눈금에 정확히 놓이면 정수 비교를 쓴다", () => {
    assert.equal(seaLevelRaw({ scale: 0.05, offset: -100 }), 2000);
  });

  it("눈금에 안 놓이면 null — 실수 비교로 물러난다", () => {
    assert.equal(seaLevelRaw({ scale: 0.07, offset: -100 }), null);
  });

  it("scale이 0이거나 음수면 null (0으로 나누지 않는다)", () => {
    assert.equal(seaLevelRaw({ scale: 0, offset: -100 }), null);
    assert.equal(seaLevelRaw({ scale: -0.05, offset: -100 }), null);
  });

  it("해수면이 raw 범위 밖이면 null", () => {
    assert.equal(seaLevelRaw({ scale: 0.05, offset: 100 }), null, "offset이 양수면 raw가 음수");
  });
});

describe("좌표", () => {
  const t = tier("core", ["~~~", "~~~", "~~~"], 30, -30, -30);

  it("셀 ↔ NED 왕복", () => {
    assert.deepEqual(cellToNed(t, 0, 0), [-30, -30]);
    assert.deepEqual(cellToNed(t, 2, 2), [30, 30]);
    assert.deepEqual(nedToCell(t, 30, 30), [2, 2]);
  });

  it("격자 밖은 null — 가장자리로 끌어붙이지 않는다", () => {
    assert.equal(nedToCell(t, 1000, 0), null);
    assert.equal(nedToCell(t, 0, -1000), null);
  });

  it("isLand는 범위 밖을 육지로 답하지 않는다", () => {
    const m = buildSeaMasks([t]).get("core")!;
    assert.equal(isLand(m, -1, 0), false);
    assert.equal(isLand(m, 0, 99), false);
  });
});

describe("캡션용 요약", () => {
  it("바다 비율과 해수면 높이 육지 비율을 낸다", () => {
    const t = tier("core", ["~~##", "~~##", "~~##", "~~##"]);
    const s = maskSummary(buildSeaMasks([t]).get("core")!);
    assert.equal(s.seaFrac, 0.5);
    assert.equal(s.landAtSeaLevelFrac, 0);
  });
});
