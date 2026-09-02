/** 시뮬 결과의 타입 — 서버 `serialize.sim_result_dict`의 웹 쪽 거울.
 *
 * ## 결측은 null이다
 *
 * 엔진은 계측되지 않은 채널을 **NaN**으로 두고(`simulator.py`: "계측되지 않은 것과 값이
 * 0인 것을 화면에서 구분해야 한다"), 직렬화가 그것을 `null`로 바꾼다. 그래서 신호 배열의
 * 원소 타입이 `number | null`이다 — 이 `| null`을 지우면 타입이 거짓말을 하고, 화면은
 * 없는 값을 0으로 그리게 된다.
 *
 * 무한대는 문자열 `"inf"` / `"-inf"`로 온다(같은 직렬화기). 3D가 쓰는 채널에서는 나오지
 * 않지만, 타입이 그것을 숨기면 언젠가 `NaN`이 조용히 섞인다.
 */

export type Sample = number | null | "inf" | "-inf";

/** 시계열 한 줄. 길이는 `t`와 같다. */
export type Signal = Sample[];

export interface Signals {
  /** NED 북 [m] */ pn?: Signal;
  /** NED 동 [m] */ pe?: Signal;
  /** MSL 고도, 상방 + [m] */ h?: Signal;
  /** 3-2-1 오일러 [rad] */ phi?: Signal; theta?: Signal; psi?: Signal;
  /** 대기속도 [m/s] */ V?: Signal;
  /** 받음각·옆미끄럼각 [rad] */ alpha?: Signal; beta?: Signal;
  mach?: Signal;
  /** 상승률, 상방 + [m/s] */ hdot?: Signal;
  /** 엘레본 collective(피치) [rad] — TE down + */ de?: Signal;
  /** 엘레본 differential(롤) [rad] */ da?: Signal;
  /** 러더 [rad] — TE left + */ dr?: Signal;
  /** 스로틀 0~1 */ thr_l?: Signal; thr_r?: Signal;
  /** 동체 각속도 [rad/s] */ p?: Signal; q?: Signal; r?: Signal;
  /** 실속 마진 */ alpha_margin?: Signal;
  /** 착륙장치 수직반력 합 [N] — 장치가 없으면 전 구간 null */ n_gear?: Signal;
  /** 레일 축방향 하중 [g] */ launch_gx?: Signal;
  limiter_active?: (boolean | null)[];
  wow?: (boolean | null)[];
  on_rail?: (boolean | null)[];
  /** 표본마다의 모드 이름 */ mode?: string[];
  [channel: string]: Signal | (boolean | null)[] | string[] | undefined;
}

/** 측지 원점 — **결과 쪽 키 이름**(`lat`/`lon`). 지형 팩은 `lat_deg`/`lon_deg`를 쓴다.
 *  키가 다른 것이 우연한 일치를 막아 주므로 통일하지 않는다(`world3d.originsAgree`). */
export interface ResultOrigin {
  lat: number; lon: number; datum?: string; h_ref?: number; h_ref_src?: string;
}

/** 기체 기준량 — 형상을 여기서 받는다. 엔진 기본값을 웹이 재기술하지 않는다. */
export interface Geometry {
  s_ref: number; cbar: number; b: number;
  /** 스키드 접촉점 (FRD, [x, y, z] m). 장치가 없으면 없다. */
  gear_contacts?: [number, number, number][];
}

export interface RunwayMeta { elevation: number; heading: number; length: number }

/** 발사 파라미터. **지금 엔진은 레일 모델이고 화면은 발사관을 그린다** — 형상은
 *  `elev_angle`·`azimuth`만 공유하고 나머지는 시뮬 쪽 수치다(`scene/Launcher.ts` 참조). */
export interface LaunchMeta {
  length: number; elev_angle: number; azimuth: number;
  exit_speed?: number | null; accel?: number | null; origin_height: number;
}

export interface Phases {
  launch_exit_t?: number | null; touchdown_t?: number | null; stop_t?: number | null;
  td_sink_rate?: number | null; td_speed?: number | null;
}

/** 작동기·타면 한계 — `simulator._effector_limits`가 **다섯 키를 항상** 낸다.
 *
 * **미장착·미상은 0이 아니라 `null`이다**(그쪽 독스트링). `| null`을 지우면 이 파일
 * 머리말이 금하는 그 거짓말이 되고, `limits.rate_max!`를 쓴 다음 사람이 null로 산술한다.
 *
 * 앞의 넷은 위치 한계 [rad]이고 **믹서가 정본**(`fcl/mixer.py`).
 * `rate_max`는 **작동기**에서 온다(`plant/actuator.py`) — 단위가 rad/s로 다르다.
 */
export interface Limits {
  elevon_lo?: number | null; elevon_hi?: number | null;
  rudder_lo?: number | null; rudder_hi?: number | null;
  rate_max?: number | null;
}

/** `meta`는 **오래된 결과일수록 비어 있다** — 필드마다 없을 수 있고, 화면은 각 부재를
 *  사유 문장으로 말해야 한다(있는 척 기본값을 채우지 않는다). */
export interface ResultMeta {
  control_hz?: number; dt_plant?: number; t_end?: number;
  limits?: Limits;
  nav?: string; actuators?: boolean; case?: string; aborted?: string | null;
  geometry?: Geometry;
  runway?: RunwayMeta;
  launch?: LaunchMeta;
  origin?: ResultOrigin;
  phases?: Phases;
  waypoints?: number[][] | null;
  accept_radius?: number | null;
  [k: string]: unknown;
}

export interface Envelope {
  stall_margin?: Signal;
  flags?: Record<string, (boolean | null)[]>;
  worst_margin?: number | null; worst_margin_t?: number | null;
  min_alt?: number | null; min_alt_t?: number | null;
  any_flag?: boolean; first_flag_t?: number | null;
}

/** `/api/sim/{id}/replay?stride=N`의 응답. */
export interface Replay {
  t: number[];
  signals: Signals;
  envelope?: Envelope;
  meta?: ResultMeta;
  params_fingerprint?: string;
  /** 다운샘플 전 표본 수 — 캡션이 "1,430 / 20,000"을 말할 수 있게 */
  n_total?: number;
  stride?: number;
}

export interface ResultRow { id: string; kind: string; created: number }

/** 유한한 수만 통과시킨다 — `"inf"`·null·NaN은 전부 null로. */
export function finite(v: Sample | undefined): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}
