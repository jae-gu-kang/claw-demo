// 접는 노드(착륙 스키드)를 모델에 싣는 규칙 — 쉬는 자세(펼침)를 한 번 기억하고 거기에 선언한 회전 × 접힘을 더한다.
// **three가 없으면 건너뛴다(사유를 남긴다)** — modelenv.test.ts와 같은 사유.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

async function load(t: { skip(msg: string): void }) {
  try {
    const three = await import("three");
    const { applyStow, hasStow } = await import("./models.ts");
    return { three, applyStow, hasStow };
  } catch {
    t.skip("three 미설치 — 노드를 만들 수 없다(npm 설치가 없는 빠른 CI층)");
    return null;
  }
}

function fakeModel(three: typeof import("three"), stow: unknown) {
  const scene = new three.Group();
  const root = new three.Object3D();
  root.name = "SHAHED136_Root";
  if (stow !== undefined) root.userData.claw_stow = stow;
  const leg = new three.Object3D();
  leg.name = "Skid_R";
  leg.rotation.set(0.1, 0, 0.2);                       // 쉬는 자세가 0이 아니어도 그 위에 더한다
  root.add(leg);
  scene.add(root);
  return { model: { root: scene, nodes: new Map(), missing: [], unknown: [], dispose() {} }, leg };
}

describe("applyStow — 선언한 노드를 접고 편다", () => {
  it("쉬는 자세 + 회전 × 접힘, 0이면 쉬는 자세로 돌아온다", async (t) => {
    const m = await load(t);
    if (!m) return;
    const { model, leg } = fakeModel(m.three, '{"Skid_R": [0, 0, 0.6]}');
    assert.equal(m.hasStow(model), true);
    assert.equal(m.applyStow(model, 1), true);
    assert.ok(Math.abs(leg.rotation.z - 0.8) < 1e-12 && Math.abs(leg.rotation.x - 0.1) < 1e-12);
    m.applyStow(model, 0.5);
    assert.ok(Math.abs(leg.rotation.z - 0.5) < 1e-12, "매 프레임 더해 쌓이지 않는다");
    m.applyStow(model, 0);
    assert.ok(Math.abs(leg.rotation.z - 0.2) < 1e-12);
  });

  it("선언이 없거나 노드가 없으면 false — 아무것도 안 돌린다", async (t) => {
    const m = await load(t);
    if (!m) return;
    assert.equal(m.applyStow(fakeModel(m.three, undefined).model, 1), false);
    assert.equal(m.hasStow(fakeModel(m.three, undefined).model), false);
    assert.equal(m.applyStow(fakeModel(m.three, '{"Nope": [0, 0, 1]}').model, 1), false);
  });
});
