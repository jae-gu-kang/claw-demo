/** 쇼케이스 신호가 끝나면 결과가 사는 자리를 화면에 올린다 — 탭 배선 가드 (06 §2, e2e D4).

e2e: 진행기가 영향성·결과·Autocode 동작을 끝냈을 때 페이지는 scrollY 0에 있었고, 결과는 그 아래
(영향성 판정 줄 y≈2720 · 결과 브리핑 y≈1163 · Autocode 대조 캡션 y≈828)에 묻혀 있었다. 진행기는 보고를
받자마자 다음 탭으로 가므로 **보고 앞에서** 올려야 청중이 본다. 올리는 일은 공용 lib/reveal.js revealPanel
(떨어진 노드는 굴리지 않는다)이다.

뷰(views/*.js)는 DOM을 모듈 스코프에서 만져 import할 수 없다 — 배선은 원문에서 읽는다
(influence.test.js·aircraftcue.test.js와 같은 가드).
*/

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const view = (name) => readFileSync(new URL(`../views/${name}.js`, import.meta.url), "utf8");

/** 원문 조각 — start 문자열에서 시작해 end 정규식의 첫 매치까지(끝 포함). 못 찾으면 "". */
function slice(src, start, end) {
  const i = src.indexOf(start);
  if (i < 0) return "";
  const m = end.exec(src.slice(i));
  return m ? src.slice(i, i + m.index + m[0].length) : "";
}

/** 조각 안의 done 보고마다 — 그 reportCue 호출 앞(직전 done 보고 뒤)에 revealPanel이 있는가.
 *  돌려주는 것: done 보고 수(0이면 조각을 잘못 짚었다). */
function assertRevealBeforeDone(body, what) {
  assert.ok(body, `${what}: 원문 조각을 찾지 못했다`);
  let from = 0;
  let n = 0;
  for (;;) {
    const done = body.indexOf('phase: "done"', from);
    if (done < 0) break;
    const call = body.lastIndexOf("reportCue(", done);
    const reveal = body.lastIndexOf("revealPanel(", call);
    assert.ok(reveal >= from, `${what}: done 보고(${n + 1}번째) 앞에서 결과 자리를 올리지 않는다`);
    from = done + 1;
    n += 1;
  }
  assert.ok(n > 0, `${what}: done 보고가 없다 — 조각을 잘못 짚었다`);
  return n;
}

const importsReveal = (src, what) =>
  assert.match(src, /import \{ revealPanel \} from "\.\.\/lib\/reveal\.js";/, `${what}: 공용 lib/reveal을 쓰지 않는다`);

test("영향성 — 진단·선별/평가·처방, 셋 다 결과 자리(진단 줄·판정 줄·수정안)를 올린 뒤 보고한다", () => {
  const src = view("influence");
  importsReveal(src, "영향성");
  const cue = slice(src, "async function handleCue(c) {", /\n {2}\}\n/);
  assert.equal(assertRevealBeforeDone(cue, "영향성 handleCue"), 3);
  // 평가 판정 줄은 카드·체크·소견 아래(y≈2720) — 그 노드를 올린다(판정이 없으면 상태 줄)
  assert.match(cue, /revealPanel\(evalVerdictNode \?\? evalStatus\);/);
  const renderEval = slice(src, "function renderEval() {", /\n {2}\}\n/);
  assert.match(renderEval, /^\s*evalVerdictNode = null;/m, "판정 노드를 매 그리기마다 비우지 않는다(옛 판정이 남는다)");
  assert.match(renderEval, /evalVerdictNode = el\("h3"[\s\S]{0,160}?하드 게이트 위반/);
  assert.match(renderEval, /evalVerdictNode = el\("p"[\s\S]{0,120}?\n\s*"하드 게이트 전부 통과/);
});

test("결과 — 브리핑(open)·소견서(opinion)를 지금 화면에서 올린 뒤 보고한다", () => {
  const src = view("results");
  importsReveal(src, "결과");
  // 옛 화면의 재부착 감시자가 먼저 끝나도 올리는 것은 지금 화면이다 — 모듈 hosts를 render가 갈아 끼운다
  assert.match(src, /hosts = \{ brief: briefBox, opinion: opinionBox \};/);
  const open = slice(src, "async function runCue(cue,", /\n\}\n/);
  assertRevealBeforeDone(open, "결과 runCue");
  assert.match(open, /revealPanel\(hosts\.brief\);/);
  const opinion = slice(src, "const settleOpinionCue = ", /\n {2}\};\n/);
  assertRevealBeforeDone(opinion, "결과 settleOpinionCue");
  assert.match(opinion, /revealPanel\(hosts\.opinion\);/);
});

test("Autocode — 대조 캡션을 올린 뒤 보고한다(부드러운 scrollIntoView 직접 호출로 돌아가지 않는다)", () => {
  const src = view("autocode");
  importsReveal(src, "Autocode");
  const settled = slice(src, "async function flightSettled(", /\n\}\n/);
  assertRevealBeforeDone(settled, "Autocode flightSettled");
  // 캡션이 있는 갈래(대조)에서만 — 빈 캡션 자리를 굴리면 코드판이 화면 밖으로 밀린다
  assert.match(settled, /if \(other\) \{[\s\S]*?paintCaption\(captionHost, data\);[\s\S]{0,300}?revealPanel\(captionHost\);\n {2}\}/);
  assert.doesNotMatch(src, /scrollIntoView/);
});

test("검증 — 판정판을 올린 뒤 보고한다(지금 화면의 판정판)", () => {
  const src = view("verify");
  importsReveal(src, "검증");
  assert.match(src, /boardHost = boardBox;/);
  const settle = slice(src, "const settleCue = ", /\n {2}\};\n/);
  assertRevealBeforeDone(settle, "검증 settleCue");
  assert.match(settle, /revealPanel\(boardHost\);/);
});

test("시뮬 — 착륙 요약(재생 패널 머리)·초안 미리보기·타면 표를 올린 뒤 보고한다", () => {
  const src = view("sim");
  importsReveal(src, "시뮬");
  const run = slice(src, "const reportRunCue = ", /\n {2}\};\n/);
  assertRevealBeforeDone(run, "시뮬 reportRunCue");
  assert.match(run, /revealPanel\(replayBox\);/);
  const draft = slice(src, "const reportDraftCue = ", /\n {2}\};\n/);
  assertRevealBeforeDone(draft, "시뮬 reportDraftCue");
  assert.match(draft, /revealPanel\(draftResultBox\);/);
  const duty = slice(src, "const cueDuty = ", /\n {2}\};\n/);
  assertRevealBeforeDone(duty, "시뮬 cueDuty");
  assert.match(duty, /revealPanel\(dutyPanel\.root\);/);
});

test("설계 흐름 — 레일을 올린 뒤 보고한다(지금 화면의 레일 — repaint와 같은 규약)", () => {
  const src = view("flow");
  importsReveal(src, "설계 흐름");
  assert.match(src, /revealRail = \(\) => revealPanel\(rowsBox\);/);
  const ov = slice(src, "async function overview(cue) {", /\n\}\n/);
  assert.ok(ov, "overview를 찾지 못했다");
  const done = ov.indexOf('phase: "done"');
  assert.ok(done > 0 && ov.lastIndexOf("revealRail();", done) > 0, "레일을 올리지 않고 보고한다");
});

test("자동 설계 — 보고서를 올린 뒤 보고한다(open·design-and-apply 둘 다)", () => {
  const src = view("autodesign");
  importsReveal(src, "자동 설계");
  assert.match(src, /screen = \{ errBox, progressBox, resultBox, form, start, showResult(, \w+)* \};/); // 뒤에 손잡이가 붙어도(syncEmpty)
  const cue = slice(src, "async function runCue(cue) {", /\n\}\n/);
  assert.equal(assertRevealBeforeDone(cue, "자동 설계 runCue"), 2);
  assert.equal(cue.match(/revealPanel\(screen\?\.resultBox\);/g)?.length, 2);
});
