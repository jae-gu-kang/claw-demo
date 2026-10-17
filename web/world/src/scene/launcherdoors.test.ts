// 발사관 포구 문 — 두 짝의 노드에 열림을 넣는 규칙. 각과 부호는 core/launcher.ts의 doorRotations가 정본이고(그쪽 테스트가
// 회전을 실제로 적용해 확인한다), 여기서는 노드에 옳게 실리는지·문이 없는 옛 GLB에서 조용히 물러나는지만 본다.
//
// **three가 없으면 건너뛴다(사유를 남긴다)** — modelenv.test.ts와 같은 사유(빠른 CI층은 npm 설치 없이 돈다).
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { doorRotations } from "../core/launcher.ts";

async function load(t: { skip(msg: string): void }) {
  try {
    const three = await import("three");
    const { applyLauncherDoors } = await import("./models.ts");
    return { three, applyLauncherDoors };
  } catch {
    t.skip("three 미설치 — 노드를 만들 수 없다(npm 설치가 없는 빠른 CI층)");
    return null;
  }
}

function fakeModel(three: typeof import("three"), names: string[]) {
  const nodes = new Map(names.map((n) => [n, new three.Object3D()] as const));
  return { root: new three.Group(), nodes, missing: [], unknown: [], dispose() {} };
}

describe("applyLauncherDoors — 포구 문 두 짝", () => {
  it("열림을 두 노드의 rotation.y에 싣는다", async (t) => {
    const m = await load(t);
    if (!m) return;
    const model = fakeModel(m.three, ["Door_L", "Door_R"]);
    assert.equal(m.applyLauncherDoors(model, 0.5), true);
    const want = doorRotations(0.5);
    assert.equal(model.nodes.get("Door_L")!.rotation.y, want.left);
    assert.equal(model.nodes.get("Door_R")!.rotation.y, want.right);
    m.applyLauncherDoors(model, 0);
    assert.equal(Math.abs(model.nodes.get("Door_R")!.rotation.y), 0, "닫힘"); // −0도 닫힘이다
  });

  it("문이 없는 GLB면 false — 호출측이 전주를 건너뛴다(기체가 빈 시각 0에서 기다리지 않게)", async (t) => {
    const m = await load(t);
    if (!m) return;
    assert.equal(m.applyLauncherDoors(fakeModel(m.three, ["Turntable", "Cradle"]), 1), false);
    assert.equal(m.applyLauncherDoors(fakeModel(m.three, ["Door_L"]), 1), false, "한 짝만 있으면 문이 아니다");
  });
});
