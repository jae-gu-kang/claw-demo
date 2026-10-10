/** 활주로 그리기 — 폭을 알고 칠할 땅(지형)이 있으면 지면 셰이더가 포장면·도색을 칠하고, 땅이 없으면 선으로,
 * 폭을 모르면 중심선 하나만 긋는다. 좌표는 NED이고 활주로는 **원점에서 heading 방향 length 구간**이다
 * (lib/site.js·lib/replay.js가 전제하는 규약).
 *
 * ## 폭은 어디서
 *
 * 결과(`meta.runway`)에는 폭이 없다. 그 런의 활주로가 시험장 제원의 활주로와 같을 때만 제원 폭을 쓴다 —
 * `siteRunwayWidth`(web/js/lib/replay.js)가 판정하고, 시뮬 탭 착륙 요약의 횡편차 한계가 받는 **같은 한 자리**다.
 * 여기서 폭 상수를 다시 적으면 화면의 가장자리와 판정의 가장자리가 두 수가 된다(옛 화면의 22 m 반폭이 그랬다
 * — 제원은 45 m). 다른 활주로면 폭을 지어내지 않는다: 중심선만 그리고 사유를 캡션에 낸다.
 *
 * ## 도색이 선을 대신한다 — 칠할 땅이 있을 때만
 *
 * 폭을 알면 시단 줄무늬·번호·중심선 점선·측면 표지·조준점(과주로가 있으면 노란 갈매기표)을 지면 셰이더가
 * 칠한다(shaders/runway.ts — 실사·게임 지형 둘 다) — 시험장 측정 기록이 영상에서 피아노 건반·중심선·측면 표지를 확인했다
 * (data/geo/goheung-runway.json). 배치와 치수는 ICAO 부속서 14의 표준이고 실제 도색을 잰 것은 아니다. 그
 * 자리에 흰 선을 겹쳐 그으면 1픽셀 선이 도색 위에 떠 같은 것을 두 번 말하므로 선은 긋지 않는다. 다만 도색은
 * **지형 재질에만** 있다 — 지형을 못 얹은 화면(팩이 없거나 원점이 다름)에서 선까지 빼면 활주로가 통째로 사라진다
 * (v1.92 리뷰 지적). 그래서 호출측이 칠할 땅이 있다고 말할 때(`paint`)만 도색이고, 기본은 선이다.
 * 과주로는 폭과 같은 제원 대조(`siteRunwayWidth`)가 함께 준다 — 따로 읽으면 다른 활주로에도 붙는다.
 *
 * ## 번호는 자방위에서
 *
 * 활주로 번호는 자방위 ÷ 10의 반올림이다(0은 36). 결과에는 진방위만 있고 자편각은 싣지 않는다 — 대신
 * 한반도 자편각 범위의 양 끝에서 셈해 **같을 때만** 칠한다. 고흥 진방위 3.26°는 서편 1.7~11.7° 어디서든 자방위가
 * 5~15°라 01이다. 갈리면 번호를 지어내지 않는다.
 *
 * ## 왜 선분마다 따로인가
 *
 * `SceneHost.setPaths`는 한 목록의 점을 **꺾은선**으로 잇는다. 선분 여럿을 한 목록에 이어 담으면 선분 끝에서
 * 다음 선분 시작으로 활주로를 가로지르는 대각선이 그어진다(종전 그리기).
 */

import type { RunwayWidth } from "../lib/replay.ts";
import { RUNWAY_FLOOR } from "./runwayfloor.ts";

/** 흰 선을 활주로 표고보다 이만큼 띄운다 [m] — 표시 값. 지형은 활주로 둘레를 정확히 활주로 표고로 펴므로
 *  (core/runwayfloor.ts) 같은 높이에 그으면 선과 면이 깊이를 다퉈 깜빡이며 끊긴다. 근거리 패스의 깊이 눈금이
 *  2 km에서 약 0.08 m라(SceneHost 머리말) 그보다 크게, 눈에는 안 띄게 잡았다. */
export const RUNWAY_LINE_LIFT_M = 0.15;

/** 한반도 자편각의 범위 [°, 동이 +] — 서편이고 크기는 대략 6~10°다. 번호는 이 범위 양 끝에서 같을 때만 칠한다
 *  (머리말 「번호는 자방위에서」). 정확한 값은 지자기 모델의 몫인데, 이 범위로 번호가 정해지면 그것이 필요 없다. */
export const DECLINATION_RANGE_DEG = [-10, -6] as const;

/** 활주로 번호 [시단 쪽, 맞은편] — 진방위 [rad]에서. 자편각 범위의 양 끝에서 갈리면 null. */
export function runwayDesignation(headingRad: number): [number, number] | null {
  if (!Number.isFinite(headingRad)) return null;
  const at = (declDeg: number): number => {
    const mag = ((((headingRad * 180) / Math.PI - declDeg) % 360) + 360) % 360;
    const n = Math.round(mag / 10) % 36;
    return n === 0 ? 36 : n;
  };
  const near = at(DECLINATION_RANGE_DEG[0]);
  if (near !== at(DECLINATION_RANGE_DEG[1])) return null;
  return [near, ((near + 17) % 36) + 1];
}

/** 활주로 포장면 — 지면 셰이더가 아스팔트·도색·비행장 풀밭을 칠할 자리(shaders/runway.ts). NED 원점에서
 *  heading 방향 length 구간, 폭 width. **폭을 알고 칠할 땅이 있을 때만** 있다 — 폭을 모르면 포장면을 지어내지 않고,
 *  땅이 없으면 선으로 긋는다(`runwayDrawing`). */
export interface RunwaySurface {
  /** 활주로 축 방위 [rad] (북에서 동으로) */ heading: number;
  /** [m] */ length: number;
  /** [m] — 제원 폭 */ width: number;
  /** 양 끝 시단 너머 과주로 [m] — 시험장 제원(모르면 0) */ overrun: number;
  /** 활주로 번호 [시단 쪽, 맞은편] — 정해지지 않으면 null(번호를 칠하지 않는다) */
  designation: [number, number] | null;
}

export interface RunwayDrawing {
  /** 두 점짜리 선분들 — 각각 [n0, e0, d0, n1, e1, d1]. 폭을 모르면 중심선 하나, 칠할 땅이 없으면 중심선·시단·종단·
   *  양 가장자리 다섯이고, 도색할 때는 비어 있다(도색이 같은 자리를 그린다). */
  segments: Float32Array[];
  /** 포장면 — 폭을 알고 칠할 땅이 있을 때만. 아니면 null. */
  surface: RunwaySurface | null;
  /** 캡션 한 줄 — 무엇을 그렸고 폭이 어디서 왔는지(또는 왜 모르는지). */
  note: string;
}

const num = (v: unknown): number | null =>
  typeof v === "number" && Number.isFinite(v) ? v : null;

const fmtM = (v: number) => String(Number(v.toFixed(1)));

/** 결과의 활주로(`meta.runway`) + 그 폭 판정 → 그리기. 방위·길이가 없으면 null(그리지 않는다).
 *  `opts.paint` — 칠할 땅이 있다: 지형이 활주로 자리를 덮는다(scene/terrain.ts `runwayCovered`). 기본은 거짓(선으로
 *  긋는다). */
export function runwayDrawing(
  rw: unknown, width: RunwayWidth, opts: { paint?: boolean } = {},
): RunwayDrawing | null {
  const r = (rw ?? null) as { heading?: unknown; length?: unknown; elevation?: unknown } | null;
  const h = num(r?.heading);
  const L = num(r?.length);
  if (h === null || L === null) return null;
  const d = -((num(r?.elevation) ?? 0) + RUNWAY_LINE_LIFT_M);
  const [cn, ce] = [Math.cos(h), Math.sin(h)]; // 활주로 축(북·동 성분)
  const n1 = cn * L;
  const e1 = ce * L;
  const seg = (a: [number, number], b: [number, number]) => new Float32Array([a[0], a[1], d, b[0], b[1], d]);
  const center = seg([0, 0], [n1, e1]);
  if (!("width" in width)) {
    return { segments: [center], surface: null, note: `활주로는 중심선만 그립니다 — 폭을 모릅니다: ${width.error}.` };
  }
  const source = `폭 ${fmtM(width.width)} m는 ${width.source} 값입니다(결과에는 폭이 없어, 이 런의 활주로가 `
    + "제원의 활주로와 같을 때만 씁니다)";
  if (!opts.paint) {
    const half = width.width / 2;
    // 축의 오른쪽(+) 법선 — 북·동 평면에서 (−sin h, cos h)
    const [rn, re] = [-ce * half, cn * half];
    const at = (n: number, e: number, side: 1 | -1): [number, number] => [n + side * rn, e + side * re];
    return {
      segments: [
        center,
        seg(at(0, 0, -1), at(0, 0, 1)), // 시단
        seg(at(n1, e1, -1), at(n1, e1, 1)), // 종단
        seg(at(0, 0, -1), at(n1, e1, -1)), // 왼 가장자리
        seg(at(0, 0, 1), at(n1, e1, 1)), // 오른 가장자리
      ],
      surface: null,
      note: `활주로: 중심선·시단·종단·양 가장자리를 선으로 긋습니다 — ${source}. 활주로 자리에 지형이 없어 포장면과 `
        + "도색은 칠하지 않습니다.",
    };
  }
  const overrun = Math.max(num(width.overrun) ?? 0, 0);
  const designation = runwayDesignation(h);
  const two = (n: number) => String(n).padStart(2, "0");
  const marks = ["시단 줄무늬", ...(designation ? [`번호 ${two(designation[0])}/${two(designation[1])}`] : []),
    "중심선 점선", "측면 표지", "조준점"];
  return {
    segments: [],
    surface: { heading: h, length: L, width: width.width, overrun, designation },
    note: `활주로: 포장면과 도색(${marks.join("·")}${overrun > 0 ? `, 양 끝 과주로 ${fmtM(overrun)} m의 노란 갈매기표` : ""})을 `
      + `지면에 칠합니다. ${source}. 도색의 배치와 치수는 ICAO 부속서 14의 표준이고 실제 도색을 잰 것이 아닙니다`
      + (designation ? " — 번호는 진방위와 한반도 자편각 범위(서편 6~10°)로 셈했습니다." : "."),
  };
}

/** 활주로 번호 → 셰이더 자리 (시단 쪽 십·일, 맞은편 십·일) — `SceneHost.setRunwaySurface`가 그대로 싣는다. 모르면
 *  -1 넷이고 셰이더가 번호를 칠하지 않는다. */
export function designationDigits(d: [number, number] | null): [number, number, number, number] {
  return d ? [Math.floor(d[0] / 10), d[0] % 10, Math.floor(d[1] / 10), d[1] % 10] : [-1, -1, -1, -1];
}

/** 포장면 → 셰이더 유니폼 값(shaders/runway.ts 선언의 자리 순서) — `SceneHost.setRunwaySurface`가 그대로 싣는다.
 *  자리가 셰이더와 갈리면(축의 cos·sin, 번호의 십·일) 화면이 조용히 틀리므로 여기서 한 번 정하고 시험한다. */
export function runwayUniformValues(s: RunwaySurface): {
  runway: [number, number, number, number];
  area: [number, number, number, number];
  num: [number, number, number, number];
} {
  return {
    runway: [Math.cos(s.heading), Math.sin(s.heading), s.length, s.width / 2],
    // 착륙대는 펴진 바닥과 **같은 구역**이다 — 두 수가 갈리면 풀밭 끝에서 땅이 기운다(core/runwayfloor.ts)
    area: [s.overrun, RUNWAY_FLOOR.halfWidthM, RUNWAY_FLOOR.endM, 0],
    num: designationDigits(s.designation),
  };
}
