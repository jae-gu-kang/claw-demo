/** 영향성 그래프 배치 — 순수 함수, DOM 무접촉 (판단은 lib에, 그리기는 views에).

두 후보가 **같은 Layout 형태**를 낸다. 그래서 렌더러가 하나면 되고, 후보를 지우는
일이 함수를 지우는 일이 된다 — 성운(radial)이 실제로 그렇게 지워졌다.

    layeredLayout  후보 A — 좌→우 층 배치 (신경망 레이어 그림)
    cascadeLayout  후보 B — 생키 리본 (전파 폭포)

**결정적이다.** Math.random을 쓰지 않는다 — 같은 입력이면 같은 그림이라야 다시
그릴 때 흔들리지 않고, 테스트도 쓸 수 있다.
*/

// 랭크 규약 — 파라미터가 왼쪽 끝, 지표가 오른쪽 끝
export const KIND_ORDER = { param: 0, input: 1, ir: 2, ghost: 2, output: 3, plant: 4, metric: 5 };

// 랭크를 밀지 못하는(들어오는 간선이 없는) 종류
const PINNED = { param: 0, input: 1 };

/** 위상 정렬 — Kahn. 동률은 배열 순서로 깨서 결정적이다.
 *
 * 선언 순서가 위상 순서라는 IR의 성질에 기대지 않는다: 유령 노드(구조 변경으로
 * '생길' 노드)는 선언 순서 밖에서 붙기 때문이다. 순환은 IR이 원천 차단하지만,
 * 남으면 조용히 빠뜨리는 대신 던진다.
 */
export function topoOrder(nodes, edges) {
  const idx = new Map(nodes.map((n, i) => [n.id, i]));
  const indeg = new Map(nodes.map((n) => [n.id, 0]));
  const out = new Map(nodes.map((n) => [n.id, []]));
  for (const e of edges) {
    if (!idx.has(e.src) || !idx.has(e.dst)) continue;
    out.get(e.src).push(e.dst);
    indeg.set(e.dst, indeg.get(e.dst) + 1);
  }
  const ready = nodes.filter((n) => indeg.get(n.id) === 0).map((n) => n.id);
  ready.sort((a, b) => idx.get(a) - idx.get(b));
  const order = [];
  while (ready.length) {
    const id = ready.shift();
    order.push(id);
    for (const d of out.get(id)) {
      indeg.set(d, indeg.get(d) - 1);
      if (indeg.get(d) === 0) {
        // 정렬 삽입 — shift 순서를 배열 순서에 묶어 결정성을 지킨다
        let i = 0;
        while (i < ready.length && idx.get(ready[i]) < idx.get(d)) i += 1;
        ready.splice(i, 0, d);
      }
    }
  }
  if (order.length !== nodes.length) {
    throw new Error(`순환이 있다 — 위상 정렬 불가 (${nodes.length - order.length}개 남음)`);
  }
  return order;
}

/** 랭크 배정 — **최장 경로**. 최단이 아니다.
 *
 * 최장이라야 "층 번호 = 이 노드가 실행될 수 있는 가장 이른 단계"가 되고, 그래야
 * 화면의 파급 애니메이션이 곧 생성 C의 문장 순서를 보여 준다. 최단으로 매기면
 * 긴 경로의 노드가 앞으로 당겨져 층이 실행 순서와 어긋난다.
 */
export function assignRanks(nodes, edges) {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const order = topoOrder(nodes, edges);
  const rank = new Map();
  for (const id of order) {
    const kind = byId.get(id).kind;
    rank.set(id, PINNED[kind] ?? 0);
  }
  const incoming = new Map(nodes.map((n) => [n.id, []]));
  for (const e of edges) {
    if (byId.has(e.src) && byId.has(e.dst)) incoming.get(e.dst).push(e.src);
  }
  for (const id of order) {
    const kind = byId.get(id).kind;
    if (kind in PINNED) continue;
    let r = 0;
    for (const s of incoming.get(id)) r = Math.max(r, rank.get(s) + 1);
    rank.set(id, r);
  }
  let maxRank = 0;
  for (const r of rank.values()) maxRank = Math.max(maxRank, r);
  const byRank = Array.from({ length: maxRank + 1 }, () => []);
  for (const n of nodes) byRank[rank.get(n.id)].push(n.id);
  return { rank, byRank, maxRank };
}

/** 간선 교차 수 — 배치 품질의 목적함수.
 *
 * **같은 층 쌍의 간선끼리만** 센다. 층이 다르면 화면에서 겹칠 수는 있어도 이 배치
 * 문제에서 말하는 교차가 아니고, 섞어 세면 목적함수가 순서 개선에 반응하지 않는다.
 */
export function crossingCount(edges, order, rank) {
  const groups = new Map();
  for (const e of edges) {
    if (!order.has(e.src) || !order.has(e.dst)) continue;
    const key = `${rank.get(e.src)}>${rank.get(e.dst)}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(e);
  }
  let n = 0;
  for (const es of groups.values()) {
    for (let i = 0; i < es.length; i += 1) {
      for (let j = i + 1; j < es.length; j += 1) {
        const da = order.get(es[i].src) - order.get(es[j].src);
        const db = order.get(es[i].dst) - order.get(es[j].dst);
        if (da * db < 0) n += 1;
      }
    }
  }
  return n;
}

/** 층 내 순서 — 바리센터 스윕. 그룹(sched·ap·lim·scas·mix)은 붙여 둔다.
 *
 * 묶음을 흐트러뜨리면 교차는 줄어도 "어디까지가 오토파일럿인가"가 사라진다.
 * IR은 group이 선언 순서상 연속이도록 강제돼 있으므로(ir.py) 그 성질을 배치에서도 지킨다.
 */
export function orderWithinRanks(nodes, edges, ranks, { sweeps = 8, keepGroups = true } = {}) {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const bands = [...new Set(nodes.map((n) => n.band ?? ""))];
  const bandIdx = new Map(bands.map((b, i) => [b, i]));
  const pred = new Map(nodes.map((n) => [n.id, []]));
  const succ = new Map(nodes.map((n) => [n.id, []]));
  for (const e of edges) {
    if (!byId.has(e.src) || !byId.has(e.dst)) continue;
    pred.get(e.dst).push(e.src);
    succ.get(e.src).push(e.dst);
  }

  // 묶음 정렬은 **초기 순서부터** 건다. 스윕 안의 비교자에만 두면, 교차가 이미 0인
  // 경우 개선이 채택되지 않아 선언 순서(묶음이 섞인 채)가 그대로 남는다.
  const declIdx = new Map(nodes.map((n, i) => [n.id, i]));
  let best = ranks.byRank.map((ids) => (keepGroups
    ? [...ids].sort((a, b) => (bandIdx.get(byId.get(a).band ?? "") - bandIdx.get(byId.get(b).band ?? ""))
        || (declIdx.get(a) - declIdx.get(b)))
    : [...ids]));
  const posOf = (layers) => {
    const m = new Map();
    layers.forEach((ids) => ids.forEach((id, i) => m.set(id, i)));
    return m;
  };
  let bestPos = posOf(best);
  let bestCross = crossingCount(edges, bestPos, ranks.rank);

  let cur = best.map((ids) => [...ids]);  // 스윕은 이 묶음 정렬 위에서 시작한다
  for (let s = 0; s < sweeps; s += 1) {
    const down = s % 2 === 0;
    const pos = posOf(cur);
    const layers = down ? cur.map((_, i) => i) : cur.map((_, i) => cur.length - 1 - i);
    for (const li of layers) {
      const neigh = down ? pred : succ;
      const prev = new Map(cur[li].map((id, i) => [id, i]));
      cur[li] = [...cur[li]].sort((a, b) => {
        if (keepGroups) {
          const ga = bandIdx.get(byId.get(a).band ?? "");
          const gb = bandIdx.get(byId.get(b).band ?? "");
          if (ga !== gb) return ga - gb;
        }
        const ba = barycenter(neigh.get(a), pos, prev.get(a));
        const bb = barycenter(neigh.get(b), pos, prev.get(b));
        if (ba !== bb) return ba - bb;
        return prev.get(a) - prev.get(b); // 안정 — 결정성의 마지막 고리
      });
    }
    const p = posOf(cur);
    const c = crossingCount(edges, p, ranks.rank);
    if (c < bestCross) {
      bestCross = c;
      best = cur.map((ids) => [...ids]);
      bestPos = p;
    }
  }
  return { byRank: best, order: bestPos, crossings: bestCross };
}

function barycenter(neighbors, pos, fallback) {
  if (!neighbors || !neighbors.length) return fallback;
  let sum = 0;
  let n = 0;
  for (const id of neighbors) {
    const p = pos.get(id);
    if (p !== undefined) {
      sum += p;
      n += 1;
    }
  }
  return n ? sum / n : fallback;
}


/** 좌표 배정 — x는 랭크, y는 층 내 순서 + 이웃 중앙값으로 당기기.
 *
 * `cols`는 한 랭크를 세로 여러 줄로 접는다. 파라미터 열이 65행인데 IR 층은 넓어야
 * 12행이라, 접지 않으면 왼쪽만 길고 오른쪽은 텅 빈 그림이 된다. 층 내 순서가 이미
 * 묶음 정렬이라 연속 덩이로 자르면 묶음도 함께 보존된다.
 */
export function assignCoords(nodes, edges, ranks, ordered, opts = {}) {
  const {
    width = 1200, height = 640, pad = 34, rowGap = 20, colGap = 132,
    // 오른쪽 여백은 장식이 아니다 — 지표·출력 라벨이 노드 **오른쪽**에 붙으므로
    // 여기를 안 비우면 마지막 열의 글자가 캔버스 밖으로 잘린다
    padRight = pad, cols = {}, medianPasses = 2, radiusOf = null, rankX: rankXIn = null,
  } = opts;
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const nRank = ranks.maxRank + 1;

  // 각 랭크의 실제 폭(접은 줄 수)과 행 수
  const colsOf = (r) => Math.max(1, cols[r] ?? 1);
  const rowsOf = (r) => Math.ceil((ordered.byRank[r]?.length ?? 0) / colsOf(r));
  const maxRows = Math.max(1, ...Array.from({ length: nRank }, (_, r) => rowsOf(r)));

  // x: 접힌 랭크는 자기 줄 수만큼 자리를 더 먹는다
  const rankX = rankXIn ?? (() => {
    const xs = [];
    let x = pad;
    for (let r = 0; r < nRank; r += 1) {
      xs.push(x);
      x += colGap + (colsOf(r) - 1) * (colGap * 0.55);
    }
    return xs;
  })();
  const spanX = rankX[nRank - 1] - rankX[0] || 1;
  const usableW = Math.max(1, width - pad - padRight);
  const kx = Math.min(1, usableW / spanX);

  const pos = new Map();
  for (let r = 0; r < nRank; r += 1) {
    const ids = ordered.byRank[r] ?? [];
    const c = colsOf(r);
    const rows = rowsOf(r);
    const perCol = Math.ceil(ids.length / c) || 1;
    const y0 = (height - (rows - 1) * rowGap) / 2;
    ids.forEach((id, i) => {
      const col = Math.floor(i / perCol);
      const row = i % perCol;
      pos.set(id, {
        x: pad + (rankX[r] - rankX[0]) * kx + col * colGap * 0.55 * kx,
        y: y0 + row * rowGap,
        r: radiusOf ? radiusOf(byId.get(id)) : 4.5,
      });
    });
  }

  // 이웃 중앙값으로 당기기 — 긴 간선이 층을 가로지르며 꺾이는 것을 줄인다.
  // 같은 (랭크, 줄) 안에서만 움직이고 minGap으로 다시 벌린다
  const neigh = new Map(nodes.map((n) => [n.id, []]));
  for (const e of edges) {
    if (!byId.has(e.src) || !byId.has(e.dst)) continue;
    neigh.get(e.dst).push(e.src);
    neigh.get(e.src).push(e.dst);
  }
  for (let pass = 0; pass < medianPasses; pass += 1) {
    for (let r = 0; r < nRank; r += 1) {
      const ids = ordered.byRank[r] ?? [];
      const c = colsOf(r);
      const perCol = Math.ceil(ids.length / c) || 1;
      for (let col = 0; col < c; col += 1) {
        const slice = ids.slice(col * perCol, (col + 1) * perCol);
        if (slice.length < 2) continue;
        const want = slice.map((id) => {
          const ys = neigh.get(id).map((m) => pos.get(m)?.y).filter((y) => y !== undefined);
          return ys.length ? median(ys) : pos.get(id).y;
        });
        const idxs = slice.map((_, i) => i).sort((a, b) => want[a] - want[b]);
        // 순서는 유지하고 값만 정렬해 다시 배치 — 교차 최적화를 되돌리지 않는다
        const sortedWant = idxs.map((i) => want[i]).sort((a, b) => a - b);
        let prev = -Infinity;
        slice.forEach((id, i) => {
          const y = Math.max(sortedWant[i] ?? pos.get(id).y, prev + rowGap);
          pos.get(id).y = y;
          prev = y;
        });
        // 위 밀어내기는 **아래로만** 작용한다 — 그대로 두면 패스를 돌 때마다 열이
        // 통째로 내려앉아 위쪽이 비고 아래가 넘친다. 열 단위로 다시 가운데 맞춘다
        const lo = pos.get(slice[0]).y;
        const hi = pos.get(slice[slice.length - 1]).y;
        const shift = (height - (hi - lo)) / 2 - lo;
        for (const id of slice) pos.get(id).y += shift;
      }
    }
  }
  let maxY = 0;
  for (const p of pos.values()) maxY = Math.max(maxY, p.y);
  return { pos, rankX, bounds: { w: width, h: Math.max(height, maxY + pad), maxRows } };
}

function median(xs) {
  const s = [...xs].sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

/** 간선 곡선 — 양 끝이 수평으로 드나든다.
 *
 * 끝점 접선을 수평으로 두는 것이 층 그림으로 읽히게 하는 핵심이다. 자유 곡선이면
 * 같은 데이터라도 실타래로 보인다. 층을 여럿 건너뛰는 간선은 노드 밭 **바깥으로**
 * 휘어 지나가게 해서 중간 층을 관통하지 않게 한다.
 */
export function edgeBezier(p0, p1, { rankSpan = 1, tension = 0.42, bowAway = 0 } = {}) {
  const dx = p1.x - p0.x;
  const k = tension + 0.06 * Math.min(rankSpan, 4);
  const arc = rankSpan <= 1 ? 0 : Math.sign(bowAway || 1) * Math.min(28, 6 * rankSpan);
  return {
    x0: p0.x, y0: p0.y,
    c1x: p0.x + k * dx, c1y: p0.y + arc,
    c2x: p1.x - k * dx, c2y: p1.y + arc,
    x1: p1.x, y1: p1.y,
  };
}

/** 베지어 → 폴리라인 + 누적 호길이. 입자가 곡선에서 느려지지 않게 하는 근거.
 *
 * 표본 24: 원뿔 간선은 **자라는 중이든 완성이든 이 폴리라인으로만** 그린다
 * (`arcPrefix`). 즉 현눈금 오차가 곧 화면의 곡선 오차다 — 이 화면에서 가장 심한
 * 곡선(길이 ~400 px·곡률반경 ~200 px)에서 16이면 0.39 px, 24면 0.17 px.
 */
export function flattenBezier(b, samples = 24) {
  const pts = [];
  for (let i = 0; i <= samples; i += 1) {
    const t = i / samples;
    const u = 1 - t;
    pts.push({
      x: u * u * u * b.x0 + 3 * u * u * t * b.c1x + 3 * u * t * t * b.c2x + t * t * t * b.x1,
      y: u * u * u * b.y0 + 3 * u * u * t * b.c1y + 3 * u * t * t * b.c2y + t * t * t * b.y1,
    });
  }
  const cum = new Float64Array(pts.length);
  for (let i = 1; i < pts.length; i += 1) {
    cum[i] = cum[i - 1] + Math.hypot(pts[i].x - pts[i - 1].x, pts[i].y - pts[i - 1].y);
  }
  return { pts, cum, len: cum[cum.length - 1] };
}

/** 호길이 매개변수 s∈[0,1]의 점 — 균등 t가 아니라 균등 **거리**. */
export function pointAtArc(flat, s) {
  const target = Math.max(0, Math.min(1, s)) * flat.len;
  const { pts, cum } = flat;
  if (!(flat.len > 0)) return { ...pts[0], angle: 0 };
  let i = 1;
  while (i < cum.length - 1 && cum[i] < target) i += 1;
  const seg = cum[i] - cum[i - 1] || 1;
  const u = (target - cum[i - 1]) / seg;
  const a = pts[i - 1];
  const b = pts[i];
  return {
    x: a.x + (b.x - a.x) * u,
    y: a.y + (b.y - a.y) * u,
    angle: Math.atan2(b.y - a.y, b.x - a.x),
  };
}

/** 호길이 0..s 구간의 폴리라인 — **끝점만 보간한다**.
 *
 * `{ n, last }`: `flat.pts[0 .. n-1]`을 잇고, `last`가 있으면 거기까지 한 번 더 긋는다.
 * 배열을 새로 만들지 않는 이유: 순차 재생에서 간선 141개 × 25 fps로 불린다.
 *
 * 끝점을 자체 보간하지 않고 `pointAtArc`를 재사용하는 이유는 "호길이 s의 점이 어디인가"를
 * 두 곳에서 정의하지 않기 위해서다 — 어긋나면 입자와 선 끝이 다른 자리에 놓인다.
 */
export function arcPrefix(flat, s) {
  const pts = flat.pts;
  if (!(s > 0)) return { n: 0, last: null };
  // len이 정확히 0인 경우만 걸린다. 제자리 간선의 실제 len은 1.5e-14쯤이라 아래
  // 일반 경로로 가는데, pointAtArc가 `seg || 1`로 0-나눗셈을 막고 있어 제자리 점이 나온다
  if (s >= 1 || !(flat.len > 0)) return { n: pts.length, last: null };
  const target = s * flat.len;
  const cum = flat.cum;
  let i = 0;
  while (i < cum.length - 1 && cum[i + 1] <= target) i += 1;
  return { n: i + 1, last: pointAtArc(flat, s) };
}

/** 가장 가까운 노드 — 반경 안, 동률이면 작은 노드 우선 (겹칠 때 위에 있는 쪽). */
export function hitTestNodes(pos, x, y, { radius = 10 } = {}) {
  let best = null;
  let bestD = Infinity;
  for (const [id, p] of pos) {
    const d = Math.hypot(p.x - x, p.y - y);
    if (d > Math.max(radius, p.r + 4)) continue;
    if (d < bestD || (d === bestD && best && p.r < pos.get(best).r)) {
      bestD = d;
      best = id;
    }
  }
  return best;
}

/** 후보 A — 레이어 활성망. 파라미터 열은 세 줄로 접는다. */
export function layeredLayout(graph, opts = {}) {
  const { nodes, edges } = graph;
  const ranks = assignRanks(nodes, edges);
  const ordered = orderWithinRanks(nodes, edges, ranks, opts);
  const paramCols = opts.paramCols ?? 3;
  const coords = assignCoords(nodes, edges, ranks, ordered, {
    ...opts,
    cols: { 0: paramCols, ...(opts.cols ?? {}) },
  });
  // `idx`는 **입력 배열에서의 자리**다. 아래 filter가 좌표 없는 간선을 떨구므로
  // 출력 배열의 위치는 모델 간선 인덱스와 어긋날 수 있는데, 소비처(원뿔 판정·재생
  // 일정)는 모델 인덱스로 말한다 — 자리로 맞추면 **엉뚱한 선이 켜진다**
  const eout = edges.map((e, i) => {
    const p0 = coords.pos.get(e.src);
    const p1 = coords.pos.get(e.dst);
    if (!p0 || !p1) return null;
    const span = Math.abs((ranks.rank.get(e.dst) ?? 0) - (ranks.rank.get(e.src) ?? 0));
    const bow = (p0.y + p1.y) / 2 < coords.bounds.h / 2 ? -1 : 1;
    const bez = edgeBezier(p0, p1, { rankSpan: span, bowAway: bow });
    return { ...e, idx: i, rankSpan: span, bez, flat: flattenBezier(bez) };
  }).filter(Boolean);
  return {
    variant: "layered", nodes, edges: eout, pos: coords.pos, ranks,
    order: ordered.order, crossings: ordered.crossings,
    rankX: coords.rankX, bounds: coords.bounds, meta: { conserved: null },
  };
}


/** 후보 B — 전파 폭포. 16층이 아니라 **모듈 밴드**로 접어 굵은 리본으로 흐르게 한다.
 *
 * 굵기가 곧 영향량이라는 읽기를 주지만, 영향은 **보존량이 아니다** — 파라미터 하나가
 * 여러 노드를 흔들고, 하류 합이 상류와 같지도 않다. 그래서 랭크 내 상대값으로만
 * 정규화하고 `meta.conserved = false`로 못박는다 (화면이 그 문구를 띄울 근거).
 */
export function cascadeLayout(graph, opts = {}) {
  const { nodes, edges } = graph;
  const { width = 1180, height = 640, pad = 26, padRight = 168, rowGap = 16 } = opts;
  // 묶음 이름·IR 그룹 이름은 **엔진 소유**다 (influence.py BANDS / Graph.partitions).
  // 여기 목록으로 베껴 두면 엔진에 하나 늘 때 A·B는 멀쩡한데 C만 조용히 그 노드를
  // 미분류 열에 처박는다 — 02 §5.5가 막는 바로 그 사고다. payload에서 받고,
  // 못 받았으면 노드에서 유도한다 (둘 다 없으면 그때만 빈 목록)
  const seen = (key) => [...new Set(nodes.map((n) => n[key]).filter(Boolean))];
  const bandOrder = opts.bandOrder?.length ? opts.bandOrder : seen("band");
  const groups = [...new Set([...(opts.groups ?? []), ...seen("group")])];
  const nCol = groups.length + 5;
  const colOf = (n) => {
    if (n.kind === "param") return 0;
    if (n.kind === "input") return 1;
    if (n.kind === "output") return nCol - 3;
    if (n.kind === "plant") return nCol - 2;
    if (n.kind === "metric") return nCol - 1;
    const gi = groups.indexOf(n.group ?? "");
    return gi < 0 ? nCol - 3 : 2 + gi;  // 모르는 그룹은 출력 직전에 세운다 (삼키지 않는다)
  };
  const cols = Array.from({ length: nCol }, () => []);
  const bandRank = (n) => {
    if (n.kind !== "param") return 0;
    const i = bandOrder.indexOf(n.band ?? "");
    return i < 0 ? bandOrder.length : i;  // 모르는 묶음은 맨 뒤 — 앞으로 끼어들지 않게
  };
  for (const n of nodes) cols[colOf(n)].push(n);
  for (const c of cols) c.sort((a, b) => bandRank(a) - bandRank(b));

  // 파라미터 열만 65개다 — 접지 않으면 그 열 하나가 화면 높이를 1000 px 넘게 끌어올려
  // 나머지 열이 전부 실선 한 줄로 보인다. 다른 열은 12개 이하라 접을 필요가 없다
  const maxPerCol = Math.max(4, opts.maxPerCol ?? 24);
  const sub = cols.map((c) => Math.max(1, Math.ceil(c.length / maxPerCol)));
  const maxRows = Math.max(1, ...cols.map((c, i) => Math.ceil(c.length / sub[i])));
  const usableW = Math.max(1, width - pad - padRight);
  const pos = new Map();
  cols.forEach((ids, c) => {
    const x = pad + (c / (nCol - 1)) * usableW;
    const perCol = Math.ceil(ids.length / sub[c]) || 1;
    const rows = Math.min(perCol, ids.length);
    const y0 = (height - (rows - 1) * rowGap) / 2;
    ids.forEach((n, i) => {
      pos.set(n.id, {
        x: x + Math.floor(i / perCol) * 26,
        y: y0 + (i % perCol) * rowGap,
        r: opts.radiusOf ? opts.radiusOf(n) : 4.5,
      });
    });
  });

  const colIdx = new Map(nodes.map((n) => [n.id, colOf(n)]));
  const eout = edges.map((e, i) => {
    const p0 = pos.get(e.src);
    const p1 = pos.get(e.dst);
    if (!p0 || !p1) return null;
    const span = Math.abs((colIdx.get(e.dst) ?? 0) - (colIdx.get(e.src) ?? 0));
    const bez = edgeBezier(p0, p1, { rankSpan: Math.max(1, span), tension: 0.5 });
    return { ...e, idx: i, rankSpan: span, bez, flat: flattenBezier(bez) };
  }).filter(Boolean);

  return {
    variant: "cascade", nodes, edges: eout, pos,
    ranks: { rank: colIdx, byRank: cols.map((c) => c.map((n) => n.id)), maxRank: nCol - 1 },
    order: new Map(nodes.map((n) => [n.id, 0])), crossings: null,
    rankX: cols.map((_, c) => pad + (c / (nCol - 1)) * usableW),
    bounds: { w: width, h: Math.max(height, maxRows * rowGap + 80), maxRows },
    // 영향은 보존량이 아니다 — 화면이 이 사실을 말하지 않으면 리본 폭이 유량으로 읽힌다
    // 열 이름 중 그룹 부분은 엔진이 준 이름 그대로 — 여기서 한글 라벨을 지어내면
    // 그것도 재기술이다. 나머지 다섯은 종류(kind)라 구조적으로 고정이다
    meta: {
      conserved: false,
      columns: ["파라미터", "입력", ...groups, "출력", "기체", "지표"],
    },
  };
}
