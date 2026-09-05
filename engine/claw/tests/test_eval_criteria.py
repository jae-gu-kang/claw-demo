"""pipeline.criteria 검증 — 필수 11항목 기준 데이터의 계약.

핵심은 셋이다: ① 직렬화 왕복이 지문을 보존한다(기준이 계보 키다) ② 모르는
키는 조용히 기본값이 되지 않고 거부된다(오타가 "내 문턱이 반영됐다"는 착각이
되면 안 된다) ③ 기본값은 기존 판정선(diagnose 상수)과 같은 값으로 시드된다 —
기준 정본화가 조용한 판정 변화가 되면 안 된다.
"""

import pytest

from claw.pipeline import diagnose
from claw.pipeline.criteria import (
    SCHEMA_VERSION,
    AuthorityCriteria,
    CouplingCriteria,
    GainEvalCriteria,
    JWeights,
    RobustnessCriteria,
)


def test_직렬화_왕복이_지문을_보존한다():
    c = GainEvalCriteria()
    c2 = GainEvalCriteria.from_dict(c.to_dict())
    assert c2.fingerprint() == c.fingerprint()


def test_문턱_하나가_바뀌면_지문이_바뀐다():
    base = GainEvalCriteria()
    d = base.to_dict()
    d["actuator"]["sat_frac_max"] = 0.10
    assert GainEvalCriteria.from_dict(d).fingerprint() != base.fingerprint()


def test_부분_dict는_나머지를_기본값으로_채운다():
    c = GainEvalCriteria.from_dict(
        {"authority": {"de_frac_warn": 0.4, "de_frac_max": 0.7}})
    assert c.authority.de_frac_max == 0.7
    assert c.actuator.sat_frac_max == GainEvalCriteria().actuator.sat_frac_max


def test_모르는_그룹은_거부():
    with pytest.raises(ValueError, match="알 수 없는 기준 그룹"):
        GainEvalCriteria.from_dict({"actuatr": {}})


def test_모르는_필드는_거부():
    # 오타가 기본값으로 조용히 대체되면 사용자는 자기 문턱이 반영됐다고 믿는다
    with pytest.raises(ValueError, match="actuator"):
        GainEvalCriteria.from_dict({"actuator": {"sat_frac_maxx": 0.1}})


def test_기본값은_기존_판정선과_같은_값으로_시드된다():
    """값의 출처가 바뀌는 것이지 값이 바뀌는 게 아니다 — diagnose 상수와 대조."""
    c = GainEvalCriteria()
    assert c.actuator.sat_frac_max == diagnose.SAT_FRAC_WARN
    assert c.recovery.windup_frac_max == diagnose.WINDUP_FRAC
    assert c.response.rms_max == diagnose.RMS_THRESH
    assert c.envelope.alpha_margin_min == diagnose._GRID_CHECKS["worst_stall_margin"][0]


def test_트림_여유_순서_검증():
    with pytest.raises(ValueError):
        AuthorityCriteria(de_frac_warn=0.9, de_frac_max=0.5)


def test_구_스키마는_조용히_매핑되지_않는다():
    """v1(trim 그룹·w_track류)이 절반만 이식되면 "내 기준이 반영됐다"는 착각이 된다."""
    with pytest.raises(ValueError, match="스키마 v1"):
        GainEvalCriteria.from_dict({"schema_version": 1})
    with pytest.raises(ValueError, match="알 수 없는 기준 그룹"):
        GainEvalCriteria.from_dict({"trim": {"de_frac_warn": 0.4}})
    with pytest.raises(ValueError, match="weights"):
        GainEvalCriteria.from_dict({"weights": {"w_track": 1.0}})


def test_스키마_버전이_직렬화에_실린다():
    d = GainEvalCriteria().to_dict()
    assert d["schema_version"] == SCHEMA_VERSION


def test_J_목표값은_튜너_목표를_합성한다():
    """J_ζ·J_BW의 목표가 튜너(TuneTargets)와 갈리면 "튜닝 성공 = 좋은 J"가 깨진다."""
    from claw.design.tune import TuneTargets

    c = GainEvalCriteria()
    assert c.targets.zeta_sp == TuneTargets().zeta_sp
    assert c.targets.roll_lambda == TuneTargets().roll_lambda


def test_동시명령은_두_축이_다_걸려야_한다():
    with pytest.raises(ValueError, match="동시명령"):
        CouplingCriteria(dpsi=0.0)


def test_가중치는_음수를_거부():
    with pytest.raises(ValueError):
        JWeights(w_rms=-1.0)


def test_강건성_corners_어휘_검증():
    with pytest.raises(ValueError, match="corners"):
        RobustnessCriteria(corners="montecarlo")


def test_대역폭_창은_tuple_list_왕복에도_지문이_같다():
    d = GainEvalCriteria().to_dict()
    d["response"]["bandwidth_window"] = [0.5, 8.0]
    a = GainEvalCriteria.from_dict(d)
    b = GainEvalCriteria.from_dict(a.to_dict())
    assert a.fingerprint() == b.fingerprint()


def test_파생_문턱은_진단_상수와_같은_값이다():
    """규칙 3의 이행 — 기준이 진단·격자 판정의 정본이 되되, 기본값에서는 종전과
    한 글자도 다르지 않아야 한다(정본화가 조용한 판정 변화가 되면 안 된다)."""
    c = GainEvalCriteria()
    th = c.to_diagnose_thresholds()
    assert th["rms"] == diagnose.RMS_THRESH
    assert th["sat_frac"] == diagnose.SAT_FRAC_WARN
    assert th["windup_frac"] == diagnose.WINDUP_FRAC
    assert th["limiter_frac"] == diagnose.LIMITER_FRAC
    assert abs(th["local_frac"] - diagnose.LOCAL_FRAC) < 1e-15
    grid = c.to_grid_thresholds()
    for key, (value, _above) in diagnose._GRID_CHECKS.items():
        assert abs(grid[key] - value) < 1e-15, key
    # 반대 방향 — 진단이 모르는 지표를 격자에 넣지 않는다
    assert set(grid) == set(diagnose._GRID_CHECKS)
