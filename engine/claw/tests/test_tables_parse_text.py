"""CSV 텍스트 판독 — 파일 로더와 같은 판독을 지난다 (웹 기체 편집기 반입 경로, 02 §5.6)."""

import pytest

from claw.tables import TableError
from claw.tables.loader import load_table_csv, parse_table_csv

CSV = "mach,alpha,CL\n0.2,0.0,0.0\n0.2,0.1,0.35\n0.6,0.0,0.01\n0.6,0.1,0.37\n"


def test_text_and_file_loaders_build_the_same_table(tmp_path):
    path = tmp_path / "cl.csv"
    path.write_text("﻿" + CSV, encoding="utf-8")
    a = load_table_csv(path, ["mach", "alpha"], "CL")
    b = parse_table_csv("﻿" + CSV, ["mach", "alpha"], "CL")
    assert a.axis_names == b.axis_names == ("mach", "alpha")
    assert all((x == y).all() for x, y in zip(a.axes, b.axes))
    assert (a.data == b.data).all() and a.name == b.name == "CL"


def test_text_loader_reports_the_same_errors():
    with pytest.raises(TableError, match="CSV에 없는 열"):
        parse_table_csv(CSV, ["mach", "beta"], "CL")
    with pytest.raises(TableError, match="격자 불완전"):
        parse_table_csv(CSV.rsplit("\n", 2)[0] + "\n", ["mach", "alpha"], "CL")
