// 가이드 투어 판단 — 사전 판정·단계 표시·끝 시각·마무리 모델·캡션 (DOM 없이)
import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";

import { normalizeDraft } from "./missiondraft.js";
import { GOHEUNG } from "./site.js";
import { defaultModeRows, defaultWpRows } from "./simrequest.js";
import {
  SPEECH_GATE, STAGES, TAIL_S, TOUR_SPEED, captionFor, endTimeFor, finaleModel, precheck, stepperModel,
} from "./tour.js";

const draft = (over = {}) => normalizeDraft({
  summary: "발사 후 순항하고 착륙",
  assumptions: ["순항 200 m", "88 m/s", "도달 반경 100 m"],
  modeRows: defaultModeRows(),
  wpRows: defaultWpRows(),
  runConditions: { mach: "0", alt: "0", fuel: "300", groundOn: true, launchOn: true,
    tEnd: "200", accept: "100" },
  warnings: [],
  ...over,
});

test("멀쩡한 초안은 막힘도 경고도 없다", () => {
  const { blockers, warnings } = precheck(draft());
  assert.deepEqual(blockers, []);
  assert.deepEqual(warnings, []);
});

test("검증 정본이 거부할 초안은 시뮬 전에 막는다 — 422를 조용히 맞지 않는다", () => {
  const rows = defaultModeRows();
  rows[1] = { ...rows[1], exitValue: "" };
  const { blockers } = precheck(draft({ modeRows: rows }));
  assert.match(blockers.join(" "), /값이 비어 있음/);
});

test("모드가 없으면 막되 같은 말을 경고로 두 번 하지 않는다", () => {
  const { blockers, warnings } = precheck(draft({ modeRows: [] }));
  assert.match(blockers.join(" "), /모드 행이 없다/);
  assert.ok(!warnings.some((m) => /모드 행이 없다/.test(m)));
});

test("정규화가 고친 것은 막지 않고 경고로 남긴다", () => {
  const rows = defaultModeRows();
  rows[0] = { ...rows[0], lonAxis: "vs" }; // off로 고쳐진다 — 실행은 된다
  const { blockers, warnings } = precheck(draft({ modeRows: rows }));
  assert.deepEqual(blockers, []);
  assert.match(warnings.join(" "), /모르는 종방향 축/);
});

test("단계 표시 — 지난 단계는 완료, 지금은 진행, 실패는 그 자리에", () => {
  assert.deepEqual(stepperModel("sim", null).map((s) => s.state),
    ["done", "active", "todo", "todo", "todo"]);
  assert.deepEqual(stepperModel("comms", "comms").map((s) => s.state),
    ["done", "done", "failed", "todo", "todo"]);
  assert.deepEqual(stepperModel("done", null).map((s) => s.state), STAGES.map(() => "done"));
  assert.deepEqual(stepperModel("draft", null).map((s) => s.label), STAGES.map((s) => s.label));
});

test("투어 배속은 가상환경 음성 게이트 아래여야 한다 — 넘으면 교신이 자막만 흐른다", () => {
  // 번들 경계를 넘는 짝이라 주석으로는 갈린다 (core/comms.ts SPEECH_MAX_SPEED = 5)
  assert.ok(TOUR_SPEED <= 5, `투어 배속 ${TOUR_SPEED}×가 음성 게이트를 넘었다`);
  assert.ok(TAIL_S > 0 && TAIL_S <= 5, `정지 뒤 여유 ${TAIL_S}s — 길면 빈 화면을 다시 본다`);
});

test("끝 시각은 정지 + 여유 — 정지가 없으면 null(데이터 끝까지 재생)", () => {
  // **리터럴로** 박는다 — `stop_t + TAIL_S`로 적으면 TAIL_S가 바뀌어도 통과한다
  assert.equal(endTimeFor({ meta: { phases: { stop_t: 101.5 } } }), 104.5);
  assert.equal(endTimeFor({ meta: { phases: { stop_t: null } } }), null);
  assert.equal(endTimeFor({ meta: {} }), null);
  assert.equal(endTimeFor(null), null);
});

test("마무리 — 시뮬 탭과 같은 착륙 요약을 쓰고, 없으면 그 사실을 말한다", () => {
  const body = { t: [0, 1, 2], signals: {}, meta: { phases: {
    launch_exit_t: null, touchdown_t: 1, stop_t: null, td_sink_rate: -0.9, td_speed: 79 } } };
  const m = finaleModel(body);
  assert.ok(m.rows.some((r) => r.label === "접지"));
  assert.equal(m.note, null);
  const empty = finaleModel({ t: [], signals: {}, meta: {} });
  assert.deepEqual(empty.rows, []);
  assert.match(empty.note, /착륙 구간이 없/);
});

test("마무리 — 레일 이탈 행은 시뮬 탭과 같은 발사하중 한계로 판정한다(넘기지 않으면 판정 불가)", () => {
  // meta.launch = 그 런이 쓴 레일(서버가 동봉) — 판정은 축방향 하중배수 5.1 + sin 0.26 = 5.36 g
  const body = { t: [0, 0.1, 0.2], signals: { launch_gx: [0, 5.1, 3] },
    meta: { phases: { launch_exit_t: 0.2, touchdown_t: null, stop_t: null }, launch: { elev_angle: 0.26 } } };
  const rail = (m) => m.rows.find((r) => r.label === "레일 이탈");
  const ok = rail(finaleModel(body, { launchLimit: { nx: 8, source: "S1 · r2" } }));
  assert.equal(ok.pass, true);
  assert.ok(ok.passLabel);
  assert.equal(ok.unjudged, undefined);
  const over = rail(finaleModel(body, { launchLimit: { nx: 4, source: "S1 · r2" } }));
  assert.equal(over.over, true);
  // 순가속(5.1 g)만이면 한계 안이지만 중력 성분을 더하면 넘는다 — 시뮬 탭과 같은 n_x로 판정한다
  const grav = rail(finaleModel(body, { launchLimit: { nx: 5.2, source: "S1 · r2" } }));
  assert.equal(grav.over, true);
  assert.match(grav.note, /축방향 하중배수 5\.36 g \(레일 가속 5\.10 g \+ 중력 성분 0\.26 g\)/);
  // 한계 조회 실패는 사유와 함께 판정 불가 — 통과로 위장하지 않는다
  const failed = rail(finaleModel(body, { launchLimit: { error: "문서를 받지 못했다" } }));
  assert.equal(failed.unjudged, true);
  assert.match(failed.note, /문서를 받지 못했다/);
  assert.equal(rail(finaleModel(body)).unjudged, true, "안 넘기면 대조하지 않은 것");
  // 조립(views/tour.js)이 실제로 넘긴다 — 원문 대조(뷰는 테스트가 import하지 않는다)
  const view = readFileSync(new URL("../views/tour.js", import.meta.url), "utf8");
  assert.match(view, /launchLimitOf\(replay\.meta\)/);
  assert.match(view, /finaleModel\(replay, \{ launchLimit \}\)/);
  assert.match(view, /r\.pass \? el\("span", \{ class: "flag ok" \}/, "통과 표지도 그린다");
});

test("마무리 — 접지·정지 횡편차는 시뮬 탭과 같은 고흥 활주로 폭으로 판정한다(고친 활주로는 빌리지 않는다)", () => {
  // 그 런이 쓴 활주로(서버가 meta.runway로 동봉) = 시뮬 탭 기본 폼의 고흥 제원. 방위가 0이 아니라
  // 활주로 축 a · 횡편차 c인 점을 NED로 돌려 놓는다
  const h = GOHEUNG.runwayHeadingRad;
  const at = (a, c) => [a * Math.cos(h) - c * Math.sin(h), a * Math.sin(h) + c * Math.cos(h)];
  const pts = [at(0, 0), at(300, -0.6), at(700, -0.6)];
  const body = { t: [0, 1, 2], signals: { pn: pts.map((p) => p[0]), pe: pts.map((p) => p[1]) },
    meta: { phases: { launch_exit_t: null, touchdown_t: 1, stop_t: 2, td_sink_rate: -0.9, td_speed: 31 },
      runway: { elevation: 0, heading: h, length: GOHEUNG.runwayLengthM } } };
  const lat = finaleModel(body).rows.find((r) => r.label === "접지 횡편차");
  // 종전에는 폭을 안 넘겨 「활주로 폭과 대조하지 않았다, 판정 불가」였다 — 시뮬 탭은 같은 런을 「폭 안」이라 했다
  assert.match(lat.note, /한계 21 m \(고흥 시험장 제원/);
  assert.equal(lat.pass, true);
  assert.equal(lat.unjudged, undefined);
  const stop = finaleModel(body).rows.find((r) => r.label === "정지");
  assert.match(stop.note, /≤ 한계 21 m\)$/);
  // 폼에서 활주로를 고친 런 — 남의 기하로 판정하지 않는다(사유를 단 판정 불가)
  const edited = { ...body, meta: { ...body.meta, runway: { ...body.meta.runway, length: 1500 } } };
  const e = finaleModel(edited).rows.find((r) => r.label === "접지 횡편차");
  assert.equal(e.unjudged, true);
  assert.match(e.note, /달라 그 폭을 쓸 수 없다/);
});

test("캡션은 기존 산출물로 — 초안 요약·가정, 모드 사슬·진행률, 교신 줄 수", () => {
  assert.match(captionFor("draft", { intent: "북쪽 5 km" }), /북쪽 5 km/);
  const d = captionFor("draft", { draft: draft() });
  assert.match(d, /발사 후 순항하고 착륙/);
  assert.match(d, /순항 200 m · 88 m\/s/); // 가정은 앞 둘만 — 캡션은 한 줄이다
  assert.doesNotMatch(d, /도달 반경/);
  const s = captionFor("sim", { modes: ["launch", "climb"], progress: 0.4 });
  assert.match(s, /launch → climb/);
  assert.match(s, /40%/);
  assert.match(captionFor("comms", {}), /교신 대본/);
  assert.match(captionFor("comms", { failed: "401" }), /교신 없이.*401/);
  assert.match(captionFor("play", { lines: 12, voice: true }),
    new RegExp(`12줄.*${TOUR_SPEED}×.*음성`));
  assert.match(captionFor("play", { lines: 0 }), /교신 없음/);
});

test("재생 캡션은 실제로 건 배속을 말한다 — 게이트를 넘으면 「음성」이라 적지 않는다", () => {
  // 쇼케이스 진행기는 교신이 없으면 투어보다 빨리 튼다(lib/showcase worldSpeedFor) — 종전 캡션은 늘 투어 배속(2×)
  assert.equal(captionFor("play", { lines: 0, voice: true, speed: 10 }), "3D 재생 — 교신 없음 · 10×");
  assert.equal(captionFor("play", { lines: 9, voice: true, speed: SPEECH_GATE }),
    `3D 재생 — 교신 9줄 · ${SPEECH_GATE}× · 음성`);
  assert.equal(captionFor("play", { lines: 9, voice: true, speed: SPEECH_GATE + 5 }),
    `3D 재생 — 교신 9줄 · ${SPEECH_GATE + 5}×`, "게이트 위는 자막만 — 음성이라 적으면 거짓말");
  // 안 넘기면(투어) 투어 배속 그대로
  assert.equal(captionFor("play", { lines: 0 }), `3D 재생 — 교신 없음 · ${TOUR_SPEED}×`);
  for (const bad of [0, -2, NaN, "10"]) {
    assert.equal(captionFor("play", { lines: 0, speed: bad }), `3D 재생 — 교신 없음 · ${TOUR_SPEED}×`, String(bad));
  }
});
