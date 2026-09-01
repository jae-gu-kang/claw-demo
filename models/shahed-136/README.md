# SHAHED-136형 무인기 — 조종면 분리 .blend 모델

조종면이 **독립 오브젝트로 분리되어 실제로 움직이는** SHAHED-136형(델타익 +
꼬리 없는 배치, 후방 푸셔 프로펠러) 무인기 모델이다. 리깅·드라이버·데모 애니메이션이
`.blend` 안에 들어 있고, 순수 파이썬 스크립트로 재생성된다.

> 형상은 공개 보도 기반 근사(전장 ~3.5 m, 익폭 ~2.5 m)의 **시각화용**이며,
> 실기체 설계·제조 데이터가 아니다.

## 파일

| 파일 | 내용 |
|------|------|
| `generate_shahed136.py` | 모델·리그·애니메이션을 처음부터 만드는 스크립트 (정본) |
| `shahed136.blend` | 산출된 블렌더 파일 (Blender 4.0+) — 드라이버·커스텀 프로퍼티 리그 |
| `shahed136.glb` | **three.js용** glTF — 조종면이 개별 노드로 살아 있고, 데모 동작이 애니메이션 클립으로 구워져 있다 |
| `preview.png` | 미리보기 렌더 (Cycles) |

## 움직이는 조종면 (6개)

각 조종면은 **자기 힌지선을 원점으로 하는 별도 메시 오브젝트**다. 부모(주익/핀)를
따라 움직이되, 로컬 축으로 독립 회전한다.

| 오브젝트 | 힌지축(로컬) | 부모 | + 변위 방향 |
|----------|-------------|------|-------------|
| `Elevon_In_L` / `Elevon_In_R` | X (스팬) | `Wing` | 뒷전 내림 (TE down) |
| `Elevon_Out_L` / `Elevon_Out_R` | X (스팬) | `Wing` | 뒷전 내림 (TE down) |
| `Rudder_L` / `Rudder_R` | Z (수직) | `Fin_L` / `Fin_R` | 뒷전 좌 (TE left) |

엘레본은 **좌/우 × 인보드/아웃보드 = 4면**이 각각 독립이다. `docs/conventions.md`
§5의 4면 배치 규약(collective δe = 4면 평균 → 피치, differential δa = (좌−우)/2 →
롤)을 그대로 구동할 수 있다. 부호도 규약에 맞췄다: 엘레본 + = TE down, 러더 + = TE left.

`Propeller`도 별도 오브젝트로, 회전축(로컬 Y)을 중심으로 프레임에 비례해 돈다.

> 오브젝트 이름에 점(`.`)을 안 쓰고 밑줄을 쓴 이유: glTF/three.js는 노드 이름의
> 점을 지운다(`Elevon.In.L` → `ElevonInL`). 밑줄은 보존되므로 Blender와 three.js가
> **같은 이름**으로 조회된다.

## 조종하는 법 — 루트의 커스텀 프로퍼티

전 타면은 `SHAHED136_Root` 엠프티의 **커스텀 프로퍼티**로 제어된다. 오브젝트
프로퍼티 패널(N 패널 → Item, 또는 Object Properties → Custom Properties)에서 값을
바꾸면 드라이버가 해당 타면을 즉시 돌린다. 단위는 도(deg), 범위 ±30°.

| 프로퍼티 | 대상 |
|----------|------|
| `elevon_in_left`, `elevon_in_right` | 인보드 엘레본 좌·우 |
| `elevon_out_left`, `elevon_out_right` | 아웃보드 엘레본 좌·우 |
| `rudder_left`, `rudder_right` | 러더 좌·우 |
| `prop_speed` | 프로펠러 회전 속도 [deg/frame] |

각 타면에는 ±35° **Limit Rotation** 컨스트레인트가 걸려 있어, 직접 회전을 주더라도
물리적으로 말이 되는 범위를 벗어나지 않는다.

### 믹싱 예시 (루트 프로퍼티에 넣을 값)

- **피치 업**: 4개 엘레본 모두 음수(예: 전부 −15) → TE up, 기수 들림
- **롤 우**: 좌 엘레본 +, 우 엘레본 − (예: 좌 In/Out +15, 우 In/Out −15)
- **요 우**: 러더 둘 다 음수 (TE right)

## 데모 애니메이션

1–168 프레임(24 fps)에 타면 작동 데모가 키프레임되어 있다. 재생하면:
롤(엘레본 차동) → 피치(엘레본 동상) → **인보드만** 편향 + 러더 → **아웃보드만**
편향 + 러더 순으로, 인보드·아웃보드가 서로 독립임이 눈으로 확인된다.

키프레임은 루트 프로퍼티에 찍혀 있으므로, 지우고 새로 제어법칙 출력을 물려도 된다.

## three.js에서 쓰기 (`shahed136.glb`)

three.js(`GLTFLoader`)는 블렌더의 **드라이버·커스텀 프로퍼티를 실행하지 않는다.**
그래서 GLB로 내보낼 때 각 타면의 드라이버 모션을 프레임별로 샘플해 **노드 회전
키프레임으로 굽고**, 데모 동작을 단일 애니메이션 클립(`"SHAHED-136"`, 7 s @ 24 fps)으로
넣었다. 동시에 각 조종면은 **힌지에 피벗이 맞춰진 개별 노드**로 남아 코드에서 직접
회전시킬 수 있다. 두 방식 모두 실제 three.js r185 + `GLTFLoader`에서 로드·구동을 확인했다.

### 노드 이름과 회전축 (glTF Y-up 변환 반영)

| 노드 | three.js 회전축 | + 방향 |
|------|----------------|--------|
| `Elevon_In_L`, `Elevon_In_R` | `rotation.x` | 뒷전 내림 (TE down) |
| `Elevon_Out_L`, `Elevon_Out_R` | `rotation.x` | 뒷전 내림 (TE down) |
| `Rudder_L`, `Rudder_R` | `rotation.y` | 뒷전 좌 (TE left) |
| `Propeller` | `rotation.z` | 회전 |

계층: `SHAHED136_Root › Fuselage › { Propeller, Wing › {엘레본 4, Fin_L/R › Rudder} }`.
(`Fuselage`·`Wing`은 다중 머티리얼이라 `Fuselage_1`처럼 렌더용 서브메시로 갈리지만,
조종면 노드는 위 이름 그대로다.)

### 1) 데모 클립 재생

```js
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

let mixer;
new GLTFLoader().load('shahed136.glb', (gltf) => {
  scene.add(gltf.scene);
  mixer = new THREE.AnimationMixer(gltf.scene);
  mixer.clipAction(gltf.animations[0]).play();   // "SHAHED-136" 클립
});

// 렌더 루프에서
const dt = clock.getDelta();
if (mixer) mixer.update(dt);
```

### 2) 코드로 직접 조종 (제어법칙 출력 물리기)

```js
const deg = THREE.MathUtils.degToRad;
const root = gltf.scene;
const el = n => root.getObjectByName(n);

// 피치 업: 4개 엘레본 TE up (음수)
for (const n of ['Elevon_In_L','Elevon_In_R','Elevon_Out_L','Elevon_Out_R'])
  el(n).rotation.x = deg(-15);

// 롤 우: 좌 +, 우 −
el('Elevon_In_L').rotation.x = el('Elevon_Out_L').rotation.x = deg(+15);
el('Elevon_In_R').rotation.x = el('Elevon_Out_R').rotation.x = deg(-15);

// 요 우: 러더 TE right (음수)
el('Rudder_L').rotation.y = el('Rudder_R').rotation.y = deg(-15);

// 프로펠러 스핀 (렌더 루프에서)
el('Propeller').rotation.z += 12 * dt;
```

직접 회전은 데모 클립과 배타적이다 — 코드로 제어할 거면 `mixer`를 만들지 않거나
`mixer.stopAllAction()` 후 노드 회전을 준다. (GLB에는 블렌더의 ±35° 리밋
컨스트레인트가 안 들어가므로, 각도 클램프가 필요하면 앱에서 건다.)

## 재생성

```bash
blender -b --factory-startup -P generate_shahed136.py
```

`shahed136.blend`, `shahed136.glb`, `preview.png`를 다시 만든다. 렌더를 건너뛰려면
`SHAHED_SKIP_RENDER=1`. glTF 내보내기는 Blender 내장 파이썬에 `numpy`가 필요하다
(없으면 그 단계만 건너뛰고 `.blend`는 정상 생성).

저장된 `.blend`는 인터랙티브용 드라이버 리그를 그대로 유지한다 — GLB용 베이크는
내보내기 직전 in-메모리 상태에서만 일어나고 `.blend`에는 반영되지 않는다.

### 커밋 대상과 블렌더 numpy

`.glb`·`.py`·README만 커밋하고 `.blend`·`preview.png`는 커밋하지 않는다. 그리고 내장
numpy가 못 뜨는 블렌더에서는 GLB 내보내기가 **조용히** 빠진다. 두 사유와 대처는
`models/README.md`에 한 번만 적혀 있다 — 여기 옮겨 적으면 갈린다.

Blender 4.0.2·5.2.1 / three.js r185에서 검증. 외부 에셋·애드온 의존성 없음.
