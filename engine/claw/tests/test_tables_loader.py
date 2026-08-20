"""M3 tables 검증 — long-format CSV 로더·실속 경계 테이블 (Phase 1 백로그 소진)."""

import pytest

from claw.tables import TableError, load_stall_boundary_csv, load_table_csv


def write_aero_csv(path, drop_last=False, dup_first=False):
    """CL(mach, alpha) = mach + 0.1·alpha 인 2×3 정규격자 long-format CSV."""
    lines = ["mach,alpha,CL"]
    for mach in (0.5, 0.8):
        for alpha in (0.0, 5.0, 10.0):
            lines.append(f"{mach},{alpha},{mach + 0.1 * alpha}")
    if drop_last:
        lines = lines[:-1]
    if dup_first:
        lines.append(lines[1])
    path.write_text("\n".join(lines), encoding="utf-8")


def test_load_round_trip(tmp_path):
    p = tmp_path / "cl.csv"
    write_aero_csv(p)
    t = load_table_csv(p, axis_cols=["mach", "alpha"], value_col="CL")
    assert t.data.shape == (2, 3)
    assert t.name == "CL"
    assert t(mach=0.8, alpha=10.0) == pytest.approx(1.8)  # 격자점
    assert t(mach=0.65, alpha=2.5) == pytest.approx(0.9)  # 격자 사이 쌍선형 보간


def test_axis_order_follows_axis_cols(tmp_path):
    p = tmp_path / "cl.csv"
    write_aero_csv(p)
    t = load_table_csv(p, axis_cols=["alpha", "mach"], value_col="CL")
    assert t.axis_names == ("alpha", "mach")
    assert t.data.shape == (3, 2)
    assert t(mach=0.5, alpha=5.0) == pytest.approx(1.0)


def test_incomplete_grid_rejected(tmp_path):
    p = tmp_path / "bad.csv"
    write_aero_csv(p, drop_last=True)
    with pytest.raises(TableError, match="격자 불완전"):
        load_table_csv(p, axis_cols=["mach", "alpha"], value_col="CL")


def test_duplicate_combination_rejected(tmp_path):
    p = tmp_path / "dup.csv"
    write_aero_csv(p, dup_first=True)
    with pytest.raises(TableError, match="중복"):
        load_table_csv(p, axis_cols=["mach", "alpha"], value_col="CL")


def test_missing_column_rejected(tmp_path):
    p = tmp_path / "cl.csv"
    write_aero_csv(p)
    with pytest.raises(TableError, match="없는 열"):
        load_table_csv(p, axis_cols=["mach", "beta"], value_col="CL")


def test_non_numeric_rejected(tmp_path):
    p = tmp_path / "nan.csv"
    p.write_text("mach,alpha,CL\n0.5,0.0,0.5\n0.5,5.0,abc\n", encoding="utf-8")
    with pytest.raises(TableError, match="수치 변환 실패"):
        load_table_csv(p, axis_cols=["mach", "alpha"], value_col="CL")


def test_empty_file_rejected(tmp_path):
    p = tmp_path / "empty.csv"
    p.write_text("mach,alpha,CL\n", encoding="utf-8")
    with pytest.raises(TableError, match="데이터 행이 없음"):
        load_table_csv(p, axis_cols=["mach", "alpha"], value_col="CL")


def test_extrapolate_policy_passthrough(tmp_path):
    p = tmp_path / "cl.csv"
    write_aero_csv(p)
    t = load_table_csv(p, axis_cols=["mach", "alpha"], value_col="CL", extrapolate="error")
    with pytest.raises(TableError):
        t(mach=2.0, alpha=0.0)


def test_bom_header_tolerated(tmp_path):
    # 공력팀 Excel 저장 CSV의 UTF-8 BOM 대비 (utf-8-sig 판독)
    p = tmp_path / "bom.csv"
    body = "mach,alpha_stall\n0.3,16.0\n0.6,14.0\n0.9,10.0\n"
    p.write_bytes(b"\xef\xbb\xbf" + body.encode("utf-8"))
    t = load_stall_boundary_csv(p)
    assert t(mach=0.3) == pytest.approx(16.0)


def test_stall_boundary_loader(tmp_path):
    p = tmp_path / "stall.csv"
    p.write_text("mach,alpha_stall\n0.3,16.0\n0.6,14.0\n0.9,10.0\n", encoding="utf-8")
    t = load_stall_boundary_csv(p)
    assert t.name == "alpha_stall"
    assert t(mach=0.45) == pytest.approx(15.0)  # 보간
    assert t(mach=1.2) == pytest.approx(10.0)  # 기본 clip 외삽 — 경계값 고정
    assert t.in_range(mach=1.2) is False  # 엔벨로프 플래그 근거는 별도 노출
