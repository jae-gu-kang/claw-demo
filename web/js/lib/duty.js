/** 타면 사용 통계 표시 계층 — 엔진 duty 리포트 → 화면에 올릴 값. DOM 무접촉.

수치는 전부 엔진(claw/analysis/duty.py)이 전 해상도 원본에서 낸다. 여기서 하는
일은 **표시 변환과 표시 정책**뿐이다.

**각은 여기서만 deg가 된다.** 내부·저장·전송은 SI+rad 규약(03 §3) 그대로고,
사람이 읽는 자리에서만 도로 바꾼다 — 0.35 rad보다 20°가 "타면을 얼마나 꺾었나"를
즉시 말해 주기 때문. `lib/wiresignals.js`와 같은 정책.

**판정 불가와 0은 다르다.** 한계가 알려지지 않은 결과(구 결과·작동기 미장착)는
포화율 0이 아니라 "판정 불가"로 나와야 한다. 0으로 보이면 "한계에 한 번도 안
닿았다"는 **적극적인 거짓말**이 된다 — 실제로는 닿았는지조차 모르는 상태다.
*/

export const DEG = 180 / Math.PI;

/** 유한 수치만 통과 — null·NaN·"inf" 문자열(serialize 정책)은 전부 미상. */
function num(v) {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

/** rad → deg (표시 전용). 미상은 null 유지 — 0으로 채우지 않는다. */
export function toDeg(v) {
  const n = num(v);
  return n == null ? null : n * DEG;
}

export function fmtDeg(v, digits = 2) {
  const d = toDeg(v);
  return d == null ? "—" : `${d.toFixed(digits)}°`;
}

export function fmtRateDeg(v, digits = 1) {
  const d = toDeg(v);
  return d == null ? "—" : `${d.toFixed(digits)}°/s`;
}

function fmtSec(v, digits = 2) {
  const n = num(v);
  return n == null ? "—" : `${n.toFixed(digits)} s`;
}

function fmtPct(v, digits = 1) {
  const n = num(v);
  return n == null ? "—" : `${(n * 100).toFixed(digits)}%`;
}

/** "값 @ 시각" — 최대값은 언제 그랬는지가 붙어야 시계열에서 되짚을 수 있다. */
function withTime(text, t) {
  const n = num(t);
  return text === "—" || n == null ? text : `${text} @ ${n.toFixed(1)} s`;
}

/** 포화율 → 심각도. 포화는 조금이라도 있으면 볼 것이고(warn), 1%를 넘으면
설계가 조종권이나 작동기 속도에 기대고 있다는 뜻이다(bad). 미상은 na. */
export function severity(frac) {
  const n = num(frac);
  if (n == null) return "na";
  if (n <= 0) return "ok";
  return n < 0.01 ? "warn" : "bad";
}

/** 포화 집계 → {text, severity}. null(한계 미상)은 "0초"가 아니라 "판정 불가". */
function satCell(sat) {
  if (!sat) return { text: "판정 불가", severity: "na" };
  const frac = num(sat.frac) ?? 0;
  if (frac <= 0) return { text: "없음", severity: "ok" };
  // 시간·비율만으로는 "짧게 여러 번"과 "길게 한 번"이 구분되지 않는다 —
  // 앞은 리밋사이클 징후, 뒤는 조종권 부족이라 처방이 다르다
  return {
    text: `${fmtSec(sat.time)} · ${fmtPct(frac)} · ${sat.events ?? 0}회`
      + ` · 최장 ${fmtSec(sat.longest)}`,
    severity: severity(frac),
  };
}

/** 리포트 → 요약 표 행 (표시 문자열까지 확정 — "—" 정책을 한곳에 모은다). */
export function channelRows(report) {
  return (report?.channels ?? []).map((c) => {
    const s = c.stats ?? {};
    return {
      key: c.key,
      label: c.label,
      mean: fmtDeg(s.mean),
      std: fmtDeg(s.std),
      p95: fmtDeg(c.exceedance?.p95),
      max: withTime(fmtDeg(s.max_abs), s.max_abs_t),
      maxRate: withTime(fmtRateDeg(s.max_rate_abs), s.max_rate_abs_t),
      usage: fmtPct(s.usage),
      posSat: satCell(c.pos_sat),
      rateSat: satCell(c.rate_sat),
      reversals: c.reversals
        ? `${c.reversals.count}회 (${(num(c.reversals.per_min) ?? 0).toFixed(1)}/분)`
        : "—",
      // 반전 횟수는 불감대에 민감하고 불감대는 rate 한계에 비례한다 —
      // 한계가 다른 두 런의 횟수를 나란히 놓으면 같은 척도가 아니다
      reversalsHint: c.reversals
        ? `불감대 ${fmtRateDeg(c.reversals.deadband)} 초과분만 계수`
        : "판정 불가",
    };
  });
}

/** 히스토그램 → 막대 [{x0, x1, time, frac}] (deg). 경계는 n+1개, 막대는 n개. */
export function histBars(hist) {
  const edges = hist?.edges ?? [];
  const time = hist?.time ?? [];
  const out = [];
  for (let i = 0; i < time.length && i + 1 < edges.length; i += 1) {
    out.push({
      x0: (num(edges[i]) ?? 0) * DEG,
      x1: (num(edges[i + 1]) ?? 0) * DEG,
      time: num(time[i]) ?? 0,
      frac: num(hist?.frac?.[i]) ?? 0,
    });
  }
  return out;
}

/** 누적 초과 → {level[deg], time[s]} — 선 차트에 그대로 넣을 두 배열. */
export function exceedanceSeries(ex) {
  const level = (ex?.level ?? []).map((v) => (num(v) ?? 0) * DEG);
  const time = (ex?.time ?? []).map((v) => num(v));
  return { level, time };
}

/** 작동기 능력 상자 (deg·deg/s) — 모르는 변은 null이라 그리지 않는다.

한계를 임의값으로 채워 그리면 "여기까지가 능력"이라는 **없는 정보**를 그리게 된다. */
export function capabilityBox(channel) {
  const rate = toDeg(channel?.rate_max);
  return {
    xLo: toDeg(channel?.pos_lo),
    xHi: toDeg(channel?.pos_hi),
    yLo: rate == null ? null : -rate,
    yHi: rate,
  };
}

/** 밀도 격자 — 경계만 deg 변환, 셀 값은 체류 시간[s]이라 그대로. */
export function densityView(density) {
  return {
    xEdges: (density?.x_edges ?? []).map((v) => (num(v) ?? 0) * DEG),
    yEdges: (density?.y_edges ?? []).map((v) => (num(v) ?? 0) * DEG),
    time: density?.time ?? [],
  };
}

/** 모드 선택지 — 전체가 먼저, 각 모드에 체류 시간을 붙인다 (짧은 구간의
통계는 표본이 적다는 것을 고르기 전에 알 수 있게). */
export function modeOptions(report) {
  const total = num(report?.t_total);
  const opts = [{ value: "", label: `전체${total == null ? "" : ` (${total.toFixed(1)} s)`}` }];
  for (const m of report?.modes ?? []) {
    const t = num(report?.mode_time?.[m]);
    opts.push({ value: m, label: t == null ? m : `${m} (${t.toFixed(1)} s)` });
  }
  return opts;
}

/** 채널 × 모드 선택 → 그릴 것들. 모드별로는 히스토그램·통계·포화만 있고
초과곡선·밀도는 없다(엔진이 전체에 대해서만 낸다) — null로 정직하게 비운다.

없는 모드는 조용히 전체로 넘어가지 않고 null: 선택과 다른 것이 그려지면
"이 모드에서는 안 썼다"가 "전체에서 이만큼 썼다"로 오독된다. */
export function viewOf(channel, mode) {
  if (!channel) return null;
  if (!mode) {
    return {
      mode: "",
      time: num(channel.hist?.time?.reduce?.((a, b) => a + (num(b) ?? 0), 0)),
      hist: channel.hist,
      stats: channel.stats,
      exceedance: channel.exceedance,
      density: channel.density,
      posSat: channel.pos_sat,
      rateSat: channel.rate_sat,
    };
  }
  const m = channel.by_mode?.[mode];
  if (!m) return null;
  return {
    mode,
    time: num(m.time),
    hist: m.hist,
    stats: m.stats,
    exceedance: null,
    density: null,
    posSat: m.pos_sat,
    rateSat: m.rate_sat,
  };
}
