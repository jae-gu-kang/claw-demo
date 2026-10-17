// 모델 재질에 하늘 환경광을 꽂는 규칙 — PBR 재질만, 같은 텍스처면 다시 안 짜고, 붙였다 뗄 때만 프로그램을 다시 짠다.
//
// **three가 없으면 건너뛴다(사유를 남긴다)** — materials.test.ts와 같은 사유(빠른 CI층은 npm 설치 없이 돈다).
import assert from "node:assert/strict";
import { describe, it } from "node:test";

async function load(t: { skip(msg: string): void }) {
  try {
    const three = await import("three");
    const { setModelEnvironment } = await import("./models.ts");
    return { three, setModelEnvironment };
  } catch {
    t.skip("three 미설치 — 재질 형식을 만들 수 없다(npm 설치가 없는 빠른 CI층)");
    return null;
  }
}

describe("setModelEnvironment — 모델 재질의 하늘 환경광", () => {
  it("PBR 재질(표준·물리)에만 꽂고 세기를 맞춘다", async (t) => {
    const m = await load(t);
    if (!m) return;
    const { three, setModelEnvironment } = m;
    const std = new three.MeshStandardMaterial();
    const phys = new three.MeshPhysicalMaterial({ clearcoat: 0.12 });
    const basic = new three.MeshBasicMaterial();
    const root = new three.Group();
    root.add(new three.Mesh(new three.BoxGeometry(), [std, basic]), new three.Mesh(new three.BoxGeometry(), phys));
    const env = new three.Texture();
    assert.equal(setModelEnvironment(root, env, 0.7), 2);
    assert.equal(std.envMap, env);
    assert.equal(phys.envMap, env);
    assert.equal(basic.envMap, null, "조명 없는 재질은 건드리지 않는다");
    assert.equal(std.envMapIntensity, 0.7);
  });

  it("같은 텍스처면 아무것도 안 바꾸고, 붙이거나 뗄 때만 프로그램을 다시 짠다", async (t) => {
    const m = await load(t);
    if (!m) return;
    const { three, setModelEnvironment } = m;
    const std = new three.MeshStandardMaterial();
    const root = new three.Mesh(new three.BoxGeometry(), std);
    const a = new three.Texture();
    const b = new three.Texture();
    const v0 = std.version;
    setModelEnvironment(root, a, 1);
    assert.ok(std.version > v0, "처음 붙이면 셰이더에 환경광 갈래가 생긴다");
    const v1 = std.version;
    assert.equal(setModelEnvironment(root, a, 1), 0);
    assert.equal(setModelEnvironment(root, b, 1), 1, "다시 구운 텍스처로 갈아 끼운다");
    assert.equal(std.version, v1, "텍스처만 바뀌면 프로그램은 그대로다");
    setModelEnvironment(root, null, 1);
    assert.ok(std.version > v1);
  });

  it("모델을 놓아도 함께 꽂은 환경광은 파괴하지 않는다 — 주인은 장면이다", async (t) => {
    const m = await load(t);
    if (!m) return;
    const { three } = m;
    const { disposeMaterial } = await import("./dispose.ts");
    const env = new three.Texture();
    const own = new three.Texture();
    const gone: string[] = [];
    env.addEventListener("dispose", () => gone.push("env"));
    own.addEventListener("dispose", () => gone.push("own"));
    disposeMaterial(new three.MeshStandardMaterial({ map: own, envMap: env }));
    assert.deepEqual(gone, ["own"]);
  });
});
