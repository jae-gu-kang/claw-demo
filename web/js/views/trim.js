/** 트림 뷰 (02 §8 3단계) — 격자 → 배치 실행 → 비행 가능 영역.

이 탭의 답은 표가 아니라 **지도**다: "이 격자에서 어디가 날 수 있고 어디가 안 되나."
그래서 비행 엔벨로프 맵이 카드 밖 전면에 놓이고(블록도 최상위·영향성과 같은 규약,
views/stage.js), 격자 조건·케이스 목록·케이스별 수치는 패널에 들어간다.

DOM 조립 전용 (얇게) — 격자 로직은 lib/grid.js, 수치·판정은 전부 서버(엔진) 산출.
*/

import { api, errorText } from "../api.js";
import { clear, el, flagBadge, fmt } from "../dom.js";
import { DEFAULT_GRID, machRange, parseNumberList, serpentineCases } from "../lib/grid.js";
import { fillGridFromProfile } from "./missionfill.js";
import { SERIES_COLORS, STATUS, fuelsOf, pivotCases, trimCurves, trimEnvelopeCell } from "../lib/plot.js";
import { store } from "../store.js";
import { heatmapCanvas, lineChartCanvas } from "./plots.js";
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
  const tableBox = el("div");   // 패널 — 케이스별 수치·판정
  const curvesBox = el("div");  // 패널 — 트림 곡선 (α·스로틀·δe vs 마하)
  const errBox = el("div");
  const summaryLine = el("p", { class: "tab-status" });

  // 기본 격자는 **비행 가능 범위 안**이어야 한다 — 근거·실측 여유·칸 수는
  // lib/grid.js DEFAULT_GRID 주석이 정본이고 여기서는 그 값을 읽기만 한다.
  // 숫자를 여기 다시 적으면 안 된다: v0.44가 이 탭만 고치고 상수는 옛 값으로
  // 남겨 둔 것이 v0.44~v0.72 내내 평가 격자를 엔벨로프 밖에 묶어 두었다.
  const fMachFrom = el("input", { class: "num", value: String(DEFAULT_GRID.machFrom) });
  const fMachTo = el("input", { class: "num", value: String(DEFAULT_GRID.machTo) });
  const fMachStep = el("input", { class: "num", value: String(DEFAULT_GRID.machStep) });
  const fAlts = el("input", { value: DEFAULT_GRID.alts.join(", ") });
  const fFuels = el("input", { class: "num", value: DEFAULT_GRID.fuels.join(", ") });
  const fFp = el("input", { value: "web-trim-v1" });
  // 위 격자는 **예제 기체의 격자**(폴백)다 — 고른 기체 문서가 오면 손대지 않은 칸만 그 기체 미션 템플릿의
  // 격자로 바꾸고, 템플릿이 없으면 그렇다고 적는다(views/missionfill.js). 케이스 목록이 아직 기본 격자
  // 그대로면 새 격자로 다시 만든다 — 손으로 고친 목록은 두지 않는다
  const gridHint = el("p", { class: "hint" });
  const isDefaultCases = () => JSON.stringify(cases) === JSON.stringify(serpentineCases(
    machRange(DEFAULT_GRID.machFrom, DEFAULT_GRID.machTo, DEFAULT_GRID.machStep), DEFAULT_GRID.alts, DEFAULT_GRID.fuels));
  fillGridFromProfile({ machFrom: fMachFrom, machTo: fMachTo, machStep: fMachStep, alts: fAlts, fuels: fFuels },
    gridHint, () => { if (!runningJobId && isDefaultCases()) makeGrid(); });

  // 실행 버튼은 **전면**이다 — 격자를 고치는 패널 안에만 있으면 패널을 닫는 순간
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
        drawers.open("rows"); // 수치가 사는 패널을 열어 준다
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
    renderCurves(curvesBox, lastBody);
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
      { key: "curves", label: "트림 곡선", group: "결과",
        title: "α(=θ)·스로틀·δe — 마하에 따른 곡선, 고도별 색, 연료별 한 장",
        build: () => [el("h2", {}, "트림 곡선 — 조건(마하·고도·연료)에 따른 트림 해"), curvesBox] },
    ],
  });

  repaintCases();
  if (lastBody) renderResults();
  else {
    renderMap(mapBox, summaryLine, null);
    renderRows(tableBox, null);
    renderCurves(curvesBox, null);
  }
  if (runningJobId) watchTrim(); // 재부착

  return el("div", { class: "tab-page" },
    tabTop({
      title: "트림",
      lead: "격자의 점마다 평형해를 푼다 — 그 판정이 곧 «어디를 날 수 있나»의 답이고, "
        + "다음 단계(선형화·마진)는 여기서 수렴한 점 위에서만 성립한다.",
      actions: [runBtn, el("button", { onclick: makeGrid }, "격자 생성")],
      extra: [summaryLine, gridHint, progressBox, errBox],
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
      // 트림 여유 — 트림 해가 이미 가져간 몫과 남은 몫(엔진 TrimResult.reserve). 시뮬의 가용 동적 여유가 이 수에서
      // 기동 편차를 뺀다(01 §4.1). 옛 결과·지상 평형은 수치가 없어 비운다
      el("th", { title: "|δe| / 부호 쪽 엘레본 한계" }, "δe 소모"),
      el("th", { title: "1 − 스로틀" }, "추력 여유"),
      el("th", { title: "α_stall(M) − α — 판정 한계는 여기서 기체의 트림 α 여유를 뺀 것" }, "실속 여유 [rad]"),
      FLAG_COLS.map(([, title]) => el("th", {}, title)))),
    el("tbody", {}, body.results.map((r) => el("tr", {},
      el("td", {}, r.case.name),
      el("td", {}, flagBadge(r.converged, "수렴", "실패")),
      el("td", { class: "num" }, fmt(r.euler[1], 4)),
      el("td", { class: "num" }, fmt(r.control.elevon[0], 4)),
      el("td", { class: "num" }, fmt(r.control.throttle[0], 3)),
      el("td", { class: "num" }, r.reserve?.de ? `${fmt(r.reserve.de.frac * 100.0, 1)} %` : "—"),
      el("td", { class: "num" }, r.reserve?.thr ? `${fmt(r.reserve.thr.reserve_hi * 100.0, 1)} %` : "—"),
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
