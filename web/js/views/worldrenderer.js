/** 3D 월드 렌더러 계약 + 팩토리 — 구현 교체 지점.

## 왜 계약을 따로 두나

three.js는 **범위 한정 예외 1건**으로 반입한 외부 의존이고(vendor/three/VERSION,
02 §4 개정), 폐쇄망 반입 시 자체 WebGL2 구현으로 갈아 끼울 여지를 남겨야 한다. 그러려면
"인터페이스만 정의"로는 부족하다 — **재미있는 계산이 전부 렌더러 밖에 있어야** 교체가
현실적이다. 그래서 이 층을 넘는 값은 다음 세 규칙을 지킨다.

1. **좌표는 전부 NED·미터·라디안.** 렌더러 축(three는 y가 위)으로 옮기는 일은 어댑터
   안 한 줄(`toWorld`)이 맡는다.
2. **자세는 동체축의 NED 성분**으로 넘긴다(쿼터니언 규약을 렌더러가 몰라도 되게).
   lib/attitude.js `bodyAxesNed`가 그것을 낸다.
3. **기하는 타입배열**로 넘긴다(lib/uavmesh.js). 파일 포맷 규약이 끼어들지 않는다.

카메라 pose·LOD 선택·형상 생성·재생 커서는 전부 lib/에 있고 테스트가 붙어 있다.
어댑터에 남은 것은 three 객체 조립뿐이라, 교체할 때 다시 쓸 것이 그만큼 적다.

## 계약

    resize(w, h, dpr)
    setEnvironment({sunAzEl:[az,el], visibility, exposure, groundColor?})
    setTerrain([{positions, normals, indices}])   // NED 기하 (lib/terrainpack.js)
    setGround({elevation, grid:{extent, step}, runway?, rail?, showPlane?, showGrid?})
    setPaths([{points:Float32Array(NED 평탄), color, breaks?}])
    setMarkers([{ne:[n,e,d], kind:"waypoint"|"start"|"end", radius?}])
    setModelMesh({positions, normals, indices, groups} | null)
    setModelPose({pos:[n,e,d], axes:{forward,right,down}, scale?} | null)
    render({eye, target, up, fovY})       // 1프레임 — rAF 자유주행은 호출측 몫
    stats() -> {drawCalls, triangles, ms}
    describe() -> {name, api, maxTextureSize, maxAnisotropy}
    dispose()
*/

/** 렌더러 생성 — 실패 시 **던지지 않고** {renderer: null, reason}을 낸다.
 *
 * WebGL2를 못 만드는 환경(오래된 브라우저, GPU 차단, 원격 데스크톱)에서 검은 캔버스를
 * 남기면 사용자는 무엇이 잘못됐는지 알 수 없다. 사유를 문장으로 받아 화면이 말한다.
 */
export async function createRenderer(canvas) {
  if (typeof WebGL2RenderingContext === "undefined") {
    return { renderer: null, reason: "이 브라우저가 WebGL2를 지원하지 않습니다." };
  }
  // **탐지한 컨텍스트를 그대로 넘긴다.** 같은 캔버스에서 getContext를 두 번 부르면
  // 두 번째는 기존 컨텍스트를 돌려주면서 속성(antialias 등)을 무시하므로, 여기서
  // 미리 만들어 두면 three가 안티앨리어싱 없는 컨텍스트를 받게 된다.
  const context = canvas.getContext("webgl2", { antialias: true });
  if (context == null) {
    return {
      renderer: null,
      reason: "WebGL2 컨텍스트를 만들지 못했습니다 — 하드웨어 가속이 꺼져 있거나 "
        + "GPU가 차단된 환경일 수 있습니다.",
    };
  }
  try {
    const { createThreeRenderer } = await import("./renderer-three.js");
    return { renderer: createThreeRenderer(canvas, context) };
  } catch (e) {
    return { renderer: null, reason: `렌더러를 불러오지 못했습니다 — ${e.message}` };
  }
}
