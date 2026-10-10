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

import { GAME_RUNWAY_ANCHORS, GROUND_ANCHORS, applyGameRunway, applyGroundDetail } from "./materials.ts";
import { GROUND_GLSL } from "../shaders/ground.ts";
import { RUNWAY_GAME_FRAG_BODY, RUNWAY_GAME_VERT_BODY, RUNWAY_GLSL, RUNWAY_UNIFORM_DECL } from "../shaders/runway.ts";

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

describe("applyGameRunway — 게임 지형에 활주로를 칠하는 치환 자리", () => {
  const count = (src: string, s: string) => src.split(s).length - 1;

  it("정점·조각 셰이더에 자리가 하나씩 있다", async (t) => {
    const std = await standardShader(t);
    if (std == null) return;
    for (const a of GAME_RUNWAY_ANCHORS.vertex) assert.equal(count(std.vertexShader, a), 1, a);
    for (const a of GAME_RUNWAY_ANCHORS.fragment) assert.equal(count(std.fragmentShader, a), 1, a);
  });
});

describe("지면·게임 지형 패치가 실제로 끼워 넣는다 — three 재질에 걸고 onBeforeCompile을 돌린다", () => {
  // 자리 이름만 맞아도 치환 문자열을 잘못 적으면(앵커를 지우거나 다른 자리에 넣으면) 화면은 조용히 틀린다.
  // three 재질에 실제로 걸어 컴파일 직전의 셰이더 문자열을 본다 — WebGL 없이 된다
  async function compiled(t: { skip(msg: string): void }, patch: (m: import("three").Material) => void) {
    let three: typeof import("three");
    try {
      three = await import("three");
    } catch {
      t.skip("three 미설치 — 패치를 걸 재질이 없다(npm 설치가 없는 빠른 CI층)");
      return null;
    }
    const mat = new three.MeshStandardMaterial({ vertexColors: true, flatShading: true });
    patch(mat);
    const std = three.ShaderLib.standard;
    const shader = { vertexShader: std.vertexShader, fragmentShader: std.fragmentShader, uniforms: {} as Record<string, unknown> };
    mat.onBeforeCompile(shader as never, {} as never);
    return { shader, key: mat.customProgramCacheKey() };
  }
  const uniforms = { uRunway: { value: 1 }, uRunwayOn: { value: 1 }, uRunwayArea: { value: 2 }, uRunwayNum: { value: 3 } };
  const count = (src: string, s: string) => src.split(s).length - 1;

  it("게임 지형 — 정점색이 곱해진 뒤 도색을 얹고, 유니폼은 넘긴 객체 그대로다", async (t) => {
    const r = await compiled(t, (m) => applyGameRunway(m, uniforms));
    if (r == null) return;
    const { vertexShader: vs, fragmentShader: fs } = r.shader;
    assert.ok(vs.indexOf(RUNWAY_GAME_VERT_BODY) > vs.indexOf("#include <fog_vertex>"), "정점 본문이 fog_vertex 뒤에 없다");
    assert.ok(fs.includes(RUNWAY_UNIFORM_DECL) && fs.includes(RUNWAY_GLSL), "도색 함수·유니폼 선언이 없다");
    assert.ok(fs.indexOf(RUNWAY_GLSL) < fs.indexOf("void main"), "도색 함수가 main 앞에 없다");
    const at = fs.indexOf(RUNWAY_GAME_FRAG_BODY);
    assert.ok(at > fs.indexOf("#include <color_fragment>"), "정점색 램프가 곱해지기 전에 칠한다");
    assert.ok(at < fs.indexOf("#include <normal_fragment_begin>"), "조명 앞에서 칠해야 낱면 음영이 탄다");
    for (const k of Object.keys(uniforms) as (keyof typeof uniforms)[]) {
      assert.equal(r.shader.uniforms[k], uniforms[k], `${k}는 SceneHost의 한 벌이어야 한다`);
    }
    assert.match(r.key, /^game-runway-v1\|/, "캐시 키 — 안 이으면 도색 없는 재질과 프로그램을 나눠 쓴다");
  });

  it("실사 지면 — 도색 함수가 지면 함수보다 앞이다(grCover가 부른다)", async (t) => {
    const r = await compiled(t, (m) => applyGroundDetail(m, uniforms));
    if (r == null) return;
    const fs = r.shader.fragmentShader;
    assert.ok(fs.includes(RUNWAY_GLSL) && fs.includes(GROUND_GLSL));
    assert.ok(fs.indexOf(RUNWAY_UNIFORM_DECL) < fs.indexOf(RUNWAY_GLSL));
    assert.ok(fs.indexOf(RUNWAY_GLSL) < fs.indexOf(GROUND_GLSL));
    assert.equal(count(fs, RUNWAY_GLSL), 1, "도색 함수가 두 번 들어가면 재정의로 깨진다");
  });
});
