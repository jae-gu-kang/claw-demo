// 기체 탭 평가 기준·튜닝 목표 패널의 판단 — 행·희소 패치·충돌 미리 보기 (node --test, 의존 0)
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  atLeastAsStrict, buildRows, cellOf, commitValue, conflictText, writtenDiffers, directionHint, effectiveCriteria,
  groupOfKey, sectionOf, setCriteriaValue, targetConflicts, writtenValue,
} from "./criteriaedit.js";

// 서버 GET /profiles/{id}/criteria 모양의 축약본 (design.criteria.LINES와 기본값)
const LINES = [
  { metric: "pm_deg", label: "위상여유 PM", unit: "°", direction: "min", pass_key: "pm_min_deg", rec_key: null,
    target_key: "pm_deg", ratio_of_target: false },
  { metric: "gm_db", label: "이득여유 GM", unit: "dB", direction: "min", pass_key: "gm_min_db", rec_key: "gm_good_db",
    target_key: "gm_db", ratio_of_target: false },
  { metric: "zeta_sp", label: "단주기 감쇠 ζ_sp", unit: "", direction: "min", pass_key: "zeta_min",
    rec_key: "zeta_good", target_key: "zeta_sp", ratio_of_target: false },
  { metric: "zeta_dr", label: "더치롤 감쇠 ζ_dr", unit: "", direction: "min", pass_key: "zeta_min",
    rec_key: "zeta_good", target_key: "zeta_dr", ratio_of_target: false },
  { metric: "roll_lambda", label: "롤 수렴 대역폭 λ_roll", unit: "rad/s", direction: "min",
    pass_key: "lam_min_frac", rec_key: "lam_good_frac", target_key: "roll_lambda", ratio_of_target: true },
];
const DEFAULTS = {
  schema_version: 2,
  margin: { pm_min_deg: 45, gm_min_db: 6, pm_bad_deg: 30, gm_good_db: 8, zeta_min: 0.3, zeta_good: 0.5,
    lam_min_frac: 0.5, lam_good_frac: 0.8, lam_part_min: 0.5 },
  fq: { level: "1" },
  targets: { pm_deg: 50, gm_db: 8, zeta_sp: 0.7, zeta_dr: 0.6, roll_lambda: 12, backoff: 0.7 },
  weights: { w_zeta: 1 },
};
const BODY = { lines: LINES, defaults: DEFAULTS };

test("그룹 → 절: targets·weights는 /tuning, 나머지는 /criteria", () => {
  assert.equal(sectionOf("targets"), "tuning");
  assert.equal(sectionOf("weights"), "tuning");
  assert.equal(sectionOf("margin"), "criteria");
  assert.equal(directionHint("min"), "≥");
  assert.equal(directionHint("max"), "≤");
});

test("groupOfKey: 판정선 칸은 튜닝 밖 그룹, 목표 칸은 targets", () => {
  assert.equal(groupOfKey(DEFAULTS, "pm_min_deg"), "margin");
  assert.equal(groupOfKey(DEFAULTS, "pm_deg", { target: true }), "targets");
  assert.equal(groupOfKey(DEFAULTS, "pm_deg"), null); // 목표 칸을 판정선 그룹에서 찾지 않는다
  assert.equal(groupOfKey(DEFAULTS, null), null);
  assert.equal(groupOfKey(DEFAULTS, "nope"), null);
});

test("cellOf: 적은 칸과 기본값 칸을 가른다", () => {
  const doc = { criteria: { margin: { pm_min_deg: 50 } }, tuning: null };
  const a = cellOf(doc, DEFAULTS, "margin", "pm_min_deg");
  assert.deepEqual([a.written, a.value, a.def, a.path], [true, 50, 45, "/criteria/margin/pm_min_deg"]);
  const b = cellOf(doc, DEFAULTS, "targets", "pm_deg");
  assert.deepEqual([b.written, b.value, b.path], [false, 50, "/tuning/targets/pm_deg"]);
  assert.equal(writtenValue(doc, "targets", "pm_deg"), undefined);
  assert.equal(cellOf(doc, DEFAULTS, null, "x"), null);
});

test("buildRows: 판정선마다 합격·권장·목표 칸, 비율 판정선 표시, 공유 칸, 남은 margin 칸", () => {
  const doc = { criteria: { margin: { gm_good_db: 9 }, fq: { level: "2" } }, tuning: { weights: { w_zeta: 2 } } };
  const { rows, extras, others } = buildRows(BODY, doc);
  assert.equal(rows.length, 5);
  const pm = rows[0];
  assert.equal(pm.rec, null); // PM에는 권장선이 없다
  assert.equal(pm.hint, "≥");
  const gm = rows[1];
  assert.deepEqual([gm.rec.written, gm.rec.value], [true, 9]);
  assert.equal(rows[4].ratio, true);
  assert.equal(rows[4].target.key, "roll_lambda");
  assert.deepEqual(rows[2].shared.pass, ["더치롤 감쇠 ζ_dr"]); // zeta_min을 둘이 같이 쓴다
  assert.deepEqual(extras.map((c) => c.key), ["pm_bad_deg", "lam_part_min"]);
  assert.deepEqual(others, ["/criteria/fq/level", "/tuning/weights/w_zeta"]);
});

test("buildRows: 빈 본문이면 빈 표", () => {
  assert.deepEqual(buildRows(null, {}), { rows: [], extras: [], others: [] });
});

test("setCriteriaValue: 희소하게 쓰고 원본은 그대로", () => {
  const doc = { id: "a", criteria: null };
  const next = setCriteriaValue(doc, "margin", "pm_min_deg", 50);
  assert.deepEqual(next.criteria, { margin: { pm_min_deg: 50 } });
  assert.equal(doc.criteria, null);
  assert.equal(next.tuning, undefined); // 건드리지 않은 절은 그대로
  const t = setCriteriaValue(next, "targets", "pm_deg", 55);
  assert.deepEqual(t.tuning, { targets: { pm_deg: 55 } });
});

test("setCriteriaValue: 지우면 빈 그룹은 빠지고 빈 절은 null", () => {
  const doc = { criteria: { margin: { pm_min_deg: 50, gm_min_db: 7 } }, tuning: { targets: { pm_deg: 55 } } };
  const a = setCriteriaValue(doc, "margin", "pm_min_deg", undefined);
  assert.deepEqual(a.criteria, { margin: { gm_min_db: 7 } });
  const b = setCriteriaValue(a, "margin", "gm_min_db", undefined);
  assert.equal(b.criteria, null);
  const c = setCriteriaValue(b, "targets", "pm_deg", undefined);
  assert.equal(c.tuning, null);
});

test("commitValue: 틀린 글은 사유, 적용값과 같고 안 적은 칸은 굳히지 않는다", () => {
  const doc = { criteria: null };
  const cell = cellOf(doc, DEFAULTS, "margin", "pm_min_deg");
  assert.match(commitValue(doc, cell, "abc").error, /pm_min_deg/);
  assert.match(commitValue(doc, cell, "").error, /빈 칸/);
  assert.deepEqual(commitValue(doc, cell, "45"), { noop: true });
  assert.deepEqual(commitValue(doc, cell, " 50 ").doc.criteria, { margin: { pm_min_deg: 50 } });
});

test("effectiveCriteria: 칸 단위로 기본값을 덮는다", () => {
  const eff = effectiveCriteria({ criteria: { margin: { pm_min_deg: 50 } }, tuning: { targets: { pm_deg: 40 } } },
    DEFAULTS);
  assert.equal(eff.margin.pm_min_deg, 50);
  assert.equal(eff.margin.gm_min_db, 6);
  assert.equal(eff.targets.pm_deg, 40);
  assert.equal(eff.targets.gm_db, 8);
  assert.equal("schema_version" in eff, false);
});

test("atLeastAsStrict: min·max 방향, 모르는 방향은 오류", () => {
  assert.equal(atLeastAsStrict("min", 5, 5), true);
  assert.equal(atLeastAsStrict("min", 4, 5), false);
  assert.equal(atLeastAsStrict("max", 4, 5), true);
  assert.equal(atLeastAsStrict("max", 6, 5), false);
  assert.throws(() => atLeastAsStrict("up", 1, 1));
});

test("targetConflicts: 기본값은 충돌 없음", () => {
  assert.deepEqual(targetConflicts(LINES, effectiveCriteria({}, DEFAULTS)), []);
});

test("targetConflicts: 합격선보다 느슨하면 pass 하나만, 권장선만 어기면 rec, 비율 판정선은 빼기", () => {
  const doc = { tuning: { targets: { pm_deg: 40, gm_db: 7, roll_lambda: 0.1 } } };
  const out = targetConflicts(LINES, effectiveCriteria(doc, DEFAULTS));
  assert.deepEqual(out, [
    { metric: "pm_deg", level: "pass", target_key: "pm_deg", target: 40, line_key: "pm_min_deg", line: 45,
      direction: "min" },
    { metric: "gm_db", level: "rec", target_key: "gm_db", target: 7, line_key: "gm_good_db", line: 8,
      direction: "min" },
  ]);
  // 목표가 합격선 아래면 pass 하나만(더 심한 쪽) — 권장선 줄을 겹쳐 내지 않는다
  const two = targetConflicts(LINES, effectiveCriteria({ tuning: { targets: { gm_db: 5 } } }, DEFAULTS));
  assert.deepEqual(two.map((c) => c.level), ["pass"]);
  // 판정선을 올려도 충돌이 된다 (목표는 그대로)
  const up = targetConflicts(LINES, effectiveCriteria({ criteria: { margin: { zeta_min: 0.65, zeta_good: 0.8 } } },
    DEFAULTS));
  assert.deepEqual(up.map((c) => [c.metric, c.level]), [["zeta_sp", "rec"], ["zeta_dr", "pass"]]);
});

test("targetConflicts: max 방향과 잴 수 없는 목표", () => {
  const lines = [{ metric: "ov", label: "오버슈트", direction: "max", pass_key: "ov_max", rec_key: null,
    target_key: "ov", ratio_of_target: false }];
  const applied = { margin: { ov_max: 10 }, targets: { ov: 12 } };
  assert.equal(targetConflicts(lines, applied)[0].level, "pass");
  assert.deepEqual(targetConflicts(lines, { margin: { ov_max: 10 }, targets: { ov: 9 } }), []);
  assert.deepEqual(targetConflicts(lines, { margin: { ov_max: 10 }, targets: { ov: NaN } }), []);
});

test("conflictText: 수준마다 다른 말", () => {
  const [p] = targetConflicts(LINES, effectiveCriteria({ tuning: { targets: { pm_deg: 40 } } }, DEFAULTS));
  assert.match(conflictText(p, LINES), /위상여유 PM.*합격선보다 느슨하다 — 성공한 점이 곧바로 불합격/);
  const [r] = targetConflicts(LINES, effectiveCriteria({ tuning: { targets: { gm_db: 7 } } }, DEFAULTS));
  assert.match(conflictText(r, LINES), /권장선보다 느슨하다 — 성공한 점이 합격·주의/);
});

test("writtenDiffers: 없음·빈 절·키 순서는 같은 것으로 본다", () => {
  const written = { criteria: { margin: { a: 1, b: 2 } }, tuning: null };
  assert.equal(writtenDiffers({ criteria: { margin: { b: 2, a: 1 } } }, written), false);
  assert.equal(writtenDiffers({ criteria: { margin: { a: 1, b: 3 } } }, written), true);
  assert.equal(writtenDiffers({ criteria: null, tuning: {} }, { criteria: null, tuning: null }), false);
  assert.equal(writtenDiffers({ tuning: { targets: { pm_deg: 1 } } }, { criteria: null, tuning: null }), true);
});


test("effectiveCriteria — 축별 한계 칸은 적은 축만 기본값 위에 덧붙는다(서버 from_profile과 같다)", () => {
  const defaults = { response: { rms_max: { alt: 10, spd: 2, hdg: 0.1 } }, margin: { pm_min_deg: 45 } };
  const doc = { criteria: { response: { rms_max: { alt: 5 } } } };
  const eff = effectiveCriteria(doc, defaults);
  assert.deepEqual(eff.response.rms_max, { alt: 5, spd: 2, hdg: 0.1 });
  assert.equal(eff.margin.pm_min_deg, 45);
});
