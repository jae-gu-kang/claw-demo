/** lib/aircrafthero.js — 기체 탭 대표 그림이 무엇을 그리고 무엇이라고 말하나. */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { heroEntries, heroFacts, heroPlan, stepIndex, variantNote } from "./aircrafthero.js";
import { effectiveOf } from "./profileform.js";

const EXAMPLE = JSON.parse(readFileSync(
  new URL("../../../engine/claw/profile/examples/delta_demo.json", import.meta.url), "utf8"));
const MANIFEST = { models: [{ name: "shahed136.glb", bytes: 98020 }, { name: "launcher.glb", bytes: 90576 }],
  models_reason: null };
const copy = (patch) => ({ ...structuredClone(EXAMPLE), ...patch });

test("예제는 문서가 가리키는 GLB를 그리고, 도식도 물러날 자리로 함께 만든다", () => {
  const plan = heroPlan(EXAMPLE, MANIFEST);
  assert.equal(plan.model, "shahed136.glb");
  assert.ok(plan.schematic?.positions.length > 0);
  assert.deepEqual(plan.notes, []); // 모델을 그대로 그리면 그림 아래에 할 말이 없다
  assert.match(plan.title, /화면용 형상/);
});

test("표시 모델이 없는 기체는 **예제 모델을 빌리지 않고** 도식을 그리며 그렇다고 말한다", () => {
  const plan = heroPlan(copy({ display: null }), MANIFEST);
  assert.equal(plan.model, null);
  assert.ok(plan.schematic);
  assert.match(plan.notes.join(" "), /표시 모델이 없는 기체/);
  assert.match(plan.title, /도식/);
});

test("파일이 서버 자산에 없으면 도식으로 대신하고 서버 사유를 붙인다", () => {
  const plan = heroPlan(copy({ display: { kind: "model", model: "other.glb" } }),
    { models: MANIFEST.models, models_reason: "이름이 겹쳐 뺀 GLB: other.glb" });
  assert.equal(plan.model, null);
  assert.match(plan.notes.join(" "), /other\.glb.*찾지 못해.*이름이 겹쳐/);
});

test("자산 목록을 못 받았으면 일단 읽어 보게 둔다 — 못 읽으면 뷰어가 사유와 함께 물러난다", () => {
  assert.equal(heroPlan(EXAMPLE, null).model, "shahed136.glb");
});

test("도식을 만들 수 없는 형상이면 사유를 말한다 (던지지 않는다)", () => {
  const plan = heroPlan(copy({ display: null, geometry: { S: 0, cbar: 1, b: 2 } }), MANIFEST);
  assert.equal(plan.schematic, null);
  assert.match(plan.notes[0], /도식을 만들 수 없습니다/);
});

test("사실 줄은 문서 값 그대로다 — 형상·종횡비·질량 범위·타면 배치·발사·착륙", () => {
  const facts = heroFacts(EXAMPLE);
  const g = EXAMPLE.geometry;
  const m = EXAMPLE.mass;
  assert.ok(facts.includes(`익폭 ${g.b.toFixed(2)} m`));
  assert.ok(facts.includes(`기준면적 ${g.S.toFixed(2)} m²`));
  assert.ok(facts.includes(`종횡비 ${((g.b * g.b) / g.S).toFixed(2)}`));
  assert.ok(facts.includes(`질량 ${m.m_empty.toFixed(0)}–${(m.m_empty + m.fuel_max).toFixed(0)} kg`));
  assert.ok(facts.includes("엘레본 4면·러더 1면"));
  assert.equal(facts.some((f) => f.startsWith("레일 발사")), !!EXAMPLE.ground.rail);
  assert.equal(facts.includes("스키드 착륙"), !!EXAMPLE.ground.skid);
  const bare = heroFacts({ ...structuredClone(EXAMPLE), ground: { skid: null, rail: null } });
  assert.ok(!bare.includes("스키드 착륙") && !bare.some((f) => f.startsWith("레일 발사")));
});

test("예제의 EO/IR형은 문서가 가리키는 짐벌 볼 모델을 그린다", () => {
  const doc = effectiveOf(EXAMPLE, "eoir"); // 기체 탭이 쓰는 그 치환 적용(lib/profileform.js)
  const plan = heroPlan(doc, { models: [...MANIFEST.models, { name: "shahed136_eoir.glb", bytes: 160904 }] });
  assert.equal(plan.model, "shahed136_eoir.glb");
});

test("‹ › 순서는 기체마다 기본 형상 다음에 형상 변형이고, 읽을 수 없는 기체는 뺀다", () => {
  const list = [
    { id: "example-delta", name: "예제 델타윙", variants: [{ id: "eoir", name: "EO/IR형" }] },
    { id: "broken", unreadable: true, reason: "손상" },
    { id: "mine", name: "내 기체", variants: [] },
  ];
  assert.deepEqual(heroEntries(list), [
    { id: "example-delta", variant: null, label: "예제 델타윙" },
    { id: "example-delta", variant: "eoir", label: "예제 델타윙 · EO/IR형" },
    { id: "mine", variant: null, label: "내 기체" },
  ]);
  assert.deepEqual(heroEntries(null), []);
});

test("고리는 끝에서 처음으로 돌고, 목록에 없는 칸에서는 앞으로는 첫 칸·뒤로는 끝 칸으로 간다", () => {
  assert.equal(stepIndex(3, 2, +1), 0);
  assert.equal(stepIndex(3, 0, -1), 2);
  assert.equal(stepIndex(3, 1, +1), 2);
  assert.equal(stepIndex(3, -1, +1), 0);
  assert.equal(stepIndex(3, -1, -1), 2);
  assert.equal(stepIndex(0, 0, +1), -1);
});

test("표시 모델만 바꾼 변형은 계산이 기본 형상과 같다고 말하고, 다른 걸 바꾼 변형은 바뀐 절을 이름으로 댄다", () => {
  const lookOnly = { variants: [{ id: "l", name: "도색형", patch: { "/display": { kind: "model", model: "x.glb" } } }] };
  assert.match(variantNote(lookOnly, "l"), /도색형.*표시 모델만.*기본 형상과 같습니다/);
  assert.equal(variantNote(EXAMPLE, null), null);
  // 예제의 EO/IR형은 짐벌 무게만큼 질량·관성도 바꾼다 — 계산이 같다고 말하면 안 된다
  assert.match(variantNote(EXAMPLE, "eoir"), /EO\/IR형.*기본 형상과 다른 것: 표시 모델, 질량·관성$/);
  const heavy = { variants: [{ id: "h", name: "무거운형", patch: { "/mass/m_empty": 900, "/mass/J_full": [], "/display/model": "x.glb" } }] };
  assert.match(variantNote(heavy, "h"), /기본 형상과 다른 것: 질량·관성, 표시 모델$/);
  // 막 추가해 치환이 빈 변형 — 「0개:」로 매달리지 않는다
  assert.match(variantNote({ variants: [{ id: "n", name: "새 변형", patch: {} }] }, "n"), /덮어쓴 항목이 없어 기본 형상과 같습니다/);
});

