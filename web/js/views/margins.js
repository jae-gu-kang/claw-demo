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
import {
  FALLBACK_CRITERIA, STATUS, fuelsOf, gmColor, heatmapCanvasHeight, heatmapCellAt, marginColor,
  marginLegendText, pivotCases, threshold,
} from "../lib/plot.js";
import { toCanvasXY } from "../lib/wpmap.js";
import { store } from "../store.js";
import { bodeCanvas, heatmapCanvas, scatterCanvas } from "./plots.js";
import { attachProgress, cancelledWithoutResult } from "./progress.js";

let lastBody = null;
let runningJobId = null;
// 탭 재진입에도 루프 편집 상태 유지 (수치는 입력 문자열 — 제출 시 파싱)
let loopRows = DEFAULT_LOOPS.map((r) => ({ ...r }));
// 판정선 — 정본은 /design/defaults(엔진 MarginCriteria). 하드코딩 폴백을 쓰면
// 자동 설계 탭에서 기준을 바꿨을 때 같은 점을 두 탭이 다르게 칠한다 (lib/plot.js
// FALLBACK_CRITERIA 머리말). 탭 재진입마다 다시 부르지 않도록 모듈에 남긴다
let criteria = null;
let criteriaErr = null;

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

  // 판정선 한 줄 — 폴백을 썼다는 사실을 숨기지 않는다. 숨기면 화면이 자기 기준을
  // 정본인 척하게 되고, 그게 두 탭이 어긋나는 것보다 나쁘다
  const criteriaBox = el("p", { class: "hint" },
    "판정선 불러오는 중… (엔진 기본값 /design/defaults)");
  const drawCriteria = () => {
    clear(criteriaBox).append(
      marginLegendText(criteria ?? FALLBACK_CRITERIA),
      criteria
        ? " — 엔진 기본값(/design/defaults). 자동 설계 실행이 요구를 덮어썼다면"
          + " 그 실행의 판정선은 결과의 margin_out.criteria다"
        : ` — 판정선 조회 실패로 웹 폴백값을 쓰는 중이다 (${criteriaErr}). `
          + "자동 설계 탭에서 기준을 바꿨다면 이 색은 그 기준이 아니다.",
    );
  };

  const loadCriteria = async () => {
    try {
      const d = await api.get("/design/defaults");
      criteria = d?.config?.criteria ?? null;
      criteriaErr = criteria ? null : "응답에 config.criteria가 없다";
    } catch (e) {
      criteria = null;
      criteriaErr = errorText(e);
    }
    drawCriteria();
    // 문턱이 바뀌었으니 이미 그려진 히트맵도 다시 칠한다 (조용히 옛 색으로 두지 않는다)
    if (lastBody) renderResults(resultBox, lastBody);
  };

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
        "항법 출력 지연 0.03 s [기본값] + 제어주기(100 Hz) 등가지연 0.005 s."),
      criteriaBox,
      progressBox, errBox,
    ),
    el("div", { class: "panel" }, el("h2", {}, "대시보드"), resultBox),
  );
  if (lastBody) renderResults(resultBox, lastBody);
  if (runningJobId) watch(); // 실행 중 재진입 — 진행 UI 재부착 (리뷰 S4)
  if (criteria) drawCriteria(); // 이미 받아 둔 판정선 — 재진입마다 다시 부르지 않는다
  else loadCriteria();
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
  const detailBox = el("div");
  const HEAT_W = 560; // heatmapCanvas 기본 폭 — 클릭 역매핑이 같은 값을 써야 한다

  /** 히트맵 칸 클릭 → 그 운용점·그 루프의 보드선도. GM·PM이 주파수축 어디에
   * 있는지는 히트맵 두 장으로는 원리적으로 안 보인다 (01 §4.2). */
  let bodeSeq = 0; // 늦게 도착한 응답이 새 선택을 덮지 않도록
  const openBode = async (lp, entry) => {
    const seq = ++bodeSeq;
    clear(detailBox).append(el("p", { class: "hint" },
      `보드선도 계산 중 — ${entry.trim.case.name} · ${lp.name}`));
    try {
      const res = await api.post("/analysis/bode", {
        case: entry.trim.case, loop: lp,
        actuator: lastBody.actuator ?? null,
        delay_s: lastBody.delay_s ?? 0.0,
        pade_order: lastBody.pade_order ?? 2,
        // 이 칸의 트림 해를 씨앗으로 — 마진 맵은 웜스타트로 풀었으므로 냉간으로
        // 다시 풀면 다른 선형화점에 앉아 곡선과 칸이 어긋난다(칸은 수렴인데
        // 보드만 422가 나기도 한다). 수평비행 트림은 θ = α라 euler[1]이 α다
        z0: [entry.trim.euler[1], entry.trim.control.elevon[0], entry.trim.control.throttle[0]],
      });
      if (seq !== bodeSeq) return; // 그사이 다른 칸을 눌렀다 — 옛 응답을 버린다
      renderBode(detailBox, lp, entry, res);
    } catch (e) {
      if (seq !== bodeSeq) return;
      clear(detailBox).append(el("div", { class: "error-box" }, errorText(e)));
    }
  };

  /** 캔버스에 클릭·커서를 붙인다 — 좌표 변환은 lib/wpmap.js toCanvasXY(CSS 축소 보정). */
  const wireCells = (canvas, pivot, lp) => {
    const hitAt = (ev) => {
      // 논리 크기를 넘긴다 — clientHeight(축소된 렌더 높이)를 넘기면 y 배율이
      // 1이 되어 좁은 화면에서 세로 좌표가 안 풀린다
      const { x, y } = toCanvasXY(ev.clientX, ev.clientY,
        canvas.getBoundingClientRect(), HEAT_W, heatmapCanvasHeight(pivot.alts.length));
      return heatmapCellAt(pivot, x, y, { width: HEAT_W });
    };
    canvas.addEventListener("pointermove", (ev) => {
      const hit = hitAt(ev);
      canvas.style.cursor = hit && hit.entry ? "pointer" : "default";
    });
    canvas.addEventListener("click", (ev) => {
      const hit = hitAt(ev);
      if (!hit || !hit.entry) return; // 여백·격자 밖 — 가까운 칸으로 끌어붙이지 않는다
      if (!hit.entry.trim.converged) {
        clear(detailBox).append(el("p", { class: "hint" },
          `${hit.entry.trim.case.name}: 트림 미수렴이라 선형화점이 없습니다 — 보드선도를 낼 수 없습니다.`));
        return;
      }
      if (!hit.entry.margins?.[lp.name]) {
        // 이 루프의 마진이 없는 칸(해석 실패로 회색) — 열어 봐야 서버도 같은
        // 이유로 못 푼다. 색칠된 칸만 열린다는 약속을 여기서 지킨다
        clear(detailBox).append(el("p", { class: "hint" },
          `${hit.entry.trim.case.name}: 이 루프의 마진이 없는 칸입니다`
          + (hit.entry.note ? ` — ${hit.entry.note}` : " (해석 실패)")));
        return;
      }
      if (!lp.x_out) { // 구버전 결과(loopsOf 폴백) — 루프 스펙이 없어 재조립 불가
        clear(detailBox).append(el("p", { class: "hint" },
          "이 결과에는 루프 스펙이 저장돼 있지 않아(구버전) 보드선도를 낼 수 없습니다 — 다시 실행하세요."));
        return;
      }
      openBode(lp, hit.entry);
    });
  };

  const draw = () => {
    // 판정선은 그릴 때마다 읽는다 — /design/defaults가 뒤늦게 도착해도 다시 칠해진다
    const cr = criteria ?? FALLBACK_CRITERIA;
    const fuel = Number(fuelSel.value);
    const pivot = pivotCases(entries, fuel);
    // 연료가 바뀌면 다른 격자다 — 옛 상세도, **진행 중인 요청도** 무효다
    bodeSeq += 1;
    clear(detailBox);
    const loopPlots = loops.flatMap((lp) => {
      const label = lp.x_out
        ? `${lp.name} — ${lp.sign < 0 ? "−" : "+"}PI·G(${lp.x_out} ← ${lp.u_in}) [${lp.axis}]`
        : lp.name;
      const pmCanvas = heatmapCanvas(pivot, (e) => {
        if (!e.trim.converged) return { color: STATUS.na, text: "트림×" };
        const pm = e.margins[lp.name] ? e.margins[lp.name].pm_deg : null;
        return { color: marginColor(pm, cr), text: `${fmt(pm, 3)}°` };
      }, { title: `위상여유 PM [deg] — ${lp.name} (≥${threshold(cr, "pm_min_deg")}°)`, width: HEAT_W });
      const gmCanvas = heatmapCanvas(pivot, (e) => {
        if (!e.trim.converged) return { color: STATUS.na, text: "트림×" };
        const gm = e.margins[lp.name] ? e.margins[lp.name].gm_db : null;
        return { color: gmColor(gm, cr), text: gm === "inf" ? "∞ dB" : `${fmt(gm, 3)} dB` };
      }, { title: `이득여유 GM [dB] — ${lp.name} (≥${threshold(cr, "gm_min_db")} dB)`, width: HEAT_W });
      // PM·GM 두 장 다 같은 루프의 같은 칸이므로 어느 쪽을 눌러도 같은 선도가 뜬다
      wireCells(pmCanvas, pivot, lp);
      wireCells(gmCanvas, pivot, lp);
      return [
        el("h3", { style: "font-size: 13px; margin: 14px 0 4px" }, label),
        pmCanvas, gmCanvas,
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
    el("div", { class: "row" }, fuelSel), plotBox,
    el("p", { class: "hint" }, "히트맵 칸을 클릭하면 그 운용점·그 루프의 보드선도가 아래에 열립니다."),
    detailBox);
  draw();
}

/** 필터 스펙 한 줄 — 파라미터 이름·단위는 블록 PARAM_DEFS 그대로 (엔진 filter_tf
 * 규격). kind와 무관하게 τ로 적으면 저역통과(fc)·노치(f0·q)에서 "τ=— s"가 된다. */
function filterText(f) {
  if (f.kind === "washout") return `washout τ=${fmt(f.tau, 3)} s`;
  if (f.kind === "lowpass") return `lowpass fc=${fmt(f.fc, 3)} Hz`;
  if (f.kind === "notch") return `notch f0=${fmt(f.f0, 3)} Hz · Q=${fmt(f.q, 3)}`;
  return f.kind;
}

/** 보드선도 상세 — 어느 칸인지, 무엇이 기준인지, 교차가 몇 개인지를 문장으로. */
function renderBode(box, lp, entry, body) {
  const c = entry.trim.case;
  const m = body.margins;
  const nGain = body.crossings.gain.length;
  const nPhase = body.crossings.phase.length;
  const kids = [
    el("h3", { style: "font-size: 13px; margin: 14px 0 4px" },
      `보드선도 — ${lp.name} @ M${fmt(c.mach, 3)} · ${fmt(c.alt, 5)} m · 연료 ${fmt(c.fuel, 4)} kg`),
    el("div", { class: "scroll-x" },
      bodeCanvas(body, { title: `${lp.name} — ${lp.sign < 0 ? "−" : "+"}PI·G(${lp.x_out} ← ${lp.u_in}) [${lp.axis}]` })),
    el("p", { class: "hint" },
      `실선이 기준입니다 — 클릭한 칸의 PM ${fmt(m.pm_deg, 4)}° · GM `
      + `${m.gm_db === "inf" ? "∞" : fmt(m.gm_db, 4)} dB가 이 곡선에서 읽은 값입니다. `
      + "PM은 |L|=0 dB인 wcp(초록)에서, GM은 ∠L=−180°인 wcg(주황)에서 읽습니다 — "
      + "두 수가 서로 다른 주파수의 값이라는 것이 두 수직선의 간격입니다."),
  ];
  // 교차가 여럿이면 보고된 마진은 그중 하나다 — 01 §4.2의 yaw_rate 사례가 이것이다
  if (nGain > 1 || nPhase > 1) {
    kids.push(el("p", { class: "hint" },
      `⚠ 0 dB 교차 ${nGain}개 · −180° 교차 ${nPhase}개 — 보고된 마진은 그중 하나입니다`
      + "(채운 원이 control.margin이 고른 자리, 빈 원이 나머지). 조립이 조금 바뀔 때 "
      + "마진 숫자가 크게 튀면 값이 나빠진 것이 아니라 **선택이 바뀐 것**일 수 있습니다."));
  }
  if (body.filtered) {
    const f = body.filtered.margins;
    kids.push(el("p", { class: "hint" },
      `파선은 법칙에 실제로 있는 레이트 필터(${filterText(body.filtered.filter)})를 `
      + `넣은 조립입니다 — PM ${fmt(f.pm_deg, 4)}° · `
      + `GM ${f.gm_db === "inf" ? "∞" : fmt(f.gm_db, 4)} dB. 마진 맵은 이 필터를 정적 게인으로 `
      + "보므로(01 §4.2 [한계]) 두 곡선의 간격이 곧 그 한계의 크기입니다 — 히트맵 숫자가 "
      + "틀린 것이 아니라 필터를 안 본 값입니다."));
  } else if (body.filtered_note) {
    kids.push(el("p", { class: "hint" }, `필터 반영 곡선 없음 — ${body.filtered_note}.`));
  }
  clear(box).append(...kids);
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
