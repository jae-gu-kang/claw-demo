import { strict as assert } from "node:assert";
import { describe, it } from "node:test";

import { SCHEMATIC_NOTE, schematicCaption, vehicleSchematic } from "./vehicleschematic.ts";
import { vehicleModelPlan } from "./world3d.ts";
import { heroPlan } from "../../../js/lib/aircrafthero.js";

// 쇼케이스급 기준량(익폭 2.5 m · 기준면적 3.0 m² · 스키드 넷) — 표시 모델 이름은 중립
const DOC = {
  geometry: { b: 2.5, S: 3.0, cbar: 1.5 },
  ground: { skid: { contacts: [[0.6, -0.6, 0.55], [-0.6, -0.6, 0.55], [0.6, 0.6, 0.55], [-0.6, 0.6, 0.55]] } },
  display: { kind: "model", model: "delta.glb" },
};

describe("vehicleSchematic — 기체 탭과 같은 도식", () => {
  it("문서 기준량에서 **기체 탭 대표 그림과 같은** 메시를 만든다 — 치수 대응을 두 벌 두지 않는다", () => {
    const got = vehicleSchematic(DOC);
    assert.equal(got.reason, null);
    assert.ok(got.mesh, "도식이 없다");
    const hero = heroPlan(DOC, null).schematic;
    assert.ok(hero, "기체 탭 도식이 없다");
    assert.deepEqual(got.mesh.positions, hero.positions);
    assert.deepEqual(got.mesh.indices, hero.indices);
    assert.deepEqual(got.mesh.groups, hero.groups);
    // 스키드도 싣는다 — 문서의 접촉점 넷이 도식에 선다(없는 것을 지어내지도, 있는 것을 빼지도 않는다)
    const bare = vehicleSchematic({ ...DOC, ground: {} }).mesh;
    assert.ok(bare && got.mesh.positions.length > bare.positions.length);
  });

  it("문서가 없으면 도식도 없다 — 사유는 기체 모델 계획(궤적만)이 이미 말한다", () => {
    assert.deepEqual(vehicleSchematic(null), { mesh: null, reason: null });
    assert.deepEqual(vehicleSchematic("x"), { mesh: null, reason: null });
  });

  it("기준량이 깨졌으면 도식 대신 사유 — 0으로 메운 판을 그리지 않는다", () => {
    const got = vehicleSchematic({ ...DOC, geometry: { b: 0, S: 3, cbar: 1.5 } });
    assert.equal(got.mesh, null);
    assert.match(got.reason ?? "", /도식을 만들 수 없습니다/);
  });
});

describe("schematicCaption — 「궤적만」이 아니라 도식으로 대신 그린다고 말한다", () => {
  const manifest = { models: [{ name: "launcher.glb" }], models_reason: "모델 폴더가 없습니다 (models)" };

  it("표시 모델이 없는 기체 · 서버 자산에 없는 모델 — 사유는 그대로, 결말만 도식으로", () => {
    for (const doc of [{ ...DOC, display: { kind: "schematic" } }, DOC]) {
      const note = vehicleModelPlan(doc, manifest, { label: "이 런의 기체" }).note;
      assert.ok(note && /궤적만/.test(note), `원문 사유가 바뀌었다: ${note}`);
      const cap = schematicCaption(note);
      assert.doesNotMatch(cap, /궤적만/, "도식을 그리면서 궤적만 그린다고 말하면 화면과 캡션이 어긋난다");
      assert.match(cap, /도식으로 대신 그립니다/);
    }
    // 서버 자산 사유(모델 폴더 없음)는 지우지 않는다 — 사람이 할 일이 거기 있다
    assert.match(schematicCaption(vehicleModelPlan(DOC, manifest).note), /모델 폴더가 없습니다/);
  });

  it("GLB를 못 읽은 사유(궤적만이 없는 문장)에는 결말을 덧붙인다", () => {
    const cap = schematicCaption("모델을 읽지 못했습니다 (/api/world/model/delta.glb) — 404");
    assert.match(cap, /^모델을 읽지 못했습니다 .* — 404 — 도식으로 대신 그립니다\.$/);
  });

  it("도식이 무엇인지 — 기준량에서 만든 표시용이고 타면·프로펠러는 안 움직인다", () => {
    assert.match(SCHEMATIC_NOTE, /익폭·기준면적/);
    assert.match(SCHEMATIC_NOTE, /타면·프로펠러/);
  });
});
