/** 전면 배치 뼈대의 판단부 — 칩·서랍의 상태 계산 (DOM 없음).
 *
 * 이 앱의 탭 규약은 하나다: **주 그림은 카드 밖 전면에, 나머지는 눌렀을 때만.**
 * 블록도 최상위(.bd .canvas-wrap.top)가 먼저 그렇게 했고 영향성·가상환경이 따랐다.
 * 그 배치를 탭마다 베끼면 같은 레이아웃이 열 벌이 되므로(02 §5.5) 판단은 여기,
 * 조립은 views/stage.js 한 곳에 둔다.
 *
 * 여기 있는 것은 **DOM이 없어도 답이 정해지는 질문**들이다:
 *   - 지금 열려야 하는 서랍은 무엇인가 (숨은 칩이 열려 있으면?)
 *   - 칩에 배지를 달아야 하는가, 단다면 몇인가
 *   - 칩을 분류로 묶으면 어떤 줄이 서는가
 * 그래서 테스트가 가능하고, 실제로 이 파일이 막는 사고는 전부 **눌러도 안 열리거나
 * 여는 버튼 없이 열려 있는 서랍**이다 — 화면에서는 원인이 안 보이는 종류다.
 */

/** 셀 수 없는 것을 0으로 위장하지 않는다 — null·undefined·NaN은 배지 자체가 없다.
 *
 *  0도 배지를 달지 않는다: "0건"을 띄우면 사용자는 **센 결과가 0**이라고 읽는데,
 *  아직 안 센 것과 세어서 0인 것이 화면에서 같아진다. 셌다는 사실을 말해야 하는
 *  칩은 count에서 문자열을 돌려주면 된다 (예: "0/15"). */
export function badgeOf(count) {
  if (typeof count === "string") return count || null;
  if (typeof count !== "number" || !Number.isFinite(count) || count === 0) return null;
  return String(count);
}

const isHidden = (d) => (typeof d.hidden === "function" ? !!d.hidden() : !!d.hidden);
const countOf = (d) => (typeof d.count === "function" ? d.count() : d.count ?? null);

/** 실제로 열려야 하는 서랍 키.
 *
 *  **없는 키·숨은 키는 열지 않는다.** 조건부 칩(경고 등)은 조건이 사라지면 사라지는데,
 *  그때 서랍만 남으면 화면에 여는 버튼도 닫는 버튼도 없는 판이 떠 있게 된다. */
export function resolveOpen(defs, want) {
  if (want == null) return null;
  const d = (defs ?? []).find((x) => x.key === want);
  return d && !isHidden(d) ? want : null;
}

/** 칩을 눌렀을 때의 다음 상태 — 같은 칩이면 닫는다(토글), 다른 칩이면 그쪽으로.
 *
 *  한 번에 하나만 연다. 여러 개를 동시에 열 수 있게 하면 결국 세로로 쌓인 패널
 *  더미가 되고, 그건 이 배치가 없애려던 바로 그 화면이다. */
export function toggleOpen(defs, current, key) {
  return resolveOpen(defs, current === key ? null : key);
}

/** 칩 한 줄의 표시 모델 — 조립부는 이 배열을 그대로 그린다.
 *
 *  `group`이 있으면 **바뀌는 지점에만** 라벨을 세운다(startsGroup): 칩마다 분류를
 *  붙이면 줄이 두 배로 길어져 분류가 오히려 안 읽힌다. */
export function chipModels(defs, open) {
  const live = resolveOpen(defs, open);
  let prev = null;
  return (defs ?? []).map((d) => {
    const hidden = isHidden(d);
    const startsGroup = !hidden && d.group != null && d.group !== prev;
    if (!hidden) prev = d.group ?? null;
    return {
      key: d.key,
      label: d.label,
      title: d.title ?? null,
      group: d.group ?? null,
      startsGroup,
      hidden,
      badge: hidden ? null : badgeOf(countOf(d)),
      expanded: !hidden && d.key === live,
    };
  });
}

/** 지금 열린 서랍의 정의 (없으면 null) — 조립부가 build()를 부를 대상. */
export function openDef(defs, open) {
  const live = resolveOpen(defs, open);
  return live == null ? null : (defs ?? []).find((d) => d.key === live) ?? null;
}
