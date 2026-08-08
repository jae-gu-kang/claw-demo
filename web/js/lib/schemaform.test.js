// 레지스트리 JSON 스키마 → 폼 필드 변환·입력 파싱 검증 (블록 파라미터 폼의 로직)
import { test } from "node:test";
import assert from "node:assert/strict";

import { parseFieldValue, schemaFields } from "./schemaform.js";

// ParamSet.to_json_schema 출력 형태 그대로 (엔진 paramset.py가 정본)
const SCHEMA = {
  title: "fcl/Autopilot",
  type: "object",
  properties: {
    kp_spd: { description: "속도 비례 게인 [s/m]", default: 0.15, type: "number" },
    phi_max: {
      description: "뱅크 명령 한계 (π/2 미만 — 선회 FF 부호 보전) [rad]",
      default: 0.7, type: "number", minimum: 0.0, maximum: 1.5,
    },
    seed: { description: "난수 시드 [-]", default: 0, type: "integer" },
    angle: { description: "각도(wrap) 모드 [-]", default: false, type: "boolean" },
    kind: { description: "종류 [-]", default: "a", enum: ["a", "b"] },
  },
};

test("schemaFields: 설명에서 단위 분리 + 범위·타입·기본값 전달", () => {
  const fields = schemaFields(SCHEMA);
  assert.deepEqual(fields.map((f) => f.name),
    ["kp_spd", "phi_max", "seed", "angle", "kind"]); // 정의 순서 유지
  const phi = fields.find((f) => f.name === "phi_max");
  assert.equal(phi.unit, "rad");
  assert.equal(phi.desc, "뱅크 명령 한계 (π/2 미만 — 선회 FF 부호 보전)");
  assert.equal(phi.lo, 0.0);
  assert.equal(phi.hi, 1.5);
  assert.equal(phi.default, 0.7);
  assert.equal(phi.type, "number");
  const kp = fields.find((f) => f.name === "kp_spd");
  assert.equal(kp.unit, "s/m");
  assert.equal(kp.lo, null); // 무범위
  assert.equal(fields.find((f) => f.name === "seed").type, "integer");
  assert.equal(fields.find((f) => f.name === "angle").type, "boolean");
  const kind = fields.find((f) => f.name === "kind");
  assert.equal(kind.type, "enum");
  assert.deepEqual(kind.choices, ["a", "b"]);
});

test("schemaFields: properties 없음 → 빈 목록 (파라미터 없는 컴포넌트)", () => {
  assert.deepEqual(schemaFields({ title: "x", type: "object" }), []);
});

test("parseFieldValue: 빈 문자열·badInput 거부 (Number('')===0 함정)", () => {
  const f = { name: "kp", type: "number", lo: null, hi: null };
  assert.ok(parseFieldValue(f, "").error);
  assert.ok(parseFieldValue(f, "  ").error);
  assert.ok(parseFieldValue(f, "abc").error);
  assert.ok(parseFieldValue(f, "1e999").error); // Infinity — 유한성 정책
});

test("parseFieldValue: 범위·정수 검증", () => {
  const phi = { name: "phi_max", type: "number", lo: 0.0, hi: 1.5 };
  assert.equal(parseFieldValue(phi, "0.7").value, 0.7);
  assert.equal(parseFieldValue(phi, "0").value, 0); // 경계 포함
  assert.equal(parseFieldValue(phi, "1.5").value, 1.5);
  assert.ok(parseFieldValue(phi, "-0.1").error);
  assert.ok(parseFieldValue(phi, "1.6").error);
  const seed = { name: "seed", type: "integer", lo: null, hi: null };
  assert.equal(parseFieldValue(seed, "11").value, 11);
  assert.ok(parseFieldValue(seed, "1.5").error); // 정수 아님
});

test("parseFieldValue: enum은 허용값만", () => {
  const kind = { name: "kind", type: "enum", choices: ["a", "b"] };
  assert.equal(parseFieldValue(kind, "b").value, "b");
  assert.ok(parseFieldValue(kind, "c").error);
});
