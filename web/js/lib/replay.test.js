// 재생 유틸 검증 — stride 산정, 모드 구간 분할, 극값
import { test } from "node:test";
import assert from "node:assert/strict";

import { extent, flaggedNames, landingSummary, modeSpans, strideFor } from "./replay.js";

test("strideFor: 목표 점수 이하로 다운샘플", () => {
  assert.equal(strideFor(18000, 1500), 12);
  assert.equal(strideFor(1000, 1500), 1); // 이미 작으면 원해상도
  assert.equal(strideFor(1501, 1500), 2);
});

test("modeSpans: 연속 구간 분할 (경계 인덱스)", () => {
  const spans = modeSpans(["a", "a", "b", "b", "b", "c"]);
  assert.deepEqual(spans, [
    { mode: "a", i0: 0, i1: 2 },
    { mode: "b", i0: 2, i1: 5 },
    { mode: "c", i0: 5, i1: 6 },
  ]);
  assert.deepEqual(modeSpans([]), []);
});

test("extent: null(NaN 직렬화) 무시 극값", () => {
  assert.deepEqual(extent([3, null, 1, 2]), [1, 3]);
  assert.deepEqual(extent([null, null]), [0, 1]); // 전부 null — 안전 기본
});

test("flaggedNames: 뜬 플래그만 이름으로 — 고도 이탈이 DB 이탈로 오독되지 않게", () => {
  const env = (f) => ({ flags: f });
  assert.equal(flaggedNames(env({ alpha: [false, false], altitude: [false, true] })), "고도");
  assert.equal(flaggedNames(env({ alpha: [true], mach: [true], altitude: [false] })), "α·마하");
  assert.equal(flaggedNames(env({ alpha: [false] })), "—");
  // 엔진이 플래그를 추가해도 이름 그대로 통과 (미정의 라벨에 안전)
  assert.equal(flaggedNames(env({ nz: [true] })), "nz");
  assert.equal(flaggedNames({}), "—"); // 엔벨로프 없음/구버전 결과
});

// ---- 이착륙 요약 (01 §3.3.1) ----

const landingBody = (over = {}) => ({
  t: [0, 0.01, 0.02, 0.03, 0.04, 0.05],
  signals: {
    u: Array(6).fill(79.0), v: Array(6).fill(5.0), w: Array(6).fill(20.4),
    phi: Array(6).fill(0.17), theta: Array(6).fill(0.25),
    V: [90, 88, 86, 81.4, 60, 0.2],
    pn: [0, 100, 200, 300, 700, 900], pe: Array(6).fill(0),
    launch_gx: [33.9, 33.9, 0, 0, 0, 0],
  },
  meta: {
    // 강하율·속도는 **엔진이 전 해상도에서 재서** phases에 실어 보낸 값이다 —
    // 화면은 그것을 표시할 뿐 신호에서 다시 계산하지 않는다(재생 응답은 솎여 있다)
    phases: {
      launch_exit_t: 0.02, touchdown_t: 0.03, stop_t: 0.05,
      td_sink_rate: -0.9833, td_speed: 79.54,
    },
    runway: { elevation: 0, heading: 0, length: 1500 },
  },
  ...over,
});

test("landingSummary: 세 단계가 각각 한 줄 — 사출 하중은 미판정으로 나온다", () => {
  const rows = landingSummary(landingBody());
  assert.deepEqual(rows.map((r) => r.label), ["레일 이탈", "접지", "정지"]);
  assert.match(rows[0].note, /33\.9 g/);
  assert.match(rows[0].note, /판정 불가/);
  assert.equal(rows[0].unjudged, true, "판정 기준이 없으면 통과로 위장하지 않는다");
  assert.match(rows[1].note, /강하율 -0\.98 m\/s/, "엔진이 잰 값을 그대로 표시한다");
  assert.match(rows[1].note, /속도 79\.5 m\/s/);
  assert.match(rows[2].note, /600 m/); // 300 → 900
  assert.match(rows[2].note, /활주로 1500 m/);
  assert.equal(rows[2].over, false);
});

test("landingSummary: 없는 단계는 **행 자체가 없다** (0으로 채우지 않는다)", () => {
  const none = landingSummary(landingBody({
    meta: { phases: {
      launch_exit_t: null, touchdown_t: null, stop_t: null,
      td_sink_rate: null, td_speed: null,
    } },
  }));
  assert.deepEqual(none, []);
  // 접지했지만 아직 안 멈춘 런 — 정지 줄이 없다(미래를 지어내지 않는다)
  const mid = landingSummary(landingBody({
    meta: { phases: {
      launch_exit_t: 0.02, touchdown_t: 0.03, stop_t: null,
      td_sink_rate: -0.9833, td_speed: 79.54,
    } },
  }));
  assert.deepEqual(mid.map((r) => r.label), ["레일 이탈", "접지"]);
  // phases 자체가 없는 구 결과 재생도 조용히 0을 만들지 않는다
  assert.deepEqual(landingSummary({ t: [], signals: {}, meta: {} }), []);
});

test("landingSummary: 활주로를 넘어서면 그 사실을 말한다", () => {
  const rows = landingSummary(landingBody({
    meta: {
      phases: {
        launch_exit_t: null, touchdown_t: 0.03, stop_t: 0.05,
        td_sink_rate: -0.9833, td_speed: 79.54,
      },
      runway: { elevation: 0, heading: 0, length: 400 },
    },
  }));
  const stop = rows.find((r) => r.label === "정지");
  assert.equal(stop.over, true);
  assert.match(stop.note, /넘어섰다/);
});

test("landingSummary: 강하율이 없으면 '미계측' — 0으로 눙치지 않는다", () => {
  const rows = landingSummary(landingBody({
    meta: { phases: {
      launch_exit_t: null, touchdown_t: 0.03, stop_t: null,
      td_sink_rate: null, td_speed: null,
    } },
  }));
  assert.match(rows[0].note, /강하율 미계측/);
});
