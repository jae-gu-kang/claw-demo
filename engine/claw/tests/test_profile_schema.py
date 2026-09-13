"""기체 문서 검증기 — 경로가 붙은 오류, 기본값 보충 없음, null은 없음 (02 §5.6)."""

import copy

import pytest

from claw.profile import ProfileError, load_example, validate_document


def _bad(mutate):
    doc = load_example()
    mutate(doc)
    with pytest.raises(ProfileError) as ei:
        validate_document(doc)
    return ei.value


def test_example_validates_and_validation_is_idempotent():
    doc = load_example()
    assert validate_document(copy.deepcopy(doc)) == doc


def test_profile_error_is_a_value_error_with_a_path():
    e = _bad(lambda d: d["mass"].__setitem__("m_empty", -1.0))
    assert isinstance(e, ValueError)
    assert e.path == "/mass/m_empty"


def test_integers_are_normalized_to_floats():
    doc = load_example()
    doc["mass"]["m_empty"] = 800
    doc["structural"]["n_limit_pos"] = 6
    out = validate_document(doc)
    assert type(out["mass"]["m_empty"]) is float and out["mass"]["m_empty"] == 800.0
    assert type(out["structural"]["n_limit_pos"]) is float


def test_missing_and_unknown_keys_are_rejected():
    assert _bad(lambda d: d.pop("mass")).path == "/mass"
    assert _bad(lambda d: d["mass"].__setitem__("extra", 1.0)).path == "/mass/extra"


@pytest.mark.parametrize("path,mutate", [
    ("/aero/coefficients/CL/0/inputs/0",
     lambda d: d["aero"]["coefficients"]["CL"][0].__setitem__("inputs", ["CL"])),
    ("/aero/coefficients/Cn/0/dispersion",
     lambda d: d["aero"]["coefficients"]["Cn"][0].__setitem__("dispersion", "cmalpha")),
    ("/aero/coefficients/Cm/2/dispersion",  # cmq 태그인데 qhat 입력이 없는 항
     lambda d: d["aero"]["coefficients"]["Cm"][2].__setitem__("dispersion", "cmq")),
    ("/stall/table/axes/mach/2",
     lambda d: d["stall"]["table"]["axes"]["mach"].__setitem__(2, 0.2)),
    ("/stall/table/extrapolate",
     lambda d: d["stall"]["table"].__setitem__("extrapolate", "linear")),
    ("/structural/mach_d", lambda d: d["structural"].__setitem__("mach_d", 0.5)),
    ("/mass/J_empty/0/1", lambda d: d["mass"]["J_empty"][0].__setitem__(1, 5.0)),
    ("/surfaces/layout", lambda d: d["surfaces"].__setitem__("layout", "canard")),
    ("/operating/alt_max", lambda d: d["operating"].update(alt_min=3000.0, alt_max=1000.0)),
    ("/ground/rail/elev_angle", lambda d: d["ground"]["rail"].__setitem__("elev_angle", 2.0)),
])
def test_domain_rules_point_at_the_field(path, mutate):
    assert _bad(mutate).path == path


def test_registry_components_require_every_parameter():
    # 기본값 보충 없음 — 빠진 파라미터는 레지스트리 기본값으로 조용히 채우지 않는다
    assert _bad(lambda d: d["propulsion"]["params"].pop("z_offset")).path \
        == "/propulsion/params/z_offset"
    assert _bad(lambda d: d["propulsion"].__setitem__("type", "Jet")).path == "/propulsion/type"
    assert _bad(lambda d: d["propulsion"]["params"].__setitem__("eta", 1.5)).path \
        == "/propulsion/params/eta"
    # 작동기 위치 한계·초기값은 문서 항목이 아니다 (surfaces·트림이 정한다)
    assert _bad(lambda d: d["actuator"]["params"].__setitem__("pos_lo", -1.0)).path \
        == "/actuator/params/pos_lo"
    assert _bad(lambda d: d["law"]["design"]["scas"]["pitch"].pop("washout_tau")).path \
        == "/law/design/scas/pitch/washout_tau"
    assert _bad(lambda d: d["law"]["design"]["scas"]["yaw"].__setitem__("out_lo", -0.3)).path \
        == "/law/design/scas/yaw/out_lo"


def test_schedule_rules():
    def no_design(d):
        d["law"]["design"] = None
    assert _bad(no_design).path == "/law/schedule"
    assert _bad(lambda d: d["law"]["schedule"]["scheduled"].__setitem__(0, "pitch.nope")).path \
        == "/law/schedule/scheduled/0"
    assert _bad(lambda d: d["law"]["schedule"]["caps"]["by_group"].__setitem__("wing", 1.0)).path \
        == "/law/schedule/caps/by_group/wing"


def test_nullable_sections_accept_null():
    doc = load_example()
    doc["structural"]["q_max"] = None
    doc["ground"] = {"skid": None, "rail": None}
    doc["aero"]["db_ranges"]["beta"] = None
    doc["law"].update(design=None, schedule=None, alloc=None)
    out = validate_document(doc)
    assert out["ground"] == {"skid": None, "rail": None}
    assert out["law"]["design"] is None
    # 필수 수치는 null이 "없음"이 아니라 오류다
    assert _bad(lambda d: d["mass"].__setitem__("fuel_max", None)).path == "/mass/fuel_max"


def test_body_form_uses_body_axis_coefficients():
    doc = load_example()
    zero = [{"k": 0.0, "inputs": [], "dispersion": None}]
    doc["aero"]["form"] = "body"
    doc["aero"]["coefficients"] = {n: copy.deepcopy(zero) for n in ("CX", "CY", "CZ", "Cl", "Cm", "Cn")}
    assert validate_document(doc)["aero"]["form"] == "body"
    doc["aero"]["coefficients"]["CX"] = [{"k": 1.0, "inputs": ["CL"], "dispersion": None}]
    with pytest.raises(ProfileError) as ei:
        validate_document(doc)
    assert ei.value.path == "/aero/coefficients/CX/0/inputs/0"


@pytest.mark.parametrize("path,mutate", [
    ("/mass/m_empty", lambda d: d["mass"].__setitem__("m_empty", True)),
    ("/mass/m_empty", lambda d: d["mass"].__setitem__("m_empty", float("nan"))),
    ("/geometry/S", lambda d: d["geometry"].__setitem__("S", float("inf"))),
    ("/mass/m_empty", lambda d: d["mass"].__setitem__("m_empty", 10 ** 400)),
    ("/actuator/params/wn", lambda d: d["actuator"]["params"].__setitem__("wn", float("nan"))),
    ("/law/design/autopilot/kp_spd",
     lambda d: d["law"]["design"]["autopilot"].__setitem__("kp_spd", float("inf"))),
    ("/propulsion/params/power_max",
     lambda d: d["propulsion"]["params"].__setitem__("power_max", 10 ** 400)),
    ("/aero/coefficients/Cm/1/dispersion",
     lambda d: d["aero"]["coefficients"]["Cm"][1].__setitem__("dispersion", [])),
    ("/aero/coefficients/CL/0/inputs/0",
     lambda d: d["aero"]["coefficients"]["CL"][0].__setitem__("inputs", [{"x": 1}])),
    ("/law/schedule/scheduled", lambda d: d["law"]["schedule"]["scheduled"].append({"x": 1})),
])
def test_malformed_values_are_profile_errors_not_crashes(path, mutate):
    # 서버에서는 ProfileError가 422가 되고, 그 밖의 예외는 500이 된다
    assert _bad(mutate).path == path


def test_ids_must_match_exactly():
    # `$`는 끝의 줄바꿈 앞에서도 맞는다 — 저장소 키가 될 id라 정확히 맞아야 한다
    assert _bad(lambda d: d.__setitem__("id", "example-delta\n")).path == "/id"
    doc = load_example()
    doc["variants"] = [{"id": "v\n", "name": "v", "patch": {}}]
    with pytest.raises(ProfileError) as ei:
        validate_document(doc)
    assert ei.value.path == "/variants/0/id"
