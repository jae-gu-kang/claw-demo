// 화면 모델 계약 — 특히 "없음"과 "0"을 섞지 않는지.
import test from "node:test";
import assert from "node:assert/strict";

import {
  coneOf, fmtDelta, logScale, normalizeGraph, paramState, radiusOf,
  rampColor, structuralRequest,
} from "./influence.js";

const payload = {
  fingerprint: "abc", dt: 0.01, control_hz: 100, probe_rel: 0.01,
  graph: { name: "fcl", n_nodes: 3 }, bands: {}, metrics: [],
  warnings: ["주의"], elapsed_ms: 12,
  nodes: [
    { id: "in:mach", kind: "input", band: "io" },
    { id: "a", kind: "ir", band: "ap", n_reach: 3 },
    { id: "b", kind: "ir", band: "scas", n_reach: 1 },
    { id: "out:elevon_l", kind: "output", band: "io" },
    { id: "sys:plant", kind: "plant", band: "io" },
    { id: "param:P", kind: "param", band: "ap", in_law: true, seeds: ["a"],
      reach: ["a", "b"], outputs: ["elevon_l"], added: [], overridden: [],
      structural: false, inert: false, error: null },
    { id: "param:N", kind: "param", band: "nav", in_law: false, seeds: [], reach: [],
      outputs: [], added: [], overridden: [], structural: false, inert: false, error: null },
  ],
  edges: [
    { src: "in:mach", dst: "a", kind: "ir" },
    { src: "a", dst: "b", kind: "ir" },
    { src: "b", dst: "out:elevon_l", kind: "ir" },
    { src: "param:P", dst: "a", kind: "param" },
    { src: "param:N", dst: "sys:plant", kind: "offgraph" },
  ],
};

test("파라미터 상태 다섯 가지를 구분한다 — 뭉뚱그리면 화면의 값어치가 사라진다", () => {
  const base = { in_law: true, inert: false, overridden: [], structural: false, error: null };
  assert.equal(paramState(base), "live");
  assert.equal(paramState({ ...base, structural: true }), "structural");
  assert.equal(paramState({ ...base, overridden: ["x"] }), "overridden");
  assert.equal(paramState({ ...base, inert: true }), "inert");
  assert.equal(paramState({ ...base, in_law: false }), "offgraph");
  assert.equal(paramState({ ...base, error: "범위" }), "error");
});

test("우선순위: 섭동 불가 > 법칙 밖 > 미방출 > 덮임 > 구조 변경", () => {
  assert.equal(paramState({ in_law: false, inert: true, error: "e" }), "error");
  assert.equal(paramState({ in_law: false, inert: true }), "offgraph");
  assert.equal(paramState({ in_law: true, inert: true, overridden: ["x"] }), "inert");
});

test("normalizeGraph는 파라미터에만 state를 붙인다", () => {
  const m = normalizeGraph(payload);
  assert.equal(m.byId.get("param:P").state, "live");
  assert.equal(m.byId.get("param:N").state, "offgraph");
  assert.equal(m.byId.get("a").state, undefined);
  assert.equal(m.params.length, 2);
  assert.deepEqual(m.warnings, ["주의"]);
});

test("원뿔은 서버가 준 reach를 쓴다 — 같은 답을 두 곳에서 정의하지 않는다", () => {
  const m = normalizeGraph(payload);
  const c = coneOf(m, "param:P");
  assert.ok(c.nodes.has("a") && c.nodes.has("b") && c.nodes.has("out:elevon_l"));
  assert.ok(!c.nodes.has("in:mach"), "상류는 원뿔이 아니다");
  assert.deepEqual([...c.seeds], ["a"]);
  assert.ok(c.edges.has(3), "파라미터→씨앗 간선이 원뿔에 든다");
  assert.ok(c.edges.has(1), "원뿔 안에 완전히 들어가는 간선만");
  assert.ok(!c.edges.has(0), "상류 간선은 제외");
});

test("법칙 밖 파라미터의 원뿔은 기체까지만 — 비어 있지 않다", () => {
  const c = coneOf(normalizeGraph(payload), "param:N");
  assert.ok(c.nodes.has("sys:plant"));
  assert.equal(c.seeds.size, 0);
});

test("모르는 id는 빈 원뿔 — 던지지 않는다", () => {
  const c = coneOf(normalizeGraph(payload), "param:없음");
  assert.equal(c.nodes.size, 0);
});

test("null은 0이 아니라 「—」", () => {
  assert.equal(fmtDelta(null), "—");
  assert.equal(fmtDelta(undefined), "—");
  assert.equal(fmtDelta(NaN), "—");
  assert.equal(fmtDelta(0), "0");
  assert.notEqual(fmtDelta(null), fmtDelta(0));
});

test("로그 스케일이 폭주값을 눌러 준다 — 실측 341%가 화면을 먹지 않게", () => {
  assert.equal(logScale(0), 0);
  assert.equal(logScale(-1), 0);
  assert.ok(logScale(3.41) === 1, "상한 클램프");
  assert.ok(logScale(0.15) < 1 && logScale(0.15) > logScale(0.001));
  // 선형이면 341%가 15%의 22배지만 로그로는 2배 미만이어야 한다
  assert.ok(logScale(3.41) / logScale(0.15) < 2);
});

test("램프는 양 끝에서 안정적이고 범위 밖을 클램프한다", () => {
  assert.equal(rampColor(-5), rampColor(0));
  assert.equal(rampColor(9), rampColor(1));
  assert.match(rampColor(0.5, 0.3), /^rgba\(\d+, \d+, \d+, 0\.3\)$/);
});

test("반지름은 도달 개수에 단조 증가", () => {
  assert.ok(radiusOf({ kind: "ir", n_reach: 40 }) > radiusOf({ kind: "ir", n_reach: 2 }));
  assert.ok(Number.isFinite(radiusOf({ kind: "ir" })));
});

test("요청은 사용자가 정한 것만 싣는다 (02 §5.5 — 엔진 기본값 재기술 금지)", () => {
  assert.deepEqual(structuralRequest({}), {});
  assert.deepEqual(structuralRequest({ autopilot: {} }), {}, "빈 dict는 '안 정했다'");
  assert.deepEqual(
    structuralRequest({ withSchedule: false, scas: { pitch: { kp: -2 } }, probeRel: 0.05 }),
    { with_schedule: false, scas: { pitch: { kp: -2 } }, probe_rel: 0.05 },
  );
});

test("출력에 도달하면 기체·지표까지 원뿔에 든다 — 끊으면 '지표는 영향 없음'으로 읽힌다", () => {
  const m = normalizeGraph(payload);
  const c = coneOf(m, "param:P");
  assert.ok(c.nodes.has("sys:plant"), "타면이 움직이면 기체도 움직인다");
});

test("출력에 도달하지 못하는 파라미터는 기체까지 가지 않는다", () => {
  const dead = {
    ...payload,
    nodes: [...payload.nodes, {
      id: "param:D", kind: "param", band: "ap", in_law: true, seeds: [], reach: [],
      outputs: [], added: [], overridden: [], structural: false, inert: true, error: null,
    }],
  };
  const c = coneOf(normalizeGraph(dead), "param:D");
  assert.ok(!c.nodes.has("sys:plant"), "그래프에 없는 상수는 아무 데도 못 간다");
});
