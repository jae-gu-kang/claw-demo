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
 * 엔진의 발사 모델은 길이 10 m의 레일이다(`meta.launch.length`). 캐니스터 관은 1.7 m,
 * 상부 레일을 더해도 2.3 m다. 기체 위치는 시뮬이 준 대로 그리므로 사출되어 나오는
 * 그림이 되고, 캡션이 그 둘이 별개임을 밝힌다. 형상을 시뮬에 맞춰 늘이지 않는다 —
 * 그러면 화면이 없는 장비를 그리게 된다.
 */

import { finite, type LaunchMeta } from "./types.ts";

/** 모델에서 잰 값 [m·rad].
 *
 * 앞의 넷은 GLB의 **노드 translation과 메시 bbox**에서 직접 읽었고, 뒤의 둘은 생성
 * 스크립트가 정본이다 — glTF는 Blender의 Limit 컨스트레인트와 드라이버 상수를 내보내지
 * 않으므로 GLB만 보면 알 수 없다. 출처를 항목마다 밝혀 둔다.
 */
export const LAUNCHER_GEOMETRY = {
  /** 턴테이블 회전축 높이 (트레일러 기준) — GLB `Turntable.translation.y` */ turntableY: 0.92,
  /** 크래들 피벗 높이 (턴테이블 기준) — GLB `Cradle.translation.y` */ cradleY: 0.86,
  /** 캐니스터 포구의 크래들 로컬 Z — GLB `Box_Tubes` bbox 앞끝 (기준축은 −Z) */ muzzleZ: -0.94,
  /** 캐니스터 관 뒤끝 — GLB `Box_Tubes` bbox 뒤끝 */ tubeAftZ: 0.78,
  /** 상부 레일 앞끝 — GLB `Box_Rails` bbox */ railTipZ: -1.55,
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
} as const;

/** 발사관 구조 전장 [m] — 상부 레일 앞끝에서 캐니스터 관 뒤끝까지. 캡션이 이 수를 쓴다. */
export const LAUNCHER_SPAN =
  Math.abs(LAUNCHER_GEOMETRY.tubeAftZ - LAUNCHER_GEOMETRY.railTipZ);
/** 캐니스터 관 자체의 길이 [m]. */
export const CANISTER_LENGTH =
  Math.abs(LAUNCHER_GEOMETRY.tubeAftZ - LAUNCHER_GEOMETRY.muzzleZ);

export interface LauncherPose {
  /** `Turntable.rotation.y` [rad] */ turntableY: number;
  /** `Cradle.rotation.x` [rad] */ cradleX: number;
  /** `Jack_*.position.y` 오프셋 [m] — 접힘 자세 기준 하강량(음수) */ jackOffsetY: number;
  /** 포구 방향의 NED 단위벡터 — 테스트와 캡션이 읽는 검증 가능한 량 */
  boresightNed: [number, number, number];
  /** 지면 기준 포구 높이 [m] */ muzzleHeight: number;
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
  const pivotHeight = g.turntableY + g.cradleY;
  const muzzleHeight = pivotHeight + Math.abs(g.muzzleZ) * Math.sin(clamped);

  return {
    // **부호가 뒤집히는 자리** — 위 주석의 유도 참조.
    turntableY: -az,
    cradleX: clamped,
    jackOffsetY: -g.jackDrop,
    boresightNed: boresightNed(az, clamped),
    muzzleHeight,
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

  const originHeight = finite(launch.origin_height);
  if (originHeight !== null) {
    const dz = pose.muzzleHeight - originHeight;
    if (Math.abs(dz) > 0.05) {
      notes.push(
        `발사 원점(${originHeight.toFixed(1)} m)과 발사관 포구(${pose.muzzleHeight.toFixed(1)} m) 높이가 `
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
