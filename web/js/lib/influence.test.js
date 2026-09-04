// 화면 모델 계약 — 특히 "없음"과 "0"을 섞지 않는지.
import { readFileSync } from "node:fs";
import test from "node:test";
import assert from "node:assert/strict";

import {
  KNOB_CLASS, byImpact, columnFormat, coneOf, diagnoseRequest, edgeVia, fmtChange,
  fmtDelta, fmtPair, fmtPercent, fmtSigned, impactRank, logScale, pairDigits,
  nodeDetail, normalizeDiagnosis, normalizeGraph, openloopWorst, pairsFor,
  paramState, probeTransition, radiusOf, rampColor, relOf, relReadable, fmtRel,
  scanRequest, scanSummary, structuralRequest, sweepCases, sweepKnobs, sweepRequest,
  trendInk, trendMatrix, worstTransitions,
  BAD_INK, GOOD_INK, SKIN, TREND_LABEL, TREND_MARK, WARN_INK,
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

test("scanRequest: 케이스 격자만 — knobs·pairs가 없는 것이 3단 A의 정의다", () => {
  const body = scanRequest({ withSchedule: false }, {
    cases: [{ name: "c1", mach: 0.5, alt: 1000, fuel: 200 }],
    tSettle: 2, tStep: 4, fingerprint: "fp-a",
  });
  assert.equal(body.cases.length, 1);
  assert.equal(body.t_settle, 2);
  assert.equal(body.t_step, 4);
  assert.equal(body.fingerprint, "fp-a");
  assert.equal(body.with_schedule, false); // 형상은 structuralRequest 위임
  assert.ok(!("knobs" in body) && !("pairs" in body));
});

test("scanSummary: 판정 나쁜 순 정렬 + 결함 케이스 합집합", () => {
  const sum = scanSummary({
    grid: {
      local_frac: 1 / 3,
      metrics: {
        alt_rms: { verdict: "ok", knob_class: null, threshold: 2, n_bad: 0,
          n_cases: 3, bad_frac: 0, bad_cases: [] },
        hdg_rms: { verdict: "global", knob_class: "loop_gain", threshold: 0.05,
          n_bad: 2, n_cases: 3, bad_frac: 2 / 3, bad_cases: ["c1", "c2"] },
        spd_rms: { verdict: "local", knob_class: "schedule", threshold: 1.5,
          n_bad: 1, n_cases: 3, bad_frac: 1 / 3, bad_cases: ["c2"] },
      },
    },
  });
  assert.deepEqual(sum.verdicts.map((v) => v.metric),
    ["hdg_rms", "spd_rms", "alt_rms"]);
  assert.deepEqual(sum.badCaseNames, ["c1", "c2"]); // 합집합 — 중복 없음
  assert.equal(sum.localFrac, 1 / 3);
  assert.equal(sum.verdicts[0].knobClass, "loop_gain");
});

test("scanSummary: 발산으로 잘린 케이스도 3단 B 대상 — 판정 제외가 곧 면제는 아니다", () => {
  const sum = scanSummary({
    rows: [{ case: "c1" }, { case: "c2", aborted: "diverged" },
           { case: "c3", aborted: null }],
    grid: { local_frac: 1 / 3, metrics: { alt_rms: {
      verdict: "local", knob_class: "schedule", threshold: 2, n_bad: 1,
      n_cases: 2, bad_frac: 0.5, bad_cases: ["c1"] } } },
  });
  assert.deepEqual(sum.abortedCases, ["c2"]);
  assert.deepEqual(sum.badCaseNames, ["c1", "c2"]); // 잘린 c2가 빠지면 안 된다
  // 판정이 하나도 없어도(전부 발산) 잘린 케이스는 대상으로 남는다
  const allAborted = scanSummary({
    rows: [{ case: "c1", aborted: "diverged" }], grid: { metrics: {} },
  });
  assert.deepEqual(allAborted.badCaseNames, ["c1"]);
  assert.deepEqual(allAborted.verdicts, []);
});

test("sweepCases: 스캔 전·결함 없음은 격자 전체, 결함 있으면 체크된 것만", () => {
  const grid = [{ name: "c1" }, { name: "c2" }, { name: "c3" }];
  const withBad = (bad) => ({
    grid: { local_frac: 1 / 3, metrics: { alt_rms: {
      verdict: bad.length ? "global" : "ok", knob_class: null, threshold: 1,
      n_bad: bad.length, n_cases: 3, bad_frac: bad.length / 3, bad_cases: bad } } },
  });
  assert.deepEqual(sweepCases(grid, null), grid);               // 스캔 전
  assert.deepEqual(sweepCases(grid, { result: withBad([]) }), grid); // 전 케이스 정상
  assert.deepEqual(
    sweepCases(grid, { result: withBad(["c1", "c3"]), selected: new Set(["c1"]) }),
    [{ name: "c1" }]);
});

test("sweepCases: 전부 해제·격자 어긋남은 던진다 — 조용히 일부만 돌지 않는다", () => {
  const grid = [{ name: "c1" }, { name: "c2" }];
  const scan = (sel) => ({
    result: { grid: { local_frac: 1 / 3, metrics: { alt_rms: {
      verdict: "global", knob_class: "loop_gain", threshold: 1, n_bad: 2,
      n_cases: 2, bad_frac: 1, bad_cases: ["c1", "c2"] } } } },
    selected: sel,
  });
  assert.throws(() => sweepCases(grid, scan(new Set())), /전부 해제/);
  // 선택 2건 중 1건만 현 격자에 남은 경우 — 남은 것만 조용히 돌리면 안 된다
  assert.throws(
    () => sweepCases(grid, scan(new Set(["c1", "c9"]))),
    /c9/);
});

test("worstTransitions: 런별 |Δ| 최대와 그 케이스 — base와 null은 세지 않는다", () => {
  const w = worstTransitions([
    { label: "base", case: "c1", metrics: { a: 1, b: 2 }, delta: null },
    { label: "base", case: "c2", metrics: { a: 10, b: 20 }, delta: null },
    { label: "k@+0.1", case: "c1", metrics: { a: 0.5 }, delta: { a: -0.5, b: null } },
    { label: "k@+0.1", case: "c2", metrics: { a: 10.2, b: 23 }, delta: { a: 0.2, b: 3 } },
  ]);
  assert.deepEqual(w["k@+0.1"].a, // |−0.5| > |0.2|
    { delta: -0.5, case: "c1", from: 1, to: 0.5, rel: -0.5 });
  assert.deepEqual(w["k@+0.1"].b, // null은 후보가 아니다
    { delta: 3, case: "c2", from: 20, to: 23, rel: 0.15 });
  assert.ok(!("base" in w));
});

test("worstTransitions: 기준값은 **같은 케이스**의 base 런에서 온다", () => {
  // 케이스를 섞어 잡으면 "12.4 → 11.1"이 서로 다른 비행 조건의 두 수가 된다 —
  // 화면이 가장 그럴듯하게 거짓말하는 자리라 케이스 짝짓기를 못박는다
  const w = worstTransitions([
    { label: "base", case: "저속", metrics: { alt_rms: 100 }, delta: null },
    { label: "base", case: "고속", metrics: { alt_rms: 1 }, delta: null },
    { label: "k@+0.1", case: "고속", metrics: { alt_rms: 1.5 }, delta: { alt_rms: 0.5 } },
  ]);
  assert.equal(w["k@+0.1"].alt_rms.from, 1);   // 100(저속의 기준)이 아니다
  assert.equal(w["k@+0.1"].alt_rms.rel, 0.5);
});

test("worstTransitions: base 런이 없는 케이스도 Δ는 남는다 — from만 없음", () => {
  // 취소로 base가 잘린 케이스. Δ는 서버가 같은 케이스 base 대비로 이미 계산했으므로
  // 유효하다 — 요약에서 통째로 빼면 "영향 없음"으로 읽힌다
  const w = worstTransitions([
    { label: "k@+0.1", case: "c1", metrics: { a: 2 }, delta: { a: 0.4 } },
  ]);
  assert.deepEqual(w["k@+0.1"].a, { delta: 0.4, case: "c1", from: null, to: 2, rel: null });
});

test("fmtPair: 미세 지수값이 같은 표기로 뭉개지지 않는다 — fmtDelta로는 죽는 자리", () => {
  // kp_alt 실측값. fmtDelta는 1e-3 미만을 toExponential(1)로 찍어 둘 다 "4.0e-4"였다 —
  // 판독대가 "4.0e−4 → 4.0e−4"라고, 즉 "안 변했다"고 말하던 화면
  assert.equal(fmtDelta(4.0e-4), fmtDelta(4.04e-4), "회귀의 전제: fmtDelta로는 구분이 없다");
  const [a, b] = fmtPair(4.0e-4, 4.04e-4);
  assert.notEqual(a, b, "두 표기가 같으면 판독대가 거짓말한다");
  assert.deepEqual([a, b], ["4.00e-4", "4.04e-4"]);
  // 표기 방식은 둘이 같아야 크기 비교가 된다 — 한쪽만 지수로 찍히면 안 된다
  assert.ok(a.includes("e") === b.includes("e"));
  // 자릿수가 넉넉한 자리는 늘리지 않는다 (3자리에서 이미 갈린다)
  assert.deepEqual(fmtPair(100, 101), ["100", "101"]);
});

test("fmtPair: 3자리로 안 갈리면 갈릴 때까지 늘린다 — 스윕 Δ는 3자리보다 작을 수 있다", () => {
  // 12.3456 vs 12.3459 — 3·4·5자리 전부 같고 6자리에서 처음 갈린다.
  // 고정 자릿수 구현은 여기서 "12.3 → 12.3"을 찍는다
  for (const d of [3, 4, 5]) {
    assert.equal((12.3456).toPrecision(d), (12.3459).toPrecision(d),
      `전제: ${d}자리로는 구분이 없다`);
  }
  assert.deepEqual(fmtPair(12.3456, 12.3459), ["12.3456", "12.3459"]);
});

test("columnFormat: 한 열은 가장 촘촘한 전이에 맞춘다 — 같은 기준값이 다르게 찍히지 않게", () => {
  // 라이브에서 나온 회귀: 같은 base 런의 40.847이 한 열 안에서 40.8·40.847·40.85로
  // 세 번 다르게 찍혀 다른 수처럼 읽혔다
  const col = [[40.847, 40.853], [40.847, 40.85], [40.847, 40.84]];
  const f = columnFormat(col);
  const lefts = new Set(col.map(([a, b]) => fmtPair(a, b, f)[0]));
  assert.equal(lefts.size, 1, `같은 기준값은 한 열에서 한 표기: ${[...lefts]}`);
  // 그러면서도 가장 촘촘한 행이 뭉개지지 않아야 한다
  for (const [a, b] of col) {
    const [x, y] = fmtPair(a, b, f);
    assert.notEqual(x, y, `${a} → ${b}가 뭉개졌다`);
  }
  assert.deepEqual(columnFormat([]), { digits: 3, expo: false });          // 셀 것 없음
  assert.deepEqual(columnFormat([[null, 3]]), { digits: 3, expo: false }); // 미계측
  // 행별 최소의 **최댓값**이면 안 된다: 40.847→40.853은 3자리(40.8/40.9)에서 갈리지만
  // 4자리에서 둘 다 40.85로 새로 뭉개진다. 이 열의 답은 5자리다
  assert.equal(pairDigits(40.847, 40.853), 3);
  assert.equal(pairDigits(40.847, 40.84), 4);
  assert.equal(f.digits, 5, "행별 최댓값(4)을 쓰면 첫 행이 뭉개진다");
  // 정말 같은 값인 행은 탐색을 막지 않는다 (섭동이 범위에 클립된 자리)
  assert.equal(columnFormat([[1.5, 1.5], [2.0, 2.1]]).digits, 3);
});

test("columnFormat: 어느 자릿수로도 못 갈리는 행이 열 전체를 끌어올리지 않는다", () => {
  // 리뷰가 잡은 것: 차이가 7자리 밑인 행 하나가 splits()를 영원히 막아 열 전체가
  // 7자리로 간다. 정작 그 행은 7자리로도 안 갈리므로 아무도 못 얻는 정밀도를 위해
  // 나머지가 전부 거짓 정밀도를 뒤집어썼다
  const unsplittable = [2.2938472847, 2.2938472851];
  assert.equal(pairDigits(...unsplittable), 7, "전제: 7자리로도 못 갈린다");
  const f = columnFormat([unsplittable, [40.847, 40.853]]);
  assert.equal(f.digits, 3, "못 갈리는 행은 탐색에서 빠진다");
  assert.deepEqual(fmtPair(40.847, 40.853, f), ["40.8", "40.9"]);
});

test("columnFormat: 표기(지수/소수)도 열마다 하나 — 같은 수가 두 모습으로 찍히지 않게", () => {
  // 리뷰가 잡은 것: 자릿수는 통일했는데 지수/소수 결정이 행마다여서, 같은 base 런의
  // 0.00105가 한 행에서는 1.05e-3, 기준 행에서는 0.00105로 찍혔다
  const col = [[0.00105, 0.00098], [0.0020, 0.0021]];
  const f = columnFormat(col);
  assert.equal(f.expo, true, "열에 1e-3 미만 값이 있으면 열 전체가 지수 표기다");
  const shapes = new Set(col.flatMap(([a, b]) => fmtPair(a, b, f)).map((s) => s.includes("e")));
  assert.equal(shapes.size, 1, "한 열 안에서 표기가 갈리면 크기 비교가 안 된다");
  // 기준 행이 찍는 같은 0.00105도 같은 모습이어야 한다
  assert.equal(fmtPair(0.00105, 0.00105, f)[0], fmtPair(0.00105, 0.00098, f)[0]);
});

test("fmtPair: 정말 같은 값이면 같은 문자열 — 없는 차이를 만들지 않는다", () => {
  // 섭동이 범위에 클립돼 기준과 같아진 자리. 7자리까지 가도 같으면 같은 것이다
  assert.deepEqual(fmtPair(0.35, 0.35), ["0.35", "0.35"]);
  // 미계측은 fmtDelta 규약 그대로 (0이 아니라 —)
  assert.deepEqual(fmtPair(null, 3), ["—", "3.00"]);
  assert.deepEqual(fmtPair(1, "inf"), ["1.00", "∞"]);
});

test("fmtChange: 「+0.0%」로 반올림될 변화는 절대 Δ로 말한다", () => {
  assert.equal(fmtChange(0.053, 0.0232, "m/s"), "+2.3%");
  assert.equal(fmtChange(-0.053, -0.0232, "m/s"), "−2.3%");
  // 라이브 회귀: 0.16969 → 0.16972는 값이 눈에 띄게 움직였는데 비율은 "+0.0%"였다
  const rel = (0.16972 - 0.16969) / 0.16969;
  assert.ok(fmtPercent(rel) === "0.0%", "회귀의 전제: 비율이 0.0%로 반올림된다");
  assert.ok(!fmtChange(3e-5, rel, "rad").includes("%"), "그때는 비율로 말하지 않는다");
  assert.equal(fmtChange(3e-5, rel, "rad"), "+3.0e-5 rad");
  // 기준이 0이라 비율이 아예 없는 자리도 절대 Δ (리미터 작동률이 0에서 벗어난 자리)
  assert.equal(fmtChange(0.04, null, ""), "+0.0400");
  assert.equal(fmtChange(0, null, ""), "0");
});

test("relReadable: 퍼센트를 손으로 찍는 자리가 같은 문턱을 쓰게 — 0에 「−」가 붙지 않게", () => {
  // 0은 방향이 없다 — `rel > 0 ? "+" : "−"`를 그냥 쓰면 「−0.0%」가 찍힌다
  assert.equal(relReadable(0), false);
  assert.equal(relReadable(null), false);
  assert.equal(relReadable(0.0009), false);   // 「+0.0%」로 뭉개지는 구간
  assert.equal(relReadable(-0.0232), true);
  assert.equal(fmtRel(0.0232), "+2.3%");
  assert.equal(fmtRel(-0.0232), "−2.3%");     // U+2212
  // fmtChange가 갈아타는 문턱과 **같은 하나**여야 한다 (두 곳이 갈리면 안 된다)
  for (const r of [0, 0.0005, 0.0009, 0.001, 0.02, -0.0009, -0.001]) {
    assert.equal(fmtChange(1, r, "").includes("%"), relReadable(r), `rel=${r}`);
  }
});

test("impactRank: 안 움직인 지표가 움직인 지표보다 앞에 서지 않는다", () => {
  // 라이브 회귀: relOf가 null(기준 0 → 0)을 내는데 Math.abs(null ?? -1)이 1이라,
  // 0→0인 엔벨로프 이탈·타면 포화·리미터 작동이 상위 3줄을 차지하고 실제로 움직인
  // 속도 RMS(+2.3%)가 「외 지표 4개」로 접혀 들어갔다
  const dead = { from: 0, to: 0, delta: 0, rel: null };
  const moved = { from: 2.29, to: 2.34, delta: 0.053, rel: 0.0232 };
  assert.ok(impactRank(moved) > impactRank(dead), "움직인 쪽이 위다");
  assert.equal(impactRank(dead), -1);
  // 기준 0에서 벗어난 것은 질적 변화라 맨 앞 — 리미터가 처음 걸리기 시작한 자리
  const appeared = { from: 0, to: 0.04, delta: 0.04, rel: null };
  assert.ok(impactRank(appeared) > impactRank(moved));
  assert.equal(impactRank(null), -1);
  // 정렬 결과로도 확인 (뷰가 하는 그대로)
  assert.deepEqual([dead, moved, appeared].sort(byImpact), [appeared, moved, dead]);
});

test("byImpact: 0에서 벗어난 지표가 둘이어도 비교자가 NaN을 내지 않는다", () => {
  // 리뷰가 잡은 것: impactRank를 뺄셈으로 쓰면 Infinity − Infinity = NaN이라
  // 비교자 계약이 깨진다(엔진마다 다르게 처리한다)
  const a = { from: 0, to: 0.04, delta: 0.04, rel: null };
  const b = { from: 0, to: 0.09, delta: 0.09, rel: null };
  assert.ok(Number.isNaN(impactRank(a) - impactRank(b)), "전제: 뺄셈은 NaN이다");
  assert.equal(byImpact(a, b), 0);
  assert.ok(Number.isFinite(byImpact(a, b)));
  // 순서 자체는 그대로 (큰 것이 앞)
  const dead = { from: 0, to: 0, delta: 0, rel: null };
  const moved = { from: 2, to: 2.1, delta: 0.1, rel: 0.05 };
  assert.deepEqual([dead, a, moved].sort(byImpact), [a, moved, dead]);
});

test("relOf: 기준이 0이면 비율이 **없다** — ∞도 0도 거짓말이다", () => {
  assert.equal(relOf(2, 3), 0.5);
  assert.equal(relOf(-2, -3), -0.5); // 분모는 |from| — 부호는 방향이 갖는다
  assert.equal(relOf(0, 0.01), null); // k_diff_thr·ki_hdg가 실제로 0인 자리
  assert.equal(relOf(1, undefined), null);
});

test("fmtSigned: +를 붙이고 음수는 U+2212 — 0과 미계측은 부호가 없다", () => {
  assert.equal(fmtSigned(1.25), "+1.25");
  assert.equal(fmtSigned(-1.25), "−1.25");
  assert.ok(!fmtSigned(-1.25).includes("-"), "하이픈이 남으면 글머리표로 읽힌다");
  assert.equal(fmtSigned(0), "0");
  assert.equal(fmtSigned(null), "—");
});

test("probeTransition: 섭동을 못 만든 자리는 전이가 **없다**", () => {
  assert.deepEqual(probeTransition({ value: 1, probe_to: 1.01, unit: "s" }),
    { from: 1, to: 1.01, delta: 1.01 - 1, rel: 1.01 - 1, unit: "s" });
  // 무단위 센티널 "-"는 단위가 아니다 (엔진 규약)
  assert.equal(probeTransition({ value: 1, probe_to: 1.01, unit: "-" }).unit, "");
  assert.equal(probeTransition({ value: 1, probe_to: null }), null);
  assert.equal(probeTransition(null), null);
});

test("openloopWorst: (knob, 루프)별 |ΔPM|·|ΔGM| 최악 — delta 없는 항목 제외", () => {
  const rows = openloopWorst({
    k1: {
      status: "ok", value: 0.8, probe_to: 0.808,
      loops: {
        pitch_rate: {
          c1: { base: { pm_deg: 48.3, gm_db: 9 }, perturbed: { pm_deg: 46.3, gm_db: 9.5 },
                delta: { pm_deg: -2, gm_db: 0.5 } },
          c2: { base: { pm_deg: 50, gm_db: 12 }, perturbed: { pm_deg: 51, gm_db: 9 },
                delta: { pm_deg: 1, gm_db: -3 } },
          c3: { note: "no_loop" }, // delta 없음 — 케이스 수에 안 들어간다
        },
      },
    },
    k2: { status: "overridden" }, // ok가 아니면 요약에 없다 (상세 표가 사유를 든다)
  }, ["k1", "k2"]);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].nCases, 2);
  // 마진 전이는 **그 Δ가 나온 케이스의** base·perturbed다 — PM 최악은 c1, GM 최악은 c2라
  // 두 줄의 케이스가 갈린다. 한쪽 케이스로 뭉뚱그리면 없는 조합을 화면에 세운다
  assert.deepEqual(rows[0].pm, { value: -2, case: "c1", from: 48.3, to: 46.3 });
  assert.deepEqual(rows[0].gm, { value: -3, case: "c2", from: 12, to: 9 });
  // 손잡이 자신의 전이 — "무엇을 얼마로 바꿨을 때"가 빠지면 마진 전이가 뜻을 잃는다
  assert.equal(rows[0].knobFrom, 0.8);
  assert.equal(rows[0].knobTo, 0.808);
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

// ── 구간 경향 (3단 C) ──────────────────────────────────────────────────────

const close = (a, b) => Math.abs(a - b) < 1e-9;

/** 스윕 런 한 행 — 서버 저장본(routes/influence.py)의 모양 그대로. */
const row = (caseName, label, knobValue, metrics, extra = {}) => ({
  case: caseName, label,
  role: label === "base" ? "base" : "single",
  overrides: label === "base" ? {} : { k: knobValue },
  metrics, aborted: false, ...extra,
});

/** 한 구간의 다섯 점 — 기준 뒤 −20·−10·+10·+20% (스팬 순이 아니라 실행 순으로 싣는다). */
const caseRows = (name, alt, spd, lim) => [
  row(name, "base", null, { alt_rms: alt[2], spd_rms: spd[2], limiter_frac: lim, xtrack_rms: null }),
  row(name, "k@-0.2", 0.8, { alt_rms: alt[0], spd_rms: spd[0], limiter_frac: lim, xtrack_rms: null }),
  row(name, "k@-0.1", 0.9, { alt_rms: alt[1], spd_rms: spd[1], limiter_frac: lim, xtrack_rms: null }),
  row(name, "k@+0.1", 1.1, { alt_rms: alt[3], spd_rms: spd[3], limiter_frac: lim, xtrack_rms: null }),
  row(name, "k@+0.2", 1.2, { alt_rms: alt[4], spd_rms: spd[4], limiter_frac: lim, xtrack_rms: null }),
];

const NIL = [null, null, null, null, null];

test("trendMatrix: 단조·비단조·평탄·판정 불가를 구분한다 — 넷을 뭉치면 표가 답을 못 낸다", () => {
  const rows = [
    ...caseRows("M0.4_h100_f200", [12, 11, 10, 9, 8], [null, null, 5, null, null], 0),
    ...caseRows("M0.6_h100_f200", [9, 9.5, 10, 9.5, 9], [null, null, 5, null, null], 0),
  ];
  const tm = trendMatrix(rows, "k");
  assert.deepEqual(tm.points.map((p) => p.span), [-0.2, -0.1, 0.1, 0.2]);
  assert.deepEqual(tm.points.map((p) => p.knobValue), [0.8, 0.9, 1.1, 1.2]);

  const [c1, c2] = tm.cases;
  // 스팬이 커질수록 줄어든다 — 게인을 올리면 이 구간의 고도 RMS가 내려간다
  assert.equal(c1.cells.alt_rms.trend, "down");
  assert.ok(close(c1.cells.alt_rms.slope, -1)); // +10%당 −1 m (최소제곱)
  assert.ok(close(c1.cells.alt_rms.rel, -0.1)); // 기준 10 m 대비 −10%
  assert.ok(close(c1.cells.alt_rms.swing, 4));
  assert.deepEqual(c1.cells.alt_rms.values, [12, 11, 9, 8]);
  assert.equal(c1.cells.alt_rms.base, 10);

  // 양끝이 내려가고 가운데가 솟았다 — 스팬 안에 극점이 있다는 사실이 "단조"로
  // 접히면 안 된다 (회귀 기울기 부호로 판정하면 여기서 0에 가까워 '평탄'이 된다)
  assert.equal(c2.cells.alt_rms.trend, "mixed");
  assert.ok(close(c2.cells.alt_rms.swing, 1));

  // 기준만 있고 흔든 런의 값이 전부 없다 — "안 변했다"가 아니라 판정 불가다
  assert.equal(c1.cells.spd_rms.trend, "none");
  assert.equal(c1.cells.spd_rms.slope, null);
  assert.match(c1.cells.spd_rms.reason, /기준 하나뿐/);

  // 전 점이 같은 값 — 이건 판정 불가가 아니라 "이 손잡이가 이 지표를 안 움직인다"
  assert.equal(c1.cells.limiter_frac.trend, "flat");
  assert.equal(c1.cells.limiter_frac.slope, 0);
  assert.equal(c1.cells.limiter_frac.swing, 0);
  assert.equal(c1.cells.limiter_frac.rel, null); // 기준 0 — 비율이 없다(relOf 규약)

  // 전 구간 전부 없는 지표는 「—」 열로 표를 채우지 않고 따로 이름을 낸다
  assert.deepEqual(tm.metrics, ["alt_rms", "spd_rms", "limiter_frac"]);
  assert.deepEqual(tm.unmeasured, ["xtrack_rms"]);

  assert.deepEqual(tm.counts.alt_rms, { up: 0, down: 1, mixed: 1, flat: 0, none: 0 });
  assert.deepEqual(tm.counts.spd_rms, { up: 0, down: 0, mixed: 0, flat: 0, none: 2 });
  assert.deepEqual(tm.total, { up: 0, down: 1, mixed: 1, flat: 2, none: 2 });
});

test("trendMatrix: 평탄한 지표의 기울기는 **정확히 0** — 회귀 반올림이 안 움직인 값을 움직였다고 말하지 않게", () => {
  // 실측(server_data/0bdf5c4be9f6): 실속마진이 네 스팬에서 전부 같은데 회귀가
  // 7.7e−34를 냈고, 화면은 그 수를 그대로 찍었다 — 0이 아닌 수는 "움직였다"로 읽힌다
  const v = 0.23790136464742842;
  const rows = caseRows("M0.5_h1000_f200", [v, v, v, v, v], NIL, 0);
  const cell = trendMatrix(rows, "k").cases[0].cells.alt_rms;
  assert.equal(cell.trend, "flat");
  assert.equal(cell.slope, 0);
  assert.equal(cell.rel, 0);
});

test("trendMatrix: 1 ulp 차이로 판정이 뒤집히지 않는다 — 반올림 잡음은 신호가 아니다", () => {
  const v = 31.234567890123;
  const up1 = v + Number.EPSILON * v;   // 마지막 자리 하나
  // 순수 부호 판정이면 [v, v+1ulp, v] 는 「비단조」 — 이 표에서 가장 센 판정이
  // 부동소수 끝자리로 선다. 가운데만 솟은 모양이라 단조로도 못 접힌다
  const noisy = trendMatrix(
    caseRows("M0.5_h1000_f200", [v, up1, v, up1, v], NIL, 0), "k").cases[0];
  assert.equal(noisy.cells.alt_rms.trend, "flat");
  assert.equal(noisy.cells.alt_rms.slope, 0);
  // 문턱은 **상대**다 — 값이 작아도 실제 신호는 그대로 잡힌다 (상대 1e-4대)
  const real = trendMatrix(
    caseRows("M0.5_h1000_f200",
      [0.2102, 0.2096, 0.2091, 0.2088, 0.2085], NIL, 0), "k").cases[0];
  assert.equal(real.cells.alt_rms.trend, "down");
});

test("trendMatrix: 문턱은 **상대**다 — 절대 상수면 큰 값에서 잡음을, 작은 값에서 신호를 잘못 읽는다", () => {
  const trend = (vals) =>
    trendMatrix(caseRows("M0.5_h1000_f200", vals, NIL, 0), "k").cases[0].cells.alt_rms.trend;
  // **변형을 잡는 줄은 이쪽이다**: 1e6대에서 1e-7 차이는 상대 1e-13(잡음)이지만
  // 절대값으로는 1e-12보다 크다 — `scale *`를 떼면 여기가 「비단조」로 빨개진다
  assert.equal(trend([1e6, 1e6 + 1e-7, 1e6, 1e6 - 1e-7, 1e6]), "flat");
  // 아래 줄은 반대 방향의 가드다 — 상대 1e-3짜리 **신호**가 문턱에 삼켜지지 않는지.
  // 다만 이 줄이 막는 것은 큰 절대 상수(≥5e-7)뿐이다: 절대 1e-12로 바꿔도 5e-7
  // 차분은 그대로 잡히므로, 이 줄만으로 상대성이 고정된다고 읽으면 안 된다
  assert.equal(trend([3e-6, 2.5e-6, 2e-6, 1.5e-6, 1e-6]), "down");
});

test("trendMatrix: ∞는 곡선에서 빼되 **화면에서는 지우지 않는다** — 발산과 미계측은 다르다", () => {
  // 서버는 ±inf를 "inf"/"-inf" 문자열로 준다 (serialize 정책, fmtDelta가 ∞로 찍는다)
  const rows = caseRows("M0.5_h1000_f200", [12, "inf", 10, 9, 8], NIL, 0);
  const cell = trendMatrix(rows, "k").cases[0].cells.alt_rms;
  // 곡선 점에서는 빠진다 — 차분이 ±∞·NaN이라 세울 수 없다
  assert.deepEqual(cell.values, [12, null, 9, 8]);
  // 그러나 서버가 준 값은 그대로 남는다 (화면이 「—」 대신 ∞를 찍는 근거)
  assert.deepEqual(cell.raw, [12, "inf", 9, 8]);
  assert.equal(cell.nonfinite, true);
  assert.equal(cell.trend, "down");

  // 기준은 멀쩡하고 섭동만 발산 — 이 기능이 겨냥하는 바로 그 시나리오다.
  // 「기준」열에 값이 찍혀 있는데 사유가 "세울 점이 없다"면 표가 자기와 어긋난다
  const soloBase = trendMatrix(
    caseRows("M0.5_h1000_f200", ["inf", "inf", 10, "inf", "inf"], NIL, 0), "k")
    .cases[0].cells.alt_rms;
  assert.equal(soloBase.base, 10);
  assert.match(soloBase.reason, /기준 하나뿐/);
  assert.match(soloBase.reason, /∞/);       // 어느 쪽이 발산했는지까지 말한다
  assert.ok(!/세울 점이 없다/.test(soloBase.reason));

  // 전 점이 ∞면 곡선은 없지만 **잰 지표다** — "이 기동이 못 재는 지표" 목록이 아니다
  const all = trendMatrix(
    caseRows("M0.5_h1000_f200", ["inf", "inf", "inf", "inf", "inf"], NIL, 0), "k");
  assert.ok(all.metrics.includes("alt_rms"));
  assert.ok(!all.unmeasured.includes("alt_rms"));
  const c = all.cases[0].cells.alt_rms;
  assert.equal(c.trend, "none");
  assert.match(c.reason, /∞/);          // "재지 못했다"가 아니다
  assert.equal(c.base, null);
  assert.equal(c.rawBase, "inf");
});

test("trendMatrix: base 런이 없는 구간의 사유는 「기준이 없다」다 — 「기준 하나뿐」이 아니다", () => {
  const rows = caseRows("M0.5_h1000_f200", [null, null, 10, 9, null], NIL, 0);
  rows.shift();  // base 런을 통째로 뺀다 (취소로 잘린 스윕에서 실재한다)
  const c = trendMatrix(rows, "k").cases[0];
  assert.deepEqual(c.missing, ["base"]);
  const cell = c.cells.alt_rms;
  assert.equal(cell.base, null);
  assert.equal(cell.trend, "none");     // 섭동 한 점만으로는 방향이 없다
  assert.match(cell.reason, /기준\(base\) 런의 값이 없다/);
  assert.equal(cell.rel, null);
});

test("trendMatrix: 행은 격자 순 — 서펜타인 실행 순서로는 마하가 줄마다 뒤집힌다", () => {
  const rows = [
    ...caseRows("M0.4_h100_f200", [1, 1, 1, 1, 1], NIL, 0),
    ...caseRows("M0.6_h100_f200", [1, 1, 1, 1, 1], NIL, 0),
    ...caseRows("M0.6_h1000_f200", [1, 1, 1, 1, 1], NIL, 0),  // 둘째 줄은 역순 실행
    ...caseRows("M0.4_h1000_f200", [1, 1, 1, 1, 1], NIL, 0),
  ];
  assert.deepEqual(trendMatrix(rows, "k").cases.map((c) => c.name), [
    "M0.4_h100_f200", "M0.6_h100_f200", "M0.4_h1000_f200", "M0.6_h1000_f200",
  ]);
});

test("trendMatrix: 잘린 런·빠진 런은 행에 남는다 — 없는 점을 0으로 치면 경향이 달라진다", () => {
  const full = caseRows("M0.6_h100_f200", [12, 11, 10, 9, 8], NIL, 0);
  const partial = caseRows("M0.4_h100_f200", [12, 11, 10, 9, 8], NIL, 0);
  partial[1].aborted = true;            // 발산으로 잘린 런
  const rows = [...partial.slice(0, 4), ...full];  // +0.2는 취소로 아예 안 돌았다
  const [c1] = trendMatrix(rows, "k").cases;
  assert.equal(c1.name, "M0.4_h100_f200");
  assert.deepEqual(c1.aborted, ["k@-0.2"]);
  assert.deepEqual(c1.missing, ["k@+0.2"]);
  // 빠진 점은 곡선에서 빠질 뿐 — 남은 네 점(12·11·10·9)으로 판정한다
  assert.deepEqual(c1.cells.alt_rms.values, [12, 11, 9, null]);
  assert.equal(c1.cells.alt_rms.trend, "down");
});

test("sweepKnobs: 단독 런이 있는 손잡이만 — 쌍 런은 한쪽의 경향으로 읽으면 귀속이 틀린다", () => {
  const rows = [
    { case: "c1", label: "base", overrides: {}, metrics: {} },
    { case: "c1", label: "kp@+0.1", overrides: { kp: 1.1 }, metrics: {} },
    { case: "c1", label: "kp@+0.2", overrides: { kp: 1.2 }, metrics: {} },
    { case: "c1", label: "ki@+0.1", overrides: { ki: 0.2 }, metrics: {} },
    { case: "c1", label: "kp&ki@+0.1", overrides: { kp: 1.1, ki: 0.2 }, metrics: {} },
  ];
  assert.deepEqual(sweepKnobs(rows), ["kp", "ki"]);  // 런 순서 = 처방 카드 순서
  assert.deepEqual(sweepKnobs([]), []);
  assert.deepEqual(sweepKnobs(undefined), []);
  // 손잡이 이름이 다른 단독 런은 그 손잡이의 스팬 점이 아니다
  assert.deepEqual(trendMatrix(rows, "kp").points.map((p) => p.span), [0.1, 0.2]);
});

test("TREND_MARK: 색과 별도로 기호가 경향을 말한다 — 색만이면 흑백에서 표가 무의미해진다", () => {
  assert.deepEqual(Object.keys(TREND_MARK).sort(), Object.keys(TREND_LABEL).sort());
  assert.equal(new Set(Object.values(TREND_MARK)).size, Object.keys(TREND_MARK).length);
});

test("trendInk: 색은 방향이 아니라 좋고 나쁨 — 극성이 없으면 단언하지 않는다", () => {
  assert.equal(trendInk("up", "lower"), BAD_INK);     // 추종 RMS가 오르면 악화
  assert.equal(trendInk("up", "higher"), GOOD_INK);   // 실속마진이 오르면 개선
  assert.equal(trendInk("down", "lower"), GOOD_INK);
  assert.equal(trendInk("down", "higher"), BAD_INK);
  assert.equal(trendInk("mixed", "lower"), WARN_INK);
  assert.equal(trendInk("flat", "lower"), SKIN.inkDim);
  assert.equal(trendInk("none", "lower"), SKIN.inkFaint);
  assert.equal(trendInk("up", undefined), SKIN.ink);  // 극성 미상 — 중립
});
