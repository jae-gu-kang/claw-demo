import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { SKID_DEPLOY_LEAD_S, SKID_DEPLOY_S, parseStow, stowFraction } from "./stow.ts";

describe("parseStow — 모델이 선언한 접는 노드(루트 extras `claw_stow`)", () => {
  it("JSON 문자열(블렌더 사용자 속성)과 객체를 다 받는다", () => {
    const want = [{ node: "Skid_R", rot: [0, 0, 0.6] }, { node: "Skid_L", rot: [0, 0, -0.6] }];
    assert.deepEqual(parseStow('{"Skid_R": [0, 0, 0.6], "Skid_L": [0, 0, -0.6]}'), want);
    assert.deepEqual(parseStow({ Skid_R: [0, 0, 0.6], Skid_L: [0, 0, -0.6] }), want);
  });

  it("못 읽는 항목은 빼고, 못 읽는 선언은 빈 목록 — 던지지 않는다(모델 하나가 화면을 세우면 안 된다)", () => {
    assert.deepEqual(parseStow(undefined), []);
    assert.deepEqual(parseStow("{not json"), []);
    assert.deepEqual(parseStow("[1, 2, 3]"), []);
    assert.deepEqual(parseStow({ A: [0, 0], B: [0, 0, "x"], C: [0, Number.NaN, 0], D: [0.1, 0, 0] }),
      [{ node: "D", rot: [0.1, 0, 0] }]);
  });
});

describe("stowFraction — 1 접힘 · 0 펼침", () => {
  const TD = 500;
  it("관에서 발사하지 않는 결과는 늘 펼침 — 접을 까닭이 없다", () => {
    assert.equal(stowFraction(0, false, TD), 0);
    assert.equal(stowFraction(0, false, null), 0);
  });

  it("관에서 발사하고 착지가 없으면 내내 접힘", () => {
    assert.equal(stowFraction(0, true, null), 1);
    assert.equal(stowFraction(9999, true, null), 1);
  });

  it("관 안·비행 중엔 접고, 접지 전에 다 편다", () => {
    assert.equal(stowFraction(0, true, TD), 1);
    assert.equal(stowFraction(TD - SKID_DEPLOY_LEAD_S, true, TD), 1);
    assert.equal(stowFraction(TD - SKID_DEPLOY_LEAD_S + SKID_DEPLOY_S, true, TD), 0);
    assert.equal(stowFraction(TD, true, TD), 0, "접지 때는 다 펴져 있다");
    assert.equal(stowFraction(TD + 100, true, TD), 0, "활주·정지 중에도");
    assert.ok(SKID_DEPLOY_LEAD_S > SKID_DEPLOY_S);
    let prev = 2;
    for (let k = 0; k <= 20; k++) {
      const f = stowFraction(TD - SKID_DEPLOY_LEAD_S + (SKID_DEPLOY_S * k) / 20, true, TD);
      assert.ok(f <= prev, `단조 감소 ${k}`);
      prev = f;
    }
  });

  it("시각이 성하지 않으면 접힘으로 둔다 — 펼침을 지어내지 않는다", () => {
    assert.equal(stowFraction(Number.NaN, true, TD), 1);
  });
});
