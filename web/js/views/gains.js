/** 게인 스케줄 뷰 (02 §8 4단계) — 설계 테이블 조회 → 셀 편집 → 시뮬 주입 준비.

주입은 전체 교체 (엔진 make_demo_fcl 계약) — 편집본은 store("gainTables")로
시뮬레이션 탭에 전달. 검증(그룹·키·형상·유한성)은 제출 시 서버/엔진이 수행.
*/

import { api, errorText } from "../api.js";
import { clear, el, fmt } from "../dom.js";
import { store } from "../store.js";

let tables = null; // {name: {axes: {mach: [...]}, data: [...], extrapolate}}
let dirty = false;

export function render() {
  const box = el("div");
  const errBox = el("div");
  const statusLine = el("p", { class: "hint" });

  const load = async () => {
    try {
      clear(errBox);
      tables = await api.get("/gains/demo");
      dirty = false;
      renderTables(box, statusLine);
    } catch (e) {
      clear(errBox).append(el("div", { class: "error-box" }, errorText(e)));
    }
  };

  const root = el("div", {},
    el("div", { class: "panel" },
      el("h2", {}, "게인 스케줄 테이블 (동압 스케일 1D mach — 설계점 M0.6)"),
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

function renderTables(box, statusLine) {
  const names = Object.keys(tables);
  const machs = tables[names[0]].axes.mach;
  // 전치 배열: 행 = 마하(비행조건), 열 = 게인 6개 — 폭이 패널에 들어오고
  // 한 비행조건의 게인 세트를 한 줄에서 편집
  clear(box).append(
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
                const num = Number(ev.target.value);
                if (Number.isFinite(num)) {
                  tables[name].data[i] = num;
                  dirty = true;
                  statusLine.textContent = "편집됨 (미적용) — '시뮬에 적용'을 누르세요.";
                }
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
