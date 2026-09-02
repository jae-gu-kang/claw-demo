import { strict as assert } from "node:assert";
import { describe, it } from "node:test";

import { PROPS, hash2, placeProps, type ElevSample } from "./propfield.ts";

const RECT = { n0: -6000, e0: -6000, n1: 6000, e1: 6000 };
/** 완만한 언덕 지형 — 전부 육지, 경사 ≈ 0.09 이하. */
const hills: ElevSample = (n, e) => 60 + 40 * Math.sin(n / 900) * Math.cos(e / 1100);

describe("hash2", () => {
  it("결정론 — 같은 좌표·씨앗은 같은 값", () => {
    assert.equal(hash2(12, -7, 3), hash2(12, -7, 3));
  });

  it("0‥1 범위", () => {
    for (let i = -20; i < 20; i++) {
      const v = hash2(i, i * 31, 9);
      assert.ok(v >= 0 && v < 1, `v=${v}`);
    }
  });
});

describe("placeProps", () => {
  it("결정론 — 같은 지형·씨앗이면 같은 배치", () => {
    const a = placeProps(hills, RECT, 800, 5);
    const b = placeProps(hills, RECT, 800, 5);
    assert.deepEqual(a, b);
  });

  it("육지 언덕에는 나무가 실제로 선다", () => {
    const f = placeProps(hills, RECT, 800);
    assert.ok(f.pines.length > 200, `pines=${f.pines.length}`);
  });

  it("바다(표고 0)와 격자 밖(null)에는 아무것도 없다", () => {
    const sea: ElevSample = (n) => (n > 0 ? 0 : null);
    const f = placeProps(sea, RECT, 800);
    assert.equal(f.pines.length + f.leaves.length + f.cabins.length, 0);
  });

  it("원점 둘레(활주로·발사장)는 비운다", () => {
    const f = placeProps(hills, RECT, 800);
    for (const p of [...f.pines, ...f.leaves, ...f.cabins]) {
      assert.ok(Math.hypot(p.n, p.e) >= PROPS.originClear);
    }
  });

  it("수목한계(relief 0.72) 위에는 나무가 없다", () => {
    const high: ElevSample = () => 700; // relief 800 → 한계 576
    const f = placeProps(high, RECT, 800);
    assert.equal(f.pines.length + f.leaves.length, 0);
  });

  it("절벽(결측 이웃 포함)에는 놓지 않는다", () => {
    const cliff: ElevSample = (n, e) => (Math.abs(e) < 50 ? 80 : null);
    const f = placeProps(cliff, RECT, 800);
    assert.equal(f.pines.length + f.leaves.length + f.cabins.length, 0);
  });

  it("개수 상한을 지킨다", () => {
    const f = placeProps(hills, { n0: -12000, e0: -12000, n1: 12000, e1: 12000 }, 800);
    assert.ok(f.pines.length <= PROPS.maxPines);
    assert.ok(f.leaves.length <= PROPS.maxLeaves);
    assert.ok(f.cabins.length <= PROPS.maxCabins);
  });

  it("밑동은 표본 표고에 앉는다 — 다른 값을 지어내지 않는다", () => {
    const f = placeProps(hills, RECT, 800);
    const p = f.pines[0]!;
    assert.equal(p.elev, hills(p.n, p.e));
  });
});
