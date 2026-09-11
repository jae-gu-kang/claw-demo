// LLM 미션 초안 정규화 검증 — 방어적 수용(문자열 강제·안전값+사유)과
// 제출 가능성 사전 판정(검증 정본 재사용 — 재구현 없음)
import { test } from "node:test";
import assert from "node:assert/strict";

import { dryRun, normalizeDraft } from "./missiondraft.js";

const modeRow = (over = {}) => ({
  name: "cruise", speed: "88", lonAxis: "alt", lonValue: "200", heading: "path",
  exitKind: "path_done", exitValue: "", next: "", ...over,
});

const draft = (over = {}) => ({
  summary: "요약", assumptions: ["가정"],
  modeRows: [modeRow()],
  wpRows: [{ n: "5000", e: "0", d: "" }],
  runConditions: { mach: "0", alt: "", fuel: "300", groundOn: true,
                   launchOn: false, tEnd: "200", accept: "" },
  warnings: ["주의"],
  ...over,
});

test("정상 초안은 그대로 통과하고 이슈가 없다", () => {
  const d = normalizeDraft(draft());
  assert.equal(d.issues.length, 0);
  assert.equal(d.summary, "요약");
  assert.deepEqual(d.assumptions, ["가정"]);
  assert.deepEqual(d.warnings, ["주의"]);
  assert.deepEqual(d.modeRows, [modeRow()]);
  assert.equal(dryRun(d).length, 0);
});

test("빈 고도 d는 키 자체를 지운다 — wpDraft 소비 규약과 동일", () => {
  const d = normalizeDraft(draft());
  assert.deepEqual(d.wpRows, [{ n: "5000", e: "0" }]); // d 키 없음
  assert.equal(Object.hasOwn(d.wpRows[0], "d"), false);
});

test("실행 조건의 빈 문자열은 폼 유지 — 키를 담지 않는다", () => {
  const d = normalizeDraft(draft());
  assert.deepEqual(d.runConditions,
    { mach: "0", fuel: "300", tEnd: "200", groundOn: true, launchOn: false });
});

test("숫자·불리언으로 온 칸 값은 문자열로 강제된다 — 표는 문자열 계약이다", () => {
  const d = normalizeDraft(draft({
    modeRows: [modeRow({ speed: 88, lonValue: 200 })],
    wpRows: [{ n: 5000, e: -150, d: 200 }],
  }));
  assert.equal(d.modeRows[0].speed, "88");
  assert.equal(d.modeRows[0].lonValue, "200");
  assert.deepEqual(d.wpRows, [{ n: "5000", e: "-150", d: "200" }]);
});

test("enum 두 칸은 trim해서 저장한다 — 검사만 trim하면 표가 거짓말한다 (리뷰 3)", () => {
  // " alt"를 원본대로 두면: 검사는 통과, 표의 select(정확 일치)는 off 표시,
  // buildModes는 trim해서 alt 실행 — 화면과 실행이 갈린다. " time_ge"는
  // COND_KINDS[" time_ge"]가 undefined라 인자수 검사가 생략돼 dryRun까지 침묵.
  const d = normalizeDraft(draft({
    modeRows: [modeRow({ lonAxis: " alt ", exitKind: " time_ge", exitValue: "" })],
  }));
  assert.equal(d.issues.length, 0);
  assert.equal(d.modeRows[0].lonAxis, "alt");
  assert.equal(d.modeRows[0].exitKind, "time_ge");
  assert.match(dryRun(d).join("\n"), /값이 비어 있음/); // 인자수 검사가 살아 있다
});

test("퇴화 응답 방어 — 행 수 상한을 넘으면 자르고 사유를 남긴다", () => {
  const many = Array.from({ length: 60 }, (_, i) => modeRow({ name: `m${i}` }));
  const wps = Array.from({ length: 250 }, (_, i) => ({ n: String(i), e: "0", d: "" }));
  const d = normalizeDraft(draft({ modeRows: many, wpRows: wps }));
  assert.equal(d.modeRows.length, 50);
  assert.equal(d.wpRows.length, 200);
  assert.ok(d.issues.some((m) => /모드가 60행.*50행만/.test(m)));
  assert.ok(d.issues.some((m) => /웨이포인트가 250개.*200개만/.test(m)));
});

test("모르는 종방향 축은 off로 두고 사유를 남긴다 — 조용한 폐기 금지", () => {
  const d = normalizeDraft(draft({ modeRows: [modeRow({ lonAxis: "vs" })] }));
  assert.equal(d.modeRows[0].lonAxis, "");
  assert.match(d.issues[0], /모르는 종방향 축/);
  assert.match(d.issues[0], /"vs"/);
});

test("모르는 이탈 조건은 always로 두고 사유를 남긴다", () => {
  const d = normalizeDraft(draft({
    modeRows: [modeRow({ exitKind: "touchdown", exitValue: "3" })],
  }));
  assert.equal(d.modeRows[0].exitKind, "always");
  assert.equal(d.modeRows[0].exitValue, ""); // always는 인자가 없다 — 남기면 쓰이는 척한다
  assert.match(d.issues[0], /모르는 이탈 조건/);
});

test("객체가 아닌 초안·빈 모드는 이슈로 말한다", () => {
  assert.match(normalizeDraft(null).issues[0], /객체가 아니다/);
  assert.match(normalizeDraft("x").issues[0], /객체가 아니다/);
  assert.match(normalizeDraft(draft({ modeRows: [] })).issues[0], /모드 행이 없다/);
});

test("실행 조건의 불리언 아닌 토글·모르는 칸은 무시하되 사유를 남긴다", () => {
  const d = normalizeDraft(draft({
    runConditions: { mach: "0", alt: "", fuel: "", groundOn: "yes",
                     launchOn: true, tEnd: "", accept: "", seed: "7" },
  }));
  assert.equal(Object.hasOwn(d.runConditions, "groundOn"), false);
  assert.equal(d.runConditions.launchOn, true);
  assert.ok(d.issues.some((m) => /groundOn/.test(m)));
  assert.ok(d.issues.some((m) => /모르는 칸.*seed/.test(m)));
});

test("dryRun은 검증 정본의 거부 메시지를 그대로 모은다", () => {
  // time_ge인데 인자 없음 → buildModes가 던지는 바로 그 문장
  const d = normalizeDraft(draft({
    modeRows: [modeRow({ exitKind: "time_ge", exitValue: "" })],
  }));
  assert.match(dryRun(d).join("\n"), /값이 비어 있음/);
  // 고도 섞임 → buildWaypoints의 행 번호 짚는 문장
  const mixed = normalizeDraft(draft({
    wpRows: [{ n: "1", e: "1", d: "100" }, { n: "2", e: "2", d: "" }],
  }));
  assert.match(dryRun(mixed).join("\n"), /전부 채우거나 전부 비워야/);
});

test("dryRun은 path 모드와 웨이포인트의 공존도 본다 — 실행 시 422 예고", () => {
  const d = normalizeDraft(draft({ wpRows: [] }));
  assert.match(dryRun(d).join("\n"), /웨이포인트가 없다/);
  // 세로 프로파일 쪽 "path"(lonAxis alt + lonValue "path")도 같은 422 부류다
  const altPath = normalizeDraft(draft({
    modeRows: [modeRow({ heading: "0.1", lonValue: "path", exitKind: "always" })],
    wpRows: [],
  }));
  assert.match(dryRun(altPath).join("\n"), /웨이포인트가 없다/);
  // 반대 방향(웨이포인트만 있고 path 없음)은 거부가 아니다 — 기준선 쓰임이
  // 있어(lib/mission.js pathUsage 머리말) 탭의 wpNotice가 말한다. 여기선 침묵.
  const noPath = normalizeDraft(draft({
    modeRows: [modeRow({ heading: "0.1", exitKind: "always" })],
  }));
  assert.equal(dryRun(noPath).length, 0);
});
