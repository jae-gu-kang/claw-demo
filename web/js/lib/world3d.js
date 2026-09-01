/** 3D 월드 수치 계층 — 신호 → 궤적 기하·표본·시점 입력 (DOM 무접촉, 테스트 대상).

views/world.js에서 뺀 판단들이다. 뺀 이유가 분명하다: **결측 정책이 여기 모여 있어야
테스트가 잡는다.** 처음에 이 셋이 뷰에 흩어져 있을 때 궤적 선은 조심스럽게 끊으면서
기체 위치는 `?? 0`으로 메워, 결측 프레임에서 기체가 NED 원점으로 순간이동하고 후방차분
속도가 66 km/s로 튀는 상태였다(리뷰 지적). 같은 물음에 두 답이 있으면 언젠가 갈린다.

## 결측 규약

시뮬 결과의 비유한값은 직렬화에서 null이 된다(M13 serialize). 이 층은 그것을 **끝까지
null로 전한다** — 0으로 메우지 않고, 호출측이 "그리지 않는다"를 고를 수 있게 한다.
*/

/** NED [n, e, d] → 렌더러 월드 [x, y, z] — **내장 어댑터가 쓰는 축 사상의 정본**.
 *
 *     x = e,  y = −d,  z = −n     (행렬식 +1 — 오른손 좌표계 보존)
 *
 * 왜 lib에 있나: 삼각형 감김이 옳은지는 이 사상 아래에서만 판정할 수 있다. 사상을 어댑터에
 * 두고 테스트가 그것을 지역에서 다시 선언하면, 어댑터가 바뀌어도 테스트는 옛 사상 기준으로
 * 계속 초록이다(리뷰 지적). 여기 한 곳에 두고 어댑터와 테스트가 **같이 읽는다**.
 *
 * 다른 렌더러가 다른 축 규약(예: z-up)을 고른다면 그 어댑터가 자기 사상과 감김을 함께
 * 책임진다 — 그때 이 함수는 내장 어댑터의 것으로 남는다.
 */
export function nedToRender(n, e, d) {
  return [e, -d, -n];
}

/** 궤적 기하 — {points: Float32Array(NED 평탄), breaks: number[]}.
 *
 * 결측 자리는 **NaN**으로 채운다(0이 아니라). 0으로 두면 끊기 로직에 구멍이 하나만 생겨도
 * 원점에서 뻗어 나오는 그럴듯한 선분이 되는데, NaN이면 그런 선분이 만들어질 수 없다.
 * `breaks`는 결측 표본의 인덱스이고, 소비자는 **양 끝 중 하나라도** breaks면 그 구간을
 * 그리지 않아야 한다(한쪽만 보면 나가는 구간이 살아남는다).
 */
export function trackPoints(signals, n) {
  const points = new Float32Array(n * 3);
  const breaks = [];
  for (let i = 0; i < n; i++) {
    const p = sampleAt(signals, i);
    if (p === null) {
      breaks.push(i);
      points[3 * i] = NaN;
      points[3 * i + 1] = NaN;
      points[3 * i + 2] = NaN;
      continue;
    }
    points[3 * i] = p[0];
    points[3 * i + 1] = p[1];
    points[3 * i + 2] = p[2];
  }
  return { points, breaks };
}

/** 표본 i의 NED 위치 [n, e, d] — 하나라도 결측이면 **null**(0으로 메우지 않는다). */
export function sampleAt(signals, i) {
  const n = signals.pn?.[i];
  const e = signals.pe?.[i];
  const h = signals.h?.[i];
  if (!Number.isFinite(n) || !Number.isFinite(e) || !Number.isFinite(h)) return null;
  return [n, e, -h]; // h는 상방 +, D는 하방 +
}

/** 표본 i의 자세 (φ, θ, ψ) [rad] — 하나라도 결측이면 **null**.
 *
 * 위치와 같은 규약이다. `?? 0`으로 메우면 없는 수평비행을 지어내고, 그 쿼터니언이
 * 온보드·자세 관측 시점을 몬다 — 카메라가 있지도 않은 자세로 세상을 본다.
 */
export function attitudeAt(signals, i) {
  const phi = signals.phi?.[i], theta = signals.theta?.[i], psi = signals.psi?.[i];
  if (!Number.isFinite(phi) || !Number.isFinite(theta) || !Number.isFinite(psi)) return null;
  return [phi, theta, psi];
}

/** 후방차분 NED 속도 [m/s] — 양 끝 표본이 성하고 dt > 0일 때만. 아니면 null.
 *
 * 신호에 NED 속도가 없어 위치 차분으로 구한다(경로 진행 방향과 정확히 같다).
 * 결측을 0으로 메우면 8 km 지점에서 원점으로 튀는 도약이 dt로 나뉘어 수만 m/s가 되고,
 * 그 값이 체이스 카메라의 진행 방향을 정한다 — 그래서 여기서 null을 낸다.
 */
export function velocityAt(t, signals, i) {
  const j = i - 1;
  if (j < 0) return null;
  const a = sampleAt(signals, j);
  const b = sampleAt(signals, i);
  if (a === null || b === null) return null;
  const dt = t[i] - t[j];
  if (!(dt > 0)) return null;
  return [(b[0] - a[0]) / dt, (b[1] - a[1]) / dt, (b[2] - a[2]) / dt];
}

/** 기준면 한 변 [m] — 궤적 수평 범위의 2.5배, 하한 2 km. 표본이 없으면 기본값. */
export function sceneExtent(signals, fallback = 4000) {
  let lo = Infinity, hi = -Infinity;
  for (const arr of [signals.pn, signals.pe]) {
    for (const v of arr ?? []) {
      if (!Number.isFinite(v)) continue;
      if (v < lo) lo = v;
      if (v > hi) hi = v;
    }
  }
  if (!Number.isFinite(lo)) return fallback;
  return Math.max((hi - lo) * 2.5, 2000);
}

/** 지형 팩과 시뮬 결과가 **같은 원점에 등록돼 있는가** — 아니면 겹쳐 그릴 수 없다.
 *
 * 지형 격자는 팩의 원점 기준 NED이고 궤적은 결과의 원점 기준 NED다. 둘이 다르면 같은
 * (n, e)가 지구상 다른 곳을 가리키므로, 겹쳐 그린 화면은 **기체가 저 능선 위를 날았다고
 * 거짓말한다.** 키 이름까지 다르므로(`lat_deg`/`lon_deg` vs `lat`/`lon`) 우연히 맞아떨어져
 * 발각될 일도 없다 — 그래서 여기서 명시적으로 판정한다.
 *
 * 반환 {ok, reason} — 화면이 사유를 그대로 문장으로 낸다.
 */
export function originsAgree(packOrigin, resultOrigin, tolDeg = 1e-6) {
  if (packOrigin == null) return { ok: false, reason: "지형 팩에 원점이 없습니다." };
  if (resultOrigin == null) {
    return {
      ok: false,
      reason: "이 결과에는 측지 원점이 없어 지형을 얹을 수 없습니다 — "
        + "같은 (N, E)가 지구상 어디인지 알 수 없습니다.",
    };
  }
  const dLat = Math.abs(packOrigin.lat_deg - resultOrigin.lat);
  const dLon = Math.abs(packOrigin.lon_deg - resultOrigin.lon);
  if (!(dLat <= tolDeg && dLon <= tolDeg)) {
    return {
      ok: false,
      reason: `지형 팩은 ${fmtDeg(packOrigin.lat_deg)}N ${fmtDeg(packOrigin.lon_deg)}E 기준인데 `
        + `이 결과는 ${fmtDeg(resultOrigin.lat)}N ${fmtDeg(resultOrigin.lon)}E 기준입니다 `
        + "— 원점이 달라 겹쳐 그릴 수 없습니다.",
    };
  }
  return { ok: true, reason: null };
}

function fmtDeg(v) {
  return Number.isFinite(v) ? `${v.toFixed(4)}°` : "?";
}

/** 격자 간격 — 1·2·5 계열에서 고른다 (lib/plot.js niceTicks와 같은 어휘). */
export function niceStep(extent) {
  const raw = extent / 20;
  const mag = 10 ** Math.floor(Math.log10(raw));
  return [1, 2, 5, 10].map((m) => m * mag).find((v) => v >= raw) ?? 10 * mag;
}
