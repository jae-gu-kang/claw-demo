/** 기체 문서 절별 폼의 판단 — JSON Pointer 읽기·쓰기, 형상 변형 덮어쓰기, 칸 입력 해석 (06 §8).

칸의 이름·단위·형식·선택지는 서버(`GET /profiles/_form`, 엔진 `claw.profile.form`)가 준다 — 여기서
다시 적지 않는다. 판정(범위·서열·대칭 검사)도 적지 않는다: 저장·검증 때 서버 검증기가 경로와 함께
말한다. 여기는 **입력을 문서 값으로 옮기는 규칙**만 있다.

형상 변형은 `patch: {"/경로": 값}` 치환 맵이다(엔진 `profile/patch.py`). 화면에 보이는 값은 기본 문서에
치환을 **끼운 순서대로** 적용한 값이고, 변형을 고칠 때는 그 칸을 덮어쓴 경로(자기 자신 또는 상위)에
쓴다 — 상위 경로가 통째로 덮어썼는데 하위 경로를 새로 만들면, 적용 순서에 따라 한쪽이 조용히 사라진다.
*/

export const FORBIDDEN_PATCH_ROOTS = ["schema_version", "id", "is_example", "variants"];

/** "/a/b~1c" → ["a", "b/c"] (RFC 6901). */
export function parsePointer(ptr) {
  if (typeof ptr !== "string" || !ptr.startsWith("/")) throw new Error(`JSON Pointer는 '/'로 시작해야 함: ${ptr}`);
  return ptr.slice(1).split("/").map((t) => t.replaceAll("~1", "/").replaceAll("~0", "~"));
}

export const toPointer = (tokens) => `/${tokens.map((t) => String(t).replaceAll("~", "~0").replaceAll("/", "~1")).join("/")}`;

function step(node, token) {
  if (Array.isArray(node)) {
    if (!/^(0|[1-9][0-9]*)$/.test(token)) return undefined;
    const i = Number(token);
    return i < node.length ? i : undefined;
  }
  if (node != null && typeof node === "object" && Object.hasOwn(node, token)) return token;
  return undefined;
}

/** 경로의 값 — 없는 경로면 undefined (null은 「없음」이라는 실제 값이다). */
export function getAt(doc, ptr) {
  let node = doc;
  for (const t of parsePointer(ptr)) {
    const k = step(node, t);
    if (k === undefined) return undefined;
    node = node[k];
  }
  return node;
}

const clone = (v) => (v === undefined ? undefined : JSON.parse(JSON.stringify(v)));

/** 경로에 값을 넣은 **새 문서** — 경로는 이미 있어야 한다(없는 경로는 오타다, 엔진 patch 규칙과 같다). */
export function setAt(doc, ptr, value) {
  const out = clone(doc);
  const tokens = parsePointer(ptr);
  let node = out;
  for (const t of tokens.slice(0, -1)) {
    const k = step(node, t);
    if (k === undefined) throw new Error(`문서에 없는 경로: ${ptr}`);
    node = node[k];
  }
  const last = step(node, tokens.at(-1));
  if (last === undefined) throw new Error(`문서에 없는 경로: ${ptr}`);
  node[last] = clone(value);
  return out;
}

/** ptr이 base와 같거나 그 아래인가 — 토큰 단위(“/mass/m”은 “/mass/m_empty”의 상위가 아니다). */
export function isUnder(ptr, base) {
  const a = parsePointer(ptr);
  const b = parsePointer(base);
  return b.length <= a.length && b.every((t, i) => a[i] === t);
}

/** 이 칸을 덮어쓴 경로 — 자기 자신 또는 상위 중 **뒤에 끼운 것**. 없으면 null.
 *  엔진은 치환을 끼운 순서대로 적용하므로 뒤의 것이 이긴다 — 깊이로 고르면 앞에 끼운(이미 가려진) 하위
 *  치환을 고치게 되고, 칸은 아무 일 없이 원래 값으로 돌아온다. */
export function patchOwner(patch, ptr) {
  let owner = null;
  for (const key of Object.keys(patch ?? {})) if (isUnder(ptr, key)) owner = key;
  return owner;
}

/** 이 칸 아래를 부분적으로 덮어쓴 경로들 (자기 자신 제외) — 이 칸을 덮은 치환보다 뒤에 끼운 것만 효과가 있다. */
export function patchedBelow(patch, ptr) {
  const keys = Object.keys(patch ?? {});
  const ownerAt = keys.findLastIndex((k) => isUnder(ptr, k));
  return keys.filter((k, i) => i > ownerAt && k !== ptr && isUnder(k, ptr));
}

/** 기본 문서에 치환 맵을 적용한 문서 — 엔진 apply_patch와 같은 순서·규칙. 적용 못 한 경로는 사유로 모은다. */
export function applyPatch(doc, patch) {
  const issues = [];
  let out = clone(Object.fromEntries(Object.entries(doc ?? {}).filter(([k]) => k !== "variants")));
  for (const [ptr, value] of Object.entries(patch ?? {})) {
    let tokens;
    try {
      tokens = parsePointer(ptr);
    } catch (e) {
      issues.push(`${ptr}: ${e.message}`);
      continue;
    }
    if (FORBIDDEN_PATCH_ROOTS.includes(tokens[0])) {
      issues.push(`${ptr}: 형상 변형이 바꿀 수 없는 항목`);
      continue;
    }
    try {
      out = setAt(out, ptr, value);
    } catch (e) {
      issues.push(`${ptr}: ${e.message}`);
    }
  }
  return { doc: out, issues };
}

/** 형상 변형에서 칸 하나를 고친 **새 치환 맵**.
 *  상위 경로가 이미 덮어썼으면 그 값 안을 고친다. 이 칸 아래의 부분 덮어쓰기는 이 값에 녹아들므로 지운다. */
export function setInPatch(patch, ptr, value) {
  const out = { ...(patch ?? {}) };
  const owner = patchOwner(out, ptr);
  if (owner != null && owner !== ptr) {
    // 그 상위 앞에 끼운 하위 치환은 이미 가려져 효과가 없다 — 남기면 「덮어씀」 표시만 헷갈리게 한다
    const keys = Object.keys(out);
    for (const k of keys.slice(0, keys.indexOf(owner))) if (isUnder(k, owner)) delete out[k];
    // 그 상위 뒤에 끼운 이 칸 아래 치환은 이 값을 다시 덮는다 — 남기면 고친 값이 안 보인다
    for (const k of keys.slice(keys.indexOf(owner) + 1)) if (k !== ptr && isUnder(k, ptr)) delete out[k];
    const rel = parsePointer(ptr).slice(parsePointer(owner).length);
    out[owner] = setAt({ v: out[owner] }, toPointer(["v", ...rel]), value).v;
    return out;
  }
  // 이 칸 아래의 치환은 이 값에 녹는다(앞에 끼웠든 뒤에 끼웠든). 자기 자리가 있으면 자리를 지키고 값만 바꾼다
  for (const k of Object.keys(out)) if (k !== ptr && isUnder(k, ptr)) delete out[k];
  out[ptr] = clone(value);
  return out;
}

/** 덮어쓰기 해제 — 그 경로의 치환만 지운다(상위 경로가 덮어쓴 칸은 상위를 해제해야 한다). */
export function clearInPatch(patch, ptr) {
  const out = { ...(patch ?? {}) };
  delete out[ptr];
  return out;
}

/** 칸 글 → 수치. 빈 칸·비유한값은 오류(「없음」은 체크로 고른다 — 빈 칸을 null로 읽으면 지운 줄 모른다). */
export function parseNum(raw) {
  const s = String(raw ?? "").trim();
  if (s === "") return { error: "빈 칸" };
  const v = Number(s);
  return Number.isFinite(v) ? { value: v } : { error: `수치가 아님: ${s}` };
}

/** "0.1, 0.2  0.3" → [0.1, 0.2, 0.3] — 쉼표·공백 구분. */
export function parseNumList(raw) {
  const parts = String(raw ?? "").split(/[\s,]+/).filter(Boolean);
  if (!parts.length) return { error: "빈 목록" };
  const out = [];
  for (const p of parts) {
    const r = parseNum(p);
    if (r.error) return { error: r.error };
    out.push(r.value);
  }
  return { value: out };
}

/** 수치 표시 — 문서 값을 **그대로** 보인다(반올림하면 저장 때 값이 바뀐다). */
export const formatNum = (v) => (v == null ? "" : String(v));

/** 대칭 행렬의 한 칸 — 대칭이면 마주 보는 칸도 같이 바꾼 새 행렬. */
export function setMatrixCell(mat, i, j, v, { symmetric = false } = {}) {
  const out = clone(mat);
  out[i][j] = v;
  if (symmetric) out[j][i] = v;
  return out;
}

/** 마하 표 ↔ 행 [{mach, value}] — 행은 편집용이고 순서·중복 판정은 서버가 한다. */
export const tableRows = (table) => (table?.axes?.mach ?? []).map((m, i) => ({ mach: m, value: table.data?.[i] }));

export function tableFromRows(rows, extrapolate) {
  return { axes: { mach: rows.map((r) => r.mach) }, data: rows.map((r) => r.value), extrapolate };
}

/** `/profiles/parse-table` 응답(축 이름 → 목록) → 문서의 마하 표. 축이 mach 하나가 아니면 사유. */
export function machTableFromParsed(parsed, extrapolate) {
  const names = Object.keys(parsed?.axes ?? {});
  if (names.length !== 1 || names[0] !== "mach") {
    return { error: `마하 1축 표여야 합니다 — 받은 축: ${names.join(", ") || "없음"}` };
  }
  return { value: { axes: { mach: parsed.axes.mach }, data: parsed.data, extrapolate } };
}

/** 공력 항 입력 글 "alpha, qhat" ↔ 목록. 모르는 이름은 서버가 경로와 함께 거부한다 — 여기선 나누기만. */
export const inputsText = (inputs) => (inputs ?? []).join(", ");
export const parseInputs = (raw) => String(raw ?? "").split(/[\s,*·]+/).filter(Boolean);

/** 이 계수 항에 허용되는 입력 이름 — 서버 폼 서술의 term_inputs + term_extra_inputs. */
export function allowedInputs(spec, form, coef) {
  const extra = (spec?.term_extra_inputs ?? []).find((e) => e.form === form && e.coef === coef);
  return [...(spec?.term_inputs ?? []), ...(extra?.inputs ?? [])];
}

/** 레지스트리 스키마 필드(schemaform.schemaFields) → 파라미터 객체 — 형식을 바꿀 때 **사용자가 누른 뒤에만**
 *  기본값으로 채운다(문서는 전부 명시 규칙이라 조용히 채우지 않는다). 예약 파라미터는 뺀다. */
export function paramsFromDefaults(fields, reserved = []) {
  return Object.fromEntries(fields.filter((f) => !reserved.includes(f.name)).map((f) => [f.name, f.default]));
}

/** 칸을 비울 수 없는가 — 서술의 `nullable`이 정본이다(검증기가 null을 받는 칸만 nullable). 기본값으로 채워 주지 않으므로
 *  화면이 「필수」를 **표시로** 말한다 — 「없음」 체크박스가 없다는 부재만으로는 처음 보는 사람이 규칙을 읽어 내지 못한다. */
export const isRequired = (f) => !f?.nullable;

/** 절 머리의 「필수 N · 선택 M」 — 선택 묶음(nullable group)은 선택 하나로 세고 그 안의 칸은 세지 않는다(묶음을 쓸 때만
 *  필수라 절의 필수 수에 넣으면 비워 둔 묶음에서 거짓이 된다). 필수 묶음은 머리를 세지 않고 안의 칸을 센다. */
export function requirementCounts(fields) {
  let required = 0;
  let optional = 0;
  for (const f of fields ?? []) {
    if (f.kind === "group") {
      if (f.nullable) optional += 1;
      else {
        const inner = requirementCounts(f.fields);
        required += inner.required;
        optional += inner.optional;
      }
    } else if (isRequired(f)) required += 1;
    else optional += 1;
  }
  return { required, optional };
}

/** 절 서술의 칸을 평평하게 — 묶음(group) 안까지. */
export function flattenFields(fields) {
  return (fields ?? []).flatMap((f) => (f.kind === "group" ? [f, ...flattenFields(f.fields)] : [f]));
}

/** 형상 변형이 이 절에서 덮어쓴 경로 수 — 절 머리에 적어 어디를 봐야 하는지 알게 한다. */
export function sectionOverrides(patch, section) {
  const base = `/${section.key}`;
  return Object.keys(patch ?? {}).filter((k) => isUnder(k, base));
}

/** 편집 대상에서 보이는 문서 — 기본 문서, 또는 그 형상 변형의 치환을 적용한 문서. */
export function effectiveOf(doc, variantId) {
  if (variantId == null) return doc;
  const v = (Array.isArray(doc?.variants) ? doc.variants : []).find((x) => x?.id === variantId);
  return v ? applyPatch(doc, v.patch).doc : doc;
}

/** [[경로, 값], …]를 편집 대상에 쓴 **새 문서** — 기본 문서면 그 자리에, 형상 변형이면 그 변형의 치환 맵으로. */
export function writeValues(doc, variantId, pairs) {
  if (variantId == null) return pairs.reduce((d, [ptr, v]) => setAt(d, ptr, v), doc);
  const i = (Array.isArray(doc?.variants) ? doc.variants : []).findIndex((v) => v?.id === variantId);
  if (i < 0) throw new Error(`형상 변형이 문서에 없습니다: ${variantId}`);
  const patch = pairs.reduce((p, [ptr, v]) => setInPatch(p, ptr, v), doc.variants[i].patch ?? {});
  return setAt(doc, `/variants/${i}/patch`, patch);
}

/** 폼 쓰기 한 건을 받을지 — 기체 탭(views/aircraft.js)의 판단.
 *
 *  쓰기는 **그 순간의 문서**(`state.obj`)에 `fn`을 적용한다 — 그린 때의 사본이 아니다. 그래서 칸을 고친
 *  직후 [행 추가]를 눌러도 방금 친 값이 산다. 받지 않는 것은 폼이 그 편집 기록의 것이 아닐 때뿐이다(그사이
 *  다른 기체를 열었거나 JSON 글로 옮겼다 — 네트워크를 기다린 쓰기가 여기 걸린다).
 *  돌려주는 것: {reject} | {error} | {obj, text}. */
/** 쓰기 fn이 던지는 **사유 그대로** 보일 알림 — 문서 모양 오류가 아니라 "이 쓰기를 하지 않았다"는 안내. */
export class FormNotice extends Error {}

export function formUpdate({ state, owner, fn, async = false }) {
  if (!state || state !== owner || state.mode !== "form") {
    return { reject: async
      ? "그사이 다른 기체를 열었거나 JSON 글로 옮겨 이 변경을 적용하지 않았습니다 — 다시 해 주세요."
      : "편집 중인 폼이 바뀌어 이 변경을 적용하지 않았습니다." };
  }
  let next;
  try {
    next = fn(state.obj);
  } catch (e) {
    if (e instanceof FormNotice) return { error: e.message };
    return { error: `값을 쓰지 못했습니다 — ${e.message} (JSON 글에서 문서 모양을 확인하세요)` };
  }
  return { obj: next, text: JSON.stringify(next, null, 1) };
}

/** 공력 항 k가 표면 한 줄 요약 — "표 alpha×mach · 7×3칸 · clip". 수치면 null. */
export function tableSummary(k) {
  const t = k?.table;
  if (!t?.axes) return null;
  const names = Object.keys(t.axes);
  return `표 ${names.join("×")} · ${names.map((n) => t.axes[n].length).join("×")}칸 · ${t.extrapolate}`;
}

/** `/profiles/parse-table` 응답 → 공력 항 k({table}). 축 이름이 허용 목록 밖이면 사유 — 서버 검증 전에 막는다. */
export function aeroTableFromParsed(parsed, allowedAxes) {
  const names = Object.keys(parsed?.axes ?? {});
  if (!names.length) return { error: "표 축이 없습니다" };
  const bad = names.filter((n) => !(allowedAxes ?? []).includes(n));
  if (bad.length) return { error: `허용하지 않는 축: ${bad.join(", ")} — 허용 ${(allowedAxes ?? []).join(", ")}` };
  return { value: { table: { axes: parsed.axes, data: parsed.data, extrapolate: parsed.extrapolate } } };
}

/** 뷰어 칸 글 → `/profiles/aero-slice` 본문(document·variant 제외). 틀린 칸은 모아서 사유로. */
export function sliceBody(form, axes) {
  const errors = [];
  const num = (label, raw) => {
    const r = parseNum(raw);
    if (r.error) errors.push(`${label}: ${r.error}`);
    return r.value;
  };
  const body = {
    along: form.along,
    start: num("시작", form.start),
    stop: num("끝", form.stop),
    n: num("점 수", form.n),
    fixed: {},
  };
  for (const a of axes) {
    if (a !== form.along) body.fixed[a] = num(a, form.fixed?.[a]);
  }
  if (!errors.length && !(body.start < body.stop)) errors.push("시작 < 끝이어야 합니다");
  if (!errors.length && !(Number.isInteger(body.n) && body.n >= 2)) errors.push("점 수는 2 이상 정수입니다");
  return errors.length ? { error: errors.join(" · ") } : { value: body };
}

/** 뷰어 응답의 실속 대조 한 줄 — 추출은 참고, 정본은 실속 표다. */
export function stallNote(slice) {
  const st = slice?.stall;
  if (!st) return "";
  const r = (v) => (v == null ? "—" : `${v.toFixed(4)} rad`);
  if (slice.along === "alpha") {
    // 추출은 CL을 만드는 표의 α 격자·DB 유효 범위 안에서만 한다 — 그 밖은 외삽이라 꺾여도 표 끝이다
    const [lo, hi] = st.window ?? [null, null];
    const win = lo == null && hi == null ? ""
      : ` (추출 구간 α [${lo == null ? "−∞" : lo}, ${hi == null ? "∞" : hi}] — 표 격자·DB 유효 범위)`;
    return st.extracted == null
      ? `실속 표 α_stall(M=${slice.fixed.mach}) = ${r(st.table_at)} · 곡선 추출: ${st.reason}${win}`
      : `실속 표 α_stall(M=${slice.fixed.mach}) = ${r(st.table_at)} · 곡선 추출(CL이 오르다 떨어지는 꼭대기) = `
        + `${r(st.extracted)} · 차이 ${r(st.delta)} (정본은 실속 표)${win}`;
  }
  if (slice.along === "mach" && st.table_curve) return "아래 그림은 실속 표 α_stall(M) — 같은 마하 축";
  return "";
}
