"""M3 tables — nD 보간 엔진, 공력 DB 로더, 실속 경계 테이블 (구현 문서 §5.1~5.3).

구현됨: Table — numpy 다중선형 보간, 외삽 정책(clip/linear/error), 유효범위 질의
(엔벨로프 플래그 근거), 슬라이스 추출(DB 뷰어용).
후속: 공력 DB 로더(CSV/Excel — 파일 규격 [TBD], pandas 도입 시점 재결정),
실속 경계 테이블(공력팀 규격 협의 [TBD]).
"""

from claw.tables.table import Table, TableError

__all__ = ["Table", "TableError"]
