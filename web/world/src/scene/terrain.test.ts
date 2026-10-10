// 지형 조립(scene/terrain.ts)은 three를 안 들인다 — 합성 팩으로 node에서 바로 본다.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { floorWeight, type RunwayFloor } from "../core/runwayfloor.ts";
import type { Tier, TerrainPack } from "../lib/terrainpack.ts";
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

describe("지형 조립 — 활주로 바닥", () => {
  const src = bumpyTier();
  const srcZ = (i: number) => OFFSET + src.raw[i]! * SCALE;

  it("그릴 격자에서 활주로 둘레는 활주로 표고로 평평하고, 멀리는 원자료 그대로다", () => {
    const b = buildTerrain(pack(src), { floor: FLOOR });
    const m = b.meshes[0]!;
    let flat = 0;
    let kept = 0;
    for (let r = 0; r < m.rows; r++) {
      for (let c = 0; c < m.cols; c++) {
        const i = r * m.cols + c;
        const z = -m.positions[3 * i + 2]!;
        const w = floorWeight(FLOOR, src.n0 + r * src.step, src.e0 + c * src.step);
        if (w >= 1) { assert.ok(Math.abs(z) < 1e-6, `(${r}, ${c}) 편 자리 ${z}`); flat++; }
        if (w <= 0) { assert.ok(Math.abs(z - srcZ(i)) < 1e-4, `(${r}, ${c}) 원자료 ${z} ≠ ${srcZ(i)}`); kept++; }
      }
    }
    assert.ok(flat > 200 && kept > 200, `편 ${flat} · 그대로 ${kept}`);
  });

  it("캡션이 편 구역과 원자료의 출렁임을 말하고, 판독도 그 바닥을 쓴다고 밝힌다", () => {
    const notes = buildTerrain(pack(src), { floor: FLOOR }).notes.join("\n");
    assert.match(notes, /활주로 바닥: 축 양옆 75 m·양 끝 너머 60 m를 활주로 표고 0 m로 평평하게/);
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

  it("바다 쪽 물속 이음은 바닥이 건드리지 않는다 — 해안에 붙은 활주로에서 물가선이 톱니로 돌아가지 않게", () => {
    // 섬 한가운데를 지나는 활주로 — 펴는 구역이 해안을 덮는다
    const island = tier("core", ISLAND, 30, -135, -135);
    const b = buildTerrain(pack(island), { floor: { heading: 0, length: 60, elevation: 4 } });
    const m = b.meshes[0]!;
    const z = (r: number, c: number) => -m.positions[3 * (r * m.cols + c) + 2]!;
    // (8,5)는 땅 30 m — 펴는 구역 안이라 활주로 표고 4 m. 옆 (8,4)는 맞닿은 바다 — 물속 그대로
    assert.ok(Math.abs(z(8, 5) - 4) < 1e-6, `땅 ${z(8, 5)}`);
    assert.ok(z(8, 4) < -1, `맞닿은 바다 ${z(8, 4)}`);
  });
});
