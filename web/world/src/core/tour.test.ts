import { strict as assert } from "node:assert";
import { describe, it } from "node:test";

import {
  readTour, tourMismatch, tourReady, tourShouldEnd, tourStopped, type WorldTour,
} from "./tour.ts";

const T: WorldTour = {
  token: "t1", resultId: "r1", commsId: "c1", speed: 2, voice: true, endT: 104.4,
};

describe("readTour", () => {
  it("형상이 맞는 값만 투어로 읽는다 — 틀리면 투어 아님(null)", () => {
    assert.deepEqual(readTour(T), T);
    assert.equal(readTour(null), null);
    assert.equal(readTour({ ...T, resultId: 7 }), null);
    assert.equal(readTour({ ...T, token: "" }), null);
    // 선택 칸은 없으면 null로 — undefined를 그대로 두면 비교가 조용히 어긋난다
    assert.deepEqual(readTour({ ...T, commsId: undefined, endT: undefined }),
      { ...T, commsId: null, endT: null });
  });

  it("배속이 비정상이면 1로 — 0·음수·NaN 배속은 재생이 흐르지 않는다", () => {
    assert.equal(readTour({ ...T, speed: 0 })?.speed, 1);
    assert.equal(readTour({ ...T, speed: Number.NaN })?.speed, 1);
  });
});

describe("tourReady", () => {
  const ok = { chosen: "r1", shownId: "r1", playable: true, commsKey: "c1" };

  it("투어 런이 선택·표시·재생 가능하고 대본이 앉았을 때만 시작한다", () => {
    assert.equal(tourReady(T, ok), true);
    assert.equal(tourReady(T, { ...ok, shownId: "r0" }), false); // 옛 장면이 아직 떠 있다
    assert.equal(tourReady(T, { ...ok, playable: false }), false);
    assert.equal(tourReady(T, { ...ok, commsKey: null }), false); // 대본이 아직 안 앉았다
  });

  it("대본 없는 투어(교신 실패)는 대본을 기다리지 않는다", () => {
    assert.equal(tourReady({ ...T, commsId: null }, { ...ok, commsKey: null }), true);
  });
});

describe("tourMismatch", () => {
  it("목록이 아직 없으면 판단하지 않는다", () => {
    assert.equal(tourMismatch(T, { chosen: null, resultIds: [] }), null);
  });

  it("투어 런이 목록에 없으면 사유 — 최신으로 조용히 폴백한 화면을 투어로 틀지 않는다", () => {
    assert.match(tourMismatch(T, { chosen: "r9", resultIds: ["r9", "r8"] }) ?? "", /목록에 없/);
  });

  it("사용자가 다른 런을 고르면 사유, 투어 런이면 null", () => {
    assert.match(tourMismatch(T, { chosen: "r2", resultIds: ["r1", "r2"] }) ?? "", /다른 결과/);
    assert.equal(tourMismatch(T, { chosen: "r1", resultIds: ["r1", "r2"] }), null);
  });
});

describe("tourShouldEnd", () => {
  it("정지 + 여유에 닿으면 끝 — 끝 시각이 없으면 데이터 끝까지", () => {
    assert.equal(tourShouldEnd(T, 104.3), false);
    assert.equal(tourShouldEnd(T, 104.4), true);
    assert.equal(tourShouldEnd({ ...T, endT: null }, 999), false);
    assert.equal(tourShouldEnd(T, null), false);
  });
});

describe("tourStopped", () => {
  it("조율자가 키를 거두면 멈춤 — [중단]·실패가 기체와 목소리를 남기지 않는다", () => {
    assert.equal(tourStopped(T, T), false);
    assert.equal(tourStopped(null, T), true);
    assert.equal(tourStopped(undefined, T), true);
  });

  it("토큰이 바뀌면 지금 도는 재생은 지난 투어의 것이다 — 멈춘다", () => {
    assert.equal(tourStopped({ ...T, token: "t2" }, T), true);
  });

  it("형상이 깨진 값도 멈춤으로 본다 — 판정 불가를 '계속'으로 눙치지 않는다", () => {
    assert.equal(tourStopped({ token: "t1" }, T), true); // resultId가 없다 — 투어가 아니다
  });
});
