"""M13 server — FastAPI 백엔드 (03 M13): REST + 웹소켓 진행률 + 결과 저장.

엔진(claw) Python API만 호출 — 도메인 로직 없음 (02 §2.3 계층).
단독 사용자·로컬 서버 (02 §4). 기동: uvicorn 팩토리 = claw_server:create_app.
"""

from claw_server.app import create_app

__all__ = ["create_app"]
