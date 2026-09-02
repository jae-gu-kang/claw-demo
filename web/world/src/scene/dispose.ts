/** three 자원 해제 — **한 곳에만 둔다.**
 *
 * 처음에는 `SceneHost`와 `models`가 각자 복사본을 들고 있었고, 텍스처까지 놓도록 한쪽만
 * 고쳤다. 하필 GLB를 읽는 쪽(= 실제로 텍스처를 쥐게 될 쪽)이 안 고쳐진 쪽이었다.
 * 같은 일을 두 번 적으면 언젠가 한쪽만 고쳐진다.
 */

import type { Object3D } from "three";

/** 재질이 쥔 텍스처까지 놓는다.
 *
 * 지금 두 GLB는 텍스처가 0장이라 아무 일도 안 하지만, 텍스처가 붙은 모델이 들어오는
 * 순간 이 줄이 없으면 결과를 바꿀 때마다 GPU 메모리가 샌다 — 재질을 dispose해도
 * 그것이 참조하던 텍스처는 따로 놓아야 한다. */
export function disposeMaterial(mat: unknown): void {
  const m = mat as (Record<string, unknown> & { dispose?: () => void }) | null;
  if (m == null) return;
  for (const v of Object.values(m)) {
    if (v && typeof v === "object" && "isTexture" in v) {
      (v as { dispose?: () => void }).dispose?.();
    }
  }
  m.dispose?.();
}

/** 트리 전체의 지오메트리·재질·텍스처를 놓고 자식을 비운다. */
export function disposeTree(root: Object3D): void {
  root.traverse((o) => {
    const m = o as { geometry?: { dispose?: () => void }; material?: unknown };
    m.geometry?.dispose?.();
    const mat = m.material;
    if (Array.isArray(mat)) mat.forEach(disposeMaterial);
    else disposeMaterial(mat);
  });
  root.clear();
}
