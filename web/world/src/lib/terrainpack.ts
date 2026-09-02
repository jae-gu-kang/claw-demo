/** `web/js/lib/terrainpack.js`의 타입 있는 얼굴 — `attitude.ts`와 같은 이유의 어댑터.
 *
 * 파서·메시 생성은 그쪽이 정본이고 `terrainpack.test.js`가 시험한다. 여기서는 좁히기만 한다.
 */

import {
  buildTerrainMesh as rawBuild,
  elevationAt as rawElevationAt,
  parseTerrainPack as rawParse,
  tierRect as rawTierRect,
} from "../../../js/lib/terrainpack.js";
import type { MaskTier } from "../core/seamask.ts";

/** 팩 헤더의 원점 — 키가 `lat_deg`/`lon_deg`다(결과 쪽은 `lat`/`lon`).
 *  통일하지 않는 이유는 `world3d.originsAgree`의 주석에 있다 — 이름이 달라야
 *  우연한 일치로 다른 곳의 지형을 얹는 일이 안 생긴다. */
export interface PackOrigin {
  lat_deg: number;
  lon_deg: number;
  h_ref?: number;
  datum?: string;
}

/** 파싱된 티어 — 마스크가 쓰는 필드에 표시용 메타가 더 붙는다. */
export interface Tier extends MaskTier {
  coverage?: number;
  source?: string;
  source_res_m?: number;
  sea_level_frac?: number;
  elev_min?: number;
  elev_max?: number;
}

export interface TerrainPack {
  origin: PackOrigin;
  tiers: Tier[];
}

export interface NedRect { n0: number; e0: number; n1: number; e1: number }

export interface TerrainMesh {
  positions: Float32Array;
  normals: Float32Array;
  indices: Uint16Array | Uint32Array;
  rows: number;
  cols: number;
  step: number;
  triangles: number;
}

export interface BuildOptions {
  stride?: number;
  skipRect?: NedRect | null;
  /** 원본 격자 인덱스로 묻는다 — 마스크가 그 좌표계에서 판정되기 때문. */
  skipCell?: ((r0: number, c0: number, r1: number, c1: number) => boolean) | null;
}

export function parseTerrainPack(buffer: ArrayBuffer): TerrainPack {
  return rawParse(buffer) as TerrainPack;
}

export function buildTerrainMesh(tier: Tier, opts: BuildOptions = {}): TerrainMesh {
  // **옵션을 인라인 리터럴로 넘긴다.** 변수를 그대로 넘기면 TS가 초과 속성 검사도
  // 약한 타입 검사도 걸지 않아, `terrainpack.js`가 `skipCell`을 다른 이름으로 바꿔도
  // 여기가 조용히 통과한다(실측 — 이름을 바꾸고 `tsc`를 돌려 확인했다). 그러면 바다가
  // 다시 지형으로 그려지는데 화면은 그럴듯하고, 아무것도 그것을 못 잡는다.
  // 리터럴이면 그 순간 `TS2353`이 난다.
  return rawBuild(tier, {
    stride: opts.stride,
    skipRect: opts.skipRect,
    skipCell: opts.skipCell,
  }) as TerrainMesh;
}

export function tierRect(tier: Tier): NedRect {
  return rawTierRect(tier) as NedRect;
}

/** NED (n, e)의 표고 [m] — 이중선형. 네 이웃 중 하나라도 결측이거나 격자 밖이면 **null**. */
export function elevationAt(tier: Tier, n: number, e: number): number | null {
  const z = rawElevationAt(tier, n, e) as number | null;
  return typeof z === "number" && Number.isFinite(z) ? z : null;
}
