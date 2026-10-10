// 도식 → three 메시 — 기체 탭 대표 그림과 가상환경 대체 기체가 같은 함수를 쓴다. three의 형상·재질은 WebGL 없이
// node에서 선다(렌더러만 안 만든다). 축이 틀리면 가상환경에서 도식이 옆으로 누워 날아가므로 여기서 잡는다.
//
// **three가 없으면 건너뛴다(사유를 남긴다)** — materials.test.ts와 같은 사정이다. 빠른 CI층은 npm 설치 없이 돈다
// (.github/workflows/fast.yml). 도식·모델 모듈이 three를 들여오므로 정적 import면 모듈 연결에서 파일째 실패한다.
// 그래서 동적으로 들이고, **three가 없을 때만** 건너뛴다 — 도식 모듈 자신의 오류는 그대로 던져 실패로 센다.
import { strict as assert } from "node:assert";
import { describe, it } from "node:test";

import type { BufferAttribute, Mesh as ThreeMesh, MeshStandardMaterial } from "three";

import { LOCAL_NOSE, LOCAL_STARBOARD, LOCAL_UP } from "../core/modelaxes.ts";
import { surfacePose } from "../core/surfaces.ts";
import type { BodyAxes } from "../lib/attitude.ts";
import { vehicleSchematic } from "../lib/vehicleschematic.ts";

async function loadScene() {
  try {
    await import("three");
  } catch (e) {
    if ((e as { code?: string }).code === "ERR_MODULE_NOT_FOUND") return null;
    throw e;
  }
  const [{ Group }, models, schematic] = await Promise.all([import("three"), import("./models.ts"), import("./schematic.ts")]);
  return { Group, ...models, ...schematic };
}

const scene = await loadScene();
// 건너뛴 묶음은 본문을 돌지 않는다 — 아래 `scene!`은 three가 있을 때만 읽힌다
const skip = scene == null && "three 미설치 — 도식 메시를 세울 수 없다(npm 설치가 없는 빠른 CI층)";

const DOC = { geometry: { b: 2.5, S: 3.0, cbar: 1.5 }, ground: {} };

/** 모델 로컬 정점들 중 방향 d로 가장 먼 거리. */
const reach = (pos: ArrayLike<number>, d: readonly number[]): number => {
  let best = -Infinity;
  for (let i = 0; i < pos.length; i += 3) {
    best = Math.max(best, pos[i]! * d[0]! + pos[i + 1]! * d[1]! + pos[i + 2]! * d[2]!);
  }
  return best;
};

describe("schematicObject — FRD 도식을 GLB와 같은 모델 로컬 축에", { skip }, () => {
  const { schematicObject } = scene!;
  const mesh = vehicleSchematic(DOC).mesh;
  assert.ok(mesh, "도식이 없다");
  const obj = schematicObject(mesh);
  const pos = (obj.geometry.getAttribute("position") as BufferAttribute).array;

  it("기수는 모델 로컬 기수 방향, 익단은 우현 방향, 수직미익은 위 — 자세 행렬이 그대로 먹는다", () => {
    const cRoot = (2 * DOC.geometry.S) / DOC.geometry.b;
    assert.ok(Math.abs(reach(pos, LOCAL_NOSE) - 0.4 * cRoot) < 1e-6, "기수가 CG 앞 0.4 c_root에 선다");
    assert.ok(Math.abs(reach(pos, LOCAL_STARBOARD) - DOC.geometry.b / 2) < 1e-6, "우익단이 우현 b/2");
    assert.ok(reach(pos, LOCAL_UP) > 0.5, "수직미익은 위로 선다(FRD −z)");
    // 평평한 음영 — 정점 수가 FRD 원본과 같다(변환이 정점을 버리거나 합치지 않는다)
    assert.equal(pos.length, mesh.positions.length);
  });

  it("엘레본만 다른 색 — 믹서가 쓰는 4면이 눈에 띈다, 그림자를 드리운다", () => {
    const mats = obj.material as MeshStandardMaterial[];
    assert.equal(mats.length, mesh.groups.length);
    const color = (name: string) => mats[mesh.groups.findIndex((g) => g.name === name)]!.color.getHex();
    assert.notEqual(color("elevon"), color("wing"));
    assert.equal(obj.castShadow, true);
  });
});

describe("schematicVehicle — GLB 자리에 서는 도식 기체", { skip }, () => {
  const { Group, applySurfaces, hideVehicle, schematicVehicle, setVehiclePose, spinPropeller } = scene!;
  const mesh = vehicleSchematic(DOC).mesh!;

  it("GLB와 같은 기체 계약을 탄다 — 자세·숨김은 먹고, 몰 노드가 없어 타면·프로펠러는 그냥 지나간다", () => {
    const v = schematicVehicle(mesh);
    // 기대한 적 없는 노드를 "못 찾았다"고 캡션에 싣지 않는다
    assert.deepEqual(v.missing, []);
    assert.equal(v.nodes.size, 0);
    const axes: BodyAxes = { forward: [1, 0, 0], right: [0, 1, 0], down: [0, 0, 1] };
    setVehiclePose(v, [100, 50, -300], axes);
    assert.equal(v.root.visible, true);
    assert.equal(v.root.matrixAutoUpdate, false, "자세 행렬을 직접 쓴다(GLB와 같은 경로)");
    hideVehicle(v);
    assert.equal(v.root.visible, false, "결측이면 숨긴다 — 도식도 없는 자세를 지어내지 않는다");
    assert.equal(applySurfaces(v, surfacePose(0.1, 0.05, 0.02, {})), true);
    assert.doesNotThrow(() => spinPropeller(v, 200, 0.016));
  });

  it("대기 산란은 GLB처럼 걸고, 떼면 장면에서 빠진다", () => {
    const v = schematicVehicle(mesh);
    const mats = (v.root.children[0] as ThreeMesh).material as (MeshStandardMaterial & { __aerial?: boolean })[];
    assert.ok(mats.every((m) => m.__aerial === true), "먼 도식만 또렷하면 오려 붙인 것처럼 보인다");
    const parent = new Group();
    parent.add(v.root);
    v.dispose();
    assert.equal(parent.children.length, 0);
  });
});
