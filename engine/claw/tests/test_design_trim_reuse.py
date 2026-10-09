"""자동 설계의 트림 저장소 재사용 (05 §11.10 사용자 후속 ③) — 켜면 같은 모델·조건·설정의 트림을 다시 풀지 않는다.

**기본은 끔**이다(AutoDesignConfig.trim_reuse false — 서버가 그때만 창을 준다). 근거가 이 파일의 특성 테스트다:
설계의 **자기 좌표**가 이미 저장소에 있으면(v1.72부터 탭이 다 같은 기본 격자를 쓰므로 흔한 경우다) 꺼내 온 해는
설계가 스스로 풀었을 해와 마지막 비트가 다르고, 아슬아슬한 점은 수렴 판정까지 뒤집혀 judged·failures가 움직인다.

- store=None은 종전 그대로다(엔진·설계 골든이 지킨다) — 저장소를 처음 받는 실행도 빈 저장소면 비트 동일이어야 한다
- 재사용 집계는 report()["trim_reuse"]({"reused","computed","enabled","reused_names"})가 말하고, 수·이름은
  왕복(to_dict/from_dict)에 실려 재개가 이어 센다 — 서버 reuse_counts와 같은 칸 이름
- 꺼낸 점 이름(reused_names)은 진단용이다 — 놀라운 failures를 뒤에 되짚는 유일한 단서다
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


def _z(tr) -> tuple:
    """트림 해 자체 — 받음각·엘러본·스로틀. 수렴 여부·비용만 보면 「같은 점을 꺼냈다」와 「같은 답이다」가 갈린다."""
    return (float(tr.state.euler()[1]), float(tr.control.elevon[0]), float(tr.control.throttle[0]))


def test_region_grid_reuses_the_trim_tab_batch(env):
    """트림 탭이 같은 기본 격자를 먼저 풀었으면(=trim_batch로 저장) COARSE는 그 기록을 꺼내 쓴다 — **그리고 그 해는
    COARSE가 스스로 풀었을 해와 같지 않다**. 수만 세면 이 사실이 안 보인다(그래서 설계 재사용은 기본 끔이다):
    trim_batch의 시드 사슬(직전 해를 다음 케이스 시드로)이 region_grid의 것과 달라 마지막 비트가 갈린다."""
    ac, stall, limits, db, _ = env
    ctx = _vctx()
    scope = _scope()
    cold = region_grid(ac, ctx.region, ctx.model, ctx=ctx, n_mach=3, alts=(1000.0,), fuels=(200.0,), budget=24)
    cases = [cold["trims"][n].case for n in sorted(cold["trims"])]
    trim_batch(ac, cases, store=scope)  # 트림 탭 경로 — 같은 좌표를 저장소에 남긴다(배치 순서만 다르다)
    warm = region_grid(ac, ctx.region, ctx.model, ctx=ctx, n_mach=3, alts=(1000.0,), fuels=(200.0,), budget=24,
                       store=scope)
    assert _origins(warm["trims"])["reused"] == sum(1 for tr in cold["trims"].values() if tr.converged) > 0
    # 꺼내 온 해를 냉간 해와 **값으로** 대조한다 — 수만 세면 「같은 점을 꺼냈다」가 「같은 답이다」로 읽힌다.
    # 이 격자(옛 예제 기체·3점)에서는 지금 비트 동일하다. 어긋나면 시드 사슬이 바뀐 것이고, 재사용 기본값의
    # 근거(아래 특성 테스트)를 다시 재야 한다 — 그래서 tol 없이 붙잡는다.
    # 일반적으로 비트 동일이 아니라는 사실은 test_priming_the_designs_own_coordinates_changes_the_verdict_scale이
    # 고정한다(설계 자기 좌표를 프라이밍하면 판정 규모까지 움직인다)
    for name, tr in warm["trims"].items():
        ref = cold["trims"][name]
        assert (tr.converged, tr.cost, _z(tr), dict(tr.flags), dict(tr.reserve)) == (
            ref.converged, ref.cost, _z(ref), dict(ref.flags), dict(ref.reserve)), (
            f"{name}: trim_batch가 남긴 해가 region_grid의 냉간 해와 다르다 — 05 §11.10의 기본 끔 근거를 다시 잰다")


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
    # enabled는 실행 인자라 싣지 않는다 — 수와 꺼낸 점 이름만 왕복한다
    assert d["trim_reuse"] == {"reused": mid["reused"], "computed": mid["computed"],
                               "reused_names": mid["reused_names"]}
    s2 = DesignSession.from_dict(d)
    s2.run(ac, stall, limits, db, design, verdict_ctx=_vctx(), fingerprint="fp", trim_store=scope)
    r = s2.report()["trim_reuse"]
    assert r["reused"] + r["computed"] == len(s2.trims)
    assert r["reused"] >= mid["reused"] and r["computed"] >= mid["computed"]


def test_the_report_names_the_points_it_took_from_the_store(env):
    """어느 점을 꺼냈나 — 수만 있으면 놀라운 failures를 뒤에 되짚을 수 없다(리뷰 2항). 이름도 왕복에 실린다."""
    ac, stall, limits, db, design = env
    scope = _scope()
    s1 = DesignSession(_small(budget_iters=1))
    s1.run(ac, stall, limits, db, design, verdict_ctx=_vctx(), fingerprint="fp", trim_store=scope)
    assert s1.report()["trim_reuse"]["reused_names"] == []  # 빈 저장소 — 꺼낸 점이 없다
    s2 = DesignSession(_small(budget_iters=1))
    s2.run(ac, stall, limits, db, design, verdict_ctx=_vctx(), fingerprint="fp", trim_store=scope)
    rep = s2.report()["trim_reuse"]
    names = rep["reused_names"]
    assert names == sorted(names) and len(names) == rep["reused"] > 0
    assert set(names) <= set(s2.trims), "보고가 이 세션에 없는 점 이름을 말한다"
    assert all(s1.trims[n].converged for n in names)  # 수렴 기록만 꺼낸다
    # 왕복 — 재개가 이어 모은다(수와 같은 규약)
    assert DesignSession.from_dict(s2.to_dict()).report()["trim_reuse"]["reused_names"] == names


def test_a_saved_session_without_the_counts_still_loads(env):
    """이 단계 전 저장물에는 trim_reuse가 없다 — 0에서 시작해 읽힌다(왕복 규약)."""
    ac, stall, limits, db, design = env
    s = DesignSession(_small(budget_iters=1))
    s.run(ac, stall, limits, db, design, verdict_ctx=_vctx(), fingerprint="fp")
    d = s.to_dict()
    d.pop("trim_reuse")
    s2 = DesignSession.from_dict(d)
    assert s2.report()["trim_reuse"] == {"reused": 0, "computed": 0, "enabled": False, "reused_names": []}


# ── 설정 플래그 — 기본 끔 ─────────────────────────────────────────────────────


def test_trim_reuse_is_off_by_default_and_must_be_a_bool():
    """`trim_reuse` 기본 False — 서버가 이 플래그를 볼 때만 창을 준다(routes/design.py `_design_trim_scope`)."""
    assert AutoDesignConfig().trim_reuse is False
    assert AutoDesignConfig(trim_reuse=True).trim_reuse is True
    # 왕복에 실린다 — 재개가 제출 때의 스위치를 그대로 쓴다(재개에서 조용히 켜지지 않게)
    assert AutoDesignConfig.from_dict(AutoDesignConfig(trim_reuse=True).to_dict()).trim_reuse is True
    for bad in (1, 0, "true", None):
        with pytest.raises(ValueError, match="trim_reuse"):
            AutoDesignConfig(trim_reuse=bad)


# ── 특성 테스트 — 왜 기본이 끔인가 ─────────────────────────────────────────────
#
# 아래 테스트는 **같기를 바라는 것이 아니라 다르다는 사실을 고정한다**. v1.75는 「게인 표 비트 동일」을 근거로 재사용을
# 기본으로 켰지만, 그 실험은 트림 탭 격자를 프라이밍해 24개 기록 중 4개만 설계 좌표에 닿았다. 설계의 **자기 좌표**를
# 프라이밍하면(v1.72부터 탭이 다 같은 기본 격자를 쓰니 흔한 경우다) 판정 규모까지 움직인다. 이 드리프트가 커지거나
# 조용히 사라지면 기본값 결정의 근거가 바뀐 것이므로, 여기서 붙잡아 사람이 다시 재게 한다.

# 출하 예제(200 kg)로 잰다 — conftest가 예제 자리에 옛 1200 kg 픽스처를 두므로 example_profile()로는 이 효과를
# 볼 수 없다(옛 기체에서는 판정 수가 그대로고 트림 값만 마지막 비트에서 흔들린다). 서버가 설계에 넘기는 그 묶음
# (design_inputs)을 그대로 쓴다
_CHAR_FLIP = "M0.28_h100_f10"  # 미수렴 → 수렴으로 뒤집히는 아슬아슬한 점
_CHAR_COLD = (35, 10)  # (judged, failures) — 냉간(저장소 없음)
_CHAR_WARM = (40, 12)  # 같은 요청, 자기 좌표가 프라이밍된 저장소


def _shipped_inputs():
    from claw.design.orchestrator import design_inputs
    from claw.profile import build_profile
    from claw.profile.document import load_shipped_example

    return design_inputs(build_profile(load_shipped_example()))


def _char_run(inp, store):
    s = DesignSession(_small(budget_iters=1))
    s.run(inp["aircraft"], inp["stall_table"], inp["limits"], inp["db_ranges"], inp["design"],
          verdict_ctx=inp["verdict_ctx"], rate_filters=inp["rate_filters"], actuator=inp["actuator"],
          fingerprint="fp", trim_store=store)
    return s


def test_priming_the_designs_own_coordinates_changes_the_verdict_scale(env):
    """자기 좌표가 저장소에 있으면 **판정 규모가 달라진다** — 재사용을 기본으로 켜지 않는 근거(05 §11.10).

    프라이밍은 retry 없이(엔진 기본) 같은 좌표를 그대로 푼다 — 배치 **순서**만 다르다. 그런데도 시드 사슬이 달라
    아슬아슬한 점의 수렴 판정이 뒤집히고, 그 점의 루프가 마진 맵에 미달로 들어온다.
    """
    inp = _shipped_inputs()
    cold = _char_run(inp, None)
    rc = cold.report()
    assert (rc["judged"], rc["failures"]) == _CHAR_COLD, (
        f"냉간 기준선이 움직였다 {rc['judged']}·{rc['failures']} — 재측정하고 05 §11.10·CHANGELOG의 수를 같이 고친다")
    assert cold.trims[_CHAR_FLIP].converged is False
    assert cold.trims[_CHAR_FLIP].cost == pytest.approx(1.9701209393e-12, rel=1e-6)
    assert cold.points.get(_CHAR_FLIP).trimmable is False

    scope = _scope()
    trim_batch(inp["aircraft"], [cold.trims[n].case for n in sorted(cold.trims)], store=scope)
    warm = _char_run(inp, scope)
    rw = warm.report()
    assert rw["trim_reuse"]["reused"] == len(warm.trims)  # 전 점을 꺼냈다 — 푼 것은 프라이밍 배치다
    # 여기서 **같기를 단정하지 않는다** — 다르다는 것이 이 테스트의 내용이다
    assert (rw["judged"], rw["failures"]) == _CHAR_WARM, (
        f"프라이밍 쪽 규모가 움직였다 {rw['judged']}·{rw['failures']} — 드리프트가 커졌거나 사라졌다."
        " 재측정하고 05 §11.10·CHANGELOG의 수와 기본값 결정을 같이 본다")
    assert (rw["judged"], rw["failures"]) != _CHAR_COLD, "드리프트가 사라졌다 — 기본 끔의 근거를 다시 잰다"
    tr = warm.trims[_CHAR_FLIP]
    assert tr.converged is True and tr.cost == pytest.approx(1.3602353471e-12, rel=1e-6)
    assert warm.points.get(_CHAR_FLIP).trimmable is True
    assert _CHAR_FLIP in rw["trim_reuse"]["reused_names"]  # 진단은 이 이름에서 시작한다

