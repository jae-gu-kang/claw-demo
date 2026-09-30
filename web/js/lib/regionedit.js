/** 요구영역 편집 (05 §11.13 이관 6단계 · 06 §10 ①) — 편집 사본·칸 쓰기·오류 칸·꼭짓점 고르기·영향 줄·계보 행
(순수 로직, 테스트 대상).

요구영역의 정본은 기체 문서의 `operating_region` 절이고, 검증·윤곽(행마다 요구 마하)·기본 격자·영향은 서버(엔진
claw.opspace)가 낸다(`POST /grid/region/preview`). 여기서는 **숫자 표를 고치는 규칙만** 둔다:

- 편집 사본은 절 모양 그대로다 {mach, alt, fuel, boundary, base_grid} — 보낼 때 따로 조립하지 않는다.
- 웹은 보간하지 않는다. 경계표가 없는(null) 영역의 첫 편집은 미리보기 윤곽(엔진)에서 연료 양끝 × 고도 양끝 행을
  옮겨 적어 경계표를 세운다(seedBoundary). 윤곽에 그 고도가 없으면 세우지 않는다.
- 「전체 연료」는 같은 고도 행의 같은 칸에 **같은 절댓값**을 모든 층에 쓴다. 그 고도 행이 없는 층은 그 층 연료의
  엔진 윤곽(미리보기 outlines)에서 하한·상한을 둘 다 옮겨 행을 넣은 뒤 고친 칸만 덮는다. 윤곽이 없거나 그 고도가
  요구 안(in)이 아니면 거부한다 — 고친 행을 복사하면 다른 칸을 지어낸다. 층마다 값이 달랐으면 changes가 말한다.
- 칸 이름은 검증 오류 경로(schema.py `/operating_region/...`)와 같은 JSON 포인터다 — 422가 곧 칸을 가리킨다.
  그래서 경계표는 엔진(_from_section)과 같은 순서(층은 연료, 행은 고도 오름차순)로 늘 정렬해 둔다.
*/

import { parseNumberList } from "./grid.js";

const EPS = 1e-9;
const same = (a, b) => Math.abs(a - b) <= EPS;
const clone = (v) => (v == null ? v : JSON.parse(JSON.stringify(v)));

export const SCOPE_ALL = "all";
export const SCOPE_LAYER = "layer";
export const SCOPE_LABEL = Object.freeze({ all: "전체 연료", layer: "현재 연료만" });
const COL_NAME = ["고도", "마하 하한", "마하 상한"];

/** 서버 요구영역 되울림(Region.to_dict — 기본 격자 명세는 `grid`) 또는 절(`base_grid`) → 편집 사본(절 모양).
 *  null이면 null. */
export function workingFromRegion(region) {
  if (!region) return null;
  const g = region.base_grid ?? region.grid ?? {};
  // 저장본·사본 모두 엔진 순서로 — 손으로 쓴 절이 순서만 달라도 sameSection이 「저장 전」으로 보지 않게
  return sortBoundary({
    mach: [...region.mach], alt: [...region.alt], fuel: [...region.fuel],
    boundary: region.boundary == null ? null
      : region.boundary.map((l) => ({ fuel: l.fuel, rows: l.rows.map((r) => [...r]) })),
    base_grid: { n_mach: g.n_mach, alts: [...(g.alts ?? [])], fuels: [...(g.fuels ?? [])] },
  });
}

/** 두 사본이 같은 절인가 — 저장본과 비교해 「저장 전」을 가린다. */
export const sameSection = (a, b) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);

function sortBoundary(work) {
  if (!work.boundary) return work;
  work.boundary.sort((a, b) => a.fuel - b.fuel);
  for (const l of work.boundary) l.rows.sort((a, b) => a[0] - b[0]);
  return work;
}

const outlineRowAt = (outline, alt) =>
  (outline ?? []).find((r) => same(r.alt, alt) && Number.isFinite(r.mach_lo) && Number.isFinite(r.mach_hi)) ?? null;

/** 층 윤곽 사전({"50.0": 윤곽} — 서버 키는 연료 수의 글)에서 그 연료의 윤곽. 수로 짝짓는다("50"·"50.0" 둘 다). */
export function layerOutline(outlines, fuel) {
  for (const [k, v] of Object.entries(outlines ?? {})) if (same(Number(k), fuel)) return v;
  return null;
}

/** 경계표가 없는 사본 → 연료 양끝 층 × 고도 양끝 행의 경계표. 값은 미리보기 윤곽(엔진이 낸 행마다 요구 마하)에서
 *  옮겨 적는다 — 경계표가 없으면 윤곽은 연료와 무관하니 한 윤곽이 양끝 층을 다 채운다. 윤곽에 고도 양끝 행이 없으면
 *  던진다(웹이 지어내지 않는다). 이미 경계표가 있으면 사본을 그대로 돌려준다. */
export function seedBoundary(work, outline) {
  if (work.boundary) return clone(work);
  const alts = [...new Set(work.alt)];
  const rows = alts.map((a) => {
    const r = outlineRowAt(outline, a);
    if (!r) throw new Error(`윤곽에 고도 ${a} m 행이 없어 경계표를 세우지 못한다 — 미리보기를 받은 뒤 다시 고친다`);
    return [a, r.mach_lo, r.mach_hi];
  });
  const out = clone(work);
  out.boundary = [...new Set(work.fuel)].map((f) => ({ fuel: f, rows: rows.map((r) => [...r]) }));
  return sortBoundary(out);
}

/** 보이는 연료의 층 색인 — 층 값 그대로일 때만(층 사이 연료는 편집할 층이 아니다). 없으면 -1. */
export const layerIndexAt = (work, fuel) => (work?.boundary ?? []).findIndex((l) => same(l.fuel, fuel));

/** 고를 수 있는 연료 — 경계표 층, 없으면 기본 연료 범위 양끝(첫 편집이 그 둘에 층을 세운다). */
export function fuelChoices(work) {
  if (!work) return [];
  return work.boundary ? work.boundary.map((l) => l.fuel) : [...new Set(work.fuel)];
}

/** 연료 칩 — 편집할 층(fuelChoices) ∪ 기본 격자 연료(그 연료의 격자 점을 보려고), 오름차순. 층이 아닌 연료는 보기만
 *  한다(층 사이는 보간이라 편집할 행이 없다 — isLayerFuel). */
export function shownFuels(work) {
  if (!work) return [];
  const out = [];
  for (const f of [...fuelChoices(work), ...(work.base_grid?.fuels ?? [])]) {
    if (!out.some((g) => same(g, f))) out.push(f);
  }
  return out.sort((a, b) => a - b);
}

/** 이 연료에 편집할 층이 있나 — 경계표 층, 없으면 기본 연료 범위 양끝. */
export const isLayerFuel = (work, fuel) => fuelChoices(work).some((f) => same(f, fuel));

/** 보이는 연료의 표 행 [{alt, lo, hi, paths: [고도, 하한, 상한 칸], virtual}]. 경계표가 없으면 윤곽에서 옮긴 가상
 *  행(고치면 seedBoundary가 그대로 세운다 — 칸 이름도 그때의 색인이다). 윤곽에 없으면 빈 칸(null). */
export function tableRows(work, fuel, outline) {
  if (!work) return [];
  if (!work.boundary) {
    const i = [...new Set(work.fuel)].sort((a, b) => a - b).findIndex((f) => same(f, fuel));
    if (i < 0) return [];
    return [...new Set(work.alt)].map((a, j) => {
      const r = outlineRowAt(outline, a);
      return { alt: a, lo: r?.mach_lo ?? null, hi: r?.mach_hi ?? null, virtual: true,
        paths: [0, 1, 2].map((k) => `/boundary/${i}/rows/${j}/${k}`) };
    });
  }
  const i = layerIndexAt(work, fuel);
  if (i < 0) return [];
  return work.boundary[i].rows.map((r, j) => ({ alt: r[0], lo: r[1], hi: r[2], virtual: false,
    paths: [0, 1, 2].map((k) => `/boundary/${i}/rows/${j}/${k}`) }));
}

const num = (value, path, what) => {
  const s = typeof value === "number" ? value : String(value ?? "").trim();
  const v = s === "" ? NaN : Number(s);
  if (!Number.isFinite(v)) return { error: { path, message: `${what}: 수치가 아님 — ${value}` } };
  return { v };
};

const fail = (work, path, message) => ({ work, changes: [], error: { path, message } });

/** 칸 하나를 쓴다 → {work(새 사본), changes, error}. 입력 사본은 건드리지 않는다.
 *  path — 칸 이름(JSON 포인터): /mach/0 · /alt/1 · /fuel/0 · /base_grid/n_mach · /base_grid/alts · /base_grid/fuels ·
 *  /boundary/{층}/rows/{행}/{0 고도|1 하한|2 상한}. scope — "layer"(그 층만) | "all"(같은 고도 행의 같은 칸을 모든 층에
 *  같은 값으로). outline — 보이는 연료의 윤곽(경계표 세우기), outlines — {연료: 윤곽}(「전체 연료」가 행 없는 층에 행을
 *  넣을 때 — 그 층 윤곽의 그 고도가 요구 안(in)이 아니면 error로 거부). 값이 수치가 아니면 error만 싣고 사본은
 *  그대로다(서버에 보내지 않는다). changes — 경계표 쓰기에서 층마다 [{fuel, alt, col, old, value, inserted, source}]
 *  (넣은 행이면 old는 그 층 윤곽 값, source "outline"). */
export function applyCell(work, { path, value, scope = SCOPE_LAYER, outline = null, outlines = null } = {}) {
  if (!work) return fail(work, path, "편집할 요구영역이 없다");
  let m = /^\/(mach|alt|fuel)\/([01])$/.exec(path);
  if (m) {
    const r = num(value, path, `${{ mach: "마하", alt: "고도", fuel: "연료" }[m[1]]} 범위`);
    if (r.error) return { work, changes: [], error: r.error };
    const out = clone(work);
    out[m[1]][Number(m[2])] = r.v;
    return { work: out, changes: [], error: null };
  }
  if (path === "/base_grid/n_mach") {
    const r = num(value, path, "마하 점 수");
    if (r.error) return { work, changes: [], error: r.error };
    if (!Number.isInteger(r.v)) return fail(work, path, `마하 점 수는 정수: ${value}`);
    const out = clone(work);
    out.base_grid.n_mach = r.v;
    return { work: out, changes: [], error: null };
  }
  m = /^\/base_grid\/(alts|fuels)$/.exec(path);
  if (m) {
    let list;
    try {
      list = Array.isArray(value) ? value.map(Number) : parseNumberList(value);
      if (list.some((v) => !Number.isFinite(v))) throw new Error(`수치 목록이 아님: ${value}`);
    } catch (e) {
      return fail(work, path, e.message);
    }
    const out = clone(work);
    out.base_grid[m[1]] = list;
    return { work: out, changes: [], error: null };
  }
  m = /^\/boundary\/(\d+)\/rows\/(\d+)\/([012])$/.exec(path);
  if (!m) return fail(work, path, `모르는 칸: ${path}`);
  const r = num(value, path, COL_NAME[Number(m[3])]);
  if (r.error) return { work, changes: [], error: r.error };
  let base;
  try {
    base = work.boundary ? clone(work) : seedBoundary(work, outline);
  } catch (e) {
    return fail(work, path, e.message);
  }
  const [i, j, k] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const layer = base.boundary[i];
  const row = layer?.rows[j];
  if (!row) return fail(work, path, `경계표에 없는 행: ${path}`);
  const alt = row[0];
  const changes = [];
  const targets = scope === SCOPE_ALL ? base.boundary : [layer];
  for (const L of targets) {
    let hit = L.rows.find((x) => same(x[0], alt));
    let inserted = false;
    let source = null;
    if (!hit) {
      // 엔진이 그 층에서 낸 값만 — 고친 행을 복사하면 안 고친 칸(반대편 한계)이 다른 층 값으로 둔갑한다
      const lo = layerOutline(outlines, L.fuel);
      const o = (lo ?? []).find((x) => same(x.alt, alt));
      if (!o || o.state !== "in" || !Number.isFinite(o.mach_lo) || !Number.isFinite(o.mach_hi)) {
        const why = !lo ? "그 층의 엔진 윤곽을 아직 받지 못했다(미리 보기 뒤 다시)"
          : !o ? "그 층 윤곽에 그 고도가 없다"
            : `그 층에서 그 고도는 요구 ${o.state === "out_of_region" ? "범위 밖" : "미정의"}`;
        return fail(work, path, `「전체 연료」 거부 — 연료 ${fmtN(L.fuel)} kg 층에 고도 ${fmtN(alt)} m 행이 없고 ${why} — `
          + "값을 지어내지 않는다(「현재 연료만」으로 고치거나 그 층에 행을 먼저 넣는다)");
      }
      hit = [alt, o.mach_lo, o.mach_hi];
      source = "outline";
      inserted = true;
      L.rows.push(hit);
    }
    changes.push({ fuel: L.fuel, alt, col: k, old: hit[k], value: r.v, inserted, source });
    hit[k] = r.v;
  }
  return { work: sortBoundary(base), changes, error: null };
}

/** 행 추가 — [고도, 하한, 상한]을 보이는 연료의 층에(scope "all"이면 모든 층에 같은 값으로). 경계표가 없으면 먼저
 *  세운다. 이미 그 고도 행이 있는 층이 있으면 아무것도 바꾸지 않고 error로 알린다(값 고치기는 칸 편집으로). */
export function addRow(work, { fuel, row, scope = SCOPE_LAYER, outline = null } = {}) {
  const vals = (row ?? []).map((v) => (typeof v === "number" ? v : Number(String(v ?? "").trim() || NaN)));
  if (vals.length !== 3 || vals.some((v) => !Number.isFinite(v))) {
    return fail(work, "/boundary", "새 행은 [고도, 마하 하한, 마하 상한] 세 수치");
  }
  let base;
  try {
    base = work.boundary ? clone(work) : seedBoundary(work, outline);
  } catch (e) {
    return fail(work, "/boundary", e.message);
  }
  const i = layerIndexAt(base, fuel);
  if (i < 0) return fail(work, "/boundary", `연료 ${fuel} kg는 경계표 층이 아니다`);
  const targets = scope === SCOPE_ALL ? base.boundary : [base.boundary[i]];
  const clash = targets.filter((L) => L.rows.some((x) => same(x[0], vals[0]))).map((L) => L.fuel);
  if (clash.length) return fail(work, "/boundary", `고도 ${vals[0]} m 행이 이미 있다 (연료 ${clash.join(", ")} kg)`);
  for (const L of targets) L.rows.push([...vals]);
  return { work: sortBoundary(base), changes: targets.map((L) => ({ fuel: L.fuel, alt: vals[0], col: null, old: null,
    value: vals, inserted: true, source: "input" })), error: null };
}

/** 행 지우기 — 보이는 연료 층의 그 고도 행(scope "all"이면 그 고도 행이 있는 모든 층). 층이 비게 되면 지우지 않는다
 *  (검증기가 층마다 행 1개 이상을 요구한다). */
export function removeRow(work, { fuel, alt, scope = SCOPE_LAYER } = {}) {
  if (!work?.boundary) return fail(work, "/boundary", "경계표가 없다 — 지울 행이 없다");
  const base = clone(work);
  const i = layerIndexAt(base, fuel);
  if (i < 0) return fail(work, "/boundary", `연료 ${fuel} kg는 경계표 층이 아니다`);
  const targets = scope === SCOPE_ALL ? base.boundary : [base.boundary[i]];
  const changes = [];
  for (const L of targets) {
    const j = L.rows.findIndex((x) => same(x[0], alt));
    if (j < 0) continue;
    if (L.rows.length === 1) {
      return fail(work, `/boundary/${base.boundary.indexOf(L)}/rows`, `연료 ${L.fuel} kg 층의 마지막 행이라 지우지 않는다`);
    }
    changes.push({ fuel: L.fuel, alt, col: null, old: L.rows[j], value: null, inserted: false, source: null });
    L.rows.splice(j, 1);
  }
  return { work: base, changes, error: null };
}

/** 검증 오류 경로(서버 422 {path}) → 표의 칸 {cell, layer, row, col}. `/operating_region` 접두는 떼고, 목록 칸의
 *  원소(/base_grid/alts/2)·행 전체(/boundary/0/rows/1)·범위 전체(/mach)는 그것을 담는 칸으로 올린다.
 *  칸으로 못 가리키는 경로(층 연료·경계표 전체·빈 경로)는 cell null — 호출측이 캡션에 메시지만 낸다. */
export function errorCell(path) {
  const none = { cell: null, layer: null, row: null, col: null };
  if (typeof path !== "string") return none;
  const p = path.replace(/^\/operating_region(?=\/|$)/, "");
  let m = /^\/boundary\/(\d+)\/rows\/(\d+)(?:\/([012]))?/.exec(p);
  if (m) {
    const col = m[3] == null ? 0 : Number(m[3]);
    return { cell: `/boundary/${m[1]}/rows/${m[2]}/${col}`, layer: Number(m[1]), row: Number(m[2]), col };
  }
  m = /^\/boundary\/(\d+)/.exec(p);
  if (m) return { ...none, layer: Number(m[1]) };
  m = /^\/(mach|alt|fuel)(?:\/([01]))?/.exec(p);
  if (m) return { ...none, cell: `/${m[1]}/${m[2] ?? 0}` };
  m = /^\/base_grid\/(n_mach|alts|fuels)/.exec(p);
  if (m) return { ...none, cell: `/base_grid/${m[1]}` };
  if (p.startsWith("/base_grid")) return { ...none, cell: "/base_grid/n_mach" };
  return none;
}

/** 오류 → 강조할 표의 칸을 값으로 {fuel, alt, col, path}. 경계표 칸은 **보낸 사본**(sent)에서 그 층 연료·그 행 고도를
 *  읽는다 — 타자 중 고도가 바뀌어 사본이 다시 정렬되면 서버 경로의 행 색인은 화면의 행과 어긋난다(화면은 칸을 떠날
 *  때만 다시 짠다). 보낸 사본이 없거나(로컬 오류 — 칸 자신의 경로) 경계표 칸이 아니면 path(errorCell의 칸 이름). */
export function errorTarget(err, sent = null) {
  if (!err) return null;
  const c = errorCell(err.path);
  const L = c.layer != null && c.row != null ? sent?.boundary?.[c.layer] : null;
  const row = L?.rows?.[c.row];
  if (row) return { fuel: L.fuel, alt: row[0], col: c.col, path: null };
  return { fuel: null, alt: null, col: null, path: c.cell };
}

/** 캔버스 클릭 → 가장 가까운 윤곽 꼭짓점 {alt, side: "lo"|"hi", mach, dist} (반경 안에 없으면 null).
 *  scale — {x(mach)→px, y(alt)→px, r?: 반경 px(기본 8)}. 마하가 없는 행(미정의·영역 밖)은 꼭짓점이 없다. */
export function hitVertex(outline, px, py, scale) {
  const r = scale?.r ?? 8;
  let best = null;
  for (const row of outline ?? []) {
    for (const side of ["lo", "hi"]) {
      const mach = row[`mach_${side}`];
      if (!Number.isFinite(mach)) continue;
      const d = Math.hypot(scale.x(mach) - px, scale.y(row.alt) - py);
      if (d <= r && (!best || d < best.dist)) best = { alt: row.alt, side, mach, dist: d };
    }
  }
  return best;
}

/** 꼭짓점 → 표의 칸 이름. 보이는 연료의 표에 그 고도 행이 있으면 그 칸(경계표가 없으면 가상 행), 경계표가 있는데
 *  행이 없으면 null(보간된 고도다), 경계표가 없고 가상 행도 아니면 기본 마하 범위 칸(/mach/0 · /mach/1). */
export function vertexCell(work, fuel, hit, outline = null) {
  if (!work || !hit) return null;
  const col = hit.side === "lo" ? 1 : 2;
  const row = tableRows(work, fuel, outline).find((r) => same(r.alt, hit.alt));
  if (row) return row.paths[col];
  if (!work.boundary) return hit.side === "lo" ? "/mach/0" : "/mach/1";
  return null;
}

const count = (x) => (Array.isArray(x) ? x.length : Number.isFinite(x) ? x : null);
const fmtN = (v) => (Number.isInteger(v) ? String(v) : String(Number(Number(v).toPrecision(4))));

/** 「전체 연료」 쓰기에서 층마다 달랐던 값 → 「층마다 달랐던 마하 하한 덮음 — 10 kg 0.12 · 50 kg 0.14」 (행을 넣은
 *  층은 「30 kg 행 추가(윤곽|복사)」). 층이 하나뿐이거나 전부 같은 값이었으면 null — 덮은 것이 없다. */
export function layerNote(changes) {
  const cell = (changes ?? []).filter((c) => c.col != null);
  if (cell.length < 2) return null;
  const olds = cell.filter((c) => !c.inserted).map((c) => fmtN(c.old));
  if (!cell.some((c) => c.inserted) && new Set(olds).size <= 1) return null;
  const parts = cell.filter((c) => c.inserted || !same(c.old, c.value)).map((c) => (c.inserted
    ? `${fmtN(c.fuel)} kg 행 추가(윤곽)`
    : `${fmtN(c.fuel)} kg ${fmtN(c.old)}`));
  return parts.length ? `층마다 달랐던 ${COL_NAME[cell[0].col]} 덮음 — ${parts.join(" · ")}` : null;
}

// 소비자(서버 region_consumers의 what) → 짧은 이름. 모르는 것은 그대로 낸다(서버가 늘리면 화면이 지어내지 않게)
export const CONSUMER_NAME = Object.freeze({ de_trim: "δe_trim 표", gain_tables: "확정 게인 표", trim_store: "트림 저장소" });
const consumerName = (s) => CONSUMER_NAME[s.what] ?? s.what;

/** 미리보기 영향(impact) → 「바꾸면 영향: 기본 격자 n → m점 (유지 k · 새 트림 j · 빠짐 d) · 낡는 결과: …」.
 *  grid의 before·after·kept·added·dropped와 new_trims는 수 또는 점 목록 둘 다 받는다. 낡는 결과는 status "stale"만
 *  (없으면 「없음」), 요구영역 기록이 없어 낡았는지 모르는 것(no_record)은 「기록 없어 모름」으로 따로 — 낡지 않았다고
 *  말하지 않는다. opts.changes — 「전체 연료」 쓰기의 층별 변경(layerNote가 덮은 값을 덧붙인다). impact가 없으면 null. */
export function impactLine(impact, { changes = null } = {}) {
  if (!impact?.grid) return null;
  const g = impact.grid;
  const n = (x) => count(x) ?? 0;
  const newTrims = count(impact.new_trims) ?? count(g.added) ?? 0;
  const list = impact.stale ?? [];
  const stale = list.filter((s) => s.status === "stale").map(consumerName);
  const unknown = list.filter((s) => s.status === "no_record").map(consumerName);
  let line = `바꾸면 영향: 기본 격자 ${n(g.before)} → ${n(g.after)}점 (유지 ${n(g.kept)} · 새 트림 ${newTrims} · 빠짐 `
    + `${n(g.dropped)}) · 낡는 결과: ${stale.length ? stale.join(", ") : "없음"}`;
  if (unknown.length) line += ` (기록 없어 모름: ${unknown.join(", ")})`;
  const note = layerNote(changes);
  if (note) line += ` · ${note}`;
  return line;
}

/** 영향의 툴팁 — 대조 규칙·재사용 수·소비자 상태 전부(서버 label이 있으면 그 글). */
export function impactTip(impact) {
  if (!impact?.grid) return "";
  const parts = ["저장본 요구영역의 기본 격자와 이름(값 그대로)으로 대조했다 — 유지는 같은 이름의 점, "
    + "새 트림은 보낼 점 중 트림 저장소에 수렴 기록이 없는 점"];
  const reused = count(impact.reused ?? impact.grid.reused);
  if (reused != null) parts.push(`트림 저장소 재사용 ${reused}점(플랜트 키 — 요구영역과 무관)`);
  for (const s of impact.stale ?? []) parts.push(s.label ?? `${consumerName(s)}: ${s.status}`);
  return parts.join(" · ");
}

const span = (v, unit = "") => (Array.isArray(v) && v.length === 2 ? `${fmtN(v[0])}–${fmtN(v[1])}${unit}` : "—");

/** 요구영역 이력(GET /profiles/{id}/region-history) → 계보 표 행(최신 리비전이 위).
 *  current — {region_key}: 지금 저장본의 판과 같은 행에 current. 요구영역이 없는 리비전은 「없음」, 서버가 못 읽은
 *  리비전({unreadable, reason})은 「못 읽음」(사유는 source 칸) — 건너뛰면 이력에 구멍이 보이지 않는다. */
export function lineageRows(history, current = null) {
  return [...(history ?? [])].sort((a, b) => b.revision - a.revision).map((h) => (h.unreadable ? {
    revision: h.revision, key: null, state: "못 읽음", source: h.reason ?? "—", range: "—", points: null, current: false,
  } : {
    revision: h.revision,
    key: h.region_key ?? null,
    state: h.region_key == null ? "없음" : h.confirmed ? "확정" : "초안",
    source: h.source ?? "—",
    range: h.region_key == null ? "—"
      : `마하 ${span(h.mach)} · 고도 ${span(h.alt, " m")} · 연료 ${span(h.fuel, " kg")}`,
    points: Number.isFinite(h.n_points) ? h.n_points : null,
    current: current?.region_key != null && h.region_key === current.region_key,
  }));
}

/** 편집 사본 → 캡션의 경계표 요약 「경계표 2층 · 4행」(없으면 「경계표 없음」). */
export function boundarySummary(work) {
  if (!work?.boundary) return "경계표 없음";
  const rows = work.boundary.reduce((s, l) => s + l.rows.length, 0);
  return `경계표 ${work.boundary.length}층 · ${rows}행`;
}

/** 편집 그림의 좌표 — 가로 마하(요구 범위 ∪ 모델 마하 ∪ 격자 점), 세로 고도(요구 범위, 위로 증가). 여백 안쪽이
 *  그림이고 여백은 눈금 숫자 자리다(그림 위에는 글자를 두지 않는다). 사본이 없으면 null. */
export const PLOT_MARGIN = Object.freeze({ mL: 56, mR: 16, mT: 12, mB: 30 });

export function plotScale({ work, model = null, points = [], width, height }) {
  if (!work) return null;
  const { mL, mR, mT, mB } = PLOT_MARGIN;
  const ms = [...work.mach, ...(model?.mach ?? []), ...(points ?? []).map((p) => p.mach)].filter(Number.isFinite);
  let m0 = Math.min(...ms);
  let m1 = Math.max(...ms);
  const mp = (m1 - m0 || 0.1) * 0.04;
  m0 -= mp;
  m1 += mp;
  let [a0, a1] = work.alt;
  const ap = (a1 - a0 || 200) * 0.05;
  a0 -= ap;
  a1 += ap;
  return {
    mL, mR, mT, mB, width, height, domain: { mach: [m0, m1], alt: [a0, a1] },
    x: (m) => mL + ((m - m0) / (m1 - m0)) * (width - mL - mR),
    y: (a) => height - mB - ((a - a0) / (a1 - a0)) * (height - mT - mB),
  };
}
