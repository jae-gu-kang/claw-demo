import { strict as assert } from "node:assert";
import { describe, it } from "node:test";

import { ATMOSPHERE_GLSL, ATMOSPHERE_UNIFORM_DECL } from "./atmosphere.ts";
import { CLOUD_UNIFORM_DECL, cloudGlsl } from "./clouds.ts";
import { NOISE_GLSL } from "./noise.ts";
import { OCEAN_FRAG, OCEAN_VERT } from "./ocean.ts";

const SOURCES: [string, string][] = [
  ["ATMOSPHERE_GLSL", ATMOSPHERE_GLSL],
  ["ATMOSPHERE_UNIFORM_DECL", ATMOSPHERE_UNIFORM_DECL],
  ["NOISE_GLSL", NOISE_GLSL],
  ["CLOUD_UNIFORM_DECL", CLOUD_UNIFORM_DECL],
  ["cloudGlsl(16,3)", cloudGlsl(16, 3)],
  ["cloudGlsl(3,1)", cloudGlsl(3, 1)],
  ["OCEAN_VERT", OCEAN_VERT],
  ["OCEAN_FRAG", OCEAN_FRAG],
];

describe("GLSL 문자열", () => {
  it("**백틱이 없다** — 이 세션에서만 세 번 걸렸다", () => {
    // 템플릿 리터럴 안의 백틱은 문자열을 끊는다. 이스케이프하면 TS는 통과하지만
    // 백틱이 GLSL로 흘러가 셰이더 컴파일이 깨진다 — 화면이 통째로 검게 나오는 부류다.
    for (const [name, src] of SOURCES) {
      assert.ok(!src.includes("`"), `${name}에 백틱이 있다`);
    }
  });

  it("벡터 생성자에 정수 리터럴이 섞여 있지 않다 — 소수점을 남기는 습관을 지킨다", () => {
    // GLSL ES 3.00은 `vec3(1, 0.95, 0.88)`을 받아 주지만, 상수를 손으로 적을 때 `1`과
    // `1.0`이 섞이면 읽는 사람이 정수 산술을 의심하게 된다. `glsl()` 포맷터가 막는 것을
    // 여기서 다시 확인한다. `float(i)` 같은 변환 호출은 정수를 넣는 것이 **맞으므로** 뺀다.
    const bad = /\bvec[234]\s*\(\s*-?\d+\s*[,)]/;
    for (const [name, src] of SOURCES) {
      const m = src.match(bad);
      assert.equal(m, null, `${name}: ${m?.[0]}`);
    }
  });

  it("괄호와 중괄호가 맞는다 — 문자열을 이어 붙이다 한쪽만 빠지기 쉽다", () => {
    for (const [name, src] of SOURCES) {
      const code = src.replace(/\/\/[^\n]*/g, "");
      let curly = 0; let paren = 0;
      for (const ch of code) {
        if (ch === "{") curly++;
        if (ch === "}") curly--;
        if (ch === "(") paren++;
        if (ch === ")") paren--;
        assert.ok(curly >= 0 && paren >= 0, `${name}: 닫는 괄호가 먼저 나온다`);
      }
      assert.equal(curly, 0, `${name}: 중괄호 ${curly}`);
      assert.equal(paren, 0, `${name}: 소괄호 ${paren}`);
    }
  });

  it("**varying이 정점·조각 양쪽에 같은 이름으로 선언돼 있다**", () => {
    // 한쪽에서 빠지면 셰이더 컴파일이 깨지고 그 물체만 통째로 사라진다. 문자열을
    // 자동 치환하다 선언 한 줄이 잘려 나간 적이 있는데(`varying vec3 vWorld;` →
    // `ec3 vWorld;`), 화면에서는 "바다가 없다"로만 보여서 원인을 한참 못 찾았다.
    // 괄호 균형 검사로는 안 잡힌다 — 중괄호는 그대로였다.
    const decls = (src: string) => new Set(
      [...src.matchAll(/^\s*varying\s+(\w+)\s+(\w+)\s*;/gm)].map((m) => `${m[1]} ${m[2]}`),
    );
    const used = (src: string, name: string) =>
      new RegExp(`\\b${name}\\b`).test(src.replace(/^\s*varying[^\n]*$/gm, ""));

    const vs = decls(OCEAN_VERT);
    const fs = decls(OCEAN_FRAG);
    assert.ok(vs.size > 0, "OCEAN_VERT에 varying 선언이 하나도 없다");
    for (const d of fs) {
      assert.ok(vs.has(d), `조각에만 있는 varying: ${d}`);
    }
    // 조각이 쓰는 이름은 조각이 선언했어야 한다.
    for (const d of vs) {
      const name = d.split(" ")[1]!;
      if (used(OCEAN_FRAG, name)) assert.ok(fs.has(d), `조각이 ${name}을 쓰는데 선언이 없다`);
    }
  });

  it("대기 함수를 쓰는 셰이더는 그 유니폼 선언과 짝을 이룬다", () => {
    // 선언을 빼먹으면 셰이더 컴파일이 깨진다. 여기서 잡으면 브라우저를 안 열어도 안다.
    for (const [name, src] of [["OCEAN_FRAG", OCEAN_FRAG]] as [string, string][]) {
      if (!/skyRadiance|sunThroughAtmosphere|atmosphere\(/.test(src)) continue;
      for (const u of ["uSunDirWorld", "uSunIntensity", "uHaze"]) {
        assert.ok(
          ATMOSPHERE_UNIFORM_DECL.includes(u),
          `${name}이 대기 함수를 쓰는데 ${u} 선언이 공용 선언에 없다`,
        );
      }
    }
  });
});
