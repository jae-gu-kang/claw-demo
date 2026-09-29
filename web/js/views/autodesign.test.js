// 자동 설계 탭 보고서 — 결과가 싣는 사실(작동기·튜닝 실패 표본 제외·적합 보고·원장 fit_excluded·표현별 warn
// 문단)이 **실제로 그려지는가** (node --test, 가짜 DOM·가짜 fetch). 문장 자체는 lib/autodesign.test.js가 본다 —
// 여기는 뷰가 그 함수들을 불러 보고서 자리에 앉히는지(참조 오류·null 조각 없이)만 본다.
import { test } from "node:test";
import assert from "node:assert/strict";

import { installDom } from "./testdom.js";

installDom(); // 뷰 import보다 먼저

const { store } = await import("../store.js");
const { render } = await import("./autodesign.js");

// 실측 모양 — 예제 기체 작은 설정(표 모드) 결과에서 뗀 조각. 예제 기체라 [문서에 반영]은 서지 않는다
// (반영 사전 확인 조회가 안 나간다 — 이 시험의 가짜 서버가 작게 남는다)
const BODY = {
  kind: "auto_design",
  config: { actuator_wn: null, actuator_zeta: null, delay_s: 0.035 },
  report: {
    status: "escalated", stage: "DONE", iterations: 0, judged: 3, failures: 1, fit_mode: "table",
    failures_by_role: { anchor: 1 }, n_points: 2, points: { anchor: 2, breakpoint: 0, validation: 0 },
    excluded_samples: [
      { slot: "roll.k_rate", point: "M0.1_h500_f25", value: 0, loop: "roll_rate", reason: "no_stable_gain", basis: "own" },
      { slot: "roll.kp", point: "M0.1_h500_f25", value: 0.05, loop: "roll_rate", reason: "no_stable_gain", basis: "rate_loop" },
    ],
    exclusion_withheld: ["pitch.ki"],
    actuator: { source: { wn: "profile", zeta: "profile" }, wn: 30, zeta: 0.7, delay_s: 0.035, pade_order: 2 },
    coverage: null, coverage_gaps: [], ledger_size: 1,
    // 이관 2단계 — 요구영역 커버리지: 채택 2 · 요구영역 제외 1(트림하지 않은 점) → 완료 아님
    region_coverage: { source: "profile", confirmed: true, points: 3, complete: false,
      by_category: { adopted: 2, trim: 0, model: 0, limits: 0, region: 1 } },
  },
  points: { points: [
    { name: "M0.1_h500_f25", mach: 0.1, alt: 500, fuel: 25, role: "anchor", trimmable: true },
    { name: "M0.2_h500_f25", mach: 0.2, alt: 500, fuel: 25, role: "anchor", trimmable: true },
    { name: "M0.3_h3000_f25", mach: 0.3, alt: 3000, fuel: 25, role: "anchor", trimmable: false,
      verdict: { adopted: false, exclusion: { category: "region", reasons: ["undefined"] },
        trim: { status: "undefined", reasons: [] } } },
  ] },
  margin_out: { cases: {
    "M0.1_h500_f25": { loops: { roll_rate: { status: "fail" }, pitch_att: { status: "ok" } } },
    "M0.2_h500_f25": { loops: { pitch_att: { status: "warn" } } },
  }, criteria: { pm_min_deg: 45, gm_min_db: 6, gm_good_db: 8, zeta_min: 0.35, zeta_good: 0.7 } },
  fits: {
    "roll.ki": { kind: "table", axis: "mach", axes_excluded: ["alt"], zigzag: 4, n_breakpoints: 14,
      quality: { cross_axis_frac: 0.5531, status: "na" } },
    "pitch.ki": { kind: "table", axis: "mach", n_breakpoints: 3, zigzag: 0, quality: { cross_axis_frac: 0 },
      exclusion_withheld: { kept_would_be: 1, samples: [{}, {}] } },
  },
  ledger: [{ point: "M0.1_h500_f25", loop: "roll_rate", kind: "tune", reason: "no_stable_gain",
    status: "infeasible", severity: null, fit_excluded: ["roll.k_rate", "roll.kp"] }],
  proposed_actions: [{ id: "e1", verdict: "structural_limit", case: "M0.1_h500_f25", loop: "roll_rate",
    action: { type: "escalate" }, evidence: {} }],
  gain_export: { tables: { "roll.ki": {} }, tables_resampled: { "roll.ki": { axes: { mach: [0.1, 0.2] }, data: [1, 2] } },
    constants: {}, reverify: { n_judged: 3, identical: true, note: "반출 표가 세션이 검증한 표와 동일" } },
  profile: { id: "example-delta", is_example: true, source: "request", variant: null },
};

const reply = (status, data) => ({ ok: status < 400, status, text: async () => JSON.stringify(data) });
globalThis.fetch = (url) => {
  const path = url.replace(/^\/api/, "");
  const ok = (data) => Promise.resolve(reply(200, data));
  if (path === "/design/defaults") {
    return ok({ config: { mode: "gated", fit_mode: "table", delay_s: 0.035,
      criteria: { pm_min_deg: 45, gm_min_db: 6 }, targets: { pm_deg: 50, gm_db: 8, zeta_sp: 0.7 } },
    reason_text: { no_stable_gain: "서버 사전 문구" }, grid: { alts: [0, 1000], fuel_fracs: [0.1, 0.5, 1] } });
  }
  if (path.startsWith("/profiles/")) return ok({ document: { mass: { fuel_max: 50 }, actuator: { params: { wn: 30, zeta: 0.7 } } } });
  if (path === "/results") return ok([{ id: "d1", kind: "auto_design", status: "escalated", stage: "DONE" }]);
  if (path === "/results/d1") return ok(BODY);
  return Promise.resolve(reply(404, { detail: `stub에 없는 경로: ${path}` }));
};

const tick = () => new Promise((r) => setTimeout(r, 5));
const textOf = (n) => (typeof n === "string" ? n : n?.nodeType === 3 ? n.data : (n?.children ?? []).map(textOf).join(""));
async function waitFor(cond, what, ms = 2000) {
  for (let t = 0; t < ms; t += 5) {
    if (cond()) return;
    await tick();
  }
  assert.fail(`기다렸지만 오지 않았다: ${what}`);
}

test("보고서에 작동기·표본 제외(보류 포함)·적합 보고·원장 제외 줄·표 모드 warn 문단이 선다", async () => {
  store.set("designOpen", { resultId: "d1" }); // 결과 탭·설계 흐름의 인계 — 한 번 읽고 지운다
  const root = render();
  await waitFor(() => textOf(root).includes("결과 d1"), "인계된 보고서");
  const text = textOf(root);
  assert.match(text, /표현 표\(선형 보간\) · 실패 위치 앵커 1 · 튜닝 실패 표본 제외 2 · 제외 보류 1자리/);
  assert.match(text, /작동기 ωn 30 rad\/s · ζ 0\.700 \(기체 문서\) · 지연 35 ms · Padé 2차/);
  assert.match(text, /pitch\.ki — 튜닝 실패 표본 2개를 빼면 1개만 남아 제외를 보류했다/);
  assert.match(text, /적합에서 뺀 튜닝 표본 2개 — 자리별 내역/);
  assert.match(text, /roll\.kp 1점 — 사유 no_stable_gain 1 · 근거 같은 축 레이트 루프가 실패한 위에서 튜닝 1/);
  assert.match(text, /적합 보고 — 스케줄 축 밖 변동 1\/2자리\(alt\) · 교차축 잔차 최대 55% \(roll\.ki\)/);
  assert.match(text, /적합에서 뺐다 — roll\.k_rate, roll\.kp \(이 점의 스케줄 값은 튜닝값이 아니라 이웃 보간\)/);
  assert.match(text, /적합 허용치 조이기는 표 모드에 없다/);
  // 요구영역 — 부분 성공을 완료로 읽히지 않게, 트림하지 않은 점은 판정 사유로
  assert.match(text, /요구영역 완료 아님 — 미해결 조건 남음/);
  assert.match(text, /요구영역 3점 중 채택 2 · 제외\(트림 0 · 모델 0 · 제한 0 · 요구영역 1\)/);
  assert.match(text, /제외 — 요구영역 판정 대상 아님 — 요구 미정의/);
  assert.match(text, /트림하지 않음 1/);
  // 조건부 조각이 글자 "null"로 새지 않는다 (DOM append(null) 함정)
  assert.doesNotMatch(text, /null|undefined/);
});
