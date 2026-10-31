import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  CANISTER_LENGTH, DOOR_OPEN_S, LAUNCHER_GEOMETRY, LAUNCHER_SPAN, PRELUDE_S,
  advancePrelude, boresightNed, doorOpenFraction, doorRotations, launcherCaptionNotes, launcherPose,
  startsInCanister,
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
  exit_speed: 81.5, accel: null, origin_height: 2.9,
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

  it("관축 시작점 — 고각을 들면 **내려간다** (트러니언이 관 뒤에 있다)", () => {
    const p = launcherPose(LAUNCH)!;
    near(p.breechHeight, (0.80 + 0.65 - 0.13 * Math.sin(15 * D2R)) * 2.0, "관축 시작점", 1e-9);
    const flat = launcherPose({ ...LAUNCH, elev_angle: 0 })!;
    assert.ok(p.breechHeight < flat.breechHeight, "들었는데 뒤끝이 안 내려가면 피벗이 앞이다");
  });

  it("기본 원점 2.9 m ≈ 관축 시작점 2.83 m — 높이 차이 줄이 **안 선다**", () => {
    // 시뮬 기본(RAIL_ORIGIN_H·sim.py)이 관축과 정합하도록 올라갔다. 0.07 m 차이에
    // 줄이 서면 없는 문제를 지어내는 쪽이다(문턱 0.15 m의 근거).
    const notes = launcherCaptionNotes(LAUNCH, launcherPose(LAUNCH)!);
    assert.ok(!notes.some((s) => s.includes("높이가")), notes.join(" / "));
  });

  it("옛 결과(원점 1.2 m)에서는 1.6 m 차이를 캡션이 말한다", () => {
    const legacy = { ...LAUNCH, origin_height: 1.2 };
    const line = launcherCaptionNotes(legacy, launcherPose(legacy)!)
      .find((s) => s.includes("높이가"));
    assert.ok(line, "높이 불일치를 숨기면 화면이 거짓말한다");
    assert.ok(line!.includes("1.6 m"), line);
    assert.ok(line!.includes("관축 시작점"), "비교 기준은 포구가 아니라 관축 시작점이다");
  });

  it("배치가 표시용 선택임을 조건 없이 밝힌다", () => {
    const notes = launcherCaptionNotes(LAUNCH, launcherPose(LAUNCH)!);
    assert.ok(notes.some((s) => s.includes("표시용 배치")), notes.join(" / "));
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

describe("루트 배치 오프셋 — 기체 원점의 관축 방향 위치가 관 뒤끝에서 꼬리 길이 + 틈이 되게 수평으로 민다", () => {
  const S = LAUNCHER_GEOMETRY.rootScale;
  const VEHICLE_AFT_EXTENT = 1.90; // shahed136.glb 실측 — 아래 "기체 꼬리" describe와 공유
  const TAIL_CLEARANCE = 0.03;
  // 원점 2.9 m = 피벗 높이라 수직 몫이 없다: 관축 방향 u = D·cosθ → D = u / cosθ
  const ahead = (VEHICLE_AFT_EXTENT + TAIL_CLEARANCE - 0.13 * S) / Math.cos(15 * D2R);
  const yawR = 0.90 * S - ahead; // 방위와 함께 도는 수평 성분

  it("ψ = 0: 북으로", () => {
    const off = launcherPose(LAUNCH)!.rootOffsetNed;
    near(off[0], 0.90 * S + yawR, "북", 1e-9);
    near(off[1], 0, "동", 1e-9);
    near(off[2], 0, "하 — 수직은 밀지 않는다(트레일러는 지면에 선다)", 1e-9);
  });

  it("ψ = 90°: 턴테이블 몫은 북에 남고 크래들·관 몫만 동으로 돈다", () => {
    // 트레일러는 선회하지 않으므로 루트→턴테이블(1.8 m)은 방위와 무관하다 —
    // 전부를 돌리면 트레일러가 발사 방위를 따라 도는 셈이 된다.
    const off = launcherPose({ ...LAUNCH, azimuth: 90 * D2R })!.rootOffsetNed;
    near(off[0], 0.90 * S, "북", 1e-9);
    near(off[1], yawR, "동", 1e-9);
  });
});

describe("기체 꼬리 — 관 안에, 관축 방향으로 잰다(2026-09-02 · v2.04)", () => {
  // shahed136.glb bbox z ∈ [−1.75, 1.905](Y-up) — 기체 원점(≈무게중심) 뒤로 꼬리·
  // 프로펠러가 1.90 m 뻗어 있다. 기체는 rootScale 없이 1:1로 놓인다(MODEL_SCALE).
  const VEHICLE_AFT_EXTENT = 1.90;
  const TAIL_CLEARANCE = 0.03;
  const S = LAUNCHER_GEOMETRY.rootScale;
  const g = LAUNCHER_GEOMETRY;

  /** 루트 원점 → 크래들 로컬 Z가 zLocal인 점까지의 NED 오프셋(로컬 단위, rootScale 전).
   *
   *  `launcherPose`의 공식을 재사용하지 않고 회전행렬을 그대로
   *  곱해 독립적으로 구한다 — `nodeBoresightToNed`와 같은 이유(유도를 믿지 않는다). */
  function nodePointToNed(turntableY: number, cradleX: number, zLocal: number): [number, number, number] {
    let [x, y, z] = [0, 0, zLocal];
    const cx = Math.cos(cradleX), sx = Math.sin(cradleX);
    [x, y, z] = [x, cx * y - sx * z, sx * y + cx * z];
    y += g.cradleY; z += g.cradleAftZ;
    const cy = Math.cos(turntableY), sy = Math.sin(turntableY);
    [x, y, z] = [cy * x + sy * z, y, -sy * x + cy * z];
    y += g.turntableY; z += g.turntableAftZ;
    return [-z, x, -y]; // nedToRender(n,e,d) = [e, −d, −n] 의 역
  }

  /** 루트가 지면 위 발사 지점(NED 원점)에서 `rootOffsetNed` 만큼 밀려 놓였을 때, 크래들 로컬 Z가 zLocal인
   *  점의 절대 NED 위치(m) — `placeLauncher`가 하는 일 그대로. */
  function absoluteNed(pose: NonNullable<ReturnType<typeof launcherPose>>, zLocal: number): [number, number, number] {
    const local = nodePointToNed(pose.turntableY, pose.cradleX, zLocal);
    const off = pose.rootOffsetNed;
    return [off[0] + local[0] * S, off[1] + local[1] * S, off[2] + local[2] * S];
  }

  /** 기체 원점(레일 원점, 지면 위 origin_height)을 관 뒤끝 기준 관축 좌표로 — [관축 방향, 관축 아래]. */
  function inBore(l: typeof LAUNCH): [number, number] {
    const pose = launcherPose(l)!;
    const breech = absoluteNed(pose, g.tubeAftZ);
    const u = boresightNed(l.azimuth, pose.cradleX);
    const [rn, re, rd] = [0 - breech[0], 0 - breech[1], -l.origin_height - breech[2]];
    const along = rn * u[0] + re * u[1] + rd * u[2];
    const [sn, se, sd] = [rn - along * u[0], re - along * u[1], rd - along * u[2]];
    const below = Math.sign(sd) * Math.hypot(sn, se, sd); // NED d가 + = 아래
    return [along, below];
  }

  it("꼬리(원점 뒤 1.90 m)가 관 뒤끝보다 관축 방향으로 정확히 틈만큼 안쪽이다", () => {
    const [along] = inBore(LAUNCH);
    near(along - VEHICLE_AFT_EXTENT, TAIL_CLEARANCE, "꼬리 → 관 뒤끝", 1e-9);
  });

  it("회귀: 원점 높이가 피벗과 달라도 관축 방향으로 맞는다 — 수평만 맞추면 15°에서 0.11 m 뒤로 처졌다", () => {
    for (const h of [1.2, 2.9, 3.4]) {
      const [along] = inBore({ ...LAUNCH, origin_height: h });
      near(along - VEHICLE_AFT_EXTENT, TAIL_CLEARANCE, `원점 ${h} m`, 1e-9);
    }
  });

  it("15°·원점 2.9 m에서 기체는 관축 0.45 m 아래다 — 관 바닥은 이 자리에 맞춰 낮췄다(generate_launcher.py TUBE_ZLO)", () => {
    // 트레일러는 지면에 서고 기체는 시뮬 자리에 있으므로, 피벗 뒤에 담긴 꼬리 길이만큼 관축이 원점보다 높다.
    const [, below] = inBore(LAUNCH);
    near(below, (VEHICLE_AFT_EXTENT + TAIL_CLEARANCE - g.tubeAftZ * S) * Math.tan(15 * D2R), "관축 아래", 1e-9);
    assert.ok(below > 0.44 && below < 0.46, String(below));
    // 고각 0°면 관축 위에 있다
    near(inBore({ ...LAUNCH, elev_angle: 0 })[1], 0, "0°", 1e-9);
  });

  it("기체 코(원점 앞 1.75 m)는 포구(muzzleZ)에서 한참 안쪽 — 앞으로도 안 나온다", () => {
    const [along] = inBore(LAUNCH);
    const muzzle = (g.tubeAftZ - g.muzzleZ) * S;
    assert.ok(muzzle - (along + 1.75) > 3, `포구까지 여유가 3 m도 안 된다: ${muzzle - along - 1.75}`);
  });

  it("ψ = 90°에서도 성립한다 — 회전축에 의존하지 않는 관계다", () => {
    const [along, below] = inBore({ ...LAUNCH, azimuth: 90 * D2R });
    const [along0, below0] = inBore(LAUNCH);
    near(along, along0, "관축 방향", 1e-9);
    near(below, below0, "관축 아래", 1e-9);
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

describe("포구 문 — 처음부터 재생하면 문이 열린 뒤 발사가 흐른다", () => {
  /** three `rotation.y = a`를 경첩(원점) 둘레에 실제로 적용한다 — 부호를 손으로 따지지 않으려고. */
  const turnY = (a: number, [x, z]: [number, number]): [number, number] =>
    [Math.cos(a) * x + Math.sin(a) * z, -Math.sin(a) * x + Math.cos(a) * z];

  it("다 열면 두 짝이 **바깥·앞으로** 열린다 — 포구는 로컬 −Z", () => {
    const r = doorRotations(1);
    near(r.right, -LAUNCHER_GEOMETRY.doorOpenDeg * D2R, "우현");
    near(r.left, LAUNCHER_GEOMETRY.doorOpenDeg * D2R, "좌현");
    // 우현(+x) 문의 자유단은 경첩에서 −x 쪽에 있다. 열면 앞(−z)으로, 직각을 넘겨 바깥(+x)으로 비킨다
    const [rx, rz] = turnY(r.right, [-1, 0]);
    assert.ok(rz < -0.9 && rx > 0, `우현 문 자유단 ${rx}, ${rz}`);
    const [lx, lz] = turnY(r.left, [1, 0]);
    assert.ok(lz < -0.9 && lx < 0, `좌현 문 자유단 ${lx}, ${lz}`);
  });

  it("닫힘 0 · 범위를 넘는 값은 자른다", () => {
    near(doorRotations(0).right, 0, "닫힘");
    near(doorRotations(-1).left, 0, "음수");
    near(doorRotations(2).left, doorRotations(1).left, "넘침");
  });

  it("시뮬 시각이 0을 지나면(idx > 0) 늘 열려 있다 — 커서를 끌어 앞으로 가도", () => {
    assert.equal(doorOpenFraction(1, 0), 1);
    assert.equal(doorOpenFraction(500, 0), 1);
  });

  it("idx 0에서는 전주 시각을 따라 0 → 1로 매끄럽게 열린다", () => {
    assert.equal(doorOpenFraction(0, 0), 0);
    assert.equal(doorOpenFraction(0, DOOR_OPEN_S), 1);
    assert.equal(doorOpenFraction(0, PRELUDE_S), 1);
    let prev = -1;
    for (let k = 0; k <= 20; k++) {
      const f = doorOpenFraction(0, (DOOR_OPEN_S * k) / 20);
      assert.ok(f >= prev, `단조 증가 ${k}`);
      prev = f;
    }
    near(doorOpenFraction(0, DOOR_OPEN_S / 2), 0.5, "가운데", 1e-12);
    // 다 열린 뒤 잠깐 선다 — 문이 멈추기도 전에 기체가 튀어나오면 문이 기체를 쳐 내는 것처럼 보인다
    assert.ok(PRELUDE_S > DOOR_OPEN_S);
  });

  it("전주는 배속을 1배까지만 탄다 — 기본 5×에서도 문이 열리는 것이 보인다", () => {
    near(advancePrelude(0, 0.1, 5), 0.1, "5×");
    near(advancePrelude(0, 0.1, 0.5), 0.05, "0.5×는 그대로 느리게");
    near(advancePrelude(PRELUDE_S - 0.01, 0.1, 1), PRELUDE_S, "끝에서 멈춘다");
    near(advancePrelude(0.3, -1, 1), 0.3, "벽시계가 뒤로 가도 되감지 않는다");
  });

  it("기체가 관 안에서 시작할 때만 문을 닫아 둔다 — 레일 표지가 없으면 meta.launch를 믿는다", () => {
    assert.equal(startsInCanister(true), true);
    assert.equal(startsInCanister(null), true);
    assert.equal(startsInCanister(undefined), true);
    assert.equal(startsInCanister(false), false);
  });
});
