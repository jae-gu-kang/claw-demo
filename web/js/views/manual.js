/** 블록도 매뉴얼 — DOM 조립 전용.

글·게인 사전·색인은 lib/manualdoc.js가 갖는다 (README 규약: views/는 얇게).
전에는 이 파일이 667줄이었는데 그중 500줄이 데이터였다 — 뷰가 아니었다.
여기 남는 것은 "그 데이터를 어떤 모양으로 화면에 놓는가"뿐이다.

소제목은 manualdoc.js HEADINGS에서만 온다 — 여기에 문자열을 적으면 안 된다
(manualdoc.test.js가 원문을 검사해 막는다).

본문 문자열은 innerHTML로 들어간다 — manualdoc.js의 수작성 정적 문자열만이 원천이고
사용자 데이터는 절대 오지 않는다 (subsystems.js와 같은 계약).
*/

import { api } from "../api.js";
import { el } from "../dom.js";
import {
  BACKGROUND, BLOCK_DOCS, GAIN_GROUPS, HEADINGS, TUNING_ORDER, UNDRAWN_GAINS,
  docFor, gainCountFor, gainsFor,
} from "../lib/manualdoc.js";
import { schemaFields } from "../lib/schemaform.js";
import { DESIGN_ORDER } from "./diagram.js";

const para = (html) => { const p = el("p"); p.innerHTML = html; return p; };
const list = (items) => el("ul", {}, items.map((t) => {
  const li = el("li"); li.innerHTML = t; return li;
}));
const sec = (title, ...kids) => el("section", { class: "man-sec" }, el("h3", {}, title), ...kids);
const stepOf = () => Object.fromEntries(DESIGN_ORDER.map((s) => [s.page, s]));

/** 설계 단계 배지 — 층이면 색·번호, 아니면 회색 '지원' (정본 diagram.js DESIGN_ORDER). */
function stepTag(page) {
  const s = stepOf()[page];
  return s
    ? el("span", { class: "step-tag", style: `background:${s.color}` }, `설계 ${s.n}`)
    : el("span", { class: "step-tag", style: "background:#5f6b78" }, "지원");
}

const goto = (page) => () => { location.hash = `#blocks/${page}`; };

/** 게인 카드를 펴 두는 상한. 접기의 근거는 성격이 아니라 __길이__였다 — 홈에 49개를
펴면 13000px이라 못 훑는다는 관측. 한 페이지 몫은 그 근거가 성립하지 않는 크기라
펴 두고, nav(13개)처럼 여전히 긴 곳만 접는다. */
const OPEN_MAX = 8;

// ── 홈 (#blocks) ───────────────────────────────────────────────────────

/** 홈 매뉴얼 — __어느 한 블록에도 속하지 않는 것만__ (정본 manualdoc.js HOME_SECTIONS).
 *
 * 블록 11개 상세와 게인 49개는 각자의 블록 페이지로 내려갔다. 여기 다 쌓으면 게인
 * 사전만 펴도 13000px이라 훑을 수가 없었고, 무엇보다 그림을 보는 자리와 그 그림의
 * 설명이 다른 페이지에 있었다. 대신 __목차__를 두어 무엇이 어디 있는지 보이게 한다. */
export function renderHomeManual(box) {
  box.append(
    el("div", { class: "manual" },
      el("h2", {}, "블록도 매뉴얼"),
      el("p", { class: "hint" },
        "블록마다의 설명·게인은 그 블록의 내부 블록도 페이지에 있습니다 — 아래 목차에서 여세요. ",
        "여기는 어느 한 블록에도 속하지 않는 것만 답니다."),

      sec("먼저 알아야 할 것",
        el("div", { class: "man-bg" }, BACKGROUND.map((b) =>
          el("div", { class: "man-q" }, el("h4", {}, b.q), b.a.map((t) => para(t)))))),

      sec("어디에 무엇이 있나",
        para("설계 순서대로 다섯 층, 그리고 그 사이를 채우는 지원 블록들입니다. "
          + "각 페이지에 <b>그 그림의 흐름·설계 근거·게인 설명</b>이 함께 있습니다."),
        indexGrid((page) => stepOf()[page], "층 — 설계 순서"),
        indexGrid((page) => !stepOf()[page], "지원 블록")),

      sec("튜닝 순서 요약",
        para("막혔을 때 돌아올 자리입니다. <b>안쪽에서 바깥으로, 감쇠에서 적분으로.</b>"),
        el("ol", { class: "man-order" },
          TUNING_ORDER.map((t) => { const li = el("li"); li.innerHTML = t; return li; })))));
}

/** 목차 한 묶음 — 카드는 .man-head 재사용(본문 없는 머리줄)이라 새 CSS가 거의 없다. */
function indexGrid(keep, label) {
  // 층은 설계 순서(①→⑤)로, 지원은 신호 흐름 순서(BLOCK_DOCS 배열)로 — 각 묶음이
  // 읽히는 순서가 다르다. 층은 "무엇을 먼저 닫나", 지원은 "신호가 어디를 지나나"
  const order = stepOf();
  const rows = BLOCK_DOCS.filter((d) => keep(d.page));
  rows.sort((a, b) => (order[a.page]?.n ?? 0) - (order[b.page]?.n ?? 0));
  return el("div", { class: "man-idx" },
    el("h4", {}, label),
    el("div", { class: "man-idx-grid" }, rows.map((d) => {
      // 블록 전체 몫을 센다 — gainsFor(루트)는 잔여분만이라 SCAS가 0개로 뜬다
      const n = gainCountFor(d.page);
      return el("button", { class: "man-card", onclick: goto(d.page) },
        el("span", { class: "man-card-head" }, stepTag(d.page), el("b", {}, d.title)),
        el("span", { class: "man-card-role" }, d.role),
        n ? el("span", { class: "man-card-n" }, `게인 ${n}`) : null);
    })));
}

// ── 서브시스템 페이지 (#blocks/<경로>) ─────────────────────────────────

/** 그 페이지 몫의 매뉴얼 — 흐름(항상) · 블록 설명(루트) · 게인(접힘).
 *
 * 3겹이다. ① 흐름은 접지 않는다: 접으면 그림이 안 읽히고, 두 문단이라 접을 만큼
 * 길지도 않다. ② 게인은 <details>로 접는다 — 접기의 근거는 성격이 아니라 길이였고
 * (49개 = 13000px), 그래서 카드가 몇 개 안 되는 페이지는 펴 둔다. ③ 그림 속 게인
 * 이름을 클릭하면 그 카드가 열리며 스크롤된다 (배선은 views/blocks.js).
 *
 * 반환값의 revealGain을 뷰가 SVG 배선에 쓴다 — 이 모듈이 카드를 갖고 있으므로
 * "어느 카드로 갈 것인가"도 여기가 안다. */
export function renderPageManual(box, path, flow, diagram = {}) {
  const { doc, isRoot, root } = docFor(path);
  const groups = gainsFor(path);
  const wrap = el("div", { class: "manual inpage" });
  box.append(wrap);

  // flow가 없는 페이지도 있다 (아직 안 쓴 자리) — 그 칸만 비고 나머지는 그대로 뜬다.
  // 어느 페이지가 비었는지는 lib/manualdoc.test.js가 명시 목록으로 붙들고 있다
  if (flow) {
    wrap.append(el("section", { class: "man-flow" },
      el("h4", {}, "이 그림 읽기"),
      el("p", { class: "man-flow-lead" }, flow.lead),
      el("ol", { class: "man-flow-steps" }, flow.reads.map((t) => {
        const li = el("li"); li.innerHTML = t; return li;
      })),
      el("h4", {}, "왜 이 구조인가"),
      flow.why.map((t) => para(t))));
  }

  if (doc && isRoot) {
    // 루트 페이지에만 블록 설명을 붙인다 — "왜 있나"는 블록이 아키텍처에서 차지하는
    // 자리에 대한 진술이라 루트의 사실이고, 하위 넷에 되풀이하면 분량이지 설명이 아니다
    wrap.append(el("section", { class: "man-blk" },
      el("div", { class: "man-head" }, stepTag(doc.page), el("h3", {}, doc.title),
        el("span", { class: "man-role" }, doc.role)),
      el("div", { class: "man-body" },
        el("div", { class: "man-col" },
          Object.entries(HEADINGS).flatMap(([field, label]) =>
            [el("h5", {}, label), para(doc[field])])),
        el("div", { class: "man-col" },
          doc.tuning ? el("div", {}, el("h5", {}, "튜닝"), list(doc.tuning)) : null,
          el("h5", {}, "흔한 증상과 대처"),
          el("dl", { class: "man-tr" }, doc.trouble.flatMap(([sym, fix]) => {
            const dd = el("dd"); dd.innerHTML = fix;
            return [el("dt", {}, sym), dd];
          }))))));
  } else if (doc) {
    // 하위 페이지는 같은 글을 되풀이하지 않고 루트로 가는 한 줄 띠만 받는다
    wrap.append(el("div", { class: "man-head man-parent" },
      stepTag(doc.page), el("b", {}, doc.title),
      el("span", { class: "man-role" }, doc.role),
      el("button", { class: "man-go", onclick: goto(root) }, "이 블록 전체 설명 ▸")));
  }

  // 카드는 스키마 응답 뒤에 채워진다 — 그때까지의 클릭을 삼키지 않으려고 약속을 들고 있는다.
  // 이걸 안 기다리면 페이지를 열자마자 그림의 게인을 누른 사용자에게 **아무 일도 안 일어난다**
  // (느린 서버·폐쇄망에서 더 길어지는 창이다)
  const cards = new Map();
  // 약속이 거부되면 __이후 모든 클릭이__ 같이 죽는다. 카드 렌더 실패는 클릭을 못 살릴
  // 뿐이지, 클릭 자체를 영구히 망가뜨릴 일은 아니다.
  //
  // 다만 __조용히 삼키지는 않는다__: 스키마 실패는 renderGainCards 안에서 이미 잡히므로
  // (단위·기본값 칸만 비운다) 여기까지 오는 것은 진짜 버그뿐이다. 그걸 묻으면 unhandled
  // 경고라는 유일한 신호마저 사라져 개발 중에 아무도 모른다
  let ready = Promise.resolve();
  if (groups.length) {
    ready = renderGainCards(wrap, groups, cards, diagram)
      .catch((e) => { console.error("게인 카드 렌더 실패", e); });
  }

  // 루트 페이지에서 __하위가 가져간 몫__을 알려 준다. groups가 비었을 때만 띄우면
  // 오토파일럿(잔여 3개가 카드로 뜬다)은 안내를 못 받아, 나머지 15개가 한 층 아래
  // 있다는 사실이 화면 어디에도 안 나온다
  const owned = isRoot ? gainCountFor(path[0]) : 0;
  const shown = groups.reduce((n, g) => n + g.rows.length, 0);
  if (owned > shown) {
    wrap.append(el("p", { class: "hint" },
      shown === 0
        ? `이 블록의 게인 ${owned}개는 전부 하위 페이지에 있습니다 — `
        : `이 블록의 게인 ${owned}개 중 ${owned - shown}개는 하위 페이지에 있습니다 — `,
      "위 그림에서 블록을 클릭해 들어가세요."));
  }

  /** 게인 카드로 데려간다 — <details>를 열고, 스크롤하고, 잠깐 강조.
   *
   * 강조는 __한 번에 하나__여야 한다: 이전 것을 안 지우면 누른 자리마다 색이 남아
   * "지금 이것"이 아니라 "여기까지 봤음" 표시가 된다 (기능의 목적과 정반대다).
   * 애니메이션은 되돌아오지만 정적 선언(.hit 배경)은 안 되돌아온다 */
  return async (key) => {
    await ready; // 스키마가 아직이면 기다린다 (실패해도 글 카드는 만들어진다)
    const hit = cards.get(key);
    if (!hit) return false;
    hit.set.open = true;
    for (const n of wrap.querySelectorAll(".man-gain.hit")) n.classList.remove("hit");
    // behavior 기본값 — smooth로 하면 모션 축소 설정을 무시하게 된다
    hit.card.scrollIntoView({ block: "center" });
    hit.card.focus();
    void hit.card.offsetWidth; // 리플로우 강제 — 같은 게인을 연달아 눌러도 다시 번쩍인다
    hit.card.classList.add("hit");
    return true;
  };
}

/** 게인 카드 — 단위·기본값은 레지스트리 스키마에서. 스키마를 못 받아도 글은 전부 뜬다:
값이 없으면 그 칸만 빈다. 서버가 죽었다고 매뉴얼이 사라지면 안 된다.

한 페이지 몫이라 ref마다 요청 하나다 (홈에 사전을 다 두던 때는 6건이었다). */
async function renderGainCards(box, groups, cards, diagram = {}) {
  const fmt = (v) => {
    if (typeof v !== "number") return String(v ?? "");
    if (Math.abs(v) >= 1e29) return "제한 없음";
    return String(Number(v.toPrecision(4)));
  };
  for (const g of groups) {
    // 길면 접고 짧으면 편다. 접기의 근거는 길이였다 — 한 페이지 몫이 몇 개뿐이면
    // 접을 이유가 없고, 열어 두어야 그림 옆에서 바로 읽힌다
    const set = el("details", { class: "man-gset", open: g.rows.length <= OPEN_MAX },
      el("summary", {},
        el("span", { class: "man-gtitle" }, "이 페이지의 게인"),
        el("span", { class: "man-ref" }, g.ref),
        el("span", { class: "man-gcount" }, `${g.rows.length}개`)));
    const lead = el("p", { class: "man-lead" }); lead.innerHTML = g.lead;
    set.append(lead);
    box.append(set);

    let fields = [];
    try {
      const [cat, name] = g.ref.split("/");
      fields = schemaFields(await api.get(`/registry/${cat}/${name}/schema`));
    } catch {
      // 스키마 없이 진행 — 단위·기본값 칸만 빈다
    }
    const byName = Object.fromEntries(fields.map((f) => [f.name, f]));
    for (const d of g.rows) {
      const f = byName[d.key];
      // tabindex −1: focus()는 되고 탭 순서에는 안 들어간다 (그림 클릭으로 오는 자리)
      const row = el("div", { class: "man-gain", tabindex: "-1" },
        el("div", { class: "man-gname" },
          el("code", {}, d.key),
          f?.unit ? el("span", { class: "man-unit" }, `[${f.unit}]`) : null,
          f && f.default !== undefined
            ? el("span", { class: "man-def" }, `기본 ${fmt(f.default)}`) : null,
          f && (f.lo !== null || f.hi !== null)
            ? el("span", { class: "man-def" },
              `범위 ${f.lo === null ? "" : fmt(f.lo)}~${f.hi === null ? "" : fmt(f.hi)}`) : null,
          UNDRAWN_GAINS.has(d.key)
            ? el("span", { class: "man-nodraw" }, "그림에 없음") : null,
          // 그림에 앵커가 있는 게인만 역방향 버튼을 받는다 — 없는 자리에 달면
          // 눌러도 아무 데도 안 가는 버튼이 된다
          diagram.anchored?.has(d.key)
            ? el("button", {
              class: "man-go man-find",
              onclick: () => diagram.onShowInDiagram?.(d.key),
            }, "◂ 그림에서 보기") : null),
        el("div", { class: "man-gtext" }));
      const t = row.lastChild;
      // 본문을 span으로 감싼다 — 격자 칸은 **자식 요소마다** 생기므로, 감싸지 않으면
      // 본문 안의 <b>가 저마다 칸을 차지해 라벨 열로 밀려 들어간다
      const line = (cls, label, html) => {
        const p = el("p", { class: cls });
        p.innerHTML = `<span class="lb">${label}</span><span class="tx">${html}</span>`;
        t.append(p);
      };
      line("g-what", "무엇을", d.what);
      if (d.up) line("g-up", "↑ 올리면", d.up);
      if (d.down) line("g-down", "↓ 내리면", d.down);
      if (d.chain) line("g-chain", "→ 다음 단·기체", d.chain);
      for (const [sym, share] of d.sym ?? []) line("g-sym", `⚠ ${sym}`, share);
      set.append(row);
      cards.set(d.key, { set, card: row });
    }
  }
}
