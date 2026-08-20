"""공력 DB 로더 — long-format CSV → Table (구현 문서 §5.1).

입력 규격: 각 행이 (축1, 축2, …, 값) 한 조합인 long-format 표. 전체 축 조합
(Cartesian product)이 정확히 한 번씩 있어야 정규격자로 인정 — 누락·중복은
TableError (조용한 결손 금지, 검증 원칙 §7).

stdlib csv + numpy만 사용 — pandas 미도입(의존성 최소화 원칙, tables/__init__ 참조).
Excel 로더는 openpyxl 도입 시점에 같은 검증 경로를 재사용해 추가한다 [TBD].
"""

import csv

import numpy as np

from claw.tables.table import Table, TableError


def load_table_csv(path, axis_cols, value_col, name="", extrapolate="clip") -> Table:
    """long-format CSV 파일을 정규격자 Table로 변환.

    axis_cols 순서가 그대로 Table의 축 순서가 된다.
    """
    axis_cols = list(axis_cols)
    label = name or value_col

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames or []
        missing = [c for c in axis_cols + [value_col] if c not in header]
        if missing:
            raise TableError(f"{label}: CSV에 없는 열 {missing} (헤더: {header})")
        rows = []
        for lineno, row in enumerate(reader, start=2):
            try:
                key = tuple(float(row[c]) for c in axis_cols)
                val = float(row[value_col])
            except (TypeError, ValueError):
                raise TableError(f"{label}: {lineno}행 수치 변환 실패: {row}") from None
            rows.append((key, val))

    if not rows:
        raise TableError(f"{label}: 데이터 행이 없음")

    axes = {c: np.unique([k[i] for k, _ in rows]) for i, c in enumerate(axis_cols)}
    index = {c: {v: j for j, v in enumerate(ax)} for c, ax in axes.items()}

    expected_n = 1
    for ax in axes.values():
        expected_n *= ax.size

    shape = tuple(ax.size for ax in axes.values())
    data = np.full(shape, np.nan)
    for key, val in rows:
        idx = tuple(index[c][key[i]] for i, c in enumerate(axis_cols))
        if not np.isnan(data[idx]):
            raise TableError(f"{label}: 중복된 축 조합 {dict(zip(axis_cols, key))}")
        data[idx] = val

    if len(rows) != expected_n:
        missing_n = expected_n - len(rows)
        raise TableError(
            f"{label}: 격자 불완전 — 행 {len(rows)}개, 필요 {expected_n}개 (누락 {missing_n}건)"
        )

    return Table(axes, data, name=label, extrapolate=extrapolate)
