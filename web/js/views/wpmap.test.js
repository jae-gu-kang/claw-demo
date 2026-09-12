/** 웨이포인트 지도 뷰 — **무엇을 그리기로 하는가**의 검증 (픽셀이 아니라 결정).
 *
 * `js/views/`가 무검증 16,800줄이던 자리의 첫 조각이다. 여기를 먼저 고른 이유:
 * 이 파일에는 lib으로 뺄 수 없는 **판단이 실제로 남아 있다** — 미리보기를 그릴지,
 * 못 나는 꺾임에 고리를 칠지, 도달반경 원을 점선으로 낼지. 판단이 lib에 있는 뷰
 * (`stage.js`가 그렇게 적어 둔다)는 시험할 것이 뷰 쪽에 없다.
 *
 * 가짜 DOM·기록 캔버스는 `testdom.js`. 픽셀을 견주지 않고 "그 색으로 stroke가
 * 일어났는가 · 경로에 점이 몇 개인가"를 묻는다.
 */
import test from "node:test";
import assert from "node:assert/strict";

import { canvasIn, installDom, opsOf, strokesOf } from "./testdom.js";

installDom(); // **import보다 먼저** — makeCanvas가 모듈 로드 시 window를 읽는다
const { createWpMap } = await import("./wpmap.js");

// 뷰가 쓰는 색 — 여기 적어 두는 것이 곧 "색이 뜻을 가진다"는 계약의 고정이다.
// 바꾸면 이 테스트가 먼저 빨개지고, 그때 캡션(범례)도 같이 고쳐야 한다.
const PLAN = "rgba(255, 149, 0, .55)"; // 주황 점선 — 찍은 순서
const FLY = "rgba(52, 199, 89, .9)"; // 초록 실선 — 실제로 날 경로
const TIGHT = "rgba(255, 59, 48, .95)"; // 빨간 고리 — 계획대로 못 나는 꺾임
const ACCEPT = "#ff9500"; // 도달반경 원

const row = (n, e, d = "") => ({ n: String(n), e: String(e), d });

/** 지도 하나 — 기본은 미리보기 없음(getFlyable 미지정). */
function mount({ rows, flyable = null, accept = 300 } = {}) {
  const map = createWpMap({
    getRows: () => rows,
    getAcceptRadius: () => accept,
    getTrack: () => null,
    getFlyable: flyable === null ? undefined : () => flyable,
    onRowsChanged: () => {},
    onSelect: () => {},
    viewRef: { view: null },
  });
  const canvas = canvasIn(map.root);
  assert.ok(canvas, "지도가 캔버스를 만들지 않았다");
  return { map, canvas };
}

test("계획 점선은 원점에서 출발해 웨이포인트를 순서대로 잇는다", () => {
  const rows = [row(3000, 0), row(3000, 3000)];
  const { canvas } = mount({ rows });
  const plan = strokesOf(canvas, PLAN);
  assert.equal(plan.length, 1, "계획선은 한 번에 그린다");
  // 원점 + WP 2개 = 점 3개. 출발점을 빼먹으면 발사대에서 첫 점까지가 화면에서 사라진다
  assert.equal(plan[0].path.length, 3);
  assert.equal(plan[0].path[0].op, "move", "첫 점은 moveTo(원점)");
  assert.deepEqual(plan[0].dash, [5, 4], "계획선은 점선이다 — 실선이면 실제 경로로 읽힌다");
});

test("미리보기를 안 주면 초록 선을 그리지 않는다 — 없는 것을 지어내지 않는다", () => {
  const { canvas } = mount({ rows: [row(3000, 0), row(3000, 3000)] });
  assert.equal(strokesOf(canvas, FLY).length, 0);
  assert.equal(strokesOf(canvas, TIGHT).length, 0);
  // 계획선은 그대로 있다 — 미리보기 부재가 지도를 비우지 않는다
  assert.equal(strokesOf(canvas, PLAN).length, 1);
});

test("속도·뱅크를 몰라 points가 비면 역시 안 그린다 (radius null 경로)", () => {
  const { canvas } = mount({
    rows: [row(3000, 0), row(3000, 3000)],
    flyable: { radius: null, points: [], tightIdx: [] },
  });
  assert.equal(strokesOf(canvas, FLY).length, 0);
});

test("점이 하나뿐이면 선이 아니다 — 그리지 않는다", () => {
  const { canvas } = mount({
    rows: [row(3000, 0)],
    flyable: { radius: 900, points: [{ n: 0, e: 0 }], tightIdx: [] },
  });
  assert.equal(strokesOf(canvas, FLY).length, 0);
});

test("미리보기를 주면 초록 **실선**으로 그 폴리라인을 그대로 그린다", () => {
  const pts = [{ n: 0, e: 0 }, { n: 1000, e: 0 }, { n: 1500, e: 500 }, { n: 3000, e: 3000 }];
  const { canvas } = mount({
    rows: [row(3000, 0), row(3000, 3000)],
    flyable: { radius: 900, points: pts, tightIdx: [] },
  });
  const fly = strokesOf(canvas, FLY);
  assert.equal(fly.length, 1);
  assert.equal(fly[0].path.length, pts.length, "표본을 솎지 않는다 — 호가 각져 보인다");
  assert.equal(fly[0].path[0].op, "move");
  assert.ok(fly[0].path.slice(1).every((p) => p.op === "line"));
  assert.deepEqual(fly[0].dash, [], "실제 경로는 실선 — 계획선과 구분되는 축이 그것이다");
});

test("못 나는 꺾임에는 그 웨이포인트 자리에 빨간 고리를 친다", () => {
  const rows = [row(2000, 0), row(2000, 1000), row(0, 1000)];
  const { canvas } = mount({
    rows,
    flyable: {
      radius: 900,
      points: [{ n: 0, e: 0 }, { n: 2000, e: 0 }, { n: 2000, e: 1000 }, { n: 0, e: 1000 }],
      tightIdx: [1], // 두 번째 웨이포인트
    },
  });
  const rings = strokesOf(canvas, TIGHT);
  assert.equal(rings.length, 1, "tightIdx 하나에 고리 하나");
  assert.equal(rings[0].path.length, 1);
  assert.equal(rings[0].path[0].op, "arc");
  // 고리는 **그 웨이포인트** 자리다 — 다른 점에 치면 경고 문장이 지목한 번호와 어긋난다
  const wpFills = opsOf(canvas).filter(
    (o) => o.kind === "fill" && o.fillStyle === "#ff9500" && o.path[0]?.op === "arc",
  );
  const target = wpFills[1]; // rows[1]의 주황 점
  assert.ok(target, "웨이포인트 점이 안 그려졌다");
  assert.ok(Math.abs(rings[0].path[0].x - target.path[0].x) < 1e-9);
  assert.ok(Math.abs(rings[0].path[0].y - target.path[0].y) < 1e-9);
});

test("tightIdx가 범위를 벗어나도 죽지 않는다 — 표와 미리보기가 한 틱 어긋날 수 있다", () => {
  // 행을 지운 직후 등 getFlyable이 옛 목록으로 계산된 순간이 있다. 그때 뷰가
  // 터지면 지도가 통째로 사라진다 — 없는 점은 조용히 건너뛰는 것이 맞다.
  const { canvas } = mount({
    rows: [row(3000, 0)],
    flyable: { radius: 900, points: [{ n: 0, e: 0 }, { n: 3000, e: 0 }], tightIdx: [7] },
  });
  assert.equal(strokesOf(canvas, TIGHT).length, 0);
  assert.equal(strokesOf(canvas, FLY).length, 1, "나머지는 정상적으로 그린다");
});

test("도달반경 원이 하한에 걸리면 **점선**이다 — 축척인 줄 읽히지 않게", () => {
  // 반경이 작아 화면 반지름이 하한(5.5 px) 밑으로 내려가는 구성.
  // 실선으로 두면 그 크기가 실제 축척이라고 읽히는데, 그건 하한이 그린 크기다.
  const rows = [row(30000, 0), row(-30000, 0)]; // 넓은 뷰 → kScale 작음
  const { canvas } = mount({ rows, accept: 1 });
  const circles = strokesOf(canvas, ACCEPT).filter((o) => o.path[0]?.op === "arc");
  assert.ok(circles.length >= 1, "도달반경 원이 없다");
  assert.deepEqual(circles[0].dash, [2, 2], "하한에 걸린 원은 점선이어야 한다");
  assert.ok(Math.abs(circles[0].path[0].r - 5.5) < 1e-9, "하한 크기로 그린다");
});

test("도달반경이 충분히 크면 실선이고 반지름이 축척을 따른다", () => {
  const rows = [row(3000, 0), row(3000, 3000)];
  const { canvas } = mount({ rows, accept: 500 });
  const circles = strokesOf(canvas, ACCEPT).filter((o) => o.path[0]?.op === "arc");
  assert.ok(circles.length >= 1);
  assert.deepEqual(circles[0].dash, [], "축척이 그린 원은 실선");
  assert.ok(circles[0].path[0].r > 5.5);
});

test("도달반경 0이면 원 자체가 없다 — 0을 '아주 작은 원'으로 위장하지 않는다", () => {
  const rows = [row(3000, 0), row(3000, 3000)];
  const { canvas } = mount({ rows, accept: 0 });
  assert.equal(strokesOf(canvas, ACCEPT).filter((o) => o.path[0]?.op === "arc").length, 0);
});

test("미완성 행은 그리지 않는다 — 빈 칸이 0으로 찍히지 않는다", () => {
  const { canvas } = mount({ rows: [row(3000, 0), row("", ""), row(3000, 3000)] });
  const plan = strokesOf(canvas, PLAN);
  // 원점 + 성한 WP 2개 = 3점 (빈 행이 (0,0)으로 끼면 4점이 된다)
  assert.equal(plan[0].path.length, 3);
});

test("refresh()는 다시 그린다 — 매번 clearRect로 시작한다", () => {
  const rows = [row(3000, 0), row(3000, 3000)];
  const { map, canvas } = mount({ rows });
  const before = opsOf(canvas).filter((o) => o.kind === "clear").length;
  rows.push(row(6000, 3000));
  map.refresh();
  assert.equal(opsOf(canvas).filter((o) => o.kind === "clear").length, before + 1);
  // 새 행이 계획선에 들어왔다 (원점 + 3점)
  assert.equal(strokesOf(canvas, PLAN).at(-1).path.length, 4);
});

test("캡션에 마크다운 별표가 새어 나가지 않는다 — hint는 텍스트 노드다", () => {
  // 실제로 한 번 새었다(v0.96 작성 중). el(...)의 자식은 그대로 텍스트가 되므로
  // `**강조**`는 화면에 별표째 나온다 — 강조는 색이 맡는다.
  const { map } = mount({ rows: [row(3000, 0)] });
  const hints = map.root.find("p").map((p) => p.text).join(" ");
  assert.ok(hints.length > 0, "안내문이 비어 있다");
  assert.ok(!hints.includes("**"), `캡션에 마크다운이 있다: ${hints}`);
  // 세 색의 뜻을 실제로 적고 있는가 — 범례 없이 색만 늘리면 읽을 수 없다
  for (const word of ["주황", "초록", "빨간", "파랑"]) {
    assert.ok(hints.includes(word), `캡션이 ${word}을 설명하지 않는다`);
  }
});
