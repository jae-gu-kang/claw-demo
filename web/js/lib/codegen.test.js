// 설계 형상 → 코드 텍스트(Python·C 헤더) + 검토 자료 생성 검증 (코드 생성 기능의 로직)
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  cLiteral, cMacro, diffParams, genCHeader, genPython, genSnapshotC, genSnapshotPython,
  notesToComment, numDisplay, paramWarnings, pyLiteral, traceRows, UNBOUNDED, wrapItems,
} from "./codegen.js";

// schemaform.schemaFields() 출력 형태 (엔진 ParamDef가 정본)
const FIELDS = [
  { name: "kp_spd", desc: "속도 비례 게인", unit: "s/m", type: "number", default: 0.15,
    lo: null, hi: null, choices: null },
  { name: "phi_max", desc: "뱅크 명령 한계", unit: "rad", type: "number", default: 0.7,
    lo: 0.0, hi: 1.5, choices: null },
  { name: "update_hz", desc: "갱신 주기", unit: "Hz", type: "number", default: 100.0,
    lo: null, hi: null, choices: null },
  { name: "seed", desc: "난수 시드", unit: "-", type: "integer", default: 0,
    lo: null, hi: null, choices: null },
];

const spec = (values, over = {}) => ({
  key: "fcl/Autopilot", pyImport: "claw.fcl", pyClass: "Autopilot",
  varName: "ap", cPrefix: "AP", kind: "object",
  fields: FIELDS, values, desc: "오토파일럿", notes: "", hint: "", applied: true, ...over,
});

const BASE = { kp_spd: 0.15, phi_max: 0.7, update_hz: 100.0, seed: 0 };

test("pyLiteral: number 필드는 정수값이어도 소수점을 붙인다 — Python int/float 혼동 방지", () => {
  assert.equal(pyLiteral(100, "number"), "100.0");
  assert.equal(pyLiteral(0, "integer"), "0");
  assert.equal(pyLiteral(0.15, "number"), "0.15");
});

test("pyLiteral: bool·문자열·배열은 Python 문법으로", () => {
  assert.equal(pyLiteral(true, "boolean"), "True");
  assert.equal(pyLiteral(false, "boolean"), "False");
  assert.equal(pyLiteral("clip", "enum"), '"clip"');
  assert.equal(pyLiteral([1, 2.5], "number"), "[1.0, 2.5]");
});

test("리터럴 왕복 정밀도: 최단 표현이 되읽어도 원값 — 게인이 조용히 달라지면 안 됨", () => {
  for (const v of [0.1, 1 / 3, 1e-7, -0.008, 123456.789]) {
    assert.equal(Number(pyLiteral(v, "number")), v);
    assert.equal(Number(cLiteral(v, "number").replace(/f$/, "")), v);
  }
});

test("cLiteral: 실수는 f 접미사 + 소수점 필수 — `30f`는 C 문법 오류", () => {
  assert.equal(cLiteral(30, "number"), "30.0f");
  assert.equal(cLiteral(0.62, "number"), "0.62f");
  assert.equal(cLiteral(5, "integer"), "5");
  assert.equal(cLiteral(true, "boolean"), "true");
});

test("cMacro: 접두사 + 대문자, 점·하이픈은 밑줄 — 게인명 \"pitch.kp\" 대응", () => {
  assert.equal(cMacro("AP", "kp_spd"), "AP_KP_SPD");
  assert.equal(cMacro("GAIN", "pitch.kp"), "GAIN_PITCH_KP");
});

test("numDisplay: 무제한 센티널(±1e30)은 사람 말로 — 폼과 표에 1e+30 노출 방지", () => {
  assert.equal(numDisplay(UNBOUNDED), "무제한");
  assert.equal(numDisplay(-UNBOUNDED), "−무제한");
  assert.equal(numDisplay(Infinity), "무제한");
  assert.equal(numDisplay(0.7), "0.7");
});

test("diffParams: 기본값과 같은 항목은 제외하고 변경분만 — 형상 관리의 실체", () => {
  const d = diffParams(FIELDS, { ...BASE, kp_spd: 0.3 });
  assert.equal(d.length, 1);
  assert.deepEqual(
    { name: d[0].name, from: d[0].from, to: d[0].to, deltaPct: Math.round(d[0].deltaPct) },
    { name: "kp_spd", from: 0.15, to: 0.3, deltaPct: 100 },
  );
});

test("diffParams: 기준이 0이면 백분율은 null — 0으로 나눠 Infinity가 표에 새지 않게", () => {
  const d = diffParams(FIELDS, { ...BASE, seed: 7 });
  assert.equal(d[0].deltaPct, null);
});

test("paramWarnings: 허용 구간 90% 이상만 한계 근접 — 중앙값은 무경고(경고 피로 방지)", () => {
  const near = paramWarnings(FIELDS, { ...BASE, phi_max: 1.4 });
  assert.ok(near.some((w) => w.name === "phi_max" && w.level === "warn"));
  assert.equal(paramWarnings(FIELDS, { ...BASE, phi_max: 0.75 })
    .filter((w) => w.name === "phi_max" && w.level === "warn").length, 0);
});

test("paramWarnings: 무제한 센티널은 한계 근접이 아니라 표기 안내로", () => {
  const w = paramWarnings(FIELDS, { ...BASE, kp_spd: UNBOUNDED });
  assert.equal(w.filter((x) => x.name === "kp_spd").length, 1);
  assert.equal(w.find((x) => x.name === "kp_spd").level, "info");
});

test("paramWarnings: C 탭은 float32 유효자리 초과만 경고 — 0.1 같은 통상값은 무경고", () => {
  assert.equal(paramWarnings(FIELDS, { ...BASE, kp_spd: 0.1 }, { lang: "c" })
    .filter((w) => w.text.includes("float32")).length, 0);
  assert.ok(paramWarnings(FIELDS, { ...BASE, kp_spd: 0.123456789 }, { lang: "c" })
    .some((w) => w.text.includes("float32")));
});

test("wrapItems: 폭을 넘기면 줄을 나누되 항목을 쪼개지 않는다", () => {
  const out = wrapItems(["aaaa", "bbbb", "cccc"], "  ", 14);
  assert.deepEqual(out, ["  aaaa, bbbb,", "  cccc,"]);
  assert.deepEqual(wrapItems([], "  "), []);
});

test("notesToComment: 태그·엔티티가 코드 주석으로 새지 않고 li는 불릿으로", () => {
  const out = notesToComment("<ul><li>가 &middot; 나</li><li>다 &lt;x&gt;</li></ul><p></p>");
  assert.deepEqual(out, ["- 가 · 나", "- 다 <x>"]);
  assert.equal(notesToComment("").length, 0);
});

test("genPython: 실행 가능한 형태 — import 후 생성자 호출, 값이 그대로 반영", () => {
  const { code } = genPython(spec({ ...BASE, kp_spd: 0.3 }));
  assert.ok(code.includes("from claw.fcl import Autopilot"));
  assert.ok(code.includes("ap = Autopilot("));
  assert.ok(code.includes("kp_spd=0.3,"));
  assert.ok(code.includes("update_hz=100.0,")); // number는 소수점 유지
});

test("genPython: lineOf가 실제 코드 라인과 일치 — 추적성 표가 이 번호를 인용", () => {
  const { code, lineOf } = genPython(spec(BASE));
  const lines = code.split("\n");
  for (const f of FIELDS) {
    assert.ok(lines[lineOf[f.name] - 1].includes(`${f.name}=`), `${f.name} 라인 불일치`);
  }
});

test("genPython: 상세 주석 꺼짐이 기본 — 변경분만 표시하고 설명·단위는 코드에 넣지 않음", () => {
  const plain = genPython(spec({ ...BASE, kp_spd: 0.3 })).code;
  assert.ok(plain.includes("← 기본 0.15"));
  assert.ok(!plain.includes("속도 비례 게인 [s/m]"));
  const verbose = genPython(spec({ ...BASE, kp_spd: 0.3 }), { verbose: true }).code;
  assert.ok(verbose.includes("속도 비례 게인 [s/m]"));
});

test("genPython: dict 종류는 생성자가 아니라 딕셔너리 — 작동기의 실제 주입 경로", () => {
  const { code } = genPython(spec(BASE, {
    key: "actuator/SecondOrderActuator", varName: "actuator_params", kind: "dict",
  }));
  assert.ok(code.includes("actuator_params = {"));
  assert.ok(!code.includes("import"));
  assert.ok(code.includes('"kp_spd": 0.15,'));
});

test("genCHeader: 헤더 가드 + 상수만 — 로직 생성 아님 (02 §1 스코프)", () => {
  const { code, lineOf } = genCHeader(spec(BASE));
  assert.ok(code.includes("#ifndef CLAW_AP_H") && code.includes("#endif /* CLAW_AP_H */"));
  const macros = code.split("\n").filter((l) => l.startsWith("#define ") && !l.includes("CLAW_AP_H"))
    .map((l) => l.split(/\s+/)[1]);
  assert.deepEqual(macros, [...new Set(macros)], "매크로 이름 중복");
  assert.ok(code.split("\n")[lineOf.phi_max - 1].includes("AP_PHI_MAX"));
});

test("genSnapshotPython: 게인 테이블은 엔진 Table 생성자 형태로", () => {
  const tables = { "pitch.kp": { axes: { mach: [0.3, 0.6] }, data: [-2, -1.5], extrapolate: "clip" } };
  const { code, lineOf } = genSnapshotPython([spec(BASE)], tables);
  assert.ok(code.includes("from claw.tables import Table"));
  assert.ok(code.includes('"pitch.kp": Table('));
  assert.ok(code.includes('"mach": ['));
  assert.ok(code.includes("0.3, 0.6,"));
  assert.ok(code.includes("-2.0, -1.5,"));
  assert.ok(code.includes('name="pitch.kp",') && code.includes('extrapolate="clip",'));
  assert.equal(typeof lineOf["gain_tables.pitch.kp"], "number");
});

test("긴 게인 테이블은 줄바꿈되고 값은 손실 없이 보존 — 한 줄로 뭉치면 검토 불가", () => {
  const bp = Array.from({ length: 40 }, (_, i) => Number((0.15 + i * 0.02).toFixed(2)));
  const data = bp.map((m) => -8 / (m * m));
  const { code } = genSnapshotPython([spec(BASE)], {
    "pitch.kp": { axes: { mach: bp }, data, extrapolate: "clip" },
  });
  for (const line of code.split("\n")) assert.ok(line.length <= 100, `과폭 줄: ${line}`);
  // 생성문에서 수치를 되읽어 원본과 일치하는지 (줄바꿈이 값을 자르지 않았는지)
  const block = code.split('"pitch.kp": Table(')[1].split("name=")[0];
  const nums = block.match(/-?\d+\.?\d*(e[+-]?\d+)?/gi).map(Number);
  assert.deepEqual(nums, [...bp, ...data]);
});

test("genSnapshotPython: 미적용 컴포넌트는 기본값 사용 사실이 헤더에 남는다", () => {
  const { code } = genSnapshotPython([spec(BASE, { applied: false })], null);
  assert.ok(code.includes("엔진 기본값 (편집 미적용)"));
  assert.ok(!code.includes("gain_tables = {"));
  assert.ok(code.includes("routes/sim.py::_build")); // 조립은 서버가 정본
});

test("genSnapshotC: 1D 게인만 배열로, 다차원은 건너뛰되 침묵하지 않는다", () => {
  const tables = {
    "pitch.kp": { axes: { mach: [0.3, 0.6] }, data: [-2, -1.5], extrapolate: "clip" },
    "roll.kp": { axes: { mach: [0.3], alt: [0] }, data: [[1]], extrapolate: "clip" },
  };
  const { code } = genSnapshotC([spec(BASE)], tables);
  assert.ok(code.includes("#define GAIN_PITCH_KP_N 2"));
  assert.ok(code.includes("static const float GAIN_PITCH_KP_MACH[GAIN_PITCH_KP_N] = {"));
  assert.ok(code.includes("0.3f, 0.6f,"));
  assert.ok(code.includes("roll.kp: 2차원 테이블"));
});

test("traceRows: 파라미터 → 출처 스키마 → 코드 라인 대응 (산출물 기재용)", () => {
  const s = spec(BASE);
  const { lineOf } = genPython(s);
  const rows = traceRows([s], lineOf);
  const row = rows.find((r) => r.param === "phi_max");
  assert.equal(row.source, "fcl/Autopilot @ claw.fcl.Autopilot");
  assert.equal(row.range, "0 ~ 1.5");
  assert.equal(row.unit, "rad");
  assert.equal(row.line, lineOf.phi_max);
  assert.equal(rows.find((r) => r.param === "seed").unit, ""); // 무차원 "-"는 빈칸
});
