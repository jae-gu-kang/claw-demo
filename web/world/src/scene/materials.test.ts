// 지면 패치의 치환 자리가 three 원문에 **그대로 있는가** — three를 올리다 청크 이름이 바뀌면
// `String.replace`가 조용히 아무것도 안 하고, 지형은 그림자나 피복 하나가 빠진 채 그럴듯하게 그려진다.
// 셰이더 컴파일 오류와 달리 콘솔에도 아무것도 안 남는 부류라 여기서 막는다.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { ShaderLib } from "three";

import { GROUND_ANCHORS } from "./materials.ts";

describe("applyGroundDetail — three 셰이더의 치환 자리", () => {
  const std = ShaderLib.standard;
  const count = (src: string, s: string) => src.split(s).length - 1;

  it("정점 셰이더에 자리가 하나씩 있다", () => {
    for (const a of GROUND_ANCHORS.vertex) assert.equal(count(std.vertexShader, a), 1, a);
  });

  it("조각 셰이더에 자리가 하나씩 있고, 순서가 피복 → 법선 → 조명이다", () => {
    const fs = std.fragmentShader;
    for (const a of GROUND_ANCHORS.fragment) assert.equal(count(fs, a), 1, a);
    // 법선 단계가 피복 단계의 기울기를, 조명 단계가 피복 단계의 젖음·차폐를 읽는다
    const at = (s: string) => fs.indexOf(s);
    assert.ok(at("#include <metalnessmap_fragment>") < at("#include <normal_fragment_begin>"));
    assert.ok(at("#include <normal_fragment_begin>") < at("#include <lights_fragment_end>"));
  });
});
