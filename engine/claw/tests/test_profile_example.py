"""예제 기체 문서와 호환 층 — 옛 이름이 옛 **모양과 값**을 그대로 내놓는지 리터럴로 고정한다 (02 §5.6).

이관 전후 비트 동일의 독립 증거는 이관 전 HEAD에서 굳힌 골든(test_golden_profile_example.py)이다.
데모 함수가 이제 이 문서를 감싸므로 "문서 ≡ 데모 함수" 같은 비교는 실패할 수 없어 두지 않는다.
여기서는 기존 호출(테스트·대조 하네스)이 기대는 호환 층의 표면을 고정한다.
"""

import pytest

from claw.fcl.autopilot import Autopilot
from claw.profile import EXAMPLE_ID, example_profile, load_shipped_example


def test_example_identity_and_dispersion_axes():
    p = example_profile()
    assert p.id == EXAMPLE_ID and p.is_example is True
    assert p.dispersion_axes == ("mass", "cmalpha", "cmq")


def test_trim_bounds_are_the_former_module_constants():
    # 트림 모듈 상수(ALPHA_BOUNDS·DE_BOUNDS·ALPHA_MARGIN)는 프로파일로 옮겨 없어졌다 — 종전 값을 고정한다
    p = example_profile()
    assert p.trim_alpha_bounds == (-0.10, 0.35) and p.trim_alpha_margin == 0.035
    assert p.surfaces["elevon"] == (-0.35, 0.35)
    tb = p.aircraft().trim_bounds
    stall = tb.pop("stall")  # α 판정이 실속 표 기준이라 함께 싣는다 (v1.07)
    assert tb == {"alpha": (-0.10, 0.35), "de": (-0.35, 0.35), "alpha_margin": 0.035}
    assert list(stall.data) == list(p.stall_table().data)


def test_tables_are_built_fresh_each_call():
    p = example_profile()
    assert p.stall_table() is not p.stall_table()
    assert p.stall_table().data is not p.stall_table().data


def test_registry_autopilot_defaults_are_the_legacy_fixture_design():
    # 알려진 중복: Autopilot ParamDef 기본값은 구 합성 기체(회귀 픽스처 — conftest가 예제 자리에 둔다)의 설계값이다.
    # 프로파일은 기본값을 쓰지 않고 전부 명시하므로 계산에는 영향이 없다. 제품 예제(200 kg급)의 설계값은 이와 달라서,
    # 웹 폼 초기값은 레지스트리 기본값이 아니라 /gains/catalog autopilot_design(선택 기체의 설계값)에서 온다
    assert example_profile().autopilot_params() == Autopilot().cfg
    assert load_shipped_example()["law"]["design"]["autopilot"] != Autopilot().cfg


def test_legacy_constants_keep_their_old_shapes_and_values():
    from claw.fcl.demo import (DEFAULT_SCHEDULED, DEMO_ALLOC_RESV_FRAC, DEMO_ALLOC_TRIM_TABLE,
                               DEMO_ALPHA_MARGIN, DEMO_K_DIFF_THR, DEMO_PITCH, DEMO_ROLL, DEMO_YAW,
                               _F_CAP, _F_CAP_ROLL, _M_DESIGN)
    from claw.plant.demo import RAIL_ORIGIN_H, SKID_C, SKID_K, SKID_MU

    assert list(DEMO_PITCH.items()) == [("kp", -2.0), ("ki", -0.5), ("k_rate", 0.4),
                                        ("out_lo", -0.35), ("out_hi", 0.35)]
    assert list(DEMO_ROLL.items()) == [("kp", 1.0), ("ki", 0.1), ("k_rate", -0.2),
                                       ("out_lo", -0.35), ("out_hi", 0.35)]
    assert list(DEMO_YAW.items()) == [("kp", 0.5), ("ki", 0.0), ("k_rate", 0.8), ("washout_tau", 2.0),
                                      ("out_lo", -0.35), ("out_hi", 0.35)]
    assert (DEMO_K_DIFF_THR, DEMO_ALPHA_MARGIN, DEMO_ALLOC_RESV_FRAC) == (0.0, 0.05, 0.80)
    assert DEFAULT_SCHEDULED == ("pitch.kp", "pitch.ki", "pitch.k_rate",
                                 "roll.kp", "roll.ki", "roll.k_rate")
    assert (_M_DESIGN, _F_CAP, _F_CAP_ROLL) == (0.6, 2.0, 4.0)
    assert (RAIL_ORIGIN_H, SKID_K, SKID_C, SKID_MU) == (2.9, 54_000.0, 5_400.0, 0.35)
    assert callable(DEMO_ALLOC_TRIM_TABLE) and DEMO_ALLOC_TRIM_TABLE().name == "de_trim"


def test_unknown_legacy_names_raise_attribute_error():
    import claw.fcl.demo as fcl_demo
    import claw.plant.demo as plant_demo

    with pytest.raises(AttributeError):
        fcl_demo.NOPE
    with pytest.raises(AttributeError):
        plant_demo.NOPE
