/** 결과 뷰 (02 §8 12단계 열람) — 저장 산출물 목록(메타)·원본 조회.

검증 리포트 생성(M12)은 엔진 구축 대기 — 여기서는 산출물 계보(지문) 열람까지.

배치는 다른 탭과 같은 규약(views/stage.js): **목록이 전면**이고 종류별 요약·저장
구조 설명은 패널이다. 이 탭에 온 사람의 질문은 "무엇이 저장돼 있나" 하나뿐이라,
그 답 위에 다른 것을 얹지 않는다.
*/

import { api, errorText } from "../api.js";
import { clear, el } from "../dom.js";
import { attachProgress, cancelledWithoutResult } from "./progress.js";
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
  influence_evaluate: "평가 — 대표 카드·나머지 판정",
  influence_verify: "검증 — 3단계 (강건성·중간점)",
  influence_prescribe: "정량 처방 — 얼마나·조합·확인",
  mission_draft: "미션 초안 (LLM)",
  llm_brief: "소견서 (LLM)",
  llm_comms: "교신 대본 (LLM)",
  llm_ask: "문답 (LLM)",
};
const kindLabel = (k) => KIND_LABEL[k] ?? k ?? "—";

/** 전면에 한 번에 세우는 최대 행 수 [표시 정책].
 *
 *  산출물은 계속 쌓인다(이 개발 서버는 이미 180건이다). 전부 세우면 표가 화면
 *  스무 장이 되고, 그 아래 있는 칩·패널이 **사실상 닿을 수 없는 곳**으로 밀린다.
 *  최근순이라 앞쪽이 거의 언제나 찾는 것이므로 앞을 자르고, 자른 사실과 전체 수를
 *  화면이 말한다(조용히 자르면 "산출물이 50건뿐"이라고 읽힌다). */
const HEAD_ROWS = 50;

// 탭 재진입에도 열어 둔 패널·불러온 목록·펼침 상태 유지 (모듈 스코프 규약)
let items = null;
let openDrawer = null;
let showAll = false;
// LLM 소견서 — 잡·결과 재진입 유지 (시뮬 탭 draftJobId와 같은 규약)
let briefJobId = null;
let lastBrief = null;

export function render() {
  const listBox = el("div", { class: "tab-sheet" });
  const summaryBox = el("div");
  const errBox = el("div");
  const statusLine = el("p", { class: "tab-status" });

  // ── LLM 소견서 — 행의 [브리핑]이 시작하고 결과는 「브리핑」 패널에 산다 ────
  // 판단 로직 없음(표시 조립뿐)이라 lib 없이 여기 둔다. 서버 계약·가지치기는
  // routes/llm.py·brief.py + 테스트가 정본.
  const briefProgressBox = el("div");
  const briefErrBox = el("div");
  const briefBox = el("div");
  let llm = null; // GET /llm/status — 이 render 안에서 한 번 (재진입 시 재조회)

  const paintBrief = () => {
    clear(briefBox);
    if (!lastBrief) {
      briefBox.append(el("p", { class: "hint" },
        "아직 소견서가 없습니다 — 목록 행의 [브리핑]을 누르면 그 결과의 소견서가 "
        + "생성돼 여기 열립니다. 버튼이 꺼져 있으면 버튼 설명(title)이 사유를 "
        + "말합니다 (키 없는 배포에서는 꺼진 것이 정상)."));
      return;
    }
    const b = lastBrief;
    briefBox.append(
      el("h2", {}, b.headline || "(제목 없음)"),
      el("p", { class: "hint", style: "margin:0 0 8px" },
        `대상 ${b.parent} — ${kindLabel(b.parent_kind)}`,
        b.model ? ` · ${b.model}` : ""),
      // body는 자유 서술이라 빈 줄로 문단을 가른다 — 통짜 <p>는 벽이 된다
      ...String(b.body || "").split(/\n{2,}/).map((par) =>
        el("p", { style: "max-width:96ch" }, par)),
      b.look_at?.length
        ? el("div", {},
            el("p", { class: "hint", style: "margin:8px 0 4px" }, "어디부터 볼까"),
            el("ul", { class: "hint" }, b.look_at.map((t) => el("li", {}, t))))
        : null,
    );
  };

  const watchBrief = () => attachProgress(briefProgressBox, briefJobId, {
    onDone: async (job) => {
      briefJobId = null;
      paintList(); // 행 버튼이 다시 켜진다
      try {
        if (job.status === "error") throw new Error(job.error);
        if (cancelledWithoutResult(job)) {
          clear(briefErrBox).append(el("div", { class: "error-box" },
            "취소됨 — 저장된 소견서 없음"));
          return;
        }
        lastBrief = await api.get(`/results/${job.result_id}`);
        paintBrief();
        drawers.open("brief"); // 결과가 사는 패널을 열어 준다 (전 탭 규약)
        load(); // 목록에도 「소견서 (LLM)」 행이 선다
      } catch (e) {
        clear(briefErrBox).append(el("div", { class: "error-box" }, errorText(e)));
      }
    },
    onError: (e) => {
      briefJobId = null;
      paintList();
      clear(briefErrBox).append(el("div", { class: "error-box" }, errorText(e)));
    },
  });

  // await 앞의 동기 플래그 — briefJobId만 보면 POST 왕복 사이의 더블클릭이
  // 유료 잡을 두 번 만든다 (리뷰 지적: 워처가 첫 잡을 고아로 만들고 둘 다 과금)
  let briefSubmitting = false;
  const onBrief = async (id) => {
    if (briefJobId || briefSubmitting) return; // 버튼이 이미 꺼져 있다 — 방어만
    briefSubmitting = true;
    try {
      clear(briefErrBox);
      const submitted = await api.post("/llm/brief", { result_id: id });
      briefJobId = submitted.id;
      paintList();
      drawers.open("brief"); // 진행이 이 패널에 산다 — 누른 자리에서 보이게 바로 연다
      watchBrief();
    } catch (e) {
      drawers.open("brief");
      clear(briefErrBox).append(el("div", { class: "error-box" }, errorText(e)));
    } finally {
      briefSubmitting = false;
    }
  };

  const briefCtl = () => ({
    available: !!llm?.available,
    reason: llm == null ? "서버 LLM 상태 확인 중…" : llm.reason,
    busy: !!briefJobId || briefSubmitting,
    onBrief,
  });

  const loadLlm = async () => {
    try {
      llm = await api.get("/llm/status");
    } catch (e) {
      llm = { available: false, reason: `상태 조회 실패 — ${errorText(e)}` };
    }
    paintList(); // 버튼 활성·사유가 실제 상태를 말하게 다시 그린다
  };

  const drawers = createDrawers({
    id: "results-drawer",
    initial: openDrawer,
    onOpen: (k) => { openDrawer = k; },
    defs: [
      { key: "kinds", label: "종류별 요약", group: "보기",
        title: "무엇을 몇 건 냈나 — 단계별로 실측이 있는지",
        count: () => (items ? new Set(items.map((m) => m.kind)).size : null),
        build: () => summaryBox },
      { key: "brief", label: "브리핑", group: "보기",
        title: "고른 결과의 LLM 소견서 — 목록 행의 [브리핑]으로 생성한다",
        count: () => (lastBrief ? 1 : null),
        build: () => [briefProgressBox, briefErrBox, briefBox] },
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

  const paintList = () => {
    if (!items) return; // 목록보다 LLM 상태가 먼저 도착할 수 있다 (loadLlm 경로)
    renderList(listBox, items, showAll, () => {
      showAll = !showAll;
      paintList();
    }, briefCtl());
  };

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
  loadLlm();
  paintBrief(); // 재진입 — 마지막 소견서 복원
  if (briefJobId) watchBrief(); // 생성 중 재진입 — 진행 UI 재부착 (전 탭 규약)

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

/** [브리핑] 버튼 — 못 누르는 상태는 끄되 사유를 title로 낸다 (조용한 비활성 금지). */
function briefBtn(m, brief) {
  const isBrief = m.kind === "llm_brief";
  const disabled = isBrief || !brief.available || brief.busy;
  const title = isBrief ? "소견서에는 브리핑을 만들지 않습니다"
    : !brief.available ? (brief.reason ?? "사용할 수 없습니다")
    : brief.busy ? "브리핑이 이미 생성 중입니다 — 「브리핑」 패널에서 진행을 봅니다"
    : "이 결과의 소견서를 LLM으로 생성합니다";
  return el("button", { disabled, title, onclick: () => brief.onBrief(m.id) },
    "브리핑");
}

function renderList(box, list, all, onToggle, brief) {
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
      el("td", { style: "white-space:nowrap" },
        el("a", { href: `/api/results/${m.id}`, target: "_blank" }, "원본 JSON"),
        " ", briefBtn(m, brief)),
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
