"""트림 풀이/조립 분리 + 트림 저장소 (05 §11.8 트림·모델 저장소).

- trim_level = assemble_level(solve_level) — 비트 동일
- trim_batch(store=None)은 종전 그대로(엔진 골든이 바이트로 못박는다), store가 있으면 수렴 기록을 꺼내 쓴다
- 판정(flags·reserve·continuity)은 재사용 때 지금 기준으로 다시 세운다 — 판정선만 바뀐 점은 다시 풀지 않는다
"""

import threading

import numpy as np
import pytest

from claw.common.contracts import TrimCase
from claw.plant.dispersion import DispersionSet
from claw.profile import example_profile
from claw.trim import assemble_level, solve_level, trim_batch, trim_level
from claw.trim.store import TrimRecord, TrimStore


@pytest.fixture(scope="module")
def built():
    return example_profile()


@pytest.fixture(scope="module")
def ac(built):
    return built.aircraft()


def _serp(machs, alts, fuel=200.0):
    out = []
    for i, alt in enumerate(alts):
        row = machs if i % 2 == 0 else machs[::-1]
        out += [TrimCase(f"M{m:.2f}_h{alt:.0f}_f{fuel:.0f}", mach=m, alt=alt, fuel=fuel) for m in row]
    return out


CASES = _serp([0.3, 0.4, 0.5], [1000.0, 3000.0])
SLOW = TrimCase("slow", mach=0.12, alt=100.0, fuel=400.0)  # 요구 CL이 α 한계 밖 — 미수렴


def _z(tr):
    return np.array([tr.state.euler()[1], tr.control.elevon[0], tr.control.throttle[0]])


def _same(a, b):
    """두 트림 해가 비트까지 같다 — 상태·조종·판정·여유 전부."""
    assert a.converged == b.converged and a.cost == b.cost
    assert a.flags == b.flags and a.reserve == b.reserve
    assert np.array_equal(a.state.vel_b, b.state.vel_b) and np.array_equal(a.state.q_nb, b.state.q_nb)
    assert np.array_equal(a.control.elevon, b.control.elevon)
    assert np.array_equal(a.control.throttle, b.control.throttle)
    assert a.params_fingerprint == b.params_fingerprint


def test_assemble_of_solve_is_trim_level_bit_identical(ac):
    for case, z0 in [(CASES[0], None), (CASES[1], [0.08, -0.05, 0.4]), (SLOW, None)]:
        x, ok, cost = solve_level(ac, case, z0=z0)
        _same(assemble_level(ac, case, x, ok, cost, fingerprint="fp"), trim_level(ac, case, z0=z0, fingerprint="fp"))
    assert trim_level(ac, CASES[0]).origin == "computed"


def test_batch_without_store_is_unchanged(ac):
    """store=None은 종전 루프 그대로 — 인접 시드를 손으로 따라 푼 것과 같다."""
    got = trim_batch(ac, CASES, fingerprint="fp")
    z_prev = None
    for case, tr in zip(CASES, got):
        ref = trim_level(ac, case, z0=z_prev, fingerprint="fp")
        z = _z(ref)
        if z_prev is not None:
            ref.flags["continuity_ok"] = bool(np.all(np.abs(z - z_prev) < np.array([0.05, 0.05, 0.15])))
        if ref.converged:
            z_prev = z
        _same(tr, ref)
        assert tr.origin == "computed"


def test_second_batch_reuses_all_and_equal(ac, built):
    scope = TrimStore(100).scope(built.trim_fingerprint)
    cold = trim_batch(ac, CASES, fingerprint="fp", store=scope)
    assert [t.origin for t in cold] == ["computed"] * len(CASES)
    _ = [_same(a, b) for a, b in zip(cold, trim_batch(ac, CASES, fingerprint="fp"))]  # 첫 배치 = 저장소 없는 배치
    again = trim_batch(ac, CASES, fingerprint="fp", store=scope)
    assert [t.origin for t in again] == ["reused"] * len(CASES)
    for a, b in zip(cold, again):
        _same(a, b)
    rec = scope.get(CASES[1])
    assert rec.seed == {"kind": "neighbour", "from": CASES[0].name} and scope.get(CASES[0]).seed["kind"] == "cold"


def test_shifted_grid_solves_only_new_coords(ac, built):
    scope = TrimStore(100).scope(built.trim_fingerprint)
    trim_batch(ac, CASES, store=scope)
    shifted = _serp([0.4, 0.5, 0.6], [1000.0, 3000.0])
    out = trim_batch(ac, shifted, store=scope)
    old = {(c.mach, c.alt) for c in CASES}
    assert [t.origin for t in out] == ["reused" if (c.mach, c.alt) in old else "computed" for c in shifted]
    assert sum(t.origin == "computed" for t in out) == 2
    # 재사용 칸 사이의 연속성은 이 배치 안의 직전 점으로 다시 잰다(첫 점은 미판정)
    assert out[0].flags["continuity_ok"] is None and all(t.flags["continuity_ok"] is not None for t in out[1:])


def test_criteria_change_hits_but_flags_recomputed(ac, built):
    """판정선(기준 trim_margin)은 트림 지문 밖 — 같은 키로 재사용하되 판정은 새 기준으로."""
    scope = TrimStore(100).scope(built.trim_fingerprint)
    trim_batch(ac, CASES, store=scope)
    strict = built.aircraft()
    strict.trim_bounds = {**strict.trim_bounds, "sat_frac": 0.05, "alpha_margin": 0.5}
    got = trim_batch(strict, CASES, store=scope)
    ref = trim_batch(strict, CASES)
    assert all(t.origin == "reused" for t in got)
    for a, b in zip(got, ref):
        _same(a, b)
    assert not any(t.flags["saturation_ok"] for t in got)  # 판정선이 실제로 바뀌었다


def test_solver_or_plant_change_misses(ac, built):
    store = TrimStore(100)
    trim_batch(ac, CASES, store=store.scope(built.trim_fingerprint))
    out = trim_batch(ac, CASES, store=store.scope(built.trim_fingerprint + "-other"))
    assert all(t.origin == "computed" for t in out)
    assert len(store) == 2 * len(CASES)


def test_non_converged_is_stored_but_resolved(ac, built):
    scope = TrimStore(100).scope(built.trim_fingerprint)
    first = trim_batch(ac, [SLOW], store=scope)
    assert not first[0].converged
    rec = scope.get(SLOW)
    assert rec is not None and not rec.converged  # 계산 실패도 기록이다
    again = trim_batch(ac, [SLOW], store=scope)
    assert again[0].origin == "computed"


def test_reuse_none_reads_nothing(ac, built):
    scope = TrimStore(100).scope(built.trim_fingerprint)
    trim_batch(ac, CASES, store=scope)
    out = trim_batch(ac, CASES, store=scope, reuse="none")
    assert all(t.origin == "computed" for t in out)
    with pytest.raises(ValueError):
        trim_batch(ac, CASES, store=scope, reuse="always")


def test_dispersed_aircraft_never_touch_store(built):
    """트림 지문은 섭동을 모른다 — 섭동 기체의 해가 명목 키로 들어가면 명목 조회가 섭동 해를 받는다."""
    store = TrimStore(100)
    disp = built.aircraft(dispersion=DispersionSet(mass=0.2))
    with pytest.raises(ValueError, match="섭동"):
        trim_batch(disp, CASES[:1], store=store.scope(built.trim_fingerprint))
    assert len(store) == 0
    trim_batch(disp, CASES[:1])  # 저장소 없이는 종전대로 푼다


def test_ground_cases_not_stored(built):
    store = TrimStore(100)
    scope = store.scope(built.trim_fingerprint)
    g = TrimCase("gnd", mach=0.0, alt=0.0, fuel=200.0, condition="ground")
    assert scope.get(g) is None and scope.put(g, TrimRecord((0.0, 0.0, 0.0), True, 0.0, True)) is False
    assert len(store) == 0


def test_lru_cap_and_disabled():
    store = TrimStore(3)
    s = store.scope("fp")
    rec = TrimRecord((0.1, 0.0, 0.3), True, 0.0, True)
    cs = [TrimCase(f"c{i}", mach=0.3 + 0.1 * i, alt=1000.0, fuel=200.0) for i in range(4)]
    for c in cs[:3]:
        s.put(c, rec)
    s.get(cs[0])  # 최근 사용 — 밀려나지 않는다
    s.put(cs[3], rec)
    assert len(store) == 3 and s.get(cs[1]) is None and s.get(cs[0]) is rec
    off = TrimStore(0)
    assert off.scope("fp").put(cs[0], rec) is False and len(off) == 0
    with pytest.raises(ValueError):
        TrimStore(10).scope("")


def test_key_rounds_coordinates():
    s = TrimStore(10).scope("fp")
    rec = TrimRecord((0.1, 0.0, 0.3), True, 0.0, True)
    s.put(TrimCase("a", mach=0.1 + 0.2, alt=1000.0, fuel=200.0), rec)
    assert s.get(TrimCase("b", mach=0.3, alt=1000.0, fuel=200.0)) is rec  # 0.30000000000000004 = 0.3


def test_first_converged_write_wins_and_replaces_failure():
    s = TrimStore(10).scope("fp")
    c = TrimCase("a", mach=0.3, alt=1000.0, fuel=200.0)
    bad = TrimRecord((0.3, 0.0, 1.0), False, 1.0, False)
    a = TrimRecord((0.1, 0.0, 0.3), True, 0.0, True)
    b = TrimRecord((0.2, 0.0, 0.3), True, 0.0, True)
    assert s.put(c, bad) and s.put(c, a) and not s.put(c, b) and not s.put(c, bad)
    assert s.get(c) is a


def test_concurrent_put_first_write_wins():
    store = TrimStore(10)
    s = store.scope("fp")
    c = TrimCase("a", mach=0.3, alt=1000.0, fuel=200.0)
    recs = [TrimRecord((0.01 * i, 0.0, 0.3), True, 0.0, True) for i in range(16)]
    won = [None] * 16
    gate = threading.Barrier(16)

    def go(i):
        gate.wait()
        won[i] = s.put(c, recs[i])

    ts = [threading.Thread(target=go, args=(i,)) for i in range(16)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert won.count(True) == 1
    assert s.get(c) is recs[won.index(True)] and len(store) == 1
