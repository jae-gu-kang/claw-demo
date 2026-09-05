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
  STATUS_LABEL, cardLines, caseGrid, checksSummary, evaluateRequest,
  hardFailLines, jLine, normalizeEvalReport, normalizeVerifyReport,
  statusInk, verifyRequest,
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
  assert.equal(line, "추가 판정 9/9 PASS");
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
  // 카드 7·체크 9 — 웹은 목록을 하드코딩하지 않지만 개수 계약은 화면 배치의 전제다
  assert.equal((src.match(/CARDS = \(([^)]+)\)/) || [])[1].split(",")
    .filter((x) => x.trim()).length, 7);
  assert.equal((src.match(/CHECKS = \(([^)]+)\)/) || [])[1].split(",")
    .filter((x) => x.trim()).length, 9);
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
