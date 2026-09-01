// 3D 축측투영 수치 검증 — 상자 산출, 극단 시점(평면도·정측면)의 축 대응,
// 회전해도 캔버스 밖으로 나가지 않는 맞춤, 연직 과장 배율, 퇴화 입력
import { test } from "node:test";
import assert from "node:assert/strict";

import { bounds3d, projector3d } from "./plot3d.js";

const LAYOUT = { width: 320, height: 320, margin: 30 };

test("bounds3d: 웨이포인트까지 포함 — 상자 밖에 놓이면 안내선이 잘린다", () => {
  const b = bounds3d([0, 100], [0, 50], [1000, 1200], [[500, -200]]);
  assert.equal(b.n0, 0);
  assert.equal(b.n1, 500); // 웨이포인트 N이 궤적보다 북쪽
  assert.equal(b.e0, -200); // 웨이포인트 E가 궤적보다 서쪽
  assert.equal(b.e1, 50);
  assert.deepEqual([b.h0, b.h1], [1000, 1200]); // 고도 없는 열은 h를 넓히지 않는다
});

test("bounds3d: 웨이포인트 고도도 상자에 든다 — 궤적 위/아래 점이 잘리지 않게", () => {
  // 궤적은 1000~1200 m인데 계획은 1500 m·800 m — 빼면 두 점이 상자 밖에 찍힌다
  const b = bounds3d([0, 100], [0, 50], [1000, 1200], [[10, 10, 1500], [20, 20, 800]]);
  assert.deepEqual([b.h0, b.h1], [800, 1500]);
  // 상자 안이 된 것을 투영으로 확인 — 여백 안에 들어와야 화면에서 안 잘린다
  const p = projector3d(b, { az: 0.6, el: 0.4 }, LAYOUT);
  for (const [n, e, alt] of [[10, 10, 1500], [20, 20, 800]]) {
    const q = p.toPx(n, e, alt);
    assert.ok(q.x >= 0 && q.x <= LAYOUT.width, `x ${q.x}`);
    assert.ok(q.y >= 0 && q.y <= LAYOUT.height, `y ${q.y}`);
  }
});

test("bounds3d: 고도가 섞인 열에서도 있는 것만 센다 (전부/전무는 엔진이 막는다)", () => {
  const b = bounds3d([0, 10], [0, 10], [100, 110], [[1, 1], [2, 2, 400]]);
  assert.deepEqual([b.h0, b.h1], [100, 400]);
});

test("bounds3d: 퇴화 축(정고도·단일점)은 폭 1로 벌린다 — 0-span 나눗셈 금지", () => {
  const b = bounds3d([10, 10], [5, 5], [300, 300]);
  assert.ok(b.n1 > b.n0 && b.e1 > b.e0 && b.h1 > b.h0);
  const p = projector3d(b, { az: 0.6, el: 0.4 }, LAYOUT);
  const q = p.toPx(10, 5, 300);
  assert.ok(Number.isFinite(q.x) && Number.isFinite(q.y));
});

test("bounds3d: 비유한값은 건너뛴다 (null 직렬화·NaN)", () => {
  const b = bounds3d([0, null, 100, NaN], [0, 40], [50, 60]);
  assert.deepEqual([b.n0, b.n1], [0, 100]);
});

test("projector3d: el=π/2는 평면도 — 북쪽이 화면 위, 동쪽이 오른쪽", () => {
  const b = bounds3d([0, 1000], [0, 1000], [0, 100]);
  const p = projector3d(b, { az: 0, el: Math.PI / 2 }, LAYOUT);
  const south = p.toPx(0, 500, 0);
  const north = p.toPx(1000, 500, 0);
  const west = p.toPx(500, 0, 0);
  const east = p.toPx(500, 1000, 0);
  assert.ok(north.y < south.y, "북쪽이 화면 위(캔버스 y가 작다)");
  assert.ok(east.x > west.x, "동쪽이 화면 오른쪽");
  // 평면도에서는 고도가 화면 위치를 바꾸지 않는다 (연직축이 시선과 나란함)
  const lo = p.toPx(500, 500, 0);
  const hi = p.toPx(500, 500, 100);
  assert.ok(Math.abs(hi.y - lo.y) < 1e-6 && Math.abs(hi.x - lo.x) < 1e-6);
});

test("projector3d: el=0은 정측면 — 고도가 화면 위, 북쪽은 깊이로 소실", () => {
  const b = bounds3d([0, 1000], [0, 1000], [0, 100]);
  const p = projector3d(b, { az: 0, el: 0 }, LAYOUT);
  const low = p.toPx(500, 500, 0);
  const high = p.toPx(500, 500, 100);
  assert.ok(high.y < low.y, "고도가 높을수록 화면 위");
  // az=0·el=0에서 북쪽 성분은 화면에 나타나지 않는다 (정확히 시선 방향)
  const near = p.toPx(0, 500, 50);
  const far = p.toPx(1000, 500, 50);
  assert.ok(Math.abs(near.x - far.x) < 1e-6 && Math.abs(near.y - far.y) < 1e-6);
});

test("projector3d: 어떤 시점에서도 상자 안 점은 캔버스 여백 안 — 회전 시 잘림 금지", () => {
  const b = bounds3d([0, 9000], [-2000, 18000], [-20, 1340]);
  for (const az of [0, 0.7, 1.9, 3.4, 5.6]) {
    for (const el of [0, 0.3, 0.9, Math.PI / 2]) {
      const p = projector3d(b, { az, el }, LAYOUT);
      for (const n of [b.n0, b.n1]) {
        for (const e of [b.e0, b.e1]) {
          for (const h of [b.h0, b.h1]) {
            const q = p.toPx(n, e, h);
            assert.ok(Number.isFinite(q.x) && Number.isFinite(q.y), `NaN @ az=${az}`);
            assert.ok(q.x >= -0.001 && q.x <= LAYOUT.width + 0.001,
              `x 이탈 ${q.x} @ az=${az} el=${el}`);
            assert.ok(q.y >= -0.001 && q.y <= LAYOUT.height + 0.001,
              `y 이탈 ${q.y} @ az=${az} el=${el}`);
          }
        }
      }
    }
  }
});

test("projector3d: 수평 두 축은 같은 배율 — 평면 기하(선회반경) 보존", () => {
  // N 범위가 E보다 훨씬 좁아도 같은 거리는 같은 픽셀이어야 한다
  const b = bounds3d([0, 1000], [0, 10000], [0, 500]);
  const p = projector3d(b, { az: 0, el: Math.PI / 2 }, LAYOUT); // 평면도에서 비교
  const dN = p.toPx(1000, 0, 0).y - p.toPx(0, 0, 0).y;
  const dE = p.toPx(0, 1000, 0).x - p.toPx(0, 0, 0).x;
  assert.ok(Math.abs(Math.abs(dN) - Math.abs(dE)) < 1e-6,
    `같은 1000 m가 N ${dN}px vs E ${dE}px`);
});

test("projector3d: vExag는 연직 과장 배율 — 납작한 궤적일수록 크다", () => {
  const flat = projector3d(bounds3d([0, 10000], [0, 10000], [0, 100]), {}, LAYOUT);
  const cube = projector3d(bounds3d([0, 1000], [0, 1000], [0, 1000]), {}, LAYOUT);
  assert.ok(flat.vExag > cube.vExag, "수평이 넓을수록 연직을 더 과장한다");
  assert.ok(Number.isFinite(flat.vExag) && flat.vExag > 0);
});

test("projector3d: 상자 모서리 8개 — 같은 기둥의 천장이 바닥보다 화면 위", () => {
  const b = bounds3d([0, 1000], [0, 1000], [0, 800]);
  const p = projector3d(b, { az: 0.6, el: 0.5 }, LAYOUT);
  assert.equal(p.corners.length, 8);
  assert.ok(p.corners.every((c) => Number.isFinite(c.x) && Number.isFinite(c.y)));
  // 상자 전체로 비교하면 안 된다 — 얕은 고각에서는 먼 쪽 바닥이 가까운 쪽 천장보다
  // 화면 위로 올라간다(정상적인 깊이 표현). 성립하는 불변식은 같은 (x,y) 기둥 안:
  // 인덱스 i(바닥)와 i+4(천장)가 같은 기둥이라는 규약도 여기서 함께 고정된다
  for (let i = 0; i < 4; i += 1) {
    assert.ok(p.corners[i + 4].y < p.corners[i].y, `기둥 ${i}: 천장이 바닥보다 아래`);
    assert.ok(Math.abs(p.corners[i + 4].x - p.corners[i].x) < 1e-6,
      `기둥 ${i}: 천장·바닥의 가로 위치가 달라짐 (연직축이 화면 수직이어야)`);
  }
});

test("projector3d: toPxFloor는 바닥면 그림자 — 고도와 무관하게 같은 자리", () => {
  const b = bounds3d([0, 1000], [0, 1000], [0, 800]);
  const p = projector3d(b, { az: 0.6, el: 0.5 }, LAYOUT);
  const shadow = p.toPxFloor(400, 700);
  const atFloor = p.toPx(400, 700, b.h0);
  assert.ok(Math.abs(shadow.x - atFloor.x) < 1e-6);
  assert.ok(Math.abs(shadow.y - atFloor.y) < 1e-6);
  // 고도가 달라도 그림자는 안 움직인다
  assert.deepEqual(p.toPxFloor(400, 700), shadow);
});
