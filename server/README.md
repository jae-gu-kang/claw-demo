# server — M13 백엔드 (Phase 5)

FastAPI 기반 REST API + 웹소켓 진행률. 엔진(`engine/claw`)의 Python API만 호출하며 도메인 로직을 갖지 않는다.
단독 사용자·로컬 서버 (구현 문서 §4).

## 설치 (모노레포 루트에서)

```bash
pip install -e engine        # claw-engine 먼저 (claw-server가 PyPI에서 찾지 않도록 의도적 미기재)
pip install -e "server[dev]" # fastapi·uvicorn (+pytest·httpx)
```

## 기동

```bash
uvicorn --factory claw_server:create_app --port 8000
```

결과 저장 루트: `$CLAW_SERVER_DATA` (기본 `./server_data`).

## 테스트

```bash
cd server && python -m pytest -q
```

## API 개요 (02 §8 워크플로우 단계 대응)

| 경로 | 내용 |
|---|---|
| `GET /api/health` | 헬스체크 |
| `GET /api/registry`, `GET /api/registry/{cat}/{name}/schema` | 컴포넌트 목록·파라미터 JSON 스키마 (폼 자동 생성) |
| `POST /api/trim/batch` | 2단계: 트림 케이스 매트릭스 → 배치 작업 (202 + job, 판정 플래그 포함) |
| `POST /api/analysis/margin-map` | 3단계: 케이스 격자 + PI 루프 스펙 → 선형화·모드 분류·마진 맵 |
| `GET /api/gains/demo` | 4단계: 설계 게인 테이블 조회 (편집 후 시뮬 `gain_tables`로 주입) |
| `POST /api/sim/run` | 5단계: 미션 스펙 → 폐루프 시뮬 (항법 오차·작동기·게인/AP 오버라이드 옵션) |
| `GET /api/sim/{id}/replay?stride=n` | 시뮬 재생 다운샘플 뷰 (엔벨로프 포함) |
| `GET /api/jobs`, `GET /api/jobs/{id}`, `POST /api/jobs/{id}/cancel` | 작업 조회·협조적 취소 (부분 결과 보존) |
| `WS /api/ws/jobs/{id}` | 작업 진행률 푸시 (변화 시·종단 시 종료) |
| `GET /api/results`, `GET /api/results/{id}` | 저장 산출물 목록(메타)·본문 |

직렬화 정책: NaN→`null`, ±inf→`"inf"`/`"-inf"`, 복소 고유치→`[re, im]`.
검증 원칙: 도메인 검증은 엔진(구성 오류→422), 서버는 경계 유한성만 차단.
