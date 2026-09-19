// 로그인 게이트 로직 검증 — 게이트 필요 판정, 흩뿌리기 계획 결정성, 스태거, 실패 문구
import { test } from "node:test";
import assert from "node:assert/strict";

import { ApiError } from "../api.js";
import { loginFailText, needsGate, scatterPlan, snapDelays } from "./logingate.js";

test("needsGate — 세션 모드에서 미인증일 때만 참", () => {
  assert.equal(needsGate({ mode: "session", user: null }), true);
  assert.equal(needsGate({ mode: "session", user: { username: "kim" } }), false);
  assert.equal(needsGate({ mode: "basic", user: null }), false);
  assert.equal(needsGate({ mode: "open", user: null }), false);
  // 응답이 아예 없으면(서버 무응답 등) 게이트로 부팅을 막지 않는다 — 이후 401이 다시 세운다
  assert.equal(needsGate(null), false);
  assert.equal(needsGate(undefined), false);
});

test("scatterPlan — 결정적(같은 seed 같은 계획), 개수·범위", () => {
  const a = scatterPlan(10);
  const b = scatterPlan(10);
  assert.deepEqual(a, b); // 새로고침마다 다른 그림이면 스냅숏 비교·디버깅이 안 된다
  assert.equal(a.length, 10);
  assert.notDeepEqual(a[0], a[1]); // 전부 같은 곳에 흩어지면 해체로 안 보인다
  for (const p of a) {
    assert.ok(Math.abs(p.dx) <= 420 && Math.abs(p.dy) <= 300, "화면(viewBox) 밖으로 날아가지 않는다");
    assert.ok(Math.abs(p.rot) <= 30, "글자가 뒤집힐 만큼 돌리지 않는다");
    assert.ok(p.dur >= 3 && p.dur <= 8, "둥둥 주기는 느긋하게");
    assert.ok(p.delay <= 0, "음수 delay — 시작부터 위상이 갈라져 있어야 한다");
    assert.ok(Math.abs(p.fx) >= 4 && Math.abs(p.fy) >= 4, "떠다니는 진폭이 보일 만큼");
  }
  assert.notDeepEqual(scatterPlan(10, 99), a); // seed가 다르면 다른 계획
});

test("snapDelays — 조립 순서 스태거(단조 증가), 기본 80ms 간격", () => {
  assert.deepEqual(snapDelays(4), [0, 80, 160, 240]);
  assert.deepEqual(snapDelays(3, 120), [0, 120, 240]);
  assert.deepEqual(snapDelays(0), []);
});

test("loginFailText — 401/403(pending·rejected)/기타 매핑", () => {
  assert.match(loginFailText(new ApiError(401, "아이디 또는 비밀번호가 맞지 않는다")), /맞지 않는다/);
  assert.match(loginFailText(new ApiError(403, { code: "pending", message: "가입 승인 대기 중이다" })), /대기/);
  assert.match(loginFailText(new ApiError(403, { code: "rejected", message: "가입이 거절된 계정이다" })), /거절/);
  assert.match(loginFailText(new TypeError("Failed to fetch")), /Failed to fetch/); // 지어내지 않는다
});
