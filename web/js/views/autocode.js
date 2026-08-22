/** AUTO CODE 탭 — 생성 코드를 한자리에 모은 화면 (02 §4).

기본은 **통합**이다: 형상 전체를 대상으로, 탑재 C부터 열린다. 이 탭에 온 사람이
알고 싶은 것은 "지금 형상에서 무슨 코드가 나오나"이지 블록 하나의 파라미터가
아니기 때문이다. 항목별(블록별)은 대상 선택으로 남는다.

코드 텍스트·검토 패널 조립은 views/codegen.js가 그대로 맡고, 여기는 대상 선택과
스펙 조달만 한다. 판단이 드는 부분(스펙 조립·메타)은 lib/specs.js에 있다.
스타일은 인라인 — app.css는 병행 세션 작업 중이라 건드리지 않는다.
*/

import { api, errorText } from "../api.js";
import { clear, el } from "../dom.js";
import { BLOCKS } from "../lib/blocks.js";
import { schemaFields } from "../lib/schemaform.js";
import { makeMetaSource, makeSpecBuilder } from "../lib/specs.js";
import { store } from "../store.js";
import { renderCodePanel } from "./codegen.js";

const ALL = "__all__";
// 뷰 재생성마다 다시 묻지 않도록 모듈 스코프 (views/gains.js fitCfg 관행)
const state = { target: ALL, opened: false };
const buildSpec = makeSpecBuilder(api);
const codegenMeta = makeMetaSource(api);

const targets = () => BLOCKS.filter((b) => b.detail.editable && b.detail.codegen);

export function render() {
  const panel = el("div");
  const tabs = el("div", { class: "row", style: "margin: 10px 0 0; flex-wrap: wrap" });

  const paint = () => {
    clear(tabs).append(...targetButtons(paint));
    load(panel);
  };

  const host = el("section", {},
    el("h2", {}, "AUTO CODE"),
    el("p", { class: "hint" },
      "현재 설계 형상에서 생성되는 코드입니다. 기본 대상은 형상 전체이고 탑재 C부터 ",
      "열립니다. 탑재 C는 구조 정본인 IR에서 엔진이 생성하며, 같은 형상이면 커밋 ",
      "산출물 flight/gen/ 과 바이트 단위로 같습니다."),
    tabs,
    panel,
  );
  paint();
  return host;
}

function targetButtons(paint) {
  const pick = (id) => () => { state.target = id; paint(); };
  return [
    el("span", { class: "hint", style: "margin-right: 4px" }, "대상"),
    el("button", {
      class: state.target === ALL ? "primary" : "",
      title: "형상 전체 — 제어법칙 탑재 C + 편집 블록 파라미터 + 게인 테이블",
      onclick: pick(ALL),
    }, "통합 (형상 전체)"),
    ...targets().map((b) => el("button", {
      class: state.target === b.id ? "primary" : "",
      title: b.detail.desc ?? "",
      onclick: pick(b.id),
    }, b.title ?? b.id)),
  ];
}

async function load(panel) {
  clear(panel).append(el("p", { class: "hint", style: "margin-top: 12px" }, "생성 중…"));
  try {
    const all = state.target === ALL;
    const blocks = all ? targets() : targets().filter((b) => b.id === state.target);
    const [built, meta] = await Promise.all([
      Promise.all(blocks.map((b) =>
        buildSpec(b, store.get(b.detail.injectKey) ?? null, schemaFields))),
      codegenMeta(),
    ]);
    // 첫 진입은 탑재 C로 연다 — 그 뒤에는 사용자가 고른 탭을 따른다
    const lang = state.opened ? null : "flight";
    state.opened = true;
    renderCodePanel(panel, {
      specs: built.map((r) => r.spec),
      validation: built.map((r) => r.validation),
      gainTables: all ? (store.get("gainTables") ?? null) : null,
      meta,
      lang,
    });
  } catch (e) {
    clear(panel).append(el("div", { class: "error-box" }, errorText(e)));
  }
}
