/** 게임 모드 소품 — 소나무·활엽수·오두막을 인스턴싱으로 세운다.
 *
 * 배치 규칙은 `core/propfield.ts`(순수·테스트 대상)가 정본이고, 여기는 three 결선만
 * 한다 — 이 저장소의 계층 규율(axes.ts 머리말) 그대로다.
 *
 * ## 왜 부품별 InstancedMesh인가
 *
 * 나무 하나는 줄기+수관 두 지오메트리다. 애드온 merge 유틸로 한 덩어리를 만들 수도
 * 있지만, 부품 둘이 **같은 인스턴스 행렬**을 공유하면 merge 없이 같은 그림이 나온다 —
 * 소품 3종 × 부품 2 = 드로우콜 6이 전부라 합칠 실익이 없다.
 *
 * ## frustumCulled를 끈다
 *
 * InstancedMesh의 경계구는 **지오메트리에서만** 나온다. 나무 한 그루 크기의 구로
 * 24 km에 흩어진 인스턴스를 컬링하면, 카메라가 원점을 벗어나는 순간 숲 전체가
 * 사라진다(`setTerrain`의 NaN 경계구와 같은 부류 — 원인이 화면에 안 보인다).
 */

import {
  BoxGeometry, type BufferGeometry, Color, ConeGeometry, CylinderGeometry, Group,
  IcosahedronGeometry,
  InstancedMesh, Matrix4, MeshStandardMaterial, Quaternion, Vector3,
} from "three";

import type { PropField, PropPlacement } from "../core/propfield.ts";
import { applyAerialPerspective } from "./atmosphere.ts";
import { toWorld } from "./axes.ts";

/** 부품 하나 — 지오메트리는 **밑동이 원점**에 오게 미리 이동해 둔다.
 *  그래야 인스턴스 행렬이 "지면 위 한 점"만 말하면 된다. */
interface Part {
  geometry: BufferGeometry;
  /** sRGB — three Color가 감마를 처리한다. */
  color: string;
  /** 인스턴스 밝기 지터 폭 (0이면 균일) */
  jitter: number;
}

/** 밑동을 지면 아래로 이만큼 연장한다 [m].
 *
 * 소품 밑동은 30 m 격자 이중선형 표고에 앉는데, 게임 지형은 같은 팩을 90 m 낱면으로
 * 솎은 현(chord)이라 날카로운 능선에서 둘이 수 m 벌어진다(리뷰 실측 — 최악 능선 5 m+).
 * 낱면 표고를 다시 재는 대신 줄기를 아래로 늘려 틈을 가린다 — 평지에선 안 보이는
 * 부분이고, 골에 묻히는 쪽은 원래 낱면이 이기는 게 자연스럽다. */
const SINK = 3.2;

const PARTS: Record<keyof PropField, Part[]> = {
  pines: [
    { geometry: new CylinderGeometry(0.28, 0.45, 1.8 + SINK, 5)
        .translate(0, 0.9 - SINK / 2, 0),
      color: "#5b4630", jitter: 0.15 },
    { geometry: new ConeGeometry(2.5, 7.2, 6).translate(0, 1.6 + 3.6, 0),
      color: "#2e6a3b", jitter: 0.4 },
  ],
  leaves: [
    { geometry: new CylinderGeometry(0.32, 0.5, 2.4 + SINK, 5)
        .translate(0, 1.2 - SINK / 2, 0),
      color: "#6b5238", jitter: 0.15 },
    { geometry: new IcosahedronGeometry(2.7, 0).translate(0, 4.4, 0),
      color: "#4f8a3c", jitter: 0.45 },
  ],
  cabins: [
    // 집은 평지(경사 0.06 미만)에만 서므로 연장 폭이 작아도 된다.
    { geometry: new BoxGeometry(5.5, 3.0 + 1.2, 4.2).translate(0, 1.5 - 0.6, 0),
      color: "#8a6a4a", jitter: 0.2 },
    // 지붕 — 45° 돌린 상자의 위 절반만 벽 밖으로 나온다(마름모 단면). 프리미티브
    // 둘로 지붕을 읽게 하는 가장 싼 방법이다.
    { geometry: new BoxGeometry(4.4, 4.4, 4.8).rotateZ(Math.PI / 4).translate(0, 2.6, 0),
      color: "#7d3b32", jitter: 0.15 },
  ],
};

function fillInstances(mesh: InstancedMesh, places: readonly PropPlacement[], part: Part): void {
  const m = new Matrix4();
  const p = new Vector3();
  const q = new Quaternion();
  const s = new Vector3();
  const up = new Vector3(0, 1, 0);
  const base = new Color(part.color);
  const c = new Color();
  for (let i = 0; i < places.length; i++) {
    const pl = places[i]!;
    const w = toWorld(pl.n, pl.e, -pl.elev);
    p.set(w[0], w[1], w[2]);
    q.setFromAxisAngle(up, pl.rot);
    s.setScalar(pl.scale);
    mesh.setMatrixAt(i, m.compose(p, q, s));
    // 밝기 지터 — 같은 색 수천 그루는 도장한 모형처럼 읽힌다.
    c.copy(base).multiplyScalar(1 - part.jitter / 2 + part.jitter * pl.tint);
    mesh.setColorAt(i, c);
  }
  mesh.instanceMatrix.needsUpdate = true;
  if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
}

/** 소품 그룹을 만든다 — 호출측(SceneHost)이 수명을 쥔다. */
export function buildPropsGroup(field: PropField): { group: Group; count: number } {
  const group = new Group();
  let count = 0;
  for (const kind of ["pines", "leaves", "cabins"] as const) {
    const places = field[kind];
    if (places.length === 0) continue;
    count += places.length;
    for (const part of PARTS[kind]) {
      // 지오메트리는 모듈 상수를 공유한다 — dispose가 그것을 놓아도(clear 시)
      // 다음 빌드가 같은 상수를 다시 쓰므로, **clone으로 소유권을 넘긴다.**
      const mat = new MeshStandardMaterial({ flatShading: true, roughness: 0.9, metalness: 0 });
      applyAerialPerspective(mat);
      const mesh = new InstancedMesh(part.geometry.clone(), mat, places.length);
      mesh.frustumCulled = false; // 머리말 — 경계구가 인스턴스를 모른다
      mesh.castShadow = true;
      fillInstances(mesh, places, part);
      group.add(mesh);
    }
  }
  return { group, count };
}
