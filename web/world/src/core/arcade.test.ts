import { strict as assert } from "node:assert";
import { describe, it } from "node:test";

import { ARCADE, spawnArcade, stepArcade, type ArcadeInput } from "./arcade.ts";

const IDLE: ArcadeInput = { turn: 0, pitch: 0, throttle: 0 };
const run = (input: ArcadeInput, steps: number, ground: number | null = null) => {
  let s = spawnArcade(0, 0);
  for (let i = 0; i < steps; i++) s = stepArcade(s, input, 0.02, ground);
  return s;
};

describe("spawnArcade", () => {
  it("활주로 표고 위 150 m·활주로 방위에서 출발한다", () => {
    const s = spawnArcade(0.6, 40);
    assert.equal(-s.pos[2], 190);
    assert.equal(s.psi, 0.6);
  });

  it("모르면 0 m 기준 150 m·북향 — 값을 지어내지 않는다", () => {
    const s = spawnArcade(null, null);
    assert.equal(-s.pos[2], 150);
    assert.equal(s.psi, 0);
  });
});

describe("stepArcade", () => {
  it("순수하다 — 같은 입력은 같은 결과", () => {
    const a = run({ turn: 0.5, pitch: 0.3, throttle: 1 }, 100);
    const b = run({ turn: 0.5, pitch: 0.3, throttle: 1 }, 100);
    assert.deepEqual(a, b);
  });

  it("상승 입력이면 고도가 는다 (NED: d 감소)", () => {
    const s = run({ ...IDLE, pitch: 1 }, 150);
    assert.ok(-s.pos[2] > 150, `h=${-s.pos[2]}`);
  });

  it("속력은 한계에 클램프된다", () => {
    assert.equal(run({ ...IDLE, throttle: 1 }, 2000).V, ARCADE.vMax);
    assert.equal(run({ ...IDLE, throttle: -1 }, 2000).V, ARCADE.vMin);
  });

  it("우선회는 ψ를 늘리고 표시 뱅크가 따라간다", () => {
    const s = run({ ...IDLE, turn: 1 }, 100);
    assert.ok(s.psi > 0.5, `psi=${s.psi}`);
    assert.ok(s.phi > 0.5, `phi=${s.phi}`);
  });

  it("ψ는 [−π, π)로 되돌린다 — 무한 적분 금지", () => {
    const s = run({ ...IDLE, turn: 1 }, 5000);
    assert.ok(s.psi >= -Math.PI && s.psi < Math.PI, `psi=${s.psi}`);
  });

  it("지면 위 최저 높이 밑으로 안 내려간다", () => {
    const s = run({ ...IDLE, pitch: -1 }, 3000, 120);
    assert.ok(Math.abs(-s.pos[2] - (120 + ARCADE.floor)) < 1e-6, `h=${-s.pos[2]}`);
  });

  it("지면을 모르면 기준면 0을 바닥으로 쓴다", () => {
    const s = run({ ...IDLE, pitch: -1 }, 3000, null);
    assert.ok(Math.abs(-s.pos[2] - ARCADE.floor) < 1e-6, `h=${-s.pos[2]}`);
  });

  it("큰 dt는 0.25 s로 클램프 — 탭 복귀 프레임이 순간이동을 만들지 않는다", () => {
    const s0 = spawnArcade(0, 0);
    const far = stepArcade(s0, IDLE, 10, null);
    assert.ok(Math.abs(far.pos[0] - s0.pos[0]) <= s0.V * 0.25 + 1e-9);
  });

  it("비수치 입력 축은 0으로 본다 — NaN이 위치로 흘러들지 않는다", () => {
    const s = stepArcade(spawnArcade(0, 0), { turn: NaN, pitch: NaN, throttle: NaN }, 0.02, null);
    for (const v of [...s.pos, s.psi, s.theta, s.phi, s.V]) assert.ok(Number.isFinite(v));
  });
});
