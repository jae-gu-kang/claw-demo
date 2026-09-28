import { readFileSync } from "node:fs";
import assert from "node:assert/strict";
import test from "node:test";

import {
  deriveSummary, deTrimStatus, designSource, gainTablesStatus, seedSummary, variantTableSource,
} from "./quickseed.js";

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
  // 산출 근거 직행 저장(v1.34) — 검증 전임을 출처 줄이 말한다
  const b = designSource({ law: { design: { provenance: { source: "seed_basis" } } } });
  assert.equal(b.kind, "seed_basis");
  assert.match(b.label, /검증 전/);
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


test("확정 게인 표 상태 — 없음·정상·낡음 (판정은 서버 요약 그대로)", () => {
  assert.equal(gainTablesStatus(null).kind, "none");
  assert.equal(gainTablesStatus({ gain_tables: null }).kind, "none");
  const ok = gainTablesStatus({ gain_tables: { source: "auto_design", stale: false } });
  assert.equal(ok.kind, "ok");
  assert.match(ok.label, /auto_design/);
  const stale = gainTablesStatus({ gain_tables: { source: "auto_design", stale: true } });
  assert.equal(stale.kind, "stale");
  assert.equal(stale.stale, true);
  assert.match(stale.label, /낡았습니다/);
  assert.match(gainTablesStatus({ gain_tables: { source: null, stale: false } }).label, /기록 없음/);
  // 기본은 신선한데 변형에서만 낡음 — 그 변형 이름을 미리 말한다(변형 계산 422가 첫 통보가 되지 않게)
  const v = gainTablesStatus({ gain_tables: { source: "auto_design", stale: false, stale_variants: ["heavy"] } });
  assert.equal(v.kind, "ok");
  assert.deepEqual(v.staleVariants, ["heavy"]);
  assert.match(v.label, /heavy/);
});

// 쇼케이스 EO/IR형 — 변형 패치가 /law/gain_tables를 비워 규칙 스케줄로 난다(기본형 행은 「확정 표 사용」)
const s1Row = (variants) => ({
  variants: [{ id: "eoir", name: "EO/IR형", fingerprint: "847d" }],
  gain_tables: { source: "auto_design", stale: false, stale_variants: [], ...(variants ? { variants } : {}) },
});

test("확정 게인 표 상태 — 고른 형상 변형은 서버 변형별 출처대로 (EO/IR형은 규칙 스케줄)", () => {
  const rule = gainTablesStatus(s1Row({ eoir: { source: "rule_schedule" } }), { variant: "eoir" });
  assert.equal(rule.kind, "rule");
  assert.equal(rule.stale, false);
  assert.equal(rule.label, "고른 형상 변형(「EO/IR형」)은 규칙 스케줄(설계 게인 × q̄ 역비)로 납니다 — "
    + "확정 게인 표는 기본형 설계 결과(출처 auto_design)이고 이 변형은 그 표를 쓰지 않습니다");
  assert.doesNotMatch(rule.label, /이 표를 씁니다/);
  // 서버 판정이 문서 추정보다 앞선다 — 문서가 표를 가진 듯 보여도 서버가 낡음이라 하면 낡음
  const st = gainTablesStatus(s1Row({ eoir: { source: "stale" } }), { variant: "eoir", effectiveTables: {} });
  assert.equal(st.kind, "stale");
  assert.match(st.label, /「EO\/IR형」\)에서는 낡았습니다/);
  assert.equal(gainTablesStatus(s1Row({ eoir: { source: "confirmed" } }), { variant: "eoir" }).kind, "ok");
  assert.match(gainTablesStatus(s1Row({ eoir: { source: "confirmed" } }), { variant: "eoir" }).label,
    /「EO\/IR형」\)도 조립이 규칙 스케줄 대신 이 표를 씁니다/);
  assert.equal(gainTablesStatus(s1Row({ eoir: { source: "none" } }), { variant: "eoir" }).kind, "none");
  // 변형을 안 고르면 기본형 문구 그대로
  assert.equal(gainTablesStatus(s1Row({ eoir: { source: "rule_schedule" } })).kind, "ok");
});

test("확정 게인 표 상태 — 변형별 출처가 없는 서버면 낡은 변형 목록과 변형 문서의 표 자리로 가린다", () => {
  // 변형 패치가 표를 비웠다(effectiveTables null) — 규칙 스케줄
  assert.equal(gainTablesStatus(s1Row(), { variant: "eoir", effectiveTables: null }).kind, "rule");
  // 낡은 변형 목록(서버 판정)이 먼저
  const stale = { ...s1Row(), gain_tables: { ...s1Row().gain_tables, stale_variants: ["eoir"] } };
  assert.equal(gainTablesStatus(stale, { variant: "eoir", effectiveTables: { tables: {} } }).kind, "stale");
  assert.equal(gainTablesStatus(s1Row(), { variant: "eoir", effectiveTables: { tables: {} } }).kind, "ok");
  // 둘 다 모르면 기본형 문구에 단서를 단다 — 「이 표를 씁니다」를 변형의 사실처럼 말하지 않는다
  const unk = gainTablesStatus(s1Row(), { variant: "eoir" });
  assert.equal(unk.kind, "ok");
  assert.match(unk.label, /기본형 기준 — 고른 형상 변형\(「EO\/IR형」\)의 조립이 이 표를 쓰는지는 목록 요약에 없습니다/);
  // 기본형에 표가 없으면 변형도 없음(변형이 제 표를 들고 있으면 모름)
  assert.equal(variantTableSource(null, "eoir", null), "none");
  assert.equal(variantTableSource(null, "eoir", undefined), "none");
  assert.equal(variantTableSource(null, "eoir", { tables: {} }), null);
  // 알 수 없는 출처 값은 무시하고 다른 사실로
  assert.equal(variantTableSource({ variants: { eoir: { source: "bogus" } }, stale_variants: [] }, "eoir", null),
    "rule_schedule");
});

// 뷰는 DOM을 모듈 스코프에서 만져 import할 수 없다 — 배선은 원문에서 읽는다(influence.test.js와 같은 가드)
test("확정 게인 표 배너 배선 — 기체 탭·게인 탭이 고른 형상 변형을 넘긴다", () => {
  const aircraft = readFileSync(new URL("../views/aircraft.js", import.meta.url), "utf8");
  // 기체 탭: 연 기체가 고른 기체면 그 형상 변형 + 저장 문서에 변형을 적용한 표 자리
  assert.match(aircraft, /const gt = gainTablesStatus\(summary, selVariant\s*\? \{ variant: selVariant, effectiveTables: effectiveOf\(doc, selVariant\)\?\.law\?\.gain_tables \?\? null \} : \{\}\);/);
  assert.doesNotMatch(aircraft, /gainTablesStatus\(summary\);/, "기본형 행의 상태를 변형에 그대로 단다");
  const gains = readFileSync(new URL("../views/gains.js", import.meta.url), "utf8");
  // 게인 탭: 카탈로그(변형 적용 문서)에 확정 표가 없고 변형을 골랐으면 목록 요약으로 「규칙 스케줄」을 말한다
  assert.match(gains, /import \{ gainTablesStatus \} from "\.\.\/lib\/quickseed\.js";/);
  assert.match(gains, /if \(!c\) \{[\s\S]{0,600}?gainTablesStatus\(row, \{ variant: sel\.variant, effectiveTables: null \}\)[\s\S]{0,200}?st\.kind !== "rule"/);
});
