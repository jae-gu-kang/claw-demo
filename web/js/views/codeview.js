/** 코드 표면 — VS Code 언어의 읽기 전용 편집기 (조립 전용).
 *
 * 거터(줄번호) + 색칠된 본문. 색칠 판단은 lib/highlight.js(테스트 있음), 여기는
 * 노드 조립뿐이다. **삽입 경로는 textContent 하나뿐** — 생성 코드는 서버 응답이고
 * 마크업으로 넣으면 그 순간 코드가 실행 가능한 문서가 된다(codegen.js와 같은 계약).
 *
 * ## 거터가 어긋나지 않는 이유
 *
 * 줄번호를 별도 열에 그리면 본문이 줄바꿈되는 순간 두 열의 줄 수가 갈린다. 그래서
 * 본문은 `white-space: pre`로 **절대 줄바꿈하지 않고**, 넘치면 가로 스크롤한다
 * (편집기가 하는 그대로). 거터는 sticky라 가로로 밀어도 왼쪽에 남는다.
 *
 * ## 아주 큰 파일
 *
 * 탑재 코드 통합본은 수천 줄이다. 토큰마다 span을 만들면 노드가 수만 개가 되므로
 * 상한을 두고 넘으면 **색 없이** 낸다 — 색을 위해 화면이 멎는 것보다, 색이 없는
 * 대신 뜨는 편이 낫다. 그 사실은 화면이 스스로 말한다(조용한 저하 금지).
 */

import { clear, el } from "../dom.js";
import { langOfFile, lineCount, normalizeLang, tokenize } from "../lib/highlight.js";

export { langOfFile };

/** 이 위로는 색칠하지 않는다 [표시 정책] — 실측: 통합본 ~3천 줄/90 kB에서 span 약
 *  1.5만 개, 재조립 40 ms 안팎. 20만 자는 그 두 배쯤에서 끊는 자리다. */
const MAX_PAINT_CHARS = 200_000;

/** 읽기 전용 코드 표면 하나. setCode로 갈아 끼운다 (루트 노드는 유지). */
export function createCodeView({ lang = "text", ariaLabel = "생성 코드" } = {}) {
  const gutter = el("div", { class: "cv-gut", "aria-hidden": "true" });
  const codeBox = el("code", { class: "cv-code" });
  const scroll = el("pre", { class: "cv-scroll", tabIndex: 0, "aria-label": ariaLabel },
    gutter, codeBox);
  const note = el("p", { class: "cv-note hint" });
  const root = el("div", { class: "cv" }, scroll, note);
  let text = "";

  const setCode = (code, nextLang = lang) => {
    text = String(code ?? "");
    const kind = normalizeLang(nextLang);
    const n = lineCount(text);
    clear(gutter);
    // 줄번호는 노드 하나에 개행으로 — n개의 div를 만들면 5천 줄에서 그것만으로 느리다
    gutter.textContent = Array.from({ length: n }, (_, i) => i + 1).join("\n");
    clear(codeBox);
    clear(note);
    if (text.length > MAX_PAINT_CHARS) {
      codeBox.textContent = text;
      note.append(`${n.toLocaleString()}줄 · 문법 색칠 생략 — ${
        (MAX_PAINT_CHARS / 1000).toFixed(0)}k자를 넘는 파일은 색 없이 냅니다 (내용은 그대로).`);
      return;
    }
    const frag = document.createDocumentFragment();
    for (const t of tokenize(text, kind)) {
      // 색 없는 조각은 span을 만들지 않는다 — 노드 수가 절반으로 준다
      frag.append(t.k ? el("span", { class: `cv-${t.k}` }, t.s) : document.createTextNode(t.s));
    }
    codeBox.append(frag);
    if (kind === "text" && text) {
      note.append(`${n.toLocaleString()}줄 · 문법을 모르는 형식이라 색칠하지 않았습니다.`);
    }
  };

  setCode("", lang);
  return {
    root,
    scroll,
    setCode,
    getText: () => text,
    /** 클립보드가 막혔을 때 선택만이라도 — 호출부가 안내 문구를 정한다. */
    selectAll() {
      const range = document.createRange();
      range.selectNodeContents(codeBox);
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
    },
  };
}
