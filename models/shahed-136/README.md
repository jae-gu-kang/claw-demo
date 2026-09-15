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
| `shahed136_eoir.blend` · `.glb` · `preview_eoir.png` | **EOIR형** — 기수 대신 총알형 EO/IR 헤드 (아래 「EOIR형」). 기본형 파일과 따로 산출된다 |
| `test_generate_shahed136.py` | 두 GLB의 노드·기수·엔진·프로펠러·최후방·러더/짐벌 부호·짐벌 리밋 검사 — `pytest models` (블렌더 불필요) |

## 움직이는 조종면 (6개)

각 조종면은 **자기 힌지선을 원점으로 하는 별도 메시 오브젝트**다. 부모(주익/핀)를
따라 움직이되, 로컬 축으로 독립 회전한다.

| 오브젝트 | 힌지축(로컬) | 부모 | + 변위 방향 |
|----------|-------------|------|-------------|
| `Elevon_In_L` / `Elevon_In_R` | X (스팬) | `Wing` | 뒷전 내림 (TE down) |
| `Elevon_Out_L` / `Elevon_Out_R` | X (스팬) | `Wing` | 뒷전 내림 (TE down) |
| `Rudder_L` / `Rudder_R` | Z (수직) | `Fin_L` / `Fin_R` | 뒷전 좌 (TE left) — 로컬 +Z 회전의 **반대**(드라이버가 부호를 뒤집는다) |

엘레본은 **좌/우 × 인보드/아웃보드 = 4면**이 각각 독립이다. `docs/conventions.md`
§5의 4면 배치 규약(collective δe = 4면 평균 → 피치, differential δa = (좌−우)/2 →
롤)을 그대로 구동할 수 있다. 부호도 규약에 맞췄다: 엘레본 + = TE down, 러더 + = TE left —
기수를 12시에 두고 내려다볼 때 러더 뒷전이 4시 쪽에서 8시 쪽으로 가는 방향이다.

`Propeller`도 별도 오브젝트로, 회전축(로컬 Y)을 중심으로 프레임에 비례해 돈다.

### 엔진·프로펠러

동체는 날개 뒷전(y −1.45 m)의 어두운 방화벽에서 끝나고, 짧은 후드 입술만 엔진 앞 윗부분을
덮는다. 그 뒤로 참고 사진의 **수평대향 4기통**이 드러난다. `Engine`(고정, `Fuselage` 자식)은
크랭크케이스, 핀 달린 실린더 넷(좌 뱅크가 2 cm 앞)과 헤드 커버, 카뷰레터·흡기 스택, 구리
매니폴드·런너, 노란 점화선·배전기, 배기관, 톱니 60개 구리 링기어를 한 메시로 가진다
(`Engine_Block` · `Engine_Fins` · `Engine_Copper` · `Engine_Alloy` · `Engine_Wire` ·
`Engine_Exhaust`). `Propeller`는 나무 2엽(`Prop_Wood` — 타원 단면, 비틀림, 둥근 끝)과 알루미늄
허브판·볼트 6개·센터 보스다.

바깥이 쓰는 값은 그대로 두었다. 최후방(센터 너트)은 기체 원점 뒤 **1.905 m**다 — 가상환경이
발사관 안에 기체를 맞추는 상수(`web/world/src/core/launcher.ts`의 `VEHICLE_AFT_EXTENT`)가 이
값에서 왔고, `test_generate_shahed136.py`가 GLB에서 고정한다. 블레이드 끝 반경도 종전과 같은
0.45 m다.

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
| `Rudder_L`, `Rudder_R` | `rotation.y` | 뒷전 **우** (TE right) — 러더 δr(TE left +)은 `rotation.y = −δr` |
| `Propeller` | `rotation.z` | 회전 |

계층: `SHAHED136_Root › Fuselage › { Propeller, Engine, Wing › {엘레본 4, Fin_L/R › Rudder} }`.
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

// 요 우: 러더 TE right = δr −15° → rotation.y = −δr = +15°
el('Rudder_L').rotation.y = el('Rudder_R').rotation.y = deg(+15);

// 프로펠러 스핀 (렌더 루프에서)
el('Propeller').rotation.z += 12 * dt;
```

직접 회전은 데모 클립과 배타적이다 — 코드로 제어할 거면 `mixer`를 만들지 않거나
`mixer.stopAllAction()` 후 노드 회전을 준다. (GLB에는 블렌더의 ±35° 리밋
컨스트레인트가 안 들어가므로, 각도 클램프가 필요하면 앱에서 건다.)

## EOIR형 — 기수 대신 EO/IR 헤드 (`SHAHED_VARIANT=eoir`)

기수 원추를 떼고 실기체 사진처럼 **총알형 기수**를 단 변형이다. 몸통을 원통에 가깝게 끌고 와
한 단 솟은 검은 띠(y 1.26~1.29 m, r 0.122 m)를 두르고, 같은 굵기(r 0.119 m)의 원통 기수를
y 1.46 m까지 뻗은 뒤 그 끝에 **헤드 돔**(r 0.1175 m)이 반구로 맞물린다 — 돔이 원통보다 조금
작아 어느 자세에서도 원통 안에 들고, 남는 단은 어두운 이음 테다. 돔 앞은
평평한 센서면(반경 0.068 m)으로 잘려 참고 사진의 창 넷 — 큰 EO 렌즈, 작은 IR 창, 둥근 오각형
레이저 창, 작은 보조 렌즈 — 이 붉은 가스켓과 함께 붙고, 둘레 리벳과 비스듬한 패널 이음매가
돈다. 기체·타면·프로펠러와 그 노드 이름은 기본형과 같고 노드가 **두 개 더** 있다 — 가상환경이
조회하는 노드(`VEHICLE_NODES`)를 전부 가지므로 GLB만 바꿔 물려도 타면은 그대로 움직인다.

| 오브젝트 | 회전축(블렌더 로컬) | 부모 | + 방향 | three.js |
|----------|-------------------|------|--------|----------|
| `EOIR_Pan` | Z (수직) | `Fuselage` | 보어사이트 우측 | `rotation.y = −pan` |
| `EOIR_Tilt` | X (좌우) | `EOIR_Pan` | 보어사이트 위 | `rotation.x = +tilt` |

- `EOIR_Pan`은 형상 없는 엠프티(방위축)이고, 보이는 헤드는 전부 `EOIR_Tilt`다. 두 원점 = 돔
  중심 = 두 축의 교점이라 돔은 어느 자세에서도 외형이 같고 센서면만 돈다.
- 보어사이트 = 기수 방향(블렌더 +Y, glTF −Z). 창 배치는 센서면을 **마주 보고** 사진과 같다.
  재질: `EOIR_Housing`(돔) · `EOIR_Gasket` · `EOIR_Lens_EO` · `EOIR_Lens_IR` · `EOIR_Laser` ·
  `EOIR_Optics` · `EOIR_Seam`(이음매·리벳).
- 부호는 FRD 오일러와 같은 뜻이다: **pan + = 우측, tilt + = 위.** three.js 열은
  `test_generate_shahed136.py`가 구워진 클립에서 부호·축·크기까지 실측해 고정한다.

루트 프로퍼티가 둘 늘고, 같은 범위의 Limit Rotation이 걸린다:

| 프로퍼티 | 대상 | 범위 |
|----------|------|------|
| `eoir_pan` | 방위 [deg] | ±35 |
| `eoir_tilt` | 고각 [deg] | −45 … +30 |

범위는 센서면 가장자리·창이 원통 기수에 먹히지 않는 **직사각형**이다(원통 28각형 대비 해석
계산, 1° 격자에서 간섭 0 — `test_generate_shahed136.py`가 생성 스크립트의 리밋 값을 읽어
고정한다). 센서면 가장자리가 보어사이트에서 35°라 돌리면 곧 원통 쪽으로 넘어간다 — 비는 방위는
tilt 0에서 ±54°, −30°에서 ±48°, −40°에서 ±41°, −45°에서 ±35°, −50°에서 ±26°로 줄고, −60°에서는
정면(pan 0)도 먹힌다. 축별 리밋은 이 결합 영역을 그리지 못하므로 그 안의 직사각형으로 잘랐다.
센서면을 크게 자를수록 사진에 가깝지만 범위가 더 준다.

**리밋은 `.blend`에만 있다.** GLB에는 컨스트레인트가 안 들어가므로, three.js에서 짐벌을
직접 돌리면 앱이 위 범위로 클램프해야 한다.

데모 1–168 프레임에는 짐벌 탐색(좌우 훑기 → 내려다보며 추적 → 복귀)이 겹쳐 있다.
미리보기는 센서면이 보이도록 전방 쿼터뷰, 프레임 72(pan +35°)다.

```js
el('EOIR_Pan').rotation.y = -deg(30);    // 우측 30°
el('EOIR_Tilt').rotation.x = deg(-20);   // 아래 20°
```

## 재생성

```bash
blender -b --factory-startup -P generate_shahed136.py                       # 기본형
SHAHED_VARIANT=eoir blender -b --factory-startup -P generate_shahed136.py   # EOIR형
```

기본형은 `shahed136.blend`, `shahed136.glb`, `preview.png`를, EOIR형은 같은 이름에 `_eoir`가
붙은 셋을 만든다 — 서로의 산출물을 덮지 않는다. 렌더를 건너뛰려면
`SHAHED_SKIP_RENDER=1`. glTF 내보내기는 Blender 내장 파이썬에 `numpy`가 필요하다
(없으면 그 단계만 건너뛰고 `.blend`는 정상 생성).

저장된 `.blend`는 인터랙티브용 드라이버 리그를 그대로 유지한다 — GLB용 베이크는
내보내기 직전 in-메모리 상태에서만 일어나고 `.blend`에는 반영되지 않는다.

### 커밋 대상과 블렌더 numpy

`.glb`·`.py`·README만 커밋하고 `.blend`·`preview.png`는 커밋하지 않는다. 그리고 내장
numpy가 못 뜨는 블렌더에서는 GLB 내보내기가 **조용히** 빠진다. 두 사유와 대처는
`models/README.md`에 한 번만 적혀 있다 — 여기 옮겨 적으면 갈린다.

Blender 4.0.2·5.2.1 / three.js r185에서 검증. 외부 에셋·애드온 의존성 없음.
