import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { SKID_DEPLOY_LEAD_S, SKID_DEPLOY_S, parseStow, railExitTime, stowFraction } from "./stow.ts";

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
  const EXIT = 0.6;
  it("관에서 발사하지 않는 결과는 늘 펼침 — 접을 까닭이 없다", () => {
    assert.equal(stowFraction(0, false, TD, EXIT), 0);
    assert.equal(stowFraction(0, false, null, EXIT), 0);
  });

  it("관에서 발사하고 착지가 없으면 내내 접힘", () => {
    assert.equal(stowFraction(0, true, null, EXIT), 1);
    assert.equal(stowFraction(9999, true, null, EXIT), 1);
  });

  it("관 안·비행 중엔 접고, 접지 전에 다 편다", () => {
    assert.equal(stowFraction(0, true, TD, EXIT), 1);
    assert.equal(stowFraction(TD - SKID_DEPLOY_LEAD_S, true, TD, EXIT), 1);
    assert.equal(stowFraction(TD - SKID_DEPLOY_LEAD_S + SKID_DEPLOY_S, true, TD, EXIT), 0);
    assert.equal(stowFraction(TD, true, TD, EXIT), 0, "접지 때는 다 펴져 있다");
    assert.equal(stowFraction(TD + 100, true, TD, EXIT), 0, "활주·정지 중에도");
    assert.ok(SKID_DEPLOY_LEAD_S > SKID_DEPLOY_S);
    let prev = 2;
    for (let k = 0; k <= 20; k++) {
      const f = stowFraction(TD - SKID_DEPLOY_LEAD_S + (SKID_DEPLOY_S * k) / 20, true, TD, EXIT);
      assert.ok(f <= prev, `단조 감소 ${k}`);
      prev = f;
    }
  });

  it("시각이 성하지 않으면 접힘으로 둔다 — 펼침을 지어내지 않는다", () => {
    assert.equal(stowFraction(Number.NaN, true, TD, EXIT), 1);
  });
});

describe("짧은 비행 — 레일을 떠나기 전엔 펴지 않는다 (v2.02 리뷰)", () => {
  // touchdown_t는 첫 지면 접촉이다 — 발사 직후 추락도 포함한다. 그 20 s 전이 시각 0보다 앞서면, 레일 이탈 시각으로
  // 미루지 않는 한 관 안(문 열리는 전주·레일 주행)에서 스키드가 펴져 바닥을 뚫는다.
  const EXIT = 0.6;
  it("접지가 8 s여도 관 안(시각 0 · 레일 위)에선 접혀 있고, 레일을 떠난 뒤 편다", () => {
    assert.equal(stowFraction(0, true, 8, EXIT), 1);
    assert.equal(stowFraction(EXIT, true, 8, EXIT), 1);
    assert.equal(stowFraction(EXIT + SKID_DEPLOY_S, true, 8, EXIT), 0);
  });

  it("접지 20 s(경계)도 레일 위에선 다 접혀 있다", () => {
    assert.equal(stowFraction(0.3, true, 20, EXIT), 1);
  });

  it("레일 이탈을 모르면 시각 0을 이탈로 본다 — 옛 결과는 접지 시각도 없어 내내 접힘이다", () => {
    assert.equal(stowFraction(0, true, 8, null), 1);
    assert.ok(stowFraction(1, true, 8, null) < 1);
  });
});

describe("railExitTime — 레일 이탈 시각", () => {
  it("phases.launch_exit_t가 먼저, 없으면 on_rail이 처음 거짓인 표본의 시각", () => {
    assert.equal(railExitTime(0.6, [0, 0.5, 1], [true, true, false]), 0.6);
    assert.equal(railExitTime(null, [0, 0.5, 1], [true, true, false]), 1);
    assert.equal(railExitTime(undefined, [0, 0.5, 1], [true, null, false]), 1, "결측은 이탈이 아니다");
  });

  it("둘 다 없으면 null", () => {
    assert.equal(railExitTime(null, [0, 1], undefined), null);
    assert.equal(railExitTime(null, [0, 1], [true, true]), null);
  });
});
