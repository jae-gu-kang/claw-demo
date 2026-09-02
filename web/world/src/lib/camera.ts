/** `web/js/lib/camera.js`의 타입 있는 얼굴. 반환은 전부 **NED**다. */

import {
  CAM_MODES as rawModes, FOV_Y as rawFovY, JUMP_RESET_SAMPLES as rawJump,
  ROT_PER_PX as rawRotPerPx,
  attitudeCamera as rawAttitude, chaseCamera as rawChase, onboardCamera as rawOnboard,
  orbitCamera as rawOrbit, rotateBy as rawRotateBy,
  shouldResetSmoothing as rawShouldReset, travelDirection as rawTravel,
} from "../../../js/lib/camera.js";
import type { Quat, Vec3 } from "./attitude.ts";

export type CamMode = "chase" | "orbit" | "onboard" | "attitude";
export const CAM_MODES = rawModes as readonly CamMode[];
export const FOV_Y = rawFovY as number;
export const ROT_PER_PX = rawRotPerPx as number;
export const JUMP_RESET_SAMPLES = rawJump as number;

export interface CameraPose { eye: Vec3; target: Vec3; up: Vec3; fovY: number }
export interface OrbitView { az: number; el: number }

const pose = (o: unknown): CameraPose => o as CameraPose;

export function chaseCamera(args: {
  pos: Vec3; vel: Vec3 | null; q: Quat | null; prevEye: Vec3 | null;
  dtWall?: number; dist: number; height: number; tau?: number;
  groundD?: number | null; minClearance?: number;
}): CameraPose {
  return pose(rawChase(args));
}

export function orbitCamera(args: {
  pivot: Vec3; az: number; el: number; dist: number;
  groundD?: number | null; minClearance?: number;
}): CameraPose {
  return pose(rawOrbit(args));
}

export function onboardCamera(args: {
  pos: Vec3; q: Quat; offsetFrd?: Vec3; lookAhead?: number;
}): CameraPose {
  return pose(rawOnboard(args));
}

export function attitudeCamera(args: {
  pos: Vec3; az?: number; el?: number; dist: number; groundD?: number | null;
}): CameraPose {
  return pose(rawAttitude(args));
}

/** 드래그 → 새 궤도 시점. 원본이 클램프까지 한다. */
export function rotateBy(view: OrbitView, dxPx: number, dyPx: number): OrbitView {
  return rawRotateBy(view, dxPx, dyPx) as OrbitView;
}

/** 커서가 크게 뛰었나 — 뛰었으면 체이스 지연을 리셋한다. */
export function shouldResetSmoothing(prevIdx: number | null, idx: number): boolean {
  return rawShouldReset(prevIdx, idx) as boolean;
}

/** 진행 방향 — 속도가 거의 0이면 기수로, 자세도 없으면 북으로 물러선다. */
export function travelDirection(vel: Vec3 | null, q: Quat | null): Vec3 {
  return rawTravel(vel, q) as Vec3;
}
