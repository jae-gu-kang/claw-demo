/** 활주로 그리기 — 폭을 알면 지면 셰이더가 포장면·도색을 칠하고, 모르면 중심선 하나만 선으로 긋는다. 좌표는
 * NED이고 활주로는 **원점에서 heading 방향 length 구간**이다(lib/site.js·lib/replay.js가 전제하는 규약).
 *
 * ## 폭은 어디서
 *
 * 결과(`meta.runway`)에는 폭이 없다. 그 런의 활주로가 시험장 제원의 활주로와 같을 때만 제원 폭을 쓴다 —
 * `siteRunwayWidth`(web/js/lib/replay.js)가 판정하고, 시뮬 탭 착륙 요약의 횡편차 한계가 받는 **같은 한 자리**다.
 * 여기서 폭 상수를 다시 적으면 화면의 가장자리와 판정의 가장자리가 두 수가 된다(옛 화면의 22 m 반폭이 그랬다
 * — 제원은 45 m). 다른 활주로면 폭을 지어내지 않는다: 중심선만 그리고 사유를 캡션에 낸다.
 *
 * ## 도색이 선을 대신한다
 *
 * 폭을 알면 시단 줄무늬·번호·중심선 점선·측면 표지·조준점(과주로가 있으면 노란 갈매기표)을 지면 셰이더가
 * 칠한다(shaders/ground.ts) — 시험장 측정 기록이 영상에서 피아노 건반·중심선·측면 표지를 확인했다
 * (data/geo/goheung-runway.json). 배치와 치수는 ICAO 부속서 14의 표준이고 실제 도색을 잰 것은 아니다. 그
 * 자리에 흰 선을 겹쳐 그으면 1픽셀 선이 도색 위에 떠 같은 것을 두 번 말하므로, 선은 폭을 모를 때의 중심선뿐이다.
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

/** 활주로 포장면 — 지면 셰이더가 아스팔트·도색·비행장 풀밭을 칠할 자리(shaders/ground.ts). NED 원점에서
 *  heading 방향 length 구간, 폭 width. **폭을 알 때만** 있다 — 모르면 포장면을 지어내지 않는다. */
export interface RunwaySurface {
  /** 활주로 축 방위 [rad] (북에서 동으로) */ heading: number;
  /** [m] */ length: number;
  /** [m] — 제원 폭 */ width: number;
  /** 양 끝 시단 너머 과주로 [m] — 시험장 제원(모르면 0) */ overrun: number;
  /** 활주로 번호 [시단 쪽, 맞은편] — 정해지지 않으면 null(번호를 칠하지 않는다) */
  designation: [number, number] | null;
}

export interface RunwayDrawing {
  /** 두 점짜리 선분들 — 각각 [n0, e0, d0, n1, e1, d1]. 폭을 모를 때의 중심선뿐이다(폭을 알면 도색이 그린다). */
  segments: Float32Array[];
  /** 포장면 — 폭을 알 때만. 없으면 null. */
  surface: RunwaySurface | null;
  /** 캡션 한 줄 — 무엇을 그렸고 폭이 어디서 왔는지(또는 왜 모르는지). */
  note: string;
}

const num = (v: unknown): number | null =>
  typeof v === "number" && Number.isFinite(v) ? v : null;

const fmtM = (v: number) => String(Number(v.toFixed(1)));

/** 결과의 활주로(`meta.runway`) + 그 폭 판정 → 그리기. 방위·길이가 없으면 null(그리지 않는다).
 *  `site.overrunM`은 시험장 제원의 과주로 — 폭을 알 때(= 그 런이 시험장 활주로를 썼을 때)만 쓴다. */
export function runwayDrawing(
  rw: unknown, width: RunwayWidth, site: { overrunM?: number } = {},
): RunwayDrawing | null {
  const r = (rw ?? null) as { heading?: unknown; length?: unknown; elevation?: unknown } | null;
  const h = num(r?.heading);
  const L = num(r?.length);
  if (h === null || L === null) return null;
  if (!("width" in width)) {
    const d = -((num(r?.elevation) ?? 0) + RUNWAY_LINE_LIFT_M);
    const center = new Float32Array([0, 0, d, Math.cos(h) * L, Math.sin(h) * L, d]);
    return { segments: [center], surface: null, note: `활주로는 중심선만 그립니다 — 폭을 모릅니다: ${width.error}.` };
  }
  const overrun = Math.max(num(site.overrunM) ?? 0, 0);
  const designation = runwayDesignation(h);
  const two = (n: number) => String(n).padStart(2, "0");
  const marks = ["시단 줄무늬", ...(designation ? [`번호 ${two(designation[0])}/${two(designation[1])}`] : []),
    "중심선 점선", "측면 표지", "조준점"];
  return {
    segments: [],
    surface: { heading: h, length: L, width: width.width, overrun, designation },
    note: `활주로: 포장면과 도색(${marks.join("·")}${overrun > 0 ? `, 양 끝 과주로 ${fmtM(overrun)} m의 노란 갈매기표` : ""})을 `
      + `지면에 칠합니다. 폭 ${fmtM(width.width)} m는 ${width.source} 값입니다(결과에는 폭이 없어, 이 런의 활주로가 `
      + "제원의 활주로와 같을 때만 씁니다). 도색의 배치와 치수는 ICAO 부속서 14의 표준이고 실제 도색을 잰 것이 아닙니다"
      + (designation ? " — 번호는 진방위와 한반도 자편각 범위(서편 6~10°)로 셈했습니다." : "."),
  };
}
