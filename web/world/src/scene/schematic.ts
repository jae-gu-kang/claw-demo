/** 절차 도식 메시(FRD 성분) → three 메시 — 기체 탭 대표 그림(`aircraftViewer.ts`)과 가상환경 대체 기체
 *  (`models.ts schematicVehicle`)가 **같은 것**을 쓴다. 축 사상은 `core/modelaxes.ts frdToModelLocal`이 정본이라,
 *  여기서 만든 메시는 GLB와 같은 모델 로컬 축에 앉고 `setVehiclePose`가 그대로 자세를 입힌다. */

import { BufferAttribute, BufferGeometry, Group, Mesh, MeshStandardMaterial, type Material } from "three";

import { frdToModelLocal } from "../core/modelaxes.ts";
import type { SchematicMesh } from "../lib/vehicleschematic.ts";
import { applyAerialPerspective } from "./atmosphere.ts";
import { disposeTree } from "./dispose.ts";
import type { LoadedModel } from "./models.ts";

/** 도식 색 — 엘레본만 눈에 띄게(믹서가 쓰는 그 4면). 표시 선택이다 */
const SCHEMATIC_COLOR: Record<string, number> = { wing: 0xb8c1cb, elevon: 0xe08a2e, body: 0x7b8591 };

export function schematicObject(mesh: SchematicMesh): Mesh {
  const n = mesh.positions.length / 3;
  const pos = new Float32Array(mesh.positions.length);
  const nrm = new Float32Array(mesh.normals.length);
  for (let i = 0; i < n; i++) {
    const k = 3 * i;
    pos.set(frdToModelLocal([mesh.positions[k]!, mesh.positions[k + 1]!, mesh.positions[k + 2]!]), k);
    nrm.set(frdToModelLocal([mesh.normals[k]!, mesh.normals[k + 1]!, mesh.normals[k + 2]!]), k);
  }
  const geo = new BufferGeometry();
  geo.setAttribute("position", new BufferAttribute(pos, 3));
  geo.setAttribute("normal", new BufferAttribute(nrm, 3));
  geo.setIndex(new BufferAttribute(new Uint16Array(mesh.indices), 1));
  const mats = mesh.groups.map((g, i) => {
    geo.addGroup(g.start, g.count, i);
    return new MeshStandardMaterial({ color: SCHEMATIC_COLOR[g.name] ?? 0xaab2bc, roughness: 0.55, metalness: 0.1 });
  });
  const obj = new Mesh(geo, mats);
  obj.castShadow = true;
  obj.receiveShadow = true;
  return obj;
}

/** 가상환경 대체 기체 — 도식을 GLB와 같은 `LoadedModel` 모양으로 감싼다(`models.ts`의 자세·숨김이 그대로 먹는다).
 *
 * **몰 노드가 없다** — `nodes`가 비어 `applySurfaces`·`spinPropeller`는 그냥 지나가고, `missing`도 비운다(기대한 적
 * 없는 노드를 "못 찾았다"고 캡션에 싣지 않는다). 움직이지 않는 사실은 캡션(`SCHEMATIC_NOTE`)이 말한다.
 * 대기 산란은 GLB처럼 건다 — 빠뜨리면 먼 도식만 또렷해 오려 붙인 것처럼 보인다. 마모는 걸지 않는다(도식은 도장이 아니다). */
export function schematicVehicle(mesh: SchematicMesh): LoadedModel {
  const obj = schematicObject(mesh);
  for (const m of obj.material as Material[]) applyAerialPerspective(m);
  const root = new Group();
  root.add(obj);
  return {
    root,
    nodes: new Map(),
    missing: [],
    dispose() {
      root.removeFromParent(); // 자원을 놓기 전에 씬에서 뗀다(models.ts loadModel과 같은 순서)
      disposeTree(root);
    },
  };
}
