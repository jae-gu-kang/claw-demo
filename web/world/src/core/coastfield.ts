/** 해안 거리장 — 해면이 **어디서 잦아들고 어디서 사라지는지**.
 *
 * ## 왜 필요한가 — 화면이 알려 준 것
 *
 * 해면을 무한 평면으로 깔고 파도를 올렸더니, 활주로 둘레의 평지에서 **파마루가 지형을
 * 뚫고 올라왔다.** `core/seamask.ts`가 말하는 그 16.5 km²다: 표고가 정확히 0 m인데
 * 바다가 아닌 땅(간척지·저지대). 지형도 0 m, 해면도 0 m라 파고 1 m가 그대로 솟는다.
 *
 * 지형을 올리거나 해면을 내리는 것은 둘 다 화면이 거짓말하는 쪽이다. 대신 **해안에서
 * 파고를 0으로 재운다** — 실제로도 파도는 얕은 곳에서 부서져 잦아든다. 그리고 뭍
 * 안쪽에서는 해면을 아예 버린다.
 *
 * ## 해상도와 그 대가
 *
 * 60 km 도메인을 1536칸으로 나누면 39 m/텍셀이다. 지형 안쪽 티어(30 m)보다 성기므로
 * **해안선을 이 격자로 그리면 안 된다** — 그래서 버리는 문턱을 뭍 쪽으로 120 m 밀어
 * 둔다. 그 띠에서는 파고가 이미 0이라 평평한 해면이 남고, 깊이 밀기(polygonOffset)가
 * 지형에 진다. 거리장은 **부드러운 것**(파고 감쇠·얕은 물색·포말)에만 쓴다.
 *
 * ## 결측은 바다가 아니다
 *
 * `known = 0`인 칸에서는 해면을 그리지 않는다. 관측이 없는 곳에 없는 바다를 만들지
 * 않는다는 규약이 여기까지 온다 — 지형에 구멍이 뚫려 있으면 그 구멍으로 바다가 보이는데,
 * 그것은 구멍이 아니라 **호수**로 읽힌다.
 *
 * ## 도메인 밖
 *
 * 바깥은 **바다로 친다.** 이 시험장은 해안가라 30 km 경계는 대부분 바다지만, 동쪽
 * 산지가 물가에서 끊기는 그림이 되기도 한다. 지어낸 지리이므로 캡션이 밝힌다.
 */

import { CELL, nedToCell, type MaskTier, type TierMask } from "./seamask.ts";

export interface CoastField {
  /** 한 변의 칸 수 */ size: number;
  /** 도메인 좌하단 NED [m] */ n0: number; e0: number;
  /** 도메인 한 변 [m] */ nSpan: number; eSpan: number;
  /** 부호 있는 해안 거리 [m]. **양수 = 바다**, 음수 = 뭍. */
  dist: Float32Array;
  /** 1이면 지형 자료가 있는 칸. 0이면 해면을 그리지 않는다. */
  known: Uint8Array;
  /** 칸 한 변 [m] — 캡션이 말한다. */
  metersPerCell: number;
}

/** 티어 하나와 그 마스크. */
export interface MaskedTier { tier: MaskTier; mask: TierMask }

/** 펠젠츠발브-허튼로커 1차원 제곱거리 변환. `f`를 제자리에서 `d`로 옮긴다. O(n). */
function edt1d(f: Float64Array, n: number, d: Float64Array, v: Int32Array, z: Float64Array): void {
  let k = 0;
  v[0] = 0;
  z[0] = -Infinity;
  z[1] = Infinity;
  for (let q = 1; q < n; q++) {
    let s = (f[q]! + q * q - (f[v[k]!]! + v[k]! * v[k]!)) / (2 * q - 2 * v[k]!);
    while (s <= z[k]!) {
      k--;
      s = (f[q]! + q * q - (f[v[k]!]! + v[k]! * v[k]!)) / (2 * q - 2 * v[k]!);
    }
    k++;
    v[k] = q;
    z[k] = s;
    z[k + 1] = Infinity;
  }
  k = 0;
  for (let q = 0; q < n; q++) {
    while (z[k + 1]! < q) k++;
    const dq = q - v[k]!;
    d[q] = dq * dq + f[v[k]!]!;
  }
}

/** 2차원 제곱거리 변환 — `seed[i] === 0`인 칸까지의 거리(칸 단위)의 제곱. */
export function squaredDistanceTransform(seed: Float64Array, w: number, h: number): Float64Array {
  const INF = 1e20;
  const out = new Float64Array(w * h);
  for (let i = 0; i < w * h; i++) out[i] = seed[i] === 0 ? 0 : INF;

  const n = Math.max(w, h);
  const f = new Float64Array(n);
  const d = new Float64Array(n);
  const v = new Int32Array(n);
  const z = new Float64Array(n + 1);

  for (let x = 0; x < w; x++) {
    for (let y = 0; y < h; y++) f[y] = out[y * w + x]!;
    edt1d(f, h, d, v, z);
    for (let y = 0; y < h; y++) out[y * w + x] = d[y]!;
  }
  for (let y = 0; y < h; y++) {
    const row = y * w;
    for (let x = 0; x < w; x++) f[x] = out[row + x]!;
    edt1d(f, w, d, v, z);
    for (let x = 0; x < w; x++) out[row + x] = d[x]!;
  }
  return out;
}

/** 모든 티어를 덮는 NED 사각형. */
function domainOf(tiers: readonly MaskedTier[]): { n0: number; e0: number; nSpan: number; eSpan: number } {
  let n0 = Infinity; let e0 = Infinity; let n1 = -Infinity; let e1 = -Infinity;
  for (const { tier } of tiers) {
    n0 = Math.min(n0, tier.n0);
    e0 = Math.min(e0, tier.e0);
    n1 = Math.max(n1, tier.n0 + (tier.rows - 1) * tier.step);
    e1 = Math.max(e1, tier.e0 + (tier.cols - 1) * tier.step);
  }
  return { n0, e0, nSpan: Math.max(n1 - n0, 1), eSpan: Math.max(e1 - e0, 1) };
}

/** 거리장을 굽는다. 티어는 **격자가 촘촘한 것이 이긴다**(안쪽 티어가 정본). */
export function buildCoastField(tiers: readonly MaskedTier[], size = 1536): CoastField {
  const fine = [...tiers].sort((a, b) => a.tier.step - b.tier.step);
  const dom = domainOf(fine.length > 0 ? fine : tiers);
  const w = size;
  const h = size;

  // 0 = 시드. `seaSeed`는 바다 칸이 0(→ 바다까지의 거리), `landSeed`는 뭍 칸이 0.
  const seaSeed = new Float64Array(w * h);
  const landSeed = new Float64Array(w * h);
  const known = new Uint8Array(w * h);
  const isSea = new Uint8Array(w * h);

  for (let r = 0; r < h; r++) {
    const n = dom.n0 + (dom.nSpan * r) / (h - 1);
    for (let c = 0; c < w; c++) {
      const e = dom.e0 + (dom.eSpan * c) / (w - 1);
      const i = r * w + c;
      let cell: number | null = null;
      for (const { tier, mask } of fine) {
        const idx = nedToCell(tier, n, e);
        if (idx) { cell = mask.cells[idx[0] * mask.cols + idx[1]]!; break; }
      }
      // 도메인 밖 — 열린 바다로 친다(지어낸 지리, 캡션이 밝힌다).
      if (cell === null) cell = CELL.SEA;
      if (cell === CELL.MISSING) {
        // 결측은 바다도 뭍도 아니다. 어느 쪽 시드도 아니게 두면 거리가 양쪽에서 흘러온다.
        seaSeed[i] = 1;
        landSeed[i] = 1;
        continue;
      }
      known[i] = 1;
      if (cell === CELL.SEA) { isSea[i] = 1; seaSeed[i] = 0; landSeed[i] = 1; }
      else { seaSeed[i] = 1; landSeed[i] = 0; }
    }
  }

  const toSea = squaredDistanceTransform(seaSeed, w, h);
  const toLand = squaredDistanceTransform(landSeed, w, h);
  // 칸이 정사각이 아닐 수 있다 — 짧은 쪽으로 재면 거리를 **과소평가**하지 않는다.
  const mpc = Math.min(dom.eSpan / (w - 1), dom.nSpan / (h - 1));

  const dist = new Float32Array(w * h);
  for (let i = 0; i < w * h; i++) {
    dist[i] = isSea[i] === 1
      ? Math.sqrt(toLand[i]!) * mpc
      : -Math.sqrt(toSea[i]!) * mpc;
  }

  return { size, n0: dom.n0, e0: dom.e0, nSpan: dom.nSpan, eSpan: dom.eSpan, dist, known, metersPerCell: mpc };
}

/** 인코딩이 담는 거리의 폭 [m]. 밖은 포화한다. */
export const COAST_RANGE_M = 1500;

/** 바이트 → 거리 [m]. **셰이더가 하는 것과 같은 식**이다(`shaders/ocean.ts`).
 *
 * 0 m가 바이트 중앙에 정확히 앉지 않는다는 점이 중요하다 — `0.5 × 255 = 127.5`라
 * 반올림하면 0 m와 +6 m가 같은 바이트(128)로 간다. 그래서 판정은 **복호한 값의 부호**로
 * 해야 하고, 바이트를 127/128과 견주면 해안선이 한 칸 밀린다. */
export function decodeCoastDistance(byte: number): number {
  return ((byte / 255) * 2 - 1) * COAST_RANGE_M;
}

/** RG8 텍스처 바이트 — R = 거리(부호 있음), G = known. */
export function encodeCoastField(f: CoastField): Uint8Array {
  const out = new Uint8Array(f.size * f.size * 2);
  for (let i = 0; i < f.size * f.size; i++) {
    const t = Math.max(-1, Math.min(1, f.dist[i]! / COAST_RANGE_M)) * 0.5 + 0.5;
    out[2 * i] = Math.round(t * 255);
    out[2 * i + 1] = f.known[i] === 1 ? 255 : 0;
  }
  return out;
}
