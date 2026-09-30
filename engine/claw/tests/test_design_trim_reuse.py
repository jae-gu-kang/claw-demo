"""자동 설계의 트림 저장소 재사용 (05 §11.10 사용자 후속 ③) — 같은 모델·조건·설정의 트림은 재계산 0회, 새 좌표만 계산.

- store=None은 종전 그대로다(엔진·설계 골든이 지킨다) — 저장소를 처음 받는 실행도 빈 저장소면 비트 동일이어야 한다
- 재사용 집계는 report()["trim_reuse"]({"reused","computed","enabled"})가 말하고, 수는 왕복(to_dict/from_dict)에
  실려 재개가 이어 센다 — 서버 reuse_counts와 같은 칸 이름
"""

import copy
import functools

import pytest

from claw.common.contracts import TrimCase
from claw.design import AutoDesignConfig, DesignSession, LinearModelSet
from claw.design.grid import coarse_grid, region_grid
from claw.design.refine import refine_trim_points
from claw.fcl.demo import demo_design_gains
from claw.opspace.verdict import VerdictContext
from claw.plant import (
    make_demo_aircraft,
    make_demo_db_ranges,
    make_demo_stall_table,
    make_demo_structural_limits,
)
from claw.profile import example_profile
from claw.trim import TrimStore, trim_batch


@pytest.fixture(scope="module")
def env():
    return (
        make_demo_aircraft(),
        make_demo_stall_table(),
        make_demo_structural_limits(),
        make_demo_db_ranges(),
        demo_design_gains(),
    )


@functools.lru_cache(maxsize=None)
def _vctx():
    return VerdictContext.from_profile(example_profile())


def _small(**over):
    base = dict(n_mach=3, alts=(1000.0,), fuels=(200.0,), budget_points=24,
                budget_iters=2, mode="auto")
    base.update(over)
    return AutoDesignConfig(**base)


def _scope(fp="trim-fp"):
    return TrimStore(1000).scope(fp)


def _origins(trims) -> dict:
    out = {"reused": 0, "computed": 0}
    for tr in trims.values():
        out["reused" if getattr(tr, "origin", "computed") == "reused" else "computed"] += 1
    return out


def _strip(d: dict) -> dict:
    """재사용 수·벽시계를 뺀 세션 직렬화본 — 비트 동일 비교용 (실행 이력·시간은 결과가 아니다)."""
    d = copy.deepcopy(d)
    d.pop("trim_reuse", None)
    if d.get("reinforce_state"):
        d["reinforce_state"].pop("elapsed_s", None)
    return d


# ── 격자·세분화 단위 — store= 배선 ──────────────────────────────────────────────


def test_coarse_grid_reuses_a_primed_store_bit_identically(env):
    ac, stall, limits, db, _ = env
    scope = _scope()
    cold = coarse_grid(ac, stall, limits, db, ctx=_vctx(), n_mach=3, alts=(1000.0,), fuels=(200.0,), store=scope)
    assert _origins(cold["trims"])["reused"] == 0
    warm = coarse_grid(ac, stall, limits, db, ctx=_vctx(), n_mach=3, alts=(1000.0,), fuels=(200.0,), store=scope)
    counts = _origins(warm["trims"])
    # 수렴 기록만 재사용한다 — 미수렴 점(있다면)은 다시 푼다
    assert counts["reused"] == sum(1 for tr in cold["trims"].values() if tr.converged) > 0
    for name, tr in warm["trims"].items():
        ref = cold["trims"][name]
        assert (tr.converged, tr.cost, tr.flags, tr.reserve) == (ref.converged, ref.cost, ref.flags, ref.reserve)


def test_region_grid_reuses_the_trim_tab_batch(env):
    """트림 탭이 같은 기본 격자를 먼저 풀었으면(=trim_batch로 저장) COARSE는 그 기록을 꺼내 쓴다."""
    ac, stall, limits, db, _ = env
    ctx = _vctx()
    scope = _scope()
    cold = region_grid(ac, ctx.region, ctx.model, ctx=ctx, n_mach=3, alts=(1000.0,), fuels=(200.0,), budget=24)
    cases = [cold["trims"][n].case for n in cold["trims"]]
    trim_batch(ac, cases, store=scope)  # 트림 탭 경로 — 같은 좌표를 저장소에 남긴다
    warm = region_grid(ac, ctx.region, ctx.model, ctx=ctx, n_mach=3, alts=(1000.0,), fuels=(200.0,), budget=24,
                       store=scope)
    assert _origins(warm["trims"])["reused"] == sum(1 for tr in cold["trims"].values() if tr.converged) > 0


def test_refine_hits_and_misses_the_store(env):
    """REFINE 중점 — 저장소 히트는 풀지 않고 조립(origin reused), 미스는 풀어 저장한다."""
    ac, stall, limits, db, _ = env

    def _fresh():
        out = coarse_grid(ac, stall, limits, db, ctx=_vctx(), n_mach=3, alts=(1000.0, 3000.0), fuels=(200.0,))
        return out["points"], LinearModelSet(), out["trims"]

    scope = _scope()
    points, lms, trims = _fresh()
    n0 = len(trims)
    rep = refine_trim_points(ac, points, lms, trims, ctx=_vctx(), tol=0.05, max_points=len(points) + 4, store=scope)
    if not rep["inserted"]:
        pytest.skip("tol 0.05로도 삽입이 없다 — 히트/미스는 세션 테스트가 덮는다")
    assert _origins(trims)["reused"] == 0  # 첫 실행은 전부 미스 — 풀어서 저장만 한다
    # 같은 격자에서 다시 세분화 — 같은 중점이 나오고 전부 히트다
    points2, lms2, trims2 = _fresh()
    rep2 = refine_trim_points(ac, points2, lms2, trims2, ctx=_vctx(), tol=0.05, max_points=len(points2) + 4,
                              store=scope)
    assert rep2["inserted"] == rep["inserted"]
    reused = [n for n, tr in trims2.items() if getattr(tr, "origin", "computed") == "reused"]
    assert sorted(reused) == sorted(n for n in rep["inserted"] if trims[n].converged)
    for n in reused:
        assert (trims2[n].cost, trims2[n].flags, trims2[n].reserve) == (trims[n].cost, trims[n].flags,
                                                                        trims[n].reserve)
    assert _origins(trims2)["computed"] == len(trims2) - len(reused) == n0 + len(rep2["inserted"]) - len(reused)


# ── 세션 — trim_store= 관통·집계·왕복 ──────────────────────────────────────────


def test_first_run_with_an_empty_store_is_bit_identical_to_none(env):
    """빈 저장소를 준 첫 실행은 store=None과 비트 동일 — 히트가 없으면 시드 사슬이 그대로다."""
    ac, stall, limits, db, design = env
    bare = DesignSession(_small())
    bare.run(ac, stall, limits, db, design, verdict_ctx=_vctx(), fingerprint="fp")
    stored = DesignSession(_small())
    stored.run(ac, stall, limits, db, design, verdict_ctx=_vctx(), fingerprint="fp", trim_store=_scope())
    assert _strip(stored.to_dict()) == _strip(bare.to_dict())
    assert bare.report()["trim_reuse"]["enabled"] is False
    rep = stored.report()["trim_reuse"]
    assert rep["enabled"] is True and rep["reused"] == 0 and rep["computed"] == len(stored.trims)


def test_repeat_design_on_one_store_recomputes_nothing(env):
    """같은 설정을 같은 저장소에 두 번 — 두 번째는 수렴 트림 전부 재사용·재계산 0, 산출물 비트 동일 (05 §11.10)."""
    ac, stall, limits, db, design = env
    scope = _scope()
    s1 = DesignSession(_small())
    s1.run(ac, stall, limits, db, design, verdict_ctx=_vctx(), fingerprint="fp", trim_store=scope)
    s2 = DesignSession(_small())
    s2.run(ac, stall, limits, db, design, verdict_ctx=_vctx(), fingerprint="fp", trim_store=scope)
    r = s2.report()["trim_reuse"]
    unconverged = sum(1 for tr in s1.trims.values() if not tr.converged)
    assert r["reused"] == len(s2.trims) - unconverged
    assert r["computed"] == unconverged == 0  # 데모 격자는 전 점 수렴 — 재계산 0
    assert _strip(s2.to_dict()) == _strip(s1.to_dict())


def test_another_fingerprint_hits_nothing(env):
    """풀이 설정·플랜트가 바뀌면 트림 지문이 바뀐다 — 다른 지문 창은 히트 0, 전부 새로 푼다."""
    ac, stall, limits, db, design = env
    store = TrimStore(1000)
    s1 = DesignSession(_small())
    s1.run(ac, stall, limits, db, design, verdict_ctx=_vctx(), fingerprint="fp", trim_store=store.scope("fp-a"))
    s2 = DesignSession(_small())
    s2.run(ac, stall, limits, db, design, verdict_ctx=_vctx(), fingerprint="fp", trim_store=store.scope("fp-b"))
    r = s2.report()["trim_reuse"]
    assert r["reused"] == 0 and r["computed"] == len(s2.trims)
    assert _strip(s2.to_dict()) == _strip(s1.to_dict())


def test_resume_with_the_store_accumulates_the_counts(env):
    """취소 → 왕복 → 재개(서버가 창을 다시 준다) — 수는 왕복에 실려 이어 센다, 저장소는 직렬화하지 않는다."""
    ac, stall, limits, db, design = env
    scope = _scope()
    s = DesignSession(_small())
    calls = []
    # 취소는 COARSE 뒤에 — COARSE 안에서 끊으면 그 판의 트림이 세션에 안 담긴다(종전 취소 규약: 스테이지 처음부터 재개)
    s.run(ac, stall, limits, db, design, verdict_ctx=_vctx(), fingerprint="fp", trim_store=scope,
          on_progress=lambda d, t, m: (calls.append(m), len(calls) >= 6)[1])
    assert s.status == "cancelled"
    mid = s.report()["trim_reuse"]
    assert mid["reused"] + mid["computed"] == len(s.trims) > 0
    d = s.to_dict()
    assert d["trim_reuse"] == {"reused": mid["reused"], "computed": mid["computed"]}  # enabled는 실행 인자다
    s2 = DesignSession.from_dict(d)
    s2.run(ac, stall, limits, db, design, verdict_ctx=_vctx(), fingerprint="fp", trim_store=scope)
    r = s2.report()["trim_reuse"]
    assert r["reused"] + r["computed"] == len(s2.trims)
    assert r["reused"] >= mid["reused"] and r["computed"] >= mid["computed"]


def test_a_saved_session_without_the_counts_still_loads(env):
    """이 단계 전 저장물에는 trim_reuse가 없다 — 0에서 시작해 읽힌다(왕복 규약)."""
    ac, stall, limits, db, design = env
    s = DesignSession(_small(budget_iters=1))
    s.run(ac, stall, limits, db, design, verdict_ctx=_vctx(), fingerprint="fp")
    d = s.to_dict()
    d.pop("trim_reuse")
    s2 = DesignSession.from_dict(d)
    assert s2.report()["trim_reuse"] == {"reused": 0, "computed": 0, "enabled": False}
