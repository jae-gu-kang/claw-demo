"""BuiltProfile은 호출자와 가변 상태를 공유하지 않는다 (02 §5.6).

서버가 문서나 조립 결과를 캐시하는 순간, 공유된 dict 하나를 누가 고치면 지문은 그대로인데
조립되는 기체가 바뀌는 일이 생긴다. 지문이 말하는 기체와 계산한 기체가 갈라지면 안 된다.
"""

from claw.profile import build_profile, load_example, validate_document


def test_mutating_the_source_document_after_build_does_not_leak_in():
    doc = validate_document(load_example())
    p = build_profile(doc, validated=True)
    fp = p.fingerprint
    doc["mass"]["m_empty"] = 5000.0
    doc["law"]["design"]["scas"]["pitch"]["kp"] = 99.0
    assert p.aircraft().fuel_mass.m_empty == 800.0
    assert p.scas_axis_params("pitch")["kp"] == -2.0
    assert p.fingerprint == fp


def test_law_view_is_a_copy():
    p = build_profile(load_example(), validated=True)
    p.law["design"]["scas"]["pitch"]["kp"] = 99.0
    assert p.scas_axis_params("pitch")["kp"] == -2.0
