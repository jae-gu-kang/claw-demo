/** 게인 스케줄 뷰 (02 §8 4단계) — 설계 테이블 조회 → 셀 편집 → 시뮬 주입 준비.

주입은 전체 교체 (엔진 make_demo_fcl 계약) — 편집본은 store("gainTables")로
시뮬레이션 탭에 전달. 검증(그룹·키·형상·유한성)은 제출 시 서버/엔진이 수행.
*/

import { api, errorText } from "../api.js";
import { clear, el, fmt } from "../dom.js";
import { gainPlotGroups } from "../lib/plot.js";
import { store } from "../store.js";
import { lineChartCanvas } from "./plots.js";

let tables = null; // {name: {axes: {mach: [...]}, data: [...], extrapolate}}

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

function drawCharts(chartBox) {
  const { groups, skipped } = gainPlotGroups(tables);
  // 네이티브 append에 null·배열 직접 전달 금지 (문자열화 함정) — el 래핑으로 조립
  clear(chartBox).append(el("div", {},
    el("div", { class: "row" },
      groups.map(({ group, mach, series }) =>
        lineChartCanvas(mach, series, {
          title: `${group} 게인`, width: 420, height: 200, xUnit: "M", markers: true,
        }))),
    el("p", { class: "hint" },
      "점 = 테이블 격자점(브레이크포인트), 선 = 현재 조회 규칙(구간 선형 보간, 외삽 clip). ",
      "셀 편집 시 즉시 갱신. 구간별 다항식 회귀 근사식 피팅·오버레이는 [백로그] (01 §3.4)."),
    skipped.length
      ? el("p", { class: "hint" },
          `차트 제외: ${skipped.map((s) => `${s.name} — ${s.reason}`).join(" · ")}`)
      : null,
  ));
}

function renderTables(box, statusLine) {
  const names = Object.keys(tables);
  const machs = tables[names[0]].axes.mach;
  const chartBox = el("div");
  drawCharts(chartBox);
  // 전치 배열: 행 = 마하(비행조건), 열 = 게인 6개 — 폭이 패널에 들어오고
  // 한 비행조건의 게인 세트를 한 줄에서 편집
  clear(box).append(
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
                drawCharts(chartBox); // 편집값 즉시 반영 (data 참조 공유)
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
