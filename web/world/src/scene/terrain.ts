/** 지형 조립 — 팩을 읽어 **바다를 뺀** 삼각형을 만든다.
 *
 * ## 왜 바다를 빼나
 *
 * 해면을 지형 위에 겹쳐 그리면 두 면이 같은 높이(0 m)에서 만나 z-fighting이 난다.
 * 대신 **바다 칸을 지형에서 아예 빼고** 그 구멍을 해면이 채운다 — 겹치지 않으므로
 * 깊이 싸움 자체가 없어진다.
 *
 * ## 바다 판정은 표고가 아니다
 *
 * `core/seamask.ts`의 머리말에 있다 — 활주로와 먼바다가 똑같이 0 m라, 표고로 가르면
 * 활주로가 잠긴다. 경계 연결 성분으로 판정하고, **넓은 티어를 먼저 흘려** 좁은 티어의
 * 시드로 넘긴다.
 *
 * ## 티어 겹침
 *
 * 바깥 티어는 안쪽 티어 사각형 안을 그리지 않는다(`skipRect`) — 30 m와 90 m 격자가
 * 겹치면 어느 쪽이 진짜인지 화면이 말할 수 없다.
 */

import { coastalDepths } from "../core/coastdepth.ts";
import { REFINE_MIN_STEP_M, refineGrid } from "../core/refine.ts";
import {
  FLOOR_FIT_M, RUNWAY_FLOOR, floorFits, floorGrid, floorSource, type FloorSource, type RunwayFloor,
} from "../core/runwayfloor.ts";
import { CELL, buildSeaMasks, type TierMask } from "../core/seamask.ts";
import {
  buildTerrainMesh, tierRect,
  type NedRect, type TerrainMesh, type Tier, type TerrainPack,
} from "../lib/terrainpack.ts";

export interface TerrainBuild {
  meshes: TerrainMesh[];
  masks: Map<string, TierMask>;
  /** 캡션이 말할 사실 — 출처·해상도·커버리지·바다 비율. */
  notes: string[];
  /** 실제로 편 활주로 바닥 — 안 줬거나 지형과 맞지 않아 안 폈으면 null. 지면 판독이 이것을 쓴다 */
  floor: RunwayFloor | null;
}

/** 칸이 통째로 바다인가 — **덮는 범위를 전부 본다.**
 *
 * 하나라도 육지면 남긴다. 해안 칸을 남기는 쪽이 안전하다 — 빼 버리면 해면과 지형 사이에
 * 틈이 생겨 아래가 비쳐 보이는데, 남기면 해면이 그 칸 밑으로 들어갈 뿐이다.
 *
 * **네 꼭짓점만 보면 안 된다.** `stride > 1`이면 칸 하나가 원본 격자 여러 칸을 덮는데,
 * 꼭짓점 넷만 물으면 그 사이의 작은 섬이 통째로 빠져 바다에 잠긴다 — 육지를 지우는
 * 쪽이라 "해안 칸을 남긴다"는 이 함수의 방침과 정반대다. 그래서 범위를 훑는다.
 * (stride 1이면 훑는 것이 곧 꼭짓점 넷이라 비용이 같다.) */
function seaQuad(mask: TierMask): (r0: number, c0: number, r1: number, c1: number) => boolean {
  const at = (r: number, c: number) => mask.cells[r * mask.cols + c];
  return (r0, c0, r1, c1) => {
    for (let r = r0; r <= r1; r++) {
      for (let c = c0; c <= c1; c++) {
        if (at(r, c) !== CELL.SEA) return false;
      }
    }
    return true;
  };
}

/** 원자료 티어의 표고 [m] — 행 우선, 결측 NaN. */
function tierElevations(tier: Tier): Float32Array {
  const elev = new Float32Array(tier.rows * tier.cols);
  for (let i = 0; i < elev.length; i++) {
    const v = tier.raw[i]!;
    elev[i] = v === tier.nodata ? Number.NaN : tier.offset + v * tier.scale;
  }
  return elev;
}

/** 물가에 맞닿지 않은 땅 표본인가 — 활주로 바닥은 이것만 편다(core/runwayfloor.ts 「물가는 펴지 않는다」). */
function inlandLand(mask: TierMask): (i: number) => boolean {
  const { rows, cols, cells } = mask;
  return (i) => {
    if (cells[i] !== CELL.LAND) return false;
    const r = (i / cols) | 0;
    const c = i - r * cols;
    for (let dr = -1; dr <= 1; dr++) {
      for (let dc = -1; dc <= 1; dc++) {
        const rr = r + dr;
        const cc = c + dc;
        if (rr >= 0 && cc >= 0 && rr < rows && cc < cols && cells[rr * cols + cc] === CELL.SEA) return false;
      }
    }
    return true;
  };
}

/** 안쪽 티어(격자가 촘촘한 것)부터 정렬 — `skipRect`를 겹겹이 쌓는다. */
function byStepAsc(a: Tier, b: Tier): number {
  return a.step - b.step;
}

/** 사각형들을 덮는 하나의 경계 사각형. 비면 null(건너뛸 것이 없다). */
function boundingRect(rects: readonly NedRect[]): NedRect | null {
  if (rects.length === 0) return null;
  let { n0, e0, n1, e1 } = rects[0]!;
  for (const r of rects.slice(1)) {
    n0 = Math.min(n0, r.n0); e0 = Math.min(e0, r.e0);
    n1 = Math.max(n1, r.n1); e1 = Math.max(e1, r.e1);
  }
  return { n0, e0, n1, e1 };
}

/** 그릴 격자 — 원자료 티어에서 **그림 전용**으로 만든다(판독은 원자료를 쓴다 — 활주로 바닥만 같이 편다).
 *
 * 1. 바다 쪽 고리에 표시용 수심(`core/coastdepth.ts`) — 물가선이 꼭짓점 톱니가 아니라 높이를 따라 그어진다.
 * 2. 활주로 둘레를 활주로 표고로 편다(`core/runwayfloor.ts`) — 물가에 맞닿지 않은 땅 표본만. 세분 **전** 원래
 *    격자에서 펴야 마스크로 물가를 가릴 수 있고, 세분은 편 표본에서 평평하게 나온다. 펼지는 호출측이 정해 넘긴다.
 * 3. 간격이 `REFINE_MIN_STEP_M` 이상이면 3차 보간으로 2배 세분(`core/refine.ts`) — 외곽 언덕이 피라미드가 아니다.
 *
 * 세분한 티어의 바다 칸 판정은 원래 격자에서 한다 — 세분한 칸은 원래 칸 하나 안에 든다. */
export function renderTier(
  tier: Tier, mask: TierMask | undefined, refine: boolean, floor: RunwayFloor | null = null,
): { tier: Tier; skipCell: ((r0: number, c0: number, r1: number, c1: number) => boolean) | null; refined: boolean } {
  let elev = tierElevations(tier);
  if (mask) elev = coastalDepths(elev, tier.rows, tier.cols, mask.cells);
  if (floor) {
    elev = floorGrid(elev, tier.rows, tier.cols, tier.n0, tier.e0, tier.step, floor,
      mask ? inlandLand(mask) : undefined).elev;
  }
  const doRefine = refine && tier.step >= REFINE_MIN_STEP_M && tier.rows > 1 && tier.cols > 1;
  let rows = tier.rows;
  let cols = tier.cols;
  let step = tier.step;
  if (doRefine) {
    const g = refineGrid(elev, rows, cols);
    elev = g.elev; rows = g.rows; cols = g.cols; step = tier.step / 2;
  }
  const raw = new Uint16Array(rows * cols);
  for (let i = 0; i < raw.length; i++) {
    const z = elev[i]!;
    raw[i] = Number.isFinite(z)
      ? Math.min(Math.max(Math.round((z - tier.offset) / tier.scale), 0), tier.nodata - 1)
      : tier.nodata;
  }
  const out: Tier = { ...tier, rows, cols, step, raw };
  if (!mask) return { tier: out, skipCell: null, refined: doRefine };
  const sea = seaQuad(mask);
  return {
    tier: out,
    // 세분 격자 (r, c) → 원래 격자 (r/2, c/2). 세분한 칸은 원래 칸 하나 안에 들므로 내림·올림이 그 칸이다.
    skipCell: doRefine
      ? (r0, c0, r1, c1) => sea(r0 >> 1, c0 >> 1, (r1 + 1) >> 1, (c1 + 1) >> 1)
      : sea,
    refined: doRefine,
  };
}

/** 캡션의 미터 — 소수 한 자리, 끝의 0은 뗀다 */
const m1 = (v: number) => String(Number(v.toFixed(1)));

/** @param opts.strideFor 그릴 격자(세분 뒤)에 걸 솎기 — 게임 모드의 로우폴리
 *  @param opts.refine 외곽 세분 여부(기본 참). 게임 모드는 낱면이 곧 문법이라 끈다.
 *  @param opts.floor 활주로 바닥(`core/runwayfloor.ts`) — 결과의 활주로. 없거나 그 자리 지형과 맞지 않으면
 *    펴지 않고(돌려주는 `floor`가 null), 캡션이 그 사유를 말한다. */
export function buildTerrain(
  pack: TerrainPack,
  opts: { strideFor?: (t: Tier) => number; refine?: boolean; floor?: RunwayFloor | null } = {},
): TerrainBuild {
  const masks = buildSeaMasks(pack.tiers);
  const inner = [...pack.tiers].sort(byStepAsc);
  const meshes: TerrainMesh[] = [];
  const notes: string[] = [];
  let anyRefined = false;
  // 활주로 바닥 — 활주로를 덮는 가장 촘촘한 티어의 원자료로 맞는지 **한 번** 정한다. 맞으면 모든 티어에 같은 바닥,
  // 아니면 어디에도 안 편다(티어마다 정하면 겹친 자리에서 둘이 갈린다)
  const want = opts.floor ?? null;
  let floorSrc: FloorSource | null = null;
  if (want) {
    for (const tier of inner) {
      const mask = masks.get(tier.name);
      floorSrc = floorSource(tierElevations(tier), tier.rows, tier.cols, tier.n0, tier.e0, tier.step, want,
        mask ? inlandLand(mask) : undefined);
      if (floorSrc) break;
    }
  }
  const floor = want && floorFits(want, floorSrc) ? want : null;

  for (let i = 0; i < inner.length; i++) {
    const tier = inner[i]!;
    const mask = masks.get(tier.name);
    // 안쪽 티어들이 이미 덮은 범위는 그리지 않는다.
    //
    // **경계 사각형 하나로 합친다.** `buildTerrainMesh`가 사각형을 하나만 받는데,
    // 예전에는 "마지막 것"을 넘겼다. 지금 팩(core ⊂ outer)에서는 그게 맞지만 그건
    // "step이 클수록 사각형도 크다"는 **검사되지 않는 전제** 위에서만 참이다.
    // `--tier core:radius=12000,step=30 --tier mid:radius=8000,step=60 ...` 같은 구성이
    // CLI에서 그대로 받아들여지는데, 그러면 8~12 km 고리가 두 번 그려져 z-fighting이 난다.
    // 합집합의 경계 사각형은 그 전제 없이도 "이미 덮인 곳"을 덮는다.
    const skipRect = boundingRect(inner.slice(0, i).map(tierRect));
    const rt = renderTier(tier, mask, opts.refine ?? true, floor);
    anyRefined ||= rt.refined;
    meshes.push(buildTerrainMesh(rt.tier, {
      stride: opts.strideFor?.(rt.tier) ?? 1,
      skipRect,
      skipCell: rt.skipCell,
    }));

    const mesh = meshes[meshes.length - 1]!;
    if (mesh.triangles === 0) {
      // 안쪽 티어에 통째로 가려진 티어 — **격자 제원을 말하면 없는 것을 설명하게 된다.**
      notes.push(`${tier.name}: 안쪽 티어에 가려 그리지 않았습니다.`);
    } else if (mask) {
      const n = mask.rows * mask.cols;
      notes.push(
        `${tier.name}: ${tier.step} m 격자${rt.refined ? `(그릴 때 ${rt.tier.step} m로 세분)` : ""}`
        + ` · 바다 ${((100 * mask.seaCells) / n).toFixed(0)}%`
        + (mask.missingCells > 0
          ? ` · 결측 ${((100 * mask.missingCells) / n).toFixed(1)}%(구멍으로 둡니다)` : ""),
      );
    }
  }

  // 출처와 해상도는 **같은 티어에서** 읽는다. 따로 찾으면 A의 출처에 B의 해상도를
  // 붙여 말하게 되는데, 둘 다 그럴듯한 수라 화면만 봐서는 못 잡는다.
  const cited = pack.tiers.find((t) => t.source);
  if (cited?.source) {
    const res = cited.source_res_m;
    notes.push(`지형 출처: ${cited.source}${res ? ` (약 ${res.toFixed(0)} m/px)` : ""}`);
  }
  notes.push(
    "해안선은 표고 0의 **경계 연결 성분**으로 판정했습니다 — 해수면 높이의 간척지·저지대는 "
    + "육지로 남습니다. 표고만으로는 활주로와 먼바다를 가릴 수 없습니다.",
  );
  // 첨탑 정리 — 굽는 스크립트가 원자료의 물 위 첨탑을 지웠는가. **정리 전 팩이면 그렇다고 말한다**:
  // 만·해안에 선 바늘을 보고 렌더러를 의심하게 두지 않는다(scripts/terrain/build_terrain.py 머리말).
  const cl = pack.cleaning;
  const needles = cl?.per_stage?.reduce((a, b) => a + b, 0);
  if (cl == null || typeof needles !== "number") {
    notes.push("이 지형 팩은 첨탑 정리 전에 구웠습니다 — 만·해안에 바늘 같은 첨탑이 보이면 "
      + "scripts/terrain/build_terrain.py로 다시 구우십시오.");
  } else if (typeof cl.spires_px !== "number") {
    // v1.86 팩 — 물 위 바늘만 정리했다. 해안 잡음 지대의 낮은 원뿔·벽은 남아 있다(v1.88에서 잡는다)
    notes.push(`원자료 첨탑 정리(1차): 물 위에 튄 표고 ${needles}픽셀을 이웃 중앙값으로 바꿨습니다. `
      + "해안의 낮은 원뿔·벽은 이 팩에 남아 있습니다 — scripts/terrain/build_terrain.py로 다시 구우십시오.");
  } else {
    notes.push(`원자료 정리: 물 위 바늘 ${needles}픽셀, 1픽셀 벽·도랑 ${cl.walls_px ?? 0}, 평지·바다 위 좁은 기둥 `
      + `${cl.spires_px}, 그 둘레 해안 잡음 지대 ${cl.zone_px ?? 0}픽셀을 다듬었습니다 — 산지와 폭 95 m 넘는 섬은 `
      + "건드리지 않습니다.");
  }
  notes.push(
    "지형 색은 꼴(경사·표고·볼록도·해안 거리)로 판정한 지표 피복 — 논밭·숲·마을·갯벌·암반 — 의 "
    + "절차 무늬이며 영상지도가 아닙니다. 필지·지붕·나무 하나하나는 표시용이고 실제 지표 피복이 "
    + "아닙니다. 해안 둘레 바다의 낮은 턱(원자료가 얕은 바다를 거친 표고로 메운 자리)은 갯벌로 칠합니다.",
  );
  notes.push(
    "물가선은 바다 쪽 첫 세 칸을 물속으로 이어 내려(땅 높이에 비례한 1~30 m의 표시용 수심 — 실제 수심이 "
    + "아닙니다) 격자 꼭짓점의 톱니 대신 높이를 따라 그립니다."
    + (anyRefined
      ? " 외곽 격자는 그릴 때 3차 보간으로 두 배 촘촘히 해 작은 언덕을 둥글게 그립니다(원래 표본 범위를 "
        + "넘지 않게 자릅니다). 둘 다 그림에만 들어가고 지면 높이 판독은 원자료 격자를 씁니다."
      : " 이것은 그림에만 들어가고 지면 높이 판독은 원자료 격자를 씁니다."),
  );
  if (want) {
    notes.push(floor && floorSrc
      ? `활주로 바닥: 축 양옆 ${RUNWAY_FLOOR.halfWidthM} m·양 끝 너머 ${RUNWAY_FLOOR.endM} m를 활주로 표고 `
        + `${m1(floor.elevation)} m로 평평하게 그리고, 바깥 ${RUNWAY_FLOOR.blendM} m에서 원자료로 이었습니다 — `
        + `원자료는 이 구역에서 ${m1(floorSrc.min)}~${m1(floorSrc.max)} m로 출렁입니다(표고 자료의 오차 수준). 시뮬은 `
        + "땅을 활주로 표고의 평면으로 계산하므로, 펴지 않으면 멈춘 기체가 솟은 지면에 묻힙니다. 이 구역에서는 지면 "
        + "높이 판독도 편 높이를 씁니다(바다에 맞닿은 땅은 펴지 않습니다)."
      : floorSrc
        ? `활주로 바닥: 활주로 표고 ${m1(want.elevation)} m가 그 자리 지형(${m1(floorSrc.min)}~${m1(floorSrc.max)} m)에서 `
          + `${FLOOR_FIT_M} m 넘게 벗어나 펴지 않았습니다 — 펴면 없는 둑이나 구덩이를 짓게 됩니다. 시뮬은 땅을 `
          + "활주로 표고의 평면으로 계산하므로 지상의 기체가 그만큼 떠 보이거나 묻혀 보이고, 지면 높이 판독도 원자료 "
          + "그대로입니다."
        : "활주로 바닥: 지형이 활주로 자리를 덮지 않아 펴지 않았습니다.");
  }
  notes.push(
    "산그늘은 표고 격자를 태양 쪽으로 훑어 그리고(격자 30·90 m만큼 무디며, 걸음 사이의 좁은 능선은 "
    + "놓칠 수 있습니다), 골짜기의 어둑함은 반경 60·180·540 m의 상대 표고로 어림한 하늘 열림입니다 — "
    + "둘 다 표시용 근사입니다.",
  );
  return { meshes, masks, notes, floor };
}
