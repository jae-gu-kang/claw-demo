/** 지형 팩 파서 + 메시 생성 — `claw-terrain v1` (DOM 무접촉, 테스트 대상).

scripts/terrain/build_terrain.py가 구운 바이너리를 읽어 3D 월드가 쓸 삼각형을 만든다.
포맷 규격은 그 스크립트의 독스트링이 정본이고 여기가 소비자다.

    "CLAWTER1"      8 B   매직 — 버전이 다르면 **즉시 거부**한다(조용한 오독 금지)
    u32 header_len  4 B   리틀엔디언
    header          UTF-8 JSON  {origin, tiers:[{name,n0,e0,step,rows,cols,scale,offset,nodata,…}]}
    tier 데이터      헤더 순서대로 rows*cols × u16 LE, row-major, row 0 = n0(남), col 0 = e0(서)

    표고 = offset + raw*scale,  raw == nodata 이면 **결측**

## 결측을 메우지 않는다

수치표고모델에는 도엽 사이 빈 곳과 관측 실패가 있다. 그 자리를 0으로 채우면 화면에 없는
평지가 생기고, 이웃 값으로 채우면 없는 능선이 생긴다. 둘 다 화면이 자료에 없는 것을
말하는 것이라, **삼각형을 만들지 않아 구멍으로 남긴다.** 커버리지는 헤더가 들고 다니고
캡션이 수치로 밝힌다.

## 좌표는 NED다

이 층은 렌더러를 모른다 — 정점은 [n, e, d] (d = −표고)로 낸다. three 축으로 옮기는 일은
어댑터의 `toWorld` 한 줄이 맡는다.
*/

export const MAGIC = "CLAWTER1";

/** ArrayBuffer → {origin, tiers}. 각 tier에 `raw`(Uint16Array)가 붙는다. */
export function parseTerrainPack(buffer) {
  const bytes = new Uint8Array(buffer);
  if (bytes.length < 12) throw new Error("지형 팩이 너무 짧다");
  const magic = String.fromCharCode(...bytes.subarray(0, 8));
  if (magic !== MAGIC) {
    // 버전이 오르면 여기서 시끄럽게 멈춘다 — 옛 팩을 새 코드로 읽으면 표고가 조용히 틀린다
    throw new Error(`지형 팩 매직 불일치: ${JSON.stringify(magic)} (기대 ${MAGIC})`);
  }
  const view = new DataView(buffer);
  const headerLen = view.getUint32(8, true);
  const headerEnd = 12 + headerLen;
  if (headerEnd > bytes.length) throw new Error("지형 팩 헤더 길이가 파일을 넘는다");
  const header = JSON.parse(new TextDecoder().decode(bytes.subarray(12, headerEnd)));

  let offset = headerEnd;
  const tiers = header.tiers.map((t) => {
    const count = t.rows * t.cols;
    const end = offset + count * 2;
    if (end > bytes.length) {
      throw new Error(`지형 팩 데이터가 모자란다: ${t.name} (${count}개 필요)`);
    }
    // slice로 복사한다 — subarray는 정렬이 안 맞으면 Uint16Array 생성이 던진다
    const raw = new Uint16Array(buffer.slice(offset, end));
    offset = end;
    return { ...t, raw };
  });
  return { origin: header.origin, tiers };
}

/** 격자 인덱스 (r, c)의 표고 [m] — 결측이면 null. */
export function elevationAtIndex(tier, r, c) {
  if (r < 0 || c < 0 || r >= tier.rows || c >= tier.cols) return null;
  const raw = tier.raw[r * tier.cols + c];
  return raw === tier.nodata ? null : tier.offset + raw * tier.scale;
}

/** NED (n, e)의 표고 [m] — 이중선형. 네 이웃 중 하나라도 결측이거나 격자 밖이면 null. */
export function elevationAt(tier, n, e) {
  const gr = (n - tier.n0) / tier.step;
  const gc = (e - tier.e0) / tier.step;
  const r0 = Math.floor(gr), c0 = Math.floor(gc);
  const u = gc - c0, v = gr - r0;
  let acc = 0;
  for (const [dr, dc, w] of [
    [0, 0, (1 - u) * (1 - v)], [0, 1, u * (1 - v)],
    [1, 0, (1 - u) * v], [1, 1, u * v],
  ]) {
    if (w === 0) continue; // 경계에 정확히 걸린 경우 없는 이웃을 보지 않는다
    const z = elevationAtIndex(tier, r0 + dr, c0 + dc);
    if (z === null) return null;
    acc += w * z;
  }
  return acc;
}

/** 격자 → 삼각형 메시. 결측 셀은 **삼각형을 만들지 않는다**(구멍으로 남는다).
 *
 * `stride`로 솎고, `skipRect`(NED 사각형) 안쪽 셀은 건너뛴다 — 바깥 티어가 안쪽 티어와
 * 겹쳐 z-fighting을 내지 않도록 **빌드 시점에** 잘라 내는 방식이다(폴리곤오프셋 튜닝 없음).
 *
 * `skipCell(r0, c0, r1, c1)`은 그 위에 얹는 선택 조건이다 — 인자는 **원본 격자 인덱스**로
 * 준 네 꼭짓점이고(솎기 전 좌표), 참이면 그 칸을 그리지 않는다. 바다를 지형에서 빼고
 * 해면이 채우게 하는 데 쓴다. 솎기와 무관하게 원본 좌표로 묻는 이유는, 마스크가 원본
 * 격자 위에서 판정되기 때문이다 — 여기서 좌표계를 바꾸면 호출측이 매번 되돌려야 한다.
 *
 * 반환 정점은 NED [n, e, d]. 법선은 중앙차분으로 만든다(힐셰이드용).
 *
 * @param {object} tier 파싱된 티어
 * @param {object} [opts]
 * @param {number} [opts.stride] 격자 솎기 (1 = 전부)
 * @param {{n0:number, e0:number, n1:number, e1:number}|null} [opts.skipRect] 건너뛸 NED 사각형
 * @param {((r0:number, c0:number, r1:number, c1:number) => boolean)|null} [opts.skipCell]
 *        원본 격자 인덱스로 묻는 추가 조건
 */
export function buildTerrainMesh(tier, { stride = 1, skipRect = null, skipCell = null } = {}) {
  // **마지막 행·열을 반드시 포함한다.** 단순히 stride로 세면 stride가 (rows−1)을
  // 나누어떨어지지 않을 때 가장자리 한 줄이 빠져 티어 경계에 띠가 생긴다 — 격자는
  // tierRect까지 덮는다고 되어 있는데 메시는 못 미치는 상태가 된다.
  const rIdx = sampleIndices(tier.rows, stride);
  const cIdx = sampleIndices(tier.cols, stride);
  const rows = rIdx.length, cols = cIdx.length;

  const positions = new Float32Array(rows * cols * 3);
  const normals = new Float32Array(rows * cols * 3);
  const present = new Uint8Array(rows * cols);

  for (let r = 0; r < rows; r++) {
    const n = tier.n0 + rIdx[r] * tier.step;
    for (let c = 0; c < cols; c++) {
      const e = tier.e0 + cIdx[c] * tier.step;
      const i = r * cols + c;
      const z = elevationAtIndex(tier, rIdx[r], cIdx[c]);
      positions[3 * i] = n;
      positions[3 * i + 1] = e;
      positions[3 * i + 2] = z === null ? NaN : -z; // 표고 → D
      present[i] = z === null ? 0 : 1;
    }
  }

  // 법선 — 중앙차분. 간격은 **실제 정점 간격**에서 읽는다(가장자리 칸은 짧을 수 있다).
  // 이웃이 결측이면 그쪽은 한쪽 차분으로 물러선다(0 법선을 만들지 않는다).
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const i = r * cols + c;
      if (!present[i]) { normals[3 * i + 2] = -1; continue; }
      const dzdn = slope(positions, present, rows, cols, r, c, 1, 0, 0);
      const dzde = slope(positions, present, rows, cols, r, c, 0, 1, 1);
      // 표면 z = f(n, e)의 법선(위 방향) = (−∂z/∂n, −∂z/∂e, 1) → D축은 부호 반전
      const len = Math.hypot(dzdn, dzde, 1);
      normals[3 * i] = -dzdn / len;
      normals[3 * i + 1] = -dzde / len;
      normals[3 * i + 2] = -1 / len;
    }
  }

  const idx = [];
  let skipped = 0;
  for (let r = 0; r + 1 < rows; r++) {
    for (let c = 0; c + 1 < cols; c++) {
      const a = r * cols + c, b = a + 1, d = a + cols, f = d + 1;
      if (!(present[a] && present[b] && present[d] && present[f])) { skipped++; continue; }
      if (skipRect && cellInside(positions, cols, r, c, skipRect)) { skipped++; continue; }
      if (skipCell && skipCell(rIdx[r], cIdx[c], rIdx[r + 1], cIdx[c + 1])) { skipped++; continue; }
      // 감김 방향 주의: NED에서 r은 북(+n), c는 동(+e)인데 렌더러 축은 x=e, y=−d, z=−n이라
      // **n이 커질수록 z가 작아진다.** 그래서 (a,d,b) 순서로 감으면 앞면이 아래를 보고,
      // 위에서 내려다보는 카메라가 지형의 **밑면**을 보게 된다(조명이 위에 있으니 새까맣다).
      // 라이브에서 화면 아래 절반이 검게 나와 잡았고, 아래 테스트가 그것을 못박는다.
      idx.push(a, b, d, b, f, d);
    }
  }
  return {
    positions, normals,
    indices: rows * cols > 65535 ? new Uint32Array(idx) : new Uint16Array(idx),
    rows, cols, step: tier.step * stride,
    triangles: idx.length / 3,
    skippedCells: skipped,
  };
}

/** 0부터 stride 간격으로, **마지막 인덱스는 반드시 포함**해서. */
function sampleIndices(count, stride) {
  // count 0에서 [0, −1]을 내던 함정 — 오늘 닿는 경로는 없지만 남겨 둘 이유도 없다
  if (!(count > 0)) return [];
  if (!(stride > 0)) throw new Error(`stride는 양수여야 함: ${stride}`);
  const out = [];
  for (let i = 0; i < count; i += stride) out.push(i);
  if (out[out.length - 1] !== count - 1) out.push(count - 1);
  return out;
}

/** 이 티어가 덮는 NED 사각형 — 바깥 티어의 skipRect를 만들 때 쓴다. */
export function tierRect(tier) {
  return {
    n0: tier.n0, e0: tier.e0,
    n1: tier.n0 + (tier.rows - 1) * tier.step,
    e1: tier.e0 + (tier.cols - 1) * tier.step,
  };
}

/** 셀 네 귀퉁이가 전부 사각형 안이면 건너뛴다 — 경계 셀은 남겨야 틈이 안 생긴다.
 *  실제 정점 좌표를 보므로 가장자리에서 간격이 달라져도 판정이 어긋나지 않는다. */
function cellInside(pos, cols, r, c, rect) {
  const a = (r * cols + c) * 3;
  const f = ((r + 1) * cols + (c + 1)) * 3;
  return pos[a] >= rect.n0 && pos[f] <= rect.n1
    && pos[a + 1] >= rect.e0 && pos[f + 1] <= rect.e1;
}

/** 중앙차분 기울기 — 간격을 **실제 정점 좌표**에서 읽는다(가장자리 칸이 짧을 수 있다). */
function slope(pos, present, rows, cols, r, c, dr, dc, axis) {
  const at = (rr, cc) => {
    const i = rr * cols + cc;
    return present[i] ? -pos[3 * i + 2] : null; // D → 표고
  };
  const coord = (rr, cc) => pos[(rr * cols + cc) * 3 + axis];
  const hasBack = r - dr >= 0 && c - dc >= 0;
  const hasFwd = r + dr < rows && c + dc < cols;
  const back = hasBack ? at(r - dr, c - dc) : null;
  const fwd = hasFwd ? at(r + dr, c + dc) : null;
  const here = at(r, c);
  if (back !== null && fwd !== null) {
    const d = coord(r + dr, c + dc) - coord(r - dr, c - dc);
    return d === 0 ? 0 : (fwd - back) / d;
  }
  if (fwd !== null) {
    const d = coord(r + dr, c + dc) - coord(r, c);
    return d === 0 ? 0 : (fwd - here) / d;
  }
  if (back !== null) {
    const d = coord(r, c) - coord(r - dr, c - dc);
    return d === 0 ? 0 : (here - back) / d;
  }
  return 0;
}
