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

const TURN_EPS = 1e-6; // 이보다 작은 꺾임은 직진이다 (엔진 _TURN_EPS와 같은 자리)

/** 구간 열 — `legs[i]`는 **`good[i]`에서 끝난다**(legs[0]은 원점 → good[0]).
 *
 *  그래서 `legs[i]`와 `legs[i+1]` 사이의 꺾임점이 곧 `good[i]`다. 판정과 미리보기가
 *  이 인덱스 규약을 공유해야 "경고한 번호"와 "빨갛게 그린 점"이 같은 웨이포인트다.
 */
function buildLegs(good) {
  const legs = [];
  let prev = { n: 0, e: 0 };
  for (const p of good) {
    const dn = p.n - prev.n;
    const de = p.e - prev.e;
    legs.push({ len: Math.hypot(dn, de), brg: Math.atan2(de, dn) });
    prev = p;
  }
  return legs;
}

/** `good[i]`의 꺾임 기하 — 꺾임이 아니면 null.
 *
 *  `signed`는 **부호 있는** 선회각이다(+ = 우선회). 판정에는 크기만 필요하지만
 *  미리보기는 호를 어느 쪽으로 그릴지 알아야 해서 함께 낸다 — 두 소비자가 같은
 *  함수를 쓰게 하려고 여기 둔다(따로 재면 한쪽만 고치는 일이 생긴다).
 */
function cornerAt(legs, i, radius) {
  const legIn = legs[i];
  const legOut = legs[i + 1];
  if (!legIn || !legOut || legIn.len <= 0 || legOut.len <= 0) return null;
  const signed = wrapPi(legOut.brg - legIn.brg);
  const turn = Math.abs(signed);
  if (turn < TURN_EPS) return null;
  // tan(Δψ/2)는 Δψ→π에서 발산한다 — 180° 되돌기는 예상 거리로 표현되지 않는다
  const lead = turn >= Math.PI - 1e-9 ? Infinity : radius * Math.tan(turn / 2);
  const limit = 0.5 * Math.min(legIn.len, legOut.len);
  return {
    idx: i, // good[] 기준 꺾임 웨이포인트 번호 (0 기준)
    signed,
    turn,
    turnDeg: (turn * 180) / Math.PI,
    lead,
    legIn: legIn.len,
    legOut: legOut.len,
    limit,
    tight: lead > limit,
  };
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
  const legs = buildLegs(good);
  for (let i = 0; i + 1 < legs.length; i += 1) {
    const c = cornerAt(legs, i, out.radius);
    if (c !== null) out.corners.push(c);
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

/** 실제로 날 경로 미리보기 — **찍자마자** 보이는 선회호 폴리라인.
 *
 * 지도는 종전에도 웨이포인트를 즉시 이었지만 그것은 **직선 꺾은선**이라, 화면은 각을
 * 딱 꺾어 도는 그림을 보여 주는데 기체는 선회 반경만큼 크게 돌아 나간다. 사용자가
 * "경로가 꼬인다"고 본 괴리가 그 자리다. 여기서는 엔진이 실제로 쓰는 예상 전환 기하
 * (`guidance/path.py` §선회 예상 전환)를 그대로 그린다 — 꺾임점 앞뒤 `lead` 지점을
 * 접점으로 반경 `R`의 원호를 물리고, 그 사이는 직선이다.
 *
 * ## 못 나는 꺾임은 **호를 지어내지 않는다**
 *
 * `tight`인 꺾임(예상 거리가 구간 절반을 넘는 자리)에서는 접선 원호가 구간 안에
 * 존재하지 않는다. 그때 기체가 실제로 그리는 궤적은 지나쳤다 되돌아오는 추종
 * 동역학의 결과라 이 정도 기하로는 예측할 수 없다 — 그래서 **계획 꺾은선을 그대로
 * 두고 그 점을 `tightIdx`로 표시만 한다**. 그럴듯한 호를 그려 넣으면 화면이 날 수
 * 없는 경로를 날 수 있는 것처럼 말하게 되고, 그것이 바로 이 기능이 없애려던 거짓말이다.
 *
 * 출발점은 원점(0, 0)이다 — `checkWaypoints`의 `firstLegAssumed`와 같은 가정이고,
 * 지도의 기존 계획 점선도 원점에서 시작하므로 두 선이 같은 자리에서 갈라진다.
 *
 * @param arcSteps 호 하나를 쪼갤 선분 수 (기본 16 — 화면 축척에서 각지지 않는 값)
 * @returns {{radius, points: [{n, e}], tightIdx: number[]}}
 *   radius가 null이면(속도·뱅크 한계 미지) points는 비어 있다 — 지어내지 않는다.
 */
export function flyablePath(pts, speed, bankMax, arcSteps = 16) {
  const good = (pts ?? []).filter((p) => p && p.ok);
  const radius = turnRadius(speed, bankMax);
  const out = { radius, points: [], tightIdx: [] };
  if (radius === null || !good.length || !(arcSteps >= 1)) return out;

  const legs = buildLegs(good);
  out.points.push({ n: 0, e: 0 });
  for (let i = 0; i < good.length; i += 1) {
    const w = good[i];
    const c = cornerAt(legs, i, radius);
    if (c === null || c.tight) {
      // 꺾임이 아니거나(마지막 점·직진) 계획대로 못 나는 자리 — 계획선 그대로
      if (c !== null) out.tightIdx.push(i);
      out.points.push({ n: w.n, e: w.e });
      continue;
    }
    const brgIn = legs[i].brg;
    const brgOut = legs[i + 1].brg;
    const tIn = { n: w.n - c.lead * Math.cos(brgIn), e: w.e - c.lead * Math.sin(brgIn) };
    // 선회 중심은 진입 구간의 **선회 쪽** 법선으로 R만큼 — 우선회(+)면 진행방향 오른쪽,
    // 즉 brgIn + π/2 방향이다. NED에서 방위가 커지는 쪽이 오른쪽이다(북→동).
    const s = c.signed >= 0 ? 1 : -1;
    const ctr = {
      n: tIn.n + s * radius * -Math.sin(brgIn),
      e: tIn.e + s * radius * Math.cos(brgIn),
    };
    out.points.push(tIn);
    // 중심에서 본 접점의 각을 **선회각만큼** 돌린다 — 위치 벡터는 기수와 같은 방향으로
    // 돈다. 끝 각의 점이 곧 출구 접점이라 다음 직선이 거기서 이어진다.
    const a0 = Math.atan2(tIn.e - ctr.e, tIn.n - ctr.n);
    for (let k = 1; k <= arcSteps; k += 1) {
      const a = a0 + c.signed * (k / arcSteps);
      out.points.push({ n: ctr.n + radius * Math.cos(a), e: ctr.e + radius * Math.sin(a) });
    }
  }
  return out;
}
