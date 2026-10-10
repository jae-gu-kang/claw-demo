import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  CENTERLINE_INSET_M, DECLINATION_RANGE_DEG, RUNWAY_LINE_LIFT_M, aimingPoint, centerlineLayout, designationDigits,
  runwayDesignation, runwayDrawing, runwayUniformValues,
} from "./runway.ts";
import { RUNWAY_FLOOR } from "./runwayfloor.ts";
import { siteRunwayWidth } from "../lib/replay.ts";
import { GOHEUNG } from "../../../js/lib/site.js";

const near = (got: number, want: number, what = "", tol = 1e-9) =>
  assert.ok(Math.abs(got - want) < tol, `${what} ${got} ≠ ${want}`);

/** 시뮬 탭 기본 폼이 보내는 고흥 활주로 — 결과 meta.runway가 그대로 되돌려 준다. 방위·길이는 lib/site.js GOHEUNG에서
 *  받는다 — 숫자로 옮겨 적었더니 축 보정(2026-09-27, 0.05964 → 0.05682 rad) 때 혼자 남아 폭 판정이 거절됐다. */
const GOHEUNG_RW = { heading: GOHEUNG.runwayHeadingRad, length: GOHEUNG.runwayLengthM, elevation: 4 };

/** 선분 [n0,e0,d0,n1,e1,d1] → 길이 [m] */
const lengthOf = (s: Float32Array) => Math.hypot(s[3]! - s[0]!, s[4]! - s[1]!, s[5]! - s[2]!);

describe("활주로 그리기 — 칠할 땅이 있으면 도색, 없으면 선", () => {
  const W = siteRunwayWidth(GOHEUNG_RW);

  it("지형이 있으면 포장면·도색을 지면에 칠하고 흰 선은 긋지 않는다 — 도색이 같은 자리를 그린다", () => {
    const d = runwayDrawing(GOHEUNG_RW, W, { paint: true })!;
    assert.equal(d.segments.length, 0);
    // 포장면 — 제원 폭(옛 22 m 반폭 상수가 아니다)·과주로(제원 대조가 함께 준다)·번호
    assert.deepEqual(d.surface, {
      heading: GOHEUNG_RW.heading, length: GOHEUNG_RW.length, width: 45, overrun: 61, designation: [1, 19],
    });
    assert.match(d.note, /폭 45 m는 고흥 시험장 제원 값입니다/);
    assert.match(d.note, /번호 01\/19/);
    assert.match(d.note, /과주로 61 m/);
    assert.match(d.note, /ICAO 부속서 14/);
  });

  it("**지형이 없으면 선으로 긋는다** — 도색은 지형 재질에만 있어, 선마저 빼면 활주로가 통째로 사라진다(리뷰 지적)", () => {
    const d = runwayDrawing(GOHEUNG_RW, W, { paint: false })!;
    assert.equal(d.surface, null, "칠할 땅이 없다");
    // 중심선 1 + 시단·종단 2 + 양 가장자리 2 — 선분마다 두 점(한 꺾은선에 이어 담으면 대각선이 그어진다)
    assert.equal(d.segments.length, 5);
    for (const seg of d.segments) assert.equal(seg.length, 6);
    const [center, bar0, bar1, edgeL, edgeR] = d.segments as [Float32Array, Float32Array, Float32Array,
      Float32Array, Float32Array];
    near(lengthOf(center), 1205, "중심선", 1e-3);
    near(lengthOf(bar0), 45, "시단 가로선", 1e-3);
    near(lengthOf(bar1), 45, "종단 가로선", 1e-3);
    near(lengthOf(edgeL), 1205, "왼 가장자리", 1e-3);
    near(lengthOf(edgeR), 1205, "오른 가장자리", 1e-3);
    // 가로선은 중심선에 수직이고, 가장자리는 중심선에서 반폭만큼 떨어져 나란하다
    const ax = [Math.cos(GOHEUNG_RW.heading), Math.sin(GOHEUNG_RW.heading)];
    near((bar0[3]! - bar0[0]!) * ax[0]! + (bar0[4]! - bar0[1]!) * ax[1]!, 0, "수직", 1e-3);
    // 자리도 본다 — 길이·수직만 보면 종단 막대를 시단에 긋거나 두 가장자리를 한쪽에 그어도 통과했다(v1.94 리뷰 변이)
    const along = (x: number, y: number) => x * ax[0]! + y * ax[1]!;
    const lateral = (x: number, y: number) => -(x * ax[1]!) + y * ax[0]!;
    for (const [seg, a, what] of [[bar0, 0, "시단 막대"], [bar1, 1205, "종단 막대"]] as const) {
      near(along(seg[0]!, seg[1]!), a, `${what} 자리`, 1e-3);
      near(along(seg[3]!, seg[4]!), a, `${what} 자리`, 1e-3);
    }
    for (const [seg, side, what] of [[edgeL, -1, "왼 가장자리"], [edgeR, 1, "오른 가장자리"]] as const) {
      near(lateral(seg[0]!, seg[1]!), side * 22.5, `${what} 횡거리(오른쪽이 +)`, 1e-3);
      near(lateral(seg[3]!, seg[4]!), side * 22.5, `${what} 횡거리(오른쪽이 +)`, 1e-3);
      near(along(seg[0]!, seg[1]!), 0, `${what} 시작`, 1e-3);
      near(along(seg[3]!, seg[4]!), 1205, `${what} 끝`, 1e-3);
    }
    assert.match(d.note, /폭 45 m는 고흥 시험장 제원 값입니다/);
    assert.match(d.note, /지형이 없어/);
    assert.doesNotMatch(d.note, /지면에 칠합니다/);
  });

  it("기본은 선이다 — 칠할 땅이 있다고 말하지 않은 호출측이 빈 활주로를 받지 않게", () => {
    assert.equal(runwayDrawing(GOHEUNG_RW, W)!.segments.length, 5);
  });

  it("과주로는 제원 대조에서만 받는다 — 대조가 안 주면 0 m, 시단 너머를 포장하지 않는다", () => {
    const d = runwayDrawing(GOHEUNG_RW, { width: 45, source: "시험 제원" }, { paint: true })!;
    assert.equal(d.surface!.overrun, 0);
    assert.doesNotMatch(d.note, /과주로/);
  });

  it("제원의 활주로와 다른 런이면 폭을 지어내지 않는다 — 칠할 땅이 있어도 중심선만 선으로, 사유는 캡션에", () => {
    const other = { heading: 1.2, length: 900, elevation: 0 };
    for (const paint of [true, false]) {
      const d = runwayDrawing(other, siteRunwayWidth(other), { paint })!;
      assert.equal(d.segments.length, 1);
      assert.equal(d.segments[0]!.length, 6);
      near(lengthOf(d.segments[0]!), 900, "중심선", 1e-3);
      assert.equal(d.surface, null, "폭을 모르면 포장면도 칠하지 않는다");
      assert.match(d.note, /^활주로는 중심선만 그립니다 — 폭을 모릅니다: 이 런의 활주로\(방위 1\.2 rad · 길이 900 m\)가 고흥 시험장 제원의 활주로/);
    }
  });

  it("흰 선은 펴진 바닥보다 조금 위다 — 같은 높이면 면과 깊이를 다퉈 깜빡이며 끊긴다", () => {
    // 근거리 패스의 깊이 눈금이 2 km에서 약 0.08 m다(SceneHost 머리말의 표) — 그보다 크고, 눈에는 안 띄게
    assert.ok(RUNWAY_LINE_LIFT_M > 0.08 && RUNWAY_LINE_LIFT_M < 0.5, `${RUNWAY_LINE_LIFT_M}`);
    for (const width of [{ error: "x" }, { width: 30, source: "시험 제원" }] as const) {
      const d = runwayDrawing({ heading: 0, length: 100, elevation: 4 }, width)!;
      for (const seg of d.segments) {
        near(seg[2]!, -(4 + RUNWAY_LINE_LIFT_M), "D", 1e-6);
        near(seg[5]!, -(4 + RUNWAY_LINE_LIFT_M), "D", 1e-6);
      }
    }
  });

  it("방위·길이가 없으면 그리지 않는다(표고만 없으면 0)", () => {
    assert.equal(runwayDrawing(null, { error: "x" }), null);
    assert.equal(runwayDrawing({ heading: 0.1 }, { error: "x" }), null);
    assert.equal(runwayDrawing({ length: 100 }, { error: "x" }), null);
    const d = runwayDrawing({ heading: 0, length: 100 }, { error: "x" })!;
    for (const seg of d.segments) { near(seg[2]!, -RUNWAY_LINE_LIFT_M, "D", 1e-6); near(seg[5]!, -RUNWAY_LINE_LIFT_M, "D", 1e-6); }
    const w = runwayDrawing({ heading: 0, length: 100 }, { width: 30, source: "시험 제원" }, { paint: true })!;
    assert.equal(w.surface!.width, 30);
  });
});

describe("runwayDesignation — 자방위 ÷ 10, 자편각 범위 양 끝에서 같을 때만", () => {
  const rad = (deg: number) => (deg * Math.PI) / 180;

  it("고흥 진방위 3.26°는 01, 맞은편 19 — 서편 6~10° 어디서든 자방위 9~13°", () => {
    assert.deepEqual(runwayDesignation(GOHEUNG.runwayHeadingRad), [1, 19]);
  });

  it("남향이면 19·01, 0은 36으로 쓴다", () => {
    assert.deepEqual(runwayDesignation(rad(180)), [19, 1]);
    assert.deepEqual(runwayDesignation(rad(352)), [36, 18]);
  });

  it("범위 안에서 번호가 갈리면 null — 번호를 지어내지 않는다", () => {
    // 진방위 7°: 자방위 13~17° — 01과 02 사이
    assert.equal(runwayDesignation(rad(7)), null);
    assert.ok(DECLINATION_RANGE_DEG[0] < DECLINATION_RANGE_DEG[1] && DECLINATION_RANGE_DEG[1] < 0, "서편 범위");
  });
});

describe("designationDigits — 셰이더에 넘길 번호 자리", () => {
  it("(시단 쪽 십·일, 맞은편 십·일) — 자리를 바꾸면 01이 10으로 칠해진다", () => {
    assert.deepEqual(designationDigits([1, 19]), [0, 1, 1, 9]);
    assert.deepEqual(designationDigits([36, 18]), [3, 6, 1, 8]);
  });

  it("번호를 모르면 -1 넷 — 셰이더가 번호를 칠하지 않는다", () => {
    assert.deepEqual(designationDigits(null), [-1, -1, -1, -1]);
  });
});

describe("runwayUniformValues — 셰이더 유니폼 자리(SceneHost.setRunwaySurface가 그대로 싣는다)", () => {
  it("축 (cos, sin, 길이, 반폭) · 착륙대 (과주로, 펴는 구역 반폭·끝 너머, 0) · 번호 (시단 쪽 십·일, 맞은편 십·일)", () => {
    const s = runwayDrawing(GOHEUNG_RW, siteRunwayWidth(GOHEUNG_RW), { paint: true })!.surface!;
    const v = runwayUniformValues(s);
    const h = GOHEUNG_RW.heading;
    assert.deepEqual(v.runway, [Math.cos(h), Math.sin(h), 1205, 22.5]);
    // 풀밭은 펴진 바닥과 같은 구역이다 — 두 수가 갈리면 풀밭 끝에서 땅이 기운다
    assert.deepEqual(v.area, [61, RUNWAY_FLOOR.halfWidthM, RUNWAY_FLOOR.endM, 0]);
    assert.deepEqual(v.num, [0, 1, 1, 9], "01/19 — 자리를 바꾸면 10/91로 칠해진다");
    assert.deepEqual(runwayUniformValues({ ...s, designation: null }).num, [-1, -1, -1, -1]);
    // 중심선 (줄 길이, 주기, 시단에서 시작, 0) · 조준점 (시작, 길이, 폭, 안쪽 간격) — 셰이더는 받은 대로 칠한다
    near(v.dash[0], 30, "줄 길이", 1e-9);
    near(v.dash[1], 51.85, "주기", 1e-9);
    assert.deepEqual(v.dash.slice(2), [CENTERLINE_INSET_M, 0]);
    assert.deepEqual(v.aim, [300, 45, 6, 18]);
    assert.deepEqual(runwayUniformValues({ ...s, length: 150 }).dash, [0, 0, CENTERLINE_INSET_M, 0], "중심선이 없으면 줄 길이 0");
  });
});

describe("centerlineLayout — 중심선 점선 배치(ICAO 부속서 14: 줄 + 칸 50~75 m, 줄 ≥ 칸·30 m)", () => {
  it("고흥 1,205 m는 30 m 줄 21개, 주기 51.85 m — 69~99 m에서 시작해 1,106~1,136 m에서 끝난다", () => {
    const c = centerlineLayout(1205)!;
    assert.equal(c.count, 21);
    near(c.stripe, 30, "줄", 1e-9);
    near(c.period, 51.85, "주기", 1e-9);
    const last = CENTERLINE_INSET_M + (c.count - 1) * c.period;
    near(last, 1106, "마지막 줄 시작", 1e-6);
    near(last + c.stripe, 1205 - CENTERLINE_INSET_M, "마지막 줄 끝 — 북쪽 첫 줄도 온 줄", 1e-6);
  });

  it("218 m부터 10 km까지 어느 길이든 규칙 안이고 양 끝이 온 줄로 끝난다 — 짧은 활주로에서 칸이 줄보다 길지 않다", () => {
    // 셰이더에서 셈하던 규칙은 418 m 아래에서 칸이 줄보다 길었고(30 m 줄에 칸 41 m), 168~218 m에서는 토막 줄이 붙었다
    // (v1.94 리뷰 측정 — 지금은 고흥만 칠하므로 닿지 않던 길)
    for (let L = 218; L <= 10_000; L += 0.5) {
      const c = centerlineLayout(L)!;
      const gap = c.period - c.stripe;
      const end = CENTERLINE_INSET_M + (c.count - 1) * c.period + c.stripe;
      assert.ok(c.count >= 2, `${L}`);
      assert.ok(c.period >= 50 - 1e-9 && c.period <= 75 + 1e-9, `${L}: 줄 + 칸 ${c.period}`);
      assert.ok(c.stripe >= 30 - 1e-9 && c.stripe >= gap - 1e-9, `${L}: 줄 ${c.stripe} · 칸 ${gap}`);
      assert.ok(Math.abs(end - (L - CENTERLINE_INSET_M)) < 1e-6, `${L}: 끝 ${end}`);
    }
  });

  it("구간이 80 m가 안 되면 줄 하나, 30 m가 안 되면 중심선이 없다(null)", () => {
    assert.equal(centerlineLayout(2 * CENTERLINE_INSET_M + 29.9), null);
    assert.equal(centerlineLayout(Number.NaN), null);
    assert.deepEqual(centerlineLayout(2 * CENTERLINE_INSET_M + 50), { stripe: 50, period: 0, count: 1 });
  });
});

describe("aimingPoint — 조준점(ICAO 부속서 14 표 5-1, 범위는 최솟값)", () => {
  it("착륙 거리의 열 — 800·1,200·2,400 m가 경계다", () => {
    assert.deepEqual(aimingPoint(799), [150, 30, 4, 6]);
    assert.deepEqual(aimingPoint(800), [250, 30, 6, 9]);
    assert.deepEqual(aimingPoint(1199), [250, 30, 6, 9]);
    assert.deepEqual(aimingPoint(1200), [300, 45, 6, 18]);
    assert.deepEqual(aimingPoint(1205), [300, 45, 6, 18], "고흥 — 300~345 m, 축에서 9~15 m");
    assert.deepEqual(aimingPoint(2399), [300, 45, 6, 18]);
    assert.deepEqual(aimingPoint(2400), [400, 45, 6, 18]);
  });
});
