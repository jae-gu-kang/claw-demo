// SceneController는 three·WebGL 호스트를 잡고 서서 node에서 세울 수 없다 — 배선은 **원문에서 읽는다**
// (web/js/lib/influence.test.js·aircraftcue.test.js와 같은 가드). 판단 자체는 core/runway.ts·lib가 테스트한다.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

const src = readFileSync(new URL("./SceneController.ts", import.meta.url), "utf8");
const fn = (name: string) =>
  src.match(new RegExp(`\\n  (?:private )?(?:async )?${name}\\([\\s\\S]*?\\n  \\}\\n`))?.[0] ?? "";

describe("SceneController 배선", () => {
  it("활주로는 제원 폭(siteRunwayWidth)으로 core/runway.ts가 그린다 — 폭 상수를 다시 적지 않는다", () => {
    const build = fn("buildScene");
    assert.ok(build, "buildScene이 없다");
    assert.match(build, /runwayDrawing\(rw, siteRunwayWidth\(rw\)\)/);
    assert.doesNotMatch(build, /\* 22\b/, "옛 22 m 반폭 상수");
    assert.doesNotMatch(src, /폭은 결과에 없습니다/);
    // 선분마다 따로 — 한 꺾은선에 이어 담으면 활주로를 가로지르는 대각선이 그어진다
    assert.match(build, /for \(const points of rwDraw\.segments\) rwLines\.push\(\{ points, color: 0xffffff \}\)/);
  });

  it("기체 동기화는 장면의 결과가 바뀔 때만 물러난다 — 새 요청이 실패해도 받던 모델·캡션이 멈추지 않는다", () => {
    const sync = fn("syncVehicle");
    assert.ok(sync, "syncVehicle이 없다");
    assert.equal(sync.match(/gen !== this\.vehicleGen \|\| this\.disposed/g)?.length, 2);
    assert.doesNotMatch(sync, /this\.loadGen/, "요청 세대(loadGen)로 물리면 실패한 새 요청이 받던 GLB를 버린다");
    // 문서를 받는 동안의 캡션 — 「모델이 없어 궤적만」이 아니라 받는 중
    assert.match(sync, /this\.vehicleLoading = "doc";\n\s*this\.emitNotes\(\);\n\s*const src = await source\(\);/);
    const load = fn("loadResult");
    assert.ok(load, "loadResult가 없다");
    // 세대는 결과를 받아 장면에 앉힌 **뒤에만** 오른다(받기 실패 경로보다 뒤)
    const bump = load.indexOf("++this.vehicleGen");
    assert.ok(bump > load.indexOf("this.body = body;"), "세대는 새 결과가 장면에 앉은 뒤에 오른다");
    assert.ok(bump > load.lastIndexOf("return false;", load.indexOf("this.body = body;")));
    assert.match(load, /void this\.syncVehicle\(vgen, /);
    assert.match(fn("vehicleFromSelection"), /this\.syncVehicle\(this\.vehicleGen, /);
    // 문서를 받는 중인 단계가 캡션에 있다
    assert.match(fn("vehicleNotes"), /this\.vehicleLoading === "doc"/);
  });

  it("GLB가 없거나 못 읽으면 궤적만 두지 않고 기체 탭과 같은 도식을 그 자리에 세운다", () => {
    const sync = fn("syncVehicle");
    // 두 갈래 다 — 표시 모델을 못 정했을 때(계획 단계)와 GLB를 못 읽었을 때(로드 단계)
    assert.match(sync, /if \(plan\.model == null\) \{\n\s*this\.standInSchematic\(src\.doc, plan\.note\);/);
    assert.match(sync, /this\.vehicleNote = r\.reason;\n\s*this\.standInSchematic\(src\.doc, r\.reason\);/);
    const stand = fn("standInSchematic");
    assert.ok(stand, "standInSchematic이 없다");
    // 형상은 이 런의 문서에서(lib/vehicleschematic.ts → 기체 탭 heroPlan) — 치수를 여기서 다시 적지 않는다
    assert.match(stand, /vehicleSchematic\(doc\)/);
    assert.match(stand, /schematicVehicle\(s\.mesh\)/);
    assert.match(stand, /this\.vehicleCaption = schematicCaption\(why\)/);
    assert.match(stand, /this\.host\.modelGroup\.add\(this\.vehicle\.root\)/);
    // 도식에는 몰 노드가 없다 — 타면·프로펠러 캡션 대신 도식 캡션
    assert.match(fn("vehicleNotes"), /if \(this\.vehicleKind === "schematic"\) return \[\.\.\.head, SCHEMATIC_NOTE\];/);
  });

  it("기체 판정이 끝났다는 신호(onVehicle)는 끝나는 모든 갈래에서, 새로 맞출 때는 문서를 받기 전에 내린다", () => {
    const sync = fn("syncVehicle");
    // 내리는 것은 첫 await 앞 — loadResult가 shownId를 갱신하기 전에 거짓이 앉아야 투어가 옛 참을 보지 않는다
    assert.match(sync, /this\.setVehicleSettled\(false\);\n[^\n]*\n\s*this\.vehicleLoading = "doc";\n\s*this\.emitNotes\(\);\n\s*const src = await source\(\);/);
    // 같은 모델 재사용 · 모델 없음(도식/궤적만) · GLB 로드 끝(성공·실패) — 셋
    assert.equal(sync.match(/this\.setVehicleSettled\(true\)/g)?.length, 3);
    // 물러나는(세대가 바뀐) 갈래는 알리지 않는다 — 새 세대의 동기화가 알린다
    for (const stale of sync.match(/if \(gen !== this\.vehicleGen \|\| this\.disposed\)[^\n]*/g) ?? []) {
      assert.doesNotMatch(stale, /setVehicleSettled/);
    }
    assert.match(fn("setVehicleSettled"), /this\.cb\.onVehicle\(v\)/);
  });
});
