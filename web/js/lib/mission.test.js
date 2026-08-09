// 미션 빌더 검증 — 편집 행 → 서버 미션 스펙 (빈 값=off, 조건 인자수, 웨이포인트)
import { test } from "node:test";
import assert from "node:assert/strict";

import { buildModes, buildWaypoints, COND_KINDS } from "./mission.js";

test("buildModes: 빈 값 → null(축 off), heading path/숫자, next 연결", () => {
  const rows = [
    { name: "climb", speed: "202", alt: "1300", heading: "0",
      exitKind: "alt_ge", exitValue: "1280", next: "wpnav" },
    { name: "wpnav", speed: "140", alt: "1300", heading: "path",
      exitKind: "path_done", exitValue: "", next: "descent" },
    { name: "descent", speed: "140", alt: "100", heading: "",
      exitKind: "alt_le", exitValue: "130", next: "mission" },
    { name: "mission", speed: "140", alt: "30", heading: "",
      exitKind: "time_ge", exitValue: "1e9", next: "" },
  ];
  const modes = buildModes(rows);
  assert.equal(modes.length, 4);
  assert.deepEqual(modes[0], {
    name: "climb", speed: 202, alt: 1300, heading: 0,
    exit: ["alt_ge", 1280], next: "wpnav",
  });
  assert.equal(modes[1].heading, "path");
  assert.deepEqual(modes[1].exit, ["path_done"]); // 0-인자 조건
  assert.equal(modes[2].heading, null); // 빈 = 축 off
  assert.equal(modes[3].next, null);
  assert.deepEqual(modes[3].exit, ["time_ge", 1e9]);
});

test("buildModes: 이름 없음·비수치 거부", () => {
  assert.throws(() => buildModes([{ name: "", speed: "", alt: "", heading: "",
    exitKind: "always", exitValue: "", next: "" }]));
  assert.throws(() => buildModes([{ name: "x", speed: "abc", alt: "", heading: "",
    exitKind: "always", exitValue: "", next: "" }]));
  assert.throws(() => buildModes([{ name: "x", speed: "", alt: "", heading: "",
    exitKind: "alt_ge", exitValue: "높게", next: "" }]));
});

test("buildModes: 필수 인자 빈 문자열은 0이 아니라 거부 (리뷰 S1 — Number('')===0 함정)", () => {
  // 이탈 조건 값을 비우면 ["alt_ge", 0]이 되어 즉시 이탈하는 무증상 붕괴 — 차단
  assert.throws(() => buildModes([{ name: "x", speed: "", alt: "", heading: "",
    exitKind: "alt_ge", exitValue: "", next: "" }]));
  assert.throws(() => buildModes([{ name: "x", speed: "", alt: "", heading: "",
    exitKind: "alt_ge", exitValue: "   ", next: "" }]));
});

test("buildWaypoints: 좌표 빈 문자열 거부 (0 조용 주입 금지)", () => {
  assert.throws(() => buildWaypoints([{ n: "", e: "100" }]));
  assert.throws(() => buildWaypoints([{ n: "100", e: " " }]));
});

test("COND_KINDS: 인자수 테이블 (0-인자 = always·path_done)", () => {
  assert.equal(COND_KINDS.always, 0);
  assert.equal(COND_KINDS.path_done, 0);
  assert.equal(COND_KINDS.alt_ge, 1);
  assert.equal(COND_KINDS.time_ge, 1);
});

test("buildWaypoints: (N,E) 행 → 튜플 배열, 빈 목록 → null", () => {
  assert.deepEqual(
    buildWaypoints([{ n: "8000", e: "0" }, { n: "8000", e: "8000" }]),
    [[8000, 0], [8000, 8000]],
  );
  assert.equal(buildWaypoints([]), null);
  assert.throws(() => buildWaypoints([{ n: "abc", e: "0" }]));
});
