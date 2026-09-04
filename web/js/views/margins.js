/** 마진 맵 뷰 (02 §8 3단계) — 케이스 격자 × PI 개루프(다중) → 마진 맵·고유치·감쇠비.

이 탭의 답은 **히트맵**이다: "전 구간에서 마진이 서는가, 어디가 얇은가." 그래서
PM·GM 맵이 카드 밖 전면에 놓이고(블록도 최상위·영향성과 같은 규약, views/stage.js),
격자·루프 편집과 고유치 맵·감쇠비 표는 서랍에 들어간다 — 매번 보는 것과 가끔 보는
것을 같은 크기로 늘어놓으면 어느 것이 답인지가 화면에서 사라진다.

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
import { createDrawers, tabStage, tabTop } from "./stage.js";

let lastBody = null;
let runningJobId = null;
// 탭 재진입에도 루프 편집 상태 유지 (수치는 입력 문자열 — 제출 시 파싱)
let loopRows = DEFAULT_LOOPS.map((r) => ({ ...r }));
// 판정선 — 정본은 /design/defaults(엔진 MarginCriteria). 하드코딩 폴백을 쓰면
// 자동 설계 탭에서 기준을 바꿨을 때 같은 점을 두 탭이 다르게 칠한다 (lib/plot.js
// FALLBACK_CRITERIA 머리말). 탭 재진입마다 다시 부르지 않도록 모듈에 남긴다
let criteria = null;
let criteriaErr = null;
// 보드선도 요청 시퀀스 — **모듈 스코프**여야 한다. renderResults 지역이면 재진입이
// bodeSeq=0인 새 클로저를 만들어, 옛 클로저의 진행 중 요청이 자기 카운터로는
// 유효(seq === bodeSeq)라 **DOM에서 떨어진 슬롯**에 곡선을 그린다 — 사용자는
// "계산 중"만 보고 곡선은 영영 안 온다(조용한 비표시). 대시보드 재렌더 경로는
// /design/defaults 응답 뒤와 탭 재진입 둘 다 있다. 인스턴스는 동시에 하나뿐이라
// 모듈로 올려도 서로 간섭하지 않는다
let bodeSeq = 0;
// 탭을 떠났다 와도 열어 둔 서랍은 그대로 (모듈 스코프 규약)
let openDrawer = null;

export function render() {
  const errBox = el("div");
  const progressBox = el("div");
  const loopBox = el("div");
  // 결과를 한 덩이(resultBox)로 내면 어느 조각이 전면이고 어느 조각이 서랍인지를
  // 부르는 쪽이 정할 수 없다 — 슬롯으로 갈라 renderResults가 각각 채운다
  const slots = {
    head: el("div"),   // 전면 — 몇 건·무엇을 포함했나·연료 선택
    plots: el("div"),  // 전면 — PM·GM 히트맵 (이 탭의 답)
    eig: el("div"),    // 서랍 — 고유치 맵
    damp: el("div"),   // 서랍 — 감쇠비 표
  };

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
  const criteriaBox = el("p", { class: "tab-status" },
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
    if (lastBody) renderResults(slots, lastBody);
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
        renderResults(slots, lastBody);
        // refresh(칩만)가 아니라 repaint — 서랍이 열린 채였다면 "실행 후 표시됩니다"
        // 줄이 방금 채워진 캔버스 밑에 그대로 남는다
        drawers.repaint();
        // 결과는 **전면**이라 스크롤이 필요 없다 — 폼이 서랍으로 들어가면서
        // 히트맵이 항상 화면 위쪽에 온다 (종전의 scrollIntoView는 그 자리의 흔적)
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
      for (const slot of Object.values(slots)) clear(slot);
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

  const drawers = createDrawers({
    id: "margins-drawer",
    initial: openDrawer,
    onOpen: (k) => { openDrawer = k; },
    defs: [
      { key: "grid", label: "격자·계보", group: "입력",
        title: "마하 범위·간격, 고도·연료 목록, 지문",
        build: () => [
          el("h2", {}, "케이스 격자"),
          el("div", { class: "row" },
            el("label", { class: "field" }, "마하 시작", fMachFrom),
            el("label", { class: "field" }, "마하 끝", fMachTo),
            el("label", { class: "field" }, "간격", fMachStep),
            el("label", { class: "field grow" }, "고도 목록 [m]", fAlts),
            el("label", { class: "field" }, "연료 [kg]", fFuels),
            el("label", { class: "field" }, "지문", fFp)),
          el("p", { class: "hint" },
            "검증 격자는 설계(게인 스케줄) 격자보다 촘촘해야 한다 — 설계점에서만 재면 "
            + "스케줄 경계점 사이에서 마진이 꺼지는 곳을 못 찾는다. "
            + "엔벨로프 탭 ⑥ 검증·마진 층이 같은 이야기를 한다."),
        ] },
      { key: "loops", label: "개루프 정의", group: "입력",
        title: "축·출력 상태·입력·kp·ki·sign — 서버 loops[] 계약 그대로",
        count: () => loopRows.length,
        build: () => [
          el("h2", {}, "PI 개루프 (다중)"),
          loopBox,
          el("p", { class: "hint" },
            "트림 → 선형화 → 모드 분류 → 루프별 sign·PI·G(x_out←u_in) 마진 (엔진 M9·M10). "
            + "루프를 전부 지우면 고유치·감쇠비만 계산."),
        ] },
      { key: "plant", label: "작동기·지연", group: "입력",
        title: "미포함 마진은 낙관적 — 체크 해제로 영향 분리 비교",
        build: () => [
          el("h2", {}, "플랜트에 무엇을 포함할 것인가"),
          el("div", { class: "field-grid" },
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
                el("label", { class: "field" }, "Padé 차수", fPade)))),
          el("p", { class: "hint" },
            "작동기·지연 미포함 마진은 낙관적 (01 §4.2) — 기본은 포함, 체크 해제로 영향 "
            + "분리 비교. 지연 기본값 0.035 s = 항법 출력 지연 0.03 s [기본값] + "
            + "제어주기(100 Hz) 등가지연 0.005 s."),
        ] },
      { key: "eig", label: "고유치 맵", group: "결과",
        title: "전 케이스의 모드를 한 복소평면에 — 허수축 좌측이 안정",
        build: () => [
          el("h2", {}, "고유치 맵"),
          slots.eig,
          lastBody ? null : el("p", { class: "hint" }, "실행 후 표시됩니다."),
        ] },
      { key: "damp", label: "감쇠비·모드 표", group: "결과",
        title: "케이스별 모드 ω_n·ζ — 어느 점의 어느 모드가 얇은가",
        build: () => [
          el("h2", {}, "모드별 감쇠비"),
          slots.damp,
          lastBody ? null : el("p", { class: "hint" }, "실행 후 표시됩니다."),
        ] },
    ],
  });

  const root = el("div", { class: "tab-page" },
    tabTop({
      title: "마진 맵",
      lead: "격자의 점마다 선형화해 개루프 마진을 잰다 — 설계점만이 아니라 그 사이까지 "
        + "훑어야 스케줄 경계에서 마진이 꺼지는 곳이 보인다. 격자·루프·조건은 아래 서랍에.",
      actions: [el("button", { class: "primary", onclick: run }, "실행")],
      // 판정선은 **서랍에 넣지 않는다** — 히트맵 색이 무엇을 기준으로 갈리는지이고,
      // 폴백을 쓰는 중이라면 그 사실이 색과 같은 화면에 있어야 한다
      extra: [criteriaBox, progressBox, errBox],
    }),
    // PM·GM 히트맵 — 카드 밖, 페이지 위에 그대로. 이 탭의 답이 여기 있다
    tabStage(slots.head, slots.plots),
    drawers.root,
  );
  if (lastBody) renderResults(slots, lastBody);
  else {
    clear(slots.head).append(el("p", { class: "hint" },
      "아직 실행하지 않았습니다 — [실행]을 누르면 격자 점마다 트림·선형화를 거쳐 "
      + "루프별 위상여유(PM)·이득여유(GM) 히트맵이 여기 그려집니다. "
      + "칸을 누르면 그 점의 보드선도가 열립니다."));
  }
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

/** 결과를 네 슬롯에 나눠 그린다 — 어디에 놓을지는 부르는 쪽이 정한다.
 *  slots: {head, plots, eig, damp}. 연료를 바꾸면 네 슬롯이 함께 다시 그려진다
 *  (한 슬롯만 갱신하면 히트맵과 감쇠비 표가 서로 다른 연료를 말하게 된다). */
function renderResults(slots, body) {
  const entries = body.cases;
  const loops = loopsOf(body);
  const fuels = fuelsOf(entries);
  const fuelSel = el("select", { "aria-label": "연료 선택" },
    fuels.map((f) => el("option", { value: f }, `연료 ${f} kg`)));
  const plotBox = el("div");
  const HEAT_W = 560; // heatmapCanvas 기본 폭 — 클릭 역매핑이 같은 값을 써야 한다

  /** 히트맵 칸 클릭 → 그 운용점·그 루프의 보드선도. GM·PM이 주파수축 어디에
   * 있는지는 히트맵 두 장으로는 원리적으로 안 보인다 (01 §4.2).
   * bodeSeq(늦게 도착한 응답 폐기)는 모듈 스코프 — 머리말 참조. */
  // 루프 구간마다 상세 슬롯 — 보드선도는 **누른 칸 바로 밑**에 연다. 종전처럼
  // 대시보드 맨 아래 한 자리에 열면 위쪽 루프를 누른 사람은 히트맵과 곡선을 나란히
  // 못 보고 화면 밖으로 스크롤해야 했다 (사용자 제기). draw()마다 새로 만든다.
  // **키는 이름이 아니라 루프 객체**다 — 이름은 서버 echo라 유일성 보장이 없고,
  // 겹치면 위 루프를 눌렀는데 아래 루프 자리에 곡선이 열린다
  let detailBoxes = new Map();
  /** 모든 슬롯을 비우고 그 루프의 슬롯을 돌려준다 — 한 번에 하나만 연다
   * (루프마다 남겨 두면 어느 것이 방금 누른 것인지 흐려진다). */
  const slotFor = (lp) => {
    for (const b of detailBoxes.values()) clear(b);
    return detailBoxes.get(lp) ?? null;
  };
  /** 계산 없이 사유만 내는 자리 — bodeSeq를 올려 **진행 중인 요청이 이 문장을
   * 덮지 않게** 한다. 안 올리면 미수렴 칸을 누른 직후 앞서 보낸 응답이 도착해
   * 사유를 지우고 남의 칸 곡선을 그린다. */
  const showNote = (lp, node) => {
    bodeSeq += 1;
    slotFor(lp)?.append(node);
  };
  const openBode = async (lp, entry) => {
    const seq = ++bodeSeq;
    const box = slotFor(lp);
    if (!box) return; // 그사이 다시 그려져 슬롯이 사라졌다
    box.append(el("p", { class: "hint" },
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
      renderBode(box, lp, entry, res);
    } catch (e) {
      if (seq !== bodeSeq) return;
      clear(box).append(el("div", { class: "error-box" }, errorText(e)));
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
      // 열려 있던 슬롯이 **이 캔버스보다 위**에 있으면 비우는 순간 그만큼 페이지가
      // 위로 밀려 방금 누른 히트맵이 손가락 밑에서 튄다(상세 높이가 노트북 한 화면쯤
      // 된다). Chrome·Firefox는 scroll anchoring이 흡수하지만 Safari에는 없다 —
      // 눌린 자리를 화면상 제자리에 붙들어 둔다
      const top0 = canvas.getBoundingClientRect().top;
      const keepAnchored = () => {
        const d = canvas.getBoundingClientRect().top - top0;
        if (d) window.scrollBy(0, d);
      };
      if (!hit.entry.trim.converged) {
        showNote(lp, el("p", { class: "hint" },
          `${hit.entry.trim.case.name}: 트림 미수렴이라 선형화점이 없습니다 — 보드선도를 낼 수 없습니다.`));
        keepAnchored();
        return;
      }
      if (!hit.entry.margins?.[lp.name]) {
        // 이 루프의 마진이 없는 칸(해석 실패로 회색) — 열어 봐야 서버도 같은
        // 이유로 못 푼다. 색칠된 칸만 열린다는 약속을 여기서 지킨다
        showNote(lp, el("p", { class: "hint" },
          `${hit.entry.trim.case.name}: 이 루프의 마진이 없는 칸입니다`
          + (hit.entry.note ? ` — ${hit.entry.note}` : " (해석 실패)")));
        keepAnchored();
        return;
      }
      if (!lp.x_out) { // 구버전 결과(loopsOf 폴백) — 루프 스펙이 없어 재조립 불가
        showNote(lp, el("p", { class: "hint" },
          "이 결과에는 루프 스펙이 저장돼 있지 않아(구버전) 보드선도를 낼 수 없습니다 — 다시 실행하세요."));
        keepAnchored();
        return;
      }
      openBode(lp, hit.entry); // 동기 구간(슬롯 비우기 + "계산 중")까지 끝난 뒤 보정
      keepAnchored();
    });
  };

  const draw = () => {
    // 판정선은 그릴 때마다 읽는다 — /design/defaults가 뒤늦게 도착해도 다시 칠해진다
    const cr = criteria ?? FALLBACK_CRITERIA;
    const fuel = Number(fuelSel.value);
    const pivot = pivotCases(entries, fuel);
    // 연료가 바뀌면 다른 격자다 — 옛 상세도, **진행 중인 요청도** 무효다
    bodeSeq += 1;
    detailBoxes = new Map(); // 슬롯도 새로 만든다 (옛 노드는 곧 버려진다)
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
      const detail = el("div"); // 이 구간의 보드선도 자리 — 누른 칸 바로 밑
      detailBoxes.set(lp, detail);
      return [
        el("h3", { style: "font-size: 13px; margin: 14px 0 4px" }, label),
        pmCanvas, gmCanvas, detail,
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
      el("div", { class: "legend" },
        el("span", {}, el("span", { class: "chip", style: `background:${STATUS.ok}` }), "양호"),
        el("span", {}, el("span", { class: "chip", style: `background:${STATUS.warn}` }), "주의"),
        el("span", {}, el("span", { class: "chip", style: `background:${STATUS.bad}` }), "부족"),
        el("span", {}, el("span", { class: "chip", style: `background:${STATUS.na}` }), "트림 불가/판정 불가")),
    );
    // 고유치·감쇠비는 서랍이다 — 같은 연료로 함께 갈아 끼운다
    clear(slots.eig).append(
      el("div", { class: "scroll-x" },
        scatterCanvas(points, { title: "고유치 맵 (파랑=종축, 주황=횡축) — 허수축 좌측이 안정" })),
      el("p", { class: "hint" },
        `연료 ${fmt(fuel, 4)} kg 격자의 전 케이스 모드를 한 평면에 겹친 것 — 점 하나가 `
        + "케이스 하나의 모드 하나다. 어느 점이 어느 케이스인지는 아래 감쇠비 표가 낸다."),
    );
    clear(slots.damp).append(dampingTable(entries.filter((e) => e.trim.case.fuel === fuel)));
  };
  fuelSel.addEventListener("change", draw);
  // el()로 감싼다 — 아래 `loops.length > 0 && …`는 거짓일 때 **false**를 낳고,
  // clear().append()는 네이티브라 그것을 "false" 텍스트로 붙인다 (el은 걸러 낸다)
  clear(slots.head).append(el("div", {},
    el("p", { style: "margin:0 0 4px" },
      el("b", {}, `계산 완료 — 케이스 ${entries.length}건 · 루프 ${loops.length}개`)),
    el("p", { class: "hint", style: "margin:0 0 6px" }, appliedSummary(body)),
    el("div", { class: "row" }, fuelSel),
    // 안내가 플롯 **앞**에 있어야 한다 — 상세가 루프 구간마다 열리므로 맨 아래
    // 한 줄로는 어디를 눌러야 하는지 읽을 자리가 없다. 루프가 0개면(루프를 전부
    // 지웠거나 전 케이스 해석 실패) 히트맵이 한 장도 없으므로 안내도 내지 않는다 —
    // 맨 앞자리라 "루프 0개" 헤더 바로 밑에서 없는 것을 누르라고 하게 된다
    loops.length > 0 && el("p", { class: "hint", style: "margin:6px 0 0" },
      "히트맵 칸을 클릭하면 그 운용점·그 루프의 보드선도가 그 구간 바로 아래에 열립니다 — 한 번에 한 곳만."),
  ));
  clear(slots.plots).append(plotBox);
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
