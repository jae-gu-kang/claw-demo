/** 가상환경 탭 진입점 — 호스트 페이지에 마운트되는 **모듈**이다 (자기 페이지가 없다).
 *
 * `web/js/main.js`의 해시 라우터가 `#world`에서 이 번들을 동적 import해 `mount()`를
 * 부르고, 탭을 떠날 때 반환된 `dispose()`를 부른다. `<iframe>`을 쓰지 않는 이유는
 * 기존 WebGL 컨텍스트 반납 규율이 그대로 살아야 하기 때문이다 — 브라우저당 컨텍스트가
 * 8~16개뿐이라 탭을 오갈 때마다 새로 만들면 곧 바닥난다.
 *
 * ## dispose는 **동기**여야 한다
 *
 * `main.js:32`가 `clear()` 직전에 부르므로 await할 자리가 없다. 비동기 정리가 필요하면
 * 그 자리에서 취소 플래그를 세우고, 늦게 도착한 로드가 스스로 물러나게 한다 —
 * 기존 `views/world.js`의 세션 토큰과 같은 수법이고, 같은 버그를 막는다.
 */

import { StrictMode } from "react";
import { createRoot, type Root } from "react-dom/client";

import { WorldTab } from "./ui/WorldTab.tsx";

export interface MountHandle {
  dispose(): void;
}

/** 호스트가 넘겨 주는 것 — 여기서 fetch를 새로 짜지 않고 기존 계층을 그대로 쓴다. */
export interface MountDeps {
  /** `web/js/store.js` — 시뮬 탭이 고른 결과를 이어받는다 */
  store?: { get(k: string): unknown; set(k: string, v: unknown): void };
  /** 처음 열 결과 id (없으면 최신) */
  resultId?: string | null;
}

export function mount(container: HTMLElement, deps: MountDeps = {}): MountHandle {
  const host = document.createElement("div");
  host.style.cssText = "display:flex; flex-direction:column; gap:10px;";
  container.append(host);

  // **던지더라도 회수한다.** `createRoot` 뒤에 예외가 나면 호출측은 핸들을 못 받고,
  // 그러면 이 루트와 그것이 잡은 것(장차 WebGL 컨텍스트)은 도달 불가능한 고아가 된다.
  // 파일 머리가 막겠다고 한 바로 그 부류가 **탐색 경로가 아니라 오류 경로로** 들어온다.
  let root: Root | null = null;
  try {
    root = createRoot(host);
    root.render(
      <StrictMode>
        <WorldTab deps={deps} />
      </StrictMode>,
    );
  } catch (e) {
    root?.unmount();
    host.remove();
    throw e;
  }

  return {
    dispose() {
      // unmount가 effect 정리를 돌려 SceneHost.dispose()까지 간다.
      // React 18의 unmount는 동기다 — 그래서 이 함수도 동기일 수 있다.
      root?.unmount();
      root = null;
      host.remove();
    },
  };
}
