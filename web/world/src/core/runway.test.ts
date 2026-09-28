import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { runwayDrawing } from "./runway.ts";
import { siteRunwayWidth } from "../lib/replay.ts";
import { GOHEUNG } from "../../../js/lib/site.js";

const near = (got: number, want: number, what = "", tol = 1e-9) =>
  assert.ok(Math.abs(got - want) < tol, `${what} ${got} ≠ ${want}`);

/** 시뮬 탭 기본 폼이 보내는 고흥 활주로 — 결과 meta.runway가 그대로 되돌려 준다. 방위·길이는 lib/site.js GOHEUNG에서
 *  받는다 — 숫자로 옮겨 적었더니 축 보정(2026-09-27, 0.05964 → 0.05682 rad) 때 혼자 남아 폭 판정이 거절됐다. */
const GOHEUNG_RW = { heading: GOHEUNG.runwayHeadingRad, length: GOHEUNG.runwayLengthM, elevation: 4 };

/** 선분 [n0,e0,d0,n1,e1,d1] → 길이 [m] */
const lengthOf = (s: Float32Array) => Math.hypot(s[3]! - s[0]!, s[4]! - s[1]!, s[5]! - s[2]!);

describe("활주로 표시선 — 폭은 시험장 제원에서, 선분은 따로", () => {
  it("고흥 활주로면 시단·종단 가로선이 제원 폭(45 m) 그대로다 — 옛 22 m 반폭 상수가 아니다", () => {
    const d = runwayDrawing(GOHEUNG_RW, siteRunwayWidth(GOHEUNG_RW))!;
    // 중심선 1 + 시단·종단 2 + 양 가장자리 2
    assert.equal(d.segments.length, 5);
    const [center, bar0, bar1, edgeL, edgeR] = d.segments as [Float32Array, Float32Array, Float32Array,
      Float32Array, Float32Array];
    near(lengthOf(center), 1205, "중심선", 1e-3);
    near(lengthOf(bar0), 45, "시단 가로선", 1e-3);
    near(lengthOf(bar1), 45, "종단 가로선", 1e-3);
    near(lengthOf(edgeL), 1205, "왼 가장자리", 1e-3);
    near(lengthOf(edgeR), 1205, "오른 가장자리", 1e-3);
    // 가로선은 중심선에 수직이고 중심선 끝점에서 둘로 나뉜다(반폭 22.5 m씩)
    const ax = [Math.cos(GOHEUNG_RW.heading), Math.sin(GOHEUNG_RW.heading)];
    const dot = (bar0[3]! - bar0[0]!) * ax[0]! + (bar0[4]! - bar0[1]!) * ax[1]!;
    near(dot, 0, "수직", 1e-3);
    near((bar1[0]! + bar1[3]!) / 2, center[3]!, "종단 가로선 가운데 N", 1e-3);
    near((bar1[1]! + bar1[4]!) / 2, center[4]!, "종단 가로선 가운데 E", 1e-3);
    // 가장자리는 중심선에서 반폭만큼 떨어져 나란하다
    const lateral = (x: number, y: number) => -(x * ax[1]!) + y * ax[0]!;
    near(Math.abs(lateral(edgeL[0]!, edgeL[1]!)), 22.5, "왼 가장자리 횡거리", 1e-3);
    near(Math.abs(lateral(edgeR[3]!, edgeR[4]!)), 22.5, "오른 가장자리 횡거리", 1e-3);
    // 표고는 D = −표고
    for (const s of d.segments) { near(s[2]!, -4, "D"); near(s[5]!, -4, "D"); }
    assert.match(d.note, /폭 45 m는 고흥 시험장 제원 값입니다/);
    assert.doesNotMatch(d.note, /폭은 결과에 없습니다/);
  });

  it("선분마다 두 점이다 — 한 꺾은선에 이어 담으면 중심선 끝에서 시단 가로선으로 대각선이 그어진다", () => {
    const d = runwayDrawing(GOHEUNG_RW, siteRunwayWidth(GOHEUNG_RW))!;
    for (const s of d.segments) assert.equal(s.length, 6);
  });

  it("제원의 활주로와 다른 런이면 폭을 지어내지 않는다 — 중심선만, 사유는 캡션에", () => {
    const other = { heading: 1.2, length: 900, elevation: 0 };
    const d = runwayDrawing(other, siteRunwayWidth(other))!;
    assert.equal(d.segments.length, 1);
    near(lengthOf(d.segments[0]!), 900, "중심선", 1e-3);
    assert.match(d.note, /^활주로는 중심선만 그립니다 — 폭을 모릅니다: 이 런의 활주로\(방위 1\.2 rad · 길이 900 m\)가 고흥 시험장 제원의 활주로/);
  });

  it("방위·길이가 없으면 그리지 않는다(표고만 없으면 0)", () => {
    assert.equal(runwayDrawing(null, { error: "x" }), null);
    assert.equal(runwayDrawing({ heading: 0.1 }, { error: "x" }), null);
    assert.equal(runwayDrawing({ length: 100 }, { error: "x" }), null);
    const d = runwayDrawing({ heading: 0, length: 100 }, { width: 30, source: "시험 제원" })!;
    for (const s of d.segments) { near(s[2]!, 0, "D"); near(s[5]!, 0, "D"); }
    near(lengthOf(d.segments[1]!), 30, "가로선", 1e-9);
  });
});
