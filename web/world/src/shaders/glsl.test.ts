import { strict as assert } from "node:assert";
import { describe, it } from "node:test";

import { ATMOSPHERE_GLSL, ATMOSPHERE_UNIFORM_DECL } from "./atmosphere.ts";
import { CLOUD_UNIFORM_DECL, cloudGlsl } from "./clouds.ts";
import {
  GROUND_FRAG_BODY, GROUND_GLSL, GROUND_LIGHT_BODY, GROUND_NORMAL_BODY, GROUND_UNIFORM_DECL,
  GROUND_VARYING_DECL, GROUND_VERT_BODY, GROUND_VERT_DECL,
} from "./ground.ts";
import { NOISE_GLSL } from "./noise.ts";
import { COAST_GLSL, OCEAN_FRAG, OCEAN_VERT } from "./ocean.ts";
import {
  WEAR_FRAG_BODY, WEAR_GLSL, WEAR_NORMAL_BODY, WEAR_UNIFORM_DECL, WEAR_VARYING_DECL,
  WEAR_VERT_BODY,
} from "./wear.ts";

const SOURCES: [string, string][] = [
  ["ATMOSPHERE_GLSL", ATMOSPHERE_GLSL],
  ["ATMOSPHERE_UNIFORM_DECL", ATMOSPHERE_UNIFORM_DECL],
  ["NOISE_GLSL", NOISE_GLSL],
  ["CLOUD_UNIFORM_DECL", CLOUD_UNIFORM_DECL],
  ["cloudGlsl(16,3)", cloudGlsl(16, 3)],
  ["cloudGlsl(3,1)", cloudGlsl(3, 1)],
  ["OCEAN_VERT", OCEAN_VERT],
  ["OCEAN_FRAG", OCEAN_FRAG],
  ["WEAR_UNIFORM_DECL", WEAR_UNIFORM_DECL],
  ["WEAR_VARYING_DECL", WEAR_VARYING_DECL],
  ["WEAR_VERT_BODY", WEAR_VERT_BODY],
  ["WEAR_GLSL", WEAR_GLSL],
  ["WEAR_FRAG_BODY", WEAR_FRAG_BODY],
  ["WEAR_NORMAL_BODY", WEAR_NORMAL_BODY],
  ["COAST_GLSL", COAST_GLSL],
  ["GROUND_UNIFORM_DECL", GROUND_UNIFORM_DECL],
  ["GROUND_VARYING_DECL", GROUND_VARYING_DECL],
  ["GROUND_VERT_DECL", GROUND_VERT_DECL],
  ["GROUND_VERT_BODY", GROUND_VERT_BODY],
  ["GROUND_GLSL", GROUND_GLSL],
  ["GROUND_FRAG_BODY", GROUND_FRAG_BODY],
  ["GROUND_NORMAL_BODY", GROUND_NORMAL_BODY],
  ["GROUND_LIGHT_BODY", GROUND_LIGHT_BODY],
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

  it("smoothstep의 경계를 거꾸로 주지 않는다 — GLSL·Metal 사양에서 결과가 정의되지 않는다", () => {
    // 지금 GPU에서 돌아가도 사양 밖이다. 뒤집힌 곡선이 필요하면 1.0 - smoothstep(낮은, 높은, x)로 쓴다.
    for (const [name, src] of SOURCES) {
      for (const m of src.matchAll(/smoothstep\(\s*(-?[0-9.]+)\s*,\s*(-?[0-9.]+)\s*,/g)) {
        assert.ok(Number(m[1]) < Number(m[2]), `${name}: ${m[0]}`);
      }
    }
  });

  it("두 패치가 함께 넣는 본문은 가드가 있다 — 지면·대기가 한 재질에 같은 함수를 넣는다", () => {
    // 지형 재질은 에어리얼 퍼스펙티브와 지면 패치가 둘 다 ATMOSPHERE_GLSL을 넣는다. 가드가 빠지면
    // 재정의로 컴파일이 깨지고 **지형만 조용히 사라진다**(셰이더 오류는 그 물체만 없앤다).
    for (const [name, src, guard] of [
      ["ATMOSPHERE_GLSL", ATMOSPHERE_GLSL, "ATMOSPHERE_GLSL_G"],
      ["COAST_GLSL", COAST_GLSL, "COAST_GLSL_G"],
      ["NOISE_GLSL", NOISE_GLSL, "NOISE_GLSL_G"],
    ] as const) {
      assert.match(src, new RegExp(`#ifndef ${guard}\\s*\\n#define ${guard}`), `${name} 가드`);
      assert.match(src.trimEnd(), /#endif$/, `${name}의 끝이 #endif가 아니다`);
    }
  });

  it("지면 셰이더의 화면 도함수는 분기·discard 앞 한 곳뿐이다", () => {
    // 갈라진 분기 안이나 discard 뒤의 fwidth·dFdx는 GLSL에서 정의되지 않는다 — 함수 본문(분기 안에서
    // 불린다)·조명 단계(discard 뒤)에 들어가면 쿼드 가장자리에서 걸음 수·무늬 접기가 튄다. 활주로 도색이 축마다
    // 발자국을 재므로 fwidth 하나 대신 dFdx·dFdy 한 쌍을 재고, 등방 발자국(grPw)은 그 둘에서 셈한다.
    for (const [name, src] of [["GROUND_GLSL", GROUND_GLSL], ["GROUND_NORMAL_BODY", GROUND_NORMAL_BODY],
      ["GROUND_LIGHT_BODY", GROUND_LIGHT_BODY]] as const) {
      assert.doesNotMatch(src, /\b(fwidth|dFdx|dFdy)\s*\(/, name);
    }
    const body = GROUND_FRAG_BODY;
    assert.doesNotMatch(body, /\bfwidth\s*\(/);
    assert.equal(body.match(/\bdFdx\s*\(/g)?.length, 1);
    assert.equal(body.match(/\bdFdy\s*\(/g)?.length, 1);
    assert.ok(body.includes("discard;"), "discard 문장이 있다");
    assert.ok(Math.max(body.indexOf("dFdx("), body.indexOf("dFdy(")) < body.indexOf("discard;"), "도함수가 discard보다 앞이다");
  });

  it("활주로 숫자의 획 표가 7획 표준과 같다 — 1만 가운데 막대라 0으로 둔다", () => {
    // a 위 1 · b 오른 위 2 · c 오른 아래 4 · d 아래 8 · e 왼 아래 16 · f 왼 위 32 · g 가운데 64
    const want = [63, 0, 91, 79, 102, 109, 125, 7, 127, 111];
    const m = GROUND_GLSL.match(/const int GR_SEG\[10\] = int\[10\]\(([^)]*)\)/);
    assert.ok(m, "GR_SEG 표가 없다");
    assert.deepEqual(m[1]!.split(",").map((v) => Number(v.trim())), want);
  });

  it("지면 정점·조각의 varying이 같은 선언 한 벌에서 나온다", () => {
    // 정점 선언은 조각과 같은 상수를 끼워 넣는다 — 손으로 두 벌 적다 한쪽만 고치는 일을 막는다
    assert.ok(GROUND_VERT_DECL.includes(GROUND_VARYING_DECL));
    for (const v of ["vGroundWorld", "vGroundNormal", "vGroundShade"]) {
      assert.match(GROUND_VERT_BODY, new RegExp(`\\b${v}\\s*=`), `${v}를 정점이 안 채운다`);
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
