/** 드로어 공통 인프라 — open()의 onOpen 통지 계약.
 *
 * 이 계약은 전 뷰가 기대는 불변식이다: 프로그램이 연 패널([열기]→문서, 배치 완료→결과,
 * 목록 자동 열림)도 뷰의 「열린 패널 유지」 모듈 상태(openDrawer 등)에 남아야 탭
 * 재진입에 복원되고, 자동 열림 가드(openDrawer 확인)가 헛돌지 않는다. 한 줄을 지워도
 * 다른 테스트는 전부 초록이라 여기서 핀한다(리뷰 지적).
 */
import test from "node:test";
import assert from "node:assert/strict";

import { installDom } from "./testdom.js";

installDom(); // import보다 먼저 — stage.js가 dom.js el()을 쓴다

const { createDrawers } = await import("./stage.js");

const defs = () => [
  { key: "a", label: "A", group: "g", build: () => [] },
  { key: "b", label: "B", group: "g", build: () => [] },
];

test("open(key)는 onOpen에 실제 열린 키를 알린다 — 칩 클릭 경로와 같은 계약", () => {
  const seen = [];
  const d = createDrawers({ id: "t", defs: defs(), onOpen: (k) => seen.push(k) });
  d.open("b");
  assert.deepEqual(seen, ["b"]);
  assert.equal(d.current(), "b");
  d.open("a"); // 다른 패널로 갈아 끼우기 — 토글 닫힘이 아니라 항상 연다
  assert.deepEqual(seen, ["b", "a"]);
  assert.equal(d.current(), "a");
});

test("onOpen 없이도 open()은 동작한다 — 통지는 선택 규약이다", () => {
  const d = createDrawers({ id: "t2", defs: defs() });
  d.open("a");
  assert.equal(d.current(), "a");
});
