/** lib/uavmesh.js — 기체 형상 테스트.

이 파일의 마지막 절이 이 작업에서 가장 값싼 안전장치다: **attitude와 uavmesh를 합쳐
"요 90°면 기수가 동쪽으로 간다"를 렌더러 없이 확인한다.** 3-2-1 규약·FRD 축·쿼터니언
부호·형상 배치가 한 사슬로 엮여 있어, 셋이 통과하면 화면에서 기체가 엉뚱하게 누워 있을
경우의 수가 사실상 사라진다. views/는 테스트하지 않는 리포이므로 회귀를 여기서 막는다.
*/

import assert from "node:assert/strict";
import { test } from "node:test";

import { bodyToNed, eulerToQuat } from "./attitude.js";
import { uavMesh } from "./uavmesh.js";

// 엔진 make_demo_aircraft의 AeroModel 값 — 서버가 meta.geometry로 실어 보내는 것과 같다
const DEMO = {
  b: 2.5, s_ref: 3.0, cbar: 1.5,
  gear_contacts: [[0.6, -0.6, 0.55], [-0.6, -0.6, 0.55], [0.6, 0.6, 0.55], [-0.6, 0.6, 0.55]],
};
const HALF_PI = Math.PI / 2;

/* ---------- 구조 ---------- */

test("메시가 온전하다 — 인덱스가 범위 안이고 법선이 단위벡터다", () => {
  const m = uavMesh(DEMO);
  const nVert = m.positions.length / 3;
  assert.equal(m.normals.length, m.positions.length);
  assert.equal(m.indices.length % 3, 0);
  for (const i of m.indices) assert.ok(i >= 0 && i < nVert, `인덱스 ${i} 범위 밖`);
  for (let i = 0; i < nVert; i++) {
    const n = Math.hypot(m.normals[3 * i], m.normals[3 * i + 1], m.normals[3 * i + 2]);
    assert.ok(Math.abs(n - 1) < 1e-6, `법선 ${i} 길이 ${n}`);
  }
  // Uint16 인덱스를 쓰므로 정점이 65,536을 넘으면 조용히 잘린다
  assert.ok(nVert < 65536, "Uint16 인덱스 한계");
});

test("그룹이 인덱스를 빠짐없이 겹치지 않게 덮는다", () => {
  const m = uavMesh(DEMO);
  let cursor = 0;
  for (const g of m.groups) {
    assert.equal(g.start, cursor, `그룹 ${g.name} 시작이 어긋남`);
    cursor += g.count;
  }
  assert.equal(cursor, m.indices.length, "그룹 합이 인덱스 전체가 아님");
  assert.deepEqual(m.groups.map((g) => g.name), ["wing", "elevon", "body"]);
});

test("엘레본은 4면이다 — 믹서가 그 4면을 쓴다 (규약 §5)", () => {
  const m = uavMesh(DEMO);
  const elevon = m.groups.find((g) => g.name === "elevon");
  // 육면체 하나는 6면 × 2삼각형 × 3인덱스 = 36
  assert.equal(elevon.count, 4 * 36);
});

/* ---------- 치수가 엔진에서 온다 ---------- */

test("뿌리시위는 삼각 평면형 가정 c_root = 2S/b로 유도된다", () => {
  const m = uavMesh(DEMO);
  assert.ok(Math.abs(m.extent.rootChord - (2 * DEMO.s_ref) / DEMO.b) < 1e-12);
  assert.equal(m.extent.span, DEMO.b);
});

test("델타 가정이 자체 정합적이다 — 삼각형 MAC (2/3)c_root가 엔진 c̄와 맞는다", () => {
  // 이 부등식이 깨지면 델타 평면형 가정이 그 기체에 맞지 않는다는 뜻이고,
  // 그때는 형상을 바꾸는 게 아니라 **가정이 틀렸다고 화면이 말해야** 한다.
  const m = uavMesh(DEMO);
  const macOfTriangle = (2 / 3) * m.extent.rootChord;
  assert.ok(Math.abs(macOfTriangle - DEMO.cbar) / DEMO.cbar < 0.10,
    `MAC ${macOfTriangle} vs c̄ ${DEMO.cbar} — 10% 넘게 어긋나면 델타 가정 재검토`);
});

test("스팬을 바꾸면 익단이 따라간다 — 치수가 하드코딩되어 있지 않다", () => {
  const wide = uavMesh({ ...DEMO, b: 6.0 });
  assert.equal(wide.landmarks.rightWingTip[1], 3.0);
  assert.equal(wide.landmarks.leftWingTip[1], -3.0);
});

test("치수가 없거나 말이 안 되면 기체를 그리지 않고 던진다", () => {
  assert.throws(() => uavMesh(undefined), /양의 유한값/);
  assert.throws(() => uavMesh({ s_ref: 3.0 }), /b/);
  assert.throws(() => uavMesh({ b: 0, s_ref: 3.0 }), /b/);
  assert.throws(() => uavMesh({ b: 2.5, s_ref: NaN }), /s_ref/);
});

test("스키드는 접촉점이 있을 때만 생긴다 — 없는 것을 그리지 않는다", () => {
  const withGear = uavMesh(DEMO);
  const noGear = uavMesh({ b: DEMO.b, s_ref: DEMO.s_ref, cbar: DEMO.cbar });
  assert.ok(withGear.indices.length > noGear.indices.length);
  // 스키드가 CG 아래로 뻗는다 (접촉점 z = +0.55, FRD에서 아래가 +z)
  const maxZ = maxComponent(withGear.positions, 2);
  assert.ok(maxZ >= 0.55 - 1e-9, `스키드 최하단 ${maxZ}`);
  assert.ok(maxComponent(noGear.positions, 2) < 0.55);
});

/* ---------- 자세 사슬 (attitude + uavmesh 합성) ----------
   여기가 렌더러 없이 "기체가 옳게 누워 있는가"를 확인하는 자리다. */

test("수평 자세: 기수는 북, 우익은 동, 수직미익은 위", () => {
  const q = eulerToQuat(0, 0, 0);
  const { landmarks: L } = uavMesh(DEMO);
  const nose = bodyToNed(q, L.nose);
  assert.ok(nose[0] > 0 && Math.abs(nose[1]) < 1e-12, "기수가 북(+N)");
  const tip = bodyToNed(q, L.rightWingTip);
  assert.ok(tip[1] > 0, "우익이 동(+E)");
  assert.ok(bodyToNed(q, L.finTop)[2] < 0, "미익 끝이 위(D 음수)");
});

test("요 90°: 기수가 동쪽을 본다", () => {
  const q = eulerToQuat(0, 0, HALF_PI);
  const { landmarks: L } = uavMesh(DEMO);
  const nose = bodyToNed(q, L.nose);
  assert.ok(Math.abs(nose[0]) < 1e-12, `북 성분이 남아 있음: ${nose[0]}`);
  assert.ok(Math.abs(nose[1] - L.nose[0]) < 1e-12, `동으로 ${L.nose[0]} m 가야 함`);
});

test("롤 90°: 오른쪽 날개 끝이 CG보다 아래로 내려간다", () => {
  const q = eulerToQuat(HALF_PI, 0, 0);
  const { landmarks: L } = uavMesh(DEMO);
  const tip = bodyToNed(q, L.rightWingTip);
  assert.ok(Math.abs(tip[2] - L.rightWingTip[1]) < 1e-12, `아래로 반스팬만큼: ${tip[2]}`);
  assert.ok(bodyToNed(q, L.leftWingTip)[2] < 0, "좌익은 반대로 위");
});

test("피치 −90°: 기수가 수직 아래를 향한다 (강하)", () => {
  const q = eulerToQuat(0, -HALF_PI, 0);
  const { landmarks: L } = uavMesh(DEMO);
  const nose = bodyToNed(q, L.nose);
  assert.ok(Math.abs(nose[2] - L.nose[0]) < 1e-12, `D 성분이 기수 길이만큼: ${nose[2]}`);
});

test("발사 레일 앙각 15°: 기수가 그만큼 들리고 여전히 정북을 본다", () => {
  // 기본 미션의 레일 구간이 그리는 자세 — 이륙 장면이 옳게 보이는지의 근거
  const elev = (15 * Math.PI) / 180;
  const q = eulerToQuat(0, elev, 0);
  const { landmarks: L } = uavMesh(DEMO);
  const nose = bodyToNed(q, L.nose);
  assert.ok(Math.abs(nose[1]) < 1e-12, "방위는 그대로 북");
  assert.ok(nose[2] < 0, "기수가 위로");
  assert.ok(Math.abs(Math.atan2(-nose[2], nose[0]) - elev) < 1e-12, "앙각이 정확히 15°");
});

function maxComponent(positions, axis) {
  let m = -Infinity;
  for (let i = axis; i < positions.length; i += 3) m = Math.max(m, positions[i]);
  return m;
}
