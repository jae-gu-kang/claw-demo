// 배선별 신호 표시 — 어떤 배선에 어떤 신호를 얹고 어떻게 포맷하는지.
// 여기서 지키는 것: ① 배선 id가 블록도 SVG와 어긋나지 않는다 ② 각은 표시 전용
// deg 변환(내부 규약은 SI+rad) ③ 계측 안 된 항목이 0으로 위장되지 않는다
import { test } from "node:test";
import assert from "node:assert/strict";

import { WIRE_SIGNALS, requiredSignals, wireText } from "./wiresignals.js";

const SIG = {
  cmd_speed: [140, 202], cmd_alt: [1300, 1300], cmd_heading: [0, Math.PI / 2],
  theta_cmd: [0.1, 0.2], phi_cmd: [0, 0.7], theta_lim: [0.1, 0.15],
  pitch: [-0.05, -0.08], roll: [0, 0.26], yaw: [0, 0.04],
  de: [-0.03, -0.04], da: [0, 0.01], dr: [0, 0.002],
  thr_l: [0.47, 0.5], thr_r: [0.47, 0.5],
  V: [200, 210], h: [1000, 1300], psi: [0, 1.5], alpha: [0.05, 0.06],
  theta: [0.1, 0.12], phi: [0, 0.6],
  limiter_active: [0, 1], alpha_margin: [0.2, 0.01],
};

test("모든 배선 항목이 라벨·신호키·자릿수를 갖춘다", () => {
  for (const [id, spec] of Object.entries(WIRE_SIGNALS)) {
    assert.ok(spec.items.length > 0, `${id}: 표시 항목 없음`);
    for (const it of spec.items) {
      assert.ok(it.key, `${id}: 신호 키 누락`);
      assert.ok(["rad", "raw", "text"].includes(it.as ?? "raw"), `${id}.${it.key}: 미정의 변환`);
    }
  }
});

test("wireText: 각은 표시 전용으로 deg 변환 — 내부는 rad 규약 유지", () => {
  // phi_cmd 0.7 rad ≈ 40.1°
  const txt = wireText(WIRE_SIGNALS.w_ap, SIG, 1);
  assert.match(txt, /40/, `deg 변환 안 됨: ${txt}`);
  assert.match(txt, /°/, "각도 단위 표기 없음");
});

test("wireText: 계측 안 된 신호는 0이 아니라 —", () => {
  const partial = { ...SIG };
  delete partial.theta_lim;
  const txt = wireText(WIRE_SIGNALS.w_lim, partial, 0);
  assert.match(txt, /—/, `미계측이 —로 표시되지 않음: ${txt}`);
  assert.doesNotMatch(txt, /\b0\.0+°?\b/, "미계측이 0으로 위장됨");
});

test("wireText: NaN 표본도 — (엔진이 미장착 형상을 NaN으로 채운다)", () => {
  const withNaN = { ...SIG, theta_lim: [NaN, NaN] };
  assert.match(wireText(WIRE_SIGNALS.w_lim, withNaN, 0), /—/);
});

test("wireText: 범위 밖 인덱스는 조용히 0번을 쓰지 않고 —", () => {
  assert.match(wireText(WIRE_SIGNALS.w_ap, SIG, 99), /—/);
});

test("wireText: 여러 항목은 구분자로 이어 붙인다", () => {
  const txt = wireText(WIRE_SIGNALS.w_gui, SIG, 1);
  assert.match(txt, /202/); // cmd_speed
  assert.match(txt, /1300/); // cmd_alt
  assert.ok(txt.includes("·"), `구분자 없음: ${txt}`);
});

test("requiredSignals: 표시에 필요한 신호 키 집합 (재생 요청 검증용)", () => {
  const keys = requiredSignals();
  assert.ok(keys.has("theta_cmd") && keys.has("de") && keys.has("cmd_speed"));
  assert.ok(!keys.has(""), "빈 키 유입");
  // 중복 없이 집합으로
  assert.equal(keys.size, new Set([...keys]).size);
});

test("배선 id는 전부 w_ 접두 — SVG data-sig 값과 대조되는 계약", () => {
  for (const id of Object.keys(WIRE_SIGNALS)) {
    assert.match(id, /^w_[a-z0-9_]+$/, `${id}: 배선 id 규약 위반`);
  }
});

test("wireText: 모드는 문자열 신호 — 숫자 포맷을 타지 않는다", () => {
  const withMode = { ...SIG, mode: ["climb", "wpnav"] };
  assert.equal(wireText(WIRE_SIGNALS.w_plan, withMode, 1), "wpnav");
  assert.equal(wireText(WIRE_SIGNALS.w_plan, { mode: [] }, 0), "—");
});

test("wireText: 라벨이 빈 항목은 값만 (SCAS 축처럼 자리로 뜻이 통할 때)", () => {
  const txt = wireText(WIRE_SIGNALS.w_scas, SIG, 0);
  assert.doesNotMatch(txt, /[가-힣]/, `불필요한 라벨: ${txt}`);
  assert.ok(txt.startsWith("-2.9°") || /^-?\d/.test(txt), `값으로 시작해야: ${txt}`);
});

test("SVG data-sig ↔ WIRE_SIGNALS 양방향 정합 — 한쪽만 바뀌면 값이 조용히 안 뜬다", async () => {
  const { TOP_SVG } = await import("../views/diagram.js");
  const inSvg = new Set([...TOP_SVG.matchAll(/data-sig="([^"]+)"/g)].map((m) => m[1]));
  const inMap = new Set(Object.keys(WIRE_SIGNALS));
  assert.deepEqual([...inSvg].sort(), [...inMap].sort(),
    `SVG ${[...inSvg].sort()} vs 지도 ${[...inMap].sort()}`);
});

test("값 자리는 전부 sigval 클래스 — 오버레이가 스타일을 걸 대상", async () => {
  const { TOP_SVG } = await import("../views/diagram.js");
  for (const m of TOP_SVG.matchAll(/<text[^>]*data-sig="[^"]+"[^>]*>/g)) {
    assert.match(m[0], /class="sigval"/, `sigval 클래스 없음: ${m[0]}`);
  }
});
