/** 영향성 원뿔의 순차 재생 일정 — 벽시계 경과 → 무엇이 얼마나 그려졌나. 순수 함수.

`lib/playback.js`(시뮬 재생)와 같은 자리의 모듈이다: 시간 계산을 뷰에서 떼어내
캔버스는 "받은 진행도대로 긋기"만 하게 한다. 기하는 `influencelayout.js`, **시간은 여기**.

**시간축을 기하에서 분리한 것이 이 모듈의 요지다.** 배치가 준 `layout.ranks`를 쓰지
않는다 — `cascadeLayout`의 ranks는 위상 랭크가 아니라 **모듈 밴드의 열 인덱스**라
간선 방향으로 단조가 아니고, 그걸 시간으로 쓰면 간선이 거꾸로 자란다. 여기서
`assignRanks`를 직접 돌려 **IR 실행 순서**로만 시각을 매기므로 두 배치(A·B)가 같은
재생을 낸다 — 뷰의 전파 경로 패널이 배치와 무관하게 같은 층 칩을 켜는 근거이기도 하다.

층 슬롯이 성립하는 근거: 엔진이 내는 간선의 목적지는 전부 IR 노드·출력·기체·지표이고
**파라미터나 입력을 목적지로 삼는 간선이 하나도 없다.** 그래서 `assignRanks`의
`PINNED` 예외가 발동할 수 없고 모든 간선에서 랭크가 강하게 증가한다.

인접 층은 **겹친다(설계다)**. 16층을 2.5 s에 통과하려면 층 간격이 150 ms인데 간선
성장이 180 ms라 k층이 다 자라기 전에 k+1층이 출발한다. 엄격한 직렬화는 총 4.8 s가
되어 요구와 양립하지 않는다 — 대신 출발 **순서**는 층 순서로 엄격하고, 캔버스가
노드 점등을 램프로 처리해 "어두운 노드에서 선이 나가는" 장면을 없앤다.
*/

import { assignRanks } from "./influencelayout.js";

export const PLAY = {
  stepMs: 150, // 층 슬롯 간격 — 16층 × 150 = 2250 ms
  growMs: 180, // 간선 하나가 자라는 시간
  staggerMs: 30, // 층 안 시차
  spreadMax: 120, // 한 층의 시차 **총량** 상한 (0.8 × step) — 간선 많은 층이 슬롯을 넘지 않게
  maxPlayMs: 4000, // 총 재생 상한 — 층 수가 늘어도 폭주 금지
  holdMs: 3800, // 완성 유지 구간
  fadeMs: 350, // 되감기 페이드아웃
};

// 층 자막에 세울 노드의 우선순위 — 사람이 알아보는 이름부터
const HEAD_RANK = { output: 0, metric: 1, plant: 2, ghost: 3, ir: 4, input: 5, param: 6 };

/** 그래프가 몇 층인가 — 재생·자막·배치 설명이 **같은 수**를 쓰게 하는 한 자리.
 *
 * 웹이 "16층" 같은 수를 문구에 박아 두면 엔진이 노드를 하나 늘리는 순간 화면이
 * 조용히 거짓말한다(02 §5.5). 층 수는 그래프에서 나오는 것이지 적어 두는 것이 아니다.
 * 파라미터·입력·출력·기체·지표까지 포함한 **화면에 그려지는 열 수**다 — 사용자가
 * 캔버스에서 실제로 셀 수 있는 수와 같아야 자막의 「층 4/21」이 검증 가능해진다.
 */
export function graphDepth(model) {
  return assignRanks(model.nodes, model.edges).maxRank + 1;
}

/** 원뿔 하나의 재생 일정.
 *
 * 반환 맵은 **전 노드·전 간선을 담고 원뿔 밖은 `null`**이다 — 0으로 두면 "동시에
 * 켜졌다"로 읽힌다(미계측과 실제 0을 섞지 않는다는 이 화면의 규약).
 */
export function conePlayback(model, cone, opts = {}) {
  const o = { ...PLAY, ...opts };
  const { nodes, edges } = model;
  const ranks = assignRanks(nodes, edges);
  const edgeAt = new Map(edges.map((_, i) => [i, null]));
  const nodeAt = new Map(nodes.map((n) => [n.id, null]));

  if (!cone || !cone.edges?.size) {
    // 그래프에 방출되지 않는 상수 — 번질 곳이 없다. 고른 파라미터만 켜 둔다.
    // 전체 층 수(maxRank)는 그대로 내준다: 모르면 자막이 「층 ?/0」이 된다
    if (cone) for (const id of cone.nodes) if (nodeAt.has(id)) nodeAt.set(id, { at: 0, layer: -1 });
    return {
      edges: edgeAt, nodes: nodeAt, layers: [], playMs: 0, nLayer: 0,
      maxRank: ranks.maxRank, startRank: null, endRank: null,
      firstOutput: null, reachesPlant: false,
    };
  }

  const kindOf = new Map(nodes.map((n) => [n.id, n.kind]));
  const reachOf = new Map(nodes.map((n) => [n.id, n.n_reach ?? 0]));
  // 선언 순서 = IR 선언 순서(서버가 위상 순서로 보낸다). 층 **안**의 순서를 좌표가
  // 아니라 이걸로 정하는 이유: 좌표로 정렬하면 배치마다 순서가 달라져 "애니메이션이
  // 곧 생성 C 문장 순서"라는 이 탭의 주장이 층 안에서 깨진다
  const declIdx = new Map(nodes.map((n, i) => [n.id, i]));

  const byRank = new Map();
  for (const i of cone.edges) {
    const e = edges[i];
    if (!e) continue;
    const r = ranks.rank.get(e.dst) ?? 0;
    if (!byRank.has(r)) byRank.set(r, []);
    byRank.get(r).push(i);
  }
  // 점유한 랭크만 슬롯에 배정한다 — 빈 층을 건너뛰므로 씨앗이 층 6인 파라미터도
  // t=0에 바로 출발한다. 자막·요약은 **절대 층 번호**를 쓰므로 "층 3에서 시작"은 그대로 성립
  const occupied = [...byRank.keys()].sort((a, b) => a - b);
  const K = occupied.length;
  const step = K > 1
    ? Math.min(o.stepMs, Math.max(0, o.maxPlayMs - o.growMs - o.spreadMax) / (K - 1))
    : o.stepMs;

  const layers = [];
  let playMs = 0;
  occupied.forEach((rank, k) => {
    const list = byRank.get(rank);
    list.sort((a, b) =>
      (declIdx.get(edges[a].dst) ?? 0) - (declIdx.get(edges[b].dst) ?? 0)
      || (declIdx.get(edges[a].src) ?? 0) - (declIdx.get(edges[b].src) ?? 0)
      || a - b);
    const m = list.length;
    // 시차 **총량**에 상한을 건다. 간선마다 30 ms를 그냥 더하면 간선 50개짜리 층
    // 하나가 1.5 s를 먹어 총 재생이 폭주한다 — 층이 커지면 자동으로 촘촘해진다
    const spread = Math.min((m - 1) * o.staggerMs, o.spreadMax);
    const slot = k * step;
    list.forEach((i, j) => {
      const t0 = slot + (m > 1 ? (j / (m - 1)) * spread : 0);
      const t1 = t0 + o.growMs;
      edgeAt.set(i, { t0, t1, layer: k });
      if (t1 > playMs) playMs = t1;
      // 노드 점등 = **첫** 도착 간선의 성장 완료. max로 두면 선이 눈에 보이게 닿았는데도
      // 노드가 어두운 채 남고, 랭크 시각으로 두면 반대로 선이 자라는 중에 노드가 먼저
      // 켜져 허공에 매달린 선이 된다
      const dst = edges[i].dst;
      const prev = nodeAt.get(dst);
      if (nodeAt.has(dst) && (prev === null || t1 < prev.at)) nodeAt.set(dst, { at: t1, layer: k });
    });
    layers.push({ rank, t0: slot, spread, edges: list, arrive: [], headline: null });
  });

  // 들어오는 원뿔 간선이 없는 원뿔 노드 = 고른 파라미터 자신(간선의 목적지가 될 수
  // 없다). 고른 순간 켜져 있어야 하므로 0
  for (const id of cone.nodes) {
    if (nodeAt.has(id) && nodeAt.get(id) === null) nodeAt.set(id, { at: 0, layer: -1 });
  }

  for (const [id, v] of nodeAt) {
    if (v === null || v.layer < 0) continue;
    layers[v.layer].arrive.push(id);
  }
  for (const L of layers) {
    L.arrive.sort((a, b) =>
      (HEAD_RANK[kindOf.get(a)] ?? 9) - (HEAD_RANK[kindOf.get(b)] ?? 9)
      || (reachOf.get(b) ?? 0) - (reachOf.get(a) ?? 0)
      || (declIdx.get(a) ?? 0) - (declIdx.get(b) ?? 0));
    L.headline = L.arrive[0] ?? null;
  }

  // 요약이 가리킬 층은 **첫 법칙 출력이 도착한 층**이다. 마지막 층은 어느 파라미터든
  // 지표라, 마지막을 쓰면 "지표 도달"만 나와 정보가 0이 된다
  let firstOutput = null;
  for (const [id, v] of nodeAt) {
    if (v === null || kindOf.get(id) !== "output") continue;
    if (!firstOutput || v.at < firstOutput.at) {
      firstOutput = { id, at: v.at, rank: ranks.rank.get(id) ?? 0 };
    }
  }

  return {
    edges: edgeAt,
    nodes: nodeAt,
    layers,
    playMs,
    nLayer: K,
    maxRank: ranks.maxRank,
    startRank: occupied[0],
    endRank: occupied[K - 1],
    firstOutput,
    reachesPlant: (nodeAt.get("sys:plant") ?? null) !== null,
  };
}

/** 벽시계 경과 → 재생 위치. 프레임을 세지 않는다 (앵커 하나 + 매 프레임 차분).
 *
 * 유지 구간에서 `t`가 `playMs`에 **고정**되므로 완성된 원뿔이 그대로 켜져 있다.
 * `fade`는 주기 끝에서 1→0 — 「완성」에서 「암흑」으로 툭 끊기면 계속 움직이는
 * 화면보다 **더** 시선을 뺏는다.
 *
 * `u`는 **클램프하지 않은** 주기 내 위치다. `t`만으로는 "방금 다 그렸다"와 "3초째
 * 유지 중"이 구분되지 않아, 도착 펄스처럼 수명이 있는 표현이 마지막 층에서 아예
 * 못 뜨거나(t < playMs로 끊으면) 유지 구간 내내 얼어붙는다(안 끊으면).
 */
export function cycleAt(elapsed, opts = {}) {
  const { playMs = 0, holdMs = PLAY.holdMs, fadeMs = PLAY.fadeMs, loop = true } = opts;
  // 완료 착지 — u = Infinity라 수명 있는 표현(도착 펄스·hot)이 전부 꺼진다
  const done = { t: Math.max(0, playMs), u: Infinity, fade: 1, cycle: 0 };
  const total = playMs + holdMs;
  if (!loop || !(playMs > 0) || !(total > 0) || !Number.isFinite(elapsed)) return done;
  const e = Math.max(0, elapsed);
  const cycle = Math.floor(e / total);
  const u = e - cycle * total;
  // 페이드가 재생 구간을 먹지 않게 — 유지가 짧으면 페이드도 같이 짧아진다
  const fw = Math.max(0, Math.min(fadeMs, holdMs));
  const fade = fw > 0 && u > total - fw ? Math.max(0, (total - u) / fw) : 1;
  return { t: Math.min(u, playMs), u, fade, cycle };
}

/** 재생 위치 t가 가리키는 층 인덱스 — 자막(captionAt)과 뷰의 경로 패널(onLayer)이
 * **같은 판정**을 써야 칩과 자막이 어긋나지 않는다. 판정을 각자 복제하면 경계
 * (`>=` vs `>`, 완료 문턱)가 어긋나도 화면은 계속 그럴듯해서 아무도 못 알아챈다.
 *
 * 반환: 0..K-1 = 그 층이 자라는 중, K(=layers.length) = 완료(요약 구간). 빈 재생
 * (nLayer 0)도 K=0으로 곧장 완료다. play가 없으면 null — "재생 없음"은 층이 아니다.
 */
export function layerIndexAt(play, t) {
  if (!play) return null;
  if (play.nLayer === 0 || t >= play.playMs) return play.layers.length;
  let li = 0;
  for (let i = 0; i < play.layers.length; i += 1) if (play.layers[i].t0 <= t) li = i;
  return li;
}

/** 재생 중 한 줄 — 「층 7/16 · limiter_active 도달」. 완료 후에는 요약으로 바뀐다. */
export function captionAt(play, t, labelOf = (id) => id) {
  if (!play || play.nLayer === 0) return "번질 곳이 없다 — 이 상수는 그래프에 방출되지 않는다";
  const li = layerIndexAt(play, t);
  if (li >= play.layers.length) return summaryOf(play, labelOf);
  const cur = play.layers[li];
  const where = `층 ${cur.rank + 1}/${play.maxRank + 1}`;
  return cur.headline ? `${where} · ${labelOf(cur.headline)} 도달` : `${where} · 노드 ${cur.arrive.length}개`;
}

/** 완료 요약 — 재생이 끝난 뒤 남는 문장. 세 갈래로 갈린다. */
export function summaryOf(play, labelOf = (id) => id) {
  if (!play || play.nLayer === 0) return "번질 곳이 없다 — 이 상수는 그래프에 방출되지 않는다";
  const of = play.maxRank + 1;
  const start = play.startRank + 1;
  const passed = `${of}층 중 ${play.nLayer}층 통과`;
  if (play.firstOutput) {
    return `층 ${start}에서 시작해 층 ${play.firstOutput.rank + 1}에서 `
      + `${labelOf(play.firstOutput.id)} 도달 · ${passed}`;
  }
  // 법칙 밖 — IR을 통째로 건너뛰고 기체로 직행한다.
  // 여기서 startRank를 쓰면 안 된다: 원뿔의 첫 간선이 param→기체라 startRank가 곧
  // **기체 자신의 층**이고, "층 20에서 시작해 기체까지"라는 동어반복이 나온다
  if (play.reachesPlant) {
    return `제어법칙 층을 하나도 지나지 않고 곧장 기체로 간다 — ${of}층 중 0층 통과. `
      + "개루프로는 보이지 않고 폐루프 스윕에서만 드러난다";
  }
  return `층 ${start}에서 시작해 층 ${play.endRank + 1}에서 멈춘다 · ${passed}`;
}
