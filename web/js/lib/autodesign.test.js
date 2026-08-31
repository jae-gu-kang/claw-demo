/** autodesign 순수 로직 검증 — 설정 페이로드, 점·판정 결합, 처방 그룹, 게인 채택. */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  actionCards,
  adoptBlockedText,
  adoptStorePayload,
  adoptWarnText,
  adoptable,
  buildConfig,
  coverageLines,
  effectText,
  evidenceLines,
  ledgerActionText,
  ledgerKindText,
  ledgerRows,
  ledgerTruncatedText,
  pointRows,
  reasonText,
  reliefLines,
  reportLine,
  resumable,
  resumeBlockedText,
  shortfallLines,
  statusCounts,
  statusRank,
  statusSeverity,
  statusText,
  trimLabel,
  tunedLines,
  verdictLegend,
  worstStatus,
} from "./autodesign.js";

const RESULT = {
  points: {
    points: [
      { name: "A", mach: 0.3, alt: 1000, fuel: 200, role: "anchor", trimmable: true },
      { name: "V", mach: 0.4, alt: 1000, fuel: 200, role: "validation", trimmable: true },
      { name: "B", mach: 0.5, alt: 1000, fuel: 200, role: "breakpoint", trimmable: null },
    ],
  },
  margin_out: {
    cases: {
      A: { loops: { pitch_att: { status: "ok" }, pitch_rate: { status: "warn" } } },
      V: { loops: { pitch_att: { status: "fail" } } },
    },
  },
  proposed_actions: [
    { id: "a1", verdict: "gain_interp_valley", case: "V", loop: "pitch_att",
      action: { type: "promote", to: "breakpoint" }, evidence: {} },
    { id: "a2", verdict: "structural_limit", case: "V", loop: "roll_att",
      action: { type: "escalate" }, evidence: {} },
  ],
  gain_export: {
    tables: { "pitch.kp": { kind: "poly", axis: "mach", segments: [] } },
    tables_resampled: {
      "pitch.kp": { axes: { mach: [0.3, 0.5] }, data: [-8, -2], extrapolate: "clip" },
    },
    constants: { "yaw.k_rate": 0.4 },
  },
};

test("buildConfig — 채운 것만 덮어쓰고 수치 목록을 파싱한다", () => {
  const cfg = buildConfig({
    mode: "auto", budgetPoints: "60", budgetIters: "3",
    nMach: "4", altsText: "0, 3000", fuelsText: "",
  });
  assert.deepEqual(cfg, {
    mode: "auto", budget_points: 60, budget_iters: 3, n_mach: 4, alts: [0, 3000],
  });
});

test("buildConfig — 잘못된 수치 목록은 던진다", () => {
  assert.throws(() => buildConfig({ mode: "gated", altsText: "abc" }));
});

test("worstStatus — fail > warn > na > ok", () => {
  assert.equal(worstStatus({ a: { status: "ok" }, b: { status: "warn" } }), "warn");
  assert.equal(worstStatus({ a: { status: "warn" }, b: { status: "fail" } }), "fail");
  assert.equal(worstStatus({}), null);
  assert.ok(statusRank("fail") > statusRank("ok"));
});

test("pointRows — 점과 검증 판정을 이름으로 결합한다", () => {
  const rows = pointRows(RESULT);
  assert.equal(rows.length, 3);
  const v = rows.find((r) => r.name === "V");
  assert.equal(v.role, "validation");
  assert.equal(v.status, "fail");
  const b = rows.find((r) => r.name === "B");
  assert.equal(b.status, null); // 마진맵에 없는 점 — 미판정으로 남긴다
});

test("actionCards — 승인 가능/에스컬레이션 분리, supersede 제외", () => {
  const withSuperseded = {
    ...RESULT,
    proposed_actions: [
      ...RESULT.proposed_actions,
      { id: "a3", verdict: "simple_deficit", case: "V", loop: "x",
        action: { type: "add_validation" }, superseded_by: "V→anchor" },
    ],
  };
  const cards = actionCards(withSuperseded);
  assert.deepEqual(cards.approvable.map((a) => a.id), ["a1"]); // a3은 supersede — 제외
  assert.deepEqual(cards.escalations.map((a) => a.id), ["a2"]);
});

test("adoptStorePayload — 재샘플 테이블을 기존 스토어 계약으로 낸다", () => {
  const p = adoptStorePayload(RESULT);
  assert.equal(p.scheduleOff, false);
  assert.deepEqual(Object.keys(p.tables), ["pitch.kp"]);
  assert.deepEqual(p.tables["pitch.kp"].axes.mach, [0.3, 0.5]);
  // 반출이 비면 스케줄 없음 신호
  const empty = adoptStorePayload({ gain_export: { tables_resampled: {} } });
  assert.equal(empty.tables, null);
  assert.equal(empty.scheduleOff, true);
});

test("adoptStorePayload — 상수 자리를 버리지 않는다 (검증한 형상 = 채택한 형상)", () => {
  const p = adoptStorePayload(RESULT);
  assert.deepEqual(p.constants, { "yaw.k_rate": 0.4 });
  // 전 자리가 상수로 접혀도 상수는 살아 있어야 한다 — 그때가 가장 위험하다
  const allConst = adoptStorePayload({
    gain_export: { tables_resampled: {}, constants: { "pitch.kp": -2, "roll.kp": 1 } },
  });
  assert.equal(allConst.tables, null);
  assert.equal(allConst.scheduleOff, true);
  assert.deepEqual(allConst.constants, { "pitch.kp": -2, "roll.kp": 1 });
  // 반출이 아예 없으면 빈 객체 (undefined 접근 금지)
  assert.deepEqual(adoptStorePayload({}).constants, {});
});

test("statusCounts — 미판정을 통과로 세지 않는다", () => {
  // status null은 "판정을 못 했다"이지 "합격"이 아니다 — 한 칸으로 뭉치면
  // 트림 불가·판정 불가 점이 ok 개수에 섞여 실행이 실제보다 건강해 보인다
  // A는 pitch_att ok + pitch_rate warn → 점 판정은 최악값 warn (worstStatus 규약)
  const c = statusCounts(pointRows(RESULT));
  assert.deepEqual(c, { ok: 0, warn: 1, fail: 1, na: 0, outside: 0, unjudged: 1 });
  assert.deepEqual(statusCounts(undefined),
    { ok: 0, warn: 0, fail: 0, na: 0, outside: 0, unjudged: 0 });
});

test("엔벨로프 경계 점은 판정 칸이 아니라 자기 칸에 센다", () => {
  // 엔진이 그 점의 실패를 처방 목록에서 뺀다(schedmap.outside_envelope). 화면이
  // 그걸 fail로 세면 "실패 N건"과 처방 카드 수가 어긋나 사용자가 사라진 카드를 찾는다.
  // 그렇다고 빼고 안 세면 조용한 누락이므로 자기 칸이 필요하다
  const withOutside = {
    ...RESULT,
    margin_out: {
      cases: {
        ...RESULT.margin_out.cases,
        V: { outside_envelope: true, loops: { pitch_att: { status: "fail" } } },
      },
    },
  };
  const rows = pointRows(withOutside);
  assert.deepEqual(statusCounts(rows),
    { ok: 0, warn: 1, fail: 0, na: 0, outside: 1, unjudged: 1 });
  const v = rows.find((r) => r.name === "V");
  assert.equal(v.outsideEnvelope, true);
  assert.equal(v.status, "fail"); // 수치는 남긴다 — 경계의 마진은 자료다
});

test("trimLabel — 미수렴과 엔벨로프 경계를 한 낱말로 뭉치지 않는다", () => {
  assert.equal(trimLabel({ trimmable: true }), "OK");
  assert.equal(trimLabel({ trimmable: null }), "미판정");
  assert.equal(trimLabel({ trimmable: false }), "미수렴");
  // 엔벨로프 경계는 trimmable=false로도 오지만 트림해는 있다 — 종전엔 둘 다 "불가"였다
  assert.equal(trimLabel({ trimmable: false, outsideEnvelope: true }), "엔벨로프 경계");
  assert.equal(trimLabel(undefined), "미판정");
});

test("verdictLegend — 기준 수치를 결과에서 읽어 문장에 박는다", () => {
  const lines = verdictLegend({
    pm_min_deg: 45, gm_min_db: 6, gm_good_db: 8, zeta_min: 0.3, zeta_good: 0.5,
  });
  assert.deepEqual(lines.map((l) => l.key), ["ok", "warn", "fail", "na"]);
  const ok = lines.find((l) => l.key === "ok").text;
  const warn = lines.find((l) => l.key === "warn").text;
  // ok는 **목표선**(gm_good), warn은 합격선~목표선 구간을 말해야 한다.
  // 여기가 어긋나면 화면이 warn을 "곧 실패"로 오해하게 설명한다
  assert.match(ok, /GM ≥ 8 dB/);
  assert.match(warn, /GM 6~8 dB/);
  assert.match(lines.find((l) => l.key === "fail").text, /GM < 6 dB/);
  // 기준을 바꾸면 문장도 따라가야 한다 — 기본값을 웹에 다시 적으면 안 되는 이유
  const strict = verdictLegend({ pm_min_deg: 50, gm_min_db: 8, gm_good_db: 12 });
  assert.match(strict.find((l) => l.key === "ok").text, /PM ≥ 50° · GM ≥ 12 dB/);
});

// ── 재개·확정 게이트 ───────────────────────────────────────────────────

test("resumable — 서버가 재개를 받는 상태만 true (409 나는 버튼을 그리지 않는다)", () => {
  // routes/design.py: awaiting_approval·cancelled만 재개, 나머지는 409
  assert.equal(resumable({ status: "awaiting_approval" }), true);
  assert.equal(resumable({ status: "cancelled" }), true);
  // budget_exhausted는 **처방 카드가 남은 채로** 끝나는 상태다 — 종전 화면은 카드
  // 수만 보고 "승인 반영 재개"를 그렸고, 누르면 409만 돌아왔다
  assert.equal(resumable({ status: "budget_exhausted" }), false);
  assert.equal(resumable({ status: "escalated" }), false);
  assert.equal(resumable({ status: "converged" }), false);
  assert.equal(resumable({ status: "nothing_verified" }), false);
  assert.equal(resumable(undefined), false);
});

test("resumeBlockedText — 재개 불가면 사유가 있고, 가능하면 null", () => {
  assert.equal(resumeBlockedText({ status: "cancelled" }), null);
  assert.equal(resumeBlockedText({ status: "awaiting_approval" }), null);
  assert.match(resumeBlockedText({ status: "budget_exhausted" }), /이터 상한/);
  assert.match(resumeBlockedText({ status: "escalated" }), /상위 설계/);
  // 모르는 상태도 빈칸으로 두지 않는다 — 버튼도 설명도 없는 화면이 가장 나쁘다
  assert.match(resumeBlockedText({ status: "wat" }), /wat/);
  assert.match(resumeBlockedText({}), /없음/);
});

test("adoptable — 판정이 난 자리가 있어야 게인을 확정한다", () => {
  // failures=0은 통과의 근거가 못 된다: 트림 전량 미수렴·빈 격자·엔벨로프 밖 격자는
  // 실패 목록도 비어 있다(engine judged_count). 그 게인을 확정하면 아무것도 검증하지
  // 않은 게인이 시뮬·Autocode·구조도의 정본이 된다
  assert.equal(adoptable({ judged: 12, failures: 0 }), true);
  assert.equal(adoptable({ judged: 0, failures: 0 }), false);
  assert.equal(adoptable({ failures: 0 }), false); // judged 없는 구형 결과
  assert.equal(adoptable(undefined), false);
});

test("adoptBlockedText — 확정 불가 사유는 '미검증'과 '구형 결과'를 가른다", () => {
  assert.equal(adoptBlockedText({ judged: 3 }), null);
  assert.match(adoptBlockedText({ judged: 0 }), /아무것도 검증하지 않았다/);
  // judged 필드 자체가 없는 결과를 "0건 판정"이라고 단정하면 거짓말이 된다
  assert.match(adoptBlockedText({ failures: 0 }), /구형 결과/);
});

// ── 종료 상태 문구 ─────────────────────────────────────────────────────

test("statusText — 6종 종료 상태 + running에 뜻과 다음 행동이 있다", () => {
  for (const s of ["converged", "escalated", "budget_exhausted", "awaiting_approval",
    "nothing_verified", "cancelled", "running"]) {
    assert.equal(typeof statusText(s), "string");
    assert.ok(statusText(s).length > 10, s);
  }
  // 이 셋은 오독의 대가가 커서 문구를 고정한다
  assert.match(statusText("nothing_verified"), /실패가 없는 게 아니라 볼 것이 없었다/);
  assert.match(statusText("nothing_verified"), /게인을 확정하면 안 된다/);
  assert.match(statusText("escalated"), /게인·격자로는 풀리지 않는다/);
  assert.match(statusText("budget_exhausted"), /이터레이션 예산을 다 썼다/);
  assert.match(statusText("bogus"), /알 수 없는 상태/);
});

test("statusSeverity — nothing_verified는 회색(미판정)이 아니라 실패 쪽이다", () => {
  assert.equal(statusSeverity("converged"), "ok");
  assert.equal(statusSeverity("awaiting_approval"), "warn");
  // 종전엔 converged/awaiting_approval 외 전부 na였다 — 미검증이 '미판정 회색'으로
  // 뜨면 통과와 구별이 흐려진다
  assert.equal(statusSeverity("nothing_verified"), "fail");
  assert.equal(statusSeverity("escalated"), "fail");
  assert.equal(statusSeverity("budget_exhausted"), "fail");
  assert.equal(statusSeverity("cancelled"), "na");
});

// ── 상태 줄 ────────────────────────────────────────────────────────────

test("reportLine — 0인 항목은 생략하되 판정·실패는 0이어도 낸다", () => {
  const line = reportLine({
    status: "converged", stage: "DONE", iterations: 2, n_points: 24,
    points: { anchor: 5, breakpoint: 7, validation: 12 },
    failures: 0, judged: 48, outside_envelope: 0, tuned: 12, skipped: [],
    escalations: 0, ineffective_actions: 0, sealed: 0, fit_tighten: 1,
    criteria_fingerprint: "abcdef0123456789",
  });
  const text = line.join(" · ");
  // "실패 0"이 통과인지 미검증인지는 판정 수가 가른다 — 둘 다 항상 보인다
  assert.match(text, /판정 48/);
  assert.match(text, /실패 0/);
  assert.match(text, /튜닝 12/);
  assert.match(text, /적합 조이기 1/);
  assert.doesNotMatch(text, /엔벨로프 밖/); // 0 — 생략
  assert.doesNotMatch(text, /무효 처방/);
  assert.doesNotMatch(text, /봉인/);
  assert.doesNotMatch(text, /건너뜀/);
  assert.match(text, /기준 지문 abcdef01/); // 해시는 앞 8자만
});

test("reportLine — 미검증 실행은 '판정 0'이 줄에 남는다", () => {
  const text = reportLine({ status: "nothing_verified", judged: 0, failures: 0 },
    9).join(" · ");
  assert.match(text, /판정 0/);
  assert.match(text, /실패 0/);
  assert.match(text, /점 9/); // n_points 없으면 표 행 수로 폴백
});

test("reportLine — 신규 카운터와 건너뛴 점 이름", () => {
  const text = reportLine({
    outside_envelope: 3, escalations: 1, ineffective_actions: 2, sealed: 1,
    skipped: ["p1", "p2", "p3", "p4", "p5"],
  }).join(" · ");
  assert.match(text, /엔벨로프 밖 3/);
  assert.match(text, /에스컬레이션 1/);
  assert.match(text, /무효 처방 2/);
  assert.match(text, /봉인 1/);
  // 이름을 다 늘어놓으면 줄이 넘친다 — 앞 셋만 보이고 나머지는 수로
  assert.match(text, /튜닝 건너뜀 5 \(p1, p2, p3 외 2\)/);
});

// ── 사유 코드 ──────────────────────────────────────────────────────────

test("reasonText — 서버 맵이 정본, 없으면 폴백, 그것도 없으면 코드 그대로", () => {
  assert.equal(reasonText("capped", { capped: "서버 문구" }), "capped — 서버 문구");
  assert.match(reasonText("capped"), /^capped — 작동기·지연 포함 폐루프 안정 경계/);
  assert.match(reasonText("zero_design"), /설계 게인이 0이라/);
  assert.match(reasonText("bandwidth_collapse"), /교차 주파수가 하한 아래/);
  assert.match(reasonText("margin_floor"), /지연·작동기 예산이 병목/);
  assert.match(reasonText("rescued"), /통과/);
  // na_no_crossover — 교차 없음을 "통과"로 읽지 않게 하는 사유다. 폴백에 없으면
  // 서버 사전이 안 왔을 때(기본값 조회 실패) 코드만 뜬다
  assert.match(reasonText("na_no_crossover"), /통과가 아니라 판정 불가다/);
  // 모르는 코드를 삼키면 엔진에 사유가 늘어도 화면이 조용해진다 — 코드는 남긴다
  assert.equal(reasonText("brand_new_code"), "brand_new_code");
  assert.equal(reasonText(null), null);
});

// ── 요구 대비 부족 ─────────────────────────────────────────────────────

test("shortfallLines — 요구선·달성·부족을 함께 낸다 (이번 작업의 핵심)", () => {
  const lines = shortfallLines({
    pm_deg: { required: 45, achieved: 38.2, deficit: 6.8, deficit_frac: 6.8 / 45 },
  });
  assert.equal(lines.length, 1);
  // 종전 화면은 "현재 PM 38.2°"만 말했다 — 요구선도 부족량도 없으면 그 수치가
  // 합격인지 미달인지, 얼마나 모자란지를 화면만 보고는 알 수 없다
  assert.match(lines[0].text, /요구 45°/);
  assert.match(lines[0].text, /달성 38.2°/);
  assert.match(lines[0].text, /부족 6.80°/); // 표기 정밀도는 dom.fmt와 같은 정책
  assert.equal(lines[0].kind, "short");
});

test("shortfallLines — 음수 부족은 여유, null은 판정 불가(통과 아님)", () => {
  const lines = shortfallLines({
    gm_db: { required: 6, achieved: 9.3, deficit: -3.3, deficit_frac: -0.55 },
    zeta: { required: 0.3, achieved: null, deficit: null, deficit_frac: null },
  });
  const gm = lines.find((l) => l.key === "gm_db");
  assert.equal(gm.kind, "spare");
  assert.match(gm.text, /여유 3.30 dB/);
  assert.doesNotMatch(gm.text, /부족/);
  const z = lines.find((l) => l.key === "zeta");
  assert.equal(z.kind, "na");
  // deficit null을 "부족 0"으로 그리면 교차 없음이 합격으로 보인다
  assert.match(z.text, /판정 불가/);
  assert.match(z.text, /통과가 아니다/);
});

test("shortfallLines — 판정 불가가 맨 앞, 그다음 부족 큰 순 (엔진 severity와 같은 규약)", () => {
  const lines = shortfallLines({
    gm_db: { required: 6, achieved: 5, deficit: 1, deficit_frac: 0.1667 },
    pm_deg: { required: 45, achieved: 30, deficit: 15, deficit_frac: 0.3333 },
    zeta: { required: 0.3, achieved: null, deficit: null, deficit_frac: null },
  });
  assert.deepEqual(lines.map((l) => l.key), ["zeta", "pm_deg", "gm_db"]);
  assert.deepEqual(shortfallLines(undefined), []);
});

// ── 자유 게인 결과·반영 효과·완화 프로브 ────────────────────────────────

test("tunedLines — 자리 status·사유·달성 지표를 낸다", () => {
  const lines = tunedLines({
    status: "infeasible", reason: "margin_floor", point_status: "ok",
    judged: "fail", target: 12, achieved: { pm_deg: 31.2, gm_db: 5.1 },
    notes: ["roll.kp/ki: 대역폭 바닥"],
  });
  const text = lines.join(" | ");
  assert.match(text, /자유 게인 튜닝 불가/);
  assert.match(text, /margin_floor — 대역폭을 바닥까지/);
  assert.match(text, /달성 PM 31.2° · GM 5.10 dB/);
  // 점 단위 status는 자리 status와 다를 때만 참고로 — 뭉치면 실행 가능한 처방이
  // 적용 버튼 없는 에스컬레이션처럼 읽힌다
  assert.match(text, /점 단위 ok \(참고/);
  assert.match(text, /튜너 메모: roll.kp\/ki/);
  assert.deepEqual(tunedLines(null), []);
});

test("effectText — 반영했는데 판정이 안 움직인 처방을 드러낸다", () => {
  const before = { status: "fail", severity: 0.22 };
  const same = effectText({ before, after: { status: "fail", severity: 0.22 }, changed: false });
  assert.match(same, /반영했으나 판정이 그대로다/);
  assert.match(same, /듣지 않았다/);
  const moved = effectText({ before, after: { status: "ok", severity: null }, changed: true });
  assert.match(moved, /반영 효과 fail \(심각도 0.220\) → ok/);
  // 아직 채점 전(다음 VERIFY에서 잰다)을 "효과 없음"으로 그리면 거짓이다
  assert.match(effectText({ before }), /다음 검증에서 잰다/);
  assert.equal(effectText(null), null);
});

test("reliefLines — 무엇을 얼마에서 얼마로 바꿨는지까지 낸다", () => {
  const lines = reliefLines([
    { change: "delay_s", label: "지연 제거", from: 0.035, to: 0, resolves: true },
    { change: "actuator_wn", label: "작동기 대역폭 ×3", from: 30, to: 90,
      resolves: false, reason: "target_unreached" },
  ]);
  // label과 통과 여부만 그리면 "×3"이 30→90인지 10→30인지 알 수 없어, 예산을
  // 얼마로 잡아야 하는지가 화면에서 안 나온다
  assert.match(lines[0].text, /지연 제거 \(delay_s 0.0350 → 0\) → 통과/);
  assert.equal(lines[0].resolves, true);
  assert.match(lines[1].text, /작동기 대역폭 ×3 \(actuator_wn 30 → 90\) → 여전히 미달/);
  assert.match(lines[1].text, /사유 target_unreached — /);
  assert.deepEqual(reliefLines(undefined), []);
});

// ── 카드 근거 묶음 ─────────────────────────────────────────────────────

test("evidenceLines — 카드에 실려 오는데 버려지던 것을 전부 줄로 낸다", () => {
  const ev = evidenceLines({
    verdict: "structural_limit",
    severity: 0.31,
    action: { type: "escalate", note: "작동기 대역폭 예산을 늘릴 것" },
    sealed: "2회 반영해도 판정이 안 바뀌었다",
    skipped: "이미 anchor — 승격 불필요",
    effect: { before: { status: "fail", severity: 0.31 },
      after: { status: "fail", severity: 0.31 }, changed: false },
    evidence: {
      current: { pm_deg: 38.2, gm_db: 7.1, zeta: null },
      shortfall: { pm_deg: { required: 45, achieved: 38.2, deficit: 6.8, deficit_frac: 0.151 } },
      tuned: { status: "infeasible", reason: "capped", judged: "fail" },
      bottleneck: {
        wc_over_actuator: 0.4, delay_phase_deg_at_wc: 24.1, note: "지연 제거 시 통과",
        relief: [{ change: "delay_s", label: "지연 제거", from: 0.035, to: 0, resolves: true }],
      },
    },
  });
  const head = ev.head.join(" · ");
  assert.match(head, /현재 PM 38.2°/);
  assert.match(head, /심각도 0.31/); // 종전엔 계산돼 오고도 안 그려졌다
  assert.match(head, /ωc\/작동기 0.4/);
  assert.equal(ev.shortfall.length, 1);
  assert.match(ev.shortfall[0].text, /요구 45°/);
  assert.ok(ev.tuned.some((t) => /capped — /.test(t)));
  assert.equal(ev.relief.length, 1);
  assert.equal(ev.effect.ineffective, true);
  // 분류기 자신의 설명(action.note)과 병목 결론(bottleneck.note) 둘 다 나온다
  assert.deepEqual(ev.notes, ["지연 제거 시 통과", "작동기 대역폭 예산을 늘릴 것"]);
  assert.equal(ev.flags.length, 2); // 봉인 · 건너뜀
  assert.ok(ev.flags[0].startsWith("봉인:"));
});

test("evidenceLines — evidence가 비어도 터지지 않고 빈 묶음을 낸다", () => {
  const ev = evidenceLines({ evidence: {} });
  assert.deepEqual(ev.head, []);
  assert.deepEqual(ev.shortfall, []);
  assert.deepEqual(ev.tuned, []);
  assert.deepEqual(ev.relief, []);
  assert.equal(ev.effect, null);
  assert.deepEqual(ev.notes, []);
  assert.deepEqual(ev.flags, []);
  assert.deepEqual(evidenceLines(undefined).head, []);
});

test("evidenceLines — 부호 뒤집힘은 맨 앞에 온다", () => {
  // 마진 수치는 방향 보정 후 값이라 PM 116°처럼 건강해 보인다 — 왜 fail인지가
  // 이 줄에만 있다
  const ev = evidenceLines({
    evidence: { sign_flip: { slots: ["roll.kp"] }, current: { pm_deg: 116, gm_db: 12 } },
  });
  assert.match(ev.head[0], /부호 반대: roll.kp/);
});

// ── 요구 조정 폼 ───────────────────────────────────────────────────────

test("buildConfig — criteria·targets 중첩 덮어쓰기는 채운 칸만", () => {
  const cfg = buildConfig({
    mode: "gated",
    criteria: { pm_min_deg: "50", gm_min_db: "", zeta_min: " " },
    targets: { pm_deg: "55", gm_db: "" },
    actuatorWn: "40", actuatorZeta: "", delayS: "0.05",
  });
  assert.deepEqual(cfg, {
    mode: "gated",
    actuator_wn: 40, delay_s: 0.05,
    criteria: { pm_min_deg: 50 },
    targets: { pm_deg: 55 },
  });
});

test("buildConfig — 중첩이 전부 비면 키 자체를 안 보낸다 (빈 dict 금지)", () => {
  const cfg = buildConfig({ mode: "auto", criteria: { pm_min_deg: "" }, targets: {} });
  assert.deepEqual(cfg, { mode: "auto" });
  assert.equal("criteria" in cfg, false);
  assert.equal("targets" in cfg, false);
});

test("buildConfig — 중첩 칸의 비수치는 어느 칸인지 밝히며 던진다", () => {
  assert.throws(() => buildConfig({ criteria: { pm_min_deg: "쉰" } }),
    /criteria.pm_min_deg/);
  assert.throws(() => buildConfig({ targets: { gm_db: "abc" } }), /targets.gm_db/);
  assert.throws(() => buildConfig({ actuatorWn: "xx" }), /actuator_wn/);
});

test("shortfallLines — 비유한값은 문자열로 온다, 숫자로 다루면 최악이 초록이 된다", () => {
  // 엔진은 nan(=null, 판정 불가)과 ±inf(=무한 여유/최악)를 **구별해서** 낸다.
  // ±inf는 "inf"/"-inf" 문자열이다(serialize.py). 숫자로 다루면 `"inf" > 0`이
  // false라 GM −∞(있을 수 있는 최악의 이득여유)가 "여유"로 초록칠되고,
  // Math.abs("−inf")가 NaN이 되어 부족량과 정렬 키가 통째로 망가진다.
  const spare = shortfallLines({
    gm_db: { required: 6, achieved: "inf", deficit: "-inf", deficit_frac: null },
  });
  assert.equal(spare[0].kind, "spare");
  assert.match(spare[0].text, /달성 ∞ dB · 여유 ∞ dB/);
  assert.ok(!/NaN/.test(spare[0].text));

  const worst = shortfallLines({
    gm_db: { required: 6, achieved: "-inf", deficit: "inf", deficit_frac: null },
  });
  assert.equal(worst[0].kind, "short", "GM −∞를 여유로 칠했다");
  assert.match(worst[0].text, /부족 ∞ dB/);
  assert.ok(!/NaN/.test(worst[0].text));

  // 무한 부족이 유한한 부족보다 앞에 선다 (정렬 키가 NaN이 되면 순서가 무너진다)
  const mixed = shortfallLines({
    pm_deg: { required: 45, achieved: 40, deficit: 5, deficit_frac: 0.111 },
    gm_db: { required: 6, achieved: "-inf", deficit: "inf", deficit_frac: null },
  });
  assert.deepEqual(mixed.map((r) => r.key), ["gm_db", "pm_deg"]);
});

test("tunedLines — 달성 줄은 아는 지표만 적는다 (엔진 레코드는 메타를 함께 싣는다)", () => {
  // 엔진의 achieved는 지표만 담은 dict가 아니다. 전부 훑으면 한 줄이
  // "PM 38.2° · GM 7.10 dB · wcg 4.21 · wcp 2.13 · orientation 1 · wc_att 1.22 ·
  //  wc0 2.44 · wc_fallback false · target_pm_deg 50 · … · reason margin_floor"
  // 이 되고, 사유 코드는 바로 위에서 한국어로 푼 것을 원문으로 한 번 더 찍는다.
  const real = {  // tune._tune_att이 실제로 만드는 모양
    status: "infeasible", reason: "margin_floor", judged: "fail",
    achieved: {
      pm_deg: 38.2, gm_db: 7.1, wcg: 4.21, wcp: 2.13, orientation: 1,
      wc_att: 1.22, wc0: 2.44, wc_fallback: false,
      target_pm_deg: 50, target_gm_db: 8, target_wc_frac: 0.2, reason: "margin_floor",
    },
  };
  const line = tunedLines(real, {}).join(" / ");
  assert.match(line, /달성 PM 38\.2° · GM 7\.10 dB$/);
  for (const noise of ["orientation", "wc_fallback", "target_pm_deg", "wcg"]) {
    assert.ok(!line.includes(noise), `메타 ${noise}가 달성 줄에 샜다`);
  }
  // 레이트 자리도 같은 문제 — participation·bracket_growth 등이 섞이면 안 된다
  const rate = tunedLines({
    status: "infeasible", reason: "target_unreached", judged: "warn",
    achieved: {
      kind: "bandwidth", roll_lambda: 8.65, target: 12, wc: 15.7, capped: null,
      reached: false, bracket_growth: 3, unstable: false, participation: 0.93,
    },
  }, {}).join(" / ");
  assert.match(rate, /λ 8\.65 rad\/s/);
  for (const noise of ["bracket_growth", "participation", "capped"]) {
    assert.ok(!rate.includes(noise), `메타 ${noise}가 달성 줄에 샜다`);
  }
});

// ── 미달 원장 ──────────────────────────────────────────────────────────

const LEDGER_BODY = {
  // failures=0인데 미달은 있다 — 처방이 나오는 실패만 세면 이 실행은 무결해 보인다
  report: { status: "converged", judged: 40, failures: 0, ledger_size: 5 },
  ledger: [
    { point: "M0.8_h5000", loop: null, kind: "not_trimmed", status: null,
      reason: null, severity: null, shortfall: {}, target: null,
      note: "트림 미수렴 — 이 점에서는 아무것도 못 봤다", action: null },
    { point: "M0.35_h0_f200", loop: "roll_att", kind: "tune", status: "warn",
      reason: "capped", severity: 0.223,
      shortfall: { pm_deg: { required: 45, achieved: 38.2, deficit: 6.8,
        deficit_frac: 0.151 } },
      target: 12, note: "튜닝이 설계 목표 PM에 못 갔다",
      action: null },
    { point: "M0.6_h3000", loop: "pitch_att", kind: "ineffective", status: "fail",
      reason: null, severity: 0.11, shortfall: {}, target: null,
      note: "같은 처방을 두 번 반영했으나 판정이 그대로다",
      action: { id: "a7", verdict: "gain_interp_valley", type: "promote",
        applied: true, changed: false, sealed: "2회 무효" } },
    { point: "M0.9_h9000", loop: null, kind: "skipped", status: null,
      reason: null, severity: 0.02, shortfall: {}, target: null,
      note: "튜닝을 건너뛴 점", action: null },
  ],
};

test("ledgerRows — 원장이 없어도 안 터진다 (원장 이전의 구형 결과)", () => {
  // 화면은 원장 절을 건너뛰기만 하면 된다. 여기서 던지면 결과 조회 전체가 죽어
  // 구형 결과를 아예 못 연다
  assert.deepEqual(ledgerRows({}), []);
  assert.deepEqual(ledgerRows(undefined), []);
  assert.deepEqual(ledgerRows({ ledger: [] }), []);
  assert.deepEqual(ledgerRows(RESULT), []);
});

test("ledgerRows — 실패 0인 실행에도 미달이 남는다 (이 작업의 핵심)", () => {
  // 처방 카드가 붙는 실패만 그리면 이 결과는 화면에서 무결해 보인다 — 트림 미수렴,
  // 튜닝 목표 미달, 무효 처방, 건너뛴 점이 전부 카드 없는 미달이기 때문이다
  const rows = ledgerRows(LEDGER_BODY);
  assert.equal(LEDGER_BODY.report.failures, 0);
  assert.ok(rows.length > 0, "실패 0이라고 원장까지 비는 것은 아니다");
  assert.equal(rows.length, 4);
});

test("ledgerRows — 못 잰 심각도(null)가 맨 앞 (엔진 severity 규약과 같음)", () => {
  const rows = ledgerRows({
    ledger: [
      { point: "p1", kind: "tune", severity: 0.1 },
      { point: "p2", kind: "verify", severity: null },
      { point: "p3", kind: "verify", severity: 0.5 },
      // 비유한값은 문자열로 온다 — 숫자로 다루면 최악(∞ 부족)이 꼬리에 가라앉는다
      { point: "p4", kind: "verify", severity: "inf" },
    ],
  });
  assert.deepEqual(rows.map((r) => r.point), ["p2", "p4", "p3", "p1"]);
  // 못 잰 것을 0으로 그리면 최악이 최선처럼 보인다
  assert.equal(rows[0].severityText, "못 잼");
  assert.equal(rows[1].severityText, "∞");
  assert.equal(rows[3].severityText, "0.100");
});

test("ledgerRows — 표시용 필드: 종류 라벨·사유·부족 한 줄·처방 효과", () => {
  const rows = ledgerRows(LEDGER_BODY, { capped: "서버 문구" });
  const tune = rows.find((r) => r.kind === "tune");
  assert.equal(tune.kindLabel, "튜닝 목표 미달");
  assert.match(tune.kindText, /합격선은 넘길 수 있다/); // 다음에 뭘 할지가 있다
  assert.equal(tune.reasonLine, "capped — 서버 문구"); // 서버 사전이 정본
  // 부족은 가장 심각한 지표 하나만 — 표 한 칸이다
  assert.match(tune.shortfallLine, /요구 45° · 달성 38.2° · 부족 6.80°/);
  assert.equal(tune.shortfallKind, "short");
  assert.equal(tune.severityText, "0.223");
  assert.equal(tune.actionLine, null); // 처방 없는 미달 — 이런 행이 더 많다

  const bad = rows.find((r) => r.kind === "ineffective");
  assert.match(bad.actionLine, /게인 보간 valley/); // verdict는 한국어로
  assert.match(bad.actionLine, /반영했으나 판정이 그대로다/);
  assert.match(bad.actionLine, /봉인: 2회 무효/);

  const nt = rows.find((r) => r.kind === "not_trimmed");
  assert.equal(nt.loop, null); // 점 단위 항목 — 자리가 없다
  assert.equal(nt.shortfallLine, null);
  assert.match(nt.note, /아무것도 못 봤다/);
});

test("ledgerRows — 사유 줄과 같은 문장인 메모는 두 번 뜨지 않는다", () => {
  // 엔진의 tune 행은 note에 사유 문구를 그대로 넣는다(REASON_TEXT[reason]).
  // 사유 줄이 "capped — 서버 문구"면 표 한 칸에 같은 문장이 두 번 남는다
  const map = { capped: "서버 문구" };
  const [same] = ledgerRows({
    ledger: [{ point: "p", kind: "tune", reason: "capped", note: "서버 문구" }] }, map);
  assert.equal(same.reasonLine, "capped — 서버 문구");
  assert.equal(same.noteLine, null);
  assert.equal(same.note, "서버 문구"); // 원문은 남긴다 — 지우는 건 표시뿐이다
  // 다른 문장이면 그대로 보인다 — 겹칠 때만 접는다
  const [other] = ledgerRows({
    ledger: [{ point: "p", kind: "tune", reason: "capped", note: "이터 3에서 포기" }] }, map);
  assert.equal(other.noteLine, "이터 3에서 포기");
  // 사유가 없는 종류는 메모가 유일한 설명이다
  const [only] = ledgerRows({
    ledger: [{ point: "p", kind: "not_trimmed", note: "트림 미수렴" }] });
  assert.equal(only.reasonLine, null);
  assert.equal(only.noteLine, "트림 미수렴");
});

test("ledgerRows — 튜닝 행은 목표·달성으로 부족 칸을 채운다 (빈칸으로 두지 않는다)", () => {
  // 엔진 tune 행에는 shortfall이 없다(검증 항목이 아니다) — 대신 target·achieved가
  // 실려 온다. 그 칸을 비우면 "얼마나 모자란가"가 원장에서 사라진다
  const [row] = ledgerRows({
    ledger: [{ point: "p", loop: "roll_rate", kind: "tune", status: "warn",
      reason: "target_unreached", severity: null, shortfall: {}, target: 12,
      achieved: { kind: "bandwidth", roll_lambda: 8.65, wc: 15.7, reached: false,
        bracket_growth: 3, participation: 0.93 } }],
  });
  assert.match(row.shortfallLine, /목표 12 · 달성 λ 8\.65 rad\/s/);
  // 달성 줄에 조성 메타가 새면 한 칸이 덤프가 된다 (tunedLines와 같은 규약)
  for (const noise of ["bracket_growth", "participation", "wc "]) {
    assert.ok(!row.shortfallLine.includes(noise), `메타 ${noise}가 샜다`);
  }
  // 부족량을 잰 것이 아니므로 빨강(short)으로 칠하지 않는다
  assert.equal(row.shortfallKind, null);
});

test("ledgerRows — 부족 한 줄은 판정 불가를 먼저 고른다", () => {
  // 지표가 여럿이면 "가장 심각한 하나"가 표에 남는다. 못 잰 지표가 있는데 잰
  // 지표를 대표로 세우면, 그 행은 실제보다 덜 나빠 보인다
  const [row] = ledgerRows({
    ledger: [{ point: "p", kind: "verify", status: "fail", severity: null,
      shortfall: {
        pm_deg: { required: 45, achieved: 30, deficit: 15, deficit_frac: 0.333 },
        zeta: { required: 0.3, achieved: null, deficit: null, deficit_frac: null },
      } }],
  });
  assert.equal(row.shortfallKind, "na");
  assert.match(row.shortfallLine, /판정 불가/);
});

test("ledgerRows — 모르는 종류도 코드 그대로 남는다 (조용히 사라지지 않는다)", () => {
  // 엔진에 종류가 늘면 화면은 그것을 모른다. 그때 행을 버리거나 라벨을 비우면
  // 새로 생긴 미달이 화면에서만 존재하지 않게 된다 — 가장 나쁜 실패 모드다
  const [row] = ledgerRows({
    ledger: [{ point: "p", loop: "roll_att", kind: "quantization_loss",
      status: "warn", severity: 0.4 }],
  });
  assert.equal(row.kind, "quantization_loss");
  assert.equal(row.kindLabel, "quantization_loss");
  assert.match(row.kindText, /quantization_loss/);
  assert.match(row.kindText, /모르는 종류/);
  assert.equal(row.tone, "warn"); // 색은 status로 폴백 — 회색으로 숨기지 않는다
});

test("ledgerTone — 종류가 먼저, 그다음 판정 (무효 처방은 따로 강조)", () => {
  const tone = (r) => ledgerRows({ ledger: [r] })[0].tone;
  assert.equal(tone({ kind: "verify", status: "fail" }), "fail");
  assert.equal(tone({ kind: "verify", status: "warn" }), "warn");
  assert.equal(tone({ kind: "not_trimmed", status: null }), "fail");
  // 튜닝 목표 미달·판정 불가는 실패가 아니다 — 빨강으로 칠하면 합격선 미달과 섞인다
  assert.equal(tone({ kind: "tune", status: "warn" }), "warn");
  assert.equal(tone({ kind: "unjudged", status: "na" }), "warn");
  // 설계 대상 밖은 회색 — 처방·수렴 판정에서 빠진 자리다
  assert.equal(tone({ kind: "outside_envelope", status: "fail" }), "na");
  assert.equal(tone({ kind: "skipped", status: null }), "na");
  // 무효 처방은 미달이면서 예산을 태운 처방이라 따로 눈에 띄어야 한다
  assert.equal(tone({ kind: "ineffective", status: "fail" }), "ineffective");
});

test("ledgerActionText — 반영 여부와 효과가 같은 줄에 있다", () => {
  assert.equal(ledgerActionText(null), null);
  assert.match(ledgerActionText({ verdict: "simple_deficit", applied: false }),
    /미반영 — 승인하면 반영된다/);
  assert.match(ledgerActionText({ verdict: "simple_deficit", applied: true, changed: true }),
    /반영 후 판정이 움직였다/);
  // changed가 아직 없는 것(채점 전)을 "효과 없음"으로 그리면 거짓이다
  assert.match(ledgerActionText({ verdict: "simple_deficit", applied: true }),
    /다음 검증에서 잰다/);
  // verdict를 모르면 코드 그대로 (VERDICT_LABEL을 못 찾았다고 칸을 비우지 않는다)
  assert.match(ledgerActionText({ verdict: "new_verdict", applied: false }), /new_verdict/);
});

test("ledgerTruncatedText — 잘린 원장을 '이게 전부'로 그리지 않는다", () => {
  // 저장물은 severity 상위 N행만 싣는다(routes/design.py MAX_LEDGER_ROWS). 조용히
  // 잘린 원장은 못 맞춘 것이 그것뿐이라고 말하는 목록이 된다
  const body = { ledger: [{ point: "p", kind: "verify", severity: 0.5 }],
    ledger_truncated: { kept: 1, total: 12 }, report: { ledger_size: 12 } };
  const t = ledgerTruncatedText(body);
  assert.match(t, /원장 12행 중 1행만/);
  assert.match(t, /나머지 11행은 여기에 없다/);
  assert.match(t, /이게 전부/);
  // 고지가 빠져도 report.ledger_size가 행 수보다 크면 잘린 것이다 — 한 출처만
  // 믿으면 다른 쪽이 빠졌을 때 화면이 조용해진다
  assert.match(ledgerTruncatedText({ ledger: [{ point: "p" }], report: { ledger_size: 9 } }),
    /원장 9행 중 1행만/);
  // 전량이면 고지하지 않는다 — 늘 뜨는 경고는 아무도 안 읽는다
  assert.equal(ledgerTruncatedText({ ledger: [{ point: "p" }],
    report: { ledger_size: 1 } }), null);
  assert.equal(ledgerTruncatedText({ ledger: [] }), null);
  assert.equal(ledgerTruncatedText({}), null);
  assert.equal(ledgerTruncatedText(undefined), null);
});

test("ledgerKindText — 7종 전부 뜻과 다음 행동이 있다", () => {
  for (const k of ["verify", "tune", "unjudged", "outside_envelope",
    "not_trimmed", "skipped", "ineffective"]) {
    assert.ok(ledgerKindText(k).length > 20, k);
  }
  assert.match(ledgerKindText("tune"), /예산을 늘리거나 목표를 낮춘다/);
  assert.match(ledgerKindText("unjudged"), /통과가 아니다/);
});

// ── 검증 커버리지 ──────────────────────────────────────────────────────

test("coverageLines — 검증점 0(요구 있음)이 가장 강한 줄이고 맨 앞이다", () => {
  // 판정·실패 수는 **본 것만** 센다. 검증점이 0이면 실패도 0이라, 커버리지를 안
  // 말하면 "무검증"이 "무결"과 같은 얼굴로 뜬다.
  // coverage의 실물 키는 엔진 orchestrator.coverage() — 남은 수(validation_missing)다
  const lines = coverageLines({
    coverage: { validation_points: 0, validation_missing: 60, refine_remaining: 0.5409,
      refine_tol: 0.25, refine_aborted: "budget_points", not_trimmed: 2 },
    coverage_gaps: ["breakpoint 사이 구간을 검증하지 않았다"],
  });
  assert.equal(lines[0].tone, "fail", "가장 강한 줄이 맨 앞이 아니다");
  assert.equal(lines[0].key, "validation");
  assert.match(lines[0].text, /보간 구간 검증점이 한 개도 없다/);
  assert.match(lines[0].text, /남은 구간 60개/);
  // points + missing을 "요구 수"로 합치지 않는다 — 이터가 돌면 요구가 갱신되므로
  // 그 합은 전체 구간 수가 아니다. 합치면 화면이 분모를 지어내는 것이다
  assert.doesNotMatch(lines[0].text, /요구 60/);
  // 나머지 공백도 사라지지 않는다
  const keys = lines.map((l) => l.key);
  for (const k of ["refine", "not_trimmed", "gap0"]) {
    assert.ok(keys.includes(k), `${k} 줄이 없다`);
  }
  assert.ok(lines.every((l) => l.tone !== "hint"));
  const refine = lines.find((l) => l.key === "refine").text;
  assert.match(refine, /0.541 \(허용 0.250\)/);
  assert.match(refine, /중단 사유 budget_points — 점 예산 소진/);
});

test("coverageLines — 프로즈는 엔진이 정본, 없을 때만 화면이 대신 말한다", () => {
  // 엔진 문장(coverage_gaps)과 화면 문장을 둘 다 내면 같은 말이 색만 달리해 두 번
  // 뜬다. 수치는 화면이 늘 내고("몇 개인가"), 왜 문제인지는 엔진이 낸다
  const cov = { validation_points: 0, validation_missing: 60 };
  const withGaps = coverageLines({ coverage: cov, coverage_gaps: ["엔진 문장"] });
  assert.doesNotMatch(withGaps[0].text, /앵커/);
  assert.equal(withGaps.find((l) => l.key === "gap0").text, "엔진 문장");

  // 엔진 문장이 없으면(구형 결과) 화면이 그 자리를 메운다 — 수치만 남기고 끝내면
  // "검증점 0"이 왜 심각한지가 화면 어디에도 없다
  const alone = coverageLines({ coverage: cov });
  assert.match(alone[0].text, /전부 자기 게인이 직접 튜닝된 앵커다/);
  assert.match(alone[0].text, /breakpoint 사이에서 무너지는지는 보지 않았다/);
});

test("coverageLines — 실측 형상: 검증도 하고 남기기도 한 실행", () => {
  // 실측(작은 격자): points 6 · missing 11 · refine 0.327 > tol 0.25 · aborted
  const lines = coverageLines({
    coverage: { validation_points: 6, validation_missing: 11, refine_remaining: 0.327,
      refine_tol: 0.25, refine_aborted: "budget_points", not_trimmed: 0 },
  });
  const v = lines.find((l) => l.key === "validation");
  assert.equal(v.tone, "warn");
  assert.match(v.text, /보간 구간 11개가 검증점 없이 남았다 \(검증된 구간은 6개\)/);
  // 6과 11을 더해 "요구 17"이라 쓰면 안 된다 — 이터가 돌면 요구가 갱신된다
  assert.doesNotMatch(v.text, /17/);
  assert.equal(lines.find((l) => l.key === "not_trimmed"), undefined); // 0은 말 안 한다

  const full = coverageLines({
    coverage: { validation_points: 60, validation_missing: 0, refine_remaining: 0.1,
      refine_tol: 0.25, not_trimmed: 0 },
  });
  assert.ok(full.every((l) => l.tone === "hint"), "공백이 없는데 경고를 냈다");
  assert.match(full[0].text, /보간 구간 검증점 60/);

  // 둘 다 0이면 아무 말도 안 한다 — 검증할 구간 자체가 없었던 실행이다
  assert.deepEqual(coverageLines({
    coverage: { validation_points: 0, validation_missing: 0 } }), []);

  // coverage 자체가 없는 구형 결과 — 지어내지 않는다
  assert.deepEqual(coverageLines({}), []);
  assert.deepEqual(coverageLines(undefined), []);

  // 검증점 수가 안 온 것과 0인 것은 다르다 — 없는 수를 0으로 읽으면 결과가 말한
  // 적 없는 "한 개도 없다"를 화면이 단정한다
  const unknown = coverageLines({
    coverage: { validation_points: null, validation_missing: 60 },
  });
  assert.equal(unknown[0].tone, "warn");
  assert.match(unknown[0].text, /몇 개가 검증됐는지를 결과가 말하지 않는다/);
  assert.doesNotMatch(unknown[0].text, /한 개도 없다/);
});

test("coverageLines — refine 잔여가 허용을 넘으면 경고, 안 넘으면 hint", () => {
  const over = coverageLines({ coverage: { refine_remaining: 0.54, refine_tol: 0.25 } });
  assert.equal(over[0].tone, "warn");
  assert.match(over[0].text, /플랜트 변화를 다 못 따라갔다/);
  const under = coverageLines({ coverage: { refine_remaining: 0.1, refine_tol: 0.25 } });
  assert.equal(under[0].tone, "hint");
  // 거리를 못 재도 중단 사실은 남는다 — 모르는 사유 코드도 코드 그대로
  const aborted = coverageLines({ coverage: { refine_aborted: "wat" } });
  assert.equal(aborted[0].tone, "warn");
  assert.match(aborted[0].text, /격자 세분화 중단 — wat/);
});

test("adoptWarnText — 확정을 막지는 않되 무엇을 모르고 확정하는지 말한다", () => {
  const report = {
    judged: 40, failures: 0,
    coverage: { validation_points: 0, validation_missing: 60 },
    coverage_gaps: ["보간 구간 검증점이 하나도 들어가지 않았다"],
  };
  // 커버리지 공백은 확정을 막는 사유가 아니다 — 앵커에서는 판정이 났다
  assert.equal(adoptable(report), true);
  assert.equal(adoptBlockedText(report), null);
  const warn = adoptWarnText(report);
  assert.match(warn, /보간 구간 검증점이 한 개도 없다/);
  assert.match(warn, /보간 구간 검증점이 하나도 들어가지 않았다/); // 엔진 문장 그대로
  assert.match(warn, /검증된 적 없는 채로/);
  // 공백이 없으면 경고도 없다 — 늘 뜨는 경고는 아무도 안 읽는다
  assert.equal(adoptWarnText({ judged: 40, coverage: { validation_points: 60,
    validation_missing: 0 } }), null);
  assert.equal(adoptWarnText({}), null);
  assert.equal(adoptWarnText(undefined), null);
});

test("reportLine — 원장 크기도 줄에 오른다 (카드 수와 다른 수다)", () => {
  assert.match(reportLine({ ledger_size: 7 }).join(" · "), /미달 원장 7/);
  // 0이면 생략 — 원장 없는 구형 결과가 "미달 원장 0"으로 뜨면 거짓말이다
  assert.doesNotMatch(reportLine({ judged: 3, failures: 0 }).join(" · "), /미달 원장/);
});

test("reliefLines — 통과한 축은 **임계값**을 말한다 (×3이 아니라 ≥47 rad/s)", () => {
  // "작동기 대역폭 ×3이면 통과"는 무엇을 주문해야 하는지 알려 주지 않는다.
  // 엔진이 이분으로 최소 완화량을 실측하므로 화면은 그 수치를 그대로 낸다 —
  // docs §7 "작동기 대역폭 요구 사양 미도출"이 요구하던 답이다.
  const [ok, no] = reliefLines([
    { change: "actuator_wn", label: "작동기 대역폭 ×3", from: 18, to: 54,
      resolves: true,
      threshold: { name: "min_actuator_wn", value: 20.39, unit: "rad/s",
                   text: "작동기 대역폭 ≥ 20.4 rad/s면 통과 (현재 18)" } },
    { change: "delay_s", label: "지연 제거", from: 0.035, to: 0, resolves: false,
      reason: "margin_floor" },
  ], {});
  assert.equal(ok.threshold, "작동기 대역폭 ≥ 20.4 rad/s면 통과 (현재 18)");
  assert.match(ok.text, /통과 · 작동기 대역폭 ≥ 20\.4 rad\/s면 통과 \(현재 18\)/);
  assert.equal(no.threshold, null, "미달 축에 임계값을 지어내면 안 된다");
  assert.match(no.text, /여전히 미달 · 사유 /);
});

test("reliefLines — 없는 것을 추가하는 축은 '없음 → 값' (필터 프로브)", () => {
  // 완화 축이 늘 "현재값을 바꾼다"는 아니다 — 레이트 필터는 지금 **없는** 것을
  // 더해 보는 프로브라 from이 null이다. num()의 "—"로 그리면 "값을 모른다"로
  // 읽혀, 아직 안 붙은 것과 못 잰 것이 화면에서 같아진다
  const [line] = reliefLines([
    { change: "rate_filter_fc", label: "레이트 저역통과 추가",
      from: null, to: 2.39, resolves: false, reason: "bandwidth_collapse" },
  ], {});
  assert.match(line.text, /없음 → 2\.39/);
  assert.equal(line.resolves, false);
  assert.equal(line.threshold, null);
  // 양쪽 다 없는 경우는 종전대로 괄호 자체를 안 그린다
  const [bare] = reliefLines([{ label: "x", from: null, to: null, resolves: true }], {});
  assert.equal(bare.text, "x → 통과");
});
