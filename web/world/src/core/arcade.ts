/** 게임 모드 아케이드 비행 — **표시·계획 전용 운동학**이며 엔진 동역학이 아니다.
 *
 * ## 왜 실제 엔진이 아닌가
 *
 * 게임 모드의 몫은 "날아다니며 마음에 드는 지점을 찍는" 것이고, 그렇게 찍은
 * 웨이포인트를 검증하는 것은 시뮬레이션 탭(실제 엔진)의 몫이다 — 사용자가 정한
 * 분업이다. 여기서 엔진을 돌리면 잡 왕복 지연이 조작감을 죽이고, 무엇보다
 * "아케이드로 느낀 비행"이 실제 성능이라는 인상을 주게 된다. 캡션이 이 사실을
 * 말한다(`SceneController`).
 *
 * ## 좌표는 NED·rad·m — 이 저장소의 유일 규약
 *
 * 자세는 (φ, θ, ψ)로 내고, 렌더는 `eulerToQuat` → `bodyAxesNed` → `setVehiclePose`의
 * 기존 경로를 그대로 탄다. 여기서 새 사상을 만들면 재생 기체와 게임 기체가 서로
 * 다른 자세 규약을 갖게 된다.
 */

export interface ArcadeState {
  /** NED [m] */
  pos: [number, number, number];
  /** 기수 방위 [rad] */
  psi: number;
  /** 피치 [rad] — 운동학에 쓴다(상승률 = V·sinθ) */
  theta: number;
  /** 롤 [rad] — **표시 전용** 뱅크. 선회는 ψ 적분이 낸다 */
  phi: number;
  /** 속력 [m/s] */
  V: number;
}

/** 키 입력의 정규화 축 — 각각 −1‥+1. */
export interface ArcadeInput {
  /** +1 = 우선회 */
  turn: number;
  /** +1 = 상승 */
  pitch: number;
  /** +1 = 가속 */
  throttle: number;
}

/** 조작 상수 — 전부 **게임 감각**으로 고른 표시 값이다(실기 성능 아님).
 *  vMin을 0으로 두지 않는 이유: 정지하면 체이스 카메라의 진행 방향이 사라져
 *  시점이 튄다(`travelDirection`의 폴백 조건을 항상 피한다). */
export const ARCADE = {
  vMin: 22,
  vMax: 90,
  accel: 14,          // [m/s²]
  turnRate: 0.75,     // [rad/s] 최대 선회율
  pitchMax: 0.38,     // [rad] ≈ 22°
  bankMax: 0.75,      // [rad] 표시 뱅크 한계
  pitchTau: 0.35,     // [s] 피치 응답 시정수
  bankTau: 0.22,      // [s] 뱅크 응답 시정수
  floor: 8,           // [m] 지면 위 최저 높이 — 계획 도구라 추락 대신 스침
} as const;

const clamp = (v: number, lo: number, hi: number): number => Math.min(Math.max(v, lo), hi);
const axis = (v: number): number => (Number.isFinite(v) ? clamp(v, -1, 1) : 0);

/** 출발 상태 — 활주로 방위·표고를 알면 그 위 150 m에서 그 방향으로 난다.
 *  모르면 원점 상공 150 m·북향 — 지어내지 않고 "모른다"의 중립값이다. */
export function spawnArcade(
  runwayHeading: number | null, groundElev: number | null,
): ArcadeState {
  const elev = groundElev ?? 0;
  return {
    pos: [0, 0, -(elev + 150)],
    psi: runwayHeading ?? 0,
    theta: 0,
    phi: 0,
    V: 45,
  };
}

/** 한 걸음 — 순수 함수라 같은 입력이면 같은 결과다(테스트가 이 성질을 잡는다).
 *
 * @param groundElev 기체 발밑 지면 표고 [m] — 모르면 null(기준면 0으로 본다).
 *   `SceneController.groundElevationAt`과 같은 값을 넣어야 화면의 지면과 바닥
 *   클램프가 같은 면을 말한다. */
export function stepArcade(
  s: ArcadeState, input: ArcadeInput, dt: number, groundElev: number | null,
): ArcadeState {
  // rAF가 멈췄다 돌아온 큰 dt는 순간이동을 만든다 — 렌더 루프(step)의 0.25 s
  // 클램프와 같은 상한을 여기서도 진다(호출측을 믿지 않는다).
  const h = clamp(Number.isFinite(dt) ? dt : 0, 0, 0.25);
  const turn = axis(input.turn);
  const pitch = axis(input.pitch);
  const throttle = axis(input.throttle);

  const V = clamp(s.V + throttle * ARCADE.accel * h, ARCADE.vMin, ARCADE.vMax);

  // 1차 지연 — exp 형태라 dt가 흔들려도 응답 모양이 유지된다(오일러 배율식은
  // 큰 dt에서 오버슈트한다).
  const kPitch = 1 - Math.exp(-h / ARCADE.pitchTau);
  const kBank = 1 - Math.exp(-h / ARCADE.bankTau);
  let theta = s.theta + (pitch * ARCADE.pitchMax - s.theta) * kPitch;
  const phi = s.phi + (turn * ARCADE.bankMax - s.phi) * kBank;

  let psi = s.psi + turn * ARCADE.turnRate * h;
  // [−π, π)로 되돌린다 — 무한 적분을 두면 몇 분 뒤 표시 방위가 수천 도가 된다.
  if (psi >= Math.PI) psi -= 2 * Math.PI;
  if (psi < -Math.PI) psi += 2 * Math.PI;

  const cosT = Math.cos(theta);
  const n = s.pos[0] + V * cosT * Math.cos(psi) * h;
  const e = s.pos[1] + V * cosT * Math.sin(psi) * h;
  let d = s.pos[2] - V * Math.sin(theta) * h; // 상승 = d 감소 (NED)

  // 바닥 — 지면을 뚫는 대신 스치고, 내려가던 피치만 푼다(들어 올리지는 않는다 —
  // 사용자 입력을 덮어쓰면 조작감이 "빼앗겼다"로 읽힌다).
  const minD = -((groundElev ?? 0) + ARCADE.floor);
  if (d > minD) {
    d = minD;
    if (theta < 0) theta = 0;
  }

  return { pos: [n, e, d], psi, theta, phi, V };
}
