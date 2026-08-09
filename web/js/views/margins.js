/** 마진 맵 뷰 (02 §8 3단계) — 케이스 격자 × PI 개루프(다중) → 마진 맵·고유치·감쇠비.

수치는 전부 서버(엔진 linearize/classify/pi_loop) 산출 — 여기서는 표시만.
루프 스펙(축·출력 상태·입력·kp·ki·sign)은 행 편집 — 서버 loops[] 계약 그대로
("설계값은 요청이 보유"). 사전검증은 lib/loops.js, 최종 판정은 서버 422.
트림 가능/불가·판정 색상 맵은 트림 플래그 재사용 (02 §4).
*/

import { api, errorText } from "../api.js";
import { clear, el, fmt } from "../dom.js";
import { machRange, parseNumberList, serpentineCases } from "../lib/grid.js";
import { AXIS_NAMES, DEFAULT_LOOPS, validateLoops } from "../lib/loops.js";
import { fuelsOf, marginColor, pivotCases } from "../lib/plot.js";
import { store } from "../store.js";
import { heatmapCanvas, scatterCanvas } from "./plots.js";
import { attachProgress, cancelledWithoutResult } from "./progress.js";

let lastBody = null;
let runningJobId = null;
// 탭 재진입에도 루프 편집 상태 유지 (수치는 입력 문자열 — 제출 시 파싱)
let loopRows = DEFAULT_LOOPS.map((r) => ({ ...r }));

export function render() {
  const errBox = el("div");
  const progressBox = el("div");
  const resultBox = el("div");
  const loopBox = el("div");

  const fMachFrom = el("input", { class: "num", value: "0.4" });
  const fMachTo = el("input", { class: "num", value: "0.8" });
  const fMachStep = el("input", { class: "num", value: "0.1" });
  const fAlts = el("input", { value: "100, 1000, 3000" });
  const fFuels = el("input", { class: "num", value: "200" });
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
      const v = validateLoops(loopRows);
      if (v.errors) {
        clear(errBox).append(el("div", { class: "error-box" }, v.errors.join("\n")));
        return;
      }
      clear(resultBox);
      const cases = serpentineCases(
        machRange(Number(fMachFrom.value), Number(fMachTo.value), Number(fMachStep.value)),
        parseNumberList(fAlts.value),
        parseNumberList(fFuels.value),
      );
      const req = { cases, loops: v.loops, fingerprint: fFp.value };
      const submitted = await api.post("/analysis/margin-map", req);
      runningJobId = submitted.id;
      watch();
    } catch (e) {
      showErr(e);
    }
  };

  renderLoopEditor(loopBox);
  const root = el("div", {},
    el("div", { class: "panel" },
      el("h2", {}, "마진 맵 — 케이스 격자 × PI 개루프 (다중)"),
      el("div", { class: "row" },
        el("label", { class: "field" }, "마하 시작", fMachFrom),
        el("label", { class: "field" }, "마하 끝", fMachTo),
        el("label", { class: "field" }, "간격", fMachStep),
        el("label", { class: "field grow" }, "고도 목록 [m]", fAlts),
        el("label", { class: "field" }, "연료 [kg]", fFuels),
        el("label", { class: "field" }, "지문", fFp),
        el("button", { class: "primary", onclick: run }, "실행"),
      ),
      loopBox,
      el("p", { class: "hint" },
        "트림 → 선형화 → 모드 분류 → 루프별 sign·PI·G(x_out←u_in) 마진 (엔진 M9·M10). ",
        "루프를 전부 지우면 고유치·감쇠비만 계산. 선형모델은 현재 플랜트 단독 — ",
        "작동기·지연 미포함 마진은 낙관적 (01 §4.2), 최종 확인은 시뮬 검증으로. ",
        "상태색 [기본값]: PM ≥45° 양호 · 30~45° 주의 · <30° 부족 · GM ≥10 dB 양호 · ",
        "6~10 주의 · <6 부족 · 회색 = 트림 불가/판정 불가."),
      progressBox, errBox,
    ),
    el("div", { class: "panel" }, el("h2", {}, "대시보드"), resultBox),
  );
  if (lastBody) renderResults(resultBox, lastBody);
  if (runningJobId) watch(); // 실행 중 재진입 — 진행 UI 재부착 (리뷰 S4)
  return root;
}

// ── 루프 스펙 편집 표 ──────────────────────────────────────────────────

function renderLoopEditor(loopBox) {
  const numCell = (row, key) => el("input", {
    class: "num-sm", value: String(row[key]),
    oninput: (ev) => { row[key] = ev.target.value; },
  });
  const nameSel = (row, key, names) => el("select", {
    onchange: (ev) => { row[key] = ev.target.value; },
  }, names.map((n) => el("option", { value: n, selected: n === row[key] }, n)));

  const rowTr = (row) => {
    // 축 변경 시 상태·입력 선택지를 그 축 이름으로 재구성 (기존 값 무효 시 첫 항목)
    const xTd = el("td");
    const uTd = el("td");
    const fillSelects = () => {
      const ax = AXIS_NAMES[row.axis];
      if (!ax.states.includes(row.x_out)) row.x_out = ax.states[0];
      if (!ax.inputs.includes(row.u_in)) row.u_in = ax.inputs[0];
      clear(xTd).append(nameSel(row, "x_out", ax.states));
      clear(uTd).append(nameSel(row, "u_in", ax.inputs));
    };
    fillSelects();
    return el("tr", {},
      el("td", {}, el("input", {
        style: "width: 110px", value: row.name,
        oninput: (ev) => { row.name = ev.target.value; },
      })),
      el("td", {}, el("select", {
        onchange: (ev) => { row.axis = ev.target.value; fillSelects(); },
      }, ["lon", "lat"].map((a) =>
        el("option", { value: a, selected: a === row.axis }, a === "lon" ? "종축 (lon)" : "횡축 (lat)")))),
      xTd, uTd,
      el("td", {}, numCell(row, "kp")),
      el("td", {}, numCell(row, "ki")),
      el("td", {}, numCell(row, "sign")),
      el("td", {}, el("button", {
        class: "danger",
        onclick: () => {
          loopRows = loopRows.filter((r) => r !== row);
          renderLoopEditor(loopBox);
        },
      }, "삭제")),
    );
  };

  clear(loopBox).append(
    el("div", { class: "scroll-x", style: "margin-top: 10px" }, el("table", {},
      el("thead", {}, el("tr", {},
        el("th", {}, "루프 이름"), el("th", {}, "축"), el("th", {}, "출력 상태"),
        el("th", {}, "입력"), el("th", {}, "kp"), el("th", {}, "ki"),
        el("th", {}, "sign"), el("th", {}, ""))),
      el("tbody", {}, loopRows.map(rowTr)))),
    el("div", { class: "row", style: "margin-top: 8px" },
      el("button", {
        onclick: () => {
          loopRows.push({
            name: `loop_${loopRows.length + 1}`, axis: "lon", x_out: "q", u_in: "de",
            kp: "0.5", ki: "0", sign: "-1",
          });
          renderLoopEditor(loopBox);
        },
      }, "루프 추가"),
      el("button", {
        onclick: () => {
          loopRows = DEFAULT_LOOPS.map((r) => ({ ...r }));
          renderLoopEditor(loopBox);
        },
      }, "3축 프리셋 복원"),
    ),
  );
}

// ── 결과 대시보드 ──────────────────────────────────────────────────────

function gmColor(gm) {
  if (gm === "inf") return "#157f3d";
  if (typeof gm !== "number") return "#9aa3ad";
  return gm < 6 ? "#c22f2f" : gm < 10 ? "#b57908" : "#157f3d";
}

/** 결과에 포함된 루프 스펙 — 저장 결과의 loops가 정본 (재열람 시 폼 상태와 무관).
구형 결과 폴백: 케이스 margins 키에서 이름만 복원. */
function loopsOf(body) {
  if (body.loops?.length) return body.loops;
  const withMargins = (body.cases ?? []).find((e) => Object.keys(e.margins ?? {}).length);
  return Object.keys(withMargins?.margins ?? {}).map((name) => ({ name }));
}

function renderResults(resultBox, body) {
  const entries = body.cases;
  const loops = loopsOf(body);
  const fuels = fuelsOf(entries);
  const fuelSel = el("select", { "aria-label": "연료 선택" },
    fuels.map((f) => el("option", { value: f }, `연료 ${f} kg`)));
  const plotBox = el("div");
  const draw = () => {
    const fuel = Number(fuelSel.value);
    const pivot = pivotCases(entries, fuel);
    const loopPlots = loops.flatMap((lp) => {
      const label = lp.x_out
        ? `${lp.name} — ${lp.sign < 0 ? "−" : "+"}PI·G(${lp.x_out} ← ${lp.u_in}) [${lp.axis}]`
        : lp.name;
      return [
        el("h3", { style: "font-size: 13px; margin: 14px 0 4px" }, label),
        heatmapCanvas(pivot, (e) => {
          if (!e.trim.converged) return { color: "#9aa3ad", text: "트림×" };
          const pm = e.margins[lp.name] ? e.margins[lp.name].pm_deg : null;
          return { color: marginColor(pm), text: `${fmt(pm, 3)}°` };
        }, { title: `위상여유 PM [deg] — ${lp.name}` }),
        heatmapCanvas(pivot, (e) => {
          if (!e.trim.converged) return { color: "#9aa3ad", text: "트림×" };
          const gm = e.margins[lp.name] ? e.margins[lp.name].gm_db : null;
          return { color: gmColor(gm), text: gm === "inf" ? "∞ dB" : `${fmt(gm, 3)} dB` };
        }, { title: `이득여유 GM [dB] — ${lp.name} (≥6 dB [기본값])` }),
      ];
    });
    const points = [];
    for (const e of entries) {
      if (e.trim.case.fuel !== fuel || !e.lon) continue;
      for (const m of e.lon.modes) points.push({ x: m.eig[0], y: m.eig[1], color: "#1a6feb" });
      for (const m of e.lat.modes) points.push({ x: m.eig[0], y: m.eig[1], color: "#b57908" });
    }
    clear(plotBox).append(
      loopPlots,
      scatterCanvas(points, { title: "고유치 맵 (파랑=종축, 주황=횡축) — 허수축 좌측이 안정" }),
      el("div", { class: "legend" },
        el("span", {}, el("span", { class: "chip", style: "background:#157f3d" }), "양호"),
        el("span", {}, el("span", { class: "chip", style: "background:#b57908" }), "주의"),
        el("span", {}, el("span", { class: "chip", style: "background:#c22f2f" }), "부족"),
        el("span", {}, el("span", { class: "chip", style: "background:#9aa3ad" }), "트림 불가/판정 불가")),
      dampingTable(entries.filter((e) => e.trim.case.fuel === fuel)),
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
