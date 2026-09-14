"""예제 기체(구 데모 델타윙)의 호환 이름 — 값은 기체 프로파일 문서에 있다 (02 §5.6).

종전에는 이 모듈이 데모 기체의 공력·질량·추진·한계·지상장치를 리터럴로 들고 있었고, 서버·엔진이
그것을 직접 불러 툴 전체가 한 기체를 전제했다. 이제 값은 `claw/profile/examples/delta_demo.json`
하나에 있고, 여기 함수들은 그 문서로 조립한 객체를 돌려주는 **얇은 호환 층**이다 — 기존 호출(주로
테스트)을 그대로 두기 위해서다. 제품 코드는 `claw.profile`로 기체를 받아야 하고, 이 모듈을 import하면
가드 테스트(test_profile_guard.py)가 막는다.

수치의 근거(스키드 강성·레일 높이·추진 500 kW·DB 마하 하한·구조 한계·δe_trim 측정 절차·실속표
clip)는 02 §5.6.1로 옮겼다.
"""

from claw.plant.dispersion import DispersionSet  # noqa: F401 — 재수출 (기존 import 경로 유지)


def _example():
    # 지연 import — claw.profile의 조립기가 claw.plant 부품을 쓰므로 모듈 로드 시점에 부르면 순환한다
    from claw.profile import example_profile

    return example_profile()


def make_demo_aircraft(ground=None, dispersion: DispersionSet | None = None):
    return _example().aircraft(ground=ground, dispersion=dispersion)


def make_demo_skid_gear():
    return _example().skid_gear()


def make_demo_launch_rail():
    return _example().launch_rail()


def make_demo_db_ranges() -> dict:
    return _example().db_ranges()


def make_demo_structural_limits() -> dict:
    return _example().structural_limits()


def make_demo_trim_elevator_table():
    return _example().alloc_trim_table()


def make_demo_stall_table():
    return _example().stall_table()


_LAZY = {
    "RAIL_ORIGIN_H": lambda p: p.rail_origin_height,
    "SKID_K": lambda p: p.doc["ground"]["skid"]["k"],
    "SKID_C": lambda p: p.doc["ground"]["skid"]["c"],
    "SKID_MU": lambda p: p.doc["ground"]["skid"]["mu"],
}


def __getattr__(name):
    # 모듈 상수도 문서에서 읽는다 — import 시점에 읽으면 위 순환이 생기므로 PEP 562 지연 속성
    if name in _LAZY:
        return _LAZY[name](_example())
    raise AttributeError(f"module 'claw.plant.demo' has no attribute {name!r}")
