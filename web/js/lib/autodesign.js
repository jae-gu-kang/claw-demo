/** 자동 설계 탭 순수 로직 — 설정 페이로드·점/판정 결합·처방 그룹·게인 채택. DOM·통신 없음.

수치의 정본은 서버(GET /design/defaults ← 엔진 AutoDesignConfig)다 — 여기서
기본값을 다시 적지 않고, 사용자가 채운 칸만 config 덮어쓰기로 보낸다.

게인 채택은 기존 스토어 계약(gains 탭 storePayload — {tables, scheduleOff})으로
낸다. v1은 **재샘플 테이블**(gain_export.tables_resampled)을 주입한다 — 다항
정본(kind='poly')은 서버 sim/codegen이 직접 받지만, 웹 스토어 소비자(구조도
표시·influence·웹 코드 미리보기)가 테이블 형상을 전제하므로 스토어 경유는
호환 반출을 쓴다 (다항 스토어 채택은 [백로그] — docs -01 §3.4).

출처(`gainTablesSource`)를 함께 넣는다 — 게인 탭이 되읽을 때 "자동 설계 확정본
(결과 id)"이라고 이름을 댈 수 있어야, 화면에 뜬 표가 어디서 온 것인지가 분명해진다.
*/

import { parseNumberList } from "./grid.js";

export const VERDICT_LABEL = {
  simple_deficit: "단순 마진 부족 — 검증점 추가",
  plant_variation: "플랜트 급변 — 트림/선형화점 승격",
  gain_interp_valley: "게인 보간 valley — breakpoint 승격 + 재튜닝",
  structural_limit: "구조 한계 — 상위 설계 변경 검토 (보고 전용)",
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

/** 폼 → config 덮어쓰기 — 채운 칸만. 수치 목록 오류는 던진다 (호출측이 표시). */
export function buildConfig(form) {
  const out = {};
  if (form.mode) out.mode = form.mode;
  const nums = [
    ["budgetPoints", "budget_points"],
    ["budgetIters", "budget_iters"],
    ["nMach", "n_mach"],
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
  return out;
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
    trimmable: p.trimmable,
    status: worstStatus(cases[p.name]?.loops),
  }));
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
