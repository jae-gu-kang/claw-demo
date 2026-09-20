import assert from "node:assert/strict";
import test from "node:test";

import {
  FLOW_STAGES, applyStateVerdict, designVerdict, docVerdict, envelopeVerdict,
  evalVerdict, seedStateVerdict, stageArtifact,
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

test("단계 산출물 — 어디에 남았나(다이어그램 발치줄), 안 쓴 문서·없는 결과는 위조하지 않는다", () => {
  assert.deepEqual(stageArtifact("doc", null), [{ label: "저장 없음 — 문서 판정만", to: null }]);
  assert.deepEqual(stageArtifact("envelope", {}), [{ label: "저장 없음 — 조회 계산", to: null }]);
  assert.deepEqual(stageArtifact("design", null), [{ label: "결과 저장소(잡 산출물)", to: null }]);
  assert.deepEqual(stageArtifact("design", { resultId: "abc123" }),
    [{ label: "결과 abc123", to: "design" }]);
  assert.deepEqual(stageArtifact("eval", { resultId: "e1" }), [{ label: "결과 e1", to: "brief" }]);
  // 시드 — 채택·저장(ok)이면 결과와 문서 리비전 둘 다, 미채택(bad)이면 결과만
  assert.deepEqual(stageArtifact("seed", { resultId: "r1", verdict: { tone: "ok" }, echo: { revision: 3 } }),
    [{ label: "결과 r1", to: "brief" }, { label: "문서 리비전 3에 저장", to: "aircraft" }]);
  assert.deepEqual(stageArtifact("seed", { resultId: "r1", verdict: { tone: "bad" }, echo: { revision: 2 } }),
    [{ label: "결과 r1", to: "brief" }]);
  assert.deepEqual(stageArtifact("seed", { verdict: { tone: "ok" } }),
    [{ label: "저장 없음 — 미실행·탐색 생략", to: null }]);
  // apply는 목적지 프레이밍 — "저장됐다"가 아니라 "쓰는 곳"(반영 여부는 판정 칩 몫)
  assert.deepEqual(stageArtifact("apply", null),
    [{ label: "쓰는 곳 — 문서 law.gain_tables(확정 표)", to: "gains" }]);
});
