/** 마진 맵 뷰 (02 §8 3단계) — 케이스 격자 + PI 루프 스펙 → 마진 맵·고유치·감쇠비.

수치는 전부 서버(엔진 linearize/classify/pi_loop) 산출 — 여기서는 표시만.
트림 가능/불가·판정 색상 맵은 트림 플래그 재사용 (02 §4).
*/

import { api, errorText } from "../api.js";
import { clear, el, fmt } from "../dom.js";
import { machRange, parseNumberList, serpentineCases } from "../lib/grid.js";
import { fuelsOf, marginColor, pivotCases } from "../lib/plot.js";
import { store } from "../store.js";
import { heatmapCanvas, scatterCanvas } from "./plots.js";
import { attachProgress, cancelledWithoutResult } from "./progress.js";

let lastBody = null;
let runningJobId = null;

export function render() {
  const errBox = el("div");
  const progressBox = el("div");
  const resultBox = el("div");

  const fMachFrom = el("input", { class: "num", value: "0.4" });
  const fMachTo = el("input", { class: "num", value: "0.8" });
  const fMachStep = el("input", { class: "num", value: "0.1" });
  const fAlts = el("input", { value: "100, 1000, 3000" });
  const fFuels = el("input", { class: "num", value: "200" });
  const fKp = el("input", { class: "num", value: "0.5" });
  const fKi = el("input", { class: "num", value: "0.8" });
  const fFp = el("input", { value: "web-margin-v1" });

  const showErr = (e) =>
    clear(errBox).append(el("div", { class: "error-box" }, errorText(e)));

  const watch = () => attachProgress(progressBox, runningJobId, {
    onDone: async (job) => {
      runningJobId = null;
      try {
        if (job.status === "error") throw new Error(job.error);
        if (cancelledWithoutResult(job)) {
          showErr(new Error("취소됨 — 저장된 결과 없음 (실행 전 취소)"));
          return;
        }
        lastBody = await api.get(`/results/${job.result_id}`);
        store.set("marginMap", { id: job.result_id });
        renderResults(resultBox, lastBody);
      } catch (e) {
        showErr(e);
      }
    },
    onError: (e) => {
      runningJobId = null;
      showErr(e);
    },
  });

  const run = async () => {
    if (runningJobId) return; // 이중 제출 방지 (리뷰 S4)
    try {
      clear(errBox);
      clear(resultBox);
      const cases = serpentineCases(
        machRange(Number(fMachFrom.value), Number(fMachTo.value), Number(fMachStep.value)),
        parseNumberList(fAlts.value),
        parseNumberList(fFuels.value),
      );
      const req = {
        cases,
        loops: [{
          name: "pitch_q", axis: "lon", x_out: "q", u_in: "de",
          kp: Number(fKp.value), ki: Number(fKi.value),
        }],
        fingerprint: fFp.value,
      };
      const submitted = await api.post("/analysis/margin-map", req);
      runningJobId = submitted.id;
      watch();
    } catch (e) {
      showErr(e);
    }
  };

  const root = el("div", {},
    el("div", { class: "panel" },
      el("h2", {}, "마진 맵 — 케이스 격자 × 피치레이트 PI 개루프 (δe → q)"),
      el("div", { class: "row" },
        el("label", { class: "field" }, "마하 시작", fMachFrom),
        el("label", { class: "field" }, "마하 끝", fMachTo),
        el("label", { class: "field" }, "간격", fMachStep),
        el("label", { class: "field grow" }, "고도 목록 [m]", fAlts),
        el("label", { class: "field" }, "연료 [kg]", fFuels),
        el("label", { class: "field" }, "kp", fKp),
        el("label", { class: "field" }, "ki", fKi),
        el("label", { class: "field" }, "지문", fFp),
        el("button", { class: "primary", onclick: run }, "실행"),
      ),
      el("p", { class: "hint" },
        "트림 → 선형화 → 모드 분류 → −PI·G(q←δe) 마진 (엔진 M9·M10). ",
        "상태색 [기본값]: PM ≥45° 양호 · 30~45° 주의 · <30° 부족 · 회색 = 트림 불가/판정 불가."),
      progressBox, errBox,
    ),
    el("div", { class: "panel" }, el("h2", {}, "대시보드"), resultBox),
  );
  if (lastBody) renderResults(resultBox, lastBody);
  if (runningJobId) watch(); // 실행 중 재진입 — 진행 UI 재부착 (리뷰 S4)
  return root;
}

function renderResults(resultBox, body) {
  const entries = body.cases;
  const fuels = fuelsOf(entries);
  const fuelSel = el("select", { "aria-label": "연료 선택" },
    fuels.map((f) => el("option", { value: f }, `연료 ${f} kg`)));
  const plotBox = el("div");
  const draw = () => {
    const fuel = Number(fuelSel.value);
    const pivot = pivotCases(entries, fuel);
    const pmMap = heatmapCanvas(pivot, (e) => {
      if (!e.trim.converged) return { color: "#9aa3ad", text: "트림×" };
      const pm = e.margins.pitch_q ? e.margins.pitch_q.pm_deg : null;
      return { color: marginColor(pm), text: `${fmt(pm, 3)}°` };
    }, { title: "위상여유 PM [deg] — pitch_q" });
    const gmMap = heatmapCanvas(pivot, (e) => {
      if (!e.trim.converged) return { color: "#9aa3ad", text: "트림×" };
      const gm = e.margins.pitch_q ? e.margins.pitch_q.gm_db : null;
      const color = gm === "inf" ? "#157f3d"
        : typeof gm !== "number" ? "#9aa3ad"
        : gm < 6 ? "#c22f2f" : gm < 10 ? "#b57908" : "#157f3d";
      return { color, text: gm === "inf" ? "∞ dB" : `${fmt(gm, 3)} dB` };
    }, { title: "이득여유 GM [dB] — pitch_q (≥6 dB [기본값])" });
    const points = [];
    for (const e of entries) {
      if (e.trim.case.fuel !== Number(fuelSel.value) || !e.lon) continue;
      for (const m of e.lon.modes) points.push({ x: m.eig[0], y: m.eig[1], color: "#1a6feb" });
      for (const m of e.lat.modes) points.push({ x: m.eig[0], y: m.eig[1], color: "#b57908" });
    }
    clear(plotBox).append(
      pmMap, gmMap,
      scatterCanvas(points, { title: "고유치 맵 (파랑=종축, 주황=횡축) — 허수축 좌측이 안정" }),
      el("div", { class: "legend" },
        el("span", {}, el("span", { class: "chip", style: "background:#157f3d" }), "양호"),
        el("span", {}, el("span", { class: "chip", style: "background:#b57908" }), "주의"),
        el("span", {}, el("span", { class: "chip", style: "background:#c22f2f" }), "부족"),
        el("span", {}, el("span", { class: "chip", style: "background:#9aa3ad" }), "트림 불가/판정 불가")),
      dampingTable(entries.filter((e) => e.trim.case.fuel === Number(fuelSel.value))),
    );
  };
  fuelSel.addEventListener("change", draw);
  clear(resultBox).append(el("div", { class: "row" }, fuelSel), plotBox);
  draw();
}

function dampingTable(entries) {
  const modeCell = (m) => (m ? `${fmt(m.wn, 3)} / ${fmt(m.zeta, 2)}` : "—");
  return el("table", {},
    el("thead", {}, el("tr", {},
      el("th", {}, "케이스"),
      el("th", {}, "단주기 wn/ζ"), el("th", {}, "장주기 wn/ζ"),
      el("th", {}, "더치롤 wn/ζ"), el("th", {}, "롤 λ"), el("th", {}, "나선 λ"))),
    el("tbody", {}, entries.map((e) => {
      const lonC = e.lon && e.lon.classified;
      const latC = e.lat && e.lat.classified;
      return el("tr", {},
        el("td", {}, e.trim.case.name),
        el("td", { class: "num" }, modeCell(lonC && lonC.short_period)),
        el("td", { class: "num" }, modeCell(lonC && lonC.phugoid)),
        el("td", { class: "num" }, modeCell(latC && latC.dutch_roll)),
        el("td", { class: "num" }, latC ? fmt(latC.roll.eig[0], 3) : "—"),
        el("td", { class: "num" }, latC ? fmt(latC.spiral.eig[0], 3) : "—"),
      );
    })),
  );
}
