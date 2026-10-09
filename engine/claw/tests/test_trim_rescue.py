"""한계 안쪽 트림 재풀이 (05 §11.3 · 이관 7b) — trim_inside_limit를 그 근거 해 시드로 다시 푼다.

출하 예제·EO/IR형 어디서도 이 유형(물리 한계 하나에 멈춘 미수렴인데 한계 고정 평형 근거가 한계 안쪽 트림을 가리킴)은
나오지 않았다 — 매끄러운 추진 모델이라 SLSQP가 한계에서 빠져나온다. 그래서 수렴한 M0.18 트림을 스로틀 1.0·미수렴으로
꾸미고(test_opspace.py의 픽스처), **실제 근거 풀이(_limit_evidence)와 실제 솔버**가 진짜 M0.18 트림을 되찾는지 본다.
「그래도 실패」 가지는 풀이기를 한계에 멈추게 스크립트한다(test_trim_retry.py의 _stalled 패턴).
"""

import dataclasses
import importlib

import numpy as np
import pytest

import claw.design  # noqa: F401 — opspace ↔ design 순환 import 순서
from claw.common.contracts import TrimCase
from claw.opspace import CALC_FAILED, COMPUTABLE, INFEASIBLE, ModelRange, trim_assessment
from claw.opspace import states as states_mod
from claw.opspace.rescue import EVIDENCE_KIND, evidence_seeds, rescue_inside_limit
from claw.profile import build_profile
from claw.profile.document import load_shipped_example
from claw.trim import DEFAULT_RETRY, RetryPolicy, TrimRecord, TrimStore, trim_batch, trim_level

trim_mod = importlib.import_module("claw.trim.trim")
WIDE_MODEL = ModelRange(mach=(0.0, 0.9), fuel=(0.0, 50.0))
CASE = TrimCase(name="M0.18_h1000_f25", mach=0.18, alt=1000.0, fuel=25.0)


@pytest.fixture(scope="module")
def example():
    return build_profile(load_shipped_example())


@pytest.fixture(scope="module")
def real_trim(example):
    tr = trim_level(example.aircraft(), CASE)
    assert tr.converged
    return tr


def _z(tr):
    return np.array([tr.state.euler()[1], tr.control.elevon[0], tr.control.throttle[0]])


def _pinned(tr):
    """수렴한 트림을 스로틀 100 %·미수렴으로 꾸민다 — 풀이기가 한계에 멈춘 척(test_opspace.py와 같은 픽스처)."""
    return dataclasses.replace(tr, converged=False, control=dataclasses.replace(tr.control, throttle=np.array([1.0, 1.0])))


def _count_solves(monkeypatch):
    real = trim_mod.solve_level
    calls = []

    def counted(aircraft, case, z0=None):
        calls.append(None if z0 is None else [float(v) for v in z0])
        return real(aircraft, case, z0=z0)

    monkeypatch.setattr(trim_mod, "solve_level", counted)
    return calls


def _stalled(monkeypatch, z_out):
    """풀이기가 늘 같은 한계 점에 멈추는 척 — 근거 시드로도 못 빠져나오는 자리. 호출 수를 센다."""
    calls = []

    def fake(aircraft, case, z0=None):
        calls.append(None if z0 is None else [float(v) for v in z0])
        return np.array(z_out, dtype=float), True, 1e3 + len(calls)

    monkeypatch.setattr(trim_mod, "solve_level", fake)
    return calls


def _count_evidence(monkeypatch):
    real = states_mod._limit_evidence
    calls = []

    def counted(*a, **k):
        calls.append(a[2])
        return real(*a, **k)

    monkeypatch.setattr(states_mod, "_limit_evidence", counted)
    return calls


# ── 시드 구성 ───────────────────────────────────────────────────────────────
def test_seeds_shift_by_need_first_then_raw_with_clip_and_dedupe(example):
    tb = example.trim_bounds
    ev = {"channel": "throttle_high", "solutions": [
        {"alpha": 0.05, "de": -0.04, "throttle": 1.0, "need": -0.4, "short": False},
        {"alpha": 0.06, "de": -0.03, "throttle": 1.0, "need": 0.3, "short": True},  # 부족한 해 — 시드가 아니다
        {"alpha": 0.07, "de": -0.02, "throttle": 1.0, "need": -1.7, "short": False},  # 안쪽 한계(0) 밖까지 — 클립
        {"alpha": 0.05, "de": -0.04, "throttle": 1.0, "need": -0.4, "short": False},  # 중복
    ]}
    seeds = evidence_seeds(ev, tb)
    assert [s["z0"] for s in seeds] == [[0.05, -0.04, 0.6], [0.07, -0.02, 0.0], [0.05, -0.04, 1.0], [0.07, -0.02, 1.0]]
    assert all(s["kind"] == EVIDENCE_KIND and s["from"] == "throttle_high" for s in seeds)
    # 멈춘 해 그 자체는 시드가 아니다
    assert [s["z0"] for s in evidence_seeds(ev, tb, skip=[0.05, -0.04, 1.0])] == [
        [0.05, -0.04, 0.6], [0.07, -0.02, 0.0], [0.07, -0.02, 1.0]]
    # 엘레본 채널은 δe를 옮기고 엘레본 한계로 자른다
    de_lo, de_hi = tb["de"]
    ev = {"channel": "de_high", "solutions": [{"alpha": 0.05, "de": de_hi, "throttle": 0.4, "need": -5.0, "short": False}]}
    assert evidence_seeds(ev, tb)[0]["z0"] == [0.05, de_lo, 0.4]


# ── A: 꾸민 한계 정체 → 실제 근거 + 실제 솔버가 진짜 트림을 되찾는다 ─────────────────
def test_pinned_throttle_is_rescued_by_the_real_evidence_and_solver(example, real_trim, monkeypatch):
    stalled = _pinned(real_trim)
    cache = {}
    before = trim_assessment(stalled, example, WIDE_MODEL, cache=cache)
    assert before["state"] == CALC_FAILED
    assert before["reasons"] == ["throttle_high", "not_converged", "trim_inside_limit"]
    scope = TrimStore().scope("fp")
    scope.put(CASE, TrimRecord(z=tuple(float(v) for v in _z(stalled)), success=True, cost=float(stalled.cost),
                               converged=False))
    solves = _count_solves(monkeypatch)
    out = rescue_inside_limit([stalled], example, WIDE_MODEL, cache=cache, store=scope)
    tr = out[0]
    assert tr.converged and len(solves) == 1
    # 첫 시드는 근거 해에서 스로틀을 need만큼 안쪽으로 옮긴 점 — 진짜 트림 스로틀 근처다
    first = [s for s in before["evidence"]["solutions"] if s["short"] is False][0]
    assert solves[0][2] == pytest.approx(1.0 + first["need"])
    assert abs(solves[0][2] - float(real_trim.control.throttle[0])) < 0.05
    np.testing.assert_allclose(_z(tr), _z(real_trim), atol=1e-5)
    rec = tr.retry
    assert rec["seeds"][rec["chosen"]]["kind"] == EVIDENCE_KIND and rec["seeds"][rec["chosen"]]["from"] == "throttle_high"
    assert rec["result"] == "converged" and rec["stop"] == "converged"
    assert rec["evidence_pass"] == {"channel": "throttle_high", "attempts": 1}
    a = trim_assessment(tr, example, WIDE_MODEL, cache=cache)
    assert a["state"] == COMPUTABLE and a["reasons"] == []
    # 저장소의 미수렴 기록을 수렴 기록이 대체한다(먼저 쓴 수렴 기록이 이긴다 — 미수렴은 이기지 못한다)
    stored = scope.get(CASE)
    assert stored.converged and stored.seed == {"kind": EVIDENCE_KIND, "from": "throttle_high"}
    np.testing.assert_allclose(stored.z, _z(real_trim), atol=1e-5)
    assert stored.retry is rec


# ── B: 그래도 실패 → 실패 상태와 근거 보존 + retry_exhausted ─────────────────────
def test_still_stalled_keeps_the_failure_and_its_evidence(example, real_trim, monkeypatch):
    stalled = _pinned(real_trim)
    cache = {}
    before = trim_assessment(stalled, example, WIDE_MODEL, cache=cache)
    inside = [s for s in before["evidence"]["solutions"] if s["short"] is False]
    assert inside
    calls = _stalled(monkeypatch, [*_z(real_trim)[:2], 1.0])
    out = rescue_inside_limit([stalled], example, WIDE_MODEL, cache=cache)
    tr = out[0]
    assert tr is stalled and not tr.converged
    n_seeds = len(evidence_seeds(before["evidence"], example.trim_bounds, skip=_z(stalled)))
    # 한계에 다시 닿은 첫 시도에서 멈춘다(retry_level 규칙) — 풀이 수 ≤ 시드 수
    assert len(calls) == 1 <= n_seeds
    assert tr.retry["evidence_pass"] == {"channel": "throttle_high", "attempts": 1}
    assert tr.retry["chosen"] is None and tr.retry["result"] == "limit"
    a = trim_assessment(tr, example, WIDE_MODEL, cache=cache)
    assert a["state"] == CALC_FAILED
    assert a["reasons"] == ["throttle_high", "not_converged", "trim_inside_limit", "retry_exhausted"]
    assert a["evidence"] == before["evidence"]
    assert [s for s in a["evidence"]["solutions"] if s["short"] is False] == inside
    assert a["retry"] is tr.retry


# ── C: 근거 메모 — 한 조건·한 채널의 근거는 한 번만 푼다 ──────────────────────────
def test_evidence_is_solved_once_across_assessments_and_the_pass(example, real_trim, monkeypatch):
    stalled = _pinned(real_trim)
    ev_calls = _count_evidence(monkeypatch)
    _stalled(monkeypatch, [*_z(real_trim)[:2], 1.0])
    cache = {}
    a1 = trim_assessment(stalled, example, WIDE_MODEL, cache=cache)
    out = rescue_inside_limit([stalled], example, WIDE_MODEL, cache=cache)
    a2 = trim_assessment(out[0], example, WIDE_MODEL, cache=cache)
    assert ev_calls == ["throttle_high"]
    assert a2["evidence"] == a1["evidence"] and a2["reasons"][-1] == "retry_exhausted"
    assert "retry_exhausted" not in a1["reasons"]


# ── 대상 밖은 손대지 않는다 ───────────────────────────────────────────────────
def test_thrust_deficit_and_converged_points_are_untouched(example, real_trim, monkeypatch):
    deficit = trim_level(example.aircraft(), TrimCase(name="M0.5_h100_f25", mach=0.5, alt=100.0, fuel=25.0))
    assert not deficit.converged
    cache = {}
    assert trim_assessment(deficit, example, WIDE_MODEL, cache=cache)["state"] == INFEASIBLE
    solves = _count_solves(monkeypatch)
    out = rescue_inside_limit([real_trim, deficit], example, WIDE_MODEL, cache=cache)
    assert out[0] is real_trim and out[1] is deficit and solves == []
    assert real_trim.retry is None and deficit.retry is None


# ── 배치 재시도 기록이 이미 있으면 합친다 ─────────────────────────────────────────
def test_existing_retry_record_is_merged(example, real_trim, monkeypatch):
    stalled = _pinned(real_trim)
    old_seeds = [{"kind": "last", "from": "prev", "z0": [0.05, 0.0, 0.9]}, {"kind": "cold", "from": None, "z0": [0.0, 0.0, 0.5]}]
    stalled.retry = {"attempts": 2, "seeds": old_seeds,
                     "outcomes": [{"converged": False, "result": "failed", "cost": 5.0},
                                  {"converged": False, "result": "limit", "cost": 4.0}],
                     "chosen": 1, "result": "limit", "stop": "limit"}
    out = rescue_inside_limit([stalled], example, WIDE_MODEL, cache={})
    rec = out[0].retry
    assert out[0].converged
    assert rec["attempts"] == 3 and rec["seeds"][:2] == old_seeds and rec["seeds"][2]["kind"] == EVIDENCE_KIND
    assert len(rec["outcomes"]) == 3 and rec["outcomes"][2]["converged"]
    assert rec["chosen"] == 2 and rec["result"] == "converged" and rec["stop"] == "converged"
    assert rec["evidence_pass"] == {"channel": "throttle_high", "attempts": 1}


def test_continuity_is_measured_against_the_previous_converged_point(example, real_trim):
    prev = trim_level(example.aircraft(), TrimCase(name="M0.17_h1000_f25", mach=0.17, alt=1000.0, fuel=25.0))
    out = rescue_inside_limit([prev, _pinned(real_trim)], example, WIDE_MODEL, cache={})
    assert out[1].converged and out[1].flags["continuity_ok"] is True


def test_zero_budget_does_not_mark_the_point(example, real_trim, monkeypatch):
    stalled = _pinned(real_trim)
    solves = _count_solves(monkeypatch)
    out = rescue_inside_limit([stalled], example, WIDE_MODEL, cache={}, policy=RetryPolicy(max_attempts=0))
    assert out[0] is stalled and stalled.retry is None and solves == []


def test_batch_without_store_or_retry_is_unchanged(example):
    # 엔진 골든 경로 — trim_batch(store=None, retry=None)는 이 패스와 무관하다(기록 없음)
    out = trim_batch(example.aircraft(), [CASE], retry=None)
    assert out[0].retry is None and DEFAULT_RETRY.max_attempts == 6
