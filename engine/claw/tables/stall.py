"""실속 경계 테이블 — α_stall(Mach) 공력팀 정본 로더 (구현 문서 §5.3).

sim·fcl의 엔벨로프 감시(실속 마진 = α_stall(현재 조건) − α, §6.1)와 α 리미터
(α_cmd_max = α_stall − 마진, 01 §3.2)가 이 테이블을 소비한다. 단위는 DB 파일
규약을 그대로 따른다 (경계 변환 원칙, conventions.md §3).
"""

from claw.tables.loader import load_table_csv
from claw.tables.table import Table


def load_stall_boundary_csv(
    path, mach_col: str = "mach", alpha_col: str = "alpha_stall", extrapolate: str = "clip"
) -> Table:
    """CSV (mach, alpha_stall) 열 → 1축 실속 경계 Table. 기본 외삽은 경계값 고정(clip)."""
    return load_table_csv(
        path,
        axis_cols=[mach_col],
        value_col=alpha_col,
        name="alpha_stall",
        extrapolate=extrapolate,
    )
