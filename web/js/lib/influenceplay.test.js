import assert from "node:assert/strict";
import test from "node:test";

import { assignRanks } from "./influencelayout.js";
import { PLAY, captionAt, conePlayback, cycleAt, graphDepth, summaryOf } from "./influenceplay.js";

const N = (id, kind, extra = {}) => ({ id, kind, band: "x", ...extra });

/** 실제 payload를 축소한 모형 — 파라미터 → IR 2단 → 출력 → 기체 → 지표 2개.
 *  `q`는 원뿔 **밖** IR 노드(들어오는 간선이 없어 랭크 0). */
const model = {
  nodes: [
    N("param:p", "param"), N("q", "ir"), N("a", "ir", { n_reach: 4 }),
    N("b", "ir", { n_reach: 3 }), N("out:x", "output"), N("sys:plant", "plant"),
    N("metric:m1", "metric"), N("metric:m2", "metric"),
  ],
  edges: [
    { src: "param:p", dst: "a", kind: "param" }, //          0
    { src: "a", dst: "b", kind: "ir" }, //                   1
    { src: "b", dst: "out:x", kind: "ir" }, //               2
    { src: "out:x", dst: "sys:plant", kind: "boundary" }, // 3
    { src: "sys:plant", dst: "metric:m1", kind: "declared" }, // 4
    { src: "sys:plant", dst: "metric:m2", kind: "declared" }, // 5
    { src: "q", dst: "b", kind: "ir" }, //                   6  원뿔 밖
  ],
};
const cone = {
  nodes: new Set(["param:p", "a", "b", "out:x", "sys:plant", "metric:m1", "metric:m2"]),
  seeds: new Set(["a"]),
  edges: new Set([0, 1, 2, 3, 4, 5]),
};
const play = () => conePlayback(model, cone);

test("고른 파라미터는 at=0 — 씨앗은 파라미터 간선이 다 자란 뒤에 켜진다", () => {
  const p = play();
  assert.deepEqual(p.nodes.get("param:p"), { at: 0, layer: -1 });
  // 씨앗을 0으로 두면 param→a 선이 자라기도 전에 a가 켜져 허공에 매달린 선이 된다
  assert.equal(p.nodes.get("a").at, PLAY.growMs);
});

test("원뿔 밖은 null이지 0이 아니다 — 0이면 '동시에 켜졌다'로 읽힌다", () => {
  const p = play();
  assert.equal(p.nodes.get("q"), null);
  assert.equal(p.edges.get(6), null);
  // 전 노드·전 간선이 키로 들어 있어야 소비처가 has/get을 나눠 쓰지 않는다
  assert.equal(p.nodes.size, model.nodes.length);
  assert.equal(p.edges.size, model.edges.length);
});

test("층 슬롯은 강하게 증가하고, 같은 층 간선은 슬롯 안에서 어긋난다", () => {
  const p = play();
  for (let k = 1; k < p.layers.length; k += 1) {
    assert.ok(p.layers[k].t0 > p.layers[k - 1].t0, `층 ${k}`);
  }
  const last = p.layers.at(-1); // 지표 2개가 도착하는 층
  assert.equal(last.edges.length, 2);
  const [e0, e1] = last.edges.map((i) => p.edges.get(i));
  assert.equal(e0.t0, last.t0);
  assert.equal(e1.t0 - e0.t0, PLAY.staggerMs, "간선 2개면 정확히 시차 한 칸");
  assert.ok(e1.t0 - last.t0 <= PLAY.spreadMax);
});

test("노드는 **첫** 도착 간선이 다 자란 뒤 켜진다 (max나 랭크 시각이면 실패)", () => {
  // b로 두 갈래가 들어오되 하나가 훨씬 늦은 그래프 — min이어야 이른 쪽에서 켜진다
  const m = {
    nodes: [N("param:p", "param"), N("a", "ir"), N("c", "ir"), N("d", "ir"), N("b", "ir")],
    edges: [
      { src: "param:p", dst: "a" }, { src: "param:p", dst: "c" },
      { src: "c", dst: "d" }, { src: "a", dst: "b" }, { src: "d", dst: "b" },
    ],
  };
  const c = {
    nodes: new Set(["param:p", "a", "c", "d", "b"]), seeds: new Set(["a", "c"]),
    edges: new Set([0, 1, 2, 3, 4]),
  };
  const p = conePlayback(m, c);
  const arrivals = [3, 4].map((i) => p.edges.get(i).t1);
  assert.equal(p.nodes.get("b").at, Math.min(...arrivals));
  assert.ok(Math.max(...arrivals) > Math.min(...arrivals), "두 도착 시각이 달라야 의미 있다");
});

test("겹침 상한 — 어두운 노드에서 선이 나가는 폭이 성장 시간을 넘지 않는다", () => {
  // 인접 층이 겹치는 것은 설계다(엄격 직렬화는 16층에 4.8 s). 다만 소스가 켜지기
  // 전에 나가는 선이 **다 자라 버리는** 것은 인과가 뒤집힌 것이라 막아야 한다
  const p = play();
  let overlapped = 0;
  for (const [i, v] of p.edges) {
    if (v === null) continue;
    const src = p.nodes.get(model.edges[i].src);
    assert.ok(src !== null && src.at <= v.t1, `간선 ${i}: src.at=${src?.at} t1=${v.t1}`);
    if (src.at > v.t0) overlapped += 1; // 소스가 켜지기 전에 출발한 간선
  }
  // 겹침이 하나도 없으면 직렬화된 것이고, 그러면 16층에 4.8 s가 걸려 요구와 어긋난다.
  // (`src.at <= v.t0 + growMs`는 t1 = t0 + growMs라 위 단정과 같은 부등식이라 뺐다)
  assert.ok(overlapped > 0, "인접 층 겹침은 설계다 — 0이면 슬롯 간격이 성장 시간을 넘었다");
});

test("층 안 시차가 폭주하지 않는다 — 간선이 많아지면 자동으로 촘촘해진다", () => {
  const nodes = [N("param:p", "param"), N("s", "ir")];
  const edges = [{ src: "param:p", dst: "s" }];
  for (let i = 0; i < 50; i += 1) {
    nodes.push(N(`t${i}`, "ir"));
    edges.push({ src: "s", dst: `t${i}` });
  }
  const p = conePlayback(
    { nodes, edges },
    { nodes: new Set(nodes.map((n) => n.id)), seeds: new Set(["s"]),
      edges: new Set(edges.map((_, i) => i)) },
  );
  const wide = p.layers.at(-1);
  assert.equal(wide.edges.length, 50);
  const t0s = wide.edges.map((i) => p.edges.get(i).t0);
  // 30 ms × 49 = 1470 ms가 그냥 더해지면 이 층 하나가 총 재생을 먹는다
  assert.ok(Math.max(...t0s) - Math.min(...t0s) <= PLAY.spreadMax, `${Math.max(...t0s)}`);
});

test("총 재생에 상한이 있다 — 층이 100개여도 넘지 않는다", () => {
  const nodes = [N("param:p", "param")];
  const edges = [];
  for (let i = 0; i < 100; i += 1) {
    nodes.push(N(`n${i}`, "ir"));
    edges.push({ src: i === 0 ? "param:p" : `n${i - 1}`, dst: `n${i}` });
  }
  const p = conePlayback(
    { nodes, edges },
    { nodes: new Set(nodes.map((n) => n.id)), seeds: new Set(["n0"]),
      edges: new Set(edges.map((_, i) => i)) },
  );
  assert.equal(p.nLayer, 100);
  assert.ok(p.playMs <= PLAY.maxPlayMs, `${p.playMs}`);
});

test("빈 원뿔(그래프에 방출 안 되는 상수) — 던지지 않고 재생 길이 0", () => {
  const p = conePlayback(model, { nodes: new Set(["param:p"]), seeds: new Set(), edges: new Set() });
  assert.equal(p.playMs, 0);
  assert.equal(p.nLayer, 0);
  assert.deepEqual(p.nodes.get("param:p"), { at: 0, layer: -1 });
  assert.equal(p.nodes.get("a"), null);
  assert.match(captionAt(p, 0), /번질 곳이 없다/);
  // 층 수를 모르면 자막이 "층 ?/0"이 된다 — 빈 원뿔에서도 전체 층 수는 안다
  assert.ok(p.maxRank > 0);
});

test("결정적 — 같은 입력이면 같은 일정 (Math.random 금지)", () => {
  const a = play();
  const b = play();
  assert.deepEqual([...a.edges], [...b.edges]);
  assert.deepEqual([...a.nodes], [...b.nodes]);
  assert.deepEqual(a.layers, b.layers);
});

test("시간축이 **위상 랭크**다 — 배치의 열 인덱스를 쓰면 깨지는 자리", () => {
  const p = play();
  const ranks = assignRanks(model.nodes, model.edges);
  // 층의 rank가 assignRanks와 일치해야 "층 번호 = IR 실행 순서"라는 주장이 성립한다.
  // cascadeLayout의 ranks(모듈 밴드 열 인덱스)를 넣으면 여기서 어긋난다
  for (const L of p.layers) {
    for (const i of L.edges) {
      assert.equal(ranks.rank.get(model.edges[i].dst), L.rank, `간선 ${i}`);
    }
  }
  assert.equal(p.maxRank, ranks.maxRank);
});

test("cycleAt: 유지 구간에서 t가 playMs에 고정된다 — 완성된 원뿔이 그대로 켜져 있다", () => {
  const cfg = { playMs: 1000, holdMs: 2000, fadeMs: 300 };
  assert.equal(cycleAt(0, cfg).t, 0);
  assert.equal(cycleAt(500, cfg).t, 500);
  assert.equal(cycleAt(1000, cfg).t, 1000);
  assert.equal(cycleAt(2000, cfg).t, 1000, "유지 구간");
  assert.equal(cycleAt(2900, cfg).t, 1000, "유지 구간 끝");
  assert.equal(cycleAt(3000, cfg).t, 0, "되감김");
  assert.equal(cycleAt(3500, cfg).cycle, 1);
});

test("cycleAt: 되감기 직전에만 페이드 — 재생 구간을 먹지 않는다", () => {
  const cfg = { playMs: 1000, holdMs: 2000, fadeMs: 300 };
  assert.equal(cycleAt(0, cfg).fade, 1);
  assert.equal(cycleAt(1500, cfg).fade, 1);
  assert.equal(cycleAt(2700, cfg).fade, 1);
  assert.ok(cycleAt(2850, cfg).fade < 0.6 && cycleAt(2850, cfg).fade > 0.4);
  assert.ok(cycleAt(2999, cfg).fade < 0.01);
  // holdMs가 페이드보다 짧으면 페이드가 **재생 구간을 갉아먹는다** → 페이드를 줄인다.
  // 이걸 유지 구간에서만 보면 fade ∈ (0,1]이라 무조건 참이 되어 클램프를 지워도 통과한다.
  // 클램프가 사라지면 실제로 무슨 일이 나는지는 **재생 중간**에서 드러난다
  const tightCfg = { playMs: 1000, holdMs: 100, fadeMs: 900 };
  assert.equal(cycleAt(500, tightCfg).fade, 1, "재생 중간은 페이드가 닿으면 안 된다");
  assert.equal(cycleAt(1050, tightCfg).t, 1000);
});

test("cycleAt: loop=false·재생 없음·비유한 경과는 완료 상태로 착지 (동작 축소 경로)", () => {
  const cfg = { playMs: 1000, holdMs: 2000 };
  // u = Infinity라야 수명 있는 표현(도착 펄스·hot)이 완료 착지에서 전부 꺼진다
  assert.deepEqual(cycleAt(99999, { ...cfg, loop: false }), { t: 1000, u: Infinity, fade: 1, cycle: 0 });
  assert.deepEqual(cycleAt(500, { playMs: 0, holdMs: 2000 }), { t: 0, u: Infinity, fade: 1, cycle: 0 });
  assert.equal(cycleAt(NaN, cfg).t, 1000);
  assert.equal(cycleAt(-5, cfg).t, 0, "음수 경과는 시작으로");
});

test("자막: 재생 중에는 절대 층 번호, 끝나면 요약으로 바뀐다", () => {
  const p = play();
  const label = (id) => id;
  assert.match(captionAt(p, 0, label), /^층 2\/6 · a 도달$/);
  assert.match(captionAt(p, p.layers[2].t0, label), /^층 4\/6 · out:x 도달$/);
  assert.equal(captionAt(p, p.playMs, label), summaryOf(p, label));
  // 층 안에 여러 노드가 도착하면 사람이 알아보는 종류부터 (출력 > 지표 > 기체 > IR)
  assert.match(captionAt(p, p.layers.at(-1).t0, label), /metric:m1/);
});

test("요약 세 갈래 — 출력 도달 / 법칙 밖 / 출력 미도달이 서로 다른 문장", () => {
  assert.equal(summaryOf(play(), (id) => id),
    "층 2에서 시작해 층 4에서 out:x 도달 · 6층 중 5층 통과");

  // 법칙 밖: param → 기체 직행 (IR 층을 지나지 않는다)
  const off = {
    nodes: [N("param:n", "param"), N("sys:plant", "plant"), N("metric:m", "metric")],
    edges: [{ src: "param:n", dst: "sys:plant" }, { src: "sys:plant", dst: "metric:m" }],
  };
  const offP = conePlayback(off, {
    nodes: new Set(["param:n", "sys:plant", "metric:m"]), seeds: new Set(),
    edges: new Set([0, 1]),
  });
  // startRank를 쓰면 "층 5에서 시작해 기체까지"가 되는데 기체가 바로 그 층이다(동어반복)
  assert.match(summaryOf(offP), /곧장 기체로 간다/);
  assert.doesNotMatch(summaryOf(offP), /에서 시작/);

  // 출력 미도달: IR 안에서 끊긴다
  const stop = {
    nodes: [N("param:p", "param"), N("a", "ir"), N("b", "ir")],
    edges: [{ src: "param:p", dst: "a" }, { src: "a", dst: "b" }],
  };
  const stopP = conePlayback(stop, {
    nodes: new Set(["param:p", "a", "b"]), seeds: new Set(["a"]), edges: new Set([0, 1]),
  });
  assert.match(summaryOf(stopP), /멈춘다/);
  assert.doesNotMatch(summaryOf(stopP), /도달/);
});

test("graphDepth: 자막·배치 설명이 쓰는 층 수는 재생 일정과 같은 수다", () => {
  // 두 곳이 각각 세면 엔진이 노드를 하나 늘렸을 때 한쪽만 조용히 어긋난다
  assert.equal(graphDepth(model), conePlayback(model, cone).maxRank + 1);
  assert.equal(graphDepth(model), 6); // param0 · a1 · b2 · out3 · plant4 · metric5
});

test("cycleAt: u는 클램프하지 않는다 — 도착 펄스가 마지막 층에서도 뜨고 유지 구간엔 꺼진다", () => {
  const cfg = { playMs: 1000, holdMs: 2000, fadeMs: 300 };
  // playMs가 곧 **마지막 도착 시각**이다(playMs = max t1 = 마지막 노드의 at).
  // t로 재면 `t < playMs`는 마지막 펄스를 통째로 삼키고, `t <= playMs`는 유지 구간
  // 내내 age≈0으로 얼어붙는다. u만이 둘 다 피한다
  assert.equal(cycleAt(1000, cfg).t, 1000);
  assert.equal(cycleAt(1000, cfg).u, 1000, "완료 순간: age 0 → 마지막 펄스가 터진다");
  assert.equal(cycleAt(1200, cfg).u, 1200, "완료 200 ms 뒤: 펄스가 감쇠 중");
  assert.equal(cycleAt(2500, cfg).u, 2500, "유지 한복판: 어떤 수명도 남지 않는다");
  assert.equal(cycleAt(2500, cfg).t, 1000, "그동안 t는 고정 — 원뿔은 켜진 채다");
  // 되감기 뒤 u가 0으로 돌아오지 않으면 age가 영원히 커져 **두 번째 주기부터**
  // 도착 펄스와 헤일로 플레어가 영영 안 뜬다. 기본 동작이 무한 반복이므로
  // 사용자가 보는 시간의 대부분이 그 상태다 — 주기 안 지점만 재면 안 걸린다
  assert.equal(cycleAt(3100, cfg).u, 100, "다음 주기에서도 펄스가 다시 터진다");
  assert.equal(cycleAt(3100, cfg).cycle, 1);
});
