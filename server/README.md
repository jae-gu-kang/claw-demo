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

## API 개요

| 경로 | 내용 |
|---|---|
| `GET /api/health` | 헬스체크 |
| `GET /api/registry`, `GET /api/registry/{cat}/{name}/schema` | 컴포넌트 목록·파라미터 JSON 스키마 (폼 자동 생성) |
| `POST /api/trim/batch` | 트림 케이스 매트릭스 → 배치 작업 (202 + job) |
| `GET /api/jobs`, `GET /api/jobs/{id}`, `POST /api/jobs/{id}/cancel` | 작업 조회·협조적 취소 |
| `GET /api/results`, `GET /api/results/{id}` | 저장 산출물 목록(메타)·본문 |
