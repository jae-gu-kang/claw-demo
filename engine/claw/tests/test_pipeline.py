"""M15 pipeline 검증 — 부분집합 지문 선택적 무효화, 캐시, Δ리포트, 트림 연동."""

import pytest

from claw.common.contracts import TrimCase
from claw.params.param import ParamDef
from claw.params.paramset import ParamSet
from claw.pipeline import Pipeline, delta_report, subset_fingerprint
from claw.plant import make_demo_aircraft
from claw.trim import trim_level

DEFS = (
    ParamDef("veh.mass", 1000.0, "kg", "질량"),
    ParamDef("gain.kp", 0.5, "-", "게인"),
)


def make_pipe(calls):
    pipe = Pipeline()
    pipe.add("trim", lambda ps: (calls.__setitem__("trim", calls["trim"] + 1), ps["veh.mass"] * 2)[1], uses=("veh.",))
    pipe.add(
        "margin",
        lambda ps, trim: (calls.__setitem__("margin", calls["margin"] + 1), trim + ps["gain.kp"])[1],
        deps=("trim",),
        uses=("gain.",),
    )
    return pipe


def test_cache_and_selective_invalidation():
    calls = {"trim": 0, "margin": 0}
    pipe = make_pipe(calls)
    ps = ParamSet(DEFS)

    assert pipe.run("margin", ps) == pytest.approx(2000.5)
    assert calls == {"trim": 1, "margin": 1}
    pipe.run("margin", ps)  # 동일 스냅샷 → 전부 캐시
    assert calls == {"trim": 1, "margin": 1}

    ps_gain = ps.copy_with({"gain.kp": 0.9})  # margin만 소비하는 파라미터
    assert pipe.run("margin", ps_gain) == pytest.approx(2000.9)
    assert calls == {"trim": 1, "margin": 2}  # trim은 캐시 유지 (선택적 무효화)

    ps_mass = ps.copy_with({"veh.mass": 1200.0})  # 상류 파라미터 → 전파 재계산
    assert pipe.run("margin", ps_mass) == pytest.approx(2400.5)
    assert calls == {"trim": 2, "margin": 3}


def test_subset_fingerprint():
    ps = ParamSet(DEFS)
    fp_veh = subset_fingerprint(ps, ("veh.",))
    assert fp_veh == subset_fingerprint(ps.copy_with({"gain.kp": 0.9}), ("veh.",))  # 무관 변경에 불변
    assert fp_veh != subset_fingerprint(ps.copy_with({"veh.mass": 999.0}), ("veh.",))
    assert subset_fingerprint(ps, ()) == ps.fingerprint()  # 빈 접두사 = 전체 지문


def test_unknown_node_and_missing_dep():
    pipe = Pipeline()
    with pytest.raises(KeyError):
        pipe.run("nope", ParamSet(DEFS))
    pipe.add("b", lambda ps, a: a, deps=("a",))
    with pytest.raises(KeyError):
        pipe.run("b", ParamSet(DEFS))


def test_delta_report_with_real_trim():
    """Δ리포트 실사용: 마하 변경 → 트림 α·스로틀 이동량 정량화 (02 §2.4)."""
    ac = make_demo_aircraft()
    defs = (
        ParamDef("case.mach", 0.6, "-", "마하수"),
        ParamDef("case.alt", 1000.0, "m", "고도"),
        ParamDef("case.fuel", 200.0, "kg", "연료"),
    )
    pipe = Pipeline()
    pipe.add(
        "trim",
        lambda ps: trim_level(
            ac, TrimCase("dr", ps["case.mach"], ps["case.alt"], ps["case.fuel"]),
            fingerprint=ps.fingerprint(),
        ),
        uses=("case.",),
    )
    a = ParamSet(defs)
    b = a.copy_with({"case.mach": 0.7})
    rep = delta_report(
        pipe, "trim", a, b,
        metrics=lambda tr: {"alpha": tr.state.euler()[1], "thr": float(tr.control.throttle[0])},
    )
    assert rep["param_diff"] == {"case.mach": (0.6, 0.7)}
    assert rep["delta"]["alpha"] < 0  # 마하 증가 → 트림 α 감소
    assert rep["delta"]["thr"] > 0  # 항력 증가 → 스로틀 증가
    assert rep["a"]["alpha"] == pytest.approx(rep["b"]["alpha"] - rep["delta"]["alpha"])
