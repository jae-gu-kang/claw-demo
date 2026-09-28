/** 시험장 제원이 측정 기록·굽는 명령과 어긋나지 않는지.
 *
 * 이 테스트의 존재 이유는 **중복을 묶는 것**이다. 고흥 좌표는 다섯 곳에 있다:
 *   ① data/geo/goheung-runway.json   측정 기록 (정본)
 *   ② web/js/lib/site.js             화면이 읽는 상수
 *   ③ data/README.md                 지형 팩을 굽는 명령의 --origin-*
 *   ④ render.yaml                    배포 빌드가 같은 팩을 굽는 명령 (배포 팩의 원점은 이것이다)
 *   ⑤ data/geo/*.bin 헤더            구운 팩의 origin (런타임에 originsAgree가 본다)
 * ①~④는 사람이 옮겨 적는 것이라 하나만 고치면 조용히 어긋난다. 여기서 넷을 대조한다 —
 * ④는 축 보정(2026-09-27) 때 실제로 혼자 남아, 배포만 옛 원점 팩을 구워 새 결과에 지형이 안 얹힐 뻔했다.
 * ⑤는 팩이 gitignore라 테스트가 볼 수 없고, 대신 화면이 originsAgree로 막는다.
 * 그 밖의 사본(서버 미션 초안 llm_draft.py — 서버 테스트가 대조, 가상환경 번들)은
 * 기록의 consumers가 목록이다.
 *
 * data/geodesy-fixture.json을 엔진·웹 테스트가 함께 읽는 것과 같은 장치다.
 */

import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { DEG2RAD, geodeticToNed } from "./geo.js";
import { GOHEUNG, touchdownWindowM } from "./site.js";

const root = fileURLToPath(new URL("../../../", import.meta.url));
const record = JSON.parse(readFileSync(`${root}data/geo/goheung-runway.json`, "utf-8"));
const dataReadme = readFileSync(`${root}data/README.md`, "utf-8");
const renderYaml = readFileSync(`${root}render.yaml`, "utf-8");

test("site.js의 원점이 측정 기록의 남단 임계와 같다", () => {
  // 남단인 것 자체가 규약이다 — 중점이나 북단으로 바뀌면 활주로가 통째로 어긋난다
  assert.equal(GOHEUNG.originLatDeg, record.threshold_south.lat_deg);
  assert.equal(GOHEUNG.originLonDeg, record.threshold_south.lon_deg);
});

test("site.js의 활주로 방위·길이가 측정 기록과 같다", () => {
  assert.equal(GOHEUNG.runwayHeadingRad, record.heading_rad);
  assert.equal(GOHEUNG.runwayLengthM, record.length_m);
});

// 임계 하나를 원점으로 다른 점의 NED — 엔진 claw.env.geodesy와 같은 식(geo.js, geodesy-fixture가 묶는다)
const nedFrom = (o, p) => geodeticToNed(p.lat_deg * DEG2RAD, p.lon_deg * DEG2RAD,
  { latRad: o.lat_deg * DEG2RAD, lonRad: o.lon_deg * DEG2RAD });

test("기록의 방위·길이는 두 임계에서 셈한 값이다 — 임계만 옮기고 방위를 두면 빨개진다", () => {
  // 방위·길이는 따로 잰 양이 아니라 두 임계의 함수다. 축을 보정하며 셋이 함께 움직였다
  // (centerline_correction) — 하나만 되돌리면 활주로가 원점에서 엉뚱한 쪽으로 그려진다.
  const { n, e } = nedFrom(record.threshold_south, record.threshold_north);
  // 허용차는 기록의 반올림만큼 — 방위 5자리(5e-6 rad), 길이 0.1 m
  assert.ok(Math.abs(Math.atan2(e, n) - record.heading_rad) <= 5e-6,
    `두 임계의 방위 ${Math.atan2(e, n)} rad ≠ 기록 ${record.heading_rad}`);
  assert.ok(Math.abs(Math.hypot(n, e) - record.length_m) <= 0.05,
    `두 임계 사이 ${Math.hypot(n, e)} m ≠ 기록 ${record.length_m}`);
  assert.ok(Math.abs(record.heading_rad / DEG2RAD - record.heading_deg_true) < 5e-4, "도 표기가 rad와 다르다");
});

test("원점은 도색 중심선 위다 — 보정 전 축에서 영상이 잰 치우침만큼 가로로만 옮겼다", () => {
  // 보정 전 축(포장면 주성분)은 유도로 쪽으로 끌려 남단에서 3.6 m 서쪽이었다. 두 임계가 그 축에서
  // **잰 치우침만큼 오른쪽(동)으로**, 축방향으로는 그대로(피아노 건반으로 잡은 임계) 옮겨졌는지를
  // 좌표 자체에서 셈한다 — 기록의 자기주장이 아니다. 좌표를 옛 값으로 되돌리면 가로 이동이 0이 돼 빨개진다.
  const c = record.centerline_correction;
  assert.ok(c?.before && c?.measured_offset_m, "축 보정 기록(centerline_correction)이 없다");
  const h = c.before.heading_rad;
  for (const [end, key] of [["south", "threshold_south"], ["north", "threshold_north"]]) {
    const { n, e } = nedFrom(c.before[key], record[key]);
    const along = n * Math.cos(h) + e * Math.sin(h);
    const cross = -n * Math.sin(h) + e * Math.cos(h);
    // 허용차 0.15 m = 좌표 6자리 반올림(위도 0.11 m · 경도 0.09 m)
    assert.ok(Math.abs(cross - c.measured_offset_m[end]) <= 0.15,
      `${key}: 보정 전 축에서 가로 ${cross.toFixed(2)} m 옮겼는데 영상이 잰 치우침은 ${c.measured_offset_m[end]} m`);
    assert.ok(Math.abs(along) <= 0.15, `${key}: 축방향으로 ${along.toFixed(2)} m 움직였다 — 임계 위치는 그대로여야 한다`);
    // 보정한 좌표로 단면을 다시 뜬 재측정 — 도색 중심이 새 축 위에 있다(잔차 수 cm)
    assert.ok(Math.abs(c.check_after[`${end}_m`]) < 0.1, `${end}: 보정 뒤에도 도색 중심이 ${c.check_after[`${end}_m`]} m 벗어나 있다`);
  }
  // 원점(남단 임계)이 옛 값이면 옛 팩·옛 결과와 섞인다 — 화면 상수도 보정한 값이어야 한다
  assert.notEqual(GOHEUNG.originLonDeg, c.before.threshold_south.lon_deg);
  assert.notEqual(GOHEUNG.runwayHeadingRad, c.before.heading_rad);
});

test("굽는 명령의 원점이 같은 좌표다 — 팩과 결과가 어긋나면 지형이 안 얹힌다", () => {
  const m = dataReadme.match(/--origin-lat\s+([\d.]+)\s+--origin-lon\s+([\d.]+)/);
  assert.ok(m, "data/README.md에서 --origin-lat/--origin-lon을 찾지 못했다");
  assert.equal(Number(m[1]), GOHEUNG.originLatDeg);
  assert.equal(Number(m[2]), GOHEUNG.originLonDeg);
});

// 굽는 명령의 인자 — `build_terrain.py` 뒤에서 셸 리다이렉트·줄잇기 전까지의 낱말
const bakeArgs = (text) => {
  const m = text.match(/build_terrain\.py((?:\s+(?:\\\n)?\s*--[\w-]+\s+[^\s\\>)]+)+)/);
  return m ? m[1].replace(/\\\n/g, " ").trim().split(/\s+/) : null;
};

test("배포 빌드(render.yaml)가 굽는 팩의 원점도 같은 좌표다", () => {
  const m = renderYaml.match(/--origin-lat\s+([\d.]+)\s+--origin-lon\s+([\d.]+)/);
  assert.ok(m, "render.yaml에서 --origin-lat/--origin-lon을 찾지 못했다");
  assert.equal(Number(m[1]), GOHEUNG.originLatDeg);
  assert.equal(Number(m[2]), GOHEUNG.originLonDeg);
});

test("배포 빌드의 굽는 명령이 data/README.md의 명령과 인자까지 같고, 스크립트가 받는 인자만 쓴다", () => {
  // 원점만 같고 계층·출력 이름이 갈라지면 배포 팩만 다른 격자가 되거나 서버가 못 읽는 이름이 된다
  const deploy = bakeArgs(renderYaml);
  const manual = bakeArgs(dataReadme);
  assert.ok(deploy && manual, "굽는 명령을 찾지 못했다");
  assert.deepEqual(deploy, manual);
  const script = readFileSync(`${root}scripts/terrain/build_terrain.py`, "utf-8");
  for (const flag of deploy.filter((w) => w.startsWith("--"))) {
    assert.ok(script.includes(`add_argument("${flag}"`), `build_terrain.py가 ${flag}를 받지 않는다`);
  }
  // 서버는 *-terrain-*.bin만 인식한다(routes/world.py _terrain_packs) — 배포가 구운 팩이 보여야 한다
  assert.match(deploy[deploy.indexOf("--out") + 1], /^data\/geo\/[A-Za-z0-9._-]*-terrain-[A-Za-z0-9._-]*\.bin$/);
});

test("site.js의 활주로 폭이 기록의 width_m과 같다", () => {
  // 폭이 없던 동안 착륙 요약의 횡편차 행은 어느 런이든 「고흥 시험장 제원에 활주로 폭이 없다, 판정 불가」였다
  assert.equal(GOHEUNG.runwayWidthM, record.width_m);
  assert.equal(typeof record.width_m, "number");
});

test("활주로 폭은 인용된 공표 제원이다 — 인용문마다 그 폭과 **같은 활주로의 길이**를 말한다", () => {
  // 시험장에는 활주로가 둘이다(신 1200 m × 45 m · 구 700 m × 24 m). 인용문에서 폭 숫자만 찾으면
  // 구활주로의 24 m를 그 인용(「700*24m」)과 함께 옮겨 적어도 지나간다 — 인용문이 기록의 공표 길이
  // (verification)와 같은 활주로를 말하는지까지 본다. 확인일은 필수다 — 웹 페이지는 바뀐다.
  const src = record.width_source;
  assert.ok(Array.isArray(src?.published) && src.published.length > 0, "폭의 출처 인용이 없다");
  const w = record.width_m;
  for (const p of src.published) {
    assert.match(p.url, /^https:\/\//);
    assert.match(p.accessed, /^\d{4}-\d{2}-\d{2}$/, `${p.url}: 확인일이 없다`);
    assert.ok(new RegExp(`(폭\\s*|[x×*]\\s*)${w}\\s*m`).test(p.quote), `${p.url}의 인용문이 폭 ${w} m를 말하지 않는다: ${p.quote}`);
    const km = p.quote.match(/(\d+(?:\.\d+)?)\s*km/);
    const m = p.quote.match(/(\d[\d,]*)\s*m/);
    const len = km ? Number(km[1]) * 1000 : Number(m?.[1].replace(/,/g, ""));
    assert.equal(len, record.verification.published_length_m, `${p.url}의 인용문이 다른 활주로를 말한다: ${p.quote}`);
  }
});

test("폭의 항공영상 검산이 공표 제원과 맞는다 — 길이 검산과 같은 1 % 문턱", () => {
  // 공표 폭은 계획서의 수일 수도 있다 — 지어진 활주로의 표지 간격이 그 수와 맞는다는 것이 독립 증거다
  const c = record.width_source.imagery_check;
  const err = Math.abs(c.measured_width_m - record.width_m) / record.width_m;
  assert.ok(err < 0.01, `공표 폭 대비 ${(err * 100).toFixed(2)}% — 1% 넘으면 다시 재야 한다`);
});

test("data/README.md가 말하는 활주로 폭이 기록과 같다 — 사본은 대조한다", () => {
  const m = dataReadme.match(/활주로 \*\*폭\*\*\((\d+(?:\.\d+)?) m\)/);
  assert.ok(m, "data/README.md에서 활주로 폭 문장을 찾지 못했다");
  assert.equal(Number(m[1]), record.width_m);
});

test("측정 기록이 공표 제원과 맞는다 — 검출이 옳았다는 독립 증거", () => {
  // 길이는 검출 절차에 입력되지 않는 량이라, 맞는 것이 우연일 수 없다.
  // 기록의 자기주장(relative_error 문자열)이 아니라 여기서 실제로 셈한다.
  const v = record.verification;
  assert.equal(v.measured_length_m, record.length_m, "기록이 스스로 두 길이를 다르게 말한다");
  const err = Math.abs(v.measured_length_m - v.published_length_m) / v.published_length_m;
  assert.ok(err < 0.01, `공표 대비 ${(err * 100).toFixed(2)}% — 1% 넘으면 다시 재야 한다`);
});

test("접지 창은 활주로 전장이 아니라 전장 − 미끄럼이다", () => {
  // 시단에 닿아도 미끄럼만큼은 굴러간다. 이 구별을 놓치면 산포를 1,205 m와 견주어
  // "겨우 들어간다"는 거짓 통과가 나온다 — 실제로 그렇게 쓴 적이 있다.
  assert.equal(touchdownWindowM(), 1048); // 1,205 − 미끄럼 157 m (200 kg급 예제 실측)
  assert.ok(touchdownWindowM() < GOHEUNG.runwayLengthM);
});

test("화면 문구가 시험장 좌표·방위를 옮겨 적지 않는다 — GOHEUNG에서 셈한다", () => {
  // 축 보정(2026-09-27) 때 시뮬 탭 안내문의 「(3.417°)」「(34.601303 / 127.212067)」가 상수를 따라오지 않고 혼자
  // 남았다 — 문구의 수는 site.js에서 셈해야 한다. 지금 값과 보정 전 값을 둘 다 찾는다(주석은 걷어낸다 — 연혁은 적어도 된다)
  const strip = (src) => src.replace(/\/\*[\s\S]*?\*\//g, " ").replace(/\/\/[^\n]*/g, " ");
  const before = record.centerline_correction.before;
  const literals = [
    String(GOHEUNG.originLatDeg), String(GOHEUNG.originLonDeg), `${(GOHEUNG.runwayHeadingRad / DEG2RAD).toFixed(3)}°`,
    String(before.threshold_south.lat_deg), String(before.threshold_south.lon_deg), `${before.heading_deg_true}°`,
  ];
  for (const f of readdirSync(`${root}web/js/views`).filter((x) => x.endsWith(".js") && !x.endsWith(".test.js"))) {
    const code = strip(readFileSync(`${root}web/js/views/${f}`, "utf-8"));
    for (const lit of literals) assert.ok(!code.includes(lit), `${f}가 시험장 값 ${lit}을 문구에 옮겨 적었다`);
  }
  // 착륙 요약은 접지·정지 지점을 활주로 축 구간과 폭에 견준다(lib/replay.js) — 판정하지 않는다던 옛 안내가 돌아오면 안 된다
  const sim = strip(readFileSync(`${root}web/js/views/sim.js`, "utf-8"));
  assert.ok(!sim.includes("활주로에 내렸는지는 판정하지 않습니다"), "sim.js가 착륙 지점을 판정하지 않는다고 말한다");
});

test("산포 수치는 화면에도 여기에도 없다 — 엔진이 재는 값을 옮겨 적지 않는다", () => {
  // 옮겨 적었다가 병행 작업의 스케줄 변경으로 곧장 틀렸고, 이 테스트가 그 낡은 값을
  // 고정해 정정을 막았다. 다시 들어오면 같은 일이 반복되므로 없다는 것을 못박는다.
  assert.equal(GOHEUNG.touchdownSpreadM, undefined,
    "산포는 시험장 제원이 아니다 — engine/claw/tests/test_landing.py가 정본이다");
  // 이것은 **보증이 아니라 트립와이어**다. 실제 보증은 값의 집이 하나라는 것
  // (engine/claw/tests/test_landing.py)이고, 여기서는 일어났던 회귀만 값싸게 막는다.
  // 식별자만 보므로 `someNumber / touchdownWindowM()` 같은 우회는 잡지 못한다.
  //
  // 주석은 걷어내고 본다 — 이 리포는 주석 밀도가 높아, "산포 배수(spreadRatio)는
  // 여기서 계산하지 않는다"는 설명 한 줄이 거짓 실패를 내는 것이 가정이 아니다.
  const strip = (src) => src.replace(/\/\*[\s\S]*?\*\//g, " ").replace(/\/\/[^\n]*/g, " ");
  const views = readdirSync(`${root}web/js/views`).filter((f) => f.endsWith(".js"));
  for (const f of views) {
    const code = strip(readFileSync(`${root}web/js/views/${f}`, "utf-8"));
    assert.ok(!code.includes("spreadRatio"), `${f}가 산포 배수를 다시 계산하고 있다`);
    assert.ok(!code.includes("touchdownSpread"), `${f}가 산포를 시험장 제원에서 읽는다`);
  }
});
