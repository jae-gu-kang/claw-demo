// 트림 격자 생성 검증 — 부동소수 라운딩, 서펜타인 인접성, 수치 목록 파싱
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  DEFAULT_GRID, defaultGridCases,
  machRange, nameCases, representativeGrid, orderCaseNames, parseCaseName, parseNumberList, serpentineCases,
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


test("기본 격자는 한 곳 정의 — 15케이스·이름 유일", () => {
  const cases = defaultGridCases();
  assert.equal(cases.length, 15);
  assert.equal(new Set(cases.map((c) => c.name)).size, 15);
  // 마진 맵 폼 기본값과 게인 카드가 같은 격자를 쓴다는 계약의 최소 핀 (영향성 탭은 요구영역 기본 격자에서 고른다)
  assert.equal(DEFAULT_GRID.machFrom, 0.14);
});

// 격자가 **비행 가능 범위 안**에 있다는 계약 — 값이 아니라 성질을 못박는다.
// 엔벨로프(engine trim_level 0.001 격자 실측, 200 kg급 예제·연료 25 kg): h100 M0.082~0.284 · h1000
// M0.086~0.285 · h3000 M0.097~0.283 → 세 고도 공통을 안쪽으로 반올림해 M0.10~0.28(추진 1.45배). 이 밖으로 나가면
// 트림이 안 풀려 평가가 「판정 불가」로 빠지는데, 화면은 그 원인을 게인처럼
// 보여 준다(v0.72 이전 15칸 중 7칸이 그랬다). 엔진 엔벨로프가 바뀌면 이 상수도
// 같이 고치라고 여기서 죽는다.
test("기본 격자는 세 고도 공통 엔벨로프 안이다 — 트림 실패 케이스를 기본값으로 주지 않는다", () => {
  const ENVELOPE = { lo: 0.10, hi: 0.28 };   // engine trim_level 실측 (위 주석)
  // **위 숫자의 전제부터 못박는다** — 엔벨로프는 이 고도·연료에서 잰 값이다.
  // 무게가 α 여유(아래 끝)를, 고도가 양 끝을 정하므로 둘 중 하나만 바뀌어도
  // ENVELOPE는 무효인데, 케이스 수 대조는 고도를 **바꾸는** 변이를 못 잡는다
  // (h3000 → h6000은 18케이스 그대로다).
  assert.deepEqual(DEFAULT_GRID.alts, [100, 1000, 3000], "엔벨로프를 잰 고도가 아니다");
  assert.deepEqual(DEFAULT_GRID.fuels, [25], "엔벨로프를 잰 연료가 아니다");

  const machs = machRange(DEFAULT_GRID.machFrom, DEFAULT_GRID.machTo, DEFAULT_GRID.machStep);
  for (const m of machs) {
    assert.ok(m >= ENVELOPE.lo && m <= ENVELOPE.hi,
      `M${m}이 공통 엔벨로프 M${ENVELOPE.lo}~${ENVELOPE.hi} 밖 — 트림이 안 풀린다`);
  }
  // 경계에 붙이지도 않는다(구 기체에서 양 끝 칸이 여유 +0.5°/+0.006로 사실상 경계였다)
  assert.ok(machs[0] > ENVELOPE.lo, "아래 끝이 경계에 붙었다 — α 여유가 없다");
  assert.ok(machs[machs.length - 1] < ENVELOPE.hi, "위 끝이 경계에 붙었다 — 스로틀 여유가 없다");

  // **두 물리 코너를 실제로 잡는지**를 본다 — 개수만 세면 안쪽으로 뭉친 격자가
  // 통과한다. 아래 끝은 나선 배가 시간(20 s 판정선 바로 위 — 느린 기체에서는 α보다 먼저 걸린다,
  // engine test_profile_shipped_example.py), 위 끝은 추력 여유(v0.72 판정)가 걸리는 자리라 하나를 버리면
  // 그 판정이 기본 격자에서 영영 안 걸린다.
  assert.ok(machs[0] <= 0.14, "아래 코너를 안 잡는다 — 나선·실속 여유가 걸리는 자리가 격자에 없다");
  assert.ok(machs[machs.length - 1] >= 0.22, "위 코너를 안 잡는다 — 추력 여유가 걸리는 자리가 격자에 없다");
});


// ── 대표 부분 격자 (쇼케이스 영향성 2단) ──────────────────────────────────────

test("representativeGrid: n=4는 마하 양끝 × 고도 양끝 — 폼 칸 세 개로 적히는 부분 격자", () => {
  const g = representativeGrid(DEFAULT_GRID, 4);
  assert.deepEqual(g, { machFrom: 0.14, machTo: 0.22, machStep: 0.08, alts: [100, 3000], fuels: [25] });
  const names = defaultGridCases(g).map((c) => c.name);
  assert.deepEqual(names, ["M0.14_h100_f25", "M0.22_h100_f25", "M0.22_h3000_f25", "M0.14_h3000_f25"]);
  // 이름이 원 격자와 같다 — 평가·처방·감도가 같은 케이스를 같은 이름으로 부른다
  const full = new Set(defaultGridCases().map((c) => c.name));
  assert.ok(names.every((n) => full.has(n)));
});

test("representativeGrid: 건수는 n 이하 — 등간격이 안 되는 마하 점수는 건너뛴다", () => {
  for (let n = 1; n <= 20; n += 1) {
    const g = representativeGrid(DEFAULT_GRID, n);
    const cases = defaultGridCases(g);
    assert.ok(cases.length <= n, `n=${n} → ${cases.length}건`);
    assert.ok(cases.length >= 1);
  }
  // 마하 5점에서 4점은 등간격으로 못 뽑는다 — 3점(0.14·0.18·0.22)으로 선다
  const g6 = representativeGrid(DEFAULT_GRID, 6);
  assert.deepEqual(machRange(g6.machFrom, g6.machTo, g6.machStep), [0.14, 0.18, 0.22]);
  assert.deepEqual(g6.alts, [100, 3000]);
});

test("representativeGrid: n=1은 가운데 점, 격자보다 크면 격자 그대로", () => {
  assert.deepEqual(defaultGridCases(representativeGrid(DEFAULT_GRID, 1)).map((c) => c.name),
    ["M0.18_h1000_f25"]);
  assert.deepEqual(representativeGrid(DEFAULT_GRID, 15), { ...DEFAULT_GRID });
  assert.deepEqual(representativeGrid(DEFAULT_GRID, 99), { ...DEFAULT_GRID });
});

test("representativeGrid: 연료 축도 끝점부터 — 기체 값은 인자 격자에서만 온다", () => {
  const grid = { machFrom: 0.3, machTo: 0.5, machStep: 0.1, alts: [0, 2000], fuels: [10, 50, 90] };
  const g = representativeGrid(grid, 8);
  assert.deepEqual(g, { machFrom: 0.3, machTo: 0.5, machStep: 0.2, alts: [0, 2000], fuels: [10, 90] });
  assert.equal(defaultGridCases(g).length, 8);
});

test("representativeGrid: 양끝은 값의 양끝 — 순서 없이 적힌 템플릿 목록에서도 최저·최고 고도를 잡는다", () => {
  const grid = { machFrom: 0.14, machTo: 0.22, machStep: 0.02, alts: [1000, 100, 3000], fuels: [50, 10] };
  const g = representativeGrid(grid, 4);
  assert.deepEqual(g.alts, [100, 3000]);   // 목록 첫·끝(1000·3000)이면 저고도 최대 동압 구석이 빠진다
  assert.deepEqual(g.fuels, [10]);         // 둘 중 가운데는 작은 쪽 — 적힌 순서와 무관
  // 격자 전체를 돌려줄 때는 적힌 목록 그대로다
  assert.deepEqual(representativeGrid(grid, 99).alts, [1000, 100, 3000]);
});

test("representativeGrid: 잘못된 n·빈 목록은 던진다", () => {
  assert.throws(() => representativeGrid(DEFAULT_GRID, 0));
  assert.throws(() => representativeGrid(DEFAULT_GRID, 2.5));
  assert.throws(() => representativeGrid({ ...DEFAULT_GRID, alts: [] }, 4));
});
