/** 플롯 수치 계층 (뷰·캔버스와 분리, 테스트 대상) — 스케일·눈금·상태색·격자 피벗.

마진 맵 시각화(02 §4)의 수치 부분. 캔버스 그리기 자체는 views/plots.js.
*/

export function linScale(d0, d1, r0, r1) {
  const k = (r1 - r0) / (d1 - d0 || 1);
  return (v) => r0 + (v - d0) * k;
}

export function niceTicks(min, max, n = 5) {
  if (!(max > min)) return [min];
  const span = max - min;
  const step0 = span / Math.max(1, n);
  const mag = 10 ** Math.floor(Math.log10(step0));
  const step = [1, 2, 5, 10].map((m) => m * mag).find((s) => span / s <= n) ?? 10 * mag;
  const out = [];
  for (let v = Math.ceil(min / step - 1e-9) * step; v <= max + 1e-9; v += step) {
    const t = Math.round(v * 1e9) / 1e9;
    out.push(t === 0 ? 0 : t); // -0 정규화 (ceil의 음의 영)
  }
  return out;
}

/** PM[deg] → 상태색 — 관례 여유 기준 [기본값]: ≥45° 양호, 30~45° 주의, <30° 부족.
 * 합격기준 수치는 파라미터 관리 계층 확정 시 그쪽이 정본 (02 §5.5). */
export function marginColor(pm) {
  if (pm === "inf") return "#157f3d";
  if (typeof pm !== "number") return "#9aa3ad"; // null(NaN)·문자열 — 판정 불가
  if (pm < 30) return "#c22f2f";
  if (pm < 45) return "#b57908";
  return "#157f3d";
}

/** 트림 판정 → 비행 엔벨로프 셀 (01 §4.1 자동 판정 플래그 기반 근사).

우선순위: 불가(미수렴/잔차) > 실속 근접(α 여유) > 포화(추력·타면) > 가능.
실속 경계 테이블 기반 정밀 경계선은 공력 정본 확정 후 [백로그].
*/
export function trimEnvelopeCell(r) {
  if (!r.converged || r.flags.residual_ok === false) {
    return { kind: "infeasible", color: "#9aa3ad", text: "불가" };
  }
  if (r.flags.alpha_margin_ok === false) {
    return { kind: "stall", color: "#c22f2f", text: "실속≈" };
  }
  if (r.flags.saturation_ok === false) {
    return { kind: "saturated", color: "#b57908", text: "포화" };
  }
  return { kind: "ok", color: "#157f3d", text: "가능" };
}

/** 시리즈 색 순환 팔레트 — 그룹 내 순번으로 배정 (앱 공통 상태색과 동일 계열). */
export const SERIES_COLORS = ["#1a6feb", "#b57908", "#c22f2f", "#157f3d", "#7a4fc9", "#0e7c86"];

/** 게인 테이블 dict {"그룹.게인": {axes, data}} → 그룹별 차트 시리즈.

1D mach 테이블만 대상 (현 데모 스케줄 규격) — 다차원·비mach 테이블과 그룹 내
mach 축이 다른 테이블은 skipped에 사유와 함께 보고. 그룹 = 이름의 점 앞
접두부, 등장 순서 유지. 반환 {groups: [{group, mach, series}], skipped}.
시리즈 data는 입력 배열 참조 — 편집 후 재호출로 최신값 반영.
*/
export function gainPlotGroups(tables, colors = SERIES_COLORS) {
  const groups = [];
  const byGroup = new Map();
  const skipped = [];
  for (const [name, t] of Object.entries(tables)) {
    const axes = Object.keys(t.axes ?? {});
    if (axes.length !== 1 || axes[0] !== "mach") {
      skipped.push({ name, reason: `1D mach 테이블 아님 (축: ${axes.join("×") || "없음"})` });
      continue;
    }
    const dot = name.indexOf(".");
    const grp = dot >= 0 ? name.slice(0, dot) : name;
    const label = dot >= 0 ? name.slice(dot + 1) : name;
    let g = byGroup.get(grp);
    if (!g) {
      g = { group: grp, mach: t.axes.mach, series: [] };
      byGroup.set(grp, g);
      groups.push(g);
    }
    if (g.mach.length !== t.axes.mach.length || g.mach.some((v, i) => v !== t.axes.mach[i])) {
      skipped.push({ name, reason: "그룹 내 mach 축 불일치 (차트가 x축 공유)" });
      continue;
    }
    g.series.push({ label, data: t.data, color: colors[g.series.length % colors.length] });
  }
  return { groups: groups.filter((g) => g.series.length > 0), skipped };
}

/** margin-map entries → 연료 고정 (mach×alt) 격자 조회. */
export function pivotCases(entries, fuel) {
  const sel = entries.filter((e) => e.trim.case.fuel === fuel);
  const machs = [...new Set(sel.map((e) => e.trim.case.mach))].sort((a, b) => a - b);
  const alts = [...new Set(sel.map((e) => e.trim.case.alt))].sort((a, b) => a - b);
  const map = new Map(sel.map((e) => [`${e.trim.case.mach}|${e.trim.case.alt}`, e]));
  return { machs, alts, at: (m, a) => map.get(`${m}|${a}`) ?? null };
}

export function fuelsOf(entries) {
  return [...new Set(entries.map((e) => e.trim.case.fuel))].sort((a, b) => a - b);
}
