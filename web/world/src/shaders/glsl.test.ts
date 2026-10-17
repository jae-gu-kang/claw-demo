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
  RUNWAY_GAME_FRAG_BODY, RUNWAY_GAME_GLSL, RUNWAY_GAME_VARYING_DECL, RUNWAY_GAME_VERT_BODY, RUNWAY_GLSL,
  RUNWAY_UNIFORM_DECL,
} from "./runway.ts";

const SOURCES: [string, string][] = [
  ["ATMOSPHERE_GLSL", ATMOSPHERE_GLSL],
  ["ATMOSPHERE_UNIFORM_DECL", ATMOSPHERE_UNIFORM_DECL],
  ["NOISE_GLSL", NOISE_GLSL],
  ["CLOUD_UNIFORM_DECL", CLOUD_UNIFORM_DECL],
  ["cloudGlsl(16,3)", cloudGlsl(16, 3)],
  ["cloudGlsl(3,1)", cloudGlsl(3, 1)],
  ["OCEAN_VERT", OCEAN_VERT],
  ["OCEAN_FRAG", OCEAN_FRAG],
  ["COAST_GLSL", COAST_GLSL],
  ["GROUND_UNIFORM_DECL", GROUND_UNIFORM_DECL],
  ["GROUND_VARYING_DECL", GROUND_VARYING_DECL],
  ["GROUND_VERT_DECL", GROUND_VERT_DECL],
  ["GROUND_VERT_BODY", GROUND_VERT_BODY],
  ["GROUND_GLSL", GROUND_GLSL],
  ["GROUND_FRAG_BODY", GROUND_FRAG_BODY],
  ["GROUND_NORMAL_BODY", GROUND_NORMAL_BODY],
  ["GROUND_LIGHT_BODY", GROUND_LIGHT_BODY],
  ["RUNWAY_UNIFORM_DECL", RUNWAY_UNIFORM_DECL],
  ["RUNWAY_GLSL", RUNWAY_GLSL],
  ["RUNWAY_GAME_VARYING_DECL", RUNWAY_GAME_VARYING_DECL],
  ["RUNWAY_GAME_VERT_BODY", RUNWAY_GAME_VERT_BODY],
  ["RUNWAY_GAME_GLSL", RUNWAY_GAME_GLSL],
  ["RUNWAY_GAME_FRAG_BODY", RUNWAY_GAME_FRAG_BODY],
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
      ["GROUND_LIGHT_BODY", GROUND_LIGHT_BODY], ["RUNWAY_GLSL", RUNWAY_GLSL]] as const) {
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
    const m = RUNWAY_GLSL.match(/const int GR_SEG\[10\] = int\[10\]\(([^)]*)\)/);
    assert.ok(m, "GR_SEG 표가 없다");
    assert.deepEqual(m[1]!.split(",").map((v) => Number(v.trim())), want);
  });

  it("게임 지형의 활주로 조각도 화면 도함수를 분기 앞 한 곳에서만 잰다", () => {
    // grAirfield는 uRunwayOn 분기 안에서 불린다 — 도함수는 그 앞에서 재 넘긴다(dxy)
    const body = RUNWAY_GAME_FRAG_BODY;
    assert.doesNotMatch(body, /\bfwidth\s*\(/);
    assert.equal(body.match(/\bdFdx\s*\(/g)?.length, 1);
    assert.equal(body.match(/\bdFdy\s*\(/g)?.length, 1);
    assert.ok(Math.max(body.indexOf("dFdx("), body.indexOf("dFdy(")) < body.indexOf("if (uRunwayOn"), "도함수가 분기보다 앞이다");
    assert.match(RUNWAY_GAME_VERT_BODY, /\bvRunwayWorld\s*=/, "정점이 세계 위치를 안 채운다");
    assert.match(RUNWAY_GAME_VARYING_DECL, /^\s*varying vec3 vRunwayWorld;/m);
  });

  it("활주로 자리·덮임은 한 벌 — 실사 지면과 게임 지형이 같은 함수를 부르고, 지면은 다시 정의하지 않는다", () => {
    // 두 지형이 각자 도색을 적으면 배치가 두 벌이 되어 한쪽만 고쳐진다. 지면 재질은 RUNWAY_GLSL과 GROUND_GLSL을 함께
    // 넣으므로 같은 이름을 GROUND_GLSL이 또 정의하면 재정의로 컴파일이 깨져 **지형만 조용히 사라진다**
    for (const [name, src] of [["GROUND_GLSL", GROUND_GLSL], ["RUNWAY_GAME_FRAG_BODY", RUNWAY_GAME_FRAG_BODY]] as const) {
      assert.match(src, /\bgrAirfield\(/, `${name}이 grAirfield를 안 부른다`);
      assert.match(src, /\bgrRunwayAxes\(/, `${name}이 grRunwayAxes를 안 부른다`);
    }
    const defs = [...RUNWAY_GLSL.matchAll(/^(?:float|vec[234]|int|void|bool)\s+(\w+)\s*\(/gm)].map((m) => m[1]!);
    for (const f of ["grBand", "grStripes", "grDigit", "grDesignation", "grPiano", "grCenterline", "grChevron",
      "grRunwayAxes", "grAirfield"]) {
      assert.ok(defs.includes(f), `RUNWAY_GLSL에 ${f}가 없다: ${defs.join(",")}`);
    }
    for (const f of [...defs, "GR_SEG"]) {
      assert.doesNotMatch(GROUND_GLSL, new RegExp(`^(?:const\\s+)?(?:float|vec[234]|int|void|bool)(?:\\[\\d+\\])?\\s+${f}\\b`, "m"), `GROUND_GLSL이 ${f}를 또 정의한다`);
    }
    // 유니폼 선언도 한 곳 — 지면 재질은 두 선언을 함께 넣는다
    for (const u of ["uRunway", "uRunwayOn", "uRunwayArea", "uRunwayNum"]) {
      assert.match(RUNWAY_UNIFORM_DECL, new RegExp(`^uniform \\w+ ${u};`, "m"), u);
      assert.doesNotMatch(GROUND_UNIFORM_DECL, new RegExp(`\\b${u}\\b`), `GROUND_UNIFORM_DECL에 ${u}가 또 있다`);
    }
  });

  it("두 지형의 화면 도함수는 어떤 분기보다도 앞이고, 세계 위치의 x·z를 (dFdx, dFdy) 순서로 넘긴다", () => {
    // 글의 순서만 보면 분기 **안**으로 옮긴 도함수(discard보다는 앞)가 통과했다. 축을 xy로 묶거나 dFdx·dFdy 자리를 바꿔도
    // 통과했다(v1.94 리뷰 변이) — 셰이더는 CI가 돌리지 못하므로 그 자리를 글로 묶는다
    const code = (src: string) => src.replace(/\/\/[^\n]*/g, "");
    for (const [name, body, world, packed] of [
      ["GROUND_FRAG_BODY", GROUND_FRAG_BODY, "vGroundWorld", "vec4(grDx.xz, grDy.xz)"],
      ["RUNWAY_GAME_FRAG_BODY", RUNWAY_GAME_FRAG_BODY, "vRunwayWorld", "vec4(rwDx.xz, rwDy.xz)"],
    ] as const) {
      const c = code(body);
      const first = Math.min(c.indexOf("dFdx("), c.indexOf("dFdy("));
      assert.ok(first > 0, `${name}: 도함수가 없다`);
      assert.doesNotMatch(c.slice(0, first), /\b(if|for|while|else|discard)\b|\?/, `${name}: 도함수 앞에 분기가 있다`);
      assert.match(c, new RegExp(`dFdx\\(${world}\\)`), `${name}: dFdx(${world})`);
      assert.match(c, new RegExp(`dFdy\\(${world}\\)`), `${name}: dFdy(${world})`);
      assert.ok(c.includes(packed), `${name}: ${packed}`);
    }
  });

  it("층은 바깥 층의 몫만 바꾼다 — 도색에 포장면 덮임을 한 번 더 곱하지 않는다", () => {
    // 측면 표지는 포장면 가장자리에 붙어 있어, 흰 덮임 × 포장면 덮임으로 섞으면 두 번 걸러져 멀리서 중심선보다 40 %
    // 어둡고 움직이면 깜빡였다(v1.94 리뷰 실측). grAirfield가 몫을 잘라 주고 두 지형은 더하기만 한다
    assert.match(RUNWAY_GLSL, /white = min\(white, paved\);/);
    assert.match(RUNWAY_GLSL, /return vec4\(field, paved, white, min\(yel, paved - white\)\);/);
    for (const [name, src] of [["GROUND_GLSL", GROUND_GLSL], ["RUNWAY_GAME_FRAG_BODY", RUNWAY_GAME_FRAG_BODY]] as const) {
      assert.doesNotMatch(src, /af\.[zw] \* (paved|af\.y)/, `${name}: 도색에 포장면을 또 곱한다`);
    }
    assert.match(GROUND_GLSL, /col \+= af\.z \* \(/);
    assert.match(RUNWAY_GAME_FRAG_BODY, /af\.z \* \(GAME_RW_PAINT - GAME_RW_ASPHALT\)/);
  });

  it("길이로 정해지는 배치(중심선 줄·주기, 조준점)는 셰이더가 셈하지 않고 유니폼으로 받는다 — core/runway.ts가 시험한다", () => {
    // 셰이더 안에서 셈하면 주기를 50 m로, 조준점을 250 m로 되돌려도 시험이 다 통과했다(v1.94 리뷰 변이)
    const center = RUNWAY_GLSL.match(/float grCenterline\([\s\S]*?\n\}/)?.[0] ?? "";
    assert.ok(center, "grCenterline이 없다");
    for (const k of ["uRunwayDash.x", "uRunwayDash.y", "uRunwayDash.z"]) assert.ok(center.includes(k), k);
    assert.doesNotMatch(center, /\b(50|84|138|69)\.0\b/, "중심선 배치 상수가 셰이더에 남았다");
    assert.doesNotMatch(RUNWAY_GLSL, /grAimSpec/);
    assert.match(RUNWAY_GLSL, /vec4 aim = uRunwayAim;/);
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
