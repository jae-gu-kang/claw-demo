/** 후처리 파이프라인 — **HDR로 그리고 마지막에 톤매핑한다.**
 *
 * ## 왜 톤매핑을 끝으로 옮기나
 *
 * three는 재질 셰이더 안에서 톤매핑을 하는데, **렌더타깃에 그릴 때는 건너뛴다** —
 * `WebGLRenderer`가 `currentRenderTarget === null`일 때만 그 청크를 넣는다(소스 확인).
 * 컴포저는 오프스크린에 그리므로 재질은 저절로 선형값을 남기고, `OutputPass`가 마지막에
 * `renderer.toneMapping`·`toneMappingExposure`를 읽어 ACES와 색공간을 건다.
 *
 * 그래서 **렌더러의 톤매핑은 켜 둔 채여야 한다** — 끄면 `OutputPass`도 안 걸어서 화면이
 * 선형인 채로 나온다. 중간 버퍼만 HalfFloat로 두면 1.0을 넘는 값이 살아서 블룸에 닿는다.
 * 그 값이 안 살면 태양 원반도 윤슬도 1.0에서 잘려 **아무것도 안 번진다.**
 *
 * ## 왜 samples를 직접 주나
 *
 * 컨텍스트를 `antialias: true`로 만들어도, 컴포저를 붙이면 그림이 오프스크린 렌더타깃으로
 * 가므로 **그 MSAA가 통째로 무용지물이 된다.** 렌더타깃에 `samples`를 주지 않으면
 * 궤적 선과 기체 실루엣이 후처리를 붙이기 **전보다** 나빠진다.
 *
 * ## 분할 프러스텀을 컴포저 안에서 한다
 *
 * `RenderPass`는 장면을 한 번 그린다. 우리는 원거리·근거리를 나눠 그리고 그 사이에
 * **깊이만** 지워야 하므로 전용 패스를 둔다. 이 패스가 컴포저의 첫 패스이고, 그 뒤로는
 * 화면 공간 패스만 온다.
 */

import {
  HalfFloatType, Vector2, WebGLRenderTarget,
  type PerspectiveCamera, type Scene, type WebGLRenderer,
} from "three";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";
import { Pass } from "three/addons/postprocessing/Pass.js";
import { SMAAPass } from "three/addons/postprocessing/SMAAPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";

export interface FrustumRanges {
  near: number; nearFar: number; farNear: number; far: number;
}

/** 한 프레임을 두 프러스텀으로 그린다 — 원거리(색·깊이 지움) → 근거리(깊이만 지움). */
export class SplitFrustumPass extends Pass {
  constructor(
    private readonly scene: Scene,
    private readonly camera: PerspectiveCamera,
    private readonly ranges: FrustumRanges,
    /** 근거리 패스에서 숨길 것 — 하늘처럼 카메라를 감싸 컬링이 안 되는 것. */
    private readonly hideInNear: { visible: boolean }[],
  ) {
    super();
    this.needsSwap = false; // 우리가 쓴 버퍼를 다음 패스가 그대로 읽는다
  }

  /** 장면만의 비용 — 후처리 풀스크린 쿼드가 섞이기 전 값. 화면이 이것을 말한다. */
  sceneStats = { drawCalls: 0, triangles: 0 };

  override render(renderer: WebGLRenderer, _write: WebGLRenderTarget, read: WebGLRenderTarget): void {
    renderer.setRenderTarget(this.renderToScreen ? null : read);
    const autoClear = renderer.autoClear;
    // **여기서만 끈다.** 전역으로 끄면 `SMAAPass`가 조용히 망가진다 — 그쪽은
    // `this.clear`가 기본 false라 자기 내부 타깃을 `renderer.autoClear`에 기대어
    // 지우는데, 에지 셰이더가 `discard`를 쓰므로 안 지우면 에지 마스크가 **누적**된다.
    renderer.autoClear = false;
    try {
      this.camera.near = this.ranges.farNear;
      this.camera.far = this.ranges.far;
      this.camera.updateProjectionMatrix();
      renderer.clear(true, true, false);
      renderer.render(this.scene, this.camera);

      for (const o of this.hideInNear) o.visible = false;
      try {
        this.camera.near = this.ranges.near;
        this.camera.far = this.ranges.nearFar;
        this.camera.updateProjectionMatrix();
        renderer.clear(false, true, false);
        renderer.render(this.scene, this.camera);
      } finally {
        // 던지면 하늘이 숨은 채로 남는다 — 장면은 계속 그려지고 하늘만 없어서
        // 원인이 가장 안 보이는 실패가 된다.
        for (const o of this.hideInNear) o.visible = true;
      }
      const info = renderer.info.render;
      this.sceneStats = { drawCalls: info.calls, triangles: info.triangles };
    } finally {
      renderer.autoClear = autoClear;
    }
  }
}

export interface PostOptions {
  /** 블룸 세기 — Engineering은 최소, Cinematic은 올린다. 0이면 패스를 안 만든다. */
  bloomStrength: number;
  bloomRadius: number;
  /** 이 밝기를 넘는 것만 번진다. 윤슬·태양 원반만 걸리게 높게 잡는다. */
  bloomThreshold: number;
  antialias: boolean;
}

export interface Post {
  setSize(width: number, height: number, dpr: number): void;
  render(): void;
  /** 장면만의 비용 — 후처리 쿼드가 안 섞인 값. */
  sceneStats(): { drawCalls: number; triangles: number };
  dispose(): void;
}

export function createPost(
  renderer: WebGLRenderer,
  scenePass: Pass,
  width: number,
  height: number,
  opts: PostOptions,
): Post {
  // **HalfFloat + samples.** 위 주석의 두 이유가 이 한 줄에 다 있다.
  const target = new WebGLRenderTarget(Math.max(width, 1), Math.max(height, 1), {
    type: HalfFloatType,
    samples: 4,
  });
  const composer = new EffectComposer(renderer, target);
  // **MSAA는 장면이 내려앉는 버퍼에만 있으면 된다.** `EffectComposer`가 target을 복제해
  // `renderTarget2`를 만들고 `RenderTarget.copy`가 samples까지 가져가는데, 첫 패스가
  // 쓰는 쪽은 그 **복제본**(readBuffer)이다. 나머지 한 장은 풀스크린 쿼드만 받으므로
  // 4배 메모리와 매 읽기의 resolve blit이 순수 낭비다.
  composer.renderTarget1.samples = 0;
  composer.addPass(scenePass);

  const bloom = opts.bloomStrength > 0
    ? new UnrealBloomPass(
      new Vector2(width, height), opts.bloomStrength, opts.bloomRadius, opts.bloomThreshold)
    : null;
  if (bloom) composer.addPass(bloom);

  // **SMAA는 `OutputPass` 앞이다.** 그쪽 문서가 명시한다 — "SMAAPass operates in
  // linear-srgb so this pass must be executed before OutputPass"(FXAA는 반대다).
  // 그리고 `clear = true`를 준다: 기본값 false면 자기 내부 타깃을 `renderer.autoClear`에
  // 기대어 지우는데, 우리는 장면 패스에서 그것을 끄고 쓴다. 에지 셰이더가 `discard`라
  // 안 지우면 마스크가 **프레임마다 누적**되어 시간이 갈수록 번진다.
  const smaa = opts.antialias ? new SMAAPass() : null;
  if (smaa) {
    smaa.clear = true;
    composer.addPass(smaa);
  }

  // **톤매핑은 여기 한 번뿐이다** — 재질 쪽은 렌더타깃이라 저절로 건너뛴다(위 주석).
  const output = new OutputPass();
  composer.addPass(output);



  return {
    setSize(w, h, dpr) {
      composer.setPixelRatio(Math.min(dpr, 2));
      composer.setSize(w, h);
    },
    render() {
      composer.render();
    },
    sceneStats() {
      return (scenePass as SplitFrustumPass).sceneStats;
    },
    dispose() {
      bloom?.dispose();
      smaa?.dispose();
      output.dispose();
      // `composer.dispose()`가 renderTarget1·2와 내부 copyPass까지 놓는다 —
      // 우리가 넘긴 target이 곧 renderTarget1이므로 따로 부르지 않는다.
      composer.dispose();
    },
  };
}
