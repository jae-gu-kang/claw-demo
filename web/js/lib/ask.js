/** 전역 질문 위젯 판정 — 순수 로직 (조립은 views/ask.js, DOM 없이 답이 정해진다).

서버(routes/llm.py `/llm/ask`)가 structured output으로 형상을 강제하지만
방어적으로 받는다(missiondraft.js normalizeDraft와 같은 자리): 문자열 강제,
모르는 탭 액션은 버리되 **사유를 issues에** — 죽은 탭으로 안내하는 버튼이
조용히 서면 안 된다. 허용 목록(views·blockPages)은 **인자로 받는다** —
views/subsystems를 여기서 import하면 층이 역전된다 (lib/stage.js 어투).
*/

/** 상단 탭 해시 — index.html nav 순서 그대로.
 *
 *  이것은 nav·main.js VIEWS에 이은 **세 번째 원문**이다 — ask.test.js가
 *  index.html을 정규식으로 읽어 순서까지 deepEqual로 못박는다(blocks.test.js
 *  PIPELINE 선례). 서버 ASK_SCHEMA의 enum도 같은 가드를 파이썬판으로 갖는다. */
export const TAB_HASHES = [
  "blocks", "envelope", "trim", "gains", "margins", "autodesign",
  "sim", "world", "influence", "autocode", "verify", "results",
];

const MAX_ACTIONS = 6; // 퇴화 응답 방어 — 답 하나에 탭 아홉 개는 안내가 아니다

const str = (v) => (v == null ? "" : String(v));

/** 서버 문답 JSON → 화면에 앉을 형태. 무엇을 버렸든 issues가 말한다. */
export function normalizeAnswer(json, { views, blockPages }) {
  const issues = [];
  const out = { answer: "", actions: [], issues };
  if (json == null || typeof json !== "object" || Array.isArray(json)) {
    issues.push("문답이 객체가 아니다 — 서버 응답을 확인할 것");
    return out;
  }
  out.answer = str(json.answer).trim();
  if (out.answer === "") issues.push("답이 비었다");

  let acts = Array.isArray(json.actions) ? json.actions : [];
  if (acts.length > MAX_ACTIONS) {
    issues.push(`액션 ${acts.length}개 — 앞 ${MAX_ACTIONS}개만 받았다`);
    acts = acts.slice(0, MAX_ACTIONS);
  }
  for (const a of acts) {
    const view = str(a?.view).trim();
    if (!views.includes(view)) {
      // 탭 자체가 틀리면 버린다 — 죽은 탭 버튼은 고장으로 읽힌다
      issues.push(`모르는 탭 액션 버림: ${JSON.stringify(view)}`);
      continue;
    }
    let sub = str(a?.sub).trim().replace(/^\/+|\/+$/g, "");
    if (sub !== "" && view !== "blocks") {
      issues.push(`${view}: 하위 경로가 없는 탭 — sub ${JSON.stringify(sub)} 무시`);
      sub = "";
    } else if (sub !== "" && !blockPages.has(sub)) {
      // 페이지가 틀려도 탭은 살린다 — 블록도 홈이 그 하위의 진입점이다
      issues.push(`블록도에 없는 페이지 — sub ${JSON.stringify(sub)} 무시`);
      sub = "";
    }
    const hash = sub === "" ? `#${view}` : `#${view}/${sub}`;
    if (out.actions.some((x) => x.hash === hash)) {
      // 같은 곳 버튼 둘은 안내가 아니라 잡음이다 (퇴화 응답의 흔한 형태)
      issues.push(`중복 액션 무시: ${hash}`);
      continue;
    }
    out.actions.push({
      hash,
      label: str(a?.label).trim() || view, // 이름 없는 버튼 금지
      why: str(a?.why).trim(),
    });
  }
  return out;
}
