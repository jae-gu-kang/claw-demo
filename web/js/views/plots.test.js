/** 공유 드로잉 계층 — **파급이 가장 큰 뷰**다. 여기가 틀리면 탭 전부가 틀린다.
 *
 * 픽셀이 아니라 결정을 본다(`wpmap.test.js`와 같은 규약, 스텁은 `testdom.js`).
 * 고른 자리는 셋이다 — 셋 다 **틀려도 화면이 조용한** 종류다:
 *
 *   ① 좌표에 NaN이 새는가 — 캔버스는 NaN을 그냥 **안 그린다**. 예외도 경고도 없이
 *      선이 사라지므로, 통째로 빈 차트가 "그릴 것이 없었다"와 구분되지 않는다.
 *      (유한성 자체는 `lib/plot.js linScale`의 `|| 1`이 지킨다. 퇴화 입력에서
 *      plots.js의 가드들이 하는 일은 **선이 변에 눌어붙지 않게** 하는 것이고,
 *      그건 좌표가 유한한 채로 틀리는 종류라 따로 잡는다.)
 *   ② 구멍에서 붓을 떼는가 — 결측(null) 위를 이어 그으면 없는 데이터를 지어낸 선이
 *      되고, 그 선은 완벽히 그럴듯해 보인다.
 *   ③ N–E 평면이 등축인가 — 캡션이 "등축(선회반경 판독용)"이라고 약속한다. 깨지면
 *      사용자가 그 그림에서 선회반경을 읽고 **틀린 수를 얻는다**.
 */
import test from "node:test";
import assert from "node:assert/strict";

import { installDom, opsOf } from "./testdom.js";

installDom(); // **import보다 먼저** — makeCanvas가 window.devicePixelRatio를 읽는다
// 빌더들은 **캔버스 노드를 그대로** 돌려준다 — `{canvas, ctx}`를 내는 것은 makeCanvas뿐이다
const {
  histogramCanvas, lineChartCanvas, profileCanvas, scatterCanvas, trackCanvas,
} = await import("./plots.js");

/** 컨텍스트에 닿은 좌표 전부 — NaN 한 톨이 조용히 선 하나를 지운다. */
function coordsOf(canvas) {
  const out = [];
  for (const o of opsOf(canvas)) {
    for (const p of o.path ?? []) {
      for (const k of ["x", "y", "r", "w", "h"]) if (k in p) out.push([`${o.kind}.${k}`, p[k]]);
    }
    for (const k of ["x", "y", "w", "h"]) if (k in o) out.push([`${o.kind}.${k}`, o[k]]);
  }
  return out;
}

function assertAllFinite(canvas, what) {
  const bad = coordsOf(canvas).filter(([, v]) => !Number.isFinite(v));
  assert.deepEqual(bad, [], `${what}: 비유한 좌표가 컨텍스트에 닿았다 — 조용히 안 그려진다`);
}

const T = [0, 1, 2, 3, 4];

// ---- ① 비유한 좌표가 새지 않는가 (퇴화 입력 포함) ----

test("lineChartCanvas: 상수 시계열도 좌표가 유한하다", () => {
  // **유한성을 지키는 것은 `linScale`의 `|| 1`이다** — plots.js의 퇴화 가드가 아니다.
  // 그 사실을 여기 적어 두는 이유: 이 테스트가 무엇을 붙잡고 있는지 틀리게 적으면
  // 나중에 엉뚱한 코드를 "이 테스트가 지킨다"고 믿고 고치게 된다. 퇴화 가드가
  // 실제로 하는 일은 바로 아래 테스트가 잡는다.
  const canvas = lineChartCanvas(T, [{ data: [7, 7, 7, 7, 7], color: "#007aff" }]);
  assertAllFinite(canvas, "상수 시계열");
});

test("lineChartCanvas: 상수 시계열은 **축 가운데**에 그린다 — 바닥에 붙지 않는다", () => {
  // 퇴화 가드(lo -= 1; hi += 1)가 실제로 하는 일이 이것이다. 없으면 lo === hi라
  // py(v) = r0 그대로여서 선이 그림 영역 **맨 아래 변**에 눌어붙는다 — 좌표는
  // 유한하니 위 테스트로는 안 잡히고, 화면에서는 "0으로 떨어졌다"로 오독된다.
  const color = "#007aff";
  const canvas = lineChartCanvas(T, [{ data: [7, 7, 7, 7, 7], color }], { height: 190 });
  const line = opsOf(canvas).find((o) => o.kind === "stroke" && o.strokeStyle === color);
  const ys = line.path.map((p) => p.y);
  const mT = 22, mB = 24, height = 190; // plots.js lineChartCanvas의 여백
  const mid = (mT + (height - mB)) / 2;
  assert.ok(ys.every((y) => Math.abs(y - mid) < 2), `상수선이 가운데가 아니다: ${ys[0]}`);
});

test("lineChartCanvas: 전 표본이 null이어도 터지지 않고 좌표가 유한하다", () => {
  const canvas = lineChartCanvas(T, [{ data: [null, null, null, null, null], color: "#f00" }]);
  assertAllFinite(canvas, "전량 결측");
});

test("lineChartCanvas: 빈 시계열도 좌표가 유한하다", () => {
  const canvas = lineChartCanvas([], [{ data: [], color: "#f00" }]);
  assertAllFinite(canvas, "빈 시계열");
});

test("trackCanvas: 한 점짜리 궤적도 좌표가 유한하다", () => {
  // 여기서도 유한성의 주인은 `linScale`의 `|| 1`이다 (위 상수 시계열과 같은 자리).
  const canvas = trackCanvas([100], [200], [], 0);
  assertAllFinite(canvas, "단일 표본 궤적");
});

test("trackCanvas: 한 점짜리 궤적은 **화면 가운데**에 놓인다 — 구석에 붙지 않는다", () => {
  // span의 `…, 1)` 하한이 하는 일. 없으면 span = 0이라 그 점이 좌상단 여백 자리에
  // 찍힌다 — 좌표는 유한하고, 화면은 "기체가 구석에 있다"는 거짓을 말한다.
  const canvas = trackCanvas([100], [200], [[100, 200]], 50);
  const dot = opsOf(canvas)
    .filter((o) => o.kind === "fill" && o.fillStyle === "#ff9500")
    .map((o) => o.path[0]).find((p) => p?.op === "arc");
  assert.ok(dot, "웨이포인트 점이 없다");
  const m = 42, size = 380; // plots.js trackCanvas의 여백·기본 크기
  const mid = (m + (size - m)) / 2;
  assert.ok(Math.abs(dot.x - mid) < 2 && Math.abs(dot.y - mid) < 2,
    `가운데가 아니다: (${dot.x}, ${dot.y})`);
});

test("profileCanvas: 상수 고도·빈 입력에서도 좌표가 유한하다", () => {
  assertAllFinite(profileCanvas([0, 1, 2], [50, 50, 50]), "상수 고도");
  assertAllFinite(profileCanvas([], []), "빈 프로파일");
});

test("scatterCanvas: 점이 없거나 한 점이어도 좌표가 유한하다", () => {
  assertAllFinite(scatterCanvas([]), "빈 산점도");
  assertAllFinite(scatterCanvas([{ x: 5, y: 5 }]), "한 점 산점도");
});

test("histogramCanvas: 막대가 없으면 사유를 적는다 — 빈 축만 두지 않는다", () => {
  const canvas = histogramCanvas([]);
  assertAllFinite(canvas, "빈 히스토그램");
  const texts = opsOf(canvas).filter((o) => o.kind === "text").map((o) => o.text);
  assert.ok(texts.includes("표본 없음"), `사유가 없다: ${texts.join("|")}`);
});

// ---- ② 결측 위를 이어 긋지 않는가 ----

test("lineChartCanvas: null 구간에서 붓을 뗀다 — 없는 데이터를 이어 그리지 않는다", () => {
  const color = "#34c759";
  const canvas = lineChartCanvas(T, [{ data: [1, 2, null, 4, 5], color }]);
  const line = opsOf(canvas).find((o) => o.kind === "stroke" && o.strokeStyle === color);
  assert.ok(line, "계열 선이 없다");
  // 구멍 앞뒤가 각각 새 붓질이라 moveTo가 **둘**이다. 이어 그었다면 하나뿐이다
  assert.equal(line.path.filter((p) => p.op === "move").length, 2);
  assert.equal(line.path.filter((p) => p.op === "line").length, 2);
});

test("lineChartCanvas: 구멍이 없으면 붓질은 한 번이다 (위 테스트의 짝)", () => {
  const color = "#34c759";
  const canvas = lineChartCanvas(T, [{ data: [1, 2, 3, 4, 5], color }]);
  const line = opsOf(canvas).find((o) => o.kind === "stroke" && o.strokeStyle === color);
  assert.equal(line.path.filter((p) => p.op === "move").length, 1);
  assert.equal(line.path.filter((p) => p.op === "line").length, 4);
});

test("lineChartCanvas: 점선 계열은 점선으로, 실선 계열에 점선이 새지 않는다", () => {
  const canvas = lineChartCanvas(T, [
    { data: [1, 2, 3, 4, 5], color: "#111", dash: [4, 3] },
    { data: [2, 3, 4, 5, 6], color: "#222" },
  ]);
  const a = opsOf(canvas).find((o) => o.kind === "stroke" && o.strokeStyle === "#111");
  const b = opsOf(canvas).find((o) => o.kind === "stroke" && o.strokeStyle === "#222");
  assert.deepEqual(a.dash, [4, 3]);
  assert.deepEqual(b.dash, [], "앞 계열의 점선이 뒤로 새면 두 계열이 같아 보인다");
});

// ---- ③ N–E 평면이 등축인가 ----

test("trackCanvas: N–E는 **등축**이다 — 캡션이 선회반경 판독을 약속한다", () => {
  // 동서로 길고 남북으로 짧은 궤적. 축을 각각 맞추면(비등축) 원이 타원으로 그려져
  // 사용자가 선회반경을 읽을 때 틀린 수를 얻는다.
  const pn = [0, 100];
  const pe = [0, 10000];
  const canvas = trackCanvas(pn, pe, [[0, 0], [100, 10000]], 500);
  // 웨이포인트 도달반경 원 두 개의 반지름이 같아야 한다(같은 acceptRadius·같은 kScale)
  const circles = opsOf(canvas)
    .filter((o) => o.kind === "stroke" && o.strokeStyle === "#ff9500")
    .map((o) => o.path[0]).filter((p) => p?.op === "arc");
  assert.equal(circles.length, 2);
  assert.ok(Math.abs(circles[0].r - circles[1].r) < 1e-9);
  // 두 웨이포인트의 화면 거리 / 실제 거리 = 축척. N·E 어느 쪽으로 재도 같아야 등축이다
  const dxPx = Math.abs(circles[1].x - circles[0].x); // E 10,000 m 만큼
  const dyPx = Math.abs(circles[1].y - circles[0].y); // N 100 m 만큼
  const kE = dxPx / 10000;
  const kN = dyPx / 100;
  assert.ok(Math.abs(kE - kN) / kE < 1e-9, `등축이 아니다: E축 ${kE} vs N축 ${kN}`);
});

test("trackCanvas: 도달반경이 아주 작아도 원이 점(반지름 3) 밑으로 사라지지 않는다", () => {
  const canvas = trackCanvas([0, 1000], [0, 1000], [[500, 500]], 0.001);
  const arc = opsOf(canvas)
    .filter((o) => o.kind === "stroke" && o.strokeStyle === "#ff9500")
    .map((o) => o.path[0]).find((p) => p?.op === "arc");
  assert.ok(arc, "도달반경 원이 없다");
  assert.ok(arc.r >= 3, `반지름 ${arc.r} — 하한이 일하지 않았다`);
});
