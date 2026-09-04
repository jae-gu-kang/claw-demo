/** 전면 배치 뼈대 — 머리줄 + 전면 무대 + 칩·서랍 (조립 전용).
 *
 * 이 앱의 탭 규약(02 §4): **주 그림은 카드 밖 전면에, 나머지는 눌렀을 때만.**
 * 블록도 최상위가 먼저 그렇게 했고(.bd .canvas-wrap.top — 보드가 화면의 주인공이라
 * 그 위에 카드를 하나 더 얹지 않는다) 영향성·가상환경이 따랐다. 그 배치를 탭마다
 * 베끼면 같은 레이아웃이 열 벌이 되므로 여기 한 벌만 둔다.
 *
 * 판단(어느 서랍이 열리나·배지·분류 줄)은 lib/stage.js에 있고 여기는 DOM뿐이다.
 *
 * ## 밝은 탭과 어두운 탭
 *
 * 뼈대는 색이 없다. 어두운 것은 **주 그림이 어두운 탭**뿐이다 — 영향성(IR 그래프)·
 * 가상환경(3D)·Autocode(편집기). 나머지(엔벨로프·시뮬·트림·마진·게인·자동설계·
 * 타면·결과)는 캔버스가 흰 종이라 밝은 채로 둔다. 캔버스 팔레트를 통째로 뒤집는
 * 것은 이 작업의 범위가 아니고, 어중간하게 뒤집으면 흰 그림 위에 검은 테두리만
 * 남는다. 어둡게 하려면 루트에 `tab-dark`를 함께 준다(CSS가 스코프로 받는다).
 */

import { clear, el } from "../dom.js";
import { chipModels, openDef, toggleOpen } from "../lib/stage.js";

/** 머리줄 — 카드 없는 제목 + 한 줄 설명 + 오른쪽 조작.
 *
 *  lead·actions가 둘 다 없으면 줄 자체를 만들지 않는다 (빈 줄이 여백만 먹는다).
 *  lead는 글이거나 **노드**다 — 문구가 선택에 따라 바뀌는 탭은 자기 `<p>`를 쥐고
 *  갈아 끼운다. 그걸 다시 `<p>`로 감싸면 p 안에 p가 되어 브라우저가 조각을 낸다. */
export function tabTop({ title, lead = null, actions = null, extra = null } = {}) {
  const sub = lead || actions
    ? el("div", { class: "tab-subline" },
        lead == null ? el("p", {}) : lead.nodeType ? lead : el("p", {}, lead),
        actions ? el("div", { class: "row", style: "gap:8px" }, actions) : null)
    : null;
  return el("div", { class: "tab-top" }, el("h1", {}, title), sub, extra);
}

/** 전면 무대 — **규칙이 없는 것이 요지다.** 캔버스·SVG는 자기 테두리를 이미 갖고,
 *  그 바깥에 배경도 테두리도 두지 않는 것이 "칸 없이 페이지 위에"다. */
export function tabStage(...kids) {
  return el("div", { class: "tab-stage" }, ...kids);
}

/** 칩 줄 + 서랍 한 벌.
 *
 * defs: [{key, label, group?, title?, count?, hidden?, build()}] — lib/stage.js 계약.
 * `build()`는 **열 때마다** 불린다. 내용 박스를 모듈/클로저에 잡아 두고 그것을
 * 돌려주면(영향성 관행) 서랍을 닫을 때마다 다시 그리는 비용이 없다.
 *
 * 돌려주는 것:
 *   root    — 칩 줄 + 서랍을 담은 조각 (그대로 append)
 *   refresh — 배지·숨김만 다시 (결과가 생겼는데 서랍이 닫혀 있어도 개수는 보여야 한다)
 *   open(key) — 서랍을 열어 준다. 잡이 끝난 뒤 결과가 사는 서랍을 여는 자리
 *   current() — 지금 열린 키
 */
export function createDrawers({ id, defs, initial = null, onOpen = null } = {}) {
  const chipRow = el("div", { class: "tab-chips" });
  const box = el("div", { class: "tab-drawer", id });
  const btns = new Map(); // key → 버튼 노드 (**재사용**한다 — 아래 참조)
  let open = initial;

  /** 칩 줄만 갱신한다 — 서랍 내용은 건드리지 않는다.
   *
   *  **버튼을 다시 만들지 않는 것이 요지다.** 배지 하나 바뀌었다고 줄을 새로 조립하면
   *  방금 누른 버튼이 DOM에서 들려 나가 포커스가 `<body>`로 떨어지고, 열려 있던 서랍
   *  안에서 타이핑 중이던 칸도 같이 사라진다(영향성 `syncChips`가 겪고 고친 그 자리).
   *  키 집합이 그대로면 제자리에서 라벨·배지·눌림만 고친다. */
  const paintChips = () => {
    const models = chipModels(defs, open);
    open = models.find((m) => m.expanded)?.key ?? null;
    const wanted = models.filter((m) => !m.hidden).map((m) => m.key);
    const have = [...chipRow.children]
      .filter((n) => n.classList.contains("tab-chip"))
      .map((n) => n.dataset.key);
    const sameSet = wanted.length === have.length
      && wanted.every((k, i) => k === have[i]);
    if (!sameSet) {
      clear(chipRow);
      btns.clear();
    }
    for (const m of models) {
      if (m.hidden) continue;
      let btn = btns.get(m.key);
      if (!btn) {
        btn = el("button", {
          class: "tab-chip",
          type: "button",
          "data-key": m.key,
          "aria-controls": id,
          onclick: () => {
            open = toggleOpen(defs, open, m.key);
            paintChips();
            paintDrawer();
            onOpen?.(open);
          },
        });
        btns.set(m.key, btn);
        if (m.startsGroup) chipRow.append(el("span", { class: "tab-chipgroup" }, m.group));
        chipRow.append(btn);
      }
      btn.setAttribute("aria-expanded", m.expanded ? "true" : "false");
      btn.title = m.title ?? "";
      // 라벨·배지는 매번 갈아 끼운다 — 노드 둘뿐이라 포커스에 영향이 없다.
      // **null을 넘기지 않는다**: `clear()`가 돌려주는 것에 붙이는 append는 네이티브라
      // null을 "null" 텍스트로 찍는다(`el()`은 거른다). 배지 없는 칩이 「격자 조건null」이
      // 됐다 — 이 리포의 상습 함정군이고 이번 작업에서만 세 번째다
      clear(btn).append(m.label);
      if (m.badge) btn.append(el("span", { class: "n" }, m.badge));
    }
  };

  const paintDrawer = () => {
    clear(box);
    const d = openDef(defs, open);
    if (!d) return;
    for (const node of [d.build()].flat()) if (node) box.append(node);
  };

  paintChips();
  paintDrawer();
  return {
    root: el("div", {}, chipRow, box),
    chipRow,
    box,
    /** 배지·숨김만 — **서랍 내용은 그대로 둔다.** 결과가 생겼는데 서랍이 닫혀 있어도
     *  개수는 보여야 하고, 열려 있는 서랍에서 편집 중이면 그 편집이 살아 있어야 한다. */
    refresh: paintChips,
    /** 내용까지 다시 — 열린 서랍이 그리는 것 자체가 바뀌었을 때만. */
    repaint() {
      paintChips();
      paintDrawer();
    },
    current: () => open,
    open(key) {
      open = toggleOpen(defs, null, key); // null에서 여는 것 = 항상 그 칩을 연다
      paintChips();
      paintDrawer();
    },
  };
}

/** 서랍 안의 소제목 — 서랍 하나에 여러 덩이가 들어갈 때만 쓴다. */
export function drawerSection(title, hint, ...kids) {
  return el("section", { class: "tab-sect" },
    el("h2", {}, title),
    hint ? el("p", { class: "hint", style: "margin:0 0 10px" }, hint) : null,
    ...kids);
}
