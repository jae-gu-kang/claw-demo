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

test("landingSummary: 각 단계가 한 줄 — 사출 하중은 미판정으로 나온다", () => {
  const rows = landingSummary(landingBody());
  // "접지 지점"은 접지 **뒤**, 정지 **앞**이다 — 접지 이야기가 붙어 있어야 읽힌다
  assert.deepEqual(rows.map((r) => r.label),
    ["레일 이탈", "접지", "접지 지점", "정지"]);
  const by = (label) => rows.find((r) => r.label === label);
  assert.match(by("레일 이탈").note, /33\.9 g/);
  assert.match(by("레일 이탈").note, /판정 불가/);
  assert.equal(by("레일 이탈").unjudged, true, "판정 기준이 없으면 통과로 위장하지 않는다");
  assert.match(by("접지").note, /강하율 -0\.98 m\/s/, "엔진이 잰 값을 그대로 표시한다");
  assert.match(by("접지").note, /속도 79\.5 m\/s/);
  assert.match(by("정지").note, /600 m/); // 300 → 900
  assert.match(by("정지").note, /활주로 1500 m/);
  assert.equal(by("정지").over, false);
});

test("landingSummary: 접지 지점이 활주로 구간 밖이면 그렇게 말한다", () => {
  // 기본 미션은 발사대에서 떠서 **7 km 북쪽**에 내린다. 접지→정지 거리만 길이와
  // 견주면 "869 m / 활주로 1205 m"가 되어 활주로에 선 것처럼 읽힌다 — 실제로
  // 그렇게 읽혔다. 축방향 위치를 함께 내야 그 착시가 없어진다.
  const far = landingSummary(landingBody({
    signals: { ...landingBody().signals, pn: [0, 100, 200, 7000, 7400, 7870] },
  }));
  const spot = far.find((r) => r.label === "접지 지점");
  assert.ok(spot, "접지 지점 행이 없다");
  assert.equal(spot.value, "활주로 축 +7,000 m"); // 구분자 포함 — ko-KR 고정
  assert.equal(spot.over, true, "활주로 구간 밖인데 밖이라고 하지 않는다");
  assert.match(spot.note, /구간\(0~1,500 m\) 밖이다/);
  assert.equal(spot.overLabel, "활주로 밖");
});

test("landingSummary: 방위를 모르면 접지 지점 행이 없다 — 축을 지어내지 않는다", () => {
  // 방위가 없으면 "활주로 축"이라는 축 자체가 없다. 0으로 메우면 방위를 알 때와
  // 똑같은 확신으로 축방향 거리를 찍게 된다 — 이 파일의 "0으로 채우지 않는다" 규약 위반.
  const rows = landingSummary(landingBody({
    meta: { ...landingBody().meta, runway: { elevation: 0, length: 1500 } },
  }));
  assert.equal(rows.find((r) => r.label === "접지 지점"), undefined);
  // 활주로 자체는 있으므로 "정지" 행의 길이 비교는 그대로 산다
  assert.match(rows.find((r) => r.label === "정지").note, /활주로 1500 m/);
});

test("landingSummary: 길이가 0 이하면 접지 지점 행이 없다 — 항상 '밖'이 되지 않게", () => {
  for (const length of [0, -100]) {
    const rows = landingSummary(landingBody({
      meta: { ...landingBody().meta, runway: { elevation: 0, heading: 0, length } },
    }));
    assert.equal(rows.find((r) => r.label === "접지 지점"), undefined, `length=${length}`);
  }
});

test("landingSummary: 접지 위치가 결측이면 행이 없다", () => {
  const rows = landingSummary(landingBody({
    signals: { ...landingBody().signals, pn: [0, 100, 200, null, 700, 900] },
  }));
  assert.equal(rows.find((r) => r.label === "접지 지점"), undefined);
});

test("landingSummary: 횡편차가 길이를 넘으면 폭을 몰라도 밖이라고 단정한다", () => {
  // 활주로가 자기 길이보다 넓을 수는 없다 — 축방향 하한과 같은 논법이다.
  const wide = landingSummary(landingBody({
    signals: {
      ...landingBody().signals,
      pn: [0, 100, 200, 300, 700, 900], pe: [0, 0, 0, 3000, 3000, 3000],
    },
  }));
  const spot = wide.find((r) => r.label === "접지 지점");
  assert.equal(spot.over, true, "횡편차 3000 m인데 판정 불가로 나온다");
  assert.equal(spot.unjudged, undefined);
  assert.equal(spot.overLabel, "활주로 밖");
});

test("landingSummary: 접지 지점은 10 m 단위 — 재생 표본이 그보다 성글다", () => {
  // 재생 응답은 stride로 솎여 있어 표본 간격이 88 m/s × 0.14 s ≈ 12 m다.
  // 1 m 단위로 찍으면 갖지 않은 분해능을 주장한다.
  const rows = landingSummary(landingBody({
    signals: { ...landingBody().signals, pn: [0, 100, 200, 7073, 7400, 7870] },
  }));
  const spot = rows.find((r) => r.label === "접지 지점");
  assert.match(spot.value, /7,070 m/, "1 m 단위로 찍고 있다");
});

test("landingSummary: 시단 앞에 내린 것을 '활주로 초과'라 하지 않는다", () => {
  const short = landingSummary(landingBody({
    signals: { ...landingBody().signals, pn: [0, -100, -200, -300, -100, 100] },
  }));
  const spot = short.find((r) => r.label === "접지 지점");
  assert.equal(spot.over, true);
  assert.equal(spot.overLabel, "시단 못 미침");
  const far = landingSummary(landingBody({
    signals: { ...landingBody().signals, pn: [0, 100, 200, 7000, 7400, 7870] },
  }));
  assert.equal(far.find((r) => r.label === "접지 지점").overLabel, "활주로 밖");
});

test("landingSummary: 구간 안이어도 **통과로 말하지 않는다** — 폭을 모른다", () => {
  // 축방향이 0~length 안이라는 것은 활주로에 내렸다는 뜻이 아니다. 활주로 폭이
  // 결과 meta에 없으므로 횡편차를 판정할 수 없다 — 미판정이지 통과가 아니다.
  const near = landingSummary(landingBody({
    signals: { ...landingBody().signals, pn: [0, 100, 200, 300, 700, 900] },
  }));
  const spot = near.find((r) => r.label === "접지 지점");
  assert.equal(spot.over, false);
  assert.equal(spot.unjudged, true, "폭을 모르는데 통과로 말한다");
  assert.match(spot.note, /폭/);
});

test("landingSummary: 활주로가 없으면 접지 지점 행도 없다", () => {
  const rows = landingSummary(landingBody({
    meta: { ...landingBody().meta, runway: undefined },
  }));
  assert.equal(rows.find((r) => r.label === "접지 지점"), undefined);
});

test("landingSummary: 축방향은 활주로 방위 기준이다 (정북이 아니라)", () => {
  // 방위가 90°면 북쪽으로 간 거리는 축방향이 아니라 횡편차다
  const east = landingSummary(landingBody({
    signals: { ...landingBody().signals, pn: [0, 100, 200, 300, 700, 900] },
    meta: {
      ...landingBody().meta,
      runway: { elevation: 0, heading: Math.PI / 2, length: 1500 },
    },
  }));
  const spot = east.find((r) => r.label === "접지 지점");
  assert.match(spot.value, /축 \+?0 m/);
  assert.match(spot.note, /300 m/); // 횡편차로 나온다
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

test("landingSummary: 어느 행에도 마크다운이 없다 — 문자열이 그대로 화면에 나간다", () => {
  // label·value·note·overLabel은 전부 **텍스트 노드**로 들어간다(views/sim.js —
  // label은 el("b"), overLabel은 flagBadge → el("span")). 그래서 `**강조**`를 적으면
  // 별표째 찍힌다. 실제로 정지 행의 `**넘어섰다**`가 그렇게 나가고 있었는데,
  // 위 시나리오 테스트의 `/넘어섰다/`가 **부분 일치**라 별표 안쪽을 그냥 통과시켰다.
  //
  // 이 단정을 그 시나리오 테스트 안에 두면 안 된다 — 거기는 launch_exit_t가 null이라
  // **레일 이탈 행이 아예 안 생기고**, 접지·접지 지점 행도 분기 하나씩만 탄다.
  // 네 행이 다 나오는 기본 본문으로 따로 세워야 전 문구를 덮는다 (리뷰 지적).
  const rows = landingSummary(landingBody());
  assert.ok(rows.length >= 3, "행이 안 생기면 아무것도 검사하지 못한다");
  for (const r of rows) {
    const text = [r.label, r.value, r.note, r.overLabel].filter(Boolean).join(" ");
    assert.doesNotMatch(text, /\*\*|`|<[a-z]/i, `${r.label}: 마크다운·마크업 잔재`);
  }
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
