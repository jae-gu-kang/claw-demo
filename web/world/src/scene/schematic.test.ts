// 도식 → three 메시 — 기체 탭 대표 그림과 가상환경 대체 기체가 같은 함수를 쓴다. three의 형상·재질은 WebGL 없이
// node에서 선다(렌더러만 안 만든다). 축이 틀리면 가상환경에서 도식이 옆으로 누워 날아가므로 여기서 잡는다.
import { strict as assert } from "node:assert";
import { describe, it } from "node:test";

import { Group, type BufferAttribute, type Mesh as ThreeMesh, type MeshStandardMaterial } from "three";

import { LOCAL_NOSE, LOCAL_STARBOARD, LOCAL_UP } from "../core/modelaxes.ts";
import { surfacePose } from "../core/surfaces.ts";
import type { BodyAxes } from "../lib/attitude.ts";
import { vehicleSchematic } from "../lib/vehicleschematic.ts";
import { applySurfaces, hideVehicle, setVehiclePose, spinPropeller } from "./models.ts";
import { schematicObject, schematicVehicle } from "./schematic.ts";

const DOC = { geometry: { b: 2.5, S: 3.0, cbar: 1.5 }, ground: {} };

/** 모델 로컬 정점들 중 방향 d로 가장 먼 거리. */
const reach = (pos: ArrayLike<number>, d: readonly number[]): number => {
  let best = -Infinity;
  for (let i = 0; i < pos.length; i += 3) {
    best = Math.max(best, pos[i]! * d[0]! + pos[i + 1]! * d[1]! + pos[i + 2]! * d[2]!);
  }
  return best;
};

describe("schematicObject — FRD 도식을 GLB와 같은 모델 로컬 축에", () => {
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

describe("schematicVehicle — GLB 자리에 서는 도식 기체", () => {
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
