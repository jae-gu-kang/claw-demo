# web — M14 프론트엔드 (Phase 5)

**바닐라 ES 모듈 + no-build** [확정 02 §4]. 외부 의존은 3D 월드 렌더링 **1건뿐**이고, 그것도 반입물은 커밋된 빌드 산출물 `world/build/world.js` 하나다(three는 `world/`의 npm devDependency — 개발 머신 전용, 06 §6). 나머지 반입물은 이 디렉터리 파일 전부이며, 현지 수정은 텍스트 에디터로 가능하다. eval-free
디렉터리 파일 전부이며, 현지 수정은 텍스트 에디터로 가능하다. eval-free
(엄격 CSP 호환), 플롯은 자체 Canvas.

## 실행

빌드 없음 — 서버(M13)가 정적 서빙한다:

```bash
scripts/run.sh          # 모노레포 루트에서 (설치까지 겸함)
# → http://127.0.0.1:8000/
```

## 구조

```
index.html            # 탭 네비 — **왼쪽에서 오른쪽이 업무 순서**다 (06 §3, 순서 정본은 02 §8):
                      #   블록도·엔벨로프·트림 → 게인·마진 맵·자동 설계 →
                      #   시뮬레이션·가상환경 → 영향성 → Autocode·검증 | 결과
                      #   탭은 **설계 단계**만. 런 하나를 다시 읽는 화면(타면 사용)은
                      #   그 단계 탭의 패널이다. 나열 순서는 main.js VIEWS와 같아야
                      #   하고 lib/blocks.test.js가 배열로 대조한다
css/app.css
js/
├── main.js           # 해시 라우팅 (기본 = 구조도 허브) + 헬스 폴링
├── api.js            # REST 래퍼·ApiError·watchJob(WS 우선, 폴링 폴백)
├── dom.js            # el() 조립·fmt(비유한값 정책)·flagBadge(3-상태)
├── store.js          # 탭 간 공유 상태 (게인·AP 편집본 전달 등)
├── lib/              # 순수 로직 37개 (공존 *.test.js로 테스트)
│   ├── 블록도·매뉴얼   blocks · manualdoc · schemaform · wiresignals
│   ├── 격자·배치      grid · stage · specs · loops
│   ├── 엔벨로프·트림   envelope
│   ├── 게인·자동설계   gainsched · gainsync · autodesign · polyfit
│   ├── 평가·진단      evaluate · prescribe · duty
│   ├── 영향성        influence · influencelayout · influenceplay
│   ├── 시뮬·재생      mission · replay · playback · playcursor
│   ├── 지도·지형      geo · wpmap · terrainpack · site
│   ├── 3D·기하       world3d · attitude · uavmesh · camera · plot3d
│   ├── 코드·검증      highlight · flightcode · codegen · verify
│   └── 플롯          plot
└── views/            # DOM 조립 전용 26개 (얇게 유지)
    ├── 뼈대·공용      stage · plots · progress · evalcards · codeview
    ├── 블록도        blocks · diagram · subsystems · manual
    ├── 엔벨로프      envelope
    ├── 트림 (3단계)   trim
    ├── 게인 (4단계)   gains
    ├── 마진 맵 (5단계) margins
    ├── 자동 설계 (6단계) autodesign
    ├── 시뮬 (7단계)   sim · wpmap · duty · replayoverlay
    ├── 가상환경 (8단계) world           ← world/ 번들로 넘기는 얇은 어댑터
    ├── 영향성 (9단계)  influence · influencecanvas · plot3d
    ├── Autocode (10단계) autocode · codegen
    ├── 검증 (11단계)  verify
    └── 결과 (12단계)  results
world/                # 가상환경 번들 (별도 빌드 — 반입물은 build/world.js)
├── src/core/         #   판단: 자세·카메라·해수면·지형 좌표 (순수 함수, 테스트)
├── src/scene|shaders|post/  #   three를 아는 층
├── src/ui|data|lib/  #   화면 조립·자산
└── build/world.js    #   커밋된 산출물 (비-미니파이드 ESM)
```

## 탭 배치 규약

**주 그림은 카드 밖 전면, 나머지는 패널** (06 §2). 그 탭의 주 질문에 답하는 것이
카드 없이 페이지 위에 놓이고(`tabStage`), 표·수치판처럼 테두리가 없으면서 늘 보여야
하는 것은 판독 시트(`.tab-sheet`), 나머지는 분류로 묶인 칩을 눌러야 열린다
(`createDrawers` — 한 번에 하나). 실행 버튼과 잡 상태는 무대에 남기고, 잡이 끝나면
결과가 사는 패널을 열어 준다.

새 탭을 만들 때 이 뼈대를 베끼지 말 것 — `views/stage.js` 하나를 쓴다. 어두운 탭은
루트에 `tab-dark`를 함께 주는데, 그 자격은 **주 그림 자체가 검은 캔버스**인 경우뿐이다
(지금은 영향성·가상환경 둘). Autocode는 코드판만 어둡고 페이지는 밝다.

그리고 **최상위 탭은 설계 단계 하나씩**이고, **줄의 순서가 업무 순서**다. "런 하나를
다시 읽는 방법"(타면 사용 같은 것)은 탭이 아니라 그 단계 탭의 패널이다 — 최상위에
두면 사용자가 결과를 두 번 고르게 되고 그 둘이 어긋날 수 있다.

순서가 뜻을 갖는 만큼 **단계 사이는 배선돼 있어야 한다**: 시뮬 탭이 낸 런 하나가
[가상환경에서 보기]·[영향성에서 진단]으로 넘어간다. 지목은 store `simResult` 하나로
통일돼 있고(가상환경이 목록에서 고른 런도 같은 키를 갱신한다), 화면을 바꾸는 인계만
`influenceHandoff`를 따로 실어 **받는 쪽이 한 번 읽고 지운다**(wpDraft와 같은 규약).
순서만 바꾸고 배선이 없으면 탭 줄이 하지 않는 일을 말하게 된다.

패널(칩) 줄도 같은 문법이다 — 중요도가 아니라 **그 탭에서 먼저 하는 일** 순으로
세운다(영향성: 파라미터 → 평가·처방 → 감도 → ⚠경고).

## 테스트 (개발 환경 전용 — 반입물 아님)

```bash
node --test "js/**/*.test.js"   # web/ 에서 — node 내장 러너, npm 의존 0
```

## 알려진 표시 한계

- 재생은 다운샘플(stride) 뷰 — 모드 밴드 경계가 최대 `stride×dt`(기본 ~0.12 s)
  이동할 수 있고, stride보다 짧은 모드는 밴드가 생략될 수 있다. 수치 판정은
  항상 서버 저장 원본(전 해상도)이 정본.
