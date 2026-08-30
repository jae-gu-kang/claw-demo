/** autodesign 순수 로직 검증 — 설정 페이로드, 점·판정 결합, 처방 그룹, 게인 채택. */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  actionCards,
  adoptBlockedText,
  adoptStorePayload,
  adoptable,
  buildConfig,
  effectText,
  evidenceLines,
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
