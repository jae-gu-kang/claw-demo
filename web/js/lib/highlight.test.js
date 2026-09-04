// 코드 색칠 토크나이저 — 무손실 계약이 먼저다 (색이 코드를 바꾸면 안 된다)
import { test } from "node:test";
import assert from "node:assert/strict";

import { KINDS, langOfFile, lineCount, normalizeLang, tokenize } from "./highlight.js";

/** 이 파일 전체가 기대는 계약 — 이어 붙이면 원문 그대로, 종류는 아는 것뿐. */
function roundtrip(code, lang) {
  const toks = tokenize(code, lang);
  assert.equal(toks.map((t) => t.s).join(""), code, "무손실 위반");
  for (const t of toks) {
    assert.ok(t.k === "" || KINDS.includes(t.k), `모르는 종류 ${t.k}`);
    assert.ok(t.s.length > 0, "빈 토큰");
  }
  return toks;
}

const kindsOf = (toks, k) => toks.filter((t) => t.k === k).map((t) => t.s);

test("무손실 — 어떤 입력이든 이어 붙이면 원문 (색칠은 표시이지 편집이 아니다)", () => {
  const samples = [
    "", "\n", "   ", "x", "def f(a, b):\n    return a + b\n",
    "int main(void) { return 0; }\n",
    "/* 안 닫힌 주석", "'안 닫힌 문자열", '"""안 닫힌 삼중',
    "#define A(x) ((x) * 2)\n", "a = 0x1F_u + .5e-3f;\n",
    "한글 주석 # 이것도\n", "x = '\\''", "y = \"a\\\\\"", "@decorator\ndef g(): pass",
  ];
  for (const s of samples) {
    for (const lang of ["python", "c", "text", "말도 안 되는 언어"]) roundtrip(s, lang);
  }
});

test("python: 주석·문자열·수·키워드·호출", () => {
  const src = "def solve(n: int = 3) -> float:  # 답\n    return 1.5e-2 * n\n";
  const t = roundtrip(src, "python");
  assert.deepEqual(kindsOf(t, "com"), ["# 답"]);
  assert.deepEqual(kindsOf(t, "kw"), ["def", "return"]);
  assert.deepEqual(kindsOf(t, "typ"), ["int", "float"]);
  assert.deepEqual(kindsOf(t, "fn"), ["solve"]);
  assert.deepEqual(kindsOf(t, "num"), ["3", "1.5e-2"]);
});

test("python: 삼중 따옴표는 여러 줄 하나 — 안의 #는 주석이 아니다", () => {
  const t = roundtrip('x = """줄1\n# 주석 아님\n줄3"""\n', "python");
  assert.deepEqual(kindsOf(t, "str"), ['"""줄1\n# 주석 아님\n줄3"""']);
  assert.equal(kindsOf(t, "com").length, 0);
});

test("python: 안 닫힌 따옴표는 그 줄까지 — 파일 나머지를 삼키지 않는다", () => {
  const t = roundtrip("a = 'oops\nb = 1\n", "python");
  assert.deepEqual(kindsOf(t, "str"), ["'oops"]);
  assert.deepEqual(kindsOf(t, "num"), ["1"]); // 다음 줄이 살아 있다
});

test("python: 데코레이터는 붙지만 행렬곱 @는 아니다", () => {
  assert.deepEqual(kindsOf(roundtrip("@dataclass\nclass X: pass", "python"), "pre"),
    ["@dataclass"]);
  assert.deepEqual(kindsOf(roundtrip("z = a @ b", "python"), "pre"), []);
});

test("C: 블록·줄 주석, 전처리기, 접미가 붙은 수", () => {
  const src = "#include <math.h>\n// 줄 주석\nstatic float g = 9.81f; /* 블록 */\n";
  const t = roundtrip(src, "c");
  assert.deepEqual(kindsOf(t, "pre"), ["#include <math.h>"]);
  assert.deepEqual(kindsOf(t, "com"), ["// 줄 주석", "/* 블록 */"]);
  assert.deepEqual(kindsOf(t, "kw"), ["static"]);
  assert.deepEqual(kindsOf(t, "typ"), ["float"]);
  assert.deepEqual(kindsOf(t, "num"), ["9.81f"]);
});

test("C: 여러 줄 매크로는 역슬래시 이어짐까지 한 토큰", () => {
  const t = roundtrip("#define M(a) \\\n  ((a) + 1)\nint x;\n", "c");
  assert.deepEqual(kindsOf(t, "pre"), ["#define M(a) \\\n  ((a) + 1)"]);
  assert.deepEqual(kindsOf(t, "typ"), ["int"]);
});

test("C: 줄머리가 아닌 #는 전처리기가 아니다 (문자열 안의 #도)", () => {
  assert.deepEqual(kindsOf(roundtrip('puts("a#b"); x = 1;\n', "c"), "pre"), []);
  // 들여쓴 #는 전처리기가 맞다 — C는 줄머리 공백을 허용한다
  assert.deepEqual(kindsOf(roundtrip("  #endif\n", "c"), "pre"), ["  #endif".trimStart()]);
});

test("C: 안 닫힌 블록 주석은 끝까지 — 뒤를 잃느니 전부 주석", () => {
  const t = roundtrip("int a;\n/* 여기서 안 닫힘\nint b;\n", "c");
  assert.deepEqual(kindsOf(t, "com"), ["/* 여기서 안 닫힘\nint b;\n"]);
});

test("연산자는 묶인다 — 주석 시작은 삼키지 않는다", () => {
  assert.deepEqual(kindsOf(roundtrip("a >>= b;", "c"), "op"), [">>="]);
  const t = roundtrip("a = b / c; // 나눗셈\n", "c");
  assert.deepEqual(kindsOf(t, "com"), ["// 나눗셈"]);
  const t2 = roundtrip("a =/* 붙은 주석 */b;", "c");
  assert.deepEqual(kindsOf(t2, "com"), ["/* 붙은 주석 */"]);
});

test("text·미지 언어는 통짜 한 덩이 — 잘못 칠하느니 안 칠한다", () => {
  assert.deepEqual(tokenize("def f(): pass", "text"), [{ k: "", s: "def f(): pass" }]);
  assert.deepEqual(tokenize("", "text"), []);
});

test("normalizeLang·langOfFile", () => {
  assert.equal(normalizeLang("PY"), "python");
  assert.equal(normalizeLang("Python"), "python");
  assert.equal(normalizeLang("h"), "c");
  assert.equal(normalizeLang("rust"), "text");
  assert.equal(normalizeLang(null), "text");
  assert.equal(langOfFile("fcl_scas.c"), "c");
  assert.equal(langOfFile("fcl.h"), "c");
  assert.equal(langOfFile("snapshot.py"), "python");
  assert.equal(langOfFile("README"), "text");
  assert.equal(langOfFile(null), "text");
});

test("lineCount: 거터가 코드와 같은 줄 수여야 어긋나지 않는다", () => {
  assert.equal(lineCount(""), 1);
  assert.equal(lineCount("a"), 1);
  assert.equal(lineCount("a\n"), 1);   // 끝 개행은 새 줄이 아니다
  assert.equal(lineCount("a\nb"), 2);
  assert.equal(lineCount("a\nb\n"), 2);
  assert.equal(lineCount("\n"), 1);
});
