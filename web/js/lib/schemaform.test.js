// 레지스트리 JSON 스키마 → 폼 필드 변환·입력 파싱 검증 (블록 파라미터 폼의 로직)
import { test } from "node:test";
import assert from "node:assert/strict";

import { BLOCKS } from "./blocks.js";
import { FIELD_GROUPS, groupFields, parseFieldValue, schemaFields } from "./schemaform.js";
import { SUBSYSTEMS } from "../views/subsystems.js";

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

// ── 필드 그룹핑 (서버 스키마는 알파벳 정렬 출력 — 기능 단위로 재배열) ──

const mkFields = (...names) => names.map((name) => ({ name }));

test("groupFields: 스펙 순서로 재배열 + 전 필드 정확히 1회 커버", () => {
  // 서버 정렬 출력 시뮬레이션 — 알파벳 순 입력
  const names = FIELD_GROUPS["fcl/Autopilot"].flatMap(([, ns]) => ns);
  const fields = mkFields(...[...names].sort());
  const groups = groupFields("fcl/Autopilot", fields);
  const out = groups.flatMap((g) => g.fields.map((f) => f.name));
  assert.deepEqual([...out].sort(), [...names].sort()); // 전 필드 보존
  assert.equal(new Set(out).size, out.length); // 중복 없음
  // 첫 그룹이 속도 루프 — kp_spd·ki_spd·tau_spd가 붙어서 나옴
  assert.equal(groups[0].title, "속도 루프");
  assert.deepEqual(groups[0].fields.map((f) => f.name), ["kp_spd", "ki_spd", "tau_spd"]);
});

test("groupFields: 스펙 밖 필드는 '기타'로 (엔진이 파라미터 추가해도 유실 없음)", () => {
  const fields = mkFields("kp", "ki", "k_rate", "washout_tau", "out_lo", "out_hi", "brand_new");
  const groups = groupFields("fcl/ScasAxis", fields);
  const last = groups[groups.length - 1];
  assert.equal(last.title, "기타");
  assert.deepEqual(last.fields.map((f) => f.name), ["brand_new"]);
});

test("groupFields: 스키마에 없는 스펙 이름은 무시, 미지 컴포넌트는 원 순서 단일 그룹", () => {
  // 엔진이 파라미터를 제거해도 폼이 깨지지 않음
  const groups = groupFields("fcl/ScasAxis", mkFields("kp", "ki"));
  assert.deepEqual(groups.map((g) => g.fields.map((f) => f.name)).flat(), ["kp", "ki"]);
  // 그룹 스펙 없는 컴포넌트 — 서버 출력 순서 그대로
  const plain = groupFields("guidance/LOS", mkFields("accept_radius"));
  assert.deepEqual(plain, [{ title: "", fields: [{ name: "accept_radius" }] }]);
});

/** 하위 페이지 스키마도 폼 원천이다 (views/blocks.js loadSubSchema) — 트리 재귀. */
function* subSchemas(node) {
  if (node.schema) yield `${node.schema.category}/${node.schema.name}`;
  for (const child of Object.values(node.children ?? {})) yield* subSchemas(child);
}

test("FIELD_GROUPS 키는 전부 블록 스키마 참조에 실존 (오타 → 조용한 폴백 방지)", () => {
  const refs = new Set([
    ...BLOCKS.filter((b) => b.detail.schema)
      .map((b) => `${b.detail.schema.category}/${b.detail.schema.name}`),
    ...Object.values(SUBSYSTEMS).flatMap((s) => [...subSchemas(s)]),
  ]);
  for (const key of Object.keys(FIELD_GROUPS)) {
    assert.ok(refs.has(key), `FIELD_GROUPS 고아 키: ${key}`);
  }
  // 그룹 내 이름 중복 금지 (한 필드가 두 그룹에 들어가면 중복 렌더)
  for (const [key, spec] of Object.entries(FIELD_GROUPS)) {
    const names = spec.flatMap(([, ns]) => ns);
    assert.equal(new Set(names).size, names.length, `${key} 그룹 간 이름 중복`);
  }
});

// 엔진 PARAM_DEFS 이름 스냅샷 — 엔진 rename 시 여기도 갱신할 것. 한계: 엔진과
// 스냅샷이 함께 낡으면 못 잡음(그 경우 해당 필드는 '기타' 강등 — 유실은 없음).
// FIELD_GROUPS 쪽 오타·독자 드리프트는 즉시 잡는다 (리뷰 S1).
const SCHEMA_NAMES = {
  "fcl/Autopilot": ["kp_spd", "ki_spd", "tau_spd", "kp_alt", "ki_alt", "k_hdot",
    "tau_alt", "kp_hdg", "ki_hdg", "tau_hdg", "theta_lo", "theta_hi",
    "phi_max", "k_pitch_turn", "k_thr_turn"],
  "fcl/ScasAxis": ["kp", "ki", "k_rate", "washout_tau", "out_lo", "out_hi"],
  "fcl/Mixer": ["elevon_lo", "elevon_hi", "rudder_lo", "rudder_hi", "k_diff_thr"],
  "actuator/SecondOrderActuator": ["wn", "zeta", "rate_max", "pos_lo", "pos_hi", "initial"],
  // x_offset·thrust_map은 스키마에 없다 — 죽은 인자와 콜러블이라 의도적 제외
  // (engine claw/plant/prop.py, test_plant_models가 그 목록을 핀한다)
  "propulsion/SingleEngine": ["max_thrust", "z_offset"],
  "propulsion/TwinEngine": ["max_thrust", "y_offset", "z_offset"],
  "nav/ErrorModel": ["pos_std_h", "pos_std_v", "vel_std_h", "vel_std_v",
    "att_std", "psi_std", "rate_std",
    "bias_std_h", "bias_std_v", "bias_tau", "delay_s", "update_hz", "seed"],
};

test("FIELD_GROUPS 필드명은 엔진 스키마 이름 스냅샷에 실존 (오타 → '기타' 강등 방지)", () => {
  for (const [key, spec] of Object.entries(FIELD_GROUPS)) {
    const known = new Set(SCHEMA_NAMES[key] ?? []);
    assert.ok(known.size, `SCHEMA_NAMES에 ${key} 스냅샷 없음`);
    for (const n of spec.flatMap(([, ns]) => ns)) {
      assert.ok(known.has(n), `${key}: 스키마에 없는 필드명 ${n}`);
    }
  }
});
