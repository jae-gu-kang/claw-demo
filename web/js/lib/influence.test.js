// 화면 모델 계약 — 특히 "없음"과 "0"을 섞지 않는지.
import { readFileSync } from "node:fs";
import test from "node:test";
import assert from "node:assert/strict";

import {
  KNOB_CLASS, coneOf, diagnoseRequest, edgeVia, fmtDelta, logScale, nodeDetail,
  normalizeDiagnosis, normalizeGraph, pairsFor, paramState, radiusOf, rampColor,
  structuralRequest, sweepRequest,
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

// ── 진단 → 처방 → 스윕 (2·3단) — 요청 빌더와 처방 카드 정규화의 계약 ──────

test("diagnoseRequest: 형상 위임 + result_id — 형상 필드를 재기술하지 않는다", () => {
  const body = diagnoseRequest(
    { withSchedule: false, autopilot: { kp_alt: 0.005 } }, "res-1");
  assert.equal(body.result_id, "res-1");
  assert.equal(body.with_schedule, false);
  assert.deepEqual(body.autopilot, { kp_alt: 0.005 });
  assert.ok(!("cases" in body)); // 진단은 저장된 런이 대상 — 케이스가 없다
});

test("sweepRequest: 처방 knobs·pairs가 그대로 실린다 (부분공간 한정)", () => {
  const body = sweepRequest({}, {
    cases: [{ mach: 0.6, alt: 1000, fuel: 200 }],
    knobs: ["table.pitch.kp"],
    pairs: [["table.pitch.kp", "table.pitch.k_rate"]],
    tSettle: 2, tStep: 4,
    fingerprint: "fp-x",
  });
  assert.deepEqual(body.knobs, ["table.pitch.kp"]);
  assert.deepEqual(body.pairs, [["table.pitch.kp", "table.pitch.k_rate"]]);
  assert.equal(body.t_settle, 2);
  assert.equal(body.t_step, 4);
  assert.equal(body.fingerprint, "fp-x");
  assert.equal(body.cases.length, 1);
});

test("pairsFor: 카드의 joint_with → (대표 knob, 동반 knob) 쌍", () => {
  assert.deepEqual(
    pairsFor({ knobs: ["a"], joint_with: ["b", "c"] }),
    [["a", "b"], ["a", "c"]]);
  assert.deepEqual(pairsFor({ knobs: ["a"] }), []);
  assert.deepEqual(pairsFor({ knobs: [], joint_with: ["b"] }), []); // 대표가 없으면 쌍도 없다
});

test("normalizeDiagnosis: 카드 인덱스 부여 + warn 유무 요약", () => {
  const d = normalizeDiagnosis({
    result_id: "r", fingerprint: "fp",
    metrics: { alt_rms: 1.0 }, thresholds: { sat_frac: 0.05 },
    findings: [
      { rule: "error_split", axis: "alt", severity: "info", verdict: "", evidence: {} },
      { rule: "windup", axis: "alt", severity: "warn", verdict: "", evidence: {} },
    ],
    prescriptions: [{ knobs: ["k"], knob_class: "filter", direction: "decrease",
                      findings: [1], joint_with: [], recheck: [], notes: [] }],
  });
  assert.equal(d.resultId, "r");
  assert.equal(d.prescriptions[0].index, 0);
  assert.equal(d.hasWarn, true);
  const quiet = normalizeDiagnosis({ findings: [], prescriptions: [] });
  assert.equal(quiet.hasWarn, false);
  assert.deepEqual(quiet.warnings, []);
});

test("KNOB_CLASS: 진단 엔진의 처방 클래스 전부에 라벨·잉크가 있다 (드리프트 가드)", () => {
  // 정본(engine/claw/pipeline/diagnose.py)의 클래스 주석 행을 직접 대조 —
  // 엔진이 클래스를 더하면 이 테스트가 즉시 깨진다 (loops.test.js와 같은 규약)
  const src = readFileSync(
    new URL("../../../engine/claw/pipeline/diagnose.py", import.meta.url), "utf8");
  const m = src.match(/knob_class: str  # (.+)/);
  assert.ok(m, "엔진에서 knob_class 주석을 못 찾음");
  const classes = [...m[1].matchAll(/'(\w+)'/g)].map((g) => g[1]);
  assert.ok(classes.length >= 6);
  for (const c of classes) {
    assert.ok(KNOB_CLASS[c]?.label, `KNOB_CLASS에 ${c} 라벨 없음`);
    assert.match(KNOB_CLASS[c].ink, /^#[0-9a-f]{6}$/i);
  }
});

test("edgeVia: 포트·효과·종류를 사람 말로 — 모르는 값은 삼키지 않고 원문", () => {
  assert.equal(edgeVia({ port: "input" }), "입력");
  assert.equal(edgeVia({ port: "gain:kp" }), "게인 kp");
  assert.equal(edgeVia({ port: "enable" }), "인에이블");
  assert.equal(edgeVia({ port: "on_disable:out" }), "비활성 폴백 out");
  assert.equal(edgeVia({ port: "output" }), "출력");
  assert.equal(edgeVia({ kind: "param", effect: "changed" }), "값 주입");
  assert.equal(edgeVia({ kind: "param", effect: "added" }), "노드 생성");
  assert.equal(edgeVia({ kind: "param", effect: "removed" }), "노드 제거");
  assert.equal(edgeVia({ kind: "param", effect: "overridden" }), "덮인 값");
  assert.equal(edgeVia({ kind: "param" }), "값 주입", "effect 누락은 기본 갈래");
  assert.equal(edgeVia({ kind: "param", effect: "미래효과" }), "미래효과",
    "모르는 효과를 「값 주입」으로 뭉개면 틀린 말이 된다");
  assert.equal(edgeVia({ kind: "boundary" }), "법칙 경계");
  assert.equal(edgeVia({ kind: "declared" }), "폐루프 선언");
  assert.equal(edgeVia({ kind: "offgraph" }), "법칙 밖 직행");
  assert.equal(edgeVia({ kind: "ghost" }), "구조 변경 시");
  assert.equal(edgeVia({ port: "미래포트" }), "미래포트", "새 포트가 조용히 사라지면 안 된다");
  assert.equal(edgeVia(null), "");
});

test("nodeDetail: 서버가 실어 준 것부터 — 블록 파라미터 값이 한 줄에 나온다", () => {
  const bands = { ap: { label: "오토파일럿" } };
  assert.equal(nodeDetail({ kind: "metric", desc: "α 여유" }), "α 여유");
  assert.equal(nodeDetail({ kind: "plant", note: "폐루프는 밖" }), "폐루프는 밖");
  assert.equal(
    nodeDetail({ kind: "ir", band: "ap", block: "Saturation",
      params: { lo: -0.35, hi: 0.35 } }, bands),
    "오토파일럿 · 블록 Saturation — lo=-0.350 hi=0.350");
  // 4개째부터는 접는다 — 한 줄 설명이 표가 되면 안 된다
  assert.match(nodeDetail({ kind: "ir", block: "B", params: { a: 1, b: 2, c: 3, d: 4 } }), / …$/);
  // 배열·객체 값은 한 줄에 넣지 않는다
  assert.equal(nodeDetail({ kind: "ir", block: "B", params: { arr: [1, 2] } }), "블록 B");
  // 묶음 라벨이 없으면(IR 그룹) 엔진 그룹 이름 원문
  assert.equal(nodeDetail({ kind: "ir", band: "x", group: "mix", op: "add" }, {}), "mix · 연산 add");
  assert.match(nodeDetail({ kind: "output" }), /법칙 출력/);
  assert.equal(nodeDetail({ kind: "input" }), "법칙 입력");
  assert.equal(nodeDetail(null), "");
});
