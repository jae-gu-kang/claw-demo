# web — M14 프론트엔드 (Phase 5)

**바닐라 ES 모듈 + no-build** [확정 02 §4]. 외부 의존은 3D 월드용 vendored three.js **1건뿐**이며 CDN이 아니라 `js/vendor/` 아래 파일이다(출처·해시·`eval` 0건 검사 결과는 `js/vendor/three/VERSION`). 폐쇄망 반입물은 이
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
index.html            # 탭 네비 (구조도/엔벨로프/트림/게인/마진 맵/시뮬레이션/…) — 설계 순서
css/app.css
js/
├── main.js           # 해시 라우팅 (기본 = 구조도 허브) + 헬스 폴링
├── api.js            # REST 래퍼·ApiError·watchJob(WS 우선, 폴링 폴백)
├── dom.js            # el() 조립·fmt(비유한값 정책)·flagBadge(3-상태)
├── store.js          # 탭 간 공유 상태 (게인·AP 편집본 전달 등)
├── lib/              # 순수 로직 (공존 *.test.js로 테스트)
│   ├── blocks.js     #   블록 계약 데이터 — 주 경로 CHAIN·스키마·편집 경로 (허브 계약)
│   ├── schemaform.js #   레지스트리 JSON 스키마 → 폼 필드·입력 검증
│   ├── grid.js       #   트림 격자 — 서펜타인 순서 (인접 시드 전제 01 §4.1)
│   ├── plot.js       #   스케일·눈금·마진 상태색·격자 피벗
│   ├── mission.js    #   편집 행 → 미션 스펙 (조건 인자수 = 엔진 _COND_ARITY)
│   ├── replay.js     #   stride 산정·모드 구간·극값
│   ├── playcursor.js #   재생 커서 정본 — 벽시계 경과 → 샘플 인덱스 (시뮬·3D 월드 공유)
│   ├── geo.js        #   NED↔위경도↔타일 (엔진 claw.env.geodesy의 짝, 공유 고정점으로 대조)
│   ├── attitude.js   #   3-2-1 오일러 → 쿼터니언 → 동체축의 NED 성분 (규약 §2)
│   ├── uavmesh.js    #   기체 형상 — 엔진 기준량(S·c̄·b)에서 만드는 절차적 메시
│   └── camera.js     #   시점 4종 (추적·궤도·온보드·자세) + 지면 클램프
└── views/            # DOM 조립 전용 (얇게 유지)
    ├── blocks.js     #   구조도 허브: 블록 클릭 → 서브시스템 페이지 #blocks/<id> (02 §4)
    ├── diagram.js    #   최상위 SVG 블록도 (설계순서 프레임·피드백 — 시뮬링크 스타일)
    ├── subsystems.js #   서브시스템 내부 블록도 SVG·설계 노트 (엔진 구현과 1:1)
    ├── trim.js       #   2단계: 케이스 매트릭스 → 배치 → 판정 플래그 결과표
    ├── margins.js    #   3단계: PM/GM 히트맵·고유치 맵·감쇠비 테이블
    ├── envelope.js   #   V-n 선도 (01 §3.6 — 구조 한계는 데모 자리표시)
    ├── gains.js      #   4단계: 게인 테이블 편집 → 시뮬 주입 (전체 교체)
    ├── sim.js        #   5단계: 모드 테이블·웨이포인트 편집 → 재생+엔벨로프
    ├── results.js    #   6단계 열람: 산출물 목록·계보 지문
    ├── plots.js      #   캔버스 렌더러 (히트맵·산점도·시계열·NED 궤적)
    ├── world.js      #   가상환경 탭 — 결과 선택·시점 4종·재생·환경
    ├── worldrenderer.js #  렌더러 계약 + 팩토리 (구현 교체 지점)
    └── renderer-three.js # three.js 어댑터 — 축 변환은 여기 toWorld 한 줄뿐
```

## 테스트 (개발 환경 전용 — 반입물 아님)

```bash
node --test "js/**/*.test.js"   # web/ 에서 — node 내장 러너, npm 의존 0
```

## 알려진 표시 한계

- 재생은 다운샘플(stride) 뷰 — 모드 밴드 경계가 최대 `stride×dt`(기본 ~0.12 s)
  이동할 수 있고, stride보다 짧은 모드는 밴드가 생략될 수 있다. 수치 판정은
  항상 서버 저장 원본(전 해상도)이 정본.
