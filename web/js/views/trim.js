/** 트림 뷰 (02 §8 2단계) — 격자 → 배치 실행 → 비행 가능 영역.

이 탭의 답은 표가 아니라 **지도**다: "이 격자에서 어디가 날 수 있고 어디가 안 되나."
그래서 비행 엔벨로프 맵이 카드 밖 전면에 놓이고(블록도 최상위·영향성과 같은 규약,
views/stage.js), 격자 조건·케이스 목록·케이스별 수치는 서랍에 들어간다.

DOM 조립 전용 (얇게) — 격자 로직은 lib/grid.js, 수치·판정은 전부 서버(엔진) 산출.
*/

import { api, errorText } from "../api.js";
import { clear, el, flagBadge, fmt } from "../dom.js";
import { machRange, parseNumberList, serpentineCases } from "../lib/grid.js";
import { STATUS, fuelsOf, pivotCases, trimEnvelopeCell } from "../lib/plot.js";
import { store } from "../store.js";
import { heatmapCanvas } from "./plots.js";
import { attachProgress, cancelledWithoutResult } from "./progress.js";
import { createDrawers, tabStage, tabTop } from "./stage.js";

// 모듈 상태 — 탭 재진입 시 유지 (실행 중 작업 재부착 포함, 리뷰 S4)
let cases = [];
let lastBody = null;
let runningJobId = null;
let runningFp = "";
let openDrawer = null;

const FLAG_COLS = [
  ["residual_ok", "잔차"],
  ["saturation_ok", "포화"],
  ["alpha_margin_ok", "α여유"],
  ["continuity_ok", "연속성"],
];

export function render() {
  const caseBox = el("div");
  const progressBox = el("div");
  const mapBox = el("div");     // 전면 — 비행 엔벨로프 맵
  const tableBox = el("div");   // 서랍 — 케이스별 수치·판정
  const errBox = el("div");
  const summaryLine = el("p", { class: "tab-status" });

  // 기본 격자는 **비행 가능 범위 안**이어야 한다 — 프로펠러 전환 전의 0.4~0.8/0.1은
  // 15칸 중 8칸이 밖이 됐고(고도 1000·3000 m에서 M0.6·0.7·0.8, 100 m에서 0.7·0.8), 0.10 간격은 thr 변화가 연속성 문턱(0.15)을
  // 넘어 시드 연쇄까지 끊겼다. 0.30~0.55/0.05는 세 고도(100·1000·3000 m) 전부 안이다.
  const fMachFrom = el("input", { class: "num", value: "0.3" });
  const fMachTo = el("input", { class: "num", value: "0.55" });
  const fMachStep = el("input", { class: "num", value: "0.05" });
  const fAlts = el("input", { value: "100, 1000, 3000" });
  const fFuels = el("input", { class: "num", value: "200" });
  const fFp = el("input", { value: "web-trim-v1" });

  // 실행 버튼은 **전면**이다 — 격자를 고치는 서랍 안에만 있으면 서랍을 닫는 순간
  // 실행할 방법이 사라진다. 라벨이 케이스 수를 들고 있어 상태 표시도 겸한다
  const runBtn = el("button", { class: "primary" }, "배치 실행");
  const syncRunBtn = () => {
    runBtn.disabled = !cases.length || !!runningJobId; // 이중 제출 방지 (리뷰 S4)
    clear(runBtn).append(runningJobId ? "실행 중…" : `배치 실행 (${cases.length}케이스)`);
  };
  runBtn.onclick = () => runBatch();

  const makeGrid = () => {
    try {
      clear(errBox);
      cases = serpentineCases(
        machRange(Number(fMachFrom.value), Number(fMachTo.value), Number(fMachStep.value)),
        parseNumberList(fAlts.value),
        parseNumberList(fFuels.value),
      );
      repaintCases();
    } catch (e) {
      showError(errBox, e);
    }
  };

  const repaintCases = () => {
    renderCases(caseBox, cases, repaintCases);
    syncRunBtn();
    drawers.refresh();
  };

  const runBatch = async () => {
    if (runningJobId) return;
    clear(errBox);
    runningFp = fFp.value;
    try {
      const submitted = await api.post("/trim/batch", { cases, fingerprint: runningFp });
      runningJobId = submitted.id;
      repaintCases(); // 버튼 비활성 반영
      watchTrim();
    } catch (e) {
      showError(errBox, e);
    }
  };

  const watchTrim = () => attachProgress(progressBox, runningJobId, {
    onDone: async (job) => {
      runningJobId = null;
      repaintCases();
      try {
        if (job.status === "error") throw new Error(job.error);
        if (cancelledWithoutResult(job)) {
          showError(errBox, new Error("취소됨 — 저장된 결과 없음 (실행 전 취소)"));
          return;
        }
        const body = await api.get(`/results/${job.result_id}`);
        lastBody = body;
        store.set("trimResult", { id: job.result_id, fingerprint: runningFp, cases: [...cases] });
        renderResults();
        drawers.open("rows"); // 수치가 사는 서랍을 열어 준다
      } catch (e) {
        showError(errBox, e);
      }
    },
    onError: (e) => {
      runningJobId = null;
      repaintCases();
      showError(errBox, e);
    },
  });

  const renderResults = () => {
    renderMap(mapBox, summaryLine, lastBody);
    renderRows(tableBox, lastBody);
    drawers.refresh();
  };

  const drawers = createDrawers({
    id: "trim-drawer",
    initial: openDrawer,
    onOpen: (k) => { openDrawer = k; },
    defs: [
      { key: "grid", label: "격자 조건", group: "입력",
        title: "마하 범위·간격, 고도·연료 목록, 계보 지문",
        build: () => [
          el("h2", {}, "트림 케이스 매트릭스 (격자 생성 — 서펜타인 순서)"),
          el("div", { class: "row" },
            el("label", { class: "field" }, "마하 시작", fMachFrom),
            el("label", { class: "field" }, "마하 끝", fMachTo),
            el("label", { class: "field" }, "간격", fMachStep),
            el("label", { class: "field grow" }, "고도 목록 [m]", fAlts),
            el("label", { class: "field" }, "연료 [kg]", fFuels),
            el("label", { class: "field" }, "지문(fingerprint)", fFp),
            el("button", { onclick: makeGrid }, "격자 생성")),
          el("p", { class: "hint" },
            "리스트상 인접 케이스가 물리적으로도 인접하도록 행마다 마하 방향을 뒤집는다",
            " — 배치 트림의 인접 시드·연속성 판정 전제 (01 §4.1). 격자를 촘촘히 할수록 ",
            "위 지도의 경계가 정확해진다."),
        ] },
      { key: "cases", label: "케이스 목록", group: "입력",
        title: "격자가 낸 케이스 — 손으로 더하거나 지울 수 있다",
        count: () => cases.length,
        build: () => [el("h2", {}, "케이스 목록"), caseBox] },
      { key: "rows", label: "케이스별 수치·판정", group: "결과",
        title: "θ·δe·스로틀과 판정 플래그 4종",
        count: () => (lastBody ? lastBody.results.length : null),
        build: () => [el("h2", {}, "결과 — 케이스별 트림 해와 판정"), tableBox] },
    ],
  });

  repaintCases();
  if (lastBody) renderResults();
  else renderMap(mapBox, summaryLine, null);
  if (runningJobId) watchTrim(); // 재부착

  return el("div", { class: "tab-page" },
    tabTop({
      title: "트림",
      lead: "격자의 점마다 평형해를 푼다 — 그 판정이 곧 «어디를 날 수 있나»의 답이고, "
        + "다음 단계(선형화·마진)는 여기서 수렴한 점 위에서만 성립한다.",
      actions: [runBtn, el("button", { onclick: makeGrid }, "격자 생성")],
      extra: [summaryLine, progressBox, errBox],
    }),
    // 비행 엔벨로프 맵 — 카드 밖, 페이지 위에 그대로 (캔버스가 자기 테두리를 갖는다)
    tabStage(mapBox),
    drawers.root,
  );
}

function renderCases(caseBox, list, repaint) {
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
          onclick: () => { list.splice(i, 1); repaint(); },
        }, "삭제")),
      ))),
    )));
  }
  caseBox.append(el("div", { class: "row" },
    el("button", {
      onclick: () => {
        list.push({ mach: 0.45, alt: 1000, fuel: 200 });  // 엔벨로프 안 (스로틀 0.58)
        repaint();
      },
    }, "행 추가"),
  ));
}

/** 전면 무대 — 비행 엔벨로프 맵. 결과가 없으면 **무엇이 여기 그려질지**를 말한다
 *  (빈 화면은 "고장"과 "아직 안 함"을 구분해 주지 않는다). */
function renderMap(mapBox, summaryLine, body) {
  clear(summaryLine);
  if (!body) {
    clear(mapBox).append(el("p", { class: "hint" },
      "아직 실행하지 않았습니다 — [배치 실행]을 누르면 격자 점마다 평형해를 풀고, "
      + "그 판정을 여기 (마하 × 고도) 지도로 그립니다. 연료가 여럿이면 연료마다 한 장입니다."));
    return;
  }
  const rows = body.results;
  const nOk = rows.filter((r) => r.converged).length;
  const nBad = rows.filter(
    (r) => !Object.values(r.flags).every((v) => v !== false),
  ).length;
  summaryLine.append(
    `수렴 ${nOk}/${rows.length} · 판정 플래그 위반 ${nBad}건`,
    nBad === 0 && nOk === rows.length
      ? el("span", { class: "flag ok", style: "margin-left:8px" }, "전체 정상")
      : el("span", { class: "flag bad", style: "margin-left:8px" }, "확인 필요"));
  // 비행 엔벨로프 맵 — 트림 판정 기반 (mach×alt, 연료별)
  const entries = rows.map((r) => ({ trim: r }));
  const maps = fuelsOf(entries).map((fuel) =>
    heatmapCanvas(
      pivotCases(entries, fuel),
      (e) => trimEnvelopeCell(e.trim),
      { title: `비행 엔벨로프 — 연료 ${fuel} kg (트림 판정 기반 근사)` },
    ));
  clear(mapBox).append(
    el("div", { class: "stage-pair" }, ...maps),
    el("div", { class: "legend" },
      el("span", {}, el("span", { class: "chip", style: `background:${STATUS.ok}` }), "가능"),
      el("span", {}, el("span", { class: "chip", style: `background:${STATUS.bad}` }), "실속 근접 (α 여유 위반)"),
      el("span", {}, el("span", { class: "chip", style: `background:${STATUS.warn}` }), "포화 (추력·타면 한계)"),
      el("span", {}, el("span", { class: "chip", style: `background:${STATUS.na}` }), "트림 불가"),
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
      el("th", {}, "θ [rad]"), el("th", {}, "δe [rad]"), el("th", {}, "스로틀"),
      FLAG_COLS.map(([, title]) => el("th", {}, title)))),
    el("tbody", {}, body.results.map((r) => el("tr", {},
      el("td", {}, r.case.name),
      el("td", {}, flagBadge(r.converged, "수렴", "실패")),
      el("td", { class: "num" }, fmt(r.euler[1], 4)),
      el("td", { class: "num" }, fmt(r.control.elevon[0], 4)),
      el("td", { class: "num" }, fmt(r.control.throttle[0], 3)),
      FLAG_COLS.map(([key]) => el("td", {}, flagBadge(r.flags[key]))),
    ))),
  )));
}

function showError(errBox, e) {
  clear(errBox).append(el("div", { class: "error-box" }, errorText(e)));
}
