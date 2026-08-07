"""테이블 조회 블록 — 보간 테이블을 Block 프로토콜로 감싸는 어댑터.

M7 fcl의 게인 스케줄(스케줄 변수 → 게인) 소비 형태. table은 axis_names와
interp(**point)를 가진 객체(M3 Table 등)를 덕 타이핑으로 받는다 — blocks(L1)가
tables(L1)를 import하지 않아 동일 계층 상호 의존 금지 규칙(03 §1)을 지킨다.
테이블 데이터 입력 블록이므로 레지스트리 등록 대상이 아니다 (registry.py 참조).
"""

from claw.blocks.base import Block


class LookupBlock(Block):
    NAME = "Lookup"

    def __init__(self, table, axis_order=None):
        order = tuple(axis_order) if axis_order is not None else tuple(table.axis_names)
        if set(order) != set(table.axis_names):
            raise ValueError(f"축 이름 불일치: {order} != {tuple(table.axis_names)}")
        self.table = table
        self.axis_order = order

    def step(self, u):
        """1축 테이블은 스칼라 u, n축은 axis_order 순서의 시퀀스 u."""
        vals = (u,) if len(self.axis_order) == 1 else tuple(u)
        return self.table.interp(**dict(zip(self.axis_order, vals)))
