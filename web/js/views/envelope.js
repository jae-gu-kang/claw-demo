/** 엔벨로프 뷰 (01 §2.6) — 제어법칙 설계 엔벨로프를 **6계층**으로.

Envelope는 하나가 아니다. 목적에 따라 층이 갈리고, 그 순서가 곧 설계 순서다 —
"어디서 날 수 있나 → 각 점이 트림되나 → 그 점의 동특성이 무엇인가 → 어디를 설계점
으로 삼고 게인을 어떻게 배치하나 → 어디를 넘으면 안 되나 → 설계점 **사이**에서도
지켜지나". 그래서 이 탭의 서랍은 기능 묶음이 아니라 **계층 파이프라인**이다:

    ① 운용·비행 → ② 트림 → ③ 선형 모델 → ④ 제어 설계·스케줄링
                              → ⑤ 한계·보호 → ⑥ 검증·마진

    Flight Envelope → Trim Point → Linear Model A,B,C,D → Control Design/LPV
                    → Limit/Protection → Dense Sweep → Validation

화면의 주인공은 ①이다 — M-h 합성 선도가 카드 밖 전면에 놓이고(블록도 최상위·
영향성과 같은 규약, views/stage.js), 나머지 층은 눌렀을 때만 나온다.

**이 탭이 계산하지 않는 층도 층으로 세운다.** ③ 선형 모델과 ⑥ 검증·마진의 수치는
마진 맵 탭이 낸다. 그렇다고 목록에서 빼면 파이프라인에 구멍이 뚫린 채 "엔벨로프는
다섯 층"이라고 말하게 된다 — 대신 그 서랍은 **그 층이 무엇이고 어디서 나오는지**와
지금 저장된 산출물이 몇 건인지를 낸다. 없는 그림을 지어내지 않는 것과, 층이 없는
척하는 것은 다르다.

수치는 전부 엔진(vn_envelope·design_envelope·envelope_verdict) — 여기서는 표시만.
표현 변환(다각형·세그먼트·셀 분류·프리필)은 lib/envelope.js(테스트).
구조 한계 프리필은 응답 echo 자기 정렬(02 §5.5 — 기본값 재기술 금지):
손대지 않은 필드만 echo로 갱신, 값을 보내는 건 손댄 필드뿐.
*/

import { api, errorText } from "../api.js";
import { clear, el, fmt } from "../dom.js";
import {
  boundColor, boundLabel, boundarySegments, capColor, capLabel, dbLoBinds, envelopeQuery,
  ftToM, isoLabelIndex, isoOffWindow, kindColor, kindLabel, machSpan, machWindow, mToFt, msToKt,
  optNum, outlineCaps, prefillValue, outsideRegion, regionPolygons, scanCells, scanSummary,
  spreadLabels, tasAxisTicks, throttleCell, thrustFrontier,
} from "../lib/envelope.js";
import { machRange, nameCases, parseNumberList, serpentineCases } from "../lib/grid.js";
import { fuelsOf, linScale, niceTicks, pivotCases } from "../lib/plot.js";
import { heatmapCanvas, makeCanvas } from "./plots.js";
import { attachProgress, cancelledWithoutResult } from "./progress.js";
import { createDrawers, drawerSection, tabStage, tabTop } from "./stage.js";

let lastVn = null;
let lastMh = null;
let lastScan = null; // /results 페이로드 {kind: "envelope_scan", cases, n_requested}
let runningJobId = null;
// 폼 문자열 — 재진입 유지. 구조 5종은 첫 응답 echo로 프리필(§5.5 자기 정렬)
const form = {
  alt: "1000", fuel: "200", margin: "0.05",
  nPos: "", nNeg: "", sf: "", machNo: "", machD: "",
  qMax: "", altMin: "", altMax: "", machMargin: "", nz: "",
  scanFrom: "0.2", scanTo: "0.7", scanStep: "0.05", scanAlts: "0, 1000, 3000, 5000",
};
const touched = new Set(); // 구조 필드 중 사용자가 손댄 것 — 이것만 서버로 보낸다
// 레이어 토글 — 겹쳐 그릴 것이 아홉 가지라 토글 없이는 읽히지 않는다.
// 응답을 다시 받지 않고 다시 그리기만 하므로 서버 계약과 무관한 순수 표시 상태.
const layers = { isoQbar: true, isoTas: false, maneuver: true, scan: true, thrust: true };
// 탭을 떠났다 와도 열어 둔 계층은 그대로 (모듈 스코프 규약)
let openLayer = null;
// /results 색인 — ③·⑥ 층이 "이 격자를 실제로 잰 산출물이 몇 건인가"를 말하는 데만 쓴다.
// 없으면 없다고 하지, 0건을 "아직 안 불러옴"과 같은 얼굴로 내지 않는다
let stored = null;

// [폼 키, 서버 파라미터] — 구조 한계 오버라이드 5종 (vn·design-envelope 공유 계약)
const STRUCT_FIELDS = [
  ["nPos", "n_limit_pos"], ["nNeg", "n_limit_neg"], ["sf", "safety_factor"],
  ["machNo", "mach_no"], ["machD", "mach_d"],
];

const LAYER_FIELDS = [
  ["isoQbar", "등동압선"], ["isoTas", "등속선"], ["maneuver", "기동 엔벨로프"],
  ["scan", "스캔 판정"], ["thrust", "추력 한계 경계"],
];

/** 6계층 — 서랍의 순서가 곧 설계 순서다 (파이프라인). 각 층의 정의는 여기 한 곳.
 *  칩 라벨의 번호를 지우지 말 것: 이 목록은 묶음이 아니라 **차례**라, 번호가 없으면
 *  같은 칩 여덟 개가 나란히 선 화면이 된다. */
const LAYER_DEF = {
  L1: {
    label: "① 운용·비행",
    what: "항공기가 운용 가능한 비행조건의 전체 영역. 축은 (M, h)로 그리지만 실제 "
      + "운용점은 다차원이다 — x_op = [M, h, W, CG, 형상(flap·gear·store), …].",
  },
  L2: {
    label: "② 트림",
    what: "그 영역 안에서 실제로 trim이 잡히는 부분과, 각 점의 α_trim·δe_trim·"
      + "T_trim. 공력 DB(C_L·C_D·C_m …)와 안정·조종 미계수가 여기서 쓰이고, "
      + "이 값들이 다음 층의 선형화 입력이 된다.",
  },
  L3: {
    label: "③ 선형 모델",
    what: "각 트림점에서 뽑은 ẋ = A_i x + B_i u — 그리고 그 모드(단주기·장주기·"
      + "더치롤·롤·나선)의 ω_n·ζ와 조종 효율.",
  },
  L4: {
    label: "④ 제어 설계·스케줄링",
    what: "전 영역에서 대표 설계점을 고르고(P1, P2, …), 그 점들에 게인을 배치한다 — "
      + "K = f(M, q̄) 또는 f(V)·f(q̄)·f(M, h). LPV라면 스케줄링 파라미터 ρ가 "
      + "영역 안에서 연속으로 움직인다.",
  },
  L5: {
    label: "⑤ 한계·보호",
    what: "물리적으로 넘어가면 안 되는 경계 — V-n 선도, V_S·V_A·V_NO·V_D, 하중배수 "
      + "한계, 동압 한계. 제어법칙의 Envelope Protection(α ≤ α_lim, n_z ≤ n_z,max, "
      + "q̄ ≤ q̄_max)이 여기서 나온다. 조종권(타면 위치·rate·힌지모멘트) 한계도 같은 층이다.",
  },
  L6: {
    label: "⑥ 검증·마진",
    what: "설계점만 보면 안 된다. 설계점 사이까지 촘촘히 sweep해서 GM(M,h)·PM(M,h)·"
      + "ζ(M,h)·ω_n(M,h)를 맵으로 만든다 — 게인 스케줄 경계점 사이에서 마진이 "
      + "떨어지는 현상을 찾는 것이 목적이다.",
  },
};

/** 층 머리 — 정의 한 문단 + "이 도구에서는" 한 줄. 여섯 서랍이 같은 얼굴이어야
 *  사용자가 층을 옮겨 다니며 같은 자리에서 같은 것을 읽는다. */
function layerHead(key, here) {
  const d = LAYER_DEF[key];
  return [
    el("h2", {}, `${d.label} 엔벨로프`),
    // 마크다운 별표는 텍스트 노드에서 글자 그대로 나온다 — 강조가 필요하면 노드를
    // 쓰고, 이 문장은 칩 title(속성)로도 쓰이므로 애초에 표식 없는 글로 적는다
    el("p", { class: "hint", style: "margin:0 0 4px; max-width:96ch" }, d.what),
    el("p", { class: "hint", style: "margin:0 0 12px; max-width:96ch" },
      el("b", {}, "이 도구에서 — "), here),
  ];
}

/** 다른 탭으로 보내는 줄. 링크 없이 "마진 맵 탭에서 봅니다"라고만 쓰면 사용자가
 *  탭 이름을 눈으로 찾아야 한다 — 갈 곳이 있으면 갈 수 있게 한다. */
const goTo = (hash, label, tail) =>
  el("p", { class: "hint", style: "margin:8px 0 0" },
    "→ ", el("a", { href: hash }, label), tail ? ` ${tail}` : null);

export function render() {
  const errBox = el("div");
  const progressBox = el("div");
  const mhBox = el("div");
  const vnBox = el("div");
  const aeroBox = el("div");
  const propBox = el("div");
  const opsBox = el("div");
  const scanBox = el("div");
  // 스캔 격자 칸은 **한 번만** 만들고 다시 그리지 않는다 — 담는 상자째로.
  // renderScanTable이 매번 새로 만들면(또는 담긴 상자를 비우면) 「그리기」를 누르는
  // 순간 편집 중이던 칸이 DOM에서 들려 나가 포커스가 <body>로 떨어진다. 값은 form에
  // 남으니 잃지 않지만, 타이핑하다 다른 버튼을 누르면 커서가 사라지는 화면이 된다
  // (영향성 칩이 겪고 고친 그 자리와 같은 종류다). 그래서 격자는 서랍이 직접 들고,
  // renderScanTable은 **그 아래 결과만** 갈아 끼운다
  const scanGrid = el("div", { class: "opt-group" },
    el("div", { class: "g-title" }, "제어 가능 스캔 격자 (트림 잡 — 점당 트림 1회)"),
    el("div", { class: "row-inner" },
      el("label", { class: "field" }, "마하 시작", scanInput("scanFrom", "num-sm")),
      el("label", { class: "field" }, "끝", scanInput("scanTo", "num-sm")),
      el("label", { class: "field" }, "간격", scanInput("scanStep", "num-sm")),
      el("label", { class: "field grow" }, "고도 목록 [m]", scanInput("scanAlts", ""))));
  const formBox = el("div");
  const l1Box = el("div");
  const l3Box = el("div");
  const l4Box = el("div");
  const l6Box = el("div");
  const limitsBox = el("div");
  const layerBar = el("div", { class: "tab-actions" });

  const showErr = (e) =>
    clear(errBox).append(el("div", { class: "error-box" }, errorText(e)));

  const bind = (key, opts = {}) => {
    const inp = el("input", { class: "num", value: form[key], ...opts });
    inp.oninput = () => { form[key] = inp.value; };
    return inp;
  };
  const structInputs = {};
  const bindStruct = (key) => {
    const inp = bind(key);
    inp.oninput = () => { form[key] = inp.value; touched.add(key); };
    structInputs[key] = inp;
    return inp;
  };

  // 손대지 않은 구조 필드를 응답 echo로 채운다/맞춘다 (§5.5 자기 정렬)
  const syncStructural = (limits) => {
    for (const [key, param] of STRUCT_FIELDS) {
      form[key] = prefillValue(form[key], touched.has(key), limits?.[param]);
      structInputs[key].value = form[key];
    }
  };

  const structuralParams = () => {
    const out = {};
    for (const [key, param] of STRUCT_FIELDS) {
      if (touched.has(key)) out[param] = optNum(form[key], param); // 빈칸 = 데모로 복귀
    }
    return out;
  };

  const draw = async () => {
    try {
      clear(errBox);
      const struct = structuralParams();
      const shared = {
        fuel: Number(form.fuel),
        alpha_margin: Number(form.margin),
        ...struct,
      };
      lastVn = await api.get("/analysis/vn-envelope?"
        + envelopeQuery({ alt: Number(form.alt), ...shared }));
      lastMh = await api.get("/analysis/design-envelope?"
        + envelopeQuery({
          ...shared,
          q_max: optNum(form.qMax, "q̄_max"),
          alt_min: optNum(form.altMin, "운용 고도 하한"),
          alt_max: optNum(form.altMax, "운용 고도 상한"),
          mach_margin: optNum(form.machMargin, "실속 여유"),
          nz: optNum(form.nz, "기동 하중배수"),
        }));
      syncStructural(lastMh.limits);
      renderAll();
    } catch (e) {
      showErr(e);
    }
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
        lastScan = await api.get(`/results/${job.result_id}`);
        renderAll();
        drawers.open("L2"); // 결과가 사는 층을 열어 준다 — 찾아 헤매게 하지 않는다
      } catch (e) {
        showErr(e);
      }
    },
    onError: (e) => {
      runningJobId = null;
      showErr(e);
    },
  });

  const runScan = async () => {
    if (runningJobId) { // 이중 제출 방지 — 무반응 대신 안내 (조용한 무시 금지)
      clear(errBox).append(el("div", { class: "error-box" },
        "이미 실행 중입니다 — 진행률 표시를 확인하세요."));
      return;
    }
    try {
      clear(errBox);
      const cases = nameCases(serpentineCases(
        machRange(Number(form.scanFrom), Number(form.scanTo), Number(form.scanStep)),
        parseNumberList(form.scanAlts),
        [Number(form.fuel)],
      ));
      const submitted = await api.post("/analysis/design-envelope-scan",
        { cases, fingerprint: "web-envelope-v1" });
      runningJobId = submitted.id;
      watch();
    } catch (e) {
      showErr(e);
    }
  };

  // 레이어는 응답을 다시 받지 않고 다시 그리기만 한다 (표시 상태 — 서버 왕복 없음)
  const layerToggle = (key, label) => {
    const inp = el("input", { type: "checkbox" });
    inp.checked = layers[key];
    // 기동 층은 V-n에도 참조선을 긋는다 — 한쪽만 다시 그리면 없는 층을 가리키는 선이 남는다
    inp.onchange = () => {
      layers[key] = inp.checked;
      renderMh(mhBox);
      if (key === "maneuver") renderVn(vnBox);
    };
    return el("label", { class: "field", style: "flex-direction: row; align-items: center; gap: 4px" },
      inp, label);
  };

  const renderAll = () => {
    renderMh(mhBox);
    renderVn(vnBox);
    renderAero(aeroBox);
    renderProp(propBox);
    renderOps(opsBox);
    renderScanTable(scanBox);
    renderL1(l1Box);
    renderL3(l3Box);
    renderL4(l4Box);
    renderL6(l6Box);
    renderLimits(limitsBox);
    drawers.refresh();
  };

  // ── 필요값 입력 — 서랍 안. 한 번 정하면 잘 안 바뀌는 값들이라 늘 펴 둘 자리가
  //    아니다. 다만 「그리기」만은 머리줄에 남긴다: 값을 고친 뒤 눌러야 하는 버튼이
  //    같은 서랍 안에만 있으면 서랍을 닫는 순간 다시 그릴 방법이 사라진다.
  clear(formBox).append(
    el("div", { class: "row" },
      el("label", { class: "field" }, "고도 [m] (V-n)", bind("alt")),
      el("label", { class: "field" }, "연료 [kg]", bind("fuel")),
      el("label", { class: "field" }, "보호 마진 [rad]", bind("margin")),
      el("button", { class: "primary", onclick: draw }, "그리기"),
    ),
    el("div", { class: "field-grid", style: "margin-top: 10px" },
      el("div", { class: "opt-group" },
        el("div", { class: "g-title" }, "구조 한계 — 빈칸/미수정 = 데모 자리표시 (응답이 채움)"),
        el("div", { class: "row-inner" },
          el("label", { class: "field" }, "+제한 [g]", bindStruct("nPos")),
          el("label", { class: "field" }, "−제한 [g]", bindStruct("nNeg")),
          el("label", { class: "field" }, "안전계수", bindStruct("sf")),
          el("label", { class: "field" }, "M_NO", bindStruct("machNo")),
          el("label", { class: "field" }, "M_D", bindStruct("machD")))),
      el("div", { class: "opt-group" },
        el("div", { class: "g-title" }, "운용·동압 — 실기체 값: 미입력이면 경계 없음 (기본값 없음)"),
        el("div", { class: "row-inner" },
          el("label", { class: "field" }, "q̄_max [Pa]", bind("qMax")),
          el("label", { class: "field" }, "운용 하한 [m]", bind("altMin")),
          el("label", { class: "field" }, "운용 상한 [m]", bind("altMax")),
          el("label", { class: "field" }, "실속 여유 ×", bind("machMargin")),
          el("label", { class: "field" }, "기동 n_z [g]", bind("nz")))),
    ),
    el("p", { class: "hint" },
      "설계 엔벨로프 = 구조 ∧ 공력 ∧ 추진 ∧ 운용 ∧ 제어 가능 영역 (01 §2.6) — ",
      "V-n은 상위 constraint 하나. 구조 필드는 손댄 것만 서버로 보내고(02 §5.5), ",
      "빈칸으로 되돌리면 데모 자리표시로 복귀. 실속 여유 빈칸 = 엔진 기본값. ",
      "기동 n_z는 그 하중배수를 낼 수 있는 영역(1g 영역의 안쪽) — 빈칸이면 안 그린다."),
  );

  clear(layerBar).append(
    el("span", { class: "hint" }, "M-h 층"),
    ...LAYER_FIELDS.map(([key, label]) => layerToggle(key, label)),
  );

  const scanCount = () => (lastScan ? lastScan.cases.length : null);
  const marginCount = () => (stored ? stored.filter((m) => m.kind === "margin_map").length : null);

  const drawers = createDrawers({
    id: "envelope-drawer",
    initial: openLayer,
    onOpen: (k) => { openLayer = k; },
    defs: [
      { key: "form", label: "필요값 입력", group: "입력",
        title: "형상·구조 한계·운용 한계 — 여기 값이 전 층의 입력이다",
        build: () => formBox },
      { key: "L1", label: LAYER_DEF.L1.label, group: "설계 엔벨로프 6계층",
        title: LAYER_DEF.L1.what,
        count: () => (lastMh ? `${lastMh.region.alt.filter((_, i) => !lastMh.region.empty[i]).length}행` : null),
        build: () => l1Box },
      { key: "L2", label: LAYER_DEF.L2.label, group: "설계 엔벨로프 6계층",
        title: LAYER_DEF.L2.what, count: scanCount,
        build: () => [
          ...layerHead("L2", [
            "격자 트림 스캔이 점마다 trim 가능 여부와 사유를 판정하고(엔진 ",
            el("code", {}, "envelope_verdict"),
            "), 그 결과가 ① 합성 선도 위에 판정 점으로 덧그려진다. ",
            "α–Mach 선도가 공력 경계를, 스로틀 소요 히트맵이 추진 소요를 낸다.",
          ]),
          scanGrid,
          scanBox,
          drawerSection("공력 경계 — α–Mach",
            "설계 엔벨로프의 저속 경계는 이 곡선의 V_S 역산(×실속 여유)에서 온다.",
            aeroBox),
          drawerSection("추진 소요 — 트림 스로틀",
            "T_trim을 스로틀 소요로 표면화한 것. 상한 포화가 곧 추진 한계다.",
            propBox),
          goTo("#trim", "트림 탭", "— 같은 격자를 배치로 돌려 θ·δe·스로틀과 판정 플래그를 표로 봅니다."),
        ] },
      { key: "L3", label: LAYER_DEF.L3.label, group: "설계 엔벨로프 6계층",
        title: LAYER_DEF.L3.what, build: () => l3Box },
      { key: "L4", label: LAYER_DEF.L4.label, group: "설계 엔벨로프 6계층",
        title: LAYER_DEF.L4.what,
        count: () => lastMh?.schedule_grid?.points?.length ?? null,
        build: () => l4Box },
      { key: "L5", label: LAYER_DEF.L5.label, group: "설계 엔벨로프 6계층",
        title: LAYER_DEF.L5.what,
        build: () => [
          ...layerHead("L5", [
            "V-n 선도가 구조 한계를, 운용 박스가 입력한 고도·마하 한계를 낸다. ",
            "이 층의 값이 그대로 제어법칙의 보호 한계(α 리미터·n_z·q̄)가 된다 — ",
            "지금 구조 한계는 데모 프로파일 자리표시이고, 위 「필요값 입력」에 실기체 값을 "
            + "넣으면 그 값으로 다시 계산한다.",
          ]),
          limitsBox,
          drawerSection("V-n 선도 (교과서형)", null, vnBox),
          drawerSection("운용 엔벨로프 — 입력 한계 박스", null, opsBox),
          goTo("#sim", "시뮬레이션 탭 → 「타면 사용」 서랍",
            "— 조종권(타면 위치·rate) 한계 쪽 층입니다. 다만 이 도구는 아직 "
            + "δ_max(M, q̄)처럼 비행조건별로 갈리는 조종권 한계를 관리하지 않습니다 — "
            + "타면 한계는 조건과 무관한 상수입니다."),
        ] },
      { key: "L6", label: LAYER_DEF.L6.label, group: "설계 엔벨로프 6계층",
        title: LAYER_DEF.L6.what, count: marginCount, build: () => l6Box },
    ],
  });

  // 먼저 한 번 그린다 — 응답이 아직 없어도 각 층이 **왜 비었는지**를 말해야 한다
  renderAll();
  loadStored().then(() => drawers.refresh());
  if (!lastVn && !lastMh) draw(); // 재진입이면 받아 둔 응답 그대로 (다시 부르지 않는다)
  if (runningJobId) watch(); // 실행 중 재진입 — 진행 UI 재부착

  return el("div", { class: "tab-page" },
    tabTop({
      title: "엔벨로프",
      lead: "설계 엔벨로프는 한 장이 아니라 여섯 층이다 — "
        + "운용·비행 → 트림 → 선형 모델 → 제어 설계·스케줄링 → 한계·보호 → 검증·마진. "
        + "화면의 그림은 그중 ①이고, 나머지 층은 아래 칩에 있다.",
      actions: [
        el("button", { class: "primary", onclick: draw }, "그리기"),
        el("button", { onclick: runScan }, "제어 가능 판정 (트림 스캔)"),
      ],
      extra: [progressBox, errBox],
    }),
    layerBar,
    // ① 합성 선도 — 카드 밖, 페이지 위에 그대로 (캔버스가 자기 테두리를 갖는다)
    tabStage(mhBox),
    drawers.root,
  );
}

/** /results 색인 — ③·⑥ 층의 "몇 건 있나"에만 쓴다. 실패해도 화면은 그대로 뜬다
 *  (건수를 못 세는 것과 그림이 안 뜨는 것은 무게가 다르다). */
async function loadStored() {
  try {
    stored = await api.get("/results");
  } catch {
    stored = null; // null = 못 물어봤다. 0건과 같은 얼굴로 내지 않는다
  }
}

/** 구조·운용 한계 표 — ⑤ 층. 값이 어디서 왔는지(자리표시/사용자 입력)가 값만큼 중요하다.
 *
 *  **지속 노드에 그린다.** build() 안에서 만들면 서랍을 열어 둔 채 「그리기」를 눌렀을 때
 *  표가 옛 상태("그리기 실행 시 표시됩니다")에 얼어붙는다 — 서랍 갱신은 칩만 고치므로. */
function renderLimits(box) {
  if (!lastMh?.limits) {
    clear(box).append(el("p", { class: "hint" }, "그리기 실행 시 표시됩니다."));
    return;
  }
  const L = lastMh.limits;
  const b = lastMh.bounds;
  const over = new Set(lastMh.limits_overridden ?? []);
  const src = (param) => (over.has(param)
    ? el("span", { class: "flag ok" }, "사용자 입력")
    : el("span", { class: "flag na" }, "데모 자리표시"));
  const rows = [
    ["n_limit_pos", "+제한하중 n", "g", L.n_limit_pos],
    ["n_limit_neg", "−제한하중 n", "g", L.n_limit_neg],
    ["safety_factor", "안전계수 (극한/제한)", "—", L.safety_factor],
    ["mach_no", "M_NO 최대 구조 순항", "—", L.mach_no],
    ["mach_d", "M_D 급강하 한계", "—", L.mach_d],
  ];
  clear(box).append(el("div", { class: "scroll-x" }, el("table", {},
    el("thead", {}, el("tr", {},
      el("th", {}, "한계"), el("th", {}, "값"), el("th", {}, "단위"), el("th", {}, "출처"))),
    el("tbody", {},
      rows.map(([param, name, unit, v]) => el("tr", {},
        el("td", {}, name),
        el("td", { class: "num" }, fmt(v, 4)),
        el("td", {}, unit),
        el("td", {}, src(param)))),
      // 운용·동압은 구조와 출처가 다르다 — 미입력이면 **경계 자체가 없다**
      [["q̄_max 동압 한계", "Pa", b.q_max], ["운용 고도 하한", "m", b.alt_min],
       ["운용 고도 상한", "m", b.alt_max]].map(([name, unit, v]) => el("tr", {},
        el("td", {}, name),
        el("td", { class: "num" }, v == null ? "—" : fmt(v, 5)),
        el("td", {}, unit),
        el("td", {}, v == null
          ? el("span", { class: "flag na" }, "미입력 — 경계 없음")
          : el("span", { class: "flag ok" }, "사용자 입력")))),
    ))));
}

// ── ① 운용·비행 — 경계 귀속과, 이 도구가 아직 축으로 쓰지 않는 것 ────────────

function renderL1(box) {
  const kids = layerHead("L1", [
    "M-h 합성 선도가 이 층이고, 화면 위에 이미 떠 있다. 여기 표는 그 영역의 ",
    el("b", {}, "경계를 무엇이 정했는지"),
    "를 고도 구간별로 나눠 적는다 — 같은 테두리라도 실속이 정한 변과 M_D가 정한 변은 "
    + "설계에서 하는 일이 다르다.",
  ]);
  if (!lastMh) {
    clear(box).append(...kids, el("p", { class: "hint" }, "그리기 실행 시 표시됩니다."));
    return;
  }
  const r = lastMh.region;
  const live = r.alt.map((_, i) => i).filter((i) => !r.empty[i]);
  // 귀속이 바뀌는 지점에서만 행을 낸다 — 41행을 그대로 내면 표가 아니라 목록이다
  const runs = [];
  for (const i of live) {
    const key = `${r.lo_source[i]}|${r.hi_source[i]}`;
    const last = runs[runs.length - 1];
    if (last && last.key === key && last.end + 1 === i) { last.end = i; }
    else runs.push({ key, start: i, end: i, lo: r.lo_source[i], hi: r.hi_source[i] });
  }
  kids.push(
    el("div", { class: "scroll-x" }, el("table", {},
      el("thead", {}, el("tr", {},
        el("th", {}, "고도 구간 [m]"), el("th", {}, "저속 경계 (하한)"),
        el("th", {}, "고속 경계 (상한)"), el("th", {}, "마하 폭"))),
      el("tbody", {}, runs.map((run) => el("tr", {},
        el("td", { class: "num" },
          `${fmt(r.alt[run.start], 5)} ~ ${fmt(r.alt[run.end], 5)}`),
        el("td", {},
          el("span", { class: "chip", style: `background:${boundColor(run.lo)}` }),
          " ", boundLabel(run.lo)),
        el("td", {},
          el("span", { class: "chip", style: `background:${boundColor(run.hi)}` }),
          " ", boundLabel(run.hi)),
        el("td", { class: "num" },
          `M ${fmt(r.mach_lo[run.start], 3)} ~ ${fmt(r.mach_hi[run.start], 3)}`),
      )))),
    ),
    // 위·아래 변은 좌우 변과 성격이 다르다 — 셋 중 하나가 "운용 한계가 아닌 것"이다
    el("h3", {}, "위·아래 변 (닫힌 곡선의 나머지 두 변)"),
    el("div", { class: "legend" },
      ...[...new Set(outlineCaps(r, lastMh.bounds).map((c) => c.source))].map((code) =>
        el("span", {},
          el("span", { class: "chip", style: `background:${capColor(code)}` }),
          capLabel(code)))),
    el("p", { class: "hint" },
      "천장이 세 종류인 이유: 운용 상한(실기체 값)·표시 상한([기본값]이라 운용 한계가 "
      + "아니다)·자연 천장(실속 하한이 마하 상한을 만나 영역이 사라진 지점). 셋을 같은 "
      + "선으로 그리면 화면이 없는 상승한도를 있는 것처럼 말한다."),
    el("h3", {}, "이 도구가 축으로 쓰는 것 · 아직 쓰지 않는 것"),
    el("p", { class: "hint" },
      "운용점은 ", el("code", {}, "[M, h, 연료]"), " 세 축이다. ",
      el("b", {}, "무게중심(CG)·형상(flap·gear·store)은 축이 아니다"),
      " — 데모 기체가 형상 변화를 갖지 않고 CG는 연료 소모로만 움직인다. "
      + "실기체로 갈 때 이 층이 가장 먼저 넓어지는 자리이고, 그때 아래 층 전부가 "
      + "축 하나씩을 더 받는다(트림도 선형화도 설계점도 CG별로 갈린다)."),
  );
  clear(box).append(...kids);
}

// ── ② 트림 — 스캔 판정 표 ─────────────────────────────────────────────────

function renderScanTable(box) {
  const kids = [];
  if (!lastScan) {
    kids.push(el("p", { class: "hint" },
      "아직 스캔하지 않았습니다 — 머리줄의 [제어 가능 판정 (트림 스캔)]을 누르면 "
      + "격자 점마다 트림을 풀고 판정이 여기와 ① 선도에 함께 나옵니다. "
      + "연료는 「필요값 입력」의 값을 씁니다."));
    clear(box).append(...kids);
    return;
  }
  const cells = scanCells(lastScan.cases);
  const s = scanSummary(cells);
  kids.push(
    el("div", { class: "legend" },
      el("span", {}, el("span", { class: "chip", style: `background:${kindColor("ok")}` }),
        `${kindLabel("ok")} ${s.ok}/${s.total}`),
      ...s.byKind.map(({ kind, n }) => el("span", {},
        el("span", { class: "chip", style: `background:${kindColor(kind)}` }),
        `${kindLabel(kind)} ${n}건`))),
    el("div", { class: "scroll-x" }, el("table", {},
      el("thead", {}, el("tr", {},
        el("th", {}, "마하"), el("th", {}, "고도 [m]"), el("th", {}, "연료 [kg]"),
        el("th", {}, "판정"), el("th", {}, "사유 (엔진 우선순위 순)"))),
      el("tbody", {}, cells.map((c) => el("tr", {},
        el("td", { class: "num" }, fmt(c.mach, 4)),
        el("td", { class: "num" }, fmt(c.alt, 5)),
        el("td", { class: "num" }, fmt(c.fuel, 4)),
        el("td", {}, el("span", {
          class: "chip",
          style: `background:${kindColor(c.kind)}; width:auto; padding:1px 8px; border-radius:999px`,
        }, c.ok ? "가능" : "불가")),
        // 사유는 전량을 낸다 — 대표 하나만 내면 스로틀 포화가 미수렴에 가려진다
        el("td", {}, c.ok ? "—" : c.reasons.map(kindLabel).join(" · ")),
      )))),
    ),
    el("p", { class: "hint" },
      "판정은 엔진 envelope_verdict가 낸다 — 웹은 사유 코드를 라벨로만 바꾼다. "
      + "격자를 촘촘히 할수록 경계가 정확해지고, 스캔 격자 해상도가 곧 경계 해상도다."),
  );
  clear(box).append(...kids);
}

/** 스캔 격자 입력 한 칸 — 폼 상태(form)를 직접 물고, 만든 노드가 화면의 수명 내내
 *  그대로 산다(위 scanGrid 참조). 값의 정본은 form이라 탭을 떠났다 와도 남는다. */
function scanInput(key, cls) {
  const inp = el("input", { class: cls, value: form[key] });
  inp.oninput = () => { form[key] = inp.value; };
  return inp;
}

// ── ③ 선형 모델 · ⑥ 검증·마진 — 이 탭이 계산하지 않는 층 ─────────────────

/** 저장된 산출물 줄 — "몇 건 있나"까지만. 못 물어봤으면 0건이라고 하지 않는다. */
function storedLine(kind, label) {
  if (stored == null) {
    return el("p", { class: "hint", style: "margin:8px 0 0" },
      `저장 산출물 목록을 불러오지 못했습니다 — ${label} 건수를 세지 못했습니다.`);
  }
  const n = stored.filter((m) => m.kind === kind).length;
  const last = stored.filter((m) => m.kind === kind)[0];
  return el("p", { class: "hint", style: "margin:8px 0 0" },
    n === 0
      ? `저장된 ${label} 산출물 없음 — 아직 이 층을 실측하지 않았습니다.`
      : `저장된 ${label} 산출물 ${n}건`
        + (last?.created ? ` · 최근 ${new Date(last.created * 1000).toLocaleString()}` : "")
        + ".");
}

function renderL3(box) {
  clear(box).append(
    ...layerHead("L3", [
      el("b", {}, "이 탭은 선형 모델을 만들지 않는다"),
      " — 트림점에서 A, B, C, D를 뽑고 모드를 분류하는 것은 마진 맵 탭의 잡(엔진 ",
      el("code", {}, "linearize"), " · ", el("code", {}, "classify"),
      ")이다. 여기서는 그 층이 파이프라인의 어디인지와, 지금 실측이 있는지만 말한다.",
    ]),
    el("p", { class: "hint", style: "max-width:96ch" },
      "② 트림이 낸 각 점의 (α_trim, δe_trim, T_trim)이 이 층의 입력이고, 나온 A_i·B_i가 "
      + "④ 설계점의 제어기 설계 대상이 된다. 그래서 ②가 실패한 점에는 ③이 없다 — "
      + "선형화할 평형점 자체가 없기 때문이다."),
    storedLine("margin_map", "마진 맵(선형화·고유치)"),
    goTo("#margins", "마진 맵 탭",
      "— 케이스 격자 × 개루프로 고유치 맵·감쇠비 표·보드선도를 냅니다."),
  );
}

function renderL6(box) {
  const kids = layerHead("L6", [
    el("b", {}, "설계점 격자와 검증 격자는 같을 필요가 없다"),
    " — 오히려 달라야 한다. 게인을 마하 몇 점에서 설계했더라도, 검증은 그 사이를 "
    + "훨씬 촘촘히 훑어야 스케줄 경계점 사이에서 마진이 꺼지는 곳을 찾는다.",
  ]);
  if (lastMh?.schedule_grid) {
    const g = lastMh.schedule_grid;
    kids.push(el("p", { class: "hint", style: "max-width:96ch" },
      `지금 설계(스케줄) 격자는 고도당 마하 ${g.n_mach}점 · 고도 ${g.alts.length}단이다. `
      + "검증 격자는 마진 맵 탭에서 따로 정한다 — 같은 수를 쓰면 설계점만 통과하는 "
      + "게인이 통과로 보이고, 그것이 이 층을 따로 두는 이유다."));
  }
  kids.push(
    storedLine("margin_map", "마진 맵(GM·PM 스윕)"),
    goTo("#margins", "마진 맵 탭", "— GM/PM 히트맵·고유치 맵·감쇠비 표."),
    goTo("#autodesign", "자동 설계 탭",
      "— 설계 → 검증 → 처방 루프를 한 잡으로 돌리고, 검증점 판정을 원장으로 남깁니다."),
    goTo("#influence", "영향성 탭",
      "— 게인 하나를 흔들었을 때 전 구간 마진이 어느 쪽으로 가는지를 표로 냅니다."),
  );
  clear(box).append(...kids);
}

// ── ④ 제어 설계·스케줄링 — 설계점 격자 ───────────────────────────────────

function renderL4(box) {
  const kids = layerHead("L4", [
    "① 합성 선도 위의 속 빈 사각형이 이 층이다 — 게인 스케줄 격자점. "
    + "그 점마다 ③ 선형 모델을 뽑아 제어기를 설계하고, 점 사이는 스케줄이 잇는다.",
  ]);
  if (!lastMh?.schedule_grid) {
    clear(box).append(...kids, el("p", { class: "hint" }, "그리기 실행 시 표시됩니다."));
    return;
  }
  const g = lastMh.schedule_grid;
  const out = g.points.filter((p) => outsideRegion(p, lastMh.region));
  // 고도별 한 줄 — 20점을 세로로 늘어놓으면 격자라는 사실이 표에서 사라진다
  const byAlt = g.alts.map((alt) => ({
    alt,
    pts: g.points.filter((p) => p.alt === alt),
  }));
  kids.push(
    el("div", { class: "scroll-x" }, el("table", {},
      el("thead", {}, el("tr", {},
        el("th", {}, "고도 [m]"),
        ...Array.from({ length: g.n_mach }, (_, i) => el("th", {}, `P${i + 1}`)),
        el("th", {}, "영역 밖"))),
      el("tbody", {}, byAlt.map(({ alt, pts }) => el("tr", {},
        el("td", { class: "num" }, fmt(alt, 5)),
        ...pts.map((p) => el("td", { class: "num" },
          outsideRegion(p, lastMh.region)
            ? el("span", { style: `color:${C.limitLine}` }, `M ${fmt(p.mach, 4)} ×`)
            : `M ${fmt(p.mach, 4)}`)),
        el("td", { class: "num" },
          pts.filter((p) => outsideRegion(p, lastMh.region)).length || "—"),
      )))),
    ),
    out.length
      ? el("p", { class: "hint", style: `color:${C.limitLine}` },
        `⚠ ${out.length}점이 합성 영역 밖(×)입니다 — 격자 좌표는 coarse 격자(design.grid)와 `
        + "맞추려고 q̄를 보지 않고 만들어지므로, 이것이 실제 설계점 위치입니다. "
        + "좌표를 옮기지 않고 표시만 합니다.")
      : el("p", { class: "hint" }, "설계점 전부가 합성 영역 안입니다."),
    el("h3", {}, "게인을 무엇의 함수로 둘 것인가"),
    el("p", { class: "hint", style: "max-width:96ch" },
      "지금 스케줄은 ", el("code", {}, "K = f(M)"),
      " 1D(동압 스케일)다. 기체에 따라 ", el("code", {}, "f(V)"), " · ",
      el("code", {}, "f(q̄)"), " · ", el("code", {}, "f(M, h)"),
      "가 낫고, LPV라면 ρ = [M, q̄, α, …]를 정해 영역 안에서 플랜트·제어기가 "
      + "연속으로 변하게 한다. 어느 쪽이든 이 층의 결정이고, 아래 ⑥이 그 결정을 검증한다."),
    goTo("#gains", "게인 탭", "— 스케줄 자리(어느 게인에 표를 붙일지)와 셀 값을 고칩니다."),
    goTo("#autodesign", "자동 설계 탭", "— 설계점 선정·튜닝·스케줄 적합을 잡 하나로 돌립니다."),
  );
  clear(box).append(...kids);
}

// 애플 시스템 팔레트 — 존은 옅은 틴트, 경계선은 시스템 컬러 (블록도와 동일 언어)
const C = {
  ok: "#e4f8ea", stallZone: "#f2f2f7", caution: "#fdf7e0",
  damage: "#ffefdd", failure: "#fdeaea",
  stallLine: "#ff3b30", protLine: "#34c759", limitLine: "#c93400",
  ultLine: "#d70015", speedLine: "#8e8e93", text: "#1d1d1f", sub: "#86868b",
  frame: "#d2d2d7", opsLine: "#007aff", dbTint: "#f6effc", schedPt: "#8e8e93",
  manFill: "rgba(10, 132, 255, 0.16)", manLine: "#0a84ff",
  isoLine: "#c7c7cc", tropo: "#8e8e93", thrustLine: "#ff6b00",
};
const FONT_BASE = "11px -apple-system, 'Segoe UI', sans-serif";
const FONT_LABEL = "600 11px -apple-system, 'Segoe UI', sans-serif";
const FONT_TITLE = "600 12px -apple-system, 'Segoe UI', sans-serif";

// 등고선 이름 — 캔버스 라벨과 "창 밖" 안내가 **한 곳**에서 나온다. 두 곳에서 따로
// 조립하면 한쪽만 고쳤을 때 안내가 가리키는 이름을 화면에서 못 찾는다 (TAS 접두를
// 넣기까지 리뷰 두 라운드가 걸렸다 — 그 결정이 한쪽에만 남으면 안 된다). 캔버스는
// 여기에 kt 병기를 덧붙일 뿐이다
const ISO_NAME = {
  qbar: (c) => `${fmt(c.q, 4)} Pa`,
  tas: (c) => `TAS ${fmt(c.v, 4)} m/s`,
};

const placeholderHint = (body) => (body?.limits_source === "user-input"
  ? el("p", { class: "hint" },
    `구조 한계 중 사용자 입력: ${(body.limits_overridden ?? []).join(", ")} — `
    + "나머지는 데모 프로파일 자리표시 [기본값 — 실기체 값 아님, 01 §2.6].")
  : el("p", { class: "hint" },
    "⚠ 구조 한계(±제한/극한·M_NO·M_D)는 데모 프로파일 자리표시 [기본값 — 실기체 값 ",
    "아님, 01 §2.6]: 구조팀 정본 확보 시 프로파일 교체. 폼에 값을 넣으면 그 값으로 계산."));

// ── 합성 (M-h) ────────────────────────────────────────────────────────────

function mhEnvelopeCanvas(mh, cells) {
  const W = 780;
  const H = 544; // 상단 축이 먹은 24 px만큼 키운다 — 플롯 영역을 줄이지 않는다
  const { canvas, ctx } = makeCanvas(W, H);
  // mR — 우측 ft 보조축, mT — 상단 대기속도(kt) 보조축 눈금·이름 자리
  const mL = 56, mT = 54, mR = 54, mB = 40;
  const b = mh.bounds;
  const r = mh.region;
  const man = layers.maneuver ? mh.maneuver : null;
  // 창 계산은 lib 정본 — renderMh의 "창 밖" 안내가 같은 창을 봐야 한 말이 된다
  const { xMin, xMax } = machWindow(b, r);
  const px = linScale(xMin, xMax, mL, W - mR);
  const py = linScale(b.alt_min_used, b.alt_max_used, H - mB, mT);
  // 채움 위에 얹히는 글자는 흰 테두리를 깔아야 읽힌다.
  // save/restore로 감싼다 — 안 그러면 흰 strokeStyle·굵기 3이 남아, 다음에 라벨
  // 뒤에 선을 긋는 사람이 흰 선을 보게 된다 (지금은 호출부마다 우연히 다시 세운다)
  const haloText = (text, x, y, color) => {
    ctx.save();
    ctx.strokeStyle = "rgba(255,255,255,0.92)";
    ctx.lineWidth = 3;
    ctx.lineJoin = "round";
    ctx.strokeText(text, x, y);
    ctx.fillStyle = color;
    ctx.fillText(text, x, y);
    ctx.restore();
  };
  const polyline = (machs, alts) => {
    ctx.beginPath();
    machs.forEach((m, i) => (i === 0 ? ctx.moveTo(px(m), py(alts[i])) : ctx.lineTo(px(m), py(alts[i]))));
    ctx.stroke();
  };

  ctx.strokeStyle = C.frame;
  ctx.lineWidth = 1;
  ctx.strokeRect(mL, mT, W - mL - mR, H - mT - mB);
  ctx.save();
  ctx.beginPath();
  ctx.rect(mL, mT, W - mL - mR, H - mT - mB);
  ctx.clip();

  // 대류권계면 — 엔진 echo (웹이 11000을 재기술하지 않는다, 02 §5.5)
  const tropo = b.tropopause_alt;
  if (tropo != null && tropo > b.alt_min_used && tropo < b.alt_max_used) {
    ctx.strokeStyle = C.tropo;
    ctx.lineWidth = 1;
    ctx.setLineDash([8, 5]);
    ctx.beginPath();
    ctx.moveTo(mL, py(tropo));
    ctx.lineTo(W - mR, py(tropo));
    ctx.stroke();
    ctx.setLineDash([]);
    haloText("대류권계면", W - mR - 60, py(tropo) - 4, C.sub);
  }

  // 설계 영역 틴트 (1g)
  const fillRegion = (reg, style) => {
    ctx.fillStyle = style;
    for (const poly of regionPolygons(reg)) {
      ctx.beginPath();
      poly.forEach((p, i) => (i === 0 ? ctx.moveTo(px(p.mach), py(p.alt)) : ctx.lineTo(px(p.mach), py(p.alt))));
      ctx.closePath();
      ctx.fill();
    }
  };
  fillRegion(r, C.ok);
  // 기동 엔벨로프 — 1g 안쪽 (하한만 올라간다). 그림 17의 내부 엔벨로프 자리
  if (man) {
    fillRegion(man.region, C.manFill);
    ctx.strokeStyle = C.manLine;
    ctx.lineWidth = 1.8;
    ctx.setLineDash([5, 3]);
    for (const seg of boundarySegments(man.region)) {
      if (seg.side !== "lo" || seg.pts.length < 2) continue;
      polyline(seg.pts.map((p) => p.mach), seg.pts.map((p) => p.alt));
    }
    ctx.setLineDash([]);
  }

  // 등동압선·등속선 — M-h 평면에서 대기속도 보조축은 한 고도에서만 맞으므로(엔진
  // iso_curves 참조) 축 대신 곡선. **채움 뒤가 아니라 위에** 그린다 — 영역 틴트가
  // 불투명이라 뒤에 깔면 정작 설계 영역 안에서 안 보인다 (라이브 확인에서 드러남)
  // prefer는 라벨을 붙일 기준 행(고도 비율) — 두 계열에 다른 값을 준다. 같은 행을
  // 쓰면 등동압선과 등속선 라벨이 한 줄에 겹쳐 "1000"+"200 m/s…"처럼 서로를 잘라
  // 먹는다(두 층을 함께 켜면 바로 드러난다). 계열 안의 흩어짐은 곡선마다 x가
  // 다른 것으로 해결되지만, 계열끼리는 행을 갈라야 한다
  const isoSets = [
    layers.isoQbar
      ? { curves: mh.iso.qbar, prefer: 0.62, label: ISO_NAME.qbar }
      : null,
    // 등속선은 상단 kt 축과 **같은 물리량**이다 — m/s만 적으면 축과 곡선이 서로 다른
    // 단위로 같은 것을 말해 대조가 안 된다. 곡선이 상단 모서리에 닿는 자리가 곧
    // 그 kt 눈금 자리이므로, 두 표시가 한 눈에 이어져야 축의 고도 의존이 읽힌다
    layers.isoTas
      ? {
        curves: mh.iso.tas,
        prefer: 0.34,
        label: (c) => `${ISO_NAME.tas(c)} · ${Math.round(msToKt(c.v))} kt`,
      }
      : null,
  ].filter(Boolean);
  ctx.font = FONT_BASE;
  // 라벨 기준 높이를 도표 안쪽으로 잡는다 — 곡선들이 하나같이 천장으로 빠져나가서
  // "범위 안 마지막 행"이 전부 같은 줄이 되면 라벨이 겹쳐 뭉갠다 (라이브 확인)
  for (const set of isoSets) {
    const isoPrefer = Math.round((r.alt.length - 1) * set.prefer);
    for (const cur of set.curves) {
      ctx.strokeStyle = C.isoLine;
      ctx.lineWidth = 1.1;
      ctx.setLineDash([2, 3]);
      polyline(cur.mach, r.alt);
      ctx.setLineDash([]);
      const i = isoLabelIndex(cur, xMin, xMax, isoPrefer);
      if (i < 0) continue;
      const text = set.label(cur);
      const x = px(cur.mach[i]);
      // 오른쪽 끝에서는 글자를 왼쪽으로 뒤집는다 — 안 그러면 잘려서 "4"만 남는다.
      // 폭은 재서 판단한다 — 고정 60 px는 kt를 덧붙인 등속선 라벨에서 모자란다
      const flip = x + 3 + ctx.measureText(text).width > W - mR;
      const yTop = py(r.alt[i]) - 3;
      ctx.textAlign = flip ? "right" : "left";
      haloText(text, x + (flip ? -3 : 3), yTop < mT + 10 ? yTop + 15 : yTop, C.sub);
      ctx.textAlign = "left";
    }
  }

  // 참고 수직선 — M_D, DB 범위 (합성 경계 밖 정보). 오른쪽 끝에서는 라벨을 왼쪽으로
  const vline = (v, label, color = C.speedLine) => {
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.2;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(px(v), mT);
    ctx.lineTo(px(v), H - mB);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = color;
    if (px(v) > W - mR - 70) {
      ctx.textAlign = "right";
      ctx.fillText(label, px(v) - 3, mT + 12);
      ctx.textAlign = "left";
    } else {
      ctx.fillText(label, px(v) + 3, mT + 12);
    }
  };
  // 데모는 M_D = DB 상한(0.9) — 같은 자리면 선 하나에 합친 라벨 (겹침 방지)
  const dbHiCoincides = Math.abs(b.db_mach[1] - b.mach_d) < 1e-9;
  vline(b.mach_d, dbHiCoincides ? `M_D·DB ${fmt(b.mach_d, 3)}` : `M_D ${fmt(b.mach_d, 3)}`);
  // DB 하한은 **구속일 때만** 그린다 — 영역보다 아래면 아무것도 자르지 않으므로
  // 그리면 없는 제약을 있다고 말하게 된다. 안 그린 사유는 캡션이 문장으로 낸다.
  if (dbLoBinds(b, r)) vline(b.db_mach[0], `DB ${fmt(b.db_mach[0], 3)}`, "#c7b3e0");
  if (!dbHiCoincides) vline(b.db_mach[1], `DB ${fmt(b.db_mach[1], 3)}`, "#c7b3e0");

  // 운용 고도 한계 — 입력했을 때만 (없는 경계를 그리지 않는다). 상단 끝이면 라벨을 선 아래로
  const hline = (alt, label) => {
    ctx.strokeStyle = C.opsLine;
    ctx.lineWidth = 1.4;
    ctx.setLineDash([6, 4]);
    ctx.beginPath();
    ctx.moveTo(mL, py(alt));
    ctx.lineTo(W - mR, py(alt));
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = C.opsLine;
    ctx.fillText(label, mL + 6, py(alt) < mT + 16 ? py(alt) + 14 : py(alt) - 4);
  };
  if (b.alt_min != null) hline(b.alt_min, `운용 하한 ${fmt(b.alt_min, 5)} m`);
  if (b.alt_max != null) hline(b.alt_max, `운용 상한 ${fmt(b.alt_max, 5)} m`);

  // 합성 경계선 — 귀속별 색 (승자 엔벨로프가 경계를 결정)
  const segs = boundarySegments(r);
  for (const seg of segs) {
    if (seg.pts.length < 2) continue;
    ctx.strokeStyle = boundColor(seg.source);
    ctx.lineWidth = 2.2;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.beginPath();
    seg.pts.forEach((p, i) => (i === 0 ? ctx.moveTo(px(p.mach), py(p.alt)) : ctx.lineTo(px(p.mach), py(p.alt))));
    ctx.stroke();
  }
  // 닫힌 경계의 위·아래 캡 — 운용 한계는 위 hline이 이미 전 폭에 그렸으므로
  // 여기서는 **모호한 모서리만**: 자연 천장/바닥과 표시 한계. 셋을 구분하지 않으면
  // 화면이 "여기가 상승한도"라고 말해버린다 (진짜 천장은 추력 한계 경계가 그린다 — thrustFrontier)
  const caps = outlineCaps(r, b).filter((c) => !c.source.startsWith("ops_"));
  for (const cap of caps) {
    ctx.strokeStyle = capColor(cap.source);
    ctx.lineWidth = 1.6;
    ctx.setLineDash([5, 3]);
    ctx.beginPath();
    ctx.moveTo(px(cap.mach0), py(cap.alt));
    ctx.lineTo(px(cap.mach1), py(cap.alt));
    ctx.stroke();
    ctx.setLineDash([]);
  }
  ctx.font = FONT_LABEL;
  ctx.textAlign = "center";
  for (const cap of caps) {
    // 캡이 도표 위/아래 끝에 붙으면(표시 한계가 그렇다) 바깥쪽 라벨은 클립돼 사라진다
    // — 그 경우 안쪽으로 접는다. 라이브 확인 전에는 두 라벨 다 보이지 않았다
    const y = py(cap.alt);
    const above = y - 6, below = y + 13;
    haloText(capLabel(cap.source), (px(cap.mach0) + px(cap.mach1)) / 2,
      cap.side === "top" ? (above < mT + 10 ? below : above)
        : (below > H - mB - 4 ? above : below),
      capColor(cap.source));
  }
  ctx.textAlign = "left";

  // 추력 한계 경계 — 스캔의 스로틀 상한 포화 전선. 프로펠러 추력 모델이 들어와
  // 포화가 곧 진짜 한계다. 해석 곡선이 아니라 측정점이라 격자 해상도가 곧 경계 해상도
  // 저속(backside)·고속 전선은 서로 다른 곡선이다 — 한 줄로 이으면 평면을 가로지른다
  const frontier = layers.thrust && cells ? thrustFrontier(cells) : [];
  for (const side of ["lo", "hi"]) {
    const pts = frontier.filter((p) => p.side === side);
    if (!pts.length) continue;
    ctx.strokeStyle = C.thrustLine;
    ctx.lineWidth = 2;
    ctx.setLineDash([7, 4]);
    if (pts.length >= 2) polyline(pts.map((p) => p.mach), pts.map((p) => p.alt));
    ctx.setLineDash([]);
    // 미수렴 셀에서 나온 전이점은 속 빈 원 — 그 스로틀은 해가 아니라 솔버의
    // 마지막 반복값이라 "수평비행에 이만큼 필요하다"는 측정이 아니다
    for (const p of pts) {
      ctx.beginPath();
      ctx.arc(px(p.mach), py(p.alt), 3, 0, Math.PI * 2);
      if (p.provisional) {
        ctx.strokeStyle = C.thrustLine;
        ctx.lineWidth = 1.4;
        ctx.stroke();
      } else {
        ctx.fillStyle = C.thrustLine;
        ctx.fill();
      }
    }
    const mid = pts[Math.floor(pts.length / 2)];
    ctx.font = FONT_LABEL;
    ctx.textAlign = side === "lo" ? "right" : "left";
    haloText(side === "lo" ? "추력 한계 (저속)" : "추력 한계 (고속)",
      px(mid.mach) + (side === "lo" ? -8 : 8), py(mid.alt) + 4, C.thrustLine);
    ctx.textAlign = "left";
  }

  // 게인 스케줄 격자점 (엔진 coarse 좌표 — trimmable 미판정, 빈 원).
  // 영역 밖 점은 ×로 — 좌표는 coarse 격자와 맞추느라 q̄를 안 보므로 실제로 밖일 수 있다
  for (const p of mh.schedule_grid.points) {
    const x = px(p.mach), y = py(p.alt);
    ctx.strokeStyle = C.schedPt;
    ctx.lineWidth = 1.4;
    if (outsideRegion(p, r)) {
      ctx.strokeStyle = C.limitLine;
      ctx.beginPath();
      ctx.moveTo(x - 4, y - 4); ctx.lineTo(x + 4, y + 4);
      ctx.moveTo(x + 4, y - 4); ctx.lineTo(x - 4, y + 4);
      ctx.stroke();
    } else {
      ctx.beginPath();
      ctx.arc(x, y, 4, 0, Math.PI * 2);
      ctx.stroke();
    }
  }

  // 합성 경계가 한 행뿐인 조각 — 선이 못 되므로 점으로라도 남긴다 (조용한 비표시 금지)
  for (const seg of segs) {
    if (seg.pts.length !== 1) continue;
    ctx.fillStyle = boundColor(seg.source);
    ctx.beginPath();
    ctx.arc(px(seg.pts[0].mach), py(seg.pts[0].alt), 2.6, 0, Math.PI * 2);
    ctx.fill();
  }

  // 제어 가능 스캔 판정 점 (호출측이 연료 일치분만 전달)
  if (cells && layers.scan) {
    for (const c of cells) {
      ctx.fillStyle = kindColor(c.kind);
      ctx.beginPath();
      ctx.arc(px(c.mach), py(c.alt), 3.2, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  // 귀속 라벨 — source별 가장 긴 세그먼트에 지시선을 달고, 좌·우 무리를 각각 벌린다
  const longest = new Map();
  for (const seg of segs) {
    if (seg.pts.length < 2) continue;
    if (!longest.has(seg.source) || longest.get(seg.source).pts.length < seg.pts.length) {
      longest.set(seg.source, seg);
    }
  }
  const anchors = [...longest.values()].map((seg) => {
    const mid = seg.pts[Math.floor(seg.pts.length / 2)];
    return {
      side: seg.side, color: boundColor(seg.source), text: boundLabel(seg.source),
      ax: px(mid.mach), ay: py(mid.alt), y: py(mid.alt),
    };
  });
  if (man) {
    const lo = boundarySegments(man.region).filter((s) => s.side === "lo" && s.pts.length >= 2);
    const seg = lo.sort((a, c) => c.pts.length - a.pts.length)[0];
    if (seg) {
      const mid = seg.pts[Math.floor(seg.pts.length / 2)];
      anchors.push({
        side: "hi", color: C.manLine, text: `기동 n_z=${fmt(man.nz, 3)}`,
        ax: px(mid.mach), ay: py(mid.alt), y: py(mid.alt),
      });
    }
  }
  ctx.font = FONT_LABEL;
  for (const side of ["lo", "hi"]) {
    const group = spreadLabels(anchors.filter((a) => a.side === side), 15);
    for (const a of group) {
      const tx = a.ax + (side === "lo" ? -10 : 10);
      ctx.strokeStyle = a.color;
      ctx.lineWidth = 0.8;
      ctx.beginPath(); // 지시선 — 라벨이 밀려도 어느 곡선인지 남는다
      ctx.moveTo(a.ax, a.ay);
      ctx.lineTo(tx, a.y - 3);
      ctx.stroke();
      ctx.textAlign = side === "lo" ? "right" : "left";
      haloText(a.text, tx, a.y, a.color);
    }
  }
  ctx.textAlign = "left";
  ctx.restore();

  // 영역 없음 안내 + 축
  ctx.font = FONT_LABEL;
  ctx.fillStyle = C.sub;
  if (!r.empty.some((e) => !e)) {
    ctx.fillText("설계 영역 없음 — 경계가 전 고도에서 닫힘", mL + 20, (mT + H - mB) / 2);
  }
  ctx.font = FONT_BASE;
  for (const t of niceTicks(xMin, xMax, 7)) {
    // 끝 눈금은 프레임 안으로 접는다 — 가운데 정렬로 두면 우측 ft 축의 바닥 라벨과
    // 겹쳐 "0.350"과 "0"이 한 덩어리로 읽힌다 (마하 창이 좁을 때 라이브 확인)
    const x = px(t);
    ctx.textAlign = x > W - mR - 14 ? "right" : (x < mL + 14 ? "left" : "center");
    ctx.fillText(fmt(t, 3), x, H - mB + 16);
  }
  ctx.textAlign = "left";
  for (const t of niceTicks(b.alt_min_used, b.alt_max_used, 7)) {
    ctx.fillText(`${Math.round(t)}`, 6, py(t) + 3);
  }
  // 우측 ft 보조축은 **자기 눈금**을 가진다 — m 눈금 자리에 환산값을 얹으면
  // 39370·32808·26247이 늘어서 축 구실을 못 한다. 교과서 도해도 좌 k ft·우 km를
  // 서로 다른 높이에 찍는다. 환산은 정의값이라 자리는 여전히 정확하다
  for (const t of niceTicks(mToFt(b.alt_min_used), mToFt(b.alt_max_used), 9)) {
    ctx.fillText(`${Math.round(t)}`, W - mR + 6, py(ftToM(t)) + 3);
  }
  ctx.fillText("Mach", W / 2 - 14, H - 8);
  ctx.fillText("ft", W - mR + 6, H - mB + 16);

  // 상단 대기속도(kt) 보조축 — 교과서 도해의 윗변. M ↔ V = M·a의 대응은 고도마다
  // 다르므로 이 축은 **자기가 놓인 선**, 즉 도표 윗변에서만 참이다: 기준 음속을
  // 엔진 echo에서 받아(웹이 ISA를 재기술하지 않는다, 02 §5.5) 기준 고도를 축 이름에
  // 적는다. 아래로 갈수록 같은 마하가 더 빠르다는 사실은 축이 아니라 등속선 층과
  // renderMh의 캡션이 말한다 — 축 하나로 뭉개면 화면이 한 고도의 값을 전부에 대해
  // 참인 것처럼 말하게 된다. 구버전 응답(재시작 전 캐시)에는 이 echo가 없다:
  // tasAxisTicks가 빈 목록을 내고 축이 아예 안 그려진다 (0 kt 눈금 금지)
  const ktTicks = tasAxisTicks(xMin, xMax, b.speed_of_sound?.alt_max_used);
  if (ktTicks.length) {
    ctx.strokeStyle = C.frame;
    ctx.lineWidth = 1;
    ctx.textAlign = "center";
    for (const t of ktTicks) {
      ctx.beginPath();
      ctx.moveTo(px(t.mach), mT);
      ctx.lineTo(px(t.mach), mT - 5);
      ctx.stroke();
      ctx.fillText(`${Math.round(t.kt)}`, px(t.mach), mT - 9);
    }
    ctx.textAlign = "right";
    // **TAS를 이름에 박는다.** 엔진 실체는 M = V/a(h)라 진대기속도인데, M-h 도표
    // 윗변에 kt로 붙은 "대기속도"는 KEAS/KCAS로 읽히기 쉽다(교과서 도해의 윗변
    // 속도축이 대개 EAS인 것도 그쪽으로 민다). 12 km에서 TAS 400 kt는 EAS로 약
    // 202 kt — 이 캔버스가 정직하게 고지하는 15.3%보다 **한 자릿수 큰** 어긋남이
    // 단위 이름 하나에 숨는다. V-n 캔버스가 이미 "V (TAS) [m/s]"로 명시한다
    ctx.fillText(`진대기속도 TAS [kt] — h ${Math.round(b.alt_max_used)} m 기준`, W - mR, mT - 24);
    ctx.textAlign = "left";
  }
  ctx.font = FONT_TITLE;
  ctx.fillStyle = C.text;
  ctx.fillText(`h [m] — 연료 ${fmt(mh.fuel, 4)} kg · 실속 여유 ×${fmt(mh.mach_margin, 3)}`, mL, 18);
  return canvas;
}

function renderMh(box) {
  if (!lastMh) {
    clear(box).append(el("p", { class: "hint" }, "필요값을 입력하고 그리기를 누르면 표시됩니다."));
    return;
  }
  // 차트 연료와 일치하는 스캔 셀만 — 집계도 같은 것만 세야 점과 숫자가 같은 말을 한다
  const allCells = lastScan ? scanCells(lastScan.cases) : null;
  const cells = allCells ? allCells.filter((c) => c.fuel === lastMh.fuel) : null;
  // 범례 귀속 칩은 실제로 그려진(비어 있지 않은) 행의 승자만
  const sources = new Set();
  lastMh.region.empty.forEach((e, i) => {
    if (e) return;
    sources.add(lastMh.region.lo_source[i]);
    sources.add(lastMh.region.hi_source[i]);
  });
  const man = layers.maneuver ? lastMh.maneuver : null;
  const legend = el("div", { class: "legend" },
    el("span", {}, el("span", { class: "chip", style: `background:${C.ok}` }), "설계 영역 (1g 합성)"),
    ...(man ? [el("span", {}, el("span", { class: "chip", style: `background:${C.manLine}` }),
      `기동 엔벨로프 n_z=${fmt(man.nz, 3)} g`)] : []),
    ...[...sources].map((s) => el("span", {},
      el("span", { class: "chip", style: `background:${boundColor(s)}` }), boundLabel(s))),
    el("span", {}, el("span", { class: "chip", style: `border:1.4px solid ${C.schedPt}; background:transparent` }),
      "게인 스케줄 격자점 (coarse [기본값] — trimmable 미판정)"),
    // 꺼진 층은 범례에서도 뺀다 — 화면에 없는 표시를 설명하면 범례가 거짓말이 된다
    ...(layers.thrust ? [el("span", {}, el("span", { class: "chip", style: `background:${C.thrustLine}` }),
      "추력 한계 경계 (스로틀 상한 포화)")] : []),
  );
  const kids = [el("div", { class: "scroll-x" }, mhEnvelopeCanvas(lastMh, cells)), legend];
  // 상단 kt 축의 기준과 오차 폭 — 축은 자기가 놓인 윗변에서만 참이므로, 아래로
  // 갈수록 얼마나 어긋나는지를 화면이 스스로 말해야 한다. 두 모서리 음속이 엔진
  // echo로 오므로 어긋남을 지어내지 않고 계산해 적는다 (02 §5.5)
  // 창 밖 판정은 캡션보다 먼저 — 캡션이 "켜면 그려집니다"라고 단정하려면 켰을 때
  // 실제로 그려지는지를 알아야 한다(창이 아주 좁으면 켜도 안 그려진다)
  const win = machWindow(lastMh.bounds, lastMh.region);
  const tasOff = isoOffWindow(lastMh.iso.tas, win.xMin, win.xMax);
  const qbarOff = isoOffWindow(lastMh.iso.qbar, win.xMin, win.xMax);
  const tasAllOff = lastMh.iso.tas.length > 0 && tasOff.length === lastMh.iso.tas.length;
  const sos = lastMh.bounds.speed_of_sound;
  if (sos) {
    const faster = (sos.alt_min_used / sos.alt_max_used - 1) * 100;
    // 표시 범위가 ISA 등온층 안에만 있으면 두 모서리 음속이 같다. 그때 종전 문장은
    // "M ↔ V는 고도마다 다르므로 … 0% 더 빠릅니다"가 되어 **전제절부터 거짓**이고 0%는
    // 포맷 버그처럼 읽힌다 — 실은 자랑할 사실이다: 그 창에서는 축이 전 고도에서 정확하다.
    // 축의 한계를 고지하는 캡션이 한계가 없는 경우도 말한다.
    //
    // 판정 근거는 엔진이 echo하는 대류권계면 고도다 — 문구와 **같은 근거**를 써야 한다
    // (02 §5.5: 웹이 11000을 재기술하지 않는다). 첫 구현은 "음속비 0.05%" 문턱이었는데
    // 그건 h≈10966 m라 alt_min ∈ [10966, 11000)에서 "고도 범위(h 10970~…)는 ISA
    // 등온층(11 km 위) 안"이라는 자기모순 문장이 나왔다 — 판정과 문구의 근거가 갈리면
    // 폭 34 m짜리 틈이 생긴다. 엔진이 표시 고도를 ISA 상한(등온층 천장 20 km) 안으로
    // 강제하므로 하한만 보면 범위 전체가 등온층이다.
    //
    // echo가 없으면 **일반 분기로 보낸다**(문턱 폴백을 두지 않는다): 그 폴백은 같은 틈을
    // 눈에 안 띄게 되살릴 뿐이고 — 숫자를 뺀 "대류권계면 위"는 10970 m에서도 거짓이다,
    // 거짓을 들키게 해 주던 단서만 지운 셈 — 애초에 도달할 수도 없다. 이 문단은
    // if (sos) 안이고 speed_of_sound가 tropopause_alt보다 나중에 생긴 키라
    // sos != null ⟹ tropo != null이다
    const tropo = lastMh.bounds.tropopause_alt;
    const isothermal = tropo != null && lastMh.bounds.alt_min_used >= tropo;
    kids.push(el("p", { class: "hint" },
      `상단 진대기속도(TAS, kt) 축은 도표 윗변 h ${fmt(lastMh.bounds.alt_max_used, 5)} m의 음속 `
      + `${fmt(sos.alt_max_used, 4)} m/s로 환산한 값`
      + (isothermal
        ? `입니다. 이 도표의 고도 범위(h ${fmt(lastMh.bounds.alt_min_used, 5)}~`
          + `${fmt(lastMh.bounds.alt_max_used, 5)} m)는 ISA 등온층`
          // isothermal이 tropo != null을 함의하므로 여기서 다시 방어하지 않는다
          + `(대류권계면 ${fmt(tropo, 5)} m 위) 안이라 음속이 일정해 `
          + "축이 전 고도에서 정확합니다. "
        : ` — 그 선 위에서만 정확합니다. M ↔ V는 고도마다 다르므로 아래 모서리`
          + `(h ${fmt(lastMh.bounds.alt_min_used, 5)} m, ${fmt(sos.alt_min_used, 4)} m/s)에서는 `
          + `같은 마하가 ${fmt(faster, 3)}% 더 빠릅니다. `)
      // 등속선은 기본 꺼짐이다 — 무조건 "그립니다"라고 적으면 탭을 연 첫 화면에서
      // 없는 곡선을 있다고 말하게 되고(범례가 꺼진 층을 설명하지 않는 것과 같은
      // 자리), 축의 한계를 메우는 물건을 켜 볼 이유도 사라진다("이미 있다는데
      // 안 보이네"). 고지는 어느 쪽이든 남기고 동사만 갈린다 — 꼬리 문장은 삼항
      // 밖으로: 한쪽만 고쳐 두 문장이 갈리는 것을 막는다
      //
      // **tasAllOff가 층 분기보다 위다.** 켜짐 분기에서 이 조건을 안 보면, 층을 켠
      // 채 전 곡선이 창 밖인 상태에서 이 문단은 "그립니다"라고 하고 바로 아래 경고는
      // 같은 곡선을 두고 "그려지지 않습니다"라고 한다 — 붙어 있는 두 문단이 정반대를
      // 말하는 것은 침묵보다 나쁘다(침묵은 정보가 없을 뿐이지만 모순은 화면 전체의
      // 신뢰를 깎는다). 창 밖이면 켜짐·꺼짐과 무관하게 그 사실이 먼저다
      + (tasAllOff
        ? "고도에 따른 실제 값은 '등속선' 층이 그리지만, 지금 마하 창에서는 그 곡선이 전부 창 밖입니다"
        : (layers.isoTas
          ? "고도에 따른 실제 값은 '등속선' 층이 평면 안에 그립니다"
          : "고도에 따른 실제 값은 '등속선' 층을 켜면 평면 안에 그려집니다"))
      // "닿는 자리가" → "닿으면 그 자리가": 마하 창이 좁으면 곡선이 윗변까지 못 가는데
      // (M_NO·M_D를 낮게 입력한 경우) 단정형은 그때 거짓이 된다. 조건형은 늘 참이다
      + " — 등속선이 윗변에 닿으면 그 자리가 곧 그 속도의 눈금 자리입니다."));
  }
  // 층은 켜져 있는데 곡선이 통째로 마하 창 밖일 수 있다 — 값은 멀쩡하다. 사유 없이
  // 사라지면 조용한 비표시이고, 위 캡션이 "등속선이 그린다"고 말하는 상황에서는 그
  // 문장까지 거짓이 된다. 켜진 층만 센다 (안 그리는 것을 세면 범례와 같은 거짓말)
  //
  // **원인을 단정하지 않는다.** 창이 좁아서일 수도 있지만(M_NO·M_D를 낮게 입력),
  // 창이 데모 최대 폭인데도 곡선이 밖일 수 있다 — 운용 고도대를 8~12 km로 주면
  // 40000 Pa 등동압선이 M 1.27~1.72로 밀려난다(창 [0.07, 0.93]은 그대로다). 그때
  // "창이 좁으니 M_NO·M_D를 보라"고 하면 **표시 문제 때문에 구조 한계를 만지게** 만든다.
  // 대신 곡선의 실제 마하 구간을 적는다 — 응답에 이미 있는 수라 지어내지 않는다
  // DB 마하 하한선이 도표에 없으면 **그 사유를 적는다** — 선이 사유 없이 사라지는 것은
  // 이 리포가 금하는 조용한 비표시다. 반대로 구속도 아닌 선을 그리면 없는 제약을 있다고
  // 말하게 되므로, 안 그리는 쪽이 맞고 대신 문장이 그 자리를 대신한다.
  if (!dbLoBinds(lastMh.bounds, lastMh.region)) {
    kids.push(el("p", { class: "hint" },
      `공력 DB 마하 하한(${fmt(lastMh.bounds.db_mach[0], 3)})은 세로선으로 그리지 않았습니다 — `
      + `비행 가능 영역의 하한(M ${fmt(Math.min(...lastMh.region.mach_lo), 3)})보다 아래라 `
      + "아무것도 자르지 않기 때문입니다. 이 영역의 저속 경계는 실속이 정합니다."));
  }
  const span = (name, c) => {
    const s = machSpan(c); // 구간을 못 내면 이름만 — "M NaN~NaN"을 증거인 척 내지 않는다
    return s ? `${name} (M ${fmt(s.lo, 3)}~${fmt(s.hi, 3)})` : name;
  };
  const offWin = [
    ...(layers.isoQbar ? qbarOff.map((c) => span(ISO_NAME.qbar(c), c)) : []),
    ...(layers.isoTas ? tasOff.map((c) => span(ISO_NAME.tas(c), c)) : []),
  ];
  if (offWin.length) {
    kids.push(el("p", { class: "hint" },
      `⚠ 등고선 ${offWin.length}개가 마하 창 [${fmt(win.xMin, 3)}, ${fmt(win.xMax, 3)}] 밖이라 `
      + `그려지지 않습니다 — ${offWin.join(", ")}. 값이 없어진 것이 아니라 창이 곡선에 닿지 `
      + "않는 것입니다. 창은 "
      // DB 하한이 구속이 아니면 창을 벌리지도 않는다 — 규칙이 갈리는데 문장이 하나면
      // 캡션이 창을 잘못 설명한다(같은 판정을 lib dbLoBinds 하나로 쓰는 이유)
      + (dbLoBinds(lastMh.bounds, lastMh.region) ? "DB 하한·합성 하한의 최소" : "합성 하한")
      + "부터 M_D·합성 상한의 최대까지입니다 — "
      // "예를 들어": 기전이 이 둘뿐인 것처럼 읽히면 안 된다. q̄_max를 크게 잡아도
      // [기본값] 등동압선이 그 배수라 밖으로 나간다(창도 안 좁고 고도대도 기본이다)
      + "예를 들어 M_NO·M_D를 낮게 잡으면 창이 좁아지고, 운용 고도대가 높거나 q̄_max가 크면 "
      + "등고선이 더 높은 마하로 밀립니다."));
  }
  if (man) {
    // n_reach 행은 전부 empty라 경계 세그먼트도 범례 칩도 안 나온다 — 갈라 둔 귀속이
    // 화면에 닿는 자리가 여기뿐이므로 개수를 숫자로 낸다 (안 그리면 갈라 둔 값이 죽는다)
    const nEmpty = man.region.empty.filter(Boolean).length;
    const nReach = man.region.lo_source.filter((s) => s === "n_reach").length;
    kids.push(el("p", { class: "hint" },
      `기동 엔벨로프는 n_z=${fmt(man.nz, 3)} g를 낼 수 있는 영역 — 하한만 올라가므로 1g 영역의 안쪽이다. `
      // 다 열린 흔한 경우(낮은 n_z)에 "0행 … 0행 … 0행"을 늘어놓지 않는다
      + (nEmpty
        ? `${nEmpty}/${man.region.alt.length}행이 비었고 그중 ${nReach}행은 `
          + `'${boundLabel("n_reach")}' — 그 고도에서는 어느 마하로도 그 하중배수를 못 낸다. `
          + `나머지 ${nEmpty - nReach}행은 하한이 상한(구조·DB·q̄)을 넘어 닫힌 것이다. `
        : "표시 고도 전 구간에서 이 하중배수가 가능하다. ")
      + (man.nz_over_limit
        ? "⚠ 입력한 n_z가 구조 제한하중을 넘습니다 — 구조 엔벨로프 밖입니다."
        : "V-n 선도의 같은 n_z 선과 한 세트.")));
  }
  const outCount = lastMh.schedule_grid.points.filter((p) => outsideRegion(p, lastMh.region)).length;
  if (outCount) {
    kids.push(el("p", { class: "hint" },
      `⚠ 스케줄 격자점 ${outCount}개가 합성 영역 밖(×)입니다 — 격자 좌표는 coarse 격자(design.grid)와 `
      + "맞추려고 q̄를 보지 않고 만들어지므로, 이것이 실제 설계점 위치입니다. 좌표를 옮기지 않고 표시만 합니다."));
  }
  if (cells && cells.length) {
    // 범례·집계도 층 토글을 따른다 — 안 그리는 점의 개수를 세어 주면 화면과 어긋난다
    if (layers.scan) {
      const s = scanSummary(cells);
      kids.push(el("div", { class: "legend" },
        el("span", {}, el("span", { class: "chip", style: `background:${kindColor("ok")}` }),
          `${kindLabel("ok")} ${s.ok}/${s.total}`),
        ...s.byKind.map(({ kind, n }) => el("span", {},
          el("span", { class: "chip", style: `background:${kindColor(kind)}` }),
          `${kindLabel(kind)} ${n}건`)),
      ));
    }
    if (layers.thrust) {
      const frontier = thrustFrontier(cells);
      const nLo = frontier.filter((p) => p.side === "lo").length;
      const nProv = frontier.filter((p) => p.provisional).length;
      kids.push(el("p", { class: "hint" }, frontier.length
        ? `추력 한계 경계 — 고속 전이 ${frontier.length - nLo}점 · 저속(항력곡선 backside) 전이 ${nLo}점`
          + (nProv ? `, 그중 ${nProv}점은 미수렴 셀이라 잠정(속 빈 원) — 그 스로틀은 해가 아니라 솔버의 마지막 반복값입니다. ` : ". ")
          + "프로펠러 추력 곡선 T = δσ·min(T_static, ηP/V)에서 트림이 스로틀 상한에 닿은 지점입니다 — "
          + "다만 그 상한은 100%가 아니라 스로틀 95% 등고선입니다(trim.py SAT_FRAC). 설계 여유만큼 진짜 한계보다 안쪽입니다. "
          + "해석 곡선이 아니므로 스캔 격자 해상도가 곧 경계 해상도이고, 격자를 촘촘히 하면 경계가 움직입니다."
        : "추력 한계 경계 없음 — 스캔 격자 안에서 스로틀 상한 포화가 나오지 않았습니다. "
          + "상한이 없다는 뜻이 아니라 격자가 거기 닿지 않았다는 뜻입니다."));
    }
  } else if (allCells) {
    // 스캔은 있는데 이 차트 연료와 안 맞는다 — 옛 집계를 그대로 보여주면 거짓말이 된다
    const scanned = [...new Set(allCells.map((c) => c.fuel))].join(", ");
    kids.push(el("p", { class: "hint" },
      `스캔 연료(${scanned} kg)가 차트 연료(${fmt(lastMh.fuel, 4)} kg)와 달라 판정 점을 겹치지 `
      + "않습니다 — 현재 연료로 트림 스캔을 다시 실행하세요."));
  } else {
    kids.push(el("p", { class: "hint" },
      "제어 가능 영역은 아직 미판정 — 폼의 트림 스캔을 실행하면 격자 점별 판정이 덧그려집니다."));
  }
  if (lastMh.bounds.alt_max_is_display_default) {
    kids.push(el("p", { class: "hint" },
      `표시 고도 상한 ${fmt(lastMh.bounds.alt_max_used, 5)} m는 표시용 [기본값] — 운용 상한이 아님 `
      + "(운용 상한을 입력하면 그 값으로 잘림)."));
  }
  kids.push(placeholderHint(lastMh));
  clear(box).append(...kids);
}

// ── 구조 (V-n — 교과서형, 기존 캔버스 유지) ───────────────────────────────

function vnDiagramCanvas(body) {
  const W = 780;
  const H = 470;
  const { canvas, ctx } = makeCanvas(W, H);
  const mL = 52, mT = 30, mR = 16, mB = 40;
  const L = body.limits;
  const V = body.V;
  const nS = body.n_stall;
  const nP = body.n_prot;
  const nN = body.n_stall_neg ?? null; // 구버전 응답(재시작 전 캐시) 방어

  const vMax = L.v_d * 1.08;
  // 극한하중 살짝 위까지만 — 실속 포물선의 세로 기울기 강조 (교과서형)
  const nTop = L.n_ultimate_pos * 1.1;
  const nBot = L.n_ultimate_neg * 1.15;
  const px = linScale(V[0], vMax, mL, W - mR);
  const py = linScale(nBot, nTop, H - mB, mT);
  const interpAt = (arr) => (v) => {
    for (let i = 1; i < V.length; i += 1) {
      if (V[i] >= v) {
        const t = (v - V[i - 1]) / (V[i] - V[i - 1]);
        return arr[i - 1] + t * (arr[i] - arr[i - 1]);
      }
    }
    return arr[arr.length - 1];
  };
  const stallAt = interpAt(nS);
  const negAt = nN ? interpAt(nN) : null;
  // 정상 운용 하한 — 음의 실속 자리표시가 있으면 max(음실속, −제한), 없으면 −제한
  const lowAt = (v) => (nN ? Math.max(negAt(v), L.n_limit_neg) : L.n_limit_neg);

  // ── 배경 영역 (뒤→앞) ──
  ctx.fillStyle = C.failure; // 기본 = 구조 파괴 (극한 밖·V_D 밖)
  ctx.fillRect(mL, mT, W - mL - mR, H - mT - mB);
  ctx.fillStyle = C.damage; // 구조 손상: 제한~극한, V ≤ V_D
  ctx.fillRect(mL, py(L.n_ultimate_pos), px(L.v_d) - mL, py(L.n_limit_pos) - py(L.n_ultimate_pos));
  ctx.fillRect(mL, py(L.n_limit_neg), px(L.v_d) - mL, py(L.n_ultimate_neg) - py(L.n_limit_neg));
  ctx.fillStyle = C.caution; // 주의: V_NO~V_D, 제한하중 이내
  ctx.fillRect(px(L.v_no), py(L.n_limit_pos), px(L.v_d) - px(L.v_no), py(L.n_limit_neg) - py(L.n_limit_pos));
  // 정상 운용: V ≤ V_NO, 위 = min(실속, +제한), 아래 = max(음실속 자리표시, −제한)
  ctx.fillStyle = C.ok;
  ctx.beginPath();
  ctx.moveTo(px(V[0]), py(lowAt(V[0])));
  ctx.lineTo(px(V[0]), py(Math.min(stallAt(V[0]), L.n_limit_pos)));
  for (let i = 0; i < V.length && V[i] <= L.v_no; i += 1) {
    ctx.lineTo(px(V[i]), py(Math.min(nS[i], L.n_limit_pos)));
  }
  ctx.lineTo(px(L.v_no), py(Math.min(stallAt(L.v_no), L.n_limit_pos)));
  ctx.lineTo(px(L.v_no), py(lowAt(L.v_no)));
  if (nN) {
    for (let i = V.length - 1; i >= 0; i -= 1) {
      if (V[i] <= L.v_no) ctx.lineTo(px(V[i]), py(Math.max(nN[i], L.n_limit_neg)));
    }
  }
  ctx.closePath();
  ctx.fill();
  // 실속 영역 상부 (공력 도달 불가): 실속 곡선 위, +제한 아래, V ≤ V_A쪽
  ctx.fillStyle = C.stallZone;
  ctx.beginPath();
  ctx.moveTo(px(V[0]), py(Math.min(stallAt(V[0]), L.n_limit_pos)));
  for (let i = 0; i < V.length && nS[i] <= L.n_limit_pos; i += 1) {
    ctx.lineTo(px(V[i]), py(nS[i]));
  }
  const vA = body.speeds.v_a ?? L.v_d;
  ctx.lineTo(px(vA), py(L.n_limit_pos));
  ctx.lineTo(px(V[0]), py(L.n_limit_pos));
  ctx.closePath();
  ctx.fill();
  // 실속 영역 하부 — 음의 실속 자리표시 곡선 아래, −제한 위 (벌어지는 입 모양)
  if (nN) {
    ctx.fillStyle = C.stallZone;
    ctx.beginPath();
    ctx.moveTo(px(V[0]), py(Math.max(nN[0], L.n_limit_neg)));
    for (let i = 0; i < V.length && nN[i] >= L.n_limit_neg; i += 1) {
      ctx.lineTo(px(V[i]), py(nN[i]));
    }
    const k = nN.findIndex((n) => n < L.n_limit_neg); // −제한 교차(음의 기동속도 상당)
    const vAneg = k > 0
      ? V[k - 1] + ((V[k] - V[k - 1]) * (L.n_limit_neg - nN[k - 1])) / (nN[k] - nN[k - 1])
      : L.v_d;
    ctx.lineTo(px(vAneg), py(L.n_limit_neg));
    ctx.lineTo(px(V[0]), py(L.n_limit_neg));
    ctx.closePath();
    ctx.fill();
  }

  // ── 곡선·한계선 (플롯 영역 클리핑) ──
  ctx.save();
  ctx.beginPath();
  ctx.rect(mL, mT, W - mL - mR, H - mT - mB);
  ctx.clip();
  const curve = (data, color, { width = 2, i0 = 0, i1 = data.length - 1, dash = null } = {}) => {
    ctx.strokeStyle = color;
    ctx.lineWidth = width;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    if (dash) ctx.setLineDash(dash);
    ctx.beginPath();
    for (let i = i0; i <= i1; i += 1) {
      if (i === i0) ctx.moveTo(px(V[i]), py(data[i]));
      else ctx.lineTo(px(V[i]), py(data[i]));
    }
    ctx.stroke();
    ctx.setLineDash([]);
  };
  // 제한하중 교차 전 실선(엔벨로프 경계), 이후 점선(엔벨로프 밖 참고 정보)
  const splitCurve = (data, color, limit, below) => {
    let k = data.findIndex((n) => (below ? n < limit : n > limit));
    if (k < 0) k = data.length;
    curve(data, color, { i1: Math.min(k, data.length - 1) });
    if (k < data.length) curve(data, color, { i0: Math.max(0, k - 1), dash: [5, 4], width: 1.3 });
  };
  splitCurve(nS, C.stallLine, L.n_limit_pos, false);
  splitCurve(nP, C.protLine, L.n_limit_pos, false);
  if (nN) splitCurve(nN, C.stallLine, L.n_limit_neg, true); // 음의 실속 자리표시
  const hline = (n, color, dash, label) => {
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.2;
    ctx.setLineDash(dash);
    ctx.beginPath();
    ctx.moveTo(mL, py(n));
    ctx.lineTo(px(L.v_d), py(n));
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = color;
    ctx.fillText(label, mL + 6, py(n) - 4);
  };
  hline(L.n_limit_pos, C.limitLine, [6, 4], `+제한하중 ${fmt(L.n_limit_pos, 3)} g`);
  hline(L.n_limit_neg, C.limitLine, [6, 4], `−제한하중 ${fmt(L.n_limit_neg, 3)} g`);
  hline(L.n_ultimate_pos, C.ultLine, [3, 3], `+극한하중 ${fmt(L.n_ultimate_pos, 3)} g (제한×${L.safety_factor})`);
  hline(L.n_ultimate_neg, C.ultLine, [3, 3], `−극한하중 ${fmt(L.n_ultimate_neg, 3)} g`);
  hline(1.0, "#aeaeb2", [2, 4], "n=1 수평비행");
  // M-h 탭의 기동 엔벨로프와 같은 n_z — 두 패널이 같은 축을 본다는 것을 눈으로 잇는다
  const nzMan = layers.maneuver ? lastMh?.maneuver?.nz : null;
  if (nzMan != null && nzMan > nBot && nzMan < nTop) {
    hline(nzMan, C.manLine, [5, 3], `기동 n_z=${fmt(nzMan, 3)} g (M-h 기동 엔벨로프)`);
  }
  const vline = (v, label) => {
    if (v == null) return;
    ctx.strokeStyle = C.speedLine;
    ctx.lineWidth = 1.2;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(px(v), mT);
    ctx.lineTo(px(v), H - mB);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = C.speedLine;
    ctx.fillText(label, px(v) + 3, mT + 12);
  };
  vline(body.speeds.v_s, `V_S ${fmt(body.speeds.v_s, 4)}`);
  vline(body.speeds.v_a, `V_A ${fmt(body.speeds.v_a, 4)}`);
  vline(L.v_no, `V_NO ${fmt(L.v_no, 4)}`);
  vline(L.v_d, `V_D ${fmt(L.v_d, 4)}`);
  ctx.restore();

  // 플롯 영역 헤어라인 프레임 (존 색면 가장자리 정리)
  ctx.strokeStyle = C.frame;
  ctx.lineWidth = 1;
  ctx.strokeRect(mL, mT, W - mL - mR, H - mT - mB);

  // 영역 라벨 (세미볼드)
  ctx.font = FONT_LABEL;
  ctx.fillStyle = C.sub;
  ctx.fillText("정상 운용", px(L.v_no * 0.62), py(L.n_limit_pos * 0.45));
  ctx.fillText("실속 영역", px(V[0]) + 14, py(L.n_limit_pos) + 26);
  if (nN) ctx.fillText("실속 영역", px(V[0]) + 14, py(L.n_limit_neg) - 10);
  ctx.fillText("주의", (px(L.v_no) + px(L.v_d)) / 2 - 12, py(0.2));
  ctx.fillText("구조 손상", px(L.v_d * 0.45), (py(L.n_limit_pos) + py(L.n_ultimate_pos)) / 2 + 4);
  ctx.fillText("구조 파괴", px(L.v_d * 0.45), py(L.n_ultimate_pos) - 8);

  // 축
  ctx.font = FONT_BASE;
  ctx.fillStyle = C.sub;
  for (const t of niceTicks(V[0], vMax, 7)) {
    ctx.fillText(`${Math.round(t)}`, px(t) - 10, H - mB + 16);
  }
  for (const t of niceTicks(nBot, nTop, 8)) {
    ctx.fillText(`${Math.round(t * 10) / 10}`, 8, py(t) + 3);
  }
  ctx.fillText("V (TAS) [m/s]", W / 2 - 30, H - 8);
  ctx.font = FONT_TITLE;
  ctx.fillStyle = C.text;
  ctx.fillText(`n [g] — h ${fmt(body.alt, 4)} m · 연료 ${fmt(body.fuel, 4)} kg`, mL, 18);
  ctx.font = FONT_BASE;
  return canvas;
}

function renderVn(box) {
  if (!lastVn) {
    clear(box).append(el("p", { class: "hint" }, "그리기 실행 시 표시됩니다."));
    return;
  }
  const body = lastVn;
  clear(box).append(
    el("div", { class: "scroll-x" }, vnDiagramCanvas(body)),
    el("div", { class: "legend" },
      el("span", {}, el("span", { class: "chip", style: `background:${C.ok}` }), "정상 운용"),
      el("span", {}, el("span", { class: "chip", style: `background:${C.stallZone}` }), "실속 영역 (공력 도달 불가)"),
      el("span", {}, el("span", { class: "chip", style: `background:${C.caution}` }), "주의 (V_NO~V_D)"),
      el("span", {}, el("span", { class: "chip", style: `background:${C.damage}` }), "구조 손상 (제한~극한)"),
      el("span", {}, el("span", { class: "chip", style: `background:${C.failure}` }), "구조 파괴 (극한 밖·V_D 밖)"),
      el("span", {}, el("span", { class: "chip", style: `background:${C.stallLine}` }), "실속 경계 (±)"),
      el("span", {}, el("span", { class: "chip", style: `background:${C.protLine}` }), "α 리미터 보호 경계")),
    el("p", { class: "hint" },
      "V_S 실속속도(n=1) · V_A 기동속도(실속선∩제한하중) · V_NO 최대 구조 순항속도 · ",
      "V_D 급강하 한계속도. 보호선(녹)이 법칙이 명령을 자르는 선 — 실속선 안쪽. ",
      "실속·보호선은 제한하중 교차 이후 점선(엔벨로프 밖 참고)."),
    placeholderHint(body),
    el("p", { class: "hint" },
      "음의 실속 곡선은 자리표시 ",
      `(−${fmt(body.neg_alpha_ratio ?? 0.6, 3)}×α_stall 가정 [기본값]) — 공력 정본 확보 시 교체.`),
  );
}

// ── 공력 (α–Mach) ─────────────────────────────────────────────────────────

function aeroCanvas(aero) {
  const W = 620;
  const H = 320;
  const { canvas, ctx } = makeCanvas(W, H);
  const mL = 56, mT = 30, mR = 16, mB = 40;
  const xMin = Math.min(aero.db.mach[0], aero.mach[0]) - 0.03;
  const xMax = Math.max(aero.db.mach[1], aero.mach[aero.mach.length - 1]) + 0.03;
  const aTop = Math.max(aero.db.alpha[1], ...aero.alpha_stall) + 0.06;
  const aBot = Math.min(aero.db.alpha[0], aero.trim_alpha_bounds?.[0] ?? 0) - 0.06;
  const px = linScale(xMin, xMax, mL, W - mR);
  const py = linScale(aBot, aTop, H - mB, mT);

  // 공력 DB 유효범위 박스 (α×Mach)
  ctx.fillStyle = C.dbTint;
  ctx.fillRect(px(aero.db.mach[0]), py(aero.db.alpha[1]),
    px(aero.db.mach[1]) - px(aero.db.mach[0]), py(aero.db.alpha[0]) - py(aero.db.alpha[1]));
  ctx.strokeStyle = "#af52de";
  ctx.lineWidth = 1.2;
  ctx.setLineDash([4, 4]);
  ctx.strokeRect(px(aero.db.mach[0]), py(aero.db.alpha[1]),
    px(aero.db.mach[1]) - px(aero.db.mach[0]), py(aero.db.alpha[0]) - py(aero.db.alpha[1]));
  ctx.setLineDash([]);

  const curve = (ys, color) => {
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.lineCap = "round";
    ctx.beginPath();
    aero.mach.forEach((m, i) => (i === 0 ? ctx.moveTo(px(m), py(ys[i])) : ctx.lineTo(px(m), py(ys[i]))));
    ctx.stroke();
  };
  curve(aero.alpha_stall, C.stallLine);
  curve(aero.alpha_prot, C.protLine);

  // 트림 탐색 α 범위 — 엔진 상수 echo (null이면 그리지 않는다)
  if (aero.trim_alpha_bounds) {
    for (const [a, label] of [
      [aero.trim_alpha_bounds[0], `트림 α 하한 ${fmt(aero.trim_alpha_bounds[0], 3)}`],
      [aero.trim_alpha_bounds[1], `트림 α 상한 ${fmt(aero.trim_alpha_bounds[1], 3)}`],
    ]) {
      ctx.strokeStyle = C.speedLine;
      ctx.lineWidth = 1.2;
      ctx.setLineDash([2, 4]);
      ctx.beginPath();
      ctx.moveTo(mL, py(a));
      ctx.lineTo(W - mR, py(a));
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = C.speedLine;
      ctx.fillText(label, mL + 6, py(a) - 4);
    }
  }

  ctx.font = FONT_LABEL;
  ctx.fillStyle = C.stallLine;
  ctx.fillText("실속 경계 α_stall(M)", px(aero.mach[2] ?? aero.mach[0]), py(aero.alpha_stall[2] ?? aero.alpha_stall[0]) - 8);
  ctx.fillStyle = C.protLine;
  ctx.fillText(`보호선 (−${fmt(aero.alpha_margin, 3)} rad)`,
    px(aero.mach[Math.floor(aero.mach.length / 2)]),
    py(aero.alpha_prot[Math.floor(aero.mach.length / 2)]) + 14);
  ctx.fillStyle = "#af52de";
  ctx.fillText("공력 DB 유효범위", px(aero.db.mach[0]) + 6, py(aero.db.alpha[0]) - 6);

  ctx.strokeStyle = C.frame;
  ctx.lineWidth = 1;
  ctx.strokeRect(mL, mT, W - mL - mR, H - mT - mB);
  ctx.font = FONT_BASE;
  ctx.fillStyle = C.sub;
  for (const t of niceTicks(xMin, xMax, 7)) ctx.fillText(fmt(t, 3), px(t) - 10, H - mB + 16);
  for (const t of niceTicks(aBot, aTop, 7)) ctx.fillText(fmt(t, 3), 8, py(t) + 3);
  ctx.fillText("Mach", W / 2 - 14, H - 8);
  ctx.font = FONT_TITLE;
  ctx.fillStyle = C.text;
  ctx.fillText("α [rad]", mL, 18);
  return canvas;
}

function renderAero(box) {
  if (!lastMh?.aero) {
    clear(box).append(el("p", { class: "hint" }, "그리기 실행 시 표시됩니다."));
    return;
  }
  clear(box).append(
    el("div", { class: "scroll-x" }, aeroCanvas(lastMh.aero)),
    el("p", { class: "hint" },
      "실속 경계(공력팀 정본 테이블, 01 §2.3)와 α 리미터 보호선 — 설계 엔벨로프의 ",
      "저속 경계는 이 곡선의 V_S 역산(×실속 여유)에서 온다. DB 박스 밖은 공력 ",
      "데이터 유효성이 보장되지 않는 영역, 트림 α 범위는 엔진 탐색 한계 echo."),
  );
}

// ── 추진 (스로틀 소요 히트맵) ─────────────────────────────────────────────

function renderProp(box) {
  if (!lastScan) {
    clear(box).append(el("p", { class: "hint" },
      "추진 엔벨로프는 프로펠러 추력 곡선에 대한 트림 스로틀 소요로 표면화합니다 — ",
      "폼의 트림 스캔을 실행하면 격자별 n=1 수평비행 스로틀 소요와 포화 경계가 표시됩니다."));
    return;
  }
  const entries = lastScan.cases;
  const fuels = fuelsOf(entries);
  const kids = [];
  for (const fuel of fuels) {
    kids.push(el("div", { class: "scroll-x" },
      heatmapCanvas(pivotCases(entries, fuel), throttleCell,
        { title: `스로틀 소요 — n=1 수평비행 트림, 연료 ${fmt(fuel, 4)} kg` })));
  }
  kids.push(el("p", { class: "hint" },
    "추진 한계는 프로펠러 추력 곡선 T = δσ·min(T_static, ηP/V)이 정하고, 화면에는 ",
    "트림 스로틀 상한 포화(saturated_throttle_high, 엔진 판정)로 드러납니다 — 그 선은 ",
    "스로틀 95% 등고선이라(SAT_FRAC) 진짜 한계보다 설계 여유만큼 안쪽입니다. ",
    "셀 % = 트림 스로틀 소요, ",
    "적색 = 포화(설계 영역 밖 — 95~100% 칸은 수평비행 자체는 되지만 여유가 없다), ",
    "회색 = 트림 미수렴."));
  clear(box).append(...kids);
}

// ── 운용 (입력 한계 박스) ─────────────────────────────────────────────────

function opsCanvas(b) {
  const W = 620;
  const H = 260;
  const { canvas, ctx } = makeCanvas(W, H);
  const mL = 56, mT = 26, mR = 16, mB = 36;
  const xMin = 0;
  const xMax = b.mach_d + 0.06;
  const px = linScale(xMin, xMax, mL, W - mR);
  const py = linScale(b.alt_min_used, b.alt_max_used, H - mB, mT);

  const yTop = b.alt_max != null ? py(b.alt_max) : mT;
  const yBot = b.alt_min != null ? py(b.alt_min) : H - mB;
  // 운용 박스 — 입력된 한계로만 (M 상한은 구조 순항 M_NO까지)
  ctx.fillStyle = "#e8f1fe";
  ctx.fillRect(mL, yTop, px(b.mach_no) - mL, yBot - yTop);

  const hline = (alt, label) => {
    ctx.strokeStyle = C.opsLine;
    ctx.lineWidth = 1.6;
    ctx.beginPath();
    ctx.moveTo(mL, py(alt));
    ctx.lineTo(W - mR, py(alt));
    ctx.stroke();
    ctx.fillStyle = C.opsLine;
    ctx.fillText(label, mL + 6, py(alt) < mT + 16 ? py(alt) + 14 : py(alt) - 5);
  };
  if (b.alt_min != null) hline(b.alt_min, `운용 하한 ${fmt(b.alt_min, 5)} m`);
  if (b.alt_max != null) hline(b.alt_max, `운용 상한 ${fmt(b.alt_max, 5)} m`);
  for (const [v, label] of [[b.mach_no, `M_NO ${fmt(b.mach_no, 3)}`], [b.mach_d, `M_D ${fmt(b.mach_d, 3)}`]]) {
    ctx.strokeStyle = C.limitLine;
    ctx.lineWidth = 1.4;
    ctx.setLineDash([5, 4]);
    ctx.beginPath();
    ctx.moveTo(px(v), mT);
    ctx.lineTo(px(v), H - mB);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = C.limitLine;
    if (px(v) > W - mR - 70) { // 오른쪽 끝 — 선 왼쪽에 붙여 캔버스 밖으로 잘리지 않게
      ctx.textAlign = "right";
      ctx.fillText(label, px(v) - 3, mT + 12);
      ctx.textAlign = "left";
    } else {
      ctx.fillText(label, px(v) + 3, mT + 12);
    }
  }

  ctx.strokeStyle = C.frame;
  ctx.lineWidth = 1;
  ctx.strokeRect(mL, mT, W - mL - mR, H - mT - mB);
  ctx.font = FONT_BASE;
  ctx.fillStyle = C.sub;
  for (const t of niceTicks(xMin, xMax, 7)) ctx.fillText(fmt(t, 3), px(t) - 10, H - mB + 16);
  for (const t of niceTicks(b.alt_min_used, b.alt_max_used, 6)) ctx.fillText(`${Math.round(t)}`, 6, py(t) + 3);
  ctx.fillText("Mach", W / 2 - 14, H - 8);
  ctx.font = FONT_TITLE;
  ctx.fillStyle = C.text;
  ctx.fillText("h [m] — 운용 한계 (입력값)", mL, 16);
  return canvas;
}

function renderOps(box) {
  if (!lastMh) {
    clear(box).append(el("p", { class: "hint" }, "그리기 실행 시 표시됩니다."));
    return;
  }
  const b = lastMh.bounds;
  if (b.alt_min == null && b.alt_max == null) {
    clear(box).append(el("p", { class: "hint" },
      "운용 고도 한계 미입력 — 경계 없음 (없는 값을 그리지 않습니다). 폼의 운용 ",
      "하한·상한을 입력하면 여기와 합성 차트에 반영됩니다. 마하 방향 운용 한계는 ",
      "구조 M_NO·M_D를 준용."));
    return;
  }
  clear(box).append(
    el("div", { class: "scroll-x" }, opsCanvas(b)),
    el("p", { class: "hint" },
      "운용 엔벨로프 — 사용자 입력 고도 한계 × 마하 한계(M_NO 준용). 미입력 경계는 ",
      "표시하지 않으며 합성에도 들어가지 않습니다."),
  );
}
