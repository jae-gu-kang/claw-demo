import assert from "node:assert/strict";
import test from "node:test";

import { deriveSummary, deTrimStatus, designSource, seedSummary } from "./quickseed.js";

const SEED = {
  ok: true, reason: null, reason_text: null, schedule_created: true, elapsed_s: 0.4,
  anchors: [{ name: "M0.35_h1000_f200", qbar: 7777.4 }],
  slots: {
    "roll.kp": { value: 1.2, sign_basis: "B[p,da]=26.92", anchors_used: 2, reason: null },
    "pitch.k_rate": { value: 0.17, sign_basis: "B[q,de]=-35", anchors_used: 3, reason: null },
  },
  warnings: ["M0.2 roll_att: 스케줄 검증 fail"], autopilot_notes: [],
  design: { provenance: { autopilot: { kp_alt: "heuristic", kp_hdg: "heuristic", tau_alt: "registry_default" } } },
};

test("게인 출처 — 미설계·빠른 탐색·그 밖", () => {
  assert.equal(designSource({ law: { design: null } }).kind, "none");
  const q = designSource({ law: { design: { provenance: { source: "quick_seed", ok: true } } } });
  assert.equal(q.seeded, true);
  assert.match(q.label, /자동 설계 전/);
  assert.equal(designSource({ law: { design: { provenance: { source: "example" } } } }).label, "게인 출처: example");
  assert.equal(designSource({ law: { design: { provenance: {} } } }).kind, "unknown");
});

test("탐색 요약 — 저장·충돌·미채택 머리말과 자리 순서", () => {
  const written = seedSummary({ seed: SEED, written: true, profile: { revision: 4 } });
  assert.match(written.headline, /리비전 4로 저장/);
  assert.deepEqual(written.rows.map((r) => r.name), ["pitch.k_rate", "roll.kp"]); // 닫는 순서, 없는 자리는 뺀다
  assert.deepEqual(written.autopilotSources, { heuristic: 2, registry_default: 1 });
  assert.deepEqual(written.anchors, ["M0.35_h1000_f200 (q̄ 7777 Pa)"]);
  assert.equal(written.scheduleCreated, true);

  assert.match(seedSummary({ seed: SEED, written: false, conflict_head: 5 }).headline, /리비전 5가 저장됐습니다/);
  assert.match(seedSummary({ seed: SEED, written: false, conflict_head: null, write_error: "KeyError: 'gone'" }).headline,
    /저장하지 못했습니다 — KeyError/);
  const failed = seedSummary({ seed: { ...SEED, ok: false, reason: "seed_no_anchor", reason_text: "엔벨로프 안 점이 없다" } });
  assert.equal(failed.ok, false);
  assert.match(failed.headline, /채택하지 않았습니다 — 엔벨로프 안 점이 없다/);
  assert.equal(seedSummary({}).ok, false);
});

test("δe_trim 표 상태 — 없음·손으로·도출·낡음(서버 요약이 안다)", () => {
  assert.equal(deTrimStatus({ law: { alloc: null } }).kind, "none");
  const doc = (source) => ({ law: { alloc: { de_trim: { source } } } });
  assert.equal(deTrimStatus(doc("explicit"), { de_trim: { stale: true } }).kind, "explicit"); // 손으로 넣은 표는 대조 기록이 없다
  assert.equal(deTrimStatus(doc("derived"), { de_trim: { source: "derived", stale: false } }).kind, "derived");
  const stale = deTrimStatus(doc("derived"), { de_trim: { source: "derived", stale: true } });
  assert.equal(stale.stale, true);
  assert.match(stale.label, /다시 도출/);
  const variant = deTrimStatus(doc("derived"), { de_trim: { source: "derived", stale: false, stale_variants: ["heavier"] } });
  assert.equal(variant.stale, true); // 기본 문서는 멀쩡해도 새 플랜트 변형은 막힌다
  assert.match(variant.label, /heavier/);
});

test("도출 요약 — 표 줄과 검사 통계", () => {
  const body = { written: true, profile: { revision: 3 }, derive: {
    ok: true, requirement: { mach: [0.2, 0.22, 0.24] },
    alloc: { de_trim: { table: { axes: { mach: [0.2, 0.3] }, data: [0.25, 0.19] },
      provenance: { shortfall: 0, excess_max: 0.004, iterations: 2, excluded_trims: 5, undefined_machs: [] } } } } };
  const s = deriveSummary(body);
  assert.match(s.headline, /리비전 3로 저장/);
  assert.deepEqual(s.rows, [{ mach: 0.2, value: 0.25 }, { mach: 0.3, value: 0.19 }]);
  assert.deepEqual(s.stats, { checks: 3, shortfall: 0, excessMax: 0.004, iterations: 2, excluded: 5, undefined: [] });
  const failed = deriveSummary({ derive: { ok: false, reason: "de_trim_no_requirement", reason_text: "트림이 없다" } });
  assert.equal(failed.stats, null);
  assert.match(failed.headline, /트림이 없다/);
});
