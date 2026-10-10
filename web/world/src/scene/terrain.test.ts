// 지형 조립(scene/terrain.ts)은 three를 안 들인다 — 합성 팩으로 node에서 바로 본다.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { FLOOR_FIT_M, floorElevation, floorWeight, type RunwayFloor } from "../core/runwayfloor.ts";
import { elevationAt, type Tier, type TerrainPack } from "../lib/terrainpack.ts";
import { buildTerrain, renderTier } from "./terrain.ts";

const SCALE = 0.05;
const OFFSET = -100;
const NODATA = 65535;

/** 문자 격자 → 티어. `~` 바다(0 m), 숫자 0~9 → 그 값 × 10 m의 땅. 행 0 = 그림의 **마지막** 줄(남). */
function tier(name: string, art: string[], step: number, n0 = 0, e0 = 0): Tier {
  const rows = art.length;
  const cols = art[0]!.length;
  const raw = new Uint16Array(rows * cols);
  [...art].reverse().forEach((line, r) => [...line].forEach((ch, c) => {
    const z = ch === "~" ? 0 : Number(ch) * 10;
    raw[r * cols + c] = Math.round((z - OFFSET) / SCALE);
  }));
  return { name, rows, cols, n0, e0, step, scale: SCALE, offset: OFFSET, nodata: NODATA, raw };
}

const pack = (...tiers: Tier[]): TerrainPack => ({ origin: { lat_deg: 34.6, lon_deg: 127.2 }, tiers, cleaning: null });

// 대각선 해안의 섬 — 90 m 격자에서 톱니가 났던 모양
const ISLAND = [
  "~~~~~~~~~~",
  "~~~~~33~~~",
  "~~~~3553~~",
  "~~~35775~~",
  "~~357975~~",
  "~~~35775~~",
  "~~~~3553~~",
  "~~~~~33~~~",
  "~~~~~~~~~~",
  "~~~~~~~~~~",
];

describe("지형 조립 — 그릴 격자", () => {
  it("90 m 티어는 그릴 때 2배로 세분되고, 30 m 티어는 그대로다", () => {
    const outer = tier("outer", ISLAND, 90, -405, -405);
    const core = tier("core", ISLAND, 30, -135, -135);
    const b = buildTerrain(pack(core, outer));
    const [mc, mo] = b.meshes as [typeof b.meshes[0], typeof b.meshes[0]];
    assert.equal(mc.rows, 10);
    assert.equal(mc.step, 30);
    assert.equal(mo.rows, 19);
    assert.equal(mo.step, 45);
    assert.ok(b.notes.some((s) => /outer: 90 m 격자\(그릴 때 45 m로 세분\)/.test(s)));
    assert.ok(b.notes.some((s) => /표시용 수심/.test(s)));
  });

  it("게임 모드(refine 끔)는 세분하지 않는다", () => {
    const b = buildTerrain(pack(tier("outer", ISLAND, 90)), { refine: false, strideFor: () => 1 });
    assert.equal(b.meshes[0]!.rows, 10);
  });

  it("물가선이 꼭짓점이 아니라 변 안쪽을 지난다 — 땅에 맞닿은 바다 꼭짓점이 물속에 있다", () => {
    const b = buildTerrain(pack(tier("core", ISLAND, 30)));
    const m = b.meshes[0]!;
    const z = (r: number, c: number) => -m.positions[3 * (r * m.cols + c) + 2]!;
    // 그림 둘째 줄 "~~~~~33~~~"는 행 8 — 그 줄의 (8,5)가 땅 30 m, 옆 (8,4)는 맞닿은 바다
    assert.equal(z(8, 5), 30);
    assert.ok(z(8, 4) < -1, `맞닿은 바다 ${z(8, 4)}`);
    // 그 사이 변에서 0이 되는 자리가 꼭짓점이 아니라 변 안쪽이다
    const s0 = z(8, 5) / (z(8, 5) - z(8, 4));
    assert.ok(s0 > 0.3 && s0 < 0.9, `물가선 위치 ${s0.toFixed(2)}`);
    // 먼바다(맞닿지 않은 바다)는 손대지 않는다
    assert.equal(z(0, 0), 0);
  });

  it("세분해도 모두 바다인 칸은 그리지 않고, 섬의 칸은 그린다", () => {
    const outer = tier("outer", ISLAND, 90);
    const plain = buildTerrain(pack(outer), { refine: false });
    const fine = buildTerrain(pack(outer));
    // 같은 넓이를 4배 칸으로 덮는다 — 세분 격자의 그린 삼각형이 정확히 4배
    assert.equal(fine.meshes[0]!.triangles, 4 * plain.meshes[0]!.triangles);
  });

  it("renderTier는 원자료 티어를 바꾸지 않는다 — 판독(groundElevationAt)이 원자료를 쓴다", () => {
    const t = tier("outer", ISLAND, 90);
    const before = Uint16Array.from(t.raw);
    renderTier(t, undefined, true);
    buildTerrain(pack(t));
    buildTerrain(pack(t), { floor: FLOOR });
    assert.deepEqual(t.raw, before);
  });
});

/** 고흥 활주로 축(진방위 3.26°, 1,205 m) — 표고 0 m의 바닥 */
const FLOOR: RunwayFloor = { heading: 0.05682, length: 1205, elevation: 0 };

/** 활주로 위 원자료처럼 0.5~2.9 m로 출렁이는 땅 — 30 m 격자, N −300~1,500 m · E −300~300 m */
function bumpyTier(): Tier {
  const rows = 61;
  const cols = 21;
  const raw = new Uint16Array(rows * cols);
  for (let i = 0; i < raw.length; i++) raw[i] = Math.round((0.5 + ((i * 7) % 25) * 0.1 - OFFSET) / SCALE);
  return { name: "core", rows, cols, n0: -300, e0: -300, step: 30, scale: SCALE, offset: OFFSET, nodata: NODATA, raw };
}

/** 서쪽 세 열이 바다, 동쪽이 2.8~3.2 m 간척지(해안 턱 흡수의 2.5 m 문턱 위)인 30 m 격자 — 원점이 가운데쯤 */
function coastTier(): Tier {
  const rows = 10;
  const cols = 10;
  const raw = new Uint16Array(rows * cols);
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const z = c < 3 ? 0 : 2.8 + 0.1 * ((r + c) % 5);
      raw[r * cols + c] = Math.round((z - OFFSET) / SCALE);
    }
  }
  return { name: "core", rows, cols, n0: -135, e0: -135, step: 30, scale: SCALE, offset: OFFSET, nodata: NODATA, raw };
}

describe("지형 조립 — 활주로 바닥", () => {
  const src = bumpyTier();
  const srcZ = (i: number) => OFFSET + src.raw[i]! * SCALE;

  it("그릴 격자의 정점마다 floorElevation 그대로다 — 둘레는 활주로 표고, 이음 90 m, 멀리는 원자료", () => {
    const b = buildTerrain(pack(src), { floor: FLOOR });
    assert.deepEqual(b.floor, FLOOR, "맞는 바닥은 그대로 돌려준다 — 판독이 이것을 쓴다");
    const m = b.meshes[0]!;
    let flat = 0;
    let kept = 0;
    for (let r = 0; r < m.rows; r++) {
      for (let c = 0; c < m.cols; c++) {
        const i = r * m.cols + c;
        const z = -m.positions[3 * i + 2]!;
        const [n, e] = [src.n0 + r * src.step, src.e0 + c * src.step];
        // 이음 띠도 값으로 — 팩 눈금(0.05 m)의 반 안
        const want = floorElevation(FLOOR, n, e, srcZ(i));
        assert.ok(Math.abs(z - want) <= 0.026, `(${r}, ${c}) ${z} ≠ ${want}`);
        const w = floorWeight(FLOOR, n, e);
        if (w >= 1) { assert.ok(Math.abs(z) < 1e-6, `(${r}, ${c}) 편 자리 ${z}`); flat++; }
        if (w <= 0) kept++;
      }
    }
    assert.ok(flat > 200 && kept > 200, `편 ${flat} · 그대로 ${kept}`);
  });

  it("활주로 표고가 그 자리 원자료에서 FLOOR_FIT_M 넘게 벗어나면 펴지 않고 그렇다고 말한다 — 둑을 짓지 않는다", () => {
    // 시뮬 폼의 시작 고도 칸이 활주로 표고가 된다 — 12 m를 넣은 런(리뷰가 든 경우)
    const high = { ...FLOOR, elevation: 2.9 + FLOOR_FIT_M + 6 };
    const b = buildTerrain(pack(src), { floor: high });
    assert.equal(b.floor, null, "판독도 원자료 그대로여야 한다");
    const m = b.meshes[0]!;
    for (let i = 0; i < m.rows * m.cols; i++) {
      assert.ok(Math.abs(-m.positions[3 * i + 2]! - srcZ(i)) < 1e-4, `표본 ${i}`);
    }
    const notes = b.notes.join("\n");
    assert.match(notes, /활주로 바닥: 활주로 표고 11\.9 m가 그 자리 지형\(0\.5~2\.9 m\)에서 3 m 넘게 벗어나 펴지 않았습니다/);
    assert.doesNotMatch(notes, /평평하게 그리고/);
  });

  it("캡션이 편 구역과 원자료의 출렁임을 말하고, 판독도 그 바닥을 쓴다고 밝힌다", () => {
    const notes = buildTerrain(pack(src), { floor: FLOOR }).notes.join("\n");
    assert.match(notes, /활주로 바닥: 축 양옆 75 m·양 끝 너머 120 m를 활주로 표고 0 m로 평평하게/);
    assert.match(notes, /원자료는 이 구역에서 0\.5~2\.9 m로 출렁입니다/);
    assert.match(notes, /지면 높이 판독도 편 높이를 씁니다/);
  });

  it("바닥을 안 주면 펴지 않는다 — 활주로를 모르는 결과는 원자료 그대로", () => {
    const b = buildTerrain(pack(src));
    const m = b.meshes[0]!;
    for (let i = 0; i < m.rows * m.cols; i++) {
      assert.ok(Math.abs(-m.positions[3 * i + 2]! - srcZ(i)) < 1e-4, `표본 ${i}`);
    }
    assert.ok(!b.notes.some((s) => /활주로 바닥/.test(s)));
  });

  it("지형이 활주로 자리를 안 덮으면 펴지 않았다고 말한다", () => {
    const far = { ...src, n0: 20_000, e0: 20_000 };
    assert.ok(buildTerrain(pack(far), { floor: FLOOR }).notes.some((s) => /지형이 활주로 자리를 덮지 않아 펴지 않았습니다/.test(s)));
  });

  it("활주로 자리에 그린 땅이 있으면 칠할 땅이 있다(runwayCovered) — 바닥을 못 펴도 참, 모르거나 비었으면 거짓", () => {
    // 팩이 있다는 것만으로 도색을 고르면 그 자리가 바다·결측·격자 밖일 때 도색도 선도 없이 캡션만 남는다(v1.94 리뷰)
    assert.equal(buildTerrain(pack(src), { floor: FLOOR }).runwayCovered, true);
    assert.equal(buildTerrain(pack(src), { floor: { ...FLOOR, elevation: 40 } }).runwayCovered, true, "표고가 안 맞아 안 펴도 땅은 있다");
    assert.equal(buildTerrain(pack(src)).runwayCovered, false, "활주로를 모른다");
    assert.equal(buildTerrain(pack({ ...src, n0: 20_000, e0: 20_000 }), { floor: FLOOR }).runwayCovered, false, "격자 밖");
    const sea = { ...src, raw: new Uint16Array(src.raw.length).fill(Math.round((0 - OFFSET) / SCALE)) };
    assert.equal(buildTerrain(pack(sea), { floor: FLOOR }).runwayCovered, false, "그 자리가 온통 바다");
    const holes = { ...src, raw: new Uint16Array(src.raw.length).fill(NODATA) };
    assert.equal(buildTerrain(pack(holes), { floor: FLOOR }).runwayCovered, false, "그 자리가 온통 결측");
  });

  it("물가는 펴지 않는다 — 해안에 붙은 활주로에서 물가선이 꼭짓점 톱니로 돌아가지 않게", () => {
    // 간척지 위로 활주로가 지난다. 표고 0(고흥·폼 기본값)으로 물가 땅까지 펴면 그 꼭짓점이 해수면에 붙어 물가선이
    // 꼭짓점을 지난다(리뷰가 시험 섬에서 확인 — 물가선 위치 0.00). 그래서 바다에 맞닿은 땅과 바다는 둔다
    const coast = coastTier();
    const { raw, cols } = coast;
    const b = buildTerrain(pack(coast), { floor: { heading: 0, length: 60, elevation: 0 } });
    assert.ok(b.floor, "간척지 위 0 m 바닥은 지형과 맞는다");
    const m = b.meshes[0]!;
    const z = (r: number, c: number) => -m.positions[3 * (r * m.cols + c) + 2]!;
    const zSrc = (r: number, c: number) => OFFSET + raw[r * cols + c]! * SCALE;
    // (5,5)는 안쪽 땅 — 편다. (5,3)은 바다에 맞닿은 땅 — 둔다. (5,2)는 맞닿은 바다 — 물속 그대로
    assert.ok(Math.abs(z(5, 5)) < 1e-6, `안쪽 땅 ${z(5, 5)}`);
    assert.ok(Math.abs(z(5, 3) - zSrc(5, 3)) < 1e-4, `물가 땅 ${z(5, 3)} ≠ ${zSrc(5, 3)}`);
    assert.ok(z(5, 2) < -1, `맞닿은 바다 ${z(5, 2)}`);
    const s0 = z(5, 3) / (z(5, 3) - z(5, 2));
    assert.ok(s0 > 0.3 && s0 < 0.9, `물가선 위치 ${s0.toFixed(2)}`);
  });
  it("판독용 티어(groundTiers)는 그림과 같은 표본을 편다 — 물가 땅은 원자료 그대로, 원자료 티어는 안 바뀐다", () => {
    // 판독이 원자료에 바닥 함수를 따로 얹으면 물가에서 그림(물가 땅은 안 편다)과 판독(편다)이 갈린다(v1.92 리뷰)
    const coast = coastTier();
    const before = Uint16Array.from(coast.raw);
    const b = buildTerrain(pack(coast), { floor: { heading: 0, length: 60, elevation: 0 } });
    const g = b.groundTiers[0]!;
    const at = (r: number, c: number) => elevationAt(g, coast.n0 + r * coast.step, coast.e0 + c * coast.step)!;
    const src = (r: number, c: number) => elevationAt(coast, coast.n0 + r * coast.step, coast.e0 + c * coast.step)!;
    assert.ok(Math.abs(at(5, 5)) < 1e-6, `안쪽 땅 ${at(5, 5)}`);
    assert.ok(Math.abs(at(5, 3) - src(5, 3)) < 1e-9, `물가 땅 ${at(5, 3)}`);
    // 그린 정점과 판독 표본이 같다 — 표본 자리에서
    const m = b.meshes[0]!;
    for (const [r, c] of [[5, 5], [5, 3], [2, 6], [8, 9]] as const) {
      assert.ok(Math.abs(-m.positions[3 * (r * m.cols + c) + 2]! - at(r, c)) < 1e-6, `(${r}, ${c})`);
    }
    assert.deepEqual(coast.raw, before);
  });

  it("바닥이 없거나 지형과 맞지 않으면 판독용 티어는 원자료 티어 그대로다(같은 객체)", () => {
    assert.equal(buildTerrain(pack(src)).groundTiers[0], src);
    assert.equal(buildTerrain(pack(src), { floor: { ...FLOOR, elevation: 40 } }).groundTiers[0], src);
    assert.notEqual(buildTerrain(pack(src), { floor: FLOOR }).groundTiers[0], src);
  });
});
