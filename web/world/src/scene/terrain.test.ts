// 지형 조립(scene/terrain.ts)은 three를 안 들인다 — 합성 팩으로 node에서 바로 본다.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

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
    assert.deepEqual(t.raw, before);
  });
});
