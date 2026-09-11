// 가이드 투어 판단 — 사전 판정·단계 표시·끝 시각·마무리 모델·캡션 (DOM 없이)
import { test } from "node:test";
import assert from "node:assert/strict";

import { normalizeDraft } from "./missiondraft.js";
import { defaultModeRows, defaultWpRows } from "./simrequest.js";
import {
  STAGES, TAIL_S, TOUR_SPEED, captionFor, endTimeFor, finaleModel, precheck, stepperModel,
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
