import assert from "node:assert/strict";
import test from "node:test";

import {
  FLOW_STAGES, applyStateVerdict, designVerdict, docVerdict, envelopeVerdict,
  evalVerdict, seedStateVerdict,
} from "./flowsteps.js";

test("단계 순서 — 실행 다섯 + 수동 관문 하나, apply만 manual", () => {
  assert.deepEqual(FLOW_STAGES.map((s) => s.key),
    ["doc", "envelope", "seed", "design", "eval", "apply"]);
  assert.deepEqual(FLOW_STAGES.filter((s) => s.manual).map((s) => s.key), ["apply"]);
  for (const s of FLOW_STAGES) assert.ok(s.tab.startsWith("#"), s.key);
});

test("문서 검증 — 경고는 통과이되 수를 말한다", () => {
  assert.equal(docVerdict({ ok: true, warnings: [] }).tone, "ok");
  const w = docVerdict({ ok: true, warnings: ["저속 가림"] });
  assert.equal(w.tone, "warn");
  assert.match(w.text, /1건/);
  assert.equal(docVerdict({ ok: false }).tone, "bad");
  assert.equal(docVerdict(null).tone, "bad");
});

test("엔벨로프 — 컬럼형 region(empty[])에서 성립 고도 수와 자리표시 한계", () => {
  const region = { alt: [0, 1000, 3000], empty: [false, true, false] };
  const ok = envelopeVerdict({ region, limits_source: "profile" });
  assert.equal(ok.tone, "ok");
  assert.match(ok.text, /2\/3줄/);
  const ph = envelopeVerdict({ region, limits_source: "demo-placeholder" });
  assert.equal(ph.tone, "warn");
  assert.match(ph.text, /자리표시/);
  assert.equal(envelopeVerdict({ region: { alt: [0], empty: [true] } }).tone, "bad");
  assert.equal(envelopeVerdict({ region: { alt: [], empty: [] } }).tone, "na");
  assert.equal(envelopeVerdict({}).tone, "na");
});

test("초기 게인 — 미설계만 탐색을 돌린다", () => {
  const run = seedStateVerdict(null);
  assert.equal(run.run, true);
  const skip = seedStateVerdict("quick_seed");
  assert.equal(skip.run, false);
  assert.match(skip.text, /quick_seed/);
});

test("자동 설계 — 승인 대기는 흐름을 멈추는 관문", () => {
  const gate = designVerdict({ report: { status: "awaiting_approval" } });
  assert.equal(gate.stop, true);
  assert.equal(gate.tone, "warn");
  assert.equal(designVerdict({ report: { status: "converged", failures: 0 } }).tone, "ok");
  const f = designVerdict({ report: { status: "converged", failures: 3 } });
  assert.equal(f.tone, "warn");
  assert.match(f.text, /3건/);
  assert.equal(designVerdict({}).tone, "na");
});

test("평가 — 하드 게이트가 최종선, 케이스 0은 보류(na)", () => {
  assert.equal(evalVerdict({ aggregate: { hard_fail: null } }).tone, "na");
  const bad = evalVerdict({ aggregate: { hard_fail: true, hard_fails: [1, 2] }, depth: "full" });
  assert.equal(bad.tone, "bad");
  assert.match(bad.text, /2건/);
  assert.equal(evalVerdict({ aggregate: { hard_fail: false }, depth: "full" }).tone, "ok");
});

test("채택·반영 — 확정 표 상태와 설계 결과 유무로 관문 상태를 말한다", () => {
  assert.equal(applyStateVerdict({ source: "auto_design", stale: false }, true).tone, "ok");
  assert.equal(applyStateVerdict({ source: "auto_design", stale: true }, true).tone, "warn");
  const ready = applyStateVerdict(null, true);
  assert.equal(ready.tone, "na");
  assert.match(ready.text, /문서에 반영/);
  assert.match(applyStateVerdict(null, false).text, /먼저/);
});
