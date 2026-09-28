/** `web/js/lib/replay.js`의 타입 있는 얼굴 (이 앱이 쓰는 부분만). */

import {
  modeSpans as rawModeSpans, profileDocPath as rawProfileDocPath, refLabel as rawRefLabel,
  runProfileRef as rawRunProfileRef, siteRunwayWidth as rawSiteRunwayWidth, strideFor as rawStrideFor,
} from "../../../js/lib/replay.js";

/** 목표 표본 수(기본 1500)에 맞춘 다운샘플 간격. */
export function strideFor(nTotal: number, target = 1500): number {
  return rawStrideFor(nTotal, target) as number;
}

/** 연속 구간 — `i1`은 **배타적**이다(원본 규약). 필드 이름을 여기서 바꾸지 않는다:
 *  `views/sim.js`가 같은 함수를 쓰므로, 두 화면이 같은 어휘를 써야 대조가 된다. */
export interface ModeSpan { mode: string; i0: number; i1: number }

/** 모드 이름 시계열 → 구간. 화면이 "지금 어느 단계인가"를 말한다. */
export function modeSpans(modes: readonly string[]): ModeSpan[] {
  return rawModeSpans(modes) as ModeSpan[];
}

/** 이 런을 난 기체의 문서 좌표 — 결과 `meta.profile`(서버 profile_echo). 표시 모델을 그 문서에서 읽는다. */
export interface RunProfileRef { id: string; variant: string | null; revision: number | null; name: string }

/** 결과 meta → 문서 좌표. 기록이 없거나 깨졌으면 **null**(지금 고른 기체로 눙치지 않는다). */
export function runProfileRef(meta: unknown): RunProfileRef | null {
  return (rawRunProfileRef(meta) as RunProfileRef | null) ?? null;
}

/** 그 문서의 API 경로 — 리비전을 알면 그 리비전. */
export function profileDocPath(ref: RunProfileRef): string {
  return rawProfileDocPath(ref) as string;
}

/** 캡션용 기체 이름표 — "이름 / 형상 변형 · r리비전". */
export function refLabel(ref: RunProfileRef | null): string {
  return rawRefLabel(ref) as string;
}

/** 활주로 폭 — 제원에서 받았으면 {width, source}, 못 쓰면 사유 {error}. */
export type RunwayWidth = { width: number; source: string } | { error: string };

/** 그 런의 활주로 폭을 시험장 제원(lib/site.js GOHEUNG)에서 — 시뮬 탭 착륙 요약의 횡편차 판정이 폭을 받는 **같은
 *  한 자리**다. 결과(meta.runway)에는 폭이 없고, 그 런의 활주로가 제원의 활주로와 같을 때만 폭이 선다. */
export function siteRunwayWidth(runway: unknown): RunwayWidth {
  return rawSiteRunwayWidth(runway) as RunwayWidth;
}
