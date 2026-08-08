"""게인 스케줄 라우트 (02 §8 워크플로우 4단계) — 설계 게인 테이블 조회.

편집 흐름: GET으로 설계 테이블을 받아 웹에서 편집 → 시뮬 요청(gain_tables)에
주입. 저장·버전관리는 파라미터 관리 계층(02 §5.5)과 함께 확장 [TBD].
"""

from fastapi import APIRouter

from claw.fcl.demo import make_demo_gain_tables
from claw_server.serialize import table_dict

router = APIRouter(tags=["gains"])


@router.get("/gains/demo")
def demo_gain_tables() -> dict:
    """데모 기체 설계 게인 테이블 — "그룹.게인" 이름 → 테이블 JSON."""
    return {name: table_dict(t) for name, t in make_demo_gain_tables().items()}
