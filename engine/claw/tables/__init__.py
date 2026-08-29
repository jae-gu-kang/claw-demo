"""M3 tables — nD 보간 엔진, 공력 DB 로더, 실속 경계 테이블 (구현 문서 §5.1~5.3).

구현됨: Table — numpy 다중선형 보간, 외삽 정책(clip/linear/error), 유효범위 질의
(엔벨로프 플래그 근거), 슬라이스 추출(DB 뷰어용); long-format CSV 로더(격자
완전성·중복 검증, stdlib csv — pandas 미도입); 실속 경계 테이블 로더.
후속: Excel 로더(openpyxl 도입 시점 [TBD]), 공력팀 테이블 규격 협의 [TBD].
"""

from claw.tables.loader import load_table_csv
from claw.tables.poly import PolyTable
from claw.tables.stall import load_stall_boundary_csv
from claw.tables.table import Table, TableError

__all__ = ["Table", "PolyTable", "TableError", "load_table_csv", "load_stall_boundary_csv"]
