// 블록 다이어그램 데이터·히트테스트 검증 — 허브 UI(블록 클릭 → 편집 경로)의 계약
import { test } from "node:test";
import assert from "node:assert/strict";

import { BLOCKS, DIAGRAM_H, DIAGRAM_W, hitBlock } from "./blocks.js";

const VIEW_HASHES = new Set(["blocks", "trim", "margins", "envelope", "gains", "sim", "results"]);
// 엔진 레지스트리에 실존하는 카테고리/이름 (test_fcl_law·test_system이 핀)
const REGISTRY_REFS = new Set([
  "fcl/Autopilot", "fcl/ScasAxis", "fcl/Mixer",
  "actuator/SecondOrderActuator", "guidance/LOS", "nav/ErrorModel",
]);

test("블록: id 유일 + 캔버스 안 + 상세 스펙 완결", () => {
  const ids = BLOCKS.map((b) => b.id);
  assert.equal(new Set(ids).size, ids.length);
  for (const b of BLOCKS) {
    assert.ok(b.x >= 0 && b.y >= 0 && b.x + b.w <= DIAGRAM_W && b.y + b.h <= DIAGRAM_H,
      `${b.id} 캔버스 밖`);
    assert.ok(b.title, `${b.id} title 없음`);
    const d = b.detail;
    assert.ok(d && typeof d.desc === "string" && d.desc.length > 0, `${b.id} desc 없음`);
    // 이동 대상 해시는 실제 뷰만 (라우터 폴백으로 무효 링크 은폐 방지)
    if (d.edit) assert.ok(VIEW_HASHES.has(d.edit.hash), `${b.id} 무효 해시 ${d.edit.hash}`);
    // 스키마 참조는 엔진 레지스트리 실존 컴포넌트만
    if (d.schema) {
      assert.ok(REGISTRY_REFS.has(`${d.schema.category}/${d.schema.name}`),
        `${b.id} 미등록 스키마 참조`);
    }
    // 편집 가능 = 시뮬 주입 경로 보유 — schema와 store 키가 모두 있어야 함
    if (d.editable) {
      assert.ok(d.schema, `${b.id} editable인데 schema 없음`);
      assert.ok(typeof d.injectKey === "string" && d.injectKey, `${b.id} injectKey 없음`);
    } else {
      assert.equal(d.injectKey, null, `${b.id} 편집 불가인데 injectKey 있음`);
    }
  }
});

test("블록: 서로 겹치지 않음 (히트테스트 유일성)", () => {
  for (let i = 0; i < BLOCKS.length; i += 1) {
    for (let j = i + 1; j < BLOCKS.length; j += 1) {
      const a = BLOCKS[i];
      const b = BLOCKS[j];
      const overlap = a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
      assert.ok(!overlap, `${a.id} ↔ ${b.id} 겹침`);
    }
  }
});

test("hitBlock: 중심점 명중·경계 포함·빈 영역 null", () => {
  for (const b of BLOCKS) {
    assert.equal(hitBlock(b.x + b.w / 2, b.y + b.h / 2)?.id, b.id);
    assert.equal(hitBlock(b.x, b.y)?.id, b.id); // 좌상 모서리 포함
  }
  assert.equal(hitBlock(-5, -5), null);
  assert.equal(hitBlock(DIAGRAM_W - 1, DIAGRAM_H - 1), null); // 우하단 여백
});

test("주 신호 경로 조립 순서 = M7 (유도→AP→리미터→SCAS→믹서→작동기→플랜트)", () => {
  const order = ["guidance", "autopilot", "limiter", "scas", "mixer", "actuator", "plant"];
  const xs = order.map((id) => BLOCKS.find((b) => b.id === id).x);
  assert.deepEqual([...xs].sort((p, q) => p - q), xs); // 좌→우 단조
});

test("허브 계약: AP는 편집 가능, 스케줄·SCAS는 게인 탭으로 이동", () => {
  const byId = Object.fromEntries(BLOCKS.map((b) => [b.id, b.detail]));
  assert.equal(byId.autopilot.editable, true);
  assert.equal(byId.autopilot.injectKey, "autopilotParams");
  assert.equal(byId.schedule.edit.hash, "gains");
  assert.equal(byId.scas.edit.hash, "gains"); // 게인 정본은 스케줄 — 폼은 열람 전용
  assert.equal(byId.limiter.edit.hash, "envelope");
  assert.equal(byId.actuator.edit.hash, "sim");
  assert.equal(byId.nav.edit.hash, "sim");
});
