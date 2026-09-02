import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { bodyAxesNed, eulerToQuat } from "../lib/attitude.ts";
import {
  LOCAL_NOSE, LOCAL_STARBOARD, LOCAL_UP,
  determinant, localToNed, modelColumnsNed,
} from "./modelaxes.ts";

const D2R = Math.PI / 180;
const near = (g: number, w: number, what = "", tol = 1e-9) =>
  assert.ok(Math.abs(g - w) < tol, `${what} ${g} ≠ ${w}`);

/** 오일러각 → 모델 열. 엔진과 같은 규약(3-2-1, scalar-first)을 `lib/attitude.js`가 낸다. */
const columnsFor = (phi: number, theta: number, psi: number) =>
  modelColumnsNed(bodyAxesNed(eulerToQuat(phi, theta, psi)!)!);

describe("모델 로컬축 → NED", () => {
  it("수평·기수 북에서 기수가 북을 본다", () => {
    const nose = localToNed(columnsFor(0, 0, 0), LOCAL_NOSE);
    near(nose[0], 1, "북"); near(nose[1], 0, "동"); near(nose[2], 0, "하");
  });

  it("요 90°면 기수가 **동**을 본다 — 부호가 뒤집히면 서쪽이 된다", () => {
    const nose = localToNed(columnsFor(0, 0, 90 * D2R), LOCAL_NOSE);
    near(nose[0], 0, "북"); near(nose[1], 1, "동");
  });

  it("피치업이면 기수가 위를 본다 (d < 0)", () => {
    const nose = localToNed(columnsFor(0, 20 * D2R, 0), LOCAL_NOSE);
    assert.ok(nose[2] < 0, "d가 음수여야 상방");
    near(nose[2], -Math.sin(20 * D2R), "d");
  });

  it("우현은 요 0에서 동을 본다", () => {
    const stbd = localToNed(columnsFor(0, 0, 0), LOCAL_STARBOARD);
    near(stbd[1], 1, "동");
  });

  it("우롤이면 상방 벡터가 **동쪽으로** 기운다", () => {
    const up = localToNed(columnsFor(30 * D2R, 0, 0), LOCAL_UP);
    assert.ok(up[1] > 0, "우롤에서 기체 상방이 우현(동)으로 기울어야 한다");
    near(up[1], Math.sin(30 * D2R), "동 성분");
  });
});

describe("거울상이 되지 않는다", () => {
  it("여러 자세에서 행렬식이 +1이다", () => {
    for (const [p, t, y] of [
      [0, 0, 0], [30, 10, 45], [-60, -20, 200], [10, 80, -170],
    ] as const) {
      near(determinant(columnsFor(p * D2R, t * D2R, y * D2R)), 1, `φ${p} θ${t} ψ${y}`, 1e-9);
    }
  });

  it("열이 서로 직교하고 단위길이다", () => {
    const c = columnsFor(20 * D2R, -15 * D2R, 100 * D2R);
    const dot = (a: number[], b: number[]) => a[0]! * b[0]! + a[1]! * b[1]! + a[2]! * b[2]!;
    for (const v of [c.x, c.y, c.z]) near(Math.hypot(...v), 1, "단위길이");
    near(dot(c.x, c.y), 0, "x·y"); near(dot(c.y, c.z), 0, "y·z"); near(dot(c.x, c.z), 0, "x·z");
  });
});

describe("사상 자체", () => {
  it("로컬 X=우현, Y=−하방, Z=−전방", () => {
    const axes = {
      forward: [1, 2, 3] as [number, number, number],
      right: [4, 5, 6] as [number, number, number],
      down: [7, 8, 9] as [number, number, number],
    };
    const c = modelColumnsNed(axes);
    assert.deepEqual(c.x, [4, 5, 6]);
    assert.deepEqual(c.y, [-7, -8, -9]);
    assert.deepEqual(c.z, [-1, -2, -3]);
  });
});
