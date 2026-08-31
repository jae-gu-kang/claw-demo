/** 엔벨로프 뷰 (01 §2.6) — 제어법칙 설계 엔벨로프: 필요값 입력 → 합성 + 구성 선도.

설계 엔벨로프 = 구조 ∧ 공력 ∧ 추진 ∧ 운용 ∧ 제어 가능 영역 — V-n 선도는
설계점 선정표가 아니라 상위 constraint 하나다. 패널: 필요값 폼 → M-h 합성
(경계별 색 귀속 + 스케줄 격자점 + 트림 스캔 판정) → 구조(V-n, 교과서형)
→ 공력(α–Mach) → 추진(스로틀 소요 히트맵 — 전용 추력 모델 [TBD] 전까지
트림 스로틀이 대리) → 운용(입력 한계 박스).

수치는 전부 엔진(vn_envelope·design_envelope·envelope_verdict) — 여기서는
표시만. 표현 변환(다각형·세그먼트·셀 분류·프리필)은 lib/envelope.js(테스트).
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

// [폼 키, 서버 파라미터] — 구조 한계 오버라이드 5종 (vn·design-envelope 공유 계약)
const STRUCT_FIELDS = [
  ["nPos", "n_limit_pos"], ["nNeg", "n_limit_neg"], ["sf", "safety_factor"],
  ["machNo", "mach_no"], ["machD", "mach_d"],
];

const LAYER_FIELDS = [
  ["isoQbar", "등동압선"], ["isoTas", "등속선"], ["maneuver", "기동 엔벨로프"],
  ["scan", "스캔 판정"], ["thrust", "추력 대리 경계"],
];

export function render() {
  const errBox = el("div");
  const progressBox = el("div");
  const mhBox = el("div");
  const vnBox = el("div");
  const aeroBox = el("div");
  const propBox = el("div");
  const opsBox = el("div");

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
  };

  const root = el("div", {},
    el("div", { class: "panel" },
      el("h2", {}, "설계 엔벨로프 — 필요값 입력"),
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
        el("div", { class: "opt-group" },
          el("div", { class: "g-title" }, "제어 가능 스캔 격자 (트림 잡 — 점당 트림 1회)"),
          el("div", { class: "row-inner" },
            el("label", { class: "field" }, "마하 시작", bind("scanFrom", { class: "num-sm" })),
            el("label", { class: "field" }, "끝", bind("scanTo", { class: "num-sm" })),
            el("label", { class: "field" }, "간격", bind("scanStep", { class: "num-sm" })),
            el("label", { class: "field grow" }, "고도 목록 [m]", bind("scanAlts", { class: "" })),
            el("button", { onclick: runScan }, "제어 가능 판정 (트림 스캔)"))),
      ),
      el("div", { class: "row", style: "margin-top: 10px" },
        el("span", { class: "g-title" }, "M-h 레이어"),
        ...LAYER_FIELDS.map(([key, label]) => layerToggle(key, label)),
      ),
      el("p", { class: "hint" },
        "설계 엔벨로프 = 구조 ∧ 공력 ∧ 추진 ∧ 운용 ∧ 제어 가능 영역 (01 §2.6) — ",
        "V-n은 상위 constraint 하나. 구조 필드는 손댄 것만 서버로 보내고(02 §5.5), ",
        "빈칸으로 되돌리면 데모 자리표시로 복귀. 실속 여유 빈칸 = 엔진 기본값. ",
        "기동 n_z는 그 하중배수를 낼 수 있는 영역(1g 영역의 안쪽) — 빈칸이면 안 그린다."),
      progressBox, errBox,
    ),
    el("div", { class: "panel" }, el("h2", {}, "설계 엔벨로프 합성 (M-h)"), mhBox),
    el("div", { class: "panel" }, el("h2", {}, "구조 엔벨로프 — V-n 선도"), vnBox),
    el("div", { class: "panel" }, el("h2", {}, "공력 엔벨로프 — α–Mach"), aeroBox),
    el("div", { class: "panel" }, el("h2", {}, "추진 엔벨로프 — 스로틀 소요"), propBox),
    el("div", { class: "panel" }, el("h2", {}, "운용 엔벨로프"), opsBox),
  );
  if (lastVn || lastMh) renderAll();
  else draw();
  if (runningJobId) watch(); // 실행 중 재진입 — 진행 UI 재부착
  return root;
}

// 애플 시스템 팔레트 — 존은 옅은 틴트, 경계선은 시스템 컬러 (구조도와 동일 언어)
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
  // 화면이 "여기가 상승한도"라고 말해버린다 (추력 모델은 없다, 01 §2.6 [TBD])
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

  // 추력 대리 경계 — 스캔의 스로틀 상한 포화 전선. 해석 곡선이 아니라 측정점이라
  // 격자 해상도가 곧 경계 해상도다 (전용 추력 모델 [TBD] — 대체가 아니다)
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
    haloText(side === "lo" ? "추력 대리 (저속)" : "추력 대리 (고속)",
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
      "추력 대리 경계 (스로틀 상한 포화)")] : []),
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
        ? `추력 대리 경계 — 고속 전이 ${frontier.length - nLo}점 · 저속(항력곡선 backside) 전이 ${nLo}점`
          + (nProv ? `, 그중 ${nProv}점은 미수렴 셀이라 잠정(속 빈 원) — 그 스로틀은 해가 아니라 솔버의 마지막 반복값입니다. ` : ". ")
          + "전용 추력 모델이 아니라 트림이 스로틀 상한에 닿은 지점입니다(01 §2.6 [TBD]). "
          + "해석 곡선이 아니므로 스캔 격자 해상도가 곧 경계 해상도이고, 격자를 촘촘히 하면 경계가 움직입니다."
        : "추력 대리 경계 없음 — 스캔 격자 안에서 스로틀 상한 포화가 나오지 않았습니다. "
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
      "전용 추진 모델이 없어 추진 엔벨로프는 트림 스로틀 소요로 표면화합니다 [TBD] — ",
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
    "⚠ 전용 추력 모델 부재 [TBD] — 추진 한계는 트림 스로틀 상한 포화",
    "(saturated_throttle_high, 엔진 판정)로만 드러납니다. 셀 % = 트림 스로틀 소요, ",
    "적색 = 포화(그 점은 수평비행 유지 불가 — 설계 영역 밖), 회색 = 트림 미수렴."));
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
