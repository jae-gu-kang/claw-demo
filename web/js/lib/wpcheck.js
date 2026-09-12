/** 웨이포인트 사전 판정 — **제출하기 전에** 기하가 비행 성능 안에 있는지 본다.

순수추적(LOS)은 선회 반경보다 급한 꺾임을 못 난다. 그때 기체는 웨이포인트를
중심으로 원을 돌며 영영 수렴하지 않고, 미션이 `path_done`에 닿지 못해 끝나지
않는다 — 실측: 88 m/s·φ_max 0.7(R≈938 m)에서 1 km 간격 직각 웨이포인트 넷 중
하나만 잡고 400 s 동안 5.4바퀴를 돌았다.

엔진에는 이제 두 장치가 있다(engine `guidance/path.py`): 꺾임 앞에서 미리 트는
**선회 예상 전환**과, 그래도 못 잡으면 한 바퀴 뒤 넘기는 **궤도 고착 탈출**.
둘 다 *사후*다 — 돌고 나서야 알고, 그 점은 계획대로 지나가지 못한다. 이 모듈은
같은 기하를 **미리** 재서 사용자가 좌표를 고칠 기회를 준다.

## 무엇을 재는가

선회 반경 R = V²/(g·tan φ_max)에서 꺾임점마다 예상 거리 L = R·tan(Δψ/2)를 낸다.
L이 양쪽 구간의 절반을 넘으면 앞뒤 전환이 서로를 삼켜 그 꺾임을 계획대로 날 수
없다 — 엔진이 L을 자르는 바로 그 조건이라 **화면과 엔진이 같은 부등식을 본다**.

## 무엇을 재지 않는가 — 경고이지 거부가 아니다

- **판정은 근사다.** 실제 선회는 뱅크가 차오르는 시간·바람·항법 오차를 탄다.
  그래서 결과는 `warn`이지 `error`가 아니고, **제출을 막지 않는다**. 막으면
  "돌려 보고 알기"라는 이 툴의 쓰임 자체를 없앤다.
- **속도는 모드 표에서 온다.** `"path"` 헤딩을 쓰는 모드의 속도 지령이 근거이고,
  없으면 **판정하지 않는다**(0이나 임의값으로 메우면 없는 판정선을 지어낸다 —
  01 §4.2 「0 위장 금지」와 같은 자리).
- **첫 구간의 시작점은 원점(0, 0)으로 둔다.** 실제로는 순항 진입 지점이라 다르다.
  첫 꺾임의 진입 방위만 영향을 받고, 그 사실을 `firstLegAssumed`로 낸다.
*/

const G0 = 9.80665; // [m/s²] 엔진 common/constants.py G0와 같은 값 — 표준 중력

/** 선회 반경 [m] — R = V²/(g·tan φ). 유한·양수가 아니면 null(판정 불가). */
export function turnRadius(speed, bankMax) {
  if (!Number.isFinite(speed) || speed <= 0) return null;
  if (!Number.isFinite(bankMax) || bankMax <= 0) return null;
  const t = Math.tan(bankMax);
  if (!Number.isFinite(t) || t <= 0) return null;
  return (speed * speed) / (G0 * t);
}

/** (-π, π] 래핑 — 엔진 `_wrap_pi`와 같은 규약. */
function wrapPi(a) {
  const x = (a + Math.PI) % (2 * Math.PI);
  return (x < 0 ? x + 2 * Math.PI : x) - Math.PI;
}

/** `"path"` 헤딩을 쓰는 모드의 속도 지령 [m/s] — 없으면 null.
 *
 * 여럿이면 **가장 빠른 것**을 쓴다: 선회 반경은 V²로 커지므로 가장 빠른 구간이
 * 가장 못 도는 구간이다. 느린 쪽으로 재면 통과를 낙관한다.
 */
export function pathSpeed(modeRows) {
  let best = null;
  for (const r of modeRows ?? []) {
    if (String(r.heading ?? "").trim() !== "path") continue;
    const v = Number(String(r.speed ?? "").trim());
    if (!Number.isFinite(v) || v <= 0) continue;
    if (best === null || v > best) best = v;
  }
  return best;
}

/** 웨이포인트 기하 판정.
 *
 * @param pts        [{n, e, ok}] — `wpmap.rowsToPoints` 결과 (ok=false는 건너뛴다)
 * @param speed      순항 속도 [m/s] (`pathSpeed`)
 * @param bankMax    뱅크 한계 [rad] (오토파일럿 phi_max)
 * @param acceptRadius 도달 반경 [m]
 * @returns {{radius, corners, warnings, firstLegAssumed}}
 *   corners: 꺾임점마다 {idx, turnDeg, lead, legIn, legOut, limit, tight}
 *   warnings: 사람이 읽을 문장 (빈 배열 = 걸릴 것 없음)
 */
export function checkWaypoints(pts, speed, bankMax, acceptRadius) {
  const good = (pts ?? []).filter((p) => p && p.ok);
  const out = {
    radius: turnRadius(speed, bankMax),
    corners: [],
    warnings: [],
    firstLegAssumed: good.length > 0,
  };
  if (out.radius === null || good.length < 2) return out;

  // 첫 구간의 진입 방위는 원점에서 첫 웨이포인트로 — 위 머리말의 가정이다
  const legs = [];
  let prev = { n: 0, e: 0 };
  for (const p of good) {
    const dn = p.n - prev.n;
    const de = p.e - prev.e;
    legs.push({ len: Math.hypot(dn, de), brg: Math.atan2(de, dn) });
    prev = p;
  }

  for (let i = 0; i + 1 < legs.length; i += 1) {
    const legIn = legs[i];
    const legOut = legs[i + 1];
    if (legIn.len <= 0 || legOut.len <= 0) continue;
    const turn = Math.abs(wrapPi(legOut.brg - legIn.brg));
    if (turn < 1e-6) continue;
    // tan(Δψ/2)는 Δψ→π에서 발산한다 — 180° 되돌기는 예상 거리로 표현되지 않는다
    const lead = turn >= Math.PI - 1e-9
      ? Infinity
      : out.radius * Math.tan(turn / 2);
    const limit = 0.5 * Math.min(legIn.len, legOut.len);
    out.corners.push({
      idx: i, // good[] 기준 꺾임 웨이포인트 번호 (0 기준)
      turnDeg: (turn * 180) / Math.PI,
      lead,
      legIn: legIn.len,
      legOut: legOut.len,
      limit,
      tight: lead > limit,
    });
  }

  const tight = out.corners.filter((c) => c.tight);
  if (tight.length) {
    const names = tight.map((c) => c.idx + 1).join(", ");
    const worst = tight.reduce((a, b) => (b.lead > a.lead ? b : a));
    const leadTxt = Number.isFinite(worst.lead)
      ? `${Math.round(worst.lead).toLocaleString("ko-KR")} m`
      : "되돌기(180°)라 유한한 값이 없습니다";
    out.warnings.push(
      `웨이포인트 ${names}번의 꺾임이 선회 성능보다 급합니다 — `
      + `${Math.round(speed)} m/s·뱅크 ${(bankMax * 180 / Math.PI).toFixed(0)}°에서 `
      + `선회 반경이 ${Math.round(out.radius).toLocaleString("ko-KR")} m라 `
      + `가장 급한 곳(${worst.turnDeg.toFixed(0)}°)은 선회에 ${leadTxt}가 필요한데 `
      + `구간 절반이 ${Math.round(worst.limit).toLocaleString("ko-KR")} m뿐입니다. `
      + "기체가 그 점을 지나쳤다 되돌아오거나, 한 바퀴 돈 뒤 못 잡고 넘어갑니다 — "
      + "웨이포인트를 더 벌리거나 순항 속도를 낮추면 풀립니다.",
    );
  }

  // 도달 반경이 선회 반경보다 훨씬 작으면 **넘어간 뒤 되돌기**가 잦다. 예상 전환이
  // 대개 덮지만(위 lead가 바닥을 올린다) 마지막 웨이포인트에는 다음 구간이 없어
  // 예상 전환이 0이고 도달 반경만 남는다 — 거기서 못 잡으면 경로가 안 끝난다.
  if (acceptRadius > 0 && out.radius > 0 && acceptRadius < 0.25 * out.radius) {
    out.warnings.push(
      `도달 반경 ${Math.round(acceptRadius).toLocaleString("ko-KR")} m가 선회 반경 `
      + `${Math.round(out.radius).toLocaleString("ko-KR")} m에 비해 작습니다 — `
      + "마지막 웨이포인트는 예상 전환이 없어(다음 구간이 없다) 도달 반경만으로 "
      + "잡아야 하는데, 빗나가면 그 점을 돌기만 하다 경로가 끝나지 않습니다. "
      + `선회 반경의 1/4(${Math.round(0.25 * out.radius).toLocaleString("ko-KR")} m) 이상을 권합니다.`,
    );
  }
  return out;
}
