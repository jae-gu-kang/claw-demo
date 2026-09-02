import { strict as assert } from "node:assert";
import { describe, it } from "node:test";

import {
  COAST_RANGE_M, buildCoastField, decodeCoastDistance, encodeCoastField,
  squaredDistanceTransform, type MaskedTier,
} from "./coastfield.ts";
import { CELL, type MaskTier, type TierMask } from "./seamask.ts";

/** 셀 그림에서 티어 + 마스크를 만든다. `.` = 뭍, `~` = 바다, `?` = 결측. */
function tierOf(rows: string[], step = 10, name = "t"): MaskedTier {
  const h = rows.length;
  const w = rows[0]!.length;
  const cells = new Uint8Array(w * h);
  let sea = 0; let missing = 0;
  for (let r = 0; r < h; r++) {
    for (let c = 0; c < w; c++) {
      const ch = rows[r]![c];
      const v = ch === "~" ? CELL.SEA : ch === "?" ? CELL.MISSING : CELL.LAND;
      cells[r * w + c] = v;
      if (v === CELL.SEA) sea++;
      if (v === CELL.MISSING) missing++;
    }
  }
  const tier: MaskTier = {
    name, rows: h, cols: w, n0: 0, e0: 0, step,
    scale: 1, offset: 0, nodata: 65535, raw: new Uint16Array(w * h),
  };
  const mask: TierMask = {
    name, rows: h, cols: w, cells, seaCells: sea, landAtSeaLevel: 0, missingCells: missing,
  };
  return { tier, mask };
}

describe("squaredDistanceTransform", () => {
  it("시드 칸은 0", () => {
    const seed = new Float64Array([0, 1, 1, 1]);
    const d = squaredDistanceTransform(seed, 4, 1);
    assert.equal(d[0], 0);
  });

  it("한 줄에서 칸 수의 제곱이 나온다", () => {
    const d = squaredDistanceTransform(new Float64Array([0, 1, 1, 1]), 4, 1);
    assert.deepEqual([...d], [0, 1, 4, 9]);
  });

  it("2차원 유클리드 — 대각선은 √2 칸", () => {
    // 좌상단만 시드. (1,1)까지의 제곱거리는 2.
    const seed = new Float64Array(9).fill(1);
    seed[0] = 0;
    const d = squaredDistanceTransform(seed, 3, 3);
    assert.equal(d[4], 2);
    assert.equal(d[8], 8);   // (2,2) → 4+4
  });

  it("시드가 하나도 없으면 전부 큰 값 — 0으로 무너지지 않는다", () => {
    const d = squaredDistanceTransform(new Float64Array([1, 1, 1, 1]), 2, 2);
    for (const v of d) assert.ok(v > 1e10, `${v}`);
  });
});

describe("buildCoastField", () => {
  //  왼쪽 절반이 바다, 오른쪽이 뭍. 격자 10 m.
  const rows = [
    "~~~~....",
    "~~~~....",
    "~~~~....",
    "~~~~....",
  ];
  const f = buildCoastField([tierOf(rows)], 8);

  it("바다는 양수 · 뭍은 음수 — 부호가 곧 판정이다", () => {
    const at = (r: number, c: number) => f.dist[r * f.size + c]!;
    assert.ok(at(1, 0) > 0, `바다 ${at(1, 0)}`);
    assert.ok(at(1, 7) < 0, `뭍 ${at(1, 7)}`);
  });

  it("해안에서 멀수록 커진다", () => {
    const at = (r: number, c: number) => f.dist[r * f.size + c]!;
    assert.ok(at(1, 0) > at(1, 3), `${at(1, 0)} vs ${at(1, 3)}`);
    assert.ok(at(1, 7) < at(1, 4), `${at(1, 7)} vs ${at(1, 4)}`);
  });

  it("**도메인 밖은 바다** — 열린 바다를 이어 그린다(지어낸 지리, 캡션이 밝힌다)", () => {
    // size를 격자보다 크게 잡아도 티어 사각형 안이면 티어가 이긴다. 여기서는 딱 맞다.
    const wide = buildCoastField([tierOf(rows)], 16);
    assert.equal(wide.size, 16);
    assert.ok(wide.dist.every((v) => Number.isFinite(v)));
  });

  it("결측은 known 0 — 해면을 그리지 않는다", () => {
    const g = buildCoastField([tierOf(["~~??", "~~??", "..??", "..??"])], 4);
    assert.equal(g.known[0 * 4 + 3], 0);
    assert.equal(g.known[0 * 4 + 0], 1);
  });

  it("결측은 바다로도 뭍으로도 세지 않는다 — 거리가 그 칸에서 시작하지 않는다", () => {
    const g = buildCoastField([tierOf(["~~??", "~~??", "~~??", "~~??"])], 4);
    // 전부 바다 아니면 결측이다. 뭍이 없으므로 바다 칸의 거리는 포화해야 한다.
    assert.ok(g.dist[0]! > 1e6, `${g.dist[0]}`);
  });

  it("촘촘한 티어가 이긴다 — 같은 자리에서 안쪽 판정을 쓴다", () => {
    const coarse = tierOf(["...."], 100, "outer");
    const finer = tierOf(["~~~~"], 10, "core");
    const g = buildCoastField([coarse, finer], 4);
    // core가 (0,0) 부근을 덮으므로 바다여야 한다.
    assert.ok(g.dist[0]! > 0, `${g.dist[0]}`);
  });

  it("칸 크기를 짧은 쪽으로 잰다 — 거리를 과소평가하지 않는다", () => {
    assert.ok(f.metersPerCell > 0 && Number.isFinite(f.metersPerCell));
  });

  it("전부 유한하다 — NaN 하나가 해면을 통째로 지운다", () => {
    for (const v of f.dist) assert.ok(Number.isFinite(v));
  });
});

describe("encodeCoastField", () => {
  const f = buildCoastField([tierOf(["~~..", "~~..", "~~..", "~~.."])], 4);
  const bytes = encodeCoastField(f);

  it("칸마다 두 바이트", () => {
    assert.equal(bytes.length, f.size * f.size * 2);
  });

  it("**복호했을 때 부호가 그대로다** — 해안선이 한 칸도 밀리지 않는다", () => {
    // 바이트를 127/128과 견주면 안 된다: 0.5×255 = 127.5라 0 m가 중앙에 안 앉는다.
    // 판정은 셰이더가 하는 그대로, 복호한 값의 부호로 한다.
    let sawSea = false; let sawLand = false;
    for (let i = 0; i < f.size * f.size; i++) {
      const d = decodeCoastDistance(bytes[2 * i]!);
      if (f.dist[i]! > 0) { sawSea = true; assert.ok(d > 0, `바다인데 ${d}`); }
      if (f.dist[i]! < 0) { sawLand = true; assert.ok(d < 0, `뭍인데 ${d}`); }
    }
    assert.ok(sawSea && sawLand);
  });

  it("복호 오차가 반 눈금 안이다 — 포화 구간 밖에서", () => {
    const step = (2 * COAST_RANGE_M) / 255;
    for (let i = 0; i < f.size * f.size; i++) {
      const want = f.dist[i]!;
      if (Math.abs(want) >= COAST_RANGE_M) continue;
      assert.ok(Math.abs(decodeCoastDistance(bytes[2 * i]!) - want) <= step / 2 + 1e-6);
    }
  });

  it("범위 밖은 포화한다 — 감기지 않는다", () => {
    const g: typeof f = { ...f, dist: new Float32Array([COAST_RANGE_M * 9, -COAST_RANGE_M * 9]), known: new Uint8Array([1, 1]), size: 1 };
    const b = encodeCoastField({ ...g, size: 1 });
    assert.equal(b[0], 255);
  });
});
