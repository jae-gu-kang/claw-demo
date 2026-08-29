/** 설계 형상 → 코드 텍스트(Python·C 헤더) + 검토 자료 — 순수 계층.

여기서 만드는 것은 **탑재 비행코드가 아니라 현재 설계 형상의 코드 표현**이다:
로직을 생성하지 않고 파라미터 값만 낸다 (02 §1의 제외 항목이 아니라, 같은 문서
§2.2·03 M7이 예비해 둔 "코드젠 모듈이 소비할 구조"의 첫 소비자).

파이썬 클래스·임포트 경로는 추측하지 않는다 — 서버
POST /registry/{category}/{name}/validate가 엔진 인스턴스에서 얻어 준 값을
그대로 쓴다(nav/ErrorModel의 실제 클래스는 NavErrorModel — 이름 추론 불가).

DOM·네트워크 없음. 뷰(views/codegen.js)는 이 결과를 표시만 한다.

스펙 형태:
  {key, pyImport, pyClass, varName, cPrefix, kind:"object"|"dict",
   fields, values, desc, notes, hint, applied}
  fields = schemaform.schemaFields() 결과에서 omit 적용 후, values = 폼 현재값
*/

/** 스펙 하나를 가리키는 이름 — **key로는 모자란다.** 한 스키마를 여러 번 싣는
블록이 있다(SCAS 3축은 셋 다 fcl/ScasAxis다). key를 식별자로 쓰면 lineOf가
서로를 덮어써서 추적성 표의 세 축이 전부 마지막 축의 줄을 가리킨다 — 그 표는
산출물에 그대로 옮기는 물건이라 틀린 줄이 문서로 나간다.
varName은 스냅샷 안에서 유일하다 (lib/blocks.js 계약 테스트가 핀한다). */
export function specLabel(spec) {
  return spec.varName ?? spec.key;
}

/** 엔진 무제한 센티널 (blocks/base UNBOUNDED) — inf가 아니므로 코드에도 1e+30으로 낸다. */
export const UNBOUNDED = 1e30;

/** float32 유효자리 (C 헤더 정밀도 경고 기준). */
const F32_DIGITS = 7;

const isUnbounded = (v) => typeof v === "number" && Math.abs(v) >= UNBOUNDED;

/** 소수점 강제 — "30" → "30.0". 지수 표기는 이미 실수 리터럴이라 그대로.
Python에서 int/float가 갈리고 C에서 `30f`는 문법 오류라 양쪽 모두 필요. */
function decimalize(s) {
  return /[.eE]/.test(s) ? s : `${s}.0`;
}

/** 표시용 수치 — 무제한 센티널은 사람이 읽는 말로 (코드 리터럴 아님). */
export function numDisplay(v) {
  if (isUnbounded(v)) return v > 0 ? "무제한" : "−무제한";
  return String(v);
}

/** Python 리터럴 — String(v)는 되읽으면 원값이 되는 최단 표현(왕복 보장). */
export function pyLiteral(v, type = "number") {
  if (typeof v === "boolean") return v ? "True" : "False";
  if (typeof v === "string") return JSON.stringify(v);
  if (Array.isArray(v)) return `[${v.map((x) => pyLiteral(x, type)).join(", ")}]`;
  if (type === "integer") return String(v);
  return decimalize(String(v));
}

/** C 리터럴 — 실수는 float 접미사(비행 코드 관행). bool은 <stdbool.h> 전제. */
export function cLiteral(v, type = "number") {
  if (typeof v === "boolean") return v ? "true" : "false";
  if (typeof v === "string") return JSON.stringify(v);
  if (Array.isArray(v)) return `{${v.map((x) => cLiteral(x, type)).join(", ")}}`;
  if (type === "integer") return String(v);
  return `${decimalize(String(v))}f`;
}

/** "AP" + "kp_spd" → "AP_KP_SPD" (점·하이픈은 밑줄 — 게인명 "pitch.kp" 대응). */
export function cMacro(prefix, name) {
  const body = String(name).replace(/[.\-\s]+/g, "_").toUpperCase();
  return prefix ? `${prefix}_${body}` : body;
}

/** 기본값과 다른 항목만 — 무엇을 설계했는지가 형상 관리의 실체. */
export function diffParams(fields, values) {
  const out = [];
  for (const f of fields) {
    const to = values[f.name];
    if (to === undefined || to === f.default) continue;
    const both = typeof to === "number" && typeof f.default === "number";
    out.push({
      name: f.name,
      from: f.default,
      to,
      unit: f.unit,
      // 기준이 0이거나 수치가 아니면 백분율이 무의미 — null로 두고 표에서 "—"
      deltaPct: both && f.default !== 0 ? ((to - f.default) / Math.abs(f.default)) * 100 : null,
    });
  }
  return out;
}

/** 한계 안에서 값이 차지하는 위치 [0,1] — 판정 불가면 null. */
function boundFraction(f, v) {
  const { lo, hi } = f;
  if (typeof v !== "number" || isUnbounded(v)) return null;
  if (lo != null && hi != null && !isUnbounded(lo) && !isUnbounded(hi) && hi > lo) {
    return (v - lo) / (hi - lo);
  }
  if (hi != null && !isUnbounded(hi) && hi > 0 && v >= 0) return v / hi;
  if (lo != null && !isUnbounded(lo) && lo < 0 && v <= 0) return 1 - v / lo;
  return null;
}

/** 검토용 경고·정보 — 값 자체는 유효해도 설계자가 봐야 할 것들. */
export function paramWarnings(fields, values, { lang = "python" } = {}) {
  const out = [];
  for (const f of fields) {
    const v = values[f.name];
    if (v === undefined) continue;
    if (isUnbounded(v)) {
      out.push({
        name: f.name, level: "info",
        text: `무제한 센티널 ±1e30 — 무한대가 아니므로 코드에도 1e+30으로 표기됩니다.`,
      });
      continue;
    }
    const t = boundFraction(f, v);
    if (t != null && (t >= 0.9 || t <= 0.1)) {
      const side = t >= 0.9 ? "상한" : "하한";
      out.push({
        name: f.name, level: "warn",
        text: `${side} 근접 — 허용 ${numDisplay(f.lo ?? -Infinity)} ~ `
          + `${numDisplay(f.hi ?? Infinity)} 구간의 ${Math.round(t * 100)}% 지점.`,
      });
    }
    if (typeof v === "number" && typeof f.default === "number"
        && f.default !== 0 && Math.abs((v - f.default) / f.default) >= 0.5) {
      out.push({
        name: f.name, level: "info",
        text: `엔진 기본값 ${numDisplay(f.default)}에서 50% 이상 벗어남 — 근거를 남기세요.`,
      });
    }
    // float32는 유효자리 약 7 — 그보다 정밀한 입력은 C 헤더에서 반올림된다
    if (lang === "c" && typeof v === "number" && v !== 0 && f.type !== "integer") {
      const rounded = Number(v.toPrecision(F32_DIGITS));
      if (rounded !== v) {
        out.push({
          name: f.name, level: "warn",
          text: `float32 유효자리(약 ${F32_DIGITS})를 초과 — C 헤더에서 ${rounded}로 저장됩니다.`,
        });
      }
    }
  }
  return out;
}

const ENTITIES = {
  amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " ",
  middot: "·", rarr: "→", larr: "←", times: "×", minus: "−", deg: "°",
};

/** 설계 노트 HTML → 코드 주석 줄 목록.
구조도 노트는 수작성 마크업이라 그대로 주석에 넣으면 태그가 코드에 샌다. */
export function notesToComment(html) {
  if (!html) return [];
  return String(html)
    .replace(/<li[^>]*>/gi, "\n- ")
    .replace(/<\/(p|div|li|ul|ol|h\d|tr)>/gi, "\n")
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<[^>]*>/g, "")
    .replace(/&#(\d+);/g, (_, d) => String.fromCodePoint(Number(d)))
    .replace(/&(\w+);/g, (m, e) => ENTITIES[e] ?? m)
    .split("\n")
    .map((s) => s.replace(/[ \t]+/g, " ").trim())
    .filter((s) => s !== "");
}

const PURPOSE = "탑재 비행코드가 아니라 현재 설계 형상의 코드 표현입니다 (02 §1).";

/** 값의 출처 한 줄 — 산출물에서 "무엇을 근거로 이 수치인가"의 답. */
function originLabel(spec) {
  if (!spec.applied) return "엔진 기본값 (편집 미적용)";
  const n = diffParams(spec.fields, spec.values).length;
  return n === 0 ? "엔진 기본값과 동일" : `편집값 (기본값 대비 ${n}개 변경)`;
}

/** 헤더 주석 본문 줄 — 생성 메타 + 적용 상태 + 설계 근거·주의. */
function headerLines(specs, meta, lang) {
  const lines = [];
  const stamp = [meta?.generatedAt, meta?.server && `server ${meta.server}`,
    meta?.engine && `engine ${meta.engine}`].filter(Boolean).join(" · ");
  if (stamp) lines.push(`생성: ${stamp}`);
  lines.push(PURPOSE);
  lines.push("");
  lines.push("[적용 상태]");
  for (const s of specs) lines.push(`- ${specLabel(s)} (${s.key}): ${originLabel(s)}`);
  const notes = [];
  for (const s of specs) {
    // 근거(설계 노트·주입 계약)와 지적(한계 근접 등)을 컴포넌트 라벨 아래로 묶는다 —
    // 노트가 없는 컴포넌트의 지적이 앞 컴포넌트 것으로 읽히는 오독 방지
    const own = [
      ...notesToComment(s.notes),
      ...(s.hint ? [s.hint] : []),
      ...paramWarnings(s.fields, s.values, { lang })
        .map((w) => `${w.level === "warn" ? "⚠" : "·"} ${w.name}: ${w.text}`),
    ];
    if (own.length) notes.push(`- ${s.key}`, ...own.map((t) => `  ${t}`));
  }
  if (notes.length) lines.push("", "[설계 근거·주의]", ...notes);
  return lines;
}

/** 파라미터 한 줄의 꼬리 주석 — 기본은 변경 표시만, verbose에서 설명·단위·범위. */
function tailComment(f, v, verbose) {
  const parts = [];
  if (verbose) {
    const unit = f.unit && f.unit !== "-" ? ` [${f.unit}]` : "";
    parts.push(`${f.desc}${unit}`);
    if (f.lo != null || f.hi != null) {
      parts.push(`허용 ${numDisplay(f.lo ?? -Infinity)}~${numDisplay(f.hi ?? Infinity)}`);
    }
  }
  if (v !== f.default) parts.push(`← 기본 ${numDisplay(f.default)}`);
  return parts.join(" · ");
}

/** 항목을 폭 안에서 여러 줄로 — 격자점 17개짜리 게인 테이블이 한 줄로 뭉치면
검토(리뷰)가 불가능해진다. 각 줄은 항목 뒤 쉼표 유지(Python·C 모두 후행 쉼표 허용). */
export function wrapItems(items, indent, width = 92) {
  const out = [];
  let cur = "";
  for (const it of items) {
    const next = cur ? `${cur} ${it},` : `${it},`;
    if (cur && indent.length + next.length > width) {
      out.push(indent + cur);
      cur = `${it},`;
    } else {
      cur = next;
    }
  }
  if (cur) out.push(indent + cur);
  return out;
}

/** 컴포넌트 1개의 Python 본문 줄 + 파라미터별 라인 번호(추적성). */
function pyBody(spec, verbose, lines, lineOf, keyPrefix) {
  const { kind = "object", varName, pyClass } = spec;
  lines.push(`# ${spec.key} — ${originLabel(spec)}`);
  lines.push(kind === "dict" ? `${varName} = {` : `${varName} = ${pyClass}(`);
  for (const f of spec.fields) {
    const v = spec.values[f.name];
    if (v === undefined) continue;
    const lhs = kind === "dict" ? `${JSON.stringify(f.name)}: ` : `${f.name}=`;
    const tail = tailComment(f, v, verbose);
    lines.push(`    ${lhs}${pyLiteral(v, f.type)},${tail ? `  # ${tail}` : ""}`);
    lineOf[`${keyPrefix}${f.name}`] = lines.length;
  }
  lines.push(kind === "dict" ? "}" : ")");
}

function docstring(specs, meta, lang = "python") {
  return ['"""', ...headerLines(specs, meta, lang), '"""'];
}

/** 컴포넌트 1개 → 실행 가능한 Python. {code, lineOf} — lineOf는 추적성 표가 인용. */
export function genPython(spec, { verbose = false, meta = null } = {}) {
  const lines = [];
  const lineOf = {};
  const head = docstring([spec], meta);
  head[0] = `"""${spec.key} — 파라미터 형상`;
  lines.push(...head, "");
  if (spec.kind !== "dict") lines.push(`from ${spec.pyImport} import ${spec.pyClass}`, "");
  pyBody(spec, verbose, lines, lineOf, "");
  return { code: lines.join("\n") + "\n", lineOf };
}

/** 전 형상 스냅샷 — 편집 3블록 + 게인 스케줄 테이블 한 파일. */
export function genSnapshotPython(specs, gainTables, { verbose = false, meta = null } = {}) {
  const lines = [];
  const lineOf = {};
  const head = docstring(specs, meta);
  head[0] = '"""CLAW 설계 형상 스냅샷';
  lines.push(...head, "");
  const imports = new Set(specs.filter((s) => s.kind !== "dict")
    .map((s) => `from ${s.pyImport} import ${s.pyClass}`));
  if (gainTables) imports.add("from claw.tables import Table");
  lines.push(...[...imports].sort(), "");
  for (const s of specs) {
    pyBody(s, verbose, lines, lineOf, `${specLabel(s)}.`);
    lines.push("");
  }
  if (gainTables) {
    lines.push("# 게인 스케줄 (게인 탭 '시뮬에 적용' 값) — 주입은 전체 교체", "gain_tables = {");
    for (const [name, t] of Object.entries(gainTables)) {
      lines.push(`    ${JSON.stringify(name)}: Table(`);
      lineOf[`gain_tables.${name}`] = lines.length;
      lines.push("        {");
      for (const [ax, vs] of Object.entries(t.axes)) {
        lines.push(`            ${JSON.stringify(ax)}: [`,
          ...wrapItems(vs.map((v) => pyLiteral(v)), " ".repeat(16)), "            ],");
      }
      lines.push("        },");
      const nested = Array.isArray(t.data[0]);
      lines.push("        [",
        ...(nested
          ? t.data.map((row) => `            ${pyLiteral(row)},`)
          : wrapItems(t.data.map((v) => pyLiteral(v)), " ".repeat(12))),
        "        ],");
      lines.push(`        name=${JSON.stringify(name)},`,
        `        extrapolate=${JSON.stringify(t.extrapolate ?? "clip")},`, "    ),");
    }
    lines.push("}", "");
  }
  // 조립은 서버가 정본 — JS가 흉내 내면 _build 변경 시 조용히 드리프트한다
  lines.push(
    "# 조립(결선)은 서버 routes/sim.py::_build 가 정본 — 참고용 호출 형태:",
    `#   fcl = make_demo_fcl(autopilot=ap${gainTables ? ", gain_tables=gain_tables" : ""})`,
    "#   sim = Simulator(aircraft=..., fcl=fcl, guidance=..., nav_model=nav,",
    "#                   actuator_params=actuator_params, ...)",
  );
  return { code: lines.join("\n") + "\n", lineOf };
}

/** 이름·값 열을 맞춰 정렬 — 헤더 자체가 리뷰 대상 문서라 훑어 읽을 수 있어야 한다. */
function alignDefines(rows) {
  const wn = Math.max(0, ...rows.map((r) => r.macro.length));
  const anyTail = rows.some((r) => r.tail);
  const wv = anyTail ? Math.max(0, ...rows.map((r) => r.value.length)) : 0;
  return rows.map((r) => `#define ${r.macro.padEnd(wn)}  ${r.value.padEnd(wv)}`.trimEnd()
    + (r.tail ? `  /* ${r.tail} */` : ""));
}

function cBlock(spec, verbose, lines, lineOf, keyPrefix) {
  lines.push(`/* ${spec.key} — ${originLabel(spec)} */`);
  const rows = [];
  for (const f of spec.fields) {
    const v = spec.values[f.name];
    if (v === undefined) continue;
    rows.push({
      macro: cMacro(spec.cPrefix, f.name),
      value: cLiteral(v, f.type),
      tail: tailComment(f, v, verbose),
      name: f.name,
    });
  }
  alignDefines(rows).forEach((text, i) => {
    lines.push(text);
    lineOf[`${keyPrefix}${rows[i].name}`] = lines.length;
  });
}

function cGuard(name) {
  return `CLAW_${name.replace(/[^A-Za-z0-9]+/g, "_").toUpperCase()}_H`;
}

/** 컴포넌트 1개 → C 파라미터 헤더 (상수만 — 로직 생성 아님). */
export function genCHeader(spec, { verbose = false, meta = null } = {}) {
  const lines = [];
  const lineOf = {};
  const guard = cGuard(spec.cPrefix || spec.pyClass || "params");
  lines.push(`/* ${spec.key} — 파라미터 형상`, ...headerLines([spec], meta, "c").map((s) => `   ${s}`),
    "*/", `#ifndef ${guard}`, `#define ${guard}`, "");
  cBlock(spec, verbose, lines, lineOf, "");
  lines.push("", `#endif /* ${guard} */`);
  return { code: lines.join("\n") + "\n", lineOf };
}

/** 전 형상 스냅샷 C 헤더 — 게인 테이블은 1D만 배열로, 다차원은 건너뛰고 명시. */
export function genSnapshotC(specs, gainTables, { verbose = false, meta = null } = {}) {
  const lines = [];
  const lineOf = {};
  const guard = cGuard("config_snapshot");
  lines.push("/* CLAW 설계 형상 스냅샷", ...headerLines(specs, meta, "c").map((s) => `   ${s}`),
    "*/", `#ifndef ${guard}`, `#define ${guard}`, "");
  for (const s of specs) {
    cBlock(s, verbose, lines, lineOf, `${specLabel(s)}.`);
    lines.push("");
  }
  for (const [name, t] of Object.entries(gainTables ?? {})) {
    const axNames = Object.keys(t.axes);
    const macro = cMacro("GAIN", name);
    if (axNames.length !== 1) {
      lines.push(`/* ${name}: ${axNames.length}차원 테이블 — C 배열 생성은 미지원 (Python 탭 참조) */`);
      continue;
    }
    const bp = t.axes[axNames[0]];
    lines.push(`#define ${macro}_N ${bp.length}`);
    lines.push(`static const float ${macro}_${axNames[0].toUpperCase()}[${macro}_N] = {`,
      ...wrapItems(bp.map((v) => cLiteral(v)), "    "), "};");
    lines.push(`static const float ${macro}_VALUE[${macro}_N] = {`,
      ...wrapItems(t.data.map((v) => cLiteral(v)), "    "), "};");
    lineOf[`gain_tables.${name}`] = lines.length;
    lines.push("");
  }
  lines.push(`#endif /* ${guard} */`);
  return { code: lines.join("\n") + "\n", lineOf };
}

/** 추적성 표 행 — 파라미터 → 출처 스키마 → 생성 코드 라인 (산출물 기재용). */
export function traceRows(specs, lineOf, { prefixed = false } = {}) {
  const rows = [];
  for (const s of specs) {
    for (const f of s.fields) {
      const v = s.values[f.name];
      if (v === undefined) continue;
      rows.push({
        param: f.name,
        value: numDisplay(v),
        unit: f.unit && f.unit !== "-" ? f.unit : "",
        range: f.choices ? f.choices.join(" | ")
          : (f.lo == null && f.hi == null ? "—"
            : `${numDisplay(f.lo ?? -Infinity)} ~ ${numDisplay(f.hi ?? Infinity)}`),
        // 스냅샷에서만 변수명을 앞에 단다 — 한 스키마가 여러 줄일 때(SCAS 3축)
        // 스키마 이름만으로는 어느 줄의 kp인지 구분이 안 된다. 단일 블록 패널은
        // 스펙이 하나뿐이라 붙일 이유가 없다
        source: `${prefixed ? `${specLabel(s)} · ` : ""}${s.key} @ ${s.pyImport}.${s.pyClass}`,
        line: lineOf[`${prefixed ? `${specLabel(s)}.` : ""}${f.name}`] ?? null,
        desc: f.desc,
      });
    }
  }
  return rows;
}
