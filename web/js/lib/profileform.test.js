// 기체 문서 폼의 판단 — 포인터·형상 변형 덮어쓰기·칸 해석 (node --test, 의존 0)
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  FormNotice, aeroTableFromParsed, sliceBody, stallNote, tableSummary,
  allowedInputs, applyPatch, clearInPatch, effectiveOf, flattenFields, formatNum, formUpdate, getAt, inputsText, isUnder, writeValues,
  machTableFromParsed, paramsFromDefaults, parseInputs, parseNum, parseNumList, parsePointer,
  patchOwner, patchedBelow, sectionOverrides, setAt, setInPatch, setMatrixCell, tableFromRows,
  tableRows, toPointer,
} from "./profileform.js";

const DOC = {
  schema_version: 1, id: "a", is_example: false,
  mass: { m_empty: 800, J_full: [[1, 0, 0], [0, 2, 0], [0, 0, 3]] },
  structural: { q_max: null },
  "we/ird": { "t~x": 1 },
  variants: [{ id: "v", name: "v", patch: {} }],
};

test("포인터 — 이스케이프 왕복, 없는 경로는 undefined, null은 값", () => {
  assert.deepEqual(parsePointer("/we~1ird/t~0x"), ["we/ird", "t~x"]);
  assert.equal(toPointer(["we/ird", "t~x"]), "/we~1ird/t~0x");
  assert.equal(getAt(DOC, "/we~1ird/t~0x"), 1);
  assert.equal(getAt(DOC, "/mass/J_full/1/1"), 2);
  assert.equal(getAt(DOC, "/structural/q_max"), null);
  assert.equal(getAt(DOC, "/mass/nope"), undefined);
  assert.equal(getAt(DOC, "/mass/J_full/01/0"), undefined, "앞자리 0 인덱스는 인덱스가 아니다");
  assert.throws(() => parsePointer("mass"));
});

test("setAt — 새 문서를 돌려주고, 없는 경로는 거부한다 (엔진 patch 규칙)", () => {
  const out = setAt(DOC, "/mass/m_empty", 900);
  assert.equal(out.mass.m_empty, 900);
  assert.equal(DOC.mass.m_empty, 800, "원본 불변");
  assert.throws(() => setAt(DOC, "/mass/m_typo", 1), /없는 경로/);
  assert.throws(() => setAt(DOC, "/mass/J_full/3/0", 1), /없는 경로/);
});

test("isUnder는 토큰 단위다", () => {
  assert.ok(isUnder("/mass/m_empty", "/mass"));
  assert.ok(isUnder("/mass", "/mass"));
  assert.ok(!isUnder("/mass/m_empty", "/mass/m"));
  assert.ok(!isUnder("/mass", "/mass/m_empty"));
});

test("형상 변형 — 적용 순서·금지 항목·없는 경로를 엔진처럼 다룬다", () => {
  const patch = { "/mass": { m_empty: 1, J_full: [[9, 0, 0], [0, 9, 0], [0, 0, 9]] }, "/mass/m_empty": 5, "/id": "x", "/nope": 1 };
  const { doc, issues } = applyPatch(DOC, patch);
  assert.equal(doc.mass.m_empty, 5, "뒤에 끼운 하위 치환이 이긴다");
  assert.equal(doc.id, "a");
  assert.equal("variants" in doc, false);
  assert.equal(issues.length, 2);
});

test("형상 변형 편집 — 덮어쓴 주인 경로 안을 고치고, 하위 부분 치환은 녹여 없앤다", () => {
  assert.equal(patchOwner({ "/mass": {} }, "/mass/m_empty"), "/mass");
  assert.equal(patchOwner({ "/mass": {}, "/mass/m_empty": 1 }, "/mass/m_empty"), "/mass/m_empty");
  assert.equal(patchOwner({ "/structural/q_max": 1 }, "/mass/m_empty"), null);
  assert.deepEqual(patchedBelow({ "/mass": {}, "/mass/J_full/0/0": 2 }, "/mass"), ["/mass/J_full/0/0"]);
  assert.deepEqual(patchedBelow({ "/mass/J_full/0/0": 2, "/mass": {} }, "/mass"), [], "상위 앞에 끼운 하위는 가려졌다");

  let p = setInPatch({}, "/mass/m_empty", 900);
  assert.deepEqual(p, { "/mass/m_empty": 900 });
  // 상위가 통째로 덮어썼으면 그 값 안을 고친다 — 하위 키를 새로 만들지 않는다
  p = setInPatch({ "/mass": { m_empty: 1, J_full: DOC.mass.J_full } }, "/mass/m_empty", 2);
  assert.deepEqual(Object.keys(p), ["/mass"]);
  assert.equal(p["/mass"].m_empty, 2);
  // 행렬 전체를 새로 쓰면 그 안의 칸 치환은 사라진다(값에 녹았다)
  p = setInPatch({ "/mass/J_full/0/0": 7 }, "/mass/J_full", [[7, 0, 0], [0, 2, 0], [0, 0, 3]]);
  assert.deepEqual(Object.keys(p), ["/mass/J_full"]);
  assert.deepEqual(clearInPatch(p, "/mass/J_full"), {});
  // null(없음)도 치환 값이다
  assert.deepEqual(setInPatch({}, "/structural/q_max", null), { "/structural/q_max": null });
});

test("치환 순서 — 뒤에 끼운 상위가 이긴다: 그 값 안을 고쳐야 칸에 보인다 (엔진 적용 순서)", () => {
  // JSON 글·가져오기로 생길 수 있는 순서 — 검증기도 받는다
  const patch = { "/mass/m_empty": 5, "/mass": { m_empty: 1, J_full: DOC.mass.J_full } };
  assert.equal(applyPatch(DOC, patch).doc.mass.m_empty, 1);
  assert.equal(patchOwner(patch, "/mass/m_empty"), "/mass");
  const next = setInPatch(patch, "/mass/m_empty", 999);
  assert.deepEqual(Object.keys(next), ["/mass"], "가려진 하위 치환은 지운다");
  assert.equal(applyPatch(DOC, next).doc.mass.m_empty, 999, "고친 값이 실제로 보인다");
  // 반대 순서 — 자기 자리가 뒤에 있으면 자리를 지키며 값만 바꾼다
  const ordered = setInPatch({ "/mass": { m_empty: 1, J_full: DOC.mass.J_full }, "/mass/m_empty": 5 }, "/mass/m_empty", 7);
  assert.deepEqual(Object.keys(ordered), ["/mass", "/mass/m_empty"]);
  assert.equal(applyPatch(DOC, ordered).doc.mass.m_empty, 7);
});

test("칸 해석 — 빈 칸·비유한값은 오류, 목록은 쉼표·공백", () => {
  assert.deepEqual(parseNum(" 1.5e3 "), { value: 1500 });
  assert.ok(parseNum("").error);
  assert.ok(parseNum("inf").error);
  assert.ok(parseNum("NaN").error);
  assert.deepEqual(parseNumList("0.1, 0.2  0.3"), { value: [0.1, 0.2, 0.3] });
  assert.ok(parseNumList("0.1, x").error);
  assert.ok(parseNumList(" ").error);
  assert.equal(formatNum(null), "");
  assert.equal(formatNum(0.30000000000000004), "0.30000000000000004", "반올림하지 않는다");
});

test("행렬·표·항·레지스트리 기본값", () => {
  const m = setMatrixCell(DOC.mass.J_full, 0, 2, -0.5, { symmetric: true });
  assert.equal(m[0][2], -0.5);
  assert.equal(m[2][0], -0.5);
  assert.equal(DOC.mass.J_full[0][2], 0);
  assert.equal(setMatrixCell(DOC.mass.J_full, 0, 2, 4)[2][0], 0);

  const t = { axes: { mach: [0.1, 0.5] }, data: [0.4, 0.33], extrapolate: "clip" };
  assert.deepEqual(tableFromRows(tableRows(t), "clip"), t);
  assert.deepEqual(machTableFromParsed({ axes: { mach: [0.1] }, data: [1] }, "clip").value,
    { axes: { mach: [0.1] }, data: [1], extrapolate: "clip" });
  assert.match(machTableFromParsed({ axes: { alt: [1] }, data: [1] }, "clip").error, /마하 1축/);

  assert.equal(inputsText(["alpha", "qhat"]), "alpha, qhat");
  assert.deepEqual(parseInputs("alpha * qhat, de"), ["alpha", "qhat", "de"]);
  const spec = { term_inputs: ["alpha", "de"], term_extra_inputs: [{ form: "lift_drag", coef: "CD", inputs: ["CL"] }] };
  assert.deepEqual(allowedInputs(spec, "lift_drag", "CD"), ["alpha", "de", "CL"]);
  assert.deepEqual(allowedInputs(spec, "body", "CD"), ["alpha", "de"]);

  assert.deepEqual(paramsFromDefaults([{ name: "wn", default: 30 }, { name: "pos_lo", default: -1 }], ["pos_lo"]), { wn: 30 });
});

test("절 서술 평탄화와 절별 덮어쓰기 수", () => {
  const fields = [{ kind: "number", path: "/a/x" }, { kind: "group", path: "/a/g", fields: [{ kind: "number", path: "/a/g/y" }] }];
  assert.deepEqual(flattenFields(fields).map((f) => f.path), ["/a/x", "/a/g", "/a/g/y"]);
  assert.deepEqual(sectionOverrides({ "/mass/m_empty": 1, "/massive": 2, "/structural/q_max": null }, { key: "mass" }), ["/mass/m_empty"]);
});

test("상위 치환 뒤에 끼운 하위 치환이 고친 칸을 다시 덮지 않게 지운다", () => {
  const J = [[1, 0, 0], [0, 2, 0], [0, 0, 3]];
  const patch = { "/mass": { m_empty: 1, J_full: J }, "/mass/J_full/0/0": 7, "/mass/J_full/1/1": 9 };
  // 폼의 행렬 칸은 행렬 전체를 쓴다 — 주인은 상위 /mass, 그 뒤의 칸 치환들이 이 값을 다시 덮던 자리
  const shownJ = applyPatch(DOC, patch).doc.mass.J_full;
  assert.deepEqual(shownJ, [[7, 0, 0], [0, 9, 0], [0, 0, 3]]);
  const written = shownJ.map((r, i) => r.map((c, j) => (i === 0 && j === 0 ? 123 : c)));
  const next = setInPatch(patch, "/mass/J_full", written);
  assert.deepEqual(Object.keys(next), ["/mass"], "뒤에 끼운 칸 치환은 이 값에 녹았다");
  assert.equal(applyPatch(DOC, next).doc.mass.J_full[0][0], 123, "고친 값이 보인다");
  assert.equal(applyPatch(DOC, next).doc.mass.J_full[1][1], 9, "보이던 다른 칸 값도 그대로");
  // 다른 칸(형제)의 뒤 치환은 산다
  const sibling = setInPatch({ "/mass": { m_empty: 1, J_full: J }, "/mass/J_full/1/1": 9 }, "/mass/m_empty", 5);
  assert.deepEqual(Object.keys(sibling), ["/mass", "/mass/J_full/1/1"]);
  assert.equal(applyPatch(DOC, sibling).doc.mass.m_empty, 5);
  assert.equal(applyPatch(DOC, sibling).doc.mass.J_full[1][1], 9);
});

test("편집 대상 쓰기 — 기본 문서는 그 자리에, 형상 변형은 치환으로, 사라진 변형은 사유", () => {
  const doc = { ...JSON.parse(JSON.stringify(DOC)), variants: [{ id: "v", name: "v", patch: { "/mass/m_empty": 900 } }] };
  assert.equal(effectiveOf(doc, "v").mass.m_empty, 900);
  assert.equal(effectiveOf(doc, null).mass.m_empty, 800);
  assert.equal(writeValues(doc, null, [["/mass/m_empty", 1]]).mass.m_empty, 1);
  const w = writeValues(doc, "v", [["/structural/q_max", 5], ["/mass/m_empty", 950]]);
  assert.deepEqual(w.variants[0].patch, { "/mass/m_empty": 950, "/structural/q_max": 5 });
  assert.equal(w.mass.m_empty, 800);
  assert.throws(() => writeValues(doc, "gone", [["/mass/m_empty", 1]]), /형상 변형이 문서에 없습니다/);
});

test("폼 쓰기 판단 — 그 순간의 문서에 적용, 다른 기록·JSON 글이면 거절, 못 쓰면 사유", () => {
  const rec = { mode: "form", obj: { a: 1 } };
  const ok = formUpdate({ state: rec, owner: rec, fn: (cur) => ({ ...cur, b: cur.a + 1 }) });
  assert.deepEqual(ok.obj, { a: 1, b: 2 });
  assert.equal(ok.text, JSON.stringify({ a: 1, b: 2 }, null, 1));
  assert.ok(formUpdate({ state: { mode: "form", obj: {} }, owner: rec, fn: (c) => c, async: true }).reject.includes("다른 기체"));
  assert.ok(formUpdate({ state: { ...rec, mode: "json" }, owner: rec, fn: (c) => c }).reject);
  assert.match(formUpdate({ state: rec, owner: rec, fn: () => { throw new Error("문서에 없는 경로: /x"); } }).error, /없는 경로/);
});

test("공력 표 항 — 요약·CSV 응답 변환·허용 축", () => {
  assert.equal(tableSummary(1.5), null);
  assert.equal(tableSummary({ table: { axes: { alpha: [0, 1, 2], mach: [0.1, 0.9] }, data: [], extrapolate: "clip" } }),
    "표 alpha×mach · 3×2칸 · clip");
  const parsed = { axes: { alpha: [0, 1], mach: [0.1, 0.5] }, data: [[1, 2], [3, 4]], extrapolate: "linear" };
  assert.deepEqual(aeroTableFromParsed(parsed, ["alpha", "mach"]).value,
    { table: { axes: parsed.axes, data: parsed.data, extrapolate: "linear" } });
  assert.match(aeroTableFromParsed({ axes: { qhat: [0, 1] }, data: [1, 2] }, ["alpha"]).error, /qhat/);
  assert.match(aeroTableFromParsed({ axes: {} }, ["alpha"]).error, /축이 없습니다/);
});

test("뷰어 본문 — 따라가는 축은 고정값에서 빠지고, 틀린 칸은 모아서 말한다", () => {
  const axes = ["alpha", "mach", "alt"];
  const ok = sliceBody({ along: "alpha", start: "-0.1", stop: "0.5", n: "61", fixed: { alpha: "x", mach: "0.4", alt: "1000" } }, axes);
  assert.deepEqual(ok.value, { along: "alpha", start: -0.1, stop: 0.5, n: 61, fixed: { mach: 0.4, alt: 1000 } });
  assert.match(sliceBody({ along: "mach", start: "0.5", stop: "0.1", n: "5", fixed: { alpha: "0", alt: "0" } }, axes).error, /시작 < 끝/);
  const bad = sliceBody({ along: "alpha", start: "", stop: "1", n: "2.5", fixed: { mach: "a", alt: "0" } }, axes).error;
  assert.match(bad, /시작/);
  assert.match(bad, /mach/);
});

test("실속 대조 한 줄 — 추출이 없으면 사유, 있으면 차이", () => {
  assert.match(stallNote({ along: "alpha", fixed: { mach: 0.4 }, stall: { table_at: 0.3, extracted: null, reason: "꺾이지 않는다" } }), /꺾이지 않는다/);
  assert.match(stallNote({ along: "alpha", fixed: { mach: 0.4 }, stall: { table_at: 0.3, extracted: 0.28, delta: -0.02 } }), /차이 -0\.0200 rad/);
  assert.equal(stallNote({ along: "beta", stall: {} }), "");
});

test("실속 대조 한 줄 — 추출 구간(표 α 격자·DB 유효 범위)을 함께 적는다", () => {
  const note = stallNote({ along: "alpha", fixed: { mach: 0.4 },
    stall: { table_at: 0.3, extracted: null, reason: "없다", window: [-0.2, 0.4] } });
  assert.match(note, /추출 구간 α \[-0\.2, 0\.4\]/);
  assert.match(stallNote({ along: "alpha", fixed: { mach: 0.4 },
    stall: { table_at: 0.3, extracted: null, reason: "없다", window: [null, 0.4] } }), /\[−∞, 0\.4\]/);
  assert.doesNotMatch(stallNote({ along: "alpha", fixed: { mach: 0.4 },
    stall: { table_at: 0.3, extracted: null, reason: "없다", window: [null, null] } }), /추출 구간/);
});

test("쓰기 안내(FormNotice)는 문서 모양 오류 문구 없이 사유 그대로 낸다", () => {
  const state = { mode: "form", obj: { a: 1 } };
  const notice = formUpdate({ state, owner: state, fn: () => { throw new FormNotice("넣지 않았습니다"); } });
  assert.deepEqual(notice, { error: "넣지 않았습니다" });
  const broken = formUpdate({ state, owner: state, fn: () => { throw new Error("x"); } });
  assert.match(broken.error, /JSON 글에서 문서 모양을 확인하세요/);
});

// ── 필수·선택 표시 (v1.13) ─────────────────────────────────────────────────

import { isRequired, requirementCounts } from "./profileform.js";

test("필수는 nullable이 아닌 칸이다 — 서술이 정본", () => {
  assert.equal(isRequired({ kind: "number", path: "/mass/m_empty" }), true);
  assert.equal(isRequired({ kind: "number", path: "/structural/q_max", nullable: true }), false);
  assert.equal(isRequired({ kind: "number", nullable: false }), true);
});

test("절의 필수·선택 수 — 선택 묶음은 하나로 세고 안의 칸은 세지 않는다", () => {
  const fields = [
    { kind: "number", path: "/a" },
    { kind: "number", path: "/b", nullable: true },
    { kind: "group", path: "/rail", nullable: true, fields: [{ kind: "number", path: "/rail/length" }] },
    { kind: "group", path: "/must", fields: [
      { kind: "number", path: "/must/x" }, { kind: "range", path: "/must/r", nullable: true },
    ] },
  ];
  assert.deepEqual(requirementCounts(fields), { required: 2, optional: 3 });
  assert.deepEqual(requirementCounts([]), { required: 0, optional: 0 });
  assert.deepEqual(requirementCounts(undefined), { required: 0, optional: 0 });
});

test("정적 안정성 본문 — α는 따라가는 축이라 고정값에서 빠지고, 틀린 칸은 모아서 말한다", async () => {
  const { stabilityBody } = await import("./profileform.js");
  const axes = ["alpha", "beta", "mach", "alt"];
  const ok = stabilityBody({ start: "-0.1", stop: "0.4", n: "41", fixed: { alpha: "x", beta: "0", mach: "0.4", alt: "0" } }, axes);
  assert.deepEqual(ok.value, { start: -0.1, stop: 0.4, n: 41, fixed: { beta: 0, mach: 0.4, alt: 0 } });
  assert.match(stabilityBody({ start: "0.5", stop: "0.1", n: "5", fixed: { beta: "0", mach: "0.4", alt: "0" } }, axes).error, /시작 < 끝/);
  const bad = stabilityBody({ start: "", stop: "1", n: "2.5", fixed: { beta: "0", mach: "a", alt: "0" } }, axes).error;
  assert.match(bad, /시작/);
  assert.match(bad, /mach/);
});

test("정적 안정성 판정 한 줄 — 전 구간 안정 / 위반 구간 나열", async () => {
  const { stabilityVerdictText } = await import("./profileform.js");
  assert.match(stabilityVerdictText({ stable_sign: "-", all_ok: true, violations: [] }),
    /안정 부호 −.*전 구간 안정/);
  const t = stabilityVerdictText({ stable_sign: "+", all_ok: false, violations: [[0.2, 0.4]] });
  assert.match(t, /안정 부호 \+/);
  assert.match(t, /α \[0\.2000, 0\.4000\] rad/);
  // 구간이 여럿이면 전부 — 하나만 보이면 나머지 위반이 숨는다
  assert.match(stabilityVerdictText({ stable_sign: "-", all_ok: false, violations: [[-0.1, -0.05], [0.3, 0.3]] }),
    /α \[-0\.1000, -0\.0500\] rad.*α \[0\.3000, 0\.3000\] rad/);
});

test("L/D — CD ≤ 0인 점은 null (나누기 위조 금지), 통계는 유한값에서만", async () => {
  const { aeroCurveStats, liftDragRatio } = await import("./profileform.js");
  assert.deepEqual(liftDragRatio([0.2, 0.4, 0.6], [0.02, 0.0, 0.03]), [10, null, 20]);
  const res = {
    along: "alpha", x: [0.0, 0.1, 0.2],
    coefficients: { CL: [0.2, 0.4, 0.6], CD: [0.03, 0.02, 0.04] },
  };
  const s = aeroCurveStats(res);
  assert.deepEqual(s.clMax, { v: 0.6, x: 0.2 });
  assert.deepEqual(s.cdMin, { v: 0.02, x: 0.1 });
  assert.deepEqual(s.ldMax, { v: 20, x: 0.1 });
  assert.deepEqual(s.ld, [0.2 / 0.03, 20, 15]);
  // CD가 전부 0 이하이면 통계가 없다 — 지어내지 않는다
  const none = aeroCurveStats({ along: "alpha", x: [0], coefficients: { CL: [1], CD: [0] } });
  assert.equal(none.ldMax, null);
  assert.equal(none.cdMin, null);
});

test("곡선 통계는 DB 유효 범위(α) 밖(외삽 구간)을 보지 않는다 — 실속 추출과 같은 창", async () => {
  const { aeroCurveStats } = await import("./profileform.js");
  const res = {
    along: "alpha", x: [0.0, 0.1, 0.2],
    coefficients: { CL: [0.2, 0.4, 0.6], CD: [0.03, 0.02, 0.01] },
    db_ranges: { alpha: [0.0, 0.15] }, // 0.2는 외삽 — clip 평탄값이 「최대」로 찍히는 자리
  };
  const s = aeroCurveStats(res);
  assert.deepEqual(s.clMax, { v: 0.4, x: 0.1 });
  assert.deepEqual(s.ldMax, { v: 20, x: 0.1 });
  assert.equal(s.ld.length, 3); // 곡선 자체는 전 구간 — 창은 극값 통계만 제한한다
});

test("겹치기 값 파싱 — 빈 칸은 겹치기 없음, 개수 상한, 수치 오류는 사유", async () => {
  const { overlayValues } = await import("./profileform.js");
  assert.equal(overlayValues("").value, null);
  assert.equal(overlayValues("  ").value, null);
  assert.deepEqual(overlayValues("0.1, 0.3 0.5").value, [0.1, 0.3, 0.5]);
  assert.match(overlayValues("0.1, x").error, /수치가 아님/);
  assert.match(overlayValues("1,2,3,4,5,6,7").error, /6개까지/);
});
