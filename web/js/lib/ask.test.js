// 전역 질문 위젯 판정 — 액션 정규화(방어적 수용)와 탭 목록 드리프트 가드
import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";

import { TAB_HASHES, normalizeAnswer } from "./ask.js";

const read = (p) => readFileSync(new URL(p, import.meta.url), "utf8");

const OPTS = {
  views: TAB_HASHES,
  blockPages: new Set(["scas", "scas/pitch", "scas/pitch/pi", "autopilot"]),
};

const answer = (over = {}) => ({
  answer: "마진 맵 탭에서 봅니다.",
  actions: [{ view: "margins", sub: "", label: "마진 맵", why: "히트맵이 전면" }],
  ...over,
});

test("TAB_HASHES는 index.html nav와 순서까지 같다 — 세 번째 원문의 드리프트 가드", () => {
  // blocks.test.js PIPELINE과 같은 방식 — 원문(정본)에서 정규식으로 읽어 대조.
  // 이 목록이 낡으면 위젯이 죽은 탭으로 안내하면서 아무것도 안 빨개진다
  const nav = [...read("../../index.html").matchAll(/data-view="([\w-]+)"/g)]
    .map((m) => m[1]);
  assert.ok(nav.length > 0, "nav를 읽지 못했다 — 가드 자체가 죽으면 안 된다");
  assert.deepEqual(TAB_HASHES, nav);
});

test("정상 답은 그대로 통과하고 해시가 조립된다", () => {
  const out = normalizeAnswer(answer(), OPTS);
  assert.equal(out.issues.length, 0);
  assert.equal(out.answer, "마진 맵 탭에서 봅니다.");
  assert.deepEqual(out.actions, [{ hash: "#margins", label: "마진 맵",
    why: "히트맵이 전면" }]);
});

test("블록도 하위 경로는 해시 세그먼트가 된다", () => {
  const out = normalizeAnswer(answer({
    actions: [{ view: "blocks", sub: "scas/pitch", label: "SCAS 피치", why: "" }],
  }), OPTS);
  assert.equal(out.actions[0].hash, "#blocks/scas/pitch");
});

test("모르는 view는 버리되 사유를 남긴다 — 죽은 탭 안내 금지", () => {
  const out = normalizeAnswer(answer({
    actions: [{ view: "settings", sub: "", label: "설정", why: "" }],
  }), OPTS);
  assert.deepEqual(out.actions, []);
  assert.match(out.issues.join(" "), /모르는 탭.*settings/);
});

test("블록도가 아닌 탭의 sub·모르는 하위 경로는 sub만 버린다", () => {
  const out = normalizeAnswer(answer({
    actions: [
      { view: "margins", sub: "pm", label: "마진", why: "" },      // 하위가 없는 탭
      { view: "blocks", sub: "ghost/page", label: "블록", why: "" }, // 미실존 페이지
    ],
  }), OPTS);
  assert.deepEqual(out.actions.map((a) => a.hash), ["#margins", "#blocks"]);
  assert.equal(out.issues.length, 2); // 각각 사유 — 탭 자체는 살린다
});

test("액션 상한을 넘으면 자르고 사유를 남긴다", () => {
  // 서로 다른 탭 9개 — 같은 탭이면 중복 제거가 먼저 잡아 상한을 못 잰다
  const many = ["blocks", "envelope", "trim", "gains", "margins",
    "sim", "world", "results", "verify"]
    .map((v) => ({ view: v, sub: "", label: v, why: "" }));
  const out = normalizeAnswer(answer({ actions: many }), OPTS);
  assert.equal(out.actions.length, 6);
  assert.match(out.issues.join(" "), /9개.*6개만/);
});

test("중복 액션은 하나만 남기고 사유를 남긴다", () => {
  const out = normalizeAnswer(answer({
    actions: [
      { view: "margins", sub: "", label: "마진", why: "" },
      { view: "margins", sub: "", label: "마진 다시", why: "" },
    ],
  }), OPTS);
  assert.equal(out.actions.length, 1);
  assert.match(out.issues.join(" "), /중복 액션.*#margins/);
});

test("겹슬래시 sub는 페이지 폐기로 안전하게 떨어진다 — 탭은 산다", () => {
  const out = normalizeAnswer(answer({
    actions: [{ view: "blocks", sub: "scas//pitch", label: "", why: "" }],
  }), OPTS);
  assert.equal(out.actions[0].hash, "#blocks");
  assert.match(out.issues.join(" "), /없는 페이지/);
});

test("객체가 아니거나 답이 비면 사유로 말한다", () => {
  assert.match(normalizeAnswer(null, OPTS).issues[0], /객체가 아니다/);
  const out = normalizeAnswer(answer({ answer: "" }), OPTS);
  assert.match(out.issues.join(" "), /답이 비었다/);
});

test("라벨이 비면 탭 이름으로 채운다 — 이름 없는 버튼 금지", () => {
  const out = normalizeAnswer(answer({
    actions: [{ view: "sim", sub: "", label: " ", why: "" }],
  }), OPTS);
  assert.equal(out.actions[0].label, "sim");
});
