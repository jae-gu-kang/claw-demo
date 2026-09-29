"""기체 프로파일의 평가 기준·튜닝 목표 절 (기준 통합 ① S2, v1.51).

프로파일 = 설계 작업 단위. /criteria(합격선·권장선)와 /tuning(목표·J 가중치)은 그 단위의 모든 탭이 공유한다.
핵심 계약: ① 없음·부분 = 도구 기본값(기본값을 문서에 굳히지 않는다) ② 오류는 문서 경로를 짚는다
③ 형상 변형은 못 고친다 ④ 옛 문서(절이 없던 때)가 그대로 읽히고 저장된다 ⑤ 목표 충돌은 저장되되 경고다.
"""

import copy

import pytest

from claw.pipeline.criteria import GainEvalCriteria
from claw.profile import ProfileError, build_profile, load_example, validate_document
from claw.profile.document import load_showcase
from claw.profile.schema import document_warnings


def _built(doc):
    return build_profile(validate_document(doc), validated=True)


def test_없으면_도구_기본값이고_그렇다고_말한다():
    doc = load_example()
    doc.pop("criteria", None)
    doc.pop("tuning", None)
    v = validate_document(doc)
    assert v["criteria"] is None and v["tuning"] is None
    b = build_profile(v, validated=True)
    assert b.criteria_source == "default"
    assert b.eval_criteria.judgement_fingerprint() == GainEvalCriteria().judgement_fingerprint()
    assert b.eval_criteria.targets_fingerprint() == GainEvalCriteria().targets_fingerprint()


def test_옛_문서는_읽고_저장해도_그대로다():
    """절이 없던 문서 → 검증 → 다시 검증: 두 번째가 첫 번째와 같다(멱등). 새 절은 없음으로만 붙는다."""
    doc = load_example()
    doc.pop("criteria", None)
    doc.pop("tuning", None)
    once = validate_document(doc)
    assert validate_document(copy.deepcopy(once)) == once
    assert {k: v for k, v in once.items() if k not in ("criteria", "tuning")} == \
        {k: v for k, v in validate_document(load_example()).items() if k not in ("criteria", "tuning")}


def test_적은_칸만_남고_나머지는_기본값을_따른다():
    doc = load_example()
    doc["criteria"] = {"margin": {"pm_min_deg": 40}}  # 정수로 적어도
    doc["tuning"] = {"targets": {"zeta_sp": 0.9}}
    v = validate_document(doc)
    assert v["criteria"] == {"margin": {"pm_min_deg": 40.0}}  # 실수로 정규화 · 적은 칸만
    assert isinstance(v["criteria"]["margin"]["pm_min_deg"], float)
    assert v["tuning"] == {"targets": {"zeta_sp": 0.9}}
    b = build_profile(v, validated=True)
    assert b.criteria_source == "profile"
    c = b.eval_criteria
    assert c.margin.pm_min_deg == 40.0 and c.margin.gm_min_db == 6.0  # 적지 않은 칸은 기본값
    assert c.targets.zeta_sp == 0.9 and c.targets.zeta_dr == 0.6


@pytest.mark.parametrize("section,value,path", [
    ("criteria", {"targets": {"zeta_sp": 0.9}}, "/criteria/targets"),  # 목표는 /tuning 몫
    ("criteria", {"marign": {}}, "/criteria/marign"),                   # 오타 그룹
    ("criteria", {"margin": {"pm_min": 40.0}}, "/criteria/margin/pm_min"),  # 오타 칸 — 조용히 기본값이 되면 안 된다
    ("criteria", {"margin": {"pm_min_deg": -1.0}}, "/criteria/margin"),  # 값 검증
    ("criteria", {"margin": 3}, "/criteria/margin"),
    ("criteria", [1], "/criteria"),
    ("tuning", {"margin": {"pm_min_deg": 40.0}}, "/tuning/margin"),     # 판정선은 /criteria 몫
    ("tuning", {"targets": {"backoff": 1.5}}, "/tuning/targets"),
    # 형식 — 저장은 되고 평가 때 한계 비교에서 터지던 값들(리뷰 지적)
    ("criteria", {"response": {"rms_max": [1]}}, "/criteria/response/rms_max"),       # 500(AttributeError)이던 자리
    ("criteria", {"response": {"rms_max": {"alt": "10"}}}, "/criteria/response/rms_max/alt"),
    ("tuning", {"weights": {"w_rms": True}}, "/tuning/weights/w_rms"),
    ("tuning", {"weights": {"w_rms": "2"}}, "/tuning/weights/w_rms"),
    ("criteria", {"robustness": {"monte_carlo_n": 2.7}}, "/criteria/robustness/monte_carlo_n"),
    ("criteria", {"response": {"bandwidth_window": "ab"}}, "/criteria/response/bandwidth_window"),
    ("criteria", {"schedule": {"midpoints": 1}}, "/criteria/schedule/midpoints"),
])
def test_오류는_문서_경로를_짚는다(section, value, path):
    doc = load_example()
    doc[section] = value
    with pytest.raises(ProfileError) as e:
        validate_document(doc)
    assert e.value.path == path


def test_형상_변형은_기준을_고칠_수_없다():
    doc = load_example()
    doc["variants"] = [{"id": "v1", "name": "변형", "patch": {"/criteria": {"margin": {"pm_min_deg": 30.0}}}}]
    with pytest.raises(ProfileError) as e:
        validate_document(doc)
    assert e.value.path == "/variants/0/patch" and "작업 단위" in e.value.message
    doc["variants"][0]["patch"] = {"/tuning/targets/zeta_sp": 0.9}
    with pytest.raises(ProfileError):
        validate_document(doc)


def test_목표_충돌은_저장되고_경고다():
    """합격선보다 느슨한 목표도 문서는 저장된다(거절은 자동 설계가 제출 시점에 한다) — 대신 경고가 칸을 짚는다."""
    doc = load_example()
    doc["tuning"] = {"targets": {"gm_db": 7.0, "pm_deg": 40.0}}
    v = validate_document(doc)
    warns = {w["path"]: w["message"] for w in document_warnings(v)}
    assert "합격선" in warns["/tuning/targets/pm_deg"]
    assert "권장선" in warns["/tuning/targets/gm_db"]
    assert not [w for w in document_warnings(validate_document(load_example())) if w["path"].startswith("/tuning")]


def test_쇼케이스_기체는_설계_기록의_목표를_프로파일에_싣는다():
    """쇼케이스 게인 표는 ζ_sp 0.9 목표로 설계됐다(설계 기록 provenance.design.config.targets) — 그 목표가 이제
    프로파일의 /tuning에도 있다. 두 자리가 어긋나면 서버가 프로파일 목표로 재설계할 때 조용히 0.7로 돌아간다."""
    doc = load_showcase()
    rec = doc["law"]["gain_tables"]["provenance"]["design"]["config"]["targets"]
    b = _built(doc)
    for k, v in rec.items():
        assert getattr(b.eval_criteria.targets, k) == v
    assert b.criteria_source == "profile"


def test_형식은_정규화된다_그리고_빈_그룹은_적은_것이_아니다():
    doc = load_example()
    doc["criteria"] = {"robustness": {"monte_carlo_n": 3.0}, "response": {"rms_max": {"alt": 12}}, "margin": {}}
    v = validate_document(doc)
    assert v["criteria"]["robustness"]["monte_carlo_n"] == 3 and isinstance(v["criteria"]["robustness"]["monte_carlo_n"], int)
    assert v["criteria"]["response"]["rms_max"] == {"alt": 12.0}
    doc = load_example()
    doc["criteria"] = {"margin": {}}
    assert _built(doc).criteria_source == "default"


def test_축별_한계는_적은_축만_기본값_위에_덧붙는다():
    """rms_max: {"alt": 5}만 적어도 속도·헤딩 RMS 한계는 기본값으로 남는다 — 칸 통째 교체면 다른 축 판정이 조용히
    사라진다. 문서에는 적은 축만 남는다(기본값을 굳히지 않는다)."""
    doc = load_example()
    doc["criteria"] = {"response": {"rms_max": {"alt": 5.0}}}
    v = validate_document(doc)
    assert v["criteria"] == {"response": {"rms_max": {"alt": 5.0}}}
    applied = build_profile(v, validated=True).eval_criteria.response.rms_max
    default = GainEvalCriteria().response.rms_max
    assert applied == {**default, "alt": 5.0} and set(applied) == set(default)
