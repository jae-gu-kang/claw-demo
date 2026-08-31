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

/** 판정 상태색 팔레트 — 애플 시스템 컬러 (히트맵 셀·범례·엔벨로프 맵이 공유). */
export const STATUS = {
  ok: "#34c759", // 양호
  warn: "#ff9500", // 주의
  bad: "#ff3b30", // 부족·위반
  na: "#aeaeb2", // 판정 불가·트림 불가
};

/** 판정 문턱 [폴백] — **정본은 서버 GET /design/defaults**(엔진 MarginCriteria).
 *
 * 여기 수치는 그 조회가 실패했을 때만 쓴다. 종전에는 이 값이 하드코딩된 판정선
 * 자체였고, 자동 설계 탭에서 criteria.pm_min_deg를 50으로 올려도 마진 탭은 그대로
 * 45로 칠했다 — 같은 47° 점을 한 탭은 초록, 다른 탭은 fail로 보이게 하는 어긋남이다.
 * 폴백을 쓴 화면은 그 사실을 힌트로 밝힌다 (조용한 폴백 금지). */
export const FALLBACK_CRITERIA = Object.freeze({
  pm_min_deg: 45, // 합격선
  pm_bad_deg: 30, // 표시용 심각선
  gm_min_db: 6, // 합격선
  gm_good_db: 8, // 목표선
});

export function threshold(criteria, key) {
  const v = criteria?.[key];
  return typeof v === "number" && Number.isFinite(v) ? v : FALLBACK_CRITERIA[key];
}

/** PM[deg] → 상태색 — 문턱은 인자로 받는다 (criteria 생략 시 폴백).
 * ≥pm_min_deg 양호 · pm_bad_deg~pm_min_deg 주의 · <pm_bad_deg 부족. */
export function marginColor(pm, criteria) {
  if (pm === "inf") return STATUS.ok;
  if (typeof pm !== "number") return STATUS.na; // null(NaN)·문자열 — 판정 불가
  if (pm < threshold(criteria, "pm_bad_deg")) return STATUS.bad;
  if (pm < threshold(criteria, "pm_min_deg")) return STATUS.warn;
  return STATUS.ok;
}

/** GM[dB] → 상태색 — 합격선 gm_min_db, 목표선 gm_good_db.
 *
 * 목표선은 튜너 목표(TuneTargets.gm_db)와도 같은 값이라 세 자리가 한 수치를
 * 공유한다 — 그래서 이 문턱을 화면이 따로 들고 있으면 안 된다. */
export function gmColor(gm, criteria) {
  if (gm === "inf") return STATUS.ok;
  if (typeof gm !== "number") return STATUS.na;
  if (gm < threshold(criteria, "gm_min_db")) return STATUS.bad;
  if (gm < threshold(criteria, "gm_good_db")) return STATUS.warn;
  return STATUS.ok;
}

/** 상태색 범례 문장 — 문턱을 문장에 박아 낸다 (수치를 두 번 적지 않는다). */
export function marginLegendText(criteria) {
  const t = (k) => threshold(criteria, k);
  return `상태색: PM ≥${t("pm_min_deg")}° 양호 · ${t("pm_bad_deg")}~${t("pm_min_deg")}° 주의 `
    + `· <${t("pm_bad_deg")}° 부족 · GM ≥${t("gm_good_db")} dB 양호 · `
    + `${t("gm_min_db")}~${t("gm_good_db")} dB 주의 · <${t("gm_min_db")} dB 부족 · `
    + "회색 = 트림 불가/판정 불가";
}

/** 트림 판정 → 비행 엔벨로프 셀 (01 §4.1 자동 판정 플래그 기반 근사).

우선순위: 불가(미수렴/잔차) > 실속 근접(α 여유) > 포화(추력·타면) > 가능.
실속 경계 테이블 기반 정밀 경계선은 공력 정본 확정 후 [백로그].
*/
export function trimEnvelopeCell(r) {
  if (!r.converged || r.flags.residual_ok === false) {
    return { kind: "infeasible", color: STATUS.na, text: "불가" };
  }
  if (r.flags.alpha_margin_ok === false) {
    return { kind: "stall", color: STATUS.bad, text: "실속≈" };
  }
  if (r.flags.saturation_ok === false) {
    return { kind: "saturated", color: STATUS.warn, text: "포화" };
  }
  return { kind: "ok", color: STATUS.ok, text: "가능" };
}

/** 시리즈 색 순환 팔레트 — 그룹 내 순번으로 배정 (애플 시스템 팔레트, 상태색과 동일 계열). */
export const SERIES_COLORS = ["#007aff", "#ff9500", "#ff3b30", "#34c759", "#af52de", "#5ac8fa"];

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
    } else if (g.mach.length !== t.axes.mach.length || g.mach.some((v, i) => v !== t.axes.mach[i])) {
      skipped.push({ name, reason: "그룹 내 mach 축 불일치 (차트가 x축 공유)" });
      continue;
    }
    g.series.push({ label, data: t.data, color: colors[g.series.length % colors.length] });
  }
  // 그룹은 생성한 테이블이 첫 시리즈로 반드시 들어감 — 빈 그룹 없음
  return { groups, skipped };
}

/** 시뮬 궤적 → 3면도 뷰 정의 (평면도·측면도·정면도).

평면 이름은 NED 축으로 부른다 (conventions §6 — 북·동·하방). 툴 내부 좌표가
NED이므로 XY/YZ/ZX로 부르면 어느 축이 어디인지 한 번 더 번역해야 한다.

연직 평면(N–D·E–D)의 세로축은 D 대신 고도 h = −D 를 위로 그린다 — 같은 평면을
부호만 뒤집어 본 것이고, 프로파일을 거꾸로 읽는 오독이 D 표기보다 훨씬 잦기
때문. 대신 라벨에 (= −D)를 명시해 규약을 숨기지 않는다.

equal(등축)은 N–E 평면만 true — 선회반경을 왜곡 없이 읽어야 하므로. 연직 평면은
수평 이동이 고도 변화보다 통상 한 자릿수 이상 커서 등축이면 직선으로 뭉개진다.
wpIdx: 웨이포인트 [n, e] 중 그 뷰의 가로축에 해당하는 성분 (N–E 평면은 원으로
직접 그리므로 null). 배열은 입력 참조 — 복사하지 않는다.
*/
export function planeViews(sig) {
  return [
    { key: "ne", title: "N–E 평면 (평면도)", equal: true, wpIdx: null,
      xs: sig.pe, ys: sig.pn, xLabel: "E [m]", yLabel: "N [m]" },
    { key: "nd", title: "N–D 평면 (측면도)", equal: false, wpIdx: 0,
      xs: sig.pn, ys: sig.h, xLabel: "N [m]", yLabel: "h [m] (= −D)" },
    { key: "ed", title: "E–D 평면 (정면도)", equal: false, wpIdx: 1,
      xs: sig.pe, ys: sig.h, xLabel: "E [m]", yLabel: "h [m] (= −D)" },
  ];
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

// ── 마진 맵 격자 레이아웃 (views/plots.js heatmapCanvas와 **공유**) ────────
// 그리기와 역매핑이 각자 상수를 들고 있으면 갈린다 — 갈려도 화면은 멀쩡해 보이고
// 클릭만 한 칸씩 어긋나므로 눈에 잘 안 띈다. 한 표를 양쪽이 읽는다.
export const HEATMAP_LAYOUT = {
  mL: 64, mT: 28, mR: 10, mB: 34,
  ch: 34,        // 행 높이
  cwMax: 90,     // 열 폭 상한 — 케이스가 적으면 격자가 width를 다 채우지 않는다
  gap: 3,        // 칸 사이 여백 (칠하는 폭은 cw-gap / ch-gap)
};

/** 마하 개수·캔버스 폭 → 열 폭. heatmapCanvas와 같은 식. */
export function heatmapCellWidth(nMach, width) {
  const { mL, mR, cwMax } = HEATMAP_LAYOUT;
  return Math.min(cwMax, (width - mL - mR) / Math.max(1, nMach));
}

/** 고도 개수 → 캔버스 **논리** 높이. 클릭 역변환이 이 값을 알아야 한다 —
 * canvas.clientHeight는 CSS로 축소된 뒤의 높이라 그걸 쓰면 y 배율이 1이 되어
 * 좁은 화면에서 세로 좌표가 안 풀린다(app.css의 max-width·height:auto). */
export function heatmapCanvasHeight(nAlt) {
  const { mT, mB, ch } = HEATMAP_LAYOUT;
  return mT + ch * nAlt + mB;
}

/** 캔버스 논리 좌표 → {mach, alt, entry} | null — 히트맵 칸 역매핑.
 *
 * 칸 사이 여백과 cwMax로 남는 우측 공백은 **null**이다. 가장 가까운 칸으로
 * 끌어붙이면 사용자가 안 누른 운용점의 선도가 뜬다. `entry`는 그 좌표에 케이스가
 * 없으면 null이지만 칸 자체는 존재하므로 mach·alt는 채워 보낸다(호출측이
 * "빈 칸을 눌렀다"와 "격자 밖을 눌렀다"를 구분할 수 있게). */
export function heatmapCellAt(pivot, x, y, { width = 560 } = {}) {
  const { machs, alts } = pivot;
  const { mL, mT, ch, gap } = HEATMAP_LAYOUT;
  const cw = heatmapCellWidth(machs.length, width);
  const dx = x - mL;
  const dy = y - mT;
  if (dx < 0 || dy < 0) return null;
  const i = Math.floor(dx / cw);
  const row = Math.floor(dy / ch);
  if (i >= machs.length || row >= alts.length) return null;
  if (dx - i * cw > cw - gap || dy - row * ch > ch - gap) return null; // 칸 사이 여백
  const alt = alts[alts.length - 1 - row]; // 고도는 위로 증가 (heatmapCanvas와 동일)
  const mach = machs[i];
  return { mach, alt, entry: pivot.at(mach, alt) };
}

// ── 주파수축 (보드선도) ───────────────────────────────────────────────────

/** linScale의 log10판 — 데케이드가 등간격이 된다. */
export function logScale(d0, d1, r0, r1) {
  const a = Math.log10(d0);
  const k = (r1 - r0) / ((Math.log10(d1) - a) || 1);
  return (v) => r0 + (Math.log10(v) - a) * k;
}

/** log 축 눈금 — 넓으면 10^k만, 좁으면 1·2·5×10^k까지 (선형 niceTicks의 log판). */
export function decadeTicks(min, max) {
  if (!(max > min)) return [min];
  const lo = Math.floor(Math.log10(min));
  const hi = Math.ceil(Math.log10(max));
  const decades = [];
  for (let k = lo; k <= hi; k += 1) decades.push(10 ** k);
  const inRange = (t) => t >= min * (1 - 1e-12) && t <= max * (1 + 1e-12);
  const plain = decades.filter(inRange);
  if (plain.length >= 4) return plain;
  const fine = [];
  for (let k = lo; k <= hi; k += 1) for (const m of [1, 2, 5]) fine.push(m * 10 ** k);
  const dense = fine.filter(inRange).sort((a, b) => a - b);
  return dense.length ? dense : plain.length ? plain : [min, max];
}

/** log-x 선형보간 — xs 오름차순, ys에 null 갭 허용. 범위 밖은 가장 가까운 끝값.
 *
 * 보드선도 교차 마커를 **곡선 위에** 찍는 데 쓴다: 교차 위치는 _level_crossings가
 * log-w 보간으로 찾았으므로 같은 자로 되읽어야 마커가 곡선에 앉는다. */
export function interpLogAt(xs, ys, x) {
  const n = xs.length;
  if (!n) return null;
  const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);
  const i = xs.findIndex((v) => v >= x);
  if (i < 0) return num(ys[n - 1]);   // x가 마지막 표본보다 크다 — 끝값
  if (i === 0) return num(ys[0]);
  const a = num(ys[i - 1]), b = num(ys[i]);
  if (a === null || b === null) return b ?? a;
  const lo = Math.log10(xs[i - 1]), hi = Math.log10(xs[i]);
  return a + (b - a) * ((Math.log10(x) - lo) / ((hi - lo) || 1));
}

/** 보드 응답 → 그리기용 시리즈 {w, mag, phase} — 비유한 dB는 null 갭.
 *
 * to_jsonable이 ±inf를 문자열 "inf"/"-inf"로, nan을 null로 보낸다. 그것을 0으로
 * 채우면 없는 교차가 생기고 있는 교차가 사라진다 — 끊어 그린다. */
export function bodeSeries(data) {
  const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);
  return {
    w: data.w,
    mag: data.mag_db.map(num),
    phase: data.phase_deg.map(num),
  };
}
