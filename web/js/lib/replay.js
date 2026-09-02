/** 재생 유틸 (02 §8 5단계) — stride 산정·모드 구간·극값 (순수 로직, 테스트 대상). */

export function strideFor(nTotal, target = 1500) {
  return Math.max(1, Math.ceil(nTotal / target));
}

/** 엔벨로프 플래그 이름(한국어) — 엔진 flags 키와 1:1 (simulator._envelope). */
export const FLAG_LABEL = {
  alpha: "α", beta: "β", mach: "마하", altitude: "고도",
};

/** 실제로 뜬 플래그 이름만 나열 — any_flag 하나로 뭉뚱그리면 기준면 이탈(고도)이
DB 유효범위 이탈로 오독된다. 미정의 키는 원래 이름으로 통과(엔진 확장에 안전). */
export function flaggedNames(env) {
  const hit = Object.entries(env?.flags ?? {})
    .filter(([, arr]) => Array.isArray(arr) && arr.some(Boolean))
    .map(([k]) => FLAG_LABEL[k] ?? k);
  return hit.length ? hit.join("·") : "—";
}

/** 모드 문자열 시계열 → 연속 구간 [{mode, i0, i1}] (i1 배타) — 배경 밴드용. */
export function modeSpans(modes) {
  const spans = [];
  for (let i = 0; i < modes.length; i += 1) {
    if (!spans.length || spans[spans.length - 1].mode !== modes[i]) {
      if (spans.length) spans[spans.length - 1].i1 = i;
      spans.push({ mode: modes[i], i0: i, i1: modes.length });
    }
  }
  return spans;
}

/** null(NaN 직렬화) 무시 극값 — 전부 null이면 [0, 1] 안전 기본. */
export function extent(arr) {
  let lo = Infinity;
  let hi = -Infinity;
  for (const v of arr) {
    if (typeof v !== "number") continue;
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  return lo <= hi ? [lo, hi] : [0, 1];
}

/** 재생 응답 → 이착륙 요약 [{label, value, note}] — 단계가 없으면 **행 자체가 없다**.
 *
 * 0으로 채우면 착륙하지 않은 런이 "접지 강하율 0 = 완벽한 착륙"으로 읽힌다.
 * 사출 하중은 **판정 기준이 없어** 값과 함께 "미판정"을 낸다 — 구조 한계표의
 * n_limit_pos 6.0은 Nz라 종방향 34 g를 판정할 수 없고, n_x_launch는 아직 [TBD]다.
 * 판정 불가를 통과로 위장하지 않는다는 규약이 화면에 나오는 자리다.
 */
export function landingSummary(body) {
  const ph = body?.meta?.phases;
  const sig = body?.signals ?? {};
  const t = body?.t ?? [];
  if (!ph) return [];
  const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);
  const rows = [];
  const idxAt = (tv) => {
    if (typeof tv !== "number" || !t.length) return null;
    let best = 0;
    for (let i = 1; i < t.length; i += 1) {
      if (Math.abs(t[i] - tv) < Math.abs(t[best] - tv)) best = i;
    }
    return best;
  };

  if (typeof ph.launch_exit_t === "number") {
    const gx = Array.isArray(sig.launch_gx)
      ? sig.launch_gx.reduce((m, x) => (typeof x === "number" && x > m ? x : m), 0) : null;
    rows.push({
      label: "레일 이탈",
      value: `${ph.launch_exit_t.toFixed(3)} s`,
      note: gx
        ? `사출 ${gx.toFixed(1)} g — 종방향 발사하중 한계 미정 [TBD], 판정 불가`
        : "사출 하중 미계측",
      unjudged: Boolean(gx),
    });
  }
  const k = idxAt(ph.touchdown_t);
  if (k !== null) {
    // 강하율·속도는 **엔진이 전 해상도에서 잰 값**을 그대로 쓴다. 여기서 신호로
    // 다시 계산하면 재생 응답이 stride로 솎여 있어 다른 수가 나온다 — 접지 직후
    // 승강률은 0.02 s에 −0.98 → −0.83으로 움직이고, 라이브에서 실제로 −0.98을
    // −0.74로 표시했다. 화면이 조용히 다른 접지를 말하는 자리였다.
    const hdot = num(ph.td_sink_rate);
    const V = num(ph.td_speed);
    rows.push({
      label: "접지",
      value: `${ph.touchdown_t.toFixed(2)} s`,
      note: [
        hdot === null ? "강하율 미계측" : `강하율 ${hdot.toFixed(2)} m/s`,
        V === null ? null : `속도 ${V.toFixed(1)} m/s`,
      ].filter(Boolean).join(" · "),
    });
  }
  // 접지 **지점** — 거리만으로는 활주로에 내렸는지 알 수 없다.
  //
  // 아래 "정지" 행은 접지→정지 직선거리를 활주로 길이와 견주는데, 그것은 **미끄럼이
  // 짧다**는 뜻일 뿐이다. 기본 미션은 발사대에서 떠서 7 km 북쪽에 내리는데도 그 행만
  // 보면 "869 m / 활주로 1205 m"라 활주로에 선 것처럼 읽혔다.
  //
  // 활주로 기하는 화면과 같은 규약을 쓴다 — 원점에서 heading 방향 length 구간
  // (world/src/scene/SceneController.ts 활주로 그리기 — 옛 renderer-three.js에서 왔다).
  // 두 가지는 **폭을 몰라도 단정할 수 있다**:
  //   ① 축방향이 0~length 밖이면 밖이다
  //   ② |횡편차| > length면 밖이다 — 활주로가 자기 길이보다 넓을 수는 없다
  // 둘 다 아니면 단정하지 않는다. 활주로 **폭이 결과에 없어** 그 안쪽을 가릴 수단이
  // 없기 때문이고, 그래서 통과가 아니라 미판정으로 낸다.
  //
  // 방위·길이가 없으면 **행 자체를 내지 않는다**. 방위를 0으로 메우면 "활주로 축"을
  // 지어내고 방위를 알 때와 똑같은 확신으로 거리를 찍게 되며, 길이 0은 거의 모든
  // 접지를 "밖"으로 만든다 — 이 파일의 "0으로 채우지 않는다" 규약과 같은 자리다.
  const rw = body?.meta?.runway;
  if (k !== null && rw) {
    const hdg = num(rw.heading);
    const len = num(rw.length);
    const pn = num(sig.pn?.[k]);
    const pe = num(sig.pe?.[k]);
    if (hdg !== null && len !== null && len > 0 && pn !== null && pe !== null) {
      const along = pn * Math.cos(hdg) + pe * Math.sin(hdg);
      const cross = -pn * Math.sin(hdg) + pe * Math.cos(hdg);
      const outside = along < 0 || along > len || Math.abs(cross) > len;
      // 재생 응답은 stride로 솎여 있어 표본 간격이 순항 속도에서 10 m를 넘는다
      // (strideFor 14 → 0.14 s → 88 m/s에서 12.3 m). 1 m 단위로 찍으면 갖지 않은
      // 분해능을 주장한다 — 엔진이 전 해상도에서 재어 meta.phases에 실어 주면
      // (강하율이 그렇게 한다) 그때 자릿수를 올린다.
      // 로캘을 못박는다(world.js와 같은 규약). 실행 환경 기본 로캘도 쉼표를 쓰는
      // 경우가 많아 **테스트로는 구별되지 않는다** — 변이시험에서 0건이 뜬다.
      const r10 = (x) => Math.round(x / 10) * 10;
      const signed = (x) => `${x >= 0 ? "+" : ""}${r10(x).toLocaleString("ko-KR")}`;
      rows.push({
        label: "접지 지점",
        value: `활주로 축 ${signed(along)} m`,
        note: `횡편차 ${signed(cross)} m · `
          + (outside
            ? `활주로 구간(0~${Math.round(len).toLocaleString("ko-KR")} m) 밖이다`
            : "구간 안이지만 활주로 폭이 결과에 없어 판정 불가"),
        over: outside,
        // 시단 **앞**에 내린 경우도 있어 "활주로 초과"는 틀린 말이 된다
        overLabel: along < 0 ? "시단 못 미침" : "활주로 밖",
        ...(outside ? {} : { unjudged: true }),
      });
    }
  }

  const j = idxAt(ph.stop_t);
  if (j !== null && k !== null) {
    const dn = (sig.pn?.[j] ?? 0) - (sig.pn?.[k] ?? 0);
    const de = (sig.pe?.[j] ?? 0) - (sig.pe?.[k] ?? 0);
    const dist = Math.hypot(dn, de);
    const rw = body?.meta?.runway?.length;
    rows.push({
      label: "정지",
      value: `${ph.stop_t.toFixed(2)} s`,
      note: `접지→정지 직선거리 ${Math.round(dist)} m`
        + (typeof rw === "number"
          // 마크다운 **는 여기서 글자 그대로 나온다 — note는 텍스트 노드로 들어간다
          // (views/sim.js). 강조는 이 행이 이미 내는 over 배지가 맡는다
          ? ` / 활주로 ${Math.round(rw)} m${dist > rw ? " — 넘어섰다" : ""}` : ""),
      over: typeof rw === "number" && dist > rw,
    });
  }
  return rows;
}
