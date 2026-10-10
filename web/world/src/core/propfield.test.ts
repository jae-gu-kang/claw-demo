import { strict as assert } from "node:assert";
import { describe, it } from "node:test";

import { PROPS, hash2, placeProps, type ElevSample, type PropField } from "./propfield.ts";

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

  it("keepOut 자리(활주로 착륙대)는 비우고, 그 밖은 덜어 내지 않는다", () => {
    // 원점 원(originClear 1.2 km) 밖으로 이어지는 띠 — 고흥 활주로 끝·착륙대가 그렇다(게임 지형에도 활주로가 칠해진다)
    const rect = { n0: -3000, e0: -3000, n1: 3000, e1: 3000 };
    const strip = (n: number, e: number) => Math.abs(e) <= 75 && n >= -120 && n <= 3000;
    const all = (f: PropField) => [...f.pines, ...f.leaves, ...f.cabins];
    const free = placeProps(hills, rect, 800);
    const kept = placeProps(hills, rect, 800, 1, strip);
    assert.ok(all(free).some((p) => strip(p.n, p.e)), "비우지 않으면 띠에도 선다 — 이 시험이 빈 띠를 재지 않는다");
    for (const p of all(kept)) assert.ok(!strip(p.n, p.e), `띠 안 (${p.n.toFixed(0)}, ${p.e.toFixed(0)})`);
    // 띠 밖은 그대로이거나 늘 뿐이다(오두막 상한을 띠가 덜 먹으면 밖에 하나 더 선다) — 표본을 null로 메워 비우면
    // 이웃 경사 판정이 번져 띠 밖 한 칸이 같이 빈다(propfield.ts keepOut)
    const outside = (f: PropField) => all(f).filter((p) => !strip(p.n, p.e)).length;
    assert.ok(outside(kept) >= outside(free), `${outside(kept)} < ${outside(free)}`);
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
