/** 레지스트리 JSON 스키마 → 폼 필드 목록 + 입력 파싱 — 블록 파라미터 폼 (02 §2.3).

스키마 형태는 엔진 ParamSet.to_json_schema가 정본:
  properties: {name: {description: "설명 [단위]", default, type, minimum?, maximum?, enum?}}
여기서 폼 표시용 필드 서술자와 문자열 입력 검증(빈 문자열·유한성·범위·정수·enum)만
담당 — 도메인 검증(교차 조건 등)은 제출 시 엔진이 수행.
*/

const UNIT_RE = /^(.*) \[(.+)\]$/;

/** 스키마 → [{name, desc, unit, type, choices, default, lo, hi}] (정의 순서 유지). */
export function schemaFields(schema) {
  return Object.entries(schema.properties ?? {}).map(([name, p]) => {
    const m = UNIT_RE.exec(p.description ?? "");
    return {
      name,
      desc: m ? m[1] : (p.description ?? ""),
      unit: m ? m[2] : "",
      type: p.enum ? "enum" : (p.type ?? "number"),
      choices: p.enum ?? null,
      default: p.default,
      lo: p.minimum ?? null,
      hi: p.maximum ?? null,
    };
  });
}

/** 문자열 입력 → {value} 또는 {error}. boolean은 체크박스라 파싱 대상 아님. */
export function parseFieldValue(field, raw) {
  if (field.type === "enum") {
    return field.choices.includes(raw) ? { value: raw }
      : { error: `${field.name}: 허용값 ${field.choices.join(", ")} 중 하나여야 함` };
  }
  const s = String(raw).trim();
  if (s === "") return { error: `${field.name}: 빈 입력` };
  const num = Number(s);
  if (!Number.isFinite(num)) return { error: `${field.name}: 유한한 수치가 아님` };
  if (field.type === "integer" && !Number.isInteger(num)) {
    return { error: `${field.name}: 정수여야 함` };
  }
  if (field.lo != null && num < field.lo) return { error: `${field.name}: 하한 ${field.lo} 미만` };
  if (field.hi != null && num > field.hi) return { error: `${field.name}: 상한 ${field.hi} 초과` };
  return { value: num };
}
