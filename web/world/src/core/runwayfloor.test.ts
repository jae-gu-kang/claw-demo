// 활주로 바닥(core/runwayfloor.ts) — 그릴 격자와 지면 판독이 같이 쓰는 순수 함수다. three 없이 돈다.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { GOHEUNG } from "../../../js/lib/site.js";
import {
  RUNWAY_FLOOR, floorElevation, floorGrid, floorWeight, runwayFloorOf, sameFloor,
} from "./runwayfloor.ts";

/** 고흥 활주로 — 방위·길이는 lib/site.js에서 받는다(옮겨 적으면 축 보정 때 혼자 남는다 — runway.test.ts). */
const RW = runwayFloorOf({ heading: GOHEUNG.runwayHeadingRad, length: GOHEUNG.runwayLengthM, elevation: 0 })!;
const HALF = GOHEUNG.runwayWidthM / 2;
const { halfWidthM: SIDE, endM: END, blendM: BLEND } = RUNWAY_FLOOR;

/** 활주로 축 좌표(along 시단에서, across 오른쪽 +) → NED (n, e) */
function ned(along: number, across: number): [number, number] {
  const c = Math.cos(RW.heading);
  const s = Math.sin(RW.heading);
  return [along * c - across * s, along * s + across * c];
}
const wAt = (along: number, across: number) => floorWeight(RW, ...ned(along, across));

describe("runwayFloorOf — 결과의 활주로에서 바닥을", () => {
  it("방위·길이가 없거나 길이가 0 이하면 null — 펼 자리를 모른다", () => {
    assert.equal(runwayFloorOf(null), null);
    assert.equal(runwayFloorOf({ heading: 0.1 }), null);
    assert.equal(runwayFloorOf({ length: 100 }), null);
    assert.equal(runwayFloorOf({ heading: 0.1, length: 0 }), null);
    assert.equal(runwayFloorOf({ heading: Number.NaN, length: 100 }), null);
  });

  it("표고가 없으면 0 — 활주로 선·지형 없는 기준면과 같은 값", () => {
    assert.deepEqual(runwayFloorOf({ heading: 0.1, length: 100 }), { heading: 0.1, length: 100, elevation: 0 });
    assert.equal(runwayFloorOf({ heading: 0.1, length: 100, elevation: 4 })!.elevation, 4);
  });

  it("sameFloor는 값으로 비교하고, null은 null하고만 같다", () => {
    const a = runwayFloorOf({ heading: 0.1, length: 100, elevation: 4 });
    assert.ok(sameFloor(a, runwayFloorOf({ heading: 0.1, length: 100, elevation: 4 })));
    assert.ok(!sameFloor(a, runwayFloorOf({ heading: 0.1, length: 100, elevation: 5 })));
    assert.ok(!sameFloor(a, null));
    assert.ok(sameFloor(null, null));
  });
});

describe("floorWeight — 펴는 구역은 1, 바깥 90 m에 걸쳐 0으로", () => {
  it("포장면과 그 둘레(축 양옆 75 m · 끝 너머 60 m)는 1", () => {
    const L = GOHEUNG.runwayLengthM;
    for (const [a, x] of [[0, 0], [600, HALF], [L, -HALF], [-END, SIDE], [L + END, -SIDE]] as const) {
      assert.equal(wAt(a, x), 1, `along ${a} · across ${x}`);
    }
  });

  it("구역에서 blendM 넘게 떨어지면 0 — 원자료 그대로", () => {
    assert.equal(wAt(600, SIDE + BLEND), 0);
    assert.equal(wAt(600, -(SIDE + BLEND + 30)), 0);
    assert.equal(wAt(-END - BLEND, 0), 0);
    assert.equal(wAt(GOHEUNG.runwayLengthM + END + BLEND + 1, 0), 0);
    // 귀퉁이는 구역에서 잰 거리다 — 두 방향 각각은 blendM 안이어도 대각 거리가 넘으면 0
    assert.equal(wAt(-END - 70, SIDE + 70), 0);
  });

  it("그 사이에서는 바깥으로 갈수록 줄기만 한다 — 둔덕·도랑을 만들지 않는다", () => {
    let prev = 1;
    for (let x = SIDE; x <= SIDE + BLEND; x += 5) {
      const w = wAt(600, x);
      assert.ok(w <= prev && w >= 0 && w <= 1, `across ${x}: ${w}`);
      prev = w;
    }
    assert.ok(Math.abs(wAt(600, SIDE + BLEND / 2) - 0.5) < 1e-9, "가운데는 반");
  });

  it("**활주로에 걸치는 30 m 격자 칸은 꼭짓점 넷이 모두 평평한 구역이다** — 하나라도 빠지면 포장면이 기운다", () => {
    // 지형 팩 core 티어처럼 원점 기준 30 m 격자. 칸 안을 촘촘히 훑어 포장면에 닿는 칸만 고른다
    const step = 30;
    const ca = Math.cos(RW.heading);
    const sa = Math.sin(RW.heading);
    let checked = 0;
    for (let r = -10; r <= 50; r++) {
      for (let c = -10; c <= 10; c++) {
        const n0 = r * step;
        const e0 = c * step;
        let hits = false;
        for (let u = 0; u <= 6 && !hits; u++) {
          for (let v = 0; v <= 6 && !hits; v++) {
            const n = n0 + (u / 6) * step;
            const e = e0 + (v / 6) * step;
            const along = n * ca + e * sa;
            const across = -n * sa + e * ca;
            hits = along >= 0 && along <= RW.length && Math.abs(across) <= HALF;
          }
        }
        if (!hits) continue;
        checked++;
        for (const [dn, de] of [[0, 0], [step, 0], [0, step], [step, step]] as const) {
          assert.equal(floorWeight(RW, n0 + dn, e0 + de), 1, `칸 (${r}, ${c})의 꼭짓점 (${dn}, ${de})`);
        }
      }
    }
    assert.ok(checked > 80, `포장면에 닿는 칸 ${checked}`);
  });
});

describe("floorElevation — 원자료 표고에 바닥을 얹는다", () => {
  it("구역 안은 정확히 활주로 표고, 멀리서는 원자료, 그 사이는 둘 사이", () => {
    const f = { ...RW, elevation: 4 };
    assert.equal(floorElevation(f, ...ned(600, 30), 2.95), 4);
    assert.equal(floorElevation(f, ...ned(600, 500), 2.95), 2.95);
    const mid = floorElevation(f, ...ned(600, SIDE + BLEND / 2), 2);
    assert.ok(Math.abs(mid - 3) < 1e-9, `반 가중이면 2와 4의 가운데: ${mid}`);
  });

  it("결측은 결측 — 없는 땅을 지어내지 않는다", () => {
    assert.ok(Number.isNaN(floorElevation(RW, 0, 0, Number.NaN)));
  });
});

describe("floorGrid — 격자에 바닥을 얹은 새 격자", () => {
  // 원점 둘레 30 m 격자 — 0.5~2.9 m로 출렁이는 땅. 행 r의 N = −300 + 30r, 열 c의 E = −300 + 30c
  const rows = 61;
  const cols = 21;
  const n0 = -300;
  const e0 = -300;
  const step = 30;
  const bumpy = Float32Array.from({ length: rows * cols }, (_, i) => 0.5 + ((i * 7) % 25) * 0.1);
  const ORIGIN = 10 * cols + 10; // (N 0, E 0) — 시단 한가운데

  it("구역 안 표본은 활주로 표고, 멀리 있는 표본은 그대로, 입력은 안 바뀐다", () => {
    const before = Float32Array.from(bumpy);
    const g = floorGrid(bumpy, rows, cols, n0, e0, step, RW);
    assert.deepEqual(bumpy, before);
    let flat = 0;
    let kept = 0;
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const i = r * cols + c;
        const w = floorWeight(RW, n0 + r * step, e0 + c * step);
        if (w >= 1) { assert.equal(g.elev[i], 0, `(${r}, ${c})`); flat++; }
        else if (w <= 0) { assert.equal(g.elev[i], bumpy[i], `(${r}, ${c})`); kept++; }
        else assert.ok(g.elev[i]! <= bumpy[i]! && g.elev[i]! >= 0, `(${r}, ${c}) 사이: ${g.elev[i]}`);
      }
    }
    assert.ok(flat > 100 && kept > 100, `편 ${flat} · 그대로 ${kept}`);
    // 편 표본의 원자료 범위 — 캡션이 그대로 말한다
    assert.ok(g.source !== null && g.source.min >= 0.5 && g.source.max <= 2.9 + 1e-6, JSON.stringify(g.source));
    assert.ok(g.touched >= flat);
  });

  it("keep이 거짓인 표본은 건드리지 않는다 — 호출측이 바다 쪽 물속 이음을 지킨다", () => {
    const coast = Float32Array.from(bumpy);
    coast[ORIGIN] = -5;
    const g = floorGrid(coast, rows, cols, n0, e0, step, RW, (i) => i !== ORIGIN);
    assert.equal(g.elev[ORIGIN], -5);
    assert.equal(g.elev[ORIGIN + 1], 0, "옆 표본은 편다");
  });

  it("결측은 결측 그대로 둔다", () => {
    const holes = Float32Array.from(bumpy);
    holes[ORIGIN] = Number.NaN;
    const g = floorGrid(holes, rows, cols, n0, e0, step, RW);
    assert.ok(Number.isNaN(g.elev[ORIGIN]!));
  });

  it("바닥이 격자 밖이면 아무것도 안 바꾼다", () => {
    const g = floorGrid(bumpy, rows, cols, 20_000, 20_000, step, RW);
    assert.equal(g.touched, 0);
    assert.equal(g.source, null);
    assert.deepEqual(g.elev, bumpy);
  });
});
