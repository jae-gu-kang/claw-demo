/** 고정 구조 신호흐름 다이어그램 (02 §4 (a)) — 시뮬링크 다이어그램의 '보기' 대체.

자유 블록 배선 에디터는 [확정] 스코프 제외 — 아키텍처가 고정(01 §3)이므로
편집은 파라미터(게인·옵션·모드 테이블)로만 하고, 구조는 이 다이어그램이
정본을 표시한다. 그리는 내용은 M7 FlightControlLaw 조립 순서와 1:1.
*/

import { makeCanvas } from "./plots.js";

const BOX_FILL = "#f2f6fd";
const BOX_EDGE = "#1a6feb";
const TXT = "#1c2430";
const SUB = "#66707e";

function box(ctx, x, y, w, h, title, sub) {
  ctx.fillStyle = BOX_FILL;
  ctx.strokeStyle = BOX_EDGE;
  ctx.lineWidth = 1.2;
  ctx.fillRect(x, y, w, h);
  ctx.strokeRect(x, y, w, h);
  ctx.fillStyle = TXT;
  ctx.fillText(title, x + w / 2 - ctx.measureText(title).width / 2, y + 18);
  if (sub) {
    ctx.fillStyle = SUB;
    ctx.fillText(sub, x + w / 2 - ctx.measureText(sub).width / 2, y + 34);
  }
}

function arrow(ctx, x1, y1, x2, y2, label, labelDy = -5) {
  ctx.strokeStyle = "#66707e";
  ctx.lineWidth = 1.2;
  ctx.beginPath();
  ctx.moveTo(x1, y1);
  ctx.lineTo(x2, y2);
  ctx.stroke();
  const ang = Math.atan2(y2 - y1, x2 - x1);
  ctx.beginPath();
  ctx.moveTo(x2, y2);
  ctx.lineTo(x2 - 7 * Math.cos(ang - 0.4), y2 - 7 * Math.sin(ang - 0.4));
  ctx.lineTo(x2 - 7 * Math.cos(ang + 0.4), y2 - 7 * Math.sin(ang + 0.4));
  ctx.fillStyle = "#66707e";
  ctx.fill();
  if (label) {
    ctx.fillStyle = SUB;
    ctx.fillText(label, (x1 + x2) / 2 - ctx.measureText(label).width / 2,
      (y1 + y2) / 2 + labelDy);
  }
}

export function clawDiagramCanvas() {
  const W = 1060;
  const H = 330;
  const { canvas, ctx } = makeCanvas(W, H);
  const Y = 110; // 주 신호 경로 행
  const BH = 52;

  // 게인 스케줄 (상단) — AP·SCAS 게인 주입
  box(ctx, 330, 18, 260, 44, "게인 스케줄 (M7)", "mach·alt·fuel → kp·ki·k_rate");
  arrow(ctx, 400, 62, 400, Y, "");
  arrow(ctx, 540, 62, 540, Y, "");

  // 주 신호 경로 (좌→우) — FlightControlLaw 조립 순서 그대로
  box(ctx, 15, Y, 105, BH, "유도 (M8)", "모드 테이블·LOS");
  arrow(ctx, 120, Y + BH / 2, 158, Y + BH / 2, "명령");
  box(ctx, 158, Y, 128, BH, "오토파일럿", "속도·고도·헤딩 PI");
  arrow(ctx, 286, Y + BH / 2, 324, Y + BH / 2, "θ·φ·thr");
  box(ctx, 324, Y, 118, BH, "α 리미터", "θ_cmd ≤ f(α_stall)");
  arrow(ctx, 442, Y + BH / 2, 478, Y + BH / 2, "θ_cmd′");
  box(ctx, 478, Y, 122, BH, "SCAS", "자세 PI + 레이트");
  arrow(ctx, 600, Y + BH / 2, 636, Y + BH / 2, "δe·δa·δr");
  box(ctx, 636, Y, 122, BH, "믹서", "엘레본4·차동추력");
  arrow(ctx, 758, Y + BH / 2, 794, Y + BH / 2, "명령");
  box(ctx, 794, Y, 116, BH, "작동기", "2차계 rate≥10");
  arrow(ctx, 910, Y + BH / 2, 942, Y + BH / 2, "");
  box(ctx, 942, Y, 103, BH, "플랜트", "6DOF RK4");

  // 항법 피드백 (하단) — 법칙은 NavOutput만 소비 (참값 차단 계약)
  box(ctx, 430, 230, 190, 44, "항법 (M6 오차 모델)", "잡음·바이어스·지연·주기");
  arrow(ctx, 993, Y + BH, 620, 252, "VehicleState (참값)", 12);
  ctx.strokeStyle = "#66707e";
  ctx.beginPath();
  ctx.moveTo(430, 252);
  ctx.lineTo(70, 252);
  ctx.stroke();
  arrow(ctx, 70, 252, 70, Y + BH, "", 0);
  ctx.fillStyle = SUB;
  ctx.fillText("NavOutput — 법칙·유도·스케줄은 이것만 소비 (참값 차단 계약, 03 §4)", 90, 266);

  ctx.fillStyle = SUB;
  ctx.fillText("제어 100 Hz (틱 사이 ZOH) · 플랜트 dt 10 ms RK4 · 항법 자체 갱신주기/지연 — 멀티레이트 [확정 02 §6]", 15, H - 12);
  ctx.fillStyle = TXT;
  ctx.fillText("고정 아키텍처 (01 §3) — 자유 배선 없음 [확정 02 §4], 편집은 파라미터·게인·모드 테이블로", 15, 16);
  return canvas;
}
