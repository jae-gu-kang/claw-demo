import assert from "node:assert/strict";
import test from "node:test";

import {
  FLOW_STAGES, applyFreshnessBlock, applyStateVerdict, designVerdict, docVerdict, envelopeVerdict,
  evalVerdict, flowStepStates, flowSummaryLine, latestResultFor, seedStateVerdict, stageArtifact,
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

test("자동 설계 — 실패 0이 곧 「전 판정 통과」가 아니다: 수렴했을 때만 · 미달엔 위치를 붙인다", () => {
  assert.equal(designVerdict({ report: { status: "converged", failures: 0, judged: 435 } }).text,
    "converged — 전 판정 통과");
  // 판정 0(nothing_verified) — 볼 것이 없었다. 종전에는 「nothing_verified — 전 판정 통과」였다
  const nv = designVerdict({ report: { status: "nothing_verified", failures: 0, judged: 0 } });
  assert.equal(nv.text, "nothing_verified — 판정 0: 실패 0은 통과가 아니다(아무것도 검증하지 않았다)");
  assert.doesNotMatch(nv.text, /통과$/);
  // 수렴 전에 멈춘 실행(취소)의 실패 0은 끝까지 보지 않았다는 뜻이다
  const cx = designVerdict({ report: { status: "cancelled", failures: 0, judged: 12 } });
  assert.equal(cx.text, "cancelled — 실패 0이나 수렴 전에 멈췄다");
  assert.equal(cx.tone, "warn");
  // judged가 없는 옛 결과 — 없는 수를 0으로 읽어 「판정 0」이라 단정하지 않는다
  assert.equal(designVerdict({ report: { status: "converged", failures: 0 } }).text, "converged — 전 판정 통과");
  // 미달의 위치 — 앵커(튜닝 성립)인지 검증점(스케줄 성립)인지, 탭 상태 줄과 같은 말
  assert.equal(designVerdict({ report: { status: "escalated", failures: 45, judged: 290,
    failures_by_role: { anchor: 31, validation: 14 } } }).text,
  "escalated — 미달 45건(앵커 31 · 검증점 14) — 자동 설계 탭 원장");
  assert.equal(designVerdict({ report: { status: "escalated", failures: 2, judged: 9 } }).text,
    "escalated — 미달 2건 — 자동 설계 탭 원장");
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

test("채택·반영 상태 — 결과는 있는데 막혔으면 막힌 사유를 말한다(「먼저 돌립니다」가 아니다)", () => {
  // 승인 대기 결과가 있는 흐름 — 종전 뷰는 !applyBlocked(=false)를 넘겨 "먼저 돌립니다"가 떴다
  const blocked = applyStateVerdict(null, true, "승인 대기 결과는 반영하지 않는다");
  assert.equal(blocked.tone, "na");
  assert.match(blocked.text, /승인 대기/);
  assert.doesNotMatch(blocked.text, /먼저/);
  // 결과 없음이면 사유가 있어도 "먼저 돌립니다"
  assert.match(applyStateVerdict(null, false, "자동 설계를 먼저 돌린다").text, /자동 설계를 먼저 돌립니다/);
  // 문서 표가 유효하면 결과·사유와 무관하게 반영됨
  assert.equal(applyStateVerdict({ source: "auto_design", stale: false }, true, "낡음").tone, "ok");
});

test("최근 결과 고르기 — 같은 기체·같은 형상 변형·같은 종류의 첫 행(목록은 최근순)", () => {
  const metas = [
    { id: "r5", kind: "auto_design", profile: { id: "other", variant: null } },
    { id: "r4", kind: "auto_design", profile: { id: "showcase-delta", variant: "eoir" } },
    { id: "r3", kind: "trim_batch", profile: { id: "showcase-delta", variant: null } },
    { id: "r2", kind: "auto_design", profile: { id: "showcase-delta" } },
    { id: "r1", kind: "auto_design", profile: { id: "showcase-delta", variant: null } },
    { id: "r0", kind: "auto_design" },
  ];
  assert.equal(latestResultFor(metas, "auto_design", { id: "showcase-delta", variant: null }).id, "r2");
  assert.equal(latestResultFor(metas, "auto_design", { id: "showcase-delta", variant: "eoir" }).id, "r4");
  assert.equal(latestResultFor(metas, "quick_seed", { id: "showcase-delta" }), null);
  assert.equal(latestResultFor(metas, "auto_design", null), null);
  assert.equal(latestResultFor(null, "auto_design", { id: "x" }), null);
});

test("레일 단계 상태 — 실행 중·판정 tone·안 돌림, apply는 문서 판정, 낡음 대조", () => {
  const stages = {
    doc: { state: "done", verdict: { tone: "warn", text: "통과 — 문서 경고 1건" }, echo: { fingerprint: "a" } },
    envelope: { state: "running" },
    design: { state: "done", verdict: { tone: "warn", text: "escalated" }, echo: { fingerprint: "old" },
      resultId: "r9" },
  };
  const apply = { tone: "ok", text: "문서에 확정 게인 표 반영됨" };
  const steps = flowStepStates(stages, apply, (echo) => (echo.fingerprint === "old" ? "stale" : "fresh"));
  assert.deepEqual(steps.map((s) => [s.key, s.state, s.fresh]), [
    ["doc", "warn", "fresh"], ["envelope", "running", "unknown"], ["seed", "none", "unknown"],
    ["design", "warn", "stale"], ["eval", "none", "unknown"], ["apply", "ok", "unknown"],
  ]);
  assert.equal(steps.find((s) => s.key === "design").resultId, "r9");
  assert.equal(flowSummaryLine(steps),
    "문서 검증 주의 · 엔벨로프 실행 중 · 초기 게인 안 돌림 · 자동 설계 주의(낡음) · 평가 안 돌림"
    + " · 채택·문서 반영 통과");
  assert.equal(flowStepStates({}, null).every((s) => s.state === "none"), true);
});

test("레일 단계 상태 — 반영 직후의 자동 설계는 낡음이 아니라 「문서에 반영됨」 (결과 id가 대조 재료)", () => {
  const stages = {
    design: { state: "done", verdict: { tone: "ok", text: "converged — 전 판정 통과" },
      echo: { fingerprint: "before-apply" }, resultId: "r-ad" },
    eval: { state: "done", verdict: { tone: "ok", text: "하드 게이트 전부 통과" },
      echo: { fingerprint: "before-apply" }, resultId: "r-ev" },
  };
  const apply = { tone: "ok", text: "문서에 확정 게인 표 반영됨" };
  // freshOf는 echo와 **그 단계의 결과 id**를 받는다 — 반영물로 이름 불린 결과만 applied
  const freshOf = (echo, rid) => (echo.fingerprint !== "before-apply" ? "fresh"
    : rid === "r-ad" ? "applied" : "stale");
  const steps = flowStepStates(stages, apply, freshOf);
  assert.equal(steps.find((s) => s.key === "design").fresh, "applied");
  assert.equal(steps.find((s) => s.key === "eval").fresh, "stale"); // 다른 결과는 종전대로
  assert.equal(flowSummaryLine(steps),
    "문서 검증 안 돌림 · 엔벨로프 안 돌림 · 초기 게인 안 돌림 · 자동 설계 통과(문서에 반영됨)"
    + " · 평가 통과(낡음) · 채택·문서 반영 통과");
});

test("반영 관문 신선도 사유 — 이미 반영한 결과와 문서를 고친 결과를 가르되 둘 다 막는다 (서버 지문 가드 409)", () => {
  const applied = applyFreshnessBlock("applied");
  assert.match(applied, /이미 문서에 반영/);
  assert.doesNotMatch(applied, /다르다/); // 반영된 결과에 "문서가 다르다"를 말하지 않는다
  assert.match(applyFreshnessBlock("stale"), /다르다/);
  // 신선·판정 불가·기체 없음은 이 관문이 막지 않는다(다른 관문·서버가 말한다)
  for (const st of ["fresh", "unknown", "gone", "unreadable", undefined]) {
    assert.equal(applyFreshnessBlock(st), null, st);
  }
});
