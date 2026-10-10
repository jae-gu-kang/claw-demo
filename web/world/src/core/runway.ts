/** 활주로 표시선 — 중심선·시단·종단(+ 폭을 알면 양 가장자리). 좌표는 NED이고 활주로는 **원점에서 heading
 * 방향 length 구간**이다(lib/site.js·lib/replay.js가 전제하는 규약).
 *
 * ## 폭은 어디서
 *
 * 결과(`meta.runway`)에는 폭이 없다. 그 런의 활주로가 시험장 제원의 활주로와 같을 때만 제원 폭을 쓴다 —
 * `siteRunwayWidth`(web/js/lib/replay.js)가 판정하고, 시뮬 탭 착륙 요약의 횡편차 한계가 받는 **같은 한 자리**다.
 * 여기서 폭 상수를 다시 적으면 화면의 가장자리와 판정의 가장자리가 두 수가 된다(옛 화면의 22 m 반폭이 그랬다
 * — 제원은 45 m). 다른 활주로면 폭을 지어내지 않는다: 중심선만 그리고 사유를 캡션에 낸다.
 *
 * ## 왜 선분마다 따로인가
 *
 * `SceneHost.setPaths`는 한 목록의 점을 **꺾은선**으로 잇는다. 중심선·가로선을 한 목록에 이어 담으면 중심선
 * 끝에서 시단 가로선으로, 시단 가로선에서 종단 가로선으로 활주로를 가로지르는 대각선이 그어진다(종전 그리기).
 */

import type { RunwayWidth } from "../lib/replay.ts";

/** 흰 선을 활주로 표고보다 이만큼 띄운다 [m] — 표시 값. 지형은 활주로 둘레를 정확히 활주로 표고로 펴므로
 *  (core/runwayfloor.ts) 같은 높이에 그으면 선과 면이 깊이를 다퉈 깜빡이며 끊긴다. 근거리 패스의 깊이 눈금이
 *  2 km에서 약 0.08 m라(SceneHost 머리말) 그보다 크게, 눈에는 안 띄게 잡았다. */
export const RUNWAY_LINE_LIFT_M = 0.15;

/** 활주로 포장면 — 지면 셰이더가 아스팔트와 비행장 풀밭을 칠할 자리(shaders/ground.ts). NED 원점에서
 *  heading 방향 length 구간, 폭 width. **폭을 알 때만** 있다 — 모르면 포장면을 지어내지 않는다. */
export interface RunwaySurface {
  /** 활주로 축 방위 [rad] (북에서 동으로) */ heading: number;
  /** [m] */ length: number;
  /** [m] — 제원 폭 */ width: number;
}

export interface RunwayDrawing {
  /** 두 점짜리 선분들 — 각각 [n0, e0, d0, n1, e1, d1]. 순서: 중심선, 시단, 종단, (폭을 알면) 왼·오른 가장자리. */
  segments: Float32Array[];
  /** 포장면 — 폭을 알 때만(가장자리 선과 같은 조건). 없으면 null. */
  surface: RunwaySurface | null;
  /** 캡션 한 줄 — 무엇을 그렸고 폭이 어디서 왔는지(또는 왜 모르는지). */
  note: string;
}

const num = (v: unknown): number | null =>
  typeof v === "number" && Number.isFinite(v) ? v : null;

const fmtM = (v: number) => String(Number(v.toFixed(1)));

/** 결과의 활주로(`meta.runway`) + 그 폭 판정 → 표시선. 방위·길이가 없으면 null(그리지 않는다). */
export function runwayDrawing(rw: unknown, width: RunwayWidth): RunwayDrawing | null {
  const r = (rw ?? null) as { heading?: unknown; length?: unknown; elevation?: unknown } | null;
  const h = num(r?.heading);
  const L = num(r?.length);
  if (h === null || L === null) return null;
  const d = -((num(r?.elevation) ?? 0) + RUNWAY_LINE_LIFT_M);
  const [cn, ce] = [Math.cos(h), Math.sin(h)]; // 활주로 축(북·동 성분)
  const n1 = cn * L;
  const e1 = ce * L;
  const seg = (a: [number, number], b: [number, number]) => new Float32Array([a[0], a[1], d, b[0], b[1], d]);
  const segments = [seg([0, 0], [n1, e1])];
  if (!("width" in width)) {
    return { segments, surface: null, note: `활주로는 중심선만 그립니다 — 폭을 모릅니다: ${width.error}.` };
  }
  const half = width.width / 2;
  // 축의 오른쪽(+) 법선 — 북·동 평면에서 (−sin h, cos h)
  const [rn, re] = [-ce * half, cn * half];
  const at = (n: number, e: number, side: 1 | -1): [number, number] => [n + side * rn, e + side * re];
  segments.push(
    seg(at(0, 0, -1), at(0, 0, 1)), // 시단
    seg(at(n1, e1, -1), at(n1, e1, 1)), // 종단
    seg(at(0, 0, -1), at(n1, e1, -1)), // 왼 가장자리
    seg(at(0, 0, 1), at(n1, e1, 1)), // 오른 가장자리
  );
  return {
    segments,
    surface: { heading: h, length: L, width: width.width },
    note: `활주로: 중심선·시단·종단·양 가장자리 — 폭 ${fmtM(width.width)} m는 ${width.source} 값입니다`
      + "(결과에는 폭이 없어, 이 런의 활주로가 제원의 활주로와 같을 때만 씁니다).",
  };
}
