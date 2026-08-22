// 블록 → 코드 생성 스펙 조립 (스키마 캐시·엔진 검증 실패 시 심볼 폴백·메타)
import { test } from "node:test";
import assert from "node:assert/strict";

import { makeMetaSource, makeSpecBuilder } from "./specs.js";

const BLOCK = {
  detail: {
    schema: { category: "fcl", name: "Autopilot" },
    codegen: { varName: "ap", cPrefix: "AP", kind: "component", hint: "힌트" },
    desc: "오토파일럿",
    omit: ["숨김"],
  },
};

// schemaform.schemaFields()의 자리 — 여기서는 스키마를 그대로 필드로 본다
const asFields = (schema) => schema.fields;
const SCHEMA = {
  fields: [
    { name: "kp_alt", default: 0.004 },
    { name: "숨김", default: 1 },
  ],
};

function io({ post } = {}) {
  const calls = [];
  return {
    calls,
    get: async (p) => { calls.push(["get", p]); return SCHEMA; },
    post: async (p, b) => {
      calls.push(["post", p, b]);
      return post ? post(b) : { py_import: "claw.fcl", py_class: "Autopilot" };
    },
    errorText: (e) => e.message,
  };
}

test("기본값 형상 — values=null이면 스키마 기본값, applied=false", async () => {
  const net = io();
  const build = makeSpecBuilder(net);
  const { spec, validation } = await build(BLOCK, null, asFields);
  assert.equal(spec.applied, false);
  assert.deepEqual(spec.values, { kp_alt: 0.004 }); // omit된 필드는 빠진다
  assert.deepEqual(spec.fields.map((f) => f.name), ["kp_alt"]);
  assert.equal(validation.ok, true);
});

test("파이썬 심볼은 엔진 회신을 그대로 싣는다 — 추측 금지", async () => {
  const net = io({ post: () => ({ py_import: "claw.nav", py_class: "NavErrorModel" }) });
  const { spec } = await makeSpecBuilder(net)(BLOCK, null, asFields);
  assert.equal(spec.pyImport, "claw.nav");
  assert.equal(spec.pyClass, "NavErrorModel");
});

test("스키마는 한 번만 조회한다 — 캐시 공유", async () => {
  const net = io();
  const cache = {};
  const build = makeSpecBuilder(net, { cache });
  await build(BLOCK, null, asFields);
  await build(BLOCK, { kp_alt: 1 }, asFields);
  assert.equal(net.calls.filter((c) => c[0] === "get").length, 1);
});

test("검증 실패해도 코드는 나온다 — 심볼을 기본값으로 재조회", async () => {
  let first = true;
  const net = io({
    post: (body) => {
      if (first && Object.keys(body.values).length > 0) {
        first = false;
        throw new Error("theta_lo > theta_hi");
      }
      return { py_import: "claw.fcl", py_class: "Autopilot" };
    },
  });
  const { spec, validation } = await makeSpecBuilder(net)(BLOCK, { kp_alt: 9 }, asFields);
  assert.equal(validation.ok, false);
  assert.match(validation.detail, /theta_lo/);
  assert.equal(spec.pyClass, "Autopilot", "심볼 폴백 실패");
  assert.deepEqual(spec.values, { kp_alt: 9 }, "거부된 값도 그대로 코드에 낸다");
});

test("서버가 아주 죽어도 스펙은 만들어진다", async () => {
  const net = io({ post: () => { throw new Error("연결 안 됨"); } });
  const { spec, validation } = await makeSpecBuilder(net)(BLOCK, { kp_alt: 1 }, asFields);
  assert.equal(validation.ok, false);
  assert.equal(spec.pyClass, undefined); // 폴백 표기는 lib/codegen 몫
});

test("메타 — 서버 버전은 한 번만 묻고, 시각은 매번 찍는다", async () => {
  const net = io();
  net.get = async () => ({ version: "0.1.0", engine: "0.1.0" });
  const meta = makeMetaSource(net, () => new Date(2026, 7, 22, 9, 5));
  const a = await meta();
  assert.equal(a.generatedAt, "2026-08-22 09:05");
  assert.equal(a.server, "0.1.0");
  await meta();
});

test("헬스가 죽어도 메타는 나온다 — 버전 줄만 빠진다", async () => {
  const net = io();
  net.get = async () => { throw new Error("down"); };
  const m = await makeMetaSource(net, () => new Date(2026, 0, 2, 3, 4))();
  assert.equal(m.generatedAt, "2026-01-02 03:04");
  assert.equal(m.server, undefined);
});
