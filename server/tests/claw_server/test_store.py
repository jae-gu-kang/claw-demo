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


def test_limit_evicts_oldest(tmp_path):
    """보존 개수 상한(옵트인) — 저장 시 초과분을 오래된 것부터 본문·메타 함께 삭제.

    휘발성 디스크의 공개 데모 인스턴스에서 한 세션 안에 결과가 무한정 쌓이는 것
    방지. 기본(None)은 현행 무제한 그대로."""
    st = ResultStore(tmp_path, limit=2)
    for i, rid in enumerate(("a1", "b2", "c3")):
        st.save(rid, {"v": i}, meta={"created": float(i)})
    assert [m["id"] for m in st.list()] == ["c3", "b2"]
    assert not st.exists("a1")
    assert not (st.root / "a1.meta.json").exists()  # 메타도 함께 — 유령 목록 방지


def test_limit_below_one_rejected(tmp_path):
    """limit < 1은 생성 시점 ValueError — 0·음수면 슬라이스가 뒤집혀 방금 저장한
    결과까지 조용히 삭제되는(저장 성공인데 조회 404) 사고를 시끄럽게 차단."""
    for bad in (0, -2):
        with pytest.raises(ValueError):
            ResultStore(tmp_path, limit=bad)


def test_nan_rejected_at_save(tmp_path):
    """serialize 비유한값 정책 위반은 저장 시점 ValueError — 무효 JSON 미노출."""
    st = ResultStore(tmp_path)
    with pytest.raises(ValueError):
        st.save("x1", {"bad": float("nan")})
    assert not st.exists("x1")
    assert st.list() == []  # 메타 미기록 — 목록에 유령 결과 없음


# ── 줄 나눈 본문 — 긴 시계열을 한 줄씩 읽고 쓴다 (Render 512 MB 대비) ──────────
#
# S1 기본 미션(475 s × 100 Hz × 신호 95개) 본문은 68.6 MB이고, 통째로 읽으면 글 한 벌
# (meta의 한글 기체 이름 때문에 UCS-2 → 137 MB)과 파싱본(129 MB)이 동시에 선다.
# 아래 테스트는 그 두 벌이 다시 겹치지 않는지와, 필요한 항목만 파싱하는 경로를 고정한다.

import json
import tracemalloc


def _series_payload(n_sig=40, n=10000):
    """sim 본문 꼴의 합성 결과 — 신호 여럿 + 한글 meta(글이 UCS-2가 되는 조건) + 빈 dict·스칼라."""
    t = [i * 0.01 for i in range(n)]
    return {
        "t": t,
        "signals": {f"s{k}": [((i * 7919 + k) % 1000) / 3.0 for i in range(n)] for k in range(n_sig)}
        | {"mode": ["launch"] * (n // 2) + ["climb"] * (n - n // 2), "gap": [None] * n},
        "envelope": {"stall_margin": [0.1] * n, "flags": {"alpha": [False] * n},
                     "worst_margin": 0.1, "first_flag_t": None},
        "empty": {},
        "meta": {"profile": {"name": "쇼케이스 델타"}, "dt_plant": 0.01, "note": "a,\n b"},
        "kind": "sim",
    }


def _same(a, b):
    """값과 **키 순서**까지 같다 — 골든(hexjson)이 dict 순서를 본다."""
    assert a == b
    assert json.dumps(a, ensure_ascii=False) == json.dumps(b, ensure_ascii=False)


def test_body_is_one_json_document_with_a_line_per_entry(tmp_path):
    """본문은 여전히 JSON 문서 하나다(원본 JSON 링크·외부 도구 그대로) — 다만 최상위 항목마다,
    비지 않은 최상위 dict는 그 항목마다 한 줄이라 줄 단위로 읽을 수 있다."""
    st = ResultStore(tmp_path)
    p = _series_payload(n_sig=3, n=50)
    st.save("r1", p, meta={"created": 1.0})
    raw = (st.root / "r1.json").read_bytes()
    _same(json.loads(raw.decode("utf-8")), p)
    _same(st.load("r1"), p)
    lines = raw.decode("utf-8").split("\n")
    assert lines[0] == "{" and lines[-2:] == ["}", ""]
    # 신호 하나가 한 줄 — 줄 머리가 곧 키다
    assert [ln[:6] for ln in lines if ln[:3] in ('"s0', '"s1', '"s2')] == ['"s0": ', '"s1": ', '"s2": ']
    assert any(ln.startswith('"gap": [null') for ln in lines)
    # 줄 경계는 \n뿐 — 값 안의 개행은 이스케이프되고 U+2028은 줄을 나누지 않는다
    assert '"note": "a,\\n b"' in raw.decode("utf-8")


def test_load_want_skips_entries_without_parsing_them(tmp_path):
    """want(path)가 거짓이면 그 줄은 파싱하지 않는다 — 손상된 줄도 건드리지 않고 지나간다."""
    st = ResultStore(tmp_path)
    p = _series_payload(n_sig=3, n=50)
    st.save("r1", p)
    path = st.root / "r1.json"
    text = path.read_text(encoding="utf-8")
    bad = "\n".join('"s1": @손상@,' if ln.startswith('"s1": ') else ln for ln in text.split("\n"))
    path.write_text(bad, encoding="utf-8")
    with pytest.raises(ValueError):
        st.load("r1")  # 통째 읽기는 손상을 만난다
    got = st.load("r1", want=lambda path: path != ("signals", "s1"))
    exp = {**p, "signals": {k: v for k, v in p["signals"].items() if k != "s1"}}
    _same(got, exp)
    # 하위 항목을 다 걸러도 그릇(dict)은 남는다 — 소비자가 .get("signals")로 빈 dict를 받는다
    only_t = st.load("r1", want=lambda path: path[0] in ("t", "signals") and path[-1] != "s1"
                     and path[-1] in ("t", "mode"))
    assert list(only_t) == ["t", "signals", "envelope", "meta"]  # 빈 dict "empty"는 (키,) 항목이라 걸러졌다
    assert list(only_t["signals"]) == ["mode"] and only_t["envelope"] == {} == only_t["meta"]


def test_load_each_transforms_entry_by_entry(tmp_path):
    """each(path, value)는 항목마다 불린다 — 재생 stride 솎음이 파싱 직후 한 줄씩 끝난다."""
    st = ResultStore(tmp_path)
    p = _series_payload(n_sig=3, n=50)
    st.save("r1", p)
    seen = []

    def each(path, v):
        seen.append(path)
        return v[::7] if isinstance(v, list) else v

    got = st.load("r1", each=each)
    assert got["t"] == p["t"][::7] and got["signals"]["s2"] == p["signals"]["s2"][::7]
    assert got["envelope"]["flags"] == p["envelope"]["flags"]  # dict 값은 each가 받은 그대로
    # 경로: 최상위 (키,) · 비지 않은 최상위 dict는 (키, 하위 키) · 빈 dict는 (키,)
    assert ("t",) in seen and ("signals", "mode") in seen and ("envelope", "flags") in seen
    assert ("empty",) in seen and ("signals",) not in seen


def test_single_line_file_from_before_still_loads(tmp_path):
    """이 형식 이전의 한 줄 본문도 그대로 읽힌다 — want/each도 같은 경로 규칙으로 적용된다."""
    st = ResultStore(tmp_path)
    p = _series_payload(n_sig=3, n=50)
    (st.root / "old1.json").write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")
    st.save("new1", p)
    _same(st.load("old1"), p)

    def want(path):
        return path != ("signals", "s0")

    def each(path, v):
        return v[::5] if isinstance(v, list) else v

    _same(st.load("old1", want=want, each=each), st.load("new1", want=want, each=each))


def test_single_line_file_is_read_once_not_twice(tmp_path, monkeypatch):
    """한 줄 본문의 머리 판정은 몇 바이트만 본다 — 첫 줄을 통째로 읽으면 파일 전체(수십 MB)를
    판정에 한 번, 파싱에 또 한 번 읽는다."""
    import claw_server.store as store_mod

    st = ResultStore(tmp_path)
    p = _series_payload(n_sig=3, n=2000)
    (st.root / "old1.json").write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")
    size = (st.root / "old1.json").stat().st_size
    got = []

    class Counting:
        def __init__(self, fh):
            self._fh = fh

        def __getattr__(self, name):
            return getattr(self._fh, name)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return self._fh.__exit__(*exc)

        def __iter__(self):
            for line in self._fh:
                got.append(len(line))
                yield line

        def readline(self, *a):
            line = self._fh.readline(*a)
            got.append(len(line))
            return line

        def read(self, *a):
            data = self._fh.read(*a)
            got.append(len(data))
            return data

    real_open = open
    monkeypatch.setattr(store_mod, "open", lambda *a, **k: Counting(real_open(*a, **k)), raising=False)
    _same(st.load("old1"), p)
    assert sum(got) <= size + 8, (sum(got), size)


def test_load_peak_is_the_parsed_body_not_text_plus_body(tmp_path):
    """통째 읽기의 정점 = 파싱본 + 한 줄. 예전에는 파일 글 전체(한글 meta면 UCS-2라 파일의 2배)가
    파싱본과 함께 떠 있었다 — 68.6 MB 본문에서 +274 MB(Render 512 MB의 절반)."""
    st = ResultStore(tmp_path)
    st.save("big", _series_payload())
    size = (st.root / "big.json").stat().st_size
    tracemalloc.start()
    try:
        body = st.load("big")
        current, peak = tracemalloc.get_traced_memory()
        del body
        assert peak - current < 0.25 * size, (peak, current, size)
        # 솎아 읽기는 파싱본 한 벌도 세우지 않는다
        tracemalloc.reset_peak()
        base = tracemalloc.get_traced_memory()[0]
        lean = st.load("big", each=lambda path, v: v[::50] if isinstance(v, list) else v)
        lean_peak = tracemalloc.get_traced_memory()[1] - base
        del lean
        assert lean_peak < 0.25 * size, (lean_peak, size)
    finally:
        tracemalloc.stop()


def test_save_peak_is_one_line_not_the_whole_text(tmp_path):
    """쓰기도 줄 단위 — 예전에는 dumps 글 한 벌(UCS-2면 2배) + utf-8 바이트 한 벌이 결과 위에 섰다."""
    st = ResultStore(tmp_path)
    p = _series_payload()
    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        base = tracemalloc.get_traced_memory()[0]
        st.save("big", p)
        peak = tracemalloc.get_traced_memory()[1] - base
    finally:
        tracemalloc.stop()
    size = (st.root / "big.json").stat().st_size
    assert peak < 0.25 * size, (peak, size)


def test_failed_save_leaves_no_temp_file(tmp_path):
    """줄 단위 쓰기는 중간에 실패할 수 있다(NaN 등) — 반쯤 쓴 tmp를 남기지 않는다."""
    st = ResultStore(tmp_path)
    with pytest.raises(ValueError):
        st.save("x1", {"ok": [1.0], "signals": {"a": [1.0], "b": [float("inf")]}})
    assert not st.exists("x1")
    assert list(st.root.iterdir()) == []


def test_missing_body_is_a_keyerror_on_every_path(tmp_path):
    """본문 없음은 골라 읽기에서도 KeyError다 — 라우트가 404로 옮긴다(보존 상한이 방금 지운 경합 포함)."""
    st = ResultStore(tmp_path)
    with pytest.raises(KeyError):
        st.load("gone1")
    with pytest.raises(KeyError):
        st.load("gone1", want=lambda path: True)


def test_open_body_hands_out_the_stored_json_bytes(tmp_path):
    """open_body — 통째 전달(원본 JSON)을 파싱 없이 흘려보내는 길. 파일 바이트가 곧 JSON 문서다."""
    st = ResultStore(tmp_path)
    p = _series_payload(n_sig=2, n=20)
    st.save("r1", p)
    with st.open_body("r1") as fh:
        _same(json.loads(fh.read().decode("utf-8")), p)
    # 연 뒤에 보존 상한이 지워도 연 핸들로는 끝까지 읽힌다 (POSIX)
    fh = st.open_body("r1")
    st.delete("r1")
    with fh:
        _same(json.loads(fh.read().decode("utf-8")), p)
    with pytest.raises(KeyError):
        st.open_body("r1")
    with pytest.raises(ValueError):
        st.open_body("../x")


# ── 골라 읽기(load_picked) — 엔진 함수가 무엇을 읽을지 다 모르는 소비자(타면 사용·진단·교신) ──────


def _corrupt(st, rid, key):
    """본문의 신호 한 줄을 망가뜨린다 — 그 줄을 파싱하면 ValueError다(파싱하지 않았다는 증거)."""
    path = st.root / f"{rid}.json"
    lines = path.read_text(encoding="utf-8").split("\n")
    i = next(i for i, ln in enumerate(lines) if ln.startswith(f'"{key}": '))
    lines[i] = f'"{key}": @손상@' + ("," if lines[i].endswith(",") else "")
    path.write_text("\n".join(lines), encoding="utf-8")


def test_load_picked_parses_only_the_named_entries_and_fills_the_rest_on_read(tmp_path):
    """names만 먼저 파싱하고, 목록 밖 항목은 있다고 답하며 읽는 순간 그 줄만 채운다 — 엔진의 선택 신호
    읽기(.get이 None이면 보정을 건너뛴다)가 조용히 다른 수를 내지 않게."""
    st = ResultStore(tmp_path)
    p = _series_payload(n_sig=4, n=50)
    st.save("r1", p)
    _corrupt(st, "r1", "s3")  # 아무도 읽지 않는 신호 — 통째 읽기라면 여기서 ValueError
    with pytest.raises(ValueError):
        st.load("r1")
    got = st.load_picked("r1", "signals", {"s0", "mode"})
    sig = got["signals"]
    assert dict.keys(sig) == {"s0", "mode"}  # 먼저 파싱한 것은 목록뿐이다
    assert [k for k in got] == list(p)  # box 밖 항목은 전부(want 없음) — 순서 그대로
    assert got["t"] == p["t"] and got["envelope"] == p["envelope"] and got["meta"] == p["meta"]
    # 목록 밖이지만 본문에 있는 신호 — 있다고 답하고, 읽으면 채운다
    assert "s1" in sig and len(sig) == len(p["signals"])
    assert sig.get("s1") == p["signals"]["s1"] and sig["gap"] == p["signals"]["gap"]
    assert dict.keys(sig) == {"s0", "mode", "s1", "gap"}  # 읽은 것만 채웠다(s2·s3은 아직)
    # 본래 없는 신호는 없다 — .get은 기본값, []는 KeyError
    assert "nope" not in sig and sig.get("nope", 7) == 7
    with pytest.raises(KeyError):
        sig["nope"]
    # 망가진 줄을 읽는 순간에야 손상이 드러난다 — 읽지 않으면 끝까지 모른다
    with pytest.raises(ValueError):
        sig.get("s3")


def test_load_picked_whole_iteration_equals_the_full_load_in_file_order(tmp_path):
    """통째로 훑는 소비자(items·keys·values·iter)는 전부 채운 dict를 **본문 순서로** 본다 — 채운 항목이 끝에
    붙은 채로 두면 json.dumps·순서 의존 소비자가 통째 읽기와 다른 글을 낸다."""
    st = ResultStore(tmp_path)
    p = _series_payload(n_sig=4, n=30)
    st.save("r1", p)
    for walk in (lambda s: list(s.items()), lambda s: list(s), lambda s: list(s.keys()),
                 lambda s: list(s.values())):
        got = st.load_picked("r1", "signals", {"s2"})
        got["signals"].get("s0")  # 일부를 먼저 채운 뒤 훑는다 — 채운 순서와 본문 순서가 다르다
        walk(got["signals"])
        _same(got, p)
    # want는 box 밖 항목의 골라 읽기다(load와 같은 경로 규칙)
    lean = st.load_picked("r1", "signals", {"s1"}, want=lambda path: path[0] != "envelope")
    assert lean["envelope"] == {} and lean["signals"]["s1"] == p["signals"]["s1"]


def test_load_picked_reads_the_single_line_body_from_before(tmp_path):
    """이 형식 이전의 한 줄 본문도 같은 규칙이다 — 목록 밖 신호는 읽으면 채워진다."""
    st = ResultStore(tmp_path)
    p = _series_payload(n_sig=3, n=20)
    (st.root / "old1.json").write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")
    got = st.load_picked("old1", "signals", {"s0"})
    assert dict.keys(got["signals"]) == {"s0"}
    assert got["signals"]["s2"] == p["signals"]["s2"]
    _same(dict(got["signals"].items()), p["signals"])
    with pytest.raises(KeyError):
        st.load_picked("gone1", "signals", {"s0"})
