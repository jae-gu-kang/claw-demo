"""ResultStore 검증 — 본문/메타 분리 왕복, id 검증(경로 조작 차단), NaN 저장 거부."""

import pytest

from claw_server.store import ResultStore


def test_roundtrip_and_list(tmp_path):
    st = ResultStore(tmp_path / "store")
    st.save("a1", {"v": 1}, meta={"kind": "trim_batch", "created": 100.0})
    st.save("b2", {"v": 2}, meta={"kind": "sim", "created": 200.0})
    assert st.load("a1") == {"v": 1}
    assert st.exists("b2") and not st.exists("c3")
    lst = st.list()
    assert [m["id"] for m in lst] == ["b2", "a1"]  # created 내림차순
    assert lst[0]["kind"] == "sim"
    # 같은 id 재저장 = 덮어쓰기
    st.save("a1", {"v": 9}, meta={"created": 300.0})
    assert st.load("a1") == {"v": 9}


def test_bad_id_rejected(tmp_path):
    st = ResultStore(tmp_path)
    for bad in ("", "a/b", "../x", "a.b", "한글", "abc\n"):  # 후행 개행 포함 (리뷰 S2)
        with pytest.raises(ValueError):
            st.save(bad, {})
        with pytest.raises(ValueError):
            st.load(bad)
    with pytest.raises(KeyError):
        st.load("missing")


def test_list_skips_corrupt_meta(tmp_path):
    """손상 메타 파일 하나가 목록 전체를 죽이지 않음 (리뷰 N3)."""
    st = ResultStore(tmp_path)
    st.save("ok1", {"v": 1}, meta={"created": 1.0})
    (st.root / "bad.meta.json").write_text("{손상", encoding="utf-8")
    assert [m["id"] for m in st.list()] == ["ok1"]


def test_nan_rejected_at_save(tmp_path):
    """serialize 비유한값 정책 위반은 저장 시점 ValueError — 무효 JSON 미노출."""
    st = ResultStore(tmp_path)
    with pytest.raises(ValueError):
        st.save("x1", {"bad": float("nan")})
    assert not st.exists("x1")
    assert st.list() == []  # 메타 미기록 — 목록에 유령 결과 없음
