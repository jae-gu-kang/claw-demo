/** 발사관 관절 — `meta.launch` → 캐니스터 발사관 모델의 노드 값 (NED·m·rad 입력).
 *
 * ## 부호가 조용히 틀릴 수 있는 자리
 *
 * NED 방위각 ψ는 **북에서 시계방향**이 양수다(`docs/conventions.md` §1). 렌더러 월드는
 * `x = E, y = 위, z = −N`이고, three의 `rotation.y = θ`는
 *
 *     (0, 0, −1) ─θ→ (−sin θ, 0, −cos θ)
 *
 * 즉 포구 기준축인 로컬 −Z가 **북에서 서쪽으로** 돈다(반시계). 우리가 원하는 것은
 * 북에서 동쪽이므로 **`rotation.y = −ψ`** 다. 모델 README의 "azimuth + = 좌현 선회"와
 * 같은 말이다.
 *
 * **데모 결과의 `azimuth`가 0.0이라 부호가 뒤집혀도 화면이 멀쩡해 보인다.** 회귀가
 * 눈으로 안 잡히는 부류라 ψ = 90°(정동) 케이스를 테스트가 못박는다.
 *
 * 고각은 `rotation.x = +elev_angle`이 포구를 든다: (0,0,−1) → (0, sin φ, −cos φ).
 * 크래들이 턴테이블의 자식이라 **선회한 뒤 그 자세에서** 고각이 붙는다 — 실장비의
 * 트러니언 거동과 같고, 그래서 두 각을 곱하는 순서를 이 모듈이 정하지 않아도 된다.
 *
 * ## 시뮬은 레일이고 화면은 발사관이다
 *
 * 엔진의 발사 모델은 길이 10 m의 레일이다(`meta.launch.length`). 2026-09-02 재개정으로
 * 구조 전장이 9.7 m(캐니스터 관 7.2 m + 상부 레일)가 되어 시뮬 모델과 비슷해졌고,
 * "별개입니다" 캡션은 길이가 크게 다를 때(1.5배 초과)만 뜬다 — 지금 데모에선 안 뜬다.
 *
 * ## 확대 내력 (2026-09-02 재개정 — 높이는 낮추고 수평은 2배)
 *
 * 첫 확대(루트 스케일 2.0)는 **화면에 살지 못했다** — 생성 스크립트가 스케일을 부모화
 * 앞에 걸어 자식 `matrix_parent_inverse`가 0.5를 물려받았고, glTF에 Trailer 노드
 * scale 0.5로 실려 ×2가 통째로 상쇄됐다. 사용자가 계속 "작다·삐져나온다"고 본 원인.
 * 재개정에서 (1) 스케일을 부모화 뒤로 옮겨 ×2를 살리고, (2) 로컬 기하 자체를 수평만
 * 2배·수직은 낮춤(축 3.56→2.90 m)으로 다시 팠다. 비균일 루트 스케일을 안 쓴 이유:
 * 회전 관절(고각·방위)이 축을 섞는 순간 기하가 일그러지고 바퀴가 타원이 된다.
 * 트러니언은 관 뒤끝 근처로 옮겼다 — 7.6 m 관이 중앙 피벗으로 들리면 뒤끝이 상판을
 * 뚫는다. 시뮬 기본 `origin_height`는 2.9 m로 올려져 있다(엔진 `RAIL_ORIGIN_H`,
 * 관축 시작점 2.83 m와 정합) — 그 이전에 저장된 결과는 1.2 m를 들고 있으므로
 * 캡션의 높이 차이 줄이 그 결과에서만 선다.
 *
 * ## 3차 수정 (같은 날) — 관 뒤끝에 맞췄더니 기체 꼬리가 관 밖으로 나왔다
 *
 * 관축 시작점(관 뒤끝)을 레일 원점에 그대로 맞추면, 기체 GLB의 원점(≈ 무게중심)이
 * 관 뒤끝에 서는 셈이다. 그런데 `shahed136.glb`는 원점 뒤로 꼬리·프로펠러가
 * `VEHICLE_AFT_EXTENT`(1.90 m)만큼 뻗어 있다 — 실물 축척 1:1로 놓이므로(`MODEL_SCALE`,
 * `SceneController.ts`) 그 1.90 m가 고스란히 관 밖으로 삐져나왔다. 포구 쪽(1.75 m)은
 * 관이 7.22 m나 남아 있어 문제가 없었던 것과 대비된다. 관축 시작점 자체(`tubeAftZ`,
 * 물리 구조물)는 그대로 두고, **배치 기준점만** 관 안쪽(포구 방향)으로 그만큼 당겨
 * 잡는다 — 그 결과 발사관 전체가 기체보다 더 뒤로 밀리고, 관 뒤끝은 기체 원점보다
 * 1.90 m 뒤(관 밖이 아니라 안)에 남아 꼬리를 담는다.
 */

import { finite, type LaunchMeta } from "./types.ts";

/** 모델에서 잰 값 [m·rad].
 *
 * 앞의 넷은 GLB의 **노드 translation과 메시 bbox**에서 직접 읽었고, 뒤의 둘은 생성
 * 스크립트가 정본이다 — glTF는 Blender의 Limit 컨스트레인트와 드라이버 상수를 내보내지
 * 않으므로 GLB만 보면 알 수 없다. 출처를 항목마다 밝혀 둔다.
 */
export const LAUNCHER_GEOMETRY = {
  /** 턴테이블 회전축 높이 (트레일러 기준) — GLB `Turntable.translation.y` */ turntableY: 0.80,
  /** 크래들 피벗 높이 (턴테이블 기준) — GLB `Cradle.translation.y` */ cradleY: 0.65,
  /** 캐니스터 포구의 크래들 로컬 Z — GLB `Box_Tubes` bbox 앞끝 (기준축은 −Z).
   *  트러니언이 관 뒤끝 근처라 포구가 피벗에서 멀다(재개정 내력 참조). */ muzzleZ: -3.48,
  /** 캐니스터 관 뒤끝 — GLB `Box_Tubes` bbox 뒤끝 (피벗 살짝 뒤) */ tubeAftZ: 0.13,
  /** 상부 레일 앞끝 — GLB `Box_Rails` bbox */ railTipZ: -4.70,
  /** 루트→턴테이블 축 로컬 Z — GLB `Turntable.translation.z`. 트레일러 프레임이라
   *  방위와 무관하게 고정이다(트레일러는 선회하지 않는다). */ turntableAftZ: 0.90,
  /** 턴테이블→크래들 피벗 로컬 Z — GLB `Cradle.translation.z`. 턴테이블의 자식이라
   *  **방위와 함께 돈다.** */ cradleAftZ: 0.90,
  /** 크래들 가동 범위 — `generate_launcher.py`의 `PROPS`(317~319행)와 모델 README 표.
   *
   * **`LIMIT_ROTATION` 컨스트레인트가 아니다.** 그쪽은 크래들 −2~52°, 턴테이블 ±110°로
   * 일부러 더 느슨한 오버트래블 여유다. 그 값으로 "고쳤다"가는 −2~0° 구간에서 잘림
   * 판정이 안 뜨는데 캡션은 계속 0~48°라고 말하게 된다. */
  elevMin: 0, elevMax: (48 * Math.PI) / 180,
  /** 방위 가동 범위 — 같은 출처. **여기서 자르지 않는다**(아래 캡션 참조) */
  azMin: (-100 * Math.PI) / 180, azMax: (100 * Math.PI) / 180,
  /** 아웃리거 전개 행정 — `generate_launcher.py`의 `JACK_TRAVEL` (GLB에는 안 실린다) */
  jackDrop: 0.46,
  /** GLB 루트 노드 스케일 — `generate_launcher.py`의 `root.scale`. 로컬 값(위 전부)을
   *  지면 기준 미터로 바꿀 때만 곱한다. 관절 값은 로컬이라 곱하지 않는다. */
  rootScale: 2.0,
  /** 포구 문 두 짝(`Door_L`·`Door_R`)이 다 열린 각 [deg] — `generate_launcher.py`의 `DOOR_OPEN`(드라이버 상수라
   *  GLB에는 안 실린다. 두 원문을 `test_generate_launcher.py`가 대조한다). 직각을 넘겨 문이 통로 밖으로 비킨다. */
  doorOpenDeg: 115,
} as const;

/** 기체(`shahed-136/shahed136.glb`) 원점(≈ 무게중심)에서 꼬리·프로펠러 끝까지 로컬
 *  +Z(후방) 거리 [m, 실물 축척]. 기체 모델은 `rootScale` 없이 1:1로 놓이므로
 *  (`MODEL_SCALE`, `scene/SceneController.ts`) 이 값도 미터 그대로 더한다.
 *  GLB 노드 좌표 실측: bbox z ∈ [−1.75, 1.90] → 원점 뒤(+Z) 최댓값 1.90. */
const VEHICLE_AFT_EXTENT = 1.90;

/** 발사관 구조 전장 [m, 지면 기준] — 상부 레일 앞끝에서 캐니스터 뒤끝까지. 캡션이 쓴다. */
export const LAUNCHER_SPAN =
  Math.abs(LAUNCHER_GEOMETRY.tubeAftZ - LAUNCHER_GEOMETRY.railTipZ) * LAUNCHER_GEOMETRY.rootScale;
/** 캐니스터 박스 자체의 길이 [m, 지면 기준]. */
export const CANISTER_LENGTH =
  Math.abs(LAUNCHER_GEOMETRY.tubeAftZ - LAUNCHER_GEOMETRY.muzzleZ) * LAUNCHER_GEOMETRY.rootScale;

export interface LauncherPose {
  /** `Turntable.rotation.y` [rad] */ turntableY: number;
  /** `Cradle.rotation.x` [rad] */ cradleX: number;
  /** `Jack_*.position.y` 오프셋 [m] — 접힘 자세 기준 하강량(음수) */ jackOffsetY: number;
  /** 포구 방향의 NED 단위벡터 — 테스트와 캡션이 읽는 검증 가능한 량 */
  boresightNed: [number, number, number];
  /** 지면 기준 포구 높이 [m] */ muzzleHeight: number;
  /** 지면 기준 관축 시작점(관 뒤끝) 높이 [m] — 발사 원점과 비교하는 기준.
   *  트러니언이 관 뒤에 있어 고각을 들면 이 점은 오히려 **내려간다**. */
  breechHeight: number;
  /** 발사관 루트를 놓을 자리 = 발사 지점 + 이 오프셋 [NED, m]. 관 뒤끝(`tubeAftZ`)이
   *  아니라 그보다 `VEHICLE_AFT_EXTENT`만큼 관 안쪽인 지점을 레일 원점 위에 오도록
   *  수평만 민다 — 그래야 기체 꼬리가 관 밖으로 나오지 않는다. 시뮬에 발사관 위치는
   *  없으므로 이 배치는 표시용 선택이고 캡션이 밝힌다. */
  rootOffsetNed: [number, number, number];
  /** 고각이 가동 범위를 벗어나 잘렸나 */ elevationClamped: boolean;
}

/** NED 방위 ψ·고각 φ에서 기준축의 NED 단위벡터 [n, e, d]. d는 하방 +. */
export function boresightNed(azimuth: number, elevation: number): [number, number, number] {
  const c = Math.cos(elevation);
  return [c * Math.cos(azimuth), c * Math.sin(azimuth), -Math.sin(elevation)];
}

/** `meta.launch` → 관절 값. 필요한 각이 결측이면 **null**(발사관을 그리지 않는다). */
export function launcherPose(launch: LaunchMeta | null | undefined): LauncherPose | null {
  const az = finite(launch?.azimuth);
  const el = finite(launch?.elev_angle);
  if (az === null || el === null) return null;

  const g = LAUNCHER_GEOMETRY;
  const clamped = Math.min(Math.max(el, g.elevMin), g.elevMax);

  // 포구 높이: 크래들 피벗에서 기준축을 따라 |muzzleZ| 만큼 나간 자리의 높이.
  // 로컬 값이라 지면 기준 미터로는 rootScale을 곱한다.
  const pivotHeight = g.turntableY + g.cradleY;
  const muzzleHeight =
    (pivotHeight + Math.abs(g.muzzleZ) * Math.sin(clamped)) * g.rootScale;
  // 관축 시작점(관 뒤끝, 피벗 뒤 tubeAftZ): 고각을 들면 뒤끝은 **내려간다**.
  const breechHeight = (pivotHeight - g.tubeAftZ * Math.sin(clamped)) * g.rootScale;

  // 루트 배치 오프셋: 관 뒤끝(tubeAftZ)이 아니라 그보다 기체 꼬리 길이만큼 관 안쪽인
  // 지점(anchorZ)을 시뮬 레일 원점 위(수평)에 오게 루트를 민다 — 관 뒤끝 그대로 맞추면
  // 기체 원점이 곧 관 뒤끝이 되어 꼬리(VEHICLE_AFT_EXTENT)가 관 밖으로 남는다.
  // 루트→턴테이블(트레일러 프레임, 방위 무관) + 턴테이블→크래들·anchorZ(방위와
  // 함께 도는 수평 성분). 수직은 밀지 않는다 — 트레일러는 지면에 선다.
  const anchorZ = g.tubeAftZ - VEHICLE_AFT_EXTENT / g.rootScale;
  const yawR = (g.cradleAftZ + anchorZ * Math.cos(clamped)) * g.rootScale;
  const rootOffsetNed: [number, number, number] = [
    (g.turntableAftZ * g.rootScale) + yawR * Math.cos(az),
    yawR * Math.sin(az),
    0,
  ];

  return {
    // **부호가 뒤집히는 자리** — 위 주석의 유도 참조.
    turntableY: -az,
    cradleX: clamped,
    jackOffsetY: -g.jackDrop,
    boresightNed: boresightNed(az, clamped),
    muzzleHeight,
    breechHeight,
    rootOffsetNed,
    elevationClamped: clamped !== el,
  };
}

const deg = (rad: number): string => ((rad * 180) / Math.PI).toFixed(0);

/** 화면이 밝혀야 할 불일치 — 없으면 null(캡션에 줄이 안 생긴다). */
export function launcherCaptionNotes(
  launch: LaunchMeta | null | undefined,
  pose: LauncherPose | null,
): string[] {
  if (pose == null || launch == null) return [];
  const notes: string[] = [];

  // 배치는 표시용 선택이다 — 시뮬에 발사관 위치가 없으므로, 관축 시작점이 레일
  // 원점 위에 오게 트레일러를 밀어 놓았다. 선택인 이상 조건 없이 밝힌다.
  notes.push("발사관 위치는 시뮬에 없습니다 — 관축 시작점이 발사 원점 위에 오도록 놓은 표시용 배치입니다.");

  const originHeight = finite(launch.origin_height);
  if (originHeight !== null) {
    // 비교 기준은 포구가 아니라 **관축 시작점**이다 — 트러니언이 관 뒤에 있어
    // 포구는 원점에서 관 길이만큼 나간 자리라 높이가 다른 게 정상이다.
    // 문턱 0.15 m: 4 m급 구조물에서 그보다 작은 차이는 화면에서 식별되지 않는데
    // 줄이 서면 없는 문제를 지어내는 쪽이 된다.
    const dz = pose.breechHeight - originHeight;
    if (Math.abs(dz) > 0.15) {
      notes.push(
        `발사 원점(${originHeight.toFixed(1)} m)과 발사관 관축 시작점(${pose.breechHeight.toFixed(1)} m) 높이가 `
        + `${Math.abs(dz).toFixed(1)} m 다릅니다 — 트레일러를 지면에 두었고 기체는 시뮬이 준 자리에 있습니다.`,
      );
    }
  }

  const len = finite(launch.length);
  if (len !== null && len > LAUNCHER_SPAN * 1.5) {
    notes.push(
      `발사 구간은 ${len.toFixed(0)} m 가속 모델이고 발사관 형상(캐니스터 관 `
      + `${CANISTER_LENGTH.toFixed(1)} m · 상부 레일까지 ${LAUNCHER_SPAN.toFixed(1)} m)과 별개입니다.`,
    );
  }

  if (pose.elevationClamped) {
    // 범위를 **상수에서 만든다** — 하드코딩하면 상수를 바꿨을 때 캡션만 옛 값을 말한다.
    notes.push(
      `발사관 고각이 모델 가동 범위(${deg(LAUNCHER_GEOMETRY.elevMin)}~`
      + `${deg(LAUNCHER_GEOMETRY.elevMax)}°)를 벗어나 잘렸습니다.`,
    );
  }

  // **방위는 자르지 않는다.** 자르면 화면이 기체가 나간 방향과 다른 쪽을 겨눈 발사관을
  // 그리게 되고, 그건 잘렸다는 사실보다 나쁜 거짓말이다. 대신 말한다.
  const az = finite(launch.azimuth);
  if (az !== null) {
    const wrapped = Math.atan2(Math.sin(az), Math.cos(az));
    if (wrapped < LAUNCHER_GEOMETRY.azMin || wrapped > LAUNCHER_GEOMETRY.azMax) {
      notes.push(
        `발사 방위 ${deg(wrapped)}°는 실장비 선회 범위(${deg(LAUNCHER_GEOMETRY.azMin)}~`
        + `${deg(LAUNCHER_GEOMETRY.azMax)}°)를 벗어납니다 — 화면은 시뮬이 준 방향 그대로 그립니다.`,
      );
    }
  }
  return notes;
}

// ---------------------------------------------------------------- 포구 문과 발사 전주
//
// 시뮬에는 문이 없다. 레일 발사는 시각 0에 바로 가속해 0.6 s 안에 끝나므로(데모 결과 실측 — 기수가 포구에 닿는 데
// 약 0.36 s), 문을 시각 0부터 열면 한 프레임 만에 튀어 열린다. 그래서 **처음부터 재생할 때만** 시뮬 시각 0에 머무는
// 전주(前奏)를 두어 문을 먼저 열고, 그다음 발사를 흘린다. 커서가 0을 지난 뒤엔 문은 늘 열려 있다 — 커서를 끌어
// 어느 시점으로 가도 화면이 같은 말을 한다. 전주는 벽시계로 돈다(시뮬 시각이 아니다) — 캡션이 밝힌다.

/** 문이 다 열리는 시간 [s, 벽시계·배속 1]. */
export const DOOR_OPEN_S = 1.2;
/** 전주 길이 [s] — 문이 다 열리고 잠깐 선 뒤 발사한다. 멈추기도 전에 나오면 기체가 문을 쳐 내는 것처럼 보인다. */
export const PRELUDE_S = 1.5;

const clamp01 = (v: number): number => Math.min(Math.max(v, 0), 1);

/** 전주 시각을 한 프레임 진행한다. **배속은 1배까지만 탄다** — 기본 5×로 돌리면 문이 0.3 s에 튀어 열린다. 느린
 *  배속(0.5×)은 그대로 느리게. 벽시계가 뒤로 가도(탭 복귀 등) 되감지 않는다. */
export function advancePrelude(preT: number, dtWall: number, speed: number): number {
  return Math.min(PRELUDE_S, preT + Math.max(dtWall, 0) * Math.min(Math.max(speed, 0), 1));
}

/** 문 열림 0(닫힘)…1(다 열림). 시뮬 표본 `idx`가 0을 지났으면 1, 아니면 전주 시각을 따라 매끄럽게(smoothstep)
 *  — 액추에이터가 서서히 밀고 서서히 세운다. */
export function doorOpenFraction(idx: number, preT: number): number {
  if (idx > 0) return 1;
  const u = clamp01(preT / DOOR_OPEN_S);
  return u * u * (3 - 2 * u);
}

/** 열림 → 두 짝의 three `rotation.y` [rad]. 경첩이 수직(로컬 Y)이고 포구는 로컬 −Z다: 우현(+x) 문은 **−각**,
 *  좌현(−x) 문은 **+각**이 바깥·앞으로 연다(테스트가 회전을 실제로 적용해 확인한다). */
export function doorRotations(f: number): { left: number; right: number } {
  const a = clamp01(f) * LAUNCHER_GEOMETRY.doorOpenDeg * (Math.PI / 180);
  return { left: a, right: -a };
}

/** 첫 표본에서 기체가 관 안(레일 위)인가 — 아니면 문을 닫아 둘 까닭이 없다(이미 날고 있는 결과). 레일 표지가
 *  없는 옛 결과는 `meta.launch`가 있다는 것 자체를 믿는다(발사 정보가 있으면 시각 0은 레일 위다). */
export function startsInCanister(onRail0: boolean | null | undefined): boolean {
  return onRail0 !== false;
}

/** 문이 있는 발사관을 보일 때 캡션이 밝히는 줄 — 문과 전주는 시뮬에 없는 표시다. */
export const LAUNCHER_DOOR_NOTE =
  "발사관 문은 표시용입니다 — 시뮬에는 문이 없어, 처음부터 재생하면 문이 열린 뒤(약 1.5초, 시뮬 시각은 0에 머묾) 발사가 흐릅니다.";
