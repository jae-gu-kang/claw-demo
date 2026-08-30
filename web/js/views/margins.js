/** 마진 맵 뷰 (02 §8 3단계) — 케이스 격자 × PI 개루프(다중) → 마진 맵·고유치·감쇠비.

수치는 전부 서버(엔진 linearize/classify/pi_loop) 산출 — 여기서는 표시만.
루프 스펙(축·출력 상태·입력·kp·ki·sign)은 행 편집 — 서버 loops[] 계약 그대로
("설계값은 요청이 보유"). 사전검증은 lib/loops.js, 최종 판정은 서버 422.
트림 가능/불가·판정 색상 맵은 트림 플래그 재사용 (02 §4).
*/

import { api, errorText } from "../api.js";
import { clear, el, fmt } from "../dom.js";
import { machRange, parseNumberList, serpentineCases } from "../lib/grid.js";
import { AXIS_NAMES, DEFAULT_LOOPS, validateActuatorDelay, validateLoops } from "../lib/loops.js";
import { STATUS, fuelsOf, marginColor, pivotCases } from "../lib/plot.js";
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
  // 작동기·지연 포함 — [기본값 01 §4.2] 체크 ON으로 시작, 꺼서 영향 분리 비교 가능
  const fUseAct = el("input", { type: "checkbox", checked: true });
  const fWn = el("input", { class: "num-sm", value: "30" });
  const fZeta = el("input", { class: "num-sm", value: "0.7" });
  const fUseDelay = el("input", { type: "checkbox", checked: true });
  const fDelay = el("input", { class: "num-sm", value: "0.035" });
  const fPade = el("input", { class: "num-sm", value: "2" });

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
        // 결과는 아래 대시보드 패널에 그려짐 — 폼이 길어 뷰포트 밖일 수 있으니 이동
        resultBox.scrollIntoView?.({ behavior: "smooth", block: "start" });
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
    if (runningJobId) { // 이중 제출 방지 (리뷰 S4) — 무반응 대신 안내 (조용한 무시 금지)
      clear(errBox).append(el("div", { class: "error-box" },
        "이미 실행 중입니다 — 진행률 표시를 확인하세요."));
      return;
    }
    try {
      clear(errBox);
      const v = validateLoops(loopRows);
      const ad = validateActuatorDelay({
        useActuator: fUseAct.checked, wn: fWn.value, zeta: fZeta.value,
        useDelay: fUseDelay.checked, delaySeconds: fDelay.value, padeOrder: fPade.value,
      });
      const errs = [...(v.errors ?? []), ...(ad.errors ?? [])];
      if (errs.length) {
        clear(errBox).append(el("div", { class: "error-box" }, errs.join("\n")));
        return;
      }
      clear(resultBox);
      const cases = serpentineCases(
        machRange(Number(fMachFrom.value), Number(fMachTo.value), Number(fMachStep.value)),
        parseNumberList(fAlts.value),
        parseNumberList(fFuels.value),
      );
      const req = {
        cases, loops: v.loops, fingerprint: fFp.value,
        actuator: ad.actuator, delay_s: ad.delay_s, pade_order: ad.pade_order,
      };
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
      el("div", { class: "field-grid", style: "margin-top: 10px" },
        el("div", { class: "opt-group" },
          el("div", { class: "g-title" }, "작동기 포함 (2차계 — plant.actuator와 동일 모델)"),
          el("div", { class: "row-inner" },
            el("label", { class: "field check" }, fUseAct, "포함"),
            el("label", { class: "field" }, "wn [rad/s]", fWn),
            el("label", { class: "field" }, "ζ", fZeta))),
        el("div", { class: "opt-group" },
          el("div", { class: "g-title" }, "지연 포함 (항법 출력 + 제어주기 — Padé 근사)"),
          el("div", { class: "row-inner" },
            el("label", { class: "field check" }, fUseDelay, "포함"),
            el("label", { class: "field" }, "총 지연 [s]", fDelay),
            el("label", { class: "field" }, "Padé 차수", fPade))),
      ),
      el("p", { class: "hint" },
        "트림 → 선형화 → 모드 분류 → 루프별 sign·PI·G(x_out←u_in) 마진 (엔진 M9·M10). ",
        "루프를 전부 지우면 고유치·감쇠비만 계산. 작동기·지연 미포함 마진은 낙관적 ",
        "(01 §4.2) — 기본은 포함, 체크 해제로 영향 분리 비교. 지연 기본값 0.035 s = ",
        "항법 출력 지연 0.03 s [기본값] + 제어주기(100 Hz) 등가지연 0.005 s. ",
        "상태색 [기본값]: PM ≥45° 양호 · 30~45° 주의 · <30° 부족 · GM ≥8 dB 양호 · ",
        "6~8 주의 · <6 부족 · 회색 = 트림 불가/판정 불가."),
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
          let i = loopRows.length + 1; // 삭제 후 추가해도 유일 이름 (리뷰 사소)
          while (loopRows.some((r) => r.name === `loop_${i}`)) i += 1;
          loopRows.push({
            name: `loop_${i}`, axis: "lon", x_out: "q", u_in: "de",
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

// 음영 문턱은 엔진 MarginCriteria(design/criteria.py)의 합격선 6 dB·목표선 8 dB와
// 같은 값이다 — 자동 설계 탭이 ok로 찍은 수치가 여기서 주의로 뜨면 같은 GM을 두 탭이
// 다르게 판정하는 셈이 된다. 목표선 8은 튜너 목표(TuneTargets.gm_db)와도 같은 값이라
// 세 자리가 한 수치를 공유한다 (하드코딩은 폴백 — 정본은 /design/defaults)
function gmColor(gm) {
  if (gm === "inf") return STATUS.ok;
  if (typeof gm !== "number") return STATUS.na;
  return gm < 6 ? STATUS.bad : gm < 8 ? STATUS.warn : STATUS.ok;
}

/** 결과에 포함된 루프 스펙 — 저장 결과의 loops가 정본 (재열람 시 폼 상태와 무관).
구형 결과 폴백: 케이스 margins 키에서 이름만 복원. */
function loopsOf(body) {
  if (body.loops?.length) return body.loops;
  const withMargins = (body.cases ?? []).find((e) => Object.keys(e.margins ?? {}).length);
  return Object.keys(withMargins?.margins ?? {}).map((name) => ({ name }));
}

/** 저장 결과의 작동기·지연 적용값 요약 — 재열람 시 현재 폼 상태와 무관하게
그 결과가 실제로 무엇을 포함해 계산됐는지 확인 (구형 결과는 필드 자체가 없음). */
function appliedSummary(body) {
  const act = body.actuator
    ? `작동기 포함 (wn=${body.actuator.wn} rad/s, ζ=${body.actuator.zeta})`
    : "작동기 미포함";
  const delay = body.delay_s > 0
    ? `지연 포함 (${body.delay_s} s, Padé ${body.pade_order}차)`
    : "지연 미포함";
  return `${act} · ${delay}`;
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
          if (!e.trim.converged) return { color: STATUS.na, text: "트림×" };
          const pm = e.margins[lp.name] ? e.margins[lp.name].pm_deg : null;
          return { color: marginColor(pm), text: `${fmt(pm, 3)}°` };
        }, { title: `위상여유 PM [deg] — ${lp.name}` }),
        heatmapCanvas(pivot, (e) => {
          if (!e.trim.converged) return { color: STATUS.na, text: "트림×" };
          const gm = e.margins[lp.name] ? e.margins[lp.name].gm_db : null;
          return { color: gmColor(gm), text: gm === "inf" ? "∞ dB" : `${fmt(gm, 3)} dB` };
        }, { title: `이득여유 GM [dB] — ${lp.name} (≥6 dB [기본값])` }),
      ];
    });
    const points = [];
    for (const e of entries) {
      if (e.trim.case.fuel !== fuel || !e.lon) continue;
      for (const m of e.lon.modes) points.push({ x: m.eig[0], y: m.eig[1], color: "#007aff" });
      for (const m of e.lat.modes) points.push({ x: m.eig[0], y: m.eig[1], color: "#ff9500" });
    }
    clear(plotBox).append(
      // el() 래핑 필수 — 네이티브 append는 배열을 문자열화 (리뷰 Must: 상습 함정군)
      el("div", {}, loopPlots),
      scatterCanvas(points, { title: "고유치 맵 (파랑=종축, 주황=횡축) — 허수축 좌측이 안정" }),
      el("div", { class: "legend" },
        el("span", {}, el("span", { class: "chip", style: `background:${STATUS.ok}` }), "양호"),
        el("span", {}, el("span", { class: "chip", style: `background:${STATUS.warn}` }), "주의"),
        el("span", {}, el("span", { class: "chip", style: `background:${STATUS.bad}` }), "부족"),
        el("span", {}, el("span", { class: "chip", style: `background:${STATUS.na}` }), "트림 불가/판정 불가")),
      dampingTable(entries.filter((e) => e.trim.case.fuel === fuel)),
    );
  };
  fuelSel.addEventListener("change", draw);
  clear(resultBox).append(
    el("p", {}, el("b", {}, `계산 완료 — 케이스 ${entries.length}건 · 루프 ${loops.length}개`)),
    el("p", { class: "hint" }, appliedSummary(body)),
    el("div", { class: "row" }, fuelSel), plotBox);
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
