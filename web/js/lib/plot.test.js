// 플롯 수치 계층 검증 — 스케일, 눈금, 마진 상태색, 마진 맵 격자 피벗
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  fuelsOf,
  linScale,
  marginColor,
  niceTicks,
  pivotCases,
  trimEnvelopeCell,
} from "./plot.js";

test("linScale: 선형 사상·역방향 범위", () => {
  const s = linScale(0, 10, 0, 100);
  assert.equal(s(5), 50);
  const flip = linScale(0, 10, 100, 0); // 캔버스 y축 (아래로 증가)
  assert.equal(flip(0), 100);
  assert.equal(flip(10), 0);
});

test("niceTicks: 1-2-5 스텝, 범위 포함", () => {
  assert.deepEqual(niceTicks(0, 10, 5), [0, 2, 4, 6, 8, 10]);
  assert.deepEqual(niceTicks(0.4, 0.8, 5), [0.4, 0.5, 0.6, 0.7, 0.8]);
  assert.deepEqual(niceTicks(5, 5, 5), [5]); // 퇴화 구간
});

test("marginColor: 여유 구간 상태색 + 비유한값 정책", () => {
  assert.equal(marginColor(60), "#157f3d"); // 양호 (≥45°)
  assert.equal(marginColor(35), "#b57908"); // 주의 (30~45°)
  assert.equal(marginColor(10), "#c22f2f"); // 부족 (<30°)
  assert.equal(marginColor("inf"), "#157f3d"); // 무한 여유
  assert.equal(marginColor(null), "#9aa3ad"); // 판정 불가 (NaN 직렬화)
});

test("trimEnvelopeCell: 판정 우선순위 — 불가 > 실속 근접 > 포화 > 가능", () => {
  const base = { residual_ok: true, saturation_ok: true, alpha_margin_ok: true,
                 continuity_ok: true };
  const cell = (converged, flags) => trimEnvelopeCell({ converged, flags });
  assert.equal(cell(true, base).kind, "ok");
  assert.equal(cell(false, base).kind, "infeasible"); // 미수렴
  assert.equal(cell(true, { ...base, residual_ok: false }).kind, "infeasible");
  // α 여유 위반이 포화보다 우선 (더 치명적 — 실속 경계 접근)
  assert.equal(
    cell(true, { ...base, alpha_margin_ok: false, saturation_ok: false }).kind,
    "stall",
  );
  assert.equal(cell(true, { ...base, saturation_ok: false }).kind, "saturated");
  // 연속성 미판정(null)은 가능 판정에 영향 없음 (3-상태)
  assert.equal(cell(true, { ...base, continuity_ok: null }).kind, "ok");
  // 색·라벨 존재
  const c = cell(true, base);
  assert.ok(c.color.startsWith("#") && c.text.length > 0);
});


function entry(mach, alt, fuel, pm) {
  return {
    trim: { case: { mach, alt, fuel }, converged: true },
    margins: { pitch_q: { pm_deg: pm } },
  };
}

test("pivotCases: 연료 필터 + 축 정렬 + 조회", () => {
  const entries = [
    entry(0.6, 1000, 200, 50), entry(0.4, 1000, 200, 40),
    entry(0.4, 100, 200, 45), entry(0.6, 100, 200, 55),
    entry(0.5, 1000, 300, 60), // 다른 연료 — 제외돼야 함
  ];
  const p = pivotCases(entries, 200);
  assert.deepEqual(p.machs, [0.4, 0.6]);
  assert.deepEqual(p.alts, [100, 1000]);
  assert.equal(p.at(0.4, 1000).margins.pitch_q.pm_deg, 40);
  assert.equal(p.at(0.5, 1000), null); // 빈 셀
  assert.deepEqual(fuelsOf(entries), [200, 300]);
});
