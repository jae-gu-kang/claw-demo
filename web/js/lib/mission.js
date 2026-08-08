/** 미션 빌더 (02 §8 5단계) — 편집 행 → 서버 /api/sim/run 스펙 (순수 로직, 테스트 대상).

빈 문자열 = 축 off(null). 조건 DSL 인자수는 엔진 _COND_ARITY와 동일 테이블 —
불일치는 어차피 서버(엔진 validate_condition)가 422로 거부한다.
*/

export const COND_KINDS = {
  always: 0,
  time_ge: 1,
  alt_ge: 1,
  alt_le: 1,
  speed_ge: 1,
  speed_le: 1,
  path_done: 0,
};

function num(text, what) {
  const v = Number(text);
  if (!Number.isFinite(v)) throw new Error(`${what}: 수치가 아님 — ${JSON.stringify(text)}`);
  return v;
}

function numOrNull(text, what) {
  const s = String(text).trim();
  return s === "" ? null : num(s, what);
}

export function buildModes(rows) {
  return rows.map((r) => {
    const name = String(r.name).trim();
    if (!name) throw new Error("모드 이름이 비어 있음");
    let heading = String(r.heading).trim();
    heading = heading === "" ? null : heading === "path" ? "path" : num(heading, `${name}.heading`);
    const exit = [r.exitKind];
    if (COND_KINDS[r.exitKind] === 1) exit.push(num(r.exitValue, `${name}.exit`));
    return {
      name,
      speed: numOrNull(r.speed, `${name}.speed`),
      alt: numOrNull(r.alt, `${name}.alt`),
      heading,
      exit,
      next: String(r.next).trim() || null,
    };
  });
}

export function buildWaypoints(rows) {
  if (!rows.length) return null;
  return rows.map((r, i) => [num(r.n, `wp${i}.N`), num(r.e, `wp${i}.E`)]);
}
