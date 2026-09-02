/** GLB 로딩과 노드 결선 — 시뮬 상태가 관절을 몬다.
 *
 * ## 애니메이션 클립은 쓰지 않는다
 *
 * 두 GLB에는 데모 동작이 클립으로 구워져 있다(`"SHAHED-136"`, `"Launcher"`). **`AnimationMixer`를
 * 만들지 않는다** — 만들면 그 클립이 노드 회전을 매 프레임 덮어써서, 우리가 넣은 타면 각이
 * 조용히 사라진다. 화면은 그럴듯하게 움직이지만 시뮬과 무관한 동작이 된다.
 *
 * ## 없는 노드는 조용히 넘기지 않는다
 *
 * 모델을 다시 구우면서 노드 이름이 바뀌면 타면이 안 움직이게 되는데, 그건 "타면이 중립"과
 * 화면에서 구별되지 않는다. 그래서 **찾은 노드 목록과 못 찾은 이름을 함께** 돌려주고
 * 캡션이 그것을 말한다.
 *
 * ## 축
 *
 * 모델 로컬축(+X 우현, +Y 위, +Z 후방)에서 FRD로 가는 한 겹은 `core/modelaxes.ts`가
 * 흡수한다. 여기서는 그 결과 열벡터를 `toWorld`에 태워 행렬을 세우기만 한다 —
 * 축 사상은 여전히 `nedToRender` 한 곳이다.
 */

import {
  Box3, CircleGeometry, DoubleSide, Group, Matrix4, Mesh as ThreeMesh, MeshBasicMaterial,
  Vector3, type Material, type Mesh, type Object3D,
} from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";

import type { BodyAxes, Vec3 } from "../lib/attitude.ts";
import { modelColumnsNed } from "../core/modelaxes.ts";
import type { LauncherPose } from "../core/launcher.ts";
import type { SurfacePose } from "../core/surfaces.ts";
import { applyAerialPerspective } from "./atmosphere.ts";
import { WEAR_BY_MATERIAL, applyWear } from "./materials.ts";
import { disposeTree } from "./dispose.ts";
import { toWorld } from "./axes.ts";

/** 무인기에서 우리가 모는 노드 — 이름은 `models/shahed-136/README.md`가 정본. */
export const VEHICLE_NODES = [
  "Elevon_In_L", "Elevon_Out_L", "Elevon_In_R", "Elevon_Out_R",
  "Rudder_L", "Rudder_R", "Propeller",
] as const;

/** 발사관에서 우리가 모는 노드 — `models/launcher/README.md`가 정본. */
export const LAUNCHER_NODES = [
  "Turntable", "Cradle", "Jack_FL", "Jack_FR", "Jack_RL", "Jack_RR",
] as const;

export interface LoadedModel {
  root: Group;
  /** 이름 → 노드. 못 찾은 것은 여기 없다. */
  nodes: Map<string, Object3D>;
  /** 기대했는데 없던 이름 — 캡션이 말한다. */
  missing: string[];
  dispose(): void;
}

/** GLB 하나를 읽어 노드 손잡이를 만든다. 실패는 **던지지 않고** 사유를 낸다. */
export async function loadModel(
  url: string,
  expect: readonly string[],
  signal?: AbortSignal,
): Promise<{ model: LoadedModel; reason: null } | { model: null; reason: string }> {
  let gltf: { scene: Group; animations: unknown[] };
  try {
    gltf = await new GLTFLoader().loadAsync(url);
  } catch (e) {
    // 떠나면서 실패한 것을 "읽지 못했습니다"라고 하면 사용자가 없는 고장을 쫓는다.
    if (signal?.aborted) return { model: null, reason: "취소됨" };
    return { model: null, reason: `모델을 읽지 못했습니다 (${url}) — ${(e as Error).message}` };
  }
  if (signal?.aborted) {
    disposeTree(gltf.scene);
    return { model: null, reason: "취소됨" };
  }

  const nodes = new Map<string, Object3D>();
  const missing: string[] = [];
  for (const name of expect) {
    const o = gltf.scene.getObjectByName(name);
    if (o) nodes.set(name, o);
    else missing.push(name);
  }
  // **자동 갱신은 켠 채로 둔다**(three 기본값이기도 하다). `placeLauncher`가
  // `position.set`으로 자리를 옮기므로 꺼 두면 발사관이 원점에 얼어붙는다.
  // 기체 루트만 `setVehiclePose`가 행렬을 직접 쓰면서 그 자리에서 끈다.
  gltf.scene.matrixAutoUpdate = true;

  // **GLB 재질에 마모와 대기를 건다.** 대기를 빠뜨리면 30 km 밖 지형이 하늘로 녹아드는데
  // 기체만 또렷하게 남아, 배경에서 오려 붙인 것처럼 보인다. 마모는 재질 **이름**으로
  // 조회한다 — 이름이 목록에 없으면 민짜로 남을 뿐 실패하지 않는다(관 안쪽처럼 일부러
  // 뺀 것과 구별할 수 없기 때문에, 조용히 넘기는 쪽이 맞다). 재질은 한 GLB 안에서
  // 메시끼리 공유되기도 하므로 두 패처 모두 중복 호출을 흡수한다.
  gltf.scene.traverse((o) => {
    const m = (o as Mesh).material as Material | Material[] | undefined;
    if (!m) return;
    // 그림자를 드리우고 받는다 — 발사 장면과 착륙 롤아웃에서 기체를 지면에 정박시키는
    // 가장 싼 단서다. 캐스터가 GLB뿐이라 그림자 패스 비용도 GLB 삼각형만큼이다.
    o.castShadow = true;
    o.receiveShadow = true;
    for (const one of Array.isArray(m) ? m : [m]) {
      const wear = WEAR_BY_MATERIAL[one.name];
      if (wear) applyWear(one, wear);
      applyAerialPerspective(one);
    }
  });

  return {
    model: {
      root: gltf.scene,
      nodes,
      missing,
      dispose() {
        // 자원을 놓기 전에 씬에서 뗀다 — 안 떼면 빈 Group이 `modelGroup`에 쌓인다.
        gltf.scene.removeFromParent();
        disposeTree(gltf.scene);
      },
    },
    reason: null,
  };
}

/** 기체 자세 — 위치는 NED, 회전은 동체축에서 온다. */
export function setVehiclePose(
  model: LoadedModel,
  posNed: Vec3,
  axes: BodyAxes,
  scale = 1,
): void {
  const c = modelColumnsNed(axes);
  const x = toWorld(c.x[0], c.x[1], c.x[2]);
  const y = toWorld(c.y[0], c.y[1], c.y[2]);
  const z = toWorld(c.z[0], c.z[1], c.z[2]);
  const p = toWorld(posNed[0], posNed[1], posNed[2]);
  // 열이 (로컬X, 로컬Y, 로컬Z)인 회전 + 이동. three의 Matrix4.set은 **행 우선** 인자다.
  const m = new Matrix4().set(
    x[0] * scale, y[0] * scale, z[0] * scale, p[0],
    x[1] * scale, y[1] * scale, z[1] * scale, p[1],
    x[2] * scale, y[2] * scale, z[2] * scale, p[2],
    0, 0, 0, 1,
  );
  model.root.matrixAutoUpdate = false;
  model.root.matrix.copy(m);
  model.root.matrixWorldNeedsUpdate = true;
  model.root.visible = true;
}

/** 자세를 모르면 **그리지 않는다** — 0으로 놓으면 없는 수평비행을 지어낸다. */
export function hideVehicle(model: LoadedModel): void {
  model.root.visible = false;
}

/** 조종면 — `core/surfaces.ts`가 낸 각을 노드 회전에 넣는다.
 *
 * 축은 모델 README가 정본이다: 엘레본 `rotation.x`(TE down +), 러더 `rotation.y`(TE left +). */
export function applySurfaces(model: LoadedModel, pose: SurfacePose | null): boolean {
  // **결측이면 마지막 각을 유지한다** — 중립으로 튀면 없는 조종 입력을 그리게 되고,
  // 타면을 숨기면 날개에 구멍이 뚫린다. 다만 유지도 표시 선택이라, 그 사실을 호출측이
  // 알 수 있게 **적용 여부를 돌려준다**(`SURFACE_NOTES.holdOnMissing`이 문장이다).
  // 결측이 처음부터 끝까지면 타면이 정확히 0에 앉는데, 그건 "중립"과 구별되지 않는다.
  if (pose == null) return false;
  for (const [name, angle] of Object.entries(pose.elevon)) {
    const n = model.nodes.get(name);
    if (n) n.rotation.x = angle;
  }
  for (const name of ["Rudder_L", "Rudder_R"]) {
    const n = model.nodes.get(name);
    if (n) n.rotation.y = pose.rudder;
  }
  return true;
}

/** 프로펠러 — 각속도 [rad/s]를 적분하고, 빠르면 **블러 디스크로 갈아탄다.**
 *
 * 실사에서 도는 프로펠러는 블레이드가 아니라 반투명 원반으로 보인다 — 또렷한 블레이드가
 * 도는 것이 CG 티의 고전이다. 여기는 모션블러가 없으므로(분할 프러스텀 × 깊이) 원반을
 * 직접 만든다: 60 rad/s부터 원반이 배어 나오고 140에서 블레이드가 꺼진다.
 * `null`이면 돌리지도 갈아타지도 않는다 — 멈춘 채 둔다.
 *
 * 원반은 반투명이라 분할 프러스텀 겹침 구간(1.5~2 km)에서 두 번 섞일 수 있지만,
 * 그 거리에서 원반은 1 px 미만이다 — 실익이 없어 그대로 둔다. */
export function spinPropeller(model: LoadedModel, rate: number | null, dt: number): void {
  if (rate === null || !(dt > 0)) return;
  const n = model.nodes.get("Propeller");
  if (!n) return;
  n.rotation.z = (n.rotation.z + rate * dt) % (Math.PI * 2);

  let disc = n.userData.blurDisc as ThreeMesh | undefined;
  if (!disc) {
    // 반경은 지오메트리에서 잰다 — 모델을 다시 구워 프로펠러가 커져도 따라온다.
    const box = new Box3().setFromObject(n);
    const size = box.getSize(new Vector3());
    const r = Math.max(size.x, size.y) / 2;
    const mat = new MeshBasicMaterial({
      color: 0x1a1c1f, transparent: true, opacity: 0, side: DoubleSide, depthWrite: false,
    });
    applyAerialPerspective(mat);
    disc = new ThreeMesh(new CircleGeometry(r * 0.96, 48), mat);
    // 프로펠러의 부모에 단다 — 프로펠러 노드에 달면 rotation.z를 같이 타는데,
    // 원반은 회전 대칭이라 낭비일 뿐 아니라 z-속도가 블러 계산처럼 오해된다.
    disc.position.copy(n.position);
    disc.rotation.copy(n.rotation);
    disc.rotation.z = 0;
    n.parent?.add(disc);
    n.userData.blurDisc = disc;
  }
  const a = Math.min(Math.max((Math.abs(rate) - 60) / 80, 0), 1);
  (disc.material as MeshBasicMaterial).opacity = a * 0.38;
  disc.visible = a > 0.01;
  n.visible = a < 1;
}

/** 발사관 관절 — 방위·고각·아웃리거. 자세를 모르면 **적용하지 않고 false**를 낸다.
 *
 * 대개는 `showLauncher`를 쓰는 게 맞다 — 그쪽은 나쁜 상태를 표현할 수 없게 만든다. */
export function applyLauncher(model: LoadedModel, pose: LauncherPose | null): boolean {
  if (pose == null) return false;
  const t = model.nodes.get("Turntable");
  if (t) t.rotation.y = pose.turntableY;
  const c = model.nodes.get("Cradle");
  if (c) c.rotation.x = pose.cradleX;
  for (const tag of ["Jack_FL", "Jack_FR", "Jack_RL", "Jack_RR"]) {
    const j = model.nodes.get(tag);
    if (!j) continue;
    // 접힘 자세를 한 번만 기억한다 — 매 프레임 빼면 계속 내려간다.
    const rest = (j.userData.restY ?? (j.userData.restY = j.position.y)) as number;
    j.position.y = rest + pose.jackOffsetY;
  }
  return true;
}

/** 발사관을 발사 지점 곁에 놓는다 (NED). 방위·고각은 관절이 맡는다.
 *
 * 루트를 발사 지점에 그대로 두지 않는다 — 트러니언이 관 뒤에 있어 그러면 원점
 * 자리의 관축이 기체보다 1 m 높아 기체가 관 바닥을 뚫는다. 관 뒤끝을 원점에 그대로
 * 맞추지도 않는다 — 기체 원점 뒤로 뻗은 꼬리가 관 밖으로 남는다. `pose.rootOffsetNed`가
 * (관 뒤끝보다 기체 꼬리 길이만큼 안쪽인 지점을) 원점 위로 가져오는 수평 이동이고,
 * 유도는 core/launcher.ts에 있다. */
export function placeLauncher(model: LoadedModel, siteNed: Vec3, pose: LauncherPose): void {
  const off = pose.rootOffsetNed;
  const p = toWorld(siteNed[0] + off[0], siteNed[1] + off[1], siteNed[2] + off[2]);
  model.root.position.set(p[0], p[1], p[2]);
  model.root.visible = true;
}

/** 발사 정보를 모르면 **그리지 않는다.**
 *
 * 자세 없이 그리면 턴테이블 0°·크래들 0°·잭 접힘인 발사관이 남는데, 그건 구멍이 아니라
 * **지어낸 자세**다. 게다가 데모의 실제 방위가 0.0이라 지어낸 것과 옳은 것이 화면에서
 * 구별되지 않는다 — 아무도 눈치채지 못한다. */
export function hideLauncher(model: LoadedModel): void {
  model.root.visible = false;
}

/** 발사관 배치와 관절을 **한 번에** — 자세가 없으면 숨긴다.
 *
 * `placeLauncher` + `applyLauncher`를 따로 부르면, 자리를 옮기는 쪽이 무조건 보이게
 * 하고 관절을 넣는 쪽이 조용히 물러나므로 **호출자가 `hideLauncher`를 기억해야** 한다.
 * 잊으면 지어낸 자세가 남고, 그 실패는 화면에서 안 보인다. 여기서는 그 상태를 아예
 * 표현할 수 없게 묶는다 — `setVehiclePose`/`hideVehicle`가 이미 닫힌 쌍인 것과 같은 모양. */
export function showLauncher(
  model: LoadedModel,
  siteNed: Vec3,
  pose: LauncherPose | null,
): boolean {
  if (pose == null) {
    hideLauncher(model);
    return false;
  }
  placeLauncher(model, siteNed, pose);
  return applyLauncher(model, pose);
}
