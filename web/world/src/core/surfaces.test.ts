import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { SURFACE_NOTES, propellerRate, skidCompression, surfacePose } from "./surfaces.ts";

const LIMITS = { elevon_lo: -0.35, elevon_hi: 0.35, rudder_lo: -0.35, rudder_hi: 0.35 };

/** 각도 비교 — 0.1 − 0.04가 0.060000000000000005이 되는 자리라 정확 일치는 못 쓴다.
 *  허용오차는 1 µrad: 화면에서 구분 불가능하고, 부호·믹싱 실수는 훨씬 크게 어긋난다. */
const near = (got: number, want: number, what = "") =>
  assert.ok(Math.abs(got - want) < 1e-6, `${what} ${got} ≠ ${want}`);

describe("타면 재구성 — 믹서 규약의 역", () => {
  it("좌 = de + da, 우 = de − da (fcl/mixer.py의 항등)", () => {
    const p = surfacePose(0.1, 0.04, 0)!;
    near(p.elevon.Elevon_In_L, 0.14, "좌");
    near(p.elevon.Elevon_In_R, 0.06, "우");
  });

  it("내측과 외측은 같다 — 시뮬이 둘을 구분하지 않는다", () => {
    const p = surfacePose(0.1, 0.04, 0)!;
    assert.equal(p.elevon.Elevon_In_L, p.elevon.Elevon_Out_L);
    assert.equal(p.elevon.Elevon_In_R, p.elevon.Elevon_Out_R);
  });

  it("순수 피치 명령은 4면을 같은 쪽으로 움직인다", () => {
    // 피치업 = 전 면 TE up = 음수 (models/shahed-136/README.md의 믹싱 예시)
    const p = surfacePose(-0.15, 0, 0)!;
    for (const v of Object.values(p.elevon)) near(v, -0.15);
  });

  it("순수 롤 명령은 좌우를 반대로 움직인다", () => {
    const p = surfacePose(0, 0.15, 0)!;
    near(p.elevon.Elevon_In_L, 0.15, "좌");
    near(p.elevon.Elevon_In_R, -0.15, "우");
    near(p.elevon.Elevon_In_L, -p.elevon.Elevon_In_R, "좌우 대칭");
  });

  it("재구성 항등이 왕복한다 — mean = de, (좌−우)/2 = da", () => {
    for (const [de, da] of [[0.1, 0.04], [-0.2, 0.11], [0, 0], [0.33, -0.02]] as const) {
      const p = surfacePose(de, da, 0)!;
      const four = [
        p.elevon.Elevon_In_L, p.elevon.Elevon_Out_L,
        p.elevon.Elevon_In_R, p.elevon.Elevon_Out_R,
      ];
      const mean = four.reduce((s, v) => s + v, 0) / 4;
      assert.ok(Math.abs(mean - de) < 1e-12, `mean ${mean} ≠ de ${de}`);
      assert.ok(Math.abs((four[0]! - four[2]!) / 2 - da) < 1e-12);
    }
  });

  it("러더 두 면은 같은 값 — 시뮬 채널이 하나다", () => {
    assert.equal(surfacePose(0, 0, 0.2)!.rudder, 0.2);
  });
});

describe("한계", () => {
  it("한계를 넘으면 자르고 **그 사실을 알린다**", () => {
    const p = surfacePose(0.3, 0.2, 0, LIMITS)!; // 좌 0.5 → 0.35
    assert.equal(p.elevon.Elevon_In_L, 0.35);
    assert.equal(p.clamped, true, "잘린 것을 조용히 숨기면 화면이 거짓말한다");
  });

  it("한계 안이면 자르지 않고 clamped도 거짓", () => {
    const p = surfacePose(0.1, 0.05, 0.1, LIMITS)!;
    near(p.elevon.Elevon_In_L, 0.15, "좌");
    assert.equal(p.clamped, false);
  });

  it("**한계가 null이면 자르지 않는다** — 서버가 실제로 보내는 모양이다", () => {
    // `simulator._effector_limits`는 다섯 키를 **항상** 내고 미상을 `None`으로 둔다.
    // 즉 프로덕션에서 오는 것은 "키 없음"이 아니라 "키가 null"이다. 이 케이스가 없으면
    // `typeof lo === "number"`를 `lo !== undefined`로 바꿔도 전부 초록인데(실측),
    // 그러면 `out < null`이 `out < 0`, `out > null`이 `out > 0`이 되어 **양·음 편향이
    // 전부 null로 잘린다.** 결과는 NaN이 아니라 더 나쁘다 — three가 `Math.cos(null)=1`,
    // `Math.sin(null)=0`으로 계산해 타면이 조용히 **중립에 앉는다.** 지어낸 중립은
    // 진짜 중립과 화면에서 구별되지 않는다(이 파일 머리말이 금하는 그것).
    const nulls = {
      elevon_lo: null, elevon_hi: null, rudder_lo: null, rudder_hi: null,
    };
    const p = surfacePose(-0.9, 0, 0.9, nulls)!;
    near(p.elevon.Elevon_In_L, -0.9, "좌");
    near(p.elevon.Elevon_In_R, -0.9, "우");
    near(p.rudder, 0.9, "러더");
    assert.equal(p.clamped, false, "없는 한계로 잘랐다고 말하면 안 된다");
  });

  it("null과 수가 섞여 있어도 수인 쪽만 건다", () => {
    const p = surfacePose(-0.9, 0, 0, { elevon_lo: -0.35, elevon_hi: null })!;
    near(p.elevon.Elevon_In_L, -0.35, "하한은 걸린다");
    assert.equal(p.clamped, true);
  });

  it("한계를 안 주면 자르지 않는다 — 없는 기준으로 옮기지 않는다", () => {
    const p = surfacePose(0.9, 0, 0.9)!;
    near(p.elevon.Elevon_In_L, 0.9, "좌");
    near(p.rudder, 0.9, "러더");
    assert.equal(p.clamped, false);
  });

  it("한계가 한쪽만 있어도 그쪽만 건다", () => {
    const p = surfacePose(-0.9, 0, 0, { elevon_lo: -0.35 })!;
    assert.equal(p.elevon.Elevon_In_L, -0.35);
    assert.equal(p.clamped, true);
  });
});

describe("결측", () => {
  it("하나라도 결측이면 null — 0으로 메우면 없는 중립 자세를 그린다", () => {
    assert.equal(surfacePose(null, 0, 0), null);
    assert.equal(surfacePose(0, null, 0), null);
    assert.equal(surfacePose(0, 0, null), null);
    assert.equal(surfacePose(undefined, 0, 0), null);
  });

  it('무한대 문자열도 결측으로 본다', () => {
    assert.equal(surfacePose("inf", 0, 0), null);
    assert.equal(surfacePose(0, "-inf", 0), null);
  });
});

describe("프로펠러 — 표시 값", () => {
  it("좌·우 스로틀 평균에 비례한다", () => {
    assert.equal(propellerRate(0.5, 0.5, 200), 100);
    assert.equal(propellerRate(0, 1, 200), 100);
  });

  it("0~1 밖 값은 눌러서 쓴다 (역회전·초과회전을 그리지 않는다)", () => {
    assert.equal(propellerRate(-0.5, -0.5, 200), 0);
    assert.equal(propellerRate(2, 2, 200), 200);
  });

  it("한쪽만 결측이면 null — 쌍발의 한쪽만 보고 회전을 지어내지 않는다", () => {
    assert.equal(propellerRate(0.8, null), null);
    assert.equal(propellerRate(null, 0.8), null);
  });
});

describe("스키드 압축 — 표시 근사", () => {
  it("반력을 네 점에 고르게 나눠 강성으로 나눈다", () => {
    // 54 kN/m × 4점 → 합 21.6 kN 이면 점당 5.4 kN → 0.1 m
    assert.ok(Math.abs(skidCompression(21600, 54000, 4, 0.12)! - 0.1) < 1e-12);
  });

  it("최대 행정에서 멈춘다 — 스키드가 동체를 뚫고 들어가지 않게", () => {
    assert.equal(skidCompression(1e9, 54000, 4, 0.12), 0.12);
  });

  it("음의 반력은 0으로 — 지면이 기체를 당기지 않는다", () => {
    assert.equal(skidCompression(-500), 0);
  });

  it("착륙장치 미장착(NaN)이면 null — 스키드를 움직이지 않는다", () => {
    // simulator.py는 장치가 없을 때 n_gear에 NaN을 넣고, 직렬화가 null로 바꾼다
    assert.equal(skidCompression(null), null);
    assert.equal(skidCompression(NaN), null);
  });
});

describe("공시 원장", () => {
  it("표시 전용 근사마다 캡션 문장이 있다", () => {
    // 다섯 자리다 — 내/외측 공유 · 러더 공유 · 프로펠러 표시값 · 스키드 표시 근사,
    // 그리고 결측 구간의 **각 유지**(그 동작 자체는 `scene/models.ts`에 있고 여기는
    // 문장만 든다). 문장이 없으면 화면이 그 선택을 밝힐 수단 자체가 없다.
    for (const key of [
      "innerOuterShared", "rudderShared", "propellerDisplay", "skidDisplay", "holdOnMissing",
    ] as const) {
      assert.ok(SURFACE_NOTES[key] && SURFACE_NOTES[key].length > 10, `${key} 문장이 없다`);
    }
  });

  it("스키드 문장이 **두 근사를 다** 말한다", () => {
    // 처음에는 '넷을 같이 누른다'만 적을 뻔했는데, 실제로 더 큰 오차는 감쇠 항이다.
    const n = SURFACE_NOTES.skidDisplay;
    assert.ok(n.includes("합"), "합만 있다는 사실");
    assert.ok(n.includes("감쇠"), "감쇠 항이 섞여 있다는 사실");
  });
});
