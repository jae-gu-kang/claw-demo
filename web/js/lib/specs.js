/** 블록 → 코드 생성 스펙 조립 — 스키마 조회·엔진 검증·심볼 회신을 묶는다.

lib/codegen.js가 소비하는 spec 형태를 만드는 유일한 자리다. **파이썬 클래스·임포트
경로를 여기서 짓지 않는다** — 엔진 인스턴스가 회신한 값을 그대로 싣는다(nav/ErrorModel
→ NavErrorModel처럼 추론 불가한 경우가 있고, 추측하면 엔진 개명 시 조용히 틀린 코드가
나온다). 부수 효과로 생성자 교차 조건까지 생성 시점에 엔진이 판정한다.

통신은 주입받는다(`io`) — DOM도 전역 fetch도 없이 테스트할 수 있어야 하고,
뷰가 아니라 여기가 판단을 갖는 자리이기 때문이다.
*/

/** {get, post, errorText} — api.js가 그대로 맞는다. */
export function makeSpecBuilder(io, { cache = {} } = {}) {
  const fields = async (block, schemaFields) => {
    const { category, name } = block.detail.schema;
    const key = `${category}/${name}`;
    cache[key] ??= await io.get(`/registry/${category}/${name}/schema`);
    const omit = new Set(block.detail.omit ?? []);
    return { key, fields: schemaFields(cache[key]).filter((f) => !omit.has(f.name)) };
  };

  /** 블록 + 값 → {spec, validation}. values=null이면 엔진 기본값 형상. */
  return async function buildSpec(block, values, schemaFields) {
    const { key, fields: flds } = await fields(block, schemaFields);
    const applied = values != null;
    const vals = values ?? Object.fromEntries(flds.map((f) => [f.name, f.default]));
    const { category, name } = block.detail.schema;
    const url = `/registry/${category}/${name}/validate`;
    let sym = {};
    let validation = { key, ok: true, detail: "" };
    try {
      sym = await io.post(url, { values: vals });
    } catch (e) {
      validation = { key, ok: false, detail: io.errorText(e) };
      // 값이 거부돼도 심볼은 필요하다 — 기본값으로 재조회 (등록 컴포넌트면 항상 성립)
      try {
        sym = await io.post(url, { values: {} });
      } catch { /* 서버 이탈 — 폴백 표기로 코드는 생성 */ }
    }
    const cg = block.detail.codegen;
    return {
      validation,
      spec: {
        key, fields: flds, values: vals, applied,
        pyImport: sym.py_import, pyClass: sym.py_class,
        varName: cg.varName, cPrefix: cg.cPrefix, kind: cg.kind, hint: cg.hint ?? "",
        desc: block.detail.desc, notes: block.detail.notes ?? "",
      },
    };
  };
}

/** 생성 코드의 추적성 메타 — 서버 버전은 한 번만 물어본다. */
export function makeMetaSource(io, now = () => new Date()) {
  let cached = null;
  return async function codegenMeta() {
    if (!cached) {
      try {
        cached = await io.get("/health");
      } catch {
        cached = {}; // 버전 줄만 빠지고 코드 생성은 계속
      }
    }
    const d = now();
    const pad = (n) => String(n).padStart(2, "0");
    return {
      generatedAt: `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} `
        + `${pad(d.getHours())}:${pad(d.getMinutes())}`,
      server: cached.version,
      engine: cached.engine,
    };
  };
}
