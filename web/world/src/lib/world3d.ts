/** `web/js/lib/world3d.js`의 타입 있는 얼굴 — `attitude.ts`와 같은 이유의 어댑터.
 *
 * **결측 규약이 이 모듈의 요점이다.** 원본이 null을 내는 자리를 여기서 `| null`로
 * 드러내지 않으면, 호출부가 `!`로 눌러 버리고 결측이 0으로 흘러든다.
 */

import {
  attitudeAt as rawAttitudeAt, originsAgree as rawOriginsAgree, sampleAt as rawSampleAt,
  sceneExtent as rawSceneExtent, trackPoints as rawTrackPoints, vehicleModelPlan as rawVehicleModelPlan,
  velocityAt as rawVelocityAt,
} from "../../../js/lib/world3d.js";
import type { Vec3 } from "./attitude.ts";
import type { ResultOrigin, Signals } from "../core/types.ts";
import type { PackOrigin } from "./terrainpack.ts";

const v3 = (v: unknown): Vec3 | null => {
  if (!Array.isArray(v) || v.length !== 3) return null;
  const [a, b, c] = v as (number | undefined)[];
  return (typeof a === "number" && typeof b === "number" && typeof c === "number")
    ? [a, b, c] : null;
};

/** 궤적 기하 — `breaks`는 결측 표본의 인덱스. 결측 자리는 NaN이다(0이 아니라). */
export function trackPoints(signals: Signals, n: number): { points: Float32Array; breaks: number[] } {
  return rawTrackPoints(signals, n) as { points: Float32Array; breaks: number[] };
}

/** 표본 i의 NED 위치. 하나라도 결측이면 **null**. */
export function sampleAt(signals: Signals, i: number): Vec3 | null {
  return v3(rawSampleAt(signals, i));
}

/** 표본 i의 자세 (φ, θ, ψ) [rad]. 하나라도 결측이면 **null**. */
export function attitudeAt(signals: Signals, i: number): Vec3 | null {
  return v3(rawAttitudeAt(signals, i));
}

/** 후방차분 NED 속도 [m/s]. 양 끝이 성하고 dt > 0일 때만. */
export function velocityAt(t: readonly number[], signals: Signals, i: number): Vec3 | null {
  return v3(rawVelocityAt(t, signals, i));
}

/** 기준면 한 변 [m]. */
export function sceneExtent(signals: Signals, fallback = 4000): number {
  return rawSceneExtent(signals, fallback) as number;
}

/** 지형 팩과 결과가 **같은 원점에 등록돼 있는가** — 아니면 겹쳐 그릴 수 없다. */
export function originsAgree(
  packOrigin: PackOrigin | null | undefined,
  resultOrigin: ResultOrigin | null | undefined,
): { ok: boolean; reason: string | null } {
  return rawOriginsAgree(packOrigin, resultOrigin) as { ok: boolean; reason: string | null };
}

/** 기체 모델 계획 — 읽을 GLB(없으면 null = 궤적만)·그 사유·출처 캡션. 판정은 원본(`vehicleModelPlan`)이 정본. */
export interface VehiclePlan { model: string | null; note: string | null; caption: string | null }

/** 이 런의 기체 적용 문서(형상 변형 반영) + 자산 목록 → 기체 모델 계획. */
export function vehicleModelPlan(
  doc: unknown,
  manifest: { models: { name: string }[]; models_reason: string | null } | null,
  opts: { label?: string; error?: string | null } = {},
): VehiclePlan {
  return rawVehicleModelPlan(doc, manifest, opts) as VehiclePlan;
}
