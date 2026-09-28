/** 조사 고르기 — 받침(숫자는 읽는 소리)에 따라 「으로/로」·「이/가」·「을/를」·「은/는」·「과/와」. */

import assert from "node:assert/strict";
import { test } from "node:test";

import { finalConsonant, josaOf, withJosa } from "./josa.js";

test("withJosa — 리비전 번호에 「으로/로」 (쇼케이스 결함: 「리비전 3로」)", () => {
  // 삼(ㅁ) → 으로, 이(모음) → 로, 일·칠·팔(ㄹ) → 로 — ㄹ 받침은 「로」다
  assert.equal(`리비전 ${withJosa(3, "으로/로")}`, "리비전 3으로");
  assert.equal(withJosa(2, "으로/로"), "2로");
  assert.equal(withJosa(1, "으로/로"), "1로");
  assert.equal(withJosa(7, "으로/로"), "7로");
  assert.equal(withJosa(8, "으로/로"), "8로");
  assert.equal(withJosa(5, "으로/로"), "5로");
  assert.equal(withJosa(6, "으로/로"), "6으로"); // 육(ㄱ)
  assert.equal(withJosa(0, "으로/로"), "0으로"); // 영(ㅇ)
});

test("withJosa — 0으로 끝나는 수는 자릿값의 소리 (십·백·천·만·억·조)", () => {
  assert.equal(withJosa(10, "으로/로"), "10으로"); // 십(ㅂ)
  assert.equal(withJosa(20, "이/가"), "20이");
  assert.equal(withJosa(100, "을/를"), "100을"); // 백(ㄱ)
  assert.equal(withJosa(3000, "은/는"), "3000은"); // 천(ㄴ)
  assert.equal(withJosa(50000, "과/와"), "50000과"); // 만(ㄴ)
  assert.equal(withJosa(200000000, "이/가"), "200000000이"); // 억(ㄱ)
  assert.equal(withJosa(1e12, "이/가"), "1000000000000가"); // 조(모음)
  assert.equal(withJosa(12, "으로/로"), "12로"); // 이(모음) — 끝자리만 본다
});

test("withJosa — 소수는 끝자리를 한 자씩 읽는다 (2.0 → 영, 0.5 → 오)", () => {
  assert.equal(withJosa("2.0", "으로/로"), "2.0으로");
  assert.equal(withJosa(0.5, "으로/로"), "0.5로");
  assert.equal(withJosa(0.25, "이/가"), "0.25가");
});

test("withJosa — 한글 낱말은 끝 글자의 받침", () => {
  assert.equal(withJosa("리비전", "으로/로"), "리비전으로");
  assert.equal(withJosa("표", "으로/로"), "표로");
  assert.equal(withJosa("레일", "으로/로"), "레일로"); // ㄹ 받침
  assert.equal(withJosa("형상", "이/가"), "형상이");
  assert.equal(withJosa("게인", "을/를"), "게인을");
  assert.equal(withJosa("기체", "을/를"), "기체를");
  assert.equal(withJosa("사본", "과/와"), "사본과");
  assert.equal(withJosa("노드", "은/는"), "노드는");
});

test("withJosa — 짝을 앞뒤 어느 순서로 줘도 받침 쪽 조사를 고른다", () => {
  assert.equal(withJosa(3, "로/으로"), "3으로");
  assert.equal(withJosa(2, "가/이"), "2가");
});

test("withJosa — 읽을 수 없는 끝(영문·기호·빈 값)은 병기 「(으)로」로 둔다 — 틀린 조사를 단정하지 않는다", () => {
  assert.equal(withJosa("eoir", "으로/로"), "eoir(으)로");
  assert.equal(withJosa("M0.18_h3000_f50)", "이/가"), "M0.18_h3000_f50)이(가)");
  assert.equal(withJosa("", "을/를"), "을(를)");
  assert.equal(withJosa(null, "으로/로"), "—(으)로");
  assert.equal(withJosa(Number.NaN, "으로/로"), "NaN(으)로");
});

test("finalConsonant — 받침 없음 null · ㄹ은 'ㄹ' · 그 밖은 'other' · 모름은 undefined", () => {
  assert.equal(finalConsonant("가"), null);
  assert.equal(finalConsonant("길"), "ㄹ");
  assert.equal(finalConsonant("각"), "other");
  assert.equal(finalConsonant("3"), "other");
  assert.equal(finalConsonant("x"), undefined);
});

test("withJosa — 모르는 짝이면 던진다 (조용히 잘못된 문장을 내지 않는다)", () => {
  assert.throws(() => withJosa(3, "에서"), /짝/);
});

test("josaOf — 조사만: 괄호 덧붙임 뒤라도 앞 낱말로 고른다 (「확정본 (r1)을」·「게인 표 (r1)를」)", () => {
  assert.equal(`자동 설계 확정본 (r1)${josaOf("자동 설계 확정본", "을/를")}`, "자동 설계 확정본 (r1)을");
  assert.equal(`문서의 확정 게인 표${josaOf("문서의 확정 게인 표", "을/를")}`, "문서의 확정 게인 표를");
  assert.equal(josaOf("δe_trim 표", "을/를"), "를");
  assert.equal(josaOf("초기 게인", "을/를"), "을");
  assert.equal(josaOf("eoir", "을/를"), "을(를)");
});
