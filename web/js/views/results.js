/** 결과 뷰 (02 §8 12단계 열람) — 저장 산출물 목록(메타)·브리핑·원본 조회.

검증 리포트 생성(M12)은 엔진 구축 대기 — 여기서는 산출물 계보(지문) 열람까지.

배치는 다른 탭과 같은 규약(views/stage.js): **목록이 전면**이고 브리핑·종류별
요약·저장 구조 설명은 패널이다. 결과 하나를 여는 길은 [브리핑]이 먼저다 —
정해진 양식(머리·종합 판정·절)이 본문에서 계산으로 즉시 서고(lib/resultbrief.js),
원본 JSON은 그 안의 접기(옵션)다. LLM 소견서는 별도 패널(키 필요·자유 서술).
*/

import { lineageText } from "../lib/lineage.js";
import { resultFreshness } from "../lib/freshness.js";
import { briefModel, jsonPreview, kindLabel } from "../lib/resultbrief.js";
import { STATUS } from "../lib/plot.js";
import { api, errorText } from "../api.js";
import { clear, el } from "../dom.js";
import { attachProgress, cancelledWithoutResult } from "./progress.js";
import { createDrawers, tabStage, tabTop } from "./stage.js";

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
// 브리핑 — 마지막으로 연 결과의 결정적 요약 {meta, model, preview} (재진입 유지)
let lastView = null;
let profileRows = null; // GET /profiles — 결과 신선도 대조용(lib/freshness.js). 못 받으면 판정하지 않는다
let viewSeq = 0; // 늦게 온 옛 본문이 새로 고른 결과의 브리핑을 덮지 않게
// 탭을 열면 최신 결과의 브리핑이 자동으로 선다 — 세션에 한 번, 이미 보던 브리핑·열어 둔
// 패널이 있으면 끼어들지 않는다 (기체 탭 목록 자동 열림과 같은 규약)
let briefAutoOpened = false;
// LLM 소견서 — 잡·결과 재진입 유지 (시뮬 탭 draftJobId와 같은 규약)
let opinionJobId = null;
let lastOpinion = null;

export function render() {
  const listBox = el("div", { class: "tab-sheet" });
  const summaryBox = el("div");
  const errBox = el("div");
  const statusLine = el("p", { class: "tab-status" });

  // ── 브리핑 — 행의 [브리핑]이 연다. 정해진 양식의 결정적 요약(lib/resultbrief.js),
  //    원본 JSON은 그 안의 접기다 (사용자 제기: "브리핑부터, JSON은 옵션으로")
  const briefBox = el("div");

  const paintBriefDoc = () => {
    clear(briefBox);
    if (!lastView) {
      briefBox.append(el("p", { class: "hint" },
        "목록 행의 [브리핑]을 누르면 그 결과의 요약이 정해진 양식(머리·종합 판정·절)으로 "
        + "여기 섭니다 — 원본 JSON은 맨 아래 접기에서 폅니다."));
      return;
    }
    if (lastView.loading) {
      briefBox.append(el("p", { class: "hint" }, `본문 불러오는 중… (${lastView.id})`));
      return;
    }
    if (lastView.error) {
      briefBox.append(el("div", { class: "error-box" }, lastView.error));
      return;
    }
    // 이 paint의 view를 스냅숏으로 잡는다 — 클로저가 모듈 lastView를 잡으면 옛 details의
    // 늦은 toggle이 **새** 결과의 캐시를 건드릴 수 있다. view에만 쓰면 구조적으로 옳다(리뷰 지적)
    const view = lastView;
    const { model, id } = view;
    // 신선도 — 계산 시점 지문과 지금 목록 대조. 낡음은 눈에 띄게(이 결과로 지금 기체를 판단하면
    // 틀린다), 기체 없음은 정보로, 신선·판정 불가는 조용히
    const fresh = resultFreshness(view.meta?.profile, profileRows);
    const toneColor = { ok: STATUS.ok, warn: STATUS.warn, bad: STATUS.bad, na: STATUS.na };
    // 원본 JSON은 **펼칠 때 처음** 문자열화한다 — 시뮬 본문(전 해상도, 수 MB)을 브리핑을
    // 열 때마다 만들면 대부분 버려지는 수십 MB 문자열이 매번 생긴다(리뷰 지적).
    // 한 번 만든 것은 view에 남아 재진입·재펼침에 다시 만들지 않는다
    const summaryText = (p) => (p
      ? `원본 JSON — ${Math.max(1, Math.round(p.chars / 1024)).toLocaleString()} KB`
        + (p.truncated ? " (상한 앞부분만 — 전량은 아래 새 탭 링크)" : "")
      : "원본 JSON 펼치기 (펼칠 때 문자열화)");
    const jsonSummary = el("summary", {}, summaryText(view.preview));
    const jsonPre = el("pre", { style: "max-height:420px; overflow:auto; font-size:11px" },
      view.preview ? view.preview.text : "");
    const jsonFold = el("details", {
      style: "margin-top:12px",
      ontoggle: () => {
        if (!jsonFold.open || view.preview) return;
        view.preview = jsonPreview(view.body);
        clear(jsonSummary).append(summaryText(view.preview));
        clear(jsonPre).append(view.preview.text);
      },
    }, jsonSummary, jsonPre);
    // 네이티브 append에 null 직접 전달 금지 (문자열화 함정 — 판정 없는 브리핑마다
    // "null" 글자가 찍힌다, 리뷰 지적) — el 래핑으로 조립한다
    briefBox.append(el("div", {},
      el("h2", {}, model.title),
      el("table", { class: "num", style: "margin:4px 0 8px" }, el("tbody", {},
        model.head.map(([k, v]) => el("tr", {},
          el("td", { class: "hint", style: "padding-right:10px; white-space:nowrap" }, k),
          el("td", {}, v))))),
      fresh.state === "stale" ? el("p", { class: "error-box", style: "margin:0 0 8px" }, fresh.label) : null,
      fresh.state === "gone" || fresh.state === "unreadable"
        ? el("p", { class: "hint", style: "margin:0 0 8px" }, fresh.label) : null,
      model.verdict
        ? el("p", { style: "margin:0 0 8px" },
            el("span", { class: "flag",
              style: `background:${toneColor[model.verdict.tone]}22; color:${toneColor[model.verdict.tone]}` },
              "종합"),
            " ", model.verdict.text)
        : null,
      ...model.sections.map((s) => el("div", { style: "margin-top:8px" },
        el("h3", { style: "font-size:13px; margin:0 0 4px" }, s.title),
        s.rows ? el("div", { class: "scroll-x" }, el("table", {}, el("tbody", {},
          s.rows.map(([k, v]) => el("tr", {},
            el("td", { style: "padding-right:10px; white-space:nowrap" }, k),
            el("td", {}, v))))))
          : el("div", {}, (s.lines ?? []).map((t) => el("p", { style: "max-width:96ch; margin:4px 0" }, t))))),
      jsonFold,
      el("p", { class: "hint", style: "margin-top:6px" },
        el("a", { href: `/api/results/${id}`, target: "_blank" }, "원본 JSON (새 탭)"),
        " — 다른 탭이 이 결과를 되읽는 바로 그 본문이다."),
    ));
  };

  const onView = async (m) => {
    const my = ++viewSeq;
    lastView = { id: m.id, meta: m, loading: true }; // meta 보관 — 로딩 중 재진입이 다시 건다
    paintBriefDoc();
    drawers.open("brief"); // 결과가 사는 패널을 열어 준다 (전 탭 규약)
    try {
      const body = await api.get(`/results/${m.id}`);
      if (my !== viewSeq) return; // 그사이 다른 행을 열었다
      lastView = { id: m.id, meta: m, model: briefModel(m, body), body, preview: null };
    } catch (e) {
      if (my !== viewSeq) return;
      lastView = { id: m.id, error: errorText(e) };
    }
    paintBriefDoc();
    drawers.refresh(); // 「브리핑」 칩 배지
  };

  // ── LLM 소견서 — 행의 [소견서]가 시작하고 결과는 「소견서 (LLM)」 패널에 산다 ──
  // 판단 로직 없음(표시 조립뿐)이라 lib 없이 여기 둔다. 서버 계약·가지치기는
  // routes/llm.py·brief.py + 테스트가 정본.
  const opinionProgressBox = el("div");
  const opinionErrBox = el("div");
  const opinionBox = el("div");
  let llm = null; // GET /llm/status — 이 render 안에서 한 번 (재진입 시 재조회)

  const paintOpinion = () => {
    clear(opinionBox);
    if (!lastOpinion) {
      opinionBox.append(el("p", { class: "hint" },
        "아직 소견서가 없습니다 — 목록 행의 [소견서]를 누르면 그 결과의 소견서가 "
        + "LLM으로 생성돼 여기 열립니다. 버튼이 꺼져 있으면 버튼 설명(title)이 사유를 "
        + "말합니다 (키 없는 배포에서는 꺼진 것이 정상)."));
      return;
    }
    const b = lastOpinion;
    opinionBox.append(
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

  const watchOpinion = () => attachProgress(opinionProgressBox, opinionJobId, {
    onDone: async (job) => {
      opinionJobId = null;
      paintList(); // 행 버튼이 다시 켜진다
      try {
        if (job.status === "error") throw new Error(job.error);
        if (cancelledWithoutResult(job)) {
          clear(opinionErrBox).append(el("div", { class: "error-box" },
            "취소됨 — 저장된 소견서 없음"));
          return;
        }
        lastOpinion = await api.get(`/results/${job.result_id}`);
        paintOpinion();
        drawers.open("opinion"); // 결과가 사는 패널을 열어 준다 (전 탭 규약)
        load(); // 목록에도 「소견서 (LLM)」 행이 선다
      } catch (e) {
        clear(opinionErrBox).append(el("div", { class: "error-box" }, errorText(e)));
      }
    },
    onError: (e) => {
      opinionJobId = null;
      paintList();
      clear(opinionErrBox).append(el("div", { class: "error-box" }, errorText(e)));
    },
  });

  // await 앞의 동기 플래그 — opinionJobId만 보면 POST 왕복 사이의 더블클릭이
  // 유료 잡을 두 번 만든다 (리뷰 지적: 워처가 첫 잡을 고아로 만들고 둘 다 과금)
  let opinionSubmitting = false;
  const onOpinion = async (id) => {
    if (opinionJobId || opinionSubmitting) return; // 버튼이 이미 꺼져 있다 — 방어만
    opinionSubmitting = true;
    try {
      clear(opinionErrBox);
      const submitted = await api.post("/llm/brief", { result_id: id });
      opinionJobId = submitted.id;
      paintList();
      drawers.open("opinion"); // 진행이 이 패널에 산다 — 누른 자리에서 보이게 바로 연다
      watchOpinion();
    } catch (e) {
      drawers.open("opinion");
      clear(opinionErrBox).append(el("div", { class: "error-box" }, errorText(e)));
    } finally {
      opinionSubmitting = false;
    }
  };

  const opinionCtl = () => ({
    available: !!llm?.available,
    reason: llm == null ? "서버 LLM 상태 확인 중…" : llm.reason,
    busy: !!opinionJobId || opinionSubmitting,
    onOpinion,
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
      { key: "brief", label: "브리핑", group: "보기",
        title: "고른 결과의 요약 — 정해진 양식(머리·종합 판정·절), 원본 JSON은 안의 접기",
        count: () => (lastView && !lastView.loading && !lastView.error ? 1 : null),
        build: () => briefBox },
      { key: "kinds", label: "종류별 요약", group: "보기",
        title: "무엇을 몇 건 냈나 — 단계별로 실측이 있는지",
        count: () => (items ? new Set(items.map((m) => m.kind)).size : null),
        build: () => summaryBox },
      { key: "opinion", label: "소견서 (LLM)", group: "보기",
        title: "고른 결과의 LLM 소견서(자유 서술·키 필요) — 목록 행의 [소견서]로 생성한다",
        count: () => (lastOpinion ? 1 : null),
        build: () => [opinionProgressBox, opinionErrBox, opinionBox] },
      { key: "about", label: "저장 구조·지문", group: "설명",
        build: () => [
          el("h2", {}, "본문/메타 분리 저장소"),
          el("p", { class: "hint", style: "max-width:96ch" },
            "목록에 뜨는 것은 메타뿐이고 본문(케이스·신호·판정)은 따로 저장된다 — ",
            "그래서 이 표는 산출물이 아무리 커도 즉시 뜬다. 행의 [브리핑]이 그 본문을 ",
            "정형 요약으로 열고, 원본 JSON(다른 탭이 되읽는 그 본문)은 브리핑 안의 ",
            "접기·새 탭 링크다."),
          el("p", { class: "hint", style: "max-width:96ch" },
            "지문(fingerprint)은 산출물 계보 키 (02 §2.4) — ",
            el("b", {}, "현재 클라이언트 자기신고"),
            "다. 같은 지문이 곧 같은 형상이라는 보장이 아직 없다는 뜻이고, ",
            "파라미터 관리 계층(02 §5.5) 결선 시 엔진 발급으로 전환 예정이다. ",
            "탑재 C 검증 결과는 엔진이 발급한 지문 둘을 싣는다(v1.12) — 구조 지문(생성 C가 바이트 동일한가)과 ",
            "파라미터 지문(장입 이미지의 값). 그 전 결과의 단일 지문은 「구 형상 지문」으로 표시한다."),
        ] },
    ],
  });

  const paintList = () => {
    if (!items) return; // 목록보다 LLM 상태가 먼저 도착할 수 있다 (loadLlm 경로)
    renderList(listBox, items, showAll, () => {
      showAll = !showAll;
      paintList();
    }, opinionCtl(), onView, profileRows);
  };

  const load = async () => {
    try {
      clear(errBox);
      statusLine.textContent = "불러오는 중…";
      const [res, rows] = await Promise.all([
        api.get("/results"),
        api.get("/profiles").catch(() => null), // 신선도 대조용 — 실패는 판정 불가(unknown)로 조용히
      ]);
      items = res;
      profileRows = rows;
      statusLine.textContent = items.length
        ? `${items.length}건 · 최근순`
        : "";
      // 신선도 대조는 기체 목록이 재료다 — 못 받았으면 "전부 신선"처럼 보이게 두지 않고 그 사실을
      // 말한다(조용한 실패 금지 — 결과별 unknown이 조용한 것과 층이 다르다: 이건 열 전체의 측정 실패)
      if (profileRows === null && items.length) {
        statusLine.textContent += " · 신선도 대조 불가(기체 목록 조회 실패 — 낡음 표시가 빠져 있을 수 있음)";
      }
      paintList();
      renderSummary(summaryBox, items);
      drawers.refresh();
      // 최신 결과의 브리핑을 바로 세운다 (사용자 제기 "누르지 않아도 기본으로") —
      // 목록이 최근순이라 [0]이 최신이다. 소견서(LLM) 결과가 최신이어도 그대로 연다:
      // 그 브리핑은 소견 본문을 보여 주므로 "최신 산출물"이라는 답에 맞다
      if (items.length && !lastView && !openDrawer && !briefAutoOpened) {
        briefAutoOpened = true;
        onView(items[0]);
      }
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
  // 재진입 — 마지막 브리핑 복원. 로딩 중에 떠났다 왔으면 다시 건다: 진행 중이던 옛
  // render의 continuation은 분리된 옛 DOM만 갱신해 화면이 「불러오는 중」에 멈춘다
  // (viewSeq가 올라가 옛 응답은 버려진다 — 소견서의 watchOpinion 재부착과 같은 규약)
  if (lastView?.loading && lastView.meta) onView(lastView.meta);
  else paintBriefDoc();
  paintOpinion(); // 재진입 — 마지막 소견서 복원
  if (opinionJobId) watchOpinion(); // 생성 중 재진입 — 진행 UI 재부착 (전 탭 규약)

  return el("div", { class: "tab-page" },
    tabTop({
      title: "결과",
      lead: "이 도구가 지금까지 낸 산출물 전부 — 탭을 열면 최신 결과의 브리핑이 "
        + "정해진 양식으로 바로 서고, 다른 결과는 행의 [브리핑]으로 연다. "
        + "원본 JSON은 브리핑 안의 접기다.",
      actions: [el("button", { onclick: load }, "새로고침")],
      extra: [statusLine, errBox],
    }),
    tabStage(listBox),
    drawers.root,
  );
}

/** [소견서] 버튼 — 못 누르는 상태는 끄되 사유를 title로 낸다 (조용한 비활성 금지). */
function opinionBtn(m, opinion) {
  const isBrief = m.kind === "llm_brief";
  const disabled = isBrief || !opinion.available || opinion.busy;
  const title = isBrief ? "소견서에는 소견서를 만들지 않습니다"
    : !opinion.available ? (opinion.reason ?? "사용할 수 없습니다")
    : opinion.busy ? "소견서가 이미 생성 중입니다 — 「소견서 (LLM)」 패널에서 진행을 봅니다"
    : "이 결과의 소견서를 LLM으로 생성합니다 (자유 서술 — 정형 요약은 [브리핑])";
  return el("button", { disabled, title, onclick: () => opinion.onOpinion(m.id) },
    "소견서");
}

function renderList(box, list, all, onToggle, opinion, onView, rows) {
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
      el("th", {}, "생성 시각"), el("th", {}, "종류"), el("th", {}, "기체"), el("th", {}, "id"),
      el("th", {}, "건수"), el("th", {}, "지문(계보)"), el("th", {}, ""))),
    el("tbody", {}, shown.map((m) => el("tr", {},
      el("td", {}, m.created ? new Date(m.created * 1000).toLocaleString() : "—"),
      el("td", {}, kindLabel(m.kind),
        // 코드도 함께 낸다 — 우리말 이름만 내면 API·다른 화면과 대조가 안 된다
        el("span", { class: "hint", style: "margin-left:6px" }, m.kind ?? "")),
      el("td", {}, aircraftCell(m.profile), freshnessChip(m.profile, rows)),
      el("td", { class: "num" }, m.id),
      el("td", { class: "num" }, m.n ?? "—"),
      el("td", { class: "num" }, lineageText(m)),
      el("td", { style: "white-space:nowrap" },
        // 브리핑이 먼저다 — 정형 요약이 즉시 서고, 원본 JSON은 그 안의 접기(옵션)다
        el("button", { class: "primary", title: "정해진 양식의 요약 — 원본 JSON은 안의 접기",
          onclick: () => onView(m) }, "브리핑"),
        " ", opinionBtn(m, opinion)),
    ))),
  ))));
}

/** 신선도 칩 — 계산 시점 지문과 지금 목록의 지문 대조(lib/freshness.js). 신선·판정 불가는 조용하다. */
function freshnessChip(p, rows) {
  const f = resultFreshness(p, rows);
  if (f.state === "stale") {
    return el("span", { class: "flag bad", style: "margin-left:6px", title: f.label }, "낡음");
  }
  if (f.state === "gone") {
    return el("span", { class: "flag na", style: "margin-left:6px", title: f.label }, "기체 없음");
  }
  if (f.state === "unreadable") {
    return el("span", { class: "flag na", style: "margin-left:6px", title: f.label }, "읽을 수 없음");
  }
  return null;
}

/** 그 결과를 계산한 기체 — 결과 meta의 profile 블록(02 §5.6). 지금 헤더에서 고른 기체가 아니다.
 *  블록이 없으면 기체 선택이 생기기 전(v1.03 이전)의 결과이거나 기체와 무관한 산출물(LLM 등)이다. */
function aircraftCell(p) {
  if (!p) {
    return el("span", { class: "hint",
      title: "기체 기록 없음 — v1.03 이전 결과(그때는 예제 기체뿐이었다)이거나 기체와 무관한 산출물" }, "—");
  }
  return el("span", {
    title: `${p.id}${p.variant ? ` / ${p.variant}` : ""} · 리비전 ${p.revision ?? "—"} · 지문 ${p.fingerprint}`
      + ` · 출처 ${p.source ?? "—"}`,
  }, p.name ?? p.id, p.variant ? ` · ${p.variant}` : "",
  p.is_example ? el("span", { class: "hint", style: "margin-left:6px" }, "예제") : null,
  // 초기 탐색 게인으로 계산한 결과 — 자동 설계 전 게인이라는 사실을 결과와 함께 보인다(서버가 그때만 싣는다)
  p.design_source === "quick_seed"
    ? el("span", { class: "hint", style: "margin-left:6px", title: "초기 게인 빠른 탐색이 채운 게인 — 자동 설계 전" },
      "초기 탐색 게인") : null);
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
