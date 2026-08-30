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
  boundColor, boundLabel, boundarySegments, envelopeQuery, kindColor, kindLabel,
  optNum, prefillValue, regionPolygons, scanCells, scanSummary, throttleCell,
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
  qMax: "", altMin: "", altMax: "", machMargin: "",
  scanFrom: "0.2", scanTo: "0.7", scanStep: "0.05", scanAlts: "0, 1000, 3000, 5000",
};
const touched = new Set(); // 구조 필드 중 사용자가 손댄 것 — 이것만 서버로 보낸다

// [폼 키, 서버 파라미터] — 구조 한계 오버라이드 5종 (vn·design-envelope 공유 계약)
const STRUCT_FIELDS = [
  ["nPos", "n_limit_pos"], ["nNeg", "n_limit_neg"], ["sf", "safety_factor"],
  ["machNo", "mach_no"], ["machD", "mach_d"],
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
            el("label", { class: "field" }, "실속 여유 ×", bind("machMargin")))),
        el("div", { class: "opt-group" },
          el("div", { class: "g-title" }, "제어 가능 스캔 격자 (트림 잡 — 점당 트림 1회)"),
          el("div", { class: "row-inner" },
            el("label", { class: "field" }, "마하 시작", bind("scanFrom", { class: "num-sm" })),
            el("label", { class: "field" }, "끝", bind("scanTo", { class: "num-sm" })),
            el("label", { class: "field" }, "간격", bind("scanStep", { class: "num-sm" })),
            el("label", { class: "field grow" }, "고도 목록 [m]", bind("scanAlts", { class: "" })),
            el("button", { onclick: runScan }, "제어 가능 판정 (트림 스캔)"))),
      ),
      el("p", { class: "hint" },
        "설계 엔벨로프 = 구조 ∧ 공력 ∧ 추진 ∧ 운용 ∧ 제어 가능 영역 (01 §2.6) — ",
        "V-n은 상위 constraint 하나. 구조 필드는 손댄 것만 서버로 보내고(02 §5.5), ",
        "빈칸으로 되돌리면 데모 자리표시로 복귀. 실속 여유 빈칸 = 엔진 기본값."),
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
};
const FONT_BASE = "11px -apple-system, 'Segoe UI', sans-serif";
const FONT_LABEL = "600 11px -apple-system, 'Segoe UI', sans-serif";
const FONT_TITLE = "600 12px -apple-system, 'Segoe UI', sans-serif";

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
  const H = 470;
  const { canvas, ctx } = makeCanvas(W, H);
  const mL = 56, mT = 30, mR = 16, mB = 40;
  const b = mh.bounds;
  const r = mh.region;
  const xMin = Math.min(b.db_mach[0], ...r.mach_lo) - 0.03;
  const xMax = Math.max(b.mach_d, ...r.mach_hi) + 0.03;
  const px = linScale(xMin, xMax, mL, W - mR);
  const py = linScale(b.alt_min_used, b.alt_max_used, H - mB, mT);

  ctx.strokeStyle = C.frame;
  ctx.lineWidth = 1;
  ctx.strokeRect(mL, mT, W - mL - mR, H - mT - mB);
  ctx.save();
  ctx.beginPath();
  ctx.rect(mL, mT, W - mL - mR, H - mT - mB);
  ctx.clip();

  // 설계 영역 틴트
  ctx.fillStyle = C.ok;
  for (const poly of regionPolygons(r)) {
    ctx.beginPath();
    poly.forEach((p, i) => (i === 0 ? ctx.moveTo(px(p.mach), py(p.alt)) : ctx.lineTo(px(p.mach), py(p.alt))));
    ctx.closePath();
    ctx.fill();
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
  vline(b.db_mach[0], `DB ${fmt(b.db_mach[0], 3)}`, "#c7b3e0");
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
  // 귀속 라벨 — source별 가장 긴 세그먼트의 중앙에 한 번
  ctx.font = FONT_LABEL;
  const longest = new Map();
  for (const seg of segs) {
    if (seg.pts.length < 2) continue;
    if (!longest.has(seg.source) || longest.get(seg.source).pts.length < seg.pts.length) {
      longest.set(seg.source, seg);
    }
  }
  for (const seg of longest.values()) {
    const mid = seg.pts[Math.floor(seg.pts.length / 2)];
    ctx.fillStyle = boundColor(seg.source);
    const dx = seg.side === "lo" ? -8 : 8;
    ctx.textAlign = seg.side === "lo" ? "right" : "left";
    ctx.fillText(boundLabel(seg.source), px(mid.mach) + dx, py(mid.alt));
  }
  ctx.textAlign = "left";

  // 게인 스케줄 격자점 (엔진 coarse 좌표 — trimmable 미판정, 빈 원)
  for (const p of mh.schedule_grid.points) {
    ctx.strokeStyle = C.schedPt;
    ctx.lineWidth = 1.4;
    ctx.beginPath();
    ctx.arc(px(p.mach), py(p.alt), 4, 0, Math.PI * 2);
    ctx.stroke();
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
  if (cells) {
    for (const c of cells) {
      ctx.fillStyle = kindColor(c.kind);
      ctx.beginPath();
      ctx.arc(px(c.mach), py(c.alt), 3.2, 0, Math.PI * 2);
      ctx.fill();
    }
  }
  ctx.restore();

  // 영역 라벨 + 축
  ctx.font = FONT_LABEL;
  ctx.fillStyle = C.sub;
  const okRow = r.empty.findIndex((e) => !e);
  if (okRow >= 0) {
    ctx.fillText("설계 영역",
      (px(r.mach_lo[okRow]) + px(r.mach_hi[okRow])) / 2 - 24,
      py(r.alt[okRow]) - 12);
  } else {
    ctx.fillText("설계 영역 없음 — 경계가 전 고도에서 닫힘", mL + 20, (mT + H - mB) / 2);
  }
  ctx.font = FONT_BASE;
  for (const t of niceTicks(xMin, xMax, 7)) {
    ctx.fillText(fmt(t, 3), px(t) - 10, H - mB + 16);
  }
  for (const t of niceTicks(b.alt_min_used, b.alt_max_used, 7)) {
    ctx.fillText(`${Math.round(t)}`, 6, py(t) + 3);
  }
  ctx.fillText("Mach", W / 2 - 14, H - 8);
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
  const legend = el("div", { class: "legend" },
    el("span", {}, el("span", { class: "chip", style: `background:${C.ok}` }), "설계 영역 (합성)"),
    ...[...sources].map((s) => el("span", {},
      el("span", { class: "chip", style: `background:${boundColor(s)}` }), boundLabel(s))),
    el("span", {}, el("span", { class: "chip", style: `border:1.4px solid ${C.schedPt}; background:transparent` }),
      "게인 스케줄 격자점 (coarse [기본값] — trimmable 미판정)"),
  );
  const kids = [el("div", { class: "scroll-x" }, mhEnvelopeCanvas(lastMh, cells)), legend];
  if (cells && cells.length) {
    const s = scanSummary(cells);
    kids.push(el("div", { class: "legend" },
      el("span", {}, el("span", { class: "chip", style: `background:${kindColor("ok")}` }),
        `${kindLabel("ok")} ${s.ok}/${s.total}`),
      ...s.byKind.map(({ kind, n }) => el("span", {},
        el("span", { class: "chip", style: `background:${kindColor(kind)}` }),
        `${kindLabel(kind)} ${n}건`)),
    ));
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
    ctx.fillText(label, px(v) + 3, mT + 12);
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
