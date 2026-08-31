// 미션 빌더 검증 — 편집 행 → 서버 미션 스펙 (빈 값=off, 조건 인자수, 웨이포인트)
import { test } from "node:test";
import assert from "node:assert/strict";

import { buildModes, buildWaypoints, COND_KINDS, LON_AXES } from "./mission.js";

test("buildModes: 빈 값 → null(축 off), heading path/숫자, next 연결", () => {
  const rows = [
    { name: "climb", speed: "202", lonAxis: "alt", lonValue: "1300", heading: "0",
      exitKind: "alt_ge", exitValue: "1280", next: "wpnav" },
    { name: "wpnav", speed: "140", lonAxis: "alt", lonValue: "path", heading: "path",
      exitKind: "path_done", exitValue: "", next: "descent" },
    { name: "descent", speed: "140", lonAxis: "alt", lonValue: "100", heading: "",
      exitKind: "alt_le", exitValue: "130", next: "mission" },
    { name: "mission", speed: "140", lonAxis: "alt", lonValue: "30", heading: "",
      exitKind: "time_ge", exitValue: "1e9", next: "" },
  ];
  const modes = buildModes(rows);
  assert.equal(modes.length, 4);
  assert.deepEqual(modes[0], {
    name: "climb", speed: 202, alt: 1300, pitch: null, hdot: null, heading: 0,
    exit: ["alt_ge", 1280], next: "wpnav",
  });
  assert.equal(modes[1].alt, "path");
  assert.equal(modes[1].heading, "path");
  assert.deepEqual(modes[1].exit, ["path_done"]); // 0-인자 조건
  assert.equal(modes[2].heading, null); // 빈 = 축 off
  assert.equal(modes[3].next, null);
  assert.deepEqual(modes[3].exit, ["time_ge", 1e9]);
});

test("buildModes: 종방향은 **하나만** 나간다 — 배타가 구조로 보장된다", () => {
  const row = (lonAxis, lonValue) => ({
    name: "m", speed: "100", lonAxis, lonValue, heading: "",
    exitKind: "always", exitValue: "", next: "",
  });
  const alt = buildModes([row("alt", "300")])[0];
  assert.deepEqual([alt.alt, alt.pitch, alt.hdot], [300, null, null]);
  const pit = buildModes([row("pitch", "0.37")])[0];
  assert.deepEqual([pit.alt, pit.pitch, pit.hdot], [null, 0.37, null]);
  const vs = buildModes([row("hdot", "-4.8")])[0];
  assert.deepEqual([vs.alt, vs.pitch, vs.hdot], [null, null, -4.8]);
  // off — 셋 다 null (고도축 PI가 오차 0을 물고 트림 θ를 유지한다)
  const off = buildModes([row("", "")])[0];
  assert.deepEqual([off.alt, off.pitch, off.hdot], [null, null, null]);
});

test('buildModes: "path"는 고도축에서만 — 경로가 내는 것은 세로 프로파일이다', () => {
  const row = (lonAxis) => ({
    name: "m", speed: "", lonAxis, lonValue: "path", heading: "",
    exitKind: "always", exitValue: "", next: "",
  });
  assert.equal(buildModes([row("alt")])[0].alt, "path");
  assert.throws(() => buildModes([row("pitch")]), /고도축에서만/);
  assert.throws(() => buildModes([row("hdot")]), /고도축에서만/);
});

test("buildModes: 모르는 종방향 축은 조용히 off가 되지 않는다", () => {
  assert.throws(() => buildModes([{
    name: "m", speed: "", lonAxis: "gamma", lonValue: "3", heading: "",
    exitKind: "always", exitValue: "", next: "",
  }]), /모르는 종방향 축/);
});

test("LON_AXES: 편집 표의 선택지 — off + 세 축, value는 서버 필드 이름", () => {
  assert.deepEqual(LON_AXES.map((a) => a.value), ["", "alt", "pitch", "hdot"]);
  assert.equal(LON_AXES[0].label, "off");
});

test("buildModes: 이름 없음·비수치 거부", () => {
  assert.throws(() => buildModes([{ name: "", speed: "", lonAxis: "", lonValue: "",
    heading: "", exitKind: "always", exitValue: "", next: "" }]));
  assert.throws(() => buildModes([{ name: "x", speed: "abc", lonAxis: "", lonValue: "",
    heading: "", exitKind: "always", exitValue: "", next: "" }]));
  assert.throws(() => buildModes([{ name: "x", speed: "", lonAxis: "", lonValue: "",
    heading: "", exitKind: "alt_ge", exitValue: "높게", next: "" }]));
});

test("buildModes: 필수 인자 빈 문자열은 0이 아니라 거부 (리뷰 S1 — Number('')===0 함정)", () => {
  // 이탈 조건 값을 비우면 ["alt_ge", 0]이 되어 즉시 이탈하는 무증상 붕괴 — 차단
  assert.throws(() => buildModes([{ name: "x", speed: "", lonAxis: "", lonValue: "",
    heading: "", exitKind: "alt_ge", exitValue: "", next: "" }]));
  assert.throws(() => buildModes([{ name: "x", speed: "", lonAxis: "", lonValue: "",
    heading: "", exitKind: "alt_ge", exitValue: "   ", next: "" }]));
});

test("buildWaypoints: 좌표 빈 문자열 거부 (0 조용 주입 금지)", () => {
  assert.throws(() => buildWaypoints([{ n: "", e: "100" }]));
  assert.throws(() => buildWaypoints([{ n: "100", e: " " }]));
});

test("COND_KINDS: 인자수 테이블 (0-인자 = always·path_done·접지·레일)", () => {
  assert.equal(COND_KINDS.always, 0);
  assert.equal(COND_KINDS.path_done, 0);
  assert.equal(COND_KINDS.alt_ge, 1);
  assert.equal(COND_KINDS.time_ge, 1);
  // 이륙·착륙 (01 §3.3.1) — 접지·레일은 항법에 없는 정보라 시뮬이 주입한다
  assert.equal(COND_KINDS.hdot_le, 1);
  assert.equal(COND_KINDS.hdot_ge, 1);
  assert.equal(COND_KINDS.on_ground, 0);
  assert.equal(COND_KINDS.airborne, 0);
  assert.equal(COND_KINDS.off_rail, 0);
});

test("buildWaypoints: (N,E) 행 → 튜플 배열, 빈 목록 → null", () => {
  assert.deepEqual(
    buildWaypoints([{ n: "8000", e: "0" }, { n: "8000", e: "8000" }]),
    [[8000, 0], [8000, 8000]],
  );
  assert.equal(buildWaypoints([]), null);
  assert.throws(() => buildWaypoints([{ n: "abc", e: "0" }]));
});

test('buildModes: 고도축도 "path"를 받는다 — heading과 같은 규약 (축별 명령 출처)', () => {
  const [m] = buildModes([{
    name: "wpnav", speed: "140", lonAxis: "alt", lonValue: "path", heading: "path",
    exitKind: "path_done", exitValue: "", next: null,
  }]);
  assert.equal(m.alt, "path");
  assert.equal(m.heading, "path");
  // 오타는 조용히 축 off가 되지 않고 던진다 (서버도 같은 말로 거부한다)
  assert.throws(() => buildModes([{
    name: "x", speed: "", lonAxis: "alt", lonValue: "pat", heading: "",
    exitKind: "always", exitValue: "", next: null,
  }]), /x\.고도.*수치가 아님/);
});

test("buildWaypoints: 고도는 전부 채우거나 전부 비우거나 — 섞이면 행 번호를 짚는다", () => {
  assert.deepEqual(buildWaypoints([{ n: "8000", e: "0" }, { n: "8000", e: "8000" }]),
    [[8000, 0], [8000, 8000]]);
  assert.deepEqual(
    buildWaypoints([{ n: "8000", e: "0", d: "1500" }, { n: "8000", e: "8000", d: "900" }]),
    [[8000, 0, 1500], [8000, 8000, 900]]);
  // 섞인 채 보내면 서버가 422로 답하지만 어느 행인지는 안 알려준다 — 여기서 짚는다
  assert.throws(() => buildWaypoints([
    { n: "1", e: "2", d: "100" }, { n: "3", e: "4" }, { n: "5", e: "6", d: "" },
  ]), /비어 있는 행: 2, 3/);
  assert.equal(buildWaypoints([]), null);
  assert.throws(() => buildWaypoints([{ n: "1", e: "2", d: "abc" }]), /wp0\.고도/);
});
