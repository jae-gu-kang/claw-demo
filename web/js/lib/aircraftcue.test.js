// 기체 탭 쇼케이스 신호의 판단 — 문서에서 읽는 기본 조건·공학 수정 치환 경로·보고 한 줄 (node --test, 의존 0)
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  aeroReport, basisReport, cd0EditPlan, cd0TermIndex, deriveReport, editReport, machListArg, operatingMachs,
  overviewReport, stabilityReport, viewerDefaults,
} from "./aircraftcue.js";

// 예제 문서는 읽기 전용이라 읽기만 한다 — 판단이 실제 문서 모양에서 도는지
const EXAMPLE = JSON.parse(readFileSync(
  new URL("../../../engine/claw/profile/examples/delta_demo.json", import.meta.url), "utf8"));

// 쇼케이스형 문서의 뼈대 — 수치는 판단 경로를 가르는 데만 쓴다(기체 값의 정본이 아니다)
const doc = (over = {}) => ({
  id: "s", name: "S",
  aero: {
    form: "lift_drag",
    coefficients: {
      CL: [{ k: 3, inputs: ["alpha"] }],
      CD: [{ k: 0.25, inputs: ["CL", "CL"] }, { k: 0.028, inputs: [] }],
    },
    db_ranges: { alpha: [-0.2, 0.55], beta: [-0.3, 0.3], mach: [0, 0.45] },
  },
  structural: { mach_no: 0.23, mach_d: 0.29 },
  law: { schedule: { m_design: 0.147, mach_grid: [0.08, 0.1, 0.2, 0.3] } },
  variants: [{ id: "eoir", name: "EO/IR형", patch: { "/mass/m_empty": 170 } }],
  ...over,
});

test("뷰어 기본 조건 — 설계 마하(없으면 M_NO), α 구간은 DB 유효 범위", () => {
  const d = viewerDefaults(doc());
  assert.equal(d.mach, 0.147);
  assert.equal(d.machSource, "law.schedule.m_design");
  assert.deepEqual(d.alpha, [-0.2, 0.55]);
  const noSched = viewerDefaults(doc({ law: { schedule: null } }));
  assert.equal(noSched.mach, 0.23);
  assert.equal(noSched.machSource, "structural.mach_no");
  // 아무것도 없으면 지어내지 않는다 — 빈 칸으로 두고 입력을 받는다(기체 고정 금지)
  const none = viewerDefaults({ aero: { db_ranges: { alpha: [0.3, 0.1] } } });
  assert.equal(none.mach, null);
  assert.equal(none.alpha, null, "뒤집힌 범위는 쓰지 않는다");
  // 출하 예제: 설계 마하 0.2449 — 옛 고정값 0.5(M_D 0.367 위)가 아니다
  const ex = viewerDefaults(EXAMPLE);
  assert.equal(ex.mach, EXAMPLE.law.schedule.m_design);
  assert.ok(ex.mach < EXAMPLE.structural.mach_d);
  assert.deepEqual(ex.alpha, EXAMPLE.aero.db_ranges.alpha);
});

test("운용 마하 — 스케줄 격자 최소 ~ min(격자 최대, M_NO)에서 고르게 n개", () => {
  const r = operatingMachs(doc());
  assert.deepEqual(r.value, [0.08, 0.155, 0.23]);
  assert.match(r.source, /mach_grid/);
  assert.match(r.source, /structural\.mach_no/);
  assert.deepEqual(operatingMachs(doc(), 2).value, [0.08, 0.23]);
  // M_NO가 없으면 격자 최대까지
  assert.deepEqual(operatingMachs(doc({ structural: {} })).value, [0.08, 0.19, 0.3]);
  // 격자가 없으면 멈춘다 — 사유와 함께
  assert.match(operatingMachs(doc({ law: { schedule: null } })).error, /mach_grid/);
  // 격자가 통째로 M_NO 위면 범위가 성립하지 않는다
  assert.match(operatingMachs(doc({ law: { schedule: { mach_grid: [0.3, 0.4] } } })).error, /M_NO/);
  // 출하 예제: 격자 0.0612…0.3878이 M_NO 0.306에서 잘린다 — 모두 M_D 아래
  const ex = operatingMachs(EXAMPLE);
  assert.equal(ex.value.length, 3);
  assert.equal(ex.value.at(-1), EXAMPLE.structural.mach_no);
  assert.ok(ex.value.every((m) => m < EXAMPLE.structural.mach_d));
});

test("신호가 준 마하 목록 — 양의 유한수 1~6개만", () => {
  assert.deepEqual(machListArg([0.1, 0.2]).value, [0.1, 0.2]);
  assert.match(machListArg([]).error, /1~6/);
  assert.match(machListArg([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]).error, /1~6/);
  assert.match(machListArg([0.1, -0.2]).error, /양의 유한수/);
  assert.match(machListArg([0.1, "0.2"]).error, /양의 유한수/);
  assert.match(machListArg(0.2).error, /목록/);
});

test("CD0 항 — lift_drag의 입력 없는 CD 상수항 하나, 표·여럿·body 형식은 사유", () => {
  assert.deepEqual(cd0TermIndex(doc().aero), { index: 1, k: 0.028 });
  assert.deepEqual(cd0TermIndex(EXAMPLE.aero), { index: 0, k: EXAMPLE.aero.coefficients.CD[0].k });
  assert.match(cd0TermIndex({ form: "body", coefficients: {} }).error, /lift_drag/);
  const two = { form: "lift_drag", coefficients: { CD: [{ k: 0.01, inputs: [] }, { k: 0.02, inputs: [] }] } };
  assert.match(cd0TermIndex(two).error, /2개/);
  assert.match(cd0TermIndex({ form: "lift_drag", coefficients: { CD: [{ k: 0.2, inputs: ["CL"] }] } }).error,
    /상수항/);
  const table = { form: "lift_drag", coefficients: { CD: [{ k: { table: {} }, inputs: [] }] } };
  assert.match(cd0TermIndex(table).error, /표/);
});

test("EO/IR 항력 수정 계획 — 기본 문서 CD0 + Δ를 변형 치환 경로에, 이미 같으면 바뀜 없음", () => {
  const p = cd0EditPlan(doc(), "eoir", 0.007);
  assert.equal(p.ptr, "/aero/coefficients/CD/1/k");
  assert.equal(p.value, 0.035, "부동소수 꼬리(0.035000000000000003)를 싣지 않는다");
  assert.equal(p.base, 0.028);
  assert.equal(p.before, 0.028, "변형이 아직 덮지 않았다 — 지금 보이는 값은 기본 문서 값");
  assert.equal(p.changed, true);
  // 이미 덮어쓴 변형 — 갱신(기본 + Δ, 변형 값 + Δ가 아니다)
  const patched = doc({ variants: [{ id: "eoir", name: "E", patch: { "/aero/coefficients/CD/1/k": 0.04 } }] });
  const q = cd0EditPlan(patched, "eoir", 0.007);
  assert.equal(q.before, 0.04);
  assert.equal(q.value, 0.035);
  assert.equal(q.changed, true);
  const same = doc({ variants: [{ id: "eoir", name: "E", patch: { "/aero/coefficients/CD/1/k": 0.035 } }] });
  assert.equal(cd0EditPlan(same, "eoir", 0.007).changed, false);
  assert.match(cd0EditPlan(doc(), "nope", 0.007).error, /nope/);
  assert.match(cd0EditPlan(doc(), "eoir", Number.NaN).error, /cd0_delta/);
  assert.match(cd0EditPlan(doc(), "eoir", -0.03).error, /0 이하/);
  // 변형이 CD 목록을 통째로 바꿔 항 자리가 달라지면 멈춘다 — 엉뚱한 항에 쓰지 않는다
  const moved = doc({ variants: [{ id: "eoir", name: "E",
    patch: { "/aero/coefficients/CD": [{ k: 0.03, inputs: [] }, { k: 0.25, inputs: ["CL", "CL"] }] } }] });
  assert.match(cd0EditPlan(moved, "eoir", 0.007).error, /자리/);
  // 출하 예제에서도 경로가 선다(쓰기는 서버가 예제를 거부 — 여기는 계획뿐)
  assert.equal(cd0EditPlan(EXAMPLE, "eoir", 0.007).ptr, "/aero/coefficients/CD/0/k");
});

const W = [{ path: "/trim/alpha_bounds/1", variant: null,
  message: "트림 α 탐색 상한 0.35 rad가 판정 한계 최대 0.365 rad(실속 표 최대 − 트림 α 여유)보다 낮다 — 저속에서 막힌다" }];

test("기본 화면 보고 — 이름·리비전·문서 경고(서버 GET 동봉) 그대로", () => {
  const r = overviewReport({ document: { id: "s", name: "S1" }, revision: 3, fingerprint: "abc", warnings: W });
  assert.deepEqual(r.data, { id: "s", name: "S1", revision: 3, fingerprint: "abc", warnings: W });
  assert.match(r.summary, /^S1 · 리비전 3 · 문서 경고 1건 — \/trim\/alpha_bounds\/1 트림 α 탐색 상한 0\.35 rad가/);
  assert.doesNotMatch(r.summary, /저속에서 막힌다/, "한 줄 — 첫 마디까지만");
  const clean = overviewReport({ document: { id: "s", name: "S1" }, revision: 1, fingerprint: "f", warnings: [] });
  assert.equal(clean.summary, "S1 · 리비전 1 · 문서 경고 없음");
  assert.deepEqual(overviewReport({ document: { id: "s", name: "S1" }, revision: 1 }).data.warnings, []);
});

const slice = (mach, extracted, tableAt) => ({
  along: "alpha", fixed: { mach }, stall: { extracted, table_at: tableAt, reason: extracted == null ? "선형" : null },
});

test("공력 보고 — 곡선마다 실속 추출 vs 실속 표", () => {
  const r = aeroReport({ axis: "mach", curves: [
    { tag: "mach 0.08", res: slice(0.08, 0.4, 0.4) }, { tag: "mach 0.23", res: slice(0.23, 0.39, 0.3925) },
  ] });
  assert.deepEqual(r.data.mach, [0.08, 0.23]);
  assert.deepEqual(r.data.stall_extracted, [0.4, 0.39]);
  assert.deepEqual(r.data.stall_table, [0.4, 0.3925]);
  assert.equal(r.summary, "실속 추출 α 0.400 · 0.390 rad vs 실속 표 0.400 · 0.393 rad (M 0.08 · 0.23)");
  // 추출이 없으면(선형 모델) —로 싣고 사유를 data에
  const lin = aeroReport({ axis: "mach", curves: [{ tag: null, res: slice(0.2, null, 0.35) }] });
  assert.deepEqual(lin.data.stall_extracted, [null]);
  assert.deepEqual(lin.data.reasons, ["선형"]);
  assert.match(lin.summary, /실속 추출 α — rad vs 실속 표 0\.350 rad/);
});

test("정적 안정성 보고 — 위반 구간 목록과 도함수별 한 줄", () => {
  const res = { judgments: {
    Cl_beta: { stable_sign: "-", all_ok: true, violations: [] },
    Cn_beta: { stable_sign: "+", all_ok: false, violations: [[0.45, 0.55]] },
    Cm_alpha: { stable_sign: "-", all_ok: true, violations: [] },
  } };
  const r = stabilityReport(res);
  assert.deepEqual(r.data.violations, [{ derivative: "Cn_beta", alpha: [0.45, 0.55] }]);
  assert.equal(r.summary, "Clβ 안정 · Cnβ 위반 α [0.450, 0.550] rad · Cmα 안정");
  const ok = stabilityReport({ judgments: { Cl_beta: res.judgments.Cl_beta } });
  assert.deepEqual(ok.data.violations, []);
});

test("산출 근거 보고 — 머리말 + 레이트 달성·자세 통과 수 (엔진 판정 그대로)", () => {
  const body = {
    ok: true, case: { name: "M0.147_h0_f25", mach: 0.147, alt: 0, fuel: 25 }, e_ref_dps: 10,
    trim: { alpha: 0.04, de: -0.01, throttle: 0.5 },
    order: ["pitch_rate", "roll_rate"],
    rates: {
      pitch_rate: { slot: "pitch.k_rate", candidate: { k: 0.06 }, target: { metric: "zeta_sp", value: 0.7 },
        full: { achieved: 0.7, ok: true, stable: true } },
      roll_rate: { slot: "roll.k_rate", candidate: { k: -0.11 }, target: { metric: "roll_lambda", value: 12 },
        full: { achieved: 11.5, ok: false, stable: true } },
    },
    attitude: { pitch_att: { slot: "pitch", kp: 1, ki: 0.2, passing: true } },
  };
  const r = basisReport(body);
  // 판정 수 곁에 자리마다 달성/목표·목표 대비 차 — 근소 미달(−4.2 %)이 「달성 0」으로만 읽히지 않게(쇼케이스 D7).
  // 카드 줄이 잘려도 남게 판정이 앞, 트림 조건 머리말이 뒤
  assert.match(r.summary,
    /^레이트 후보 달성 1\/2 \(ζ_sp 0\.7\/0\.7 \(\+0\.0 %\) · λ_roll 11\.5\/12 \(−4\.2 %\)\) · 자세 PI 통과 1\/1 · M0\.147_h0_f25 트림 — α/);
  assert.deepEqual(r.data.rates, [
    { slot: "pitch.k_rate", k: 0.06, achieved_ok: true, stable: true, metric: "zeta_sp", achieved: 0.7, target: 0.7, gap: 0 },
    { slot: "roll.k_rate", k: -0.11, achieved_ok: false, stable: true, metric: "roll_lambda", achieved: 11.5,
      target: 12, gap: (11.5 - 12) / 12 },
  ]);
  assert.deepEqual(r.data.case, body.case);
  assert.match(basisReport({ ok: false, reason_text: "트림 불가" }).error, /트림 불가/);
});

test("공학 수정 보고 — 값·리비전·변형 지문 전후와 δe_trim 낡음", () => {
  const plan = { ptr: "/aero/coefficients/CD/1/k", value: 0.035, base: 0.028, before: 0.028, changed: true };
  const r = editReport({
    variant: "eoir", delta: 0.007, plan,
    before: { revision: 3, fingerprint: "aaaa", baseFingerprint: "base" },
    after: { revision: 4, fingerprint: "bbbb", baseFingerprint: "base" },
    trim: { stale: true, staleVariants: ["eoir"] },
  });
  assert.deepEqual(r.data, {
    revision: 4, fingerprint_before: "aaaa", fingerprint_after: "bbbb", variant: "eoir",
    path: "/aero/coefficients/CD/1/k", cd0_base: 0.028, cd0_before: 0.028, cd0_after: 0.035, changed: true,
    base_fingerprint: "base", de_trim_stale_variants: ["eoir"],
  });
  assert.equal(r.summary, "형상 변형 eoir CD0 0.028 → 0.035 (기본 0.028 + 0.007) · 리비전 3 → 4 · "
    + "변형 지문 aaaa → bbbb · δe_trim 표 낡음(eoir)");
  // 이미 같은 값 — 저장하지 않았다고 말한다
  const same = editReport({ variant: "eoir", delta: 0.007, plan: { ...plan, before: 0.035, changed: false },
    before: { revision: 4, fingerprint: "bbbb", baseFingerprint: "base" }, after: null, trim: null });
  assert.equal(same.data.revision, 4);
  assert.equal(same.data.fingerprint_after, "bbbb");
  assert.match(same.summary, /이미 0\.035 — 저장하지 않았습니다/);
});

test("δe_trim 도출 보고 — 저장된 리비전, 미채택·미저장은 사유", () => {
  const derive = { ok: true, requirement: { mach: [0.1, 0.2] },
    alloc: { de_trim: { table: { axes: { mach: [0.1, 0.2] }, data: [0.2, 0.1] },
      provenance: { shortfall: 0, iterations: 2, excluded_trims: 5 } } } };
  const r = deriveReport({ derive, written: true, profile: { revision: 5 } });
  assert.equal(r.data.revision, 5);
  assert.deepEqual(r.data.table, { mach: [0.1, 0.2], data: [0.2, 0.1] });
  assert.match(r.summary, /^채택 — 리비전 5로 저장했습니다 · 검사 2점 · 요구 미달 0 · 보정 2회$/);
  // 조사는 번호의 소리를 따른다 — 쇼케이스 공학 수정 뒤 리비전 3에서 「리비전 3로」가 찍혔다(D17)
  assert.match(deriveReport({ derive, written: true, profile: { revision: 3 } }).summary, /^채택 — 리비전 3으로 저장했습니다 · /);
  assert.match(deriveReport({ derive, written: true, profile: { revision: 10 } }).summary, /^채택 — 리비전 10으로 저장했습니다/);
  assert.match(deriveReport({ derive, written: false, conflict_head: 7 }).error, /리비전 7/);
  assert.match(deriveReport({ derive: { ...derive, ok: false, reason_text: "트림 없음" } }).error, /트림 없음/);
  assert.match(deriveReport({}).error, /도출 결과가 없습니다/);
});

// 뷰(views/aircraft.js)는 DOM을 모듈 스코프에서 만져 import할 수 없다 — 배선은 **원문에서 읽는다**(blocks.test.js와 같은 가드)
test("기체 탭 배선 — 신호를 한 번 읽고, 계약 동작 6개를 싣고, 모르는 동작·잡 감시 끊김도 끝 보고", () => {
  const src = readFileSync(new URL("../views/aircraft.js", import.meta.url), "utf8");
  assert.equal(src.match(/takeCue\("aircraft"\)/g)?.length, 1, "render가 신호를 정확히 한 번 읽어야 한다");
  const table = src.match(/const CUE_ACTIONS = \{([\s\S]*?)\n {2}\};/)?.[1];
  assert.ok(table, "CUE_ACTIONS 표가 없다");
  const keys = [...table.matchAll(/^\s*(?:"([\w-]+)"|(\w+)):/gm)].map((m) => m[1] ?? m[2]);
  assert.deepEqual(keys.sort(),
    ["aero", "derive-de-trim", "edit-eoir-drag", "overview", "seed-basis", "stability"]);
  assert.match(src, /if \(!act\) unknownAction\(cue\)/, "모르는 동작을 조용히 무시한다");
  // 도출 잡: 걸면 started, 감시가 끊기면(seedDone이 오지 않는다) 그 자리에서 실패 보고 — 없으면 진행기가 시간 초과까지 기다린다
  assert.match(src, /reportCue\(cue, \{ phase: "started", jobId: job\.id \}\)/);
  assert.match(src, /onError: \(e\) => \{[\s\S]{0,400}?failCue\(watched\.cue/);
  // 공학 수정이 저장에 실패하면 신호가 친 편집을 거둔다 — 남기면 재시도가 「저장하지 않은 편집」에 막힌다
  assert.match(src, /if \(!out\.ok\) \{[\s\S]{0,600}?dirty: false[\s\S]{0,200}?throw new Error\(out\.error\)/);
});

test("기체 탭 배선 — 신호가 끝나면 결과 패널을 공용 revealPanel로 굴린다(부드럽게), 저장 머리말은 조사를 맞춘다", () => {
  const src = readFileSync(new URL("../views/aircraft.js", import.meta.url), "utf8");
  assert.match(src, /import \{ revealPanel \} from "\.\.\/lib\/reveal\.js";/);
  // 종전 굴리기는 scrollIntoView({block})를 바로 불러 순간 이동이었다(쇼케이스 D4 — 청중이 이동을 못 따라간다)
  assert.doesNotMatch(src, /scrollIntoView/);
  assert.match(src, /const reveal = \(node, block = "start"\) => revealPanel\(node, \{ block \}\);/);
  // 공력·안정성·산출 근거 — 각 동작이 보고할 값을 돌려주기 전에 자기 패널을 굴린다
  for (const [fn, node] of [["cueAero", "viewerBox"], ["cueStability", "stabilityBox"],
    ["cueSeedBasis", 'seedBox.querySelector("[data-seed-basis]")']]) {
    const body = src.match(new RegExp(`const ${fn} = async[\\s\\S]*?\\n {2}\\};`))?.[0];
    assert.ok(body, `${fn}가 없다`);
    const at = body.indexOf(`reveal(${node})`);
    assert.ok(at > 0 && at < body.lastIndexOf("return "), `${fn}: 결과 패널(${node})을 굴리지 않고 보고한다`);
  }
  // δe_trim 도출 잡 — 끝 보고 앞에서 도출 표 패널을 굴린다
  assert.match(src, /\n\s*revealPanel\(seedBox\);[^\n]*\n\s*reportCue\(cue, \{ phase: "done", summary: r\.summary, resultId: job\.result_id/);
  // 리비전 번호 뒤 조사를 글에 박지 않는다 — 3·6·10에서 「3로」가 된다(D17)
  assert.doesNotMatch(src, /리비전 \$\{[^}]*\}로/);
});
