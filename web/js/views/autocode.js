/** Autocode 탭 — 생성 코드를 한자리에, 계층으로 (02 §4).

선택지를 한 줄에 늘어놓으면 "무엇을 고르는 중인지"가 사라진다. 그래서 3단이다:

    종류   [형상코드] [탑재코드]
    ├ 형상코드 → 대상 [통합] [오토파일럿] [작동기] [항법] · 형식 [Python] [C 헤더]
    └ 탑재코드 → 보기 [통합] [모듈별]  → (모듈별이면) 역할별로 묶인 파일 탭

기본은 **탑재코드 · 통합**이다. 이 탭에 온 사람의 주 질문은 "지금 형상에서 무슨
코드가 실리나"이고, 그 답은 파일 하나가 아니라 전체이기 때문이다.

두 종류는 성격이 다르다 — 형상코드는 설계 형상의 코드 표현(파라미터)이고,
탑재코드는 FCC에 그대로 실릴 제어법칙 코드다. 그래서 형식 탭도 갈라 준다.

코드 텍스트·검토 패널 조립은 views/codegen.js가 맡고 여기는 선택과 스펙 조달만
한다. 판단이 드는 부분(스펙 조립·병합·역할 묶음)은 lib/에 있다.
스타일은 인라인 — app.css는 병행 세션 작업 중이라 건드리지 않는다.
*/

import { api, errorText } from "../api.js";
import { clear, el } from "../dom.js";
import { BLOCKS, codegenTargets } from "../lib/blocks.js";
import { schemaFields } from "../lib/schemaform.js";
import { makeMetaSource, makeSpecBuilder } from "../lib/specs.js";
import { store } from "../store.js";
import { renderCodePanel } from "./codegen.js";

const ALL = "__all__";
const SHAPE = "shape";
const FLIGHT = "flight";

// 뷰 재생성마다 처음으로 되돌아가지 않도록 모듈 스코프 (views/gains.js fitCfg 관행)
const state = { kind: FLIGHT, target: ALL, merged: true };
const buildSpec = makeSpecBuilder(api);

let catalogCache = null; // /gains/catalog — SCAS 축 설계 kwargs의 원천
/** 실패해도 코드 패널은 뜬다 (SCAS만 스키마 기본값으로 떨어진다).
 *
 * **성공만 캐시한다.** 실패를 캐시하면 첫 요청 한 번이 실패한 뒤로 페이지를 새로
 * 고치기 전까지 영영 축 설계값 없이 돈다 — 무료 플랜의 15분 유휴 슬립·1분 콜드
 * 스타트에서 그 첫 요청이 실패하는 것은 드문 일이 아니다. 재시도 비용은 요청 하나다.
 */
async function gainsCatalog() {
  if (catalogCache === null) {
    try {
      catalogCache = await api.get("/gains/catalog");
    } catch {
      return null;  // 캐시하지 않는다 — 다음 진입에서 다시 시도한다
    }
  }
  return catalogCache || null;
}
const codegenMeta = makeMetaSource(api);

const targets = () => BLOCKS.filter((b) => b.detail.editable && b.detail.codegen);

const KIND_NOTE = {
  [SHAPE]: "현재 설계 형상을 코드로 적은 것입니다 — 파라미터가 대상이고 로직은 "
    + "담기지 않습니다. 검토·산출물 작성용입니다.",
  [FLIGHT]: "FCC에 통합되어 그대로 실릴 제어법칙 코드입니다 — 구조·블록 로직·"
    + "파라미터가 전부 들어 있고, 구조 정본인 IR에서 엔진이 생성합니다. "
    + "같은 형상이면 커밋 산출물 flight/gen/ 과 바이트 단위로 같습니다.",
};

export function render() {
  const rows = el("div");
  const panel = el("div");

  const paint = () => {
    clear(rows).append(kindRow(paint), subRow(paint));
    load(panel);
  };

  const host = el("section", {},
    el("h2", {}, "Autocode"),
    rows,
    panel,
  );
  paint();
  return host;
}

const btn = (label, on, opts) => el("button", {
  class: on ? "primary" : "",
  ...opts,
}, label);

function kindRow(paint) {
  const pick = (k) => () => { state.kind = k; paint(); };
  return el("div", { class: "row", style: "margin: 10px 0 0; flex-wrap: wrap" },
    el("span", { class: "hint", style: "margin-right: 4px" }, "종류"),
    btn("형상코드", state.kind === SHAPE, {
      title: "설계 형상의 코드 표현 (파라미터)", onclick: pick(SHAPE),
    }),
    btn("탑재코드", state.kind === FLIGHT, {
      title: "FCC에 실릴 제어법칙 코드 (구조·로직·파라미터)", onclick: pick(FLIGHT),
    }),
    el("span", { class: "hint", style: "margin-left: 10px" }, KIND_NOTE[state.kind]),
  );
}

/** 종류에 딸린 2단 — 형상코드는 대상, 탑재코드는 보기 범위. */
function subRow(paint) {
  const row = (...kids) =>
    el("div", { class: "row", style: "margin: 6px 0 0; flex-wrap: wrap" }, ...kids);

  if (state.kind === SHAPE) {
    const pick = (id) => () => { state.target = id; paint(); };
    return row(
      el("span", { class: "hint", style: "margin-right: 4px" }, "대상"),
      btn("통합 (형상 전체)", state.target === ALL, {
        title: "편집 블록 전부 + 게인 스케줄 테이블을 한 파일로", onclick: pick(ALL),
      }),
      ...targets().map((b) =>
        btn(b.title ?? b.id, state.target === b.id, {
          title: b.detail.desc ?? "", onclick: pick(b.id),
        })),
    );
  }

  const pick = (m) => () => { state.merged = m; paint(); };
  return row(
    el("span", { class: "hint", style: "margin-right: 4px" }, "보기"),
    btn("통합 (전체 이어보기)", state.merged, {
      title: "탑재되는 모든 파일을 읽는 순서대로 이어붙인 열람본", onclick: pick(true),
    }),
    btn("모듈별", !state.merged, {
      title: "역할·서브시스템 단위로 파일 하나씩", onclick: pick(false),
    }),
  );
}

async function load(panel) {
  clear(panel).append(el("p", { class: "hint", style: "margin-top: 12px" }, "생성 중…"));
  try {
    const shape = state.kind === SHAPE;
    // 탑재코드는 형상 전체가 대상이다 — 블록 하나만 골라 실을 수는 없다
    const all = !shape || state.target === ALL;
    const blocks = all ? targets() : targets().filter((b) => b.id === state.target);
    // SCAS는 축마다 한 줄로 편다. 편집이 없어도 카탈로그 설계 kwargs로 채운다 —
    // ScasAxis의 스키마 기본값은 0이라 그대로 내면 게인 없는 형상이 나온다
    const catalog = await gainsCatalog();
    const specTargets = blocks.flatMap((b) =>
      codegenTargets(b, store.get(b.detail.injectKey), catalog?.scas_design)
        .map((t) => ({ block: b, ...t })));
    const [built, meta] = await Promise.all([
      Promise.all(specTargets.map((t) =>
        buildSpec(t.block, t.values, schemaFields, t.cg, t.applied))),
      codegenMeta(),
    ]);
    renderCodePanel(panel, {
      specs: built.map((r) => r.spec),
      validation: built.map((r) => r.validation),
      // 게인 스케줄은 형상 전체의 것이라 대상이 통합일 때만 싣는다. 전부 끈 상태는
      // 빈 dict로 표현할 수 없어 별도 신호로 간다 (lib/gainsched.js storePayload)
      gainTables: all ? (store.get("gainTables") ?? null) : null,
      scheduleOff: all ? (store.get("gainScheduleOff") ?? false) : false,
      meta,
      langs: shape ? ["python", "c"] : ["flight"],
      flightMerged: state.merged,
    });
  } catch (e) {
    clear(panel).append(el("div", { class: "error-box" }, errorText(e)));
  }
}
