/** lib/evaluate v2 계약 — A급 카드·B급 요약·C급 검증 모델의 판단.

핵심 규약: ① 카드·체크 어휘는 서버가 준다(웹 재기술 금지 — 빈 응답에서도 죽지
않되 지어내지 않는다) ② B급 요약에서 na는 PASS 분모에서 빠지되 **반드시 병기**
된다, warn은 PASS가 아니다 ③ J null은 빈칸이 아니라 사유 문장이다 ④ 상태 어휘는
엔진 evaluate.py와 한 벌이다(드리프트 가드).
*/

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  STATUS_LABEL, attributionRows, cardDeltas, cardLines, caseGrid, checksSummary,
  compositionLine, evalFocus, evaluateRequest, hardFailLines, jLine, localityLines,
  normalizeEvalReport,
  normalizeVerifyReport, statusInk, verifyRequest,
  maneuverLine,
  sameManeuver,
  MANEUVER_KEYS,
} from "./evaluate.js";

const payload = {
  depth: "full",
  cards: [
    { key: "gm", card: 2, label: "이득여유 GM", status: "fail",
      value: { gm_db: 4.2, loop: "roll_att" },
      threshold: { gm_min_db: 6.0, gm_good_db: 8.0 },
      worst_case: "M0.5", note: null },
    { key: "pm", card: 3, label: "위상여유 PM", status: "ok",
      value: { pm_deg: 61.0, loop: "pitch_att", delay_margin_s: 0.066 },
      threshold: { pm_min_deg: 45.0 }, worst_case: "M0.5", note: null },
  ],
  checks: {
    list: [
      { key: "poles_all", label: "전체 극점", status: "warn",
        worst_case: "M0.5", value: null, note: "허용된 나선 발산" },
      { key: "envelope", label: "실속·엔벨로프 마진", status: "ok",
        worst_case: "M0.5", value: { value: 0.21, case: "M0.5" }, note: null },
      { key: "recovery", label: "포화 회복", status: "na",
        worst_case: null, value: null, note: "계측 없음" },
    ],
    n_pass: 1, n_warn: 1, n_fail: 0, n_na: 1, n_judged: 2,
  },
  stage_order: ["envelope", "margins"],
  items: { envelope: { item: 5, label: "실속·엔벨로프 마진" },
           margins: { item: 3, label: "이득·위상여유" } },
  hard_checks: ["margins.gm"],
  cases: [{
    case: "M0.5", midpoint: false, aborted: false,
    stages: { envelope: { status: "ok" }, margins: { status: "fail" } },
    hard_fails: [{ check: "margins.gm", loop: "roll_att", value: 4.2,
                   limit: 6.0, case: "M0.5" }],
    J: null, J_reason: "하드 실패",
  }],
  aggregate: {
    hard_fail: true,
    hard_fails: [{ check: "margins.gm", loop: "roll_att", value: 4.2,
                   limit: 6.0, case: "M0.5" }],
    stages: { envelope: { status: "ok" }, margins: { status: "fail" } },
    J: null, J_reason: "J 미산정 케이스가 있다",
    n_cases: 1, n_midpoint: 0,
  },
  warnings: [], fingerprint: "fp", criteria_fingerprint: "cfp",
};

test("빈 응답에서도 죽지 않되 카드·체크를 지어내지 않는다", () => {
  const m = normalizeEvalReport(null);
  assert.deepEqual(m.cards, []);
  assert.equal(m.checks, null);
  assert.deepEqual(caseGrid(m), []);
});

test("정규화 — 카드·체크·깊이가 그대로 실린다", () => {
  const m = normalizeEvalReport(payload);
  assert.equal(m.depth, "full");
  assert.equal(m.cards.length, 2);
  assert.equal(m.checks.n_pass, 1);
});

test("B급 요약 — na는 분모에서 빠지되 반드시 병기, warn은 PASS가 아니다", () => {
  const m = normalizeEvalReport(payload);
  const line = checksSummary(m.checks);
  assert.match(line, /1\/2 PASS/);  // ok 1 / judged 2 — warn은 pass가 아니다
  assert.match(line, /주의 1/);
  assert.match(line, /판정 불가 1/);  // na>0이면 생략 불가
});

test("B급 요약 — 전부 통과·na 0이면 짧은 한 줄", () => {
  const line = checksSummary({ n_pass: 9, n_warn: 0, n_fail: 0, n_na: 0,
                               n_judged: 9, list: [] });
  assert.equal(line, "나머지 판정 9/9 PASS");
});

test("B급 요약 — 체크가 하나도 없으면 판정 불가 문장", () => {
  const line = checksSummary({ n_pass: 0, n_warn: 0, n_fail: 0, n_na: 9,
                               n_judged: 0, list: [] });
  assert.match(line, /0\/0/);
  assert.match(line, /판정 불가 9/);
});

test("카드 줄 — 값·기준·최악 운용점이 문장으로 선다 (GM 카드)", () => {
  const m = normalizeEvalReport(payload);
  const lines = cardLines(m.cards[0]);
  const joined = lines.join(" | ");
  assert.match(joined, /4\.2/);
  assert.match(joined, /6/);       // 기준
  assert.match(joined, /roll_att/);
  assert.match(joined, /M0\.5/);   // 최악 운용점
});

test("카드 줄 — 값이 없으면 사유가 선다 (지어내지 않는다)", () => {
  const lines = cardLines({ key: "gm", label: "이득여유 GM", status: "na",
                            value: null, threshold: null, worst_case: null,
                            note: "판정할 루프 마진이 없다" });
  assert.match(lines.join(" "), /판정할 루프 마진이 없다/);
  assert.ok(!/null|undefined|NaN/.test(lines.join(" ")));
});

test("케이스 격자 — 행이 케이스, 열이 stage_order", () => {
  const g = caseGrid(normalizeEvalReport(payload));
  assert.deepEqual(g[0].statuses, ["ok", "fail"]);
  assert.equal(g[0].hardFails, 1);
});

test("J null은 빈칸이 아니라 사유 문장이다", () => {
  const line = jLine(normalizeEvalReport(payload).aggregate);
  assert.match(line, /J 없음/);
  assert.ok(!/NaN|null|undefined/.test(line));
});

test("하드 실패 줄 — check 어휘는 번역하지 않는다", () => {
  const lines = hardFailLines(normalizeEvalReport(payload).aggregate);
  assert.match(lines[0], /margins\.gm/);
  assert.match(lines[0], /roll_att/);
});

test("요청 본문 — depth가 실리고 v1 필드(items)는 없다", () => {
  const body = evaluateRequest({}, { cases: [{ mach: 0.5 }], depth: "linear",
                                     tSettle: 2, fingerprint: "fp" });
  assert.equal(body.depth, "linear");
  assert.equal(body.t_settle, 2);
  assert.ok(!("items" in body) && !("schedule_midpoints" in body));
});

test("검증 요청 — 중간점 스위치·깊이가 실린다", () => {
  const body = verifyRequest({}, { cases: [{ mach: 0.5 }], depth: "linear",
                                   midpoints: false });
  assert.equal(body.midpoints, false);
  assert.equal(body.depth, "linear");
});

test("검증 응답 정규화 — 블록·상태가 실리고 빈 응답에도 죽지 않는다", () => {
  const v = normalizeVerifyReport({
    verify: { mass_cg: { status: "ok", corners: [], note: "[TBD]" } },
    verify_meta: { mass_cg: "질량·CG 섭동" },
    status: "ok", fingerprint: "fp", criteria_fingerprint: "cfp",
  });
  assert.equal(v.blocks[0].key, "mass_cg");
  assert.equal(v.blocks[0].label, "질량·CG 섭동");
  assert.deepEqual(normalizeVerifyReport(null).blocks, []);
});

test("상태 어휘는 엔진 evaluate.py와 한 벌이다 (드리프트 가드)", () => {
  const src = readFileSync(
    new URL("../../../engine/claw/pipeline/evaluate.py", import.meta.url),
    "utf8");
  const m = src.match(/_RANK = \{([^}]+)\}/);
  assert.ok(m, "엔진 _RANK 선언을 찾지 못했다");
  const engineStatuses = [...m[1].matchAll(/"(\w+)"/g)].map((x) => x[1]);
  assert.deepEqual(new Set(engineStatuses), new Set(Object.keys(STATUS_LABEL)));
  for (const s of engineStatuses) {
    assert.ok(statusInk(s), `${s}의 잉크가 없다`);
  }
  assert.notEqual(statusInk("na"), statusInk("ok"));
  assert.notEqual(statusInk("na"), statusInk("fail"));
  // 카드 7·체크 10 — 웹은 목록을 하드코딩하지 않지만 개수 계약은 화면 배치의 전제다
  assert.equal((src.match(/CARDS = \(([^)]+)\)/) || [])[1].split(",")
    .filter((x) => x.trim()).length, 7);
  assert.equal((src.match(/CHECKS = \(([^)]+)\)/) || [])[1].split(",")
    .filter((x) => x.trim()).length, 10);
});

test("카드 값의 문자열 필드는 수로 위장되지 않는다 (라이브에서 case가 −∞로 찍혔다)", () => {
  const lines = cardLines({
    key: "mode_stability", label: "모드 안정성", status: "ok",
    value: { mode: "zeta_dr", zeta: 0.75, wn: 2.1, case: "M0.4_h3000_f200" },
    threshold: { zeta_min: 0.3 }, worst_case: "M0.4_h3000_f200", note: null,
  });
  const joined = lines.join(" | ");
  assert.ok(!joined.includes("−∞") && !joined.includes("NaN"), joined);
  // case 키는 worst_case 줄이 싣는다 — 같은 이름이 두 번 찍히지 않는다
  assert.equal(joined.split("M0.4_h3000_f200").length - 1, 1);
});

test("소견(원인 귀속)은 판정 옆에 선다 — 별도 실행 표면이 아니다", () => {
  const m = normalizeEvalReport({
    ...payload,
    cases: [{ ...payload.cases[0],
      attribution: { status: "ok",
        findings: [{ rule: "error_split", axis: "alt", severity: "warn",
                     verdict: "필터 병목", evidence: { rms_filter: 3.1 } }],
        prescriptions: [{ knobs: ["fcl/Autopilot.tau_alt"], knob_class: "filter",
                          direction: "decrease", findings: [0], joint_with: [],
                          recheck: ["surf_sat_frac"], notes: [] }] } }],
  });
  const rows = attributionRows(m);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].case, "M0.5");
  assert.match(rows[0].text, /tau_alt/);
  assert.match(rows[0].text, /줄인다|↓/);
  assert.deepEqual(rows[0].knobs, ["fcl/Autopilot.tau_alt"]);
});

test("귀속이 없으면 사유가 자리를 지킨다 (빈칸 금지)", () => {
  const m = normalizeEvalReport({
    ...payload,
    cases: [{ ...payload.cases[0],
      attribution: { status: "na", note: "전 항목 통과 — 귀속할 결함이 없다" } }],
  });
  const rows = attributionRows(m);
  assert.equal(rows[0].solvable, false);
  assert.match(rows[0].text, /귀속할 결함이 없다/);
  assert.deepEqual(rows[0].knobs, []);
});

test("국소성 줄 — 어디서 나쁜지와 처방 층을 함께 낸다", () => {
  const lines = localityLines({
    metrics: {
      alt_rms: { verdict: "local", n_bad: 2, n_cases: 6, bad_frac: 0.33,
                 bad_cases: ["M0.4", "M0.45"], knob_class: "schedule",
                 threshold: 10.0 },
      spd_rms: { verdict: "ok", n_bad: 0, n_cases: 6, bad_cases: [],
                 knob_class: null, threshold: 2.0 },
    },
    local_frac: 1 / 3,
  });
  const joined = lines.join(" | ");
  assert.match(joined, /alt_rms/);
  assert.match(joined, /국소/);
  assert.match(joined, /2\/6/);
  assert.match(joined, /M0\.4/);
  assert.ok(!/spd_rms/.test(joined), "통과 지표는 줄을 차지하지 않는다");
  assert.deepEqual(localityLines(null), []);
});

test("재측정 델타 — 대표 스칼라끼리 짝지어 좋아졌는지 말한다", () => {
  const before = [{ key: "gm", label: "이득여유 GM", status: "fail",
                    primary: { value: 4.2, unit: "dB", better: "higher" } }];
  const after = [{ key: "gm", label: "이득여유 GM", status: "ok",
                   primary: { value: 7.1, unit: "dB", better: "higher" } }];
  const [d] = cardDeltas(before, after);
  assert.equal(d.key, "gm");
  assert.equal(d.improved, true);
  assert.match(d.text, /4\.2/);
  assert.match(d.text, /7\.1/);
  assert.match(d.text, /dB/);
  // 나빠진 쪽도 같은 문법으로 — 개선만 보여 주면 화면이 낙관 편향이 된다
  const [w] = cardDeltas(after, before);
  assert.equal(w.improved, false);
});

test("델타 — 한쪽이 못 잰 카드는 사유가 값 자리다", () => {
  const [d] = cardDeltas(
    [{ key: "pm", label: "PM", status: "na", primary: null }],
    [{ key: "pm", label: "PM", status: "ok",
       primary: { value: 61, unit: "deg", better: "higher" } }]);
  assert.equal(d.improved, null);
  assert.match(d.text, /이전 값 없음|판정 불가/);
  assert.ok(!/NaN|null|undefined/.test(d.text));
});

test("마진 조성 줄 — 무슨 플랜트에서 판정했는지 화면이 말한다", () => {
  const m = normalizeEvalReport({
    ...payload,
    cases: [{ ...payload.cases[0], stages: { ...payload.cases[0].stages,
      margins: { status: "ok", composition: {
        text: "레이트 폐쇄 플랜트 + 작동기·지연 포함", actuator_wn: 30.0,
        actuator_zeta: 0.7, delay_s: 0.035, pade_order: 2 } } } }],
  });
  const line = compositionLine(m);
  assert.match(line, /작동기/);
  assert.match(line, /30/);
  assert.match(line, /35 ms/);
  assert.ok(!/NaN|undefined/.test(line));
  // 구버전 저장물(문장 하나)도 그대로 읽는다 — 조용히 빈칸이 되지 않게
  const old = normalizeEvalReport({ ...payload,
    cases: [{ ...payload.cases[0], stages: { margins: { composition: "옛 문장" } } }] });
  assert.equal(compositionLine(old), "옛 문장");
  assert.equal(compositionLine(normalizeEvalReport(null)), null);
});

test("그래프 초점 — 소견이 귀속한 설계변수와 실패한 지표를 뽑는다", () => {
  const m = normalizeEvalReport({
    ...payload,
    cards: [
      { key: "gm", label: "GM", status: "fail", value: null, primary: null },
      { key: "pm", label: "PM", status: "ok", value: null, primary: null },
    ],
    aggregate: { ...payload.aggregate, locality: { metrics: {
      alt_rms: { verdict: "global", bad_cases: ["M0.5"] },
      spd_rms: { verdict: "ok", bad_cases: [] },
      surf_sat_frac: { verdict: "local", bad_cases: ["M0.6"] },
    } } },
    cases: [{ ...payload.cases[0], attribution: { status: "ok", findings: [],
      prescriptions: [
        { knobs: ["fcl/Autopilot.tau_alt"], knob_class: "filter",
          direction: "decrease", findings: [], joint_with: [], recheck: [], notes: [] },
        { knobs: ["table.pitch.kp", "fcl/Autopilot.tau_alt"], knob_class: "loop_gain",
          direction: "increase", findings: [], joint_with: [], recheck: [], notes: [] },
      ] } }],
  });
  const f = evalFocus(m);
  // 설계변수는 중복 없이, 파라미터 노드 id로
  assert.deepEqual(f.paramIds,
    ["param:fcl/Autopilot.tau_alt", "param:table.pitch.kp"]);
  // 문턱을 넘은 지표만 — 통과 지표는 초점이 아니다
  assert.deepEqual(f.metricIds, ["metric:alt_rms", "metric:surf_sat_frac"]);
  assert.match(f.caption, /설계변수 2/);
  assert.match(f.caption, /지표 2/);
});

test("그래프 초점 — 귀속도 실패도 없으면 초점을 만들지 않는다", () => {
  const clean = normalizeEvalReport({
    ...payload,
    aggregate: { ...payload.aggregate, hard_fail: false, hard_fails: [],
                 locality: { metrics: { alt_rms: { verdict: "ok", bad_cases: [] } } } },
    cases: [{ ...payload.cases[0], hard_fails: [],
              attribution: { status: "na", note: "전 항목 통과" } }],
  });
  const f = evalFocus(clean);
  assert.equal(f, null);  // 초점 없음은 빈 초점이 아니다 — 그래프를 흐리지 않는다
  assert.equal(evalFocus(normalizeEvalReport(null)), null);
});

test("기동 기록 — 옛 결과는 「미기록」이지 기본값이 아니다", () => {
  // 스텝이 바뀌면 같은 지문으로도 RMS·J가 다른 뜻이 된다. 없는 것을 현행 값으로
  // 채우면 옛 결과가 새 자로 잰 것처럼 읽힌다 — 「없음」과 「값」을 섞지 않는다
  assert.equal(normalizeEvalReport({}).maneuver, null);
  const m = normalizeEvalReport({ maneuver: { dv: 3, dh: 30, dpsi: 0.3, t_step: 30 } });
  assert.equal(m.maneuver.dv, 3);
  assert.equal(m.maneuver.t_step, 30);
});

test("기동 줄 — 선형은 침묵, 기록 없으면 「미기록」, 있으면 단위까지", () => {
  // 선형은 시뮬을 한 번도 안 돈다 — 결과에 기동이 적혀 있어도 찍으면 안 돈 것을
  // 돈 것처럼 읽힌다. 이 가드를 지우면 바로 그 오독이 되는데 종전에는 무증상이었다
  const man = { dh: 30, dv: 3, dpsi: 0.3, t_step: 15 };
  assert.equal(maneuverLine({ depth: "linear", maneuver: man }), "");
  assert.equal(maneuverLine({ depth: "full", maneuver: null }),
    "기동 미기록 — 옛 결과라 스텝이 지금과 다를 수 있다");
  const line = maneuverLine({ depth: "full", maneuver: man });
  // 단위가 없으면 dψ가 rad인지 deg인지 화면만 보고 못 정한다 (17배 차이다)
  assert.match(line, /dh 30 m/);
  assert.match(line, /dv 3 m\/s/);
  assert.match(line, /dψ 0\.3 rad/);
  assert.match(line, /간격 15 s/);
  assert.equal(maneuverLine(null), "");
});

test("기동이 다르면 「직전 대비」를 비교하지 않는다 — 개선이 아니라 자가 바뀐 것", () => {
  const man = { dv: 3, dh: 30, dpsi: 0.3, t_settle: 5, t_step: 15, t_hold: 15 };
  const run = (m) => ({ depth: "full", maneuver: m });
  assert.ok(sameManeuver(run(man), run({ ...man })));
  // 옛 결과는 스텝을 모른다 — 「같다」로 넘기면 그 오독이 그대로 남는다
  assert.ok(!sameManeuver(run(null), run(man)));
  assert.ok(!sameManeuver(run(man), { depth: "full" }));
  // **여섯 키가 전부 판정에 든다.** 하나라도 빠지면 그 축의 변경이 조용히
  // 「같은 기동」이 된다 — dh 100→30이 v0.72가 실제로 한 일이라 남 얘기가 아니다.
  // 목록은 **여기 손으로 적는다**: MANEUVER_KEYS를 순회하면 키를 빼는 변이가
  // 테스트의 순회 대상까지 같이 줄여 자기참조로 통과한다(실제로 그랬다)
  for (const k of ["dv", "dh", "dpsi", "t_settle", "t_step", "t_hold"]) {
    const other = { ...man, [k]: man[k] + 1 };
    assert.ok(!sameManeuver(run(man), run(other)), `${k}가 판정에서 빠졌다`);
  }
});

test("기동 키 목록이 엔진 evaluate.py와 한 벌이다 (드리프트 가드)", () => {
  // 엔진이 키를 늘리면 웹의 비교가 그 축을 못 보고 조용히 「같다」고 답한다 —
  // 상태 어휘 가드와 같은 방식으로 정본을 직접 읽어 대조한다
  const src = readFileSync(
    new URL("../../../engine/claw/pipeline/evaluate.py", import.meta.url),
    "utf8");
  const m = src.match(/"maneuver": \{([\s\S]*?)\},/);
  assert.ok(m, "엔진 maneuver 선언을 찾지 못했다");
  const engineKeys = [...m[1].matchAll(/"(\w+)":/g)].map((x) => x[1]);
  assert.deepEqual(new Set(engineKeys), new Set(MANEUVER_KEYS));
});

test("선형끼리는 기동과 무관하게 비교된다 — 없는 비교 불가를 지어내지 않는다", () => {
  // 선형은 시뮬을 한 번도 안 돌아 기동이 쓰이지 않는다. 스텝만 바꿔 다시 돌렸다고
  // ζ·GM·PM 델타를 막으면, 이 함수가 막으려던 것과 **정반대** 거짓말이 된다
  const a = { depth: "linear", maneuver: { dv: 3, dh: 30, dpsi: 0.3, t_step: 15 } };
  const b = { depth: "linear", maneuver: { dv: 3, dh: 30, dpsi: 0.3, t_step: 60 } };
  assert.ok(sameManeuver(a, b));
  // 깊이가 다르면 애초에 비교 대상이 아니다
  assert.ok(!sameManeuver(a, { depth: "full", maneuver: a.maneuver }));
});
