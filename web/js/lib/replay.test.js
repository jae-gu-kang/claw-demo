// 재생 유틸 검증 — stride 산정, 모드 구간 분할, 극값
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  extent, flaggedNames, idleTail, idleTailNote, landingLine, landingSummary, launchGx, launchLimitFrom, launchLoad,
  modeSpans,
  pathEscapeNote, profileDocPath, refLabel, runProfileRef, runwayWidthFor, RUNWAY_EDGE_MARGIN_M, siteRunwayWidth,
  strideFor,
} from "./replay.js";
import { DEFAULT_FORM, appliedFrom, buildSimRequest, defaultModeRows, defaultWpRows } from "./simrequest.js";

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
    // 그 런이 실제로 쓴 레일(서버 routes/sim.py가 요청의 레일을 동봉) — 앙각 15°라 중력 성분 sin 15° = 0.2588 g
    launch: { length: 10, elev_angle: Math.PI / 12, azimuth: 0, exit_speed: 33.3, accel: null, origin_height: 2.9 },
  },
  ...over,
});

test("landingSummary: 각 단계가 한 줄 — 사출 하중은 미판정으로 나온다", () => {
  const rows = landingSummary(landingBody());
  // "접지 지점"·"접지 횡편차"는 접지 **뒤**, 정지 **앞**이다 — 접지 이야기가 붙어 있어야 읽힌다
  assert.deepEqual(rows.map((r) => r.label),
    ["레일 이탈", "접지", "접지 지점", "접지 횡편차", "정지"]);
  const by = (label) => rows.find((r) => r.label === label);
  assert.match(by("레일 이탈").note, /^축방향 하중배수 34\.16 g \(레일 가속 33\.90 g \+ 중력 성분 0\.26 g\)/);
  assert.match(by("레일 이탈").note, /대조하지 않았다, 판정 불가/, "한계를 안 넘겼으면 대조 안 함이 사유다");
  assert.equal(by("레일 이탈").unjudged, true, "판정 기준이 없으면 통과로 위장하지 않는다");
  assert.match(by("접지").note, /강하율 -0\.98 m\/s/, "엔진이 잰 값을 그대로 표시한다");
  assert.match(by("접지").note, /속도 79\.5 m\/s/);
  assert.match(by("정지").note, /600 m/); // 300 → 900
  assert.match(by("정지").note, /활주로 1500 m/);
  assert.equal(by("정지").over, false);
});

// ---- 발사하중 판정 — 그 런의 기체 문서 structural.n_x_launch (lib/replay.js launchVerdict) ----

const rail = (limit) => landingSummary(landingBody(), { launchLimit: limit })
  .find((r) => r.label === "레일 이탈");

test("landingSummary: 한계 안이면 통과 표지 — 값·한계·출처를 함께 적는다", () => {
  const r = rail({ nx: 40, source: "S1 · r3" });
  assert.match(r.note, /하중배수 34\.16 g \(.*\) ≤ 한계 40 g \(S1 · r3 structural\.n_x_launch\)$/);
  assert.equal(r.pass, true);
  assert.equal(r.passLabel, "한계 안");
  assert.equal(r.unjudged, undefined, "판정했으면 미판정 표지를 달지 않는다");
  assert.equal(r.over, undefined);
});

test("landingSummary: 한계를 넘으면 초과 표지", () => {
  const r = rail({ nx: 8, source: "S1 · r3" });
  assert.match(r.note, /34\.16 g \(.*\) > 한계 8 g \(S1 · r3 structural\.n_x_launch\) — 한계를 넘었다$/);
  assert.equal(r.over, true);
  assert.equal(r.overLabel, "발사하중 초과");
  assert.equal(r.pass, undefined);
});

test("landingSummary: 문서에 한계가 없으면 판정 불가 — 문서 이름과 칸을 사유로", () => {
  const r = rail({ nx: null, source: "예제 델타 · r0" });
  assert.match(r.note, /기체 문서\(예제 델타 · r0\)에 .*structural\.n_x_launch\)가 없어 판정 불가/);
  assert.equal(r.unjudged, true);
});

test("landingSummary: 문서를 못 받았으면 그 사유로 판정 불가", () => {
  const r = rail({ error: "이 런의 기체 문서를 받지 못했다 — 404" });
  assert.match(r.note, /받지 못했다 — 404, 판정 불가/);
  assert.equal(r.unjudged, true);
  assert.equal(rail(null).unjudged, true, "null도 통과가 아니다");
});

test("landingSummary: 레일 위 표본이 없으면(gx 0) 판정하지 않는다 — 미계측", () => {
  const body = landingBody();
  body.signals.launch_gx = Array(6).fill(0);
  const r = landingSummary(body, { launchLimit: { nx: 8, source: "x" } }).find((x) => x.label === "레일 이탈");
  assert.equal(r.note, "사출 하중 미계측");
  assert.equal(r.pass, undefined);
  assert.equal(r.over, undefined);
});

test("launchGx: 레일 축 가속도 최대 — 신호가 없으면 null, 레일 표본이 없으면 0", () => {
  assert.equal(launchGx(landingBody()), 33.9);
  assert.equal(launchGx({ signals: { launch_gx: [0, null, 0] } }), 0);
  assert.equal(launchGx({ signals: {} }), null);
  assert.equal(launchGx(null), null);
});

// ---- 축방향 하중배수 n_x = gx + sin γ (lib/replay.js launchLoad) ----
// 예제 레일(길이 10 m·앙각 15°·이탈 33.3 m/s): 순가속 33.3²/(2·10)/g0 = 5.654 g — 엔진 LaunchRail.launch_gx와 같은 식
const G0 = 9.80665;
const exampleGx = 33.3 ** 2 / (2 * 10) / G0;
const exampleBody = (launch = { length: 10, elev_angle: Math.PI / 12, exit_speed: 33.3 }) => landingBody({
  signals: { ...landingBody().signals, launch_gx: [exampleGx, exampleGx, 0, 0, 0, 0] },
  meta: { ...landingBody().meta, launch },
});
const exampleRail = (limit, launch) => landingSummary(exampleBody(launch), { launchLimit: limit })
  .find((r) => r.label === "레일 이탈");

test("launchLoad: 레일 가속에 중력 성분(sin γ)을 더한다 — 앙각은 그 런의 meta.launch에서", () => {
  const load = launchLoad(exampleBody());
  assert.ok(Math.abs(load.gx - 5.6538) < 1e-4, String(load.gx));
  assert.ok(Math.abs(load.grav - Math.sin(Math.PI / 12)) < 1e-12);
  assert.ok(Math.abs(load.nx - 5.9126) < 1e-4, "5.65 g + 0.26 g — 순가속만 보면 0.26 g 과소");
  // 앙각이 음수(내리막 레일)면 중력 성분이 하중을 던다
  const down = launchLoad(exampleBody({ elev_angle: -0.1 }));
  assert.ok(Math.abs(down.nx - (exampleGx + Math.sin(-0.1))) < 1e-12);
  // 앙각이 없으면 합을 짓지 않는다(0으로 메우면 순가속을 하중배수라 부른다)
  for (const launch of [null, {}, { elev_angle: null }, { elev_angle: NaN }, { elev_angle: "0.26" }]) {
    const l = launchLoad(exampleBody(launch));
    assert.equal(l.nx, null, JSON.stringify(launch));
    assert.equal(l.grav, null);
    assert.equal(l.gx, exampleGx);
  }
  // 레일 위 표본이 없으면(미계측) null
  assert.equal(launchLoad({ signals: { launch_gx: [0, 0] }, meta: { launch: { elev_angle: 0.26 } } }), null);
  assert.equal(launchLoad({ signals: {} }), null);
});

test("landingSummary: 판정 문장은 합과 두 항을 함께 — 「축방향 하중배수 5.91 g (레일 가속 5.65 g + 중력 성분 0.26 g) ≤ 한계」", () => {
  const r = exampleRail({ nx: 8, source: "S1 · r2" });
  assert.equal(r.note,
    "축방향 하중배수 5.91 g (레일 가속 5.65 g + 중력 성분 0.26 g) ≤ 한계 8 g (S1 · r2 structural.n_x_launch)");
  assert.equal(r.pass, true);
  // 내리막 레일은 부호를 뺄셈으로 적는다("+ 중력 성분 -0.10 g"로 쓰지 않는다)
  assert.match(exampleRail({ nx: 8, source: "S1" }, { elev_angle: -0.1 }).note,
    /^축방향 하중배수 5\.55 g \(레일 가속 5\.65 g − 중력 성분 0\.10 g\) ≤ 한계 8 g/);
});

test("landingSummary: 순가속은 한계 안이지만 중력 성분을 더하면 넘는 런 — 초과로 판정한다", () => {
  // 한계 5.8 g: 순가속 5.65 g만 견주면 「한계 안」이었다(판정 지표가 앙각만큼 낙관이던 자리)
  const r = exampleRail({ nx: 5.8, source: "S1 · r2" });
  assert.equal(r.over, true);
  assert.equal(r.overLabel, "발사하중 초과");
  assert.equal(r.pass, undefined);
  assert.match(r.note, /5\.91 g .* > 한계 5\.8 g .* — 한계를 넘었다$/);
  assert.match(landingLine(landingSummary(exampleBody(), { launchLimit: { nx: 5.8, source: "S1" } })), /발사하중 초과$/);
  // 합이 한계와 같으면 안이다(≤)
  const edge = exampleRail({ nx: exampleGx + Math.sin(Math.PI / 12), source: "S1" });
  assert.equal(edge.pass, true);
});

test("landingSummary: 결과에 레일 앙각이 없으면 가속만 적고 판정 불가 — 사유는 빠진 칸", () => {
  const r = exampleRail({ nx: 8, source: "S1 · r2" }, null);
  assert.match(r.note, /^레일 가속 5\.65 g — 결과에 레일 앙각\(meta\.launch\.elev_angle\)이 없어 .*판정 불가$/);
  assert.equal(r.unjudged, true);
  assert.equal(r.pass, undefined, "앙각 없이 순가속으로 통과를 말하지 않는다");
  assert.equal(r.over, undefined);
  // 한계 쪽 사유가 먼저다 — 한계가 없으면 앙각이 있어도 판정할 수 없다
  assert.match(exampleRail({ nx: null, source: "S1" }, null).note, /structural\.n_x_launch\)가 없어 판정 불가$/);
});

test("runProfileRef: 결과 meta.profile → 문서 좌표, 기록이 없거나 깨졌으면 null", () => {
  assert.deepEqual(
    runProfileRef({ profile: { id: "showcase-delta", name: "S1", variant: "eoir", revision: 3 } }),
    { id: "showcase-delta", variant: "eoir", revision: 3, name: "S1" });
  // 기본 형상·예제 리비전 0 — 0을 "없음"으로 버리지 않는다
  assert.deepEqual(runProfileRef({ profile: { id: "example-delta", variant: null, revision: 0 } }),
    { id: "example-delta", variant: null, revision: 0, name: "example-delta" });
  assert.equal(runProfileRef({ profile: { id: "a", revision: null } }).revision, null);
  assert.equal(runProfileRef({ profile: { id: "a", revision: 1.5 } }).revision, null);
  for (const bad of [undefined, null, {}, { profile: null }, { profile: { id: "" } }, { profile: { id: 3 } }]) {
    assert.equal(runProfileRef(bad), null, JSON.stringify(bad));
  }
});

test("profileDocPath·refLabel: 리비전을 알면 그 리비전을 받는다", () => {
  assert.equal(profileDocPath({ id: "showcase-delta", revision: 3 }), "/profiles/showcase-delta?revision=3");
  assert.equal(profileDocPath({ id: "example-delta", revision: 0 }), "/profiles/example-delta?revision=0");
  assert.equal(profileDocPath({ id: "a b", revision: null }), "/profiles/a%20b");
  assert.equal(refLabel({ name: "S1", variant: "eoir", revision: 3 }), "S1 / eoir · r3");
  assert.equal(refLabel({ name: "S1", variant: null, revision: null }), "S1");
  assert.equal(refLabel(null), "기체 미상");
});

test("launchLimitFrom: 적용 문서의 n_x_launch — 없거나 0 이하면 null (지어내지 않는다)", () => {
  const ref = { name: "S1", variant: null, revision: 2 };
  assert.deepEqual(launchLimitFrom({ structural: { n_x_launch: 8 } }, ref), { nx: 8, source: "S1 · r2" });
  for (const v of [null, undefined, 0, -1, NaN, "8"]) {
    assert.equal(launchLimitFrom({ structural: { n_x_launch: v } }, ref).nx, null, String(v));
  }
  assert.equal(launchLimitFrom(null, ref).nx, null);
});

test("landingLine: 착륙 요약 행을 한 줄로 — 행의 값·사유를 그대로", () => {
  const rows = landingSummary(landingBody(), { launchLimit: { nx: 40, source: "S1" } });
  const line = landingLine(rows);
  assert.match(line, /^접지 0\.03 s \(강하율 -0\.98 m\/s · 속도 79\.5 m\/s\)/);
  assert.match(line, /활주로 축 \+300 m/);
  assert.match(line, /정지 0\.05 s \(접지→정지 직선거리 600 m \/ 활주로 1500 m\)/);
  assert.match(line, /발사하중 한계 안$/);
  // 초과는 표지 이름으로
  const over = landingLine(landingSummary(landingBody(), { launchLimit: { nx: 8, source: "S1" } }));
  assert.match(over, /발사하중 초과$/);
  // 접지가 없으면 null — 호출측이 모드 체인으로 대신 말한다
  const air = landingBody();
  air.meta.phases = { launch_exit_t: 0.02, touchdown_t: null, stop_t: null };
  assert.equal(landingLine(landingSummary(air)), null);
  assert.equal(landingLine([]), null);
});

test("idleTail: 정지 뒤 t_end까지 — 예제 기본 미션 실측(512.7 s / 750 s)", () => {
  const body = { meta: { t_end: 750, aborted: null, phases: { stop_t: 512.7 } } };
  const tail = idleTail(body);
  assert.ok(Math.abs(tail.idle - 237.3) < 1e-9);
  assert.ok(Math.abs(tail.frac - 237.3 / 750) < 1e-12);
  assert.match(idleTailNote(body), /정지\(512\.7 s\) 뒤 t_end 750 s까지 237 s\(전 구간의 32 %\)/);
  // 정지 + 20 s(템플릿 규약)는 안내하지 않는다
  assert.equal(idleTailNote({ meta: { t_end: 532.7, phases: { stop_t: 512.7 } } }), null);
  // 짧은 런의 큰 비율도 30 s 이하면 조용히
  assert.equal(idleTailNote({ meta: { t_end: 40, phases: { stop_t: 15 } } }), null);
  // 정지가 없거나 절단됐거나 t_end를 모르면 null
  assert.equal(idleTail({ meta: { t_end: 750, phases: { stop_t: null } } }), null);
  assert.equal(idleTail({ meta: { t_end: 750, aborted: "altitude", phases: { stop_t: 100 } } }), null);
  assert.equal(idleTail({ meta: { phases: { stop_t: 100 } } }), null);
  assert.equal(idleTail({ meta: { t_end: 50, phases: { stop_t: 100 } } }), null);
  assert.equal(idleTail(null), null);
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

test("landingSummary: 횡편차가 길이를 넘으면 폭을 몰라도 옆이라고 단정한다", () => {
  // 활주로가 자기 길이보다 넓을 수는 없다 — 축방향 하한과 같은 논법이다. 폭을 안 넘겨도 판정한다.
  const wide = landingSummary(landingBody({
    signals: {
      ...landingBody().signals,
      pn: [0, 100, 200, 300, 700, 900], pe: [0, 0, 0, 3000, 3000, 3000],
    },
  }));
  const lat = wide.find((r) => r.label === "접지 횡편차");
  assert.equal(lat.value, "+3,000 m");
  assert.equal(lat.over, true, "횡편차 3000 m인데 판정 불가로 나온다");
  assert.equal(lat.unjudged, undefined);
  assert.equal(lat.overLabel, "활주로 옆");
  assert.match(lat.note, /활주로 길이 1,500 m보다 멀다/);
  // 축방향은 축방향대로 — 300 m는 구간 안이다(두 축을 한 행에 섞지 않는다)
  assert.equal(wide.find((r) => r.label === "접지 지점").over, false);
  // 정지 지점도 같은 자로 — 옆에 섰다
  const stop = wide.find((r) => r.label === "정지");
  assert.equal(stop.over, true);
  assert.equal(stop.overLabel, "활주로 옆 정지");
  assert.match(stop.note, /정지 지점 횡편차 \+3,000 m > 활주로 길이 1,500 m/);
});

test("landingSummary: 접지 지점은 10 m 단위 — 판정에 그 이하 자릿수가 필요 없다", () => {
  // 위치는 사건 시각에서 보간해 표본 간격(13~16 m)이 오차가 아니지만, 접지 지점은 미션의 작은 섭동에도 미터
  // 단위로 움직인다(마지막 WP 1 m → 3.4 m). 1 m 단위로 내면 그 흔들림이 런 사이의 차이처럼 읽힌다(replay.js r10 주석).
  const rows = landingSummary(landingBody({
    signals: { ...landingBody().signals, pn: [0, 100, 200, 7073, 7400, 7870] },
  }));
  const spot = rows.find((r) => r.label === "접지 지점");
  assert.match(spot.value, /7,070 m/, "1 m 단위로 찍고 있다");
});

// ---- 사건 시각 보간 ----
//
// 재생 응답은 stride로 솎여 있고(쇼케이스 기체 0.32 s · 예제 기체 0.5 s), 접지·정지 **시각**은 엔진이 전 해상도에서
// 잰 meta.phases 값이다. 가장 가까운 표본 하나의 위치를 쓰던 때는 지점이 표본 한 칸(13~16 m)씩 뛰었다 — 활주로 축
// 보정 뒤 접지가 0.09 s(3.4 m) 옮겼을 뿐인데 화면이 +340 → +320 m를 말했다. 아래 본문은 그 간격(0.5 s)을 흉내 낸다.
const sparseBody = (over = {}) => landingBody({
  t: [0, 0.5, 1.0, 1.5, 2.0, 2.5],
  signals: {
    ...landingBody().signals,
    // 40 m/s로 활주로 축(북)을 따라 달리다 2.0 s에 선다
    pn: [300, 320, 340, 360, 380, 380], pe: [0, 0, 0, 0, 0, 0],
    ...over.signals,
  },
  meta: {
    ...landingBody().meta,
    phases: { launch_exit_t: null, touchdown_t: 0.7, stop_t: 1.9, td_sink_rate: -0.5, td_speed: 40, ...over.phases },
  },
});
const spotOf = (rows) => rows.find((r) => r.label === "접지 지점");

test("landingSummary: 접지 지점은 사건 시각에서 두 표본 사이를 보간한다 — 가까운 표본으로 한 칸 뛰지 않는다", () => {
  // 0.7 s = 0.5 s 표본(320 m)과 1.0 s 표본(340 m) 사이 → 328 m. 가까운 표본이면 320 m다
  assert.equal(spotOf(landingSummary(sparseBody())).value, "활주로 축 +330 m");
  // 접지가 0.02 s(0.8 m) 옮긴 두 런 — 가까운 표본은 0.74 → 320 m, 0.76 → 340 m로 20 m를 뛰었다
  for (const td of [0.74, 0.76]) {
    assert.equal(spotOf(landingSummary(sparseBody({ phases: { touchdown_t: td } }))).value, "활주로 축 +330 m", `td=${td}`);
  }
});

test("landingSummary: 횡편차도 사건 시각에서 보간한다", () => {
  // 0.5 s에 0 m, 1.0 s에 +4 m — 0.8 s 접지는 +2.4 m(가까운 표본이면 +4 m)
  const rows = landingSummary(sparseBody({ signals: { pe: [0, 0, 4, 4, 4, 4] }, phases: { touchdown_t: 0.8 } }),
    { runwayWidth: { width: 45, source: "시험장 제원" } });
  assert.equal(latRow(rows).value, "+2 m");
});

test("landingSummary: 접지→정지 거리도 두 보간 위치 사이다 — 지점 행과 같은 위치", () => {
  // 접지 0.7 s → 328 m, 정지 1.9 s → 1.5 s 표본(360 m)과 2.0 s 표본(380 m) 사이 376 m → 48 m.
  // 가까운 표본끼리면 320 → 380 m라 60 m였다
  const stop = landingSummary(sparseBody()).find((r) => r.label === "정지");
  assert.match(stop.note, /^접지→정지 직선거리 48 m \/ 활주로 1500 m/);
});

test("landingSummary: 사건을 끼는 표본 하나가 결측이면 지점을 지어내지 않는다 — 거리도 0으로 메우지 않는다", () => {
  // 0.7 s를 끼는 0.5 s 표본이 결측 — 한쪽 표본으로 눙치면 그 한 칸 오차가 되돌아온다
  const rows = landingSummary(sparseBody({ signals: { pn: [300, null, 340, 360, 380, 380] } }));
  assert.equal(spotOf(rows), undefined);
  assert.equal(latRow(rows), undefined);
  const stop = rows.find((r) => r.label === "정지");
  // 종전에는 결측을 0으로 메워 원점에서 정지 지점까지(380 m)를 「접지→정지」라 했다
  assert.match(stop.note, /^접지→정지 직선거리 미계측 \/ 활주로 1500 m/);
  assert.equal(stop.over, false, "모르는 거리로 초과를 말하지 않는다");
  // 결측이 사건을 끼지 않는 표본이면 상관없다
  assert.equal(spotOf(landingSummary(sparseBody({ signals: { pn: [null, 320, 340, 360, 380, 380] } }))).value,
    "활주로 축 +330 m");
});

test("landingSummary: 사건 시각이 표본과 겹치거나 재생 구간 밖이면 그 끝 표본이다", () => {
  assert.equal(spotOf(landingSummary(sparseBody({ phases: { touchdown_t: 1.0 } }))).value, "활주로 축 +340 m");
  // 재생 구간 밖 — 끝 표본(재생이 거기서 끝났다). 앞쪽도 같다
  assert.equal(spotOf(landingSummary(sparseBody({ phases: { touchdown_t: 9, stop_t: null } }))).value, "활주로 축 +380 m");
  assert.equal(spotOf(landingSummary(sparseBody({ phases: { touchdown_t: -1, stop_t: null } }))).value, "활주로 축 +300 m");
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

test("landingSummary: 구간 안은 **축방향만** 통과다 — 폭을 모르면 횡편차 행이 판정 불가", () => {
  // 축방향이 0~length 안이라는 것은 활주로에 내렸다는 뜻이 아니다. 접지 지점 행은 축방향만
  // 말하고(표지 이름도 「축 구간 안」), 옆으로 얼마나 벗어났는지는 접지 횡편차 행이 폭과 견준다 —
  // 폭을 대조하지 않았으면 그 행은 미판정이지 통과가 아니다.
  const near = landingSummary(landingBody({
    signals: { ...landingBody().signals, pn: [0, 100, 200, 300, 700, 900] },
  }));
  const spot = near.find((r) => r.label === "접지 지점");
  assert.equal(spot.over, false);
  assert.equal(spot.pass, true);
  assert.equal(spot.passLabel, "축 구간 안", "축방향 통과가 활주로 안착처럼 읽히는 이름이면 안 된다");
  assert.match(spot.note, /횡방향은 접지 횡편차 행/);
  const lat = near.find((r) => r.label === "접지 횡편차");
  assert.equal(lat.unjudged, true, "폭을 모르는데 통과로 말한다");
  assert.equal(lat.pass, undefined);
  assert.equal(lat.over, false);
  assert.match(lat.note, /활주로 폭과 대조하지 않았다, 판정 불가/);
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
  // 북쪽 300 m는 동향 활주로의 왼쪽(−) 300 m다 — 횡편차로 나온다
  assert.equal(east.find((r) => r.label === "접지 횡편차").value, "-300 m");
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

test("landingSummary: 정지 **지점**도 활주로 안팎을 판정한다", () => {
  // 종전에는 접지→정지 **거리**만 길이와 견주어, 7 km 북쪽 논에 선 기본 미션이
  // "869 m / 활주로 1205 m"라 통과처럼 읽혔다. 거리가 짧은 것과 활주로에 선 것은 다르다.
  const far = landingSummary(landingBody({
    signals: { ...landingBody().signals, pn: [0, 100, 200, 7000, 7400, 7870] },
  }));
  const stop = far.find((r) => r.label === "정지");
  assert.match(stop.note, /870 m/, "거리 비교는 그대로 산다");
  assert.match(stop.note, /활주로 1500 m/);
  assert.match(stop.note, /정지 지점이 활주로 구간 밖이다 \(축 \+?7,870 m\)/);
  assert.equal(stop.over, true, "거리는 짧아도 지점이 밖이면 배지를 단다");
  assert.equal(stop.overLabel, "활주로 밖 정지");
  assert.equal(stop.unjudged, undefined, "밖이라고 단정했으면 미판정이 아니다");
});

test("landingSummary: 활주로 구간 안에 서도 폭을 모르면 미판정 — 통과로 위장하지 않는다", () => {
  const rows = landingSummary(landingBody()); // pn 300 → 900, 활주로 1500
  const stop = rows.find((r) => r.label === "정지");
  assert.equal(stop.over, false);
  assert.match(stop.note, /정지 지점은 구간 안, 횡편차 0 m — 활주로 폭과 대조하지 않았다, 판정 불가/);
  assert.equal(stop.unjudged, true);
  assert.equal(stop.pass, undefined);
  // 폭을 받으려 했으나 못 받았으면 그 사유가 그대로 나온다
  const why = landingSummary(landingBody(), { runwayWidth: { error: "시험장 제원에 활주로 폭이 없다" } })
    .find((r) => r.label === "정지");
  assert.match(why.note, /시험장 제원에 활주로 폭이 없다, 판정 불가/);
  assert.equal(why.unjudged, true);
});

test("landingSummary: 방위가 없으면 정지 지점 판정도 없다 — 접지 지점과 같은 규약", () => {
  const rows = landingSummary(landingBody({
    meta: { ...landingBody().meta, runway: { elevation: 0, length: 1500 } },
  }));
  const stop = rows.find((r) => r.label === "정지");
  assert.doesNotMatch(stop.note, /정지 지점/);
  assert.match(stop.note, /활주로 1500 m/, "길이 비교는 방위 없이도 성립한다");
});

// ---- 횡편차 판정 — 활주로 폭(시험장 제원)의 반폭 − 가장자리 여유 (lib/replay.js lateralVerdict) ----
//
// 쇼케이스 기체가 장주에서 중심선에 못 들어와 모든 조건에서 20~24 m 옆에 내렸는데, 요약은 축방향만
// 판정해 조용히 넘어갔다. 아래는 그 판정이 폭을 받았을 때·못 받았을 때 각각 무엇을 말하는지 고정한다.

const SITE = Object.freeze({ runwayWidthM: 45, runwayLengthM: 1500, runwayHeadingRad: 0 });
const W45 = runwayWidthFor(landingBody().meta.runway, SITE);
// 활주로 방위 0이라 pe가 곧 횡편차다(오른쪽 +)
const withCross = (pe) => landingBody({ signals: { ...landingBody().signals, pe: Array(6).fill(pe) } });
const latRow = (rows) => rows.find((r) => r.label === "접지 횡편차");

test("runwayWidthFor: 그 런이 시험장 활주로를 썼을 때만 그 폭을 준다 — 없으면 사유", () => {
  assert.deepEqual(W45, { width: 45, source: "시험장 제원" });
  const rw = { heading: 0, length: 1500 };
  // 제원에 폭이 없으면 지어내지 않는다
  assert.match(runwayWidthFor(rw, { runwayLengthM: 1500, runwayHeadingRad: 0 }, "고흥 시험장 제원").error,
    /^고흥 시험장 제원에 활주로 폭이 없다$/);
  assert.match(runwayWidthFor(rw, { ...SITE, runwayWidthM: -1 }).error, /활주로 폭이 없다/);
  // 폭이 가장자리 여유의 두 배 이하면 한계가 서지 않는다
  assert.match(runwayWidthFor(rw, { ...SITE, runwayWidthM: 3 }).error, /두 배 이하라 한계가 서지 않는다/);
  // 폼에서 길이·방위를 고친 런은 다른 활주로다 — 시험장 폭을 빌려 쓰지 않는다
  assert.match(runwayWidthFor({ heading: 0, length: 1200 }, SITE).error, /길이 1200 m\)가 시험장 제원의 활주로.*달라 그 폭을 쓸 수 없다/);
  assert.match(runwayWidthFor({ heading: 0.1, length: 1500 }, SITE).error, /달라 그 폭을 쓸 수 없다/);
  // 표기 반올림 안의 차이 · 한 바퀴 감긴 방위는 같은 활주로다
  assert.equal(runwayWidthFor({ heading: 2e-5, length: 1500.2 }, SITE).width, 45);
  assert.equal(runwayWidthFor({ heading: 2 * Math.PI, length: 1500 }, SITE).width, 45);
  // 런의 활주로를 모르면 대조할 수 없다
  assert.ok(runwayWidthFor(undefined, SITE).error);
  assert.ok(runwayWidthFor({ length: 1500 }, SITE).error);
});

test("landingSummary: 45 m 활주로의 횡편차 한계는 21 m — CS-AWO 외측 착륙장치 한계와 같은 수", () => {
  assert.equal(RUNWAY_EDGE_MARGIN_M, 1.5);
  const rows = landingSummary(withCross(3), { runwayWidth: W45 });
  const lat = latRow(rows);
  assert.equal(lat.value, "+3 m");
  assert.equal(lat.pass, true);
  assert.equal(lat.passLabel, "폭 안");
  assert.equal(lat.over, false);
  assert.equal(lat.unjudged, undefined, "판정했으면 미판정 표지가 없다");
  // 사유는 한계와 그 근거(출처·폭·반폭·여유)를 함께 — 수를 보고 검산할 수 있게
  assert.equal(lat.note, "|횡편차| ≤ 한계 21 m (시험장 제원 활주로 폭 45 m의 반폭 22.5 m − 가장자리 여유 1.5 m)");
  for (const r of rows) {
    const text = [r.label, r.value, r.note, r.overLabel, r.passLabel].filter(Boolean).join(" ");
    assert.doesNotMatch(text, /\*\*|`|<[a-z]/i, `${r.label}: 마크다운·마크업 잔재`);
  }
});

test("landingSummary: 한계 밖 — 반폭 안이면 「가장자리 근접」, 반폭 밖이면 「활주로 옆」", () => {
  const at = (pe) => latRow(landingSummary(withCross(pe), { runwayWidth: W45 }));
  assert.equal(at(21).pass, true, "한계 21 m 자체는 안이다");
  assert.equal(at(-21).pass, true, "왼쪽도 같은 한계");
  const edge = at(21.1);
  assert.equal(edge.over, true);
  assert.equal(edge.overLabel, "가장자리 근접");
  assert.equal(edge.pass, undefined);
  assert.match(edge.note, /^\|횡편차\| > 한계 21 m /);
  const off = at(-23);
  assert.equal(off.over, true);
  assert.equal(off.overLabel, "활주로 옆", "반폭 22.5 m 밖은 포장면 밖이다");
  assert.equal(off.value, "-23 m");
});

test("landingSummary: 횡편차는 1 m 단위 — −0.3은 「-0」이 아니라 0이다", () => {
  const v = (pe) => latRow(landingSummary(withCross(pe), { runwayWidth: W45 })).value;
  assert.equal(v(-0.3), "0 m");
  assert.equal(v(20.6), "+21 m");
  assert.equal(v(-7.4), "-7 m");
});

test("landingSummary: 정지 지점도 같은 횡편차 자로 — 폭 안이면 통과, 밖이면 배지", () => {
  const stopOf = (body, opts) => landingSummary(body, opts).find((r) => r.label === "정지");
  const ok = stopOf(withCross(2), { runwayWidth: W45 });
  assert.equal(ok.over, false);
  assert.equal(ok.pass, true);
  assert.equal(ok.passLabel, "활주로 안");
  assert.equal(ok.unjudged, undefined);
  assert.match(ok.note, /정지 지점 활주로 안 \(횡편차 \+2 m ≤ 한계 21 m\)$/);
  const edge = stopOf(withCross(22), { runwayWidth: W45 });
  assert.equal(edge.over, true);
  assert.equal(edge.overLabel, "가장자리 근접 정지");
  assert.equal(edge.pass, undefined);
  assert.match(edge.note, /정지 지점 횡편차 \+22 m > 한계 21 m$/);
  // 미끄럼이 활주로 길이를 넘었으면 선 자리가 폭 안이어도 통과가 아니다(시단 앞 접지 → 구간 안 정지)
  const long = stopOf(landingBody({
    signals: { ...landingBody().signals, pn: [0, -100, -200, -300, 100, 400] },
    meta: { ...landingBody().meta, runway: { elevation: 0, heading: 0, length: 500 } },
  }), { runwayWidth: { width: 45, source: "시험장 제원" } });
  assert.equal(long.over, true);
  assert.equal(long.pass, undefined);
  assert.equal(long.overLabel, undefined, "거리 초과는 지점 표지가 아니다 — landingLine이 「활주로 초과」로 말한다");
  assert.match(long.note, /넘어섰다 · 정지 지점 활주로 안/);
});

// ---- 고흥 시험장 폭 (siteRunwayWidth) ----
//
// 폭이 시험장 제원(lib/site.js)에 없던 동안 이 판정은 어느 런에서나 「고흥 시험장 제원에 활주로 폭이 없다,
// 판정 불가」였다. 아래는 **시뮬 탭 기본 폼이 실제로 보내는 활주로**로 그 사슬 끝의 문장까지 고정한다.

const defaultRunway = () => buildSimRequest(
  DEFAULT_FORM, defaultModeRows(), defaultWpRows(), appliedFrom(() => undefined)).req.runway;

test("siteRunwayWidth: 기본 미션의 활주로는 고흥 폭 45 m(공표 제원)를 받는다 — 고친 활주로는 빌리지 않는다", () => {
  const rw = defaultRunway();
  assert.deepEqual(siteRunwayWidth(rw), { width: 45, source: "고흥 시험장 제원" });
  assert.match(siteRunwayWidth({ ...rw, length: 1500 }).error, /고흥 시험장 제원의 활주로.*달라 그 폭을 쓸 수 없다/);
  assert.match(siteRunwayWidth({ ...rw, heading: 0 }).error, /달라 그 폭을 쓸 수 없다/);
});

test("landingSummary: 고흥 활주로를 쓴 런 — 한계 21 m로 판정하고 근거에 출처·폭을 적는다", () => {
  const rw = defaultRunway();
  const h = rw.heading;
  // 활주로 축 a · 횡편차 c(오른쪽 +)인 점을 NED로 — 방위가 0이 아니라 pe가 곧 횡편차가 아니다
  const body = (c) => {
    const pts = [0, 100, 200, 300, 500, 600].map((a) => [a * Math.cos(h) - c * Math.sin(h), a * Math.sin(h) + c * Math.cos(h)]);
    return landingBody({
      signals: { ...landingBody().signals, pn: pts.map((p) => p[0]), pe: pts.map((p) => p[1]) },
      meta: { ...landingBody().meta, runway: rw },
    });
  };
  const rows = landingSummary(body(-0.6), { runwayWidth: siteRunwayWidth(rw) });
  const lat = latRow(rows);
  assert.equal(lat.value, "-1 m");
  assert.equal(lat.pass, true);
  assert.equal(lat.unjudged, undefined);
  assert.equal(lat.note, "|횡편차| ≤ 한계 21 m (고흥 시험장 제원 활주로 폭 45 m의 반폭 22.5 m − 가장자리 여유 1.5 m)");
  const stop = rows.find((r) => r.label === "정지");
  assert.equal(stop.passLabel, "활주로 안");
  assert.match(stop.note, /정지 지점 활주로 안 \(횡편차 -1 m ≤ 한계 21 m\)$/);
  // 한계와 반폭 사이 · 반폭 밖
  assert.equal(latRow(landingSummary(body(22), { runwayWidth: siteRunwayWidth(rw) })).overLabel, "가장자리 근접");
  assert.equal(latRow(landingSummary(body(-24), { runwayWidth: siteRunwayWidth(rw) })).overLabel, "활주로 옆");
});

test("landingLine: 횡편차가 한 줄에 들어간다 — 축방향만으로 섰다고 읽히지 않게", () => {
  const edge = landingLine(landingSummary(withCross(22), { launchLimit: { nx: 40, source: "S1" }, runwayWidth: W45 }));
  assert.match(edge, /활주로 축 \+300 m · 횡편차 \+22 m — 가장자리 근접 · 정지 0\.05 s \(.*\) — 가장자리 근접 정지 · 발사하중 한계 안$/);
  const ok = landingLine(landingSummary(withCross(0), { runwayWidth: W45 }));
  assert.match(ok, /활주로 축 \+300 m · 횡편차 0 m · 정지 /);
});

// ---- 경로 탈출 안내 ----

test("pathEscapeNote: 넘어간 웨이포인트를 **1 기준**으로 말한다 (표의 행 번호와 같은 어휘)", () => {
  const note = pathEscapeNote({ meta: { path_escapes: [0, 3] } });
  assert.match(note, /웨이포인트 1, 4번/);
  assert.match(note, /한 바퀴/);
});

test("pathEscapeNote: 넘어간 것이 없으면 null — 조용한 정상이 기본이다", () => {
  assert.equal(pathEscapeNote({ meta: { path_escapes: [] } }), null);
  assert.equal(pathEscapeNote({ meta: {} }), null);
  assert.equal(pathEscapeNote({}), null);
  assert.equal(pathEscapeNote(undefined), null);
});
