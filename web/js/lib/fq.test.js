// 비행성 수준 표시 계층 검증 — 키 사상, 모드별 최악, 근거 수치 문장, 판정선 범례
import { test } from "node:test";
import assert from "node:assert/strict";

import { FQ_BADGE, FQ_MODES, fqKey, fqLegendText, fqMeasureText, fqWorst } from "./fq.js";

test("fqKey: 수준·수준 밖·판정 없음을 구분한다", () => {
  assert.equal(fqKey({ level: 1 }), 1);
  assert.equal(fqKey({ level: 3 }), 3);
  assert.equal(fqKey({ level: null, t2_s: 2.0 }), "out"); // 쟀는데 최하 미달
  assert.equal(fqKey(null), "na"); // 잰 것이 없다
  assert.equal(fqKey(undefined), "na"); // 구버전 결과 (fq 블록 자체가 없음)
});

test("FQ_BADGE: 다섯 키 전부 라벨·축약·색을 가진다 — 「수준 밖」 축약은 「밖」이다", () => {
  for (const k of [1, 2, 3, "out", "na"]) {
    assert.ok(FQ_BADGE[k].label && FQ_BADGE[k].short && FQ_BADGE[k].color, String(k));
  }
  // 문자열 치환으로 만들면 "수준 밖"이 "수준 "을 포함해 "L밖"이 된다 — 명시 맵이 정본
  assert.equal(FQ_BADGE.out.short, "밖");
  assert.equal(FQ_BADGE[1].short, "L1");
});

const entry = (name, lonFq, latFq) => ({
  trim: { case: { name, mach: 0.4, alt: 1000, fuel: 200 } },
  lon: lonFq ? { fq: lonFq } : null,
  lat: latFq ? { fq: latFq } : null,
});

test("fqWorst: 모드별 최악 수준과 그 케이스 — na는 최악 후보가 아니다", () => {
  const rows = fqWorst([
    entry("a", { short_period: { level: 1, zeta: 0.5 }, phugoid: { level: 2, zeta: 0.01 } },
      { dutch_roll: { level: 1 }, roll: { level: 1, tau_s: 0.5 }, spiral: { level: 1, stable: true, t2_s: null } }),
    entry("b", { short_period: { level: 2, zeta: 0.22 }, phugoid: { level: 1, zeta: 0.06 } },
      { dutch_roll: { level: null }, roll: { level: 1, tau_s: 0.4 }, spiral: { level: 2, stable: false, t2_s: 14.0 } }),
    entry("c", null, null), // 트림 불가 — 전 모드 na
  ]);
  const by = Object.fromEntries(rows.map((r) => [r.mode, r]));
  assert.equal(by.short_period.key, 2);
  assert.equal(by.short_period.caseName, "b");
  assert.equal(by.dutch_roll.key, "out"); // 수준 밖이 수준 2보다 나쁘다
  assert.equal(by.spiral.key, 2);
  assert.equal(by.spiral.j.t2_s, 14.0); // v1.10에서 손으로 찾던 "가장 짧은 T₂"
  assert.deepEqual(rows.map((r) => r.mode), FQ_MODES.map(([m]) => m)); // 표 열 순서
});

test("fqWorst: 전 케이스 na면 na로 남는다 — 없는 판정을 지어내지 않는다", () => {
  const rows = fqWorst([entry("a", null, null)]);
  assert.ok(rows.every((r) => r.key === "na" && r.j === null));
});

test("fqWorst: 같은 수준끼리는 측정값이 나쁜 쪽 — 먼저 온 케이스가 대표를 가리지 않는다", () => {
  const lat = (spiral, roll) => ({ dutch_roll: { level: 1, zeta: 0.2 }, roll, spiral });
  const rows = fqWorst([
    // 나선 T₂ 19 s와 8.5 s가 둘 다 수준 2 — 실제 최악은 8.5 s다
    entry("a", null, lat({ level: 2, stable: false, t2_s: 19.0 }, { level: 1, tau_s: 0.4 })),
    entry("b", null, lat({ level: 2, stable: false, t2_s: 8.5 }, { level: 1, tau_s: 1.2 })),
  ]);
  const by = Object.fromEntries(rows.map((r) => [r.mode, r]));
  assert.equal(by.spiral.caseName, "b");
  assert.equal(by.spiral.j.t2_s, 8.5);
  assert.equal(by.roll.caseName, "b"); // 롤은 τ 큰 쪽
  // 안정 나선(수준 1)은 발산 수준 1(T₂ ≥ 20 s)보다 나쁘지 않다
  const rows2 = fqWorst([
    entry("c", null, lat({ level: 1, stable: false, t2_s: 25.0 }, { level: 1, tau_s: 0.4 })),
    entry("d", null, lat({ level: 1, stable: true, t2_s: null }, { level: 1, tau_s: 0.4 })),
  ]);
  assert.equal(rows2.find((r) => r.mode === "spiral").caseName, "c");
});

test("fqWorst: ζ 축 모드의 동률은 ζ 작은 쪽 — 부호가 뒤집히면 여기서 잡힌다", () => {
  // 리뷰 W1: worseness의 -(j.zeta)가 +로 퇴화해도 기존 동률 테스트는 전부 통과했다 — ζ 축을 핀한다
  const rows = fqWorst([
    entry("a", { short_period: { level: 2, zeta: 0.28 }, phugoid: { level: 1, zeta: 0.09, t2_s: null } },
      { dutch_roll: { level: 2, zeta: 0.05, wn: 1.0, zwn: 0.05 }, roll: { level: 1, tau_s: 0.4 },
        spiral: { level: 1, stable: true, t2_s: null } }),
    entry("b", { short_period: { level: 2, zeta: 0.22 }, phugoid: { level: 1, zeta: 0.05, t2_s: null } },
      { dutch_roll: { level: 2, zeta: 0.03, wn: 1.4, zwn: 0.042 }, roll: { level: 1, tau_s: 0.4 },
        spiral: { level: 1, stable: true, t2_s: null } }),
  ]);
  const by = Object.fromEntries(rows.map((r) => [r.mode, r]));
  assert.equal(by.short_period.caseName, "b"); // ζ 0.22 < 0.28
  assert.equal(by.phugoid.caseName, "b"); // 안정 장주기 — ζ 0.05 < 0.09
  assert.equal(by.dutch_roll.caseName, "b"); // ζ 0.03 < 0.05
});

test("fqMeasureText: 모드별 근거 수치 — 나선은 안정/T₂를 가른다", () => {
  assert.equal(fqMeasureText("spiral", { stable: true, t2_s: null }), "안정");
  assert.match(fqMeasureText("spiral", { stable: false, t2_s: 14.04 }), /T₂ 14 s/);
  assert.match(fqMeasureText("roll", { tau_s: 0.5 }), /τ 0.5 s/);
  assert.equal(fqMeasureText("roll", { tau_s: null }), "발산 실근");
  assert.match(fqMeasureText("phugoid", { t2_s: 60.0 }), /발산 T₂ 60 s/);
  assert.match(fqMeasureText("dutch_roll", { zeta: 0.05, wn: 1.2, zwn: 0.06 }), /ζ 0.05/);
  assert.equal(fqMeasureText("spiral", null), "");
});

test("fqLegendText: 서버 동봉 판정선으로 문장을 만든다 — 수치 재기술 없음", () => {
  const c = {
    fingerprint: "abc123",
    sp_zeta_l1_lo: 0.3, sp_zeta_l1_hi: 2.0, sp_zeta_l2_lo: 0.2, sp_zeta_l2_hi: 2.0, sp_zeta_l3_lo: 0.15,
    ph_zeta_l1: 0.04, ph_t2_l3: 55.0,
    dr_zeta_l1: 0.08, dr_zwn_l1: 0.15, dr_wn_l1: 0.4,
    dr_zeta_l2: 0.02, dr_zwn_l2: 0.05, dr_wn_l2: 0.4, dr_zeta_l3: 0, dr_wn_l3: 0.4,
    roll_tau_l1: 1.4, roll_tau_l2: 3.0, roll_tau_l3: 10.0,
    spiral_t2_l1: 20.0, spiral_t2_l2: 8.0, spiral_t2_l3: 4.0,
  };
  const text = fqLegendText(c);
  assert.match(text, /나선 T₂ ≥ 20 \/ 8 \/ 4 s/);
  assert.match(text, /abc123/); // 계보 지문 노출
  // 구버전 결과(판정선 미동봉)는 그 사실을 말한다 — 조용한 생략 금지
  assert.match(fqLegendText(null), /판정선 정보가 없습니다/);
});
