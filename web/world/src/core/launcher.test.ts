import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  CANISTER_LENGTH, LAUNCHER_GEOMETRY, LAUNCHER_SPAN,
  boresightNed, launcherCaptionNotes, launcherPose,
} from "./launcher.ts";

const D2R = Math.PI / 180;
const near = (got: number, want: number, what = "", tol = 1e-9) =>
  assert.ok(Math.abs(got - want) < tol, `${what} ${got} ≠ ${want}`);

/** three의 `rotation.y = θ` · `rotation.x = φ` 를 실제로 적용하고, 결과를 NED로 되돌린다.
 *
 * **유도를 믿지 않으려고 둔 함수다.** 부호를 손으로 따지면 `x = E, y = 위, z = −N`과
 * 오른손 법칙이 얽혀 틀리기 쉬운데, 여기서는 회전행렬을 그대로 곱하고 축 사상의 역
 * (`n = −z, e = x, d = −y`)으로 돌려놓아 **결과끼리** 비교한다. */
function nodeBoresightToNed(turntableY: number, cradleX: number): [number, number, number] {
  // 기준축은 로컬 −Z (포구 방향). 크래들이 턴테이블의 자식이므로 X 먼저, 그 다음 Y.
  let [x, y, z] = [0, 0, -1];
  const cx = Math.cos(cradleX), sx = Math.sin(cradleX);
  [x, y, z] = [x, cx * y - sx * z, sx * y + cx * z];
  const cy = Math.cos(turntableY), sy = Math.sin(turntableY);
  [x, y, z] = [cy * x + sy * z, y, -sy * x + cy * z];
  return [-z, x, -y]; // nedToRender(n,e,d) = [e, −d, −n] 의 역
}

const LAUNCH = {
  length: 10, elev_angle: 15 * D2R, azimuth: 0,
  exit_speed: 81.5, accel: null, origin_height: 1.2,
};

describe("발사관 방위 — 부호가 조용히 틀리는 자리", () => {
  it("ψ = 0 이면 포구가 북을 본다", () => {
    const p = launcherPose({ ...LAUNCH, azimuth: 0, elev_angle: 0 })!;
    const ned = nodeBoresightToNed(p.turntableY, p.cradleX);
    near(ned[0], 1, "북"); near(ned[1], 0, "동"); near(ned[2], 0, "하");
  });

  it("**ψ = 90°이면 포구가 정동을 본다** — 데모가 0이라 이 케이스만이 부호를 잡는다", () => {
    const p = launcherPose({ ...LAUNCH, azimuth: 90 * D2R, elev_angle: 0 })!;
    assert.ok(p.turntableY < 0, "rotation.y 는 −ψ 여야 한다 (부호가 뒤집히면 서쪽을 본다)");
    const ned = nodeBoresightToNed(p.turntableY, p.cradleX);
    near(ned[0], 0, "북"); near(ned[1], 1, "동");
  });

  it("ψ = 270°(정서)도 맞는다", () => {
    const p = launcherPose({ ...LAUNCH, azimuth: 270 * D2R, elev_angle: 0 })!;
    const ned = nodeBoresightToNed(p.turntableY, p.cradleX);
    near(ned[1], -1, "동 성분이 −1이어야 서쪽");
  });

  it("네 방위 전부에서 노드 회전과 NED 계산이 일치한다", () => {
    for (const deg of [0, 30, 90, 150, 180, 225, 270, 359]) {
      const az = deg * D2R;
      const p = launcherPose({ ...LAUNCH, azimuth: az, elev_angle: 20 * D2R })!;
      const fromNodes = nodeBoresightToNed(p.turntableY, p.cradleX);
      for (let i = 0; i < 3; i++) near(fromNodes[i]!, p.boresightNed[i]!, `ψ=${deg}° 성분 ${i}`, 1e-9);
    }
  });
});

describe("발사관 고각", () => {
  it("양의 고각이 포구를 든다 (NED의 d가 음수 = 상방)", () => {
    const p = launcherPose({ ...LAUNCH, elev_angle: 15 * D2R })!;
    assert.ok(p.boresightNed[2] < 0, "d가 음수여야 위를 본다");
    near(p.boresightNed[2], -Math.sin(15 * D2R), "d");
    assert.equal(p.cradleX, 15 * D2R);
  });

  it("데모의 15°는 모델 가동 범위(0~48°) 안이라 안 잘린다", () => {
    const p = launcherPose(LAUNCH)!;
    assert.equal(p.elevationClamped, false);
  });

  it("범위를 넘으면 자르고 그 사실을 알린다", () => {
    const p = launcherPose({ ...LAUNCH, elev_angle: 60 * D2R })!;
    assert.equal(p.cradleX, LAUNCHER_GEOMETRY.elevMax);
    assert.equal(p.elevationClamped, true);
    assert.ok(launcherCaptionNotes({ ...LAUNCH, elev_angle: 60 * D2R }, p)
      .some((s) => s.includes("가동 범위")));
  });

  it("캡션의 범위가 **상수에서 나온다** — 하드코딩하면 상수를 바꿔도 옛 값을 말한다", () => {
    const l = { ...LAUNCH, elev_angle: 60 * D2R };
    const line = launcherCaptionNotes(l, launcherPose(l)!).find((s) => s.includes("가동 범위"));
    const lo = ((LAUNCHER_GEOMETRY.elevMin * 180) / Math.PI).toFixed(0);
    const hi = ((LAUNCHER_GEOMETRY.elevMax * 180) / Math.PI).toFixed(0);
    assert.ok(line!.includes(`${lo}~${hi}°`), `상수와 다른 범위를 말한다: ${line}`);
  });

  it("음의 고각도 잘린다 (크래들은 아래로 안 내려간다)", () => {
    const p = launcherPose({ ...LAUNCH, elev_angle: -0.2 })!;
    assert.equal(p.cradleX, 0);
    assert.equal(p.elevationClamped, true);
  });
});

describe("포구 높이와 캡션", () => {
  it("15°에서 포구가 약 4.7 m — 실측 피벗 × 루트 스케일 2.0에서 나온다", () => {
    // 트러니언이 관 뒤끝 근처라 |muzzleZ|가 3.48로 길다 — 포구가 피벗에서 멀어
    // 같은 고각에서도 높이 나간다(2026-09-02 재개정 내력).
    const p = launcherPose(LAUNCH)!;
    near(p.muzzleHeight, (0.80 + 0.65 + 3.48 * Math.sin(15 * D2R)) * 2.0, "포구 높이", 1e-9);
    assert.ok(p.muzzleHeight > 4.6 && p.muzzleHeight < 4.8);
  });

  it("발사 원점 1.2 m와의 3.5 m 차이를 캡션이 말한다 (재개정 기하)", () => {
    const notes = launcherCaptionNotes(LAUNCH, launcherPose(LAUNCH)!);
    const line = notes.find((s) => s.includes("높이가"));
    assert.ok(line, "높이 불일치를 숨기면 화면이 거짓말한다");
    assert.ok(line!.includes("3.5 m"), line);
  });

  it("원점 높이가 포구에 맞춰지면 그 줄이 사라진다", () => {
    const p0 = launcherPose(LAUNCH)!;
    const fixed = { ...LAUNCH, origin_height: p0.muzzleHeight };
    assert.ok(!launcherCaptionNotes(fixed, launcherPose(fixed)!).some((s) => s.includes("높이가")));
  });

  it("구조 전장 9.7 m ≈ 가속 구간 10 m — 데모에선 '별개' 캡션이 **안 뜬다**", () => {
    // 재개정으로 길이가 비슷해졌다. 비슷한데도 뜨면 캡션이 없는 차이를 지어내는 것.
    const line = launcherCaptionNotes(LAUNCH, launcherPose(LAUNCH)!)
      .find((s) => s.includes("가속 모델"));
    assert.equal(line, undefined, `길이가 비슷한데 별개라고 말한다: ${line}`);
  });

  it("가속 구간이 구조보다 훨씬 길면(1.5배 초과) 수치까지 말한다", () => {
    // 처음에는 `|railTipZ − muzzleZ| + |muzzleZ|` 로 길이를 지어내 화면에 찍고 있었다.
    // 문구만 확인하는 단정은 그 오류를 통과시켰으므로 여기서는 **숫자를 본다.**
    const l = { ...LAUNCH, length: 30 };
    const line = launcherCaptionNotes(l, launcherPose(l)!).find((s) => s.includes("가속 모델"));
    assert.ok(line, "이 줄이 있어야 한다");
    assert.ok(line!.includes("7.2 m"), `캐니스터 길이가 틀렸다: ${line}`);
    assert.ok(line!.includes("9.7 m"), `상부 레일까지의 길이가 틀렸다: ${line}`);
  });

  it("실측 상수가 GLB bbox × 루트 스케일과 맞는다", () => {
    // Box_Tubes bbox z ∈ [−3.48, 0.13] → 3.61 × 2.0 = 7.22 m,
    // Box_Rails 앞끝 −4.70 → 전장 4.83 × 2.0 = 9.66 m (루트 스케일은 생성 스크립트가 정본)
    near(CANISTER_LENGTH, 7.22, "캐니스터", 1e-6);
    near(LAUNCHER_SPAN, 9.66, "구조 전장", 1e-6);
  });
});

describe("결측", () => {
  it("발사 정보가 없으면 null — 발사관을 그리지 않는다", () => {
    assert.equal(launcherPose(null), null);
    assert.equal(launcherPose(undefined), null);
  });

  it("방위나 고각이 결측이면 null — 0으로 놓고 엉뚱한 방향을 그리지 않는다", () => {
    assert.equal(launcherPose({ ...LAUNCH, azimuth: null as never }), null);
    assert.equal(launcherPose({ ...LAUNCH, elev_angle: undefined as never }), null);
  });

  it("캡션은 pose가 없으면 아무 줄도 안 낸다", () => {
    assert.deepEqual(launcherCaptionNotes(LAUNCH, null), []);
    assert.deepEqual(launcherCaptionNotes(null, null), []);
  });
});

describe("boresightNed", () => {
  it("단위벡터다", () => {
    for (const [az, el] of [[0, 0], [1.2, 0.3], [-2.0, 0.8]] as const) {
      const v = boresightNed(az, el);
      near(Math.hypot(v[0], v[1], v[2]), 1, `|v| (ψ=${az}, φ=${el})`);
    }
  });
});

describe("아웃리거", () => {
  it("전개량이 생성 스크립트의 JACK_TRAVEL과 같다", () => {
    // GLB에는 드라이버 상수가 안 실리므로 이 수의 정본은 `generate_launcher.py`다.
    // 어긋나면 발판이 지면을 뚫거나 뜬 채로 그려진다 — 눈에 안 띄는 4 cm짜리 거짓말이다.
    assert.equal(LAUNCHER_GEOMETRY.jackDrop, 0.46);
    assert.equal(launcherPose(LAUNCH)!.jackOffsetY, -0.46);
  });
});

describe("방위 가동 범위", () => {
  it("범위 안이면 아무 말도 안 한다", () => {
    for (const deg of [0, 45, -90, 99]) {
      const l = { ...LAUNCH, azimuth: deg * D2R };
      assert.ok(!launcherCaptionNotes(l, launcherPose(l)!).some((s) => s.includes("선회 범위")));
    }
  });

  it("방위 캡션의 범위도 상수에서 나온다", () => {
    const l = { ...LAUNCH, azimuth: 150 * D2R };
    const line = launcherCaptionNotes(l, launcherPose(l)!).find((s) => s.includes("선회 범위"));
    const lo = ((LAUNCHER_GEOMETRY.azMin * 180) / Math.PI).toFixed(0);
    const hi = ((LAUNCHER_GEOMETRY.azMax * 180) / Math.PI).toFixed(0);
    assert.ok(line!.includes(`${lo}~${hi}°`), `상수와 다른 범위를 말한다: ${line}`);
  });

  it("범위를 넘으면 **자르지 않고 말한다**", () => {
    // 자르면 기체가 나간 방향과 다른 쪽을 겨눈 발사관을 그리게 된다 — 그게 더 나쁘다.
    const l = { ...LAUNCH, azimuth: 150 * D2R };
    const p = launcherPose(l)!;
    near(p.turntableY, -150 * D2R, "자르지 않았는가");
    assert.ok(launcherCaptionNotes(l, p).some((s) => s.includes("선회 범위")), "말해야 한다");
  });

  it("270°는 −90°로 접어 판정한다 (범위 안)", () => {
    const l = { ...LAUNCH, azimuth: 270 * D2R };
    assert.ok(!launcherCaptionNotes(l, launcherPose(l)!).some((s) => s.includes("선회 범위")),
      "270°는 좌현 90°와 같은 자세다");
  });
});
