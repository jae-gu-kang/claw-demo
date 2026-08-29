// 트림 격자 생성 검증 — 부동소수 라운딩, 서펜타인 인접성, 수치 목록 파싱
import { test } from "node:test";
import assert from "node:assert/strict";

import { machRange, nameCases, parseNumberList, serpentineCases } from "./grid.js";

test("machRange: 부동소수 오차 없는 등간격", () => {
  assert.deepEqual(machRange(0.4, 0.8, 0.1), [0.4, 0.5, 0.6, 0.7, 0.8]);
  // 0.4 + 7×0.05 = 0.7500000000000001 방지
  assert.deepEqual(machRange(0.4, 0.55, 0.05), [0.4, 0.45, 0.5, 0.55]);
  assert.deepEqual(machRange(0.6, 0.6, 0.1), [0.6]); // 단일점
  assert.throws(() => machRange(0.8, 0.4, 0.1)); // 역순
  assert.throws(() => machRange(0.4, 0.8, 0)); // step 0
});

test("serpentineCases: 행 경계에서 마하 연속 (인접 시드 전제, 01 §4.1)", () => {
  const cases = serpentineCases([0.4, 0.5, 0.6], [100, 1000], [200]);
  assert.equal(cases.length, 6);
  assert.deepEqual(cases[0], { mach: 0.4, alt: 100, fuel: 200 });
  assert.deepEqual(cases[2], { mach: 0.6, alt: 100, fuel: 200 });
  // 다음 행은 역순 시작 — 리스트상 인접 케이스가 물리적으로도 인접
  assert.deepEqual(cases[3], { mach: 0.6, alt: 1000, fuel: 200 });
  assert.deepEqual(cases[5], { mach: 0.4, alt: 1000, fuel: 200 });
});

test("serpentineCases: 연료 축 포함 시 행 교대 지속", () => {
  const cases = serpentineCases([0.4, 0.5], [100], [200, 300]);
  assert.deepEqual(
    cases.map((c) => [c.mach, c.fuel]),
    [[0.4, 200], [0.5, 200], [0.5, 300], [0.4, 300]]
  );
});

test("nameCases: 값 그대로 이름 — 정밀 격자에서도 유일 (반올림 이름은 겹친다)", () => {
  const named = nameCases(serpentineCases([0.4, 0.5], [1000], [200]));
  assert.deepEqual(named.map((c) => c.name),
    ["M0.4_h1000_f200", "M0.5_h1000_f200"]);
  assert.deepEqual(named[0], { name: "M0.4_h1000_f200", mach: 0.4, alt: 1000, fuel: 200 });
  // 간격 0.005 → 81케이스: toFixed(2) 이름이면 41개로 뭉개지던 격자 — 전부 유일해야 한다
  const fine = nameCases(serpentineCases(machRange(0.4, 0.8, 0.005), [1000], [200]));
  assert.equal(new Set(fine.map((c) => c.name)).size, fine.length);
  // 입력에 name이 있어도 검증한 이름이 이긴다 — 아니면 검증한 이름과 반환한
  // 이름이 다른 객체가 나온다 (유일성 보장이 무의미해진다)
  assert.equal(
    nameCases([{ mach: 0.5, alt: 1000, fuel: 200, name: "stale" }])[0].name,
    "M0.5_h1000_f200");
});

test("nameCases: 중복 이름은 던진다 — 겹친 이름은 Δ의 base 귀속을 오염시킨다", () => {
  assert.throws(
    () => nameCases(serpentineCases([0.5], [1000, 1000], [200])),
    /케이스 이름 중복/);
});

test("parseNumberList: 콤마·공백 구분, 비수치 거부", () => {
  assert.deepEqual(parseNumberList("100, 1000 3000"), [100, 1000, 3000]);
  assert.deepEqual(parseNumberList(" 200 "), [200]);
  assert.throws(() => parseNumberList(""));
  assert.throws(() => parseNumberList("100, abc"));
});
