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
