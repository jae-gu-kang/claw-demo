// 트림 격자 생성 검증 — 부동소수 라운딩, 서펜타인 인접성, 수치 목록 파싱
import { test } from "node:test";
import assert from "node:assert/strict";

import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import {
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


// 탭의 폴백 격자 상수는 폐지했다(05 §11.13 5단계) — 마진 맵·게인 카드·흐름 평가·영향성은 요구영역의 기본 격자
// (서버 /grid/base)에서 점을 받는다. 그 이름이 web/js 어디에도(주석·시험 포함) 다시 나타나면 여기서 죽는다.
// 이름은 조각으로 적는다 — 이 파일 자체가 걸리지 않게
test("폐지한 폴백 격자 상수·헬퍼가 web/js에 되살아나지 않는다", () => {
  const banned = ["DEFAULT_" + "GRID", "defaultGrid" + "Cases", "fillGrid" + "FromProfile", "grid" + "Strings",
    "gridCentre" + "Case"];
  const root = new URL("..", import.meta.url).pathname;
  const hits = [];
  const walk = (dir) => {
    for (const name of readdirSync(dir)) {
      const full = join(dir, name);
      if (statSync(full).isDirectory()) walk(full);
      else if (name.endsWith(".js")) {
        const text = readFileSync(full, "utf8");
        for (const b of banned) if (text.includes(b)) hits.push(`${full.slice(root.length)}: ${b}`);
      }
    }
  };
  walk(root);
  assert.deepEqual(hits, []);
});

// 대표 부분 격자 시험의 격자 — 옛 예제 기체 템플릿 격자 꼴(M0.14~0.22/0.02 × 세 고도 × 연료 하나, 15건)의 사본.
// 기체 값이 아니라 시험 재료다
const G15 = { machFrom: 0.14, machTo: 0.22, machStep: 0.02, alts: [100, 1000, 3000], fuels: [25] };
const casesOf = (g) => nameCases(serpentineCases(machRange(g.machFrom, g.machTo, g.machStep), g.alts, g.fuels));


// ── 대표 부분 격자 (쇼케이스 영향성 2단) ──────────────────────────────────────

test("representativeGrid: n=4는 마하 양끝 × 고도 양끝 — 폼 칸 세 개로 적히는 부분 격자", () => {
  const g = representativeGrid(G15, 4);
  assert.deepEqual(g, { machFrom: 0.14, machTo: 0.22, machStep: 0.08, alts: [100, 3000], fuels: [25] });
  const names = casesOf(g).map((c) => c.name);
  assert.deepEqual(names, ["M0.14_h100_f25", "M0.22_h100_f25", "M0.22_h3000_f25", "M0.14_h3000_f25"]);
  // 이름이 원 격자와 같다 — 평가·처방·감도가 같은 케이스를 같은 이름으로 부른다
  const full = new Set(casesOf(G15).map((c) => c.name));
  assert.ok(names.every((n) => full.has(n)));
});

test("representativeGrid: 건수는 n 이하 — 등간격이 안 되는 마하 점수는 건너뛴다", () => {
  for (let n = 1; n <= 20; n += 1) {
    const g = representativeGrid(G15, n);
    const cases = casesOf(g);
    assert.ok(cases.length <= n, `n=${n} → ${cases.length}건`);
    assert.ok(cases.length >= 1);
  }
  // 마하 5점에서 4점은 등간격으로 못 뽑는다 — 3점(0.14·0.18·0.22)으로 선다
  const g6 = representativeGrid(G15, 6);
  assert.deepEqual(machRange(g6.machFrom, g6.machTo, g6.machStep), [0.14, 0.18, 0.22]);
  assert.deepEqual(g6.alts, [100, 3000]);
});

test("representativeGrid: n=1은 가운데 점, 격자보다 크면 격자 그대로", () => {
  assert.deepEqual(casesOf(representativeGrid(G15, 1)).map((c) => c.name),
    ["M0.18_h1000_f25"]);
  assert.deepEqual(representativeGrid(G15, 15), { ...G15 });
  assert.deepEqual(representativeGrid(G15, 99), { ...G15 });
});

test("representativeGrid: 연료 축도 끝점부터 — 기체 값은 인자 격자에서만 온다", () => {
  const grid = { machFrom: 0.3, machTo: 0.5, machStep: 0.1, alts: [0, 2000], fuels: [10, 50, 90] };
  const g = representativeGrid(grid, 8);
  assert.deepEqual(g, { machFrom: 0.3, machTo: 0.5, machStep: 0.2, alts: [0, 2000], fuels: [10, 90] });
  assert.equal(casesOf(g).length, 8);
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
  assert.throws(() => representativeGrid(G15, 0));
  assert.throws(() => representativeGrid(G15, 2.5));
  assert.throws(() => representativeGrid({ ...G15, alts: [] }, 4));
});
