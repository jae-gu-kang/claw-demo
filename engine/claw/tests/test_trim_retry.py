"""계산 실패 재시도 (05 §11.3 · 이관 7단계) — 한계 안의 미수렴을 인접 해·기본값 시드로 다시 푼다.

- retry=None은 종전 그대로(엔진 골든·자동 설계) — 재시도 기록도 없다
- 재시도 대상은 새로 푼 해 중 어느 한계에도 안 붙은 미수렴(interior_failure)뿐 — 수렴·한계 해·재사용 해는 손대지 않는다
- 조건 상태의 「계산 실패」와 배치 재시도의 대상은 같은 술어다(trim.interior_failure) — 둘이 갈리면 재시도한 점과 보고되는
  계산 실패가 달라진다
"""

import dataclasses
import importlib
import time

import numpy as np
import pytest

import claw.design  # noqa: F401 — opspace ↔ design 순환 import 순서
from claw.common.contracts import TrimCase
from claw.opspace import CALC_FAILED, INFEASIBLE, ModelRange, trim_assessment
from claw.opspace import states as states_mod
from claw.profile import build_profile
from claw.profile.document import load_shipped_example
from claw.trim import (
    DEFAULT_RETRY, RetryPolicy, TrimStore, alpha_bound, assemble_level, interior_failure, physical_limits, retry_level,
    retry_result, retry_seeds, trim_batch,
)

# claw.trim.trim은 패키지 속성으로는 함수 trim이 가린다 — 모듈을 직접 잡는다
trim_mod = importlib.import_module("claw.trim.trim")
WIDE_MODEL = ModelRange(mach=(0.0, 0.9), fuel=(0.0, 50.0))
# 1단계 실측의 재현 — 출하 예제에서 요구영역을 M1.0까지 넓힌 100 m 행(25 kg). M0.3부터는 최대 추력으로도 수평을 못
# 지키는데, 종전 배치는 M0.6 이상에서 앞 수렴점(M0.2)의 스로틀에 멈춘 채 「계산 실패」를 냈다
ROW = [TrimCase(f"M{m:.1f}_h100_f25", mach=m, alt=100.0, fuel=25.0) for m in np.round(np.arange(0.1, 0.95, 0.1), 1)]


@pytest.fixture(scope="module")
def built():
    return build_profile(load_shipped_example())


@pytest.fixture(scope="module")
def ac(built):
    return built.aircraft()


@pytest.fixture(scope="module")
def plain(ac):
    return trim_batch(ac, ROW)


@pytest.fixture(scope="module")
def retried(ac):
    t0 = time.perf_counter()
    out = trim_batch(ac, ROW, retry=DEFAULT_RETRY)
    return out, time.perf_counter() - t0


def _by(results, mach):
    return next(t for t in results if t.case.mach == pytest.approx(mach))


def _bits(a, b):
    assert a.converged == b.converged and a.cost == b.cost and a.flags == b.flags and a.reserve == b.reserve
    assert np.array_equal(a.state.q_nb, b.state.q_nb) and np.array_equal(a.state.vel_b, b.state.vel_b)
    assert np.array_equal(a.control.elevon, b.control.elevon)
    assert np.array_equal(a.control.throttle, b.control.throttle)


# ── 실측 재현 ──────────────────────────────────────────────────────────────
def test_repro_without_retry_is_stuck_at_last_converged_throttle(plain, built):
    tb = built.trim_bounds
    thr_last = float(_by(plain, 0.2).control.throttle[0])
    for m in (0.6, 0.7):
        tr = _by(plain, m)
        assert interior_failure(tr, tb)
        assert float(tr.control.throttle[0]) == pytest.approx(thr_last, abs=1e-9)  # 시드에서 못 움직였다
        assert tr.cost > 1e3 and tr.retry is None
        a = trim_assessment(tr, built, WIDE_MODEL)
        assert (a["state"], a["reasons"], a["retry"]) == (CALC_FAILED, ["not_converged"], None)


def test_repro_with_retry_reaches_the_thrust_limit_and_evidence(retried, built):
    out, dt = retried
    tb = built.trim_bounds
    assert not any(interior_failure(t, tb) for t in out)
    for m in (0.6, 0.7):
        tr = _by(out, m)
        assert tr.retry["result"] == "limit" and tr.retry["seeds"][0]["kind"] == "last"
        # 한계 하나에 닿은 시도에서 멈춘다 — 그 뒤 상태는 고정한 한계만의 함수다(한계 근거가 따로 다시 푼다)
        assert tr.retry["stop"] == "limit" and tr.retry["attempts"] == tr.retry["chosen"] + 1
        assert physical_limits(tr, tb) == ["throttle_high"]
        a = trim_assessment(tr, built, WIDE_MODEL)
        assert a["state"] == INFEASIBLE and a["reasons"] == ["thrust_deficit", "throttle_high"]
        assert a["retry"] is tr.retry
    # 「last」는 직전 케이스의 해 — M0.6은 M0.5의 한계 해(수렴 안 함)에서 출발한다
    assert _by(out, 0.6).retry["seeds"][0]["from"] == "M0.5_h100_f25"
    assert dt < 5.0  # 느슨한 상한 — 비용의 실측은 풀이 수(test_early_stop_spends_one_solve_per_stuck_point)


def test_retry_leaves_converged_and_limit_points_alone(plain, retried, built):
    out, _dt = retried
    tb = built.trim_bounds
    for a, b in zip(plain, out):
        if not interior_failure(a, tb):
            _bits(a, b)
            assert b.retry is None


def test_retry_none_is_byte_identical_and_unrecorded(ac, plain):
    again = trim_batch(ac, ROW, retry=None)
    for a, b in zip(plain, again):
        _bits(a, b)
        assert b.retry is None and "retry" not in vars(b)


def test_retry_is_deterministic(ac, retried):
    out, _dt = retried
    again = trim_batch(ac, ROW, retry=DEFAULT_RETRY)
    for a, b in zip(out, again):
        _bits(a, b)
        assert a.retry == b.retry


def test_continuity_and_next_seed_follow_chosen(retried):
    out, _dt = retried
    # 고른 해도 미수렴이면 다음 케이스의 이어 풀기 시드(z_prev)는 옮기지 않는다 — 연속성은 마지막 수렴 해와 잰다
    m8 = _by(out, 0.8)
    assert m8.retry["seeds"][0] == {"kind": "last", "from": "M0.7_h100_f25",
                                    "z0": [float(v) for v in trim_mod._z_of(_by(out, 0.7))]}


# ── 시드 후보 ──────────────────────────────────────────────────────────────
def test_seed_order_dedupe_and_nearest():
    case = TrimCase("x", mach=0.5, alt=1000.0, fuel=25.0)
    a = TrimCase("a", mach=0.3, alt=1000.0, fuel=25.0)  # 거리 2
    b = TrimCase("b", mach=0.5, alt=3000.0, fuel=25.0)  # 거리 2 — 동률은 앞의 것
    c = TrimCase("c", mach=0.1, alt=1000.0, fuel=25.0)
    za, zb, zc = np.array([0.1, 0.0, 0.4]), np.array([0.11, 0.0, 0.45]), np.array([0.2, 0.0, 0.3])
    seeds = retry_seeds(case, za, ("prev", zc), [(c, zc), (a, za), (b, zb)], DEFAULT_RETRY)
    # last(zc) · nearest(a = 처음 시드와 같아 빠지고 b가 아니라 — 동률에서 앞의 a가 뽑혀 중복 제거) · cold · sweep 넷
    assert [s["kind"] for s in seeds] == ["last", "cold", "sweep", "sweep", "sweep", "sweep"]
    assert seeds[0] == {"kind": "last", "from": "prev", "z0": [0.2, 0.0, 0.3]}
    seeds = retry_seeds(case, None, None, [(c, zc), (b, zb), (a, za)], DEFAULT_RETRY)
    # 처음 시드가 기본값이면 cold는 중복이다
    assert [(s["kind"], s["from"]) for s in seeds[:2]] == [("nearest", "b"), ("sweep", None)]
    assert len(seeds) == 1 + len(DEFAULT_RETRY.sweep)


# ── 예산·고르기 ────────────────────────────────────────────────────────────
def _stalled(monkeypatch, z_out):
    """풀이기가 늘 같은 한계 안 점에 멈추는 척 — 재시도가 전부 실패하는 자리. 호출 수를 센다."""
    calls = []

    def fake(aircraft, case, z0=None):
        calls.append(None if z0 is None else [float(v) for v in z0])
        return np.array(z_out, dtype=float), True, 1e3 + len(calls)  # 뒤로 갈수록 비용이 크다

    monkeypatch.setattr(trim_mod, "solve_level", fake)
    return calls


def test_budget_counts_solves(monkeypatch, ac, built):
    calls = _stalled(monkeypatch, [0.05, 0.0, 0.5])
    cases = ROW[5:7]
    out = trim_batch(ac, cases, retry=RetryPolicy(max_attempts=2))
    assert len(calls) == len(cases) * (1 + 2)
    assert all(t.retry["attempts"] == 2 and len(t.retry["outcomes"]) == 2 for t in out)
    # 전부 한계 안 미수렴 — 비용이 가장 낮은 처음 해를 그대로 둔다
    assert all(t.retry["chosen"] is None and t.retry["result"] == "failed" and t.retry["stop"] == "exhausted"
               for t in out)
    a = trim_assessment(out[0], built, WIDE_MODEL)
    assert a["state"] == CALC_FAILED and a["reasons"] == ["not_converged", "retry_exhausted"]
    calls.clear()
    out = trim_batch(ac, cases, retry=RetryPolicy(max_attempts=0))
    assert len(calls) == len(cases)
    # 한 번도 다시 풀지 않았으면 「다시 풀어도 실패」라 말하지 않는다 — 기록은 남아도(시도 0) 사유는 종전 그대로
    assert out[0].retry["attempts"] == 0
    a = trim_assessment(out[0], built, WIDE_MODEL)
    assert a["state"] == CALC_FAILED and a["reasons"] == ["not_converged"]


def test_first_converged_attempt_stops_and_is_chosen(monkeypatch, ac):
    real = trim_mod.solve_level
    calls = []

    def fake(aircraft, case, z0=None):
        calls.append(z0)
        if len(calls) == 1:
            return np.array([0.05, 0.0, 0.5]), True, 1e3  # 처음 풀이만 멈춘다
        return real(aircraft, case, z0=z0)

    monkeypatch.setattr(trim_mod, "solve_level", fake)
    case = TrimCase("M0.2_h1000_f25", mach=0.2, alt=1000.0, fuel=25.0)
    out = trim_batch(ac, [case], retry=DEFAULT_RETRY)
    r = out[0].retry
    assert out[0].converged and r["result"] == "converged" and r["chosen"] == r["attempts"] - 1
    assert r["stop"] == "converged"
    assert r["outcomes"][-1]["converged"] and len(calls) == 1 + r["attempts"]


def test_retry_level_prefers_limit_over_interior(monkeypatch, ac, built):
    case = ROW[6]
    x0 = np.array([0.05, 0.0, 0.5])
    first = assemble_level(ac, case, x0, True, 1e3)
    outs = iter([(np.array([0.05, 0.0, 0.6]), True, 5e2), (np.array([0.05, 0.0, 1.0]), False, 9e2)])
    monkeypatch.setattr(trim_mod, "solve_level", lambda *a, **k: next(outs))
    seeds = [{"kind": "cold", "from": None, "z0": [0.0, 0.0, 0.1]}, {"kind": "sweep", "from": None, "z0": [0.0, 0.0, 0.9]}]
    tr, rec = retry_level(ac, case, first, seeds, RetryPolicy(max_attempts=5))
    # 비용이 더 낮은 한계 안 해보다 한계에 붙은 해 — 조건 상태가 거기서 근거를 잰다
    assert rec["chosen"] == 1 and rec["result"] == "limit" and tr.retry is rec and rec["stop"] == "limit"
    assert [o["result"] for o in rec["outcomes"]] == ["failed", "limit"]
    assert float(tr.control.throttle[0]) == 1.0


def _scripted(monkeypatch, outs):
    """풀이기가 정해 둔 해를 차례로 낸다 — 몇 번 불렸나를 센다."""
    it = iter(outs)
    calls = []

    def fake(*a, **k):
        calls.append(k.get("z0"))
        return next(it)

    monkeypatch.setattr(trim_mod, "solve_level", fake)
    return calls


def _seeds(n):
    return [{"kind": "sweep", "from": None, "z0": [0.01 * i, 0.0, 0.5]} for i in range(n)]


def test_result_labels_split_limit_bound_and_multi(ac, built):
    tb = built.trim_bounds
    case = ROW[6]
    a_lo, a_hi = tb["alpha"]
    de_lo, de_hi = tb["de"]
    lab = lambda z, ok=False: retry_result(assemble_level(ac, case, np.array(z), ok, 1e3), tb)  # noqa: E731
    assert lab([0.05, 0.0, 0.5]) == "failed"
    assert lab([0.05, 0.0, 1.0]) == "limit"
    assert lab([0.05, de_hi, 0.5]) == "limit"
    # 한계 둘 — 한 채널을 고정한 근거가 서지 않는다
    assert lab([0.05, de_hi, 1.0]) == "multi_limit"
    # 받음각 탐색 경계는 해석 설정이지 물리 한계가 아니다
    tr = assemble_level(ac, case, np.array([a_hi, 0.0, 0.5]), False, 1e3)
    assert alpha_bound(tr, tb) == "upper" and not physical_limits(tr, tb)
    assert retry_result(tr, tb) == "alpha_bound"
    assert lab([a_lo, 0.0, 0.5]) == "alpha_bound"


def test_limit_beats_alpha_bound_and_multi(monkeypatch, ac, built):
    tb = built.trim_bounds
    case = ROW[6]
    a_hi = tb["alpha"][1]
    de_hi = tb["de"][1]
    first = assemble_level(ac, case, np.array([0.05, 0.0, 0.5]), True, 1e3)
    # 탐색 경계(비용 최저) · 한계 둘 · 한계 하나 — 한계 하나가 이기고 거기서 멈춘다(뒤의 시드는 풀지 않는다)
    calls = _scripted(monkeypatch, [(np.array([a_hi, 0.0, 0.5]), False, 1e1), (np.array([0.05, de_hi, 1.0]), False, 2e1),
                                    (np.array([0.05, 0.0, 1.0]), False, 9e2), (np.array([0.05, 0.0, 0.6]), True, 0.0)])
    tr, rec = retry_level(ac, case, first, _seeds(4), RetryPolicy(max_attempts=4))
    assert [o["result"] for o in rec["outcomes"]] == ["alpha_bound", "multi_limit", "limit"]
    assert rec["chosen"] == 2 and rec["result"] == "limit" and rec["stop"] == "limit" and len(calls) == 3
    # 한계 하나가 없으면 탐색 경계·한계 둘 가운데 비용이 낮은 쪽 — 그 라벨이 결과다
    _scripted(monkeypatch, [(np.array([0.05, de_hi, 1.0]), False, 2e1), (np.array([a_hi, 0.0, 0.5]), False, 1e1)])
    tr, rec = retry_level(ac, case, first, _seeds(2), RetryPolicy(max_attempts=2))
    assert rec["chosen"] == 1 and rec["result"] == "alpha_bound" and rec["stop"] == "exhausted"


def test_earlier_converged_wins_but_later_seed_is_not_tried_after_a_limit(monkeypatch, ac):
    case = ROW[1]
    zc, okc, cc = trim_mod.solve_level(ac, case)  # 실제 수렴 해(M0.2)
    stuck = assemble_level(ac, case, np.array([0.05, 0.0, 0.5]), True, 1e3)
    limit = (np.array([0.05, 0.0, 1.0]), False, 9e2)
    # 수렴이 먼저면 수렴에서 멈춘다(종전 의미 그대로)
    calls = _scripted(monkeypatch, [(zc, okc, cc), limit])
    tr, rec = retry_level(ac, case, stuck, _seeds(2), RetryPolicy(max_attempts=2))
    assert tr.converged and rec["result"] == "converged" and rec["stop"] == "converged" and len(calls) == 1
    # 한계가 먼저면 거기서 멈춘다 — 뒤의 시드가 수렴했을 수도 있다(풀이 수와 맞바꾼 절충, 05 §11.3)
    calls = _scripted(monkeypatch, [limit, (zc, okc, cc)])
    tr, rec = retry_level(ac, case, stuck, _seeds(2), RetryPolicy(max_attempts=2))
    assert not tr.converged and rec["result"] == "limit" and rec["stop"] == "limit" and len(calls) == 1


def test_next_case_is_seeded_from_the_retry_converged_solution(monkeypatch, ac):
    """처음 풀이가 멈췄다가 재시도에서 수렴한 해 — 다음 케이스의 이어 풀기 시드(z_prev)와 연속성 기준이 그 해다."""
    real = trim_mod.solve_level
    cases = [TrimCase(f"M{m}_h1000_f25", mach=m, alt=1000.0, fuel=25.0) for m in (0.2, 0.22, 0.24)]
    calls = []

    def fake(aircraft, case, z0=None):
        calls.append((case.name, None if z0 is None else [float(v) for v in z0]))
        if case.name == cases[1].name and len([c for c in calls if c[0] == case.name]) == 1:
            return np.array([0.15, 0.08, 0.1]), True, 1e3  # 둘째 케이스의 처음 풀이만 한계 안에 멈춘다(이웃과 먼 점)
        return real(aircraft, case, z0=z0)

    monkeypatch.setattr(trim_mod, "solve_level", fake)
    out = trim_batch(ac, cases, retry=DEFAULT_RETRY)
    assert out[1].converged and out[1].retry["result"] == "converged"
    z1 = [float(v) for v in trim_mod._z_of(out[1])]
    third = [z0 for name, z0 in calls if name == cases[2].name]
    assert third == [pytest.approx(z1, abs=1e-12)]  # 셋째는 재시도 해에서 한 번에 이어 푼다
    assert out[2].retry is None and out[2].converged
    assert out[2].flags["continuity_ok"] is True
    # 연속성은 재시도로 고른 해와 잰다 — 멈춘 처음 해와 재면 둘 다 거짓 경고가 난다
    assert out[1].flags["continuity_ok"] is True


def test_early_stop_spends_one_solve_per_stuck_point(monkeypatch, ac):
    """실측 재현 행의 비용 — 조기 종료 전에는 멈춘 점마다 시도 상한(6)을 다 썼다(한계 해는 수렴하지 않는다)."""
    calls = []
    real = trim_mod.solve_level

    def count(*a, **k):
        calls.append(a[1].name)
        return real(*a, **k)

    monkeypatch.setattr(trim_mod, "solve_level", count)
    out = trim_batch(ac, ROW, retry=DEFAULT_RETRY)
    retried = [t for t in out if t.retry is not None]
    assert retried and all(t.retry["attempts"] == 1 and t.retry["stop"] == "limit" for t in retried)
    assert len(calls) == len(ROW) + len(retried)


# ── 진행 콜백 ──────────────────────────────────────────────────────────────
def test_on_progress_once_per_case_after_retry(ac, retried):
    out, _dt = retried
    seen = []
    trim_batch(ac, ROW, retry=DEFAULT_RETRY, on_progress=lambda d, n, tr: seen.append((d, n, tr.retry)))
    assert [d for d, _n, _r in seen] == list(range(1, len(ROW) + 1))
    assert [r for _d, _n, r in seen] == [t.retry for t in out]


# ── 저장소 ─────────────────────────────────────────────────────────────────
def test_store_keeps_chosen_with_its_seed_and_record(ac, built, retried):
    out, _dt = retried
    scope = TrimStore(100).scope(built.trim_fingerprint)
    got = trim_batch(ac, ROW, store=scope, retry=DEFAULT_RETRY)
    for a, b in zip(out, got):
        _bits(a, b)
    tr = _by(got, 0.6)
    rec = scope.get(tr.case)
    chosen = tr.retry["seeds"][tr.retry["chosen"]]
    assert rec.retry == tr.retry and rec.seed == {"kind": chosen["kind"], "from": chosen["from"]}
    assert rec.z == pytest.approx(tuple(trim_mod._z_of(tr)), abs=1e-12) and not rec.converged
    assert scope.get(ROW[1]).retry is None  # 수렴 점은 기록이 없다


def test_store_reused_converged_never_retried_failed_resolved(monkeypatch, ac, built):
    scope = TrimStore(100).scope(built.trim_fingerprint)
    trim_batch(ac, ROW, store=scope)  # 재시도 없이 — 계산 실패가 저장된다
    assert not scope.get(ROW[5]).converged and scope.get(ROW[5]).retry is None
    calls = []
    real = trim_mod.solve_level
    monkeypatch.setattr(trim_mod, "solve_level", lambda *a, **k: calls.append(a[1].name) or real(*a, **k))
    got = trim_batch(ac, ROW, store=scope, retry=DEFAULT_RETRY)
    assert [t.origin for t in got[:2]] == ["reused", "reused"] and all(t.retry is None for t in got[:2])
    assert ROW[0].name not in calls and ROW[1].name not in calls
    assert _by(got, 0.6).retry["result"] == "limit"
    # 저장된 계산 실패는 다시 풀고 재시도한 해로 대체된다(수렴 기록이 아니라 먼저 쓴 기록이 이기지 않는다)
    assert scope.get(ROW[5]).retry == _by(got, 0.6).retry


# ── 술어 일치 ───────────────────────────────────────────────────────────────
def test_states_uses_the_trim_predicates(plain, retried, built):
    assert states_mod.physical_limits is physical_limits
    assert states_mod.alpha_bound is alpha_bound
    tb = built.trim_bounds
    for tr in [*plain, *retried[0]]:
        a = trim_assessment(tr, built, WIDE_MODEL)
        interior = a["state"] == CALC_FAILED and a["reasons"][:1] == ["not_converged"]
        assert interior == interior_failure(tr, tb)


def test_replaced_result_drops_the_record(retried):
    # dataclasses.replace는 인스턴스 속성을 옮기지 않는다 — 필드가 아닌 기록이라 기본값 None(주의 표시용 회귀)
    tr = _by(retried[0], 0.6)
    assert dataclasses.replace(tr).retry is None


def test_non_level_cases_are_never_retried(ac):
    # 재시도는 수평비행 조건 상태 「계산 실패」의 처방이다 — 지상 케이스는 조건 상태가 없어(서버 state None) 다시 풀 뜻이 없다
    ground = TrimCase("g", mach=0.0, alt=0.0, fuel=25.0, condition="ground")
    a, b = trim_batch(ac, [ground]), trim_batch(ac, [ground], retry=DEFAULT_RETRY)
    _bits(a[0], b[0])
    assert b[0].retry is None
