/** 게인 스케줄 뷰 (02 §8 4단계) — 설계 테이블 조회 → 셀 편집 → 시뮬 주입 준비.

주입은 전체 교체 (엔진 make_demo_fcl 계약) — 편집본은 store("gainTables")로
시뮬레이션 탭에 전달. 검증(그룹·키·형상·유한성)은 제출 시 서버/엔진이 수행.
*/

import { api, errorText } from "../api.js";
import { clear, el, fmt } from "../dom.js";
import { gainPlotGroups } from "../lib/plot.js";
import { piecewisePolyfit, rawCoeffs, sampleFit } from "../lib/polyfit.js";
import { store } from "../store.js";
import { lineChartCanvas } from "./plots.js";

let tables = null; // {name: {axes: {mach: [...]}, data: [...], extrapolate}}

// 근사 곡선 설정 — 탭 이탈·재로드에도 유지 (경계 "0.3"은 데모 동압 스케일의
// 상한 클립 경계와 일치하는 시연 기본값, 검증은 piecewisePolyfit이 수행)
const fitCfg = { show: true, degree: 3, boundaries: "0.3", detailsOpen: false };

export function render() {
  const box = el("div");
  const errBox = el("div");
  const statusLine = el("p", { class: "hint" });

  const load = async () => {
    try {
      clear(errBox);
      tables = await api.get("/gains/demo");
      renderTables(box, statusLine);
    } catch (e) {
      clear(errBox).append(el("div", { class: "error-box" }, errorText(e)));
    }
  };

  const root = el("div", {},
    el("div", { class: "panel" },
      el("h2", {}, "게인 스케줄 테이블 (동압 스케일 1D mach — 설계점 M0.6)"),
      el("p", { class: "hint" },
        "신호흐름 구조는 구조도 탭 — SCAS·게인 스케줄 블록에서 여기로 진입한다."),
      el("div", { class: "row" },
        el("button", { onclick: load }, "설계값 다시 불러오기"),
        el("button", {
          class: "primary",
          onclick: () => {
            if (!tables) return;
            store.set("gainTables", JSON.parse(JSON.stringify(tables)));
            statusLine.textContent =
              "편집본 적용됨 — 시뮬레이션 탭에서 '편집 게인 사용'을 켜면 주입됩니다 (전체 교체).";
          },
        }, "시뮬에 적용"),
      ),
      statusLine, errBox,
    ),
    el("div", { class: "panel" }, box),
  );

  if (tables) renderTables(box, statusLine);
  else load();
  return root;
}

/** 전 게인 구간별 회귀 — 실패 시 {error} (첫 실패에서 중단, 조건은 전 게인 공통). */
function computeFits(groups) {
  const items = fitCfg.boundaries.split(",").map((s) => s.trim()).filter((s) => s !== "");
  const values = items.map(Number);
  const bad = items.filter((_, i) => !Number.isFinite(values[i]));
  if (bad.length) return { error: `경계 형식 오류: ${bad.join(", ")}` };
  const overlays = new Map(); // group → 점선 시리즈 목록
  const rows = []; // {name, pw} — 근사식·잔차 표
  for (const g of groups) {
    const list = [];
    for (const s of g.series) {
      const pw = piecewisePolyfit(g.mach, s.data, values, fitCfg.degree);
      if (pw.error) return { error: pw.error };
      const sm = sampleFit(pw);
      list.push({ label: "", data: sm.y, x: sm.x, color: s.color, dash: [5, 4], markers: false });
      rows.push({ name: `${g.group}.${s.label}`, pw });
    }
    overlays.set(g.group, list);
  }
  return { overlays, rows };
}

const SUP = ["", "", "²", "³", "⁴", "⁵", "⁶"];

function formulaText(fit) {
  let out = "";
  rawCoeffs(fit).forEach((v, k) => {
    const term = k === 0 ? fmt(Math.abs(v), 4) : `${fmt(Math.abs(v), 4)}·M${SUP[k]}`;
    if (k === 0) out = (v < 0 ? "−" : "") + term;
    else out += ` ${v < 0 ? "−" : "+"} ${term}`;
  });
  return out;
}

function fitDetails(rows) {
  return el("details", {
    open: fitCfg.detailsOpen,
    ontoggle: (ev) => { fitCfg.detailsOpen = ev.target.open; }, // 재그리기에도 접힘 유지
  },
    el("summary", {}, "근사식 계수·잔차·경계 연속성"),
    el("div", { class: "scroll-x" },
      el("table", { class: "fit-table" },
        el("thead", {}, el("tr", {},
          ["게인", "구간별 근사식 p(M)", "최대|잔차|", "RMS", "경계 점프 (값 / 기울기)"]
            .map((h) => el("th", {}, h)))),
        el("tbody", {}, rows.map(({ name, pw }) => el("tr", {},
          el("td", {}, name),
          el("td", { class: "col-lines" }, pw.segments.map((s) =>
            el("div", {}, `[M${fmt(s.x0, 3)}–M${fmt(s.x1, 3)}]  ${formulaText(s.fit)}`))),
          el("td", { class: "num" }, fmt(pw.maxResidual, 3)),
          el("td", { class: "num" }, fmt(pw.rms, 3)),
          el("td", { class: "col-lines" }, pw.joints.length
            ? pw.joints.map((j) => el("div", {},
                `M${fmt(j.x, 3)}: ${fmt(j.valueJump, 3)} / ${fmt(j.slopeJump, 3)}`))
            : "—"),
        ))))),
    el("p", { class: "hint" },
      "근사식은 검토·반출용 표시 — 시뮬 조회는 여전히 테이블 구간 선형 보간 (실주입은 백로그). ",
      "경계 점프 = 경계 마하에서 우측 구간식 − 좌측 구간식 (값·기울기). 허용치 판정은 설계자 소관 (01 §3.4)."));
}

function drawCharts(chartBox, fitStatus) {
  const { groups, skipped } = gainPlotGroups(tables);
  let overlays = null;
  let fitRows = [];
  fitStatus.textContent = "";
  if (fitCfg.show) {
    const r = computeFits(groups);
    if (r.error) fitStatus.textContent = `근사 불가: ${r.error}`;
    else { overlays = r.overlays; fitRows = r.rows; }
  }
  // 네이티브 append에 null·배열 직접 전달 금지 (문자열화 함정) — el 래핑으로 조립
  clear(chartBox).append(el("div", {},
    el("div", { class: "row" },
      groups.map(({ group, mach, series }) =>
        lineChartCanvas(mach, overlays ? [...series, ...overlays.get(group)] : series, {
          title: `${group} 게인`, width: 420, height: 200, xUnit: "M", markers: true,
        }))),
    el("p", { class: "hint" },
      "점 = 테이블 격자점(브레이크포인트), 실선 = 현재 조회 규칙(구간 선형 보간, 외삽 clip), ",
      "점선 = 구간별 다항식 회귀 근사 곡선(위 경계·차수 설정). 셀 편집 시 즉시 갱신."),
    skipped.length
      ? el("p", { class: "hint" },
          `차트 제외: ${skipped.map((s) => `${s.name} — ${s.reason}`).join(" · ")}`)
      : null,
    fitRows.length ? fitDetails(fitRows) : null,
  ));
}

function renderTables(box, statusLine) {
  const names = Object.keys(tables);
  const machs = tables[names[0]].axes.mach;
  const chartBox = el("div");
  const fitStatus = el("span", { class: "hint" });
  const redraw = () => drawCharts(chartBox, fitStatus);
  // 컨트롤은 redraw 대상 밖 — 입력 도중 재그리기로 포커스를 잃지 않게
  const fitControls = el("div", { class: "row" },
    el("label", {},
      el("input", {
        type: "checkbox", checked: fitCfg.show,
        onchange: (ev) => { fitCfg.show = ev.target.checked; redraw(); },
      }),
      " 근사 곡선(점선) 표시"),
    el("label", {}, "구간 경계 (마하, 쉼표 구분) ",
      el("input", {
        class: "num-sm", type: "text", value: fitCfg.boundaries,
        onchange: (ev) => { fitCfg.boundaries = ev.target.value; redraw(); },
      })),
    el("label", {}, "차수 ",
      el("input", {
        class: "num-sm", type: "number", min: "1", max: "6", step: "1",
        value: String(fitCfg.degree),
        onchange: (ev) => { fitCfg.degree = Number(ev.target.value); redraw(); },
      })),
    fitStatus,
  );
  redraw();
  // 전치 배열: 행 = 마하(비행조건), 열 = 게인 6개 — 폭이 패널에 들어오고
  // 한 비행조건의 게인 세트를 한 줄에서 편집
  clear(box).append(
    fitControls,
    chartBox,
    el("div", { class: "scroll-x" },
      el("table", {},
        el("thead", {}, el("tr", {},
          el("th", {}, "마하 \\ 게인"),
          names.map((name) => el("th", {}, name)))),
        el("tbody", {}, machs.map((m, i) => el("tr", {},
          el("td", {}, `M${m}`),
          names.map((name) => el("td", {},
            el("input", {
              class: "num-sm",
              type: "number",
              step: "any",
              value: String(tables[name].data[i]),
              onchange: (ev) => {
                // badInput(오타)이면 value가 ""가 되어 Number("")===0으로 제로
                // 게인이 조용히 주입됨 — 원복 + 경고 (리뷰 S2)
                const raw = ev.target.value.trim();
                const num = Number(raw);
                if (raw === "" || ev.target.validity.badInput || !Number.isFinite(num)) {
                  ev.target.value = String(tables[name].data[i]);
                  statusLine.textContent = `잘못된 수치 — M${m} ${name} 원복됨.`;
                  return;
                }
                tables[name].data[i] = num;
                redraw(); // 편집값 즉시 반영 (data 참조 공유) — 근사 곡선 포함
                statusLine.textContent = "편집됨 (미적용) — '시뮬에 적용'을 누르세요.";
              },
            }))),
        ))),
      ),
    ),
    el("p", { class: "hint" },
      "열 = \"그룹.게인\" (ScasAxis.step 덮어쓰기 인자), 행 = 스케줄 변수 마하. ",
      "외삽 clip 고정 — 그룹·키·형상 검증은 제출 시 엔진이 수행."),
  );
}
