import { strict as assert } from "node:assert";
import { describe, it } from "node:test";

import {
  G, WAVE_COUNT, coxMunkSlopeVariance, gerstnerSet, peakWavelength, significantWaveHeight,
} from "./waves.ts";

describe("significantWaveHeight", () => {
  it("풍속의 제곱에 비례한다", () => {
    // 두 배 바람은 네 배 파고. 상수를 바꿔도 이 관계는 남아야 한다.
    assert.ok(Math.abs(significantWaveHeight(10) - 4 * significantWaveHeight(5)) < 1e-12);
  });

  it("7 m/s에서 1 m 안팎 — 실제 해상 상태와 자리수가 맞는다", () => {
    const hs = significantWaveHeight(7);
    assert.ok(hs > 0.8 && hs < 1.4, `H_s = ${hs}`);
  });

  it("바람이 없으면 0", () => {
    assert.equal(significantWaveHeight(0), 0);
  });

  it("음수 풍속은 0으로 본다 — NaN을 셰이더로 흘리지 않는다", () => {
    assert.equal(significantWaveHeight(-3), 0);
  });
});

describe("peakWavelength", () => {
  it("풍속의 제곱에 비례한다 — 바람이 세면 파도가 길어진다", () => {
    assert.ok(Math.abs(peakWavelength(12) / peakWavelength(6) - 4) < 1e-9);
  });

  it("무풍에서도 유한하다 — 파수가 발산하면 셰이더가 죽는다", () => {
    const l = peakWavelength(0);
    assert.ok(Number.isFinite(l) && l > 0, `L_p = ${l}`);
  });
});

describe("coxMunkSlopeVariance", () => {
  it("Cox & Munk 1954 계수를 그대로 쓴다", () => {
    assert.ok(Math.abs(coxMunkSlopeVariance(0) - 0.003) < 1e-12);
    assert.ok(Math.abs(coxMunkSlopeVariance(10) - (0.003 + 0.0512)) < 1e-12);
  });

  it("바람이 세면 커진다 — 윤슬 띠가 넓어지는 근거다", () => {
    assert.ok(coxMunkSlopeVariance(12) > coxMunkSlopeVariance(3));
  });
});

describe("gerstnerSet", () => {
  const waves = gerstnerSet(7, 0.4);

  it("셰이더 유니폼 길이와 성분 수가 같다", () => {
    assert.equal(waves.length, WAVE_COUNT);
  });

  it("심해 분산관계를 지킨다 — ω² = g k", () => {
    for (const w of waves) {
      assert.ok(Math.abs(w.omega * w.omega - G * w.k) < 1e-9, `ω²=${w.omega ** 2}, gk=${G * w.k}`);
    }
  });

  it("파수와 파장이 서로의 역수다 — k = 2π/L", () => {
    for (const w of waves) {
      assert.ok(Math.abs(w.k * w.length - 2 * Math.PI) < 1e-9);
    }
  });

  it("**고리가 생기지 않는다** — Σ Q k A ≤ 1", () => {
    // 넘으면 마루가 자기를 파고들어 면이 뒤집힌다. 화면에서는 검은 얼룩으로 보인다.
    const sum = waves.reduce((s, w) => s + w.q * w.k * w.amplitude, 0);
    assert.ok(sum <= 1 + 1e-9, `Σ QkA = ${sum}`);
  });

  it("진폭 합이 유의파고를 맞춘다 — H_s = 4√(ΣA²/2)", () => {
    const m0 = waves.reduce((s, w) => s + (w.amplitude * w.amplitude) / 2, 0);
    const hs = 4 * Math.sqrt(m0);
    assert.ok(Math.abs(hs - significantWaveHeight(7)) < 1e-9, `H_s = ${hs}`);
  });

  it("방향이 전부 단위벡터다 — 아니면 파장이 방향마다 달라진다", () => {
    for (const w of waves) {
      assert.ok(Math.abs(Math.hypot(w.dir[0], w.dir[1]) - 1) < 1e-12);
    }
  });

  it("방향이 하나로 몰려 있지 않다 — 전부 같으면 물결이 아니라 주름이 된다", () => {
    const dots = waves.map((w) => w.dir[0] * waves[0]!.dir[0] + w.dir[1] * waves[0]!.dir[1]);
    assert.ok(Math.min(...dots) < 0.8, `가장 벌어진 성분의 cos = ${Math.min(...dots)}`);
  });

  it("풍향을 돌리면 성분이 통째로 같은 각만큼 돈다", () => {
    const a = gerstnerSet(7, 0);
    const b = gerstnerSet(7, Math.PI / 2);
    for (let i = 0; i < a.length; i++) {
      // (x, z) → (−z, x)
      assert.ok(Math.abs(b[i]!.dir[0] - -a[i]!.dir[1]) < 1e-12);
      assert.ok(Math.abs(b[i]!.dir[1] - a[i]!.dir[0]) < 1e-12);
    }
  });

  it("무풍이면 진폭 0 · Q 0 — 0으로 나누지 않는다", () => {
    for (const w of gerstnerSet(0, 0)) {
      assert.equal(w.amplitude, 0);
      assert.equal(w.q, 0);
      assert.ok(Number.isFinite(w.k) && Number.isFinite(w.omega));
    }
  });

  it("steepness 0이면 상하로만 움직인다 — Q가 0이라 수평 변위가 없다", () => {
    for (const w of gerstnerSet(7, 0, 0)) assert.equal(w.q, 0);
  });

  it("전부 유한하다 — 하나라도 NaN이면 해면이 통째로 사라진다", () => {
    for (const u of [0, 0.1, 1, 7, 30]) {
      for (const w of gerstnerSet(u, 1.2)) {
        for (const v of [w.dir[0], w.dir[1], w.length, w.amplitude, w.k, w.omega, w.q]) {
          assert.ok(Number.isFinite(v), `U=${u}에서 ${v}`);
        }
      }
    }
  });
});
