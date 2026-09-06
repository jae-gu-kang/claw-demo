// 트림 격자 생성 검증 — 부동소수 라운딩, 서펜타인 인접성, 수치 목록 파싱
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  DEFAULT_GRID, defaultGridCases,
  machRange, nameCases, orderCaseNames, parseCaseName, parseNumberList, serpentineCases,
} from "./grid.js";

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

test("parseCaseName: nameCases의 역함수 — 형식이 아니면 null", () => {
  assert.deepEqual(parseCaseName("M0.5_h1000_f200"), { mach: 0.5, alt: 1000, fuel: 200 });
  assert.deepEqual(parseCaseName("M0.005_h-50_f200"), { mach: 0.005, alt: -50, fuel: 200 });
  // 왕복 — 이름이 값 그대로라는 nameCases의 계약이 되읽기에서도 성립해야 한다
  for (const c of nameCases(serpentineCases(machRange(0.4, 0.8, 0.005), [100, 3000], [200]))) {
    assert.deepEqual(parseCaseName(c.name), { mach: c.mach, alt: c.alt, fuel: c.fuel });
  }
  for (const bad of ["", "base", "M0.5_h1000", "손으로_지은_이름", null]) {
    assert.equal(parseCaseName(bad), null);
  }
});

test("orderCaseNames: 표는 (fuel, alt, mach) 순 — 서펜타인은 실행 순서지 읽는 순서가 아니다", () => {
  const names = nameCases(serpentineCases([0.4, 0.5, 0.6], [100, 1000], [200])).map((c) => c.name);
  // 실행 순서는 둘째 줄이 뒤집혀 있다 (인접 트림 시드)
  assert.equal(names[3], "M0.6_h1000_f200");
  assert.deepEqual(orderCaseNames(names), [
    "M0.4_h100_f200", "M0.5_h100_f200", "M0.6_h100_f200",
    "M0.4_h1000_f200", "M0.5_h1000_f200", "M0.6_h1000_f200",
  ]);
  // 원본은 건드리지 않는다 — 부른 쪽의 실행 순서가 정렬로 사라지면 안 된다
  assert.equal(names[3], "M0.6_h1000_f200");
});

test("orderCaseNames: 하나라도 못 읽으면 **전부** 원래 순서 — 절반 정렬은 비일관 비교자다", () => {
  const mixed = ["M0.6_h100_f200", "손으로_지은_이름", "M0.4_h100_f200"];
  assert.deepEqual(orderCaseNames(mixed), mixed);
  assert.deepEqual(orderCaseNames([]), []);
  assert.deepEqual(orderCaseNames(undefined), []);
});

test("parseNumberList: 콤마·공백 구분, 비수치 거부", () => {
  assert.deepEqual(parseNumberList("100, 1000 3000"), [100, 1000, 3000]);
  assert.deepEqual(parseNumberList(" 200 "), [200]);
  assert.throws(() => parseNumberList(""));
  assert.throws(() => parseNumberList("100, abc"));
});


test("기본 격자는 한 곳 정의 — 18케이스·이름 유일", () => {
  const cases = defaultGridCases();
  assert.equal(cases.length, 18);
  assert.equal(new Set(cases.map((c) => c.name)).size, 18);
  // 영향성 폼 기본값과 게인 카드가 같은 격자를 쓴다는 계약의 최소 핀
  assert.equal(DEFAULT_GRID.machFrom, 0.3);
});

// 격자가 **비행 가능 범위 안**에 있다는 계약 — 값이 아니라 성질을 못박는다.
// 엔벨로프(engine trim_level 실측, 연료 200 kg): h100 M0.21~0.60 · h1000
// M0.22~0.59 · h3000 M0.25~0.58 → 세 고도 공통 M0.25~0.58. 이 밖으로 나가면
// 트림이 안 풀려 평가가 「판정 불가」로 빠지는데, 화면은 그 원인을 게인처럼
// 보여 준다(v0.72 이전 15칸 중 7칸이 그랬다). 엔진 엔벨로프가 바뀌면 이 상수도
// 같이 고치라고 여기서 죽는다.
test("기본 격자는 세 고도 공통 엔벨로프 안이다 — 트림 실패 케이스를 기본값으로 주지 않는다", () => {
  const ENVELOPE = { lo: 0.25, hi: 0.58 };   // engine/claw/trim/trim.py 실측
  // **위 숫자의 전제부터 못박는다** — 엔벨로프는 이 고도·연료에서 잰 값이다.
  // 무게가 α 여유(아래 끝)를, 고도가 양 끝을 정하므로 둘 중 하나만 바뀌어도
  // ENVELOPE는 무효인데, 케이스 수 대조는 고도를 **바꾸는** 변이를 못 잡는다
  // (h3000 → h6000은 18케이스 그대로다).
  assert.deepEqual(DEFAULT_GRID.alts, [100, 1000, 3000], "엔벨로프를 잰 고도가 아니다");
  assert.deepEqual(DEFAULT_GRID.fuels, [200], "엔벨로프를 잰 연료가 아니다");

  const machs = machRange(DEFAULT_GRID.machFrom, DEFAULT_GRID.machTo, DEFAULT_GRID.machStep);
  for (const m of machs) {
    assert.ok(m >= ENVELOPE.lo && m <= ENVELOPE.hi,
      `M${m}이 공통 엔벨로프 M${ENVELOPE.lo}~${ENVELOPE.hi} 밖 — 트림이 안 풀린다`);
  }
  // 경계에 붙이지도 않는다: 양 끝 칸이 여유 +0.5°/+0.006로 사실상 경계였다
  assert.ok(machs[0] > ENVELOPE.lo, "아래 끝이 경계에 붙었다 — α 여유가 없다");
  assert.ok(machs[machs.length - 1] < ENVELOPE.hi, "위 끝이 경계에 붙었다 — 스로틀 여유가 없다");

  // **두 물리 코너를 실제로 잡는지**를 본다 — 개수만 세면 안쪽으로 뭉친 격자가
  // 통과한다(0.30~0.45/0.03도 6칸·18케이스·전부 엔벨로프 안이면서 위 코너가
  // 통째로 없다). 아래 끝은 실속 여유, 위 끝은 추력 여유(v0.72 판정)가 걸리는
  // 자리라 하나를 버리면 그 판정이 기본 격자에서 영영 안 걸린다.
  assert.ok(machs[0] <= 0.30, "아래 코너를 안 잡는다 — 실속 여유가 걸리는 자리가 격자에 없다");
  assert.ok(machs[machs.length - 1] >= 0.55, "위 코너를 안 잡는다 — 추력 여유가 걸리는 자리가 격자에 없다");
});
