# web — M14 프론트엔드 (Phase 5)

**바닐라 ES 모듈 + no-build, 외부 의존 0** [확정 02 §4] — 폐쇄망 반입물은 이
디렉터리 파일 전부이며, 현지 수정은 텍스트 에디터로 가능하다. eval-free
(엄격 CSP 호환), 플롯은 자체 Canvas.

## 실행

빌드 없음 — 서버(M13)가 정적 서빙한다:

```bash
uvicorn --factory claw_server:create_app --port 8000
# → http://127.0.0.1:8000/
```

## 구조

```
index.html            # 탭 네비 (트림/마진 맵/게인/시뮬레이션/결과)
css/app.css
js/
├── main.js           # 해시 라우팅 + 헬스 폴링
├── api.js            # REST 래퍼·ApiError·watchJob(WS 우선, 폴링 폴백)
├── dom.js            # el() 조립·fmt(비유한값 정책)·flagBadge(3-상태)
├── store.js          # 탭 간 공유 상태 (게인 편집본 전달 등)
├── lib/              # 순수 로직 (공존 *.test.js로 테스트)
│   ├── grid.js       #   트림 격자 — 서펜타인 순서 (인접 시드 전제 01 §4.1)
│   ├── plot.js       #   스케일·눈금·마진 상태색·격자 피벗
│   ├── mission.js    #   편집 행 → 미션 스펙 (조건 인자수 = 엔진 _COND_ARITY)
│   └── replay.js     #   stride 산정·모드 구간·극값
└── views/            # DOM 조립 전용 (얇게 유지)
    ├── trim.js       #   2단계: 케이스 매트릭스 → 배치 → 판정 플래그 결과표
    ├── margins.js    #   3단계: PM/GM 히트맵·고유치 맵·감쇠비 테이블
    ├── gains.js      #   4단계: 게인 테이블 편집 → 시뮬 주입 (전체 교체)
    ├── sim.js        #   5단계: 모드 테이블·웨이포인트 편집 → 재생+엔벨로프
    ├── results.js    #   6단계 열람: 산출물 목록·계보 지문
    └── plots.js      #   캔버스 렌더러 (히트맵·산점도·시계열·NED 궤적)
```

## 테스트 (개발 환경 전용 — 반입물 아님)

```bash
node --test "js/**/*.test.js"   # node 내장 러너, npm 의존 0
```

## 알려진 표시 한계

- 재생은 다운샘플(stride) 뷰 — 모드 밴드 경계가 최대 `stride×dt`(기본 ~0.12 s)
  이동할 수 있고, stride보다 짧은 모드는 밴드가 생략될 수 있다. 수치 판정은
  항상 서버 저장 원본(전 해상도)이 정본.
