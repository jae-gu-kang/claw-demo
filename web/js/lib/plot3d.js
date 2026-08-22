/** 3D 궤적 축측투영 수치 계층 — NED (n, e, h) → 화면 좌표. DOM 무접촉 순수 함수.

캔버스·포인터(회전 드래그)는 views/plot3d.js. 좌표 규약은 lib/plot.js planeViews와
같다: 내부는 NED(북·동·하방)이고 연직은 D 대신 고도 h = −D 를 위로 그린다.

투영은 직교(원근 없음) 축측투영 — 설계 검토용 그림이라 원근 왜곡으로 거리 판단을
흐리지 않는 편이 낫다. 카메라는 방위각 az(연직축 회전)와 고각 el(수평면 위로
들어올린 각)로 정한다:
  el = 0     → 정측면 (고도가 화면 위, 북쪽은 시선 방향이라 화면에서 소실)
  el = π/2   → 완전 평면도 (북쪽이 화면 위, 동쪽이 오른쪽)

축척: 수평 두 축(N·E)은 **같은 배율** — 평면 기하(선회반경)를 왜곡하지 않기 위해.
연직만 별도 배율로 상자 높이 vertFrac에 맞춘다. 수평 이동이 고도 변화보다 통상
한 자릿수 이상 커서 등축이면 궤적이 납작한 판으로 뭉개지기 때문 (planeViews와
같은 이유). 대신 과장 배율을 vExag로 돌려주니 화면에 밝혀 쓸 것.
*/

const EPS = 1e-9;

/** 신호·웨이포인트를 모두 담는 데이터 상자. 퇴화(단일점) 축은 폭 1로 벌린다. */
export function bounds3d(pn, pe, h, waypoints = []) {
  const span = (arr, extra = []) => {
    let lo = Infinity;
    let hi = -Infinity;
    for (const v of [...arr, ...extra]) {
      if (typeof v !== "number" || !Number.isFinite(v)) continue;
      if (v < lo) lo = v;
      if (v > hi) hi = v;
    }
    if (!(lo <= hi)) return [0, 1]; // 유한값 전무
    return lo < hi ? [lo, hi] : [lo - 0.5, hi + 0.5];
  };
  const [n0, n1] = span(pn, waypoints.map((w) => w[0]));
  const [e0, e1] = span(pe, waypoints.map((w) => w[1]));
  const [h0, h1] = span(h);
  return { n0, n1, e0, e1, h0, h1 };
}

/** (n, e, h) → 정규 좌표 (x=동, y=북, z=위). 수평 등배율, 연직만 vertFrac 배. */
function normalizer(b, vertFrac) {
  const spanN = b.n1 - b.n0;
  const spanE = b.e1 - b.e0;
  const spanH = Math.max(b.h1 - b.h0, EPS);
  const s = 2 / Math.max(spanN, spanE, EPS); // 수평 공통 배율
  const sz = (2 * vertFrac) / spanH;
  const cn = (b.n0 + b.n1) / 2;
  const ce = (b.e0 + b.e1) / 2;
  return {
    s,
    sz,
    // z는 상자 바닥(h0)이 0 — 궤적이 항상 상자 안에 들어오고, 해수면이 데이터
    // 범위 밖이어도(데모는 h가 음수까지 내려간다) 축척이 흔들리지 않는다
    at: (n, e, h) => ({ x: (e - ce) * s, y: (n - cn) * s, z: (h - b.h0) * sz }),
    ranges: {
      x: [(b.e0 - ce) * s, (b.e1 - ce) * s],
      y: [(b.n0 - cn) * s, (b.n1 - cn) * s],
      z: [0, spanH * sz],
    },
  };
}

/** 정규 좌표 → 화면 방향 (sx 오른쪽, sy 위쪽). 캔버스 y는 호출측이 뒤집는다. */
function projectNorm(x, y, z, az, el) {
  const ca = Math.cos(az);
  const sa = Math.sin(az);
  const xr = x * ca - y * sa;
  const yr = x * sa + y * ca;
  // el=π/2에서 sy=yr(북쪽이 화면 위), el=0에서 sy=z(고도가 화면 위)
  return { sx: xr, sy: z * Math.cos(el) + yr * Math.sin(el) };
}

/** 데이터 상자 8모서리 — 와이어프레임·바닥면 그리기와 화면 맞춤에 쓴다.
인덱스 0~3 바닥(z 최소), 4~7 천장. 각 층은 (x0y0, x1y0, x0y1, x1y1) 순. */
function boxCorners(ranges) {
  const out = [];
  for (const z of ranges.z) {
    for (const y of ranges.y) {
      for (const x of ranges.x) out.push({ x, y, z });
    }
  }
  return out;
}

/** 3D 투영기 — toPx(n,e,h)와 상자 모서리 픽셀 좌표, 연직 과장배율 vExag.

view: {az, el} [rad]. layout: {width, height, margin, vertFrac}.
상자 8모서리를 먼저 투영해 그 외접 사각형을 캔버스에 맞추므로, 상자 안의 모든
점은 여백 안에 들어온다 (어느 각도로 돌려도 잘리지 않는다). 가로·세로에 **같은
배율**을 써서 투영 자체의 종횡비는 보존한다.
*/
export function projector3d(b, { az = 0, el = 0 } = {}, {
  width = 320, height = 320, margin = 30, vertFrac = 0.55,
} = {}) {
  const nrm = normalizer(b, vertFrac);
  const corners = boxCorners(nrm.ranges).map((c) => projectNorm(c.x, c.y, c.z, az, el));
  const xs = corners.map((c) => c.sx);
  const ys = corners.map((c) => c.sy);
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  const y0 = Math.min(...ys), y1 = Math.max(...ys);
  const k = Math.min(
    (width - 2 * margin) / Math.max(x1 - x0, EPS),
    (height - 2 * margin) / Math.max(y1 - y0, EPS),
  );
  // 투영 외접 사각형을 캔버스 중앙에 놓는다
  const ox = width / 2 - ((x0 + x1) / 2) * k;
  const oy = height / 2 + ((y0 + y1) / 2) * k;
  const toScreen = (p) => ({ x: ox + p.sx * k, y: oy - p.sy * k });

  return {
    toPx: (n, e, h) => {
      const q = nrm.at(n, e, h);
      return toScreen(projectNorm(q.x, q.y, q.z, az, el));
    },
    /** 바닥면(h0)에 떨어뜨린 그림자 — 3D에서 높이를 읽게 해 주는 깊이 단서. */
    toPxFloor: (n, e) => {
      const q = nrm.at(n, e, b.h0);
      return toScreen(projectNorm(q.x, q.y, 0, az, el));
    },
    corners: corners.map(toScreen), // 0~3 바닥, 4~7 천장
    /** 연직 과장 배율 — 1이면 등축. 화면에 밝혀 쓸 것 (경사각 오독 방지). */
    vExag: nrm.sz / nrm.s,
  };
}
