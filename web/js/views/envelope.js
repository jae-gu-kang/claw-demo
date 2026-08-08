/** 엔벨로프 뷰 — V-n 보호 경계 (01 §3.6). 수치는 전부 엔진 vn_stall_boundary.

실속 경계(공력 한계)와 α 리미터 보호 경계는 실계산으로 그린다. 구조 한계(±n)·
급강하 한계속도 V_D는 [TBD] — 데이터가 없으므로 선을 지어내지 않고 주석으로만
표기한다. 음의 실속 경계도 실속 테이블(정 α만)의 범위 밖이라 미표시.
*/

import { api, errorText } from "../api.js";
import { clear, el, fmt } from "../dom.js";
import { lineChartCanvas } from "./plots.js";

let lastBody = null;

export function render() {
  const errBox = el("div");
  const plotBox = el("div");
  const fAlt = el("input", { class: "num", value: "1000" });
  const fFuel = el("input", { class: "num", value: "200" });
  const fMargin = el("input", { class: "num", value: "0.05" });

  const draw = async () => {
    try {
      clear(errBox);
      lastBody = await api.get(
        `/analysis/vn-envelope?alt=${Number(fAlt.value)}&fuel=${Number(fFuel.value)}`
        + `&alpha_margin=${Number(fMargin.value)}`,
      );
      renderPlot(plotBox, lastBody);
    } catch (e) {
      clear(errBox).append(el("div", { class: "error-box" }, errorText(e)));
    }
  };

  const root = el("div", {},
    el("div", { class: "panel" },
      el("h2", {}, "V-n 보호 경계 (flight envelope protection)"),
      el("div", { class: "row" },
        el("label", { class: "field" }, "고도 [m]", fAlt),
        el("label", { class: "field" }, "연료 [kg]", fFuel),
        el("label", { class: "field" }, "보호 마진 [rad]", fMargin),
        el("button", { class: "primary", onclick: draw }, "그리기"),
      ),
      el("p", { class: "hint" },
        "n = L(α경계)/W — δe=0·준정적·ISA. 실속선 = α_stall(M), ",
        "보호선 = α 리미터 경계(α_stall − 마진, 기본 0.05 rad = 리미터 [기본값])."),
      errBox,
    ),
    el("div", { class: "panel" }, plotBox),
  );
  if (lastBody) renderPlot(plotBox, lastBody);
  else draw();
  return root;
}

function renderPlot(plotBox, body) {
  const ones = body.V.map(() => 1.0); // n=1 수평비행 기준선
  clear(plotBox).append(
    lineChartCanvas(body.V, [
      { label: "실속 경계", data: body.n_stall, color: "#c22f2f" },
      { label: "α 리미터 보호", data: body.n_prot, color: "#157f3d" },
      { label: "n=1", data: ones, color: "#9aa3ad" },
    ], {
      title: `n [g] — h ${fmt(body.alt, 4)} m · 연료 ${fmt(body.fuel, 4)} kg`,
      width: 720, height: 320, xUnit: " m/s",
    }),
    el("div", { class: "legend" },
      el("span", {}, el("span", { class: "chip", style: "background:#c22f2f" }),
        "실속 경계 (공력 한계 — 이 위쪽 불가)"),
      el("span", {}, el("span", { class: "chip", style: "background:#157f3d" }),
        "α 리미터 보호 경계 (법칙이 명령을 자르는 선)"),
      el("span", {}, el("span", { class: "chip", style: "background:#9aa3ad" }),
        "n=1 수평비행")),
    el("p", { class: "hint" },
      "구조 한계 ±n · 급강하 한계속도 V_D: [TBD] — 구조하중 데이터 확보 시 표시 ",
      "(Nz 제한 기능 필요 여부도 01 §3.6 [TBD]). 음의 실속 경계는 실속 테이블(정 α만) 범위 밖. ",
      "보호선과 n=1의 교점 좌측이 α 리미터가 수평비행을 지켜줄 수 없는 저속 영역."),
  );
}
