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

/** 컴포넌트별 폼 필드 그룹 스펙 — 서버 스키마는 알파벳 정렬 출력이므로
기능 단위(루프·한계 등)로 재배열한다. 표시 전용: 미기재 필드는 "기타"로
보존(엔진 파라미터 추가에 안전), 스키마에 없는 이름은 무시(제거에 안전). */
export const FIELD_GROUPS = {
  "fcl/Autopilot": [
    ["속도 루프", ["kp_spd", "ki_spd", "tau_spd"]],
    ["고도 루프", ["kp_alt", "ki_alt", "k_hdot", "tau_alt"]],
    ["헤딩 루프", ["kp_hdg", "ki_hdg", "tau_hdg"]],
    ["피치 명령 한계", ["theta_lo", "theta_hi"]],
    ["선회", ["phi_max", "k_pitch_turn", "k_thr_turn"]],
  ],
  "fcl/ScasAxis": [
    ["게인", ["kp", "ki", "k_rate"]],
    ["레이트 워시아웃", ["washout_tau"]],
    ["출력 한계", ["out_lo", "out_hi"]],
  ],
  "fcl/Mixer": [
    ["타면 한계", ["elevon_lo", "elevon_hi", "rudder_lo", "rudder_hi"]],
    ["차동추력", ["k_diff_thr"]],
  ],
  "actuator/SecondOrderActuator": [
    ["동특성", ["wn", "zeta", "rate_max"]],
    ["위치·초기", ["pos_lo", "pos_hi", "initial"]],
  ],
  "nav/ErrorModel": [
    ["측정 잡음 σ", ["pos_std", "vel_std", "att_std", "psi_std", "rate_std"]],
    ["바이어스", ["bias_std", "bias_tau"]],
    ["시간 특성", ["delay_s", "update_hz"]],
    ["난수", ["seed"]],
  ],
};

/** 필드 목록 → [{title, fields}] — FIELD_GROUPS 스펙 순, 잔여는 "기타". */
export function groupFields(key, fields) {
  const spec = FIELD_GROUPS[key];
  if (!spec) return [{ title: "", fields }];
  const byName = new Map(fields.map((f) => [f.name, f]));
  const used = new Set();
  const groups = [];
  for (const [title, names] of spec) {
    const fs = names.filter((n) => byName.has(n)).map((n) => {
      used.add(n);
      return byName.get(n);
    });
    if (fs.length) groups.push({ title, fields: fs });
  }
  const rest = fields.filter((f) => !used.has(f.name));
  if (rest.length) groups.push({ title: "기타", fields: rest });
  return groups;
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
