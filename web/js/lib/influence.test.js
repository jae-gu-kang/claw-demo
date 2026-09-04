// 화면 모델 계약 — 특히 "없음"과 "0"을 섞지 않는지.
import { readFileSync } from "node:fs";
import test from "node:test";
import assert from "node:assert/strict";

import {
  KNOB_CLASS, columnDigits, coneOf, diagnoseRequest, edgeVia, fmtDelta, fmtPair,
  fmtChange, fmtPercent, fmtSigned, impactRank, logScale, pairDigits,
  nodeDetail, normalizeDiagnosis, normalizeGraph, openloopWorst, pairsFor,
  paramState, probeTransition, radiusOf, rampColor, relOf, scanRequest,
  scanSummary, structuralRequest, sweepCases, sweepRequest, worstTransitions,
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

test("columnDigits: 한 열은 가장 촘촘한 전이에 맞춘다 — 같은 기준값이 다르게 찍히지 않게", () => {
  // 라이브에서 나온 회귀: 같은 base 런의 40.847이 한 열 안에서 40.8·40.847·40.85로
  // 세 번 다르게 찍혀 다른 수처럼 읽혔다
  const col = [[40.847, 40.853], [40.847, 40.85], [40.847, 40.84]];
  const d = columnDigits(col);
  const lefts = new Set(col.map(([f, t]) => fmtPair(f, t, d)[0]));
  assert.equal(lefts.size, 1, `같은 기준값은 한 열에서 한 표기: ${[...lefts]}`);
  // 그러면서도 가장 촘촘한 행이 뭉개지지 않아야 한다
  for (const [f, t] of col) {
    const [a, b] = fmtPair(f, t, d);
    assert.notEqual(a, b, `${f} → ${t}가 뭉개졌다`);
  }
  assert.equal(columnDigits([]), 3);            // 셀 것이 없으면 최소 자릿수
  assert.equal(columnDigits([[null, 3]]), 3);   // 미계측은 자릿수를 끌어올리지 않는다
  // 행별 최소의 **최댓값**이면 안 된다: 40.847→40.853은 3자리(40.8/40.9)에서 갈리지만
  // 4자리에서 둘 다 40.85로 새로 뭉개진다. 이 열의 답은 5자리다
  assert.equal(pairDigits(40.847, 40.853), 3);
  assert.equal(pairDigits(40.847, 40.84), 4);
  assert.equal(d, 5, "행별 최댓값(4)을 쓰면 첫 행이 뭉개진다");
  // 정말 같은 값인 행은 탐색을 막지 않는다 (섭동이 범위에 클립된 자리)
  assert.equal(columnDigits([[1.5, 1.5], [2.0, 2.1]]), 3);
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
  assert.deepEqual(
    [dead, moved, appeared].sort((a, b) => impactRank(b) - impactRank(a)),
    [appeared, moved, dead]);
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
