/** A급 카드 스트립 — 평가 서랍(영향성)·게인 탭 공용 조립 (판단은 lib/evaluate.js).

views/stage.js처럼 "뷰끼리 공용하는 조립 헬퍼"다 — 같은 카드가 두 탭에서 다르게
생기면 지표가 두 벌로 보인다. 스타일은 인라인이다: 이 스트립은 다크 탭(영향성)과
밝은 탭(게인) 양쪽에 서므로 한쪽 스킨 스코프(.inf-dark)의 클래스에 기대면 다른
쪽에서 민낯이 된다. 색은 판정 잉크(statusInk)만 쓰고 바탕은 반투명 중립이라
양쪽 배경에서 성립한다.

기호(○△✕—)가 색과 별도로 판정을 말한다 — 색 하나에만 기대지 않는 규약.
*/

import { clear, el } from "../dom.js";
import { STATUS_LABEL, cardLines, statusInk } from "../lib/evaluate.js";

export const EVAL_MARK = { ok: "○", warn: "△", fail: "✕", na: "—" };

const CARD_STYLE =
  "flex:1;min-width:min(200px,100%);max-width:300px;padding:10px 12px;" +
  "border:1px solid #88888844;border-radius:10px;background:#88888811";

/** 카드 7장 → 스트립. cards는 서버 echo(순서 = 정본) 그대로 — 여기서 자르거나
 *  재정렬하지 않는다. dim(선택 강조용) 키 집합이 오면 나머지를 흐린다. */
export function renderEvalCards(box, cards, { emphasis = null } = {}) {
  clear(box);
  if (!cards.length) return;
  box.append(el("div", {
    class: "row",
    style: "gap:10px;flex-wrap:wrap;align-items:stretch",
  }, cards.map((c) => {
    const ink = statusInk(c.status);
    const dim = emphasis && emphasis.size && !emphasis.has(c.key);
    return el("div", { style: CARD_STYLE + (dim ? ";opacity:.5" : "") },
      el("div", { class: "row", style: "gap:8px;align-items:center" },
        el("span", {
          class: "flag",
          style: `background:${ink}26;color:${ink};font-weight:700;` +
            "white-space:nowrap",
        }, `${EVAL_MARK[c.status] ?? ""} ${STATUS_LABEL[c.status] ?? c.status}`),
        el("span", { style: "font-weight:600;font-size:13px" },
          `${c.card ?? ""} ${c.label}`)),
      el("div", { style: "margin-top:6px;font-size:12px;line-height:1.55" },
        cardLines(c).map((t) => el("div", {}, t))));
  })));
}
