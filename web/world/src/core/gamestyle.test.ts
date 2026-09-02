import { strict as assert } from "node:assert";
import { describe, it } from "node:test";

import { gameRamp, reliefOf } from "./gamestyle.ts";

const rgb = (elev: number, relief: number): [number, number, number] => {
  const out = new Float32Array(3);
  gameRamp(elev, relief, out, 0);
  return [out[0]!, out[1]!, out[2]!];
};

describe("reliefOf", () => {
  it("티어들의 최고 표고를 낸다", () => {
    assert.equal(reliefOf([{ elev_max: 320 }, { elev_max: 612 }]), 612);
  });

  it("헤더에 없으면 800으로 물러선다 — 0이면 전 지형이 눈이 된다", () => {
    assert.equal(reliefOf([{}]), 800);
    assert.equal(reliefOf([]), 800);
  });

  it("바다뿐인 팩(최고 표고 ~0)도 800으로 물러선다", () => {
    assert.equal(reliefOf([{ elev_max: 2 }]), 800);
  });
});

describe("gameRamp", () => {
  it("저지는 초록이 우세하고 정상부는 눈(밝은 무채색)이다", () => {
    const low = rgb(20, 600);
    const top = rgb(590, 600);
    assert.ok(low[1] > low[0] && low[1] > low[2], `저지 ${low}`);
    assert.ok(top[0] > 0.7 && top[1] > 0.7 && top[2] > 0.7, `정상 ${top}`);
  });

  it("중턱은 갈색 — 붉은 성분이 초록을 넘는다", () => {
    const mid = rgb(0.45 * 600, 600);
    assert.ok(mid[0] > mid[1], `중턱 ${mid}`);
  });

  it("정규화라 relief가 다르면 같은 절대 고도의 색이 다르다", () => {
    const a = rgb(400, 500);
    const b = rgb(400, 2000);
    assert.notDeepEqual(a, b);
  });

  it("범위 밖 고도는 클램프 — 음수·초과가 NaN을 만들지 않는다", () => {
    for (const v of rgb(-50, 600)) assert.ok(Number.isFinite(v));
    for (const v of rgb(5000, 600)) assert.ok(Number.isFinite(v));
  });

  it("선형으로 낸다 — 스톱 지점에서 정확히 sRGB^2.2 (뮤테이션 방어)", () => {
    // t=0은 보간 없이 첫 스톱 그대로라 기대값이 닫힌 식이다. 보간 지점(t≈0.03)에서
    // "< 0.67" 같은 문턱으로 재면 pow를 지워도 통과한다 — 리뷰 뮤테이션 실측.
    const low = rgb(0, 600);
    assert.ok(Math.abs(low[1] - Math.pow(0.67, 2.2)) < 1e-6, `g=${low[1]}`);
  });
});
