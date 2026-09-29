/** 기체 탭 「평가 기준 · 튜닝 목표」 패널의 판단 — 행 만들기·문서 희소 패치·목표 ↔ 판정선 충돌 미리 보기 (의존 0).

판정선의 뜻(지표·방향·합격선·권장선·목표 필드)은 서버 `GET /profiles/{id}/criteria`의 `lines`가 정본이다 — 여기서
방향을 다시 적지 않는다. 문서 규약(02 §5.6): /criteria(합격·권장선 — margin 등 판정 그룹)와 /tuning(targets·weights)은
**적은 칸만** 싣는다. 적지 않은 칸·없음(null)은 도구 기본값을 따른다 — 기본값을 문서에 굳히지 않는다.

충돌 미리 보기는 엔진 design.criteria.target_conflicts와 같은 규칙이다(목표가 판정선보다 느슨한가 — min이면
목표 < 선, max면 목표 > 선; 한 지표는 더 심한 쪽 하나; 비율 판정선과 잴 수 없는 목표는 빼기). 즉시 반응용일 뿐이고
저장 뒤 서버가 돌려준 target_conflicts가 정본이다.
*/

import { parseNum } from "./profileform.js";

/** /tuning 절에 사는 그룹 — 나머지는 /criteria (엔진 TUNING_GROUPS와 같은 목록) */
export const TUNING_GROUPS = ["targets", "weights"];

export const sectionOf = (group) => (TUNING_GROUPS.includes(group) ? "tuning" : "criteria");

/** 방향 → 부호 힌트: min 선은 「이상이어야 합격」, max 선은 「이하」 */
export const directionHint = (direction) => (direction === "max" ? "≤" : "≥");

const isObj = (v) => v != null && typeof v === "object" && !Array.isArray(v);
const groupsOf = (defaults) => Object.keys(defaults ?? {}).filter((g) => isObj(defaults[g]));
const judgedGroupWith = (groups, key) => Object.keys(groups ?? {})
  .find((g) => !TUNING_GROUPS.includes(g) && isObj(groups[g]) && key in groups[g]) ?? null;

/** 칸 이름 → 그 칸이 사는 기본값 그룹. target이면 targets, 아니면 튜닝 밖 판정 그룹에서 찾는다. 못 찾으면 null */
export function groupOfKey(defaults, key, { target = false } = {}) {
  if (key == null) return null;
  if (target) return isObj(defaults?.targets) && key in defaults.targets ? "targets" : null;
  return judgedGroupWith(defaults, key);
}

/** 문서가 실제로 적은 값 — 적지 않았으면 undefined */
export function writtenValue(doc, group, key) {
  const sec = doc?.[sectionOf(group)];
  const grp = isObj(sec) ? sec[group] : null;
  return isObj(grp) && Object.prototype.hasOwnProperty.call(grp, key) ? grp[key] : undefined;
}

/** 칸 하나 — {group, section, key, path, def, written, value(적용값), editable}. 그룹을 모르면 null */
export function cellOf(doc, defaults, group, key) {
  if (group == null || key == null) return null;
  const section = sectionOf(group);
  const def = defaults?.[group]?.[key];
  const w = writtenValue(doc, group, key);
  return {
    group, section, key, path: `/${section}/${group}/${key}`,
    def, written: w !== undefined, value: w !== undefined ? w : def,
    editable: typeof def === "number",
  };
}

/** 응답 본문(lines·defaults) + 편집 중 문서 → 표의 행.
 *  rows: 판정선마다 {metric,label,unit,direction,hint,ratio, pass,rec,target(칸|null), shared:{pass,rec}(같은 칸을 쓰는
 *  다른 지표 이름)}. extras: 판정선 그룹(margin 등) 칸 중 어느 판정선도 쓰지 않는 수치 칸 — 한 줄씩 고친다.
 *  others: 이 표 밖의 칸에 문서가 적은 경로(JSON 글에서 고친다) */
export function buildRows(body, doc) {
  const lines = Array.isArray(body?.lines) ? body.lines : [];
  const defaults = body?.defaults ?? {};
  const used = new Set();
  const lineGroups = new Set();
  const rows = lines.map((ln) => {
    const pg = groupOfKey(defaults, ln.pass_key);
    const rg = groupOfKey(defaults, ln.rec_key);
    const tg = groupOfKey(defaults, ln.target_key, { target: true });
    for (const [g, k] of [[pg, ln.pass_key], [rg, ln.rec_key]]) {
      if (!g) continue;
      used.add(`${g}/${k}`);
      lineGroups.add(g);
    }
    if (tg) used.add(`${tg}/${ln.target_key}`);
    const sharers = (key) => (key == null ? [] : lines
      .filter((o) => o !== ln && (o.pass_key === key || o.rec_key === key)).map((o) => o.label));
    return {
      metric: ln.metric, label: ln.label, unit: ln.unit ?? "", direction: ln.direction,
      hint: directionHint(ln.direction), ratio: !!ln.ratio_of_target,
      pass: cellOf(doc, defaults, pg, ln.pass_key),
      rec: cellOf(doc, defaults, rg, ln.rec_key),
      target: cellOf(doc, defaults, tg, ln.target_key),
      shared: { pass: sharers(ln.pass_key), rec: sharers(ln.rec_key) },
    };
  });
  const extras = [];
  for (const g of lineGroups) {
    for (const k of Object.keys(defaults[g])) {
      if (used.has(`${g}/${k}`)) continue;
      const c = cellOf(doc, defaults, g, k);
      if (c.editable) extras.push(c);
    }
  }
  const shown = new Set([...used, ...extras.map((c) => `${c.group}/${c.key}`)]);
  const others = [];
  for (const sec of ["criteria", "tuning"]) {
    const s = doc?.[sec];
    if (!isObj(s)) continue;
    for (const [g, grp] of Object.entries(s)) {
      if (!isObj(grp)) continue;
      for (const k of Object.keys(grp)) if (!shown.has(`${g}/${k}`)) others.push(`/${sec}/${g}/${k}`);
    }
  }
  return { rows, extras, others };
}

/** 문서에 칸 하나를 쓰거나(value) 지운다(undefined — 기본값을 따르게). **새 문서**를 돌려준다(원본 불변).
 *  빈 그룹은 빼고, 빈 절은 null이다(없음 = 도구 기본값) */
export function setCriteriaValue(doc, group, key, value) {
  const next = JSON.parse(JSON.stringify(doc ?? {}));
  const sec = sectionOf(group);
  const s = isObj(next[sec]) ? next[sec] : {};
  const grp = isObj(s[group]) ? s[group] : {};
  if (value === undefined) delete grp[key];
  else grp[key] = value;
  if (Object.keys(grp).length) s[group] = grp;
  else delete s[group];
  next[sec] = Object.keys(s).length ? s : null;
  return next;
}

/** 칸 글 적용 — {doc}(바뀜) | {noop: true}(적용값과 같다 — 안 적은 칸이면 기본값을 문서에 굳히지 않는다) | {error} */
export function commitValue(doc, cell, raw) {
  const r = parseNum(raw);
  if (r.error) return { error: `${cell.key}: ${r.error}` };
  if (r.value === cell.value) return { noop: true };
  return { doc: setCriteriaValue(doc, cell.group, cell.key, r.value) };
}

/** 문서 + 기본값 → 적용값 한 벌 {group: {key: value}} — 서버 GainEvalCriteria.from_profile과 같은 병합: 칸 단위로
 *  덮되, 기본값이 {축: 수치}인 칸(rms_max 등)은 적은 축만 기본값 위에 덧붙인다(v1.63 — 통째 교체면 다른 축이 사라진다). */
export function effectiveCriteria(doc, defaults) {
  const out = {};
  for (const g of groupsOf(defaults)) {
    const sec = doc?.[sectionOf(g)];
    const w = isObj(sec) && isObj(sec[g]) ? sec[g] : {};
    out[g] = { ...defaults[g] };
    for (const [k, v] of Object.entries(w)) {
      out[g][k] = isObj(defaults[g]?.[k]) && isObj(v) ? { ...defaults[g][k], ...v } : v;
    }
  }
  return out;
}

/** value가 line과 같거나 더 엄격한가 — 엔진 at_least_as_strict */
export function atLeastAsStrict(direction, value, line) {
  if (direction === "min") return value >= line;
  if (direction === "max") return value <= line;
  throw new Error(`판정선 방향은 "min"|"max": ${direction}`);
}

/** 목표가 판정선보다 느슨한 자리 — 서버 target_conflicts와 같은 모양 [{metric, level, target_key, target, line_key,
 *  line, direction}]. applied는 effectiveCriteria의 결과(또는 서버 applied) */
export function targetConflicts(lines, applied) {
  const out = [];
  for (const ln of lines ?? []) {
    if (ln.target_key == null || ln.ratio_of_target) continue;
    const t = Number(applied?.targets?.[ln.target_key]);
    if (Number.isNaN(t)) continue; // 잴 수 없는 목표는 충돌로 판정하지 않는다(엔진과 같다)
    for (const [level, key] of [["pass", ln.pass_key], ["rec", ln.rec_key]]) {
      if (key == null) continue;
      const g = judgedGroupWith(applied, key);
      if (g == null) continue;
      const v = Number(applied[g][key]);
      if (!atLeastAsStrict(ln.direction, t, v)) {
        out.push({ metric: ln.metric, level, target_key: ln.target_key, target: t, line_key: key, line: v,
          direction: ln.direction });
        break;
      }
    }
  }
  return out;
}

/** 충돌 한 줄 — pass는 자동 설계가 거절하고, rec는 경고다 */
export function conflictText(c, lines) {
  const name = (lines ?? []).find((l) => l.metric === c.metric)?.label ?? c.metric;
  const rel = c.direction === "max" ? ">" : "<";
  return c.level === "pass"
    ? `${name}: 목표 ${c.target_key} ${c.target} ${rel} 합격선 ${c.line_key} ${c.line} — 합격선보다 느슨하다 — `
      + "성공한 점이 곧바로 불합격 (자동 설계가 이 설정을 거절합니다)"
    : `${name}: 목표 ${c.target_key} ${c.target} ${rel} 권장선 ${c.line_key} ${c.line} — 권장선보다 느슨하다 — `
      + "성공한 점이 합격·주의 (경고)";
}

const norm = (v) => (isObj(v) && Object.keys(v).length ? v : null);
const canon = (v) => JSON.stringify(v, (_, x) => (isObj(x)
  ? Object.fromEntries(Object.keys(x).sort().map((k) => [k, x[k]])) : x));

/** 편집 중 문서의 /criteria·/tuning이 저장본(written)과 다른가 — 다르면 충돌은 미리 보기, 같으면 서버 판정을 보인다 */
export function writtenDiffers(doc, written) {
  return canon(norm(doc?.criteria)) !== canon(norm(written?.criteria))
    || canon(norm(doc?.tuning)) !== canon(norm(written?.tuning));
}
