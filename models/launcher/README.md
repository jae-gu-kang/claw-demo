# 무인기 캐니스터 발사관 — 가동부 분리 .blend / three.js GLB

트레일러 탑재형 **캐니스터 발사관**(2×2 = 4 발사관)을, 같은 저장소의 SHAHED-136
모델과 **같은 톤**(스튜디오·재질 스타일·파이프라인)으로 만든 모델이다. 방위각(선회)·
고각(상하)·지지대(전개) 가동부가 **독립 오브젝트로 분리되어 실제로 움직인다.**

> 형상은 참고 이미지 기반 근사의 **시각화용**이며 실장비 설계·제조 데이터가 아니다.

## 파일

| 파일 | 내용 |
|------|------|
| `generate_launcher.py` | 모델·리그·애니메이션을 처음부터 만드는 스크립트 (정본) |
| `launcher.blend` | 산출된 블렌더 파일 (Blender 4.0+) — 드라이버·커스텀 프로퍼티 리그 |
| `launcher.glb` | **three.js용** glTF — 가동부가 개별 노드로 살아 있고, 데모 동작이 애니메이션 클립으로 구워져 있다 |
| `preview.png` | 미리보기 렌더 (Cycles) |

## 움직이는 가동부

각 가동부는 **자기 회전/이동 축을 원점으로 하는 별도 오브젝트**다.

| 오브젝트 | 동작 | 축(로컬) | 부모 |
|----------|------|---------|------|
| `Turntable` | 방위각 선회 | Z 회전 | `Trailer` |
| `Cradle` | 고각 상하 | X 회전 | `Turntable` |
| `Jack_FL` / `FR` / `RL` / `RR` | 아웃리거 전개 | Z 이동(하강) | `Trailer` |

`Cradle`은 `Turntable`의 자식이라, **선회한 다음 그 자세에서 고각을 준다** — 실장비의
트러니언 거동과 같다. 발사관 본체(외피·측면 장갑판은 `Cradle`에 통합, 캐니스터 내부
암부는 `Box_Tubes`, 상부 레일은 `Box_Rails`)는 크래들을 따라 함께 움직인다.

**아웃리거 잭**은 4모서리에 있고, 각 잭은 프레임에서 뻗은 아웃리거 암 → 슬리브 →
텔레스코핑 레그 → 지면 받침대로 **트레일러와 지면을 끊김 없이 잇는다**. 받침 footprint를
바퀴 트랙(±1.12 m)보다 넓게(±1.28 m) 잡아, 전개 시 바퀴 하나로 기우는 것을 막는다.
레그 상단은 전개해도 슬리브 안에 물려 있어 항상 연결된 상태다. `Wheel_L/R`은 정적이다.

## 조종하는 법 — 루트의 커스텀 프로퍼티 (Blender)

전 가동부는 `LAUNCHER_Root` 엠프티의 **커스텀 프로퍼티**로 제어된다. 오브젝트
프로퍼티 패널에서 값을 바꾸면 드라이버가 즉시 반영한다.

| 프로퍼티 | 대상 | 범위 |
|----------|------|------|
| `azimuth` | 방위각 [deg], + = 좌현 선회 | −100 … 100 |
| `elevation` | 고각 [deg], + = 포구 상승 | 0 … 48 |
| `jack_deploy` | 지지대 0(접힘) → 1(지면 전개) | 0 … 1 |

`Turntable`·`Cradle`에는 Limit Rotation 컨스트레인트가 걸려 있어 과회전을 막는다.

## 데모 애니메이션

1–168 프레임(24 fps)에 전개 시퀀스가 키프레임되어 있다: **지지대 전개 → 방위각
선회 → 고각 상승 → 발사 자세 유지**. 재생하면 세 축이 순서대로 도는 게 보인다.

## three.js에서 쓰기 (`launcher.glb`)

three.js(`GLTFLoader`)는 블렌더의 드라이버·커스텀 프로퍼티를 실행하지 않는다. 그래서
GLB로 내보낼 때 각 가동부의 모션을 프레임별로 샘플해 **노드 트랜스폼 키프레임으로
굽고**, 데모 동작을 단일 클립(`"Launcher"`, 7 s @ 24 fps)으로 넣었다. 동시에 각
가동부는 **개별 노드**로 남아 코드에서 직접 구동할 수 있다. 실제 three.js r185 +
`GLTFLoader`에서 로드·클립재생·수동 관절구동을 확인했다.

### 노드 이름과 축 (glTF Y-up 변환 반영)

| 노드 | three.js | + 방향 |
|------|----------|--------|
| `Turntable` | `rotation.y` | 방위각 선회 |
| `Cradle` | `rotation.x` | 고각(포구 상승) |
| `Jack_FL`,`Jack_FR`,`Jack_RL`,`Jack_RR` | `position.y` | 전개(하강 = −y) |

계층: `LAUNCHER_Root › Trailer › { Wheel_L/R, Jack_×4, Turntable › Cradle › {Box_Tubes, Box_Rails} }`.
(오브젝트 이름에 점을 안 쓰고 밑줄을 쓴 이유는 glTF/three.js가 노드 이름의 점을
지우기 때문 — Blender·three.js에서 같은 이름으로 조회된다.)

### 1) 데모 클립 재생

```js
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

let mixer;
new GLTFLoader().load('launcher.glb', (gltf) => {
  scene.add(gltf.scene);
  mixer = new THREE.AnimationMixer(gltf.scene);
  mixer.clipAction(gltf.animations[0]).play();   // "Launcher" 클립
});
// 렌더 루프에서: if (mixer) mixer.update(clock.getDelta());
```

### 2) 코드로 직접 구동 (사격통제 값 물리기)

```js
const deg = THREE.MathUtils.degToRad;
const root = gltf.scene;

root.getObjectByName('Turntable').rotation.y = deg(30);   // 방위각 30°
root.getObjectByName('Cradle').rotation.x    = deg(40);   // 고각 40°

// 지지대 전개: 각 잭을 아래로 (−y). 접힘 자세를 기준으로 오프셋
for (const t of ['FL','FR','RL','RR']) {
  const j = root.getObjectByName('Jack_' + t);
  j.position.y = j.userData.restY ?? (j.userData.restY = j.position.y);
  j.position.y -= 0.5;                                    // 지면까지
}
```

직접 구동은 데모 클립과 배타적이다 — 코드로 제어할 거면 `mixer`를 만들지 않거나
`mixer.stopAllAction()` 후 노드를 조작한다. (GLB에는 Limit 컨스트레인트가 안 들어가므로
각도 클램프가 필요하면 앱에서 건다.)

## 재생성

```bash
blender -b --factory-startup -P generate_launcher.py
```

`launcher.blend`, `launcher.glb`, `preview.png`를 다시 만든다. 렌더를 건너뛰려면
`LAUNCHER_SKIP_RENDER=1`. glTF 내보내기는 Blender 내장 파이썬에 `numpy`가 필요하다.
저장된 `.blend`는 인터랙티브 드라이버 리그를 유지하고, GLB용 베이크는 내보내기 직전
in-메모리에서만 일어난다.

### 커밋 대상과 블렌더 numpy

`.glb`·`.py`·README만 커밋하고 `.blend`·`preview.png`는 커밋하지 않는다. 그리고 내장
numpy가 못 뜨는 블렌더에서는 GLB 내보내기가 **조용히** 빠진다. 두 사유와 대처는
`models/README.md`에 한 번만 적혀 있다 — 여기 옮겨 적으면 갈린다.

Blender 4.0.2·5.2.1 / three.js r185에서 검증. 외부 에셋·애드온 의존성 없음.
