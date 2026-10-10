/** 지형 조각 — 한 장의 삼각형 목록을 격자 블록으로 나눈다 (렌더러 무관).
 *
 * ## 왜 나누나
 *
 * 지형은 장마다 메시가 하나였다. three는 메시 단위로 시야 판정을 하므로 60 km 장 하나는 **언제나**
 * 시야 안이고, 분할 프러스텀의 두 패스(원거리·근거리)가 매번 장 전체의 삼각형을 다 처리했다. 외곽을
 * 2배로 세분하자(core/refine.ts) 삼각형이 1.24M → 2.55M이 되어 추적·1인칭 시점이 60 fps에서 55 fps로
 * 떨어졌다(실측). 조각으로 나누면 카메라 뒤 조각은 원거리 패스에서, 2 km 밖 조각은 근거리 패스에서
 * 통째로 빠진다.
 *
 * 정점 버퍼는 조각끼리 **공유한다** — 나누는 것은 인덱스뿐이다(SceneHost.setTerrain). 그래서 정점이
 * 조각 경계에서 갈라지지 않고 틈도 생기지 않는다.
 *
 * ## 조각 크기
 *
 * 너무 작으면 그리기 호출이 늘고, 너무 크면 근거리 패스가 못 거른다. 촘촘한 장은 약 3 km(카메라가 주로
 * 그 안에 있다 — 근거리 2 km를 거를 만큼), 외곽은 약 7.5 km(멀리서만 보인다).
 */

/** 장의 격자 간격 [m] → 조각 한 변의 칸 수. */
export function chunkQuads(stepM: number): number {
  const target = stepM <= 35 ? 3000 : 7500;
  return Math.max(16, Math.round(target / stepM));
}

export interface TerrainChunk {
  /** 조각 블록 위치 (행, 열) */
  br: number;
  bc: number;
  indices: Uint32Array;
}

/** `buildTerrainMesh`의 인덱스(칸마다 삼각형 둘 = 6개, 첫 인덱스가 칸의 왼아래 꼭짓점 r·cols + c)를
 *  블록별로 나눈다. 빈 블록은 내지 않는다. */
export function chunkIndices(
  indices: ArrayLike<number>, cols: number, quadsPerChunk: number,
): TerrainChunk[] {
  if (indices.length % 6 !== 0) throw new Error(`인덱스가 칸 단위(6)가 아니다: ${indices.length}`);
  const buckets = new Map<number, number[]>();
  const keyOf = (br: number, bc: number) => br * 100003 + bc;
  for (let k = 0; k < indices.length; k += 6) {
    const a = indices[k]!;
    const r = Math.floor(a / cols);
    const c = a - r * cols;
    const key = keyOf(Math.floor(r / quadsPerChunk), Math.floor(c / quadsPerChunk));
    let list = buckets.get(key);
    if (!list) { list = []; buckets.set(key, list); }
    for (let t = 0; t < 6; t++) list.push(indices[k + t]!);
  }
  const out: TerrainChunk[] = [];
  for (const [key, list] of buckets) {
    out.push({ br: Math.floor(key / 100003), bc: key % 100003, indices: Uint32Array.from(list) });
  }
  out.sort((x, y) => x.br - y.br || x.bc - y.bc);
  return out;
}
