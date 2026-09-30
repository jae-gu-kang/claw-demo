/** 자동 설계 탭 순수 로직 — 설정 페이로드·점/판정 결합·처방 그룹·게인 채택. DOM·통신 없음.

수치의 정본은 서버(GET /design/defaults ← 엔진 AutoDesignConfig)다 — 여기서
기본값을 다시 적지 않고, 사용자가 채운 칸만 config 덮어쓰기로 보낸다.

게인 채택은 기존 스토어 계약(gains 탭 storePayload — {tables, scheduleOff})으로
낸다. 주입은 `gain_export.tables_resampled`이고, 표 모드(v1.47 기본)에서는 그것이
세션이 검증한 표 **그 자체**이며 다항 모드에서는 **재샘플 테이블**이다 — 다항
정본(kind='poly')은 서버 sim/codegen이 직접 받지만, 웹 스토어 소비자(블록도
표시·influence·웹 코드 미리보기)가 테이블 형상을 전제하므로 스토어 경유는
호환 반출을 쓴다 (다항 스토어 채택은 [백로그] — docs -01 §3.4).

출처(`gainTablesSource`)를 함께 넣는다 — 게인 탭이 되읽을 때 "자동 설계 확정본
(결과 id)"이라고 이름을 댈 수 있어야, 화면에 뜬 표가 어디서 온 것인지가 분명해진다.
*/

import { parseNumberList } from "./grid.js";
import { reuseLine, reuseTip } from "./opspace.js";
import { EXCLUSION_CATEGORY_LABEL, marginShortText, verdictExclusionText } from "./plot.js";
import { EXAMPLE_ID } from "./profile.js";

/** 수치 표기 — dom.js의 fmt와 같은 정책(null=—, "inf"=∞, 유효자릿수).
 *
 * lib은 DOM 계층을 import하지 않는다는 규약 때문에 여기 한 벌을 둔다. 정책이
 * 갈리면 같은 수가 카드와 표에서 다르게 보이므로 fmt와 함께 고칠 자리다. */
/** 비유한값 문자열("inf"/"-inf")을 걸러낸 수치 — 아니면 null.
 *
 * 크기 계산·정렬에는 이걸 쓴다. `num`은 표시용이라 문자열을 그대로 받아 넘긴다. */
function numeric(x) {
  return typeof x === "number" && Number.isFinite(x) ? x : null;
}

function num(x, digits = 3) {
  if (x == null) return "—";
  if (x === "inf") return "∞";
  if (x === "-inf") return "−∞";
  if (typeof x !== "number") return String(x);
  if (Number.isInteger(x) && Math.abs(x) < 1e6) return String(x);
  return x.toPrecision(digits);
}

export const VERDICT_LABEL = {
  simple_deficit: "단순 마진 부족 — 검증점 추가",
  plant_variation: "플랜트 급변 — 설계점 승격(그 점을 트림·튜닝)",
  // 절점 분리(05 §11.13 이관 3단계) — 보간 괴리는 점을 올리는 것이 아니라 이름 댄 표에 절점을 더한다(add_knot).
  // 분리는 표 단위다(그 표 전체가 새 집합으로) — 구간 단위로 읽히는 말을 쓰지 않는다
  gain_interp_valley: "게인 보간 valley — 해당 표에 절점 추가 (공통 집합을 쓰던 표면 그 표를 분리 집합으로)",
  structural_limit: "구조 한계 — 상위 설계 변경 검토 (보고 전용)",
  // v1.70부터 절점 추가(검증점이면 설계점 편입 동반) — 옛 결과의 refit_at 카드는 actionText가 「옛 결과」로 읽는다
  gain_sign_flip: "게인 부호 뒤집힘 — 그 마하에 절점 추가 (검증점이면 설계점 편입)",
  // 엔진 classify VERDICTS의 여섯째 — 빠져 있어 카드·원장에 코드("fit_residual")가 그대로 떴다.
  // 표 모드는 절점 추가(add_knot — 이관 3단계), 조일 적합(tighten_fit)은 다항에만 있다
  fit_residual: "설계점 적합 괴리 — 표: 절점 추가 · 다항: 적합 허용치 조이기",
};

const _STATUS_RANK = { ok: 0, na: 1, warn: 2, fail: 3 };

export function statusRank(s) {
  return _STATUS_RANK[s] ?? 1;
}

/** 자리별 판정 dict → 최악 판정 (fail > warn > na > ok). 빈 dict는 null(미판정). */
export function worstStatus(loops) {
  let worst = null;
  for (const entry of Object.values(loops ?? {})) {
    const s = entry?.status;
    if (s == null) continue;
    if (worst == null || statusRank(s) > statusRank(worst)) worst = s;
  }
  return worst;
}

/** 판정선·튜닝 목표는 설계 설정이 아니라 **기체 문서**의 것이다(기준 통합 ① — /criteria·/tuning). 서버 자동
 * 설계는 선택 기체의 그 절로 설계하고, 요청의 config.criteria·config.targets는 곧 거절한다 — 화면·신호 어느 길로도
 * 싣지 않는다. */
export const CRITERIA_CONFIG_KEYS = ["criteria", "targets"];

/** config에서 판정선·튜닝 목표 칸을 뗀 사본 — 기록된 설계 설정(provenance)·신호 config를 요청으로 옮길 때. */
export function withoutCriteria(config) {
  const out = { ...(config ?? {}) };
  for (const k of CRITERIA_CONFIG_KEYS) delete out[k];
  return out;
}

const fmtCrit = (v) => (typeof v === "number" && Number.isFinite(v) ? String(+v.toPrecision(6)) : "—");

/** GET /profiles/{id}/criteria 응답 → 읽기 전용 요약(자동 설계 탭의 「판정선·튜닝 목표」 패널).
 *  판정선의 뜻(방향·합격선·권장선·목표 칸)은 응답의 lines가 정본이다 — 여기서 다시 적지 않는다. 칸마다 값과
 *  출처(written에 적혔으면 "profile" = 이 기체가 바꾼 값, 아니면 "default" = 도구 기본값)를 낸다.
 *  돌려주는 것: {rows: [{metric, label, unit, cells: [{kind, key, value, text, source}]}], extra, conflicts, written}.
 *  kind ∈ "pass"(합격선) | "rec"(권장선) | "target"(튜닝 목표). 비율선(λ — 목표의 비율)은 text에 "× 목표"를 붙인다. */
export function criteriaSummaryModel(body) {
  const applied = body?.applied ?? {};
  const margin = applied.margin ?? {};
  const targets = applied.targets ?? {};
  const wMargin = body?.written?.criteria?.margin ?? {};
  const wTargets = body?.written?.tuning?.targets ?? {};
  const src = (w, k) => (w[k] != null ? "profile" : "default");
  const ge = (dir) => (dir === "max" ? "≤" : "≥");
  const used = new Set();
  const rows = (Array.isArray(body?.lines) ? body.lines : []).map((ln) => {
    const cells = [];
    for (const [kind, key] of [["pass", ln.pass_key], ["rec", ln.rec_key]]) {
      if (!key) continue;
      used.add(key);
      const v = margin[key];
      const text = ln.ratio_of_target ? `${ge(ln.direction)} ${fmtCrit(v)} × 목표` : `${ge(ln.direction)} ${fmtCrit(v)}`;
      cells.push({ kind, key, value: v ?? null, text, source: src(wMargin, key) });
    }
    if (ln.target_key) {
      const v = targets[ln.target_key];
      cells.push({ kind: "target", key: ln.target_key, value: v ?? null, text: fmtCrit(v),
        source: src(wTargets, ln.target_key) });
    }
    return { metric: ln.metric, label: ln.label, unit: ln.unit ?? "", cells };
  });
  // 판정선 표(lines)에 없는 margin 칸(심각선·참여도 하한 등) — 숨기지 않고 한 줄로
  const extra = Object.keys(margin).filter((k) => !used.has(k)).map((k) => ({
    key: k, value: margin[k], text: fmtCrit(margin[k]), source: src(wMargin, k),
  }));
  // 「적지 않았다」는 문서 전체로 판단한다 — 표에 서는 margin·targets만 보면 /criteria.stability나 /tuning.weights만
  // 적은 기체에 「전부 도구 기본값」이라고 거짓말을 한다
  const w = body?.written ?? {};
  const written = ["criteria", "tuning"].some((sec) =>
    Object.values(w[sec] ?? {}).some((grp) => grp && Object.keys(grp).length > 0));
  return { rows, extra, conflicts: Array.isArray(body?.target_conflicts) ? body.target_conflicts : [], written };
}

/** 폼 → config 덮어쓰기 — 채운 칸만. 수치 목록 오류는 던진다 (호출측이 표시).
 * 판정선·튜닝 목표(criteria·targets)는 싣지 않는다 — 기체 문서의 것이다(CRITERIA_CONFIG_KEYS). */
export function buildConfig(form) {
  const out = {};
  if (form.mode) out.mode = form.mode;
  // 게인 표현 — 수치가 아니라 열거값이라 nums 목록에 넣으면 NaN으로 던진다.
  // 허용 목록은 엔진(AutoDesignConfig.fit_mode)이 본다 — 여기서 재기술하지 않는다
  if (form.fitMode) out.fit_mode = form.fitMode;
  const nums = [
    ["budgetPoints", "budget_points"],
    ["budgetIters", "budget_iters"],
    ["nMach", "n_mach"],
    ["nValidationBetween", "n_validation_between"],
    ["actuatorWn", "actuator_wn"],
    ["actuatorZeta", "actuator_zeta"],
    ["delayS", "delay_s"],
  ];
  for (const [from, to] of nums) {
    const raw = String(form[from] ?? "").trim();
    if (!raw) continue;
    const v = Number(raw);
    if (!Number.isFinite(v)) throw new Error(`${to}: 수치가 아님 — ${raw}`);
    out[to] = v;
  }
  for (const [from, to] of [["altsText", "alts"], ["fuelsText", "fuels"]]) {
    const raw = String(form[from] ?? "").trim();
    if (!raw) continue;
    out[to] = parseNumberList(raw);
  }
  const knots = knotConfig(form);
  if (knots) out.knots = knots;
  const validation = validationConfig(form);
  if (validation) out.validation = validation;
  const reinforce = reinforceConfig(form);
  if (reinforce) out.reinforce = reinforce;
  return out;
}

/** 절점 설정 칸 → config.knots 부분 덮어쓰기(서버가 기본값 위에 겹친다) — 채운 칸만, 없으면 null.
 *  규칙(knotRule)은 열거값이라 그대로, 절점 수·표당 상한은 정수, 좌표는 공백·쉼표 목록. 허용 목록·순증가·하한은
 *  서버(_check_knots)가 본다 — 여기서 재기술하지 않는다. */
function knotConfig(form) {
  const out = {};
  if (form.knotRule) out.rule = form.knotRule;
  for (const [from, to] of [["knotN", "n"], ["knotMax", "max_per_table"]]) {
    const raw = String(form[from] ?? "").trim();
    if (!raw) continue;
    const v = Number(raw);
    if (!Number.isFinite(v)) throw new Error(`knots.${to}: 수치가 아님 — ${raw}`);
    out[to] = v;
  }
  const coords = String(form.knotCoordsText ?? "").trim();
  if (coords) out.coords = parseNumberList(coords);
  return Object.keys(out).length ? out : null;
}

/** 검증 조건 글 → [[고도, 연료], …] — 「고도/연료」 짝을 쉼표·세미콜론·공백으로 가른다("200/25, 3000/10").
 *  짝이 아니거나 수치가 아니면 던진다(호출측이 표시). 빈 글은 null(= 서버 기본: 설계 행 전부). */
export function parseConditionPairs(text) {
  const raw = String(text ?? "").trim();
  if (!raw) return null;
  return raw.split(/[\s,;]+/).filter(Boolean).map((tok) => {
    const parts = tok.split("/");
    const v = parts.map((x) => (x.trim() === "" ? NaN : Number(x)));
    if (parts.length !== 2 || !v.every(Number.isFinite)) {
      throw new Error(`validation.conditions: 「고도/연료」 짝이 아님 — ${tok}`);
    }
    return v;
  });
}

/** 검증점 설정 칸 → config.validation 부분 덮어쓰기(05 §11.6 — 서버가 기본값 위에 겹친다). 채운 칸만, 없으면 null.
 *  조건(validationConditionsText)은 「고도/연료」 짝 목록, 방식(validationMode)은 열거값 그대로(허용 목록은 서버
 *  /design/defaults의 validation_modes — 판정은 엔진 check_validation_config), 경계점(validationBoundary)은 "on"/"off". */
export function validationConfig(form) {
  const out = {};
  const conds = parseConditionPairs(form.validationConditionsText);
  if (conds) out.conditions = conds;
  if (form.validationMode) out.mode = form.validationMode;
  const b = String(form.validationBoundary ?? "");
  if (b === "on" || b === "off") out.boundary = b === "on";
  return Object.keys(out).length ? out : null;
}

/** 보강 설정 칸 → config.reinforce 부분 덮어쓰기(05 §11.7). 허용치(tol)·추가점 상한·이분 깊이·시간 상한 — 채운 칸만,
 *  없으면 null. 허용치를 비우면 서버 기본(미설정 — 이분 없이 d 분포만)이다. 범위는 엔진 check_reinforce_config가 본다. */
export function reinforceConfig(form) {
  const out = {};
  for (const [from, to] of [["reinforceTol", "tol"], ["reinforceMaxPoints", "max_points"],
    ["reinforceMaxDepth", "max_depth"], ["reinforceMaxTime", "max_time_s"]]) {
    const raw = String(form[from] ?? "").trim();
    if (!raw) continue;
    const v = Number(raw);
    if (!Number.isFinite(v)) throw new Error(`reinforce.${to}: 수치가 아님 — ${raw}`);
    out[to] = v;
  }
  return Object.keys(out).length ? out : null;
}

// ── 점 역할 · 절점 (05 §11.13 이관 3단계 — 설계점과 절점 분리) ────────────────

/** 점 역할 이름 — 설계점(튜닝하는 점)과 검증점(절점 사이를 재는 점) 둘. anchor·breakpoint는 옛 결과(역할 위계
 *  시절)의 이름이라 그대로 읽히게 남긴다 — 엔진은 옛 세션을 되읽을 때 둘 다 설계점으로 옮긴다. */
export const ROLE_LABEL = {
  design: "설계점(튜닝)",
  validation: "검증점",
  anchor: "앵커(옛 결과 — 설계점)",
  breakpoint: "breakpoint(옛 결과 — 설계점)",
};

/** 옛 역할(anchor·breakpoint)을 설계점으로 묶은 역할 — 개수 셈·색 구분용. 모르는 역할은 그대로. */
export function roleGroup(role) {
  return role === "anchor" || role === "breakpoint" ? "design" : role;
}

/** report.points → "설계점 a · 검증점 b". 옛 결과(design 칸 없음, anchor·breakpoint 칸)는 옛 이름 그대로 —
 *  옛 결과를 새 이름으로 합쳐 말하면 그 실행이 절점을 따로 정한 것처럼 읽힌다. missing은 없는 칸의 표기. */
export function pointCountText(pts, missing = "?") {
  const p = pts ?? {};
  const v = (k) => p[k] ?? missing;
  if (p.design == null && (p.anchor != null || p.breakpoint != null)) {
    return `앵커 ${v("anchor")} · bp ${v("breakpoint")} · 검증 ${v("validation")}`;
  }
  return `설계점 ${v("design")} · 검증점 ${v("validation")}`;
}

/** 마하 좌표 표기 — M0.15 (유효 3자리). */
export function machText(m) {
  const v = numeric(m);
  return v == null ? "M?" : `M${Number(v.toPrecision(3))}`;
}

const KNOT_SOURCE_TEXT = {
  base_axis: "요구영역 기본 격자",
  user: "사용자 좌표",
  samples: "튜닝한 마하 전부(옛 방식)",
};

/** 절점 집합의 출처 코드(엔진 KnotSet.source) → 한국어. uniform:<n> · split:<부모>는 꼬리를 읽는다. 모르는 코드는
 *  그대로(삼키면 엔진에 규칙이 늘어도 화면이 조용하다). */
export function knotSourceText(source) {
  if (source == null || source === "") return "출처 기록 없음";
  const s = String(source);
  if (KNOT_SOURCE_TEXT[s]) return KNOT_SOURCE_TEXT[s];
  if (s.startsWith("uniform:")) return `설계 마하 구간 ${s.slice(8)}등분`;
  if (s.startsWith("split:")) return `${knotSetName(s.slice(6))}에서 분리`;
  return s;
}

/** 절점 집합 이름 — 엔진 기본 공유 집합(knots.COMMON "common")은 「공통」, 떼어 낸 집합은 그 표 이름들(a+b). */
export function knotSetName(name) {
  return name === "common" ? "공통" : name == null ? "—" : String(name);
}

/** 절점 집합 이력 한 항목(엔진 KnotSet.history — op init·split·add) → 한 줄. 모르는 모양은 JSON 그대로. */
export function knotHistoryText(h) {
  if (!h || typeof h !== "object") return String(h ?? "");
  const iter = h.iter ?? h.iter_n;
  if (h.op === "init") return `시작 — 규칙 ${h.rule ?? "?"} · ${h.n ?? "?"}절점`;
  if (h.op === "split") return `${knotSetName(h.from)}에서 분리${iter != null ? ` · 이터 ${iter}` : ""}`;
  const bits = [];
  if (h.mach != null) bits.push(`${machText(h.mach)} 추가`);
  if (h.point) bits.push(`점 ${h.point}`);
  if (iter != null) bits.push(`이터 ${iter}`);
  if (h.reason) bits.push(`사유 ${h.reason}`);
  return bits.length ? bits.join(" · ") : JSON.stringify(h);
}

/** 뺀 절점 → {edge: 끝 바깥(범위 밖 — 끝값 clip), dropped: 안쪽(표본이 멀거나 없어 뺌 — 이웃 절점 직선으로 메움)}.
 *  엔진 unsupported_detail[].edge가 있으면 그대로, 없으면(사유 기록 이전) 남은 절점 범위로 가른다. */
function splitUnsupported(unsupported, detail, coords) {
  const byKnot = new Map((Array.isArray(detail) ? detail : [])
    .filter((d) => d && typeof d.edge === "boolean").map((d) => [Number(d.knot), d.edge]));
  const drop = new Set(unsupported.map(Number));
  const kept = (coords ?? []).map(Number).filter((c) => Number.isFinite(c) && !drop.has(c));
  const lo = kept.length ? Math.min(...kept) : null;
  const hi = kept.length ? Math.max(...kept) : null;
  const edge = [];
  const dropped = [];
  for (const c of unsupported) {
    const k = Number(c);
    const isEdge = byKnot.has(k) ? byKnot.get(k) : lo == null ? true : k < lo || k > hi;
    (isEdge ? edge : dropped).push(c);
  }
  return { edge, dropped };
}

/** 표별 절점 모델 — gain_export.knots(엔진 knot_record: {sets, tables})·report.knots({tables:{자리:n}, shared})·
 *  fits[자리].unsupported_knots를 한 모양으로. 둘 다 없으면(절점 분리 이전 결과) null.
 *
 *  돌려주는 것: {rows:[{slot, set, n, common, shared, sharedText, unsupported, edge, dropped, coords, source,
 *  sourceText, history, historyLines}], sets:[{name, n, members, sourceText}], summary}. common은 이 표가 **공통 집합**
 *  (엔진 knots.COMMON "common")을 쓰는가 — 공유/분리의 뜻은 이것이다. 엔진 표 기록의 shared는 「그 집합을 쓰는 표가
 *  둘 이상인가」라 떼어 낸 집합을 두 표가 함께 써도 true다(공통 집합으로 읽으면 틀린다) — sharedText의 「(n표 함께)」로만
 *  쓴다. unsupported는 그 표에서 뺀 절점 전부, edge·dropped는 끝 바깥(범위 밖)과 안쪽에서 뺀 것의 갈래다. */
export function knotModel(body) {
  const rec = body?.gain_export?.knots;
  const rk = body?.report?.knots;
  const hasRec = rec && typeof rec === "object";
  const hasRk = rk && typeof rk === "object";
  if (!hasRec && !hasRk) return null;
  const sets = (hasRec && rec.sets && typeof rec.sets === "object") ? rec.sets : {};
  const tables = (hasRec && rec.tables && typeof rec.tables === "object") ? rec.tables : {};
  const counts = (hasRk && rk.tables && typeof rk.tables === "object") ? rk.tables : {};
  const slots = [...new Set([...Object.keys(tables), ...Object.keys(counts)])].sort();
  const users = {};
  for (const t of Object.values(tables)) if (t?.set != null) users[t.set] = (users[t.set] ?? 0) + 1;
  const rows = slots.map((slot) => {
    const t = tables[slot] ?? {};
    const set = t.set ?? null;
    const ks = set != null ? sets[set] : null;
    const coords = Array.isArray(ks?.coords) ? ks.coords : null;
    const fitUnsup = body?.fits?.[slot]?.unsupported_knots;
    const unsupported = Array.isArray(t.unsupported) ? t.unsupported
      : Array.isArray(fitUnsup) ? fitUnsup : [];
    const detail = t.unsupported_detail ?? body?.fits?.[slot]?.unsupported_detail;
    const { edge, dropped } = splitUnsupported(unsupported, detail, coords);
    const n = numeric(counts[slot]) ?? numeric(t.n) ?? (coords ? coords.length - unsupported.length : null);
    const common = set == null ? null : set === "common";
    const shared = typeof t.shared === "boolean" ? t.shared : null;
    const nUsers = set != null ? users[set] ?? 0 : 0;
    const sharedText = common == null ? "—" : common ? "공통 집합"
      : nUsers > 1 ? `분리 집합(${nUsers}표 함께)` : "분리 집합";
    const history = Array.isArray(ks?.history) ? ks.history : [];
    return {
      slot, set, setName: knotSetName(set), n, common, shared, sharedText,
      unsupported, edge, dropped, coords, source: ks?.source ?? null, sourceText: knotSourceText(ks?.source),
      history, historyLines: history.map(knotHistoryText),
    };
  });
  const setRows = Object.entries(sets).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)).map(([name, ks]) => ({
    name, displayName: knotSetName(name), n: Array.isArray(ks?.coords) ? ks.coords.length : null,
    members: rows.filter((r) => r.set === name).map((r) => r.slot),
    sourceText: knotSourceText(ks?.source),
  }));
  const nCommon = rows.filter((r) => r.common === true).length;
  const nSplit = rows.filter((r) => r.common === false).length;
  const nEdge = rows.reduce((acc, r) => acc + r.edge.length, 0);
  const nDropped = rows.reduce((acc, r) => acc + r.dropped.length, 0);
  const ns = rows.map((r) => r.n).filter((x) => x != null);
  const span = ns.length ? (Math.min(...ns) === Math.max(...ns) ? `${ns[0]}` : `${Math.min(...ns)}~${Math.max(...ns)}`) : "?";
  const bits = [`표 ${rows.length}개 · 절점 ${span}`];
  if (setRows.length) bits.push(`집합 ${setRows.length}`);
  // 보고 knots.shared = 표 전부가 한 집합(엔진 knots_summary) — 그때는 한 마디로
  if (rk?.shared === true && !nSplit) bits.push("전 표 공통 집합");
  else if (nCommon || nSplit) bits.push(`공통 ${nCommon} · 분리 ${nSplit}`);
  if (nEdge) bits.push(`범위 밖 절점 ${nEdge}`);
  if (nDropped) bits.push(`안쪽에서 뺀 절점 ${nDropped}`);
  return { rows, sets: setRows, summary: `절점 — ${bits.join(" · ")}` };
}

/** 문서의 확정 게인 표 출처(provenance.knots — 자동 설계 반영이 적는다) → 게인 탭 배지 {label, tone, tip}. 기록이
 *  없으면(옛 반영·손으로 적은 표) null. 배지 글은 짧게(공통 집합 / 분리 k/n — 공통 집합을 안 쓰는 표 수), 표별
 *  집합·절점 수·출처는 툴팁. 판단은 집합 이름(공통 집합인가)이다 — 집합별 shared(사용자 둘 이상)로 세면 떼어 낸
 *  집합을 두 표가 함께 쓸 때 「공유」로 잘못 그린다. */
export function knotBadgeSpec(knots) {
  const m = knots && typeof knots === "object" ? knotModel({ gain_export: { knots } }) : null;
  if (!m || !m.rows.length) return null;
  const split = m.rows.filter((r) => r.common === false).length;
  const label = split ? `절점 분리 ${split}/${m.rows.length}` : "절점 공통 집합";
  const tip = [m.summary, ...m.rows.map((r) => `${r.slot} — ${r.sharedText} · 집합 ${r.setName} · `
    + `${r.coords ? r.coords.length : "?"}절점 · ${r.sourceText}`
    + (r.edge.length ? ` · 범위 밖 ${r.edge.length}` : "")
    + (r.dropped.length ? ` · 안쪽에서 뺌 ${r.dropped.length}` : ""))].join("\n");
  return { label, tone: "na", tip };
}

/** 처방의 동작(action) → 한 줄 — 무엇을 어디에 하나. add_knot은 반영 전엔 요청만(「절점 추가 요청: M0.15 → 표 a·b」 —
 *  분리될지는 엔진이 반영할 때 정한다: 이름 댄 표가 그 집합의 사용자 전부면 제자리에 더한다), 반영 뒤엔 엔진 결과
 *  (knot = 카드의 a.knot {added, split, skipped})대로 말한다. 설계점 승격 동반이면 그 점을 붙인다. 옛 결과의
 *  promote·refit_at·tighten_fit도 읽힌다. 모르는 동작은 코드 그대로. */
export function actionText(act, knot = null) {
  const t = act?.type;
  if (!t) return null;
  if (t === "add_knot") {
    const slots = Array.isArray(act.slots) && act.slots.length ? act.slots.join("·") : "?";
    const where = `${machText(act.mach)} → 표 ${slots}`;
    const promote = act.promote ? ` · 점 ${act.point ?? "?"} 설계점 승격(튜닝)` : "";
    if (!knot || typeof knot !== "object") return `절점 추가 요청: ${where}${promote}`;
    if (!knot.added) return `절점 추가 안 됨: ${where}${knot.skipped ? ` — ${knot.skipped}` : ""}${promote}`;
    const split = Array.isArray(knot.split) ? knot.split : [];
    return `절점 추가: ${where} (${split.length ? `분리 집합으로 뗌: ${split.join(", ")}` : "그 집합을 쓰는 표 전부"})`
      + promote;
  }
  if (t === "promote") {
    return `승격: 점 ${act.point ?? "?"} → ${ROLE_LABEL[act.to] ?? act.to ?? "?"}`;
  }
  if (t === "add_validation") return "검증점 추가";
  if (t === "refit_at") return `재적합 고정: 점 ${act.point ?? "?"} (옛 결과)`;
  if (t === "tighten_fit") return "적합 허용치 조이기 (다항)";
  if (t === "escalate") return "상위 설계 변경 검토 (보고 전용)";
  return String(t);
}

/** 결과 → 점 행 [{name, mach, alt, fuel, role, trimmable, status}] —
 * 마진맵 판정을 이름으로 결합, 판정 없는 점은 status null(미판정). */
export function pointRows(result) {
  const cases = result?.margin_out?.cases ?? {};
  return (result?.points?.points ?? []).map((p) => ({
    name: p.name,
    mach: p.mach,
    alt: p.alt,
    fuel: p.fuel,
    role: p.role,
    // 역할 묶음 — 옛 결과의 앵커·breakpoint도 설계점(이관 3단계). 이름 칸은 roleLabel(옛 이름을 그대로 보인다)
    roleGroup: roleGroup(p.role),
    roleLabel: ROLE_LABEL[p.role] ?? p.role ?? "역할 미상",
    trimmable: p.trimmable,
    // 엔진이 처방·수렴 판정에서 뺀 점(트림은 수렴했으나 조건 판정이 채택하지 않음 — 제한 위반·모델 범위 밖) —
    // 미수렴과 다른 상태다. 여유 미달은 채택이라 여기 없다(v1.65)
    outsideEnvelope: Boolean(cases[p.name]?.outside_envelope),
    status: worstStatus(cases[p.name]?.loops),
    // 조건 판정(05 §11.3 · 이관 8단계 — 엔진 OperatingPoint.verdict). 옛 결과에는 없다(null)
    verdict: p.verdict ?? null,
    // 트림하지 않은 요구영역 점(이관 2단계 — 요구영역 밖·미정의, 모델 부족). 트림한 해의 모델 범위 밖과 다르다
    untrimmed: isUntrimmed(p.verdict),
  }));
}

function isUntrimmed(v) {
  const cat = v && !v.adopted ? v.exclusion?.category : null;
  return cat === "region" || (cat === "model" && v.trim?.status !== "computable");
}

/** 점 표 「자동 설계 채택」 열 — 조건 판정의 채택 여부(성능 판정이 아니다: 마진 판정은 옆 「판정」 열).
 *
 * 종전에는 "불가" 하나가 **미수렴**과 **엔벨로프 경계**를 함께 가리켰다. 둘은
 * 성격이 전혀 다르다: 앞은 트림해가 없어 볼 것이 없는 점이고, 뒤는 트림해는
 * 있으나 조건 판정이 채택하지 않아 설계 대상에서 빠진 점이다(마진 수치는 나온다).
 * 채택은 「OK」라 쓰지 않는다 — 옆 판정 열의 ok(성능 합격)와 같은 낱말이면 채택이 합격으로 읽힌다.
 * 채택된 여유 미달 점은 「채택 · 추진 여유 미달」 — 설계에 쓰되 미달을 표시한다(v1.65). */
export function trimLabel(row) {
  // 조건 판정이 실린 결과는 그 제외 항목과 사유로 — 트림 탭 표(plot.js trimStateLabel·verdictEvidenceText)와 같은
  // 사유 글이라, 같은 조건에 두 탭이 다른 말을 하지 않는다(이관 8단계 완료 기준). 「엔벨로프 경계」 한 낱말은
  // 여유 미달·제한 위반·모델 범위 밖을 뭉쳤다. 여유 미달은 채택이라 채택에 붙인다
  const v = row?.verdict;
  if (v) {
    if (v.adopted || !v.exclusion) {
      const short = marginShortText(row);
      return short ? `채택 · ${short}` : "채택";
    }
    const cat = EXCLUSION_CATEGORY_LABEL[v.exclusion.category] ?? v.exclusion.category;
    const why = verdictExclusionText(row);
    return why ? `제외 — ${cat} — ${why}` : `제외 — ${cat}`;
  }
  // 판정 없는 옛 결과 — 그때의 엔벨로프 경계는 여유 미달 제외였다(옛 정책)
  if (row?.outsideEnvelope) return "제외 — 엔벨로프 경계";
  if (row?.trimmable === false) return "제외 — 미수렴";
  if (row?.trimmable) return "채택";
  return "미판정";
}

/** 점 행 목록 → 판정 개수 {ok, warn, fail, na, outside, unjudged}.
 *
 * "경고가 왜 이렇게 많나"에 화면이 스스로 답하려면 먼저 몇 건인지 세어야 한다.
 * 표를 눈으로 세는 것이 유일한 방법이면 사용자는 경고의 규모를 오해한다.
 *
 * 엔벨로프 경계 점은 **판정 칸에서 뺀다** — 엔진이 그 점의 실패를 처방 목록에서
 * 제외하므로(schedmap.outside_envelope), 개수에만 섞으면 화면이 세는 실패와
 * 처방 카드 수가 어긋난다. 빼되 자기 칸에 세어 조용한 누락은 만들지 않는다. */
export function statusCounts(rows) {
  const out = { ok: 0, warn: 0, fail: 0, na: 0, outside: 0, untrimmed: 0, unjudged: 0 };
  for (const r of rows ?? []) {
    if (r?.outsideEnvelope) { out.outside += 1; continue; }
    // 트림하지 않은 요구영역 점 — 판정할 해가 없으니 미판정과 섞지 않고 자기 칸에(개수는 남는다)
    if (r?.untrimmed) { out.untrimmed += 1; continue; }
    const s = r?.status;
    if (s == null) out.unjudged += 1;
    else if (s in out) out[s] += 1;
  }
  return out;
}

/** 판정 기준 dict → 판정어의 뜻 문장 [{key, text}] — 기준 수치를 문장에 박아 낸다.
 *
 * 종전 화면은 ok/warn/fail 칩만 띄우고 뜻을 어디에도 적지 않아, warn이 "합격이나
 * 목표 미달"인지 "곧 실패"인지 알 수 없었다. 수치는 결과에 동봉된 criteria(판정에
 * 실제로 쓴 값)에서 읽는다 — 여기에 기본값을 다시 적으면 기준을 바꿨을 때 화면만
 * 옛 수치를 말하게 된다. */
export function verdictLegend(criteria) {
  const c = criteria ?? {};
  const n = (v, unit) => (v == null ? "?" : `${v}${unit}`);
  return [
    { key: "ok", text: `설계 목표 달성 — PM ≥ ${n(c.pm_min_deg, "°")} · `
      + `GM ≥ ${n(c.gm_good_db, " dB")} · ζ ≥ ${n(c.zeta_good, "")}` },
    { key: "warn", text: `합격선은 넘겼으나 목표 미달 — GM ${n(c.gm_min_db, "")}~`
      + `${n(c.gm_good_db, " dB")} 또는 ζ ${n(c.zeta_min, "")}~${n(c.zeta_good, "")}. `
      + "채택해도 되지만 여유가 얇아 형상이 바뀌면 먼저 무너지는 자리다" },
    { key: "fail", text: `합격선 미달 — PM < ${n(c.pm_min_deg, "°")} 또는 `
      + `GM < ${n(c.gm_min_db, " dB")} 또는 ζ < ${n(c.zeta_min, "")}, 혹은 게인 부호 뒤집힘. `
      + "처방 카드로 이어진다" },
    // 문장은 그대로 텍스트 노드로 들어간다 — 마크다운 강조는 별표가 화면에 그대로 뜬다
    { key: "na", text: "판정 불가 — 교차 없음(nan)이거나 트림 미수렴. 통과가 아니다" },
  ];
}

/** 범례 아래 「warn은 무엇이고 어떻게 줄이나」 문단 — 표현(report.fit_mode)에 따라 다르다.
 *
 * 종전 문단은 다항 시절 그대로였다: "스케줄 곡선이 목표선 아래로 내려온 자리 — breakpoint를 늘리거나
 * 적합 허용치를 조인다". 표 모드(기본)에는 조일 적합이 없고(엔진이 tighten_fit을 사유와 함께 건너뛴다),
 * 분할점의 값은 곡선이 아니라 그 마하의 튜닝값이다(같은 마하에 표본이 여럿이면 평균, 튜닝 실패로 뺀
 * 점은 이웃 보간). 그래서 앵커의 warn과 검증점의 warn이 다른 말이다. 표현 기록이 없는 결과(표현 선택
 * 이전)는 다항이었으므로 다항 문단이다. */
export function warnNoteText(fitMode) {
  const tail = " fail은 다르다 — 합격선 미달이라 그대로 확정하면 안 된다.";
  if (fitMode === "table") {
    return "warn은 자동 설계가 실패한 것이 아니다 — 합격선은 넘겼으나 목표선에 못 미친 자리다. "
      + "표 모드에서 절점의 값은 설계점 튜닝값 전부에 맞춘 최소제곱 구간 선형 값이다(절점은 설계점과 "
      + "따로 정한다 — 튜닝 실패로 적합에서 뺀 점은 쓰지 않는다). 그래서 설계점의 warn은 튜닝이 목표에 "
      + "못 갔거나(미달 원장 「튜닝 목표 미달」) 적합이 튜닝값을 다 못 따라간 탓이고, 검증점의 warn은 "
      + "절점 사이 선형 보간이 목표선 아래로 내려온 자리다. 보간 탓이면 그 구간 표에 절점을 더한다(처방 "
      + "카드 「절점 추가」). 적합 허용치 조이기는 표 모드에 없다 — 고도·연료로 갈리는 어긋남은 다축 표가 "
      + "있어야 풀린다." + tail;
  }
  return "warn은 자동 설계가 실패한 것이 아니다 — 튜닝은 목표를 맞췄는데 그 사이를 잇는 "
    + "스케줄 곡선이 목표선 아래로 내려온 자리다. 줄이려면 그 구간을 더 촘촘히 잇거나"
    + "(처방 카드가 이미 그것을 제안한다) 적합 허용치를 조인다." + tail;
}

// ── 종료 상태 ──────────────────────────────────────────────────────────

/** 종료 상태 6종 + running의 뜻과 **다음에 할 일**.
 *
 * 영어 토큰만 찍으면 화면이 상태를 말하되 뜻을 말하지 않는다 — 특히
 * nothing_verified는 "실패 0"으로 보여 통과로 오독되는 상태다. */
export const STATUS_TEXT = {
  converged: "수렴 — 판정한 자리가 모두 합격선을 넘었다. 게인을 확정하고 게인·시뮬·"
    + "마진·Autocode 순으로 확인할 것.",
  escalated: "남은 실패가 전부 상위 설계 변경 대상이다 — 게인·격자로는 풀리지 않는다. "
    + "작동기 대역폭·지연 예산 같은 상위 설계를 먼저 정하고 다시 돌릴 것.",
  budget_exhausted: "이터레이션 예산을 다 썼다 — 남은 처방이 있으나 반영하지 못했다. "
    + "이터 상한을 올려 새로 돌릴 것 (이 결과는 재개할 수 없다).",
  awaiting_approval: "처방 카드를 기다리는 중이다 — 승인한 처방만 반영해 그 자리에서 "
    + "이어 돈다. 승인 없이 두면 이 상태로 남는다.",
  nothing_verified: "실패가 없는 게 아니라 볼 것이 없었다 — 트림 전량 미수렴이거나 격자가 "
    + "비었다. 게인을 확정하면 안 된다.",
  cancelled: "사용자 취소로 스테이지 도중에 멈췄다 — 트림·선형모델·튜닝 결과는 남아 있어 "
    + "남은 스테이지부터 이어서 돌 수 있다.",
  running: "아직 도는 중이다 — 종료 상태가 아니므로 이 결과로 판단하지 말 것.",
};

export function statusText(status) {
  return STATUS_TEXT[status]
    ?? `알 수 없는 상태 (${status ?? "없음"}) — 엔진과 화면의 상태 어휘가 어긋났다.`;
}

/** 상태 칩 색. converged만 ok, 사람 손을 기다리는 것(승인 대기·실행 중)은 warn,
 * **통과가 아닌 채 끝난 것**(미검증·에스컬레이션·예산 소진)은 fail 쪽에 둔다.
 * 취소는 판정이 아니라 중단이라 na다 — 실패라 칠하면 사용자가 자기 취소를 결함으로
 * 읽는다 (재개 버튼은 그대로 뜬다). */
export function statusSeverity(status) {
  if (status === "converged") return "ok";
  if (status === "awaiting_approval" || status === "running") return "warn";
  if (status === "nothing_verified" || status === "escalated"
      || status === "budget_exhausted") return "fail";
  return "na";
}

/** 재개 가능 판정 — 서버 계약 그대로 (routes/design.py: awaiting_approval·cancelled만).
 *
 * 종전 화면은 처방 카드가 하나라도 있으면 "승인 반영 재개" 버튼을 그렸다.
 * budget_exhausted는 카드가 남은 채로 끝나는 상태라 버튼이 늘 떴고, 누르면 409다. */
export const RESUMABLE_STATUS = ["awaiting_approval", "cancelled"];

export function resumable(report) {
  return RESUMABLE_STATUS.includes(report?.status);
}

/** 재개 불가 사유 한 줄 — 재개 가능하면 null. 버튼 자리를 빈칸으로 두지 않는다. */
export function resumeBlockedText(report) {
  if (resumable(report)) return null;
  const s = report?.status;
  const why = {
    budget_exhausted: "이터 예산을 다 써 세션이 종료됐다 — 남은 처방이 있어도 재개할 수 "
      + "없다(서버가 409로 거절한다). 이터 상한을 올려 새로 돌릴 것.",
    escalated: "남은 실패가 전부 상위 설계 변경 대상이라 세션이 종료됐다 — 승인해 "
      + "반영할 처방이 없다. 작동기·지연 예산을 바꾼 뒤 새로 돌릴 것.",
    converged: "이미 수렴해 종료된 세션이다 — 재개할 것이 없다.",
    nothing_verified: "판정된 자리가 하나도 없어 종료됐다 — 재개가 아니라 격자·트림을 "
      + "고쳐 새로 돌려야 한다.",
    running: "아직 실행 중이다 — 끝난 뒤에 재개 여부가 정해진다.",
  };
  return why[s] ?? `재개할 수 없는 상태다 (${s ?? "없음"}) — 승인 대기·취소만 재개 가능.`;
}

/** 게인 확정 가능 판정 — **판정이 난 자리가 하나라도 있어야** 한다.
 *
 * failures가 0이라는 것만으로는 통과의 근거가 못 된다: 트림 전량 미수렴·빈 격자·
 * 엔벨로프 밖 격자는 실패 목록도 비어 있다(engine judged_count 머리말). 그 실행의
 * 게인을 확정할 수 있으면 **아무것도 검증하지 않은 게인이 정본이 된다.**
 *
 * 커버리지 공백(coverage_gaps)은 여기서 막지 않는다 — 검증점이 모자란 실행도
 * 앵커에서는 판정이 났고, 그것을 확정조차 못 하게 하는 것은 과하다. 대신 무엇을
 * 모르고 확정하는지를 adoptWarnText가 문장으로 낸다. 막는 것과 말하는 것은 다르다. */
export function adoptable(report) {
  return Number(report?.judged) > 0;
}

/** 확정 불가 사유 한 줄 — 확정 가능하면 null. */
export function adoptBlockedText(report) {
  if (adoptable(report)) return null;
  if (report?.judged == null) {
    return "이 결과에는 판정 수(judged)가 없다 — 그 필드가 생기기 전의 구형 결과다. "
      + "무엇을 검증했는지 확인할 수 없으므로 확정하지 않는다. 다시 돌릴 것.";
  }
  return "판정이 난 (점, 자리)가 0이다 — 이 실행은 아무것도 검증하지 않았다. "
    + "실패 0은 통과가 아니라 볼 것이 없었다는 뜻이므로 게인을 확정할 수 없다. "
    + "트림 미수렴·빈 격자·엔벨로프 밖 격자를 먼저 확인할 것.";
}

/** 확정해도 되지만 **무엇을 모르고 확정하는지** — 커버리지 공백이 없으면 null.
 *
 * adoptBlockedText가 "확정 못 한다"라면 이쪽은 "확정은 되는데 이만큼은 안 봤다"다.
 * 둘을 한 문장으로 뭉치면 막는 사유와 경고가 같은 무게로 읽혀, 정작 막아야 할
 * 미검증 실행이 흔한 경고에 섞인다. */
export function adoptWarnText(report) {
  const gaps = coverageLines(report).filter((l) => l.tone !== "hint");
  if (!gaps.length) return null;
  return "확정은 막지 않는다 — 다만 이 실행이 무엇을 안 봤는지는 알고 확정해야 한다. "
    + gaps.map((l) => l.text).join(" / ")
    + " 이대로 확정하면 그 미검증 구간이 검증된 적 없는 채로 시뮬·마진·Autocode의 "
    + "정본이 된다.";
}

/** 반출 표 재검증(gain_export.reverify) → 줄 [{key, tone, text}] — 채택 섹션용.
 *
 * resample_error가 "게인이 얼마나 다른가"라면 이쪽은 "그 표로 다시 판정하면 무엇이
 * 움직이나"다(05 §5.1). 악화(worse)가 있으면 확정 버튼 옆에서 경고해야 한다 —
 * 게인 오차가 허용치 안이어도 판정 마진이 그보다 얇으면 등급이 움직인다.
 * 움직인 자리 목록은 앞 몇 개만 문장에 싣는다(전량은 결과 JSON에 있다). */
export function reverifyLines(gainExport) {
  const rv = gainExport?.reverify;
  if (!rv) {
    // 재검증 도입 전 결과 — 없는 것을 0으로 위장하지 않고, 없다고 말한다
    return [{ key: "none", tone: "hint",
      text: "채택 표 재검증 없음 — 이 결과는 재검증 도입 전에 반출됐다." }];
  }
  if (rv.note) {
    return [{ key: "note", tone: Number(rv.n_judged) > 0 ? "hint" : "warn",
      text: `채택 표 재검증 — ${rv.note}` }];
  }
  const judged = Number(rv.n_judged) || 0;
  const moved = rv.changed ?? [];
  const dropped = Number(rv.dropped) || 0;
  // 판정이 있다가 없어진 자리 — 등급 이동보다 나쁠 수 있다 (fail이 na로 사라진 것일 수 있다)
  const droppedLine = dropped
    ? [{ key: "dropped", tone: "warn",
      text: `채택 표에서 판정 불가가 된 자리 ${dropped}곳 — 다항에서는 판정이 있었다`
        + " (교차 소멸 등). 등급 이동 목록에 나오지 않으므로 따로 확인할 것." }]
    : [];
  if (!moved.length) {
    return [...droppedLine, { key: "clean", tone: "hint",
      text: `채택 표(재양자화) 재검증 — 판정 ${judged}곳 전부 다항 검증과 같다.` }];
  }
  const toFail = moved.some((c) => c.to === "fail");
  const head = moved.slice(0, 3)
    .map((c) => `${c.case} ${c.loop} ${c.to === "fail" ? "→ fail" : `${c.from}→${c.to}`}`)
    .join(" · ");
  const more = moved.length > 3 ? ` 외 ${moved.length - 3}곳` : "";
  return [...droppedLine, { key: "moved", tone: toFail ? "fail" : "warn",
    text: `채택 표(재양자화)로 재판정하면 ${judged}곳 중 ${moved.length}곳의 등급이 움직인다`
      + ` (악화 ${Number(rv.worse) || 0} · 호전 ${Number(rv.better) || 0}): ${head}${more}.`
      + " 확정되는 것은 이 표다 — 다항 검증 결과를 그대로 물려받지 않는다." }];
}

/** 적합 품질(fits[*].quality) → 줄 [{key, tone, text}] — 04 §10 갭의 렌더 경로.
 *
 * 문턱을 켠 실행에서 넘은 자리만 경고로 세운다. 문턱이 꺼진 실행(전부 na)은 줄을
 * 세우지 않는다 — 지표는 결과 JSON에 있고, 판정하지 않은 것을 화면이 "품질 확인
 * 완료"처럼 말하면 안 된다. 켰는데 전부 통과면 그 사실을 hint 한 줄로 남긴다
 * (켠 실행과 안 켠 실행이 화면에서 같아 보이면 안 된다). */
export function fitQualityLines(fits) {
  const entries = Object.entries(fits ?? {})
    .map(([slot, rep]) => [slot, rep?.quality])
    .filter(([, q]) => q);
  const warns = entries.filter(([, q]) => q.status === "warn");
  if (warns.length) {
    return warns.map(([slot, q]) => ({
      key: `warn:${slot}`, tone: "warn",
      text: `적합 품질 — ${slot}: `
        + `기울기 점프 ${num(q.slope_jump_norm_max)} · 교차축 ${num(q.cross_axis_frac)}`
        + " — 문턱 초과. 급한 관절·교차축 잔차는 스케줄 전이 채터링 소지다.",
    }));
  }
  const judged = entries.filter(([, q]) => q.status === "ok").length;
  if (judged) {
    return [{ key: "ok", tone: "hint",
      text: `적합 품질 — 판정한 ${judged}자리 전부 문턱 내.` }];
  }
  return []; // 전부 na(문턱 끔·상수) — 판정하지 않은 것을 말하지 않는다
}

/** 비율 → 백분율 표기 (유효 2자리). */
const pctText = (x) => `${num(100 * x, 2)}%`;

/** 적합 보고(fits) → 자리별 사실 {rows, summary} — 스케줄 축 밖 변동(axes_excluded)·교차축 잔차
 *  (quality.cross_axis_frac)·톱니(zigzag). 적합 보고가 없으면 null.
 *
 * fitQualityLines는 **문턱을 켠 실행의 판정**이라, 문턱이 꺼진 기본 실행에서는 아무 줄도 없다. 그런데
 * 이 수치들은 문턱과 무관하게 매 실행 계산되어 결과에 실려 있었고 화면 어디에도 없었다: 표는 마하 1축
 * (sched_axes)이라 고도·연료로 변하는 게인은 버려지지 않고 마하 분할점 하나에 평균되거나(교차축 잔차)
 * 마하 축 위에 번갈아 놓여 값이 오르내린다(톱니) — 그 대가를 사실로 적는다. 판정은 하지 않는다(판정은
 * VERIFY가 그 표로 했고, 문턱은 fitQualityLines 몫이다). 0은 생략한다 — 실제로 0인 것을 적으면
 * 행마다 "교차축 0% · 톱니 0회"가 붙어 정작 0이 아닌 자리가 묻힌다. */
export function fitFactsModel(fits, knots = null) {
  const entries = Object.entries(fits ?? {}).filter(([, rep]) => rep && typeof rep === "object");
  if (!entries.length) return null;
  entries.sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
  const rows = entries.map(([slot, rep]) => {
    const kind = rep.kind ?? null;
    const excluded = Array.isArray(rep.axes_excluded) ? rep.axes_excluded.map(String) : [];
    const cross = numeric(rep.quality?.cross_axis_frac);
    const zigzag = numeric(rep.zigzag);
    const nBreakpoints = numeric(rep.n_breakpoints);
    // 절점 집합(knotModel 행) — 공통/분리 집합·뺀 절점(끝 바깥/안쪽). 없으면(옛 결과·다항) 적지 않는다
    const kr = kind === "table" ? (knots?.rows ?? []).find((r) => r.slot === slot) ?? null : null;
    const unsup = Array.isArray(rep.unsupported_knots) ? rep.unsupported_knots.length
      : kr ? kr.unsupported.length : 0;
    const shape = kind === "table" ? `표 ${nBreakpoints ?? "?"}절점(${rep.axis ?? "?"} 축)`
      : kind === "poly" ? `다항(${rep.axis ?? "?"} 축`
        + `${Array.isArray(rep.segments) ? ` · 구간 ${rep.segments.length}` : ""})`
        : kind === "constant" ? `상수 ${num(rep.value)}` : `표현 ${kind ?? "?"}`;
    const parts = [shape];
    if (kr?.common != null) parts.push(kr.sharedText);
    if (kr && (kr.edge.length || kr.dropped.length)) {
      if (kr.edge.length) parts.push(`범위 밖 절점 ${kr.edge.length}`);
      if (kr.dropped.length) parts.push(`안쪽에서 뺀 절점 ${kr.dropped.length}`);
    } else if (unsup) {
      // 절점 기록이 없으면 끝 바깥인지 안쪽인지 모른다 — 「범위 밖」이라 단정하지 않는다
      parts.push(`뺀 절점 ${unsup}`);
    }
    if (excluded.length) {
      // 상수로 접힌 자리는 그 변동이 잔차에 남는다(fit.fit_slot) — 적합에서 "뺐다"가 아니라 "접었다"다
      parts.push(`스케줄 축 밖 변동 ${excluded.join("·")}`
        + (kind === "constant" ? ` — 상수로 접었다(잔차 ${num(rep.max_residual)})` : ""));
    }
    if (cross != null && cross > 0) parts.push(`교차축 잔차 ${pctText(cross)}`);
    if (zigzag != null && zigzag > 0) {
      parts.push(`톱니 ${zigzag}회${nBreakpoints ? `/절점 ${nBreakpoints}` : ""}`);
    }
    return { slot, kind, excluded, cross, zigzag, nBreakpoints, common: kr?.common ?? null, unsupported: unsup,
      text: `${slot} — ${parts.join(" · ")}` };
  });
  const withExcluded = rows.filter((r) => r.excluded.length);
  const axes = [...new Set(withExcluded.flatMap((r) => r.excluded))];
  const worst = (key) => rows.reduce((w, r) => (r[key] != null && r[key] > 0
    && (w == null || r[key] > w[key]) ? r : w), null);
  const wc = worst("cross");
  const wz = worst("zigzag");
  const head = [];
  if (withExcluded.length) {
    head.push(`스케줄 축 밖 변동 ${withExcluded.length}/${rows.length}자리(${axes.join("·")})`);
  }
  if (wc) head.push(`교차축 잔차 최대 ${pctText(wc.cross)} (${wc.slot})`);
  if (wz) {
    head.push(`톱니 최대 ${wz.zigzag}회${wz.nBreakpoints ? `/절점 ${wz.nBreakpoints}` : ""} (${wz.slot})`);
  }
  return { rows, summary: head.length ? `적합 보고 — ${head.join(" · ")}` : null };
}

// 적합에서 뺀 근거 — 엔진 orchestrator._fit_exclusions의 두 겹
const EXCLUDE_BASIS_TEXT = {
  own: "그 자리 튜닝 실패",
  rate_loop: "같은 축 레이트 루프가 실패한 위에서 튜닝",
};

/** 값 목록 → "a 3 · b 1" (나온 순서, 수 붙여). */
function tallyText(values) {
  const m = new Map();
  for (const v of values) m.set(v, (m.get(v) ?? 0) + 1);
  return [...m.entries()].map(([k, n]) => `${k} ${n}`).join(" · ");
}

/** 적합에서 뺀 튜닝 표본(report.excluded_samples)·제외 보류(report.exclusion_withheld) → 화면 모델 —
 *  {total, points, slots:[{slot, n, items, text}], withheld:[{slot, n, keptWouldBe, text}], excludedText,
 *  summary}. excludedText는 뺀 표본 한 줄(없으면 null), summary는 거기에 보류 한 줄을 이은 것. 둘 다 없으면 null.
 *
 * 엔진의 coverage_gaps 문장은 **몇 개인가**만 말한다. 어느 자리의 어느 점을 왜 뺐는지(사유 코드·근거·
 * 뺀 값)는 결과 JSON에만 있었다 — 표의 어느 분할점이 튜닝값이 아니라 이웃 보간인지 화면이 말할 수 없었다.
 * 보류는 반대 방향의 사실이다: 빼면 표가 안 서서 못 뺐으니 **그 표는 실패 표본(자리값 — 0 댐퍼 등)을
 * 담고 있다**. 보류 상세(남을 뻔한 수)는 report가 아니라 fits[자리].exclusion_withheld에 있다 —
 * 없으면(옛 결과·잘린 본문) 수를 지어내지 않는다. */
export function excludedSamplesModel(body) {
  const r = body?.report ?? {};
  const rows = Array.isArray(r.excluded_samples) ? r.excluded_samples.filter(Boolean) : [];
  const held = Array.isArray(r.exclusion_withheld) ? r.exclusion_withheld : [];
  if (!rows.length && !held.length) return null;
  const bySlot = new Map();
  for (const x of rows) {
    const slot = x.slot ?? "?";
    if (!bySlot.has(slot)) bySlot.set(slot, []);
    bySlot.get(slot).push(x);
  }
  const slots = [...bySlot.entries()].map(([slot, items]) => ({
    slot,
    n: items.length,
    items: items.map((x) => ({
      point: x.point ?? "?", value: x.value ?? null, loop: x.loop ?? null,
      reason: x.reason ?? null, basis: x.basis ?? null,
      basisText: EXCLUDE_BASIS_TEXT[x.basis] ?? (x.basis ? String(x.basis) : "근거 미상"),
    })),
    text: `${items.length}점 — 사유 ${tallyText(items.map((x) => x.reason ?? "기록 없음"))}`
      + ` · 근거 ${tallyText(items.map((x) => EXCLUDE_BASIS_TEXT[x.basis] ?? x.basis ?? "미상"))}`,
  }));
  const withheld = held.map((slot) => {
    const h = body?.fits?.[slot]?.exclusion_withheld;
    const n = Array.isArray(h?.samples) ? h.samples.length : null;
    const kept = numeric(h?.kept_would_be);
    return {
      slot, n, keptWouldBe: kept,
      text: `${slot} — `
        + (n != null && kept != null
          ? `튜닝 실패 표본 ${n}개를 빼면 ${kept}개만 남아 제외를 보류했다`
          : "튜닝 실패 표본 제외를 보류했다 (상세는 결과 JSON fits)")
        + " — 이 자리의 표는 실패 표본을 담고 있다",
    };
  });
  const points = new Set(rows.map((x) => x.point)).size;
  const excludedText = rows.length
    ? `튜닝 실패 표본 ${rows.length}개를 적합에서 뺐다 (점 ${points}곳 · 자리 ${slots.length}개`
      + " — 그 점의 스케줄 값은 이웃 보간)"
    : null;
  const heldText = withheld.length ? `제외 보류 ${withheld.length}자리 (빼면 표가 안 서서 못 뺐다)` : null;
  return { total: rows.length, points, slots, withheld, excludedText,
    summary: [excludedText, heldText].filter(Boolean).join(" · ") };
}

// 작동기 값의 출처 — 엔진 DesignSession.actuator_used의 source 어휘
const ACTUATOR_SOURCE_TEXT = {
  profile: "기체 문서",
  config: "설정 — 작동기 가정 연구",
  default: "엔진 폴백 — 기체 값이 아니다",
};

/** 튜닝·검증이 본 작동기 한 줄 {tone, value, text} — report.actuator({wn, zeta, source, delay_s, pade_order}).
 *
 * 작동기는 마진 조성의 일부다(병목이 되는 상위 설계값). 이제 config의 actuator_wn·zeta는 비어(null)
 * 있고 값은 기체 문서에서 오므로, config만 보면 **무엇으로 설계했는지가 사라진다** — 정본은
 * report.actuator다. 출처가 폴백(기체 값 아님)이면 경고 톤이다.
 * 그 필드가 없는 옛 결과는 config 수치가 곧 쓴 값이다(그때는 config 30·0.7이 늘 이겼다 — 기체 작동기를
 * 보지 않았다). 그 사실을 그대로 적는다. 둘 다 없으면 null. */
export function actuatorLine(body) {
  const a = body?.report?.actuator;
  const c = body?.config ?? {};
  const delayOf = (d, p) => {
    const bits = [];
    if (numeric(d) != null) bits.push(`지연 ${num(Math.round(d * 1e6) / 1e3)} ms`);
    if (p != null) bits.push(`Padé ${p}차`);
    return bits.length ? ` · ${bits.join(" · ")}` : "";
  };
  // value는 머리말 없는 값 — 표의 「작동기」 칸(결과 브리핑)이 쓴다. text는 한 줄로 서는 문장
  const line = (tone, value) => ({ tone, value, text: `작동기 ${value}` });
  if (a && typeof a === "object") {
    const src = a.source ?? {};
    const label = (k) => ACTUATOR_SOURCE_TEXT[src[k]] ?? (src[k] ? String(src[k]) : "출처 기록 없음");
    const head = src.wn === src.zeta
      ? `ωn ${num(a.wn)} rad/s · ζ ${num(a.zeta)} (${label("wn")})`
      : `ωn ${num(a.wn)} rad/s (${label("wn")}) · ζ ${num(a.zeta)} (${label("zeta")})`;
    const known = (k) => src[k] === "profile" || src[k] === "config";
    return line(known("wn") && known("zeta") ? "hint" : "warn", head + delayOf(a.delay_s, a.pade_order));
  }
  if (numeric(c.actuator_wn) != null) {
    return line("warn", `ωn ${num(c.actuator_wn)} rad/s · ζ ${num(c.actuator_zeta)}`
      + " (설정 — 작동기 출처 기록 이전 결과: 기체 문서의 작동기가 아니라 설정값으로 튜닝·검증했다)"
      + delayOf(c.delay_s, c.pade_order));
  }
  return null;
}

const FIT_MODE_LABEL = { table: "표(선형 보간)", poly: "다항" };

/** 게인 표현 이름 — report.fit_mode(엔진 AutoDesignConfig.fit_mode). 모르는 값은 **코드 그대로**(종전
 *  상태 줄은 table이 아니면 전부 "다항"이라 적었다 — 엔진에 표현이 늘면 화면이 조용히 틀린다).
 *  없으면 null — 표현 선택이 생기기 전 결과다. 없는 것을 지어내지 않고, 부르는 쪽이 그 사실을 말한다. */
export function fitModeLabel(mode) {
  if (mode == null || mode === "") return null;
  return FIT_MODE_LABEL[mode] ?? String(mode);
}

// 설계점·검증점(이관 3단계). 옛 결과의 역할 이름(앵커·bp)은 설계점 자리에 그대로 둔다 — 옛 결과를 열어도
// 「앵커 31 · 검증점 14」로 위치가 읽힌다(설계점류가 먼저, 점 사이가 뒤)
const ROLE_SHORT = [["design", "설계점"], ["anchor", "앵커"], ["breakpoint", "bp"], ["validation", "검증점"],
  ["unknown", "역할 미상"]];

/** report.failures_by_role → "설계점 31 · 검증점 14"(옛 결과는 "앵커 31 · 검증점 14") — 실패가 없으면 null.
 *
 * 실패가 설계점인지 점 사이인지 — 설계점은 자기 튜닝값 근처에서 검증받아 통과가
 * "튜닝 성립"에 가깝고, 스케줄 성립을 말하는 것은 검증점이다(엔진 failures_by_role 머리말).
 * 상태 줄·신호 보고·결과 브리핑이 **이 한 함수로** 같은 말을 한다. 화면이 모르는 역할도 코드 그대로
 * 센다 — 삼키면 "실패 N"과 위치의 합이 어긋나는데 화면은 그걸 말하지 않는다. */
export function failureRoleText(byRole) {
  const known = new Set(ROLE_SHORT.map(([k]) => k));
  const parts = ROLE_SHORT
    .filter(([k]) => Number(byRole?.[k]) > 0)
    .map(([k, label]) => `${label} ${Number(byRole[k])}`);
  for (const [k, v] of Object.entries(byRole ?? {})) {
    if (!known.has(k) && Number(v) > 0) parts.push(`${k} ${Number(v)}`);
  }
  return parts.length ? parts.join(" · ") : null;
}

/** report → 상태 줄 조각 [문자열] — 계산해 놓고 안 내던 수치를 담되 0은 생략한다.
 *
 * judged와 failures만은 0이어도 낸다: "실패 0 / 판정 0"이 곧 nothing_verified의
 * 얼굴이라, 하나를 감추면 남은 하나가 통과처럼 읽힌다. */
export function reportLine(report, nPointsFallback) {
  const r = report ?? {};
  const pts = r.points ?? {};
  const parts = [
    `스테이지 ${r.stage ?? "?"}`,
    `이터레이션 ${r.iterations ?? 0}`,
    `점 ${r.n_points ?? nPointsFallback ?? "?"} (${pointCountText(pts)})`,
    `판정 ${Number(r.judged) || 0}`,
    `실패 ${Number(r.failures) || 0}`,
  ];
  // 어느 표현으로 검증한 결과인가 — 표는 반출 표가 검증받은 그 표이고, 다항은
  // 재양자화 근사가 끼어 채택 시 재검증을 받는다 (05 §5.1). 수치가 아니라
  // 표현이라 아래 optional 카운터 목록에 못 섞는다
  const mode = fitModeLabel(r.fit_mode);
  if (mode) parts.push(`표현 ${mode}`);
  const where = failureRoleText(r.failures_by_role);
  if (where) parts.push(`실패 위치 ${where}`);
  // 튜닝이 성립하지 않아 적합에서 뺀 표본 — 그 점의 스케줄 값은 튜닝값이 아니라 이웃 보간이다.
  // 보류(표본이 모자라 못 뺀 자리)는 따로 센다 — 그 자리의 표는 실패 표본(자리값)을 담고 있다
  const nExcluded = Array.isArray(r.excluded_samples) ? r.excluded_samples.length : 0;
  if (nExcluded) parts.push(`튜닝 실패 표본 제외 ${nExcluded}`);
  const nHeld = Array.isArray(r.exclusion_withheld) ? r.exclusion_withheld.length : 0;
  if (nHeld) parts.push(`제외 보류 ${nHeld}자리`);
  const optional = [
    ["outside_envelope", "채택 제외"],
    ["tuned", "튜닝"],
    ["escalations", "에스컬레이션"],
    ["ineffective_actions", "무효 처방"],
    ["sealed", "봉인"],
    ["fit_tighten", "적합 조이기"],
    ["fit_quality_warns", "적합 품질 경고"],
    // 원장 행 수 — 처방 카드 수와 다른 수다. 카드 없는 미달이 대부분이라
    // 이 수가 카드 수보다 훨씬 클 수 있고, 그 격차가 곧 "안 보이던 것"의 규모다
    ["ledger_size", "미달 원장"],
  ];
  for (const [key, label] of optional) {
    const v = Number(r[key]) || 0;
    if (v) parts.push(`${label} ${v}`);
  }
  const skipped = r.skipped ?? [];
  if (skipped.length) {
    // 이름을 다 늘어놓으면 줄이 넘친다 — 앞 셋만 보이고 나머지는 수로 말한다
    const head = skipped.slice(0, 3).join(", ");
    parts.push(`튜닝 건너뜀 ${skipped.length} (${head}`
      + (skipped.length > 3 ? ` 외 ${skipped.length - 3}` : "") + ")");
  }
  if (r.criteria_fingerprint) {
    parts.push(`기준 지문 ${String(r.criteria_fingerprint).slice(0, 8)}`);
  }
  return parts;
}

/** 본문 최상위 trim_reuse(서버 refs.design_reuse_echo) → {text, tip} — 「트림 재사용 k · 새로 n」.
 *
 * 트림 탭·마진 맵과 **같은 함수**(lib/opspace.js reuseLine·reuseTip)를 쓴다 — 서버가 형제 라우트와 같은 칸 이름으로
 * 싣기 때문이고, 같은 사실을 화면마다 다르게 말하지 않기 위해서다.
 *
 * 블록이 없는 옛 결과, 그리고 **재사용도 계산도 0인 실행**(트림 스테이지 전에 멈춘 세션)은 null이다 — retryLine이
 * 다시 푼 점이 없을 때 조용한 것과 같은 규약: 말할 것이 없으면 줄을 내지 않는다. 저장소가 꺼진 서버(policy "off")는
 * 새로 푼 수가 있으면 낸다 — 「하나도 재사용하지 않았다」도 사실이고, 툴팁이 규칙을 말한다. */
export function designReuseLine(body) {
  const r = body?.trim_reuse;
  const text = reuseLine(r);
  if (!text || (!r.reused && !r.computed)) return null;
  return { text, tip: reuseTip(r) };
}

// ── 사유 코드 ──────────────────────────────────────────────────────────

/** 튜닝 포기 사유 코드 → 한국어 [폴백].
 *
 * 정본은 서버 /design/defaults의 reason_text(← 엔진 tune.REASON_TEXT)다 —
 * 여기 문구는 그 응답에 코드가 없을 때만 쓴다. 그래도 **사본은 정본과 같아야** 한다 — 엔진이
 * sign_mismatch·capped 문구를 고치고 loop_unstable을 보탠 뒤 이 사본만 옛 말을 했다(기본값 조회가
 * 실패한 화면에서 드러난다). autodesign.test.js가 tune.py 원문과 대조한다. */
export const REASON_TEXT = {
  ok: "설계 목표 달성",
  zero_design: "설계 게인이 0이라 방향 정보가 없다 — 이 자리를 쓸 것이면 설계값을 먼저 정한다",
  seed_required: "설계 게인이 0이라 부호를 몰라 튜닝하지 않았다 — 초기 게인 빠른 탐색으로 부호·크기를"
    + " 채운 뒤 다시 돌린다 (부호를 짐작하면 틀린 부호도 통과해 보인다)",
  sign_mismatch: "게인 부호가 플랜트와 반대다(양의 되먹임) — 자세 루프는 뒤집어야만 위상여유가 나고,"
    + " 레이트 댐퍼는 반대 부호가 감쇠를 더 준다. 설계 게인 부호를 확인한다",
  target_unreached: "게인을 아무리 키워도 목표 지표가 안 나온다 — 플랜트 한계다."
    + " 목표를 낮추거나 이 조건을 설계 범위에서 뺀다",
  capped: "댐퍼 안정 가드(작동기·지연 포함 폐루프 안정, 느린 나선은 비행성 기준 배가시간) 또는"
    + " 레이트 루프 마진 가드(AS94900 끊은 루프 여유가 설계 목표 PM/GM 아래로 내려가지 않게)가"
    + " 목표 전에 묶는다 — 작동기·지연이나 마진 가드가 묶었으면 작동기 대역폭·지연 예산을 늘리거나"
    + " 목표를 낮추고, 나선 기준이 묶었으면 목표를 낮춘다 (어느 쪽인지는 그 점의 note·cap_bound)",
  no_stable_gain: "어떤 게인으로도 이 댐퍼 루프가 안정하지 않아 0으로 두었다 —"
    + " 플랜트·루프 구조를 검토한다",
  bandwidth_collapse: "마진은 넘겼으나 교차 주파수가 하한 아래다 — 성능이 무너졌다."
    + " 지연·작동기 예산을 늘리거나 대역폭 하한을 낮춘다",
  margin_floor: "대역폭을 바닥까지 버려도 PM/GM 목표에 못 미친다 — 지연·작동기 예산이 병목이다",
  degenerate: "이 자리의 기저 루프 응답이 무의미하다 — 입출력·플랜트를 확인한다",
  na_no_crossover: "교차가 없어 이 루프의 마진을 잴 수 없다 — 통과가 아니라 판정 불가다."
    + " 루프 조성·게인 부호를 확인한다",
  rescued: "백오프 해가 대역폭 하한 아래여서 마무리로 되찾았다 (통과)",
  loop_unstable: "자세 루프까지 닫은 축 전체 폐루프(작동기·지연 포함)가 불안정하다(발산, 또는 작동기"
    + " 대역 공진의 감쇠가 댐퍼 가드와 같은 하한 미만) — 개별 루프의 댐퍼 가드·보드 마진은"
    + " 통과해도 합친 루프가 서지 않는다. 지연·작동기 예산을 늘리거나 게인(자세 교차·댐퍼)을 줄인다",
};

/** 사유 코드 → "코드 — 뜻". 서버 맵이 우선, 없으면 폴백, 그것도 없으면 코드 그대로.
 * 모르는 코드를 삼키면 새 사유가 생겼을 때 화면이 조용해진다. */
export function reasonText(code, reasonMap) {
  if (!code) return null;
  const t = reasonMap?.[code] ?? REASON_TEXT[code];
  return t ? `${code} — ${t}` : String(code);
}

/** 처방 카드 그룹 — {approvable, escalations}. supersede는 양쪽 다 제외
 * (같은 점 상위 승격에 흡수됨 — 엔진 promote 래칫과 정합). */
export function actionCards(result) {
  const approvable = [];
  const escalations = [];
  for (const a of result?.proposed_actions ?? []) {
    if (a.superseded_by) continue;
    (a.action?.type === "escalate" ? escalations : approvable).push(a);
  }
  return { approvable, escalations };
}

/** 게인 채택 — gains 탭 스토어 계약 {tables, scheduleOff} + **상수 자리**.
 *
 * 적합이 평탄하다고 판정한 자리는 테이블이 아니라 상수로 나온다(gain_export.constants).
 * 그 자리를 빠뜨리면 시뮬·Autocode가 새 스케줄과 옛 설계 상수를 섞어 돌게 되어,
 * **이 실행이 검증한 마진이 채택한 형상에 해당하지 않는다.** 전 자리가 상수로 접히면
 * tables가 비어 scheduleOff가 서지만 그때도 constants는 반영되어야 한다.
 */
export function adoptStorePayload(result) {
  const tables = result?.gain_export?.tables_resampled ?? {};
  const off = Object.keys(tables).length === 0;
  return {
    tables: off ? null : tables,
    scheduleOff: off,
    constants: { ...(result?.gain_export?.constants ?? {}) },
  };
}

// ── 처방 카드 근거 ─────────────────────────────────────────────────────

/** 지표 키 → 표시 이름·단위 — 엔진 classify._LABEL과 같은 대응. */
const METRIC = {
  pm_deg: ["PM", "°"],
  gm_db: ["GM", " dB"],
  zeta: ["ζ", ""],
  zeta_sp: ["ζ_sp", ""],
  zeta_dr: ["ζ_dr", ""],
  roll_lambda: ["λ", " rad/s"],
};

const TUNED_STATUS_TEXT = {
  ok: "가능 (자유 게인으로 이 자리를 맞출 수 있다)",
  infeasible: "불가 (자유 게인으로도 설계 목표에 못 간다)",
  na: "해당 없음",
};

/** evidence.shortfall → 지표별 한 줄 [{key, kind, text}] — **요구선·달성·부족을 함께**.
 *
 * 종전 화면은 "현재 PM 38.2°"만 말했다. 요구선(45°)도 부족(6.8°)도 없으면 그 수치가
 * 합격인지 미달인지, 얼마나 모자란지를 화면만 보고는 알 수 없다 — 처방 카드에서
 * 가장 먼저 알아야 할 것이 그 둘이다.
 *
 * deficit는 양수가 부족·음수가 여유·null이 판정 불가(교차 없음)다. 정렬은 요구선
 * 대비 비율의 내림차순이고 판정 불가를 맨 앞에 둔다 — 엔진 severity와 같은 규약
 * ("얼마나 나쁜지 모른다"가 목록 맨 앞). */
export function shortfallLines(shortfall) {
  const rows = [];
  for (const [key, rec] of Object.entries(shortfall ?? {})) {
    if (!rec) continue;
    const [label, unit] = METRIC[key] ?? [key, ""];
    const req = `요구 ${num(rec.required)}${unit}`;
    if (rec.deficit == null) {
      rows.push({ key, kind: "na", rank: Infinity,
        text: `${label} ${req} · 달성 판정 불가 (교차 없음 — 통과가 아니다)` });
      continue;
    }
    // 비유한값은 **문자열**로 온다 ("inf" / "-inf" — 엔진이 nan(=null)과 구별하려고
    // 일부러 그렇게 낸다, serialize.py). 숫자로 다루면 `"inf" > 0`이 false라
    // **GM −∞(최악)가 "여유"로 초록칠**되고, Math.abs("−inf")가 NaN이 되어 부족량과
    // 정렬 키가 통째로 망가진다. 부호만 뽑아 쓰고 크기는 ∞로 적는다
    const d = numeric(rec.deficit);
    const short = d == null ? rec.deficit === "inf" : d > 0;
    const frac = numeric(rec.deficit_frac);
    const pct = frac == null ? "" : ` (요구선 대비 ${num(100 * Math.abs(frac), 3)}%)`;
    const size = d == null ? "∞" : num(Math.abs(d));
    rows.push({
      key,
      kind: short ? "short" : "spare",
      // 무한 부족은 유한한 어떤 부족보다 심각하고, 무한 여유는 어떤 여유보다 낫다
      rank: frac ?? (short ? Infinity : -Infinity),
      text: `${label} ${req} · 달성 ${num(rec.achieved)}${unit} · `
        + `${short ? "부족" : "여유"} ${size}${unit}${pct}`,
    });
  }
  rows.sort((a, b) => b.rank - a.rank);
  return rows.map(({ key, kind, text }) => ({ key, kind, text }));
}

/** 달성 지표 dict → 한 줄 ("PM 46.1° · GM 8.2 dB"). 볼 게 없으면 null.
 *
 * **아는 지표만** 적는다. 엔진의 achieved 레코드는 지표만 담은 dict가 아니라
 * 조성 메타를 함께 싣는다 — 자세 자리는 orientation·wc0·wc_fallback·target_pm_deg…,
 * 레이트 자리는 kind·capped·reached·bracket_growth·participation… 전부 훑으면
 * 한 줄이 열두 조각짜리 덤프가 되고, 사유 코드는 바로 위에서 이미 한국어로 푼 것을
 * 원문으로 한 번 더 찍는다. */
function achievedText(ach) {
  const parts = [];
  for (const [key, v] of Object.entries(ach ?? {})) {
    if (!(key in METRIC)) continue;
    const [label, unit] = METRIC[key];
    parts.push(`${label} ${num(v)}${unit}`);
  }
  return parts.length ? parts.join(" · ") : null;
}

/** evidence.tuned → 줄 목록 — 자유 게인으로 그 자리를 맞출 수 있었나와 그 사유.
 *
 * 이 판정이 structural_limit(에스컬레이션)의 근거다. 자리 단위 status를 내고,
 * 점 단위(point_status)가 다를 때만 참고로 덧붙인다 — 둘을 뭉치면 실행 가능한
 * 처방이 적용 버튼 없는 에스컬레이션처럼 읽힌다. */
export function tunedLines(tuned, reasonMap) {
  if (!tuned) return [];
  const out = [];
  const head = [`자유 게인 튜닝 ${TUNED_STATUS_TEXT[tuned.status] ?? tuned.status ?? "?"}`];
  const r = reasonText(tuned.reason, reasonMap);
  if (r) head.push(`사유 ${r}`);
  out.push(head.join(" · "));
  const detail = [];
  if (tuned.judged) detail.push(`그 자리 판정 ${tuned.judged}`);
  if (tuned.target != null) detail.push(`목표 ${num(tuned.target)}`);
  const ach = achievedText(tuned.achieved);
  if (ach) detail.push(`달성 ${ach}`);
  if (tuned.point_status && tuned.point_status !== tuned.status) {
    detail.push(`점 단위 ${tuned.point_status} (참고 — 판정에는 안 쓴다)`);
  }
  if (detail.length) out.push(detail.join(" · "));
  for (const note of tuned.notes ?? []) out.push(`튜너 메모: ${note}`);
  return out;
}

/** 처방 전후 판정 스냅샷 한 줄 — 채점 전이면 그 사실을 적는다.
 *
 * **반영했는데 안 바뀐 처방**을 드러내는 것이 목적이다. "applied"만 찍고 결과를
 * 안 보면 무효 처방이 이터 예산을 태우는 것을 아무도 모른다 (엔진 _score_applied_actions). */
export function effectText(effect) {
  if (!effect) return null;
  const snap = (s) => (s == null ? "없음"
    : `${s.status ?? "?"}${s.severity == null ? "" : ` (심각도 ${num(s.severity)})`}`);
  if (!("changed" in effect)) {
    return `반영됨 — 효과는 다음 검증에서 잰다 (반영 전 ${snap(effect.before)})`;
  }
  if (effect.changed) {
    return `반영 효과 ${snap(effect.before)} → ${snap(effect.after)}`;
  }
  return `반영했으나 판정이 그대로다 ${snap(effect.before)} → ${snap(effect.after)}`
    + " — 이 처방은 이 자리에서 듣지 않았다";
}

/** 완화 프로브 한 줄 — 무엇을 얼마에서 얼마로 바꿨더니 통과했는지까지 낸다.
 *
 * label과 통과 여부만 그리면 "작동기 대역폭 ×3"이 30에서 90인지 10에서 30인지
 * 알 수 없어, 예산을 얼마로 잡아야 하는지가 화면에서 안 나온다. */
export function reliefLines(relief, reasonMap) {
  return (relief ?? []).map((p) => {
    // from이 없는 축은 "지금 그것이 없다"는 뜻이다 (필터 추가 프로브) — "—"로
    // 그리면 "값을 모른다"로 읽힌다
    const from = p.from == null && p.to != null ? "없음" : num(p.from);
    const move = p.from == null && p.to == null
      ? "" : ` (${p.change ?? "?"} ${from} → ${num(p.to)})`;
    const why = p.resolves ? null : reasonText(p.reason, reasonMap);
    // 임계값이 이 카드의 실질이다 — "×3이면 통과"가 아니라 "≥ 47 rad/s면 통과"가
    // 사용자가 바로 쓸 수 있는 답이고, 01 §7의 "작동기 대역폭 요구 사양"이
    // 요구하던 수치다. 통과한 축에만 붙는다 (미달 축에 숫자를 지어내면 안 된다)
    const th = p.threshold?.text;
    return {
      resolves: Boolean(p.resolves),
      threshold: th ?? null,
      text: `${p.label ?? p.change ?? "?"}${move} → ${p.resolves ? "통과" : "여전히 미달"}`
        + (th ? ` · ${th}` : "") + (why ? ` · 사유 ${why}` : ""),
    };
  });
}

/** 처방 카드 하나 → 표시용 줄 묶음. DOM은 뷰가 만든다.
 *
 * {head} 인라인 수치 · {shortfall} 요구 대비 부족 · {tuned} 자유 게인 결과 ·
 * {relief} 완화 프로브 · {effect} 반영 효과 · {notes} 강조 문장 · {flags} 봉인·건너뜀.
 * 카드에 실려 오는데 화면에 안 나오던 것들이 여기서 전부 줄이 된다. */
export function evidenceLines(a, reasonMap) {
  const ev = a?.evidence ?? {};
  const cur = ev.current ?? {};
  const head = [];
  // 부호 뒤집힘은 **가장 먼저** 말해야 한다 — 마진 수치는 방향 보정 후 값이라
  // PM 116°처럼 건강해 보이고, 그러면 왜 fail인지 화면만 봐서는 알 수 없다
  if (ev.sign_flip) {
    const slots = (ev.sign_flip.slots ?? []).join(", ");
    head.push(`부호 반대: ${slots} (설계와 반대 방향 — 양의 되먹임)`);
  }
  // 계획한 검증점의 실패(이관 4단계) — 어느 계획 종류(경계·clip·절점·추가…)에서 났는지. 요구영역 안 실패는 실제 실패다
  if (ev.plan_point?.kind) {
    head.push(`검증점 종류: ${ev.plan_point.label ?? VALIDATION_KIND_LABEL[ev.plan_point.kind] ?? ev.plan_point.kind}`
      + (ev.plan_point.origin ? ` (${ev.plan_point.origin})` : ""));
  }
  if (cur.pm_deg != null) head.push(`현재 PM ${num(cur.pm_deg)}° / GM ${num(cur.gm_db)} dB`);
  if (cur.zeta != null) head.push(`현재 ζ ${num(cur.zeta)}`);
  if (cur.roll_lambda != null) head.push(`현재 λ ${num(cur.roll_lambda)} rad/s`);
  if (a?.severity != null) {
    head.push(`심각도 ${num(a.severity)} (요구선 대비 부족 비율 — 클수록 심각)`);
  }
  if (ev.interp_gap?.max != null) {
    head.push(`보간 괴리 ${num(100 * ev.interp_gap.max, 3)}% `
      + `(허용 ${num(100 * (ev.interp_gap.tol ?? 0), 2)}%)`);
  }
  if (ev.plant?.d_total != null) {
    head.push(`플랜트 거리 ${num(ev.plant.d_total)} (허용 ${num(ev.plant.tol)})`);
  }
  if (ev.bottleneck) {
    head.push(`ωc/작동기 ${num(ev.bottleneck.wc_over_actuator)} · 지연 위상 `
      + `${num(ev.bottleneck.delay_phase_deg_at_wc)}°`);
  }

  const notes = [];
  // 에스컬레이션은 "무엇을 바꾸면 통과하는가"가 결론이다 — 흐린 회색 나열에 묻히면
  // 사용자는 이 카드를 보고도 다음 행동을 정할 수 없다
  if (ev.bottleneck?.note) notes.push(ev.bottleneck.note);
  // 분류기 자신의 설명 — 왜 이 처방인지를 분류기가 이미 적어 놓았는데 버려져 있었다
  if (a?.action?.note) notes.push(a.action.note);

  // 엔진이 반영하며 남긴 참고(편입 불필요·편입은 됐으나 절점 못 더함) — 건너뜀이 아니다(한 일이 있는 카드)
  for (const n of Array.isArray(a?.notes) ? a.notes : []) notes.push(String(n));

  const flags = [];
  if (a?.sealed) flags.push(`봉인: ${a.sealed}`);
  if (a?.skipped) flags.push(`건너뜀: ${a.skipped}`);

  const effect = a?.effect
    ? { text: effectText(a.effect), ineffective: a.effect.changed === false }
    : null;

  return {
    // 무엇을 어디에 하나 — 반영 전엔 요청(마하·표), 반영 뒤엔 엔진 결과(a.knot — 분리·못 더함)대로
    action: actionText(a?.action, a?.knot),
    // 반영 뒤 엔진이 적은 절점 추가 결과 한 줄 — 동작 줄이 이미 말하므로 더한 경우의 분리 표만 따로 남긴다
    knot: a?.knot?.added
      ? `절점 더함${Array.isArray(a.knot.split) && a.knot.split.length
        ? ` — 분리 집합으로 뗀 표: ${a.knot.split.join(", ")}` : " — 그 집합을 쓰는 표 전부에"}`
      : null,
    head,
    shortfall: shortfallLines(ev.shortfall),
    tuned: tunedLines(ev.tuned, reasonMap),
    relief: reliefLines(ev.bottleneck?.relief, reasonMap),
    effect,
    notes,
    flags,
  };
}

// ── 미달 원장 ──────────────────────────────────────────────────────────

/** 원장 행 종류 → {label, text}. label은 표 칸, text는 "무슨 뜻이고 다음에 뭘 하나".
 *
 * 처방 카드가 붙는 실패는 미달의 일부일 뿐이다 — 처방이 나오지 않는 미달(튜닝이
 * 설계 목표를 못 채운 자리, 판정 불가, 채택 제외, 튜닝을 건너뛴 점, 트림
 * 미수렴, 반영했는데 안 바뀐 처방)이 오히려 더 많다. 종전 화면은 그중 카드가 있는
 * 것만 그려서, **처방이 안 나온 미달은 화면 어디에도 없었다.**
 *
 * 종류마다 다음 행동이 다르므로 라벨만 붙이고 뜻을 안 적으면 표가 "무엇이 안 됐나"만
 * 말하고 "그래서 뭘 하나"는 말하지 않는다. */
export const LEDGER_KIND = {
  verify: {
    label: "검증 미달",
    text: "보간 실효 게인으로 잰 마진이 합격선(fail) 또는 목표선(warn) 아래다 — "
      + "처방 카드가 있으면 승인해 재개하고, 없으면 그 점·자리를 직접 볼 것",
  },
  tune: {
    label: "튜닝 목표 미달",
    text: "자동 튜닝이 설계 목표를 못 채웠다 — 합격선은 넘길 수 있다. 사유를 보고 "
      + "예산을 늘리거나 목표를 낮춘다",
  },
  unjudged: {
    label: "판정 불가",
    text: "교차 없음(nan)이거나 트림 미수렴이라 판정이 안 났다 — 통과가 아니다. "
      + "이 자리는 검증되지 않은 채로 남는다",
  },
  outside_envelope: {
    // 조건 판정(05 §11.3)이 채택하지 않은 수렴 점 — 여유 미달은 v1.65부터 채택이라 여기 오지 않는다
    label: "채택 제외",
    text: "트림은 수렴했으나 조건 판정이 채택하지 않은 점이다(제한 위반·모델 범위 밖 — 까닭은 점 표의 「자동 설계 채택」 열) — "
      + "처방·수렴 판정에서 뺐고 마진은 참고값이다. 제한 위반이면 설계 범위에서 뺄 점인지, 모델 범위 밖이면 "
      + "모델 보강인지 격자 조정인지 먼저 정할 것",
  },
  not_trimmed: {
    label: "트림 미수렴",
    text: "트림해를 못 찾아 아무것도 못 봤다 — 이 점에는 마진도 게인 근거도 없다. "
      + "격자 범위·조종면 한계를 확인할 것",
  },
  skipped: {
    label: "튜닝 건너뜀",
    text: "이 점에서는 튜닝을 돌리지 않았다 — 게인은 이웃에서 보간된 값이고 그 자리의 "
      + "근거는 없다. 점 예산을 늘리거나, 검증점이면 설계점으로 올린다",
  },
  ineffective: {
    label: "무효 처방",
    text: "반영했는데 판정이 안 움직였다 — 이터 예산만 나갔다. 같은 처방을 다시 "
      + "승인하지 말고 상위 설계·격자를 볼 것",
  },
};

/** 종류 라벨 — 모르는 코드는 **코드 그대로**. 삼키면 엔진에 종류가 늘어도 화면이
 * 조용해지고, 그 행은 표에서 이름 없는 줄이 된다. */
export function ledgerKindLabel(kind) {
  return LEDGER_KIND[kind]?.label ?? String(kind ?? "?");
}

export function ledgerKindText(kind) {
  return LEDGER_KIND[kind]?.text
    ?? `화면이 모르는 종류다 (${kind ?? "없음"}) — 엔진과 화면의 어휘가 어긋났다. `
      + "결과 JSON의 ledger를 직접 볼 것.";
}

/** 행 색 계열 — kind가 먼저, 그다음 status.
 *
 * fail 계열은 빨강, 목표 미달·판정 불가는 주황, 설계 대상 밖(엔벨로프·건너뜀)은
 * 회색, 무효 처방은 따로 강조한다 — 무효 처방은 "미달"이면서 동시에 "예산을 태운
 * 처방"이라, 다른 미달과 같은 색으로 두면 눈에 안 띈다. */
export function ledgerTone(row) {
  const kind = row?.kind;
  if (kind === "ineffective") return "ineffective";
  if (kind === "outside_envelope" || kind === "skipped") return "na";
  if (kind === "not_trimmed") return "fail";
  if (kind === "tune" || kind === "unjudged") return "warn";
  const s = row?.status;
  if (s === "fail") return "fail";
  if (s === "warn") return "warn";
  if (s === "ok") return "ok";
  return "na";
}

/** 심각도 정렬 키 — 큰 것이 앞. null(못 잼)이 가장 앞, 그다음 ∞ 부족.
 *
 * 엔진 severity와 같은 규약이다: "얼마나 나쁜지 모른다"가 먼저다. 비유한값은
 * 문자열로 오므로(serialize.py) numeric()으로 걸러 부호만 본다 — 숫자로 다루면
 * "inf" 비교가 전부 false가 되어 최악이 목록 꼬리에 가라앉는다. */
function severityKey(s) {
  if (s == null) return Number.POSITIVE_INFINITY;
  const v = numeric(s);
  if (v != null) return v;
  return s === "inf" ? Number.MAX_VALUE : -Number.MAX_VALUE;
}

/** 원장 행의 처방 칸 한 줄 — 처방이 없으면 null.
 *
 * verdict만 찍으면 "그 처방이 어떻게 됐는가"가 빠진다. 반영 여부와 효과까지 같은
 * 줄에 있어야, 카드 목록을 따로 뒤지지 않고도 이 미달이 손을 탄 자리인지 알 수 있다. */
export function ledgerActionText(action) {
  if (!action) return null;
  const parts = [VERDICT_LABEL[action.verdict] ?? action.verdict ?? action.type ?? "처방"];
  // 절점 추가는 판정 이름만으로 동작이 안 읽히는 판정(단순 부족 등)에서도 나온다 — 동작을 붙인다
  if (action.type === "add_knot" && !parts[0].includes("절점 추가")) parts.push("절점 추가");
  if (!action.applied) parts.push("미반영 — 승인하면 반영된다");
  else if (action.changed === false) {
    parts.push("반영했으나 판정이 그대로다 — 이 자리에서 듣지 않았다");
  } else if (action.changed) parts.push("반영 후 판정이 움직였다");
  else parts.push("반영됨 — 효과는 다음 검증에서 잰다");
  if (action.sealed) parts.push(`봉인: ${action.sealed}`);
  return parts.join(" · ");
}

/** body.ledger → 표 행. 없으면 [] (원장이 생기기 전의 구형 결과도 그대로 뜬다).
 *
 * 표시용 필드를 여기서 붙인다 — 사유 한국어, 부족 한 줄(가장 심각한 지표 하나),
 * 종류 라벨·뜻, 색 계열, 심각도 표기, 처방 한 줄. 뷰는 배치만 한다.
 *
 * 정렬은 엔진 규약(severity 내림차순·못 잼이 맨 앞)을 여기서 한 번 더 세운다.
 * 엔진 순서를 그대로 믿으면 계약이 흔들렸을 때 화면이 조용히 잘못된 순서를 그리고,
 * 상위 N개만 펼치는 화면에서 그것은 곧 **가장 나쁜 행이 접힌 채로 남는 것**이다.
 * 같은 심각도 안에서는 엔진 순서를 지킨다(JS sort는 안정 정렬). */
export function ledgerRows(body, reasonMap) {
  const rows = (body?.ledger ?? []).map((r) => {
    const worst = shortfallLines(r?.shortfall)[0] ?? null;
    const reasonLine = reasonText(r?.reason, reasonMap);
    const note = r?.note ?? null;
    // 튜닝 행에는 shortfall이 없다 — 검증 항목이 아니라서 요구선 대비 부족을 못 낸다.
    // 대신 목표와 달성이 따로 실려 오는데, 그 칸을 비우면 "얼마나 모자란가"가 원장에서
    // 사라진다(그걸 보려고 만든 표다). 달성은 **아는 지표만** 적는다 — 엔진 레코드는
    // 조성 메타를 함께 싣는다 (tunedLines와 같은 이유)
    let shortfallLine = worst?.text ?? null;
    let shortfallKind = worst?.kind ?? null;
    if (!shortfallLine) {
      const parts = [];
      if (r?.target != null) parts.push(`목표 ${num(r.target)}`);
      const ach = achievedText(r?.achieved);
      if (ach) parts.push(`달성 ${ach}`);
      if (parts.length) {
        shortfallLine = parts.join(" · ");
        shortfallKind = null; // 부족량을 잰 것이 아니다 — 빨강으로 칠하지 않는다
      }
    }
    return {
      point: r?.point ?? null,
      loop: r?.loop ?? null,
      kind: r?.kind ?? null,
      status: r?.status ?? null,
      severity: r?.severity ?? null,
      target: r?.target ?? null,
      note,
      // 엔진의 tune 행은 note에 사유 문구를 그대로 넣는다(REASON_TEXT[reason]) —
      // 사유 줄이 같은 문장을 이미 담고 있으면 표에 한 문장이 두 번 뜬다
      noteLine: note && reasonLine && reasonLine.includes(note) ? null : note,
      action: r?.action ?? null,
      kindLabel: ledgerKindLabel(r?.kind),
      kindText: ledgerKindText(r?.kind),
      tone: ledgerTone(r),
      reason: r?.reason ?? null,
      reasonLine,
      // 지표가 여럿이어도 표에는 가장 심각한 하나만 — 나머지는 처방 카드에 있다
      shortfallLine,
      shortfallKind,
      // 못 잰 것을 "0"으로 그리면 최악이 최선처럼 보인다 — 낱말로 적는다
      severityText: r?.severity == null ? "못 잼" : num(r.severity),
      actionLine: ledgerActionText(r?.action),
      // 튜닝 행의 fit_excluded — 튜닝이 성립하지 않아 이 점의 표본을 적합에서 뺀 게인 자리(엔진 원장).
      // 그 점의 스케줄 값은 튜닝값이 아니라 이웃 보간이다 — 원장이 "못 맞췄다"만 말하면 표에 무엇이
      // 들어갔는지(0 자리값이 박혔는지, 보간인지)를 모른다
      excludedLine: Array.isArray(r?.fit_excluded) && r.fit_excluded.length
        ? `적합에서 뺐다 — ${r.fit_excluded.join(", ")} (이 점의 스케줄 값은 튜닝값이 아니라 이웃 보간)`
        : null,
    };
  });
  return rows.sort((a, b) => {
    const ka = severityKey(a.severity);
    const kb = severityKey(b.severity);
    return ka === kb ? 0 : kb - ka;
  });
}

/** 원장이 잘렸다는 고지 한 줄 — 전량이면 null.
 *
 * 저장물은 원장을 severity 상위 N행만 싣는다(routes/design.py MAX_LEDGER_ROWS).
 * 원장은 "이 실행이 못 맞춘 것 전부"를 뜻하는 목록이라, 조용히 잘린 원장은 **못
 * 맞춘 것이 그것뿐이라고 말하는 목록**이 된다 — 실패 0을 통과로 위장하지 않으려고
 * judged를 함께 세는 것과 같은 이유로, 잘린 사실은 표 위에 적는다.
 *
 * 고지(ledger_truncated)가 없어도 report.ledger_size가 행 수보다 크면 잘린 것이다 —
 * 두 출처 중 하나만 믿으면 다른 쪽이 빠졌을 때 화면이 조용해진다. */
export function ledgerTruncatedText(body) {
  const kept = (body?.ledger ?? []).length;
  if (!kept) return null;
  const total = numeric(body?.ledger_truncated?.total)
    ?? numeric(body?.report?.ledger_size);
  if (total == null || total <= kept) return null;
  return `원장 ${total}행 중 ${kept}행만 이 결과에 실렸다 (저장 크기 상한) — `
    + `나머지 ${total - kept}행은 여기에 없다. 심각도 상위부터 남으므로 잘린 쪽이 `
    + "덜 심각하지만, 이 표를 '미달은 이게 전부'로 읽으면 안 된다.";
}

// ── 검증 커버리지 ──────────────────────────────────────────────────────

/** 격자 세분화 중단 사유 → 한국어 [폴백]. 모르는 코드는 코드 그대로 붙는다. */
const REFINE_ABORT_TEXT = {
  budget_points: "점 예산 소진 (점 예산을 올리면 더 촘촘해진다)",
  budget_iters: "이터 예산 소진",
};

function refineAbortText(code) {
  const t = REFINE_ABORT_TEXT[code];
  return t ? `${code} — ${t}` : String(code);
}

const _TONE_RANK = { fail: 2, warn: 1, hint: 0 };

/** report.region_coverage → 줄 [{key, tone, text}] (05 §11.13 이관 2단계). 옛 결과(없음)는 [].
 *  일부 점에서 설계가 성공해도 미해결 요구 조건이 남으면 요구영역 전체를 완료로 읽히면 안 된다 — 그래서 완료가 아니면
 *  「완료 아님」 줄이 먼저 서고(fail), 개수 줄과 엔진 사유(reasons — 문장은 엔진이 정본)가 뒤따른다.
 *  source가 없으면 개수를 지어내지 않는다: 옛 격자로 돈 기체(coarse_source "coarse_grid")는 요구영역 미정의이고, 기본
 *  격자 기록이 없는 세션(이관 2단계 전·COARSE 전)은 기체에 요구영역이 있을 수 있어 「모름」이다 — 미정의라 하지 않는다. */
export function regionCoverageLines(report) {
  const rc = report?.region_coverage;
  if (!rc) return [];
  const reasons = Array.isArray(rc.reasons) ? rc.reasons.map(String) : [];
  if (rc.source == null) {
    if (report?.coarse_source === "coarse_grid") {
      return [{ key: "region_undefined", tone: "fail",
        text: reasons[0] ?? "요구영역 미정의 — 기체 문서에 요구 운용영역이 없어 이 설계가 덮어야 할 범위를 판정하지 못했다" }];
    }
    return [{ key: "region_unknown", tone: "warn",
      text: reasons[0] ?? "요구영역 커버리지 모름 — 이 결과에 요구영역 기본 격자 기록이 없다" }];
  }
  const c = rc.by_category ?? {};
  const n = (k) => Number(c[k]) || 0;
  // 범주를 다 더하면 N이다 — 미선택(예산)·미판정(취소 등)·설정이 뺌(격자 명세 덮음, 있을 때만)까지 센다
  const text = `요구영역 ${Number(rc.points) || 0}점 중 채택 ${n("adopted")} · 제외(트림 ${n("trim")} · 모델 ${n("model")} · `
    + `제한 ${n("limits")} · 요구영역 ${n("region")}) · 미선택 ${n("unselected")} · 미판정 ${n("not_run")}`
    + (n("omitted") ? ` · 설정이 뺌 ${n("omitted")}` : "")
    + (rc.confirmed ? "" : " — 미확정 초안 요구영역(trim_grid 범위) 기준");
  const out = [];
  if (rc.complete !== true) out.push({ key: "region_incomplete", tone: "fail", text: "요구영역 완료 아님 — 미해결 조건 남음" });
  out.push({ key: "region_coverage", tone: rc.complete === true ? "hint" : "warn", text });
  if (rc.complete !== true) reasons.forEach((r, i) => out.push({ key: `region_reason_${i}`, tone: "warn", text: r }));
  return out;
}

/** report.coverage·coverage_gaps → 줄 목록 [{key, tone, text}] — 없으면 [].
 *
 * "무엇을 봤나"가 아니라 **무엇을 안 봤나**를 세는 줄이다. 판정·실패 수는 본 것만
 * 세므로, 안 본 것이 많을수록 그 수치는 오히려 건강해 보인다 — 검증점이 0이면
 * 실패도 0이다.
 *
 * 검증점 0인데 못 넣은 구간이 있는 것이 가장 강한 줄이다: 보간 구간 검증이 한 건도
 * 수행되지 않았다는 뜻이고, 그러면 판정된 자리가 전부 자기 게인이 직접 튜닝된
 * 앵커다 — 스케줄이 breakpoint 사이에서 무너지는지는 아무도 보지 않았다.
 *
 * 프로즈는 엔진이 정본이다(coverage_gaps). 여기서 만드는 문장은 **엔진 문장이 없을
 * 때만** 붙는다 — 둘 다 내면 같은 말이 색만 달리해 두 번 뜬다. 수치 줄은 항상 낸다:
 * 엔진 문장은 "왜 문제인가"를 말하고 이 줄은 "몇 개인가"를 말한다.
 *
 * 검증점 수와 못 넣은 수는 **더하지 않는다**. validation_points는 지금 점집합에
 * 실재하는 검증점 수이고(스테이지 카운터로 세면 VERIFY가 여러 번 도는 이터레이션에서
 * 마지막 패스 값만 남아, 15개를 넣고도 0으로 보고된다), validation_missing은 요구했는데
 * 점 예산 때문에 못 넣은 구간 수다. 이터가 돌면 요구가 갱신되므로 둘의 합은 전체 구간
 * 수가 아니다 — "요구 N개 중 M개"라고 쓰면 화면이 분모를 지어내게 된다.
 *
 * 줄 순서는 심각도순(fail → warn → hint)으로 세운다. 엔진 문장이 먼저 오면 가장 큰
 * 공백이 목록 중간에 묻힌다. */
export function coverageLines(report) {
  const c = report?.coverage ?? null;
  const gaps = (report?.coverage_gaps ?? []).filter((g) => String(g ?? "").trim());
  // 엔진 문장이 있으면 화면은 수치만 말한다 — 프로즈를 다시 적지 않는다
  const prose = (s) => (gaps.length ? "" : s);
  const out = [];
  if (c) {
    // 검증점 수가 아예 안 온 것과 0인 것은 다르다 — 없는 수를 0으로 읽으면
    // "한 건도 안 봤다"를 결과가 말한 적 없는데 화면이 단정하게 된다. 못 넣은 수도 같다 — 안 온 것을 0으로 읽으면
    // 검증점 0을 「볼 구간이 없었다」로 삼킨다
    const got = numeric(c.validation_points);
    const missingRaw = numeric(c.validation_missing);
    const missing = missingRaw ?? 0;
    // 엔진 키(orchestrator.coverage) — 내분점 자리에 설계점이 있어 옮긴 수는 **정보용**이다(설계점 판정은 적합 잔차라
    // 검증이 아니다). 옛 초안 키 validation_at_design_points는 설계점 겹침을 검증으로 센 수라 읽지 않는다
    const moved = numeric(c.midpoints_at_design_points);
    const movedText = moved ? ` (중점에 설계점이 있어 옮긴 ${num(moved)})` : "";
    if (got == null && missing > 0) {
      out.push({ key: "validation", tone: "warn",
        text: `보간 구간 ${num(missing)}개가 검증점 없이 남았는데 실제로 몇 개가 검증됐는지를 `
          + "결과가 말하지 않는다 — 무엇을 봤는지 확인할 수 없다." });
    } else if (got === 0 && missing > 0) {
      out.push({ key: "validation", tone: "fail",
        text: `보간 구간 검증점이 한 개도 없다 (검증점 없이 남은 구간 ${num(missing)}개).`
          + prose(" 판정된 자리가 전부 자기 게인이 직접 튜닝된 설계점이다 —"
            + " 스케줄이 절점 사이에서 무너지는지는 보지 않았다.") });
    } else if (got === 0 && missingRaw == null) {
      out.push({ key: "validation", tone: "warn",
        text: "보간 구간 검증점 0 — 못 넣은 구간 수를 결과가 말하지 않는다(볼 구간이 없었는지 알 수 없다)." });
    } else if (got > 0 && missing > 0) {
      // got은 검증점 수다(구간 수가 아니다 — 편입된 검증점과 그 구간의 새 검증점이 함께 센다)
      out.push({ key: "validation", tone: "warn",
        text: `보간 구간 ${num(missing)}개가 검증점 없이 남았다 (들어간 검증점은 ${num(got)}개).`
          + prose(" 그 구간의 스케줄은 보지 않았다.") });
    } else if (got > 0) {
      // 못 넣은 구간이 없다 — 이건 공백이 아니라 근거라 회색으로 둔다
      out.push({ key: "validation", tone: "hint",
        text: `보간 구간 검증점 ${num(got)}${movedText}` });
    }
    // got === 0 && missing === 0이면 아무 말도 안 한다 — 검증할 구간 자체가 없었다
    const unplaceable = numeric(c.validation_unplaceable);
    if (unplaceable) {
      out.push({ key: "unplaceable", tone: "warn",
        text: `보간 구간 ${num(unplaceable)}개는 검증점을 둘 빈 자리가 없었다 (내분점마다 설계점).`
          + prose(" 설계점 판정은 적합 잔차라 그 구간의 보간은 보지 않았다.") });
    }

    const rem = numeric(c.refine_remaining);
    const tol = numeric(c.refine_tol);
    if (rem != null && tol != null) {
      out.push(rem > tol
        ? { key: "refine", tone: "warn",
          text: `REFINE이 남긴 최대 플랜트 거리 ${num(rem)} (허용 ${num(tol)})`
            + `${c.refine_aborted ? ` · 중단 사유 ${refineAbortText(c.refine_aborted)}` : ""}`
            + prose(" — 격자가 플랜트 변화를 다 못 따라갔다."
              + " 그 구간의 게인은 보간으로만 채워진다.") }
        : { key: "refine", tone: "hint",
          text: `플랜트 거리 잔여 ${num(rem)} ≤ 허용 ${num(tol)}` });
    } else if (c.refine_aborted) {
      // 거리를 못 재도 중단 사실은 남는다 — 조용히 넘기면 격자가 계획대로 찼는지 모른다
      out.push({ key: "refine", tone: "warn",
        text: `격자 세분화 중단 — ${refineAbortText(c.refine_aborted)}` });
    }
    const nt = numeric(c.not_trimmed) ?? 0;
    if (nt > 0) {
      out.push({ key: "not_trimmed", tone: "warn",
        text: `트림 미수렴 ${num(nt)}점`
          + prose(" — 그 점들은 실패 목록에도 판정 수에도 들어가지 않는다.") });
    }
    // 검증점 계획(05 §11.6 — 이관 4단계). 요청·완료·미실행은 **요구영역 안** 점만 센다 — 요구영역 밖은 계획에만 있고
    // (트림·예산 없음) 따로 적는다. 옛 결과(키 없음)는 줄이 없다 — 없는 수를 0으로 읽지 않는다
    const req = numeric(c.validation_requested);
    if (req != null) {
      const done = numeric(c.validation_done);
      const notRun = numeric(c.validation_not_run) ?? 0;
      const oor = numeric(c.validation_out_of_region) ?? 0;
      // 완료 < 요청인데 미실행이 아니면 계산은 했으나 못 선 점이다(트림 불가·계산 실패 등) — 요약 격자 합계의 상태
      // 내역으로 이유를 댄다. 내역이 없으면(옛 결과·격자 없음) 이유를 모른다고 쓰고 경고색이다
      const short = done == null ? 0 : Math.max(0, req - done - notRun);
      const states = report?.summary_grid?.totals?.states;
      const whyText = states ? tally(Object.fromEntries(Object.entries(states)
        .filter(([k]) => k !== "computable" && k !== "not_run")), STATE_SHORT) : "";
      const unexplained = short > 0 && !whyText;
      out.push({ key: "validation_plan", tone: notRun > 0 || unexplained ? "warn" : "hint",
        text: `검증점 요청 ${num(req)} · 완료 ${done == null ? "?" : num(done)}`
          + (short ? ` · 미완료 ${num(short)}(${whyText || "사유 기록 없음"})` : "")
          + (notRun ? ` · 미실행 ${num(notRun)}` : "")
          + (oor ? ` · 요구영역 밖 ${num(oor)}(계획만)` : "")
          + (notRun ? prose(" — 돌지 않은 점(예산·취소)은 판정 수에 없다.") : "") });
    }
    const omitted = Array.isArray(c.validation_omitted_rows) ? c.validation_omitted_rows.length
      : numeric(c.validation_omitted_rows);
    if (omitted) {
      out.push({ key: "validation_omitted", tone: "warn",
        text: `대표 조건 방식이 뺀 검증 조건 ${num(omitted)}행`
          + prose(" — 그 고도·연료에서는 절점 사이를 이번에 보지 않았다.") });
    }
    const dUn = Array.isArray(c.d_unmeasured) ? c.d_unmeasured.length : numeric(c.d_unmeasured);
    if (dUn) {
      out.push({ key: "d_unmeasured", tone: "warn",
        text: `보강 지표 d를 잴 수 없는 구간 ${num(dUn)}`
          + prose(" — 양끝이나 안쪽 점이 계산되지 않았다. 완료로 치지 않는다.") });
    }
    // 보강이 예산에서 멈췄다 — 남은 구간은 합격도 설계 불가도 아니다(05 §11.7). 허용치 미설정(tol_unset)은 공백이 아니다
    if (c.reinforce_status === "budget") {
      out.push({ key: "reinforce", tone: "warn", text: REINFORCE_STATUS_TEXT.budget
        + prose(" — 허용치를 넘는 구간이 남았다.") });
    }
  }
  // 엔진이 만든 문장 — 화면이 다시 쓰지 않는다. 비어 있지 않다는 것 자체가
  // "무엇을 안 봤는지가 있는 실행"이라는 신호다
  gaps.forEach((g, i) => {
    out.push({ key: `gap${i}`, tone: "warn", text: String(g) });
  });
  return out.sort((a, b) => (_TONE_RANK[b.tone] ?? 0) - (_TONE_RANK[a.tone] ?? 0));
}

// ── 요약 격자 · 보강 (05 §11.8 · 05 §11.7 — 이관 4단계) ───────────────────────

/** 보강 상태 코드(엔진 reinforce) → 문구 [폴백]. 정본은 보고의 reinforcement.label과 서버
 *  /design/defaults reinforce_status_text — 결과에 문구가 없을 때만 이것을 쓴다. 모르는 코드는 그대로. */
export const REINFORCE_STATUS_TEXT = {
  tol_unset: "허용치 미설정 — d 분포만",
  done: "보강 완료",
  budget: "보강 종료 · 추가 검증 필요",
  unmeasured: "보강 종료 · 잴 수 없는 구간 있음",
};

/** 검증점 종류(엔진 validation.VALIDATION_KINDS) → 이름 [폴백]. 정본은 서버 /design/defaults의 validation_kinds
 *  (엔진 표 그대로) — 그것이 오면 그쪽을 넘긴다. 모르는 종류는 코드 그대로. */
export const VALIDATION_KIND_LABEL = {
  midpoint: "구간 내분점", knot: "절점", clip: "clip 구간", boundary: "요구영역 경계", extra: "추가 조건",
  between_rows: "고도·연료 사이", reinforce: "보강", prior: "이전 계획",
};

/** 검증 방식(엔진 validation.VALIDATION_MODES) → 이름 [폴백]. 정본은 서버 validation_modes. */
export const VALIDATION_MODE_LABEL = { full: "전체 조합", representative: "대표 조합" };

/** 서버 목록(배열 또는 {코드: 이름}) → {코드: 이름}. 배열이면 폴백 이름을 붙인다. */
export function labelMap(list, fallback) {
  if (Array.isArray(list)) return Object.fromEntries(list.map((k) => [k, fallback[k] ?? k]));
  if (list && typeof list === "object") return { ...fallback, ...list };
  return { ...fallback };
}

/** 요약 격자 칸의 대표 문구 코드(엔진 headline_code) → 색 톤. 문구(headline)만 있는 결과는 문구로 고른다.
 *  「구간 합격」이라는 말은 없다 — 검사한 점만 말한다. 판정 불가·채택 제외가 섞인 칸은 회색(모두 충족으로 뭉개지 않는다). */
const HEADLINE_TONE = { fail: "fail", incomplete: "warn", na: "na", excluded: "na", all_met: "ok",
  "불합격": "fail", "미완료": "warn", "판정 불가 포함": "na", "채택 제외 포함": "na", "검사한 점 모두 충족": "ok" };

const VERDICT_SHORT = { fail: "불합격", caution: "주의", good: "충족", na: "판정 불가", excluded: "채택 제외" };
const STATE_SHORT = {
  computable: "계산", calc_failed: "계산 실패", constraint_hit: "제약 걸림", infeasible: "트림 불가",
  not_run: "미실행", out_of_region: "요구영역 밖", undefined: "정의 안 됨", model_gap: "모델 없음",
};

const tally = (obj, names) => Object.entries(obj ?? {})
  .filter(([, n]) => Number(n) > 0).map(([k, n]) => `${names[k] ?? k} ${n}`).join(" · ");

function rowLabel(r) {
  if (r.label) return String(r.label);
  if (r.alt != null && r.fuel != null) return `${num(r.alt)} m · ${num(r.fuel)} kg`;
  return r.kind === "condition" || r.kind == null ? String(r.key) : "경계·추가";
}

function colLabel(c) {
  if (c.kind === "all") return "전 마하";
  if (c.kind === "knot") return machText(c.lo ?? c.hi);
  if (c.kind === "clip") return c.key === "clip_hi" || (c.lo != null && c.hi == null) ? "끝>" : "<끝";
  return "·";
}

function colTip(c) {
  if (c.kind === "all") return "절점 없음(전 자리 상수) — 마하 전체";
  if (c.kind === "knot") return `절점 ${machText(c.lo ?? c.hi)}`;
  if (c.kind === "clip") {
    return c.key === "clip_hi" || (c.lo != null && c.hi == null)
      ? `끝 절점 바깥 ${machText(c.lo)} 이상 — 표는 끝값 유지` : `끝 절점 바깥 ${machText(c.hi)} 이하 — 표는 끝값 유지`;
  }
  return `절점 사이 ${machText(c.lo)}–${machText(c.hi)}`;
}

/** report.summary_grid → 행렬 모델 — 옛 결과(격자 없음)는 null.
 *  열 = 끝 밖 · 절점 · 구간 … · 끝 밖, 행 = 검증 조건 + 「경계·추가」. 칸 글은 짧게(완료 d/n, 불합격 수)이고 대표 문구·
 *  상태·판정 내역은 툴팁이다. 대표 문구는 엔진 것 그대로(불합격 → 미완료 → 「검사한 점 모두 충족」) — 구간 합격이라 하지
 *  않는다. 빈 칸(그 자리에 검증점 없음)은 empty. 요구영역 밖 점은 n에 없고 따로 센다. */
export function summaryGridModel(report) {
  const g = report?.summary_grid;
  if (!g || !Array.isArray(g.columns) || !Array.isArray(g.rows)) return null;
  const columns = g.columns.map((c) => ({ key: c.key, kind: c.kind, label: colLabel(c), tip: colTip(c) }));
  // 칸 수는 대표 문구별로 — 판정 불가 포함과 채택 제외 포함은 색(회색)이 같아도 이름이 다르다
  const counts = { fail: 0, warn: 0, ok: 0, na: 0, excluded: 0 };
  const rows = g.rows.map((r) => {
    const label = rowLabel(r);
    const cells = columns.map((col) => {
      const cell = g.cells?.[r.key]?.[col.key];
      if (!cell || !(Number(cell.n) > 0)) {
        // 요구영역 밖 점만 있는 칸 — 분모에 없으니 빈 칸이되 툴팁이 그 수를 말한다
        const oorHere = Number(cell?.out_of_region) || 0;
        return { key: col.key, empty: true, tone: null, text: "",
          tip: `${label} · ${col.tip} — ${oorHere ? `요구영역 밖 ${oorHere}점만(판정 대상 아님)` : "검증점 없음"}` };
      }
      const fails = Number(cell.verdicts?.fail) || 0;
      const tone = HEADLINE_TONE[cell.headline_code] ?? HEADLINE_TONE[cell.headline] ?? "na";
      const excluded = cell.headline_code === "excluded" || cell.headline === "채택 제외 포함";
      const countKey = excluded ? "excluded" : tone;
      counts[countKey] = (counts[countKey] ?? 0) + 1;
      const tip = [
        `${label} · ${col.tip}`,
        cell.headline ?? null,
        cell.text ?? `완료 ${cell.done ?? "?"}/${cell.n}`,
        tally(cell.states, STATE_SHORT) ? `상태 — ${tally(cell.states, STATE_SHORT)}` : null,
        tally(cell.verdicts, VERDICT_SHORT) ? `판정 — ${tally(cell.verdicts, VERDICT_SHORT)}` : null,
      ].filter(Boolean).join("\n");
      return { key: col.key, empty: false, tone, headline: cell.headline ?? null, fails,
        text: fails ? `✗${fails}` : `${cell.done ?? "?"}/${cell.n}`, tip };
    });
    return { key: r.key, kind: r.kind ?? null, label, cells };
  });
  const t = g.totals ?? {};
  const oor = numeric(t.out_of_region) ?? numeric(report?.validation?.out_of_region);
  const summary = `요약 격자 — 불합격 칸 ${counts.fail} · 미완료 칸 ${counts.warn} · 검사한 점 모두 충족 칸 ${counts.ok}`
    + (counts.na ? ` · 판정 불가 포함 칸 ${counts.na}` : "")
    + (counts.excluded ? ` · 채택 제외 포함 칸 ${counts.excluded}` : "")
    + (oor ? ` · 요구영역 밖 ${num(oor)}점(칸에 없음)` : "");
  // 엔진 주석(계획 밖 점의 실패 · 계획 뒤 절점 바뀜) — 녹색 격자와 미수렴 상태가 설명 없이 나란히 서지 않게
  const notes = Array.isArray(g.notes) ? g.notes.filter((n) => typeof n === "string" && n) : [];
  return { columns, rows, counts, outOfRegion: oor, summary, notes };
}

const DIST_KEYS = [["max", "최대"], ["p90", "p90"], ["p50", "p50"]];

/** report.reinforcement → 줄 [{key, tone, text, tip?, slot?}] — 옛 결과는 []. 첫 줄은 상태(엔진 label 우선).
 *  허용치 미설정(tol_unset)은 공백이 아니다(회색) — 자리별 d 분포를 한 줄씩 짧게. 허용치가 있으면 추가점·남은 구간·최대 d,
 *  잴 수 없는 구간(사유는 툴팁), 양끝 판정이 다른 구간 수. 척도 s와 그 출처는 툴팁. */
export function reinforcementLines(report, statusText = null) {
  const rf = report?.reinforcement;
  if (!rf || typeof rf !== "object") return [];
  const st = rf.status ?? null;
  const label = rf.label ?? statusText?.[st] ?? REINFORCE_STATUS_TEXT[st] ?? String(st ?? "보강 기록 없음");
  const tone = st === "budget" || st === "unmeasured" ? "warn" : "hint";
  const scales = rf.scales ?? {};
  const src = rf.scale_sources ?? {};
  const scaleTip = Object.keys(scales).map((k) => `${k} s=${num(scales[k])}${src[k] ? ` — ${src[k]}` : ""}`).join("\n");
  const out = [{ key: "reinforce_status", tone, text: `보강 — ${label}`, tip: scaleTip || null }];
  const tol = numeric(rf.tol ?? rf.budget?.tol);
  const cnt = (x) => (Array.isArray(x) ? x.length : numeric(x));
  if (tol != null) {
    const added = cnt(rf.added) ?? 0;
    // 엔진 문구가 이미 남은 구간·최대 d를 말하면(budget label) 다시 적지 않는다
    const rem = String(label).includes("남은 구간") ? 0 : cnt(rf.remaining) ?? 0;
    const b = rf.budget ?? {};
    const budget = [b.max_points != null ? `추가점 상한 ${b.max_points}` : null,
      b.max_depth != null ? `깊이 ${b.max_depth}` : null, b.max_time_s != null ? `${b.max_time_s} s` : null]
      .filter(Boolean).join(" · ");
    out.push({ key: "reinforce_run", tone: rem ? "warn" : "hint",
      text: `허용치 d ≤ ${+tol.toPrecision(6)} · 추가 ${num(added)}점`
        + (rem ? ` · 남은 구간 ${num(rem)}(최대 d ${num(rf.max_d_remaining)})` : ""),
      tip: budget ? `예산 — ${budget}` : null });
  }
  const dist = rf.distribution ?? {};
  for (const slot of Object.keys(dist)) {
    const d = dist[slot] ?? {};
    out.push({ key: `dist_${slot}`, slot, tone: "hint",
      text: `${slot} d ${DIST_KEYS.filter(([k]) => d[k] != null).map(([k, n]) => `${n} ${num(d[k], 2)}`).join(" · ")}`
        + (d.n != null ? ` (n ${d.n})` : ""),
      tip: scales[slot] != null ? `s=${num(scales[slot])}${src[slot] ? ` — ${src[slot]}` : ""}` : null });
  }
  const un = Array.isArray(rf.unmeasured) ? rf.unmeasured : [];
  const nUn = un.length || numeric(rf.unmeasured) || 0;
  if (nUn) {
    out.push({ key: "reinforce_unmeasured", tone: "warn", text: `잴 수 없는 구간 ${nUn}`,
      tip: !un.length ? null : un.slice(0, 12).map((u) => `${Array.isArray(u.row) ? u.row.join("/") : u.row ?? "?"} · `
        + `${Array.isArray(u.interval) ? u.interval.map(machText).join("–") : u.interval ?? "?"} — ${u.why ?? "?"}`)
        .join("\n") + (un.length > 12 ? `\n… 외 ${un.length - 12}` : "") });
  }
  const vc = cnt(rf.verdict_change_intervals) ?? numeric(rf.verdict_change);
  if (vc) out.push({ key: "verdict_change", tone: "hint", text: `양끝 판정이 다른 구간 ${num(vc)}` });
  return out;
}

/** report.validation.by_kind → {종류: 요청 수}. 엔진은 종류마다 {requested, done, not_run, out_of_region}를 싣는다 —
 *  수 하나만 온 모양도 읽는다. */
export function kindCounts(byKind) {
  return Object.fromEntries(Object.entries(byKind ?? {}).map(([k, v]) =>
    [k, v && typeof v === "object" ? Number(v.requested) || 0 : Number(v) || 0]));
}

/** report.validation → 한 줄(탭 요약·결과 브리핑 공용) — 옛 결과(구간 중점 규칙·기록 없음)는 null.
 *  「요청 N · 완료 M · 조건 k행(방식) · 뺀 j행 · 요구영역 밖 o · 종류별 수」. */
export function validationSummaryText(report, { kinds = null, modes = null } = {}) {
  const v = report?.validation;
  if (!v || typeof v !== "object" || v.rule === "midpoint") return null;
  const cov = report?.coverage ?? {};
  const nCond = Array.isArray(v.conditions) ? v.conditions.length : numeric(v.conditions);
  const nOm = Array.isArray(v.omitted) ? v.omitted.length : numeric(v.omitted);
  const done = numeric(v.done) ?? numeric(cov.validation_done);
  const kindText = tally(kindCounts(v.by_kind), labelMap(kinds, VALIDATION_KIND_LABEL));
  const modeName = labelMap(modes, VALIDATION_MODE_LABEL)[v.mode] ?? v.mode ?? "?";
  return [
    `요청 ${v.requested ?? "?"}${done != null ? ` · 완료 ${done}` : ""}`,
    nCond != null ? `조건 ${nCond}행(${modeName})` : null,
    nOm ? `뺀 조건 ${nOm}행` : null,
    numeric(v.out_of_region) ? `요구영역 밖 ${v.out_of_region}(계획만)` : null,
    kindText || null,
  ].filter(Boolean).join(" · ");
}

// ── 문서 반영 관문 · 신호(쇼케이스) 사슬 ────────────────────────────────

/** [문서에 반영] 관문 — 결과의 기체 echo로 서버 apply-gains 가드(routes/design.py)와 같은 판정을
 * **버튼 앞에서** 말한다. null이면 반영 대상이 있다(최종 판정은 여전히 서버 — 지문·리비전 409).
 *
 * source가 "request"인지만 보면 안 된다. 재개(resume)한 결과는 저장된 스냅숏으로 조립돼
 * source가 "snapshot"이다 — 종전 관문은 이걸 예제로 읽어 승인·재개한 결과의 반영 버튼을
 * 숨겼다. 거꾸로 헤더에서 예제를 **명시로** 고르면 source가 "request"라 관문을 지나고
 * 서버가 403을 낸다. 그래서 id·예제 표시·출처 셋을 함께 본다. */
export function applyGateReason(echo) {
  if (!echo?.id) {
    return "기체 기록이 없는 옛 결과는 문서에 반영할 수 없다 — 기체를 골라 다시 설계한다.";
  }
  if (echo.is_example || echo.id === EXAMPLE_ID
      || echo.source === "default-example" || echo.source === "legacy-unrecorded") {
    return "예제 기체는 문서에 반영할 수 없다 — 복제한 기체에서 설계하고 반영한다.";
  }
  if (echo.variant) {
    return "형상 변형 위에서 돈 설계는 기본 문서에 반영할 수 없다 — 기본 형상으로 다시 돌린다.";
  }
  return null;
}

/** config 덮어쓰기 둘을 겹친다 — over가 이긴다. 판정선·튜닝 목표(criteria·targets)는 어느 쪽에 있어도
 * 뗀다 — 서버는 선택 기체 문서의 /criteria·/tuning으로 설계한다(옛 신호·기록이 실어 와도 요청에 안 싣는다). */
export function mergeDesignConfig(base, over) {
  return withoutCriteria({ ...(base ?? {}), ...(over ?? {}) });
}

// 폼 칸 ↔ config 키 — buildConfig의 역방향. 칸이 없는 키(예: max_degree)는 여기 없다
const FORM_OF_CONFIG = [
  ["budget_points", "budgetPoints"], ["budget_iters", "budgetIters"], ["n_mach", "nMach"],
  ["n_validation_between", "nValidationBetween"], ["actuator_wn", "actuatorWn"],
  ["actuator_zeta", "actuatorZeta"], ["delay_s", "delayS"],
];

/** config 덮어쓰기 → 실행 설정·요구 조정 칸의 글 — 신호로 온 설정을 **화면 칸에** 보이게.
 * 칸이 있는 키만 옮긴다(나머지는 호출측이 config로 그대로 덧씌운다). 숫자 목록은 공백 구분 —
 * 칸 placeholder와 같은 모양이라 buildConfig가 그대로 되읽는다. */
export function configFormValues(config) {
  const c = config ?? {};
  const out = {};
  if (typeof c.mode === "string") out.mode = c.mode;
  // 게인 표현 — 열거값이라 FORM_OF_CONFIG(수치 칸)에 못 섞는다. 옮기지 않으면 신호가 준 표현이
  // 셀렉트에 안 보이고(실행은 config 덧씌움으로 맞게 돈다), buildConfig 되읽기에서 사라진다
  if (typeof c.fit_mode === "string") out.fitMode = c.fit_mode;
  for (const [key, field] of FORM_OF_CONFIG) {
    if (c[key] != null) out[field] = String(c[key]);
  }
  if (Array.isArray(c.alts)) out.altsText = c.alts.join(" ");
  if (Array.isArray(c.fuels)) out.fuelsText = c.fuels.join(" ");
  // 절점 설정 — 규칙 셀렉트·절점 수·좌표·표당 상한 칸 (buildConfig의 knotConfig 역방향)
  const k = c.knots;
  if (k && typeof k === "object") {
    if (typeof k.rule === "string") out.knotRule = k.rule;
    if (k.n != null) out.knotN = String(k.n);
    if (Array.isArray(k.coords)) out.knotCoordsText = k.coords.join(" ");
    if (k.max_per_table != null) out.knotMax = String(k.max_per_table);
  }
  // 검증점·보강 설정 — validationConfig·reinforceConfig의 역방향. 조건은 「고도/연료」 짝 글
  const v = c.validation;
  if (v && typeof v === "object") {
    if (Array.isArray(v.conditions)) out.validationConditionsText = v.conditions.map((p) => p.join("/")).join(", ");
    if (typeof v.mode === "string") out.validationMode = v.mode;
    if (typeof v.boundary === "boolean") out.validationBoundary = v.boundary ? "on" : "off";
  }
  const r = c.reinforce;
  if (r && typeof r === "object") {
    for (const [key, field] of [["tol", "reinforceTol"], ["max_points", "reinforceMaxPoints"],
      ["max_depth", "reinforceMaxDepth"], ["max_time_s", "reinforceMaxTime"]]) {
      if (r[key] != null) out[field] = String(r[key]);
    }
  }
  return out;
}

/** 처방 카드의 기본 승인 — 봉인·건너뜀 처방만 해제(엔진은 승인하면 봉인된 것도 반영하고 다시
 * 봉인한다 — 무효인 줄 아는 처방에 이터 예산이 나간다). 탭 체크박스의 기본값이 이것이고, 신호
 * 사슬도 그 체크박스를 그대로 읽는다(손대지 않고 [승인 반영 재개]를 누른 것과 같다). */
export function approvedByDefault(action) {
  return !(action?.sealed || action?.skipped);
}

/** 결과 한 줄 — 신호 보고의 summary. 탭 보고서가 이미 내는 수(상태·이터레이션·판정·실패·
 * 실패 위치·표현·처방·에스컬레이션·표본 제외)만 옮긴다 — 새 판정을 만들지 않는다. 실패 위치와 표현은
 * 상태 줄(reportLine)과 같은 함수다: "실패 45"가 앵커의 튜닝 실패인지 점 사이의 스케줄 실패인지,
 * 검증받은 것이 반출될 표 그 자체인지 재양자화 근사인지를 진행기 카드도 같은 말로 한다. */
export function designCueSummary(body) {
  const r = body?.report ?? {};
  const cards = actionCards(body);
  const parts = [
    r.status ?? "?",
    `이터레이션 ${Number(r.iterations) || 0}`,
    `판정 ${Number(r.judged) || 0}`,
    `실패 ${Number(r.failures) || 0}`,
  ];
  const where = failureRoleText(r.failures_by_role);
  if (where) parts.push(`실패 위치 ${where}`);
  const mode = fitModeLabel(r.fit_mode);
  if (mode) parts.push(`표현 ${mode}`);
  if (cards.approvable.length) parts.push(`처방 ${cards.approvable.length}`);
  if (cards.escalations.length) parts.push(`에스컬레이션 ${cards.escalations.length}`);
  const nExcluded = Array.isArray(r.excluded_samples) ? r.excluded_samples.length : 0;
  if (nExcluded) parts.push(`튜닝 실패 표본 제외 ${nExcluded}`);
  // 요구영역 — 부분 성공이 완료로 읽히지 않게 신호 한 줄에도(이관 2단계). 옛 결과(없음)는 말하지 않는다
  const rc = r.region_coverage;
  // source 없음은 둘이다 — 옛 격자로 돈 기체(미정의)와 기본 격자 기록이 없는 세션(모름: 기체엔 요구영역이 있을 수 있다)
  if (rc && rc.source == null) parts.push(r.coarse_source === "coarse_grid" ? "요구영역 미정의" : "요구영역 커버리지 모름");
  else if (rc && rc.complete !== true) {
    parts.push(`요구영역 완료 아님 (채택 ${Number(rc.by_category?.adopted) || 0}/${Number(rc.points) || 0})`);
  }
  return parts.join(" · ");
}

/** 엔진 coarse 격자의 기본 연료 비율 — `fuels`를 비우면 fuel_max × 이 비율(엔진 design/grid.py
 * DEFAULT_FUEL_FRACS의 **사본**이다). 서버 /design/defaults가 `grid.fuel_fracs`를 내면 그쪽이
 * 정본이고 이 사본은 옛 서버용 폴백이다. 기체 값(fuel_max)은 여기 없다 — 문서에서 받는다. */
export const DEFAULT_FUEL_FRACS = Object.freeze([0.1, 0.5, 1.0]);

/** 연료 칸 placeholder — 비웠을 때 엔진이 실제로 쓰는 연료 목록([kg], 공백 구분). 기체 문서의
 * fuel_max × 비율이다: 예제 값이나 옛 1200 kg 기체의 "40 200 400"을 물려주지 않는다(기체 고정
 * 금지). fuel_max를 모르면 빈 글 — 모르는 값을 수치로 위장하지 않는다. */
export function fuelsPlaceholder(fuelMax, fracs = DEFAULT_FUEL_FRACS) {
  const fm = numeric(fuelMax);
  if (fm == null || !(fm > 0)) return "";
  const list = Array.isArray(fracs) && fracs.length ? fracs : DEFAULT_FUEL_FRACS;
  return list.map((f) => {
    const v = fm * Number(f);
    // 0.1 × 45 = 4.5000000001 같은 부동소수 꼬리를 떼고, 정수면 정수로
    return String(Number(v.toPrecision(4)));
  }).join(" ");
}

/** 격자 칸 자리표시 — 비웠을 때 COARSE가 실제로 쓰는 명세 {nMach, alts, fuels, source} (05 §11.13 이관 2단계).
 * 요구영역이 있으면 그 기본 격자 명세(operating_region.base_grid), 절이 없으면 trim_grid 초안의 모양(엔진 region_of 규칙 —
 * 마하 점 수 = 범위/간격 + 1), 둘 다 없으면 옛 coarse 기본값(서버 grid · fuel_max × 비율). 모르는 칸은 null. */
export function gridPlaceholders(doc, defaults) {
  const r = doc?.operating_region;
  if (r?.base_grid) {
    const g = r.base_grid;
    return { nMach: String(g.n_mach), alts: g.alts.join(" "), fuels: g.fuels.join(" "), source: "region" };
  }
  const tg = doc?.mission_template?.trim_grid;
  if (tg) {
    const n = Math.max(2, Math.floor((tg.mach.to - tg.mach.from) / tg.mach.step + 1e-9) + 1);
    return { nMach: String(n), alts: tg.alt.join(" "), fuels: tg.fuel.join(" "), source: "draft" };
  }
  const alts = Array.isArray(defaults?.grid?.alts) ? defaults.grid.alts.join(" ") : null;
  return { nMach: null, alts,
    fuels: fuelsPlaceholder(doc?.mass?.fuel_max, defaults?.grid?.fuel_fracs ?? DEFAULT_FUEL_FRACS) || null,
    source: "legacy" };
}

/** 보고서 자리의 빈 안내 — 결과가 아직 없을 때만 쓴다(결과가 서 있으면 보고서가 스스로 말한다).
 * e2e: 첫 자동 설계가 도는 동안(36/41) 「아직 결과가 없습니다 — [자동 설계 시작]을 누르거나…」가 서 있어
 * 청중은 버튼을 다시 눌러야 하는 줄 알았다 — 검증 탭 D11(lib/verify boardNotice)과 같은 결함, 같은 처방. */
export function emptyResultNotice({ running = false } = {}) {
  if (running) {
    return "자동 설계가 도는 중입니다 — 트림 → 게인 튜닝 → 스케줄 적합 → 마진 검증이 끝나면 운영점 판정·"
      + "처방 카드·게인 확정이 여기 섭니다. 진행은 위 진행줄에 있습니다.";
  }
  return "아직 결과가 없습니다 — [자동 설계 시작]을 누르거나 위 목록에서 지난 결과를 "
    + "열면 운영점 판정·처방 카드·게인 확정이 여기 채워집니다.";
}
