// 지면 패치의 치환 자리가 three 원문에 **그대로 있는가** — three를 올리다 청크 이름이 바뀌면
// `String.replace`가 조용히 아무것도 안 하고, 지형은 그림자나 피복 하나가 빠진 채 그럴듯하게 그려진다.
// 셰이더 컴파일 오류와 달리 콘솔에도 아무것도 안 남는 부류라 여기서 막는다.
//
// **three가 없으면 건너뛴다(사유를 남긴다).** 빠른 CI층은 npm 설치 없이 돌고(.github/workflows/fast.yml —
// 이 스위트는 자기 src만 들여온다는 전제), three는 web/world의 개발 의존이다. 대조할 원문이 없는 곳에서
// 실패로 세면 이 시험이 지키는 것과 무관한 빨간불이 된다. three를 올리는 일은 npm이 있는 개발 머신에서만
// 일어나므로, 이 시험이 필요한 순간에는 three가 있다.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { GROUND_ANCHORS } from "./materials.ts";

async function standardShader(t: { skip(msg: string): void }): Promise<{ vertexShader: string; fragmentShader: string } | null> {
  try {
    const three = await import("three");
    return three.ShaderLib.standard;
  } catch {
    t.skip("three 미설치 — 치환 자리를 대조할 원문이 없다(npm 설치가 없는 빠른 CI층)");
    return null;
  }
}

describe("applyGroundDetail — three 셰이더의 치환 자리", () => {
  const count = (src: string, s: string) => src.split(s).length - 1;

  it("정점 셰이더에 자리가 하나씩 있다", async (t) => {
    const std = await standardShader(t);
    if (std == null) return;
    for (const a of GROUND_ANCHORS.vertex) assert.equal(count(std.vertexShader, a), 1, a);
  });

  it("조각 셰이더에 자리가 하나씩 있고, 순서가 피복 → 법선 → 조명이다", async (t) => {
    const std = await standardShader(t);
    if (std == null) return;
    const fs = std.fragmentShader;
    for (const a of GROUND_ANCHORS.fragment) assert.equal(count(fs, a), 1, a);
    // 법선 단계가 피복 단계의 기울기를, 조명 단계가 피복 단계의 젖음·차폐를 읽는다
    const at = (s: string) => fs.indexOf(s);
    assert.ok(at("#include <metalnessmap_fragment>") < at("#include <normal_fragment_begin>"));
    assert.ok(at("#include <normal_fragment_begin>") < at("#include <lights_fragment_end>"));
  });
});
