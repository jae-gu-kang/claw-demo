/** 시뮬 요청 조립 (02 §8 7단계) — 폼 값 → `POST /api/sim/run` 본문 (순수 로직).

시뮬 탭의 [시뮬 실행](views/sim.js)과 가이드 투어(views/tour.js)가 **같은 조립**을
쓴다. 조립이 두 벌이면 투어가 돌린 미션과 시뮬 탭이 돌렸을 미션이 조용히 갈리고,
그때 화면은 자기가 보여 주는 표가 그 결과를 낸 미션이라고 거짓말하게 된다.

기본 미션·실행 조건 기본값도 여기가 정본이다(시뮬 탭이 import). 동작은 v0.92까지
sim.js run()에 있던 것을 **그대로** 옮겼다 — 빈 칸이 칸마다 다르게 처리되는 것까지
포함해서다(대부분 `Number("")`=0, 측지 원점만 NaN). simrequest.test.js의 골든이
그 동등성을 고정한다: sim.js에는 뷰 테스트가 없어 이 테스트가 유일한 지킴이다.
*/

import { buildModes, buildWaypoints } from "./mission.js";
import { GOHEUNG } from "./site.js";

// 기본 미션 = **발사대에서 떠서 활주로에 선다** (01 §3.3.1 이륙~착륙).
// 발사 → 상승 → 장주 순항 → 접근 → 플레어 → 미끄럼 → 정지.
//
// **순항은 우선회 장주(traffic pattern)다.** 종전에는 활주로 축 위 웨이포인트 둘을
// 지나 그대로 북진하며 내려갔고, 접지가 활주로 시단에서 7,010 m 북쪽이었다(실측) —
// 논밭 한가운데다. 착륙 요약이 "접지 지점" 행으로 그 사실을 말하고는 있었지만,
// 화면의 3D 지형은 실측 고흥이고 물리 지면은 표고 하나짜리 평면이라 그 자리에서는
// 기체가 땅에 파묻힌 것처럼 보였다(지형-물리 결합은 별건 [TBD]). 활주로로 되돌아와
// 내리면 두 기준면이 같은 자리라 그 착시가 사라진다.
//
// 종방향 축이 단계마다 갈린다 — launch·climb·rollout은 **피치**(고도 루프를 거칠
// 이유가 없는 자세 구간), approach·flare는 **강하율**(어느 고도가 아니라 내려가는
// 속도를 잡는 구간), cruise만 **고도**다. 셋은 배타라 한 모드에 하나씩만 들어간다.
//
// 수치는 엔진 실측으로 정했다. 이탈속도·플레어 개시·미끄럼은 engine test_landing과
// 같은 값이고, **climb·cruise는 일부러 다르다** — 저쪽은 250/300 m라 다운레인지가
// 10.8 km인데, 이쪽은 지형 팩 안에 들어오도록 180/200 m로 낮춰 8.0 km로 줄였다:
//   이탈 81.5 m/s = 1.15 × 트림 실속속도 70.9
//   플레어 개시 20 m·kp_vs 0.08 → 접지 −1.0 m/s (5 m에서는 0.9 s뿐이라 −4.6)
//   접지 후 미끄럼 870 m — 고흥 활주로 실측 1,205 m에서 접지 창은 335 m뿐이다
//   (그 창을 실제로 맞추는 것이 아래 장주다. 화면은 여전히 숨기지 않는다 — 착륙
//    요약이 "접지 지점"·"정지" 행에 활주로 축 기준 실제 값을 내고 구간 밖이면
//    밖이라고 적는다. 여기에 그 수를 적어 두면 프로파일이 바뀔 때마다 조용히
//    낡는다 — lib/replay.js landingSummary)
//
// 장주 기하는 **실측에서 역산했다**(engine 직접 실행, 도달 반경 300·순항 88 m/s):
//   접근 시작 → 접지 4,007 m (접근 3,249 + 플레어 758) · 접지 → 정지 863 m
//   활주로가 0~1,205 m이므로 접지가 ~150 m여야 정지가 구간 안에 든다
//   → 접근 시작은 활주로 축 −3,860 m, path_done이 도달 반경만큼 먼저 오므로 WP는 −3,600
// 이 수들은 프로파일(속도·강하율·플레어)이 바뀌면 함께 움직인다 — 바꿨으면 다시 재라.
//
// 이 값들은 엔진 기본값의 사본이 아니라 **미션 시나리오**라 02 §5.5의 "엔진 기본값
// 재기술" 대상이 아니다 (lib/loops.js DEFAULT_LOOPS와 같은 부류).
const CLIMB_PITCH = "0.3665"; // [rad] 21° — α 리미터 한계까지 기수를 든다
// 고흥 활주로 진방위 실측 (lib/site.js ← data/geo/goheung-runway.json). 미션 헤딩과
// 활주로 칸의 **초기값**이 같은 상수에서 나온다 — 헤딩 0으로 날던 때는 10 km 뒤에
// 축에서 595 m 벌어져 있었고, 맞추고 나니 29 m다.
export const RUNWAY_HDG = String(GOHEUNG.runwayHeadingRad); // [rad] 3.417°

/** 기본 모드 표 — **부를 때마다 새 사본**이다. 표 편집이 행을 제자리에서 고치므로
 *  (views/sim.js renderModeTable) 정본 배열을 그대로 내주면 기본값이 오염된다. */
export function defaultModeRows() {
  return [
    { name: "launch", speed: "110", lonAxis: "pitch", lonValue: CLIMB_PITCH,
      heading: RUNWAY_HDG, exitKind: "off_rail", exitValue: "", next: "climb" },
    { name: "climb", speed: "110", lonAxis: "pitch", lonValue: CLIMB_PITCH,
      heading: RUNWAY_HDG, exitKind: "alt_ge", exitValue: "180", next: "cruise" },
    // 순항 헤딩은 "path" — 기본 웨이포인트를 따라 날고, 소진(path_done)이 접근
    // 진입을 정한다. 종전 time_ge 15는 경로를 15 s만 따르다 시계로 포기하고
    // 활주로 방위로 되돌아갔다 — 웨이포인트를 찍어도 비행이 안 바뀌던 이유였다.
    { name: "cruise", speed: "88", lonAxis: "alt", lonValue: "200", heading: "path",
      exitKind: "path_done", exitValue: "", next: "approach" },
    // 3° 활공: 88 m/s · sin3° ≈ 4.6 m/s
    { name: "approach", speed: "88", lonAxis: "hdot", lonValue: "-4.8",
      heading: RUNWAY_HDG, exitKind: "alt_le", exitValue: "20", next: "flare" },
    { name: "flare", speed: "80", lonAxis: "hdot", lonValue: "-0.8",
      heading: RUNWAY_HDG, exitKind: "on_ground", exitValue: "", next: "rollout" },
    { name: "rollout", speed: "0", lonAxis: "pitch", lonValue: "0",
      heading: RUNWAY_HDG, exitKind: "speed_le", exitValue: "0.5", next: "stopped" },
    { name: "stopped", speed: "0", lonAxis: "pitch", lonValue: "0", heading: "",
      exitKind: "time_ge", exitValue: "1e9", next: "" },
  ];
}

// 활주로 축 좌표(along = 시단에서 방위 방향, cross = 그 오른쪽) → NED 행.
// 좌표를 리터럴 대신 방위에서 계산하는 이유는 RUNWAY_HDG와 같은 상수를 공유하기
// 위해서다 — 활주로 방위가 바뀌면 장주가 통째로 함께 돈다(리터럴이면 조용히 축을
// 벗어난다). 고도 칸은 비워 둔다(세로는 cruise의 고도 200이 낸다): 고도를 넣는 순간
// "전부 있거나 전부 없거나" 규칙과 alt="path" 전환이 사용자 몫이 된다.
const axisWp = (along, cross = 0) => {
  const c = Math.cos(GOHEUNG.runwayHeadingRad);
  const s = Math.sin(GOHEUNG.runwayHeadingRad);
  return {
    n: String(Math.round(along * c - cross * s)),
    e: String(Math.round(along * s + cross * c)),
    d: "",
  };
};

// 장주 폭 [m] — 180° 되돌기 둘을 담아야 한다. 88 m/s·뱅크 0.7에서 선회 반경이
// 938 m이므로 반전 하나에 2R = 1,876 m가 든다. 2,200은 그 위의 여유다.
const PATTERN_CROSS = 2200;

/** 기본 웨이포인트 표 — 모드 표와 같은 이유로 **새 사본**이다.
 *
 *  이륙 방향(북)으로 나갔다가 우선회 장주로 되돌아와 활주로 축에 정대한다:
 *  이륙 구간 → 크로스윈드 → 다운윈드(남) → 베이스 → 파이널.
 *  마지막 점에서 `path_done`이 나면 approach가 활주로 방위로 받아 내린다.
 */
export function defaultWpRows() {
  return [
    axisWp(3500, 0), //  이륙 구간 — 상승 이탈(축 1,865 m) 뒤 첫 우선회까지의 여유
    axisWp(3500, PATTERN_CROSS), //  크로스윈드
    axisWp(-5800, PATTERN_CROSS), //  다운윈드 — 활주로를 지나 남쪽으로
    axisWp(-5800, 0), //  베이스 — 축으로 되돌아온다
    axisWp(-3600, 0), //  파이널 진입 — 여기서 경로가 끝나고 접근이 시작된다
  ];
}

/** 작동기 폼 폴백 — 엔진 기본값의 사본이다(02 §5.5). 폼이 즉시 유효해야 해서
 *  남기되, 스키마가 도착하면 `applyActuatorSchema`가 스스로 어긋남을 고친다. */
export const ACT_FALLBACK = Object.freeze({ wn: 30, zeta: 0.7, rate: 10 });
const ACT_SCHEMA_KEY = Object.freeze({ wn: "wn", zeta: "zeta", rate: "rate_max" });

/** 뱅크 한계 폴백 [rad] — 웨이포인트 기하 판정(lib/wpcheck.js)이 선회 반경을 재는 데
 *  쓴다. 위 `ACT_FALLBACK`과 같은 부류의 사본이다: 화면이 표를 그리는 **그 순간**
 *  판정을 내야 해서 남기되, 레지스트리 스키마(`/registry/fcl/Autopilot/schema`)가
 *  도착하면 뷰가 실값으로 갈아 끼운다. 실행 경로에는 이 값이 쓰이지 않는다 —
 *  서버가 오토파일럿의 실제 `phi_max`를 경로추종기에 넘긴다(routes/sim.py _build). */
export const AP_PHI_MAX_FALLBACK = 0.7;

/** 실행 조건 기본값 — 폼 칸 이름 그대로(뷰의 f.* 키와 1:1). 수치는 문자열이다:
 *  폼이 문자열을 들고 있고, 빈 칸과 0을 가르는 것이 조립의 계약이기 때문이다. */
export const DEFAULT_FORM = Object.freeze({
  // 기본 미션은 **발사대 위 정지**에서 출발한다 — 지상 평형해라 mach는 0이고
  // alt는 비행 고도가 아니라 활주로 표고다 (엔진 trim_ground)
  mach: "0",
  alt: "0",
  fuel: "300",
  groundOn: true,
  rwHeading: RUNWAY_HDG,
  rwLength: String(GOHEUNG.runwayLengthM),
  launchOn: true,
  railLen: "10",
  railAngle: "0.2618", // [rad] 15°
  railExit: "81.5", // 1.15 × 트림 실속속도 70.9 → 33.9 g
  rtkOn: true,
  // 측지 원점 — NED (0,0)이 지구상 어디인가. 엔진은 보지 않고 결과 meta에만 실린다.
  // 끄면 3D 월드가 지형을 얹지 못한다(같은 N·E가 어디인지 모르므로).
  originOn: true,
  originLat: String(GOHEUNG.originLatDeg),
  originLon: String(GOHEUNG.originLonDeg),
  // 장주 미션은 280 s 안팎에 선다(실측). 320은 그 위의 여유다 — 짧으면 서기 전에
  // 끊긴다. 정확한 시각은 실행 후 착륙 요약이 말한다(여기 적어 두면 조용히 낡는다).
  tEnd: "320",
  // 도달 반경 [기본값] — 300 m. **너무 작으면 경로가 끝나지 않는다**: 순항 88 m/s·
  // 뱅크 한계 0.7 rad에서 선회 반경이 938 m라 LOS 추종이 임의로 작은 원을 못 잡고
  // 목표를 지나쳤다 되돌기를 반복한다(선회 예상 전환이 꺾임점은 덮지만 **마지막
  // 웨이포인트**에는 다음 구간이 없어 도달 반경만 남는다). 그 하한은 웨이포인트
  // 기하 × 선회 성능의 함수라 상수가 아니고, 화면이 제출 전에 판정해 사유를 낸다
  // (lib/wpcheck.js — 선회 반경의 1/4인 235 m 아래를 경고한다. 300은 그 위다).
  accept: "300",
  navOn: true,
  seed: "11",
  actOn: true,
  wn: String(ACT_FALLBACK.wn),
  zeta: String(ACT_FALLBACK.zeta),
  rate: String(ACT_FALLBACK.rate),
  fuelFlow: "0.3",
  useGains: false,
  useAp: false,
  useScas: false,
  fp: "web-sim-v1",
});

/** 블록도에서 '시뮬에 적용'한 값들 — 조립이 store를 직접 읽지 않도록 getter를 받는다
 *  (lib는 store를 모른다). 제출 **순간에** 읽어야 한다: 폼을 연 시점이 아니라. */
export const APPLIED_KEYS = Object.freeze([
  "navParams", "actuatorParams", "gainTables", "autopilotParams", "scasParams",
]);

export function appliedFrom(get) {
  return Object.fromEntries(APPLIED_KEYS.map((k) => [k, get(k)]));
}

/** 폼 초기값 — 블록도 작동기 적용값이 있으면 그 값이 칸에 앉는다(최종 편집권은 폼). */
export function initialForm(actuatorParams = null) {
  const out = { ...DEFAULT_FORM };
  if (actuatorParams) {
    for (const [key, name] of Object.entries(ACT_SCHEMA_KEY)) {
      const v = actuatorParams[name];
      if (v !== undefined && v !== null) out[key] = String(v);
    }
  }
  return out;
}

/** 레지스트리 스키마 기본값을 **손대지 않은 칸에만** 채운다.
 *
 *  폴백(위 ACT_FALLBACK)은 엔진 기본값의 사본이라 조용히 어긋날 수 있다 — 항법
 *  기본값 7개가 어긋난 채 돌던 전례(01 v0.19)가 그것이다. 사용자가 고친 칸은
 *  건드리지 않는다: 고친 값을 스키마가 덮으면 편집이 조용히 사라진다. */
export function applyActuatorSchema(form, schema) {
  const out = { ...form };
  for (const [key, name] of Object.entries(ACT_SCHEMA_KEY)) {
    const d = schema?.properties?.[name]?.default;
    if (d !== undefined && out[key] === String(ACT_FALLBACK[key])) out[key] = String(d);
  }
  return out;
}

/** 빈 칸은 0이 아니라 NaN — JSON에서 null이 되어 서버가 422로 답한다.
 *  `Number("")`가 0인 것이 조용한 오답의 통로다. */
function blankIsNaN(value) {
  return String(value).trim() === "" ? NaN : Number(value);
}

/** 폼 값 + 표 → `{req, snapshot, missing}`.
 *
 *  - `snapshot`은 **제출 시점의 웨이포인트·도달 반경**이다(리뷰 S3) — 실행 중
 *    편집이 재생 오버레이를 오염시키지 않게. `waypoints` 키를 지우기 **전에** 뜬다.
 *  - `missing`은 "편집값을 쓰겠다고 켰는데 적용본이 없다"는 사실이다 — 조용히
 *    기본값으로 도는 대신 화면이 말한다.
 *  - 표가 틀리면 buildModes·buildWaypoints가 **던진다**(검증 정본) — 여기서
 *    잡아 고치지 않는다.
 */
export function buildSimRequest(form, modeRows, wpRows, applied = {}) {
  const req = {
    trim: {
      name: "start",
      mach: Number(form.mach), alt: Number(form.alt), fuel: Number(form.fuel),
      // 지상 평형인지 수평비행인지 — 활주로가 있으면 발사대/활주로 위 정지에서
      // 출발한다. 엔진이 mach=0을 요구하므로 둘이 어긋나면 서버가 422로 답한다
      condition: form.groundOn ? "ground" : "level",
    },
    modes: buildModes(modeRows),
    waypoints: buildWaypoints(wpRows),
    accept_radius: Number(form.accept),
    t_end: Number(form.tEnd),
    // 활주로가 있어야 스키드가 달린다 — 없으면 지면 자체가 없어서 기체가
    // h<0을 그대로 통과한다(접지·정지 판정도 불가). 표고는 시작 고도 칸과 같다.
    ...(form.groundOn ? { runway: {
      elevation: Number(form.alt),
      heading: Number(form.rwHeading),
      length: Number(form.rwLength),
    } } : {}),
    // 빈 칸을 Number()에 그대로 넘기면 0이 된다 — 오타(NaN→null→422)와 달리
    // (0,0)은 **유효하고 그럴듯한 틀린 값**이라 기니만 앞바다가 결과 meta에 박힌 채
    // 저장된다. 다른 칸은 서버 제약(length gt=0 등)이 막아 주지만 원점은 안 막힌다.
    ...(form.originOn ? { origin: {
      lat: blankIsNaN(form.originLat),
      lon: blankIsNaN(form.originLon),
    } } : {}),
    ...(form.launchOn ? { launch: {
      length: Number(form.railLen),
      elev_angle: Number(form.railAngle),
      exit_speed: Number(form.railExit),
    } } : {}),
    fuel_flow: Number(form.fuelFlow),
    fingerprint: form.fp,
  };
  const snapshot = { // 제출 시점 캡처 (리뷰 S3)
    waypoints: req.waypoints ?? [],
    acceptRadius: req.accept_radius,
  };
  if (req.waypoints === null) delete req.waypoints;
  if (form.navOn) {
    // 미지정 파라미터는 엔진 ParamDef 기본값이 채운다 — 여기서 기본값을 다시 적으면
    // 엔진과 조용히 어긋난다(실제로 7개가 어긋난 채 돌고 있었다). 빈 dict도 오차
    // 모델은 장착 — 미장착은 nav 필드 자체를 생략하는 경우뿐 (routes/sim.py::_build)
    req.nav = { ...(applied.navParams ?? {}), seed: Number(form.seed) };
    // 등급은 **이름으로** 고른다 — RTK 수치를 여기 적으면 엔진 RTK_FIXED와 어긋난다
    if (form.rtkOn) req.nav_grade = "rtk";
  }
  if (form.actOn) {
    // 블록도 작동기 블록 적용값(pos 한계·initial 포함) 위에 폼 칸이 최종 덮어씀
    req.actuators = { ...(applied.actuatorParams ?? {}),
                      wn: Number(form.wn), zeta: Number(form.zeta),
                      rate_max: Number(form.rate) };
  }
  // 편집본 체크됐는데 적용본이 없으면 기본값 실행을 조용히 하지 않고 알림 (리뷰 Nit3)
  const missing = [];
  if (form.useGains) {
    if (applied.gainTables) req.gain_tables = applied.gainTables;
    else missing.push("편집 게인 (게인 탭 '시뮬에 적용' 필요)");
  }
  if (form.useAp) {
    if (applied.autopilotParams) req.autopilot = applied.autopilotParams;
    else missing.push("편집 AP (블록도 탭 오토파일럿 블록 '시뮬에 적용' 필요)");
  }
  if (form.useScas) {
    // 블록도 SCAS 축 편집값 — 세 축이 한 벌이다 (서버가 부분 주입을 거부한다)
    if (applied.scasParams) req.scas = applied.scasParams;
    else missing.push("편집 SCAS (블록도 탭 SCAS 축 페이지 '시뮬에 적용' 필요)");
  }
  return { req, snapshot, missing };
}
