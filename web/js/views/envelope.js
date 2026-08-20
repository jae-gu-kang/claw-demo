/** 엔벨로프 뷰 — 교과서형 V-n 선도 (01 §3.6). 수치는 전부 엔진 vn_envelope.

영역: 정상 운용(녹) / 실속 영역(회, 상·하) / 주의 V_NO~V_D(황) / 구조 손상
제한~극한(주황) / 구조 파괴 극한 밖·V_D 밖(적). 특성 속도 V_S·V_A·V_NO·V_D
수직선. 구조 한계는 프로파일 자리표시 [기본값] — 실기체 값 아님을 명기 표시.
음의 실속 곡선은 공력 데이터 부재로 엔진 자리표시(−ratio×α_stall [기본값]) —
실데이터 아님을 명기 표시. 실속·보호선은 제한하중 교차 이후 점선(엔벨로프
밖 참고 정보). 격자는 저마하(포물선 뿌리)부터 — 교과서형 벌어지는 모양.
*/

import { api, errorText } from "../api.js";
import { clear, el, fmt } from "../dom.js";
import { linScale, niceTicks } from "../lib/plot.js";
import { makeCanvas } from "./plots.js";

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
      el("h2", {}, "V-n 선도 (flight envelope + protection)"),
      el("div", { class: "row" },
        el("label", { class: "field" }, "고도 [m]", fAlt),
        el("label", { class: "field" }, "연료 [kg]", fFuel),
        el("label", { class: "field" }, "보호 마진 [rad]", fMargin),
        el("button", { class: "primary", onclick: draw }, "그리기"),
      ),
      errBox,
    ),
    el("div", { class: "panel" }, plotBox),
  );
  if (lastBody) renderPlot(plotBox, lastBody);
  else draw();
  return root;
}

// 애플 시스템 팔레트 — 존은 옅은 틴트, 경계선은 시스템 컬러 (구조도와 동일 언어)
const C = {
  ok: "#e4f8ea", stallZone: "#f2f2f7", caution: "#fdf7e0",
  damage: "#ffefdd", failure: "#fdeaea",
  stallLine: "#ff3b30", protLine: "#34c759", limitLine: "#c93400",
  ultLine: "#d70015", speedLine: "#8e8e93", text: "#1d1d1f", sub: "#86868b",
  frame: "#d2d2d7",
};
const FONT_BASE = "11px -apple-system, 'Segoe UI', sans-serif";
const FONT_LABEL = "600 11px -apple-system, 'Segoe UI', sans-serif";
const FONT_TITLE = "600 12px -apple-system, 'Segoe UI', sans-serif";

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

function renderPlot(plotBox, body) {
  clear(plotBox).append(
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
    el("p", { class: "hint" },
      "⚠ 구조 한계(±제한/극한·V_NO·V_D)는 데모 프로파일 자리표시 [기본값 — 실기체 값 아님, ",
      "01 §3.6]: 구조팀 정본 확보 시 프로파일 교체. 음의 실속 곡선도 자리표시 ",
      `(−${fmt(body.neg_alpha_ratio ?? 0.6, 3)}×α_stall 가정 [기본값]) — 공력 정본 확보 시 교체.`),
  );
}
