import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  ELEV_MAX, ELEV_MIN, MAX_FRAME_DT_S, SPIN_PERIOD_S, START_VIEW,
  advanceYaw, cameraOffset, dragView, fitDistance, wrapYaw,
} from "./turntable.ts";

const TAU = 2 * Math.PI;
const near = (g: number, w: number, what = "", tol = 1e-9) =>
  assert.ok(Math.abs(g - w) < tol, `${what} ${g} ≠ ${w}`);

/** three `rotation.y = θ`를 **행렬 그대로** 곱한다 — 부호를 손으로 따지지 않으려고 둔다. */
const rotY = (v: [number, number, number], th: number): [number, number, number] =>
  [Math.cos(th) * v[0] + Math.sin(th) * v[2], v[1], -Math.sin(th) * v[0] + Math.cos(th) * v[2]];

describe("자동 회전", () => {
  it("주기만큼 돌면 제자리다", () => {
    let yaw = 1.0;
    const steps = Math.round(SPIN_PERIOD_S / 0.05);
    for (let i = 0; i < steps; i++) yaw = advanceYaw(yaw, 0.05);
    near(yaw, 1.0, "한 바퀴 뒤", 1e-9);
  });

  it("배경 탭에서 돌아온 긴 dt는 한 프레임 상한만큼만 돈다", () => {
    near(advanceYaw(0, 30), (TAU * MAX_FRAME_DT_S) / SPIN_PERIOD_S, "30 s");
  });

  it("음수·NaN dt는 제자리다", () => {
    assert.equal(advanceYaw(0.5, -1), 0.5);
    assert.equal(advanceYaw(0.5, Number.NaN), 0.5);
  });

  it("요는 [0, 2π)에 산다", () => {
    for (const a of [-7, -TAU, 0, TAU, 13]) {
      const w = wrapYaw(a);
      assert.ok(w >= 0 && w < TAU, `${a} → ${w}`);
      near(Math.cos(w), Math.cos(a), `${a}`);
    }
  });
});

describe("끌기", () => {
  it("오른쪽으로 끌면 카메라를 보던 면이 화면 오른쪽(+X)으로 간다", () => {
    const v = dragView({ yaw: 0, elev: 0.3 }, 20, 0);
    assert.ok(rotY([0, 0, 1], v.yaw)[0] > 0);
  });

  it("고각은 상·하한에서 멈춘다", () => {
    assert.equal(dragView({ yaw: 0, elev: 0.3 }, 0, 1e6).elev, ELEV_MAX);
    assert.equal(dragView({ yaw: 0, elev: 0.3 }, 0, -1e6).elev, ELEV_MIN);
  });

  it("시작 시점은 기수가 카메라 쪽 왼편을 본다", () => {
    const nose = rotY([0, 0, -1], START_VIEW.yaw); // 모델 기수 = 로컬 −Z (modelaxes.ts LOCAL_NOSE)
    assert.ok(nose[2] > 0, "카메라(+Z) 쪽");
    assert.ok(nose[0] < 0, "화면 왼편");
  });
});

describe("화면 맞춤", () => {
  const vfov = (30 * Math.PI) / 180;

  /** 원기둥 표면 점을 요·고각대로 돌려 원근 투영한 NDC — 뷰어와 같은 배치(카메라 +Z, 원점을 본다)를 손으로 곱한다. */
  const worstNdc = (ext: { radial: number; halfHeight: number }, elev: number, aspect: number, dist: number) => {
    let worst = 0;
    const t = Math.tan(vfov / 2);
    for (let i = 0; i < 72; i++) {
      const a = (i / 72) * TAU;
      for (const y of [-ext.halfHeight, 0, ext.halfHeight]) {
        const p: [number, number, number] = [ext.radial * Math.cos(a), y, ext.radial * Math.sin(a)];
        // 카메라 좌표: 오른쪽 = +X, 위 = (0, cos e, −sin e), 뒤(카메라 쪽) = (0, sin e, cos e)
        const right = p[0];
        const up = p[1] * Math.cos(elev) - p[2] * Math.sin(elev);
        const toward = p[1] * Math.sin(elev) + p[2] * Math.cos(elev);
        const depth = dist - toward;
        worst = Math.max(worst, Math.abs(up / (depth * t)), Math.abs(right / (depth * t * aspect)));
      }
    }
    return worst;
  };

  it("어느 요·고각·화면비에서도 원기둥이 화면 안이다 (여유 1이면 가장자리까지)", () => {
    const ext = { radial: 2.15, halfHeight: 0.3 };
    for (const elev of [0.02, 0.3, 0.8, 1.35]) {
      for (const aspect of [0.46, 1, 2.6]) {
        const ndc = worstNdc(ext, elev, aspect, fitDistance(ext, elev, vfov, aspect, 1));
        assert.ok(ndc <= 1 + 1e-9, `elev ${elev} aspect ${aspect}: ${ndc}`);
      }
    }
  });

  it("납작한 기체는 경계구 맞춤보다 가깝게 선다 — 대표 그림이 화면 가운데 작게 남지 않게", () => {
    const ext = { radial: 2.15, halfHeight: 0.3 };
    const sphere = Math.hypot(ext.radial, ext.halfHeight) / Math.sin(vfov / 2);
    assert.ok(fitDistance(ext, 0.3, vfov, 2.6, 1) < 0.75 * sphere);
  });

  it("폭이 0인 무대에서도 유한한 거리를 낸다", () => {
    assert.ok(Number.isFinite(fitDistance({ radial: 2, halfHeight: 0.3 }, 0.3, vfov, 0)));
  });

  it("카메라는 거리를 지키며 고각만큼 올라간다", () => {
    const [x, y, z] = cameraOffset(10, 0.4);
    near(Math.hypot(x, y, z), 10, "거리");
    near(y, 10 * Math.sin(0.4), "높이");
    assert.deepEqual(cameraOffset(10, 0), [0, 0, 10]);
  });
});
