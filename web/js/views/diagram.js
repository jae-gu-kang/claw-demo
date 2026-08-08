/** 고정 구조 신호흐름 다이어그램 (02 §4 (a)) — 시뮬링크 다이어그램의 '보기' 대체.

자유 블록 배선 에디터는 [확정] 스코프 제외 — 아키텍처가 고정(01 §3)이므로
편집은 파라미터(게인·옵션·모드 테이블)로만 하고, 구조는 이 다이어그램이
정본을 표시한다. 블록 기하·편집 경로는 lib/blocks.js가 정본 (허브 UI와 공유),
배선(화살표)은 블록 기하에서 계산 — 데이터와 그림이 어긋날 수 없다.
*/

import { BLOCKS, DIAGRAM_H, DIAGRAM_W, hitBlock } from "../lib/blocks.js";
import { makeCanvas } from "./plots.js";

const BOX_FILL = "#f2f6fd";
const BOX_FILL_SEL = "#d7e5fc";
const BOX_EDGE = "#1a6feb";
const TXT = "#1c2430";
const SUB = "#66707e";

const B = Object.fromEntries(BLOCKS.map((b) => [b.id, b]));
const right = (b) => b.x + b.w;
const cy = (b) => b.y + b.h / 2;

function box(ctx, b, selected) {
  ctx.fillStyle = selected ? BOX_FILL_SEL : BOX_FILL;
  ctx.strokeStyle = BOX_EDGE;
  ctx.lineWidth = selected ? 2.4 : 1.2;
  ctx.fillRect(b.x, b.y, b.w, b.h);
  ctx.strokeRect(b.x, b.y, b.w, b.h);
  ctx.fillStyle = TXT;
  ctx.fillText(b.title, b.x + b.w / 2 - ctx.measureText(b.title).width / 2, b.y + 18);
  if (b.sub) {
    ctx.fillStyle = SUB;
    ctx.fillText(b.sub, b.x + b.w / 2 - ctx.measureText(b.sub).width / 2, b.y + 34);
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

/** 주 경로 연쇄 (id, 라벨) — M7 조립 순서. 화살표는 인접 블록 기하로 계산. */
const CHAIN = [
  ["guidance", "명령"], ["autopilot", "θ·φ·thr"], ["limiter", "θ_cmd′"],
  ["scas", "δe·δa·δr"], ["mixer", "명령"], ["actuator", ""], ["plant", null],
];

/**
 * 옵션:
 * - selectedId: 강조 표시할 블록 id
 * - onBlockClick(block): 클릭 핸들러 — 지정 시 커서·클릭 배선 (허브 모드)
 */
export function clawDiagramCanvas({ selectedId = null, onBlockClick = null } = {}) {
  const { canvas, ctx } = makeCanvas(DIAGRAM_W, DIAGRAM_H);

  // 게인 스케줄 (상단) → AP·SCAS 주입 — 목적 블록 상단 중앙으로 (리뷰 S1:
  // 고정 x가 α 리미터 위에 꽂혀 잘못된 구조 인상을 주던 결함 수정)
  const sched = B.schedule;
  box(ctx, sched, selectedId === "schedule");
  const apx = B.autopilot.x + B.autopilot.w / 2;
  ctx.strokeStyle = "#66707e";
  ctx.lineWidth = 1.2;
  ctx.beginPath();
  ctx.moveTo(sched.x + 20, sched.y + sched.h);
  ctx.lineTo(sched.x + 20, 86);
  ctx.lineTo(apx, 86);
  ctx.stroke();
  arrow(ctx, apx, 86, apx, B.autopilot.y, "");
  const scx = B.scas.x + B.scas.w / 2;
  arrow(ctx, scx, sched.y + sched.h, scx, B.scas.y, "");

  // 주 신호 경로 (좌→우)
  for (let i = 0; i < CHAIN.length; i += 1) {
    const b = B[CHAIN[i][0]];
    box(ctx, b, selectedId === b.id);
    if (i + 1 < CHAIN.length) {
      const nb = B[CHAIN[i + 1][0]];
      arrow(ctx, right(b), cy(b), nb.x, cy(nb), CHAIN[i][1]);
    }
  }

  // 항법 피드백 (하단) — 법칙은 NavOutput만 소비 (참값 차단 계약)
  const nav = B.nav;
  box(ctx, nav, selectedId === "nav");
  arrow(ctx, B.plant.x + B.plant.w / 2, B.plant.y + B.plant.h, right(nav), cy(nav) + 4,
    "VehicleState (참값)", 12);
  ctx.strokeStyle = "#66707e";
  ctx.beginPath();
  ctx.moveTo(nav.x, cy(nav) + 4);
  ctx.lineTo(70, cy(nav) + 4);
  ctx.stroke();
  arrow(ctx, 70, cy(nav) + 4, 70, B.guidance.y + B.guidance.h, "", 0);
  ctx.fillStyle = SUB;
  ctx.fillText("NavOutput — 법칙·유도·스케줄은 이것만 소비 (참값 차단 계약, 03 §4)", 90, 266);

  ctx.fillStyle = SUB;
  ctx.fillText("제어 100 Hz (틱 사이 ZOH) · 플랜트 dt 10 ms RK4 · 항법 자체 갱신주기/지연 — 멀티레이트 [확정 02 §6]", 15, DIAGRAM_H - 12);
  ctx.fillStyle = TXT;
  ctx.fillText("고정 아키텍처 (01 §3) — 자유 배선 없음 [확정 02 §4], 편집은 파라미터·게인·모드 테이블로", 15, 16);

  if (onBlockClick) {
    // CSS 축소(max-width) 대비 — 표시 크기 → 논리 좌표 보정
    const toLogical = (ev) => {
      const r = canvas.getBoundingClientRect();
      return [(ev.clientX - r.left) * (DIAGRAM_W / r.width),
        (ev.clientY - r.top) * (DIAGRAM_H / r.height)];
    };
    canvas.addEventListener("mousemove", (ev) => {
      canvas.style.cursor = hitBlock(...toLogical(ev)) ? "pointer" : "default";
    });
    canvas.addEventListener("click", (ev) => {
      const b = hitBlock(...toLogical(ev));
      if (b) onBlockClick(b);
    });
  }
  return canvas;
}
