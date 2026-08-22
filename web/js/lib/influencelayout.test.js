// 배치 계약 — 층 그림이 층 그림으로 읽히는 데 필요한 성질들.
import test from "node:test";
import assert from "node:assert/strict";

import {
  assignCoords,
  assignRanks,
  crossingCount,
  edgeBezier,
  flattenBezier,
  hitTestNodes,
  layeredLayout,
  orderWithinRanks,
  pointAtArc,
  topoOrder,
  wavefrontSchedule,
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

test("파급: 씨앗은 0, 도달 불가는 null(0이 아니다)", () => {
  const nodes = [N("i", "input", "io"), N("a", "ir"), N("b", "ir"), N("z", "ir")];
  const edges = [{ src: "i", dst: "a" }, { src: "a", dst: "b" }, { src: "i", dst: "z" }];
  const ranks = assignRanks(nodes, edges);
  const t = wavefrontSchedule(nodes, edges, ranks, ["a"], { msPerRank: 100 });
  assert.equal(t.get("a"), 0);
  assert.equal(t.get("b"), 100);
  assert.equal(t.get("z"), null, "도달 못 하면 null — 0이면 '동시에 켜졌다'로 읽힌다");
});

test("파급 시각은 간선 방향으로 단조 증가", () => {
  const ranks = assignRanks(diamond.nodes, diamond.edges);
  const t = wavefrontSchedule(diamond.nodes, diamond.edges, ranks, ["a"]);
  for (const e of diamond.edges) {
    if (t.get(e.src) !== null && t.get(e.dst) !== null) {
      assert.ok(t.get(e.dst) >= t.get(e.src), JSON.stringify(e));
    }
  }
});

test("각도 평균은 단위벡터로 — 170°와 −170°의 평균은 180°지 0°가 아니다", async () => {
  const { meanAngle } = await import("./influencelayout.js");
  const d = Math.PI / 180;
  assert.ok(Math.abs(Math.abs(meanAngle([170 * d, -170 * d])) - Math.PI) < 1e-9);
  assert.equal(meanAngle([]), 0);
  assert.ok(Number.isFinite(meanAngle([0, Math.PI])));
});

test("성운: 모든 노드가 자기 랭크의 링 위에 정확히 놓인다", async () => {
  const { radialLayout } = await import("./influencelayout.js");
  const L = radialLayout(diamond, { width: 600, height: 600 });
  const byRank = new Map();
  for (const n of diamond.nodes) {
    const p = L.pos.get(n.id);
    const rr = Math.hypot(p.x - L.center.x, p.y - L.center.y);
    const k = L.ranks.rank.get(n.id);
    if (byRank.has(k)) assert.ok(Math.abs(byRank.get(k) - rr) < 1e-9, `랭크 ${k} 반경 불일치`);
    else byRank.set(k, rr);
  }
  // diamond에는 파라미터(랭크 0)가 없다 — 존재하는 최소·최대 랭크로 방향만 확인한다
  const present = [...byRank.keys()].sort((a, b) => a - b);
  assert.ok(byRank.get(present[0]) > byRank.get(present.at(-1)),
    "바깥일수록 상류 — 파라미터가 바깥 링, 지표가 중심");
});

test("폭포: 리본 폭은 유량이 아니라고 못박는다", async () => {
  const { cascadeLayout } = await import("./influencelayout.js");
  const L = cascadeLayout(diamond, { width: 600, height: 400 });
  assert.equal(L.meta.conserved, false, "보존량으로 읽히면 화면이 거짓말한다");
  for (const p of L.pos.values()) assert.ok(Number.isFinite(p.x) && Number.isFinite(p.y));
});

test("세 배치가 같은 형태를 낸다 — 렌더러가 하나여야 후보를 지우기 쉽다", async () => {
  const { radialLayout, cascadeLayout } = await import("./influencelayout.js");
  for (const L of [layeredLayout(diamond, {}), radialLayout(diamond, {}), cascadeLayout(diamond, {})]) {
    assert.ok(L.pos instanceof Map && Array.isArray(L.edges) && L.bounds && L.ranks, L.variant);
    for (const e of L.edges) {
      assert.ok(Number.isFinite(e.bez.x0) && Number.isFinite(e.bez.y1), L.variant);
      assert.ok(e.flat.cum.length > 1, L.variant);
    }
  }
});

test("같은 링의 각도는 최소 간격만큼 벌어진다 — 안 벌리면 지표가 한 점에 겹친다", async () => {
  const { spreadAngles } = await import("./influencelayout.js");
  const a = new Map([["m1", 1], ["m2", 1], ["m3", 1]]);
  spreadAngles(["m1", "m2", "m3"], a, 0.2);
  const vs = [a.get("m1"), a.get("m2"), a.get("m3")].sort((x, y) => x - y);
  assert.ok(vs[1] - vs[0] >= 0.199 && vs[2] - vs[1] >= 0.199, `${vs}`);
  assert.ok(Math.abs((vs[0] + vs[2]) / 2 - 1) < 1e-9, "가운데는 원래 자리에 남는다");
});

test("이미 충분히 벌어져 있으면 건드리지 않는다 — 바리센터 순서를 되돌리지 않는다", async () => {
  const { spreadAngles } = await import("./influencelayout.js");
  const a = new Map([["x", 0], ["y", 1], ["z", 2]]);
  spreadAngles(["x", "y", "z"], a, 0.2);
  assert.deepEqual([a.get("x"), a.get("y"), a.get("z")], [0, 1, 2]);
});
