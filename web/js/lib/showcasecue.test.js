// 쇼케이스 신호 규약 — 한 번 읽기·탭 구분·보고 대조·시간 초과 (node --test, 의존 0)
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  CUE_KEY, REPORT_KEY, awaitReport, failCue, postCue, reportCue, takeCue, unknownAction,
} from "./showcasecue.js";

function memStore() {
  const state = {};
  const subs = new Set();
  return {
    get: (k) => state[k],
    set(k, v) { state[k] = v; for (const fn of subs) fn(k, v); },
    subscribe(fn) { subs.add(fn); return () => subs.delete(fn); },
  };
}

test("신호는 받을 탭만 한 번 읽고 지운다", () => {
  const s = memStore();
  postCue({ token: "t1", tab: "trim", action: "run" }, s);
  assert.equal(takeCue("margins", s), null, "다른 탭은 건드리지 않는다");
  assert.ok(s.get(CUE_KEY), "다른 탭이 읽어도 남아 있다");
  const c = takeCue("trim", s);
  assert.deepEqual(c, { token: "t1", tab: "trim", action: "run", args: {} });
  assert.equal(takeCue("trim", s), null, "두 번째 렌더는 빈손");
});

test("신호 모양이 틀리면 거부한다", () => {
  const s = memStore();
  assert.throws(() => postCue({ tab: "trim", action: "run" }, s), TypeError);
  assert.throws(() => postCue(null, s), TypeError);
});

test("보고는 토큰·탭·동작을 달고, done은 ok 기본 참·failed는 ok 거짓", () => {
  const s = memStore();
  const cue = { token: "t2", tab: "verify", action: "run" };
  reportCue(cue, { phase: "started", jobId: "j1" }, s);
  assert.deepEqual(s.get(REPORT_KEY),
    { token: "t2", tab: "verify", action: "run", phase: "started", jobId: "j1" });
  reportCue(cue, { phase: "done", resultId: "r1", summary: "통과" }, s);
  assert.equal(s.get(REPORT_KEY).ok, true);
  failCue(cue, new Error("컴파일러 없음"), s);
  assert.equal(s.get(REPORT_KEY).ok, false);
  assert.equal(s.get(REPORT_KEY).error, "컴파일러 없음");
  assert.throws(() => reportCue(cue, { phase: "weird" }, s), TypeError);
  reportCue(null, { phase: "done" }, s); // 신호 없이 연 탭 — 아무 일도 없다
});

test("모르는 동작은 실패 보고로 말한다", () => {
  const s = memStore();
  unknownAction({ token: "t3", tab: "gains", action: "dance" }, s);
  const r = s.get(REPORT_KEY);
  assert.equal(r.ok, false);
  assert.match(r.error, /dance/);
});

test("awaitReport — 제 토큰의 끝 보고만 받고 중간 경과는 onEvent로 흘린다", async () => {
  const s = memStore();
  const cue = { token: "t4", tab: "sim", action: "run" };
  const seen = [];
  const p = awaitReport(cue, { s, timeoutMs: 1000, onEvent: (v) => seen.push(v.phase) });
  reportCue({ ...cue, token: "other" }, { phase: "done" }, s); // 남의 토큰
  reportCue({ ...cue, action: "draft" }, { phase: "done" }, s); // 같은 탭 다른 동작
  reportCue(cue, { phase: "started", jobId: "j" }, s);
  reportCue(cue, { phase: "progress", summary: "50%" }, s);
  reportCue(cue, { phase: "done", resultId: "r9" }, s);
  const r = await p;
  assert.equal(r.resultId, "r9");
  assert.deepEqual(seen, ["started", "progress"]);
});

test("awaitReport — 시간 초과는 사유를 단 실패, 취소는 null", async () => {
  const s = memStore();
  const r = await awaitReport({ token: "t5", tab: "world", action: "play" }, { s, timeoutMs: 20 });
  assert.equal(r.ok, false);
  assert.match(r.error, /world/);
  let stop = false;
  const p = awaitReport({ token: "t6", tab: "trim", action: "run" },
    { s, timeoutMs: 5000, cancelled: () => stop });
  stop = true;
  assert.equal(await p, null);
});
