/** 트림 뷰 (02 §8 3단계) — 격자 → 배치 실행 → 비행 가능 영역.

이 탭의 답은 표가 아니라 **지도**다: "이 격자에서 어디가 날 수 있고 어디가 안 되나."
그래서 비행 엔벨로프 맵이 카드 밖 전면에 놓이고(블록도 최상위·영향성과 같은 규약,
views/stage.js), 격자 조건·케이스 목록·케이스별 수치는 패널에 들어간다.

DOM 조립 전용 (얇게) — 격자 로직은 lib/grid.js, 수치·판정은 전부 서버(엔진) 산출.

격자는 이 탭이 만들지 않는다 — 서버 `POST /grid/base`(엔진 claw.opspace)가 요구 운용영역에서 **공통 마하 좌표
기본 격자**를 내고(05 §11.11), 이 탭은 그중 트림할 점(미계산)을 케이스로 받는다. 모델 부족 점은 트림하지 않고 지도에
그 상태로 남는다. 탭에 처음 들어오면 격자를 자동으로 받는다 — 빈 케이스 목록으로 시작하지 않는다.
지도의 칸은 조건 상태(05 §11.3 — 계산 가능 · 물리적 불가 · 제약 도달·미수렴 · 계산 실패 · 모델 부족)다.

쇼케이스 진행기 신호(lib/showcasecue.js): run() — 요구영역의 기본 격자 명세로 격자를 다시 받고 [배치 실행]과 같은
길로 돌린 뒤, 상태별 개수(지도 범례와 같은 라벨)를 보고한다.
*/

import { ApiError, api, errorText } from "../api.js";
import { clear, el, flagBadge, fmt } from "../dom.js";
import {
  PRE_STATE_LABEL, casesFromBaseGrid, gridMapEntries, parseGridSpec, regionLines, stateCountText, untrimmedSummary,
} from "../lib/opspace.js";
import {
  SERIES_COLORS, STATUS, TRIM_CELL_LABEL, TRIM_FLAG_LABEL, TRIM_STATE_CELL, fuelsOf, pctText, pivotCases,
  stateReasonText, trimCueReport, trimCurves, trimEnvelopeCell, trimFlagSummary,
} from "../lib/plot.js";
import { revealPanel } from "../lib/reveal.js";
import { failCue, reportCue, takeCue, unknownAction } from "../lib/showcasecue.js";
import { heatmapCanvas, lineChartCanvas, stateMapCanvas } from "./plots.js";
import { attachProgress, cancelledWithoutResult } from "./progress.js";
import { createDrawers, tabStage, tabTop } from "./stage.js";

// 신호 실패 사유 — 서버 오류는 errorText(422 배열·엔진 detail을 사람 글로), 그 밖은 메시지만("Error: " 접두 없이)
const cueReason = (e) => (e instanceof ApiError ? errorText(e) : (e?.message ?? String(e)));

// 모듈 상태 — 탭 재진입 시 유지 (실행 중 작업 재부착 포함, 리뷰 S4)
let cases = [];
let baseGrid = null; // 마지막으로 받은 기본 격자 응답(서버 /grid/base) — 요구영역 요약·모델 부족 점·[행 추가]의 근거
let gridSeq = 0; // 격자 요청 차례 — 늦게 온 옛 응답이 새 응답을 덮지 않게(같은 방문 안의 경쟁)
let gridAuto = false; // 지금 케이스가 요구영역의 기본 명세로 받은 그대로인가 — 재진입 때 문서가 바뀌었으면 다시 받는다
let lastBody = null;
let runningJobId = null;
let runningFp = "";
let openDrawer = null;
let trimCue = null; // 배치를 건 진행기 신호 — 잡이 끝나면 한 번 보고하고 지운다 (감시자가 둘이어도 한 번)
let trimVisit = 0; // 탭을 그린 차례 — 떠난 방문의 늦은 신호 처리가 지금 화면의 칸·케이스를 덮지 않게
// 배치가 이미 도는 중일 때의 사유 — [배치 실행]과 신호가 같은 문장을 낸다
const BUSY_REASON = "이미 실행 중인 배치가 있다 — 끝난 뒤 다시 건다";

// 판정 플래그 열 — 라벨은 lib 한 표(머리줄·쇼케이스 보고가 같은 말을 쓴다)
const FLAG_COLS = Object.entries(TRIM_FLAG_LABEL);

export function render() {
  const visit = ++trimVisit;
  const caseBox = el("div");
  const progressBox = el("div");
  const mapBox = el("div");     // 전면 — 비행 엔벨로프 맵
  const tableBox = el("div");   // 패널 — 케이스별 수치·판정
  const curvesBox = el("div");  // 패널 — 트림 곡선 (α·스로틀·δe vs 마하)
  const errBox = el("div");
  const summaryLine = el("p", { class: "tab-status" });

  // 기본 격자 명세 — 빈 칸이면 요구 운용영역의 명세(기체 문서 operating_region.base_grid, 없으면 trim_grid 초안)를
  // 서버가 쓴다. 칸에 값을 적으면 그 값으로 다시 받는다. 좌표 규칙(공통 마하 좌표 + 행 끝점)은 엔진 한 곳이다
  const fNMach = el("input", { class: "num", placeholder: "영역 명세" });
  const fAlts = el("input", { placeholder: "영역 명세" });
  const fFuels = el("input", { placeholder: "영역 명세" });
  const fFp = el("input", { value: "web-trim-v1" });
  const gridHint = el("p", { class: "hint" });
  const regionBox = el("div");

  // 실행 버튼은 **전면**이다 — 격자를 고치는 패널 안에만 있으면 패널을 닫는 순간
  // 실행할 방법이 사라진다. 라벨이 케이스 수를 들고 있어 상태 표시도 겸한다
  const runBtn = el("button", { class: "primary" }, "배치 실행");
  const syncRunBtn = () => {
    runBtn.disabled = !cases.length || !!runningJobId; // 이중 제출 방지 (리뷰 S4)
    clear(runBtn).append(runningJobId ? "실행 중…" : `배치 실행 (${cases.length}케이스)`);
  };
  runBtn.onclick = () => runBatch();

  // 기본 격자 받기 → 케이스 — 받았으면 null, 못 받았으면 사유 (신호 경로가 옛 케이스로 돌지 않게).
  // fromRegion: 칸을 무시하고 요구영역의 기본 명세로 받는다(첫 진입·신호). 받는 사이 탭이 다시 그려졌으면 버린다
  const makeGrid = async ({ fromRegion = false } = {}) => {
    const seq = ++gridSeq;
    try {
      clear(errBox);
      const spec = fromRegion ? {} : parseGridSpec({ nMach: fNMach.value, alts: fAlts.value, fuels: fFuels.value });
      const body = await api.post("/grid/base", spec);
      if (visit !== trimVisit) return "격자를 받는 사이 탭이 다시 그려졌다";
      if (seq !== gridSeq) return "더 나중에 요청한 격자가 있다 — 이 응답은 버린다";
      // 받는 사이 배치가 걸렸으면 케이스를 덮지 않는다 — 도는 배치와 화면의 목록이 갈린다
      if (runningJobId) return BUSY_REASON;
      if (!body.region) {
        baseGrid = body;
        cases = [];
        repaintGrid();
        repaintCases();
        return body.reason;
      }
      baseGrid = body;
      cases = casesFromBaseGrid(body);
      gridAuto = fromRegion;
      repaintGrid();
      repaintCases();
      if (lastBody) renderResults(); // 모델 부족 칸이 새 격자를 따른다
      return null;
    } catch (e) {
      showError(errBox, e);
      return cueReason(e);
    }
  };

  // [행 추가]의 첫 값 — 지금 기본 격자의 트림 대상 점 가운데 하나. 특정 기체의 점을 코드에 적지 않는다
  const addRow = () => {
    const pool = casesFromBaseGrid(baseGrid);
    if (!pool.length) {
      showError(errBox, new Error("기본 격자가 없다 — 먼저 [격자 생성]으로 요구영역의 격자를 받는다"));
      return;
    }
    const { mach, alt, fuel } = pool[Math.floor((pool.length - 1) / 2)];
    cases.push({ mach, alt, fuel }); // 이름은 서버가 짓는다 — 손으로 고칠 값이라 격자 이름을 물려주지 않는다
    gridAuto = false;
    repaintCases();
  };

  const repaintGrid = () => renderRegion(regionBox, gridHint, baseGrid);

  const repaintCases = () => {
    renderCases(caseBox, cases, repaintCases, addRow);
    syncRunBtn();
    drawers.refresh();
  };

  // 배치 걸기 — 걸었으면 null, 못 걸었으면 사유. cue가 오면 잡이 끝날 때 그 신호로 보고한다
  const runBatch = async (cue = null) => {
    if (runningJobId) return BUSY_REASON;
    if (!cases.length) return "케이스가 없다 — 격자를 생성하거나 행을 추가한다";
    clear(errBox);
    runningFp = fFp.value;
    try {
      const submitted = await api.post("/trim/batch", { cases, fingerprint: runningFp });
      runningJobId = submitted.id;
      if (cue) {
        trimCue = cue;
        reportCue(cue, { phase: "started", jobId: submitted.id });
      }
      repaintCases(); // 버튼 비활성 반영
      watchTrim();
      return null;
    } catch (e) {
      showError(errBox, e);
      return cueReason(e);
    }
  };

  const watchTrim = () => attachProgress(progressBox, runningJobId, {
    onDone: async (job) => {
      runningJobId = null;
      repaintCases();
      // 신호는 한 번만 — 잡이 끝난 뒤의 보고는 store에만 쓰므로 떠난 화면이어도 보낸다
      const cue = trimCue;
      trimCue = null;
      try {
        if (job.status === "error") throw new Error(job.error);
        if (cancelledWithoutResult(job)) {
          showError(errBox, new Error("취소됨 — 저장된 결과 없음 (실행 전 취소)"));
          failCue(cue, "취소됨 — 저장된 결과 없음 (실행 전 취소)");
          return;
        }
        const body = await api.get(`/results/${job.result_id}`);
        lastBody = body;
        renderResults();
        drawers.open("rows"); // 수치가 사는 패널을 열어 준다
        if (cue) revealPanel(drawers.box); // 신호면 그 패널을 화면 안으로 — 청중이 표를 본다 (06 §2)
        if (job.status === "cancelled") {
          failCue(cue, `취소됨 — 완료분 ${body.results.length}케이스만 저장`);
          return;
        }
        reportCue(cue, { phase: "done", resultId: job.result_id,
          ...trimCueReport(body.results, untrimmedSummary(baseGrid)) });
      } catch (e) {
        showError(errBox, e);
        failCue(cue, cueReason(e));
      }
    },
    onError: (e) => {
      runningJobId = null;
      repaintCases();
      showError(errBox, e);
      const cue = trimCue;
      trimCue = null;
      failCue(cue, cueReason(e));
    },
  });

  const renderResults = () => {
    renderMap(mapBox, summaryLine, lastBody, baseGrid);
    renderRows(tableBox, lastBody);
    renderCurves(curvesBox, lastBody);
    drawers.refresh();
  };

  const drawers = createDrawers({
    id: "trim-drawer",
    initial: openDrawer,
    onOpen: (k) => { openDrawer = k; },
    defs: [
      { key: "grid", label: "운용영역·기본 격자", group: "입력",
        title: "요구 운용영역(기본 범위 + 경계표)과 거기서 만든 공통 마하 좌표 기본 격자",
        build: () => [
          el("h2", {}, "요구 운용영역 → 기본 모델 격자 (05 §11)"),
          regionBox,
          el("h3", { style: "font-size:13px; margin:12px 0 4px" }, "기본 격자 명세 — 빈 칸은 요구영역의 명세"),
          el("div", { class: "row" },
            el("label", { class: "field" }, "마하 점 수 (공통 좌표)", fNMach),
            el("label", { class: "field grow" }, "고도 목록 [m]", fAlts),
            el("label", { class: "field" }, "연료 목록 [kg]", fFuels),
            el("label", { class: "field" }, "지문(fingerprint)", fFp),
            el("button", { onclick: () => makeGrid() }, "격자 생성")),
          el("p", { class: "hint" },
            "요구영역 전체 마하를 등간격한 공통 좌표를 행(고도·연료)의 요구 범위로 거르고 행 끝점을 더한다 — ",
            "행마다 좌표가 같아 절점·검증점이 이 트림을 다시 쓴다. 실속·추력으로 행을 깎지 않는다: 날 수 없는 점은 ",
            "지도에 그 상태로 남는다. 행마다 마하 방향을 뒤집어 배치 트림의 인접 시드가 이어진다 (01 §4.1)."),
        ] },
      { key: "cases", label: "케이스 목록", group: "입력",
        title: "격자가 낸 케이스 — 손으로 더하거나 지울 수 있다",
        count: () => cases.length,
        build: () => [el("h2", {}, "케이스 목록"), caseBox] },
      { key: "rows", label: "케이스별 수치·판정", group: "결과",
        title: "θ·δe·스로틀과 판정 플래그 4종",
        count: () => (lastBody ? lastBody.results.length : null),
        build: () => [el("h2", {}, "결과 — 케이스별 트림 해와 판정"), tableBox] },
      { key: "curves", label: "트림 곡선", group: "결과",
        title: "α(=θ)·스로틀·δe — 마하에 따른 곡선, 고도별 색, 연료별 한 장",
        build: () => [el("h2", {}, "트림 곡선 — 조건(마하·고도·연료)에 따른 트림 해"), curvesBox] },
    ],
  });

  repaintCases();
  repaintGrid();
  if (lastBody) renderResults();
  else {
    renderMap(mapBox, summaryLine, null);
    renderRows(tableBox, null);
    renderCurves(curvesBox, null);
  }
  if (runningJobId) watchTrim(); // 재부착
  // 첫 진입 — 빈 케이스 목록으로 시작하지 않는다(종전: [격자 생성]을 누르기 전까지 0케이스). 신호가 오면 신호가 받는다
  const cue = takeCue("trim");
  // 재진입 — 케이스가 요구영역 명세 그대로면 다시 받는다: 그사이 기체 탭에서 요구영역을 고쳤으면(새 리비전, 새로고침
  // 없음) 옛 영역을 「확정」으로 보이지 않게. 손으로 고친 목록·다른 명세로 받은 목록은 둔다
  if (!cue && (!cases.length || gridAuto) && !runningJobId) makeGrid({ fromRegion: true }).then((err) => {
    if (err && visit === trimVisit) clear(errBox).append(el("div", { class: "error-box" }, err));
  });

  // 쇼케이스 신호 — 요구영역의 기본 명세로 격자를 다시 받고 [배치 실행]과 같은 길로. 요구영역이 없으면 사유를 단다
  const handleCue = async (c) => {
    try {
      if (c.action !== "run") {
        unknownAction(c);
        return;
      }
      // 케이스를 덮기 **전에** 거른다 — 덮은 뒤 runBatch가 거절하면 사용자가 돌리던 케이스만 잃는다
      if (runningJobId) throw new Error(BUSY_REASON);
      const err = await makeGrid({ fromRegion: true });
      if (err) throw new Error(err);
      if (visit !== trimVisit) throw new Error("신호를 처리하기 전에 탭이 다시 그려졌다");
      if (runningJobId) throw new Error(BUSY_REASON);
      const runErr = await runBatch(c); // 끝 보고는 잡 감시(watchTrim)가 한다
      if (runErr) throw new Error(runErr);
    } catch (e) {
      failCue(c, cueReason(e));
    }
  };
  if (cue) handleCue(cue);

  return el("div", { class: "tab-page" },
    tabTop({
      title: "트림",
      lead: "격자의 점마다 평형해를 푼다 — 그 판정이 곧 «어디를 날 수 있나»의 답이고, "
        + "다음 단계(선형화·마진)는 여기서 수렴한 점 위에서만 성립한다.",
      actions: [runBtn, el("button", { onclick: () => makeGrid() }, "격자 생성")],
      extra: [summaryLine, gridHint, progressBox, errBox],
    }),
    // 비행 엔벨로프 맵 — 카드 밖, 페이지 위에 그대로 (캔버스가 자기 테두리를 갖는다)
    tabStage(mapBox),
    drawers.root,
  );
}

/** 요구 운용영역 요약 + 기본 격자 행 목록. 계산하지 못한 것이 사라지지 않게 요구 미정의 행·모델 부족 점을 센다
 *  (05 §11.8). 미확정 초안이면 머리줄 안내(hint)도 그렇다고 말한다 — 패널을 닫아도 보이게. */
function renderRegion(box, hint, grid) {
  clear(box);
  hint.textContent = "";
  if (!grid) {
    box.append(el("p", { class: "hint" }, "요구 운용영역을 받는 중…"));
    return;
  }
  if (!grid.region) {
    box.append(el("div", { class: "error-box" }, grid.reason));
    hint.textContent = grid.reason;
    return;
  }
  const r = regionLines(grid.region, grid.model);
  if (!grid.region.confirmed) hint.textContent = `요구 운용영역: ${r.status}`;
  box.append(
    el("div", { class: grid.region.confirmed ? "notice" : "error-box" }, r.status),
    el("p", {}, el("strong", {}, "기본 범위 "), r.range),
    el("p", {}, el("strong", {}, "모델 유효영역 "), r.model,
      el("span", { class: "hint" }, " — 요구가 이보다 넓으면 줄이지 않고 「모델 부족」으로 남긴다")),
    r.boundary.length
      ? el("div", { class: "scroll-x" }, el("table", {},
        el("thead", {}, el("tr", {}, el("th", {}, "연료 층 [kg]"), el("th", {}, "고도 [m]"),
          el("th", {}, "마하 하한"), el("th", {}, "마하 상한"))),
        el("tbody", {}, r.boundary.map((b) => el("tr", {},
          el("td", { class: "num" }, fmt(b.fuel)), el("td", { class: "num" }, fmt(b.alt)),
          el("td", { class: "num" }, fmt(b.lo)), el("td", { class: "num" }, fmt(b.hi)))))))
      : el("p", { class: "hint" }, "경계표 없음 — 모든 행이 기본 범위의 마하를 쓴다."),
    el("p", { class: "hint" }, "경계표 행 사이·연료 층 사이는 선형 보간이고, 표가 덮지 않는 조건은 「요구 미정의」다 ",
      "(가까운 행으로 늘리지 않는다). 요구영역은 기체 탭 문서 패널의 JSON `operating_region`에서 고친다."),
    el("p", {}, el("strong", {}, "기본 격자 "), `${grid.points.length}점 — ${stateCountText(grid.counts, grid.labels)}`,
      el("span", { class: "hint" }, ` · 공통 마하 좌표 ${grid.axis.length}점`)),
    el("div", { class: "scroll-x" }, el("table", {},
      el("thead", {}, el("tr", {}, el("th", {}, "고도 [m]"), el("th", {}, "연료 [kg]"), el("th", {}, "요구 마하"),
        el("th", {}, "점"), el("th", {}, "상태"))),
      el("tbody", {}, grid.rows.map((row) => el("tr", {},
        el("td", { class: "num" }, fmt(row.alt)), el("td", { class: "num" }, fmt(row.fuel)),
        el("td", { class: "num" }, row.bounds ? `${fmt(row.bounds[0], 4)}–${fmt(row.bounds[1], 4)}` : "—"),
        el("td", { class: "num" }, row.n),
        el("td", {}, row.state === "not_run" ? "" : (grid.labels?.[row.state] ?? row.state))))))),
  );
}

function renderCases(caseBox, list, repaint, addRow) {
  clear(caseBox);
  if (!list.length) {
    caseBox.append(el("p", { class: "hint" }, "격자를 생성하거나 행을 추가하세요."));
  } else {
    caseBox.append(el("div", { class: "scroll-x" }, el("table", {},
      el("thead", {}, el("tr", {},
        el("th", {}, "#"), el("th", {}, "마하"), el("th", {}, "고도 [m]"),
        el("th", {}, "연료 [kg]"), el("th", {}, ""))),
      el("tbody", {}, list.map((c, i) => el("tr", {},
        el("td", {}, i + 1),
        el("td", { class: "num" }, fmt(c.mach)),
        el("td", { class: "num" }, fmt(c.alt)),
        el("td", { class: "num" }, fmt(c.fuel)),
        el("td", {}, el("button", {
          class: "danger",
          onclick: () => { list.splice(i, 1); gridAuto = false; repaint(); }, // 손으로 고친 목록 — 재진입이 덮지 않는다
        }, "삭제")),
      ))),
    )));
  }
  caseBox.append(el("div", { class: "row" },
    el("button", { onclick: addRow, title: "지금 격자의 가운데 점을 한 줄 더한다 — 값은 표에서 고친다" },
      "행 추가"),
  ));
}

/** 전면 무대 — 비행 엔벨로프 맵. 결과가 없으면 **무엇이 여기 그려질지**를 말한다
 *  (빈 화면은 "고장"과 "아직 안 함"을 구분해 주지 않는다). */
function renderMap(mapBox, summaryLine, body, grid) {
  clear(summaryLine);
  if (!body) {
    clear(mapBox).append(el("p", { class: "hint" },
      "아직 실행하지 않았습니다 — [배치 실행]을 누르면 격자 점마다 평형해를 풀고, "
      + "그 판정을 여기 (마하 × 고도) 지도로 그립니다. 연료가 여럿이면 연료마다 한 장입니다."));
    return;
  }
  const rows = body.results;
  // 머리줄의 판정은 lib 한 벌 — 쇼케이스 보고(trimCueReport)가 같은 집계로 같은 경고를 말한다
  const f = trimFlagSummary(rows);
  const untrimmed = untrimmedSummary(grid);
  summaryLine.append(
    f.line + (f.bad ? ` (${f.detail})` : "") + (untrimmed.text ? ` · ${untrimmed.text}` : ""),
    f.bad === 0 && f.converged === rows.length
      ? el("span", { class: "flag ok", style: "margin-left:8px" }, "전체 정상")
      : el("span", { class: "flag bad", style: "margin-left:8px" }, "확인 필요"));
  // 비행 엔벨로프 맵 — 조건 상태 (mach×alt, 연료별). 트림하지 않은 모델 부족 점도 그 상태로 칸을 차지한다 —
  // 요구영역과 모델 영역의 겹침을 눈으로 보이게(06 §10). 옛 결과(state 없음)는 판정 플래그 범례로 그린다
  const byState = rows.length > 0 && rows.every((r) => r.state);
  const entries = byState ? gridMapEntries(rows, grid) : rows.map((r) => ({ trim: r }));
  // 기본 격자가 있으면 실제 마하 가로축 + 요구 마하 띠(행 끝점이 공통 좌표 사이에 떨어져 등간격 열로는 거짓 간격이
  // 된다), 없으면(옛 결과만) 종전 히트맵
  const maps = fuelsOf(entries).map((fuel) => (byState && grid?.region
    ? stateMapCanvas({ rows: grid.rows, entries, machRange: grid.region.mach, fuel },
      (e) => trimEnvelopeCell(e.trim),
      { title: `조건 상태 — 연료 ${fuel} kg (띠 = 요구 마하 범위, 점 = 계산한 조건)` })
    : heatmapCanvas(
      pivotCases(entries, fuel),
      (e) => trimEnvelopeCell(e.trim),
      { title: `비행 엔벨로프 — 연료 ${fuel} kg (트림 판정 기반 근사)` },
    )));
  const stateLegend = el("div", { class: "legend" },
    Object.values(TRIM_STATE_CELL).map((c) => el("span", {},
      el("span", { class: "chip", style: `background:${c.color}` }), c.label)),
    el("span", { class: "hint" }, "— 물리적 불가 칸의 글은 첫 근거(추력·타면·실속). 계산 실패는 다시 풀 대상, ",
      "제약 도달은 트림 탐색 제약에 걸린 것이라 날 수 없다는 근거가 아니다"));
  clear(mapBox).append(
    el("div", { class: "stage-pair" }, ...maps),
    byState ? stateLegend : el("div", { class: "legend" },
      el("span", {}, el("span", { class: "chip", style: `background:${STATUS.ok}` }), TRIM_CELL_LABEL.ok),
      el("span", {}, el("span", { class: "chip", style: `background:${STATUS.bad}` }), TRIM_CELL_LABEL.stall),
      el("span", {}, el("span", { class: "chip", style: `background:${STATUS.warn}` }), TRIM_CELL_LABEL.saturated),
      el("span", {}, el("span", { class: "chip", style: `background:${STATUS.na}` }), TRIM_CELL_LABEL.infeasible),
      el("span", { class: "hint" }, "— 격자를 조밀하게(마하 간격 0.05, 고도 추가) 돌릴수록 경계가 정확해집니다")),
  );
}

function renderRows(tableBox, body) {
  if (!body) {
    clear(tableBox).append(el("p", { class: "hint" },
      "아직 결과가 없습니다 — 배치를 실행하면 케이스마다 θ·δe·스로틀과 판정 플래그가 여기 채워집니다."));
    return;
  }
  clear(tableBox).append(el("div", { class: "scroll-x" }, el("table", {},
    el("thead", {}, el("tr", {},
      el("th", {}, "케이스"), el("th", {}, "수렴"),
      el("th", { title: "조건 상태 (05 §11.3) — 계산 실패·제약 도달·물리적 불가를 가른다" }, "상태"),
      el("th", {}, "근거"),
      el("th", {}, "θ [rad]"), el("th", {}, "δe [rad]"), el("th", {}, "스로틀"),
      // 트림 여유 — 트림 해가 이미 가져간 몫과 남은 몫(엔진 TrimResult.reserve). 시뮬의 가용 동적 여유가 이 수에서
      // 기동 편차를 뺀다(01 §4.1). 옛 결과·지상 평형은 수치가 없어 비운다
      el("th", { title: "|δe| / 부호 쪽 엘레본 한계" }, "δe 소모"),
      el("th", { title: "1 − 스로틀" }, "추력 여유"),
      el("th", { title: "α_stall(M) − α — 판정 한계는 여기서 기체의 트림 α 여유를 뺀 것" }, "실속 여유 [rad]"),
      FLAG_COLS.map(([, title]) => el("th", {}, title)))),
    el("tbody", {}, body.results.map((r) => el("tr", {},
      el("td", {}, r.case.name),
      el("td", {}, flagBadge(r.converged, "수렴", "실패")),
      el("td", {}, r.state ? (TRIM_STATE_CELL[r.state]?.label ?? r.state)
        + (r.region_state ? ` · ${PRE_STATE_LABEL[r.region_state] ?? r.region_state}` : "")
        : "—"),
      el("td", { class: "hint" }, stateReasonText(r.state_reasons)),
      el("td", { class: "num" }, fmt(r.euler[1], 4)),
      el("td", { class: "num" }, fmt(r.control.elevon[0], 4)),
      el("td", { class: "num" }, fmt(r.control.throttle[0], 3)),
      // 백분율은 소수 자리 고정 — 유효 자리(fmt(·, 1))는 20 %를 「2e+1 %」로 찍었다
      el("td", { class: "num" }, r.reserve?.de ? pctText(r.reserve.de.frac) : "—"),
      el("td", { class: "num" }, r.reserve?.thr ? pctText(r.reserve.thr.reserve_hi) : "—"),
      el("td", { class: "num" }, r.reserve?.alpha ? fmt(r.reserve.alpha.stall_reserve, 4) : "—"),
      FLAG_COLS.map(([key]) => el("td", {}, flagBadge(r.flags[key]))),
    ))),
  )));
}

// 곡선에 그릴 양 — 표(renderRows)와 같은 수를 다른 표현으로 낸다. α는 트림 해에서
// θ와 같으므로(수평정상비행 γ=0 — lib/plot.js trimCurves 머리말) 두 그림을 내지 않는다
const CURVE_QTYS = [
  ["alpha", "받음각 α (= 피치각 θ) [rad]"],
  ["throttle", "스로틀 [-]"],
  ["de", "엘레본 δe [rad]"],
];

/** 패널 — 트림 곡선. 양마다 한 줄, 연료마다 한 장, 고도는 색(전 그림 공통 배정).
 *  같은 고도가 어느 그림에서든 같은 색이어야 연료 장끼리 비교가 선다. */
function renderCurves(curvesBox, body) {
  if (!body) {
    clear(curvesBox).append(el("p", { class: "hint" },
      "아직 결과가 없습니다 — 배치를 실행하면 마하에 따른 α(=θ)·스로틀·δe 곡선이 "
      + "연료마다 한 장씩 여기 섭니다."));
    return;
  }
  const entries = body.results.map((r) => ({ trim: r }));
  const fuels = fuelsOf(entries);
  const byFuel = fuels.map((fuel) => ({ fuel, curves: trimCurves(body.results, fuel) }));
  // 고도 → 색: 연료 장마다 고도 집합이 달라도 같은 고도는 같은 색 (합집합 순번)
  const altsUnion = [...new Set(byFuel.flatMap((f) => f.curves.alts))].sort((a, b) => a - b);
  const colorOf = (alt) => SERIES_COLORS[altsUnion.indexOf(alt) % SERIES_COLORS.length];
  const drawable = byFuel.filter((f) => f.curves.machs.length >= 2);
  const rows = CURVE_QTYS.map(([qty, label]) => el("div", { style: "margin-top: 10px" },
    el("h3", { style: "font-size: 13px; margin: 0 0 4px" }, label),
    el("div", { class: "row" }, drawable.map(({ fuel, curves }) =>
      lineChartCanvas(curves.machs, curves.series[qty].map((s) => ({
        data: s.data, color: colorOf(s.alt), label: "",
      })), { title: `연료 ${fuel} kg`, width: 420, height: 200, xUnit: "M", markers: true })))));
  // 네이티브 append에 null 직접 전달 금지 (문자열화 함정) — el 래핑으로 조립
  clear(curvesBox).append(el("div", {},
    el("div", { class: "legend" },
      ...altsUnion.map((alt) => el("span", {},
        el("span", { class: "chip", style: `background:${colorOf(alt)}` }), `${alt} m`)),
      el("span", { class: "hint" }, "— 고도별 곡선 · 점 = 계산한 격자점")),
    ...rows,
    byFuel.length > drawable.length
      ? el("p", { class: "hint" },
          `마하 점이 1개뿐인 연료(${byFuel.filter((f) => f.curves.machs.length < 2)
            .map((f) => `${f.fuel} kg`).join(", ")})는 곡선이 서지 않습니다 — 수치는 위 표에 있습니다.`)
      : null,
    el("p", { class: "hint" },
      "끊긴 구간 = 트림 불가·미수렴(위 지도의 「불가」 칸과 같은 사실) — 0으로 채우지 않습니다. ",
      "α는 수평정상비행 트림이라 θ와 같습니다 — 상승·강하 트림을 지원하면 두 곡선이 갈립니다."),
  ));
}

function showError(errBox, e) {
  clear(errBox).append(el("div", { class: "error-box" }, errorText(e)));
}
