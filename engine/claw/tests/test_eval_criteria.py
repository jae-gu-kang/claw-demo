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


def test_마진_조성은_자동설계와_같은_값이다():
    """두 화면이 같은 점에서 다른 마진을 말하면 어느 쪽이 정본인지가 사라진다."""
    from claw.design.orchestrator import AutoDesignConfig, DesignSession
    from claw.pipeline.criteria import MarginComposition

    c, a = GainEvalCriteria().composition, AutoDesignConfig()
    # 자동 설계의 작동기는 기체 문서 값이다(config 없음 = 기체) — 기체도 config도 없을 때의
    # 폴백이 마진 조성 기본값과 같아야 한다 (두 경로 다 "형상 작동기가 이긴다" 규칙)
    fallback = DesignSession(a).actuator_used()
    assert fallback["source"] == {"wn": "default", "zeta": "default"}
    assert c.actuator_wn == fallback["wn"] and c.actuator_zeta == fallback["zeta"]
    assert c.delay_s == a.delay_s and c.pade_order == a.pade_order
    with pytest.raises(ValueError):
        MarginComposition(actuator_wn=0.0)
    with pytest.raises(ValueError):
        MarginComposition(delay_s=-0.01)


def test_판정_척도는_지표_키만_낸다():
    """영향성 그래프가 이 자를 지표 노드에 붙인다 — 키가 어긋나면 조용히 못 붙는다."""
    from claw.pipeline.influence import METRICS

    scales = GainEvalCriteria().to_metric_scales()
    assert set(scales) <= {m.key for m in METRICS}
    assert scales["alt_rms"] == 10.0 and scales["hdg_rms"] == 0.1


def test_판정선이_0이면_척도가_되지_않는다():
    """alpha_margin_min 0.0은 "여유가 없어지는 지점"이지 크기가 아니다 — 0으로 나눈다."""
    c = GainEvalCriteria()
    assert c.envelope.alpha_margin_min == 0.0
    assert "worst_stall_margin" not in c.to_metric_scales()


def test_기준이_비어_있으면_척도도_비운다():
    """tr/ts/mp/sse 상한은 [TBD]다 — 억지 기본값은 없는 판정선을 있다고 말하는 것이다."""
    scales = GainEvalCriteria().to_metric_scales()
    for key in ("alt_tr", "spd_ts", "hdg_mp", "alt_sse"):
        assert key not in scales


def test_기준을_채우면_척도가_따라온다():
    c = GainEvalCriteria.from_dict({"response": {"ts_max": {"alt": 8.0}}})
    scales = c.to_metric_scales()
    assert scales["alt_ts"] == 8.0
    assert "spd_ts" not in scales  # 채운 축만


def test_척도가_양수인_것은_기준이_먼저_막기_때문이다():
    """0 이하 상한은 **기준 생성에서** 걷힌다 — 척도가 뒤늦게 거를 일이 없다.
    그래도 to_metric_scales가 양수만 내는 계약은 유지한다(기준이 늘어날 때의 방어)."""
    with pytest.raises(ValueError):
        GainEvalCriteria.from_dict({"response": {"mp_max": {"alt": 0.0}}})
    assert all(v > 0 for v in GainEvalCriteria().to_metric_scales().values())


# ── 기준 통합 ① S1 — 판정 기준 지문 · 목표 지문 ────────────────────────────────


def test_지문_둘은_서로_독립이다():
    """목표만 바꾸면 판정 기준 지문은 그대로(「J 재계산」), 판정선을 바꾸면 목표 지문은 그대로(「재평가」)."""
    base = GainEvalCriteria()
    d = base.to_dict()
    d["targets"]["zeta_sp"] = 0.9
    tgt = GainEvalCriteria.from_dict(d)
    assert tgt.judgement_fingerprint() == base.judgement_fingerprint()
    assert tgt.targets_fingerprint() != base.targets_fingerprint()

    d = base.to_dict()
    d["margin"]["pm_min_deg"] = 40.0
    crit = GainEvalCriteria.from_dict(d)
    assert crit.judgement_fingerprint() != base.judgement_fingerprint()
    assert crit.targets_fingerprint() == base.targets_fingerprint()

    d = base.to_dict()
    d["weights"]["w_rms"] = 2.0
    w = GainEvalCriteria.from_dict(d)
    assert w.judgement_fingerprint() == base.judgement_fingerprint()
    assert w.targets_fingerprint() != base.targets_fingerprint()


def test_지문은_펼친_적용값으로_잰다_그리고_판정_함수_버전을_담는다(monkeypatch):
    """빈 설정({})도 기본값을 펼친 값으로 재야 기본값 변경이 감지된다. 판정 함수 버전을 올리면 값이 같아도 갈린다."""
    from claw.pipeline import criteria as pc

    assert GainEvalCriteria.from_dict({}).judgement_fingerprint() == GainEvalCriteria().judgement_fingerprint()
    before = GainEvalCriteria().judgement_fingerprint(), GainEvalCriteria().targets_fingerprint()
    monkeypatch.setattr(pc, "JUDGEMENT_SCHEME", "crit-test")
    after = GainEvalCriteria().judgement_fingerprint(), GainEvalCriteria().targets_fingerprint()
    assert before[0] != after[0] and before[1] != after[1]


def test_옛_지문은_그대로다():
    """S1은 동작 불변 — 저장물의 criteria_fingerprint(전 항목 한 해시)는 옮겨 가는 동안 그대로다.
    값을 못박는다: 기본값이나 to_dict 모양이 바뀌면 저장된 평가 결과가 전부 「다른 기준」이 된다 —
    그 변경은 의도해서 여기 값을 고치는 커밋이어야 한다."""
    assert GainEvalCriteria().fingerprint() == "285b1415cbf86dba"


def test_목표의_비율인_판정선은_판정_지문에도_든다():
    """λ_roll 합격선 = lam_min_frac × targets.roll_lambda — 이 목표를 바꾸면 카드 ④ 판정이 바뀐다.
    판정 지문이 그대로면 판정이 바뀐 결과가 「J 재계산」으로만 보인다."""
    base = GainEvalCriteria()
    d = base.to_dict()
    d["targets"]["roll_lambda"] = 20.0
    c = GainEvalCriteria.from_dict(d)
    assert c.judgement_fingerprint() != base.judgement_fingerprint()
    assert c.targets_fingerprint() != base.targets_fingerprint()


def test_평가_기준은_목표_충돌을_보고만_한다():
    """S1에서는 거절하지 않는다(동작 불변) — 판정은 design.criteria.target_conflicts 한 자리다."""
    d = GainEvalCriteria().to_dict()
    d["targets"]["gm_db"] = 7.0
    c = GainEvalCriteria.from_dict(d)  # 예전처럼 받아들인다
    assert [x["metric"] for x in c.target_conflicts()] == ["gm_db"]
    assert GainEvalCriteria().target_conflicts() == []
