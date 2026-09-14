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
    ("/surfaces/elevon", lambda d: d["surfaces"].__setitem__("elevon", [-0.35, 0.0])),
    ("/surfaces/rudder", lambda d: d["surfaces"].__setitem__("rudder", [0.05, 0.35])),
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


def test_variant_count_is_capped():
    from claw.profile.schema import MAX_VARIANTS

    doc = load_example()
    doc["variants"] = [{"id": f"v{i}", "name": "v", "patch": {}} for i in range(MAX_VARIANTS + 1)]
    with pytest.raises(ProfileError) as ei:
        validate_document(doc)
    assert ei.value.path == "/variants"


def test_mission_template_is_optional_and_validated_with_paths():
    """선택 절 — 없으면 없음(null)으로 채우고, 있으면 칸마다 경로가 붙은 오류로 판정한다."""
    doc = load_example()
    del doc["mission_template"]
    assert validate_document(doc)["mission_template"] is None
    assert list(validate_document(load_example())).index("mission_template") == \
        list(validate_document(load_example())).index("law") + 1
    e = _bad(lambda d: d["mission_template"]["trim_grid"]["mach"].__setitem__("step", 0.0))
    assert e.path == "/mission_template/trim_grid/mach/step"
    e = _bad(lambda d: d["mission_template"]["envelope"]["scan_mach"].__setitem__("to", 0.1))
    assert e.path == "/mission_template/envelope/scan_mach/to"
    e = _bad(lambda d: d["mission_template"]["sim"]["approach"].__setitem__("hdot", 1.0))
    assert e.path == "/mission_template/sim/approach/hdot"
    e = _bad(lambda d: d["mission_template"]["sim"].__setitem__("extra", 1.0))
    assert e.path == "/mission_template/sim/extra"
    doc = load_example()
    doc["mission_template"]["sim"]["rollout_m"] = None  # 실측이 없는 기체
    validate_document(doc)


def test_mission_template_grids_are_capped():
    """간격 오타 하나로 수만 케이스가 되면 그 기체를 고른 화면이 격자를 만들다 멈춘다 — 경로와 함께 거부한다."""
    e = _bad(lambda d: d["mission_template"]["trim_grid"]["mach"].__setitem__("step", 0.0001))
    assert e.path == "/mission_template/trim_grid"
    e = _bad(lambda d: d["mission_template"]["envelope"]["scan_mach"].__setitem__("step", 0.0001))
    assert e.path == "/mission_template/envelope/scan_mach"
    # 비율이 inf가 되는 간격·범위 — 500(OverflowError)이 아니라 같은 경로의 거부다
    e = _bad(lambda d: d["mission_template"]["trim_grid"]["mach"].__setitem__("step", 1e-310))
    assert e.path == "/mission_template/trim_grid"

    def huge(d):
        d["mission_template"]["envelope"]["scan_mach"].update({"to": 1e308, "step": 1e-5})
    e = _bad(huge)
    assert e.path == "/mission_template/envelope/scan_mach"


def test_display_is_optional_and_takes_only_a_bare_glb_name():
    """표시 모델 — 없으면 없음(null), 있으면 형식과 경로 없는 GLB 이름만 받는다(서버가 이름으로 자산을 찾는다)."""
    doc = load_example()
    del doc["display"]
    assert validate_document(doc)["display"] is None
    order = list(validate_document(load_example()))
    assert order.index("display") == order.index("mission_template") + 1
    assert validate_document(load_example())["display"] == {"kind": "model", "model": "shahed136.glb"}
    for bad in ("", "shahed136.gltf", "../secret.glb", "models/shahed136.glb", ".glb", " shahed136.glb"):
        e = _bad(lambda d, v=bad: d["display"].__setitem__("model", v))
        assert e.path == "/display/model", bad
    e = _bad(lambda d: d["display"].__setitem__("kind", "procedural"))
    assert e.path == "/display/kind"
    e = _bad(lambda d: d["display"].__setitem__("scale", 1.0))
    assert e.path == "/display/scale"


def test_document_warns_when_the_trim_search_hides_the_low_speed_stall():
    """트림 α 탐색 상한이 실속 표 최대보다 낮으면 경고한다 — 오류가 아니라 알림이다(예제가 그렇다: 0.35 < 0.40)."""
    from claw.profile import load_example
    from claw.profile.schema import document_warnings

    doc = validate_document(load_example())
    warns = document_warnings(doc)
    assert [w["path"] for w in warns] == ["/trim/alpha_bounds/1"] and "저속 가림" in warns[0]["message"]
    doc["trim"]["alpha_bounds"] = [-0.1, 0.37]  # 판정 한계 최대 0.365 위 — 실속각 0.40 아래여도 가리는 것이 없다
    assert document_warnings(validate_document(doc)) == []
    # 형상 변형이 탐색 상한을 낮추면 그 변형만 경고한다
    doc["variants"] = [{"id": "narrow", "name": "좁은 탐색", "patch": {"/trim/alpha_bounds": [-0.1, 0.30]}}]
    warns = document_warnings(validate_document(doc))
    assert [(w["variant"], w["path"]) for w in warns] == [("narrow", "/trim/alpha_bounds/1")]
