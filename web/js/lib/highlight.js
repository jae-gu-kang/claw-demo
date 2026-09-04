/** 코드 색칠 — Python·C 토크나이저 (의존 0, eval 0).
 *
 * Autocode 탭이 내는 것은 **FCC에 그대로 실릴 코드**다. 그걸 회색 판에 통짜로
 * 부어 놓으면 주석과 실행문이 같은 무게로 읽히고, 리뷰어는 매번 눈으로 파싱한다.
 * 그래서 편집기와 같은 문법 색을 입힌다. CSP(default-src 'self')와 eval-free
 * 방침 때문에 하이라이터를 반입할 수 없어 여기서 직접 훑는다.
 *
 * ## 계약: 무손실
 *
 * `tokenize(code, lang).map(t => t.s).join("") === code` 가 **항상** 성립한다.
 * 색칠은 표시이고, 표시가 코드를 한 글자라도 바꾸면 그건 색칠이 아니라 위조다
 * (그 코드는 복사돼서 빌드로 들어간다). 테스트가 이 항등식을 먼저 잡는다.
 *
 * ## 파서가 아니다
 *
 * 문맥 없는 스캐너다 — 문자열·주석·수·식별자만 가른다. 타입 추론도, 매크로 전개도,
 * 괄호 짝도 보지 않는다. 잘못 칠할 수 있는 자리는 알고 남겨 둔다(아래 KNOWN):
 * 색이 틀려도 코드는 그대로이므로 손해가 표시에 갇힌다. 반대로 파서를 흉내 내면
 * 틀린 곳에서 조용히 멈추고, 그때 사라지는 것은 색이 아니라 **코드 뒷부분**이다.
 *
 * KNOWN — C에서 `'` 를 문자 리터럴로만 본다(C에 다른 뜻이 없다), Python f-문자열
 * 안의 `{expr}`은 통째로 문자열, 매크로 안의 주석은 주석이 이긴다(실제 컴파일러와 같다).
 */

/** 토큰 종류 — CSS 클래스 `cv-<k>`로 그대로 내려간다. ""는 색 없는 본문. */
export const KINDS = ["com", "str", "num", "kw", "typ", "fn", "pre", "op"];

const PY_KW = new Set([
  "and", "as", "assert", "async", "await", "break", "class", "continue", "def", "del",
  "elif", "else", "except", "finally", "for", "from", "global", "if", "import", "in",
  "is", "lambda", "nonlocal", "not", "or", "pass", "raise", "return", "try", "while",
  "with", "yield", "match", "case",
]);
const PY_TYP = new Set([
  "True", "False", "None", "self", "cls", "int", "float", "bool", "str", "bytes",
  "list", "dict", "set", "tuple", "object", "type", "len", "range", "enumerate", "zip",
  "print", "min", "max", "abs", "sum", "round", "isinstance", "super", "property",
  "staticmethod", "classmethod", "dataclass",
]);
const C_KW = new Set([
  "auto", "break", "case", "const", "continue", "default", "do", "else", "enum",
  "extern", "for", "goto", "if", "inline", "register", "restrict", "return", "sizeof",
  "static", "struct", "switch", "typedef", "union", "volatile", "while", "_Bool",
  "_Static_assert", "alignas", "alignof",
]);
const C_TYP = new Set([
  "char", "double", "float", "int", "long", "short", "signed", "unsigned", "void",
  "size_t", "ptrdiff_t", "bool", "true", "false", "NULL",
  "int8_t", "int16_t", "int32_t", "int64_t",
  "uint8_t", "uint16_t", "uint32_t", "uint64_t", "float32_t", "float64_t",
]);

const ID_START = /[A-Za-z_$À-￿]/;
const ID_PART = /[A-Za-z0-9_$À-￿]/;
const DIGIT = /[0-9]/;
const OP_CHARS = "+-*/%=<>!&|^~?:";

/** 언어 이름 정규화 — 모르는 이름은 색칠하지 않는다(통짜 본문 한 덩이). */
export function normalizeLang(lang) {
  const s = String(lang ?? "").toLowerCase();
  if (s === "py" || s === "python") return "python";
  if (s === "c" || s === "h" || s === "cpp" || s === "c-header") return "c";
  return "text";
}

/** 파일 이름 → 언어. 확장자만 본다 (탑재 코드 파일 탭이 쓴다). */
export function langOfFile(name) {
  const m = /\.([A-Za-z0-9]+)$/.exec(String(name ?? ""));
  if (!m) return "text";
  const ext = m[1].toLowerCase();
  if (ext === "py") return "python";
  if (ext === "c" || ext === "h") return "c";
  return "text";
}

/** 코드 → [{k, s}]. k는 KINDS 중 하나이거나 ""(본문). 이어 붙이면 원문 그대로. */
export function tokenize(code, lang) {
  const src = String(code ?? "");
  const kind = normalizeLang(lang);
  if (kind === "text" || src === "") return src === "" ? [] : [{ k: "", s: src }];
  const out = [];
  let plain = 0; // 아직 안 낸 본문의 시작 — 토큰마다 push하지 않고 모아서 낸다
  const flush = (i) => {
    if (i > plain) out.push({ k: "", s: src.slice(plain, i) });
  };
  const emit = (k, from, to) => {
    flush(from);
    out.push({ k, s: src.slice(from, to) });
    plain = to;
  };

  const py = kind === "python";
  const KW = py ? PY_KW : C_KW;
  const TYP = py ? PY_TYP : C_TYP;
  let i = 0;
  let lineStart = true; // C 전처리기는 줄머리에서만 — 식 안의 `#`는 전처리기가 아니다

  while (i < src.length) {
    const c = src[i];

    if (c === "\n") { i += 1; lineStart = true; continue; }
    if (c === " " || c === "\t" || c === "\r") { i += 1; continue; }

    // ── 주석 ──
    if (py && c === "#") { const s = i; i = eol(src, i); emit("com", s, i); lineStart = false; continue; }
    if (!py && c === "/" && src[i + 1] === "/") {
      const s = i; i = eol(src, i); emit("com", s, i); lineStart = false; continue;
    }
    if (!py && c === "/" && src[i + 1] === "*") {
      const s = i;
      const end = src.indexOf("*/", i + 2);
      i = end < 0 ? src.length : end + 2; // 안 닫혀도 끝까지 — 나머지를 잃지 않는다
      emit("com", s, i);
      lineStart = false;
      continue;
    }

    // ── 전처리기 (C) — 줄머리 `#`부터 줄 끝까지, 역슬래시 이어짐 포함 ──
    if (!py && c === "#" && lineStart) {
      const s = i;
      i = eol(src, i);
      while (src[i - 1] === "\\" || (src[i - 1] === "\r" && src[i - 2] === "\\")) {
        if (i >= src.length) break;
        i = eol(src, i + 1);
      }
      emit("pre", s, i);
      continue;
    }

    // ── 문자열 ──
    if (c === '"' || c === "'") {
      const s = i;
      const triple = py && src.slice(i, i + 3) === c.repeat(3);
      i = triple ? scanTriple(src, i, c) : scanQuoted(src, i, c, py);
      emit("str", s, i);
      lineStart = false;
      continue;
    }

    // ── 수 ── (`.5`는 앞이 수가 아닐 때만 — `a.5`는 C에 없고 py에선 문법 오류다)
    if (DIGIT.test(c) || (c === "." && DIGIT.test(src[i + 1] ?? ""))) {
      const s = i;
      i = scanNumber(src, i);
      emit("num", s, i);
      lineStart = false;
      continue;
    }

    // ── 데코레이터 (py) — `@` 하나만으로는 행렬곱과 못 가르니 뒤에 이름이 붙어야 한다 ──
    if (py && c === "@" && ID_START.test(src[i + 1] ?? "")) {
      const s = i;
      i += 1;
      while (i < src.length && (ID_PART.test(src[i]) || src[i] === ".")) i += 1;
      emit("pre", s, i);
      lineStart = false;
      continue;
    }

    // ── 식별자 ──
    if (ID_START.test(c)) {
      const s = i;
      while (i < src.length && ID_PART.test(src[i])) i += 1;
      const word = src.slice(s, i);
      // 호출 자리는 함수로 — 뒤 공백을 건너뛰고 `(`가 오는지만 본다. 선언인지
      // 호출인지는 문맥이라 여기서 가르지 않는다(둘 다 이름이 주인공인 자리다)
      const isCall = src[skipSpace(src, i)] === "(";
      const k = KW.has(word) ? "kw" : TYP.has(word) ? "typ" : isCall ? "fn" : "";
      if (k) emit(k, s, i);
      lineStart = false;
      continue;
    }

    // ── 연산자 — 묶어서 한 토큰 (`>>=`가 세 조각으로 갈리면 색이 깜빡인다) ──
    if (OP_CHARS.includes(c)) {
      const s = i;
      while (i < src.length && OP_CHARS.includes(src[i])) {
        // 주석 시작을 연산자가 삼키면 그 뒤 주석이 통째로 본문이 된다
        if (!py && src[i] === "/" && (src[i + 1] === "/" || src[i + 1] === "*")) break;
        i += 1;
      }
      if (i > s) { emit("op", s, i); lineStart = false; continue; }
    }

    i += 1;
    lineStart = false;
  }
  flush(src.length);
  return out;
}

const eol = (src, i) => {
  const n = src.indexOf("\n", i);
  return n < 0 ? src.length : n;
};

const skipSpace = (src, i) => {
  let j = i;
  while (j < src.length && (src[j] === " " || src[j] === "\t")) j += 1;
  return j;
};

/** 따옴표 하나짜리 문자열. Python은 줄을 넘지 않는다(넘으면 그 줄까지만 문자열) —
 *  안 닫힌 따옴표 하나에 파일 나머지가 통째로 문자열이 되는 것을 막는다. */
function scanQuoted(src, i, q, py) {
  let j = i + 1;
  while (j < src.length) {
    const ch = src[j];
    if (ch === "\\") { j += 2; continue; } // 이어짐(`\` + 개행)도 여기서 함께 넘어간다
    if (ch === q) return j + 1;
    if (ch === "\n" && py) return j;
    j += 1;
  }
  return src.length;
}

/** Python 삼중 따옴표 — 닫히지 않으면 끝까지. */
function scanTriple(src, i, q) {
  const close = src.indexOf(q.repeat(3), i + 3);
  return close < 0 ? src.length : close + 3;
}

/** 수 리터럴 — 진법 접두, 자릿수 구분, 지수, 접미(f·u·l·j). */
function scanNumber(src, i) {
  let j = i;
  if (src[j] === "0" && /[xXbBoO]/.test(src[j + 1] ?? "")) {
    j += 2;
    while (j < src.length && /[0-9a-fA-F_']/.test(src[j])) j += 1;
  } else {
    while (j < src.length && /[0-9_']/.test(src[j])) j += 1;
    if (src[j] === ".") {
      j += 1;
      while (j < src.length && /[0-9_']/.test(src[j])) j += 1;
    }
    if (/[eE]/.test(src[j] ?? "") && /[0-9+-]/.test(src[j + 1] ?? "")) {
      j += 2;
      while (j < src.length && DIGIT.test(src[j])) j += 1;
    }
  }
  while (j < src.length && /[uUlLfFjJ]/.test(src[j])) j += 1;
  return j;
}

/** 줄 수 — 거터(줄번호)가 코드와 **정확히 같은 줄 수**여야 어긋나지 않는다.
 *  마지막 줄이 개행으로 끝나면 그 뒤 빈 줄은 세지 않는다(편집기 관례). */
export function lineCount(code) {
  const s = String(code ?? "");
  if (s === "") return 1;
  const n = s.split("\n").length;
  return s.endsWith("\n") ? n - 1 : n;
}
