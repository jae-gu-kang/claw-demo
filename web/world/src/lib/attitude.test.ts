import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { bodyAxesNed, eulerToQuat } from "./attitude.ts";

const near = (g: number, w: number, what = "", tol = 1e-12) =>
  assert.ok(Math.abs(g - w) < tol, `${what} ${g} ≠ ${w}`);

describe("eulerToQuat", () => {
  it("영 자세는 단위 쿼터니언", () => {
    const q = eulerToQuat(0, 0, 0)!;
    near(q[0], 1, "w"); near(q[1], 0); near(q[2], 0); near(q[3], 0);
  });

  it("단위 노름이다", () => {
    const q = eulerToQuat(0.3, -0.2, 1.1)!;
    near(Math.hypot(...q), 1, "|q|");
  });

  it("**NaN 입력은 null** — typeof 검사만으로는 안 걸린다", () => {
    // typeof NaN === "number"라, 타입만 보면 통과한다. 통과시키면 three 행렬이 통째로
    // NaN이 되고 메시가 프러스텀 컬링으로 사라진다 — 원인이 전혀 안 보이는 부류다.
    assert.equal(eulerToQuat(NaN, 0, 0), null);
    assert.equal(eulerToQuat(0, NaN, 0), null);
    assert.equal(eulerToQuat(0, 0, NaN), null);
  });

  it("무한대도 null", () => {
    assert.equal(eulerToQuat(Infinity, 0, 0), null);
    assert.equal(eulerToQuat(0, -Infinity, 0), null);
  });
});

describe("bodyAxesNed", () => {
  it("단위 쿼터니언에서 축 셋이 나온다", () => {
    const a = bodyAxesNed([1, 0, 0, 0])!;
    assert.deepEqual(a.forward, [1, 0, 0]);
    assert.deepEqual(a.right, [0, 1, 0]);
    assert.deepEqual(a.down, [0, 0, 1]);
  });

  it("**던지지 않는다** — rAF 안에서 던지면 그리지 않는 게 아니라 루프가 죽는다", () => {
    assert.equal(bodyAxesNed([0, 0, 0, 0]), null, "영 쿼터니언");
    assert.equal(bodyAxesNed([NaN, 0, 0, 0]), null, "NaN");
    assert.equal(bodyAxesNed([1, 0, 0]), null, "길이 3");
    assert.equal(bodyAxesNed(null), null);
  });

  it("성분이 전부 유한하다", () => {
    const a = bodyAxesNed(eulerToQuat(0.4, 0.2, -1.0)!)!;
    for (const v of [a.forward, a.right, a.down]) {
      for (const x of v) assert.ok(Number.isFinite(x));
    }
  });
});
