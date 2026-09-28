/** 게인 스케줄 **자리 선택** 로직 — 어떤 게인에 테이블을 붙일지. DOM·통신 없음.

값 편집(테이블 셀)과 다른 층이다. 값은 게인을 바꾸지만, 자리는 **형상**을 바꾼다 —
스케줄한 자리는 탑재 C에 룩업 + 스케줄 변수 필터 상태가 생기고, 뺀 자리는 설계점
상수로 접힌다. 그래서 자리를 건드리면 지문이 움직인다.

자리 목록·설계 상수·불가 사유는 전부 서버(GET /gains/catalog)가 준다 — 정본은
엔진 `fcl/graphs.py` SCHEDULABLE이고, 여기서 목록을 다시 적으면 "켤 수 있다"고
보여 준 자리가 실행 시점에 터진다. 이 파일이 하는 일은 고른 것을 요청·스토어
계약으로 옮기는 것뿐이다.
*/

import { checksSummary } from "./evaluate.js";
import { valueAt } from "./gainsync.js";

/** 격자의 열 — 불가 자리도 칸은 있어야 축마다 열이 어긋나지 않는다. */
export const GAIN_KEYS = ["kp", "ki", "k_rate"];

/** 그룹 표시 이름. 식별자(pitch)는 게인 이름의 일부라 그대로 두고 한글을 덧붙인다. */
export const GROUP_LABEL = {
  pitch: "피치", roll: "롤", yaw: "요",
  alt: "고도", speed: "속도", heading: "헤딩",
};

/** 카탈로그 → 그룹별 행 [{group, label, cells}]. 서버가 준 그룹 순서를 유지한다. */
export function slotRows(catalog) {
  const order = [];
  const byGroup = new Map();
  for (const s of catalog?.slots ?? []) {
    if (!byGroup.has(s.group)) {
      byGroup.set(s.group, new Map());
      order.push(s.group);
    }
    byGroup.get(s.group).set(s.key, s);
  }
  return order.map((group) => ({
    group,
    label: GROUP_LABEL[group] ?? group,
    cells: GAIN_KEYS.map((key) => byGroup.get(group).get(key) ?? null),
  }));
}

/** 서버가 지금 켜져 있다고 한 자리 — 처음 들어왔을 때의 선택. */
export function defaultSelection(catalog) {
  return (catalog?.slots ?? []).filter((s) => s.scheduled).map((s) => s.name);
}

/** 자리 토글 → 새 선택 배열. 불가 자리는 무시한다 (체크박스가 없어야 정상이지만,
 * 없는 것과 눌러도 안 되는 것을 화면 밖에서 한 번 더 막는다). */
export function toggleSlot(catalog, selected, name) {
  const slot = (catalog?.slots ?? []).find((s) => s.name === name);
  const cur = [...new Set(selected ?? [])];
  if (!slot || !slot.available) return cur;
  return cur.includes(name) ? cur.filter((n) => n !== name) : [...cur, name];
}

/** 고른 자리만 남긴 테이블 dict — **키 집합이 곧 스케줄 대상**이다.
 * 카탈로그 순서를 유지해 같은 선택이면 같은 요청 본문이 나온다(캐시 키가 된다). */
export function appliedTables(catalog, selected) {
  const want = new Set(selected ?? []);
  const out = {};
  for (const s of catalog?.slots ?? []) {
    if (s.available && s.table && want.has(s.name)) out[s.name] = s.table;
  }
  return out;
}

/** 켜지 않은 자리 — 스케줄을 빼면 이 설계 상수로 굳는다. */
export function fixedGains(catalog, selected) {
  const want = new Set(selected ?? []);
  return (catalog?.slots ?? [])
    .filter((s) => s.available && !want.has(s.name))
    .map((s) => ({ name: s.name, design: s.design, unit: s.unit, param: s.param }));
}

/** 켰지만 설계값이 0이라 테이블이 전부 0인 자리 — 편집 전엔 아무 효과가 없다.
 * (요축 ki·헤딩 ki가 그렇다. 켜 놓고 "왜 안 변하지"가 되는 자리다.) */
export function zeroTables(catalog, selected) {
  const want = new Set(selected ?? []);
  return (catalog?.slots ?? [])
    .filter((s) => s.available && want.has(s.name) && s.design === 0)
    .map((s) => s.name);
}

/** 선택 상태 한 줄 요약. */
export function schedSummary(catalog, selected) {
  const slots = (catalog?.slots ?? []).filter((s) => s.available);
  if (!slots.length) return "";
  const want = new Set(selected ?? []);
  const on = slots.filter((s) => want.has(s.name)).length;
  if (on === 0) return `스케줄 없음 — ${slots.length}자리 전부 설계점 고정`;
  return `${slots.length}자리 중 ${on}개 스케줄 · ${slots.length - on}개 설계점 고정`;
}

/** 자리마다 다른 축을 **합집합 축**으로 정렬 — 조회 함수는 그대로 보존된다.
 *
 * 자동 설계 확정본(M17)은 자리마다 breakpoint가 다르다 — 적합이 자리별로 독립
 * 실행되기 때문이다(pitch.kp 6점, roll.kp 15점처럼). 반면 이 탭의 표는 행=축
 * 격자·열=자리라 **공통 축**이 필요하다.
 *
 * 합집합에는 원래 격자점이 전부 남으므로 **그 점들의 값은 정확히 보존되고**, 새로
 * 생긴 점은 그 구간의 보간값이라 조회 함수가 수학적으로 같다(범위 밖은 양쪽 다
 * clip). 구간 안쪽 질의는 보간이 한 번 더 끼어 마지막 비트가 갈릴 수 있다 —
 * 게인 값에서 1 ulp는 무의미하지만, "비트 단위로 같다"고는 말하지 않는다.
 *
 * 반환 {tables, axis, aligned} — 이미 축이 같으면 원본 참조를 그대로 돌려준다
 * (셀 편집이 slot.table 참조를 공유하는 경로를 끊지 않기 위해).
 * 축이 없는 표가 섞이면 null (호출자가 사유를 표시한다). */
export function alignTables(tables, axis) {
  const names = Object.keys(tables ?? {});
  if (!names.length) return { tables: {}, axis: [], aligned: false };
  const grids = names.map((n) => tables[n]?.axes?.[axis]);
  if (grids.some((g) => !Array.isArray(g) || !g.length)) return null;
  const union = [...new Set(grids.flat())].sort((a, b) => a - b);
  const same = grids.every(
    (g) => g.length === union.length && g.every((v, i) => v === union[i]),
  );
  if (same) return { tables, axis: union, aligned: false };
  const out = {};
  for (const name of names) {
    const t = tables[name];
    out[name] = {
      axes: { ...t.axes, [axis]: [...union] },
      data: union.map((c) => valueAt(t, axis, c)),
      extrapolate: t.extrapolate ?? "clip",
    };
  }
  return { tables: out, axis: union, aligned: true };
}

/** 축이 없는 표 [{name, axes}] — alignTables가 null을 낸 **사유**. 이 화면(과 문서 스키마 law.gain_tables)은
 * 마하 축 표만 받는다 — 자동 설계가 고도 축으로 적합한 확정본이 오면 어느 자리가 어느 축인지를 그대로
 * 말해야 한다(「축이 없는 표가 섞였다」만으로는 무엇을 고칠지 모른다). axes는 그 표가 가진 축 이름들. */
export function axisMismatch(tables, axis) {
  return Object.entries(tables ?? {})
    .filter(([, t]) => !Array.isArray(t?.axes?.[axis]) || !t.axes[axis].length)
    .map(([name, t]) => ({ name, axes: Object.keys(t?.axes ?? {}) }));
}

/** axisMismatch → 한 줄 사유. 비었으면 null. */
export function axisMismatchText(mismatch, axis) {
  if (!mismatch?.length) return null;
  const list = mismatch.map((m) => `${m.name}(${m.axes.length ? `${m.axes.join("·")} 축` : "축 없음"})`);
  return `${list.join(", ")} — '${axis}' 축이 아닌 표라 이 화면에 세울 수 없다(게인 탭·문서 확정 표는 `
    + `'${axis}' 축만 받는다)`;
}

/** 근사 곡선 구간 경계 기본값 — 스케줄 표의 **상한 클립이 풀리는 첫 격자점**들 (문서 스케줄에서).
 *
 * 규칙 표 K(M) = K0·min((M_design/M)², 상한)은 상한에 걸린 평탄부와 동압 곡선 사이에 꺾임이 있다.
 * 다항 근사는 꺾임을 한 구간에 품으면 잔차가 커지므로 거기에 경계를 두는 것이 기본값이다(종전 "0.3"은
 * 1200 kg 기체 롤 상한의 꺾임이었다 — 다른 기체에서는 뜻이 없다). 표마다 앞머리의 평탄부(첫 값과 같은
 * 점들) 다음 점을 모은다 — 평탄부가 없거나 표 전체가 평탄(0 표 등)이면 그 표는 경계를 내지 않는다.
 * 격자점이라 구간마다 점이 하나 이상 들고(polyfit 조건), 축의 첫·끝 점은 경계가 될 수 없어 뺀다. */
export function scheduleKnees(tables, axis) {
  const out = new Set();
  for (const t of Object.values(tables ?? {})) {
    const grid = t?.axes?.[axis];
    const data = t?.data;
    if (!Array.isArray(grid) || !Array.isArray(data) || grid.length !== data.length || grid.length < 3) continue;
    let i = 1;
    while (i < data.length && data[i] === data[0]) i += 1;
    if (i > 1 && i < data.length - 1) out.add(grid[i]);
  }
  return [...out].sort((a, b) => a - b);
}

/** 튜닝 지표 카드 한 줄 — 하드 게이트·나머지 판정·깊이 (게인 탭 카드 스트립과 쇼케이스 보고가 같은 줄). */
export function evalStripLine(m) {
  const agg = m?.aggregate;
  return (agg?.hard_fail == null ? "하드 게이트 판정 보류(케이스 0건)"
    : agg.hard_fail ? `하드 게이트 위반 ${agg.hard_fails.length}건 — Fail`
    : "하드 게이트 전부 통과")
    + ` · ${checksSummary(m?.checks)} · depth=${m?.depth}`;
}

/** 스토어에 넣을 값 — {tables, scheduleOff}.
 *
 * **전부 끔은 "편집 없음"과 다른 형상이다.** 전자는 스케줄이 아예 없는 형상이고
 * 후자는 서버의 설계 기본(6자리)이다. 빈 dict로는 그 차이를 못 보낸다 — 서버가
 * 빈 dict를 422로 막고(조용한 무스케줄 방지), 필드를 생략하면 설계 기본이 된다.
 * 그래서 별도 신호를 함께 낸다. */
export function storePayload(catalog, selected) {
  const tables = appliedTables(catalog, selected);
  const off = Object.keys(tables).length === 0;
  return { tables: off ? null : tables, scheduleOff: off };
}
