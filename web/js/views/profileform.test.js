/** 기체 문서 절별 폼 — 칸 입력이 **어느 문서의 어느 경로**로 가는가 (06 §8).
 *
 * 폼 서술은 여기서 손으로 적는다 — 이 테스트가 보는 것은 서술이 아니라(그건 엔진 test_profile_form.py)
 * 뷰가 서술을 받아 칸을 세우고, 입력을 기본 문서·형상 변형 치환 중 맞는 쪽에 쓰는지다. 값은 실제 예제
 * 기체 문서를 읽는다. 스텁 DOM은 testdom.js(버블링 없음 — 리스너를 직접 부른다).
 */
import { readFileSync } from "node:fs";
import test from "node:test";
import assert from "node:assert/strict";

import { installDom } from "./testdom.js";

installDom();
const { renderProfileForm } = await import("./profileform.js");

const EXAMPLE = JSON.parse(readFileSync(
  new URL("../../../engine/claw/profile/examples/delta_demo.json", import.meta.url), "utf8"));

const SPEC = {
  sections: [
    { key: "mass", title: "질량·관성", help: "", fields: [
      { kind: "number", path: "/mass/m_empty", label: "공허 질량", unit: "kg" },
      { kind: "mat3", path: "/mass/J_full", label: "관성 행렬 (연료 만재)", unit: "kg·m²", symmetric: true },
    ] },
    { key: "stall", title: "실속", help: "", fields: [
      { kind: "table_mach", path: "/stall/table", label: "실속 받음각", unit: "rad", value_label: "α_stall", extrapolate: ["clip"] },
    ] },
    { key: "structural", title: "구조 한계", help: "", fields: [
      { kind: "number", path: "/structural/q_max", label: "최대 동압", unit: "Pa", nullable: true },
    ] },
    { key: "ground", title: "지상·발사", help: "", fields: [
      { kind: "group", path: "/ground/rail", label: "발사 레일", nullable: true, fields: [
        { kind: "number", path: "/ground/rail/length", label: "레일 길이", unit: "m" },
      ] },
    ] },
    { key: "actuator", title: "작동기", help: "", fields: [
      { kind: "component", path: "/actuator", label: "작동기 형식", category: "actuator", reserved: ["pos_lo", "pos_hi", "initial"] },
    ] },
    { key: "law", title: "제어법칙", help: "", fields: [
      { kind: "choice", path: "/law/template", label: "법칙 템플릿", choices: ["delta_elevon_v1"] },
      { kind: "multichoice", path: "/law/schedule/scheduled", label: "스케줄 적용 자리", choices: ["pitch.kp", "pitch.ki", "roll.kp"] },
    ] },
  ],
  registry: { actuator: ["SecondOrderActuator"] },
  aero_forms: {}, term_inputs: [], term_extra_inputs: [], dispersion_tags: {},
};
const SCHEMA = { properties: {
  wn: { description: "고유진동수 [rad/s]", default: 30, type: "number" },
  zeta: { description: "감쇠비", default: 0.7, type: "number" },
  rate_max: { description: "속도 한계 [rad/s]", default: 10, type: "number" },
  pos_lo: { description: "하한", default: -1e30, type: "number" },
} };

/** 호출측(기체 탭)의 쓰기를 흉내 낸다 — fn을 **그 순간의 문서**에 적용한다. 다시 그리지 않는다(수치 칸 규약). */
function mount(doc, { editVariant = null, readOnly = false } = {}) {
  const commits = [];
  let cur = doc;
  const root = renderProfileForm({
    spec: SPEC, doc, editVariant, example: EXAMPLE, readOnly,
    getSchema: async () => SCHEMA,
    update: (fn, opts = {}) => {
      cur = fn(cur);
      commits.push({ next: cur, opts });
    },
    setEditVariant: () => {},
  });
  return { root, commits };
}

/** 이름표 글을 가진 칸(pf-row·pf-group)의 입력들 */
function inputsOf(root, label) {
  const rows = [...root.find("div")].filter((d) => /\bpf-(row|group)\b/.test(d.className) && d.text.includes(label));
  assert.ok(rows.length, `「${label}」 칸이 없다`);
  return rows.at(-1).find("input");
}
const change = (node, value) => {
  if (value !== undefined) node.value = value;
  node.emit("change", { target: node });
};

test("기본 문서 편집 — 수치 칸은 그 경로로, 대칭 행렬은 마주 보는 칸도 함께", () => {
  const before = EXAMPLE.mass.m_empty;
  const { root, commits } = mount(EXAMPLE);
  change(inputsOf(root, "공허 질량")[0], "900");
  assert.equal(commits.at(-1).next.mass.m_empty, 900);
  assert.equal(EXAMPLE.mass.m_empty, before, "받은 문서를 고치지 않는다");
  const cells = inputsOf(root, "관성 행렬 (연료 만재)");
  assert.equal(cells.length, 9);
  change(cells[2], "-12.5"); // [0][2]
  const J = commits.at(-1).next.mass.J_full;
  assert.equal(J[0][2], -12.5);
  assert.equal(J[2][0], -12.5);
});

test("틀린 입력은 쓰지 않고 칸에 표시한다 · 「없음」은 체크로만 null이 된다", () => {
  const { root, commits } = mount(EXAMPLE);
  const m = inputsOf(root, "공허 질량")[0];
  change(m, "abc");
  assert.equal(commits.length, 0);
  assert.ok(m.className.includes("bad"));
  change(m, "");
  assert.equal(commits.length, 0, "빈 칸은 null이 아니다");
  const [, none] = inputsOf(root, "최대 동압");
  none.checked = false;
  change(none);
  assert.equal(commits.length, 0);
  const doc = JSON.parse(JSON.stringify(EXAMPLE));
  doc.structural.q_max = 50000;
  const again = mount(doc);
  const box = inputsOf(again.root, "최대 동압")[1];
  box.checked = true;
  change(box);
  assert.equal(again.commits.at(-1).next.structural.q_max, null);
});

test("형상 변형 편집 — 값은 치환으로 가고, 덮어쓴 칸은 표시된다", () => {
  const doc = JSON.parse(JSON.stringify(EXAMPLE));
  doc.variants = [{ id: "heavy", name: "무거운", patch: { "/mass/m_empty": 1000 } }];
  const { root, commits } = mount(doc, { editVariant: "heavy" });
  const m = inputsOf(root, "공허 질량")[0];
  assert.equal(m.value, "1000", "보이는 값은 치환을 적용한 값");
  assert.ok(root.text.includes("덮어씀"));
  change(inputsOf(root, "레일 길이")[0], "12");
  const next = commits.at(-1).next;
  assert.equal(next.ground.rail.length, 10, "기본 문서는 그대로");
  assert.deepEqual(next.variants[0].patch, { "/mass/m_empty": 1000, "/ground/rail/length": 12 });
});

test("비어 있던 묶음은 누를 때만 예제 값으로 채운다", () => {
  const doc = JSON.parse(JSON.stringify(EXAMPLE));
  doc.ground.rail = null;
  const { root, commits } = mount(doc);
  assert.ok(root.text.includes("없음"));
  assert.equal(commits.length, 0, "그리기만으로는 채우지 않는다");
  const start = root.find("button").find((b) => b.text === "예제 값으로 시작");
  assert.ok(start, "시작 버튼이 없다");
  const prev = globalThis.confirm;
  globalThis.confirm = () => true;
  try {
    start.emit("click", {});
  } finally {
    globalThis.confirm = prev;
  }
  assert.deepEqual(commits.at(-1).next.ground.rail, EXAMPLE.ground.rail);
});

test("레지스트리 파라미터 칸은 스키마가 오면 서고, 예약 파라미터는 뺀다 · 읽기 전용은 버튼이 없다", async () => {
  const { root, commits } = mount(EXAMPLE);
  await new Promise((r) => setTimeout(r, 0));
  const labels = root.find("label").map((l) => l.text);
  assert.ok(labels.some((t) => t.startsWith("wn")));
  assert.ok(!labels.some((t) => t.startsWith("pos_lo")), "예약 파라미터(위치 한계)는 타면 절 소관");
  const wn = root.find("label").find((l) => l.text.startsWith("wn")).find("input")[0];
  change(wn, "25");
  assert.equal(commits.at(-1).next.actuator.params.wn, 25);

  const ro = mount(EXAMPLE, { readOnly: true });
  assert.equal(ro.root.find("button").filter((b) => b.text === "새 형상 변형").length, 0);
  assert.ok(inputsOf(ro.root, "공허 질량")[0].disabled);
});

test("쓰기는 그 순간의 문서에 적용된다 — 칸을 고친 직후 [행 추가]를 눌러도 방금 친 값이 산다", () => {
  const { root, commits } = mount(EXAMPLE);
  const cells = inputsOf(root, "실속 받음각");
  change(cells[1], "0.5"); // 첫 행 값 — 다시 그리지 않는다
  assert.equal(commits.at(-1).opts.structural, undefined, "수치 칸 쓰기는 다시 그리기를 부르지 않는다");
  const add = root.find("button").find((b) => b.text === "행 추가");
  add.emit("click", {});
  const t = commits.at(-1).next.stall.table;
  assert.equal(commits.at(-1).opts.structural, true);
  assert.equal(t.data[0], 0.5, "방금 친 값이 산다");
  assert.equal(t.axes.mach.length, EXAMPLE.stall.table.axes.mach.length + 1);
});

test("다시 그리지 않으므로 대칭 칸과 「덮어씀」은 그 자리에서 고친다", () => {
  const { root } = mount(EXAMPLE);
  const cells = inputsOf(root, "관성 행렬 (연료 만재)");
  change(cells[1], "3.25"); // [0][1]
  assert.equal(cells[3].value, "3.25", "마주 보는 [1][0] 칸");

  const doc = JSON.parse(JSON.stringify(EXAMPLE));
  doc.variants = [{ id: "heavy", name: "무거운", patch: {} }];
  const v = mount(doc, { editVariant: "heavy" });
  const railRow = [...v.root.find("div")].filter((d) => /\bpf-row\b/.test(d.className) && d.text.includes("레일 길이")).at(-1);
  assert.ok(!railRow.className.includes("ov"));
  change(railRow.find("input")[0], "12");
  assert.ok(railRow.className.includes("ov"));
  assert.ok(railRow.text.includes("덮어씀"));
});

test("[해제]는 그 치환만 지운다", () => {
  const doc = JSON.parse(JSON.stringify(EXAMPLE));
  doc.variants = [{ id: "heavy", name: "무거운", patch: { "/mass/m_empty": 1000, "/structural/q_max": 5e4 } }];
  const { root, commits } = mount(doc, { editVariant: "heavy" });
  const release = root.find("button").filter((b) => b.text === "해제");
  assert.equal(release.length, 2);
  release[0].emit("click", {});
  assert.deepEqual(commits.at(-1).next.variants[0].patch, { "/structural/q_max": 5e4 });
  assert.equal(commits.at(-1).opts.structural, true);
});

test("선택지 밖 값은 그대로 보이고, 여러 선택은 순서·목록 밖 이름을 지킨다", () => {
  const doc = JSON.parse(JSON.stringify(EXAMPLE));
  doc.law.template = "old_template";
  doc.law.schedule.scheduled = ["roll.kp", "pitch.kp", "yaw.zz"];
  const { root, commits } = mount(doc);
  assert.ok(root.text.includes("old_template (허용 목록 밖"), "첫 선택지를 고른 척하지 않는다");
  const box = root.find("label").find((l) => l.text.trim() === "pitch.ki").find("input")[0];
  box.checked = true;
  change(box);
  assert.deepEqual(commits.at(-1).next.law.schedule.scheduled, ["roll.kp", "pitch.kp", "yaw.zz", "pitch.ki"]);
});

test("문서에서 빠진 레지스트리 파라미터도 칸에서 채운다 · 없는 경로는 칸이 말한다", async () => {
  const doc = JSON.parse(JSON.stringify(EXAMPLE));
  delete doc.actuator.params.zeta;
  const { root, commits } = mount(doc);
  await new Promise((r) => setTimeout(r, 0));
  const zeta = root.find("label").find((l) => l.text.startsWith("zeta")).find("input")[0];
  change(zeta, "0.8");
  assert.equal(commits.at(-1).next.actuator.params.zeta, 0.8);

  const broken = JSON.parse(JSON.stringify(EXAMPLE));
  delete broken.mass.m_empty; // JSON 글로 지운 칸
  assert.ok(mount(broken).root.text.includes("문서에 없는 경로: /mass/m_empty"));
});

test("받아들인 값은 오류 표시를 지운다 — 다시 그리지 않으므로 칸이 스스로", () => {
  const { root, commits } = mount(EXAMPLE);
  const m = inputsOf(root, "공허 질량")[0];
  change(m, "abc");
  assert.ok(m.className.includes("bad"));
  change(m, "850");
  assert.ok(!m.className.includes("bad"));
  assert.equal(m.title, "");
  assert.equal(commits.at(-1).next.mass.m_empty, 850);
});

test("칸 줄은 경로 표식을 단다 — 모양이 바뀐 뒤 포커스를 같은 줄로 되돌리는 자리", () => {
  const { root } = mount(EXAMPLE);
  const paths = root.find("div").map((d) => d.getAttribute("data-pf-path")).filter(Boolean);
  for (const p of ["/mass/m_empty", "/mass/J_full", "/stall/table", "/ground/rail", "/ground/rail/length"]) {
    assert.ok(paths.includes(p), `${p} 줄에 표식이 없다`);
  }
});
