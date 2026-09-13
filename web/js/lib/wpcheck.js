/** 웨이포인트 사전 판정 — **제출하기 전에** 기하가 비행 성능 안에 있는지 본다.

순수추적(LOS)은 선회 반경보다 급한 꺾임을 못 난다. 그때 기체는 웨이포인트를
중심으로 원을 돌며 영영 수렴하지 않고, 미션이 `path_done`에 닿지 못해 끝나지
않는다 — 실측: 88 m/s·φ_max 0.7(R≈938 m)에서 1 km 간격 직각 웨이포인트 넷 중
하나만 잡고 400 s 동안 5.4바퀴를 돌았다.

엔진에는 이제 두 장치가 있다(engine `guidance/path.py`): 꺾임 앞에서 미리 트는
**선회 예상 전환**과, 그래도 못 잡으면 한 바퀴 뒤 넘기는 **궤도 고착 탈출**.
둘 다 *사후*다 — 돌고 나서야 알고, 그 점은 계획대로 지나가지 못한다. 이 모듈은
같은 기하를 **미리** 재서 사용자가 좌표를 고칠 기회를 준다.

## 무엇을 재는가 — 축이 둘이다

**수평(선회 반경).** R = V²/(g·tan φ_max)에서 꺾임점마다 예상 거리 L = R·tan(Δψ/2)를
낸다. L이 양쪽 구간의 절반을 넘으면 앞뒤 전환이 서로를 삼켜 그 꺾임을 계획대로 날 수
없다 — 엔진이 L을 자르는 바로 그 조건이라 **화면과 엔진이 같은 부등식을 본다**.

**세로(상승 경사).** 구간마다 Δ고도 / 유효 램프 길이를 내어 기체 성능과 견준다.
램프는 웨이포인트 중심이 아니라 **유효 포획 반경 경계**에서 끝나므로(엔진 `_leg_alt`)
분모가 구간 길이보다 짧고, 급한 꺾임은 예상 거리만큼 그 분모를 **더** 깎는다 —
즉 수평으로 급한 자리는 세로 여유까지 같이 잃는다. 두 축이 한 함수에 있는 이유다.

세로가 수평과 **다른 점**: 선회 반경은 기체를 안 봐도 나오지만(V와 φ뿐), 상승 경사는
기체를 봐야 한다. 그래도 상수로 박지 않는다 — 실측해 보니 한계를 정하는 것이 기체가
아니라 **오토파일럿의 피치 상한**이었기 때문이다(`theta_hi` 0.3에서 3.56 %, 0.5로 열면
14.75 %, 그때 스로틀 0.635 → 0.992). 그래서 `climbGradientMax()`가 설정에서 유도하고,
기체의 몫으로 남는 실측 상수는 **순항 받음각 하나**와 **추력 천장**뿐이다.

## 무엇을 재지 않는가 — 경고이지 거부가 아니다

- **판정은 근사다.** 실제 선회는 뱅크가 차오르는 시간·바람·항법 오차를 탄다.
  그래서 결과는 `warn`이지 `error`가 아니고, **제출을 막지 않는다**. 막으면
  "돌려 보고 알기"라는 이 툴의 쓰임 자체를 없앤다.
- **속도는 모드 표에서 온다.** `"path"` 헤딩을 쓰는 모드의 속도 지령이 근거이고,
  없으면 **판정하지 않는다**(0이나 임의값으로 메우면 없는 판정선을 지어낸다 —
  01 §4.2 「0 위장 금지」와 같은 자리).
- **첫 구간의 시작점은 원점(0, 0)으로 둔다.** 실제로는 순항 진입 지점이라 다르다.
  첫 꺾임의 진입 방위만 영향을 받고, 그 사실을 `firstLegAssumed`로 낸다.
- **첫 구간의 상승은 아예 판정하지 않는다.** 진입 방위는 원점으로 가정할 수 있지만
  진입 **고도**는 가정할 자리가 없다. 화면이 아는 출발 고도는 *시작 트림 고도*인데
  (기본 미션에서 0 m = 활주로 표고), 엔진의 램프는 거기서 시작하지 않는다 —
  고도 축이 경로를 **잡는 순간** 다시 그어지므로(`begin_alt_leg`) 실제 시작점은
  순항 진입 고도다(기본 미션 실측 ≈ 180 m). 트림 고도로 재면 0 → 700 m를 요구하는
  것으로 보여 **없는 경고를 지어낸다**. 그래서 `climbs`는 둘째 구간부터다 —
  실측에서 그 첫 구간이 12.5 %로 한계의 세 배였던 적이 있으므로, 여기가 비어
  있다는 것은 안전하다는 뜻이 아니라 **못 쟀다**는 뜻이다.
  [TBD] 순항 진입 고도를 서버에서 받아 오면 이 구간도 잴 수 있다.
- **속도를 모르면 세로도 판정하지 않는다.** 램프 분모가 선회 예상 거리를 빼야 하고
  그 거리가 선회 반경에서 오므로, 속도가 없으면 분모를 못 만든다. `"path"` 헤딩
  없이 `alt="path"`만 쓰는 미션(웨이포인트를 세로 프로파일로만 쓰는 구성)이 그
  사각지대다 — `pathSpeed`가 헤딩만 보기 때문이고, 그때는 조용하다.
- **질량은 설계변수가 아니다.** `CRUISE_AOA`는 연료 300 kg·질량 1,100 kg에서 잰
  값이고, 지금은 `m_empty`가 `plant/demo.py`에 하드코딩이라(모든 라우트가
  `make_demo_aircraft()`를 인자 없이 부른다) 이 상수가 성립한다. 질량을 여는 날
  여기도 함께 열어야 한다 — 안 그러면 화면이 없는 기체의 성능을 말한다 [TBD].
- **강하는 판정하지 않는다.** 내려가는 쪽 한계는 추력이 아니라 속도 제어·강하율에서
  오는 다른 물리라 같은 상수로 재면 틀린 수를 말한다. 올라가는 구간만 본다.
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

/** 순항 받음각 [rad] — 기준 속도에서 수평비행에 드는 α. **실측 상수 하나**다.
 *
 * 상승 경사를 상수로 박지 않고 여기까지 내려온 이유: 한계를 정하는 것은 기체가 아니라
 * **오토파일럿의 피치 상한**이었다. 실측 — `theta_hi` 0.3 rad에서 경사 3.56 %인데
 * 그때 스로틀이 0.635(추력 36 % 여유)이고 α 리미터는 한 번도 안 물었다. 상한을
 * 0.5 rad로 열자 같은 기체가 14.75 %를 낸다. 즉 4 %는 기체의 수가 아니라 **설정의
 * 수**이고, 상수로 박으면 사용자가 오토파일럿을 손봐도 판정선이 안 따라온다.
 *
 * 기준: 88 m/s에서 **13.71°**(실측, 연료 300 kg·질량 1,100 kg).
 * 속도에 따라 α ∝ 1/V²로 민다 — CL = W/(q·S)이고 이 기체는 CL이 α에 선형이라
 * (`plant/demo.py` CL = 3.5α) 그 눈금이 맞는다. **질량이 바뀌면 틀린다** —
 * 지금은 질량이 설계변수가 아니라(`m_empty` 하드코딩) 이 상수가 성립하지만,
 * 질량을 열면 여기도 함께 열어야 한다 [TBD].
 */
export const CRUISE_AOA = Object.freeze({ alpha: 0.2393, speed: 88 });

/** 추력이 막는 상승 경사 [무차원] — 피치 상한을 열어도 여기서 멈춘다.
 *
 * 둘째 천장이다. `theta_hi`를 0.5 rad로 열면 θ 명령이 22.79°에서 서는데 상한
 * 28.6°에 **닿지 않았다** — 스로틀이 0.992라 추력이 먼저 떨어진 것이다. 0.7 rad로
 * 더 열면 α 리미터가 100 % 물고 속도가 76.7 m/s로 떨어져 경사가 오히려 나빠진다
 * (14.52 %). 이 천장이 없으면 "상한을 열면 40 %까지 올라간다"는 거짓을 말한다.
 *
 * 실측 14.75 % — 보수적으로 내려 박는다. 손계산 (T−D)/W는 20.5 %를 내는데 그것은
 * 상승 자세에서 늘어나는 유도항력을 빼먹은 값이다. 측정이 이긴다.
 *
 * **질량·고도의 함수다** (`CRUISE_AOA`와 같은 [TBD]). 연료 0 kg(800 kg)에서는 같은
 * 설정이 15.56 %를 내어 이 천장을 넘고, 1,200 kg·2,000 m에서는 5 %대로 주저앉는다.
 * 지금 값은 **1,100 kg·500 m**의 것이라 그 코너에서 낙관한다 — 질량을 설계변수로
 * 여는 날 이 상수도 축을 가져야 한다.
 */
export const CLIMB_THRUST_CAP = 0.147;

/** 상승 경사 한계 [무차원] — **설정에서 유도한다**.
 *
 * 고도 PI가 피치 상한에 박히면 θ 명령 = `theta_hi` + `k_hdot`·hdot이고(댐핑항은
 * 음수라 빠진다), 경사각 γ = θ − α, hdot = V·sin γ다. 묶어서 풀면
 *
 *     γ = (theta_hi − α) / (1 + |k_hdot|·V)
 *
 * 소각 근사(sin γ ≈ γ)를 한 번 쓴다. 실측과 맞춘 결과:
 *
 *   theta_hi 0.3  → 모델 3.564 % · 실측 3.56 %   (피치 상한이 물린다)
 *   theta_hi 0.40 → 모델 9.46 %  · 실측 9.13 %    ← **현행 기본값** (v1.03)
 *   theta_hi 0.5  → 모델 15.4 %  → 추력 천장 14.75 % · 실측 14.75 %
 *   theta_hi 0.7  → 모델 27.7 %  → 추력 천장 14.75 % · 실측 14.52 %
 *
 * 판정할 수 없으면 **null**이다(0이 아니다) — 0을 내면 모든 상승이 급하다고 나오고
 * 경고가 장식이 된다. 위쪽 `turnRadius`와 같은 규약이다.
 */
export function climbGradientMax(thetaHi, kHdot, speed) {
  if (!Number.isFinite(thetaHi) || !Number.isFinite(speed) || speed <= 0) return null;
  if (!Number.isFinite(kHdot)) return null;
  // α ∝ 1/V² — 기준점에서 민다 (CL = W/(q·S), CL은 α에 선형)
  const alpha = CRUISE_AOA.alpha * (CRUISE_AOA.speed / speed) ** 2;
  const gamma = (thetaHi - alpha) / (1 + Math.abs(kHdot) * speed);
  // 상한이 순항 α보다 낮으면 **올라갈 각이 없다** — 음수를 그대로 내면 모든 상승이
  // 걸리는데 그것이 사실이다(그 설정으로는 수평비행도 빠듯하다). 0으로 바닥을 치면
  // "아주 완만한 상승은 된다"는 거짓이 된다
  if (!(gamma > 0)) return 0;
  return Math.min(Math.tan(gamma), CLIMB_THRUST_CAP);
}

/** 구간 i의 **유효 램프 길이** [m] — 엔진 `_leg_alt`의 분모와 같은 값.
 *
 * 엔진의 고도 램프는 웨이포인트 중심이 아니라 **유효 포획 반경 경계**에서 끝난다
 * (거기서 다음 구간으로 전환하므로 도착할 때 이미 목표 고도여야 한다). 그 반경은
 * 도달 반경과 선회 예상 거리 중 **큰 쪽**이다 — 예상 전환이 켜지면 램프도 함께
 * 앞당겨져 **짧아진다**. 즉 급한 꺾임은 상승 여유까지 같이 깎는다.
 *
 * 도달 반경만으로 재면(`lib/wpmap.js planProfile`이 그렇다) 여기서 램프를 실제보다
 * 길게 봐서 **못 나는 구간을 통과시킨다**. 판정은 엔진과 같은 분모를 써야 한다.
 *
 * **tight 꺾임에서도 예상 거리는 0이 아니다.** 엔진은 `min(lead, ½legIn, ½legOut)`으로
 * **자르지 끄지 않는다**(`_lead` 마지막 줄) — 잘린 값이 그대로 포획 반경에 든다.
 * 여기서 0으로 두면(미리보기가 호를 안 그리는 것과 헷갈리기 쉬운 자리다) 가장 급한
 * 꺾임에서 분모를 가장 크게 낙관해, **수평으로도 세로로도 못 나는 구간이 조용히
 * 통과한다**. 미리보기가 호를 지어내지 않는 것과 분모를 어떻게 재는가는 다른 물음이다.
 */
function rampLength(legLen, corner, acceptRadius) {
  const r = Number.isFinite(acceptRadius) && acceptRadius > 0 ? acceptRadius : 0;
  // 엔진 `_lead`와 같은 자르기 — 180° 되돌기(lead = Infinity)도 limit으로 떨어진다
  const lead = corner === null ? 0 : Math.min(corner.lead, corner.limit);
  return legLen - Math.max(r, Number.isFinite(lead) ? lead : 0);
}

/** 웨이포인트 기하 판정.
 *
 * @param pts        [{n, e, ok}] — `wpmap.rowsToPoints` 결과 (ok=false는 건너뛴다)
 * @param speed      순항 속도 [m/s] (`pathSpeed`)
 * @param bankMax    뱅크 한계 [rad] (오토파일럿 phi_max)
 * @param acceptRadius 도달 반경 [m]
 * @param climbMax   상승 경사 한계 [무차원] — `climbGradientMax()` 산출. **기본값이
 *   없다**: 오토파일럿 설정에서 나오는 값이라 이 모듈이 지어낼 수 없고, 안 주면
 *   세로는 판정하지 않는다(속도를 모를 때 수평을 판정하지 않는 것과 같은 자리).
 *   뷰가 넘기는지는 `wpcheck.test.js`가 원문 대조로 지킨다 — 조용히 빠지면
 *   경고만 사라지고 화면은 멀쩡해 보인다
 * @returns {{radius, corners, climbs, warnings, firstLegAssumed}}
 *   corners: 꺾임점마다 {idx, turnDeg, lead, legIn, legOut, limit, tight}
 *   climbs:  **둘째 구간부터** {idx, from, to, rise, ramp, grad, steep} (첫 구간은 없다)
 *   warnings: 사람이 읽을 문장 (빈 배열 = 걸릴 것 없음)
 */
export function checkWaypoints(pts, speed, bankMax, acceptRadius,
                               climbMax = null) {
  const good = (pts ?? []).filter((p) => p && p.ok);
  const out = {
    radius: turnRadius(speed, bankMax),
    corners: [],
    climbs: [],
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

  // ── 상승 경사 — 계획이 기체 성능 안에 드는가.
  //
  // **첫 구간(legs[0])은 판정하지 않는다.** 그 구간의 시작 고도는 "고도 축이 경로를
  // 잡는 순간의 기체 고도"인데(엔진 `begin_alt_leg`), 그것은 이륙·상승 구간 전체가
  // 낸 결과라 화면이 알 수 없다. 지어내면 없는 판정선이 된다 — 진입 방위를 원점으로
  // 가정하는 `firstLegAssumed`와 같은 자리이고, 같은 이유로 조용히 넘기지 않고 적는다.
  //
  // **내려가는 쪽도 판정하지 않는다.** 강하 한계는 추력이 아니라 속도 제어·강하율에서
  // 오는 다른 물리라 같은 상수로 재면 틀린 수를 말한다. rise > 0만 본다.
  if (Number.isFinite(climbMax) && climbMax > 0) {
    for (let i = 1; i < good.length; i += 1) {
      const from = good[i - 1].d;
      const to = good[i].d;
      if (from == null || to == null) continue; // 고도 없는 점 — 잴 것이 없다
      const rise = to - from;
      if (rise <= 0) continue; // 수평·강하는 이 판정선의 몫이 아니다
      const corner = cornerAt(legs, i, out.radius);
      const ramp = rampLength(legs[i].len, corner, acceptRadius);
      // ramp <= 0이면 엔진은 구간 시작에서 **곧바로** 목표 고도를 명령한다
      // (`_leg_alt`의 denom <= 0 분기) — 유한한 경사가 없는 계단이라 Infinity다
      const grad = ramp > 0 ? rise / ramp : Infinity;
      out.climbs.push({ idx: i, from, to, rise, ramp, grad, steep: grad > climbMax });
    }
    const steep = out.climbs.filter((c) => c.steep);
    if (steep.length) {
      const names = steep.map((c) => c.idx + 1).join(", ");
      const worst = steep.reduce((a, b) => (b.grad > a.grad ? b : a));
      const gradTxt = Number.isFinite(worst.grad)
        ? `${(worst.grad * 100).toFixed(1)} %`
        : "램프 구간이 없어(구간이 포획 반경보다 짧다) 계단입니다";
      // **처방을 미션 쪽으로만 말하지 않는다.** 이 한계는 대개 기체가 아니라
      // 오토파일럿 `theta_hi`가 정한다(실측: 0.3 → 3.56 %, 0.5 → 14.75 %). 설계
      // 툴에서 진짜 레버는 그쪽인데 "웨이포인트를 벌리세요"만 말하면 사용자를
      // 미션을 고치는 쪽으로 몰아 설계변수를 못 보게 한다. 다만 추력 천장에
      // 닿았으면 상한을 더 열어도 소용없으므로 그때는 그 말을 하지 않는다
      const capped = climbMax >= CLIMB_THRUST_CAP - 1e-9;
      out.warnings.push(
        `웨이포인트 ${names}번까지의 상승이 지금 설정으로는 급합니다 — `
        + `가장 급한 곳은 ${Math.round(worst.ramp).toLocaleString("ko-KR")} m 안에 `
        + `${Math.round(worst.rise).toLocaleString("ko-KR")} m를 올라야 해서 `
        + `${gradTxt}가 필요한데 지금 낼 수 있는 것은 약 ${(climbMax * 100).toFixed(1)} %입니다. `
        + "기체는 명령을 따라가려 하지만 못 올라가 계획보다 낮게 날고, 그 뒤 구간이 "
        + "그 낮은 고도에서 다시 시작합니다. "
        + (capped
          ? "이 값은 **추력 한계**입니다 — 피치 상한을 더 열어도 오르지 않습니다. "
            + "웨이포인트를 더 벌리거나 고도차를 줄이십시오."
          : "이 한계는 기체가 아니라 **오토파일럿 피치 상한(`theta_hi`)**이 정합니다 — "
            + "지금은 추력이 남아 있으므로 블록도에서 그 값을 올리면 함께 올라갑니다. "
            + "웨이포인트를 벌리거나 고도차를 줄여도 풀립니다."),
      );
    }
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
