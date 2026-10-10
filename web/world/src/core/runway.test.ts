import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { DECLINATION_RANGE_DEG, RUNWAY_LINE_LIFT_M, runwayDesignation, runwayDrawing } from "./runway.ts";
import { siteRunwayWidth } from "../lib/replay.ts";
import { GOHEUNG } from "../../../js/lib/site.js";

const near = (got: number, want: number, what = "", tol = 1e-9) =>
  assert.ok(Math.abs(got - want) < tol, `${what} ${got} ≠ ${want}`);

/** 시뮬 탭 기본 폼이 보내는 고흥 활주로 — 결과 meta.runway가 그대로 되돌려 준다. 방위·길이는 lib/site.js GOHEUNG에서
 *  받는다 — 숫자로 옮겨 적었더니 축 보정(2026-09-27, 0.05964 → 0.05682 rad) 때 혼자 남아 폭 판정이 거절됐다. */
const GOHEUNG_RW = { heading: GOHEUNG.runwayHeadingRad, length: GOHEUNG.runwayLengthM, elevation: 4 };

/** 선분 [n0,e0,d0,n1,e1,d1] → 길이 [m] */
const lengthOf = (s: Float32Array) => Math.hypot(s[3]! - s[0]!, s[4]! - s[1]!, s[5]! - s[2]!);

describe("활주로 그리기 — 폭을 알면 도색, 모르면 중심선 하나", () => {
  const SITE = { overrunM: GOHEUNG.runwayOverrunM };

  it("고흥 활주로면 포장면·도색을 지면에 칠하고 흰 선은 긋지 않는다 — 도색이 같은 자리를 그린다", () => {
    const d = runwayDrawing(GOHEUNG_RW, siteRunwayWidth(GOHEUNG_RW), SITE)!;
    assert.equal(d.segments.length, 0);
    // 포장면 — 제원 폭(옛 22 m 반폭 상수가 아니다)·과주로·번호
    assert.deepEqual(d.surface, {
      heading: GOHEUNG_RW.heading, length: GOHEUNG_RW.length, width: 45, overrun: 61, designation: [1, 19],
    });
    assert.match(d.note, /폭 45 m는 고흥 시험장 제원 값입니다/);
    assert.match(d.note, /번호 01\/19/);
    assert.match(d.note, /과주로 61 m/);
    assert.match(d.note, /ICAO 부속서 14/);
  });

  it("과주로를 모르면 0 m — 시단 너머를 포장하지 않는다", () => {
    const d = runwayDrawing(GOHEUNG_RW, siteRunwayWidth(GOHEUNG_RW))!;
    assert.equal(d.surface!.overrun, 0);
    assert.doesNotMatch(d.note, /과주로/);
  });

  it("제원의 활주로와 다른 런이면 폭을 지어내지 않는다 — 중심선만 선으로, 사유는 캡션에", () => {
    const other = { heading: 1.2, length: 900, elevation: 0 };
    const d = runwayDrawing(other, siteRunwayWidth(other), SITE)!;
    assert.equal(d.segments.length, 1);
    // 선분마다 두 점 — 한 꺾은선에 이어 담으면 선분 사이에 대각선이 그어진다
    assert.equal(d.segments[0]!.length, 6);
    near(lengthOf(d.segments[0]!), 900, "중심선", 1e-3);
    assert.equal(d.surface, null, "폭을 모르면 포장면도 칠하지 않는다");
    assert.match(d.note, /^활주로는 중심선만 그립니다 — 폭을 모릅니다: 이 런의 활주로\(방위 1\.2 rad · 길이 900 m\)가 고흥 시험장 제원의 활주로/);
  });

  it("흰 선은 펴진 바닥보다 조금 위다 — 같은 높이면 면과 깊이를 다퉈 깜빡이며 끊긴다", () => {
    // 근거리 패스의 깊이 눈금이 2 km에서 약 0.08 m다(SceneHost 머리말의 표) — 그보다 크고, 눈에는 안 띄게
    assert.ok(RUNWAY_LINE_LIFT_M > 0.08 && RUNWAY_LINE_LIFT_M < 0.5, `${RUNWAY_LINE_LIFT_M}`);
    const d = runwayDrawing({ heading: 0, length: 100, elevation: 4 }, { error: "x" })!;
    for (const s of d.segments) { near(s[2]!, -(4 + RUNWAY_LINE_LIFT_M), "D", 1e-6); near(s[5]!, -(4 + RUNWAY_LINE_LIFT_M), "D", 1e-6); }
  });

  it("방위·길이가 없으면 그리지 않는다(표고만 없으면 0)", () => {
    assert.equal(runwayDrawing(null, { error: "x" }), null);
    assert.equal(runwayDrawing({ heading: 0.1 }, { error: "x" }), null);
    assert.equal(runwayDrawing({ length: 100 }, { error: "x" }), null);
    const d = runwayDrawing({ heading: 0, length: 100 }, { error: "x" })!;
    for (const s of d.segments) { near(s[2]!, -RUNWAY_LINE_LIFT_M, "D", 1e-6); near(s[5]!, -RUNWAY_LINE_LIFT_M, "D", 1e-6); }
    const w = runwayDrawing({ heading: 0, length: 100 }, { width: 30, source: "시험 제원" })!;
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
