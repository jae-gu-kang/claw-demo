/** lib/verify — 요청 조립·판정 표시 모델.

요청 조립은 실제 BLOCKS 위에서 검사한다 — 가짜 블록 목록으로 통과시키면 BLOCKS
계약(schema·injectKey·axes)이 바뀌었을 때 여기가 낡은 채 초록으로 남는다.
*/

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  buildVerifyRequest, caseGroups, covCell, failedRuleCount, firstFailKey,
  mcdcCell, mismatchedOutputCount, pct, sourceRows, statusFlag, truthTable,
  uncoveredBranchCount, unitGridRows, verdictModel,
} from "./verify.js";

const storeOf = (map) => (key) => map[key];

const CATALOG = {
  scas_design: {
    pitch: { kp: -2.0, ki: -0.5, k_rate: 0.4, out_lo: -0.35, out_hi: 0.35 },
    roll: { kp: 1.0, ki: 0.1, k_rate: -0.2, out_lo: -0.35, out_hi: 0.35 },
    yaw: { kp: 0.5, ki: 0.0, k_rate: 0.8, washout_tau: 2.0, out_lo: -0.35, out_hi: 0.35 },
  },
};

test("편집도 카탈로그도 없으면 최소 요청 — 서버의 설계 기본 형상", () => {
  const req = buildVerifyRequest(storeOf({}), null);
  assert.deepEqual(req, { control_hz: 100, t_end: 180 });
});

test("카탈로그가 있으면 SCAS 세 축 전량이 실린다 (부분 주입 422 회피)", () => {
  const req = buildVerifyRequest(storeOf({}), CATALOG);
  assert.deepEqual(Object.keys(req.scas).sort(), ["pitch", "roll", "yaw"]);
  assert.equal(req.scas.yaw.washout_tau, 2.0);
});

test("편집값이 설계값을 이긴다 + AP·게인 테이블·t_end가 실린다", () => {
  const store = {
    autopilotParams: { kp_alt: 0.008 },
    scasParams: { pitch: { ...CATALOG.scas_design.pitch, kp: -3.0 } },
    gainTables: { "pitch.kp": { axes: { mach: [0.2, 0.6] }, data: [1, 2] } },
  };
  const req = buildVerifyRequest(storeOf(store), CATALOG, { tEnd: 30 });
  assert.equal(req.autopilot.kp_alt, 0.008);
  assert.equal(req.scas.pitch.kp, -3.0);
  assert.equal(req.scas.roll.kp, 1.0); // 미편집 축은 설계값
  assert.ok(req.gain_tables["pitch.kp"]);
  assert.equal(req.t_end, 30);
});

test("전부 끔(scheduleOff)은 with_schedule:false로 — 테이블은 함께 못 실린다", () => {
  const req = buildVerifyRequest(
    storeOf({ gainScheduleOff: true, gainTables: { "pitch.kp": {} } }), null);
  assert.equal(req.with_schedule, false);
  assert.equal("gain_tables" in req, false);
});

test("statusFlag — 측정은 통과가 아니다 (na 색)", () => {
  assert.deepEqual(statusFlag("pass"), { cls: "ok", label: "통과" });
  assert.deepEqual(statusFlag("fail"), { cls: "bad", label: "실패" });
  assert.deepEqual(statusFlag("skip"), { cls: "na", label: "생략" });
  assert.equal(statusFlag("info").cls, "na");
  assert.equal(statusFlag("measured").cls, "na");
  assert.equal(statusFlag(undefined).label, "—");
});

test("verdictModel — 실패는 무엇이 실패했는지를 한 줄로", () => {
  const rep = {
    verdict: "fail",
    summary: [
      { key: "static", label: "정적 — 생성 코드 규율", status: "pass" },
      { key: "equiv", label: "동등성 — Python↔C 비트 일치", status: "fail" },
    ],
  };
  const v = verdictModel(rep);
  assert.equal(v.cls, "bad");
  assert.ok(v.line.includes("동등성"));
  assert.equal(verdictModel(null), null);
  assert.equal(verdictModel({ verdict: "pass", summary: [] }).cls, "ok");
  const s = verdictModel({ verdict: "pass_with_skips", summary: [{ status: "skip" }] });
  assert.equal(s.cls, "na");
  assert.ok(s.line.includes("생략 1건"));
});

test("firstFailKey — 잡이 끝나면 열어 줄 서랍", () => {
  assert.equal(firstFailKey({ summary: [{ key: "a", status: "pass" }, { key: "b", status: "fail" }] }), "b");
  assert.equal(firstFailKey({ summary: [{ key: "a", status: "pass" }] }), null);
  assert.equal(firstFailKey(null), null);
});

test("배지 수 — 못 센 것은 null (0으로 위장하지 않는다)", () => {
  assert.equal(failedRuleCount(null), null);
  assert.equal(failedRuleCount({ static: { rules: [{ status: "pass" }, { status: "fail" }] } }), 1);
  assert.equal(uncoveredBranchCount({ coverage: { status: "skip" } }), null);
  assert.equal(uncoveredBranchCount(
    { coverage: { status: "measured", uncovered_branches: [1, 2] } }), 2);
  assert.equal(mismatchedOutputCount({ equivalence: { outputs: [
    { first_diff: null }, { first_diff: { step: 3 } }] } }), 1);
  assert.equal(mismatchedOutputCount({}), null);
});

test("pct — 측정 불가는 0%가 아니라 —", () => {
  assert.equal(pct(97.83), "97.8%");
  assert.equal(pct(null), "—");
  assert.equal(pct(NaN), "—");
});

// ── VectorCAST식 표시 모델 ────────────────────────────────────────────────

const REPORT = {
  files: [{ name: "fcl_ap.c", lines: 4, text: "a\nif ((x > h && i > 0.0) || (x < l && i < 0.0)) {\nc\nd" }],
  coverage: {
    status: "measured",
    files: [{ name: "fcl_ap.c", line_counts: [[1, 5], [2, 5], [3, 0]],
              lines: { count: 3, covered: 2, percent: 66.7 },
              branches: { count: 8, covered: 6, percent: 75.0 } }],
    uncovered_branches: [{ file: "fcl_ap.c", line: 2, missing: "참측", text: "if…" }],
    justified: [{ file: "fcl_ap.c", line: 2, missing: "거짓측", text: "if…" }],
  },
  mcdc: { status: "measured", decisions: [{
    id: 0, file: "fcl_ap.c", line: 2, kind: "guard", label: "x",
    conditions: ["x > h", "i > 0.0", "x < l", "i < 0.0"],
    covered: [true, false, true, false], justified_cis: [1, 3],
    pairs: [[0x13, 0x51], null, [0x31, 0x15], null],
    vectors: [
      { mask: 0x13, conds: [true, true, null, null], outcome: true },
      { mask: 0x51, conds: [false, null, false, null], outcome: false },
    ],
    uncovered: [{ ci: 1, text: "i > 0.0", justified: true, reason: "구조적 종속 …" }],
  }] },
  units: [
    { unit: "ap", title: "오토파일럿", files: ["fcl_ap.c", "fcl_ap.h"],
      cases: { total: 4, passed: 4, skipped: 0 },
      lines: { count: 3, covered: 3, percent: 100 },
      branches: { count: 8, covered: 6, percent: 75 },
      mcdc: { total: 4, covered: 2, justified: 2 } },
    { unit: "claw_rt", title: "공용 런타임", files: ["claw_rt.c"],
      cases: { total: 0, passed: 0, skipped: 0 },
      lines: { count: 0, covered: 0, percent: null },
      branches: { count: 0, covered: 0, percent: null },
      mcdc: { total: 0, covered: 0, justified: 0 } },
  ],
  cases: [
    { id: "TC-MISSION-6S", title: "통합", unit: "fcl", steps: 600, status: "pass", first_diff: null },
    { id: "TC-U-AP-WIND", title: "ap 유닛", unit: "ap", steps: 220, status: "fail",
      first_diff: { step: 3, output: "ap_hdg_sat", c: 1, py: 2 } },
  ],
};

test("covCell·mcdcCell — 잴 것 없음은 0%가 아니라 —", () => {
  assert.equal(covCell({ count: 8, covered: 6, percent: 75 }), "75.0% (6/8)");
  assert.equal(covCell({ count: 0, covered: 0, percent: null }), "—");
  assert.equal(mcdcCell({ total: 4, covered: 2, justified: 2 }), "2+2/4");
  assert.equal(mcdcCell({ total: 4, covered: 4, justified: 0 }), "4/4");
  assert.equal(mcdcCell({ total: 0, covered: 0, justified: 0 }), "—");
});

test("unitGridRows — 케이스·커버리지·MC/DC가 표시 문자열로", () => {
  const rows = unitGridRows(REPORT);
  assert.equal(rows.length, 2);
  assert.equal(rows[0].tc, "4/4");
  assert.equal(rows[0].status.cls, "ok");
  assert.equal(rows[0].mcdc, "2+2/4");
  assert.equal(rows[1].tc, "—");
  assert.equal(rows[1].status.cls, "na");
  assert.equal(unitGridRows(null).length, 0);
});

test("unitGridRows — 케이스 실패는 유닛 행을 빨갛게", () => {
  const rep = { units: [{ ...REPORT.units[0], cases: { total: 4, passed: 3, skipped: 0 } }] };
  assert.equal(unitGridRows(rep)[0].status.cls, "bad");
});

test("sourceRows — 실행/미실행/부분/정당화/비실행문 분류", () => {
  const rows = sourceRows(REPORT, "fcl_ap.c");
  assert.equal(rows.length, 4);
  assert.equal(rows[0].cls, "hit");
  assert.equal(rows[1].cls, "part");        // 실행됐지만 분기 한쪽 미달
  assert.deepEqual(rows[1].dec.id, 0);      // MC/DC 결정이 그 줄에 붙는다
  assert.equal(rows[2].cls, "miss");
  assert.equal(rows[3].cls, "");            // 비실행문 — 미측정과 구분
  assert.equal(rows[3].count, null);
});

test("sourceRows — 커버리지 생략이어도 소스는 선다 (조용한 빈 화면 금지)", () => {
  const rep = { files: REPORT.files, coverage: { status: "skip" }, mcdc: { status: "skip" } };
  const rows = sourceRows(rep, "fcl_ap.c");
  assert.equal(rows.length, 4);
  assert.ok(rows.every((r) => r.cls === "" && r.count == null));
  assert.equal(sourceRows(REPORT, "없는파일.c"), null);
});

test("truthTable — 벡터·독립쌍·정당화 조건", () => {
  const t = truthTable(REPORT.mcdc.decisions[0]);
  assert.equal(t.conds.length, 4);
  assert.equal(t.conds[0].covered, true);
  assert.equal(t.conds[1].justified, true);
  assert.deepEqual(t.rows[0].cells, ["T", "T", "–", "–"]);
  assert.equal(t.rows[0].outcome, "T");
  assert.ok(t.rows[0].inPair);   // 0x13은 c0의 독립쌍에 참여
  assert.equal(t.rows[1].outcome, "F");
});

test("caseGroups — 유닛 순서로 묶고 제목을 단다", () => {
  const g = caseGroups(REPORT);
  assert.deepEqual(g.map((x) => x.unit), ["ap", "claw_rt", "fcl"]);
  assert.equal(g.find((x) => x.unit === "ap").cases.length, 1);
  assert.equal(g.find((x) => x.unit === "fcl").cases.length, 1);
  assert.equal(caseGroups(null).length, 0);
});
