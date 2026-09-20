import assert from "node:assert/strict";
import test from "node:test";

import { resultFreshness } from "./freshness.js";

const ROWS = [
  { id: "alpha", revision: 3, fingerprint: "fp-a3",
    variants: [{ id: "eo", name: "EO형", fingerprint: "fp-a3-eo" }] },
  { id: "broken", unreadable: true, reason: "손상" },
];

test("신선 — 지문이 지금 목록과 같으면 조용하다 (배지 남발 금지)", () => {
  const f = resultFreshness({ id: "alpha", variant: null, revision: 3, fingerprint: "fp-a3" }, ROWS);
  assert.equal(f.state, "fresh");
  assert.equal(f.label, null);
  const v = resultFreshness({ id: "alpha", variant: "eo", revision: 3, fingerprint: "fp-a3-eo" }, ROWS);
  assert.equal(v.state, "fresh");
});

test("낡음 — 계산 시점 리비전·지문과 지금 문서를 함께 말한다", () => {
  const f = resultFreshness({ id: "alpha", variant: null, revision: 1, fingerprint: "fp-a1" }, ROWS);
  assert.equal(f.state, "stale");
  assert.match(f.label, /리비전 1/);
  assert.match(f.label, /fp-a1/);
  assert.match(f.label, /리비전 3/);
  const v = resultFreshness({ id: "alpha", variant: "eo", revision: 2, fingerprint: "fp-old" }, ROWS);
  assert.equal(v.state, "stale");
});

test("지워짐·읽을 수 없음 — 없는 기체와 손상 기체를 가른다 (손상은 id를 점유한 채라 복구 경로가 다르다)", () => {
  assert.equal(resultFreshness({ id: "gone", fingerprint: "x" }, ROWS).state, "gone");
  const b = resultFreshness({ id: "broken", fingerprint: "x" }, ROWS);
  assert.equal(b.state, "unreadable");
  assert.match(b.label, /손상/);
  const v = resultFreshness({ id: "alpha", variant: "ir", fingerprint: "x" }, ROWS);
  assert.equal(v.state, "gone");
  assert.match(v.label, /ir/);
});

test("판정 불가 — 기체 기록 없는 옛 결과·목록 미수신은 모른다고 말한다 (낡음으로 위장 금지)", () => {
  assert.equal(resultFreshness(null, ROWS).state, "unknown");
  assert.equal(resultFreshness({ id: "alpha" }, ROWS).state, "unknown");  // 지문 없는 옛 echo
  assert.equal(resultFreshness({ id: "alpha", fingerprint: "fp-a3" }, null).state, "unknown");
});
