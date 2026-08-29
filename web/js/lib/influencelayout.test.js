// 배치 계약 — 층 그림이 층 그림으로 읽히는 데 필요한 성질들.
import test from "node:test";
import assert from "node:assert/strict";

import {
  assignCoords,
  assignRanks,
  arcPrefix,
  crossingCount,
  edgeBezier,
  flattenBezier,
  hitTestNodes,
  layeredLayout,
  orderWithinRanks,
  pointAtArc,
  topoOrder,
} from "./influencelayout.js";

const N = (id, kind, band = "x") => ({ id, kind, band });

// 다이아몬드: 긴 팔 a→b→c→d 와 짧은 팔 a→d
const diamond = {
  nodes: [N("i", "input", "io"), N("a", "ir"), N("b", "ir"), N("c", "ir"), N("d", "ir")],
  edges: [
    { src: "i", dst: "a" }, { src: "a", dst: "b" }, { src: "b", dst: "c" },
    { src: "c", dst: "d" }, { src: "a", dst: "d" },
  ],
};

test("랭크는 최장 경로다 — 최단이면 층이 실행 순서와 어긋난다", () => {
  const { rank } = assignRanks(diamond.nodes, diamond.edges);
  assert.equal(rank.get("d") - rank.get("a"), 3, "짧은 팔이 아니라 긴 팔이 랭크를 정한다");
});

test("파라미터는 0랭크, 입력은 1랭크에 고정", () => {
  const nodes = [N("p", "param", "ap"), N("i", "input", "io"), N("a", "ir")];
  const edges = [{ src: "i", dst: "a" }, { src: "p", dst: "a" }];
  const { rank } = assignRanks(nodes, edges);
  assert.equal(rank.get("p"), 0);
  assert.equal(rank.get("i"), 1);
  assert.equal(rank.get("a"), 2);
});

test("지표가 가장 오른쪽 — 출력 → 기체 → 지표로 이어진다", () => {
  const nodes = [N("i", "input", "io"), N("a", "ir"), N("o", "output", "io"),
    N("sys", "plant", "io"), N("m", "metric", "metric")];
  const edges = [{ src: "i", dst: "a" }, { src: "a", dst: "o" },
    { src: "o", dst: "sys" }, { src: "sys", dst: "m" }];
  const { rank, maxRank } = assignRanks(nodes, edges);
  assert.equal(rank.get("m"), maxRank);
  assert.ok(rank.get("sys") < rank.get("m"));
});

test("모든 IR 간선은 전방이다", () => {
  const { rank } = assignRanks(diamond.nodes, diamond.edges);
  for (const e of diamond.edges) assert.ok(rank.get(e.dst) > rank.get(e.src), JSON.stringify(e));
});

test("순환은 조용히 빠뜨리지 않고 던진다", () => {
  assert.throws(
    () => topoOrder([N("a", "ir"), N("b", "ir")], [{ src: "a", dst: "b" }, { src: "b", dst: "a" }]),
    /순환/,
  );
});

test("교차는 같은 층 쌍끼리만 센다", () => {
  const nodes = [N("a", "input", "io"), N("b", "input", "io"), N("x", "ir"), N("y", "ir")];
  const edges = [{ src: "a", dst: "y" }, { src: "b", dst: "x" }];
  const { rank } = assignRanks(nodes, edges);
  const bad = new Map([["a", 0], ["b", 1], ["x", 0], ["y", 1]]);
  const good = new Map([["a", 0], ["b", 1], ["x", 1], ["y", 0]]);
  assert.equal(crossingCount(edges, bad, rank), 1);
  assert.equal(crossingCount(edges, good, rank), 0);
});

test("바리센터 스윕이 교차를 없앤다", () => {
  const nodes = [N("a", "input", "io"), N("b", "input", "io"), N("x", "ir"), N("y", "ir")];
  const edges = [{ src: "a", dst: "y" }, { src: "b", dst: "x" }];
  const ranks = assignRanks(nodes, edges);
  assert.equal(orderWithinRanks(nodes, edges, ranks).crossings, 0);
});

test("묶음은 층 안에서 연속으로 남는다 — 흐트러지면 '어디까지가 AP인가'가 사라진다", () => {
  const nodes = [
    N("i", "input", "io"),
    N("a1", "ir", "ap"), N("s1", "ir", "scas"), N("a2", "ir", "ap"), N("s2", "ir", "scas"),
  ];
  const edges = ["a1", "s1", "a2", "s2"].map((d) => ({ src: "i", dst: d }));
  const ranks = assignRanks(nodes, edges);
  const { byRank } = orderWithinRanks(nodes, edges, ranks, { keepGroups: true });
  const bandOf = new Map(nodes.map((n) => [n.id, n.band]));
  for (const ids of byRank) {
    const seq = ids.map((id) => bandOf.get(id));
    const runs = seq.filter((b, i) => i === 0 || b !== seq[i - 1]);
    assert.equal(runs.length, new Set(seq).size, `묶음이 쪼개졌다: ${seq}`);
  }
});

test("결정적이다 — 같은 입력이면 같은 그림", () => {
  const a = layeredLayout(diamond, { width: 500, height: 300 });
  const b = layeredLayout(diamond, { width: 500, height: 300 });
  assert.deepEqual([...a.pos.entries()], [...b.pos.entries()]);
});

test("같은 랭크·같은 줄의 노드는 최소 간격을 지킨다", () => {
  const nodes = [N("i", "input", "io"), ...Array.from({ length: 9 }, (_, k) => N(`n${k}`, "ir"))];
  const edges = nodes.slice(1).map((n) => ({ src: "i", dst: n.id }));
  const ranks = assignRanks(nodes, edges);
  const ordered = orderWithinRanks(nodes, edges, ranks);
  const { pos } = assignCoords(nodes, edges, ranks, ordered, { rowGap: 20, height: 400 });
  const ys = nodes.slice(1).map((n) => pos.get(n.id).y).sort((p, q) => p - q);
  for (let i = 1; i < ys.length; i += 1) assert.ok(ys[i] - ys[i - 1] >= 19.999, `${ys}`);
});

test("한 랭크를 여러 줄로 접으면 행 수가 줄고 x가 갈라진다", () => {
  const nodes = [N("i", "input", "io"), ...Array.from({ length: 12 }, (_, k) => N(`p${k}`, "param", "ap"))];
  const edges = nodes.slice(1).map((n) => ({ src: n.id, dst: "i" }));
  const ranks = assignRanks(nodes, edges);
  const ordered = orderWithinRanks(nodes, edges, ranks);
  const flat = assignCoords(nodes, edges, ranks, ordered, { cols: {} });
  const folded = assignCoords(nodes, edges, ranks, ordered, { cols: { 0: 3 } });
  assert.equal(flat.bounds.maxRows, 12);
  assert.equal(folded.bounds.maxRows, 4);
  assert.equal(new Set(nodes.slice(1).map((n) => folded.pos.get(n.id).x)).size, 3);
});

test("퇴화 입력이 NaN을 내지 않는다", () => {
  const one = layeredLayout({ nodes: [N("a", "ir")], edges: [] }, { width: 300, height: 200 });
  for (const p of one.pos.values()) assert.ok(Number.isFinite(p.x) && Number.isFinite(p.y));
  const none = layeredLayout({ nodes: [], edges: [] });
  assert.equal(none.pos.size, 0);
});

test("간선 곡선의 끝점은 정확히 노드에 붙고, 접선은 수평이다", () => {
  const b = edgeBezier({ x: 0, y: 10 }, { x: 100, y: 40 }, { rankSpan: 1 });
  assert.deepEqual([b.x0, b.y0, b.x1, b.y1], [0, 10, 100, 40]);
  assert.equal(b.c1y, 10, "출발 접선이 수평이라야 층 그림으로 읽힌다");
  assert.equal(b.c2y, 40);
  assert.ok(b.c1x > b.x0 && b.c2x < b.x1);
});

test("층을 여럿 건너뛰는 간선만 노드 밭 바깥으로 휜다", () => {
  const near = edgeBezier({ x: 0, y: 0 }, { x: 100, y: 0 }, { rankSpan: 1 });
  const far = edgeBezier({ x: 0, y: 0 }, { x: 100, y: 0 }, { rankSpan: 4 });
  assert.equal(near.c1y - near.y0, 0);
  assert.ok(Math.abs(far.c1y - far.y0) > Math.abs(near.c1y - near.y0));
});

test("호길이 매개변수가 균등하다 — 입자가 곡선에서 느려지지 않는다", () => {
  const flat = flattenBezier(edgeBezier({ x: 0, y: 0 }, { x: 200, y: 120 }, { rankSpan: 4 }), 32);
  const steps = [];
  for (let i = 0; i < 20; i += 1) {
    const a = pointAtArc(flat, i / 20);
    const b = pointAtArc(flat, (i + 1) / 20);
    steps.push(Math.hypot(b.x - a.x, b.y - a.y));
  }
  assert.ok(Math.max(...steps) / Math.min(...steps) < 1.6, `편차 과대: ${steps}`);
  const s0 = pointAtArc(flat, 0);
  const s1 = pointAtArc(flat, 1);
  assert.ok(Math.hypot(s0.x - flat.pts[0].x, s0.y - flat.pts[0].y) < 1e-9);
  assert.ok(Math.hypot(s1.x - flat.pts.at(-1).x, s1.y - flat.pts.at(-1).y) < 1e-9);
});

test("길이 0 곡선도 NaN을 내지 않는다", () => {
  const flat = flattenBezier(edgeBezier({ x: 5, y: 5 }, { x: 5, y: 5 }, { rankSpan: 1 }));
  const p = pointAtArc(flat, 0.5);
  assert.ok(Number.isFinite(p.x) && Number.isFinite(p.y));
});

test("히트테스트는 반경 밖이면 null", () => {
  const pos = new Map([["a", { x: 10, y: 10, r: 5 }], ["b", { x: 60, y: 10, r: 5 }]]);
  assert.equal(hitTestNodes(pos, 11, 11), "a");
  assert.equal(hitTestNodes(pos, 35, 10), null);
});

// 파급 일정 테스트 2건(씨앗=0 · 미도달=null · 간선 방향 단조)은 후계인
// `influenceplay.js`의 conePlayback으로 이관됐다 — 세 성질 모두 그쪽이 승계한다.
// 성운(radial) 전용 테스트 4건(링 반경·각도 평균·각도 벌리기)은 후보 삭제와 함께
// 지워졌다 — 배치가 지워지면 그 계약도 같이 지워지는 것이 이 파일의 규약이다.
test("폭포: 리본 폭은 유량이 아니라고 못박는다", async () => {
  const { cascadeLayout } = await import("./influencelayout.js");
  const L = cascadeLayout(diamond, { width: 600, height: 400 });
  assert.equal(L.meta.conserved, false, "보존량으로 읽히면 화면이 거짓말한다");
  for (const p of L.pos.values()) assert.ok(Number.isFinite(p.x) && Number.isFinite(p.y));
});

test("두 배치가 같은 형태를 낸다 — 렌더러가 하나여야 후보를 지우기 쉽다", async () => {
  const { cascadeLayout } = await import("./influencelayout.js");
  for (const L of [layeredLayout(diamond, {}), cascadeLayout(diamond, {})]) {
    assert.ok(L.pos instanceof Map && Array.isArray(L.edges) && L.bounds && L.ranks, L.variant);
    for (const e of L.edges) {
      assert.ok(Number.isFinite(e.bez.x0) && Number.isFinite(e.bez.y1), L.variant);
      assert.ok(e.flat.cum.length > 1, L.variant);
    }
  }
});

// ── 부분 스트로크 (순차 재생이 간선을 0..s로 자를 때 쓴다) ────────────────

test("arcPrefix: s=0은 아무것도, s=1은 전 표본 — 완성 프레임이 흔들리지 않는다", () => {
  const flat = flattenBezier(edgeBezier({ x: 0, y: 0 }, { x: 200, y: 120 }, { rankSpan: 4 }));
  assert.deepEqual(arcPrefix(flat, 0), { n: 0, last: null });
  assert.deepEqual(arcPrefix(flat, -1), { n: 0, last: null });
  // s=1에서 last가 남으면 마지막 프레임에만 점이 하나 더 찍혀 선 끝이 떤다
  assert.deepEqual(arcPrefix(flat, 1), { n: flat.pts.length, last: null });
  assert.deepEqual(arcPrefix(flat, 2), { n: flat.pts.length, last: null });
});

test("arcPrefix: 끝점은 pointAtArc와 같은 자리 — 선 끝과 입자가 어긋나지 않는다", () => {
  const flat = flattenBezier(edgeBezier({ x: 0, y: 0 }, { x: 300, y: -80 }, { rankSpan: 3 }));
  for (const s of [0.13, 0.5, 0.87]) {
    const { last } = arcPrefix(flat, s);
    const p = pointAtArc(flat, s);
    assert.ok(Math.hypot(last.x - p.x, last.y - p.y) < 1e-9, `s=${s}`);
  }
});

test("arcPrefix: 그려지는 길이가 s에 비례한다 — 등속으로 자란다", () => {
  const flat = flattenBezier(edgeBezier({ x: 0, y: 0 }, { x: 400, y: 200 }, { rankSpan: 4 }));
  const drawn = (s) => {
    const { n, last } = arcPrefix(flat, s);
    let L = 0;
    for (let i = 1; i < n; i += 1) {
      L += Math.hypot(flat.pts[i].x - flat.pts[i - 1].x, flat.pts[i].y - flat.pts[i - 1].y);
    }
    if (last && n > 0) L += Math.hypot(last.x - flat.pts[n - 1].x, last.y - flat.pts[n - 1].y);
    return L;
  };
  // cum을 잘못 읽으면(한 칸 밀림 등) 여기서 계단이 생긴다
  // **첫 마디 안(s ≲ 0.065)을 반드시 밟는다.** 여기를 안 보면 `n = i + 1`을 `n = i`로
  // 바꾸는 오프바이원(= 모든 간선의 성장 첫 65 ms 동안 선이 아예 안 그려진다)이
  // 통과한다 — 다른 s에서는 오차가 0.04 px에 그쳐 허용오차 안에 숨는다
  for (const s of [0.01, 0.04, 0.1, 0.25, 0.4, 0.6, 0.75, 0.9]) {
    assert.ok(Math.abs(drawn(s) - s * flat.len) < 0.5, `s=${s}: ${drawn(s)} vs ${s * flat.len}`);
  }
});

test("arcPrefix: 제자리 간선에서 NaN도 예외도 없다", () => {
  // 주의: 이 곡선의 len은 **정확히 0이 아니라 1.5e-14**다 (3차식 평가의 부동소수 잡음).
  // 그래서 `len > 0` 가드에 안 걸리고 일반 경로를 탄다 — 계약은 "0을 특례로 잡는다"가
  // 아니라 "어느 경로로 가든 유한한 점을 내고 끝점을 벗어나지 않는다"여야 한다
  const flat = flattenBezier(edgeBezier({ x: 5, y: 5 }, { x: 5, y: 5 }, { rankSpan: 1 }));
  assert.deepEqual(arcPrefix(flat, 0), { n: 0, last: null });
  const r = arcPrefix(flat, 0.5);
  assert.ok(Number.isFinite(r.n) && r.n >= 0 && r.n <= flat.pts.length);
  assert.ok(Number.isFinite(r.last.x) && Number.isFinite(r.last.y));
  assert.ok(Math.hypot(r.last.x - 5, r.last.y - 5) < 1e-9, "제자리 간선은 제자리에 머문다");
});

test("간선의 idx는 **모델 간선 인덱스** — 좌표 없는 간선이 빠져도 안 어긋난다", async () => {
  const { cascadeLayout } = await import("./influencelayout.js");
  // 두 번째 간선의 목적지를 배치에 없는 노드로 둔다 → filter(Boolean)에 떨어진다
  const g = {
    nodes: diamond.nodes,
    edges: [diamond.edges[0], { src: "a", dst: "유령" }, ...diamond.edges.slice(1)],
  };
  for (const fn of [layeredLayout, cascadeLayout]) {
    const L = fn(g, { width: 600, height: 400 });
    assert.ok(L.edges.length < g.edges.length, "떨어진 간선이 있어야 이 테스트가 의미 있다");
    for (const e of L.edges) {
      // 자리(위치)로 맞추면 여기서 어긋난다 — 원뿔 판정·재생 일정이 엉뚱한 선을 켠다
      assert.equal(e.src, g.edges[e.idx].src, `${L.variant} idx=${e.idx}`);
      assert.equal(e.dst, g.edges[e.idx].dst, `${L.variant} idx=${e.idx}`);
    }
  }
});
