/** 타면 사용 — 조종면이 어느 타각 범위에 얼마나 오래 머물렀나.
 *
 * 시계열(시뮬 재생)은 "언제 무슨 일이 있었나"를 말한다. 여기는 **같은 런**을 체류
 * 시간의 언어로 다시 읽는다 — 작동기 사이징·힌지모멘트 듀티·리밋사이클 판정이
 * 쓰는 언어다. 특히 "작동기 rate ≥ 10 rad/s" 요구 사양(01 v0.13)이 이 런에서
 * 지켜졌는지가 타각–타율 밀도의 능력 상자로 바로 읽힌다.
 *
 * 수치는 전부 엔진(claw/analysis/duty.py)이 **저장된 전 해상도**에서 낸다. 재생과
 * 달리 stride 다운샘플을 쓰지 않는 이유는 최대 타율과 짧은 포화 구간이 통째로
 * 사라지기 때문 — 서버가 집계를 끝내고 요약만 보낸다.
 *
 * 세 그림이 서로 다른 질문에 답한다:
 *   히스토그램 — 어느 타각에 얼마나 있었나 (빈 칸 = 쓰지 않은 조종권)
 *   누적 초과   — |δ| ≥ x인 시간이 얼마 (P95 같은 사양 수치가 여기서 나온다)
 *   밀도+상자   — 타각·타율 조합이 작동기 능력 안에 있었나
 *
 * ## 탭이 아니라 시뮬레이션 탭의 서랍이다 (v0.54)
 *
 * 종전에는 최상위 탭이었는데 **층위가 맞지 않았다**(사용자 지적). 나머지 탭은 전부
 * 설계 단계 하나씩이고(엔벨로프 → 트림 → 게인 → 마진 → 자동 설계 → 시뮬), 이것은
 * 단계가 아니라 **시뮬 런 하나를 다시 읽는 한 가지 방법**이다 — 재생·엔벨로프 감시와
 * 같은 층이다. 최상위에 두면 사용자는 시뮬을 돌린 뒤 탭을 옮겨 같은 결과를 다시
 * 고르게 되고, 그 선택이 방금 돌린 런과 어긋날 수 있다.
 *
 * 그래서 이 파일은 라우트 뷰가 아니라 **컴포넌트**를 내보낸다(`createDutyPanel`).
 * 서랍 안이라 층을 한 겹 더 파지 않는다 — 요약 표가 위, 타면 선택 버튼이 아래,
 * 고른 타면의 세 그림이 그 밑. 요약이 "어디가 문제인가"를, 그림이 "왜 그런가"를 답한다.
 *
 * 심각도 색은 클래스가 아니라 값으로 지정한다 — 이 색은 판정이지 테마가 아니다.
 */

import { api, errorText } from "../api.js";
import { clear, el } from "../dom.js";
import {
  capabilityBox, channelRows, densityView, exceedanceSeries, fmtDeg,
  histBars, modeOptions, toDeg, viewOf,
} from "../lib/duty.js";
import { store } from "../store.js";
import { densityCanvas, histogramCanvas, lineChartCanvas } from "./plots.js";

const BINS = 32;
const RATE_BINS = 24;
const CHART_W = 372;
const CHART_H = 196;
// 심각도 색은 클래스가 아니라 값으로 — app.css 비접촉 (ok/경고/판정불가 3단 + 주의)
const SEV_COLOR = { ok: "#34c759", warn: "#ff9500", bad: "#ff3b30", na: "#8e8e93" };

// 탭을 떠났다 와도 고른 결과·구간·타면을 잃지 않는다 (sim.js lastReplay와 동렬)
let lastReport = null;
let selectedId = null;
let selectedMode = "";
let selectedChannel = null; // 타면 라벨 — 결과가 바뀌어도 같은 이름이면 그대로 따라간다
let stale = true;           // 새 런이 끝나면 서면 — 다음에 열 때 다시 집계한다

/** 시뮬 런이 새로 끝났다 — 다음에 서랍을 열 때 다시 집계한다.
 *  즉시 부르지 않는 이유: 서랍이 닫혀 있으면 아무도 안 보는 집계에 서버를 쓴다. */
export function invalidate() {
  stale = true;
}

/** 타면 사용 패널 — 시뮬레이션 탭의 서랍 하나가 그대로 이것이다.
 *
 *  `ensure()`는 **열릴 때** 불린다(지연 로드). 탭에 들어올 때마다 집계하면 이 서랍을
 *  한 번도 안 여는 사람에게 매번 서버 왕복이 생긴다 — 20000 표본 집계는 공짜가 아니다. */
export function createDutyPanel() {
  const errBox = el("div");
  const statusBox = el("span", { class: "hint" });
  const summaryBox = el("div");
  const chanBar = el("div", { class: "row", style: "gap:6px; margin-top:12px" });
  const chanBox = el("div");
  const idSel = el("select", { "aria-label": "시뮬 결과 선택" });
  const modeSel = el("select", { "aria-label": "비행 모드 선택" });

  const drawChannel = () => {
    clear(chanBar);
    clear(chanBox);
    const chans = lastReport?.channels ?? [];
    if (!chans.length) return;
    // 고른 타면이 이 결과에 없으면 첫 타면으로 — 빈 화면 대신 무엇이든 보여 준다
    if (!chans.some((c) => c.label === selectedChannel)) selectedChannel = chans[0].label;
    chanBar.append(el("span", { class: "hint" }, "타면"));
    for (const c of chans) {
      chanBar.append(el("button", {
        class: c.label === selectedChannel ? "primary" : "",
        onclick: () => { selectedChannel = c.label; drawChannel(); },
      }, c.label));
    }
    const chan = chans.find((c) => c.label === selectedChannel);
    chanBox.append(channelBody(chan, selectedMode, lastReport));
  };

  const draw = () => {
    if (!lastReport) return;
    clear(modeSel).append(...modeOptions(lastReport).map((o) =>
      el("option", { value: o.value, selected: o.value === selectedMode }, o.label)));
    renderSummary(summaryBox, lastReport);
    drawChannel();
  };

  const load = async (id) => {
    try {
      clear(errBox);
      statusBox.textContent = "집계 중…";
      lastReport = await api.get(
        `/sim/${id}/duty?bins=${BINS}&rate_bins=${RATE_BINS}`);
      selectedId = id;
      selectedMode = "";
      stale = false;
      statusBox.textContent =
        `${lastReport.n}표본 · ${lastReport.t_total.toFixed(1)} s`
        + ` · dt ${lastReport.dt}s (전 해상도)`;
      draw();
    } catch (e) {
      lastReport = null;
      clear(summaryBox);
      clear(chanBar);
      clear(chanBox);
      statusBox.textContent = "";
      clear(errBox).append(el("div", { class: "error-box" }, errorText(e)));
    }
  };

  const loadList = async () => {
    try {
      clear(errBox);
      const items = (await api.get("/results")).filter((m) => m.kind === "sim");
      if (!items.length) {
        // 조용한 빈 화면 금지 — 무엇을 해야 하는지를 말한다
        clear(summaryBox).append(el("p", { class: "hint" },
          "시뮬 결과가 없습니다 — 위 [시뮬 실행]을 한 번 누르면 그 런의 타면 사용 "
          + "통계가 여기 채워집니다."));
        return;
      }
      clear(idSel).append(...items.map((m) => el("option", { value: m.id },
        `${m.id} · ${m.n ?? "?"}표본${m.aborted ? ` · 절단 ${m.aborted}` : ""}`)));
      // 방금 돌린 런이 기본이다 — 이 서랍은 그 런을 다시 읽는 자리다
      const prefer = store.get("simResult")?.id ?? selectedId;
      const pick = items.some((m) => m.id === prefer) ? prefer : items[0].id;
      idSel.value = pick;
      if (lastReport && selectedId === pick && !stale) draw();
      else await load(pick);
    } catch (e) {
      clear(errBox).append(el("div", { class: "error-box" }, errorText(e)));
    }
  };

  idSel.addEventListener("change", () => load(idSel.value));
  modeSel.addEventListener("change", () => {
    selectedMode = modeSel.value;
    renderSummary(summaryBox, lastReport);
    drawChannel();
  });

  const root = el("div", {},
    el("h2", {}, "타면 사용 — 타각 범위별 체류 시간·포화"),
    el("p", { class: "hint", style: "margin:0 0 10px; max-width:96ch" },
      "재생이 «언제 무슨 일이 있었나»를 말한다면 여기는 같은 런을 체류 시간의 "
      + "언어로 다시 읽는다 — 작동기 사이징·힌지모멘트 듀티·리밋사이클 판정이 쓰는 언어다."),
    el("div", { class: "row" },
      el("label", { class: "field" }, "시뮬 결과", idSel),
      el("label", { class: "field" }, "구간", modeSel),
      el("button", { onclick: loadList }, "새로고침"),
      statusBox),
    errBox,
    summaryBox,
    chanBar,
    chanBox,
    noteBox(),
  );

  return {
    root,
    /** 서랍이 열릴 때 — 아직 없거나 새 런이 끝났으면 그때 집계한다. */
    ensure() {
      if (!lastReport || stale) loadList();
      else draw();
    },
  };
}

function sevCell(cell) {
  return el("td", { style: `color:${SEV_COLOR[cell.severity] ?? SEV_COLOR.na}` }, cell.text);
}

function summaryTable(report) {
  const head = ["타면", "평균", "표준편차", "P95 |δ|", "최대 |δ|", "최대 |δ̇|",
    "사용률", "위치 포화", "rate 포화", "타율 반전"];
  return el("div", { class: "scroll-x" }, el("table", {},
    el("thead", {}, el("tr", {}, head.map((h) => el("th", {}, h)))),
    el("tbody", {}, channelRows(report).map((r) => el("tr", {},
      el("td", {}, r.label),
      el("td", { class: "num" }, r.mean),
      el("td", { class: "num" }, r.std),
      el("td", { class: "num" }, r.p95),
      el("td", { class: "num" }, r.max),
      el("td", { class: "num" }, r.maxRate),
      el("td", { class: "num" }, r.usage),
      sevCell(r.posSat),
      sevCell(r.rateSat),
      el("td", { class: "num", title: r.reversalsHint }, r.reversals))))));
}

/** 타면 한 장 — 세 그림과 그 그림들이 기대는 전제. 카드(.panel)를 두르지 않는다:
 *  이미 서랍 안이라 판이 겹치면 상자 속 상자가 된다. */
function channelBody(channel, mode, report) {
  const v = viewOf(channel, mode);
  if (!v) {
    return el("div", {},
      el("h2", {}, channel.label),
      el("p", { class: "hint" }, `이 결과에 ${mode} 구간이 없습니다.`));
  }
  const box = capabilityBox(channel);
  const bars = histBars(v.hist);
  const limitText = box.xLo == null ? "한계 미상"
    : `위치 한계 ${fmtDeg(channel.pos_lo)} ~ ${fmtDeg(channel.pos_hi)}`;
  const rateText = box.yHi == null ? "rate 한계 없음(작동기 미장착)"
    : `rate 한계 ±${(box.yHi).toFixed(0)}°/s`;

  const charts = [
    histogramCanvas(bars, {
      title: `체류 시간 — ${v.time == null ? "" : `${v.time.toFixed(1)} s`}`,
      xLabel: "타각 [°]", width: CHART_W, height: CHART_H,
      // 평균선 = 트림 편향. 0에서 벗어나 있으면 그만큼을 상시 물고 비행한 것
      markers: [{ x: toDeg(v.stats?.mean), color: "#ff9500", label: "평균" }],
    }),
  ];
  if (v.exceedance) {
    const ex = exceedanceSeries(v.exceedance);
    charts.push(lineChartCanvas(ex.level,
      [{ label: "|δ| ≥ x", data: ex.time, color: "#007aff" }],
      { title: "누적 초과 시간 [s]", xUnit: "°", width: CHART_W, height: CHART_H }));
  }
  if (v.density) {
    charts.push(densityCanvas(densityView(v.density), {
      box, title: "타각–타율 밀도 (붉은 선 = 작동기 능력)",
      xLabel: "타각 [°]", yLabel: "[°/s]", width: CHART_W, height: CHART_H,
    }));
  }

  const oor = v.hist?.out_of_range ?? 0;
  return el("div", {},
    el("h2", {}, channel.label,
      el("span", { class: "hint", style: "margin-left:10px; font-weight:400" },
        `${limitText} · ${rateText}`)),
    el("div", { style: "display:flex; flex-wrap:wrap; gap:10px" }, ...charts),
    mode
      ? el("p", { class: "hint" },
        `${mode} 구간만 — 누적 초과·밀도는 전체 런에 대해서만 산출되므로 여기서는 생략.`)
      : null,
    oor > 0
      ? el("p", { class: "hint", style: `color:${SEV_COLOR.warn}` },
        `한계 밖 표본 ${oor.toFixed(2)} s — 양끝 빈으로 접어 그렸습니다.`)
      : null,
    !report.actuators
      ? el("p", { class: "hint" },
        "작동기 미장착 — 타율은 실현값이 아니라 명령 요구 slew이고, rate 한계가 "
        + `없어 능력 상자의 가로선이 그려지지 않습니다 (제어주기 ${report.rate_dt}s 기준).`)
      : null);
}

/** 전면 — 전 타면 한 줄씩. "어디가 문제인가"를 여기서 먼저 답한다. */
function renderSummary(box, report) {
  if (!report) {
    clear(box).append(el("p", { class: "hint" }, "결과가 없습니다."));
    return;
  }
  // el()로 감싼다 — clear(box).append(...)는 **네이티브** append라 null을 "null"
  // 텍스트로 붙인다(el은 걸러 낸다). 실제로 경고가 없는 런에서 표 밑에 "null"이
  // 한 줄 찍혔다 (이 리포의 상습 함정군)
  clear(box).append(el("div", {},
    summaryTable(report),
    report.warnings?.length
      ? el("p", { class: "hint", style: `color:${SEV_COLOR.warn}` },
        report.warnings.join(" "))
      : null,
    // 범례는 **표와 같은 화면**에 둔다 — 색이 판정인데 뜻을 클릭 뒤로 숨기면
    // 화면이 자기가 쓴 색을 설명하지 않는 상태가 된다 (영향성 범례와 같은 규약)
    el("div", { class: "legend" },
      el("span", {}, el("span", { class: "chip", style: `background:${SEV_COLOR.ok}` }), "포화 없음"),
      el("span", {}, el("span", { class: "chip", style: `background:${SEV_COLOR.warn}` }), "포화 1% 미만"),
      el("span", {}, el("span", { class: "chip", style: `background:${SEV_COLOR.bad}` }), "포화 1% 이상"),
      el("span", {}, el("span", { class: "chip", style: `background:${SEV_COLOR.na}` }), "판정 불가")),
  ));
}

/** 읽는 법 — 표를 보다 막히는 자리들의 뜻. 서랍 안이라 층을 하나 더 파지 않고
 *  `<details>` 하나로 접는다(칩 안의 칩은 어디를 눌러야 하는지를 흐린다). */
function noteBox() {
  return el("details", { style: "margin-top:14px" },
    el("summary", { class: "hint" }, "읽는 법 — 판정 색·포화의 뜻·타율 반전의 불감대"),
    el("p", { class: "hint", style: "max-width:96ch" },
      "각은 표시 전용 deg 변환 (내부·전송은 rad). 포화 '판정 불가'는 0초가 아니라 ",
      "한계값을 모르는 상태입니다 — 작동기 미장착이거나 판정 기준선이 없는 옛 결과. ",
      "포화는 시간·비율과 함께 ", el("b", {}, "구간 수·최장 구간"), "을 봅니다: 짧게 여러 번이면 ",
      "리밋사이클 징후, 길게 한 번이면 조종권 부족으로 처방이 다릅니다. ",
      "타율 반전은 불감대(rate 한계의 2%) 초과분만 세므로 rate 한계가 다른 런끼리 ",
      "횟수를 직접 비교하면 안 됩니다 — 쓰인 불감대는 칸에 마우스를 올리면 나옵니다."),
    el("p", { class: "hint", style: "max-width:96ch" },
      "수치는 전부 엔진이 ", el("b", {}, "저장된 전 해상도"), "에서 냅니다 — 재생과 달리 ",
      "stride 다운샘플을 쓰지 않는 이유는 최대 타율과 짧은 포화 구간이 통째로 ",
      "사라지기 때문입니다."),
  );
}
