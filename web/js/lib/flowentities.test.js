/** 설계 흐름 엔티티 막대 목록 — 순수 lib 테스트 (node --test).
 *
 * 이 파일의 앞 절반은 기능이 아니라 **거짓말 금지**를 고정한다(계약 「비워야 하는 것」 일곱):
 *   (1) 엔벨로프 도달을 목록이 칠하지 않는다            (2) 평가 합격/불합격은 hard_fail이 있을 때만
 *   (3) 판정 0의 실패 0을 통과로 쓰지 않는다             (4) 변형 줄에 기본형 확정 표를 물려주지 않는다
 *   (5) 기체 기록 없는 옛 meta를 어느 줄에도 싣지 않는다  (6) 미수렴 원인 셋을 구별하지 않는다
 *   (7) 키 없는 옛 ④ 결과에 세그먼트를 그리지 않는다
 * 증거가 없는 칸은 실패한 칸과 **다른 토큰**이어야 하고, 둘 다 「통과」가 아니어야 한다.
 */
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  FE_STAGES, FE_TOKENS, FE_TRIM_TOKENS, entityRows, gainLayersModel, trimStoreModel,
} from "./flowentities.js";

// ── 재료 ─────────────────────────────────────────────────────────────────────
const profile = (over = {}) => ({
  id: "ac", name: "기체 A", revision: 3, fingerprint: "fp1", is_example: false,
  variants: [], design_source: null, de_trim: null, gain_tables: null, applied_design: null, ...over,
});
const meta = (over = {}) => ({
  id: "r1", kind: "auto_design", created: 100,
  profile: { id: "ac", variant: null, fingerprint: "fp1" }, ...over,
});
const cellOf = (row, key) => row.cells.find((c) => c.stage === key);
const rowOf = (out, key) => out.rows.find((r) => r.key === key);

// ── 1. 비워야 하는 것 ─────────────────────────────────────────────────────────

test("엔벨로프 — 목록 재료만으로는 절대 도달이 아니다(저장물 없는 조회 단계)", () => {
  // 기록이 많은 기체여도, 엔벨로프 칸은 기록 없음이다
  const out = entityRows([profile({ design_source: "quick_seed",
    gain_tables: { source: "auto_design", stale: false, stale_variants: [], variants: {} } })],
  [meta({ status: "converged", judged: 5, failures: 0 })]);
  const env = cellOf(out.rows[0], "envelope");
  assert.equal(env.state, "no_record");
  assert.equal(env.tone, "no_record");
  assert.notEqual(env.state, "reached");
  assert.equal(env.source, "none");
  // ① 문서 검증도 서버가 경고 수를 안 실으면 기록 없음이다
  assert.equal(cellOf(out.rows[0], "doc").state, "no_record");
});

test("평가 — hard_fail 키가 없는 옛 결과는 판정 모름이다(합격도 불합격도 아니다)", () => {
  const out = entityRows([profile()], [meta({ kind: "influence_evaluate", id: "e1", n: 12 })]);
  const c = cellOf(out.rows[0], "eval");
  assert.equal(c.state, "unknown_verdict");
  assert.equal(c.tone, "unknown_verdict");
  assert.notEqual(c.tone, "fail", "불합격(붉은색)으로 위장하지 않는다");
  assert.notEqual(c.tone, "reached", "통과로도 쓰지 않는다");
  assert.match(c.tip, /판정/);
  assert.equal(FE_TOKENS.unknown_verdict.border, "dotted", "판정 부재는 점선 테두리다");
});

test("평가 — hard_fail이 있으면 그 판정을 말한다(true면 불합격색, false면 도달)", () => {
  const bad = entityRows([profile()],
    [meta({ kind: "influence_evaluate", id: "e1", n: 4, hard_fail: true, hard_fails: 3 })]);
  assert.equal(cellOf(bad.rows[0], "eval").tone, "fail");
  assert.match(cellOf(bad.rows[0], "eval").label, /위반 3건/);
  const ok = entityRows([profile()],
    [meta({ kind: "influence_evaluate", id: "e1", n: 4, hard_fail: false, hard_fails: 0 })]);
  assert.equal(cellOf(ok.rows[0], "eval").state, "reached");
  assert.equal(cellOf(ok.rows[0], "eval").tone, "reached");
});

test("자동 설계 — 판정 0의 실패 0을 통과로 쓰지 않는다", () => {
  const out = entityRows([profile()], [meta({ status: "converged", judged: 0, failures: 0 })]);
  const c = cellOf(out.rows[0], "design");
  assert.equal(c.state, "unknown_verdict");
  assert.notEqual(c.tone, "reached");
  assert.match(c.tip, /실패 0은 통과가 아니다/);
  // 판정 키 자체가 없는 옛 결과도 통과가 아니다
  const old = entityRows([profile()], [meta({ status: "converged" })]);
  assert.equal(cellOf(old.rows[0], "design").state, "unknown_verdict");
  assert.match(cellOf(old.rows[0], "design").tip, /옛 결과/);
});

test("자동 설계 — 키 없는 옛 결과엔 세그먼트를 그리지 않는다", () => {
  const old = entityRows([profile()], [meta({ status: "converged", judged: 3, failures: 0 })]);
  assert.deepEqual(cellOf(old.rows[0], "design").segments, []);
  // trim_reuse·iterations가 있으면(③ 작업이 넣는 키) 그때만 세그먼트가 선다
  const now = entityRows([profile()], [meta({ status: "converged", judged: 3, failures: 0,
    trim_reuse: { reused: 7, computed: 2, resolved_failed: 1 }, iterations: 2 })]);
  assert.deepEqual(cellOf(now.rows[0], "design").segments.map((s) => [s.kind, s.n]),
    [["trim_reused", 7], ["trim_computed", 2], ["trim_resolved_failed", 1], ["iterations", 2]]);
});

test("형상 변형 줄 — 기본형 확정 표를 물려받지 않는다", () => {
  const p = profile({
    variants: [{ id: "eoir", name: "EO/IR형", fingerprint: "fpv" }],
    gain_tables: { source: "auto_design", stale: false, stale_variants: [],
      variants: { eoir: { source: "rule_schedule" } } },
  });
  // 변형에 기록이 있어야 자기 줄을 갖는다 — 그 변형으로 돈 결과를 준다
  const out = entityRows([p], [meta({ id: "v1", status: "converged", judged: 2, failures: 0,
    profile: { id: "ac", variant: "eoir" } })]);
  const v = rowOf(out, "ac::eoir");
  assert.ok(v, "변형 줄이 있어야 한다");
  const cell = cellOf(v, "apply");
  assert.equal(cell.state, "not_run");
  assert.match(cell.label, /규칙 스케줄/);
  assert.doesNotMatch(cell.label, /유효/);
  assert.doesNotMatch(cell.tip, /출처 auto_design/);
  // 기본 줄은 자기 표를 그대로 말한다
  assert.equal(cellOf(rowOf(out, "ac"), "apply").state, "reached");
});

test("기체 기록 없는 옛 meta는 어느 줄에도 싣지 않는다", () => {
  const out = entityRows([profile()],
    [{ id: "r0", kind: "auto_design", created: 1, status: "converged", judged: 9, failures: 0 }]);
  const c = cellOf(out.rows[0], "design");
  assert.equal(c.state, "not_run");
  assert.equal(c.resultId, null);
});

test("트림 저장소 — 미수렴 기록은 원인 셋을 구별하지 않는다", () => {
  const grid = { points: [
    { name: "a", mach: 0.1, alt: 0, fuel: 10, state: "not_run", stored: { state: null, converged: false } },
    { name: "b", mach: 0.2, alt: 0, fuel: 10, state: "not_run", stored: { state: "computable", converged: true } },
    { name: "c", mach: 0.3, alt: 0, fuel: 10, state: "not_run" },
    { name: "d", mach: 0.4, alt: 0, fuel: 10, state: "model_gap" },
  ] };
  const m = trimStoreModel(grid, null);
  const cells = m.rows[0].cells;
  assert.deepEqual(cells.map((c) => c.state),
    ["stored_unconverged", "stored_converged", "not_run", "model_gap"]);
  // 미수렴 토큰은 하나 — 계산 실패·제약 도달·물리적 불가 칸이 따로 없다
  assert.match(FE_TRIM_TOKENS.stored_unconverged.label, /원인 미판정/);
  for (const k of ["calc_failed", "constraint_hit", "infeasible"]) {
    assert.equal(FE_TRIM_TOKENS[k], undefined, `미수렴 원인 칸(${k})을 만들지 않는다`);
  }
  assert.equal(m.fingerprint, null, "재사용 되울림이 없으면 저장소 창 지문은 모름이다");
  assert.equal(m.reuse, null);
  assert.ok(m.notes.some((n) => /같은 창/.test(n)), "창은 기체 1:1이 아니라는 사실을 적는다");
});

// ── 2. 상태·토큰·도달 ────────────────────────────────────────────────────────

test("네 상태(안 돌림·건너뜀·실패·불합격)가 서로 다른 토큰이고, 기록 없음·판정 모름도 따로다", () => {
  const keys = ["reached", "not_run", "skipped", "failed", "fail", "warn", "blocked", "no_record",
    "unknown_verdict"];
  const sig = keys.map((k) => {
    const t = FE_TOKENS[k];
    return `${t.fill}|${t.color}|${t.pattern}|${t.border}|${t.marker}`;
  });
  assert.equal(new Set(sig).size, keys.length, `토큰이 겹친다: ${JSON.stringify(sig)}`);
  // 색은 lib/plot.js 한 벌에서만 온다 — 넷이 색을 나눠 갖고, 계산 상태는 무늬·테두리로 갈린다
  assert.equal(FE_TOKENS.not_run.pattern, "none");
  assert.equal(FE_TOKENS.skipped.pattern, "diagonal");
  assert.equal(FE_TOKENS.no_record.pattern, "dots");
  assert.equal(FE_TOKENS.fail.color, "#ff3b30");
  assert.equal(FE_TOKENS.blocked.marker, "stop");
});

test("도달은 ①②를 세지 않는다 — 머리 둘만 판정돼도 도달은 없다", () => {
  const live = {
    doc: { state: "done", verdict: { tone: "ok", text: "통과" } },
    envelope: { state: "done", verdict: { tone: "ok", text: "성립 고도 4/5줄" } },
  };
  const out = entityRows([profile()], [], { sel: { id: "ac", variant: null }, live });
  const r = out.rows[0];
  assert.equal(cellOf(r, "doc").state, "reached", "지금 세션이 돈 기록은 판정 칸이 된다");
  assert.equal(cellOf(r, "envelope").state, "reached");
  assert.equal(r.reach.index, -1, "①②는 도달로 세지 않는다");
  assert.equal(r.reach.key, null);
  assert.equal(r.stop.stageKey, "seed");
});

test("도달 — ③ 건너뜀부터 이어서 세고, 막힌 칸에서 끊는다", () => {
  const p = profile({ design_source: "quick_seed",
    gain_tables: { source: "auto_design", stale: true, stale_variants: [], variants: {} } });
  const out = entityRows([p], [
    meta({ status: "converged", judged: 4, failures: 0 }),
    meta({ id: "e1", kind: "influence_evaluate", n: 6, hard_fail: false, created: 200 }),
  ]);
  const r = out.rows[0];
  assert.deepEqual(r.cells.map((c) => c.state),
    ["no_record", "no_record", "skipped", "reached", "reached", "blocked"]);
  assert.equal(r.reach.key, "eval");
  assert.equal(r.reach.index, 4);
  assert.equal(r.stop.stageKey, "apply");
  assert.match(r.stop.reason, /확정 표 낡음/);
});

test("gain_tables.stale → ⑥ 막힘(끝 마커)", () => {
  const out = entityRows([profile({ gain_tables: { source: "auto_design", stale: true,
    stale_variants: [], variants: {} } })], []);
  const c = cellOf(out.rows[0], "apply");
  assert.equal(c.state, "blocked");
  assert.equal(FE_TOKENS[c.tone].marker, "stop");
  assert.match(c.tip, /다시 돌려/);
});

test("awaiting_approval → ④ 막힘 + 정지 사유", () => {
  const out = entityRows([profile({ design_source: "quick_seed" })],
    [meta({ status: "awaiting_approval", stage: "PRESCRIBE" })]);
  const r = out.rows[0];
  assert.equal(cellOf(r, "design").state, "blocked");
  assert.equal(r.stop.stageKey, "design");
  assert.match(r.stop.reason, /승인 대기/);
  assert.equal(r.reach.key, "seed", "막힌 앞 칸까지만 도달이다");
});

test("트림 재사용 세그먼트는 ⑤ 평가 칸에 선다(자리·단계를 옮기지 않는다)", () => {
  const out = entityRows([profile()], [meta({ id: "e1", kind: "influence_evaluate", n: 5,
    hard_fail: false, trim_reuse_counts: { reused: 3, computed: 2, resolved_failed: 0 } })]);
  const r = out.rows[0];
  assert.deepEqual(cellOf(r, "eval").segments.map((s) => s.kind), ["trim_reused", "trim_computed"]);
  assert.deepEqual(cellOf(r, "design").segments, [], "평가의 재사용이 ④로 새지 않는다");
  assert.equal(cellOf(r, "eval").segments[0].n, 3);
});

test("칸 수·순서는 레일과 같다(6) — 단계를 늘리면 둘을 같이 고친다", () => {
  const out = entityRows([profile()], []);
  assert.equal(out.rows[0].cells.length, 6);
  assert.deepEqual(out.rows[0].cells.map((c) => c.stage), FE_STAGES.map((s) => s.key));
});

test("읽을 수 없는 기체는 ① 실패로 서고 줄이 사라지지 않는다", () => {
  const out = entityRows([{ id: "broken", unreadable: true, reason: "파일이 없다" }], []);
  assert.equal(out.rows.length, 1);
  assert.equal(cellOf(out.rows[0], "doc").state, "failed");
  assert.match(out.rows[0].label, /읽을 수 없음/);
  assert.match(cellOf(out.rows[0], "doc").tip, /파일이 없다/);
});

// ── 3. 변형 접기·캡션·정렬 ────────────────────────────────────────────────────

test("형상 변형 접기 — 기록 없는 변형은 자기 줄을 갖지 않고 캡션이 그 수를 말한다", () => {
  const p = profile({ variants: [
    { id: "eoir", name: "EO/IR형" }, { id: "hp", name: "고출력형" }] });
  const out = entityRows([p], [meta({ id: "v1", status: "converged", judged: 1, failures: 0,
    profile: { id: "ac", variant: "eoir" } })]);
  assert.deepEqual(out.rows.map((r) => r.key).sort(), ["ac", "ac::eoir"]);
  assert.match(out.caption, /형상 변형 2개 중 1개에 설계 기록/);
  // 확정 표로 나는 변형도 자기 줄을 갖는다(결과가 없어도)
  const p2 = profile({ variants: [{ id: "eoir", name: "EO/IR형" }],
    gain_tables: { source: "auto_design", stale: false, stale_variants: [],
      variants: { eoir: { source: "confirmed" } } } });
  const out2 = entityRows([p2], []);
  assert.ok(rowOf(out2, "ac::eoir"), "확정 표로 나는 변형은 줄을 갖는다");
  assert.equal(cellOf(rowOf(out2, "ac::eoir"), "apply").state, "reached");
});

test("캡션의 수 합 — 줄 수·이어진 줄·막힌 줄·판정 모름 줄", () => {
  const rows = [
    profile({ id: "a", name: "A", design_source: "quick_seed",
      gain_tables: { source: "auto_design", stale: false, stale_variants: [], variants: {} } }),
    profile({ id: "b", name: "B", gain_tables: { source: "auto_design", stale: true,
      stale_variants: [], variants: {} } }),
    profile({ id: "c", name: "C" }),
  ];
  const metas = [
    meta({ id: "ra", profile: { id: "a", variant: null }, status: "converged", judged: 3, failures: 0, created: 5 }),
    meta({ id: "ea", kind: "influence_evaluate", profile: { id: "a", variant: null }, n: 2,
      hard_fail: false, created: 6 }),
    meta({ id: "rb", profile: { id: "b", variant: null }, status: "converged", created: 4 }),
  ];
  const out = entityRows(rows, metas);
  assert.match(out.caption, /엔티티 3개/);
  assert.match(out.caption, /이어진 줄 1개/); // a만 ③부터 이어진다
  assert.match(out.caption, /막힌 줄 1개/); // b의 ⑥ 낡음
  // b의 ④(judged 없는 옛 meta)만 판정 모름이다 — ①②의 기록 없음은 이 수에 들지 않고(다른 무늬다),
  // 기록이 아예 없는 c는 「안 돌림」이다
  assert.match(out.caption, /판정을 목록으로 알 수 없는 칸이 있는 줄 1개/);
  assert.ok(out.notes.length >= 3);
});

test("정렬 — 도달 내림차순 뒤 최근 created 내림차순", () => {
  const far = profile({ id: "far", name: "멀리", design_source: "quick_seed",
    gain_tables: { source: "auto_design", stale: false, stale_variants: [], variants: {} } });
  const nearNew = profile({ id: "n1", name: "최근" });
  const nearOld = profile({ id: "n2", name: "옛것" });
  const metas = [
    meta({ id: "f", profile: { id: "far", variant: null }, status: "converged", judged: 2, failures: 0, created: 1 }),
    meta({ id: "fe", kind: "influence_evaluate", profile: { id: "far", variant: null }, n: 1, hard_fail: false, created: 1 }),
    meta({ id: "a", profile: { id: "n1", variant: null }, status: "converged", created: 900 }),
    meta({ id: "b", profile: { id: "n2", variant: null }, status: "converged", created: 100 }),
  ];
  assert.deepEqual(entityRows([nearOld, nearNew, far], metas).rows.map((r) => r.id),
    ["far", "n1", "n2"]);
});

test("선택된 줄에만 live 기록이 실린다 — 다른 줄에 A 기체 판정이 서지 않는다", () => {
  const live = { doc: { state: "done", verdict: { tone: "ok", text: "통과" } } };
  const out = entityRows([profile({ id: "a", name: "A" }), profile({ id: "b", name: "B" })], [],
    { sel: { id: "a", variant: null }, live });
  assert.equal(cellOf(rowOf(out, "a"), "doc").source, "live");
  assert.equal(cellOf(rowOf(out, "b"), "doc").state, "no_record");
  assert.equal(rowOf(out, "a").selected, true);
  assert.equal(rowOf(out, "b").selected, false);
});

test("실행 중인 단계는 running 토큰이다(도달로 세지 않는다)", () => {
  const live = { design: { state: "running", note: "자동 설계 40%" } };
  const out = entityRows([profile({ design_source: "quick_seed" })], [],
    { sel: { id: "ac", variant: null }, live });
  const c = cellOf(out.rows[0], "design");
  assert.equal(c.state, "running");
  assert.equal(FE_TOKENS.running.pattern, "pulse");
  assert.equal(out.rows[0].reach.key, "seed");
});

test("① 문서 경고 수는 서버가 실을 때만 말한다(doc_warnings)", () => {
  const warn = entityRows([profile({ doc_warnings: 2 })], []);
  assert.equal(cellOf(warn.rows[0], "doc").state, "reached");
  assert.equal(cellOf(warn.rows[0], "doc").tone, "warn", "문서 경고는 주의다 — 불합격(붉은색)이 아니다");
  assert.match(cellOf(warn.rows[0], "doc").label, /경고 2건/);
  const clean = entityRows([profile({ doc_warnings: 0 })], []);
  assert.equal(cellOf(clean.rows[0], "doc").tone, "reached");
  assert.match(cellOf(clean.rows[0], "doc").label, /경고 없음/);
});

// ── 4. 트림 저장소 모델 ──────────────────────────────────────────────────────

test("트림 저장소 — 고도·연료로 줄을 묶고 마하 순으로 칸을 세운다", () => {
  const grid = { points: [
    { name: "b", mach: 0.3, alt: 0, fuel: 10, state: "not_run" },
    { name: "a", mach: 0.1, alt: 0, fuel: 10, state: "not_run" },
    { name: "c", mach: 0.2, alt: 3000, fuel: 10, state: "not_run" },
  ] };
  const m = trimStoreModel(grid, { trim_reuse: { trim_fingerprint: "tf1", reused: 2, computed: 1,
    resolved_failed: 0, policy: "converged" } });
  assert.deepEqual(m.rows.map((r) => [r.alt, r.fuel, r.cells.map((c) => c.mach)]),
    [[0, 10, [0.1, 0.3]], [3000, 10, [0.2]]]);
  assert.equal(m.fingerprint, "tf1");
  assert.deepEqual(m.reuse, { reused: 2, computed: 1, resolved_failed: 0, policy: "converged" });
  assert.equal(m.counts.not_run, 3);
});

test("트림 저장소 — meta(trim_reuse_counts)만 있으면 수는 말하고 지문은 모른다", () => {
  const m = trimStoreModel({ points: [] },
    { trim_reuse_counts: { reused: 5, computed: 0, resolved_failed: 1 } });
  assert.equal(m.fingerprint, null, "meta에는 저장소 창 지문이 없다(서버 reuse_counts가 세 수만 남긴다)");
  assert.equal(m.reuse.reused, 5);
  assert.equal(m.reuse.policy, null);
});

// ── 5. 게인값 3층 ───────────────────────────────────────────────────────────

const DOC = {
  law: {
    design: { provenance: { source: "quick_seed", slots: {
      "pitch.k_rate": { value: -0.8, sign_basis: "B[q,de]=-12", anchors_used: 2, reason: null },
      "roll.ki": { value: 0, sign_basis: "B[p,da]=9", anchors_used: 0,
        reason: "seed_thin_anchors", reason_text: "앵커가 얇다" },
    } } },
    gain_tables: { tables: { "pitch.k_rate": { axes: { mach: [0.1, 0.3, 0.5] }, data: [1, 2, 3] } },
      provenance: { source: "auto_design", result_id: "r9" } },
  },
};

test("게인값 3층 — 자리마다 세 층이 따로 서고, 없는 층은 null이다", () => {
  const m = gainLayersModel(DOC, null, { gainTablesStale: false });
  const byslot = Object.fromEntries(m.slots.map((s) => [s.slot, s]));
  assert.equal(byslot["pitch.k_rate"].seed.value, -0.8);
  assert.equal(byslot["pitch.k_rate"].seed.anchors_used, 2);
  assert.equal(byslot["pitch.k_rate"].seed.basis, "B[q,de]=-12");
  assert.equal(byslot["pitch.k_rate"].seed.kind, "quick_seed");
  assert.equal(byslot["pitch.k_rate"].design, null, "결과를 열지 않았으면 설계층은 없음이다");
  assert.deepEqual(byslot["pitch.k_rate"].confirmed,
    { source: "auto_design", n_knots: 3, stale: false, shape: "table" });
  assert.equal(byslot["roll.ki"].confirmed, null, "표가 없는 자리엔 확정층이 없다");
  assert.equal(byslot["roll.ki"].seed.reason_text, "앵커가 얇다");
  assert.ok(m.notes.some((n) => /설계층은 기록 없음/.test(n)));
});

test("게인값 3층 — 설계층은 루프→자리 표로 접고 가장 나쁜 판정을 싣는다", () => {
  const body = {
    tune_meta: { slots: {
      "M0.3": { pitch_rate: { status: "ok", reason: "ok", target: 0.7, achieved: 0.72 } },
      "M0.6": { pitch_rate: { status: "infeasible", reason: "capped", target: 0.7, achieved: 0.4 } },
    } },
    gain_export: { constants: { "pitch.k_rate": -0.9 } },
    fits: { "pitch.k_rate": { excluded_samples: { "M0.9": { reason: "no_stable_gain" } } } },
  };
  const m = gainLayersModel(DOC, body, { gainTablesStale: false });
  const d = m.slots.find((s) => s.slot === "pitch.k_rate").design;
  assert.equal(d.status, "infeasible");
  assert.equal(d.point, "M0.6");
  assert.equal(d.points, 2);
  assert.equal(d.achieved, 0.4);
  assert.equal(d.value, -0.9);
  assert.equal(d.shape, "constant");
  assert.equal(d.fit_excluded, 1);
  // 적합 보고가 없는 자리는 0이 아니라 모름이다
  const none = gainLayersModel(DOC, { tune_meta: { slots: {} }, gain_export: { constants: {} } });
  assert.equal(none.slots.find((s) => s.slot === "roll.ki").design, null);
});

test("게인값 3층 — 낡음 판정을 브라우저가 짓지 않는다(서버 값이 없으면 모름)", () => {
  const m = gainLayersModel(DOC, null);
  assert.equal(m.slots.find((s) => s.slot === "pitch.k_rate").confirmed.stale, null);
  assert.ok(m.notes.some((n) => /낡음을 말하지 않는다/.test(n)));
});

test("게인값 3층 — 산출 근거 직행(seed_basis)의 묶인 키를 두 자리로 편다", () => {
  // 엔진 design/basis.py는 자세를 "pitch.kp/ki" 한 키에 묶어 적는다 — 안 펴면 그 글자가 자리 이름으로
  // 화면에 서고 정작 pitch.kp·pitch.ki 줄은 「기록 없음」이 된다(실서버 예제 기체에서 자리 9개가 나왔다)
  const doc = { law: { gain_tables: null, design: { provenance: { source: "seed_basis", slots: {
    "pitch.k_rate": { k: 0.111, stored: 0.0896, schedule_factor: 1.245, achieved: 0.849,
      stable: true, budget_ok: true },
    "pitch.kp/ki": { kp: -0.965, ki: -0.349, stored_kp: -0.775, stored_ki: -0.28,
      schedule_factor_kp: 1.245, schedule_factor_ki: 1.245, passing: true, reason: "ok" },
  } } } } };
  const m = gainLayersModel(doc, null);
  const names = m.slots.map((s) => s.slot);
  assert.ok(!names.some((n) => n.includes("/")), `묶인 키가 자리로 섰다: ${names}`);
  const by = Object.fromEntries(m.slots.map((s) => [s.slot, s]));
  assert.equal(by["pitch.kp"].seed.value, -0.775);
  assert.equal(by["pitch.ki"].seed.value, -0.28);
  assert.match(by["pitch.ki"].seed.basis, /한 점 산출 근거 ki=-0.349/);
  assert.equal(by["pitch.kp"].seed.reason, null, "reason \"ok\"는 사유가 아니다");
  assert.equal(by["pitch.k_rate"].seed.value, 0.0896, "문서에 든 값(stored)이다");
  assert.match(by["pitch.k_rate"].seed.basis, /한 점 산출 근거 k=0.111 · 스케줄 배수 1.245/);
  assert.equal(by["pitch.k_rate"].seed.kind, "seed_basis");
  // 모양을 모르는 기록은 값을 짐작하지 않는다
  const odd = gainLayersModel({ law: { gain_tables: null,
    design: { provenance: { source: "손으로", slots: { "roll.kp": { 무엇: 1 } } } } } }, null);
  assert.equal(odd.slots[0].seed.value, null);
  assert.match(odd.slots[0].seed.basis, /짐작하지 않는다/);
});

test("게인값 3층 — 기록이 아무것도 없는 자리는 줄을 만들지 않는다", () => {
  const m = gainLayersModel({ law: { design: null, gain_tables: null } }, null);
  assert.deepEqual(m.slots, []);
});
