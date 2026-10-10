# Banshee Jet 80+ — 쌍발 제트 표적기 모델 (가상환경용 GLB)

쌍발 터보제트 표적기 Banshee Jet 80+의 3D 모델. 원본은 **분해·조립 리그가 달린 절차적 블렌더
모델**(`banshee_assembly.py`)이고, 가상환경(`#world`)이 모는 `banshee.glb`는 그 결과를 **shahed와
같은 규약**으로 굽기만 한 것이다(`generate_banshee.py`). 규약(축·노드 이름·부호·구동 노드 선언)의
정본은 이 문서다.

> 바깥 형상은 공개된 익폭·전장·높이(2.49 / 2.90 / 0.78 m)와 사진을 따른 **시각화용** 근사이고,
> 내부 장비 배치는 조립 애니메이션을 위한 예시다 — 실기체 설계·제조 데이터가 아니다. 기체의
> 공력·질량 데이터는 이 폴더에 없다(프로파일 문서가 정본 — 02 §5.6).

## 파일

| 파일 | 내용 | 커밋 |
|------|------|------|
| `banshee_assembly.py` | 원본 모델 — 형상·장비·분해(explode) 리그·조립 순서를 처음부터 만드는 스크립트 (정본, **손대지 않는다**) | ○ |
| `generate_banshee.py` | 원본을 불러 가상환경 규약으로 **내보내기만** 하는 스크립트 — 축 회전·노드 이름·러더 프레임·구동 노드 선언 | ○ |
| `banshee.glb` | 가상환경이 읽는 glTF — 조립 상태로 굳히고 애니메이션 없음 (1.4 MB · 노드 64 · 메시 56 · 재질 22) | ○ |
| `test_generate_banshee.py` | 커밋된 GLB를 **블렌더 없이** 읽어 축·구동 노드·정지 회전·엘레본/러더 부호·발사관 길이를 검사 — `pytest models` | ○ |
| `banshee.blend` · `.blend1` | 내보내기 직전 상태의 블렌더 파일(재생성됨) | × (`.gitignore`) |
| `Banshee_Jet80_Assembly.blend` · `.glb` | 원본 스크립트가 직접 낸 산출(분해 리그·`explode_anim` 클립 포함) — 가상환경은 쓰지 않는다 | × |
| `A1_exploded.png` … `A6_parts_and_order.png` | 원본의 분해도·장비·조립 순서 렌더(참고 그림) | × |

재생성:

```
/Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup -P models/banshee/generate_banshee.py
```

블렌더 내장 numpy가 못 뜨는 환경의 보정은 `models/blender_numpy.py`(자동으로 불린다). 커밋 규칙
(`.glb`·스크립트·README만)은 `models/README.md`.

## 원본 모델 (`banshee_assembly.py`)

- 오브젝트 이름은 전부 `Jet80_` 접두 — 외피(`NoseCone`·`FuselageLower/Upper`·`Hatch`·`EngineCowl`·`Fin`·`Rudder`),
  주익(`Wing.L/.R` + 엘레본 패널 4·서보·링키지), 구조(프레임·엔진 크래들·스파), 장비(루네베르크 렌즈·항전
  트레이·배터리·연료탱크·낙하산·엔진 2 …). 뿌리는 `Jet80_ROOT` 엠프티, 원점은 **MAC 25 % 동체 축선**.
- 원본 규약: m 단위, **기수 −Y · 위 +Z · 좌익 +X**(블렌더). 타면은 힌지선을 원점으로 둔 별도 메시이고
  로컬 X 회전만 한다(±30°): 엘레본 +X = 뒷전 **아래**, 러더 +X = 뒷전 **왼쪽**.
- 분해도·조립 순서: 루트 프로퍼티 `explode`(0 조립 … 1 완전 분해)와 타임라인(1–240 프레임, `explode_anim`).
  부품마다 `assembly_order`·`explode_offset`·`explode_window`가 있다. 가상환경은 이것을 쓰지 않는다 —
  `generate_banshee.py`가 드라이버·키를 걷어 내고 0에 굳힌다(실행 환경에 따라 분해도가 구워지지 않게).

## 가상환경 규약 (`banshee.glb`) — shahed와 같다

가상환경(`web/world/src/scene/models.ts` · `core/surfaces.ts`)은 모델을 **하나의 규약**으로 몬다. 이 모델에서
그 규약을 맞춘 방법:

| 항목 | 규약 | 이 모델에서 |
|------|------|-------------|
| 축 | glTF 로컬 **+X 우현 · +Y 위 · +Z 후방**(기수는 −Z) | 원본이 기수 −Y·좌익 +X라 그대로 내보내면 shahed와 180° 돌아 있다 → 루트를 Z축 180° 회전 |
| 원점 | 무게중심 근처(`core/modelaxes.ts`) | 원본 그대로 MAC 25 %. 기수까지 1.819 m, 최후방 **1.08 m** |
| 엘레본 | `Elevon_In_L/Out_L/In_R/Out_R`, `rotation.x = δ`, + = 뒷전 아래 | 원본 패널 이름만 바꿈(`Jet80_Elevon_In.L` → `Elevon_In_L` — three는 점을 지우므로 점 없는 이름) |
| 러더 | `Rudder`, `rotation.y = −δr`(로컬 +Y 회전 = 뒷전 **오른쪽**) | 원본은 로컬 +X 회전 = 뒷전 왼쪽 → 힌지 밑에 `Rudder_Frame`(블렌더 로컬 Z를 힌지 −X로 눕힘) › `Rudder`(항등, **모는 노드**) 두 겹을 끼우고 원본 메시를 그 밑에 자리 그대로 매단다 |
| 프로펠러 | `Propeller`(shahed) | **없다** — 쌍발 제트. 선언으로 뺀다(아래) |
| 애니메이션 | 싣지 않는다(화면이 클립을 재생하지 않고, 바이트는 반입 꾸러미에 영구히 남는다) | `export_animations=False` |

### 구동 노드 선언 — `claw_drive_nodes`

모델마다 가진 타면이 다르다(이 기체는 러더 하나, 프로펠러 없음). 화면이 shahed 목록을 고정으로 기대하면
멀쩡한 모델에 「못 찾은 노드: Rudder_L, Rudder_R, Propeller」가 붙는다. 그래서 **모델이 자기 구동 노드를
선언한다** — 루트 엠프티의 사용자 속성 `claw_drive_nodes`(쉼표 목록)가 glTF extras로 실리고, three가
`userData`로 읽는다(`core/surfaces.ts driveNodesFor`):

```
claw_drive_nodes = "Elevon_In_L,Elevon_Out_L,Elevon_In_R,Elevon_Out_R,Rudder"
```

- 선언이 있으면 **그 이름만** 기대하고, 빠진 것을 「못 찾은 노드」로 말한다.
- 화면이 몰 줄 모르는 이름(예: 카나드)은 기대하지 않고 「선언했지만 몰 줄 모르는 노드」로 따로 말한다.
- 선언이 없는 모델(shahed)은 종전 목록(쌍 러더 + 프로펠러)을 기대한다 — 재굽기로 이름이 바뀐 것을 계속 잡는다.
- 타면 캡션도 선언을 따른다: 단발 러더에 「러더 두 면」, 제트기에 프로펠러 표시 규약을 말하지 않는다.

루트 extras에는 원본이 둔 `variant`·`span_m`·`length_m`·`nose_to_origin_m`·`assembly_stages`도 함께 실린다
(참고값 — 화면은 읽지 않는다).

### 계층

```
Jet80_ROOT (Z 180°, extras)
 › Jet80_FuselageLower / Upper / NoseCone / Hatch / EngineCowl / 구조·장비 …
 › Jet80_Wing.L / Wing.R › Elevon_In_* / Elevon_Out_* (모는 노드) › 서보 링키지
 › Jet80_Fin › Jet80_Hinge_Rudder › Rudder_Frame › Rudder (모는 노드) › Jet80_Rudder (메시)
```

모는 노드 다섯의 정지 회전은 **항등**이다 — three가 `rotation.x`/`.y`만 덮어쓰므로 정지 회전이 있으면
축이 힌지와 어긋난다(`test_drive_nodes_have_identity_rest`).

## 발사관

최후방이 원점 뒤 1.08 m라 발사관 상수 `VEHICLE_AFT_EXTENT`(1.90 m, shahed의 센터 너트) 안에 든다 —
`test_fits_launcher_tube`가 고정한다. 발사관 안에서는 shahed보다 0.8 m 앞쪽 여유가 남는다(관 길이는 그대로).

## 쓰는 법

프로파일 문서의 표시 모델에 이름만 적는다 — `display: {kind: "model", model: "banshee.glb"}`(02 §5.6).
서버가 `models/*/*.glb`를 이름으로 찾아 싣고(`server/claw_server/routes/world.py`), 가상환경은 그 런의
문서에서 이 절을 읽어 모델을 고른다(06 §6). 이 폴더에는 기체 프로파일이 없다 — 공력·질량·추진 데이터는
프로파일이 정본이고, 모델은 그리는 방법일 뿐이다.
