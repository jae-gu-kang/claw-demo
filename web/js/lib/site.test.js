/** 시험장 제원이 측정 기록·굽는 명령과 어긋나지 않는지.
 *
 * 이 테스트의 존재 이유는 **중복을 묶는 것**이다. 고흥 좌표는 네 곳에 있다:
 *   ① data/geo/goheung-runway.json   측정 기록 (정본)
 *   ② web/js/lib/site.js             화면이 읽는 상수
 *   ③ data/README.md                 지형 팩을 굽는 명령의 --origin-*
 *   ④ data/geo/*.bin 헤더            구운 팩의 origin (런타임에 originsAgree가 본다)
 * ①~③은 사람이 옮겨 적는 것이라 하나만 고치면 조용히 어긋난다. 여기서 셋을 대조한다.
 * ④는 팩이 gitignore라 테스트가 볼 수 없고, 대신 화면이 originsAgree로 막는다.
 *
 * data/geodesy-fixture.json을 엔진·웹 테스트가 함께 읽는 것과 같은 장치다.
 */

import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { GOHEUNG, touchdownWindowM } from "./site.js";

const root = fileURLToPath(new URL("../../../", import.meta.url));
const record = JSON.parse(readFileSync(`${root}data/geo/goheung-runway.json`, "utf-8"));
const dataReadme = readFileSync(`${root}data/README.md`, "utf-8");

test("site.js의 원점이 측정 기록의 남단 임계와 같다", () => {
  // 남단인 것 자체가 규약이다 — 중점이나 북단으로 바뀌면 활주로가 통째로 어긋난다
  assert.equal(GOHEUNG.originLatDeg, record.threshold_south.lat_deg);
  assert.equal(GOHEUNG.originLonDeg, record.threshold_south.lon_deg);
});

test("site.js의 활주로 방위·길이가 측정 기록과 같다", () => {
  assert.equal(GOHEUNG.runwayHeadingRad, record.heading_rad);
  assert.equal(GOHEUNG.runwayLengthM, record.length_m);
});

test("굽는 명령의 원점이 같은 좌표다 — 팩과 결과가 어긋나면 지형이 안 얹힌다", () => {
  const m = dataReadme.match(/--origin-lat\s+([\d.]+)\s+--origin-lon\s+([\d.]+)/);
  assert.ok(m, "data/README.md에서 --origin-lat/--origin-lon을 찾지 못했다");
  assert.equal(Number(m[1]), GOHEUNG.originLatDeg);
  assert.equal(Number(m[2]), GOHEUNG.originLonDeg);
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
  assert.equal(touchdownWindowM(), 335);
  assert.ok(touchdownWindowM() < GOHEUNG.runwayLengthM);
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
