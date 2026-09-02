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

export function buildTerrain(pack: TerrainPack, strideFor?: (t: Tier) => number): TerrainBuild {
  const masks = buildSeaMasks(pack.tiers);
  const inner = [...pack.tiers].sort(byStepAsc);
  const meshes: TerrainMesh[] = [];
  const notes: string[] = [];

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
    meshes.push(buildTerrainMesh(tier, {
      stride: strideFor?.(tier) ?? 1,
      skipRect,
      skipCell: mask ? seaQuad(mask) : null,
    }));

    const mesh = meshes[meshes.length - 1]!;
    if (mesh.triangles === 0) {
      // 안쪽 티어에 통째로 가려진 티어 — **격자 제원을 말하면 없는 것을 설명하게 된다.**
      notes.push(`${tier.name}: 안쪽 티어에 가려 그리지 않았습니다.`);
    } else if (mask) {
      const n = mask.rows * mask.cols;
      notes.push(
        `${tier.name}: ${tier.step} m 격자 · 바다 ${((100 * mask.seaCells) / n).toFixed(0)}%`
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
  notes.push(
    "지형 색은 고도 램프 + 절차 무늬(식생·암반·명암 변조)이며 영상지도가 아닙니다 — "
    + "무늬는 표시용이고 실제 지표 피복이 아닙니다.",
  );
  return { meshes, masks, notes };
}
