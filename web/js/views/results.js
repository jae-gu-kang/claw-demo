/** 결과 뷰 (02 §8 6단계 열람) — 저장 산출물 목록(메타)·원본 조회.

검증 리포트 생성(M12)은 엔진 구축 대기 — 여기서는 산출물 계보(지문) 열람까지.

배치는 다른 탭과 같은 규약(views/stage.js): **목록이 전면**이고 종류별 요약·저장
구조 설명은 서랍이다. 이 탭에 온 사람의 질문은 "무엇이 저장돼 있나" 하나뿐이라,
그 답 위에 다른 것을 얹지 않는다.
*/

import { api, errorText } from "../api.js";
import { clear, el } from "../dom.js";
import { createDrawers, tabStage, tabTop } from "./stage.js";

// 산출물 종류의 우리말 이름 — 서버가 내는 것은 코드다. 모르는 코드는 **그대로** 낸다
// (임의로 "기타"로 뭉치면 새 종류가 생겼다는 사실이 화면에서 사라진다).
const KIND_LABEL = {
  trim_batch: "트림 배치",
  margin_map: "마진 맵",
  envelope_scan: "엔벨로프 스캔",
  sim: "시뮬레이션",
  auto_design: "자동 설계",
  verify_flight: "검증 — 탑재 C 신뢰성",
  influence_scan: "영향성 — 전 케이스 스캔",
  influence_sweep: "영향성 — 부분 풀 스윕",
  influence_openloop: "영향성 — 개루프 Δ",
  influence_evaluate: "평가 — A급 카드·B급 판정",
  influence_verify: "검증 — C급 (강건성·중간점)",
  influence_prescribe: "정량 처방 — 얼마나·조합·확인",
};
const kindLabel = (k) => KIND_LABEL[k] ?? k ?? "—";

/** 전면에 한 번에 세우는 최대 행 수 [표시 정책].
 *
 *  산출물은 계속 쌓인다(이 개발 서버는 이미 180건이다). 전부 세우면 표가 화면
 *  스무 장이 되고, 그 아래 있는 칩·서랍이 **사실상 닿을 수 없는 곳**으로 밀린다.
 *  최근순이라 앞쪽이 거의 언제나 찾는 것이므로 앞을 자르고, 자른 사실과 전체 수를
 *  화면이 말한다(조용히 자르면 "산출물이 50건뿐"이라고 읽힌다). */
const HEAD_ROWS = 50;

// 탭 재진입에도 열어 둔 서랍·불러온 목록·펼침 상태 유지 (모듈 스코프 규약)
let items = null;
let openDrawer = null;
let showAll = false;

export function render() {
  const listBox = el("div", { class: "tab-sheet" });
  const summaryBox = el("div");
  const errBox = el("div");
  const statusLine = el("p", { class: "tab-status" });

  const drawers = createDrawers({
    id: "results-drawer",
    initial: openDrawer,
    onOpen: (k) => { openDrawer = k; },
    defs: [
      { key: "kinds", label: "종류별 요약", group: "보기",
        title: "무엇을 몇 건 냈나 — 단계별로 실측이 있는지",
        count: () => (items ? new Set(items.map((m) => m.kind)).size : null),
        build: () => summaryBox },
      { key: "about", label: "저장 구조·지문", group: "설명",
        build: () => [
          el("h2", {}, "본문/메타 분리 저장소"),
          el("p", { class: "hint", style: "max-width:96ch" },
            "목록에 뜨는 것은 메타뿐이고 본문(케이스·신호·판정)은 따로 저장된다 — ",
            "그래서 이 표는 산출물이 아무리 커도 즉시 뜬다. 각 행의 [원본 JSON]이 ",
            "본문이며, 다른 탭이 결과를 다시 열 때 쓰는 것과 같은 경로다."),
          el("p", { class: "hint", style: "max-width:96ch" },
            "지문(fingerprint)은 산출물 계보 키 (02 §2.4) — ",
            el("b", {}, "현재 클라이언트 자기신고"),
            "다. 같은 지문이 곧 같은 형상이라는 보장이 아직 없다는 뜻이고, ",
            "파라미터 관리 계층(02 §5.5) 결선 시 엔진 발급으로 전환 예정이다."),
        ] },
    ],
  });

  const paintList = () => renderList(listBox, items, showAll, () => {
    showAll = !showAll;
    paintList();
  });

  const load = async () => {
    try {
      clear(errBox);
      statusLine.textContent = "불러오는 중…";
      items = await api.get("/results");
      statusLine.textContent = items.length
        ? `${items.length}건 · 최근순`
        : "";
      paintList();
      renderSummary(summaryBox, items);
      drawers.refresh();
    } catch (e) {
      items = null;
      statusLine.textContent = "";
      clear(listBox);
      clear(errBox).append(el("div", { class: "error-box" }, errorText(e)));
      drawers.refresh();
    }
  };

  if (items) {
    paintList();
    renderSummary(summaryBox, items);
    statusLine.textContent = `${items.length}건 · 최근순`;
  } else {
    clear(listBox).append(el("p", { class: "hint" }, "불러오는 중…"));
  }
  load();

  return el("div", { class: "tab-page" },
    tabTop({
      title: "결과",
      lead: "이 도구가 지금까지 낸 산출물 전부 — 어느 단계를 실제로 재 봤는지가 "
        + "여기서 한 줄로 읽힌다. 각 행의 원본 JSON이 다른 탭이 되읽는 바로 그 본문이다.",
      actions: [el("button", { onclick: load }, "새로고침")],
      extra: [statusLine, errBox],
    }),
    tabStage(listBox),
    drawers.root,
  );
}

function renderList(box, list, all, onToggle) {
  if (!list.length) {
    clear(box).append(el("p", { class: "hint" },
      "저장된 산출물이 없습니다 — ", el("a", { href: "#trim" }, "트림"), " · ",
      el("a", { href: "#margins" }, "마진 맵"), " · ",
      el("a", { href: "#sim" }, "시뮬레이션"), " 중 하나를 실행하세요."));
    return;
  }
  const shown = all ? list : list.slice(0, HEAD_ROWS);
  clear(box).append(el("div", {},
    list.length > HEAD_ROWS
      ? el("p", { class: "hint", style: "margin:0 0 8px" },
          all
            ? `전체 ${list.length}건을 모두 세웠습니다. `
            : `전체 ${list.length}건 중 최근 ${HEAD_ROWS}건. `,
          el("button", { onclick: onToggle },
            all ? `최근 ${HEAD_ROWS}건만 보기` : `전체 ${list.length}건 보기`))
      : null,
    el("div", { class: "scroll-x" }, el("table", {},
    el("thead", {}, el("tr", {},
      el("th", {}, "생성 시각"), el("th", {}, "종류"), el("th", {}, "id"),
      el("th", {}, "건수"), el("th", {}, "지문(계보)"), el("th", {}, ""))),
    el("tbody", {}, shown.map((m) => el("tr", {},
      el("td", {}, m.created ? new Date(m.created * 1000).toLocaleString() : "—"),
      el("td", {}, kindLabel(m.kind),
        // 코드도 함께 낸다 — 우리말 이름만 내면 API·다른 화면과 대조가 안 된다
        el("span", { class: "hint", style: "margin-left:6px" }, m.kind ?? "")),
      el("td", { class: "num" }, m.id),
      el("td", { class: "num" }, m.n ?? "—"),
      el("td", { class: "num" }, m.fingerprint || "—"),
      el("td", {}, el("a", { href: `/api/results/${m.id}`, target: "_blank" }, "원본 JSON")),
    ))),
  ))));
}

function renderSummary(box, list) {
  const counts = new Map();
  for (const m of list) counts.set(m.kind, (counts.get(m.kind) ?? 0) + 1);
  // 많은 순 — 무엇을 주로 돌렸는지가 순서로 읽힌다
  const rows = [...counts.entries()].sort((a, b) => b[1] - a[1]);
  clear(box).append(
    el("h2", {}, "종류별 요약"),
    rows.length === 0
      ? el("p", { class: "hint" }, "아직 아무것도 저장되지 않았습니다.")
      : el("div", { class: "scroll-x" }, el("table", {},
          el("thead", {}, el("tr", {},
            el("th", {}, "종류"), el("th", {}, "코드"), el("th", {}, "건수"),
            el("th", {}, "최근"))),
          el("tbody", {}, rows.map(([kind, n]) => {
            // 목록은 최근순이라 처음 만나는 것이 그 종류의 최근이다
            const last = list.find((m) => m.kind === kind);
            return el("tr", {},
              el("td", {}, kindLabel(kind)),
              el("td", { class: "num" }, kind ?? "—"),
              el("td", { class: "num" }, n),
              el("td", {}, last?.created
                ? new Date(last.created * 1000).toLocaleString() : "—"));
          })))),
  );
}
