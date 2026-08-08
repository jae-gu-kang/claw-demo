/** 트림 뷰 (02 §8 2단계) — 케이스 매트릭스 편집 → 배치 실행(진행률·취소) → 결과표.

DOM 조립 전용 (얇게) — 격자 로직은 lib/grid.js, 수치·판정은 전부 서버(엔진) 산출.
*/

import { api, errorText } from "../api.js";
import { clear, el, flagBadge, fmt } from "../dom.js";
import { machRange, parseNumberList, serpentineCases } from "../lib/grid.js";
import { store } from "../store.js";
import { attachProgress, cancelledWithoutResult } from "./progress.js";

// 모듈 상태 — 탭 재진입 시 유지 (실행 중 작업 재부착 포함, 리뷰 S4)
let cases = [];
let lastBody = null;
let runningJobId = null;
let runningFp = "";

const FLAG_COLS = [
  ["residual_ok", "잔차"],
  ["saturation_ok", "포화"],
  ["alpha_margin_ok", "α여유"],
  ["continuity_ok", "연속성"],
];

export function render() {
  const caseBox = el("div");
  const progressBox = el("div");
  const resultBox = el("div");
  const errBox = el("div");

  const fMachFrom = el("input", { class: "num", value: "0.4" });
  const fMachTo = el("input", { class: "num", value: "0.8" });
  const fMachStep = el("input", { class: "num", value: "0.1" });
  const fAlts = el("input", { value: "100, 1000, 3000" });
  const fFuels = el("input", { class: "num", value: "200" });
  const fFp = el("input", { value: "web-trim-v1" });

  const makeGrid = () => {
    try {
      clear(errBox);
      cases = serpentineCases(
        machRange(Number(fMachFrom.value), Number(fMachTo.value), Number(fMachStep.value)),
        parseNumberList(fAlts.value),
        parseNumberList(fFuels.value),
      );
      renderCases(caseBox, progressBox, errBox, resultBox);
    } catch (e) {
      showError(errBox, e);
    }
  };

  const root = el("div", {},
    el("div", { class: "panel" },
      el("h2", {}, "트림 케이스 매트릭스 (격자 생성 — 서펜타인 순서)"),
      el("div", { class: "row" },
        el("label", { class: "field" }, "마하 시작", fMachFrom),
        el("label", { class: "field" }, "마하 끝", fMachTo),
        el("label", { class: "field" }, "간격", fMachStep),
        el("label", { class: "field grow" }, "고도 목록 [m]", fAlts),
        el("label", { class: "field" }, "연료 [kg]", fFuels),
        el("label", { class: "field" }, "지문(fingerprint)", fFp),
        el("button", { onclick: makeGrid }, "격자 생성"),
      ),
      el("p", { class: "hint" },
        "리스트상 인접 케이스가 물리적으로도 인접하도록 행마다 마하 방향을 뒤집는다",
        " — 배치 트림의 인접 시드·연속성 판정 전제 (01 §4.1)."),
    ),
    el("div", { class: "panel" },
      el("h2", {}, "케이스 목록"),
      caseBox, progressBox, errBox,
    ),
    el("div", { class: "panel" }, el("h2", {}, "결과"), resultBox),
  );

  // 실행 클로저에 지문 접근을 넘기기 위해 보관
  caseBox._fp = fFp;
  renderCases(caseBox, progressBox, errBox, resultBox);
  if (lastBody) renderResults(resultBox, lastBody);
  if (runningJobId) watchTrim(caseBox, progressBox, errBox, resultBox); // 재부착
  return root;
}

function renderCases(caseBox, progressBox, errBox, resultBox) {
  clear(caseBox);
  if (!cases.length) {
    caseBox.append(el("p", { class: "hint" }, "격자를 생성하거나 행을 추가하세요."));
  } else {
    caseBox.append(el("table", {},
      el("thead", {}, el("tr", {},
        el("th", {}, "#"), el("th", {}, "마하"), el("th", {}, "고도 [m]"),
        el("th", {}, "연료 [kg]"), el("th", {}, ""))),
      el("tbody", {}, cases.map((c, i) => el("tr", {},
        el("td", {}, i + 1),
        el("td", { class: "num" }, fmt(c.mach)),
        el("td", { class: "num" }, fmt(c.alt)),
        el("td", { class: "num" }, fmt(c.fuel)),
        el("td", {}, el("button", {
          class: "danger",
          onclick: () => {
            cases.splice(i, 1);
            renderCases(caseBox, progressBox, errBox, resultBox);
          },
        }, "삭제")),
      ))),
    ));
  }
  caseBox.append(el("div", { class: "row" },
    el("button", {
      onclick: () => {
        cases.push({ mach: 0.6, alt: 1000, fuel: 200 });
        renderCases(caseBox, progressBox, errBox, resultBox);
      },
    }, "행 추가"),
    el("button", {
      class: "primary",
      disabled: !cases.length || !!runningJobId, // 이중 제출 방지 (리뷰 S4)
      onclick: () => runBatch(caseBox, progressBox, errBox, resultBox),
    }, runningJobId ? "실행 중…" : `배치 실행 (${cases.length}케이스)`),
  ));
}

async function runBatch(caseBox, progressBox, errBox, resultBox) {
  if (runningJobId) return;
  clear(errBox);
  clear(resultBox);
  runningFp = caseBox._fp ? caseBox._fp.value : "";
  try {
    const submitted = await api.post("/trim/batch", { cases, fingerprint: runningFp });
    runningJobId = submitted.id;
    renderCases(caseBox, progressBox, errBox, resultBox); // 버튼 비활성 반영
    watchTrim(caseBox, progressBox, errBox, resultBox);
  } catch (e) {
    showError(errBox, e);
  }
}

function watchTrim(caseBox, progressBox, errBox, resultBox) {
  attachProgress(progressBox, runningJobId, {
    onDone: async (job) => {
      runningJobId = null;
      renderCases(caseBox, progressBox, errBox, resultBox);
      try {
        if (job.status === "error") throw new Error(job.error);
        if (cancelledWithoutResult(job)) {
          showError(errBox, new Error("취소됨 — 저장된 결과 없음 (실행 전 취소)"));
          return;
        }
        const body = await api.get(`/results/${job.result_id}`);
        lastBody = body;
        store.set("trimResult", { id: job.result_id, fingerprint: runningFp, cases: [...cases] });
        renderResults(resultBox, body);
      } catch (e) {
        showError(errBox, e);
      }
    },
    onError: (e) => {
      runningJobId = null;
      renderCases(caseBox, progressBox, errBox, resultBox);
      showError(errBox, e);
    },
  });
}

function renderResults(resultBox, body) {
  const rows = body.results;
  const nOk = rows.filter((r) => r.converged).length;
  const nBad = rows.filter(
    (r) => !Object.values(r.flags).every((v) => v !== false),
  ).length;
  clear(resultBox).append(
    el("p", {},
      `수렴 ${nOk}/${rows.length} · 판정 플래그 위반 ${nBad}건`,
      nBad === 0 && nOk === rows.length
        ? el("span", { class: "flag ok", style: "margin-left:8px" }, "전체 정상")
        : el("span", { class: "flag bad", style: "margin-left:8px" }, "확인 필요")),
    el("table", {},
      el("thead", {}, el("tr", {},
        el("th", {}, "케이스"), el("th", {}, "수렴"),
        el("th", {}, "θ [rad]"), el("th", {}, "δe [rad]"), el("th", {}, "스로틀"),
        FLAG_COLS.map(([, title]) => el("th", {}, title)))),
      el("tbody", {}, rows.map((r) => el("tr", {},
        el("td", {}, r.case.name),
        el("td", {}, flagBadge(r.converged, "수렴", "실패")),
        el("td", { class: "num" }, fmt(r.euler[1], 4)),
        el("td", { class: "num" }, fmt(r.control.elevon[0], 4)),
        el("td", { class: "num" }, fmt(r.control.throttle[0], 3)),
        FLAG_COLS.map(([key]) => el("td", {}, flagBadge(r.flags[key]))),
      ))),
    ),
  );
}

function showError(errBox, e) {
  clear(errBox).append(el("div", { class: "error-box" }, errorText(e)));
}
