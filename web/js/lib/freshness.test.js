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

test("문서에 반영됨 — 자동 설계 결과 자신의 표 반영만으로 달라진 문서는 낡음이 아니다 (그 결과만)", () => {
  // 반영(apply-gains)이 표를 써서 지문이 바뀐 뒤 — 서버 목록이 applied_design으로 그 결과를 이름 댄다
  const rows = [{ id: "alpha", revision: 5, fingerprint: "fp-a5", variants: [],
    applied_design: { result_id: "r-ad", revision: 5 } }];
  const echo = { id: "alpha", variant: null, revision: 4, fingerprint: "fp-a4" };
  const f = resultFreshness(echo, rows, "r-ad");
  assert.equal(f.state, "applied");
  assert.match(f.label, /리비전 5/);   // 반영한 리비전
  assert.match(f.label, /리비전 4/);   // 계산 시점
  assert.match(f.label, /자신의/);     // 달라진 것이 제 산출물뿐이라는 사실
  // 같은 문서로 계산한 **다른** 결과(트림·마진·시뮬, 다른 자동 설계)는 종전대로 낡음 — 표가 그 계산을 바꾼다
  assert.equal(resultFreshness(echo, rows, "r-trim").state, "stale");
  // 결과 id를 안 넘기는 호출자는 종전 판정 그대로
  assert.equal(resultFreshness(echo, rows).state, "stale");
  // 변형 위에서 돈 결과는 기본 문서 반영물일 수 없다(서버 422) — 이름이 같아도 낡음
  const vrows = [{ ...rows[0], variants: [{ id: "eo", fingerprint: "fp-a5-eo" }] }];
  assert.equal(resultFreshness({ ...echo, variant: "eo" }, vrows, "r-ad").state, "stale");
  // 서버가 이름 대지 않으면(표를 손으로 고침·표 밖 편집 — applied_design null) 낡음
  assert.equal(resultFreshness(echo, [{ ...rows[0], applied_design: null }], "r-ad").state, "stale");
  // 지문이 같으면 여전히 조용한 신선이다(반영됨 배지 남발 금지)
  assert.equal(resultFreshness({ ...echo, fingerprint: "fp-a5" }, rows, "r-ad").state, "fresh");
});

test("판정 불가 — 기체 기록 없는 옛 결과·목록 미수신은 모른다고 말한다 (낡음으로 위장 금지)", () => {
  assert.equal(resultFreshness(null, ROWS).state, "unknown");
  assert.equal(resultFreshness({ id: "alpha" }, ROWS).state, "unknown");  // 지문 없는 옛 echo
  assert.equal(resultFreshness({ id: "alpha", fingerprint: "fp-a3" }, null).state, "unknown");
});
